"""Routes Contexts, captures et Artifacts du Control Center : relais de Core (session-context-recording, Slice 09).

Core possède les Contexts (`SessionManager`), les captures (`CaptureService`),
la transcription et le registre d'Artifacts ; l'API est
`jarvis/protocol/capture_routes.py`. Le Control Center n'en garde **rien** : ces
routes relaient telles quelles, et ce sont elles que l'interface (Slice 10) et
le serveur MCP `jarvis-capture` du cerveau appellent — jamais Core en direct.

| Control Center | Core | Délai |
| --- | --- | --- |
| `GET/POST /api/contexts`, `GET /api/contexts/current`, `POST /api/contexts/{id}/activate` | même chemin sous `/v1` | 10 s |
| `GET /api/captures/status`, `GET /api/captures/{id}`, `GET /api/captures/{id}/transcript` | idem | 10 s |
| `POST /api/captures/start`, `/screenshot`, `/{id}/stop`, `/{id}/transcription/retry\\|abandon` | idem | 45 s |
| `GET /api/artifacts`, `GET/DELETE /api/artifacts/{id}`, `GET …/relations`, `GET …/transcript` | idem | 10 s (DELETE 30 s) |
| `GET /api/artifacts/{id}/payload` | idem, **en octets** (`forward_bytes`, `Range` relayé) | 30 s |
| `GET /api/activity` | `GET /v1/activity` | 10 s |

**Relais transparent.** Requête relayée paire par paire (un paramètre répété,
`kind=screenshot&kind=transcript`, garde toutes ses valeurs) ; chemin : chaque
paramètre de route ré-encodé (`quote`). Statut et corps JSON de Core rendus tels quels, erreurs
comprises (`{"error": {"code", "message"}}`, codes des domaines). Core
injoignable ou non configuré : 503 `core_unreachable` / `core_unconfigured` ;
délai dépassé : 504 `core_timeout` — pour une écriture l'issue est **inconnue**
(relire `GET /api/captures/status`). Le payload binaire est borné par réponse
(`MAX_FORWARDED_PAYLOAD_BYTES`, 8 Mio, la borne de Core) : au-delà, 502
`payload_too_large_for_relay`, rien n'est rendu à moitié.

**Garde.** Ces préfixes sont dans `READ_GUARDED_ROUTES` du Control Center :
transcriptions, captures d'écran et enregistrements sont aussi sensibles en
lecture qu'en écriture (Host de bouclage, Origin de bouclage s'il existe,
jamais `Sec-Fetch-Site: cross-site`).

**Journal.** Chaque écriture relayée : `capture.request.relayed` (action, statut,
code) ; jamais un corps. Une panne de Core : `capture.request.core_unreachable`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from urllib.parse import quote

from aiohttp import web

from jarvis.protocol.strict_json import read_bounded
from jarvis.runtime.journal import RuntimeJournal

CONTEXTS_ROUTE = "/api/contexts"
CAPTURES_ROUTE = "/api/captures"
ARTIFACTS_ROUTE = "/api/artifacts"
ACTIVITY_ROUTE = "/api/activity"
#: Préfixes servis par ce module (gardés en lecture comme en écriture par le Control Center).
GUARDED_PREFIXES = (CONTEXTS_ROUTE, CAPTURES_ROUTE, ARTIFACTS_ROUTE, ACTIVITY_ROUTE)
#: Corps relayés : même borne que Core (`MAX_CAPTURE_BODY_BYTES`).
MAX_PROXY_BODY_BYTES = 64 * 1024
#: Démarrer une source (échéance de Core 15 s), arrêter et finaliser (10 s + réparation), capture d'écran.
WRITE_TIMEOUT_S = 45.0
DELETE_TIMEOUT_S = 30.0
PAYLOAD_TIMEOUT_S = 30.0


def _error(status: int, code: str, message: str) -> web.Response:
    return web.json_response({"error": {"code": code, "message": message}}, status=status)


def _code_of(payload: Any) -> str | None:
    error = payload.get("error") if isinstance(payload, dict) else None
    return error.get("code") if isinstance(error, dict) and isinstance(error.get("code"), str) else None


class CaptureRelayRoutes:
    """Relais `/api/contexts*`, `/api/captures*`, `/api/artifacts*`, `/api/activity` -> Core. Voir l'en-tête."""

    #: Famille des lignes de journal (`<préfixe>.relayed`, `<préfixe>.core_unreachable`) ; une
    #: sous-classe qui relaie une autre surface (`workspace_relay.py`) a la sienne.
    JOURNAL_PREFIX = "capture.request"
    #: Plus grand corps relayé (la borne de Core pour cette surface).
    MAX_BODY_BYTES = MAX_PROXY_BODY_BYTES

    def __init__(self, *, transport: Callable[[], Any], journal: RuntimeJournal) -> None:
        # Lu à chaque requête : le Control Center peut recevoir son transport après coup.
        self._transport = transport
        self._journal = journal

    def routes(self) -> list[web.RouteDef]:
        capture = CAPTURES_ROUTE + "/{capture_id}"
        artifact = ARTIFACTS_ROUTE + "/{artifact_id}"
        w = WRITE_TIMEOUT_S
        return [
            web.get(CONTEXTS_ROUTE, self._relay("contexts", "/v1/contexts")),
            web.post(CONTEXTS_ROUTE, self._relay("context_create", "/v1/contexts")),
            web.get(CONTEXTS_ROUTE + "/current", self._relay("context_current", "/v1/contexts/current")),
            web.post(CONTEXTS_ROUTE + "/{context_id}/activate",
                     self._relay("context_activate", "/v1/contexts/{context_id}/activate")),
            web.get(CAPTURES_ROUTE + "/status", self._relay("capture_status", "/v1/captures/status")),
            web.post(CAPTURES_ROUTE + "/start", self._relay("capture_start", "/v1/captures/start", w)),
            web.post(CAPTURES_ROUTE + "/screenshot", self._relay("screenshot", "/v1/captures/screenshot", w)),
            web.get(capture, self._relay("capture_get", "/v1/captures/{capture_id}")),
            web.post(capture + "/stop", self._relay("capture_stop", "/v1/captures/{capture_id}/stop", w)),
            web.post(capture + "/transcription/retry",
                     self._relay("transcription_retry", "/v1/captures/{capture_id}/transcription/retry", w)),
            web.post(capture + "/transcription/abandon",
                     self._relay("transcription_abandon", "/v1/captures/{capture_id}/transcription/abandon", w)),
            web.get(capture + "/transcript", self._relay("capture_transcript", "/v1/captures/{capture_id}/transcript")),
            web.get(ARTIFACTS_ROUTE, self._relay("artifacts", "/v1/artifacts")),
            web.get(artifact, self._relay("artifact_get", "/v1/artifacts/{artifact_id}")),
            web.delete(artifact, self._relay("artifact_delete", "/v1/artifacts/{artifact_id}", DELETE_TIMEOUT_S)),
            web.get(artifact + "/relations", self._relay("artifact_relations", "/v1/artifacts/{artifact_id}/relations")),
            web.get(artifact + "/transcript",
                    self._relay("artifact_transcript", "/v1/artifacts/{artifact_id}/transcript")),
            web.get(artifact + "/payload", self.payload),
            web.get(ACTIVITY_ROUTE, self._relay("activity", "/v1/activity")),
        ]

    # ------------------------------------------------------------ JSON

    def _relay(self, action: str, core_path: str,
               timeout_s: float | None = None) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(request: web.Request) -> web.Response:
            try:
                body = await self._read_body(request)
            except ValueError as exc:
                return _error(400, "invalid_request", str(exc))
            path = core_path.format(**{key: quote(value, safe="") for key, value in request.match_info.items()})
            status, payload = await self._forward(request.method, path, action=action,
                                                  params=list(request.query.items()) or None, body=body,
                                                  timeout_s=timeout_s)
            if request.method != "GET":
                self._journal.emit(f"{self.JOURNAL_PREFIX}.relayed", f"{action} relayé à Core (HTTP {status})",
                                   level="info" if status < 400 else "warning",
                                   data={"action": action, "status": status, "code": _code_of(payload)})
            if payload is None:
                return _error(status if status >= 400 else 502, "http_error", f"Core answered HTTP {status} without JSON")
            return web.json_response(payload, status=status)

        return handler

    async def _forward(self, method: str, core_path: str, *, action: str, params: Sequence[tuple[str, str]] | None,
                       body: bytes | None, timeout_s: float | None) -> tuple[int, Any]:
        """(statut, JSON) de Core, ou l'enveloppe d'une panne de transport. Ne lève jamais sauf annulation."""

        transport = self._transport()
        if transport is None:
            return 503, {"error": {"code": "core_unconfigured", "message": "the control center does not know Core"}}
        try:
            return await transport.forward(method, core_path, params=params, body=body, timeout_s=timeout_s)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            unknown = "" if method == "GET" else "; the outcome of this write is unknown, read the status back"
            self._unreachable(action, method, core_path, "core_timeout", "TimeoutError")
            return 504, {"error": {"code": "core_timeout",
                                   "message": f"Core did not answer {method} {core_path} in time{unknown}"}}
        except Exception as exc:  # noqa: BLE001 - surfaced: 503 with the real cause, and journaled
            self._unreachable(action, method, core_path, "core_unreachable", type(exc).__name__)
            return 503, {"error": {"code": "core_unreachable",
                                   "message": f"Core is unreachable: {type(exc).__name__}: {str(exc)[:200]}"}}

    def _unreachable(self, action: str, method: str, path: str, code: str, exception_type: str) -> None:
        self._journal.emit(f"{self.JOURNAL_PREFIX}.core_unreachable", f"Core n'a pas répondu à {method} {path} ({code})",
                           level="warning", data={"action": action, "code": code, "method": method, "path": path,
                                                  "exception_type": exception_type})

    async def _read_body(self, request: web.Request) -> bytes | None:
        if not request.can_read_body:
            return None
        return await read_bounded(request.content, self.MAX_BODY_BYTES) or None

    # ------------------------------------------------------------ octets

    async def payload(self, request: web.Request) -> web.Response:
        """`GET /api/artifacts/{id}/payload` : octets de Core, `Range` relayé, borné ; pour l'interface seulement."""

        if request.query:
            return _error(400, "invalid_request", "unexpected query parameters")
        transport = self._transport()
        if transport is None:
            return _error(503, "core_unconfigured", "the control center does not know Core")
        path = f"/v1/artifacts/{quote(request.match_info['artifact_id'], safe='')}/payload"
        try:
            status, headers, data = await transport.forward_bytes(path, range_header=request.headers.get("Range"),
                                                                  timeout_s=PAYLOAD_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            self._unreachable("artifact_payload", "GET", path, "core_timeout", "TimeoutError")
            return _error(504, "core_timeout", "Core did not send the payload in time")
        except ValueError as exc:
            # Réponse plus grosse que la borne : jamais rendue à moitié.
            self._journal.emit("capture.request.payload_refused", "Payload relayé refusé : trop gros",
                               level="warning", data={"code": "payload_too_large_for_relay", "path": path})
            return _error(502, "payload_too_large_for_relay", str(exc)[:200])
        except Exception as exc:  # noqa: BLE001 - surfaced: 503 with the real cause, and journaled
            self._unreachable("artifact_payload", "GET", path, "core_unreachable", type(exc).__name__)
            return _error(503, "core_unreachable", f"Core is unreachable: {type(exc).__name__}: {str(exc)[:200]}")
        return web.Response(body=data, status=status, headers=headers)
