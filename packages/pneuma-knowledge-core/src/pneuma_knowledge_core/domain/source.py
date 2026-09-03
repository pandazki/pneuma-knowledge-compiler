"""Source domain models: raw → normalized, with structure map for L0 addressing.

A source's four parallel views (architecture.md §3) all address into the block
sequence produced here. The StructureMap backs L0 structural fetch (chapter/section/¶ span):
locator v1 forms are `{"section": [...]} | {"blocks": [start, end]}`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .ids import UserId, SourceId

# locator v1: a section path or an explicit half-open-free inclusive block range.
Locator = dict[str, Any]

# Who spoke a turn, relative to the knowledge owner. A structured stream may already
# diarize this (`self/*` vs `others/*`); typing it lets the context_stream adapter render
# the owner/other distinction the compile skill reasons over (§9, speaker and attribution),
# instead
# of leaving opaque diarization codes for the LLM to guess. `unknown` = un-diarized
# (a generic pasted transcript) → rendered by raw speaker string, no owner claim.
SpeakerRole = Literal["owner", "other", "unknown"]

# Provenance of a raw source. Official provider origins identify the adapter boundary;
# `mock` is canonical synthetic input; `upload` and `context_stream` remain only for the
# legacy generic endpoints. Origin is orthogonal to source kind and intake treatment.
SourceOrigin = Literal[
    "upload",
    "context_stream",  # legacy capture path; not an official stored-source default
    "zoom",
    "obsidian",
    "slack",
    "rfc822",
    "console",  # the surface the library's owner speaks to the steward through
    "mock",
]
SourceKind = Literal[
    "meeting",
    "document_library",
    "im",
    "email",
    "conversation",  # legacy API compatibility
    "document",
    "structured",
    # The owner's own statement about the library — a correction, an instruction, an
    # addition. An ordinary source in every respect; only its authorship is unusual.
    "owner_dialogue",
]


class ConversationTurn(BaseModel):
    speaker: str
    text: str
    # WHEN this turn happened, as an AWARE UTC instant. A naive value is accepted and
    # interpreted as UTC rather than rejected (existing callers post naive timestamps), and
    # a value carrying any other offset is honoured as the instant it denotes. The CALENDAR
    # DAY a turn belongs to is never read off this field directly — it is resolved through
    # the subject's TimeContext at the sectioning boundary (domain/time_context.py).
    at: datetime | None = None
    # Role relative to the owner. First-party context_stream sets this from diarization;
    # a generic conversation leaves it "unknown" (rendered by raw `speaker`).
    role: SpeakerRole = "unknown"
    # Stable within-source id for a distinct other speaker (e.g. the diarization channel
    # "others/2"), so the same interlocutor keeps one label across the transcript.
    speaker_id: str | None = None


class RawSource(BaseModel):
    source_id: SourceId
    user_id: UserId
    kind: SourceKind
    source_class: Literal["workstream", "reference"] = "workstream"
    # First-party vs uploaded provenance (defaults to upload for back-compat). Drives
    # adapter/skill selection for first-party data (requirement: type-specific handling).
    origin: SourceOrigin = "upload"
    title: str
    mime: str
    checksum: str
    created_at: datetime
    meta: dict[str, Any] = Field(default_factory=dict)
    # IntakePlan proposal, persisted for audit (§4: "the IntakePlan is a proposal … persisted
    # for audit").
    # Held as a plain dict to keep the domain source module free of an intake import
    # cycle; the plan's schema lives in domain/intake.py.
    intake_plan: dict[str, Any] | None = None
    # The archive mark that lives on L0 (docs/design/archive.md §2.2). None = live; a
    # timestamp = the Owner retired this material. It changes the SEARCH face and the
    # listing default only — every block is still here and L0 fetch by locator is still
    # unconditional (invariant I3).
    archived_at: datetime | None = None

    def retrieval_context_lines(self) -> list[str]:
        """Stable source-level context for retrieval.

        ``created_at`` is deliberately absent: it is the ingest wall clock, not when the
        material happened. Provider-neutral normalizers put the source's own occurrence
        day in ``meta.occurred_on`` when one is known.
        """

        lines = [f"[source title] {self.title}"] if self.title.strip() else []
        occurred_on = self.occurred_on()
        if occurred_on:
            lines.append(f"[source occurred_on] {occurred_on}")
        return lines

    def occurred_on(self) -> str:
        """The source's own occurrence label, never the ingest wall clock."""

        return str(self.meta.get("occurred_on") or "").strip()


class DerivedMediaText(BaseModel):
    """Searchable text derived from a media asset without replacing the asset."""

    kind: Literal["caption", "ocr"]
    text: str
    producer: str


class BlockImage(BaseModel):
    """An immutable L0 image aligned to the block covered by its citation."""

    image_id: str = Field(pattern=r"^[A-Za-z0-9._:-]+$")
    mime_type: Literal["image/jpeg", "image/png", "image/webp", "image/gif"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    storage_key: str = Field(min_length=1)
    derived: list[DerivedMediaText] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedBlock(BaseModel):
    index: int
    text: str
    section_path: list[str] = Field(default_factory=list)
    images: list[BlockImage] = Field(default_factory=list)

    def derived_media_index_lines(self) -> list[str]:
        """Labelled media-derived text aligned to this block's ordinary citation."""

        return [
            f"[image {image.image_id}; {derived.kind}; "
            f"producer={derived.producer}] {derived.text}"
            for image in self.images
            for derived in image.derived
        ]

    def index_text(self) -> str:
        """Textual L1 view: verbatim block plus labelled media representations."""

        return "\n".join([self.text, *self.derived_media_index_lines()])


class SectionSpan(BaseModel):
    """One section's inclusive block interval [start_block, end_block]."""

    path: list[str]
    start_block: int
    end_block: int


class StructureMap(BaseModel):
    """Section path → block interval mapping. Backs L0 structural addressing."""

    sections: list[SectionSpan] = Field(default_factory=list)

    def resolve(self, locator: Locator) -> tuple[int, int]:
        """Resolve a v1 locator to an inclusive block interval (start, end).

        `{"blocks": [start, end]}` passes through; `{"section": [...]}` looks up
        the matching section path. Raises KeyError/ValueError on unresolvable
        locators rather than guessing.
        """
        if "blocks" in locator:
            blocks = locator["blocks"]
            if len(blocks) != 2:
                raise ValueError(f"blocks locator needs [start, end], got {blocks!r}")
            start, end = int(blocks[0]), int(blocks[1])
            return (start, end)
        if "section" in locator:
            path = list(locator["section"])
            for span in self.sections:
                if span.path == path:
                    return (span.start_block, span.end_block)
            raise KeyError(f"section not found: {path!r}")
        raise ValueError(f"unrecognized locator: {locator!r}")


class NormalizedSource(BaseModel):
    raw: RawSource
    blocks: list[NormalizedBlock]
    structure: StructureMap
