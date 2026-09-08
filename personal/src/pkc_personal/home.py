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
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pneuma_knowledge_service.infra.ports import probe_free_ports

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


class SyncConfig(Model):
    interval_minutes: int = Field(default=15, ge=1)
    enabled: bool = True


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
