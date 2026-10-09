"""Scene variant preview state of the playback service (handoff jarvis-interactive-presentation-studio, Slice 17).

The stage window can show a *preview state*: a scene rendered in memory (never written) with a scene-local variant selected,
started by the user while the run is PAUSED. It is memory only and ephemeral: it ends on `end_preview`, on the timeout, on any
playback command (the service's `_dispatch` calls `_end_preview_locked`), on a committed edit, on stop and on a crash, and every exit
repaints the canonical scene or releases the stage. Contract: `docs/presentation-studio.md` > *Scene-local variant contract*.

A mixin, not a second service: it uses the playback service's own lock, stage, state and plan (one lock, one stage, one truth),
and is kept in its own module only so that the playback service file stays one responsibility long.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from jarvis.core.presentation_studio_stage import StageError
from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.domain.presentation_studio_playback import Phase


def _clip(value: object, limit: int = 300) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


@dataclass(slots=True)
class Preview:
    scene_id: str
    scene_variant_id: str
    timer: "asyncio.Task[Any] | None" = None


class ScenePreviewMixin:
    """Methods of `PresentationStudioPlaybackService`; see the module header. Expects `_lock`, `_stage`, `_state`, `_plan`,
    `_tasks`, `_preview`, `_sync_stage`, `_notice` and `_trace` from the service."""

    async def show_preview(self, presentation_id: str, variant_id: str, scene: Any, *, scene_variant_id: str, revision: int,
                           timeout_s: float) -> dict[str, Any]:
        """Show `scene` (already rendered in memory by the edit engine, never written) on the stage window, in a user-started
        PREVIEW state. Only for the variant the run plays and only while the run is PAUSED (the audience never sees a preview
        of a live, moving run). The state is ephemeral: it ends on `end_preview`, on the timeout, on any playback command, on a
        committed edit, on stop and on a crash; every exit repaints the canonical scene (or releases the stage). "Not possible"
        is an answer, `{staged: false, reason}`; a stage fault is a real error and is raised."""

        async with self._lock:
            if not self._state.active or (presentation_id, variant_id) != (self._presentation_id, self._variant_id):
                return {"staged": False, "reason": "no_run_on_this_variant"}
            if self._state.phase is not Phase.PAUSED:
                return {"staged": False, "reason": "run_not_paused"}
            await self._end_preview_locked("replaced", repaint=False)
            await self._stage.show(scene.payload())
            preview = Preview(scene.scene_id, scene_variant_id)
            self._preview = preview
            preview.timer = asyncio.get_running_loop().create_task(self._preview_timeout(preview, timeout_s))
            self._tasks.add(preview.timer)
            preview.timer.add_done_callback(self._tasks.discard)
            self._trace("preview_shown", "Apercu de variante locale sur la fenetre de scene", data={
                "run_id": self._state.run_id, "scene_id": scene.scene_id, "scene_variant_id": scene_variant_id,
                "timeout_s": timeout_s})
            return {"staged": True}

    async def end_preview(self, reason: str, *, presentation_id: str | None = None) -> bool:
        """Cancel the preview state if there is one (and it is on this Presentation): the stage shows the canonical scene again."""

        async with self._lock:
            if self._preview is None or (presentation_id is not None and presentation_id != self._presentation_id):
                return False
            await self._end_preview_locked(reason, repaint=True)
            return True

    async def _preview_timeout(self, preview: "Preview", timeout_s: float) -> None:
        try:
            await asyncio.sleep(timeout_s)
            async with self._lock:
                if self._preview is preview:
                    await self._end_preview_locked("timeout", repaint=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - captured as an error row: this runs in a background task, nothing awaits it
            self._trace("preview_timeout_failed", "Fin d'apercu par delai en echec", level="error",
                        data={"error_class": type(exc).__name__, "error": _clip(exc)})

    def _forget_preview(self) -> None:
        """Drop the state without touching the stage (the caller repaints or releases it)."""

        preview, self._preview = self._preview, None
        if preview is not None and preview.timer is not None and preview.timer is not asyncio.current_task():
            preview.timer.cancel()

    async def _end_preview_locked(self, reason: str, *, repaint: bool) -> None:
        if self._preview is None:
            return
        scene_id = self._preview.scene_id
        self._forget_preview()
        if repaint and self._state.active and self._plan is not None:
            try:
                await self._sync_stage()
            except (StageError, PresentationStudioError) as exc:
                self._notice("stage_sync_after_preview_failed")
                self._trace("playback_stage_failed", "La fenetre de scene n'est pas revenue de l'apercu", level="error",
                            data={"command": "preview_end", "error": _clip(exc.message), "run_id": self._state.run_id})
        self._trace("preview_ended", "Apercu de variante locale termine", data={
            "run_id": self._state.run_id, "scene_id": scene_id, "reason": reason, "repainted": repaint})
