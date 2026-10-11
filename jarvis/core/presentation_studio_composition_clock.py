"""La carte de l'horloge de composition d'une variante, servie par Core (handoff jarvis-remotion-native-studio-playback-fix, Slice 04 ;
`docs/presentation-studio.md` > *Composition clock (Level 3)*).

À ne pas confondre avec `presentation_studio_composition.py` (Slice 19 : *composer* une variante enfant à partir de dimensions de
plusieurs sources) : ici « composition » est la composition **vidéo** (les scènes Remotion bout à bout) et son horloge.

Lecture seule : lit la variante (`PresentationStudioService.get_variant`) puis la composition **déclarée** de chaque pin
(`PrefabService.remotion_composition`, manifeste seulement : ni octet de source ni compilation) et rend la carte pure de
`jarvis/domain/composition_clock.py`, avec sa clé (Presentation, variante, pins). Rien n'est écrit, aucune horloge n'est tenue ici :
Core ne possède pas d'horloge de média pour la vidéo continue (contrat § 3).

Une variante qui n'a pas de vidéo n'est pas une erreur HTTP : la réponse dit `clock: null` et `problem: {code, message, scene_id}`
(variante vide, scène HTML, manifeste invalide, version inconnue ou altérée), pour que « Lire » soit désactivé avec sa raison (§ 4.2,
§ 4.11). Chaque calcul est journalisé (`core.presentation_studio.composition_clock_{built,refused}`), identifiants et comptes seulement.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jarvis.domain.composition_clock import (
    SCENE_INVALID, CompositionError, build_composition, composition_key, scene_manifest, to_wire,
)
from jarvis.ports.prefabs import PrefabStoreError

#: Une scène HTML (prefab non Remotion) : la variante n'a pas de vidéo à lire.
NOT_REMOTION = "composition_scene_not_remotion"


def pins_of(scenes: Any) -> list[tuple[str, str, int]]:
    """Les pins ordonnés `(scene_id, prefab_id, version)` d'une suite de scènes (`StudioScene`) : l'entrée de `composition_key`, la
    même pour cette vue et pour la vue de lecture (`presentation_studio_playback`)."""

    return [(scene.scene_id, scene.prefab.prefab_id, scene.prefab.version) for scene in scenes]


class PresentationStudioCompositionClock:
    def __init__(self, studio: Any, prefabs: Any, *, diagnostics: Any | None = None) -> None:
        self._studio = studio
        self._prefabs = prefabs
        self._diagnostics = diagnostics

    async def view(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        """`{presentation_id, variant_id, variant_revision, key, clock, problem}`. Une erreur de la variante elle-même (inconnue,
        corrompue) remonte en `PresentationStudioError`, comme les autres lectures ; une panne de disque du catalogue aussi."""

        variant = await self._studio.get_variant(presentation_id, variant_id)
        pins = pins_of(variant.scenes)
        key = composition_key(presentation_id, variant_id, pins)
        answer: dict[str, Any] = {"presentation_id": presentation_id, "variant_id": variant_id,
                                  "variant_revision": variant.revision, "key": key, "clock": None, "problem": None}
        try:
            manifests = []
            for scene_id, prefab_id, version in pins:
                try:
                    declared = await self._prefabs.remotion_composition(prefab_id, version)
                except PrefabStoreError as exc:
                    if exc.status >= 500:
                        raise   # a disk or root failure is a fault, answered 500 by the route boundary with its real cause
                    raise CompositionError(SCENE_INVALID, f"{scene_id}: {prefab_id}@{version} is not readable ({exc.code.value})",
                                           scene_id=scene_id) from exc
                if declared is None:
                    raise CompositionError(NOT_REMOTION, f"{scene_id} is not a Remotion scene: the variant has no video",
                                           scene_id=scene_id)
                manifests.append(scene_manifest(scene_id, declared))
            cmap = build_composition(manifests)
        except CompositionError as exc:
            answer["problem"] = {"code": exc.code, "message": exc.message, "scene_id": exc.scene_id}
            self._trace("core.presentation_studio.composition_clock_refused", "Variante sans horloge de composition",
                        level="warning", data={"presentation_id": presentation_id, "variant_id": variant_id, "code": exc.code,
                                               "scene_id": exc.scene_id, "scenes": len(pins)})
            return answer
        answer["clock"] = to_wire(cmap, key=key)
        self._trace("core.presentation_studio.composition_clock_built", "Horloge de composition de la variante calculee",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "key": key, "scenes": len(cmap.scenes),
                          "fps": cmap.fps, "frames": cmap.total_frames})
        return answer

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never fails a read-only view
            pass
