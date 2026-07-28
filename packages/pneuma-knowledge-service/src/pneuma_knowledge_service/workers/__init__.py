"""Background worker: consumes the PG task queue, per-user serial (ADR-001, §5).

Dispatches by job kind — `index` (L1 lexical + L2 chunking/embedding) and `compile`
(L3 canonical). Self-heals stale `claimed` jobs on startup. See compile_worker.py.
"""
