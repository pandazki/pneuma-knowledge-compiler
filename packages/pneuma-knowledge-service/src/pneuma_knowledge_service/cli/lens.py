"""`pkc lens` — the structure lens at the terminal (docs/design/structure-lens.md §5.2).

A read face, exactly like `pkc outline`: nothing runs it for the Steward, nothing is refused
because of it, and nothing it says enters a compile task. A person or an agent asks for the
library's shape and gets the same report the console shows — same lens, same templates, same
ref — because both go through `service/lens.py` and neither computes anything of its own.

Two output shapes and one rule about each. `--json` is a MACHINE face and is never paged: a
JSON report holding nine of three hundred findings is indistinguishable from a complete one,
so a caller that branched on it would be branching on a truncation nobody told it about.
Prose is paged for a reader with a context window, and its footer states how many findings
the page did not show — a prose page that stopped silently would make the same false claim
in the other rendering.

It exits 0 whenever it could read the library, findings or none. Exit 4 is `pkc library
check`'s "I found problems", and it is deliberately not spoken here: a library of any size
holds findings, so an exit code that said so would turn a reading into a verdict and make
every script that runs it treat the ordinary state of a growing library as a failure.
"""

from __future__ import annotations

import json

from pneuma_knowledge_core.lens import page_findings, render_action, render_impact

from ..lens import read_lens
from .read import EXIT_NOTHING, EXIT_OK, ReadRuntime

#: Level → the heading it is printed under, in the report's own order (§3.4). The levels come
#: from core; the words are the ones the design uses for them.
_LEVEL_HEADINGS: tuple[tuple[str, str], ...] = (
    ("principle", "principle — the layout, no single page fixes it"),
    ("drift", "drift — a page falls short of what its family expects"),
    ("shape", "shape — malformed in a way the write mechanism now refuses"),
)


def _finding_lines(finding) -> list[str]:  # noqa: ANN001 — core's Finding, structurally read
    """One finding as a person reads it: what and where, then why it costs and what to do."""
    where = " · ".join(finding.paths) or "(library-wide)"
    lines = [f"  {finding.lens}  {where}", f"    key       {finding.key}"]
    if finding.targets:
        lines.append(f"    targets   {' · '.join(finding.targets)}")
    if finding.evidence:
        lines.append(f"    evidence  {' · '.join(finding.evidence)}")
    impact, action = render_impact(finding), render_action(finding)
    if impact:
        lines.append(f"    costs     {impact}")
    if action:
        lines.append(f"    do        {action}  [{finding.actor}]")
    return lines


def _head_lines(report) -> list[str]:  # noqa: ANN001
    """The counts and the score — printed above every page, never paged away."""
    return [
        f"lens · {report.ref or 'HEAD'} · score {report.score}",
        f"{report.subjects} subjects · {report.files} files · "
        f"{report.claims} claims · {report.edges} edges",
    ]


def _blocks(findings) -> list[list[str]]:  # noqa: ANN001
    """The findings as whole units, each carrying the level heading it opens, if any.

    A block is the smallest thing a page may hold: paging that cut a finding in half would
    show an action with no subject, or evidence with nothing it is evidence for.
    """
    blocks: list[list[str]] = []
    for level, heading in _LEVEL_HEADINGS:
        of_level = [f for f in findings if f.level == level]
        for index, finding in enumerate(of_level):
            opener = ["", f"{heading} · {len(of_level)}"] if index == 0 else []
            blocks.append(opener + _finding_lines(finding))
    return blocks


def _pages(blocks: list[list[str]], page_chars: int) -> list[tuple[str, int]]:
    """Pack whole findings into pages of at most `page_chars`. `(text, findings on it)`.

    A single finding longer than a page is its own page rather than a cut one — the bound is
    a courtesy to a reader's window, and losing the end of an action to it would not be.
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


def _print(rt: ReadRuntime, report, findings) -> None:  # noqa: ANN001
    """The prose rendering: the head, one page of findings, and what the page left out."""
    head = _head_lines(report)
    if not findings:
        print("\n".join([*head, "", "no findings"]), file=rt.out)
        return
    blocks = _blocks(findings)
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
    footer = (
        f"[page {index}/{len(pages)} · {shown} of {len(blocks)} findings"
        f"{f' · --page {index + 1} for the next' if index < len(pages) else ''}"
        " · --all-pages for everything · --json for the whole report]"
    )
    print(footer, file=rt.out)


async def cmd_lens(rt: ReadRuntime, *, path: str = "", at: str = "") -> int:
    """The report at `at` (default HEAD), or one page's findings with `--path`.

    A page the library does not hold is EXIT_NOTHING and says so: a clean page and a mistyped
    one must not render the same sentence.
    """
    report, documents = await read_lens(rt.ctx, rt.user_id, at=(at or "").strip() or None)
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
    _print(rt, report, findings)
    return EXIT_OK
