"""Arrêt d'une étoile `job` depuis la scène (handoff jarvis-constellation-scene-runtime, Slice 08).

Chaîne réelle : Control Center (`POST /api/jobs/cancel`, garde d'origine) →
`CoreSceneView.cancel_work` → `CoreSceneTransport` → Core
(`POST /v1/work/cancel`, jeton) → `JobService.cancel_for_user` → job annulé →
projection runtime → étoile `cancelled`.

Ce qui doit tenir :

- seuls les jobs Core s'arrêtent : toute autre source (sous-agent Claude) est
  refusée 409 `not_cancellable`, par Core comme par le Control Center (qui
  n'appelle alors pas Core) ;
- jeton exigé (401), corps strict (400), job inconnu ou spéculatif (404) ;
- un job en cours est annulé, Core le dit (`cancelled`), l'étoile le reflète ;
  redemander rend `already_terminal` sans rien toucher ;
- origine étrangère refusée (403), Core injoignable dit tel quel (503).
"""

from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.core.scene_projector import star_object_id
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.core.v2_services import JOB_USER_CANCEL_KIND
from jarvis.domain.scene import ExecState
from jarvis.domain.v2 import Job, JobStatus, PROTOCOL_VERSION
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.scene_view import CORE_UNREACHABLE, NOT_CANCELLABLE, CoreSceneTransport, CoreSceneView
from tests.integration.test_scene_transport import CoreProcess
from tests.unit.test_scene_service import RecordingDiagnostics


class BlockingWorker:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    async def execute(self, job):
        await asyncio.Event().wait()
        return {}

    async def cancel(self, job_id):
        self.cancelled.append(job_id)


class JobCore(CoreProcess):
    """`CoreProcess` avec un worker `demo` qui ne finit jamais seul."""

    def __init__(self, tmp_path) -> None:  # noqa: ANN001
        super().__init__(tmp_path)
        self.worker = BlockingWorker()
        self.diagnostics = RecordingDiagnostics()

    async def start(self) -> JarvisCoreApplication:
        self.generation += 1
        self.token = f"{self.generation}" * 48
        self.token_file.write_text(self.token, encoding="utf-8")
        self.core = JarvisCoreApplication(data_root=self.data_root, workers={"demo": self.worker}, diagnostics=self.diagnostics)
        await self.core.start()
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=self.port, token=self.token)
        await self.server.start()
        return self.core


async def star_state(core: JarvisCoreApplication, object_id: str, state: ExecState) -> None:
    async def reached() -> None:
        while True:
            item = (await core.scene.snapshot()).get_object(object_id)
            if item is not None and item.exec_state is state:
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(reached(), 5)


@pytest.fixture
async def jobs(tmp_path):
    process = JobCore(tmp_path)
    await process.start()
    try:
        yield process
    finally:
        await process.stop()


def cancel_body(external_id: str, source: str = "job") -> dict:
    return {"schema_version": 1, "source": source, "external_id": external_id}


async def running_job(process: JobCore) -> Job:
    job = await process.core.jobs.submit(Job(kind="demo", payload={}))
    await star_state(process.core, star_object_id("job", job.id), ExecState.RUNNING)
    return job


# ------------------------------------------------------------ Core


async def test_core_cancels_a_running_job_star_and_the_star_becomes_cancelled(jobs):
    job = await running_job(jobs)

    status, body, _ = await jobs.request("POST", "/v1/work/cancel", json=cancel_body(job.id))

    assert status == 200, body
    assert body == {"source": "job", "external_id": job.id, "outcome": "cancelled", "status": "cancelled"}
    assert (await jobs.core.state.get_job(job.id)).status is JobStatus.CANCELLED
    await star_state(jobs.core, star_object_id("job", job.id), ExecState.CANCELLED)
    assert jobs.diagnostics.kinds(JOB_USER_CANCEL_KIND) == [
        ("info", {"job_id": job.id, "kind": "demo", "outcome": "cancelled", "status": "cancelled"})
    ]

    again_status, again, _ = await jobs.request("POST", "/v1/work/cancel", json=cancel_body(job.id))
    assert again_status == 200 and again["outcome"] == "already_terminal" and again["status"] == "cancelled"


async def test_core_never_stops_a_claude_sub_agent_and_needs_its_token(jobs):
    job = await running_job(jobs)
    claude, claude_body, _ = await jobs.request("POST", "/v1/work/cancel", json=cancel_body("toolu_01", source="claude"))
    unauthorized, _, _ = await jobs.request(
        "POST", "/v1/work/cancel", json=cancel_body(job.id), headers={"X-Jarvis-Protocol": str(PROTOCOL_VERSION)},
    )
    unknown, unknown_body, _ = await jobs.request("POST", "/v1/work/cancel", json=cancel_body("no-such-job"))

    assert claude == 409 and claude_body["error"]["code"] == "not_cancellable"
    assert unauthorized == 401
    assert unknown == 404 and unknown_body["error"]["code"] == "not_found"
    assert (await jobs.core.state.get_job(job.id)).status is JobStatus.RUNNING


@pytest.mark.parametrize(
    "raw",
    [
        b"nope",
        b"[]",
        b'{"schema_version": 1, "source": "job"}',
        b'{"schema_version": 2, "source": "job", "external_id": "x"}',
        b'{"schema_version": 1, "source": "job", "external_id": "x", "extra": 1}',
        b'{"schema_version": 1, "source": "job", "external_id": "x", "external_id": "y"}',
        b'{"schema_version": 1, "source": 3, "external_id": "x"}',
        b'{"schema_version": 1, "source": "job", "external_id": " x"}',
        b'{"schema_version": true, "source": "job", "external_id": "x"}',
    ],
)
async def test_core_refuses_malformed_cancel_bodies_without_touching_jobs(jobs, raw):
    job = await running_job(jobs)
    status, body, text = await jobs.request("POST", "/v1/work/cancel", data=raw, headers={**jobs.headers(), "Content-Type": "application/json"})
    assert status == 400 and body["error"]["code"] == "invalid_request" and "Traceback" not in text
    assert (await jobs.core.state.get_job(job.id)).status is JobStatus.RUNNING


async def test_a_speculative_back_brain_job_is_not_a_star_and_cannot_be_found(jobs):
    speculative = Job(kind="demo", payload={"scope": "speculative_analysis"})
    await jobs.core.state.save_job(speculative)
    status, body, _ = await jobs.request("POST", "/v1/work/cancel", json=cancel_body(speculative.id))
    assert status == 404 and body["error"]["code"] == "not_found"


# ------------------------------------------------------------ Control Center


@pytest.fixture
async def center(jobs, tmp_path):
    view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=jobs.port, token_file=jobs.token_file))
    control = ControlCenter(runtime_root=tmp_path / "cc", project_root=tmp_path, scene_view=view)
    view.journal = control.journal
    client = TestClient(TestServer(control._app))
    await client.start_server()
    try:
        yield jobs, client, tmp_path / "cc"
    finally:
        await client.close()
        await view.aclose()


async def test_the_control_center_relays_a_job_stop_and_journals_it(center):
    process, client, runtime = center
    job = await running_job(process)

    response = await client.post("/api/jobs/cancel", json={"source": "job", "external_id": job.id})
    body = await response.json()

    assert response.status == 200, body
    assert body["outcome"] == "cancelled" and body["status"] == "cancelled" and body["error"] is None
    await star_state(process.core, star_object_id("job", job.id), ExecState.CANCELLED)
    assert '"scene.work_cancel"' in (runtime / "trace.jsonl").read_text(encoding="utf-8")


async def test_the_control_center_refuses_claude_stars_origin_and_shape_before_core(center):
    process, client, _ = center
    job = await running_job(process)

    claude = await client.post("/api/jobs/cancel", json={"source": "claude", "external_id": "toolu_01"})
    foreign = await client.post("/api/jobs/cancel", json={"source": "job", "external_id": job.id}, headers={"Origin": "http://evil.example"})
    extra = await client.post("/api/jobs/cancel", json={"source": "job", "external_id": job.id, "actor": "brain"})
    garbage = await client.post("/api/jobs/cancel", data=b"{nope")
    oversize = await client.post("/api/jobs/cancel", data=b"{" + b" " * 5000 + b"}")
    query = await client.post("/api/jobs/cancel?x=1", json={"source": "job", "external_id": job.id})
    get = await client.get("/api/jobs/cancel")

    assert claude.status == 409 and (await claude.json())["error"]["code"] == NOT_CANCELLABLE
    assert foreign.status == 403
    assert extra.status == 400 and garbage.status == 400 and query.status == 400
    assert oversize.status == 413
    assert get.status == 405
    assert (await process.core.state.get_job(job.id)).status is JobStatus.RUNNING
    assert process.diagnostics.kinds(JOB_USER_CANCEL_KIND) == []


async def test_the_control_center_relays_unknown_jobs_and_says_when_core_is_down(center):
    process, client, _ = center
    unknown = await client.post("/api/jobs/cancel", json={"source": "job", "external_id": "no-such-job"})
    await process.stop()
    down = await client.post("/api/jobs/cancel", json={"source": "job", "external_id": "any"})

    assert unknown.status == 404 and (await unknown.json())["error"]["code"] == "not_found"
    down_body = await down.json()
    assert down.status == 503 and down_body["error"]["code"] == CORE_UNREACHABLE and down_body["core_reachable"] is False


async def test_without_a_scene_view_the_stop_route_says_it_is_not_configured(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    async with TestClient(TestServer(control._app)) as client:
        response = await client.post("/api/jobs/cancel", json={"source": "job", "external_id": "x"})
        assert response.status == 503 and (await response.json())["error"]["code"] == "not_configured"


class ScriptedCancel:
    def __init__(self, result) -> None:  # noqa: ANN001
        self.result = result
        self.calls: list[dict] = []

    async def work_cancel(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    async def close(self) -> None:
        return None


@pytest.mark.parametrize(
    ("result", "status", "code"),
    [
        ({"source": "job", "external_id": "other", "outcome": "cancelled", "status": "cancelled"}, 502, "invalid_scene_response"),
        ({"source": "job", "external_id": "j1", "outcome": "stopped?", "status": "cancelled"}, 502, "invalid_scene_response"),
        (__import__("aiohttp").ConnectionTimeoutError(), 503, "command_not_sent"),
        (TimeoutError(), 504, "core_timeout"),
    ],
)
async def test_the_stop_relay_classifies_bad_answers_and_link_failures(result, status, code):
    from tests.unit.test_scene_view import Journal

    journal = Journal()
    view = CoreSceneView(ScriptedCancel(result), journal=journal)
    got_status, body = await view.cancel_work("job", "j1")
    assert (got_status, body["error"]["code"]) == (status, code)
    assert ("scene.work_cancel_failed", "warning") in journal.kinds()


async def test_the_stop_relay_never_calls_core_for_a_claude_star():
    transport = ScriptedCancel({"source": "claude", "external_id": "t", "outcome": "cancelled", "status": "cancelled"})
    status, body = await CoreSceneView(transport).cancel_work("claude", "t")
    assert status == 409 and body["error"]["code"] == NOT_CANCELLABLE and transport.calls == []
