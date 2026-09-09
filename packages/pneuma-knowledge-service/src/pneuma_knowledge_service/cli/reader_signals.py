"""Mechanical reader metadata shared by the CLI's evidence and source faces."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from pneuma_knowledge_core.domain.authorship import block_authorship
from pneuma_knowledge_core.domain.canonical import format_citation_span
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import NormalizedSource, RawSource
from pneuma_knowledge_core.ingest.source_types import agent_session_owner_label
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.fast import FastEvidence


def one_line(value: Any) -> str:
    return " ".join(str(value).split())


def span_label(start: int, end: int) -> str:
    return format_citation_span("", start, end).strip()


def source_day(raw: RawSource) -> str:
    """Prefer the recorded local occurrence day; ingestion timestamps fall back to UTC."""
    occurred = raw.occurred_on()
    if occurred:
        try:
            return date.fromisoformat(occurred).isoformat()
        except ValueError:
            # Older/custom sources may carry an instant instead of a calendar day.
            try:
                instant = datetime.fromisoformat(occurred)
            except ValueError:
                pass
            else:
                return instant.replace(tzinfo=instant.tzinfo or timezone.utc).astimezone(
                    timezone.utc
                ).date().isoformat()
    instant = raw.created_at
    return instant.replace(tzinfo=instant.tzinfo or timezone.utc).astimezone(
        timezone.utc
    ).date().isoformat()


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
        if name:
            speakers[index] = one_line(name)
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

    async def span(self, source_id: str, start: int, end: int) -> dict[str, Any]:
        await self.get(source_id)
        row: dict[str, Any] = {"span": span_label(start, end)}
        speakers = self.speakers[source_id]
        covered = [index for index in sorted(speakers) if start <= index <= end]
        names = list(dict.fromkeys(speakers[index] for index in covered))
        if names:
            # Work is bounded by stored authorship, including for an invalid historical
            # citation with an enormous end block. Missing roles never borrow a neighbour.
            if len(covered) < end - start + 1:
                names.append(prompt("steward.read.unknown"))
            row["speaker"] = ", ".join(names)
        return row


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
        cited = [f"{span['span']} {span['speaker']}" for span in source.get("cited", [])
                 if span.get("speaker")]
        if cited:
            lines.append("    " + prompt("steward.read.cited", spans=" · ".join(cited)))
    return lines


def evidence_tally(evidence: FastEvidence) -> dict[str, Any]:
    pages: dict[str, int] = {}
    for claim in evidence.used_claims:
        pages[claim.document_path] = pages.get(claim.document_path, 0) + 1
    return {
        "claims": len(evidence.used_claims),
        "pages": [{"path": path, "claims": count} for path, count in pages.items()],
        "windows": len(evidence.used_windows),
        "window_sources": len({str(window.source_id) for window in evidence.used_windows}),
        "episodes": len(evidence.used_episode_summaries),
    }


def evidence_lines(evidence: FastEvidence, tally: dict[str, Any]) -> list[str]:
    when = evidence.as_of.replace(tzinfo=evidence.as_of.tzinfo or timezone.utc)
    lines = [
        prompt("steward.read.evidence_for", query=one_line(evidence.question)),
        "as_of: " + when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        prompt("steward.read.tally", **{**tally, "pages": len(tally["pages"])}),
        prompt("steward.read.pages", pages=" · ".join(
            f"{page['path']} ({page['claims']})" for page in tally["pages"]
        ) or prompt("steward.read.none")),
        prompt("steward.read.sections"),
        "",
    ]
    sections = dict(evidence.sections)
    for number, (kind, header_key, count) in enumerate((
        ("claims", "recall.section.claims_header", tally["claims"]),
        ("windows", "recall.section.windows_header", tally["windows"]),
        ("episodes", "recall.section.episode_summaries_header", tally["episodes"]),
    ), 1):
        section = sections.get(kind, prompt(header_key, count=count))
        # The title and section body are the lane's own bytes, with only a reading number
        # inserted before the title; source text containing Markdown headings is untouched.
        lines.extend([f"# {number} {section.removeprefix('# ')}", ""])
    for kind, section in evidence.sections:
        if kind not in {"claims", "windows", "episodes", "map"}:
            lines.extend([section, ""])
    lines.extend([prompt("steward.read.map"), sections.get("map", ""), ""])
    return lines
