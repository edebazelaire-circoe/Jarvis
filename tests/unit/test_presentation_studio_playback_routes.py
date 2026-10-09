"""Playback over the real wire: Core routes, typed client, Control Center relay, bus message (Slice 12).

Real `JarvisCoreApplication` behind the real `LocalProtocolServer`, real Control Center in front, base prefab
`jarvis.window`, real `/v1/events` WebSocket for the armed-set message. The relay forces the actor to `user`; the armed set
(phrases) and the cue report are never relayed; the page cannot reach anything but the playback verbs.
Contract: `docs/presentation-studio.md` > *Playback runtime contract*.
"""

from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.presentation_studio_playback_requests import Verb
from jarvis.protocol import client as client_module
from jarvis.protocol.client import FORWARDABLE_PREFIXES, PLAYBACK_PREFIX, CoreProtocolError
from jarvis.protocol.presentation_studio_playback_routes import CUES, PLAYBACK, PresentationStudioPlaybackRoutes
from jarvis.runtime.presentation_studio_relay import PLAYBACK_ROUTE, PresentationStudioRelayRoutes
from tests.unit.test_presentation_studio_routes import AUTH, Core, variant_body

S1, S2, S3 = "pss_0000000000d1", "pss_0000000000d2", "pss_0000000000d3"
I1, I2, I3 = "psi_0000000000d1", "psi_0000000000d2", "psi_0000000000d3"
CUE = "psc_0000000000d1"
CONTROLS = [{"control_id": "density", "path": "props.density", "label": "Densite", "group": "layout"},
            {"control_id": "body", "path": "data.body", "label": "Texte", "group": "content"}]
AUX = {"title": "Annexe", "prefab": {"id": "jarvis.window", "version": 1, "props": {"density": "compact"},
                                     "data": {"body": "Annexe"}}}


def scene(scene_id: str, title: str) -> dict:
    return {"scene_id": scene_id, "prefab": {"id": "jarvis.window", "version": 1}, "title": title,
            "props": {"density": "compact"}, "data": {"body": "Texte"}, "controls": CONTROLS}


def score(revision: int) -> dict:
    return {"expected_variant_revision": revision, "start_item_id": I1, "items": [
        {"item_id": I1, "scene_id": S1, "presenter": "user", "kind": "speech", "note": "Un",
         "visual": [{"kind": "control_set", "scene_id": S1, "control_id": "body", "value": "Premier"}], "next_item_id": I2},
        {"item_id": I2, "scene_id": S2, "presenter": "user", "kind": "speech", "note": "Deux", "cue_id": CUE,
         "next_item_id": I3},
        {"item_id": I3, "scene_id": S3, "presenter": "none", "kind": "silence"}],
        "cues": [{"cue_id": CUE, "label": "Suite", "armable": True, "predicate": {"phrases": ["passons a la suite"]}}],
        "sequences": [], "recovery_points": []}


async def presentation_with_score(core: Core) -> tuple[str, str]:
    _, created = await core.call("POST", "", json={"title": "Lecture"})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    vid = variant["variant_id"]
    status, saved = await core.call("PUT", f"/{pid}/variants/{vid}", json=variant_body(
        variant, scenes=[scene(S1, "Un"), scene(S2, "Deux"), scene(S3, "Trois")]))
    assert status == 200, saved
    status, made = await core.call("POST", f"/{pid}/variants/{vid}/score", json=score(saved["revision"]))
    assert status == 201, made
    status, art = await core.call("POST", f"/{pid}/variants/{vid}/art-direction/fallback",
                                  json={"expected_variant_revision": saved["revision"] + 1})
    assert status == 201, art  # a serious run needs an art direction (the real gate, Slice 09)
    return pid, vid


def start_body(pid: str, **extra) -> dict:
    return {"actor": "user", "presentation_id": pid, "role": "user_presenter", **extra}


async def post(core: Core, path: str, body: dict | None = None, *, headers=AUTH):
    async with core.http.post(core.stack.core_url + path, headers=headers, json=body) as response:
        return response.status, await response.json(content_type=None)


# ------------------------------------------------------------------ tables

def test_the_core_route_table_and_what_the_relay_exposes():
    routes = [(r.method, r.path) for r in PresentationStudioPlaybackRoutes(object()).routes()]
    assert routes == [("GET", PLAYBACK), ("GET", PLAYBACK + "/armed"), ("POST", PLAYBACK + "/{verb}"), ("POST", CUES)]
    relay = PresentationStudioRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    mapped = {(r.method, "/v1/presentation-studio" + r.path[len("/api/presentation-studio"):]) for r in relay.routes()
              if r.path.startswith(PLAYBACK_ROUTE)}
    assert mapped == {("GET", PLAYBACK), *(("POST", f"{PLAYBACK}/{verb.value}") for verb in Verb)}
    assert not any("armed" in path or "cues" in path for _, path in mapped), "phrases and cue reports are never relayed"
    assert PLAYBACK == PLAYBACK_PREFIX and PLAYBACK_PREFIX in FORWARDABLE_PREFIXES == client_module.FORWARDABLE_PREFIXES
    assert {v.value for v in Verb} == {"start", "stop", "pause", "resume", "next", "previous", "goto", "detour", "return",
                                       "reveal", "hide", "edit", "skip_sequence"}


# ------------------------------------------------------------------ Core

async def test_a_run_over_http_with_its_statuses_and_the_typed_client(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid = await presentation_with_score(core)
        async with core.http.get(core.stack.core_url + PLAYBACK, headers=AUTH) as response:
            assert response.status == 200 and await response.json() == {"state": {"phase": "idle", "running": False}}
        async with core.http.get(core.stack.core_url + PLAYBACK) as response:
            assert response.status == 401                                       # the bearer token is required
        client = core.client
        started = await client.presentation_studio_playback("start", start_body(pid))
        assert started["status"] == "applied" and started["state"]["phase"] == "playing"
        assert started["state"]["scene"]["title"] == "Un" and started["state"]["art_direction"] == "fallback"
        stage_id = started["state"]["stage_object_id"]
        snapshot = await core.stack.core.scene.snapshot()
        assert snapshot.get_object(stage_id).payload.prefab.data["body"] == "Premier"       # the overlay is on screen
        _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
        assert variant["scenes"][0]["data"]["body"] == "Texte"                              # ... and not in the variant
        assert (await client.presentation_studio_playback_state())["state"]["phase"] == "playing"
        refused = await client.presentation_studio_playback("previous", {"actor": "user"})
        assert refused["status"] == "refused" and refused["reason"] == "at_start" and refused["error"]["code"] == \
            "presentation_studio_playback_refused"
        status, raw = await post(core, f"{PLAYBACK}/previous", {"actor": "user"})
        assert status == 409 and raw["status"] == "refused"
        moved = await client.presentation_studio_playback("next", {"actor": "user"})
        assert moved["state"]["scene"]["title"] == "Deux" and moved["state"]["stage_object_id"] == stage_id
        detour = await client.presentation_studio_playback("detour", {"actor": "user", **AUX})
        assert detour["state"]["phase"] == "detour"
        back = await client.presentation_studio_playback("return", {"actor": "user"})
        assert back["state"]["phase"] == "playing"
        stopped = await client.presentation_studio_playback("stop", {"actor": "user"})
        assert stopped["state"]["phase"] == "stopped" and snapshot is not None
        after = await core.stack.core.scene.snapshot()
        assert after.get_object(stage_id) is None


async def test_malformed_unknown_and_unauthorized_requests_are_coded_envelopes(tmp_path):
    async with Core(tmp_path) as core:
        pid, _ = await presentation_with_score(core)

        async def code(path, body, **kw):
            status, payload = await post(core, path, body, **kw)
            return status, payload["error"]["code"]

        assert await code(f"{PLAYBACK}/start", {**start_body(pid), "text": "hello"}) == (400, "invalid_request")
        assert await code(f"{PLAYBACK}/start", {"actor": "root", "presentation_id": pid, "role": "x"}) == (400, "invalid_request")
        assert await code(f"{PLAYBACK}/next", {"actor": "user", "extra": 1}) == (400, "invalid_request")
        assert await code(f"{PLAYBACK}/launch", {"actor": "user"}) == (404, "invalid_request")
        assert await code(f"{PLAYBACK}/start", start_body("pst_" + "0" * 32)) == (404, "presentation_studio_unknown_presentation")
        status, unauthorized = await post(core, f"{PLAYBACK}/start", start_body(pid), headers={})
        assert status == 401
        async with core.http.post(core.stack.core_url + f"{PLAYBACK}/start", headers=AUTH, data=b"nope") as response:
            assert response.status == 400 and (await response.json())["error"]["code"] == "invalid_request"
        async with core.http.post(core.stack.core_url + f"{PLAYBACK}/start?x=1", headers=AUTH, json=start_body(pid)) as response:
            assert response.status == 400
        # nothing started by any of these
        assert (await core.client.presentation_studio_playback_state())["state"]["running"] is False


async def test_a_presentation_without_a_score_is_a_coded_404_and_nothing_appears_on_the_scene(tmp_path):
    async with Core(tmp_path) as core:
        _, created = await core.call("POST", "", json={"title": "Sans partition"})
        pid = created["presentation"]["presentation_id"]
        before = (await core.stack.core.scene.snapshot()).revision
        status, payload = await post(core, f"{PLAYBACK}/start", start_body(pid))
        assert (status, payload["error"]["code"]) == (404, "presentation_studio_unknown_score")
        assert (await core.stack.core.scene.snapshot()).revision == before


# ------------------------------------------------------------------ the armed-set delivery over the real transport

async def test_the_follower_hears_a_content_free_message_on_the_event_stream_then_pulls_and_reports(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid = await presentation_with_score(core)
        async with core.http.ws_connect(core.stack.core_url + "/v1/events", headers=AUTH) as ws:
            assert (await ws.receive_json())["message_type"] == "connected"
            started = await core.client.presentation_studio_playback("start", start_body(pid))
            heard = []
            while not heard:
                message = await asyncio.wait_for(ws.receive_json(), 5)
                if message["message_type"] == "presentation_studio.armed.changed":
                    heard.append(message)
            [announced] = heard
            payload = announced["payload"]
            assert payload == {"run_id": payload["run_id"], "generation": 1, "count": 1}
            assert "passons" not in json.dumps(announced)                    # the bus never carries a phrase
            armed = await core.client.presentation_studio_playback_armed()
            assert armed["run_id"] == payload["run_id"] == started["state"]["run_id"]
            assert armed["cues"] == [{"cue_id": CUE, "phrases": ["passons a la suite"], "semantics": []}]
            answer = await core.client.presentation_studio_report_cue(armed["run_id"], armed["generation"], CUE)
            assert answer["status"] == "fired"
            stale = await core.client.presentation_studio_report_cue(armed["run_id"], armed["generation"], CUE)
            assert stale["duplicate"] is True and stale["status"] == "fired"            # idempotent: no second advance
            wrong = await core.client.presentation_studio_report_cue(armed["run_id"], armed["generation"] + 5, CUE)
            assert wrong["status"] == "refused" and wrong["code"] == "stale_generation"
            state = (await core.client.presentation_studio_playback_state())["state"]
            assert state["position"]["index"] == 2
            status, bad = await post(core, CUES, {"run_id": "r", "generation": 1, "cue_id": CUE, "text": "passons a la suite"})
            assert (status, bad["error"]["code"]) == (400, "invalid_request")           # room text has no way in
            async with core.http.get(core.stack.core_url + PLAYBACK + "/armed") as response:
                assert response.status == 401


async def test_the_typed_client_raises_on_a_bare_envelope_and_returns_every_outcome(tmp_path):
    async with Core(tmp_path) as core:
        with pytest.raises(CoreProtocolError) as caught:
            await core.client.presentation_studio_playback("start", {"actor": "user"})
        assert caught.value.status == 400
        refused = await core.client.presentation_studio_playback("next", {"actor": "user"})
        assert refused["status"] == "refused" and refused["reason"] == "not_running"


async def test_the_canonical_event_carries_ids_and_a_status_word_never_content(tmp_path):
    async with Core(tmp_path) as core:
        seen = []
        core.stack.core.conversation_event_emitter.add_listener(seen.append)
        pid, vid = await presentation_with_score(core)
        await core.client.presentation_studio_playback("start", start_body(pid))
        await core.client.presentation_studio_playback("detour", {"actor": "user", **AUX})
        await core.client.presentation_studio_playback("stop", {"actor": "user"})
        events = [e for e in seen if e.event_type is T.SYSTEM_PRESENTATION_STUDIO_PLAYBACK_CHANGED]
        assert [dict(e.attributes)["status"] for e in events] == ["started", "detour", "stopped"]
        assert dict(events[0].attributes) == {"presentation_id": pid, "variant_id": vid, "status": "started",
                                              "role": "user_presenter", "depth": 0}
        assert all(e.actor.value == "system" and e.content is None for e in events)
        assert "Annexe" not in repr(events) and "passons" not in repr(events)
        await core.stack.core.conversation_event_emitter.stop()


# ------------------------------------------------------------------ the relay

async def test_the_relay_forces_the_actor_and_cannot_claim_a_spontaneous_origin(tmp_path):
    async with Core(tmp_path) as core:
        pid, _ = await presentation_with_score(core)
        call = core.stack.call
        status, started, _ = await call("POST", f"{PLAYBACK_ROUTE}/start", json={**start_body(pid), "actor": "brain"})
        assert status == 200 and started["state"]["phase"] == "playing"
        assert core.stack.core.interaction_mode.state.source == "presentation_studio_run"   # the page may switch the mode
        status, state, _ = await call("GET", PLAYBACK_ROUTE)
        assert status == 200 and state["state"]["role"] == "user_presenter"
        for verb in ("stop",):
            await call("POST", f"{PLAYBACK_ROUTE}/{verb}", json={"actor": "brain"})
        status, bad, _ = await call("POST", f"{PLAYBACK_ROUTE}/start",
                                    json={**start_body(pid), "actor": "brain", "origin": "ambient_text"})
        assert status == 400 and bad["error"]["code"] == "invalid_request"     # forced to user: only an explicit request
        assert core.stack.core.interaction_mode.mode.value == "assistant"      # restored after the stop


async def test_the_relay_reads_a_bounded_state_and_exposes_neither_the_armed_set_nor_the_cue_report(tmp_path):
    async with Core(tmp_path) as core:
        pid, _ = await presentation_with_score(core)
        call = core.stack.call
        await call("POST", f"{PLAYBACK_ROUTE}/start", json=start_body(pid))
        for method, path in (("GET", f"{PLAYBACK_ROUTE}/armed"), ("POST", "/api/presentation-studio/cues/satisfied"),
                             ("POST", f"{PLAYBACK_ROUTE}/launch"), ("DELETE", PLAYBACK_ROUTE), ("PUT", PLAYBACK_ROUTE)):
            status, _, _ = await call(method, path, **({"json": {}} if method != "GET" else {}))
            assert status in (404, 405), (method, path, status)
        status, state, _ = await call("GET", PLAYBACK_ROUTE)
        # The user's own page reads the bounded "where are we" (at most three trigger phrases of the next cue, to show
        # the presenter what to say); the armed MESSAGE (ids + generation + all phrases + ambiguity) is Voice's alone.
        assert status == 200 and state["state"]["next"]["cue"]["phrases"] == ["passons a la suite"]
        assert len(json.dumps(state).encode()) < 2600
        await call("POST", f"{PLAYBACK_ROUTE}/stop", json={})


async def test_the_relay_answers_refusals_and_unavailable_core_with_the_core_body(tmp_path):
    async with Core(tmp_path) as core:
        status, refused, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/next", json={})
        assert status == 409 and refused["status"] == "refused" and refused["reason"] == "not_running"
        status, malformed, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/next", json=[1, 2])
        assert status == 400 and malformed["error"]["code"] == "invalid_request"
        status, nonJson, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/next", data=b"nope")
        assert status == 400
        status, cross, _ = await core.stack.call("GET", PLAYBACK_ROUTE, headers={"Origin": "null"})
        assert status in (400, 403), "a prefab frame (Origin: null) reads nothing here"


# ------------------------------------------------------------------ Slice 12 rework: 422, skip_sequence, follower on the wire

async def test_an_invalid_detour_is_a_422_with_a_typed_refusal_on_both_hops_and_the_run_is_untouched(tmp_path):
    async with Core(tmp_path) as core:
        pid, _ = await presentation_with_score(core)
        status, started = await post(core, f"{PLAYBACK}/start", start_body(pid))
        assert status == 200
        bad = {"actor": "user", "title": "Annexe", "prefab": {"id": "lab.nothing", "version": 1}}
        for hop in ("core", "relay"):
            if hop == "core":
                status, body = await post(core, f"{PLAYBACK}/detour", bad)
            else:
                status, body, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/detour", json=bad)
            assert status == 422, (hop, status, body)
            assert body["status"] == "refused" and body["reason"] == "detour_invalid", body
            assert body["error"]["code"] == "presentation_studio_playback_refused"
            assert body["state"]["phase"] == "playing" and body["state"]["detour"] is None
        status, moved = await post(core, f"{PLAYBACK}/next", {"actor": "user"})
        assert status == 200 and moved["state"]["scene"]["title"] == "Deux"           # not stuck in a phantom detour
        await post(core, f"{PLAYBACK}/stop", {"actor": "user"})


async def test_skip_sequence_is_user_only_on_the_wire_and_refused_typed_when_there_is_no_sequence(tmp_path):
    async with Core(tmp_path) as core:
        pid, _ = await presentation_with_score(core)
        await post(core, f"{PLAYBACK}/start", start_body(pid))
        status, body = await post(core, f"{PLAYBACK}/skip_sequence", {"actor": "brain"})
        assert status == 400 and body["error"]["code"] == "invalid_request" and "user action" in body["error"]["message"]
        status, body = await post(core, f"{PLAYBACK}/skip_sequence", {"actor": "user"})
        assert status == 409 and body["reason"] == "no_sequence"
        status, body, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/skip_sequence", json={"actor": "brain"})
        assert status == 409 and body["reason"] == "no_sequence"        # the relay forced the actor to user, as for every verb
        await post(core, f"{PLAYBACK}/stop", {"actor": "user"})


async def test_the_follower_state_travels_in_the_bounded_state_and_a_pull_connects_it(tmp_path):
    async with Core(tmp_path) as core:
        pid, _ = await presentation_with_score(core)
        status, started = await post(core, f"{PLAYBACK}/start", start_body(pid))
        assert started["state"]["follower"] == "waiting"
        async with core.http.get(core.stack.core_url + PLAYBACK + "/armed", headers=AUTH) as response:
            assert response.status == 200
        status, state, _ = await core.stack.call("GET", PLAYBACK_ROUTE)
        assert state["state"]["follower"] == "connected"
        assert len(json.dumps(state).encode()) < 3072
        await post(core, f"{PLAYBACK}/stop", {"actor": "user"})
        status, state, _ = await core.stack.call("GET", PLAYBACK_ROUTE)
        assert "follower" not in state["state"]
