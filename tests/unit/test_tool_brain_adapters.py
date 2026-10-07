"""Adaptateurs d'exécution du Tool Brain pour la scène et les surfaces (handoff jarvis-tool-brain-ui-orchestrator, S7).

Contrat : `docs/tool-brain-contracts.md` §14.4 et §15. Tout est **réel** côté propriétaires : `SceneService` (SQLite) avec
le validateur de prefabs de Core (`PrefabService` sur la bibliothèque de base livrée, donc le manifeste de
`jarvis.browser@1`), file, exécuteur et `read_ui_state` du Tool Brain. Ce qui doit tenir :

- chaque mutateur passe par `SceneService.apply_if` (acteur `brain`), une seule fois, et change vraiment la scène ;
- un id fabriqué, retiré ou archivé entre le plan et l'exécution est une invalidation typée, le propriétaire n'écrit rien ;
- une adresse dangereuse (`javascript:`, `file:`, identifiants, hôte privé) est refusée **avant** l'écriture ;
- les surfaces sont enregistrées dans l'état canonique (`UiState.surfaces`) et offertes par `surface.browser` ;
- aucun outil irréversible, de création de contenu ou de lecture n'est exécutable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import jarvis
from jarvis.adapters.file_prefab_library import FilePrefabLibrary
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.prefab_service import PrefabService
from jarvis.core.scene_service import SceneService
from jarvis.domain.browser_surface import surface_id_of
from jarvis.domain.scene import (
    ExecState, Representation, SceneActor, SceneCommand, SceneGeometry, SceneObjectFields, SceneObjectKind, SceneOp,
    ScenePayload, Visibility,
)
from jarvis.runtime.tool_brain_choices import PROVIDERS, read_ui_state
from jarvis.runtime.tool_brain_executor import default_adapters
from jarvis.runtime.tool_brain_queue import (
    DONE, INVALIDATED, ActionRecord, ToolBrainActionQueue, Trigger, preconditions_from,
)
from tests.unit.test_tool_brain_executor import DISPLAY, FakeBoards, Rig, SpyScene, note

SURFACE = "jarvis-surface"
PACKAGE = Path(jarvis.__file__).resolve().parent / "prefabs" / "base"
A, B, C = "brain-note-a", "brain-note-b", "brain-note-c"


@pytest.fixture
async def stack(tmp_path):
    catalog = PrefabService(FilePrefabLibrary(PACKAGE, tmp_path / "data"))
    await catalog.start()
    service = SceneService(SQLiteSceneRepository(tmp_path / "scene.sqlite3"), prefab_validator=catalog)
    await service.start()
    for object_id in (A, B, C):
        assert (await service.apply(note(object_id))).outcome.value == "applied"
    # Un nœud d'exécution du runtime (tâche) : un objet de scène comme un autre pour la présentation.
    await service.apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.RUNTIME, object_id="claude:task-1",
                                     fields=SceneObjectFields(kind=SceneObjectKind.JOB, category="job",
                                                              exec_state=ExecState.RUNNING,
                                                              payload=ScenePayload(title="Compilation"))))
    rig = Rig(SpyScene(service), FakeBoards())
    # La file n'admet que ce que l'exécuteur sait exécuter (comme `tool_brain_wiring`).
    rig.queue = ToolBrainActionQueue(clock=rig.clock, supported=rig.executor.supports)
    rig.executor._queue = rig.queue
    yield rig
    await service.close()


async def run(rig, action_id, server, tool, arguments, **kw):
    """Planifie sur l'état courant puis exécute : le chemin complet file -> exécuteur -> propriétaire."""

    state = await read_ui_state(rig.scene, rig.boards)
    observed = state.ref()
    added = rig.queue.add(ActionRecord(action_id, server, tool, arguments, trigger=Trigger.from_payload(None),
                                       planned_from=observed, preconditions=preconditions_from(observed), **kw))
    assert added.queued, added
    return await rig.executor.execute(action_id)


async def get(rig, object_id):
    return (await rig.scene.snapshot()).get_object(object_id)


# ------------------------------------------------------------------ mutateurs de scène (07a)


async def test_update_object_shows_hides_resizes_and_raises_through_apply_if(stack):
    hidden = await run(stack, "h", DISPLAY, "scene_update_object", {"object_id": A, "visibility": "hidden"})
    assert (hidden.status, hidden.code) == (DONE, "applied") and (await get(stack, A)).visibility is Visibility.HIDDEN
    shown = await run(stack, "s", DISPLAY, "scene_update_object", {"object_id": A, "visibility": "visible"})
    assert shown.status == DONE and (await get(stack, A)).visibility is Visibility.VISIBLE
    resized = await run(stack, "r", DISPLAY, "scene_update_object",
                        {"object_id": A, "geometry": {"x": 1, "y": 2, "w": 30, "h": 20}, "layer": 400})
    assert resized.status == DONE
    item = await get(stack, A)
    assert (item.geometry, item.layer) == (SceneGeometry(1, 2, 30, 20), 400)
    again = await run(stack, "r2", DISPLAY, "scene_update_object", {"object_id": A, "layer": 400})
    assert (again.status, again.code) == (DONE, "unchanged")
    assert stack.scene.writes == 4  # une porte d'écriture par action, jamais deux


async def test_a_runtime_process_object_is_presented_like_any_scene_object_but_its_execution_state_is_untouchable(stack):
    moved = await run(stack, "m", DISPLAY, "scene_update_object",
                      {"object_id": "claude:task-1", "geometry": {"x": 5, "y": 5, "w": 20, "h": 10}})
    assert moved.status == DONE
    item = await get(stack, "claude:task-1")
    assert item.geometry.x == 5 and item.exec_state is ExecState.RUNNING
    hidden = await run(stack, "hide", DISPLAY, "scene_update_object", {"object_id": "claude:task-1", "visibility": "hidden"})
    assert hidden.status == DONE and (await get(stack, "claude:task-1")).exec_state is ExecState.RUNNING


async def test_prefab_and_source_path_arguments_are_not_executable_by_the_tool_brain(stack):
    revision = (await stack.scene.snapshot()).revision
    for number, arguments in enumerate(({"object_id": A, "prefab": {"prefab_id": "jarvis.window"}},
                                        {"object_id": A, "source_path": "C:/x"})):
        result = await run(stack, f"p{number}", DISPLAY, "scene_update_object", arguments)
        assert (result.status, result.code) == (INVALIDATED, "unsupported_argument")
    assert (await stack.scene.snapshot()).revision == revision


async def test_update_many_hides_a_set_in_one_revision_and_refuses_an_emptied_screen_without_confirm(stack):
    before = (await stack.scene.snapshot()).revision
    result = await run(stack, "m1", DISPLAY, "scene_update_many", {"object_ids": [A, B], "visibility": "hidden"})
    # 4 visibles (3 notes + la tâche) : en masquer 2 ne dépasse pas la moitié avant le seuil de 3.
    assert result.status == DONE and (await stack.scene.snapshot()).revision == before + 1
    shown = await run(stack, "m2", DISPLAY, "scene_update_many", {"object_ids": [A, B], "visibility": "visible"})
    assert shown.status == DONE
    refused = await run(stack, "m3", DISPLAY, "scene_update_many",
                        {"object_ids": [A, B, C], "visibility": "hidden"})
    assert (refused.status, refused.code) == (INVALIDATED, "selection_too_broad")
    assert (await get(stack, C)).visibility is Visibility.VISIBLE
    confirmed = await run(stack, "m4", DISPLAY, "scene_update_many",
                          {"object_ids": [A, B, C], "visibility": "hidden", "confirm": True})
    assert confirmed.status == DONE and (await get(stack, C)).visibility is Visibility.HIDDEN


async def test_pin_link_and_unlink_use_the_scene_owner_and_keep_runtime_relations_untouchable(stack):
    pinned = await run(stack, "pin", DISPLAY, "scene_pin", {"object_ids": [A], "pinned": True})
    assert pinned.status == DONE and (await get(stack, A)).constraints.pinned_by_user
    group = SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id="brain-group-g",
                         fields=SceneObjectFields(kind=SceneObjectKind.GROUP, category="note",
                                                  payload=ScenePayload(title="Groupe")))
    await stack.scene.service.apply(group)
    linked = await run(stack, "l1", DISPLAY, "scene_link", {"from_id": "brain-group-g", "to_id": B, "kind": "groups"})
    assert linked.status == DONE
    relation = next(r for r in (await stack.scene.snapshot()).relations if r.to_id == B)
    duplicate = await run(stack, "l2", DISPLAY, "scene_link", {"from_id": "brain-group-g", "to_id": B, "kind": "groups"})
    assert (duplicate.status, duplicate.code) == (DONE, "unchanged")
    unlinked = await run(stack, "u1", DISPLAY, "scene_unlink", {"relation_id": relation.relation_id})
    assert unlinked.status == DONE and not [r for r in (await stack.scene.snapshot()).relations if r.to_id == B]
    ghost = await run(stack, "u2", DISPLAY, "scene_unlink", {"relation_id": relation.relation_id})
    assert (ghost.status, ghost.code) == (INVALIDATED, "unknown_relation")


async def test_a_fabricated_or_archived_id_is_invalidated_and_the_owner_writes_nothing(stack):
    revision = (await stack.scene.snapshot()).revision
    fake = await run(stack, "f", DISPLAY, "scene_update_object", {"object_id": "brain-note-nope", "visibility": "hidden"})
    assert (fake.status, fake.code) == (INVALIDATED, "unknown_object") and stack.scene.writes == 0
    state = await read_ui_state(stack.scene, stack.boards)
    observed = state.ref()
    stack.queue.add(ActionRecord("late", DISPLAY, "scene_update_object", {"object_id": C, "visibility": "hidden"},
                                 trigger=Trigger.from_payload(None), planned_from=observed,
                                 preconditions=preconditions_from(observed)))
    await stack.scene.service.apply(SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id=C))
    # L'époque est la même, la révision a bougé : l'objet archivé est refusé par le validateur, pas par chance.
    late = await stack.executor.execute("late")
    assert (late.status, late.code) == (INVALIDATED, "object_archived")
    assert (await stack.scene.snapshot()).revision == revision + 1  # seulement l'archivage de l'utilisateur


async def test_irreversible_content_and_read_tools_are_not_executable(stack):
    for tool, arguments in (("scene_archive", {"object_ids": [A]}), ("scene_create_object", {"kind": "window", "category": "x"}),
                            ("scene_add_artifact", {"target_id": A, "category": "x", "title": "t"}),
                            ("scene_inspect", {}), ("scene_get", {"object_ids": [A]})):
        state = await read_ui_state(stack.scene, stack.boards)
        added = stack.queue.add(ActionRecord(f"x-{tool}", DISPLAY, tool, arguments, trigger=Trigger.from_payload(None),
                                             planned_from=state.ref(), preconditions=preconditions_from(state.ref())))
        assert not added.queued and added.code == "unsupported_tool", tool
    assert stack.scene.writes == 0 and (await get(stack, A)) is not None


# ------------------------------------------------------------------ surfaces (07b)


async def _open(stack, url="https://example.com/a", action_id="o1", **extra):
    result = await run(stack, action_id, SURFACE, "surface_open", {"url": url, **extra})
    assert result.status == DONE, result
    return result.detail["surface_id"], result.detail["object_id"]


async def test_open_registers_a_surface_in_the_canonical_state_and_the_provider_offers_it(stack):
    surface_id, object_id = await _open(stack, label="Exemple", note="Des notes")
    assert surface_id == surface_id_of(object_id) and surface_id.startswith("surf_")
    state = await read_ui_state(stack.scene, stack.boards)
    assert [surface.surface_id for surface in state.surfaces] == [surface_id]
    (choice,) = PROVIDERS["surface.browser"].list_choices(state)
    assert (choice.value, choice.label) == (surface_id, "Exemple")
    assert choice.meta["url"] == "https://example.com/a" and choice.meta["pages"] == 1
    assert (await get(stack, object_id)).payload.prefab.prefab_id == "jarvis.browser"  # Core a validé le manifeste livré


async def test_navigation_verbs_change_the_surface_state_through_the_owner(stack):
    surface_id, object_id = await _open(stack)
    steps = [("surface_open", {"surface_id": surface_id, "url": "https://example.com/b"}),
             ("surface_scroll", {"surface_id": surface_id, "direction": "down"}),
             ("surface_zoom", {"surface_id": surface_id, "action": "in"}),
             ("surface_history", {"surface_id": surface_id, "direction": "back"}),
             ("surface_focus", {"surface_id": surface_id})]
    for number, (tool, arguments) in enumerate(steps):
        result = await run(stack, f"n{number}", SURFACE, tool, arguments)
        assert result.status == DONE, (tool, result)
        assert result.detail["surface_id"] == surface_id
    (surface,) = (await read_ui_state(stack.scene, stack.boards)).surfaces
    assert (surface.index, surface.scroll, surface.zoom, len(surface.history)) == (0, 0, 125, 2)
    assert surface.visible and surface.representation is Representation.WINDOW
    again = await run(stack, "n9", SURFACE, "surface_zoom", {"surface_id": surface_id, "action": "reset"})
    assert again.status == DONE and again.code == "applied"
    assert (await run(stack, "n10", SURFACE, "surface_zoom", {"surface_id": surface_id, "action": "reset"})).code == "unchanged"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "file:///c:/windows/win.ini",
                                 "https://user:pw@example.com/", "http://127.0.0.1:8080/", "http://localhost/",
                                 "http://192.168.0.2/", "http://2130706433/", "ftp://example.com/"])
async def test_a_dangerous_address_is_invalidated_before_any_write(stack, url):
    revision = (await stack.scene.snapshot()).revision
    result = await run(stack, "bad", SURFACE, "surface_open", {"url": url})
    assert (result.status, result.code) == (INVALIDATED, "unsafe_url")
    assert stack.scene.writes == 0 and (await stack.scene.snapshot()).revision == revision
    assert not (await read_ui_state(stack.scene, stack.boards)).surfaces


async def test_a_guessed_or_vanished_surface_is_invalidated_and_history_edges_are_typed(stack):
    guessed = await run(stack, "g", SURFACE, "surface_zoom", {"surface_id": "surf_000000000000", "action": "in"})
    assert (guessed.status, guessed.code) == (INVALIDATED, "unknown_surface") and stack.scene.writes == 0
    surface_id, object_id = await _open(stack)
    edge = await run(stack, "e", SURFACE, "surface_history", {"surface_id": surface_id, "direction": "back"})
    assert (edge.status, edge.code) == (INVALIDATED, "no_history")
    state = await read_ui_state(stack.scene, stack.boards)
    stack.queue.add(ActionRecord("late", SURFACE, "surface_focus", {"surface_id": surface_id},
                                 trigger=Trigger.from_payload(None), planned_from=state.ref(),
                                 preconditions=preconditions_from(state.ref())))
    await stack.scene.service.apply(SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id=object_id))
    gone = await stack.executor.execute("late")
    assert (gone.status, gone.code) == (INVALIDATED, "unknown_surface")


async def test_two_surfaces_stay_independent_and_ids_are_never_reused(stack):
    first, first_object = await _open(stack, "https://example.com/1", "o1")
    second, _ = await _open(stack, "https://example.com/2", "o2")
    assert first != second
    await run(stack, "z", SURFACE, "surface_zoom", {"surface_id": second, "action": "out"})
    zooms = {surface.surface_id: surface.zoom for surface in (await read_ui_state(stack.scene, stack.boards)).surfaces}
    assert zooms == {first: 100, second: 75}
    await stack.scene.service.apply(SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id=first_object))
    third, third_object = await _open(stack, "https://example.com/3", "o3")
    assert third not in (first, second) and third_object != first_object


def test_the_executable_set_matches_the_ui_tool_metadata():
    """Chaque adaptateur de S7 a sa `ToolMeta` d'interface (surface, réversibilité, préconditions, fournisseurs)."""

    from jarvis.runtime.mcp_tool_meta import tool_meta

    for server, tool in default_adapters(object(), object()):
        meta = tool_meta(server, tool)
        assert meta.ui_surface in ("scene", "board", "browser") and meta.preconditions is not None, (server, tool)
