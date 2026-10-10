"""The service store's atomic L0-and-jobs boundary; no middleware types cross it."""

from dataclasses import dataclass, field
from typing import Any

from pneuma_knowledge_core.domain.ids import SourceId


@dataclass(frozen=True)
class SourceImportJob:
    source_id: SourceId
    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class SourceImportReceipt:
    source_id: SourceId
    deduplicated: bool
    intake_plan: dict[str, Any] | None


@dataclass
class SourceImportBatchReceipt:
    sources: list[SourceImportReceipt] = field(default_factory=list)
    jobs: list[tuple[str, str]] = field(default_factory=list)  # (kind, job_id)
