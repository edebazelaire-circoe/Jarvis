"""Scenes du Studio contre les prefabs (handoff jarvis-interactive-presentation-studio, Slice 04).

Seul point de Core qui relie une `StudioScene` au catalogue des prefabs : le pin
existe-t-il (`PrefabService.manifest`), les valeurs sont-elles valides pour le
manifeste (`PrefabService.validate_instance`, **pas** une seconde validation),
les contrôles curés tiennent-ils dans ce manifeste (`check_scene`, pur) ? Et la
réponse à « qu'est-ce qui s'édite ici ? » (`describe`).

Refus : `scene_incompatible` (400) quand la scène et le manifeste divergent,
`prefab_unavailable` (409) quand le pin n'existe pas, est altéré ou que le
catalogue ne répond pas (la vraie cause de prefab est dans le message), `storage_io`
(500) quand c'est le disque du catalogue. Un imprévu n'est pas capturé ici : la
frontière HTTP le journalise en `error` avec sa vraie cause.
"""

from __future__ import annotations

from typing import Any

from jarvis.domain.prefab import PrefabInstanceRef, PrefabManifest
from jarvis.domain.presentation_studio_checks import (
    PresentationStudioError, PresentationStudioErrorCode as C, clip,
)
from jarvis.domain.presentation_studio_scene import StudioScene, check_scene, describe_scene
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from jarvis.ports.presentation_studio import PrefabCatalog


class SceneCatalog:
    def __init__(self, prefabs: PrefabCatalog) -> None:
        self._prefabs = prefabs

    async def manifest_of(self, scene: StudioScene) -> PrefabManifest:
        try:
            return await self._prefabs.manifest(scene.prefab.prefab_id, scene.prefab.version)
        except PrefabStoreError as exc:
            code = C.STORAGE_IO if exc.code is PrefabStoreErrorCode.STORAGE_IO else C.PREFAB_UNAVAILABLE
            raise PresentationStudioError(
                code, f"scene {scene.scene_id}: {scene.prefab.prefab_id}@{scene.prefab.version}: "
                      f"{exc.code.value}: {exc.message}") from exc

    async def _controls_ok(self, scene: StudioScene) -> PrefabManifest:
        manifest = await self.manifest_of(scene)
        problems = check_scene(scene, manifest)
        if problems:
            raise PresentationStudioError(C.SCENE_INCOMPATIBLE, f"scene {scene.scene_id}: " + "; ".join(problems))
        return manifest

    async def _instance_problem(self, scene: StudioScene) -> str | None:
        """Le détail de `PrefabService.validate_instance` quand les valeurs ne conviennent pas, sinon `None`."""

        verdict = await self._prefabs.validate_instance(
            PrefabInstanceRef(scene.prefab.prefab_id, scene.prefab.version, scene.props, scene.data))
        if verdict.ok:
            return None
        if verdict.code is not PrefabStoreErrorCode.INVALID_DEFINITION:
            raise PresentationStudioError(C.PREFAB_UNAVAILABLE, clip(f"scene {scene.scene_id}: {verdict.detail}"))
        return clip(f"scene {scene.scene_id}: {verdict.detail}")

    async def check(self, scene: StudioScene) -> None:
        """Le pin existe, ses valeurs sont valides pour lui, ses contrôles tiennent dans son manifeste. Sinon `PresentationStudioError`."""

        await self._controls_ok(scene)
        problem = await self._instance_problem(scene)
        if problem is not None:
            raise PresentationStudioError(C.SCENE_INCOMPATIBLE, problem)

    async def describe(self, scene: StudioScene, order: int) -> dict[str, Any]:
        """`describe_scene`. Contrôles incompatibles : `scene_incompatible`. Valeurs d'instance incomplètes (une donnée
        requise encore absente) : la scène se décrit quand même, avec ce détail dans `problems`, pour qu'on puisse la régler."""

        manifest = await self._controls_ok(scene)
        description = describe_scene(scene, manifest, order=order)
        problem = await self._instance_problem(scene)
        if problem is not None:
            description["problems"] = [*description["problems"], problem]
        return description
