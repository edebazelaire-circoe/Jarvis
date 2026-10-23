"""Graphe d'architecture (Slice 01) : projection par architecture, mutations transactionnelles, disposition.

Contrat : docs/architecture-graph.md. Les fixtures de l'interface (`tests/fixtures/architecture_snapshot_*.json`)
sont produites par la projection : `JARVIS_WRITE_ARCHITECTURE_FIXTURES=1 pytest tests/unit/test_architecture_graph.py`
les réécrit, sinon ce test vérifie qu'elles sont à jour.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.domain.architecture_graph import (
    ArchitectureGraphError, Channel, Port, PortDirection, port_incompatibility,
)
from jarvis.runtime.architecture_graph import (
    ArchitectureGraphService, FileSettingsStore, RuntimeObservations, observe_runtime, project_architecture,
)
from jarvis.runtime.architecture_graph_routes import ArchitectureGraphRoutes
from jarvis.runtime.architecture_layout import ArchitectureLayoutStore
from jarvis.runtime.back_brain_delegation import BACK_BRAIN_DELEGATE, VOICE_ALONE_RULE, conversation_tools
from jarvis.runtime.realtime_frontend_session import RealtimeFrontendSession
from jarvis.runtime.tool_brain_ownership import JARVIS_DEFAULT, OwnershipView
from jarvis.runtime.tool_brain_runtime import ToolBrainMode
from jarvis.runtime.tool_brain_wiring import build_tool_brain, resolve_mode
from jarvis.runtime.voice_composition import resolve_voice_composition
from jarvis.core.v2_services import CoreEventBus
from tests.integration.test_voice_production_composition import ControlledWire
from tests.unit.test_v2_voice_toggle import FakeHttpSession

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _selection(config: dict) -> dict:
    return {"voice_architecture": {"schema_version": 1, "config": config, "compatibility": None}}


DUPLEX = _selection({"architecture": "duplex", "conversation_model": {"provider_id": "openai", "model_id": "gpt-live-1"}})
SIMPLE = _selection({"architecture": "simple", "conversation_model": {"provider_id": "openai", "model_id": "gpt-realtime-2.1"}})
FRONT = _selection({"architecture": "front_brain", "reflex_model": {"provider_id": "openai", "model_id": "gpt-realtime-2.1"},
                    "analysis_model": {"provider_id": "openai", "model_id": "gpt-5.6-luna"}})


def _observed(settings: dict | None, *, core: bool = True, tool: OwnershipView = JARVIS_DEFAULT) -> RuntimeObservations:
    """Voice tourne sur la configuration `settings` (ou ne tourne pas si `None`)."""

    voice = None
    if settings is not None:
        voice = {"configuration_id": resolve_voice_composition(settings, environ={}).configuration_id, "ts": time.time()}
    return RuntimeObservations(voice, tool, core)


def _service(tmp_path: Path, settings: dict, *, environ: dict | None = None, observations=None, switch=None):
    store = FileSettingsStore(tmp_path)
    store.write(settings)
    calls: list = []

    def requester(previous, updated, observed):
        calls.append((previous, updated))
        return {"request_id": "switch-1"}

    service = ArchitectureGraphService(tmp_path, store=store, environ=environ or {},
                                       observe=lambda: observations or _observed(None),
                                       voice_switch=switch or requester)
    return service, store, calls


# ------------------------------------------------------------------ projection

@pytest.mark.parametrize("settings,environ,arch,nodes,delegate", [
    (DUPLEX, {}, "duplex", ["mic", "voice", "core", "tool_brain", "subagents", "speakers"], "voice.delegate->core.request"),
    (SIMPLE, {}, "simple", ["mic", "voice", "core", "tool_brain", "subagents", "speakers"], "voice.delegate->core.job"),
    (FRONT, {}, "front_brain", ["mic", "voice", "luna", "core", "tool_brain", "subagents", "speakers"], "voice.delegate->core.job"),
    ({}, {}, "legacy", ["mic", "voice", "core", "tool_brain", "subagents", "speakers"], "voice.delegate->core.job"),
    ({"voice_arch": "continuous_brain"}, {}, "continuous_brain", ["mic", "voice", "core", "tool_brain", "subagents", "speakers"],
     "voice.delegate->core.request"),
])
def test_the_snapshot_shows_only_the_real_nodes_of_the_effective_voice_architecture(settings, environ, arch, nodes, delegate):
    snapshot = project_architecture(settings, environ=environ, observations=_observed(None)).to_dict()
    assert snapshot["voice_architecture"]["id"] == arch
    assert [node["id"] for node in snapshot["nodes"]] == nodes
    ids = {conn["id"]: conn for conn in snapshot["connections"]}
    assert delegate in ids
    for conn in snapshot["connections"]:
        assert set(conn) >= {"id", "source", "target", "channel", "purpose", "enabled", "mutability", "locked_reason",
                             "impact_when_disabled", "applies", "pending", "governed_by", "binding"}
        assert conn["binding"] and conn["purpose"]
    # Tool Brain affiché même coupé (état inactif) ; Core -> Sous-agents gouvernée, en lecture seule.
    tool = next(node for node in snapshot["nodes"] if node["id"] == "tool_brain")
    assert tool["state"] == "inactive" and tool["details"]["mode"] == "off"
    agents = ids["core.agents->subagents.spawn"]
    assert agents["mutability"] == "governed"
    assert agents["governed_by"] == {"kind": "brain_config", "node": "core", "field": "delegation"}
    expected = "toggleable" if arch in ("duplex", "simple", "front_brain") else "required_locked"
    assert ids[delegate]["mutability"] == expected


def test_audio_and_core_speech_links_are_locked_with_a_reason():
    snapshot = project_architecture(DUPLEX, environ={}, observations=_observed(DUPLEX)).to_dict()
    ids = {conn["id"]: conn for conn in snapshot["connections"]}
    for conn_id in ("mic.audio_out->voice.audio_in", "voice.audio_out->speakers.audio_in", "core.speech->voice.speech_in"):
        assert ids[conn_id]["mutability"] == "required_locked" and ids[conn_id]["locked_reason"]


def test_port_compatibility_requires_direction_channel_and_family():
    out_audio = Port("o", PortDirection.OUT, Channel.AUDIO, "audio")
    assert port_incompatibility(out_audio, Port("i", PortDirection.IN, Channel.AUDIO, "audio")) is None
    assert "entrée" in port_incompatibility(Port("i", PortDirection.IN, Channel.AUDIO, "audio"), out_audio)
    assert "Canaux" in port_incompatibility(out_audio, Port("i", PortDirection.IN, Channel.EVENT, "audio"))
    assert "Familles" in port_incompatibility(out_audio, Port("i", PortDirection.IN, Channel.AUDIO, "speech"))


def test_runtime_observations_read_the_voice_heartbeat_and_the_core_token(tmp_path):
    assert observe_runtime(tmp_path).voice is None and observe_runtime(tmp_path).core_running is False
    (tmp_path / ".voice_runtime").write_text(json.dumps({"configuration_id": "abc", "ts": time.time()}), encoding="utf-8")
    (tmp_path / "core.token").write_text("t", encoding="utf-8")
    observed = observe_runtime(tmp_path)
    assert observed.voice["configuration_id"] == "abc" and observed.core_running
    (tmp_path / ".voice_runtime").write_text(json.dumps({"configuration_id": "abc", "ts": time.time() - 60}), encoding="utf-8")
    assert observe_runtime(tmp_path).voice is None


# ------------------------------------------------------------------ mutations

def test_disabling_duplex_delegation_writes_brain_orchestration_and_reports_it_pending_until_voice_restarts(tmp_path):
    service, store, calls = _service(tmp_path, DUPLEX, observations=_observed(DUPLEX))
    before = service.snapshot()
    result = service.set_connection_enabled("voice.delegate->core.request", base_revision=before.revision, enabled=False)
    assert result.changed and result.voice_switch == {"request_id": "switch-1"} and len(calls) == 1
    # Le réglage relu par Voice au démarrage (`LiveFrontendSession` reçoit `mode.brain_orchestration`).
    assert resolve_voice_composition(store.read(), environ={}).selection.config.brain_orchestration is False
    conn = result.snapshot.connection("voice.delegate->core.request").to_dict()
    # Voice tourne encore sur l'ancienne configuration : état vivant activé, nouvelle valeur en attente.
    assert conn["enabled"] is True and conn["pending"] == {"enabled": False, "applies": "voice_restart"}
    assert result.snapshot.revision != before.revision


async def test_disabling_simple_delegation_removes_the_tool_from_the_real_surface(tmp_path):
    service, store, _calls = _service(tmp_path, SIMPLE)
    revision = service.snapshot().revision
    service.set_connection_enabled("voice.delegate->core.job", base_revision=revision, enabled=False)
    composition = resolve_voice_composition(store.read(), environ={})
    assert composition.back_brain_delegation is False
    assert composition.configuration_id != resolve_voice_composition(SIMPLE, environ={}).configuration_id
    wire = ControlledWire()
    session = await RealtimeFrontendSession.connect(
        api_key="controlled", model="gpt-realtime-2.1", voice="cedar", context={}, conversational=True,
        continuous_brain=True, auto_turn=True, tools=conversation_tools(), session=FakeHttpSession(wire),
        back_brain_delegation=composition.back_brain_delegation)
    try:
        update = next(event["session"] for event in wire.sent if event["type"] == "session.update")
        assert BACK_BRAIN_DELEGATE not in json.dumps(update.get("tools", []))
        assert VOICE_ALONE_RULE in update["instructions"]
        assert session._back_brain is None and session.dispatch_back_brain(None, "c", "call") is False
        assert session.back_brain_delegation_disabled is True  # un appel halluciné le dira (I-001 S01-4)
    finally:
        await session.close()


async def test_default_simple_surface_still_offers_the_delegation_tool():
    wire = ControlledWire()
    session = await RealtimeFrontendSession.connect(
        api_key="controlled", model="gpt-realtime-2.1", voice="cedar", context={}, conversational=True,
        continuous_brain=True, auto_turn=True, tools=conversation_tools(), session=FakeHttpSession(wire))
    try:
        update = next(event["session"] for event in wire.sent if event["type"] == "session.update")
        assert BACK_BRAIN_DELEGATE in json.dumps(update.get("tools", []))
        assert VOICE_ALONE_RULE not in update["instructions"] and session._back_brain is not None
        assert session.back_brain_delegation_disabled is False
    finally:
        await session.close()


def test_enabling_the_tool_brain_link_persists_shadow_and_core_builds_it_at_next_start(tmp_path):
    service, store, calls = _service(tmp_path, SIMPLE, observations=_observed(SIMPLE))
    result = service.set_connection_enabled("core.events->tool_brain.wake", base_revision=service.snapshot().revision,
                                            enabled=True)
    settings = store.read()
    assert settings["tool_brain"] == {"mode": "shadow"} and calls == []  # pas de bascule de Voice pour Core
    assert resolve_mode(settings, {}) == (ToolBrainMode.SHADOW, "settings")
    conn = result.snapshot.connection("core.events->tool_brain.wake").to_dict()
    assert conn["enabled"] is False and conn["pending"] == {"enabled": True, "applies": "core_restart"}
    core = SimpleNamespace(scene=object(), boards=object(), events=CoreEventBus(), conversation_event_emitter=object(),
                           brain=SimpleNamespace(list_ui_intents=lambda c, correlation_id=None: []))
    runtime, _sources = build_tool_brain(core, control_settings=lambda: settings, cwd=".", runtime_root=".", environ={})
    assert runtime.mode is ToolBrainMode.SHADOW


def test_an_environment_tool_brain_mode_locks_the_link_and_nothing_is_written(tmp_path):
    service, store, _calls = _service(tmp_path, SIMPLE, environ={"JARVIS_TOOL_BRAIN": "shadow"})
    snapshot = service.snapshot()
    conn = snapshot.connection("core.events->tool_brain.wake")
    assert conn.mutability.value == "required_locked" and "JARVIS_TOOL_BRAIN=shadow" in conn.locked_reason
    raw = store.path.read_bytes()
    with pytest.raises(ArchitectureGraphError) as refused:
        service.set_connection_enabled(conn.id, base_revision=snapshot.revision, enabled=False)
    assert (refused.value.code, refused.value.status) == ("connection_locked", 423)
    assert store.path.read_bytes() == raw


def test_a_stale_revision_is_refused_and_nothing_is_written(tmp_path):
    service, store, _calls = _service(tmp_path, SIMPLE)
    stale = service.snapshot().revision
    settings = store.read()
    settings["tool_brain"] = {"mode": "shadow"}  # une autre page a écrit entre-temps
    store.write(settings)
    raw = store.path.read_bytes()
    with pytest.raises(ArchitectureGraphError) as refused:
        service.set_connection_enabled("voice.delegate->core.job", base_revision=stale, enabled=False)
    assert (refused.value.code, refused.value.status) == ("architecture_revision_stale", 409)
    assert store.path.read_bytes() == raw


@pytest.mark.parametrize("conn_id,code,status", [
    ("core.agents->subagents.spawn", "connection_governed", 422),
    ("mic.audio_out->voice.audio_in", "connection_locked", 423),
    ("voice.delegate->core.request", "connection_unknown", 422),  # n'existe pas en Simple
])
def test_governed_locked_and_unknown_links_are_refused_with_stable_codes(tmp_path, conn_id, code, status):
    service, _store, _calls = _service(tmp_path, SIMPLE)
    with pytest.raises(ArchitectureGraphError) as refused:
        service.set_connection_enabled(conn_id, base_revision=service.snapshot().revision, enabled=False)
    assert (refused.value.code, refused.value.status) == (code, status) and refused.value.reason


def test_creating_or_deleting_links_is_refused_because_no_runtime_binding_exists(tmp_path):
    service, _store, _calls = _service(tmp_path, SIMPLE)
    revision = service.snapshot().revision
    with pytest.raises(ArchitectureGraphError) as incompatible:
        service.create_connection(base_revision=revision, source={"node": "mic", "port": "audio_out"},
                                  target={"node": "tool_brain", "port": "wake"}, channel="audio")
    assert incompatible.value.code == "connection_incompatible"
    with pytest.raises(ArchitectureGraphError) as unbindable:
        service.create_connection(base_revision=revision, source={"node": "mic", "port": "audio_out"},
                                  target={"node": "speakers", "port": "audio_in"}, channel="audio")
    assert unbindable.value.code == "connection_unbindable"
    with pytest.raises(ArchitectureGraphError) as removable:
        service.delete_connection("voice.delegate->core.job", base_revision=revision)
    assert removable.value.code == "connection_not_removable"


def test_a_voice_switch_failure_restores_the_previous_settings(tmp_path):
    def broken(previous, updated, observed):
        raise OSError("bus unwritable")

    service, store, _calls = _service(tmp_path, SIMPLE, switch=broken)
    raw = store.path.read_bytes()
    with pytest.raises(ArchitectureGraphError) as failed:
        service.set_connection_enabled("voice.delegate->core.job", base_revision=service.snapshot().revision, enabled=False)
    assert (failed.value.code, failed.value.status) == ("architecture_apply_failed", 500)
    assert json.loads(store.path.read_bytes()) == json.loads(raw)


def test_writing_the_current_value_is_an_idempotent_no_op(tmp_path):
    service, store, calls = _service(tmp_path, SIMPLE)
    raw = store.path.read_bytes()
    result = service.set_connection_enabled("voice.delegate->core.job", base_revision=service.snapshot().revision,
                                            enabled=True)
    assert result.changed is False and calls == [] and store.path.read_bytes() == raw


# ------------------------------------------------------------------ disposition

def test_layout_has_its_own_revision_and_never_touches_the_topology(tmp_path):
    service, store, _calls = _service(tmp_path, SIMPLE)
    layout = ArchitectureLayoutStore(tmp_path)
    topology = service.snapshot().revision
    settings_bytes = store.path.read_bytes()
    first = layout.write(base_revision="l-0", positions={"voice": {"x": 120, "y": 80}})
    assert first.revision_token == "l-1" and layout.read().positions == {"voice": {"x": 120.0, "y": 80.0}}
    assert service.snapshot().revision == topology and store.path.read_bytes() == settings_bytes
    with pytest.raises(ArchitectureGraphError) as stale:
        layout.write(base_revision="l-0", positions={})
    assert (stale.value.code, stale.value.status) == ("layout_revision_stale", 409)
    service.set_connection_enabled("voice.delegate->core.job", base_revision=topology, enabled=False)
    assert layout.read().revision_token == "l-1"
    with pytest.raises(ArchitectureGraphError) as invalid:
        layout.write(base_revision="l-1", positions={"voice": {"x": float("nan"), "y": 0}})
    assert invalid.value.code == "layout_invalid"


# ------------------------------------------------------------------ routes (non montées)

async def test_routes_answer_the_snapshot_and_coded_refusals(tmp_path):
    service, _store, _calls = _service(tmp_path, SIMPLE)
    app = web.Application()
    app.add_routes(ArchitectureGraphRoutes(service, ArchitectureLayoutStore(tmp_path)).routes())
    async with TestClient(TestServer(app)) as client:
        snapshot = await (await client.get("/api/architecture")).json()
        assert snapshot["schema_version"] == 1 and snapshot["voice_architecture"]["id"] == "simple"
        url = "/api/architecture/connections/" + "voice.delegate-%3Ecore.job"
        stale = await client.post(url, json={"base_revision": "t-old", "enabled": False})
        body = await stale.json()
        assert stale.status == 409 and body["code"] == "architecture_revision_stale" and body["snapshot"]["revision"]
        ok = await client.post(url, json={"base_revision": snapshot["revision"], "enabled": False})
        body = await ok.json()
        assert ok.status == 200 and body["ok"] and body["changed"]
        assert next(c for c in body["snapshot"]["connections"] if c["id"] == "voice.delegate->core.job")["enabled"] is False
        locked = await client.post("/api/architecture/connections/mic.audio_out-%3Evoice.audio_in",
                                   json={"base_revision": body["snapshot"]["revision"], "enabled": False})
        assert locked.status == 423 and (await locked.json())["code"] == "connection_locked"
        bad = await client.post(url, data="not json")
        assert bad.status == 400 and (await bad.json())["code"] == "architecture_request_invalid"
        layout = await client.put("/api/architecture/layout", json={"base_revision": "l-0", "positions": {"core": {"x": 1, "y": 2}}})
        assert layout.status == 200 and (await layout.json())["revision"] == "l-1"


# ------------------------------------------------------------------ fixtures de l'interface

@pytest.mark.parametrize("name,settings", [("duplex", DUPLEX), ("simple", SIMPLE)])
def test_ui_fixtures_are_the_projection_output(name, settings):
    tool = OwnershipView("jarvis_direct", "off", "no_publication")
    snapshot = project_architecture(settings, environ={}, observations=_observed(settings, tool=tool)).to_dict()
    text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    path = FIXTURES / f"architecture_snapshot_{name}.json"
    if os.environ.get("JARVIS_WRITE_ARCHITECTURE_FIXTURES") == "1":
        path.write_text(text, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == text, f"fixture périmée : {path.name} (régénérez-la)"


def test_resolve_mode_reads_a_set_variable_first_then_the_saved_block_then_off():
    """I-001 S01-5 (Slice 07) : `resolve_mode` testé directement. Une variable vide ne compte pas (le bloc décide)."""
    block = {"tool_brain": {"mode": "active"}}
    assert resolve_mode(block, {}) == (ToolBrainMode.ACTIVE, "settings")
    assert resolve_mode(block, {"JARVIS_TOOL_BRAIN": "  "}) == (ToolBrainMode.ACTIVE, "settings")
    assert resolve_mode(block, {"JARVIS_TOOL_BRAIN": "shadow"}) == (ToolBrainMode.SHADOW, "env")
    assert resolve_mode({}, {}) == (ToolBrainMode.OFF, "default")
    assert resolve_mode({"tool_brain": {"mode": "inconnu"}}, {}) == (ToolBrainMode.OFF, "settings")
