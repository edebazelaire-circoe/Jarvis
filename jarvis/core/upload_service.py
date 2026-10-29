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
  `brain-turns`) et `brain_attachments` (bloc du tour, chemin absolu) ;
- **dépôt sur un Board** (Slice 08, `docs/chat.md` › *Board drop*) :
  `purpose=board` pour un fichier, `put_link` pour une URL (Artifact `link`,
  `complete` d'un coup, **jamais récupérée**). La cible doit être le Board
  actif de la Session ouverte (409 `board_drop_target_inactive`) ; le lien
  automatique de la transaction de création est le lien Board, et si une
  bascule passe entre le contrôle et la transaction, la cible est liée
  explicitement (`WorkspaceService.artifact_link`, `origin=user`) et la
  réponse le dit (`relinked`) ; le lien automatique que cette création a
  posé sur le Board devenu actif est alors retiré (`artifact_unlink`), un
  lien `explicit` jamais. Jamais un événement de conversation, jamais un
  tour du cerveau.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from jarvis.core.artifact_service import ArtifactService
from jarvis.domain.artifacts import Artifact, ArtifactError, ArtifactErrorCode, ArtifactKind, ArtifactQuery, ArtifactState
from jarvis.domain.board_artifact_links import BoardArtifactLinkOrigin
from jarvis.domain.brain_context import BrainAttachment, BrainAttachmentsContext
from jarvis.domain.uploads import (
    BRAIN_AGENTS, SNIFF_BYTES, UPLOAD_CHUNK_BYTES, LinkInvalid, Provenance, SOURCE_BY_PROVENANCE, UploadBounds,
    UploadNameError, UploadPurpose, brain_readable, check_client_upload_id, check_link_url, decode_upload_name,
    payload_name_for, sniff_mime, upload_artifact_id,
)
from jarvis.ports.artifacts import ArtifactPayloadError
from jarvis.ports.v2 import DiagnosticSink

#: `reader(n)` : au plus `n` octets du corps, `b""` à la fin (`aiohttp.StreamReader.read`).
Reader = Callable[[int], Awaitable[bytes]]
UPLOAD_INTERRUPTED = "upload_interrupted"
_MAX_DECLARED_MIME_CHARS = 200


class UploadRefused(Exception):
    """Refus stable d'un téléversement ou d'une pièce jointe : `status`, `code` (`docs/chat.md` › *Error codes*)."""

    def __init__(self, status: int, code: str, message: str, *, artifact: Artifact | None = None,
                 details: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.artifact = status, code, message, artifact
        #: Champs sûrs ajoutés au refus (`active_board_id` d'un dépôt hors du Board affiché).
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class UploadOutcome:
    artifact: Artifact
    #: Vrai : rejeu reconnu (200) ; faux : nouvel Artifact (201).
    replayed: bool
    #: Dépôt sur un Board (Slice 08) : le Board ciblé, et vrai si Core a dû le lier explicitement.
    board_id: str | None = None
    relinked: bool = False
    #: Rattrapage fait mais lien automatique du Board devenu actif impossible à retirer : ce Board le porte aussi.
    also_linked_board_id: str | None = None
    #: Une image déposée est aussi montrée sur la scène du Board : l'objet (fenêtre) qui la porte, sinon `None`.
    scene_object_id: str | None = None


@dataclass(frozen=True, slots=True)
class BoardDropSeam:
    """Ce que le dépôt sur un Board lit et écrit hors du registre (Slice 08), câblé par `JarvisCoreApplication`."""

    #: `active_board_id` de la Session ouverte ; `BoardError` (`session_not_found`) sans Session.
    active_board: Callable[[], Awaitable[str]]
    #: Liens d'un Artifact (`board_artifact_links`) : `{board_id: origine}` (`active_board` ou `explicit`).
    links_of: Callable[[str], Awaitable[Mapping[str, str]]]
    #: Lien explicite (`WorkspaceService.artifact_link(board_id, artifact_id, origin="user")`).
    link: Callable[[str, str], Awaitable[Any]]
    #: Retrait d'un lien (`WorkspaceService.artifact_unlink(board_id, artifact_id, origin="user")`).
    unlink: Callable[[str, str], Awaitable[Any]]
    #: Montre l'Artifact sur la scène du Board (`DossierService.present`) : rend l'`object_id` de la fenêtre.
    #: Facultatif : sans lui (ou s'il échoue), l'image reste un Artifact du Board, sans objet de scène.
    present: Callable[[str, str], Awaitable[str | None]] | None = None


def storage_cause(exc: ArtifactPayloadError, stage: str) -> dict[str, Any]:
    """Cause réelle d'un refus du magasin de payloads (constat 3 de la Slice 09), sans le chemin (dossier de
    l'utilisateur), sans un nom, sans un message d'OS (qui cite le chemin).

    `stage` : `open` (spool), `write`, `finalize`. `cause_type` : classe de la cause enchaînée par l'adaptateur
    (`raise ... from exc`) ; `os_error`, `errno`, `winerror` : la première `OSError` de la chaîne ; `path_limit` :
    la limite Windows dépassée (MAX_PATH, `SafeFolderError.path_limit`), avec `path_chars`."""

    chain: list[BaseException] = []
    current = exc.__cause__
    while current is not None and len(chain) < 4:
        chain.append(current)
        current = current.__cause__
    os_error = next((item for item in chain if isinstance(item, OSError)), None)
    path_limit = next((item.path_limit for item in chain if getattr(item, "path_limit", None)), None)
    return {"payload_code": exc.code, "stage": stage,
            "cause_type": type(chain[0]).__name__ if chain else None,
            "os_error": type(os_error).__name__ if os_error is not None else None,
            "errno": getattr(os_error, "errno", None), "winerror": getattr(os_error, "winerror", None),
            "path_chars": len(str(exc.path)), "path_limit": path_limit}


def _cause_text(cause: Mapping[str, Any]) -> str:
    """La cause en une phrase sûre pour le message du refus (aucun chemin)."""

    parts = [f"{cause['payload_code']} at {cause['stage']}", str(cause["cause_type"] or "no chained cause")]
    if cause["os_error"] is not None:
        parts.append(f"{cause['os_error']} errno={cause['errno']} winerror={cause['winerror']}")
    if cause["path_limit"] is not None:
        parts.append(f"path of {cause['path_chars']} characters above the Windows limit of {cause['path_limit']}")
    return "; ".join(parts)


def upload_view(artifact: Artifact) -> dict[str, Any]:
    """Ce que le navigateur peut savoir d'un téléversement : jamais un chemin (ni absolu, ni `payload_ref`)."""

    meta = artifact.metadata
    return {"artifact_id": artifact.artifact_id, "original_name": meta.get("original_name"),
            "mime_type": artifact.mime_type, "size_bytes": artifact.size_bytes,
            "brain_readable": bool(meta.get("brain_readable")), "state": artifact.state.value,
            "error_code": artifact.error_code}


def link_view(artifact: Artifact) -> dict[str, Any]:
    """Une URL déposée : l'URL telle que donnée et son hôte, jamais rien de récupéré."""

    return {"artifact_id": artifact.artifact_id, "kind": artifact.kind.value, "url": artifact.text,
            "host": artifact.metadata.get("host"), "state": artifact.state.value}


#: Nom donné au cerveau pour une capture d'écran jointe (elle n'a pas de nom d'origine).
SCREENSHOT_ATTACHMENT_NAME = "capture d’écran.png"


def screenshot_attachment_name(artifact: Artifact) -> str:
    """Le nom d'une capture d'écran dans le brief, celui de sa pièce dans le Chat : « Capture d’écran
    HH-MM-SS.png » à l'heure locale de sa création (`created_at`, la même que lit l'aperçu du Control
    Center), « … annotée » pour une copie annotée. Deux captures d'un même message ne portent plus le
    même nom (QA S05, polish 2). Sans heure lisible : `SCREENSHOT_ATTACHMENT_NAME`."""

    try:
        clock = artifact.created_at.astimezone().strftime("%H-%M-%S")
    except (AttributeError, ValueError, OSError):
        return SCREENSHOT_ATTACHMENT_NAME
    annotated = " annotée" if artifact.source == "annotation" else ""
    extension = {"image/jpeg": "jpg", "image/webp": "webp"}.get(artifact.mime_type or "", "png")
    return f"Capture d’écran {clock}{annotated}.{extension}"


def attachable(artifact: Artifact) -> bool:
    """Peut accompagner un message écrit : une pièce jointe du chat, ou une capture d'écran (Slice 05, D7).

    La Session et l'état `complete` sont vérifiés à part (`attachment_refusal`). Une capture d'écran
    n'est jamais copiée : le brief donne le chemin de SON payload, comme pour un fichier joint.
    """

    if artifact.kind is ArtifactKind.SCREENSHOT:
        return True
    return artifact.kind is ArtifactKind.UPLOAD and artifact.metadata.get("provenance") == Provenance.CHAT_ATTACHMENT


class UploadService:
    """Voir l'en-tête du module. Construit par `JarvisCoreApplication`."""

    def __init__(self, artifacts: ArtifactService, *, association: Callable[[], Awaitable[tuple[str, str]]],
                 bounds: Callable[[], UploadBounds], artifacts_root: Path,
                 diagnostics: DiagnosticSink | None = None, board_drop: BoardDropSeam | None = None) -> None:
        self._artifacts = artifacts
        self._board_drop = board_drop
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
                  name_header: str | None, content_length: int | None, read: Reader,
                  board_id: str | None = None) -> UploadOutcome:
        """Un fichier, en flux. `UploadRefused` pour tout refus ; `BoardError` sans Session ouverte.

        `purpose=board` (Slice 08) : `board_id` doit être le Board affiché ; contrôlé **avant** de lire
        un octet, puis le lien est vérifié après création (`_ensure_board_link`).
        """

        try:
            check_client_upload_id(client_upload_id)
        except ValueError as exc:
            raise UploadRefused(400, "invalid_request", str(exc)) from None
        if purpose not in (UploadPurpose.CHAT, UploadPurpose.BOARD):
            raise UploadRefused(400, "invalid_request", "purpose must be 'chat' or 'board'")
        if purpose == UploadPurpose.CHAT and board_id is not None:
            raise UploadRefused(400, "invalid_request", "board_id is only accepted with purpose=board")
        provenance = Provenance.BOARD_DROP if purpose == UploadPurpose.BOARD else Provenance.CHAT_ATTACHMENT
        if agent is not None and agent not in BRAIN_AGENTS:
            raise UploadRefused(400, "invalid_request", f"agent must be one of {sorted(BRAIN_AGENTS)}")
        try:
            original_name = decode_upload_name(name_header)
        except UploadNameError as exc:
            raise UploadRefused(400, "upload_name_invalid", str(exc)) from None
        declared = (declared_mime or "").strip()[:_MAX_DECLARED_MIME_CHARS] or None
        if purpose == UploadPurpose.BOARD:
            board_id = await self._drop_target(board_id, client_upload_id)
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
                if existing.kind is not ArtifactKind.UPLOAD or existing.metadata.get("provenance") != provenance:
                    raise self._refused(UploadRefused(409, "upload_conflict", "this client_upload_id was used for "
                                                      "another kind of upload; use a new id", artifact=existing),
                                        artifact_id)
                outcome = await self._replay(existing, content_length, read, max_bytes)
            else:
                outcome = await self._store(artifact_id, client_upload_id=client_upload_id, agent=agent,
                                            declared=declared, original_name=original_name,
                                            content_length=content_length, read=read, max_bytes=max_bytes,
                                            provenance=provenance)
        finally:
            self._active.discard(artifact_id)
        if board_id is None:
            return outcome
        relinked, stray = await self._ensure_board_link(board_id, outcome.artifact.artifact_id,
                                                        fresh=not outcome.replayed)
        shown = await self._show_on_scene(board_id, outcome.artifact)
        return dataclasses.replace(outcome, board_id=board_id, relinked=relinked, also_linked_board_id=stray,
                                   scene_object_id=shown)

    async def _show_on_scene(self, board_id: str, artifact: Artifact) -> str | None:
        """Une image déposée devient une fenêtre de la scène du Board (même chemin que « Afficher sur le Board »).

        Jamais bloquant : l'Artifact est déjà stocké et lié ; si la scène refuse, on le trace et l'image reste
        dans les Artefacts du Board (rail, inspecteur). Rejeu : la fenêtre existante est réutilisée, pas doublée.
        """

        seam = self._board_drop
        if seam is None or seam.present is None or not (artifact.mime_type or "").startswith("image/"):
            return None
        try:
            return await seam.present(board_id, artifact.artifact_id)
        except Exception as exc:  # noqa: BLE001 - capture: the file is stored and linked; the scene is a bonus
            self._trace("core.upload.scene_present_failed", "dépôt : image stockée mais non montrée sur la scène",
                        level="warning", data={"artifact_id": artifact.artifact_id, "board_id": board_id,
                                               "exception_type": type(exc).__name__})
            return None

    # ------------------------------------------------------------ dépôt sur un Board (Slice 08)

    async def put_link(self, *, client_upload_id: str, url: object, board_id: object) -> UploadOutcome:
        """Une URL déposée sur le Board affiché : Artifact `link` `complete`, `text` = l'URL. **Jamais récupérée.**

        Même identité rejouable qu'un fichier (`client_upload_id`) : même URL → rejeu 200, autre URL ou
        autre nature → 409 `upload_conflict`.
        """

        try:
            check_client_upload_id(client_upload_id)
        except ValueError as exc:
            raise UploadRefused(400, "invalid_request", str(exc)) from None
        try:
            link_url, host = check_link_url(url)
        except LinkInvalid as exc:
            raise self._refused(UploadRefused(400, "link_invalid", str(exc)), client_upload_id) from None
        target = await self._drop_target(board_id, client_upload_id)
        artifact_id = upload_artifact_id(client_upload_id)
        existing = await self._existing(artifact_id)
        replayed = existing is not None
        if existing is None:
            session_id, context_id = await self._association()
            try:
                existing = await self._artifacts.record_text(
                    artifact_id=artifact_id, kind=ArtifactKind.LINK,
                    source=SOURCE_BY_PROVENANCE[Provenance.BOARD_DROP], text=link_url, jarvis_session_id=session_id,
                    context_id=context_id, started_at=None, ended_at=None, duration_ms=None, origins=(),
                    metadata={"provenance": Provenance.BOARD_DROP, "host": host, "client_upload_id": client_upload_id})
            except ArtifactError as exc:
                if exc.code is not ArtifactErrorCode.ARTIFACT_CONFLICT:
                    raise
                # Même id créé entre la lecture et l'écriture (double dépôt) : comparé comme un rejeu.
                existing, replayed = await self._artifacts.get(artifact_id), True
        if replayed and (existing.kind is not ArtifactKind.LINK or existing.text != link_url):
            raise self._refused(UploadRefused(409, "upload_conflict", "this client_upload_id was used for another "
                                              "drop; use a new id", artifact=existing), artifact_id)
        self._trace("core.upload.link_replayed" if replayed else "core.upload.link_stored",
                    "URL déposée sur le Board, jamais récupérée",
                    data={"artifact_id": artifact_id, "board_id": target, "replayed": replayed})
        relinked, stray = await self._ensure_board_link(target, artifact_id, fresh=not replayed)
        return UploadOutcome(existing, replayed=replayed, board_id=target, relinked=relinked,
                             also_linked_board_id=stray)

    async def _drop_target(self, board_id: object, key: str) -> str:
        """Le Board ciblé s'il est le Board actif de la Session ouverte ; sinon un refus codé."""

        if self._board_drop is None:
            raise UploadRefused(503, "core_unavailable", "board drop is not wired in this Core")
        if not isinstance(board_id, str) or not board_id.strip():
            raise self._refused(UploadRefused(400, "invalid_request", "board_id is required for a board drop"), key)
        active = await self._board_drop.active_board()
        if board_id != active:
            raise self._refused(UploadRefused(
                409, "board_drop_target_inactive",
                f"board {board_id[:80]} is not the displayed Board; drop on the Board shown on screen",
                details={"active_board_id": active}), key)
        return board_id

    async def _ensure_board_link(self, board_id: str, artifact_id: str, *,
                                 fresh: bool) -> tuple[bool, str | None]:
        """Contrôle après création : la cible porte-t-elle le lien ? Sinon lien explicite, et on le dit.

        Rend `(relinked, also_linked_board_id)`. Après le rattrapage d'un Artifact créé par **cet** appel
        (`fresh`), le lien automatique posé sur le Board devenu actif est retiré (`_drop_auto_link`) ; jamais
        sur un rejeu, où un lien a pu être posé entre-temps par quelqu'un d'autre.
        """

        assert self._board_drop is not None  # `_drop_target` l'a exigé
        if board_id in await self._board_drop.links_of(artifact_id):
            return False, None
        try:
            await self._board_drop.link(board_id, artifact_id)
        except Exception as exc:
            # Rethrow : la route rend le refus du Board (archivé, inconnu) ; l'Artifact reste, un rejeu relie.
            self._trace("core.upload.board_relink_failed", "dépôt : lien du Board ciblé impossible", level="error",
                        data={"artifact_id": artifact_id, "board_id": board_id, "exception_type": type(exc).__name__})
            raise
        self._trace("core.upload.board_relinked", "dépôt : Board changé pendant le dépôt, cible liée explicitement",
                    level="warning", data={"artifact_id": artifact_id, "board_id": board_id})
        return True, (await self._drop_auto_link(board_id, artifact_id) if fresh else None)

    async def _drop_auto_link(self, target: str, artifact_id: str) -> str | None:
        """Retire le lien **automatique** que la création a posé sur le Board devenu actif pendant le dépôt.

        Seul un lien d'origine `active_board` hors de la cible est retiré ; un lien `explicit` reste. Échec :
        journalisé `error`, l'Artifact reste lié à la cible et la réponse nomme le Board qui porte encore le
        lien automatique (`also_linked_board_id`, que la page peut ignorer).
        """

        assert self._board_drop is not None
        auto = BoardArtifactLinkOrigin.ACTIVE_BOARD.value
        board: str | None = None
        try:
            links = await self._board_drop.links_of(artifact_id)
            for board in [other for other, origin in links.items() if other != target and origin == auto]:
                await self._board_drop.unlink(board, artifact_id)
                self._trace("core.upload.board_auto_link_removed",
                            "dépôt : lien automatique du Board devenu actif retiré, l'Artifact reste sur la cible",
                            level="warning", data={"artifact_id": artifact_id, "board_id": target,
                                                   "auto_board_id": board})
        except Exception as exc:  # noqa: BLE001 - capture: the file is on the right Board; the stray link is said
            self._trace("core.upload.board_auto_link_remove_failed",
                        "dépôt : lien automatique du Board devenu actif impossible à retirer", level="error",
                        data={"artifact_id": artifact_id, "board_id": target, "auto_board_id": board,
                              "exception_type": type(exc).__name__})
            return board
        return None

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
                     original_name: str, content_length: int | None, read: Reader, max_bytes: int,
                     provenance: str) -> UploadOutcome:
        try:
            head, ended = await self._read_head(read)
        except Exception as exc:  # noqa: BLE001 - capture: nothing written yet, said with its code
            raise self._refused(UploadRefused(400, "upload_incomplete",
                                              f"the body stopped early ({type(exc).__name__})"), artifact_id) from None
        if not head:
            raise self._refused(UploadRefused(400, "upload_empty", "the file is empty"), artifact_id)
        mime = sniff_mime(head, whole=ended)
        session_id, context_id = await self._association()
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
        cause: dict[str, Any] = {}
        stage = "open"
        try:
            spool = await asyncio.to_thread(self._artifacts.open_spool, artifact)
            opened = True
            stage = "write"
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
                stage = "finalize"
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
            # Constat 3 de la Slice 09 : la cause réelle (classe, errno, MAX_PATH) va au journal et au message ;
            # jamais le chemin (dossier de l'utilisateur) ni le nom d'origine.
            cause = storage_cause(exc, stage)
            failure = UploadRefused(503, "upload_storage_failed",
                                    f"the payload store refused the file ({_cause_text(cause)})")
        except ArtifactError:
            await self._abandon(artifact, spool, "upload_storage_failed", purge=opened)
            raise
        except Exception as exc:  # noqa: BLE001 - capture: a cut stream is an incomplete upload, said with its code
            failure = UploadRefused(400, "upload_incomplete", f"the body stopped early ({type(exc).__name__})")
        failed = await self._abandon(artifact, spool, failure.code, purge=opened)
        failure.artifact = failed
        raise self._refused(failure, artifact.artifact_id, cause=cause)

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

    async def attachment_refusal(self, artifact_ids: tuple[str, ...], jarvis_session_id: str,
                                 board_id: str) -> UploadRefused | None:
        """Étape 5 de `docs/chat.md` › *Core: same `brain-turns` route* : chaque pièce existe, est une pièce
        jointe du chat **ou une capture d'écran** (« Envoyer à Jarvis », orbital-ui Slice 05, D7), de la
        Session ouverte, liée au Board du tour (`board_id`, celui du binding visé), et `complete`. Rend le
        premier refus, ou `None`.

        Le Board d'une pièce jointe est son lien Board (`board_artifact_links`) : le lien automatique
        `active_board` posé dans la transaction de création (une capture d'écran comme un téléversement), ou un
        lien `explicit`. Une pièce envoyée sur A puis citée par un tour de B (même Session) est refusée ici, pas
        seulement par la page (`stale`)."""

        for artifact_id in artifact_ids:
            artifact = await self._existing(artifact_id)
            if artifact is None:
                return UploadRefused(404, "attachment_not_found", f"attachment {artifact_id} does not exist")
            if not attachable(artifact) or artifact.jarvis_session_id != jarvis_session_id:
                return UploadRefused(400, "attachment_not_allowed",
                                     f"attachment {artifact_id} is not a chat attachment of the open Session")
            if self._board_drop is None:
                # Garde fermée : sans lecture des liens Board, on ne sait pas à quel Board la pièce appartient.
                return UploadRefused(503, "core_unavailable", "board links are not wired in this Core")
            if board_id not in await self._board_drop.links_of(artifact_id):
                self._trace("core.upload.attachment_other_board", "pièce jointe d'un autre Board refusée",
                            level="warning", data={"artifact_id": artifact_id, "board_id": board_id})
                return UploadRefused(409, "attachment_other_board",
                                     f"attachment {artifact_id} belongs to another Board than this conversation's")
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
            fallback = screenshot_attachment_name(artifact) if artifact.kind is ArtifactKind.SCREENSHOT else "fichier"
            items.append(BrainAttachment(
                artifact_id=artifact.artifact_id, original_name=str(meta.get("original_name") or fallback),
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

    def _refused(self, refusal: UploadRefused, key: str, *,
                 cause: Mapping[str, Any] | None = None) -> UploadRefused:
        data = {"code": refusal.code, "status": refusal.status,
                "artifact_id": key if key.startswith("jart_") else upload_artifact_id(key)}
        if cause:
            data["cause"] = dict(cause)
        self._trace("core.upload.refused", "téléversement refusé",
                    level="error" if refusal.status >= 500 else "warning", data=data)
        return refusal

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not undo a committed write
            pass
