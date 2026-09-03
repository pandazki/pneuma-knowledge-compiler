"""What a lane cost this deployment — the bridge from a role table to money.

Core knows how to turn tokens into money given rates (`domain/pricing.py`). It does not know
which model served which lane, because that is deployment routing and routing lives here.
This module is the join, and it is the whole of the service's involvement with money: no
amount is stored anywhere, so every figure the API returns is computed from the rates
declared at the moment somebody asked.

WHY A LANE IS PRICED THROUGH ITS ROLES, PLURAL
----------------------------------------------
A lane's `token_usage` is the sum over every model call it made, and a lane can spend across
roles: fast plans and glances on `recall` and answers on `answer`; the Live Context tick
discovers on `live_discover` and picks on `live_pick`. There is no per-role split inside the
number, so there is exactly one honest rule — the roles must AGREE on a price. All of them
resolving to the same declared rates ⇒ that price, and the arithmetic is exact. Any of them
undeclared, or two of them priced differently ⇒ no money at all, tokens only.

The alternative — nominate the "principal" role and price the lane at its rate — produces a
confident wrong number the moment a deployment splits its roles, which is precisely the
deployment that most wants to know what it is spending.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Mapping, Sequence

from pneuma_knowledge_core.domain.pricing import (
    ModelPrice,
    agreed_price,
    cost_of,
    parse_model_pricing,
)

from .settings import Settings
from .wiring import resolve_model_name

#: Which model roles each spending lane actually calls — read off the dispatch points, not
#: guessed: fast builds `recall` + `answer` (api/routes/v1.py), deep builds `deep`, the
#: briefing ask builds `recall`, a full-scope Live Context tick builds `live_discover` +
#: `live_pick` while a briefing-scope one builds `live_context`, and a compile job's usage
#: counts the tool loop only, which is `compile` alone.
LANE_ROLES: dict[str, tuple[str, ...]] = {
    "fast": ("recall", "answer"),
    "deep": ("deep",),
    "briefing_ask": ("recall",),
    "live": ("live_discover", "live_pick"),
    "live_briefing": ("live_context",),
    "live_detail": ("live_context",),
    "compile": ("compile",),
}


@lru_cache(maxsize=8)
def _parsed(declaration: str) -> dict[str, ModelPrice]:
    """The declaration parsed once per distinct text. It is validated at `Settings`
    construction, so by the time it reaches here it cannot raise."""
    return parse_model_pricing(declaration)


def pricing_table(settings: Settings) -> dict[str, ModelPrice]:
    """This deployment's declared rates. Empty when it has declared none.

    Read with `getattr` because "declares no prices" is the state every stand-in settings
    object is in, and money is the one feature that must degrade to silence rather than to
    an exception: a face that cannot say what a call cost still has to show what it spent.
    """
    return _parsed(str(getattr(settings, "model_pricing", "") or ""))


def price_for_roles(settings: Settings, roles: Iterable[str]) -> ModelPrice | None:
    """The one price covering every named role, or `None` (see the module docstring)."""
    table = pricing_table(settings)
    if not table:
        return None
    return agreed_price((resolve_model_name(settings, role) for role in roles), table)


def cost_for_roles(
    settings: Settings,
    roles: Iterable[str],
    usage: Mapping[str, int] | Sequence[tuple[str, int]] | None,
) -> dict[str, object] | None:
    """`{"amount": …, "currency": …}` for this usage on these roles, or `None`."""
    return cost_of(usage, price_for_roles(settings, roles))


def lane_cost(
    settings: Settings,
    lane: str,
    usage: Mapping[str, int] | Sequence[tuple[str, int]] | None,
) -> dict[str, object] | None:
    """The same, addressed by lane name. A lane this module does not know has no cost —
    an unknown lane's roles are unknown, and unknown roles cannot be priced."""
    roles = LANE_ROLES.get(lane)
    if not roles:
        return None
    return cost_for_roles(settings, roles, usage)


__all__ = [
    "LANE_ROLES",
    "cost_for_roles",
    "lane_cost",
    "price_for_roles",
    "pricing_table",
]
