"""Trace drill-down of a stored Conversation Event (Slice 04).

Contract: `docs/conversation-events.md`, "Query and live API" / "Trace drill-down".
The drill-down starts from a stored event, scans `runtime/trace.jsonl` newest
first within bounds, tolerates interleaved fragments and never returns raw
text: tool arguments/results, error messages, summaries and `agent.event`
lines stay out.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from jarvis.core.conversation_event_emitter import journal_trace
from jarvis.domain.conversation_events import (
    ConversationEventType as T, TraceRef, TraceSource,
)
from jarvis.runtime import conversation_event_trace as trace_module
from jarvis.runtime.conversation_event_trace import (
    STATIC_MESSAGES, TRACE_DATA_KEYS, ScanLimits, TraceNotApplicable, agent_task_trace_url, drill_down,
    project_trace_entry, scan_trace,
)
from tests.fakes.conversation_events import BASE, make_event

SECRETS = ("SECRET_ARGUMENT", "SECRET_RESULT", "SECRET_ERROR", "SECRET_TEXT", "SECRET_SUMMARY", "SECRET_MESSAGE",
           "SECRET_DESCRIPTION", "SECRET_THINKING")


def line(kind: str, data: dict, *, at: datetime = BASE, message: str = "static", level: str = "info") -> bytes:
    """A RuntimeJournal line, same serialization as `RuntimeJournal.emit`."""
    return (json.dumps({"ts": at.isoformat(), "kind": kind, "level": level, "message": message, "data": data},
                       ensure_ascii=False) + "\n").encode("utf-8")


GARBAGE = [
    b'{"ts": "2026-09-16T10:00:00.100000+00:00", "kind": "voice.speech.started", "lev\n',  # torn line
    b'el": "info", "message": "x", "data": {}}\n',  # its other half
    b'\xff\xfe\x00 binary noise voice.speech.started\n',
    b'{"ts": "2026-09-16T10:00:00+00:00", "kind": "core.brain.backend_task_started", "data": {}}'
    b'{"ts": "2026-09-16T10:00:00+00:00", "kind": "core.brain.backend_task_started", "data": {}}\n',  # two glued
    b'[1, 2, 3]\n',
    b'\n',
    b'   \n',
]


def write_trace(path: Path, chunks) -> Path:
    with path.open("wb") as handle:
        for chunk in chunks:
            handle.write(chunk)
    return path


def core_work_started():
    return make_event(T.BRAIN_WORK_STARTED, "w1", producer="core.brain_service", ms=50,
                      trace_ref=journal_trace("core.brain.backend_task_started", "correlation_id", "work_id"))


def voice_speech_started():
    return make_event(T.MOUTH_SPEECH_STARTED, "m1", producer="voice.speech_scheduler", ms=80,
                      trace_ref=journal_trace("voice.speech.started"))


def cc_subagent_finished():
    return make_event(T.SUBAGENT_FINISHED, "a1", producer="control_center.agent_tasks", ms=900,
                      started_at=BASE, trace_ref=journal_trace("agent.subagent.finished"))


def tool_started():
    return make_event(T.TOOL_CALL_STARTED, "c1", producer="voice.realtime_audio", ms=120,
                      trace_ref=journal_trace("tool.call"))


def mixed_trace(tmp_path: Path) -> tuple[Path, dict]:
    work, speech, subagent, tool = core_work_started(), voice_speech_started(), cc_subagent_finished(), tool_started()
    other = make_event(T.BRAIN_WORK_STARTED, "w2", producer="core.brain_service", ms=60,
                       trace_ref=journal_trace("core.brain.backend_task_started", "correlation_id", "work_id"))
    chunks = [
        GARBAGE[0],
        line("core.brain.backend_task_started", {"conversation_id": "conv-a", "correlation_id": work.correlation_id,
                                                  "work_id": work.work_id, "conversation_event_id": work.event_id},
             at=BASE + timedelta(milliseconds=50), message="backend task accepted"),
        GARBAGE[2],
        # same kind and keys, another event id: decided by the id, not a match
        line("core.brain.backend_task_started", {"conversation_id": "conv-a", "correlation_id": work.correlation_id,
                                                  "work_id": work.work_id, "conversation_event_id": other.event_id},
             at=BASE + timedelta(milliseconds=60), message="backend task accepted"),
        GARBAGE[1],
        line("core.brain.backend_task_result", {"correlation_id": work.correlation_id, "work_id": work.work_id,
                                                 "conversation_event_id": work.event_id, "status": "completed"},
             at=BASE + timedelta(milliseconds=70), message="backend task completed"),
        line("voice.speech.started", {"conversation_id": "conv-a", "speech_id": speech.speech_id,
                                      "output_id": "out-1", "conversation_event_id": speech.event_id,
                                      "text": "SECRET_TEXT"}, at=BASE + timedelta(milliseconds=80),
             message="Speech generation requested"),
        GARBAGE[3],
        line("tool.call", {"call_id": "call-c1", "arguments": {"password": "SECRET_ARGUMENT"},
                           "conversation_event_id": tool.event_id}, at=BASE + timedelta(milliseconds=120),
             message="SECRET_MESSAGE"),
        line("tool.result", {"call_id": "call-c1", "result": {"body": "SECRET_RESULT"}},
             at=BASE + timedelta(milliseconds=130), message="SECRET_MESSAGE"),
        GARBAGE[4], GARBAGE[5], GARBAGE[6],
        line("agent.event", {"conversation_event_id": subagent.event_id, "thinking": "SECRET_THINKING"},
             at=BASE + timedelta(milliseconds=880), message="SECRET_THINKING"),
        line("agent.subagent.finished", {"provider": "claude", "task_id": "agent-a1", "tool_use_id": "toolu_A",
                                         "status": "completed", "duration_ms": 900, "tokens": 1200, "tool_uses": 4,
                                         "summary": "SECRET_SUMMARY", "description": "SECRET_DESCRIPTION",
                                         "error": "SECRET_ERROR", "conversation_event_id": subagent.event_id},
             at=BASE + timedelta(milliseconds=900), message="Sous-agent terminé en 1 s : SECRET_DESCRIPTION"),
        b'{"ts": "2026-09-16T10:00:01+00:00", "kind": "voice.speech.started", "data": {"conversation_event_id": "cev-',
    ]
    return write_trace(tmp_path / "trace.jsonl", chunks), {
        "work": work, "speech": speech, "subagent": subagent, "tool": tool}


# ------------------------------------------------------------------ joins

@pytest.mark.parametrize("name", ["work", "speech", "subagent", "tool"])
def test_core_voice_and_control_center_events_join_exactly_one_line_despite_garbage(tmp_path, name):
    path, events = mixed_trace(tmp_path)
    event = events[name]
    body = drill_down(event, path)
    assert body["status"] == "found"
    scan = body["scan"]
    assert scan["match_count"] == 1 and not scan["truncated"] and scan["stopped_by"] == "file_start"
    assert scan["scanned_bytes"] == path.stat().st_size
    [entry] = scan["entries"]
    assert entry["kind"] == event.trace_ref.journal_kind
    assert entry["data"]["conversation_event_id"] == event.event_id
    rendered = json.dumps(body, ensure_ascii=False)
    assert not any(secret in rendered for secret in SECRETS), rendered


def test_the_projection_keeps_ids_statuses_counts_and_static_messages_only(tmp_path):
    path, events = mixed_trace(tmp_path)
    [finished] = drill_down(events["subagent"], path)["scan"]["entries"]
    assert finished["data"] == {"provider": "claude", "task_id": "agent-a1", "tool_use_id": "toolu_A",
                                "status": "completed", "duration_ms": 900, "tokens": 1200, "tool_uses": 4,
                                "conversation_event_id": events["subagent"].event_id}
    assert finished["redacted_keys"] == ["description", "error", "summary"]
    assert (finished["message"], finished["message_redacted"]) == (None, True)
    [tool] = drill_down(events["tool"], path)["scan"]["entries"]
    assert tool["redacted_keys"] == ["arguments"] and tool["message"] is None
    [speech] = drill_down(events["speech"], path)["scan"]["entries"]
    assert (speech["message"], speech["message_redacted"], speech["redacted_keys"]) == (
        "Speech generation requested", False, ["text"])


@pytest.mark.parametrize("key", ["arguments", "result", "error", "text", "summary", "description", "prompt"])
def test_planted_secrets_never_leave_the_projection(key):
    for value in ("SECRET_VALUE", {"nested": "SECRET_VALUE"}, ["SECRET_VALUE"]):
        for kind in ("tool.call", "tool.result", "voice.speech.started", "agent.subagent.finished"):
            projected = project_trace_entry({"ts": "2026-09-16T10:00:00+00:00", "kind": kind, "level": "info",
                                             "message": "SECRET_VALUE", "data": {key: value, "call_id": "c"}})
            assert "SECRET" not in json.dumps(projected), (key, kind)


def test_allowlisted_keys_with_free_text_or_nested_values_are_dropped():
    projected = project_trace_entry({"kind": "voice.brain_turn_rejected", "message": "Core a refusé: SECRET",
                                     "data": {"reason": "SECRET text with spaces", "code": {"x": 1},
                                              "status": 409, "error_class": "CoreProtocolError"}})
    assert projected["data"] == {"status": 409, "error_class": "CoreProtocolError"}
    assert projected["redacted_keys"] == ["code", "reason"] and projected["message"] is None
    assert "SECRET" not in json.dumps(projected)


def test_the_allowlist_holds_no_free_text_key():
    assert not TRACE_DATA_KEYS & {"arguments", "result", "error", "text", "summary", "description", "message",
                                  "label", "prompt", "thinking", "content", "detail"}
    assert all(STATIC_MESSAGES.values())


def test_an_agent_event_line_is_never_returned_even_if_it_would_match(tmp_path, monkeypatch):
    path, events = mixed_trace(tmp_path)
    monkeypatch.setattr(trace_module, "trace_entry_matches", lambda event, entry: True)
    event = events["subagent"]
    # The codec refuses an `agent.event` reference; force one past it to prove the scan's own guard.
    object.__setattr__(event, "trace_ref", SimpleNamespace(source=TraceSource.RUNTIME_JOURNAL,
                                                           journal_kind="agent.event", join_keys=()))
    scan = scan_trace(path, event)
    assert scan.entries == []
    assert "SECRET_THINKING" not in json.dumps(scan.to_payload())


def test_ids_written_in_journal_lines_are_never_followed(tmp_path):
    # A provisional sub-agent line names an event that was never stored; the
    # drill-down of a *stored* event only resolves that event's own reference.
    provisional = make_event(T.SUBAGENT_STARTED, "ghost", producer="control_center.agent_tasks", ms=10,
                             trace_ref=journal_trace("agent.subagent.started"))
    stored = make_event(T.SUBAGENT_STARTED, "real", producer="control_center.agent_tasks", ms=20,
                        trace_ref=journal_trace("agent.subagent.started"))
    path = write_trace(tmp_path / "trace.jsonl", [
        line("agent.subagent.started", {"task_id": "t-ghost", "conversation_event_id": provisional.event_id,
                                        "parent_id": stored.event_id}, at=BASE),
    ])
    body = drill_down(stored, path)
    assert body["status"] == "not_found" and body["scan"]["entries"] == []


# ------------------------------------------------------------- not applicable

def test_user_events_have_no_drill_down(tmp_path):
    user = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1", producer="core.voice_admission")
    with pytest.raises(TraceNotApplicable):
        drill_down(user, tmp_path / "trace.jsonl")


def test_an_event_without_trace_ref_says_so(tmp_path):
    accepted = make_event(T.BRAIN_TURN_ACCEPTED, "b1", producer="core.brain_service")
    body = drill_down(accepted, tmp_path / "missing.jsonl")
    assert (body["status"], body["scan"], body["trace_ref"]) == ("no_trace_ref", None, None)


def test_an_agent_task_reference_links_to_the_existing_trace_route(tmp_path):
    subagent = make_event(T.SUBAGENT_STARTED, "a/b c", producer="control_center.agent_tasks",
                          trace_ref=TraceRef(TraceSource.AGENT_TASK, None, ("task_id",)))
    body = drill_down(subagent, tmp_path / "never-read.jsonl")
    assert body["status"] == "agent_task" and body["scan"] is None
    assert body["agent_task"] == {"task_id": "task-a/b c", "trace_url": "/api/agent/tasks/task-a%2Fb%20c/trace"}
    assert agent_task_trace_url("x") == "/api/agent/tasks/x/trace"


def test_a_missing_trace_file_is_not_found_not_an_error(tmp_path):
    body = drill_down(voice_speech_started(), tmp_path / "absent.jsonl")
    assert body["status"] == "not_found" and body["scan"]["stopped_by"] == "missing_file"


# -------------------------------------------------------------------- bounds

def filler(count: int, *, start: datetime, step_ms: int = 1, kind: str = "voice.audio.level") -> bytes:
    return b"".join(line(kind, {"rms": index, "pad": "x" * 200}, at=start + timedelta(milliseconds=index * step_ms))
                    for index in range(count))


def test_a_large_trace_is_scanned_within_the_byte_budget_and_reports_truncation(tmp_path):
    event = voice_speech_started()
    target = line("voice.speech.started", {"conversation_event_id": event.event_id},
                  at=BASE + timedelta(milliseconds=80), message="Speech generation requested")
    path = write_trace(tmp_path / "trace.jsonl", [target, filler(12_000, start=BASE + timedelta(seconds=1))])
    assert path.stat().st_size > 3 * 2**20
    limited = scan_trace(path, event, limits=ScanLimits(max_bytes=2**20))
    assert (limited.entries, limited.truncated, limited.stopped_by) == ([], True, "max_bytes")
    assert limited.scanned_bytes == 2**20
    by_lines = scan_trace(path, event, limits=ScanLimits(max_lines=500))
    assert (by_lines.truncated, by_lines.stopped_by, by_lines.scanned_lines) == (True, "max_lines", 500)
    started = time.perf_counter()
    full = scan_trace(path, event)
    elapsed = time.perf_counter() - started
    assert len(full.entries) == 1 and not full.truncated and full.scanned_bytes == path.stat().st_size
    assert elapsed < 5.0, elapsed


def test_the_scan_stops_at_the_time_window_before_the_event(tmp_path):
    event = voice_speech_started()
    old = filler(2_000, start=BASE - timedelta(hours=2))
    target = line("voice.speech.started", {"conversation_event_id": event.event_id},
                  at=BASE + timedelta(milliseconds=80))
    later = filler(50, start=BASE + timedelta(seconds=5))
    path = write_trace(tmp_path / "trace.jsonl", [old, target, later])
    scan = scan_trace(path, event, limits=ScanLimits(window=timedelta(minutes=15)))
    assert len(scan.entries) == 1 and scan.stopped_by == "window_start" and not scan.truncated
    assert scan.scanned_lines == 52  # later lines, the target, then the first line out of the window


def test_lines_far_after_the_event_are_not_decoded(tmp_path):
    event = voice_speech_started()
    far = line("voice.speech.started", {"conversation_event_id": event.event_id},
               at=BASE + timedelta(hours=3))
    path = write_trace(tmp_path / "trace.jsonl", [far])
    assert scan_trace(path, event).entries == []


def test_oversized_lines_are_skipped_and_counted(tmp_path):
    event = voice_speech_started()
    target = line("voice.speech.started", {"conversation_event_id": event.event_id},
                  at=BASE + timedelta(milliseconds=80))
    huge = line("voice.speech.started", {"blob": "y" * 700_000}, at=BASE + timedelta(milliseconds=90))
    path = write_trace(tmp_path / "trace.jsonl", [target, huge, filler(3, start=BASE)])
    scan = scan_trace(path, event, limits=ScanLimits(max_line_bytes=100_000))
    assert len(scan.entries) == 1 and scan.oversized_lines == 1


def test_the_match_cap_bounds_duplicate_evidence(tmp_path):
    event = voice_speech_started()
    copies = [line("voice.speech.started", {"conversation_event_id": event.event_id},
                   at=BASE + timedelta(milliseconds=80 + i)) for i in range(5)]
    scan = scan_trace(write_trace(tmp_path / "t.jsonl", copies), event, limits=ScanLimits(max_matches=3))
    assert (len(scan.entries), scan.truncated, scan.stopped_by) == (3, True, "max_matches")
    # newest first
    assert [entry["ts"] for entry in scan.entries] == sorted((entry["ts"] for entry in scan.entries), reverse=True)


def test_a_trace_without_final_newline_counts_the_torn_tail_as_corrupt(tmp_path):
    event = voice_speech_started()
    path = write_trace(tmp_path / "trace.jsonl", [
        line("voice.speech.started", {"conversation_event_id": event.event_id}, at=BASE),
        b'{"ts": "2026-09-16T10:00:00+00:00", "kind": "voice.speech.started", "data": {"conv',
    ])
    scan = scan_trace(path, event)
    assert len(scan.entries) == 1 and scan.corrupt_lines == 1


def test_scan_needs_a_runtime_journal_reference(tmp_path):
    with pytest.raises(ValueError):
        scan_trace(tmp_path / "t.jsonl", make_event(T.BRAIN_TURN_ACCEPTED, "b"))


def test_journal_times_without_offset_are_read_as_utc(tmp_path):
    event = voice_speech_started()
    naive = (BASE + timedelta(milliseconds=80)).astimezone(timezone.utc).replace(tzinfo=None)
    path = write_trace(tmp_path / "trace.jsonl", [line("voice.speech.started", {"conversation_event_id": event.event_id},
                                                       at=naive)])
    assert len(scan_trace(path, event).entries) == 1


# ------------------------------------------------------------ rework (QA S1, S2)

@pytest.mark.parametrize("message", [["Speech generation requested"], {"text": "SECRET"}, 42, None, True])
def test_a_non_string_message_is_projected_never_raised_on(tmp_path, message):
    event = voice_speech_started()
    entry = {"ts": "2026-09-16T10:00:00.080000+00:00", "kind": "voice.speech.started", "level": "info",
             "message": message, "data": {"conversation_event_id": event.event_id}}
    projected = project_trace_entry(entry)
    assert projected["message"] is None and projected["message_redacted"] is (message is not None)
    path = write_trace(tmp_path / "trace.jsonl", [(json.dumps(entry) + "\n").encode()])
    assert drill_down(event, path)["status"] == "found"


SECRET_SHAPES = {
    "api_key": "sk-proj-AbCdEf0123456789",
    "lower_api_key": "sk-abcdef0123456789",
    "email": "paul.martin@example.com",
    "windows_path": "C:/Users/Clarice/Documents/secret.txt",
    "backslash_path": r"C:\Users\Clarice\secret.txt",
    "url": "https://example.com/callback?token=abc",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl",
    "base64": "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=",
    "github": "ghp_0123456789abcdefABCDEF",
    "bearer": "Bearer abc.def",
    "spaces": "open the pod bay doors",
}


@pytest.mark.parametrize("shape", sorted(SECRET_SHAPES))
def test_secret_shaped_values_are_dropped_from_every_allowed_key(shape):
    from jarvis.runtime.conversation_event_trace import TRACE_DATA_KEYS

    value = SECRET_SHAPES[shape]
    projected = project_trace_entry({"kind": "voice.speech.started", "data": {key: value for key in TRACE_DATA_KEYS}})
    assert projected["data"] == {}, (shape, projected["data"])
    assert projected["redacted_key_count"] == len(TRACE_DATA_KEYS)


def test_real_values_of_every_key_group_are_kept():
    data = {"conversation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "correlation_id": "brain-turn:item_01AbC",
            "tool_use_id": "toolu_01ABCdef", "task_id": "agent-a1", "speech_id": "speech.1:chunk-2",
            "conversation_event_id": "cev-" + "a" * 64, "status": "completed", "code": "speech_speak_failed",
            "reason": "user_barge_in", "kind": "progress", "priority": 2, "provider": "claude", "source": "realtime",
            "disposition": "refused", "error_class": "CoreProtocolError", "exception_type": "OSError",
            "model": "claude-sonnet-4-5-20250929", "subagent_type": "general-purpose", "duplicate": False,
            "background": True, "duration_ms": 1234, "played_ms": 400, "tokens": 12000, "tool_uses": 3, "depth": 1,
            "revision": 7, "attempt": 2}
    projected = project_trace_entry({"kind": "agent.subagent.finished", "data": {**data, "status_code": 409}})
    assert projected["data"] == data
    assert projected["redacted_keys"] == ["status_code"] and projected["redacted_key_count"] == 1
    # http status as a number stays; an event id key refuses anything but cev-hex; numbers are not ids
    assert project_trace_entry({"data": {"status": 409, "conversation_event_id": "cev-XYZ", "task_id": 5}})["data"] == {
        "status": 409}


def test_redacted_key_names_are_listed_only_when_code_shaped():
    projected = project_trace_entry({"data": {"arguments": 1j, "Sk-Secret Key": "x", "sk-live-123": "y",
                                              "summary": "SECRET"}})
    assert projected["redacted_keys"] == ["arguments", "summary"]
    assert projected["redacted_key_count"] == 4


PRODUCER_SOURCES = {
    "core.brain.outcome_retained": "jarvis/core/brain_outcomes.py",
    "core.brain.outcome_matured": "jarvis/core/brain_outcomes.py",
    "core.brain.": "jarvis/core/brain_service.py",
    "voice.": "jarvis/runtime/speech_scheduler.py",
}


@pytest.mark.parametrize("kind", sorted(STATIC_MESSAGES))
def test_each_static_message_is_still_written_by_its_producer(kind):
    root = Path(__file__).resolve().parents[2]
    source_path = next(path for prefix, path in PRODUCER_SOURCES.items() if kind == prefix or kind.startswith(prefix))
    source = (root / source_path).read_text(encoding="utf-8")
    for message in STATIC_MESSAGES[kind]:
        assert f'"{message}"' in source, (kind, message, source_path)
