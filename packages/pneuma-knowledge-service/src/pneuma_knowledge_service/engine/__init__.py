"""The engine directory — one versioned unit holding everything that IS this engine.

Strategy files, the compile contract, prompt overlays, the owner profile: all in one
directory with its own git repository, one commit per apply, separate from data, secrets and
machinery. `PNEUMA_KNOWLEDGE_ENGINE_DIR` points at it; unset (the default) means the engine
directory does not exist for this deployment and behavior is byte-for-byte what it was
before the concept — the settings chain adds nothing and `/v1/engine/*` returns 404.

Design authority: `docs/design/engine-console.md`. Reading order in this package:
`stage_map` (what exists) → `schema` (the derived picture) → `files` (addressing and shape)
→ `resolve` (precedence) → `apply` / `gitops` (writes) → `prompts` (the language pack the
framework's own wording arrives in, plus the Prompt Studio's read side: core's surface
registry resolved against this directory's overlay map).
"""

from __future__ import annotations

from .apply import Change, Effect, apply_changes, plan_effects, validate
from .files import (
    EngineDirectory,
    EngineFileError,
    EnginePathError,
    read_engine_directory,
    read_engine_file,
    read_engine_files,
)
from .gitops import (
    Commit,
    EngineGitError,
    EngineHeadMismatch,
    EngineUnknownCommit,
    Version,
    commit_files,
    ensure_repo,
    history,
    version,
)
from .prompts import (
    PromptRewrite,
    active_language,
    apply_prompt_stack,
    framework_catalog,
    language_pack,
    overlays_file,
    read_overlays,
    rewrite_messages,
    surface_payload,
)
from .resolve import ResolvedEngine, engine_overrides, resolve_engine
from .schema import SCHEMA_PATH, build_schema, load_schema, serialize_schema

__all__ = [
    "Change",
    "Commit",
    "Effect",
    "EngineDirectory",
    "EngineFileError",
    "EngineGitError",
    "EngineHeadMismatch",
    "EnginePathError",
    "EngineUnknownCommit",
    "PromptRewrite",
    "ResolvedEngine",
    "SCHEMA_PATH",
    "Version",
    "active_language",
    "apply_changes",
    "apply_prompt_stack",
    "build_schema",
    "commit_files",
    "engine_overrides",
    "ensure_repo",
    "framework_catalog",
    "history",
    "language_pack",
    "load_schema",
    "overlays_file",
    "plan_effects",
    "read_engine_directory",
    "read_engine_file",
    "read_engine_files",
    "read_overlays",
    "resolve_engine",
    "rewrite_messages",
    "serialize_schema",
    "surface_payload",
    "validate",
    "version",
]
