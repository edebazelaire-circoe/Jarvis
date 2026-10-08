"""Rechargement a chaud d'une scene contre de VRAIS services (jarvis-interactive-presentation-studio, Slice 06).

Magasin de fichiers, `PrefabService`, `SceneService` (SQLite), registre des pins, coalesceur et stage sont reels sous
`tmp_path` ; seul le navigateur est simule (`FakeHost` rapporte les montages). Prouve : une bonne edition ne recharge que la
scene visee, une mauvaise est refusee avant toute publication ou revenue en arriere sans abimer la derniere scene valide,
la continuite des valeurs studio, les pannes injectees a chaque etape, la concurrence. Contrat :
`docs/presentation-studio.md` > *Hot reload contract*.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from jarvis.core.presentation_studio_stage import StagePatchError
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.prefab import PrefabRef
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_checks import HTTP_STATUS
from jarvis.domain.presentation_studio_reload import ReloadStatus as S
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from tests.fakes.presentation_studio_reload import GOOD_STYLE, SID, SID2, Rig, counter_behavior, scene_body

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def rig(tmp_path):
    opened = await Rig(tmp_path).open()
    yield opened
    await opened.close()


def digest(rig: Rig) -> str:
    return hashlib.sha256(rig.variant_file().read_bytes()).hexdigest()


def scene_of(variant, scene_id=SID):
    return next(item for item in variant.scenes if item.scene_id == scene_id)


def shrunk_manifest(rig: Rig) -> dict:
    """`count` becomes optional with a small ceiling: the stored 12 and the control's 0..100 bounds no longer fit."""

    manifest = json.loads((rig.data / "prefabs" / "lab.counter" / "1" / "manifest.json").read_text(encoding="utf-8"))
    manifest["inputs"]["props"]["properties"]["mode"].update(values=["compact"], default="compact")
    count = manifest["inputs"]["data"]["properties"]["count"]
    count.update(max=5, default=0)
    manifest["inputs"]["data"]["required"] = []
    return manifest


async def refused(awaitable, code: C):
    with pytest.raises(PresentationStudioError) as caught:
        await awaitable
    assert caught.value.code is code, caught.value
    return caught.value


# ------------------------------------------------------------------ une bonne edition

async def test_a_good_source_edit_reloads_only_the_affected_scene(rig):
    before = await rig.variant()
    other_before = scene_of(before, SID2).to_dict()
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.status is S.RELOADED and result.mounted is True and result.http_status == 200
    after = await rig.variant()
    scene = scene_of(after)
    # the pin moved to the scene's own source id, exactly one version, the previous pin is no longer a fallback (confirmed)
    assert scene.prefab.prefab_id.startswith("presentation-studio.p") and scene.prefab.version == 1
    assert scene.source_revision == 1 and scene.last_valid_pin is None
    assert result.previous == PrefabRef("lab.counter", 1) and result.prefab == scene.prefab
    # the sibling scene is untouched, byte for byte
    assert scene_of(after, SID2).to_dict() == other_before
    # the stage window was re-pinned (that is the remount), values carried over
    block = await rig.stage_block()
    assert (block.prefab_id, block.version) == (scene.prefab.prefab_id, 1) and block.data["count"] == 12
    assert block.props["label"] == "Visiteurs"
    # the published source really carries the edit and starts from the previous source
    detail = await rig.prefabs.get(scene.prefab.prefab_id, 1)
    assert detail.entry.bundle.style == GOOD_STYLE and detail.entry.bundle.behavior == counter_behavior()


async def test_the_result_says_what_was_preserved_and_the_wire_is_json(rig):
    result = await rig.edit({"style": GOOD_STYLE})
    wire = result.to_dict()
    assert wire["preserved"] == {"variant_id": rig.vid, "scene_id": SID, "playback": None, "playback_unchanged": True}
    assert wire["basis"] == {"variant_revision": 2} and wire["revision"] == 4 and wire["source_revision"] == 1
    assert json.loads(json.dumps(wire)) == wire and "error" not in wire


async def test_a_second_edit_revises_the_scenes_own_source_instead_of_forking_again(rig):
    first = await rig.edit({"style": "p{color:red}"})
    second = await rig.edit({"style": "p{color:blue}"})
    assert first.status is S.RELOADED and second.status is S.RELOADED
    assert second.prefab.prefab_id == first.prefab.prefab_id and second.prefab.version == 2
    assert scene_of(await rig.variant()).source_revision == 2
    assert rig.versions_of(first.prefab.prefab_id) == [1, 2]
    detail = await rig.prefabs.get(second.prefab.prefab_id, 2)
    assert detail.entry.bundle.style == "p{color:blue}"


async def test_live_values_committed_by_the_frame_survive_the_remount(rig):
    # the frame's own `state` events write the stage window's data (not the variant): a reload must carry them over
    from jarvis.domain.scene import SceneActor, SceneCommand, SceneObjectFields, SceneOp, ScenePrefabRef
    snapshot = await rig.scene.snapshot()
    stage = snapshot.get_object(f"studio-stage-{rig.pid.removeprefix('pst_')[:12]}")
    block = stage.payload.prefab
    live = ScenePrefabRef(block.prefab_id, block.version, block.props, {**block.data, "count": 77})
    await rig.scene.apply(SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.USER, object_id=stage.object_id,
                                       fields=SceneObjectFields(payload=stage.payload.__class__(
                                           title=stage.payload.title, prefab=live))))
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.status is S.RELOADED
    assert (await rig.stage_block()).data["count"] == 77                       # the clicks are not lost
    assert scene_of(await rig.variant()).data["count"] == 12                    # the authored value is not rewritten


async def test_a_reload_never_moves_the_playback_position(tmp_path):
    class Probe:
        def position(self, presentation_id):
            return {"variant_id": "x", "scene_id": SID, "state": "running", "item_id": "psi_000000000001"}

    rig = Rig(tmp_path)
    rig.playback = Probe()
    await rig.open()
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.preserved["playback"] == {"variant_id": "x", "scene_id": SID, "state": "running", "item_id": "psi_000000000001"}
    assert result.preserved["playback_unchanged"] is True
    await rig.close()


# ------------------------------------------------------------------ la validation avant tout

@pytest.mark.parametrize(("files", "needle"), [
    ({"template": "<iframe src='x'></iframe>"}, "forbidden tag"),
    ({"style": "@import url(https://evil.example/x.css);"}, "@import"),
    ({"template": '<p onclick="x()">hi</p>'}, "on*="),
    ({"manifest": {"id": "x"}}, "manifest"),
])
async def test_a_candidate_the_prefab_validation_refuses_is_never_published(rig, files, needle):
    before, versions = digest(rig), rig.versions_of("lab.counter")
    result = await rig.edit(files)
    assert result.status is S.REFUSED_VALIDATION and result.code == C.SOURCE_INVALID.value and result.http_status == 400
    assert needle in result.message and result.published is None
    assert digest(rig) == before and rig.versions_of("lab.counter") == versions
    assert not [p for p in rig.data.joinpath("prefabs").iterdir() if p.name.startswith("presentation-studio")]
    assert (await rig.stage_block()).version == 1 and rig.sink.of("core.presentation_studio.reload_refused")


async def test_a_manifest_declaring_a_prototype_property_is_refused(rig):
    manifest = json.loads((rig.data / "prefabs" / "lab.counter" / "1" / "manifest.json").read_text(encoding="utf-8"))
    manifest["inputs"]["data"]["properties"]["__proto__"] = {"type": "string"}
    result = await rig.edit({"manifest": manifest})
    assert result.status is S.REFUSED_VALIDATION and result.code == C.SOURCE_INVALID.value and "__proto__" in result.message


async def test_a_syntax_error_in_the_behavior_passes_the_static_gate_and_is_caught_at_mount(rig):
    # Python cannot compile JavaScript: the last gate is the host's mount report (rollback), proven below.
    result = await rig.edit(rig.behavior("function ( {"))
    assert result.status in (S.RELOADED, S.RELOADED_STATE_RESET) or result.status is S.ROLLED_BACK


async def test_incompatible_studio_values_are_refused_unless_a_reset_is_allowed_and_named(rig):
    manifest = shrunk_manifest(rig)
    before = digest(rig)
    refusal = await rig.edit({"manifest": manifest})
    assert refusal.status is S.REFUSED_VALIDATION and refusal.code == C.SCENE_INCOMPATIBLE.value
    assert "allow_state_reset" in refusal.message and digest(rig) == before
    assert not [p for p in (rig.data / "prefabs").iterdir() if p.name.startswith("presentation-studio")]
    reset = await rig.edit({"manifest": manifest}, allow_state_reset=True)
    assert reset.status is S.RELOADED_STATE_RESET and reset.reset is not None
    assert reset.reset.data == ("count",) and reset.reset.controls == ("start_count",) and reset.reset.anchors == ("reveal",)
    scene = scene_of(await rig.variant())
    assert "count" not in scene.data and [c.control_id for c in scene.controls] == ["headline"]
    assert [(a.anchor_id, a.control_id) for a in scene.anchors] == [("reveal", None)]    # the anchor stays, unbound
    assert "12" not in json.dumps(reset.to_dict()["reset"])                                   # names, never values


async def test_a_reload_that_would_break_the_score_is_refused(rig):
    item = {"item_id": "psi_000000000001", "scene_id": SID, "presenter": "user", "kind": "speech", "note": "Explain",
            "visual": [{"kind": "control_set", "scene_id": SID, "control_id": "start_count", "value": 11}],
            "next_item_id": None}
    await rig.studio.create_score(rig.pid, rig.vid, {
        "expected_variant_revision": (await rig.variant()).revision, "start_item_id": item["item_id"], "items": [item],
        "cues": [], "sequences": [], "recovery_points": []})
    manifest = shrunk_manifest(rig)
    before = digest(rig)
    result = await rig.edit({"manifest": manifest}, allow_state_reset=True)
    assert result.status is S.REFUSED_VALIDATION and result.code == C.SCORE_INCOMPATIBLE.value
    assert "start_count" in result.message and digest(rig) == before
    assert not [p for p in (rig.data / "prefabs").iterdir() if p.name.startswith("presentation-studio")]


# ------------------------------------------------------------------ retour arriere

def failing_studio_sources(pin):
    """Le navigateur : tout monte, sauf une source de scene du Studio (le comportement leve au montage)."""

    if pin.prefab_id.startswith("presentation-studio."):
        return {"outcome": "failed", "reason": "frame", "message": "SyntaxError: Unexpected token in behavior.js"}
    return {"outcome": "mounted"}


def stable(scene) -> dict:
    wire = scene.to_dict()
    wire.pop("source_revision")
    return wire


async def test_a_mount_failure_rolls_back_and_the_last_valid_scene_is_intact(tmp_path):
    rig = await Rig(tmp_path).open(host=failing_studio_sources)
    before = await rig.variant()
    block_before = await rig.stage_block()
    result = await rig.edit(rig.behavior("function ( {"))
    assert result.status is S.ROLLED_BACK and result.http_status == 409 and result.mounted is False
    assert result.code == C.MOUNT_FAILED.value and result.reason == "frame" and "SyntaxError" in result.message
    assert result.prefab == PrefabRef("lab.counter", 1) and result.published.prefab_id.startswith("presentation-studio.")
    after = await rig.variant()
    # the document is the previous one, byte for byte, but for the monotonic counter; nothing else moved
    assert stable(scene_of(after)) == stable(scene_of(before)) and scene_of(after).source_revision == 2
    assert scene_of(after).last_valid_pin is None and scene_of(after, SID2).to_dict() == scene_of(before, SID2).to_dict()
    block = await rig.stage_block()
    assert (block.prefab_id, block.version, block.props, block.data) == (
        block_before.prefab_id, block_before.version, block_before.props, block_before.data)
    # the failed version stays in the library, unpinned and harmless; the error is on the record, without frame text
    assert rig.versions_of(result.published.prefab_id) == [1]
    row = rig.sink.of("core.presentation_studio.reload_rolled_back")[-1]
    assert row[0] == "warning" and row[1]["code"] == C.MOUNT_FAILED.value and "SyntaxError" not in json.dumps(row[1])
    event = [e for e in rig.emitter.recorded if e[0] is T.SYSTEM_PRESENTATION_STUDIO_SCENE_RELOADED][-1]
    assert event[2]["status"] == "rolled_back" and event[2]["code"] == C.MOUNT_FAILED.value and "SyntaxError" not in json.dumps(event[2])
    # and the scene is still editable: a good edit afterwards lands as the next revision of the same source id
    rig.host.policy = lambda pin: {"outcome": "mounted"}
    good = await rig.edit({"style": GOOD_STYLE})
    assert good.status is S.RELOADED and good.prefab.prefab_id == result.published.prefab_id and good.prefab.version == 2
    await rig.close()


async def test_a_rollback_restores_the_live_values_the_frame_had_committed(tmp_path):
    rig = await Rig(tmp_path).open(host=failing_studio_sources)
    from jarvis.domain.scene import SceneActor, SceneCommand, SceneObjectFields, SceneOp, ScenePayload, ScenePrefabRef
    stage = (await rig.scene.snapshot()).get_object(f"studio-stage-{rig.pid.removeprefix('pst_')[:12]}")
    block = stage.payload.prefab
    await rig.scene.apply(SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.USER, object_id=stage.object_id,
                                       fields=SceneObjectFields(payload=ScenePayload(
                                           title=stage.payload.title,
                                           prefab=ScenePrefabRef(block.prefab_id, block.version, block.props,
                                                                 {**block.data, "count": 41})))))
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.status is S.ROLLED_BACK
    assert (await rig.stage_block()).data["count"] == 41
    await rig.close()


# ------------------------------------------------------------------ pannes injectees, une par etape

async def test_a_candidate_validation_that_crashes_changes_nothing(rig, monkeypatch):
    before = digest(rig)

    def boom(candidate):
        raise RuntimeError("validator down")

    monkeypatch.setattr(rig.prefabs, "validate_candidate", boom)
    with pytest.raises(RuntimeError):
        await rig.edit({"style": GOOD_STYLE})
    assert digest(rig) == before and rig.reload.stats()["inflight"] == 0 and not rig.reload._drafts


async def test_a_failing_publication_changes_nothing_and_a_capacity_refusal_names_its_way_out(rig, monkeypatch):
    before, submit = digest(rig), rig.coalescer.submit

    async def broken(candidate, **kw):
        raise PrefabStoreError(PrefabStoreErrorCode.STORAGE_IO, "disk gone")

    monkeypatch.setattr(rig.coalescer, "submit", broken)
    await refused(rig.edit({"style": GOOD_STYLE}), C.STORAGE_IO)
    assert digest(rig) == before and not rig.reload._drafts

    async def full(candidate, **kw):
        raise PrefabStoreError(PrefabStoreErrorCode.VERSION_LIMIT, "64 live versions: save under a new id")

    monkeypatch.setattr(rig.coalescer, "submit", full)
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.status is S.REFUSED_VALIDATION and result.code == C.LIMIT_REACHED.value and "version_limit" in result.message
    monkeypatch.setattr(rig.coalescer, "submit", submit)
    assert (await rig.edit({"style": GOOD_STYLE})).status is S.RELOADED


async def test_a_pin_write_that_fails_leaves_the_stage_and_the_document_alone_and_the_next_edit_works(rig, monkeypatch):
    before, block, write = digest(rig), await rig.stage_block(), rig.studio.replace_scene_source
    calls = []

    async def failing(*args, **kwargs):
        calls.append(1)
        raise PresentationStudioError(C.STORAGE_IO, "replace_scene_source: OSError: disk full")

    monkeypatch.setattr(rig.studio, "replace_scene_source", failing)
    await refused(rig.edit({"style": GOOD_STYLE}), C.STORAGE_IO)
    assert digest(rig) == before and calls == [1]
    assert (await rig.stage_block()).version == block.version and (await rig.stage_block()).prefab_id == block.prefab_id
    published = [p.name for p in (rig.data / "prefabs").iterdir() if p.name.startswith("presentation-studio")]
    assert len(published) == 1                          # published, never pinned: harmless, retention may archive it
    monkeypatch.setattr(rig.studio, "replace_scene_source", write)
    again = await rig.edit({"style": "p{color:blue}"})
    assert again.status is S.RELOADED and again.prefab.version == 2        # numbering continues, nothing reused


async def test_a_stage_patch_that_fails_rolls_the_pin_back_and_says_why(rig, monkeypatch):
    before = stable(scene_of(await rig.variant()))

    async def gone(*args, **kwargs):
        raise StagePatchError("stage_missing", "the stage window no longer exists")

    monkeypatch.setattr(rig.stage, "repin", gone)
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.status is S.ROLLED_BACK and result.code == C.STAGE_FAILED.value and result.reason == "stage_missing"
    assert result.mounted is None and stable(scene_of(await rig.variant())) == before
    assert scene_of(await rig.variant()).last_valid_pin is None


async def test_a_rollback_that_cannot_write_keeps_the_new_pin_with_its_fallback_and_a_late_report_finishes_it(tmp_path, monkeypatch):
    rig = await Rig(tmp_path).open(host=failing_studio_sources)
    real, calls = rig.studio.replace_scene_source, []

    async def second_fails(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise PresentationStudioError(C.STORAGE_IO, "replace_scene_source: OSError: disk full")
        return await real(*args, **kwargs)

    monkeypatch.setattr(rig.studio, "replace_scene_source", second_fails)
    degraded = await rig.edit({"style": GOOD_STYLE})
    assert degraded.status is S.DEGRADED and degraded.code == C.STORAGE_IO.value and degraded.mounted is False
    assert "previous pin could not be written back" in degraded.message and degraded.http_status == 409
    scene = scene_of(await rig.variant())
    # consistent and recoverable: the document still names the fallback that restores the previous version
    assert scene.prefab.prefab_id.startswith("presentation-studio.") and scene.last_valid_pin == PrefabRef("lab.counter", 1)
    assert rig.sink.of("core.presentation_studio.reload_rollback_failed")
    monkeypatch.setattr(rig.studio, "replace_scene_source", real)
    assert await rig.reload.recover() == 1
    report = {"object_id": f"studio-stage-{rig.pid.removeprefix('pst_')[:12]}", "prefab": scene.prefab.to_dict(),
              "outcome": "failed", "reason": "frame", "message": "still broken"}
    answer = await rig.reload.handle_mount_report(report)
    assert answer["resolved"] == 1
    healed = scene_of(await rig.variant())
    assert healed.prefab == PrefabRef("lab.counter", 1) and healed.last_valid_pin is None
    assert (await rig.stage_block()).prefab_id == "lab.counter"
    await rig.close()


# ------------------------------------------------------------------ pas de fenetre, pas de rapport

async def test_without_a_stage_window_the_pin_waits_and_the_first_mount_report_decides(tmp_path):
    rig = await Rig(tmp_path).open(host=False, show=False)
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.status is S.REPINNED and result.mounted is None and result.http_status == 200
    scene = scene_of(await rig.variant())
    assert scene.last_valid_pin == PrefabRef("lab.counter", 1) and scene.source_revision == 1
    held = await rig.pins.pinned_versions(["lab.counter", scene.prefab.prefab_id])
    assert held["lab.counter"] == frozenset({1}) and held[scene.prefab.prefab_id] == frozenset({1})
    ok = {"object_id": "any-window", "prefab": scene.prefab.to_dict(), "outcome": "mounted"}
    assert (await rig.reload.handle_mount_report(ok))["resolved"] == 1
    confirmed = scene_of(await rig.variant())
    assert confirmed.last_valid_pin is None and confirmed.prefab == scene.prefab and confirmed.source_revision == 1
    # a second edit, never shown, then a late failure: back to the previous source, loud in the journal
    second = await rig.edit({"style": "p{color:red}"})
    assert second.status is S.REPINNED
    failed = {"object_id": "any-window", "prefab": second.prefab.to_dict(), "outcome": "failed", "reason": "bundle"}
    await rig.reload.handle_mount_report(failed)
    back = scene_of(await rig.variant())
    assert back.prefab == scene.prefab and back.last_valid_pin is None and back.source_revision == 3
    assert rig.sink.of("core.presentation_studio.reload_late")[-1][0] == "warning"
    await rig.close()


async def test_a_page_that_never_reports_leaves_a_pending_mount_with_its_fallback_and_a_late_report_confirms_it(tmp_path):
    rig = await Rig(tmp_path, mount_deadline_s=0.2).open(host=False)
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.status is S.PENDING_MOUNT and result.http_status == 202 and result.waited_s >= 0.19
    assert "did not report" in result.message and result.code == C.MOUNT_FAILED.value
    scene = scene_of(await rig.variant())
    assert scene.prefab == result.prefab and scene.last_valid_pin == PrefabRef("lab.counter", 1)
    assert (await rig.stage_block()).prefab_id == scene.prefab.prefab_id          # the new version is on the stage
    object_id = f"studio-stage-{rig.pid.removeprefix('pst_')[:12]}"
    await rig.reload.handle_mount_report({"object_id": object_id, "prefab": scene.prefab.to_dict(), "outcome": "mounted"})
    assert scene_of(await rig.variant()).last_valid_pin is None
    await rig.close()


async def test_a_wrong_object_or_a_wrong_version_never_confirms_anything(tmp_path):
    rig = await Rig(tmp_path, mount_deadline_s=0.2).open(host=False)
    result = await rig.edit({"style": GOOD_STYLE})
    other = {"object_id": "somebody-else", "prefab": {"id": "lab.counter", "version": 1}, "outcome": "failed"}
    answer = await rig.reload.handle_mount_report(other)
    assert answer == {"matched": False, "waiting": 0, "resolved": 0, "scenes": []}
    assert scene_of(await rig.variant()).prefab == result.prefab
    await refused(rig.reload.handle_mount_report({"object_id": "x", "prefab": {"id": "lab.counter", "version": 1}}),
                  C.INVALID_PRESENTATION)
    await rig.close()


# ------------------------------------------------------------------ concurrence

async def test_a_burst_of_edits_on_one_scene_is_one_version_and_one_outcome(tmp_path):
    rig = await Rig(tmp_path, quiet_s=0.4, max_wait_s=2.0).open()
    first, second = await asyncio.gather(rig.edit({"style": "p{color:red}"}),
                                         rig.edit({"behavior": counter_behavior() + "\n// retouche"}))
    assert first.status is S.RELOADED and second.status is S.RELOADED
    assert first.prefab == second.prefab and sorted([first.merged, second.merged]) == [False, True]
    assert rig.versions_of(first.prefab.prefab_id) == [1]                       # ONE version for the whole burst
    detail = await rig.prefabs.get(first.prefab.prefab_id, 1)
    assert detail.entry.bundle.style == "p{color:red}" and detail.entry.bundle.behavior.endswith("// retouche")  # no retouche lost
    assert scene_of(await rig.variant()).source_revision == 1
    await rig.close()


async def test_two_edits_from_the_same_stale_base_one_wins_and_the_other_is_stale(rig):
    revision = (await rig.variant()).revision
    first = await rig.edit({"style": "p{color:red}"}, revision=revision)
    second = await rig.edit({"style": "p{color:blue}"}, revision=revision)
    assert first.status is S.RELOADED and second.status is S.STALE and second.http_status == 409
    assert second.code == C.STALE_REVISION.value and "read it again" in second.message
    detail = await rig.prefabs.get(first.prefab.prefab_id, first.prefab.version)
    assert detail.entry.bundle.style == "p{color:red}" and rig.versions_of(first.prefab.prefab_id) == [1]


async def test_a_control_edit_landing_during_the_edit_makes_the_source_edit_stale_not_lost(rig):
    revision = (await rig.variant()).revision
    await rig.edits.edit(rig.pid, rig.vid, {"actor": "user", "mode": "commit", "basis": {"variant_revision": revision},
                                            "ops": [{"op": "control.set", "scene_id": SID, "control_id": "headline",
                                                     "value": "Autre"}]})
    result = await rig.edit({"style": GOOD_STYLE}, revision=revision)
    assert result.status is S.STALE
    assert scene_of(await rig.variant()).props["label"] == "Autre"          # the control edit stands


async def test_edits_to_different_scenes_do_not_touch_each_other_and_only_the_shown_one_is_patched(rig):
    first = await rig.edit({"style": "p{color:red}"}, scene_id=SID)
    third = await rig.edit({"style": "p{color:green}"}, scene_id=SID2)
    assert first.status is S.RELOADED
    assert third.status is S.REPINNED and third.mounted is None            # SID2 is not on the stage
    scene1, scene2 = scene_of(await rig.variant()), scene_of(await rig.variant(), SID2)
    assert scene1.prefab.prefab_id != scene2.prefab.prefab_id             # one source id per scene
    assert (await rig.stage_block()).prefab_id == scene1.prefab.prefab_id


async def test_nothing_new_is_accepted_after_close_and_the_pending_burst_is_published_first(tmp_path):
    rig = await Rig(tmp_path, quiet_s=60.0, max_wait_s=120.0).open()      # only a flush can publish it inside the test's wait
    pending = asyncio.ensure_future(rig.edit({"style": GOOD_STYLE}))
    await asyncio.sleep(0.3)
    assert rig.coalescer.pending_ids                                             # the burst is waiting on its quiet period
    await rig.reload.close()
    result = await asyncio.wait_for(pending, 10)
    assert result.status in (S.RELOADED, S.PENDING_MOUNT) and not rig.coalescer.pending_ids
    await refused(rig.edit({"style": "p{color:red}"}), C.RELOAD_UNAVAILABLE)
    await rig.scene.close()


# ------------------------------------------------------------------ demandes de source, evenements, bornes

async def test_a_source_request_is_closed_by_the_edit_that_answers_it_and_never_blocks_one(rig):
    revision = (await rig.variant()).revision
    recorded = await rig.edits.edit(rig.pid, rig.vid, {
        "actor": "brain", "mode": "commit", "basis": {"variant_revision": revision},
        "ops": [{"op": "scene.source_request", "scene_id": SID, "intent": "Make the title bigger"}]})
    request_id = recorded.source_requests[0]["request_id"]
    assert [r.request_id for r in rig.edits.pending_source_requests()] == [request_id]
    result = await rig.edit({"style": GOOD_STYLE}, request_id=request_id, actor="brain", revision=recorded.revision)
    assert result.status is S.RELOADED and result.request_id == request_id and result.actor.value == "brain"
    assert rig.edits.pending_source_requests() == ()
    # an unknown (evicted, restarted) request id is not an error: the queue is not durable by decision
    again = await rig.edit({"style": "p{color:red}"}, request_id="psq_0000000000ff")
    assert again.status is S.RELOADED


async def test_events_and_journal_rows_carry_ids_and_codes_never_source_or_values(rig):
    await rig.edit({"style": "p{color:#123456}"})
    events = [e for e in rig.emitter.recorded if e[0] is T.SYSTEM_PRESENTATION_STUDIO_SCENE_RELOADED]
    assert len(events) == 1 and events[0][2]["status"] == "reloaded" and events[0][2]["tier"] == "source"
    blob = json.dumps([e[2] for e in events]) + json.dumps(
        [row for row in rig.sink.rows if row[0].startswith("core.presentation_studio.reload")])
    for secret in ("#123456", "Visiteurs", "p{color"):
        assert secret not in blob


async def test_the_bookkeeping_stays_bounded_over_many_reloads(rig):
    for index in range(6):
        assert (await rig.edit({"style": f"p{{color:#00000{index}}}"})).status is S.RELOADED
    assert not rig.reload._drafts and rig.reload.stats()["inflight"] == 0
    assert len(rig.reload._outcomes) <= 64 and len(rig.reload.recent()) <= 64
    assert rig.reload.mounts.stats().waiting == 0
    assert rig.pins.stats()["holds"] == 0


async def test_after_a_restart_the_unconfirmed_scenes_are_found_again_from_their_documents(tmp_path):
    rig = await Rig(tmp_path, mount_deadline_s=0.2).open(host=False)
    result = await rig.edit({"style": GOOD_STYLE})
    assert result.status is S.PENDING_MOUNT
    from jarvis.core.presentation_studio_reload import PresentationStudioReloadService
    fresh = PresentationStudioReloadService(rig.studio, rig.prefabs, rig.coalescer, rig.stage, pins=rig.pins,
                                            diagnostics=rig.sink)
    assert await fresh.recover() == 1 and fresh.pending_scenes()[0].fallback == PrefabRef("lab.counter", 1)
    await rig.close()


# ------------------------------------------------------------------ champs du rechargement : la propriete du service

async def save_with(rig: Rig, scenes: list):
    variant = await rig.variant()
    return await rig.studio.save_variant(rig.pid, rig.vid, {
        "expected_revision": variant.revision, "title": variant.title, "scenes": scenes,
        "art_direction_id": None, "score_id": None})


async def test_a_variant_save_can_neither_set_nor_lower_the_reload_fields(rig):
    variant = await rig.variant()
    body = [s.to_dict() for s in variant.scenes]
    for forged in ({"source_revision": 7}, {"last_valid_pin": {"id": "jarvis.counter", "version": 1}}):
        scenes = [{**body[0], **forged}, body[1]]
        error = await refused(save_with(rig, scenes), C.INVALID_PRESENTATION)
        assert "owned by the hot reload" in error.message
    assert (await rig.variant()).revision == variant.revision                   # nothing was written
    # an unchanged round trip is fine, and so is a value equal to the stored one
    assert (await save_with(rig, body)).revision == variant.revision + 1


async def test_a_new_scene_starts_at_zero_with_no_fallback_whatever_the_body_says(rig):
    variant = await rig.variant()
    body = [s.to_dict() for s in variant.scenes]
    fresh = scene_body("pss_0000000000a3", title="Neuve")
    await refused(save_with(rig, [*body, {**fresh, "source_revision": 3}]), C.INVALID_PRESENTATION)
    saved = await save_with(rig, [*body, fresh])
    added = next(s for s in saved.scenes if s.scene_id == "pss_0000000000a3")
    assert (added.source_revision, added.last_valid_pin) == (0, None)


async def test_an_ordinary_pin_change_moves_the_counter_by_one_and_clears_the_fallback(tmp_path):
    rig = await Rig(tmp_path, mount_deadline_s=0.2).open(host=False, show=False)
    try:
        await rig.edit({"style": GOOD_STYLE})                                      # repinned: counter 1, fallback lab.counter@1
        before = scene_of(await rig.variant())
        assert before.source_revision == 1 and before.last_valid_pin == PrefabRef("lab.counter", 1)
        body = [s.to_dict() for s in (await rig.variant()).scenes]
        body[0]["prefab"] = {"id": "lab.counter", "version": 1}                    # a manual re-pin through the ordinary save
        body[0]["last_valid_pin"] = None                                            # (the fallback of a scene is never its own pin)
        body[0]["source_revision"] = 1                                              # the stored value, or one more, is accepted
        saved = await save_with(rig, body)
        moved = scene_of(saved)
        assert moved.prefab == PrefabRef("lab.counter", 1) and moved.source_revision == 2 and moved.last_valid_pin is None
        # a lower counter, or a fallback invented while the pin moves, is refused
        again = [s.to_dict() for s in saved.scenes]
        again[0]["prefab"] = before.prefab.to_dict()
        again[0]["source_revision"] = 0
        await refused(save_with(rig, again), C.INVALID_PRESENTATION)
        again[0]["source_revision"] = 2
        again[0]["last_valid_pin"] = {"id": "jarvis.counter", "version": 1}      # a fallback invented while the pin moves
        await refused(save_with(rig, again), C.INVALID_PRESENTATION)
    finally:
        await rig.close()


async def test_replace_scene_source_moves_the_counter_by_exactly_one_when_the_pin_moves_and_never_otherwise(rig):
    from dataclasses import replace
    variant = await rig.variant()
    scene = scene_of(variant)
    moved = replace(scene, prefab=PrefabRef("jarvis.counter", 1), last_valid_pin=scene.prefab)
    for wrong in (0, 2, 5):
        await refused(rig.studio.replace_scene_source(rig.pid, rig.vid, expected_revision=variant.revision,
                                                      scene=replace(moved, source_revision=wrong)), C.INVALID_PRESENTATION)
    saved = await rig.studio.replace_scene_source(rig.pid, rig.vid, expected_revision=variant.revision,
                                                  scene=replace(moved, source_revision=1))
    assert scene_of(saved).source_revision == 1 and saved.revision == variant.revision + 1
    # same pin: the counter does not move (confirming a pin clears the fallback and leaves the counter alone)
    confirmed = await rig.studio.replace_scene_source(rig.pid, rig.vid, expected_revision=saved.revision,
                                                      scene=replace(scene_of(saved), last_valid_pin=None))
    assert scene_of(confirmed).source_revision == 1 and scene_of(confirmed).last_valid_pin is None
    await refused(rig.studio.replace_scene_source(rig.pid, rig.vid, expected_revision=confirmed.revision,
                                                  scene=replace(scene_of(confirmed), source_revision=2)), C.INVALID_PRESENTATION)
    await refused(rig.studio.replace_scene_source(rig.pid, rig.vid, expected_revision=1, scene=scene_of(confirmed)), C.STALE_REVISION)
    await refused(rig.studio.replace_scene_source(rig.pid, rig.vid, expected_revision=confirmed.revision,
                                                  scene=replace(scene_of(confirmed), scene_id="pss_00000000ffff")), C.UNKNOWN_SCENE)


async def test_the_source_revision_is_monotonic_across_edits_rollbacks_and_manual_changes(tmp_path):
    rig = await Rig(tmp_path).open(host=failing_studio_sources)
    try:
        seen = [scene_of(await rig.variant()).source_revision]
        assert (await rig.edit({"style": GOOD_STYLE})).status is S.ROLLED_BACK            # +2: the pin moved, then moved back
        seen.append(scene_of(await rig.variant()).source_revision)
        rig.host.policy = lambda pin: {"outcome": "mounted"}
        assert (await rig.edit({"style": "p{color:red}"})).status is S.RELOADED            # +1
        seen.append(scene_of(await rig.variant()).source_revision)
        assert (await rig.edit({"style": "p{color:blue}"})).status is S.RELOADED           # +1
        seen.append(scene_of(await rig.variant()).source_revision)
        assert seen == [0, 2, 3, 4] and seen == sorted(seen)
    finally:
        await rig.close()


# ------------------------------------------------------------------ la course entre la publication et le pin

async def test_a_control_edit_that_lands_between_the_publication_and_the_pin_makes_the_edit_stale(rig, monkeypatch):
    real = rig.coalescer.submit
    revision = (await rig.variant()).revision

    async def with_a_rival(candidate, **kw):
        publication = await real(candidate, **kw)             # the version is published ...
        await rig.edits.edit(rig.pid, rig.vid, {"actor": "user", "mode": "commit", "basis": {"variant_revision": revision},
                                                "ops": [{"op": "control.set", "scene_id": SID, "control_id": "headline",
                                                         "value": "Rival"}]})          # ... and someone else writes the variant before the pin
        return publication

    monkeypatch.setattr(rig.coalescer, "submit", with_a_rival)
    result = await rig.edit({"style": GOOD_STYLE}, revision=revision)
    assert result.status is S.STALE and result.published is not None and result.code == C.STALE_REVISION.value
    scene = scene_of(await rig.variant())
    assert scene.prefab == PrefabRef("lab.counter", 1) and scene.props["label"] == "Rival" and scene.source_revision == 0
    assert (await rig.stage_block()).prefab_id == "lab.counter"                     # nothing reached the stage
    monkeypatch.setattr(rig.coalescer, "submit", real)
    again = await rig.edit({"style": "p{color:red}"})                               # the retry works and numbering continues
    assert again.status is S.RELOADED and again.prefab.version == 2


async def test_a_pin_changed_by_someone_else_between_the_publication_and_the_pin_makes_the_edit_stale(rig, monkeypatch):
    real = rig.coalescer.submit
    revision = (await rig.variant()).revision

    async def with_a_manual_repin(candidate, **kw):
        publication = await real(candidate, **kw)
        variant = await rig.variant()
        body = [s.to_dict() for s in variant.scenes]
        body[0]["prefab"] = {"id": "jarvis.counter", "version": 1}                 # another writer re-pinned the scene by hand
        body[0]["props"], body[0]["data"], body[0]["controls"], body[0]["anchors"] = {}, {"count": 1}, [], []
        await rig.studio.save_variant(rig.pid, rig.vid, {"expected_revision": variant.revision, "title": variant.title,
                                                         "scenes": body, "art_direction_id": None, "score_id": None})
        return publication

    monkeypatch.setattr(rig.coalescer, "submit", with_a_manual_repin)
    result = await rig.edit({"style": GOOD_STYLE}, revision=revision)
    assert result.status is S.STALE and "another edit landed" in result.message
    assert scene_of(await rig.variant()).prefab == PrefabRef("jarvis.counter", 1)    # the other writer's pin stands


# ------------------------------------------------------------------ QA-1 B1 : une edition de controle pendant un rechargement

def silent(pin):
    """Le navigateur ne repond pas tout seul : le test livre le rapport quand il le veut."""

    return None if pin.prefab_id.startswith("presentation-studio.") else {"outcome": "mounted"}


async def set_count(rig: Rig, value, *, control_id: str = "start_count"):
    variant = await rig.variant()
    return await rig.edits.edit(rig.pid, rig.vid, {"actor": "user", "mode": "commit", "basis": {"variant_revision": variant.revision},
                                                   "ops": [{"op": "control.set", "scene_id": SID, "control_id": control_id,
                                                            "value": value}]})


async def in_flight(rig: Rig, task: asyncio.Task) -> None:
    """Attend que l'edition ait patche le stage (l'attente du rapport est ouverte) et ne l'ait pas encore fini."""

    for _ in range(400):
        block = await rig.stage_block()
        if block is not None and block.prefab_id.startswith("presentation-studio.") and not task.done():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the reload never reached the mount wait")


async def report(rig: Rig, outcome: str = "failed") -> dict:
    scene = scene_of(await rig.variant())
    body = {"object_id": f"studio-stage-{rig.pid.removeprefix('pst_')[:12]}", "prefab": scene.prefab.to_dict(), "outcome": outcome}
    if outcome == "failed":
        body.update(reason="frame", message="SyntaxError: boom")
    return await rig.reload.handle_mount_report(body)


async def test_a_control_edit_during_a_reload_is_refused_with_a_typed_409_and_works_once_it_is_over(tmp_path):
    rig = await Rig(tmp_path, mount_deadline_s=10).open(host=silent)
    try:
        task = asyncio.ensure_future(rig.edit({"style": GOOD_STYLE}))
        await in_flight(rig, task)
        assert rig.reload.is_reloading(rig.pid, rig.vid, SID)
        error = await refused(set_count(rig, 77), C.SCENE_RELOADING)                    # visible and retry-able
        assert HTTP_STATUS[error.code] == 409 and "retry" in error.message
        variant = await rig.variant()
        other = await rig.edits.edit(rig.pid, rig.vid, {"actor": "user", "mode": "commit", "basis": {"variant_revision": variant.revision},
                                                        "ops": [{"op": "control.set", "scene_id": SID2, "control_id": "headline",
                                                                 "value": "Autre"}]})
        assert other.committed, "a scene that is not being reloaded stays editable"
        body = [s.to_dict() for s in (await rig.variant()).scenes]
        body[0]["title"] = "Renommee"                                                    # a structure save that touches the scene
        await refused(rig.studio.save_variant(rig.pid, rig.vid, {
            "expected_revision": (await rig.variant()).revision, "title": variant.title, "scenes": body,
            "art_direction_id": None, "score_id": None}), C.SCENE_RELOADING)
        assert (await report(rig))["waiting"] == 1
        result = await task
        assert result.status is S.ROLLED_BACK
        assert scene_of(await rig.variant()).data["count"] == 12                         # nothing was lost: nothing was accepted
        assert not rig.reload.is_reloading(rig.pid, rig.vid, SID)
        assert (await set_count(rig, 77)).committed                                       # after the reload, the same edit lands
        assert scene_of(await rig.variant()).data["count"] == 77
    finally:
        await rig.close()


async def test_the_reload_guard_also_ends_when_the_reload_raises(tmp_path, monkeypatch):
    rig = await Rig(tmp_path).open()
    try:
        async def broken(*args, **kwargs):
            raise PresentationStudioError(C.STORAGE_IO, "replace_scene_source: OSError: disk full")

        monkeypatch.setattr(rig.studio, "replace_scene_source", broken)
        await refused(rig.edit({"style": GOOD_STYLE}), C.STORAGE_IO)
        assert not rig.reload.is_reloading(rig.pid, rig.vid, SID)
        assert (await set_count(rig, 31)).committed
    finally:
        await rig.close()


async def test_rollback_keeps_a_control_value_written_during_the_wait_even_if_nothing_refuses_it(tmp_path):
    """(b) alone: with the guard of (a) off, the rollback is still a compare-and-restore, never a stale whole-scene copy."""

    rig = await Rig(tmp_path, mount_deadline_s=10).open(host=silent)
    try:
        rig.studio.set_scene_guard(None)
        task = asyncio.ensure_future(rig.edit({"style": GOOD_STYLE}))
        await in_flight(rig, task)
        assert (await set_count(rig, 77)).committed                                       # lands while the host is mounting
        await report(rig)
        result = await task
        assert result.status is S.ROLLED_BACK and result.reset is None
        scene = scene_of(await rig.variant())
        assert scene.prefab == PrefabRef("lab.counter", 1) and scene.last_valid_pin is None
        assert scene.data["count"] == 77 and scene.props["label"] == "Visiteurs"
        assert scene.source_revision == 2                                                 # the counter moved forward, twice
        assert result.source_revision == 2 and result.revision == (await rig.variant()).revision
    finally:
        await rig.close()


async def test_a_late_failure_report_does_not_undo_a_control_edit_made_while_the_scene_waited(tmp_path):
    rig = await Rig(tmp_path, mount_deadline_s=0.2).open(host=silent)
    try:
        result = await rig.edit({"style": GOOD_STYLE})
        assert result.status is S.PENDING_MOUNT and not rig.reload.is_reloading(rig.pid, rig.vid, SID)
        assert (await set_count(rig, 77)).committed                                       # allowed: nothing is in flight now
        assert (await report(rig))["resolved"] == 1                                       # the late failure
        scene = scene_of(await rig.variant())
        assert scene.prefab == PrefabRef("lab.counter", 1) and scene.last_valid_pin is None
        assert scene.data["count"] == 77
    finally:
        await rig.close()


async def test_a_late_success_report_confirms_without_touching_a_control_value(tmp_path):
    rig = await Rig(tmp_path, mount_deadline_s=0.2).open(host=silent)
    try:
        assert (await rig.edit({"style": GOOD_STYLE})).status is S.PENDING_MOUNT
        assert (await set_count(rig, 64)).committed
        assert (await report(rig, "mounted"))["resolved"] == 1
        scene = scene_of(await rig.variant())
        assert scene.prefab.prefab_id.startswith("presentation-studio.") and scene.last_valid_pin is None
        assert scene.data["count"] == 64
    finally:
        await rig.close()


async def test_a_value_that_no_longer_fits_the_restored_version_is_reset_and_said(tmp_path):
    rig = await Rig(tmp_path, mount_deadline_s=10).open(host=silent)
    try:
        rig.studio.set_scene_guard(None)
        task = asyncio.ensure_future(rig.edit({"style": GOOD_STYLE}))
        await in_flight(rig, task)
        variant = await rig.variant()
        scene = scene_of(variant)
        from dataclasses import replace
        await rig.studio.replace_scene_source(rig.pid, rig.vid, expected_revision=variant.revision,
                                              scene=replace(scene, props={**scene.props, "mode": "weird"}))
        await report(rig)
        result = await task
        assert result.status is S.ROLLED_BACK and result.reset is not None and "mode" in result.reset.props
        assert "reset" in result.message
        healed = scene_of(await rig.variant())
        assert healed.prefab == PrefabRef("lab.counter", 1) and "mode" not in healed.props and healed.data["count"] == 12
    finally:
        await rig.close()


async def test_a_reset_made_by_the_reload_comes_back_with_the_rollback_when_nobody_touched_it(tmp_path):
    rig = await Rig(tmp_path).open(host=failing_studio_sources)
    try:
        before = scene_of(await rig.variant())
        result = await rig.edit({"manifest": rig.shrunk_manifest()}, allow_state_reset=True)
        assert result.status is S.ROLLED_BACK
        after = scene_of(await rig.variant())
        assert (after.props, after.data, after.controls, after.anchors) == (before.props, before.data, before.controls, before.anchors)
    finally:
        await rig.close()


# ------------------------------------------------------------------ QA-1 : les autres trous du retour arriere

async def test_when_the_stage_cannot_be_restored_the_scene_is_degraded_visibly_and_repairable(tmp_path, monkeypatch):
    rig = await Rig(tmp_path).open(host=failing_studio_sources)
    try:
        real, calls = rig.stage.repin, []

        async def repin(*args, **kwargs):
            calls.append(1)
            if len(calls) > 1:
                raise StagePatchError("stage_unavailable", "the scene service is down")
            return await real(*args, **kwargs)

        monkeypatch.setattr(rig.stage, "repin", repin)
        result = await rig.edit({"style": GOOD_STYLE})
        assert result.status is S.DEGRADED and result.http_status == 409 and result.mounted is False
        assert result.code == C.STAGE_FAILED.value and "stage window could not be put back" in result.message
        assert len(calls) == 1 + 3                                                       # bounded: one patch, three restores
        scene = scene_of(await rig.variant())
        assert scene.prefab.prefab_id.startswith("presentation-studio.") and scene.last_valid_pin == PrefabRef("lab.counter", 1)
        assert [p.scene_id for p in rig.reload.pending_scenes()] == [SID]                 # a report or a restart can repair it
        assert rig.reload.stats()["degraded"] == 1 and rig.sink.of("core.presentation_studio.reload_rollback_failed")
        assert any(row["status"] == "degraded" for row in rig.reload.recent())
        monkeypatch.setattr(rig.stage, "repin", real)                                     # the scene service is back
        assert (await report(rig))["resolved"] == 1                                       # the next report repairs it
        healed = scene_of(await rig.variant())
        assert healed.prefab == PrefabRef("lab.counter", 1) and healed.last_valid_pin is None
        assert (await rig.stage_block()).prefab_id == "lab.counter"
    finally:
        await rig.close()


async def test_a_stage_fault_and_a_failed_variant_restore_leave_the_fallback_written_and_raise_the_original_fault(tmp_path, monkeypatch):
    rig = await Rig(tmp_path).open()
    try:
        real = rig.studio.replace_scene_source
        calls = []

        async def second_fails(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise PresentationStudioError(C.STORAGE_IO, "replace_scene_source: OSError: disk full")
            return await real(*args, **kwargs)

        async def boom(*args, **kwargs):
            raise RuntimeError("the scene service blew up")

        monkeypatch.setattr(rig.studio, "replace_scene_source", second_fails)
        monkeypatch.setattr(rig.stage, "repin", boom)
        with pytest.raises(RuntimeError, match="blew up"):
            await rig.edit({"style": GOOD_STYLE})
        scene = scene_of(await rig.variant())
        assert scene.prefab.prefab_id.startswith("presentation-studio.") and scene.last_valid_pin == PrefabRef("lab.counter", 1)
        assert [p.scene_id for p in rig.reload.pending_scenes()] == [SID] and rig.reload.stats()["degraded"] == 1
        assert not rig.reload.is_reloading(rig.pid, rig.vid, SID)
    finally:
        await rig.close()


async def test_a_confirmation_that_cannot_be_written_never_reports_reloaded(tmp_path, monkeypatch):
    rig = await Rig(tmp_path).open()
    try:
        real, calls = rig.studio.replace_scene_source, []

        async def confirm_fails(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise PresentationStudioError(C.STORAGE_IO, "replace_scene_source: OSError: disk full")
            return await real(*args, **kwargs)

        monkeypatch.setattr(rig.studio, "replace_scene_source", confirm_fails)
        result = await rig.edit({"style": GOOD_STYLE})
        assert result.status is S.PENDING_MOUNT and result.mounted is True and result.code == C.STORAGE_IO.value
        assert "confirmation could not be written" in result.message and result.http_status == 202
        scene = scene_of(await rig.variant())
        assert scene.last_valid_pin == PrefabRef("lab.counter", 1)                        # the fallback is still there
        assert [p.scene_id for p in rig.reload.pending_scenes()] == [SID]
        assert rig.sink.of("core.presentation_studio.reload_confirm_failed")
        monkeypatch.setattr(rig.studio, "replace_scene_source", real)
        assert (await report(rig, "mounted"))["resolved"] == 1                            # a later report finishes the job
        assert scene_of(await rig.variant()).last_valid_pin is None
    finally:
        await rig.close()


# ------------------------------------------------------------------ plafond des editions de l'agent

async def test_the_brain_is_rate_limited_per_scene_and_the_user_is_not(tmp_path):
    from jarvis.core.presentation_studio_reload import BRAIN_EDIT_LIMIT, BRAIN_EDIT_WINDOW_S
    rig = await Rig(tmp_path).open()
    clock = [100.0]
    rig.reload._monotonic = lambda: clock[0]
    try:
        for index in range(BRAIN_EDIT_LIMIT):
            assert (await rig.edit({"style": f"p{{color:#a{index:05d}}}"}, actor="brain")).status is S.RELOADED
        error = await refused(rig.edit({"style": "p{color:red}"}, actor="brain"), C.SOURCE_EDIT_RATE)
        assert HTTP_STATUS[error.code] == 429 and f"{BRAIN_EDIT_LIMIT} source edits" in error.message
        assert rig.sink.of("core.presentation_studio.reload_rate_limited")
        before = len(rig.versions_of(scene_of(await rig.variant()).prefab.prefab_id))
        assert (await rig.edit({"style": "p{color:red}"}, actor="user")).status is S.RELOADED          # the user is never capped
        assert (await rig.edit({"style": "p{color:#00ff00}"}, actor="brain", scene_id=SID2)).status in (S.RELOADED, S.REPINNED)
        clock[0] += BRAIN_EDIT_WINDOW_S + 1                                                         # the window moves on
        assert (await rig.edit({"style": "p{color:blue}"}, actor="brain")).status is S.RELOADED
        assert before >= BRAIN_EDIT_LIMIT
    finally:
        await rig.close()
