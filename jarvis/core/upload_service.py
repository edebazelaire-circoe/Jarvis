"""Fichiers téléversés dans Core (handoff jarvis-unified-chat-and-board-drop, Slice 07).

Façade sur `ArtifactService` (`create` / `open_spool` / `finalize` / `fail`) :
aucune table, aucun chemin propre. Règles pures : `jarvis/domain/uploads.py`.
Contrat : `docs/chat.md` › *Attachments*.

Ce que tient ce module :

- **flux borné** : le corps est lu par morceaux de 64 Kio ; jamais plus de
  64 Kio en mémoire (l'en-tête reniflé), jamais de copie temporaire ; la
  borne (`JARVIS_UPLOAD_MAX_BYTES`) est vérifiée à chaque morceau ;
- **type reniflé avant création** : l'en-tête décide `mime_type` et le nom
  de payload (`upload.<ext>`), fixés à la création de l'Artifact ;
- **identité rejouable** : `jart_up_<sha256(client_upload_id)[:40]>`. Même id
  déjà `complete`, mêmes octets (taille et empreinte) → rejeu 200 ; autres
  octets, ou essai précédent en échec → 409 `upload_conflict` ; encore en
  cours → 409 `upload_in_progress` (verrou en mémoire, puis conflit de
  création) ;
- **échec propre** : un flux trop long, coupé ou refusé par le disque laisse
  un Artifact `failed` codé (`upload_too_large`, `upload_incomplete`,
  `upload_storage_failed`) et **aucun** `.partial` (dossier retiré par
  `purge_payload`). Un refus avant le premier octet (corps vide,
  `Content-Length` au-delà de la borne, nom illisible) n'écrit rien ;
- **reprise** : un téléversement laissé `pending` par une mort de Core
  devient `failed` (`upload_interrupted`) sans payload (`recover`), jamais
  `partial` : un fichier tronqué n'est jamais joignable ;
- **journal** (`runtime/trace.jsonl`) : ids, tailles, types et codes ; jamais
  le nom d'origine ni un octet ;
- **pièces d'un tour écrit** : `attachment_refusal` (garde de
  `brain-turns`) et `brain_attachments` (bloc du tour, chemin absolu).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from jarvis.core.artifact_service import ArtifactService
from jarvis.domain.artifacts import Artifact, ArtifactError, ArtifactErrorCode, ArtifactKind, ArtifactQuery, ArtifactState
from jarvis.domain.brain_context import BrainAttachment, BrainAttachmentsContext
from jarvis.domain.uploads import (
    BRAIN_AGENTS, SNIFF_BYTES, UPLOAD_CHUNK_BYTES, Provenance, SOURCE_BY_PROVENANCE, UploadBounds, UploadNameError,
    UploadPurpose, brain_readable, check_client_upload_id, decode_upload_name, payload_name_for, sniff_mime,
    upload_artifact_id,
)
from jarvis.ports.artifacts import ArtifactPayloadError
from jarvis.ports.v2 import DiagnosticSink

#: `reader(n)` : au plus `n` octets du corps, `b""` à la fin (`aiohttp.StreamReader.read`).
Reader = Callable[[int], Awaitable[bytes]]
UPLOAD_INTERRUPTED = "upload_interrupted"
_MAX_DECLARED_MIME_CHARS = 200


class UploadRefused(Exception):
    """Refus stable d'un téléversement ou d'une pièce jointe : `status`, `code` (`docs/chat.md` › *Error codes*)."""

    def __init__(self, status: int, code: str, message: str, *, artifact: Artifact | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.artifact = status, code, message, artifact


@dataclass(frozen=True, slots=True)
class UploadOutcome:
    artifact: Artifact
    #: Vrai : rejeu reconnu (200) ; faux : nouvel Artifact (201).
    replayed: bool


def upload_view(artifact: Artifact) -> dict[str, Any]:
    """Ce que le navigateur peut savoir d'un téléversement : jamais un chemin (ni absolu, ni `payload_ref`)."""

    meta = artifact.metadata
    return {"artifact_id": artifact.artifact_id, "original_name": meta.get("original_name"),
            "mime_type": artifact.mime_type, "size_bytes": artifact.size_bytes,
            "brain_readable": bool(meta.get("brain_readable")), "state": artifact.state.value,
            "error_code": artifact.error_code}


class UploadService:
    """Voir l'en-tête du module. Construit par `JarvisCoreApplication`."""

    def __init__(self, artifacts: ArtifactService, *, association: Callable[[], Awaitable[tuple[str, str]]],
                 bounds: Callable[[], UploadBounds], artifacts_root: Path,
                 diagnostics: DiagnosticSink | None = None) -> None:
        self._artifacts = artifacts
        self._association = association
        self._bounds = bounds
        self._artifacts_root = Path(artifacts_root)
        self._diagnostics = diagnostics
        #: Téléversements en cours dans ce processus : un second essai du même id répond tout de suite 409.
        self._active: set[str] = set()

    @property
    def bounds(self) -> UploadBounds:
        return self._bounds()

    # ------------------------------------------------------------ téléversement

    async def put(self, *, client_upload_id: str, purpose: str, agent: str | None, declared_mime: str | None,
                  name_header: str | None, content_length: int | None, read: Reader) -> UploadOutcome:
        """Un fichier, en flux. `UploadRefused` pour tout refus ; `BoardError` sans Session ouverte."""

        try:
            check_client_upload_id(client_upload_id)
        except ValueError as exc:
            raise UploadRefused(400, "invalid_request", str(exc)) from None
        if purpose == UploadPurpose.BOARD:
            raise UploadRefused(400, "invalid_request", "purpose=board is not served yet (board drop, Slice 08)")
        if purpose != UploadPurpose.CHAT:
            raise UploadRefused(400, "invalid_request", "purpose must be 'chat'")
        if agent is not None and agent not in BRAIN_AGENTS:
            raise UploadRefused(400, "invalid_request", f"agent must be one of {sorted(BRAIN_AGENTS)}")
        try:
            original_name = decode_upload_name(name_header)
        except UploadNameError as exc:
            raise UploadRefused(400, "upload_name_invalid", str(exc)) from None
        declared = (declared_mime or "").strip()[:_MAX_DECLARED_MIME_CHARS] or None
        max_bytes = self._bounds().max_bytes
        if content_length is not None and content_length > max_bytes:
            raise self._refused(UploadRefused(413, "upload_too_large",
                                              f"the file exceeds the {max_bytes}-byte upload bound"), client_upload_id)
        artifact_id = upload_artifact_id(client_upload_id)
        if artifact_id in self._active:
            raise self._refused(UploadRefused(409, "upload_in_progress", "this client_upload_id is being uploaded"),
                                client_upload_id)
        self._active.add(artifact_id)
        try:
            existing = await self._existing(artifact_id)
            if existing is not None:
                return await self._replay(existing, content_length, read, max_bytes)
            return await self._store(artifact_id, client_upload_id=client_upload_id, agent=agent, declared=declared,
                                     original_name=original_name, content_length=content_length, read=read,
                                     max_bytes=max_bytes)
        finally:
            self._active.discard(artifact_id)

    async def _existing(self, artifact_id: str) -> Artifact | None:
        try:
            return await self._artifacts.get(artifact_id)
        except ArtifactError as exc:
            if exc.code is ArtifactErrorCode.ARTIFACT_NOT_FOUND:
                return None
            raise

    async def _replay(self, existing: Artifact, content_length: int | None, read: Reader, max_bytes: int) -> UploadOutcome:
        """Même `client_upload_id` : rejeu si mêmes octets, sinon conflit. Le corps est lu, haché, jamais gardé."""

        if existing.state is ArtifactState.PENDING:
            raise self._refused(UploadRefused(409, "upload_in_progress", "this client_upload_id is being uploaded",
                                              artifact=existing), existing.artifact_id)
        if existing.state is not ArtifactState.COMPLETE:
            raise self._refused(UploadRefused(409, "upload_conflict", f"a previous upload with this client_upload_id "
                                              f"ended {existing.state.value} ({existing.error_code}); use a new id",
                                              artifact=existing), existing.artifact_id)
        conflict = UploadRefused(409, "upload_conflict", "this client_upload_id was uploaded with other bytes",
                                 artifact=existing)
        if content_length is not None and content_length != existing.size_bytes:
            raise self._refused(conflict, existing.artifact_id)
        digest, size = hashlib.sha256(), 0
        limit = min(max_bytes, existing.size_bytes or 0)
        try:
            while chunk := await read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > limit:
                    raise self._refused(conflict, existing.artifact_id)
                digest.update(chunk)
        except UploadRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: a cut replay is said, the stored file is untouched
            raise self._refused(UploadRefused(400, "upload_incomplete",
                                              f"the body stopped early ({type(exc).__name__})"), existing.artifact_id)
        if size != existing.size_bytes or digest.hexdigest() != existing.metadata.get("sha256"):
            raise self._refused(conflict, existing.artifact_id)
        self._trace("core.upload.replayed", "téléversement rejoué : mêmes octets, même Artifact",
                    data={"artifact_id": existing.artifact_id, "size_bytes": size, "mime_type": existing.mime_type})
        return UploadOutcome(existing, replayed=True)

    async def _read_head(self, read: Reader) -> tuple[bytes, bool]:
        """(en-tête ≤ `SNIFF_BYTES`, fin du corps atteinte). Seule mémoire tenue par un téléversement."""

        head = bytearray()
        while len(head) < SNIFF_BYTES:
            chunk = await read(SNIFF_BYTES - len(head))
            if not chunk:
                return bytes(head), True
            head.extend(chunk)
        return bytes(head), False

    async def _store(self, artifact_id: str, *, client_upload_id: str, agent: str | None, declared: str | None,
                     original_name: str, content_length: int | None, read: Reader, max_bytes: int) -> UploadOutcome:
        try:
            head, ended = await self._read_head(read)
        except Exception as exc:  # noqa: BLE001 - capture: nothing written yet, said with its code
            raise self._refused(UploadRefused(400, "upload_incomplete",
                                              f"the body stopped early ({type(exc).__name__})"), artifact_id) from None
        if not head:
            raise self._refused(UploadRefused(400, "upload_empty", "the file is empty"), artifact_id)
        mime = sniff_mime(head, whole=ended)
        session_id, context_id = await self._association()
        provenance = Provenance.CHAT_ATTACHMENT
        metadata = {"original_name": original_name, "declared_mime": declared, "provenance": provenance,
                    "client_upload_id": client_upload_id, "brain_readable": brain_readable(agent or "claude", mime)}
        try:
            artifact = await self._artifacts.create(
                kind=ArtifactKind.UPLOAD, source=SOURCE_BY_PROVENANCE[provenance], jarvis_session_id=session_id,
                context_id=context_id, payload_name=payload_name_for(original_name, mime), mime_type=mime,
                metadata=metadata, artifact_id=artifact_id)
        except ArtifactError as exc:
            if exc.code is ArtifactErrorCode.ARTIFACT_CONFLICT:
                # Un autre processus (ou une requête passée entre la lecture et la création) l'a pris.
                raise self._refused(UploadRefused(409, "upload_in_progress",
                                                  "this client_upload_id is being uploaded"), artifact_id) from None
            raise
        return await self._spool(artifact, head, ended=ended, content_length=content_length, read=read,
                                 max_bytes=max_bytes)

    async def _spool(self, artifact: Artifact, head: bytes, *, ended: bool, content_length: int | None, read: Reader,
                     max_bytes: int) -> UploadOutcome:
        digest, size = hashlib.sha256(), 0
        spool = None
        opened = False
        failure: UploadRefused | None = None
        try:
            spool = await asyncio.to_thread(self._artifacts.open_spool, artifact)
            opened = True
            chunk = head
            while chunk:
                size += len(chunk)
                if size > max_bytes:
                    failure = UploadRefused(413, "upload_too_large",
                                            f"the file exceeds the {max_bytes}-byte upload bound")
                    break
                digest.update(chunk)
                await asyncio.to_thread(spool.write, chunk)
                if ended:
                    break
                chunk = await read(UPLOAD_CHUNK_BYTES)
            if failure is None and content_length is not None and size < content_length:
                failure = UploadRefused(400, "upload_incomplete",
                                        f"received {size} of the {content_length} announced bytes")
            if failure is None:
                await self._artifacts.update_pending(artifact.artifact_id, metadata={"sha256": digest.hexdigest()})
                await asyncio.to_thread(spool.finalize)
                spool = None
                done = await self._artifacts.finalize(artifact.artifact_id)
                self._trace("core.upload.stored", "fichier téléversé", data={
                    "artifact_id": done.artifact_id, "size_bytes": done.size_bytes, "mime_type": done.mime_type,
                    "provenance": done.metadata.get("provenance"), "brain_readable": done.metadata.get("brain_readable")})
                return UploadOutcome(done, replayed=False)
        except asyncio.CancelledError:
            # Client parti, handler annulé : l'Artifact ne reste jamais `pending` sans propriétaire.
            await asyncio.shield(self._abandon(artifact, spool, "upload_incomplete", purge=opened))
            raise
        except ArtifactPayloadError as exc:
            failure = UploadRefused(503, "upload_storage_failed", f"the payload store refused the file ({exc.code})")
        except ArtifactError:
            await self._abandon(artifact, spool, "upload_storage_failed", purge=opened)
            raise
        except Exception as exc:  # noqa: BLE001 - capture: a cut stream is an incomplete upload, said with its code
            failure = UploadRefused(400, "upload_incomplete", f"the body stopped early ({type(exc).__name__})")
        failed = await self._abandon(artifact, spool, failure.code, purge=opened)
        failure.artifact = failed
        raise self._refused(failure, artifact.artifact_id)

    async def _abandon(self, artifact: Artifact, spool: Any, code: str, *, purge: bool = True) -> Artifact | None:
        """Spool fermé, Artifact `failed` codé, dossier retiré : aucun `.partial` orphelin. Ne lève pas.

        `purge=False` quand le spool n'a jamais été ouvert : rien de ce qui est sur disque n'est à nous
        (un `.partial` trouvé là n'est ni écrasé ni effacé ; `artifact_payload_conflict`).
        """

        if spool is not None:
            try:
                await asyncio.to_thread(spool.close)
            except Exception as exc:  # noqa: BLE001 - capture: said; the folder purge below still runs
                self._trace("core.upload.spool_close_failed", "spool non fermé", level="warning",
                            data={"artifact_id": artifact.artifact_id, "exception_type": type(exc).__name__})
        failed = None
        try:
            failed = await self._artifacts.fail(artifact.artifact_id, error_code=code)
            if purge:
                await self._artifacts.purge_payload(artifact.artifact_id)
        except Exception as exc:  # noqa: BLE001 - capture: recovery at the next start fails it, said here
            self._trace("core.upload.abandon_failed", "téléversement en échec non soldé", level="error",
                        data={"artifact_id": artifact.artifact_id, "code": code,
                              "exception_type": type(exc).__name__})
        return failed

    # ------------------------------------------------------------ reprise

    @staticmethod
    def owns(artifact: Artifact) -> bool:
        """Un téléversement `pending` d'une vie précédente : repris par `recover`, pas par la reprise générique."""

        return artifact.kind is ArtifactKind.UPLOAD

    async def recover(self) -> int:
        """Au démarrage (après `recover_pending(owned=…)`) : chaque téléversement `pending` → `failed`
        `upload_interrupted`, dossier retiré. Ne lève pas ; rend le nombre soldé."""

        count = 0
        try:
            while True:
                page = await self._artifacts.query(ArtifactQuery(kinds=(ArtifactKind.UPLOAD,),
                                                                 states=(ArtifactState.PENDING,), limit=100))
                if not page.items:
                    break
                for artifact in page.items:
                    await self._artifacts.fail(artifact.artifact_id, error_code=UPLOAD_INTERRUPTED)
                    await self._artifacts.purge_payload(artifact.artifact_id)
                    count += 1
        except Exception as exc:  # noqa: BLE001 - capture: Core keeps starting, the next start retries
            self._trace("core.upload.recovery_failed", "reprise des téléversements interrompue", level="error",
                        data={"recovered": count, "exception_type": type(exc).__name__})
            return count
        if count:
            self._trace("core.upload.recovered", "téléversements interrompus soldés en échec", level="warning",
                        data={"recovered": count})
        return count

    # ------------------------------------------------------------ pièces d'un tour écrit

    async def attachment_refusal(self, artifact_ids: tuple[str, ...], jarvis_session_id: str) -> UploadRefused | None:
        """Étape 5 de `docs/chat.md` › *Core: same `brain-turns` route* : chaque pièce existe, est une pièce
        jointe du chat, de la Session ouverte, et `complete`. Rend le premier refus, ou `None`."""

        for artifact_id in artifact_ids:
            artifact = await self._existing(artifact_id)
            if artifact is None:
                return UploadRefused(404, "attachment_not_found", f"attachment {artifact_id} does not exist")
            if (artifact.kind is not ArtifactKind.UPLOAD
                    or artifact.metadata.get("provenance") != Provenance.CHAT_ATTACHMENT
                    or artifact.jarvis_session_id != jarvis_session_id):
                return UploadRefused(400, "attachment_not_allowed",
                                     f"attachment {artifact_id} is not a chat attachment of the open Session")
            if artifact.state is not ArtifactState.COMPLETE:
                return UploadRefused(409, "attachment_not_ready",
                                     f"attachment {artifact_id} is {artifact.state.value}, not complete")
        return None

    async def brain_attachments(self, turn: Any) -> BrainAttachmentsContext | None:
        """Bloc `attachments` du tour, lu du registre **au moment du tour** ; une pièce disparue depuis
        l'admission reste listée sans chemin (le brief le dit : jamais une perte silencieuse)."""

        ids = tuple(getattr(turn, "attachments", ()) or ())
        if not ids:
            return None
        items = []
        for artifact_id in ids:
            artifact = await self._existing(artifact_id)
            if artifact is None:
                items.append(BrainAttachment(artifact_id, "pièce supprimée", "application/octet-stream", None, None,
                                             False))
                continue
            path = self._readable_path(artifact)
            meta: Mapping[str, Any] = artifact.metadata
            items.append(BrainAttachment(
                artifact_id=artifact.artifact_id, original_name=str(meta.get("original_name") or "fichier"),
                mime_type=artifact.mime_type or "application/octet-stream", size_bytes=artifact.size_bytes,
                path=path, brain_readable=path is not None and bool(meta.get("brain_readable"))))
        missing = sum(1 for item in items if item.path is None)
        self._trace("core.upload.attachments_delivered", "pièces jointes remises au cerveau",
                    level="warning" if missing else "info",
                    data={"correlation_id": getattr(turn, "correlation_id", None), "attachments": len(items),
                          "unavailable": missing})
        return BrainAttachmentsContext(items=tuple(items), artifacts_root=str(self._artifacts_root))

    def _readable_path(self, artifact: Artifact) -> str | None:
        if artifact.state is not ArtifactState.COMPLETE:
            return None
        try:
            info = self._artifacts.payload_info(artifact)
            return self._artifacts.payload_path(artifact) if info is not None and info.final_bytes is not None else None
        except (ArtifactPayloadError, ArtifactError):
            return None

    # ------------------------------------------------------------ journal

    def _refused(self, refusal: UploadRefused, key: str) -> UploadRefused:
        self._trace("core.upload.refused", "téléversement refusé", level="warning",
                    data={"code": refusal.code, "status": refusal.status,
                          "artifact_id": key if key.startswith("jart_") else upload_artifact_id(key)})
        return refusal

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not undo a committed write
            pass
