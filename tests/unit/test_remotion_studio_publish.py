"""Remotion Studio -> variante : espace de travail et publication (handoff jarvis-remotion-native-studio-playback-fix, Slice 12).

Banc réel : `RemotionRig` (vrais `PrefabService`, Studio de présentations, porte d'édition de source, coalesceur, lecture ; seul le
compilateur est `FakeBuilder`, contrat d'erreur typée de `check_build`) + le VRAI `RemotionStudioRunner` sur disque + le vrai
`RemotionStudioService` (aucun processus : un espace matérialisé comme après une ouverture puis une fermeture). Prouve : publication
d'une modification en NOUVELLE version épinglée (la base intacte), ajout / suppression / asset, rebasage, conflit sur une base
périmée, base vue par la page différente, rien à publier, liens / jonctions / liens durs / fichiers de premier niveau / noms refusés
(jamais lus), import hors liste refusé AVANT la compilation sans aucun élargissement possible, compilation refusée sans rien publier,
l'ancien chemin de synchronisation qui ne remplace jamais en silence, retour arrière, survie à un redémarrage (services neufs sur la
même racine). L'arrêt brutal réel est dans `test_remotion_studio_publish_crash.py`. Contrat : `docs/presentation-studio.md` ›
*Remotion Studio round trip (Level 3, Slice 12)*.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from jarvis.adapters.remotion_studio_runner import EDITS_DIR, RemotionStudioRunner
from jarvis.core.remotion_studio_publish import VariantScenePublisher
from jarvis.core.remotion_studio_service import RemotionStudioService, prefab_source_provider
from jarvis.domain import remotion_studio as D
from jarvis.domain.prefab import PrefabRef
from jarvis.domain.remotion_studio import StudioError, StudioErrorCode as C, StudioPin, StudioState
from jarvis.domain.remotion_studio_workspace import WIDENING_REFUSAL, parse_publish
from tests.fakes.remotion_edit_rig import BASE, SCENE_TSX, SID, SID2, TITLE_TSX, RemotionRig

pytestmark = pytest.mark.asyncio

PIN = StudioPin(BASE, 1)
EDITED = SCENE_TSX.replace("#101820", "#203040")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class Bench:
    def __init__(self, rig: RemotionRig, runtime: Path) -> None:
        self.rig, self.runtime = rig, runtime
        self.runner = RemotionStudioRunner(lambda: runtime, which=lambda name: None)
        self.service = RemotionStudioService(self.runner, source_provider=prefab_source_provider(rig.prefabs),
                                             capability_status=lambda: "ready", diagnostics=rig.sink)
        self.service.bind_publisher(VariantScenePublisher(rig.studio, rig.reload))

    @property
    def work(self) -> Path:
        return self.runtime / "studio" / "work"

    async def materialize(self, pin: StudioPin = PIN) -> None:
        """L'espace tel qu'une ouverture puis une fermeture le laissent (`open` exige un vrai processus : prouvé en réel)."""

        source, props = await prefab_source_provider(self.rig.prefabs)(pin)
        self.runner.sync_work(D.plan_workspace(source, props))
        self.runner.write_state(StudioState(pin=pin).to_payload())

    def write(self, path: str, data: str | bytes) -> None:
        target = self.work.joinpath(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            target.write_bytes(data.encode("utf-8"))   # byte-exact: no newline translation on Windows
        else:
            target.write_bytes(data)

    def body(self, base: StudioPin = PIN, scene_id: str = SID) -> dict:
        return {"presentation_id": self.rig.pid, "variant_id": self.rig.vid, "scene_id": scene_id, "base": base.to_dict(),
                "confirm_publish": True}

    async def publish(self, **kwargs):
        return await self.service.publish(parse_publish(self.body(**kwargs)))


@pytest.fixture
async def bench(tmp_path):
    rig = await RemotionRig(tmp_path).open()
    runtime = tmp_path / "rt" / "local_capabilities" / "remotion" / "runtime"
    runtime.mkdir(parents=True)
    b = Bench(rig, runtime)
    await b.materialize()
    yield b
    await rig.close()


async def scene_pin(rig, scene_id=SID) -> PrefabRef:
    return next(scene.prefab for scene in (await rig.variant()).scenes if scene.scene_id == scene_id)


def own_ids(rig) -> list[str]:
    return [item for item in rig.prefabs_ids() if item.startswith("presentation-studio.")]


# ------------------------------------------------------------------ le chemin nominal

async def test_an_edit_in_the_workspace_is_published_as_a_new_pinned_version_and_the_base_stays_intact(bench):
    rig = bench.rig
    bench.write("src/Scene.tsx", EDITED)
    status = await bench.service.status()
    assert status["work_copy"]["modified_files"] == ["src/Scene.tsx"] and status["work_copy"]["unpublished"] == 1
    assert status["work_copy"]["base"] == PIN.to_dict() and status["status"] == "stopped", "unpublished edits are seen with Remotion Studio stopped"
    revision = (await rig.variant()).revision
    answer = await bench.publish()
    outcome = answer["publish"]
    assert outcome["status"] in ("reloaded", "repinned"), outcome
    assert outcome["previous"] == PIN.to_dict() and outcome["files"]["changed"] == ["src/Scene.tsx"]
    published = outcome["published"]
    assert published["prefab_id"].startswith("presentation-studio.p") and published["version"] == 1
    # the variant now pins the NEW version (a new revision); the base version is byte for byte what it was
    pin = await scene_pin(rig)
    assert (pin.prefab_id, pin.version) == (published["prefab_id"], 1) and (await rig.variant()).revision > revision
    assert (await rig.source_of(pin))["src/Scene.tsx"] == EDITED and (await rig.source_of(pin))["src/lib/Title.tsx"] == TITLE_TSX
    assert (await rig.source_of(PrefabRef(BASE, 1)))["src/Scene.tsx"] == SCENE_TSX
    assert len(rig.fake.calls) == 1, "the real gate built it once, before the publication"
    # the workspace is rebased on the published version: nothing left to publish, the file on disk untouched (HMR keeps running)
    view = answer["studio"]
    assert view["pin"] == published and view["work_copy"]["unpublished"] == 0 and view["work_copy"]["base"] == published
    assert (bench.work / "src" / "Scene.tsx").read_bytes().decode("utf-8") == EDITED
    assert scene_pin_sibling_untouched(await rig.variant())
    kinds = rig.sink.kinds()
    assert "remotion_studio.publish_started" in kinds and "remotion_studio.published" in kinds and "core.presentation_studio.reload_published" in kinds


def scene_pin_sibling_untouched(variant) -> bool:
    other = next(scene for scene in variant.scenes if scene.scene_id == SID2)
    return (other.prefab.prefab_id, other.prefab.version) == (BASE, 1)


async def test_added_removed_and_asset_files_publish_and_a_second_publish_builds_on_the_first(bench):
    rig = bench.rig
    bench.write("src/lib/theme.ts", 'export const ink = "#fff";\n')
    bench.write("public/dot.png", PNG)
    first = (await bench.publish())["publish"]
    assert first["files"]["added"] == ["public/dot.png", "src/lib/theme.ts"]
    published = StudioPin(first["published"]["prefab_id"], first["published"]["version"])
    detail = await rig.prefabs.get(published.prefab_id, published.version)
    assert list(detail.entry.manifest.source.modules) == ["src/Scene.tsx", "src/lib/Title.tsx", "src/lib/theme.ts"]
    assert list(detail.entry.manifest.source.assets) == ["public/dot.png"]
    (bench.work / "src" / "lib" / "theme.ts").unlink()
    bench.write("src/Scene.tsx", EDITED)
    second = (await bench.publish(base=published))["publish"]
    assert second["files"]["removed"] == ["src/lib/theme.ts"] and second["files"]["changed"] == ["src/Scene.tsx"]
    assert second["previous"] == published.to_dict() and second["published"]["version"] == published.version + 1
    source = await rig.source_of(await scene_pin(rig))
    assert "src/lib/theme.ts" not in source and source["src/Scene.tsx"] == EDITED


async def test_edits_made_during_the_publication_stay_unpublished_after_the_rebase(bench):
    rig = bench.rig
    bench.write("src/Scene.tsx", EDITED)
    real = rig.fake.check_build

    async def slow_build(source):
        bench.write("src/lib/Title.tsx", TITLE_TSX + "// typed while the build ran\n")
        return await real(source)

    rig.fake.check_build = slow_build
    answer = await bench.publish()
    assert answer["studio"]["work_copy"]["modified_files"] == ["src/lib/Title.tsx"], "a later edit is never folded into the base"
    assert (await rig.source_of(await scene_pin(rig)))["src/lib/Title.tsx"] == TITLE_TSX, "nor into the published version"


# ------------------------------------------------------------------ refus : rien n'est publié

async def refused(bench, code: C, **kwargs) -> StudioError:
    before_ids, before_pin = own_ids(bench.rig), await scene_pin(bench.rig)
    with pytest.raises(StudioError) as caught:
        await bench.publish(**kwargs)
    assert caught.value.code is code, (caught.value.code, caught.value.detail)
    assert own_ids(bench.rig) == before_ids and await scene_pin(bench.rig) == before_pin, "nothing published, nothing pinned"
    return caught.value


async def test_nothing_to_publish_is_said(bench):
    error = await refused(bench, C.PUBLISH_NOTHING)
    assert error.http_status == 409


async def test_a_stale_base_is_a_conflict_and_the_workspace_is_kept(bench):
    rig = bench.rig
    bench.write("src/Scene.tsx", EDITED)
    moved = await rig.edit({"sources": {"src/lib/Title.tsx": TITLE_TSX + "// another writer\n"}})
    assert moved.status.value in ("reloaded", "repinned")
    error = await refused(bench, C.PUBLISH_CONFLICT)
    assert error.http_status == 409 and error.extra["base"] == PIN.to_dict()
    assert error.extra["current"] == {"prefab_id": moved.prefab.prefab_id, "version": moved.prefab.version}
    assert (bench.work / "src" / "Scene.tsx").read_bytes().decode("utf-8") == EDITED, "the user's work is never touched"
    assert (await bench.service.status())["work_copy"]["unpublished"] == 1
    assert "remotion_studio.publish_conflict" in rig.sink.kinds()


async def test_a_concurrent_write_between_the_check_and_the_door_is_a_conflict_too(bench):
    rig = bench.rig
    bench.write("src/Scene.tsx", EDITED)
    publisher = bench.service._publisher
    real_current = publisher.current

    async def current_then_someone_writes(*args):
        found = await real_current(*args)
        await rig.edit({"sources": {"src/lib/Title.tsx": TITLE_TSX + "// raced\n"}})
        return found

    publisher.current = current_then_someone_writes
    error = await refused_after_race(bench)
    assert error.code is C.PUBLISH_CONFLICT and error.extra["publish_status"] == "stale" and error.http_status == 409


async def refused_after_race(bench) -> StudioError:
    with pytest.raises(StudioError) as caught:
        await bench.publish()
    return caught.value


async def test_a_base_the_page_did_not_see_is_refused(bench):
    bench.write("src/Scene.tsx", EDITED)
    error = await refused(bench, C.PUBLISH_BASE_MISMATCH, base=StudioPin(BASE, 2))
    assert error.extra["base"] == PIN.to_dict()


async def test_a_restricted_import_is_refused_before_any_build_and_no_widening_exists(bench):
    rig = bench.rig
    for spec in ("zod", "fs", "node:child_process", "@remotion/renderer"):
        bench.write("src/Scene.tsx", f'import x from "{spec}";\n' + SCENE_TSX)
        error = await refused(bench, C.PUBLISH_IMPORT_REFUSED)
        assert error.http_status == 422 and any(item.startswith(spec) for item in error.extra["imports"]), spec
        assert "HV-RFX-12-01" in error.detail and rig.fake.calls == [], "refused BEFORE the build"
    # no approval path: the publish body is exact, nothing in it (or anywhere) widens the list
    with pytest.raises(StudioError) as caught:
        parse_publish({**bench.body(), "allowed_imports": ["zod"]})
    assert caught.value.code is C.INVALID
    assert "react" in WIDENING_REFUSAL and "remotion" in WIDENING_REFUSAL


async def test_a_source_that_does_not_compile_publishes_nothing_and_says_where(bench):
    bench.write("src/Scene.tsx", SCENE_TSX.replace("export default", "const bad = SYNTAX_ERROR\nexport default"))
    error = await refused(bench, C.PUBLISH_REFUSED)
    assert error.http_status == 422 and error.extra["publish_code"] == "presentation_studio_source_build_failed"
    assert error.extra["diagnostics"][0]["file"] == "src/Scene.tsx" and error.extra["base"] == PIN.to_dict()
    assert (await bench.service.status())["work_copy"]["unpublished"] == 1, "the workspace and its base are untouched"


async def test_an_unknown_target_keeps_the_variant_code(bench):
    bench.write("src/Scene.tsx", EDITED)
    error = await refused(bench, C.PUBLISH_REFUSED, scene_id="pss_000000000000")
    assert error.extra["publish_code"].startswith("presentation_studio_") and error.http_status in (400, 404)


# ------------------------------------------------------------------ frontière du disque (adversarial)

def outside_secret(bench) -> Path:
    secret = bench.runtime.parent.parent.parent / "outside-secret.ts"
    secret.write_text('export const token = "TOP-SECRET";\n', encoding="utf-8")
    return secret


def library_holds(rig, needle: bytes) -> bool:
    from jarvis.adapters.file_prefab_library import LIBRARY_DIR
    return any(needle in path.read_bytes() for path in (rig.data / LIBRARY_DIR).rglob("*") if path.is_file())


async def test_a_symlinked_file_is_refused_and_its_target_is_never_read(bench):
    secret = outside_secret(bench)
    try:
        os.symlink(secret, bench.work / "src" / "evil.ts")
    except OSError:
        pytest.skip("this Windows account cannot create symbolic links (junctions and hard links are tested below)")
    error = await refused(bench, C.PUBLISH_INVALID_FILE)
    assert "src/evil.ts" in error.detail and not library_holds(bench.rig, b"TOP-SECRET")


async def test_a_junction_folder_escaping_the_workspace_is_refused(bench):
    import _winapi
    outside = bench.runtime.parent.parent.parent / "outside-dir"
    outside.mkdir()
    (outside / "Leak.tsx").write_text('export const leak = "TOP-SECRET";\n', encoding="utf-8")
    _winapi.CreateJunction(str(outside), str(bench.work / "src" / "lib2"))
    error = await refused(bench, C.PUBLISH_INVALID_FILE)
    assert "src/lib2/" in error.detail and not library_holds(bench.rig, b"TOP-SECRET")
    assert (outside / "Leak.tsx").exists(), "the junction target is never touched"


async def test_a_hard_link_to_a_file_outside_is_refused(bench):
    secret = outside_secret(bench)
    os.link(secret, bench.work / "src" / "hard.ts")
    error = await refused(bench, C.PUBLISH_INVALID_FILE)
    assert "src/hard.ts" in error.detail and not library_holds(bench.rig, b"TOP-SECRET")


async def test_a_replaced_source_folder_and_a_file_turned_into_a_link_are_refused(bench):
    import _winapi
    outside = bench.runtime.parent.parent.parent / "outside-public"
    outside.mkdir()
    (outside / "x.png").write_bytes(PNG)
    import shutil
    shutil.rmtree(bench.work / "public", ignore_errors=True)
    _winapi.CreateJunction(str(outside), str(bench.work / "public"))
    error = await refused(bench, C.PUBLISH_INVALID_FILE)
    assert "public/" in error.detail


@pytest.mark.parametrize("path,data", [
    ("remotion.config.ts", "export {};\n"),               # a top-level file Remotion Studio would read: never a scene source
    (D.WORK_ROOT_FILE, "// edited generated root\n"),      # the generated root (composition comes from the manifest)
    ("src/a b.tsx", "export {};\n"),                       # a name the source path rule refuses
    ("src/style.css", "body{}\n"),                         # CSS is not a scene module
    ("src/.hidden.ts", "export {};\n"),                    # hidden file
    ("src/bin.ts", b"\xff\xfe\x00"),                       # not UTF-8 text
])
async def test_unpublishable_workspace_files_are_named_and_nothing_is_published(bench, path, data):
    if path == D.WORK_ROOT_FILE:
        os.chmod(bench.work / path, 0o666)
    bench.write(path, data)
    error = await refused(bench, C.PUBLISH_INVALID_FILE)
    assert path.split("/")[-1][:20] in error.detail and error.http_status == 422


async def test_hostile_relative_paths_never_reach_the_disk(bench):
    for bad in ("../outside.ts", "src/../../x.ts", "C:/x.ts", "src\\x.ts", "/abs.ts", "src/x\x00.ts"):
        with pytest.raises(StudioError):
            bench.runner.rebase_work({bad: b"x"})
    assert not (bench.runtime / "studio" / "outside.ts").exists()


# ------------------------------------------------------------------ l'ancien chemin ne remplace jamais en silence

async def test_opening_another_version_with_unpublished_edits_is_refused_and_nothing_moves(bench):
    bench.write("src/Scene.tsx", EDITED)
    other = await bench.rig.prefabs.save(_candidate_v2(bench), actor="user")
    with pytest.raises(StudioError) as caught:
        await bench.service.open(StudioPin(BASE, other.version), acknowledged=True)
    assert caught.value.code is C.UNPUBLISHED_EDITS and caught.value.extra["files"] == ["src/Scene.tsx"]
    assert caught.value.extra["base"] == PIN.to_dict()
    assert (bench.work / "src" / "Scene.tsx").read_bytes().decode("utf-8") == EDITED
    view = await bench.service.status()
    assert view["pin"] == PIN.to_dict() and view["status"] == "stopped" and view["work_copy"]["unpublished"] == 1
    assert not (bench.runtime.parent / EDITS_DIR).exists(), "no backup was even needed: nothing was replaced"


def _candidate_v2(bench):
    from tests.fakes.remotion_scene import ENGINE, PROPS_SCHEMA, SAMPLE, scene_candidate
    return scene_candidate(BASE, engine=ENGINE, title="Base Remotion", files={"src/Scene.tsx": EDITED, "src/lib/Title.tsx": TITLE_TSX},
                           props=PROPS_SCHEMA, sample=SAMPLE)


async def test_a_capability_change_copies_unpublished_files_outside_runtime_first(bench):
    bench.write("src/Scene.tsx", EDITED)
    bench.service.stop_for_capability_change()   # no loop bound yet: the synchronous path (as when Core never served the Studio)
    copies = list((bench.runtime.parent / EDITS_DIR).glob("*/src/Scene.tsx"))
    assert len(copies) == 1 and copies[0].read_bytes().decode("utf-8") == EDITED
    assert not str(copies[0]).startswith(str(bench.runtime)), "outside runtime/: an uninstall never takes it"
    assert "remotion_studio.unpublished_saved" in bench.rig.sink.kinds()


# ------------------------------------------------------------------ retour arrière, redémarrage

async def test_the_previous_version_can_be_reactivated_and_stays_intact(bench):
    rig = bench.rig
    bench.write("src/Scene.tsx", EDITED)
    outcome = (await bench.publish())["publish"]
    published = PrefabRef(outcome["published"]["prefab_id"], outcome["published"]["version"])
    revision = (await rig.variant()).revision
    back = await rig.reload.apply_source_edit(rig.pid, rig.vid, {"actor": "user", "basis": {"variant_revision": revision}, "scene_id": SID,
                                                                  "files": {"restore_version": {"id": BASE, "version": 1}}})
    assert back.status.value in ("reloaded", "repinned"), back.to_dict()
    pin = await scene_pin(rig)
    assert pin.version == published.version + 1 and (await rig.source_of(pin))["src/Scene.tsx"] == SCENE_TSX
    assert (await rig.source_of(published))["src/Scene.tsx"] == EDITED, "the published version is never rewritten either"
    # the workspace (based on the published version) is now another version than the scene: a publish from it is a conflict
    bench.write("src/lib/Title.tsx", TITLE_TSX + "// more\n")
    error = await refused(bench, C.PUBLISH_CONFLICT, base=StudioPin(published.prefab_id, published.version))
    assert error.extra["current"] == {"prefab_id": pin.prefab_id, "version": pin.version}


async def test_a_fresh_core_on_the_same_data_root_keeps_unpublished_edits_then_publishes_them(tmp_path):
    first = await RemotionRig(tmp_path).open(show=False)
    runtime = tmp_path / "rt" / "local_capabilities" / "remotion" / "runtime"
    runtime.mkdir(parents=True)
    bench = Bench(first, runtime)
    await bench.materialize()
    bench.write("src/Scene.tsx", EDITED)
    await first.close()
    # a NEW life: new prefab service, new presentation studio, new reload, new Studio service, same folders
    second = await RemotionRig(tmp_path, existing=True).open()
    try:
        again = Bench(second, runtime)
        view = await again.service.reconcile()
        assert view["status"] == "stopped" and view["pin"] == PIN.to_dict()
        status = await again.service.status()
        assert status["work_copy"]["modified_files"] == ["src/Scene.tsx"], "unpublished edits survive a Core restart"
        outcome = (await again.publish())["publish"]
        pin = await scene_pin(second)
        assert (pin.prefab_id, pin.version) == (outcome["published"]["prefab_id"], outcome["published"]["version"])
    finally:
        await second.close()
    # and a THIRD life reads the published version from disk: what Variants shows after a restart
    third = await RemotionRig(tmp_path, existing=True).open()
    try:
        pin = await scene_pin(third)
        assert pin.prefab_id.startswith("presentation-studio.") and (await third.source_of(pin))["src/Scene.tsx"] == EDITED
        state = json.loads((runtime / "studio" / "state.json").read_text(encoding="utf-8"))
        assert state["pin"] == {"prefab_id": pin.prefab_id, "version": pin.version}, "the workspace base followed the publication"
    finally:
        await third.close()


async def test_publishing_without_a_presentation_studio_is_a_typed_503(tmp_path):
    runtime = tmp_path / "runtime"
    service = RemotionStudioService(RemotionStudioRunner(lambda: runtime, which=lambda n: None),
                                    source_provider=lambda pin: None, capability_status=lambda: "ready")
    with pytest.raises(StudioError) as caught:
        await service.publish(parse_publish({"presentation_id": "prs_1", "variant_id": "var_1", "scene_id": "pss_1",
                                             "base": PIN.to_dict(), "confirm_publish": True}))
    assert caught.value.code is C.PUBLISH_UNAVAILABLE and caught.value.http_status == 503


async def test_the_publish_body_is_exact_and_needs_the_confirmation():
    good = {"presentation_id": "prs_1", "variant_id": "var_1", "scene_id": "pss_1", "base": PIN.to_dict(), "confirm_publish": True}
    assert parse_publish(good).base == PIN
    for bad, code in (({**good, "confirm_publish": False}, C.PUBLISH_CONFIRM_REQUIRED), ({**good, "confirm_publish": "yes"}, C.PUBLISH_CONFIRM_REQUIRED),
                      ({k: v for k, v in good.items() if k != "confirm_publish"}, C.INVALID), ({**good, "actor": "brain"}, C.INVALID),
                      ({**good, "scene_id": "../x"}, C.INVALID), ({**good, "base": {"prefab_id": BASE}}, C.INVALID), ([], C.INVALID)):
        with pytest.raises(StudioError) as caught:
            parse_publish(bad)
        assert caught.value.code is code, bad
    assert base64.b64encode(b"x")  # (keeps the import list honest for the asset path above)
