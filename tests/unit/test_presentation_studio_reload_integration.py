"""Le rechargement a chaud integre aux Slices 08, 12 et 16 (jarvis-interactive-presentation-studio, merge de la Slice 06).

Tout est reel sauf le navigateur (`FakeHost`) : magasin de fichiers, prefabs, scene SQLite, registre des pins, historique
d'annulation (08), **vraie lecture** (12) qui possede la fenetre `studio-stage-<run_id>`, graphe des variantes (16).
Prouve : le rechargement de la scene qu'un run affiche patche la fenetre de CE run sans le mettre en pause ni le deplacer ; une
scene non affichee est seulement re-epinglee ; le verrou de scene couvre annuler/retablir et les branches ; une branche n'herite
jamais d'un pin non verifie ; archiver la variante jouee reste refuse.
Contrat : `docs/presentation-studio.md` > *Hot reload contract* > *Playback and a reload of the shown scene*.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.domain.prefab import PrefabRef
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_reload import ReloadStatus as S
from tests.fakes.presentation_studio_reload import GOOD_STYLE, SID, SID2, Rig

pytestmark = pytest.mark.asyncio

OLD = PrefabRef("lab.counter", 1)


@pytest.fixture
async def rig(tmp_path):
    opened = await Rig(tmp_path).open()
    yield opened
    await opened.close()


def scene_of(variant, scene_id=SID):
    return next(item for item in variant.scenes if item.scene_id == scene_id)


def silent(pin):
    return None if pin.prefab_id.startswith("presentation-studio.") else {"outcome": "mounted"}


async def refused(awaitable, code: C):
    with pytest.raises(PresentationStudioError) as caught:
        await awaitable
    assert caught.value.code is code, caught.value
    return caught.value


async def control_set(rig: Rig, scene_id: str, control_id: str, value):
    variant = await rig.variant()
    return await rig.edits.edit(rig.pid, rig.vid, {"actor": "user", "mode": "commit", "basis": {"variant_revision": variant.revision},
                                                   "ops": [{"op": "control.set", "scene_id": scene_id, "control_id": control_id,
                                                            "value": value}]})


# ------------------------------------------------------------------ la lecture possede la fenetre

async def test_a_reload_of_the_scene_a_run_shows_patches_that_runs_window_and_the_run_goes_on(rig):
    window = rig.stage_object_id()
    assert window.startswith("studio-stage-") and len(window) == len("studio-stage-") + 12          # `studio-stage-<run_id>`
    binding = rig.stage.binding_for(rig.pid, rig.vid, SID)
    assert binding is not None and binding.object_id == window                                    # the playback told the reload
    before = rig.playback.position(rig.pid)
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.status is S.RELOADED and result.mounted is True
    assert rig.stage_object_id() == window                                                        # the SAME window, never a new one
    block = await rig.stage_block()
    assert block.prefab_id.startswith("presentation-studio.") and block.version == 1
    assert [r["object_id"] for r in rig.host.reports if r["prefab"]["id"] == block.prefab_id] == [window]   # the report named it
    after = rig.playback.position(rig.pid)
    assert after == before and after["state"] == "playing" and after["position"] == 0             # not paused, not moved
    assert result.preserved["playback"] == before and result.preserved["playback_unchanged"] is True
    # the run re-read the variant (the pin moved) on the same item: its plan is current, nothing was written by it
    assert rig.playback._plan.variant_revision == (await rig.variant()).revision
    stage_objects = [o for o in (await rig.scene.snapshot()).objects if o.object_id.startswith("studio-stage-")]
    assert [o.object_id for o in stage_objects] == [window]


async def test_a_reload_does_not_pause_the_run_even_though_it_is_announced_like_a_commit(rig):
    seen: list[object] = []

    async def spy(presentation_id, variant_id, revision, origin=None):
        seen.append(origin)

    rig.edits.add_commit_listener(spy)
    assert (await rig.edit({"style": GOOD_STYLE})).status is S.RELOADED
    kinds = [getattr(o, "step", None) for o in seen]
    assert kinds == ["pin", "confirm"] and all(type(o).__name__ == "ReloadOrigin" for o in seen)
    assert rig.playback.state.phase.value == "playing"                                              # a foreign edit would pause it
    assert not rig.sink.of("core.presentation_studio.reload_announce_failed")


async def test_a_bad_source_in_the_shown_scene_puts_that_runs_window_back_and_keeps_the_position(tmp_path):
    def failing(pin):
        return {"outcome": "failed", "reason": "frame", "message": "SyntaxError"} if pin.prefab_id.startswith("presentation-studio.") \
            else {"outcome": "mounted"}

    rig = await Rig(tmp_path).open(host=failing)
    try:
        window, before = rig.stage_object_id(), rig.playback.position(rig.pid)
        result = await rig.edit({"behavior": "function ( {"})
        assert result.status is S.ROLLED_BACK and result.mounted is False
        assert rig.stage_object_id() == window
        assert (await rig.stage_block()).prefab_id == "lab.counter"
        assert rig.playback.position(rig.pid) == before
        assert scene_of(await rig.variant()).prefab == OLD
    finally:
        await rig.close()


async def test_a_scene_no_run_shows_is_only_repinned_and_the_run_mounts_it_when_it_gets_there(tmp_path):
    rig = await Rig(tmp_path).open()
    try:
        window = rig.stage_object_id()
        shown_before = await rig.stage_block()
        result = await rig.edit({"style": GOOD_STYLE}, scene_id=SID2)
        assert result.status is S.REPINNED and result.mounted is None                              # not on the stage: re-pin only
        assert await rig.stage_block() == shown_before and rig.stage.binding_for(rig.pid, rig.vid, SID2) is None
        assert scene_of(await rig.variant(), SID2).last_valid_pin == OLD                          # waits to be seen mounted
        assert [p.scene_id for p in rig.reload.pending_scenes()] == [SID2]
        moved = await rig.playback.next({"actor": "user"})                                          # the run gets to that scene
        assert moved.status.value == "applied"
        await asyncio.sleep(0.4)                                                                    # the host mounts and reports
        assert rig.stage_object_id() == window
        assert (await rig.stage_block()).prefab_id.startswith("presentation-studio.")             # the new source is on the window
        confirmed = scene_of(await rig.variant(), SID2)
        assert confirmed.last_valid_pin is None and not rig.reload.pending_scenes()               # the report of the run confirmed it
        assert rig.stage.binding_for(rig.pid, rig.vid, SID2).object_id == window                  # and the reload can now patch it
    finally:
        await rig.close()


async def test_a_failed_first_mount_of_a_repinned_scene_goes_back_on_the_runs_window(tmp_path):
    def failing(pin):
        return {"outcome": "failed", "reason": "frame", "message": "boom"} if pin.prefab_id.startswith("presentation-studio.") \
            else {"outcome": "mounted"}

    rig = await Rig(tmp_path).open(host=failing)
    try:
        assert (await rig.edit({"style": GOOD_STYLE}, scene_id=SID2)).status is S.REPINNED
        await rig.playback.next({"actor": "user"})
        await asyncio.sleep(0.5)
        back = scene_of(await rig.variant(), SID2)
        assert back.prefab == OLD and back.last_valid_pin is None and not rig.reload.pending_scenes()
        assert (await rig.stage_block()).prefab_id == "lab.counter"                              # the run's window went back too
    finally:
        await rig.close()


async def test_when_the_run_ends_the_binding_is_gone_and_a_reload_only_repins(rig):
    assert rig.stage.binding_for(rig.pid, rig.vid, SID) is not None
    stopped = await rig.playback.stop({"actor": "user"})
    assert stopped.status.value == "applied" and rig.playback.position(rig.pid) is None
    assert rig.stage.binding_for(rig.pid, rig.vid, SID) is None and not rig.stage.bindings()
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.status is S.REPINNED and result.preserved["playback"] is None


async def test_a_window_the_user_closed_is_reopened_by_the_run_and_the_reload_follows_the_new_id(rig):
    from jarvis.domain.scene import SceneActor, SceneCommand, SceneOp
    first = rig.stage_object_id()
    await rig.scene.apply(SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id=first))
    # the reload now finds no window showing the scene: it only re-pins (the next show of the run decides)
    gone = await rig.edit({"style": "p{color:red}"})
    assert gone.status is S.REPINNED
    await rig.playback.next({"actor": "user"})
    await rig.playback.previous({"actor": "user"})                                                 # the run re-shows scene 1
    second = rig.stage_object_id()
    assert second != first and second.startswith("studio-stage-")
    assert rig.stage.binding_for(rig.pid, rig.vid, SID).object_id == second                       # rebound to the reopened window


# ------------------------------------------------------------------ le verrou de scene : annuler / retablir

async def test_undo_of_a_scene_being_reloaded_is_refused_typed_and_the_history_ticket_is_released(tmp_path):
    rig = await Rig(tmp_path, mount_deadline_s=10).open(host=silent)
    try:
        assert (await control_set(rig, SID, "headline", "Titre")).committed
        gate, entered = asyncio.Event(), asyncio.Event()
        real = rig.studio.check_scenes

        async def slow(*args, **kwargs):
            if not entered.is_set():                                                                # only the reload's own check waits
                entered.set()
                await gate.wait()
            return await real(*args, **kwargs)

        rig.studio.check_scenes = slow                                                              # type: ignore[method-assign]
        task = asyncio.ensure_future(rig.edit({"style": GOOD_STYLE}))
        await asyncio.wait_for(entered.wait(), 5)                                                   # published, pin not yet written
        assert rig.reload.is_reloading(rig.pid, rig.vid, SID)
        document = (await rig.variant()).revision
        error = await refused(rig.history.undo(rig.pid, rig.vid, {"actor": "user"}), C.SCENE_RELOADING)
        assert error.code is C.SCENE_RELOADING
        assert (await rig.variant()).revision == document and not rig.history._book.in_flight((rig.pid, rig.vid))
        gate.set()
        rig.studio.check_scenes = real                                                               # type: ignore[method-assign]
        await asyncio.sleep(0.2)
        await rig.reload.handle_mount_report({"object_id": rig.stage_object_id(), "prefab": scene_of(await rig.variant()).prefab.to_dict(),
                                              "outcome": "mounted"})
        assert (await task).status is S.RELOADED
    finally:
        await rig.close()


async def test_undo_after_a_reload_is_stale_and_never_replays_over_the_new_source(rig):
    assert (await control_set(rig, SID, "headline", "Titre")).committed
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.status is S.RELOADED
    pin = scene_of(await rig.variant()).prefab
    answer = await rig.history.undo(rig.pid, rig.vid, {"actor": "user"})
    assert answer.status.value == "stale" and answer.to_dict()["reason"] == "document_moved_on"
    assert scene_of(await rig.variant()).prefab == pin and scene_of(await rig.variant()).props["label"] == "Titre"


# ------------------------------------------------------------------ le verrou de scene : branches (Slice 16)

async def test_a_branch_is_refused_while_a_scene_of_the_source_is_being_reloaded(tmp_path):
    rig = await Rig(tmp_path, mount_deadline_s=10).open(host=silent)
    try:
        gate, entered = asyncio.Event(), asyncio.Event()
        real = rig.studio.check_scenes

        async def slow(*args, **kwargs):
            if not entered.is_set():                                                                # only the reload's own check waits
                entered.set()
                await gate.wait()
            return await real(*args, **kwargs)

        rig.studio.check_scenes = slow                                                              # type: ignore[method-assign]
        task = asyncio.ensure_future(rig.edit({"style": GOOD_STYLE}))
        await asyncio.wait_for(entered.wait(), 5)
        files_before = sorted(p.name for p in (rig.tmp / "studio" / "presentations" / rig.pid / "variants").iterdir())
        await refused(rig.variants.create_branch(rig.pid, {"title": "Essai"}), C.SCENE_RELOADING)
        assert sorted(p.name for p in (rig.tmp / "studio" / "presentations" / rig.pid / "variants").iterdir()) == files_before
        gate.set()
        rig.studio.check_scenes = real                                                               # type: ignore[method-assign]
        await asyncio.sleep(0.2)
        await rig.reload.handle_mount_report({"object_id": rig.stage_object_id(), "prefab": scene_of(await rig.variant()).prefab.to_dict(),
                                              "outcome": "mounted"})
        assert (await task).status is S.RELOADED
        answer = await rig.variants.create_branch(rig.pid, {"title": "Apres"})                        # over: the same branch works
        assert answer["node"]["variant_number"] == 2
    finally:
        await rig.close()


async def test_a_branch_never_inherits_a_pin_that_was_not_seen_mounted(tmp_path):
    rig = await Rig(tmp_path).open(host=False)
    try:
        result = await rig.edit({"style": GOOD_STYLE}, scene_id=SID2)                               # not shown: unconfirmed
        assert result.status is S.REPINNED
        source = scene_of(await rig.variant(), SID2)
        assert source.prefab.prefab_id.startswith("presentation-studio.") and source.last_valid_pin == OLD
        answer = await rig.variants.create_branch(rig.pid, {"title": "Prudente"})
        branch = scene_of(await rig.studio.get_variant(rig.pid, answer["node"]["variant_id"]), SID2)
        assert branch.prefab == OLD and branch.last_valid_pin is None                              # the LAST VALID pin, no repair data
        assert scene_of(await rig.variant(), SID2) == source                                        # the source is untouched
    finally:
        await rig.close()


async def test_a_branch_whose_values_do_not_fit_the_last_valid_pin_is_refused_instead_of_copying_an_unverified_pin(tmp_path):
    rig = await Rig(tmp_path).open(host=False)
    try:
        assert (await rig.edit({"style": GOOD_STYLE}, scene_id=SID2)).status is S.REPINNED
        variant = await rig.variant()
        from dataclasses import replace
        broken = replace(scene_of(variant, SID2), props={**scene_of(variant, SID2).props, "mode": "weird"})   # fits no version
        await rig.studio.replace_scene_source(rig.pid, rig.vid, expected_revision=variant.revision, scene=broken)
        await refused(rig.variants.create_branch(rig.pid, {"title": "Refusee"}), C.SCENE_RELOADING)
    finally:
        await rig.close()


async def test_archiving_the_variant_a_run_is_playing_is_still_refused_after_a_reload(rig):
    assert (await rig.edit({"style": GOOD_STYLE})).status is S.RELOADED
    other = await rig.variants.create_branch(rig.pid, {"title": "Autre", "activate": True})        # the played variant is no longer active
    await refused(rig.variants.plan_archive(rig.pid, rig.vid, None), C.VARIANT_IN_PLAYBACK)         # refused at the plan, before any token
    assert other["activated"] is True and scene_of(await rig.variant()).prefab.prefab_id.startswith("presentation-studio.")


# ------------------------------------------------------------------ StageWindows : le seul geste du rechargement sur la fenetre

async def test_repin_is_idempotent_when_the_runs_window_already_shows_the_target_and_refuses_a_stranger(rig):
    from jarvis.core.presentation_studio_reload_stage import StagePatchError
    binding = rig.stage.binding_for(rig.pid, rig.vid, SID)
    block = await rig.stage_block()
    now = PrefabRef(block.prefab_id, block.version)
    await rig.stage.repin(binding, expect=OLD, to=now, props=dict(block.props), data=dict(block.data))   # already there: no write
    revision = (await rig.scene.snapshot()).revision
    await rig.stage.repin(binding, expect=OLD, to=now, props=dict(block.props), data=dict(block.data))
    assert (await rig.scene.snapshot()).revision == revision
    with pytest.raises(StagePatchError) as caught:                                                     # a window on another pin: never overwritten
        await rig.stage.repin(binding, expect=PrefabRef("jarvis.counter", 1), to=PrefabRef("jarvis.counter", 1), props={}, data={})
    assert caught.value.code == "stage_changed"


async def test_locate_needs_a_live_window_that_shows_the_pin_a_binding_alone_is_not_enough(rig):
    from jarvis.core.presentation_studio_reload_stage import StageBinding
    assert await rig.stage.locate(rig.pid, rig.vid, SID, OLD) is not None
    assert await rig.stage.locate(rig.pid, rig.vid, SID, PrefabRef("lab.counter", 9)) is None          # shows another pin
    rig.stage.bind(StageBinding(rig.pid, rig.vid, SID, "studio-stage-gone", "r0"))
    assert await rig.stage.locate(rig.pid, rig.vid, SID, OLD) is None                                  # the window no longer exists
    rig.stage.unbind(rig.pid)
    assert rig.stage.bindings() == ()


# ------------------------------------------------------------------ le presentateur Jarvis (Slice 14)

async def test_a_reload_is_never_read_as_a_user_interruption_by_the_jarvis_presenter(tmp_path):
    from jarvis.core.presentation_studio_events import StudioPresenterEvents
    from jarvis.core.presentation_studio_presenter import PresentationStudioPresenter
    from jarvis.domain.conversation_events import ConversationEventType as T
    from tests.fakes.presentation_studio_presenter import FakeBrain
    from tests.fakes.presentation_studio_reload import I1, I2

    rig = await Rig(tmp_path).open(show=False)
    try:
        brain = FakeBrain()
        presenter = PresentationStudioPresenter(rig.playback, brain, events=StudioPresenterEvents(rig.emitter, lambda: "conv-1"),
                                                diagnostics=rig.sink, run_loop=False)
        brain.presenter = presenter
        content = {"start_item_id": I1, "items": [
            {"item_id": I1, "scene_id": SID, "presenter": "jarvis", "kind": "speech", "text": "Bonjour a tous.", "label": "Un",
             "next_item_id": I2},
            {"item_id": I2, "scene_id": SID2, "presenter": "user", "kind": "speech", "note": "Deux"}],
            "cues": [], "sequences": [], "recovery_points": []}
        await rig.play(role="jarvis_presenter", content=content)
        await presenter.pump()
        assert brain.texts == ["Bonjour a tous."] and presenter.view()["line"] == "pending"
        before = rig.playback.position(rig.pid)
        result = await rig.edit({"style": GOOD_STYLE})                                              # a reload commit, ReloadOrigin
        assert result.status is S.RELOADED
        await presenter.pump()
        view = presenter.view()
        assert view["interrupted"] is False and view["problem"] is None                             # not a user turn, not a pause
        assert rig.playback.position(rig.pid) == before and rig.playback.state.phase.value == "playing"
        assert brain.texts == ["Bonjour a tous."]                                                  # the line was not said again or dropped
        assert not [a for t, _, a in rig.emitter.recorded if t is T.SYSTEM_PRESENTATION_STUDIO_PRESENTER_CHANGED]
        await presenter.close()
    finally:
        await rig.close()
