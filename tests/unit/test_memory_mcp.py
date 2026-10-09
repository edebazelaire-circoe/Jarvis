"""Slice 05b : outils mémoire du cerveau (`jarvis-memory`).

Trois étages :

- Core (`BrainMemoryTools` + routes `/v1/memory/...`) sur la vraie pile `JarvisCoreApplication` : budget de 3 appels
  par tour (remis à zéro par le tour), portée du cerveau, `memory_propose` = un candidat `proposed` et rien d'autre,
  loadout de la connaissance ;
- le relais Control Center `/api/memory/brain/*` (table de routes, corps relayé) ;
- le serveur MCP : schémas fermés, chaque outil contre un faux Control Center, Core absent = erreur d'outil codée.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json

import aiohttp
import pytest
from aiohttp import web

from jarvis.core.memory_tools import MAX_TOOL_CALLS_PER_TURN
from jarvis.domain.knowledge import AssetHit, AssetKind, AssetScope, KnowledgeAsset, Loadout, SourceRef
from jarvis.domain.memory import (
    MemoryKind,
    MemoryLevel,
    MemoryNote,
    RetentionClass,
    new_memory_id,
)
from jarvis.domain.v2 import PROTOCOL_VERSION
from jarvis.runtime import mcp_catalog
from jarvis.runtime.memory_mcp import (
    SERVER_NAME,
    TOOL_NAMES,
    MemoryMcpTarget,
    MemoryToolError,
    MemoryTools,
    build_server,
    mcp_config,
)
from jarvis.runtime.memory_relay import MemoryBrainRelayRoutes
from tests.unit.test_memory_routes import CoreOverHttp, wiring_with_notes

T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
FIVE = {"memory_search", "memory_read", "memory_propose", "knowledge_search", "knowledge_read"}


# ------------------------------------------------------------------ Core


class FakeWiki:
    kind = AssetKind.WIKI

    def __init__(self) -> None:
        self.assets = {
            "allowed-page": self._asset("allowed-page", "Guide Atlas", "Atlas deploiement procedure " * 3),
            "secret-page": self._asset("secret-page", "Hors loadout", "Atlas secret"),
        }

    @staticmethod
    def _asset(asset_id: str, title: str, body: str) -> KnowledgeAsset:
        return KnowledgeAsset(asset_id=asset_id, kind=AssetKind.WIKI, title=title, scope=AssetScope.SHARED,
                              source=SourceRef(uri="file:///docs/x.md", version_or_commit="abc", fetched_at=T0),
                              body=body, version="2")

    def status(self):
        from jarvis.domain.memory import CapabilityState, CapabilityStatus

        return CapabilityState(CapabilityStatus.OK)

    def list(self, scope=None):
        return tuple(self.assets.values())

    def search(self, query, limit, scope=None):
        return [AssetHit(asset=a, snippet=a.title, score=1.0 - i / 10) for i, a in enumerate(self.assets.values())]

    def read(self, asset_id):
        return self.assets[asset_id]

    def rebuild(self):
        return len(self.assets)


class OneWikiLoadout:
    def resolve(self, profile, role=None):
        return Loadout(profile=profile, role=role, memory_scopes=("shared", "private"), allow_private=True,
                       wiki_ids=("allowed-page",))


async def post(http: CoreOverHttp, path: str, body: dict) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {http.token}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION)}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"http://127.0.0.1:{http.port}{path}", headers=headers, json=body) as response:
            return response.status, await response.json()


@pytest.fixture
async def served(tmp_path):
    wiring, notes = await wiring_with_notes(tmp_path)
    wiring.register_knowledge(FakeWiki())
    wiring.set_loadout_resolver(OneWikiLoadout())
    async with CoreOverHttp(tmp_path, wiring) as http:
        http.notes, http.wiring = notes, wiring  # type: ignore[attr-defined]
        yield http


async def test_search_gives_canonical_text_with_provenance_and_counts_the_budget(served):
    status, body = await served.get("/v1/memory/brain/search", q="budget Atlas")
    assert status == 200 and body["calls_left"] == MAX_TOOL_CALLS_PER_TURN - 1
    ids = [item["id"] for item in body["items"]]
    assert served.notes["budget"].id in ids and served.notes["old"].id not in ids  # superseded never offered
    first = next(item for item in body["items"] if item["id"] == served.notes["budget"].id)
    assert "42 000 euros" in first["text"] and first["source"] and first["revision"] == 1


async def test_the_fourth_call_of_a_turn_is_refused_with_the_stable_code_then_a_new_turn_resets_it(served):
    for _ in range(MAX_TOOL_CALLS_PER_TURN):
        assert (await served.get("/v1/memory/brain/search", q="budget Atlas"))[0] == 200
    status, body = await served.get("/v1/memory/brain/search", q="budget Atlas")
    assert status == 429 and body["error"]["code"] == "memory_tool_budget_exceeded"
    served.wiring.service.begin_turn()  # what MemoryTurnContext does for a user turn
    assert (await served.get("/v1/memory/brain/search", q="budget Atlas"))[0] == 200


async def test_a_user_turn_in_the_context_builder_resets_the_budget_but_a_system_turn_does_not(served):
    from jarvis.domain.v2 import BrainTurnInput, BrainTurnSource

    tools = served.wiring.tools
    for _ in range(MAX_TOOL_CALLS_PER_TURN):
        await tools.search("budget Atlas")
    assert tools.calls_left == 0
    system = BrainTurnInput(conversation_id="c", text="réveil", correlation_id="x", source=BrainTurnSource.SYSTEM)
    await served.wiring.context(system)
    assert tools.calls_left == 0
    user = BrainTurnInput(conversation_id="c", text="bonjour Atlas", correlation_id="y", source=BrainTurnSource.REALTIME)
    await served.wiring.context(user)
    assert tools.calls_left == MAX_TOOL_CALLS_PER_TURN


async def test_read_returns_the_note_and_the_budget_also_counts_reads(served):
    status, body = await served.get(f"/v1/memory/brain/notes/{served.notes['budget'].id}")
    assert status == 200 and "42 000 euros" in body["note"]["text"] and body["calls_left"] == 2
    status, body = await served.get("/v1/memory/brain/notes/..%2Fsecret")
    assert status in (400, 404)


async def test_read_refuses_a_scope_the_brain_policy_does_not_grant(tmp_path):
    from jarvis.core.memory_service import brain_policy

    wiring, notes = await wiring_with_notes(tmp_path)
    secret = wiring.store.create(MemoryNote(
        id=new_memory_id(), title="Hors portée", body="contenu d'un scope exclu", level=MemoryLevel.L1,
        kind=MemoryKind.FACT, retention=RetentionClass.LONG_TERM, scope="project:other", created_at=T0, updated_at=T0))
    assert not brain_policy().can_read(secret.scope)
    async with CoreOverHttp(tmp_path, wiring) as http:
        status, body = await http.get(f"/v1/memory/brain/notes/{secret.id}")
    assert status == 403 and body["error"]["code"] == "memory_scope_denied"
    assert "contenu d'un scope exclu" not in json.dumps(body)


async def test_propose_only_creates_a_proposed_candidate_never_a_note(served):
    before = [n.id for n in served.wiring.store.list(__import__("jarvis.domain.memory", fromlist=["MemoryFilters"]).MemoryFilters(limit=200))]
    status, body = await post(served, "/v1/memory/candidates", {
        "title": "Clarice aime le the vert", "body": "Dit le 7 octobre.", "kind": "preference", "confidence": 0.99})
    assert status == 201 and body["candidate"]["state"] == "proposed" and body["already_proposed"] is False
    assert body["candidate"]["confidence"] <= 0.6 and body["candidate"]["scope"] == "shared"
    candidate = served.wiring.tools._candidates.get(body["candidate"]["id"])
    assert candidate.state.value == "proposed" and candidate.committed_memory_id is None
    after = [n.id for n in served.wiring.store.list(__import__("jarvis.domain.memory", fromlist=["MemoryFilters"]).MemoryFilters(limit=200))]
    assert after == before  # no durable note was written
    status, again = await post(served, "/v1/memory/candidates", {
        "title": "Clarice aime le the vert", "body": "Dit le 7 octobre.", "kind": "preference"})
    assert status == 200 and again["already_proposed"] is True and again["candidate"]["id"] == body["candidate"]["id"]


@pytest.mark.parametrize("payload", [
    {"title": "x", "retention": "eternal_memory"},
    {"title": "x", "retention": "traumatic_memory"},
    {"title": "x", "state": "accepted"},
    {"title": "x", "kind": "nonsense"},
    {"title": "x", "confidence": "high"},
    {"body": "no title"},
])
async def test_propose_refuses_protected_classes_states_and_bad_shapes(served, payload):
    status, body = await post(served, "/v1/memory/candidates", payload)
    assert status == 400 and body["error"]["code"] == "invalid_request"
    assert len(served.wiring.tools._candidates.list()) == 0


async def test_propose_into_a_scope_the_brain_cannot_read_is_denied(served):
    status, body = await post(served, "/v1/memory/candidates", {"title": "x", "scope": "project:other"})
    assert status == 403 and body["error"]["code"] == "memory_scope_denied"


async def test_knowledge_is_limited_to_the_brain_loadout(served):
    status, body = await served.get("/v1/memory/brain/knowledge/search", q="Atlas")
    assert status == 200 and [hit["id"] for hit in body["hits"]] == ["allowed-page"]
    status, body = await served.get("/v1/memory/brain/knowledge/wiki/allowed-page")
    assert status == 200 and "deploiement" in body["asset"]["text"] and body["asset"]["version"] == "2"
    status, body = await served.get("/v1/memory/brain/knowledge/wiki/secret-page")
    assert status == 403 and body["error"]["code"] == "memory_scope_denied" and "secret" not in json.dumps(body["error"]).lower().replace("secret-page", "")
    served.wiring.service.begin_turn()
    status, body = await served.get("/v1/memory/brain/knowledge/skill/anything")
    assert status in (403, 503)  # not in the loadout, or no provider: never a read
    status, body = await served.get("/v1/memory/brain/knowledge/bogus/x")
    assert status == 400


async def test_the_diagnostics_never_carry_the_query_or_the_text(tmp_path):
    from tests.unit.test_memory_routes import Events

    wiring, _notes = await wiring_with_notes(tmp_path)
    events = Events()
    wiring.tools._diagnostics = events
    async with CoreOverHttp(tmp_path, wiring, events) as http:
        await http.get("/v1/memory/brain/search", q="budget Atlas zorblaxrouteword")
    assert any(kind == "core.memory.tool_called" for kind, _level, _data in events.events)
    assert "zorblax" not in json.dumps(events.events) and "42 000" not in json.dumps(events.events)


async def test_without_memory_the_tool_routes_answer_memory_unavailable(tmp_path):
    from jarvis.core.memory_wiring import MemoryWiring

    async with CoreOverHttp(tmp_path, MemoryWiring.absent()) as http:
        status, body = await http.get("/v1/memory/brain/search", q="budget")
    assert status == 503 and body["error"]["code"] == "memory_unavailable"


# ------------------------------------------------------------------ relais Control Center


def test_the_relay_maps_each_tool_to_its_core_route():
    class Silent:
        def emit(self, *a, **k): ...

    routes = MemoryBrainRelayRoutes(transport=lambda: None, journal=Silent()).routes()
    pairs = {(route.method, route.path) for route in routes}
    assert pairs == {
        ("GET", "/api/memory/brain/search"), ("GET", "/api/memory/brain/notes/{memory_id}"),
        ("POST", "/api/memory/brain/candidates"), ("GET", "/api/memory/brain/knowledge/search"),
        ("GET", "/api/memory/brain/knowledge/{kind}/{asset_id}")}


async def test_the_relay_forwards_the_proposal_body_and_params_to_core():
    class Silent:
        def emit(self, *a, **k): ...

    seen: list[tuple] = []

    class Transport:
        async def forward(self, method, path, *, params, body, timeout_s):
            seen.append((method, path, params, body))
            return 201, {"candidate": {"id": "c1"}}

    app = web.Application()
    app.add_routes(MemoryBrainRelayRoutes(transport=lambda: Transport(), journal=Silent()).routes())
    from aiohttp.test_utils import TestClient, TestServer

    client = TestClient(TestServer(app))
    await client.start_server()
    response = await client.post("/api/memory/brain/candidates", json={"title": "t"})
    assert response.status == 201
    response = await client.get("/api/memory/brain/notes/abc", params={"x": "1"})
    assert seen[0][:2] == ("POST", "/v1/memory/candidates") and json.loads(seen[0][3]) == {"title": "t"}
    await client.close()
    assert seen[1][:2] == ("GET", "/v1/memory/brain/notes/abc")


def test_the_control_center_guards_the_prefix_and_the_agent_receives_the_target():
    from jarvis.runtime.control_center import READ_GUARDED_ROUTES

    assert "/api/memory/brain" in READ_GUARDED_ROUTES


# ------------------------------------------------------------------ serveur MCP


class FakeControlCenter:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict, object]] = []
        self.answers: dict[tuple[str, str], tuple[int, object]] = {}
        self.runner = None
        self.port = 0

    async def start(self) -> None:
        async def handle(request: web.Request) -> web.Response:
            raw = await request.text()
            self.requests.append((request.method, request.path, dict(request.query), json.loads(raw) if raw else None))
            status, body = self.answers.get((request.method, request.path), (404, {"error": {"code": "x", "message": "x"}}))
            return web.json_response(body, status=status)

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001

    async def stop(self) -> None:
        await self.runner.cleanup()


@pytest.fixture
async def fake():
    cc = FakeControlCenter()
    await cc.start()
    tools = MemoryTools(MemoryMcpTarget("127.0.0.1", cc.port))
    yield cc, tools
    await tools.close()
    await cc.stop()


async def test_the_server_declares_exactly_the_five_tools_with_closed_schemas():
    server = build_server(tools=MemoryTools(MemoryMcpTarget("127.0.0.1", 1)))
    listed = {tool.name: tool for tool in await server.list_tools()}
    assert set(listed) == FIVE == set(TOOL_NAMES)
    assert all(tool.inputSchema["additionalProperties"] is False for tool in listed.values())
    assert listed["memory_propose"].inputSchema["required"] == ["title"]
    assert not any(name for name in listed if name.startswith(("board_", "session_")))
    props = listed["memory_propose"].inputSchema["properties"]
    assert "state" not in props and "id" not in props  # a proposal cannot choose a state or an id


async def test_the_catalog_knows_the_server_and_builds_it_inert():
    from jarvis.runtime.mcp_tool_meta import server_meta

    assert set(server_meta(SERVER_NAME).tools) == FIVE
    assert {tool.name for tool in await mcp_catalog.build_introspection_server(SERVER_NAME).list_tools()} == FIVE


ITEM = {"id": "n1", "title": "T", "text": "t", "level": "L1", "retention": "long_term_memory", "source": "s", "revision": 1,
        "why": "w"}
NOTE = {"id": "n1", "title": "T", "level": "L1", "kind": "fact", "retention": "long_term_memory", "scope": "shared",
        "revision": 1, "created_at": "a", "updated_at": "b", "valid_from": None, "valid_to": None, "confidence": 0.5,
        "agent": None, "superseded_by": None, "supersedes": [], "contradicts": [],
        "sources": [{"type": "turn", "ref": "r", "at": "a"}], "text": "t", "truncated": False}
CANDIDATE = {"id": "c1", "state": "proposed", "title": "T", "kind": "fact", "level": "L1",
             "retention": "long_term_memory", "scope": "shared", "confidence": 0.5}
HIT = {"id": "w", "kind": "wiki", "title": "T", "snippet": "s", "score": 1.0, "version": "1", "stale": False, "source": "u"}
ASSET = {"id": "w", "kind": "wiki", "title": "T", "version": "1", "stale": False, "confidence": None, "source": "u",
         "source_version": "abc", "text": "t", "truncated": False}


async def test_each_tool_calls_its_route_with_the_right_verb_and_shape(fake):
    cc, tools = fake
    cc.answers[("GET", "/api/memory/brain/search")] = (200, {"items": [ITEM], "degraded": [], "calls_left": 2, "extra": 1})
    cc.answers[("GET", "/api/memory/brain/notes/n1")] = (200, {"note": NOTE, "calls_left": 1})
    cc.answers[("POST", "/api/memory/brain/candidates")] = (201, {"candidate": CANDIDATE, "already_proposed": False, "calls_left": 0})
    cc.answers[("GET", "/api/memory/brain/knowledge/search")] = (200, {"hits": [HIT], "degraded": [], "calls_left": 2})
    cc.answers[("GET", "/api/memory/brain/knowledge/wiki/w")] = (200, {"asset": ASSET, "calls_left": 1})
    assert (await tools.memory_search("budget Atlas", limit=3))["items"] == [ITEM]
    assert (await tools.memory_read("n1"))["note"]["id"] == "n1"
    proposed = await tools.memory_propose("Un fait", body="détail", kind="fact")
    assert proposed["candidate"]["id"] == "c1" and "Memory Center" in proposed["note"]
    assert (await tools.knowledge_search("Atlas", kind="wiki"))["hits"] == [HIT]
    assert (await tools.knowledge_read("wiki", "w"))["asset"]["id"] == "w"
    verbs = [(m, p) for m, p, _q, _b in cc.requests]
    assert verbs == [("GET", "/api/memory/brain/search"), ("GET", "/api/memory/brain/notes/n1"),
                     ("POST", "/api/memory/brain/candidates"), ("GET", "/api/memory/brain/knowledge/search"),
                     ("GET", "/api/memory/brain/knowledge/wiki/w")]
    assert cc.requests[0][2] == {"q": "budget Atlas", "limit": "3"}
    assert cc.requests[2][3] == {"title": "Un fait", "body": "détail", "kind": "fact"}  # no origin, no state, no id


async def test_every_tool_result_passes_its_announced_output_schema_through_the_real_server(fake):
    """The MCP session validates the structured result against the announced schema (closed, extra fields refused)."""
    from mcp.shared.memory import create_connected_server_and_client_session

    cc, tools = fake
    cc.answers[("GET", "/api/memory/brain/search")] = (200, {"items": [ITEM], "degraded": ["recall_timeout"], "calls_left": 2})
    cc.answers[("GET", "/api/memory/brain/notes/n1")] = (200, {"note": NOTE, "calls_left": 1})
    cc.answers[("POST", "/api/memory/brain/candidates")] = (201, {"candidate": CANDIDATE, "already_proposed": True, "calls_left": 0})
    cc.answers[("GET", "/api/memory/brain/knowledge/search")] = (200, {"hits": [HIT], "degraded": [], "calls_left": 2})
    cc.answers[("GET", "/api/memory/brain/knowledge/wiki/w")] = (200, {"asset": ASSET, "calls_left": 1})
    async with create_connected_server_and_client_session(build_server(tools=tools)) as session:
        for name, args in (("memory_search", {"query": "budget"}), ("memory_read", {"memory_id": "n1"}),
                           ("memory_propose", {"title": "x"}), ("knowledge_search", {"query": "atlas"}),
                           ("knowledge_read", {"kind": "wiki", "asset_id": "w"})):
            result = await session.call_tool(name, args)
            assert not result.isError, (name, result.content)
            assert result.structuredContent
        refused = await session.call_tool("memory_propose", {"title": "x", "state": "accepted"})
        assert refused.isError  # unknown argument: refused before anything is sent
        assert len([r for r in cc.requests if r[0] == "POST"]) == 1


async def test_the_budget_refusal_reaches_the_brain_with_its_stable_code(fake):
    cc, tools = fake
    cc.answers[("GET", "/api/memory/brain/search")] = (429, {"error": {"code": "memory_tool_budget_exceeded",
                                                                       "message": "at most 3"}})
    with pytest.raises(MemoryToolError) as raised:
        await tools.memory_search("budget Atlas")
    assert "memory_tool_budget_exceeded" in str(raised.value)


async def test_core_down_is_a_clean_coded_tool_error(fake):
    cc, tools = fake
    cc.answers[("GET", "/api/memory/brain/search")] = (503, {"error": {"code": "core_unreachable", "message": "Core is unreachable"}})
    with pytest.raises(MemoryToolError) as raised:
        await tools.memory_search("budget Atlas")
    assert "core_unreachable" in str(raised.value)
    dead = MemoryTools(MemoryMcpTarget("127.0.0.1", 1))
    try:
        with pytest.raises(MemoryToolError) as raised:
            await dead.memory_read("n1")
        assert "control_center_unreachable" in str(raised.value)
    finally:
        await dead.close()


def test_the_config_names_the_module_and_the_target(tmp_path):
    config = mcp_config(MemoryMcpTarget("127.0.0.1", 4321, tmp_path), python="py")
    entry = config["mcpServers"][SERVER_NAME]
    assert entry["args"] == ["-m", "jarvis", "memory-mcp"] and "4321" in entry["env"].values()
    from jarvis.runtime.memory_mcp import write_mcp_config

    path = write_mcp_config(MemoryMcpTarget("127.0.0.1", 4321, tmp_path), tmp_path / "rt")
    assert json.loads(path.read_text(encoding="utf-8"))["mcpServers"][SERVER_NAME]["type"] == "stdio"
