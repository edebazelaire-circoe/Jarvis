"""Routes Core, client type et relais Control Center de l'avis et de l'essai de version (Remotion Slice 19).

Vrai Core (`JarvisCoreApplication`) derriere le vrai `LocalProtocolServer`, vrai Control Center devant lui. Le prefab epingle est un
prefab de la bibliotheque (copie de `jarvis.window`) dont on publie une deuxieme version. Contrat : `docs/presentation-studio.md` >
*Newer prefab versions and trial variants*.
"""

from __future__ import annotations

import hashlib

import pytest

from jarvis.protocol.client import CoreProtocolError
from jarvis.protocol.presentation_studio_routes import PREFIX
from jarvis.protocol.presentation_studio_upgrades_routes import PresentationStudioUpgradesRoutes
from jarvis.runtime.presentation_studio_relay import STUDIO_ROUTE
from jarvis.runtime.presentation_studio_upgrades_relay import PresentationStudioUpgradesRelayRoutes
from tests.unit.test_presentation_studio_edit_routes import CONTROLS, S1, S2, scene
from tests.unit.test_presentation_studio_routes import Core, variant_body

UPGRADES = "/{presentation_id}/variants/{variant_id}/upgrades"


def at(pid, vid, tail=""):
    return f"/{pid}/variants/{vid}/upgrades{tail}"


def tree(core, pid) -> dict[str, str]:
    folder = next(core.stack.data_root.rglob(pid))
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


async def lab_window(core, version_2: bool) -> None:
    """`lab.window` : une copie de la base `jarvis.window` (version 1), et une version 2 si demandee."""

    prefabs = core.stack.core.prefabs
    base = (await prefabs.get("jarvis.window")).to_dict(include_source=True)
    for number in (1, 2) if version_2 else (1,):
        files = dict(base["files"])
        files["style"] += f"\n/* v{number} */"
        await prefabs.save({"manifest": {**base["manifest"], "id": "lab.window"}, **files}, actor="user")


async def presentation(core) -> tuple[str, str]:
    _, created = await core.call("POST", "", json={"title": "Atelier"})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    body = variant_body(variant, scenes=[{**scene(S1, controls=CONTROLS), "prefab": {"id": "lab.window", "version": 1}},
                                         {**scene(S2, controls=CONTROLS), "prefab": {"id": "lab.window", "version": 1}}])
    status, saved = await core.call("PUT", f"/{pid}/variants/{variant['variant_id']}", json=body)
    assert status == 200, saved
    return pid, variant["variant_id"]


def test_the_route_table_and_the_relay_surface():
    routes = [(r.method, r.path) for r in PresentationStudioUpgradesRoutes(object()).routes()]
    assert routes == [("GET", PREFIX + UPGRADES), ("POST", PREFIX + UPGRADES + "/try")]
    relay = PresentationStudioUpgradesRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    mapped = sorted((r.method, r.path.replace("/api/presentation-studio/presentations", PREFIX)) for r in relay.routes())
    assert mapped == sorted(routes) and set(vars(relay)) == {"_transport", "_journal"}, "no state in the Control Center"


async def test_the_notice_is_read_only_and_the_trial_creates_a_child_variant_over_http(tmp_path):
    async with Core(tmp_path) as core:
        await lab_window(core, version_2=True)
        pid, vid = await presentation(core)
        before = tree(core, pid)
        status, notices = await core.call("GET", at(pid, vid))
        assert status == 200 and notices["count"] == 2 and notices["auto_upgrade"] is False
        assert notices["notices"][0]["latest_version"] == 2 and notices["notices"][0]["fits"] is True
        assert tree(core, pid) == before, "a notice writes nothing"

        status, trial = await core.call("POST", at(pid, vid, "/try"), json={"scene_id": S1, "title": "Essai"})
        assert status == 201 and trial["trial"] is True and trial["adopted"] is False and trial["to"] == {"id": "lab.window", "version": 2}
        after = tree(core, pid)
        assert {k: v for k, v in after.items() if k.startswith(f"variants/{vid}")} == {
            k: v for k, v in before.items() if k.startswith(f"variants/{vid}")}, "the original variant file is byte-identical"
        status, graph = await core.call("GET", f"/{pid}")
        assert status == 200 and graph["presentation"]["active_variant_id"] == vid
        status, notices = await core.call("GET", at(pid, vid))
        assert notices["trials"][0]["variant_id"] == trial["node"]["variant_id"]


async def test_every_refusal_is_a_coded_envelope(tmp_path):
    async with Core(tmp_path) as core:
        await lab_window(core, version_2=False)
        pid, vid = await presentation(core)

        async def code(method, path, **kw):
            status, payload = await core.call(method, path, **kw)
            assert set(payload) == {"error"}, payload
            return status, payload["error"]["code"]

        assert await code("POST", at(pid, vid, "/try"), json={"scene_id": S1}) == (400, "presentation_studio_invalid")  # nothing newer
        assert await code("POST", at(pid, vid, "/try"), json={"scene_id": "pss_ffffffffffff"}) == (404, "presentation_studio_unknown_scene")
        assert await code("POST", at(pid, vid, "/try"), json={"scene_id": S1, "activate": True}) == (400, "presentation_studio_invalid")
        assert await code("POST", at(pid, vid, "/try"), json={}) == (400, "presentation_studio_invalid")
        assert await code("POST", at(pid, vid, "/try"), data=b"not json") == (400, "invalid_request")
        assert await code("POST", at(pid, vid, "/try") + "?x=1", json={"scene_id": S1}) == (400, "invalid_request")
        assert (await code("GET", at("pst_" + "0" * 32, vid)))[0] == 404  # the variant is looked up in its presentation
        assert await code("GET", at(pid, "psv_" + "0" * 32)) == (404, "presentation_studio_unknown_variant")
        async with core.http.get(core.stack.core_url + PREFIX + at(pid, vid)) as response:
            assert response.status == 401  # the bearer token is required


async def test_the_typed_client_and_the_relay_force_the_actor_to_user(tmp_path):
    async with Core(tmp_path) as core:
        await lab_window(core, version_2=True)
        pid, vid = await presentation(core)
        assert (await core.client.presentation_studio_upgrades(pid, vid))["count"] == 2
        call = core.stack.call
        status, via, _ = await call("GET", STUDIO_ROUTE + at(pid, vid))
        _, direct = await core.call("GET", at(pid, vid))
        assert status == 200 and via == direct
        status, trial, _ = await call("POST", STUDIO_ROUTE + at(pid, vid, "/try"), json={"scene_id": S1, "actor": "brain"})
        assert status == 201 and trial["node"]["created_by"] == "user", "the page of the user never speaks as the brain"
        with pytest.raises(CoreProtocolError) as caught:
            await core.client.presentation_studio_upgrade_try(pid, vid, {"scene_id": "pss_ffffffffffff"})
        assert caught.value.code == "presentation_studio_unknown_scene"
        status, payload, _ = await call("POST", STUDIO_ROUTE + at(pid, vid, "/try"), data=b"[1]")
        assert (status, payload["error"]["code"]) == (400, "invalid_request")
        for method, path in (("PUT", STUDIO_ROUTE + at(pid, vid)), ("DELETE", STUDIO_ROUTE + at(pid, vid, "/try"))):
            status, _, _ = await call(method, path, json={})
            assert status in (404, 405)


@pytest.mark.parametrize("headers", [{"Origin": "null"}, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}])
async def test_a_frame_or_a_foreign_origin_cannot_try_a_version(tmp_path, headers):
    async with Core(tmp_path) as core:
        await lab_window(core, version_2=True)
        pid, vid = await presentation(core)
        before = tree(core, pid)
        status, payload, _ = await core.stack.call("GET", STUDIO_ROUTE + at(pid, vid), headers=headers)
        assert status == 403 and payload["code"] == "forbidden_origin"
        status, _, _ = await core.stack.call("POST", STUDIO_ROUTE + at(pid, vid, "/try"), headers=headers, json={"scene_id": S1})
        assert status == 403 and tree(core, pid) == before


async def test_the_core_application_wires_the_service(tmp_path):
    async with Core(tmp_path) as core:
        app = core.stack.core
        service = app.presentation_studio_upgrades
        assert service._prefabs is app.prefabs and service._studio is app.presentation_studio
        assert service._variants is app.presentation_studio_variants and service._edit is app.presentation_studio_edit


async def test_a_licence_change_is_in_the_notice_and_the_trial_needs_the_named_acknowledgement_over_http_and_through_the_relay(tmp_path):
    async with Core(tmp_path) as core:
        prefabs = core.stack.core.prefabs
        base = (await prefabs.get("jarvis.window")).to_dict(include_source=True)
        await prefabs.save({"manifest": {**base["manifest"], "id": "lab.window"}, **base["files"]}, actor="user")
        catalog = {"type": "component", "compatibility": {"slidecar": "native"}, "stack": ["html"], "license": "CC-BY-NC-4.0"}
        files = dict(base["files"])
        files["style"] += "\n/* v2 */"
        await prefabs.save({"manifest": {**base["manifest"], "id": "lab.window", "schema_version": 3, "catalog": catalog}, **files}, actor="user")
        pid, vid = await presentation(core)
        status, notices = await core.call("GET", at(pid, vid))
        row = notices["notices"][0]
        assert status == 200 and row["licence_changed"] is True and row["latest_licence"] == "CC-BY-NC-4.0" and row["licence_ack_required"] == "CC-BY-NC-4.0"
        before = tree(core, pid)
        status, refused = await core.call("POST", at(pid, vid, "/try"), json={"scene_id": S1})
        assert (status, refused["error"]["code"]) == (400, "presentation_studio_invalid") and "licence_ack" in refused["error"]["message"]
        assert tree(core, pid) == before
        status, brain = await core.call("POST", at(pid, vid, "/try"), json={"scene_id": S1, "actor": "brain", "licence_ack": ["CC-BY-NC-4.0"]})
        assert (status, brain["error"]["code"]) == (400, "presentation_studio_invalid") and tree(core, pid) == before
        status, done, _ = await core.stack.call("POST", STUDIO_ROUTE + at(pid, vid, "/try"),
                                                json={"scene_id": S1, "actor": "brain", "licence_ack": ["CC-BY-NC-4.0"]})
        assert status == 201 and done["trial"] is True and done["node"]["created_by"] == "user", "the page is the user: it may acknowledge"
