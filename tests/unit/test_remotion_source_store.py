"""Une source Remotion dans la bibliothèque de prefabs versionnée : stockage, immuabilité, relecture, altération, rétention,
épinglage, identité de scène (Slice 05).

Vrai magasin sur dossiers temporaires. Contrat : `docs/remotion-source.md` §1-4 ; `docs/prefabs.md` › *Manifest* v2.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.core.prefab_service import PrefabService
from jarvis.core.presentation_studio_pins import StudioPinRegistry
from jarvis.domain.prefab import PrefabRef, RETENTION_TRIGGER_VERSIONS
from jarvis.domain.presentation_studio_reload import plan_carry_over, scene_problems
from jarvis.domain.presentation_studio_scene import ScoreAnchor, StudioControl, StudioScene
from jarvis.ports.prefabs import PrefabRoot, PrefabStoreError, PrefabStoreErrorCode as C
from tests.fakes.links import make_dir_link
from tests.fakes.prefabs import candidate as html_candidate, install_version
from tests.fakes.remotion_scene import PNG_1X1, scene_candidate, scene_files

NOW = datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
SCENE = "presentation-studio.p000000000001.s000000000001"
OTHER = "presentation-studio.p000000000001.s000000000002"


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.events.append((kind, level, dict(data or {})))

    def kinds(self):
        return [kind for kind, _, _ in self.events]


class Pins:
    def __init__(self, pinned=None):
        self.pinned = pinned or {}

    async def pinned_versions(self, prefab_ids):
        return {prefab_id: frozenset(self.pinned.get(prefab_id, ())) for prefab_id in prefab_ids}


@pytest.fixture
def roots(tmp_path: Path):
    package = tmp_path / "package"
    package.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    install_version(package, "jarvis.counter", title="Base counter")
    return package, data


def make_service(roots, *, pins=None):
    recorder = Recorder()
    return PrefabService(FilePrefabLibrary(*roots), diagnostics=recorder, clock=lambda: NOW, pin_registry=pins), recorder


def version_dir(data: Path, prefab_id: str, version: int) -> Path:
    return data / LIBRARY_DIR / prefab_id / str(version)


def snapshot(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)).replace("\\", "/"): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


# ------------------------------------------------------------------ disposition sur disque


async def test_a_remotion_source_is_a_prefab_version_with_src_and_public_and_no_node_modules(roots):
    service, recorder = make_service(roots)
    publication = await service.save(scene_candidate(SCENE), actor="user")
    assert (publication.prefab_id, publication.version) == (SCENE, 1)
    folder = version_dir(roots[1], SCENE, 1)
    files = snapshot(folder)
    assert set(files) == {"manifest.json", "publication.json", "src/Scene.tsx", "src/lib/Title.tsx", "src/theme.json",
                          "public/dot.png"}
    assert files["public/dot.png"] == PNG_1X1
    assert not [p for p in roots[1].rglob("*") if p.name in ("node_modules", "package.json", "package-lock.json")]
    manifest = json.loads(files["manifest.json"])
    assert manifest["schema_version"] == 2 and manifest["version"] == 1 and "files" not in manifest
    assert publication.fingerprint == (await service.get(SCENE)).entry.fingerprint
    assert "core.prefab.saved" in recorder.kinds()
    assert not [p for p in (roots[1] / LIBRARY_DIR).iterdir() if p.name.startswith(".staging-")]


async def test_the_source_reopens_identical_after_a_restart(roots):
    service, _ = make_service(roots)
    candidate = scene_candidate(SCENE)
    publication = await service.save(candidate, actor="user")
    first = await service.remotion_source(SCENE, 1)
    reopened, recorder = make_service(roots)  # a new process: new service, new library, nothing cached
    await reopened.start()
    again = await reopened.remotion_source(SCENE, 1)
    assert again.digest == first.digest and dict(again.files) == dict(first.files)
    assert (await reopened.get(SCENE, 1)).entry.fingerprint == publication.fingerprint
    assert again.files["public/dot.png"] == PNG_1X1
    assert again.block.composition.width == 1280 and again.block.entry == "src/Scene.tsx"
    assert "core.prefab.tampered" not in recorder.kinds()


async def test_versions_are_immutable_and_a_revision_is_a_new_version(roots):
    service, _ = make_service(roots)
    one = await service.save(scene_candidate(SCENE), actor="user")
    before = snapshot(version_dir(roots[1], SCENE, 1))
    two = await service.save(scene_candidate(SCENE, files=scene_files("// v2\n")), actor="brain")
    assert (one.version, two.version) == (1, 2) and two.provenance.origin.value == "revision"
    assert snapshot(version_dir(roots[1], SCENE, 1)) == before
    assert (await service.remotion_source(SCENE, 1)).digest != (await service.remotion_source(SCENE, 2)).digest
    with pytest.raises(PrefabStoreError) as caught:
        await asyncio.to_thread(FilePrefabLibrary(*roots).publish, (await service.get(SCENE, 1)).entry.bundle, one)
    assert caught.value.code is C.VERSION_EXISTS
    assert snapshot(version_dir(roots[1], SCENE, 1)) == before


async def test_two_scenes_with_the_same_file_names_do_not_share_anything(roots):
    service, _ = make_service(roots)
    await service.save(scene_candidate(SCENE), actor="user")
    await service.save(scene_candidate(OTHER, files=scene_files("export const Extra = 1;\n")), actor="user")
    one, two = await service.remotion_source(SCENE, 1), await service.remotion_source(OTHER, 1)
    assert set(one.files) == set(two.files) and one.digest != two.digest
    assert version_dir(roots[1], SCENE, 1) != version_dir(roots[1], OTHER, 1)
    assert one.text("src/Scene.tsx") == two.text("src/Scene.tsx")


async def test_a_changed_data_root_has_its_own_library(roots, tmp_path):
    service, _ = make_service(roots)
    await service.save(scene_candidate(SCENE), actor="user")
    other_data = tmp_path / "other-data"
    other_data.mkdir()
    elsewhere, _ = make_service((roots[0], other_data))
    with pytest.raises(PrefabStoreError) as caught:
        await elsewhere.remotion_source(SCENE, 1)
    assert caught.value.code is C.UNKNOWN_PREFAB
    assert not (other_data / LIBRARY_DIR).exists() or not any((other_data / LIBRARY_DIR).iterdir())


# ------------------------------------------------------------------ cohabitation avec l'HTML


async def test_html_and_remotion_prefabs_share_one_library(roots):
    service, _ = make_service(roots)
    await service.save(html_candidate("test.counter") | {"manifest": {**html_candidate("test.counter")["manifest"], "id": "lab.html"}},
                       actor="user")
    await service.save(scene_candidate(SCENE), actor="user")
    ids = {row.prefab_id for row in await service.search()}
    assert {"jarvis.counter", "lab.html", SCENE} <= ids
    assert (await service.get("lab.html", 1)).to_dict(include_source=True)["files"]["template"]  # HTML detail untouched
    with pytest.raises(PrefabStoreError) as caught:
        await service.bundle(SCENE, 1)
    assert caught.value.code is C.INVALID_DEFINITION and "Remotion source" in caught.value.message
    with pytest.raises(PrefabStoreError) as caught:
        await service.remotion_source("lab.html", 1)
    assert caught.value.code is C.INVALID_DEFINITION
    with pytest.raises(PrefabStoreError) as caught:
        await service.remotion_source(SCENE, None)  # an exact version is required
    assert caught.value.code is C.UNKNOWN_VERSION


async def test_the_detail_lists_modules_as_text_and_never_inlines_assets(roots):
    service, _ = make_service(roots)
    await service.save(scene_candidate(SCENE), actor="user")
    body = (await service.get(SCENE, 1)).to_dict(include_source=True)
    assert body["files"] == {}  # a catalogue entry holds no contents (see the memory test below)
    assert set(body["inventory"]) == {"src/Scene.tsx", "src/lib/Title.tsx", "src/theme.json", "public/dot.png"}
    assert body["inventory"]["public/dot.png"] == {"bytes": len(PNG_1X1), "sha256": hashlib.sha256(PNG_1X1).hexdigest()}
    assert body["manifest"]["source"]["assets"] == ["public/dot.png"]


OLD_READER_KEYS = {"schema", "schema_version", "id", "version", "title", "description", "family", "tags", "aliases", "scene",
                   "inputs", "events", "sample", "files"}


def old_reader_accepts(manifest: dict) -> bool:
    """La règle de `parse_manifest` d'avant la Slice 05 : version 1, clés fermées. Figée ici pour le test de compatibilité."""

    return manifest.get("schema_version") == 1 and set(manifest) <= OLD_READER_KEYS


async def test_an_old_reader_refuses_a_remotion_version_and_still_reads_every_html_one(roots):
    """Un lecteur d'avant la Slice 05 range la version 2 en « refusée » (version `tampered`, tracée), jamais en panne ; les
    manifestes HTML (v1) restent, eux, exactement ce qu'il lit."""

    service, _ = make_service(roots)
    await service.save(scene_candidate(SCENE), actor="user")
    v2 = json.loads((version_dir(roots[1], SCENE, 1) / "manifest.json").read_text("utf-8"))
    assert not old_reader_accepts(v2)
    assert set(v2) - OLD_READER_KEYS == {"source"} and "files" not in v2
    assert old_reader_accepts(html_candidate()["manifest"])
    base = json.loads((roots[0] / "jarvis.counter" / "1" / "manifest.json").read_text("utf-8"))
    assert old_reader_accepts(base) and base["schema_version"] == 1


# ------------------------------------------------------------------ altération


async def tampered(roots, mutate):
    service, _ = make_service(roots)
    await service.save(scene_candidate(SCENE), actor="user")
    folder = version_dir(roots[1], SCENE, 1)
    mutate(folder)
    fresh, recorder = make_service(roots)
    with pytest.raises(PrefabStoreError) as caught:
        await fresh.remotion_source(SCENE, 1)
    assert caught.value.code is C.TAMPERED, caught.value
    assert "core.prefab.tampered" in recorder.kinds()
    return caught.value


async def test_an_edited_source_file_is_refused_not_trusted(roots):
    error = await tampered(roots, lambda f: (f / "src" / "Scene.tsx").write_text("export default () => null;\n", "utf-8"))
    assert "fingerprint" in error.message or "edited" in error.message


async def test_a_file_added_to_the_folder_is_refused(roots):
    await tampered(roots, lambda f: (f / "src" / "Sneaky.ts").write_text("export {}", "utf-8"))


async def test_a_declared_file_that_disappeared_is_refused(roots):
    await tampered(roots, lambda f: (f / "public" / "dot.png").unlink())


async def test_a_folder_in_place_of_a_declared_file_is_refused(roots):
    def swap(folder: Path) -> None:
        (folder / "src" / "theme.json").unlink()
        (folder / "src" / "theme.json").mkdir()

    await tampered(roots, swap)


def relocate(folder: Path, relative: str, outside: Path) -> None:
    """Déplace `folder/relative` (dossier) vers `outside` puis met à sa place une JONCTION (Windows, sans privilège) ou un lien
    symbolique : le contenu reste lisible par le lien, seule la défense de lien peut le refuser."""

    source = folder.joinpath(*relative.split("/"))
    outside.mkdir(parents=True)
    for item in sorted(source.iterdir()):
        item.rename(outside / item.name)
    source.rmdir()
    make_dir_link(source, outside)


@pytest.mark.parametrize("relative", ["src", "src/lib", "public"])
async def test_a_linked_source_folder_is_refused_at_every_level(roots, tmp_path, relative):
    """Jonction sur `src`, sur un sous-dossier imbriqué `src/lib` ou sur `public` : la version est `tampered`, jamais lue à
    travers le lien. Ces cas tournent ici sans privilège (jonction)."""

    error = await tampered(roots, lambda folder: relocate(folder, relative, tmp_path / "elsewhere"))
    assert "link" in error.message or "regular file" in error.message or "refused" in error.message


def test_the_source_walk_flags_a_link_instead_of_following_it(roots, tmp_path):
    from jarvis.adapters.file_prefab_library import _walk_sources
    folder = tmp_path / "version"
    (folder / "src" / "lib").mkdir(parents=True)
    (folder / "src" / "Scene.tsx").write_text("x", "utf-8")
    inside = tmp_path / "outside"
    inside.mkdir()
    (inside / "Secret.ts").write_text("secret", "utf-8")
    make_dir_link(folder / "src" / "lib" / "ln", inside)
    found = {path: size for path, size, _ in _walk_sources(folder)}
    assert found["src/lib/ln"] == -1 and "src/lib/ln/Secret.ts" not in found and found["src/Scene.tsx"] == 1


# ------------------------------------------------------------------ mémoire du catalogue, lecture à la demande, bornes de lecture


async def test_the_catalogue_holds_no_file_contents_for_a_remotion_version(roots):
    import tracemalloc
    service, _ = make_service(roots)
    big = {**scene_files(), "public/photo.png": b"\x89PNG" + bytes(range(256)) * (3 * 1024 * 1024 // 256)}
    await service.save(scene_candidate(SCENE, files=big), actor="user")
    fresh, _ = make_service(roots)
    tracemalloc.start()
    await fresh.start()
    retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    entry = fresh._entries_of(SCENE)[0]  # noqa: SLF001 - the catalogue entry is the subject
    assert entry.bundle.sources == {} and not entry.bundle.holds_bytes and entry.bundle.files() == {}
    assert entry.bundle.inventory["public/photo.png"][0] == len(big["public/photo.png"]) > 3_000_000
    assert retained < 400_000, f"the catalogue retains {retained} bytes after loading: file contents are being held"
    assert peak < 1_000_000, f"loading the catalogue peaked at {peak} bytes: file contents are being held"
    source = await fresh.remotion_source(SCENE, 1)  # the bytes come back on demand
    assert source.files["public/photo.png"] == big["public/photo.png"] and source.digest


async def test_a_source_changed_after_the_catalogue_was_loaded_is_refused_on_demand(roots):
    service, recorder = make_service(roots)
    await service.save(scene_candidate(SCENE), actor="user")
    await service.remotion_source(SCENE, 1)
    target = version_dir(roots[1], SCENE, 1) / "src" / "theme.json"
    original = target.read_bytes()
    target.write_bytes(original.replace(b"101820", b"101821"))  # same size, other bytes
    with pytest.raises(PrefabStoreError) as caught:
        await service.remotion_source(SCENE, 1)
    assert caught.value.code is C.TAMPERED and "core.prefab.tampered" in recorder.kinds()


class NoRead(Exception):
    pass


def forbid_reads(monkeypatch):
    def boom(*args, **kwargs):
        raise NoRead("a source file was read although a bound was already broken")

    real = FilePrefabLibrary._read_bytes

    def guarded(path, limit, label):
        if "/src/" in label or "/public/" in label:
            boom()
        return real(path, limit, label)

    monkeypatch.setattr(FilePrefabLibrary, "_read_chunks", staticmethod(boom))
    monkeypatch.setattr(FilePrefabLibrary, "_read_bytes", staticmethod(guarded))


async def test_a_folder_stuffed_with_files_is_refused_by_count_before_any_read(roots, monkeypatch):
    service, _ = make_service(roots)
    await service.save(scene_candidate(SCENE), actor="user")
    stuffed = version_dir(roots[1], SCENE, 1) / "src" / "junk"
    stuffed.mkdir()
    for index in range(1500):
        (stuffed / f"f{index:04d}.ts").write_text("x", "utf-8")
    library = FilePrefabLibrary(*roots)
    from jarvis.adapters.file_prefab_library import MAX_SOURCE_FILES, _walk_sources
    assert len(_walk_sources(version_dir(roots[1], SCENE, 1))) <= MAX_SOURCE_FILES + 1  # the walk itself stops at the bound
    forbid_reads(monkeypatch)
    with pytest.raises(PrefabStoreError) as caught:
        library.read_version(PrefabRoot.DATA, SCENE, 1)
    assert caught.value.code is C.TAMPERED and "source files" in caught.value.message
    with pytest.raises(PrefabStoreError):
        library.read_sources(PrefabRoot.DATA, SCENE, 1)


async def test_an_inflated_file_or_total_is_refused_by_size_before_any_read(roots, monkeypatch):
    service, _ = make_service(roots)
    await service.save(scene_candidate(SCENE), actor="user")
    folder = version_dir(roots[1], SCENE, 1)
    library = FilePrefabLibrary(*roots)
    forbid_reads(monkeypatch)
    huge = folder / "public" / "huge.png"
    with open(huge, "wb") as stream:
        stream.truncate(60 * 1024 * 1024)  # sparse: costs nothing on disk, would cost 60 MiB if read
    with pytest.raises(PrefabStoreError) as caught:
        library.read_version(PrefabRoot.DATA, SCENE, 1)
    assert caught.value.code is C.TAMPERED and "at most" in caught.value.message
    huge.unlink()
    for index in range(8):  # each under the per-file bound, together over the total bound
        with open(folder / "public" / f"p{index}.png", "wb") as stream:
            stream.truncate(3 * 1024 * 1024)
    with pytest.raises(PrefabStoreError) as caught:
        library.read_sources(PrefabRoot.DATA, SCENE, 1)
    assert caught.value.code is C.TAMPERED and "bytes of sources" in caught.value.message


# ------------------------------------------------------------------ validation d'instance, identité de scène


async def test_instance_values_are_validated_against_the_remotion_manifest(roots):
    from jarvis.domain.prefab import PrefabInstanceRef
    service, _ = make_service(roots)
    await service.save(scene_candidate(SCENE), actor="user")
    ok = await service.validate_instance(PrefabInstanceRef(SCENE, 1, {"accent": "#ff0000"}, {}))
    assert ok.ok and ok.props == {"title": "Bonjour", "accent": "#ff0000"}
    bad = await service.validate_instance(PrefabInstanceRef(SCENE, 1, {"accent": "red"}, {}))
    assert not bad.ok and bad.code is C.INVALID_DEFINITION and "props.accent" in bad.detail
    missing = await service.validate_instance(PrefabInstanceRef(SCENE, 9, {}, {}))
    assert missing.code is C.UNKNOWN_VERSION


SCENE_ID = "pss_0000000000a1"
CONTROLS = (StudioControl("headline", "props.title", "Titre", "content"), StudioControl("accent", "props.accent", "Accent", "visual"))
ANCHORS = (ScoreAnchor("intro", "Entrée", "headline"), ScoreAnchor("beat", "Temps fort"))


async def test_scene_identity_and_score_anchors_resolve_unchanged_on_a_remotion_pin(roots):
    service, _ = make_service(roots)
    await service.save(scene_candidate(SCENE), actor="user")
    manifest = await service.manifest(SCENE, 1)
    scene = StudioScene(SCENE_ID, PrefabRef(SCENE, 1), "Titre", props={"title": "Salut"}, controls=CONTROLS, anchors=ANCHORS)
    assert scene.scene_id == SCENE_ID and scene.held_pins() == frozenset({(SCENE, 1)})
    assert scene_problems(scene, manifest) == []  # controls resolve to props.title / props.accent, anchors to controls
    assert [a.control_id for a in scene.anchors] == ["headline", None]
    assert StudioScene.from_dict(scene.to_dict()) == scene  # the wire form is the same as for an HTML pin


async def test_a_revision_carries_scene_values_controls_and_anchors_like_an_html_one(roots):
    service, _ = make_service(roots)
    await service.save(scene_candidate(SCENE), actor="user")
    narrower = scene_candidate(SCENE, props={"type": "object", "properties": {"title": {"type": "string", "default": "Bonjour"}}},
                               sample={"props": {"title": "Bonjour"}, "data": {}})
    await service.save(narrower, actor="user")
    scene = StudioScene(SCENE_ID, PrefabRef(SCENE, 1), "T", props={"title": "Salut", "accent": "#112233"}, controls=CONTROLS,
                        anchors=ANCHORS)
    new_manifest = await service.manifest(SCENE, 2)
    refused = plan_carry_over(scene, new_manifest, allow_reset=False)
    assert refused.scene is None and any("accent" in item for item in refused.problems)
    carried = plan_carry_over(scene, new_manifest, allow_reset=True)
    assert carried.scene.prefab == PrefabRef(SCENE, 2) and carried.scene.scene_id == SCENE_ID
    assert carried.reset.props == ("accent",) and carried.reset.controls == ("accent",)
    assert [a.anchor_id for a in carried.scene.anchors] == ["intro", "beat"]  # the anchors survive, by id


class FakeScene:
    async def snapshot(self):
        class Snap:
            objects = ()
        return Snap()


async def test_a_pinned_remotion_version_survives_retention_and_an_unpinned_one_is_archived(roots):
    registry = StudioPinRegistry()
    registry.bind_scene(FakeScene())
    registry.mark_ready()
    service, recorder = make_service(roots, pins=registry)
    library = FilePrefabLibrary(*roots)
    for index in range(RETENTION_TRIGGER_VERSIONS):
        await service.save(scene_candidate(SCENE, files=scene_files(f"// {index}\n")), actor="user")
    scene = StudioScene(SCENE_ID, PrefabRef(SCENE, 3), "T", props={"title": "Salut"})
    registry.register_variant("pst_" + "a" * 32, "psv_" + "b" * 32, scene.held_pins())
    await service.save(scene_candidate(SCENE, files=scene_files("// last\n")), actor="user")  # triggers the pass
    live = {entry.version for entry in service._entries_of(SCENE)}  # noqa: SLF001 - catalogue state is the subject
    assert 3 in live and 1 not in live and 2 not in live  # pinned kept, old unpinned archived
    archive = roots[1] / LIBRARY_DIR / ".archive" / SCENE
    archived = sorted(int(p.name) for p in archive.iterdir())
    assert archived and 1 in archived
    moved = snapshot(archive / "1")
    assert "src/Scene.tsx" in moved and "public/dot.png" in moved and "manifest.json" in moved  # whole tree moved, nothing lost
    assert not version_dir(roots[1], SCENE, 1).exists()
    assert (PrefabRoot.DATA, SCENE, 1) in library.scan().version_folders  # number 1 stays occupied
    newest = await service.save(scene_candidate(SCENE, files=scene_files("// after\n")), actor="user")
    assert newest.version > max(archived)  # a retired number is never reassigned
    assert "core.prefab.retention_failed" not in recorder.kinds()


# ------------------------------------------------------------------ reprise après arrêt brutal


async def test_a_crash_between_files_leaves_a_staging_folder_that_start_sweeps_and_no_version(roots):
    library = FilePrefabLibrary(*roots)
    staging = roots[1] / LIBRARY_DIR / ".staging-00000000000000cc"
    (staging / "src" / "lib").mkdir(parents=True)
    (staging / "public").mkdir()
    (staging / "src" / "Scene.tsx").write_text("export default () => null;", "utf-8")
    (staging / "public" / "dot.png").write_bytes(PNG_1X1)
    (staging / "manifest.json.tmp").write_text("{", "utf-8")
    service, recorder = make_service(roots)
    await service.start()
    assert not staging.exists() and "core.prefab.swept" in recorder.kinds()
    assert library.scan().versions == () or all(v.prefab_id != SCENE for v in library.scan().versions)
    published = await service.save(scene_candidate(SCENE), actor="user")
    assert published.version == 1  # the interrupted attempt consumed no number


async def test_the_sweep_leaves_a_staging_folder_with_an_unknown_subfolder(roots):
    staging = roots[1] / LIBRARY_DIR / ".staging-00000000000000dd"
    (staging / "node_modules").mkdir(parents=True)
    report = FilePrefabLibrary(*roots).sweep()
    assert report.failed == (staging.name,) and (staging / "node_modules").exists()
