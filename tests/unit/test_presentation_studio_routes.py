"""Routes Core et client typé des Presentations (jarvis-interactive-presentation-studio, Slice 02).

Vrai Core (`JarvisCoreApplication`, racine de données de test) derrière le vrai
`LocalProtocolServer` : jeton exigé, cycle créer/charger/lister/sauvegarder/
valider, refus codés, redémarrage, imprévu journalisé. Contrat :
`jarvis/protocol/presentation_studio_routes.py`, `docs/presentation-studio.md`.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import aiohttp
from aiohttp.test_utils import make_mocked_request
import pytest

from jarvis.protocol import client as client_module
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.presentation_studio_routes import PREFIX, PresentationStudioProtocolRoutes
from tests.fakes.capture_stack import TOKEN, CaptureStack

AUTH = {"Authorization": f"Bearer {TOKEN}"}
SCENES = [{"scene_id": "pss_000000000001", "prefab": {"id": "jarvis.window", "version": 1}}]


class Core:
    """`async with Core(tmp_path) as core` : `core.call(method, path, **kw) -> (status, json)` direct sur Core."""

    def __init__(self, tmp_path) -> None:
        self.stack = CaptureStack(tmp_path)

    async def __aenter__(self) -> "Core":
        await self.stack.__aenter__()
        self.http = aiohttp.ClientSession()
        port = int(self.stack.core_url.rsplit(":", 1)[1])
        self.client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
        return self

    async def __aexit__(self, *exc) -> None:
        await self.client.close()
        await self.http.close()
        await self.stack.__aexit__(*exc)

    async def call(self, method: str, path: str, *, headers: dict | None = None, **kwargs):
        async with self.http.request(method, self.stack.core_url + PREFIX + path, headers={**AUTH, **(headers or {})},
                                     **kwargs) as response:
            return response.status, await response.json(content_type=None)


def variant_body(variant: dict, **changes) -> dict:
    return {"expected_revision": variant["revision"], "title": variant["title"], "scenes": variant["scenes"],
            "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"], **changes}


def test_the_route_table_has_the_fixed_segment_before_the_id():
    routes = [(route.method, route.path) for route in PresentationStudioProtocolRoutes(object()).routes()]
    assert routes == [
        ("GET", PREFIX), ("POST", PREFIX), ("POST", PREFIX + "/validate"), ("POST", PREFIX + "/mount-reports"),
        ("GET", PREFIX + "/{presentation_id}"),
        ("PUT", PREFIX + "/{presentation_id}"), ("GET", PREFIX + "/{presentation_id}/variants/{variant_id}"),
        ("PUT", PREFIX + "/{presentation_id}/variants/{variant_id}"),
        ("GET", PREFIX + "/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/controls"),
        # Slice 09: the art direction
        ("GET", PREFIX + "/{presentation_id}/variants/{variant_id}/art-direction"),
        ("POST", PREFIX + "/{presentation_id}/variants/{variant_id}/art-direction"),
        ("PUT", PREFIX + "/{presentation_id}/variants/{variant_id}/art-direction"),
        ("POST", PREFIX + "/{presentation_id}/variants/{variant_id}/art-direction/fallback"),
        ("POST", PREFIX + "/{presentation_id}/variants/{variant_id}/art-direction/candidates"),
        # Slice 10: the score
        ("GET", PREFIX + "/{presentation_id}/variants/{variant_id}/score"),
        ("POST", PREFIX + "/{presentation_id}/variants/{variant_id}/score"),
        ("PUT", PREFIX + "/{presentation_id}/variants/{variant_id}/score"),
        # Slice 05: the semantic edit API and the control proposals
        ("GET", PREFIX + "/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/control-suggestions"),
        ("POST", PREFIX + "/{presentation_id}/variants/{variant_id}/edits"),
        # Slice 06: hot reload of a scene source, recent reloads (the page's mount reports are a separate, relayed route)
        ("POST", PREFIX + "/{presentation_id}/variants/{variant_id}/source-edits"),
        # Slice 14: the agent reads the scene source before proposing a file edit
        ("GET", PREFIX + "/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/source"),
        ("GET", PREFIX + "/{presentation_id}/reloads"),
        # Slice 08: the bounded undo history (memory only); an undo is an edit through the same service
        ("GET", PREFIX + "/{presentation_id}/variants/{variant_id}/history"),
        ("POST", PREFIX + "/{presentation_id}/variants/{variant_id}/undo"),
        ("POST", PREFIX + "/{presentation_id}/variants/{variant_id}/redo")]
    assert PREFIX == "/v1/presentation-studio/presentations" == client_module.STUDIO_PREFIX


async def test_the_token_is_required(tmp_path):
    async with Core(tmp_path) as core:
        async with core.http.get(core.stack.core_url + PREFIX) as response:
            assert response.status == 401
        async with core.http.post(core.stack.core_url + PREFIX, json={"title": "x"}) as response:
            assert response.status == 401
        status, body = await core.call("GET", "")
        assert status == 200 and body == {"presentations": [], "problems": []}  # first run: nothing, not an error


async def test_the_full_lifecycle_over_http(tmp_path):
    async with Core(tmp_path) as core:
        status, created = await core.call("POST", "", json={"title": "Atelier"})
        assert status == 201 and created["presentation"]["schema_version"] == 3
        pid = created["presentation"]["presentation_id"]
        variant = created["variants"][0]
        vid = variant["variant_id"]

        status, saved = await core.call("PUT", f"/{pid}/variants/{vid}",
                                        json=variant_body(variant, scenes=SCENES, title="Version A"))
        assert status == 200 and saved["revision"] == 2
        assert [(s["scene_id"], s["prefab"]) for s in saved["scenes"]] == [(s["scene_id"], s["prefab"]) for s in SCENES]
        status, saved_p = await core.call("PUT", f"/{pid}", json={
            "expected_revision": 1, "title": "Atelier 2", "active_variant_id": vid,
            "resources": [{"kind": "web_page", "locator": "https://example.org", "title": "Ex"}]})
        assert status == 200 and saved_p["revision"] == 2 and saved_p["resources"][0]["title"] == "Ex"

        status, loaded = await core.call("GET", f"/{pid}")
        assert status == 200 and loaded == {"presentation": saved_p, "variants": [saved]}
        status, one = await core.call("GET", f"/{pid}/variants/{vid}")
        assert status == 200 and one == saved
        status, listing = await core.call("GET", "", params={"limit": "5"})
        assert status == 200 and [r["title"] for r in listing["presentations"]] == ["Atelier 2"]
        status, report = await core.call("POST", "/validate", json=loaded)
        assert status == 200 and report == {"ok": True, "errors": []}


async def test_data_survives_a_core_restart(tmp_path):
    async with Core(tmp_path) as core:
        status, created = await core.call("POST", "", json={"title": "Durable"})
        pid = created["presentation"]["presentation_id"]
    async with Core(tmp_path) as again:
        status, loaded = await again.call("GET", f"/{pid}")
        assert status == 200 and loaded["presentation"] == created["presentation"]


async def test_refusals_are_coded_envelopes_with_their_status(tmp_path):
    async with Core(tmp_path) as core:
        _, created = await core.call("POST", "", json={"title": "A"})
        pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
        vid = variant["variant_id"]

        async def code(method, path, **kwargs):
            status, body = await core.call(method, path, **kwargs)
            assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}, body
            return status, body["error"]["code"]

        assert await code("GET", "/pst_" + "0" * 32) == (404, "presentation_studio_unknown_presentation")
        assert await code("GET", f"/{pid}/variants/psv_" + "0" * 32) == (404, "presentation_studio_unknown_variant")
        assert await code("GET", "/not-an-id") == (404, "presentation_studio_unknown_presentation")
        assert await code("POST", "", json={"title": ""}) == (400, "presentation_studio_invalid")
        assert await code("POST", "", json={"title": "x", "extra": 1}) == (400, "presentation_studio_invalid")
        assert await code("PUT", f"/{pid}/variants/{vid}", json=variant_body(variant, playback={"state": "running"})) == (
            400, "presentation_studio_runtime_state_refused")
        assert await code("PUT", f"/{pid}/variants/{vid}", json=variant_body(variant, scenes=[{
            "scene_id": "pss_000000000001", "prefab": {"id": "jarvis.window", "version": 1}, "manifest": {"a": 1}}])) == (
            400, "presentation_studio_invalid")
        # a value the pinned prefab does not declare: refused by the real PrefabService through the real Core
        assert await code("PUT", f"/{pid}/variants/{vid}", json=variant_body(variant, scenes=[{
            "scene_id": "pss_000000000001", "prefab": {"id": "jarvis.window", "version": 1}, "props": {"a": 1}}])) == (
            400, "presentation_studio_scene_incompatible")
        assert await code("PUT", f"/{pid}/variants/{vid}", json=variant_body(variant, expected_revision=5)) == (
            409, "presentation_studio_stale_revision")
        assert await code("PUT", f"/{pid}", json={"expected_revision": 1, "title": "A", "resources": [],
                                                  "active_variant_id": "psv_" + "5" * 32}) == (
            404, "presentation_studio_unknown_variant")
        # malformed requests: coded `invalid_request`, never a bare 500
        assert await code("POST", "", data=b"{not json") == (400, "invalid_request")
        assert await code("POST", "", data=b'{"title": "a", "title": "b"}') == (400, "invalid_request")
        assert await code("POST", "", data=b'{"title": "' + b"x" * 300_000 + b'"}') == (400, "invalid_request")
        assert await code("GET", "", params={"limit": "0"}) == (400, "invalid_request")
        assert await code("GET", "", params={"bogus": "1"}) == (400, "invalid_request")
        assert await code("GET", f"/{pid}", params={"x": "1"}) == (400, "invalid_request")
        status, report = await core.call("POST", "/validate", data=b"[]")  # validation answers, it does not fail
        assert status == 200 and report["ok"] is False and "JSON object" in report["errors"][0]["message"]
        assert await code("POST", "/validate", data=b"{oops") == (400, "invalid_request")
        status, report = await core.call("POST", "/validate", json={"presentation": {}, "variants": []})
        assert status == 200 and report["ok"] is False and report["errors"][0]["code"] == "presentation_studio_invalid"


async def test_a_future_document_is_a_409_that_leaves_the_file_alone_and_the_listing_names_it(tmp_path):
    async with Core(tmp_path) as core:
        _, created = await core.call("POST", "", json={"title": "A"})
        pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
        path = tmp_path / "data" / "presentations" / pid / "variants" / f"{variant['variant_id']}.json"
        path.write_text(json.dumps({**variant, "schema_version": 5}), encoding="utf-8")
        snapshot = path.read_bytes()
        status, body = await core.call("PUT", f"/{pid}/variants/{variant['variant_id']}", json=variant_body(variant))
        assert (status, body["error"]["code"]) == (409, "presentation_studio_unsupported_schema_version")
        assert path.read_bytes() == snapshot
        status, body = await core.call("GET", "")
        assert status == 200 and body["presentations"][0]["presentation_id"] == pid  # the manifest itself is fine
        status, body = await core.call("GET", f"/{pid}")
        assert status == 409 and "schema_version 5" in body["error"]["message"]


async def test_error_messages_never_carry_an_absolute_path(tmp_path):
    async with Core(tmp_path) as core:
        _, created = await core.call("POST", "", json={"title": "A"})
        pid = created["presentation"]["presentation_id"]
        (tmp_path / "data" / "presentations" / pid / "presentation.json").write_text("{nope", encoding="utf-8")
        status, body = await core.call("GET", f"/{pid}")
        assert status == 409 and str(tmp_path) not in json.dumps(body)


async def test_an_unexpected_failure_is_a_coded_500_and_lands_in_the_error_log(tmp_path):
    rows: list[tuple] = []

    class Sink:
        def emit(self, kind, message, *, level="info", data=None) -> None:
            rows.append((kind, level, data))

    async with Core(tmp_path) as core:
        service = core.stack.core.presentation_studio
        service._diagnostics = Sink()

        async def explode(_pid):
            raise RuntimeError("kaboom")

        service.get = explode
        status, body = await core.call("GET", "/pst_" + "0" * 32)
        assert status == 500 and body["error"]["code"] == "internal_error" and "RuntimeError" in body["error"]["message"]
        assert [(kind, level) for kind, level, _ in rows] == [("core.presentation_studio.unexpected", "error")]
        assert "kaboom" in rows[0][2]["error"] and rows[0][2]["op"].startswith("GET ")


async def test_the_route_answers_503_before_core_is_ready():
    routes = PresentationStudioProtocolRoutes(SimpleNamespace(health=SimpleNamespace(ready=False)))

    async def never(_request):
        raise AssertionError("must not run")

    response = await routes._guarded(never)(make_mocked_request("GET", PREFIX))
    assert response.status == 503 and json.loads(response.body)["error"]["code"] == "core_unavailable"


async def test_the_typed_client_round_trips_and_raises_core_protocol_error(tmp_path):
    async with Core(tmp_path) as core:
        client = core.client
        created = await client.presentation_studio_create("Via client")
        pid = created["presentation"]["presentation_id"]
        variant = created["variants"][0]
        saved = await client.presentation_studio_save_variant(pid, variant["variant_id"], variant_body(variant, scenes=SCENES))
        assert saved["revision"] == 2 and (await client.presentation_studio_variant(pid, variant["variant_id"])) == saved
        saved_p = await client.presentation_studio_save(pid, {
            "expected_revision": 1, "title": "Via client 2", "active_variant_id": variant["variant_id"], "resources": []})
        loaded = await client.presentation_studio_get(pid)
        assert loaded == {"presentation": saved_p, "variants": [saved]}
        assert (await client.presentation_studio_list(limit=3))["presentations"][0]["title"] == "Via client 2"
        assert (await client.presentation_studio_validate(loaded)) == {"ok": True, "errors": []}
        with pytest.raises(CoreProtocolError) as stale:
            await client.presentation_studio_save_variant(pid, variant["variant_id"], variant_body(variant))
        assert (stale.value.status, stale.value.code) == (409, "presentation_studio_stale_revision")
        with pytest.raises(CoreProtocolError) as missing:
            await client.presentation_studio_get("pst_" + "0" * 32)
        assert (missing.value.status, missing.value.code) == (404, "presentation_studio_unknown_presentation")
        with pytest.raises(CoreProtocolError) as bad:
            await client.presentation_studio_create("")
        assert bad.value.code == "presentation_studio_invalid"


async def test_the_client_relays_only_the_presentation_tree_through_forward_json(tmp_path):
    """Slice 05 added the relay (`presentation_studio_relay.py`): `forward_json` admits the presentations tree (and, Slice 12, the
    playback tree), which the relay reaches only through the fixed paths it builds; anything else of the Studio namespace
    (the cue report included) stays refused."""

    client = LocalCoreClient(host="127.0.0.1", port=9, token=TOKEN)
    try:
        for path in ("/v1/presentation-studio", "/v1/presentation-studio/cues/satisfied", "/v1/presentation-studioX/presentations"):
            with pytest.raises(ValueError):
                await client.forward_json("GET", path)
        assert client_module.STUDIO_PREFIX in client_module.FORWARDABLE_PREFIXES
        assert client_module.PLAYBACK_PREFIX in client_module.FORWARDABLE_PREFIXES   # Slice 12: playback state + verbs only
    finally:
        await client.close()


# ------------------------------------------------------------------ Slice 04 : introspection des controles d'une scene

SID = "pss_0000000000a1"
WINDOW_SCENE = {
    "scene_id": SID, "prefab": {"id": "jarvis.window", "version": 1}, "title": "Ouverture", "section": "Intro",
    "props": {"accent": "#ff8800"}, "data": {"body": "Bonjour"},
    "controls": [
        {"control_id": "accent_color", "path": "props.accent", "label": "Accent", "group": "visual",
         "meaning": "Couleur des liens"},
        {"control_id": "spacing", "path": "props.density", "label": "Densite", "group": "layout"},
        {"control_id": "body_text", "path": "data.body", "label": "Texte", "group": "content",
         "bounds": {"max_length": 200}}],
    "anchors": [{"anchor_id": "show_text", "label": "Montrer le texte", "control_id": "body_text"}],
    "preview": {"caption": "Intro", "alt": "Fenetre de texte"}}


async def scene_presentation(core, scenes=None):
    _, created = await core.call("POST", "", json={"title": "A"})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    status, saved = await core.call("PUT", f"/{pid}/variants/{variant['variant_id']}",
                                    json=variant_body(variant, scenes=[WINDOW_SCENE] if scenes is None else scenes))
    assert status == 200, saved
    return pid, saved


async def test_the_controls_route_answers_what_is_editable_on_a_scene_with_the_real_prefab_catalog(tmp_path):
    async with Core(tmp_path) as core:
        pid, variant = await scene_presentation(core)
        vid = variant["variant_id"]
        status, body = await core.call("GET", f"/{pid}/variants/{vid}/scenes/{SID}/controls")
        assert status == 200 and body["scene_id"] == SID and body["variant_revision"] == variant["revision"]
        assert body["prefab"] == {"id": "jarvis.window", "version": 1} and body["problems"] == []
        controls = {c["control_id"]: c for c in body["controls"]}
        assert list(controls) == ["accent_color", "spacing", "body_text"]
        assert (controls["accent_color"]["widget"], controls["accent_color"]["current"]) == ("color", "#ff8800")
        assert controls["spacing"]["widget"] == "choice" and controls["spacing"]["bounds"] == {
            "choices": ["compact", "comfortable"]} and controls["spacing"]["current"] == "comfortable"
        assert controls["body_text"]["bounds"] == {"max_length": 200} and controls["body_text"]["widget"] == "text_area"
        assert body["payload"]["limit"] == 16_384 and body["stage"]["prefab_key"] == "jarvis.window@1"
        again = await core.call("GET", f"/{pid}/variants/{vid}/scenes/{SID}/controls")
        assert again == (200, body)  # stable across calls
        assert await core.client.presentation_studio_scene_controls(pid, vid, SID) == body  # the typed client agrees


async def test_the_controls_route_refusals_are_coded(tmp_path):
    async with Core(tmp_path) as core:
        pid, variant = await scene_presentation(core)
        vid = variant["variant_id"]

        async def code(path, **kwargs):
            status, body = await core.call("GET", path, **kwargs)
            return status, body["error"]["code"]

        base = f"/{pid}/variants/{vid}/scenes"
        assert await code(f"{base}/pss_ffffffffffff/controls") == (404, "presentation_studio_unknown_scene")
        assert await code(f"{base}/not-a-scene/controls") == (404, "presentation_studio_unknown_scene")
        assert await code(f"/{pid}/variants/psv_{'1' * 32}/scenes/{SID}/controls") == (404, "presentation_studio_unknown_variant")
        assert await code(f"/pst_{'1' * 32}/variants/{vid}/scenes/{SID}/controls") == (404, "presentation_studio_unknown_presentation")
        assert await code(f"{base}/{SID}/controls", params={"x": "1"}) == (400, "invalid_request")
        async with core.http.get(core.stack.core_url + PREFIX + f"{base}/{SID}/controls") as response:
            assert response.status == 401  # the bearer token is required here too
        with pytest.raises(CoreProtocolError) as missing:
            await core.client.presentation_studio_scene_controls(pid, vid, "pss_ffffffffffff")
        assert (missing.value.status, missing.value.code) == (404, "presentation_studio_unknown_scene")


async def test_a_scene_pinned_to_a_missing_prefab_is_refused_at_save_and_nothing_is_written(tmp_path):
    async with Core(tmp_path) as core:
        _, created = await core.call("POST", "", json={"title": "A"})
        pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
        ghost = {"scene_id": SID, "prefab": {"id": "lab.ghost", "version": 1}}
        status, body = await core.call("PUT", f"/{pid}/variants/{variant['variant_id']}",
                                       json=variant_body(variant, scenes=[ghost]))
        assert status == 409 and body["error"]["code"] == "presentation_studio_prefab_unavailable"
        assert "unknown_prefab" in body["error"]["message"] and str(tmp_path) not in json.dumps(body)
        status, loaded = await core.call("GET", f"/{pid}/variants/{variant['variant_id']}")
        assert loaded["scenes"] == [] and loaded["revision"] == variant["revision"]  # not written


async def test_controls_stored_before_a_restart_describe_identically_after_it(tmp_path):
    async with Core(tmp_path) as core:
        pid, variant = await scene_presentation(core)
        vid = variant["variant_id"]
        _, before = await core.call("GET", f"/{pid}/variants/{vid}/scenes/{SID}/controls")
    async with Core(tmp_path) as again:
        status, after = await again.call("GET", f"/{pid}/variants/{vid}/scenes/{SID}/controls")
        assert status == 200 and after == before


async def test_the_http_statuses_of_a_refused_scene_are_400_incompatible_and_409_unavailable(tmp_path):
    async with Core(tmp_path) as core:
        _, created = await core.call("POST", "", json={"title": "A"})
        pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
        url = f"/{pid}/variants/{variant['variant_id']}"
        bad_value = {**WINDOW_SCENE, "controls": [], "anchors": [], "props": {"density": "huge"}}
        status, body = await core.call("PUT", url, json=variant_body(variant, scenes=[bad_value]))
        assert (status, body["error"]["code"]) == (400, "presentation_studio_scene_incompatible")
        assert "density" in body["error"]["message"]
        ghost = {"scene_id": SID, "prefab": {"id": "lab.ghost", "version": 1}}
        status, body = await core.call("PUT", url, json=variant_body(variant, scenes=[ghost]))
        assert (status, body["error"]["code"]) == (409, "presentation_studio_prefab_unavailable")
        wrong_version = {"scene_id": SID, "prefab": {"id": "jarvis.window", "version": 99}}
        status, body = await core.call("PUT", url, json=variant_body(variant, scenes=[wrong_version]))
        assert (status, body["error"]["code"]) == (409, "presentation_studio_prefab_unavailable")
        assert "unknown_version" in body["error"]["message"]


# ------------------------------------------------------------------ Slice 10 : partition

ITEM_1, ITEM_2, ITEM_3 = "psi_000000000001", "psi_000000000002", "psi_000000000003"
CUE_1 = "psc_000000000001"


def score_content(**changes) -> dict:
    content = {
        "start_item_id": ITEM_1,
        "items": [
            {"item_id": ITEM_1, "scene_id": SID, "presenter": "jarvis", "kind": "speech", "text": "Bonjour.",
             "visual": [{"kind": "reveal", "scene_id": SID, "anchor_id": "show_text"}], "next_item_id": ITEM_2},
            {"item_id": ITEM_2, "scene_id": SID, "presenter": "user", "kind": "speech", "note": "Context",
             "cue_id": CUE_1, "next_item_id": ITEM_3},
            {"item_id": ITEM_3, "scene_id": SID, "presenter": "none", "kind": "silence", "target_duration_ms": 2000}],
        "cues": [{"cue_id": CUE_1, "label": "Go", "armable": True, "predicate": {"phrases": ["on continue"]}}],
        "sequences": [], "recovery_points": []}
    return {**content, **changes}


async def test_the_score_lifecycle_over_http(tmp_path):
    async with Core(tmp_path) as core:
        pid, variant = await scene_presentation(core)
        vid = variant["variant_id"]
        base = f"/{pid}/variants/{vid}/score"

        status, body = await core.call("GET", base)
        assert (status, body["error"]["code"]) == (404, "presentation_studio_unknown_score")  # none yet, coded not empty

        status, created = await core.call("POST", base, json={"expected_variant_revision": variant["revision"],
                                                              **score_content()})
        assert status == 201 and created["problems"] == [] and created["score"]["revision"] == 1
        score = created["score"]
        assert score["schema"] == "jarvis.presentation_studio.score" and score["variant_id"] == vid

        status, again = await core.call("GET", base)
        assert (status, again) == (200, created)
        status, one = await core.call("GET", f"/{pid}/variants/{vid}")
        assert one["score_id"] == score["score_id"] and one["revision"] == variant["revision"] + 1

        changed = score_content()
        changed["items"][2]["target_duration_ms"] = 5000
        status, saved = await core.call("PUT", base, json={"expected_revision": 1, **changed})
        assert status == 200 and saved["score"]["revision"] == 2 and saved["score"]["items"][2]["target_duration_ms"] == 5000

        status, body = await core.call("PUT", base, json={"expected_revision": 1, **changed})
        assert (status, body["error"]["code"]) == (409, "presentation_studio_stale_revision")
        status, body = await core.call("POST", base, json={"expected_variant_revision": one["revision"], **score_content()})
        assert (status, body["error"]["code"]) == (409, "presentation_studio_already_exists")


async def test_score_refusals_are_coded_envelopes_with_their_status(tmp_path):
    async with Core(tmp_path) as core:
        pid, variant = await scene_presentation(core)
        vid, revision = variant["variant_id"], variant["revision"]
        base = f"/{pid}/variants/{vid}/score"

        async def code(method, path, **kwargs):
            status, body = await core.call(method, path, **kwargs)
            assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}, body
            return status, body["error"]["code"]

        good = {"expected_variant_revision": revision, **score_content()}
        dangling = score_content()
        dangling["items"][0]["visual"] = [{"kind": "reveal", "scene_id": SID, "anchor_id": "nope"}]
        assert await code("POST", base, json={**good, **dangling}) == (400, "presentation_studio_score_incompatible")
        assert await code("POST", base, json={**good, "extra": 1}) == (400, "presentation_studio_invalid")
        assert await code("POST", base, json={**good, "position": 3}) == (400, "presentation_studio_runtime_state_refused")
        assert await code("POST", base, json={**good, "expected_variant_revision": 99}) == (409, "presentation_studio_stale_revision")
        tool = score_content()
        tool["items"][0]["visual"] = [{"kind": "reveal", "scene_id": SID, "anchor_id": "show_text", "tool": "delete_all"}]
        assert await code("POST", base, json={**good, **tool}) == (400, "presentation_studio_invalid")
        regex = score_content()
        regex["cues"][0]["predicate"]["phrases"] = [".*"]
        assert await code("POST", base, json={**good, **regex}) == (400, "presentation_studio_invalid")
        assert await code("GET", f"/{pid}/variants/psv_{'1' * 32}/score") == (404, "presentation_studio_unknown_variant")
        assert await code("GET", f"/pst_{'1' * 32}/variants/{vid}/score") == (404, "presentation_studio_unknown_presentation")
        assert await code("GET", base, params={"x": "1"}) == (400, "invalid_request")
        assert await code("POST", base, data=b"{not json") == (400, "invalid_request")
        assert await code("POST", base, data=b'{"expected_variant_revision": 1, "expected_variant_revision": 2}') == (
            400, "invalid_request")
        assert await code("PUT", base, json={"expected_revision": 1, **score_content()}) == (404, "presentation_studio_unknown_score")
        async with core.http.get(core.stack.core_url + PREFIX + base) as response:
            assert response.status == 401  # the bearer token is required here too
        async with core.http.post(core.stack.core_url + PREFIX + base, json=good) as response:
            assert response.status == 401
        status, body = await core.call("GET", base)
        assert str(tmp_path) not in body["error"]["message"]


async def test_the_typed_client_covers_the_score_routes(tmp_path):
    async with Core(tmp_path) as core:
        client = core.client
        pid, variant = await scene_presentation(core)
        vid = variant["variant_id"]
        with pytest.raises(CoreProtocolError) as none_yet:
            await client.presentation_studio_score(pid, vid)
        assert (none_yet.value.status, none_yet.value.code) == (404, "presentation_studio_unknown_score")
        created = await client.presentation_studio_create_score(
            pid, vid, {"expected_variant_revision": variant["revision"], **score_content()})
        assert created["score"]["revision"] == 1 and (await client.presentation_studio_score(pid, vid)) == created
        saved = await client.presentation_studio_save_score(pid, vid, {"expected_revision": 1, **score_content()})
        assert saved["score"]["revision"] == 2
        with pytest.raises(CoreProtocolError) as stale:
            await client.presentation_studio_save_score(pid, vid, {"expected_revision": 1, **score_content()})
        assert (stale.value.status, stale.value.code) == (409, "presentation_studio_stale_revision")
        with pytest.raises(CoreProtocolError) as bad:
            await client.presentation_studio_save_score(pid, vid, {"expected_revision": 2})
        assert bad.value.code == "presentation_studio_invalid"
        with pytest.raises(CoreProtocolError) as incompatible:
            await client.presentation_studio_save_score(pid, vid, {"expected_revision": 2, **score_content(
                items=[{"item_id": ITEM_1, "scene_id": "pss_0000000000ff", "presenter": "none", "kind": "silence"}],
                cues=[], start_item_id=ITEM_1)})
        assert incompatible.value.code == "presentation_studio_score_incompatible"


async def test_a_score_is_still_there_after_a_core_restart_and_the_listing_is_unchanged(tmp_path):
    async with Core(tmp_path) as core:
        pid, variant = await scene_presentation(core)
        vid = variant["variant_id"]
        _, created = await core.call("POST", f"/{pid}/variants/{vid}/score",
                                     json={"expected_variant_revision": variant["revision"], **score_content()})
    async with Core(tmp_path) as again:
        status, loaded = await again.call("GET", f"/{pid}/variants/{vid}/score")
        assert status == 200 and loaded == created
        status, listing = await again.call("GET", "")
        assert status == 200 and listing["problems"] == [] and len(listing["presentations"]) == 1


# ------------------------------------------------------------------ Slice 09 : direction artistique


def art_profile(**paths) -> dict:
    from tests.fakes import presentation_studio_art_direction as fx

    doc = fx.base_dict()
    for path, value in paths.items():
        doc = fx.set_path(doc, path.replace("__", "."), value)
    return doc


async def test_the_art_direction_lifecycle_over_http(tmp_path):
    async with Core(tmp_path) as core:
        pid, variant = await scene_presentation(core)
        vid = variant["variant_id"]
        base = f"/{pid}/variants/{vid}/art-direction"

        status, body = await core.call("GET", base)
        assert (status, body["error"]["code"]) == (404, "presentation_studio_unknown_art_direction")  # none yet, coded not empty

        status, created = await core.call("POST", base, json={"expected_variant_revision": variant["revision"], "profile": art_profile()})
        assert status == 201 and created["art_direction"]["revision"] == 1 and "relinked_from" not in created
        art = created["art_direction"]
        assert art["schema"] == "jarvis.presentation_studio.art_direction" and art["variant_id"] == vid
        assert (await core.call("GET", base)) == (200, created)
        status, one = await core.call("GET", f"/{pid}/variants/{vid}")
        assert one["art_direction_id"] == art["art_direction_id"] and one["revision"] == variant["revision"] + 1

        status, saved = await core.call("PUT", base, json={"expected_revision": 1, "profile": art_profile(shapes__radius_px=20)})
        assert status == 200 and saved["art_direction"]["revision"] == 2 and saved["art_direction"]["profile"]["shapes"]["radius_px"] == 20
        status, body = await core.call("PUT", base, json={"expected_revision": 1, "profile": art_profile()})
        assert (status, body["error"]["code"]) == (409, "presentation_studio_stale_revision")
        status, body = await core.call("POST", base, json={"expected_variant_revision": one["revision"], "profile": art_profile()})
        assert (status, body["error"]["code"]) == (409, "presentation_studio_already_exists")


async def test_art_direction_refusals_are_coded_envelopes_with_their_status(tmp_path):
    from tests.fakes import presentation_studio_art_direction as fx

    async with Core(tmp_path) as core:
        pid, variant = await scene_presentation(core)
        vid, revision = variant["variant_id"], variant["revision"]
        base = f"/{pid}/variants/{vid}/art-direction"

        async def code(method, path, **kwargs):
            status, body = await core.call(method, path, **kwargs)
            assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}, body
            return status, body["error"]["code"]

        good = {"expected_variant_revision": revision, "profile": art_profile()}
        for hostile in fx.HOSTILE[:6]:
            assert await code("POST", base, json={**good, "profile": art_profile(palette__accent=hostile)}) == (400, "presentation_studio_invalid")
        assert await code("POST", base, json={**good, "profile": art_profile(palette__text="#f7f9fc")}) == (400, "presentation_studio_invalid")
        assert await code("POST", base, json={**good, "extra": 1}) == (400, "presentation_studio_invalid")
        assert await code("POST", base, json={**good, "profile": {**art_profile(), "position": 3}}) == (400, "presentation_studio_runtime_state_refused")
        assert await code("POST", base, json={**good, "expected_variant_revision": 99}) == (409, "presentation_studio_stale_revision")
        assert await code("GET", f"/{pid}/variants/psv_{'1' * 32}/art-direction") == (404, "presentation_studio_unknown_variant")
        assert await code("GET", f"/pst_{'1' * 32}/variants/{vid}/art-direction") == (404, "presentation_studio_unknown_presentation")
        assert await code("GET", base, params={"x": "1"}) == (400, "invalid_request")
        assert await code("POST", base, data=b"{not json") == (400, "invalid_request")
        assert await code("POST", base, data=b'{"expected_variant_revision": 1, "expected_variant_revision": 2}') == (400, "invalid_request")
        assert await code("PUT", base, json={"expected_revision": 1, "profile": art_profile()}) == (404, "presentation_studio_unknown_art_direction")
        assert await code("POST", base + "/fallback", json={"expected_variant_revision": revision, "seed_context": {"spare": 1}}) == (400, "presentation_studio_invalid")
        assert await code("POST", base + "/candidates", json={"count": 99}) == (400, "presentation_studio_invalid")
        async with core.http.get(core.stack.core_url + PREFIX + base) as response:
            assert response.status == 401  # the bearer token is required here too
        async with core.http.post(core.stack.core_url + PREFIX + base + "/candidates", json={"count": 2}) as response:
            assert response.status == 401
        status, body = await core.call("GET", base)
        assert str(tmp_path) not in body["error"]["message"]


async def test_the_fallback_and_the_candidates_over_http(tmp_path):
    async with Core(tmp_path) as core:
        pid, variant = await scene_presentation(core)
        vid, revision = variant["variant_id"], variant["revision"]
        base = f"/{pid}/variants/{vid}/art-direction"

        status, listed = await core.call("POST", base + "/candidates", json={"count": 3, "seed_context": {"tone": ["luxe"]}})
        assert status == 200 and listed["base"] == "fallback" and len(listed["candidates"]) == 3
        assert (await core.call("GET", base))[0] == 404  # computing candidates stored nothing

        status, made = await core.call("POST", base + "/fallback", json={"expected_variant_revision": revision, "seed_context": {"tone": ["luxe"]}})
        assert status == 201 and made["art_direction"]["profile"]["provenance"]["fallback"] is True
        assert made["art_direction"]["profile"]["name"] == listed["base_profile"]["name"] == "Fallback - Luxury minimal"
        status, again = await core.call("POST", base + "/candidates", json={"count": 3})
        assert (status, again["base"], again["candidates"]) == (200, "stored", listed["candidates"])  # same base, same candidates
        status, body = await core.call("POST", base + "/fallback", json={"expected_variant_revision": revision + 1})
        assert (status, body["error"]["code"]) == (409, "presentation_studio_already_exists")


async def test_the_typed_client_covers_the_art_direction_routes(tmp_path):
    async with Core(tmp_path) as core:
        client = core.client
        pid, variant = await scene_presentation(core)
        vid = variant["variant_id"]
        with pytest.raises(CoreProtocolError) as none_yet:
            await client.presentation_studio_art_direction(pid, vid)
        assert (none_yet.value.status, none_yet.value.code) == (404, "presentation_studio_unknown_art_direction")
        candidates = await client.presentation_studio_art_direction_candidates(pid, vid, {"count": 2})
        assert candidates["base"] == "fallback" and len(candidates["candidates"]) == 2
        created = await client.presentation_studio_create_art_direction(
            pid, vid, {"expected_variant_revision": variant["revision"], "profile": candidates["candidates"][0]})
        assert created["art_direction"]["revision"] == 1 and (await client.presentation_studio_art_direction(pid, vid)) == created
        saved = await client.presentation_studio_save_art_direction(pid, vid, {"expected_revision": 1, "profile": candidates["candidates"][1]})
        assert saved["art_direction"]["revision"] == 2 and saved["art_direction"]["profile"]["name"].startswith("Direction 2")
        with pytest.raises(CoreProtocolError) as stale:
            await client.presentation_studio_save_art_direction(pid, vid, {"expected_revision": 1, "profile": candidates["candidates"][1]})
        assert (stale.value.status, stale.value.code) == (409, "presentation_studio_stale_revision")
        with pytest.raises(CoreProtocolError) as bad:
            await client.presentation_studio_save_art_direction(pid, vid, {"expected_revision": 2, "profile": {}})
        assert bad.value.code == "presentation_studio_invalid"
        pid2, variant2 = await scene_presentation(core)
        fallback = await client.presentation_studio_fallback_art_direction(
            pid2, variant2["variant_id"], {"expected_variant_revision": variant2["revision"]})
        assert fallback["art_direction"]["profile"]["provenance"]["fallback"] is True


async def test_an_art_direction_is_still_there_after_a_core_restart_and_the_listing_is_unchanged(tmp_path):
    async with Core(tmp_path) as core:
        pid, variant = await scene_presentation(core)
        vid = variant["variant_id"]
        _, created = await core.call("POST", f"/{pid}/variants/{vid}/art-direction",
                                     json={"expected_variant_revision": variant["revision"], "profile": art_profile()})
    async with Core(tmp_path) as again:
        status, loaded = await again.call("GET", f"/{pid}/variants/{vid}/art-direction")
        assert status == 200 and loaded == created
        status, listing = await again.call("GET", "")
        assert status == 200 and listing["problems"] == [] and len(listing["presentations"]) == 1


async def test_a_variant_put_cannot_attach_an_art_direction_over_http(tmp_path):
    async with Core(tmp_path) as core:
        pid, variant = await scene_presentation(core)
        vid = variant["variant_id"]
        status, body = await core.call("PUT", f"/{pid}/variants/{vid}", json=variant_body(variant, art_direction_id="psd_00000000dead"))
        assert (status, body["error"]["code"]) == (400, "presentation_studio_invalid")
        assert "art direction routes" in body["error"]["message"]
