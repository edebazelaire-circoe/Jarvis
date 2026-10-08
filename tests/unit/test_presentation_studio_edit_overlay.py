"""`render_overlay` and the commit listener of the edit service (Slice 12), the two seams playback uses.

`render_overlay` is a preview that hands back the **scenes**: same engine, same checks, nothing written, nothing recorded.
The listener is how the visible stage follows a committed edit. Contract: `docs/presentation-studio.md` > *Playback runtime
contract* (values overlay) and *Semantic edit contract* (Extension points).
"""

from __future__ import annotations

import pytest

from jarvis.domain.presentation_studio import PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import EditStatus, StudioActor
from tests.unit.test_presentation_studio_edit_service import Env, Rig, op_set, request
from tests.unit.test_presentation_studio_scene_service import SID, SID2


@pytest.fixture
async def rig(tmp_path) -> Rig:
    return await Rig(Env(tmp_path)).open()


def ops(*pairs):
    return [op_set(scene, control, value) for scene, control, value in pairs]


async def test_the_overlay_is_what_a_preview_would_compute_and_it_writes_nothing(rig):
    variant = await rig.variant()
    digest = rig.digest()
    wanted = ops((SID, "headline", "Apercu"), (SID2, "start_count", 7))
    render = await rig.edit.render_overlay(rig.pid, rig.vid, variant.revision, wanted)
    assert render.status is EditStatus.APPLIED and render.code is None
    assert render.scenes[0].props["label"] == "Apercu" and render.scenes[1].data["count"] == 7
    assert rig.digest() == digest and (await rig.variant()).revision == variant.revision, "not a byte, not a revision"
    assert rig.emitter.recorded == [] and rig.edit.pending_source_requests() == ()
    assert not rig.sink.of("core.presentation_studio.edit_committed") and not rig.sink.of("core.presentation_studio.edit_previewed")
    [(level, data)] = rig.sink.of("core.presentation_studio.overlay_rendered")
    assert data["written"] is False and data["ops"] == 2 and "Apercu" not in str(data)
    preview = await rig.run(variant.revision, *wanted, mode="preview")
    assert preview.status is EditStatus.APPLIED
    assert (render.scenes[0].props["label"], render.scenes[1].data["count"]) == (preview.ops[0]["after"], preview.ops[1]["after"])


async def test_more_operations_than_one_request_holds_are_chained_not_refused(rig):
    variant = await rig.variant()
    many = ops(*[(SID, "start_count", n) for n in range(1, 41)])          # 40 ops: 3 chunks, the last one wins
    render = await rig.edit.render_overlay(rig.pid, rig.vid, variant.revision, many)
    assert render.status is EditStatus.APPLIED and render.scenes[0].data["count"] == 40


async def test_a_value_the_control_refuses_is_refused_with_the_index_of_the_whole_list(rig):
    variant = await rig.variant()
    many = ops(*[(SID, "start_count", 5)] * 20, (SID, "start_count", 999))     # the 21st, in the second chunk
    render = await rig.edit.render_overlay(rig.pid, rig.vid, variant.revision, many)
    assert render.status is EditStatus.REFUSED and render.code == C.VALUE_REFUSED.value and render.failed_index == 20


async def test_a_moved_base_is_stale_and_an_unknown_scene_or_control_is_refused(rig):
    variant = await rig.variant()
    stale = await rig.edit.render_overlay(rig.pid, rig.vid, variant.revision + 3, ops((SID, "headline", "x")))
    assert stale.status is EditStatus.STALE and stale.code == C.STALE_REVISION.value
    unknown = await rig.edit.render_overlay(rig.pid, rig.vid, variant.revision, ops((SID, "nope", 1)))
    assert unknown.status is EditStatus.REFUSED and unknown.code == C.UNKNOWN_CONTROL.value
    scene = await rig.edit.render_overlay(rig.pid, rig.vid, variant.revision, ops(("pss_00000000ffff", "headline", "x")))
    assert scene.status is EditStatus.REFUSED and scene.code == C.UNKNOWN_SCENE.value


async def test_an_overlay_never_records_a_source_request(rig):
    variant = await rig.variant()
    source = [{"op": "scene.source_request", "scene_id": SID, "intent": "glow"}]
    render = await rig.edit.render_overlay(rig.pid, rig.vid, variant.revision, source, actor=StudioActor.BRAIN)
    assert render.status is EditStatus.APPLIED
    assert rig.edit.pending_source_requests() == (), "a request is recorded by a commit, never by a playback overlay"


# ------------------------------------------------------------------ commit listener

async def test_a_listener_is_awaited_after_a_commit_that_changed_the_scenes_and_only_then(rig):
    seen = []

    async def listener(presentation_id, variant_id, revision, origin):
        seen.append((presentation_id, variant_id, revision))
        assert origin is None                                    # no token given: any other commit is anonymous

    rig.edit.add_commit_listener(listener)
    start = await rig.variant()
    preview = await rig.run(start.revision, op_set(SID, "headline", "P"), mode="preview")
    noop = await rig.run(start.revision, op_set(SID, "headline", "Visiteurs"))
    assert preview.committed is False and noop.changed is False and seen == []
    done = await rig.run(start.revision, op_set(SID, "headline", "Vrai"))
    assert done.committed and seen == [(rig.pid, rig.vid, start.revision + 1)]
    stale = await rig.run(start.revision, op_set(SID, "headline", "Perime"))
    assert stale.status is EditStatus.STALE and len(seen) == 1


async def test_a_failing_listener_is_traced_and_never_undoes_the_committed_edit(rig):
    async def broken(presentation_id, variant_id, revision, origin):
        raise RuntimeError("the stage is gone")

    rig.edit.add_commit_listener(broken)
    start = await rig.variant()
    result = await rig.run(start.revision, op_set(SID, "headline", "Garde"))
    assert result.committed and (await rig.variant()).scenes[0].props["label"] == "Garde"
    [(level, data)] = rig.sink.of("core.presentation_studio.commit_listener_failed")
    assert level == "warning" and data["error_class"] == "RuntimeError" and "gone" not in str(data)


async def test_the_origin_token_of_one_edit_reaches_the_listeners_of_that_commit_only(rig):
    """P5: a run recognises ITS edit by identity of a token, never by a service-wide flag."""

    seen = []

    async def listener(presentation_id, variant_id, revision, origin):
        seen.append(origin)

    rig.edit.add_commit_listener(listener)
    token = object()
    start = await rig.variant()
    body = {"actor": "user", "mode": "commit", "basis": {"variant_revision": start.revision},
            "ops": [op_set(SID, "headline", "Mien")]}
    await rig.edit.edit(rig.pid, rig.vid, body, origin=token)
    second = await rig.variant()
    await rig.run(second.revision, op_set(SID, "headline", "Autre"))      # a foreign commit right after
    assert seen[0] is token and seen[1] is None
    from jarvis.domain.presentation_studio import PresentationStudioError
    with pytest.raises(PresentationStudioError):                          # an origin can never travel in a request body
        await rig.edit.edit(rig.pid, rig.vid, {**body, "origin": "x"})
