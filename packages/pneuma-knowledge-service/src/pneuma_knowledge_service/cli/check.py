"""`pkc library check` — the gate's predicates over the COMMITTED library (ruling 10).

Correctness is the framework's, and it is told rather than asked for. A write command
post-checks the page it touched (`cli/draft.py`); this is the other end of the same ruling:
the whole repository, judged by the same predicates, at any time, and REPORTED — never
repaired. A repair is a compile, under a contract, through the gate, and a command that
silently fixed canonical would be the one write path the design does not have.

There is no second rulebook here. The predicates are `run_gate`'s, run over a draft that
CHANGES NOTHING — base and working table are the committed library — so:

- anchor uniqueness, supersession legality, frontmatter and anchor coverage are judged
  repository-wide, which is how the gate judges them anyway;
- every `[cite:]` in every current page is judged for shape AND resolvability, because
  passing `known_source_bounds` turns off the single-span grandfather rule: nothing is exempt
  for having been committed already;
- path ownership is judged against the composed templates;
- every enabled component's `gate_checks(docs, docs)` runs, with the library as its own base;
- and the checks that only make sense about a CHANGE (anchor continuity, provenance on new
  anchors, dead links introduced this round, a frozen volume that moved) find nothing,
  because nothing changed. That is not them being skipped; it is them being true.

Two things the unchanged draft cannot say, and both are added explicitly:

- **the overview rules.** `check_overviews` deliberately does not re-judge a region identical
  to its base — a grandfather rule that exists so an evolve merge cannot wedge every later
  compile. Over a committed library there is no "this round", so the whole region is judged —
  over the pages a compile may write. The archive is left to `run_gate`'s own exemptions
  (docs/design/archive.md): a head under `archive/`, or on the record a retired subject left
  at its live path, is one no write path can repair, and this command reports, never repairs.
- **the trailer.** Every canonical commit the store can enumerate must carry the framework's
  `Skill-Version` trailer; a commit without one is a canonical write nothing can attribute.
  Every channel stamps it — a compile, a groom heal, an evolve adopt, the skill manifest, and
  the archive job's move (which carries `Archive-Proposal:` in the same trailer block) — so
  this predicate accepts all of them and singles out only what the framework did not write.

Exit 4 when anything is found, 0 when nothing is. The rendering is `Violation.render()` —
the same line `post_write_violations` and the compile feedback print.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from pneuma_knowledge_core.compile.gate import Violation, run_gate
from pneuma_knowledge_core.compile.overview import check_overviews
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.domain.archive import is_archive_record, is_archived_path
from pneuma_knowledge_core.domain.ids import UserId

EXIT_OK = 0
EXIT_NOTHING = 1
EXIT_FINDINGS = 4

#: The trailer every canonical write channel stamps (`compile/runner.py:with_skill_trailer`).
SKILL_TRAILER = "Skill-Version"


async def cmd_library_check(
    ctx: Any,
    user_id: UserId,
    *,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    documents = await ctx.canonical.list(user_id)
    if not documents:
        print("this library holds no canonical pages yet", file=err)
        return EXIT_NOTHING

    from ..skills import path_templates_for

    templates = await path_templates_for(ctx.settings, ctx.canonical, user_id)
    draft = PatchDraft.from_canonical(
        list(documents),
        list(templates),
        overview_budget_chars=ctx.settings.overview_budget_chars,
    )
    bounds = await ctx.store.block_counts(user_id)
    violations: list[Violation] = list(
        run_gate(
            draft,
            (),
            known_source_bounds=bounds,
            overview_budget_chars=ctx.settings.overview_budget_chars,
            overview_required_after_claims=ctx.settings.overview_required_after_claims,
        )
    )
    # The overview region judged in full: over a committed library every head is one someone
    # wrote, and none of them is "carried over from this round's base".
    #
    # Over the pages a compile MAY WRITE, and only those. This pass is the one place this
    # command is stricter than `run_gate` — it drops the grandfather rule — and a finding is
    # only worth reporting where a compile can repair it. The archive is where the Owner
    # moved a subject out of the answering set: every write under `archive/` is refused by
    # the gate's own rule 5c, and the record standing at the retired page's live path is
    # read-only to every write verb. Reporting an unrepairable head on either would be this
    # command inventing a rule the framework does not hold (docs/design/archive.md §2.1,
    # §2.3). `run_gate` above still judged them, by main's own exemptions.
    bodies = {
        doc.path: doc.body
        for doc in documents
        if not is_archived_path(doc.path) and not is_archive_record(doc)
    }
    standing = set(violations)
    for kind, path, detail in check_overviews(
        bodies, {}, budget=ctx.settings.overview_budget_chars
    ):
        found = Violation(kind, path, detail)
        if found not in standing:
            violations.append(found)

    violations.extend(await _trailer_violations(ctx, user_id))

    payload = {
        "documents": len(documents),
        "findings": [
            {"kind": v.kind, "path": v.path, "detail": v.detail} for v in violations
        ],
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=out)
    elif not violations:
        print(f"{len(documents)} page(s) checked — nothing to report", file=out)
    else:
        for violation in violations:
            print(violation.render(), file=out)
    return EXIT_FINDINGS if violations else EXIT_OK


async def _trailer_violations(ctx: Any, user_id: UserId) -> list[Violation]:
    """Every enumerable canonical commit that carries no `Skill-Version` trailer.

    Reported against the repository rather than a page, because that is what it is about: a
    commit is not a document, and naming one of the documents it touched would be a guess.
    """
    snapshots = await ctx.canonical.snapshots(user_id)
    reader = getattr(ctx.canonical, "commit_trailer", None)
    if reader is None:
        return []
    out: list[Violation] = []
    for snapshot in snapshots:
        try:
            value = await reader(user_id, snapshot, SKILL_TRAILER)
        except Exception:  # noqa: BLE001 — an unreadable commit is reported, not raised
            value = None
        if value:
            continue
        out.append(
            Violation(
                "trailer",
                snapshot.ref,
                f"canonical commit carries no {SKILL_TRAILER} trailer "
                f"({snapshot.label or 'no subject'}) — nothing attributes this write to a "
                "contract",
            )
        )
    return out
