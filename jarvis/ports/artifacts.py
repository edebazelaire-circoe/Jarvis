"""Ports du registre d'Artifacts, du ledger d'activité et des payloads (handoff session-context-recording, Slice 04).

Trois coutures :

- `ArtifactRepository` : lignes `artifacts` et `artifact_relations` (v6), sur
  la connexion partagée de l'état (adaptateur `sqlite_artifacts`) ;
- `ActivityLedger` : table `session_activity` (v6), même connexion
  (adaptateur `sqlite_session_activity`) ; les transitions de Session et de
  Context y écrivent **dans leur propre transaction** (`commit_switch`,
  `commit_contexts`, `insert_adopted_if_absent` prennent `activity=`) ;
- `ArtifactPayloadStore` : fichiers sous `<data_root>/artifacts/<artifact_id>/`
  (adaptateur `artifact_payloads`).

Les valeurs et les règles sont celles de `jarvis.domain.artifacts` et
`jarvis.domain.session_activity`. Contrat : `docs/artifacts.md`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from jarvis.domain.artifacts import Artifact, ArtifactPage, ArtifactQuery, ArtifactRelation
from jarvis.domain.session_activity import ActivityDraft, ActivityEvent, ActivityQuery
from jarvis.ports.workspace_board import BoardStoreError, BoardStoreUnavailable


class ArtifactStoreError(BoardStoreError):
    """Ligne illisible ou qui contredit ses colonnes clés ; jamais réparée (état canonique)."""

    code = "artifact_store_unreadable"


class ArtifactStoreUnavailable(BoardStoreUnavailable):
    """SQLite a refusé l'opération (verrou, E/S) ; la cause SQLite reste dans le message."""

    code = "artifact_store_failed"

    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(operation, reason)
        self.args = (f"artifact store {operation} failed: {reason}",)
        self.table = "artifacts"


class RelationDirection(StrEnum):
    #: Les origines de l'Artifact (ce dont il dérive).
    ORIGINS = "origins"
    #: Les Artifacts qui dérivent de lui.
    DEPENDENTS = "dependents"


@dataclass(frozen=True, slots=True)
class DeletedArtifacts:
    """Résultat d'une suppression validée : ids retirés de la base, dans l'ordre de suppression."""

    artifact_ids: tuple[str, ...]
    #: Événements `artifact.deleted` écrits dans la même transaction.
    events: tuple[ActivityEvent, ...]


class ArtifactRepository(Protocol):
    """Magasin durable du registre. Les erreurs de règle sont des `ArtifactError` (code du domaine)."""

    async def create_artifact(self, artifact: Artifact, *, relations: Sequence[ArtifactRelation] = (),
                              activity: Sequence[ActivityDraft] = ()) -> tuple[ActivityEvent, ...]:
        """Insère l'Artifact, ses relations et `activity` en **une** transaction.

        Refus : id déjà pris (`artifact_conflict`), Session ou Context inconnu,
        ou Context d'une autre Session (`invalid_artifact`), origine inconnue
        (`artifact_not_found`), cycle (`relation_cycle`).
        """
        ...

    async def update_artifact(self, previous: Artifact, updated: Artifact, *,
                              activity: Sequence[ActivityDraft] = ()) -> tuple[ActivityEvent, ...]:
        """Remplace `previous` par `updated` si la ligne est encore `previous` (comparer-échanger).

        Ligne changée entre-temps : `artifact_conflict` ; règle d'identité ou
        d'état terminal : `check_artifact_update`.
        """
        ...

    async def get_artifact(self, artifact_id: str) -> Artifact | None: ...

    async def query_artifacts(self, query: ArtifactQuery) -> ArtifactPage: ...

    async def pending_artifacts(self, *, limit: int, after: Artifact | None = None) -> Sequence[Artifact]:
        """Les Artifacts `pending`, du plus ancien au plus récent (reprise après arrêt brutal).

        `after` : curseur `(created_at, artifact_id)` du dernier lu ; la page
        suivante commence strictement après lui (un Artifact laissé `pending`
        ne bloque jamais ceux qui le suivent).
        """
        ...

    async def add_relations(self, relations: Sequence[ArtifactRelation], *,
                            activity: Sequence[ActivityDraft] = ()) -> tuple[ActivityEvent, ...]: ...

    async def relations_of(self, artifact_id: str, direction: RelationDirection, *,
                           limit: int) -> Sequence[ArtifactRelation]: ...

    async def delete_artifact(self, artifact_id: str, *, cascade: bool, now: datetime,
                              origin: str) -> DeletedArtifacts:
        """Suppression explicite (politique : `docs/artifacts.md` › *Deletion*). Base seulement,
        un `artifact.deleted` par Artifact dans la même transaction ; les dossiers sont
        retirés **après** le commit par l'appelant."""
        ...


class ActivityLedger(Protocol):
    async def append(self, drafts: Sequence[ActivityDraft]) -> tuple[ActivityEvent, ...]:
        """Ajoute les événements en une transaction, dans l'ordre ; rend leurs `seq`."""
        ...

    async def list(self, query: ActivityQuery) -> Sequence[ActivityEvent]:
        """`seq > after_seq`, filtres, `seq` croissant, au plus `limit`."""
        ...

    async def latest_seq(self) -> int:
        """Plus grand `seq` écrit (0 sur un ledger vide) : point de départ d'une queue."""
        ...


# ------------------------------------------------------------------ payloads

#: Codes stables des échecs de payload (`jarvis/adapters/artifact_payloads.py`).
PAYLOAD_UNSAFE = "artifact_payload_unsafe"
PAYLOAD_FAILED = "artifact_payload_failed"
#: Le fichier final existe déjà, ou un `.partial` d'une écriture précédente est là.
PAYLOAD_CONFLICT = "artifact_payload_conflict"


class ArtifactPayloadError(RuntimeError):
    def __init__(self, code: str, path: Path, reason: str) -> None:
        super().__init__(f"{code}: {path}: {reason}")
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PayloadInfo:
    """Ce qui est sur disque pour un payload : octets du fichier final et du `.partial` (`None` : absent)."""

    final_bytes: int | None
    partial_bytes: int | None


class ArtifactSpool(Protocol):
    """Écrivain en flux d'un payload (`<name>.partial`), pour les captures longues (Slices 06/07)."""

    @property
    def size(self) -> int: ...

    def write(self, data: bytes) -> int: ...

    def write_at(self, offset: int, data: bytes) -> None:
        """Réécrit des octets déjà écrits (en-tête WAV), sans changer la taille au-delà de la fin."""
        ...

    def sync(self) -> None:
        """`flush` + `fsync` : ce qui est écrit survit à un arrêt brutal."""
        ...

    def finalize(self) -> int:
        """`fsync`, ferme, renomme `.partial` -> nom final ; rend la taille."""
        ...

    def close(self) -> None:
        """Ferme sans finaliser : le `.partial` reste (preuve, reprise)."""
        ...


class ArtifactPayloadStore(Protocol):
    def root(self) -> Path:
        """`<data_root>/artifacts`, absolu."""
        ...

    def path_of(self, payload_ref: str) -> Path:
        """Chemin absolu d'une `payload_ref` validée (sans accès disque)."""
        ...

    def ensure_folder(self, artifact_id: str) -> Path: ...

    def open_spool(self, artifact_id: str, name: str) -> ArtifactSpool: ...

    def write_payload(self, artifact_id: str, name: str, data: bytes) -> int:
        """Écriture atomique d'un payload court (capture d'écran) ; rend la taille."""
        ...

    def inspect(self, artifact_id: str, name: str) -> PayloadInfo: ...

    def promote_partial(self, artifact_id: str, name: str) -> int:
        """Reprise : renomme un `.partial` laissé par un arrêt brutal en nom final ; rend sa taille."""
        ...

    def remove_folder(self, artifact_id: str) -> bool:
        """Retire `artifacts/<artifact_id>/` (après commit de la suppression) ; vrai s'il existait."""
        ...
