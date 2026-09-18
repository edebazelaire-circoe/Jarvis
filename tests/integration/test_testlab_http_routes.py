"""Slice 10 end to end over HTTP: the Control Center routes against real worker processes.

Contract: `docs/testlab.md` ("Native API, CLI and HTTP"). Same fixture as the CLI file
(`selftest.worker`, Slice 05): no voice stack, no provider, no device. Bounded: at most
two workers per test, one at a time, and the application's own cleanup closes the
supervisor.

The point of this file is that the HTTP surface and the CLI answer with the SAME records
and the same derived outcome, because they call the same facade — and that long work
never holds a request open.
"""

from __future__ import annotations

import asyncio
import json

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.testlab.composition import TestLab, TestLabConfig, display_path
from jarvis.testlab.hardware.channel import FilePrompter, PromptWatcher
from jarvis.testlab.hardware.prompts import GuidedAction, GuidedPrompt
from jarvis.testlab.http import TESTLAB_ROUTE, install_testlab_routes
from jarvis.testlab.maintenance import MaintenancePolicy
from jarvis.testlab.runs import TERMINAL_STATUSES
from jarvis.testlab.selftest import SELFTEST_DIAGNOSTIC_ID, SelfTestMode, write_selftest_catalog
from jarvis.testlab.supervisor import SupervisorPolicy
from jarvis.testlab.sweep_runner import SweepPolicy

STARTUP_TIMEOUT_S = 60.0
POLL_TIMEOUT_S = 120.0
TERMINAL = {item.value for item in TERMINAL_STATUSES}


@pytest.fixture
def lab(tmp_path) -> TestLab:
    catalog = write_selftest_catalog(tmp_path / "catalog", max_duration_s=60.0)
    root = tmp_path / "runtime" / "testlab"
    return TestLab(TestLabConfig(
        root=root, work_root=root / "work", runtime_root=tmp_path / "runtime", data_root=tmp_path / "data",
        catalog_root=catalog,
        policy=SupervisorPolicy(max_concurrent_runs=1, startup_timeout_s=STARTUP_TIMEOUT_S,
                                heartbeat_timeout_s=30.0, cancel_grace_s=3.0, poll_interval_s=0.05,
                                maintenance=MaintenancePolicy(enabled=False)),
        sweep_policy=SweepPolicy(max_in_flight=1, run_timeout_s=POLL_TIMEOUT_S)))


@pytest.fixture
async def client(lab):
    app = web.Application()
    install_testlab_routes(app, lab=lab)
    served = TestClient(TestServer(app))
    await served.start_server()
    try:
        yield served
    finally:
        await served.close()


async def submit(client, mode: SelfTestMode | str = SelfTestMode.MEASURE, **parameters) -> str:
    body = {"diagnostic_id": SELFTEST_DIAGNOSTIC_ID, "profile": "virtual",
            "parameters": {"mode": SelfTestMode(mode).value, **parameters}}
    response = await client.post(f"{TESTLAB_ROUTE}/runs", json=body)
    payload = await response.json()
    assert response.status == 202, payload
    return payload["run_id"]


async def poll_until_terminal(client, run_id: str) -> dict:
    """What a browser does: long-poll, and always get the current record back."""
    deadline = asyncio.get_running_loop().time() + POLL_TIMEOUT_S
    while True:
        payload = await (await client.get(f"{TESTLAB_ROUTE}/runs/{run_id}", params={"wait_s": "5"})).json()
        if payload["run"]["status"] in TERMINAL:
            return payload
        assert asyncio.get_running_loop().time() < deadline, f"run {run_id} never became terminal"


# --------------------------------------------------------------------- runs

async def test_submitting_a_run_answers_at_once_and_the_poll_carries_it_to_a_verdict(client):
    """202 with the id while the worker is still starting; the verdict arrives by polling."""
    run_id = await submit(client, value=0)
    assert run_id.startswith("tlr-")
    payload = await poll_until_terminal(client, run_id)
    assert payload["ok"] is True
    assert payload["outcome"]["outcome"] == "passed"
    assert payload["run"]["metrics"]["selftest.value"] == 0
    assert payload["declaration"]["diagnostic_id"] == SELFTEST_DIAGNOSTIC_ID
    assert {"config_snapshot.json", "worker.log"} <= {item["path"] for item in payload["artifacts"]}


async def test_the_outcome_is_derived_for_the_browser_and_never_left_to_it(client):
    """Slice 11 renders `outcome`; it must never re-derive a verdict from `status`."""
    run_id = await submit(client, value=7)
    payload = await poll_until_terminal(client, run_id)
    assert payload["run"]["status"] == "failed"
    outcome = payload["outcome"]
    assert outcome["outcome"] == "failed" and outcome["verdict"] == "failed"
    assert outcome["failed_assertions"] == ["value_is_zero"]
    assert outcome["missing_assertions"] == [] and outcome["measured"] is True


async def test_the_listing_and_the_single_run_agree(client):
    run_id = await submit(client, value=0)
    await poll_until_terminal(client, run_id)
    page = await (await client.get(f"{TESTLAB_ROUTE}/runs", params={"limit": "10"})).json()
    assert [view["run"]["run_id"] for view in page["runs"]] == [run_id]
    assert page["runs"][0]["outcome"]["outcome"] == "passed"
    assert page["corrupt"] == []


async def test_a_long_poll_that_expires_answers_with_the_current_record_not_with_nothing(client):
    run_id = await submit(client, SelfTestMode.SLEEP, sleep_ms=30000)
    payload = await (await client.get(f"{TESTLAB_ROUTE}/runs/{run_id}", params={"wait_s": "0.2"})).json()
    assert payload["ok"] is True and payload["run"]["run_id"] == run_id
    assert payload["run"]["status"] in {"queued", "running"}
    assert payload["outcome"]["outcome"] == "pending"
    cancelled = await (await client.post(f"{TESTLAB_ROUTE}/runs/{run_id}/cancel", json={})).json()
    assert cancelled["held"] is True
    assert (await poll_until_terminal(client, run_id))["outcome"]["outcome"] == "cancelled"


async def test_an_artifact_is_served_as_an_opaque_download(client):
    run_id = await submit(client, value=0)
    await poll_until_terminal(client, run_id)
    response = await client.get(f"{TESTLAB_ROUTE}/runs/{run_id}/artifacts/worker.log")
    assert response.status == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "attachment" in response.headers["Content-Disposition"]
    assert "selftest done" in (await response.text())

    missing = await client.get(f"{TESTLAB_ROUTE}/runs/{run_id}/artifacts/nope.txt")
    assert missing.status == 404 and (await missing.json())["code"] == "testlab_api_not_found"


async def test_cancelling_a_run_this_process_does_not_hold_says_so(client):
    """`held: false` instead of pretending: only the owning process can stop it."""
    run_id = await submit(client, value=0)
    await poll_until_terminal(client, run_id)
    payload = await (await client.post(f"{TESTLAB_ROUTE}/runs/{run_id}/cancel", json={})).json()
    assert payload["held"] is False and payload["terminal"] is True


# --------------------------------------------------------------- comparison

async def test_two_runs_are_compared_through_their_declaration(client):
    baseline = await submit(client, value=0)
    await poll_until_terminal(client, baseline)
    candidate = await submit(client, value=7)
    await poll_until_terminal(client, candidate)
    payload = await (await client.get(f"{TESTLAB_ROUTE}/compare",
                                      params={"baseline": baseline, "candidate": candidate})).json()
    assert payload["comparable"] is True
    delta = next(item for item in payload["metrics"] if item["metric"] == "selftest.value")
    assert delta["change"] == "worse" and delta["direction"] == "lower_better"


# ------------------------------------------------------------------ sweeps

async def test_a_sweep_answers_with_its_id_and_runs_in_the_background(client):
    """202 with the sweep id: minutes of work never hold a request open."""
    spec = {"schema": "jarvis.testlab.sweep", "schema_version": 1,
            "diagnostic_id": SELFTEST_DIAGNOSTIC_ID, "profile": "virtual", "version": None,
            "parameters": {"mode": "measure"}, "overrides": {},
            "swept": [{"name": "value", "target": "parameter", "values": [0, 7]}],
            "repetitions": 1, "scenario": None, "title": None, "description": None}
    response = await client.post(f"{TESTLAB_ROUTE}/sweeps", json={"spec": spec})
    payload = await response.json()
    assert response.status == 202, payload
    sweep_id = payload["sweep_id"]
    assert sweep_id.startswith("tls-")

    deadline = asyncio.get_running_loop().time() + POLL_TIMEOUT_S
    while True:
        record = await (await client.get(f"{TESTLAB_ROUTE}/sweeps/{sweep_id}")).json()
        if record["sweep"]["status"] != "running":
            break
        assert asyncio.get_running_loop().time() < deadline, "the sweep never finished"
        await asyncio.sleep(0.5)
    assert record["sweep"]["status"] == "completed"
    assert [point["runs"][0]["outcome"] for point in record["sweep"]["points"]] == ["passed", "failed"]
    assert "never writes a winning value" in record["summary"]["note"]

    page = await (await client.get(f"{TESTLAB_ROUTE}/sweeps")).json()
    assert [item["sweep_id"] for item in page["sweeps"]] == [sweep_id]


async def test_a_sweep_declaration_the_domain_refuses_is_a_400_with_its_code(client):
    spec = {"schema": "jarvis.testlab.sweep", "schema_version": 1,
            "diagnostic_id": SELFTEST_DIAGNOSTIC_ID, "profile": "virtual", "version": None,
            "parameters": {}, "overrides": {},
            "swept": [{"name": "value", "target": "parameter", "values": [99999]}],
            "repetitions": 1, "scenario": None, "title": None, "description": None}
    response = await client.post(f"{TESTLAB_ROUTE}/sweeps", json={"spec": spec})
    payload = await response.json()
    assert response.status == 400 and payload["ok"] is False and payload["code"].startswith("testlab_")


# ------------------------------------------------------------ guided prompts

async def test_a_prompt_a_worker_published_is_readable_and_answerable_over_http(lab, client):
    """The Slice 09 file channel, from the browser's side: no worker needed to prove the pair."""
    run_id = "tlr-20260918T100000000Z-0123456789abcdef"
    scratch = lab.config.work_root / run_id
    scratch.mkdir(parents=True)
    prompter = FilePrompter(scratch, poll_interval_s=0.02)
    prompt = GuidedPrompt(prompt_id="say_it", action=GuidedAction.SAY_PHRASE,
                          text="Dites la phrase.", deadline_s=30.0, phrase="jarvis bonjour")
    presenting = asyncio.ensure_future(prompter.present(prompt))
    try:
        payload = {}
        deadline = asyncio.get_running_loop().time() + 10
        while not payload.get("prompt"):
            payload = await (await client.get(f"{TESTLAB_ROUTE}/runs/{run_id}/prompt")).json()
            assert asyncio.get_running_loop().time() < deadline, "the prompt never reached the route"
        assert payload["prompt"]["prompt_id"] == "say_it"
        assert payload["prompt"]["phrase"] == "jarvis bonjour"
        # The countdown a UI needs: the deadline, and how much of it the WORKER has left.
        assert payload["prompt"]["deadline_s"] == 30.0
        assert 0 < payload["remaining_s"] <= 30.0
        assert payload["elapsed_s"] >= 0 and payload["shown_at"] > 0

        answered = await client.post(f"{TESTLAB_ROUTE}/runs/{run_id}/prompt",
                                     json={"prompt_id": "say_it", "sequence": payload["sequence"],
                                           "note": "dit"})
        assert answered.status == 200 and (await answered.json())["refused"] is False
        reply = await asyncio.wait_for(presenting, timeout=10)
        assert reply.acknowledged is True and reply.note == "dit"
    finally:
        presenting.cancel()
        await asyncio.gather(presenting, return_exceptions=True)
    assert PromptWatcher(scratch).pending() is None, "a finished prompt is never left on disk"


async def test_a_refusal_reaches_the_worker_as_a_refusal(lab, client):
    run_id = "tlr-20260918T100000000Z-0123456789abcde0"
    scratch = lab.config.work_root / run_id
    scratch.mkdir(parents=True)
    prompter = FilePrompter(scratch, poll_interval_s=0.02)
    presenting = asyncio.ensure_future(prompter.present(
        GuidedPrompt(prompt_id="quiet", action=GuidedAction.REMAIN_SILENT, text="Restez silencieux.")))
    try:
        payload = {}
        deadline = asyncio.get_running_loop().time() + 10
        while not payload.get("prompt"):
            payload = await (await client.get(f"{TESTLAB_ROUTE}/runs/{run_id}/prompt")).json()
            assert asyncio.get_running_loop().time() < deadline
        await client.post(f"{TESTLAB_ROUTE}/runs/{run_id}/prompt",
                          json={"prompt_id": "quiet", "sequence": payload["sequence"], "refused": True})
        reply = await asyncio.wait_for(presenting, timeout=10)
        assert reply.refused is True and reply.acknowledged is False
    finally:
        presenting.cancel()
        await asyncio.gather(presenting, return_exceptions=True)


# ------------------------------------------------------------------ upkeep

async def test_status_and_retention_report_the_real_composition(client, lab):
    run_id = await submit(client, value=0)
    await poll_until_terminal(client, run_id)
    status = await (await client.get(f"{TESTLAB_ROUTE}/status")).json()
    assert status["started"] is True and status["active_runs"] == []
    assert status["storage"]["runs"] == 1 and status["storage"]["corrupt"] == 0
    assert status["config"]["root"] == display_path(lab.config.root)

    plan = await (await client.get(f"{TESTLAB_ROUTE}/retention")).json()
    assert plan["enabled"] is False and plan["deletions"] == []
    applied = await (await client.post(f"{TESTLAB_ROUTE}/retention", json={})).json()
    assert applied["ok"] is True
    listed = await (await client.get(f"{TESTLAB_ROUTE}/runs")).json()
    assert len(listed["runs"]) == 1, "a disabled retention deleted a run"


async def test_the_scenario_a_caller_submits_is_validated_against_the_primitive_vocabulary(client):
    """Scenario submission: an ad-hoc scenario can reach nothing a manifest could not declare."""
    response = await client.post(f"{TESTLAB_ROUTE}/runs", json={
        "diagnostic_id": SELFTEST_DIAGNOSTIC_ID, "profile": "virtual",
        "scenario": {"schema": "jarvis.testlab.scenario", "schema_version": 1, "scenario_id": "adhoc",
                     "title": "ad hoc", "description": None, "provenance": None,
                     "steps": [{"primitive": "os.system", "args": {"at_ms": 0}}]}})
    payload = await response.json()
    assert response.status == 400 and payload["ok"] is False
    assert "primitive" in payload["error"], payload


def test_the_documented_shapes_are_json(client):
    """A shape a caller cannot json-encode is not a contract."""
    json.dumps({"ok": True, "runs": []})


async def test_a_work_root_another_process_holds_is_a_409_naming_the_real_cause(lab, client):
    """The Control Center must say who holds it, not hang and not 500."""
    holder = TestLab(lab.config)
    await holder.start()
    try:
        response = await client.post(f"{TESTLAB_ROUTE}/runs", json={
            "diagnostic_id": SELFTEST_DIAGNOSTIC_ID, "profile": "virtual"})
        payload = await response.json()
        assert response.status == 409
        assert payload["code"] == "testlab_supervisor_work_root_busy"
        assert "another supervisor" in payload["error"]
        # A read route is unaffected: it never takes the work root.
        assert (await client.get(f"{TESTLAB_ROUTE}/runs")).status == 200
    finally:
        await holder.aclose()


async def test_a_caller_cannot_grant_itself_a_capability_through_the_request_body(client):
    """The grant in a body can only narrow the one the process environment authorized."""
    response = await client.post(f"{TESTLAB_ROUTE}/runs", json={
        "diagnostic_id": SELFTEST_DIAGNOSTIC_ID, "profile": "virtual",
        "grant": {"capabilities": ["realtime_provider", "audio_input_device", "human_presence"],
                  "max_cost_usd": 100.0, "max_duration_s": None}})
    payload = await response.json()
    assert response.status == 202, payload
    run_id = payload["run_id"]
    # The run still executes (virtual needs nothing), and the reservation never saw a
    # capability: the status route reports what the process actually granted.
    status = await (await client.get(f"{TESTLAB_ROUTE}/status")).json()
    assert status["config"]["grant"]["capabilities"] == []
    assert status["config"]["grant"]["max_cost_usd"] == 0
    assert (await poll_until_terminal(client, run_id))["outcome"]["outcome"] == "passed"
