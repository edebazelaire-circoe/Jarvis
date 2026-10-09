"""Partition et API d'édition ensemble (jarvis-interactive-presentation-studio, merge des Slices 05 et 10).

Le chemin d'écriture des variantes est unique : l'édition (`write_variant`) et `save_variant` passent par le garde de
`score_id` (`_persist_variant`). Une édition validée sur une variante qui a une partition garde le lien et la révision
de la partition ; une base périmée ne détache ni n'échange jamais la partition.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio import VariantUpdate
from jarvis.domain.presentation_studio_edit import EditStatus
from tests.unit.test_presentation_studio_edit_service import Rig, op_set
from tests.unit.test_presentation_studio_scene_service import SID, SID2, Env


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)


@pytest.fixture
async def rig(env) -> Rig:
    return await Rig(env).open()


ITEM_1, ITEM_2 = "psi_000000000001", "psi_000000000002"


def score_content() -> dict:
    return {
        "start_item_id": ITEM_1,
        "items": [
            {"item_id": ITEM_1, "scene_id": SID, "presenter": "jarvis", "kind": "speech", "text": "Bonjour.",
             "visual": [{"kind": "reveal", "scene_id": SID, "anchor_id": "reveal"}], "next_item_id": ITEM_2},
            {"item_id": ITEM_2, "scene_id": SID2, "presenter": "none", "kind": "silence"}],
        "cues": [], "sequences": [], "recovery_points": []}


async def with_score(rig: Rig):
    variant = await rig.variant()
    answer = await rig.studio.create_score(rig.pid, rig.vid, {"expected_variant_revision": variant.revision,
                                                              **score_content()})
    return answer["score"]["score_id"], answer


def score_file(rig: Rig, score_id: str):
    return rig.env.studio_root / "presentations" / rig.pid / "scores" / f"{score_id}.json"


async def test_an_edit_commit_on_a_variant_with_a_score_keeps_the_link_and_the_score(rig):
    score_id, answer = await with_score(rig)
    variant = await rig.variant()
    assert variant.score_id == score_id
    score_digest = hashlib.sha256(score_file(rig, score_id).read_bytes()).hexdigest()

    result = await rig.run(variant.revision, op_set(SID, "headline", "Apres la partition"))
    assert (result.status, result.committed, result.revision) == (EditStatus.APPLIED, True, variant.revision + 1)

    after = await rig.variant()
    assert after.score_id == score_id and after.revision == variant.revision + 1  # one revision per commit, link intact
    assert json.loads(rig.path.read_text(encoding="utf-8"))["score_id"] == score_id
    assert hashlib.sha256(score_file(rig, score_id).read_bytes()).hexdigest() == score_digest  # the edit never rewrites the score
    got = await rig.studio.get_score(rig.pid, rig.vid)
    assert got["score"] == answer["score"] and got["problems"] == []


async def test_a_preview_on_a_variant_with_a_score_writes_nothing(rig):
    score_id, _ = await with_score(rig)
    variant = await rig.variant()
    variant_digest, score_digest = rig.digest(), hashlib.sha256(score_file(rig, score_id).read_bytes()).hexdigest()
    result = await rig.run(variant.revision, op_set(SID, "headline", "Apercu"), mode="preview")
    assert result.status is EditStatus.APPLIED and result.committed is False
    assert rig.digest() == variant_digest and hashlib.sha256(score_file(rig, score_id).read_bytes()).hexdigest() == score_digest


async def test_an_edit_planned_before_the_score_was_created_is_stale_and_cannot_detach_it(rig):
    stale_revision = (await rig.variant()).revision
    score_id, _ = await with_score(rig)  # bumps the variant revision and sets score_id
    result = await rig.run(stale_revision, op_set(SID, "headline", "Trop tard"))
    assert result.status is EditStatus.STALE and result.committed is False
    after = await rig.variant()
    assert after.score_id == score_id and after.scenes[0].props["label"] != "Trop tard"


async def test_the_edit_write_path_refuses_to_attach_swap_or_clear_a_score_link(rig):
    """`write_variant` is what the edit API ends with: even a current-revision body cannot move `score_id`."""

    variant = await rig.variant()
    update = VariantUpdate(variant.revision, variant.title, variant.scenes, variant.art_direction_id, "psr_0000000000aa")
    before = rig.digest()
    with pytest.raises(PresentationStudioError) as caught:
        await rig.studio.write_variant(rig.pid, rig.vid, update)
    assert caught.value.code is C.INVALID_PRESENTATION and "cannot attach, swap or clear" in caught.value.message
    assert rig.digest() == before and (await rig.variant()).score_id is None

    score_id, _ = await with_score(rig)
    variant = await rig.variant()
    for other in (None, "psr_0000000000bb"):
        update = VariantUpdate(variant.revision, variant.title, variant.scenes, variant.art_direction_id, other)
        with pytest.raises(PresentationStudioError) as caught:
            await rig.studio.write_variant(rig.pid, rig.vid, update)
        assert caught.value.code is C.INVALID_PRESENTATION
    same = VariantUpdate(variant.revision, variant.title, variant.scenes, variant.art_direction_id, score_id)
    saved = await rig.studio.write_variant(rig.pid, rig.vid, same)
    assert saved.score_id == score_id and saved.revision == variant.revision + 1


async def test_a_stale_revision_is_reported_before_the_score_guard(rig):
    score_id, _ = await with_score(rig)
    variant = await rig.variant()
    update = VariantUpdate(variant.revision - 1, variant.title, variant.scenes, variant.art_direction_id, None)
    with pytest.raises(PresentationStudioError) as caught:
        await rig.studio.write_variant(rig.pid, rig.vid, update)
    assert caught.value.code is C.STALE_REVISION  # reload, then retry: the caller learns its basis was old
    assert (await rig.variant()).score_id == score_id


async def test_removing_a_scene_the_score_uses_is_not_blocked_but_the_score_reports_it(rig):
    """Documented seam (Slices 05/08 must surface it): the edit commits, `GET score` lists the dangling references."""

    await with_score(rig)
    variant = await rig.variant()
    result = await rig.run(variant.revision, {"op": "scene.remove", "scene_id": SID2})
    assert result.status is EditStatus.APPLIED and result.committed is True
    got = await rig.studio.get_score(rig.pid, rig.vid)
    assert any(SID2 in problem for problem in got["problems"]) and got["score"]["revision"] == 1
    stale_save = await rig.studio.get_variant(rig.pid, rig.vid)
    assert stale_save.score_id == got["score"]["score_id"]
    with pytest.raises(PresentationStudioError) as caught:  # fixing the score is required before saving it again
        await rig.studio.save_score(rig.pid, rig.vid, {"expected_revision": 1, **score_content()})
    assert caught.value.code is C.SCORE_INCOMPATIBLE
