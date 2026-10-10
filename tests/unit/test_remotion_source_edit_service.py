"""Edition de source d'une scene REMOTION contre de VRAIS services (handoff jarvis-remotion-presentation-integration, Slice 14).

Le banc du rechargement a chaud (magasin de fichiers, `PrefabService`, `SceneService` SQLite, coalesceur, stage, lecture reelle),
avec des scenes dont le prefab est une source Remotion. Seul le navigateur (`FakeHost`) et le compilateur (`FakeBuilder`, meme
contrat d'erreur typee que `RemotionPlayerService.check_build`) sont simules ; la compilation reelle est dans
`test_remotion_source_edit_real.py`. Prouve : une bonne edition ne recharge que la scene visee, une source qui ne compile pas
n'est JAMAIS publiee (erreur typee avec fichier:ligne:colonne, la version precedente continue de jouer, jamais un autre moteur),
un montage rate revient en arriere, les controles et ancres sont reportes par nom, annuler / retablir republie une version, les
editions d'une meme scene sont serialisees. Contrat : `docs/presentation-studio.md` > *Hot reload contract* > *Remotion
sources*.
"""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from jarvis.domain.prefab import PrefabRef
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_reload import ReloadStatus as S
from tests.fakes.remotion_edit_rig import (
    BASE, EDITED_TITLE, SCENE_TSX, SID, SID2, TITLE_TSX, FakeBuilder, RemotionRig, remotion_scene,
)

pytestmark = pytest.mark.asyncio

NEW_SCENE = SCENE_TSX.replace("#101820", "#202830")
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n-fake").decode("ascii")


@pytest.fixture
async def rig(tmp_path):
    opened = await RemotionRig(tmp_path).open()
    yield opened
    await opened.close()


def scene_of(variant, scene_id=SID):
    return next(item for item in variant.scenes if item.scene_id == scene_id)


def own_versions(rig: RemotionRig, result) -> list[int]:
    return rig.versions_of(result.prefab.prefab_id)


# ------------------------------------------------------------------ une bonne edition

async def test_a_good_tsx_edit_builds_publishes_and_reloads_only_that_scene(rig):
    other_before = scene_of(await rig.variant(), SID2).to_dict()
    result = await rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}})
    assert result.status is S.RELOADED and result.mounted is True and result.http_status == 200, result.to_dict()
    after = await rig.variant()
    scene = scene_of(after)
    assert scene.prefab.prefab_id.startswith("presentation-studio.p") and scene.prefab.version == 1
    assert scene.source_revision == 1 and scene.last_valid_pin is None and result.previous == PrefabRef(BASE, 1)
    assert scene_of(after, SID2).to_dict() == other_before, "the sibling scene is untouched byte for byte"
    block = await rig.stage_block()
    assert (block.prefab_id, block.version) == (scene.prefab.prefab_id, 1), "the stage window was re-pinned: that is the swap"
    # the new version carries the edit and every file the request did not name
    published = await rig.source_of(scene.prefab)
    assert published["src/Scene.tsx"] == NEW_SCENE and published["src/lib/Title.tsx"] == TITLE_TSX
    # the build ran once, on the composed source, BEFORE the publication
    assert len(rig.fake.calls) == 1 and rig.fake.calls[0]["modules"]["src/Scene.tsx"] == NEW_SCENE
    assert (await rig.source_of(PrefabRef(BASE, 1)))["src/Scene.tsx"] == SCENE_TSX, "the original version is never rewritten"
    assert "core.presentation_studio.reload_built" in rig.sink.kinds()


async def test_files_are_added_replaced_and_deleted_and_the_manifest_lists_follow(rig):
    extra = 'export const palette = {ink: "#fff"};\n'
    result = await rig.edit({"sources": {"src/lib/theme.ts": extra, "src/lib/Title.tsx": EDITED_TITLE},
                             "assets": {"public/dot.png": PNG}})
    assert result.status is S.RELOADED, result.to_dict()
    detail = await rig.prefabs.get(result.prefab.prefab_id, result.prefab.version)
    block = detail.entry.manifest.source
    assert list(block.modules) == ["src/Scene.tsx", "src/lib/Title.tsx", "src/lib/theme.ts"] and list(block.assets) == ["public/dot.png"]
    second = await rig.edit({"sources": {"src/lib/theme.ts": None}, "assets": {"public/dot.png": None}})
    assert second.status is S.RELOADED, second.to_dict()
    detail = await rig.prefabs.get(second.prefab.prefab_id, second.prefab.version)
    assert list(detail.entry.manifest.source.modules) == ["src/Scene.tsx", "src/lib/Title.tsx"] and not detail.entry.manifest.source.assets
    assert (await rig.source_of(second.prefab))["src/lib/Title.tsx"] == EDITED_TITLE, "the second edit started from the first"


async def test_controls_anchors_and_values_are_carried_over_by_name(rig):
    before = scene_of(await rig.variant())
    result = await rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}})
    scene = scene_of(await rig.variant())
    assert result.status is S.RELOADED and result.reset is None
    assert scene.props == before.props and [c.control_id for c in scene.controls] == ["headline", "accent"]
    assert [(a.anchor_id, a.control_id) for a in scene.anchors] == [("reveal", "headline")], "the score anchor keeps its control"


async def test_the_props_contract_must_still_fit_the_controls_or_the_reset_is_named(rig):
    base = (await rig.prefabs.get(BASE, 1)).entry.manifest.raw
    manifest = json.loads(json.dumps(base))
    del manifest["inputs"]["props"]["properties"]["accent"]
    del manifest["sample"]["props"]["accent"]
    refused = await rig.edit({"manifest": manifest, "sources": {"src/Scene.tsx": NEW_SCENE}})
    assert refused.status is S.REFUSED_VALIDATION and refused.code == C.SCENE_INCOMPATIBLE.value, refused.to_dict()
    assert "accent" in refused.message and rig.fake.calls == [], "refused before the (costly) build"
    assert rig.versions_of(f"presentation-studio.p{rig.pid[4:16]}.s{SID[4:16]}") == [], "nothing was published"
    allowed = await rig.edit({"manifest": manifest, "sources": {"src/Scene.tsx": NEW_SCENE}}, allow_state_reset=True)
    assert allowed.status is S.RELOADED_STATE_RESET, allowed.to_dict()
    assert "accent" in allowed.reset.props and "accent" in allowed.reset.controls
    scene = scene_of(await rig.variant())
    assert [c.control_id for c in scene.controls] == ["headline"] and scene.anchors[0].control_id == "headline"


# ------------------------------------------------------------------ une source qui ne compile pas

async def test_a_source_that_does_not_compile_is_refused_with_file_line_column_and_nothing_is_published(rig):
    scene_before = scene_of(await rig.variant())
    block_before = await rig.stage_block()
    broken = SCENE_TSX.replace("export default", "const bad = SYNTAX_ERROR\nexport default")
    result = await rig.edit({"sources": {"src/Scene.tsx": broken}})
    wire = result.to_dict()
    assert result.status is S.REFUSED_VALIDATION and result.code == C.SOURCE_BUILD_FAILED.value and result.http_status == 422
    assert wire["diagnostics"] == [{"file": "src/Scene.tsx", "line": 5, "column": 12, "text": 'Expected ";" but found "SYNTAX_ERROR"'}]
    assert wire["error"]["code"] == "presentation_studio_source_build_failed" and wire["error"]["diagnostics"] == wire["diagnostics"]
    assert "src/Scene.tsx:5:12" in result.message and "compile_source_error" in result.message, "the band text carries the position"
    # nothing was published, pinned or patched: the previous version keeps playing, and it is still the Remotion one
    after = await rig.variant()
    assert scene_of(after).to_dict() == scene_before.to_dict() and after.revision == (await rig.variant()).revision
    assert (await rig.stage_block()) == block_before
    assert not any(p.startswith("presentation-studio.") for p in rig.prefabs_ids()), "no inert bad version in the library"
    assert [lvl for kind, lvl, _ in rig.sink.rows if kind == "core.presentation_studio.reload_build_refused"] == ["warning"]
    # the next, valid edit goes through: the refusal left no draft behind
    good = await rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}})
    assert good.status is S.RELOADED and (await rig.source_of(good.prefab))["src/Scene.tsx"] == NEW_SCENE


async def test_an_unavailable_engine_is_a_typed_refusal_never_another_engine(rig):
    rig.fake.unavailable = True
    result = await rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}})
    assert result.status is S.REFUSED_VALIDATION and result.code == C.ENGINE_UNAVAILABLE.value, result.to_dict()
    assert scene_of(await rig.variant()).prefab == PrefabRef(BASE, 1) and not any(p.startswith("presentation-studio.") for p in rig.prefabs_ids())


async def test_without_any_remotion_adapter_the_edit_is_refused_not_published(tmp_path):
    rig = await RemotionRig(tmp_path, builder=None).open()
    try:
        result = await rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}})
        assert result.status is S.REFUSED_VALIDATION and result.code == C.ENGINE_UNAVAILABLE.value
        assert "no Remotion adapter" in result.message and scene_of(await rig.variant()).prefab == PrefabRef(BASE, 1)
    finally:
        await rig.close()


@pytest.mark.parametrize(("files", "needle"), [
    ({"sources": {"src/../x.ts": "export {}"}}, "traversal"),
    ({"sources": {"src/package.json": "{}"}}, "shared"),
    ({"sources": {"src/style.css": "a{}"}}, "extension"),
    ({"sources": {"src/lib/Title.tsx": "const r = window.fetch('/x')"}}, "realm_access"),
    ({"sources": {"src/lib/Title.tsx": None, "src/lib/none.ts": None}}, "does not have"),
    ({"assets": {"public/a.png": "not base64!!"}}, "base64"),
    ({"assets": {"public/a.exe": PNG}}, "extension"),
], ids=["traversal", "package", "css", "browser-api", "delete-absent", "bad-base64", "bad-extension"])
async def test_path_rules_isolation_guards_and_bounds_refuse_before_the_build(rig, files, needle):
    result = await rig.edit(files)
    assert result.status is S.REFUSED_VALIDATION and result.code == C.SOURCE_INVALID.value, result.to_dict()
    assert needle in result.message, result.message
    assert rig.fake.calls == [], "the build is never asked about a source the library already refuses"
    assert scene_of(await rig.variant()).prefab == PrefabRef(BASE, 1)


@pytest.mark.parametrize("frames", [0, 10_000_000])
async def test_an_invalid_frame_count_is_refused_by_the_manifest_not_by_the_player(rig, frames):
    manifest = json.loads(json.dumps((await rig.prefabs.get(BASE, 1)).entry.manifest.raw))
    manifest["source"]["composition"]["duration_in_frames"] = frames
    result = await rig.edit({"manifest": manifest})
    assert result.status is S.REFUSED_VALIDATION and result.code == C.SOURCE_INVALID.value and "duration_in_frames" in result.message
    assert rig.fake.calls == []


async def test_a_slidecar_edit_of_a_remotion_scene_and_the_reverse_are_refused_with_the_right_keys(rig):
    result = await rig.edit({"style": "p{color:red}"})
    assert result.status is S.REFUSED_VALIDATION and "Remotion scene" in result.message and "files.sources" in result.message
    with pytest.raises(PresentationStudioError) as caught:
        await rig.edit({"style": "p{}", "sources": {"src/Scene.tsx": NEW_SCENE}})
    assert caught.value.code is C.INVALID_PRESENTATION or "not both" in caught.value.message


# ------------------------------------------------------------------ un montage qui echoue : retour arriere

async def test_a_scene_that_throws_at_mount_rolls_back_to_the_last_valid_version(tmp_path):
    rig = await RemotionRig(tmp_path).open(host=lambda pin: ({"outcome": "failed", "reason": "frame", "message": "ReferenceError: boom"}
                                                              if pin.prefab_id.startswith("presentation-studio.") else {"outcome": "mounted"}))
    try:
        before = scene_of(await rig.variant())
        result = await rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}})
        assert result.status is S.ROLLED_BACK and result.code == C.MOUNT_FAILED.value and result.http_status == 409, result.to_dict()
        scene = scene_of(await rig.variant())
        assert scene.prefab == before.prefab == PrefabRef(BASE, 1) and scene.source_revision > before.source_revision
        assert scene.props == before.props and scene.controls == before.controls
        block = await rig.stage_block()
        assert (block.prefab_id, block.version) == (BASE, 1), "the window shows the last valid version again"
        assert result.published is not None and result.published.prefab_id.startswith("presentation-studio."), "the failed one is inert"
    finally:
        await rig.close()


# ------------------------------------------------------------------ annuler / retablir

async def test_undo_and_redo_republish_a_version_as_a_new_immutable_revision(rig):
    first = await rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}})
    second = await rig.edit({"sources": {"src/lib/Title.tsx": EDITED_TITLE}})
    assert (first.prefab.version, second.prefab.version) == (1, 2)
    undo = await rig.edit({"restore_version": second.previous.to_dict()})
    assert undo.status is S.RELOADED and undo.prefab.version == 3, undo.to_dict()
    assert await rig.source_of(undo.prefab) == await rig.source_of(first.prefab), "version 3 has the content of version 1"
    assert own_versions(rig, undo) == [1, 2, 3], "history is linear and immutable: nothing was rewritten or deleted"
    redo = await rig.edit({"restore_version": second.prefab.to_dict()})
    assert redo.status is S.RELOADED and await rig.source_of(redo.prefab) == await rig.source_of(second.prefab)
    # undo of the FIRST edit goes back to the version the scene was forked from, which is not the scene's own source
    base_undo = await rig.edit({"restore_version": first.previous.to_dict()})
    assert base_undo.status is S.RELOADED and await rig.source_of(base_undo.prefab) == await rig.source_of(PrefabRef(BASE, 1))
    assert scene_of(await rig.variant()).prefab == base_undo.prefab and (await rig.stage_block()).version == base_undo.prefab.version


async def test_only_versions_the_scene_had_can_be_restored(rig):
    foreign = await rig.edit({"restore_version": {"id": "jarvis.counter", "version": 1}})
    assert foreign.status is S.REFUSED_VALIDATION and "not a version this scene had" in foreign.message
    first = await rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}})
    missing = await rig.edit({"restore_version": {"id": first.prefab.prefab_id, "version": 9}})
    assert missing.status is S.REFUSED_VALIDATION and "cannot be restored" in missing.message


# ------------------------------------------------------------------ concurrence

async def test_two_edits_of_the_same_basis_one_wins_one_is_stale(tmp_path):
    rig = await RemotionRig(tmp_path, builder=FakeBuilder(delay_s=0.05)).open()
    try:
        revision = (await rig.variant()).revision
        a, b = await asyncio.gather(
            rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}}, revision=revision),
            rig.edit({"sources": {"src/lib/Title.tsx": EDITED_TITLE}}, revision=revision))
        assert sorted([a.status.value, b.status.value]) == ["reloaded", "stale"], (a.status, a.message, b.status, b.message)
        assert rig.fake.peak == 1, "builds of one scene are serialized (one compose lock per source id)"
        won, lost = (a, b) if a.status is S.RELOADED else (b, a)
        assert scene_of(await rig.variant()).prefab == won.prefab, "the winner's version is the pin"
        assert lost.published is not None and lost.published != won.prefab, "the loser's version stays unpinned, immutable and harmless"
        assert lost.prefab == PrefabRef(BASE, 1) or lost.prefab == won.prefab
    finally:
        await rig.close()


async def test_a_burst_of_retouches_composes_on_the_draft_and_publishes_one_version(tmp_path):
    rig = await RemotionRig(tmp_path, quiet_s=0.2, max_wait_s=1.0).open()
    try:
        revision = (await rig.variant()).revision
        first, second = await asyncio.gather(
            rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}}, revision=revision),
            rig.edit({"sources": {"src/lib/Title.tsx": EDITED_TITLE}}, revision=revision))
        merged = [r for r in (first, second) if r.merged]
        assert first.prefab == second.prefab and len(merged) == 1 and {first.status, second.status} == {S.RELOADED}
        assert own_versions(rig, first) == [1], "a burst is ONE version"
        source = await rig.source_of(first.prefab)
        assert source["src/Scene.tsx"] == NEW_SCENE and source["src/lib/Title.tsx"] == EDITED_TITLE, "no retouch of the burst is lost"
        assert len(rig.fake.calls) == 2, "each retouch was built on the one before it"
    finally:
        await rig.close()


async def test_a_failed_retouch_inside_a_burst_leaves_the_draft_of_the_good_ones(tmp_path):
    rig = await RemotionRig(tmp_path, quiet_s=0.2, max_wait_s=1.0).open()
    try:
        revision = (await rig.variant()).revision
        good, bad = await asyncio.gather(
            rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}}, revision=revision),
            rig.edit({"sources": {"src/lib/Title.tsx": "SYNTAX_ERROR"}}, revision=revision))
        assert bad.code == C.SOURCE_BUILD_FAILED.value and good.status is S.RELOADED
        source = await rig.source_of(good.prefab)
        assert source["src/Scene.tsx"] == NEW_SCENE and source["src/lib/Title.tsx"] == TITLE_TSX, "the broken retouch left no trace"
    finally:
        await rig.close()


# ------------------------------------------------------------------ lecture de la source (agent) et redemarrage

async def test_the_agent_reads_the_source_before_editing(rig):
    body = await rig.reload.read_source(rig.pid, rig.vid, SID)
    assert body["engine"] == "remotion" and body["sources"]["src/Scene.tsx"] == SCENE_TSX and body["prefab"] == {"id": BASE, "version": 1}
    assert body["basis"] == {"variant_revision": (await rig.variant()).revision} and body["assets"] == {}
    edited = await rig.edit({"assets": {"public/dot.png": PNG}})
    again = await rig.reload.read_source(rig.pid, rig.vid, SID)
    assert again["assets"]["public/dot.png"]["bytes"] == len(base64.b64decode(PNG)) and "bytes" not in json.dumps(again["sources"])
    assert again["prefab"] == edited.prefab.to_dict() and again["source_revision"] == 1


async def test_a_restart_after_an_unconfirmed_remotion_edit_keeps_the_fallback_and_resolves_on_the_report(tmp_path):
    rig = await RemotionRig(tmp_path, mount_deadline_s=0.2).open(host=lambda pin: None)   # a host that never answers
    result = await rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}})
    assert result.status is S.PENDING_MOUNT, result.to_dict()
    pin = scene_of(await rig.variant()).prefab
    await rig.close()
    reopened = await RemotionRig(tmp_path, existing=True, mount_deadline_s=0.2).open(host=False, show=False)
    try:
        scene = scene_of(await reopened.variant())
        assert scene.prefab == pin and scene.last_valid_pin == PrefabRef(BASE, 1), "the pin and its fallback were written together"
        assert (await reopened.source_of(pin))["src/Scene.tsx"] == NEW_SCENE, "the source came back byte for byte"
        assert [e.pin for e in reopened.reload.pending_scenes()] == [pin]
        answer = await reopened.reload.handle_mount_report({"object_id": "studio-stage-xx", "prefab": pin.to_dict(), "outcome": "failed",
                                                            "reason": "frame", "message": "boom"})
        assert answer["resolved"] == 1
        assert scene_of(await reopened.variant()).prefab == PrefabRef(BASE, 1), "the late failure rolled back to the last valid version"
    finally:
        await reopened.close()


async def test_undo_works_while_the_previous_edit_is_still_unconfirmed(tmp_path):
    """No stage window shows the scene (`repinned`): the fallback pin is still written when the undo composes on an older version."""

    rig = await RemotionRig(tmp_path).open(host=False, show=False)
    try:
        first = await rig.edit({"sources": {"src/Scene.tsx": NEW_SCENE}})
        second = await rig.edit({"sources": {"src/lib/Title.tsx": EDITED_TITLE}})
        assert (first.status, second.status) == (S.REPINNED, S.REPINNED)
        undo = await rig.edit({"restore_version": second.previous.to_dict()})
        assert undo.status is S.REPINNED and undo.prefab.version == 3, undo.to_dict()
        assert await rig.source_of(undo.prefab) == await rig.source_of(first.prefab)
        assert scene_of(await rig.variant()).last_valid_pin == second.prefab
    finally:
        await rig.close()
