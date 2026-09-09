"""The engine directory's starting texts, as package data.

A generated engine directory does not start empty: it starts from a contract skeleton, an
owner-profile skeleton and an orientation README, each in the documentation language the
owner chose. Those texts are library material, not one application's private files — the
scaffold writes them into a project directory, and the personal edition writes the same
texts into a library under the home. Keeping one copy here is what makes the two editions
the same engine rather than two engines that happen to look alike.

The files are shipped inside this package (`engine/templates/`, data beside this module
rather than inside it), so they are readable through `importlib.resources` from an installed
wheel and by path from a source checkout. Slots are `{{UPPER_SNAKE}}`; the caller fills them.
"""

from __future__ import annotations

from pathlib import Path

#: Known template name → file suffix. The name is what a caller asks for; the language and
#: the suffix complete the filename (`contract` + `zh` → `contract.zh.md`).
TEMPLATE_SUFFIXES = {
    "contract": "md",
    "engine-README": "md",
    "profile": "yaml",
}

#: The languages the documentation ships in. Same two everywhere in this repository.
TEMPLATE_LANGUAGES = ("en", "zh")

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


class UnknownTemplate(LookupError):
    """A template name or language this package does not ship."""


def template_path(name: str, language: str = "en") -> Path:
    """The file for `name` in `language`, for a caller that wants to copy it.

    Raises `UnknownTemplate` naming what does exist: a miss here is a typo in a caller, and
    a message that lists the vocabulary is the difference between a one-line fix and a
    directory listing.
    """
    if name not in TEMPLATE_SUFFIXES:
        raise UnknownTemplate(
            f"unknown engine template {name!r}; known names: "
            f"{', '.join(sorted(TEMPLATE_SUFFIXES))}"
        )
    if language not in TEMPLATE_LANGUAGES:
        raise UnknownTemplate(
            f"unknown template language {language!r} for {name!r}; known languages: "
            f"{', '.join(TEMPLATE_LANGUAGES)}"
        )
    path = TEMPLATE_DIR / f"{name}.{language}.{TEMPLATE_SUFFIXES[name]}"
    if not path.is_file():
        raise UnknownTemplate(f"engine template missing from the package: {path}")
    return path


def template_text(name: str, language: str = "en") -> str:
    """The text of `name` in `language`, verbatim (UTF-8, newlines untouched)."""
    return template_path(name, language).read_text(encoding="utf-8")


def template_names() -> list[str]:
    """The template names this package ships, sorted."""
    return sorted(TEMPLATE_SUFFIXES)


__all__ = [
    "TEMPLATE_DIR",
    "TEMPLATE_LANGUAGES",
    "TEMPLATE_SUFFIXES",
    "UnknownTemplate",
    "template_names",
    "template_path",
    "template_text",
]
