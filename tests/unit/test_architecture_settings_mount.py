"""Montage de la page Architecture & Agents dans le vrai Control Center (jarvis-architecture-agents-settings-editor,
Slice 07).

Les services des Slices 01 à 03 sont testés seuls dans leurs fichiers ; celui-ci prouve leur assemblage par
`ControlCenter` : routes servies par l'application aiohttp, services uniques pour la vie du Control Center, crochet
`after_settings_write` de la fenêtre du cerveau Core, fournisseurs de catalogue et de candidats du Control Center,
règle de bascule de Voice commune avec `POST /api/settings`. Runtime temporaire : jamais le JARVIS vivant.
"""

from __future__ import annotations

import json

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.voice_switch import REQUEST_FILE, plan_voice_switch
from tests.unit.test_brain_config import SIMPLE, fake_catalog


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("JARVIS_TOOL_BRAIN", "JARVIS_TOOL_BRAIN_MODEL", "JARVIS_VOICE_ARCH", "JARVIS_VOICE_STACK",
                 "JARVIS_AGENT_CLI"):
        monkeypatch.delenv(name, raising=False)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    control._write_settings({**SIMPLE, "agent_cli": "claude"})
    # Les fournisseurs réels lancent `claude --version` et appellent les fournisseurs : remplacés ici, à la même place.
    control.brain_config._catalog = fake_catalog
    return control


def kinds(control) -> list[str]:
    return [event["kind"] for event in read_jsonl_tail(control.journal.trace_path)]


def test_services_are_built_once_and_share_the_settings_lock(control):
    assert control.brain_config.graph is control.architecture_graph
    assert control.architecture_routes.service is control.architecture_graph
    assert control.brain_config.journal is control.journal and control.architecture_graph.journal is control.journal
    paths = {str(r.resource.canonical) for r in control._app.router.routes()}
    assert {"/api/architecture", "/api/architecture/connections/{connection_id}", "/api/architecture/layout",
            "/api/brains/{brain_id}/config", "/api/subagent-role-routing/{role_id}"} <= paths


async def test_graph_toggle_changes_the_runtime_setting_and_requests_the_voice_switch(control):
    async with TestClient(TestServer(control._app)) as client:
        snapshot = await (await client.get("/api/architecture")).json()
        assert snapshot["voice_architecture"]["id"] == "simple"
        link = next(c for c in snapshot["connections"] if c["id"] == "voice.delegate->core.job")
        assert link["enabled"] is True and link["mutability"] == "toggleable"
        response = await client.post("/api/architecture/connections/voice.delegate->core.job",
                                     json={"base_revision": snapshot["revision"], "enabled": False})
        body = await response.json()
        assert response.status == 200 and body["ok"] and body["changed"]
        locked = await client.post("/api/architecture/connections/mic.audio_out->voice.audio_in",
                                   json={"base_revision": body["snapshot"]["revision"], "enabled": False})
        assert locked.status == 423 and (await locked.json())["code"] == "connection_locked"
        stale = await client.post("/api/architecture/connections/voice.delegate->core.job",
                                  json={"base_revision": snapshot["revision"], "enabled": True})
        assert stale.status == 409
    stored = json.loads(control.settings_path.read_text(encoding="utf-8"))
    assert stored["voice_surface"]["back_brain_delegation"] is False
    assert (control.runtime_root / REQUEST_FILE).is_file()
    assert {"architecture.connection.updated", "voice.switch.requested", "architecture.write.refused"} <= set(kinds(control))


async def test_core_delegation_round_trip_reaches_the_graph(control):
    async with TestClient(TestServer(control._app)) as client:
        config = await (await client.get("/api/brains/core/config")).json()
        assert config["catalog"]["status"] == "ok"
        assert [c["value"] for c in config["fields"]["model"]["choices"]][:2] == ["", "claude-opus-5-5"]
        never = await client.patch("/api/brains/core/config", json={"base_revision": config["revision"],
                                                                    "delegation": "never"})
        body = await never.json()
        assert never.status == 200 and body["config"]["fields"]["delegation"]["value"] == "never"
        graph = await (await client.get("/api/architecture")).json()
        spawn = next(c for c in graph["connections"] if c["id"] == "core.agents->subagents.spawn")
        assert spawn["enabled"] is False and spawn["mutability"] == "governed"
        back = await client.patch("/api/brains/core/config", json={"base_revision": body["config"]["revision"],
                                                                   "delegation": "standard"})
        assert back.status == 200
        graph = await (await client.get("/api/architecture")).json()
        assert next(c for c in graph["connections"] if c["id"] == "core.agents->subagents.spawn")["enabled"] is True
    assert json.loads((control.runtime_root / "brain-config.json").read_text(encoding="utf-8"))["brains"]["core"][
        "delegation"] == "standard"


async def test_core_model_write_reconfigures_the_live_agents_through_the_hook(control, monkeypatch):
    applied: list[dict] = []
    monkeypatch.setattr(control, "_apply_agent_settings", lambda settings: applied.append(settings))
    async with TestClient(TestServer(control._app)) as client:
        config = await (await client.get("/api/brains/core/config")).json()
        response = await client.patch("/api/brains/core/config", json={"base_revision": config["revision"],
                                                                       "model": "claude-haiku-5"})
        assert response.status == 200, await response.text()
    assert applied and applied[-1]["agent_cli_settings"]["claude"]["model"] == "claude-haiku-5"
    assert "claude_cli" in applied[-1]  # relu par `_settings()` : mêmes défauts que `POST /api/settings`
    assert "brain_config.agents_reconfigured" in kinds(control)


async def test_role_policy_put_uses_the_control_center_candidates(control):
    measured_calls: list[int] = []

    async def measured():
        measured_calls.append(1)
        from jarvis.domain.routing import ModelCandidate
        return [ModelCandidate(agent="claude", model="claude-haiku-5", capabilities=frozenset({"code"}))], {}

    control.role_routing_routes._candidates = measured
    async with TestClient(TestServer(control._app)) as client:
        snapshot = await (await client.get("/api/subagent-role-routing")).json()
        qa = next(r for r in snapshot["roles"] if r["role_id"] == "qa")
        assert qa["explicit"] is False
        put = await client.put("/api/subagent-role-routing/qa", json={
            "base_revision": snapshot["revision"], "allow_general_fallback": False,
            "candidates": [{"agent": "claude", "model": "claude-haiku-5"}]})
        body = await put.json()
        assert put.status == 200, body
        assert next(r for r in body["snapshot"]["roles"] if r["role_id"] == "qa")["provenance"] == "explicit"
    assert measured_calls


def test_voice_switch_rule_is_shared_with_post_settings(tmp_path):
    """`plan_voice_switch` : la source est la configuration publiée par Voice quand elle est fournie, sinon celle des
    réglages précédents ; rien si l'identité ne change pas."""
    after = json.loads(json.dumps(SIMPLE))
    after["voice_surface"] = {"back_brain_delegation": False}
    plan = plan_voice_switch(SIMPLE, after, environ={})
    assert plan is not None and plan.target_architecture == "simple" and plan.target_model
    assert plan_voice_switch(SIMPLE, SIMPLE, environ={}) is None
    running = plan_voice_switch(SIMPLE, SIMPLE, running_configuration_id="voice-old", environ={})
    assert running is not None and running.source_configuration_id == "voice-old"
    assert plan_voice_switch({"voice_architecture": "broken"}, SIMPLE, environ={}) is None


async def test_post_settings_still_requests_the_switch_through_the_shared_rule(control):
    async with TestClient(TestServer(control._app)) as client:
        view = await (await client.get("/api/settings")).json()
        profiles = {p["id"]: p for p in view["voice"]["architecture"]["architectures"]}
        response = await client.post("/api/settings", json={"voice": {"architecture": profiles["duplex"]["defaults"]}})
        assert response.status == 200, await response.text()
    request = json.loads((control.runtime_root / REQUEST_FILE).read_text(encoding="utf-8"))
    assert request["target_architecture"] == "duplex"
    assert "voice.switch.requested" in kinds(control)

