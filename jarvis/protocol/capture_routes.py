"""Routes HTTP de Core : Contexts, captures, Artifacts, transcriptions, activité (handoff session-context-recording, Slice 09).

Servies par `LocalProtocolServer` (jeton porteur exigé par son middleware) ;
logique dans `jarvis/core/capture_api.py` (`CaptureApi`). Le Control Center les
relaie sous `/api/...` (`jarvis/runtime/capture_relay.py`) pour l'interface et
pour le serveur MCP `jarvis-capture` du cerveau. Contrat : `docs/capture.md` ›
*HTTP API*.

| Méthode | Route | Effet |
| --- | --- | --- |
| GET | `/v1/contexts` | Contexts de la Session ouverte, l'actif |
| POST | `/v1/contexts` | nouveau Context actif `{title?, handoff_summary?, source_context_ids?, origin?}` (201) |
| GET | `/v1/contexts/current` | Context actif |
| POST | `/v1/contexts/{context_id}/activate` | réactiver un Context dormant `{origin?}` |
| GET | `/v1/captures/status[?recent=N]` | captures ouvertes, arrêts bloqués, dernières finies, transcription, enrichissement |
| POST | `/v1/captures/start` | `{channel: audio\\|screen, options?: {source?, device?}, origin?}` (201) |
| POST | `/v1/captures/screenshot` | `{options?, origin?}` (201) |
| GET | `/v1/captures/{capture_id}` | une capture et sa transcription |
| POST | `/v1/captures/{capture_id}/stop` | arrêt idempotent |
| POST | `/v1/captures/{capture_id}/transcription/retry` | relance |
| POST | `/v1/captures/{capture_id}/transcription/abandon` | abandon explicite `{reason?}` |
| GET | `/v1/captures/{capture_id}/transcript` | segments bornés (`after_seq`[+`char_offset`], `from_ms`, `max_chars`) |
| GET | `/v1/artifacts` | requête bornée (`kind`, `state`, `jarvis_session_id`, `context_id`, `since`, `until`, `cursor`, `limit` ≤ 50) |
| GET | `/v1/artifacts/{artifact_id}` | métadonnées (`text_chars` ≤ 16 000) |
| DELETE | `/v1/artifacts/{artifact_id}[?cascade=true&origin=]` | suppression explicite |
| GET | `/v1/artifacts/{artifact_id}/relations[?direction=]` | provenance |
| GET | `/v1/artifacts/{artifact_id}/transcript` | comme celle d'une capture |
| GET | `/v1/artifacts/{artifact_id}/payload` | octets (plages HTTP, ≤ 8 Mio par réponse) |
| GET | `/v1/activity` | queue du ledger de la Session ouverte (`after_seq`, `limit` ≤ 200, `context_id`, `kind`) |

Refus : `{"error": {"code", "message"[, "capture_id"]}}`, code stable du
domaine et son statut ; message sans chemin absolu (`redact_paths`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from aiohttp import web

from jarvis.core.capture_api import (
    DEFAULT_ACTIVITY_LIMIT, DEFAULT_QUERY_LIMIT, DEFAULT_RECENT_CAPTURES, DEFAULT_TEXT_CHARS,
    DEFAULT_TRANSCRIPT_CHARS, MAX_ACTIVITY_LIMIT, MAX_HANDOFF_SUMMARY_CHARS_API, MAX_QUERY_LIMIT,
    MAX_RECENT_CAPTURES, MAX_TEXT_CHARS, MAX_TRANSCRIPT_CHARS, ORIGINS, EvidenceApiError, redact_paths,
)
from jarvis.core.capture_service import CaptureOptions
from jarvis.domain.artifacts import (
    MAX_ARTIFACT_TEXT_CHARS, ArtifactError, ArtifactKind, ArtifactState, check_artifact_id,
)
from jarvis.domain.capture import CaptureChannel, CaptureError, check_capture_id
from jarvis.domain.session_activity import ActivityError, ActivityKind
from jarvis.domain.session_context import SessionContextError
from jarvis.domain.workspace_board import BoardError
from jarvis.ports.artifacts import ArtifactPayloadError
from jarvis.ports.workspace_board import BoardStoreError
from jarvis.protocol.strict_json import loads_strict_json

#: Plus grand corps accepté : un relais de Context (8 000 caractères) et sa marge.
MAX_CAPTURE_BODY_BYTES = 64 * 1024
MAX_SOURCE_CONTEXTS_API = 16
_CODED = (SessionContextError, ArtifactError, CaptureError, ActivityError, BoardError)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def error_response(status: int, code: str, message: str, **extra: Any) -> web.Response:
    body = {"code": code, "message": redact_paths(message)[:500], **{k: v for k, v in extra.items() if v is not None}}
    return web.json_response({"error": body}, status=status)


def _guarded(handler: Handler) -> Handler:
    """Chaque refus devient l'enveloppe codée, sans chemin absolu ; jamais un 500 muet."""

    async def run(request: web.Request) -> web.StreamResponse:
        try:
            return await handler(request)
        except asyncio.CancelledError:
            raise
        except EvidenceApiError as exc:
            response = error_response(exc.status, exc.code, str(exc))
            response.headers.update(exc.headers)
            return response
        except _CODED as exc:
            code = getattr(exc.code, "value", exc.code)
            return error_response(exc.status, str(code), str(exc), capture_id=getattr(exc, "capture_id", None))
        except BoardStoreError as exc:
            # Base refusée ou ligne illisible (Artifacts, Contexts, captures) : surfacée, jamais réparée.
            return error_response(500, str(getattr(exc, "code", "store_failed")), str(exc))
        except ArtifactPayloadError as exc:
            return error_response(500, "artifact_payload_failed", f"payload store refused ({exc.code})")
        except ValueError as exc:
            return error_response(400, "invalid_request", str(exc))

    return run


def _only(request: web.Request, allowed: set[str]) -> None:
    unknown = set(request.query) - allowed
    if unknown:
        raise ValueError(f"unexpected query parameters: {', '.join(sorted(unknown)[:6])}")


def _int(request: web.Request, name: str, default: int | None, low: int, high: int) -> int | None:
    raw = request.query.get(name)
    if raw is None:
        return default
    if not (raw.isascii() and raw.isdigit() and len(raw) <= 12) or not low <= int(raw) <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return int(raw)


def _flag(request: web.Request, name: str) -> bool:
    raw = request.query.get(name, "false")
    if raw not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return raw == "true"


def _datetime(request: web.Request, name: str) -> datetime | None:
    raw = request.query.get(name)
    if raw is None:
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"{name} must be an ISO-8601 date-time with its offset") from None
    if value.tzinfo is None:
        raise ValueError(f"{name} must carry a UTC offset")
    return value


def _enums(request: web.Request, name: str, enum: type) -> tuple[Any, ...]:
    values: list[str] = []
    for raw in request.query.getall(name, []):
        values.extend(part.strip() for part in raw.split(",") if part.strip())
    try:
        return tuple(dict.fromkeys(enum(value) for value in values))
    except ValueError:
        allowed = ", ".join(item.value for item in enum)
        raise ValueError(f"{name} must be among: {allowed}") from None


async def _body(request: web.Request, allowed: set[str], *, required: set[str] = frozenset()) -> dict[str, Any]:
    raw = await request.content.read(MAX_CAPTURE_BODY_BYTES + 1)
    if len(raw) > MAX_CAPTURE_BODY_BYTES:
        raise ValueError(f"request body exceeds {MAX_CAPTURE_BODY_BYTES} bytes")
    body = loads_strict_json(raw, invalid_message="body must be JSON") if raw.strip() else {}
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    unknown = set(body) - allowed
    if unknown:
        raise ValueError(f"unexpected fields: {', '.join(sorted(unknown)[:6])}")
    missing = required - set(body)
    if missing:
        raise ValueError(f"missing fields: {', '.join(sorted(missing))}")
    return body


def _text(body: dict[str, Any], name: str, limit: int) -> str | None:
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{name} must be text of at most {limit} characters")
    return value.strip() or None


def _origin(value: object) -> str:
    origin = "user" if value is None else value
    if origin not in ORIGINS:
        raise ValueError(f"origin must be one of {sorted(ORIGINS)}")
    return str(origin)


def _options(body: dict[str, Any], origin: str) -> CaptureOptions:
    raw = body.get("options") or {}
    if not isinstance(raw, dict) or set(raw) - {"source", "device"}:
        raise ValueError("options must be an object with at most source and device")
    for key in ("source", "device"):
        if raw.get(key) is not None and not isinstance(raw[key], str):
            raise ValueError(f"options.{key} must be a string")
    return CaptureOptions(source=raw.get("source"), device=raw.get("device") or "default", data={"origin": origin})


class CaptureProtocolRoutes:
    """Les routes ci-dessus sur un `JarvisCoreApplication` (`core.capture_api`). Voir l'en-tête."""

    def __init__(self, core: Any) -> None:
        self._core = core

    @property
    def _api(self) -> Any:
        return self._core.capture_api

    def routes(self) -> list[web.RouteDef]:
        g = _guarded
        return [
            web.get("/v1/contexts", g(self.contexts)),
            web.post("/v1/contexts", g(self.create_context)),
            web.get("/v1/contexts/current", g(self.current_context)),
            web.post("/v1/contexts/{context_id}/activate", g(self.activate_context)),
            # `status`, `start`, `screenshot` avant `{capture_id}` : aiohttp apparie dans l'ordre.
            web.get("/v1/captures/status", g(self.status)),
            web.post("/v1/captures/start", g(self.start)),
            web.post("/v1/captures/screenshot", g(self.screenshot)),
            web.get("/v1/captures/{capture_id}", g(self.capture)),
            web.post("/v1/captures/{capture_id}/stop", g(self.stop)),
            web.post("/v1/captures/{capture_id}/transcription/retry", g(self.retry)),
            web.post("/v1/captures/{capture_id}/transcription/abandon", g(self.abandon)),
            web.get("/v1/captures/{capture_id}/transcript", g(self.capture_transcript)),
            web.get("/v1/artifacts", g(self.artifacts)),
            web.get("/v1/artifacts/{artifact_id}", g(self.artifact)),
            web.delete("/v1/artifacts/{artifact_id}", g(self.delete_artifact)),
            web.get("/v1/artifacts/{artifact_id}/relations", g(self.relations)),
            web.get("/v1/artifacts/{artifact_id}/transcript", g(self.artifact_transcript)),
            web.get("/v1/artifacts/{artifact_id}/payload", g(self.payload)),
            web.get("/v1/activity", g(self.activity)),
        ]

    def _ready(self) -> None:
        if not self._core.health.ready or not self._core.sessions.started:
            raise EvidenceApiError(503, "core_unavailable", "core is not ready")

    # ------------------------------------------------------------ Contexts

    async def contexts(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        return web.json_response(await self._api.contexts())

    async def current_context(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        return web.json_response(await self._api.current_context())

    async def create_context(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        body = await _body(request, {"title", "handoff_summary", "source_context_ids", "origin"})
        sources = body.get("source_context_ids") or []
        if (not isinstance(sources, list) or len(sources) > MAX_SOURCE_CONTEXTS_API
                or not all(isinstance(item, str) for item in sources)):
            raise ValueError(f"source_context_ids must be a list of at most {MAX_SOURCE_CONTEXTS_API} context ids")
        title = body.get("title")
        if title is not None and not isinstance(title, str):
            raise ValueError("title must be a string")
        payload = await self._api.create_context(
            title=title, handoff_summary=_text(body, "handoff_summary", MAX_HANDOFF_SUMMARY_CHARS_API),
            source_context_ids=tuple(sources), origin=_origin(body.get("origin")))
        return web.json_response(payload, status=201)

    async def activate_context(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        body = await _body(request, {"origin"})
        payload = await self._api.activate_context(request.match_info["context_id"], origin=_origin(body.get("origin")))
        return web.json_response(payload)

    # ------------------------------------------------------------ captures

    async def status(self, request: web.Request) -> web.Response:
        _only(request, {"recent"})
        self._ready()
        recent = _int(request, "recent", DEFAULT_RECENT_CAPTURES, 0, MAX_RECENT_CAPTURES)
        return web.json_response(await self._api.status(recent=recent))

    async def start(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        body = await _body(request, {"channel", "options", "origin"}, required={"channel"})
        channel = body["channel"]
        if channel not in {item.value for item in CaptureChannel}:
            raise ValueError(f"channel must be one of {sorted(item.value for item in CaptureChannel)}")
        options = _options(body, _origin(body.get("origin")))
        return web.json_response(await self._api.start(channel, options), status=201)

    async def screenshot(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        body = await _body(request, {"options", "origin"})
        return web.json_response(await self._api.screenshot(_options(body, _origin(body.get("origin")))), status=201)

    def _capture_id(self, request: web.Request) -> str:
        capture_id = request.match_info["capture_id"]
        check_capture_id(capture_id)
        return capture_id

    async def capture(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        return web.json_response(await self._api.capture(self._capture_id(request)))

    async def stop(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        await _body(request, {"origin"})
        return web.json_response(await self._api.stop(self._capture_id(request)))

    async def retry(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        await _body(request, set())
        return web.json_response(await self._api.retry_transcription(self._capture_id(request)))

    async def abandon(self, request: web.Request) -> web.Response:
        _only(request, set())
        self._ready()
        body = await _body(request, {"reason"})
        return web.json_response(await self._api.abandon_transcription(
            self._capture_id(request), reason=_text(body, "reason", 200)))

    async def _transcript(self, request: web.Request, projection: Any) -> web.Response:
        after_seq = _int(request, "after_seq", None, 0, 10**9)
        from_ms = _int(request, "from_ms", None, 0, 10**11)
        char_offset = _int(request, "char_offset", 0, 0, MAX_ARTIFACT_TEXT_CHARS)
        if after_seq is not None and from_ms is not None:
            raise ValueError("after_seq and from_ms are exclusive")
        if char_offset and after_seq is None:
            raise ValueError("char_offset needs after_seq (the next_after_seq/next_char_offset cursor)")
        max_chars = _int(request, "max_chars", DEFAULT_TRANSCRIPT_CHARS, 1, MAX_TRANSCRIPT_CHARS)
        return web.json_response(await self._api.read_transcript(projection, after_seq=after_seq, from_ms=from_ms,
                                                                 char_offset=char_offset or 0, max_chars=max_chars))

    async def capture_transcript(self, request: web.Request) -> web.Response:
        _only(request, {"after_seq", "char_offset", "from_ms", "max_chars"})
        self._ready()
        projection = await self._api.transcript_projection_of_capture(self._capture_id(request))
        return await self._transcript(request, projection)

    # ------------------------------------------------------------ Artifacts

    def _artifact_id(self, request: web.Request) -> str:
        artifact_id = request.match_info["artifact_id"]
        check_artifact_id(artifact_id)
        return artifact_id

    async def artifacts(self, request: web.Request) -> web.Response:
        _only(request, {"kind", "state", "jarvis_session_id", "context_id", "since", "until", "cursor", "limit"})
        self._ready()
        payload = await self._api.query_artifacts(
            jarvis_session_id=request.query.get("jarvis_session_id"), context_id=request.query.get("context_id"),
            kinds=_enums(request, "kind", ArtifactKind), states=_enums(request, "state", ArtifactState),
            since=_datetime(request, "since"), until=_datetime(request, "until"),
            cursor=request.query.get("cursor"), limit=_int(request, "limit", DEFAULT_QUERY_LIMIT, 1, MAX_QUERY_LIMIT))
        return web.json_response(payload)

    async def artifact(self, request: web.Request) -> web.Response:
        _only(request, {"text_chars"})
        self._ready()
        text_chars = _int(request, "text_chars", DEFAULT_TEXT_CHARS, 0, MAX_TEXT_CHARS)
        return web.json_response(await self._api.artifact(self._artifact_id(request), text_chars=text_chars))

    async def delete_artifact(self, request: web.Request) -> web.Response:
        _only(request, {"cascade", "origin"})
        self._ready()
        payload = await self._api.delete(self._artifact_id(request), cascade=_flag(request, "cascade"),
                                         origin=_origin(request.query.get("origin")))
        return web.json_response(payload)

    async def relations(self, request: web.Request) -> web.Response:
        _only(request, {"direction"})
        self._ready()
        direction = request.query.get("direction", "both")
        if direction not in {"origins", "dependents", "both"}:
            raise ValueError("direction must be origins, dependents or both")
        return web.json_response(await self._api.relations(self._artifact_id(request), direction))

    async def artifact_transcript(self, request: web.Request) -> web.Response:
        _only(request, {"after_seq", "char_offset", "from_ms", "max_chars"})
        self._ready()
        projection = await self._api.transcript_projection_of_artifact(self._artifact_id(request))
        return await self._transcript(request, projection)

    async def payload(self, request: web.Request) -> web.Response:
        """Octets d'un payload, pour l'interface : jamais rendu au modèle."""

        _only(request, set())
        self._ready()
        chunk = await self._api.payload(self._artifact_id(request), request.headers.get("Range"))
        headers = {
            "Content-Type": chunk.mime_type, "Accept-Ranges": "bytes", "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="{chunk.filename}"',
        }
        if chunk.status == 206:
            headers["Content-Range"] = f"bytes {chunk.start}-{chunk.end}/{chunk.total}"
        return web.Response(body=chunk.data, status=chunk.status, headers=headers)

    async def activity(self, request: web.Request) -> web.Response:
        _only(request, {"after_seq", "limit", "context_id", "kind"})
        self._ready()
        payload = await self._api.activity(
            after_seq=_int(request, "after_seq", 0, 0, 10**15) or 0,
            limit=_int(request, "limit", DEFAULT_ACTIVITY_LIMIT, 1, MAX_ACTIVITY_LIMIT) or DEFAULT_ACTIVITY_LIMIT,
            context_id=request.query.get("context_id"), kinds=_enums(request, "kind", ActivityKind))
        return web.json_response(payload)
