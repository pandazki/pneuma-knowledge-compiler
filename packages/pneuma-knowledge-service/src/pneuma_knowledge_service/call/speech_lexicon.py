"""Persistent, tenant-scoped derived speech lexicon; never on the call's model path."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path

from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.speech_lexicon import (
    VERSION, curate, digest, extract, live_documents, maintained, occurs, render, spelling,
)


def cache_path(settings, user_id: str) -> Path:
    root = Path(settings.engine_dir) if settings.engine_dir else Path(settings.canonical_root).parent
    tenant = hashlib.sha256(user_id.encode()).hexdigest()
    return root / "derived" / "speech-lexicons" / f"{tenant}.json"


def read(path: Path, user_id: str) -> dict:
    try:
        data = json.loads(path.read_text())
        if data.get("version") == VERSION and data.get("user_id") == user_id:
            return data
    except (OSError, ValueError, AttributeError):
        pass
    return {"version": VERSION, "user_id": user_id, "documents": {}, "confusions": {}}


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".speech-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def candidates(documents, data: dict) -> list[dict]:
    """Existing compile admission and transitional fallback, before activity ranking."""
    rows = []
    selected = set(data.get("selected_terms", []))
    for document in live_documents(documents):
        rows.extend(maintained(document))
        # An explicit page field, including [], supersedes the transitional cache.
        if "speech_terms" in document.frontmatter:
            continue
        text = str(document.frontmatter.get("title", "")) + "\n" + document.body
        for term, aliases in data.get("confusions", {}).items():
            if spelling(term) and occurs(term, text):
                rows.append({"term": term, "confusions": aliases, "reason": "maintained", "risk": 3, "path": document.path})
        for row in data.get("documents", {}).get(document.path, {}).get("terms", []):
            term = spelling(row.get("term"))
            if term and term in selected and occurs(term, text):
                row = dict(row, path=document.path)
                # Explicit operator corrections are data, never model-invented aliases.
                aliases = data.get("confusions", {}).get(term, [])
                row["confusions"] = aliases
                if aliases:
                    row["reason"] = "maintained"
                rows.append(row)
    order = {term: i for i, term in enumerate(data.get("selected_terms", []))}
    rows.sort(key=lambda row: order.get(row["term"], -1))
    for row in rows:
        if row.get("reason") != "maintained":
            row["risk"] = 1
    return rows


def vocabulary(settings, user_id: str, documents, *, today=None) -> str:
    from datetime import datetime, timezone
    from .speech_activity import ranked_candidates

    documents = list(documents)
    data = read(cache_path(settings, user_id), user_id)
    rows = ranked_candidates(settings, user_id, documents, candidates(documents, data),
                             today=today or datetime.now(timezone.utc).date())
    encoded = render(rows, preserve_order=True)
    return prompt("call.lexicon.context", terms=encoded) if encoded else ""


async def rebuild(settings, user_id, documents, model, *, model_name, confusions=None,
                  concurrency=3, on_progress=None) -> dict:
    path = cache_path(settings, user_id)
    old = await asyncio.to_thread(read, path, user_id)
    recipe = hashlib.sha256((model_name + prompt("call.lexicon.extract")).encode()).hexdigest()
    data = {"version": VERSION, "user_id": user_id, "model": model_name, "recipe": recipe,
            "documents": {}, "confusions": confusions if confusions is not None else old.get("confusions", {})}
    data["selection_recipe"] = hashlib.sha256((model_name + prompt("call.lexicon.curate")).encode()).hexdigest()
    semaphore = asyncio.Semaphore(concurrency)
    failures = []
    async def scan(document):
        previous = old.get("documents", {}).get(document.path, {})
        fingerprint = digest(document)
        if old.get("recipe") == recipe and previous.get("digest") == fingerprint:
            data["documents"][document.path] = previous
            return
        try:
            async with semaphore:
                terms = await asyncio.wait_for(extract(model, document), timeout=180)
            data["documents"][document.path] = {"digest": fingerprint, "terms": terms}
            if on_progress:
                on_progress(document.path, len(terms))
        except Exception as exc:
            failures.append({"path": document.path, "error": type(exc).__name__})
            if previous:
                # Retain prior work, but leave its old digest so the next run retries it.
                data["documents"][document.path] = previous
    await asyncio.gather(*(scan(d) for d in live_documents(documents)))
    rows = [row for page in data["documents"].values() for row in page["terms"]]
    try:
        data["selected_terms"] = await asyncio.wait_for(curate(model, rows), timeout=240)
    except Exception as exc:
        failures.append({"path": "<selection>", "error": type(exc).__name__})
        data["selected_terms"] = old.get("selected_terms", [])
    data["failures"] = failures
    await asyncio.to_thread(write, path, data)
    return data
