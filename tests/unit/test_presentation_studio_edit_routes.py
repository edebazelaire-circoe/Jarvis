"""Routes Core, client type et relais Control Center de l'API d'edition (jarvis-interactive-presentation-studio, Slice 05).

Vrai Core (`JarvisCoreApplication`) derriere le vrai `LocalProtocolServer`, vrai Control Center devant lui, prefab de base
`jarvis.window` : statuts et corps des trois issues (`applied`, `refused`, `stale`), client type, acteur force a `user` par
le relais (equivalence avec l'acteur `brain` direct), seules lectures + `.../edits` relayees, garde d'origine, panne de Core,
evenement canonique reel, parite route/documentation.
Contrat : `docs/presentation-studio.md` > *Semantic edit contract*.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.protocol import client as client_module
from jarvis.protocol.client import FORWARDABLE_PREFIXES, STUDIO_PREFIX, CoreProtocolError
from jarvis.protocol.presentation_studio_routes import PREFIX, PresentationStudioProtocolRoutes
from jarvis.runtime.control_center import READ_GUARDED_ROUTES
from jarvis.runtime.presentation_studio_relay import (
    CORE_PREFIX, GUARDED_PREFIXES, STUDIO_ROUTE, PresentationStudioRelayRoutes,
)
from tests.unit.test_presentation_studio_routes import Core, variant_body

S1, S2 = "pss_0000000000c1", "pss_0000000000c2"
RELAY = STUDIO_ROUTE


def scene(scene_id: str, **extra) -> dict:
    return {"scene_id": scene_id, "prefab": {"id": "jarvis.window", "version": 1}, "title": "Fenetre",
            "props": {"density": "compact"}, "data": {"body": "Texte"}, **extra}


CONTROLS = [{"control_id": "density", "path": "props.density", "label": "Densite", "group": "layout"},
            {"control_id": "body", "path": "data.body", "label": "Texte", "group": "content"}]


def op_set(scene_id, control_id, value, **extra):
    return {"op": "control.set", "scene_id": scene_id, "control_id": control_id, "value": value, **extra}


def body(revision, *ops, actor="brain", mode="commit") -> dict:
    return {"actor": actor, "mode": mode, "basis": {"variant_revision": revision}, "ops": list(ops)}


async def new_presentation(core: Core, title: str = "Atelier") -> tuple[str, str, int]:
    _, created = await core.call("POST", "", json={"title": title})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    vid = variant["variant_id"]
    status, saved = await core.call("PUT", f"/{pid}/variants/{vid}", json=variant_body(
        variant, scenes=[scene(S1, controls=CONTROLS), scene(S2, controls=CONTROLS)]))
    assert status == 200, saved
    return pid, vid, saved["revision"]


def scenes_of(variant: dict) -> str:
    return json.dumps(variant["scenes"], sort_keys=True)


# ------------------------------------------------------------------ table et parite

def test_the_route_table_and_the_relay_surface():
    routes = [(route.method, route.path) for route in PresentationStudioProtocolRoutes(object()).routes()]
    assert ("GET", PREFIX + "/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/control-suggestions") in routes
    assert ("POST", PREFIX + "/{presentation_id}/variants/{variant_id}/edits") in routes
    relay = PresentationStudioRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    # Slice 12 adds the playback verbs under /playback (their own table: test_presentation_studio_playback_routes.py)
    mapped = {(r.method, "/v1/presentation-studio" + r.path[len("/api/presentation-studio"):]) for r in relay.routes()
              if not r.path.startswith("/api/presentation-studio/playback")}
    assert mapped <= set(routes)
    # the page reads, and writes only through the edit API: no PUT, no create, no raw validate
    # Slice 08 adds undo and redo: an undo is an edit through the same service, with the same forced actor
    assert {key for key in mapped if key[0] != "GET"} == {
        ("POST", PREFIX + f"/{{presentation_id}}/variants/{{variant_id}}/{tail}") for tail in ("edits", "undo", "redo")}
    assert set(vars(relay)) == {"_transport", "_journal"}  # no state in the Control Center


def test_the_prefix_is_guarded_for_every_method_and_relayable():
    assert GUARDED_PREFIXES == ("/api/presentation-studio",) and set(GUARDED_PREFIXES) <= set(READ_GUARDED_ROUTES)
    assert STUDIO_PREFIX in FORWARDABLE_PREFIXES == client_module.FORWARDABLE_PREFIXES
    assert CORE_PREFIX == PREFIX == STUDIO_PREFIX and STUDIO_ROUTE.startswith(GUARDED_PREFIXES[0])


# ------------------------------------------------------------------ Core

async def test_the_three_outcomes_over_http_with_their_statuses(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        edits = f"/{pid}/variants/{vid}/edits"
        status, applied = await core.call("POST", edits, json=body(revision, op_set(S1, "body", "Bonjour")))
        assert status == 200 and applied["status"] == "applied" and applied["committed"] and applied["revision"] == revision + 1
        assert applied["tier"] == "control" and applied["undo"]["available"] and "error" not in applied
        status, stale = await core.call("POST", edits, json=body(revision, op_set(S1, "body", "Perime")))
        assert status == 409 and stale["status"] == "stale" and stale["error"]["code"] == "presentation_studio_stale_revision"
        assert stale["revision"] == revision + 1 and stale["committed"] is False
        status, refused = await core.call("POST", edits, json=body(revision + 1, op_set(S1, "body", 12), op_set(S2, "nope", 1)))
        assert status == 400 and refused["status"] == "refused" and refused["failed_index"] == 0
        assert refused["code"] == "presentation_studio_value_refused" and refused["error"]["code"] == refused["code"]
        status, unknown = await core.call("POST", edits, json=body(revision + 1, op_set(S2, "nope", 1)))
        assert (status, unknown["code"]) == (404, "presentation_studio_unknown_control")
        status, preview = await core.call("POST", edits, json=body(revision + 1, op_set(S1, "body", "Plan"), mode="preview"))
        assert status == 200 and preview["committed"] is False and preview["revision"] == revision + 1
        _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
        assert variant["revision"] == revision + 1 and variant["scenes"][0]["data"]["body"] == "Bonjour"


async def test_malformed_and_unknown_requests_are_coded_envelopes(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)

        async def code(path, **kw):
            status, payload = await core.call("POST", path, **kw)
            assert set(payload) == {"error"}, payload
            return status, payload["error"]["code"]

        edits = f"/{pid}/variants/{vid}/edits"
        assert await code(edits, json={**body(revision, op_set(S1, "body", "x")), "actor": "root"}) == (400, "presentation_studio_invalid")
        assert await code(edits, json=body(revision)) == (400, "presentation_studio_invalid")
        assert await code(edits, json=body(revision, {"op": "selection.set"})) == (400, "presentation_studio_invalid")
        assert await code(edits, data=b"not json") == (400, "invalid_request")
        assert await code(edits, data=b"x" * (128 * 1024 + 10)) == (400, "invalid_request")
        assert await code(f"/{pid}/variants/psv_" + "0" * 32 + "/edits", json=body(1, op_set(S1, "body", "x"))) == (
            404, "presentation_studio_unknown_variant")
        status, payload = await core.call("POST", edits + "?x=1", json=body(revision, op_set(S1, "body", "x")))
        assert status == 400 and payload["error"]["code"] == "invalid_request"
        async with core.http.post(core.stack.core_url + PREFIX + edits, json=body(revision)) as response:
            assert response.status == 401  # the bearer token is required


async def test_the_typed_client_returns_the_result_of_all_three_outcomes_and_raises_on_envelopes(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        client = core.client
        applied = await client.presentation_studio_edit(pid, vid, body(revision, op_set(S1, "body", "Client")))
        assert applied["status"] == "applied"
        stale = await client.presentation_studio_edit(pid, vid, body(revision, op_set(S1, "body", "Perime")))
        assert stale["status"] == "stale" and stale["error"]["code"] == "presentation_studio_stale_revision"
        refused = await client.presentation_studio_edit(pid, vid, body(revision + 1, op_set(S1, "body", 5)))
        assert refused["status"] == "refused" and refused["failed_index"] == 0
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_edit(pid, vid, {"actor": "brain"})
        assert (caught.value.status, caught.value.code) == (400, "presentation_studio_invalid")
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_edit(pid, "psv_" + "0" * 32, body(1, op_set(S1, "body", "x")))
        assert caught.value.code == "presentation_studio_unknown_variant"


async def test_controls_are_discovered_proposed_and_applied_through_the_one_api(tmp_path):
    async with Core(tmp_path) as core:
        _, created = await core.call("POST", "", json={"title": "Decouverte"})
        pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
        vid = variant["variant_id"]
        _, saved = await core.call("PUT", f"/{pid}/variants/{vid}", json=variant_body(variant, scenes=[scene(S1)]))
        suggestion = await core.client.presentation_studio_suggest_controls(pid, vid, S1)
        assert {p["path"] for p in suggestion["proposals"]} == {"props.accent", "props.density", "data.body"}
        assert suggestion["basis"] == {"variant_revision": saved["revision"]} and suggestion["truncated"] is False
        _, still = await core.call("GET", f"/{pid}/variants/{vid}")
        assert still == saved  # proposing wrote nothing
        applied = await core.client.presentation_studio_edit(
            pid, vid, {"actor": "brain", "mode": "commit", "basis": suggestion["basis"], "ops": [suggestion["apply"]]})
        assert applied["status"] == "applied" and applied["tier"] == "structure"
        described = await core.client.presentation_studio_scene_controls(pid, vid, S1)
        assert {c["path"] for c in described["controls"]} == {"props.accent", "props.density", "data.body"}
        status, payload = await core.call("GET", f"/{pid}/variants/{vid}/scenes/pss_00000000ffff/control-suggestions")
        assert (status, payload["error"]["code"]) == (404, "presentation_studio_unknown_scene")


async def test_the_canonical_event_is_recorded_with_ids_and_never_content(tmp_path):
    async with Core(tmp_path) as core:
        seen = []
        core.stack.core.conversation_event_emitter.add_listener(seen.append)
        live = core.stack.core.brain.live_conversation_id()
        assert live  # Core opens a conversation at start: the edit lands on the live timeline
        pid, vid, revision = await new_presentation(core)
        result = await core.client.presentation_studio_edit(
            pid, vid, body(revision, op_set(S1, "body", "Texte secret"),
                           {"op": "scene.source_request", "scene_id": S1, "intent": "ajoute une animation"}))
        assert result["status"] == "applied"
        events = [e for e in seen if e.event_type is T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED]
        assert len(events) == 1
        event = events[0]
        assert event.conversation_id == live and event.actor.value == "system" and event.visibility.value == "diagnostic"
        assert dict(event.attributes) == {"presentation_id": pid, "variant_id": vid, "scene_id": S1,
                                          "op": ("control.set", "scene.source_request"), "tier": "source",
                                          "source": "brain", "revision": revision + 1, "status": "applied"}
        assert event.content is None and "secret" not in repr(event) and "animation" not in repr(event)
        await core.stack.core.conversation_event_emitter.stop()


# ------------------------------------------------------------------ relais

async def test_the_relay_reads_and_returns_core_bodies_unchanged(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        call = core.stack.call
        status, listing, _ = await call("GET", RELAY)
        assert status == 200 and [r["presentation_id"] for r in listing["presentations"]] == [pid]
        _, direct = await core.call("GET", f"/{pid}")
        assert (await call("GET", f"{RELAY}/{pid}"))[:2] == (200, direct)
        _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
        assert (await call("GET", f"{RELAY}/{pid}/variants/{vid}"))[:2] == (200, variant)
        _, controls = await core.call("GET", f"/{pid}/variants/{vid}/scenes/{S1}/controls")
        assert (await call("GET", f"{RELAY}/{pid}/variants/{vid}/scenes/{S1}/controls"))[:2] == (200, controls)
        status, suggestions, _ = await call("GET", f"{RELAY}/{pid}/variants/{vid}/scenes/{S1}/control-suggestions")
        assert status == 200 and suggestions["basis"] == {"variant_revision": revision}
        status, error, _ = await call("GET", f"{RELAY}/pst_{'0' * 32}")
        assert (status, error["error"]["code"]) == (404, "presentation_studio_unknown_presentation")


async def test_the_relay_forces_the_actor_to_user_whatever_the_page_says(tmp_path):
    async with Core(tmp_path) as core:
        seen = []
        core.stack.core.conversation_event_emitter.add_listener(seen.append)
        pid, vid, revision = await new_presentation(core)
        for claimed in ("brain", "system", "root", None):
            payload = body(revision, op_set(S1, "body", f"Page {claimed}"))
            payload["actor"] = claimed
            if claimed is None:
                del payload["actor"]
            status, result, _ = await core.stack.call("POST", f"{RELAY}/{pid}/variants/{vid}/edits", json=payload)
            assert status == 200 and result["actor"] == "user", (claimed, result)
            revision = result["revision"]
        sources = [dict(e.attributes)["source"] for e in seen if e.event_type is T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED]
        assert sources == ["user"] * 4


async def test_the_page_and_the_brain_reach_the_same_canonical_state(tmp_path):
    async with Core(tmp_path) as core:
        ops = [op_set(S1, "body", "Meme resultat"), op_set(S2, "density", "comfortable"),
               {"op": "scene.rename", "scene_id": S2, "title": "Renomme"},
               {"op": "scene.reorder", "scene_id": S2, "to_index": 0},
               {"op": "scene.add", "scene": scene("pss_0000000000c3", controls=CONTROLS), "index": 1}]
        pid_a, vid_a, rev_a = await new_presentation(core, "Page")
        pid_b, vid_b, rev_b = await new_presentation(core, "Voix")
        status, via_page, _ = await core.stack.call("POST", f"{RELAY}/{pid_a}/variants/{vid_a}/edits",
                                                    json=body(rev_a, *ops, actor="brain"))
        assert status == 200, via_page
        via_voice = await core.client.presentation_studio_edit(pid_b, vid_b, body(rev_b, *ops, actor="brain"))
        assert via_page["actor"] == "user" and via_voice["actor"] == "brain"
        _, state_a = await core.call("GET", f"/{pid_a}/variants/{vid_a}")
        _, state_b = await core.call("GET", f"/{pid_b}/variants/{vid_b}")
        assert scenes_of(state_a) == scenes_of(state_b) and state_a["revision"] == state_b["revision"]
        drop = ("actor", "presentation_id", "variant_id")
        assert {k: v for k, v in via_page.items() if k not in drop and k != "undo"} == \
            {k: v for k, v in via_voice.items() if k not in drop and k != "undo"}
        assert via_page["undo"]["ops"] == via_voice["undo"]["ops"]


async def test_the_relay_exposes_no_other_write(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
        for method, path, payload in (
                ("PUT", f"{RELAY}/{pid}/variants/{vid}", variant_body(variant, title="Direct")),
                ("PUT", f"{RELAY}/{pid}", {"expected_revision": 1}),
                ("POST", RELAY, {"title": "Cree"}),
                ("POST", f"{RELAY}/validate", {}),
                ("DELETE", f"{RELAY}/{pid}", None)):
            status, _, _ = await core.stack.call(method, path, **({} if payload is None else {"json": payload}))
            assert status in (404, 405), (method, path, status)
        _, after = await core.call("GET", f"/{pid}/variants/{vid}")
        assert after == variant


@pytest.mark.parametrize("headers", [{"Origin": "null"}, {"Origin": "https://evil.example"},
                                     {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"}])
async def test_a_frame_or_a_foreign_origin_can_neither_read_nor_edit(tmp_path, headers):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        status, payload, _ = await core.stack.call("GET", f"{RELAY}/{pid}", headers=headers)
        assert status == 403 and payload["code"] == "forbidden_origin"
        status, payload, _ = await core.stack.call("POST", f"{RELAY}/{pid}/variants/{vid}/edits", headers=headers,
                                                   json=body(revision, op_set(S1, "body", "Intrus")))
        assert status == 403
        _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
        assert variant["revision"] == revision


async def test_the_relay_rejects_malformed_bodies_and_reports_core_down_as_coded_503(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        url = f"{RELAY}/{pid}/variants/{vid}/edits"
        status, payload, _ = await core.stack.call("POST", url, data=b"[1,2]")
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await core.stack.call("POST", url, data=b"{nope")
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await core.stack.call("POST", url + "?actor=brain", json=body(revision, op_set(S1, "body", "x")))
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await core.stack.call("POST", url, data=b"x" * (128 * 1024 + 10))
        assert status == 400
        await core.stack.server.stop()
        status, payload, _ = await core.stack.call("POST", url, json=body(revision, op_set(S1, "body", "x")))
        assert (status, payload["error"]["code"]) == (503, "core_unreachable")
        core.stack.center.sessions = None
        status, payload, _ = await core.stack.call("GET", RELAY)
        assert (status, payload["error"]["code"]) == (503, "core_unconfigured")
        lines = [e for e in core.stack.trace() if e.get("kind") == "presentation_studio.request.core_unreachable"]
        assert lines and lines[0]["data"]["action"] == "studio_edit"


async def test_the_relay_journal_never_holds_a_value_or_an_intent(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        status, result, _ = await core.stack.call(
            "POST", f"{RELAY}/{pid}/variants/{vid}/edits",
            json=body(revision, op_set(S1, "body", "Valeur privee"),
                      {"op": "scene.source_request", "scene_id": S1, "intent": "intention privee"}))
        assert status == 200
        rows = [e for e in core.stack.trace() if str(e.get("kind", "")).startswith("presentation_studio.request")]
        assert rows and rows[0]["data"]["action"] == "studio_edit" and rows[0]["data"]["result"] == "applied"
        text = json.dumps(core.stack.trace())
        assert "privee" not in text


async def test_the_live_conversation_is_the_foreground_one_and_never_a_finished_turns_conversation(tmp_path):
    async with Core(tmp_path) as core:
        brain = core.stack.core.brain
        assert brain.live_conversation_id()  # bound at start
        brain._speech_authority = None
        brain._last_conversation_id = "conv-finished-days-ago"
        assert brain.live_conversation_id() is None  # no event is attached to a stale conversation
