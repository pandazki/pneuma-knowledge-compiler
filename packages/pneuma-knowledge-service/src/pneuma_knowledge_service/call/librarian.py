"""Two overlapping lookups inside one Live delegation.

A bounded canonical-or-lexical first look selects a complete short record and hands it to Live with an
explicit partial scope. Broader fast recall runs concurrently and returns supported facts,
evidence scope and unresolved aspects of the standalone subtask. Live owns conversation.
Both phases share tenant, time and archive scope. Neither writes the library.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields, replace
from datetime import datetime, timezone
from typing import Any, Protocol

from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.canonical_glance import display_identity
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.recall.call import Ask, Exchange, Ledger, form_ask, vocabulary_of
from pneuma_knowledge_core.recall.fast import FastAnswer, add_usage, fast_recall
from pneuma_knowledge_core.recall.call import speakable
from pneuma_knowledge_core.recall.evidence_context import enrich_evidence
from pneuma_knowledge_core.recall.progressive import FirstFinding, canonical_first_claims, first_finding, refine
from pneuma_knowledge_core.recall.stage_timing import StageTiming

#: How long one reading of the canonical tree serves a call. A compile can land mid-call and
#: the next ask should see it; re-reading git on every ask would put that read in front of
#: every first word.
DOCUMENTS_TTL_SECONDS = 60.0

#: How long the selection call may take before the lane answers on ranked evidence instead.
#: The deployment default is thirty seconds, which is right for a reader and is a dropped call
#: here. Measured with reasoning off, the selection settles in 2.4–3.9s, so this is headroom
#: and not a budget: past it the call has already lost, and failing fast leaves time for an
#: answer. The same measurement found the other half of the rule below — a selection that
#: times out degrades to RANKED evidence, which is the widest context the lane can build, so
#: the path that protects a slow call must not be the one that floods it.
SELECTION_TIMEOUT_SECONDS = 5.0

# A slow or empty first look must not prevent the broader answer from completing.
FIRST_LOOK_SECONDS = 6.0

#: The fast lane's lookup posture — see the module docstring for why each line is here.
POSTURE: dict[str, Any] = {
    "answer_style": "concise",
    "render_glance": False,
    # Preserve model relevance selection for wide pools; do not hide a brittle subject-name
    # containment filter inside a component. Small pools can be judged during answering.
    "evidence_strategy": "select",
    # The broader phase uses relevance selection; it runs alongside the bounded first look.
    "selection_reasoning_effort": None,
    "evidence_selection_timeout": SELECTION_TIMEOUT_SECONDS,
    # What survives into the answer — and, the reason it is stated here, how wide the DEGRADED
    # path is. A selection that times out or errors leaves the lane building its context from
    # this many RANKED claims, so the number that protects a slow call must not be the one
    # that floods it.
    #
    # It is NOT the selector's pool, which was the mistake this comment replaces: measured,
    # the selector reads the full candidate pool (`claim_candidate_cap`, 80 by default) at
    # both `cap` 10 and `cap` 40 — byte-identical prompts — so widening `cap` for the
    # selection's sake gave the judgement nothing and only widened its fallback. Twelve is
    # what a spoken answer of two or three sentences can carry, and the most unjudged
    # evidence this posture is willing to answer from.
    "cap": 12,
    "window_cap": 4,
    "episode_summary_cap": 3,
    "claim_provenance_passage_cap": 4,
    "episode_provenance_passage_cap": 1,
    "provenance_passage_max_chars": 6000,
    "answer_format": "text",
    "plan_queries_cap": 0,
    "reranker": None,
    "rerank_candidates": 0,
    "reasoning_effort": None,
}


@dataclass(frozen=True)
class LibraryAnswer:
    """One answer: the payload `POST /recall` would have returned, and its plain text."""

    payload: dict[str, Any]
    answer_text: str


class Librarian(Protocol):
    async def warm(self) -> None: ...

    async def vocabulary(self, heard: str) -> str: ...

    async def speech_vocabulary(self) -> str: ...

    async def form_ask(
        self, ledger: Ledger, *, earlier: Sequence[Exchange], vocabulary: str
    ) -> Ask: ...

    async def answer(
        self,
        question: str,
        *,
        on_token: Callable[[str], None],
        on_retrieved: Callable[[], None],
        on_preliminary: Callable[[str], None],
        on_progress: Callable[[str], None] | None = None,
    ) -> LibraryAnswer: ...


class LibraryLibrarian:
    """The shipped librarian, over this process's own AppContext."""

    def __init__(self, ctx: Any, user_id: str) -> None:
        self._ctx = ctx
        self._user = UserId(user_id)
        self._glance_inputs: dict[str, Any] | None = None
        self._read_at = 0.0

    async def _inputs(self) -> dict[str, Any]:
        from ..api.routes import v1

        if self._glance_inputs is None or time.monotonic() - self._read_at > DOCUMENTS_TTL_SECONDS:
            self._glance_inputs = await v1._glance_inputs(self._ctx, self._user, None)
            self._read_at = time.monotonic()
        return self._glance_inputs

    async def warm(self) -> None:
        """Read what the first ask would otherwise wait for: the canonical tree."""
        await self._inputs()

    async def vocabulary(self, heard: str) -> str:
        documents = (await self._inputs()).get("documents") or []
        by_path = {doc.path: doc for doc in documents}
        titles = vocabulary_of([display_identity(by_path, path).title for path in by_path], heard=heard)
        hints = await self.speech_vocabulary()
        return hints + "\n" + titles if hints else titles

    async def speech_vocabulary(self) -> str:
        """Read the prepared lexicon and page metadata, with no model call at dial time."""
        from .speech_lexicon import vocabulary
        documents = (await self._inputs()).get("documents") or []
        return await asyncio.to_thread(vocabulary, self._ctx.settings, str(self._user), documents)

    async def form_ask(
        self, ledger: Ledger, *, earlier: Sequence[Exchange], vocabulary: str
    ) -> Ask:
        from ..wiring import llm_call_config

        return await form_ask(
            self._ctx.get_chat_model("call"),
            ledger,
            earlier=earlier,
            vocabulary=vocabulary,
            **llm_call_config(self._ctx, operation="call.ask", user_id=str(self._user)),
        )

    async def classify_change(self, question: str, owner_text: str) -> str:
        from pneuma_knowledge_core.recall.call import task_change
        return await task_change(self._ctx.get_chat_model("call"), question, owner_text)

    async def answer(
        self,
        question: str,
        *,
        on_token: Callable[[str], None],
        on_retrieved: Callable[[], None],
        on_preliminary: Callable[[str], None],
        on_progress: Callable[[str], None] | None = None,
    ) -> LibraryAnswer:
        from ..api.routes import v1

        ctx = self._ctx
        as_of = datetime.now(timezone.utc)
        plane = await v1._resolve_plane(ctx, self._user, None)
        body = v1.RecallIn(query=question, mode="fast", answer_style="concise")
        kwargs = await v1._fast_recall_kwargs(
            ctx,
            body,
            plane,
            user_id=str(self._user),
            as_of=as_of,
            snapshot_ref=None,
            glance_inputs=await self._inputs(),
        )
        model = ctx.get_chat_model("call")
        kwargs.update(POSTURE, model=model, answer_model=model, route_model=model, glance_model=None)

        # Both phases share the resolved owner, archive scope, canonical view and as_of.
        # The first lookup needs no embedding, routing, selection or answer model call.
        quick_kwargs = dict(kwargs)
        quick_kwargs.update(
            model=None, answer_model=None, route_model=None, embeddings=None,
            # A scorer runs independently of `model`. The first look must not inherit
            # the deployment's JEV pass as well as the broader lookup's selection.
            evidence_scorer=None,
            claim_vectors=None, vectors=None, fast_paths=(),
            cap=6, claim_candidate_cap=8, window_cap=2, window_candidate_cap=3,
            episode_summary_cap=0, evidence_strategy="select",
            claim_provenance_passage_cap=6, episode_provenance_passage_cap=0,
            evidence_only=True, image_mode="caption", media=None,
        )
        started = time.perf_counter()
        first = FirstFinding()
        first_reason = ""
        first_skipped = ""

        async def quick() -> FirstFinding:
            claims = canonical_first_claims(question, kwargs.get("documents") or ())
            if claims is None:
                evidence = await fast_recall(plane.retrieval_user, question, **quick_kwargs)
            else:
                from pneuma_knowledge_core.recall.archive_filter import archive_view, filter_claims
                from pneuma_knowledge_core.recall.fast import FastEvidence
                view = await archive_view(plane.retrieval_user, kwargs.get("content"),
                                          documents_archived=kwargs.get("archive_active", False))
                claims, _ = filter_claims(claims, view,
                                         live_paths={d.path for d in kwargs.get("documents") or ()})
                claims = await enrich_evidence(
                    claims, user_id=plane.retrieval_user, content=kwargs.get("content"))
                evidence = FastEvidence(question=question, as_of=as_of, system="", content="",
                                        handles={}, used_claims=tuple(claims))
            return await first_finding(model, question, evidence,
                zone=kwargs.get("zone", "UTC"),
                callbacks=kwargs.get("callbacks"), trace_metadata=kwargs.get("trace_metadata"))

        quick_task = asyncio.create_task(quick())
        broad_task = asyncio.create_task(fast_recall(
            plane.retrieval_user, question, evidence_only=True, **kwargs))
        try:
            done, _ = await asyncio.wait(
                (quick_task, broad_task), timeout=FIRST_LOOK_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if quick_task in done:
                try:
                    first = quick_task.result()
                except Exception as exc:
                    first_reason = type(exc).__name__
            elif broad_task in done:
                # Once full evidence is available, an unfinished preliminary cannot
                # hold up the answer. Never inject a late first finding after refinement.
                first_skipped = "broader_ready"
                quick_task.cancel()
            else:
                first_reason = "timeout"
                quick_task.cancel()
            first_ms = (time.perf_counter() - started) * 1000
            if first.text:
                on_preliminary(first.text)
            elif not first_reason and not first_skipped:
                first_reason = "no_supported_finding"
            if not first.text and not broad_task.done() and on_progress is not None:
                # Task state only: unverified candidates never become Live context.
                on_progress(prompt("call.progressive.checking"))
            evidence = await broad_task
            on_retrieved()
            answer_started = time.perf_counter()
            refined = await refine(model, evidence,
                callbacks=kwargs.get("callbacks"), trace_metadata=kwargs.get("trace_metadata"))
            if refined.result_text:
                on_token(refined.result_text)
            answer_ms = (time.perf_counter() - answer_started) * 1000
            total_ms = (time.perf_counter() - started) * 1000
            stages = tuple(
                replace(stage, ms=round(answer_ms), status="ran") if stage.name == "answer"
                else replace(stage, ms=round(total_ms)) if stage.name == "total" else stage
                for stage in evidence.stages
            )
            # Preserve the recall card's evidence shape, with both phases' model receipts.
            common = {item.name: getattr(evidence, item.name) for item in fields(FastAnswer)
                      if hasattr(evidence, item.name)
                      and item.name not in {"answer", "answer_text", "token_usage", "stages"}}
            answer = FastAnswer(
                **common, answer=refined.answer, answer_text=speakable(refined.answer),
                citation_handles=evidence.handles, evidence_manifest=evidence.manifest,
                token_usage=add_usage(add_usage(evidence.token_usage, first.usage), refined.usage),
                stages=(*(s for s in stages if s.name != "total"),
                    StageTiming(name="first_lookup", ms=round(first_ms),
                        status="skipped" if first_skipped else "degraded" if first_reason else "ran",
                        detail=first_reason or first_skipped or None),
                    *(s for s in stages if s.name == "total")),
            )
            out = v1._fast_answer_out(answer, as_of=as_of, plane=plane, settings=ctx.settings)
            payload = out.model_dump(mode="json")
            payload["progressive"] = {"preliminary": first.text, "locator": first.locator,
                                      "first_disposition": first.disposition, "first_reason": first.reason,
                                      "first_degraded": first_reason or None, "first_skipped": first_skipped or None}
            payload["lookup_result"] = {
                "status": refined.status, "scope": refined.scope,
                "limitations": list(refined.limitations),
                "facts": [fact.model_dump() for fact in refined.facts],
            }
            return LibraryAnswer(payload=payload, answer_text=answer.answer_text)
        finally:
            # Cancellation, errors and superseded session shutdown must leave no hidden work.
            for task in (quick_task, broad_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(quick_task, broad_task, return_exceptions=True)
