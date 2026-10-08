"""Routes Core, client typé et relais Control Center des variantes locales d'une scène (jarvis-interactive-presentation-studio, Slice 17).

Vrai Core (`JarvisCoreApplication`) derrière le vrai `LocalProtocolServer`, vrai Control Center devant lui, prefab de base
`jarvis.window` : statuts et codes de chaque route, écritures par `.../edits` (la porte unique) avec l'acteur forcé à `user` par le
relais, aperçu qui n'écrit rien (hachage de l'arbre), promotion, garde d'origine, journal et évènement sans contenu, parité
route/documentation.
Contrat : `docs/presentation-studio.md` › *Scene-local variant contract*.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pytest

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.protocol.client import CoreProtocolError
from jarvis.protocol.presentation_studio_routes import PREFIX
from jarvis.protocol.presentation_studio_scene_variants_routes import PresentationStudioSceneVariantsRoutes
from jarvis.runtime.presentation_studio_relay import STUDIO_ROUTE
from jarvis.runtime.presentation_studio_scene_variants_relay import PresentationStudioSceneVariantsRelayRoutes
from tests.unit.test_presentation_studio_edit_routes import S1, S2, body as edit_body, new_presentation, op_set
from tests.unit.test_presentation_studio_routes import Core

RELAY = STUDIO_ROUTE
ROOT = Path(__file__).resolve().parents[2]


def sv(pid, vid, scene_id=S1, tail=""):
    return f"/{pid}/variants/{vid}/scenes/{scene_id}/scene-variants{tail}"


def tree(core, pid) -> dict[str, str]:
    folder = next(core.stack.data_root.rglob(pid)) if hasattr(core.stack, "data_root") else None
    return {} if folder is None else {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in sorted(folder.rglob("*")) if p.is_file()}


async def edit(core, pid, vid, *ops, actor="brain", mode="commit"):
    _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
    status, result = await core.call("POST", f"/{pid}/variants/{vid}/edits", json=edit_body(variant["revision"], *ops, actor=actor, mode=mode))
    return status, result


async def seeded(core):
    """Une présentation de deux scènes ; la scène 1 a une variante locale « B » dont le texte diffère."""

    pid, vid, _ = await new_presentation(core)
    status, made = await edit(core, pid, vid, {"op": "scene_variant.create", "scene_id": S1, "label": "B"})
    assert status == 200, made
    b = made["ops"][0]["scene_variant_id"]
    await edit(core, pid, vid, {"op": "scene_variant.select", "scene_id": S1, "variant_id": b})
    await edit(core, pid, vid, op_set(S1, "body", "Dans B"))
    _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
    original = next(i["variant_id"] for i in variant["scenes"][0]["scene_variants"]["items"] if i["variant_id"] != b)
    await edit(core, pid, vid, {"op": "scene_variant.select", "scene_id": S1, "variant_id": original})
    return pid, vid, b, original


# ------------------------------------------------------------------ table et parité

def test_the_route_table_of_the_scene_variants_and_its_relay_surface():
    routes = [(r.method, r.path) for r in PresentationStudioSceneVariantsRoutes(object()).routes()]
    scene = PREFIX + "/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/scene-variants"
    assert routes == [("GET", scene), ("POST", scene + "/{scene_variant_id}/preview"), ("POST", scene + "/{scene_variant_id}/promote"),
                      ("POST", PREFIX + "/{presentation_id}/scene-variants/preview/cancel")]
    relay = PresentationStudioSceneVariantsRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    mapped = [(r.method, "/v1/presentation-studio" + r.path[len("/api/presentation-studio"):]) for r in relay.routes()]
    assert sorted(mapped) == sorted(routes), "the page reaches exactly these routes, each write with a forced actor"
    assert set(vars(relay)) == {"_transport", "_journal"}  # no state in the Control Center


def test_every_route_is_in_the_docs_and_the_docs_name_no_other_scene_variant_route():
    page = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
    section = page[page.index("## Scene-local variant contract"):page.index("## Playback roles and speech authority")]
    documented = {re.sub(r"\{presentation_id\}", "{presentation_id}", m) for m in re.findall(r"`[^`]*scene-variants[^`]*`", section)
                  if m.startswith("`/v1") or m.startswith("`.../")}
    for needle in ("/scene-variants`", "/{scene_variant_id}/preview", "/{scene_variant_id}/promote", "/scene-variants/preview/cancel"):
        assert any(needle in item for item in documented), needle
    for route in PresentationStudioSceneVariantsRoutes(object()).routes():
        tail = route.path.split("scene-variants", 1)[1]
        assert tail == "" or tail in section, route.path
    for name in ("presentation_studio_scene_variants", "presentation_studio_scene_variant_preview",
                 "presentation_studio_scene_variant_cancel_preview", "presentation_studio_scene_variant_promote"):
        assert name in section, name


# ------------------------------------------------------------------ Core

async def test_list_preview_cancel_and_promote_over_http_with_status_and_codes(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, b, original = await seeded(core)
        status, listing = await core.call("GET", sv(pid, vid))
        assert status == 200 and listing["count"] == 2 and listing["selected"] == original
        assert [row["label"] for row in listing["variants"]] == ["Original", "B"] and "Dans B" not in json.dumps(listing)
        before = tree(core, pid)
        status, shown = await core.call("POST", sv(pid, vid, tail=f"/{b}/preview"), json={})
        assert status == 200 and shown["written"] is False and shown["staged"] is False
        assert shown["preview"]["payload"]["prefab"]["data"]["body"] == "Dans B" and tree(core, pid) == before
        status, nothing = await core.call("POST", f"/{pid}/scene-variants/preview/cancel")
        assert status == 200 and nothing["cancelled"] is False
        status, promoted = await core.call("POST", sv(pid, vid, tail=f"/{b}/promote"), json={"title": "Version B", "rationale": "plus direct"})
        assert status == 201 and promoted["node"]["variant_number"] == 2 and promoted["scene_variant_id"] == b
        assert promoted["node"]["sources"] == [vid] and b in promoted["node"]["rationale"]
        status, graph = await core.call("GET", f"/{pid}/graph")
        assert [n["variant_number"] for n in graph["nodes"]] == [1, 2]


async def test_every_refusal_is_a_coded_envelope_with_its_status(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, b, original = await seeded(core)

        async def code(method, path, **kw):
            status, payload = await core.call(method, path, **kw)
            assert set(payload) == {"error"}, payload
            return status, payload["error"]["code"]

        ghost = "psx_ffffffffffff"
        assert await code("POST", sv(pid, vid, tail=f"/{ghost}/preview"), json={}) == (404, "presentation_studio_unknown_scene_variant")
        assert await code("POST", sv(pid, vid, S2, f"/{b}/preview"), json={}) == (404, "presentation_studio_unknown_scene_variant")
        assert await code("POST", sv(pid, vid, "pss_ffffffffffff", f"/{b}/preview"), json={}) == (404, "presentation_studio_unknown_scene")
        assert await code("POST", sv(pid, vid, tail=f"/{b}/preview"), json={"stage": "yes"}) == (400, "presentation_studio_invalid")
        assert await code("POST", sv(pid, vid, tail=f"/{b}/preview"), json={"timeout_s": 500}) == (400, "presentation_studio_invalid")
        assert await code("POST", sv(pid, vid, tail=f"/{b}/preview"), data=b"not json") == (400, "invalid_request")
        assert await code("POST", sv(pid, vid, tail=f"/{b}/preview?x=1"), json={}) == (400, "invalid_request")
        assert await code("POST", sv(pid, vid, tail=f"/{b}/promote"), json={}) == (400, "presentation_studio_invalid")
        assert await code("POST", sv(pid, vid, tail=f"/{b}/promote"), json={"title": "x", "extra": 1}) == (400, "presentation_studio_invalid")
        assert await code("POST", sv(pid, vid, tail=f"/{ghost}/promote"), json={"title": "x"}) == (404, "presentation_studio_unknown_scene_variant")
        assert await code("POST", sv(pid, vid, tail=f"/{b}/promote"), data=b"x" * (16 * 1024 + 10)) == (400, "invalid_request")
        assert await code("GET", sv(pid, vid, "pss_ffffffffffff")) == (404, "presentation_studio_unknown_scene")
        assert await code("GET", sv(pid, "psv_" + "0" * 32)) == (404, "presentation_studio_unknown_variant")
        assert await code("GET", sv(pid, vid) + "?x=1") == (400, "invalid_request")
        assert await code("POST", "/nope/scene-variants/preview/cancel") == (404, "presentation_studio_unknown_presentation")
        async with core.http.get(core.stack.core_url + PREFIX + sv(pid, vid)) as response:
            assert response.status == 401  # the bearer token is required


async def test_the_edit_door_carries_the_five_operations_with_their_codes_over_http(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, b, original = await seeded(core)
        status, refusal = await edit(core, pid, vid, {"op": "scene_variant.delete", "scene_id": S1, "variant_id": original})
        assert status == 409 and refusal["code"] == "presentation_studio_scene_variant_protected" and refusal["error"]["code"] == refusal["code"]
        status, refusal = await edit(core, pid, vid, {"op": "scene_variant.select", "scene_id": S1, "variant_id": "psx_ffffffffffff"})
        assert status == 404 and refusal["code"] == "presentation_studio_unknown_scene_variant"
        status, done = await edit(core, pid, vid, {"op": "scene_variant.rename", "scene_id": S1, "variant_id": b, "label": "B2"})
        assert status == 200 and done["tier"] == "structure" and done["undo"]["available"] is True
        status, done = await edit(core, pid, vid, {"op": "scene_variant.delete", "scene_id": S1, "variant_id": b})
        assert status == 200 and done["changed"] is True
        status, bad = await edit(core, pid, vid, {"op": "scene_variant.select", "scene_id": S1, "variant_id": "nope"})
        assert status == 400 and bad["error"]["code"] == "presentation_studio_invalid"


async def test_the_typed_client_covers_every_route_and_raises_coded_errors(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, b, original = await seeded(core)
        client = core.client
        listing = await client.presentation_studio_scene_variants(pid, vid, S1)
        assert listing["count"] == 2
        shown = await client.presentation_studio_scene_variant_preview(pid, vid, S1, b)
        assert shown["written"] is False and shown["scene_variant_id"] == b
        assert (await client.presentation_studio_scene_variant_cancel_preview(pid))["cancelled"] is False
        promoted = await client.presentation_studio_scene_variant_promote(pid, vid, S1, b, {"title": "Promue", "activate": True})
        assert promoted["activated"] is True
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_scene_variant_preview(pid, vid, S1, "psx_ffffffffffff")
        assert (caught.value.status, caught.value.code) == (404, "presentation_studio_unknown_scene_variant")
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_scene_variant_promote(pid, vid, S1, b, {})
        assert caught.value.status == 400


async def test_the_core_application_wires_the_service_to_the_edit_the_graph_and_the_playback(tmp_path):
    async with Core(tmp_path) as core:
        app = core.stack.core
        service = app.presentation_studio_scene_variants
        assert service._edit is app.presentation_studio_edit and service._variants is app.presentation_studio_variants
        assert service._playback is app.presentation_studio_playback


# ------------------------------------------------------------------ relais

async def test_the_relay_forces_the_actor_to_user_whatever_the_page_says(tmp_path):
    async with Core(tmp_path) as core:
        seen = []
        core.stack.core.conversation_event_emitter.add_listener(seen.append)
        pid, vid, b, original = await seeded(core)
        call = core.stack.call
        status, listing, _ = await call("GET", RELAY + sv(pid, vid))
        _, direct = await core.call("GET", sv(pid, vid))
        assert status == 200 and listing == direct
        for claimed in ("brain", "system", None):
            payload = {"actor": claimed} if claimed else {}
            status, _, _ = await call("POST", RELAY + sv(pid, vid, tail=f"/{b}/preview"), json=payload)
            assert status == 200, claimed
        status, promoted, _ = await call("POST", RELAY + sv(pid, vid, tail=f"/{b}/promote"), json={"title": "Page", "actor": "brain"})
        assert status == 201 and promoted["node"]["created_by"] == "user"
        # the writes of a set go through the edit relay, which forces the actor too
        status, made, _ = await call("POST", RELAY + f"/{pid}/variants/{vid}/edits", json=edit_body(
            (await core.call("GET", f"/{pid}/variants/{vid}"))[1]["revision"],
            {"op": "scene_variant.rename", "scene_id": S1, "variant_id": b, "label": "Renomme"}, actor="brain"))
        assert status == 200 and made["actor"] == "user"
        sources = {dict(e.attributes)["source"] for e in seen
                   if e.event_type in (T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED, T.SYSTEM_PRESENTATION_STUDIO_VARIANT_CHANGED)}
        assert sources == {"brain", "user"}  # the seeding was direct (brain); the page's own are user
        page_sources = [dict(e.attributes)["source"] for e in seen if list(dict(e.attributes).get("op", ())) == ["scene_variant.rename"]]
        assert page_sources == ["user"]


@pytest.mark.parametrize("headers", [{"Origin": "null"}, {"Origin": "https://evil.example"},
                                     {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"}])
async def test_a_frame_or_a_foreign_origin_cannot_touch_the_scene_variants(tmp_path, headers):
    async with Core(tmp_path) as core:
        pid, vid, b, original = await seeded(core)
        status, payload, _ = await core.stack.call("GET", RELAY + sv(pid, vid), headers=headers)
        assert status == 403 and payload["code"] == "forbidden_origin"
        for tail in (f"/{b}/preview", f"/{b}/promote"):
            status, _, _ = await core.stack.call("POST", RELAY + sv(pid, vid, tail=tail), headers=headers, json={"title": "x"})
            assert status == 403, tail
        status, _, _ = await core.stack.call("POST", RELAY + f"/{pid}/scene-variants/preview/cancel", headers=headers, json={})
        assert status == 403
        _, graph = await core.call("GET", f"/{pid}/graph")
        assert len(graph["nodes"]) == 1


async def test_the_relay_rejects_malformed_bodies_and_exposes_no_other_method(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, b, original = await seeded(core)
        call = core.stack.call
        for method, path in (("PUT", sv(pid, vid)), ("DELETE", sv(pid, vid, tail=f"/{b}/preview")), ("GET", sv(pid, vid, tail=f"/{b}/promote"))):
            status, _, _ = await call(method, RELAY + path, json={})
            assert status in (404, 405), (method, path, status)
        status, payload, _ = await call("POST", RELAY + sv(pid, vid, tail=f"/{b}/promote"), data=b"[1]")
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await call("POST", RELAY + sv(pid, vid, tail=f"/{b}/promote?x=1"), json={"title": "x"})
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await call("POST", RELAY + sv(pid, vid, tail=f"/{b}/promote"), json={"title": "x", "number": 3})
        assert (status, payload["error"]["code"]) == (400, "presentation_studio_invalid")


async def test_the_journal_and_the_events_never_hold_a_label_a_rationale_or_a_title(tmp_path):
    async with Core(tmp_path) as core:
        seen = []
        core.stack.core.conversation_event_emitter.add_listener(seen.append)
        pid, vid, b, original = await seeded(core)
        await edit(core, pid, vid, {"op": "scene_variant.create", "scene_id": S1, "label": "Libelle secret", "rationale": "Raison secrete"})
        status, _, _ = await core.stack.call("POST", RELAY + sv(pid, vid, tail=f"/{b}/promote"),
                                             json={"title": "Titre secret", "rationale": "Autre raison secrete"})
        assert status == 201
        rows = [e for e in core.stack.trace() if str(e.get("kind", "")).startswith("presentation_studio.request")]
        assert rows and rows[-1]["data"]["action"] == "studio_scene_variant_promote" and rows[-1]["data"]["status"] == 201
        assert "secret" not in json.dumps(core.stack.trace()) and "secret" not in repr(seen)
        assert all(e.content is None for e in seen if e.event_type is T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED)
        await core.stack.core.conversation_event_emitter.stop()
