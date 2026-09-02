"""Declared pricing, and the money derived from it.

Two things are being pinned. The arithmetic: an input that is billed in three parts because
the provider's cache fields are SUBSETS of `input_tokens`, not additions to it. And the
refusals: no declaration, no money — never a zero standing in for "nobody said what this
costs", and never a figure assembled from rates that do not all apply.
"""

from __future__ import annotations

import pytest

from pneuma_knowledge_core.domain.pricing import (
    ModelPrice,
    PricingError,
    add_cost,
    agreed_price,
    cost_of,
    parse_model_pricing,
    price_for,
    usage_pairs,
)

#: 1.25 / 10 / 0.125 / 1.25 per 1M — the shape of a real rate card, synthetic numbers.
LUNA = ModelPrice(input=1.25, output=10.0, cache_read=0.125, cache_creation=1.25, currency="USD")
DECLARATION = """
# the deployment's own rate card
openrouter:openai/gpt-5.6-luna = 1.25/10/0.125/1.25 USD
anthropic/claude-opus-5 = 5/25/0.5/6.25 USD
"""


def usage(**counts: int) -> dict[str, int]:
    base = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read": 0,
        "cache_creation": 0,
    }
    base.update(counts)
    return base


# ------------------------------------------------------------------ reading a declaration


def test_a_declaration_is_one_entry_per_model_with_four_rates_and_a_currency():
    table = parse_model_pricing(DECLARATION)
    assert table["openrouter:openai/gpt-5.6-luna"] == LUNA
    assert table["anthropic/claude-opus-5"].output == 25.0
    assert table["anthropic/claude-opus-5"].currency == "USD"


def test_entries_may_be_separated_by_semicolons_for_a_one_line_environment_variable():
    table = parse_model_pricing("a/m1 = 1/2/0.1/1 USD; a/m2 = 3/4/0.3/3 CNY")
    assert set(table) == {"a/m1", "a/m2"}
    assert table["a/m2"].currency == "CNY"


def test_an_empty_declaration_is_no_prices_rather_than_free():
    assert parse_model_pricing("") == {}
    assert parse_model_pricing("   \n # only a comment\n") == {}


@pytest.mark.parametrize(
    "bad",
    [
        "openai/gpt-5.6-luna 1.25/10/0.125/1.25 USD",  # no `=`
        "openai/gpt-5.6-luna = 1.25/10 USD",  # two rates, not four
        "openai/gpt-5.6-luna = 1.25/10/0.125/1.25",  # no currency
        "openai/gpt-5.6-luna = 1.25/ten/0.125/1.25 USD",  # not a number
        "openai/gpt-5.6-luna = -1/10/0.125/1.25 USD",  # negative
        "openai/gpt-5.6-luna = nan/10/0.125/1.25 USD",  # `float()` takes it; it is no price
        "openai/gpt-5.6-luna = inf/10/0.125/1.25 USD",
        "openai/gpt-5.6-luna = 1.25/-Infinity/0.125/1.25 USD",
        "openai/gpt-5.6-luna = 1.25/10/1e309/1.25 USD",  # overflows to inf
    ],
)
def test_a_malformed_entry_is_refused_and_never_silently_skipped(bad):
    """A deployment that wrote a rate down and got no money would have no way to find out
    why. The parser raises, the settings validator carries it, and the console refuses the
    apply — mechanism, not a warning nobody reads."""
    with pytest.raises(PricingError):
        parse_model_pricing(bad)


def test_a_gateway_spec_finds_the_bare_model_it_buys_but_an_exact_entry_wins():
    table = parse_model_pricing("openai/gpt-5.6-luna = 1.25/10/0.125/1.25 USD")
    assert price_for("openrouter:openai/gpt-5.6-luna", table) is not None
    assert price_for("openai/gpt-5.6-luna", table) is not None
    exact = parse_model_pricing(
        "openai/gpt-5.6-luna = 1.25/10/0.125/1.25 USD\n"
        "openrouter:openai/gpt-5.6-luna = 2/12/0.2/2 USD"
    )
    assert price_for("openrouter:openai/gpt-5.6-luna", exact).input == 2.0


def test_an_undeclared_model_has_no_price_and_no_guess():
    table = parse_model_pricing(DECLARATION)
    assert price_for("openrouter:someone/else-4", table) is None
    assert price_for("", table) is None


# ----------------------------------------------------------------------- the truth table


@pytest.mark.parametrize(
    "counts, pricing, expected",
    [
        # Nobody declared a price: no money, and NOT a zero.
        (usage(input_tokens=1000, output_tokens=100), None, None),
        # Declared, and the lane reported all-zero counters: zero is the true answer.
        (usage(), LUNA, 0.0),
        # Declared, and NOTHING was reported — a record written before usage was kept. Not
        # zero: pricing it would print `0.00` beside a back-catalogue of calls that really
        # did cost money, the day their owner first declares a rate.
        (None, LUNA, None),
        ({}, LUNA, None),
        # A cache-free call: 1M input + 1M output at the two headline rates.
        (usage(input_tokens=1_000_000, output_tokens=1_000_000), LUNA, 11.25),
        # The whole input came out of the cache — billed at the cache_read rate only.
        (usage(input_tokens=1_000_000, cache_read=1_000_000), LUNA, 0.125),
        # The whole input was written to the cache.
        (usage(input_tokens=1_000_000, cache_creation=1_000_000), LUNA, 1.25),
        # Three parts of one input, which is the live-bench shape: the fresh remainder is
        # what is left after both cached parts, never the whole prompt counted twice.
        (
            usage(input_tokens=1_000_000, cache_read=400_000, cache_creation=400_000),
            LUNA,
            (200_000 * 1.25 + 400_000 * 0.125 + 400_000 * 1.25) / 1_000_000,
        ),
        # A provider whose fields do not add up must not produce a negative bill.
        (
            usage(input_tokens=1000, cache_read=900, cache_creation=900),
            LUNA,
            (900 * 0.125 + 900 * 1.25) / 1_000_000,
        ),
        # `total_tokens` is a reported sum, never an input to the arithmetic.
        (usage(input_tokens=0, output_tokens=0, total_tokens=999_999), LUNA, 0.0),
    ],
)
def test_the_cost_truth_table(counts, pricing, expected):
    got = cost_of(counts, pricing)
    if expected is None:
        assert got is None
        return
    assert got == {"amount": round(expected, 6), "currency": "USD"}


def test_an_unreported_usage_is_not_a_free_call_even_where_prices_are_declared():
    """The two states a money face must never merge: `{}` is "nobody counted", a row of
    zeros is "counted, and it was nothing"."""
    assert cost_of({}, LUNA) is None
    assert cost_of(usage(), LUNA) == {"amount": 0.0, "currency": "USD"}


def test_a_cost_reads_the_same_from_pairs_as_from_a_mapping():
    """The record stores field-ordered pairs; the wire hands back a mapping. One number."""
    counts = usage(input_tokens=2000, output_tokens=300, cache_read=1500)
    assert cost_of(usage_pairs(counts), LUNA) == cost_of(counts, LUNA)


# ------------------------------------------------------- one lane, possibly several roles


def test_roles_that_agree_on_one_price_price_the_whole_lane():
    table = parse_model_pricing(DECLARATION)
    models = ["openrouter:openai/gpt-5.6-luna", "openrouter:openai/gpt-5.6-luna"]
    assert agreed_price(models, table) == LUNA


def test_roles_priced_differently_leave_the_lane_in_tokens_only():
    """A lane's usage is the sum over its calls with no per-role split, so two rates cannot
    be applied to it. Refusing is the only honest answer — a "derived" figure computed from
    one of two applicable rates is still invented money."""
    table = parse_model_pricing(DECLARATION)
    models = ["openrouter:openai/gpt-5.6-luna", "anthropic/claude-opus-5"]
    assert agreed_price(models, table) is None
    assert cost_of(usage(input_tokens=10), agreed_price(models, table)) is None


def test_one_undeclared_role_is_enough_to_withhold_the_lanes_cost():
    table = parse_model_pricing(DECLARATION)
    assert agreed_price(["openrouter:openai/gpt-5.6-luna", "someone/else-4"], table) is None


def test_no_roles_at_all_is_no_price():
    assert agreed_price([], parse_model_pricing(DECLARATION)) is None


# ------------------------------------------------------------------------- aggregation


def test_two_costs_in_one_currency_add_up():
    assert add_cost({"amount": 0.5, "currency": "USD"}, {"amount": 0.25, "currency": "USD"}) == {
        "amount": 0.75,
        "currency": "USD",
    }


def test_a_window_that_mixes_currencies_reports_no_total():
    assert add_cost({"amount": 0.5, "currency": "USD"}, {"amount": 3.0, "currency": "CNY"}) is None
    assert add_cost({"amount": 0.5, "currency": "USD"}, None) is None


# ---------------------------------------------------------------------- the usage vocabulary


def test_usage_pairs_are_field_ordered_so_a_record_reads_the_same_everywhere():
    pairs = usage_pairs({"output_tokens": 3, "cache_read": 1, "input_tokens": 2})
    assert pairs == (("input_tokens", 2), ("output_tokens", 3), ("cache_read", 1))


def test_a_counter_the_framework_does_not_know_is_recorded_rather_than_dropped():
    pairs = usage_pairs({"input_tokens": 1, "reasoning_tokens": 9})
    assert pairs == (("input_tokens", 1), ("reasoning_tokens", 9))


def test_no_usage_is_an_empty_tuple_not_a_row_of_zeros():
    assert usage_pairs(None) == ()
    assert usage_pairs({}) == ()
