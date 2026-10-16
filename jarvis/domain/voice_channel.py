"""Canal vocal vu de Core : rapports de Voice, demande de désactivation, verrou du Chat (`docs/chat.md` › *Voice channel*).

Domaine pur, sans horloge ni IO : `channel_view` dérive l'état affiché et le
droit d'écrire au Chat du **dernier rapport** de l'incarnation Voice courante,
de la demande de désactivation éventuelle et de l'âge de Core. Le service en
mémoire (`jarvis/core/voice_channel.py`) tient ces faits ; ce module dit ce
qu'ils valent.

Ce n'est **ni** `InteractionMode` **ni** `OutputDisposition` : un autre axe,
jamais lu ici.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any

#: Fraîcheur d'un rapport, et période `unknown` après le démarrage de Core
#: (alignée sur `VOICE_HEARTBEAT_MAX_AGE_S` du Control Center).
VOICE_CHANNEL_FRESH_S = 5.0
#: Une demande de désactivation non acquittée dans ce délai expire.
VOICE_DISABLE_TIMEOUT_S = 10.0
VOICE_CHANNEL_SCHEMA_VERSION = 1

VOICE_DISABLE_FAILED = "voice_disable_failed"
VOICE_DISABLE_EXPIRED = "voice_disable_expired"

_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_CODE = re.compile(r"[a-z0-9_]{1,64}")
_MAX_STATE_CHARS = 32
_MAX_SEQ = 2**53


class VoiceChannelState(StrEnum):
    ABSENT = "absent"
    UNKNOWN = "unknown"
    BACKGROUND = "background"
    CONNECTING = "connecting"
    ACTIVE = "active"
    ERROR = "error"
    SWITCHING = "switching"


#: États qu'un rapport de Voice peut porter (`VoiceLifecycleState`). Une autre
#: valeur bien formée (Voice plus récent) donne `unknown`, jamais une écriture.
REPORTED_STATES = frozenset({VoiceChannelState.BACKGROUND, VoiceChannelState.ACTIVE,
                             VoiceChannelState.CONNECTING, VoiceChannelState.ERROR})
#: Seuls états où le Chat peut écrire.
WRITABLE_STATES = frozenset({VoiceChannelState.ABSENT, VoiceChannelState.BACKGROUND})


class DisableStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    FAILED = "failed"
    EXPIRED = "expired"


def locked_reason_for(state: VoiceChannelState) -> str | None:
    """`voice_<état>` pour un état verrouillé, `None` si l'écriture est permise."""

    return None if state in WRITABLE_STATES else f"voice_{state.value}"


def _require_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{field} must be an identifier of 1 to 128 characters [A-Za-z0-9_.:-]")
    return value


def _closed(payload: object, allowed: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be an object")
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unexpected {name} fields: {', '.join(sorted(map(str, unknown)))}")
    return payload


@dataclass(frozen=True, slots=True)
class VoiceChannelAck:
    """Acquittement d'une demande par Voice, porté par un rapport."""

    request_id: str
    accepted: bool
    code: str | None = None

    @classmethod
    def from_payload(cls, payload: object) -> VoiceChannelAck:
        data = _closed(payload, frozenset({"request_id", "result", "code"}), "ack")
        result = data.get("result")
        if result not in ("accepted", "failed"):
            raise ValueError("ack.result must be 'accepted' or 'failed'")
        code = data.get("code")
        if code is not None and (not isinstance(code, str) or not _CODE.fullmatch(code)):
            raise ValueError("ack.code must be null or a stable code [a-z0-9_]")
        return cls(_require_id(data.get("request_id"), "ack.request_id"), result == "accepted", code)


@dataclass(frozen=True, slots=True)
class VoiceChannelReport:
    """Un rapport `POST /v1/voice/channel/report`, validé strictement ; `received_at` est l'horloge de Core."""

    voice_incarnation_id: str
    seq: int
    lifecycle_state: str
    conversation_id: str | None
    ack: VoiceChannelAck | None
    received_at: float

    @classmethod
    def from_payload(cls, payload: object, *, received_at: float) -> VoiceChannelReport:
        data = _closed(payload, frozenset({"schema_version", "voice_incarnation_id", "seq", "lifecycle_state",
                                           "conversation_id", "ack"}), "report")
        if data.get("schema_version") != VOICE_CHANNEL_SCHEMA_VERSION or isinstance(data.get("schema_version"), bool):
            raise ValueError(f"schema_version must be {VOICE_CHANNEL_SCHEMA_VERSION}")
        seq = data.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or not 0 <= seq < _MAX_SEQ:
            raise ValueError("seq must be a non-negative integer")
        state = data.get("lifecycle_state")
        if not isinstance(state, str) or not 0 < len(state) <= _MAX_STATE_CHARS:
            raise ValueError(f"lifecycle_state must be a string of 1 to {_MAX_STATE_CHARS} characters")
        conversation = data.get("conversation_id")
        if conversation is not None:
            conversation = _require_id(conversation, "conversation_id")
        ack = data.get("ack")
        return cls(_require_id(data.get("voice_incarnation_id"), "voice_incarnation_id"), seq, state, conversation,
                   None if ack is None else VoiceChannelAck.from_payload(ack), received_at)

    @property
    def state(self) -> VoiceChannelState:
        """L'état rapporté ; une valeur hors `REPORTED_STATES` vaut `unknown`."""

        try:
            state = VoiceChannelState(self.lifecycle_state)
        except ValueError:
            return VoiceChannelState.UNKNOWN
        return state if state in REPORTED_STATES else VoiceChannelState.UNKNOWN

    def supersedes(self, previous: VoiceChannelReport | None) -> bool:
        """Nouvelle incarnation, ou `seq` strictement plus grand pour la même."""

        return (previous is None or previous.voice_incarnation_id != self.voice_incarnation_id
                or self.seq > previous.seq)


@dataclass(frozen=True, slots=True)
class DisableRequest:
    """Demande « Passer au chat » ; `requested_at` est l'horloge monotone de Core."""

    request_id: str
    client_request_id: str
    requested_at: float
    requested_at_iso: str
    status: DisableStatus = DisableStatus.PENDING
    code: str | None = None

    def live(self, now: float) -> bool:
        """En attente et pas encore expirée à `now`."""

        return self.status is DisableStatus.PENDING and now - self.requested_at < VOICE_DISABLE_TIMEOUT_S

    def to_payload(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "status": self.status.value, "code": self.code}


def channel_view(report: VoiceChannelReport | None, request: DisableRequest | None, now: float,
                 started_at: float) -> tuple[VoiceChannelState, bool, str | None]:
    """(état, `chat_writable`, `locked_reason`) : la machine d'état de `docs/chat.md` › *State machine*.

    `report` est le dernier rapport retenu de l'incarnation courante ; `now` et
    `started_at` sont sur la même horloge monotone que `received_at`.
    """

    if report is not None and now - report.received_at <= VOICE_CHANNEL_FRESH_S:
        state = report.state
        if state is not VoiceChannelState.BACKGROUND and request is not None and request.live(now):
            state = VoiceChannelState.SWITCHING
    elif report is None and now - started_at < VOICE_CHANNEL_FRESH_S:
        state = VoiceChannelState.UNKNOWN  # Core vient de (re)démarrer : Voice n'a pas encore parlé
    else:
        state = VoiceChannelState.ABSENT
    reason = locked_reason_for(state)
    return state, reason is None, reason
