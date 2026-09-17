"""The voice provider, behind the two things a call needs from it.

`create` exchanges the browser's SDP offer for an answer — the documented browser path for
this API has no ephemeral client credential, so the exchange runs here with the project key
and the browser receives an SDP answer and a session id, never a secret. `attach` opens the
sideband: a second connection to the same session that carries events and commands while
the audio stays on WebRTC.

Events cross this boundary as plain dicts. The SDK's typed events would tie the session's
logic to one SDK version's classes, and the session is tested against a scripted channel
that has no such classes to build.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol


class LiveUnavailable(RuntimeError):
    """The provider refused or could not be reached. `status` is its HTTP status, if any."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class CreatedSession:
    session_id: str
    sdp: str


class LiveChannel(Protocol):
    """An attached session: commands out, events in."""

    async def send(self, event: Mapping[str, Any]) -> None: ...

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]: ...


class LiveGateway(Protocol):
    async def create(self, *, session: Mapping[str, Any], offer_sdp: str) -> CreatedSession: ...

    def attach(self, session_id: str) -> AbstractAsyncContextManager[LiveChannel]: ...


_REFLECTED_AUDIO = frozenset({"session.output_audio.delta", "session.input_audio.append"})


class _SidebandChannel:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    async def send(self, event: Mapping[str, Any]) -> None:
        await self._connection.send(dict(event))

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        async for event in self._connection:
            # A sideband is also sent a copy of both audio streams, fifty-odd frames a second
            # of base64 PCM. Nothing here listens to audio, so those are dropped before they
            # cost a serialization.
            if getattr(event, "type", "") in _REFLECTED_AUDIO:
                continue
            yield event.model_dump(mode="json") if hasattr(event, "model_dump") else dict(event)


class OpenAILiveGateway:
    """The shipped gateway: OpenAI's Live API through its SDK."""

    def __init__(self, api_key: str, *, timeout: float = 30.0) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout)

    async def create(self, *, session: Mapping[str, Any], offer_sdp: str) -> CreatedSession:
        from openai import APIError

        try:
            result = await self._client.live.create(
                session=dict(session),  # type: ignore[arg-type]
                transport={"type": "webrtc", "sdp": offer_sdp},
            )
        except APIError as exc:
            # The message is the provider's own sentence ("Incorrect API key provided…",
            # "unsupported usage tier"); the key is never in it, and the caller scrubs anyway.
            raise LiveUnavailable(
                str(getattr(exc, "message", "") or exc), status=getattr(exc, "status_code", None)
            ) from exc
        return CreatedSession(session_id=result.session.id, sdp=result.transport.sdp)

    @asynccontextmanager
    async def attach(self, session_id: str) -> AsyncIterator[LiveChannel]:
        async with self._client.live.sideband.connect(session_id=session_id) as connection:
            yield _SidebandChannel(connection)

    async def aclose(self) -> None:
        await self._client.close()
