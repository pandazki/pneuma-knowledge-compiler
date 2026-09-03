"""The framework's access statistics against the live compose postgres.

What only a real PG can prove: the tables apply from the schema file, the write path
ACCUMULATES per day (a target read twice today is one row with two hits, and one
`ON CONFLICT` statement never touches the same row twice even when a claim was both handed
over and cited), an application is AT MOST ONCE per record because the increments and the
`projected_at` stamp commit together, the rows are per tenant (I1), and a replay of this
user's `business` consultations reproduces both tables byte-for-byte — the property that
lets a projection whose substrate is neither L0 nor canonical still be called derived.

The `attention` component is here too, in the shape it now has: FACES over a ledger it does
not own. With it registered and a business consultation applied, the evolve proposal's human
message carries the demand section; with nothing registered it is byte-identical to the
message the framework sent before any of this existed — and the ledger fills either way.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pneuma_knowledge_core.components import (
    register_component,
    reset_components,
)
from pneuma_knowledge_core.domain.consultation import ConsultationRecord, EvidenceRef
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.evolve.propose import _propose_human
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.skill import load_skill_base

from pneuma_knowledge_service.access_stats import (
    RECALL_PROJECTION_JOB_KIND,
    access_stats,
    apply_record,
    rebuild_access_stats,
)
from pneuma_knowledge_service.components.attention import AttentionComponent

FAMILIES = ["memory/people/{slug}.md", "memory/topics/{slug}.md"]
SKILL = load_skill_base("v1")
NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _no_components():
    reset_components()
    yield
    reset_components()


async def _templates(user_id: str) -> list[str]:
    return list(FAMILIES)


def _record(
    consultation_id: str,
    *,
    visitor_class: str = "business",
    handed: tuple[EvidenceRef, ...] = (),
    cited: tuple[EvidenceRef, ...] = (),
    miss: bool = False,
    question: str = "阿宝上个季度盯的是哪条线？",
    minutes: int = 0,
    lane: str = "fast",
) -> ConsultationRecord:
    return ConsultationRecord(
        consultation_id=consultation_id,
        user_id="ignored — the caller's user is the tenant",
        created_at=NOW - timedelta(minutes=minutes),
        lane=lane,
        visitor_class=visitor_class,
        question=question,
        as_of=NOW,
        library_ref="deadbeef",
        evidence_handed=handed,
        citations=cited,
        miss=miss,
    )


MEI = EvidenceRef("claim", "c:aa11bb22", "memory/people/mei-lin.md")
BAO = EvidenceRef("claim", "c:cc33dd44", "memory/people/abao.md")
SPAN = EvidenceRef("window", "src-01 ¶2-4", "")


async def _emit(store, user: UserId, record: ConsultationRecord) -> str | None:
    """What the route does, in one line: write the row, enqueue the job. Returns the job id
    (None for a visitor whose class earns no consumer)."""
    return await store.create_consultation(user, record)


async def _deliver(store, user: UserId, record: ConsultationRecord) -> bool:
    """What the worker does once it claims that job."""
    await _emit(store, user, record)
    return await apply_record(store, user, record)


async def _rows(store, user: UserId) -> tuple[list[dict], list[dict]]:
    since = (NOW - timedelta(days=400)).date()
    return (
        await store.access_hits_since(user, since),
        await store.access_misses_since(user, since),
    )


# ------------------------------------------------------------------------- the delivery


async def test_a_business_row_and_its_job_are_written_together(pg_store, user):
    """Neither half can exist alone: no job names a consultation that is not there, and no
    business record is written with nobody scheduled to read it."""
    job_id = await _emit(pg_store, user, _record("k-1", handed=(MEI,)))

    assert job_id
    jobs = await pg_store.list_jobs(user)
    assert [(j["kind"], j["status"], j["payload"]) for j in jobs] == [
        (RECALL_PROJECTION_JOB_KIND, "queued", {"consultation_id": "k-1"})
    ]


async def test_an_audit_row_is_written_and_nothing_is_queued(pg_store, user):
    job_id = await _emit(pg_store, user, _record("k-a", visitor_class="audit", handed=(MEI,)))

    assert job_id is None
    assert await pg_store.list_jobs(user) == []
    assert [r.consultation_id for r in await pg_store.list_consultations(user)] == ["k-a"]


async def test_a_replayed_record_does_not_mint_a_second_job(pg_store, user):
    """`ON CONFLICT DO NOTHING` on the row, and the enqueue conditional on it: a record
    written twice has one consumer, not two."""
    record = _record("k-1", handed=(MEI,))
    first = await _emit(pg_store, user, record)
    second = await _emit(pg_store, user, record)

    assert first and second is None
    assert len(await pg_store.list_jobs(user)) == 1


# --------------------------------------------------------------------------- the ledger


async def test_a_business_consultation_lands_as_hits_and_a_cited_item_counts_twice(
    pg_store, user
):
    assert await _deliver(
        pg_store, user, _record("k-1", handed=(MEI, BAO, SPAN), cited=(MEI, SPAN))
    )

    hits, misses = await _rows(pg_store, user)
    assert misses == []
    assert {(r["target_kind"], r["target_ref"]): r["hits"] for r in hits} == {
        # handed once + cited once, and the claim's page carries the same weight
        ("claim", "c:aa11bb22"): 2,
        ("document", "memory/people/mei-lin.md"): 2,
        # handed only
        ("claim", "c:cc33dd44"): 1,
        ("document", "memory/people/abao.md"): 1,
        # a span is addressed by its source, never by a page it has none of
        ("source", "src-01"): 2,
    }
    assert {r["day"] for r in hits} == {NOW.date()}


async def test_the_same_record_applied_twice_counts_once(pg_store, user):
    """The at-most-once guarantee, where it lives: the increments and the `projected_at`
    stamp commit in one transaction, so a retried job — a worker killed mid-job, the
    queue's self-heal on restart — writes nothing the first run already wrote."""
    record = _record("k-1", handed=(MEI,))
    assert await _deliver(pg_store, user, record) is True
    assert await apply_record(pg_store, user, record) is False

    hits, _misses = await _rows(pg_store, user)
    assert {r["target_ref"]: r["hits"] for r in hits} == {
        "c:aa11bb22": 1,
        "memory/people/mei-lin.md": 1,
    }


async def test_a_record_with_no_row_is_never_applied(pg_store, user):
    """The stamp is claimed on the consultation row, so a record nothing wrote cannot be
    counted — which is the same mechanism read from the other side."""
    assert await apply_record(pg_store, user, _record("k-ghost", handed=(MEI,))) is False
    assert await _rows(pg_store, user) == ([], [])


async def test_a_miss_is_kept_verbatim_and_counted_per_day(pg_store, user):
    for i in range(3):
        await _deliver(
            pg_store,
            user,
            _record(f"k-m{i}", miss=True, question="报销流程是什么？", minutes=i),
        )

    _hits, misses = await _rows(pg_store, user)
    assert [(r["question"], r["count"]) for r in misses] == [("报销流程是什么？", 3)]


async def test_one_tenants_ledger_is_invisible_to_another(pg_store, user):
    """I1, on the read side of the projection as well as the write side."""
    other = UserId(f"{user}-neighbour")

    await _deliver(pg_store, user, _record("k-1", handed=(MEI,)))
    await _deliver(
        pg_store, other, _record("k-2", handed=(BAO,), miss=True, question="别人的问题")
    )

    mine_hits, mine_misses = await _rows(pg_store, user)
    assert [r["target_ref"] for r in mine_hits] == [
        "c:aa11bb22",
        "memory/people/mei-lin.md",
    ]
    assert mine_misses == []

    component = AttentionComponent(content=pg_store, templates=_templates)
    mine_report = await component.report(user, days=30)
    assert "abao" not in mine_report and "别人的问题" not in mine_report

    assert await access_stats(pg_store, user, [("claim", "c:cc33dd44")], now=NOW.date()) == {
        ("claim", "c:cc33dd44"): {
            "last_accessed_at": None,
            "hits_7d": 0,
            "hits_30d": 0,
            "heat": 0.0,
        }
    }

    await pg_store.delete_user(other)


# ------------------------------------------------------------------------- the read face


async def test_the_read_face_reports_last_access_and_both_windows(pg_store, user):
    """`last_accessed_at` is the whole history's answer; the two counts are the windows'.
    A target read forty days ago has a real last access and no recent hits — the one wrong
    answer a windowed last-access query would give."""
    await _deliver(pg_store, user, _record("k-old", handed=(MEI,), minutes=40 * 24 * 60))
    await _deliver(pg_store, user, _record("k-mid", handed=(MEI,), minutes=10 * 24 * 60))
    await _deliver(pg_store, user, _record("k-new", handed=(MEI,)))

    [(_key, stats)] = (
        await access_stats(
            pg_store, user, [("claim", "c:aa11bb22")], now=NOW.date()
        )
    ).items()

    assert stats["hits_7d"] == 1
    assert stats["hits_30d"] == 2
    assert stats["last_accessed_at"] is not None
    assert (NOW - stats["last_accessed_at"]).total_seconds() < 60
    assert stats["heat"] > 1


async def test_a_target_nobody_read_answers_with_zeros_rather_than_absence(pg_store, user):
    stats = await access_stats(
        pg_store, user, [("document", "memory/topics/pricing.md")], now=NOW.date()
    )
    assert stats[("document", "memory/topics/pricing.md")]["last_accessed_at"] is None


# ----------------------------------------------------------------------------- the replay


async def test_a_rebuild_replays_the_records_into_byte_identical_tables(pg_store, user):
    """The projection is derived from a substrate that is kept rather than derived, and this
    is what makes that reading legitimate: replay the records, get the same rows — hits,
    misses and `last_seen` alike. The replay pages through `list_consultations`, so it is
    the recorded order that decides, not the order the queue happened to drain."""
    records = [
        _record("k-1", handed=(MEI, SPAN), cited=(MEI,), minutes=30),
        _record("k-2", handed=(BAO,), cited=(), minutes=20),
        _record("k-3", handed=(), miss=True, question="报销流程是什么？", minutes=10),
        # written but never influential: a rebuild must not resurrect it either
        _record("k-4", visitor_class="audit", handed=(BAO,), minutes=5),
    ]
    for record in records:
        await _deliver(pg_store, user, record)

    live_hits, live_misses = await _rows(pg_store, user)
    assert live_hits and live_misses

    assert await rebuild_access_stats(pg_store, user) == 3

    assert await _rows(pg_store, user) == (live_hits, live_misses)


async def test_a_rebuild_skips_a_record_whose_own_projection_has_not_run_yet(pg_store, user):
    """The double-count, against the real predicate. API writes stay live during a rebuild:
    a consultation emitted before the scan cursor reaches it is in the table with
    `projected_at` null and its own `recall_projection` job still queued. Replayed here it
    would be counted twice — once into the swap, once by the job that runs afterwards. The
    walk takes only stamped records, which the queue makes sound: this rebuild holds the
    user's one in-flight claim, so no projection can land between the scan and the swap."""
    delivered = _record("k-1", handed=(MEI,), minutes=30)
    await _deliver(pg_store, user, delivered)
    # emitted only: the row and its job exist, the stamp does not
    waiting = _record("k-2", handed=(BAO,), minutes=20)
    await _emit(pg_store, user, waiting)

    assert await rebuild_access_stats(pg_store, user) == 1

    hits, _ = await _rows(pg_store, user)
    assert {r["target_ref"] for r in hits} == {MEI.ref, MEI.path}

    # …and the waiting job then applies it exactly once, on top of the swap.
    assert await apply_record(pg_store, user, waiting)
    hits, _ = await _rows(pg_store, user)
    assert {r["target_ref"]: r["hits"] for r in hits if r["target_ref"] == BAO.ref} == {
        BAO.ref: 1
    }


async def test_a_rebuild_of_a_library_with_no_records_empties_the_tables(pg_store, user):
    """The other half of the same property: rows with nothing behind them do not survive a
    replay, because a replay is the definition of what the rows are."""
    await pg_store.replace_access_stats(
        user,
        [
            {
                "target_kind": "claim",
                "target_ref": "c:aa11bb22",
                "day": NOW.date(),
                "hits": 7,
                "last_seen": NOW,
            }
        ],
        [{"day": NOW.date(), "question": "报销流程是什么？", "count": 2}],
    )
    assert await _rows(pg_store, user) != ([], [])

    assert await rebuild_access_stats(pg_store, user) == 0

    assert await _rows(pg_store, user) == ([], [])


# ------------------------------------------------------------- the component's faces


async def test_the_report_groups_hot_documents_by_family_and_names_the_cold_ones(
    pg_store, user
):
    class _Canonical:
        async def list(self, user_id, *, at=None):
            return [_doc("memory/topics/pricing.md", 9)]

    component = AttentionComponent(
        content=pg_store, canonical=_Canonical(), templates=_templates
    )
    await _deliver(pg_store, user, _record("k-1", handed=(MEI, BAO), cited=(MEI,)))
    await _deliver(pg_store, user, _record("k-2", miss=True, question="报销流程是什么？"))

    report = await component.report(user, days=30)

    assert "memory/people/{slug}.md" in report
    assert "- memory/people/mei-lin.md heat 2" in report
    assert "- memory/people/abao.md heat 1" in report
    # a family holding a document with real claims that nobody read in the window
    assert "- memory/topics/{slug}.md: 1 document(s), 9 claim(s)" in report
    assert "- 1× 报销流程是什么？" in report


async def test_the_stats_accumulate_with_no_component_registered_at_all(pg_store, user):
    """Default-on: unregister the faces and the ledger keeps filling. What an operator
    switches on is what can be READ, never what is counted."""
    from pneuma_knowledge_core.components import registered_components

    assert registered_components() == ()
    await _deliver(pg_store, user, _record("k-1", handed=(MEI,)))

    hits, _misses = await _rows(pg_store, user)
    assert {r["target_ref"] for r in hits} == {
        "c:aa11bb22",
        "memory/people/mei-lin.md",
    }


async def test_the_components_rebuild_leaves_the_ledger_it_reads_alone(pg_store, user):
    """The component owns no rows: its `rebuild` is not a second replay of the framework's
    tables, and a rebuild that ran both would do the same work twice."""
    component = AttentionComponent(content=pg_store, templates=_templates)
    await _deliver(pg_store, user, _record("k-1", handed=(MEI,)))
    before = await _rows(pg_store, user)

    await component.rebuild(str(user))

    assert await _rows(pg_store, user) == before


async def test_an_empty_window_reports_nothing_rather_than_an_empty_report(pg_store, user):
    """`None`, not a block saying the library is unused — a library nobody has asked yet
    has cold families by definition, and reporting them would be an argument built out of
    the absence of evidence."""
    component = AttentionComponent(content=pg_store, templates=_templates)
    assert await component.evolve_evidence(str(user)) is None

    await _deliver(pg_store, user, _record("k-1", handed=(MEI,)))
    block = await component.evolve_evidence(str(user))
    assert block is not None and "memory/people/mei-lin.md" in block


async def test_the_block_is_capped_in_characters_and_says_what_it_cut(pg_store, user):
    component = AttentionComponent(
        content=pg_store, templates=_templates, evidence_chars=120
    )
    for i in range(30):
        await _deliver(
            pg_store,
            user,
            _record(
                f"k-{i}",
                handed=(EvidenceRef("claim", f"c:{i:08x}", f"memory/people/p{i:02d}.md"),),
            ),
        )

    block = await component.evolve_evidence(str(user))

    assert len(block) <= 120 + 80  # the closing line is allowed past the budget, once
    assert "more line(s) not shown" in block
    assert not block.endswith("memory/people/p")  # never cut mid-line


async def test_the_demand_section_reaches_the_evolve_message_only_when_registered(
    pg_store, user
):
    """Acceptance 4, end to end over a real ledger: the same call, the same library, and
    the section appears exactly when a component contributed one."""
    from pneuma_knowledge_core.components import collect_evolve_evidence

    baseline = _propose_human(SKILL, [], ["memory/people/mei-lin.md"])
    assert await collect_evolve_evidence(str(user)) is None
    assert (
        _propose_human(SKILL, [], ["memory/people/mei-lin.md"], None) == baseline
    )

    await _deliver(pg_store, user, _record("k-1", handed=(MEI,), cited=(MEI,)))
    register_component(AttentionComponent(content=pg_store, templates=_templates))

    evidence = await collect_evolve_evidence(str(user))
    assert evidence is not None and evidence.startswith("## attention\n")

    message = _propose_human(SKILL, [], ["memory/people/mei-lin.md"], evidence)
    assert message.startswith(baseline)
    assert prompt("evolve.propose.demand_header") in message
    assert "memory/people/mei-lin.md heat 2" in message


def _doc(path: str, claims: int):
    """A canonical document holding `claims` anchored, cited claims."""
    from pneuma_knowledge_core.domain.canonical import CanonicalDocument

    body = "\n".join(
        f"- 定价在三月改过。 [cite: src-01 ¶{i}] <!-- c:{i:08x} -->"
        for i in range(claims)
    )
    return CanonicalDocument(
        doc_id="d-pricing",
        path=path,
        frontmatter={"doc_id": "d-pricing", "type": "topic", "slug": "pricing"},
        body=f"# 定价\n\n## 台账\n\n{body}\n",
    )


async def test_deleting_a_tenant_takes_its_questions_and_its_ledger_with_it(pg_store, user):
    """Neither table hangs off a source, so nothing cascades: a consultation holds the
    owner's questions verbatim, and a tenant deletion that left them behind would leave
    exactly the rows nobody would think to look for."""
    await _deliver(
        pg_store, user, _record("k-1", handed=(MEI,), miss=True, question="报销流程是什么？")
    )
    assert await _rows(pg_store, user) != ([], [])

    await pg_store.delete_user(user)

    assert await _rows(pg_store, user) == ([], [])
    assert await pg_store.list_consultations(user) == []
