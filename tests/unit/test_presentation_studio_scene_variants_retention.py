"""Une version pinglée par une seule variante locale n'est jamais archivée par la rétention 01a (jarvis-interactive-presentation-studio, Slice 17).

Vrai `PrefabService` avec sa vraie rétention (`docs/prefabs.md` › *Retention of studio scene sources*), vrai magasin, vraie
source d'épinglages du Studio (`PresentationStudioVariants.pin_index()` + `PresentationStudioHistory.pins()` par
`CompositePinRegistry`, la forme que le registre de la Slice 06 aura). Témoin négatif : la même source qui ignore les variantes
locales archive la version, ce qui prouve que le test voit la faute.
Contrat : `docs/presentation-studio.md` › *Scene-local variant contract*, Branches, archive, pins.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.prefab_retention import CompositePinRegistry
from jarvis.core.prefab_service import PrefabService
from jarvis.core.presentation_studio_autosave import PresentationStudioHistory
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.core.presentation_studio_variants import PresentationStudioVariants
from jarvis.domain.prefab import RETENTION_KEEP_LAST, RETENTION_TRIGGER_VERSIONS
from jarvis.domain.presentation_studio_edit import EditStatus
from tests.fakes.prefabs import candidate, install_version
from tests.unit.test_presentation_studio_edit_service import request
from tests.unit.test_presentation_studio_score_service import Clock, Sink

NOW = datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)  # well after the fixtures' publication date
SCENE = "presentation-studio.s1"
S1 = "pss_0000000000a1"


class StudioPins:
    """Ce que le registre de la Slice 06 sera : les pins de chaque variante (vivante ou archivée) et ceux de l'historique."""

    def __init__(self, variants: PresentationStudioVariants, *, local_variants: bool = True) -> None:
        self.variants, self.local_variants = variants, local_variants

    async def pinned_versions(self, prefab_ids):
        found: dict[str, set[int]] = {prefab_id: set() for prefab_id in prefab_ids}
        for pins in (await self.variants.pin_index()).values():
            for prefab_id, version in pins:
                if prefab_id in found:
                    found[prefab_id].add(version)
        return {prefab_id: frozenset(versions) for prefab_id, versions in found.items()}


class ScenePinsOnly(StudioPins):
    """La source d'avant la Slice 17 : seul le pin vivant de chaque scène (témoin négatif)."""

    async def pinned_versions(self, prefab_ids):
        found: dict[str, set[int]] = {prefab_id: set() for prefab_id in prefab_ids}
        scan = await self.variants._studio.run_blocking("pins", None, self.variants._studio.store.scan)
        for pid in scan.presentation_ids:
            presentation = await self.variants._studio.load_presentation_locked(pid)
            for entry in presentation.variants:
                variant = await self.variants._studio.load_variant_locked(pid, entry.variant_id)
                for scene in variant.scenes:
                    if scene.prefab.prefab_id in found:
                        found[scene.prefab.prefab_id].add(scene.prefab.version)
        return {prefab_id: frozenset(versions) for prefab_id, versions in found.items()}


class World:
    @staticmethod
    def _root(tmp_path: Path) -> Path:
        root = tmp_path / "studio"
        root.mkdir()
        return root

    async def open(self, tmp_path: Path, *, local_variants: bool = True):
        package, self.data = tmp_path / "package", tmp_path / "data"
        package.mkdir()
        self.data.mkdir()
        install_version(package, "jarvis.counter", title="Base")
        for version in range(1, RETENTION_TRIGGER_VERSIONS + 1):
            install_version(self.data / LIBRARY_DIR, SCENE, version)
        self.sink = Sink()
        self.holder: list = []
        self.prefabs = PrefabService(FilePrefabLibrary(package, self.data), diagnostics=self.sink, clock=lambda: NOW,
                                     pin_registry=CompositePinRegistry(_Late(self.holder)))
        await self.prefabs.start()
        self.studio = PresentationStudioService(FilePresentationStudioStore(self._root(tmp_path)), diagnostics=self.sink,
                                                clock=Clock(), prefabs=self.prefabs)
        self.history = PresentationStudioHistory(self.studio, diagnostics=self.sink)
        self.edit = PresentationStudioEditService(self.studio, diagnostics=self.sink, history=self.history)
        self.history.bind(self.edit)
        self.variants = PresentationStudioVariants(self.studio, history=self.history, diagnostics=self.sink, secret=b"r" * 32)
        pins = (StudioPins if local_variants else ScenePinsOnly)(self.variants)
        self.holder.append(pins)
        self.holder.append(self.history)
        view = await self.studio.create({"title": "Atelier"})
        self.pid, self.vid = view.presentation.presentation_id, view.presentation.active_variant_id
        base = await self.studio.get_variant(self.pid, self.vid)
        scene = {"scene_id": S1, "prefab": {"id": SCENE, "version": RETENTION_TRIGGER_VERSIONS - 1}, "data": {"count": 1}}
        await self.studio.save_variant(self.pid, self.vid, {"expected_revision": base.revision, "title": base.title,
                                                            "scenes": [scene], "art_direction_id": None, "score_id": None})
        return self

    async def give_the_scene_a_local_variant_pinned_to(self, version: int) -> str:
        revision = (await self.studio.get_variant(self.pid, self.vid)).revision
        made = await self.edit.edit(self.pid, self.vid, request(revision, {"op": "scene_variant.create", "scene_id": S1, "label": "Ancienne"}))
        assert made.status is EditStatus.APPLIED
        local = made.ops[0]["scene_variant_id"]
        scene = (await self.studio.get_variant(self.pid, self.vid)).scenes[0].to_dict()
        scene["scene_variants"]["items"][1]["content"]["prefab"] = {"id": SCENE, "version": version}
        current = await self.studio.get_variant(self.pid, self.vid)
        await self.studio.save_variant(self.pid, self.vid, {"expected_revision": current.revision, "title": current.title,
                                                            "scenes": [scene], "art_direction_id": None, "score_id": None})
        return local

    async def retention_pass(self, title: str) -> int:
        """Publie une version de plus : au-delà du déclencheur, la rétention tourne (sous le verrou, avec la source d'épinglages)."""

        return (await self.prefabs.save(candidate(id=SCENE, title=title), actor="user")).version

    def live(self) -> list[int]:
        return sorted(int(p.name) for p in (self.data / LIBRARY_DIR / SCENE).iterdir())

    def archived(self) -> list[int]:
        folder = self.data / LIBRARY_DIR / ".archive" / SCENE
        return sorted(int(p.name) for p in folder.iterdir()) if folder.exists() else []


class _Late:
    """Le registre est câblé après le service de prefabs (comme dans Core) : une liste qu'on remplit ensuite."""

    def __init__(self, holder: list) -> None:
        self.holder = holder

    async def pinned_versions(self, prefab_ids):
        merged: dict[str, set[int]] = {prefab_id: set() for prefab_id in prefab_ids}
        for registry in self.holder:
            for prefab_id, versions in (await registry.pinned_versions(prefab_ids)).items():
                merged[prefab_id] |= set(versions)
        return {prefab_id: frozenset(versions) for prefab_id, versions in merged.items()}


async def test_a_version_pinned_only_by_a_non_selected_local_variant_survives_the_retention(tmp_path):
    world = await World().open(tmp_path)
    await world.give_the_scene_a_local_variant_pinned_to(1)
    version = await world.retention_pass("Retouche")
    live = world.live()
    assert version == RETENTION_TRIGGER_VERSIONS + 1 and 1 in live, (live, world.archived())  # pinned by the stored variant only
    assert RETENTION_TRIGGER_VERSIONS - 1 in live  # the scene's own pin
    assert world.archived() and 2 in world.archived(), "retention really ran and archived the unpinned old versions"
    assert len(live) <= RETENTION_KEEP_LAST + 2


async def test_the_negative_control_a_source_that_ignores_local_variants_would_archive_it(tmp_path):
    world = await World().open(tmp_path, local_variants=False)
    await world.give_the_scene_a_local_variant_pinned_to(1)
    await world.retention_pass("Retouche")
    assert 1 in world.archived() and 1 not in world.live(), "without the Slice 17 pin source the old version is lost"


async def test_deleting_the_local_variant_keeps_its_pin_while_the_undo_ring_can_bring_it_back(tmp_path):
    world = await World().open(tmp_path)
    local = await world.give_the_scene_a_local_variant_pinned_to(1)
    revision = (await world.studio.get_variant(world.pid, world.vid)).revision
    deleted = await world.edit.edit(world.pid, world.vid, request(revision, {"op": "scene_variant.delete", "scene_id": S1, "variant_id": local}))
    assert deleted.status is EditStatus.APPLIED and "scene_variants" not in (await world.studio.get_variant(world.pid, world.vid)).scenes[0].to_dict()
    assert ("presentation-studio.s1", 1) in world.history.pins()  # the inverse holds the pin the document just lost
    await world.retention_pass("Une")
    assert 1 in world.live()
    undone = await world.history.undo(world.pid, world.vid, {"actor": "user"})
    assert undone.status.value == "applied"
    scene = (await world.studio.get_variant(world.pid, world.vid)).scenes[0]
    assert scene.scene_variants.get(local).content["prefab"]["version"] == 1  # and it resolves: the version is still there
    # once the ring lets go (the variant is archived or evicted) and nothing else pins it, it may age out like any other
    revision = (await world.studio.get_variant(world.pid, world.vid)).revision
    await world.edit.edit(world.pid, world.vid, request(revision, {"op": "scene_variant.delete", "scene_id": S1, "variant_id": local}))
    world.history.drop_variant(world.pid, world.vid)
    assert ("presentation-studio.s1", 1) not in world.history.pins()
    for version in range(60, 60 + RETENTION_TRIGGER_VERSIONS):  # enough live versions to trigger a second pass
        install_version(world.data / LIBRARY_DIR, SCENE, version)
    await world.retention_pass("Deux")
    assert 1 in world.archived()
    assert json.loads(Path(world.data / LIBRARY_DIR / ".archive" / SCENE / "1" / "manifest.json").read_text(encoding="utf-8"))["version"] == 1


async def test_an_archived_variant_keeps_the_pins_of_its_local_variants(tmp_path):
    world = await World().open(tmp_path)
    await world.give_the_scene_a_local_variant_pinned_to(1)
    branch = (await world.variants.create_branch(world.pid, {"title": "Branche"}))["variant"]["variant_id"]
    plan = await world.variants.plan_archive(world.pid, branch)
    await world.variants.archive(world.pid, branch, {"confirmation": plan["confirmation"]})
    assert (await world.variants.pin_index())[(world.pid, branch)] >= {(SCENE, 1)}
    # the source variant alone can age out? no: both hold the pin, so one retention pass keeps it
    await world.retention_pass("Retouche")
    assert 1 in world.live()
