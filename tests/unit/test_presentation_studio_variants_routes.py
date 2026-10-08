"""Routes Core, client typé et relais Control Center du graphe des variantes (jarvis-interactive-presentation-studio, Slice 16).

Vrai Core (`JarvisCoreApplication`) derrière le vrai `LocalProtocolServer`, vrai Control Center devant lui : statuts et codes
de chaque opération, jeton de confirmation obligatoire (y compris par le relais, qui refuse seul), acteur forcé à `user`,
garde d'origine, évènement canonique réel sans contenu, journal sans contenu, parité route/documentation.
Contrat : `docs/presentation-studio.md` › *Variant graph and operations contract*.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.protocol.client import CoreProtocolError
from jarvis.protocol.presentation_studio_routes import PREFIX
from jarvis.protocol.presentation_studio_variants_routes import PresentationStudioVariantsRoutes
from jarvis.runtime.presentation_studio_variants_relay import PresentationStudioVariantsRelayRoutes
from jarvis.runtime.presentation_studio_relay import STUDIO_ROUTE
from tests.unit.test_presentation_studio_edit_routes import S1, op_set, new_presentation, body as edit_body
from tests.unit.test_presentation_studio_routes import Core

RELAY = STUDIO_ROUTE
ROOT = Path(__file__).resolve().parents[2]
TAILS = ("activate", "rename", "archive-plan", "archive", "restore")


def vpath(pid, vid, tail=""):
    return f"/{pid}/variants/{vid}" + (f"/{tail}" if tail else "")


async def branch(core, pid, title="Branche", **extra):
    status, answer = await core.call("POST", f"/{pid}/variants", json={"title": title, **extra})
    assert status == 201, answer
    return answer


# ------------------------------------------------------------------ table et parité

def test_the_route_table_of_the_graph_and_its_relay_surface():
    routes = [(r.method, r.path) for r in PresentationStudioVariantsRoutes(object()).routes()]
    base = PREFIX + "/{presentation_id}"
    assert routes == [("GET", base + "/graph"), ("POST", base + "/variants"),
                      *(("POST", base + "/variants/{variant_id}/" + tail) for tail in TAILS)]
    relay = PresentationStudioVariantsRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    mapped = [(r.method, "/v1/presentation-studio" + r.path[len("/api/presentation-studio"):]) for r in relay.routes()]
    assert sorted(mapped) == sorted(routes), "the page reaches exactly the graph operations, each with a forced actor"
    assert set(vars(relay)) == {"_transport", "_journal"}  # no state in the Control Center


def test_every_route_of_the_graph_is_in_the_docs_and_the_docs_name_no_other():
    page = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
    section = page[page.index("## Variant graph and operations contract"):]
    for tail in ("/graph", "/variants`", *(f"/variants/{{variant_id}}/{t}" for t in TAILS)):
        assert tail in section, tail
    documented = set(re.findall(r"/v1/presentation-studio/presentations/\{presentation_id\}/(?:graph|variants(?:/\{variant_id\}/[a-z-]+)?)", section))
    registered = {path for _, path in ((r.method, r.path) for r in PresentationStudioVariantsRoutes(object()).routes())}
    assert {re.sub(r"^/v1/presentation-studio/presentations/\{presentation_id\}", "", p) for p in documented} >= \
           {re.sub(r"^/v1/presentation-studio/presentations/\{presentation_id\}", "", p) for p in registered}


# ------------------------------------------------------------------ Core

async def test_the_whole_lifecycle_over_http_with_status_and_codes(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        status, graph = await core.call("GET", f"/{pid}/graph")
        assert status == 200 and [n["variant_number"] for n in graph["nodes"]] == [1]
        two = await branch(core, pid, "Version sobre", rationale="moins de couleur", actor="brain")
        assert two["node"]["variant_number"] == 2 and two["node"]["created_by"] == "brain" and two["linked"][0]["status"] == "none"
        twoid = two["variant"]["variant_id"]
        three = (await branch(core, pid, "Troisieme", source_variant_id=twoid, activate=True))["variant"]["variant_id"]
        status, switched = await core.call("POST", vpath(pid, root, "activate"), json={})
        assert status == 200 and switched["changed"] and switched["active_variant_id"] == root
        status, same = await core.call("POST", vpath(pid, root, "activate"))  # no body at all
        assert status == 200 and same["changed"] is False
        status, renamed = await core.call("POST", vpath(pid, twoid, "rename"), json={"title": "Sobre v2"})
        assert status == 200 and renamed["title"] == "Sobre v2"
        status, planned = await core.call("POST", vpath(pid, twoid, "archive-plan"))
        assert status == 200 and planned["plan"]["count"] == 2 and planned["confirmation"].startswith("psk_")
        assert [row["variant_number"] for row in planned["plan"]["affected"]] == [2, 3]
        status, done = await core.call("POST", vpath(pid, twoid, "archive"), json={"confirmation": planned["confirmation"]})
        assert status == 200 and done["count"] == 2 and done["restorable"] is True
        status, graph = await core.call("GET", f"/{pid}/graph?archived=1")
        assert {n["variant_number"]: n["state"] for n in graph["nodes"]} == {1: "live", 2: "archived", 3: "archived"}
        status, checked = await core.call("GET", f"/{pid}/graph?check=1")
        assert status == 200 and checked["check"]["clean"] is True
        status, restored = await core.call("POST", vpath(pid, three, "restore"), json={})
        assert status == 200 and [r["variant_number"] for r in restored["restored"]] == [2, 3]
        status, listing = await core.call("GET", "")
        assert listing["presentations"][0]["variant_count"] == 3


async def test_every_refusal_is_a_coded_envelope_with_its_status(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        two = (await branch(core, pid, "Deux"))["variant"]["variant_id"]

        async def code(method, path, **kw):
            status, payload = await core.call(method, path, **kw)
            assert set(payload) == {"error"}, payload
            return status, payload["error"]["code"]

        assert await code("POST", f"/{pid}/variants", json={}) == (400, "presentation_studio_invalid")
        assert await code("POST", f"/{pid}/variants", json={"title": "x", "number": 9}) == (400, "presentation_studio_invalid")
        assert await code("POST", f"/{pid}/variants", json={"title": "x", "actor": "root"}) == (400, "presentation_studio_invalid")
        assert await code("POST", f"/{pid}/variants", json={"title": "x", "activate": "yes"}) == (400, "presentation_studio_invalid")
        assert await code("POST", f"/{pid}/variants", json={"title": "x", "rationale": "a\nb"}) == (400, "presentation_studio_invalid")
        assert await code("POST", f"/{pid}/variants", data=b"not json") == (400, "invalid_request")
        assert await code("POST", f"/{pid}/variants?x=1", json={"title": "x"}) == (400, "invalid_request")
        assert await code("POST", f"/{pid}/variants", data=b"x" * (16 * 1024 + 10)) == (400, "invalid_request")
        assert await code("POST", f"/{pid}/variants", json={"title": "x", "source_variant_id": "psv_" + "0" * 32}) == \
               (404, "presentation_studio_unknown_variant")
        assert await code("POST", f"/pst_{'0' * 32}/variants", json={"title": "x"}) == (404, "presentation_studio_unknown_presentation")
        assert await code("POST", vpath(pid, two, "rename"), json={"title": ""}) == (400, "presentation_studio_invalid")
        assert await code("POST", vpath(pid, "psv_" + "0" * 32, "activate")) == (404, "presentation_studio_unknown_variant")
        assert await code("POST", vpath(pid, two, "archive"), json={}) == (400, "presentation_studio_confirmation_required")
        assert await code("POST", vpath(pid, two, "archive"), json={"confirmation": "psk_1." + "a" * 64}) == \
               (409, "presentation_studio_confirmation_stale")
        assert await code("POST", vpath(pid, root, "archive"), json={"confirmation": "psk_1." + "a" * 64}) == \
               (409, "presentation_studio_active_variant_protected")
        assert await code("POST", vpath(pid, two, "restore")) == (409, "presentation_studio_not_archived")
        assert await code("GET", f"/{pid}/graph?archived=maybe") == (400, "invalid_request")
        assert await code("GET", f"/{pid}/graph?x=1") == (400, "invalid_request")
        async with core.http.post(core.stack.core_url + PREFIX + f"/{pid}/variants", json={"title": "x"}) as response:
            assert response.status == 401  # the bearer token is required


async def test_the_typed_client_covers_every_operation_and_raises_coded_errors(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        client = core.client
        two = (await client.presentation_studio_create_branch(pid, {"title": "Deux", "rationale": "essai"}))["variant"]["variant_id"]
        assert (await client.presentation_studio_activate(pid, two))["changed"] is True
        assert (await client.presentation_studio_rename(pid, two, {"title": "Deux bis"}))["title"] == "Deux bis"
        graph = await client.presentation_studio_graph(pid)
        assert graph["active_variant_id"] == two and [n["title"] for n in graph["nodes"]] == [graph["nodes"][0]["title"], "Deux bis"]
        planned = await client.presentation_studio_archive_plan(pid, root)
        assert planned["confirmation"] is None and planned["plan"]["blocked"] == "presentation_studio_active_variant_protected"
        planned = await client.presentation_studio_archive_plan(pid, two, {"activate_variant_id": root})
        done = await client.presentation_studio_archive(pid, two, {"confirmation": planned["confirmation"], "activate_variant_id": root})
        assert done["active_variant_id"] == root
        assert (await client.presentation_studio_graph(pid, archived=True))["archived_count"] == 1
        assert (await client.presentation_studio_restore(pid, two))["count"] == 1
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_archive(pid, two, {})
        assert (caught.value.status, caught.value.code) == (400, "presentation_studio_confirmation_required")
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_activate(pid, "psv_" + "0" * 32)
        assert caught.value.status == 404


async def test_the_core_application_wires_the_graph_service_to_the_history_and_the_emitter(tmp_path):
    async with Core(tmp_path) as core:
        app = core.stack.core
        assert app.presentation_studio_variants._history is app.presentation_studio_history
        assert app.presentation_studio_variants._studio is app.presentation_studio
        pid, root, revision = await new_presentation(core)
        two = (await branch(core, pid))["variant"]["variant_id"]
        await core.client.presentation_studio_activate(pid, two)
        await core.client.presentation_studio_edit(pid, two, edit_body(1, op_set(S1, "body", "Dans la deux")))
        assert (await app.presentation_studio_history.status(pid, two))["tracked"] is True
        await core.client.presentation_studio_activate(pid, root)
        plan = await core.client.presentation_studio_archive_plan(pid, two)
        await core.client.presentation_studio_archive(pid, two, {"confirmation": plan["confirmation"]})
        await core.client.presentation_studio_restore(pid, two)
        status = await app.presentation_studio_history.status(pid, two)
        assert status["tracked"] is False and status["reason"] == "variant_archived", "archiving dropped the undo ring"


async def test_the_canonical_event_names_ids_numbers_and_counts_never_a_title_or_a_reason(tmp_path):
    async with Core(tmp_path) as core:
        seen = []
        core.stack.core.conversation_event_emitter.add_listener(seen.append)
        pid, root, _ = await new_presentation(core)
        created = await branch(core, pid, "Titre prive", rationale="Raison privee", actor="brain")
        two = created["variant"]["variant_id"]
        await core.client.presentation_studio_rename(pid, two, {"title": "Autre titre prive"})
        plan = await core.client.presentation_studio_archive_plan(pid, two)
        await core.client.presentation_studio_archive(pid, two, {"confirmation": plan["confirmation"], "actor": "brain"})
        await core.client.presentation_studio_restore(pid, two)
        events = [e for e in seen if e.event_type is T.SYSTEM_PRESENTATION_STUDIO_VARIANT_CHANGED]
        assert [dict(e.attributes)["op"] for e in events] == ["created", "renamed", "archived", "restored"]
        assert [dict(e.attributes)["source"] for e in events] == ["brain", "user", "brain", "user"]
        assert dict(events[2].attributes)["count"] == 1 and dict(events[0].attributes)["variant_number"] == 2
        assert all(e.content is None and "prive" not in repr(e) for e in events)
        await core.stack.core.conversation_event_emitter.stop()


# ------------------------------------------------------------------ relais

async def test_the_relay_forces_the_actor_to_user_whatever_the_page_says(tmp_path):
    async with Core(tmp_path) as core:
        seen = []
        core.stack.core.conversation_event_emitter.add_listener(seen.append)
        pid, root, _ = await new_presentation(core)
        call = core.stack.call
        status, created, _ = await call("POST", RELAY + f"/{pid}/variants", json={"title": "Page", "actor": "brain"})
        assert status == 201 and created["node"]["created_by"] == "user"
        two = created["variant"]["variant_id"]
        status, graph, _ = await call("GET", RELAY + f"/{pid}/graph")
        _, direct = await core.call("GET", f"/{pid}/graph")
        assert status == 200 and graph == direct
        for claimed in ("brain", "system", None):
            payload = {"title": "Renomme", "actor": claimed} if claimed else {"title": "Renomme sans acteur"}
            status, _, _ = await call("POST", RELAY + vpath(pid, two, "rename"), json=payload)
            assert status == 200
        status, planned, _ = await call("POST", RELAY + vpath(pid, two, "archive-plan"), json={"actor": "brain"})
        assert status == 200 and planned["confirmation"]
        status, done, _ = await call("POST", RELAY + vpath(pid, two, "archive"),
                                     json={"confirmation": planned["confirmation"], "actor": "brain"})
        assert status == 200
        status, _, _ = await call("POST", RELAY + vpath(pid, two, "restore"), json={"actor": "brain"})
        assert status == 200
        sources = {dict(e.attributes)["source"] for e in seen if e.event_type is T.SYSTEM_PRESENTATION_STUDIO_VARIANT_CHANGED}
        assert sources == {"user"}, sources


async def test_archiving_through_the_relay_without_a_confirmation_is_refused_by_the_relay_itself(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        two = (await branch(core, pid))["variant"]["variant_id"]
        calls = []
        real = core.stack.core.presentation_studio_variants.archive

        async def spy(*args, **kwargs):
            calls.append(args)
            return await real(*args, **kwargs)

        core.stack.core.presentation_studio_variants.archive = spy
        for payload in ({}, {"confirmation": ""}, {"confirmation": 7}, {"actor": "user"}):
            status, refused, _ = await core.stack.call("POST", RELAY + vpath(pid, two, "archive"), json=payload)
            assert status == 400 and refused["error"]["code"] == "presentation_studio_confirmation_required", payload
        assert calls == [], "the relay never forwarded a confirmation-less archive to Core"
        _, graph = await core.call("GET", f"/{pid}/graph")
        assert len(graph["nodes"]) == 2
        # a token that is no longer the plan's is stale at Core, through the relay too
        planned = (await core.stack.call("POST", RELAY + vpath(pid, two, "archive-plan")))[1]
        await branch(core, pid, "Ajout apres le plan", source_variant_id=two)
        status, stale, _ = await core.stack.call("POST", RELAY + vpath(pid, two, "archive"), json={"confirmation": planned["confirmation"]})
        assert status == 409 and stale["error"]["code"] == "presentation_studio_confirmation_stale" and len(calls) == 1
        rows = [e for e in core.stack.trace() if str(e.get("kind", "")).startswith("presentation_studio.request")]
        assert any(r["data"]["action"] == "studio_variant_archive" and r["data"]["code"] == "presentation_studio_confirmation_required" for r in rows)


@pytest.mark.parametrize("headers", [{"Origin": "null"}, {"Origin": "https://evil.example"},
                                     {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"}])
async def test_a_frame_or_a_foreign_origin_cannot_touch_the_graph(tmp_path, headers):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        two = (await branch(core, pid))["variant"]["variant_id"]
        status, payload, _ = await core.stack.call("GET", RELAY + f"/{pid}/graph", headers=headers)
        assert status == 403 and payload["code"] == "forbidden_origin"
        for path in (f"/{pid}/variants", *(vpath(pid, two, t) for t in TAILS)):
            status, _, _ = await core.stack.call("POST", RELAY + path, headers=headers, json={"title": "x", "confirmation": "x"})
            assert status == 403, path
        _, graph = await core.call("GET", f"/{pid}/graph")
        assert [n["title"] for n in graph["nodes"]][1] == "Branche"


async def test_the_relay_rejects_malformed_bodies_and_exposes_no_other_write(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        call = core.stack.call
        for method, path in (("PUT", f"/{pid}/graph"), ("DELETE", vpath(pid, root, "archive")), ("GET", vpath(pid, root, "archive")),
                             ("POST", f"/{pid}/graph")):
            status, _, _ = await call(method, RELAY + path, json={})
            assert status in (404, 405), (method, path, status)
        status, payload, _ = await call("POST", RELAY + f"/{pid}/variants", data=b"[1]")
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await call("POST", RELAY + f"/{pid}/variants?x=1", json={"title": "x"})
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await call("POST", RELAY + f"/{pid}/variants", json={"title": "x", "number": 3})
        assert (status, payload["error"]["code"]) == (400, "presentation_studio_invalid")


async def test_the_relay_journal_never_holds_a_title_or_a_rationale(tmp_path):
    async with Core(tmp_path) as core:
        pid, root, _ = await new_presentation(core)
        status, created, _ = await core.stack.call("POST", RELAY + f"/{pid}/variants",
                                                   json={"title": "Titre secret", "rationale": "Raison secrete"})
        assert status == 201
        rows = [e for e in core.stack.trace() if str(e.get("kind", "")).startswith("presentation_studio.request")]
        assert rows and rows[-1]["data"]["action"] == "studio_variant_create" and rows[-1]["data"]["status"] == 201
        assert "secret" not in json.dumps(core.stack.trace())
