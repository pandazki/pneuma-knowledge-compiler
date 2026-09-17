"""The delegate's working half: the library, asked the way a voice has to ask it.

It is the fast lane — the same function the console's Recall view and `pkc recall` call, fed
by the same `_fast_recall_kwargs` the route assembles, so a call answers from exactly the
evidence faces, archive scope and citation discipline every other answer does. What differs
is a POSTURE, and every line of it was bought with a measurement on a real library
(docs/design/voice-call.md §6): the `call` role (reasoning off) for every turn, no glance in
the prompt, the `spoken` answer style, and a selection call held to a call's patience rather
than a reader's. Together they took the first answer token from about ten seconds to under
three, and the selection is what keeps a wide retrieval from reaching the answer as a flood.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from pneuma_knowledge_core.canonical_glance import display_identity
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.recall.call import Ask, Exchange, Ledger, form_ask, vocabulary_of
from pneuma_knowledge_core.recall.fast import fast_recall

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

#: The fast lane's spoken posture — see the module docstring for why each line is here.
POSTURE: dict[str, Any] = {
    "answer_style": "spoken",
    "render_glance": False,
    # RELEVANCE IS A JUDGEMENT, so a model makes it. The lane retrieves widely and one small
    # structured call picks what actually answers the question, returning coordinates the
    # framework validates. The alternative this replaced — scoping the lookup itself with a
    # mechanical name match — was a judgement wearing a mechanism's clothes: it worked when the
    # owner said a project's whole name and missed when they said "that upload thing", and it
    # put relevance inside a component, where this framework deliberately does not keep it
    # (core `recall/component_rank.py`: paths return everything they know, the framework
    # orders). Measured against it on a real library: +2.4s to the first spoken word, and a
    # question about one project among several days of others is answered about that project.
    "evidence_strategy": "select",
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

    async def form_ask(
        self, ledger: Ledger, *, earlier: Sequence[Exchange], vocabulary: str
    ) -> Ask: ...

    async def answer(
        self,
        question: str,
        *,
        on_token: Callable[[str], None],
        on_retrieved: Callable[[], None],
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
        return vocabulary_of(
            [display_identity(by_path, path).title for path in by_path], heard=heard
        )

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

    async def answer(
        self,
        question: str,
        *,
        on_token: Callable[[str], None],
        on_retrieved: Callable[[], None],
    ) -> LibraryAnswer:
        from ..api.routes import v1

        ctx = self._ctx
        as_of = datetime.now(timezone.utc)
        plane = await v1._resolve_plane(ctx, self._user, None)
        body = v1.RecallIn(query=question, mode="fast", answer_style="spoken")
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

        def on_event(event: Any) -> None:
            # The lane's own clock says when retrieval settled; the card moves from
            # "searching" to "answering" on that and not on a guess.
            if getattr(event, "name", "") == "answer" and getattr(event, "phase", "") == "start":
                on_retrieved()

        answer = await fast_recall(
            plane.retrieval_user, question, on_token=on_token, on_event=on_event, **kwargs
        )
        out = v1._fast_answer_out(answer, as_of=as_of, plane=plane, settings=ctx.settings)
        return LibraryAnswer(payload=out.model_dump(mode="json"), answer_text=answer.answer_text)
