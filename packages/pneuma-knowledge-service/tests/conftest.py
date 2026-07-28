"""Pin the whole service test session to keyless, deterministic middleware.

The running app's `.env` selects real providers (openai embeddings, semantic chunking via
remote provider models) — right for production, wrong for tests: it would make the suite hit the network,
cost money, and contend with a live instance. In pydantic-settings, process env vars take
precedence over the `.env` file, so setting them here at collection time (before any
`Settings()` is constructed) forces tests onto the fake embedding + mechanical sentence
chunker regardless of what `.env` says.
"""

import os

# The middleware under test is on localhost, but httpx defaults to trust_env=True and on
# macOS `urllib.request.getproxies()` reads the SYSTEM proxy config — so a machine running a
# global proxy (Surge/Clash et al) tunnels even 127.0.0.1:7700 through it. The integration
# fixtures then fail inside httpcore's http_proxy path with a stack trace that names neither
# the proxy nor the port, so it reads as "Meili/Qdrant is broken". Pin the bypass here, with
# the rest of the ambient-environment isolation.
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

os.environ["PNEUMA_KNOWLEDGE_EMBEDDING_MODEL"] = "fake:384"
os.environ["PNEUMA_KNOWLEDGE_CHUNK_STRATEGY"] = "sentence"
# Model routing must come from each test's own Settings(...) arguments, not from a local
# `.env` that points ops at real models — a dev box with PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE set
# would otherwise fail the routing assertions (resolve_model_name == the test's fallback).
for _routing_var in (
    "PNEUMA_KNOWLEDGE_LLM_MODEL",
    "PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE",
    "PNEUMA_KNOWLEDGE_LLM_MODEL_RECALL",
    "PNEUMA_KNOWLEDGE_LLM_MODEL_DEEP",
    "PNEUMA_KNOWLEDGE_LLM_MODEL_SKILL",
    "PNEUMA_KNOWLEDGE_LLM_MODEL_CUE",
):
    os.environ[_routing_var] = ""
# Isolated Qdrant collection: a collection has one fixed vector dim, so the fake:384 tests
# must not share the app's real-embedding collection (e.g. 1536-dim openai) or every upsert
# hits a dim mismatch.
os.environ["PNEUMA_KNOWLEDGE_QDRANT_COLLECTION"] = "pneuma_knowledge_chunks_test"
