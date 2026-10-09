"""Variantes locales et lecture (Slices 17 et 12) : l'aperçu sur la fenêtre de scène et le suivi d'un choix par une lecture vivante
(jarvis-interactive-presentation-studio).

Vrai service de lecture (vraie scène, vrai catalogue de prefabs, vrai magasin), vraie API d'édition. Règles : un aperçu n'écrit
rien (hachage de tout l'arbre) et ne montre rien à l'auditoire tant que la lecture joue ; l'état d'aperçu est éphémère et se
termine par annulation, délai, commande, édition validée ou arrêt, en rendant toujours la scène canonique ; choisir une
variante locale de la scène montrée met la fenêtre à jour sans déplacer la position de la partition.
Contrat : `docs/presentation-studio.md` › *Scene-local variant contract*.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.core.presentation_studio_scene_variants import PresentationStudioSceneVariants
from jarvis.core.presentation_studio_variants import PresentationStudioVariants
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import EditStatus
from tests.unit.test_presentation_studio_edit_service import op_set, request
from tests.unit.test_presentation_studio_playback_service import Rig, applied
from tests.unit.test_presentation_studio_score_service import S1, S2
from tests.unit.test_presentation_studio_scene_variants_service import create, select


class Setup:
    def __init__(self, rig: Rig) -> None:
        self.rig = rig
        self.variants = PresentationStudioVariants(rig.studio, diagnostics=rig.env.sink, secret=b"p" * 32,
                                                   epoch=lambda: 1_000_000.0)
        self.variants.bind_playback(rig.service)
        self.sv = PresentationStudioSceneVariants(rig.studio, rig.edit, self.variants, diagnostics=rig.env.sink)
        self.sv.bind_playback(rig.service)

    async def edit(self, *ops):
        revision = (await self.rig.studio.get_variant(self.rig.pid, self.rig.vid)).revision
        result = await self.rig.edit.edit(self.rig.pid, self.rig.vid, request(revision, *ops))
        assert result.status is EditStatus.APPLIED, result.to_dict()
        return result

    async def alternative(self, scene_id, label, headline, count=77):
        """Une variante locale de `scene_id` dont le titre et le compte diffèrent ; la scène reste sur l'originale. Rend son id.
        (Le compte est ce qu'on regarde sur la fenêtre : la partition de la lecture surcharge le titre de la scène.)"""

        made = (await self.edit(create(scene_id, label))).ops[0]["scene_variant_id"]
        scene = next(s for s in (await self.rig.studio.get_variant(self.rig.pid, self.rig.vid)).scenes if s.scene_id == scene_id)
        original = scene.scene_variants.current_id
        await self.edit(select(scene_id, made))
        await self.edit(op_set(scene_id, "headline", headline))
        await self.edit(op_set(scene_id, "count", count))
        await self.edit(select(scene_id, original))
        return made

    async def stage_count(self):
        stage = await self.rig.stage_object()
        return None if stage is None else stage.payload.prefab.data.get("count")


@pytest.fixture
async def world(tmp_path):
    rig = await Rig(tmp_path).open()
    yield Setup(rig)
    await rig.close()


async def paused_on_first_scene(world: Setup):
    applied(await world.rig.service.start(world.rig.start_body()))
    applied(await world.rig.run("pause"))


# ------------------------------------------------------------------ aperçu hors lecture

async def test_a_preview_renders_the_scene_in_memory_and_writes_not_a_byte(world):
    b = await world.alternative(S1, "B", "Dans B")
    before = world.rig.tree_digest()
    answer = await world.sv.preview(world.rig.pid, world.rig.vid, S1, b)
    assert answer["written"] is False and answer["staged"] is False
    assert answer["preview"]["payload"]["prefab"]["props"]["label"] == "Dans B" and answer["preview"]["payload"]["prefab"]["data"]["count"] == 77
    assert answer["preview"]["title"] == "Un" and answer["preview"]["budget"]["remaining"] > 0
    assert world.rig.tree_digest() == before  # not a file, not a byte: nothing was written anywhere
    assert (await world.rig.studio.get_variant(world.rig.pid, world.rig.vid)).scenes[0].props["label"] == "Visiteurs"
    with_stage = await world.sv.preview(world.rig.pid, world.rig.vid, S1, b, {"stage": True})
    assert with_stage["staged"] is False and with_stage["stage_reason"] == "no_run_on_this_variant"
    assert await world.rig.stage_object() is None and world.rig.tree_digest() == before


async def test_a_preview_of_an_unknown_target_or_with_a_bad_body_is_a_typed_refusal(world):
    b = await world.alternative(S1, "B", "Dans B")
    await refused(world.sv.preview(world.rig.pid, world.rig.vid, S1, "psx_ffffffffffff"), C.UNKNOWN_SCENE_VARIANT)
    await refused(world.sv.preview(world.rig.pid, world.rig.vid, S2, b), C.UNKNOWN_SCENE_VARIANT)  # S2 has no set
    await refused(world.sv.preview(world.rig.pid, world.rig.vid, "pss_ffffffffffff", b), C.UNKNOWN_SCENE)
    for body in ({"stage": "yes"}, {"timeout_s": 0}, {"timeout_s": 121}, {"timeout_s": "5"}, {"bogus": 1}, {"actor": "robot"}):
        await refused(world.sv.preview(world.rig.pid, world.rig.vid, S1, b, body), C.INVALID_PRESENTATION)


async def refused(awaitable, code: C) -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        await awaitable
    assert caught.value.code is code, caught.value
    return caught.value


# ------------------------------------------------------------------ état d'aperçu sur la fenêtre de scène

async def test_a_paused_run_shows_the_preview_on_the_stage_and_cancel_gives_the_canonical_scene_back(world):
    b = await world.alternative(S1, "B", "Dans B")
    await paused_on_first_scene(world)
    canonical = await world.stage_count()
    before = world.rig.tree_digest()
    answer = await world.sv.preview(world.rig.pid, world.rig.vid, S1, b, {"stage": True})
    assert answer["staged"] is True and answer["expires_in_s"] == 30 and answer["written"] is False
    assert canonical == 12 and await world.stage_count() == 77
    assert world.rig.service.where()["preview"] == {"scene_id": S1, "scene_variant_id": b}
    cancelled = await world.sv.cancel_preview(world.rig.pid)
    assert cancelled == {"presentation_id": world.rig.pid, "cancelled": True}
    assert await world.stage_count() == canonical and "preview" not in world.rig.service.where()
    assert world.rig.tree_digest() == before  # no file moved through preview and cancel
    assert (await world.sv.cancel_preview(world.rig.pid))["cancelled"] is False  # nothing to cancel is not a fault


async def test_the_preview_reverts_by_itself_after_its_timeout(world):
    b = await world.alternative(S1, "B", "Dans B")
    await paused_on_first_scene(world)
    canonical = await world.stage_count()
    answer = await world.sv.preview(world.rig.pid, world.rig.vid, S1, b, {"stage": True, "timeout_s": 1})
    assert answer["staged"] is True and await world.stage_count() == 77
    await asyncio.sleep(1.4)
    assert await world.stage_count() == canonical and "preview" not in world.rig.service.where()
    ended = [d for k, level, d in world.rig.env.sink.rows if k == "core.presentation_studio.preview_ended"]
    assert ended and ended[-1]["reason"] == "timeout" and ended[-1]["repainted"] is True


async def test_any_playback_command_ends_the_preview_first_even_one_the_machine_refuses(world):
    b = await world.alternative(S1, "B", "Dans B")
    await paused_on_first_scene(world)
    await world.sv.preview(world.rig.pid, world.rig.vid, S1, b, {"stage": True})
    refusal = await world.rig.run("next")  # refused: the run is paused. The preview is over all the same.
    assert refusal.status.value == "refused" and "preview" not in world.rig.service.where()
    assert await world.stage_count() == 12
    await world.sv.preview(world.rig.pid, world.rig.vid, S1, b, {"stage": True})
    applied(await world.rig.run("resume"))  # a resume repaints nothing by itself: the preview must still go
    assert "preview" not in world.rig.service.where() and await world.stage_count() == 12
    applied(await world.rig.run("pause"))
    await world.sv.preview(world.rig.pid, world.rig.vid, S1, b, {"stage": True})
    applied(await world.rig.run("resume"))
    applied(await world.rig.run("next"))
    assert "preview" not in world.rig.service.where() and (await world.rig.stage_object()).payload.title == "Deux"


async def test_stop_clears_the_preview_and_the_stage_is_released(world):
    b = await world.alternative(S1, "B", "Dans B")
    await paused_on_first_scene(world)
    await world.sv.preview(world.rig.pid, world.rig.vid, S1, b, {"stage": True, "timeout_s": 1})
    applied(await world.rig.run("stop"))
    assert await world.rig.stage_object() is None and "preview" not in world.rig.service.where()
    await asyncio.sleep(1.3)  # the pending timer did not resurrect anything nor raise
    assert await world.rig.stage_object() is None


async def test_a_playing_run_is_never_previewed_on_the_stage_and_says_why(world):
    b = await world.alternative(S1, "B", "Dans B")
    applied(await world.rig.service.start(world.rig.start_body()))
    answer = await world.sv.preview(world.rig.pid, world.rig.vid, S1, b, {"stage": True})
    assert answer["staged"] is False and answer["stage_reason"] == "run_not_paused" and answer["written"] is False
    assert answer["preview"]["payload"]["prefab"]["data"]["count"] == 77  # the page still gets the render
    assert await world.stage_count() == 12


async def test_a_committed_edit_ends_the_preview_and_the_stage_follows_the_canonical_variant(world):
    b = await world.alternative(S1, "B", "Dans B")
    await paused_on_first_scene(world)
    await world.sv.preview(world.rig.pid, world.rig.vid, S1, b, {"stage": True})
    await world.edit(op_set(S1, "headline", "Edite pendant l'apercu"))
    assert "preview" not in world.rig.service.where()
    stage = await world.rig.stage_object()
    assert stage.payload.prefab.data["count"] == 12 and stage.payload.prefab.props["label"] == "Un"  # the canonical scene + the score


# ------------------------------------------------------------------ choisir pendant une lecture

async def test_selecting_a_variant_of_the_shown_scene_patches_the_stage_without_moving_the_score_position(world):
    b = await world.alternative(S1, "B", "Dans B")
    applied(await world.rig.service.start(world.rig.start_body()))
    before = world.rig.service.where()
    assert before["position"] == {"index": 1, "of": 4}
    await world.edit(select(S1, b))  # an inspector/voice commit, not the run's own
    after = world.rig.service.where()
    assert after["position"] == before["position"] and after["scene"]["title"] == before["scene"]["title"]
    assert after["phase"] == "paused"  # a foreign commit pauses and follows (Slice 12): the author resumes on purpose
    assert await world.stage_count() == 77  # the window shows the selected variant's content
    assert (await world.rig.stage_object()).object_id == before["stage_object_id"]  # the same window, patched
    original = next(i.variant_id for i in (await world.rig.studio.get_variant(world.rig.pid, world.rig.vid)).scenes[0]
                    .scene_variants.items if i.variant_id != b)
    await world.edit(select(S1, original))
    assert world.rig.service.where()["position"] == before["position"]


async def test_selecting_a_variant_of_another_scene_leaves_the_stage_content_alone(world):
    c = await world.alternative(S2, "C", "Dans C")
    applied(await world.rig.service.start(world.rig.start_body()))
    shown = (await world.rig.stage_object()).payload
    await world.edit(select(S2, c))
    assert (await world.rig.stage_object()).payload == shown and world.rig.service.where()["position"]["index"] == 1
