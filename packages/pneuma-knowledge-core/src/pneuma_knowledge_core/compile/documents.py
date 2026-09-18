"""Canonical document text (de)serialization.

A canonical document on disk is markdown with a YAML-style frontmatter fence. v1
frontmatter is a flat map of scalar strings, except for the reserved `speech_terms`
list encoded as inline JSON (also valid YAML). A
minimal deterministic serializer round-trips it without pulling a YAML dependency into
core (kept at pydantic + langchain-core). Keys are emitted sorted for byte-stability.

The body itself has two parts, and they are stated at the bottom of this module: the
LEDGER (anchored, cited claims, written one claim at a time) and the OVERVIEW (a bounded,
wholesale-rewritable head, delimited by system-written HTML comments).

The document id key was once spelled `pneuma_id`. Canonical is the one non-rebuildable
layer (invariant I2), so already-committed documents keep that spelling forever and are
NOT rewritten by a history migration. Instead the read side folds the legacy key onto
`doc_id` (`normalize_frontmatter`, applied by `parse_document`) and the write side only
ever emits `doc_id` — so a legacy document migrates for free the next time its file is
serialized, and nothing downstream ever sees two spellings of one field.
"""

from __future__ import annotations

import json

import re
from dataclasses import dataclass

from ..domain.ids import ANCHOR_MARK_RE
from ..prompts import prompt
from .links import _render_relative

_FENCE = "---"

DOC_ID_KEY = "doc_id"
# Historical spellings of DOC_ID_KEY, accepted on read only.
LEGACY_DOC_ID_KEYS = ("pneuma_id",)


def normalize_frontmatter(frontmatter: dict) -> dict:
    """Fold legacy document-id key spellings onto `doc_id` (read-side compatibility).

    The legacy key is dropped rather than kept alongside, so re-serializing the document
    writes only the current spelling. An explicit `doc_id` always wins.
    """
    normalized = dict(frontmatter)
    # Legacy fields are scalar strings; speech_terms is the structured exception. A caller — the
    # compile model passing `{"aliases": ["a", "b"]}` — may hand in a list; it is folded
    # to the one on-disk spelling, comma-separated, so the file never carries a Python
    # repr and every reader parses one shape.
    for key, value in list(normalized.items()):
        if key == "speech_terms":
            continue
        if isinstance(value, (list, tuple)):
            normalized[key] = ", ".join(str(item).strip() for item in value if str(item).strip())
    for legacy_key in LEGACY_DOC_ID_KEYS:
        legacy_value = normalized.pop(legacy_key, None)
        if legacy_value is None:
            continue
        if not str(normalized.get(DOC_ID_KEY, "")).strip():
            normalized[DOC_ID_KEY] = legacy_value
    return normalized


#: Frontmatter the system DERIVES from the body rather than storing what anyone typed.
#: A document's name is the `# ` line a reader already sees at the top of it, so a second,
#: independently-written spelling of that name can only ever disagree with it — which is
#: what a real library showed: `title` empty on 58 of 85 pages, a person's JOB title on two.
TITLE_KEY = "title"

#: A trailing HTML comment on the title line — an anchor mark, a `supersedes` marker, any
#: system annotation. The title is the text, not the machinery that rides behind it.
_TRAILING_COMMENT_RE = re.compile(r"(?:[ \t]*<!--.*?-->)+[ \t]*$")


def derived_title(body: str) -> str:
    """`body`'s LEADING `# ` heading text, or `""` when its first line is not one.

    Stripped of anchor marks, of any trailing HTML comment, and of surrounding whitespace —
    a title is what the heading SAYS. Deliberately the same rule the glance reads
    (`canonical_glance.document_title`), so the stored field and the derived display name
    agree by construction instead of by discipline.

    LEADING, and only leading (docs/design/structure-lens.md §2). This used to read the first
    `# ` line anywhere in the body, which meant a heading typed in the middle of an append
    renamed the page — silently, in every outline, glance and retrieval card, with nothing in
    the diff saying a name had changed. A page is named by the heading at the top of it; a
    heading further down is text, the write faces now refuse a new one
    (`anchor_ops.refuse_heading_in_block`), and `retitle` is the verb that changes a name.
    """
    for line in body.split("\n"):
        if not line.strip():
            continue
        if not line.startswith("# "):
            return ""
        text = ANCHOR_MARK_RE.sub("", line[2:])
        text = _TRAILING_COMMENT_RE.sub("", text).strip()
        return text
    return ""


def set_leading_title(body: str, title: str) -> str:
    """`body` with `title` as its leading `# ` heading — inserted when it has none.

    The one place a page's name is written, so `retitle` and any later channel that renames
    a page produce the same bytes. A trailing run of system markers on the existing heading
    line (its anchor, a supersedes marker) is KEPT: those are the system's and they identify
    the block, while the words in front of them are the name.
    """
    lines = body.split("\n")
    at = next((n for n, line in enumerate(lines) if line.strip()), None)
    if at is not None and lines[at].startswith("# "):
        markers = _TRAILING_COMMENT_RE.search(lines[at])
        lines[at] = f"# {title}" + (markers.group(0) if markers else "")
        return "\n".join(lines)
    head = [f"# {title}", ""]
    if at is None:
        return "\n".join(head).rstrip("\n")
    return "\n".join(head + lines[at:])


def with_derived_title(frontmatter: dict, body: str) -> dict:
    """`frontmatter` with `title` set from `body`'s H1 — or REMOVED when there is none.

    Removed, not merely left alone: a derived field that survives the disappearance of what
    it derives from is a stored field again. Applied at every write path that serializes a
    changed document (`PatchDraft.create_document` / `to_files`, `build_rollover`), never at
    the read/render faces — recall and evolve re-render documents nobody touched, and a
    derivation there would rewrite pages this round never wrote.
    """
    out = dict(frontmatter)
    title = derived_title(body)
    if title:
        out[TITLE_KEY] = title
    else:
        out.pop(TITLE_KEY, None)
    return out


#: Characters that make a scalar unreadable as a bare YAML value where it appears: a colon
#: separates a key from its value, a `#` opens a comment, a quote opens a quoted scalar, and a
#: newline — real or written as the two characters `\n` — ends the line the value is on.
_YAML_UNSAFE = (":", "#", '"', "'", "\n", "\\n")

#: …and characters YAML reads as SYNTAX when a value starts with one (an indicator).
_YAML_LEADING_INDICATORS = "-?:,[]{}#&*!|>%@`\"' \t"


def _needs_quoting(value: str) -> bool:
    if not value:
        return False
    if value != value.strip():
        return True
    if value[0] in _YAML_LEADING_INDICATORS:
        return True
    return any(token in value for token in _YAML_UNSAFE)


def _quote_scalar(value: str) -> str:
    """One YAML double-quoted scalar: backslash and quote escaped, real newlines folded."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def _unquote_scalar(raw: str) -> str:
    """The inverse of `_quote_scalar`, and the round trip the parser owes it.

    A single-quoted scalar is read too, because a human editing a frontmatter by hand writes
    one; nothing ever emits it.
    """
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        out: list[str] = []
        index = 1
        while index < len(raw) - 1:
            char = raw[index]
            if char == "\\" and index + 1 < len(raw) - 1:
                nxt = raw[index + 1]
                out.append("\n" if nxt == "n" else nxt)
                index += 2
                continue
            out.append(char)
            index += 1
        return "".join(out)
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    return raw


def render_document(frontmatter: dict, body: str) -> str:
    """Serialize (frontmatter, body) to a frontmatter-fenced markdown file.

    `title` is the one value written QUOTED when it needs quoting. It is the only frontmatter
    field whose content is a subject's real name rather than a slug or an id, so it is the
    only one that legitimately carries a colon, a `#` or a quote — and an unquoted `title:
    Aurora: phase two` is a frontmatter that parses back as `Aurora`, i.e. a page whose
    stored name silently differs from the one on its page. Every other key stays byte-for-byte
    as it was written, so no existing file's frontmatter moves for a rule it never needed.
    """
    lines = [_FENCE]
    for key in sorted(frontmatter):
        value = frontmatter[key]
        if key == "speech_terms" and isinstance(value, list):
            value = json.dumps(value, ensure_ascii=False)
        if key == TITLE_KEY and isinstance(value, str) and _needs_quoting(value):
            value = _quote_scalar(value)
        lines.append(f"{key}: {value}")
    lines.append(_FENCE)
    text = "\n".join(lines) + "\n"
    if body:
        text += "\n" + body.rstrip("\n") + "\n"
    return text


def parse_document(text: str) -> tuple[dict, str]:
    """Parse a frontmatter-fenced markdown file into (frontmatter, body).

    A file without a leading fence parses as empty frontmatter + whole text as body.
    Legacy document-id keys are normalized to `doc_id` here, so every caller that loads a
    canonical file off disk/git sees one spelling (see the module docstring).
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != _FENCE:
        return {}, text.strip("\n")
    frontmatter: dict = {}
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            end = i
            break
        raw = lines[i]
        if ":" in raw:
            key, _, value = raw.partition(":")
            name = key.strip()
            # Unquoted for exactly the key `render_document` quotes, so the two halves of the
            # round trip cover the same set: a value nothing ever quotes must not be read as
            # quoted either, or a field that happens to open and close on a quote character
            # would lose two bytes every time its file was re-serialized.
            if name == "speech_terms":
                try:
                    frontmatter[name] = json.loads(value.strip())
                except ValueError:
                    frontmatter[name] = value.strip()
                continue
            frontmatter[name] = (
                _unquote_scalar(value.strip()) if name == TITLE_KEY else value.strip()
            )
    if end < 0:
        return {}, text.strip("\n")
    body = "\n".join(lines[end + 1 :]).strip("\n")
    return normalize_frontmatter(frontmatter), body


# ═══════════════════════════════════════════════════════════════ the overview region
#
# A canonical document has two parts. The LEDGER is everything the claim-level write tools
# produce: anchored, cited claims under sections, append/edit/supersede only, anchors
# immutable. The OVERVIEW is a bounded head above it — the current picture of the subject in
# four slots — which the compile model may rewrite WHOLESALE whenever it judges the picture
# has changed. Losing an overview sentence loses nothing: every one of them is grounded in a
# ledger claim, so the overview is a reading of the ledger, never a second authority.
#
# The region is delimited by HTML comments the SYSTEM writes; the model never types one. The
# slots inside are delimited the same way, and that is the reason parsing does not key on the
# headings: the headings are catalog prose and a deployment may translate or rewrite them,
# while `<!-- overview:definition -->` means the same thing in every language and in every
# overlay. Reading a document must not depend on which language pack was loaded when it was
# written (discipline 1: mechanism, not prose).

OVERVIEW_OPEN = "<!-- overview -->"
OVERVIEW_CLOSE = "<!-- /overview -->"

#: The four slots, in render order. `definition` is the "one level below the title" line the
#: compile outline and the recall glance show for each document.
OVERVIEW_SLOTS = ("definition", "summary", "introduction", "connections")

#: Any line that is nothing but an overview marker — the region's two delimiters and the four
#: slot openers. Every block walker in the system skips these lines: they are structure, not
#: claim text, so they must never be segmented into a block (which would make them orphaned
#: canonical text) nor swallowed into a neighbouring claim.
OVERVIEW_MARKER_RE = re.compile(r"^[ \t]*<!--[ \t]*/?overview(?::[a-z_]+)?[ \t]*-->[ \t]*$")

_SLOT_OPEN_RE = re.compile(r"^[ \t]*<!--[ \t]*overview:([a-z_]+)[ \t]*-->[ \t]*$")
_OVERVIEW_OPEN_RE = re.compile(r"^[ \t]*<!--[ \t]*overview[ \t]*-->[ \t]*$")
_OVERVIEW_CLOSE_RE = re.compile(r"^[ \t]*<!--[ \t]*/overview[ \t]*-->[ \t]*$")
_CONNECTION_RE = re.compile(
    r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[(?P<label>[^\]]*)\]\((?P<href>[^)]*)\)[ \t]*"
    r"(?:[—–-][ \t]*)?(?P<relation>.*)$"
)
_HEADING_LINE_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+\S")


def slot_marker(slot: str) -> str:
    """The system-written opener for one overview slot."""
    return f"<!-- overview:{slot} -->"


@dataclass(frozen=True)
class Connection:
    """One relation to another subject page: the target document, and why it matters here."""

    path: str
    relation: str


@dataclass(frozen=True)
class Overview:
    """The document's current picture, in four optional slots.

    `definition` is one sentence saying what or who this is; `summary` is the state now;
    `introduction` is background, origin and why it matters; `connections` are links to other
    subject pages, each with its relation in one line. Nothing here carries a permanent
    identity — a rewrite replaces every block — which is exactly what makes wholesale rewrite
    safe, and exactly why the gate insists every block still points back into the ledger.
    """

    definition: str = ""
    summary: str = ""
    introduction: str = ""
    connections: tuple[Connection, ...] = ()

    def is_empty(self) -> bool:
        return not (
            self.definition.strip()
            or self.summary.strip()
            or self.introduction.strip()
            or self.connections
        )


def overview_span(body: str) -> tuple[int, int] | None:
    """The region's line span `[start, end)` in `body`, or None when it has none.

    `end` consumes one trailing blank line so removing the region cannot leave a double
    blank behind — and so re-inserting a region writes the document back byte-for-byte.
    """
    lines = body.split("\n")
    start = -1
    for index, line in enumerate(lines):
        if _OVERVIEW_OPEN_RE.match(line):
            start = index
            break
    if start < 0:
        return None
    for index in range(start + 1, len(lines)):
        if _OVERVIEW_CLOSE_RE.match(lines[index]):
            end = index + 1
            if end < len(lines) and not lines[end].strip():
                end += 1
            return start, end
    return None


def overview_region(body: str) -> str:
    """The region's raw text (markers included), or `""` when the document has none."""
    span = overview_span(body)
    if span is None:
        return ""
    start, end = span
    lines = body.split("\n")[start:end]
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def strip_overview(body: str) -> str:
    """`body` with the overview region removed — the LEDGER, byte-for-byte."""
    span = overview_span(body)
    if span is None:
        return body
    start, end = span
    lines = body.split("\n")
    return "\n".join(lines[:start] + lines[end:])


def _slot_texts(region: str) -> dict[str, list[str]]:
    """{slot: its content lines}, keyed on the system markers alone."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in region.split("\n"):
        opener = _SLOT_OPEN_RE.match(line)
        if opener is not None:
            current = opener.group(1)
            out.setdefault(current, [])
            continue
        if _OVERVIEW_OPEN_RE.match(line) or _OVERVIEW_CLOSE_RE.match(line):
            current = None
            continue
        if current is not None:
            out[current].append(line)
    return out


def _slot_body(lines: list[str]) -> str:
    """A slot's content with its rendered heading and its anchor marks dropped."""
    kept = list(lines)
    while kept and not kept[0].strip():
        kept.pop(0)
    if kept and _HEADING_LINE_RE.match(kept[0]):
        kept.pop(0)
    text = "\n".join(kept)
    text = ANCHOR_MARK_RE.sub("", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip("\n").strip()


def parse_overview(body: str) -> tuple[Overview | None, str]:
    """Split `body` into its overview and its ledger.

    A document without the region parses as `(None, body)` — which every document written
    before the region existed does, unchanged and byte-for-byte.
    """
    region = overview_region(body)
    if not region:
        return None, body
    slots = _slot_texts(region)
    connections: list[Connection] = []
    for line in slots.get("connections", []):
        match = _CONNECTION_RE.match(ANCHOR_MARK_RE.sub("", line))
        if match is None:
            continue
        label = match.group("label").strip()
        target = label if label.endswith(".md") else match.group("href").strip()
        connections.append(
            Connection(path=target, relation=match.group("relation").strip())
        )
    return (
        Overview(
            definition=_slot_body(slots.get("definition", [])),
            summary=_slot_body(slots.get("summary", [])),
            introduction=_slot_body(slots.get("introduction", [])),
            connections=tuple(connections),
        ),
        strip_overview(body),
    )


def render_overview(overview: Overview, *, document_path: str = "") -> str:
    """Serialize an `Overview` into the region text (markers included, no anchors yet).

    Anchors are assigned afterwards by the write tool, exactly as they are for any other
    canonical block — `render_overview` produces prose and structure, never identity.

    Connection hrefs are rendered RELATIVE to `document_path`, which is what makes them
    ordinary canonical links: the gate's dead-link check and the knowledge graph read them
    with the same resolver as every other link in the repository.
    """
    lines = [OVERVIEW_OPEN]
    for slot in ("definition", "summary", "introduction"):
        text = str(getattr(overview, slot) or "").strip()
        if not text:
            continue
        lines.extend(
            ["", slot_marker(slot), f"### {prompt(f'overview.heading.{slot}')}", "", text]
        )
    if overview.connections:
        lines.extend(
            [
                "",
                slot_marker("connections"),
                f"### {prompt('overview.heading.connections')}",
                "",
            ]
        )
        for connection in overview.connections:
            target = str(connection.path or "").strip()
            href = _render_relative(document_path, target) if document_path else target
            lines.append(
                prompt(
                    "overview.connection_line",
                    path=target,
                    href=href,
                    relation=str(connection.relation or "").strip(),
                )
            )
    lines.extend(["", OVERVIEW_CLOSE])
    return "\n".join(lines)


def remove_overview_region(body: str) -> str:
    """Cut the overview region out of `body` — markers and all — leaving the ledger alone.

    The one shape "rewrite the picture with nothing" can honestly mean: this subject no
    longer has a current picture worth stating, and the document goes back to being its
    claims. Absent a region, the body is returned unchanged.
    """
    span = overview_span(body)
    if span is None:
        return body
    start, end = span
    lines = body.split("\n")
    return "\n".join(lines[:start] + lines[end:])


def set_overview_region(body: str, region: str) -> str:
    """Replace `body`'s overview region with `region`, creating it when absent.

    Absent, the region is inserted directly under the document's `# ` title (a head belongs
    below the name of the thing it heads) — or at the very top when the document has no
    title. The ledger below is not touched by either path: this only ever splices lines
    around a span the system's own markers delimit.
    """
    lines = body.split("\n")
    span = overview_span(body)
    block = region.rstrip("\n").split("\n")
    if span is not None:
        start, end = span
        tail = lines[end:]
        glue = [""] if tail and tail[0].strip() else []
        return "\n".join(lines[:start] + block + glue + tail)
    at = 0
    for index, line in enumerate(lines):
        if line.startswith("# ") and line[2:].strip():
            at = index + 1
            break
    while at < len(lines) and not lines[at].strip():
        at += 1
    head = lines[:at]
    tail = lines[at:]
    glue = [""] if head and head[-1].strip() else []
    return "\n".join(head + glue + block + ([""] if tail else []) + tail)


#: The section-path prefix every overview claim is projected under. It is a machine label,
#: not display prose — the slot headings above are the display prose — so it stays English
#: in every language pack, exactly like a field name.
OVERVIEW_LABEL = "overview"


def overview_slot_by_line(body: str) -> dict[int, str]:
    """{line index: the overview slot that line belongs to} for lines inside the region.

    The projection reads a claim's slot from this rather than from the rendered heading
    above it: the marker is the system's, the heading is the deployment's, and only one of
    the two means the same thing in every language pack.
    """
    span = overview_span(body)
    if span is None:
        return {}
    start, end = span
    lines = body.split("\n")
    out: dict[int, str] = {}
    slot: str | None = None
    for index in range(start, min(end, len(lines))):
        opener = _SLOT_OPEN_RE.match(lines[index])
        if opener is not None:
            slot = opener.group(1)
            continue
        if _OVERVIEW_OPEN_RE.match(lines[index]) or _OVERVIEW_CLOSE_RE.match(lines[index]):
            slot = None
            continue
        if slot is not None:
            out[index] = slot
    return out
