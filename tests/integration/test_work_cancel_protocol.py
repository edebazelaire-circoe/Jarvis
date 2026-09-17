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


# ------------------------------------------------------------ arrêts concurrents (reprise QA, MAJOR-1)


class CountingWorker(BlockingWorker):
    def __init__(self) -> None:
        super().__init__()
        self.executed: list[str] = []

    async def execute(self, job):
        self.executed.append(job.id)
        return await super().execute(job)


async def settled_cancelled(process: JobCore, job_id: str) -> None:
    assert (await process.core.state.get_job(job_id)).status is JobStatus.CANCELLED
    await star_state(process.core, star_object_id("job", job_id), ExecState.CANCELLED)
    assert job_id not in process.core.jobs._running
    assert job_id not in process.core.jobs._cancel_requested and job_id not in process.core.jobs._started


async def test_two_concurrent_user_stops_end_cancelled_and_cancel_the_task_once(jobs):
    job = await running_job(jobs)
    task = jobs.core.jobs._running[job.id]
    calls = []
    original = task.cancel
    task.cancel = lambda *args, **kwargs: (calls.append(1), original(*args, **kwargs))[1]  # type: ignore[method-assign]

    results = await asyncio.wait_for(asyncio.gather(jobs.core.jobs.cancel_for_user(job.id), jobs.core.jobs.cancel_for_user(job.id)), 10)

    assert [(outcome, stored.status) for outcome, stored in results] == [("cancelled", JobStatus.CANCELLED)] * 2
    assert len(calls) == 1
    await settled_cancelled(jobs, job.id)


async def test_a_brain_cancel_work_racing_a_user_stop_ends_cancelled(jobs):
    job = await jobs.core.jobs.submit(Job(kind="demo", payload={}), work_id="brain-work-1")
    await star_state(jobs.core, star_object_id("job", job.id), ExecState.RUNNING)

    cancelled, (outcome, stored) = await asyncio.wait_for(
        asyncio.gather(jobs.core.jobs.cancel_work("brain-work-1"), jobs.core.jobs.cancel_for_user(job.id)), 10)

    assert cancelled == (job.id,) and outcome == "cancelled" and stored.status is JobStatus.CANCELLED
    await settled_cancelled(jobs, job.id)


async def test_a_stop_before_the_first_step_never_runs_the_worker_and_ends_cancelled(tmp_path):
    process = JobCore(tmp_path)
    process.worker = CountingWorker()
    await process.start()
    try:
        job = await process.core.jobs.submit(Job(kind="demo", payload={}))
        # Aucune attente : la tâche existe mais n'a pas fait son premier pas.
        # La lecture du job par `cancel_for_user` ne rend pas la main (lecture
        # sans attente), pour que l'arrêt arrive vraiment avant ce premier pas.
        stored_job = job  # l'état écrit par `submit`, lu sans rendre la main
        read = process.core.state.get_job

        instant = [2]  # `cancel_for_user` puis `cancel` lisent le job avant de toucher la tâche

        async def instant_read(job_id):
            if job_id == job.id and instant[0]:
                instant[0] -= 1
                return stored_job
            return await read(job_id)

        process.core.state.get_job = instant_read
        assert job.id not in process.core.jobs._started
        try:
            outcome, stored = await asyncio.wait_for(process.core.jobs.cancel_for_user(job.id), 10)
        finally:
            process.core.state.get_job = read
        assert (outcome, stored.status) == ("cancelled", JobStatus.CANCELLED)
        assert process.worker.executed == []
        await settled_cancelled(process, job.id)
    finally:
        await process.stop()


async def test_a_second_cancel_during_the_cancelled_write_cannot_leave_the_job_running(jobs, monkeypatch):
    job = await running_job(jobs)
    task = jobs.core.jobs._running[job.id]
    writing = asyncio.Event()
    release = asyncio.Event()
    save = jobs.core.state.save_job

    async def slow_save(value):
        if value.id == job.id and value.status is JobStatus.CANCELLED:
            writing.set()
            await release.wait()
        return await save(value)

    monkeypatch.setattr(jobs.core.state, "save_job", slow_save)
    first = asyncio.create_task(jobs.core.jobs.cancel_for_user(job.id, settle_s=5))
    await asyncio.wait_for(writing.wait(), 5)
    task.cancel()  # annulation brute pendant l'écriture (arrêt de Core, autre appelant)
    await asyncio.sleep(0.05)
    release.set()
    outcome, stored = await asyncio.wait_for(first, 10)

    assert (outcome, stored.status) == ("cancelled", JobStatus.CANCELLED)
    await settled_cancelled(jobs, job.id)


async def test_two_concurrent_user_stops_of_an_owned_back_brain_job_end_cancelled(tmp_path):
    from tests.unit.test_back_brain_tasks import ControlledWorker, admitted, submit

    worker = ControlledWorker()
    core = JarvisCoreApplication(data_root=tmp_path, workers={"back_brain": worker})
    await core.start()
    try:
        _, admission = await admitted(core)
        accepted = await submit(core, admission)
        await asyncio.wait_for(worker.started.wait(), 5)
        results = await asyncio.wait_for(
            asyncio.gather(core.jobs.cancel_for_user(accepted.job_id), core.jobs.cancel_for_user(accepted.job_id)), 10)
        assert [(outcome, stored.status) for outcome, stored in results] == [("cancelled", JobStatus.CANCELLED)] * 2
        stored = await core.state.get_job(accepted.job_id)
        assert stored.status is JobStatus.CANCELLED and stored.cancellation == "confirmed"
    finally:
        worker.release.set()
        await core.stop()


async def test_core_refuses_an_oversize_cancel_body_with_413(jobs):
    job = await running_job(jobs)
    status, body, _ = await jobs.request("POST", "/v1/work/cancel", data=b"{" + b" " * 5000 + b"}",
                                         headers={**jobs.headers(), "Content-Type": "application/json"})
    assert status == 413 and body["error"]["code"] == "payload_too_large"
    assert (await jobs.core.state.get_job(job.id)).status is JobStatus.RUNNING


async def test_a_back_brain_cleanup_that_is_not_confirmed_is_reported_as_such(tmp_path):
    from tests.unit.test_back_brain_tasks import ControlledWorker, admitted, submit

    worker = ControlledWorker()
    worker.cleanup_confirmed = False
    core = JarvisCoreApplication(data_root=tmp_path, workers={"back_brain": worker})
    await core.start()
    try:
        _, admission = await admitted(core)
        accepted = await submit(core, admission)
        await asyncio.wait_for(worker.started.wait(), 5)
        outcome, stored = await asyncio.wait_for(core.jobs.cancel_for_user(accepted.job_id), 15)
        assert outcome == "cleanup_unknown" and stored.status is JobStatus.RUNNING and stored.cancellation == "cleanup_unknown"
    finally:
        worker.cleanup_confirmed = True
        worker.release.set()
        await core.stop()


def test_the_only_ui_route_that_affects_work_is_the_job_stop(tmp_path):
    """Liste blanche : l'interface n'écrit jamais l'état de travail (`/api/work` en lecture seule,
    aucune route d'observation ou d'ingestion) ; seul `POST /api/jobs/cancel` agit sur du travail, et
    seulement pour `source = job` (les autres cas sont prouvés plus haut)."""

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    affecting = set()
    for route in control._app.router.routes():
        path = route.resource.canonical
        if any(word in path for word in ("observation", "ingest")):
            affecting.add(("forbidden", path))
        if route.method in {"GET", "HEAD", "OPTIONS"}:
            continue
        if path.startswith("/api/work") or path.startswith("/api/jobs"):
            affecting.add((route.method, path))
    assert affecting == {("POST", "/api/jobs/cancel")}


async def test_the_control_center_omits_the_bulk_archive_patch_but_not_other_patches():
    from jarvis.domain.scene import (
        ExecState as SceneExec, SceneActor, SceneCommand, SceneObjectFields, SceneObjectKind, SceneOp, SceneSnapshot,
        WorkRef, apply_scene_command,
    )

    snapshot = SceneSnapshot(scene_id="s")
    for index in range(3):
        snapshot = apply_scene_command(snapshot, SceneCommand(
            op=SceneOp.UPSERT_OBJECT, actor=SceneActor.RUNTIME, object_id=f"claude:{index}",
            fields=SceneObjectFields(kind=SceneObjectKind.AGENT, category="agent", exec_state=SceneExec.COMPLETED,
                                     work_ref=WorkRef("claude", str(index))))).snapshot
    command = SceneCommand(op=SceneOp.ARCHIVE_MANY, actor=SceneActor.USER, object_ids=("claude:0", "claude:1"))
    update = apply_scene_command(snapshot, command)

    class Transport:
        async def scene_command(self, payload, **kwargs):
            return {"outcome": "applied", "reason": None, "scene_id": "s", "epoch": "e", "revision": update.snapshot.revision,
                    "patch": update.patch.to_payload()}

        async def close(self):
            return None

    status, body = await CoreSceneView(Transport()).command(command)
    assert status == 200 and body["outcome"] == "applied" and body["revision"] == update.snapshot.revision
    assert body["patch"] is None and body["patch_omitted"] is True
    single = SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id="claude:2")
    one = apply_scene_command(snapshot, single)

    class Single(Transport):
        async def scene_command(self, payload, **kwargs):
            return {"outcome": "applied", "reason": None, "scene_id": "s", "epoch": "e", "revision": one.snapshot.revision,
                    "patch": one.patch.to_payload()}

    _, single_body = await CoreSceneView(Single()).command(single)
    assert single_body["patch"] == one.patch.to_payload() and "patch_omitted" not in single_body


async def test_the_status_gives_the_page_the_real_stop_deadline(tmp_path):
    import json as _json

    bare = ControlCenter(runtime_root=tmp_path / "bare", project_root=tmp_path)
    assert _json.loads((await bare.status(None)).text)["scene_limits"] == {"job_cancel_timeout_s": None}
    view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=1, token_file=tmp_path / "none.token"), command_connect_timeout_s=2.0)
    wired = ControlCenter(runtime_root=tmp_path / "wired", project_root=tmp_path, scene_view=view)
    try:
        limits = _json.loads((await wired.status(None)).text)["scene_limits"]
        assert limits == {"job_cancel_timeout_s": view.job_cancel_deadline_s} and view.job_cancel_deadline_s == 2.0 + 20.0 + 1.0
    finally:
        await view.aclose()



# ------------------------------------------------------------ arrêt contre fin du worker (reprise QA finale, MAJOR-R1)


class OutcomeWorker:
    """Worker dont la fin est pilotée par le test : `finish(job_id, "ok" | "fail")`."""

    def __init__(self) -> None:
        self.gates: dict[str, list] = {}
        self.started: dict[str, asyncio.Event] = {}

    def _gate(self, job_id):
        return self.gates.setdefault(job_id, [asyncio.Event(), None])

    def finish(self, job_id, mode):
        gate = self._gate(job_id)
        gate[1] = mode
        gate[0].set()

    async def execute(self, job):
        self.started.setdefault(job.id, asyncio.Event()).set()
        gate = self._gate(job.id)
        await gate[0].wait()
        if gate[1] == "fail":
            raise RuntimeError("worker failure")
        return {"ok": True}

    async def cancel(self, job_id):
        return None


async def outcome_core(tmp_path):
    process = JobCore(tmp_path)
    process.worker = OutcomeWorker()
    await process.start()
    writes: dict[str, list[str]] = {}
    save = process.core.state.save_job

    async def recording_save(value):
        writes.setdefault(value.id, []).append(value.status.value)
        return await save(value)

    process.core.state.save_job = recording_save
    events: dict[str, list[str]] = {}
    publish = process.core.events.publish

    async def recording_publish(envelope):
        job_id = envelope.payload.get("job_id") if isinstance(envelope.payload, dict) else None
        if job_id:
            events.setdefault(job_id, []).append(envelope.message_type)
        return await publish(envelope)

    process.core.events.publish = recording_publish
    return process, writes, events


async def started_job(process):
    job = await process.core.jobs.submit(Job(kind="demo", payload={}))
    await asyncio.wait_for(process.worker.started.setdefault(job.id, asyncio.Event()).wait(), 5)
    return job


def terminal_writes(writes, job_id):
    return [value for value in writes.get(job_id, []) if value not in ("pending", "running")]


TERMINAL = {"ok": (JobStatus.COMPLETED, ExecState.COMPLETED, "job.completed"), "fail": (JobStatus.FAILED, ExecState.FAILED, "job.failed")}


@pytest.mark.parametrize("mode", ["ok", "fail"])
@pytest.mark.parametrize("where", ["lock_wait", "after_save", "publish", "observe"])
async def test_a_cancellation_during_the_terminal_settlement_never_overwrites_the_worker_outcome(tmp_path, mode, where):
    process, writes, events = await outcome_core(tmp_path)
    try:
        job = await started_job(process)
        task = process.core.jobs._running[job.id]
        status, exec_state, event_name = TERMINAL[mode]
        reached, release = asyncio.Event(), asyncio.Event()
        save = process.core.state.save_job

        async def hooked_save(value):
            if value.id == job.id and value.status is status and where == "lock_wait":
                holder = process.core.state._lock
                await holder.acquire()  # un autre appelant tient le verrou : l'écriture attendra
                reached.set()

                async def free_lock():
                    await release.wait()
                    holder.release()

                asyncio.get_running_loop().create_task(free_lock())
                return await save(value)
            if value.id == job.id and value.status is status and where == "after_save":
                result = await save(value)
                reached.set()
                await release.wait()
                return result
            return await save(value)

        process.core.state.save_job = hooked_save
        if where == "publish":
            publish = process.core.events.publish

            async def hooked_publish(envelope):
                if envelope.message_type == event_name:
                    reached.set()
                    await release.wait()
                return await publish(envelope)

            process.core.events.publish = hooked_publish
        if where == "observe":
            observe = process.core.jobs._observe_work

            async def hooked_observe(value, work_status, **kwargs):
                if value.id == job.id and work_status.value == status.value:
                    reached.set()
                    await release.wait()
                return await observe(value, work_status, **kwargs)

            process.core.jobs._observe_work = hooked_observe

        process.worker.finish(job.id, mode)
        await asyncio.wait_for(reached.wait(), 5)
        await asyncio.sleep(0.01)
        if where == "lock_wait":
            # Le verrou du dépôt est tenu : `cancel()` (qui relit le job) attendrait lui aussi.
            # L'annulation arrive donc brute, deux fois, pendant l'attente du verrou.
            task.cancel()
            task.cancel()
        else:
            await process.core.jobs.cancel(job.id)  # l'annulation tombe pendant le règlement
            await process.core.jobs.cancel(job.id)  # et une seconde, idempotente
        assert task.cancelling() >= 1
        release.set()
        await asyncio.wait({task}, timeout=5)

        stored = await process.core.state.get_job(job.id)
        assert task.done() and stored.status is status
        assert terminal_writes(writes, job.id) == [status.value]
        assert events.get(job.id, []).count(event_name) == 1 and "job.cancelled" not in events.get(job.id, [])
        await star_state(process.core, star_object_id("job", job.id), exec_state)
        outcome, again = await process.core.jobs.cancel_for_user(job.id)
        assert (outcome, again.status) == ("already_terminal", status)
    finally:
        await process.stop()


@pytest.mark.parametrize("mode", ["ok", "fail"])
async def test_a_user_stop_that_read_running_answers_already_terminal_with_the_real_status(tmp_path, mode):
    process, writes, _ = await outcome_core(tmp_path)
    try:
        job = await started_job(process)
        status = TERMINAL[mode][0]
        read = process.core.state.get_job
        first = [True]

        async def read_then_finish(job_id):
            value = await read(job_id)
            if job_id == job.id and first[0]:
                first[0] = False
                process.worker.finish(job.id, mode)  # le worker rend son issue juste après la lecture « running »
                for _ in range(5):
                    await asyncio.sleep(0)
            return value

        process.core.state.get_job = read_then_finish
        outcome, stored = await asyncio.wait_for(process.core.jobs.cancel_for_user(job.id, settle_s=5), 10)
        process.core.state.get_job = read
        final = await process.core.state.get_job(job.id)
        assert terminal_writes(writes, job.id) == [final.status.value]
        assert final.status is status  # l'issue était rendue : elle gagne
        assert (outcome, stored.status) == ("already_terminal", status)
    finally:
        await process.stop()


@pytest.mark.parametrize("mode", ["ok", "fail"])
async def test_an_unhooked_timing_sweep_of_stop_against_the_worker_end_is_never_stuck_nor_inconsistent(tmp_path, mode):
    process, writes, events = await outcome_core(tmp_path)
    status = TERMINAL[mode][0]
    seen = set()
    try:
        for index in range(24):
            job = await started_job(process)
            stop = asyncio.create_task(process.core.jobs.cancel_for_user(job.id, settle_s=2))
            await asyncio.sleep((index % 6) / 1000)
            process.worker.finish(job.id, mode)
            outcome, stored = await asyncio.wait_for(stop, 10)
            await asyncio.sleep(0.02)
            final = await process.core.state.get_job(job.id)
            assert final.status in (status, JobStatus.CANCELLED), (index, final.status)
            assert terminal_writes(writes, job.id) == [final.status.value], (index, writes.get(job.id))
            assert (outcome, stored.status) == ("already_terminal" if final.status is status else "cancelled", final.status)
            assert events.get(job.id, []).count(TERMINAL[mode][2]) == (1 if final.status is status else 0)
            assert job.id not in process.core.jobs._running
            seen.add(final.status)
    finally:
        await process.stop()
    assert seen  # au moins une issue observée ; les deux selon la machine


@pytest.mark.parametrize("mode", ["ok", "fail"])
async def test_core_stop_during_a_settling_terminal_write_keeps_the_worker_outcome(tmp_path, mode):
    process, writes, _ = await outcome_core(tmp_path)
    status = TERMINAL[mode][0]
    job = await started_job(process)
    reached, release = asyncio.Event(), asyncio.Event()
    save = process.core.state.save_job

    async def slow_terminal_save(value):
        if value.id == job.id and value.status is status:
            reached.set()
            await release.wait()
        return await save(value)

    process.core.state.save_job = slow_terminal_save
    process.worker.finish(job.id, mode)
    await asyncio.wait_for(reached.wait(), 5)
    stopping = asyncio.create_task(process.stop())
    await asyncio.sleep(0.2)
    release.set()
    await asyncio.wait_for(stopping, 20)
    reopened = JarvisCoreApplication(data_root=process.data_root, workers={"demo": OutcomeWorker()})
    await reopened.start()
    try:
        assert (await reopened.state.get_job(job.id)).status is status
    finally:
        await reopened.stop()
    assert terminal_writes(writes, job.id) == [status.value]
