"""`PrefabService.remotion_composition` : la composition déclarée d'une version Remotion, lue dans le manifeste (Slice 12).

Vrai `PrefabService` sur dossiers temporaires. Ni octet de source relu, ni compilation : la ligne de temps de la partition ne dépend
jamais du code de la scène. Un prefab HTML n'a pas de composition (`None`), une version inconnue est une erreur typée.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import FilePrefabLibrary
from jarvis.core.prefab_service import PrefabService
from jarvis.domain.remotion_timeline import build_frame_map
from jarvis.ports.prefabs import PrefabStoreError
from tests.fakes.prefabs import install_version
from tests.fakes.remotion_scene import scene_candidate

NOW = datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
SCENE = "presentation-studio.p000000000001.s000000000001"


@pytest.fixture
async def prefabs(tmp_path: Path):
    package, data = tmp_path / "package", tmp_path / "data"
    package.mkdir()
    data.mkdir()
    install_version(package, "jarvis.counter", title="Base counter")
    service = PrefabService(FilePrefabLibrary(package, data), clock=lambda: NOW)
    await service.save(scene_candidate(), actor="user")
    return service


async def test_a_remotion_version_reports_the_composition_its_manifest_declares(prefabs):
    composition = await prefabs.remotion_composition(SCENE, 1)
    assert composition == {"id": "Scene", "width": 1280, "height": 720, "fps": 30, "duration_in_frames": 90}
    fmap = build_frame_map("s1", composition, [type("A", (), {"anchor_id": "beat", "at_ms": 1000})()])
    assert (fmap.composition_id, fmap.fps, fmap.duration_frames, fmap.frame_of("beat")) == ("Scene", 30, 90, 30)


async def test_an_html_prefab_has_no_composition_and_an_unknown_version_is_a_typed_error(prefabs):
    assert await prefabs.remotion_composition("jarvis.counter", 1) is None
    with pytest.raises(PrefabStoreError):
        await prefabs.remotion_composition(SCENE, 99)
    with pytest.raises(PrefabStoreError):
        await prefabs.remotion_composition("nobody.here", 1)


async def test_the_answer_is_a_copy_the_caller_cannot_use_to_change_the_catalogue(prefabs):
    first = await prefabs.remotion_composition(SCENE, 1)
    first["fps"] = 1
    assert (await prefabs.remotion_composition(SCENE, 1))["fps"] == 30
