"""Integration step (jarvis-memory-intelligence-knowledge): Slice 09 wiring and Slice 04 consolidator injection."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from jarvis.domain.memory import (
    Candidate, CandidateState, MemoryKind, MemoryLevel, Provenance, RetentionClass, SourceType,
)
from jarvis.core.loadout_resolver import KnowledgeLoadoutResolver
from jarvis.core.memory_maintenance import MemoryMaintenanceWorker
from jarvis.runtime.knowledge_wiring import wire_knowledge
from jarvis.runtime.loadout_snapshot import snapshot_path
from jarvis.runtime.memory_composition import build_consolidation, build_default_memory_wiring
import aiohttp

from jarvis.domain.v2 import PROTOCOL_VERSION
from tests.unit.test_memory_routes import CoreOverHttp as _Http


class CoreOverHttp(_Http):
    async def post(self, path: str, payload: dict) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {self.token}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION)}
        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://127.0.0.1:{self.port}{path}", headers=headers, json=payload) as response:
                return response.status, await response.json()

T0 = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def make_wiring(tmp_path, clock=None):
    return build_default_memory_wiring(tmp_path / "data", tmp_path / "settings.json", clock=clock)


# ------------------------------------------------------------------ Slice 09 wiring
async def test_wire_knowledge_installs_the_resolver_the_providers_and_the_first_snapshot(tmp_path):
    wiring = make_wiring(tmp_path)
    runtime = tmp_path / "runtime"
    keeper = wire_knowledge(wiring, tmp_path / "data", runtime)
    assert keeper is not None
    assert isinstance(wiring.service.loadouts, KnowledgeLoadoutResolver)
    assert snapshot_path(runtime).is_file()
    payload = json.loads(snapshot_path(runtime).read_text(encoding="utf-8"))
    assert "brain" in payload["loadouts"] and "code:reviewer" in payload["loadouts"]
    legs = wiring.service.status()
    assert "knowledge:wiki" in legs and "knowledge:skill" in legs
    assert keeper in wiring.lifecycle
    assert keeper.refresh() is False  # nothing changed: no rewrite


async def test_the_snapshot_is_rewritten_when_the_loadout_rules_change(tmp_path):
    clock = Clock()
    wiring = make_wiring(tmp_path, clock)
    runtime = tmp_path / "runtime"
    keeper = wire_knowledge(wiring, tmp_path / "data", runtime, project_id="jarvis")
    before = snapshot_path(runtime).read_text(encoding="utf-8")
    rule = {"memory_scopes": ["shared"], "skills": False}
    (tmp_path / "settings.json").write_text(json.dumps({"memory": {"loadouts": {"code": rule}}}), encoding="utf-8")
    clock.now += 60
    assert keeper.refresh() is True
    after = json.loads(snapshot_path(runtime).read_text(encoding="utf-8"))
    assert after["loadouts"]["code"]["view"]["memory_scopes"] == ["shared"]
    assert snapshot_path(runtime).read_text(encoding="utf-8") != before


async def test_the_keeper_polls_in_the_background_and_stops_with_the_wiring(tmp_path):
    clock = Clock()
    wiring = make_wiring(tmp_path, clock)
    runtime = tmp_path / "runtime"
    keeper = wire_knowledge(wiring, tmp_path / "data", runtime, poll_s=0.05)
    await wiring.start()
    try:
        (tmp_path / "settings.json").write_text(
            json.dumps({"memory": {"loadouts": {"fast": {"memory_scopes": ["shared", "project:zz"]}}}}), encoding="utf-8")
        clock.now += 60
        seen: list[str] = []
        for _ in range(100):
            await asyncio.sleep(0.05)
            seen = json.loads(snapshot_path(runtime).read_text(encoding="utf-8"))["loadouts"]["fast"]["view"]["memory_scopes"]
            if "project:zz" in seen:
                break
        assert "project:zz" in seen
    finally:
        await wiring.stop()
    assert keeper._task is None


async def test_wire_knowledge_without_memory_does_nothing(tmp_path):
    from jarvis.core.memory_wiring import MemoryWiring

    assert wire_knowledge(MemoryWiring.absent(), tmp_path, tmp_path / "runtime") is None


# ------------------------------------------------------------------ Slice 04 injection
class NoModel:
    async def complete(self, system, prompt, *, timeout_s):  # pragma: no cover - never called by these tests
        raise AssertionError("the extractor must not run")


def candidate(candidate_id="cand1") -> Candidate:
    return Candidate(
        id=candidate_id, title="Préférence café", body="Clarice boit son café noir.", level=MemoryLevel.L1,
        kind=MemoryKind.PREFERENCE, retention=RetentionClass.LONG_TERM, scope="shared", confidence=0.8,
        evidence_hash="h" * 16, created_at=T0, sources=(Provenance(SourceType.NOTE, "n1", T0),))


async def test_build_consolidation_installs_the_pipeline_and_the_worker_uses_it(tmp_path):
    wiring = make_wiring(tmp_path)
    pipeline = build_consolidation(wiring, tmp_path / "data" / "memory", agent_execution=lambda: None,
                                   control_settings=dict, model_factory=NoModel)
    assert wiring.consolidation is pipeline
    worker = MemoryMaintenanceWorker(tmp_path / "data" / "memory", wiring.store, pipeline)
    result = await worker.execute(None)
    assert "consolidation" in result and "error" not in result["consolidation"]  # no short-term evidence: no model call


async def test_candidate_routes_list_get_and_decide(tmp_path):
    wiring = make_wiring(tmp_path)
    while not wiring.store.index_ready:
        await asyncio.sleep(0.01)
    pipeline = build_consolidation(wiring, tmp_path / "data" / "memory", agent_execution=lambda: None,
                                   control_settings=dict, model_factory=NoModel)
    pipeline._cands.save(candidate("cand1"))
    pipeline._cands.save(candidate("cand2"))
    async with CoreOverHttp(tmp_path, wiring) as http:
        status, body = await http.get("/v1/memory/candidates")
        assert status == 200 and body["available"] is True
        assert {c["id"] for c in body["candidates"]} == {"cand1", "cand2"}
        assert "body" not in body["candidates"][0]
        status, body = await http.get("/v1/memory/candidates/cand1")
        assert status == 200 and body["candidate"]["body"] == "Clarice boit son café noir."
        assert (await http.get("/v1/memory/candidates/nope"))[0] == 404
        assert (await http.get("/v1/memory/candidates/bad..id"))[0] == 400
        assert (await http.get("/v1/memory/candidates", state="bogus"))[0] == 400

        status, body = await http.post("/v1/memory/candidates/cand1/decision", {"decision": "accept"})
        assert status == 200 and body["candidate"]["state"] == "accepted"
        committed = body["candidate"]["committed_memory_id"]
        assert committed and wiring.store.get(committed).title == "Préférence café"
        assert (await http.post("/v1/memory/candidates/cand1/decision", {"decision": "accept"}))[0] == 200  # retry harmless
        assert (await http.post("/v1/memory/candidates/cand1/decision", {"decision": "reject"}))[0] == 409
        assert (await http.post("/v1/memory/candidates/cand2/decision", {"decision": "reject", "actor": "system.consolidation"}))[0] == 403
        assert (await http.post("/v1/memory/candidates/cand2/decision", {"decision": "maybe"}))[0] == 400
        status, body = await http.post("/v1/memory/candidates/cand2/decision", {"decision": "reject"})
        assert status == 200 and body["candidate"]["state"] == CandidateState.REJECTED.value
        status, body = await http.get("/v1/memory/candidates", state="proposed")
        assert body["candidates"] == []


async def test_candidate_routes_without_a_pipeline_stay_empty_and_decisions_are_unavailable(tmp_path):
    wiring = make_wiring(tmp_path)
    async with CoreOverHttp(tmp_path, wiring) as http:
        status, body = await http.get("/v1/memory/candidates")
        assert status == 200 and body == {"candidates": [], "available": False}
        assert (await http.post("/v1/memory/candidates/cand1/decision", {"decision": "accept"}))[0] == 503
