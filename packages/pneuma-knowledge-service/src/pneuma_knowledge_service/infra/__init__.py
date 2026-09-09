"""What an application needs to stand this engine's middleware up on one machine.

Not part of the engine: nothing here is imported by the API, the worker or the adapters.
It is the shared answer to a question every application shape asks — which ports are free,
which subnet is free, and what the four-service compose file looks like — kept in the
library so the scaffold's generated project and the personal edition describe the same
stack instead of two drifting copies of it.

Standard library only, deliberately: `ports` is read by the scaffold's generator, which
runs before any environment exists.
"""
