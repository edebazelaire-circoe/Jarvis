"""Live read seam of the master Remotion project planner (`docs/remotion-master-project.md` §2, handoff
jarvis-remotion-master-project-studio-export Slice 03).

Assembles the live inputs of one variant, read only: the variant and its presentation engine from `PresentationStudioService`, each
active pin through `PrefabService.manifest` + `PrefabService.remotion_source` (today's guards and SHA-256 checks), the props/data defaults
exactly as the snapshot packager freezes them. Then the pure planner decides. Nothing is written, no process starts. The live readiness
route (Slice 05), Studio open, Variants and the agent read this one seam; the frozen package goes through `frozen_inputs` directly.
"""

from __future__ import annotations

from typing import Any, Protocol

from jarvis.domain.prefab import validate_value
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode
from jarvis.domain.remotion_master_project import MasterProjectPlan, PinSource, live_inputs, plan_master
from jarvis.ports.prefabs import PrefabStoreError
from jarvis.ports.v2 import DiagnosticSink


class _Studio(Protocol):
    async def get(self, presentation_id: str) -> Any: ...


class _Prefabs(Protocol):
    async def manifest(self, prefab_id: str, version: int) -> Any: ...

    async def remotion_source(self, prefab_id: str, version: int) -> Any: ...


class MasterProjectReader:
    def __init__(self, *, studio: _Studio, prefabs: _Prefabs, diagnostics: DiagnosticSink | None = None) -> None:
        self._studio = studio
        self._prefabs = prefabs
        self._diagnostics = diagnostics

    async def live_plan(self, presentation_id: str, variant_id: str, *, trace: bool = True) -> MasterProjectPlan:
        """The plan of the variant as it is now. An unknown presentation or variant raises `PresentationStudioError` (the route's 404);
        a pin that cannot be read is NOT an error: it is the plan's `master_source_unavailable` / `master_engine_not_remotion`.
        `trace=False`: no `core.remotion_master.planned` line (the Studio status poll, Slice 05, recomputes the key to say `stale`)."""

        view = await self._studio.get(presentation_id)
        variant = next((v for v in view.variants if v.variant_id == variant_id), None)
        if variant is None:
            raise PresentationStudioError(PresentationStudioErrorCode.UNKNOWN_VARIANT, f"variant {variant_id} is not in {presentation_id}")
        pins: dict[tuple[str, int], PinSource] = {}
        for scene in variant.scenes:
            pin = (scene.prefab.prefab_id, scene.prefab.version)
            if pin not in pins:
                pins[pin] = await self._pin(*pin)
        plan = plan_master(live_inputs(view.presentation, variant, pins))
        if trace:
            self._emit(plan)
        return plan

    async def _pin(self, prefab_id: str, version: int) -> PinSource:
        label = f"{prefab_id}@{version}"
        try:
            manifest = await self._prefabs.manifest(prefab_id, version)
            if manifest.source is None:
                return PinSource.not_remotion(f"{label} is an HTML prefab, not a Remotion source")
            source = await self._prefabs.remotion_source(prefab_id, version)
        except PrefabStoreError as exc:
            # Not a failure of the read: an unreadable pin is a typed readiness fact. The store's own code says what happened.
            return PinSource.unavailable(f"{label} is {exc.code.value.replace('_', ' ')}")
        props, _ = validate_value(manifest.props, {}, "props")
        data, _ = validate_value(manifest.data, {}, "data")
        return PinSource.remotion(source, props_defaults=props if isinstance(props, dict) else {},
                                  data_defaults=data if isinstance(data, dict) else {})

    def _emit(self, plan: MasterProjectPlan) -> None:
        if self._diagnostics is None:
            return
        data: dict[str, Any] = {"presentation_id": plan.presentation_id, "variant_id": plan.variant_id,
                                "variant_revision": plan.variant_revision, "status": plan.status.value}
        if plan.ready:
            data.update(project_key=plan.project_key, scenes=len(plan.scenes), files=plan.totals.files if plan.totals else 0)
        else:
            data.update(reason=plan.reason.value if plan.reason else "", scene_ids=list(plan.scene_ids))
        self._diagnostics.emit("core.remotion_master.planned", "Plan du projet Remotion de la variante calculé", data=data)
