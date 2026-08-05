"""Service settings — 12-factor, all via environment (architecture.md §1, §5).

Env prefix: PNEUMA_KNOWLEDGE_. e.g. PNEUMA_KNOWLEDGE_PG_DSN, PNEUMA_KNOWLEDGE_QDRANT_URL.
"""

from __future__ import annotations

from typing import Literal

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

    # The timezone this installation counts calendar days in for a subject whose profile does
    # not state one — the last link of `domain.time_context.resolve_zone_with_source`
    # (provider → profile → this). UTC is the only defensible default for a library; a
    # deployment serving one region should say so (PNEUMA_KNOWLEDGE_DEFAULT_TIMEZONE=Asia/Shanghai),
    # because "UTC" for a subject who lives at +08:00 files a third of their evenings on the
    # wrong day. It is never presented as the subject's own setting: the compile contract
    # declares it as this deployment's default (compile.owner_env.timezone_default).
    default_timezone: str = "UTC"

    # L2 chunking. `semantic` (shipped default) = configured LLM topic/entity boundary
    # detection over the numbered blocks (ideally one topic/one person = one chunk),
    # inspired by nemori's boundary-detection philosophy (https://github.com/nemori-ai/nemori)
    # but returning block indexes only — chunk text stays a verbatim slice of the source.
    # A sentence chunker sub-splits over-long units; only actual L2 ingest calls the LLM
    # (preview stays mechanical), and scripted/keyless base models automatically fall back
    # to mechanical sentence chunking (see wiring). See ingest/semantic.py.
    # Mechanical opt-outs: `sentence` = chonkie SentenceChunker with CJK-aware delimiters
    # and real overlap; `recursive` = chonkie RecursiveChunker for structure-heavy docs.
    # chonkie counts in tokens; its default character tokenizer is ~1 token/char for CJK,
    # so chunk_size 768 ≈ the prior ~800-char sizing. See ingest/chunking.py.
    chunk_strategy: str = "semantic"
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
    #   user_schema_base_version — which registered skill base packs compose onto. NO
    #     DEFAULT, deliberately: it used to default to "v3", which meant a deployment that
    #     never chose a contract silently compiled everyone's knowledge against the
    #     personal-knowledge contract this project happened to develop for itself. The
    #     framework has no domain opinion to fall back on, so a deployment states the
    #     version string it registered with `register_skill_base` — and leaving it blank
    #     fails loudly at the first compile, naming the format doc and the shipped
    #     reference contracts, rather than producing someone else's knowledge base.
    user_schema_packs: bool = True
    user_schema_base_version: str = ""
    # Path to a deployment-supplied pack matrix (the JSON asset packs_for_profile reads on
    # the first-compile auto-resolution path). None → the packaged built-in matrix. This is
    # the prose seam for branch-3 skill materialization: without it a deployment could only
    # replace the built-in pack wording by pre-writing a full manifest (branch 2), which
    # REPLACES auto-resolution instead of layering on it.
    user_schema_matrix_path: str | None = None

    # OpenRouter provider routing pin, applied to every `openrouter:<model>` chat spec.
    # Empty = OpenRouter's own routing. A comma list (e.g. "openai") restricts serving to
    # those upstream providers; with allow_fallbacks=False the request fails rather than
    # silently landing on a third-party reseller of the same model.
    openrouter_provider_order: str = ""
    openrouter_allow_fallbacks: bool = False

    # Post-compile coverage challenge (opt-in): blind question generation over the just-
    # compiled material, claim-face probing, and one compensation compile for confirmed
    # gaps. Mechanizes the acceptance loop's "ask real questions" step
    # (docs/guides/compile-contract.md §5). Off by default: it spends extra model calls
    # per compile job.
    # Model role for the challenge's question generation and reflection; empty borrows
    # the compile role (same material, same judgement register). One hop, like evolve.
    llm_model_challenge: str = ""
    challenge_enabled: bool = False
    challenge_max_rounds: int = 2
    challenge_max_questions: int = 6
    challenge_compensate: bool = True

    # Schema evolve (schema-evolve §2). The whole-KB reorganization flow: a strong model
    # proposes new schema families off accrued compile evidence, an agentic pass reorganizes
    # the KB onto an evolve/<task> branch, and a human adopts/drops within a review window.
    #   evolve_auto_trigger      — master switch for the passive (post-compile) trigger
    #   evolve_trigger_topic_docs — new docs (ANY family, not just memory/topics/ — evolve
    #                               examines whole-KB growth) since the last evolve to fire;
    #                               name kept for config compatibility
    #   evolve_trigger_new_claims — new anchors since the last evolve to fire (AND with above)
    #   evolve_draft_ttl_hours    — a draft older than this is lazily expired (auto-dropped)
    evolve_auto_trigger: bool = True
    evolve_trigger_topic_docs: int = 5
    evolve_trigger_new_claims: int = 30
    evolve_draft_ttl_hours: float = 24.0

    # Document rollover (the `groom` job kind). A canonical document about one long-lived
    # subject accretes claims for as long as that subject stays alive, and past a point it
    # stops being usable AS canonical: a full replay produced one 435 KB / 894-claim product
    # document — 42% of that whole knowledge base in one file — which cannot be read whole by
    # a recall window and destroys the bird's-eye view canonical exists to give. Rollover is
    # mechanical maintenance for exactly that, the way log rotation is: size-triggered,
    # subject unchanged, older volumes frozen and linked. It is orthogonal to evolve, which
    # reorganizes MEANING (splitting a subject into sub-subjects) rather than rotating size.
    #   rollover_threshold_chars   — a document written by a compile that exceeds this many
    #     characters (the whole file, frontmatter included) gets a groom job enqueued on the
    #     same per-user queue. 0 disables rollover entirely. Only documents this compile
    #     actually wrote are checked, so an existing oversized document rolls over the next
    #     time it is touched rather than in a surprise sweep.
    #   rollover_keep_recent_chars — roughly how much of the most recent tail the active
    #     document keeps. Approximate on purpose: the cut lands on claim-block boundaries and
    #     a claim block is never split, so the retained tail is the largest whole-block suffix
    #     that fits. Must stay well below the threshold, or a rollover would archive almost
    #     nothing and re-trigger on the next write.
    rollover_threshold_chars: int = 40_000
    rollover_keep_recent_chars: int = 12_000

    # Fast-recall retrieval budget (PNEUMA_KNOWLEDGE_RECALL_CLAIM_CAP / _RECALL_WINDOW_CAP).
    # How many claims and body windows one fast_recall ask may pull into the prompt. The
    # defaults mirror the core constants (DEFAULT_CLAIM_CAP / DEFAULT_WINDOW_CAP) so an
    # unset deployment behaves byte-for-byte as before; benchmark harnesses raise them to
    # measure where retrieval saturates instead of patching core constants.
    recall_claim_cap: int = 64
    recall_window_cap: int = 8

    # Fast-recall retrieval planning (PNEUMA_KNOWLEDGE_RECALL_PLAN_QUERIES). 0 = off
    # (byte-for-byte the single-query lane). N > 0: one small call on the recall model
    # derives up to N extra retrieval queries before retrieval, and the claim face pools
    # every query through one RRF fusion — the fast lane's answer to multi-aspect
    # questions. Result-driven multi-round retrieval stays deep recall's job.
    recall_plan_queries: int = 0

    # Fast-recall claim rerank (PNEUMA_KNOWLEDGE_RECALL_RERANK_MODEL / _CANDIDATES).
    # Empty = off. "llm" = LLM reranker on the recall-role model pinned to reasoning
    # effort none (the default provider: input-heavy, output-tiny, an order of magnitude
    # cheaper than per-search-unit /rerank billing); "llm:<spec>" picks the chat model; a
    # bare model name (e.g. "cohere/rerank-4-pro") uses the OpenRouter /rerank endpoint.
    # Reranking deepens claim retrieval to `recall_rerank_candidates` per query per face
    # and scores the FULL deduped union against the original question; the winners fill
    # `recall_claim_cap`. RRF stays the candidate generator (dedup + failure fallback).
    recall_rerank_model: str = ""
    recall_rerank_candidates: int = 120

    # Answer-style preset for the answering lanes (PNEUMA_KNOWLEDGE_RECALL_ANSWER_STYLE):
    # "concise" = the bare exact value/phrase a grader or script expects;
    # "conversational" = a natural chat reply (default); "detailed" = a self-contained
    # written note. Shape only — truth discipline (red line, citations, honest close)
    # is style-independent. A recall request may override it per call.
    recall_answer_style: Literal["concise", "conversational", "detailed"] = "conversational"

    # Dev CORS: allow the vite dev server (any localhost/127.0.0.1 port) to call
    # the API from the browser. Override PNEUMA_KNOWLEDGE_CORS_ALLOW_ORIGIN_REGEX in real
    # deployments; set to "" to disable CORS entirely.
    cors_allow_origin_regex: str = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

    # Default / fallback chat model. Per-operation routing below overrides it when set.
    llm_model: str = "openai:gpt-4o-mini"
    # Per-operation model routing (PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE / _RECALL / _DEEP / _SKILL).
    # Empty → falls back to llm_model, so scripted-model tests (which set llm_model only)
    # keep routing everything to the scripted model. See docs/reference/observability.md.
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
    # Provider-call guardrails for EVERY chat-model role (compile/recall/deep/evolve/…).
    # Deliberately not split per role: one timeout and one retry budget is a guardrail, and
    # a per-role matrix would be a knob nobody can reason about.
    #   llm_timeout     — seconds a single request may take before it is abandoned. Large on
    #     purpose: a slow-but-alive request must not be killed; the guard is against hangs,
    #     not latency. Without it langchain/httpx would wait forever (a hung compile call
    #     once held a worker for 25 minutes with no error and no progress).
    #   llm_max_retries — langchain's own retry budget for transient provider errors
    #     (429 / 5xx / connection reset). Low-frequency provider flakes get absorbed by the
    #     library's mechanism rather than by hand-rolled retry code at the call sites.
    llm_timeout: float = 600.0
    llm_max_retries: int = 3
    # OpenRouter (OpenAI-compatible) key, read from the unprefixed OPENROUTER_API_KEY
    # so `openrouter:<model>` in llm_model can switch vendors without app changes.
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    # fake:<dim> = DeterministicFakeEmbedding (keyless; tests/example default, §M1.3).
    embedding_model: str = "fake:384"

    # Langfuse tracing (observability). Read from the unprefixed LANGFUSE_* env (same
    # convention as OPENROUTER_API_KEY) so the local Langfuse project's own variable
    # names work verbatim. All three default empty → tracing degrades to a no-op
    # (wiring.build_langfuse_handler returns None; every LLM call runs callbacks-free).
    # See docs/reference/observability.md.
    langfuse_secret_key: str = Field(default="", validation_alias="LANGFUSE_SECRET_KEY")
    langfuse_public_key: str = Field(default="", validation_alias="LANGFUSE_PUBLIC_KEY")
    langfuse_base_url: str = Field(default="", validation_alias="LANGFUSE_BASE_URL")


def get_settings() -> Settings:
    return Settings()
