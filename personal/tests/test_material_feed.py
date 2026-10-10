"""Local logs and transported retained snapshots share one incremental ingest processor."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_agent_sessions import OMITTED, OWNER_TEXTS, claude_row, provider_files, read_provider, sessions
from test_sync import append, cursor, importer  # noqa: F401 -- share the synthetic ingest door


def captured(files, provider="claude-code", **origin):
    path = files.claude_file if provider == "claude-code" else files.codex_file
    return sessions.capture_snapshot(provider, path, files.project, origin=origin)


def remote_only(importer):
    importer.library.state.watch = []


@pytest.mark.parametrize("provider", ["claude-code", "codex"])
def test_material_round_trip_preserves_legacy_contract_and_excludes_raw_payloads(provider_files, provider):
    old = read_provider(provider_files, provider)
    snapshot = captured(provider_files, provider, device_id="synthetic-device")
    assert OMITTED not in sessions.encoded_json(snapshot)
    recovered = sessions.decode_snapshot(json.loads(sessions.encoded_json(snapshot)))
    assert recovered.payload("owner", sessions.triage(recovered)) == old.payload("owner", sessions.triage(old))
    assert sessions.session_key(recovered) == sessions.session_key(old)
    changed_origin = deepcopy(snapshot)
    changed_origin["origin"].update(device_id="second-device", file="/elsewhere/copied.jsonl")
    assert sessions.material_id(sessions.decode_snapshot(changed_origin)) == snapshot["material_id"]
    assert recovered.payload("owner", sessions.triage(recovered)) == sessions.decode_snapshot(changed_origin).payload(
        "owner", sessions.triage(recovered))


@pytest.mark.parametrize("provider", ["claude-code", "codex"])
def test_remote_can_ingest_without_source_directory_and_has_same_contract(provider_files, importer, provider):
    snapshot = captured(provider_files, provider, device_id="remote-device")
    expected = read_provider(provider_files, provider)
    remote_only(importer)
    provider_files.project.rmdir()
    result = importer.run(snapshots=[snapshot])
    assert result["ingested"] == 1
    payload = importer.payloads[0]
    assert payload["turns"] == expected.turns
    assert payload["project"]["path"] == str(provider_files.project)
    assert "device_id" not in sessions.encoded_json(payload)
    assert result["sessions"][0]["origin"]["device_id"] == "remote-device"
    assert importer.run(snapshots=[snapshot])["unchanged"] == 1
    assert len(importer.payloads) == 1


@pytest.mark.parametrize("provider", ["claude-code", "codex"])
def test_remote_held_growth_and_continuation_use_shared_cursor(provider_files, importer, provider):
    remote_only(importer)
    importer.run(snapshots=[captured(provider_files, provider)])
    before = cursor(importer, provider)
    append(provider_files, provider, 1)
    assert importer.run(snapshots=[captured(provider_files, provider)])["held"] == 1
    assert cursor(importer, provider)["material_exported"] == before["material_exported"]
    append(provider_files, provider, 2, start=21)
    assert importer.run(snapshots=[captured(provider_files, provider)])["increments"] == 1
    assert importer.payloads[-1]["metadata"]["continues"] == before["source_ids"][-1]
    assert [turn["text"] for turn in importer.payloads[-1]["turns"]] == [OWNER_TEXTS[0], *OWNER_TEXTS[:2]]


def test_remote_rewrite_requires_explicit_override(provider_files, importer):
    remote_only(importer)
    importer.run(snapshots=[captured(provider_files)])
    before = cursor(importer)
    provider_files.claude_file.write_bytes(provider_files.claude_file.read_bytes().replace(b"offline", b"on-line"))
    snapshot = captured(provider_files)
    assert importer.run(snapshots=[snapshot])["rewritten"] == 1
    assert cursor(importer) == before
    assert importer.run(snapshots=[snapshot], rewritten="reingest")["ingested"] == 1
    assert importer.payloads[-1]["metadata"]["rewritten"] is True
    assert "continues" not in importer.payloads[-1]["metadata"]


def test_device_copy_and_changed_observation_paths_do_not_duplicate_local_evidence(provider_files, importer):
    importer.run()
    before = cursor(importer)
    snapshot = captured(provider_files, device_id="second-device")
    snapshot["origin"]["file"] = "/remote/moved/copied.jsonl"
    remote_only(importer)
    report = importer.run(snapshots=[snapshot, snapshot])
    assert report["ingested"] == 0 and report["unchanged"] == 1
    assert report["sessions"][0]["source_ids"] == before["source_ids"]
    assert len(importer.payloads) == 2
    assert len(json.loads(importer.state.read_text())["sessions"]) == 2


def test_remote_failed_receipt_replays_frozen_payload_before_new_growth(provider_files, importer):
    remote_only(importer)
    importer.behavior["lost_response"] = True
    assert importer.run(snapshots=[captured(provider_files)])["skipped"] == 1
    original = deepcopy(importer.payloads[0])
    append(provider_files, "claude-code")
    grown = captured(provider_files)
    importer.behavior["lost_response"] = False
    assert importer.run(snapshots=[grown])["ingested"] == 1
    assert importer.payloads[-1] == original
    assert len(importer.accepted) == 1
    assert importer.run(snapshots=[grown])["increments"] == 1
    assert len(importer.accepted) == 2


def test_capture_defers_partial_jsonl_and_remote_does_not_need_raw_bytes(provider_files, importer):
    remote_only(importer)
    importer.run(snapshots=[captured(provider_files)])
    append(provider_files, "claude-code", 2)
    final = json.dumps(claude_row("user", OWNER_TEXTS[2], 22)).encode()
    with provider_files.claude_file.open("ab") as stream:
        stream.write(final[:30])
    assert importer.run(snapshots=[captured(provider_files)])["held"] == 1
    with provider_files.claude_file.open("ab") as stream:
        stream.write(final[30:])
    assert importer.run(snapshots=[captured(provider_files)])["increments"] == 1


def test_legacy_cursor_is_hydrated_from_verified_local_bytes_without_reimport(provider_files, importer):
    importer.run()
    state = json.loads(importer.state.read_text())
    for entry in state["sessions"].values():
        for key in list(entry):
            if key.startswith("material_") or key == "origin":
                entry.pop(key)
    importer.state.write_text(json.dumps(state))
    previous_ids = cursor(importer)["source_ids"]
    assert importer.run()["ingested"] == 0
    assert cursor(importer)["source_ids"] == previous_ids
    assert cursor(importer)["material_exported"]
    remote_only(importer)
    assert importer.run(snapshots=[captured(provider_files, device_id="copy")])["ingested"] == 0


def test_invalid_snapshot_refused_without_ingest(provider_files, importer):
    remote_only(importer)
    snapshot = captured(provider_files)
    snapshot["session"]["turns"][0]["text"] += " changed"
    report = importer.run(snapshots=[snapshot])
    assert report["skipped"] == 1
    assert "checksum" in report["sessions"][0]["error"]
    assert not importer.payloads


def test_remote_dry_run_does_not_write_baselines_or_cursors(provider_files, importer):
    from test_sync import disk_tree
    remote_only(importer)
    before = disk_tree(importer.library.path)
    report = importer.run(snapshots=[captured(provider_files)], dry_run=True)
    assert report["new"] == 1
    assert disk_tree(importer.library.path) == before


def test_remote_split_retries_keep_every_part_and_its_original_verdict(provider_files, importer, monkeypatch):
    from types import SimpleNamespace
    from test_sync import giant_claude_session
    giant_claude_session(provider_files, [1600, 1600, 1600])
    remote_only(importer)
    snapshot = captured(provider_files)
    original_run = sessions.subprocess.run
    calls = 0

    def fail_second(command, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            return SimpleNamespace(returncode=1, stdout="", stderr="synthetic interruption")
        return original_run(command, **kwargs)

    monkeypatch.setattr(sessions.subprocess, "run", fail_second)
    report = importer.run(snapshots=[snapshot], max_part_chars=2000)
    assert report["ingested"] == 1 and report["skipped"] == 1
    assert cursor(importer)["split_turns"] > 0
    monkeypatch.setattr(sessions.subprocess, "run", original_run)
    report = importer.run(snapshots=[snapshot], max_part_chars=2000)
    assert report["ingested"] == 2
    assert [payload["metadata"]["part"] for payload in importer.payloads] == [1, 2, 3]
    assert len(cursor(importer)["source_ids"]) == 3
    assert cursor(importer)["split_turns"] == 0
    assert all(payload["metadata"]["triage"]["increment"]["owner_turns"] == 3 for payload in importer.payloads)
    assert importer.run(snapshots=[snapshot], max_part_chars=2000)["ingested"] == 0


@pytest.mark.parametrize("lost_receipt", [False, True])
def test_held_local_material_finishes_split_when_unchanged_after_retry(
    provider_files, importer, monkeypatch, lost_receipt
):
    from collections import Counter
    from types import SimpleNamespace
    from test_sync import giant_claude_session

    giant_claude_session(provider_files, [1600, 1600, 1600])
    importer.library.state.watch[0].harnesses = ["claude-code"]
    held = importer.run(options={"min_owner_turns": 10}, max_part_chars=2000)
    assert held["held"] == 1 and not importer.payloads
    observed_bytes = cursor(importer)["file_size"]
    original_run = sessions.subprocess.run
    calls = 0

    def interrupt_second(command, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2 and not lost_receipt:
            return SimpleNamespace(returncode=1, stdout="", stderr="synthetic interruption")
        result = original_run(command, **kwargs)
        if calls == 2:
            result.stdout = ""
        return result

    # Relaxing the threshold admits the already-observed bytes. If the split is then
    # interrupted, unchanged bytes still owe the unacknowledged parts to the library.
    monkeypatch.setattr(sessions.subprocess, "run", interrupt_second)
    partial = importer.run(max_part_chars=2000)
    assert partial["ingested"] == 1 and partial["skipped"] == 1
    assert cursor(importer)["file_size"] == observed_bytes
    monkeypatch.setattr(sessions.subprocess, "run", original_run)
    resumed = importer.run(max_part_chars=2000)
    assert resumed["ingested"] == 2 and resumed["skipped"] == 0
    assert cursor(importer)["exported_turns"] == 6
    assert cursor(importer)["split_turns"] == 0 and cursor(importer)["split_turn_refs"] == []
    assert len(cursor(importer)["source_ids"]) == len(importer.accepted) == 3
    unique = {sessions.digest(sessions.encoded_json(payload).encode()): payload for payload in importer.payloads}
    retained = lambda turn: sessions.encoded_json({key: turn[key] for key in ("role", "kind", "at", "text")})
    assert Counter(retained(turn) for payload in unique.values() for turn in payload["turns"]) == Counter(
        retained(turn) for turn in read_provider(provider_files, "claude-code").turns)
    assert importer.run(max_part_chars=2000)["ingested"] == 0


@pytest.mark.parametrize("remote", [False, True])
@pytest.mark.parametrize("legacy_split", [False, True])
def test_delayed_turn_during_split_receipt_retry_is_retained_exactly_once(
    provider_files, importer, monkeypatch, remote, legacy_split
):
    from collections import Counter
    from test_sync import giant_claude_session

    giant_claude_session(provider_files, [1600, 1600, 1600])
    importer.library.state.watch[0].harnesses = ["claude-code"]
    if remote:
        remote_only(importer)
    original_run = sessions.subprocess.run
    calls = 0

    def lose_second_receipt(command, **kwargs):
        nonlocal calls
        calls += 1
        result = original_run(command, **kwargs)
        if calls == 2:
            result.stdout = ""
        return result

    def run():
        return importer.run(snapshots=[captured(provider_files)] if remote else (), max_part_chars=2000)

    monkeypatch.setattr(sessions.subprocess, "run", lose_second_receipt)
    report = run()
    assert report["ingested"] == 1 and report["skipped"] == 1
    assert len(importer.accepted) == 2
    if legacy_split:
        state = json.loads(importer.state.read_text())
        entry = next(iter(state["sessions"].values()))
        entry.pop("split_turn_refs")
        entry["pending"]["cursor"].pop("split_turn_refs")
        importer.state.write_text(json.dumps(state))
    with provider_files.claude_file.open("a") as stream:
        stream.write(json.dumps(claude_row("user", "A delayed Owner decision must remain in the evidence.", 0)) + "\n")
    monkeypatch.setattr(sessions.subprocess, "run", original_run)
    report = run()
    assert report["skipped"] == report["rewritten"] == 0

    # The lost receipt replays byte-identical evidence. Compare accepted payloads only,
    # preserving multiplicity: text equality cannot erase repeated real speech.
    unique = {sessions.digest(sessions.encoded_json(payload).encode()): payload for payload in importer.payloads}
    retained = lambda turn: sessions.encoded_json({key: turn[key] for key in ("role", "kind", "at", "text")})
    assert Counter(retained(turn) for payload in unique.values() for turn in payload["turns"]) == Counter(
        retained(turn) for turn in read_provider(provider_files, "claude-code").turns)
    assert cursor(importer)["exported_turns"] == 7
    assert cursor(importer)["split_turns"] == 0
    assert cursor(importer)["split_turn_refs"] == []
    assert run()["ingested"] == 0


def test_two_devices_same_material_in_one_pass_keep_observations_without_second_ingest(provider_files, importer):
    remote_only(importer)
    first = captured(provider_files, device_id="one")
    second = deepcopy(first)
    second["origin"]["device_id"] = "two"
    report = importer.run(snapshots=[first, second])
    assert report["ingested"] == 1 and report["unchanged"] == 1
    assert len(importer.payloads) == 1
    assert {row["origin"]["device_id"] for row in report["sessions"]} == {"one", "two"}
    assert report["sessions"][-1]["source_ids"] == cursor(importer)["source_ids"]


@pytest.mark.parametrize("bad", [None, [], {"session": [], "origin": []}, {"session": {}, "origin": {}}])
def test_malformed_remote_envelope_does_not_open_origin_files(importer, bad):
    remote_only(importer)
    report = importer.run(snapshots=[bad])
    assert report["skipped"] == 1 and report["sessions"][0]["status"] == "error"
    assert not importer.payloads


@pytest.mark.parametrize("value,expected", [
    ("git@github.com:Owner/Repo.git", "https://github.com/Owner/Repo"),
    ("https://synthetic-user:synthetic-secret@github.com/Owner/Repo.git", "https://github.com/Owner/Repo"),
    ("ssh://git@github.com/Owner/Repo.git", "https://github.com/Owner/Repo"),
    ("/local/repository", None),
])
def test_git_origin_normalization_removes_credentials_and_preserves_repository_case(value, expected):
    assert sessions.normalize_git_remote(value) == expected


def test_remote_first_then_local_copy_reuses_acknowledged_evidence(provider_files, importer):
    watches = list(importer.library.state.watch)
    remote_only(importer)
    snapshot = captured(provider_files, device_id="remote")
    # A clone on another machine has another checkout path but the same native session.
    session = sessions.decode_snapshot(snapshot)
    session.project = Path("/remote/checkout")
    snapshot = sessions.session_snapshot(session, origin=snapshot["origin"])
    assert importer.run(snapshots=[snapshot])["ingested"] == 1
    before = cursor(importer)
    importer.library.state.watch = watches
    report = importer.run()
    assert report["ingested"] == 1  # Only the other provider's untouched session is new.
    assert cursor(importer)["source_ids"] == before["source_ids"]
    assert len([payload for payload in importer.payloads if payload["provider"] == "claude-code"]) == 1
    append(provider_files, "claude-code")
    assert importer.run()["increments"] == 1
    assert importer.payloads[-1]["metadata"]["continues"] == before["source_ids"][-1]


def test_two_devices_same_filename_different_native_sessions_stay_separate(provider_files, importer):
    remote_only(importer)
    one = captured(provider_files, device_id="one")
    other = sessions.decode_snapshot(one)
    other.session_id = "another-native-conversation"
    two = sessions.session_snapshot(other, origin={"device_id": "two"})
    report = importer.run(snapshots=[one, two])
    assert report["ingested"] == 2 and report["rewritten"] == 0
    assert len(json.loads(importer.state.read_text())["sessions"]) == 2


def test_remote_copy_refuses_ambiguous_native_identity(provider_files, importer):
    from test_sync import add_project
    add_project(provider_files, "second-checkout")
    from pkc_personal.library import Watch
    importer.library.state.watch = [Watch(path="all")]
    assert importer.run()["ingested"] == 4
    remote_only(importer)
    copied = sessions.decode_snapshot(captured(provider_files))
    copied.project = Path("/unknown/third/checkout")
    snapshot = sessions.session_snapshot(copied, origin={"device_id": "third"})
    report = importer.run(snapshots=[snapshot])
    assert report["ingested"] == 0 and "ambiguous_material" in report["sessions"][0]["error"]


def test_scanner_reports_one_malformed_file_and_keeps_other_material(provider_files):
    # Discovery can still identify the Claude directory; its malformed later row must not
    # prevent an independent Codex session from reaching the transport queue.
    with provider_files.claude_file.open("ab") as stream:
        stream.write(b"not JSON\n")
    errors = []
    found = sessions.scan_snapshots([{"path": str(provider_files.project)}],
                                    claude_roots=[provider_files.claude_root],
                                    codex_roots=[provider_files.codex_root], diagnostics=errors)
    assert [item["session"]["provider"] for item in found] == ["codex"]
    assert len(errors) == 1 and errors[0]["file"] == str(provider_files.claude_file)
    assert "invalid JSON" in errors[0]["error"]


def test_material_callback_precedes_ingest_and_does_not_run_in_dry_run(provider_files, importer):
    remote_only(importer)
    snapshot = captured(provider_files, device_id="device")
    observations = []

    def observe(row):
        observations.append((row, len(importer.payloads)))

    importer.run(snapshots=[snapshot], on_material=observe, dry_run=True)
    assert not observations
    importer.run(snapshots=[snapshot], on_material=observe)
    assert observations[0][1] == 0
    assert observations[0][0]["material_id"] == snapshot["material_id"]
    assert observations[0][0]["project_path"] == str(provider_files.project)
    importer.run(snapshots=[snapshot], on_material=observe)
    assert observations[-1][0]["source_ids"] == cursor(importer)["source_ids"]


def test_streaming_scan_decodes_only_one_snapshot_before_first_yield(provider_files, monkeypatch):
    original = sessions.read_session
    reads = []

    def read(*args, **kwargs):
        reads.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(sessions, "read_session", read)
    iterator = sessions.iter_snapshots([{"path": str(provider_files.project)}],
                                      claude_roots=[provider_files.claude_root],
                                      codex_roots=[provider_files.codex_root])
    first = next(iterator)
    assert reads == [first["session"]["provider"]]
    assert len(list(iterator)) == 1
    assert len(reads) == 2


def test_remote_growth_preserves_local_byte_cursor_and_file_identity_guard(provider_files, importer):
    importer.run()
    local = cursor(importer)
    append(provider_files, "claude-code")
    incoming = captured(provider_files, device_id="remote")
    incoming["origin"]["file"] = "/remote/copied-session.jsonl"
    watches = list(importer.library.state.watch)
    remote_only(importer)
    assert importer.run(snapshots=[incoming])["increments"] == 1
    assert cursor(importer)["file"] == local["file"]
    assert cursor(importer)["exported_bytes"] == local["exported_bytes"]
    importer.library.state.watch = watches
    # The local file catches up with the material already acknowledged remotely.
    assert importer.run()["ingested"] == 0
    assert cursor(importer)["file_size"] == provider_files.claude_file.stat().st_size
    provider_files.claude_file.write_bytes(provider_files.claude_file.read_bytes().replace(b"momo-claude", b"new-native-id"))
    report = importer.run()
    assert report["rewritten"] == 1 and report["ingested"] == 0


def test_older_copy_from_another_device_is_stale_without_rolling_back_evidence(provider_files, importer):
    remote_only(importer)
    old = captured(provider_files, device_id="old-copy")
    append(provider_files, "claude-code")
    current = captured(provider_files, device_id="active-device")
    assert importer.run(snapshots=[current])["ingested"] == 1
    before = cursor(importer)
    report = importer.run(snapshots=[old])
    assert report["ingested"] == report["rewritten"] == 0
    assert report["sessions"][0]["status"] == "stale"
    after = cursor(importer)
    for name in ("material_seen", "material_exported", "source_ids", "exported_turns"):
        assert after[name] == before[name]
    assert len(after["material_origins"]) == 2
    assert importer.run(snapshots=[current, old])["rewritten"] == 0


def test_same_device_new_truncation_still_requires_rewrite_override(provider_files, importer):
    from dataclasses import replace
    remote_only(importer)
    snapshot = captured(provider_files, device_id="one")
    assert importer.run(snapshots=[snapshot])["ingested"] == 1
    shorter = sessions.decode_snapshot(snapshot)
    # This shorter revision was never published before, so it is a regression, not replay.
    shorter = replace(shorter, turns=shorter.turns[:-1])
    truncated = sessions.session_snapshot(shorter, origin=snapshot["origin"])
    assert importer.run(snapshots=[truncated])["rewritten"] == 1
    assert len(importer.payloads) == 1


def test_lost_host_ack_can_replay_old_known_device_revision_after_new_one(provider_files, importer):
    remote_only(importer)
    old = captured(provider_files, device_id="one")
    assert importer.run(snapshots=[old])["ingested"] == 1
    append(provider_files, "claude-code")
    current = captured(provider_files, device_id="one")
    assert importer.run(snapshots=[current])["increments"] == 1
    before = cursor(importer)
    report = importer.run(snapshots=[old, current])
    assert report["rewritten"] == 0 and report["ingested"] == 0
    assert report["sessions"][0]["status"] == "stale"
    assert cursor(importer)["material_origins"] == before["material_origins"]


def test_unchanged_second_device_observation_still_guards_its_later_regression(provider_files, importer):
    from dataclasses import replace
    remote_only(importer)
    one = captured(provider_files, device_id="one")
    two = deepcopy(one)
    two["origin"]["device_id"] = "two"
    importer.run(snapshots=[one, two])
    session = sessions.decode_snapshot(two)
    reduced = sessions.session_snapshot(replace(session, turns=session.turns[:-1]), origin=two["origin"])
    assert importer.run(snapshots=[reduced])["rewritten"] == 1


@pytest.mark.parametrize("remote", [False, True])
def test_processor_threshold_change_rejudges_only_held_increment(provider_files, importer, remote):
    if remote:
        remote_only(importer)

    def run(**kwargs):
        if remote:
            kwargs["snapshots"] = [captured(provider_files)]
        return importer.run(**kwargs)

    run()
    before = cursor(importer)
    append(provider_files, "claude-code")
    assert run(options={"min_owner_chars": 1000})["held"] >= 1
    held = cursor(importer)
    assert held["exported_turns"] == before["exported_turns"]
    report = run(options={"min_owner_chars": 200})
    assert report["increments"] == 1
    assert importer.payloads[-1]["metadata"]["continues"] == before["source_ids"][-1]
    assert len(importer.payloads[-1]["turns"]) == 3
    assert cursor(importer)["source_ids"][:len(before["source_ids"])] == before["source_ids"]
    assert cursor(importer)["judgment"] != held["judgment"]
    assert run(options={"min_owner_chars": 200})["ingested"] == 0


def test_relaxing_local_watch_since_rejudges_unchanged_skipped_material(provider_files, importer):
    from pkc_personal.library import Watch
    importer.library.state.watch = [Watch(path=str(provider_files.project), harnesses=["claude-code"],
                                         since="2026-10-01T00:00:00Z")]
    assert importer.run()["skipped"] == 1
    assert not importer.payloads
    importer.library.state.watch = [Watch(path=str(provider_files.project), harnesses=["claude-code"],
                                         since="2026-08-01T00:00:00Z")]
    assert importer.run()["ingested"] == 1
    assert len(importer.payloads) == 1
