"""Two wires, one event vocabulary (§5.6).

The console renders turns, text, steps and a turn's cost; the two harnesses say all four in
entirely different words. These tests hold the translation still — feed each adapter the
frames its harness really emits, and assert the vocabulary that comes out, including the
three places the protocols disagree in a way that has been got wrong before:

* Codex reports BOTH `last` (this request) and `total` (the session, cumulative). A turn's
  usage is `last`; reading `total` there is the category error that renders 9,024%.
* Claude reports its usage on the `result` envelope and nowhere else, and a harness that
  reports nothing must leave `usage is None` rather than a zero.
* An approval request should not arrive under these policies at all. If one does it is
  DECLINED — in the answer shape its own method asks for — and surfaced. An unknown REQUEST
  is declined too, because ignoring it hangs the harness.
"""

from __future__ import annotations

import json

from pneuma_knowledge_service.coding_agent.steward_claude import ClaudeStreamAdapter
from pneuma_knowledge_service.coding_agent.steward_codex import CodexJsonRpcAdapter
from pneuma_knowledge_service.coding_agent.steward_events import (
    QUEUED,
    Notice,
    PermissionRequest,
    SessionStarted,
    StepFinished,
    StepStarted,
    TextDelta,
    TurnFinished,
    TurnStarted,
)


def kinds(events) -> list[str]:
    return [e.kind for e in events]


def written(adapter) -> list[dict]:
    return [json.loads(frame.decode("utf-8")) for frame in adapter.take_writes()]


# ── Claude Code: stream-json ───────────────────────────────────────────────────────────────


def test_a_claude_turn_becomes_start_text_step_and_end():
    adapter = ClaudeStreamAdapter()
    adapter.start()
    adapter.user_turn("what came in this week?")

    frame = written(adapter)[0]
    assert frame == {
        "type": "user",
        "message": {"role": "user", "content": "what came in this week?"},
        "parent_tool_use_id": None,
    }
    assert kinds(adapter.take_events()) == ["turn_started"]
    assert adapter.busy is True

    adapter.feed(
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "sess-9c",
                "model": "claude-fake",
            }
        )
        + "\n"
    )
    adapter.feed(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "reading the ledger"},
                        {
                            "type": "tool_use",
                            "id": "toolu-1",
                            "name": "Bash",
                            "input": {"command": "pkc jobs --limit 5"},
                        },
                    ],
                },
            }
        )
        + "\n"
    )
    adapter.feed(
        json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu-1",
                            "content": "2 jobs",
                        }
                    ],
                },
            }
        )
        + "\n"
    )
    adapter.feed(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "session_id": "sess-9c",
                "duration_ms": 4123,
                "usage": {"input_tokens": 42, "output_tokens": 12},
                "total_cost_usd": 0.0214,
            }
        )
        + "\n"
    )

    events = adapter.take_events()
    assert kinds(events) == [
        "session_started",
        "text_delta",
        "step_started",
        "step_finished",
        "turn_finished",
    ]
    started = next(e for e in events if isinstance(e, SessionStarted))
    assert started.agent_session_id == "sess-9c"
    step = next(e for e in events if isinstance(e, StepStarted))
    # The agent's OWN words, not a rendering the framework invented.
    assert step.command == "pkc jobs --limit 5"
    assert step.tool == "Bash"
    done = next(e for e in events if isinstance(e, StepFinished))
    assert (done.step_id, done.output_preview, done.failed) == ("toolu-1", "2 jobs", False)
    end = next(e for e in events if isinstance(e, TurnFinished))
    assert end.usage == {"input_tokens": 42, "output_tokens": 12}
    assert end.cost_usd == 0.0214
    assert adapter.busy is False


def test_claude_stdout_is_chunked_not_line_aligned():
    """A large payload lands mid-line; only whole lines are dispatched."""
    adapter = ClaudeStreamAdapter()
    line = json.dumps(
        {"type": "system", "subtype": "init", "session_id": "sess-split"}
    )
    adapter.feed(line[:20])
    assert adapter.take_events() == []
    adapter.feed(line[20:])
    assert adapter.take_events() == []  # still no newline
    adapter.feed("\n")
    assert kinds(adapter.take_events()) == ["session_started"]


def test_claude_deltas_are_not_repeated_by_the_consolidated_message():
    adapter = ClaudeStreamAdapter()
    adapter.feed(
        json.dumps(
            {
                "type": "stream_event",
                "event": {"delta": {"type": "text_delta", "text": "read"}},
            }
        )
        + "\n"
    )
    adapter.feed(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "reading the ledger"}],
                },
            }
        )
        + "\n"
    )
    texts = [e.text for e in adapter.take_events() if isinstance(e, TextDelta)]
    assert "".join(texts) == "reading the ledger"


def test_claude_reports_no_usage_as_none_never_zero():
    adapter = ClaudeStreamAdapter()
    adapter.feed(json.dumps({"type": "result", "subtype": "success"}) + "\n")
    end = next(e for e in adapter.take_events() if isinstance(e, TurnFinished))
    assert end.usage is None and end.cost_usd is None


def test_claude_declines_a_permission_request_it_should_never_have_received():
    adapter = ClaudeStreamAdapter()
    adapter.feed(
        json.dumps(
            {
                "type": "control_request",
                "request_id": "req-1",
                "request": {"subtype": "can_use_tool", "tool_name": "Bash"},
            }
        )
        + "\n"
    )
    events = adapter.take_events()
    assert kinds(events) == ["permission_request"]
    assert isinstance(events[0], PermissionRequest) and events[0].declined
    reply = written(adapter)[0]
    assert reply["type"] == "control_response"
    assert reply["response"]["behavior"] == "deny"


def test_claude_says_so_when_a_frame_is_one_it_does_not_know():
    adapter = ClaudeStreamAdapter()
    adapter.feed(json.dumps({"type": "something_new"}) + "\n")
    events = adapter.take_events()
    assert isinstance(events[0], Notice) and events[0].detail == "something_new"


# ── Codex: app-server JSON-RPC ─────────────────────────────────────────────────────────────


def test_codex_handshake_then_a_turn():
    adapter = CodexJsonRpcAdapter(project_dir="/srv/library", model="")
    adapter.start()
    boot = written(adapter)
    assert [f.get("method") for f in boot] == ["initialize", "initialized", "thread/start"]
    assert boot[2]["params"]["cwd"] == "/srv/library"
    # Nobody is at this terminal, so nothing can answer an approval.
    assert boot[2]["params"]["approvalPolicy"] == "never"

    start_id = boot[2]["id"]
    adapter.feed(
        json.dumps({"id": start_id, "result": {"thread": {"id": "thr-1"}, "model": "gpt-fake"}})
        + "\n"
    )
    assert kinds(adapter.take_events()) == ["session_started"]
    assert adapter.agent_session_id == "thr-1"

    adapter.user_turn("what came in this week?")
    turn = written(adapter)[0]
    assert turn["method"] == "turn/start"
    assert turn["params"]["threadId"] == "thr-1"
    assert turn["params"]["input"] == [{"type": "text", "text": "what came in this week?"}]
    assert kinds(adapter.take_events()) == ["turn_started"]


def test_codex_holds_a_turn_that_beats_the_handshake():
    """The console's first message routinely arrives before `thread/start` answers."""
    adapter = CodexJsonRpcAdapter(project_dir="/srv/library")
    adapter.start()
    start_id = written(adapter)[2]["id"]
    adapter.user_turn("first thing")
    assert adapter.take_writes() == []  # held, not dropped

    adapter.feed(json.dumps({"id": start_id, "result": {"thread": {"id": "thr-2"}}}) + "\n")
    frames = written(adapter)
    assert [f["method"] for f in frames] == ["turn/start"]
    assert frames[0]["params"]["input"][0]["text"] == "first thing"


def test_codex_synthesises_a_turn_end_and_reports_last_not_total():
    adapter = CodexJsonRpcAdapter(project_dir="/srv/library")
    adapter.start()
    start_id = written(adapter)[2]["id"]
    adapter.feed(json.dumps({"id": start_id, "result": {"thread": {"id": "t"}}}) + "\n")
    adapter.take_events()
    adapter.user_turn("go")
    adapter.take_writes()
    adapter.take_events()

    for frame in (
        {
            "method": "item/started",
            "params": {
                "item": {"type": "commandExecution", "id": "itm-1", "command": ["pkc", "jobs"]}
            },
        },
        {
            "method": "item/completed",
            "params": {
                "item": {
                    "type": "commandExecution",
                    "id": "itm-1",
                    "exitCode": 0,
                    "status": "completed",
                    "aggregatedOutput": "2 jobs",
                    "durationMs": 7,
                }
            },
        },
        {"method": "item/agentMessage/delta", "params": {"delta": "two jobs"}},
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "tokenUsage": {
                    "total": {"inputTokens": 23245850, "outputTokens": 74081},
                    "last": {"inputTokens": 125962, "outputTokens": 1329},
                    "modelContextWindow": 258400,
                }
            },
        },
        {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
    ):
        adapter.feed(json.dumps(frame) + "\n")

    events = adapter.take_events()
    assert kinds(events) == ["step_started", "step_finished", "text_delta", "turn_finished"]
    step = next(e for e in events if isinstance(e, StepStarted))
    assert step.command == "pkc jobs"
    done = next(e for e in events if isinstance(e, StepFinished))
    assert (done.exit_code, done.duration_ms, done.output_preview) == (0, 7, "2 jobs")
    end = next(e for e in events if isinstance(e, TurnFinished))
    # `last`, not `total`: the cumulative number is the session's, not this turn's.
    assert end.usage == {"inputTokens": 125962, "outputTokens": 1329}
    # The app-server never pushes a cost; a 0.0 would be a claim that the turn was free.
    assert end.cost_usd is None
    assert adapter.busy is False


def test_codex_declines_an_approval_in_the_shape_its_method_asks_for():
    adapter = CodexJsonRpcAdapter(project_dir="/srv/library")
    adapter.start()
    adapter.take_writes()

    adapter.feed(
        json.dumps(
            {
                "method": "item/commandExecution/requestApproval",
                "id": 13,
                "params": {"itemId": "itm-1", "command": "rm -rf /tmp/foo"},
            }
        )
        + "\n"
    )
    assert written(adapter) == [{"id": 13, "result": {"decision": "decline"}}]
    assert kinds(adapter.take_events()) == ["permission_request"]

    # The other answer vocabulary — flipping this silently rejects every approval.
    adapter.feed(json.dumps({"method": "applyPatchApproval", "id": 14, "params": {}}) + "\n")
    assert written(adapter) == [{"id": 14, "result": {"decision": "denied"}}]
    adapter.take_events()


def test_codex_declines_an_unknown_request_rather_than_ignoring_it():
    """Ignoring a request hangs the harness; approving it approves a future operation."""
    adapter = CodexJsonRpcAdapter(project_dir="/srv/library")
    adapter.start()
    adapter.take_writes()
    adapter.feed(json.dumps({"method": "future/dangerousThing", "id": 99, "params": {}}) + "\n")
    assert written(adapter) == [{"id": 99, "result": {"decision": "decline"}}]
    events = adapter.take_events()
    assert kinds(events) == ["permission_request", "notice"]


def test_codex_answers_the_auth_refresh_without_involving_anybody():
    adapter = CodexJsonRpcAdapter(project_dir="/srv/library")
    adapter.start()
    adapter.take_writes()
    adapter.feed(
        json.dumps({"method": "account/chatgptAuthTokens/refresh", "id": 7, "params": {}}) + "\n"
    )
    assert written(adapter) == [{"id": 7, "result": {}}]
    assert adapter.take_events() == []


def test_an_unknown_notification_is_dropped_because_nothing_waits_on_it():
    adapter = CodexJsonRpcAdapter(project_dir="/srv/library")
    adapter.start()
    adapter.take_writes()
    adapter.feed(json.dumps({"method": "thread/goal/cleared", "params": {}}) + "\n")
    assert adapter.take_events() == []
    assert adapter.take_writes() == []


def test_the_two_adapters_speak_the_same_vocabulary():
    """Nine event kinds, and both adapters produce them under the same names."""
    assert QUEUED == "queued"
    for cls in (TurnStarted, TextDelta, StepStarted, StepFinished, TurnFinished):
        assert cls().payload()["type"] == cls().kind
