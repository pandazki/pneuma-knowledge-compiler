"""Cold-start orchestration over the same functions the individual commands use."""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

from pydantic import Field, field_validator
from pneuma_knowledge_core.domain.user import PROFILE_FIELDS
from pneuma_knowledge_core.persona.provenance import inferred_fields, profile_fields
from pneuma_knowledge_service.embedding_key import embedding_key_requirement

from pkc_personal import engine, infra, skill_install
from pkc_personal.console import ConsoleUnavailable, console_dist, install_console
from pkc_personal.environment import home_environment
from pkc_personal.home import Backend, Choices, Home, Language, Model, read_yaml
from pkc_personal.library import (
    Library, create_library, persist_owner_profile, pkc_script, render_library, set_config,
    set_credential, use_library, validate_name,
    watch_project,
)
from pkc_personal.owner_hints import HINT_FIELDS, read_owner_hints


class Answers(Model):
    library: str = "notes"
    language: Language = "en"
    backend: Backend = "codex"
    semantic_retrieval: bool = False
    embedding_key: str | None = Field(default=None, repr=False)
    watch: list[str] = Field(default_factory=list)
    # What the Owner stated about themselves in the answers file. Written with `owner`
    # provenance, because an answers file is the Owner speaking — unlike the machine's
    # hints, these need no confirmation.
    owner: dict[str, str | list[str]] = Field(default_factory=dict)

    @field_validator("owner")
    @classmethod
    def settable_fields(cls, value: dict) -> dict:
        return validated_owner(value)


def validated_owner(value: object) -> dict[str, str | list[str]]:
    """The `owner:` mapping, refused by field name rather than by shape.

    The names are the library's own `PROFILE_FIELDS`, imported rather than restated: a key
    this face accepted and `pkc profile set` refused would be a setup that reports a profile
    it did not write.
    """
    if not isinstance(value, dict):
        raise ValueError(f"owner must be a mapping of profile fields: {', '.join(PROFILE_FIELDS)}")
    unknown = [str(key) for key in value if key not in PROFILE_FIELDS]
    if unknown:
        raise ValueError(
            f"owner has no profile field {', '.join(sorted(unknown))}; "
            f"fields: {', '.join(PROFILE_FIELDS)}"
        )
    return value


def _interactive(home: Home) -> Answers:
    defaults = home.config.defaults if home.configured else Choices(
        language="zh" if os.environ.get("LANG", "").startswith("zh") else "en"
    )
    name = input("Library name [notes]: ").strip() or "notes"
    existing = home.path / "libraries" / name / "library.yaml"
    if existing.is_file():
        choices = Library.load(home, name).state.choices
        return Answers(library=name, **{key: getattr(choices, key) for key in ("language", "backend", "semantic_retrieval")})
    language = input(f"Language (en|zh) [{defaults.language}]: ").strip() or defaults.language
    backend = input(f"Backend (codex|claude-code|api) [{defaults.backend}]: ").strip() or defaults.backend
    semantic = input("Semantic retrieval (on with a key|off) [off]: ").strip() or "off"
    if semantic not in {"on", "off"}:
        raise ValueError("semantic retrieval must be on or off")
    key = None
    requirement = embedding_key_requirement(defaults.embedding)
    if semantic == "on" and requirement and not home.credentials().get(requirement[0]):
        key = getpass.getpass(f"{requirement[0]}: ")
    return Answers(library=name, language=language, backend=backend,
                   semantic_retrieval=semantic == "on", embedding_key=key)


def setup(home: Home, answers: str | Path | None = None, *, no_skill: bool = False,
          non_interactive: bool = False) -> Library:
    # Whether the Owner chose the language or the machine did. It decides one thing: whose
    # answer wins for the profile's language fields below.
    language_stated = True
    if answers is not None:
        data = read_yaml(Path(answers).expanduser())
        language_stated = "language" in data
        # Checked before the model, so the refusal can name the settable fields; the model's
        # own refusal is caught below and generalised to keep a key out of the exception.
        if "owner" in data:
            validated_owner(data["owner"])
        if "language" not in data:
            data["language"] = "zh" if os.environ.get("LANG", "").startswith("zh") else "en"
        if isinstance(data.get("semantic_retrieval"), str):
            choice = data["semantic_retrieval"].lower()
            if choice not in {"on", "off", "true", "false"}:
                raise ValueError("semantic_retrieval must be on or off")
            data["semantic_retrieval"] = choice in {"on", "true"}
        # Avoid putting a rejected answers document (which may hold a key) in an exception.
        try:
            selected = Answers.model_validate(data)
        except ValueError:
            raise ValueError("invalid setup answers; check library, language, backend and semantic_retrieval") from None
    elif non_interactive or not sys.stdin.isatty():
        raise ValueError("setup needs --answers <yaml> when no terminal is attached")
    else:
        selected = _interactive(home)
    validate_name(selected.library)
    defaults = Choices(backend=selected.backend, language=selected.language,
                       semantic_retrieval=selected.semantic_retrieval)
    home.initialize(defaults)
    if selected.embedding_key is not None:
        requirement = embedding_key_requirement(home.config.defaults.embedding)
        if requirement is None:
            raise ValueError("the configured embedding has no credential provider")
        # Before the infrastructure and before the engine, because this is where the key is
        # written: a setup whose answers carry a key the provider refuses should stop here,
        # with nothing started and nothing stored, rather than complete and leave an engine
        # that dies on its first embed.
        set_credential(home, requirement[0], selected.embedding_key)
    # The cold start's order, spelled once and in one place, because every defect a real
    # cold start found was an ordering defect: the engine started before the library it
    # serves existed, and a refusal in the middle of the list stopped the steps after it.
    # Each step below is idempotent, so a second `setup` on an existing home walks the same
    # list and completes nothing — it reports what is already there.
    completed: list[str] = []

    # 1. the middleware, and every engine that already has a library to serve.
    infra.up(home)
    completed.append("infrastructure")

    # 2. the library itself, and 3. the choices this run was given.
    path = home.path / "libraries" / selected.library / "library.yaml"
    existing = path.is_file()
    library = Library.load(home, selected.library) if existing else create_library(
        home, selected.library, language=selected.language, backend=selected.backend,
    )
    completed.append(f"library {library.state.name} ({'already present' if existing else 'created'})")
    if not existing:
        set_config(home, "semantic_retrieval", "on" if selected.semantic_retrieval else "off", library)
    library.record_step("infra")
    if selected.embedding_key is not None:
        library.record_step("credentials")
    use_library(home, library.state.name)
    for directory in selected.watch:
        watch_project(library, directory)

    # 4. the tenant's owner profile, so a library with no Owner yet says so rather than
    # answering with the framework's synthetic mock person.
    if persist_owner_profile(home, library, only_if_missing=True):
        completed.append("owner profile (placeholder persisted)")

    # 5. the global router skill, refreshed rather than refused: the installer has usually
    # just written this exact package, and re-rendering our own bytes is not a replacement
    # of anyone's work. A directory with no marker of ours is still refused.
    if not no_skill:
        skill_install.install(home, refresh=True)
        completed.append("harness skill")

    # 6. the console's built page, BEFORE the engine, because the engine decides at start
    # whether it serves one. A machine that cannot reach the release keeps its setup: the
    # step is reported as skipped and the next `pkchome console` fetches it.
    try:
        if console_dist(home) is None:
            install_console(home)
        completed.append("console")
    except (ConsoleUnavailable, ValueError) as exc:
        completed.append(f"console skipped: {exc}")

    # 7. this library's engine, so nothing below can stop it from starting.
    engine.start(home, library)
    completed.append(f"engine on port {library.state.engine.port}")

    # 8. the profile, after the engine, because `pkc profile set` writes the engine file and
    # the persisted record in one move and needs the store the engine brought up. It is a
    # step at all because a machine already knows its Owner's name, clock and language, and
    # a setup that leaves the profile blank answers them in English on a machine whose every
    # other application does not.
    completed.append(seed_profile(home, library, selected, language_stated=language_stated))

    # 9. the library's own package, installed into the library directory in the harness's
    # convention — that directory is the project an unattended round stands in. LAST, and
    # after the profile: the package states the Owner in its own prose, so a render taken
    # before step 8 wrote them is stale the moment setup finishes, and the tray says so
    # thirteen minutes later. `create_library` rendered one from a blank profile; this
    # renders the one the harness will actually read.
    completed.append(refresh_skill_package(home, library))

    print("Setup: " + "; ".join(completed) + ".")
    print()
    print(onboarding(home, library))
    return library


def refresh_skill_package(home: Home, library: Library) -> str:
    """Re-render the library's installed package. Never fails what has already been done.

    The package carries the Owner in its own prose — the display name, the role, the language
    the Steward is to be answered in — so every write of the profile makes the installed
    bytes a rendering of a profile that no longer exists, and `pkc skill verify` calls that
    drift. Which it is: the tray showed `skill 包：已过期` thirteen minutes into a cold start
    for exactly this reason. So whichever face writes the profile re-renders afterwards,
    from the one function that installs a library's package.

    Idempotent: `pkc skill install` purges and rewrites, so a render over an unchanged
    profile writes the same bytes and moves no hash.
    """
    try:
        render_library(home, library)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        # A package that could not be re-rendered is a stale package, not a failed setup:
        # everything above stands, the worker re-renders before its next round, and the
        # reason is named rather than swallowed.
        return f"library skill package skipped: {exc}"
    return "library skill package"


def seed_profile(home: Home, library: Library, selected: Answers, *,
                 language_stated: bool) -> str:
    """Write the machine's hints and the Owner's stated facts. Never fails a setup.

    Two provenances, two writes, in that order: what the machine inferred is a hypothesis the
    Owner still has to confirm, and what the answers file stated is the Owner already
    speaking — so a fact given in both places ends up owner-stated, not inferred.
    """
    inferred = read_owner_hints()
    if language_stated:
        # The Owner chose the language for this library; the operating system only had an
        # opinion. The value is theirs, the provenance is still `inferred` — nobody has yet
        # said that this is the language they want to be ANSWERED in.
        for field in ("locale.language", "preferences.response_language"):
            inferred[field] = selected.language
    written: list[str] = []
    failure = ""
    for updates, provenance in ((inferred, "inferred"), (dict(selected.owner), "owner")):
        if not updates:
            continue
        try:
            profile_set(home, library, updates, provenance=provenance)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            # A library whose store cannot answer is not a failed setup: everything above
            # stands, and the checklist asks the same questions from a blank profile. What
            # did land is still reported — a half-written profile said to be unwritten is
            # how a Steward ends up confirming fields nobody can see.
            failure = f"profile skipped: {exc}"
            break
        written.append(f"{provenance}: {', '.join(_ordered(updates))}")
    reported = f"profile ({'; '.join(written)})" if written else ""
    return "; ".join(part for part in (reported, failure) if part) or "profile (nothing to infer)"


def _ordered(updates: dict) -> list[str]:
    """Hint fields in their reporting order, then anything else alphabetically."""
    return [key for key in HINT_FIELDS if key in updates] + sorted(set(updates) - set(HINT_FIELDS))


def _pkc(home: Home, library: Library, *argv: str, timeout: float = 60) -> str:
    """One `pkc` call in this library's own environment, the way `status` makes them."""
    result = subprocess.run([pkc_script(), *argv], env=home_environment(home, library),
                            cwd=library.path, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        # The library's own last line, which is where its refusals are written; never the
        # whole captured output, which carries the connection string.
        reason = (result.stderr or "").strip().splitlines()
        raise RuntimeError(reason[-1] if reason else f"pkc {argv[0]} exited {result.returncode}")
    return result.stdout


def profile_set(home: Home, library: Library, updates: dict, *, provenance: str) -> None:
    fields = []
    for key in _ordered(updates):
        value = updates[key]
        fields += ["--field", f"{key}={','.join(value) if isinstance(value, list) else value}"]
    _pkc(home, library, "profile", "set", *fields, "--provenance", provenance)


#: What a personal library is thin without, in the order to ask, in the Owner's own language.
#: The Steward reads this block TO somebody, so the questions are printed the way they are to
#: be asked rather than translated at the last moment by whoever is holding the terminal.
ONBOARDING_QUESTIONS: tuple[tuple[str, str, str], ...] = (
    ("occupation", "What do you do? The work itself, in your own words.",
     "你现在做的是什么工作？用你自己的说法。"),
    ("role", "Which of these is closest to your function: engineering, marketing, "
     "product_management, sales, design, support, admin, other?",
     "你的职能最接近哪一个：engineering、marketing、product_management、sales、design、"
     "support、admin、other？"),
    ("bio", "In one line: what you are working on, and what you want this library to hold.",
     "用一句话说：你在做什么，这座知识库要装下什么。"),
    ("interests", "Which subjects should this library keep up with? A few, comma-separated.",
     "这座库该持续跟进哪些主题？列几个，用逗号分隔。"),
)


def read_profile(home: Home, library: Library) -> dict | None:
    """This library's recorded profile, or nothing when the library cannot be asked."""
    try:
        payload = json.loads(_pkc(home, library, "profile", "show", "--json", timeout=30))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return None
    profile = payload.get("profile") if isinstance(payload, dict) else None
    return profile if isinstance(profile, dict) else None


def owner_language(profile: dict | None, library: Library) -> str:
    """`zh` or `en` — the profile's recorded language, else this library's own choice."""
    recorded = ""
    if profile:
        values = profile_fields(profile)
        recorded = str(values.get("preferences.response_language") or values.get("locale.language") or "")
    return "zh" if (recorded or library.state.choices.language).startswith("zh") else "en"


def _stated(value: object) -> bool:
    return any(str(item).strip() for item in value) if isinstance(value, list) else bool(str(value or "").strip())


def seed_hints(home: Home, library: Library, profile: dict) -> tuple[list[str], str]:
    """Write the machine's hints for a profile that does not state them yet. (written, failure)

    `setup` writes these at install time (step 9), and that write can be the one step of a
    cold start that does not happen — a library whose store was not up yet, an interrupted
    run. What was left behind then was a blank profile AND a checklist with no confirmation
    step in it, so the Steward could not even see that the machine had answers to give. So
    whichever face reads the checklist first writes them: `setup` through `seed_profile`,
    `pkchome onboarding` through here, from the same `read_owner_hints()`.

    Only fields the profile leaves unstated are written. That is what makes this idempotent
    and what keeps it honest: a second call writes nothing, and a value the Owner stated is
    never overwritten by a guess about them.
    """
    stated = profile_fields(profile)
    hints = read_owner_hints()
    # The language this library was created with, exactly as `setup` treats a stated answer:
    # the value is the Owner's choice, the provenance stays `inferred` — nobody has yet said
    # this is the language they want to be ANSWERED in.
    for field in ("locale.language", "preferences.response_language"):
        hints[field] = library.state.choices.language
    updates = {key: value for key, value in hints.items() if not _stated(stated.get(key))}
    if not updates:
        return [], ""
    try:
        profile_set(home, library, updates, provenance="inferred")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        # Same verdict as `seed_profile`: a profile that could not be written is not a failed
        # checklist. The questions below stand, and the reason is named rather than swallowed.
        return [], f"profile skipped: {exc}"
    # The profile the package states just changed, so the package is re-rendered here for the
    # same reason `setup` renders it after step 8 — otherwise the tray reads "stale" from this
    # write until the worker's next round notices.
    refresh_skill_package(home, library)
    return _ordered(updates), ""


def onboarding(home: Home, library: Library) -> str:
    """The Steward's checklist: what to confirm, what to ask, and what is still undecided.

    Printed by `setup` and by `pkchome onboarding`, from the same reading of the same record,
    so a Steward who arrives a week later gets the list as it stands then rather than the list
    as it stood at install time. It also SEEDS what a setup could not (`seed_hints`), so the
    confirmation step is in the list on the machine that has it to confirm.
    """
    name = library.state.name
    profile = read_profile(home, library)
    # A library that cannot be asked for its profile cannot be written one either.
    seeded, failure = seed_hints(home, library, profile) if profile is not None else ([], "")
    if seeded:
        # Read again, so the list below is the record as it now stands rather than as it stood
        # a moment ago — the same discipline that makes this function re-readable at all.
        profile = read_profile(home, library) or profile
    language = owner_language(profile, library)
    values = profile_fields(profile) if profile else {}
    lines: list[str] = []
    if seeded:
        lines.append(f"seeded: {', '.join(seeded)}")
    elif failure:
        lines.append(failure)
    lines.append(f"Owner onboarding — {name}. Speak to the Owner in {language}.")

    inferred = list(inferred_fields(profile)) if profile else []
    if inferred:
        lines += ["", "Inferred from this machine, unconfirmed — confirm or correct each:"]
        lines += [f"  {key:<30}{values.get(key) or ''}" for key in inferred]
        lines += [f"  confirm: pkchome exec --library {name} -- pkc profile confirm --field <name>",
                  f"  correct: pkchome exec --library {name} -- pkc profile set "
                  "--field <name>=<value> --provenance owner"]
    elif profile is None:
        lines += ["", f"The library could not be asked for its profile; try pkchome status --library {name}."]

    missing = [(key, en, zh) for key, en, zh in ONBOARDING_QUESTIONS
               if not _stated(values.get(key))]
    if missing:
        lines += ["", "Ask the Owner, one at a time, and write each answer with",
                  f"  pkchome exec --library {name} -- pkc profile set --field <name>=<answer> "
                  "--provenance owner"]
        lines += [f"  {key:<12}{zh if language == 'zh' else en}" for key, en, zh in missing]

    requirement = embedding_key_requirement(library.state.choices.embedding)
    undecided = not library.state.choices.semantic_retrieval and not (
        requirement and home.credentials().get(requirement[0], "").strip())
    if undecided:
        lines += ["", "Retrieval is still undecided. Ask: run without semantic retrieval, or "
                  "provide an embedding key?",
                  f"  pkchome config set semantic_retrieval on|off --library {name}"]
        if requirement:
            lines.append(f"  pkchome credentials set {requirement[0]} --from-stdin")
    if not (inferred or missing or undecided):
        lines += ["", "Nothing is waiting: the profile is stated and retrieval is chosen."]
    lines += ["", f"The rest: pkchome status --library {name}, pkchome library show {name}."]
    return "\n".join(lines)
