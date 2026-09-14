"""The transcript the verbatim check reads, and the check itself (ruling 13, story 2.5g).

The console's Steward view adds ONE mechanism a terminal session cannot have. Because the
bridge holds what the Owner typed, a statement the Steward records from that conversation can
be verified to be the Owner's own words rather than the Steward's summary of them: `pkc owner
say` in a bridged session refuses a text that is not a verbatim substring of an Owner turn.

Three things this deliberately is not:

* **not a kept record.** These rows are the CONVERSATION, and the conversation is the
  harness's, not the library's (§5.6). They are written before a turn reaches the harness,
  read by exactly one command, and deleted when the session ends or expires. Nothing else in
  the framework reads them, and nothing rebuilds from them.
* **not an authority.** The statement itself still enters as an `owner-dialogue/v1` source,
  cited and dated like every other. The check governs whose words got recorded, not whether
  the record is evidence.
* **not a normalizer of the Owner.** The comparison collapses runs of whitespace and nothing
  else. Case, punctuation, an em dash, a name's spelling — all of it is what the Owner said,
  and a check that "helpfully" ignored any of it would be accepting a paraphrase under
  another name.

An Owner turn may carry IMAGES, and the attachment note this module renders for them is the
framework's own sentence, not the Owner's. So it is recorded BESIDE the text and never inside
it: `append` takes the note as its own argument, `list` — the one thing the verbatim check
reads — returns the Owner's texts and nothing else, and `attachments` is the separate channel
a transcript view reads. Folding the note into the text would have made `[image: shot.png,
12608 bytes]` quotable as something the Owner said, which is the leak the harness-injected-
context ruling closes everywhere else.

The images themselves are validated here and written to disk by the session that owns the
scratch directory: this module decodes and bounds them (four at most, five MiB each after
decoding, four media types), and refuses anything else by name.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Protocol, runtime_checkable

from pneuma_knowledge_core.domain.ids import UserId

#: The variable the bridge sets on the harness it spawns, and the whole of how `pkc owner
#: say` knows it is inside a console session rather than a terminal one.
SESSION_ENV = "PNEUMA_KNOWLEDGE_STEWARD_SESSION"


def normalize(text: str) -> str:
    """Collapse runs of whitespace, and nothing else. The one normalization there is."""
    return " ".join((text or "").split())


def is_verbatim(text: str, turns: list[str]) -> bool:
    """Is `text` something the Owner actually typed in this session?

    A substring rather than an equality: the Owner says a paragraph and the statement the
    Steward records is one sentence of it, which is a quotation and not a paraphrase. Empty
    text is not a quotation of anything and is refused with everything else.
    """
    needle = normalize(text)
    if not needle:
        return False
    return any(needle in normalize(turn) for turn in turns)


#: How many images one turn may carry. A conversation is not an upload channel: four is the
#: most a person pastes into one message, and the fifth is refused by name rather than
#: silently dropped.
MAX_IMAGES = 4

#: How large one image may be AFTER decoding. The base64 payload on the wire is ~4/3 of this.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

#: The media types a turn may carry. Stated, not sniffed: a type this list does not name is
#: refused, so nothing decides for itself what a byte string is.
IMAGE_MIMES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif"}
)

#: The extension each media type is written under. The Owner's own filename never becomes a
#: path — it is kept only in the note — so a name like `../../.ssh/id_rsa` cannot escape the
#: session's scratch directory, because the session names the file itself.
IMAGE_SUFFIX: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

#: How much of the Owner's filename survives into the note. A frame is a glance.
NAME_CHARS = 120

_DATA_URL = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)(?P<params>;[^,]*)?,", re.ASCII)


class ImageRefused(ValueError):
    """One attachment this turn may not carry, with the reason stated."""


@dataclass(frozen=True)
class StewardImage:
    """One decoded attachment: what the Owner called it, what it is, and where it landed.

    `data` is the decoded bytes — the wire's base64 is not kept — and `path` is empty until
    the session writes the file into the scratch directory it owns.
    """

    name: str
    mime: str
    data: bytes
    path: str = ""

    @property
    def note(self) -> str:
        """The bounded sentence the transcript records BESIDE the Owner's text."""
        return f"[image: {self.name}, {len(self.data)} bytes]"

    def at(self, path: str) -> "StewardImage":
        """The same image, now on disk at `path`."""
        return replace(self, path=path)

    def filename(self, index: int) -> str:
        """What the session writes it as: a name this framework chose, never the Owner's."""
        return f"image-{index}{IMAGE_SUFFIX.get(self.mime, '.bin')}"


def _clean_name(raw: Any, index: int) -> str:
    """The Owner's filename, flattened to one bounded line. Never used as a path."""
    name = normalize(str(raw or ""))[:NAME_CHARS]
    return name or f"image-{index}"


def decode_image(payload: Any, index: int = 0) -> StewardImage:
    """One `{name, mime, data_url}` object, decoded and bounded — or refused by name."""
    if not isinstance(payload, dict):
        raise ImageRefused("an image must be an object with name, mime and data_url")
    mime = str(payload.get("mime") or "").strip().lower()
    if mime not in IMAGE_MIMES:
        raise ImageRefused(
            f"unsupported image type {mime or '(none)'}; "
            f"this turn takes {', '.join(sorted(IMAGE_MIMES))}"
        )
    data_url = str(payload.get("data_url") or "")
    match = _DATA_URL.match(data_url)
    if match is None:
        raise ImageRefused("data_url must start with data:<mime>;base64,")
    if match.group("mime").lower() != mime:
        raise ImageRefused(
            f"data_url says {match.group('mime')} but the image says {mime}"
        )
    if "base64" not in (match.group("params") or ""):
        raise ImageRefused("data_url must be base64-encoded")
    encoded = data_url[match.end() :]
    # A base64 payload more than 4/3 of the limit cannot decode under it, and refusing it
    # before decoding is what keeps a 60 MiB string from being materialised at all.
    if len(encoded) > (MAX_IMAGE_BYTES // 3 + 1) * 4 + 8:
        raise ImageRefused(f"image is larger than {MAX_IMAGE_BYTES} bytes")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageRefused(f"data_url is not valid base64: {exc}") from exc
    if not data:
        raise ImageRefused("an image with no bytes is not an image")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageRefused(
            f"image is {len(data)} bytes, over the {MAX_IMAGE_BYTES} byte limit"
        )
    return StewardImage(name=_clean_name(payload.get("name"), index), mime=mime, data=data)


def decode_images(payloads: Any) -> list[StewardImage]:
    """Every image of one turn, decoded and bounded. Refuses rather than truncates."""
    if payloads is None:
        return []
    if not isinstance(payloads, (list, tuple)):
        raise ImageRefused("images must be a list")
    if len(payloads) > MAX_IMAGES:
        raise ImageRefused(f"a turn carries at most {MAX_IMAGES} images, not {len(payloads)}")
    return [decode_image(payload, index) for index, payload in enumerate(payloads)]


def attachment_note(images: Iterable[StewardImage]) -> str:
    """The whole turn's attachment note: one bounded line per image, or nothing."""
    return " ".join(image.note for image in images)


@runtime_checkable
class StewardTurnStore(Protocol):
    """Where a session's Owner turns live while the session does."""

    async def append(
        self, user_id: UserId, session_id: str, text: str, *, seq: int | None = None
    ) -> int:
        """Record one Owner turn and return its sequence number.

        The text is the Owner's own, and only the Owner's own: an attachment note is not
        written here, because every row of this store is quotable by the verbatim check.
        """

    async def list(self, user_id: UserId, session_id: str) -> list[str]:
        """Every Owner turn of this session, in the order they were said."""

    async def clear(self, user_id: UserId, session_id: str) -> None:
        """The session is over; the transcript goes with it."""


@dataclass
class InMemoryStewardTurnStore:
    """The keyless double, and the in-memory half of the real thing.

    The session holds one of these BESIDE the Postgres store: the check must not fail because
    a database blinked, and a transcript that outlives the process it belongs to would be a
    record, which this is not.
    """

    turns: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    #: The attachment notes, one per turn, in the same order — a SEPARATE list, because a
    #: sentence this framework wrote must never be readable as one the Owner said.
    notes: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    async def append(
        self,
        user_id: UserId,
        session_id: str,
        text: str,
        *,
        seq: int | None = None,
        note: str = "",
    ) -> int:
        key = (str(user_id), session_id)
        rows = self.turns.setdefault(key, [])
        rows.append(text)
        self.notes.setdefault(key, []).append(note)
        return len(rows)

    async def list(self, user_id: UserId, session_id: str) -> list[str]:
        return list(self.turns.get((str(user_id), session_id), ()))

    async def attachments(self, user_id: UserId, session_id: str) -> list[str]:
        """The attachment note of each turn, in the order the turns were said."""
        return list(self.notes.get((str(user_id), session_id), ()))

    async def clear(self, user_id: UserId, session_id: str) -> None:
        key = (str(user_id), session_id)
        self.turns.pop(key, None)
        self.notes.pop(key, None)


@dataclass
class PairedStewardTurnStore:
    """Both halves at once: the durable one, and the in-memory double beside it.

    A write goes to memory first and then to Postgres; a read prefers whichever has rows.
    That order is the point — the row must be there before the harness sees the turn, and a
    database that is briefly unreachable must not turn the Owner's own sentence into a
    refusal.
    """

    memory: InMemoryStewardTurnStore
    durable: Any | None = None

    async def append(
        self, user_id: UserId, session_id: str, text: str, *, note: str = ""
    ) -> int:
        """The Owner's text to both halves; the attachment note to the memory half alone.

        The durable store holds exactly what it held before this turn could carry images —
        the Owner's words — so the verbatim check reads the same rows whichever half answers
        it, and no framework sentence can reach it through a database that outlived a
        process.
        """
        seq = await self.memory.append(user_id, session_id, text, note=note)
        if self.durable is not None:
            await self.durable.append(user_id, session_id, text, seq=seq)
        return seq

    async def list(self, user_id: UserId, session_id: str) -> list[str]:
        rows = await self.memory.list(user_id, session_id)
        if rows or self.durable is None:
            return rows
        return await self.durable.list(user_id, session_id)

    async def attachments(self, user_id: UserId, session_id: str) -> list[str]:
        return await self.memory.attachments(user_id, session_id)

    async def clear(self, user_id: UserId, session_id: str) -> None:
        await self.memory.clear(user_id, session_id)
        if self.durable is not None:
            await self.durable.clear(user_id, session_id)


__all__ = [
    "IMAGE_MIMES",
    "IMAGE_SUFFIX",
    "ImageRefused",
    "InMemoryStewardTurnStore",
    "MAX_IMAGES",
    "MAX_IMAGE_BYTES",
    "PairedStewardTurnStore",
    "SESSION_ENV",
    "StewardImage",
    "StewardTurnStore",
    "attachment_note",
    "decode_image",
    "decode_images",
    "is_verbatim",
    "normalize",
]
