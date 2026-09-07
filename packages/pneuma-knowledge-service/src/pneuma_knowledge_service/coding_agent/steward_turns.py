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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class StewardTurnStore(Protocol):
    """Where a session's Owner turns live while the session does."""

    async def append(
        self, user_id: UserId, session_id: str, text: str, *, seq: int | None = None
    ) -> int:
        """Record one Owner turn and return its sequence number."""

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

    async def append(
        self, user_id: UserId, session_id: str, text: str, *, seq: int | None = None
    ) -> int:
        rows = self.turns.setdefault((str(user_id), session_id), [])
        rows.append(text)
        return len(rows)

    async def list(self, user_id: UserId, session_id: str) -> list[str]:
        return list(self.turns.get((str(user_id), session_id), ()))

    async def clear(self, user_id: UserId, session_id: str) -> None:
        self.turns.pop((str(user_id), session_id), None)


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

    async def append(self, user_id: UserId, session_id: str, text: str) -> int:
        seq = await self.memory.append(user_id, session_id, text)
        if self.durable is not None:
            await self.durable.append(user_id, session_id, text, seq=seq)
        return seq

    async def list(self, user_id: UserId, session_id: str) -> list[str]:
        rows = await self.memory.list(user_id, session_id)
        if rows or self.durable is None:
            return rows
        return await self.durable.list(user_id, session_id)

    async def clear(self, user_id: UserId, session_id: str) -> None:
        await self.memory.clear(user_id, session_id)
        if self.durable is not None:
            await self.durable.clear(user_id, session_id)


__all__ = [
    "InMemoryStewardTurnStore",
    "PairedStewardTurnStore",
    "SESSION_ENV",
    "StewardTurnStore",
    "is_verbatim",
    "normalize",
]
