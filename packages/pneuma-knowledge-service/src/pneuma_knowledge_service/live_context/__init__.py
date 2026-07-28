"""Live Context service layer: session policy and per-evaluation runner.

`session.py` is pure and clock-injected (no I/O, no awaits); `engine.py` is the thin
I/O half that binds a plan to the core engine and the app's ports.
"""
