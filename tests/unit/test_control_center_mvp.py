from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.visual_signals import VisualSignalBus


CONTROL_CENTER_HTML = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html"


def test_visual_signal_bus_writes_supported_states(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.state("thinking")
    assert (tmp_path / ".voice_state").read_text(encoding="utf-8").strip() == "thinking"


def test_visual_signal_bus_tracks_heartbeat_and_clears_stale_visuals(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.state("listening")
    bus.alert("active")
    bus.waveform([0.5])
    bus.heartbeat()

    assert float((tmp_path / ".voice_heartbeat").read_text(encoding="utf-8")) <= time.time()

    bus.offline()
    assert (tmp_path / ".voice_state").read_text(encoding="utf-8").strip() == "idle"
    assert not (tmp_path / ".voice_heartbeat").exists()
    assert not (tmp_path / ".voice_alert").exists()
    assert not (tmp_path / ".voice_waveform").exists()
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


def test_control_center_keeps_pointer_visible_and_explains_configured_voice_toggle():
    html = CONTROL_CENTER_HTML.read_text(encoding="utf-8")
    assert "pointer-events:none;cursor:default" in html
    assert "F9 · DÉMARRER" in html
    assert "`${k} · ENVOYER`" in html
    assert "`${k} · ANNULER`" in html


def test_control_center_defaults_manual_voice_toggle_to_f9(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    assert control._settings()["manual_wake_key"] == "f9"


@pytest.mark.asyncio
async def test_control_center_rejects_stale_listening_state(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.state("listening")
    (tmp_path / ".voice_heartbeat").write_text("0\n", encoding="utf-8")
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)

    response = await control.status(None)
    payload = json.loads(response.text)

    assert payload["voice_online"] is False
    assert payload["voice_state"] == "idle"
    assert (tmp_path / ".voice_state").read_text(encoding="utf-8").strip() == "idle"


@pytest.mark.asyncio
async def test_control_center_accepts_live_listening_state(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.state("listening")
    bus.heartbeat()
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)

    response = await control.status(None)
    payload = json.loads(response.text)

    assert payload["voice_online"] is True
    assert payload["voice_state"] == "listening"
