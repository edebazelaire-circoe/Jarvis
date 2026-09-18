"""Control Center HTTP surface of the Test Lab: `/api/testlab/...`.

Binding contract: `docs/testlab.md` ("Native API, CLI and HTTP"). A separate module,
registered into the existing aiohttp application with one call, so this Slice adds a
handful of lines to `jarvis/runtime/control_center.py` and nothing else (READINESS,
conflict zones: `control_center.py` is parallel work).

What these routes are, and are not:

- they EXPOSE, they never decide. No endpoint chooses a diagnostic, reads a threshold or
  judges a run: the outcome of a run is `RunOutcomeSummary` derived by the domain, the
  comparison is `compare_runs`, the sweep summary is the stored document. Slice 11
  renders them and derives nothing.
- they inherit every safety gate rather than re-deciding it. The capability grant comes
  from the process environment through `jarvis.testlab.composition`; a request body may
  carry a grant and it can only NARROW that one. The live opt-in, the guided presence
  opt-in, device contention, the device lease, the cost budget and the audio-artifact
  opt-in all stay in the supervisor's reservation path, where Slices 05, 08 and 09 put
  them, and no route here can reach around them.
- the run store is SYNCHRONOUS (local files under an OS lock), so every call into it goes
  through `asyncio.to_thread` inside `TestLabApi`. No handler blocks the Control Center.
- long work never holds a request open. Submitting a run answers with its id; submitting a
  sweep answers with its sweep id; progress is a poll, optionally a bounded long poll
  (`?wait_s=`), which always answers with the current record rather than with nothing.

The origin/loopback discipline is the Control Center's own: `/api/testlab` is registered
in its read-guarded prefixes, so every method — not only writes — needs a loopback `Host`,
a loopback `Origin` when one is sent, and a request that is not `Sec-Fetch-Site:
cross-site`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from aiohttp import web

from jarvis.ports.v2 import DiagnosticSink
from jarvis.testlab.api import (
    API_NOT_FOUND,
    API_UNAVAILABLE,
    MAX_WAIT_S,
    TestLabApi,
    TestLabApiError,
    parse_time_argument,
    sweep_spec,
)
from jarvis.testlab.bundle_builder import SessionSelector
from jarvis.testlab.composition import TestLab, build_test_lab
from jarvis.testlab.manifests import CATALOG_NOT_FOUND, CatalogError
from jarvis.testlab.profiles import ResourceGrant
from jarvis.testlab.store import (
    STORE_BUSY,
    STORE_DELETION_PENDING,
    BundleNotFoundError,
    RunConflictError,
    RunNotFoundError,
    SweepNotFoundError,
    TestLabStoreError,
)
from jarvis.testlab.supervisor import SUPERVISOR_WORK_ROOT_BUSY, SupervisorError
from jarvis.testlab.validation import TestLabError

#: Prefix of every Test Lab route. `control_center.py` repeats this literal in its
#: read-guarded prefixes; `tests/unit/test_testlab_http.py` pins the two equal.
TESTLAB_ROUTE = "/api/testlab"
#: A request body is a handful of parameters. Anything larger is not one of ours.
MAX_BODY_BYTES = 256 * 1024
#: Artifacts are served as downloads, never rendered: they are machine output, and some
#: of them are logs a worker wrote.
ARTIFACT_HEADERS = {"X-Content-Type-Options": "nosniff"}

#: What a 5xx tells the caller. The real message of an unforeseen exception can carry
#: anything the code was holding — a path, a token, the contents of a file — so it goes to
#: the journal, which is local and redacted, and never into a response body.
INTERNAL_ERROR_CODE = "testlab_internal_error"
INTERNAL_ERROR_MESSAGE = ("the Test Lab failed while serving this request; the cause is in the "
                          "Jarvis journal (kind testlab.http.failed)")

_BUSY_STORE_CODES = frozenset({STORE_BUSY, STORE_DELETION_PENDING})


class TestLabHttpError(TestLabError):
    """A request these routes refuse: a body they cannot read, a query they cannot parse."""


HTTP_INVALID = "testlab_http_invalid"
#: A body past `MAX_BODY_BYTES`. Its own code, so a caller can tell "too big" from
#: "malformed" and shrink the document instead of hunting for a syntax error.
HTTP_TOO_LARGE = "testlab_http_too_large"


# ------------------------------------------------------------------ failures

def http_status(exc: BaseException) -> int:
    """The status one failure deserves. Typed, never guessed from a message.

    404 for something that does not exist, 409 for a lock somebody else holds, 503 for a
    piece that did not come up, 400 for a request we could not honour, 500 for our own
    defect. Anything unmapped is 500 on purpose: a failure we did not foresee must not
    read as the caller's mistake.
    """
    if isinstance(exc, (RunNotFoundError, BundleNotFoundError, SweepNotFoundError)):
        return 404
    if isinstance(exc, RunConflictError):
        return 409
    if isinstance(exc, TestLabApiError):
        return {API_NOT_FOUND: 404, API_UNAVAILABLE: 503}.get(exc.code, 400)
    if isinstance(exc, CatalogError):
        return 404 if exc.code == CATALOG_NOT_FOUND else 400
    if isinstance(exc, SupervisorError):
        return 409 if exc.code == SUPERVISOR_WORK_ROOT_BUSY else 400
    if isinstance(exc, TestLabStoreError):
        return 409 if exc.code in _BUSY_STORE_CODES else 400
    if isinstance(exc, TestLabHttpError):
        return 413 if exc.code == HTTP_TOO_LARGE else 400
    if isinstance(exc, TestLabError):
        return 400
    return 500


def failure_payload(exc: BaseException) -> dict[str, Any]:
    """The Control Center's own refusal shape, carrying the Test Lab's stable code.

    The code is what an agent branches on and the detail is the sentence whatever
    produced the failure wrote. Neither is ever replaced by a generic one.
    """
    code = getattr(exc, "code", None)
    detail = getattr(exc, "detail", None)
    if not isinstance(code, str):
        code = INTERNAL_ERROR_CODE
        detail = f"{type(exc).__name__}: {exc}"
    return {"ok": False, "code": code, "error": detail if isinstance(detail, str) else str(exc)}


# -------------------------------------------------------------------- routes

class TestLabRoutes:
    """The handlers. One composed `TestLabApi`, started on the first request that needs it."""

    __test__ = False  # not a pytest test class, despite the name

    def __init__(self, api: TestLabApi, *, diagnostics: DiagnosticSink | None = None) -> None:
        self._api = api
        self._diagnostics = diagnostics
        self._starting = asyncio.Lock()

    @property
    def api(self) -> TestLabApi:
        return self._api

    # ------------------------------------------------------------- lifecycle

    async def _supervised(self) -> TestLabApi:
        """Start the supervisor once, on the first request that needs to execute something.

        Deliberately NOT done when the Control Center starts: taking the work root at
        boot would refuse a CLI sweep that is already running, and an operator would find
        the Control Center unable to start for a reason that has nothing to do with it.
        A work root somebody else holds surfaces here, as a 409 naming the real cause.
        """
        async with self._starting:
            if not self._api.lab.started:
                report = await self._api.start()
                self._emit("testlab.http.supervisor_started", "Test Lab supervisor started for the Control Center",
                           reaped=len(report["reaped"]), recovered=len(report["recovered"]),
                           active_elsewhere=len(report["active_elsewhere"]))
        return self._api

    async def aclose(self) -> None:
        await self._api.aclose()

    def _emit(self, kind: str, message: str, *, level: str = "info", **data: Any) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            # Captured, argued: a broken journal must not turn a served request into a
            # failed one. The response is already correct; only the note is lost.
            pass

    # --------------------------------------------------------------- plumbing

    def _guard(self, handler):
        """Wrap one handler so every failure becomes a coded payload AND a journal line.

        This is the entry point the error contract asks for: no route may answer with a
        bare traceback, and no failure may leave the journal empty.
        """
        async def wrapped(request: web.Request) -> web.StreamResponse:
            try:
                return await handler(request)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - this IS the boundary
                status = http_status(exc)
                payload = failure_payload(exc)
                self._emit("testlab.http.failed", f"Test Lab request failed: {payload['code']}",
                           level="error" if status >= 500 else "warning", path=request.path,
                           method=request.method, status=status, code=payload["code"],
                           error=type(exc).__name__, detail=payload["error"][:500])
                if status >= 500:
                    # Our own defect: the coded refusals below 500 are sentences this
                    # package wrote on purpose, but an unforeseen exception's message is
                    # whatever it was holding. It is journaled above and generic here.
                    payload = {"ok": False, "code": INTERNAL_ERROR_CODE, "error": INTERNAL_ERROR_MESSAGE}
                return web.json_response(payload, status=status)

        wrapped.__name__ = getattr(handler, "__name__", "testlab_handler")
        return wrapped

    def routes(self) -> list[web.RouteDef]:
        """Every Test Lab route, each wrapped in the failure boundary."""
        guard, base = self._guard, TESTLAB_ROUTE
        return [
            web.get(f"{base}/status", guard(self.status)),
            web.get(f"{base}/diagnostics", guard(self.diagnostics)),
            web.get(f"{base}/diagnostics/{{diagnostic_id}}", guard(self.describe)),
            web.get(f"{base}/runs", guard(self.list_runs)),
            web.post(f"{base}/runs", guard(self.submit_run)),
            web.get(f"{base}/runs/{{run_id}}", guard(self.get_run)),
            web.post(f"{base}/runs/{{run_id}}/cancel", guard(self.cancel_run)),
            web.get(f"{base}/runs/{{run_id}}/artifacts/{{path:.+}}", guard(self.artifact)),
            web.get(f"{base}/runs/{{run_id}}/prompt", guard(self.pending_prompt)),
            web.post(f"{base}/runs/{{run_id}}/prompt", guard(self.acknowledge_prompt)),
            web.get(f"{base}/compare", guard(self.compare)),
            web.get(f"{base}/sweeps", guard(self.list_sweeps)),
            web.post(f"{base}/sweeps", guard(self.start_sweep)),
            web.get(f"{base}/sweeps/{{sweep_id}}", guard(self.get_sweep)),
            web.post(f"{base}/sweeps/{{sweep_id}}/cancel", guard(self.cancel_sweep)),
            web.get(f"{base}/bundles", guard(self.list_bundles)),
            web.post(f"{base}/bundles", guard(self.capture_bundle)),
            web.get(f"{base}/bundles/{{bundle_id}}", guard(self.get_bundle)),
            web.get(f"{base}/retention", guard(self.retention)),
            web.post(f"{base}/retention", guard(self.maintain)),
        ]

    # --------------------------------------------------------------- handlers

    async def status(self, request: web.Request) -> web.Response:
        return _ok(await self._api.status())

    async def diagnostics(self, request: web.Request) -> web.Response:
        return _ok(await self._api.list_diagnostics())

    async def describe(self, request: web.Request) -> web.Response:
        version = _int_query(request, "version")
        return _ok(await self._api.describe(request.match_info["diagnostic_id"], version))

    async def list_runs(self, request: web.Request) -> web.Response:
        statuses = request.query.getall("status", []) or None
        return _ok(await self._api.query_runs(
            diagnostic_id=request.query.get("diagnostic_id"),
            diagnostic_version=_int_query(request, "version"),
            profile=request.query.get("profile"), statuses=statuses,
            sweep_id=request.query.get("sweep_id"), bundle_id=request.query.get("bundle_id"),
            limit=_int_query(request, "limit"), after_run_id=request.query.get("after"),
            newest_first=False if "oldest_first" in request.query else None))

    async def submit_run(self, request: web.Request) -> web.Response:
        """Queue a run. Everything the catalog can refuse is refused BEFORE the work root.

        Same ordering as the CLI's `_run_command`: an unknown diagnostic, an unsupported
        profile or a scenario outside the primitive vocabulary must not have created
        `<runtime>/testlab/work/` and taken its lock on the way to a 400.
        """
        body = await _body(request)
        diagnostic_id, profile = _required(body, "diagnostic_id"), _required(body, "profile")
        await self._api.check_run_request(diagnostic_id, profile, version=body.get("version"),
                                          scenario=body.get("scenario"))
        api = await self._supervised()
        submitted = await api.submit_run(
            diagnostic_id, profile, version=body.get("version"),
            parameters=body.get("parameters"), overrides=body.get("overrides"),
            scenario=body.get("scenario"), bundle_id=body.get("bundle_id"),
            grant=_grant(body.get("grant")), allow_audio_artifacts=bool(body.get("allow_audio_artifacts")))
        self._emit("testlab.http.run_submitted", f"Test Lab run {submitted['run_id']} submitted",
                   run_id=submitted["run_id"], diagnostic=body.get("diagnostic_id"), profile=body.get("profile"))
        return _ok(submitted, status=202)

    async def get_run(self, request: web.Request) -> web.Response:
        """One run, with `?wait_s=` bounding a long poll for its terminal record."""
        wait_s = _float_query(request, "wait_s")
        if wait_s is not None:
            wait_s = max(0.0, min(wait_s, MAX_WAIT_S))
        return _ok(await self._api.show_run(request.match_info["run_id"], wait_s=wait_s))

    async def cancel_run(self, request: web.Request) -> web.Response:
        body = await _body(request, optional=True)
        # The store answers "is there such a run" without any lock; only then the work root.
        run_id = request.match_info["run_id"]
        await self._api.get_run(run_id)
        api = await self._supervised()
        return _ok(await api.cancel_run(run_id, reason=body.get("reason")))

    async def artifact(self, request: web.Request) -> web.Response:
        data, ref = await self._api.read_artifact(request.match_info["run_id"], request.match_info["path"])
        headers = dict(ARTIFACT_HEADERS)
        headers["Content-Disposition"] = f'attachment; filename="{Path(ref["path"]).name}"'
        try:
            return web.Response(body=data, content_type=ref["media_type"], headers=headers)
        except ValueError:
            # Captured, argued: a stored media type aiohttp will not accept as a bare
            # content type must not lose the caller its bytes. Served as an opaque
            # download instead, with the declared type kept in a header of its own.
            headers["X-Jarvis-Artifact-Media-Type"] = str(ref["media_type"])
            return web.Response(body=data, content_type="application/octet-stream", headers=headers)

    async def pending_prompt(self, request: web.Request) -> web.Response:
        return _ok(await self._api.pending_prompt(request.match_info["run_id"]))

    async def acknowledge_prompt(self, request: web.Request) -> web.Response:
        body = await _body(request)
        sequence = body.get("sequence")
        if type(sequence) is not int:
            raise TestLabHttpError(HTTP_INVALID, "sequence must be the integer the prompt reported")
        return _ok(await self._api.acknowledge_prompt(
            request.match_info["run_id"], _required(body, "prompt_id"), sequence,
            refused=bool(body.get("refused", False)), note=body.get("note")))

    async def compare(self, request: web.Request) -> web.Response:
        baseline, candidate = request.query.get("baseline"), request.query.get("candidate")
        if not baseline or not candidate:
            raise TestLabHttpError(HTTP_INVALID, "compare needs baseline= and candidate= run ids")
        return _ok(await self._api.compare(baseline, candidate))

    async def list_sweeps(self, request: web.Request) -> web.Response:
        return _ok(await self._api.list_sweeps(limit=_int_query(request, "limit"),
                                               after_sweep_id=request.query.get("after")))

    async def start_sweep(self, request: web.Request) -> web.Response:
        """Start a sweep. The declaration is decoded and resolved before the work root."""
        body = await _body(request)
        spec = sweep_spec(_required(body, "spec"))
        await self._api.check_run_request(spec.diagnostic_id, spec.profile, version=spec.version,
                                          scenario=spec.scenario)
        api = await self._supervised()
        started = await api.start_sweep(spec, grant=_grant(body.get("grant")))
        self._emit("testlab.http.sweep_started", f"Test Lab sweep {started['sweep_id']} started",
                   sweep_id=started["sweep_id"])
        return _ok(started, status=202)

    async def get_sweep(self, request: web.Request) -> web.Response:
        return _ok(await self._api.get_sweep(request.match_info["sweep_id"]))

    async def cancel_sweep(self, request: web.Request) -> web.Response:
        """Stop a sweep this process is running. No work root: a sweep in flight already
        started the supervisor, and one that is not gets an honest `held: false`."""
        return _ok(await self._api.cancel_sweep(request.match_info["sweep_id"]))

    async def list_bundles(self, request: web.Request) -> web.Response:
        return _ok(await self._api.list_bundles(limit=_int_query(request, "limit"),
                                                conversation_id=request.query.get("conversation_id"),
                                                after_bundle_id=request.query.get("after")))

    async def get_bundle(self, request: web.Request) -> web.Response:
        document = request.query.get("document") == "1"
        return _ok(await self._api.get_bundle(request.match_info["bundle_id"], document=document))

    async def capture_bundle(self, request: web.Request) -> web.Response:
        body = await _body(request)
        selector = SessionSelector(conversation_id=body.get("conversation_id"),
                                   session_id=body.get("session_id"),
                                   start=parse_time_argument(body.get("start"), "start"),
                                   end=parse_time_argument(body.get("end"), "end"))
        return _ok(await self._api.capture_bundle(selector, with_events=bool(body.get("events", True)),
                                                  store=bool(body.get("store", True))))

    async def retention(self, request: web.Request) -> web.Response:
        return _ok(await self._api.retention_plan())

    async def maintain(self, request: web.Request) -> web.Response:
        api = await self._supervised()
        return _ok(await api.maintain())


#: Key the composed routes are stored under on the aiohttp application, so a test or
#: another component can reach the facade without recomposing it.
TESTLAB_APP_KEY: web.AppKey[TestLabRoutes] = web.AppKey("jarvis_testlab_api", TestLabRoutes)


# ------------------------------------------------------------------ helpers

def _ok(payload: Mapping[str, Any], *, status: int = 200) -> web.Response:
    return web.json_response({"ok": True, **payload}, status=status)


async def _body(request: web.Request, *, optional: bool = False) -> dict[str, Any]:
    """The JSON object of a request, bounded. An empty body is `{}` only where allowed.

    `request.read()` and not `request.content.read(n)`: the latter returns what happens to
    be buffered, so a body larger than one chunk came back truncated and was reported as
    malformed JSON — which refused a legitimate sweep spec and told the caller the wrong
    thing about why.
    """
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        raise TestLabHttpError(HTTP_TOO_LARGE,
                               f"the request body is {request.content_length} bytes; the limit is "
                               f"{MAX_BODY_BYTES}")
    try:
        raw = await request.read()
    except web.HTTPRequestEntityTooLarge:
        raise TestLabHttpError(HTTP_TOO_LARGE,
                               f"the request body is larger than this server accepts (limit "
                               f"{MAX_BODY_BYTES} bytes for the Test Lab)") from None
    if len(raw) > MAX_BODY_BYTES:
        raise TestLabHttpError(HTTP_TOO_LARGE,
                               f"the request body is {len(raw)} bytes; the limit is {MAX_BODY_BYTES}")
    if not raw:
        if optional:
            return {}
        raise TestLabHttpError(HTTP_INVALID, "this route needs a JSON object body")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise TestLabHttpError(HTTP_INVALID, "the request body is not UTF-8 JSON") from None
    if not isinstance(payload, dict):
        raise TestLabHttpError(HTTP_INVALID, "the request body must be a JSON object")
    return payload


def _required(body: Mapping[str, Any], name: str) -> Any:
    value = body.get(name)
    if value is None:
        raise TestLabHttpError(HTTP_INVALID, f"{name} is required")
    return value


def _grant(payload: Any) -> ResourceGrant | None:
    """A grant a caller ASKS for. It is intersected with the environment's by the facade."""
    return None if payload is None else ResourceGrant.from_dict(payload)


def _int_query(request: web.Request, name: str) -> int | None:
    raw = request.query.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        raise TestLabHttpError(HTTP_INVALID, f"{name} must be an integer") from None


def _float_query(request: web.Request, name: str) -> float | None:
    raw = request.query.get(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        raise TestLabHttpError(HTTP_INVALID, f"{name} must be a number") from None


def install_testlab_routes(app: web.Application, *, runtime_root: Path | str | None = None,
                           data_root: Path | str | None = None, journal: DiagnosticSink | None = None,
                           lab: TestLab | None = None) -> TestLabRoutes:
    """Register `/api/testlab/...` on an existing aiohttp application, and own their lifecycle.

    This is the whole integration: one call from `ControlCenter.__init__`. Composition is
    lazy (no directory is created and no catalog is read here), the supervisor is started
    by the first request that needs it, and `on_cleanup` stops every worker it started.
    """
    api = TestLabApi(lab if lab is not None else build_test_lab(
        runtime_root=runtime_root, data_root=data_root, diagnostics=journal))
    routes = TestLabRoutes(api, diagnostics=journal)
    app.add_routes(routes.routes())
    app[TESTLAB_APP_KEY] = routes

    async def _close(_: web.Application) -> None:
        await routes.aclose()

    app.on_cleanup.append(_close)
    return routes
