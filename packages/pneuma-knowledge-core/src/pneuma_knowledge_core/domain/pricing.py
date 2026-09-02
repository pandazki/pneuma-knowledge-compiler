"""What a call cost — in tokens always, in money only where a deployment declared prices.

THE FRAMEWORK HOLDS NO PRICE OPINION
------------------------------------
Tokens are a fact the provider reported; a price is a commercial arrangement between a
deployment and its vendor, and it changes without asking anyone here. So this module
computes money and never states any: every rate comes from the deployment's own
declaration (`model_pricing`), and a model that declaration does not name is reported in
tokens with no money beside it. `None` is the honest answer to "what did this cost" when
nobody said what a token is worth — never a zero, and never a figure carried over from
whatever a model used to charge.

WHY COST IS DERIVED AND NOT STORED
----------------------------------
A record keeps `token_usage`, which is what actually happened and stays true forever. The
money is computed when someone asks, out of the prices declared right then. Storing the
amount instead would freeze a number that goes stale the next time a vendor moves a rate,
and leave a library full of prices nobody can reproduce.

THE ARITHMETIC, AND WHAT THE PROVIDER'S FIELDS MEAN
---------------------------------------------------
`input_tokens` is the WHOLE prompt, cache included — `cache_read` and `cache_creation` are
subsets of it, not additions to it (measured on the live bench: input 4441 = cache_read
1780 + cache_creation 2655 + 6 fresh). So the input is billed in three parts at three
rates, and the part billed at the full input rate is what is left after the two cached
parts are taken out. That subtraction is clamped at zero: a provider whose fields do not
add up must not produce a negative bill.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

#: The usage vocabulary, in the order every lane reports it and every reader shows it.
#: One tuple, so the record's field order, the wire's field order and `zero_usage()` in the
#: fast lane cannot drift apart.
USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_read",
    "cache_creation",
)

#: Rates are quoted per this many tokens — the unit every vendor prices in.
RATE_UNIT = 1_000_000


class PricingError(ValueError):
    """A pricing declaration that cannot be read. Raised, never swallowed: a deployment
    that wrote a rate down and got nothing would rather be told than shown no money."""


@dataclass(frozen=True)
class ModelPrice:
    """One model's declared rates, each per 1M tokens, in one currency.

    Frozen and comparable by value, which is what makes "these two roles are priced the
    same" a mechanical question rather than a judgement call.
    """

    input: float
    output: float
    cache_read: float
    cache_creation: float
    currency: str


def _rate(raw: str, *, entry: str) -> float:
    """One declared rate, or a refusal naming the entry.

    `float()` reads more than numbers: `nan`, `inf`, `-Infinity` and an overflowing
    `1e309` all parse, and none of them is a price. `nan` also slips past the negative
    check (every comparison against it is false), so both guards are stated here rather
    than one: a non-finite rate would travel through `cost_of` into an amount that JSON
    cannot serialize and no reader could act on.
    """
    try:
        value = float(raw)
    except ValueError:
        raise PricingError(
            f"model_pricing: {entry!r} — {raw!r} is not a number. Each entry is "
            "`<model id> = <input>/<output>/<cache_read>/<cache_creation> <CURRENCY>`."
        ) from None
    if not math.isfinite(value):
        raise PricingError(
            f"model_pricing: {entry!r} — {raw!r} is not a finite rate"
        )
    if value < 0:
        raise PricingError(f"model_pricing: {entry!r} — a rate cannot be negative")
    return value


def parse_model_pricing(declaration: str) -> dict[str, ModelPrice]:
    """The deployment's declaration → model id → rates. Empty declaration ⇒ no prices.

    One entry per line (or separated by `;`), each

        <model id> = <input>/<output>/<cache_read>/<cache_creation> <CURRENCY>

    with `#` starting a comment. All four rates are required — a deployment that leaves the
    cache rates off is not saying "they are free", it is failing to say — and so is the
    currency: a defaulted "USD" would be the framework holding a price opinion about a
    deployment that may bill in anything.

    Malformed input RAISES. The parser is reached through a `Settings` validator, so a bad
    declaration is refused at boot and at the engine console's apply, with the offending
    entry named — rather than quietly pricing nothing and leaving somebody to wonder why
    the money never appeared.
    """
    table: dict[str, ModelPrice] = {}
    text = str(declaration or "")
    for chunk in text.replace(";", "\n").splitlines():
        entry = chunk.split("#", 1)[0].strip()
        if not entry:
            continue
        model, separator, rest = entry.partition("=")
        if not separator or not model.strip():
            raise PricingError(
                f"model_pricing: {entry!r} — expected `<model id> = "
                "<input>/<output>/<cache_read>/<cache_creation> <CURRENCY>`"
            )
        parts = rest.split()
        if len(parts) != 2:
            raise PricingError(
                f"model_pricing: {entry!r} — expected four rates and a currency, "
                "e.g. `openai/gpt-5.6-luna = 1.25/10/0.125/1.25 USD`"
            )
        rates, currency = parts
        numbers = rates.split("/")
        if len(numbers) != 4:
            raise PricingError(
                f"model_pricing: {entry!r} — expected exactly four rates "
                "(input/output/cache_read/cache_creation), got "
                f"{len(numbers)}"
            )
        table[normalize_model(model)] = ModelPrice(
            input=_rate(numbers[0], entry=entry),
            output=_rate(numbers[1], entry=entry),
            cache_read=_rate(numbers[2], entry=entry),
            cache_creation=_rate(numbers[3], entry=entry),
            currency=currency.strip(),
        )
    return table


def normalize_model(model: str) -> str:
    """A model spec as this table keys it: trimmed and lower-cased, nothing else.

    Deliberately not clever. The provider prefix is NOT stripped here, because
    `openrouter:openai/gpt-5.6-luna` and `openai:gpt-5.6-luna` are two purchases at two
    prices, and a normalizer that collapsed them would let a declaration about one silently
    price the other. `price_for` is where a declaration written without the prefix is still
    found, and it says so.
    """
    return str(model or "").strip().lower()


def price_for(model: str, table: Mapping[str, ModelPrice]) -> ModelPrice | None:
    """The declared price for one model spec, or `None` — which means "nobody said".

    Two lookups, in order: the spec exactly as the deployment routes it
    (`openrouter:openai/gpt-5.6-luna`), then the bare model id after the provider prefix
    (`openai/gpt-5.6-luna`). The second exists because a rate card is quoted per model, and
    a deployment that declares the model it buys should not have to re-declare it for every
    gateway it buys through. The exact spec wins whenever it is declared, so a deployment
    that DOES price two gateways differently gets what it wrote.
    """
    key = normalize_model(model)
    if not key:
        return None
    found = table.get(key)
    if found is not None:
        return found
    _prefix, separator, bare = key.partition(":")
    if separator and bare:
        return table.get(bare)
    return None


def agreed_price(models: Iterable[str], table: Mapping[str, ModelPrice]) -> ModelPrice | None:
    """The one price that covers EVERY model in a lane — or `None`.

    A lane's `token_usage` is the sum over its calls, and a lane can spend across roles: the
    fast lane plans and glances on the recall model and answers on the answer model; the
    Live Context lane discovers on one and picks on another. There is no per-role split in
    the number, so there is exactly one honest way to put money on it — require the roles to
    agree. All resolving to the same declared price ⇒ that price, and the amount is exact.
    Any of them undeclared, or two of them priced differently ⇒ no money, tokens only.

    The alternative was to nominate a "principal" role and price the whole lane at its rate,
    which produces a confident wrong number the moment a deployment splits its roles. A
    figure labelled derived is still invented if the arithmetic never had the inputs.
    """
    agreed: ModelPrice | None = None
    seen = False
    for model in models:
        price = price_for(model, table)
        if price is None:
            return None
        if seen and price != agreed:
            return None
        agreed, seen = price, True
    return agreed if seen else None


def usage_pairs(usage: Mapping[str, int] | Sequence[tuple[str, int]] | None) -> tuple[tuple[str, int], ...]:
    """A lane's usage mapping as field-ordered pairs — the shape a record stores.

    `USAGE_FIELDS` order first (only the fields actually reported), then anything else the
    mapping carries, in its own order: a lane that grows a sixth counter is recorded rather
    than dropped, and a reader still finds the five it knows where it expects them.
    """
    if not usage:
        return ()
    mapping = dict(usage)
    known = [name for name in USAGE_FIELDS if name in mapping]
    extra = [name for name in mapping if name not in USAGE_FIELDS]
    return tuple((name, int(mapping[name] or 0)) for name in known + extra)


def usage_mapping(usage: Mapping[str, int] | Sequence[tuple[str, int]] | None) -> dict[str, int]:
    """Pairs (or a mapping) back to a plain mapping — the shape the arithmetic reads."""
    if not usage:
        return {}
    if isinstance(usage, Mapping):
        return {str(k): int(v or 0) for k, v in usage.items()}
    return {str(k): int(v or 0) for k, v in usage}


def cost_of(
    usage: Mapping[str, int] | Sequence[tuple[str, int]] | None,
    pricing: ModelPrice | None,
) -> dict[str, object] | None:
    """`{"amount": …, "currency": …}` for this usage at these rates — or `None`.

    `None` in two cases, and they are the same refusal wearing two hats. There are no rates
    to apply: the model is undeclared, or the deployment declared no prices at all. Or there
    is nothing to apply them TO: the usage is empty, which is what a record written before
    usage was kept says — "nothing was reported", not "nothing was spent". Pricing an empty
    mapping would print `0.00` beside every row in a library's back-catalogue on the day its
    owner first declares a rate, and every one of those calls did cost money.

    A call that genuinely spent nothing — a lane that reported its counters and they are all
    zero — is `0`, because "it was free" and "nobody counted" are different answers and the
    money face shows them differently.

    Six decimal places: a single cheap call can cost fractions of a cent, and rounding it to
    two would print `0.00` for money that was really spent.
    """
    if pricing is None:
        return None
    counts = usage_mapping(usage)
    if not counts:
        return None
    cache_read = max(0, counts.get("cache_read", 0))
    cache_creation = max(0, counts.get("cache_creation", 0))
    fresh_input = max(0, counts.get("input_tokens", 0) - cache_read - cache_creation)
    output = max(0, counts.get("output_tokens", 0))
    amount = (
        fresh_input * pricing.input
        + cache_read * pricing.cache_read
        + cache_creation * pricing.cache_creation
        + output * pricing.output
    ) / RATE_UNIT
    return {"amount": round(amount, 6), "currency": pricing.currency}


def add_cost(a: dict[str, object] | None, b: dict[str, object] | None) -> dict[str, object] | None:
    """Two costs summed — `None` when either is missing or they are in different currencies.

    An aggregate over a mixed-currency window has no total, and inventing one by adding
    yuan to dollars would be the worst possible answer to "what did this cost".
    """
    if a is None or b is None:
        return None
    if a.get("currency") != b.get("currency"):
        return None
    return {
        "amount": round(float(a.get("amount") or 0) + float(b.get("amount") or 0), 6),
        "currency": a.get("currency"),
    }


__all__ = [
    "ModelPrice",
    "PricingError",
    "RATE_UNIT",
    "USAGE_FIELDS",
    "add_cost",
    "agreed_price",
    "cost_of",
    "normalize_model",
    "parse_model_pricing",
    "price_for",
    "usage_mapping",
    "usage_pairs",
]
