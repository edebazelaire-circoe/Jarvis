"""Routes Core, client type et relais Control Center de l'historique d'annulation (jarvis-interactive-presentation-studio, Slice 08).

Vrai Core (`JarvisCoreApplication`) derriere le vrai `LocalProtocolServer`, vrai Control Center devant lui : statuts et
corps de chaque issue (`applied`, `history_unavailable`, `nothing_to_undo`, `nothing_to_redo`, `stale`), client type,
acteur force a `user` par le relais, garde d'origine, evenement canonique reel (`undone`/`redone`), journal sans contenu.
Contrat : `docs/presentation-studio.md` > *Persistence and undo contract*.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.protocol.client import CoreProtocolError
from jarvis.protocol.presentation_studio_routes import PREFIX, PresentationStudioProtocolRoutes
from jarvis.runtime.presentation_studio_relay import STUDIO_ROUTE, PresentationStudioRelayRoutes
from tests.unit.test_presentation_studio_edit_routes import S1, S2, body, new_presentation, op_set, scenes_of
from tests.unit.test_presentation_studio_routes import Core

RELAY = STUDIO_ROUTE
HISTORY = "/{presentation_id}/variants/{variant_id}"


def paths(pid, vid):
    base = f"/{pid}/variants/{vid}"
    return base + "/undo", base + "/redo", base + "/history", base + "/edits"


def test_the_route_table_and_the_relay_surface_for_the_history():
    routes = {(r.method, r.path) for r in PresentationStudioProtocolRoutes(object()).routes()}
    for method, tail in (("GET", "history"), ("POST", "undo"), ("POST", "redo")):
        assert (method, f"{PREFIX}{HISTORY}/{tail}") in routes
    relay = PresentationStudioRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    mapped = {(r.method, "/v1/presentation-studio" + r.path[len("/api/presentation-studio"):]) for r in relay.routes()
              if not r.path.startswith("/api/presentation-studio/playback")}   # Slice 12 playback verbs: test_presentation_studio_playback_routes
    assert mapped <= routes
    assert {key for key in mapped if key[0] != "GET"} == {
        ("POST", f"{PREFIX}{HISTORY}/{tail}") for tail in ("edits", "undo", "redo", "source-edits")
    } | {("POST", f"{PREFIX}/mount-reports")}  # the page writes only through these (Slice 06: a source edit and the host's mount report)
    assert ("GET", f"{PREFIX}{HISTORY}/history") in mapped


async def test_undo_and_redo_over_http_with_every_outcome_and_its_status(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        undo, redo, history, edits = paths(pid, vid)
        status, fresh = await core.call("POST", undo, json={"actor": "user"})
        assert status == 409 and fresh["status"] == "history_unavailable" and fresh["reason"] == "not_recorded_since_start"
        assert fresh["error"]["code"] == "presentation_studio_history_unavailable" and fresh["revision"] == revision
        status, applied = await core.call("POST", edits, json=body(revision, op_set(S1, "body", "Bonjour")))
        assert status == 200 and applied["status"] == "applied"
        status, state = await core.call("GET", history)
        assert status == 200 and state["tracked"] is True and state["undo_count"] == 1 and state["in_sync"] is True
        assert state["durable"] is False and state["stats"]["limits"]["entries_per_variant"] == 32
        head = state["next_undo"]["entry_id"]
        status, wrong = await core.call("POST", undo, json={"actor": "brain", "expected_entry_id": "psh_" + "0" * 12})
        assert status == 409 and wrong["status"] == "stale" and wrong["error"]["code"] == "presentation_studio_history_stale"
        _, still = await core.call("GET", f"/{pid}/variants/{vid}")
        assert still["revision"] == revision + 1  # a stale undo writes nothing
        status, undone = await core.call("POST", undo, json={"actor": "brain", "expected_entry_id": head})
        assert status == 200 and undone["status"] == "applied" and undone["revision"] == revision + 2 and "error" not in undone
        assert undone["entry"]["entry_id"] == head and undone["history"]["redo_count"] == 1 and undone["tier"] == "control"
        status, empty = await core.call("POST", undo, json={"actor": "user"})
        assert status == 409 and empty["status"] == "nothing_to_undo" and empty["error"]["code"] == "presentation_studio_history_empty"
        status, redone = await core.call("POST", redo, json={"actor": "user"})
        assert status == 200 and redone["status"] == "applied" and redone["revision"] == revision + 3
        status, nothing = await core.call("POST", redo, json={"actor": "user"})
        assert status == 409 and nothing["status"] == "nothing_to_redo"
        _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
        assert variant["scenes"][0]["data"]["body"] == "Bonjour"


async def test_malformed_and_unknown_history_requests_are_coded_envelopes(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        undo, redo, history, _ = paths(pid, vid)

        async def code(method, path, **kw):
            status, payload = await core.call(method, path, **kw)
            assert set(payload) == {"error"}, payload
            return status, payload["error"]["code"]

        assert await code("POST", undo, json={"actor": "root"}) == (400, "presentation_studio_invalid")
        assert await code("POST", undo, json={}) == (400, "presentation_studio_invalid")
        assert await code("POST", undo, json={"actor": "user", "mode": "commit"}) == (400, "presentation_studio_invalid")
        assert await code("POST", undo, data=b"not json") == (400, "invalid_request")
        assert await code("POST", redo, data=b"x" * (4 * 1024 + 10)) == (400, "invalid_request")
        assert await code("POST", undo + "?actor=brain", json={"actor": "user"}) == (400, "invalid_request")
        assert await code("GET", history + "?x=1") == (400, "invalid_request")
        ghost = f"/{pid}/variants/psv_{'0' * 32}"
        assert await code("POST", ghost + "/undo", json={"actor": "user"}) == (404, "presentation_studio_unknown_variant")
        assert await code("GET", ghost + "/history") == (404, "presentation_studio_unknown_variant")
        async with core.http.post(core.stack.core_url + PREFIX + undo, json={"actor": "user"}) as response:
            assert response.status == 401  # the bearer token is required


async def test_the_typed_client_returns_every_outcome_and_raises_on_envelopes(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        client = core.client
        assert (await client.presentation_studio_undo(pid, vid, {"actor": "brain"}))["status"] == "history_unavailable"
        await client.presentation_studio_edit(pid, vid, body(revision, op_set(S1, "body", "Client")))
        state = await client.presentation_studio_history(pid, vid)
        assert state["undo_count"] == 1 and state["next_undo"]["ops"] == ["control.set"]
        stale = await client.presentation_studio_undo(pid, vid, {"actor": "brain", "expected_entry_id": "psh_" + "1" * 12})
        assert stale["status"] == "stale"
        applied = await client.presentation_studio_undo(pid, vid, {"actor": "brain"})
        assert applied["status"] == "applied" and applied["actor"] == "brain"
        assert (await client.presentation_studio_undo(pid, vid, {"actor": "brain"}))["status"] == "nothing_to_undo"
        assert (await client.presentation_studio_redo(pid, vid, {"actor": "brain"}))["status"] == "applied"
        assert (await client.presentation_studio_redo(pid, vid, {"actor": "brain"}))["status"] == "nothing_to_redo"
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_undo(pid, vid, {"actor": "nobody"})
        assert (caught.value.status, caught.value.code) == (400, "presentation_studio_invalid")
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_redo(pid, "psv_" + "0" * 32, {"actor": "brain"})
        assert caught.value.code == "presentation_studio_unknown_variant"
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_history(pid, "psv_" + "0" * 32)
        assert caught.value.status == 404


async def test_the_canonical_event_says_undone_and_redone_with_ids_and_never_content(tmp_path):
    async with Core(tmp_path) as core:
        seen = []
        core.stack.core.conversation_event_emitter.add_listener(seen.append)
        pid, vid, revision = await new_presentation(core)
        await core.client.presentation_studio_edit(pid, vid, body(revision, op_set(S1, "body", "Texte secret")))
        await core.client.presentation_studio_undo(pid, vid, {"actor": "brain"})
        await core.client.presentation_studio_redo(pid, vid, {"actor": "user"})
        events = [e for e in seen if e.event_type is T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED]
        assert [dict(e.attributes)["status"] for e in events] == ["applied", "undone", "redone"]
        assert [dict(e.attributes)["source"] for e in events] == ["brain", "brain", "user"]
        assert [dict(e.attributes)["revision"] for e in events] == [revision + 1, revision + 2, revision + 3]
        assert all(e.content is None and "secret" not in repr(e) for e in events)
        await core.stack.core.conversation_event_emitter.stop()


# ------------------------------------------------------------------ relais

async def test_the_relay_forces_the_actor_to_user_for_undo_and_redo_and_reads_the_history(tmp_path):
    async with Core(tmp_path) as core:
        seen = []
        core.stack.core.conversation_event_emitter.add_listener(seen.append)
        pid, vid, revision = await new_presentation(core)
        await core.client.presentation_studio_edit(pid, vid, body(revision, op_set(S1, "body", "A"), op_set(S2, "body", "B")))
        undo, redo, history, _ = paths(pid, vid)
        call = core.stack.call
        status, via_page, _ = await call("GET", RELAY + history)
        _, direct = await core.call("GET", history)
        assert (status, via_page) == (200, direct)
        for claimed, verb in (("brain", undo), ("system", redo), (None, undo), ("root", redo)):
            payload = {"actor": claimed} if claimed is not None else {}
            status, result, _ = await call("POST", RELAY + verb, json=payload)
            assert status == 200 and result["actor"] == "user", (claimed, result)
        sources = [dict(e.attributes)["source"] for e in seen if e.event_type is T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED]
        assert sources[1:] == ["user"] * 4
        status, nothing, _ = await call("POST", RELAY + redo, json={"actor": "brain"})
        assert (status, nothing["status"], nothing["actor"]) == (409, "nothing_to_redo", "user")
        status, error, _ = await call("POST", RELAY + undo, json={"actor": "brain", "expected_entry_id": "psh_" + "2" * 12})
        assert (status, error["status"], error["actor"]) == (409, "stale", "user")


async def test_the_page_and_the_brain_reach_the_same_canonical_state_through_undo(tmp_path):
    async with Core(tmp_path) as core:
        ops = [op_set(S1, "body", "Meme resultat"), {"op": "scene.reorder", "scene_id": S2, "to_index": 0}]
        pid_a, vid_a, rev_a = await new_presentation(core, "Page")
        pid_b, vid_b, rev_b = await new_presentation(core, "Voix")
        await core.client.presentation_studio_edit(pid_a, vid_a, body(rev_a, *ops))
        await core.client.presentation_studio_edit(pid_b, vid_b, body(rev_b, *ops))
        undo_a = (await core.stack.call("POST", RELAY + paths(pid_a, vid_a)[0], json={"actor": "brain"}))[1]
        undo_b = await core.client.presentation_studio_undo(pid_b, vid_b, {"actor": "brain"})
        assert undo_a["actor"] == "user" and undo_b["actor"] == "brain"

        def scrub(value):
            if isinstance(value, dict):
                return {k: scrub(v) for k, v in value.items() if k not in ("actor", "entry_id", "presentation_id", "variant_id")}
            return [scrub(v) for v in value] if isinstance(value, list) else value

        assert scrub(undo_a) == scrub(undo_b)
        _, state_a = await core.call("GET", f"/{pid_a}/variants/{vid_a}")
        _, state_b = await core.call("GET", f"/{pid_b}/variants/{vid_b}")
        assert scenes_of(state_a) == scenes_of(state_b) and state_a["revision"] == state_b["revision"]


@pytest.mark.parametrize("headers", [{"Origin": "null"}, {"Origin": "https://evil.example"},
                                     {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"}])
async def test_a_frame_or_a_foreign_origin_can_neither_undo_nor_read_the_history(tmp_path, headers):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        await core.client.presentation_studio_edit(pid, vid, body(revision, op_set(S1, "body", "A")))
        undo, redo, history, _ = paths(pid, vid)
        status, payload, _ = await core.stack.call("GET", RELAY + history, headers=headers)
        assert status == 403 and payload["code"] == "forbidden_origin"
        for verb in (undo, redo):
            status, _, _ = await core.stack.call("POST", RELAY + verb, headers=headers, json={"actor": "user"})
            assert status == 403
        _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
        assert variant["revision"] == revision + 1


async def test_the_relay_exposes_no_other_history_write_and_rejects_malformed_bodies(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        undo, redo, history, _ = paths(pid, vid)
        for method, path in (("PUT", history), ("DELETE", history), ("POST", history), ("PUT", undo), ("GET", undo)):
            status, _, _ = await core.stack.call(method, RELAY + path, json={"actor": "user"})
            assert status in (404, 405), (method, path, status)
        status, payload, _ = await core.stack.call("POST", RELAY + undo, data=b"[1]")
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await core.stack.call("POST", RELAY + undo + "?actor=brain", json={"actor": "user"})
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await core.stack.call("POST", RELAY + undo, json={"actor": "user", "mode": "commit"})
        assert (status, payload["error"]["code"]) == (400, "presentation_studio_invalid")


async def test_the_relay_journal_for_undo_never_holds_a_value(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        await core.client.presentation_studio_edit(pid, vid, body(revision, op_set(S1, "body", "Valeur privee")))
        undo, redo, _, _ = paths(pid, vid)
        status, result, _ = await core.stack.call("POST", RELAY + undo, json={"actor": "user"})
        assert status == 200
        rows = [e for e in core.stack.trace() if str(e.get("kind", "")).startswith("presentation_studio.request")]
        assert rows and rows[-1]["data"]["action"] == "studio_undo" and rows[-1]["data"]["result"] == "applied"
        assert "privee" not in json.dumps(core.stack.trace())


# ------------------------------------------------------------------ rework (QA-1 P3)

STEP = {"direction": "undo", "entry_id": "psh_" + "a" * 12}


async def test_a_step_in_a_body_is_refused_by_core_the_relay_and_the_typed_client_and_touches_nothing(tmp_path):
    """P3: `step` is the in-process key by which an undo marks its commit. No request body may carry it, whatever the door."""

    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        await core.client.presentation_studio_edit(pid, vid, body(revision, op_set(S1, "body", "A")))
        undo, redo, history, edits = paths(pid, vid)
        _, before = await core.call("GET", history)
        head = before["next_undo"]["entry_id"]
        edit_body = body(revision + 1, op_set(S1, "body", "B"))
        nested = {**edit_body, "ops": [{**edit_body["ops"][0], "step": {"direction": "undo", "entry_id": head}}]}
        for payload in ({**edit_body, "step": {"direction": "undo", "entry_id": head}}, nested,
                        {**edit_body, "history": {"direction": "undo"}}):
            status, result = await core.call("POST", edits, json=payload)
            assert (status, result["error"]["code"]) == (400, "presentation_studio_invalid"), payload
            status, result, _ = await core.stack.call("POST", RELAY + edits, json=payload)
            assert (status, result["error"]["code"]) == (400, "presentation_studio_invalid"), payload
            with pytest.raises(CoreProtocolError) as caught:
                await core.client.presentation_studio_edit(pid, vid, payload)
            assert (caught.value.status, caught.value.code) == (400, "presentation_studio_invalid")
        for verb in (undo, redo):
            for payload in ({"actor": "user", "step": STEP}, {"actor": "user", "direction": "undo", "entry_id": head}):
                status, result = await core.call("POST", verb, json=payload)
                assert (status, result["error"]["code"]) == (400, "presentation_studio_invalid"), payload
                status, result, _ = await core.stack.call("POST", RELAY + verb, json=payload)
                assert (status, result["error"]["code"]) == (400, "presentation_studio_invalid"), payload
                with pytest.raises(CoreProtocolError):
                    await core.client.presentation_studio_undo(pid, vid, payload)
        _, after = await core.call("GET", history)
        assert after == before  # not a revision, not an entry moved
        _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
        assert variant["revision"] == revision + 1 and variant["scenes"][0]["data"]["body"] == "A"


def test_the_typed_client_and_the_routes_expose_no_step_parameter():
    import inspect

    from jarvis.protocol.client import LocalCoreClient

    for name in ("presentation_studio_edit", "presentation_studio_undo", "presentation_studio_redo"):
        assert "step" not in inspect.signature(getattr(LocalCoreClient, name)).parameters, name
    source = inspect.getsource(PresentationStudioProtocolRoutes)
    assert "step=" not in source and "step:" not in source  # the Core routes never pass one to `edit`
