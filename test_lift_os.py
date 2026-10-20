import unittest
from lift_core import (Dir, Door, LiftController, LiftScheduler, Op, SimulationEngine,
                     Floor, level_y, shaft_box, NUM_FLOORS, FLOOR_NAMES)


def run(ctl, seconds, dt=0.05, until=None):
    trace = []
    for _ in range(int(seconds / dt)):
        ctl.tick(dt)
        trace.append((round(ctl.lift.position, 3), ctl.lift.current_floor))
        if until and until():
            break
    return trace


class FakeRoot:
    def __init__(self):
        self.jobs, self.n = {}, 0

    def after(self, ms, fn):
        self.n += 1
        self.jobs[self.n] = fn
        return self.n

    def after_cancel(self, i):
        self.jobs.pop(i, None)


class T(unittest.TestCase):
    def setUp(self):
        self.c = LiftController()

    def test_floor_positions(self):
        box = shaft_box(1000, 600)
        ys = [level_y(f, box) for f in range(1, NUM_FLOORS + 1)]
        self.assertEqual(NUM_FLOORS, 15)
        self.assertTrue(all(a > b for a, b in zip(ys, ys[1:])))
        gaps = [a - b for a, b in zip(ys, ys[1:])]
        self.assertTrue(all(abs(g - gaps[0]) < 1e-9 for g in gaps))
        self.assertTrue(box[1] < ys[-1] and ys[0] < box[3])
        self.assertEqual(FLOOR_NAMES[1], "GROUND FLOOR")
        self.assertEqual(FLOOR_NAMES[15], "FOURTEENTH FLOOR")

    def test_intermediate_positions_and_indicators(self):
        self.c.request(3, "hall")
        tr = run(self.c, 10, until=lambda: self.c.lift.door != Door.CLOSED)
        positions = {p for p, _ in tr}
        self.assertTrue(any(1.0 < p < 2.0 for p in positions))
        self.assertTrue(any(2.0 < p < 3.0 for p in positions))
        self.assertIn(2, {f for _, f in tr})
        self.assertEqual(self.c.lift.current_floor, 3)
        self.assertIn("F3", self.c.location_text())
        self.assertEqual(self.c.lift.state, Op.DOORS_OPEN)
        self.assertEqual(len(self.c.pending), 0)

    def test_fifteen_floor_trip(self):
        self.c.request(15, "hall")
        tr = run(self.c, 40, until=lambda: self.c.lift.door != Door.CLOSED)
        self.assertEqual({f for _, f in tr} >= set(range(1, 16)), True)
        self.assertEqual(self.c.lift.current_floor, 15)
        self.assertIn("F15", self.c.location_text())
        self.c.request(10, "dest")
        run(self.c, 60, until=lambda: self.c.lift.current_floor == 10)
        self.assertEqual(self.c.lift.current_floor, 10)

    def test_between_floors_text(self):
        self.c.request(2, "hall")
        run(self.c, 0.3)
        self.assertEqual(self.c.location_text(), "MOVING BETWEEN FLOORS")
        self.assertEqual(self.c.lift.direction, Dir.UP)

    def test_doors_cannot_open_while_moving(self):
        self.c.request(3)
        run(self.c, 0.3)
        ok, _ = self.c.open_doors()
        self.assertFalse(ok)
        self.assertEqual(self.c.lift.door, Door.CLOSED)

    def test_cannot_move_with_doors_open(self):
        self.assertTrue(self.c.open_doors()[0])
        run(self.c, 1.2)
        self.assertEqual(self.c.lift.door, Door.OPEN)
        self.assertFalse(self.c._start_move(3)[0])
        self.c.request(3)
        run(self.c, 0.5)                       # still dwelling, must not move
        self.assertEqual(self.c.lift.position, 1.0)
        run(self.c, 6, until=lambda: self.c.lift.state == Op.MOVING)
        self.assertEqual(self.c.lift.door, Door.CLOSED)

    def test_pause_resume(self):
        self.c.request(3)
        run(self.c, 0.5)
        self.c.pause()
        p = self.c.lift.position
        run(self.c, 1)
        self.assertEqual(self.c.lift.position, p)
        self.assertEqual(self.c.lift.state, Op.PAUSED)
        self.c.resume()
        run(self.c, 0.5)
        self.assertGreater(self.c.lift.position, p)
        self.assertEqual(self.c.lift.state, Op.MOVING)

    def test_reset_cancels_stale_callbacks(self):
        root, calls = FakeRoot(), []
        eng = SimulationEngine(root, self.c, lambda: calls.append(1))
        eng.start()
        stale = list(root.jobs.values())[0]
        self.c.request(3)
        eng.cancel()
        self.c.reset()
        stale()                                 # a stale callback must do nothing
        self.assertEqual(calls, [])
        self.assertEqual(self.c.lift.position, 1.0)
        eng.start()
        eng.start()                             # idempotent: one loop only
        self.assertEqual(len(root.jobs), 1)

    def test_emergency_stop_and_recovery(self):
        self.c.request(3)
        run(self.c, 0.8)
        self.c.emergency_stop()
        p = self.c.lift.position
        run(self.c, 1)
        self.assertEqual(self.c.lift.position, p)
        self.assertEqual(self.c.lift.state, Op.EMERGENCY_STOP)
        self.assertFalse(self.c.request(2)[0])
        self.assertFalse(self.c.open_doors()[0])
        self.assertEqual(len(self.c.pending), 1)          # history preserved
        self.assertFalse(self.c.lift.destination)
        self.assertTrue(self.c.recover()[0])
        self.assertTrue(self.c.at_floor)
        run(self.c, 10, until=lambda: self.c.lift.current_floor == 3)
        self.assertEqual(self.c.lift.current_floor, 3)

    def test_invalid_requests(self):
        for bad in (0, 16, -1, "x", None, 1.5):
            self.assertFalse(self.c.request(bad)[0], bad)
        self.assertFalse(self.c.request(2, "bogus")[0])
        self.assertTrue(self.c.request(2)[0])
        self.assertFalse(self.c.request(2)[0])            # duplicate
        self.assertFalse(self.c.request(1, "dest")[0])    # already there
        with self.assertRaises(ValueError):
            Floor(16)
        self.assertTrue(any("Rejected" in m for _, _, m in self.c.log))

    def test_scheduler_deterministic(self):
        s = LiftScheduler.next_stop
        self.assertEqual(s(2.0, Dir.IDLE, {1, 3}), 1)     # tie -> lower floor
        self.assertEqual(s(2.0, Dir.UP, {1, 3}), 3)
        self.assertEqual(s(2.0, Dir.DOWN, {1, 3}), 1)
        self.assertEqual(s(3.0, Dir.UP, {1}), 1)
        self.assertIsNone(s(1.0, Dir.IDLE, set()))

        def trace():
            c = LiftController()
            for f, k in ((3, "hall"), (2, "dest"), (1, "hall")):
                c.request(f, k)
            run(c, 40)
            return [m for _, _, m in c.log]
        self.assertEqual(trace(), trace())

    def test_stops_at_intermediate_request(self):
        self.c.request(3)
        self.c.request(2, "dest")
        tr = run(self.c, 30, until=lambda: self.c.lift.current_floor == 3)
        self.assertIn("Request #2 completed at F2", [m for _, _, m in self.c.log])

    def test_snapshot_synchronised(self):
        self.c.request(3)
        run(self.c, 0.4)
        s, l = self.c.snapshot(), self.c.lift
        self.assertEqual((s["state"], s["floor"], s["destination"], s["direction"], s["door"]),
                         (l.state, l.current_floor, l.destination, l.direction, l.door))
        self.assertEqual(s["pending"], len(self.c.pending))
        self.assertEqual(s["active"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
