"""Engine Console API — the engine directory as a readable, editable, versioned surface.

Eight endpoints over ONE directory: the derived schema (what stages and knobs exist), the
current state (files, resolved values, where each value came from, git version), one file
verbatim (the repair path when the state cannot resolve), the version history and one
version's files (what a commit held, which is what makes undo an ordinary apply), apply
(write + one commit + the blast radius of what changed), and the Prompt Studio's pair —
the prompt surfaces resolved against this directory's overlay map, and a model-assisted
rewrite of one clause that never touches the disk.

**Deployment-scoped, not per-user, by design.** Every other surface in this service is
`/v1/users/{user_id}/…` because knowledge is per-tenant (invariant I1). The engine directory
is not knowledge — it is the deployment's own configuration, one per installation, and the
scaffold that ships it is single-owner. There is no user_id here because there is nothing
here that belongs to a user; I1 is untouched, since no user's data is reachable through
these routes.

Activated only when `PNEUMA_KNOWLEDGE_ENGINE_DIR` is set: with no engine directory every
route below is a 404, so a deployment that never adopted the concept has no new surface.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ...engine import (
    Change,
    EngineFileError,
    EngineGitError,
    EngineHeadMismatch,
    EnginePathError,
    EngineUnknownCommit,
    PromptRewrite,
    active_language,
    apply_changes,
    commit_files,
    history,
    load_schema,
    read_engine_directory,
    read_engine_file,
    read_overlays,
    resolve_engine,
    rewrite_messages,
    surface_payload,
    version,
)
from ...settings import Settings

router = APIRouter(prefix="/v1/engine", tags=["engine"])

# One apply at a time per deployment. `to_thread` hands each request its own thread, which is
# the opposite of mutual exclusion: two applies could interleave between writing files and
# `git add`/`commit` and produce a commit attributed to the wrong change set. The engine
# directory is one directory with one git index, so the critical section is the whole
# precondition → write → commit sequence, and it is process-wide rather than per-request.
_APPLY_LOCK = asyncio.Lock()


def _settings(request: Request) -> Settings:
    """The running deployment's settings.

    Read off `app.state.settings` rather than the app context: the engine surface touches no
    middleware, so it must stay serveable (and testable) without a live Postgres/Qdrant/Meili
    context behind it.
    """
    return request.app.state.settings


def _engine_dir(request: Request) -> Path:
    configured = _settings(request).engine_dir.strip()
    if not configured:
        raise HTTPException(
            status_code=404,
            detail=(
                "this deployment has no engine directory "
                "(set PNEUMA_KNOWLEDGE_ENGINE_DIR to serve the Engine Console)."
            ),
        )
    return Path(configured).expanduser()


class VersionOut(BaseModel):
    head: str | None
    dirty: bool


class StateOut(BaseModel):
    # engine-relative path → file content. Documents (the contract, the owner profile) live
    # here and only here: a document has no resolved scalar value, it IS a file.
    files: dict[str, str]
    # engine-relative path → why it is NOT in `files` (oversized, not UTF-8, unreadable).
    # An explicit gap, because a silent one reads as an empty file and gets overwritten.
    skipped: dict[str, str] = {}
    # "<stage>.<key>" → the value the framework would actually use, coerced through Settings.
    values: dict[str, Any]
    # "<stage>.<key>" → "env" | "engine" | "default": which precedence level supplied it.
    resolution: dict[str, str]
    # True when THIS process cannot run the model roles the engine names (an openrouter
    # spec without OPENROUTER_API_KEY): the models stage shows the state as a quiet
    # notice instead of the engine hiding its values. Values above stay the engine's
    # durable truth either way.
    keyless: bool = False
    version: VersionOut


class FileOut(BaseModel):
    """One engine file as it is on disk. `path` is the canonical spelling, echoed back."""

    path: str
    content: str


class CommitOut(BaseModel):
    sha: str
    label: str
    at: str
    files: list[str]


class CommitFilesOut(BaseModel):
    """One version's engine files, verbatim. `sha` is the full id, echoed back resolved."""

    sha: str
    # engine-relative path → content as of that commit. Only what a read of the directory
    # would also hand back: no dotfiles, nothing oversized, nothing that is not UTF-8 text.
    files: dict[str, str]


class ChangeIn(BaseModel):
    path: str
    content: str


class ApplyIn(BaseModel):
    changes: list[ChangeIn] = Field(min_length=1)
    # A label is the version's name in the timeline, so it is required and short. Length is
    # enforced here rather than trimmed later: silently truncating someone's label would make
    # the history say something they did not write.
    label: str = Field(min_length=1, max_length=60)
    # The HEAD this change set was composed against. Optional so the CLI and any older client
    # keep working; supplied by the console, where two tabs editing the same file is the
    # normal case and a silent last-write-wins would erase the first tab's version.
    expected_head: str | None = None


class EffectOut(BaseModel):
    key: str
    apply: str


class ApplyOut(BaseModel):
    sha: str
    effects: list[EffectOut]


class LocalizedOut(BaseModel):
    en: str
    zh: str


class PromptSegmentOut(BaseModel):
    """One catalog key inside one surface, with everything needed to edit it in place."""

    key: str
    label: LocalizedOut
    # WHEN the model receives this clause, in words. None for a clause whose position in an
    # assembled prompt already answers that; a sentence for every fragment and variant,
    # whose position answers nothing.
    context: LocalizedOut | None
    framework_text: str
    # None means "the framework wording is what the model sees" — distinct from "" , which
    # is a deployment that deliberately overrode this clause with nothing.
    override_text: str | None
    # The named placeholders the framework text declares; an override must keep them all.
    placeholders: list[str]
    # The other surfaces this same key composes into — rewriting it moves them too.
    shared_with: list[str]


class PromptSurfaceOut(BaseModel):
    """One model-visible prompt, or one family of independently emitted clauses.

    `kind` decides which: `assembled` surfaces carry the bytes a composition function
    really produces (byte-pinned in core), `fragments` surfaces carry empty assembled
    strings, because their clauses never reach the model as one block of text and joining
    them would show prose nobody ever received.
    """

    id: str
    group: str
    kind: Literal["assembled", "fragments"]
    title: LocalizedOut
    summary: LocalizedOut
    # Set when the assembled text is a runtime TEMPLATE rather than a finished message —
    # values substituted per call (the contract in force, the owner profile), a clause a knob
    # picks between, a human turn that carries the round's data. `null` means the bytes below
    # really are what the model receives, and only then may a reader be told so.
    note: LocalizedOut | None
    segments: list[PromptSegmentOut]
    assembled_framework: str
    assembled_effective: str


class PromptsOut(BaseModel):
    surfaces: list[PromptSurfaceOut]


class RewriteIn(BaseModel):
    key: str = Field(min_length=1, max_length=256)
    intent: str = Field(min_length=1, max_length=4000)
    locale: Literal["zh", "en"] = "en"


class RewriteOut(BaseModel):
    draft: str
    notes: str


@router.get("/schema")
async def get_engine_schema(request: Request) -> dict[str, Any]:
    """The engine schema: stages, knobs (with defaults, env names, apply semantics), edges.

    Served from the committed asset, which is generated from `Settings` metadata + the stage
    map and pinned in sync by the test suite — so the picture the console draws cannot drift
    from the code that honors it.
    """
    _engine_dir(request)
    return load_schema()


@router.get("/state", response_model=StateOut)
async def get_engine_state(request: Request) -> StateOut:
    """Everything one read of the engine directory yields, as it is on disk right now.

    Deliberately re-read per request instead of reported off the running process's settings:
    right after an apply the files are the truth, and a knob whose apply semantics say
    `restart` should show its NEW value next to a badge saying a restart is pending — not the
    stale value the process happens to still be using.
    """
    root = _engine_dir(request)
    try:
        # os.environ, not the boot Settings: "which level supplied this value" is a question
        # about the live process environment, and that is where it is answered.
        resolved = await asyncio.to_thread(resolve_engine, root, dict(os.environ))
        directory = await asyncio.to_thread(read_engine_directory, root)
        current = await asyncio.to_thread(version, root.expanduser().resolve())
    except (EngineFileError, EnginePathError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EngineGitError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    from ...wiring import usable_model_name

    return StateOut(
        files=directory.files,
        skipped=directory.skipped,
        values=resolved.values,
        resolution=resolved.resolution,
        keyless=not usable_model_name(Settings(**resolved.overrides), "recall"),
        version=VersionOut(head=current.head, dirty=current.dirty),
    )


@router.get("/file", response_model=FileOut)
async def get_engine_file(
    request: Request, path: str = Query(..., min_length=1, max_length=512)
) -> FileOut:
    """One engine file, verbatim — the repair path when `/state` cannot resolve.

    `/state` refuses to guess at a broken engine file, which is right, and leaves the console
    with nothing to edit, which is not. This route answers per file with no resolution
    involved, so the loop "read the file → fix it → apply" closes inside the console instead of
    requiring somebody who already knows what the file used to say. Addressing is the same as
    an apply's: one canonical spelling, nothing outside the directory, no dotfiles.
    """
    root = _engine_dir(request)
    try:
        canonical, content = await asyncio.to_thread(read_engine_file, root, path)
    except EnginePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"no such engine file: {exc.args[0] if exc.args else path}"
        ) from exc
    except EngineFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileOut(path=canonical, content=content)


@router.get("/prompts", response_model=PromptsOut)
async def get_engine_prompts(request: Request) -> PromptsOut:
    """Every model-visible prompt surface, resolved against THIS directory's overlays.

    The unit of override stays the catalog key; the unit of understanding becomes the
    surface — the assembled prompt a key lands in, rendered twice (framework wording and
    effective wording) so a person can read what changing a clause actually does.

    Resolved off the overlay file on disk, not off the running process's registered
    overrides: the process booted with whatever engine directory it was pointed at, and
    the studio has to show the one it is editing. The client's unsaved draft stays
    client-side and flows through the ordinary apply, exactly as the rest of the console's
    editing does.

    `framework_text` follows this directory's ACTIVE LANGUAGE PACK, because that is what the
    framework emits here: below the pack there is no author, only the framework. Showing the
    English default as "framework" under a Chinese engine would present the pack's own
    sentences as somebody's override, and every override in the studio would read as a diff
    against prose the model never sees.
    """
    root = _engine_dir(request)
    try:
        language = await asyncio.to_thread(active_language, root, dict(os.environ))
        overlays = await asyncio.to_thread(read_overlays, root)
        surfaces = await asyncio.to_thread(surface_payload, overlays, language=language)
    except (EngineFileError, EnginePathError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PromptsOut(surfaces=surfaces)


@router.post("/prompts/rewrite", response_model=RewriteOut)
async def post_engine_prompt_rewrite(request: Request, body: RewriteIn) -> RewriteOut:
    """Draft a replacement clause with the deployment's recall-role model. Writes nothing.

    The draft goes back to the client and through the normal draft → review → labelled
    apply, like every other edit: an assistant that could commit its own wording would put
    model output into the versioned unit without anybody reading it. The apply path's
    placeholder gate is what finally accepts or refuses whatever comes back from here.

    A keyless deployment gets 503 rather than a 500 out of the model builder — browsing
    and editing stay fully served, and only the assistance is unavailable.
    """
    _engine_dir(request)
    settings = _settings(request)
    from pneuma_knowledge_core.prompts import default_catalog

    if body.key not in default_catalog():
        raise HTTPException(
            status_code=400,
            detail=(
                f"{body.key!r} is not a prompt-catalog key, so there is no framework "
                "wording to rewrite."
            ),
        )
    # Local import: the engine surface stays importable (and testable) without the model
    # stack, the same way it stays serveable without Postgres/Qdrant/Meili.
    from ...wiring import build_chat_model_for, usable_model_name

    keyless = (
        "the prompt rewriter needs a configured chat model — this deployment is running "
        "keyless (browsing and editing stay fully served). Set OPENROUTER_API_KEY (or a "
        "PNEUMA_KNOWLEDGE_LLM_MODEL* spec) and restart."
    )
    if not usable_model_name(settings, "recall"):
        raise HTTPException(status_code=503, detail=keyless)
    root = _engine_dir(request)
    try:
        overlays = await asyncio.to_thread(read_overlays, root)
        # The engine's own prompt language, not the console's UI locale: the clause is written
        # back into that language pack, so it decides both the wording the rewriter is shown
        # and the language it must answer in. `locale` stays who reads the one-line notes.
        language = await asyncio.to_thread(active_language, root, dict(os.environ))
    except (EngineFileError, EnginePathError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        model = build_chat_model_for(settings, "recall")
    except RuntimeError as exc:  # e.g. openrouter:<model> with no key
        raise HTTPException(status_code=503, detail=f"{keyless} ({exc})") from exc
    system, human = rewrite_messages(
        body.key, body.intent, body.locale, overlays, language=language
    )
    # include_raw so a prose reply degrades to an explicit 502 rather than to a TypeError
    # on `None.draft` — the same soft-degrade shape the coverage audit uses.
    structured = model.with_structured_output(PromptRewrite, include_raw=True)
    envelope = await structured.ainvoke(
        [SystemMessage(system), HumanMessage(human)],
        config={"run_name": "engine.prompts.rewrite"},
    )
    result = envelope.get("parsed") if isinstance(envelope, dict) else envelope
    if result is None or not result.draft.strip():
        raise HTTPException(
            status_code=502,
            detail=(
                "the rewriter returned no usable clause. Nothing was written; try a more "
                "specific intent, or edit the clause by hand."
            ),
        )
    return RewriteOut(draft=result.draft, notes=result.notes)


@router.get("/history", response_model=list[CommitOut])
async def get_engine_history(
    request: Request, limit: int = Query(default=50, ge=1, le=500)
) -> list[CommitOut]:
    """The engine repository's commits, newest first — one per apply."""
    root = _engine_dir(request).expanduser().resolve()
    try:
        commits = await asyncio.to_thread(history, root, limit)
    except EngineGitError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return [
        CommitOut(sha=c.sha, label=c.label, at=c.at, files=c.files) for c in commits
    ]


@router.get("/history/{sha}/files", response_model=CommitFilesOut)
async def get_engine_history_files(request: Request, sha: str) -> CommitFilesOut:
    """One version's engine files, as that commit had them — the read half of "undo".

    The timeline said what changed and when; it could not say what a file used to hold, so
    undoing an apply meant remembering the old value by hand. This answers that, and undo stays
    the ordinary path: load a version's content into the draft, review it, apply it with a
    label. No revert primitive, no history rewrite, nothing new in versioning — one more commit
    forward, which is the only way this repository ever moves.

    A sha the repository does not have is a 404, including one that is not a hex object id at
    all: the route resolves a commit, it does not evaluate git's revision grammar.
    """
    root = _engine_dir(request).expanduser().resolve()
    try:
        full, files = await asyncio.to_thread(commit_files, root, sha)
    except EngineUnknownCommit as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EngineGitError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return CommitFilesOut(sha=full, files=files)


@router.post("/apply", response_model=ApplyOut)
async def post_engine_apply(request: Request, body: ApplyIn) -> ApplyOut:
    """Write the changes and commit them as one version; report what actually changed.

    Validation is total and happens before the first byte is written (path addressing,
    key-shaped content, stage-file shape), so a rejected apply leaves the engine directory
    exactly as it was. One `to_thread` hop for the whole write-then-commit sequence keeps it
    atomic in one thread rather than interleaved mid-commit, and the deployment-wide lock
    keeps a second apply from starting inside it. `expected_head` mismatches are 409: the
    caller's read is stale, which is a different thing from its request being wrong.
    """
    root = _engine_dir(request)
    changes = [Change(path=c.path, content=c.content) for c in body.changes]
    try:
        async with _APPLY_LOCK:
            sha, effects = await asyncio.to_thread(
                apply_changes, root, changes, body.label, body.expected_head
            )
    except EngineHeadMismatch as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (EnginePathError, EngineFileError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EngineGitError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ApplyOut(
        sha=sha, effects=[EffectOut(key=e.key, apply=e.apply) for e in effects]
    )
