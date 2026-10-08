"""Cablage du rechargement a chaud dans Core (jarvis-interactive-presentation-studio, Slice 06).

Le vrai `JarvisCoreApplication` sous `tmp_path` : le registre des pins est celui du service des prefabs (conditions d'entree
de `docs/prefabs.md` > *Retention of studio scene sources*), il est construit au demarrage et lie a la scene vivante, la rafale
en attente est publiee a l'arret (`flush`), un redemarrage retrouve les scenes non confirmees, un magasin illisible ferme la
retention sans empecher Core de demarrer.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.prefab import PrefabRef
from jarvis.domain.presentation_studio_reload import ReloadStatus as S

pytestmark = pytest.mark.asyncio

SID = "pss_0000000000b1"


def scene_body() -> dict:
    return {"scene_id": SID, "prefab": {"id": "jarvis.window", "version": 1}, "title": "Fenetre", "props": {"density": "compact"},
            "data": {"body": "Texte"}}


async def started(root: Path) -> JarvisCoreApplication:
    core = JarvisCoreApplication(data_root=root)
    await core.start()
    return core


async def new_presentation(core: JarvisCoreApplication) -> tuple[str, str]:
    view = await core.presentation_studio.create({"title": "Atelier"})
    pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
    variant = await core.presentation_studio.get_variant(pid, vid)
    await core.presentation_studio.save_variant(pid, vid, {
        "expected_revision": variant.revision, "title": variant.title, "scenes": [scene_body()],
        "art_direction_id": None, "score_id": None})
    return pid, vid


def edit_body(revision: int, files: dict) -> dict:
    return {"actor": "user", "basis": {"variant_revision": revision}, "scene_id": SID, "files": files}


async def test_the_one_pin_registry_is_shared_by_the_prefab_service_the_studio_store_and_the_live_scene(tmp_path):
    core = await started(tmp_path / "data")
    try:
        registry = core.studio_pins
        assert core.prefabs._pin_registry is registry and core.presentation_studio._pins is registry
        assert registry.ready and core.presentation_studio_reload.stage is core.studio_stage
        pid, vid = await new_presentation(core)
        answer = await registry.pinned_versions(["jarvis.window", "presentation-studio.nobody"])
        assert answer == {"jarvis.window": frozenset({1}), "presentation-studio.nobody": frozenset()}
        assert registry.stats()["variants"] == 1
    finally:
        await core.stop()


async def test_a_restart_rebuilds_the_index_and_finds_the_scenes_whose_pin_was_never_seen_mounted(tmp_path):
    root = tmp_path / "data"
    core = await started(root)
    try:
        pid, vid = await new_presentation(core)
        variant = await core.presentation_studio.get_variant(pid, vid)
        result = await core.presentation_studio_reload.apply_source_edit(pid, vid, edit_body(variant.revision, {"style": ".x{color:red}"}))
        assert result.status is S.REPINNED
    finally:
        await core.stop()
    again = await started(root)
    try:
        pending = again.presentation_studio_reload.pending_scenes()
        assert [(entry.scene_id, entry.fallback) for entry in pending] == [(SID, PrefabRef("jarvis.window", 1))]
        held = await again.studio_pins.pinned_versions(["jarvis.window", pending[0].pin.prefab_id])
        assert held["jarvis.window"] == frozenset({1}) and held[pending[0].pin.prefab_id] == frozenset({1})
    finally:
        await again.stop()


async def test_the_pending_burst_is_published_at_shutdown_and_nothing_new_is_accepted_after(tmp_path):
    core = await started(tmp_path / "data")
    pid, vid = await new_presentation(core)
    variant = await core.presentation_studio.get_variant(pid, vid)
    core.prefab_drafts._quiet_s, core.prefab_drafts._max_wait_s = 30.0, 60.0         # the burst would wait half a minute
    pending = asyncio.ensure_future(core.presentation_studio_reload.apply_source_edit(
        pid, vid, edit_body(variant.revision, {"style": ".x{color:blue}"})))
    await asyncio.sleep(0.5)
    assert core.prefab_drafts.pending_ids                                                   # waiting on its quiet period
    await core.stop()
    result = await asyncio.wait_for(pending, 20)
    assert result.status is S.REPINNED and not core.prefab_drafts.pending_ids
    published = [p.name for p in (tmp_path / "data" / "prefabs").iterdir() if p.name.startswith("presentation-studio")]
    assert len(published) == 1                                                              # the draft reached the disk
    document = json.loads(next((tmp_path / "data" / "presentations").rglob("psv_*.json")).read_text(encoding="utf-8"))
    assert document["scenes"][0]["prefab"]["id"] == published[0] and document["scenes"][0]["last_valid_pin"] is not None


async def test_an_unreadable_presentation_closes_the_retention_but_never_stops_core(tmp_path):
    root = tmp_path / "data"
    core = await started(root)
    try:
        pid, vid = await new_presentation(core)
    finally:
        await core.stop()
    next((root / "presentations").rglob("psv_*.json")).write_text("{ torn", encoding="utf-8")
    again = await started(root)
    try:
        assert not again.studio_pins.ready and again.health.ready
        with pytest.raises(RuntimeError, match="incomplete"):
            await again.studio_pins.pinned_versions(["jarvis.window"])
    finally:
        await again.stop()
