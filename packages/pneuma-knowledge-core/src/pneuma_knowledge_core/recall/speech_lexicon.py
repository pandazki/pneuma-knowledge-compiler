"""Rebuildable speech spelling hints. They are names, never knowledge or instructions."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..prompts import prompt

VERSION = 1


class ProposedTerm(BaseModel):
    term: str = Field(max_length=80)
    reason: Literal["coined", "proper_name", "mixed_language", "acronym"]
    risk: Literal[1, 2, 3]


class ExtractedTerms(BaseModel):
    terms: list[ProposedTerm] = Field(default_factory=list, max_length=40)


def spelling(value: object) -> str:
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= 80:
        return ""
    if any(ord(c) < 32 or c in '<>{}[]' for c in value):
        return ""
    return " ".join(unicodedata.normalize("NFC", value).split())


def key(term: str) -> str:
    return unicodedata.normalize("NFKC", term).casefold()


def occurs(term: str, text: str) -> bool:
    # Avoid admitting a made-up acronym sliced out of a longer Latin word.
    return bool(re.search(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])", text))


def live_documents(documents):
    return sorted((d for d in documents if not d.path.startswith("archive/")
                   and not d.frontmatter.get("archived")), key=lambda d: d.path)


def digest(document) -> str:
    data = json.dumps([VERSION, document.path, document.frontmatter, document.body], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()


def maintained(document) -> list[dict]:
    """Read the future page-level metadata without writing or inventing any aliases."""
    raw = document.frontmatter.get("speech_terms", [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out = []
    for value in raw:
        row = {"term": value} if isinstance(value, str) else value
        if not isinstance(row, dict) or not (term := spelling(row.get("term"))):
            continue
        aliases = row.get("confusions", [])
        if not isinstance(aliases, list):
            aliases = []
        out.append({"term": term, "confusions": [s for a in aliases if (s := spelling(a))][:6],
                    "reason": "maintained", "risk": 3, "path": document.path})
    return out


def chunks(document, limit=12000):
    title = spelling(document.frontmatter.get("title")) or ""
    body = document.body
    # Overlap protects names crossing a chunk boundary. Every body character is scanned.
    for offset in range(0, max(1, len(body)), limit - 160):
        yield title + "\n" + body[offset:offset + limit]


async def extract(model, document, *, config=None) -> list[dict]:
    rows = []
    for text in chunks(document):
        result = await model.with_structured_output(ExtractedTerms).ainvoke(
            [SystemMessage(content=prompt("call.lexicon.extract")), HumanMessage(content=text)], config=config)
        if not isinstance(result, ExtractedTerms):
            raise ValueError("invalid_speech_lexicon_result")
        for item in result.terms:
            term = spelling(item.term)
            if term and occurs(term, text):
                rows.append({"term": term, "confusions": [], "reason": item.reason,
                             "risk": item.risk, "path": document.path})
    return rows


def render(rows: list[dict], *, max_chars=3000, max_terms=80) -> str:
    """Exact spellings, globally deduplicated; coverage count never promotes a common word."""
    merged: dict[str, dict] = {}
    for row in sorted(rows, key=lambda r: (r.get("reason") != "maintained", -r.get("risk", 1))):
        term = spelling(row.get("term"))
        if not term:
            continue
        identity = key(term)
        entry = merged.setdefault(identity, {"term": term, "confusions": []})
        for alias in row.get("confusions", []):
            if (clean := spelling(alias)) and clean not in entry["confusions"]:
                entry["confusions"].append(clean)
    # A spelling that is also a real selected term is ambiguous, not a forced correction.
    selected = set(merged)
    out = []; used = 2
    for row in merged.values():
        row["confusions"] = [a for a in row["confusions"] if key(a) not in selected][:6]
        encoded = json.dumps(row, ensure_ascii=False)
        if len(out) >= max_terms:
            break
        if used + len(encoded) + 2 > max_chars:
            continue
        out.append(row); used += len(encoded) + 2
    return json.dumps(out, ensure_ascii=False) if out else ""


class SpeechSelection(BaseModel):
    terms: list[str] = Field(default_factory=list, max_length=80)


async def curate(model, rows: list[dict]) -> list[str]:
    """Bound every model input and admit only exact, already source-checked spellings."""
    candidates = list(dict.fromkeys(r["term"] for r in rows))
    pages = {term: len({r.get("path", "") for r in rows if r["term"] == term}) for term in candidates}
    async def select(batch):
        result = await model.with_structured_output(SpeechSelection).ainvoke([
            SystemMessage(content=prompt("call.lexicon.curate")),
            HumanMessage(content=json.dumps([{ "term": t, "pages": pages[t]} for t in batch], ensure_ascii=False)),
        ])
        if not isinstance(result, SpeechSelection):
            raise ValueError("invalid_speech_selection")
        allowed = set(batch)
        return list(dict.fromkeys(t for t in result.terms if t in allowed))
    while len(candidates) > 300:
        reduced = []
        for start in range(0, len(candidates), 300):
            reduced.extend(await select(candidates[start:start + 300]))
        candidates = list(dict.fromkeys(reduced))
    return await select(candidates) if candidates else []


def validate_metadata(value: object, body: str) -> None:
    """Validate a whole page-level spelling list before a canonical write."""
    if not isinstance(value, list) or len(value) > 40:
        raise ValueError('speech_terms must be a list of at most 40 entries')
    seen = set()
    for entry in value:
        row = {'term': entry} if isinstance(entry, str) else entry
        if not isinstance(row, dict) or set(row) - {'term', 'confusions'}:
            raise ValueError('speech_terms entries must be strings or term/confusions objects')
        term = spelling(row.get('term'))
        if not term or term != row.get('term') or not occurs(term, body):
            raise ValueError('speech_terms term must be a bounded exact spelling present in the page body')
        if key(term) in seen:
            raise ValueError('speech_terms contains duplicate spellings')
        seen.add(key(term))
        aliases = row.get('confusions', [])
        if not isinstance(aliases, list) or len(aliases) > 6 or any(not spelling(a) or spelling(a) != a for a in aliases):
            raise ValueError('speech_terms confusions must contain at most 6 bounded spellings')
