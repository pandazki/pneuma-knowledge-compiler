"""Home configuration and atomic persistence, with secrets kept outside libraries."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from pneuma_knowledge_service.infra.ports import probe_free_ports
from pneuma_knowledge_service.settings import AGENT_REASONING_EFFORTS, Settings

from pkc_personal import __version__

Backend = Literal["codex", "claude-code", "api"]
Language = Literal["en", "zh"]
KEY_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*\Z")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def replace_directory(staged: Path, target: Path) -> None:
    """Publish a complete tree; a failed publication restores the previous tree."""
    backup = target.with_name(f".{target.name}.{secrets.token_hex(8)}.old")
    exists = target.exists()
    if exists:
        os.replace(target, backup)
    try:
        os.replace(staged, target)
    except BaseException:
        if exists:
            os.replace(backup, target)
        raise
    if exists:
        shutil.rmtree(backup)


def yaml_text(document: dict) -> str:
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def read_yaml(path: Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        raise ValueError(f"expected a YAML mapping: {path}")
    return document


def asset_path(relative: str) -> Path:
    """Wheel assets, or this standalone project's assets in an editable installation."""
    package = Path(__file__).resolve().parent
    installed = package / "assets" / relative
    return installed if installed.exists() else package.parents[1] / relative


#: The engine's own default for one round's wall clock, imported rather than restated: this
#: face records a number the engine will read back, and two defaults would eventually differ.
DEFAULT_CALL_TIMEOUT = int(Settings.model_fields["compile_call_timeout"].default or 600)
#: Six hours. Past that a wall clock stops being a guard — a harness that hung at breakfast
#: would still be holding its lane at lunch — and the engine's own bound (0 = no timeout at
#: all) is not offered here for the same reason: an unattended round with no clock on it
#: holds its lane until somebody notices.
MAX_CALL_TIMEOUT = 21_600


def validated_timeout(value: str, key: str = "compile_call_timeout") -> int:
    """One round's wall clock in whole seconds, or a refusal naming the bounds.

    Refused at the face in the same one-line shape a bad effort gets, and again on the record
    (the field's own `ge`/`le`), so a hand-edited `library.yaml` is refused on load too."""
    try:
        seconds = int(str(value).strip())
    except ValueError:
        raise ValueError(f"{key} must be a whole number of seconds") from None
    if not 1 <= seconds <= MAX_CALL_TIMEOUT:
        raise ValueError(
            f"{key} must be between 1 and {MAX_CALL_TIMEOUT} seconds "
            f"(the engine's own default is {DEFAULT_CALL_TIMEOUT})"
        )
    return seconds


def validated_effort(value: str, key: str = "reasoning_effort") -> str:
    """One reasoning effort the harness will accept, or a refusal naming the whole set.

    The set is the service's own (`AGENT_REASONING_EFFORTS`), imported rather than restated:
    a value this face accepted and the engine's settings refused would be a library whose
    engine dies at start, with the reason in a process the Owner is not looking at.
    """
    effort = value.strip()
    if effort and effort not in AGENT_REASONING_EFFORTS:
        raise ValueError(
            f"{key} must be one of {', '.join(AGENT_REASONING_EFFORTS)}, "
            + ("or empty to inherit reasoning_effort" if key != "reasoning_effort"
               else "or empty for the harness default")
        )
    return effort


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Install(Model):
    pkchome: str = ""
    version: str = __version__


class Ports(Model):
    postgres: int = Field(ge=1, le=65535)
    qdrant: int = Field(ge=1, le=65535)
    meili: int = Field(ge=1, le=65535)
    rustfs: int = Field(ge=1, le=65535)
    # The shared renderer also publishes these two auxiliary service ports.
    qdrant_grpc: int = Field(ge=1, le=65535)
    rustfs_console: int = Field(ge=1, le=65535)

    @model_validator(mode="after")
    def distinct(self):
        values = self.model_dump().values()
        if len(set(values)) != len(type(self).model_fields):
            raise ValueError("middleware ports must be distinct")
        return self


class InfraConfig(Model):
    compose_project: str = "pkc-personal"
    data_dir: str
    ports: Ports
    pg_password: str = Field(default_factory=lambda: secrets.token_urlsafe(24), repr=False)
    meili_key: str = Field(default_factory=lambda: secrets.token_urlsafe(24), repr=False)
    rustfs_access_key: str = Field(default_factory=lambda: secrets.token_hex(12), repr=False)
    rustfs_secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)


class Choices(Model):
    backend: Backend = "codex"
    language: Language = "en"
    semantic_retrieval: bool = False
    embedding: str = "openrouter:openai/text-embedding-3-small"
    # The posture this library's worker takes under an agent executor (design §4.10). True —
    # today's behaviour — is the unattended one: the worker claims a compile job, opens its
    # draft and hands it to a harness it launches. False is the attended one: agent compile
    # and evolve jobs stay queued for the Owner's own `pkc draft open`, so a Steward at the
    # terminal and the worker never reach for the same job. It is a recorded choice per
    # library (§4.7) rather than an env file, and `home_environment` is what states it.
    unattended: bool = True
    # WHICH model this library's rounds run, and how hard it thinks. Empty leaves both to the
    # harness — which means the Owner's global harness configuration, because the launcher
    # seeds each job's config home from it. Naming them here is how a library is compiled at
    # one model and effort while the Owner's own terminal stays at another; `home_environment`
    # states them, and `set_config` restarts the engine so a running launcher obeys them.
    model: str = ""
    reasoning_effort: str = ""
    # The effort of EPISODES rounds alone (L2 boundaries for one source): a simple judgement
    # that costs a compile round's context when it thinks at a compile's effort. Empty
    # inherits `reasoning_effort`.
    reasoning_effort_episodes: str = ""
    # How long ONE launch of a round may take before it is reaped (the engine's
    # `COMPILE_CALL_TIMEOUT`, which also bounds an API model's call). A recorded choice for
    # the same reason the two above are: on one real machine successful compile rounds
    # averaged 474 s under the 600 s default and two were reaped at the wall, so the Owner
    # raised it — by hand-editing `engine/engine.yaml`, which is a durable answer only until
    # something renders that directory again. `set_config` writes the same key surgically
    # and restarts the engine, because the engine reads its directory once, at start.
    compile_call_timeout: int = Field(
        default=DEFAULT_CALL_TIMEOUT, ge=1, le=MAX_CALL_TIMEOUT
    )

    @field_validator("reasoning_effort", "reasoning_effort_episodes")
    @classmethod
    def known_effort(cls, value: str, info: ValidationInfo) -> str:
        """Checked on the record, so a hand-edited `library.yaml` is refused on load too."""
        return validated_effort(value, info.field_name)


#: Directories that hold scratch work rather than projects. They are the DEFAULT exclusions,
#: which means the Owner can drop them; the home and the libraries cannot be dropped, and are
#: excluded by mechanism in the converter (`steward_roots`) rather than by a pattern here.
DEFAULT_SYNC_EXCLUDE = ["/private/tmp/**", "/tmp/**", "/private/var/**", "/var/folders/**"]


class SyncConfig(Model):
    interval_minutes: int = Field(default=15, ge=1)
    enabled: bool = True
    # Glob patterns matched against a project's resolved directory. They matter most once the
    # scope is wider than a named directory: `watch add --all` reaches every project either
    # harness ever opened, and thousands of those are dead scratch directories.
    exclude: list[str] = Field(default_factory=lambda: list(DEFAULT_SYNC_EXCLUDE))
    # What a pending increment must hold before it is ingested rather than held. The floors
    # are the converter's own (`triage`): three Owner turns is where a session stops being an
    # errand, and a length below zero or an acknowledgement limit below one word is not a
    # threshold at all. Configuration, so a library can ask for more without a code change.
    min_owner_turns: int = Field(default=3, ge=3)
    min_owner_chars: int = Field(default=200, ge=0)
    ack_max_words: int = Field(default=1, ge=1)
    # How much Owner+agent text one ingested part may carry. A bound on a compile ROUND's
    # context, never a judgement about the material: a longer increment is cut into
    # consecutive parts at Owner turns (`agent_sessions.split_parts`) and every part is
    # ingested and compiled in order. The floor keeps a typo from cutting every session into
    # one-exchange parts.
    max_part_chars: int = Field(default=400_000, ge=1000)


class Config(Model):
    install: Install
    infra: InfraConfig
    defaults: Choices = Field(default_factory=Choices)
    sync: SyncConfig = Field(default_factory=SyncConfig)


class Home:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.environ.get("PKC_HOME") or "~/.pkc").expanduser().resolve()

    def ensure_layout(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        for name in ("infra", "run", "data", "libraries"):
            (self.path / name).mkdir(exist_ok=True)

    @property
    def configured(self) -> bool:
        return (self.path / "config.yaml").is_file()

    @property
    def config(self) -> Config:
        if not self.configured:
            raise ValueError("home is not configured; run pkchome setup --answers <yaml>")
        return Config.model_validate(read_yaml(self.path / "config.yaml"))

    def initialize(self, defaults: Choices | None = None) -> Config:
        if self.configured:
            return self.config
        self.ensure_layout()
        ports = Ports(**dict(zip(Ports.model_fields, probe_free_ports(6), strict=True)))
        config = Config(
            install=Install(pkchome=shutil.which("pkchome") or sys.argv[0]),
            infra=InfraConfig(data_dir=str(self.path / "data"), ports=ports),
            defaults=defaults or Choices(language="zh" if os.environ.get("LANG", "").startswith("zh") else "en"),
        )
        self.save_config(config)
        return config

    def save_config(self, config: Config) -> None:
        self.ensure_layout()
        atomic_write(self.path / "config.yaml", yaml_text(config.model_dump(mode="json")))

    def credentials(self) -> dict[str, str]:
        path = self.path / "credentials"
        if not path.is_file():
            return {}
        entries = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or not KEY_PATTERN.fullmatch(key):
                raise ValueError("invalid credentials file; expected KEY=value lines")
            entries[key] = value
        return entries

    def set_credential(self, key: str, value: str) -> None:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError("credential name must match [A-Z][A-Z0-9_]*")
        if any(character in value for character in "\r\n\0"):
            raise ValueError("a credential must be a single line")
        entries = self.credentials()
        entries[key] = value
        atomic_write(self.path / "credentials", "".join(f"{k}={entries[k]}\n" for k in sorted(entries)))
        from pkc_personal.library import libraries

        for library in libraries(self):
            library.record_step("credentials")

    @property
    def current(self) -> str | None:
        path = self.path / "current"
        return (path.read_text(encoding="utf-8").strip() or None) if path.is_file() else None
