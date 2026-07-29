#!/usr/bin/env python3
"""Read-only deterministic QA for OPC 84-day v2 groups."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

VERSION = "opc-84d-v2-deterministic/3"
FLOORS = {"meeting": (1200, 12), "document_library": (1800, 8), "im": (1000, 18), "email": (1200, 4)}
FAMILY = {"meetings": "meeting", "document_library": "document_library", "im": "im", "email": "email"}
BRANDS = re.compile(r"\b(?:openai|google|microsoft|apple|amazon|meta|slack|zoom|obsidian|nvidia|tesla)\b", re.I)
SECRET = re.compile(r"(?:\b(?:api[_-]?key|secret|password|access[_-]?token)\b\s*[:=]|\b(?:sk|ghp|xox[baprs])[-_][A-Za-z0-9-]{12,}|\bbearer\s+[A-Za-z0-9._-]{12,})", re.I)
MAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
ROOT = Path(__file__).resolve().parents[1]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _normal(text: str) -> str:
    return re.sub(r"[\"'“”‘’.,;:!?()\[\]{}]", "", re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold())).strip()


def _grams(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", _normal(text))
    return {tuple(words[i:i + 5]) for i in range(len(words) - 4)}


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values(): yield from _walk(child)
    elif isinstance(value, list):
        for child in value: yield from _walk(child)


def _find(code: str, message: str, family: str | None = None, ids: list[str] | None = None, spans: list[dict[str, int]] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "severity": "error", "message": message}
    if family: result["source_family"] = family
    if ids: result["authored_ids"] = ids
    if spans: result["spans"] = spans
    return result


def _markdown_body(markdown: str, kind: str) -> str:
    """Return visible prose without Markdown-only structure for char floors."""

    if kind == "heading":
        return ""
    lines = markdown.splitlines()
    if lines and lines[0].strip() == "---":
        closing = next(
            (index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"),
            None,
        )
        if closing is not None:
            lines = lines[closing + 1 :]
    visible: list[str] = []
    in_fence = False
    for raw_line in lines:
        line = raw_line.strip()
        if re.match(r"^(```|~~~)", line):
            in_fence = not in_fence
            continue
        if not line:
            continue
        if re.match(r"^#{1,6}\s+", line):
            continue
        if re.match(r"^(?:[-*_]\s*){3,}$", line):
            continue
        if re.match(r"^\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?$", line):
            continue
        line = re.sub(r"^(?:>\s*)+", "", line)
        if re.match(r"^\[![^\]]+\]\s*$", line):
            continue
        line = re.sub(r"^(?:[-+*]|\d+[.)])\s+", "", line)
        line = re.sub(r"^\[[ xX]\]\s+", "", line)
        line = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = line.replace("|", " ")
        line = re.sub(r"(?<!\\)[*_~`]", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            visible.append(line)
    return " ".join(visible)


def _email_body(text: str) -> str:
    visible: list[str] = []
    quoted_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if re.match(
            r"^(?:-{2,}\s*(?:original message|forwarded message)\s*-{2,}|on .+ wrote:)$",
            line,
            re.I,
        ):
            quoted_section = True
            continue
        if quoted_section or line.startswith(">"):
            continue
        if line:
            visible.append(line)
    return " ".join(visible)


def _document_block_records(group: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_block_ids: set[str] = set()
    for source in group.get("sources", {}).get("document_library", []):
        for document in source.get("documents", []):
            full_markdown = document.get("full_markdown", "")
            cursor = 0
            for block in document.get("visible_blocks", []):
                block_id = block.get("block_id", "unknown")
                markdown = block.get("markdown", "")
                position = full_markdown.find(markdown, cursor)
                anywhere = full_markdown.find(markdown)
                duplicate_id = block_id in seen_block_ids
                seen_block_ids.add(block_id)
                if position >= 0:
                    cursor = position + len(markdown)
                status = (
                    "duplicate_id"
                    if duplicate_id
                    else "mapped"
                    if position >= 0
                    else "out_of_order"
                    if anywhere >= 0
                    else "unmapped"
                )
                records.append(
                    {
                        "document_id": document.get("document_id", "unknown"),
                        "block_id": block_id,
                        "block": block,
                        "status": status,
                        "position": position,
                        "raw_chars": len(markdown),
                        "body_text": _markdown_body(markdown, block.get("kind", "other")),
                        "full_markdown_chars": len(full_markdown),
                    }
                )
    return records


def _units(
    group: dict[str, Any],
    document_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    result = []
    def add(family: str, artifact: str, text: str, auth: dict[str, Any], raw_text: str | None = None):
        if text: result.append({"source_family": family, "artifact_id": artifact, "text": text, "raw_text": text if raw_text is None else raw_text, "authored_id": auth.get("authored_id", "unknown"), "content_class": auth.get("content_class", "ambiguous"), "author_role": auth.get("author_role", "unknown")})
    s = group.get("sources", {})
    for src in s.get("meetings", []):
        for item in src.get("utterances", []): add("meeting", src.get("source_id", "meeting"), item.get("text", ""), item.get("authorship", {}))
    for record in document_records or _document_block_records(group):
        item = record["block"]
        if record["status"] == "mapped" and item.get("kind") != "heading":
            add(
                "document_library",
                record["document_id"],
                record["body_text"],
                item.get("authorship", {}),
                item.get("markdown", ""),
            )
    for src in s.get("im", []):
        for convo in src.get("conversations", []):
            for item in convo.get("messages", []): add("im", convo.get("conversation_id", "conversation"), item.get("full_text", ""), item.get("authorship", {}))
    for src in s.get("email", []):
        for thread in src.get("threads", []):
            for item in thread.get("messages", []):
                raw_text = item.get("full_text", "")
                add(
                    "email",
                    thread.get("thread_id", "thread"),
                    _email_body(raw_text),
                    item.get("authorship", {}),
                    raw_text,
                )
    return result


def _paths(path: Path) -> list[Path]:
    if not path.exists(): return []
    return [path] if path.is_file() else sorted(item for item in path.rglob("*.json") if item.is_file())


def _when(value: str) -> date | None:
    try: return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try: return date.fromisoformat(value)
        except ValueError: return None


def _beats_findings(group: dict[str, Any], beats: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if beats is None: return [], None
    group_id = group.get("group_id")
    days = sorted((item for item in beats.get("days", []) if item.get("group_id") == group_id), key=lambda item: item.get("date", ""))
    evidence: dict[str, Any] = {"group_id": group_id, "days": [{"date": item.get("date"), "day_id": f"D{item.get('day_index', 0):02d}", "source_plan": item.get("source_plan", []), "fact_ids": item.get("fact_ids", []), "continuity_ids": item.get("continuity_ids", [])} for item in days]}
    findings: list[dict[str, Any]] = []
    try:
        window = group["group_window"]; expected_dates = [date.fromisoformat(item["date"]) for item in days]
        actual_dates = [date.fromisoformat(window["starts_on"]) + timedelta(days=index) for index in range(window["day_count"])]
        if len(days) != 3 or actual_dates != expected_dates: findings.append(_find("beats_window", "group window does not exactly match its three daily-beats dates"))
    except (KeyError, TypeError, ValueError):
        findings.append(_find("beats_window", "daily-beats dates or group window are not parseable"))
    expected = {"meeting": 0, "document_library": 0, "im": 0, "email": 0}
    for day in days:
        for item in day.get("source_plan", []):
            kind = str(item.get("type", "")).casefold()
            if kind in expected: expected[kind] += 1
    actual = {"meeting": len(group.get("sources", {}).get("meetings", [])), "document_library": len(group.get("sources", {}).get("document_library", [])), "im": len(group.get("sources", {}).get("im", [])), "email": len(group.get("sources", {}).get("email", []))}
    evidence["expected_source_counts"] = expected; evidence["actual_source_counts"] = actual
    if actual != expected: findings.append(_find("beats_source_count", "actual source counts do not exactly match the three-day source plan"))
    day_ids = {f"D{item.get('day_index', 0):02d}" for item in days}
    final_facts = set(days[-1].get("fact_ids", [])) if days else set()
    final_continuity = set(days[-1].get("continuity_ids", [])) if days else set()
    all_days = beats.get("days", [])
    first_index = next((index for index, item in enumerate(all_days) if days and item.get("date") == days[0].get("date")), 0)
    before_continuity = set(all_days[first_index - 1].get("continuity_ids", [])) if days and first_index else set()
    scope = group.get("story_scope", {}); evidence["permitted_day_ids"] = sorted(day_ids); evidence["permitted_fact_ids"] = sorted(final_facts); evidence["permitted_continuity_ids"] = sorted(final_continuity)
    checks = (("allowed_story_beat_ids", day_ids), ("known_fact_ids", final_facts), ("open_continuity_ids", final_continuity), ("new_continuity_ids", final_continuity - before_continuity))
    for field, permitted in checks:
        excess = sorted(set(scope.get(field, [])) - permitted)
        if excess: findings.append(_find("beats_scope", f"{field} exceeds daily-beats truth: {', '.join(excess)}"))
    return findings, evidence


def _validate_group(group: dict[str, Any], validator: Draft202012Validator, prior: list[dict[str, Any]], beats: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    findings = [_find("schema", err.message) for err in sorted(validator.iter_errors(group), key=str)]
    try:
        window = group["group_window"]; start = date.fromisoformat(window["starts_on"]); end = date.fromisoformat(window["ends_on"])
        if window["day_count"] not in {2, 3} or (end - start).days + 1 != window["day_count"]: findings.append(_find("window", "group window must span exactly its declared 2 or 3 days"))
    except (KeyError, TypeError, ValueError):
        start = end = None; findings.append(_find("window", "group window is not parseable"))
    for node in _walk(group):
        for key, value in node.items():
            if (key.endswith("_at") or key == "occurred_at") and value is not None:
                parsed = _when(value) if isinstance(value, str) else None
                if parsed is None or (start and not start <= parsed <= end): findings.append(_find("timestamp", f"{key} is invalid or outside the group window"))
    sources = group.get("sources", {}); present = [name for name, items in sources.items() if items]
    if len(present) < 2: findings.append(_find("source_family_count", "at least two source families must be non-empty"))
    if not any(src.get("authorship", {}).get("content_class") == "signal" for items in sources.values() for src in items): findings.append(_find("work_signal", "at least one actual source must be signal"))
    authored = [node["authored_id"] for node in _walk(group) if "authored_id" in node]
    for identifier, count in Counter(authored).items():
        if count > 1: findings.append(_find("authored_id_duplicate", f"authored ID {identifier} appears {count} times", ids=[identifier]))
    prior_authored = {node["authored_id"] for old in prior for node in _walk(old) if "authored_id" in node}
    for identifier in sorted(set(authored) & prior_authored):
        findings.append(_find("authored_id_duplicate", f"authored ID {identifier} already exists in an accepted group", ids=[identifier]))
    scope = group.get("story_scope", {}); allowed = {"story_beat_ids": set(scope.get("allowed_story_beat_ids", [])), "fact_ids": set(scope.get("known_fact_ids", [])), "continuity_ids": set(scope.get("open_continuity_ids", [])) | set(scope.get("new_continuity_ids", []))}
    for node in _walk(group):
        for kind, values in node.get("links", {}).items() if isinstance(node.get("links"), dict) else []:
            for ref in values:
                if ref not in allowed.get(kind, set()): findings.append(_find("cross_ref_missing", f"{ref} is not permitted by story_scope"))
    for research in group.get("research_context", []):
        for identifier in research.get("applied_authored_ids", []):
            if identifier not in set(authored): findings.append(_find("research_applied_id_missing", f"research {research.get('research_ref_id')} points to unknown authored ID {identifier}", ids=[identifier]))
    for node in _walk(group):
        for key, value in node.items():
            if key in {"synthetic_address", "address"} and isinstance(value, str):
                match = MAIL.fullmatch(value)
                if match and not match.group(1).endswith(".test"): findings.append(_find("real_domain", "non-synthetic address in group metadata"))
    document_records = _document_block_records(group)
    for record in document_records:
        if record["status"] == "mapped":
            continue
        if record["status"] == "duplicate_id":
            code = "document_block_id_duplicate"
            message = (
                f"document {record['document_id']} repeats stable block ID "
                f"{record['block_id']}"
            )
        elif record["status"] == "out_of_order":
            code = "document_visible_block_out_of_order"
            message = (
                f"document {record['document_id']} block {record['block_id']} "
                "exists in full_markdown but not in visible_blocks order"
            )
        else:
            code = "document_visible_block_unmapped"
            message = (
                f"document {record['document_id']} block {record['block_id']} "
                "is not present verbatim in full_markdown"
            )
        finding = _find(
            code,
            message,
            "document_library",
            [record["block"].get("authorship", {}).get("authored_id", "unknown")],
        )
        finding["document_id"] = record["document_id"]
        finding["block_id"] = record["block_id"]
        finding["raw_chars"] = record["raw_chars"]
        findings.append(finding)
    rows = _units(group, document_records); stats: dict[str, Any] = {"source_families": {}, "body_chars": 0, "signal_chars": 0, "noise_chars": 0, "ambiguous_chars": 0, "system_noise_chars": 0, "lived_noise_chars": 0}
    for key in present:
        family = FAMILY[key]
        selected = [row for row in rows if row["source_family"] == family]; chars = sum(len(row["text"]) for row in selected); stats["source_families"][family] = {"sources": len(sources[key]), "units": len(selected), "raw_body_chars": sum(len(row["raw_text"]) for row in selected), "body_chars": chars}
        if family == "document_library":
            mapped = [
                record
                for record in document_records
                if record["status"] == "mapped"
            ]
            mapped_body = [
                record
                for record in mapped
                if record["block"].get("kind") != "heading"
            ]
            documents = [
                document
                for source in sources[key]
                for document in source.get("documents", [])
            ]
            stats["source_families"][family].update(
                {
                    "raw_full_markdown_chars": sum(
                        len(document.get("full_markdown", ""))
                        for document in documents
                    ),
                    "mapped_raw_chars": sum(
                        record["raw_chars"] for record in mapped_body
                    ),
                    "excluded_structural_chars": sum(
                        record["raw_chars"] - len(record["body_text"])
                        for record in mapped_body
                    ),
                    "unmapped_visible_block_chars": sum(
                        record["raw_chars"]
                        for record in document_records
                        if record["status"] != "mapped"
                    ),
                    "mapped_visible_blocks": len(mapped),
                    "unmapped_visible_blocks": sum(
                        record["status"] != "mapped"
                        for record in document_records
                    ),
                }
            )
        min_chars, min_units = FLOORS[family]
        if chars < min_chars or len(selected) < min_units: findings.append(_find("source_substance", f"{family} has {chars} counted body chars/{len(selected)} mapped body units; requires {min_chars}/{min_units}", family))
        if family == "meeting" and len({item.get("speaker_id") for src in sources[key] for item in src.get("utterances", [])}) < 2: findings.append(_find("source_substance", "meeting has fewer than two speakers", family))
        if family == "document_library" and sum(len(src.get("documents", [])) for src in sources[key]) < 2: findings.append(_find("source_substance", "document library has fewer than two documents", family))
        if family == "im" and sum(len(src.get("conversations", [])) for src in sources[key]) < 2: findings.append(_find("source_substance", "IM has fewer than two conversations", family))
        if family == "im" and len({item.get("sender_id") for src in sources[key] for convo in src.get("conversations", []) for item in convo.get("messages", [])}) < 3: findings.append(_find("source_substance", "IM has fewer than three senders", family))
        if family == "email" and sum(len(src.get("threads", [])) for src in sources[key]) < 2: findings.append(_find("source_substance", "email has fewer than two threads", family))
    expected = max(2400, int(sum(FLOORS[FAMILY[name]][0] for name in present) * .85 + .999))
    for row in rows:
        chars = len(row["text"]); stats["body_chars"] += chars; stats[f"{row['content_class']}_chars"] += chars
        if row["content_class"] in {"noise", "ambiguous"}: stats["system_noise_chars" if row["author_role"] == "system" else "lived_noise_chars"] += chars
    if stats["body_chars"] < expected: findings.append(_find("group_substance", f"group has {stats['body_chars']} counted body chars; requires {expected} for its present families"))
    noisy = stats["noise_chars"] + stats["ambiguous_chars"]
    if not stats["body_chars"] or not .15 <= noisy / stats["body_chars"] <= .40: findings.append(_find("noise_mix", "noise plus ambiguous body must be 15% to 40%"))
    if noisy and (stats["system_noise_chars"] / noisy > .35 or stats["lived_noise_chars"] / noisy < .40): findings.append(_find("noise_mix", "system/lived noise balance violates rubric"))
    prose = "\n".join(row["text"] for row in rows)
    for regex, code, label in ((SECRET, "prohibited_secret", "possible credential"), (BRANDS, "sensitive_brand", "sensitive brand"), (MAIL, "real_domain", "real email domain")):
        for match in regex.finditer(prose):
            if code != "real_domain" or not match.group(1).endswith(".test"): findings.append(_find(code, label, spans=[{"start": match.start(), "end": match.end()}]))
    for research in group.get("research_context", []):
        for summary in research.get("author_fact_summaries", []):
            normalized_summary = _normal(summary); summary_grams = _grams(summary)
            for row in rows:
                normalized_body = _normal(row["text"])
                match = SequenceMatcher(None, normalized_summary, normalized_body, autojunk=False).find_longest_match()
                ids = [row["authored_id"]]
                spans = [{"start": match.a, "end": match.a + match.size}, {"start": match.b, "end": match.b + match.size}]
                if match.size >= 80:
                    findings.append(_find("research_summary_overlap_contiguous", f"research {research.get('research_ref_id')} copies a long authored-prose span", row["source_family"], ids, spans))
                    continue
                body_grams = _grams(row["text"])
                if summary_grams and body_grams and len(summary_grams & body_grams) / len(summary_grams | body_grams) >= .55:
                    findings.append(_find("research_summary_overlap_ngram", f"research {research.get('research_ref_id')} has high 5-gram overlap with authored prose", row["source_family"], ids, spans))
    compared = [(group.get("group_id", "current"), row) for row in rows] + [(old.get("group_id", "prior"), row) for old in prior for row in _units(old)]
    for index, (left_group, left) in enumerate(compared):
        a = _normal(left["text"])
        if len(a) < 80: continue
        for right_group, right in compared[index + 1:]:
            b = _normal(right["text"])
            if left["source_family"] != right["source_family"] or len(b) < 80: continue
            ids = [left["authored_id"], right["authored_id"]]; spans = [{"start": 0, "end": len(left["text"])}, {"start": 0, "end": len(right["text"])}]
            if a == b: findings.append(_find("duplicate_cross_group" if left_group != right_group else "duplicate_exact", "identical or normalized body", left["source_family"], ids, spans)); continue
            x, y = _grams(left["text"]), _grams(right["text"])
            if x and y and len(x & y) / len(x | y) > .18: findings.append(_find("duplicate_ngram", "5-gram Jaccard candidate exceeds 0.18", left["source_family"], ids, spans))
    beats_findings, evidence = _beats_findings(group, beats)
    findings.extend(beats_findings)
    return findings, stats, evidence


def validate_inputs(group_paths: list[Path], schema_path: Path, accepted_dir: Path, output_path: Path, beats_path: Path | None = None) -> dict[str, Any]:
    validator = Draft202012Validator(json.loads(schema_path.read_text()), format_checker=FormatChecker())
    groups = [json.loads(path.read_text()) for path in group_paths]; prior = [json.loads(path.read_text()) for path in _paths(accepted_dir)]
    beats = json.loads(beats_path.read_text()) if beats_path else None
    reports = []; findings: list[dict[str, Any]] = []
    for group in groups:
        current, metrics, evidence = _validate_group(group, validator, prior, beats); reports.append({"group_id": group.get("group_id"), "findings": current, "metrics": metrics, "daily_beats_evidence": evidence}); findings.extend(current)
    hashes = {_portable_path(path): _hash(path) for path in group_paths}
    if beats_path: hashes[_portable_path(beats_path)] = _hash(beats_path)
    report = {"status": "draft" if findings else "structural_pass", "input_hashes": hashes, "schema_hash": _hash(schema_path), "detector": {"version": VERSION, "config": {"exact_normalized_min_chars": 80, "ngram_size": 5, "ngram_jaccard": .18, "character_count_policy": "mapped-visible-body/v2", "document_mapping": "ordered verbatim visible_blocks within full_markdown", "excluded_from_body_chars": ["frontmatter", "RFC822 headers", "Markdown headings and syntax", "email quote prefixes and quoted reply sections"]}}, "findings": findings, "groups": reports, "pending": ["semantic_near_duplicate_review", "independent_human_or_subagent_review"], "global_hooks": {"three_group_family_coverage": "pending", "uniform_source_density_review": "pending"}}
    output_path.parent.mkdir(parents=True, exist_ok=True); output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main() -> int:
    root = ROOT; parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=root / "docs/experiments/opc-84d-v2/groups")
    parser.add_argument("--schema", type=Path, default=root / "docs/experiments/opc-84d-v2/group-content.schema.json")
    parser.add_argument("--accepted-groups", type=Path, default=root / "docs/experiments/opc-84d-v2/accepted")
    parser.add_argument("--beats", type=Path, default=None, help="optional daily-beats.json ledger")
    parser.add_argument("--output", type=Path, default=root / "docs/experiments/opc-84d-v2/qa/group-qa.json")
    args = parser.parse_args(); paths = _paths(args.input)
    if not paths: parser.error("input contains no group JSON files")
    report = validate_inputs(paths, args.schema, args.accepted_groups, args.output, args.beats); print(json.dumps({"status": report["status"], "output": str(args.output)}))
    return 0 if report["status"] == "structural_pass" else 1


if __name__ == "__main__": raise SystemExit(main())
