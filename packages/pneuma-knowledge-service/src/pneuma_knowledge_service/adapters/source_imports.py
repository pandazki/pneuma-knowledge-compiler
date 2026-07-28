"""Anti-corruption adapters for the four official source contracts.

These adapters only translate provider formats. The compiler consumes the strict
provider-neutral models from ``pneuma_knowledge_core.ingest.source_contracts``.
"""

from __future__ import annotations

import hashlib
import html
import json
import mailbox
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email import policy
from email.message import EmailMessage as StdEmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import yaml

from pneuma_knowledge_core.ingest.source_contracts import (
    DocumentLibrarySource,
    EmailAddress,
    EmailAttachment,
    EmailMessage,
    EmailSource,
    EmailThread,
    ImConversation,
    ImMessage,
    ImReaction,
    ImSource,
    ImUser,
    LibraryDocument,
    LibraryLink,
    MeetingParticipant,
    MeetingSegment,
    MeetingSource,
    SourceContract,
    parse_source_contract,
)


def _read_text(value: str | bytes | Path) -> str:
    if isinstance(value, Path):
        return value.read_text(encoding="utf-8-sig")
    if isinstance(value, bytes):
        return value.decode("utf-8-sig")
    return value


class CanonicalJsonSourceAdapter:
    """Mock/import adapter with exactly the same validation as real providers."""

    def load(self, payload: str | bytes | Path | dict[str, Any]) -> SourceContract:
        if isinstance(payload, dict):
            data: object = payload
        else:
            data = json.loads(_read_text(payload))
        return parse_source_contract(data)


_VTT_CUE_RE = re.compile(
    r"(?:(?P<id>[^\n]+)\n)?"
    r"(?P<start>\d{2,}:\d{2}:\d{2}\.\d{3})\s+-->\s+"
    r"(?P<end>\d{2,}:\d{2}:\d{2}\.\d{3})(?:[^\n]*)\n"
    r"(?P<text>.*?)(?=\n{2,}|\Z)",
    re.DOTALL,
)
_VTT_SPEAKER_RE = re.compile(r"^\s*([^:\n]{1,120}):\s*(.*)$", re.DOTALL)


def _vtt_offset(value: str) -> timedelta:
    hours, minutes, seconds = value.split(":")
    return timedelta(
        hours=int(hours), minutes=int(minutes), seconds=float(seconds)
    )


class ZoomVttAdapter:
    """Zoom recording metadata + WebVTT transcript → ``meeting/v1``."""

    def load(
        self,
        metadata: dict[str, Any] | str | bytes | Path,
        transcript: str | bytes | Path,
        *,
        owner_emails: set[str] | None = None,
        owner_participant_ids: set[str] | None = None,
    ) -> MeetingSource:
        if not isinstance(metadata, dict):
            metadata = json.loads(_read_text(metadata))
        started_at = datetime.fromisoformat(
            str(metadata["start_time"]).replace("Z", "+00:00")
        )
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("Zoom start_time must include a timezone offset")

        participants: list[MeetingParticipant] = []
        by_name: dict[str, MeetingParticipant] = {}
        for index, item in enumerate(metadata.get("participants", []), start=1):
            name = str(
                item.get("name")
                or item.get("user_name")
                or item.get("display_name")
                or f"Participant {index}"
            ).strip()
            participant = MeetingParticipant(
                participant_id=str(
                    item.get("id") or item.get("user_id") or f"participant-{index}"
                ),
                display_name=name,
                email=item.get("email"),
            )
            participants.append(participant)
            by_name[name.casefold()] = participant

        segments: list[MeetingSegment] = []
        for index, match in enumerate(
            _VTT_CUE_RE.finditer(_read_text(transcript).replace("\r\n", "\n")),
            start=1,
        ):
            cue_text = " ".join(
                line.strip() for line in match.group("text").splitlines() if line.strip()
            )
            speaker_match = _VTT_SPEAKER_RE.match(cue_text)
            if speaker_match:
                speaker_name = html.unescape(speaker_match.group(1).strip())
                text = html.unescape(speaker_match.group(2).strip())
            else:
                speaker_name = "Unknown speaker"
                text = html.unescape(cue_text.strip())
            participant = by_name.get(speaker_name.casefold())
            if participant is None:
                suffix = hashlib.sha256(speaker_name.encode("utf-8")).hexdigest()[:10]
                participant = MeetingParticipant(
                    participant_id=f"speaker-{suffix}", display_name=speaker_name
                )
                participants.append(participant)
                by_name[speaker_name.casefold()] = participant
            segments.append(
                MeetingSegment(
                    segment_id=str(match.group("id") or f"segment-{index}").strip(),
                    speaker_id=participant.participant_id,
                    started_at=started_at + _vtt_offset(match.group("start")),
                    ended_at=started_at + _vtt_offset(match.group("end")),
                    text=text,
                )
            )
        if not segments:
            raise ValueError("Zoom transcript contains no WebVTT cues")

        owner_emails = {item.casefold() for item in (owner_emails or set())}
        owner_ids = set(owner_participant_ids or set())
        owner_ids.update(
            participant.participant_id
            for participant in participants
            if participant.email and participant.email.casefold() in owner_emails
        )
        duration = metadata.get("duration")
        ended_at = (
            started_at + timedelta(minutes=float(duration))
            if duration is not None
            else max(item.ended_at or item.started_at for item in segments)
        )
        return MeetingSource(
            schema="pneuma.source.meeting/v1",
            provider="zoom",
            meeting_id=str(metadata.get("uuid") or metadata.get("id")),
            title=str(metadata.get("topic") or metadata.get("title") or "Zoom meeting"),
            started_at=started_at,
            ended_at=ended_at,
            timezone=metadata.get("timezone"),
            owner_participant_ids=sorted(owner_ids),
            participants=participants,
            agenda=list(metadata.get("agenda") or []),
            segments=segments,
            metadata={
                key: metadata[key]
                for key in ("host_id", "type")
                if key in metadata
            },
        )


_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_WIKILINK_RE = re.compile(r"(?P<embed>!)?\[\[(?P<body>[^\]]+)\]\]")
_INLINE_TAG_RE = re.compile(r"(?<![\w/])#([\w\u3400-\u9fff][\w/\-\u3400-\u9fff]*)")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _frontmatter_and_body(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text.replace("\r\n", "\n").replace("\r", "\n"))
    if match is None:
        return {}, text
    loaded = yaml.safe_load(match.group(1))
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ValueError("Obsidian YAML frontmatter must be an object")
    return loaded, text[match.end() :]


def _frontmatter_tags(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        candidates = [str(item).strip() for item in value]
    else:
        raise ValueError("Obsidian frontmatter tags must be a string or list")
    return [item.removeprefix("#") for item in candidates if item]


class ObsidianVaultAdapter:
    """Visible Markdown files in an Obsidian vault → ``document-library/v1``."""

    def load(
        self, vault: Path, *, library_id: str | None = None, title: str | None = None
    ) -> DocumentLibrarySource:
        vault = Path(vault)
        if not vault.is_dir():
            raise ValueError(f"Obsidian vault is not a directory: {vault}")
        vault_root = vault.resolve()
        documents: list[LibraryDocument] = []
        for candidate in sorted(vault.rglob("*"), key=lambda item: item.as_posix()):
            if not candidate.is_file() or candidate.suffix.casefold() != ".md":
                continue
            relative = candidate.relative_to(vault)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if candidate.is_symlink() or any(
                parent.is_symlink()
                for parent in candidate.parents
                if parent != vault.parent
            ):
                continue
            try:
                candidate.resolve().relative_to(vault_root)
            except ValueError:
                continue

            raw_text = candidate.read_text(encoding="utf-8-sig")
            frontmatter, content = _frontmatter_and_body(raw_text)
            links: list[LibraryLink] = []
            for match in _WIKILINK_RE.finditer(content):
                target, separator, label = match.group("body").partition("|")
                links.append(
                    LibraryLink(
                        target=target.strip(),
                        label=label.strip() if separator and label.strip() else None,
                        embedded=bool(match.group("embed")),
                    )
                )
            tags = _frontmatter_tags(frontmatter.get("tags"))
            tags.extend(_INLINE_TAG_RE.findall(content))
            tags = list(dict.fromkeys(tags))
            heading = _H1_RE.search(content)
            note_title = str(
                frontmatter.get("title")
                or (heading.group(1).strip() if heading else candidate.stem)
            )
            stat = candidate.stat()
            path = relative.as_posix()
            documents.append(
                LibraryDocument(
                    document_id=hashlib.sha256(path.encode("utf-8")).hexdigest()[:24],
                    path=path,
                    title=note_title,
                    content=content.strip(),
                    frontmatter=frontmatter,
                    tags=tags,
                    links=links,
                    created_at=datetime.fromtimestamp(stat.st_ctime, timezone.utc),
                    modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                    metadata={},
                )
            )
        if not documents:
            raise ValueError("Obsidian vault contains no visible Markdown notes")
        return DocumentLibrarySource(
            schema="pneuma.source.document-library/v1",
            provider="obsidian",
            library_id=library_id or hashlib.sha256(str(vault_root).encode()).hexdigest()[:24],
            title=title or vault.name,
            documents=documents,
            metadata={"note_count": len(documents)},
        )


class _SlackArchive:
    def __init__(self, path: Path):
        self.path = path
        self.zip: zipfile.ZipFile | None = None
        if path.is_file() and zipfile.is_zipfile(path):
            self.zip = zipfile.ZipFile(path)
            for name in self.zip.namelist():
                pure = PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts:
                    raise ValueError(f"unsafe Slack ZIP member: {name}")
        elif not path.is_dir():
            raise ValueError(f"Slack export is not a directory or ZIP: {path}")

    def names(self) -> list[str]:
        if self.zip is not None:
            return [name for name in self.zip.namelist() if not name.endswith("/")]
        return [
            item.relative_to(self.path).as_posix()
            for item in self.path.rglob("*")
            if item.is_file()
        ]

    def json(self, name: str) -> Any:
        if self.zip is not None:
            with self.zip.open(name) as handle:
                return json.load(handle)
        return json.loads((self.path / name).read_text(encoding="utf-8-sig"))

    def close(self) -> None:
        if self.zip is not None:
            self.zip.close()


def _slack_time(value: str) -> datetime:
    return datetime.fromtimestamp(float(Decimal(value)), timezone.utc)


class SlackExportAdapter:
    """Slack JSON export directory/ZIP → ``im/v1``."""

    def load(self, export: Path, *, owner_user_ids: set[str]) -> ImSource:
        archive = _SlackArchive(Path(export))
        try:
            names = set(archive.names())
            if "users.json" not in names:
                raise ValueError("Slack export is missing users.json")
            users_by_id: dict[str, ImUser] = {}
            for item in archive.json("users.json"):
                profile = item.get("profile") or {}
                user_id = str(item["id"])
                users_by_id[user_id] = ImUser(
                    user_id=user_id,
                    display_name=str(
                        profile.get("display_name")
                        or item.get("real_name")
                        or profile.get("real_name")
                        or item.get("name")
                        or user_id
                    ),
                    email=profile.get("email"),
                    is_bot=bool(item.get("is_bot") or item.get("is_app_user")),
                )

            manifests: list[tuple[str, str]] = [
                ("channels.json", "channel"),
                ("groups.json", "channel"),
                ("dms.json", "dm"),
                ("mpims.json", "group_dm"),
            ]
            conversations: list[ImConversation] = []
            for manifest_name, kind in manifests:
                if manifest_name not in names:
                    continue
                for record in archive.json(manifest_name):
                    conversation_id = str(record["id"])
                    folder_candidates = [
                        str(record.get("name") or ""),
                        conversation_id,
                    ]
                    prefix = next(
                        (
                            f"{folder}/"
                            for folder in folder_candidates
                            if folder
                            and any(name.startswith(f"{folder}/") for name in names)
                        ),
                        None,
                    )
                    if prefix is None:
                        continue
                    raw_messages: list[dict[str, Any]] = []
                    for name in sorted(
                        item
                        for item in names
                        if item.startswith(prefix) and item.endswith(".json")
                    ):
                        loaded = archive.json(name)
                        if isinstance(loaded, list):
                            raw_messages.extend(loaded)

                    messages: list[ImMessage] = []
                    for item in raw_messages:
                        if item.get("type", "message") != "message":
                            continue
                        sender_id = str(
                            item.get("user")
                            or item.get("bot_id")
                            or item.get("username")
                            or "unknown"
                        )
                        if sender_id not in users_by_id:
                            users_by_id[sender_id] = ImUser(
                                user_id=sender_id,
                                display_name=str(
                                    item.get("username") or item.get("bot_profile", {}).get("name")
                                    or sender_id
                                ),
                                is_bot=bool(item.get("bot_id") or item.get("bot_profile")),
                            )
                        ts = str(item.get("ts") or item.get("event_ts") or "")
                        if not ts:
                            raise ValueError(
                                f"Slack message in {conversation_id} is missing ts"
                            )
                        edited = item.get("edited") or {}
                        messages.append(
                            ImMessage(
                                message_id=str(item.get("client_msg_id") or ts),
                                sender_id=sender_id,
                                sent_at=_slack_time(ts),
                                text=str(item.get("text") or ""),
                                thread_id=item.get("thread_ts"),
                                edited_at=(
                                    _slack_time(str(edited["ts"]))
                                    if edited.get("ts")
                                    else None
                                ),
                                reactions=[
                                    ImReaction(
                                        name=str(reaction["name"]),
                                        count=int(reaction.get("count") or 1),
                                    )
                                    for reaction in item.get("reactions", [])
                                ],
                                metadata={
                                    key: item[key]
                                    for key in ("subtype",)
                                    if key in item
                                },
                            )
                        )
                    if not messages:
                        continue
                    member_ids = [str(item) for item in record.get("members", [])]
                    for message in messages:
                        if message.sender_id not in member_ids:
                            member_ids.append(message.sender_id)
                    title = str(record.get("name") or "")
                    if not title:
                        peer_names = [
                            users_by_id[item].display_name
                            for item in member_ids
                            if item not in owner_user_ids and item in users_by_id
                        ]
                        title = ", ".join(peer_names) or conversation_id
                    conversations.append(
                        ImConversation(
                            conversation_id=conversation_id,
                            conversation_type=kind,
                            title=title,
                            member_ids=member_ids,
                            messages=sorted(
                                messages,
                                key=lambda item: (item.sent_at, item.message_id),
                            ),
                            metadata={
                                "purpose": (record.get("purpose") or {}).get("value")
                            }
                            if record.get("purpose")
                            else {},
                        )
                    )
            if not conversations:
                raise ValueError("Slack export contains no message histories")
            export_path = Path(export)
            return ImSource(
                schema="pneuma.source.im/v1",
                provider="slack",
                archive_id=hashlib.sha256(
                    str(export_path.resolve()).encode()
                ).hexdigest()[:24],
                owner_user_ids=sorted(owner_user_ids),
                users=sorted(users_by_id.values(), key=lambda item: item.user_id),
                conversations=conversations,
                metadata={"source_name": export_path.name},
            )
        finally:
            archive.close()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _html_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return "\n".join(parser.parts)


def _addresses(values: Iterable[str]) -> list[EmailAddress]:
    return [
        EmailAddress(address=address, display_name=name or None)
        for name, address in getaddresses(values)
        if address
    ]


def _message_text(message: StdEmailMessage) -> str:
    plain: list[str] = []
    rich: list[str] = []
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeDecodeError):
            payload = part.get_payload(decode=True) or b""
            content = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if content_type == "text/plain":
            plain.append(str(content).strip())
        else:
            rich.append(_html_text(str(content)))
    return "\n\n".join(item for item in (plain or rich) if item)


def _email_message(message: StdEmailMessage, fallback_id: str) -> EmailMessage:
    raw_date = message.get("Date")
    if not raw_date:
        raise ValueError(f"email {fallback_id} is missing Date")
    sent_at = parsedate_to_datetime(str(raw_date))
    if sent_at.tzinfo is None or sent_at.utcoffset() is None:
        raise ValueError(f"email {fallback_id} Date has no timezone")
    senders = _addresses([str(message.get("From", ""))])
    if not senders:
        raise ValueError(f"email {fallback_id} is missing a valid From address")
    attachments = []
    for part in message.iter_attachments():
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename() or "attachment"
        attachments.append(
            EmailAttachment(
                filename=str(filename),
                content_type=part.get_content_type(),
                size_bytes=len(payload),
                content_id=part.get("Content-ID"),
            )
        )
    references = str(message.get("References") or "").split()
    return EmailMessage(
        message_id=str(message.get("Message-ID") or fallback_id).strip(),
        sent_at=sent_at,
        from_=senders[0],
        to=_addresses([str(message.get("To", ""))]),
        cc=_addresses([str(message.get("Cc", ""))]),
        subject=str(message.get("Subject") or ""),
        text=_message_text(message),
        in_reply_to=(
            str(message.get("In-Reply-To")).strip()
            if message.get("In-Reply-To")
            else None
        ),
        references=references,
        attachments=attachments,
        metadata={},
    )


def _subject_key(value: str) -> str:
    return re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", value, flags=re.I).strip().casefold()


class Rfc822EmailAdapter:
    """RFC 5322 EML directory/file or mbox → ``email/v1``."""

    def load(self, path: Path, *, owner_addresses: set[str]) -> EmailSource:
        path = Path(path)
        parsed: list[EmailMessage] = []
        if path.is_dir():
            files = sorted(
                item
                for item in path.rglob("*")
                if item.is_file()
                and item.suffix.casefold() == ".eml"
                and not any(part.startswith(".") for part in item.relative_to(path).parts)
            )
            for index, item in enumerate(files, start=1):
                std = BytesParser(policy=policy.default).parsebytes(item.read_bytes())
                parsed.append(_email_message(std, f"<eml-{index}@pneuma.local>"))
        elif path.is_file() and path.suffix.casefold() == ".eml":
            std = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
            parsed.append(_email_message(std, "<eml-1@pneuma.local>"))
        elif path.is_file():
            box = mailbox.mbox(path, factory=None, create=False)
            try:
                for index, item in enumerate(box, start=1):
                    std = BytesParser(policy=policy.default).parsebytes(item.as_bytes())
                    parsed.append(_email_message(std, f"<mbox-{index}@pneuma.local>"))
            finally:
                box.close()
        else:
            raise ValueError(f"email archive does not exist: {path}")
        if not parsed:
            raise ValueError("email archive contains no messages")

        by_id = {item.message_id: item for item in parsed}
        parent: dict[str, str] = {item.message_id: item.message_id for item in parsed}

        def find(item: str) -> str:
            while parent[item] != item:
                parent[item] = parent[parent[item]]
                item = parent[item]
            return item

        def union(left: str, right: str) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for message in parsed:
            candidates = [
                candidate
                for candidate in [message.in_reply_to, *message.references]
                if candidate in by_id
            ]
            if candidates:
                union(candidates[-1], message.message_id)

        groups: dict[str, list[EmailMessage]] = defaultdict(list)
        for message in parsed:
            groups[find(message.message_id)].append(message)
        # When References are absent, normalized subject is the conservative fallback.
        subject_roots: dict[str, str] = {}
        for root in list(groups):
            key = _subject_key(groups[root][0].subject)
            if key and key in subject_roots:
                target = subject_roots[key]
                groups[target].extend(groups.pop(root))
            elif key:
                subject_roots[key] = root

        threads = []
        for root, messages in groups.items():
            ordered = sorted(messages, key=lambda item: (item.sent_at, item.message_id))
            threads.append(
                EmailThread(
                    thread_id=root,
                    subject=ordered[0].subject,
                    messages=ordered,
                    metadata={},
                )
            )
        return EmailSource(
            schema="pneuma.source.email/v1",
            provider="rfc822",
            archive_id=hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24],
            owner_addresses=sorted(owner_addresses),
            threads=sorted(threads, key=lambda item: item.messages[0].sent_at),
            metadata={"source_name": path.name},
        )
