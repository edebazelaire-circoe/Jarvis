"""Human-only engine control (handoff jarvis-remotion-presentation-integration, Slice 20; `docs/presentation-engine.md` > Human engine control).

Real Core behind the real protocol server, and the REAL Control Center in front of it (the relay is the only door that names an
engine). Negative cases first: an agent, a script, a forged body, a system caller cannot pick an engine; an existing presentation
never switches; Slidecar needs the explicit confirmation; every Slidecar creation / use is journaled.
"""

from __future__ import annotations

import json
from pathlib import Path
import socket

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.core.presentation_studio_engine_choice import MAX_EVENTS, SlidecarLedger
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.presentation_studio_engine_request import experiment_title, parse_create_request
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.core_sessions import CoreSessionTransport
from tests.fakes.fake_sealer import FakeSealer

TOKEN = "k" * 48
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PREFIX = "/v1/presentation-studio/presentations"
CC = "/api/presentation-studio/presentations"


class Sink:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def emit(self, kind, message, *, level="info", data=None, **_):
        self.rows.append({"kind": kind, "message": message, "level": level, "data": dict(data or {})})

    def of(self, suffix: str) -> list[dict]:
        return [row for row in self.rows if row["kind"].endswith(suffix)]


class World:
    """Real Core + real protocol server + real Control Center (relay) on free ports and a throwaway data root."""

    def __init__(self, tmp_path: Path, *, capability_runner=None) -> None:
        self.tmp_path = tmp_path
        self.sink = Sink()
        #: A scripted local-capability runner (Slice 04 host): the Core then has the REAL Remotion adapter wiring (compiler + sandbox
        #: listener) over a capability that is not installed, so the engine reports its real failure and the repair route works.
        self.capability_runner = capability_runner

    async def __aenter__(self) -> "World":
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.data = self.tmp_path / "data"
        extra = {}
        if self.capability_runner is not None:
            from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
            from jarvis.runtime.remotion_composition import remotion_factory
            from jarvis.runtime.remotion_sandbox_server import RemotionSandboxSettings
            with socket.socket() as sock:
                sock.bind(("127.77.0.2", 0))
                sandbox_port = sock.getsockname()[1]
            extra = {"local_capability_runner": self.capability_runner,
                     "local_capability_store": FileLocalCapabilityStore(self.data.resolve()),
                     "remotion": remotion_factory(RemotionSandboxSettings("127.77.0.2", sandbox_port, "http://127.0.0.1:1"))}
        self.core = JarvisCoreApplication(data_root=self.data, sealer=FakeSealer(), diagnostics=self.sink, **extra)
        await self.core.start()
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=self.port, token=TOKEN)
        await self.server.start()
        token_file = self.tmp_path / "core.token"
        token_file.write_text(TOKEN, encoding="utf-8")
        self.sessions = CoreSessionTransport(host="127.0.0.1", port=self.port, token_file=token_file)
        runtime = self.tmp_path / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        self.center = ControlCenter(runtime_root=runtime, project_root=self.tmp_path)
        self.center.sessions = self.sessions
        self.cc = TestClient(TestServer(self.center._app))
        await self.cc.start_server()
        import aiohttp
        self.http = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.http.close()
        await self.cc.close()
        await self.sessions.close()
        await self.server.stop()
        await self.core.stop()

    async def core_call(self, method: str, path: str, **kw):
        async with self.http.request(method, f"http://127.0.0.1:{self.port}{path}", headers=AUTH, **kw) as response:
            return response.status, await response.json(content_type=None)

    async def page(self, method: str, path: str, body=None):
        response = await self.cc.request(method, path, **({} if body is None else {"data": json.dumps(body)}))
        return response.status, await response.json(content_type=None)

    def manifest(self, presentation_id: str) -> Path:
        return self.data / "presentations" / presentation_id / "presentation.json"


# ------------------------------------------------------------------ the parser (pure)

def test_a_body_without_engine_or_actor_is_the_agent_shape_and_names_nothing():
    request = parse_create_request({"title": "A"})
    assert (request.requested, request.actor.value, request.confirmed) == (None, "agent", False)


def test_the_request_shape_is_closed():
    for bad in ({"title": "A", "owner": "x"}, {"title": "A", "experimental_confirmed": "yes"}, {"title": "A", "reason": "a\nb"},
                {"title": "A", "reason": "x" * 161}, {"title": "A", "engine": 3}, {"title": " A"}, {}):
        with pytest.raises(Exception) as caught:
            parse_create_request(bad)
        assert getattr(caught.value, "status", 400) in (400, 403), bad


def test_an_unknown_actor_fails_closed_with_the_selection_code():
    with pytest.raises(Exception) as caught:
        parse_create_request({"title": "A", "engine": "slidecar", "actor": "root"})
    assert caught.value.code.value == "presentation_studio_engine_selection_refused"


def test_the_experiment_title_is_bounded_and_marked():
    assert experiment_title("Plan") == "Plan (Slidecar)"
    assert len(experiment_title("x" * 80)) <= 80 and experiment_title("x" * 80).endswith("(Slidecar)")


def test_the_ledger_is_bounded_and_throttles_repeated_use():
    now = [0.0]
    ledger = SlidecarLedger(clock=lambda: now[0])
    for index in range(MAX_EVENTS + 20):
        ledger.add("slidecar_created", {"n": index})
    view = ledger.view()
    assert view["kept"] == MAX_EVENTS and view["total"] == MAX_EVENTS + 20 and view["events"][0]["n"] == MAX_EVENTS + 19
    assert ledger.should_note_use("p", "play") and not ledger.should_note_use("p", "play")
    assert ledger.should_note_use("p", "edit") and ledger.should_note_use("q", "play")
    now[0] = 61.0
    assert ledger.should_note_use("p", "play")


# ------------------------------------------------------------------ Core: who may name an engine

async def test_a_plain_create_is_remotion_and_the_listing_says_so(tmp_path):
    async with World(tmp_path) as w:
        status, created = await w.core_call("POST", PREFIX, json={"title": "Plan"})
        assert (status, created["presentation"]["engine"]) == (201, "remotion")
        _, listing = await w.core_call("GET", PREFIX)
        assert [row["engine"] for row in listing["presentations"]] == ["remotion"]
        assert w.sink.of(".slidecar_created") == []


@pytest.mark.parametrize("body", [
    {"title": "A", "engine": "slidecar"},                                                   # a script naming Slidecar, no actor
    {"title": "A", "engine": "slidecar", "actor": "brain", "experimental_confirmed": True},  # the brain, confirmed anyway
    {"title": "A", "engine": "remotion", "actor": "brain"},                                  # even the default is not the agent's to name
    {"title": "A", "engine": "slidecar", "actor": "system", "experimental_confirmed": True},
    {"title": "A", "engine": "slidecar", "actor": "root", "experimental_confirmed": True},   # forged actor value
])
async def test_only_the_user_actor_can_name_an_engine_everyone_else_is_refused_403_and_nothing_is_stored(tmp_path, body):
    async with World(tmp_path) as w:
        status, answer = await w.core_call("POST", PREFIX, json=body)
        assert (status, answer["error"]["code"]) == (403, "presentation_studio_engine_selection_refused")
        _, listing = await w.core_call("GET", PREFIX)
        assert listing["presentations"] == []
        assert w.sink.of(".slidecar_created") == []
        assert w.sink.of(".engine_selection_refused")[0]["level"] == "warning"


async def test_the_brain_actor_without_an_engine_still_gets_remotion(tmp_path):
    async with World(tmp_path) as w:
        status, answer = await w.core_call("POST", PREFIX, json={"title": "A", "actor": "brain"})
        assert (status, answer["presentation"]["engine"]) == (201, "remotion")


async def test_slidecar_needs_the_explicit_confirmation_even_from_the_user(tmp_path):
    async with World(tmp_path) as w:
        status, answer = await w.core_call("POST", PREFIX, json={"title": "A", "engine": "slidecar", "actor": "user"})
        assert status == 400 and "experimental" in answer["error"]["message"]
        assert (await w.core_call("GET", PREFIX))[1]["presentations"] == []


async def test_an_unknown_engine_name_is_refused_with_the_allowed_values(tmp_path):
    async with World(tmp_path) as w:
        status, answer = await w.core_call("POST", PREFIX, json={"title": "A", "engine": "sidecar", "actor": "user"})
        assert status == 400 and "slidecar" in answer["error"]["message"] and "remotion" in answer["error"]["message"]


async def test_the_user_can_pick_remotion_without_confirmation_and_slidecar_with_it_and_slidecar_is_journaled(tmp_path):
    async with World(tmp_path) as w:
        status, plain = await w.core_call("POST", PREFIX, json={"title": "R", "engine": "remotion", "actor": "user"})
        assert (status, plain["presentation"]["engine"]) == (201, "remotion")
        assert w.sink.of(".slidecar_created") == []
        status, made = await w.core_call("POST", PREFIX, json={"title": "S", "engine": "slidecar", "actor": "user",
                                                               "experimental_confirmed": True, "reason": "comparer le rendu"})
        assert (status, made["presentation"]["engine"]) == (201, "slidecar")
        pid = made["presentation"]["presentation_id"]
        assert json.loads(w.manifest(pid).read_text(encoding="utf-8"))["engine"] == "slidecar"
        [event] = w.sink.of(".slidecar_created")
        assert event["data"] == {"engine": "slidecar", "presentation_id": pid, "actor": "human", "reason": "comparer le rendu",
                                 "at": event["data"]["at"]} and event["level"] == "info"
        _, overview = await w.core_call("GET", "/v1/presentation-studio/engine")
        assert overview["default_engine"] == "remotion" and overview["experimental"] == ["slidecar"]
        assert overview["slidecar"]["events"][0]["kind"] == "slidecar_created" and overview["slidecar"]["durable"] is False
        _, listing = await w.core_call("GET", PREFIX)
        assert sorted(row["engine"] for row in listing["presentations"]) == ["remotion", "slidecar"]


async def test_a_default_reason_is_recorded_when_the_user_gave_none(tmp_path):
    async with World(tmp_path) as w:
        await w.core_call("POST", PREFIX, json={"title": "S", "engine": "slidecar", "actor": "user", "experimental_confirmed": True})
        assert w.sink.of(".slidecar_created")[0]["data"]["reason"]


# ------------------------------------------------------------------ immutability and forged engine fields elsewhere

async def test_an_existing_presentation_never_switches_engine_through_any_write_route(tmp_path):
    async with World(tmp_path) as w:
        _, made = await w.core_call("POST", PREFIX, json={"title": "A"})
        pid, variant = made["presentation"]["presentation_id"], made["variants"][0]
        before = w.manifest(pid).read_bytes()
        presentation = {"expected_revision": made["presentation"]["revision"], "title": "A", "active_variant_id": variant["variant_id"],
                        "resources": []}
        status, answer = await w.core_call("PUT", f"{PREFIX}/{pid}", json={**presentation, "engine": "slidecar"})
        assert status == 400 and "engine" in answer["error"]["message"]
        status, _ = await w.core_call("PUT", f"{PREFIX}/{pid}/variants/{variant['variant_id']}",
                                      json={"expected_revision": variant["revision"], "title": "A", "scenes": [],
                                            "art_direction_id": None, "score_id": None, "engine": "slidecar"})
        assert status == 400
        status, _ = await w.core_call("POST", f"{PREFIX}/{pid}/variants/{variant['variant_id']}/edits",
                                      json={"actor": "user", "mode": "commit", "basis": {"variant_revision": 1}, "ops": [],
                                            "engine": "slidecar"})
        assert status == 400
        assert w.manifest(pid).read_bytes() == before


async def test_the_experiment_is_a_new_document_and_the_source_is_untouched(tmp_path):
    async with World(tmp_path) as w:
        _, made = await w.core_call("POST", PREFIX, json={"title": "Plan"})
        source = made["presentation"]["presentation_id"]
        before = w.manifest(source).read_bytes()
        status, copy = await w.core_call("POST", f"{PREFIX}/{source}/experiment",
                                         json={"actor": "user", "experimental_confirmed": True})
        assert status == 201 and copy["presentation"]["engine"] == "slidecar" and copy["presentation"]["title"] == "Plan (Slidecar)"
        assert copy["presentation"]["presentation_id"] != source and copy["variants"][0]["scenes"] == []
        assert w.manifest(source).read_bytes() == before
        [event] = w.sink.of(".slidecar_experiment_created")
        assert event["data"]["derived_from"] == source and event["data"]["source_engine"] == "remotion"
        assert event["data"]["actor"] == "human" and event["data"]["reason"]


@pytest.mark.parametrize("body, code", [
    ({"actor": "brain", "experimental_confirmed": True}, "presentation_studio_engine_selection_refused"),
    ({"actor": "system", "experimental_confirmed": True}, "presentation_studio_engine_selection_refused"),
    ({"experimental_confirmed": True}, "presentation_studio_invalid"),            # no actor key at all: the shape is incomplete
    ({"actor": "user", "experimental_confirmed": False}, "presentation_studio_invalid"),
    ({"actor": "user", "experimental_confirmed": True, "engine": "remotion"}, "presentation_studio_invalid"),  # no engine key here
])
async def test_the_experiment_refuses_everyone_but_a_confirmed_user(tmp_path, body, code):
    async with World(tmp_path) as w:
        _, made = await w.core_call("POST", PREFIX, json={"title": "Plan"})
        source = made["presentation"]["presentation_id"]
        status, answer = await w.core_call("POST", f"{PREFIX}/{source}/experiment", json=body)
        assert status in (400, 403) and answer["error"]["code"] == code
        assert len((await w.core_call("GET", PREFIX))[1]["presentations"]) == 1


async def test_the_experiment_of_an_unknown_presentation_is_a_404_and_stores_nothing(tmp_path):
    async with World(tmp_path) as w:
        status, answer = await w.core_call("POST", f"{PREFIX}/pst_000000000000/experiment",
                                           json={"actor": "user", "experimental_confirmed": True})
        assert status == 404 and answer["error"]["code"] == "presentation_studio_unknown_presentation"


# ------------------------------------------------------------------ the Control Center relay is the door (real chain)

async def test_the_page_cannot_forge_the_actor_the_relay_replaces_it(tmp_path):
    async with World(tmp_path) as w:
        # The page pretends to be the brain: the relay says `user` anyway, so this is the Human path.
        status, answer = await w.page("POST", CC, {"title": "S", "engine": "slidecar", "actor": "brain", "experimental_confirmed": True})
        assert (status, answer["presentation"]["engine"]) == (201, "slidecar")
        assert w.sink.of(".slidecar_created")[0]["data"]["actor"] == "human"


async def test_the_page_default_is_remotion_and_unconfirmed_slidecar_is_refused_through_the_relay(tmp_path):
    async with World(tmp_path) as w:
        status, answer = await w.page("POST", CC, {"title": "R"})
        assert (status, answer["presentation"]["engine"]) == (201, "remotion")
        status, answer = await w.page("POST", CC, {"title": "S", "engine": "slidecar"})
        assert status == 400 and answer["error"]["code"] == "presentation_studio_invalid"


async def test_the_relay_refuses_unknown_keys_and_non_objects_before_core_sees_them(tmp_path):
    async with World(tmp_path) as w:
        for body in ({"title": "A", "owner": "x"}, {"title": "A", "derived_from": "pst_000000000000"}, [1], "x"):
            status, answer = await w.page("POST", CC, body)
            assert status == 400 and answer["error"]["code"] == "invalid_request", body
        assert (await w.core_call("GET", PREFIX))[1]["presentations"] == []


async def test_the_page_experiment_route_forces_the_user_and_rejects_an_engine_key(tmp_path):
    async with World(tmp_path) as w:
        _, made = await w.page("POST", CC, {"title": "Plan"})
        source = made["presentation"]["presentation_id"]
        status, answer = await w.page("POST", f"{CC}/{source}/experiment", {"experimental_confirmed": True, "engine": "remotion"})
        assert status == 400 and answer["error"]["code"] == "invalid_request"
        status, copy = await w.page("POST", f"{CC}/{source}/experiment", {"experimental_confirmed": True, "actor": "brain"})
        assert status == 201 and copy["presentation"]["engine"] == "slidecar"


async def test_the_page_reads_the_engine_view_through_the_relay(tmp_path):
    async with World(tmp_path) as w:
        status, view = await w.page("GET", "/api/presentation-studio/engine")
        assert status == 200 and view["default_engine"] == "remotion" and set(view["engines"]) == {"slidecar", "remotion"}


async def test_the_brain_surface_cannot_reach_the_human_path():
    """No brain-facing module (MCP tools, brain adapter, tool brain) knows the confirmation flag or the experiment route."""

    root = Path(__file__).resolve().parents[2] / "jarvis"
    allowed = {"domain/presentation_studio_engine_request.py", "core/presentation_studio_engine_choice.py",
               "core/presentation_studio_service.py", "protocol/presentation_studio_routes.py", "runtime/presentation_studio_relay.py",
               "runtime/control_center_presentation_studio_engine.js"}
    holders = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.suffix in {".py", ".js", ".html"}
               and "experimental_confirmed" in path.read_text(encoding="utf-8", errors="ignore")}
    assert holders <= allowed, sorted(holders - allowed)
    assert "runtime/presentation_studio_relay.py" in holders and "core/presentation_studio_service.py" in holders


# ------------------------------------------------------------------ fail closed: the diagnosis and the repair door (real adapter wiring)

@pytest.mark.engine_gate
async def test_a_missing_remotion_runtime_is_reported_with_its_reason_and_nothing_plays_instead(tmp_path):
    from tests.unit.test_local_capability_host import FakeRunner
    async with World(tmp_path, capability_runner=FakeRunner()) as w:
        _, made = await w.core_call("POST", PREFIX, json={"title": "Plan"})
        pid = made["presentation"]["presentation_id"]
        _, view = await w.core_call("GET", "/v1/presentation-studio/engine")
        remotion = view["engines"]["remotion"]
        assert remotion["ready"] is False and remotion["reason"] and remotion["repair"]
        assert view["engines"]["slidecar"]["ready"] is True, "Slidecar is ready, and still never answers for Remotion"
        status, refused = await w.core_call("POST", f"/v1/presentation-studio/playback/start", json={"actor": "user", "presentation_id": pid, "role": "user_presenter"})
        assert status == 409 and refused["error"]["code"] == "presentation_studio_engine_unavailable"
        assert remotion["reason"] in refused["error"]["message"]
        assert w.sink.of(".slidecar_used") == [] and w.sink.of(".slidecar_created") == []


@pytest.mark.engine_gate
async def test_the_page_repairs_through_the_relay_and_the_engine_reports_the_real_failure_then_ready(tmp_path):
    from tests.unit.test_local_capability_host import FakeRunner
    runner = FakeRunner()
    async with World(tmp_path, capability_runner=runner) as w:
        status, cap = await w.page("GET", "/api/local-capabilities/remotion")
        assert status == 200 and cap["capability"]["status"] == "not_installed"
        runner.install_error = RuntimeError("npm ERR! network unreachable")
        status, failed = await w.page("POST", "/api/local-capabilities/remotion/install", {"force": True, "path": "C:/evil"})
        assert status == 200 and failed["capability"]["status"] == "install_failed"
        assert failed["capability"]["last_error_code"] == "local_capability_install_failed" and "network" in failed["capability"]["last_error_detail"]
        _, view = await w.page("GET", "/api/presentation-studio/engine")
        assert view["engines"]["remotion"]["ready"] is False, "a failed install never turns into a Slidecar answer"
        runner.install_error = None
        status, repaired = await w.page("POST", "/api/local-capabilities/remotion/repair")
        assert status == 200 and repaired["capability"]["status"] in {"ready", "running"}, repaired
        assert "install" in runner.calls and runner.calls.count("install") == 2
