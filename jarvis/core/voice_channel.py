"""`VoiceChannelService` : l'état du canal vocal possédé par Core, en mémoire (`docs/chat.md` › *Voice channel*).

Nourri par les rapports du processus Voice (`POST /v1/voice/channel/report`,
une fois par seconde), il rend en retour la demande « Passer au chat » en
cours. Core, qui admet les tours texte, est ainsi juge du verrou du Chat :
`write_gate()` est **synchrone** pour que la route `brain-turns` (Slice 03)
la lise sans `await` avant `brain.submit`.

Rien n'est persisté : un Core redémarré tire un nouvel `epoch`, passe
`VOICE_CHANNEL_FRESH_S` en `unknown`, puis le premier rapport rétablit la
vérité. Ce service ne touche ni Session, ni Board, ni Brain, ni sous-agent,
ni `InteractionMode` : la désactivation est exécutée par Voice lui-même
(`mute()`), Core ne fait que la demander.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
import time
from typing import Any
import uuid

from jarvis.domain.voice_channel import (
    VOICE_CHANNEL_SCHEMA_VERSION, VOICE_DISABLE_EXPIRED, VOICE_DISABLE_FAILED, DisableRequest, DisableStatus,
    VoiceChannelReport, VoiceChannelState, channel_view,
)
from jarvis.ports.v2 import DiagnosticSink

#: Demandes gardées pour l'idempotence par `client_request_id` (les plus anciennes sortent).
MAX_REMEMBERED_REQUESTS = 32


def _client_request_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("client_request_id must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise ValueError("client_request_id must be a UUID string") from None
    return str(parsed)


class VoiceChannelService:
    """Dernier rapport de l'incarnation Voice courante, demande de désactivation, verrou du Chat."""

    def __init__(self, *, diagnostics: DiagnosticSink | None = None, clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._diagnostics = diagnostics
        self._clock = clock
        self._wall_clock = wall_clock
        #: Tiré à la construction : un client voit qu'il parle à une autre vie de Core.
        self.epoch = f"vce-{uuid.uuid4().hex}"
        self.started_at = clock()
        self.revision = 0
        self._report: VoiceChannelReport | None = None
        self._requests: OrderedDict[str, DisableRequest] = OrderedDict()
        self._current: str | None = None  # `client_request_id` de la dernière demande créée

    # ------------------------------------------------------------ lectures

    def write_gate(self) -> str | None:
        """Raison du refus d'écrire au Chat (`voice_active`…), `None` si permis. Synchrone, sans IO."""

        now = self._clock()
        self._settle_expired(now)
        return channel_view(self._report, self._request(), now, self.started_at)[2]

    def snapshot(self) -> dict[str, Any]:
        """Le bloc `voice` de `GET /v1/chat/state`, plus `chat_writable` et `locked_reason`."""

        now = self._clock()
        self._settle_expired(now)
        request = self._request()
        state, writable, reason = channel_view(self._report, request, now, self.started_at)
        age = None if self._report is None else max(0, round((now - self._report.received_at) * 1000))
        return {
            "voice": {"state": state.value, "epoch": self.epoch, "revision": self.revision, "report_age_ms": age,
                      "request": None if request is None else request.to_payload()},
            "chat_writable": writable,
            "locked_reason": reason,
        }

    # ------------------------------------------------------------ Voice -> Core

    def report(self, payload: object) -> dict[str, Any]:
        """Retenir un rapport (ou l'ignorer s'il est ancien) ; rendre la demande en cours. `ValueError` si mal formé."""

        now = self._clock()
        report = VoiceChannelReport.from_payload(payload, received_at=now)
        self._settle_expired(now)
        accepted = report.supersedes(self._report)
        if not accepted:
            self._trace("core.voice_channel.report_rejected", "Rapport vocal ancien ignoré", level="warning",
                        data={"code": "voice_report_stale", "voice_incarnation_id": report.voice_incarnation_id,
                              "seq": report.seq, "last_seq": self._report.seq if self._report else None})
        else:
            previous, self._report = self._report, report
            if (previous is None or previous.voice_incarnation_id != report.voice_incarnation_id
                    or previous.lifecycle_state != report.lifecycle_state):
                self.revision += 1
            self._settle_from(report, now)
        request = self._request()
        live = request is not None and request.live(now)
        return {"schema_version": VOICE_CHANNEL_SCHEMA_VERSION, "epoch": self.epoch, "revision": self.revision,
                "accepted": accepted,
                "disable_request": {"request_id": request.request_id, "requested_at": request.requested_at_iso}
                if live else None}

    # ------------------------------------------------------------ Control Center -> Core

    def disable(self, payload: object) -> tuple[int, dict[str, Any]]:
        """« Passer au chat » : (statut HTTP, corps). Idempotent par `client_request_id`. `ValueError` si mal formé."""

        if not isinstance(payload, dict) or set(payload) != {"client_request_id"}:
            raise ValueError("disable request must be exactly {\"client_request_id\": \"<uuid>\"}")
        client_id = _client_request_id(payload["client_request_id"])
        now = self._clock()
        self._settle_expired(now)
        known = self._requests.get(client_id)
        if known is not None:
            return 202, self._disable_answer(known, now)
        current = self._request()
        if current is not None and current.live(now):
            return 202, self._disable_answer(current, now)  # une seule demande en cours : on rend celle-là
        state, _, _ = channel_view(self._report, current, now, self.started_at)
        if state in (VoiceChannelState.ABSENT, VoiceChannelState.BACKGROUND):
            return 200, {"state": state.value, "request_id": None, "status": None}
        request = DisableRequest(request_id=f"vcr-{uuid.uuid4().hex}", client_request_id=client_id,
                                 requested_at=now, requested_at_iso=self._wall_clock().isoformat())
        self._remember(request)
        self.revision += 1
        self._trace("core.voice_channel.disable_requested", "Désactivation du vocal demandée",
                    data={"request_id": request.request_id, "voice_state": state.value})
        return 202, self._disable_answer(request, now)

    # ------------------------------------------------------------ interne

    def _disable_answer(self, request: DisableRequest, now: float) -> dict[str, Any]:
        state, _, _ = channel_view(self._report, self._request(), now, self.started_at)
        return {"request_id": request.request_id, "state": state.value, "status": request.status.value}

    def _request(self) -> DisableRequest | None:
        return None if self._current is None else self._requests.get(self._current)

    def _remember(self, request: DisableRequest) -> None:
        self._requests[request.client_request_id] = request
        self._requests.move_to_end(request.client_request_id)
        self._current = request.client_request_id
        while len(self._requests) > MAX_REMEMBERED_REQUESTS:
            self._requests.popitem(last=False)

    def _settle(self, request: DisableRequest, status: DisableStatus, code: str | None) -> None:
        self._requests[request.client_request_id] = replace(request, status=status, code=code)
        self.revision += 1
        self._trace("core.voice_channel.disable_settled", f"Désactivation du vocal : {status.value}",
                    level="info" if status is DisableStatus.ACCEPTED else "warning",
                    data={"request_id": request.request_id, "status": status.value, "code": code})

    def _settle_expired(self, now: float) -> None:
        request = self._request()
        if request is not None and request.status is DisableStatus.PENDING and not request.live(now):
            self._settle(request, DisableStatus.EXPIRED, VOICE_DISABLE_EXPIRED)

    def _settle_from(self, report: VoiceChannelReport, now: float) -> None:
        """Un rapport retenu conclut la demande en cours : acquittement explicite, ou retour au fond constaté."""

        request = self._request()
        if request is None or not request.live(now):
            return
        background = report.state is VoiceChannelState.BACKGROUND
        ack = report.ack
        if ack is not None and ack.request_id == request.request_id:
            if ack.accepted and background:
                self._settle(request, DisableStatus.ACCEPTED, None)
            else:
                self._settle(request, DisableStatus.FAILED, ack.code or VOICE_DISABLE_FAILED)
        elif background:
            # Voice est au fond sans avoir encore acquitté (mute par délai, par la touche) : le but est atteint.
            self._settle(request, DisableStatus.ACCEPTED, None)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=data or {})
        except Exception:  # noqa: BLE001 - argued silence: a broken journal never changes the voice lock
            pass
