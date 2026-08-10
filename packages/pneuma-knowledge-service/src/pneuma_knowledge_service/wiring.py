"""Dependency wiring: settings → adapter singletons (architecture.md §1).

A plain module, no DI framework. `build_context` assembles the concrete adapters
that satisfy the core ports and hands them to the API via FastAPI lifespan.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pneuma_knowledge_core.ingest.adapters import (
    CONTEXT_STREAM_MIME,
    AdapterRegistry,
    ContextStreamAdapter,
    MarkdownDocumentAdapter,
    PlainConversationAdapter,
)
from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from .adapters.git_canonical import GitCanonicalStore
from .adapters.meilisearch import MeiliLexicalIndex
from .adapters.postgres import PostgresStore
from .adapters.qdrant import QdrantVectorIndex
from .adapters.s3_media import S3MediaStore
from .adapters.scripted_model import load_scripted_model
from .adapters.user_info_mock import MockUserInfoProvider
from .adapters.user_info_provider_composite import PersistedThenMockUserInfoProvider
from .settings import Settings
from pneuma_knowledge_core.ports.user_info_provider import UserInfoProvider


def build_chunker(settings: Settings):
    """The L2 chonkie chunker configured from settings (chunk_strategy/size/overlap).

    Centralized here so both ingest flows (and the re-index script) build the same
    chunker; core's ``chunk_source`` stays pure — it just consumes the instance."""
    from pneuma_knowledge_core.ingest.chunking import build_chunker as _build

    return _build(
        settings.chunk_strategy, settings.chunk_size, settings.chunk_overlap
    )


async def full_l2_chunks(ctx: "AppContext", source_id, blocks, structure, user_id):
    """Build the ``semantic_indexing="full"`` L2 chunks per the configured strategy.

    - ``chunk_strategy`` in {``sentence``, ``recursive``} → the pure chonkie
      ``chunk_source`` (mechanical, no LLM).
    - ``chunk_strategy == "semantic"`` → ``semantic_chunk_source`` with the configured model (the
      ``compile`` role model via OpenRouter) detecting topic/entity boundaries, and a
      chonkie SentenceChunker (built from settings) as the over-long-segment sub-splitter.
      The LLM boundary call runs ONLY here (actual L2 indexing) — preview never reaches
      this helper, so preview stays cheap/mechanical.

    Centralized so both ingest flows and the re-index script share one dispatch."""
    from pneuma_knowledge_core.ingest.chunking import build_chunker as _build
    from pneuma_knowledge_core.ingest.chunking import chunk_source

    # Semantic segmentation needs a REAL LLM, so a scripted/keyless base model (tests,
    # demos) falls back to mechanical sentence chunking — mirroring the "scripted: base
    # model hard-overrides routing" discipline.
    #
    # NOT because scripted models cannot do structured output: `ScriptedChatModel`
    # overrides `bind_tools` (adapters/scripted_model.py), which sidesteps
    # `BaseChatModel`'s NotImplementedError guard, so `with_structured_output` works fine
    # over it — the AI suggestion path depends on exactly that. The reason is narrower: a fixed
    # replay script cannot know where the boundaries in an arbitrary document are, so
    # scripted semantic chunking would emit segments unrelated to the input.
    # Keyless deployments (no usable compile model — an openrouter spec without a key,
    # or no spec at all) fall back the same way: the engine file keeps saying
    # "semantic" as the durable strategy, and this dispatch point is where the missing
    # model degrades it mechanically for THIS process — not an env pin upstream.
    semantic = (
        ctx.settings.chunk_strategy == "semantic"
        and not ctx.settings.llm_model.startswith("scripted:")
        and bool(usable_model_name(ctx.settings, "compile"))
    )
    if semantic:
        from pneuma_knowledge_core.ingest.semantic import (
            blocks_content_digest,
            chunk_result_digest,
            decode_manifest_segments,
            encode_manifest_segments,
            semantic_chunk_source,
            semantic_segments,
        )

        # Sub-splitter for over-long single units: always the sentence chunker (with
        # overlap), regardless of the "semantic" top-level strategy.
        sub_chunker = _build(
            "sentence", ctx.settings.chunk_size, ctx.settings.chunk_overlap
        )
        cfg = llm_call_config(
            ctx, operation="chunk.semantic", user_id=str(user_id)
        )
        # Manifest-anchored determinism: the LLM boundary call is non-reproducible, so a
        # source whose content + strategy + model is unchanged REPLAYS its recorded
        # segments instead of re-detecting — a re-index is then byte-identical (I2). Only
        # a first ingest or a genuine change (edited source, model swap) calls the LLM.
        model_spec = resolve_model_name(ctx.settings, "compile")
        overlap = ctx.settings.semantic_overlap
        digest = blocks_content_digest(blocks)
        manifest = await ctx.store.get_chunk_manifest(user_id, source_id)
        # The recorded output contract is part of the replay key. `semantic_overlap` is
        # declared a `derived_rebuild` knob, and a replay that ignored the mode would make
        # that a lie: flipping the knob and rebuilding would faithfully reproduce the layout
        # the OLD mode produced, forever. A mismatch re-detects — which is exactly what
        # "takes effect on the next rebuild" means.
        recorded = (
            decode_manifest_segments(
                manifest["segments"],
                block_indices=sorted(b.index for b in blocks),
            )
            if manifest is not None
            and manifest["strategy"] == "semantic"
            and manifest["model"] == model_spec
            and manifest["content_digest"] == digest
            else None
        )
        replay = recorded is not None and recorded[1] == overlap
        if replay:
            segments = recorded[0]
        else:
            segments = await semantic_segments(
                blocks, model=ctx.get_chat_model("compile"), overlap=overlap, **cfg
            )
        chunks = await semantic_chunk_source(
            source_id,
            blocks,
            structure,
            segments=segments,
            sub_chunker=sub_chunker,
        )
        if not replay:
            await ctx.store.put_chunk_manifest(
                user_id,
                source_id,
                strategy="semantic",
                model=model_spec,
                content_digest=digest,
                segments=encode_manifest_segments(segments, overlap=overlap),
                result_digest=chunk_result_digest(chunks),
            )
        return chunks
    # Mechanical chonkie path. A "semantic" strategy that reached here (scripted/keyless
    # fallback) is not a chonkie strategy, so resolve it to sentence.
    chonkie_strategy = (
        ctx.settings.chunk_strategy
        if ctx.settings.chunk_strategy in ("sentence", "recursive")
        else "sentence"
    )
    chunker = _build(chonkie_strategy, ctx.settings.chunk_size, ctx.settings.chunk_overlap)
    return await chunk_source(source_id, blocks, structure, chunker=chunker)


async def plan_l2_chunks(ctx: "AppContext", source_id, normalized, user_id):
    """The L2 chunks a source's OWN IntakePlan asks for — the ingest path's dispatch.

    `full` → `full_l2_chunks` (strategy dispatch above); `summary` → section heads;
    anything else → no L2 at all (the plan says this source is not semantically indexed).
    Centralized here because every rebuild path (the ops re-index scripts, a prebuilt
    library restore) must reproduce what a fresh ingest would have written — a rebuild that
    ignored the plan would over-index sources the plan deliberately kept out of L2."""
    from .ingest_document import _summary_chunks

    plan = normalized.raw.intake_plan or {}
    semantic = plan.get("semantic_indexing", "full")
    if semantic == "full":
        return await full_l2_chunks(
            ctx, source_id, normalized.blocks, normalized.structure, user_id
        )
    if semantic == "summary":
        return _summary_chunks(source_id, normalized)
    return []


def build_embeddings(settings: Settings) -> Embeddings:
    """Assemble the embeddings model from settings.embedding_model.

    `fake:<dim>` → DeterministicFakeEmbedding (langchain-core built-in; the keyless
    tests/example default — zero external deps, zero keys). `openrouter:<model>` → real
    semantic embeddings over OpenRouter's OpenAI-compatible endpoint, reusing
    OPENROUTER_API_KEY (e.g. `openrouter:google/gemini-embedding-2`, 3072-dim).
    """
    model = settings.embedding_model
    if model.startswith("fake:"):
        return DeterministicFakeEmbedding(size=int(model.split(":", 1)[1]))
    if model.startswith("openrouter:"):
        from .adapters.openrouter_embeddings import OpenRouterEmbeddings

        return OpenRouterEmbeddings(
            model.split(":", 1)[1], settings.openrouter_api_key
        )
    raise NotImplementedError(
        f"unknown embedding spec {model!r}; use fake:<dim> or openrouter:<model>"
    )


# Per-operation → settings field. Empty field falls back to settings.llm_model.
_ROLE_FIELDS = {
    "compile": "llm_model_compile",
    "recall": "llm_model_recall",  # fast recall + briefing ask
    "deep": "llm_model_deep",
    "skill": "llm_model_skill",
    "live_context": "llm_model_live_context",  # evaluation + its want_more expansion
    "evolve": "llm_model_evolve",  # schema evolve (propose + reorganize)
    "challenge": "llm_model_challenge",  # post-compile coverage challenge (questions + reflection)
}

# A role whose own field is empty may borrow ANOTHER role's field before falling all the
# way back to settings.llm_model. Only `live_context` → `recall` today: both are single-shot and
# latency-shaped, so pointing recall at a fast model should route Live Context there too without a
# second env var. Deliberately one hop, no chains — a routing table you have to trace is
# how "which model actually ran?" becomes unanswerable.
# `evolve` borrows `compile`'s model when its own field is empty: schema evolve is the same
# heavy write-side reasoning as a compile (whole-KB reorganization), so a deployment that
# already pointed compile at a strong model should not have to name it twice. One hop.
_ROLE_FALLBACK = {"live_context": "recall", "evolve": "compile", "challenge": "compile"}


def resolve_model_name(settings: Settings, role: str = "default") -> str:
    """The model spec for an operation, falling back to settings.llm_model.

    A `scripted:` base model is a deterministic test/demo signal: it overrides any
    per-role routing so a scripted run stays fully keyless and reproducible (env-set
    role models never leak into it).
    """
    if settings.llm_model.startswith("scripted:"):
        return settings.llm_model
    for candidate in (role, _ROLE_FALLBACK.get(role)):
        field = _ROLE_FIELDS.get(candidate) if candidate else None
        value = getattr(settings, field, "") if field else ""
        if value:
            return value
    return settings.llm_model


def usable_model_name(settings: Settings, role: str = "default") -> str:
    """The resolved model spec for a role, or "" when THIS process cannot run it.

    An `openrouter:` spec without OPENROUTER_API_KEY is the keyless state: the engine
    file keeps naming the models the deployment would use with a key (the durable,
    console-visible truth), and every dispatch point that would otherwise build the
    model asks THIS function instead of pinning empty roles into the environment —
    which used to hide the engine's values behind an env lock in the console."""
    name = resolve_model_name(settings, role)
    if name.startswith("openrouter:") and not settings.openrouter_api_key.strip():
        return ""
    return name


def _provider_guardrails(settings: Settings) -> dict:
    """The `timeout` / `max_retries` kwargs every real chat model is constructed with.

    `timeout` is the anti-hang guard: a provider connection that stops producing (no error,
    no tokens) otherwise pins the caller forever — a worker job held for 25 minutes with a
    hung OpenRouter call is what put this here. It is set LARGE on purpose (see
    Settings.llm_timeout): killing a slow-but-alive request is the worse failure.

    `max_retries` is langchain's own transient-error retry — the library mechanism is the
    right place to absorb low-frequency 429/5xx flakes, so no call site grows its own loop.

    langchain-openai exposes the timeout field as `request_timeout` with `timeout` as its
    pydantic alias, so the kwarg name here is the portable one; other langchain provider
    integrations accept the same two names. Both are plain constructor fields: `bind_tools`
    and `with_structured_output` re-bind the same configured client and are unaffected.
    """
    return {"timeout": settings.llm_timeout, "max_retries": settings.llm_max_retries}


def _build_from_name(
    name: str,
    settings: Settings,
    *,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
) -> BaseChatModel:
    """Assemble a chat model from a spec.

    `scripted:<path>` → a keyless ScriptedChatModel from a JSON script (tests / demos,
    no provider key). `openrouter:<model>` → the OpenAI-compatible OpenRouter endpoint.
    Anything else goes through langchain `init_chat_model` (e.g. `anthropic:claude-sonnet-5`).

    `reasoning_effort` pins the model's reasoning effort at construction (OpenRouter
    `{"reasoning": {"effort": ...}}`) — used for auxiliary calls that must stay cheap,
    like the LLM reranker's `none`. OpenRouter specs only; scripted models ignore it and
    other providers do not take the field.

    `max_tokens` pins a completion budget at construction — used for auxiliary calls
    whose healthy output is small and bounded (the challenge's structured passes), so a
    runaway generation fails cheaply instead of at the provider ceiling. Scripted models
    are local replay and ignore it.

    Every REAL model (both branches, hence every role) is built with the same two provider
    guardrails from settings — see `_provider_guardrails`. The scripted model is local
    replay: no request, nothing to time out or retry.
    """
    if name.startswith("scripted:"):
        return load_scripted_model(name.split(":", 1)[1])
    # Imported lazily: init_chat_model pulls provider extras only when a real model
    # is requested, keeping the scripted/keyless path dependency-free.
    from langchain.chat_models import init_chat_model

    guardrails = _provider_guardrails(settings)
    if name.startswith("openrouter:"):
        key = settings.openrouter_api_key
        if not key:
            raise RuntimeError("openrouter:<model> requires OPENROUTER_API_KEY")
        extra: dict = {}
        if max_tokens:
            extra["max_tokens"] = max_tokens
        if reasoning_effort:
            extra["extra_body"] = {"reasoning": {"effort": reasoning_effort}}
        if settings.openrouter_provider_order.strip():
            # OpenRouter provider routing pin: restrict which upstream providers may
            # serve the request. Without it OpenRouter can fall back to third-party
            # resellers of the same model — different quantization, different behavior,
            # silently. https://openrouter.ai/docs/features/provider-routing
            extra.setdefault("extra_body", {})
            extra["extra_body"] |= {
                "provider": {
                    "order": [
                        part.strip()
                        for part in settings.openrouter_provider_order.split(",")
                        if part.strip()
                    ],
                    "allow_fallbacks": settings.openrouter_allow_fallbacks,
                }
            }
        return init_chat_model(
            name.split(":", 1)[1],
            model_provider="openai",
            base_url="https://openrouter.ai/api/v1",
            api_key=key,
            **extra,
            **guardrails,
        )
    if max_tokens:
        guardrails = {**guardrails, "max_tokens": max_tokens}
    return init_chat_model(name, **guardrails)


def build_chat_model_for(settings: Settings, role: str = "default") -> BaseChatModel:
    """Build the chat model routed for a given operation (compile/recall/deep/skill)."""
    return _build_from_name(resolve_model_name(settings, role), settings)


def build_chat_model(settings: Settings) -> BaseChatModel:
    """Back-compat: the default-role chat model (settings.llm_model)."""
    return build_chat_model_for(settings, "default")


# --------------------------------------------------------------- observability (Langfuse)
#
# Langfuse is a *service* dependency only — core never imports it (architecture.md §2).
# The service builds a langchain CallbackHandler and injects it into the core LLM call
# sites via `callbacks`. See docs/reference/observability.md.


def _import_langfuse():  # pragma: no cover - thin import shim (monkeypatched in tests)
    """Lazy import so the keyless path (and core) never pulls langfuse.

    Split out as a seam: tests monkeypatch this to assert the has-key build branch
    without importing the real client or touching the network.
    """
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler

    return Langfuse, CallbackHandler


def build_langfuse_handler(settings: Settings):
    """Build a langfuse langchain CallbackHandler, or None when unconfigured.

    Graceful degradation: if any of the three LANGFUSE_* settings is empty, tracing is
    off and this returns None — every core call site then runs with callbacks=[] (a
    byte-for-byte no-op, keyless tests unaffected). When all three are present it
    initializes the global Langfuse client (public/secret key + host) and returns a
    CallbackHandler bound to it. langfuse v3: the handler reads the process-global client
    that the `Langfuse(...)` constructor configures.
    """
    if not (
        settings.langfuse_secret_key
        and settings.langfuse_public_key
        and settings.langfuse_base_url
    ):
        return None
    Langfuse, CallbackHandler = _import_langfuse()
    Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_base_url,
    )
    return CallbackHandler()


def llm_call_config(
    ctx: "AppContext",
    *,
    operation: str,
    user_id: str,
    extra: dict | None = None,
) -> dict:
    """Assemble the {callbacks, trace_metadata} kwargs a core LLM call site accepts.

    Unified trace metadata (filterable in Langfuse): operation, user_id, env, app,
    plus caller `extra` (skill_version for compile; snapshot_ref for recall/briefing).
    Trace-size discipline (docs/reference/observability.md): ids / counts only — never a
    key, never a slab of canonical body. None-valued extras are dropped. When tracing is
    off the callbacks list is empty and the core call runs exactly as before.
    """
    handler = ctx.langfuse_handler()
    metadata: dict = {
        "operation": operation,
        "user_id": str(user_id),
        "env": "local",
        "app": "pneuma-knowledge-compiler",
    }
    if extra:
        metadata.update({k: v for k, v in extra.items() if v is not None})
    # Group a multi-round tool loop into ONE Langfuse session. Every `invoke` inside a loop
    # creates its own root trace, so a compile job's rounds used to land as N unrelated
    # traces — the job as a whole was not observable, only its individual model calls, and
    # reconstructing it meant joining on metadata by hand. `langfuse_session_id` /
    # `langfuse_user_id` are the langchain integration's reserved metadata keys; they are
    # additive and inert when tracing is off.
    session = metadata.get("job_id") or metadata.get("briefing_id") or metadata.get("snapshot_ref")
    if session:
        metadata["langfuse_session_id"] = f"{operation}:{session}"
    metadata["langfuse_user_id"] = str(user_id)
    return {
        "callbacks": [handler] if handler is not None else [],
        "trace_metadata": metadata,
    }


@dataclass
class AppContext:
    settings: Settings
    store: PostgresStore
    canonical: GitCanonicalStore
    lexical: MeiliLexicalIndex
    vectors: QdrantVectorIndex
    embeddings: Embeddings
    registry: AdapterRegistry
    media: S3MediaStore | None = None
    # user_id → UserProfile. Persisted-first (user-filled), mock-fallback;
    # build_context wires the persisted lookup to PG. The default is the bare keyless mock
    # so an AppContext built without a store (some unit tests) still resolves profiles.
    user_info: UserInfoProvider = field(default_factory=MockUserInfoProvider)
    # Lazily built per role so build_context (used widely by tests with the default
    # openai:… model) never eagerly imports a provider client — a role's chat model is
    # only assembled when an endpoint first needs it, then reused.
    _chat_models: dict[str, BaseChatModel] = field(default_factory=dict, repr=False)
    # Langfuse handler: built once, reused across calls (the underlying client batches).
    # `_langfuse_built` distinguishes "not yet attempted" from "attempted, no keys → None".
    _langfuse_handler: object | None = field(default=None, repr=False)
    _langfuse_built: bool = field(default=False, repr=False)
    # Lazily built claim reranker (core Reranker port), or None while
    # settings.recall_rerank_model is empty — the fast lane treats None as "pass off".
    _reranker: object | None = field(default=None, repr=False)

    def get_reranker(self):
        """The configured claim reranker, or None when reranking is off (empty model).

        Provider selection by spec shape:
          "llm"        → LLMReranker on the recall-role model, reasoning effort pinned to
                         none — the default provider (input-heavy, output-tiny, no extra
                         service dependency).
          "llm:<spec>" → LLMReranker on that chat spec, same effort pin.
          "<model>"    → the OpenRouter /rerank endpoint (e.g. cohere/rerank-4-pro) — a
                         dedicated cross-encoder billed per search unit, for workloads
                         where a purpose-built scorer earns its fee.
        Measured on LoCoMo-refined: neither provider beat plain capped retrieval, which
        is why the knob itself defaults OFF."""
        spec = self.settings.recall_rerank_model.strip()
        if not spec:
            return None
        if self._reranker is None:
            if spec == "llm" or spec.startswith("llm:"):
                from .adapters.llm_rerank import LLMReranker

                model_spec = (
                    spec.split(":", 1)[1]
                    if ":" in spec
                    else resolve_model_name(self.settings, "recall")
                )
                self._reranker = LLMReranker(
                    _build_from_name(model_spec, self.settings, reasoning_effort="none")
                )
            else:
                from .adapters.openrouter_rerank import OpenRouterReranker

                self._reranker = OpenRouterReranker(
                    spec, self.settings.openrouter_api_key
                )
        return self._reranker

    def get_chat_model(self, role: str = "default") -> BaseChatModel:
        # Keyed by resolved model spec, not role: roles sharing a spec (all-scripted,
        # or compile+recall both on one model) share one instance — which also keeps a
        # scripted model's replay cursor shared across roles, as tests expect.
        name = resolve_model_name(self.settings, role)
        # The challenge role carries its completion budget (see the settings comment):
        # keyed as spec+cap so a compile/recall role sharing the same spec keeps its
        # uncapped instance. Scripted models stay on the plain key — they are local
        # replay, and a forked instance would split the shared cursor tests rely on.
        max_tokens = (
            self.settings.challenge_max_output_tokens
            if role == "challenge" and not name.startswith("scripted:")
            else 0
        )
        key = f"{name}#max_tokens={max_tokens}" if max_tokens else name
        if key not in self._chat_models:
            self._chat_models[key] = _build_from_name(
                name, self.settings, max_tokens=max_tokens or None
            )
        return self._chat_models[key]

    def langfuse_handler(self):
        """The reusable langfuse CallbackHandler, or None when tracing is unconfigured."""
        if not self._langfuse_built:
            self._langfuse_handler = build_langfuse_handler(self.settings)
            self._langfuse_built = True
        return self._langfuse_handler

    async def flush_traces(self) -> None:
        """Flush buffered traces to Langfuse. No-op when tracing is off or unused.

        Short-lived processes (the compile worker per job; example scripts before exit)
        must flush or the background batch is lost when the process ends. This does NOT
        force-build the handler: a context that never ran a traced LLM call (e.g. a
        pure-ingest test) flushes nothing and touches no network.

        `asyncio.to_thread`, not real async: the langfuse SDK client is synchronous and
        `flush()` blocks on an HTTP round trip. It is moved off the loop, not made async.
        """
        if not self._langfuse_built or self._langfuse_handler is None:
            return
        import asyncio

        from langfuse import get_client

        await asyncio.to_thread(get_client().flush)

    async def aclose(self) -> None:
        await self.flush_traces()
        await self.store.aclose()
        await self.lexical.aclose()
        await self.vectors.aclose()
        if self.media is not None:
            await self.media.aclose()
        if self._reranker is not None:
            await self._reranker.aclose()


async def build_context(settings: Settings) -> AppContext:
    """Assemble the adapter singletons and bring their connections up on the CALLER's
    event loop (pool open, collection probe). Everything the constructors used to do
    eagerly — opening the PG pool, probing the Qdrant collection, probing the embedding
    dimension — is I/O, so it happens here under await rather than inside `__init__`."""
    store = PostgresStore(settings.pg_dsn)
    await store.open()
    await store.apply_schema()

    embeddings = build_embeddings(settings)
    dim = len(await embeddings.aembed_query("dimension probe"))

    lexical = MeiliLexicalIndex(settings.meili_url, settings.meili_key)
    vectors = QdrantVectorIndex(settings.qdrant_url, dim, collection=settings.qdrant_collection)
    await vectors.ensure_collection()
    canonical = GitCanonicalStore(settings.canonical_root)
    media = S3MediaStore(
        bucket=settings.media_s3_bucket,
        endpoint_url=settings.media_s3_endpoint_url,
        access_key=settings.media_s3_access_key,
        secret_key=settings.media_s3_secret_key,
        region=settings.media_s3_region,
    )

    registry = AdapterRegistry()
    registry.register(PlainConversationAdapter(), kind="conversation")
    registry.register(
        ContextStreamAdapter(), kind="conversation", mime=CONTEXT_STREAM_MIME
    )
    registry.register(MarkdownDocumentAdapter(), kind="document")

    # Persisted-first user picture: PG-backed overrides win, mock synthesis is the
    # fallback for users who never onboarded. No key dependency — the lookup only
    # touches the user_profiles table, applied above by apply_schema.
    user_info = PersistedThenMockUserInfoProvider(
        persisted_lookup=store.get_user_profile,
        mock=MockUserInfoProvider(),
    )

    return AppContext(
        settings=settings,
        store=store,
        canonical=canonical,
        lexical=lexical,
        vectors=vectors,
        embeddings=embeddings,
        registry=registry,
        media=media,
        user_info=user_info,
    )
