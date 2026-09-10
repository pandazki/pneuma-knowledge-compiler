"""Incremental sync uses synthetic transcripts and a deduplicating fake ingest door."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from pkc_personal import cli, sync
from pkc_personal.library import Library, Watch, set_config, watch_project
from test_agent_sessions import (
    OWNER_TEXTS, claude_row, claude_rows, codex_message, codex_row, codex_rows, provider_files,
    read_provider, sessions, write_jsonl,
)


def add_project(files, name, *, parent=None):
    """A second synthetic project, reachable only by enumerating the harness roots."""
    project = (parent or files.project.parent) / name
    project.mkdir(parents=True, exist_ok=True)
    write_jsonl(files.claude_root / str(project).replace("/", "-") / f"{name}.jsonl", claude_rows(project))
    write_jsonl(files.codex_root / f"2026/09/02/rollout-{name}.jsonl", codex_rows(project))
    return project


@pytest.fixture
def importer(home, make_library, provider_files, monkeypatch):
    library = make_library()
    second = make_library("second")
    watch_project(library, str(provider_files.project))
    payloads, commands = [], []
    accepted = {}
    behavior = {"fail": False, "lost_response": False}

    def run(command, **kwargs):
        assert command[:7] == ["pkchome", "exec", "--library", library.state.name, "--", "pkc", "ingest"]
        commands.append(command)
        payload = json.loads(Path(command[command.index("--file") + 1]).read_text())
        payloads.append(payload)
        if behavior["fail"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="synthetic failure")
        key = sessions.digest(sessions.encoded_json(payload).encode())
        duplicate = key in accepted
        accepted.setdefault(key, f"s{len(accepted) + 1}")
        body = {"sources": [{"source_id": accepted[key], "deduplicated": duplicate}],
                "compile_jobs": [] if duplicate else [f"job-{accepted[key]}"]}
        return SimpleNamespace(returncode=0, stdout="" if behavior["lost_response"] else json.dumps(body))

    monkeypatch.setattr(sessions.subprocess, "run", run)
    def run_pass(**kwargs):
        return sessions.sync_pass(library.show(), [w.model_dump() for w in library.state.watch],
                                  claude_root=provider_files.claude_root,
                                  codex_root=provider_files.codex_root, **kwargs)

    return SimpleNamespace(library=library, second=second, run=run_pass, payloads=payloads,
                           commands=commands, accepted=accepted, behavior=behavior,
                           state=library.path / "sync-state.json")


def cursor(importer, provider="claude-code"):
    return next(entry for entry in json.loads(importer.state.read_text())["sessions"].values()
                if entry["provider"] == provider)


def append(files, provider, count=3, start=20):
    path = files.claude_file if provider == "claude-code" else files.codex_file
    with path.open("a") as stream:
        for index, text in enumerate(OWNER_TEXTS[:count], start):
            row = claude_row("user", text, index) if provider == "claude-code" else codex_message("user", text, index)
            stream.write(json.dumps(row) + "\n")


@pytest.mark.parametrize("provider", ["claude-code", "codex"])
def test_grown_held_then_continuation_and_unchanged(provider_files, importer, provider):
    first = importer.run()
    assert (first["scanned"], first["new"], first["ingested"]) == (2, 2, 2)
    before = cursor(importer, provider)
    assert importer.run()["unchanged"] == 2
    append(provider_files, provider, 1)
    held = importer.run()
    assert held["held"] == 1 and held["ingested"] == 0
    after = cursor(importer, provider)
    for key in ("exported_turns", "last_turn_id", "last_at", "source_ids", "exported_bytes"):
        assert after[key] == before[key]
    assert after["held"] == {"owner_turns": 1, "chars": len(OWNER_TEXTS[0])}
    same = importer.run()
    assert same["held"] == 1 and same["unchanged"] == 2 and same["ingested"] == 0
    append(provider_files, provider, 2, 21)
    grown = importer.run()
    assert grown["increments"] == grown["ingested"] == 1
    payload = importer.payloads[-1]
    assert len(payload["turns"]) == 3
    assert payload["metadata"]["continues"] == before["source_ids"][-1]
    assert payload["metadata"]["part"] == 2
    assert payload["metadata"]["from_turn"] == f"t{before['exported_turns'] + 1}"
    assert len(cursor(importer, provider)["source_ids"]) == 2
    assert cursor(importer, provider)["held"] is None
    assert importer.run()["ingested"] == 0


def test_timestamp_delayed_growth_never_drops_or_repeats_turns(provider_files, importer):
    importer.run()
    # These records are appended after t7, but have timestamps earlier than it.
    append(provider_files, "codex", start=2)
    report = importer.run()
    assert report["increments"] == 1
    assert [turn["text"] for turn in importer.payloads[-1]["turns"]] == OWNER_TEXTS
    assert importer.run()["ingested"] == 0


def test_rewrite_same_size_and_touched_mtime_are_not_growth(provider_files, importer):
    importer.run()
    before = cursor(importer)
    os.utime(provider_files.claude_file, (1, 1))
    assert importer.run()["unchanged"] == 2
    path = provider_files.claude_file
    path.write_bytes(path.read_bytes().replace(b"offline", b"on-line"))
    report = importer.run()
    assert report["rewritten"] == 1 and report["ingested"] == 0
    assert cursor(importer) == before
    report = importer.run(rewritten="reingest")
    assert report["rewritten"] == report["ingested"] == 1
    assert importer.payloads[-1]["metadata"]["rewritten"] is True
    assert "continues" not in importer.payloads[-1]["metadata"]
    assert importer.run()["ingested"] == 0


def test_truncation_and_identity_change_are_rewritten(provider_files, importer):
    importer.run()
    path = provider_files.claude_file
    original = path.read_bytes()
    path.write_bytes(original[:original.find(b"\n") + 1])
    assert importer.run()["rewritten"] == 1
    path.write_bytes(original.replace(b"momo-claude", b"other-session"))
    assert importer.run()["rewritten"] == 1
    assert len(importer.payloads) == 2


def disk_tree(path):
    return {str(p.relative_to(path)): p.read_bytes() if p.is_file() else None for p in path.rglob("*")}


def test_dry_run_writes_nothing_including_lock_and_migration(provider_files, importer, home):
    old = read_provider(provider_files, "claude-code")
    legacy = {sessions.session_key(old): {"sha256": sessions.digest(sessions.encoded_json(
        old.payload("lib-notes", sessions.triage(old))).encode())}}
    sessions.atomic_json(importer.state.with_name("ingested-sessions.json"), {"version": 1, "sessions": legacy})
    before = disk_tree(home.path)
    report = importer.run(dry_run=True)
    assert report["new"] == 1
    assert not importer.commands
    assert disk_tree(home.path) == before


def test_lock_is_per_library_and_refuses_concurrent_pass(importer, home):
    with sessions.sync_lock(home.path / "run/notes.sync.lock"):
        for dry_run in (False, True):
            with pytest.raises(ValueError, match="another sync"):
                importer.run(dry_run=dry_run)
        assert sessions.sync_pass(importer.second.show(), [], dry_run=True)["scanned"] == 0
    assert not importer.commands


def test_legacy_migration_recovers_old_prefix_then_imports_increment(provider_files, importer):
    old = read_provider(provider_files, "claude-code")
    payload = old.payload("lib-notes", sessions.triage(old))
    digest = sessions.digest(sessions.encoded_json(payload).encode())
    importer.accepted[digest] = "historical-source"
    sessions.atomic_json(importer.state.with_name("ingested-sessions.json"), {"version": 1, "sessions": {
        sessions.session_key(old): {"provider": old.provider, "session_id": old.session_id, "sha256": digest,
                                    "canonical_treatment": "full", "ingested_at": "2026-09-01T05:00:00Z"}}})
    append(provider_files, "claude-code")
    report = importer.run()
    assert report["increments"] == 1 and report["ingested"] == 2
    assert importer.payloads[0] == payload
    assert importer.payloads[1]["metadata"]["continues"] == "historical-source"
    assert importer.payloads[1]["metadata"]["part"] == 2
    assert cursor(importer)["source_ids"][0] == "historical-source"
    assert json.loads(importer.state.read_text())["legacy"] == {}
    assert importer.run()["ingested"] == 0


def test_unrecoverable_legacy_hash_is_reported_and_never_assumed_current(provider_files, importer):
    old = read_provider(provider_files, "claude-code")
    sessions.atomic_json(importer.state.with_name("ingested-sessions.json"), {"version": 1, "sessions": {
        sessions.session_key(old): {"sha256": "unrecoverable"}}})
    report = importer.run()
    assert report["rewritten"] == 1
    assert all(p["provider"] != "claude-code" for p in importer.payloads)


def test_lost_ingest_response_replays_exact_payload_despite_growth(provider_files, importer):
    importer.behavior["lost_response"] = True
    assert importer.run()["skipped"] == 2
    assert len(importer.accepted) == 2
    assert cursor(importer)["exported_turns"] == 0
    old_payloads = list(importer.payloads)
    append(provider_files, "claude-code")
    importer.behavior["lost_response"] = False
    assert importer.run()["ingested"] == 2
    assert sorted(map(sessions.encoded_json, importer.payloads[2:])) == sorted(map(sessions.encoded_json, old_payloads))
    assert len(importer.accepted) == 2
    assert importer.run()["increments"] == 1
    assert len(importer.accepted) == 3


def test_partial_jsonl_tail_waits_for_newline(provider_files, importer):
    importer.run()
    append(provider_files, "claude-code", 2)
    row = json.dumps(claude_row("user", OWNER_TEXTS[2], 22)).encode()
    with provider_files.claude_file.open("ab") as stream:
        stream.write(row[:30])
    assert importer.run()["held"] == 1
    with provider_files.claude_file.open("ab") as stream:
        stream.write(row[30:] + b"\n")
    assert importer.run()["increments"] == 1


def test_complete_final_record_without_newline_is_not_lost(provider_files, importer):
    provider_files.claude_file.write_bytes(provider_files.claude_file.read_bytes().rstrip(b"\n"))
    assert importer.run()["ingested"] == 2
    assert importer.run()["unchanged"] == 2
    with provider_files.claude_file.open("ab") as stream:
        stream.write(b"\n")
    assert importer.run()["ingested"] == 0


def test_watch_commands_settings_and_library_isolation(home, make_library, tmp_path, capsys):
    one, two = make_library(), make_library("second")
    project = tmp_path / "synthetic project"
    project.mkdir()
    assert cli.main(["watch", "add", str(project), "--library", "notes", "--harnesses", "codex",
                     "--since", "2026-09-01T00:00:00Z"]) == 0
    assert cli.main(["watch", "add", str(project), "--library", "notes"]) == 0
    assert cli.main(["watch", "ls", "--library", "notes"]) == 0
    watches = json.loads(capsys.readouterr().out)
    assert len(watches) == 1 and watches[0]["harnesses"] == ["codex"]
    assert Library.load(home, two.state.name).state.watch == []
    project.rmdir()
    assert cli.main(["watch", "rm", str(project), "--library", "notes"]) == 0
    assert Library.load(home, one.state.name).state.watch == []
    assert cli.main(["config", "set", "sync.interval_minutes", "7"]) == 0
    assert home.config.sync.interval_minutes == 7
    assert cli.main(["config", "set", "sync.enabled", "off"]) == 0
    assert home.config.sync.enabled is False
    assert cli.main(["config", "set", "sync.interval_minutes", "0"]) == 2
    assert cli.main(["config", "set", "sync.enabled", "yes"]) == 2
    with pytest.raises(ValueError):
        Watch(path=str(project), since="2026-09-01T00:00:00")


def test_sync_cli_json_and_status_use_same_edition_state(home, importer, monkeypatch, capsys):
    script = sync.converter()
    monkeypatch.setattr(script, "sync_pass", lambda *args, **kwargs: importer.run(**{k: kwargs[k] for k in ("dry_run", "rewritten")}))
    assert cli.main(["sync", "--library", "notes", "--dry-run", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] and report["new"] == 2
    assert cli.main(["sync", "--library", "notes", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    result = sync.status(home, importer.library)
    # Status carries the pass's counts, never its per-session rows.
    assert result["last_result"] == {key: report[key] for key in sessions.SYNC_COUNTS}
    assert "sessions" not in result["last_result"]
    assert result["watching"] == [importer.library.state.watch[0].path]
    assert result["next_due_ms"] is not None and not result["running"]
    with sessions.sync_lock(home.path / "run/notes.sync.lock"):
        assert sync.status(home, importer.library)["running"] is True
    set_config(home, "sync.enabled", "off")
    assert sync.status(home, importer.library)["next_due"] is None


def test_watch_harness_and_since_filter_are_content_based(provider_files, importer):
    importer.library.state.watch = [Watch(path=str(provider_files.project), harnesses=["codex"],
                                         since="2026-09-01T03:00:00Z")]
    report = importer.run()
    assert report["scanned"] == 1 and report["skipped"] == 1
    append(provider_files, "codex")
    assert importer.run()["ingested"] == 0
    path = provider_files.codex_file
    row = codex_message("user", OWNER_TEXTS[0], 50)
    row["timestamp"] = "2026-09-02T03:00:00Z"
    with path.open("a") as stream:
        stream.write(json.dumps(row) + "\n")
    assert importer.run()["ingested"] == 1
    assert all(p["provider"] == "codex" for p in importer.payloads)


def test_rewrite_is_detected_before_parsing_or_reingesting(provider_files, importer):
    importer.run()
    provider_files.claude_file.write_bytes(b"this is not JSON\n")
    report = importer.run()
    assert report["rewritten"] == 1 and report["ingested"] == 0
    assert next(row for row in report["sessions"] if row["provider"] == "claude-code")["status"] == "rewritten"


def test_changed_reader_history_requires_rewrite_override(provider_files, importer):
    rows = [codex_row("session_meta", {"id": "momo-codex", "cwd": str(provider_files.project)}, 0)]
    rows += [codex_row("event_msg", {"type": "user_message", "message": text}, i)
             for i, text in enumerate(OWNER_TEXTS, 1)]
    write_jsonl(provider_files.codex_file, rows)
    importer.run()
    # Modern response items replace the reader's event-only fallback for this role.
    append(provider_files, "codex")
    assert importer.run()["rewritten"] == 1
    report = importer.run(rewritten="reingest")
    assert report["rewritten"] == report["ingested"] == 1
    assert "continues" not in importer.payloads[-1]["metadata"]


def test_continuations_cross_the_unchanged_library_contract_as_distinct_citable_sources(provider_files, importer):
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
    from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract

    importer.run()
    append(provider_files, "claude-code")
    importer.run()
    parts = [parse_source_contract(payload) for payload in importer.payloads if payload["provider"] == "claude-code"]
    sources = [normalize_source_contract(part, UserId("lib-notes"), imported_at=datetime.now(timezone.utc))[0]
               for part in parts]
    assert sources[0].raw.source_id != sources[1].raw.source_id
    assert len(sources[1].blocks) == 3
    assert sources[1].raw.meta["metadata"]["continues"] == cursor(importer)["source_ids"][0]
    assert all(text in block.text for text, block in zip(OWNER_TEXTS, sources[1].blocks, strict=True))
    other = normalize_source_contract(parts[1], UserId("lib-second"), imported_at=datetime.now(timezone.utc))[0]
    assert sources[1].raw.user_id == "lib-notes" and other.raw.user_id == "lib-second"


def test_all_scope_reads_the_harness_roots_excludes_patterns_and_counts_missing(provider_files, importer):
    root = provider_files.project.parent
    add_project(provider_files, "other")
    add_project(provider_files, "scratch", parent=root / "junk")
    shutil.rmtree(add_project(provider_files, "gone"))
    importer.library.state.watch = [Watch(path="all")]
    report = importer.run(dry_run=True, exclude=[f"{root / 'junk'}/**"])
    # momo and other, from both harnesses; the excluded project is not read at all.
    assert (report["scanned"], report["new"]) == (4, 4)
    assert all("scratch" not in row["file"] for row in report["sessions"])
    # A project whose directory is gone is counted once, and never listed session by session.
    assert report["project_missing"] == 1
    assert all("gone" not in row["file"] for row in report["sessions"])


def test_a_recursive_entry_matches_by_path_component(provider_files, importer):
    root = provider_files.project.parent
    add_project(provider_files, "inside", parent=root / "work")
    add_project(provider_files, "outside", parent=root / "workshop")
    importer.library.state.watch = [Watch(path=str(root / "work"), recursive=True)]
    report = importer.run(dry_run=True)
    assert report["scanned"] == 2
    assert all("workshop" not in row["file"] for row in report["sessions"])


def test_the_home_and_the_library_are_excluded_with_no_patterns_at_all(provider_files, importer, home):
    for name, directory in (("engine", importer.library.engine_dir),
                            ("canonical", importer.library.canonical_dir),
                            ("home", home.path)):
        write_jsonl(provider_files.claude_root / str(directory).replace("/", "-") / f"{name}.jsonl",
                    claude_rows(directory))
    importer.library.state.watch = [Watch(path="all")]
    report = importer.run(dry_run=True, exclude=[])
    assert report["scanned"] == 2
    assert all(str(home.path) not in row["file"] for row in report["sessions"])


def test_a_steward_session_is_skipped_entirely_and_never_indexed(provider_files, importer):
    rows = claude_rows(provider_files.project)
    # The Owner ran the library's own command from this session: it is work ON the library.
    rows[3]["message"]["content"][3]["input"]["command"] = "pkc draft open --json"
    write_jsonl(provider_files.claude_file, rows)
    report = importer.run()
    assert report["skipped_steward"] == 1 and report["ingested"] == 1
    assert all(payload["provider"] == "codex" for payload in importer.payloads)
    row = next(row for row in report["sessions"] if row["provider"] == "claude-code")
    assert row["status"] == "steward" and row["triage"]["verdict"] == "skip"
    assert "steward_session" in row["triage"]["reasons"]
    assert importer.run()["ingested"] == 0


def test_the_skill_entry_of_a_rendered_package_is_the_same_command(provider_files, importer):
    rows = claude_rows(provider_files.project)
    entry = importer.library.show()["entry"]
    rows[3]["message"]["content"][3]["input"]["command"] = f"{entry} queue"
    write_jsonl(provider_files.claude_file, rows)
    assert importer.run()["skipped_steward"] == 1
    # A different executable that merely begins with the same letters is ordinary material.
    rows[3]["message"]["content"][3]["input"]["command"] = "pkcompose up"
    write_jsonl(provider_files.claude_file, rows)
    report = importer.run(rewritten="reingest")
    assert report["skipped_steward"] == 0 and report["ingested"] == 1


def test_home_configuration_reaches_the_pass_and_holds_below_its_own_floor(provider_files, importer,
                                                                          home, monkeypatch):
    set_config(home, "sync.exclude", "")
    set_config(home, "sync.exclude", "/synthetic/**,/nowhere/**")
    set_config(home, "sync.min_owner_turns", "5")
    assert home.config.sync.exclude == ["/synthetic/**", "/nowhere/**"]
    captured = {}
    script = sync.converter()

    def spy(library, watches, **kwargs):
        captured.update(kwargs)
        return importer.run(**{key: kwargs[key] for key in ("dry_run", "rewritten", "options", "exclude")})

    monkeypatch.setattr(script, "sync_pass", spy)
    report = sync.run(home, importer.library, dry_run=True)
    assert captured["options"] == {"min_owner_turns": 5, "min_owner_chars": 200, "ack_max_words": 1}
    assert captured["max_part_chars"] == 400_000
    assert captured["exclude"] == ["/synthetic/**", "/nowhere/**"]
    assert captured["home"] == str(home.path)
    # Three Owner turns, and a fourth appended: still under the floor the home now states.
    append(provider_files, "claude-code", 1)
    assert report["new"] == 0 and report["held"] == 2
    assert sync.run(home, importer.library, dry_run=True)["held"] == 2


def test_watch_scope_forms_and_sync_settings_round_trip(home, make_library, tmp_path, capsys):
    make_library()
    project = tmp_path / "synthetic project"
    project.mkdir()
    assert cli.main(["watch", "add", "--all", "--library", "notes"]) == 0
    assert cli.main(["watch", "add", str(project), "--recursive", "--library", "notes"]) == 0
    assert cli.main(["watch", "ls", "--library", "notes"]) == 0
    watches = json.loads(capsys.readouterr().out)
    assert [(item["path"], item["recursive"]) for item in watches] == [("all", False), (str(project), True)]
    # One scope per entry: a directory and --all together, or neither, is a refusal.
    assert cli.main(["watch", "add", "--library", "notes"]) == 2
    assert cli.main(["watch", "add", str(project), "--all", "--library", "notes"]) == 2
    assert cli.main(["watch", "add", str(tmp_path / "absent"), "--recursive", "--library", "notes"]) == 2
    assert cli.main(["watch", "rm", "--all", "--library", "notes"]) == 0
    assert cli.main(["watch", "rm", str(project), "--library", "notes"]) == 0
    assert Library.load(home, "notes").state.watch == []
    # Patterns append to the defaults; an empty value is how they are cleared.
    assert cli.main(["config", "set", "sync.exclude", "/one/**,/two/**"]) == 0
    assert home.config.sync.exclude[-2:] == ["/one/**", "/two/**"] and len(home.config.sync.exclude) == 6
    assert cli.main(["config", "set", "sync.exclude", ""]) == 0
    assert cli.main(["config", "set", "sync.exclude", "/one/**,/two/**"]) == 0
    assert cli.main(["config", "get", "sync.exclude"]) == 0
    assert capsys.readouterr().out == "/one/**\n/two/**\n"
    assert cli.main(["config", "set", "sync.ack_max_words", "2"]) == 0
    assert cli.main(["config", "set", "sync.min_owner_chars", "0"]) == 0
    assert (home.config.sync.ack_max_words, home.config.sync.min_owner_chars) == (2, 0)
    # The converter's own floors are the model's floors; a value below them is refused.
    assert cli.main(["config", "set", "sync.min_owner_turns", "2"]) == 2
    assert cli.main(["config", "set", "sync.ack_max_words", "0"]) == 2



def giant_claude_session(files, agent_sizes):
    """One synthetic Claude session: one Owner turn, then one agent turn of each given size."""
    rows = []
    for index, size in enumerate(agent_sizes):
        rows.append(claude_row("user", OWNER_TEXTS[index % 3], 2 * index + 1,
                               cwd=str(files.project)))
        rows.append(claude_row("assistant", [{"type": "text", "text": "x" * size}], 2 * index + 2))
    write_jsonl(files.claude_file, rows)


def claude_parts(importer):
    return [p for p in importer.payloads if p["provider"] == "claude-code"]


def claude_ingest(command):
    """Is this `pkc ingest` call carrying the Claude session's part? Read off the payload."""
    return json.loads(Path(command[command.index("--file") + 1]).read_text())["provider"] == "claude-code"


def test_a_session_too_large_for_a_round_is_ingested_as_consecutive_parts(
    provider_files, importer, monkeypatch
):
    """The April session, in miniature: three Owner turns and about a million characters.

    Cut at Owner turns only, ingested in order in one pass, each part an ordinary growth part
    — `from_turn`, `part`, `continues` — so the serial queue compiles them in order, each with
    the pages the previous part wrote as context. The cursor advances part by part."""
    giant_claude_session(provider_files, [330_000, 330_000, 330_000])
    real_run = sessions.subprocess.run
    cursors = []

    def watching(command, **kwargs):
        if claude_ingest(command):
            state = json.loads(importer.state.read_text()) if importer.state.exists() else {"sessions": {}}
            cursors.append([dict(e) for e in state["sessions"].values() if e["provider"] == "claude-code"])
        return real_run(command, **kwargs)

    monkeypatch.setattr(sessions.subprocess, "run", watching)
    report = importer.run(max_part_chars=400_000)

    parts = claude_parts(importer)
    assert [p["metadata"]["part"] for p in parts] == [1, 2, 3]
    assert report["split_parts"] == 3 and report["oversized_parts"] == 0
    # Contiguous turn ranges, never a turn cut: each part starts where the last one ended,
    # at an Owner turn.
    first = [int(p["metadata"]["from_turn"][1:]) for p in parts]
    sizes = [len(p["turns"]) for p in parts]
    assert first == [1, 1 + sizes[0], 1 + sizes[0] + sizes[1]]
    assert all(p["turns"][0]["role"] == "owner" for p in parts)
    assert all(t["text"] == "x" * 330_000 for p in parts for t in p["turns"] if t["role"] == "agent")
    # Each part names the one before it.
    ids = [importer.accepted[sessions.digest(sessions.encoded_json(p).encode())] for p in parts]
    assert "continues" not in parts[0]["metadata"]
    assert [p["metadata"]["continues"] for p in parts[1:]] == ids[:-1]

    # The cursor as each part's ingest found it: the parts before it, and no further.
    exported = [entry[0]["exported_turns"] if entry else 0 for entry in cursors]
    assert exported == [0, sizes[0], sizes[0] + sizes[1]]
    final = cursor(importer)
    assert final["exported_turns"] == sum(sizes) and final["split_turns"] == 0
    assert final["source_ids"] == ids
    assert final["file_size"] == provider_files.claude_file.stat().st_size

    # Nothing is owed, so nothing is emitted.
    again = importer.run(max_part_chars=400_000)
    assert again["ingested"] == 0 and len(claude_parts(importer)) == 3


def test_a_pass_that_dies_between_parts_resumes_at_the_next_part(provider_files, importer, monkeypatch):
    giant_claude_session(provider_files, [330_000, 330_000, 330_000])
    real_run = sessions.subprocess.run
    calls = {"claude": 0}

    def failing_second(command, **kwargs):
        if claude_ingest(command):
            calls["claude"] += 1
            if calls["claude"] == 2:
                return SimpleNamespace(returncode=1, stdout="", stderr="synthetic failure")
        return real_run(command, **kwargs)

    monkeypatch.setattr(sessions.subprocess, "run", failing_second)
    importer.run(max_part_chars=400_000)
    stopped = cursor(importer)
    first_part = claude_parts(importer)[0]
    assert stopped["exported_turns"] == len(first_part["turns"])
    assert stopped["split_turns"] == len(first_part["turns"]), "the cursor claimed the byte boundary"
    assert len(stopped["source_ids"]) == 1

    monkeypatch.setattr(sessions.subprocess, "run", real_run)
    importer.run(max_part_chars=400_000)
    parts = claude_parts(importer)
    # Part 2 was journaled and is replayed byte for byte (the library deduplicates it);
    # part 3 follows. No part is emitted twice with different bytes, none is skipped.
    numbers = [p["metadata"]["part"] for p in parts]
    assert sorted(set(numbers)) == [1, 2, 3]
    final = cursor(importer)
    assert final["split_turns"] == 0 and len(final["source_ids"]) == 3
    assert importer.run(max_part_chars=400_000)["ingested"] == 0


def test_one_turn_larger_than_the_bound_is_its_own_part_whole_and_reported(provider_files, importer):
    giant_claude_session(provider_files, [2_000, 500_000, 2_000])
    report = importer.run(max_part_chars=400_000)
    parts = claude_parts(importer)
    assert len(parts) == 3 and report["oversized_parts"] == 1
    assert any(t["text"] == "x" * 500_000 for t in parts[1]["turns"]), "the giant turn was cut"
    lines = [r for r in report["sessions"] if r.get("provider") == "claude-code"]
    assert [r.get("oversized") for r in lines] == [None, parts and sum(
        len(t["text"]) for t in parts[1]["turns"]), None]


def test_the_bound_is_configuration_the_owner_sets_and_the_pass_applies(home, make_library):
    """A bound the Owner sets and the pass ignores is worse than no bound."""
    assert cli.main(["config", "set", "sync.max_part_chars", "50000"]) == 0
    assert home.config.sync.max_part_chars == 50_000
    assert cli.main(["config", "get", "sync.max_part_chars"]) == 0
    # Below the floor is refused rather than quietly applied.
    assert cli.main(["config", "set", "sync.max_part_chars", "10"]) == 2
    assert home.config.sync.max_part_chars == 50_000


# ───────────────────────────────────── a split part inherits the whole increment's verdict


def test_a_split_session_that_passes_the_thresholds_whole_compiles_every_part(provider_files, importer):
    """Three Owner turns, about a million characters: three parts of one Owner turn each.

    Judged part by part each would fall below `min_owner_turns` and be searchable-only — the
    session that would have compiled unsplit would never compile at all. The thresholds are
    judged on the whole increment and every part inherits that verdict; each part's record
    still counts only its own Owner words and names where its verdict came from."""
    giant_claude_session(provider_files, [330_000, 330_000, 330_000])
    report = importer.run(max_part_chars=400_000)
    parts = claude_parts(importer)
    assert len(parts) == 3
    records = [p["metadata"]["triage"] for p in parts]
    assert [r["verdict"] for r in records] == ["compile"] * 3
    assert [r["canonical_treatment"] for r in records] == ["full"] * 3
    assert [r["owner_turns"] for r in records] == [1, 1, 1]
    assert sum(r["owner_chars"] for r in records) == sum(len(t) for t in OWNER_TEXTS)
    assert {r["verdict_from"] for r in records} == {"increment"}
    assert {r["increment"]["owner_turns"] for r in records} == {3}
    # Compiled, so ingested at full intake: no `--intake searchable` on any part.
    assert not any("--intake" in command for command, payload in zip(importer.commands, importer.payloads)
                   if payload["provider"] == "claude-code")
    lines = [r for r in report["sessions"] if r.get("provider") == "claude-code"]
    assert [r["triage"]["verdict"] for r in lines] == ["compile"] * 3


def test_a_resumed_split_part_inherits_the_verdict_its_siblings_carried(provider_files, importer, monkeypatch):
    """The tail a resumed pass emits is judged as the whole increment was, not on its own."""
    giant_claude_session(provider_files, [330_000, 330_000, 330_000])
    real_run = sessions.subprocess.run
    calls = {"claude": 0}

    def lose_second(command, **kwargs):
        if claude_ingest(command):
            calls["claude"] += 1
            if calls["claude"] == 2:
                return SimpleNamespace(returncode=1, stdout="", stderr="synthetic failure")
        return real_run(command, **kwargs)

    monkeypatch.setattr(sessions.subprocess, "run", lose_second)
    importer.run(max_part_chars=400_000)
    monkeypatch.setattr(sessions.subprocess, "run", real_run)
    importer.run(max_part_chars=400_000)
    records = {p["metadata"]["part"]: p["metadata"]["triage"] for p in claude_parts(importer)}
    assert sorted(records) == [1, 2, 3]
    assert {r["verdict"] for r in records.values()} == {"compile"}
    assert {r["increment"]["owner_turns"] for r in records.values()} == {3}


def test_a_split_increment_below_the_thresholds_is_held_whole_and_never_cut(provider_files, importer):
    """Held is judged before splitting: two Owner turns stay held however large the increment."""
    giant_claude_session(provider_files, [330_000, 330_000])
    size = provider_files.claude_file.stat().st_size
    report = importer.run(max_part_chars=400_000)
    assert claude_parts(importer) == []
    assert report["split_parts"] == 0
    held = cursor(importer)
    assert held["exported_turns"] == 0 and held["exported_bytes"] == 0 and held["source_ids"] == []
    assert held["held"] == {"owner_turns": 2, "chars": sum(len(t) for t in OWNER_TEXTS[:2])}
    assert held["file_size"] == size and not held.get("split_turns")
    line = next(r for r in report["sessions"] if r.get("provider") == "claude-code")
    assert line["status"] == "held" and "parts" not in line


def test_an_ordinary_growth_increment_keeps_its_own_triage_record(provider_files, importer):
    """Not split, not touched: no inherited-verdict fields ride on an ordinary increment."""
    importer.run()
    record = claude_parts(importer)[0]["metadata"]["triage"]
    assert record["verdict"] == "compile"
    assert "verdict_from" not in record and "increment" not in record
