"""The voice call: a full-duplex voice in front, the library behind it.

Design authority: docs/design/voice-call.md. The shape in one paragraph: the browser and the
voice provider exchange audio directly over WebRTC; this process exchanges the browser's SDP
offer for an answer with the project key (which therefore never reaches the browser), attaches
to the same session over a sideband, and from there owns everything the library has a stake
in — the transcript ledger, every delegation, and every word handed to the voice. The browser
draws captions from its own data channel, which the session config narrows to three commands
(close, mute, unmute), so the page cannot append an instruction to the voice at all.

* `gateway`  — the provider, behind a two-method port so the session is testable keyless
* `session`  — one call: the event loop over the sideband, delegations, the idle watchdog
* `librarian` — the delegate's working half: ask formation → the fast lane in its spoken posture
"""

from .gateway import CreatedSession, LiveChannel, LiveGateway, LiveUnavailable, OpenAILiveGateway
from .librarian import Librarian, LibraryAnswer, LibraryLibrarian
from .session import CallSession, CallSessions, call_status, session_config

__all__ = [
    "CallSession",
    "CallSessions",
    "CreatedSession",
    "Librarian",
    "LibraryAnswer",
    "LibraryLibrarian",
    "LiveChannel",
    "LiveGateway",
    "LiveUnavailable",
    "OpenAILiveGateway",
    "call_status",
    "session_config",
]
