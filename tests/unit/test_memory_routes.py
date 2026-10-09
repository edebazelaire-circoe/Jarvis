"""Routes Core `/v1/memory/*` : lecture seule de la mémoire à long terme (handoff jarvis-memory-intelligence-knowledge, Slice 05).

Contrat : `jarvis/protocol/memory_routes.py` (en-tête) et `docs/memory.md` › *Core routes*. Chaîne réelle :
`JarvisCoreApplication` (mémoire câblée par `build_memory_wiring`) → `LocalProtocolServer`, jeton porteur.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json

import aiohttp
import pytest

from jarvis.core.memory_wiring import MemoryWiring
from jarvis.runtime.memory_composition import build_default_memory_wiring as build_memory_wiring
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.memory import MemoryKind, MemoryLevel, MemoryNote, MemoryPatch, RetentionClass, new_memory_id
from jarvis.domain.v2 import PROTOCOL_VERSION
from jarvis.protocol.server import LocalProtocolServer
from tests.integration.test_scene_transport import free_port

T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
SECRET = "zorblaxrouteword"


def note(title: str, body: str, **over) -> MemoryNote:
    base = dict(id=new_memory_id(), title=title, body=body, level=MemoryLevel.L1, kind=MemoryKind.FACT,
                retention=RetentionClass.LONG_TERM, scope="private", created_at=T0, updated_at=T0)
    return MemoryNote(**{**base, **over})


class Events:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.events.append((kind, level, dict(data or {})))


class CoreOverHttp:
    def __init__(self, tmp_path, memory: MemoryWiring | None, diagnostics: Events | None = None) -> None:
        self.tmp_path, self.memory, self.diagnostics = tmp_path, memory, diagnostics or Events()
        self.port, self.token = free_port(), "7" * 48

    async def __aenter__(self) -> "CoreOverHttp":
        self.core = JarvisCoreApplication(data_root=self.tmp_path / "data", memory=self.memory, diagnostics=self.diagnostics)
        await self.core.start()
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=self.port, token=self.token)
        await self.server.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.server.stop()
        await self.core.stop()

    async def get(self, path: str, *, token: str | None = None, **params) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {token or self.token}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION)}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{self.port}{path}", headers=headers, params=params) as response:
                return response.status, await response.json()

    async def send(self, method: str, path: str) -> int:
        headers = {"Authorization": f"Bearer {self.token}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION)}
        async with aiohttp.ClientSession() as session:
            async with session.request(method, f"http://127.0.0.1:{self.port}{path}", headers=headers, json={}) as response:
                return response.status


async def wiring_with_notes(tmp_path) -> tuple[MemoryWiring, dict[str, MemoryNote]]:
    wiring = build_memory_wiring(tmp_path / "data", tmp_path / "settings.json")
    while not wiring.store.index_ready:
        await asyncio.sleep(0.01)
    notes = {
        "budget": wiring.store.create(note("Budget Atlas", f"Le budget du projet Atlas est de 42 000 euros. {SECRET}")),
        "pref": wiring.store.create(note("Préférence", "Clarice préfère les réponses courtes.", kind=MemoryKind.PREFERENCE,
                                         scope="shared")),
        "profile": wiring.store.create(note("Profil", "Parle français.", level=MemoryLevel.L3, kind=MemoryKind.PROFILE)),
    }
    old = wiring.store.create(note("Ancien budget", "Le budget Atlas était de 10 euros."))
    wiring.store.revise(old.id, MemoryPatch(superseded_by=notes["budget"].id), 1)
    notes["old"] = wiring.store.get(old.id)
    return wiring, notes


@pytest.fixture
async def served(tmp_path):
    wiring, notes = await wiring_with_notes(tmp_path)
    async with CoreOverHttp(tmp_path, wiring) as http:
        http.notes = notes  # type: ignore[attr-defined]
        yield http


async def test_the_list_gives_the_latest_revisions_with_an_excerpt_never_the_body(served):
    status, body = await served.get("/v1/memory/notes")
    assert status == 200 and body["derived"] is False
    titles = [entry["title"] for entry in body["notes"]]
    assert set(titles) == {"Budget Atlas", "Préférence", "Profil"}  # the superseded note is hidden by default
    first = body["notes"][0]
    assert "body" not in first and first["excerpt"] and first["level"] in {"L1", "L3"} and first["retention"] == "long_term_memory"


async def test_the_list_filters_by_scope_level_kind_and_can_include_superseded(served):
    assert [n["title"] for n in (await served.get("/v1/memory/notes", scope="shared"))[1]["notes"]] == ["Préférence"]
    assert [n["title"] for n in (await served.get("/v1/memory/notes", level="L3"))[1]["notes"]] == ["Profil"]
    assert [n["title"] for n in (await served.get("/v1/memory/notes", kind="preference"))[1]["notes"]] == ["Préférence"]
    status, body = await served.get("/v1/memory/notes", include_superseded="true")
    assert status == 200 and "Ancien budget" in [n["title"] for n in body["notes"]]
    status, body = await served.get("/v1/memory/notes", limit="1", offset="1")
    assert status == 200 and len(body["notes"]) == 1 and (body["limit"], body["offset"]) == (1, 1)


async def test_a_note_comes_whole_with_its_sources_links_and_revision(served):
    status, body = await served.get(f"/v1/memory/notes/{served.notes['budget'].id}")
    assert status == 200
    found = body["note"]
    assert found["body"].startswith("Le budget du projet Atlas") and found["revision"] == 1 and found["superseded_by"] is None
    status, body = await served.get(f"/v1/memory/notes/{served.notes['old'].id}")
    assert body["note"]["superseded_by"] == served.notes["budget"].id and body["note"]["revision"] == 2


async def test_an_unknown_note_is_a_coded_404(served):
    status, body = await served.get("/v1/memory/notes/inconnu")
    assert status == 404 and body["error"]["code"] == "memory_not_found"


async def test_search_is_lexical_ranked_and_labelled_derived(served):
    status, body = await served.get("/v1/memory/search", q="budget Atlas")
    assert status == 200 and body["derived"] is True and body["ranking"] == "lexical_bm25"
    assert {hit["title"] for hit in body["hits"]} >= {"Budget Atlas"}
    hit = body["hits"][0]
    assert set(hit) >= {"id", "title", "snippet", "score", "level", "retention", "scope", "revision"}
    assert (await served.get("/v1/memory/search", q="budget", scope="shared"))[1]["hits"] == []


async def test_recall_explain_shows_what_the_brain_would_get_and_why(served):
    status, body = await served.get("/v1/memory/recall-explain", q="budget du projet Atlas")
    assert status == 200 and body["degraded"] == [] and set(body["scopes"]) == {"private", "shared"}
    [item] = [entry for entry in body["items"] if entry["title"] == "Budget Atlas"]
    assert item["rank_sources"]["lexical"] == 1 and item["why"] and item["source"] == f"long_term_memory/{item['id']}"
    assert item["revision"] == 1 and "total" in body["timings_ms"] and body["budget"]["max_items"] == 6
    assert "Ancien budget" not in [entry["title"] for entry in body["items"]]  # superseded: never recalled


async def test_recall_explain_is_narrowed_by_the_brain_policy(served):
    status, body = await served.get("/v1/memory/recall-explain", q="budget Atlas", scope="board:autre")
    assert status == 200 and body["items"] == [] and body["scopes"] == []
    status, body = await served.get("/v1/memory/recall-explain", q="réponses courtes", scope="shared")
    assert [entry["title"] for entry in body["items"]] == ["Préférence"] and body["scopes"] == ["shared"]


async def test_status_gives_one_state_per_leg_with_code_and_reason(served):
    status, body = await served.get("/v1/memory/status")
    assert status == 200 and body["available"] is True and body["index_ready"] is True and body["recall_enabled"] is True
    assert body["legs"]["store"]["status"] == "ok" and body["legs"]["lexical"]["status"] == "ok"
    assert "semantic" not in body["legs"]  # no provider configured: no leg, not a fake "on"


async def test_candidates_are_empty_and_say_the_consolidation_is_not_there_yet(served):
    status, body = await served.get("/v1/memory/candidates")
    assert status == 200 and body == {"candidates": [], "available": False}


async def test_a_bad_query_is_a_400_and_is_journaled_without_the_query(tmp_path):
    wiring, _ = await wiring_with_notes(tmp_path)
    diagnostics = Events()
    async with CoreOverHttp(tmp_path, wiring, diagnostics) as http:
        assert (await http.get("/v1/memory/search"))[0] == 400
        assert (await http.get("/v1/memory/search", q="x", limite="3"))[0] == 400  # an unknown parameter
        assert (await http.get("/v1/memory/notes", level="L9"))[0] == 400
        assert (await http.get("/v1/memory/recall-explain", q=SECRET * 400))[0] == 400
        status, body = await http.get("/v1/memory/notes", scope=f"pas-une-portee-{SECRET}")
        assert status == 400 and body["error"]["code"] == "invalid_request"
    failed = [data for kind, _level, data in diagnostics.events if kind == "core.memory.read_failed"]
    assert len(failed) == 5 and {data["code"] for data in failed} == {"invalid_request"}
    assert SECRET not in json.dumps(diagnostics.events, default=str)


async def test_a_core_without_memory_answers_memory_unavailable(tmp_path):
    async with CoreOverHttp(tmp_path, None) as http:
        status, body = await http.get("/v1/memory/notes")
        assert status == 503 and body["error"]["code"] == "memory_unavailable"
        assert "memory_not_configured" in body["error"]["message"]
        status, body = await http.get("/v1/memory/status")
        assert status == 200 and body == {"available": False, "reason_code": "memory_not_configured", "legs": {}}


async def test_an_unreadable_root_is_a_503_with_its_code_and_core_stays_up(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "memory").write_text("a file", encoding="utf-8")
    wiring = build_memory_wiring(tmp_path / "data", tmp_path / "settings.json")
    async with CoreOverHttp(tmp_path, wiring) as http:
        status, body = await http.get("/v1/memory/search", q="atlas")
        assert status == 503 and body["error"]["code"] == "memory_unavailable"
        assert (await http.get("/v1/health"))[0] == 200


async def test_the_routes_need_the_core_token(served):
    status, body = await served.get("/v1/memory/notes", token="0" * 48)
    assert status == 401 and body["error"]["code"] == "unauthorized"


async def test_the_surface_is_read_only(served):
    for method, path in (("POST", "/v1/memory/notes"), ("PUT", f"/v1/memory/notes/{served.notes['budget'].id}"),
                         ("DELETE", f"/v1/memory/notes/{served.notes['budget'].id}")):
        assert await served.send(method, path) in {404, 405}, (method, path)
    status, body = await served.get(f"/v1/memory/notes/{served.notes['budget'].id}")
    assert status == 200 and body["note"]["revision"] == 1  # nothing changed


def test_every_registered_memory_route_is_a_get_but_the_candidate_proposal_and_is_documented():
    from pathlib import Path

    from jarvis.protocol.memory_routes import MemoryProtocolRoutes

    routes = MemoryProtocolRoutes(object()).routes()
    # Slice 05b: the one write is a candidate proposal (never a note); everything else reads.
    assert routes and {(route.method, route.path) for route in routes if route.method != "GET"} == {
        ("POST", "/v1/memory/candidates")}
    root = Path(__file__).resolve().parents[2]
    docs = (root / "docs" / "memory.md").read_text(encoding="utf-8") + (root / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    for route in routes:
        template = route.path
        assert template in docs, f"{template} is registered but cited in neither docs/memory.md nor docs/ARCHITECTURE.md"
