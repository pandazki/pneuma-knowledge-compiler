"""Mechanical reader metadata shared by the CLI's evidence and source faces."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Any

from pneuma_knowledge_core.domain.authorship import block_authorship
from pneuma_knowledge_core.domain.canonical import Citation, format_citation_span
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import NormalizedSource, RawSource
from pneuma_knowledge_core.ingest.source_types import agent_session_owner_label
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.citation_alias import SessionAliaser
from pneuma_knowledge_core.recall.fast import (
    FastEvidence,
    _render_window_section,
    render_claims,
    render_episode_summaries,
)


def one_line(value: Any) -> str:
    return " ".join(str(value).split())


def span_label(start: int, end: int) -> str:
    return format_citation_span("", start, end).strip()


def recorded_day(value: Any) -> str | None:
    """A recorded day or instant's own calendar day; no imported-date fallback."""
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        try:
            return datetime.fromisoformat(str(value)).date().isoformat()
        except ValueError:
            return None


def source_date(raw: RawSource) -> tuple[str, bool]:
    """The sortable calendar day and whether it comes from the import timestamp."""
    occurred = recorded_day(raw.occurred_on())
    if occurred:
        return occurred, False
    instant = raw.created_at
    day = instant.replace(tzinfo=instant.tzinfo or timezone.utc).astimezone(
        timezone.utc
    ).date().isoformat()
    return day, True


def source_day(raw: RawSource) -> str:
    """Prefer occurrence; explicitly label the UTC import day when it is all we know."""
    day, imported = source_date(raw)
    return prompt("steward.read.imported", day=day) if imported else day


def block_days(raw: RawSource) -> dict[int, str]:
    envelope, key = {
        "agent_session": ("turns", "at"),
        "owner_dialogue": ("turns", "said_at"),
        "im": ("messages", "sent_at"),
        "meeting": ("segments", "started_at"),
    }.get(raw.kind, ("", ""))
    return {index: day for index, block in enumerate(raw.meta.get(envelope, []))
            if (day := recorded_day(block.get(key))) is not None}


def block_speakers(raw: RawSource, owner_name: str | None = None) -> dict[int, str]:
    """Resolve the structure command's authorship rows against their declared identities.

    Documents and emails deliberately supply no conversational speaker labels. Nothing is
    inferred from block text, source titles, tenant ids or an agent's prose about the Owner.
    """
    if raw.kind not in {"agent_session", "owner_dialogue", "im", "meeting"}:
        return {}
    meta = raw.meta
    people: dict[str, str] = {}
    turns: list[dict] = []
    identity_key = ""
    if raw.kind == "meeting":
        people = {p["participant_id"]: p.get("display_name") or p["participant_id"]
                  for p in meta.get("participants", [])}
        turns, identity_key = meta.get("segments", []), "speaker_id"
    elif raw.kind == "im":
        people = {p["user_id"]: p.get("display_name") or p["user_id"]
                  for p in meta.get("users", [])}
        turns, identity_key = meta.get("messages", []), "sender_id"
    speakers: dict[int, str] = {}
    for row in block_authorship(raw):
        index, role = row["index"], row["role"]
        declared = people.get(turns[index].get(identity_key)) if turns else None
        if role == "owner":
            # The contract's own name first; a source ingested before the contract carried one
            # falls back to the library owner's profile name, since the role IS the owner.
            name = agent_session_owner_label(meta.get("owner_name") or declared or owner_name)
        elif role == "agent":
            name = (meta.get("agent") or {}).get("name")
        elif role == "steward":
            name = prompt("ingest.steward_label")
        else:
            name = declared
        if name and (label := one_line(name)):
            speakers[index] = label
    return speakers


class SourceSignals:
    """Read each cited source once within this tenant and command invocation."""

    def __init__(self, store: Any, user_id: UserId, owner_name: str | None = None) -> None:
        self.store, self.user_id, self.owner_name = store, user_id, owner_name
        self.sources: dict[str, NormalizedSource | None] = {}
        self.speakers: dict[str, dict[int, str]] = {}

    @classmethod
    async def for_runtime(cls, store: Any, user_id: UserId) -> "SourceSignals":
        """Signals with the owner's profile name as the fallback speaker label for owner
        turns of sources that predate `owner_name` on the contract."""
        name = None
        lookup = getattr(store, "get_user_profile", None)
        if lookup is not None:
            try:
                profile = await lookup(user_id)
            except Exception:  # a store without profiles is still a readable library
                profile = None
            if profile is not None:
                value = profile.get("display_name") if isinstance(profile, dict) else getattr(profile, "display_name", None)
                name = str(value or "").strip() or None
        return cls(store, user_id, name)

    async def get(self, source_id: str) -> NormalizedSource | None:
        if source_id not in self.sources:
            try:
                source = await self.store.get(self.user_id, SourceId(source_id))
            except KeyError:
                source = None
            if source is not None and (
                str(source.raw.user_id) != str(self.user_id)
                or str(source.raw.source_id) != source_id
            ):
                raise ValueError("source identity mismatch")
            self.sources[source_id] = source
            self.speakers[source_id] = block_speakers(source.raw, self.owner_name) if source else {}
        return self.sources[source_id]

    async def summary(self, source_id: str) -> dict[str, Any]:
        source = await self.get(source_id)
        if source is None:
            return {"source_id": source_id, "kind": None, "date": None, "title": None}
        raw = source.raw
        row = {"source_id": source_id, "kind": raw.kind.replace("_", "-"),
               "date": source_day(raw), "title": raw.title}
        agent = (raw.meta.get("agent") or {}).get("name")
        if raw.kind == "agent_session" and agent:
            row["agent"] = agent
        return row

    def latest_day(self, source_ids: Iterable[str]) -> str | None:
        """Choose among loaded sources by date, independent of the catalog's label."""
        raw = max(
            (source.raw for sid in source_ids if (source := self.sources.get(sid)) is not None),
            key=lambda raw: source_date(raw)[0], default=None,
        )
        return source_day(raw) if raw is not None else None

    async def span(self, source_id: str, start: int, end: int) -> dict[str, Any]:
        source = await self.get(source_id)
        speakers = self.speakers[source_id]
        days = block_days(source.raw) if source else {}
        rows = []
        cursor = start
        # Bound work to stored blocks, even for a malformed historical citation. Missing
        # runs remain explicit without allocating a row per nonexistent block.
        for index in sorted({b.index for b in source.blocks} if source else set()):
            if not start <= index <= end:
                continue
            if index > cursor:
                rows.append({"span": span_label(cursor, index - 1),
                             "speaker": prompt("steward.read.unknown")})
            rows.append({"span": span_label(index, index),
                         "speaker": speakers.get(index, prompt("steward.read.unknown")),
                         **({"date": days[index]} if index in days else {})})
            cursor = index + 1
        if cursor <= end:
            rows.append({"span": span_label(cursor, end),
                         "speaker": prompt("steward.read.unknown")})
        row: dict[str, Any] = {"span": span_label(start, end), "speakers": rows}
        names = {block["speaker"] for block in rows}
        if len(names) == 1:
            row["speaker"] = next(iter(names))
        return row

    async def index(
        self, citations: Iterable[Citation], *, handles: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """The shared cited-source rows for canonical and recall, deduped by exact span."""
        cited: dict[str, set[tuple[int, int]]] = {
            sid: set() for sid in (handles or {}).values()
        }
        for citation in citations:
            sid = str(citation.source_id)
            sid = (handles or {}).get(sid, sid)
            cited.setdefault(sid, set()).add((citation.block_start, citation.block_end))
        reverse = {sid: handle for handle, sid in (handles or {}).items()}
        return [
            {**({"handle": reverse[sid]} if sid in reverse else {}),
             **await self.summary(sid),
             "cited": [await self.span(sid, a, b) for a, b in sorted(spans)]}
            for sid, spans in cited.items()
        ]


def span_speaker_text(span: dict[str, Any]) -> str:
    return " · ".join(
        f"{row['span']} {row['speaker']}" + (f" {row['date']}" if row.get("date") else "")
        for row in span["speakers"]
    )


def source_index_lines(sources: list[dict[str, Any]]) -> list[str]:
    lines = [prompt("steward.read.sources")]
    for source in sources:
        kind = source["kind"] or prompt("steward.read.unknown")
        if source.get("agent"):
            kind += f" ({one_line(source['agent'])})"
        handle = f"{source['handle']} = " if "handle" in source else ""
        lines.append(
            f"  {handle}{source['source_id']} · {kind} · "
            f"{source['date'] or prompt('steward.read.unknown')} · "
            + one_line(source['title'] or prompt('steward.read.unknown'))
        )
        cited = [span_speaker_text(span) for span in source.get("cited", [])]
        if cited:
            lines.append("    " + prompt("steward.read.cited", spans=" · ".join(cited)))
    return lines


def evidence_tally(evidence: FastEvidence) -> dict[str, Any]:
    pages: dict[str, int] = {}
    for claim in ranked_items(evidence.used_claims)[0]:
        pages[claim.document_path] = pages.get(claim.document_path, 0) + 1
    return {
        "claims": len(evidence.used_claims),
        "pages": [{"path": path, "claims": count} for path, count in pages.items()],
        "windows": len(evidence.used_windows),
        "window_sources": len({str(window.source_id) for window in evidence.used_windows}),
        "episodes": len(evidence.used_episode_summaries),
    }


def ranked_items(items) -> tuple[list, bool]:
    """Only finite, positive retrieval scores establish an order; defaults do not."""
    ranked = bool(items) and all(
        isinstance(getattr(item, "score", None), (int, float))
        and math.isfinite(item.score) and item.score > 0 for item in items
    )
    return (sorted(items, key=lambda item: -item.score) if ranked else list(items), ranked)


def evidence_lines(evidence: FastEvidence, tally: dict[str, Any]) -> tuple[list[str], list[str]]:
    """A repeatable header and the retained reader body, over the lane's exact evidence."""
    aliaser = SessionAliaser()
    for _handle, sid in evidence.handles.items():
        aliaser.alias(f"[cite: {sid} ¶0]")
    sections = dict(evidence.sections)
    ordering = []
    primary = []
    for number, (kind, items, render) in enumerate((
        ("claims", evidence.used_claims, render_claims),
        ("windows", evidence.used_windows, _render_window_section),
        ("episodes", evidence.used_episode_summaries, render_episode_summaries),
    ), 1):
        label = prompt(f"steward.read.section_{kind}")
        section = sections.get(kind, "").partition("\n")[2]
        ordered, ranked = ranked_items(items)
        # An annotated window may contain additional claims. Only reorder when this
        # renderer accounts for the entire section; otherwise preserve the lane's bytes.
        if ranked and aliaser.alias(render(list(items))).strip() == section.strip():
            section = aliaser.alias(render(ordered))
        else:
            ranked = False
        ordering.append(f"{label}: " + prompt(
            "steward.read.ranked" if ranked else "steward.read.lane_order"
        ))
        primary.extend([f"# {number} {label}", section, ""])
    when = evidence.as_of.replace(tzinfo=evidence.as_of.tzinfo or timezone.utc)
    header = [
        prompt("steward.read.evidence_for", query=one_line(evidence.question)),
        "as_of: " + when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        prompt("steward.read.tally", **{**tally, "pages": len(tally["pages"])}),
        prompt("steward.read.pages", pages=" · ".join(
            f"{page['path']} ({page['claims']})" for page in tally["pages"]
        ) or prompt("steward.read.none")),
        " · ".join(ordering),
        prompt("steward.read.sections", sections=" · ".join(
            f"{n} {prompt('steward.read.section_' + kind)}"
            for n, kind in enumerate(("claims", "windows", "episodes", "map"), 1)
        )),
    ]
    lines = primary
    for kind, section in evidence.sections:
        if kind not in {"claims", "windows", "episodes", "map"}:
            lines.extend([section, ""])
    lines.extend([f"# 4 {prompt('steward.read.section_map')}", sections.get("map", ""), ""])
    return header, lines
