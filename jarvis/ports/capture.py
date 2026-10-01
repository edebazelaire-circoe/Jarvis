"""Ports des captures (handoff session-context-recording, Slice 05). Contrat : `docs/capture.md`.

Coutures du `CaptureService` (Core) :

- `CaptureRepository` : intention et état durables (table `captures`, v7),
  sur la connexion partagée de l'état (adaptateur `sqlite_captures`) ; une
  transition et son activité (`capture.*`) s'écrivent dans **une** transaction ;
- `CaptureSource` / `OneShotSource` : un appareil (micro, bureau, faux), ouvert
  par Core lui-même (D-CAP). Une source continue écrit dans un `CaptureSink`
  et y signale ses trous et sa perte ; elle ne connaît ni Artifact, ni base ;
- `CaptureSourceRegistry` : choisit la source d'une demande, ou refuse
  (`unsupported_source`, `unsupported_platform`) ;
- `CaptureRepair` : réparation propre à une famille (en-tête WAV, Slice 06 ;
  conteneur vidéo, Slice 07) appliquée au payload d'une capture interrompue,
  au démarrage suivant, **avant** la reprise générique des Artifacts.
"""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from jarvis.domain.capture import CaptureChannel, CaptureErrorCode, CaptureMode, CaptureRecord
from jarvis.domain.session_activity import ActivityDraft, ActivityEvent
from jarvis.ports.workspace_board import BoardStoreError, BoardStoreUnavailable


class CaptureStoreError(BoardStoreError):
    """Ligne illisible ou qui contredit ses colonnes clés ; jamais réparée (état canonique)."""

    code = "capture_store_unreadable"


class CaptureStoreUnavailable(BoardStoreUnavailable):
    """SQLite a refusé l'opération (verrou, E/S) ; la cause SQLite reste dans le message."""

    code = "capture_store_failed"

    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(operation, reason)
        self.args = (f"capture store {operation} failed: {reason}",)
        self.table = "captures"


class CaptureRepository(Protocol):
    async def insert_capture(self, record: CaptureRecord, *,
                             activity: Sequence[ActivityDraft] = ()) -> tuple[ActivityEvent, ...]:
        """Nouvelle capture `starting`. Une capture continue ouverte sur le même canal/appareil :
        `already_active` (vérifiée dans la transaction et par un index unique partiel)."""
        ...

    async def update_capture(self, previous: CaptureRecord, updated: CaptureRecord, *,
                             activity: Sequence[ActivityDraft] = ()) -> tuple[ActivityEvent, ...]:
        """Comparer-échanger sur `previous` ; transitions de `check_capture_update` seulement."""
        ...

    async def get_capture(self, capture_id: str) -> CaptureRecord | None: ...

    async def open_captures(self, *, limit: int) -> Sequence[CaptureRecord]:
        """Captures `starting|active|stopping`, de la plus ancienne à la plus récente (réconciliation)."""
        ...

    async def open_capture_ids(self, *, limit: int, offset: int = 0) -> Sequence[str]:
        """Identifiants des captures ouvertes, même ordre, **sans décoder** les lignes : une ligne
        illisible ne bloque pas la réconciliation des autres (chacune est relue seule)."""
        ...

    async def recent_captures(self, *, limit: int) -> Sequence[CaptureRecord]:
        """Les plus récentes d'abord (statut, historique court)."""
        ...


# ------------------------------------------------------------------ sources


class CaptureSourceError(RuntimeError):
    """Refus ou échec d'une source, avec son code stable (`permission_denied`, `source_unavailable`...)."""

    def __init__(self, code: CaptureErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = CaptureErrorCode(code)


class CaptureSink(Protocol):
    """Seul canal d'une source continue vers son propriétaire.

    `write`/`write_at`/`sync` sont synchrones (disque) : une source réelle les
    appelle depuis son fil d'écriture, jamais depuis le callback de l'appareil
    ni depuis la boucle. Ils lèvent `CaptureSourceError` (`storage_full`,
    `write_failed`) : la source arrête alors d'écrire, le propriétaire arrête
    la capture. `gap` et `lost` sont sûrs depuis n'importe quel fil.
    """

    @property
    def bytes_written(self) -> int: ...

    def write(self, data: bytes) -> None: ...

    def write_at(self, offset: int, data: bytes) -> None: ...

    def sync(self) -> None: ...

    def hand_over(self) -> Path:
        """Confie le `.partial` à un écrivain **externe** (encodeur vidéo, Slice 07) et rend son chemin.

        Le sink n'écrit plus lui-même (`write`/`write_at` refusés) ; `bytes_written`
        devient la taille mesurée sur disque ; la finalisation (`fsync`, renommage)
        reste celle du propriétaire, après l'arrêt de l'écrivain externe.
        """
        ...

    def gap(self, *, reason: str, lost_ms: int | None = None) -> None:
        """Perte datée (file débordée...) : `capture.gap`, la preuve finale sera `partial`."""
        ...

    def lost(self, code: CaptureErrorCode, reason: str) -> None:
        """Source perdue (appareil retiré) : la capture s'arrête, preuve `partial` ou `failed`."""
        ...


@dataclass(frozen=True, slots=True)
class SourceHealth:
    ok: bool
    code: str | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """Ce que la source sait du média à la fin (durée, dimensions) ; `None` : inconnu."""

    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    #: Faits d'acquisition bornés (format, appareil réel, trous comptés...) fusionnés
    #: dans les métadonnées de l'Artifact avant sa finalisation (≤ 16 scalaires).
    details: Mapping[str, Any] = field(default_factory=dict)


class CaptureSource(Protocol):
    """Source continue d'**une** capture (une instance par capture)."""

    #: Nom du payload (`source.wav`...) et type MIME de l'Artifact principal.
    payload_name: str
    mime_type: str

    async def start(self, sink: CaptureSink) -> None:
        """Ouvre l'appareil et commence à écrire dans `sink` ; lève `CaptureSourceError`."""
        ...

    async def stop(self) -> None:
        """Arrête l'appareil et vide ses tampons dans le sink ; après le retour, plus aucune écriture."""
        ...

    def health(self) -> SourceHealth: ...

    def media_info(self) -> MediaInfo: ...


@dataclass(frozen=True, slots=True)
class OneShotResult:
    data: bytes
    width: int | None = None
    height: int | None = None
    #: Faits d'acquisition bornés (écran, DPI, heure de prise...) fusionnés dans les
    #: métadonnées de l'Artifact avant l'écriture du payload (comme `MediaInfo.details`).
    details: Mapping[str, Any] = field(default_factory=dict)


class OneShotSource(Protocol):
    payload_name: str
    mime_type: str

    async def capture(self) -> OneShotResult:
        """Une prise (capture d'écran) ; lève `CaptureSourceError`."""
        ...


class CaptureSourceRegistry(Protocol):
    def continuous(self, channel: CaptureChannel, *, source: str | None, device: str) -> CaptureSource:
        """Source neuve pour une capture continue ; `CaptureError` `unsupported_*` sinon."""
        ...

    def one_shot(self, channel: CaptureChannel, *, source: str | None, device: str) -> OneShotSource: ...

    def source_name(self, channel: CaptureChannel, mode: CaptureMode, source: str | None) -> str:
        """Nom retenu pour la demande (source par défaut du canal si `None`)."""
        ...


# ------------------------------------------------------------------ réparation


@dataclass(frozen=True, slots=True)
class RepairTarget:
    """Payload d'une capture interrompue, tel que la mort de Core l'a laissé (aucun accès fait)."""

    capture: CaptureRecord
    artifact_id: str
    #: `<name>.partial` (écriture en cours) et `<name>` (renommage déjà fait).
    partial_path: Path
    final_path: Path
    partial_bytes: int | None
    final_bytes: int | None


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    #: Vrai si des octets ont été réécrits (en-tête réparé...).
    repaired: bool
    duration_ms: int | None = None
    #: Court, sans contenu (journal et `data` de la capture).
    detail: str = ""
    #: Faux : la famille sait que le payload n'est pas lisible (conteneur vidéo sans
    #: aucun fragment complet, Slice 07) ; la capture et son Artifact finissent `failed`
    #: (`capture_interrupted`), le `.partial` reste sur disque comme preuve.
    usable: bool = True


class CaptureRepair(Protocol):
    """Réparation d'une famille, synchrone (lancée dans un fil). Ne crée, ne renomme, ne supprime aucun
    fichier : elle réécrit au plus le payload existant en place (troncature d'une fin déchirée
    comprise). Elle peut déclarer le payload illisible (`usable=False`). Une exception est journalisée et la
    reprise continue (la preuve devient `partial` telle quelle)."""

    def repair(self, target: RepairTarget) -> RepairOutcome: ...
