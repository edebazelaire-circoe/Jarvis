"""Le Tool Brain ne touche jamais aux objets de scène du Presentation Studio (jarvis-interactive-presentation-studio, Slice 21).

Condition d'entrée de la Slice 12 : la fenêtre de scène de la lecture (`studio_stage`) et les fenêtres auxiliaires (`studio_aux`) ont un
propriétaire, la lecture en cours (id par run, tombstone, registre de nettoyage). Un second décideur d'écran (le Tool Brain, sous
`JARVIS_TOOL_BRAIN=active`) qui les déplacerait, les masquerait ou les retirerait casserait cet état. Tout passe par `run_scene_plan`, l'unique
chemin d'écriture du Tool Brain : un seul garde, ces tests le prouvent adaptateur par adaptateur.
"""

from __future__ import annotations

from jarvis.core.presentation_studio_stage import AUX_CATEGORY, STAGE_CATEGORY
from jarvis.domain.scene import (
    SceneActor, SceneCommand, SceneGeometry, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload, Visibility,
)
from jarvis.runtime.tool_brain_executor import STUDIO_OWNED
from jarvis.runtime.tool_brain_queue import DONE, INVALIDATED
from tests.unit.test_tool_brain_adapters import A, DISPLAY, SURFACE, get, run, stack  # noqa: F401 - `stack` is a fixture

STAGE, AUX = "studio-stage-r1", "studio-aux-r1-1"


async def put_studio_objects(rig) -> None:
    for object_id, category in ((STAGE, STAGE_CATEGORY), (AUX, AUX_CATEGORY)):
        result = await rig.scene.service.apply(SceneCommand(
            op=SceneOp.UPSERT_OBJECT, actor=SceneActor.USER, object_id=object_id,
            fields=SceneObjectFields(kind=SceneObjectKind.ARTIFACT, category=category, payload=ScenePayload(title=object_id),
                                     geometry=SceneGeometry(0, 0, 40, 30))))
        assert result.outcome.value == "applied", result


async def test_no_tool_brain_mutator_can_touch_the_stage_or_an_auxiliary_window(stack):
    await put_studio_objects(stack)
    before = {oid: await get(stack, oid) for oid in (STAGE, AUX)}
    attempts = [
        ("scene_update_object", {"object_id": STAGE, "visibility": "hidden"}),
        ("scene_update_object", {"object_id": AUX, "geometry": {"x": 1, "y": 1, "w": 5, "h": 5}}),
        ("scene_update_many", {"object_ids": [A, STAGE], "visibility": "hidden"}),
        ("scene_pin", {"object_ids": [AUX], "pinned": True}),
        ("scene_move", {"object_ids": [STAGE], "dx": 3, "dy": 3}),
        ("scene_link", {"from_id": A, "to_id": STAGE, "kind": "explains"}),
    ]
    for number, (tool, arguments) in enumerate(attempts):
        outcome = await run(stack, f"o{number}", DISPLAY, tool, arguments)
        assert outcome.status == INVALIDATED and outcome.code == STUDIO_OWNED, (tool, outcome)
    assert {oid: await get(stack, oid) for oid in (STAGE, AUX)} == before, "nothing was written to a Studio object"
    assert (await get(stack, A)).visibility is Visibility.VISIBLE, "an all-or-nothing batch left the ordinary object alone too"


async def test_a_filter_selection_that_would_reach_a_studio_object_is_refused(stack):
    await put_studio_objects(stack)
    before = await get(stack, STAGE)
    outcome = await run(stack, "f", DISPLAY, "scene_pin", {"select": {"category": STAGE_CATEGORY}, "pinned": True})
    assert (outcome.status, outcome.code) == (INVALIDATED, STUDIO_OWNED)
    assert await get(stack, STAGE) == before


async def test_a_studio_category_cannot_be_imposed_on_an_ordinary_object(stack):
    outcome = await run(stack, "c", DISPLAY, "scene_update_object", {"object_id": A, "category": STAGE_CATEGORY})
    assert (outcome.status, outcome.code) == (INVALIDATED, STUDIO_OWNED)
    assert (await get(stack, A)).category == "note"


async def test_ordinary_objects_are_still_executable_so_the_guard_is_not_a_blanket_refusal(stack):
    await put_studio_objects(stack)
    hidden = await run(stack, "ok", DISPLAY, "scene_update_object", {"object_id": A, "visibility": "hidden"})
    assert hidden.status == DONE and (await get(stack, A)).visibility is Visibility.HIDDEN
    assert SURFACE == "jarvis-surface"
