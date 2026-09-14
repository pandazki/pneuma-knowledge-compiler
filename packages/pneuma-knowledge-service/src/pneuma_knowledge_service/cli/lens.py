"""The library's shape at the terminal: `pkc library review` and `pkc lens`.

Two tiers, two commands, one rule about each (docs/design/structure-lens.md §3.3, §4.5).

`pkc library review` is the CHECK — the page-level findings a Steward can act on, each with
its evidence, what it costs and the verb that repairs it. It is a READING and not a repair:
what acts on it is the review round (`pkc jobs enqueue review`), which opens a draft over the
whole library with this same report as its task.

`pkc lens` is the STRUCTURE LENS — the six dimensions only the whole library shows. It lists
no pages at all; a page-level fault belongs to the check, and a write-time fault belongs to
the gate, so what is left here is the reading that needs the god's-eye.

Both are read faces exactly like `pkc outline`: nothing runs them for the Steward, nothing is
refused because of them, and nothing they say enters a compile task on its own account.

Two output shapes and one rule about each. `--json` is a MACHINE face and is never paged: a
JSON report holding nine of three hundred findings is indistinguishable from a complete one,
so a caller that branched on it would be branching on a truncation nobody told it about.
Prose is paged for a reader with a context window, and its footer states how many findings
the page did not show — a prose page that stopped silently would make the same false claim in
the other rendering.

Both exit 0 whenever they could read the library, findings or none. Exit 4 is `pkc library
check`'s "I found problems", and it is deliberately not spoken here: a library of any size
holds findings, so an exit code that said so would turn a reading into a verdict and make
every script that runs it treat the ordinary state of a growing library as a failure.
"""

from __future__ import annotations

import json

from pneuma_knowledge_core.check import page_findings
from pneuma_knowledge_core.prompts import prompt

from ..lens import read_check, read_reading
from .read import EXIT_NOTHING, EXIT_OK, ReadRuntime

#: Finding kind → the heading it is printed under, in the report's own order (§3.1). The
#: kinds come from core; the words are the ones the design uses for them.
_KIND_HEADINGS: tuple[tuple[str, str], ...] = (
    ("legacy", "legacy — written before the mechanism refused it"),
    ("judgement", "judgement — the contract's expectation, no hook can decide it"),
)


def say(phrase) -> str:  # noqa: ANN001 — core's Phrase, structurally read
    """One catalog sentence, in the pack this process speaks.

    Through `prompt` rather than off the phrase's own `text`, so a deployment that rewords a
    key through the overlay seam changes what every reader sees — which is the whole reason
    the sentences are keys instead of strings. The rendered pair the phrase carries is the
    fallback for a key this catalog does not hold (a component's, an overlay's own).
    """
    if phrase is None:
        return ""
    key = getattr(phrase, "key", "")
    fields = dict(getattr(phrase, "fields", {}) or {})
    if key:
        rendered = prompt(key, **fields)
        if rendered and rendered != key:
            return rendered
    text = getattr(phrase, "text", {}) or {}
    return str(text.get("en") or next(iter(text.values()), ""))


# ───────────────────────────────────────────────────────────────────────────── paging

def _pages(blocks: list[list[str]], page_chars: int) -> list[tuple[str, int]]:
    """Pack whole blocks into pages of at most `page_chars`. `(text, blocks on it)`.

    A single block longer than a page is its own page rather than a cut one — the bound is a
    courtesy to a reader's window, and losing the end of an action to it would not be.
    """
    pages: list[tuple[str, int]] = []
    current: list[str] = []
    count = 0
    for block in blocks:
        text = "\n".join(block)
        if current and page_chars > 0 and len("\n".join(current)) + len(text) + 1 > page_chars:
            pages.append(("\n".join(current), count))
            current, count = [], 0
        current.extend(block)
        count += 1
    if current or not pages:
        pages.append(("\n".join(current), count))
    return pages


def _emit(rt: ReadRuntime, head: list[str], blocks: list[list[str]], unit: str) -> None:
    """The head, one page of blocks, and — when there is more — what the page left out."""
    pages = (
        [("\n".join(line for block in blocks for line in block), len(blocks))]
        if rt.all_pages
        else _pages(blocks, rt.page_chars)
    )
    index = min(max(rt.page, 1), len(pages))
    text, shown = pages[index - 1]
    print("\n".join([*head, text]), file=rt.out)
    if len(pages) == 1:
        return
    # The bound SAYS what it cut, in findings rather than characters: a reader counts
    # findings, and "9 of 370" is the fact a footer measured in characters cannot state.
    print(
        f"[page {index}/{len(pages)} · {shown} of {len(blocks)} {unit}"
        f"{f' · --page {index + 1} for the next' if index < len(pages) else ''}"
        " · --all-pages for everything · --json for the whole report]",
        file=rt.out,
    )


# ──────────────────────────────────────────────────────────────── tier two: the check


def _finding_lines(finding) -> list[str]:  # noqa: ANN001 — core's Finding, structurally read
    """One finding as a person reads it: what and where, then why it costs and what to do."""
    where = " · ".join(finding.paths) or "(library-wide)"
    lines = [f"  {finding.id}  {where}", f"    key       {finding.key}"]
    if finding.targets:
        lines.append(f"    targets   {' · '.join(finding.targets)}")
    if finding.evidence:
        lines.append(f"    evidence  {' · '.join(finding.evidence)}")
    impact, action = say(finding.impact), say(finding.action)
    if impact:
        lines.append(f"    costs     {impact}")
    if action:
        lines.append(f"    do        {action}")
    return lines


def finding_blocks(findings) -> list[list[str]]:  # noqa: ANN001
    """The findings as whole units, each carrying the kind heading it opens, if any.

    A block is the smallest thing a page may hold: paging that cut a finding in half would
    show an action with no subject, or evidence with nothing it is evidence for.
    """
    blocks: list[list[str]] = []
    for kind, heading in _KIND_HEADINGS:
        of_kind = [f for f in findings if f.kind == kind]
        for index, finding in enumerate(of_kind):
            opener = ["", f"{heading} · {len(of_kind)}"] if index == 0 else []
            blocks.append(opener + _finding_lines(finding))
    return blocks


def check_head(report) -> list[str]:  # noqa: ANN001
    """The counts — printed above every page, never paged away."""
    return [
        f"review · {report.ref or 'HEAD'} · {len(report.findings)} finding(s)",
        f"{report.subjects} subjects · {report.files} files · "
        f"{report.claims} claims · {report.edges} edges",
    ]


async def cmd_library_review(rt: ReadRuntime, *, path: str = "", at: str = "") -> int:
    """The check's report at `at` (default HEAD), or one page's findings with `--path`.

    A page the library does not hold is EXIT_NOTHING and says so: a clean page and a mistyped
    one must not render the same sentence.
    """
    report, documents = await read_check(rt.ctx, rt.user_id, at=(at or "").strip() or None)
    path = (path or "").strip()
    if path:
        if not any(doc.path == path for doc in documents):
            print(f"no such page: {path}", file=rt.err)
            return EXIT_NOTHING
        findings = list(page_findings(report, path))
        keys = {finding.key for finding in findings}
        payload = {
            **report.to_dict(),
            "path": path,
            "findings": [
                entry for entry in report.to_dict()["findings"] if entry["key"] in keys
            ],
        }
    else:
        if not documents:
            print("this library holds no canonical pages yet", file=rt.err)
            return EXIT_NOTHING
        findings = list(report.findings)
        payload = report.to_dict()
    if rt.as_json:
        # WHOLE, always — see the module docstring. The paging flags are prose flags here.
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), file=rt.out)
        return EXIT_OK
    head = check_head(report)
    if not findings:
        print("\n".join([*head, "", "no findings"]), file=rt.out)
        return EXIT_OK
    _emit(rt, head, finding_blocks(findings), "findings")
    return EXIT_OK


# ───────────────────────────────────────────────────────────── tier three: the lens


def _metric_line(metric) -> str:  # noqa: ANN001 — core's metric row, structurally read
    """One metric, and its movement when there is a previous reading to move against."""
    line = f"    {metric.name}: {metric.value}"
    if metric.previous is None:
        return line
    delta = metric.delta
    sign = "" if delta is None else ("+" if delta > 0 else "")
    return f"{line}  (was {metric.previous}{'' if delta is None else f', {sign}{delta}'})"


def _dimension_block(dimension) -> list[str]:  # noqa: ANN001
    """One dimension, whole: the band as a word, what it sees, what it implies, its metrics."""
    lines = ["", f"{dimension.id} · {dimension.band}"]
    statement = say(dimension.statement)
    if statement:
        lines.append(f"  {statement}")
    direction = say(dimension.direction)
    if direction:
        lines.append(f"  → {direction}")
    lines.extend(_metric_line(metric) for metric in dimension.metrics)
    if dimension.evidence:
        lines.append(f"    evidence: {' · '.join(dimension.evidence)}")
    return lines


def _lens_head(reading) -> list[str]:  # noqa: ANN001
    return [
        f"lens · {reading.ref or 'HEAD'} · "
        f"{('vs ' + reading.previous_ref) if reading.previous_ref else 'no previous reading'}",
        f"{reading.subjects} subjects · {reading.files} files · "
        f"{reading.claims} claims · {reading.edges} edges",
    ]


async def cmd_lens(rt: ReadRuntime, *, at: str = "", previous: str | None = None) -> int:
    """The six dimensions at `at` (default HEAD), against `--previous` (default: its parent).

    No `--path`: the lens reads the library as a whole and has nothing to say about one page.
    That is not a missing option — it is the ruling that gives the lens its subject, and the
    page-level reading it used to carry is `pkc library review`.
    """
    reading = await read_reading(
        rt.ctx, rt.user_id, at=(at or "").strip() or None, previous=previous
    )
    if rt.as_json:
        print(
            json.dumps(reading.to_dict(), ensure_ascii=False, indent=2, default=str),
            file=rt.out,
        )
        return EXIT_OK
    head = _lens_head(reading)
    if not reading.files or not reading.dimensions:
        # The six dimensions of an empty library are six sentences about nothing, and a
        # reader must not have to work out that "even" means "there is nothing here". Said
        # the same way `pkc library review` says it, and with the same exit code.
        print("this library holds no canonical pages yet", file=rt.err)
        return EXIT_NOTHING
    _emit(rt, head, [_dimension_block(d) for d in reading.dimensions], "dimensions")
    return EXIT_OK


__all__ = ["check_head", "cmd_lens", "cmd_library_review", "finding_blocks", "say"]
