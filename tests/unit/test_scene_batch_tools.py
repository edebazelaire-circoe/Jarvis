"""Actions de lot et étiquettes de la scène (handoff jarvis-constellation-scene-runtime, Slice 13).

`scene_update_many` applique **un même** changement à un ensemble d'objets
désigné par les filtres de `scene_query` ou par une liste d'identifiants. Chaîne
réelle : `SceneDisplayTools` → `CoreSceneTransport` → `LocalProtocolServer` →
`JarvisCoreApplication.scene`. Ce qui doit tenir :

- un lot remplace N appels unitaires et rend des comptes vrais ;
- un objet épinglé par l'utilisateur n'est **jamais** touché, et le dit ;
- les refus sont rendus avec leur motif, jamais avalés ;
- une sélection trop large, ou un masquage qui viderait l'écran, est refusé
  **avant** tout envoi ;
- le sélecteur est celui de `scene_query` (dont `connected`, la constellation) :
  ce que la lecture liste est ce que le lot touche ;
- une étiquette (`annotation`) appartient à l'objet annoté : elle le suit, elle
  disparaît avec lui, et elle reste une donnée d'affichage.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain.scene import MAX_ANNOTATION_CHARS, ScenePayload
from jarvis.runtime.display_mcp import (
    MAX_BATCH_TARGETS,
    DisplayToolError,
    build_server,
)
from jarvis.runtime.journal import read_jsonl_tail
from tests.integration.test_scene_transport import CoreProcess
from tests.unit.test_display_mcp import (  # noqa: F401 - fixtures
    SpyTransport,
    core,
    observe,
    scene_object,
    tools,
    user_command,
    wait_for,
)


# ------------------------------------------------------------------ scène de départ


async def notes(tools, count: int, *, category: str = "note") -> list[str]:
    """`count` fenêtres du cerveau, placées côte à côte ; rend leurs identifiants."""

    created = []
    for index in range(count):
        made = await tools.create_object(kind="window", category=category, title=f"Note {index}",
                                         geometry={"x": -100 + index * 12, "y": -40, "w": 10, "h": 8})
        created.append(made["object_id"])
    return created


async def snapshot_objects(core: CoreProcess) -> dict[str, dict]:
    status, body, _ = await core.request("GET", "/v1/scene/snapshot")
    assert status == 200
    return {item["object_id"]: item for item in body["snapshot"]["objects"]}


# ------------------------------------------------------------------ le lot remplace N appels


async def test_one_call_hides_every_object_a_filter_designates(core, tools):
    made = await notes(tools, 4)
    other = await tools.create_object(kind="group", category="plan", title="Plan")
    await tools.inspect()

    result = await tools.update_many(select={"kind": "window", "category": "note"}, visibility="hidden", confirm=True)

    assert result["matched"] == 4 and result["targets"] == 4
    assert result["applied"] == 4 and result["refused"] == 0 and result["duplicate"] == 0
    assert sorted(result["applied_ids"]) == sorted(made)
    assert result["atomicity"] == "best_effort" and result["changes"] == {"visibility": "hidden"}
    stored = await snapshot_objects(core)
    assert all(stored[object_id]["visibility"] == "hidden" for object_id in made)
    assert stored[other["object_id"]]["visibility"] == "visible"


async def test_one_call_folds_a_whole_set_into_points_and_moves_its_layer(core, tools):
    made = await notes(tools, 3)
    for object_id in made:
        await tools.update_object(object_id=object_id, representation="window")
    await tools.inspect()

    result = await tools.update_many(object_ids=made, representation="point", layer=140, order=7)

    assert result["applied"] == 3 and result["refused"] == 0
    stored = await snapshot_objects(core)
    for object_id in made:
        assert stored[object_id]["representation"] == "point"
        assert stored[object_id]["layer"] == 140 and stored[object_id]["order"] == 7


async def test_a_second_identical_batch_changes_nothing_and_says_so(core, tools):
    made = await notes(tools, 3)
    await tools.inspect()
    await tools.update_many(object_ids=made, category="archive")

    again = await tools.update_many(object_ids=made, category="archive")

    assert again["applied"] == 0 and again["duplicate"] == 3 and again["refused"] == 0


# ------------------------------------------------------------------ l'épingle de l'utilisateur


async def test_a_batch_never_touches_an_object_the_user_pinned_and_reports_the_refusal(core, tools):
    made = await notes(tools, 3)
    pinned = made[0]
    await user_command(core, {"op": "pin", "object_id": pinned})
    await tools.inspect()

    result = await tools.update_many(select={"kind": "window"}, representation="capsule", layer=200)

    assert result["pinned_skipped"] == 1 and "épinglés" in result["pinned_note"]
    assert result["applied"] == 2 and result["targets"] == 2 and result["matched"] == 3
    assert {"id": pinned, "reason": "pinned_by_user"} in result["refused_ids"]
    stored = await snapshot_objects(core)
    # Rien n'a été envoyé pour lui : ni forme, ni couche.
    assert stored[pinned]["representation"] == "point" and stored[pinned]["layer"] == 220
    assert stored[pinned]["constraints"]["pinned_by_user"] is True
    assert all(stored[object_id]["representation"] == "capsule" for object_id in made[1:])


async def test_an_explicit_list_of_ids_cannot_bypass_the_pin(core, tools):
    made = await notes(tools, 2)
    await user_command(core, {"op": "pin", "object_id": made[0]})
    await tools.inspect()

    result = await tools.update_many(object_ids=made, visibility="hidden")

    assert result["pinned_skipped"] == 1 and result["applied"] == 1
    stored = await snapshot_objects(core)
    assert stored[made[0]]["visibility"] == "visible" and stored[made[1]]["visibility"] == "hidden"


# ------------------------------------------------------------------ refus rendus, jamais avalés


async def test_unknown_and_archived_ids_come_back_with_their_reason_and_the_rest_is_applied(core, tools):
    made = await notes(tools, 2)
    await user_command(core, {"op": "archive", "object_id": made[1]})
    await tools.inspect()

    result = await tools.update_many(object_ids=[made[0], made[1], "brain-window-absent"], annotation="revue")

    assert result["applied"] == 1 and result["refused"] == 2
    reasons = {entry["id"]: entry["reason"] for entry in result["refused_ids"]}
    assert reasons == {made[1]: "object_archived", "brain-window-absent": "unknown_object"}
    stored = await snapshot_objects(core)
    assert stored[made[0]]["payload"]["annotation"] == "revue"


async def test_an_empty_selection_is_a_true_report_not_an_error(core, tools):
    await notes(tools, 2)
    await tools.inspect()

    result = await tools.update_many(select={"kind": "artifact"}, visibility="hidden")

    assert result["matched"] == 0 and result["applied"] == 0 and result["refused"] == 0


async def test_the_journal_keeps_the_counts_of_a_batch_without_any_content(core, tools, tmp_path):
    made = await notes(tools, 2)
    await tools.inspect()
    await tools.update_many(object_ids=made, annotation="secret d'utilisateur")

    entries = [entry for entry in read_jsonl_tail(tmp_path / "runtime" / "trace.jsonl", limit=200)
               if entry.get("data", {}).get("tool") == "scene_update_many"]
    assert entries and entries[-1]["data"]["applied"] == 2 and entries[-1]["data"]["changes"] == ["annotation"]
    assert "secret" not in json.dumps(entries, ensure_ascii=False)


# ------------------------------------------------------------------ bornes, avant tout envoi


async def test_a_selection_beyond_the_bound_is_refused_without_sending_anything(core, tools):
    await notes(tools, MAX_BATCH_TARGETS + 1)
    await tools.inspect()
    before = json.loads(await tools.inspect())["scene"]["revision"]

    with pytest.raises(DisplayToolError) as failure:
        await tools.update_many(select={"kind": "window"}, layer=130)

    assert failure.value.code == "selection_too_large"
    assert f"{MAX_BATCH_TARGETS + 1} objets" in str(failure.value) and "rien n'a été envoyé" in str(failure.value)
    assert json.loads(await tools.inspect())["scene"]["revision"] == before


async def test_hiding_most_of_the_visible_scene_needs_an_explicit_confirmation(core, tools):
    made = await notes(tools, 4)
    await tools.inspect()

    with pytest.raises(DisplayToolError) as failure:
        await tools.update_many(select={"kind": "window"}, visibility="hidden")
    assert failure.value.code == "selection_too_broad" and "confirm=true" in str(failure.value)
    stored = await snapshot_objects(core)
    assert all(stored[object_id]["visibility"] == "visible" for object_id in made)

    result = await tools.update_many(select={"kind": "window"}, visibility="hidden", confirm=True)
    assert result["applied"] == 4
    stored = await snapshot_objects(core)
    assert all(stored[object_id]["visibility"] == "hidden" for object_id in made)


async def test_a_narrow_hiding_batch_needs_no_confirmation(core, tools):
    made = await notes(tools, 8)
    await tools.inspect()

    result = await tools.update_many(object_ids=made[:2], visibility="hidden")

    assert result["applied"] == 2


async def test_showing_a_whole_set_again_never_needs_confirmation(core, tools):
    made = await notes(tools, 4)
    await tools.update_many(select={"kind": "window"}, visibility="hidden", confirm=True)
    await tools.inspect()

    result = await tools.update_many(select={"kind": "window", "visibility": "hidden"}, visibility="visible")

    assert result["applied"] == 4
    stored = await snapshot_objects(core)
    assert all(stored[object_id]["visibility"] == "visible" for object_id in made)


# ------------------------------------------------------------------ sélecteur = celui de scene_query


async def test_connected_designates_a_whole_constellation_for_reading_and_for_acting(core, tools):
    await observe(core, {"external_id": "run-1", "status": "running", "kind": "agent", "label": "Tâche code"})
    await wait_for(core, lambda snap: "claude:run-1" in {item["object_id"] for item in snap["objects"]})
    artifact = await tools.add_artifact(target_id="claude:run-1", category="research", title="Notes")
    apart = (await tools.create_object(kind="window", category="note", title="Sans lien"))["object_id"]
    await tools.inspect()

    listing = json.loads(await tools.query(connected={"object_id": "claude:run-1"}))
    seen = {row[0] for row in listing["o"]}
    assert {"claude:run-1", artifact["object_id"]} <= seen and apart not in seen

    result = await tools.update_many(select={"connected": {"object_id": "claude:run-1"}}, annotation="tâche code")

    assert result["applied"] == len(seen)
    stored = await snapshot_objects(core)
    assert stored["claude:run-1"]["payload"]["annotation"] == "tâche code"
    assert stored[artifact["object_id"]]["payload"]["annotation"] == "tâche code"
    assert stored[apart]["payload"].get("annotation", "") == ""


async def test_connected_depth_limits_the_constellation_to_its_first_hops(core, tools):
    first = (await tools.create_object(kind="group", category="plan", title="Racine"))["object_id"]
    second = (await tools.create_object(kind="window", category="note", title="Voisin"))["object_id"]
    third = (await tools.create_object(kind="window", category="note", title="Lointain"))["object_id"]
    await tools.link(from_id=first, to_id=second, kind="groups")
    await tools.link(from_id=second, to_id=third, kind="groups")
    await tools.inspect()

    close = json.loads(await tools.query(connected={"object_id": first, "depth": 1}))
    assert {row[0] for row in close["o"]} == {first, second}
    whole = json.loads(await tools.query(connected={"object_id": first}))
    assert {row[0] for row in whole["o"]} == {first, second, third}


async def test_a_selector_whose_reference_is_gone_is_refused_without_sending_anything(core, tools):
    made = await notes(tools, 2)
    await user_command(core, {"op": "archive", "object_id": made[0]})
    await tools.inspect()

    with pytest.raises(DisplayToolError) as failure:
        await tools.update_many(select={"connected": {"object_id": made[0]}}, visibility="hidden")

    assert failure.value.reason == "object_archived" and "Rien n'a été envoyé" in str(failure.value)


# ------------------------------------------------------------------ arguments


@pytest.mark.parametrize("call", [
    {"visibility": "hidden"},
    {"select": {"kind": "window"}, "object_ids": ["brain-window-1"], "visibility": "hidden"},
    {"select": {"kind": "window"}},
    {"select": {}, "visibility": "hidden"},
    {"object_ids": [], "visibility": "hidden"},
    {"select": {"kind": "window"}, "annotation": "x" * (MAX_ANNOTATION_CHARS + 1)},
    {"select": {"connected": {"object_id": "brain-window-1", "depth": 0}}, "visibility": "hidden"},
])
async def test_a_malformed_batch_call_sends_nothing(call):
    spy = SpyTransport()
    from jarvis.runtime.display_mcp import SceneDisplayTools

    display = SceneDisplayTools(spy)
    with pytest.raises(DisplayToolError) as failure:
        await display.update_many(**call)
    assert failure.value.code == "invalid_argument" and not spy.commands


# ------------------------------------------------------------------ étiquettes


async def test_an_annotation_belongs_to_its_object_follows_it_and_dies_with_it(core, tools):
    [object_id] = await notes(tools, 1)
    await tools.inspect()

    await tools.update_object(object_id=object_id, annotation="tâche code, actions en lot")
    stored = await snapshot_objects(core)
    assert stored[object_id]["payload"]["annotation"] == "tâche code, actions en lot"
    assert stored[object_id]["payload"]["title"] == "Note 0"  # le reste de la charge est gardé

    # Elle suit l'objet : déplacer ne l'efface pas.
    await tools.update_object(object_id=object_id, geometry={"x": 20, "y": 20, "w": 10, "h": 8})
    stored = await snapshot_objects(core)
    assert stored[object_id]["payload"]["annotation"] == "tâche code, actions en lot"

    # Elle disparaît avec lui : l'utilisateur archive, plus rien à dessiner.
    await user_command(core, {"op": "archive", "object_id": object_id})
    assert object_id not in await snapshot_objects(core)


async def test_an_empty_annotation_removes_the_label(core, tools):
    [object_id] = await notes(tools, 1)
    await tools.update_object(object_id=object_id, annotation="à revoir")
    await tools.inspect()

    await tools.update_object(object_id=object_id, annotation="")

    stored = await snapshot_objects(core)
    assert stored[object_id]["payload"].get("annotation", "") == ""


async def test_the_detail_and_the_text_filter_see_the_annotation_as_scene_data(core, tools):
    [object_id] = await notes(tools, 1)
    await tools.update_object(object_id=object_id, annotation="revue des lots")
    await tools.inspect()

    detail = json.loads(await tools.get(object_ids=[object_id]))
    assert detail["objects"][0]["annotation"] == "revue des lots"
    assert "étiquettes (annotation)" in detail["scene"]["legend"]["data"]
    found = json.loads(await tools.query(text="revue des lots"))
    assert [row[0] for row in found["o"]] == [object_id]


def test_the_payload_keeps_the_wire_shape_when_no_label_is_set():
    assert "annotation" not in ScenePayload(title="x").to_payload()
    assert ScenePayload(title="x", annotation="y").to_payload()["annotation"] == "y"
    assert ScenePayload.from_payload({"title": "x", "annotation": "y"}).annotation == "y"
    assert ScenePayload.from_payload({"title": "x"}).annotation == ""
    with pytest.raises(ValueError):
        ScenePayload(annotation="x" * (MAX_ANNOTATION_CHARS + 1))


# ------------------------------------------------------------------ catalogue


async def test_the_batch_tool_says_when_to_prefer_it_and_still_offers_no_archive_or_pin():
    from pathlib import Path

    from jarvis.runtime.display_mcp import DisplayMcpTarget

    server = build_server(DisplayMcpTarget("127.0.0.1", 1, Path("absent.token")))
    listed = {tool.name: tool for tool in await server.list_tools()}
    batch = listed["scene_update_many"]
    assert "en un seul appel" in batch.description and "pinned_by_user" in batch.description
    assert "confirm=true" in batch.description and "scene_query" in batch.description
    assert "Rien n'archive ni n'épingle ici." in batch.description
    assert set(batch.inputSchema["properties"]) == {
        "select", "object_ids", "visibility", "representation", "category", "layer", "order", "annotation", "confirm"}
    assert batch.inputSchema["additionalProperties"] is False
    bound = json.dumps(batch.inputSchema["properties"]["object_ids"], separators=(",", ":"))
    assert f'"maxItems":{MAX_BATCH_TARGETS}' in bound
    # L'étiquette est offerte là où elle se pose, et nulle part ailleurs.
    assert "annotation" in listed["scene_update_object"].inputSchema["properties"]
    assert "annotation" in listed["scene_create_object"].inputSchema["properties"]
    assert "annotation" not in listed["scene_set_visibility"].inputSchema["properties"]
