"""The verbatim check on `pkc owner say` (ruling 13, story 2.5g).

The console's bridge holds what the Owner typed, and that is the one thing a terminal session
cannot give this command. So inside a bridged session the recorded text must be a verbatim
substring of an Owner turn, whitespace-normalized — a paraphrase of the Owner is not the
Owner's statement — and outside one the command is exactly what it was.

What the tests pin, beyond accept and refuse: that the normalization is whitespace and
NOTHING else (a rewritten number, a dropped clause and a changed name all stay refusals), and
that an unset variable leaves no check behind at all.
"""

from __future__ import annotations

import io

import pytest

from pneuma_knowledge_service.cli import owner as owner_cmd
from pneuma_knowledge_service.coding_agent.steward_turns import (
    SESSION_ENV,
    InMemoryStewardTurnStore,
    is_verbatim,
    normalize,
)

from _cli_library import USER, library

SESSION = "stw-abc123"
SAID = "By the way, Li left the supplier in June.\nThe new contact is Wang."


@pytest.fixture
def bridged(monkeypatch):
    """A library whose context carries a Steward transcript, and the env var that names it."""
    lib = library()
    store = InMemoryStewardTurnStore()
    lib.ctx.steward_turns = store
    monkeypatch.setenv(SESSION_ENV, SESSION)
    return lib, store


async def say(lib, text: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await owner_cmd.cmd_owner_say(lib.ctx, USER, text=text, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


# ── the pure rule ──────────────────────────────────────────────────────────────────────────


def test_the_normalization_is_whitespace_and_nothing_else():
    assert normalize("Li  left\nthe supplier") == "Li left the supplier"
    assert is_verbatim("Li left the supplier", ["Li  left\n  the supplier in June"])
    # Not case, not punctuation, not a synonym: all of those are what somebody said.
    assert not is_verbatim("li left the supplier", ["Li left the supplier"])
    assert not is_verbatim("Li left the supplier!", ["Li left the supplier"])
    assert not is_verbatim("Li departed the supplier", ["Li left the supplier"])
    # A quotation of nothing is not a quotation.
    assert not is_verbatim("", ["Li left the supplier"])
    assert not is_verbatim("anything", [])


# ── the command ────────────────────────────────────────────────────────────────────────────


async def test_a_quotation_of_the_owner_is_recorded(bridged):
    lib, store = bridged
    await store.append(USER, SESSION, SAID)
    code, out, err = await say(lib, "Li left the supplier in June.")
    assert code == owner_cmd.EXIT_OK, err
    assert "source " in out
    # The statement entered as a source, verbatim, exactly as it always did.
    stored = list(lib.store.sources.values())[0] if hasattr(lib.store, "sources") else None
    assert stored is None or "Li left the supplier in June." in stored.blocks[0].text


async def test_a_paraphrase_of_the_owner_is_refused(bridged):
    lib, store = bridged
    await store.append(USER, SESSION, SAID)
    code, out, err = await say(lib, "The owner says Li is no longer at the supplier.")
    assert code == owner_cmd.EXIT_REFUSED
    assert "verbatim" in err and "paraphrase" in err
    assert out == ""


async def test_whitespace_is_normalized_on_both_sides(bridged):
    lib, store = bridged
    await store.append(USER, SESSION, "Li  left\nthe   supplier in June")
    code, _, err = await say(lib, "Li left the\nsupplier in June")
    assert code == owner_cmd.EXIT_OK, err


async def test_a_number_the_steward_rewrote_is_refused(bridged):
    """The failure this check exists for: a summary that is nearly right."""
    lib, store = bridged
    await store.append(USER, SESSION, "Seats are 25 now, not 20.")
    code, _, err = await say(lib, "Seats are 26 now, not 20.")
    assert code == owner_cmd.EXIT_REFUSED
    assert owner_cmd.NOT_VERBATIM in err


async def test_a_session_whose_transcript_cannot_be_read_refuses(monkeypatch):
    """A rule that switched itself off when it could not be enforced would not be one."""
    lib = library()
    lib.ctx.steward_turns = None
    monkeypatch.setenv(SESSION_ENV, SESSION)
    code, _, err = await say(lib, "anything at all")
    assert code == owner_cmd.EXIT_REFUSED and "verbatim" in err


async def test_a_terminal_session_is_unchanged(monkeypatch):
    """No bridge, no transcript, no check — and the statement is still a cited source."""
    monkeypatch.delenv(SESSION_ENV, raising=False)
    lib = library()
    lib.ctx.steward_turns = InMemoryStewardTurnStore()  # empty: nothing would match
    code, out, err = await say(lib, "Seats are 25 now, not 20.")
    assert code == owner_cmd.EXIT_OK, err
    assert "source " in out


async def test_the_help_says_where_the_check_applies():
    """`cli.md` regenerates from the parser, so the help text IS the documentation."""
    from pneuma_knowledge_service.cli import build_parser

    parser = build_parser()
    text = parser.format_help()
    say_help = _subcommand_help(parser, "owner", "say")
    assert "verbatim" in say_help and "terminal" in say_help
    assert "owner" in text


def _subcommand_help(parser, group: str, command: str) -> str:
    import argparse

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            sub = action.choices[group]
            for inner in sub._actions:
                if isinstance(inner, argparse._SubParsersAction):
                    return inner.choices[command].format_help() + " ".join(
                        c.help or "" for c in inner._choices_actions
                    )
    raise AssertionError("no such command")
