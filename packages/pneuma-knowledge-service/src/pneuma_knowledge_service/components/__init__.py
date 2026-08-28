"""Shipped index components — implementations of core's `IndexComponent` protocol.

Core never imports this package; `wiring.register_components` registers the ones a
deployment names in `PNEUMA_KNOWLEDGE_COMPONENTS`. A third-party component is the same
protocol in any package, registered from the application's `app.py`.
"""
