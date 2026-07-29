"""Canonical document text (de)serialization.

A canonical document on disk is markdown with a YAML-style frontmatter fence. v1
frontmatter is a flat map of scalar strings (doc_id/type/slug + optional extras), so a
minimal deterministic serializer round-trips it without pulling a YAML dependency into
core (kept at pydantic + langchain-core). Keys are emitted sorted for byte-stability.

The document id key was once spelled `pneuma_id`. Canonical is the one non-rebuildable
layer (invariant I2), so already-committed documents keep that spelling forever and are
NOT rewritten by a history migration. Instead the read side folds the legacy key onto
`doc_id` (`normalize_frontmatter`, applied by `parse_document`) and the write side only
ever emits `doc_id` — so a legacy document migrates for free the next time its file is
serialized, and nothing downstream ever sees two spellings of one field.
"""

from __future__ import annotations

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
    for legacy_key in LEGACY_DOC_ID_KEYS:
        legacy_value = normalized.pop(legacy_key, None)
        if legacy_value is None:
            continue
        if not str(normalized.get(DOC_ID_KEY, "")).strip():
            normalized[DOC_ID_KEY] = legacy_value
    return normalized


def render_document(frontmatter: dict, body: str) -> str:
    """Serialize (frontmatter, body) to a frontmatter-fenced markdown file."""
    lines = [_FENCE]
    for key in sorted(frontmatter):
        lines.append(f"{key}: {frontmatter[key]}")
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
            frontmatter[key.strip()] = value.strip()
    if end < 0:
        return {}, text.strip("\n")
    body = "\n".join(lines[end + 1 :]).strip("\n")
    return normalize_frontmatter(frontmatter), body
