"""The supplementary internet face, as a port.

The library is the authority and this is not it. Everything else in this repository answers
out of the owner's own material, and the whole point of that discipline is that a citation
resolves to a block somebody actually said. A web answer resolves to a page on the internet:
it is useful precisely where the library is silent — a release that shipped last week, a
term nobody in the room has written down yet — and it is worth exactly as much as the URLs
under it, which is why the shape below carries them and the card that uses it is refused
without one.

Provider-neutral for the ordinary reason: the shipped adapter speaks OpenRouter's Responses
API with native search, and nothing in core knows that. `available()` is here rather than
implied by `search()` raising, because the offer is made in a PROMPT — the discover contract
gains a `web` lookup kind only when a real search is behind it, and a contract that offered
a kind nothing could serve would spend the model's attention on a lookup that was always
going to be rejected.

`searches` and `cost` are carried because a supplementary path that bills per query has to
be legible in the tick record. They are reported, never gated on: a search that came back is
delivered whatever it cost, and a deployment that does not want to pay turns the knob off.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..domain.suggestion import WebCitation


@dataclass(frozen=True)
class WebSearchAnswer:
    """What one web lookup came back with.

    `text` is the provider's own answer, verbatim — the card body is this string and nothing
    is written on top of it, the same discipline the library candidates live under.
    `citations` is the pages it named; an answer with none of them cannot become a card."""

    text: str = ""
    citations: tuple[WebCitation, ...] = ()
    #: How many searches the provider actually ran to produce this.
    searches: int = 0
    #: USD, as the provider reported it. 0.0 when it reported nothing.
    cost: float = 0.0


@runtime_checkable
class WebSearch(Protocol):
    """One supplementary internet lookup. The only method the lane calls is `search`."""

    def available(self) -> bool:
        """Whether a real search is behind this. Sync: it reads configuration, not network.

        The discover contract asks this BEFORE it is assembled — an unavailable search means
        the `web` lookup kind is never offered, so the model is never invited to plan one."""
        ...

    async def search(self, question: str, *, max_results: int = 3) -> WebSearchAnswer:
        """Answer `question` from the internet, with the pages it used.

        `max_results` bounds how many searches the provider may run, not how many sentences
        come back. Implementations MUST NOT retry the underlying request: a retried search
        is a second charge, and the lane treats a failure as a degraded face rather than
        something worth paying twice for."""
        ...
