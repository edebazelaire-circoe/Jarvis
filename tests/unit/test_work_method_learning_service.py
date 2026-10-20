"""Candidats et promotion de Work Method sur une base temporaire : magasin v11, service Core, routes (Slice 12).

Bases temporaires (`tmp_path`) seulement : jamais une base réelle. Les routes sont servies par aiohttp sur la
vraie classe de routes (`WorkMethodProtocolRoutes`), sans le middleware de jeton, et le Control Center est la
vraie application (`ControlCenter`) avec une vue Core simulée.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.adapters.sqlite_work_methods import SQLiteWorkMethodRepository
from jarvis.core.work_method_learning import (
    CANDIDATES_READ_KIND, PROMOTED_KIND, PROMOTION_REFUSED_KIND, WorkMethodLearningService,
)
from jarvis.domain.agent_relations import RelationOutcome as O
from jarvis.domain.work_methods import MethodError, MethodOrigin
from jarvis.protocol.work_method_routes import WorkMethodProtocolRoutes
from jarvis.runtime.control_center import ControlCenter
from tests.fakes.mission_history import at, instance, mission, open_store
from tests.fakes.work_methods import declared as _fact, record_mission


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


@pytest.fixture
async def learning(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    journal = Journal()
    service = WorkMethodLearningService(store, SQLiteWorkMethodRepository(state), diagnostics=journal, clock=Clock())
    yield SimpleNamespace(state=state, store=store, service=service, journal=journal, path=tmp_path / "jarvis.sqlite3")
    await state.close()


async def _eligible(learning):
    for n, minute in enumerate((0, 10, 20)):
        await record_mission(learning.store, f"m{n}", minute=minute)
    reading = await learning.service.candidates()
    return reading, next(c for c in reading.candidates if c.status.value == "candidate")


# ------------------------------------------------------------------ service et magasin


async def test_candidates_are_read_from_real_history_rows(learning):
    reading, candidate = await _eligible(learning)
    assert candidate.signature.relation_kinds == ("delegation", "adversary", "qa")
    assert (candidate.uses, candidate.positive) == (3, 3)
    assert reading.report.to_payload() == {"root_missions": 3, "missions": 3, "uses": 3, "skipped": {},
                                           "truncated": False, "partial": False}
    assert learning.journal.kinds(CANDIDATES_READ_KIND)[-1]["eligible"] == 1


async def test_reading_candidates_never_writes(learning):
    await _eligible(learning)
    await learning.service.candidates()
    assert await SQLiteWorkMethodRepository(learning.state).promoted_methods() == ()


async def test_a_promotion_is_stored_append_only_and_shown_in_the_catalogue(learning):
    _, candidate = await _eligible(learning)
    method = await learning.service.promote(candidate.candidate_id, candidate.draft, expected_version=1,
                                            promoted_by="user")
    assert method.key == "deep-research@2" and method.provenance.origin is MethodOrigin.PROMOTED
    stored = await SQLiteWorkMethodRepository(learning.state).promoted_methods()
    assert stored == (method,)
    catalogue = await learning.service.catalogue()
    assert catalogue["latest"]["deep-research"] == "deep-research@2"
    assert {m["method_id"] + "@" + str(m["version"]) for m in catalogue["methods"]} >= {"deep-research@1",
                                                                                        "deep-research@2"}
    assert learning.journal.kinds(PROMOTED_KIND)[-1]["method"] == "deep-research@2"
    # Relu : le candidat est promu, et ne se promeut pas deux fois.
    again = next(c for c in (await learning.service.candidates()).candidates
                 if c.candidate_id == candidate.candidate_id)
    assert again.status.value == "promoted"
    with pytest.raises(MethodError) as caught:
        await learning.service.promote(candidate.candidate_id, {**candidate.draft, "version": 3}, expected_version=2,
                                       promoted_by="user")
    assert caught.value.code == "work_method_candidate_not_eligible"
    assert learning.journal.kinds(PROMOTION_REFUSED_KIND)[-1]["code"] == "work_method_candidate_not_eligible"
    # Ni réécriture ni suppression, même en SQL direct.
    conn = sqlite3.connect(learning.path)
    try:
        for statement in ("UPDATE work_method_versions SET data = '{}'", "DELETE FROM work_method_versions"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(statement)
    finally:
        conn.close()


async def test_a_second_content_for_one_version_is_refused_by_the_store(learning):
    _, candidate = await _eligible(learning)
    method = await learning.service.promote(candidate.candidate_id, candidate.draft, expected_version=1,
                                            promoted_by="user")
    with pytest.raises(MethodError) as caught:
        await SQLiteWorkMethodRepository(learning.state).publish(method)
    assert caught.value.code == "work_method_version_conflict"


async def test_a_stale_view_is_a_revision_conflict(learning):
    _, candidate = await _eligible(learning)
    with pytest.raises(MethodError) as caught:
        await learning.service.promote(candidate.candidate_id, candidate.draft, expected_version=0,
                                       promoted_by="user")
    assert caught.value.code == "work_method_revision_conflict"
    assert await SQLiteWorkMethodRepository(learning.state).promoted_methods() == ()


async def test_poor_outcomes_and_unknown_candidates_are_refused(learning):
    for n, (minute, qa) in enumerate(((0, O.APPROVED), (10, O.REJECTED), (20, O.REJECTED))):
        await record_mission(learning.store, f"m{n}", minute=minute, qa=qa)
    reading = await learning.service.candidates()
    poor = reading.candidates[0]
    assert poor.status.value == "insufficient_quality"
    for candidate_id, code in ((poor.candidate_id, "work_method_candidate_not_eligible"),
                               ("wmc-0000000000000000", "work_method_candidate_unknown")):
        with pytest.raises(MethodError) as caught:
            await learning.service.promote(candidate_id, {"method_id": "deep-research"}, expected_version=1,
                                           promoted_by="user")
        assert caught.value.code == code


async def test_an_open_mission_is_not_evidence(learning):
    owner = instance("oopen", role="research-lead", mission="mopen", owner=True)
    await learning.store.record_instance(owner, declaration=_fact(owner, "deep-research@1"),
                                         mission=mission("mopen", owner.instance_id))
    reading = await learning.service.candidates()
    assert reading.candidates == () and reading.report.skipped == {"mission_open": 1}


# ------------------------------------------------------------------ route Core


@pytest.fixture
async def core_client(learning):
    app = web.Application()
    app.add_routes(WorkMethodProtocolRoutes(SimpleNamespace(work_method_learning=learning.service,
                                                            _diagnostics=learning.journal)).routes())
    client = TestClient(TestServer(app))
    await client.start_server()
    yield client
    await client.close()


async def test_the_core_routes_read_and_promote(learning, core_client):
    await _eligible(learning)
    response = await core_client.get("/v1/work-methods/candidates")
    assert response.status == 200
    body = await response.json()
    assert body["thresholds"]["min_uses"] == 3 and body["scan"]["uses"] == 3
    candidate = next(c for c in body["candidates"] if c["status"] == "candidate")
    good = {"candidate_id": candidate["candidate_id"], "expected_version": 1, "method": candidate["draft"]}
    refusals = [
        # N3 : le promoteur n'est jamais lu du corps ; le nommer est une enveloppe hors contrat.
        ({**good, "promoted_by": "user"}, 400, "invalid_request"),
        ({**good, "promoted_by": "qa"}, 400, "invalid_request"),
        # N5 : la promotion publie la méthode de base du candidat, rien d'autre.
        ({**good, "method": {**candidate["draft"], "method_id": "quick-research"}}, 422,
         "work_method_not_candidate_base"),
        ({**good, "expected_version": 0}, 409, "work_method_revision_conflict"),
        ({**good, "method": {**candidate["draft"], "steps": ["a", "b"]}}, 422, "work_method_is_not_a_plan"),
        ({**good, "candidate_id": "wmc-ffffffffffffffff"}, 404, "work_method_candidate_unknown"),
        ({**good, "extra": 1}, 400, "invalid_request"),
        ({**good, "expected_version": "1"}, 400, "invalid_request"),
    ]
    for payload, status, code in refusals:
        response = await core_client.post("/v1/work-methods/promotions", json=payload)
        assert response.status == status, (payload, await response.text())
        assert (await response.json())["error"]["code"] == code
    response = await core_client.post("/v1/work-methods/promotions", json=good)
    assert response.status == 200
    assert (await response.json())["method"]["provenance"]["promoted_by"] == "user"
    response = await core_client.post("/v1/work-methods/promotions", json=good)
    assert response.status == 422  # promu : plus éligible
    catalogue = await (await core_client.get("/v1/work-methods")).json()
    assert catalogue["latest"]["deep-research"] == "deep-research@2"
    assert (await core_client.get("/v1/work-methods?x=1")).status == 400
    failed = learning.journal.kinds("core.work_methods.route_failed")
    assert {item["code"] for item in failed} >= {"work_method_not_candidate_base", "invalid_request"}


# ------------------------------------------------------------------ Control Center


class FakeView:
    def __init__(self) -> None:
        self.promotions: list[dict] = []

    async def work_method_candidates(self):
        return 200, {"candidates": [], "scan": {}, "thresholds": {}}

    async def work_methods(self):
        return 200, {"methods": [], "latest": {}}

    async def promote_work_method(self, body):
        self.promotions.append(body)
        return 200, {"method": {"method_id": "deep-research", "version": 2}}

    async def close(self):
        return None


@pytest.fixture
async def center(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    view = FakeView()
    control = ControlCenter(runtime_root=runtime, project_root=tmp_path, mission_view=view)
    client = TestClient(TestServer(control._app))
    await client.start_server()
    yield client, view, runtime
    await client.close()


def _trace(runtime) -> list[dict]:
    path = runtime / "trace.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


async def test_the_control_center_promotes_for_the_user_only_from_its_page(center):
    client, view, runtime = center
    body = {"candidate_id": "wmc-0123456789abcdef", "expected_version": 1, "method": {"method_id": "x"}}
    origin = f"http://{client.host}:{client.port}"
    # Sans les en-têtes d'une page de même origine (un outil, un script) : refusé, rien ne part vers Core.
    response = await client.post("/api/work-methods/promotions", json=body)
    assert response.status == 403 and (await response.json())["code"] == "promotion_requires_browser"
    assert view.promotions == []
    page = {"Origin": origin, "Sec-Fetch-Site": "same-origin"}
    # Le promoteur n'est jamais lu du corps.
    response = await client.post("/api/work-methods/promotions", json={**body, "promoted_by": "qa"}, headers=page)
    assert response.status == 400 and view.promotions == []
    response = await client.post("/api/work-methods/promotions", json=body, headers=page)
    assert response.status == 200 and (await response.json())["ok"] is True
    assert view.promotions == [body]  # le promoteur est posé par Core, jamais par la page ni le relais
    # Une autre origine locale est refusée par la garde du préfixe.
    response = await client.post("/api/work-methods/promotions", json=body,
                                 headers={"Origin": "http://127.0.0.1:1", "Sec-Fetch-Site": "same-origin"})
    assert response.status == 403
    kinds = [line.get("kind") for line in _trace(runtime)]
    assert "work_methods.promotion_failed" in kinds and "work_methods.promotion_done" in kinds
    assert (await client.get("/api/work-methods/candidates")).status == 200
    assert (await client.get("/api/work-methods")).status == 200
