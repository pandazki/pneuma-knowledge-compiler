"""The read face of the use-side: the consultations listing, one record, and the ledger's
top-N — over the real postgres, because every one of these properties is a SQL property.

What is being asked here is whether the AUDIT CHAIN is reachable. A consultation that can be
written and never read back is a record nobody can check, and a reverse lookup that answers
"nothing" for the page a reader clicked from is worse than no link at all — so the target
filter is exercised on all three ways an address reaches a record: the claim's own anchor,
the span it cites, and the PAGE that claim lives on, which never appears as a `ref`.

Skips (only) when postgres is unreachable — the sanctioned reason.
"""

from __future__ import annotations

import socket
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
import pytest
from pneuma_knowledge_core.domain.consultation import ConsultationRecord, EvidenceRef
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.access_stats import apply_record
from pneuma_knowledge_service.settings import Settings

DAY = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)
PAGE = "memory/people/bao.md"
OTHER_PAGE = "memory/topics/delivery.md"


def _open(url: str, default: int) -> bool:
    p = urlparse(url if "://" in url else f"//{url}")
    try:
        with socket.create_connection((p.hostname, p.port or default), timeout=1.5):
            return True
    except OSError:
        return False


@asynccontextmanager
async def _client(app):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app
            yield c


@pytest.fixture
async def client(tmp_path):
    """The app over the real PG. No model and no retrieval run here: every consultation in
    this file is written straight through the store, because what is under test is the READ
    face and seeding it through six lane calls would be testing the lanes again."""
    s = Settings(canonical_root=str(tmp_path / "canonical"))
    if not _open(s.pg_dsn, 5432):
        pytest.skip("postgres unreachable")
    async with _client(create_app(s)) as c:
        yield c


def _record(
    user: str,
    consultation_id: str,
    *,
    minute: int,
    lane: str = "fast",
    visitor_class: str = "business",
    miss: bool = False,
    handed: tuple[EvidenceRef, ...] = (),
    cited: tuple[EvidenceRef, ...] = (),
    question: str | None = None,
    created_at: datetime | None = None,
    token_usage: tuple[tuple[str, int], ...] = (),
) -> ConsultationRecord:
    return ConsultationRecord(
        consultation_id=consultation_id,
        user_id=user,
        created_at=(created_at or DAY) + timedelta(minutes=minute),
        lane=lane,
        visitor_class=visitor_class,
        question=question or f"阿宝在第 {minute} 分钟问的问题",
        as_of=DAY,
        library_ref="a1b2c3d4",
        evidence_handed=handed,
        answer_kind="no_record" if miss else "fact",
        answer="" if miss else "他在三月接手。",
        citations=cited,
        miss=miss,
        degraded=(),
        token_usage=token_usage,
    )


async def _seed(client, user: str, records) -> None:
    store = client.app.state.ctx.store
    for record in records:
        await store.create_consultation(UserId(user), record)


def _ids(body) -> list[str]:
    return [item["consultation_id"] for item in body["items"]]


# ------------------------------------------------------------------- the listing


async def test_the_listing_is_newest_first_and_pages_without_shifting(client):
    """Keyset, descending, and continued on `(created_at, consultation_id)` — the same
    cursor contract every other collection takes, so a row landing mid-walk never pushes a
    record onto a page the reader already passed."""
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    await _seed(
        client,
        user,
        [_record(user, f"k-{n}", minute=n) for n in range(5)],
    )

    first = (await client.get(f"/v1/users/{user}/consultations?limit=2")).json()
    assert _ids(first) == ["k-4", "k-3"]
    assert first["page"]["total"] == 5
    assert first["page"]["next_cursor"]

    second = (
        await client.get(
            f"/v1/users/{user}/consultations",
            params={"limit": 2, "cursor": first["page"]["next_cursor"]},
        )
    ).json()
    assert _ids(second) == ["k-2", "k-1"]

    last = (
        await client.get(
            f"/v1/users/{user}/consultations",
            params={"limit": 2, "cursor": second["page"]["next_cursor"]},
        )
    ).json()
    assert _ids(last) == ["k-0"]
    assert last["page"]["next_cursor"] is None


async def test_a_cursor_from_another_filter_set_is_refused(client):
    """The filters are bound INTO the cursor: continuing a `lane=fast` walk with `lane=deep`
    is a 422, never a silent first page of the other list."""
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    await _seed(client, user, [_record(user, f"k-{n}", minute=n) for n in range(3)])

    page = (
        await client.get(f"/v1/users/{user}/consultations", params={"limit": 1, "lane": "fast"})
    ).json()
    bad = await client.get(
        f"/v1/users/{user}/consultations",
        params={"limit": 1, "lane": "deep", "cursor": page["page"]["next_cursor"]},
    )
    assert bad.status_code == 422
    assert (await client.get(f"/v1/users/{user}/consultations?cursor=not-a-cursor")).status_code == 422


async def test_each_filter_selects_what_it_names(client):
    """lane, visitor class and miss — the three axes a reader scans a consultation list on."""
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    await _seed(
        client,
        user,
        [
            _record(user, "k-fast", minute=0),
            _record(user, "k-deep", minute=1, lane="deep"),
            _record(user, "k-audit", minute=2, visitor_class="audit"),
            _record(user, "k-miss", minute=3, miss=True, question="谁签的第二批验收？"),
        ],
    )
    base = f"/v1/users/{user}/consultations"

    assert _ids((await client.get(base, params={"lane": "deep"})).json()) == ["k-deep"]
    assert _ids((await client.get(base, params={"visitor_class": "audit"})).json()) == ["k-audit"]
    assert _ids((await client.get(base, params={"miss": True})).json()) == ["k-miss"]
    assert _ids((await client.get(base, params={"miss": False})).json()) == [
        "k-audit",
        "k-deep",
        "k-fast",
    ]
    # A miss carries the question and no citation — which is the whole of what it has to say.
    row = (await client.get(base, params={"miss": True})).json()["items"][0]
    assert row["question"] == "谁签的第二批验收？"
    assert row["citation_count"] == 0 and row["answer_kind"] == "no_record"


async def test_the_target_lookup_finds_a_page_reached_through_its_claims(client):
    """The reverse lookup, on every shape an address arrives in.

    `k-claim` never names the page as a `ref` — the page rides along as the claim's `path`,
    which is exactly how the ledger counts a document. A lookup that matched `ref` only would
    answer "no consultations" for the page whose own access card offered the link.
    """
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    await _seed(
        client,
        user,
        [
            _record(
                user,
                "k-claim",
                minute=0,
                handed=(EvidenceRef("claim", "c:aa11", PAGE),),
            ),
            _record(
                user,
                "k-span",
                minute=1,
                handed=(EvidenceRef("window", "src-01 ¶2-4", ""),),
            ),
            _record(
                user,
                "k-page",
                minute=2,
                handed=(EvidenceRef("document", OTHER_PAGE, ""),),
            ),
            _record(
                user,
                "k-cited",
                minute=3,
                handed=(EvidenceRef("claim", "c:bb22", OTHER_PAGE),),
                cited=(EvidenceRef("claim", "c:aa11", PAGE),),
            ),
            _record(user, "k-nothing", minute=4),
        ],
    )
    base = f"/v1/users/{user}/consultations"

    # The page, reached through a claim that lives on it — and through a claim CITED on it.
    assert _ids((await client.get(base, params={"target": PAGE})).json()) == [
        "k-cited",
        "k-claim",
    ]
    # The claim's own anchor finds both the handing and the citing.
    assert _ids((await client.get(base, params={"target": "c:aa11"})).json()) == [
        "k-cited",
        "k-claim",
    ]
    # A span, in the one citation grammar.
    assert _ids((await client.get(base, params={"target": "src-01 ¶2-4"})).json()) == ["k-span"]
    # A page opened and read in full, whose path IS the ref.
    assert _ids((await client.get(base, params={"target": OTHER_PAGE})).json()) == [
        "k-cited",
        "k-page",
    ]
    assert _ids((await client.get(base, params={"target": "c:zz99"})).json()) == []


async def test_one_tenants_consultations_are_invisible_to_another(client):
    """I1 on the read side: the listing and the detail route are keyed by user first, so a
    cross-tenant read is an empty page and a 404 rather than a check that could be skipped."""
    mei = f"u-it-{uuid.uuid4().hex[:10]}"
    bao = f"u-it-{uuid.uuid4().hex[:10]}"
    await _seed(client, mei, [_record(mei, "k-1", minute=0)])

    assert _ids((await client.get(f"/v1/users/{mei}/consultations")).json()) == ["k-1"]
    assert _ids((await client.get(f"/v1/users/{bao}/consultations")).json()) == []
    assert (await client.get(f"/v1/users/{bao}/consultations/k-1")).status_code == 404


async def test_the_detail_route_returns_the_whole_audit_chain(client):
    """What the listing leaves out: the addresses, the answer, and which addresses it cited —
    citations a strict subset of what was handed over, as the record's construction makes
    them."""
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    handed = (
        EvidenceRef("claim", "c:aa11", PAGE),
        EvidenceRef("window", "src-01 ¶2-4", ""),
    )
    await _seed(
        client,
        user,
        [_record(user, "k-1", minute=0, handed=handed, cited=(handed[1],))],
    )

    body = (await client.get(f"/v1/users/{user}/consultations/k-1")).json()
    assert body["lane"] == "fast" and body["visitor_class"] == "business"
    assert body["library_ref"] == "a1b2c3d4"
    assert body["answer"] == "他在三月接手。"
    assert [r["ref"] for r in body["evidence_handed"]] == ["c:aa11", "src-01 ¶2-4"]
    assert [r["ref"] for r in body["citations"]] == ["src-01 ¶2-4"]
    assert body["evidence_handed"][0]["path"] == PAGE
    assert body["citation_count"] == 1 and body["evidence_count"] == 2
    assert (await client.get(f"/v1/users/{user}/consultations/nope")).status_code == 404


# ------------------------------------------------------------------- the ledger's top-N


async def test_the_top_list_ranks_documents_and_counts_misses(client):
    """The dashboard's half: hottest documents and most-asked misses, over a stated window.

    Seeded through `apply_record` rather than by hand, so what is ranked is what the queue's
    own consumer would have written — including the rule that a document counts once per
    PASS however many of its claims travelled, where the handing and the citing are two
    passes: evidence merely handed over counts once, evidence the answer went on to cite
    counts once more.
    """
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    store = client.app.state.ctx.store
    now = datetime.now(timezone.utc)
    records = [
        # PAGE: three passes today, one of them citing as well as handing.
        _record(user, "t-1", minute=0, created_at=now, handed=(EvidenceRef("claim", "c:aa11", PAGE),)),
        _record(user, "t-2", minute=1, created_at=now, handed=(EvidenceRef("claim", "c:bb22", PAGE),)),
        _record(
            user,
            "t-3",
            minute=2,
            created_at=now,
            handed=(EvidenceRef("claim", "c:aa11", PAGE),),
            cited=(EvidenceRef("claim", "c:aa11", PAGE),),
        ),
        # OTHER_PAGE: one pass.
        _record(user, "t-4", minute=3, created_at=now, handed=(EvidenceRef("document", OTHER_PAGE, ""),)),
        # Two misses, one of them asked twice.
        _record(user, "t-5", minute=4, created_at=now, miss=True, question="第二批验收谁签的？"),
        _record(user, "t-6", minute=5, created_at=now, miss=True, question="第二批验收谁签的？"),
        _record(user, "t-7", minute=6, created_at=now, miss=True, question="momo 的合同到期了吗？"),
    ]
    for record in records:
        await store.create_consultation(UserId(user), record)
        await apply_record(store, UserId(user), record)

    body = (await client.get(f"/v1/users/{user}/access-stats/top", params={"days": 7})).json()
    assert body["window_days"] == 7
    assert body["since"] and body["until"] and body["half_life_days"] > 0

    paths = [d["path"] for d in body["documents"]]
    assert paths[:2] == [PAGE, OTHER_PAGE]
    hot = body["documents"][0]
    # Three consultations reached the page, and the third also CITED a claim on it: four
    # passes, four hits. Two different claims travelled in those manifests and the page
    # still counts once per pass — length is not attention.
    assert hot["hits_7d"] == 4 and hot["hits_30d"] == 4
    assert hot["heat"] > body["documents"][1]["heat"]
    assert hot["last_accessed_at"]

    assert [m["question"] for m in body["misses"]] == [
        "第二批验收谁签的？",
        "momo 的合同到期了吗？",
    ]
    assert body["misses"][0]["count"] == 2 and body["misses"][1]["count"] == 1
    assert body["misses"][0]["last_day"]

    # `limit` bounds both halves.
    small = (
        await client.get(f"/v1/users/{user}/access-stats/top", params={"days": 7, "limit": 1})
    ).json()
    assert len(small["documents"]) == 1 and len(small["misses"]) == 1


async def test_a_library_nobody_has_read_answers_with_two_empty_lists(client):
    """Never a 404: "nobody has read anything yet" is an answer, and a dashboard that
    errored on a new library would be reporting on its own emptiness."""
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    resp = await client.get(f"/v1/users/{user}/access-stats/top")
    assert resp.status_code == 200
    assert resp.json()["documents"] == [] and resp.json()["misses"] == []


# ------------------------------------------------------------- what it spent, and cost

#: One consultation's usage, in the shape every lane reports. Numbers taken from a real
#: bench tick so the arithmetic below is checked against a plausible call, not a round one.
SPENT = (
    ("input_tokens", 4310),
    ("output_tokens", 182),
    ("total_tokens", 4492),
    ("cache_read", 1780),
    ("cache_creation", 2524),
)
#: 1.25 / 10 / 0.125 / 1.25 per 1M, on a model this deployment invents for itself.
PRICED = Settings(
    llm_model="openrouter:test/luna-x",
    model_pricing="openrouter:test/luna-x = 1.25/10/0.125/1.25 USD",
)


def _expected_amount() -> float:
    fresh = 4310 - 1780 - 2524  # negative: the provider's parts overshoot, so it clamps
    return round(
        (max(0, fresh) * 1.25 + 1780 * 0.125 + 2524 * 1.25 + 182 * 10) / 1_000_000, 6
    )


@pytest.fixture
async def priced_client(tmp_path):
    """The same app, for a deployment that HAS declared what its models cost."""
    s = PRICED.model_copy(update={"canonical_root": str(tmp_path / "canonical")})
    if not _open(s.pg_dsn, 5432):
        pytest.skip("postgres unreachable")
    async with _client(create_app(s)) as c:
        yield c


async def test_what_a_consultation_spent_reaches_both_the_listing_and_the_record(client):
    """Usage is a fact about the call, so it rides the row rather than a side ledger — and
    it is on the LISTING too, because "what has this been costing me" is a question about a
    list."""
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    await _seed(client, user, [_record(user, "k-1", minute=1, token_usage=SPENT)])

    listing = (await client.get(f"/v1/users/{user}/consultations")).json()
    assert listing["items"][0]["token_usage"] == dict(SPENT)
    detail = (await client.get(f"/v1/users/{user}/consultations/k-1")).json()
    assert detail["token_usage"] == dict(SPENT)


async def test_a_deployment_that_declared_no_price_is_shown_tokens_and_no_money(client):
    """Not a zero. "Nobody said what this costs" and "it was free" are different answers."""
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    await _seed(client, user, [_record(user, "k-1", minute=1, token_usage=SPENT)])

    listing = (await client.get(f"/v1/users/{user}/consultations")).json()
    assert listing["items"][0]["cost"] is None
    assert (await client.get(f"/v1/users/{user}/consultations/k-1")).json()["cost"] is None


async def test_declared_prices_put_money_beside_the_tokens_on_both_faces(priced_client):
    """The input is billed in three parts, because the provider's cache counters are subsets
    of `input_tokens` rather than additions to it."""
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    await _seed(priced_client, user, [_record(user, "k-1", minute=1, token_usage=SPENT)])

    listing = (await priced_client.get(f"/v1/users/{user}/consultations")).json()
    assert listing["items"][0]["cost"] == {
        "amount": _expected_amount(),
        "currency": "USD",
    }
    detail = (await priced_client.get(f"/v1/users/{user}/consultations/k-1")).json()
    assert detail["cost"] == {"amount": _expected_amount(), "currency": "USD"}


async def test_spend_sums_the_window_and_groups_it_by_lane_and_by_visitor_class(client):
    """One aggregate read out of the consultations table alone — no counter incremented
    anywhere, so it cannot drift from the records it describes."""
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    await _seed(
        client,
        user,
        [
            _record(user, "k-1", minute=0, lane="fast", visitor_class="business",
                    created_at=now - timedelta(hours=1), token_usage=SPENT),
            _record(user, "k-2", minute=0, lane="fast", visitor_class="audit",
                    created_at=now - timedelta(hours=2), token_usage=SPENT),
            _record(user, "k-3", minute=0, lane="deep", visitor_class="business",
                    created_at=now - timedelta(hours=3), token_usage=SPENT),
            # Outside the window: recorded, and simply not part of this question.
            _record(user, "k-old", minute=0, lane="fast", visitor_class="business",
                    created_at=now - timedelta(days=90), token_usage=SPENT),
        ],
    )

    body = (await client.get(f"/v1/users/{user}/consultations/spend?days=30")).json()
    assert body["window_days"] == 30
    assert body["consultations"] == 3
    assert body["token_usage"]["input_tokens"] == 4310 * 3
    assert body["token_usage"]["cache_read"] == 1780 * 3
    assert {g["key"]: g["consultations"] for g in body["by_lane"]} == {"fast": 2, "deep": 1}
    assert {g["key"]: g["consultations"] for g in body["by_visitor_class"]} == {
        "business": 2,
        "audit": 1,
    }
    assert body["cost"] is None  # no rates declared, so tokens only


async def test_spend_reports_money_once_the_deployment_declares_its_rates(priced_client):
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    await _seed(
        priced_client,
        user,
        [
            _record(user, "k-1", minute=0, created_at=now - timedelta(hours=1),
                    token_usage=SPENT),
            _record(user, "k-2", minute=0, created_at=now - timedelta(hours=2),
                    token_usage=SPENT),
        ],
    )
    body = (await priced_client.get(f"/v1/users/{user}/consultations/spend")).json()
    assert body["cost"] == {"amount": round(_expected_amount() * 2, 6), "currency": "USD"}
    assert body["by_lane"][0]["cost"]["currency"] == "USD"


async def test_a_window_holding_a_call_that_reported_no_usage_is_marked_incomplete(
    priced_client,
):
    """A provider that reports no usage stores `{}`. Every SQL sum over it is null and
    coalesces to zero, so after the summation an unmeasured call is indistinguishable from
    one that was genuinely free — and the money over it was a partial presented as exact.
    The window says how many of its consultations reported anything, marks itself
    incomplete, and shows tokens with no amount beside them."""
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    await _seed(
        priced_client,
        user,
        [
            _record(user, "k-1", minute=0, created_at=now - timedelta(hours=1),
                    token_usage=SPENT),
            # the provider reported nothing for this one
            _record(user, "k-2", minute=0, created_at=now - timedelta(hours=2)),
        ],
    )

    body = (await priced_client.get(f"/v1/users/{user}/consultations/spend")).json()

    assert body["consultations"] == 2 and body["with_usage"] == 1
    assert body["incomplete"] is True
    assert body["token_usage"]["input_tokens"] == 4310  # the one that was measured
    assert body["cost"] is None
    [lane] = body["by_lane"]
    assert (lane["consultations"], lane["with_usage"], lane["incomplete"]) == (2, 1, True)
    assert lane["cost"] is None

    # …and a window where every call reported its counters is complete and priced.
    whole = f"u-it-{uuid.uuid4().hex[:10]}"
    await _seed(
        priced_client,
        whole,
        [_record(whole, "k-1", minute=0, created_at=now, token_usage=SPENT)],
    )
    body = (await priced_client.get(f"/v1/users/{whole}/consultations/spend")).json()
    assert body["with_usage"] == body["consultations"] == 1
    assert body["incomplete"] is False
    assert body["cost"] == {"amount": _expected_amount(), "currency": "USD"}


async def test_an_empty_window_is_zeros_rather_than_a_404(client):
    """"Nobody has asked anything yet" is an answer."""
    user = f"u-it-{uuid.uuid4().hex[:10]}"
    body = (await client.get(f"/v1/users/{user}/consultations/spend")).json()
    assert body["consultations"] == 0
    assert body["by_lane"] == [] and body["by_visitor_class"] == []
    assert body["cost"] is None


async def test_one_tenants_spend_never_counts_anothers(client):
    """I1 at the aggregate: the sum is keyed by user first, like every read."""
    mei = f"u-it-{uuid.uuid4().hex[:10]}"
    bao = f"u-it-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    await _seed(client, mei, [_record(mei, "k-1", minute=0, created_at=now, token_usage=SPENT)])
    body = (await client.get(f"/v1/users/{bao}/consultations/spend")).json()
    assert body["consultations"] == 0
    assert body["token_usage"] == {}
