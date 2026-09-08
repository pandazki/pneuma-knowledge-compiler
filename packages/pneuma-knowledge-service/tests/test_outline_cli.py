"""The complete map: one canonical listing, no per-document reads or model calls."""

from __future__ import annotations

import io
import json

import pytest

from pneuma_knowledge_core.canonical_glance import render_canonical_glance
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.skill import SkillVersion, register_skill_base
from pneuma_knowledge_service.cli import build_parser, dispatch

from _cli_library import USER, document, library


TEMPLATES = ["work/{slug}.md", "empty/{slug}.md", "people/{slug}.md", "facts/{slug}.md"]
OTHER_USER = UserId("u-outline-other")


class ListingOnly:
    """The current port returns bodies in its listing; no separate body read is allowed."""

    def __init__(self, documents, *, manifest=None):
        self.documents = documents
        self.manifest = manifest
        self.calls = []

    async def list(self, user_id, *, at=None):
        self.calls.append(user_id)
        return list(self.documents.get(user_id, []))

    async def read_meta(self, user_id, rel_path):
        assert user_id in self.documents
        return self.manifest

    async def read(self, *args, **kwargs):
        raise AssertionError("outline must not read individual documents")


@pytest.fixture
def skill():
    value = SkillVersion.from_parts(
        skill_id="synthetic-outline", version="outline-test",
        instructions="Synthetic work, people and facts.", path_templates=TEMPLATES,
    )
    register_skill_base(value.version, value)
    return value


def context(skill, documents, *, manifest=None):
    ctx = library(user_schema_base_version=skill.version).ctx
    ctx.canonical = ListingOnly(
        {USER: documents, OTHER_USER: [document("facts/other.md", "# Other tenant\n")]},
        manifest=manifest,
    )
    return ctx


async def run(ctx, *argv, user=USER):
    args = build_parser().parse_args(["--user", str(user), *argv])
    out, err = io.StringIO(), io.StringIO()
    code = await dispatch(ctx, args, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def large_library():
    return [
        document(
            f"{family}/synthetic-subject-{number:02d}.md",
            f"# Synthetic {family} subject {number:02d}\n\n"
            "<!-- overview -->\n<!-- overview:definition -->\n### What this is\n\n"
            f"Synthetic {family} subject {number:02d}. c:{index:02x}{number:04x}\n"
            "<!-- /overview -->\n\n"
            f"- The synthetic plan has {number} steps. [cite: synthetic-source ¶0] "
            f"<!-- c:{index:02x}{number:04x} -->\n",
        )
        for index, family in enumerate(("work", "people", "facts"), start=1)
        for number in range(24)
    ][::-1]


@pytest.mark.parametrize("definitions", [False, True])
async def test_outline_is_complete_where_glance_drops_pages(skill, definitions):
    docs = large_library()
    ctx = context(skill, docs)
    code, output, err = await run(ctx, "outline", *(("--definitions",) if definitions else ()))
    assert (code, err) == (0, "")
    assert ctx.canonical.calls == [USER]
    assert len(output) > 5_000
    for doc in docs:
        assert output.count(doc.path) == 1
    assert output.count("(1 claims)") == 72
    assert output.count("  definition:") == (72 if definitions else 0)
    assert "## empty/{slug}.md\n(empty)" in output
    assert [line[3:] for line in output.splitlines() if line.startswith("## ")] == TEMPLATES
    assert output.index("work/synthetic-subject-00.md") < output.index("work/synthetic-subject-23.md")
    assert "Other tenant" not in output

    code, glance, err = await run(ctx, "glance", "--json")
    assert (code, err) == (0, "")
    payload = json.loads(glance)
    assert payload == {
        "glance": render_canonical_glance(docs, skill),
        "chars": len(render_canonical_glance(docs, skill)),
    }
    assert sum(doc.path in payload["glance"] for doc in docs) < len(docs)
    assert "more" in payload["glance"]


@pytest.mark.parametrize("definitions", [False, True])
async def test_json_tree_and_definition_are_derived_from_the_listing(skill, definitions):
    body = (
        "# Synthetic lantern <!-- title annotation -->\n\n"
        "<!-- overview -->\n<!-- overview:definition -->\n### What this is\n\n"
        "A synthetic light. c:aa01 [cite: synthetic-source ¶0]\n<!-- /overview -->\n\n"
        "- It emits light. [cite: synthetic-source ¶0] <!-- c:aa01 -->\n"
        "- It has a switch. [cite: synthetic-source ¶1] <!-- c:aa02 -->\n"
    )
    ctx = context(skill, [document("work/lantern.md", body, title="Ignored title")])
    flags = ("--definitions",) if definitions else ()
    code, output, err = await run(ctx, "outline", "--json", *flags)
    assert (code, err) == (0, "")
    item = {
        "path": "work/lantern.md", "title": "Synthetic lantern", "claims": 2,
        "volumes": 0, "kind": "page", "archived": False,
    }
    if definitions:
        item["definition"] = "A synthetic light."
    assert json.loads(output) == {
        "families": [
            {"template": template, "documents": [item] if index == 0 else []}
            for index, template in enumerate(TEMPLATES)
        ],
        "documents": 1,
    }
    assert ctx.canonical.calls == [USER]
    code, output, err = await run(ctx, "outline", *flags)
    assert (code, err) == (0, "")
    assert "work/lantern.md — Synthetic lantern (2 claims)" in output
    assert ("\n  definition: A synthetic light.\n" in output) == definitions
    assert "emits light" not in output


@pytest.mark.parametrize("template", TEMPLATES)
async def test_family_filter_keeps_every_member_and_empty_families(skill, template):
    docs = large_library()
    ctx = context(skill, docs)
    code, output, err = await run(ctx, "outline", "--json", "--family", template)
    assert (code, err) == (0, "")
    tree = json.loads(output)
    expected = sorted(doc.path for doc in docs if doc.path.startswith(template.split("/")[0] + "/"))
    assert [family["template"] for family in tree["families"]] == [template]
    assert [doc["path"] for doc in tree["families"][0]["documents"]] == expected
    assert tree["documents"] == len(expected)
    assert ctx.canonical.calls == [USER]


async def test_unknown_family_is_refused_and_does_not_masquerade_as_empty(skill):
    ctx = context(skill, [])
    assert await run(ctx, "outline", "--family", "missing/{slug}.md") == (
        2, "", "no such family: missing/{slug}.md\n",
    )


@pytest.mark.parametrize("include_archived", [False, True])
async def test_volumes_records_and_archive_order(skill, include_archived):
    docs = [
        document("work/z-live.md", "# Live work\n"),
        document("work/z-live/a01.md", "Earlier work.", archived_from="work/z-live.md"),
        document("work/z-live/a02.md", "More earlier work."),
        document("work/a-retired.md", "# Retired work\n", type="archived",
                 archive_of="archive/work/a-retired.md"),
        document("archive/work/a-retired.md", "# Original work\n"),
        document("archive/work/a-retired/a01.md", "Frozen earlier work.",
                 archived_from="work/a-retired.md"),
    ]
    ctx = context(skill, docs)
    flags = ("--include-archived",) if include_archived else ()
    code, output, err = await run(ctx, "outline", "--json", "--family", TEMPLATES[0], *flags)
    assert (code, err) == (0, "")
    tree = json.loads(output)
    members = tree["families"][0]["documents"]
    assert tree["documents"] == (3 if include_archived else 2)
    assert [doc["path"] for doc in members] == [
        "work/a-retired.md", "work/z-live.md",
    ] + (["archive/work/a-retired.md"] if include_archived else [])
    assert members[0]["kind"] == "record" and members[0]["archived"] is False
    assert members[0]["volumes"] == 0
    assert members[1]["kind"] == "page" and members[1]["volumes"] == 2
    if include_archived:
        assert members[2]["archived"] is True and members[2]["volumes"] == 1
    assert ctx.canonical.calls == [USER]
    _, output, _ = await run(ctx, "outline", *flags)
    assert "work/a-retired.md — Retired work (0 claims) [record]" in output
    assert "work/z-live.md — Live work (0 claims) +2 volumes" in output
    assert ("archive/work/a-retired.md — Original work (0 claims) +1 volumes [archived]" in output) == include_archived
    assert "a01.md" not in output and "a02.md" not in output


async def test_unfiled_pages_and_orphaned_volumes_remain_visible(skill):
    ctx = context(skill, [
        document("outside/loose.md", "", title="Loose page"),
        document("work/gone/a01.md", "Earlier work.", archived_from="work/gone.md"),
    ])
    code, output, err = await run(ctx, "outline", "--json", "--definitions")
    assert (code, err) == (0, "")
    tree = json.loads(output)
    assert tree["documents"] == 2
    assert tree["families"][-1]["template"] is None
    assert [(doc["path"], doc["title"]) for doc in tree["families"][-1]["documents"]] == [
        ("outside/loose.md", "Loose page"), ("work/gone/a01.md", "a01"),
    ]
    assert all("definition" not in doc for doc in tree["families"][-1]["documents"])


async def test_empty_library_names_every_declared_family(skill):
    ctx = context(skill, [])
    assert await run(ctx, "outline", "--json") == (0, json.dumps({
        "families": [{"template": template, "documents": []} for template in TEMPLATES],
        "documents": 0,
    }, indent=2) + "\n", "")
    _, output, _ = await run(ctx, "outline")
    assert output.count("(empty)") == len(TEMPLATES)


async def test_listing_is_tenant_scoped(skill):
    ctx = context(skill, large_library())
    code, output, err = await run(ctx, "outline", user=OTHER_USER)
    assert (code, err) == (0, "")
    assert "facts/other.md" in output and "synthetic-subject" not in output
    assert ctx.canonical.calls == [OTHER_USER]


async def test_outline_reads_the_evolved_contract_without_materializing_it(skill):
    manifest = json.dumps({
        "agent_evolved": True, "base_version": skill.version,
        "instructions": "Synthetic evolved families.",
        "path_templates": ["facts/{slug}.md", "work/{slug}.md"],
    })
    ctx = context(skill, [], manifest=manifest)
    code, output, err = await run(ctx, "outline", "--json")
    assert (code, err) == (0, "")
    assert [family["template"] for family in json.loads(output)["families"]] == [
        "facts/{slug}.md", "work/{slug}.md",
    ]
    assert ctx.canonical.calls == [USER]
