"""Chaque point d'appel de la porte du moteur est épinglé par la suite par défaut (Slice 10, reprise QA B2 et B3).

Une porte dont on peut supprimer un appel sans qu'un test rougisse n'en est pas une. Ici : un faux `studio` dont la porte REFUSE (et dont tout
ce qui est derrière lève), un faux étage qui enregistre tout ; pour chaque point d'appel (lire, éditer, prévisualiser, aperçu de scène, bloc de
détour, dernière porte avant l'étage), l'erreur typée 409 sort et RIEN n'est monté, montré ni lu ; puis un balayage de la source qui liste les
appels attendus (en supprimer un fait échouer ce test). Les épreuves de bout en bout sont dans `test_remotion_player.py` et dans le navigateur.
"""

from __future__ import annotations

from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_playback import PresentationStudioPlaybackService
from jarvis.core.presentation_studio_stage import StageError
from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode as C

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "jarvis" / "core"
PID = "pst_" + "a" * 32
VID = "psv_" + "b" * 32


class RefusingStudio:
    """The studio of a Presentation whose engine is NOT ready; anything past the gate is a failure of the test."""

    def __init__(self, *, gate: bool = True, native: bool = True) -> None:
        self.gate, self.native, self.calls = gate, native, []

    async def require_engine(self, presentation_id, action):
        self.calls.append(("require_engine", action))
        if self.gate:
            raise PresentationStudioError(C.ENGINE_UNAVAILABLE, "remotion is unavailable: the Remotion capability is not_installed. Repair: install it")

    async def require_native_pin(self, presentation_id, prefab_id, version, *, what):
        self.calls.append(("require_native_pin", prefab_id))
        if not self.native:
            raise PresentationStudioError(C.ENGINE_UNSUPPORTED, f"{what} is only an adapter case for remotion: declared, not usable")

    async def require_native_scenes(self, presentation_id, scenes):
        self.calls.append(("require_native_scenes", None))
        if not self.native:
            raise PresentationStudioError(C.ENGINE_UNSUPPORTED, "a stored scene is not native")

    def __getattr__(self, name):   # everything else is "behind the gate": reaching it is the bug
        raise AssertionError(f"studio.{name} was reached past the engine gate")


class RecordingStage:
    stage_object_id = None

    def __init__(self) -> None:
        self.calls: list[str] = []

    def begin(self, run_id): self.calls.append("begin")

    async def show(self, payload): self.calls.append("show"); return True

    async def release(self): self.calls.append("release")

    async def stage_aux(self, *args): self.calls.append("stage_aux"); return "aux"

    async def reveal_aux(self, object_id): self.calls.append("reveal_aux")

    async def retire(self, ids): self.calls.append("retire")

    async def reclaim(self): self.calls.append("reclaim"); return ()


class ArtGate:
    async def require_art_direction(self, *args, **kwargs):
        raise AssertionError("art direction was reached past the engine gate")


class EditStub:
    def add_commit_listener(self, listener): pass


def playback(studio) -> tuple[PresentationStudioPlaybackService, RecordingStage]:
    stage = RecordingStage()
    return PresentationStudioPlaybackService(studio, EditStub(), stage, SimpleNamespace(mode=None), gate=ArtGate()), stage


START = {"actor": "user", "presentation_id": PID, "role": "user_presenter"}
EDIT = {"actor": "user", "mode": "preview", "basis": {"variant_revision": 1},
        "ops": [{"op": "control.set", "scene_id": "pss_000000000001", "control_id": "headline", "value": "x"}]}


async def test_play_is_refused_by_the_gate_before_anything_is_read_compiled_or_staged():
    studio = RefusingStudio()
    service, stage = playback(studio)
    with pytest.raises(PresentationStudioError) as caught:
        await service.start(START)
    assert caught.value.code is C.ENGINE_UNAVAILABLE and caught.value.status == 409
    assert studio.calls == [("require_engine", "play")] and stage.calls == []


async def test_edit_is_refused_by_the_gate_before_the_variant_is_read():
    studio = RefusingStudio()
    with pytest.raises(PresentationStudioError) as caught:
        await PresentationStudioEditService(studio).edit(PID, VID, EDIT)
    assert caught.value.code is C.ENGINE_UNAVAILABLE and studio.calls == [("require_engine", "edit")]


async def test_the_overlay_render_is_refused_by_the_gate_before_the_variant_is_read():
    studio = RefusingStudio()
    with pytest.raises(PresentationStudioError) as caught:
        await PresentationStudioEditService(studio).render_overlay(PID, VID, 1, [])
    assert caught.value.code is C.ENGINE_UNAVAILABLE and studio.calls == [("require_engine", "preview")]


async def test_a_scene_variant_preview_is_refused_by_the_gate_and_shows_nothing():
    studio = RefusingStudio()
    service, stage = playback(studio)
    scene = SimpleNamespace(scene_id="pss_000000000001", prefab=SimpleNamespace(prefab_id="x.y", version=1),
                            payload=lambda: pytest.fail("the payload of a refused preview was built"))
    with pytest.raises(PresentationStudioError) as caught:
        await service.show_preview(PID, VID, scene, scene_variant_id="v", revision=1, timeout_s=5.0)
    assert caught.value.code is C.ENGINE_UNAVAILABLE
    assert studio.calls == [("require_engine", "preview")] and stage.calls == []


async def test_a_preview_block_that_is_not_native_is_refused_even_when_the_engine_is_ready():
    studio = RefusingStudio(gate=False, native=False)
    service, stage = playback(studio)
    service._state = SimpleNamespace(active=True, phase=__import__("jarvis.domain.presentation_studio_playback", fromlist=["Phase"]).Phase.PAUSED)
    service._presentation_id, service._variant_id = PID, VID
    scene = SimpleNamespace(scene_id="pss_000000000001", prefab=SimpleNamespace(prefab_id="html.prefab", version=1),
                            payload=lambda: pytest.fail("shown"))
    with pytest.raises(PresentationStudioError) as caught:
        await service.show_preview(PID, VID, scene, scene_variant_id="v", revision=1, timeout_s=5.0)
    assert caught.value.code is C.ENGINE_UNSUPPORTED and stage.calls == []


async def test_a_detour_block_that_is_not_native_is_refused_before_the_catalogue_or_the_stage():
    studio = RefusingStudio(gate=False, native=False)
    service, stage = playback(studio)
    service._presentation_id, service._variant_id = PID, VID
    block = SimpleNamespace(prefab_id="html.prefab", version=1, props={}, data={}, key="html.prefab@1")
    refused = await service._validate_detour(block)
    assert refused is not None and refused.status.value == "refused" and refused.reason == "detour_invalid"
    assert "declared, not usable" in refused.message and stage.calls == []
    assert studio.calls == [("require_native_pin", "html.prefab")]


async def test_the_last_door_before_the_stage_refuses_a_non_native_block_whatever_path_chose_it():
    studio = RefusingStudio(gate=False, native=False)
    service, stage = playback(studio)
    service._presentation_id = PID
    with pytest.raises(StageError) as caught:
        await service._require_native_on_stage("html.prefab", 1, "scene pss_000000000001")
    assert caught.value.code == "presentation_studio_engine_unsupported" and "declared, not usable" in caught.value.message
    assert stage.calls == []
    ok = RefusingStudio(gate=False, native=True)
    service2, _ = playback(ok)
    service2._presentation_id = PID
    await service2._require_native_on_stage("remotion.prefab", 1, "scene")


# ------------------------------------------------------------------ the scan: deleting a call site fails this test

def source(name: str) -> str:
    return (CORE / name).read_text(encoding="utf-8")


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


def test_the_call_sites_of_the_gate_are_the_ones_the_contract_lists():
    playback_source = source("presentation_studio_playback.py")
    assert count(r'self\._studio\.require_engine\(presentation_id, "play"\)', playback_source) == 1, "play: before anything is compiled or staged"
    assert count(r"self\._studio\.require_native_scenes\(presentation_id, variant\.scenes\)", playback_source) == 1, "play: every stored scene"
    assert count(r"await self\._require_native_on_stage\(", playback_source) == 2, "stage: the scene shown and the detour block staged"
    assert count(r"self\._studio\.require_native_pin\(", playback_source) == 2, "detour validation and the last door"
    edit_source = source("presentation_studio_edit.py")
    assert count(r'self\._studio\.require_engine\(presentation_id, "edit"\)', edit_source) == 1
    assert count(r'self\._studio\.require_engine\(presentation_id, "preview"\)', edit_source) == 1, "render_overlay"
    preview_source = source("presentation_studio_preview.py")
    assert count(r'self\._studio\.require_engine\(presentation_id, "preview"\)', preview_source) == 1
    assert count(r"self\._studio\.require_native_pin\(", preview_source) == 1
    service_source = source("presentation_studio_service.py")
    assert count(r"self\._scenes\.require_native\(", service_source) == 2, "scene-add and scene-local variants (_check_scenes)"
    assert "gate.require_native(" in source("presentation_studio_scene_catalog.py")
    # The hot reload checks the new pin through `check_scenes` (so the same scene-add check), before anything is written or patched.
    assert "self._studio.check_scenes(" in source("presentation_studio_reload.py")
    # No call site may use the triage that accepts `adapter`.
    for name in ("presentation_studio_playback.py", "presentation_studio_edit.py", "presentation_studio_preview.py",
                 "presentation_studio_service.py", "presentation_studio_scene_catalog.py", "presentation_studio_engine_gate.py"):
        assert "require_compatible" not in source(name), name
