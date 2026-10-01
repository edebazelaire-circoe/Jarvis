"""Contrat pur des captures (handoff session-context-recording, Slice 05 ; D01, D11, D13, D-CAP).

Une **capture** est une acquisition explicite de média lancée par l'humain ou
un agent (enregistrement audio, enregistrement d'écran, capture d'écran
ponctuelle). Son unique propriétaire est le `CaptureService` de Core
(`jarvis/core/capture_service.py`) : seule vérité d'état, intention durable
(table `captures`, v7), finalisation dans le registre d'Artifacts et
réconciliation au démarrage suivant. Le cerveau, MCP et l'interface sont des
clients. Contrat : `docs/capture.md`.

Invariants portés ici :

- `capture_id` : `jcap_` + segment sûr en minuscules (comme les Artifacts) ;
- machine d'état `starting -> active -> stopping -> complete|partial|failed`
  (table `_NEXT`). `complete` n'est atteint que depuis `stopping`, sans code
  d'erreur ; `partial` et `failed` disent toujours pourquoi (`error_code`) ;
- un arrêt demandé deux fois ne change rien (`request_stop` idempotent) ;
- l'identité (canal, mode, source, appareil, Session, Context, création) est
  fixée au démarrage et ne change jamais : une capture reste associée au
  Context actif à son démarrage ;
- valeurs bornées ; la validation refuse, elle ne tronque pas.

Pur : aucune E/S, aucune horloge implicite (chaque transition reçoit `now`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
import uuid

from jarvis.domain._checks import (
    TOKEN, check_aware, check_prefixed_id, freeze_runtime_metadata, parse_dt, parse_enum, preview, strict_keys,
)
from jarvis.domain.artifacts import ARTIFACT_ID_PREFIX, ArtifactKind
from jarvis.domain.session_context import CONTEXT_ID_PREFIX
from jarvis.domain.workspace_board import SESSION_ID_PREFIX

CAPTURE_ID_PREFIX = "jcap_"
MAX_SOURCE_CHARS = 64
MAX_DEVICE_CHARS = 128
DEFAULT_DEVICE = "default"
MAX_CAPTURE_DATA_KEYS = 16
MAX_CAPTURE_DATA_VALUE_CHARS = 256
MAX_COUNT = 1 << 50


# ------------------------------------------------------------------ erreurs


class CaptureErrorCode(StrEnum):
    """Échecs nommés d'une capture (docs/03 du handoff, *Failure semantics*).

    Un code est soit un refus rendu à l'appelant (`CaptureError`), soit le
    `error_code` durable d'une capture `partial`/`failed` ; jamais réétiqueté
    en un code générique.
    """

    INVALID_CAPTURE = "invalid_capture"
    CAPTURE_NOT_FOUND = "capture_not_found"
    #: Transition interdite par la machine d'état (défaut de code, jamais attendu).
    INVALID_TRANSITION = "capture_invalid_transition"
    #: Une capture continue occupe déjà ce canal/appareil.
    ALREADY_ACTIVE = "already_active"
    SOURCE_UNAVAILABLE = "source_unavailable"
    PERMISSION_DENIED = "permission_denied"
    #: La source n'a pas démarré (ou ne s'est pas arrêtée) avant l'échéance.
    SOURCE_TIMEOUT = "source_timeout"
    #: Source perdue en cours de capture (appareil débranché, flux mort).
    SOURCE_LOST = "source_lost"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    STORAGE_FULL = "storage_full"
    WRITE_FAILED = "write_failed"
    FINALIZE_FAILED = "finalize_failed"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    UNSUPPORTED_SOURCE = "unsupported_source"
    #: Capture interrompue par la mort de Core, réconciliée au démarrage suivant
    #: avec des octets : preuve `partial` récupérable.
    RECOVERABLE_PARTIAL = "recoverable_partial"
    #: Capture interrompue par la mort de Core, sans aucun octet récupérable.
    CAPTURE_INTERRUPTED = "capture_interrupted"
    #: Perte datée en cours de capture (file débordée...) : la preuve a un trou.
    CAPTURE_GAP = "capture_gap"
    #: Session ou Context illisible au démarrage : aucune capture sans association.
    ASSOCIATION_UNAVAILABLE = "capture_association_unavailable"
    #: Core s'arrête : aucun démarrage admis.
    SERVICE_STOPPING = "capture_service_stopping"
    #: Réservés à la transcription (Slice 06), même catalogue.
    TRANSCRIPTION_UNAVAILABLE = "transcription_unavailable"
    TRANSCRIPTION_TIMEOUT = "transcription_timeout"


HTTP_STATUS: Mapping[CaptureErrorCode, int] = MappingProxyType({
    CaptureErrorCode.INVALID_CAPTURE: 400,
    CaptureErrorCode.CAPTURE_NOT_FOUND: 404,
    CaptureErrorCode.INVALID_TRANSITION: 409,
    CaptureErrorCode.ALREADY_ACTIVE: 409,
    CaptureErrorCode.SOURCE_UNAVAILABLE: 503,
    CaptureErrorCode.PERMISSION_DENIED: 403,
    CaptureErrorCode.SOURCE_TIMEOUT: 504,
    CaptureErrorCode.SOURCE_LOST: 502,
    CaptureErrorCode.STORAGE_UNAVAILABLE: 503,
    CaptureErrorCode.STORAGE_FULL: 507,
    CaptureErrorCode.WRITE_FAILED: 500,
    CaptureErrorCode.FINALIZE_FAILED: 500,
    CaptureErrorCode.UNSUPPORTED_PLATFORM: 501,
    CaptureErrorCode.UNSUPPORTED_SOURCE: 400,
    CaptureErrorCode.RECOVERABLE_PARTIAL: 409,
    CaptureErrorCode.CAPTURE_INTERRUPTED: 409,
    CaptureErrorCode.CAPTURE_GAP: 409,
    CaptureErrorCode.ASSOCIATION_UNAVAILABLE: 503,
    CaptureErrorCode.SERVICE_STOPPING: 503,
    CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE: 503,
    CaptureErrorCode.TRANSCRIPTION_TIMEOUT: 504,
})


class CaptureError(ValueError):
    """Refus ou échec nommé ; `code` stable, `status` HTTP, `capture_id` s'il existe déjà une ligne."""

    def __init__(self, code: CaptureErrorCode, message: str, *, capture_id: str | None = None) -> None:
        super().__init__(message)
        self.code = CaptureErrorCode(code)
        self.status = HTTP_STATUS[self.code]
        self.capture_id = capture_id


def _invalid(message: str) -> CaptureError:
    return CaptureError(CaptureErrorCode.INVALID_CAPTURE, message)


# ------------------------------------------------------------------ vocabulaire


class CaptureChannel(StrEnum):
    """Famille de média. Caméra (D18) : nouveau canal + sa source, sans migration (pas de CHECK SQL)."""

    AUDIO = "audio"
    SCREEN = "screen"


class CaptureMode(StrEnum):
    #: Début et fin explicites (enregistrement) ; une seule par canal/appareil.
    CONTINUOUS = "continuous"
    #: Action ponctuelle (capture d'écran) : jamais en conflit avec une continue.
    ONE_SHOT = "one_shot"


class CaptureState(StrEnum):
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


OPEN_STATES = frozenset({CaptureState.STARTING, CaptureState.ACTIVE, CaptureState.STOPPING})
TERMINAL_STATES = frozenset({CaptureState.COMPLETE, CaptureState.PARTIAL, CaptureState.FAILED})

#: Transitions permises. `starting -> partial` et `active -> partial|failed`
#: ne servent qu'à la réconciliation après la mort de Core (aucun `stopping`
#: n'a pu être écrit) ; en vie, toute fin passe par `stopping`, sauf l'échec
#: au démarrage (`starting -> failed`).
_NEXT: Mapping[CaptureState, frozenset[CaptureState]] = MappingProxyType({
    CaptureState.STARTING: frozenset({CaptureState.ACTIVE, CaptureState.STOPPING, CaptureState.FAILED,
                                      CaptureState.PARTIAL}),
    CaptureState.ACTIVE: frozenset({CaptureState.STOPPING, CaptureState.PARTIAL, CaptureState.FAILED}),
    CaptureState.STOPPING: frozenset({CaptureState.COMPLETE, CaptureState.PARTIAL, CaptureState.FAILED}),
})


class StopReason(StrEnum):
    """Pourquoi une capture s'est terminée (activité `capture.stopped`, colonne `data`)."""

    USER = "user"
    SOURCE_LOST = "source_lost"
    STORAGE_FAILURE = "storage_failure"
    START_FAILED = "start_failed"
    CORE_SHUTDOWN = "core_shutdown"
    #: Action ponctuelle terminée (capture d'écran).
    ONE_SHOT = "one_shot"
    #: Réconciliée au démarrage suivant après la mort de Core.
    RECOVERED = "recovered"


#: Nature de l'Artifact principal d'une capture.
ARTIFACT_KIND: Mapping[tuple[CaptureChannel, CaptureMode], ArtifactKind] = MappingProxyType({
    (CaptureChannel.AUDIO, CaptureMode.CONTINUOUS): ArtifactKind.AUDIO_RECORDING,
    (CaptureChannel.SCREEN, CaptureMode.CONTINUOUS): ArtifactKind.SCREEN_RECORDING,
    (CaptureChannel.SCREEN, CaptureMode.ONE_SHOT): ArtifactKind.SCREENSHOT,
})


def artifact_kind_of(channel: CaptureChannel, mode: CaptureMode) -> ArtifactKind:
    try:
        return ARTIFACT_KIND[(channel, mode)]
    except KeyError:
        raise CaptureError(CaptureErrorCode.UNSUPPORTED_SOURCE,
                           f"no {mode.value} capture on channel {channel.value}") from None


def new_capture_id() -> str:
    return f"{CAPTURE_ID_PREFIX}{uuid.uuid4().hex}"


def check_capture_id(value: object, name: str = "capture_id") -> None:
    check_prefixed_id(_invalid, name, value, CAPTURE_ID_PREFIX)


def _check_token(name: str, value: object, limit: int, *, required: bool = True) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or not value or len(value) > limit or not TOKEN.fullmatch(value):
        raise _invalid(f"{name} must be a short token (<= {limit} chars), got {preview(value)}")


def _check_count(name: str, value: object) -> None:
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise _invalid(f"{name} must be a non-negative integer, got {preview(value)}")


def _freeze_data(value: object) -> Mapping[str, Any]:
    def fail(message: str) -> CaptureError:
        return _invalid(message.replace("runtime_metadata", "data"))

    return freeze_runtime_metadata(fail, value, max_keys=MAX_CAPTURE_DATA_KEYS, max_key_chars=64,
                                   max_value_chars=MAX_CAPTURE_DATA_VALUE_CHARS)


# ------------------------------------------------------------------ valeur


@dataclass(frozen=True, slots=True)
class CaptureRecord:
    """Intention et état durables d'une capture (ligne `captures`). Voir `docs/capture.md`."""

    capture_id: str
    channel: CaptureChannel
    mode: CaptureMode
    #: Nom de la source (`microphone`, `desktop`, `fake`...).
    source: str
    device: str
    state: CaptureState
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None = None
    stop_requested_at: datetime | None = None
    ended_at: datetime | None = None
    jarvis_session_id: str | None = None
    context_id: str | None = None
    #: Artifact principal (média) ; attaché pendant `starting`.
    artifact_id: str | None = None
    error_code: str | None = None
    stop_reason: StopReason | None = None
    #: Trous datés connus (activité `capture.gap`).
    gaps: int = 0
    #: Octets écrits dans le payload, connus à la fin (mesurés en direct par `status`).
    bytes_written: int = 0
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        check_capture_id(self.capture_id)
        for name, enum in (("channel", CaptureChannel), ("mode", CaptureMode), ("state", CaptureState)):
            if not isinstance(getattr(self, name), enum):
                raise _invalid(f"{name} must be a {enum.__name__}")
        _check_token("source", self.source, MAX_SOURCE_CHARS)
        _check_token("device", self.device, MAX_DEVICE_CHARS)
        for name in ("created_at", "updated_at"):
            check_aware(_invalid, name, getattr(self, name))
        for name in ("activated_at", "stop_requested_at", "ended_at"):
            check_aware(_invalid, name, getattr(self, name), required=False)
        if self.updated_at < self.created_at:
            raise _invalid("updated_at must not precede created_at")
        if self.jarvis_session_id is not None:
            check_prefixed_id(_invalid, "jarvis_session_id", self.jarvis_session_id, SESSION_ID_PREFIX)
        if self.context_id is not None:
            check_prefixed_id(_invalid, "context_id", self.context_id, CONTEXT_ID_PREFIX)
            if self.jarvis_session_id is None:
                raise _invalid("a capture with a context_id must name its jarvis_session_id")
        if self.artifact_id is not None:
            check_prefixed_id(_invalid, "artifact_id", self.artifact_id, ARTIFACT_ID_PREFIX)
        _check_token("error_code", self.error_code, 64, required=False)
        if self.stop_reason is not None and not isinstance(self.stop_reason, StopReason):
            raise _invalid("stop_reason must be a StopReason")
        _check_count("gaps", self.gaps)
        _check_count("bytes_written", self.bytes_written)
        if self.state is CaptureState.COMPLETE and self.error_code is not None:
            raise _invalid("a complete capture carries no error_code")
        if self.state in (CaptureState.PARTIAL, CaptureState.FAILED) and self.error_code is None:
            raise _invalid(f"a {self.state.value} capture must say why (error_code)")
        if self.is_terminal and self.ended_at is None:
            raise _invalid("a finished capture must carry ended_at")
        if not self.is_terminal and self.ended_at is not None:
            raise _invalid("an open capture has no ended_at")
        object.__setattr__(self, "data", _freeze_data(self.data))

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_STATES

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def device_key(self) -> tuple[CaptureChannel, str]:
        return (self.channel, self.device)

    def to_payload(self) -> dict[str, Any]:
        def iso(value: datetime | None) -> str | None:
            return None if value is None else value.isoformat()

        return {
            "capture_id": self.capture_id, "channel": self.channel.value, "mode": self.mode.value,
            "source": self.source, "device": self.device, "state": self.state.value,
            "created_at": iso(self.created_at), "updated_at": iso(self.updated_at),
            "activated_at": iso(self.activated_at), "stop_requested_at": iso(self.stop_requested_at),
            "ended_at": iso(self.ended_at), "jarvis_session_id": self.jarvis_session_id,
            "context_id": self.context_id, "artifact_id": self.artifact_id, "error_code": self.error_code,
            "stop_reason": None if self.stop_reason is None else self.stop_reason.value, "gaps": self.gaps,
            "bytes_written": self.bytes_written, "data": dict(self.data),
        }

    @classmethod
    def from_payload(cls, payload: object) -> CaptureRecord:
        """Strict : champ inconnu ou manquant, type faux, date naïve, énum inconnue -> `invalid_capture`."""

        payload = strict_keys(_invalid, "capture", payload, _KEYS, required=_KEYS)
        reason = payload["stop_reason"]
        return cls(
            capture_id=payload["capture_id"],
            channel=parse_enum(_invalid, "channel", payload["channel"], CaptureChannel),
            mode=parse_enum(_invalid, "mode", payload["mode"], CaptureMode),
            source=payload["source"], device=payload["device"],
            state=parse_enum(_invalid, "state", payload["state"], CaptureState),
            created_at=parse_dt(_invalid, "created_at", payload["created_at"]),
            updated_at=parse_dt(_invalid, "updated_at", payload["updated_at"]),
            activated_at=parse_dt(_invalid, "activated_at", payload["activated_at"], required=False),
            stop_requested_at=parse_dt(_invalid, "stop_requested_at", payload["stop_requested_at"], required=False),
            ended_at=parse_dt(_invalid, "ended_at", payload["ended_at"], required=False),
            jarvis_session_id=payload["jarvis_session_id"], context_id=payload["context_id"],
            artifact_id=payload["artifact_id"], error_code=payload["error_code"],
            stop_reason=None if reason is None else parse_enum(_invalid, "stop_reason", reason, StopReason),
            gaps=payload["gaps"], bytes_written=payload["bytes_written"], data=payload["data"],
        )


_KEYS = frozenset({
    "capture_id", "channel", "mode", "source", "device", "state", "created_at", "updated_at", "activated_at",
    "stop_requested_at", "ended_at", "jarvis_session_id", "context_id", "artifact_id", "error_code", "stop_reason",
    "gaps", "bytes_written", "data",
})

#: Fixés au démarrage, jamais modifiés ensuite.
IDENTITY_FIELDS = ("capture_id", "channel", "mode", "source", "device", "created_at", "jarvis_session_id",
                   "context_id")


# ------------------------------------------------------------------ transitions


def new_capture(
    *,
    channel: CaptureChannel,
    mode: CaptureMode,
    source: str,
    now: datetime,
    device: str = DEFAULT_DEVICE,
    jarvis_session_id: str | None = None,
    context_id: str | None = None,
    data: Mapping[str, Any] | None = None,
    capture_id: str | None = None,
) -> CaptureRecord:
    """Capture `starting` : identité et association fixées (Context actif au démarrage)."""

    return CaptureRecord(
        capture_id=new_capture_id() if capture_id is None else capture_id, channel=channel, mode=mode,
        source=source, device=device, state=CaptureState.STARTING, created_at=now, updated_at=now,
        jarvis_session_id=jarvis_session_id, context_id=context_id, data={} if data is None else data,
    )


def _move(record: CaptureRecord, target: CaptureState) -> None:
    if target not in _NEXT.get(record.state, frozenset()):
        raise CaptureError(CaptureErrorCode.INVALID_TRANSITION,
                           f"capture {record.capture_id}: {record.state.value} -> {target.value} is not allowed",
                           capture_id=record.capture_id)


def _later(record: CaptureRecord, now: datetime) -> datetime:
    return max(now, record.updated_at)


def attach_artifact(record: CaptureRecord, artifact_id: str, *, now: datetime) -> CaptureRecord:
    """Artifact principal, attaché une fois pendant le démarrage (`starting`, ou `stopping` si un arrêt
    a été demandé avant que la source ne réponde)."""

    if record.state not in (CaptureState.STARTING, CaptureState.STOPPING) or record.artifact_id is not None             or record.activated_at is not None:
        raise CaptureError(CaptureErrorCode.INVALID_TRANSITION,
                           f"capture {record.capture_id}: artifact is attached once, while starting",
                           capture_id=record.capture_id)
    return replace(record, artifact_id=artifact_id, updated_at=_later(record, now))


def activate(record: CaptureRecord, *, now: datetime) -> CaptureRecord:
    """`starting -> active` : la source produit."""

    _move(record, CaptureState.ACTIVE)
    at = _later(record, now)
    return replace(record, state=CaptureState.ACTIVE, activated_at=at, updated_at=at)


def request_stop(record: CaptureRecord, *, now: datetime, reason: StopReason) -> CaptureRecord:
    """`starting|active -> stopping`. Déjà `stopping` ou terminée : inchangée (idempotent)."""

    if record.state is CaptureState.STOPPING or record.is_terminal:
        return record
    _move(record, CaptureState.STOPPING)
    at = _later(record, now)
    return replace(record, state=CaptureState.STOPPING, stop_requested_at=at, updated_at=at, stop_reason=reason)


def finish(
    record: CaptureRecord,
    *,
    now: datetime,
    state: CaptureState,
    error_code: str | None = None,
    reason: StopReason | None = None,
    bytes_written: int | None = None,
    gaps: int | None = None,
    data: Mapping[str, Any] | None = None,
) -> CaptureRecord:
    """Fin : `complete` (depuis `stopping`, sans erreur), `partial` ou `failed` (avec `error_code`)."""

    if state not in TERMINAL_STATES:
        raise _invalid("finish reaches complete, partial or failed")
    _move(record, state)
    at = _later(record, now)
    return replace(
        record, state=state, updated_at=at, ended_at=at, error_code=error_code,
        stop_reason=record.stop_reason if reason is None else reason,
        bytes_written=record.bytes_written if bytes_written is None else bytes_written,
        gaps=record.gaps if gaps is None else gaps,
        data=record.data if data is None else {**record.data, **data},
    )


def check_capture_update(previous: CaptureRecord, updated: CaptureRecord) -> None:
    """Garde du magasin : identité fixe, transitions de `_NEXT` seulement, terminale gelée."""

    if previous.capture_id != updated.capture_id:
        raise _invalid("an update must target the same capture")
    for name in IDENTITY_FIELDS:
        if getattr(previous, name) != getattr(updated, name):
            raise CaptureError(CaptureErrorCode.INVALID_TRANSITION,
                               f"capture {previous.capture_id}: {name} is fixed at start",
                               capture_id=previous.capture_id)
    if previous.is_terminal:
        raise CaptureError(CaptureErrorCode.INVALID_TRANSITION,
                           f"capture {previous.capture_id} is {previous.state.value}: it cannot change",
                           capture_id=previous.capture_id)
    if previous.state is not updated.state:
        _move(previous, updated.state)
    if previous.artifact_id is not None and updated.artifact_id != previous.artifact_id:
        raise CaptureError(CaptureErrorCode.INVALID_TRANSITION,
                           f"capture {previous.capture_id}: artifact_id is attached once",
                           capture_id=previous.capture_id)
    if updated.updated_at < previous.updated_at:
        raise _invalid("updated_at must not go backwards")
