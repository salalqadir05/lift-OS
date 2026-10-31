"""LIFT OS core: models, scheduler, controller, engine, canvas drawing (no Tk import needed).

Layers: Floor/Lift/LiftRequest (models) -> LiftScheduler -> LiftController (single
source of truth) -> SimulationEngine (after()-based timer) -> LiftVisualization /
LiveMonitorView (presentation only) -> DashboardApp.
Simulation only: the emergency stop does not guarantee physical elevator safety.
"""
import heapq
import itertools
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

C = dict(bg="#0B1120", bar="#111827", panel="#151F32", card="#1B2940", accent="#6366F1",
         move="#38BDF8", ok="#34D399", warn="#FBBF24", bad="#F87171", text="#F1F5F9",
         sub="#94A3B8", border="#2A3850")
FONT = "Segoe UI"
NUM_FLOORS = 15
_ORD = ["FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH", "EIGHTH", "NINTH",
        "TENTH", "ELEVENTH", "TWELFTH", "THIRTEENTH", "FOURTEENTH"]
_ORD11 = ["FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH", "EIGHTH", "NINTH",
        "TENTH", "ELEVENTH", "TWELFTH", "THIRTEENTH", "FOURTEENTH"]
FLOOR_NAMES = {1: "GROUND FLOOR", **{n: f"{_ORD[n - 2]} FLOOR" for n in range(2, NUM_FLOORS + 1)}}


# ----------------------------------------------------------------- models
@dataclass(frozen=True)
class Floor:
    number: int

    def __post_init__(self):
        if isinstance(self.number, bool) or self.number not in FLOOR_NAMES:
            raise ValueError(f"Invalid floor: {self.number!r} (valid: 1-3)")

    @property
    def name(self):
        return FLOOR_NAMES[self.number]


class Op(Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    DOORS_OPEN = "DOORS_OPEN"
    PAUSED = "PAUSED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class Dir(Enum):
    UP = "UP"
    DOWN = "DOWN"
    IDLE = "IDLE"


class Door(Enum):
    CLOSED = "CLOSED"
    OPENING = "OPENING"
    OPEN = "OPEN"
    CLOSING = "CLOSING"


@dataclass
class Lift:
    position: float = 1.0           # continuous floor coordinate (1.0 .. 15.0)
    current_floor: int = 1          # last floor reached
    direction: Dir = Dir.IDLE
    door: Door = Door.CLOSED
    door_pos: float = 0.0           # 0 closed .. 1 open
    state: Op = Op.IDLE
    destination: Optional[int] = None
    prev_state: Op = Op.IDLE
    dwell: float = 0.0


@dataclass
class LiftRequest:
    id: int
    floor: int
    kind: str                       # "hall" | "dest"
    created: datetime = field(default_factory=datetime.now)
    status: str = "PENDING"         # PENDING -> DONE


# -------------------------------------------------------------- scheduler
class LiftScheduler:
    """Deterministic SCAN-style policy: keep going in the current direction while
    stops remain ahead, otherwise take the nearest stop (ties -> lower floor)."""

    @staticmethod
    def next_stop(position, direction, floors):
        if not floors:
            return None
        eps = 1e-9
        heap = []
        for f in floors:
            ahead = (direction == Dir.UP and f >= position - eps) or \
                    (direction == Dir.DOWN and f <= position + eps)
            rank = 0 if (direction == Dir.IDLE or ahead) else 1
            heapq.heappush(heap, (rank, abs(f - position), f))
        return heap[0][2]


# ------------------------------------------------------------- controller
class LiftController:
    BASE_SPEED = 1.2     # floors per second at 1x
    DOOR_TIME = 0.9      # seconds for a full door travel at 1x
    DWELL = 2.0          # seconds doors stay open before auto-closing

    def __init__(self, speed=1.0):
        self.speed = speed
        self.scheduler = LiftScheduler()
        self.log = deque(maxlen=200)
        self._seq = 0
        self._ids = itertools.count(1)
        self.generation = 0
        self._init_state()

    def _init_state(self):
        self.lift = Lift()
        self.pending = {}            # id -> LiftRequest
        self.queue = deque()         # FIFO order of pending ids
        self.generation += 1

    # -- helpers
    def _log(self, msg):
        self._seq += 1
        self.log.append((self._seq, datetime.now(), msg))

    def _reject(self, msg):
        self._log(f"Rejected: {msg}")
        return False, msg

    def _blocked(self):
        s = self.lift.state
        if s == Op.EMERGENCY_STOP:
            return "Emergency stop active - recovery required"
        if s == Op.OUT_OF_SERVICE:
            return "Lift is out of service"
        return None

    @property
    def at_floor(self):
        return abs(self.lift.position - round(self.lift.position)) < 1e-6

    def pending_floors(self):
        return {r.floor for r in self.pending.values()}

    def active_request(self):
        d = self.lift.destination
        for rid in self.queue:
            if self.pending[rid].floor == d:
                return self.pending[rid]
        return None

    def location_text(self):
        if not self.at_floor:
            return "MOVING BETWEEN FLOORS"
        n = int(round(self.lift.position))
        return f"F{n} \u2014 {FLOOR_NAMES[n]}"

    def snapshot(self):
        l, a = self.lift, self.active_request()
        return dict(state=l.state, floor=l.current_floor, destination=l.destination,
                    direction=l.direction, door=l.door, active=a.id if a else None,
                    pending=len(self.pending), speed=self.speed,
                    location=self.location_text(),
                    last_event=self.log[-1][2] if self.log else "-")

    # -- commands
    def request(self, floor, kind="hall"):
        try:
            f = Floor(floor).number
        except (ValueError, TypeError):
            return self._reject(f"Invalid floor {floor!r}")
        if kind not in ("hall", "dest"):
            return self._reject(f"Unknown request type {kind!r}")
        if (b := self._blocked()):
            return self._reject(b)
        if any(r.floor == f and r.kind == kind for r in self.pending.values()):
            return self._reject(f"Duplicate {kind} request for F{f}")
        l = self.lift
        if kind == "dest" and l.state == Op.IDLE and self.at_floor and l.current_floor == f:
            return self._reject(f"Lift is already at F{f}")
        r = LiftRequest(next(self._ids), f, kind)
        self.pending[r.id] = r
        self.queue.append(r.id)
        label = "Hall call" if kind == "hall" else "Destination"
        self._log(f"Request #{r.id} received: {label} F{f}")
        return True, f"Request #{r.id} accepted ({label} F{f})"

    def open_doors(self):
        l = self.lift
        if (b := self._blocked()):
            return self._reject(b)
        if l.state == Op.PAUSED:
            return self._reject("Simulation is paused")
        if l.state == Op.MOVING or not self.at_floor:
            return self._reject("Doors cannot open while the cabin is moving")
        if l.door in (Door.OPEN, Door.OPENING):
            return self._reject("Doors are already open")
        if l.door == Door.CLOSING:
            return self._reject("Doors are closing - wait until closed")
        l.door, l.state, l.dwell = Door.OPENING, Op.DOORS_OPEN, self.DWELL
        self._log("Doors opening")
        return True, "Doors opening"

    def close_doors(self):
        l = self.lift
        if (b := self._blocked()):
            return self._reject(b)
        if l.state == Op.PAUSED:
            return self._reject("Simulation is paused")
        if l.door == Door.OPENING:
            return self._reject("Doors are still opening - wait until open")
        if l.door in (Door.CLOSED, Door.CLOSING):
            return self._reject("Doors are already closed")
        l.door = Door.CLOSING
        self._log("Doors closing")
        return True, "Doors closing"

    def pause(self):
        l = self.lift
        if l.state in (Op.PAUSED, Op.EMERGENCY_STOP, Op.OUT_OF_SERVICE):
            return self._reject("Cannot pause in the current state")
        l.prev_state, l.state = l.state, Op.PAUSED
        self._log("Simulation paused")
        return True, "Simulation paused"

    def resume(self):
        l = self.lift
        if l.state != Op.PAUSED:
            return self._reject("Simulation is not paused")
        l.state = l.prev_state
        self._log("Simulation resumed")
        return True, "Simulation resumed"

    def emergency_stop(self):
        l = self.lift
        if l.state == Op.EMERGENCY_STOP:
            return self._reject("Emergency stop already active")
        l.state, l.direction, l.destination = Op.EMERGENCY_STOP, Dir.IDLE, None
        self.generation += 1   # invalidates in-flight animation callbacks
        self._log(f"EMERGENCY STOP activated ({self.location_text()})")
        return True, "EMERGENCY STOP - simulation only, not a physical safety system"

    def recover(self):
        """Policy: re-home to the nearest floor, keep pending requests, then let
        the scheduler decide. Interrupted movement is never auto-continued."""
        l = self.lift
        if l.state != Op.EMERGENCY_STOP:
            return self._reject("No emergency to recover from")
        l.current_floor = min(NUM_FLOORS, max(1, int(math.floor(l.position + 0.5))))
        l.position = float(l.current_floor)
        l.state = Op.IDLE if l.door == Door.CLOSED else Op.DOORS_OPEN
        self.generation += 1
        self._log(f"Recovered: re-homed to F{l.current_floor}; pending requests kept")
        return True, f"Recovered at F{l.current_floor}"

    def reset(self):
        self._init_state()
        self._log("Simulation reset")
        return True, "Simulation reset"

    def set_speed(self, value):
        if not 0.25 <= value <= 4:
            return self._reject("Speed must be between 0.25x and 4x")
        self.speed = float(value)
        return True, f"Speed {value:g}x"

    # -- simulation step (pure, testable without Tk)
    def tick(self, dt):
        l = self.lift
        if l.state in (Op.PAUSED, Op.EMERGENCY_STOP, Op.OUT_OF_SERVICE):
            return
        dt *= self.speed
        if l.door in (Door.OPENING, Door.CLOSING):
            self._tick_doors(dt)
        elif l.door == Door.OPEN:
            l.dwell -= dt
            if l.dwell <= 0:
                self.close_doors()
        elif l.state == Op.MOVING:
            self._tick_move(dt)
        else:
            self._dispatch()

    def _tick_doors(self, dt):
        l = self.lift
        if l.door == Door.OPENING:
            l.door_pos = min(1.0, l.door_pos + dt / self.DOOR_TIME)
            if l.door_pos >= 1.0:
                l.door, l.dwell = Door.OPEN, self.DWELL
                self._log("Doors opened")
        else:
            l.door_pos = max(0.0, l.door_pos - dt / self.DOOR_TIME)
            if l.door_pos <= 0.0:
                l.door, l.state = Door.CLOSED, Op.IDLE
                self._log("Doors closed")

    def _dispatch(self):
        l = self.lift
        target = self.scheduler.next_stop(l.position, l.direction, self.pending_floors())
        if target is None:
            l.direction = Dir.IDLE
        elif target == l.current_floor and self.at_floor:
            self._arrive(target)
        else:
            self._start_move(target)

    def _start_move(self, target):
        l = self.lift
        if l.door != Door.CLOSED:
            return self._reject("Doors must be fully closed before moving")
        if (b := self._blocked()) or l.state == Op.PAUSED:
            return self._reject(b or "Simulation is paused")
        l.destination = target
        l.direction = Dir.UP if target > l.position else Dir.DOWN
        l.state = Op.MOVING
        self._log(f"Movement started: F{l.current_floor} \u2192 F{target}")
        return True, "Moving"

    def _tick_move(self, dt):
        l = self.lift
        step = self.BASE_SPEED * dt
        sign = 1 if l.direction == Dir.UP else -1
        nxt = (math.floor(l.position + 1e-9) + 1) if sign > 0 else (math.ceil(l.position - 1e-9) - 1)
        if abs(nxt - l.position) <= step + 1e-9:
            l.position, l.current_floor = float(nxt), nxt
            self._log(f"Floor reached: F{nxt}")
            tgt = self.scheduler.next_stop(nxt, l.direction, self.pending_floors())
            if tgt == nxt:
                self._arrive(nxt)
            elif tgt is None:
                l.state, l.direction, l.destination = Op.IDLE, Dir.IDLE, None
            else:
                l.destination = tgt
                l.direction = Dir.UP if tgt > nxt else Dir.DOWN
        else:
            l.position += sign * step

    def _arrive(self, floor):
        l = self.lift
        l.position, l.current_floor = float(floor), floor
        l.direction, l.destination = Dir.IDLE, None
        for rid in [i for i in self.queue if self.pending[i].floor == floor]:
            self.pending.pop(rid).status = "DONE"
            self.queue.remove(rid)
            self._log(f"Request #{rid} completed at F{floor}")
        l.door, l.state, l.dwell = Door.OPENING, Op.DOORS_OPEN, self.DWELL
        self._log("Doors opening")


# ------------------------------------------------------ simulation engine
class SimulationEngine:
    """One after()-loop at a time; a token invalidates stale callbacks."""

    def __init__(self, root, controller, on_update, interval_ms=30):
        self.root, self.ctl, self.on_update, self.interval = root, controller, on_update, interval_ms
        self._job, self._token, self._last = None, 0, 0.0

    @property
    def running(self):
        return self._job is not None

    def start(self):
        if self._job is not None:
            return
        self._token += 1
        self._last = time.monotonic()
        self._schedule(self._token)

    def cancel(self):
        if self._job is not None:
            self.root.after_cancel(self._job)
            self._job = None
        self._token += 1

    def _schedule(self, tok):
        self._job = self.root.after(self.interval, lambda: self._step(tok))

    def _step(self, tok):
        if tok != self._token:
            return
        self._job = None
        now = time.monotonic()
        dt, self._last = min(now - self._last, 0.1), now
        self.ctl.tick(dt)
        self.on_update()
        if tok == self._token and self.ctl.lift.state not in (Op.PAUSED, Op.EMERGENCY_STOP):
            self._schedule(tok)


# ------------------------------------------------------------ visualization
def shaft_box(w, h):
    sw = min(w * 0.30, 200)
    x0 = (w - sw) / 2
    return (x0, 30, x0 + sw, max(h - 30, 60))


def level_y(position, box):
    """Vertical centre of the cabin for a (possibly fractional) floor position."""
    _, y0, _, y1 = box
    return y1 - (position - 0.5) * (y1 - y0) / NUM_FLOORS


STATE_COLOR = {Op.IDLE: C["ok"], Op.MOVING: C["move"], Op.DOORS_OPEN: C["ok"],
               Op.PAUSED: C["warn"], Op.OUT_OF_SERVICE: C["bad"], Op.EMERGENCY_STOP: C["bad"]}


class LiftVisualization:
    def __init__(self, canvas, ctl):
        self.c, self.ctl = canvas, ctl
        canvas.bind("<Configure>", lambda e: self.draw())

    def draw(self):
        c, ctl, l = self.c, self.ctl, self.ctl.lift
        w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 300)
        c.delete("all")
        box = shaft_box(w, h)
        x0, y0, x1, y1 = box
        bh = (y1 - y0) / NUM_FLOORS
        fs = max(7, min(11, int(bh * 0.33)))
        c.create_rectangle(x0, y0, x1, y1, fill="#0E1626", outline=C["border"], width=2)
        pend = ctl.pending_floors()
        for f in range(NUM_FLOORS, 0, -1):
            yc = level_y(f, box)
            here = ctl.at_floor and l.current_floor == f
            col = C["move"] if here else C["sub"]
            c.create_text(x0 - 22, yc, text=f"F{f}  {FLOOR_NAMES[f]}", anchor="e", fill=col,
                          font=(FONT, fs, "bold" if here else "normal"))
            c.create_oval(x0 - 15, yc - 4, x0 - 7, yc + 4, outline=col,
                          fill=col if here else C["bg"], width=2)
            if l.destination == f:
                c.create_text(x1 + 12, yc, text="\u25C4 DEST", anchor="w", fill=C["warn"],
                              font=(FONT, fs, "bold"))
            elif f in pend:
                c.create_text(x1 + 12, yc, text="\u25CF CALL", anchor="w", fill=C["sub"],
                              font=(FONT, fs))
        for i in range(NUM_FLOORS + 1):
            y = y0 + i * bh
            c.create_line(x0 - 6, y, x1 + 6, y, fill=C["border"],
                          width=2 if i in (0, NUM_FLOORS) else 1)
        # cabin (compact layout when floors are short)
        ch = bh * 0.84
        big = ch >= 70
        cw = min((x1 - x0) * 0.7, max(ch * 2.2, 60))
        cx, cy = (x0 + x1) / 2, level_y(l.position, box)
        col = STATE_COLOR[l.state]
        pad = 8 if big else 2
        dh = ch * 0.2 if big else max(9, ch * 0.32)
        c.create_rectangle(cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2,
                           fill=C["card"], outline=col, width=3 if big else 2)
        c.create_rectangle(cx - cw / 2 + pad, cy - ch / 2 + pad, cx + cw / 2 - pad,
                           cy - ch / 2 + pad + dh, fill=C["bg"], outline=C["border"])
        arrow = {Dir.UP: "\u25B2", Dir.DOWN: "\u25BC", Dir.IDLE: "\u25CF"}[l.direction]
        c.create_text(cx, cy - ch / 2 + pad + dh / 2, text=f"F{l.current_floor}  {arrow}",
                      fill=col, font=(FONT, max(7, int(dh * (0.5 if big else 0.62))), "bold"))
        ax0, ax1 = cx - cw / 2 + pad, cx + cw / 2 - pad
        ay0 = cy - ch / 2 + 2 * pad + dh
        ay1 = cy + ch / 2 - (22 if big else pad)
        c.create_rectangle(ax0, ay0, ax1, ay1, fill="#3A4A68", outline=C["border"])
        half, off = (ax1 - ax0) / 2, l.door_pos * (ax1 - ax0) / 2
        for a, b in ((max(ax0, ax0 - off), ax0 + half - off), (ax0 + half + off, ax1)):
            if b > a + 0.5:
                c.create_rectangle(a, ay0, b, ay1, fill="#5B6F94", outline=C["bg"],
                                   width=2 if big else 1)
        if big:
            c.create_text(cx, cy + ch / 2 - 11, text=f"DOORS {l.door.value}", fill=col,
                          font=(FONT, max(7, int(dh * 0.33)), "bold"))
        c.create_text(w / 2, y1 + 15, text=f"{ctl.location_text()}   |   DOORS {l.door.value}",
                      fill=col, font=(FONT, 10, "bold"))
        if l.state == Op.EMERGENCY_STOP:
            c.create_text(w / 2, 14, text="\u26A0 EMERGENCY STOP \u2014 SIMULATION ONLY",
                          fill=C["bad"], font=(FONT, 12, "bold"))
