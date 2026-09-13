from __future__ import annotations

import json

from jarvis.domain.voice_architecture import SimpleVoiceConfig, VoiceModelRef
from jarvis.runtime.control_center import ControlCenter
from jarvis.domain.live_lifecycle import LiveLifecycleState
from jarvis.runtime.conversation_context import selected_voice_context
from jarvis.runtime.voice_switch import (
    VoiceSwitchBus, VoiceSwitchCoordinator, active_task_context, prompt_transition_evidence,
)
from jarvis.runtime.voice_architecture_config import VoiceArchitectureSettings
from jarvis.runtime.journal import RuntimeJournal
from scripts.supervisor_v2 import Supervisor


SOURCE = "a" * 64
TARGET = "b" * 64


def issue(bus: VoiceSwitchBus):
    return bus.request(source_configuration_id=SOURCE, target_configuration_id=TARGET,
                       target_architecture="duplex", target_model="gpt-live-1")


def test_switch_bus_is_idempotent_and_handoff_contains_only_bounded_metadata(tmp_path):
    bus = VoiceSwitchBus(tmp_path)
    first, second = issue(bus), issue(bus)
    context = {"recent_turns": [{"kind": "user", "content": "hello"}]}
    work = {"revision": 7, "items": [
        {"status": "running", "label": "search", "summary": "working"},
        {"status": "completed", "label": "old", "summary": "done"},
    ]}
    bus.write_handoff(first, conversation_id="conversation-1", context=context, work=work)

    assert first.request_id == second.request_id
    handoff = bus.handoff(TARGET)
    assert handoff["conversation_id"] == "conversation-1"
    assert handoff["recent_turn_count"] == 1 and handoff["active_work_count"] == 1
    raw = (tmp_path / ".voice_switch_handoff").read_text(encoding="utf-8")
    assert "hello" not in raw and "working" not in raw


def test_active_work_projection_is_public_bounded_and_ignores_terminal_items():
    work = {"items": [
        {"status": "running", "label": "Flight", "summary": "Checking alternatives"},
        {"status": "blocked", "kind": "calendar", "activity": "Waiting for choice"},
        {"status": "completed", "label": "Done", "summary": "must not appear"},
    ]}
    text = active_task_context(work)
    assert "Flight: Checking alternatives [running]" in text
    assert "calendar: Waiting for choice [blocked]" in text
    assert "must not appear" not in text
    assert len(text) <= 4096 + 80


def test_selected_context_adds_task_summary_without_rewriting_spoken_history():
    original = {"voice_ledger": {}, "recent_turns": [
        {"kind": "user", "content": "question"},
        {"kind": "assistant", "content": "heard answer"},
    ], "switch_task_context": "Travaux JARVIS actifs:\n- search"}
    selected = selected_voice_context(original)
    assert [(item.role.value, item.text) for item in selected.messages] == [
        ("user", "question"), ("assistant", "heard answer"),
        ("developer", "Travaux JARVIS actifs:\n- search"),
    ]
    assert original["recent_turns"][1]["content"] == "heard answer"


def test_new_session_trace_keeps_prompt_revisions_without_prompt_text():
    evidence = prompt_transition_evidence([{
        "program_id": "voice.simple.openai.session", "layer_revisions": ["r1", "r2"],
        "static_fingerprint": "f" * 64, "application": "acknowledged",
        "text": "private prompt must not enter trace",
    }])
    raw = json.dumps(evidence)
    assert evidence[0]["layer_revisions"] == ["r1", "r2"]
    assert "private prompt" not in raw and "text" not in evidence[0]


class Runtime:
    conversation_id = "conversation-1"


class Voice:
    def __init__(self, *, pending=False):
        self.runtime = Runtime()
        self.pending = pending
        self.muted = 0
        self.exited = False

    async def mode_switch(self):
        self.muted += 1

    def switch_close_pending(self):
        return self.pending

    def accept_reaped_live_close(self):
        return False

    def request_switch_exit(self):
        self.exited = True


class Core:
    def __init__(self, live=None):
        self.live = live
        self.work = {"store_id": "store", "revision": 9, "items": [
            {"status": "running", "label": "kept", "summary": "still running"},
        ], "updated_at": "2026-09-13T00:00:00+00:00"}

    async def context(self, conversation_id):
        assert conversation_id == "conversation-1"
        return {"conversation_id": conversation_id, "voice_ledger": {},
                "recent_turns": [{"kind": "user", "content": "keep me"}]}

    async def work_snapshot(self):
        return self.work

    async def live_session_status(self):
        return self.live


async def test_coordinator_snapshots_stops_and_requests_supervised_restart(tmp_path):
    bus, voice, core = VoiceSwitchBus(tmp_path), Voice(), Core()
    request = issue(bus)
    coordinator = VoiceSwitchCoordinator(voice=voice, core=core, bus=bus,
        configuration_id=SOURCE, architecture="simple", model="old-model")

    assert await coordinator.poll() is True

    assert voice.muted == 1 and voice.exited is True
    assert bus.read_request() is None
    assert bus.receipt()["status"] == "ready_for_restart"
    assert bus.handoff(TARGET)["request_id"] == request.request_id
    assert core.work["items"][0]["status"] == "running"


async def test_simple_front_duplex_simple_sequence_keeps_conversation_and_work(tmp_path):
    bus, core = VoiceSwitchBus(tmp_path), Core()
    configurations = [("simple", "simple-model", "a" * 64),
                      ("front_brain", "reflex-model", "b" * 64),
                      ("duplex", "gpt-live-1", "c" * 64),
                      ("simple", "simple-model-2", "d" * 64),
                      ("simple", "simple-model-3", "e" * 64)]
    for (source_arch, source_model, source_id), (target_arch, target_model, target_id) in zip(
        configurations, configurations[1:]
    ):
        bus.request(source_configuration_id=source_id, target_configuration_id=target_id,
                    target_architecture=target_arch, target_model=target_model)
        voice = Voice()
        coordinator = VoiceSwitchCoordinator(voice=voice, core=core, bus=bus,
            configuration_id=source_id, architecture=source_arch, model=source_model)
        assert await coordinator.poll() is True
        handoff = bus.handoff(target_id)
        assert handoff["conversation_id"] == "conversation-1"
        bus.mark_handoff_loaded(handoff)
        assert bus.receipt()["status"] == "applied"
        bus.clear_handoff(handoff["request_id"])
    assert core.work["items"][0]["status"] == "running"


async def test_unresolved_old_live_session_blocks_replacement(tmp_path):
    bus, voice = VoiceSwitchBus(tmp_path), Voice()
    issue(bus)
    core = Core(live=type("Record", (), {"state": LiveLifecycleState.UNKNOWN_REAP_REQUIRED})())
    coordinator = VoiceSwitchCoordinator(voice=voice, core=core, bus=bus,
        configuration_id=SOURCE, architecture="duplex", model="gpt-live-1")

    assert await coordinator.poll() is False
    assert voice.exited is False
    assert bus.read_request() is not None
    assert bus.receipt()["status"] == "blocked"


async def test_old_frontend_close_failure_is_visible_and_never_restarts(tmp_path):
    bus = VoiceSwitchBus(tmp_path)
    issue(bus)

    class BrokenVoice(Voice):
        async def mode_switch(self):
            raise OSError("controlled close failure")

    voice = BrokenVoice()
    coordinator = VoiceSwitchCoordinator(voice=voice, core=Core(), bus=bus,
        configuration_id=SOURCE, architecture="simple", model="old-model")

    assert await coordinator.poll() is False
    assert voice.exited is False and bus.read_request() is not None
    assert bus.receipt()["status"] == "failed"


async def test_already_loaded_target_acknowledges_without_another_stop(tmp_path):
    bus, voice = VoiceSwitchBus(tmp_path), Voice()
    request = issue(bus)
    coordinator = VoiceSwitchCoordinator(voice=voice, core=Core(), bus=bus,
        configuration_id=TARGET, architecture="duplex", model="gpt-live-1")

    assert await coordinator.poll() is False
    assert voice.muted == 0 and voice.exited is False
    assert bus.read_request() is None
    assert bus.receipt()["request_id"] == request.request_id
    assert bus.receipt()["status"] == "applied"


def test_conversation_pointer_survives_voice_process_restart(tmp_path):
    bus = VoiceSwitchBus(tmp_path)
    bus.remember_conversation("conversation-42", SOURCE)
    assert VoiceSwitchBus(tmp_path).conversation_id() == "conversation-42"
    stored = json.loads((tmp_path / ".voice_conversation").read_text(encoding="utf-8"))
    assert set(stored) == {"schema_version", "conversation_id", "configuration_id", "updated_at"}


class JsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


async def test_control_center_architecture_save_emits_a_switch_command(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_VOICE_ARCH", raising=False)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    settings = control._settings()
    settings["voice_architecture"] = VoiceArchitectureSettings(
        SimpleVoiceConfig(VoiceModelRef("openai", "gpt-realtime-2.1-mini"))
    ).to_dict()
    control._write_settings(settings)
    query = control._voice_architecture_payload(settings)
    target = next(item["defaults"] for item in query["architectures"] if item["id"] == "front_brain")

    response = await control.save_settings(JsonRequest({"voice": {"architecture": target}}))
    body = json.loads(response.text)
    request = VoiceSwitchBus(tmp_path).read_request()

    assert request is not None and request.target_architecture == "front_brain"
    assert request.source_configuration_id != request.target_configuration_id
    assert body["voice"]["switch"]["pending"] is True


async def test_same_architecture_model_change_emits_a_new_session_switch(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_VOICE_ARCH", raising=False)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    settings = control._settings()
    settings["voice_architecture"] = VoiceArchitectureSettings(
        SimpleVoiceConfig(VoiceModelRef("openai", "gpt-realtime-2.1-mini"))
    ).to_dict()
    control._write_settings(settings)
    target = VoiceArchitectureSettings(
        SimpleVoiceConfig(VoiceModelRef("openai", "gpt-realtime-2.1"))
    ).to_dict()["config"]

    await control.save_settings(JsonRequest({"voice": {"architecture": target}}))
    request = VoiceSwitchBus(tmp_path).read_request()

    assert request is not None and request.target_architecture == "simple"
    assert request.target_model == "gpt-realtime-2.1"


def test_supervisor_recognizes_switch_restart_without_treating_it_as_a_crash(tmp_path):
    bus = VoiceSwitchBus(tmp_path)
    request = issue(bus)
    bus.write_handoff(request, conversation_id="conversation-1", context={}, work={"items": []})
    bus.complete(request, status="ready_for_restart")
    supervisor = Supervisor(journal=RuntimeJournal(tmp_path), runtime_root=tmp_path)

    assert supervisor._voice_switch_restart_requested() is True
