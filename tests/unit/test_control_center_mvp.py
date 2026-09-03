from __future__ import annotations

import json

from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.visual_signals import VisualSignalBus


def test_visual_signal_bus_writes_supported_states(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.state("thinking")
    assert (tmp_path / ".voice_state").read_text(encoding="utf-8").strip() == "thinking"
    bus.alert("provider failed")
    assert "provider failed" in (tmp_path / ".voice_alert").read_text(encoding="utf-8")
    bus.alert(None)
    assert not (tmp_path / ".voice_alert").exists()


def test_visual_signal_bus_writes_waveform(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.waveform([1.0, -2.0, 3.0])
    payload = json.loads((tmp_path / ".voice_waveform").read_text(encoding="utf-8"))
    assert payload["samples"] == [1.0, -2.0, 3.0]
    assert payload["ts"] > 0


def test_runtime_journal_splits_errors_and_trace(tmp_path):
    journal = RuntimeJournal(tmp_path)
    journal.emit("voice.start", "started")
    journal.emit("provider.error", "boom", level="error", data={"code": "bad"})

    trace = read_jsonl_tail(journal.trace_path)
    errors = read_jsonl_tail(journal.error_path)
    assert [item["kind"] for item in trace] == ["voice.start", "provider.error"]
    assert [item["kind"] for item in errors] == ["provider.error"]
    assert errors[0]["data"]["code"] == "bad"


def test_runtime_journal_tail_limit(tmp_path):
    journal = RuntimeJournal(tmp_path)
    for index in range(5):
        journal.emit("event", str(index))
    assert [item["message"] for item in read_jsonl_tail(journal.trace_path, limit=2)] == ["3", "4"]
