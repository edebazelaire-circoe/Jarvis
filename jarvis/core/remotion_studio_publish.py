"""Remotion Studio -> variante : la cible d'une publication (handoff jarvis-remotion-native-studio-playback-fix, Slice 12).

Le Studio (`RemotionStudioService`) possède l'espace de travail ; la variante appartient au Studio de présentations. Ce pont, câblé par
`v2_app`, ne fait que deux choses et n'écrit rien lui-même :

- `current` : le pin EXACT de la scène dans la variante et la révision de la variante (pour la détection de conflit) ;
- `publish` : la SEULE porte d'écriture d'une source de scène, `PresentationStudioReloadService.apply_source_edit`, avec l'acteur
  `user` (la publication est un geste confirmé de l'utilisateur ; le cerveau n'a aucun chemin vers `POST .../studio/publish`), la
  base `variant_revision` lue juste avant, et `files: {sources, assets}`. Garde, compilation réelle, nouvelle version immuable,
  compare-and-set du pin, `last_valid_pin`, rapport de montage et retour arrière sont ceux de cette porte : aucun second écrivain.

Contrat : `docs/presentation-studio.md` › *Remotion Studio round trip (Level 3, Slice 12)*.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.domain.presentation_studio_reload import variant_scene
from jarvis.domain.remotion_studio import StudioError, StudioErrorCode as C, StudioPin


class ScenePublisher(Protocol):
    async def current(self, presentation_id: str, variant_id: str, scene_id: str) -> tuple[StudioPin, int]:
        """`(pin de la scène, révision de la variante)` ; lève `StudioError` (cible inconnue, document illisible)."""

    async def publish(self, presentation_id: str, variant_id: str, scene_id: str, revision: int,
                      files: Mapping[str, Any]) -> Any:
        """Rend le `ReloadResult` de la porte d'édition de source (tous ses statuts) ; lève `StudioError` pour une erreur codée."""


def _refusal(exc: PresentationStudioError) -> StudioError:
    """Une erreur codée de la variante garde SON code (`publish_code`) et son statut HTTP : jamais re-étiquetée en générique."""

    return StudioError(C.PUBLISH_REFUSED, exc.message, extra={"publish_code": exc.code.value}, status=exc.status)


class VariantScenePublisher:
    """`ScenePublisher` sur le vrai Studio de présentations (lecture de la variante, porte `apply_source_edit`)."""

    def __init__(self, presentations: Any, reload: Any) -> None:
        self._presentations = presentations
        self._reload = reload

    async def current(self, presentation_id: str, variant_id: str, scene_id: str) -> tuple[StudioPin, int]:
        try:
            variant = await self._presentations.get_variant(presentation_id, variant_id)
            scene = variant_scene(variant, scene_id)
        except PresentationStudioError as exc:
            raise _refusal(exc) from None
        return StudioPin(scene.prefab.prefab_id, scene.prefab.version), variant.revision

    async def publish(self, presentation_id: str, variant_id: str, scene_id: str, revision: int,
                      files: Mapping[str, Any]) -> Any:
        body = {"actor": "user", "basis": {"variant_revision": revision}, "scene_id": scene_id, "files": dict(files)}
        try:
            return await self._reload.apply_source_edit(presentation_id, variant_id, body)
        except PresentationStudioError as exc:
            raise _refusal(exc) from None


__all__ = ["ScenePublisher", "VariantScenePublisher"]
