"""Source domain models: raw → normalized, with structure map for L0 addressing.

A source's four parallel views (architecture.md §3) all address into the block
sequence produced here. The StructureMap backs L0 structural fetch (章/节/¶ span):
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
# the owner/other distinction the compile skill reasons over (§9 说话人与归属), instead
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
]


class ConversationTurn(BaseModel):
    speaker: str
    text: str
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
    # adapter/skill selection for first-party data (需求：第一方数据针对性处理).
    origin: SourceOrigin = "upload"
    title: str
    mime: str
    checksum: str
    created_at: datetime
    meta: dict[str, Any] = Field(default_factory=dict)
    # IntakePlan proposal, persisted for audit (§4: "IntakePlan 是提案 … 落库留审计").
    # Held as a plain dict to keep the domain source module free of an intake import
    # cycle; the plan's schema lives in domain/intake.py.
    intake_plan: dict[str, Any] | None = None


class NormalizedBlock(BaseModel):
    index: int
    text: str
    section_path: list[str] = Field(default_factory=list)


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
