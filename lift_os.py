"""LIFT OS - dashboard UI (Tkinter). Run: python lift_os.py"""
from datetime import datetime
from lift_core import *  # noqa: F401,F403
from lift_core import NUM_FLOORS, C, FONT, FLOOR_NAMES, STATE_COLOR, Dir, Op, LiftController, LiftVisualization, SimulationEngine

# --------------------------------------------------------------------- view
import tkinter as tk  # noqa: E402
from tkinter import messagebox, ttk  # noqa: E402


def make_button(parent, text, command, bg=None, fg=None):
    return tk.Button(parent, text=text, command=command, bg=bg or C["card"], fg=fg or C["text"],
                     activebackground=C["accent"], activeforeground=C["text"], relief="flat",
                     bd=0, padx=12, pady=7, cursor="hand2", font=(FONT, 9, "bold"),
                     disabledforeground=C["sub"], highlightthickness=0)


class LiveMonitorView(tk.Frame):
    ROWS = [("Current floor", "floor"), ("Destination", "dest"), ("Direction", "direction"),
            ("Doors", "door"), ("Status", "state"), ("Active request", "active"),
            ("Pending requests", "pending"), ("Simulation speed", "speed")]

    def __init__(self, master, ctl, app):
        super().__init__(master, bg=C["bg"])
        self.ctl, self.app, self._seen = ctl, app, 0
        self.vals = {}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._header()
        body = tk.Frame(self, bg=C["bg"])
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=10)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=C["panel"], highlightbackground=C["border"], highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew")
        self.canvas = tk.Canvas(left, bg=C["panel"], highlightthickness=0, width=520, height=540)
        self.canvas.pack(fill="both", expand=True)
        self.viz = LiftVisualization(self.canvas, ctl)
        self._sidebar(body)
        self._controls()

    def _header(self):
        h = tk.Frame(self, bg=C["bar"], highlightbackground=C["border"], highlightthickness=1)
        h.grid(row=0, column=0, sticky="ew")
        h.columnconfigure(2, weight=1)
        tk.Label(h, text="LIFT OS", bg=C["bar"], fg=C["accent"],
                 font=(FONT, 18, "bold")).grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=8)
        tk.Label(h, text="Live Lift Monitor", bg=C["bar"], fg=C["text"],
                 font=(FONT, 13, "bold")).grid(row=0, column=1, sticky="sw")
        tk.Label(h, text="Real-Time Elevator Operations", bg=C["bar"], fg=C["sub"],
                 font=(FONT, 9)).grid(row=1, column=1, sticky="nw")
        self.clock = tk.Label(h, bg=C["bar"], fg=C["sub"], font=(FONT, 10))
        self.clock.grid(row=0, column=3, rowspan=2, padx=14)
        self.badge = tk.Label(h, font=(FONT, 9, "bold"), padx=12, pady=5, fg=C["bg"])
        self.badge.grid(row=0, column=4, rowspan=2, padx=8)
        make_button(h, "\u26A0 EMERGENCY STOP", self.app.emergency, C["bad"], C["bg"]).grid(
            row=0, column=5, rowspan=2, padx=(8, 16))

    def _card(self, parent, title):
        f = tk.Frame(parent, bg=C["card"], highlightbackground=C["border"], highlightthickness=1)
        tk.Label(f, text=title, bg=C["card"], fg=C["sub"], font=(FONT, 9, "bold")).pack(
            anchor="w", padx=12, pady=(8, 2))
        return f

    def _sidebar(self, body):
        side = tk.Frame(body, bg=C["bg"], width=330)
        side.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        side.pack_propagate(False)
        side.configure(width=330)
        card = self._card(side, "LIVE STATUS")
        card.pack(fill="x")
        for label, key in self.ROWS:
            r = tk.Frame(card, bg=C["card"])
            r.pack(fill="x", padx=12, pady=2)
            tk.Label(r, text=label, bg=C["card"], fg=C["sub"], font=(FONT, 9)).pack(side="left")
            self.vals[key] = tk.Label(r, bg=C["card"], fg=C["text"], font=(FONT, 10, "bold"))
            self.vals[key].pack(side="right")
        tk.Label(card, text="LAST EVENT", bg=C["card"], fg=C["sub"], font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(6, 0))
        self.vals["last"] = tk.Label(card, bg=C["card"], fg=C["text"], font=(FONT, 9),
                                     wraplength=290, justify="left", anchor="w")
        self.vals["last"].pack(fill="x", padx=12, pady=(0, 10))
        lc = self._card(side, "ACTIVITY LOG")
        lc.pack(fill="both", expand=True, pady=(10, 0))
        self.logbox = tk.Text(lc, bg=C["card"], fg=C["text"], bd=0, height=8, wrap="word",
                              font=("Consolas", 9), state="disabled", highlightthickness=0)
        self.logbox.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.logbox.tag_configure("ts", foreground=C["sub"])
        self.logbox.tag_configure("bad", foreground=C["bad"])
        self.logbox.tag_configure("warn", foreground=C["warn"])

    def _controls(self):
        p = tk.Frame(self, bg=C["bar"], highlightbackground=C["border"], highlightthickness=1)
        p.grid(row=2, column=0, sticky="ew")
        r1, r2 = tk.Frame(p, bg=C["bar"]), tk.Frame(p, bg=C["bar"])
        r1.pack(fill="x", padx=12, pady=(10, 4))
        r2.pack(fill="x", padx=12, pady=(0, 6))
        a = self.app.run
        floors = [f"F{n}" for n in range(1, NUM_FLOORS + 1)]
        tk.Label(r1, text="Call from", bg=C["bar"], fg=C["sub"], font=(FONT, 9)).pack(side="left")
        self.call = tk.StringVar(value="F1")
        ttk.Combobox(r1, textvariable=self.call, values=floors, width=5,
                     state="readonly").pack(side="left", padx=4)
        make_button(r1, "Call lift", lambda: a("request", int(self.call.get()[1:]), "hall"),
                    C["accent"]).pack(side="left", padx=3)
        tk.Label(r1, text="  Destination", bg=C["bar"], fg=C["sub"], font=(FONT, 9)).pack(side="left")
        self.dest = tk.StringVar(value="F1")
        ttk.Combobox(r1, textvariable=self.dest, values=floors, width=5,
                     state="readonly").pack(side="left", padx=4)
        make_button(r1, "Go", lambda: a("request", int(self.dest.get()[1:]), "dest")).pack(side="left")
        tk.Label(r1, text="   Speed", bg=C["bar"], fg=C["sub"], font=(FONT, 9)).pack(side="left")
        self.speed = tk.StringVar(value="1x")
        sp = ttk.Combobox(r1, textvariable=self.speed, values=["0.5x", "1x", "2x", "4x"],
                          width=5, state="readonly")
        sp.pack(side="left", padx=4)
        sp.bind("<<ComboboxSelected>>", lambda e: a("set_speed", float(self.speed.get()[:-1])))
        for text, cmd in (("Open doors", "open_doors"), ("Close doors", "close_doors"),
                          ("Pause", "pause"), ("Resume", "resume"), ("Reset", "reset")):
            make_button(r2, text, lambda c=cmd: a(c)).pack(side="left", padx=3)
        make_button(r2, "Emergency stop", self.app.emergency, C["bad"], C["bg"]).pack(side="left", padx=3)
        self.recover_btn = make_button(r2, "Recover", lambda: a("recover"), C["warn"], C["bg"])
        self.recover_btn.pack(side="left", padx=3)
        self.msg = tk.Label(r2, text="", bg=C["bar"], fg=C["sub"], font=(FONT, 9), anchor="w")
        self.msg.pack(side="left", padx=14, fill="x", expand=True)
        tk.Label(p, text="Simulation only \u2014 the emergency stop cannot guarantee physical elevator safety.",
                 bg=C["bar"], fg=C["sub"], font=(FONT, 8)).pack(anchor="w", padx=14, pady=(0, 6))

    def set_message(self, result):
        ok, text = result
        self.msg.configure(text=text, fg=C["sub"] if ok else C["warn"])

    def update_view(self):
        s = self.ctl.snapshot()
        col = STATE_COLOR[s["state"]]
        self.badge.configure(text=f"\u25CF {s['state'].value}", bg=col)
        d = s["direction"]
        dtxt = {Dir.UP: "\u25B2 UP", Dir.DOWN: "\u25BC DOWN", Dir.IDLE: "\u25CF IDLE"}[d]
        v = self.vals
        v["floor"].configure(text=s["location"].replace(" \u2014 ", "  "), fg=C["move"] if self.ctl.at_floor else C["warn"])
        v["dest"].configure(text="-" if s["destination"] is None else f"F{s['destination']}", fg=C["warn"])
        v["direction"].configure(text=dtxt, fg=C["ok"] if d == Dir.IDLE else C["move"])
        v["door"].configure(text=s["door"].value)
        v["state"].configure(text=s["state"].value, fg=col)
        v["active"].configure(text="-" if s["active"] is None else f"#{s['active']}")
        v["pending"].configure(text=str(s["pending"]))
        v["speed"].configure(text=f"{s['speed']:g}x")
        v["last"].configure(text=s["last_event"])
        self.recover_btn.configure(state="normal" if s["state"] == Op.EMERGENCY_STOP else "disabled")
        self._sync_log()
        self.viz.draw()

    def _sync_log(self):
        new = [e for e in self.ctl.log if e[0] > self._seen]
        if not new:
            return
        self.logbox.configure(state="normal")
        for seq, ts, msg in new:
            tag = "bad" if ("EMERGENCY" in msg or msg.startswith("Rejected")) else \
                  "warn" if "paused" in msg else ""
            self.logbox.insert("end", ts.strftime("%H:%M:%S  "), "ts")
            self.logbox.insert("end", msg + "\n", tag)
            self._seen = seq
        lines = int(self.logbox.index("end-1c").split(".")[0])
        if lines > 200:
            self.logbox.delete("1.0", f"{lines - 200}.0")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")


# ---------------------------------------------------------------------- app
class DashboardApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LIFT OS \u2014 Live Lift Monitor")
        self.geometry("1180x840")
        self.minsize(980, 720)
        self.configure(bg=C["bg"])
        self.ctl = LiftController()
        self.view = LiveMonitorView(self, self.ctl, self)
        self.view.pack(fill="both", expand=True)
        self.engine = SimulationEngine(self, self.ctl, self.view.update_view)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.view.update_view()
        self.sync()
        self._tick_clock()

    def run(self, name, *args):
        result = getattr(self.ctl, name)(*args)
        if name == "reset":
            self.engine.cancel()          # drop any stale callback
        self.view.set_message(result)
        self.sync()
        self.view.update_view()

    def emergency(self):
        if messagebox.askyesno("Emergency stop",
                               "Trigger the simulated emergency stop?\n\nSimulation only - not a physical safety system.",
                               parent=self):
            self.run("emergency_stop")

    def sync(self):
        if self.ctl.lift.state in (Op.PAUSED, Op.EMERGENCY_STOP):
            self.engine.cancel()
        else:
            self.engine.start()

    def _tick_clock(self):
        self.view.clock.configure(text=datetime.now().strftime("%a %d %b %Y   %H:%M:%S"))
        self.after(1000, self._tick_clock)

    def close(self):
        self.engine.cancel()
        self.destroy()


def main():
    DashboardApp().mainloop()


if __name__ == "__main__":
    main()
