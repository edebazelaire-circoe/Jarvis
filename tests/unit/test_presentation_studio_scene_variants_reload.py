"""Variantes locales et rechargement à chaud (Slices 17 et 06), pins réels, verrou de scène, assemblage (Slice 11)
(jarvis-interactive-presentation-studio).

Vrai `JarvisCoreApplication` : vrai `StudioPinRegistry`, vraie rétention 01a, vrai service de rechargement, vrai verrou
`presentation_studio_scene_reloading`. Règles : une version épinglée par une seule variante locale non choisie (et par un
`last_valid_pin`) survit à la rétention à 60+ versions ; toute écriture d'une variante locale d'une scène en rechargement est
refusée 409 comme les autres écritures ; une promotion est refusée tant qu'une scène de la source se recharge ; un rechargement
ne touche que la scène vivante (les variantes rangées gardent leur pin) ; l'assemblage de la Slice 11 ne produit aucun ensemble.
Contrat : `docs/presentation-studio.md` › *Scene-local variant contract*, Hot reload.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import EditStatus
from jarvis.domain.presentation_studio_reload import ReloadStatus as S
from jarvis.domain.presentation_studio_scene import StudioScene
from tests.fakes.prefabs import candidate, install_version

pytestmark = pytest.mark.asyncio

S1, S2 = "pss_0000000000b1", "pss_0000000000b2"
LAB = "presentation-studio.lab"


def scene_body(scene_id=S1, **extra) -> dict:
    return {"scene_id": scene_id, "prefab": {"id": "jarvis.window", "version": 1}, "title": "Fenetre", "props": {"density": "compact"},
            "data": {"body": "Texte"}, "controls": [{"control_id": "body", "path": "data.body", "label": "Texte", "group": "content"}],
            **extra}


async def started(root: Path) -> JarvisCoreApplication:
    core = JarvisCoreApplication(data_root=root)
    await core.start()
    return core


async def new_presentation(core, scenes=(S1,)) -> tuple[str, str]:
    view = await core.presentation_studio.create({"title": "Atelier"})
    pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
    variant = await core.presentation_studio.get_variant(pid, vid)
    await core.presentation_studio.save_variant(pid, vid, {
        "expected_revision": variant.revision, "title": variant.title, "scenes": [scene_body(s) for s in scenes],
        "art_direction_id": None, "score_id": None})
    return pid, vid


async def edit(core, pid, vid, *ops):
    revision = (await core.presentation_studio.get_variant(pid, vid)).revision
    return await core.presentation_studio_edit.edit(pid, vid, {
        "actor": "user", "mode": "commit", "basis": {"variant_revision": revision}, "ops": list(ops)})


def create(scene_id, label):
    return {"op": "scene_variant.create", "scene_id": scene_id, "label": label}


def select(scene_id, variant_id, **extra):
    return {"op": "scene_variant.select", "scene_id": scene_id, "variant_id": variant_id, **extra}


async def refused_409(awaitable) -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        await awaitable
    assert caught.value.code is C.SCENE_RELOADING and caught.value.status == 409, caught.value
    return caught.value


# ------------------------------------------------------------------ pins : le vrai registre, la vraie rétention, 64 versions

def library_versions(data: Path) -> tuple[list[int], list[int]]:
    live = sorted(int(p.name) for p in (data / LIBRARY_DIR / LAB).iterdir())
    archive = data / LIBRARY_DIR / ".archive" / LAB
    return live, sorted(int(p.name) for p in archive.iterdir()) if archive.exists() else []


async def crafted_core(tmp_path: Path, monkeypatch=None, *, stored_pin: int = 3, fallback: int = 5, live: int = 62):
    """Core redémarré sur un document où la scène vivante épingle `live`, une variante locale rangée épingle `stored_pin` seule, et
    `last_valid_pin` épingle `fallback` seule : 63 versions de la même source publiées, plus que le déclencheur de rétention."""

    root = tmp_path / "data"
    core = await started(root)
    pid, vid = await new_presentation(core)
    made = await edit(core, pid, vid, create(S1, "Ancienne"))
    assert made.status is EditStatus.APPLIED
    await core.stop()
    for version in range(1, 64):
        install_version(root / LIBRARY_DIR, LAB, version)
    path = next((root / "presentations").rglob("psv_*.json"))
    document = json.loads(path.read_text(encoding="utf-8"))
    scene = document["scenes"][0]
    scene["prefab"] = {"id": LAB, "version": live}
    scene["last_valid_pin"] = {"id": LAB, "version": fallback}
    scene["scene_variants"]["items"][1]["content"]["prefab"] = {"id": LAB, "version": stored_pin}
    scene["data"], scene["props"] = {"count": 1}, {}
    scene["scene_variants"]["items"][1]["content"]["data"] = {"count": 1}
    scene["scene_variants"]["items"][1]["content"]["props"] = {}
    scene["controls"] = []
    scene["scene_variants"]["items"][1]["content"]["controls"] = []
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return await started(root), root, pid, vid


async def test_a_version_pinned_only_by_a_stored_local_variant_and_one_pinned_only_by_a_last_valid_pin_survive_the_real_retention(tmp_path):
    core, root, pid, vid = await crafted_core(tmp_path)
    try:
        held = await core.studio_pins.pinned_versions([LAB])
        assert held[LAB] >= {3, 5, 62}, held  # the live pin, the stored local variant's pin and the fallback pin: one registry
        await core.prefabs.save(candidate(id=LAB, title="Retouche"), actor="user")  # 64th version: the retention pass runs
        live, archived = library_versions(root)
        assert {3, 5, 62} <= set(live), (live, archived)
        assert archived and 1 in archived and 2 in archived, "the retention really ran and archived the unpinned old versions"
        assert 4 not in live, "only the pinned old versions were kept"
    finally:
        await core.stop()


async def test_the_negative_control_a_pin_source_that_ignored_stored_local_variants_would_lose_the_version(tmp_path, monkeypatch):
    core, root, pid, vid = await crafted_core(tmp_path)
    try:
        monkeypatch.setattr(StudioScene, "held_pins", lambda self: frozenset({(self.prefab.prefab_id, self.prefab.version)}))
        await core.studio_pins.rebuild(core.presentation_studio_variants)
        await core.prefabs.save(candidate(id=LAB, title="Retouche"), actor="user")
        live, archived = library_versions(root)
        assert 3 in archived and 3 not in live, "without the Slice 17 pin source the stored variant's version is lost"
        assert 5 in live, "last_valid_pin is still pinned by the Slice 06 function"
    finally:
        await core.stop()


async def test_there_is_one_variant_pin_function_and_it_is_the_one_the_registry_reads(tmp_path):
    from jarvis.core import presentation_studio_service as service_module
    from jarvis.core import presentation_studio_variants as variants_module

    assert variants_module.variant_pins is service_module.variant_pins  # imported, not redefined
    core, root, pid, vid = await crafted_core(tmp_path)
    try:
        variant = await core.presentation_studio.get_variant(pid, vid)
        assert service_module.variant_pins(variant.scenes) == {(LAB, 62), (LAB, 3), (LAB, 5)}
        index = await core.presentation_studio_variants.pin_index()
        assert index[(pid, vid)] == service_module.variant_pins(variant.scenes)
    finally:
        await core.stop()


# ------------------------------------------------------------------ verrou de scène

async def test_every_write_of_a_local_variant_of_a_reloading_scene_is_refused_409_like_any_other_write(tmp_path):
    core = await started(tmp_path / "data")
    try:
        pid, vid = await new_presentation(core, (S1, S2))
        first = await edit(core, pid, vid, create(S1, "B"))
        other = first.ops[0]["scene_variant_id"]
        original = (await core.presentation_studio.get_variant(pid, vid)).scenes[0].scene_variants.current_id
        before = (tmp_path / "data").rglob("psv_*.json")
        snapshot = {p: p.read_bytes() for p in before}
        core.presentation_studio_reload._reloading[(pid, vid, S1)] = 1  # the scene is between publication and mount confirmation
        for op in (create(S1, "C"), select(S1, other), {"op": "scene_variant.rename", "scene_id": S1, "variant_id": other, "label": "Z"},
                   {"op": "scene_variant.delete", "scene_id": S1, "variant_id": other},
                   {"op": "scene_variant.restore_set", "scene_id": S1, "scene_variants": None}):
            error = await refused_409(edit(core, pid, vid, op))
            assert "being reloaded" in error.message
        assert {p: p.read_bytes() for p in snapshot} == snapshot, "nothing was written"
        # the other scene of the same variant is not locked, and neither are the reads and the preview
        assert (await edit(core, pid, vid, create(S2, "B2"))).status is EditStatus.APPLIED
        assert (await core.presentation_studio_scene_variants.describe(pid, vid, S1))["count"] == 2
        assert (await core.presentation_studio_scene_variants.preview(pid, vid, S1, other))["written"] is False
        core.presentation_studio_reload._reloading.clear()
        assert (await edit(core, pid, vid, select(S1, other))).status is EditStatus.APPLIED
        assert original and (await edit(core, pid, vid, select(S1, original))).status is EditStatus.APPLIED
    finally:
        await core.stop()


async def test_promote_is_refused_while_any_scene_of_the_source_variant_reloads_and_spends_no_number(tmp_path):
    core = await started(tmp_path / "data")
    try:
        pid, vid = await new_presentation(core, (S1, S2))
        other = (await edit(core, pid, vid, create(S1, "B"))).ops[0]["scene_variant_id"]
        counter = (await core.presentation_studio.get(pid)).presentation.variant_counter
        core.presentation_studio_reload._reloading[(pid, vid, S2)] = 1  # ANOTHER scene of the source reloads: the branch rule
        error = await refused_409(core.presentation_studio_scene_variants.promote(pid, vid, S1, other, {"title": "Promue"}))
        assert "retry in a few seconds" in error.message
        assert (await core.presentation_studio.get(pid)).presentation.variant_counter == counter
        core.presentation_studio_reload._reloading.clear()
        answer = await core.presentation_studio_scene_variants.promote(pid, vid, S1, other, {"title": "Promue"})
        assert answer["node"]["variant_number"] == counter + 1
    finally:
        await core.stop()


# ------------------------------------------------------------------ ce qu'un rechargement recharge

async def test_a_reload_changes_the_live_scene_only_and_the_stored_variants_keep_their_own_pin(tmp_path):
    core = await started(tmp_path / "data")
    try:
        pid, vid = await new_presentation(core)
        other = (await edit(core, pid, vid, create(S1, "B"))).ops[0]["scene_variant_id"]
        before = await core.presentation_studio.get_variant(pid, vid)
        stored_before = copy.deepcopy(before.scenes[0].scene_variants.get(other).content)
        result = await core.presentation_studio_reload.apply_source_edit(pid, vid, {
            "actor": "user", "basis": {"variant_revision": before.revision}, "scene_id": S1, "files": {"style": ".x{color:red}"}})
        assert result.status is S.REPINNED
        after = (await core.presentation_studio.get_variant(pid, vid)).scenes[0]
        assert after.prefab.prefab_id.startswith("presentation-studio.") and after.last_valid_pin is not None
        assert after.source_revision == before.scenes[0].source_revision + 1
        assert after.scene_variants.get(other).content == stored_before, "the stored variant keeps its pin and its values"
        assert after.scene_variants.current_id == before.scenes[0].scene_variants.current_id
        # the new source is not yet seen mounted: a create or a select would carry an unverified pin and is refused like a branch is
        for op in (create(S1, "C"), select(S1, other)):
            await refused_409_result(edit(core, pid, vid, op))
        # a rename and a delete do not move any pin: they go through
        assert (await edit(core, pid, vid, {"op": "scene_variant.rename", "scene_id": S1, "variant_id": other, "label": "B2"})).status \
            is EditStatus.APPLIED
        held = await core.studio_pins.pinned_versions(["jarvis.window", after.prefab.prefab_id])
        assert 1 in held["jarvis.window"] and after.prefab.version in held[after.prefab.prefab_id]
    finally:
        await core.stop()


async def refused_409_result(awaitable) -> None:
    result = await awaitable
    assert result.status is EditStatus.REFUSED and result.code == C.SCENE_RELOADING.value and result.http_status == 409, result.to_dict()
    assert "not seen mounted" in result.message


async def test_a_select_that_changes_the_pin_counts_as_a_manual_pin_change_for_the_hot_reload_bookkeeping(tmp_path):
    root = tmp_path / "data"
    install_version(root / LIBRARY_DIR, "lab.counter", 1)  # a second prefab for the stored variant to pin
    core = await started(root)
    try:
        pid, vid = await new_presentation(core)
        other = (await edit(core, pid, vid, create(S1, "B"))).ops[0]["scene_variant_id"]
        path = next((root / "presentations").rglob("psv_*.json"))
        document = json.loads(path.read_text(encoding="utf-8"))
        document["scenes"][0]["scene_variants"]["items"][1]["content"]["prefab"] = {"id": "lab.counter", "version": 1}
        document["scenes"][0]["scene_variants"]["items"][1]["content"]["data"] = {"count": 3}
        document["scenes"][0]["scene_variants"]["items"][1]["content"]["props"] = {}
        document["scenes"][0]["scene_variants"]["items"][1]["content"]["controls"] = []
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        before = (await core.presentation_studio.get_variant(pid, vid)).scenes[0]
        done = await edit(core, pid, vid, select(S1, other))
        assert done.status is EditStatus.APPLIED
        after = (await core.presentation_studio.get_variant(pid, vid)).scenes[0]
        assert after.prefab.prefab_id == "lab.counter" and after.last_valid_pin is None
        assert after.source_revision == before.source_revision + 1  # Slice 06's rule for an ordinary save that moves the pin
        assert after.scene_variants.get(before.scene_variants.current_id).content["prefab"] == {"id": "jarvis.window", "version": 1}
    finally:
        await core.stop()


# ------------------------------------------------------------------ assemblage (Slice 11)

async def test_assemble_produces_scenes_with_no_scene_variants_and_the_authoring_stack_ignores_the_key(tmp_path):
    from tests.fakes import presentation_studio_fake_author as fa
    from tests.fakes.presentation_studio_authoring_env import AuthoringEnv

    env = await AuthoringEnv(tmp_path / "e").start()
    brief, draft = fa.brief("directed"), fa.good_deck()
    out = await env.assemble(brief, draft)
    assert out.status == "delivered"
    pid = out.to_dict()["presentation_id"]
    view = await env.studio.get(pid)
    for variant in view.variants:
        assert all(scene.scene_variants is None and "scene_variants" not in scene.to_dict() for scene in variant.scenes)
    exploratory_brief, exploratory = fa.exploratory(3)
    delivered = await env.assemble(exploratory_brief, exploratory)
    assert delivered.status == "delivered"
    ids = [v["variant_id"] for v in delivered.to_dict()["variants"]]
    for variant_id in ids:
        shown = await env.studio.get_variant(delivered.to_dict()["presentation_id"], variant_id)
        assert all(scene.scene_variants is None for scene in shown.scenes)
