# LIFT OS - Live Lift Monitor

15-floor lift management simulation. Python standard library only (Tkinter).

## Run
    python lift_os.py

## Test
    python -m unittest -v

## Files
- lift_core.py      models, scheduler, controller, simulation engine, canvas drawing (no Tk import)
- lift_os.py        dashboard UI and application window
- test_lift_os.py   unit tests

Note: Linux users may need `sudo apt install python3-tk`.
Simulation only - the emergency stop does not guarantee physical elevator safety.
