"""The run surface of Variants: where a playback run is shown (handoff jarvis-remotion-native-studio-playback-fix, Slice 09).

Until Slice 09 a run was shown on a Board window of its own (`studio-stage-<run_id>`, category `studio_stage`) plus a floating
band: the "floating viewer" the user rejected (contract `docs/presentation-studio.md` > *2026-10 § 2*). The run now plays inside
**Variants**, in its one Player. Core no longer writes anything on the global scene for a run: what the run shows is this
**memory** surface, which the page reads (`GET /v1/presentation-studio/playback/surface`) and mounts in the Variants Player.

- **One surface per run, patched, never recreated.** `show(payload)` replaces the shown block (a new revision); a payload already
  shown writes nothing. Its id, `variants-run-<run_id>`, is the object id the Variants Player mounts the run under, so the hot
  reload's mount reports and the playback view's `stage_object_id` still name exactly one surface.
- **Validated like a scene window was.** A block goes through the prefab catalogue (`validate_instance`) before it is accepted,
  defaults filled; a refusal is `prefab_invalid` with the catalogue's reason (the run pauses and says it), never shown.
- **Detours are overlays inside the same surface** (decided by agent 0, contract § 2): staged hidden, revealed, retired. Never a
  Board window.
- **Memory only** (R6): nothing persisted, nothing on the Board; a Core restart has no run and no surface.
- **Legacy reclaim.** Board windows an older Core left (`studio_stage` / `studio_aux`) are archived by `LegacyStageReclaimer`
  (`presentation_studio_stage.py`) at Core start and before each run: one last pass, by id list and by namespaced scan.
- **A pin source.** `pins()` names every pin the surface shows (scene, detours), so a frame on screen is never archived under the
  Player (contract § 8, `StudioPinRegistry`).
- **Frame events.** A frame mounted under the surface id posts its `state` / `notify` events to `/v1/prefabs/events` like a Board
  window did; `PrefabEventService` checks them the same way and a `state` writes the surface's data (`write_data`, under this
  surface's lock), so the values a frame committed survive a hot reload (carried by `StageWindows.current`). Never the variant.

`StageWindows` (`presentation_studio_reload_stage.py`) reads and re-pins this surface for the hot reload; the playback service
drives it through its `Stage` protocol. Contract: `docs/presentation-studio.md` > *Variants run surface (Level 3, Slice 09)*.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from jarvis.core.presentation_studio_stage import StageError
from jarvis.domain.prefab import PrefabInstanceRef, PrefabRef, clip_message
from jarvis.domain.scene import ScenePayload, ScenePrefabRef
from jarvis.ports.v2 import DiagnosticSink

SURFACE_ID_PREFIX = "variants-run-"
#: The detour stack of the playback machine (`MAX_AUX_STACK`), plus room for an overlay being retired.
MAX_OVERLAYS = 8
TRACE_PREFIX = "core.presentation_studio"


class InstanceValidator(Protocol):
    """`PrefabService.validate_instance`: `{ok, code, detail, props, data}` for one block."""

    async def validate_instance(self, ref: PrefabInstanceRef) -> Any: ...


class Reclaimer(Protocol):
    async def reclaim(self) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class Overlay:
    overlay_id: str
    title: str
    block: ScenePrefabRef
    visible: bool = False

    def to_wire(self) -> dict[str, Any]:
        return {"overlay_id": self.overlay_id, "title": self.title, "visible": self.visible, "prefab": _block_wire(self.block)}


class RunSurface:
    """See the module header. One instance per Core, one run at a time (the playback service's lock serialises its writers;
    the hot reload's `repin` is a compare-and-set under this surface's own lock)."""

    def __init__(self, *, validator: InstanceValidator | None = None, reclaimer: Reclaimer | None = None,
                 diagnostics: DiagnosticSink | None = None) -> None:
        self._validator, self._reclaimer, self._diagnostics = validator, reclaimer, diagnostics
        self._run: str | None = None
        self._shown: ScenePayload | None = None
        self._scene_id: str | None = None
        self._overlays: dict[str, Overlay] = {}
        self._revision = 0
        self._lock = asyncio.Lock()
        self._changed = asyncio.Event()

    # ------------------------------------------------------------ reads

    @property
    def stage_object_id(self) -> str | None:
        """The surface id (`variants-run-<run_id>`) once the run showed something, else `None`."""

        return None if self._run is None or self._shown is None else SURFACE_ID_PREFIX + self._run

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def reopens(self) -> int:
        """Always 0: nobody can close the surface (it is not a window); kept for the playback service's former probe."""

        return 0

    def snapshot(self) -> dict[str, Any] | None:
        """What the page mounts (`GET .../playback/surface`): `None` when no run shows anything."""

        surface_id = self.stage_object_id
        if surface_id is None or self._shown is None:
            return None
        block = self._shown.prefab
        return {"surface_id": surface_id, "run_id": self._run, "revision": self._revision, "scene_id": self._scene_id,
                "title": self._shown.title,
                "prefab": None if block is None else _block_wire(block),
                "overlays": [o.to_wire() for o in self._overlays.values()]}

    def owns(self, object_id: str) -> bool:
        """Is `object_id` this surface (or one of its overlays)? The frame events of these ids are the surface's, not the Board's."""

        return isinstance(object_id, str) and object_id.startswith(SURFACE_ID_PREFIX)

    def current_block(self, object_id: str) -> ScenePrefabRef | None:
        """The live block of THIS surface (`None` when the id is not the surface on screen, or nothing is shown)."""

        overlay = self._overlays.get(object_id)
        if overlay is not None:
            return overlay.block
        if object_id != self.stage_object_id or self._shown is None:
            return None
        return self._shown.prefab

    def pins(self) -> set[tuple[str, int]]:
        """Pin source (`StudioPinRegistry.add_source`): synchronous, in memory, `(prefab_id, version)` pairs."""

        found: set[tuple[str, int]] = set()
        if self._shown is not None and self._shown.prefab is not None:
            found.add((self._shown.prefab.prefab_id, self._shown.prefab.version))
        for overlay in self._overlays.values():
            found.add((overlay.block.prefab_id, overlay.block.version))
        return found

    async def wait_for_revision(self, revision: int, *, timeout_s: float) -> int:
        """Wait until the surface moves past `revision` (or the timeout); returns the revision now. For observers and tests."""

        deadline = asyncio.get_running_loop().time() + timeout_s
        while self._revision <= revision:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), remaining)
            except TimeoutError:
                break
        return self._revision

    # ------------------------------------------------------------ the run (the playback service's `Stage` protocol)

    def begin(self, run_id: str) -> None:
        self._run, self._shown, self._scene_id, self._overlays = run_id, None, None, {}
        self._bump()

    async def show(self, payload: ScenePayload, *, scene_id: str | None = None) -> bool:
        """Show `payload` (the scene `scene_id` of the variant: the Player swaps to a preloaded frame of ANOTHER scene, and takes a new pin
        of the SAME scene as a hot reload) on the surface. `True` when what is shown changed. Never blocks on anything but the catalogue check."""

        if self._run is None:
            raise StageError("stage_not_begun", "no run owns the surface")
        if payload == self._shown and scene_id == self._scene_id:
            return False
        block = payload.prefab
        if block is not None:
            block = await self._validated(block, "scene")
            payload = replace(payload, prefab=block)
        async with self._lock:
            if payload == self._shown and scene_id == self._scene_id:
                return False
            self._shown, self._scene_id = payload, scene_id
            self._bump()
        self._trace("stage_shown", "Scene de la lecture montree dans Variantes",
                    data={"object_id": self.stage_object_id, "prefab": block.key if block else None, "revision": self._revision})
        return True

    async def release(self) -> None:
        if self._run is None and self._shown is None:
            return
        surface_id = self.stage_object_id
        self._run, self._shown, self._scene_id, self._overlays = None, None, None, {}
        self._bump()
        self._trace("stage_released", "Surface de lecture de Variantes liberee", data={"object_id": surface_id})

    async def stage_aux(self, aux_id: str, title: str, block: ScenePrefabRef) -> str:
        """A detour: an overlay **hidden at birth** inside the surface (never a Board window)."""

        if self._run is None:
            raise StageError("stage_not_begun", "no run owns the surface")
        if len(self._overlays) >= MAX_OVERLAYS:
            raise StageError("stage_invalid", f"at most {MAX_OVERLAYS} overlays on the run surface")
        checked = await self._validated(block, f"detour {aux_id}")
        overlay_id = f"{SURFACE_ID_PREFIX}{self._run}-{aux_id}"
        async with self._lock:
            self._overlays[overlay_id] = Overlay(overlay_id, title, checked)
            self._bump()
        self._trace("aux_staged", "Detour monte dans la surface de Variantes, masque", data={"object_id": overlay_id,
                                                                                            "prefab": checked.key})
        return overlay_id

    async def reveal_aux(self, object_id: str) -> None:
        async with self._lock:
            found = self._overlays.get(object_id)
            if found is None:
                raise StageError("unknown_object", "no such overlay on the run surface")
            self._overlays[object_id] = replace(found, visible=True)
            self._bump()
        self._trace("aux_revealed", "Detour affiche dans Variantes", data={"object_id": object_id})

    async def retire(self, object_ids: Sequence[str]) -> None:
        """Drop overlays (an id already gone is not a failure: retiring it has nothing left to do)."""

        async with self._lock:
            gone = [i for i in object_ids if self._overlays.pop(i, None) is not None]
            if gone:
                self._bump()
        if gone:
            self._trace("archived", "Detours retires de la surface de Variantes", data={"ids": len(gone)})

    async def reclaim(self) -> tuple[str, ...]:
        """Board windows an older Core left (`studio_stage` / `studio_aux`): archived once. Nothing of the surface to take back."""

        if self._reclaimer is None:
            return ()
        return await self._reclaimer.reclaim()

    # ------------------------------------------------------------ frame events (`PrefabEventService`)

    async def write_data(self, object_id: str, pin: tuple[str, int], compute: Any) -> Any:
        """A frame's `state` event: under the lock, the block on `object_id` must still be `pin`; `compute(current_data)` returns
        `(result, merged_data | None)`. Writes `merged_data` (memory) and returns `result` with the new revision; `None` when the
        object is not on the surface any more or shows another pin."""

        async with self._lock:
            block = self.current_block(object_id)
            if block is None or (block.prefab_id, block.version) != tuple(pin):
                return None
            result, merged = compute(dict(block.data))
            if merged is None:
                return result
            changed = ScenePrefabRef(block.prefab_id, block.version, dict(block.props), dict(merged))
            if object_id in self._overlays:
                self._overlays[object_id] = replace(self._overlays[object_id], block=changed)
            else:
                self._shown = replace(self._shown, prefab=changed)
            self._bump()
            return replace(result, revision=self._revision)

    # ------------------------------------------------------------ the hot reload (`StageWindows.repin`)

    async def repin(self, object_id: str, *, expect: PrefabRef, to: PrefabRef, props: Mapping[str, Any],
                    data: Mapping[str, Any]) -> str | None:
        """Compare-and-set of the shown pin. Returns `None` when applied (or already there), else the refusal code
        (`stage_missing`, `stage_changed`); a block the catalogue refuses raises `StageError("prefab_invalid")`."""

        verdict = self._compare(object_id, expect, to)
        if verdict != "apply":
            return verdict
        block = await self._validated(ScenePrefabRef(to.prefab_id, to.version, dict(props), dict(data)), "hot reload")
        async with self._lock:
            verdict = self._compare(object_id, expect, to)   # again, under the lock: the run may have moved during the check
            if verdict != "apply":
                return verdict
            self._shown = replace(self._shown, prefab=block)
            self._bump()
        self._trace("stage_repinned", "Surface de Variantes re-epinglee par le rechargement",
                    data={"object_id": object_id, "prefab": block.key, "revision": self._revision})
        return None

    # ------------------------------------------------------------ internals

    def _compare(self, object_id: str, expect: PrefabRef, to: PrefabRef) -> str | None:
        """`apply`, `None` (already there), `stage_missing` or `stage_changed`."""

        if object_id != self.stage_object_id or self._shown is None or self._shown.prefab is None:
            return "stage_missing"
        shown = PrefabRef(self._shown.prefab.prefab_id, self._shown.prefab.version)
        if shown == to:
            return None
        return "apply" if shown == expect else "stage_changed"

    async def _validated(self, block: ScenePrefabRef, what: str) -> ScenePrefabRef:
        """The catalogue's check, closed by default (no validator, a fault: refused), defaults filled."""

        if self._validator is None:
            return block
        ref = PrefabInstanceRef(block.prefab_id, block.version, block.props, block.data)
        try:
            result = await self._validator.validate_instance(ref)
        except Exception as exc:  # noqa: BLE001 - closed by default, said with its real class
            raise StageError("prefab_catalog_unavailable", f"{what}: {block.key}: {type(exc).__name__}") from exc
        if not getattr(result, "ok", False):
            code = getattr(getattr(result, "code", None), "value", None) or "invalid"
            raise StageError("prefab_invalid", clip_message(f"{what}: {block.key}: {code}: {getattr(result, 'detail', '') or code}"))
        try:
            return ScenePrefabRef(block.prefab_id, block.version, dict(result.props), dict(result.data))
        except (TypeError, ValueError) as exc:
            raise StageError("prefab_invalid", clip_message(f"{what}: {block.key}: the defaulted block is invalid: {exc}")) from exc

    def _bump(self) -> None:
        self._revision += 1
        self._changed.set()

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(f"{TRACE_PREFIX}.{kind}", message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a surface operation
            pass


def _block_wire(block: ScenePrefabRef) -> dict[str, Any]:
    return {"id": block.prefab_id, "version": block.version, "props": dict(block.props), "data": dict(block.data)}
