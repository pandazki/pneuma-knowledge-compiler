"""Service settings — 12-factor, all via environment (architecture.md §1, §5).

Env prefix: PNEUMA_KNOWLEDGE_. e.g. PNEUMA_KNOWLEDGE_PG_DSN, PNEUMA_KNOWLEDGE_QDRANT_URL.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": a 12-factor service must tolerate unrelated env / .env vars
    # (deploy secrets, other services' keys) rather than crash on the first stray key.
    model_config = SettingsConfigDict(
        env_prefix="PNEUMA_KNOWLEDGE_", env_file=".env", extra="ignore"
    )

    pg_dsn: str = "postgresql://pneuma_knowledge:pneuma_knowledge@localhost:15432/pneuma_knowledge"
    qdrant_url: str = "http://localhost:16333"
    # The Qdrant collection holding L2 chunk vectors. A single collection has one fixed
    # vector dim, so the test suite (fake:384) must NOT share the app's collection when the
    # app runs a real embedding of a different dim — tests set PNEUMA_KNOWLEDGE_QDRANT_COLLECTION to an
    # isolated name (see tests/conftest.py).
    qdrant_collection: str = "pneuma_knowledge_chunks"
    meili_url: str = "http://localhost:17700"
    # Matches the compose default (docker-compose.yml MEILI_MASTER_KEY fallback);
    # override via PNEUMA_KNOWLEDGE_MEILI_KEY in any real deployment.
    meili_key: str = "masterKey_change_me"

    canonical_root: str = "./data/canonical"

    # L2 chunking. `sentence` = chonkie SentenceChunker with CJK-aware delimiters and
    # real overlap (shipped default); `recursive` = chonkie RecursiveChunker for
    # structure-heavy docs. `semantic` = configured LLM topic/entity boundary detection over
    # the numbered blocks (ideally one topic/one person = one chunk) with a sentence
    # chunker sub-splitting any over-long unit — opt-in via PNEUMA_KNOWLEDGE_CHUNK_STRATEGY=semantic;
    # only actual L2 ingest calls the LLM (preview stays mechanical). See ingest/semantic.py.
    # chonkie counts in tokens; its default character tokenizer is ~1 token/char for CJK,
    # so chunk_size 768 ≈ the prior ~800-char sizing. See ingest/chunking.py.
    chunk_strategy: str = "sentence"
    chunk_size: int = 768
    chunk_overlap: int = 128

    # First-party context_stream preprocessing switches. Role rendering and compile
    # guidance are independent because deployments may want raw speaker labels, generic
    # compile behavior, or both. Toggling is per-stage: rendering is applied at ingest
    # (affects new sources), guidance at compile (affects the next compile).
    #   render_roles     — render self/others as owner/participant labels at ingest (ELSE
    #                      plain verbatim)
    #   compile_guidance — inject the per-type data+app context into compile (ELSE none)
    context_stream_render_roles: bool = True
    context_stream_compile_guidance: bool = True

    # Briefing consumption (the ask) is fast-lane: alias real source ids to short
    # query-local `sNN` handles for the answer's citations (one SessionAliaser per ask), so
    # the model copies short handles the UI reverse-binds — like fast. Default on; turn off
    # to keep the briefing pack's byte-stable prompt-cache (aliasing rewrites it per ask).
    # Fast always aliases; deep never does (its agentic loop would relabel a source across
    # rounds). PNEUMA_KNOWLEDGE_BRIEFING_CITATION_ALIAS=false to disable.
    briefing_citation_alias: bool = True

    # Per-user schema packs (schema-evolve M1). When on, each user's compile skill is the
    # base version composed with their registration-derived SchemaPacks (matrix + optional
    # LLM derive), persisted in their canonical repo's skill/manifest.json and loaded
    # per-job. Off → every user compiles with the bare base version (no packs, no manifest).
    #   user_schema_packs        — master switch for per-user schema composition
    #   user_schema_base_version — the built-in skill version packs compose onto. Decoupled
    #     from load_builtin_skill()'s "v1" default so the base can advance (→ "v3") without
    #     touching existing callers; flip this knob, not the loader default.
    user_schema_packs: bool = True
    user_schema_base_version: str = "v3"
    # Path to a deployment-supplied pack matrix (the JSON asset packs_for_profile reads on
    # the first-compile auto-resolution path). None → the packaged built-in matrix. This is
    # the prose seam for branch-3 skill materialization: without it a deployment could only
    # replace the built-in pack wording by pre-writing a full manifest (branch 2), which
    # REPLACES auto-resolution instead of layering on it.
    user_schema_matrix_path: str | None = None

    # Schema evolve (schema-evolve §2). The whole-KB reorganization flow: a strong model
    # proposes new schema families off accrued compile evidence, an agentic pass reorganizes
    # the KB onto an evolve/<task> branch, and a human adopts/drops within a review window.
    #   evolve_auto_trigger      — master switch for the passive (post-compile) trigger
    #   evolve_trigger_topic_docs — new memory/topics/ docs since the last evolve to fire
    #   evolve_trigger_new_claims — new anchors since the last evolve to fire (AND with above)
    #   evolve_draft_ttl_hours    — a draft older than this is lazily expired (auto-dropped)
    evolve_auto_trigger: bool = True
    evolve_trigger_topic_docs: int = 5
    evolve_trigger_new_claims: int = 30
    evolve_draft_ttl_hours: float = 24.0

    # Dev CORS: allow the vite dev server (any localhost/127.0.0.1 port) to call
    # the API from the browser. Override PNEUMA_KNOWLEDGE_CORS_ALLOW_ORIGIN_REGEX in real
    # deployments; set to "" to disable CORS entirely.
    cors_allow_origin_regex: str = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

    # Default / fallback chat model. Per-operation routing below overrides it when set.
    llm_model: str = "openai:gpt-4o-mini"
    # Per-operation model routing (PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE / _RECALL / _DEEP / _SKILL).
    # Empty → falls back to llm_model, so scripted-model tests (which set llm_model only)
    # keep routing everything to the scripted model. See docs/observability.md.
    llm_model_compile: str = ""  # compile agent
    llm_model_recall: str = ""  # fast recall + briefing ask
    llm_model_deep: str = ""  # deep recall (agentic search)
    llm_model_skill: str = ""  # skill synthesis (future)
    llm_model_evolve: str = ""  # schema evolve (phase-1 propose + phase-2 reorganize)
    # Live Context evaluation + its want_more expansion. Empty falls back to
    # llm_model_recall BEFORE llm_model (see wiring._ROLE_FALLBACK): an evaluation is
    # single-shot, latency-shaped call with the same appetite as fast recall, so a
    # deployment that already pointed recall at a fast model should not have to say so
    # twice. Set PNEUMA_KNOWLEDGE_LLM_MODEL_LIVE_CONTEXT to split them.
    llm_model_live_context: str = ""
    # OpenRouter (OpenAI-compatible) key, read from the unprefixed OPENROUTER_API_KEY
    # so `openrouter:<model>` in llm_model can switch vendors without app changes.
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    # fake:<dim> = DeterministicFakeEmbedding (keyless; tests/example default, §M1.3).
    embedding_model: str = "fake:384"

    # Langfuse tracing (observability). Read from the unprefixed LANGFUSE_* env (same
    # convention as OPENROUTER_API_KEY) so the local Langfuse project's own variable
    # names work verbatim. All three default empty → tracing degrades to a no-op
    # (wiring.build_langfuse_handler returns None; every LLM call runs callbacks-free).
    # See docs/observability.md.
    langfuse_secret_key: str = Field(default="", validation_alias="LANGFUSE_SECRET_KEY")
    langfuse_public_key: str = Field(default="", validation_alias="LANGFUSE_PUBLIC_KEY")
    langfuse_base_url: str = Field(default="", validation_alias="LANGFUSE_BASE_URL")


def get_settings() -> Settings:
    return Settings()
