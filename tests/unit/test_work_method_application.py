"""La version promue d'une Work Method est réellement réutilisée (Slice 12, reprise QA N1a, N3, N7).

Chaîne vérifiée en bout : promotion par la vraie route du Control Center (page de même origine), vers le vrai
service Core (base temporaire) par HTTP, instantané `work-methods.json` écrit par le Control Center, puis le vrai
hook (`routing_hook.run`) qui appose `deep-research@2` et dépose le fait `work_method=deep-research@2`. Plus les
replis : instantané absent, illisible, version qui ne s'applique pas au rôle, méthode neuve citée par aucun rôle.
Bases et dossiers temporaires seulement.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.adapters.sqlite_work_methods import SQLiteWorkMethodRepository
from jarvis.core.work_method_learning import HISTORY_UNREADABLE_KIND, WorkMethodLearningService
from jarvis.domain import subagent_roles
from jarvis.domain.work_methods import MethodOrigin, MethodProvenance, WorkMethod, builtin_method
from jarvis.protocol.work_method_routes import WorkMethodProtocolRoutes
from jarvis.runtime import agent_declarations, routing_hook, work_methods_snapshot
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.journal import read_jsonl_tail
from tests.fakes.mission_history import at, open_store
from tests.fakes.work_methods import record_mission


class Journal:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.lines.append((kind, level, dict(data or {})))

    def kinds(self, kind):
        return [data for name, _level, data in self.lines if name == kind]


class Clock:
    def now(self):
        return at(500)


def promoted(version: int = 2, *, role_ids=None, method_id: str = "deep-research") -> WorkMethod:
    base = builtin_method("deep-research")
    return replace(base, method_id=method_id, version=version, role_ids=tuple(role_ids or base.role_ids),
                   useful_relations=("delegation", "adversary", "qa"),
                   provenance=MethodProvenance(origin=MethodOrigin.PROMOTED, candidate_id="wmc-0123456789abcdef",
                                               promoted_by="user", promoted_at=at(400), evidence_refs=("m1",)))


def agent_call(description: str, tool_use_id: str = "toolu_A") -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": tool_use_id, "session_id": "s1",
            "tool_input": {"description": description, "prompt": "Faites-le.", "subagent_type": "general-purpose",
                           "run_in_background": False}}


def run_hook(runtime, description="[general] [research-lead] Comparer", tool_use_id="toolu_A"):
    output = routing_hook.run(agent_call(description, tool_use_id), runtime)
    prompt = (output.get("hookSpecificOutput") or {}).get("updatedInput", {}).get("prompt", "")
    [fact] = [item.fact for item in agent_declarations.scan(runtime).facts if item.fact.tool_use_id == tool_use_id]
    trace = read_jsonl_tail(runtime / "trace.jsonl", limit=500)
    return prompt, fact, trace


# ------------------------------------------------------------------ instantané et hook


def test_the_hook_applies_the_latest_promoted_version_and_declares_it(tmp_path):
    work_methods_snapshot.write_snapshot(tmp_path, [promoted(2), promoted(3)])
    prompt, fact, trace = run_hook(tmp_path)
    assert "(deep-research@3)" in prompt and "(deep-research@1)" not in prompt
    assert "Relations à envisager quand elles servent : délégation, confrontation, contrôle qualité." in prompt
    assert fact.work_method == "deep-research@3" and fact.work_method_chosen is False
    applied = [line for line in trace if line.get("kind") == "agent.role_applied"]
    declared = [line for line in trace if line.get("kind") == "agent.declared"]
    assert applied[-1]["data"]["work_method"] == "deep-research@3"
    assert declared[-1]["data"]["work_method"] == "deep-research@3"


def test_without_a_snapshot_the_builtin_version_applies_silently(tmp_path):
    prompt, fact, trace = run_hook(tmp_path)
    assert "(deep-research@1)" in prompt and fact.work_method == "deep-research@1"
    assert not [line for line in trace if line.get("kind") == "agent.work_method.failed"]


@pytest.mark.parametrize("content", ["{pas du json", json.dumps({"schema": 9, "methods": []}),
                                     json.dumps({"schema": 1, "methods": [{"method_id": "deep-research",
                                                                            "steps": ["a"]}]}),
                                     json.dumps({"schema": 1, "methods": [builtin_method("deep-research")
                                                                           .to_payload()]})])
def test_an_unreadable_snapshot_falls_back_to_the_builtin_version_and_says_so(tmp_path, content):
    work_methods_snapshot.snapshot_path(tmp_path).write_text(content, encoding="utf-8")
    prompt, fact, trace = run_hook(tmp_path)
    assert "(deep-research@1)" in prompt and fact.work_method == "deep-research@1"
    [failed] = [line for line in trace if line.get("kind") == "agent.work_method.failed"]
    assert failed["data"]["code"] == "work_methods_snapshot_failed" and failed["level"] == "warning"


def test_a_promoted_version_that_does_not_apply_to_the_role_is_not_applied(tmp_path):
    work_methods_snapshot.write_snapshot(tmp_path, [promoted(2, role_ids=("research",))])
    prompt, fact, _trace = run_hook(tmp_path)
    assert "(deep-research@1)" in prompt and fact.work_method == "deep-research@1"


def test_a_new_method_cited_by_no_role_is_never_applied(tmp_path):
    work_methods_snapshot.write_snapshot(tmp_path, [promoted(1, method_id="delegated-review",
                                                             role_ids=("research-lead",))])
    prompt, fact, _trace = run_hook(tmp_path)
    assert "delegated-review" not in prompt and fact.work_method == "deep-research@1"
    # Même nommée en tête par l'appelant : une méthode que le rôle ne cite pas n'est jamais apposée.
    prompt, fact, _trace = run_hook(tmp_path, "[general] [research-lead] [delegated-review] Comparer", "toolu_B")
    assert "delegated-review" not in prompt and fact.work_method == "deep-research@1"


def test_effective_method_prefers_the_promoted_version_only_for_cited_roles():
    lead = subagent_roles.role_by_id("research-lead")
    assert subagent_roles.effective_method(lead, "deep-research", {"deep-research": promoted(2)}).key == \
        "deep-research@2"
    assert subagent_roles.effective_method(lead, "deep-research", {}).key == "deep-research@1"
    assert subagent_roles.effective_method(lead, None, {"deep-research": promoted(2)}) is None


# ------------------------------------------------------------------ chaîne complète par les vraies routes


class CoreHttpView:
    """La vue Core du Control Center, branchée par HTTP sur la vraie classe de routes Core (sans jeton)."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    async def _call(self, method, path, body=None):
        response = await self.client.request(method, path, json=body)
        data = await response.json()
        if response.status == 200:
            return 200, data
        return response.status, {"ok": False, "code": data["error"]["code"], "error": data["error"]["message"]}

    async def work_methods(self):
        return await self._call("GET", "/v1/work-methods")

    async def work_method_candidates(self):
        return await self._call("GET", "/v1/work-methods/candidates")

    async def promote_work_method(self, body):
        return await self._call("POST", "/v1/work-methods/promotions", body)

    async def close(self):
        return None


@pytest.fixture
async def chain(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    journal = Journal()
    service = WorkMethodLearningService(store, SQLiteWorkMethodRepository(state), diagnostics=journal, clock=Clock())
    app = web.Application()
    app.add_routes(WorkMethodProtocolRoutes(SimpleNamespace(work_method_learning=service, _diagnostics=journal))
                   .routes())
    core = TestClient(TestServer(app))
    await core.start_server()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    center = ControlCenter(runtime_root=runtime, project_root=tmp_path, mission_view=CoreHttpView(core))
    ui = TestClient(TestServer(center._app))
    await ui.start_server()
    yield SimpleNamespace(store=store, service=service, journal=journal, ui=ui, runtime=runtime,
                          path=tmp_path / "jarvis.sqlite3", center=center)
    await ui.close()
    await core.close()
    await state.close()


async def test_promotion_then_snapshot_then_hook_applies_v2_and_declares_it(chain):
    for n, minute in enumerate((0, 10, 20)):
        await record_mission(chain.store, f"m{n}", minute=minute)
    # Avant toute promotion : la version livrée.
    prompt, fact, _ = run_hook(chain.runtime, tool_use_id="toolu_before")
    assert fact.work_method == "deep-research@1"
    body = await (await chain.ui.get("/api/work-methods/candidates")).json()
    [candidate] = [c for c in body["candidates"] if c["status"] == "candidate"]
    page = {"Origin": f"http://{chain.ui.host}:{chain.ui.port}", "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors"}
    response = await chain.ui.post("/api/work-methods/promotions", headers=page, json={
        "candidate_id": candidate["candidate_id"], "expected_version": 1, "method": candidate["draft"]})
    answer = await response.json()
    assert response.status == 200, answer
    assert answer["method"]["provenance"]["promoted_by"] == "user"
    assert answer["snapshot"] == {"written": True, "code": None}
    assert set(work_methods_snapshot.read_promoted(chain.runtime)) == {"deep-research"}
    # Le vrai hook appose maintenant la version promue, et le fait la porte.
    prompt, fact, _ = run_hook(chain.runtime, tool_use_id="toolu_after")
    assert "(deep-research@2)" in prompt and fact.work_method == "deep-research@2"
    # La route du registre et donc l'onglet montrent la version effective.
    roles = chain.center._subagent_roles_payload({})
    [deep] = [m for m in roles["work_methods"] if m["method_id"] == "deep-research"]
    assert deep["version"] == 2 and deep["provenance"]["origin"] == "promoted"
    assert roles["work_methods_snapshot"] == {"promoted": ["deep-research@2"], "error": None}
    # N3 : le journal garde les faits observables de la demande, sans prétendre prouver un clic.
    trace = read_jsonl_tail(chain.runtime / "trace.jsonl", limit=500)
    [requested] = [line for line in trace if line.get("kind") == "work_methods.promotion_requested"]
    assert requested["data"]["origin"] == page["Origin"] and requested["data"]["sec_fetch_site"] == "same-origin"
    assert requested["data"]["sec_fetch_mode"] == "cors" and "user_agent_present" in requested["data"]
    assert "ne prouvent pas un clic" in requested["message"]
    assert [line for line in trace if line.get("kind") == "work_methods.snapshot_written"]


async def test_a_failed_snapshot_write_is_said_in_the_answer_and_the_journal(chain, monkeypatch):
    for n, minute in enumerate((0, 10, 20)):
        await record_mission(chain.store, f"m{n}", minute=minute)
    body = await (await chain.ui.get("/api/work-methods/candidates")).json()
    [candidate] = [c for c in body["candidates"] if c["status"] == "candidate"]

    def refuse(*_args, **_kwargs):
        raise PermissionError("disque refusé")

    monkeypatch.setattr(work_methods_snapshot, "write_snapshot", refuse)
    page = {"Origin": f"http://{chain.ui.host}:{chain.ui.port}", "Sec-Fetch-Site": "same-origin"}
    response = await chain.ui.post("/api/work-methods/promotions", headers=page, json={
        "candidate_id": candidate["candidate_id"], "expected_version": 1, "method": candidate["draft"]})
    answer = await response.json()
    assert response.status == 200 and answer["snapshot"] == {"written": False, "code": "PermissionError"}
    trace = read_jsonl_tail(chain.runtime / "trace.jsonl", limit=500)
    [failed] = [line for line in trace if line.get("kind") == "work_methods.snapshot_failed"]
    assert failed["level"] == "error" and "disque refusé" in failed["data"]["error"]


async def test_the_control_center_resyncs_the_snapshot_at_start_and_on_read(chain):
    published = promoted(2)
    await SQLiteWorkMethodRepository(chain.store._state).publish(published)
    assert work_methods_snapshot.read_payloads(chain.runtime) is None
    await chain.center._sync_work_methods_at_start()
    assert set(work_methods_snapshot.read_promoted(chain.runtime)) == {"deep-research"}
    work_methods_snapshot.snapshot_path(chain.runtime).unlink()
    assert (await chain.ui.get("/api/work-methods")).status == 200
    assert work_methods_snapshot.read_promoted(chain.runtime)["deep-research"].key == "deep-research@2"


# ------------------------------------------------------------------ N7 : une ligne illisible


async def test_one_unreadable_history_row_drops_its_tree_not_the_whole_reading(chain):
    for n, minute in enumerate((0, 10, 20, 30)):
        await record_mission(chain.store, f"m{n}", minute=minute)
    conn = sqlite3.connect(chain.path)
    try:
        conn.execute("UPDATE agent_instances SET data = json_set(data, '$.label', 123) WHERE instance_id = 'am3'")
        conn.commit()
    finally:
        conn.close()
    reading = await chain.service.candidates()
    assert reading.report.partial is True and reading.report.skipped == {"history_unreadable": 1}
    [candidate] = reading.candidates
    assert candidate.uses == 3 and candidate.status.value == "candidate"
    [diagnostic] = chain.journal.kinds(HISTORY_UNREADABLE_KIND)
    assert diagnostic["root_mission_id"] == "m3" and diagnostic["table"] == "agent_instances"
    body = await (await chain.ui.get("/api/work-methods/candidates")).json()
    assert body["scan"]["partial"] is True


# ------------------------------------------------------------------ reprise QA R-1, R-2 : clé déclarée véridique


def _forge(tmp_path, method):
    work_methods_snapshot.snapshot_path(tmp_path).write_text(
        json.dumps({"schema": 1, "methods": [method.to_payload()]}), encoding="utf-8")


def _assert_builtin_with_warning(tmp_path, expected_code_part):
    prompt, fact, trace = run_hook(tmp_path)
    assert "(deep-research@1)" in prompt and fact.work_method == "deep-research@1"
    # Le texte apposé est bien celui livré, pas celui du fichier forgé.
    assert "Texte forgé" not in prompt
    [failed] = [line for line in trace if line.get("kind") == "agent.work_method.failed"]
    assert failed["level"] == "warning" and failed["data"]["code"] == "work_methods_snapshot_failed"
    with pytest.raises(ValueError) as caught:
        work_methods_snapshot.read_promoted(tmp_path)
    assert expected_code_part in str(caught.value)


def test_a_version_promoted_by_someone_else_than_a_person_is_refused(tmp_path):
    forged = promoted(2)
    forged = replace(forged, principles=("Texte forgé par un agent.",),
                     provenance=replace(forged.provenance, promoted_by="research-lead"))
    _forge(tmp_path, forged)
    _assert_builtin_with_warning(tmp_path, "work_method_promoter_not_human")
    lead = subagent_roles.role_by_id("research-lead")
    assert subagent_roles.effective_method(lead, "deep-research", {"deep-research": forged}).key == "deep-research@1"


def test_a_promoted_version_not_after_the_builtin_one_is_refused(tmp_path):
    forged = replace(promoted(1), principles=("Texte forgé qui se dit @1.",))
    _forge(tmp_path, forged)
    _assert_builtin_with_warning(tmp_path, "work_method_version_not_after_builtin")
    lead = subagent_roles.role_by_id("research-lead")
    effective = subagent_roles.effective_method(lead, "deep-research", {"deep-research": forged})
    assert effective == builtin_method("deep-research")


def test_an_oversized_snapshot_gives_the_builtin_version_and_a_warning(tmp_path, monkeypatch):
    work_methods_snapshot.write_snapshot(tmp_path, [promoted(2)])
    monkeypatch.setattr(work_methods_snapshot, "MAX_SNAPSHOT_BYTES",
                        work_methods_snapshot.snapshot_path(tmp_path).stat().st_size - 1)
    prompt, fact, trace = run_hook(tmp_path)
    assert "(deep-research@1)" in prompt and fact.work_method == "deep-research@1"
    [failed] = [line for line in trace if line.get("kind") == "agent.work_method.failed"]
    assert failed["level"] == "warning" and failed["data"]["exception_type"] == "ValueError"


def test_the_hook_entry_never_journals_into_the_current_directory(tmp_path, monkeypatch):
    import io

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    configured = tmp_path / "configured-runtime"
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(configured))
    event = {"tool_name": "Agent", "tool_input": {"description": "[general] [research-lead] X", "prompt": "Faites."}}
    for argv in ([], ["--runtime-root", ""], ["--runtime-root"]):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
        monkeypatch.setattr("sys.stdout", io.StringIO())
        assert routing_hook.main(argv) == 0
    assert not list(cwd.iterdir()), list(cwd.iterdir())
    assert (configured / "trace.jsonl").exists()
    monkeypatch.delenv("JARVIS_RUNTIME_DIR")
    assert routing_hook.default_runtime_root().name == "runtime"
    assert routing_hook.default_runtime_root() != cwd
