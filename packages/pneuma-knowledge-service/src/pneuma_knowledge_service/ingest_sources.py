"""Official source-contract intake: normalize, persist, index and compile."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.authorship import owner_authored_blocks
from pneuma_knowledge_core.domain.intake import (
    IntakePlan,
    plan_for_archetype,
    propose_intake,
    with_semantic_retrieval,
)
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.source_contracts import SourceContract

from .ingest import IngestResult, subject_time_context
from .media_ingest import materialize_contract_images
from .snapshot_tenant import assert_writable
from .source_receipt import SourceImportJob
from .wiring import AppContext


@dataclass(frozen=True)
class OfficialIngestResult:
    contract_schema: str
    sources: list[IngestResult]
    #: The compile jobs this import enqueued, in the order it enqueued them. Empty when the
    #: contract's intake asked for no canonical treatment, or when every source was a replay
    #: the library already holds. Reported because a CLI caller has nothing else to watch:
    #: the browser polls `/jobs`, and a Steward needs the id it is about to open.
    compile_jobs: list[str] = field(default_factory=list)


async def ingest_source_contract(
    ctx: AppContext,
    user_id: UserId,
    contract: SourceContract,
    *,
    imported_at: datetime | None = None,
    intake_plan: IntakePlan | None = None,
    about_paths: Sequence[str] = (),
    intake_archetype: str | None = None,
) -> OfficialIngestResult:
    """Import a canonical bundle at its natural citation boundaries.

    Every expanded source follows the existing append-only path: L0 is persisted
    synchronously, then L1/L2 indexing and L3 compilation are queued.

    `intake_plan` OVERRIDES the mechanical proposal for every source in this bundle. It
    exists for one caller and states one thing the policy cannot know: the archive job
    ingests the Owner's statement with `canonical_treatment: none`, because the archive
    RECORD is already that statement's canonical expression, written mechanically in the
    same commit as the move. A compile of the same statement would paraphrase the decision
    onto whatever pages the model thought it touched. The statement is still fully indexed
    (`semantic_indexing: full`) and fully addressable, exactly like any other L0.

    `intake_archetype` overrules the proposal for every source of this bundle, exactly as
    `ingest_document`'s does for a single document: a plan is a PROPOSAL (architecture §4),
    and a caller who names an archetype has decided. Unknown names raise rather than falling
    back, because silently proposing when someone stated is the one failure a plan override
    exists to prevent.

    `about_paths` is the OWNER's hint about which canonical pages a statement concerns
    (`pkc owner say --about`, docs/design/coding-agent-mode.md §5.3). It rides the compile
    job's payload and is rendered into that round's source guidance; it points the round at
    pages and changes nothing about what the gate requires of what is written there. A
    caller who states both gets the plan: `intake_plan` is a fully-formed decision, and an
    archetype name is a way of naming one.
    """

    assert_writable(user_id)  # a frozen snapshot tenant is never written (snapshot_tenant.py)
    timestamp = imported_at or datetime.now(timezone.utc)
    # Meeting / IM / email contracts cut sections by calendar day; that day is the subject's
    # (domain/time_context.py), not the provider's offset.
    time = await subject_time_context(ctx, user_id)
    if ctx.media is None:
        declared_images = sum(
            len(message.images)
            for conversation in getattr(contract, "conversations", [])
            for message in getattr(conversation, "messages", [])
        )
        if declared_images:
            raise RuntimeError("image import requires a media store")
        materialized_images = {}
    else:
        materialized_images = await materialize_contract_images(
            ctx.media,
            user_id,
            contract,
            max_bytes=ctx.settings.media_max_image_bytes,
        )
    normalized_sources = normalize_source_contract(
        contract,
        user_id,
        imported_at=timestamp,
        time=time,
        materialized_images=materialized_images,
    )
    plans: list[IntakePlan] = []
    for normalized in normalized_sources:
        raw = normalized.raw
        char_count = sum(len(block.text) for block in normalized.blocks)
        plan = (
            intake_plan
            or (plan_for_archetype(intake_archetype) if intake_archetype else None)
            or propose_intake(
                raw.kind,
                raw.source_class,
                char_count,
                "note" if raw.kind == "document_library" else None,
                owner_turns=len(owner_authored_blocks(raw)),
            )
        )
        plan = with_semantic_retrieval(
            plan, getattr(ctx.settings, "semantic_retrieval", "on") == "on"
        )
        raw.intake_plan = plan.model_dump()
        plans.append(plan)

    # Bundle order is deliberate: make every natural unit searchable before any of
    # them enters L3 compilation. This also keeps bulk import progress intuitive.
    jobs = [SourceImportJob(source.raw.source_id, "index", {"source_id": str(source.raw.source_id)})
            for source in normalized_sources]
    about = [str(path).strip() for path in about_paths if str(path).strip()]
    for source, plan in zip(normalized_sources, plans, strict=True):
        source_id = str(source.raw.source_id)
        if plan.canonical_treatment != "none":
            payload: dict = {
                "source_ids": [source_id],
                "treatments": {source_id: plan.canonical_treatment},
            }
            if about:
                payload["about_paths"] = about
            jobs.append(SourceImportJob(source.raw.source_id, "compile", payload))

    # The store decides new-vs-replay inside the same transaction that persists L0 and
    # every required job. A caller may acknowledge this receipt without leaving a crash
    # window where a replay would find the source but never enqueue its processing.
    receipt = await ctx.store.add_sources_with_jobs(user_id, normalized_sources, jobs)
    results = [IngestResult(item.source_id,
                            IntakePlan.model_validate(item.intake_plan) if item.intake_plan else plan,
                            deduplicated=item.deduplicated)
               for item, plan in zip(receipt.sources, plans, strict=True)]

    return OfficialIngestResult(
        contract_schema=contract.contract_schema,
        sources=results,
        compile_jobs=[job_id for kind, job_id in receipt.jobs if kind == "compile"],
    )
