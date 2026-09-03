"""The `people` component through its faces, keyless and store-free: identities and
aliases as frontmatter — written whole with the overview, an identity bound by at most one
page and an alias never another person's name; the outline tail; `find_person`; and the
closed-world `enumerate_identities` over L0 source metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import count

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr
from pneuma_knowledge_core.canonical_glance import render_outline
from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError
from pneuma_knowledge_core.compile.documents import Overview
from pneuma_knowledge_core.compile.gate import run_gate
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import _build_tools
from pneuma_knowledge_core.components import register_component, reset_components
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, SourceId, UserId
from pneuma_knowledge_core.domain.source import RawSource

from pneuma_knowledge_service.components.people import (
    NAME_MATCH_CANDIDATES,
    PeopleComponent,
    identity_mentions,
    name_keys,
    split_cjk_name,
    strip_honorific,
    summarize_identities,
)
from pneuma_knowledge_service.wiring import register_components
from pneuma_knowledge_service.settings import Settings

FAMILY = "memory/people/{slug}.md"
TEMPLATES = ["memory/profile.md", FAMILY, "memory/topics/{slug}.md"]
USER = UserId("u-1")


@pytest.fixture(autouse=True)
def _clean():
    reset_components()
    yield
    reset_components()


def _person(slug: str, identities: str = "", aliases: str = "", title: str | None = None):
    fm = {"doc_id": f"d-{slug}", "type": "person", "slug": slug}
    if identities:
        fm["identities"] = identities
    if aliases:
        fm["aliases"] = aliases
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=f"memory/people/{slug}.md",
        frontmatter=fm,
        body=f"# {title or slug}\n\n- 事实。[cite: src-01 ¶0] <!-- c:{slug[:4].ljust(4, '0')} -->",
    )


def _path(component, name: str = "person"):
    """The named fast path off a component that now offers more than one."""
    return next(p for p in component.fast_paths(USER) if p.name == name)


def _raw(sid: str, kind: str, meta: dict, day: str) -> RawSource:
    return RawSource(
        source_id=SourceId(sid),
        user_id=USER,
        kind=kind,
        title=sid,
        mime="text/plain",
        checksum=sid,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        meta={**meta, "occurred_on": day},
    )


MEETING = _raw(
    "m1",
    "meeting",
    {
        "owner_participant_ids": ["p_owner"],
        "participants": [
            {"participant_id": "p_owner", "display_name": "林舟", "email": "zhou@self.example"},
            {"participant_id": "p_jia", "display_name": "贾宁", "email": "JiaNing@hengyin-print.example"},
            {"participant_id": "p_x", "display_name": "唐可", "email": None},
        ],
    },
    "2025-06-02",
)
IM = _raw(
    "i1",
    "im",
    {
        "owner_user_ids": ["u_owner"],
        "users": [
            {"user_id": "u_owner", "display_name": "林舟", "email": None, "is_bot": False},
            {"user_id": "u_8812", "display_name": "Lin Jia", "email": None, "is_bot": False},
            {"user_id": "u_bot", "display_name": "bot", "email": None, "is_bot": True},
        ],
    },
    "2026-04-12",
)
EMAIL = _raw(
    "e1",
    "email",
    {
        "owner_addresses": ["zhou@self.example"],
        "messages": [
            {
                "from": {"address": "sales@qingyun-print.example", "display_name": "青云印刷 销售"},
                "to": [{"address": "zhou@self.example", "display_name": "林舟"}],
                "cc": [{"address": "jianing@hengyin-print.example", "display_name": "贾宁"}],
            }
        ],
    },
    "2025-03-01",
)


class _Content:
    """L0 as the component sees it: `list` gives the raw sources, `get` gives one back with
    its blocks (the address-term scan reads turn TEXT, which meta cannot reconstruct)."""

    def __init__(self, sources):
        self._sources = list(sources)
        #: the `after` watermark of every incremental read, in order — what pins that a
        #: second job asks the store for the new sources rather than for the library
        self.since_calls: list[tuple | None] = []

    async def list(self, user_id):
        assert user_id == USER
        return [getattr(s, "raw", s) for s in self._sources]

    async def list_since(self, user_id, *, after=None):
        """The port's incremental read, over the same rows `list` answers with — so a
        subclass that makes `list` fail still fails here, as a real store would."""
        self.since_calls.append(after)
        rows = sorted(
            await self.list(user_id), key=lambda r: (r.created_at, str(r.source_id))
        )
        if after is None:
            return rows
        return [r for r in rows if (r.created_at, str(r.source_id)) > after]

    async def get(self, user_id, source_id):
        from pneuma_knowledge_core.domain.source import NormalizedSource, StructureMap

        for source in self._sources:
            raw = getattr(source, "raw", source)
            if str(raw.source_id) != str(source_id):
                continue
            if hasattr(source, "raw"):
                return source
            return NormalizedSource(raw=raw, blocks=[], structure=StructureMap())
        raise KeyError(source_id)


class _Canonical:
    def __init__(self, docs):
        self._docs = docs

    async def list(self, user_id, *, at=None):
        return list(self._docs)


# --- L0 extraction --------------------------------------------------------------------


def test_identities_come_from_the_source_contracts_owner_and_bots_excluded():
    assert [(m.identity, m.display_name) for m in identity_mentions(MEETING)] == [
        ("mailto:jianing@hengyin-print.example", "贾宁"),
        ("meeting:p_x", "唐可"),
    ]
    assert [m.identity for m in identity_mentions(IM)] == ["im:u_8812"]
    assert [m.identity for m in identity_mentions(EMAIL)] == [
        "mailto:sales@qingyun-print.example",
        "mailto:jianing@hengyin-print.example",
    ]


def test_enumeration_is_closed_over_the_window_and_collapses_the_same_email():
    all_year = summarize_identities([MEETING, IM, EMAIL], since="2025-01-01", until="2025-12-31")
    assert [(s.identity, len(s.source_ids), s.first, s.last) for s in all_year] == [
        ("mailto:jianing@hengyin-print.example", 2, "2025-03-01", "2025-06-02"),
        ("mailto:sales@qingyun-print.example", 1, "2025-03-01", "2025-03-01"),
        ("meeting:p_x", 1, "2025-06-02", "2025-06-02"),
    ]
    assert [s.identity for s in summarize_identities([MEETING, IM, EMAIL], since="2026-01-01")] == ["im:u_8812"]


# --- the four faces -----------------------------------------------------------------------


def test_gate_rejects_a_duplicate_identity_and_a_bad_shape_on_the_pages_it_touched():
    """The identity half of the rule. A page may be written whole — a name dropped, an old
    email replaced — because the frontmatter is a snapshot of the picture, not a ledger. What
    it may NOT do is claim an identity another page holds, or write one no machine can
    compare."""
    component = PeopleComponent(FAMILY)
    register_component(component)
    base = _person("jia-ning", "mailto:jianing@hengyin-print.example", "贾宁, 老贾")
    draft = PatchDraft.from_canonical([base], TEMPLATES)
    # second page claims the same email (different case) — one identity, one page
    draft.create_document(
        "memory/people/lin-jia.md",
        {"type": "person", "slug": "lin-jia", "identities": ["im:u_8812", "MAILTO:JiaNing@hengyin-print.example"]},
        "# Lin Jia\n\n- 新事实。[cite: src-01 ¶0]",
    )
    # the base page drops an alias (ordinary — it is a snapshot) and writes a malformed identity
    working = draft.documents()["memory/people/jia-ning.md"]
    working.frontmatter["aliases"] = "贾宁"
    working.frontmatter["identities"] = "mailto:jianing@hengyin-print.example, jianing"
    kinds = sorted(v.kind for v in run_gate(draft, []) if v.kind.startswith("people."))
    # the duplicate is named on BOTH pages — either one of them is the wrong one, and the
    # gate does not decide which; the dropped alias is not a violation at all
    assert kinds == [
        "people.identity_duplicate",
        "people.identity_duplicate",
        "people.identity_shape",
    ]
    # a list handed in by the model was folded to the one on-disk scalar spelling
    assert draft.documents()["memory/people/lin-jia.md"].frontmatter["identities"] == (
        "im:u_8812, MAILTO:JiaNing@hengyin-print.example"
    )


def test_the_fields_are_a_snapshot_and_the_outline_shows_identities_and_aliases():
    register_component(PeopleComponent(FAMILY))
    base = _person("jia-ning", "mailto:jianing@hengyin-print.example", "贾宁, 老贾")
    draft = PatchDraft.from_canonical([base], TEMPLATES)
    working = draft.documents()["memory/people/jia-ning.md"]
    # grown, shrunk and replaced in one write — all three are ordinary
    working.frontmatter["identities"] = "mailto:jia.ning@hengyin-print.example, im:u_8812"
    working.frontmatter["aliases"] = "贾宁, Lin Jia"
    assert [v for v in run_gate(draft, []) if v.kind.startswith("people.")] == []

    lines = render_outline([_person("jia-ning", "mailto:jianing@hengyin-print.example", "贾宁, 老贾"), _person("topic-x")])
    assert lines[1].strip() == "identities: mailto:jianing@hengyin-print.example · aliases: 贾宁, 老贾"
    assert len(lines) == 3  # the page without fields gets no tail


def _im_users(*users) -> RawSource:
    return _raw(
        "i_group",
        "im",
        {
            "owner_user_ids": ["u_owner"],
            "users": [
                {"user_id": "u_owner", "display_name": "林舟", "email": None},
                *(
                    {"user_id": uid, "display_name": name, "email": None}
                    for uid, name in users
                ),
            ],
        },
        "2026-04-12",
    )


def _normalized(raw: RawSource):
    from pneuma_knowledge_core.domain.source import NormalizedSource, StructureMap

    return NormalizedSource(raw=raw, blocks=[], structure=StructureMap())


YONG = "memory/people/yong-bai.md"
JIE = "memory/people/jie-wang.md"


def test_an_alias_may_not_be_another_persons_name():
    """The defect this rule exists for: a compile read the group chat titled "Yong BAI,
    Jie WANG, Fan WANG" and wrote two OTHER people's names into Yong's aliases. Whether
    a name is somebody else's is a FACT — another page holds it, or the sources record it as
    an identity's display name — so it is refused mechanically, at the write face and again
    at the gate."""
    component = PeopleComponent(FAMILY)
    register_component(component)
    draft = PatchDraft.from_canonical(
        [
            _person("yong-bai", "im:u_yb", title="Yong BAI"),
            _person("jie-wang", "im:u_jie", "老杰", title="Jie WANG"),
        ],
        TEMPLATES,
    )
    draft.mark_read(YONG)
    # this compile's sources: the three of them in one group chat
    component.compile_tools(
        draft,
        sources=[_normalized(_im_users(("u_jie", "Jie WANG"), ("u_fan", "Fan WANG")))],
    )
    for alias, said in (
        ("Jie WANG", f"the title of `{JIE}`"),
        ("老杰", f"the alias of `{JIE}`"),
        ("jie-wang", f"the slug of `{JIE}`"),
        ("fan wang", "the display name this library's sources record for im:u_fan"),
    ):
        with pytest.raises(AnchorToolError) as err:
            draft.set_fields(YONG, {"aliases": alias})
        assert f"alias {alias!r} is already {said}" in str(err.value)
        assert "leave it out" in str(err.value)
    # nothing was written by any of those refusals
    assert "aliases" not in draft.documents()[YONG].frontmatter
    # the person's OWN name and the names nobody else holds go straight in
    doc = draft.set_fields(YONG, {"aliases": "Yong BAI, 白工", "identities": "im:u_yb"})
    assert doc.frontmatter["aliases"] == "Yong BAI, 白工"
    assert [v for v in run_gate(draft, []) if v.kind.startswith("people.")] == []


def test_a_name_the_same_call_binds_an_identity_for_is_the_persons_own():
    """The ordinary flow must stay open: the fields are written WHOLE, so the identities in
    the call are the page's identities, and the display name of one of them is this person's
    name however many other people share the source."""
    component = PeopleComponent(FAMILY)
    register_component(component)
    draft = PatchDraft.from_canonical([_person("yb", title="小王")], TEMPLATES)
    draft.mark_read("memory/people/yb.md")
    component.compile_tools(
        draft,
        sources=[_normalized(_im_users(("u_yb", "Yong BAI"), ("u_jie", "Jie WANG")))],
    )
    doc = draft.set_fields(
        "memory/people/yb.md", {"identities": "im:u_yb", "aliases": "Yong BAI"}
    )
    assert doc.frontmatter["aliases"] == "Yong BAI"
    # …and the other person in the same source is still refused
    with pytest.raises(AnchorToolError) as err:
        draft.set_fields("memory/people/yb.md", {"aliases": "Jie WANG"})
    assert "im:u_jie" in str(err.value)


def test_a_collision_already_on_disk_stops_nothing_until_that_page_is_written():
    """Grandfathering, for the same reason the overview's grounding check has it: a wrong
    page from an older compile must not make every later compile in the library unpassable.
    Write the page and the rule applies to it in full."""
    component = PeopleComponent(FAMILY)
    register_component(component)
    base = [
        _person("yong-bai", "im:u_yb", "Jie WANG", title="Yong BAI"),
        _person("jie-wang", "im:u_jie", title="Jie WANG"),
    ]
    draft = PatchDraft.from_canonical(base, TEMPLATES)
    # a round that writes somewhere else entirely commits
    draft.create_document(
        "memory/topics/print.md",
        {"type": "topic", "slug": "print"},
        "# 印务\n\n- 新事实。[cite: src-01 ¶0]",
    )
    assert [v for v in run_gate(draft, []) if v.kind.startswith("people.")] == []
    # the moment the page's own fields are written, the collision has to be resolved
    draft.documents()[YONG].frontmatter["aliases"] = "Jie WANG, 白工"
    assert [v.kind for v in run_gate(draft, []) if v.kind.startswith("people.")] == [
        "people.alias_collision"
    ]


def test_the_write_face_judges_only_what_the_call_writes():
    """`validate_fields` is the gate's rule said earlier, not a second rule: a field the call
    does not carry is not this call's business, and a call carrying neither is not judged."""
    component = PeopleComponent(FAMILY)
    register_component(component)
    draft = PatchDraft.from_canonical(
        [
            _person("jia-ning", "mailto:jianing@hengyin-print.example", title="贾宁"),
            _person("lin-jia", "im:u_8812", title="Lin Jia"),
        ],
        TEMPLATES,
    )
    path = "memory/people/jia-ning.md"
    draft.mark_read(path)
    assert draft.set_fields(path, {"employer": "恒印印刷"}).frontmatter["employer"] == "恒印印刷"
    with pytest.raises(AnchorToolError) as err:
        draft.set_fields(path, {"identities": "im:u_8812"})
    assert "bound by `memory/people/lin-jia.md` as well" in str(err.value)
    with pytest.raises(AnchorToolError) as err:
        draft.set_fields(path, {"identities": "jianing"})
    assert "is not `scheme:value`" in str(err.value)
    assert draft.documents()[path].frontmatter["identities"] == (
        "mailto:jianing@hengyin-print.example"
    )


def test_find_person_matches_identity_alias_slug_or_title_exactly():
    component = PeopleComponent(FAMILY)
    docs = [
        _person("jia-ning", "mailto:jianing@hengyin-print.example", "贾宁, 老贾", title="贾宁"),
        _person("wu-lan", "", "吴岚"),
    ]
    draft = PatchDraft.from_canonical(docs, TEMPLATES)
    tool = next(t for t in component.compile_tools(draft) if t.name == "find_person")
    assert "memory/people/jia-ning.md" in tool.func(identity="MAILTO:jianing@hengyin-print.example")
    assert "memory/people/jia-ning.md" in tool.func(alias="老贾")
    assert "memory/people/jia-ning.md" in tool.func(alias="贾宁")  # title
    assert "memory/people/wu-lan.md" in tool.func(alias="wu-lan")  # slug
    assert tool.func(identity="im:u_8812").startswith("no person page binds im:u_8812")
    # and it is on the compile tool face only when registered
    assert not any(t.name == "find_person" for t in _build_tools(draft))
    register_component(component)
    assert any(t.name == "find_person" for t in _build_tools(draft, extra_tools=component.compile_tools(draft)))


async def test_enumerate_identities_reports_bound_pages_and_the_unbound_residue():
    component = PeopleComponent(
        FAMILY,
        content=_Content([MEETING, IM, EMAIL]),
        canonical=_Canonical([_person("jia-ning", "mailto:jianing@hengyin-print.example, im:u_8812", "贾宁")]),
    )
    tool = next(t for t in component.recall_tools(USER) if t.name == "enumerate_identities")
    text = await tool.coroutine(since="2025-01-01", until="2025-12-31")
    head, *rows = text.splitlines()
    assert head == "3 external identities in 2025-01-01..2025-12-31 · 1 bound to 1 person page(s) · 2 unbound"
    assert rows[0].startswith("- mailto:jianing@hengyin-print.example → memory/people/jia-ning.md · 2 source(s) · 2025-03-01..2025-06-02")
    assert "- mailto:sales@qingyun-print.example → (unbound) · 1 source(s)" in text
    assert "- meeting:p_x → (unbound)" in text


# --- wiring ----------------------------------------------------------------------------------


def test_register_components_enables_people_by_name_and_refuses_unknown_names():
    assert register_components(Settings(components=""), store=None, canonical=None) == []
    assert register_components(Settings(components=" people "), store=None, canonical=None) == ["people"]
    with pytest.raises(ValueError, match="unknown index component"):
        register_components(Settings(components="people, graph"), store=None, canonical=None)


async def test_registration_hands_a_component_a_canonical_face_it_cannot_write_through():
    """I7 at the one place a component is handed the library.

    The application owns the whole canonical store; a component gets `CanonicalReadOnly`
    over it. Narrowing at registration is what turns "a component never writes canonical
    except through the compile tools" from an expectation into a fact about the object.
    """
    from pneuma_knowledge_core.components import registered_components

    class _Store:
        async def list(self, user_id, *, at=None):
            return ["one document"]

        async def commit_patch(self, user_id, files, *, message):  # pragma: no cover
            raise AssertionError("a component must not be able to reach this")

    assert register_components(
        Settings(components="people,time"), store=None, canonical=_Store()
    ) == ["people", "time"]
    for component in registered_components():
        face = component._canonical
        assert not hasattr(face, "commit_patch")
        assert await face.list("u-1") == ["one document"]


def test_the_structured_fields_are_written_by_the_ordinary_whole_write():
    """There is no field-appending tool any more: `identities` and `aliases` belong to the
    document's overview — its picture right now — and are written whole by the same call
    that writes the prose. What the component contributes is the lookup and the two facts."""
    component = PeopleComponent(FAMILY)
    register_component(component)
    draft = PatchDraft.from_canonical(
        [_person("jia-ning", "mailto:jianing@hengyin-print.example", "贾宁"), _person("wu-lan")],
        TEMPLATES,
    )
    assert {t.name for t in component.compile_tools(draft)} == {
        "find_person",
        "decline_alias",
    }
    path = "memory/people/jia-ning.md"
    draft.mark_read(path)
    doc = draft.rewrite_overview(
        path,
        Overview(definition="贾宁是恒印印刷的对接人。 [cite: src-01 ¶0]"),
        {"identities": "mailto:jianing@hengyin-print.example, im:u_8812", "aliases": "贾宁, Lin Jia"},
    )
    assert doc.frontmatter["identities"] == "mailto:jianing@hengyin-print.example, im:u_8812"
    assert doc.frontmatter["aliases"] == "贾宁, Lin Jia"
    # the next round writes a shorter list, and that is simply the picture now
    doc = draft.set_fields(path, {"aliases": "贾宁"})
    assert doc.frontmatter["aliases"] == "贾宁"
    assert [v for v in run_gate(draft, []) if v.kind.startswith("people.")] == []


async def test_the_person_fast_path_returns_current_claims_first_then_superseded_history():
    page = CanonicalDocument(
        doc_id=DocumentId("d1"), path="memory/people/jia-ning.md",
        frontmatter={"doc_id": "d1", "type": "person", "slug": "jia-ning", "aliases": "贾宁, 老贾"},
        body=(
            "# 贾宁\n\n## 位置\n\n"
            "- 贾宁是恒印印刷的对接人。[cite: s_0412 ¶8-9] <!-- c:a1f3 -->\n"
            "- 贾宁自 2026-05 起任新华印务采购总监。[cite: s_0977 ¶1-2] <!-- c:c07e --> <!-- supersedes: c:a1f3 -->\n\n"
            "## 工作方式\n\n- 先给排期再谈价格。[cite: s_0412 ¶2] <!-- c:b2d0 -->"
        ),
    )
    component = PeopleComponent(FAMILY, canonical=_Canonical([page]))
    path = _path(component)
    assert path.name == "person" and "superseded" in path.description
    result = await path.run(USER, path.args_schema(alias="老贾"))
    assert [(str(c.anchor), c.labels) for c in result.claims] == [
        ("c07e", ("current",)), ("b2d0", ("current",)), ("a1f3", ("superseded",)),
    ]
    assert result.claims[0].citations[0].source_id == "s_0977" and result.claims[0].paths == ("people",)
    assert (await path.run(USER, path.args_schema(alias="nobody"))).claims == ()


async def test_person_profile_and_the_pinned_documents_win_over_the_store():
    head_page = _person("jia-ning", "mailto:jianing@hengyin-print.example", "贾宁")
    pinned_page = CanonicalDocument(
        doc_id=DocumentId("d1"), path="memory/people/jia-ning.md",
        frontmatter={"doc_id": "d1", "type": "person", "slug": "jia-ning", "aliases": "贾宁", "identities": "mailto:jianing@hengyin-print.example"},
        body=("# 贾宁\n\n## 位置\n\n- 恒印印刷对接人。[cite: s_0412 ¶8-9] <!-- c:a1f3 -->\n"
              "- 新华印务采购总监。[cite: s_0977 ¶1-2] <!-- c:c07e --> <!-- supersedes: c:a1f3 -->"),
    )
    component = PeopleComponent(FAMILY, content=_Content([MEETING]), canonical=_Canonical([head_page]))
    tools = {t.name: t for t in component.recall_tools(USER, documents=[pinned_page])}
    text = await tools["person_profile"].coroutine(alias="贾宁")
    assert text.splitlines()[0].startswith("# 贾宁 — `memory/people/jia-ning.md`")
    assert "## current (1)" in text and "[c:c07e · 贾宁 › 位置] 新华印务采购总监。 [cite: s_0977 ¶1-2]" in text
    assert "## superseded history (1)" in text and "[c:a1f3 · 贾宁 › 位置] 恒印印刷对接人。 [cite: s_0412 ¶8-9]" in text
    assert (await tools["person_profile"].coroutine(alias="nobody")).startswith("no person page binds nobody")
    # enumerate binds through the pinned documents too
    assert "→ memory/people/jia-ning.md" in await tools["enumerate_identities"].coroutine()
    # and the fast path reads the pinned page rather than the store's HEAD
    path = _path(component)
    result = await path.run(USER, path.args_schema(alias="贾宁"), documents=[pinned_page])
    assert [str(c.anchor) for c in result.claims] == ["c07e", "a1f3"]


async def test_person_profile_prints_the_overview_first_and_not_twice():
    """A person page's OVERVIEW is who they are, where they stand and how they got there —
    the order a reader wants. It leads the profile, and its lines are then left out of the
    claim ledger below, so the head is never mistaken for evidence of itself."""
    draft = PatchDraft.from_canonical(
        [
            CanonicalDocument(
                doc_id=DocumentId("d1"),
                path="memory/people/jia-ning.md",
                frontmatter={
                    "doc_id": "d1",
                    "type": "person",
                    "slug": "jia-ning",
                    "aliases": "贾宁",
                },
                body=(
                    "# 贾宁\n\n## 位置\n\n"
                    "- 恒印印刷对接人。[cite: s_0412 ¶8-9] <!-- c:a1f3 -->\n"
                ),
            )
        ],
        TEMPLATES,
    )
    draft.mark_read("memory/people/jia-ning.md")
    draft.rewrite_overview(
        "memory/people/jia-ning.md",
        Overview(
            definition="贾宁是恒印印刷的对接人。 c:a1f3",
            summary="她目前仍在恒印印刷。 c:a1f3",
        ),
    )
    written = draft.read("memory/people/jia-ning.md")
    page = CanonicalDocument(
        doc_id=DocumentId("d1"),
        path="memory/people/jia-ning.md",
        frontmatter=written.frontmatter,
        body=written.body,
    )
    component = PeopleComponent(FAMILY, canonical=_Canonical([page]))
    tools = {t.name: t for t in component.recall_tools(USER)}
    text = await tools["person_profile"].coroutine(alias="贾宁")
    lines = text.splitlines()
    assert lines.index("## overview") < lines.index("## current (1)")
    assert "- definition: 贾宁是恒印印刷的对接人。 c:a1f3" in lines
    assert "- summary: 她目前仍在恒印印刷。 c:a1f3" in lines
    # the overview's own blocks are not repeated as ledger claims
    assert text.count("她目前仍在恒印印刷。") == 1
    assert "[c:a1f3 · 贾宁 › 位置] 恒印印刷对接人。" in text


async def test_the_person_path_returns_the_whole_page_and_the_navigation_line_pages_it():
    """Fast: no truncation at the source. Deep: a cap that is never a dead end — the
    response says how much exists and how to fetch the rest."""
    lines = "\n".join(
        f"- 第 {i} 条事实。[cite: s_0412 ¶{i}-{i}] <!-- c:a{i:03x} -->" for i in range(60)
    )
    page = CanonicalDocument(
        doc_id=DocumentId("d1"), path="memory/people/jia-ning.md",
        frontmatter={"doc_id": "d1", "type": "person", "slug": "jia-ning", "aliases": "贾宁"},
        body=f"# 贾宁\n\n## 位置\n\n{lines}\n\n## 工作方式\n\n- 先给排期。[cite: s_0412 ¶99] <!-- c:b2d0 -->",
    )
    component = PeopleComponent(FAMILY, canonical=_Canonical([page]))

    # the fast path hands over all 61 claims; nothing is cut before the framework ranks
    path = _path(component)
    result = await path.run(USER, path.args_schema(alias="贾宁"))
    assert len(result.claims) == 61

    tools = {t.name: t for t in component.recall_tools(USER)}
    first = await tools["person_profile"].coroutine(alias="贾宁", limit=40)
    assert first.count("[c:") == 40
    assert "40 of 61 claims shown (positions 1-40)" in first
    assert 'the rest: person_profile(alias="贾宁", offset=40, limit=40)' in first
    assert "sections: 贾宁 › 位置 ×60 · 贾宁 › 工作方式 ×1" in first

    rest = await tools["person_profile"].coroutine(alias="贾宁", offset=40, limit=40)
    assert rest.count("[c:") == 21 and "21 of 61 claims shown (positions 41-61)" in rest
    assert "the rest:" not in rest  # the last page says so by not offering one

    # …and one section can be read on its own by copying the call the line itself printed
    narrow = first.splitlines()[-1]
    assert narrow == 'one section: person_profile(alias="贾宁", section="贾宁 › 位置")'
    only = await tools["person_profile"].coroutine(alias="贾宁", section="贾宁 › 位置")
    assert only.count("[c:") == 40 and "40 of 60 claims shown" in only
    # a bare heading works as well — the model may write either
    heading = await tools["person_profile"].coroutine(alias="贾宁", section="工作方式")
    assert heading.count("[c:") == 1 and "1 of 1 claims shown" in heading


async def test_enumerate_identities_pages_and_states_how_to_continue():
    component = PeopleComponent(
        FAMILY,
        content=_Content([MEETING, IM, EMAIL]),
        canonical=_Canonical([]),
    )
    tool = next(t for t in component.recall_tools(USER) if t.name == "enumerate_identities")
    first = await tool.coroutine(limit=2)
    assert first.count("\n- ") == 2
    assert "2 of 4 identities shown (positions 1-2)" in first
    assert "the rest: enumerate_identities(offset=2, limit=2)" in first
    assert "paginated" in tool.description
    rest = await tool.coroutine(offset=2, limit=2)
    assert rest.count("\n- ") == 2 and "the rest:" not in rest


def test_source_preamble_states_the_identities_the_source_boundary_knows():
    from pneuma_knowledge_core.domain.source import NormalizedSource, StructureMap

    component = PeopleComponent(FAMILY)
    im = NormalizedSource(raw=IM, blocks=[], structure=StructureMap())
    line = component.source_preamble(im)
    assert line.startswith("Identities present in this source") and "im:u_8812 — Lin Jia" in line
    assert component.source_preamble(NormalizedSource(raw=_raw("d", "document", {}, "2026-01-01"), blocks=[], structure=StructureMap())) is None


# --- address evidence: how a person is CALLED, from turn structure ------------------------
# The rule set is turn structure only — nothing below is IM-specific — and every output is a
# candidate with a support distribution, because `@X 阿宝怎么样` names a third person.

from pneuma_knowledge_core.ingest.adapters import (  # noqa: E402
    ContextStreamAdapter,
    PlainConversationInput,
)
from pneuma_knowledge_core.ingest.canonical_sources import (  # noqa: E402
    normalize_source_contract,
)
from pneuma_knowledge_core.ingest.source_contracts import (  # noqa: E402
    EmailSource,
    ImSource,
    MeetingSource,
)
from pneuma_knowledge_core.domain.source import (  # noqa: E402
    ConversationTurn,
    NormalizedSource,
    StructureMap,
)

from pneuma_knowledge_service.components.people import (  # noqa: E402
    ADDRESS_MIN_SUPPORT,
    REPORT_MIN_CONCENTRATION,
    REPORT_MIN_SOURCES,
    REPORT_MIN_SUPPORT,
    REPORT_MIN_VOCATIVE_SHARE,
    TermSupport,
    _leading_token,
    address_evidence,
    address_terms_by_target,
    is_reported,
    occurrences,
    rejects_address_term,
    render_address_candidates,
    reported_targets,
    reported_terms,
    structural_tokens,
    term_key,
)


def _at(hour: int, minute: int = 0) -> str:
    return datetime(2026, 5, 12, hour, minute, tzinfo=timezone.utc).isoformat()


def _im_source(
    messages: list[tuple[str, str, str]],
    users: list[tuple[str, str]],
    *,
    archive: str = "arc-1",
    title: str = "运营群",
    day: str = "",
):
    """One IM conversation through the REAL contract normalizer, so the block rendering
    under test is the renderer's own — never a guessed `speaker: text` pattern."""
    payload = {
        "schema": "pneuma.source.im/v1",
        "provider": "mock",
        "archive_id": archive,
        "owner_user_ids": ["u_owner"],
        "users": [{"user_id": uid, "display_name": name} for uid, name in users],
        "conversations": [
            {
                "conversation_id": f"c-{archive}",
                "conversation_type": "group_dm",
                "title": title,
                "member_ids": [uid for uid, _ in users],
                "messages": [
                    {
                        "message_id": mid,
                        "sender_id": sender,
                        "sent_at": (day + sent_at[10:]) if day else sent_at,
                        "text": text,
                    }
                    for mid, (sender, sent_at, text) in enumerate_messages(messages)
                ],
            }
        ],
    }
    [source] = normalize_source_contract(
        ImSource.model_validate(payload), USER, imported_at=datetime(2026, 5, 13, tzinfo=timezone.utc)
    )
    return source


def enumerate_messages(messages):
    return [(f"m{i}", m) for i, m in enumerate(messages)]


USERS = [
    ("u_owner", "Lin ZHOU"),
    ("u_hw", "Hao WEN"),
    ("u_lan", "Lan LIU"),
    ("u_yb", "Yong BAI"),
]

# The two patterns the real corpus shows, plus the owner's own counter-example: a term after
# an `@` that names a THIRD person.
CORPUS = [
    ("u_owner", _at(9, 0), "@Hao WEN 阿宝，我不发通知了，你直接同步给排期的人。"),
    ("u_hw", _at(9, 2), "好的，我这边今天先不动，等排期确认。"),
    ("u_owner", _at(9, 5), "阿宝，这两句文案你再顺一下。"),
    ("u_hw", _at(9, 7), "收到，晚点给你。"),
    ("u_owner", _at(10, 0), "@momo 既然flow要改，那这版先按旧的走。"),
    ("u_lan", _at(10, 3), "我改完发群里。"),
    ("u_owner", _at(10, 30), "momo，那份对照表也一起更新。"),
    ("u_lan", _at(10, 33), "已经更新了。"),
    ("u_owner", _at(11, 0), "@Yong BAI 阿宝，你们俩谁跟这条线？"),
    ("u_yb", _at(11, 2), "我来跟。"),
]


def test_address_evidence_is_a_distribution_over_targets_never_a_binding():
    source = _im_source(CORPUS, USERS)
    by_pair = {(c.term, c.target): c for c in address_evidence(source)}

    # co-mention: `@Hao WEN 阿宝，…` — weak, the term may name someone else
    assert by_pair[("阿宝", "im:u_hw")].co_mention == 1
    # answered: 阿宝，… and Hao's own turn right after it, twice
    assert by_pair[("阿宝", "im:u_hw")].answered == 2
    # an unresolved `@momo` is not skipped — the token IS the term; Lan LIU answers it
    assert (by_pair[("momo", "im:u_lan")].answered, by_pair[("momo", "im:u_lan")].co_mention) == (2, 0)
    # the owner's counter-example: `@Yong BAI 阿宝…` gives Yong one co-mention too, and
    # Yong speaking next adds one answered — the ambiguity stays visible
    assert by_pair[("阿宝", "im:u_yb")].support == 2
    # the owner is never a target, and no term binds anywhere
    assert not any(t.startswith("im:u_owner") for _, t in by_pair)


def test_a_term_is_stated_only_once_it_repeats_and_then_with_every_target():
    """The threshold decides what is worth SAYING; who a term names stays the model's call,
    so a reported term shows its sub-threshold targets too."""
    one_off = _im_source(
        [
            ("u_owner", _at(9, 0), "阿吉，这个你看下。"),
            ("u_hw", _at(9, 1), "我看看。"),
        ],
        USERS,
    )
    assert [c.term for c in address_evidence(one_off)] == ["阿吉"]
    assert address_evidence(one_off, min_support=ADDRESS_MIN_SUPPORT) == []

    reported = address_evidence(_im_source(CORPUS, USERS), min_support=ADDRESS_MIN_SUPPORT)
    assert [(c.term, c.target, c.support) for c in reported] == [
        ("阿宝", "im:u_hw", 3),
        ("momo", "im:u_lan", 2),
        ("阿宝", "im:u_yb", 2),
    ]


def test_a_term_that_is_a_present_display_name_identifies_and_is_never_an_alias():
    """Signal 1 is identification, not aliasing: a turn opening with someone's own display
    name says who it is addressed to — the page's `identities` records that, and the term is not
    reported. Only exact equality counts: a given name pulled out of a fuller display name
    is an address term like any other, and stays a candidate for the page to rule on."""
    users = [*USERS, ("u_mei", "小美")]
    source = _im_source(
        [
            ("u_owner", _at(9, 0), "小美，这个你看下。"),
            ("u_mei", _at(9, 1), "好，我看看。"),
            ("u_owner", _at(9, 5), "小美，还有这条。"),
            ("u_mei", _at(9, 6), "收到。"),
            ("u_owner", _at(10, 0), "Hao，排期你定。"),
            ("u_hw", _at(10, 1), "定了。"),
        ],
        users,
    )
    assert [(c.term, c.target) for c in address_evidence(source)] == [
        ("Hao", "im:u_hw")
    ]


async def test_the_source_preamble_separates_reported_terms_from_emerging_ones():
    """Two statements, two weights: what the LIBRARY has support for, and what this source
    alone is starting to show. Nothing in the second may be acted on yet, and the preamble
    says so rather than leaving the model to weigh two identical-looking lines."""
    component = PeopleComponent(FAMILY)
    source = _im_source(CORPUS, USERS)

    # cold projection: nothing is reported, and only this source's repetitions are stated
    identities, emerging, *_ = component.source_preamble(source).splitlines()
    assert identities.startswith("Identities present in this source")
    assert emerging.startswith("emerging (repeated in this source")
    assert '"阿宝" → im:u_hw (answered 2, co_mention 1 here; 1 source so far)' in emerging
    assert '"momo" → im:u_lan (answered 2 here; 1 source so far)' in emerging

    # the same turns in a SECOND source carry 阿宝 over the bar (3 supports on one target,
    # 60% of the term's total, two sources); momo still has one source and stays emerging
    await component.on_source_indexed(str(USER), source)
    await component.on_source_indexed(str(USER), _im_source(CORPUS[:4], USERS, archive="arc-2"))
    identities, reported, emerging, *_ = component.source_preamble(source).splitlines()
    assert reported.startswith("How the library's turns call these people")
    assert reported.endswith(
        '"阿宝" → im:u_hw — Hao WEN (answered 4, co_mention 2, 2 sources) · '
        'im:u_yb — Yong BAI (answered 1, co_mention 1, 1 source)'
    )
    assert emerging.startswith("emerging (repeated in this source")
    assert '"momo" → im:u_lan (answered 2 here; 1 source so far)' in emerging
    assert "阿宝" not in emerging  # a reported term is never also an emerging one


def test_the_preamble_caps_both_lists_and_says_how_many_it_cut():
    names = ["阿甲", "阿乙", "阿丙", "阿丁", "阿戊", "阿己", "阿庚"]
    users = [("u_owner", "Lin ZHOU")] + [(f"u_{i}", f"员工{i}") for i in range(len(names))]
    messages = []
    hour = 8
    for i, term in enumerate(names):
        for _ in range(2):
            hour += 1
            messages.append(("u_owner", _at(hour, 0), f"{term}，这条你跟一下。"))
            messages.append((f"u_{i}", _at(hour, 5), "在跟了。"))
    source = _im_source(messages, users)

    line = PeopleComponent(FAMILY).source_preamble(source).splitlines()[1]
    assert line.count(" → ") == 3 and line.endswith("; …and 4 more")


async def test_the_preamble_caps_the_reported_list_too():
    names = ["阿甲", "阿乙", "阿丙", "阿丁", "阿戊", "阿己", "阿庚"]
    users = [("u_owner", "Lin ZHOU")] + [(f"u_{i}", f"员工{i}") for i in range(len(names))]
    messages = []
    hour = 8
    for i, term in enumerate(names):
        for _ in range(2):
            hour += 1
            messages.append(("u_owner", _at(hour, 0), f"{term}，这条你跟一下。"))
            messages.append((f"u_{i}", _at(hour, 5), "在跟了。"))
    component = PeopleComponent(FAMILY)
    for archive in ("arc-1", "arc-2"):
        await component.on_source_indexed(str(USER), _im_source(messages, users, archive=archive))
    line = component.source_preamble(_im_source(messages, users)).splitlines()[1]
    assert line.startswith("How the library's turns call these people")
    assert line.count(" → ") == 6 and line.endswith("; …and 1 more")


# --- the hotfix: what the term grammar refuses before any counting happens ------------------


def test_the_term_grammar_rejects_identifiers_urls_repetition_and_function_words():
    """Belt-and-braces, and only that: these tokens reached a turn's head often enough to
    occupy a candidate slot, so the grammar stops them before the arithmetic runs."""
    # an ASCII colon closes a term only before whitespace or end of text
    assert _leading_token("https://example.com/x") is None
    assert _leading_token("msgId:8812 这条") is None
    assert _leading_token("a017:1 号机") is None
    assert _leading_token("周总：这个方案") == "周总"
    assert _leading_token("Kun: 对账单") == "Kun"
    # digits, dots, slashes and underscores are identifiers, not names
    assert _leading_token("MIRO-DISC-001，跟一下") is None
    assert _leading_token("v2.1，发出去") is None
    # repetition and interjection, by shape rather than by word list
    assert rejects_address_term("哈哈哈") == "repetition"
    assert rejects_address_term("hhhh") == "repetition"
    assert rejects_address_term("呵呵呵呵") == "repetition"
    # a function-word head or a sentence-final particle tail
    assert rejects_address_term("我觉得") == "function word head"
    assert rejects_address_term("看下") == "function word head"
    assert rejects_address_term("那就先把") == "function word head"
    assert rejects_address_term("没关系的") == "function word head"
    assert rejects_address_term("知道了") == "sentence-final particle"
    assert rejects_address_term("行吗") == "sentence-final particle"
    # a Latin term is one token, so "starts with a pronoun" and "is a pronoun" coincide
    assert rejects_address_term("you") == "stopword"
    assert rejects_address_term("this") == "stopword"
    # …and what a real nickname looks like passes all of it
    assert rejects_address_term("阿宝") == "" and rejects_address_term("momo") == ""
    assert rejects_address_term("周总") == "" and rejects_address_term("Kun") == ""


def test_a_latin_term_is_one_term_however_it_is_spelled():
    users = [*USERS, ("u_momo", "Lan LIU")]
    source = _im_source(
        [
            ("u_owner", _at(9, 0), "Momo，这版先按旧的走。"),
            ("u_lan", _at(9, 1), "我改完发群里。"),
            ("u_owner", _at(9, 5), "momo，那份对照表也更新一下。"),
            ("u_lan", _at(9, 6), "已经更新了。"),
        ],
        users,
    )
    [candidate] = address_evidence(source)
    assert (candidate.target, candidate.answered) == ("im:u_lan", 2)
    assert term_key(candidate.term) == "momo"


# --- the mechanism: library-wide concentration ---------------------------------------------


def _support(term, target, *, answered=0, co_mention=0, sources=1):
    return TermSupport(
        term=term, target=target, answered=answered, co_mention=co_mention, sources=sources
    )


def test_a_term_is_reported_only_where_its_support_concentrates():
    """The whole point: `是的` and `阿宝` are indistinguishable inside one conversation and
    trivially different across a library. Support spread over many targets is reported for
    nobody; support that lands on one target is reported, with the runner-ups still shown."""
    spread = [
        _support("是的", f"im:u_{i}", answered=2, sources=2) for i in range(6)
    ]
    assert reported_terms(spread) == {}

    concentrated = [
        _support("阿宝", "im:u_hw", answered=9, co_mention=4, sources=7),
        _support("阿宝", "im:u_yb", answered=2, co_mention=1, sources=2),
    ]
    [group] = reported_terms(concentrated).values()
    assert [(r.target, r.support) for r in group] == [("im:u_hw", 13), ("im:u_yb", 3)]
    # the runner-up is rendered but is NOT itself reported — 3 of 16 is not concentration
    assert is_reported(group[0], 16) and not is_reported(group[1], 16)

    # enough support, but all of it from one conversation: an anecdote, not a nickname
    assert reported_terms([_support("阿吉", "im:u_1", answered=5, sources=1)]) == {}
    # and enough sources but not enough support
    assert reported_terms([_support("阿吉", "im:u_1", answered=2, sources=2)]) == {}


async def test_the_projection_accumulates_across_sources_and_a_rebuild_starts_from_nothing():
    component = PeopleComponent(FAMILY, content=_Content([]))
    source = _im_source(CORPUS, USERS)
    await component.on_source_indexed(str(USER), source)
    first = {(r.term, r.target): (r.support, r.sources) for r in await component.library_terms(USER)}
    assert first[("阿宝", "im:u_hw")] == (3, 1)

    await component.on_source_indexed(str(USER), _im_source(CORPUS, USERS, archive="arc-2"))
    second = {(r.term, r.target): (r.support, r.sources) for r in await component.library_terms(USER)}
    assert second[("阿宝", "im:u_hw")] == (6, 2)
    assert second[("momo", "im:u_lan")] == (4, 2)

    # rebuild re-derives from L0 — the accumulating write path is safe because this exists
    component = PeopleComponent(FAMILY, content=_Content([source]))
    await component.on_source_indexed(str(USER), source)
    await component.on_source_indexed(str(USER), source)  # a re-index double-counts…
    doubled = {(r.term, r.target): r.support for r in await component.library_terms(USER)}
    assert doubled[("阿宝", "im:u_hw")] == 6
    await component.rebuild(str(USER))  # …until the rebuild
    rebuilt = {(r.term, r.target): r.support for r in await component.library_terms(USER)}
    assert rebuilt[("阿宝", "im:u_hw")] == 3


async def test_reported_since_is_the_day_the_pair_crossed_the_bar_and_a_rebuild_reproduces_it():
    """The clock the one-time ask runs on, and the reason it can be trusted: it is a function
    of L0. A pair needs two sources to be reported, so it crosses the bar on the SECOND day —
    and a rebuild replaying the library in `(occurred_on, source_id)` order arrives at that
    day from nothing, whatever order the index jobs happened to run in."""
    days = ["2026-01-09", "2026-03-04", "2026-05-20"]
    sources = [
        _im_source(CORPUS, USERS, archive=f"arc-{n}", day=day)
        for n, day in enumerate(days)
    ]

    # indexed in the material's own order: the pair is unreported after one source and
    # crosses the bar on the second, which is the day it is stamped with
    live = PeopleComponent(FAMILY, content=_Content(sources))
    await live.on_source_indexed(str(USER), sources[0])
    assert {r.reported_since for r in await live.library_terms(USER)} == {""}
    for source in sources[1:]:
        await live.on_source_indexed(str(USER), source)
    stamps = {(r.term, r.target): r.reported_since for r in await live.library_terms(USER)}
    assert stamps[("阿宝", "im:u_hw")] == days[1]

    # indexed BACKWARDS — a re-import, a backfill, a queue that drained out of order — and
    # the rebuild re-derives the answer the material supports rather than the one arrival
    # order produced
    shuffled = PeopleComponent(FAMILY, content=_Content(sources))
    for source in reversed(sources):
        await shuffled.on_source_indexed(str(USER), source)
    await shuffled.rebuild(str(USER))
    rebuilt = {(r.term, r.target): r.reported_since for r in await shuffled.library_terms(USER)}
    assert rebuilt == stamps

    # …and a second rebuild reproduces the first byte for byte
    await shuffled.rebuild(str(USER))
    again = {(r.term, r.target): r.reported_since for r in await shuffled.library_terms(USER)}
    assert again == rebuilt


async def test_a_stamp_is_written_once_and_never_moved():
    """Monotone: a pair whose concentration later shifts back under the bar keeps the day the
    library started asking about it, because it DID ask then and a page written since has
    answered. `… WHERE reported_since IS NULL` is the whole mechanism."""
    days = ["2026-01-09", "2026-03-04", "2026-05-20"]
    sources = [
        _im_source(CORPUS, USERS, archive=f"arc-{n}", day=day)
        for n, day in enumerate(days)
    ]
    component = PeopleComponent(FAMILY, content=_Content(sources))
    for source in sources:
        await component.on_source_indexed(str(USER), source)
    stamped = {(r.term, r.target): r.reported_since for r in await component.library_terms(USER)}
    assert stamped[("阿宝", "im:u_hw")] == days[1]

    # a fourth source on a much later day adds support to the same pair — the stamp stands
    await component.on_source_indexed(
        str(USER), _im_source(CORPUS, USERS, archive="arc-9", day="2027-01-01")
    )
    later = {(r.term, r.target): r.reported_since for r in await component.library_terms(USER)}
    assert later[("阿宝", "im:u_hw")] == days[1]


async def test_the_in_memory_fallback_and_a_store_backed_projection_agree_row_for_row():
    """One definition of "add a source's counts", so the keyless path and the table cannot
    drift: same fixture, same rows, same reported terms."""

    class _TermStore(_Content):
        """A ContentStore that also holds the projection, with the adapter's arithmetic."""

        def __init__(self, sources):
            super().__init__(sources)
            self.rows: dict[tuple[str, str], dict] = {}
            self.indexed: set[str] = set()

        async def add_people_terms(self, user_id, source_id, rows):
            # the adapter's manifest, in memory: claimed first, and a repeat adds nothing
            if str(source_id) in self.indexed:
                return False
            self.indexed.add(str(source_id))
            for row in rows:
                key = (row["term"], row["target_identity"])
                current = self.rows.get(key)
                if current is None:
                    self.rows[key] = dict(row)
                    continue
                current["answered"] += row["answered"]
                current["co_mention"] += row["co_mention"]
                current["non_vocative"] += row["non_vocative"]
                current["sources"] += row["sources"]
                current["first_day"] = min(current["first_day"], row["first_day"])
                current["last_day"] = max(current["last_day"], row["last_day"])
            return True

        async def set_people_terms_reported_since(self, user_id, pairs, day):
            # `… WHERE reported_since IS NULL` — the adapter's predicate, so a stamp is
            # written once and never moved.
            for pair in pairs:
                row = self.rows.get((pair["term"], pair["target_identity"]))
                if row is not None and not row.get("reported_since"):
                    row["reported_since"] = day
            return len(pairs)

        async def delete_people_terms(self, user_id):
            count = len(self.rows)
            self.rows.clear()
            self.indexed.clear()  # both tables or neither — the adapter's transaction
            return count

        async def people_terms(self, user_id, terms=None):
            return [
                dict(r)
                for key, r in sorted(self.rows.items())
                if terms is None or key[0] in set(terms)
            ]

    fixture = [_im_source(CORPUS, USERS), _im_source(CORPUS[:6], USERS, archive="arc-2")]
    keyless = PeopleComponent(FAMILY, content=_Content(fixture))
    stored = PeopleComponent(FAMILY, content=_TermStore(fixture))
    for source in fixture:
        await keyless.on_source_indexed(str(USER), source)
        await stored.on_source_indexed(str(USER), source)

    def rows_of(terms):
        return sorted(tuple(sorted(t.row().items())) for t in terms)

    keyless_rows = await keyless.library_terms(USER)
    stored_rows = await stored.library_terms(USER)
    assert rows_of(keyless_rows) == rows_of(stored_rows) != []
    assert reported_terms(keyless_rows).keys() == reported_terms(stored_rows).keys() == {
        "阿宝",
        "momo",
    }


def test_the_same_three_signals_read_a_meeting_a_mail_thread_and_a_plain_conversation():
    meeting = MeetingSource.model_validate(
        {
            "schema": "pneuma.source.meeting/v1",
            "provider": "mock",
            "meeting_id": "mtg-1",
            "title": "排期同步",
            "started_at": _at(9, 0),
            "owner_participant_ids": ["p_owner"],
            "participants": [
                {"participant_id": "p_owner", "display_name": "Lin ZHOU"},
                {"participant_id": "p_bo", "display_name": "Bo MA"},
            ],
            "segments": [
                {"segment_id": "s1", "speaker_id": "p_owner", "started_at": _at(9, 0), "text": "Bo，你那边的排期定了吗？"},
                {"segment_id": "s2", "speaker_id": "p_bo", "started_at": _at(9, 1), "text": "定了，下周一开印。"},
                {"segment_id": "s3", "speaker_id": "p_owner", "started_at": _at(9, 2), "text": "好的，那就这样。"},
            ],
        }
    )
    [normalized] = normalize_source_contract(
        meeting, USER, imported_at=datetime(2026, 5, 13, tzinfo=timezone.utc)
    )
    # a greeting opener contributes nothing; the address term does
    assert [(c.term, c.target, c.answered) for c in address_evidence(normalized)] == [
        ("Bo", "meeting:p_bo", 1)
    ]

    email = EmailSource.model_validate(
        {
            "schema": "pneuma.source.email/v1",
            "provider": "mock",
            "archive_id": "arc-e",
            "owner_addresses": ["zhou@self.example"],
            "threads": [
                {
                    "thread_id": "t-1",
                    "subject": "对账单",
                    "messages": [
                        {
                            "message_id": "e1",
                            "sent_at": _at(9, 0),
                            "from": {"address": "zhou@self.example", "display_name": "Lin ZHOU"},
                            "to": [{"address": "kun.yao@example.com", "display_name": "Kun YAO"}],
                            "cc": [],
                            "subject": "对账单",
                            "text": "Hi Kun,\n\n这个月的对账单我明天发你。",
                        }
                    ],
                }
            ],
        }
    )
    [thread] = normalize_source_contract(
        email, USER, imported_at=datetime(2026, 5, 13, tzinfo=timezone.utc)
    )
    # the header addressee is who the message is addressed to (signal 1); the greeting is
    # stepped over once, and the name behind it is the term
    assert [(c.term, c.target, c.co_mention) for c in address_evidence(thread)] == [
        ("Kun", "mailto:kun.yao@example.com", 1)
    ]

    plain = ContextStreamAdapter().normalize(
        PlainConversationInput(
            raw=_raw("cs-1", "conversation", {}, "2026-05-12"),
            turns=[
                ConversationTurn(speaker="me", text="小林，这条线你来跟。", role="owner", at=datetime(2026, 5, 12, 9, tzinfo=timezone.utc)),
                ConversationTurn(speaker="spk_2", text="好，我今天就去。", role="other", speaker_id="spk_2", at=datetime(2026, 5, 12, 9, 1, tzinfo=timezone.utc)),
            ],
        )
    )
    # no identity exists at this boundary, so the target is the speaker label the blocks
    # themselves render — the candidate still says WHO answers to the term
    assert [(c.term, c.target) for c in address_evidence(plain)] == [
        ("小林", "Participant1 (spk_2)")
    ]

    document = NormalizedSource(
        raw=_raw("d-1", "document", {}, "2026-05-12"), blocks=[], structure=StructureMap()
    )
    assert address_evidence(document) == []
    assert PeopleComponent(FAMILY).source_preamble(document) is None


def test_find_person_points_at_the_address_evidence_of_this_compiles_sources():
    component = PeopleComponent(FAMILY)
    draft = PatchDraft.from_canonical([_person("wen-hao", "im:u_hw", "Hao WEN")], TEMPLATES)
    tools = {t.name: t for t in component.compile_tools(draft, sources=[_im_source(CORPUS, USERS)])}
    miss = tools["find_person"].func(alias="阿宝")
    assert miss.startswith("no person page binds 阿宝.")
    assert (
        "This compile's turns address that name: "
        '"阿宝" → im:u_hw (answered 2, co_mention 1) · im:u_yb (answered 1, co_mention 1) — '
        "candidates from turn structure, not a binding" in miss
    )
    # a name the turns never call anyone: the miss text is the plain one
    assert "This compile's turns" not in tools["find_person"].func(alias="老王")
    # …and the lookup tool says what the two kinds of listed term ARE, without telling the
    # model when to record one: that judgement is the contract's, not the framework's.
    lookup = tools["find_person"].description
    assert "Neither is a binding" in lookup and "the contract rules on them" in lookup
    assert "written whole" in lookup


async def test_enumerate_identities_lists_the_terms_each_identity_is_called_by():
    """The enumeration states what an identity is CALLED only where the library concentrates
    on it — one conversation is never enough, however often it repeats inside that one."""
    sources = [_im_source(CORPUS, USERS), _im_source(CORPUS, USERS, archive="arc-2")]
    assert address_terms_by_target(sources[:1]) == {}  # one source: an anecdote
    assert address_terms_by_target(sources) == {
        "im:u_hw": ["阿宝 ×6"],
        "im:u_lan": ["momo ×4"],
    }
    component = PeopleComponent(
        FAMILY, content=_Content(sources), canonical=_Canonical([])
    )
    tool = next(t for t in component.recall_tools(USER) if t.name == "enumerate_identities")
    text = await tool.coroutine()
    assert "- im:u_hw → (unbound) · 2 source(s) · 2026-05-12..2026-05-12 · Hao WEN · terms: 阿宝 ×6" in text
    assert "Lan LIU · terms: momo ×4" in text
    # 阿宝 also points at Yong BAI — one co-mention out of the term's ten, so it is
    # rendered in the distribution and stated under nobody
    assert "Yong BAI" in text and "terms:" not in text.split("Yong BAI")[1]


def test_render_address_candidates_groups_a_term_and_keeps_the_order_deterministic():
    line = render_address_candidates(address_evidence(_im_source(CORPUS, USERS)))
    assert line.startswith('"阿宝" → im:u_hw (answered 2, co_mention 1) · im:u_yb (')


# --- the async face of the sync seams: `prepare` ------------------------------------------
# The shipped deployment shape runs index jobs in one process and compile jobs in another, so
# a compile process's mirror of the projection is cold by construction. `prepare` is the hook
# the framework awaits before rendering any sync seam; without it the library-wide address
# line never reaches the compile model, however much support the table holds.


class _ProjectionOnlyStore:
    """A ContentStore that only holds the address-term projection — the shape a compile
    process sees: rows written by some other process's index jobs."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.reads = 0

    async def people_terms(self, user_id, terms=None):
        self.reads += 1
        return [dict(r) for r in self.rows]

    async def add_people_terms(self, user_id, source_id, rows):  # `_persists()` tests for this
        return True

    async def set_people_terms_reported_since(self, user_id, pairs, day):
        return 0

    async def delete_people_terms(self, user_id):
        return 0


REPORTED_ROWS = [
    {
        "term": "阿宝",
        "target_identity": "im:u_hw",
        "target_name": "Hao WEN",
        "answered": 9,
        "co_mention": 4,
        "sources": 7,
        "first_day": "2026-05-01",
        "last_day": "2026-07-30",
    }
]


async def test_a_fresh_component_renders_the_address_line_only_after_prepare():
    component = PeopleComponent(FAMILY, content=_ProjectionOnlyStore(REPORTED_ROWS))
    source = _im_source(CORPUS, USERS)

    # A fresh process has indexed nothing: the mirror is cold and the seam says only what
    # this source shows. That is the documented cold state — never a wrong count.
    cold = component.source_preamble(source).splitlines()
    assert not any(line.startswith("How the library's turns call") for line in cold)

    await component.prepare(str(USER))

    identities, reported, emerging, *_ = component.source_preamble(source).splitlines()
    assert identities.startswith("Identities present in this source")
    assert reported.startswith("How the library's turns call these people")
    assert reported.endswith(
        '"阿宝" → im:u_hw — Hao WEN (answered 9, co_mention 4, 7 sources)'
    )
    # A reported term is never also an emerging one, so 阿宝 leaves the emerging line.
    assert emerging.startswith("emerging (repeated in this source")
    assert "阿宝" not in emerging


async def test_prepare_re_reads_the_projection_for_every_job_and_reaches_find_person():
    """Not once per process — once per JOB. The counts are the half of this component's
    mirror that CHANGES: every index job adds to the table, in another process, so a worker
    that read it once would state its first job's library for the rest of its life. The
    source boundary beside it stays incremental (a source's speakers never change); this is
    one ordered SELECT per compile."""
    store = _ProjectionOnlyStore(list(REPORTED_ROWS))
    component = PeopleComponent(FAMILY, content=store)

    await component.prepare(str(USER))
    assert store.reads == 1
    # the index process writes a term this worker has never seen…
    store.rows.append(dict(REPORTED_ROWS[0], term="momo"))
    await component.prepare(str(USER))
    assert store.reads == 2
    # …and the sync seams see it on this job rather than on the next process
    assert {row.term for row in component._mirrored_terms(str(USER))} == {"阿宝", "momo"}

    draft = PatchDraft.from_canonical([], TEMPLATES)
    find_person = next(
        t
        for t in component.compile_tools(draft, sources=[_im_source(CORPUS, USERS)])
        if t.name == "find_person"
    )
    answer = find_person.func(alias="阿宝")
    assert "Across the library the turns address that name" in answer
    assert "im:u_hw — Hao WEN (answered 9, co_mention 4, 7 sources)" in answer


# --- the read faces resolve a reported term, and never confuse it with a confirmation -------


def _hw_page(aliases: str = ""):
    """Hao WEN's page, bound to the identity the corpus's `阿宝` concentrates on."""
    return CanonicalDocument(
        doc_id=DocumentId("d-hw"),
        path="memory/people/hao-wen.md",
        frontmatter={
            "doc_id": "d-hw",
            "type": "person",
            "slug": "hao-wen",
            "identities": "im:u_hw",
            **({"aliases": aliases} if aliases else {}),
        },
        body=(
            "# Hao WEN\n\n## 工作方式\n\n"
            "- 排期确认前不动手。[cite: arc-1 ¶1-1] <!-- c:0a01 -->\n"
            "- 文案顺完当天回。[cite: arc-1 ¶3-3] <!-- c:0a02 -->"
        ),
    )


async def _indexed(component, *archives: str) -> None:
    for archive in archives:
        await component.on_source_indexed(str(USER), _im_source(CORPUS, USERS, archive=archive))


async def test_find_person_resolves_a_reported_address_term_and_calls_the_match_derived():
    """The library addresses Hao as 阿宝; the page has never been told. One source is
    an anecdote and resolves nothing — two carry the term over the concentration bar, and
    then the lookup answers with the page AND with the arithmetic behind it."""
    component = PeopleComponent(FAMILY, content=_Content([]))
    draft = PatchDraft.from_canonical([_hw_page()], TEMPLATES)
    sources = [_im_source(CORPUS, USERS)]

    def ask(alias: str) -> str:
        tool = next(
            t for t in component.compile_tools(draft, sources=sources) if t.name == "find_person"
        )
        return tool.func(alias=alias)

    # one source: 阿宝 has support but only one source behind it — nothing is resolved
    await _indexed(component, "arc-1")
    cold = ask("阿宝")
    assert cold.startswith("no person page binds 阿宝")
    assert "memory/people/hao-wen.md" not in cold

    # a second source carries it over the bar
    await _indexed(component, "arc-2")
    warm = ask("阿宝")
    assert "- `memory/people/hao-wen.md` — Hao WEN" in warm
    assert '(matched via library address term "阿宝": answered 4, co_mention 2, 2 sources)' in warm
    assert "the page's `aliases` field is where it becomes a confirmation" in warm

    # a term the library does not back stays unresolved, however often it is written
    assert ask("是的").startswith("no person page binds 是的")


async def test_a_canonical_alias_wins_the_lookup_and_is_never_labelled_derived():
    component = PeopleComponent(FAMILY, content=_Content([]))
    await _indexed(component, "arc-1", "arc-2")
    draft = PatchDraft.from_canonical([_hw_page(aliases="阿宝")], TEMPLATES)
    tool = next(t for t in component.compile_tools(draft) if t.name == "find_person")
    out = tool.func(alias="阿宝")
    assert "- `memory/people/hao-wen.md` — Hao WEN" in out
    assert "aliases: 阿宝" in out  # the confirmation, as the outline states it
    assert "matched via library address term" not in out


async def test_the_person_fast_path_resolves_a_reported_term_and_labels_those_claims():
    component = PeopleComponent(
        FAMILY, content=_Content([]), canonical=_Canonical([_hw_page()])
    )
    path = _path(component)

    await _indexed(component, "arc-1")
    assert (await path.run(USER, path.args_schema(alias="阿宝"))).claims == ()

    await _indexed(component, "arc-2")
    derived = await path.run(USER, path.args_schema(alias="阿宝"))
    assert [(str(c.anchor), c.labels) for c in derived.claims] == [
        ("0a01", ("current", "via:address-term")),
        ("0a02", ("current", "via:address-term")),
    ]

    # the same page reached by a CONFIRMED alias carries no derived label
    confirmed = PeopleComponent(
        FAMILY, content=_Content([]), canonical=_Canonical([_hw_page(aliases="阿宝")])
    )
    await _indexed(confirmed, "arc-1", "arc-2")
    confirmed_path = _path(confirmed)
    result = await confirmed_path.run(USER, confirmed_path.args_schema(alias="阿宝"))
    assert [c.labels for c in result.claims] == [("current",), ("current",)]


async def test_person_profile_prints_confirmed_aliases_and_library_terms_on_separate_lines():
    """Two vocabularies, two lines. A reader who cannot tell a confirmation from a count
    cannot judge either, so the header never merges them."""
    component = PeopleComponent(
        FAMILY, content=_Content([]), canonical=_Canonical([_hw_page(aliases="小文")])
    )
    await _indexed(component, "arc-1", "arc-2")
    tools = {t.name: t for t in component.recall_tools(USER)}

    text = await tools["person_profile"].coroutine(alias="小文")
    head, derived, *_ = text.splitlines()
    assert head == (
        "# Hao WEN — `memory/people/hao-wen.md` · "
        "identities: im:u_hw · aliases (confirmed): 小文"
    )
    assert derived == "library address terms: 阿宝 (answered 4, co_mention 2, 2 sources)"
    assert "matched via library address term" not in text  # the alias was canonical

    # …and the same page found BY the derived term says so under the two lines
    viaterm = await tools["person_profile"].coroutine(alias="阿宝")
    assert viaterm.splitlines()[:2] == [head, derived]
    assert viaterm.splitlines()[2] == (
        '(matched via library address term "阿宝": answered 4, co_mention 2, 2 sources)'
    )


# --- the alias decision: a reported term must END the round decided ------------------------
# The failure this closes is not a wrong answer, it is no answer: the preamble stated the
# term under every source for months, the contract asked for aliases, and the page held none
# while other documents' claims used the term. So the round is made to end with the question
# answered — recorded or declined — and the answer stays the contract's.

from pneuma_knowledge_service.components.people import (  # noqa: E402
    ALIAS_UNDECIDED_MAX,
    UNRESOLVED_MAX,
    name_shaped_tokens,
    unresolved_names,
)

DECIDE_USERS = [
    ("u_owner", "Ke ZHOU"),
    ("u_mei", "Mei LIN"),
    ("u_ravi", "Ravi SETH"),
]

DECIDE_CORPUS = [
    ("u_owner", _at(9, 0), "@Mei LIN 阿宝，这版排期你来定。"),
    ("u_mei", _at(9, 2), "好，今天定完发群里。"),
    ("u_owner", _at(9, 5), "阿宝，物料清单也一起。"),
    ("u_mei", _at(9, 7), "收到。"),
]

MEI_TERM = {
    "term": "阿宝",
    "target_identity": "im:u_mei",
    "target_name": "Mei LIN",
    "answered": 9,
    "co_mention": 4,
    "sources": 7,
    "first_day": "2026-05-01",
    "last_day": "2026-07-30",
}

MEI_PATH = "memory/people/mei-lin.md"

#: The day the library started asking about 「阿宝」 — `component_people_terms.reported_since`,
#: stamped by the index job that pushed the pair over the reporting bar.
REPORTED_SINCE = "2026-06-15"
MEI_TERM_DATED = dict(MEI_TERM, reported_since=REPORTED_SINCE)


class _WrittenCanonical:
    """`CanonicalReadOnly` as this component uses it: the day each page was last written by a
    committed patch. The git adapter answers it out of the commit history (`written_on`); a
    test states the days directly."""

    def __init__(self, days=None):
        self.days = dict(days or {})
        self.prefixes: list[str] = []

    async def list(self, user_id, *, at=None):
        return []

    async def written_on(self, user_id, *, prefix=""):
        self.prefixes.append(prefix)
        return dict(self.days)


def _mei_page(aliases: str = ""):
    fm = {"doc_id": "d-mei", "type": "person", "slug": "mei-lin", "identities": "im:u_mei"}
    if aliases:
        fm["aliases"] = aliases
    return CanonicalDocument(
        doc_id=DocumentId("d-mei"),
        path=MEI_PATH,
        frontmatter=fm,
        body="# Mei LIN\n\n- 排期当天定。[cite: arc-1 ¶1-1] <!-- c:0b01 -->",
    )


class _LibraryStore(_Content):
    """L0 plus the component's ONE table — the address-term counts. Everything this
    component stores is derived and a rebuild starts it from nothing; the judgements are not
    here at all, they are frontmatter on the person pages."""

    def __init__(self, sources=(), rows=()):
        super().__init__(sources)
        self.rows = {(r["term"], r["target_identity"]): dict(r) for r in rows}
        self.indexed: set[str] = set()

    async def people_terms(self, user_id, terms=None):
        return [
            dict(row)
            for key, row in sorted(self.rows.items())
            if terms is None or key[0] in set(terms)
        ]

    async def add_people_terms(self, user_id, source_id, rows):
        if str(source_id) in self.indexed:
            return False
        self.indexed.add(str(source_id))
        for row in rows:
            key = (row["term"], row["target_identity"])
            current = self.rows.get(key)
            if current is None:
                self.rows[key] = dict(row)
                continue
            for field_name in ("answered", "co_mention", "non_vocative", "sources"):
                current[field_name] += row[field_name]
        return True

    async def set_people_terms_reported_since(self, user_id, pairs, day):
        for pair in pairs:
            row = self.rows.get((pair["term"], pair["target_identity"]))
            if row is not None and not row.get("reported_since"):
                row["reported_since"] = day
        return len(pairs)

    async def delete_people_terms(self, user_id):
        count = len(self.rows)
        self.rows.clear()
        self.indexed.clear()
        return count


async def _round(component, docs, *, sources=None):
    """One compile round's shape, in the order the runner runs it: prepare, build the tools
    (which is where the component learns who this round's sources carry), then the gate."""
    reset_components()
    register_component(component)
    await component.prepare(str(USER))
    draft = PatchDraft.from_canonical(docs, TEMPLATES)
    component.compile_tools(
        draft, sources=[_im_source(DECIDE_CORPUS, DECIDE_USERS)] if sources is None else sources
    )
    return draft


async def test_the_gate_demands_a_decision_on_each_reported_term_for_a_present_person():
    """The term is reported, the page binds the identity, the identity is in this compile's
    sources — and the page records nothing. That is the whole trigger."""
    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=[MEI_TERM]))
    draft = await _round(component, [_mei_page()])

    [violation] = component.gate_checks(draft.documents(), draft.base_documents())
    assert violation.kind == "people.alias_undecided"
    assert violation.path == MEI_PATH
    # the term, the support behind it, and the two ways out — each named
    assert '"阿宝"' in violation.detail
    assert "im:u_mei — Mei LIN (answered 9, co_mention 4, 7 sources)" in violation.detail
    assert "`aliases` written whole" in violation.detail
    assert f'decline_alias(path="{MEI_PATH}", term="阿宝"' in violation.detail


async def test_recording_the_alias_answers_the_gate():
    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=[MEI_TERM]))
    draft = await _round(component, [_mei_page(aliases="阿宝")])
    assert component.gate_checks(draft.documents(), draft.base_documents()) == []

    # case-insensitively, and the same holds for a page CREATED this round
    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=[dict(MEI_TERM, term="momo")]))
    draft = await _round(component, [])
    draft.create_document(
        MEI_PATH,
        {"type": "person", "slug": "mei-lin", "identities": "im:u_mei"},
        "# Mei LIN\n\n- 排期当天定。[cite: arc-1 ¶1-1]",
    )
    assert [v.kind for v in component.gate_checks(draft.documents(), draft.base_documents())] == [
        "people.alias_undecided"
    ]
    draft.set_fields(MEI_PATH, {"aliases": "MoMo"})
    assert component.gate_checks(draft.documents(), draft.base_documents()) == []


def _decline_tool(component, draft, sources=None):
    if sources is None:
        sources = [_im_source(DECIDE_CORPUS, DECIDE_USERS)]
    return next(
        t
        for t in component.compile_tools(draft, sources=sources)
        if t.name == "decline_alias"
    )


# --- asked ONCE: the projection's `reported_since` against the page's last commit ----------
# DELETED with the field they covered: `test_recording_the_alias_reverses_a_decline_on_the_same_page`
# and the `declined_keys` "alias wins over a decline" read rule, `test_a_rewrite_that_drops_
# the_decline_reopens_the_question`, `test_a_decline_touches_the_page_so_the_round_answers_
# for_its_whole_frontmatter`, `test_a_decline_cannot_be_forged_through_the_generic_field_
# writes` and `test_the_forged_decline_no_longer_answers_a_question_a_later_job_asks`, and
# `test_a_decline_and_the_rewrite_that_carries_it_share_one_round`. Every one of them was
# about `declined_terms` — a person page's list of the names that are NOT its subject's —
# and that field is gone: canonical records what is KNOWN about somebody, and a column of
# refusals is a distraction on the page a reader came to for the person. A forgery test needs
# a field to forge; an alias-wins-over-a-decline test needs a decline to win over. What
# replaces all of them is below: nothing is stored, and the question is asked once.


async def test_a_term_reported_after_the_page_was_last_written_is_asked():
    """The trigger, in full: the term is reported, the page binds the identity, the identity
    is in this compile's sources, the page does not record the term — and the page was last
    written BEFORE the day the library started asking."""
    component = PeopleComponent(
        FAMILY,
        content=_LibraryStore(rows=[MEI_TERM_DATED]),
        canonical=_WrittenCanonical({MEI_PATH: "2026-06-14"}),
    )
    draft = await _round(component, [_mei_page()])

    [violation] = component.gate_checks(draft.documents(), draft.base_documents())
    assert violation.kind == "people.alias_undecided" and '"阿宝"' in violation.detail
    assert "stored nowhere" in violation.detail


async def test_a_page_written_since_the_term_became_reported_has_answered():
    """The whole of "asked once". The page carries no alias and no record of any decision —
    it was simply WRITTEN on a day the question was already being asked, so it was in front
    of the model, and what that round decided is that round's business."""
    for day in (REPORTED_SINCE, "2026-07-01"):
        component = PeopleComponent(
            FAMILY,
            content=_LibraryStore(rows=[MEI_TERM_DATED]),
            canonical=_WrittenCanonical({MEI_PATH: day}),
        )
        draft = await _round(component, [_mei_page()])
        assert component.gate_checks(draft.documents(), draft.base_documents()) == []
        # nothing on the page says so — the two derived dates do
        assert set(draft.documents()[MEI_PATH].frontmatter) == {
            "doc_id", "type", "slug", "identities"
        }
    # …and the walk is bounded to this component's own family
    assert component._canonical.prefixes == ["memory/people/"]


async def test_the_two_unknown_dates_both_mean_ask():
    """A page created this round has no committed write day, and a projection row from a
    library that predates the stamp has no date either. Silence is earned by two dates that
    exist and order the right way; an absent one is a library that cannot say the question
    was ever seen."""
    # a page created this round — written, but never committed
    component = PeopleComponent(
        FAMILY,
        content=_LibraryStore(rows=[MEI_TERM_DATED]),
        canonical=_WrittenCanonical({}),
    )
    draft = await _round(component, [])
    draft.create_document(
        MEI_PATH,
        {"type": "person", "slug": "mei-lin", "identities": "im:u_mei"},
        "# Mei LIN\n\n- 排期当天定。[cite: arc-1 ¶1-1]",
    )
    assert [v.kind for v in component.gate_checks(
        draft.documents(), draft.base_documents()
    )] == ["people.alias_undecided"]

    # …and a row with no stamp, on a page written long after any date it might have had
    component = PeopleComponent(
        FAMILY,
        content=_LibraryStore(rows=[MEI_TERM]),  # no `reported_since`
        canonical=_WrittenCanonical({MEI_PATH: "2030-01-01"}),
    )
    draft = await _round(component, [_mei_page()])
    assert [v.kind for v in component.gate_checks(
        draft.documents(), draft.base_documents()
    )] == ["people.alias_undecided"]


async def test_an_unreadable_write_history_asks_rather_than_refusing_or_forgiving():
    """The failure direction that is safe, and the reason this half is NOT a readiness bit.
    `people.not_ready` exists for a check that goes always-TRUE on an empty mirror and lets
    through the writes it exists to refuse. This one degrades the other way: with no write
    days the question is asked, which costs a round's attention and never a wrong page."""

    class _Broken(_WrittenCanonical):
        async def written_on(self, user_id, *, prefix=""):
            raise RuntimeError("git is having a day")

    component = PeopleComponent(
        FAMILY, content=_LibraryStore(rows=[MEI_TERM_DATED]), canonical=_Broken()
    )
    draft = await _round(component, [_mei_page()])
    # not refused — asked
    assert [v.kind for v in component.gate_checks(
        draft.documents(), draft.base_documents()
    )] == ["people.alias_undecided"]


async def test_the_index_job_never_asks_canonical_for_the_write_days():
    """A `git log` walk per indexed source would buy the index job nothing: the write days
    are read by the one job that judges the decision, at the head of it."""
    canonical = _WrittenCanonical({MEI_PATH: "2026-07-01"})
    source = _im_source(DECIDE_CORPUS, DECIDE_USERS)
    component = PeopleComponent(
        FAMILY, content=_LibraryStore([source], rows=[]), canonical=canonical
    )
    await component.on_source_indexed(str(USER), source)
    assert canonical.prefixes == []

    await component.prepare(str(USER))
    assert canonical.prefixes == ["memory/people/"]


async def test_declining_answers_this_round_and_writes_nothing_at_all():
    """`decline_alias` is the round's answer and nothing else: the gate is satisfied, the
    page is byte-for-byte what it was, and no field records the refusal."""
    component = PeopleComponent(
        FAMILY,
        content=_LibraryStore(rows=[MEI_TERM_DATED]),
        canonical=_WrittenCanonical({MEI_PATH: "2026-06-14"}),
    )
    draft = await _round(component, [_mei_page()])

    answer = _decline_tool(component, draft).func(path=MEI_PATH, term="阿宝", reason="honorific")
    assert answer.startswith('declined: "阿宝" is not a name of `memory/people/mei-lin.md`')
    assert "honorific" in answer and "nothing is stored" in answer
    assert "once this page commits" in answer
    # nothing reached the page — not a field, not an alias, not a claim
    assert draft.documents()[MEI_PATH].frontmatter == draft.base_documents()[MEI_PATH].frontmatter
    assert draft.documents()[MEI_PATH].body == draft.base_documents()[MEI_PATH].body
    assert "declined" not in draft.to_files()[MEI_PATH]
    assert not draft.is_dirty()
    # …and the gate a moment later sees the question answered
    assert component.gate_checks(draft.documents(), draft.base_documents()) == []
    assert component.is_declined(USER, "阿宝", "im:u_mei")


async def test_a_decline_lasts_one_round_and_the_next_job_starts_clean():
    """Job-local by construction: `prepare` clears it, so the same process running a second
    compile asks again unless the page was written in between."""
    component = PeopleComponent(
        FAMILY,
        content=_LibraryStore(rows=[MEI_TERM_DATED]),
        canonical=_WrittenCanonical({MEI_PATH: "2026-06-14"}),
    )
    draft = await _round(component, [_mei_page()])
    _decline_tool(component, draft).func(path=MEI_PATH, term="阿宝")
    assert component.declines(USER) != {}

    later = await _round(component, [_mei_page()])
    assert component.declines(USER) == {}
    assert [v.kind for v in component.gate_checks(
        later.documents(), later.base_documents()
    )] == ["people.alias_undecided"]


async def test_decline_alias_needs_no_read_because_it_writes_nothing():
    """It used to be refused on a page the round had not read — the rule every whole-region
    WRITE is held to. Nothing is written now, so there is no previous state a write would be
    replacing unobserved, and refusing would spend a round teaching nothing. A round that
    means the decline to last writes the page, and writing it requires reading it anyway."""
    component = PeopleComponent(
        FAMILY,
        content=_LibraryStore(rows=[MEI_TERM_DATED]),
        canonical=_WrittenCanonical({MEI_PATH: "2026-06-14"}),
    )
    draft = await _round(component, [_mei_page()])  # no `mark_read`

    assert "declined" in _decline_tool(component, draft).func(path=MEI_PATH, term="阿宝")
    assert component.gate_checks(draft.documents(), draft.base_documents()) == []


async def test_the_undecided_list_is_capped_and_says_how_many_it_cut():
    rows = [
        dict(MEI_TERM, term=f"term{n:02d}", answered=9, co_mention=0)
        for n in range(ALIAS_UNDECIDED_MAX + 3)
    ]
    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=rows))
    draft = await _round(component, [_mei_page()])

    violations = component.gate_checks(draft.documents(), draft.base_documents())
    assert len(violations) == ALIAS_UNDECIDED_MAX
    assert [v.detail.split('"')[1] for v in violations] == [f"term{n:02d}" for n in range(8)]
    assert violations[-1].detail.endswith("…and 3 more undecided terms, listed once these are.")


async def test_nothing_is_demanded_where_there_is_no_reported_term_or_no_present_person():
    # a page whose subject this compile's sources do not carry
    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=[MEI_TERM]))
    other = CanonicalDocument(
        doc_id=DocumentId("d-ravi"),
        path="memory/people/ravi-seth.md",
        frontmatter={"doc_id": "d-ravi", "type": "person", "slug": "ravi-seth", "identities": "mailto:ravi@example.com"},
        body="# Ravi SETH\n\n- 负责物料。[cite: arc-1 ¶1-1] <!-- c:0c01 -->",
    )
    draft = await _round(component, [other])
    assert component.gate_checks(draft.documents(), draft.base_documents()) == []

    # …and the sharper case: a page that BINDS the very identity the term is reported for,
    # while this compile's sources carry nobody by that name. The demand is about the people
    # this round is reading about; a library-wide sweep would make every compile answer for
    # every page, which is the shape of rule that gets a library stuck.
    absent = PeopleComponent(
        FAMILY,
        content=_LibraryStore(rows=[dict(MEI_TERM_DATED, target_identity="im:u_lan")]),
        canonical=_WrittenCanonical({"memory/people/lan-liu.md": "2026-06-14"}),
    )
    lan = CanonicalDocument(
        doc_id=DocumentId("d-lan"),
        path="memory/people/lan-liu.md",
        frontmatter={"doc_id": "d-lan", "type": "person", "slug": "lan-liu", "identities": "im:u_lan"},
        body="# Lan LIU\n\n- 负责对照表。[cite: arc-1 ¶1-1] <!-- c:0d01 -->",
    )
    draft = await _round(absent, [lan])
    assert absent.page_terms(absent._mirrored_terms(str(USER)), draft.documents()[lan.path])
    assert absent.gate_checks(draft.documents(), draft.base_documents()) == []

    # a present person with nothing reported about them
    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=[]))
    draft = await _round(component, [_mei_page()])
    assert component.gate_checks(draft.documents(), draft.base_documents()) == []

    # …and a compile with no sources at all decides nothing
    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=[MEI_TERM]))
    draft = await _round(component, [_mei_page()], sources=[])
    assert component.gate_checks(draft.documents(), draft.base_documents()) == []


async def test_decline_alias_refuses_an_unknown_page_a_recorded_alias_and_an_unreported_term():
    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=[MEI_TERM]))
    draft = await _round(component, [_mei_page(aliases="小林")])
    draft.mark_read(MEI_PATH)
    tool = _decline_tool(component, draft)

    assert "no person page at" in tool.func(path="memory/topics/x.md", term="阿宝")
    # a term the page RECORDS is a confirmation, and a confirmation is not declined
    assert "already records" in tool.func(path=MEI_PATH, term="小林")
    assert "nothing to decline" in tool.func(path=MEI_PATH, term="momo")
    # nothing reached the page, and nothing reached the round's own record of its decisions
    assert draft.documents()[MEI_PATH].frontmatter == draft.base_documents()[MEI_PATH].frontmatter
    assert component.declines(USER) == {}


async def test_the_preamble_states_the_rule_and_never_states_a_decline():
    """The reported line says what has to happen to a term before the round ends. There is no
    `declined:` line any more, and there is nothing for one to read: a decline is this
    round's answer and reaches no page."""
    source = _im_source(DECIDE_CORPUS, DECIDE_USERS)
    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=[MEI_TERM_DATED]))
    await component.prepare(str(USER))

    lines = component.source_preamble(source).splitlines()
    reported = next(x for x in lines if x.startswith("How the library's turns call"))
    assert "asked once, and closed by writing the page" in reported
    assert "decline_alias" in reported
    assert not any(x.startswith("declined") for x in lines)

    # …and a round that declines does not change what the next source's preamble states
    draft = await _round(component, [_mei_page()])
    _decline_tool(component, draft).func(path=MEI_PATH, term="阿宝")
    assert component.source_preamble(source).splitlines() == lines


# --- names nothing structural can target ---------------------------------------------------


def test_a_name_shaped_token_is_latin_word_or_a_bracketed_cjk_core():
    assert name_shaped_tokens("和 momo 商量一下") == ["momo"]
    assert name_shaped_tokens("Ravi 说他来跟") == ["Ravi"]
    # CJK needs a bracket particle, and the core is 2–3 characters
    assert name_shaped_tokens("和小林商量一下") == []  # nothing says where the name stops
    assert name_shaped_tokens("找小林，物料他清楚") == ["小林"]
    assert name_shaped_tokens("小林说这版可以") == ["小林"]
    assert name_shaped_tokens("@小林 这版可以") == ["小林"]
    # not names: acronyms, identifiers, one letter, a run nothing brackets
    assert name_shaped_tokens("API msgId a017 x 这版排期确认了") == []


async def test_the_preamble_lists_repeated_names_nothing_present_accounts_for():
    """A nickname can be a vocative once and a third-person mention fifty times; no turn
    structure can point those fifty at anybody. The line states the tokens and stops."""
    corpus = [
        ("u_owner", _at(9, 0), "这版先和 momo 商量，别的等排期。"),
        ("u_mei", _at(9, 2), "好，我问下 momo 的意见。"),
        ("u_owner", _at(9, 5), "找小林，momo 那边我来说。"),
        ("u_mei", _at(9, 7), "小林说他今天在。"),
    ]
    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=[]))
    await component.prepare(str(USER))
    source = _im_source(corpus, DECIDE_USERS)

    [line] = [
        x
        for x in component.source_preamble(source).splitlines()
        if x.startswith("Names in this source matching no present identity")
    ]
    assert line.endswith("momo ×3, 小林 ×2")
    assert "no target is implied" in line


def test_the_unresolved_names_line_subtracts_everything_already_accounted_for():
    from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, StructureMap

    source = NormalizedSource(
        raw=_raw("doc-1", "document", {}, "2026-05-12"),
        blocks=[
            NormalizedBlock(index=0, text="和 momo 商量，找小林，Ravi 说他来跟。"),
            NormalizedBlock(index=1, text="momo 那边我来说，小林说他今天在，Ravi 明天到。"),
        ],
        structure=StructureMap(),
    )
    assert unresolved_names(source) == [("Ravi", 2), ("momo", 2), ("小林", 2)]
    # a name the library already accounts for is not an unresolved name…
    assert [t for t, _ in unresolved_names(source, known=["Ravi SETH"])] == ["momo", "小林"]
    # …nor is a term this same preamble states elsewhere
    assert [t for t, _ in unresolved_names(source, known=["Ravi SETH"], stated=["MOMO"])] == ["小林"]
    # once is the text, not a discovery
    assert unresolved_names(
        NormalizedSource(
            raw=_raw("doc-2", "document", {}, "2026-05-12"),
            blocks=[NormalizedBlock(index=0, text="和 momo 商量，找小林。")],
            structure=StructureMap(),
        )
    ) == []


async def test_the_unresolved_names_line_is_capped_and_says_how_many_it_cut():
    names = [f"nom{chr(ord('a') + n)}" for n in range(UNRESOLVED_MAX + 2)]
    text = " ".join(f"和 {name} 商量。" for name in names) * 2
    corpus = [("u_owner", _at(9, 0), text), ("u_mei", _at(9, 2), "好。")]
    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=[]))
    await component.prepare(str(USER))

    [line] = [
        x
        for x in component.source_preamble(_im_source(corpus, DECIDE_USERS)).splitlines()
        if x.startswith("Names in this source matching no present identity")
    ]
    assert line.count("×2") == UNRESOLVED_MAX
    assert line.endswith("; …and 2 more")


# --- end to end: the round does not finish with the question open -------------------------


class _FakeCanonicalStore:
    """The canonical port as `run_compile` needs it: list, read, commit, snapshot."""

    def __init__(self, docs=()):
        from pneuma_knowledge_core.domain.snapshot import SnapshotRef

        self._docs = list(docs)
        self._ref = SnapshotRef
        self.commits: list[dict[str, str]] = []
        #: the day this store stamps a commit with, and path -> the day of its last one
        self.day = "2026-07-01"
        self.days: dict[str, str] = {}

    async def list(self, user_id, *, at=None):
        return list(self._docs)

    async def read(self, user_id, document_id, *, at=None):
        return next((d for d in self._docs if d.doc_id == document_id), None)

    async def commit_patch(self, user_id, files, *, message):
        self.commits.append(dict(files))
        for path in files:
            self.days[path] = self.day
        return self._ref(ref=f"commit-{len(self.commits)}")

    async def written_on(self, user_id, *, prefix=""):
        """The read-only face's clock, out of the same history: the day of the last commit
        that carried each path. A round that aborts never commits, so it never appears."""
        return {p: d for p, d in self.days.items() if p.startswith(prefix)}

    def snapshots(self, user_id):
        return [self._ref(ref=f"commit-{i + 1}") for i in range(len(self.commits))]

    def tag(self, user_id, ref, label):
        return self._ref(ref=label, label=label)


class _ScriptedChatModel(BaseChatModel):
    """One AIMessage of tool calls per round, then a plain answer.

    `heard` keeps every message the model was handed, tool results included — the only way
    a test can assert that a WRITE-FACE refusal actually reached the model, rather than
    inferring it from a final state a later write would have produced anyway.
    """

    turns: list = []
    heard: list = []
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.heard.extend(str(getattr(m, "content", "")) for m in messages)
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        if self._cursor < len(self.turns):
            calls = self.turns[self._cursor]
            self._cursor += 1
            message = AIMessage(content="", tool_calls=calls, usage_metadata=usage)
        else:
            message = AIMessage(content="done", usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


_call_ids = count()


def _tc(name: str, **args) -> dict:
    return {"name": name, "args": args, "id": f"call-{next(_call_ids)}", "type": "tool_call"}


def _decide_l0_source(sid: str = "im-01"):
    from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, StructureMap

    raw = RawSource(
        source_id=SourceId(sid),
        user_id=USER,
        kind="im",
        title="运营群",
        mime="text/plain",
        checksum=sid,
        created_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        meta={
            "owner_user_ids": ["u_owner"],
            "users": [
                {"user_id": uid, "display_name": name, "email": None, "is_bot": False}
                for uid, name in DECIDE_USERS
            ],
            "occurred_on": "2026-05-12",
        },
    )
    return NormalizedSource(
        raw=raw,
        blocks=[
            NormalizedBlock(index=i, text=text) for i, (_, _, text) in enumerate(DECIDE_CORPUS)
        ],
        structure=StructureMap(),
    )


async def test_a_round_that_leaves_a_reported_term_undecided_is_sent_back_and_repaired():
    """The whole mechanism through the runner: the model writes the page and finishes; the
    gate refuses the round because a reported term was left undecided; the repair round
    records it and the compile commits."""
    from pneuma_knowledge_core.compile.runner import run_compile
    from pneuma_knowledge_core.skill import load_skill_base

    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=[MEI_TERM]))
    register_component(component)
    store = _FakeCanonicalStore()
    model = _ScriptedChatModel(
        turns=[
            [
                _tc(
                    "create_document",
                    path=MEI_PATH,
                    frontmatter={
                        "type": "person",
                        "slug": "mei-lin",
                        "identities": "im:u_mei",
                    },
                    body="## 工作方式\n\n- 排期当天定完。[cite: im-01 ¶1]",
                ),
                _tc("finish_compile"),
            ],
            [
                _tc("set_fields", path=MEI_PATH, fields={"aliases": "阿宝"}),
                _tc("finish_compile"),
            ],
        ]
    )

    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_decide_l0_source()],
        skill=load_skill_base("v1"),
    )
    assert result.status == "committed"
    assert result.rounds == 2
    assert "aliases: 阿宝" in result.files[MEI_PATH]
    # and the page the model was sent back to is the one the violation named
    assert component.declines(USER) == {}


async def test_a_round_may_end_the_question_by_declining_instead():
    """…and the next round is silent because the page was WRITTEN, not because anything was
    stored. The commit carries no record of the decision at all: what the round ruled is that
    the term is not this person's name, and a name that is not somebody's is not knowledge."""
    from pneuma_knowledge_core.compile.runner import run_compile
    from pneuma_knowledge_core.skill import load_skill_base

    store = _FakeCanonicalStore()
    store.day = "2026-07-01"  # after the day the library started asking
    store_rows = _LibraryStore(rows=[MEI_TERM_DATED])
    component = PeopleComponent(FAMILY, content=store_rows, canonical=store)
    register_component(component)
    model = _ScriptedChatModel(
        turns=[
            [
                _tc(
                    "create_document",
                    path=MEI_PATH,
                    frontmatter={"type": "person", "slug": "mei-lin", "identities": "im:u_mei"},
                    body="## 工作方式\n\n- 排期当天定完。[cite: im-01 ¶1]",
                ),
                _tc("finish_compile"),
            ],
            [
                _tc("decline_alias", path=MEI_PATH, term="阿宝", reason="honorific"),
                _tc("finish_compile"),
            ],
        ]
    )

    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_decide_l0_source()],
        skill=load_skill_base("v1"),
    )
    assert result.status == "committed"
    assert result.rounds == 2
    # NOTHING about the decision reached the page: no field, no alias, no claim
    committed = store.commits[-1][MEI_PATH]
    assert "declined" not in committed and "阿宝" not in committed
    assert "aliases" not in committed
    assert not hasattr(store_rows, "decisions")  # and nothing outside canonical holds it

    # the next compile: the page was committed on a day the term was already reported, so the
    # question is closed — by the write, and by nothing the write said
    later = PeopleComponent(
        FAMILY, content=_LibraryStore(rows=[MEI_TERM_DATED]), canonical=store
    )
    draft = await _round(later, [_mei_page()])
    assert later.gate_checks(draft.documents(), draft.base_documents()) == []
    assert "declined" not in "".join(draft.documents()[MEI_PATH].frontmatter)


async def test_a_decline_in_a_round_that_aborts_leaves_nothing_behind():
    """The finding this design closes, twice over. A decline used to be a row in its own
    table, written the moment the tool was called, so a round that then failed the gate left
    a durable judgement behind while canonical stayed untouched. It was a page field next,
    which tied it to the commit but put a list of non-names in the library. It is neither
    now: the decline answers one round, and the round that aborts commits nothing — so the
    page's last write day does not move, and the next compile asks again."""
    from pneuma_knowledge_core.compile.runner import run_compile
    from pneuma_knowledge_core.skill import load_skill_base

    store = _FakeCanonicalStore([_mei_page()])
    store.days = {MEI_PATH: "2026-06-14"}  # written BEFORE the term became reported
    component = PeopleComponent(
        FAMILY, content=_LibraryStore(rows=[MEI_TERM_DATED]), canonical=store
    )
    register_component(component)
    #: The round declines the term and then writes a claim citing a source that is not in
    #: this compile — the gate refuses, both rounds.
    turns = [
        [
            _tc("read_document", path=MEI_PATH),
            _tc("decline_alias", path=MEI_PATH, term="阿宝", reason="honorific"),
            _tc("append_block", path=MEI_PATH, heading="工作方式", text="- 物料他跟。[cite: s99 ¶1]"),
            _tc("finish_compile"),
        ],
        [_tc("finish_compile")],
    ]
    result = await run_compile(
        user_id=USER,
        model=_ScriptedChatModel(turns=turns),
        store=store,
        sources=[_decide_l0_source()],
        skill=load_skill_base("v1"),
    )
    assert result.status == "aborted"
    assert [v.kind for v in result.violations] == ["citation"]  # the term WAS decided
    assert store.commits == []  # …and canonical is untouched
    assert store.days == {MEI_PATH: "2026-06-14"}  # the page's last write day did not move

    # …so the next compile asks again: nothing was committed, so nothing was answered
    fresh = PeopleComponent(
        FAMILY, content=_LibraryStore(rows=[MEI_TERM_DATED]), canonical=store
    )
    draft = await _round(fresh, [_mei_page()])
    assert [v.kind for v in fresh.gate_checks(
        draft.documents(), draft.base_documents()
    )] == ["people.alias_undecided"]


# --- two speakers of one conversation are two people --------------------------------------
#
# The defect, observed on a real library built before the collision rules: a person page
# ended with three identities and three aliases, all of them lifted from a group chat's
# title. Nothing caught it — the other two people had no page of their own to collide with,
# and the display names were the sources' own. The fact that does catch it needs no
# judgement and no channel knowledge: two identities that both SPEAK in one conversation
# are two people.

COSPEAK_USERS = [("u_owner", "Ke ZHOU"), ("u_mei", "Mei LIN"), ("u_ravi", "Ravi SETH")]

#: Both non-owner identities take a turn of their own.
COSPEAK_CORPUS = [
    ("u_owner", _at(9, 0), "这版排期谁来定？"),
    ("u_mei", _at(9, 2), "我来定，今天发群里。"),
    ("u_ravi", _at(9, 5), "物料清单我这边跟。"),
]

#: The same three in the same room, and only one of them ever speaks.
QUIET_CORPUS = [
    ("u_owner", _at(9, 0), "这版排期谁来定？"),
    ("u_mei", _at(9, 2), "我来定，Ravi SETH 那边的物料我一起问。"),
]


def _people_round(component, docs, sources):
    """One round's shape for a component with no store behind it: register, build the draft,
    then `compile_tools` — which is where the component learns whose library this is and
    folds this compile's own sources into the mirror the sync faces read."""
    reset_components()
    register_component(component)
    draft = PatchDraft.from_canonical(docs, TEMPLATES)
    component.compile_tools(draft, sources=list(sources))
    return draft


def _people_violations(draft):
    return [(v.kind, v.path) for v in run_gate(draft, []) if v.kind.startswith("people.")]


COSPEAK_REFUSAL = (
    "im:u_ravi and im:u_mei both speak in 运营群 (2026-05-12); one page cannot bind two "
    "speakers of one conversation — keep the identity of this page's subject, and give the "
    "other person their own page if they earn one."
)


def test_two_identities_that_speak_in_one_conversation_cannot_be_one_page():
    """The write face refuses it before the round is spent, and the gate says it again."""
    component = PeopleComponent(FAMILY)
    draft = _people_round(
        component,
        [_person("mei-lin", "im:u_mei", title="Mei LIN")],
        [_im_source(COSPEAK_CORPUS, COSPEAK_USERS, archive="grp-1")],
    )
    draft.mark_read(MEI_PATH)
    with pytest.raises(AnchorToolError) as err:
        draft.set_fields(MEI_PATH, {"identities": "im:u_mei, im:u_ravi"})
    assert COSPEAK_REFUSAL in str(err.value)
    # nothing was written by the refusal
    assert draft.documents()[MEI_PATH].frontmatter["identities"] == "im:u_mei"
    # the page's own identity alone goes straight in
    assert draft.set_fields(MEI_PATH, {"identities": "im:u_mei"}).frontmatter["identities"]
    assert _people_violations(draft) == []
    # …and the gate stands behind the tool face as the final arbiter
    draft.documents()[MEI_PATH].frontmatter["identities"] = "im:u_mei, im:u_ravi"
    assert _people_violations(draft) == [("people.identity_cospeakers", MEI_PATH)]


def test_a_third_speaker_costs_one_refusal_and_names_the_identity_it_would_keep():
    """Three ids from one group chat — the shape the real page had. Each one after the first
    is measured against the ones still standing, so the list says which to keep once."""
    component = PeopleComponent(FAMILY)
    draft = _people_round(
        component,
        [_person("mei-lin", "im:u_mei", title="Mei LIN")],
        [
            _im_source(
                [*COSPEAK_CORPUS, ("u_kai", _at(9, 8), "我这边同步给排期的人。")],
                [*COSPEAK_USERS, ("u_kai", "Kai SUN")],
                archive="grp-1",
            )
        ],
    )
    draft.mark_read(MEI_PATH)
    with pytest.raises(AnchorToolError) as err:
        draft.set_fields(MEI_PATH, {"identities": "im:u_mei, im:u_ravi, im:u_kai"})
    said = str(err.value)
    assert "im:u_ravi and im:u_mei both speak in" in said
    assert "im:u_kai and im:u_mei both speak in" in said
    assert "im:u_kai and im:u_ravi" not in said


def test_members_who_never_both_speak_are_not_two_people_by_this_fact():
    """Membership is not speech, and a mention is not speech. Two ids may still be one
    person reached two ways — which is the whole reason a page binds several."""
    # (a) a member list and no turns at all
    component = PeopleComponent(FAMILY)
    draft = _people_round(
        component,
        [_person("mei-lin", "im:u_mei", title="Mei LIN")],
        [_normalized(_im_users(("u_mei", "Mei LIN"), ("u_ravi", "Ravi SETH")))],
    )
    draft.mark_read(MEI_PATH)
    doc = draft.set_fields(MEI_PATH, {"identities": "im:u_mei, im:u_ravi"})
    assert doc.frontmatter["identities"] == "im:u_mei, im:u_ravi"
    assert _people_violations(draft) == []

    # (b) both in the room, one only ever spoken ABOUT
    component = PeopleComponent(FAMILY)
    draft = _people_round(
        component,
        [_person("mei-lin", "im:u_mei", title="Mei LIN")],
        [_im_source(QUIET_CORPUS, COSPEAK_USERS, archive="grp-2")],
    )
    draft.mark_read(MEI_PATH)
    assert draft.set_fields(MEI_PATH, {"identities": "im:u_mei, im:u_ravi"}).frontmatter[
        "identities"
    ] == "im:u_mei, im:u_ravi"
    assert _people_violations(draft) == []


def _mail_thread(*, subject: str = "对账单"):
    """One thread, two senders, and a third address that only ever appears on `to`."""
    payload = {
        "schema": "pneuma.source.email/v1",
        "provider": "mock",
        "archive_id": "arc-m",
        "owner_addresses": ["ke.zhou@self.example"],
        "threads": [
            {
                "thread_id": "t-1",
                "subject": subject,
                "messages": [
                    {
                        "message_id": "e1",
                        "sent_at": _at(9, 0),
                        "from": {"address": "mei.lin@example.com", "display_name": "Mei LIN"},
                        "to": [
                            {"address": "ke.zhou@self.example", "display_name": "Ke ZHOU"},
                            {"address": "kai.sun@example.com", "display_name": "Kai SUN"},
                        ],
                        "cc": [],
                        "subject": subject,
                        "text": "这个月的对账单我明天发你。",
                    },
                    {
                        "message_id": "e2",
                        "sent_at": _at(10, 0),
                        "from": {"address": "ravi.seth@example.com", "display_name": "Ravi SETH"},
                        "to": [{"address": "ke.zhou@self.example", "display_name": "Ke ZHOU"}],
                        "cc": [],
                        "subject": subject,
                        "text": "物料清单我这边一起附上。",
                    },
                ],
            }
        ],
    }
    [thread] = normalize_source_contract(
        EmailSource.model_validate(payload),
        USER,
        imported_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
    )
    return thread


def test_two_senders_of_one_mail_thread_are_not_two_people_by_this_fact():
    """An email address is not a person id. One human writing from a work address and a
    personal one is ordinary, and the correct page binds both — `email/v1` carries no stable
    actor id and no equivalence relation, so a hard refusal built on two `from` headers could
    only be answered by discarding a truthful identity or turning the rule off. The fact
    stays silent here; `im` senders and `meeting` speakers are where it has person ids."""
    component = PeopleComponent(FAMILY)
    draft = _people_round(
        component,
        [_person("mei-lin", "mailto:mei.lin@example.com", title="Mei LIN")],
        [_mail_thread()],
    )
    draft.mark_read(MEI_PATH)
    assert draft.set_fields(
        MEI_PATH,
        {"identities": "mailto:mei.lin@example.com, mailto:ravi.seth@example.com"},
    ).frontmatter["identities"].endswith("mailto:ravi.seth@example.com")
    # …the addressee likewise: it never took a turn either, and nothing is said about it
    assert draft.set_fields(
        MEI_PATH,
        {"identities": "mailto:mei.lin@example.com, mailto:kai.sun@example.com"},
    ).frontmatter["identities"].endswith("mailto:kai.sun@example.com")
    assert _people_violations(draft) == []


def test_a_page_created_this_round_holding_two_speakers_is_refused_by_the_gate():
    """`create_document` writes its frontmatter whole and has no write-face check behind it;
    the gate judges a page this round created exactly like one it changed."""
    component = PeopleComponent(FAMILY)
    draft = _people_round(
        component, [], [_im_source(COSPEAK_CORPUS, COSPEAK_USERS, archive="grp-1")]
    )
    draft.create_document(
        MEI_PATH,
        {"type": "person", "slug": "mei-lin", "identities": "im:u_mei, im:u_ravi"},
        "# Mei LIN\n\n- 排期当天定完。[cite: grp-1 ¶1]",
    )
    assert _people_violations(draft) == [("people.identity_cospeakers", MEI_PATH)]


def test_a_page_that_already_holds_two_speakers_stops_nothing_until_it_is_written():
    """The same grandfathering the other two facts have, and the reason it matters here: the
    page this rule was written for already exists in a real library, wrong. It must not make
    every later compile in that library unpassable — only the round that touches it."""
    component = PeopleComponent(FAMILY)
    draft = _people_round(
        component,
        [_person("mei-lin", "im:u_mei, im:u_ravi", title="Mei LIN")],
        [_im_source(COSPEAK_CORPUS, COSPEAK_USERS, archive="grp-1")],
    )
    draft.create_document(
        "memory/topics/print.md",
        {"type": "topic", "slug": "print"},
        "# 印务\n\n- 新事实。[cite: grp-1 ¶1]",
    )
    assert _people_violations(draft) == []
    # the moment the page's own frontmatter is written, the rule applies to it in full
    draft.documents()[MEI_PATH].frontmatter["aliases"] = "小林"
    assert _people_violations(draft) == [("people.identity_cospeakers", MEI_PATH)]


def test_an_alias_is_refused_when_its_carrier_speaks_beside_this_pages_own_identity():
    """The same fact from the alias side. Two people in one group carry the display name
    `Mei LIN`, and one of them speaks beside this page's subject — so the library cannot
    tell whose name it is, and the page may not take it on a count. Without the co-speaking
    fact this passed: one carrier WAS this page's own identity."""
    component = PeopleComponent(FAMILY)
    draft = _people_round(
        component,
        [_person("mei-lin", "im:u_mei", title="小林")],
        [
            _im_source(
                [
                    ("u_owner", _at(9, 0), "这版排期谁来定？"),
                    ("u_mei", _at(9, 2), "我来定。"),
                    ("u_mei2", _at(9, 5), "物料我这边跟。"),
                ],
                [("u_owner", "Ke ZHOU"), ("u_mei", "Mei LIN"), ("u_mei2", "Mei LIN")],
                archive="grp-3",
            )
        ],
    )
    draft.mark_read(MEI_PATH)
    with pytest.raises(AnchorToolError) as err:
        draft.set_fields(MEI_PATH, {"aliases": "Mei LIN"})
    assert (
        "the display name this library's sources record for im:u_mei2, who SPEAKS beside "
        "this page's own identity in one conversation" in str(err.value)
    )
    assert "aliases" not in draft.documents()[MEI_PATH].frontmatter


def test_a_call_writing_only_aliases_is_not_asked_about_the_identities_it_did_not_write():
    """`validate_fields` judges what the call carries. A grandfathered page whose declared
    identities co-speak may still record an alias — the gate is where that page's own
    frontmatter, once written, answers for itself."""
    component = PeopleComponent(FAMILY)
    draft = _people_round(
        component,
        [_person("mei-lin", "im:u_mei, im:u_ravi", title="Mei LIN")],
        [_im_source(COSPEAK_CORPUS, COSPEAK_USERS, archive="grp-1")],
    )
    draft.mark_read(MEI_PATH)
    assert draft.set_fields(MEI_PATH, {"aliases": "小林"}).frontmatter["aliases"] == "小林"
    assert _people_violations(draft) == [("people.identity_cospeakers", MEI_PATH)]


def _cospeak_l0_source(sid: str = "im-02", user: UserId = USER):
    from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, StructureMap

    raw = RawSource(
        source_id=SourceId(sid),
        user_id=user,
        kind="im",
        title="运营群",
        mime="text/plain",
        checksum=sid,
        # the INGEST clock, which is what the incremental source read is cursored on — this
        # conversation happened in May (`occurred_on` below) and was imported in June, after
        # `_other_l0_source`, which is the order the tests below import them in
        created_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
        meta={
            "owner_user_ids": ["u_owner"],
            "users": [
                {"user_id": uid, "display_name": name, "email": None, "is_bot": False}
                for uid, name in COSPEAK_USERS
            ],
            "messages": [
                {"message_id": f"m{i}", "sender_id": sender}
                for i, (sender, _, _) in enumerate(COSPEAK_CORPUS)
            ],
            "occurred_on": "2026-05-12",
        },
    )
    return NormalizedSource(
        raw=raw,
        blocks=[
            NormalizedBlock(index=i, text=text) for i, (_, _, text) in enumerate(COSPEAK_CORPUS)
        ],
        structure=StructureMap(),
    )


async def test_a_round_that_binds_two_speakers_is_refused_at_the_tool_face_and_repaired():
    """The whole mechanism through the runner: the model writes both ids, the write tool
    refuses with the fact, the model writes one — and the compile commits."""
    from pneuma_knowledge_core.compile.runner import run_compile
    from pneuma_knowledge_core.skill import load_skill_base

    component = PeopleComponent(FAMILY, content=_LibraryStore())
    register_component(component)
    model = _ScriptedChatModel(
        turns=[
            [
                _tc(
                    "create_document",
                    path=MEI_PATH,
                    frontmatter={"type": "person", "slug": "mei-lin"},
                    body="## 工作方式\n\n- 排期当天定完。[cite: im-02 ¶1]",
                ),
                _tc("set_fields", path=MEI_PATH, fields={"identities": "im:u_mei, im:u_ravi"}),
            ],
            [
                _tc("set_fields", path=MEI_PATH, fields={"identities": "im:u_mei"}),
                _tc("finish_compile"),
            ],
        ]
    )

    result = await run_compile(
        user_id=USER,
        model=model,
        store=_FakeCanonicalStore(),
        sources=[_cospeak_l0_source()],
        skill=load_skill_base("v1"),
    )
    assert result.status == "committed"
    assert result.rounds == 1
    # the refusal reached the model, in the words the rule states it in
    assert any(COSPEAK_REFUSAL in text for text in model.heard)
    assert "identities: im:u_mei" in result.files[MEI_PATH]
    assert "im:u_ravi" not in result.files[MEI_PATH]


# --- a round whose only write is a structured field is a round -----------------------------


def _field_page(aliases: str = ""):
    fm = {"doc_id": "d-mei", "type": "person", "slug": "mei-lin", "identities": "im:u_mei"}
    if aliases:
        fm["aliases"] = aliases
    return CanonicalDocument(
        doc_id=DocumentId("d-mei"),
        path=MEI_PATH,
        frontmatter=fm,
        body="# Mei LIN\n\n- 排期当天定完。[cite: im-02 ¶1] <!-- c:0b01 -->",
    )


async def _fields_only_round(docs):
    """One compile whose only write is `set_fields` on an existing page."""
    from pneuma_knowledge_core.compile.runner import run_compile
    from pneuma_knowledge_core.skill import load_skill_base

    reset_components()
    register_component(PeopleComponent(FAMILY, content=_LibraryStore()))
    store = _FakeCanonicalStore(docs)
    model = _ScriptedChatModel(
        turns=[
            [
                _tc("read_document", path=MEI_PATH),
                _tc("set_fields", path=MEI_PATH, fields={"aliases": "小林"}),
                _tc("finish_compile"),
            ]
        ]
    )
    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_cospeak_l0_source()],
        skill=load_skill_base("v1"),
    )
    return result, store


async def test_a_compile_whose_only_write_is_a_field_commits_and_the_same_write_again_is_a_noop():
    """`set_fields` changes no prose, and a dirtiness test that only compared BODIES called
    such a round a no-op and threw the write away. The structured fields are as canonical as
    the claims beside them — and writing the same values back is still nothing to commit."""
    result, store = await _fields_only_round([_field_page()])
    assert result.status == "committed"
    assert "aliases: 小林" in result.files[MEI_PATH]
    assert "aliases: 小林" in store.commits[-1][MEI_PATH]

    # the library now holds it; the identical round changes no byte and commits nothing
    again, store_again = await _fields_only_round([_field_page("小林")])
    assert again.status == "noop"
    assert store_again.commits == []


# --- what "the round touched this page" means ----------------------------------------------
#
# The rules above are judged over the pages a round TOUCHED, and touched has exactly one
# definition — the framework's own (`compile/patch.py:touched_this_round`): body OR
# frontmatter differs from base, or the page is new. Judging only the frontmatter left the
# grandfathered page this rule exists for uncorrected through its commonest future write: a
# compile that appends one claim to it and edits no field.

GRANDFATHERED_IDS = "im:u_mei, im:u_ravi"


def _grandfathered_page(aliases: str = ""):
    """The real library's shape: two co-speaking identities on one page, already committed."""
    fm = {
        "doc_id": "d-mei",
        "type": "person",
        "slug": "mei-lin",
        "identities": GRANDFATHERED_IDS,
    }
    if aliases:
        fm["aliases"] = aliases
    return CanonicalDocument(
        doc_id=DocumentId("d-mei"),
        path=MEI_PATH,
        frontmatter=fm,
        body="# Mei LIN\n\n- 排期当天定完。[cite: im-02 ¶1] <!-- c:0b01 -->",
    )


def _cospeak_round():
    return _people_round(
        PeopleComponent(FAMILY),
        [_grandfathered_page()],
        [_im_source(COSPEAK_CORPUS, COSPEAK_USERS, archive="grp-1")],
    )


def test_a_page_is_judged_when_its_body_changed_its_frontmatter_changed_or_it_is_new():
    # (a) body only — one claim appended, no field edited. THE common write, and the one a
    #     frontmatter-only predicate waved through for the whole life of the wrong page.
    draft = _cospeak_round()
    draft.documents()[MEI_PATH].body += "\n- 物料她跟到底。[cite: grp-1 ¶2] <!-- c:0b02 -->"
    assert _people_violations(draft) == [("people.identity_cospeakers", MEI_PATH)]

    # (b) frontmatter only — an alias recorded, no prose written
    draft = _cospeak_round()
    draft.documents()[MEI_PATH].frontmatter["aliases"] = "小林"
    assert _people_violations(draft) == [("people.identity_cospeakers", MEI_PATH)]

    # (c) created this round
    draft = _people_round(
        PeopleComponent(FAMILY), [], [_im_source(COSPEAK_CORPUS, COSPEAK_USERS, archive="grp-1")]
    )
    draft.create_document(
        MEI_PATH,
        {"type": "person", "slug": "mei-lin", "identities": GRANDFATHERED_IDS},
        "# Mei LIN\n\n- 排期当天定完。[cite: grp-1 ¶1]",
    )
    assert _people_violations(draft) == [("people.identity_cospeakers", MEI_PATH)]

    # (d) untouched — the grandfathering survives, byte for byte on both halves. A round
    #     that writes somewhere else entirely still commits, which is what keeps one old
    #     wrong page from making every later compile in that library unpassable.
    draft = _cospeak_round()
    draft.create_document(
        "memory/topics/print.md",
        {"type": "topic", "slug": "print"},
        "# 印务\n\n- 新事实。[cite: grp-1 ¶1]",
    )
    assert _people_violations(draft) == []


async def test_the_round_that_appends_to_a_grandfathered_page_repairs_it_and_commits():
    """The no-deadlock path, end to end through the runner. A wrong early write must never
    block every later compile: the round that touches the page is refused, the SAME round
    drops the rival identity with one `set_fields`, and the compile commits."""
    from pneuma_knowledge_core.compile.runner import run_compile
    from pneuma_knowledge_core.skill import load_skill_base

    component = PeopleComponent(FAMILY, content=_LibraryStore([_cospeak_l0_source()]))
    register_component(component)
    store = _FakeCanonicalStore([_grandfathered_page()])
    model = _ScriptedChatModel(
        turns=[
            [
                _tc("read_document", path=MEI_PATH),
                _tc("append_block", path=MEI_PATH, heading="工作方式", text="物料她跟到底。[cite: im-02 ¶2]"),
                _tc("finish_compile"),
            ],
            [
                _tc("set_fields", path=MEI_PATH, fields={"identities": "im:u_mei"}),
                _tc("finish_compile"),
            ],
        ]
    )

    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_cospeak_l0_source()],
        skill=load_skill_base("v1"),
    )
    assert result.status == "committed"
    assert result.rounds == 2
    # the gate's refusal — not a write-face one: nothing this round wrote was a field
    assert any(COSPEAK_REFUSAL in text for text in model.heard)
    assert "identities: im:u_mei\n" in store.commits[-1][MEI_PATH]
    assert "物料她跟到底" in store.commits[-1][MEI_PATH]


# --- an ephemeral `sNN` handle never reaches a cross-job structure --------------------------
#
# The runner shows the compile model per-job citation handles (`s01`, `s02`) instead of real
# source ids, and hands components the ALIASED sources so a component tool names a source the
# way the task text does. A component that keyed a LIBRARY-wide fact on those handles would
# have the next job's `s01` overwrite this one's evidence — and a correction that should have
# been refused would pass. The library half is read from L0, under real ids, on every job.


def _other_l0_source(sid: str = "im-03", user: UserId = USER):
    """A second, unrelated two-speaker conversation — the one a later job aliases as `s01`,
    and whose record therefore lands on exactly the key job A's group chat used."""
    from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, StructureMap

    raw = RawSource(
        source_id=SourceId(sid),
        user_id=user,
        kind="im",
        title="供应商群",
        mime="text/plain",
        checksum=sid,
        created_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
        meta={
            "owner_user_ids": ["u_owner"],
            "users": [
                {"user_id": "u_owner", "display_name": "Ke ZHOU", "email": None, "is_bot": False},
                {"user_id": "u_kai", "display_name": "Kai SUN", "email": None, "is_bot": False},
                {"user_id": "u_yan", "display_name": "Yan HU", "email": None, "is_bot": False},
            ],
            "messages": [
                {"message_id": "m0", "sender_id": "u_kai"},
                {"message_id": "m1", "sender_id": "u_yan"},
            ],
            "occurred_on": "2026-06-20",
        },
    )
    return NormalizedSource(
        raw=raw,
        blocks=[
            NormalizedBlock(index=0, text="纸张这批下周到。"),
            NormalizedBlock(index=1, text="仓位我安排。"),
        ],
        structure=StructureMap(),
    )


async def test_a_later_jobs_handle_never_overwrites_the_librarys_co_speaking_evidence():
    """Three jobs in one process, each aliasing its first source as `s01`. The group chat is
    in job A's sources and in NOBODY else's — so only the library mirror can still refuse job
    C, and it must, because the conversation did not stop having happened."""
    from pneuma_knowledge_core.compile.runner import run_compile
    from pneuma_knowledge_core.skill import load_skill_base

    library = _LibraryStore([_other_l0_source()])
    component = PeopleComponent(FAMILY, content=library)
    register_component(component)
    store = _FakeCanonicalStore()

    async def job(sources, turns):
        return await run_compile(
            user_id=USER,
            model=_ScriptedChatModel(turns=turns),
            store=store,
            sources=sources,
            skill=load_skill_base("v1"),
        )

    # An ordinary earlier compile in this long-lived worker, before the group chat existed —
    # a mirror read once per process would never look at L0 again after this one.
    assert (await job([_other_l0_source()], [])).status == "noop"
    # …and then the group chat is imported: L0 is written before its compile is enqueued.
    library._sources.append(_cospeak_l0_source())

    # A — the group chat is this job's `s01`
    assert (await job([_cospeak_l0_source()], [])).status == "noop"
    # B — a different conversation takes the same handle
    assert (await job([_other_l0_source()], [])).status == "noop"
    # C — a correction that binds both speakers, with the group chat nowhere in its sources
    result = await job(
        [_other_l0_source()],
        [
            [
                _tc(
                    "create_document",
                    path=MEI_PATH,
                    frontmatter={
                        "type": "person",
                        "slug": "mei-lin",
                        "identities": GRANDFATHERED_IDS,
                    },
                    body="# Mei LIN\n\n- 纸张这批下周到。[cite: im-03 ¶0]",
                ),
                _tc("finish_compile"),
            ],
            [_tc("finish_compile")],
        ],
    )
    assert result.status == "aborted"
    assert [v.kind for v in result.violations] == ["people.identity_cospeakers"]
    assert store.commits == []


# --- warm-up is all-or-nothing, and an unloaded mirror refuses rather than passing ----------


class _FlakyStore(_LibraryStore):
    """L0 that fails the first `list` and answers every one after it."""

    def __init__(self, sources=(), *, failures: int = 1):
        super().__init__(sources)
        self.failures = failures
        self.lists = 0

    async def list(self, user_id):
        self.lists += 1
        if self.lists <= self.failures:
            raise RuntimeError("L0 unreachable")
        return await super().list(user_id)


async def test_a_failed_warm_up_leaves_nothing_behind_and_the_next_prepare_retries():
    """Marking a user warmed BEFORE the reads turned one transient error into a gate that
    stayed open for the process's life: every later prepare skipped the load, and the hard
    refusals were judged against an empty library."""
    from pneuma_knowledge_core.components import prepare_components

    store = _FlakyStore([_cospeak_l0_source()])
    component = PeopleComponent(FAMILY, content=store)
    register_component(component)

    # the fan-out is fail-soft — a component never fails the job it prepares for
    await prepare_components(str(USER))
    assert store.lists == 1
    assert not component.is_ready(str(USER))

    await prepare_components(str(USER))
    assert store.lists == 2
    assert component.is_ready(str(USER))
    assert component._cospeak[str(USER)]["im-02"].speakers == frozenset(
        {"im:u_mei", "im:u_ravi"}
    )


async def test_an_unloaded_mirror_refuses_the_round_instead_of_judging_it_blind():
    """The library-wide facts are read from that mirror. An empty one is not a weaker check,
    it is a different and always-true one — so the round is refused, and the next reads
    again. Fail-soft belongs to the projection channel, never to a canonical gate."""
    from pneuma_knowledge_core.components import prepare_components

    component = PeopleComponent(FAMILY, content=_FlakyStore([_cospeak_l0_source()]))
    register_component(component)
    await prepare_components(str(USER))  # fails inside, logged, continues

    draft = PatchDraft.from_canonical([_grandfathered_page()], TEMPLATES)
    draft.mark_read(MEI_PATH)
    # the round WRITES the page that declares the identities — which is exactly the round
    # whose rules are measured against the mirror that failed to load
    draft.append_block(MEI_PATH, "排期", "- 下周一定稿。[cite: im-02 ¶2]")
    violations = [v for v in run_gate(draft, []) if v.kind.startswith("people.")]
    assert [(v.kind, v.path) for v in violations] == [("people.not_ready", FAMILY)]
    assert "source boundary" in violations[0].detail
    assert "refused rather than judged blind" in violations[0].detail

    # and the write face says it first, rather than accepting what it cannot judge
    with pytest.raises(AnchorToolError) as err:
        draft.set_fields(MEI_PATH, {"identities": "im:u_mei, im:u_ravi"})
    assert "could not load this library's source boundary" in str(err.value)


# --- the source boundary is refreshed INCREMENTALLY, at the database boundary ---------------


async def test_a_later_job_asks_the_store_only_for_the_sources_imported_since_the_last_one():
    """`prepare` runs per job, and the boundary answer for a source never changes. Reading
    the whole library every time made per-job latency and memory O(all sources) — every
    envelope crossing the wire to be discarded by an in-process de-duplication. The cursor is
    `(created_at, source_id)`: sources imported in one batch share a wall clock, and a
    timestamp-only cursor would drop all but one of them for good."""
    library = _LibraryStore([_other_l0_source()])
    component = PeopleComponent(FAMILY, content=library)

    await component.prepare(str(USER))
    assert library.since_calls == [None]  # first job: the library, once
    assert set(component._mirrored[str(USER)]) == {"im-03"}

    # nothing new: the second job still asks, and asks from where the first one stopped
    await component.prepare(str(USER))
    watermark = library.since_calls[-1]
    assert watermark == (datetime(2026, 6, 20, tzinfo=timezone.utc), "im-03")

    # …and when a source IS imported, that job receives exactly it
    library._sources.append(_cospeak_l0_source())
    assert await library.list_since(USER, after=watermark) == [_cospeak_l0_source().raw]
    await component.prepare(str(USER))
    assert library.since_calls[-1] == watermark
    assert set(component._mirrored[str(USER)]) == {"im-03", "im-02"}
    assert component._cospeak[str(USER)]["im-02"].speakers == frozenset(
        {"im:u_mei", "im:u_ravi"}
    )
    assert library.since_calls[-1] != library.since_calls[0]


async def test_a_failed_boundary_read_drops_the_cursor_with_the_mirror_it_describes():
    """A watermark that outlived its mirror would resume from the end of a library this
    process no longer holds — every earlier source lost for the life of the worker."""
    store = _FlakyStore([_other_l0_source()], failures=0)
    component = PeopleComponent(FAMILY, content=store)
    await component.prepare(str(USER))
    assert str(USER) in component._watermark

    store.failures, store.lists = 1, 0
    await _prepare_softly(component)  # fails inside, logged, continues
    assert str(USER) not in component._watermark
    assert not component.boundary_ready(str(USER))

    # …so the retry reads the library from the beginning, not from a cursor into it
    await component.prepare(str(USER))
    assert store.since_calls[-1] is None
    assert set(component._mirrored[str(USER)]) == {"im-03"}


# --- readiness is per RULE: two mirrors, two refusals, neither speaking for the other -------


class _TermsDownStore(_LibraryStore):
    """L0 answers; the DERIVED address-term table does not. The shape of a projection outage:
    the source boundary is perfectly healthy and one derived read is failing."""

    def __init__(self, sources=(), rows=()):
        super().__init__(sources, rows)
        self.term_reads = 0

    async def people_terms(self, user_id, terms=None):
        self.term_reads += 1
        raise RuntimeError("component_people_terms unreadable")


async def _prepare_softly(component, user=USER):
    """`prepare` as the framework calls it — fail-soft, exactly like the runner's fan-out."""
    from pneuma_knowledge_core.components import prepare_components

    register_component(component)
    await prepare_components(str(user))


async def test_a_terms_outage_leaves_the_healthy_source_boundary_standing():
    """The reviewer's reproduction: a healthy, empty L0, zero sources, zero documents, and
    only the derived term table failing produced `people.not_ready` — a persistent projection
    outage blocking topic-only compile, evolve and adopt work that needs no term at all."""
    store = _TermsDownStore()
    component = PeopleComponent(FAMILY, content=store)
    await _prepare_softly(component)

    # one read failed and took NOTHING else with it
    assert component.boundary_ready(str(USER))
    assert not component.terms_ready(str(USER))
    assert not component.is_ready(str(USER))

    draft = PatchDraft.from_canonical([], TEMPLATES)
    assert component.gate_checks(draft.documents(), draft.base_documents()) == []
    assert [v for v in run_gate(draft, []) if v.kind.startswith("people.")] == []


async def test_a_terms_outage_does_not_refuse_a_round_that_asks_the_terms_nothing():
    """A topic-only round: the sources carry no identity, so no alias decision applies, so
    the mirror that would decide one is not consulted and not demanded."""
    from pneuma_knowledge_core.domain.source import NormalizedSource, StructureMap

    component = PeopleComponent(FAMILY, content=_TermsDownStore())
    await _prepare_softly(component)
    topic = CanonicalDocument(
        doc_id=DocumentId("d-paper"),
        path="memory/topics/paper-stock.md",
        frontmatter={"doc_id": "d-paper", "type": "topic", "slug": "paper-stock"},
        body="# 纸张\n\n- 这批下周到。[cite: doc-1 ¶0] <!-- c:0d01 -->",
    )
    draft = PatchDraft.from_canonical([topic], TEMPLATES)
    draft.mark_read("memory/topics/paper-stock.md")
    draft.append_block("memory/topics/paper-stock.md", "供应", "- 供应商已确认。[cite: doc-1 ¶1]")
    component.compile_tools(
        draft,
        sources=[
            NormalizedSource(
                raw=_raw("doc-1", "document", {}, "2026-01-01"),
                blocks=[],
                structure=StructureMap(),
            )
        ],
    )
    assert component.gate_checks(draft.documents(), draft.base_documents()) == []


async def test_a_terms_outage_refuses_the_round_that_would_have_to_decide_a_term():
    """…and the moment the round IS about people this library reports terms for, the refusal
    comes back — naming the projection that failed, not the boundary that did not."""
    component = PeopleComponent(FAMILY, content=_TermsDownStore(rows=[MEI_TERM]))
    await _prepare_softly(component)
    draft = PatchDraft.from_canonical([_mei_page()], TEMPLATES)
    component.compile_tools(draft, sources=[_im_source(DECIDE_CORPUS, DECIDE_USERS)])

    [violation] = component.gate_checks(draft.documents(), draft.base_documents())
    assert (violation.kind, violation.path) == ("people.not_ready", FAMILY)
    assert "address-term projection" in violation.detail
    assert "source boundary" not in violation.detail

    # the boundary rules still hold in that same round — they read the half that loaded
    draft.mark_read(MEI_PATH)
    draft.set_fields(MEI_PATH, {"identities": "im:u_mei"})


async def test_a_boundary_outage_refuses_the_round_that_writes_a_person_page():
    """The mirror image, and the reason the two are separate: a failing L0 read is refused
    for the pages whose identity and alias rules are measured against it."""
    component = PeopleComponent(FAMILY, content=_FlakyStore([_cospeak_l0_source()], failures=99))
    await _prepare_softly(component)
    assert not component.boundary_ready(str(USER)) and component.terms_ready(str(USER))

    # a round that touches no person page and carries no identity is not this rule's business
    draft = PatchDraft.from_canonical([_grandfathered_page()], TEMPLATES)
    assert component.gate_checks(draft.documents(), draft.base_documents()) == []

    # …and the round that writes the page is
    draft.mark_read(MEI_PATH)
    draft.append_block(MEI_PATH, "排期", "- 下周一定稿。[cite: im-02 ¶2]")
    [violation] = component.gate_checks(draft.documents(), draft.base_documents())
    assert (violation.kind, violation.path) == ("people.not_ready", FAMILY)
    assert "source boundary" in violation.detail


# --- an IM sender who is not a declared member ----------------------------------------------


def test_a_sender_outside_the_member_list_still_reaches_the_source_boundary():
    """`member_ids` and `messages[].sender_id` are independently required to be users of the
    archive and neither is a subset of the other — a guest posting into a channel they are
    not a member of is an ordinary, valid provider snapshot. Normalizing the members alone
    dropped those senders' user records, and nothing downstream could resolve who spoke."""
    from pneuma_knowledge_service.components.people import source_speakers

    payload = {
        "schema": "pneuma.source.im/v1",
        "provider": "mock",
        "archive_id": "arc-guest",
        "owner_user_ids": ["u_owner"],
        "users": [
            {"user_id": "u_owner", "display_name": "Ke ZHOU"},
            {"user_id": "u1", "display_name": "Mei LIN"},
            {"user_id": "u2", "display_name": "Ravi SETH"},
        ],
        "conversations": [
            {
                "conversation_id": "c-guest",
                "conversation_type": "channel",
                "title": "排期频道",
                "member_ids": ["u_owner"],
                "messages": [
                    {
                        "message_id": "m1",
                        "sender_id": "u1",
                        "sent_at": _at(9, 0),
                        "text": "这版排期我来定。",
                    },
                    {
                        "message_id": "m2",
                        "sender_id": "u2",
                        "sent_at": _at(9, 5),
                        "text": "物料清单我这边跟。",
                    },
                ],
            }
        ],
    }
    [source] = normalize_source_contract(
        ImSource.model_validate(payload),
        USER,
        imported_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
    )
    # members in their declared order, then senders in first-seen order
    assert [u["user_id"] for u in source.raw.meta["users"]] == ["u_owner", "u1", "u2"]
    record = source_speakers(source.raw)
    assert record is not None
    assert record.speakers == frozenset({"im:u1", "im:u2"})


# --- one compile per process at a time ------------------------------------------------------
#
# `prepare` is a per-process announcement of whose job is running, so two compiles
# interleaving in one process would have the second redefine the first's word for `self` —
# and the first's gate would judge a page against another user's library. I1 says there is no
# cross-user read path, not that the shipped scheduler happens not to take one.


class _BlockingChatModel(BaseChatModel):
    """Stops inside its first call until the test releases it, and ends the turn after."""

    entered: object = None
    release: object = None
    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "blocking-fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        usage = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="done", usage_metadata=usage))]
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.entered is not None and not self.entered.is_set():
            self.entered.set()
            await self.release.wait()
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _AnyUserStore(_LibraryStore):
    """The same L0 fixture, without the single-user assertion — this test has two."""

    async def list(self, user_id):
        return [getattr(s, "raw", s) for s in self._sources]


async def test_a_second_compile_waits_for_the_first_rather_than_redefining_its_user():
    import asyncio

    from pneuma_knowledge_core.compile.runner import run_compile
    from pneuma_knowledge_core.skill import load_skill_base

    user_a, user_b = UserId("u-a"), UserId("u-b")
    component = PeopleComponent(FAMILY, content=_AnyUserStore())
    register_component(component)
    skill = load_skill_base("v1")

    entered, release = asyncio.Event(), asyncio.Event()
    first = _BlockingChatModel(entered=entered, release=release)

    task_a = asyncio.create_task(
        run_compile(
            user_id=user_a,
            model=first,
            store=_FakeCanonicalStore(),
            sources=[_cospeak_l0_source("im-a", user_a)],
            skill=skill,
        )
    )
    await entered.wait()
    assert component._job_user == "u-a"

    task_b = asyncio.create_task(
        run_compile(
            user_id=user_b,
            model=_BlockingChatModel(),
            store=_FakeCanonicalStore(),
            sources=[_cospeak_l0_source("im-b", user_b)],
            skill=skill,
        )
    )
    await asyncio.sleep(0.05)
    # B is at the window, not through it: A's compile still owns this process's answer to
    # "whose library is being judged".
    assert not task_b.done()
    assert component._job_user == "u-a"

    release.set()
    assert (await task_a).status == "noop"
    assert (await task_b).status == "noop"
    assert component._job_user == "u-b"


async def test_a_component_face_refuses_a_user_the_job_was_not_prepared_for():
    """The guard's second half, for a caller that ignores the window: a face handed a user of
    its own checks it is the one `prepare` announced, and raises rather than answering out of
    another user's mirror."""
    component = PeopleComponent(FAMILY, content=_AnyUserStore())
    await component.prepare("u-a")
    draft = PatchDraft.from_canonical([], TEMPLATES)
    stray = _cospeak_l0_source("im-b", UserId("u-b"))
    with pytest.raises(RuntimeError, match="One compile per process"):
        component.compile_tools(draft, sources=[stray])
    with pytest.raises(RuntimeError, match="One compile per process"):
        component.source_preamble(stray)


# --- the fourth threshold: WHERE a term is used, not merely how often ----------------------
# Concentration answers "does this term keep landing on one person". Measured over 88 days of
# a real IM corpus that was not enough: of sixteen terms that cleared support, sources and
# concentration, about half were not a way of addressing anybody — a vendor's name, a
# company's name, a topic word, a phrase that opens messages. Each of them concentrates
# perfectly, because the same person habitually answers whatever is said to the group. The
# forced decision then handed the model noise to rule on, and it ruled badly in both
# directions: two genuine nicknames declined, a vendor name recorded as an alias.
#
# What the genuine terms have and the impostors lack is a POSITION. A way of addressing
# somebody sits at the vocative position — message-initial, or after an `@` — and almost
# nowhere else; a topic word is all over the middle of the same sources' sentences. Both
# support signals are only ever reached from that position, so `support` IS the vocative
# count, `non_vocative` is the same term mid-sentence, and their ratio is the fourth
# threshold. The fixtures below are one synthetic conversation set carrying all three shapes.

#: A synthetic API vendor the team talks ABOUT all day — never a person.
VENDOR = "Zetlin"

#: …and a synthetic opener of the shape a real corpus recorded as an alias: a short phrase
#: that starts messages somebody answers, and turns up mid-sentence just as readily.
OPENER = "问一下"

MIXED_USERS = [("u_owner", "Ke ZHOU"), ("u_hw", "Hao WEN")]

MIXED = [
    [
        ("u_owner", _at(9, 0), "阿吉，这版排期你确认下。"),
        ("u_hw", _at(9, 1), "好，我看看。"),
        ("u_owner", _at(9, 10), "阿吉，文案也顺一下。"),
        ("u_hw", _at(9, 11), "收到。"),
        ("u_owner", _at(10, 0), f"{VENDOR}，这个接口你跟一下。"),
        ("u_hw", _at(10, 1), "我来跟。"),
        ("u_owner", _at(10, 20), f"{VENDOR}，限流口径也确认下。"),
        ("u_hw", _at(10, 21), "在确认了。"),
        ("u_owner", _at(11, 0), f"我们把 {VENDOR} 的返回值记一下，{VENDOR} 那边一直没说清楚。"),
        ("u_hw", _at(11, 1), "记下了。"),
        ("u_owner", _at(12, 0), f"{OPENER}，这个月的预算谁批？"),
        ("u_hw", _at(12, 1), "我去问。"),
        ("u_owner", _at(12, 30), f"还想{OPENER}预算的事，上次{OPENER}也没人回。"),
        ("u_hw", _at(12, 31), "我催一下。"),
    ],
    [
        ("u_owner", _at(9, 0), "阿吉，这条线你跟一下。"),
        ("u_hw", _at(9, 1), "好的。"),
        ("u_owner", _at(10, 0), f"{VENDOR}，账号权限你申请下。"),
        ("u_hw", _at(10, 1), "申请了。"),
        ("u_owner", _at(11, 0), f"我们把 {VENDOR} 的返回值记一下，{VENDOR} 那边一直没说清楚。"),
        ("u_hw", _at(11, 1), "记下了。"),
        ("u_owner", _at(12, 0), f"{OPENER}，这周的例会改时间了吗？"),
        ("u_hw", _at(12, 1), "没改。"),
        ("u_owner", _at(12, 30), f"上次{OPENER}也没人回。"),
        ("u_hw", _at(12, 31), "我看看。"),
    ],
    [
        ("u_owner", _at(9, 0), "阿吉，物料明天要。"),
        ("u_hw", _at(9, 1), "知道了。"),
        ("u_owner", _at(10, 0), f"{VENDOR}，回调地址换一下。"),
        ("u_hw", _at(10, 1), "换好了。"),
        ("u_owner", _at(11, 0), f"我们把 {VENDOR} 的返回值记一下，{VENDOR} 那边一直没说清楚。"),
        ("u_hw", _at(11, 1), "记下了。"),
        ("u_owner", _at(12, 0), f"{OPENER}，物料谁在跟？"),
        ("u_hw", _at(12, 1), "我在跟。"),
        ("u_owner", _at(12, 30), f"上次{OPENER}也没人回。"),
        ("u_hw", _at(12, 31), "我催一下。"),
    ],
]


def _mixed_sources():
    return [
        _im_source(messages, MIXED_USERS, archive=f"arc-mix-{i}")
        for i, messages in enumerate(MIXED)
    ]


def test_the_mid_sentence_count_is_taken_off_what_the_vocative_head_leaves_behind():
    """Per source, before any accumulation: the same turn structure produces the vocative
    support and the mid-sentence count, so the two can never describe different text."""
    by_term = {
        term_key(c.term): c for c in address_evidence(_mixed_sources()[0])
    }
    # the nickname: two vocatives, and it appears nowhere else in the conversation
    assert (by_term["阿吉"].answered, by_term["阿吉"].non_vocative) == (2, 0)
    # the vendor: two vocatives that Hao answers — and one sentence that talks about it twice
    assert (by_term[term_key(VENDOR)].answered, by_term[term_key(VENDOR)].non_vocative) == (2, 2)
    # the opener: one vocative, two mid-sentence
    assert (by_term[OPENER].answered, by_term[OPENER].non_vocative) == (1, 2)
    # the head itself is never counted as the middle: strip the vocative turn's term and the
    # count is the same, because that occurrence was already outside the counted region
    assert occurrences(term_key(VENDOR), f"我们把 {VENDOR} 的返回值记一下，{VENDOR} 那边") == 2
    assert occurrences("阿吉", "，这版排期你确认下。") == 0


async def test_a_term_that_is_mostly_mid_sentence_is_not_an_address_term():
    """The three shapes side by side. All three clear support, sources and concentration —
    each of them lands on the same single target, which is exactly why concentration cannot
    tell them apart. Only the one that stays at the vocative position is reported."""
    sources = _mixed_sources()
    component = PeopleComponent(FAMILY, content=_Content(sources))
    for source in sources:
        await component.on_source_indexed(str(USER), source)
    rows = {(r.term, r.target): r for r in await component.library_terms(USER)}

    counts = {
        term: (rows[(term, "im:u_hw")].support, rows[(term, "im:u_hw")].non_vocative)
        for term in ("阿吉", term_key(VENDOR), OPENER)
    }
    assert counts == {"阿吉": (4, 0), "zetlin": (4, 6), "问一下": (3, 4)}

    # the first three thresholds pass for every one of them — a single target holds all of
    # the term's support, so concentration is 1.0 by construction
    for term, (support, _) in counts.items():
        row = rows[(term, "im:u_hw")]
        assert row.support >= REPORT_MIN_SUPPORT
        assert row.sources >= REPORT_MIN_SOURCES
        assert row.support >= REPORT_MIN_CONCENTRATION * support

    # …and the fourth separates them: 4/4 against 4/10 and 3/7
    assert reported_terms(rows.values()).keys() == {"阿吉"}
    assert [r.target for r in reported_targets(rows.values(), "阿吉")] == ["im:u_hw"]
    assert reported_targets(rows.values(), VENDOR) == []
    assert reported_targets(rows.values(), OPENER) == []
    # the bar itself, stated: the vendor's share is below it, the nickname's is at the top
    assert REPORT_MIN_VOCATIVE_SHARE == 0.5
    assert 4 / (4 + 6) < REPORT_MIN_VOCATIVE_SHARE <= 4 / (4 + 0)


def test_an_at_mention_followed_by_text_is_the_vocative_position():
    """`@X 阿吉，…` is how a nickname reaches the corpus when no identity carries it, so the
    `@` head counts as address; the same term inside a sentence counts as the middle."""
    source = _im_source(
        [
            ("u_owner", _at(9, 0), "@Hao WEN 阿吉，这条你跟一下。"),
            ("u_hw", _at(9, 1), "好，我跟。"),
            ("u_owner", _at(9, 10), "@阿吉 排期发一下。"),
            ("u_hw", _at(9, 11), "发了。"),
            ("u_owner", _at(10, 0), "我跟 阿吉 说过这件事了。"),
            ("u_hw", _at(10, 1), "行。"),
        ],
        USERS,
    )
    [candidate] = [c for c in address_evidence(source) if term_key(c.term) == "阿吉"]
    # two vocatives — one behind a resolved `@`, one that IS the `@` token — and one mention
    assert (candidate.answered, candidate.co_mention, candidate.non_vocative) == (2, 1, 1)
    # so an `@`-led corpus still clears the share: 3 of 4
    assert candidate.support >= REPORT_MIN_VOCATIVE_SHARE * (
        candidate.support + candidate.non_vocative
    )


def test_a_term_the_conversation_title_supplies_is_never_counted_as_address():
    """The source's own structural vocabulary. A group named after a product makes that word
    open messages all day and somebody answers each of them — which is a fact about the
    group's name, not about anyone's name. Equality against a token, never containment."""
    assert structural_tokens(f"{VENDOR} 对接群") == {term_key(VENDOR), "对接群"}
    messages = [
        ("u_owner", _at(9, 0), f"{VENDOR}，这个接口你跟一下。"),
        ("u_hw", _at(9, 1), "我来跟。"),
        ("u_owner", _at(9, 10), f"{VENDOR}，限流口径也确认下。"),
        ("u_hw", _at(9, 11), "在确认了。"),
        ("u_owner", _at(10, 0), "阿吉，文案顺一下。"),
        ("u_hw", _at(10, 1), "收到。"),
    ]
    titled = _im_source(messages, MIXED_USERS, title=f"{VENDOR} 对接群")
    assert [term_key(c.term) for c in address_evidence(titled)] == ["阿吉"]
    # the same turns under a title that does not name it: the term is a candidate again, to
    # be ruled on by the thresholds like any other
    plain = _im_source(messages, MIXED_USERS, title="运营群")
    assert sorted(term_key(c.term) for c in address_evidence(plain)) == ["zetlin", "阿吉"]
    # containment is not equality: a nickname sitting inside a longer title run survives
    assert [term_key(c.term) for c in address_evidence(
        _im_source(messages, MIXED_USERS, title="阿吉项目组")
    )] == ["zetlin", "阿吉"]


def test_a_display_name_token_stays_a_candidate_and_is_not_blocked_twice():
    """The other half of the structural vocabulary, verified rather than duplicated: a term
    equal to a WHOLE display name the sources record is already dropped where the term is
    read (it identifies rather than names), and a piece of a fuller display name deliberately
    is not — addressing somebody by their given name alone is address, and `aliases` is
    exactly where a surname or a given name on its own belongs."""
    source = _im_source(
        [
            ("u_owner", _at(9, 0), "Hao WEN，这条你看下。"),
            ("u_hw", _at(9, 1), "看了。"),
            ("u_owner", _at(9, 10), "Hao，排期你定。"),
            ("u_hw", _at(9, 11), "定了。"),
        ],
        USERS,
    )
    assert [(c.term, c.target) for c in address_evidence(source)] == [("Hao", "im:u_hw")]


async def test_the_projection_row_carries_the_count_and_a_rebuild_reproduces_it():
    """The new column is derived like every other: written by the index path, double-counted
    by a re-index, and re-derived from L0 byte-identically."""
    sources = _mixed_sources()
    component = PeopleComponent(FAMILY, content=_Content(sources))
    for source in sources:
        await component.on_source_indexed(str(USER), source)

    def snapshot():
        return sorted(
            (tuple(sorted(row.row().items())) for row in component._terms[str(USER)].values())
        )

    first = snapshot()
    assert dict(first[0])["non_vocative"] >= 0
    assert {dict(r)["non_vocative"] for r in first} == {0, 6, 4}

    await component.on_source_indexed(str(USER), sources[0])  # a re-index double-counts…
    doubled = {
        r.term: r.non_vocative for r in component._terms[str(USER)].values()
    }
    assert doubled[term_key(VENDOR)] == 8
    # …and, until the rebuild, the vendor's share is wrong in the SAME direction as its
    # support, which is what makes the double count a count and not a verdict
    assert reported_terms(component._terms[str(USER)].values()).keys() == {"阿吉"}

    await component.rebuild(str(USER))
    assert snapshot() == first


async def test_the_tightened_report_set_reaches_every_face_at_once():
    """One rule, one place: the preamble, the forced decision and the derived lookup all read
    `is_reported`, so a term that fails the share disappears from all three together."""
    good = dict(MEI_TERM, term="阿吉", answered=9, co_mention=4, sources=7, non_vocative=2)
    noise = dict(MEI_TERM, term=term_key(VENDOR), answered=9, co_mention=4, sources=7, non_vocative=20)
    component = PeopleComponent(FAMILY, content=_LibraryStore(rows=[good, noise]))
    draft = await _round(component, [_mei_page()])

    # the gate demands a decision on the nickname and says nothing about the vendor word
    violations = component.gate_checks(draft.documents(), draft.base_documents())
    assert [(v.kind, '"阿吉"' in v.detail) for v in violations] == [
        ("people.alias_undecided", True)
    ]
    assert VENDOR not in violations[0].detail

    # the source preamble reports the one and not the other…
    reported = [
        line
        for line in component.source_preamble(
            _im_source(DECIDE_CORPUS, DECIDE_USERS)
        ).splitlines()
        if line.startswith("How the library's turns call these people")
    ]
    assert reported and "阿吉" in reported[0] and VENDOR not in reported[0]
    # …and it states the mid-sentence count it judged on, like every other signal
    assert "non_vocative 2" in reported[0]

    # …and `find_person` resolves the nickname to the page it points at, but not the vendor
    tools = {
        t.name: t
        for t in component.compile_tools(
            draft, sources=[_im_source(DECIDE_CORPUS, DECIDE_USERS)]
        )
    }
    assert MEI_PATH in tools["find_person"].func(alias="阿吉")
    assert MEI_PATH not in tools["find_person"].func(alias=VENDOR)


# --------------------------------------------------------- contact-book name matching
# The lookup used to be exact and nothing else, and a real library showed what that costs:
# a page titled `Kexin ZHOU`, bound to `im:Kexin ZHOU`, was unreachable by `可欣` — the form
# every colleague of his would type — so the answering model had to guess out loud. What
# follows is the same problem every address book solves: one normaliser expands both the
# page's names and the question into key sets, and the two meet on the pinyin.


NAME_PATH = "memory/people/kexin-zhou.md"


def _zhou_page():
    """The shape the live library had: every written form of the name is latin — the title,
    the slug and the identity's display name — and no alias records the Chinese one."""
    return CanonicalDocument(
        doc_id=DocumentId("d-wu"),
        path=NAME_PATH,
        frontmatter={
            "doc_id": "d-wu",
            "type": "person",
            "slug": "kexin-zhou",
            "identities": "im:Kexin ZHOU",
        },
        body="# Kexin ZHOU\n\n## 工作方式\n\n- 排期确认前不动手。[cite: arc-1 ¶1-1] <!-- c:0c01 -->",
    )


def _titled(slug: str, title: str, anchor: str, *, identities: str = ""):
    fm = {"doc_id": f"d-{slug}", "type": "person", "slug": slug}
    if identities:
        fm["identities"] = identities
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=f"memory/people/{slug}.md",
        frontmatter=fm,
        body=f"# {title}\n\n## 工作方式\n\n- 排期当天定。[cite: arc-1 ¶1-1] <!-- c:{anchor} -->",
    )


def _with_definition(doc: CanonicalDocument, definition: str) -> CanonicalDocument:
    """The same page with an overview `definition` — the one line that tells two people who
    share a given name apart."""
    draft = PatchDraft.from_canonical([doc], TEMPLATES)
    draft.mark_read(doc.path)
    draft.rewrite_overview(doc.path, Overview(definition=definition))
    written = draft.read(doc.path)
    return CanonicalDocument(
        doc_id=doc.doc_id,
        path=doc.path,
        frontmatter=written.frontmatter,
        body=written.body,
    )


async def _person_path(component, **kwargs):
    path = _path(component)
    return await path.run(USER, path.args_schema(**kwargs))


async def test_a_given_name_in_the_other_script_reaches_a_latin_titled_page():
    """The reported miss, as a test: `可欣` and `Kexin ZHOU` share no character, and meet on
    the pinyin the given name produces."""
    component = PeopleComponent(FAMILY, canonical=_Canonical([_zhou_page()]))
    result = await _person_path(component, alias="可欣")
    assert [(str(c.anchor), c.labels) for c in result.claims] == [
        ("0c01", ("current", "via:name-match tier1"))
    ]
    # and the deep lane's profile resolves it through the same matcher, saying so
    tools = {t.name: t for t in component.recall_tools(USER)}
    text = await tools["person_profile"].coroutine(alias="可欣")
    assert text.splitlines()[0].startswith(f"# Kexin ZHOU — `{NAME_PATH}`")
    assert "matched `可欣` against this page's own names" in text and "tier 1" in text


@pytest.mark.parametrize(
    "query", ["kexin zhou", "zhou kexin", "KexinZHOU", "kz", "周可欣", "周", "kexin"]
)
async def test_one_person_is_reached_by_every_convention_the_name_can_be_written_in(query):
    """Order, concatenation, initials, the other script and the surname alone — one page,
    seven ways of writing at it."""
    component = PeopleComponent(FAMILY, canonical=_Canonical([_zhou_page()]))
    result = await _person_path(component, alias=query)
    assert [str(c.anchor) for c in result.claims] == ["0c01"]


async def test_the_pinyin_carries_a_cjk_alias_to_a_latin_title_and_back():
    latin = PeopleComponent(FAMILY, canonical=_Canonical([_titled("mei-lin", "Mei LIN", "0e01")]))
    assert [str(c.anchor) for c in (await _person_path(latin, alias="林美")).claims] == ["0e01"]
    cjk = PeopleComponent(FAMILY, canonical=_Canonical([_titled("lin-mei", "林美", "0e02")]))
    assert [str(c.anchor) for c in (await _person_path(cjk, alias="Mei LIN")).claims] == ["0e02"]
    assert [str(c.anchor) for c in (await _person_path(cjk, alias="meilin")).claims] == ["0e02"]


async def test_a_compound_surname_splits_where_the_surname_ends():
    """`欧阳锋` is 欧阳 + 锋. Split naively it is 欧 + 阳锋, and `锋` — the half a question
    actually uses — is never a key at all."""
    assert split_cjk_name("欧阳锋") == ("欧阳", "锋")
    assert split_cjk_name("周可欣") == ("周", "可欣")
    assert "锋" in name_keys("欧阳锋") and "feng" in name_keys("欧阳锋")
    component = PeopleComponent(
        FAMILY, canonical=_Canonical([_titled("ouyang-feng", "Ouyang Feng", "0f01")])
    )
    assert [str(c.anchor) for c in (await _person_path(component, alias="欧阳锋")).claims] == ["0f01"]
    assert [str(c.anchor) for c in (await _person_path(component, alias="锋")).claims] == ["0f01"]


async def test_two_pages_sharing_a_given_name_come_back_as_candidates_with_their_definitions():
    """Ambiguity is RETURNED, not swallowed. Two colleagues are called 可欣, so the question
    has two answers — each stated by its definition line, for the lane holding the question
    to choose between. A query that names one of them outright is a single winner, whole."""
    wu = _with_definition(_zhou_page(), "周可欣负责排期。 c:0c01")
    wang = _with_definition(_titled("kexin-lin", "Kexin LIN", "0d01"), "林可欣负责文案。 c:0d01")
    component = PeopleComponent(FAMILY, canonical=_Canonical([wu, wang]))

    both = await _person_path(component, alias="可欣")
    assert {c.document_path for c in both.claims} == {wu.path, wang.path}
    assert all("via:name-match tier1" in c.labels for c in both.claims)
    # …the definition line and nothing else: three candidates must not flood the lane
    assert all("definition" in c.labels for c in both.claims)
    assert sorted(c.text for c in both.claims) == sorted(
        ["周可欣负责排期。 c:0c01", "林可欣负责文案。 c:0d01"]
    )

    one = await _person_path(component, alias="周可欣")
    assert {c.document_path for c in one.claims} == {wu.path}
    assert len(one.claims) > 1  # the whole page, as an unambiguous lookup always was
    # and the deep profile prints both candidates' overviews, saying why there are two
    tools = {t.name: t for t in component.recall_tools(USER)}
    text = await tools["person_profile"].coroutine(alias="可欣")
    assert "周可欣负责排期。" in text and "林可欣负责文案。" in text
    assert "one of 2 pages whose name matches that form equally well" in text


def test_the_candidate_list_is_capped_and_the_better_match_wins_outright():
    docs = {
        d.path: d
        for d in [
            _zhou_page(),
            _titled("kexin-lin", "Kexin LIN", "0d01"),
            _titled("kexin-li", "Kexin LI", "0d02"),
            _titled("kexin-bai", "Kexin BAI", "0d03"),
        ]
    }
    component = PeopleComponent(FAMILY)
    assert len(component.find_by_name(docs, alias="可欣")) == 4
    assert len(component.name_candidates(docs, alias="可欣")) == NAME_MATCH_CANDIDATES
    # a query that meets one page on more keys is not an ambiguity at all
    assert [m.path for m in component.name_candidates(docs, alias="周可欣")] == [NAME_PATH]


async def test_an_honorific_is_stripped_from_the_question_and_only_as_a_second_attempt():
    assert strip_honorific("可欣姐") == "可欣"
    assert strip_honorific("小周") == "周"
    assert strip_honorific("林老师") == "林"
    assert strip_honorific("可欣") == ""  # nothing to strip
    assert strip_honorific("老板") == ""  # the form of address and no name under it
    component = PeopleComponent(FAMILY, canonical=_Canonical([_zhou_page()]))
    assert [str(c.anchor) for c in (await _person_path(component, alias="可欣姐")).claims] == ["0c01"]
    assert [str(c.anchor) for c in (await _person_path(component, alias="小周")).claims] == ["0c01"]

    # …and the stripped form BEATS a raw form that only resembles: measured on a real
    # library, `可欣姐` reached three unrelated pages by their first syllable while `可欣`
    # reached the person actually called that.
    crowd = PeopleComponent(
        FAMILY,
        canonical=_Canonical([_zhou_page(), _titled("keming-chen", "Keming CHEN", "0h01")]),
    )
    raw = crowd.find_by_name({d.path: d for d in [_zhou_page(), _titled("keming-chen", "Keming CHEN", "0h01")]}, alias="可欣姐")
    assert [(m.path, m.tier) for m in raw] == [("memory/people/keming-chen.md", 2), (NAME_PATH, 2)]
    result = await _person_path(crowd, alias="可欣姐")
    assert {c.document_path for c in result.claims} == {NAME_PATH}
    assert all("via:name-match tier1" in c.labels for c in result.claims)

    # …and never before the raw form: a page that DECLARES 老贾 answers as itself, exactly,
    # rather than being reached as a stripped 贾.
    page = _titled("jia-ning", "贾宁", "0a11")
    page.frontmatter["aliases"] = "老贾"
    declared = PeopleComponent(FAMILY, canonical=_Canonical([page, _zhou_page()]))
    hit = await _person_path(declared, alias="老贾")
    assert [(c.document_path, c.labels) for c in hit.claims] == [
        ("memory/people/jia-ning.md", ("current",))
    ]


def test_a_one_character_cjk_query_matches_a_surname_key_and_never_a_prefix():
    docs = {d.path: d for d in [_zhou_page(), _titled("mei-lin", "Mei LIN", "0e01")]}
    component = PeopleComponent(FAMILY)
    # `周` is exactly the surname key the page's pinyin produces — tier 1, one key
    assert [(m.path, m.tier) for m in component.find_by_name(docs, alias="周")] == [(NAME_PATH, 1)]
    # `可`, one character, does not prefix its way into every 可-something
    assert component.find_by_name(docs, alias="可") == []
    # two characters do reach a longer key as a prefix, and say they are the weaker tier
    assert [(m.path, m.tier) for m in component.find_by_name(docs, alias="kexi")] == [
        (NAME_PATH, 2)
    ]


def test_matching_is_wide_and_the_collision_rules_stay_exact():
    """Two different questions. `is this page reachable by that name` is retrieval and is
    matched in every convention; `is this alias already somebody else's name` is a FACT, and
    a fact that only nearly holds is not a collision."""
    component = PeopleComponent(FAMILY)
    docs = {d.path: d for d in [_zhou_page(), _titled("mei-lin", "Mei LIN", "0e01")]}
    mei = "memory/people/mei-lin.md"
    # the exact name of another page is still refused…
    problems = component.field_problems(docs, mei, aliases=["Kexin ZHOU"])
    assert [kind for kind, _ in problems] == ["people.alias_collision"]
    assert component.field_problems(docs, mei, aliases=["kexin-zhou"]) != []  # its slug too
    # …and a form that merely MATCHES it is not: nothing is proven about who 可欣 is, and a
    # refusal resting on a match would refuse the truth as often as the mistake.
    assert component.field_problems(docs, mei, aliases=["可欣"]) == []
    assert component.field_problems(docs, mei, aliases=["kexinzhou"]) == []


async def test_the_page_keys_are_computed_once_and_refreshed_with_the_mirror():
    component = PeopleComponent(FAMILY)
    page = _zhou_page()
    keys = component.page_name_keys(page)
    assert component.page_name_keys(page) is keys  # cached, not recomputed
    assert {"kexin", "zhou", "kexinzhou", "kz"} <= keys
    # content-addressed: a page whose names changed has different keys, with no invalidation
    renamed = _titled("kexin-zhou", "Ke ZHOU", "0c01")
    assert component.page_name_keys(renamed) != keys
    assert "zhou" in component.page_name_keys(renamed)
    # …and the cache is dropped with the mirrors, at the head of every job
    assert component._name_key_cache
    await component.prepare(str(USER))
    assert component._name_key_cache == {}


def test_every_people_lookup_goes_through_the_one_name_normaliser():
    """Grep-pin. Three faces ask "which person is this name" — the compile tool, the fast
    path and the deep profile — and one matcher answers all three. A second implementation
    anywhere means a question that resolves in one lane and misses in another."""
    import inspect

    from pneuma_knowledge_service.components import people as module

    matcher = inspect.getsource(module.PeopleComponent.find_by_name)
    assert "name_keys(alias)" in matcher and "match_tier(" in matcher
    assert "name_candidates(" in inspect.getsource(module.PeopleComponent.resolve_by_name)
    assert "resolve_by_name(" in inspect.getsource(module.PeopleComponent._resolve_pages)
    for face in (
        module.PeopleComponent.person_claims,  # the fast path's `person`
        module.PeopleComponent.person_profile,  # deep recall
    ):
        assert "_resolve_pages(" in inspect.getsource(face)
    tools = inspect.getsource(module.PeopleComponent.compile_tools)
    assert "def find_person(" in tools and "resolve_by_name(" in tools
    # …and the write-time rules never touch it: collisions are about facts.
    for rule in (
        module.PeopleComponent.field_problems,
        module.PeopleComponent.validate_fields,
        module.PeopleComponent.gate_checks,
    ):
        source = inspect.getsource(rule)
        assert "name_candidates(" not in source and "name_keys(" not in source


# ══════════════════════════════════════════════ the people around a subject
#
# The second entry on the same two seams. `person` answers "who is X" and needs a NAME;
# a conversation that asks 「能不能邀请 lumenlab 的同学来分享一下?」 names no person at
# all — the subject is a project, and the people are what the library already wrote around
# it. That answer needs no model: canonical holds it as ordinary markdown links, and the
# claim carrying the link is the evidence.


def _subject(
    path: str = "projects/lumenlab.md",
    *,
    slug: str = "lumenlab",
    title: str = "Lumen Lab",
    connections: str = "",
    log: str = "",
    aid: str = "0da",
) -> CanonicalDocument:
    body = f"""# {title}

<!-- overview -->

<!-- overview:definition -->
### definition

{title} builds optical benches. [cite: src-01 ¶0-1] <!-- c:{aid}01 -->
{connections}
<!-- /overview -->

## Log

- {title} shipped its second bench. [cite: src-01 ¶8-9] <!-- c:{aid}09 -->
{log}"""
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=path,
        frontmatter={"doc_id": f"d-{slug}", "type": "project", "slug": slug, "title": title},
        body=body,
    )


CONNECTIONS = """
<!-- overview:connections -->
### connections

- [memory/people/ke-zhou.md](../memory/people/ke-zhou.md) — Ke ZHOU runs the bench programme. [cite: src-01 ¶2-3] <!-- c:0da02 -->
"""


def _page(slug: str, title: str, body: str, *, type_: str = "person", folder: str = "memory/people"):
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=f"{folder}/{slug}.md",
        frontmatter={"doc_id": f"d-{slug}", "type": type_, "slug": slug, "title": title},
        body=body,
    )


MEI = _page(
    "mei-lin",
    "Mei LIN",
    """# Mei LIN

<!-- overview -->

<!-- overview:definition -->
### definition

Mei LIN is the optics lead. [cite: src-02 ¶0-1] <!-- c:ae001 -->

<!-- /overview -->

## Log

- Mei LIN joined [Lumen Lab](../../projects/lumenlab.md) in March. [cite: src-02 ¶2-3] <!-- c:ae002 -->
- Mei LIN chairs [Lumen Lab](../../projects/lumenlab.md)'s review board. [cite: src-02 ¶4-5] <!-- c:ae003 -->
""",
)

# Reached ONLY from the subject document's own connections line: nothing on this page names
# Lumen Lab, and the relation is no less written down for it.
KE = _page(
    "ke-zhou",
    "Ke ZHOU",
    """# Ke ZHOU

## Log

- Ke ZHOU coordinates the bench programme. [cite: src-03 ¶0-1] <!-- c:bc001 -->
""",
)

# One link, and canonical has already replaced the claim that carried it.
HANA = _page(
    "hana-oda",
    "Hana ODA",
    """# Hana ODA

## Log

- Hana ODA led [Lumen Lab](../../projects/lumenlab.md)'s calibration. [cite: src-04 ¶0-1] <!-- c:cd001 -->
- Hana ODA now leads the metrology group. [cite: src-04 ¶2-3] <!-- supersedes: c:cd001 --> <!-- c:cd002 -->
""",
)

# A PROJECT page linking the same subject. Not a person, so it is not somebody around it.
APEX = _page(
    "apex-bench",
    "Apex Bench",
    """# Apex Bench

## Log

- Apex Bench reuses [Lumen Lab](../lumenlab.md)'s optics. [cite: src-05 ¶0-1] <!-- c:de001 -->
""",
    type_="project",
    folder="projects",
)

LIBRARY = [_subject(connections=CONNECTIONS), MEI, KE, HANA, APEX]


def _around(component=None, *, subject: str, documents=None, **kwargs):
    component = component or PeopleComponent(FAMILY)
    return component.around_claims(USER, subject=subject, documents=documents or LIBRARY, **kwargs)


def _people_of(claims) -> list[str]:
    """The person pages the face enumerates, in the order it put them."""
    out: list[str] = []
    for claim in claims:
        for label in claim.labels:
            if label.startswith("person:") and label[7:] not in out:
                out.append(label[7:])
    return out


# ── resolving the subject ─────────────────────────────────────────────────────


def test_a_subject_resolves_by_title_slug_filename_or_path_under_one_normalisation():
    component = PeopleComponent(FAMILY)
    docs = {d.path: d for d in LIBRARY}
    # One key on both sides, with separators dropped entirely: `Lumen Lab`, `lumen-lab` and
    # `lumenlab` are one name, so the title answers all three and the slug/filename tiers
    # stand behind it for a document whose heading says something else.
    for query, how in (
        ("projects/lumenlab.md", "path"),
        ("Lumen Lab", "title"),
        ("  lumen   lab ", "title"),
        ("LUMEN-LAB", "title"),
        ("lumenlab", "title"),
    ):
        [match] = component.resolve_subject(docs, subject=query)
        assert (match.path, match.how) == ("projects/lumenlab.md", how), query
    # …and a page whose heading is not its slug is still reachable by the slug.
    coded = _page("bench-7", "The Optics Bench", "# The Optics Bench\n", type_="project", folder="projects")
    [by_slug] = component.resolve_subject({coded.path: coded}, subject="bench-7")
    assert by_slug.how == "slug"


def test_a_subject_nothing_is_named_after_resolves_to_nothing_rather_than_to_the_nearest():
    component = PeopleComponent(FAMILY)
    docs = {d.path: d for d in LIBRARY}
    assert component.resolve_subject(docs, subject="lumen") == []
    assert component.resolve_subject(docs, subject="") == []


def test_a_tie_of_three_or_fewer_comes_back_whole_and_every_row_says_which_one_it_answers():
    """Two documents are named `Lumen Lab`; a lookup that picked one would invent the half
    it dropped. Both come back, and every claim carries its own `subject:` label."""
    twin = _subject("topics/lumenlab.md", slug="lumen-topic", title="Lumen Lab", aid="2b0")
    docs = {d.path: d for d in [*LIBRARY, twin]}
    component = PeopleComponent(FAMILY)
    matches = component.resolve_subject(docs, subject="Lumen Lab")
    assert [m.path for m in matches] == ["projects/lumenlab.md", "topics/lumenlab.md"]


async def test_a_tie_of_three_or_fewer_labels_every_row_with_the_document_it_answers_for():
    twin = _subject("topics/lumenlab.md", slug="lumen-topic", title="Lumen Lab", aid="2b0")
    claims = await _around(subject="Lumen Lab", documents=[*LIBRARY, twin])
    assert claims
    assert all(
        any(label.startswith("subject:") for label in claim.labels) for claim in claims
    )


async def test_a_single_subject_labels_no_row_with_it():
    """The label exists to tell two answers apart. One answer has nothing to tell apart."""
    claims = await _around(subject="Lumen Lab")
    assert not any(
        label.startswith("subject:") for claim in claims for label in claim.labels
    )


async def test_more_than_three_tied_documents_is_an_empty_face_not_a_guess():
    twins = [
        _subject(f"topics/lumen-{n}.md", slug=f"lumen-{n}", title="Lumen Lab", aid=f"1a{n}0")
        for n in range(4)
    ]
    assert await _around(subject="Lumen Lab", documents=[*LIBRARY, *twins]) == []


async def test_the_deep_tool_names_the_tied_documents_instead_of_choosing_between_them():
    twins = [
        _subject(f"topics/lumen-{n}.md", slug=f"lumen-{n}", title="Lumen Lab", aid=f"1a{n}0")
        for n in range(4)
    ]
    text = await PeopleComponent(FAMILY).people_around(
        USER, subject="Lumen Lab", documents=[*LIBRARY, *twins]
    )
    assert "names 5 documents equally well" in text
    assert "`topics/lumen-0.md`" in text and "`projects/lumenlab.md`" in text


# ── the enumeration ───────────────────────────────────────────────────────────


async def test_both_directions_count_and_each_person_carries_the_sentence_that_links_them():
    claims = await _around(subject="lumenlab")
    by_anchor = {str(c.anchor): c for c in claims}
    # Mei LIN's own claims link the subject; the subject's connections line links Ke ZHOU.
    assert "links-to" in by_anchor["ae002"].labels
    assert by_anchor["ae002"].document_path == "memory/people/mei-lin.md"
    assert "linked-from" in by_anchor["0da02"].labels
    assert by_anchor["0da02"].document_path == "projects/lumenlab.md"
    assert "person:memory/people/ke-zhou.md" in by_anchor["0da02"].labels
    # the linking SENTENCE, verbatim, and its citation intact (I4)
    assert "Mei LIN joined" in by_anchor["ae002"].text
    assert [
        (str(c.source_id), c.block_start, c.block_end) for c in by_anchor["ae002"].citations
    ] == [("src-02", 2, 3)]
    assert [
        (str(c.source_id), c.block_start, c.block_end) for c in by_anchor["0da02"].citations
    ] == [("src-01", 2, 3)]


async def test_every_person_carries_the_line_that_says_who_they_are():
    claims = await _around(subject="lumenlab")
    by_anchor = {str(c.anchor): c for c in claims}
    # Mei LIN has an overview definition; Ke ZHOU has none, so the head of her ledger stands in.
    assert "definition" in by_anchor["ae001"].labels
    assert "Mei LIN is the optics lead." in by_anchor["ae001"].text
    assert "Ke ZHOU coordinates" in by_anchor["bc001"].text
    assert by_anchor["bc001"].labels == ("current", "person:memory/people/ke-zhou.md")


async def test_the_most_linked_person_comes_first_and_the_superseded_link_comes_last():
    assert _people_of(await _around(subject="lumenlab")) == [
        "memory/people/mei-lin.md",  # two living links
        "memory/people/ke-zhou.md",  # one
        "memory/people/hana-oda.md",  # one, and canonical has replaced it
    ]


async def test_a_superseded_linking_claim_is_kept_and_labelled_never_dropped():
    """`person_claims`' own convention: canonical does not delete, so a relation the library
    has replaced is part of what it knows — it simply does not rank."""
    claims = await _around(subject="lumenlab")
    [hana] = [c for c in claims if str(c.anchor) == "cd001"]
    assert "superseded" in hana.labels and "links-to" in hana.labels
    assert "current" not in hana.labels


async def test_only_person_pages_are_enumerated():
    """A project page links the same subject, and the subject links itself nowhere."""
    people = _people_of(await _around(subject="lumenlab"))
    assert "projects/apex-bench.md" not in people
    assert "projects/lumenlab.md" not in people
    assert all(p.startswith("memory/people/") for p in people)


async def test_a_subject_nobody_is_linked_with_is_an_empty_face_not_an_error():
    lonely = _subject("projects/quiet.md", slug="quiet", title="Quiet", aid="3c0")
    assert await _around(subject="quiet", documents=[*LIBRARY, lonely]) == []
    text = await PeopleComponent(FAMILY).people_around(
        USER, subject="quiet", documents=[*LIBRARY, lonely]
    )
    assert "no person page in this library is linked with quiet" in text


async def test_a_subject_the_library_does_not_hold_is_an_empty_face_not_an_error():
    assert await _around(subject="ghost") == []
    assert "no document in this library is named ghost" in await PeopleComponent(
        FAMILY
    ).people_around(USER, subject="ghost", documents=LIBRARY)


# ── the two seams ─────────────────────────────────────────────────────────────


async def test_the_fast_path_returns_the_enumeration_and_declares_its_argument_for_the_router():
    component = PeopleComponent(FAMILY)
    path = _path(component, "people_around")
    assert path.name == "people_around"
    assert list(path.args_schema.model_fields) == ["subject"]
    described = path.args_schema.model_fields["subject"].description
    assert "project" in described and "PEOPLE connected to it" in described
    result = await path.run(
        USER, path.args_schema(subject="lumenlab"), documents=LIBRARY
    )
    assert _people_of(result.claims) == [
        "memory/people/mei-lin.md",
        "memory/people/ke-zhou.md",
        "memory/people/hana-oda.md",
    ]


async def test_the_deep_tool_is_the_same_enumeration_as_text_with_its_citations():
    [tool] = [
        t for t in PeopleComponent(FAMILY).recall_tools(USER, documents=LIBRARY)
        if t.name == "people_around"
    ]
    text = await tool.ainvoke({"subject": "Lumen Lab"})
    assert "# people around `projects/lumenlab.md` — Lumen Lab" in text
    assert "`memory/people/mei-lin.md` — Mei LIN · 2 linking claim(s)" in text
    assert "[c:ae002 · links-to] Mei LIN joined" in text
    assert "[cite: src-02 ¶2-3]" in text
    assert "[c:cd001 · links-to · superseded]" in text
    assert "who: Mei LIN is the optics lead." in text
    assert "— 3 of 3 people shown" in text


async def test_the_deep_tool_paginates_in_people_and_says_what_it_did_not_show():
    crowd = [
        _page(
            f"person-{n:02d}",
            f"Person {n:02d}",
            f"# Person {n:02d}\n\n- Person {n:02d} works at "
            f"[Lumen Lab](../../projects/lumenlab.md). [cite: src-06 ¶{n}-{n}] "
            f"<!-- c:f{n:02d}ab -->\n",
        )
        for n in range(10)
    ]
    text = await PeopleComponent(FAMILY).people_around(
        USER, subject="lumenlab", documents=[*LIBRARY, *crowd]
    )
    assert "— 8 of 13 people shown (positions 1-8)" in text
    assert 'the rest: people_around(subject="lumenlab", offset=8, limit=8)' in text


async def test_the_fast_path_never_truncates_what_the_deep_tool_pages_through():
    """A path returns everything it knows (`recall/paths.py`); the framework orders it
    against the question and spends the declared cap on THAT order."""
    crowd = [
        _page(
            f"person-{n:02d}",
            f"Person {n:02d}",
            f"# Person {n:02d}\n\n- Person {n:02d} works at "
            f"[Lumen Lab](../../projects/lumenlab.md). [cite: src-06 ¶{n}-{n}] "
            f"<!-- c:f{n:02d}ab -->\n",
        )
        for n in range(10)
    ]
    claims = await _around(subject="lumenlab", documents=[*LIBRARY, *crowd])
    assert len(_people_of(claims)) == 13


def test_the_router_is_offered_both_paths_and_the_offer_is_byte_stable():
    """Discover pickup is automatic — the contract is assembled from the REGISTERED paths'
    own descriptions and argument schemas. Pinned here rather than in the core surface
    tests because those may not import a service component (`service → core` is one-way);
    the core pin stays the zero-path contract and is unchanged by this path existing."""
    from pneuma_knowledge_core.recall.live_pipeline import discover_contract

    component = PeopleComponent(FAMILY)
    contract = discover_contract("general", tuple(component.fast_paths(USER)))
    assert "`person`" in contract and "`people_around`" in contract
    assert "subject" in contract
    assert contract == discover_contract("general", tuple(component.fast_paths(USER)))
    assert "2026" not in contract


def test_a_deployment_with_no_component_is_byte_for_byte_what_it_always_was():
    from pneuma_knowledge_core.recall.live_pipeline import discover_contract

    bare = discover_contract("general", ())
    assert "`people_around`" not in bare and "`person`" not in bare
    assert bare == discover_contract("general", ())
