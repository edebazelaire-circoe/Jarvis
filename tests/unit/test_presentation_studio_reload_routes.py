"""Routes Core, client type et relais Control Center du rechargement a chaud (jarvis-interactive-presentation-studio, Slice 06).

Vrai Core (`JarvisCoreApplication`) derriere le vrai `LocalProtocolServer`, vrai Control Center devant lui : statuts et corps
de chaque issue, client type, acteur force a `user` par le relais, rapport de montage de la page, garde d'origine (un cadre
ne peut ni editer ni rapporter), pannes, journal sans contenu, evenement canonique reel.
Contrat : `docs/presentation-studio.md` > *Hot reload contract*.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.protocol.client import CoreProtocolError
from tests.unit.test_presentation_studio_edit_routes import RELAY, S1, S2, new_presentation, op_set
from tests.unit.test_presentation_studio_routes import Core

STYLE = "p{color:#abcdef}"


def request(revision: int, files: dict, *, scene_id: str = S1, actor: str = "user", **extra) -> dict:
    return {"actor": actor, "basis": {"variant_revision": revision}, "scene_id": scene_id, "files": files, **extra}


async def pending(core: Core, pid: str, vid: str, scene_id: str = S1) -> str:
    """Remotion Slice 21 (QA B1): a pending source request as the user's edit API records it, and its id (a brain edit cites one)."""

    _, current = await core.call("GET", f"/{pid}/variants/{vid}")
    status, done = await core.call("POST", f"/{pid}/variants/{vid}/edits", json={
        "actor": "user", "mode": "commit", "basis": {"variant_revision": current["revision"]},
        "ops": [{"op": "scene.source_request", "scene_id": scene_id, "intent": "test"}]})
    assert status == 200, done
    return done["source_requests"][0]["request_id"]


async def start_run(core: Core, pid: str, vid: str) -> tuple[str, int]:
    """A REAL playback run (Slice 12) of the first scene: its stage window `studio-stage-<run_id>` and the variant revision."""

    studio, playback = core.stack.core.presentation_studio, core.stack.core.presentation_studio_playback
    variant = await studio.get_variant(pid, vid)
    item = {"item_id": "psi_000000000001", "scene_id": S1, "presenter": "user", "kind": "speech", "note": "Un", "next_item_id": None}
    await studio.create_score(pid, vid, {"expected_variant_revision": variant.revision, "start_item_id": item["item_id"],
                                         "items": [item], "cues": [], "sequences": [], "recovery_points": []})
    result = await playback.start({"actor": "user", "presentation_id": pid, "role": "rehearsal"})
    assert result.status.value == "applied", result.to_dict()
    return result.to_dict()["state"]["stage_object_id"], (await studio.get_variant(pid, vid)).revision


async def variant_of(core: Core, pid: str, vid: str) -> dict:
    return (await core.call("GET", f"/{pid}/variants/{vid}"))[1]


# ------------------------------------------------------------------ Core + client

async def test_a_source_edit_over_http_is_a_complete_result_with_its_status(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        url = f"/{pid}/variants/{vid}/source-edits"
        status, result = await core.call("POST", url, json=request(revision, {"style": STYLE}))
        # no stage window shows the scene: the version is pinned and waits to be seen mounted
        assert status == 200 and result["status"] == "repinned" and result["mounted"] is None and "error" not in result
        assert result["prefab"]["id"].startswith("presentation-studio.p") and result["previous"] == {"id": "jarvis.window", "version": 1}
        variant = await variant_of(core, pid, vid)
        scene = variant["scenes"][0]
        assert scene["source_revision"] == 1 and scene["last_valid_pin"] == {"id": "jarvis.window", "version": 1}
        assert variant["scenes"][1]["source_revision"] == 0 and variant["schema_version"] == 5
        status, refused = await core.call("POST", url, json=request(variant["revision"], {"template": "<iframe></iframe>"}))
        assert status == 400 and refused["status"] == "refused_validation" and refused["error"]["code"] == "presentation_studio_source_invalid"
        status, stale = await core.call("POST", url, json=request(revision, {"style": STYLE}))
        assert status == 409 and stale["status"] == "stale" and stale["error"]["code"] == "presentation_studio_stale_revision"


async def test_malformed_and_unknown_source_edits_are_coded_envelopes(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        url = f"/{pid}/variants/{vid}/source-edits"

        async def code(path, **kw):
            status, payload = await core.call("POST", path, **kw)
            assert set(payload) == {"error"}, payload
            return status, payload["error"]["code"]

        assert await code(url, json={**request(revision, {"style": STYLE}), "actor": "root"}) == (400, "presentation_studio_invalid")
        assert await code(url, json=request(revision, {})) == (400, "presentation_studio_invalid")
        assert await code(url, json=request(revision, {"script": "x"})) == (400, "presentation_studio_invalid")
        assert await code(url, json=request(revision, {"style": STYLE}, scene_id="pss_00000000ffff")) == (404, "presentation_studio_unknown_scene")
        assert await code(f"/{pid}/variants/psv_{'0' * 32}/source-edits", json=request(1, {"style": STYLE})) == (
            404, "presentation_studio_unknown_variant")
        assert await code(url, data=b"not json") == (400, "invalid_request")
        assert await code(url, data=b"x" * (700 * 1024)) == (400, "invalid_request")
        status, payload = await core.call("POST", url + "?x=1", json=request(revision, {"style": STYLE}))
        assert status == 400
        async with core.http.post(core.stack.core_url + "/v1/presentation-studio/presentations" + url,
                                  json=request(revision, {"style": STYLE})) as response:
            assert response.status == 401                                    # the bearer token is required


async def test_the_typed_client_returns_every_outcome_and_raises_on_envelopes(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        client = core.client
        with pytest.raises(CoreProtocolError) as caught:       # the brain needs a pending request (Slice 21 rework)
            await client.presentation_studio_source_edit(pid, vid, request(revision, {"style": STYLE}, actor="brain"))
        assert (caught.value.status, caught.value.code) == (403, "presentation_studio_source_request_required")
        done = await client.presentation_studio_source_edit(pid, vid, request(revision, {"style": STYLE}, actor="brain",
                                                                              request_id=await pending(core, pid, vid)))
        assert done["status"] == "repinned" and done["actor"] == "brain"
        refused = await client.presentation_studio_source_edit(pid, vid, request(done["revision"], {"template": "<iframe></iframe>"}))
        assert refused["status"] == "refused_validation"
        stale = await client.presentation_studio_source_edit(pid, vid, request(revision, {"style": STYLE}))
        assert stale["status"] == "stale"
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_source_edit(pid, vid, {"actor": "brain"})
        assert (caught.value.status, caught.value.code) == (400, "presentation_studio_invalid")
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_source_edit(pid, vid, request(1, {"style": STYLE}, scene_id="pss_00000000ffff"))
        assert caught.value.code == "presentation_studio_unknown_scene"
        reloads = await client.presentation_studio_reloads(pid)
        assert [row["status"] for row in reloads["reloads"]] == ["repinned", "refused_validation", "stale"]
        assert reloads["pending"][0]["scene_id"] == S1 and reloads["pending"][0]["fallback"] == {"id": "jarvis.window", "version": 1}
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_reloads("pst_" + "0" * 32)
        assert caught.value.code == "presentation_studio_unknown_presentation"


async def test_the_recent_reloads_carry_codes_and_counts_never_source_or_values(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        await core.client.presentation_studio_source_edit(pid, vid, request(revision, {"style": "p{color:#fedcba}"}))
        text = json.dumps(await core.client.presentation_studio_reloads(pid))
        assert "fedcba" not in text and "Texte" not in text


# ------------------------------------------------------------------ la page : stage et rapport de montage

async def test_the_page_shows_a_scene_then_a_source_edit_waits_for_its_mount_report(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        stage_id, revision = await start_run(core, pid, vid)
        assert stage_id.startswith("studio-stage-")                      # the run's own window, not a provisional route's
        shown = {"object_id": stage_id}
        scene_service = core.stack.core.scene

        async def the_page():
            """The browser: sees the re-pinned stage window, mounts it, reports what it observed."""
            revision_seen = (await scene_service.snapshot()).revision
            while True:
                block = (await scene_service.snapshot()).get_object(shown["object_id"]).payload.prefab
                if block.prefab_id.startswith("presentation-studio."):
                    return await core.stack.call("POST", f"{RELAY}/mount-reports", json={
                        "object_id": shown["object_id"], "prefab": {"id": block.prefab_id, "version": block.version},
                        "outcome": "mounted"})
                revision_seen = await scene_service.wait_for_revision(revision_seen, timeout_s=10)

        page = asyncio.ensure_future(the_page())
        status, result, _ = await core.stack.call("POST", f"{RELAY}/{pid}/variants/{vid}/source-edits",
                                                  json=request(revision, {"style": STYLE}))
        report_status, report, _ = await asyncio.wait_for(page, 10)
        assert status == 200 and result["status"] == "reloaded" and result["mounted"] is True, result
        assert report_status == 200 and report == {"matched": True, "waiting": 1, "resolved": 0,
                                                  "scenes": [{"scene_id": S1, "source_revision": 1}]}   # the report names the scene revision it settled
        scene = (await variant_of(core, pid, vid))["scenes"][0]
        assert scene["last_valid_pin"] is None and scene["source_revision"] == 1


async def test_a_failed_mount_report_over_the_relay_rolls_the_scene_back(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        stage_id, revision = await start_run(core, pid, vid)
        shown = {"object_id": stage_id}
        scene_service = core.stack.core.scene

        async def the_page():
            seen = (await scene_service.snapshot()).revision
            while True:
                block = (await scene_service.snapshot()).get_object(shown["object_id"]).payload.prefab
                if block.prefab_id.startswith("presentation-studio."):
                    return await core.stack.call("POST", f"{RELAY}/mount-reports", json={
                        "object_id": shown["object_id"], "prefab": {"id": block.prefab_id, "version": block.version},
                        "outcome": "failed", "reason": "frame", "message": "ReferenceError: x is not defined"})
                seen = await scene_service.wait_for_revision(seen, timeout_s=10)

        page = asyncio.ensure_future(the_page())
        status, result, _ = await core.stack.call("POST", f"{RELAY}/{pid}/variants/{vid}/source-edits",
                                                  json=request(revision, {"behavior": "x.y = 1;"}))
        await asyncio.wait_for(page, 10)
        assert status == 409 and result["status"] == "rolled_back" and result["error"]["code"] == "presentation_studio_mount_failed"
        assert result["reason"] == "frame" and "ReferenceError" in result["message"] and result["prefab"] == {"id": "jarvis.window", "version": 1}
        scene = (await variant_of(core, pid, vid))["scenes"][0]
        assert scene["prefab"] == {"id": "jarvis.window", "version": 1} and scene["last_valid_pin"] is None
        block = (await scene_service.snapshot()).get_object(shown["object_id"]).payload.prefab
        assert (block.prefab_id, block.version) == ("jarvis.window", 1)          # the previous frame is what stays on screen


# ------------------------------------------------------------------ relais : acteur, garde, pannes

async def test_the_relay_forces_the_actor_to_user_for_source_edits_too(tmp_path):
    async with Core(tmp_path) as core:
        seen = []
        core.stack.core.conversation_event_emitter.add_listener(seen.append)
        pid, vid, revision = await new_presentation(core)
        for claimed in ("brain", "system", None):
            payload = request(revision, {"style": STYLE})
            payload["actor"] = claimed
            if claimed is None:
                del payload["actor"]
            status, result, _ = await core.stack.call("POST", f"{RELAY}/{pid}/variants/{vid}/source-edits", json=payload)
            assert status == 200 and result["actor"] == "user", (claimed, result)
            revision = result["revision"]
        sources = [dict(e.attributes)["source"] for e in seen if e.event_type is T.SYSTEM_PRESENTATION_STUDIO_SCENE_RELOADED]
        assert sources == ["user"] * 3
        event = [e for e in seen if e.event_type is T.SYSTEM_PRESENTATION_STUDIO_SCENE_RELOADED][0]
        assert dict(event.attributes) == {"presentation_id": pid, "variant_id": vid, "scene_id": S1, "status": "repinned",
                                          "revision": 1, "source": "user", "tier": "source"}
        assert event.content is None and event.actor.value == "system" and "abcdef" not in repr(event)
        await core.stack.core.conversation_event_emitter.stop()


@pytest.mark.parametrize("headers", [{"Origin": "null"}, {"Origin": "https://evil.example"},
                                     {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"}])
async def test_a_frame_or_a_foreign_origin_can_neither_edit_a_source_nor_forge_a_mount_report(tmp_path, headers):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        for path, payload in ((f"{RELAY}/{pid}/variants/{vid}/source-edits", request(revision, {"style": STYLE})),
                              (f"{RELAY}/mount-reports", {"object_id": "x", "prefab": {"id": "a.b", "version": 1}, "outcome": "failed"}),
                              (f"{RELAY}/{pid}/variants/{vid}/stage", {"scene_id": S1})):
            status, body, _ = await core.stack.call("POST", path, headers=headers, json=payload)
            assert status == 403, (path, status)
        status, body, _ = await core.stack.call("GET", f"{RELAY}/{pid}/reloads", headers=headers)
        assert status == 403
        assert (await variant_of(core, pid, vid))["revision"] == revision


async def test_the_relay_rejects_bad_bodies_and_reports_core_down_as_a_coded_503(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        url = f"{RELAY}/{pid}/variants/{vid}/source-edits"
        for data in (b"[1,2]", b"{nope"):
            status, payload, _ = await core.stack.call("POST", url, data=data)
            assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await core.stack.call("POST", url + "?actor=brain", json=request(revision, {"style": STYLE}))
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await core.stack.call("POST", f"{RELAY}/mount-reports", json={"object_id": "x"})
        assert (status, payload["error"]["code"]) == (400, "presentation_studio_invalid")
        await core.stack.server.stop()
        status, payload, _ = await core.stack.call("POST", url, json=request(revision, {"style": STYLE}))
        assert (status, payload["error"]["code"]) == (503, "core_unreachable")
        lines = [e for e in core.stack.trace() if e.get("kind") == "presentation_studio.request.core_unreachable"]
        assert lines and lines[-1]["data"]["action"] == "studio_source_edit"


async def test_the_relay_journal_never_holds_source_text_or_a_frame_message(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        status, result, _ = await core.stack.call("POST", f"{RELAY}/{pid}/variants/{vid}/source-edits",
                                                  json=request(revision, {"style": "p{color:#c0ffee}"}))
        assert status == 200
        await core.stack.call("POST", f"{RELAY}/mount-reports", json={
            "object_id": "o", "prefab": result["prefab"], "outcome": "failed", "reason": "frame", "message": "mot de passe: hunter2"})
        rows = [e for e in core.stack.trace() if str(e.get("kind", "")).startswith("presentation_studio.request")]
        assert rows and rows[0]["data"]["action"] == "studio_source_edit" and rows[0]["data"]["result"] == "repinned"
        text = json.dumps(core.stack.trace())
        assert "c0ffee" not in text and "hunter2" not in text


# ------------------------------------------------------------------ espace d'ids reserve (QA 01a I1)

async def test_the_studio_id_namespace_cannot_be_published_through_the_generic_prefab_route(tmp_path):
    from tests.fakes.prefabs import candidate
    from tests.unit.test_presentation_studio_routes import AUTH

    async with Core(tmp_path) as core:
        manifest = {**candidate("test.counter")["manifest"], "id": "presentation-studio.pabcdef012345.sabcdef012345"}
        body = {"actor": "user", "candidate": {**candidate("test.counter"), "manifest": manifest}}
        async with core.http.post(core.stack.core_url + "/v1/prefabs", json=body, headers=AUTH) as response:
            payload = await response.json()
            assert response.status == 400 and payload["error"]["code"] == "invalid_definition"
            assert "reserved for the Presentation Studio" in payload["error"]["message"]
        async with core.http.post(core.stack.core_url + "/v1/prefabs", headers=AUTH, json={
                "actor": "user", "candidate": {**candidate("test.counter"), "manifest": {**manifest, "id": "lab.presentation-studio.x"}}}) as response:
            assert response.status == 201                                    # a look-alike id outside the namespace is an ordinary prefab
        # the Studio itself publishes through the service, not through this door
        pid, vid, revision = await new_presentation(core)
        result = await core.client.presentation_studio_source_edit(pid, vid, request(revision, {"style": STYLE}))
        assert result["status"] == "repinned" and result["prefab"]["id"].startswith("presentation-studio.p")


# ------------------------------------------------------------------ QA-1 : refus types de bout en bout (HTTP)

async def test_an_edit_of_a_scene_being_reloaded_is_a_typed_409_over_http_and_a_neighbour_scene_is_not(tmp_path):
    from tests.unit.test_presentation_studio_edit_routes import body
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        reload_service = core.stack.core.presentation_studio_reload
        reload_service._reloading[(pid, vid, S1)] = 1                         # a reload of S1 is between publication and mount
        edits = f"/{pid}/variants/{vid}/edits"
        status, refused = await core.call("POST", edits, json=body(revision, op_set(S1, "body", "Plan")))
        assert status == 409 and refused["error"]["code"] == "presentation_studio_scene_reloading"
        assert "retry" in refused["error"]["message"]
        status, neighbour = await core.call("POST", edits, json=body(revision, op_set(S2, "body", "Plan")))
        assert status == 200 and neighbour["committed"] is True
        del reload_service._reloading[(pid, vid, S1)]                          # the reload is over
        _, current = await core.call("GET", f"/{pid}/variants/{vid}")
        status, accepted = await core.call("POST", edits, json=body(current["revision"], op_set(S1, "body", "Plan")))
        assert status == 200 and accepted["committed"] is True


async def test_the_agent_rate_limit_is_a_typed_429_over_http_and_the_user_is_not_limited(tmp_path, monkeypatch):
    from jarvis.core import presentation_studio_reload_limits as module
    monkeypatch.setattr(module, "BRAIN_EDIT_LIMIT", 2)
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        url = f"/{pid}/variants/{vid}/source-edits"
        for index in range(2):
            _, current = await core.call("GET", f"/{pid}/variants/{vid}")
            status, _ = await core.call("POST", url, json=request(current["revision"], {"style": f"p{{color:#a0000{index}}}"}, actor="brain",
                                                                  request_id=await pending(core, pid, vid)))
            assert status == 200
        _, current = await core.call("GET", f"/{pid}/variants/{vid}")
        status, refused = await core.call("POST", url, json=request(current["revision"], {"style": "p{color:red}"}, actor="brain",
                                                                    request_id=await pending(core, pid, vid)))
        assert status == 429 and refused["error"]["code"] == "presentation_studio_source_edit_rate"
        status, user = await core.call("POST", url, json=request(current["revision"], {"style": "p{color:red}"}, actor="user"))
        assert status == 200 and user["status"] in ("repinned", "reloaded")


async def test_the_rate_limit_follows_the_verified_channel_not_the_actor_a_body_claims(tmp_path, monkeypatch):
    """The Control Center relay is the one authenticated channel for the page: it REPLACES the body's actor with `user` before Core
    sees it, so a page can never be limited as `brain` nor pass itself off as the agent. Core's `actor` is a label for every other
    caller (a direct bearer-token request): the agent's only door will be Slice 21's tool layer, which sets `brain` itself."""

    from jarvis.core import presentation_studio_reload_limits as module
    monkeypatch.setattr(module, "BRAIN_EDIT_LIMIT", 2)
    async with Core(tmp_path) as core:
        pid, vid, _ = await new_presentation(core)
        relayed = f"{RELAY}/{pid}/variants/{vid}/source-edits"
        for index in range(4):                                                                       # claims `brain` over the relay ...
            _, current = await core.call("GET", f"/{pid}/variants/{vid}")
            status, result, _ = await core.stack.call("POST", relayed, json=request(
                current["revision"], {"style": f"p{{color:#b0000{index}}}"}, actor="brain"))
            assert status == 200 and result["actor"] == "user", (index, status, result)           # ... and is never limited
        direct = f"/{pid}/variants/{vid}/source-edits"
        for index in range(2):                                                                       # a direct caller is what it claims
            _, current = await core.call("GET", f"/{pid}/variants/{vid}")
            status, _ = await core.call("POST", direct, json=request(current["revision"], {"style": f"p{{color:#c0000{index}}}"}, actor="brain",
                                                                     request_id=await pending(core, pid, vid)))
            assert status == 200
        _, current = await core.call("GET", f"/{pid}/variants/{vid}")
        status, refused = await core.call("POST", direct, json=request(current["revision"], {"style": "p{color:red}"}, actor="brain",
                                                                       request_id=await pending(core, pid, vid)))
        assert status == 429 and refused["error"]["code"] == "presentation_studio_source_edit_rate"


async def test_over_http_a_brain_source_edit_needs_a_pending_request_of_the_user_and_the_relay_user_does_not(tmp_path):
    """Remotion Slice 21 (QA B1): coded 403 for none / unknown / another scene; accepted with a pending one; the relay's user needs none."""

    async with Core(tmp_path) as core:
        pid, vid, _ = await new_presentation(core)
        url = f"/{pid}/variants/{vid}/source-edits"
        _, current = await core.call("GET", f"/{pid}/variants/{vid}")
        for extra in ({}, {"request_id": "psq_0000000000ff"}):
            status, refused = await core.call("POST", url, json=request(current["revision"], {"style": "p{color:red}"}, actor="brain", **extra))
            assert status == 403 and refused["error"]["code"] == "presentation_studio_source_request_required", extra
        other = await pending(core, pid, vid, scene_id=S1)
        _, current = await core.call("GET", f"/{pid}/variants/{vid}")
        status, refused = await core.call("POST", url, json=request(current["revision"], {"style": "p{color:red}"}, actor="brain",
                                                                    scene_id="pss_00000000ffff", request_id=other))
        assert status in (403, 404), refused                        # an unknown scene is refused (404) or the request is not its own (403)
        status, done = await core.call("POST", url, json=request(current["revision"], {"style": "p{color:#0a0b0c}"}, actor="brain", request_id=other))
        assert status == 200 and done["request_id"] == other
        _, current = await core.call("GET", f"/{pid}/variants/{vid}")
        status, relayed, _ = await core.stack.call("POST", f"{RELAY}/{pid}/variants/{vid}/source-edits", json=request(
            current["revision"], {"style": "p{color:#0d0e0f}"}, actor="brain"))
        assert status == 200 and relayed["actor"] == "user"
