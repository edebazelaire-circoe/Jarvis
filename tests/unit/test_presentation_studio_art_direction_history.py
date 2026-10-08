"""Undo / redo et liens de la variante (jarvis-interactive-presentation-studio, Slices 08 + 09 + 10).

Un annuler est une édition : il écrit par le service d'édition -> `write_variant` -> `_persist_variant`, l'unique garde des
liens `score_id` et `art_direction_id`. Une variante qui porte une partition **et** une direction artistique les garde
toutes les deux à travers édition, annuler et rétablir ; aucune écriture de variante ne contourne la garde.
"""

from __future__ import annotations

import pytest

from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_history import HistoryStatus
from tests.fakes import presentation_studio_art_direction as fx
from tests.unit.test_presentation_studio_edit_service import Env, op_set
from tests.unit.test_presentation_studio_history_service import HRig
from tests.unit.test_presentation_studio_scene_service import SID, SID2


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)


@pytest.fixture
async def rig(env) -> HRig:
    return await HRig(env).open()


async def link_both(rig: HRig) -> tuple[str, str]:
    score = await rig.studio.create_score(rig.pid, rig.vid, {
        "expected_variant_revision": (await rig.variant()).revision, "start_item_id": "psi_000000000001",
        "items": [{"item_id": "psi_000000000001", "scene_id": SID, "presenter": "none", "kind": "silence"}],
        "cues": [], "sequences": [], "recovery_points": []})
    art = await rig.studio.create_art_direction(rig.pid, rig.vid, {
        "expected_variant_revision": (await rig.variant()).revision, "profile": fx.base_dict()})
    variant = await rig.variant()
    assert (variant.score_id, variant.art_direction_id) == (score["score"]["score_id"], art["art_direction"]["art_direction_id"])
    return variant.score_id, variant.art_direction_id


async def test_undo_and_redo_keep_both_the_score_and_the_art_direction_link(rig):
    score_id, art_id = await link_both(rig)
    await rig.commit(op_set(SID2, "headline", "Bonjour"))
    after_edit = await rig.variant()
    assert (after_edit.score_id, after_edit.art_direction_id) == (score_id, art_id)
    undone = await rig.undo()
    assert undone.status is HistoryStatus.APPLIED
    after_undo = await rig.variant()
    assert (after_undo.score_id, after_undo.art_direction_id) == (score_id, art_id)
    redone = await rig.redo()
    assert redone.status is HistoryStatus.APPLIED
    after_redo = await rig.variant()
    assert (after_redo.score_id, after_redo.art_direction_id) == (score_id, art_id)
    assert after_redo.revision == after_edit.revision + 2
    stored = rig.path.read_text(encoding="utf-8")  # and the file on disk says so too
    assert score_id in stored and art_id in stored


async def test_the_links_survive_a_restart_and_a_post_restart_edit(rig):
    score_id, art_id = await link_both(rig)
    await rig.commit(op_set(SID2, "headline", "Avant"))
    rig.restart()
    await rig.commit(op_set(SID2, "headline", "Apres"))
    variant = await rig.variant()
    assert (variant.score_id, variant.art_direction_id) == (score_id, art_id)
    assert (await rig.studio.get_art_direction(rig.pid, rig.vid))["art_direction"]["art_direction_id"] == art_id


async def test_saving_an_art_direction_neither_enters_the_undo_ring_nor_moves_the_variant_revision(rig):
    await link_both(rig)
    await rig.commit(op_set(SID2, "headline", "Un"))
    before = await rig.variant()
    saved = await rig.studio.save_art_direction(rig.pid, rig.vid, {
        "expected_revision": 1, "profile": fx.set_path(fx.base_dict(), "shapes.radius_px", 24)})
    assert saved["art_direction"]["revision"] == 2
    after = await rig.variant()
    assert (after.revision, after.updated_at) == (before.revision, before.updated_at)  # readers compare the DA's own revision
    undone = await rig.undo()
    assert undone.status is HistoryStatus.APPLIED
    assert (await rig.studio.get_art_direction(rig.pid, rig.vid))["art_direction"]["profile"]["shapes"]["radius_px"] == 24


async def test_no_variant_writer_can_change_a_link_outside_its_own_routes(rig):
    """Every writer ends in `_persist_variant`: the edit service's `write_variant` cannot attach, swap or clear a link."""

    from jarvis.domain.presentation_studio import VariantUpdate

    score_id, art_id = await link_both(rig)
    variant = await rig.variant()
    for field, value in (("art_direction_id", None), ("art_direction_id", "psd_0000000000ee"), ("score_id", None),
                         ("score_id", "psr_0000000000ee")):
        values = {"art_direction_id": variant.art_direction_id, "score_id": variant.score_id, field: value}
        update = VariantUpdate(variant.revision, variant.title, variant.scenes, values["art_direction_id"], values["score_id"])
        with pytest.raises(PresentationStudioError) as caught:
            await rig.studio.write_variant(rig.pid, rig.vid, update)
        assert caught.value.code is C.INVALID_PRESENTATION and "cannot attach, swap or clear" in caught.value.message
    after = await rig.variant()
    assert (after.score_id, after.art_direction_id, after.revision) == (score_id, art_id, variant.revision)
