"""Canal agent -> interface : ouvrir une entrée du Dossier à l'écran (wheel-dossier-refactor, Slice 05).

Même transport que l'explorateur de Variantes (`presentation_studio_explorer_commands.py`) et le plein écran
(`fullscreen_commands.py`) : **une** commande en vol, remise exclusive à un long-poll de la page, reçu à usage
unique, échéance. Plus simple qu'eux : aucun miroir d'état (le Dossier ne s'arme pas, ne se met pas en plein
écran par le navigateur) ; la seule vérité rendue à l'agent est le **reçu** de la page.

| Control Center | Rôle |
| --- | --- |
| `GET /api/dossier/navigation/commands?wait_s=&page=&visible=` | relevé de la page : la commande en attente, ou `{"command": null}` (la page envoie `wait_s=0` quand `/api/status.dossier_navigation.pending` le dit, Slice 08) |
| `POST /api/dossier/navigation/commands` | demande de l'agent : `{board_id, entry_id}` ; rend le reçu de la page |
| `POST /api/dossier/navigation/commands/{command_id}` | reçu de la page : `{state: opened}` ou `{state: refused, code, reason?}` |

Le consommateur (la page) vient avec la Slice 07 ; d'ici là une demande échoue honnêtement en
`no_visible_page` (504) à l'échéance : jamais un succès par défaut. Le préfixe `/api/dossier` est gardé
(`READ_GUARDED_ROUTES`) et un reçu exige le jeton remis avec la page (`__JARVIS_DOSSIER_PAGE_TOKEN__`).
L'existence de l'entrée est vérifiée **avant** par l'appelant (`GET /api/workspace/boards/{id}/dossier/entry`,
c'est ce que fait l'outil MCP `dossier_view`). Journal `dossier.navigation.*` : identifiants courts, états,
durées et codes, jamais un titre. Contrat : `docs/dossier.md` › *Agent -> UI navigation*.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
import secrets
import time
from typing import Any

from aiohttp import web

from jarvis.domain.dossier import DossierEntryRef, DossierError
from jarvis.protocol import scene_wire
from jarvis.runtime.journal import RuntimeJournal

NAVIGATION_ROUTE = "/api/dossier/navigation"
GUARDED_PREFIXES = ("/api/dossier",)
PAGE_TOKEN_HEADER = "X-Jarvis-Page-Token"
PAGE_TOKEN_MARKER = "__JARVIS_DOSSIER_PAGE_TOKEN__"
ERROR_CODE_HEADER = "X-Jarvis-Error-Code"
#: Ouvrir le Dossier sur une entrée est immédiat côté page : 5 s couvrent un onglet lent.
DELIVERY_DEADLINE_S = 5.0
MAX_POLL_WAIT_S = 25.0
MAX_REQUEST_BYTES = 2048
MAX_RECEIPT_BYTES = 2048
MAX_REASON_CHARS = 200
OPEN_ENTRY = "open_entry"

BAD_REQUEST = "bad_request"
BAD_RECEIPT = "bad_receipt"
BAD_PAGE_TOKEN = "bad_page_token"
COMMAND_BUSY = "command_busy"
COMMAND_EXPIRED = "command_expired"
COMMAND_CANCELLED = "command_cancelled"
NO_VISIBLE_PAGE = "no_visible_page"
UNKNOWN_COMMAND_ID = "unknown_command_id"

_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_PAGE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_COMMAND_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")
_BOARD_ID = re.compile(r"(default|board_[A-Za-z0-9_-]{1,120})")

#: Phrase vouvoyée rendue à l'agent avec le reçu.
EXPLANATIONS = {
    "opened": "Le Dossier est ouvert sur cette entrée, à l'écran.",
    "refused": "La page n'a pas ouvert l'entrée (voir code et reason) : dites-en la cause, sans prétendre l'inverse.",
}


class NavigationError(Exception):
    def __init__(self, code: str, message: str, status: int, command_id: str | None = None) -> None:
        super().__init__(message)
        self.code, self.status, self.command_id = code, status, command_id


def short_id(command_id: str) -> str:
    return command_id[:8]


@dataclass(frozen=True, slots=True)
class OpenRequest:
    board_id: str
    entry_id: str

    def to_wire(self) -> dict[str, Any]:
        return {"action": OPEN_ENTRY, "board_id": self.board_id, "entry_id": self.entry_id}


def parse_request(body: object) -> OpenRequest:
    if not isinstance(body, dict) or set(body) != {"board_id", "entry_id"}:
        raise NavigationError(BAD_REQUEST, "la demande est {board_id, entry_id}, rien d'autre", 400)
    board_id = body["board_id"]
    if not isinstance(board_id, str) or not _BOARD_ID.fullmatch(board_id):
        raise NavigationError(BAD_REQUEST, "board_id : identifiant de Board attendu", 400)
    try:
        ref = DossierEntryRef.parse(body["entry_id"])
    except DossierError as exc:
        raise NavigationError(exc.code.value, str(exc), 400) from None
    return OpenRequest(board_id, ref.entry_id)


def parse_receipt(body: object) -> dict[str, Any]:
    if not isinstance(body, dict) or not set(body) <= {"state", "code", "reason"}:
        raise NavigationError(BAD_RECEIPT, "le reçu est {state, code?, reason?}", 400)
    state = body.get("state")
    if state == "opened":
        if set(body) != {"state"}:
            raise NavigationError(BAD_RECEIPT, "un reçu opened ne porte rien d'autre", 400)
        return {"state": "opened", "code": None, "reason": None}
    if state != "refused":
        raise NavigationError(BAD_RECEIPT, "state : opened ou refused", 400)
    code, reason = body.get("code"), body.get("reason")
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise NavigationError(BAD_RECEIPT, "un refus porte un code (minuscules, chiffres, _)", 400)
    if reason is not None and (not isinstance(reason, str) or len(reason) > MAX_REASON_CHARS
                               or not reason.isprintable()):
        raise NavigationError(BAD_RECEIPT, f"reason : une ligne de {MAX_REASON_CHARS} caractères au plus", 400)
    return {"state": "refused", "code": code, "reason": reason}


@dataclass(slots=True)
class _Pending:
    command_id: str
    request: OpenRequest
    created: float
    deadline: float
    result: asyncio.Future
    delivered: bool = False
    deliveries: int = 0
    consumed: bool = False


class DossierNavigationBroker:
    """Une commande en vol à la fois ; la réponse de l'agent est le reçu de la page, ou un refus nommé."""

    def __init__(self, *, journal: RuntimeJournal | None = None, deadline_s: float = DELIVERY_DEADLINE_S) -> None:
        self.journal = journal
        self.deadline_s = deadline_s
        self._pending: _Pending | None = None
        self._wake: asyncio.Event | None = None
        self._closed = False
        self._hidden: dict[str, None] = {}
        #: Remis AVEC la page servie : sans lui, aucun reçu (un processus local qui n'a pas lu la page ne la mime pas).
        self.page_token = secrets.token_urlsafe(24)

    def check_page_token(self, presented: str | None) -> bool:
        return isinstance(presented, str) and secrets.compare_digest(presented, self.page_token)

    def close(self) -> None:
        self._closed = True
        pending, self._pending = self._pending, None
        if pending is not None and not pending.result.done():
            pending.result.set_exception(NavigationError(
                COMMAND_CANCELLED, "Le Control Center s'arrête : l'ouverture du Dossier est abandonnée.", 503,
                short_id(pending.command_id)))
        self._set_wake()

    def mark_visibility(self, page: str | None, visible: bool) -> None:
        if not page:
            return
        self._hidden.pop(page, None)
        if not visible:
            self._hidden[page] = None
            while len(self._hidden) > 64:
                self._hidden.pop(next(iter(self._hidden)))

    async def request(self, request: OpenRequest) -> dict[str, Any]:
        """Remettre la commande à une page visible et rendre son reçu, au plus `deadline_s`."""

        if self._closed:
            raise NavigationError(COMMAND_CANCELLED, "Le Control Center s'arrête.", 503)
        if self._pending is not None:
            self._emit("dossier.navigation.busy", "ouverture refusée : une autre est en cours", level="warning",
                       data={"code": COMMAND_BUSY, "pending": short_id(self._pending.command_id)})
            raise NavigationError(COMMAND_BUSY, "Une ouverture du Dossier est déjà en cours : réessayez dans une "
                                  "seconde.", 409)
        loop = asyncio.get_running_loop()
        now = loop.time()
        pending = _Pending(secrets.token_urlsafe(24), request, now, now + self.deadline_s, loop.create_future())
        self._pending = pending
        self._emit("dossier.navigation.requested", "ouverture d'une entrée du Dossier demandée",
                   data={"id": short_id(pending.command_id), "source": request.entry_id.split(":", 1)[0],
                         "deadline_ms": round(self.deadline_s * 1000)})
        self._set_wake()
        try:
            receipt = await asyncio.wait_for(asyncio.shield(pending.result), timeout=self.deadline_s)
        except TimeoutError:
            took = pending.deliveries > 0
            code = COMMAND_EXPIRED if took else NO_VISIBLE_PAGE
            self._emit("dossier.navigation.expired", "ouverture du Dossier échue", level="warning",
                       data={"code": code, "id": short_id(pending.command_id), "deliveries": pending.deliveries,
                             "waited_ms": round((loop.time() - now) * 1000)})
            raise NavigationError(
                code,
                ("La page du Control Center a pris la demande sans répondre à temps : l'issue est inconnue, "
                 "demandez à l'utilisateur de regarder l'écran." if took else
                 f"Aucune page visible du Control Center n'a pris la demande en {self.deadline_s:g} s (fenêtre "
                 "fermée, onglet caché, ou page sans Dossier)."),
                504, short_id(pending.command_id)) from None
        except asyncio.CancelledError:
            self._emit("dossier.navigation.abandoned", "ouverture abandonnée par l'appelant", level="warning",
                       data={"code": COMMAND_CANCELLED, "id": short_id(pending.command_id)})
            raise
        finally:
            if self._pending is pending:
                self._pending = None
            if not pending.result.done():
                pending.result.cancel()
        duration_ms = round((loop.time() - now) * 1000)
        self._emit("dossier.navigation.answered", f"la page rapporte {receipt['state']}",
                   level="info" if receipt["state"] == "opened" else "warning",
                   data={"id": short_id(pending.command_id), "state": receipt["state"], "code": receipt["code"],
                         "duration_ms": duration_ms})
        self._set_wake()
        return {**receipt, "command": OPEN_ENTRY, "board_id": request.board_id, "entry_id": request.entry_id,
                "id": short_id(pending.command_id), "duration_ms": duration_ms,
                "explanation": EXPLANATIONS[receipt["state"]]}

    def status_block(self) -> dict[str, Any]:
        """Bloc `dossier_navigation` de `/api/status` (Slice 08) : une commande attend une page.

        La page ne tient plus de long-poll : au battement de statut à 1 Hz, une page visible qui lit
        `pending: true` relève la commande par un `GET …/commands?wait_s=0` court (remise exclusive : un seul
        onglet l'exécute). Six connexions par origine suffisent ainsi à deux pages visibles."""

        pending = self._pending
        waiting = pending is not None and not pending.delivered and not pending.consumed
        if waiting:
            try:
                waiting = asyncio.get_running_loop().time() < pending.deadline
            except RuntimeError:
                waiting = True
        return {"pending": bool(waiting)}

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
        if pending is None or pending.delivered or pending.consumed or (page is not None and page in self._hidden):
            return None
        now = asyncio.get_running_loop().time()
        if now >= pending.deadline:
            return None
        pending.delivered = True
        pending.deliveries += 1
        remaining = max(0, round((pending.deadline - now) * 1000))
        self._emit("dossier.navigation.delivered", "ouverture remise à la page",
                   data={"id": short_id(pending.command_id), "remaining_ms": remaining})
        return {"id": pending.command_id, "remaining_ms": remaining, **pending.request.to_wire()}

    def complete(self, command_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
        pending = self._pending
        if (not _COMMAND_ID.fullmatch(command_id) or pending is None or pending.command_id != command_id
                or pending.consumed or pending.result.done()):
            self._emit("dossier.navigation.receipt_refused", "reçu refusé : commande inconnue ou déjà rendue",
                       level="warning", data={"code": UNKNOWN_COMMAND_ID, "id": short_id(command_id)})
            raise NavigationError(UNKNOWN_COMMAND_ID, "Aucune ouverture en attente avec cet identifiant (inconnue, "
                                  "déjà rendue ou échue).", 404, short_id(command_id))
        pending.consumed = True
        pending.result.set_result(receipt)
        return {"command": OPEN_ENTRY, "id": command_id}

    def fail(self, command_id: str, detail: str) -> None:
        """Reçu mal formé pour la commande attendue : l'agent l'apprend tout de suite (502), pas à l'échéance."""

        pending = self._pending
        if pending is None or pending.command_id != command_id or pending.consumed or pending.result.done():
            return
        pending.consumed = True
        pending.result.set_exception(NavigationError(
            BAD_RECEIPT, f"La page a répondu, mais son reçu a été refusé ({detail[:160]}). Elle a peut-être ouvert "
            "l'entrée : n'annoncez ni succès ni échec.", 502, short_id(command_id)))
        self._emit("dossier.navigation.receipt_rejected", "reçu de la page refusé", level="warning",
                   data={"code": BAD_RECEIPT, "id": short_id(command_id)})

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except OSError:
            pass  # intentional: a full disk must not turn a receipt the page gave into a failure


class DossierNavigationRoutes:
    """Les trois routes du canal, branchées dans le `ControlCenter`."""

    def __init__(self, *, journal: RuntimeJournal | None = None, broker: DossierNavigationBroker | None = None) -> None:
        self.broker = broker or DossierNavigationBroker(journal=journal)

    def routes(self) -> list[web.RouteDef]:
        return [web.get(NAVIGATION_ROUTE + "/commands", self.poll),
                web.post(NAVIGATION_ROUTE + "/commands", self.request),
                web.post(NAVIGATION_ROUTE + "/commands/{command_id}", self.receipt)]

    def close(self) -> None:
        self.broker.close()

    @staticmethod
    def _error(status: int, code: str, message: str, command_id: str | None = None) -> web.Response:
        extra = {"id": command_id} if command_id else {}
        return web.json_response(scene_wire.error_body(code, message, **extra), status=status,
                                 headers={ERROR_CODE_HEADER: code})

    async def poll(self, request: web.Request) -> web.Response:
        unknown = set(request.query) - {"wait_s", "page", "visible"}
        if unknown:
            return self._error(400, BAD_REQUEST, "paramètre inconnu : " + ", ".join(sorted(unknown)))
        try:
            wait_s = float(request.query.get("wait_s", "0"))
        except ValueError:
            return self._error(400, BAD_REQUEST, "wait_s doit être un nombre")
        if not 0.0 <= wait_s <= MAX_POLL_WAIT_S:
            return self._error(400, BAD_REQUEST, f"wait_s doit être entre 0 et {MAX_POLL_WAIT_S:g}")
        page = request.query.get("page")
        if page is not None and not _PAGE.fullmatch(page):
            return self._error(400, BAD_REQUEST, "page : 1 à 64 lettres, chiffres, _ ou -")
        visible = request.query.get("visible", "1")
        if visible not in ("0", "1"):
            return self._error(400, BAD_REQUEST, "visible doit être 0 ou 1")
        broker = self.broker
        broker.mark_visibility(page, visible == "1")
        if visible == "0":
            return web.json_response({"command": None})
        deadline = time.monotonic() + wait_s
        while True:
            wake = broker.wake_event()
            transport = request.transport
            if transport is None or transport.is_closing():
                return web.json_response({"command": None})  # le client est parti : une remise ici serait perdue
            command = broker.deliver(page)
            if command is not None:
                return web.json_response({"command": command})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return web.json_response({"command": None})
            try:
                await asyncio.wait_for(wake.wait(), timeout=remaining)
            except TimeoutError:
                continue

    async def request(self, request: web.Request) -> web.Response:
        if request.query:
            return self._error(400, BAD_REQUEST, "unexpected query")
        try:
            raw = await scene_wire.read_bounded_body(request, MAX_REQUEST_BYTES)
            wanted = parse_request(json.loads(raw.decode("utf-8")) if raw else None)
            return web.json_response(await self.broker.request(wanted))
        except scene_wire.SceneBodyTooLarge:
            return self._error(413, BAD_REQUEST, f"la demande dépasse {MAX_REQUEST_BYTES} octets")
        except NavigationError as exc:
            return self._error(exc.status, exc.code, str(exc), exc.command_id)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            return self._error(400, BAD_REQUEST, f"demande illisible : {type(exc).__name__}")

    async def receipt(self, request: web.Request) -> web.Response:
        if not self.broker.check_page_token(request.headers.get(PAGE_TOKEN_HEADER)):
            self.broker._emit("dossier.navigation.write_refused", "reçu refusé : jeton de page absent ou faux",  # noqa: SLF001
                              level="warning", data={"code": BAD_PAGE_TOKEN})
            return self._error(403, BAD_PAGE_TOKEN, "ce reçu doit venir de la page du Control Center (jeton de page "
                               "absent ou faux)")
        if request.query:
            return self._error(400, BAD_RECEIPT, "unexpected query")
        command_id = request.match_info["command_id"]
        try:
            raw = await scene_wire.read_bounded_body(request, MAX_RECEIPT_BYTES)
            receipt = parse_receipt(json.loads(raw.decode("utf-8")) if raw else None)
            return web.json_response(self.broker.complete(command_id, receipt))
        except scene_wire.SceneBodyTooLarge:
            return self._error(413, BAD_RECEIPT, f"le reçu dépasse {MAX_RECEIPT_BYTES} octets")
        except NavigationError as exc:
            if exc.code == BAD_RECEIPT:
                self.broker.fail(command_id, str(exc))
            return self._error(exc.status, exc.code, str(exc), exc.command_id)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            self.broker.fail(command_id, f"reçu illisible : {type(exc).__name__}")
            return self._error(400, BAD_RECEIPT, f"reçu illisible : {type(exc).__name__}")
