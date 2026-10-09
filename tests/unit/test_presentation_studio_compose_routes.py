"""Routes Core, client type et relais Control Center de la comparaison et de la composition (jarvis-interactive-presentation-studio, Slice 19).

Vrai Core (`JarvisCoreApplication`) derriere le vrai `LocalProtocolServer`, vrai Control Center devant lui : statuts et codes de chaque
operation, enveloppe d'une composition refusee (`error.conflicts`), acteur force a `user` pour la composition, garde d'origine, journal
sans contenu, parite route / relais / documentation. Contrat : `docs/presentation-studio.md` > *Comparison and semantic composition contract*.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.protocol.client import CoreProtocolError
from jarvis.protocol.presentation_studio_compose_routes import PresentationStudioComposeRoutes
from jarvis.protocol.presentation_studio_routes import PREFIX
from jarvis.runtime.presentation_studio_compose_relay import PresentationStudioComposeRelayRoutes
from jarvis.runtime.presentation_studio_relay import STUDIO_ROUTE
from tests.fakes import presentation_studio_art_direction as fx
from tests.unit.test_presentation_studio_edit_routes import S1, S2, new_presentation
from tests.unit.test_presentation_studio_routes import Core

RELAY = STUDIO_ROUTE
ROOT = Path(__file__).resolve().parents[2]
COMPARE_OPS = ("select", "pair", "mode", "navigate", "links", "links/remove", "clear")


async def branch(core, pid, title="Branche", **extra):
    status, answer = await core.call("POST", f"/{pid}/variants", json={"title": title, **extra})
    assert status == 201, answer
    return answer["variant"]["variant_id"]


async def give_art(core, pid, vid):
    _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
    status, art = await core.call("POST", f"/{pid}/variants/{vid}/art-direction",
                                  json={"expected_variant_revision": variant["revision"], "profile": fx.base_dict()})
    assert status == 201, art


# ------------------------------------------------------------------ table et parite

def test_the_route_table_of_compare_and_composition_and_its_relay_surface():
    routes = [(r.method, r.path) for r in PresentationStudioComposeRoutes(object()).routes()]
    base = PREFIX + "/{presentation_id}"
    assert routes == [("GET", base + "/compare"), *(("POST", base + "/compare/" + op) for op in COMPARE_OPS),
                      ("POST", base + "/compositions/plan"), ("POST", base + "/compositions"),
                      ("GET", base + "/variants/{variant_id}/composition")]
    relay = PresentationStudioComposeRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    mapped = [(r.method, "/v1/presentation-studio" + r.path[len("/api/presentation-studio"):]) for r in relay.routes()]
    assert sorted(mapped) == sorted(routes), "the page reaches exactly the compare and composition operations"
    assert set(vars(relay)) == {"_transport", "_journal"}  # no state in the Control Center


def test_every_route_is_in_the_docs_and_the_docs_name_no_other():
    page = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
    section = page[page.index("## Comparison and semantic composition contract"):]
    documented = set(re.findall(r"`(?:GET|POST) /v1/presentation-studio/presentations/\{presentation_id\}(/(?:compare|compositions|variants/\{variant_id\}/composition)[a-z/]*)`", section))
    registered = {path[len(PREFIX + "/{presentation_id}"):] for _, path in
                  ((r.method, r.path) for r in PresentationStudioComposeRoutes(object()).routes())}
    assert documented == registered, (sorted(documented ^ registered))


def contract() -> str:
    page = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
    start = page.index("## Comparison and semantic composition contract")
    return page[start:page.index("## Reused owners (do not rebuild)")]


def test_the_documented_codes_limits_conflicts_and_client_methods_are_the_enforced_ones():
    from jarvis.core import presentation_studio_compare as service
    from jarvis.domain import presentation_studio as ps
    from jarvis.domain import presentation_studio_compare as pc
    from jarvis.domain import presentation_studio_composition as pk
    from jarvis.domain.presentation_studio import PresentationStudioErrorCode as C
    from jarvis.domain.presentation_studio_variants import MAX_SOURCES
    from jarvis.protocol.client import LocalCoreClient

    page = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
    text = contract()
    for code in (C.COMPARE_MAPPING_CONFLICT, C.COMPOSITION_REFUSED, C.UNKNOWN_COMPOSITION):
        assert f"`{code.value}` | {ps.HTTP_STATUS[code]} |" in page, code
        assert code.value in text, code
    assert all(f"`{c.value}`" in text for c in pk.ConflictCode), "every conflict code is documented"
    assert pc.MAX_LINKS == 64 and "| manual links per set | 64 |" in text and service.MAX_TRACKED == 16 and "16 Presentations" in text
    assert pk.MAX_SEGMENTS == 4 and pk.MAX_SCENES == 64 and MAX_SOURCES == 4 and pk.MAX_USER_RATIONALE == 400 and "400 characters" in text
    assert pc.COMPARE_SIZES == (2, 4) and pc.MODES == ("sync", "independent") and pc.STEPS == ("next", "previous", "first", "last")
    assert pk.DIMENSIONS == ("scenes", "narrative", "motion", "art_direction")
    for name in ("compare", "compare_op", "composition_plan", "compose", "composition"):
        assert callable(getattr(LocalCoreClient, f"presentation_studio_{name}")), name
    assert "presentation_studio_{compare,compare_op,composition_plan,compose,composition}" in text
    assert "**implemented (Level 3, backend)**" in page


# ------------------------------------------------------------------ Core

async def test_compare_over_http_select_navigate_pair_link_and_clear(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        b, c, d = [await branch(core, pid, name) for name in ("B", "C", "D")]
        status, empty = await core.call("GET", f"/{pid}/compare")
        assert status == 200 and empty["active"] is False and empty["layout"] == "empty"
        status, view = await core.call("POST", f"/{pid}/compare/select", json={"variant_ids": [root, b]})
        assert status == 200 and view["layout"] == "two_up" and view["revision"] == 1
        status, view = await core.call("POST", f"/{pid}/compare/select", json={"variant_ids": [root, b, c, d], "expected_revision": 1})
        assert status == 200 and view["layout"] == "four_up"
        status, view = await core.call("POST", f"/{pid}/compare/pair", json={"pair": [b, c]})
        assert status == 200 and view["layout"] == "focus" and view["shown"] == [b, c]
        status, view = await core.call("POST", f"/{pid}/compare/navigate", json={"variant_id": root, "scene_id": S2})
        assert status == 200 and view["navigation"]["results"][b] == {"scene_id": S2, "status": "synced"}
        status, view = await core.call("POST", f"/{pid}/compare/mode", json={"mode": "independent"})
        assert status == 200 and view["mode"] == "independent"
        status, view = await core.call("POST", f"/{pid}/compare/links", json={"a": {"variant_id": root, "scene_id": S1}, "b": {"variant_id": b, "scene_id": S2}})
        assert status == 409 and view["error"]["code"] == "presentation_studio_compare_mapping_conflict"
        status, cleared = await core.call("POST", f"/{pid}/compare/clear")  # no body at all
        assert status == 200 and cleared["cleared"] is True and (await core.call("GET", f"/{pid}/compare"))[1]["active"] is False


async def test_every_refusal_is_a_coded_envelope_with_its_status(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        b = await branch(core, pid, "B")

        async def code(method, path, **kw):
            status, payload = await core.call(method, path, **kw)
            assert set(payload) == {"error"}, payload
            return status, payload["error"]["code"]

        assert await code("POST", f"/{pid}/compare/select", json={"variant_ids": [root]}) == (400, "presentation_studio_invalid")
        assert await code("POST", f"/{pid}/compare/select", json={"variant_ids": [root, "psv_" + "0" * 32]}) == (404, "presentation_studio_unknown_variant")
        assert await code("POST", f"/pst_{'0' * 32}/compare/select", json={"variant_ids": [root, b]}) == (404, "presentation_studio_unknown_presentation")
        assert await code("POST", f"/{pid}/compare/select", data=b"nope") == (400, "invalid_request")
        assert await code("POST", f"/{pid}/compare/select?x=1", json={"variant_ids": [root, b]}) == (400, "invalid_request")
        assert await code("POST", f"/{pid}/compare/select", data=b"x" * (16 * 1024 + 10)) == (400, "invalid_request")
        assert await code("POST", f"/{pid}/compare/pair", json={"pair": None}) == (400, "presentation_studio_invalid")  # nothing open
        await core.call("POST", f"/{pid}/compare/select", json={"variant_ids": [root, b]})
        assert await code("POST", f"/{pid}/compare/select", json={"variant_ids": [root, b], "expected_revision": 5}) == (409, "presentation_studio_stale_revision")
        assert await code("POST", f"/{pid}/compare/navigate", json={"variant_id": root}) == (400, "presentation_studio_invalid")
        assert await code("POST", f"/{pid}/compositions", json={"title": "x"}) == (400, "presentation_studio_invalid")
        assert await code("POST", f"/{pid}/compositions", json={"title": "x", "base": root, "narrative": "psv_" + "0" * 32}) == (404, "presentation_studio_unknown_variant")
        assert await code("GET", f"/{pid}/variants/{b}/composition") == (404, "presentation_studio_unknown_composition")
        async with core.http.post(core.stack.core_url + PREFIX + f"/{pid}/compare/select", json={"variant_ids": [root, b]}) as response:
            assert response.status == 401  # the bearer token is required


async def test_a_refused_composition_carries_every_typed_conflict_in_the_error_envelope(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        b = await branch(core, pid, "B")
        status, refused = await core.call("POST", f"/{pid}/compositions", json={"title": "Mix", "base": root, "art_direction": b})
        assert status == 409 and set(refused) == {"error"}
        error = refused["error"]
        assert error["code"] == "presentation_studio_composition_refused" and "source_has_no_art_direction" in error["message"]
        assert [c["code"] for c in error["conflicts"]] == ["source_has_no_art_direction"]
        assert set(error["conflicts"][0]) == {"code", "dimension", "message", "fix", "details"} and error["conflicts"][0]["fix"]
        _, graph = await core.call("GET", f"/{pid}/graph")
        assert len(graph["nodes"]) == 2, "a refused composition created nothing"
        status, planned = await core.call("POST", f"/{pid}/compositions/plan", json={"title": "Mix", "base": root, "art_direction": b})
        assert status == 200 and planned["ok"] is False and planned["conflicts"] == error["conflicts"]


async def test_plan_then_compose_then_read_the_provenance_over_http_and_through_the_typed_client(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        await give_art(core, pid, root)
        b = await branch(core, pid, "B")
        client = core.client
        request = {"title": "Mix", "base": root, "art_direction": b, "scenes": [{"from": b, "scene_ids": [S2]}, {"from": root, "scene_ids": [S1]}],
                   "rationale": "le DA de B"}
        planned = await client.presentation_studio_composition_plan(pid, request)
        assert planned["ok"] is True and planned["composition"]["result"]["scene_ids"] == [S2, S1]
        created = await client.presentation_studio_compose(pid, request)
        new = created["variant"]["variant_id"]
        assert created["node"]["sources"] == [root, b] and created["node"]["variant_number"] == 3 and created["composition"]["variant_id"] == new
        provenance = await client.presentation_studio_composition(pid, new)
        assert {k: v for k, v in created["composition"].items() if k != "result"} == provenance["composition"]
        assert [d["dimension"] for d in provenance["composition"]["dimensions"]] == ["scenes", "narrative", "motion", "art_direction"]
        assert (await client.presentation_studio_graph(pid))["nodes"][-1]["sources"] == [root, b]
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_compose(pid, {"title": "Mix", "base": root, "motion": b})
        assert (caught.value.status, caught.value.code) == (409, "presentation_studio_composition_refused")
        assert caught.value.details["conflicts"][0]["code"] == "source_has_no_score" and caught.value.details["conflicts"][0]["dimension"] == "motion"
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_composition(pid, b)
        assert (caught.value.status, caught.value.code) == (404, "presentation_studio_unknown_composition")
        view = await client.presentation_studio_compare_op(pid, "select", {"variant_ids": [root, new]})
        assert view["layout"] == "two_up" and (await client.presentation_studio_compare(pid)) == view
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_compare_op(pid, "mode", {"mode": "both"})
        assert caught.value.status == 400


async def test_the_core_application_wires_both_services_to_the_studio_and_the_variant_graph(tmp_path):
    async with Core(tmp_path) as core:
        app = core.stack.core
        assert app.presentation_studio_compare._studio is app.presentation_studio
        assert app.presentation_studio_composition._variants is app.presentation_studio_variants
        pid, root, _ = await new_presentation(core)
        seen, traced = [], []
        app.conversation_event_emitter.add_listener(seen.append)
        real_trace = app.presentation_studio.trace
        app.presentation_studio.trace = lambda kind, message, **kw: (traced.append((kind, message, kw)), real_trace(kind, message, **kw))[1]
        b = await branch(core, pid, "B")
        status, created = await core.call("POST", f"/{pid}/compositions", json={"title": "Mix prive", "base": root, "scenes": b, "rationale": "Raison privee"})
        assert status == 201
        events = [dict(e.attributes) for e in seen if e.event_type is T.SYSTEM_PRESENTATION_STUDIO_VARIANT_CHANGED]
        assert [e["op"] for e in events] == ["created", "created"] and all("prive" not in json.dumps(e) for e in events)
        rows = [r for r in traced if r[0].startswith("core.presentation_studio.composition")]
        assert [r[0] for r in rows] == ["core.presentation_studio.composition_created"]
        assert "prive" not in json.dumps(rows, default=str).lower().replace("privee", "")
        await app.conversation_event_emitter.stop()


# ------------------------------------------------------------------ relais

async def test_the_relay_forces_the_actor_to_user_for_a_composition_and_passes_the_comparison_through(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        b = await branch(core, pid, "B")
        call = core.stack.call
        status, created, _ = await call("POST", RELAY + f"/{pid}/compositions", json={"title": "Page", "base": root, "scenes": b, "actor": "brain"})
        assert status == 201 and created["node"]["created_by"] == "user"
        status, planned, _ = await call("POST", RELAY + f"/{pid}/compositions/plan", json={"title": "Page 2", "base": root, "actor": "brain"})
        assert status == 200 and planned["ok"] is True
        status, view, _ = await call("POST", RELAY + f"/{pid}/compare/select", json={"variant_ids": [root, b]})
        assert status == 200 and view["layout"] == "two_up"
        status, got, _ = await call("GET", RELAY + f"/{pid}/compare")
        assert status == 200 and got == (await core.call("GET", f"/{pid}/compare"))[1]
        status, refused, _ = await call("POST", RELAY + f"/{pid}/compare/select", json={"variant_ids": [root, b], "actor": "user"})
        assert status == 400, "the comparison has no actor: a body that names one is a bad body"
        new = created["variant"]["variant_id"]
        status, provenance, _ = await call("GET", RELAY + f"/{pid}/variants/{new}/composition")
        assert status == 200 and provenance["composition"]["created_by"] == "user"
        status, conflicts, _ = await call("POST", RELAY + f"/{pid}/compositions", json={"title": "Refus", "base": root, "art_direction": b})
        assert status == 409 and conflicts["error"]["conflicts"][0]["code"] == "source_has_no_art_direction", "the relay returns Core's envelope as is"
        rows = [e for e in core.stack.trace() if str(e.get("kind", "")).startswith("presentation_studio.request")]
        assert any(r["data"]["action"] == "studio_composition_create" and r["data"]["code"] == "presentation_studio_composition_refused" for r in rows)


@pytest.mark.parametrize("headers", [{"Origin": "null"}, {"Origin": "https://evil.example"},
                                     {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"}])
async def test_a_frame_or_a_foreign_origin_cannot_touch_the_comparison_or_the_composition(tmp_path, headers):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        b = await branch(core, pid, "B")
        status, payload, _ = await core.stack.call("GET", RELAY + f"/{pid}/compare", headers=headers)
        assert status == 403 and payload["code"] == "forbidden_origin"
        for path in (*(f"/{pid}/compare/{op}" for op in COMPARE_OPS), f"/{pid}/compositions", f"/{pid}/compositions/plan"):
            status, _, _ = await core.stack.call("POST", RELAY + path, headers=headers, json={"title": "x", "base": root})
            assert status == 403, path
        _, graph = await core.call("GET", f"/{pid}/graph")
        assert len(graph["nodes"]) == 2


async def test_the_relay_rejects_malformed_bodies_and_exposes_no_other_write(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        call = core.stack.call
        for method, path in (("PUT", f"/{pid}/compare"), ("DELETE", f"/{pid}/compare"), ("GET", f"/{pid}/compare/select"),
                             ("PUT", f"/{pid}/compositions"), ("GET", f"/{pid}/compositions"), ("POST", f"/{pid}/variants/{root}/composition")):
            status, _, _ = await call(method, RELAY + path, json={})
            assert status in (404, 405), (method, path, status)
        status, payload, _ = await call("POST", RELAY + f"/{pid}/compositions", data=b"[1]")
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await call("POST", RELAY + f"/{pid}/compositions?x=1", json={"title": "x", "base": root})
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await call("POST", RELAY + f"/{pid}/compositions", json={"title": "x", "base": root, "number": 3})
        assert (status, payload["error"]["code"]) == (400, "presentation_studio_invalid")


async def test_the_relay_journal_never_holds_a_title_or_a_rationale(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        status, _, _ = await core.stack.call("POST", RELAY + f"/{pid}/compositions", json={"title": "Titre secret", "base": root, "rationale": "Raison secrete"})
        assert status == 201
        assert "secret" not in json.dumps(core.stack.trace())
