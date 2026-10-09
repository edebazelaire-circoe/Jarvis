"""Routes Core, client type et relais Control Center des modeles de presentation (jarvis-interactive-presentation-studio, Slice 20).

Vrai Core (`JarvisCoreApplication`) derriere le vrai `LocalProtocolServer`, vrai Control Center devant lui, prefab de base
`jarvis.window` comme source du projet : statuts et codes de chaque route, plan qui n'ecrit rien, promotion puis instanciation de bout
en bout, acteur force a `user` par le relais, garde d'origine, journal sans contenu, parite route/documentation.
Contrat : `docs/presentation-studio.md` > *Template and prefab promotion contract*.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pytest

from jarvis.protocol import client as client_module
from jarvis.protocol.client import FORWARDABLE_PREFIXES, TEMPLATES_PREFIX, CoreProtocolError
from jarvis.protocol.presentation_studio_routes import PREFIX
from jarvis.protocol.presentation_studio_template_routes import PresentationStudioTemplateRoutes
from jarvis.runtime.presentation_studio_relay import STUDIO_ROUTE
from jarvis.runtime.presentation_studio_template_relay import PresentationStudioTemplateRelayRoutes, TEMPLATES_ROUTE
from tests.unit.test_presentation_studio_edit_routes import S1, S2, new_presentation
from tests.unit.test_presentation_studio_routes import Core

ROOT = Path(__file__).resolve().parents[2]
CORE_TEMPLATES = "/v1/presentation-studio/templates"
SELECTION = [{"scene_id": S1, "dimensions": ["density"], "parameters": ["body"]},
             {"scene_id": S2, "dimensions": ["density"], "parameters": ["body"]}]


def promotion(kind="presentation", **extra) -> dict:
    out = {"kind": kind, "slug": "fiche", "title": "Fiche modele", **extra}
    if "scenes" in out and out["scenes"] is None:  # `scenes=None` : no selection at all
        del out["scenes"]
    elif kind == "presentation":
        out.setdefault("scenes", SELECTION)
    elif kind == "scene":
        out.setdefault("scenes", SELECTION[:1])
    return out


def at(pid, vid, tail=""):
    return f"/{pid}/variants/{vid}/templates{tail}"


async def core_templates(core, method, tail="", **kw):
    async with core.http.request(method, core.stack.core_url + CORE_TEMPLATES + tail, headers={"Authorization": f"Bearer {core.client.token}"},
                                 **kw) as response:
        return response.status, await response.json(content_type=None)


def tree(core, pid) -> dict[str, str]:
    folder = next(core.stack.data_root.rglob(pid))
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


# ------------------------------------------------------------------ table et parite

def test_the_route_table_and_the_relay_surface():
    routes = [(r.method, r.path) for r in PresentationStudioTemplateRoutes(object()).routes()]
    variant = PREFIX + "/{presentation_id}/variants/{variant_id}/templates"
    assert routes == [("POST", variant + "/plan"), ("POST", variant), ("GET", CORE_TEMPLATES), ("GET", CORE_TEMPLATES + "/{template_id}"),
                      ("POST", CORE_TEMPLATES + "/{template_id}/instantiate")]
    relay = PresentationStudioTemplateRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    mapped = [(r.method, r.path.replace("/api/presentation-studio/presentations", PREFIX)
               .replace("/api/presentation-studio/templates", CORE_TEMPLATES)) for r in relay.routes()]
    assert sorted(mapped) == sorted(routes), "the page reaches exactly these routes, each write with a forced actor"
    assert set(vars(relay)) == {"_transport", "_journal"}  # no state in the Control Center
    assert TEMPLATES_PREFIX == CORE_TEMPLATES and CORE_TEMPLATES in FORWARDABLE_PREFIXES


def test_every_route_and_client_method_is_in_the_docs():
    page = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
    start = page.index("## Template and prefab promotion contract")
    section = page[start:page.index("\n## ", start + 10)]
    for route in PresentationStudioTemplateRoutes(object()).routes():
        tail = route.path.replace(PREFIX, "").replace(CORE_TEMPLATES, "")
        assert tail.replace("/{presentation_id}/variants/{variant_id}", "...") in section or tail in section, route.path
    for name in ("presentation_studio_template_plan", "presentation_studio_template_promote", "presentation_studio_templates",
                 "presentation_studio_template", "presentation_studio_template_instantiate"):
        assert name in section and hasattr(client_module.LocalCoreClient, name), name


# ------------------------------------------------------------------ Core

async def test_plan_promote_list_read_and_instantiate_over_http(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, _ = await new_presentation(core)
        before = tree(core, pid)
        status, plan = await core.call("POST", at(pid, vid, "/plan"), json=promotion())
        assert status == 200 and plan["ok"] is True and plan["would_publish"] == ["studio-template.fiche-1"]
        assert tree(core, pid) == before, "a plan writes nothing"
        status, empty = await core_templates(core, "GET")
        assert status == 200 and empty["count"] == 0

        status, done = await core.call("POST", at(pid, vid), json=promotion())
        assert status == 201 and done["kind"] == "presentation" and done["template_id"].startswith("ptp_")
        assert done["prefabs"] == [{"id": "studio-template.fiche-1", "version": 1, "published": True, "reused": False}]
        assert {p["control_id"] for p in done["parameters"]} == {"density", "body"}
        assert done["derived_from"]["presentation_id"] == pid and tree(core, pid) == before

        status, listing = await core_templates(core, "GET")
        assert status == 200 and [r["template_id"] for r in listing["templates"]] == [done["template_id"]]
        status, filtered = await core_templates(core, "GET", "?kind=scene")
        assert filtered["count"] == 0
        status, read = await core_templates(core, "GET", "/" + done["template_id"])
        assert status == 200 and read["template"]["kind"] == "presentation" and read["prefab_availability"][0]["available"] is True

        status, made = await core_templates(core, "POST", f"/{done['template_id']}/instantiate", json={"title": "Reprise"})
        assert status == 201 and len(made["scene_ids"]) == 2 and made["presentation_id"] != pid
        assert all(r["problems"] == [] for r in made["rendered"])
        status, graph = await core.call("GET", f"/{made['presentation_id']}")
        assert status == 200 and graph["presentation"]["title"] == "Reprise"


async def test_every_refusal_is_a_coded_envelope_with_its_status(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, _ = await new_presentation(core)

        async def code(method, path, **kw):
            status, payload = await core.call(method, path, **kw)
            assert set(payload) == {"error"}, payload
            return status, payload["error"]["code"]

        assert await code("POST", at(pid, vid), json=promotion(scenes=None)) == (400, "presentation_studio_template_selection_required")
        assert await code("POST", at(pid, vid), json={"kind": "presentation", "slug": "x"}) == (400, "presentation_studio_invalid")
        assert await code("POST", at(pid, vid), json=promotion(extra=1)) == (400, "presentation_studio_invalid")
        assert await code("POST", at(pid, vid), json=promotion(kind="deck")) == (400, "presentation_studio_invalid")
        assert await code("POST", at(pid, vid), json=promotion(slug="Bad Slug")) == (400, "presentation_studio_invalid")
        assert await code("POST", at(pid, vid), json=promotion("scene", scenes=[
            {"scene_id": "pss_ffffffffffff", "dimensions": [], "parameters": []}])) == (404, "presentation_studio_unknown_scene")
        assert await code("POST", at(pid, vid), json=promotion("scene", scenes=[
            {"scene_id": S1, "dimensions": ["body"], "parameters": []}])) == (400, "presentation_studio_invalid")
        assert await code("POST", at(pid, vid), json=promotion("art_direction", art_direction={"sections": ["palette"]})) \
            == (404, "presentation_studio_unknown_art_direction")
        assert await code("POST", at(pid, vid), json=promotion(expected_revision=99)) == (409, "presentation_studio_stale_revision")
        assert await code("POST", at("pst_" + "0" * 32, vid), json=promotion()) == (404, "presentation_studio_unknown_presentation")
        assert await code("POST", at(pid, "psv_" + "0" * 32), json=promotion()) == (404, "presentation_studio_unknown_variant")
        assert await code("POST", at(pid, vid), data=b"not json") == (400, "invalid_request")
        assert await code("POST", at(pid, vid) + "?x=1", json=promotion()) == (400, "invalid_request")
        assert await code("POST", at(pid, vid), data=b"x" * (128 * 1024 + 10)) == (400, "invalid_request")
        for status, tail in ((404, "/ptp_00000000dead"), (400, "/not-an-id")):
            got, payload = await core_templates(core, "GET", tail)
            assert got == status, tail
        got, payload = await core_templates(core, "POST", "/ptp_00000000dead/instantiate", json={})
        assert (got, payload["error"]["code"]) == (404, "presentation_studio_unknown_template")
        got, payload = await core_templates(core, "GET", "?kind=nope")
        assert (got, payload["error"]["code"]) == (400, "presentation_studio_invalid")
        got, payload = await core_templates(core, "GET", "?x=1")
        assert (got, payload["error"]["code"]) == (400, "invalid_request")
        async with core.http.get(core.stack.core_url + CORE_TEMPLATES) as response:
            assert response.status == 401  # the bearer token is required


async def test_the_typed_client_covers_every_route_and_raises_coded_errors(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, _ = await new_presentation(core)
        client = core.client
        plan = await client.presentation_studio_template_plan(pid, vid, promotion("scene"))
        assert plan["ok"] is True and plan["kind"] == "scene"
        done = await client.presentation_studio_template_promote(pid, vid, promotion("scene"))
        assert done["prefabs"][0]["id"] == "studio-template.fiche"
        assert (await client.presentation_studio_templates("scene"))["count"] == 1
        assert (await client.presentation_studio_template(done["template_id"]))["summary"]["scene_count"] == 1
        _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
        added = await client.presentation_studio_template_instantiate(
            done["template_id"], {"presentation_id": pid, "variant_id": vid, "expected_revision": variant["revision"]})
        assert added["kind"] == "scene" and added["scene_id"].startswith("pss_")
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_template("ptp_00000000dead")
        assert (caught.value.status, caught.value.code) == (404, "presentation_studio_unknown_template")
        with pytest.raises(CoreProtocolError) as caught:
            await client.presentation_studio_template_promote(pid, vid, promotion(scenes=None))
        assert caught.value.code == "presentation_studio_template_selection_required"


async def test_the_core_application_wires_the_service_to_the_shared_library_and_the_edit_api(tmp_path):
    async with Core(tmp_path) as core:
        app = core.stack.core
        service = app.presentation_studio_templates
        assert service._prefabs is app.prefabs and service._studio is app.presentation_studio
        assert service._edit is app.presentation_studio_edit


# ------------------------------------------------------------------ relais

async def test_the_relay_forces_the_actor_to_user_whatever_the_page_says(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, _ = await new_presentation(core)
        call = core.stack.call
        status, plan, _ = await call("POST", STUDIO_ROUTE + at(pid, vid, "/plan"), json=promotion("scene", actor="brain"))
        assert status == 200 and plan["ok"] is True
        status, done, _ = await call("POST", STUDIO_ROUTE + at(pid, vid), json=promotion("scene", actor="brain"))
        assert status == 201
        status, read, _ = await call("GET", TEMPLATES_ROUTE + "/" + done["template_id"])
        _, direct = await core_templates(core, "GET", "/" + done["template_id"])
        assert status == 200 and read == direct and read["template"]["created_by"] == "user"
        status, listing, _ = await call("GET", TEMPLATES_ROUTE + "?kind=scene")
        assert status == 200 and listing["count"] == 1
        status, made, _ = await call("POST", TEMPLATES_ROUTE + f"/{done['template_id']}/instantiate",
                                     json={"actor": "system", "title": "Via la page", "presentation_id": pid})
        assert status == 400 and made["error"]["code"] == "presentation_studio_invalid", "an incomplete scene instantiation is refused"
        _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
        status, made, _ = await call("POST", TEMPLATES_ROUTE + f"/{done['template_id']}/instantiate", json={
            "actor": "brain", "presentation_id": pid, "variant_id": vid, "expected_revision": variant["revision"]})
        assert status == 201 and made["kind"] == "scene"
        library = core.stack.data_root.rglob("studio-template.fiche/1/publication.json")
        assert json.loads(next(library).read_text(encoding="utf-8"))["provenance"]["created_by"] == {"actor": "user"}


@pytest.mark.parametrize("headers", [{"Origin": "null"}, {"Origin": "https://evil.example"},
                                     {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"}])
async def test_a_frame_or_a_foreign_origin_cannot_touch_the_templates(tmp_path, headers):
    async with Core(tmp_path) as core:
        pid, vid, _ = await new_presentation(core)
        call = core.stack.call
        status, payload, _ = await call("GET", TEMPLATES_ROUTE, headers=headers)
        assert status == 403 and payload["code"] == "forbidden_origin"
        for path in (STUDIO_ROUTE + at(pid, vid), STUDIO_ROUTE + at(pid, vid, "/plan"),
                     TEMPLATES_ROUTE + "/ptp_00000000dead/instantiate"):
            status, _, _ = await call("POST", path, headers=headers, json=promotion())
            assert status == 403, path
        _, listing = await core_templates(core, "GET")
        assert listing["count"] == 0
        assert not list(core.stack.data_root.rglob("studio-template.*"))


async def test_the_relay_rejects_malformed_bodies_and_exposes_no_other_method(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, _ = await new_presentation(core)
        call = core.stack.call
        for method, path in (("PUT", TEMPLATES_ROUTE), ("DELETE", TEMPLATES_ROUTE + "/ptp_00000000dead"),
                             ("GET", TEMPLATES_ROUTE + "/ptp_00000000dead/instantiate"), ("PUT", STUDIO_ROUTE + at(pid, vid))):
            status, _, _ = await call(method, path, json={})
            assert status in (404, 405), (method, path, status)
        for body in (b"[1]", b"not json", b""):
            status, payload, _ = await call("POST", STUDIO_ROUTE + at(pid, vid), data=body)
            assert (status, payload["error"]["code"]) == (400, "invalid_request"), body
        status, payload, _ = await call("POST", STUDIO_ROUTE + at(pid, vid) + "?x=1", json=promotion())
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        status, payload, _ = await call("POST", STUDIO_ROUTE + at(pid, vid), json=promotion(extra=1))
        assert (status, payload["error"]["code"]) == (400, "presentation_studio_invalid")


async def test_the_journal_never_holds_a_title_a_slug_or_a_label(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, _ = await new_presentation(core)
        status, done, _ = await core.stack.call("POST", STUDIO_ROUTE + at(pid, vid), json=promotion(
            "scene", title="Titre secret", slug="slug-secret", description="Description secrete",
            scenes=[{"scene_id": S1, "label": "Etiquette secrete", "dimensions": [], "parameters": ["body"]}]))
        assert status == 201
        rows = [e for e in core.stack.trace() if str(e.get("kind", "")).startswith("presentation_studio.request")]
        assert rows and rows[-1]["data"]["action"] == "studio_template_promote" and rows[-1]["data"]["status"] == 201
        # the template tree holds what the author typed (a title is the point of a template); no log row does
        assert "secret" not in json.dumps(core.stack.trace())
        assert re.search(r"secret", json.dumps(done)) is not None, "the answer to the author names what was promoted"
