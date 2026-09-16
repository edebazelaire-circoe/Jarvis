"""Ports de la scène constellation (handoff jarvis-constellation-scene-runtime, Slice 02).

Trois coutures autour du `SceneService` de Core :

- `SceneCommandSink` : l'entrée des commandes de scène (runtime, cerveau,
  utilisateur). L'autorité est appliquée par le réducteur du domaine
  (`apply_scene_command`), jamais par l'appelant ;
- `SceneReader` : la lecture de la scène active, des patchs récents (pour le
  transport, Slice 03) et de l'historique des objets archivés ;
- `SceneRepository` : la persistance durable, implémentée par
  `jarvis/adapters/sqlite_scene.py` et injectée par le composition root.

Une commande refusée par le domaine n'est pas une erreur : elle rend un
`SceneUpdate` dont l'issue le dit. Une scène indisponible ou une écriture qui
échoue, si : elles lèvent une `SceneStoreError` au code stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from jarvis.domain.scene import SceneCommand, SceneObject, ScenePatch, SceneSnapshot, SceneUpdate


class SceneStoreErrorCode(StrEnum):
    """Motif stable d'une erreur de magasin, pour le journal et le transport."""

    #: Le fichier porte un `schema_version` plus récent que ce code : refusé,
    #: jamais migré ni effacé.
    SCHEMA_NEWER = "schema_newer"
    #: Version absente, illisible ou inconnue (plus ancienne comprise), ou base
    #: qui n'est pas une base de scène.
    SCHEMA_UNKNOWN = "schema_unknown"
    #: Fichier illisible par SQLite, contrôle d'intégrité en échec, ou ligne
    #: stockée qui ne se décode pas en scène valide.
    CORRUPTED = "corrupted"
    #: Le fichier ne s'ouvre pas ou ne s'écrit pas (disque, droits, verrou).
    STORAGE_IO = "storage_io"
    #: La révision stockée ne suit pas celle que Core croit tenir : deux
    #: écrivains, ou un état divergé. Rien n'est écrit.
    REVISION_CONFLICT = "revision_conflict"
    #: Scène jamais chargée (refus au démarrage) ou déjà fermée.
    UNAVAILABLE = "unavailable"


class SceneStoreError(RuntimeError):
    """Erreur explicite du magasin de scène. `code` est stable, le message dit la cause réelle."""

    def __init__(self, code: SceneStoreErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class SceneUnavailableError(SceneStoreError):
    """La scène n'est pas servie : refusée au démarrage, divergée ou fermée."""


class ScenePersistenceError(SceneStoreError):
    """Une commande appliquée n'a pas pu être persistée : révision inchangée, rien de visible."""


@dataclass(frozen=True, slots=True)
class ScenePatchWindow:
    """Patchs postérieurs à une révision connue du consommateur.

    `resync_required` : l'anneau borné ne couvre plus l'écart (ou la scène
    n'est pas celle que le consommateur croit tenir). `patches` est alors vide
    et le consommateur relit l'instantané (Décision 20).
    """

    scene_id: str
    revision: int
    patches: tuple[ScenePatch, ...]
    resync_required: bool


@dataclass(frozen=True, slots=True)
class ArchivedSceneObject:
    """Forme historique d'un objet archivé (`disposition = archived`).

    `revision` : révision du patch qui l'a archivé. Un même identifiant peut
    apparaître plusieurs fois si sa pierre tombale a été oubliée puis l'objet
    recréé et archivé de nouveau.
    """

    object: SceneObject
    revision: int
    archived_at: str


class SceneCommandSink(Protocol):
    """Entrée des commandes de scène, possédée par Core.

    `apply` sérialise les commandes, persiste avant d'exposer et rend le
    `SceneUpdate` du domaine. Lève `SceneUnavailableError` si la scène n'est
    pas servie, `ScenePersistenceError` si l'écriture échoue (la révision
    n'avance pas, aucun lecteur ne voit la commande).
    """

    async def apply(self, command: SceneCommand) -> SceneUpdate: ...


class SceneReader(Protocol):
    """Lecture seule de la scène. Lève `SceneUnavailableError` si elle n'est pas servie."""

    async def snapshot(self) -> SceneSnapshot: ...

    async def patches_since(self, revision: int, *, scene_id: str | None = None) -> ScenePatchWindow: ...

    async def wait_for_revision(self, after: int, *, timeout_s: float) -> int:
        """Rendre la révision courante dès qu'elle dépasse `after`, ou à l'échéance (≤ 30 s).

        Primitive locale du long-poll : la scène n'est jamais diffusée sur
        `CoreEventBus`. Lève `SceneUnavailableError` si la scène est ou devient
        indisponible pendant l'attente.
        """
        ...

    async def archived_history(self, *, object_id: str | None = None, limit: int = 100) -> tuple[ArchivedSceneObject, ...]: ...


class SceneRepository(Protocol):
    """Persistance durable de la scène active et de son historique.

    - `initialize` ouvre le stockage et refuse (`SceneStoreError`) une version
      plus récente ou inconnue et un fichier corrompu, sans jamais l'effacer ;
    - `load` rend la scène persistée, ou `None` si aucune n'a encore été créée ;
    - `create` enregistre une scène vide et son `scene_id` stable ;
    - `commit` écrit, en une seule transaction, l'état qui résulte de
      `patch` appliqué à `previous` ; il refuse si la révision stockée n'est
      pas `previous.revision` (`REVISION_CONFLICT`) ;
    - `archived_history` lit l'historique alimenté par les `archive_object`.
    """

    async def initialize(self) -> None: ...

    async def load(self) -> SceneSnapshot | None: ...

    async def create(self, scene_id: str) -> SceneSnapshot: ...

    async def commit(self, previous: SceneSnapshot, patch: ScenePatch, result: SceneSnapshot) -> None: ...

    async def archived_history(self, *, object_id: str | None = None, limit: int = 100) -> tuple[ArchivedSceneObject, ...]: ...

    async def close(self) -> None: ...
