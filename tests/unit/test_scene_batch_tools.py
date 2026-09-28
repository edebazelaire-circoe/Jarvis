"""Lots sémantiques de la scène (handoff jarvis-mcp-semantic-batch-inspector, Slice 05) et étiquettes.

`scene_update_many`, `scene_move`, `scene_archive` et `scene_pin` traduisent
`select` / `object_ids` en **une** `SceneSelection` et envoient **une** commande
de sélection à Core. Chaîne réelle : `SceneDisplayTools` → `CoreSceneTransport`
→ `LocalProtocolServer` → `JarvisCoreApplication.scene`. Ce qui doit tenir
(`docs/scene-selection-batch.md`, `docs/mcp/tool-contract.md` §6) :

- un appel sémantique = **une** requête de commande à Core = une révision ;
- tout ou rien : un refus n'applique rien, ne change pas la révision, et le
  dit en nommant chaque fautif ; jamais `best_effort`, jamais un compte partiel ;
- le résultat est le compte rendu du domaine (`SceneBatchResult`) : comptes
  exacts, listes bornées, `hidden_count` ;
- l'épingle de l'utilisateur protège la **place**, pas le reste ;
- le sélecteur est celui de `scene_query` (constellation canonique du
  domaine comprise) : ce que la lecture liste est ce que le lot touche ;
- une étiquette (`annotation`) appartient à l'objet annoté.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain.scene import MAX_ANNOTATION_CHARS, ScenePayload
from jarvis.domain.scene_selection import MAX_SELECTION_IDS
from jarvis.runtime.display_mcp import (
    BATCH_TRANSPORT_NOTE,
    MAX_BULK_REPORTED_IDS,
    DisplayToolError,
    SceneDisplayTools,
    build_server,
)
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.scene_view import CoreSceneTransport
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


async def revision(core: CoreProcess) -> int:
    status, body, _ = await core.request("GET", "/v1/scene/snapshot")
    assert status == 200
    return body["snapshot"]["revision"]


class CountingTransport:
    """Le vrai transport vers Core, qui compte chaque requête de commande envoyée."""

    def __init__(self, inner: CoreSceneTransport) -> None:
        self.inner = inner
        self.commands: list[dict] = []

    async def scene_command(self, command, **timeouts):  # noqa: ANN001, ANN003
        self.commands.append(command)
        return await self.inner.scene_command(command, **timeouts)

    async def scene_snapshot(self):  # noqa: ANN201
        return await self.inner.scene_snapshot()

    async def close(self) -> None:
        await self.inner.close()


@pytest.fixture
async def counted(core):
    transport = CountingTransport(CoreSceneTransport(host="127.0.0.1", port=core.port, token_file=core.token_file))
    display = SceneDisplayTools(transport)
    try:
        yield display, transport
    finally:
        await display.close()


# ------------------------------------------------------------------ un appel = une commande = une révision


async def test_each_semantic_batch_is_exactly_one_core_command_and_one_revision(core, counted):
    display, transport = counted
    made = await notes(display, 6)
    json.loads(await display.inspect())
    calls = (
        ("patch_selection", lambda: display.update_many(select={"kind": "window"}, representation="capsule", layer=150)),
        ("translate_selection", lambda: display.move(select={"kind": "window"}, dx=5, dy=-4)),
        ("pin_selection", lambda: display.pin(pinned=True, object_ids=made)),
        ("unpin_selection", lambda: display.pin(pinned=False, select={"category": "note"})),
        ("archive_selection", lambda: display.archive(object_ids=made[:4])),
    )
    for op, call in calls:
        before, sent = await revision(core), len(transport.commands)
        result = await call()
        assert len(transport.commands) == sent + 1, op
        assert transport.commands[-1]["op"] == op and transport.commands[-1]["actor"] == "brain"
        assert await revision(core) == before + 1 == result["revision"], op
        assert result["outcome"] == "applied" and result["op"] == op
        assert "atomicity" not in result and "remaining" not in result and "deadline_reached" not in result
    stored = await snapshot_objects(core)
    assert set(made[4:]) <= set(stored) and not set(made[:4]) & set(stored)
    assert all(stored[object_id]["geometry"]["x"] == -100 + index * 12 + 5 for index, object_id in enumerate(made) if index >= 4)


async def test_a_refused_batch_applies_nothing_keeps_the_revision_and_names_every_offender(core, counted, tmp_path):
    display, transport = counted
    made = await notes(display, 3)
    await user_command(core, {"op": "archive", "object_id": made[1]})
    json.loads(await display.inspect())
    before = await revision(core)

    with pytest.raises(DisplayToolError) as refused:
        await display.update_many(object_ids=[made[0], made[1], "brain-window-absent", made[2]], annotation="revue")

    text = str(refused.value)
    assert refused.value.outcome == "invalid" and refused.value.reason == "object_archived"
    assert "Rien n'a été appliqué" in text and f"{made[1]} (object_archived, ids)" in text
    assert "brain-window-absent (unknown_object, ids)" in text
    assert len([c for c in transport.commands if c["op"] == "patch_selection"]) == 1
    assert await revision(core) == before
    stored = await snapshot_objects(core)
    assert all(stored[object_id]["payload"].get("annotation", "") == "" for object_id in (made[0], made[2]))


async def test_a_second_identical_batch_is_a_duplicate_without_revision(core, tools):
    made = await notes(tools, 3)
    await tools.inspect()
    first = await tools.update_many(object_ids=made, category="archive")
    assert first["changed_count"] == 3 and first["unchanged_count"] == 0

    again = await tools.update_many(object_ids=made, category="archive")

    assert again["outcome"] == "duplicate" and again["revision"] == first["revision"]
    assert again["changed_ids"] == [] and again["unchanged_ids"] == made and "note" in again


async def test_an_empty_selection_is_a_true_no_op_not_an_error(core, tools):
    await notes(tools, 2)
    await tools.inspect()
    before = await revision(core)

    result = await tools.update_many(select={"kind": "artifact"}, visibility="hidden")

    assert result["outcome"] == "duplicate" and result["matched_count"] == 0 and "aucun objet" in result["note"]
    assert await revision(core) == before


async def test_a_transport_failure_is_one_tool_error_never_a_partial_count():
    async def down(_command):  # noqa: ANN001
        raise ConnectionRefusedError("refused")

    spy = SpyTransport(command=down)
    with pytest.raises(DisplayToolError) as failure:
        await SceneDisplayTools(spy).archive(object_ids=["a", "b", "c"])
    assert len(spy.commands) == 1 and spy.commands[0]["op"] == "archive_selection"
    assert BATCH_TRANSPORT_NOTE in str(failure.value) and "objet(s)" not in str(failure.value)


async def test_the_brain_ids_are_deduplicated_before_the_domain_sees_them(core, tools):
    made = await notes(tools, 2)
    await tools.inspect()

    result = await tools.update_many(object_ids=[made[0], made[1], made[0]], layer=160)

    assert result["matched_ids"] == made and result["changed_count"] == 2


async def test_id_lists_are_capped_but_counts_stay_exact(core, tools):
    made = await notes(tools, MAX_BULK_REPORTED_IDS + 3)
    await tools.inspect()

    result = await tools.update_many(select={"kind": "window"}, layer=170)

    assert result["matched_count"] == result["changed_count"] == len(made)
    assert len(result["matched_ids"]) == len(result["changed_ids"]) == MAX_BULK_REPORTED_IDS


# ------------------------------------------------------------------ « réaffiche tout »


async def test_show_all_hidden_is_one_update_many_call_including_objects_new_since_the_last_read(core, tools, tmp_path):
    a = (await tools.create_object(kind="artifact", category="note", title="A"))["object_id"]
    b = (await tools.create_object(kind="artifact", category="note", title="B"))["object_id"]
    json.loads(await tools.inspect())
    await user_command(core, {"op": "set_visibility", "object_id": a, "visibility": "hidden"})
    await observe(core, {"external_id": "late", "status": "failed", "kind": "agent", "label": "tardif", "error_class": "Boom"})
    await wait_for(core, lambda snap: any(o["object_id"] == "claude:late" for o in snap["objects"]))
    await user_command(core, {"op": "set_visibility", "object_id": "claude:late", "visibility": "hidden"})

    result = await tools.update_many(select={"visibility": "hidden"}, visibility="visible")

    assert (result["matched_count"], result["changed_count"], result["hidden_count"]) == (2, 2, 2)
    assert set(result["changed_ids"]) == {a, "claude:late"}
    snap = await wait_for(core, lambda snap: True)
    assert all(o["visibility"] == "visible" for o in snap["objects"]) and b in {o["object_id"] for o in snap["objects"]}
    # La scène vue suit le patch du lot : la commande suivante ne signale rien.
    assert "scene_changed" not in await tools.update_object(object_id=b, geometry={"x": 0, "y": 0, "w": 5, "h": 5})
    summary = [e for e in read_jsonl_tail(tmp_path / "runtime" / "trace.jsonl", limit=80)
               if e["data"].get("tool") == "scene_update_many"]
    assert summary and summary[-1]["data"]["changed"] == 2 and summary[-1]["data"]["op"] == "patch_selection"
    # Plus rien de masqué : un no-op vrai.
    assert (await tools.update_many(select={"visibility": "hidden"}, visibility="visible"))["matched_count"] == 0


async def test_the_old_visibility_tool_is_gone_without_alias(core, tools):
    from mcp.shared.memory import create_connected_server_and_client_session

    from jarvis.runtime.claude_local import BRAIN_DISPLAY_PROMPT

    async with create_connected_server_and_client_session(build_server(tools=tools)) as session:
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert "scene_set_visibility" not in names and "scene_move" in names
        gone = await session.call_tool("scene_set_visibility", {"scope": "all_hidden", "visibility": "visible"})
        assert gone.isError is True
    assert not hasattr(tools, "set_visibility")
    assert "scene_set_visibility" not in BRAIN_DISPLAY_PROMPT and "all_hidden" not in BRAIN_DISPLAY_PROMPT


# ------------------------------------------------------------------ l'épingle de l'utilisateur


async def test_a_batch_reaches_a_pinned_object_like_any_other_and_never_moves_it(core, tools):
    made = await notes(tools, 3)
    pinned = made[0]
    await user_command(core, {"op": "pin", "object_id": pinned})
    await tools.inspect()

    result = await tools.update_many(select={"kind": "window"}, representation="capsule", layer=200)

    assert result["changed_count"] == 3 and result["skipped_count"] == 0
    stored = await snapshot_objects(core)
    assert all(stored[object_id]["representation"] == "capsule" for object_id in made)
    assert stored[pinned]["layer"] == 200 and stored[pinned]["constraints"]["pinned_by_user"] is True
    assert stored[pinned]["geometry"]["x"] == -100


async def test_a_batch_hides_and_shows_a_pinned_object_without_moving_it(core, tools):
    made = await notes(tools, 3)
    pinned = made[0]
    await user_command(core, {"op": "pin", "object_id": pinned})
    await tools.inspect()

    await tools.update_many(select={"kind": "window"}, visibility="hidden", confirm=True)
    result = await tools.update_many(object_ids=made, visibility="visible")

    assert result["changed_count"] == 3 and result["hidden_count"] == 3
    stored = await snapshot_objects(core)
    assert all(stored[object_id]["visibility"] == "visible" for object_id in made)
    assert stored[pinned]["constraints"]["pinned_by_user"] is True and stored[pinned]["geometry"]["x"] == -100


# ------------------------------------------------------------------ garde-fou du masquage


async def test_hiding_most_of_the_visible_scene_needs_an_explicit_confirmation(core, counted):
    display, transport = counted
    made = await notes(display, 4)
    await display.inspect()
    sent = len(transport.commands)

    with pytest.raises(DisplayToolError) as failure:
        await display.update_many(select={"kind": "window"}, visibility="hidden")
    assert failure.value.code == "selection_too_broad" and "confirm=true" in str(failure.value)
    assert "rien n'a été envoyé" in str(failure.value) and len(transport.commands) == sent

    result = await display.update_many(select={"kind": "window"}, visibility="hidden", confirm=True)
    assert result["changed_count"] == 4
    stored = await snapshot_objects(core)
    assert all(stored[object_id]["visibility"] == "hidden" for object_id in made)


async def test_a_narrow_hiding_batch_needs_no_confirmation(core, tools):
    made = await notes(tools, 8)
    await tools.inspect()

    result = await tools.update_many(object_ids=made[:2], visibility="hidden")

    assert result["changed_count"] == 2


# ------------------------------------------------------------------ sélecteur = celui de scene_query


async def test_constellation_designates_the_same_set_for_reading_and_for_acting(core, tools):
    await observe(core, {"external_id": "run-1", "status": "running", "kind": "agent", "label": "Tâche code"})
    await wait_for(core, lambda snap: "claude:run-1" in {item["object_id"] for item in snap["objects"]})
    artifact = await tools.add_artifact(target_id="claude:run-1", category="research", title="Notes")
    apart = (await tools.create_object(kind="window", category="note", title="Sans lien"))["object_id"]
    await user_command(core, {"op": "set_visibility", "object_id": artifact["object_id"], "visibility": "hidden"})
    await tools.inspect()

    listing = json.loads(await tools.query(constellation={"object_id": "claude:run-1"}))
    seen = [row[0] for row in listing["o"]]
    assert {"claude:run-1", artifact["object_id"]} <= set(seen) and apart not in seen

    result = await tools.update_many(select={"constellation": {"object_id": "claude:run-1"}}, annotation="tâche code")

    assert set(result["matched_ids"]) == set(seen) and result["hidden_count"] == 1
    stored = await snapshot_objects(core)
    assert stored["claude:run-1"]["payload"]["annotation"] == "tâche code"
    assert stored[artifact["object_id"]]["payload"]["annotation"] == "tâche code"
    assert stored[apart]["payload"].get("annotation", "") == ""


async def test_constellation_depth_limits_the_set_to_its_first_hops(core, tools):
    first = (await tools.create_object(kind="group", category="plan", title="Racine"))["object_id"]
    second = (await tools.create_object(kind="window", category="note", title="Voisin"))["object_id"]
    third = (await tools.create_object(kind="window", category="note", title="Lointain"))["object_id"]
    await tools.link(from_id=first, to_id=second, kind="groups")
    await tools.link(from_id=second, to_id=third, kind="groups")
    await tools.inspect()

    close = json.loads(await tools.query(constellation={"object_id": first, "depth": 1}))
    assert {row[0] for row in close["o"]} == {first, second}
    whole = json.loads(await tools.query(constellation={"object_id": first}))
    assert {row[0] for row in whole["o"]} == {first, second, third}
    members = json.loads(await tools.query(group=first))
    assert {row[0] for row in members["o"]} == {second}
    rest = json.loads(await tools.query(constellation={"object_id": first}, exclude=[third]))
    assert {row[0] for row in rest["o"]} == {first, second}


async def test_a_write_selector_whose_reference_is_gone_is_refused_whole_by_core(core, tools):
    made = await notes(tools, 2)
    await user_command(core, {"op": "archive", "object_id": made[0]})
    await tools.inspect()
    before = await revision(core)

    with pytest.raises(DisplayToolError) as failure:
        await tools.update_many(select={"constellation": {"object_id": made[0]}}, visibility="hidden")

    assert failure.value.reason == "object_archived" and "Rien n'a été appliqué" in str(failure.value)
    assert f"{made[0]} (object_archived, constellation)" in str(failure.value)
    assert await revision(core) == before


# ------------------------------------------------------------------ scene_move


async def test_scene_move_translates_a_constellation_rigidly_in_one_revision(core, tools):
    root = (await tools.create_object(kind="group", category="plan", title="R",
                                      geometry={"x": -20, "y": -10, "w": 10, "h": 8}))["object_id"]
    leaf = (await tools.create_object(kind="window", category="note", title="F",
                                      geometry={"x": 5, "y": 12, "w": 10, "h": 8}))["object_id"]
    loose = (await tools.create_object(kind="window", category="note", title="Libre",
                                       geometry={"x": 60, "y": 30, "w": 10, "h": 8}))["object_id"]
    await tools.link(from_id=root, to_id=leaf, kind="groups")
    await tools.inspect()

    result = await tools.move(select={"constellation": {"object_id": root}}, dx=-30, dy=4.5, pin=True)

    assert result["op"] == "translate_selection" and result["changed_count"] == 2
    assert result["delta"] == {"requested": {"dx": -30.0, "dy": 4.5}, "effective": {"dx": -30.0, "dy": 4.5},
                               "clamped": False}
    stored = await snapshot_objects(core)
    assert (stored[root]["geometry"]["x"], stored[root]["geometry"]["y"]) == (-50, -5.5)
    assert (stored[leaf]["geometry"]["x"], stored[leaf]["geometry"]["y"]) == (-25, 16.5)
    assert stored[root]["constraints"]["pinned_by_user"] and stored[leaf]["constraints"]["pinned_by_user"]
    assert stored[loose]["geometry"]["x"] == 60 and not stored[loose]["constraints"]["pinned_by_user"]


async def test_scene_move_clamps_the_common_delta_at_the_safe_area_and_says_so(core, tools):
    made = await notes(tools, 2)
    await tools.inspect()

    result = await tools.move(object_ids=made, dx=-1000, dy=0)

    assert result["delta"]["clamped"] is True and -1000 < result["delta"]["effective"]["dx"] < 0
    stored = await snapshot_objects(core)
    # Offsets préservés : l'écart entre les deux notes ne change pas.
    assert stored[made[1]]["geometry"]["x"] - stored[made[0]]["geometry"]["x"] == 12
    blocked = await tools.move(object_ids=made, dx=-1000, dy=0)
    assert blocked["outcome"] == "duplicate" and "bord" in blocked["note"]


async def test_scene_move_refuses_an_unplaced_explicit_id_and_skips_an_unplaced_filter_member(core, tools):
    placed = await notes(tools, 1)
    unplaced = (await tools.create_object(kind="window", category="note", title="Sans place"))["object_id"]
    await tools.inspect()
    before = await revision(core)

    with pytest.raises(DisplayToolError) as refused:
        await tools.move(object_ids=[placed[0], unplaced], dx=3, dy=0)
    assert refused.value.reason == "unplaced" and f"{unplaced} (unplaced, ids)" in str(refused.value)
    assert await revision(core) == before

    result = await tools.move(select={"kind": "window"}, dx=3, dy=0)
    assert result["changed_ids"] == placed and result["skipped"] == [{"id": unplaced, "reason": "unplaced"}]
    assert result["skipped_count"] == 1


async def test_scene_move_is_not_idempotent_each_call_moves_again(core, tools):
    [object_id] = await notes(tools, 1)
    await tools.inspect()
    await tools.move(object_ids=[object_id], dx=2, dy=0)
    await tools.move(object_ids=[object_id], dx=2, dy=0)
    assert (await snapshot_objects(core))[object_id]["geometry"]["x"] == -96


# ------------------------------------------------------------------ scene_archive, scene_pin


async def test_archive_takes_a_star_signals_along_and_a_second_call_is_unchanged(core, tools):
    await observe(core, {"external_id": "p", "status": "failed", "kind": "agent", "label": "p", "error_class": "Boom"})
    snap = await wait_for(core, lambda snap: any(o["kind"] == "attention" for o in snap["objects"]))
    signals = [o["object_id"] for o in snap["objects"] if o["kind"] == "attention"]
    await tools.inspect()

    result = await tools.archive(object_ids=["claude:p"])

    assert result["changed_ids"] == ["claude:p"] and result["cascade_ids"] == signals
    assert not {"claude:p", *signals} & set(await snapshot_objects(core))
    again = await tools.archive(object_ids=["claude:p"])
    assert again["outcome"] == "duplicate" and again["unchanged_ids"] == ["claude:p"]


async def test_pin_by_filter_skips_what_has_no_place_and_pins_the_rest(core, tools):
    placed = await notes(tools, 2)
    unplaced = (await tools.create_object(kind="window", category="note", title="Sans place"))["object_id"]
    await tools.inspect()

    result = await tools.pin(pinned=True, select={"kind": "window"})

    assert result["pinned"] is True and result["changed_ids"] == placed
    assert result["skipped"] == [{"id": unplaced, "reason": "unplaced"}]
    stored = await snapshot_objects(core)
    assert all(stored[object_id]["constraints"]["pinned_by_user"] for object_id in placed)


# ------------------------------------------------------------------ journal


async def test_the_journal_keeps_the_counts_of_a_batch_without_any_content(core, tools, tmp_path):
    made = await notes(tools, 2)
    await tools.inspect()
    await tools.update_many(object_ids=made, annotation="secret d'utilisateur")

    entries = [entry for entry in read_jsonl_tail(tmp_path / "runtime" / "trace.jsonl", limit=200)
               if entry.get("data", {}).get("tool") == "scene_update_many"]
    data = entries[-1]["data"]
    assert (data["op"], data["by"], data["matched"], data["changed"]) == ("patch_selection", "explicit", 2, 2)
    assert "secret" not in json.dumps(entries, ensure_ascii=False)


# ------------------------------------------------------------------ arguments


@pytest.mark.parametrize("call", [
    {"visibility": "hidden"},
    {"select": {"kind": "window"}, "object_ids": ["brain-window-1"], "visibility": "hidden"},
    {"select": {"kind": "window"}},
    {"select": {}, "visibility": "hidden"},
    {"select": {"exclude": ["brain-window-1"]}, "visibility": "hidden"},
    {"object_ids": [], "visibility": "hidden"},
    {"select": {"kind": "window"}, "annotation": "x" * (MAX_ANNOTATION_CHARS + 1)},
    {"select": {"constellation": {"object_id": "brain-window-1", "depth": 0}}, "visibility": "hidden"},
    {"select": {"connected": {"object_id": "brain-window-1"}}, "visibility": "hidden"},
    {"select": {"kind": "window", "kinds": ["group"]}, "visibility": "hidden"},
    {"select": {"include_hidden": True, "kind": "window"}, "visibility": "hidden"},
    {"object_ids": ["x"] * 2 + [f"id-{n}" for n in range(MAX_SELECTION_IDS)], "visibility": "hidden"},
])
async def test_a_malformed_batch_call_sends_nothing(call):
    spy = SpyTransport()
    with pytest.raises(DisplayToolError) as failure:
        await SceneDisplayTools(spy).update_many(**call)
    assert failure.value.code == "invalid_argument" and not spy.commands


@pytest.mark.parametrize("call", [
    {"object_ids": ["a"], "dx": 0, "dy": 0},
    {"object_ids": ["a"], "dx": float("nan"), "dy": 1},
    {"object_ids": ["a"], "dx": 200_000, "dy": 1},
    {"dx": 1, "dy": 1},
    {"object_ids": ["a"], "dx": 1, "dy": 1, "pin": False},
])
async def test_a_malformed_move_sends_nothing(call):
    spy = SpyTransport()
    with pytest.raises(DisplayToolError) as failure:
        await SceneDisplayTools(spy).move(**call)
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


async def test_the_batch_tools_say_one_call_for_a_set_and_advertise_their_schemas():
    from pathlib import Path

    from jarvis.runtime.display_mcp import SELECT_FILTER_KEYS, DisplayMcpTarget

    server = build_server(DisplayMcpTarget("127.0.0.1", 1, Path("absent.token")))
    listed = {tool.name: tool for tool in await server.list_tools()}
    batch = listed["scene_update_many"]
    assert "en un appel et une seule commande" in batch.description and "Tout ou rien" in batch.description
    assert "confirm=true" in batch.description and "scene_query" in batch.description
    assert "hidden_count" in batch.description and "constellation" in batch.description
    assert "scene_move" in batch.description and "scene_archive" in batch.description and "scene_pin" in batch.description
    assert "best-effort" not in json.dumps({name: tool.description for name, tool in listed.items()})
    assert set(batch.inputSchema["properties"]) == {
        "select", "object_ids", "visibility", "representation", "category", "layer", "order", "annotation", "confirm"}
    assert batch.inputSchema["additionalProperties"] is False
    bound = json.dumps(batch.inputSchema["properties"]["object_ids"], separators=(",", ":"))
    assert f'"maxItems":{MAX_SELECTION_IDS}' in bound
    select = batch.inputSchema["$defs"]["SelectArg"]
    assert tuple(select["properties"]) == SELECT_FILTER_KEYS and select["additionalProperties"] is False
    move = listed["scene_move"]
    assert move.inputSchema["required"] == ["dx", "dy"] and "clamped" in move.description
    for name in ("scene_update_many", "scene_move", "scene_archive", "scene_pin"):
        output = listed[name].outputSchema
        assert output is not None and {"matched_count", "hidden_count"} <= set(output["properties"]), name
        assert set(output["required"]) >= {"op", "outcome", "revision", "matched_count", "changed_count", "hidden_count"}, name
    # L'étiquette est offerte là où elle se pose, et nulle part ailleurs.
    assert "annotation" in listed["scene_update_object"].inputSchema["properties"]
    assert "annotation" in listed["scene_create_object"].inputSchema["properties"]
    assert "annotation" not in listed["scene_move"].inputSchema["properties"]


# ------------------------------------------------------------------ reprise : lecture filtrée puis lot (trace réelle)


async def test_a_query_then_a_batch_never_reports_the_brain_own_command_as_a_change(core, tools):
    """Trace Slice 05, tour 1 : scene_query puis scene_update_many rendait « la scène a changé (N → N+1) »
    et listait six objets inchangés comme apparus."""

    made = await notes(tools, 6)
    json.loads(await tools.query(kind="window", category="note"))

    result = await tools.update_many(select={"kind": "window"}, layer=140)
    assert result["outcome"] == "applied" and "scene_changed" not in result
    again = await tools.update_many(object_ids=made[:2], annotation="lot")
    assert "scene_changed" not in again


async def test_a_filtered_inspection_then_an_archive_is_silent_but_an_external_change_is_not(core, tools):
    made = await notes(tools, 4)
    json.loads(await tools.inspect())
    json.loads(await tools.inspect(text="Note 1"))

    archived = await tools.archive(object_ids=[made[1]])
    assert archived["outcome"] == "applied" and "scene_changed" not in archived

    json.loads(await tools.query(text="Note 2"))
    await user_command(core, {"op": "set_visibility", "object_id": made[3], "visibility": "hidden"})
    moved = await tools.move(object_ids=[made[2]], dx=1, dy=0)
    hint = moved["scene_changed"]
    assert "a changé" in hint and f'~ {made[3]} (window) visible → hidden "Note 3"' in hint
    assert made[2] not in hint
