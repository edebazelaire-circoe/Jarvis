"""Routes Boards et Sessions du Control Center : relais de Core (handoff board-session, Slice 04b).

Core possède les Boards, les Sessions, la bascule et l'autorité de parole
(`docs/boards.md`). Le Control Center n'en garde rien : ces routes relaient
tel quel vers Core, et ce sont elles que l'UI (Slice 06) et le serveur MCP
`jarvis-workspace` (Slice 05, sur `jarvis-console` jusqu'à la Slice 06 board-memory) appellent — jamais
Core directement.

| Control Center | Core |
| --- | --- |
| `GET/POST /api/boards` | `GET/POST /v1/boards` |
| `GET /api/boards/active` | `GET /v1/boards/active` |
| `POST /api/boards/switch` | `POST /v1/boards/switch` |
| `GET/PATCH /api/boards/{board_id}` | `GET/PATCH /v1/boards/{board_id}` |
| `POST /api/boards/{board_id}/archive` | `POST /v1/boards/{board_id}/archive` |
| `GET /api/sessions/current` | `GET /v1/sessions/current` |
| `GET /api/sessions` | `GET /v1/sessions` |
| `POST /api/sessions/new` | `POST /v1/sessions/new` |

**Relais transparent.** Statut et corps JSON de Core rendus tels quels, erreurs
comprises (`{"error": {"code", "message"}}`, codes `BoardErrorCode`). Core
injoignable ou non configuré : 503 `{"error": {"code": "core_unreachable" |
"core_unconfigured", "message"}}`, journalisé. Une requête partie sans réponse
dans son délai (pour une transition, `CORE_TRANSITION_TIMEOUT_S`, plus long que
l'attente de l'hôte par Core) : 504 `core_transition_timeout`, qui dit que
l'issue est **inconnue** (Core peut encore valider), jamais « rien n'a
changé » ; l'appelant relit `GET /api/sessions/current`.

**Demande du cerveau (`origin: "brain"`).** `POST /api/boards/switch` et
`POST /api/sessions/new` acceptent `origin` (`user` par défaut, `brain` pour un
outil MCP appelé pendant un tour). Une demande du cerveau pendant qu'un tour
de l'agent est en vol serait exécutée sous ses pieds : la bascule lui retire
la parole avant même que sa réponse soit dite. Elle est donc **différée**
jusqu'à la fin de ce tour (plus `BRAIN_DEFER_GRACE_S`, le temps que Core
publie la réponse du tour) et la route répond aussitôt 202
`{"ok": true, "status": "scheduled"}`. L'issue différée est journalisée
(`board.request.deferred_applied` / `_failed` / `_expired`). Aucun tour en
vol : exécutée tout de suite, réponse normale. `origin` n'est jamais relayé.

**Demandes en attente** (reprise QA Slice 05, B1) : acceptées, pas encore
envoyées à Core. Le Control Center sert un tour à la fois, donc elles viennent
du tour en vol (ou de celui qui vient de finir, pendant la grâce). Règles :

- une seconde **nouvelle Session** en attente est **fusionnée** avec la
  première (202 `merged: true`) : une seule Session s'ouvre ;
- une **bascule** vers le même Board est fusionnée ; vers un autre Board, elle
  **remplace** la précédente (202 `replaced_board_id`) : la dernière volonté
  du cerveau gagne, une seule bascule part ;
- les demandes partent **dans l'ordre** où elles ont été faites, une à une ;
- `GET /api/boards/pending` les liste (`{"pending": [{action, board_id}]}`) :
  l'outil `board_switch` s'en sert pour ne pas répondre `unchanged` alors
  qu'une bascule est en attente.

Une nouvelle Session différée que Core refuse `session_closed` (une autre a
été ouverte entre-temps, par l'écran par exemple) est **sans objet**, pas une
panne : `board.request.deferred_stale`, niveau info.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from aiohttp import web

from jarvis.protocol.strict_json import loads_strict_json
from jarvis.runtime.core_sessions import CORE_TRANSITION_PATHS
from jarvis.runtime.journal import RuntimeJournal

#: Corps relayés : même borne que Core (`MAX_BOARD_BODY_BYTES`).
MAX_PROXY_BODY_BYTES = 128 * 1024
#: Origines d'une demande de bascule / nouvelle Session.
ORIGINS = frozenset({"user", "brain"})
#: Pause après la fin du tour avant d'exécuter une demande différée : Core
#: reçoit la réponse de l'agent puis publie sa parole ; la bascule attend qu'elle
#: soit partie, sinon la porte de parole la retiendrait.
BRAIN_DEFER_GRACE_S = 1.5
#: Échéance d'une demande différée : au-delà du plus long tour permis
#: (`/api/agent/ask`, 1 800 s), elle est abandonnée et le journal le dit.
BRAIN_DEFER_MAX_S = 1_860.0


@dataclass
class _Deferred:
    """Une demande du cerveau acceptée, pas encore envoyée à Core."""

    action: str
    core_path: str
    body: bytes
    board_id: str | None

    def data(self) -> dict[str, Any]:
        return {"action": self.action, "board_id": self.board_id}


class BoardSessionRoutes:
    """Relais `/api/boards*`, `/api/sessions*` -> Core. Voir l'en-tête du module."""

    def __init__(
        self,
        *,
        transport: Any,
        journal: RuntimeJournal,
        ask_in_flight: Callable[[], bool],
        wait_asks_idle: Callable[[], Awaitable[None]],
        grace_s: float = BRAIN_DEFER_GRACE_S,
        defer_max_s: float = BRAIN_DEFER_MAX_S,
        delegation: Callable[[str], str | None] | None = None,
    ) -> None:
        self._transport = transport
        self._journal = journal
        self._ask_in_flight = ask_in_flight
        self._wait_asks_idle = wait_asks_idle
        self._grace_s = grace_s
        self._defer_max_s = defer_max_s
        #: S8 : `tool -> message de refus` quand le Tool Brain possède l'écran (`DelegationGate.refusal`), sinon `None`.
        self._delegation = delegation
        #: Demandes en attente, dans l'ordre où elles ont été faites.
        self._pending: list[_Deferred] = []
        self._runner: asyncio.Task[None] | None = None

    def routes(self) -> list[web.RouteDef]:
        return [
            web.get("/api/boards", self.relay("/v1/boards")),
            web.post("/api/boards", self.relay("/v1/boards")),
            web.get("/api/boards/active", self.relay("/v1/boards/active")),
            # Avant `{board_id}` : « pending » n'est pas un identifiant de Board.
            web.get("/api/boards/pending", self.pending),
            web.post("/api/boards/switch", self.switch_board),
            web.get("/api/boards/{board_id}", self.relay("/v1/boards/{board_id}")),
            web.patch("/api/boards/{board_id}", self.relay("/v1/boards/{board_id}")),
            web.post("/api/boards/{board_id}/archive", self.relay("/v1/boards/{board_id}/archive")),
            web.get("/api/sessions/current", self.relay("/v1/sessions/current")),
            web.get("/api/sessions", self.relay("/v1/sessions")),
            web.post("/api/sessions/new", self.new_session),
        ]

    async def close(self) -> None:
        """Arrêt du Control Center : les demandes différées sont abandonnées, et c'est dit."""

        runner = self._runner
        if runner is not None and not runner.done():
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    async def pending(self, request: web.Request) -> web.Response:
        """`GET /api/boards/pending` : les demandes du cerveau en attente, dans l'ordre."""

        del request
        return web.json_response({"ok": True, "pending": [item.data() for item in self._pending]})

    # ------------------------------------------------------------ relais

    def relay(self, core_path: str) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(request: web.Request) -> web.Response:
            try:
                body = await self._read_body(request)
            except ValueError as exc:
                return _error(400, "invalid_request", str(exc))
            path = core_path.format(**{key: _segment(value) for key, value in request.match_info.items()})
            return await self._forward(request.method, path, params=dict(request.query) or None, body=body)

        return handler

    async def switch_board(self, request: web.Request) -> web.Response:
        return await self._transition(request, "/v1/boards/switch", action="switch")

    async def new_session(self, request: web.Request) -> web.Response:
        return await self._transition(request, "/v1/sessions/new", action="new_session")

    async def _transition(self, request: web.Request, core_path: str, *, action: str) -> web.Response:
        try:
            raw = await self._read_body(request)
            payload = loads_strict_json(raw, invalid_message=f"{action} body must be JSON") if raw else {}
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        if not isinstance(payload, dict):
            return _error(400, "invalid_request", f"{action} body must be a JSON object")
        origin = payload.pop("origin", "user")
        if origin not in ORIGINS:
            return _error(400, "invalid_request", f"origin must be one of {sorted(ORIGINS)}")
        body = json.dumps(payload).encode("utf-8")
        if origin == "brain" and action == "switch" and self._delegation is not None:
            refused = self._delegation("board_switch")
            if refused is not None:  # le Tool Brain exécute les bascules : une seule voix sur l'écran (contrat §16)
                return _error(409, "ui_delegated", refused)
        if origin == "brain" and self._ask_in_flight():
            board_id = payload.get("board_id") if isinstance(payload.get("board_id"), str) else None
            answer = self._defer(_Deferred(action, core_path, body, board_id))
            return web.json_response({"ok": True, "status": "scheduled", "action": action, **answer}, status=202)
        self._journal.emit("board.request.relayed", "Demande Board/Session relayée à Core",
                           data={"action": action, "origin": origin, "board_id": payload.get("board_id")})
        return await self._forward("POST", core_path, body=body)

    def _defer(self, request: _Deferred) -> dict[str, Any]:
        """Mettre `request` en attente : fusionnée, remplaçante ou nouvelle. Rend ce que le 202 ajoute."""

        earlier = next((item for item in self._pending if item.action == request.action), None)
        if earlier is not None and (request.action != "switch" or earlier.board_id == request.board_id):
            # Même demande, déjà en attente : une seule partira (une seule Session, une seule bascule).
            self._journal.emit("board.request.deferred_merged",
                               "Demande du cerveau identique à une demande en attente : fusionnée",
                               data=request.data())
            return {"merged": True}
        answer: dict[str, Any] = {}
        if earlier is not None:
            # Bascule vers un autre Board : la dernière volonté gagne, à la place de la première.
            self._pending[self._pending.index(earlier)] = request
            self._journal.emit("board.request.deferred_replaced",
                               "Bascule en attente remplacée par une bascule plus récente du cerveau",
                               data={**request.data(), "replaced_board_id": earlier.board_id})
            answer["replaced_board_id"] = earlier.board_id
        else:
            self._pending.append(request)
            self._journal.emit("board.request.deferred",
                               "Demande du cerveau différée jusqu'à la fin de son tour", data=request.data())
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._run_pending(), name="jarvis-board-deferred")
        return answer

    async def _run_pending(self) -> None:
        """Attendre la fin du tour (borné) puis la grâce, puis envoyer les demandes en attente, dans l'ordre."""

        try:
            while self._pending:
                try:
                    await asyncio.wait_for(self._wait_asks_idle(), timeout=self._defer_max_s)
                except asyncio.TimeoutError:
                    for item in self._take_pending():
                        self._journal.emit(
                            "board.request.deferred_expired",
                            f"Demande du cerveau abandonnée : son tour dure plus de {self._defer_max_s:.0f} s",
                            level="warning", data={**item.data(), "code": "board_request_deferred_expired"})
                    return
                await asyncio.sleep(self._grace_s)
                if self._ask_in_flight():
                    continue  # un nouveau tour a commencé pendant la grâce : on attend sa fin aussi
                while self._pending:
                    await self._send_deferred(self._pending.pop(0))
        except asyncio.CancelledError:
            for item in self._take_pending():
                self._journal.emit("board.request.deferred_cancelled",
                                   "Demande du cerveau abandonnée : arrêt du Control Center", level="warning",
                                   data={**item.data(), "code": "board_request_deferred_cancelled"})
            raise

    def _take_pending(self) -> list[_Deferred]:
        taken, self._pending = self._pending, []
        return taken

    async def _send_deferred(self, item: _Deferred) -> None:
        """Relayer une demande en attente ; nul n'attend la réponse, le journal est son témoin."""

        data = item.data()
        refused = self._delegation("board_switch") if item.action == "switch" and self._delegation is not None else None
        if refused is not None:
            # La propriété a pu passer au Tool Brain pendant l'attente : la porte se rejoue au moment de partir (contrat §16.2).
            self._journal.emit("board.request.deferred_delegated",
                               "Bascule différée du cerveau abandonnée : le Tool Brain possède l'écran maintenant",
                               level="warning", data={**data, "code": "ui_delegated", "detail": str(refused)[:200]})
            return
        try:
            status, answer = await self._transport.forward("POST", item.core_path, body=item.body)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: nobody waits for this answer, the journal is its record
            self._journal.emit("board.request.deferred_failed",
                               f"Demande différée non relayée : {type(exc).__name__}: {str(exc)[:200]}",
                               level="error", data={**data, "code": "core_unreachable",
                                                    "exception_type": type(exc).__name__})
            return
        if status >= 400:
            error = answer.get("error") if isinstance(answer, dict) and isinstance(answer.get("error"), dict) else {}
            code = error.get("code") or "http_error"
            if item.action == "new_session" and code == "session_closed":
                # Attendu : la Session visée a déjà été close (nouvelle Session ouverte ailleurs entre-temps).
                self._journal.emit("board.request.deferred_stale",
                                   "Nouvelle Session différée sans objet : une autre Session a déjà été ouverte",
                                   data={**data, "status": status, "code": code})
                return
            self._journal.emit("board.request.deferred_failed",
                               f"Demande différée refusée par Core (HTTP {status}) : {str(error.get('message'))[:200]}",
                               level="error", data={**data, "status": status, "code": code})
            return
        self._journal.emit("board.request.deferred_applied", "Demande différée du cerveau appliquée par Core",
                           data={**data, "status": status})

    async def _forward(self, method: str, core_path: str, *, params: dict[str, str] | None = None,
                       body: bytes | None = None) -> web.Response:
        if self._transport is None:
            return _error(503, "core_unconfigured", "the control center does not know Core")
        try:
            status, payload = await self._transport.forward(method, core_path, params=params, body=body)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as exc:
            if not (method == "POST" and core_path in CORE_TRANSITION_PATHS):
                # Lecture ou écriture simple (délai 10 s du client) : Core ne répond
                # pas, c'est tout. Seule une transition a une issue inconnue à dire
                # (QA 06/07, point 2 : une lecture répondait 504 après 10,6 s).
                self._journal.emit("board.request.core_unreachable",
                                   f"Core n'a pas répondu à {method} {core_path} dans son délai",
                                   level="warning", data={"code": "core_unreachable", "method": method,
                                                          "path": core_path, "exception_type": type(exc).__name__})
                unknown = "" if method == "GET" else "; the outcome of this write is unknown, read it back"
                return _error(503, "core_unreachable", f"Core did not answer {method} {core_path} in time{unknown}")
            # Délai d'une transition partie : Core a peut-être validé (QA 04b, S2).
            self._journal.emit("board.request.core_timeout",
                               f"Core n'a pas répondu à temps pour {method} {core_path} : issue inconnue",
                               level="warning", data={"code": "core_transition_timeout", "method": method,
                                                      "path": core_path, "exception_type": type(exc).__name__})
            return _error(504, "core_transition_timeout",
                          f"Core did not answer {method} {core_path} in time: the outcome is unknown "
                          "(Core may still commit it); read GET /api/sessions/current")
        except Exception as exc:  # noqa: BLE001 - surfaced: 503 with the real cause, and journaled
            self._journal.emit("board.request.core_unreachable",
                               f"Core injoignable pour {method} {core_path} : {type(exc).__name__}: {str(exc)[:200]}",
                               level="warning", data={"code": "core_unreachable", "method": method, "path": core_path,
                                                      "exception_type": type(exc).__name__})
            return _error(503, "core_unreachable", f"Core is unreachable: {type(exc).__name__}: {str(exc)[:200]}")
        if payload is None:
            return _error(status if status >= 400 else 502, "http_error", f"Core answered HTTP {status} without JSON")
        return web.json_response(payload, status=status)

    @staticmethod
    async def _read_body(request: web.Request) -> bytes | None:
        if not request.can_read_body:
            return None
        raw = await request.content.read(MAX_PROXY_BODY_BYTES + 1)
        if len(raw) > MAX_PROXY_BODY_BYTES:
            raise ValueError(f"request body exceeds {MAX_PROXY_BODY_BYTES} bytes")
        return raw or None


def _segment(value: str) -> str:
    return quote(value, safe="")


def _error(status: int, code: str, message: str) -> web.Response:
    return web.json_response({"error": {"code": code, "message": message}}, status=status)
