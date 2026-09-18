"""Slice 10: the Control Center HTTP surface — route table, failure mapping, guard, shapes.

Contract: `docs/testlab.md` ("Native API, CLI and HTTP"). No worker process is started
here: these tests pin what the routes ARE (the table, the documented table, the statuses,
the guard) and leave "a real run through HTTP" to
`tests/integration/test_testlab_http_routes.py`.
"""

from __future__ import annotations

from pathlib import Path
import re

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.runtime.control_center import READ_GUARDED_ROUTES, ControlCenter
from jarvis.runtime.control_center import TESTLAB_ROUTE as CONTROL_CENTER_PREFIX
from jarvis.testlab.api import API_NOT_FOUND, API_UNAVAILABLE, TestLabApi, TestLabApiError
from jarvis.testlab.composition import TestLab, TestLabConfig, build_test_lab
from jarvis.testlab.http import (
    HTTP_INVALID,
    HTTP_TOO_LARGE,
    INTERNAL_ERROR_CODE,
    INTERNAL_ERROR_MESSAGE,
    MAX_BODY_BYTES,
    TESTLAB_APP_KEY,
    TESTLAB_ROUTE,
    TestLabHttpError,
    TestLabRoutes,
    failure_payload,
    http_status,
    install_testlab_routes,
)
from jarvis.testlab.manifests import CATALOG_NOT_FOUND, CatalogError
from jarvis.testlab.store import (
    STORE_BUSY,
    STORE_CONFLICT,
    STORE_CORRUPT,
    BundleNotFoundError,
    RunConflictError,
    RunNotFoundError,
    RunRecordCorruptError,
    SweepNotFoundError,
    TestLabStoreError,
)
from jarvis.testlab.supervisor import SUPERVISOR_WORK_ROOT_BUSY, SupervisorError
from jarvis.testlab.validation import TestLabError

DOCS = Path(__file__).resolve().parents[2] / "docs" / "testlab.md"


def lab_for(tmp_path: Path) -> TestLab:
    root = tmp_path / "testlab"
    return TestLab(TestLabConfig(root=root, work_root=root / "work", runtime_root=tmp_path,
                                 data_root=tmp_path / "data"))


@pytest.fixture
async def client(tmp_path):
    """A bare aiohttp application carrying only the Test Lab routes (no Control Center)."""
    app = web.Application()
    install_testlab_routes(app, lab=lab_for(tmp_path))
    served = TestClient(TestServer(app))
    await served.start_server()
    try:
        yield served
    finally:
        await served.close()


def registered(app: web.Application) -> set[str]:
    paths = set()
    for resource in app.router.resources():
        info = resource.get_info()
        path = info.get("path") or info.get("formatter")
        if path:
            paths.add(path)
    return paths


# ------------------------------------------------------------- route table

def test_the_control_center_and_the_module_agree_on_the_prefix():
    """`control_center.py` repeats the literal so its middleware needs no testlab import."""
    assert CONTROL_CENTER_PREFIX == TESTLAB_ROUTE == "/api/testlab"
    assert TESTLAB_ROUTE in READ_GUARDED_ROUTES


def test_every_registered_route_is_documented_and_every_documented_route_exists(tmp_path):
    app = web.Application()
    install_testlab_routes(app, lab=lab_for(tmp_path))
    served = {path for path in registered(app) if path.startswith(TESTLAB_ROUTE)}
    table = DOCS.read_text(encoding="utf-8").partition("<!-- testlab-routes -->")[2] \
        .partition("<!-- /testlab-routes -->")[0]
    assert table.strip(), "docs/testlab.md carries no Test Lab route table"
    documented = set(re.findall(r"`(/api/testlab[A-Za-z0-9_{}/.-]*)`", table))
    # aiohttp renders `{path:.+}` as `{path}` in its formatter.
    assert served == documented, sorted(served ^ documented)


def test_the_routes_cover_every_operation_the_slice_names(tmp_path):
    app = web.Application()
    install_testlab_routes(app, lab=lab_for(tmp_path))
    served = registered(app)
    for path in (f"{TESTLAB_ROUTE}/diagnostics", f"{TESTLAB_ROUTE}/diagnostics/{{diagnostic_id}}",
                 f"{TESTLAB_ROUTE}/runs", f"{TESTLAB_ROUTE}/runs/{{run_id}}",
                 f"{TESTLAB_ROUTE}/runs/{{run_id}}/cancel", f"{TESTLAB_ROUTE}/runs/{{run_id}}/prompt",
                 f"{TESTLAB_ROUTE}/compare", f"{TESTLAB_ROUTE}/sweeps", f"{TESTLAB_ROUTE}/bundles",
                 f"{TESTLAB_ROUTE}/retention", f"{TESTLAB_ROUTE}/status"):
        assert path in served, path


def test_the_control_center_registers_them_all(tmp_path):
    center = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    served = {path for path in registered(center._app) if path.startswith(TESTLAB_ROUTE)}
    assert len(served) >= 15
    assert isinstance(center._app[TESTLAB_APP_KEY], TestLabRoutes)


def test_installing_the_routes_creates_nothing(tmp_path):
    app = web.Application()
    install_testlab_routes(app, runtime_root=tmp_path / "runtime")
    assert not (tmp_path / "runtime").exists()


# ----------------------------------------------------------- failure mapping

@pytest.mark.parametrize("exc, status", [
    (RunNotFoundError("testlab_store_not_found", "no run"), 404),
    (BundleNotFoundError("testlab_store_not_found", "no bundle"), 404),
    (SweepNotFoundError("testlab_sweep_not_found", "no sweep"), 404),
    (TestLabApiError(API_NOT_FOUND, "no artifact"), 404),
    (CatalogError(CATALOG_NOT_FOUND, "no diagnostic"), 404),
    (RunConflictError(STORE_CONFLICT, "changed under us"), 409),
    (SupervisorError(SUPERVISOR_WORK_ROOT_BUSY, "another supervisor"), 409),
    (TestLabStoreError(STORE_BUSY, "locked"), 409),
    (TestLabApiError(API_UNAVAILABLE, "did not start"), 503),
    (TestLabError("testlab_field_invalid", "bad value"), 400),
    (RunRecordCorruptError(STORE_CORRUPT, "unreadable"), 400),
    (RuntimeError("something we did not foresee"), 500),
])
def test_each_failure_gets_the_status_it_deserves(exc, status):
    assert http_status(exc) == status


def test_an_unmapped_failure_is_ours_not_the_callers():
    """500 on purpose: a failure we did not foresee must never read as a bad request."""
    assert http_status(ZeroDivisionError()) == 500


def test_the_refusal_payload_keeps_the_real_code_and_sentence():
    payload = failure_payload(RunNotFoundError("testlab_store_not_found", "run tlr-x does not exist"))
    assert payload == {"ok": False, "code": "testlab_store_not_found", "error": "run tlr-x does not exist"}


def test_a_failure_with_no_code_still_names_what_happened():
    payload = failure_payload(ValueError("a list index"))
    assert payload["code"] == "testlab_internal_error" and "ValueError" in payload["error"]


# ------------------------------------------------------------------ serving

async def test_the_catalog_is_served_as_it_is(client):
    response = await client.get(f"{TESTLAB_ROUTE}/diagnostics")
    payload = await response.json()
    assert response.status == 200 and payload["ok"] is True
    assert {item["diagnostic_id"] for item in payload["diagnostics"]} >= {"voice.self_echo"}


async def test_one_diagnostic_carries_its_versions(client):
    response = await client.get(f"{TESTLAB_ROUTE}/diagnostics/voice.self_echo")
    payload = await response.json()
    assert payload["diagnostic"]["version"] == max(payload["versions"])
    assert payload["diagnostic"]["assertions"], "the declaration must reach the UI whole"


async def test_an_unknown_diagnostic_is_404_with_its_code(client):
    response = await client.get(f"{TESTLAB_ROUTE}/diagnostics/voice.nope")
    payload = await response.json()
    assert response.status == 404 and payload["ok"] is False
    assert payload["code"] == CATALOG_NOT_FOUND and "voice.nope" in payload["error"]


async def test_an_unknown_run_is_404(client):
    response = await client.get(f"{TESTLAB_ROUTE}/runs/tlr-20260918T100000000Z-0123456789abcdef")
    assert response.status == 404 and (await response.json())["code"] == "testlab_store_not_found"


async def test_a_malformed_run_id_is_400_not_500(client):
    response = await client.get(f"{TESTLAB_ROUTE}/runs/not-a-run-id")
    payload = await response.json()
    assert response.status == 400 and payload["ok"] is False and payload["code"].startswith("testlab_")


async def test_an_empty_listing_is_an_empty_page_not_an_error(client):
    """An absent store is the normal first-run state, not a fault."""
    response = await client.get(f"{TESTLAB_ROUTE}/runs")
    payload = await response.json()
    assert response.status == 200 and payload["runs"] == [] and payload["corrupt"] == []


async def test_the_status_route_shows_the_composition_and_the_grant(client):
    payload = await (await client.get(f"{TESTLAB_ROUTE}/status")).json()
    assert payload["started"] is False and payload["active_runs"] == []
    assert payload["config"]["grant"]["capabilities"] == []
    assert "state" in payload["contention"] and "reason" in payload["contention"]


async def test_a_body_that_is_not_a_json_object_is_refused_with_a_sentence(client):
    for body in (b"", b"[1,2]", b"{oops"):
        response = await client.post(f"{TESTLAB_ROUTE}/runs", data=body)
        payload = await response.json()
        assert response.status == 400, body
        assert payload["code"] == "testlab_http_invalid" and payload["error"]


async def test_submitting_a_run_without_a_diagnostic_id_says_which_field_is_missing(client):
    response = await client.post(f"{TESTLAB_ROUTE}/runs", json={"profile": "virtual"})
    payload = await response.json()
    assert response.status == 400 and "diagnostic_id is required" in payload["error"]


async def test_an_unknown_profile_is_named_in_the_refusal(client):
    response = await client.post(f"{TESTLAB_ROUTE}/runs",
                                 json={"diagnostic_id": "voice.self_echo", "profile": "quantum"})
    payload = await response.json()
    assert response.status == 400 and "unknown profile" in payload["error"]


async def test_compare_without_both_run_ids_is_a_refusal_not_an_empty_answer(client):
    response = await client.get(f"{TESTLAB_ROUTE}/compare", params={"baseline": "tlr-x"})
    assert response.status == 400 and "candidate" in (await response.json())["error"]


async def test_a_run_with_no_guided_prompt_answers_null_rather_than_404(client):
    """A run that is not guided is not an error: it simply has nothing to show."""
    run_id = "tlr-20260918T100000000Z-0123456789abcdef"
    payload = await (await client.get(f"{TESTLAB_ROUTE}/runs/{run_id}/prompt")).json()
    assert payload["ok"] is True and payload["prompt"] is None and payload["run_id"] == run_id


async def test_acknowledging_without_the_sequence_the_prompt_reported_is_refused(client):
    run_id = "tlr-20260918T100000000Z-0123456789abcdef"
    response = await client.post(f"{TESTLAB_ROUTE}/runs/{run_id}/prompt",
                                 json={"prompt_id": "step", "sequence": "1"})
    assert response.status == 400 and "sequence" in (await response.json())["error"]


async def test_the_retention_plan_is_readable_and_deletes_nothing(client):
    payload = await (await client.get(f"{TESTLAB_ROUTE}/retention")).json()
    assert payload["enabled"] is False and payload["deletions"] == []


# -------------------------------------------------------------------- guard

@pytest.fixture
async def guarded(tmp_path):
    """The real Control Center, so the origin/loopback middleware is the product's own."""
    center = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    served = TestClient(TestServer(center._app))
    await served.start_server()
    try:
        yield served
    finally:
        await served.close()


async def test_a_cross_site_read_is_refused_although_it_is_a_get(guarded):
    """Test Lab evidence is read-sensitive, like conversation history: GET is guarded too."""
    response = await guarded.get(f"{TESTLAB_ROUTE}/diagnostics", headers={"Sec-Fetch-Site": "cross-site"})
    payload = await response.json()
    assert response.status == 403 and payload["code"] == "forbidden_origin"


async def test_a_foreign_origin_is_refused(guarded):
    response = await guarded.get(f"{TESTLAB_ROUTE}/status", headers={"Origin": "http://evil.example"})
    assert response.status == 403


async def test_a_loopback_read_is_served(guarded):
    response = await guarded.get(f"{TESTLAB_ROUTE}/diagnostics", headers={"Origin": "http://127.0.0.1:17654"})
    assert response.status == 200


async def test_the_conversation_routes_keep_their_own_guard(guarded):
    """The prefix list grew; the behaviour it already had must not have changed."""
    response = await guarded.get("/api/conversations", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status == 403 and (await response.json())["code"] == "forbidden_origin"


async def test_an_ordinary_get_is_still_unguarded(guarded):
    response = await guarded.get("/api/status", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status == 200, "the guard must not have spread to every route"


# ---------------------------------------------------------------- journaling

class RecordingSink:
    """A `DiagnosticSink` that keeps what it was told."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append((kind, level, dict(data or {})))


class BrokenSink:
    def emit(self, *_: object, **__: object) -> None:
        raise RuntimeError("the journal is unwritable")


async def served_with(tmp_path, sink):
    app = web.Application()
    install_testlab_routes(app, lab=lab_for(tmp_path), journal=sink)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def test_a_refused_request_leaves_a_journal_line_with_its_code(tmp_path):
    """An empty Error Logs panel after a visible failure is the defect this prevents."""
    sink = RecordingSink()
    client = await served_with(tmp_path, sink)
    try:
        assert (await client.get(f"{TESTLAB_ROUTE}/diagnostics/voice.nope")).status == 404
    finally:
        await client.close()
    failures = [event for event in sink.events if event[0] == "testlab.http.failed"]
    assert len(failures) == 1
    _, level, data = failures[0]
    assert level == "warning" and data["status"] == 404
    assert data["code"] == CATALOG_NOT_FOUND and data["path"].endswith("voice.nope")


async def test_a_journal_that_cannot_be_written_never_fails_the_request(tmp_path):
    client = await served_with(tmp_path, BrokenSink())
    try:
        response = await client.get(f"{TESTLAB_ROUTE}/diagnostics/voice.nope")
        assert response.status == 404 and (await response.json())["code"] == CATALOG_NOT_FOUND
        assert (await client.get(f"{TESTLAB_ROUTE}/diagnostics")).status == 200
    finally:
        await client.close()


# ----------------------------------- rework S1: a body is read whole, or refused as too big

def spec_of(size_bytes: int) -> dict:
    """A well-formed body padded to roughly `size_bytes`, so only its SIZE is under test.

    It deliberately omits `diagnostic_id`, so the route has to have read the WHOLE body to
    discover the missing field — and nothing is ever queued by these tests.
    """
    return {"profile": "virtual", "parameters": {}, "note": "x" * max(0, size_bytes - 120)}


@pytest.mark.parametrize("size", [1_000, 20_000, 100_000, 200_000])
async def test_a_large_but_legal_body_is_read_whole(client, size):
    """`request.content.read(n)` returned what happened to be buffered, so a body larger
    than one chunk came back truncated and was refused as malformed JSON."""
    response = await client.post(f"{TESTLAB_ROUTE}/runs", json=spec_of(size))
    payload = await response.json()
    assert response.status == 400, (size, payload)
    # Refused for the honest reason a complete document gives, never for size or syntax.
    assert "diagnostic_id is required" in payload["error"], (size, payload)
    assert payload["code"] == HTTP_INVALID and "not UTF-8 JSON" not in payload["error"]


@pytest.mark.parametrize("size", [MAX_BODY_BYTES + 1_000, 400_000])
async def test_an_oversized_body_says_it_is_too_big(client, size):
    response = await client.post(f"{TESTLAB_ROUTE}/runs", json=spec_of(size))
    payload = await response.json()
    assert response.status == 413, payload
    assert payload["code"] == HTTP_TOO_LARGE
    assert str(MAX_BODY_BYTES) in payload["error"] and "limit" in payload["error"]


def test_a_body_that_is_too_large_has_its_own_status():
    assert http_status(TestLabHttpError(HTTP_TOO_LARGE, "too big")) == 413
    assert http_status(TestLabHttpError(HTTP_INVALID, "malformed")) == 400


# ---------------------------- rework S2: a 500 never carries the raw exception message

async def test_an_unforeseen_failure_answers_a_generic_sentence_and_journals_the_cause(tmp_path):
    """QA got a credential and an absolute path out of a raw exception message in a body."""
    sink = RecordingSink()
    app = web.Application()
    routes = install_testlab_routes(app, lab=lab_for(tmp_path), journal=sink)
    secret = r"sk-live-SECRET while reading C:\Users\someone\secrets\key.txt"

    async def explode() -> dict:
        raise RuntimeError(secret)

    routes.api.list_diagnostics = explode  # type: ignore[method-assign]
    served = TestClient(TestServer(app))
    await served.start_server()
    try:
        response = await served.get(f"{TESTLAB_ROUTE}/diagnostics")
        body = await response.text()
        payload = await response.json()
    finally:
        await served.close()
    assert response.status == 500
    assert payload["code"] == INTERNAL_ERROR_CODE and payload["error"] == INTERNAL_ERROR_MESSAGE
    assert "sk-live-SECRET" not in body and "secrets" not in body
    journaled = [event for event in sink.events if event[0] == "testlab.http.failed"]
    assert journaled and secret[:40] in journaled[0][2]["detail"], "the cause must survive somewhere"


async def test_a_coded_refusal_below_500_keeps_its_own_sentence(client):
    """Those messages are written by this package on purpose; only 5xx is generic."""
    payload = await (await client.get(f"{TESTLAB_ROUTE}/diagnostics/voice.nope")).json()
    assert payload["error"] != INTERNAL_ERROR_MESSAGE and "voice.nope" in payload["error"]


# ------------------- rework 3: validate first, take the work root last

def untouched(lab: TestLab) -> bool:
    return not lab.config.root.exists() and not lab.config.work_root.exists()


async def refusing(tmp_path, method: str, path: str, **kwargs):
    """One request against a fresh lab, with the lab returned so the disk can be checked."""
    lab = lab_for(tmp_path)
    app = web.Application()
    install_testlab_routes(app, lab=lab)
    served = TestClient(TestServer(app))
    await served.start_server()
    try:
        response = await getattr(served, method)(path, **kwargs)
        return response.status, await response.json(), lab
    finally:
        await served.close()


async def test_an_unknown_diagnostic_is_refused_before_the_work_root_exists(tmp_path):
    """The same defect the CLI just fixed: a 400 that had already created `testlab/work`."""
    status, payload, lab = await refusing(tmp_path, "post", f"{TESTLAB_ROUTE}/runs",
                                          json={"diagnostic_id": "voice.nope", "profile": "virtual"})
    assert status == 404 and payload["code"] == CATALOG_NOT_FOUND
    assert untouched(lab), f"a refused POST created {lab.config.root}"


@pytest.mark.parametrize("body, status", [
    ({"diagnostic_id": "voice.self_echo", "profile": "quantum"}, 400),
    ({"diagnostic_id": "voice.self_echo", "profile": "virtual", "version": 99}, 404),
    ({"diagnostic_id": "voice.self_echo", "profile": "virtual",
      "scenario": {"schema": "jarvis.testlab.scenario", "schema_version": 1, "scenario_id": "adhoc",
                   "title": None, "description": None, "provenance": None,
                   "steps": [{"primitive": "os.system", "args": {}}]}}, 400),
])
async def test_every_refused_run_body_leaves_the_disk_alone(tmp_path, body, status):
    answered, payload, lab = await refusing(tmp_path, "post", f"{TESTLAB_ROUTE}/runs", json=body)
    assert answered == status, payload
    assert untouched(lab), f"{body} created {lab.config.root}"


async def test_a_refused_sweep_declaration_leaves_the_disk_alone(tmp_path):
    spec = {"schema": "jarvis.testlab.sweep", "schema_version": 1, "diagnostic_id": "voice.nope",
            "profile": "virtual", "version": None, "parameters": {}, "overrides": {},
            "swept": [{"name": "x", "target": "parameter", "values": [1]}],
            "repetitions": 1, "scenario": None, "title": None, "description": None}
    status, payload, lab = await refusing(tmp_path, "post", f"{TESTLAB_ROUTE}/sweeps", json={"spec": spec})
    assert status == 404 and payload["code"] == CATALOG_NOT_FOUND
    assert untouched(lab)


async def test_cancelling_an_unknown_run_leaves_the_disk_alone(tmp_path):
    run_id = "tlr-20260918T100000000Z-0123456789abcdef"
    status, payload, lab = await refusing(tmp_path, "post", f"{TESTLAB_ROUTE}/runs/{run_id}/cancel", json={})
    assert status == 404 and payload["code"] == "testlab_store_not_found"
    assert untouched(lab)


async def test_cancelling_a_sweep_nobody_is_running_takes_no_work_root(tmp_path):
    status, payload, lab = await refusing(tmp_path, "post",
                                          f"{TESTLAB_ROUTE}/sweeps/tls-20260918T100000000Z-0123456789abcdef/cancel")
    assert status == 200 and payload["held"] is False
    assert untouched(lab)


async def test_an_oversized_body_is_refused_before_the_work_root_too(tmp_path):
    status, payload, lab = await refusing(tmp_path, "post", f"{TESTLAB_ROUTE}/runs",
                                          json=spec_of(MAX_BODY_BYTES + 1_000))
    assert status == 413 and payload["code"] == HTTP_TOO_LARGE
    assert untouched(lab)
