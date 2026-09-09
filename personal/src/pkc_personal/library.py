"""Library identity, engine creation, directory bindings and derived skill rendering."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.git_canonical import GitCanonicalStore
from pneuma_knowledge_service.adapters.postgres import PostgresStore
from pneuma_knowledge_service.coding_agent.backends import (
    BACKENDS, BackendManifest, backend as backend_manifest,
)
from pneuma_knowledge_service.coding_agent.install import strip_block
from pneuma_knowledge_service.embedding_key import embedding_key_requirement
from pneuma_knowledge_service.engine.contract import load_engine_contract
from pneuma_knowledge_service.engine.schema import build_schema
from pneuma_knowledge_service.engine.template_files import template_text
from pneuma_knowledge_service.infra.ports import probe_free_ports
from pneuma_knowledge_service.persona_profile import owner_profile, read_profile_data, upsert_owner_profile
from pneuma_knowledge_service.settings import Settings

from pkc_personal.home import (
    Choices, Home, Model, SyncConfig, asset_path, atomic_write, now, read_yaml,
    validated_effort, yaml_text,
)

NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")


def validate_name(name: str) -> str:
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("library name must match [a-z][a-z0-9-]{0,31}")
    return name


class Engine(Model):
    port: int = Field(ge=1, le=65535)


class Steps(Model):
    """The steps a home command owns and can therefore record.

    `profile` and `first_compile` are NOT here: the commands that complete them
    (`pkc profile confirm`, `pkc draft finish`) belong to the library, which knows no home
    and cannot write this file. Recording them would mean recording a hope, so status
    derives them at read time instead (`pkc_personal.status`).
    """

    infra: str | None = None
    credentials: str | None = None
    skill: str | None = None

    @model_validator(mode="before")
    @classmethod
    def drop_derived_steps(cls, data):
        # Every library.yaml written before the two steps became derived still carries them.
        # They are dropped rather than refused: extra="forbid" stays on for real typos.
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if key not in DERIVED_STEPS}
        return data

    @field_validator("*")
    @classmethod
    def iso_timestamp(cls, value: str | None) -> str | None:
        if value is not None:
            datetime.fromisoformat(value)
        return value


DERIVED_STEPS = ("profile", "first_compile")


#: The `path` that opens the library to every project either harness has a session for.
#: Scope is a configuration, not a list of hundreds of `watch add` calls and not a code change.
ALL_PROJECTS = "all"


class Watch(Model):
    """One scope: an exact project, a prefix (`recursive`), or the literal `all`."""

    path: str
    # A prefix rather than one project: every project at or below `path`. The test is by path
    # components in the converter, so `/a/b` never admits `/a/bc`.
    recursive: bool = False
    harnesses: list[Literal["claude-code", "codex"]] = Field(
        default_factory=lambda: ["claude-code", "codex"], min_length=1)
    since: str | None = None

    @field_validator("path")
    @classmethod
    def directory(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("watch path must be non-blank")
        if value.strip() == ALL_PROJECTS:
            return ALL_PROJECTS
        return str(Path(value).expanduser().resolve())

    @field_validator("since")
    @classmethod
    def since_timestamp(cls, value: str | None) -> str | None:
        if value is not None:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("watch since must include a timezone")
        return value


class LibraryState(Model):
    name: str
    tenant: str
    created: str = Field(default_factory=now)
    engine: Engine
    choices: Choices
    steps: Steps = Field(default_factory=Steps)
    last_used: str | None = None
    bindings: list[str] = Field(default_factory=list)
    watch: list[Watch] = Field(default_factory=list)

    @field_validator("created", "last_used")
    @classmethod
    def iso_timestamp(cls, value: str | None) -> str | None:
        if value is not None:
            datetime.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def identity(self):
        validate_name(self.name)
        if self.tenant != f"lib-{self.name}":
            raise ValueError("library tenant must be lib-<name>")
        return self


class Library:
    def __init__(self, home: Home, state: LibraryState, *, path: Path | None = None):
        self.home = home
        self.state = state
        self.path = path or home.path / "libraries" / state.name

    @classmethod
    def load(cls, home: Home, name: str) -> Library:
        validate_name(name)
        state = LibraryState.model_validate(read_yaml(home.path / "libraries" / name / "library.yaml"))
        if state.name != name:
            raise ValueError("library directory and recorded name disagree")
        return cls(home, state)

    @property
    def engine_dir(self) -> Path:
        return self.path / "engine"

    @property
    def canonical_dir(self) -> Path:
        # The adapter owns tenant addressing. Its root is a parent, never a repository.
        return GitCanonicalStore(str(self.path / "canonical")).repo_path(self.state.tenant)

    @property
    def skill_backend(self) -> str:
        return "claude-code" if self.state.choices.backend == "claude-code" else "codex"

    @property
    def manifest(self) -> BackendManifest:
        """The chosen harness's manifest — the one place its layout is read from."""
        return backend_manifest(self.skill_backend)

    @property
    def skill_dir(self) -> Path:
        """The installed package, where the harness's own convention puts it.

        `.agents/skills/pkc-steward` under Codex, `.claude/skills/pkc-steward` under Claude
        Code — read off the manifest rather than restated here, so a third harness is a row
        in `backends.py` and not a branch. The path is inside the LIBRARY DIRECTORY because
        that directory is the project a harness stands in for this library: the engine
        process is started there, the unattended worker hands the round `os.getcwd()` as its
        project, and the round's task names the shim as
        `<project_dir>/<manifest.skill_dir>/scripts/pkc`.
        """
        return self.path / self.manifest.skill_dir

    def save(self) -> None:
        atomic_write(self.path / "library.yaml", yaml_text(self.state.model_dump(mode="json")))

    def record_step(self, step: str) -> None:
        if step not in Steps.model_fields:
            raise ValueError(f"no home command owns the step {step!r}; recordable: "
                             f"{', '.join(Steps.model_fields)}")
        # Reload before touching a single field so another command's completed steps survive.
        self.state = Library.load(self.home, self.state.name).state
        if getattr(self.state.steps, step) is None:
            setattr(self.state.steps, step, now())
            self.save()

    def touch_last_used(self) -> None:
        self.state = Library.load(self.home, self.state.name).state
        self.state.last_used = now()
        self.save()

    def owner_name(self) -> str | None:
        """The Owner's own name from the profile, or None while it is a placeholder or unstated.
        The converter labels the Owner's turns with it; it never sees the tenant id as a name."""
        try:
            name = owner_profile(self.state.tenant, read_profile_data(self.engine_dir)).display_name
        except Exception:
            return None
        return name.strip() or None

    def show(self) -> dict:
        return {
            **self.state.model_dump(mode="json"),
            "owner_name": self.owner_name(),
            "path": str(self.path),
            "engine_dir": str(self.engine_dir),
            "canonical_dir": str(self.canonical_dir),
            "skill_dir": str(self.skill_dir),
            # The package's own project shim, and the one the unattended round is told to
            # run. It cds to the library directory, finds no `.env` there (the edition
            # states the stack in the process environment instead — `home_environment`,
            # and `launcher.CONNECTION_SETTINGS` for a launched round), exports the
            # installed package's hash, and execs `pkc` on PATH — which in this edition is
            # the launcher's own entry point.
            "entry": str(self.skill_dir / "scripts" / "pkc"),
        }


def libraries(home: Home) -> list[Library]:
    root = home.path / "libraries"
    return [Library.load(home, p.name) for p in sorted(root.glob("*"))
            if NAME_PATTERN.fullmatch(p.name) and (p / "library.yaml").is_file()]


def _git(directory: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True, text=True)


def _init_git(directory: Path, *, commit: bool) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _git(directory, "init", "-q")
    _git(directory, "config", "user.name", "pneuma-engine" if commit else "pneuma-knowledge")
    _git(directory, "config", "user.email", "engine@local" if commit else "pneuma_knowledge@local")
    if commit:
        _git(directory, "add", "-A")
        _git(directory, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "engine: initial")


def _engine_files(name: str, choices: Choices, contract: str) -> dict[str, str]:
    # The schema declares the files, keys and defaults: no second strategy schema here.
    documents = {}
    for stage in build_schema()["stages"]:
        mapping = {knob["key"]: knob["default"] for knob in stage["knobs"]
                   if knob["type"] != "document"}
        if mapping:
            documents[stage["file"]] = mapping
    models = documents["engine.yaml"]
    default_model = Settings.model_fields["llm_model"].default
    models["compile"] = f"agent:{choices.backend}" if choices.backend != "api" else default_model
    models["recall"] = Settings.model_fields["llm_model_recall"].default or default_model
    models["embedding"] = choices.embedding
    if "semantic_retrieval" in Settings.model_fields:
        documents["intake/intake.yaml"]["semantic_retrieval"] = "on" if choices.semantic_retrieval else "off"
    documents["prompts/overlays.yaml"]["language"] = choices.language
    files = {path: yaml_text(document) for path, document in documents.items()}
    files["compile/contract.md"] = contract
    files["README.md"] = template_text("engine-README", choices.language).replace("{{PROJECT_NAME}}", name)
    profile = template_text("profile", choices.language)
    slots = {"DISPLAY_NAME": "Owner", "OCCUPATION": "", "BIO": "", "INTERESTS": "[]",
             "INDUSTRY": "other", "ROLE": "other", "LEVEL": "mid"}
    for slot, value in slots.items():
        profile = profile.replace("{{" + slot + "}}", value)
    files["persona/profile.yaml"] = profile
    return files


async def _upsert_profile(dsn: str, tenant: UserId, data: dict, *, only_if_missing: bool) -> bool:
    store = PostgresStore(dsn)
    await store.open()
    try:
        # The engine process applies the schema at boot, and on a cold start no engine has
        # booted yet: this may be the first connection the fresh database ever sees.
        await store.apply_schema()
        if only_if_missing and await store.get_user_profile(tenant) is not None:
            return False
        await upsert_owner_profile(store, tenant, data)
    finally:
        await store.aclose()
    return True


def persist_owner_profile(home: Home, library: Library, *, only_if_missing: bool = False) -> bool:
    """Persist `engine/persona/profile.yaml` as this tenant's record. True when it wrote.

    The untouched engine template is an unstated profile, with blank personal fields and
    placeholder provenance. Its legacy Owner/other/mid slots are application defaults,
    not declarations. A changed file is interpreted by the shared profile loader.

    The file stays the authority; this is the same mapping `pkc profile set` writes through.
    A store that is not up yet is not a failure — the step is simply not doable now, and
    `pkchome up` retries it for every library whose profile is still missing.
    """
    from pkc_personal import infra
    from pkc_personal.environment import home_environment
    from pneuma_knowledge_core.domain.user import UserProfile
    from pneuma_knowledge_service.engine.files import parse_mapping

    port = home.config.infra.ports.postgres
    if not infra.tcp_port_open("127.0.0.1", port):
        return False
    dsn = home_environment(home, library)["PNEUMA_KNOWLEDGE_PG_DSN"]
    data = read_profile_data(library.engine_dir)
    template = _engine_files(library.state.name, library.state.choices, "")["persona/profile.yaml"]
    if data == parse_mapping("persona/profile.yaml", template):
        data = UserProfile.unstated(UserId(library.state.tenant)).model_dump(exclude={"level_style"})
    return asyncio.run(_upsert_profile(dsn, UserId(library.state.tenant), data,
                                       only_if_missing=only_if_missing))


def create_library(
    home: Home, name: str, *, from_library: str | None = None,
    language: str | None = None, contract: str | Path | None = None, backend: str | None = None,
) -> Library:
    validate_name(name)
    home.ensure_layout()
    target = home.path / "libraries" / name
    if target.exists():
        raise ValueError(f"library {name!r} already exists")
    choices = home.config.defaults.model_copy()
    if language is not None:
        choices.language = language
    if backend is not None:
        choices.backend = backend
    source = Library.load(home, from_library) if from_library else None
    if contract in {"personal-projects", "personal-knowledge"}:
        contract_path = asset_path(f"contracts/{contract}.{choices.language}.md")
    elif contract:
        contract_path = Path(contract).expanduser()
    elif source:
        contract_path = source.engine_dir / "compile" / "contract.md"
    else:
        contract_path = asset_path(f"contracts/personal-projects.{choices.language}.md")
    body = contract_path.read_text(encoding="utf-8")
    reserved = {lib.state.engine.port for lib in libraries(home)} | set(home.config.infra.ports.model_dump().values())
    for _ in range(500):
        port = probe_free_ports(1)[0]
        if port not in reserved:
            break
    else:
        raise ValueError("could not find an unassigned engine port")
    state = LibraryState(name=name, tenant=f"lib-{name}", engine=Engine(port=port), choices=choices)
    with tempfile.TemporaryDirectory(prefix=f".{name}-", dir=target.parent) as temporary:
        staged = Path(temporary) / name
        library = Library(home, state, path=staged)
        for relative, text in _engine_files(name, choices, body).items():
            atomic_write(library.engine_dir / relative, text)
        if source:
            for path in sorted((source.engine_dir / "prompts").rglob("*")):
                if path.is_file():
                    atomic_write(library.engine_dir / "prompts" / path.relative_to(source.engine_dir / "prompts"),
                                 path.read_text(encoding="utf-8"))
            # The requested language remains a choice of the new library; clauses are copied.
            overlays = read_yaml(library.engine_dir / "prompts" / "overlays.yaml")
            overlays["language"] = choices.language
            atomic_write(library.engine_dir / "prompts" / "overlays.yaml", yaml_text(overlays))
        if load_engine_contract(library.engine_dir) is None:
            raise ValueError("contract needs frontmatter, path_templates and a non-empty body")
        _init_git(library.engine_dir, commit=True)
        _init_git(library.canonical_dir, commit=False)
        library.save()
        os.replace(staged, target)
    library = Library.load(home, name)
    render_library(home, library)
    persist_owner_profile(home, library)
    return library


def pkc_script() -> str:
    return str(Path(sys.prefix) / "bin" / "pkc")


def _drop_other_backends(library: Library) -> None:
    """One library, one harness's package: whatever an earlier backend left is removed.

    `pkchome config set backend` re-renders into the new harness's directory. Without this
    the old one stays — a second `pkc-steward` teaching the same library, and a `pkc:start`
    router block in an instructions file no harness here reads any more.
    """
    for other in BACKENDS.values():
        if other.name == library.manifest.name:
            continue
        shutil.rmtree(library.path / other.skills_dir, ignore_errors=True)
        instructions = library.path / other.instructions_file
        if not instructions.is_file():
            continue
        # Only the block between the markers is ours; the rest is somebody's prose and the
        # file only goes away when removing our block leaves nothing behind.
        remainder = strip_block(instructions.read_text(encoding="utf-8"))
        if remainder.strip():
            atomic_write(instructions, remainder)
        else:
            instructions.unlink()


def render_library(home: Home, library: Library) -> None:
    """Install the library's package the way a project gets one — because it IS a project.

    `pkc skill install` rather than `pkc skill render --out`: the harness looks for a skill
    in its own convention under the directory it was opened in, and for this edition that
    directory is the library's. So the package lands at `<lib>/<manifest.skill_dir>` and the
    router block is spliced into `<lib>/AGENTS.md` or `<lib>/CLAUDE.md`, exactly as in a
    scaffold-born project. A package rendered anywhere else is a path the unattended round's
    shim does not have.

    No `--force` because the install has none and needs none: it purges the skill directory
    before writing it, so an install is always wholesale. The language is not passed either
    — `install` reads the engine directory's own prompt-language knob, which is the same
    choice `library.yaml` records and `set_config` keeps in step.
    """
    from pkc_personal.environment import home_environment

    result = subprocess.run(
        [pkc_script(), "skill", "install", "--backend", library.skill_backend,
         "--project", str(library.path)],
        env=home_environment(home, library), cwd=library.path, capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"skill install failed (exit {result.returncode}): "
            f"{(result.stderr or '').strip() or 'no output'}"
        )
    _drop_other_backends(library)
    library.state = Library.load(home, library.state.name).state
    library.state.steps.skill = now()
    library.save()


def use_library(home: Home, name: str) -> Library:
    library = Library.load(home, name)
    atomic_write(home.path / "current", f"{name}\n")
    library.touch_last_used()
    return library


def bind_library(home: Home, name: str, directory: str | Path = ".") -> None:
    library = Library.load(home, name)
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError("binding needs an existing directory")
    binding = directory / ".pkc"
    if binding.exists():
        unbind_library(home, directory)
        library = Library.load(home, name)
    atomic_write(binding, f"{name}\n")
    library.state.bindings = sorted(set(library.state.bindings) | {str(directory)})
    library.save()


def unbind_library(home: Home, directory: str | Path = ".") -> None:
    directory = Path(directory).expanduser().resolve()
    binding = directory / ".pkc"
    if binding.exists() and not binding.is_file():
        raise ValueError(".pkc is a directory; it is not a library binding")
    binding.unlink(missing_ok=True)
    for library in libraries(home):
        if str(directory) in library.state.bindings:
            library.state.bindings.remove(str(directory))
            library.save()


def posture(unattended: bool) -> str:
    """The two words the Owner is shown for the worker's posture, spelled once."""
    return "unattended" if unattended else "attended"


def restart_engine(home: Home, library: Library) -> bool:
    """Replace this library's engine process, if one is running. True when it was replaced.

    The worker reads `PNEUMA_KNOWLEDGE_AGENT_UNATTENDED` at start, from the environment
    `home_environment` assembled for the process. So a posture recorded while the engine runs
    is a posture nothing obeys: the choice only reaches the worker when the process does.
    """
    from pkc_personal import engine

    if not engine.status(home, library)["up"]:
        return False
    engine.stop(home, library)
    engine.start(home, library)
    return True


class CredentialRefused(RuntimeError):
    """The provider did not accept a candidate credential, so nothing was written."""


#: What the probe embeds. Content-free on purpose: it is sent to a provider under a key
#: nobody has vouched for yet, so it must say nothing about this library.
PROBE_TEXT = "credential preflight"
PROBE_TIMEOUT = 20.0


def _settings_override(requirement: tuple[str, str] | None, value: str) -> dict[str, str]:
    """`{name: value}` that reaches the candidate into `Settings`, spelled the way it reads it.

    A field with a `validation_alias` (the key fields all carry one, so an unprefixed
    `OPENROUTER_API_KEY` is read) is populated under that alias and NOT under its Python
    name — `extra="ignore"` would drop the misnamed argument in silence and probe with
    whatever the environment held, which is the one outcome a preflight must never have.
    """
    if requirement is None:
        return {}
    field = Settings.model_fields[requirement[1]]
    alias = field.validation_alias
    return {alias if isinstance(alias, str) else requirement[1]: value}


def probe_embedding_key(spec: str, value: str, *, timeout: float = PROBE_TIMEOUT) -> None:
    """Embed one string through `spec` with this candidate. Returns on acceptance.

    The embeddings object is the deployment's own (`build_embeddings` over a `Settings`
    carrying the candidate) — one client and one retry policy, not a second HTTP client
    that could accept what the engine will reject. The candidate is passed as a value and
    never written to the process environment or to any file, so a refusal leaves nothing
    behind. Injectable: the personal tests monkeypatch this name and stay keyless.
    """
    from pneuma_knowledge_service.wiring import build_embeddings

    requirement = embedding_key_requirement(spec)
    embeddings = build_embeddings(
        Settings(_env_file=None, embedding_model=spec, **_settings_override(requirement, value))
    )

    async def probe() -> None:
        try:
            await asyncio.wait_for(embeddings.aembed_query(PROBE_TEXT), timeout)
        finally:
            release = getattr(embeddings, "aclose", None)
            if release is not None:
                await release()

    asyncio.run(probe())


def _refused(spec: str, key: str, value: str, exc: BaseException) -> CredentialRefused:
    """One line for the Owner: which provider said no, and how. Never the value.

    The provider's own text is not repeated — a status line and an exception class are all
    that is needed to act, and anything echoed back from a request is one bad provider away
    from carrying the candidate into a terminal, a log or a screenshot.
    """
    provider = (spec.split(":", 1)[0] or "the provider").strip()
    error: BaseException | None = exc
    reason = ""
    while error is not None and not reason:
        status = getattr(getattr(error, "response", None), "status_code", None)
        if isinstance(status, int):
            phrase = getattr(error.response, "reason_phrase", "") or ""
            reason = f"rejected it ({status} {phrase})" if phrase else f"rejected it ({status})"
        error = error.__cause__ or error.__context__
    reason = reason or f"did not answer ({type(exc).__name__})"
    line = (f"refused: {key} was not stored — {provider} {reason}; "
            f"the previous key, if any, is unchanged")
    # Belt and braces: nothing above puts the candidate in the line, and this makes it so.
    return CredentialRefused(line.replace(value, "***") if value else line)


def set_credential(home: Home, key: str, value: str, *, verify: bool = True) -> tuple[list[str], str]:
    """Store one key in the home's credentials and replace every running engine.

    A credential reaches an engine only as its process environment (`home_environment`
    assembles it at start), so a key saved while the engine runs is a key nothing holds:
    recall would go on answering 503 keyless until somebody remembered to restart.

    The provider is asked FIRST, before anything is written. A pasted URL once landed here
    as OPENROUTER_API_KEY: it was stored over a working key, every engine was restarted,
    the command reported success, and the engine died at startup on a 401 nobody was
    watching for — with the queue standing still until a human noticed. So a candidate for
    the embedding key of the configured spec must embed one string through that provider
    before it is written; a refusal leaves the credentials file, the running engines and
    the previous key exactly as they were. Returns the names of the libraries whose engine
    was replaced, and the clause the Owner is told about verification.
    """
    spec = home.config.defaults.embedding if home.configured else ""
    requirement = embedding_key_requirement(spec)
    if requirement is None or requirement[0] != key:
        note = " — not verified: no probe for this credential"
    elif not verify:
        note = " — not verified (--no-verify)"
    else:
        try:
            probe_embedding_key(spec, value)
        except Exception as exc:  # noqa: BLE001 — any refusal is a refusal; the reason is derived
            raise _refused(spec, key, value, exc) from None
        note = f" — verified {spec}"
    home.set_credential(key, value)
    restarted = [library.state.name for library in libraries(home) if restart_engine(home, library)]
    return restarted, note


def set_config(home: Home, key: str, value: str, library: Library | None = None) -> str | None:
    """Record one choice. Returns a line for the Owner when the command did more than record."""
    if key.startswith("sync."):
        if library is not None:
            raise ValueError("sync settings belong to the home; omit --library")
        config = home.config
        name = key.split(".", 1)[1]
        if name not in SyncConfig.model_fields:
            raise ValueError(f"unknown config key: {key}")
        if name == "enabled":
            if value.lower() not in {"on", "off", "true", "false"}:
                raise ValueError("sync.enabled must be on or off")
            config.sync.enabled = value.lower() in {"on", "true"}
        elif name == "exclude":
            # A pattern (or a comma-separated list of them) is APPENDED: the defaults are the
            # point of the field, and a set that silently replaced them would be a way to
            # re-admit every scratch directory by adding one project. An empty value clears.
            patterns = [pattern.strip() for pattern in value.split(",") if pattern.strip()]
            added = [pattern for pattern in patterns if pattern not in config.sync.exclude]
            config.sync.exclude = [*config.sync.exclude, *added] if patterns else []
        else:
            # Every other sync setting is a number, and its floor lives on the field itself.
            setattr(config.sync, name, int(value))
        home.save_config(config)
        return None
    if key not in Choices.model_fields:
        raise ValueError(f"unknown config key: {key}")
    parsed: str | bool = value
    # Every boolean choice is spelled the same way at the face — on or off — so the parsing
    # is read off the field rather than restated per key.
    if Choices.model_fields[key].annotation is bool:
        if value.lower() not in {"on", "off", "true", "false"}:
            raise ValueError(f"{key} must be on or off")
        parsed = value.lower() in {"on", "true"}
    elif key == "reasoning_effort":
        # The one string choice with a set behind it, refused here in the same one-line shape
        # a bad boolean gets rather than as a validation report from two layers down.
        parsed = validated_effort(value)
    if library is None:
        config = home.config
        setattr(config.defaults, key, parsed)
        home.save_config(config)
        return None
    setattr(library.state.choices, key, parsed)
    engine_path = library.engine_dir / "engine.yaml"
    if key in {"backend", "embedding"}:
        mapping = read_yaml(engine_path)
        mapping["embedding" if key == "embedding" else "compile"] = (
            parsed if key == "embedding" else
            Settings.model_fields["llm_model"].default if parsed == "api" else f"agent:{parsed}"
        )
        atomic_write(engine_path, yaml_text(mapping))
    elif key == "language":
        path = library.engine_dir / "prompts" / "overlays.yaml"
        mapping = read_yaml(path)
        mapping["language"] = parsed
        atomic_write(path, yaml_text(mapping))
    elif key == "semantic_retrieval" and "semantic_retrieval" in Settings.model_fields:
        path = library.engine_dir / "intake" / "intake.yaml"
        mapping = read_yaml(path)
        mapping[key] = "on" if parsed else "off"
        atomic_write(path, yaml_text(mapping))
    library.save()
    if key in {"backend", "language"}:
        render_library(home, library)
    if key == "unattended":
        name, taken = library.state.name, posture(bool(parsed))
        if restart_engine(home, library):
            return f"engine {name} restarted; its worker is now {taken}"
        return f"engine {name} is not running; its worker will be {taken} when it starts"
    if key in {"model", "reasoning_effort"}:
        # The launcher reads its settings once, at start, from the process environment
        # `home_environment` assembled — exactly as the posture does. So a model or an effort
        # recorded while the engine runs is one no round obeys until the process is replaced.
        name = library.state.name
        taken = f"{key} {parsed}" if parsed else f"the harness default {key}"
        if restart_engine(home, library):
            return f"engine {name} restarted; its rounds now run at {taken}"
        return f"engine {name} is not running; its rounds will run at {taken} when it starts"
    return None


def watch_project(library: Library, directory: str, *, remove: bool = False,
                  harnesses: list[str] | None = None, since: str | None = None,
                  recursive: bool = False) -> None:
    watch = Watch(path=directory, recursive=recursive,
                  harnesses=harnesses or ["claude-code", "codex"], since=since)
    # `all` names no directory; an exact or prefix entry still names one that must exist.
    if not remove and watch.path != ALL_PROJECTS and not Path(watch.path).is_dir():
        raise ValueError("watch add needs an existing directory")
    library.state = Library.load(library.home, library.state.name).state
    previous = next((item for item in library.state.watch if item.path == watch.path), None)
    if (previous and not remove and harnesses is None and since is None
            and previous.recursive == watch.recursive):
        return
    library.state.watch = [item for item in library.state.watch if item.path != watch.path]
    if not remove:
        library.state.watch.append(watch)
    library.save()
