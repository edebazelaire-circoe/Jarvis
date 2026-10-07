"""`jarvis.checklist` côté domaine et Core (prefab-foundation, Slice 06).

Le prefab livré (`jarvis/prefabs/base/jarvis.checklist/1/`, verrouillé) est
lu par le vrai catalogue (`PrefabService` sur le paquet), ses instances
passent par la vraie scène (`SceneService` SQLite, réducteur, validateur de
prefabs) et ses événements par `PrefabEventService` ; puis la pile réelle
Core + Control Center pour l'anneau `GET /v1/prefabs/events`.

Contrat : `docs/prefabs.md` › *Base catalogue* et *Structured inputs and
events* ; doc 06 R2 (manifeste), D-EVENTS, R9.1.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiohttp
import pytest

import jarvis
from jarvis.adapters.file_prefab_library import FilePrefabLibrary
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.prefab_events import PrefabEventOutcome, PrefabEventService
from jarvis.core.prefab_service import PrefabService
from jarvis.core.scene_service import SceneService, SceneState
from jarvis.domain.prefab import PrefabInstanceRef
from jarvis.domain.scene import (
    Representation, SceneActor, SceneCommand, SceneCommandOutcome, SceneGeometry, SceneObjectFields, SceneObjectKind,
    SceneOp, ScenePayload, ScenePrefabRef,
)
from tests.fakes.capture_stack import TOKEN, CaptureStack

PACKAGE = Path(jarvis.__file__).resolve().parent / "prefabs" / "base"
PREFAB = {"id": "jarvis.checklist", "version": 1}
ITEMS = [{"id": "a", "label": "Relire", "done": True}, {"id": "b", "label": "Mesurer"},
         {"id": "c", "label": "Décider", "note": "Avant vendredi.\nAvec Clarice."}]


def items(n: int, **extra) -> list[dict]:
    return [{"id": f"i{k}", "label": f"Élément {k}", **extra} for k in range(n)]


def window(data: dict, object_id: str = "ck-1", props: dict | None = None, actor=SceneActor.BRAIN) -> SceneCommand:
    return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=actor, object_id=object_id, fields=SceneObjectFields(
        kind=SceneObjectKind.WINDOW, category="research", representation=Representation.WINDOW,
        geometry=SceneGeometry(0, 0, 60, 48), payload=ScenePayload(title="Liste", prefab=ScenePrefabRef(
            "jarvis.checklist", 1, props or {}, data))))


def toggled(new_items: list[dict], basis_items: list[dict], object_id: str = "ck-1") -> dict:
    return {"actor": "user", "object_id": object_id, "prefab": PREFAB, "event": "item_toggled",
            "payload": {"items": new_items}, "basis": {"items": basis_items}}


def flip(stored: list[dict], index: int) -> list[dict]:
    out = [dict(item) for item in stored]
    out[index]["done"] = not out[index].get("done", False)
    return out


@pytest.fixture
async def catalog(tmp_path: Path) -> PrefabService:
    service = PrefabService(FilePrefabLibrary(PACKAGE, tmp_path / "data"))
    await service.start()
    return service


@pytest.fixture
async def stack(tmp_path: Path, catalog: PrefabService):
    scene = SceneService(SQLiteSceneRepository(tmp_path / "scene.sqlite3"), prefab_validator=catalog)
    assert (await scene.start()).state is SceneState.READY
    update = await scene.apply(window({"items": ITEMS}))
    assert update.outcome is SceneCommandOutcome.APPLIED, update.detail
    yield scene, PrefabEventService(scene, catalog)
    await scene.close()


async def data_of(scene: SceneService, object_id: str = "ck-1") -> dict:
    return (await scene.snapshot()).get_object(object_id).payload.prefab.data


# ------------------------------------------------------------------ données structurées


@pytest.mark.parametrize("count", [0, 1, 64])
async def test_empty_one_and_sixty_four_items_are_accepted_with_defaults(catalog, count):
    result = await catalog.validate_instance(PrefabInstanceRef("jarvis.checklist", 1, {}, {"items": items(count)}))
    assert result.ok, result.detail
    assert result.props == {"accent": "#6ee7ff", "show_progress": True}
    assert len(result.data["items"]) == count and all(item["done"] is False for item in result.data["items"])
    assert all("note" not in item for item in result.data["items"])  # un champ facultatif absent le reste


@pytest.mark.parametrize(("data", "needle"), [
    ({"items": items(65)}, "items"),
    ({}, "items"),
    ({"items": [{"id": "a"}]}, "label"),
    ({"items": [{"id": "a" * 65, "label": "x"}]}, "id"),
    ({"items": [{"id": "a", "label": "x" * 201}]}, "label"),
    ({"items": [{"id": "a", "label": "x", "note": "n" * 501}]}, "note"),
    ({"items": [{"id": "a", "label": "x", "note": "bip\u0007"}]}, "note"),
    ({"items": [{"id": "a", "label": "x", "done": "yes"}]}, "done"),
    ({"items": [{"id": "a", "label": "x", "owner": "me"}]}, "owner"),
], ids=["65-items", "no-items", "no-label", "long-id", "long-label", "long-note", "control-char", "done-type",
        "unknown-key"])
async def test_out_of_contract_data_is_refused(catalog, data, needle):
    result = await catalog.validate_instance(PrefabInstanceRef("jarvis.checklist", 1, {}, data))
    assert not result.ok and needle in result.detail


async def test_a_note_at_its_bound_with_line_breaks_is_kept(catalog):
    note = ("ligne\n\tretrait " * 40)[:500]
    result = await catalog.validate_instance(PrefabInstanceRef(
        "jarvis.checklist", 1, {"accent": "#ff7a59", "show_progress": False},
        {"items": [{"id": "a", "label": "x", "note": note}]}))
    assert result.ok and result.data["items"][0]["note"] == note and result.props["show_progress"] is False


async def test_the_scene_refuses_a_sixty_five_item_window_with_its_detail(stack):
    scene, _ = stack
    update = await scene.apply(window({"items": items(65)}, object_id="ck-2"))
    assert update.outcome is SceneCommandOutcome.INVALID and update.reason.value == "prefab_invalid"
    assert update.detail.startswith("ck-2: ") and (await scene.snapshot()).get_object("ck-2") is None


# ------------------------------------------------------------------ événements


async def test_a_toggle_is_written_by_the_reducer_and_persisted(stack, tmp_path, catalog):
    scene, events = stack
    stored = (await data_of(scene))["items"]
    revision = (await scene.snapshot()).revision
    result = await events.submit(toggled(flip(stored, 1), stored))
    assert result.outcome is PrefabEventOutcome.APPLIED and result.revision == revision + 1
    assert [item["done"] for item in (await data_of(scene))["items"]] == [True, True, False]
    assert (await data_of(scene))["items"][2]["note"] == "Avant vendredi.\nAvec Clarice."
    [entry] = events.entries()
    assert (entry.event, entry.event_class.value, entry.outcome.value) == ("item_toggled", "state", "applied")
    await scene.close()
    # Relu depuis le disque par une autre instance de la scène.
    reopened = SceneService(SQLiteSceneRepository(tmp_path / "scene.sqlite3"), prefab_validator=catalog)
    assert (await reopened.start()).state is SceneState.READY
    try:
        assert [item["done"] for item in (await data_of(reopened))["items"]] == [True, True, False]
        assert (await reopened.snapshot()).revision == revision + 1
    finally:
        await reopened.close()


async def test_a_brain_replacement_racing_a_toggle_wins_and_the_toggle_is_stale(stack):
    scene, events = stack
    stored = (await data_of(scene))["items"]
    revision = (await scene.snapshot()).revision
    gate = asyncio.Event()
    original = scene._repository.commit

    async def slow_commit(*args):
        await gate.wait()
        return await original(*args)

    scene._repository.commit = slow_commit
    clicked = toggled(flip(stored, 1), stored)
    brain = asyncio.ensure_future(scene.apply(window({"items": [{"id": "x", "label": "Liste de Jarvis"}]})))
    try:
        await asyncio.sleep(0.02)  # Jarvis tient le verrou de la scène, son écriture n'est pas finie
        click = asyncio.ensure_future(events.submit(clicked))
        await asyncio.sleep(0.02)
    finally:
        gate.set()  # toujours relâcher : sinon la fermeture de la scène attendrait sans fin
    applied, result = await asyncio.wait_for(asyncio.gather(brain, click), 10)
    assert applied.outcome is SceneCommandOutcome.APPLIED
    assert result.outcome is PrefabEventOutcome.STALE and result.reason == "stale"
    assert result.revision == revision + 1  # la révision de Jarvis ; le clic n'a rien écrit
    assert (await data_of(scene))["items"] == [{"id": "x", "label": "Liste de Jarvis", "done": False}]  # défauts (A3)
    assert (await scene.snapshot()).revision == revision + 1


async def test_a_toggle_outside_the_contract_writes_nothing(stack):
    scene, events = stack
    stored = (await data_of(scene))["items"]
    revision = (await scene.snapshot()).revision
    for payload, reason in (({"items": items(65)}, "invalid_event"),
                            ({"items": stored, "title": "x"}, "invalid_event")):
        result = await events.submit({**toggled([], stored), "payload": payload})
        assert (result.outcome, result.reason) == (PrefabEventOutcome.REFUSED, reason)
    result = await events.submit({**toggled([], stored), "event": "checklist_completed", "payload": {"count": 99}})
    assert (result.outcome, result.reason) == (PrefabEventOutcome.REFUSED, "invalid_payload")
    assert (await scene.snapshot()).revision == revision and (await data_of(scene))["items"] == stored


async def test_completion_is_recorded_in_the_core_ring_and_offered_to_the_brain_once(tmp_path):
    async with CaptureStack(tmp_path) as stack, aiohttp.ClientSession() as http:
        assert (await stack.core.scene.apply(window({"items": ITEMS}))).outcome is SceneCommandOutcome.APPLIED
        stored = (await data_of(stack.core.scene))["items"]
        done = [dict(item, done=True) for item in stored]
        status, answer, _ = await stack.call("POST", "/api/prefabs/events", json=toggled(done, stored))
        assert status == 200 and answer["outcome"] == "applied"
        status, answer, _ = await stack.call("POST", "/api/prefabs/events", json={
            "actor": "user", "object_id": "ck-1", "prefab": PREFAB, "event": "checklist_completed",
            "payload": {"count": 3}})
        assert status == 200 and answer == {"outcome": "recorded"}
        async with http.get(stack.core_url + "/v1/prefabs/events", params={"object_id": "ck-1"},
                            headers={"Authorization": f"Bearer {TOKEN}"}) as response:
            assert response.status == 200
            ring = (await response.json())["events"]
        assert [(e["event"], e["class"], e["outcome"]) for e in ring] == [
            ("item_toggled", "state", "applied"), ("checklist_completed", "notify", "recorded")]
        assert ring[1]["prefab"] == "jarvis.checklist@1" and ring[1]["payload"] == {"count": 3}
        [delivered] = stack.core.prefab_events.take_undelivered_notify()
        assert delivered.event == "checklist_completed" and stack.core.prefab_events.take_undelivered_notify() == ()
        assert all(item["done"] for item in (await data_of(stack.core.scene))["items"])


async def test_sixty_four_long_labels_are_tickable_through_core_b6(stack):
    """Reprise QA S06 F4 / A5 : 64 éléments de ~95 caractères (> 8 Kio d'événement) se cochent par le vrai réducteur."""

    import json

    scene, events = stack
    long_items = [{"id": f"item-{n:02d}", "label": (f"Élément {n:02d} " + "à vérifier avant la livraison " * 4)[:95]}
                  for n in range(64)]
    assert (await scene.apply(window({"items": long_items}))).outcome is SceneCommandOutcome.APPLIED
    stored = (await data_of(scene))["items"]
    revision = (await scene.snapshot()).revision
    clicked = toggled(flip(stored, 63), stored)
    assert len(json.dumps(clicked["payload"], ensure_ascii=False, separators=(",", ":")).encode()) > 8 * 1024
    result = await events.submit(clicked)
    assert result.outcome is PrefabEventOutcome.APPLIED, result
    assert (await scene.snapshot()).revision == revision + 1 and (await data_of(scene))["items"][63]["done"] is True
