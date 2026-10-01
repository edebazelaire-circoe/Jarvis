"""Registre d'Artifacts et ledger d'activité dans Core (handoff session-context-recording, Slice 04).

Façade unique pour les Slices de capture (05-07), d'enrichissement (08) et
d'API/MCP (09) : créer, écrire, finaliser, enrichir, relier, interroger et
supprimer un Artifact, et écrire ou lire l'activité de Session, sans connaître
les tables ni le disque (ports `ArtifactRepository`, `ActivityLedger`,
`ArtifactPayloadStore`). Contrat : `docs/artifacts.md`.

Règles tenues ici :

- chaque fait du registre et son événement d'activité s'écrivent dans **une**
  transaction (le magasin reçoit `activity=`) ;
- `finalize` ne rend jamais un succès `complete` sans payload final sur
  disque : la taille enregistrée est celle mesurée ;
- suppression explicite seulement : base d'abord, puis dossiers ; un dossier
  qui résiste est signalé (`orphan_folders`, journal), jamais une suppression
  annulée ; aucune rétention automatique ;
- reprise au démarrage (`recover_pending`) : un Artifact resté `pending` d'une
  vie précédente devient `partial` (octets présents) ou `failed`
  (`artifact_payload_missing`), avec son `artifact.finalized` ;
- miroir diagnostic (`DiagnosticSink`, `runtime/trace.jsonl`) : identifiants,
  états et codes seulement, jamais de texte ni de média.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.domain.artifacts import (
    PARTIAL_SUFFIX, Artifact, ArtifactError, ArtifactErrorCode, ArtifactKind, ArtifactPage, ArtifactQuery,
    ArtifactRelation, ArtifactRelationKind, ArtifactState, enrich_artifact, fail_artifact, finalize_artifact,
    new_artifact,
)
from jarvis.domain.session_activity import ActivityDraft, ActivityEvent, ActivityKind, ActivityQuery
from jarvis.domain.v2 import utc_now
from jarvis.ports.artifacts import (
    ActivityLedger, ArtifactPayloadError, ArtifactPayloadStore, ArtifactRepository, ArtifactSpool, PayloadInfo,
    RelationDirection,
)
from jarvis.ports.v2 import DiagnosticSink

#: Codes posés par la reprise et la finalisation.
RECOVERED = "artifact_recovered"
PAYLOAD_MISSING = "artifact_payload_missing"
INTERRUPTED = "artifact_interrupted"
#: Artifacts `pending` traités par lot au démarrage.
RECOVERY_BATCH = 128


@dataclass(frozen=True, slots=True)
class DeletionResult:
    artifact_ids: tuple[str, ...]
    #: Dossiers non retirés après le commit (journalisés) : à retirer à la main.
    orphan_folders: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PayloadFiles:
    """Où est (ou serait) le payload d'un Artifact, et ce qui est sur disque. Aucune écriture."""

    final_path: Path
    partial_path: Path
    info: PayloadInfo


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    partial: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    #: Laissés `pending` (payload illisible ou refusé) : réessayés au prochain démarrage.
    skipped: tuple[str, ...] = ()


class ArtifactService:
    """Porte d'écriture du registre et du ledger dans Core. Voir l'en-tête du module."""

    def __init__(self, repository: ArtifactRepository, ledger: ActivityLedger, payloads: ArtifactPayloadStore, *,
                 diagnostics: DiagnosticSink | None = None, clock: Callable[[], datetime] = utc_now) -> None:
        self._repo = repository
        self._ledger = ledger
        self._payloads = payloads
        self._diagnostics = diagnostics
        self._clock = clock

    # ------------------------------------------------------------ acquisition

    async def create(
        self,
        *,
        kind: ArtifactKind,
        source: str,
        jarvis_session_id: str | None = None,
        context_id: str | None = None,
        payload_name: str | None = None,
        started_at: datetime | None = None,
        mime_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        origins: Iterable[tuple[ArtifactRelationKind, str]] = (),
        capture_id: str | None = None,
    ) -> Artifact:
        """Nouvel Artifact `pending` (identité fixée, D07), ses origines et `artifact.created`, en une transaction."""

        now = self._clock()
        artifact = new_artifact(kind=kind, source=source, now=now, jarvis_session_id=jarvis_session_id,
                                context_id=context_id, payload_name=payload_name, started_at=started_at,
                                mime_type=mime_type, metadata=metadata)
        relations = tuple(ArtifactRelation(artifact.artifact_id, relation, origin, now) for relation, origin in origins)
        event = ActivityDraft(
            kind=ActivityKind.ARTIFACT_CREATED, occurred_at=now, jarvis_session_id=jarvis_session_id,
            context_id=context_id,
            artifact_ids=tuple(dict.fromkeys((artifact.artifact_id, *(r.origin_artifact_id for r in relations))))[:16],
            capture_ids=() if capture_id is None else (capture_id,),
            data={"artifact_kind": kind.value, "source": source, "origins": len(relations)})
        await self._repo.create_artifact(artifact, relations=relations, activity=(event,))
        self._trace("core.artifact.created", "Artifact créé",
                    data={"artifact_id": artifact.artifact_id, "kind": kind.value, "source": source,
                          "jarvis_session_id": jarvis_session_id, "context_id": context_id,
                          "origins": len(relations)})
        return artifact

    def open_spool(self, artifact: Artifact) -> ArtifactSpool:
        """Écrivain en flux du payload réservé (`<name>.partial`) d'un Artifact `pending`."""

        name = self._pending_payload_name(artifact)
        return self._payloads.open_spool(artifact.artifact_id, name)

    async def store_payload(self, artifact_id: str, data: bytes, **finalize: Any) -> Artifact:
        """Payload court (capture d'écran) : écriture atomique puis `finalize` (`complete` par défaut)."""

        artifact = await self.get(artifact_id)
        self._payloads.write_payload(artifact.artifact_id, self._pending_payload_name(artifact), data)
        return await self.finalize(artifact_id, **finalize)

    async def finalize(
        self,
        artifact_id: str,
        *,
        state: ArtifactState = ArtifactState.COMPLETE,
        ended_at: datetime | None = None,
        duration_ms: int | None = None,
        width: int | None = None,
        height: int | None = None,
        text: str | None = None,
        error_code: str | None = None,
    ) -> Artifact:
        """`pending` -> `complete`/`partial`, avec `artifact.finalized`. `size_bytes` est **mesuré**.

        Un Artifact à payload ne devient `complete` que si le fichier final est
        sur disque (`invalid_artifact` sinon : finaliser d'abord le spool).
        """

        previous = await self.get(artifact_id)
        size = None
        if previous.payload_ref is not None:
            info = self._payloads.inspect(previous.artifact_id, previous.payload_name or "")
            size = info.final_bytes
            if size is None and state is ArtifactState.COMPLETE:
                raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT,
                                    f"artifact {artifact_id}: no final payload on disk; finalize the spool first")
        updated = finalize_artifact(previous, now=self._clock(), state=state, size_bytes=size, ended_at=ended_at,
                                    duration_ms=duration_ms, width=width, height=height, text=text,
                                    error_code=error_code)
        await self._commit(previous, updated, self._finalized_event(updated, recovered=False))
        return updated

    async def fail(self, artifact_id: str, *, error_code: str, ended_at: datetime | None = None) -> Artifact:
        """`pending` -> `failed` ; un payload éventuel reste sur disque (preuve)."""

        previous = await self.get(artifact_id)
        updated = fail_artifact(previous, now=self._clock(), error_code=error_code, ended_at=ended_at)
        await self._commit(previous, updated, self._finalized_event(updated, recovered=False))
        return updated

    async def enrich(self, artifact_id: str, updates: Mapping[str, Any], *, origin: str = "service") -> Artifact:
        """Enrichissement (D07) dans tout état ; champs d'acquisition intacts ; `artifact.enrichment.updated`."""

        previous = await self.get(artifact_id)
        updated = enrich_artifact(previous, updates, now=self._clock())
        keys = ",".join(sorted(updates))[:256]
        event = ActivityDraft(kind=ActivityKind.ARTIFACT_ENRICHMENT_UPDATED, occurred_at=updated.updated_at,
                              jarvis_session_id=updated.jarvis_session_id, context_id=updated.context_id,
                              artifact_ids=(artifact_id,), data={"keys": keys, "origin": origin})
        await self._repo.update_artifact(previous, updated, activity=(event,))
        self._trace("core.artifact.enriched", "Artifact enrichi",
                    data={"artifact_id": artifact_id, "keys": len(updates), "origin": origin})
        return updated

    async def relate(self, artifact_id: str, relation: ArtifactRelationKind, origin_artifact_id: str) -> None:
        """Provenance ajoutée après coup (idempotent ; cycle refusé)."""

        await self._repo.add_relations((ArtifactRelation(artifact_id, relation, origin_artifact_id, self._clock()),))

    # ------------------------------------------------------------ lecture

    async def get(self, artifact_id: str) -> Artifact:
        artifact = await self._repo.get_artifact(artifact_id)
        if artifact is None:
            raise ArtifactError(ArtifactErrorCode.ARTIFACT_NOT_FOUND, f"artifact {str(artifact_id)[:80]!r} does not exist")
        return artifact

    async def query(self, query: ArtifactQuery) -> ArtifactPage:
        return await self._repo.query_artifacts(query)

    async def relations(self, artifact_id: str, direction: RelationDirection) -> tuple[ArtifactRelation, ...]:
        return tuple(await self._repo.relations_of(artifact_id, direction, limit=256))

    def payload_path(self, artifact: Artifact) -> str | None:
        """Chemin absolu du payload final (pour un lecteur local), dérivé de `payload_ref`."""

        return None if artifact.payload_ref is None else str(self._payloads.path_of(artifact.payload_ref))

    def payload_files(self, artifact: Artifact) -> PayloadFiles | None:
        """Chemins du payload final et du `.partial`, et leurs tailles (réparation d'une capture, Slice 05).

        `None` sans payload réservé ; `ArtifactPayloadError` si le dossier est refusé (jonction...).
        """

        name = artifact.payload_name
        if name is None or artifact.payload_ref is None:
            return None
        final = self._payloads.path_of(artifact.payload_ref)
        return PayloadFiles(final_path=final, partial_path=final.with_name(f"{name}{PARTIAL_SUFFIX}"),
                            info=self._payloads.inspect(artifact.artifact_id, name))

    # ------------------------------------------------------------ activité

    async def record(self, kind: ActivityKind, *, jarvis_session_id: str | None = None, context_id: str | None = None,
                     artifact_ids: tuple[str, ...] = (), capture_ids: tuple[str, ...] = (),
                     data: Mapping[str, Any] | None = None) -> ActivityEvent:
        """Événement factuel hors transition du registre (`capture.started`, `capture.gap`...)."""

        draft = ActivityDraft(kind=kind, occurred_at=self._clock(), jarvis_session_id=jarvis_session_id,
                              context_id=context_id, artifact_ids=artifact_ids, capture_ids=capture_ids,
                              data={} if data is None else data)
        (event,) = await self._ledger.append((draft,))
        return event

    async def activity(self, query: ActivityQuery) -> tuple[ActivityEvent, ...]:
        return tuple(await self._ledger.list(query))

    async def latest_seq(self) -> int:
        return await self._ledger.latest_seq()

    # ------------------------------------------------------------ suppression

    async def delete(self, artifact_id: str, *, cascade: bool = False, origin: str = "user") -> DeletionResult:
        """Suppression **explicite** : base (et `artifact.deleted`) d'abord, puis dossiers.

        Politique : `SQLiteArtifactRepository.delete_artifact`. Un dossier qui
        ne part pas (fichier verrouillé, entrée inattendue) n'annule rien : il
        est rendu dans `orphan_folders` et journalisé en erreur.
        """

        deleted = await self._repo.delete_artifact(artifact_id, cascade=cascade, now=self._clock(), origin=origin)
        orphans = []
        for removed in deleted.artifact_ids:
            try:
                self._payloads.remove_folder(removed)
            except ArtifactPayloadError as exc:
                orphans.append(removed)
                self._trace("core.artifact.folder_not_removed", f"Dossier d'Artifact non retiré : {str(exc)[:300]}",
                            level="error", data={"artifact_id": removed, "code": exc.code})
        self._trace("core.artifact.deleted", "Artifacts supprimés",
                    data={"artifact_id": artifact_id, "deleted": len(deleted.artifact_ids), "cascade": cascade,
                          "orphan_folders": len(orphans), "origin": origin})
        return DeletionResult(artifact_ids=deleted.artifact_ids, orphan_folders=tuple(orphans))

    # ------------------------------------------------------------ reprise

    async def recover_pending(self) -> RecoveryReport:
        """Au démarrage de Core, **avant** tout écrivain : les `pending` d'une vie précédente sont orphelins.

        - payload final déjà là (renommage fait, base pas mise à jour) ou
          `.partial` non vide (promu en nom final) : `partial`, code
          `artifact_recovered`, taille mesurée ;
        - aucun octet : `failed`, code `artifact_payload_missing` (un `.partial`
          vide reste sur disque) ; sans payload réservé : `failed`,
          `artifact_interrupted` ;
        - payload illisible ou refusé (lien, jonction) : laissé `pending`,
          journalisé, réessayé au prochain démarrage.

        Ne lève pas (sauf annulation) : un registre illisible est journalisé
        et Core démarre. Une reprise propre à une capture (en-tête WAV réparé,
        Slice 05) doit passer **avant** cet appel.
        """

        partial: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        try:
            while True:
                batch = [a for a in await self._repo.pending_artifacts(limit=RECOVERY_BATCH)
                         if a.artifact_id not in skipped]
                if not batch:
                    break
                for artifact in batch:
                    outcome = await self._recover_one(artifact)
                    {"partial": partial, "failed": failed, "skipped": skipped}[outcome].append(artifact.artifact_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: said with its code, Core keeps starting
            self._trace("core.artifact.recovery_failed", f"Reprise des Artifacts interrompue : {type(exc).__name__}: "
                        f"{str(exc)[:200]}", level="error",
                        data={"code": str(getattr(exc, "code", "artifact_store_failed")),
                              "exception_type": type(exc).__name__})
        report = RecoveryReport(tuple(partial), tuple(failed), tuple(skipped))
        self._trace("core.artifact.recovery", "Reprise des Artifacts pending",
                    level="warning" if partial or failed or skipped else "info",
                    data={"partial": len(partial), "failed": len(failed), "skipped": len(skipped)})
        return report

    async def recover(self, artifact_id: str, *, duration_ms: int | None = None) -> Artifact:
        """Reprise d'**un** Artifact `pending` d'une vie précédente, mêmes règles que `recover_pending`.

        Pour un propriétaire qui répare d'abord son payload (capture, Slice 05) ;
        rend l'Artifact après coup (resté `pending` si son payload est refusé).
        Déjà terminal : rendu tel quel.
        """

        artifact = await self.get(artifact_id)
        if artifact.is_pending:
            await self._recover_one(artifact, duration_ms=duration_ms)
            artifact = await self.get(artifact_id)
        return artifact

    async def _recover_one(self, artifact: Artifact, *, duration_ms: int | None = None) -> str:
        now = max(self._clock(), artifact.updated_at)
        name = artifact.payload_name
        try:
            info = None if name is None else self._payloads.inspect(artifact.artifact_id, name)
            if info is not None and info.final_bytes is not None:
                size = info.final_bytes
            elif info is not None and info.partial_bytes:
                size = self._payloads.promote_partial(artifact.artifact_id, name or "")
            else:
                size = None
        except ArtifactPayloadError as exc:
            self._trace("core.artifact.recovery_skipped", f"Payload d'un Artifact pending illisible : {str(exc)[:300]}",
                        level="error", data={"artifact_id": artifact.artifact_id, "code": exc.code})
            return "skipped"
        if size is None:
            code = INTERRUPTED if name is None else PAYLOAD_MISSING
            updated = fail_artifact(artifact, now=now, error_code=code)
        else:
            updated = finalize_artifact(artifact, now=now, state=ArtifactState.PARTIAL, size_bytes=size,
                                        duration_ms=duration_ms, error_code=RECOVERED)
        await self._commit(artifact, updated, self._finalized_event(updated, recovered=True))
        return "partial" if updated.state is ArtifactState.PARTIAL else "failed"

    # ------------------------------------------------------------ interne

    @staticmethod
    def _pending_payload_name(artifact: Artifact) -> str:
        if not artifact.is_pending:
            raise ArtifactError(ArtifactErrorCode.ARTIFACT_NOT_PENDING,
                                f"artifact {artifact.artifact_id} is {artifact.state.value}; acquisition is closed")
        if artifact.payload_name is None:
            raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT,
                                f"artifact {artifact.artifact_id} reserved no payload")
        return artifact.payload_name

    @staticmethod
    def _finalized_event(artifact: Artifact, *, recovered: bool) -> ActivityDraft:
        return ActivityDraft(
            kind=ActivityKind.ARTIFACT_FINALIZED, occurred_at=artifact.updated_at,
            jarvis_session_id=artifact.jarvis_session_id, context_id=artifact.context_id,
            artifact_ids=(artifact.artifact_id,),
            data={"state": artifact.state.value, "artifact_kind": artifact.kind.value,
                  "size_bytes": artifact.size_bytes, "error_code": artifact.error_code, "recovered": recovered})

    async def _commit(self, previous: Artifact, updated: Artifact, event: ActivityDraft) -> None:
        await self._repo.update_artifact(previous, updated, activity=(event,))
        self._trace("core.artifact.finalized", "Artifact finalisé",
                    level="warning" if updated.state is not ArtifactState.COMPLETE else "info",
                    data={"artifact_id": updated.artifact_id, "state": updated.state.value,
                          "error_code": updated.error_code, "size_bytes": updated.size_bytes,
                          "recovered": event.data.get("recovered", False)})

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not undo a committed write
            pass
