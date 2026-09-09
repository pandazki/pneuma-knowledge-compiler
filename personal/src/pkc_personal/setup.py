"""Cold-start orchestration over the same functions the individual commands use."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from pydantic import Field
from pneuma_knowledge_service.embedding_key import embedding_key_requirement

from pkc_personal import engine, infra, skill_install
from pkc_personal.home import Backend, Choices, Home, Language, Model, read_yaml
from pkc_personal.library import (
    Library, create_library, persist_owner_profile, render_library, set_config, set_credential,
    use_library, validate_name,
    watch_project,
)


class Answers(Model):
    library: str = "notes"
    language: Language = "en"
    backend: Backend = "codex"
    semantic_retrieval: bool = False
    embedding_key: str | None = Field(default=None, repr=False)
    watch: list[str] = Field(default_factory=list)


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
    if answers is not None:
        data = read_yaml(Path(answers).expanduser())
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

    # 5. the library's own package, installed into the library directory in the harness's
    # convention — that directory is the project an unattended round stands in.
    # `create_library` installs a new one; an existing library that never got one (an
    # interrupted setup) gets it here.
    if not library.skill_dir.is_dir():
        render_library(home, library)
        completed.append("library skill package")

    # 6. the global router skill, refreshed rather than refused: the installer has usually
    # just written this exact package, and re-rendering our own bytes is not a replacement
    # of anyone's work. A directory with no marker of ours is still refused.
    if not no_skill:
        skill_install.install(home, refresh=True)
        completed.append("harness skill")

    # 7. this library's engine, last, so nothing above can stop it from starting.
    engine.start(home, library)
    completed.append(f"engine on port {library.state.engine.port}")

    print("Setup: " + "; ".join(completed) + ".")
    print(
        "Steward next steps: read pkchome status and pkchome library show.\n"
        "1. Infer the Owner profile from what you already know, write it with "
        "pkchome exec -- pkc profile set ... --provenance inferred, then ask the Owner "
        "to correct each inferred field: 'I believe you are X, a Y, writing in Z — correct me.'\n"
        "2. Read the recorded retrieval choice. If it is still undecided, ask: "
        "'Run without semantic retrieval, or provide an embedding key?' Record the answer "
        "with pkchome config set semantic_retrieval on|off --library NAME and "
        "pkchome credentials set KEY --from-stdin. Do not repeat completed questions."
    )
    return library
