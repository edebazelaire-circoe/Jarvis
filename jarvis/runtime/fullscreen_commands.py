"""Courtier du plein écran de surface (handoff jarvis-interactive-presentation-studio, Slice 03).

Frère de `jarvis/runtime/barehands_commands.py` (même transport : une commande en
vol, remise exclusive à un long-poll, reçu à usage unique, échéance) avec deux
différences, qui sont la raison d'être de la Slice :

1. **La remise n'est pas l'effet.** Le navigateur exige un geste pour entrer en
   plein écran. Le reçu de remise (≤ `DELIVERY_DEADLINE_S`) dit donc, pour `enter`,
   `needs_gesture` : la demande est **armée**, l'invite est visible. Le clic, le
   refus, l'échéance d'armement ou l'annulation arrivent après, par
   `report()` (`POST /api/fullscreen/state`), et c'est le navigateur qui les dicte
   (`fullscreenchange`).
2. **L'état courant est tenu ici** (`snapshot()`), validé par la table de
   transitions du domaine. Un agent lit « sommes-nous en plein écran ? » au lieu
   de le déduire d'une commande passée.

**Une armée ne dure pas toujours.** L'échéance d'armement est portée par la page
(compteur visible) *et* revérifiée ici à chaque lecture d'état : si la page est
morte avec l'invite à l'écran, le serveur ne restera pas en `needs_gesture`
indéfiniment (second mécanisme, qui ne bloque pas de la même façon).

Le journal ne porte que des identifiants courts, des noms d'état, des durées et
des codes : jamais de contenu de page.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import secrets
from typing import Any

from jarvis.domain.surface_fullscreen import (
    COMMAND_BUSY,
    COMMAND_CANCELLED,
    COMMAND_EXPIRED,
    DEFAULT_STATE,
    DELIVERY_DEADLINE_S,
    NO_VISIBLE_PAGE,
    STALE_REPORT,
    STATE_EXPLANATIONS,
    UNKNOWN_COMMAND_ID,
    SurfaceFullscreenError,
    SurfaceFullscreenRequest,
    check_command_id,
    event_for_report,
    next_state,
    short_id,
)
from jarvis.runtime.journal import RuntimeJournal

#: Marge entre l'échéance d'armement de la page et celle du serveur : la page
#: expire d'abord et le dit ; le serveur ne tranche que si elle se tait.
ARM_GRACE_S = 2.0

#: Événement du domaine produit par l'état de reçu d'une demande `enter`.
_RECEIPT_EVENT = {
    "needs_gesture": "request_enter",
    "entered": "browser_entered",
    "unsupported": "unsupported",
    "refused": "browser_denied",
}


@dataclass(slots=True)
class _Pending:
    command_id: str
    request: SurfaceFullscreenRequest
    created: float
    deadline: float
    result: asyncio.Future
    delivered: bool = False
    deliveries: int = 0
    consumed: bool = False


class FullscreenCommandBroker:
    """Une commande de plein écran en vol à la fois, plus l'état que la page constate."""

    def __init__(self, *, journal: RuntimeJournal | None = None, deadline_s: float = DELIVERY_DEADLINE_S,
                 clock: Any = None) -> None:
        self.journal = journal
        self.deadline_s = deadline_s
        self._clock = clock
        self._pending: _Pending | None = None
        self._wake: asyncio.Event | None = None
        self._closed = False
        self._state = DEFAULT_STATE
        self._object_id: str | None = None
        self._armed_id: str | None = None
        self._armed_until: float | None = None
        self._code: str | None = None
        self._reason: str | None = None
        self._display_selection = "not_requested"
        #: Pages qui ont dit être cachées (identifiant de page → rien), bornées : une page cachée ne reçoit
        #: jamais une commande, même si un de ses long-polls est encore ouvert (QA-1 POLISH 2).
        self._hidden: dict[str, None] = {}

    # ------------------------------------------------------------ temps

    def _now(self) -> float:
        if self._clock is not None:
            return float(self._clock())
        return asyncio.get_running_loop().time()

    # ------------------------------------------------------------ cycle de vie

    def close(self) -> None:
        self._closed = True
        pending, self._pending = self._pending, None
        if pending is not None and not pending.result.done():
            pending.result.set_exception(SurfaceFullscreenError(
                COMMAND_CANCELLED, "Le Control Center s'arrête : commande de plein écran abandonnée.", 503,
                short_id(pending.command_id)))
        self._set_wake()

    # ------------------------------------------------------------ état

    def snapshot(self) -> dict[str, Any]:
        """L'état tel que la page l'a rapporté, avec la vérification d'échéance d'armement."""

        if self._state == "needs_gesture" and self._armed_until is not None and self._now() > self._armed_until:
            self._apply("deadline", code="fullscreen_arm_expired",
                        reason="L'invite est restée sans clic ; la page ne l'a pas retirée à temps.", source="server")
        return {
            "state": self._state,
            "object_id": self._object_id,
            "id": self._armed_id,
            "code": self._code,
            "reason": self._reason,
            "display_selection": self._display_selection,
            "explanation": STATE_EXPLANATIONS[self._state],
        }

    def _apply(self, event: str, *, code: str | None, reason: str | None, source: str,
               object_id: str | None = None, display_selection: str | None = None) -> str:
        before = self._state
        after = next_state(before, event)
        if before == "entered" and after == "entered" and event in ("browser_denied", "request_enter"):
            # Une demande refusée pendant qu'une surface est plein écran ne change RIEN à ce que fait le
            # navigateur : l'objet, le code et la raison décrivent toujours le plein écran réel (QA-1 POLISH 1).
            self._emit("fullscreen.request_refused_while_entered",
                       f"demande ({event}) sans effet : une surface est déjà plein écran", level="warning",
                       data={"event": event, "code": code, "source": source, "object_id": self._object_id,
                             "requested_object_id": object_id})
            return after
        self._state = after
        self._code = code
        self._reason = reason
        if after == "entered":
            self._object_id = object_id if object_id is not None else self._object_id
            self._armed_id = None
            self._armed_until = None
        elif after in ("exited", "expired", "refused", "unsupported"):
            self._armed_id = None
            self._armed_until = None
            if after == "exited":
                self._object_id = None
        if display_selection is not None:
            self._display_selection = display_selection
        level = "info" if after in ("entered", "exited", "needs_gesture") else "warning"
        self._emit("fullscreen.state_changed", f"plein écran : {before} -> {after} ({event})", level=level,
                   data={"from": before, "to": after, "event": event, "code": code, "source": source,
                         "object_id": self._object_id, "display_selection": self._display_selection})
        self._set_wake()   # l'armement a peut-être changé : les long-polls en attente le relisent
        return after

    # ------------------------------------------------------------ visibilité des pages

    def armed_id(self) -> str | None:
        """L'identifiant court de l'armement courant, ou `None` (lu par les pages pour réconcilier leur invite)."""

        self.snapshot()
        return self._armed_id

    def mark_visibility(self, page: str | None, visible: bool) -> None:
        """Une page dit si elle est visible. Une page cachée ne reçoit plus de commande."""

        if not page:
            return
        if visible:
            self._hidden.pop(page, None)
            return
        self._hidden.pop(page, None)
        self._hidden[page] = None
        while len(self._hidden) > 64:
            self._hidden.pop(next(iter(self._hidden)))
        self._emit("fullscreen.page_hidden", "une page du Control Center est cachée : pas de remise", data={"page": page[:8]})

    # ------------------------------------------------------------ demande de l'agent

    async def request(self, request: SurfaceFullscreenRequest) -> dict[str, Any]:
        """Remettre la commande à la page et rendre son reçu, au plus `deadline_s`.

        Rend `{state, code, reason, display_selection, command, id, deliveries, duration_ms, snapshot}`
        ou lève `SurfaceFullscreenError` : jamais un succès par défaut.
        """

        if self._closed:
            raise SurfaceFullscreenError(COMMAND_CANCELLED, "Le Control Center s'arrête.", 503)
        if self._pending is not None:
            self._emit("fullscreen.command_busy", f"commande {request.action} refusée : une autre est en cours",
                       level="warning", data={"code": COMMAND_BUSY, "command": request.action,
                                              "pending": short_id(self._pending.command_id)})
            raise SurfaceFullscreenError(
                COMMAND_BUSY, "Une commande de plein écran est déjà en cours : réessaie dans une seconde.", 409)
        loop = asyncio.get_running_loop()
        now = loop.time()
        pending = _Pending(secrets.token_urlsafe(24), request, now, now + self.deadline_s, loop.create_future())
        self._pending = pending
        self._emit("fullscreen.command_requested", f"commande de plein écran demandée : {request.action}",
                   data={"command": request.action, "id": short_id(pending.command_id), "object_id": request.object_id,
                         "display": request.display, "arm_s": request.arm_s, "deadline_ms": round(self.deadline_s * 1000)})
        self._set_wake()
        try:
            receipt = await asyncio.wait_for(asyncio.shield(pending.result), timeout=self.deadline_s)
        except TimeoutError:
            took = pending.deliveries > 0
            code = COMMAND_EXPIRED if took else NO_VISIBLE_PAGE
            self._emit("fullscreen.command_expired",
                       f"commande {request.action} échue : "
                       + ("la page l'a prise et n'a pas répondu" if took else "aucune page visible n'a répondu"),
                       level="warning", data={"code": code, "command": request.action,
                                              "id": short_id(pending.command_id), "deliveries": pending.deliveries,
                                              "waited_ms": round((loop.time() - now) * 1000)})
            raise SurfaceFullscreenError(
                code,
                (f"La page du Control Center a pris la commande mais n'a pas répondu en {self.deadline_s:g} s : "
                 "l'issue est inconnue, demande à l'utilisateur de regarder la fenêtre."
                 if took else
                 f"Aucune page visible du Control Center n'a pris la commande en {self.deadline_s:g} s "
                 "(fenêtre fermée, onglet caché ou page pas chargée)."),
                504, short_id(pending.command_id)) from None
        except asyncio.CancelledError:
            if not pending.result.done():
                self._emit("fullscreen.command_abandoned", f"commande {request.action} abandonnée par l'appelant",
                           level="warning", data={"code": COMMAND_CANCELLED, "command": request.action,
                                                  "id": short_id(pending.command_id)})
            raise
        finally:
            if self._pending is pending:
                self._pending = None
            if not pending.result.done():
                pending.result.cancel()
        self._absorb_receipt(pending, receipt)
        duration_ms = round((loop.time() - pending.created) * 1000)
        answer = {**receipt, "command": request.action, "id": short_id(pending.command_id),
                  "deliveries": pending.deliveries, "duration_ms": duration_ms,
                  "explanation": STATE_EXPLANATIONS[receipt["state"]]}
        if request.action == "enter" and receipt["state"] == "needs_gesture":
            answer["armed_for_s"] = request.arm_s
        self._emit("fullscreen.command_answered", f"commande {request.action} : la page rapporte {receipt['state']}",
                   level="info" if receipt["state"] in ("needs_gesture", "entered", "exited") else "warning",
                   data={"command": request.action, "id": short_id(pending.command_id), "state": receipt["state"],
                         "code": receipt["code"], "duration_ms": duration_ms, "deliveries": pending.deliveries})
        answer["snapshot"] = self.snapshot()
        self._set_wake()
        return answer

    def _absorb_receipt(self, pending: _Pending, receipt: dict[str, Any]) -> None:
        """Le reçu de remise met à jour l'état tenu : ce que la page a constaté, pas ce qu'on a demandé."""

        state = receipt["state"]
        try:
            if pending.request.action == "enter":
                self._apply(_RECEIPT_EVENT[state], code=receipt["code"], reason=receipt["reason"], source="receipt",
                            object_id=receipt["object_id"] or pending.request.object_id,
                            display_selection=receipt["display_selection"])
                if state == "needs_gesture":
                    self._armed_id = short_id(pending.command_id)
                    self._armed_until = self._now() + pending.request.arm_s + ARM_GRACE_S
                    self._object_id = receipt["object_id"] or pending.request.object_id
            elif state == "exited":
                self._apply(event_for_report(self._state, "exited"), code=receipt["code"], reason=receipt["reason"],
                            source="receipt")
        except SurfaceFullscreenError as exc:
            # L'état tenu et la page divergent : on le dit (warning) et l'on garde la réponse de la page.
            self._emit("fullscreen.state_diverged", f"reçu {state} incompatible avec l'état {self._state}",
                       level="warning", data={"code": exc.code, "state": self._state, "receipt_state": state})

    # ------------------------------------------------------------ long-poll

    def wake_event(self) -> asyncio.Event:
        if self._wake is None:
            self._wake = asyncio.Event()
        return self._wake

    def _set_wake(self) -> None:
        if self._wake is not None:
            self._wake.set()
        self._wake = None

    def deliver(self, page: str | None = None) -> dict[str, Any] | None:
        """La commande à joindre à une réponse de long-poll, ou `None`. Remise exclusive, une seule fois.

        `page` : identifiant que la page présente avec son poll. Une page qui s'est déclarée cachée ne la prend pas.
        """

        pending = self._pending
        if pending is None or pending.delivered or pending.consumed:
            return None
        if page is not None and page in self._hidden:
            return None
        now = asyncio.get_running_loop().time()
        if now >= pending.deadline:
            return None
        pending.delivered = True
        pending.deliveries += 1
        remaining = max(0, round((pending.deadline - now) * 1000))
        self._emit("fullscreen.command_delivered", f"commande {pending.request.action} remise à la page",
                   data={"command": pending.request.action, "id": short_id(pending.command_id),
                         "deliveries": pending.deliveries, "remaining_ms": remaining})
        return {"id": pending.command_id, "remaining_ms": remaining, **pending.request.to_wire()}

    def expected(self, command_id: str) -> str | None:
        """L'action de la commande en attente sous cet identifiant, ou `None`. Ne consomme rien."""

        pending = self._pending
        if pending is None or pending.command_id != command_id or pending.consumed:
            return None
        return pending.request.action

    # ------------------------------------------------------------ reçu de la page

    def complete(self, command_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
        try:
            check_command_id(command_id)
        except SurfaceFullscreenError:
            self._emit("fullscreen.receipt_refused", "reçu refusé : identifiant hors forme", level="warning",
                       data={"code": UNKNOWN_COMMAND_ID, "id": None,
                             "id_chars": len(command_id) if isinstance(command_id, str) else None})
            raise
        pending = self._pending
        if pending is None or pending.command_id != command_id or pending.consumed or pending.result.done():
            self._emit("fullscreen.receipt_refused", "reçu refusé : commande inconnue ou déjà rendue",
                       level="warning", data={"code": UNKNOWN_COMMAND_ID, "id": short_id(command_id)})
            raise SurfaceFullscreenError(
                UNKNOWN_COMMAND_ID,
                "Aucune commande en attente avec cet identifiant (inconnue, déjà rendue ou échue).", 404,
                short_id(command_id))
        if asyncio.get_running_loop().time() >= pending.deadline:
            self._emit("fullscreen.receipt_refused", "reçu refusé : commande échue", level="warning",
                       data={"code": COMMAND_EXPIRED, "id": short_id(command_id)})
            raise SurfaceFullscreenError(COMMAND_EXPIRED, "Commande échue : trop tard.", 410, short_id(command_id))
        pending.consumed = True
        if not pending.result.done():
            pending.result.set_result(receipt)
        return {"command": pending.request.action, "id": command_id}

    def fail(self, command_id: str, error: SurfaceFullscreenError) -> bool:
        """Solder la commande attendue par un refus nommé de son reçu (reçu mal formé ou trop gros)."""

        pending = self._pending
        if pending is None or pending.command_id != command_id or pending.consumed or pending.result.done():
            return False
        pending.consumed = True
        pending.result.set_exception(error)
        self._emit("fullscreen.receipt_rejected", f"reçu de {pending.request.action} refusé : {error.code}",
                   level="warning", data={"code": error.code, "id": short_id(command_id)})
        return True

    # ------------------------------------------------------------ rapport d'état de la page

    def report(self, report: dict[str, Any]) -> dict[str, Any]:
        """Une transition constatée par la page (clic, refus, échéance, annulation, Échap).

        Un rapport portant l'`id` d'une armée qui n'est plus la courante est
        **périmé** (`fullscreen_stale_report`, 409) : il ne réécrit pas l'état.
        Un rapport sans `id` décrit le navigateur (Échap, entrée locale par clic).
        """

        rid = report.get("id")
        if rid is not None and self._state == "needs_gesture" and rid != self._armed_id:
            self._emit("fullscreen.report_stale", "rapport d'état périmé ignoré", level="warning",
                       data={"code": STALE_REPORT, "id": rid, "armed": self._armed_id, "state": report["state"]})
            raise SurfaceFullscreenError(STALE_REPORT, "Ce rapport concerne une demande qui n'est plus armée.", 409, rid)
        # Une armée expirée côté serveur d'abord : le rapport tardif se juge sur l'état réel.
        self.snapshot()
        if report["state"] == self._state and report["state"] != "needs_gesture":
            return self.snapshot()  # idempotent: the page repeats what is already true
        event = event_for_report(self._state, report["state"])
        try:
            self._apply(event, code=report["code"], reason=report["reason"], source="page",
                        object_id=report["object_id"], display_selection=report["display_selection"])
        except SurfaceFullscreenError as exc:
            self._emit("fullscreen.report_refused", f"rapport {report['state']} refusé depuis {self._state}",
                       level="warning", data={"code": exc.code, "state": self._state, "reported": report["state"]})
            raise
        return self.snapshot()

    # ------------------------------------------------------------ outils

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except OSError:
            pass  # intentional: a full disk must not turn a transition the page applied into a failure
