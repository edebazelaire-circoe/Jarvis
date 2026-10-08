"""Courtier et routes de l'explorateur de variantes (handoff jarvis-interactive-presentation-studio, Slice 18).

Frère de `fullscreen_commands.py` (même transport : une commande en vol, remise exclusive à un long-poll, reçu à usage unique,
échéance), en plus simple : la page est seule à savoir si l'explorateur est ouvert, donc le courtier tient seulement la commande en
vol et un **miroir daté** de ce que la page a rapporté (`snapshot()`), pour qu'un agent LISE « l'explorateur est-il ouvert, sur quelle
variante, en plein écran ? » au lieu de le déduire d'une commande passée.

| Control Center | Rôle |
| --- | --- |
| `GET /api/presentation-studio/explorer/commands?wait_s=&page=&visible=` | long-poll de la page : la commande en attente, ou `{"command": null}` |
| `POST /api/presentation-studio/explorer/commands` | demande de l'agent : `{action: "open", presentation_id, variant_id?, fullscreen?, arm_s?}` ou `{action: "close"}` ; rend le reçu de la page |
| `POST /api/presentation-studio/explorer/commands/{command_id}` | reçu de la page (`opened` + `mode`, `refused` + `code`, `closed`) |
| `GET /api/presentation-studio/explorer/state` | le miroir : `closed` / `open` (+ `mode`, ids, numéro) / `unknown` (aucune page visible n'a parlé depuis 60 s) |
| `POST /api/presentation-studio/explorer/state` | rapport de la page : ouverture, sélection, plein écran, fermeture |

Le préfixe `/api/presentation-studio` est gardé (`READ_GUARDED_ROUTES`) : un cadre de prefab (`Origin: null`) ne peut ni ouvrir ni lire.
Le journal ne porte que des identifiants courts, des états, des durées et des codes : jamais un titre ni une raison (texte d'utilisateur).
**Une ouverture ne contourne rien** : l'explorateur reste refusé pendant une lecture (cause rendue en `refused` + `explorer_run_in_progress`),
et le plein écran reste armé quand le navigateur exige un clic.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import secrets
import time
from typing import Any

from aiohttp import web

from jarvis.domain import presentation_studio_explorer as vocab
from jarvis.domain.presentation_studio_explorer import ExplorerCommandError, ExplorerRequest, short_id
from jarvis.protocol import scene_wire
from jarvis.runtime.journal import RuntimeJournal

EXPLORER_ROUTE = "/api/presentation-studio/explorer"
SETTINGS_ERROR_CODE_HEADER = "X-Jarvis-Error-Code"


@dataclass(slots=True)
class _Pending:
    command_id: str
    request: ExplorerRequest
    created: float
    deadline: float
    result: asyncio.Future
    delivered: bool = False
    deliveries: int = 0
    consumed: bool = False


class ExplorerCommandBroker:
    """Une commande en vol à la fois, plus l'état que la page a rapporté."""

    def __init__(self, *, journal: RuntimeJournal | None = None, deadline_s: float = vocab.DELIVERY_DEADLINE_S,
                 clock: Any = None, silence_s: float = vocab.PAGE_SILENCE_S) -> None:
        self.journal = journal
        self.deadline_s = deadline_s
        self.silence_s = silence_s
        self._clock = clock
        self._pending: _Pending | None = None
        self._wake: asyncio.Event | None = None
        self._closed = False
        self._state: dict[str, Any] = {"open": False, "mode": None, "fullscreen": "not_requested", "presentation_id": None,
                                       "variant_id": None, "variant_number": None}
        self._reported_at: float | None = None
        self._page_seen_at: float | None = None
        #: Pages qui ont dit être cachées : une page cachée ne reçoit jamais une commande.
        self._hidden: dict[str, None] = {}

    # ------------------------------------------------------------ temps

    def _now(self) -> float:
        if self._clock is not None:
            return float(self._clock())
        return time.monotonic()

    # ------------------------------------------------------------ cycle de vie

    def close(self) -> None:
        self._closed = True
        pending, self._pending = self._pending, None
        if pending is not None and not pending.result.done():
            pending.result.set_exception(ExplorerCommandError(
                vocab.COMMAND_CANCELLED, "Le Control Center s'arrête : commande de l'explorateur abandonnée.", 503,
                short_id(pending.command_id)))
        self._set_wake()

    # ------------------------------------------------------------ état

    def snapshot(self) -> dict[str, Any]:
        """Le miroir de la page. `unknown` quand aucune page visible n'a donné de nouvelles depuis `silence_s` : jamais un état périmé affirmé."""

        now = self._now()
        silent = self._page_seen_at is None or now - self._page_seen_at > self.silence_s
        if silent and self._state["open"]:
            state = "unknown"
        else:
            state = "open" if self._state["open"] else "closed"
        mode = self._state["mode"] if state == "open" else None
        explanation = vocab.EXPLANATIONS["unknown"] if state == "unknown" else vocab.EXPLANATIONS[mode or "closed"]
        return {
            "state": state, "mode": mode, "fullscreen": self._state["fullscreen"],
            "presentation_id": self._state["presentation_id"], "variant_id": self._state["variant_id"],
            "variant_number": self._state["variant_number"], "explanation": explanation,
            "reported_s_ago": None if self._reported_at is None else round(now - self._reported_at, 1),
        }

    def report(self, report: dict[str, Any]) -> dict[str, Any]:
        """Un rapport de la page (ouverture, sélection, plein écran, fermeture). Idempotent."""

        before = self._state["open"], self._state["mode"], self._state["variant_id"]
        self._state = {key: report[key] for key in self._state}
        self._reported_at = self._now()
        self._page_seen_at = self._reported_at
        after = self._state["open"], self._state["mode"], self._state["variant_id"]
        if before != after:
            self._emit("explorer.state_changed", f"explorateur : {'ouvert' if after[0] else 'fermé'} ({after[1] or '-'})",
                       data={"open": after[0], "mode": after[1], "fullscreen": self._state["fullscreen"],
                             "variant_number": self._state["variant_number"]})
        return self.snapshot()

    # ------------------------------------------------------------ visibilité des pages

    def mark_visibility(self, page: str | None, visible: bool) -> None:
        if not page:
            return
        self._hidden.pop(page, None)
        if visible:
            self._page_seen_at = self._now()
            return
        self._hidden[page] = None
        while len(self._hidden) > 64:
            self._hidden.pop(next(iter(self._hidden)))
        self._emit("explorer.page_hidden", "une page du Control Center est cachée : pas de remise", data={"page": page[:8]})

    # ------------------------------------------------------------ demande de l'agent

    async def request(self, request: ExplorerRequest) -> dict[str, Any]:
        """Remettre la commande à la page et rendre son reçu, au plus `deadline_s`. Lève `ExplorerCommandError` : jamais un succès par défaut."""

        if self._closed:
            raise ExplorerCommandError(vocab.COMMAND_CANCELLED, "Le Control Center s'arrête.", 503)
        if self._pending is not None:
            self._emit("explorer.command_busy", f"commande {request.action} refusée : une autre est en cours", level="warning",
                       data={"code": vocab.COMMAND_BUSY, "command": request.action, "pending": short_id(self._pending.command_id)})
            raise ExplorerCommandError(vocab.COMMAND_BUSY, "Une commande de l'explorateur est déjà en cours : réessaie dans une seconde.", 409)
        loop = asyncio.get_running_loop()
        now = loop.time()
        pending = _Pending(secrets.token_urlsafe(24), request, now, now + self.deadline_s, loop.create_future())
        self._pending = pending
        self._emit("explorer.command_requested", f"commande de l'explorateur demandée : {request.action}",
                   data={"command": request.action, "id": short_id(pending.command_id), "fullscreen": request.fullscreen,
                         "arm_s": request.arm_s, "deadline_ms": round(self.deadline_s * 1000)})
        self._set_wake()
        try:
            receipt = await asyncio.wait_for(asyncio.shield(pending.result), timeout=self.deadline_s)
        except TimeoutError:
            took = pending.deliveries > 0
            code = vocab.COMMAND_EXPIRED if took else vocab.NO_VISIBLE_PAGE
            self._emit("explorer.command_expired",
                       f"commande {request.action} échue : " + ("la page l'a prise et n'a pas répondu" if took else "aucune page visible n'a répondu"),
                       level="warning", data={"code": code, "command": request.action, "id": short_id(pending.command_id),
                                              "deliveries": pending.deliveries, "waited_ms": round((loop.time() - now) * 1000)})
            raise ExplorerCommandError(
                code,
                (f"La page du Control Center a pris la commande mais n'a pas répondu en {self.deadline_s:g} s : l'issue est "
                 "inconnue, demande à l'utilisateur de regarder la fenêtre." if took else
                 f"Aucune page visible du Control Center n'a pris la commande en {self.deadline_s:g} s "
                 "(fenêtre fermée, onglet caché ou page pas chargée)."),
                504, short_id(pending.command_id)) from None
        except asyncio.CancelledError:
            if not pending.result.done():
                self._emit("explorer.command_abandoned", f"commande {request.action} abandonnée par l'appelant", level="warning",
                           data={"code": vocab.COMMAND_CANCELLED, "command": request.action, "id": short_id(pending.command_id)})
            raise
        finally:
            if self._pending is pending:
                self._pending = None
            if not pending.result.done():
                pending.result.cancel()
        duration_ms = round((loop.time() - pending.created) * 1000)
        explanation = vocab.EXPLANATIONS["closed"] if receipt["state"] == "closed" else (
            vocab.EXPLANATIONS[receipt["mode"]] if receipt["state"] == "opened" else
            "L'explorateur n'a pas été ouvert (voir `code` et `reason`). Dis la cause à l'utilisateur, sans prétendre l'inverse.")
        answer = {**receipt, "command": request.action, "id": short_id(pending.command_id), "deliveries": pending.deliveries,
                  "duration_ms": duration_ms, "explanation": explanation}
        self._emit("explorer.command_answered", f"commande {request.action} : la page rapporte {receipt['state']}",
                   level="info" if receipt["state"] != "refused" else "warning",
                   data={"command": request.action, "id": short_id(pending.command_id), "state": receipt["state"],
                         "mode": receipt["mode"], "code": receipt["code"], "duration_ms": duration_ms,
                         "deliveries": pending.deliveries})
        answer["snapshot"] = self.snapshot()
        self._set_wake()
        return answer

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
        """La commande à joindre à une réponse de long-poll, ou `None`. Remise exclusive, une seule fois."""

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
        self._emit("explorer.command_delivered", f"commande {pending.request.action} remise à la page",
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
            vocab.check_command_id(command_id)
        except ExplorerCommandError:
            self._emit("explorer.receipt_refused", "reçu refusé : identifiant hors forme", level="warning",
                       data={"code": vocab.UNKNOWN_COMMAND_ID, "id_chars": len(command_id) if isinstance(command_id, str) else None})
            raise
        pending = self._pending
        if pending is None or pending.command_id != command_id or pending.consumed or pending.result.done():
            self._emit("explorer.receipt_refused", "reçu refusé : commande inconnue ou déjà rendue", level="warning",
                       data={"code": vocab.UNKNOWN_COMMAND_ID, "id": short_id(command_id)})
            raise ExplorerCommandError(
                vocab.UNKNOWN_COMMAND_ID, "Aucune commande en attente avec cet identifiant (inconnue, déjà rendue ou échue).", 404,
                short_id(command_id))
        if asyncio.get_running_loop().time() >= pending.deadline:
            self._emit("explorer.receipt_refused", "reçu refusé : commande échue", level="warning",
                       data={"code": vocab.COMMAND_EXPIRED, "id": short_id(command_id)})
            raise ExplorerCommandError(vocab.COMMAND_EXPIRED, "Commande échue : trop tard.", 410, short_id(command_id))
        pending.consumed = True
        if not pending.result.done():
            pending.result.set_result(receipt)
        return {"command": pending.request.action, "id": command_id}

    def fail(self, command_id: str, error: ExplorerCommandError) -> bool:
        """Solder la commande attendue par un refus nommé de son reçu (reçu mal formé ou trop gros)."""

        pending = self._pending
        if pending is None or pending.command_id != command_id or pending.consumed or pending.result.done():
            return False
        pending.consumed = True
        pending.result.set_exception(error)
        self._emit("explorer.receipt_rejected", f"reçu de {pending.request.action} refusé : {error.code}", level="warning",
                   data={"code": error.code, "id": short_id(command_id)})
        return True

    # ------------------------------------------------------------ outils

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except OSError:
            pass  # intentional: a full disk must not turn a transition the page applied into a failure


class PresentationStudioExplorerRoutes:
    """Les cinq routes du canal. `routes()` est branché dans le `ControlCenter` à côté des relais du Studio."""

    def __init__(self, *, journal: RuntimeJournal | None = None, broker: ExplorerCommandBroker | None = None) -> None:
        self.journal = journal
        self.broker = broker or ExplorerCommandBroker(journal=journal)

    def routes(self) -> list[web.RouteDef]:
        return [web.get(EXPLORER_ROUTE + "/commands", self.poll),
                web.post(EXPLORER_ROUTE + "/commands", self.request),
                web.post(EXPLORER_ROUTE + "/commands/{command_id}", self.receipt),
                web.get(EXPLORER_ROUTE + "/state", self.state),
                web.post(EXPLORER_ROUTE + "/state", self.state_report)]

    def close(self) -> None:
        self.broker.close()

    @staticmethod
    def _error(status: int, code: str, message: str, command_id: str | None = None) -> web.Response:
        """Le code dans le corps (ce que la page lit) ET dans l'en-tête (ce que le serveur MCP lit)."""

        extra = {"id": command_id} if command_id else {}
        return web.json_response(scene_wire.error_body(code, message, **extra), status=status,
                                 headers={SETTINGS_ERROR_CODE_HEADER: code})

    async def poll(self, request: web.Request) -> web.Response:
        """Long-poll de la page : la commande en attente, ou `{"command": null}`. Paramètres : `wait_s`, `page`, `visible`."""

        unknown = set(request.query) - {"wait_s", "page", "visible"}
        if unknown:
            return self._error(400, vocab.BAD_REQUEST, "paramètre inconnu : " + ", ".join(sorted(unknown)))
        try:
            wait_s = float(request.query.get("wait_s", "0"))
        except ValueError:
            return self._error(400, vocab.BAD_REQUEST, "wait_s doit être un nombre")
        if not 0.0 <= wait_s <= vocab.MAX_POLL_WAIT_S:
            return self._error(400, vocab.BAD_REQUEST, f"wait_s doit être entre 0 et {vocab.MAX_POLL_WAIT_S:g}")
        page = request.query.get("page")
        if page is not None:
            try:
                vocab.check_page_id(page)
            except ExplorerCommandError as exc:
                return self._error(exc.status, exc.code, str(exc))
        visible = request.query.get("visible", "1")
        if visible not in ("0", "1"):
            return self._error(400, vocab.BAD_REQUEST, "visible doit être 0 ou 1")
        broker = self.broker
        broker.mark_visibility(page, visible == "1")
        if visible == "0":
            return web.json_response({"command": None})
        deadline = time.monotonic() + wait_s
        while True:
            wake = broker.wake_event()
            transport = request.transport
            if transport is None or transport.is_closing():
                return web.json_response({"command": None})   # le client est parti : une remise ici serait perdue
            command = broker.deliver(page)
            if command is not None:
                return web.json_response({"command": command})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                broker.mark_visibility(page, True)   # un poll qui se termine prouve la page vivante
                return web.json_response({"command": None})
            try:
                await asyncio.wait_for(wake.wait(), timeout=remaining)
            except TimeoutError:
                continue

    async def request(self, request: web.Request) -> web.Response:
        """Demande de l'agent. 200 avec le reçu de la page (`opened` + `mode`, `refused` + `code`, `closed`) ; 504 sans page visible."""

        if request.query:
            return self._error(400, vocab.BAD_REQUEST, "unexpected query")
        try:
            raw = await scene_wire.read_bounded_body(request, vocab.MAX_REQUEST_BYTES)
        except scene_wire.SceneBodyTooLarge:
            return self._error(413, vocab.BAD_REQUEST, f"la demande dépasse {vocab.MAX_REQUEST_BYTES} octets")
        try:
            wanted = vocab.parse_request(json.loads(raw.decode("utf-8")) if raw else None)
        except RecursionError:
            return self._error(400, vocab.BAD_REQUEST, "demande illisible : imbrication excessive")
        except (UnicodeDecodeError, ValueError) as exc:
            return self._error(getattr(exc, "status", 400), getattr(exc, "code", vocab.BAD_REQUEST), str(exc))
        try:
            answer = await self.broker.request(wanted)
        except ExplorerCommandError as exc:
            return self._error(exc.status, exc.code, str(exc), exc.command_id)
        return web.json_response(answer)

    async def receipt(self, request: web.Request) -> web.Response:
        """Reçu de remise : ce que la page a **constaté** en prenant la commande."""

        if request.query:
            return self._error(400, vocab.BAD_RECEIPT, "unexpected query")
        command_id = request.match_info["command_id"]
        expected = self.broker.expected(command_id)
        try:
            raw = await scene_wire.read_bounded_body(request, vocab.MAX_RECEIPT_BYTES)
        except scene_wire.SceneBodyTooLarge:
            self._rejected(command_id, expected, vocab.RECEIPT_TOO_LARGE, f"le reçu dépasse {vocab.MAX_RECEIPT_BYTES} octets")
            return self._error(413, vocab.BAD_RECEIPT, f"le reçu dépasse {vocab.MAX_RECEIPT_BYTES} octets")
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
            receipt = vocab.parse_receipt(expected or "open", body)
            return web.json_response(self.broker.complete(command_id, receipt))
        except ExplorerCommandError as exc:
            if exc.code == vocab.BAD_RECEIPT:
                self._rejected(command_id, expected, vocab.RECEIPT_INVALID, str(exc))
            return self._error(exc.status, exc.code, str(exc), exc.command_id)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            self._rejected(command_id, expected, vocab.RECEIPT_INVALID, f"reçu illisible : {type(exc).__name__}")
            return self._error(400, vocab.BAD_RECEIPT, f"reçu illisible : {type(exc).__name__}")

    def _rejected(self, command_id: str, expected: str | None, code: str, detail: str) -> None:
        """Le reçu attendu est refusé : l'agent l'apprend tout de suite, nommé, au lieu d'attendre l'échéance."""

        if expected is None:
            return
        self.broker.fail(command_id, ExplorerCommandError(
            code,
            f"La page a répondu à {expected}, mais son reçu a été refusé ({detail[:160]}). Elle a peut-être agi : n'annonce ni "
            "succès ni échec, relis l'état (GET /api/presentation-studio/explorer/state) avant toute autre chose.",
            502, command_id[:8]))

    async def state(self, request: web.Request) -> web.Response:
        """L'état de l'explorateur tel que la page l'a rapporté (jamais tel qu'il a été demandé)."""

        if request.query:
            return self._error(400, vocab.BAD_REQUEST, "unexpected query")
        return web.json_response(self.broker.snapshot())

    async def state_report(self, request: web.Request) -> web.Response:
        """Transition constatée par la page : ouverture, changement de variante, plein écran, fermeture."""

        if request.query:
            return self._error(400, vocab.BAD_RECEIPT, "unexpected query")
        try:
            raw = await scene_wire.read_bounded_body(request, vocab.MAX_RECEIPT_BYTES)
        except scene_wire.SceneBodyTooLarge:
            return self._error(413, vocab.BAD_RECEIPT, f"le rapport dépasse {vocab.MAX_RECEIPT_BYTES} octets")
        try:
            report = vocab.parse_state_report(json.loads(raw.decode("utf-8")) if raw else None)
            return web.json_response(self.broker.report(report))
        except ExplorerCommandError as exc:
            return self._error(exc.status, exc.code, str(exc), exc.command_id)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            return self._error(400, vocab.BAD_RECEIPT, f"rapport illisible : {type(exc).__name__}")
