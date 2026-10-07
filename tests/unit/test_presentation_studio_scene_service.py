"""Scenes du Studio contre le vrai `PrefabService` (jarvis-interactive-presentation-studio, Slice 04).

Magasin de fichiers et catalogue de prefabs reels sous `tmp_path` (fixture `test.counter` installee comme `lab.counter`) :
integrite des references (pin existant, altere, version inconnue), compatibilite des controles et des valeurs, introspection
stable, aucune ecriture quand une scene est refusee, scenes inchangees non reverifiees, ancien fichier v1. Contrat :
`docs/presentation-studio.md` > *Scene and control contract*.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.prefab_service import PrefabService
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.presentation_studio_scene import StudioScene
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from tests.fakes.prefabs import install_version

SID = "pss_0000000000a1"
SID2 = "pss_0000000000a2"
CONTROLS = [
    {"control_id": "headline", "path": "props.label", "label": "Titre", "group": "content", "meaning": "Texte principal"},
    {"control_id": "start_count", "path": "data.count", "label": "Valeur", "group": "content",
     "bounds": {"min": 0, "max": 100}, "default": 10},
    {"control_id": "density", "path": "props.mode", "label": "Densite", "group": "layout",
     "bounds": {"choices": ["compact"]}},
]


def scene_body(scene_id=SID, prefab=("lab.counter", 1), **changes) -> dict:
    return {"scene_id": scene_id, "prefab": {"id": prefab[0], "version": prefab[1]}, "title": "Ouverture",
            "section": "Intro", "props": {"label": "Visiteurs"}, "data": {"count": 12}, "controls": CONTROLS,
            "anchors": [{"anchor_id": "reveal", "label": "Reveler", "control_id": "start_count"}],
            "preview": {"caption": "Le chiffre", "alt": ""}, **changes}


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.rows.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[tuple[str, dict]]:
        return [(level, data) for k, level, data in self.rows if k == kind]


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class CountingCatalog:
    """Enveloppe le vrai `PrefabService` et compte ce que le Studio lui demande."""

    def __init__(self, inner: PrefabService) -> None:
        self.inner, self.manifests, self.instances = inner, 0, 0

    async def manifest(self, prefab_id, version):
        self.manifests += 1
        return await self.inner.manifest(prefab_id, version)

    async def validate_instance(self, ref):
        self.instances += 1
        return await self.inner.validate_instance(ref)


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        package, self.data = tmp_path / "package", tmp_path / "data"
        package.mkdir()
        self.data.mkdir()
        install_version(package, "jarvis.counter", title="Base")
        install_version(self.data / LIBRARY_DIR, "lab.counter", 1)
        install_version(self.data / LIBRARY_DIR, "lab.counter", 2)
        install_version(self.data / LIBRARY_DIR, "lab.broken", 1)
        (self.data / LIBRARY_DIR / "lab.broken" / "1" / "template.html").write_text("<p>edited</p>", encoding="utf-8")
        self.package = package
        self.sink = Sink()
        self.prefabs = PrefabService(FilePrefabLibrary(package, self.data))
        self.catalog = CountingCatalog(self.prefabs)
        self.studio_root = tmp_path / "studio"
        self.studio_root.mkdir()

    async def service(self, *, catalog=True) -> PresentationStudioService:
        await self.prefabs.start()
        return PresentationStudioService(FilePresentationStudioStore(self.studio_root), diagnostics=self.sink,
                                         clock=Clock(), prefabs=self.catalog if catalog else None)

    async def presentation(self, service, scenes=None):
        view = await service.create({"title": "Atelier"})
        pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
        if scenes is not None:
            await self.save(service, pid, vid, scenes)
        return pid, vid

    @staticmethod
    async def save(service, pid, vid, scenes, **changes):
        variant = await service.get_variant(pid, vid)
        return await service.save_variant(pid, vid, {
            "expected_revision": variant.revision, "title": changes.pop("title", variant.title), "scenes": scenes,
            "art_direction_id": None, "score_id": None})

    def variant_file(self, pid, vid) -> Path:
        return self.studio_root / "presentations" / pid / "variants" / f"{vid}.json"


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)


async def refused(awaitable, code: C) -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        await awaitable
    assert caught.value.code is code, caught.value
    return caught.value


# ------------------------------------------------------------------ integrite a la sauvegarde

async def test_a_scene_with_an_existing_pin_valid_values_and_declared_controls_is_saved(env):
    service = await env.service()
    pid, vid = await env.presentation(service)
    saved = await env.save(service, pid, vid, [scene_body()])
    assert saved.revision == 2 and saved.scenes[0].controls[1].bounds.max == 100
    assert saved.scenes[0].anchors[0].control_id == "start_count"
    stored = json.loads(env.variant_file(pid, vid).read_text(encoding="utf-8"))
    assert stored["schema_version"] == 2 and stored["scenes"][0] == StudioScene.from_dict(scene_body()).to_dict()
    level, data = env.sink.of("core.presentation_studio.scenes_checked")[-1]
    assert level == "info" and data == {"presentation_id": pid, "variant_id": vid, "checked": 1, "unchanged": 0}


@pytest.mark.parametrize(("prefab", "needle"), [
    (("lab.nope", 1), "unknown_prefab"), (("lab.counter", 9), "unknown_version"), (("lab.broken", 1), "tampered")])
async def test_a_pin_that_does_not_resolve_is_refused_with_the_prefab_services_own_reason(env, prefab, needle):
    service = await env.service()
    pid, vid = await env.presentation(service)
    before = env.variant_file(pid, vid).read_bytes()
    error = await refused(env.save(service, pid, vid, [scene_body(prefab=prefab, controls=[], anchors=[])]),
                          C.PREFAB_UNAVAILABLE)
    assert needle in error.message and SID in error.message and error.status == 409
    assert env.variant_file(pid, vid).read_bytes() == before  # nothing written
    assert env.sink.of("core.presentation_studio.failed")[-1][0] == "error"  # visible in the Error Logs viewer


@pytest.mark.parametrize(("change", "needle"), [
    ({"controls": [{**CONTROLS[0], "path": "props.colour"}], "anchors": []}, "props.colour is not declared"),
    ({"controls": [{**CONTROLS[1], "bounds": {"min": 0, "max": 5_000_000}}], "anchors": []}, "outside the manifest range"),
    ({"controls": [{**CONTROLS[1], "default": 500}], "anchors": []}, "at most 100"),
    ({"controls": [{**CONTROLS[2], "bounds": {"choices": ["huge"]}}], "anchors": []}, "not values of the manifest enum"),
    ({"data": {"count": 500}}, "at most 100"),
    ({"props": {"mode": "full"}}, "must be one of ['compact']"),
])
async def test_controls_and_values_that_do_not_fit_the_pinned_manifest_are_refused_and_not_written(env, change, needle):
    service = await env.service()
    pid, vid = await env.presentation(service)
    before = env.variant_file(pid, vid).read_bytes()
    error = await refused(env.save(service, pid, vid, [scene_body(**change)]), C.SCENE_INCOMPATIBLE)
    assert needle in error.message and error.status == 400
    assert env.variant_file(pid, vid).read_bytes() == before
    assert env.sink.of("core.presentation_studio.refused")[-1][0] == "info"  # the caller's fault, not a system failure


async def test_the_prefab_service_is_the_authority_on_instance_values(env):
    service = await env.service()
    pid, vid = await env.presentation(service)
    for change, needle in [({"data": {}}, "required"), ({"data": {"count": 1, "unknown": 1}}, "unknown keys"),
                           ({"props": {"accent": "red"}}, "#rrggbb"), ({"data": {"count": "x"}}, "expected a finite integer")]:
        error = await refused(env.save(service, pid, vid, [scene_body(controls=[], anchors=[], **change)]),
                              C.SCENE_INCOMPATIBLE)
        assert needle in error.message and "lab.counter@1" in error.message
    assert env.catalog.instances == 4  # every verdict came from PrefabService.validate_instance


async def test_a_second_version_of_the_same_prefab_is_a_different_exact_pin(env):
    service = await env.service()
    pid, vid = await env.presentation(service, [scene_body()])
    saved = await env.save(service, pid, vid, [scene_body(prefab=("lab.counter", 2))])
    assert saved.scenes[0].prefab.version == 2


async def test_unchanged_scenes_are_not_rechecked_and_a_changed_one_is(env):
    service = await env.service()
    pid, vid = await env.presentation(service, [scene_body(), scene_body(SID2)])
    calls = env.catalog.manifests
    await env.save(service, pid, vid, [scene_body(), scene_body(SID2)], title="Renommee")
    assert env.catalog.manifests == calls
    assert env.sink.of("core.presentation_studio.scenes_checked")[-1][1]["checked"] == 0
    await env.save(service, pid, vid, [scene_body(), scene_body(SID2, data={"count": 3})])
    assert env.catalog.manifests == calls + 1
    assert env.sink.of("core.presentation_studio.scenes_checked")[-1][1] == {
        "presentation_id": pid, "variant_id": vid, "checked": 1, "unchanged": 1}


async def test_a_too_big_scene_is_refused_before_any_prefab_call(env):
    service = await env.service()
    pid, vid = await env.presentation(service)
    calls = env.catalog.manifests
    error = await refused(env.save(service, pid, vid, [scene_body(
        controls=[], anchors=[], data={"count": 1, "notes": "n" * 17_000})]), C.INVALID_PRESENTATION)
    assert "payload exceeds 16384" in error.message and env.catalog.manifests == calls


async def test_without_a_catalog_only_the_shape_is_checked_and_describing_is_refused(env):
    service = await env.service(catalog=False)
    pid, vid = await env.presentation(service)
    await env.save(service, pid, vid, [scene_body(prefab=("lab.nope", 7))])  # shape only: the unit-test harness
    error = await refused(service.describe_scene(pid, vid, SID), C.PREFAB_UNAVAILABLE)
    assert "no prefab catalog is wired" in error.message


# ------------------------------------------------------------------ introspection

async def test_a_scene_answers_what_is_editable_with_stable_semantic_controls(env):
    service = await env.service()
    pid, vid = await env.presentation(service, [scene_body(), scene_body(SID2, prefab=("lab.counter", 2), controls=[], anchors=[])])
    answer = await service.describe_scene(pid, vid, SID)
    assert answer["presentation_id"] == pid and answer["variant_id"] == vid and answer["variant_revision"] == 2
    assert answer["scene_id"] == SID and answer["order"] == 0 and answer["prefab"] == {"id": "lab.counter", "version": 1}
    assert [c["control_id"] for c in answer["controls"]] == ["headline", "start_count", "density"]
    count = answer["controls"][1]
    assert count["widget"] == "slider" and count["bounds"] == {"min": 0, "max": 100} and count["current"] == 12
    assert count["default"] == 10 and count["required"] is True and count["label"] == "Valeur"
    assert answer["anchors"][0]["control_id"] == "start_count" and answer["problems"] == []
    assert answer["payload"]["limit"] == 16_384 and answer["payload"]["bytes"] < 1000
    second = await service.describe_scene(pid, vid, SID2)
    assert second["order"] == 1 and second["controls"] == [] and second["prefab"]["version"] == 2


async def test_control_ids_do_not_change_across_calls_unrelated_edits_or_a_restart(env):
    service = await env.service()
    pid, vid = await env.presentation(service, [scene_body()])
    first = await service.describe_scene(pid, vid, SID)
    assert await service.describe_scene(pid, vid, SID) == first
    await env.save(service, pid, vid, [scene_body()], title="Renommee")  # revision moves, controls do not
    after = await service.describe_scene(pid, vid, SID)
    assert after["variant_revision"] == first["variant_revision"] + 1
    assert {k: v for k, v in after.items() if k != "variant_revision"} == {
        k: v for k, v in first.items() if k != "variant_revision"}
    restarted = await Env.service(env)
    again = await restarted.describe_scene(pid, vid, SID)
    assert {k: v for k, v in again.items() if k != "variant_revision"} == {
        k: v for k, v in first.items() if k != "variant_revision"}
    assert env.sink.of("core.presentation_studio.scene_described")[0] == ("info", {
        "presentation_id": pid, "variant_id": vid, "scene_id": SID, "controls": 3, "problems": 0,
        "payload_bytes": first["payload"]["bytes"]})  # ids and counts only, never a title or a value


async def test_an_incomplete_instance_still_describes_itself_with_the_reason(env):
    service = await env.service()
    pid, vid = await env.presentation(service)
    await env.save(service, pid, vid, [scene_body()])
    stored = json.loads(env.variant_file(pid, vid).read_text(encoding="utf-8"))
    stored["scenes"][0]["data"] = {}  # e.g. an old v1 pin upgraded without values
    env.variant_file(pid, vid).write_text(json.dumps(stored), encoding="utf-8")
    answer = await service.describe_scene(pid, vid, SID)
    assert [c["control_id"] for c in answer["controls"]] == ["headline", "start_count", "density"]
    assert answer["controls"][1]["is_set"] is False and answer["controls"][1]["current"] == 10
    assert len(answer["problems"]) == 1 and "required" in answer["problems"][0]


async def test_describing_refuses_unknown_things_with_their_own_codes(env):
    service = await env.service()
    pid, vid = await env.presentation(service, [scene_body()])
    await refused(service.describe_scene(pid, vid, "pss_ffffffffffff"), C.UNKNOWN_SCENE)
    for bad in ("pss_xyz", "", "../x", "pss_0000000000A1", SID + "\n"):
        await refused(service.describe_scene(pid, vid, bad), C.UNKNOWN_SCENE)
    await refused(service.describe_scene(pid, "psv_" + "9" * 32, SID), C.UNKNOWN_VARIANT)
    await refused(service.describe_scene(pid, "nope", SID), C.UNKNOWN_VARIANT)
    await refused(service.describe_scene("pst_" + "9" * 32, vid, SID), C.UNKNOWN_PRESENTATION)


async def test_a_stored_scene_that_no_longer_fits_its_pin_is_reported_not_described(env):
    service = await env.service()
    pid, vid = await env.presentation(service, [scene_body()])
    stored = json.loads(env.variant_file(pid, vid).read_text(encoding="utf-8"))
    stored["scenes"][0]["controls"][0]["path"] = "props.vanished"
    env.variant_file(pid, vid).write_text(json.dumps(stored), encoding="utf-8")
    error = await refused(service.describe_scene(pid, vid, SID), C.SCENE_INCOMPATIBLE)
    assert "props.vanished is not declared" in error.message


async def test_a_catalog_disk_failure_is_a_storage_failure_not_a_missing_prefab(env):
    class Broken(CountingCatalog):
        async def manifest(self, prefab_id, version):
            raise PrefabStoreError(PrefabStoreErrorCode.STORAGE_IO, "disk unreadable")

    service = await env.service()
    pid, vid = await env.presentation(service, [scene_body()])
    env.catalog = Broken(env.prefabs)
    broken = await env.service()
    error = await refused(broken.describe_scene(pid, vid, SID), C.STORAGE_IO)
    assert "disk unreadable" in error.message and "storage_io" in error.message and error.status == 500


# ------------------------------------------------------------------ anciens fichiers

async def test_a_slice_02_variant_file_reads_as_bare_pins_and_is_rewritten_as_v2_on_save(env):
    service = await env.service(catalog=False)
    pid, vid = await env.presentation(service)
    path = env.variant_file(pid, vid)
    old = json.loads(path.read_text(encoding="utf-8"))
    old.update(schema_version=1, scenes=[{"scene_id": SID, "prefab": {"id": "lab.counter", "version": 1}}])
    path.write_text(json.dumps(old), encoding="utf-8")
    variant = await service.get_variant(pid, vid)
    assert variant.scenes[0].prefab.prefab_id == "lab.counter" and variant.scenes[0].controls == ()
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1  # reading never rewrites
    await env.save(service, pid, vid, [scene_body()], title="Atelier v2")
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2
