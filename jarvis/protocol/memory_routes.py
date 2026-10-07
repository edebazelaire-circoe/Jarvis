"""Routes HTTP de Core : lecture de la mémoire à long terme (handoff jarvis-memory-intelligence-knowledge, Slice 05).

Servies par `LocalProtocolServer` (jeton porteur exigé par son middleware) ;
logique dans `jarvis/core/memory_service.py` (`MemoryService`, `core.memory.service`).
Toutes les routes sont **en lecture seule** : aucune n'écrit une note, un index
ni un candidat (les écritures arrivent avec les Slices 04 et 05b). Le Control
Center les relaiera sous `/api/memory*` (Slice 10b). Contrat : `docs/memory.md`
› *Core routes*.

| Méthode | Route | Réponse |
| --- | --- | --- |
| GET | `/v1/memory/notes[?scope&retention&level&kind&include_superseded&limit&offset]` | notes (dernière révision, sans corps), la plus récente d'abord |
| GET | `/v1/memory/notes/{memory_id}` | une note avec son corps, ses sources et ses liens |
| GET | `/v1/memory/search?q=[&scope&retention&level&limit]` | recherche lexicale classée (BM25) sur toutes les portées |
| GET | `/v1/memory/status` | état de chaque étage (`store`, `lexical`, `semantic`, `knowledge:*`...) avec code et raison |
| GET | `/v1/memory/recall-explain?q=[&scope&max_items]` | le rappel du cerveau pour `q` : rang par étage, `why`, délais, codes de dégradation |
| GET | `/v1/memory/candidates` | candidats de consolidation ; vide, `available: false`, tant que la Slice 04 n'est pas là |

Les routes `notes`, `search` et `status` servent le propriétaire (le Memory
Center) et ne sont pas réduites par la politique du cerveau ; `recall-explain`
l'est (« qu'aurait reçu le cerveau »). Refus : `{"error": {"code", "message"}}`
— `memory_not_found` 404, `memory_scope_denied` 403, `memory_conflict_revision`
409, `memory_unavailable` 503 (aussi quand Core n'a pas de mémoire),
`invalid_request` 400, `core_unavailable` 503, `memory_failed` 500. Chaque refus
est journalisé (`core.memory.read_failed`) avec son code, jamais avec la requête.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from jarvis.core.capture_api import EvidenceApiError
from jarvis.core.memory_service import MemoryService
from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.memory import (
    DEFAULT_RECALL_TIMEOUT_MS,
    MAX_QUERY_CHARS,
    MAX_RECALL_ITEMS,
    MemoryErrorCode,
    MemoryFilters,
    MemoryKind,
    MemoryLevel,
    MemoryNote,
    MemoryStoreError,
    RecallBudget,
    RetentionClass,
)
from jarvis.protocol.capture_routes import _enums, _flag, _int, _only, error_response

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
PREFIX = "/v1/memory"
#: A note id as the store writes it (`new_memory_id` or a legacy derived id): anything else is a bad request.
_MEMORY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
#: Notes per page of the list route (the store caps a page at 500).
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 100
#: Characters of a body shown in a listing: the full text is `GET /notes/{id}`.
LIST_EXCERPT_CHARS = 200

_STATUS = {
    MemoryErrorCode.NOT_FOUND: 404,
    MemoryErrorCode.SCOPE_DENIED: 403,
    MemoryErrorCode.CONFLICT_REVISION: 409,
    MemoryErrorCode.DEGRADED: 503,
    MemoryErrorCode.UNAVAILABLE: 503,
}


def note_payload(note: MemoryNote, *, body: bool) -> dict[str, Any]:
    """Wire form of a note; `body=False` gives an excerpt (listing)."""

    payload: dict[str, Any] = {
        "id": note.id, "title": note.title, "level": note.level.value, "kind": note.kind.value,
        "retention": note.retention.value, "scope": note.scope, "revision": note.revision,
        "created_at": note.created_at.isoformat(), "updated_at": note.updated_at.isoformat(),
        "valid_from": note.valid_from.isoformat() if note.valid_from else None,
        "valid_to": note.valid_to.isoformat() if note.valid_to else None,
        "confidence": note.confidence, "agent": note.agent, "superseded_by": note.superseded_by,
        "supersedes": list(note.supersedes), "contradicts": list(note.contradicts),
        "sources": [{"type": item.type.value, "ref": item.ref, "at": item.at.isoformat()} for item in note.sources],
    }
    if body:
        payload["body"] = note.body
    else:
        payload["excerpt"] = " ".join(note.body.split())[:LIST_EXCERPT_CHARS]
    return payload


class MemoryProtocolRoutes:
    """Les routes ci-dessus sur un `JarvisCoreApplication` (`core.memory`). Voir l'en-tête."""

    def __init__(self, core: Any) -> None:
        self._core = core

    def routes(self) -> list[web.RouteDef]:
        g = self._guarded
        return [
            web.get(PREFIX + "/notes", g("note_list", self.notes)),
            web.get(PREFIX + "/notes/{memory_id}", g("note_get", self.note)),
            web.get(PREFIX + "/search", g("search", self.search)),
            web.get(PREFIX + "/status", g("status", self.status)),
            web.get(PREFIX + "/recall-explain", g("recall_explain", self.recall_explain)),
            web.get(PREFIX + "/candidates", g("candidates", self.candidates)),
        ]

    def _guarded(self, operation: str, handler: Handler) -> Handler:
        """Chaque refus devient l'enveloppe codée, journalisée, sans la requête ; jamais un 500 muet."""

        async def run(request: web.Request) -> web.StreamResponse:
            try:
                return await handler(request)
            except asyncio.CancelledError:
                raise
            except EvidenceApiError as exc:
                return self._refused(operation, exc, exc.status, exc.code)
            except MemoryStoreError as exc:
                return self._refused(operation, exc, _STATUS.get(exc.code, 500), exc.code.value, message=exc.message)
            except MemorySecurityError as exc:
                # A traversal or link refusal is the caller's bad id, not a Core fault; its text names a path and is never shown.
                return self._refused(operation, exc, 400, "invalid_request", message="invalid memory id or path")
            except ValueError as exc:
                return self._refused(operation, exc, 400, "invalid_request")
            except Exception as exc:  # noqa: BLE001 - surfaced: 500 with its type, and journaled
                return self._refused(operation, exc, 500, "memory_failed")

        return run

    def _refused(self, operation: str, exc: BaseException, status: int, code: str, *, message: str | None = None) -> web.Response:
        diagnostics = getattr(self._core, "_diagnostics", None)
        if diagnostics is not None:
            diagnostics.emit("core.memory.read_failed", f"Mémoire refusée ({operation}) : {code}",
                             level="error" if status >= 500 else "warning",
                             data={"operation": operation, "status": status, "code": code,
                                   "exception_type": type(exc).__name__})
        # A 5xx names no Python class and carries no exception text (paths, internals): the journal row has them.
        shown = message if message is not None else (str(exc) if status < 500 else "memory read failed; see core.memory.read_failed in the journal")
        return error_response(status, code, shown)

    def _service(self) -> MemoryService:
        """The service, once Core is ready; `memory_unavailable` 503 when Core runs without memory or its store was refused."""

        if not self._core.health.ready:
            raise EvidenceApiError(503, "core_unavailable", "core is not ready")
        wiring = self._core.memory
        if wiring.service is None:
            raise EvidenceApiError(503, MemoryErrorCode.UNAVAILABLE.value,
                                   f"memory is not available ({wiring.unavailable or 'unknown'})")
        return wiring.service

    @staticmethod
    def _query(request: web.Request) -> str:
        text = request.query.get("q", "").strip()
        if not text:
            raise ValueError("missing query parameter: q")
        if len(text) > MAX_QUERY_CHARS:
            raise ValueError(f"q must be at most {MAX_QUERY_CHARS} characters")
        return text

    @staticmethod
    def _scopes(request: web.Request) -> tuple[str, ...]:
        values: list[str] = []
        for raw in request.query.getall("scope", []):
            values.extend(part.strip() for part in raw.split(",") if part.strip())
        return tuple(dict.fromkeys(values))

    # ------------------------------------------------------------------ routes
    async def notes(self, request: web.Request) -> web.Response:
        _only(request, {"scope", "retention", "level", "kind", "include_superseded", "limit", "offset"})
        service = self._service()
        filters = MemoryFilters(
            scopes=self._scopes(request), retentions=_enums(request, "retention", RetentionClass),
            levels=_enums(request, "level", MemoryLevel), kinds=_enums(request, "kind", MemoryKind),
            include_superseded=_flag(request, "include_superseded"),
            limit=_int(request, "limit", DEFAULT_LIST_LIMIT, 1, MAX_LIST_LIMIT) or DEFAULT_LIST_LIMIT,
            offset=_int(request, "offset", 0, 0, 10 ** 9) or 0)
        notes = await service.list_notes(filters)
        return web.json_response({"notes": [note_payload(note, body=False) for note in notes],
                                  "limit": filters.limit, "offset": filters.offset, "derived": False})

    async def note(self, request: web.Request) -> web.Response:
        _only(request, set())
        memory_id = request.match_info["memory_id"]
        if not _MEMORY_ID.fullmatch(memory_id):
            raise ValueError("memory_id must be 1 to 64 letters, digits, dots, dashes or underscores")
        service = self._service()
        return web.json_response({"note": note_payload(await service.get_note(memory_id), body=True)})

    async def search(self, request: web.Request) -> web.Response:
        _only(request, {"q", "scope", "retention", "level", "limit"})
        query = self._query(request)
        service = self._service()
        limit = _int(request, "limit", DEFAULT_SEARCH_LIMIT, 1, MAX_SEARCH_LIMIT) or DEFAULT_SEARCH_LIMIT
        filters = MemoryFilters(scopes=self._scopes(request), retentions=_enums(request, "retention", RetentionClass),
                                levels=_enums(request, "level", MemoryLevel))
        hits = await service.search(query, limit, filters)
        return web.json_response({"hits": [
            {"id": hit.memory_id, "title": hit.title, "snippet": hit.snippet, "score": hit.score,
             "level": hit.level.value, "retention": hit.retention.value, "kind": hit.kind.value, "scope": hit.scope,
             "revision": hit.revision, "updated_at": hit.updated_at.isoformat()} for hit in hits],
            "derived": True, "ranking": "lexical_bm25"})

    async def status(self, request: web.Request) -> web.Response:
        _only(request, set())
        if not self._core.health.ready:
            raise EvidenceApiError(503, "core_unavailable", "core is not ready")
        wiring = self._core.memory
        if wiring.service is None:
            return web.json_response({"available": False, "reason_code": wiring.unavailable, "legs": {}})
        states = await asyncio.to_thread(wiring.service.status)
        settings = await asyncio.to_thread(wiring.settings.current) if wiring.settings is not None else None
        return web.json_response({
            "available": True, "index_ready": wiring.service.index_ready,
            "recall_enabled": settings.recall.enabled if settings is not None else None,
            "legs": {name: {"status": state.status.value, "reason_code": state.reason_code, "reason": state.reason}
                     for name, state in states.items()}})

    async def recall_explain(self, request: web.Request) -> web.Response:
        _only(request, {"q", "scope", "max_items"})
        query = self._query(request)
        service = self._service()
        budget = RecallBudget(max_items=_int(request, "max_items", 6, 1, MAX_RECALL_ITEMS) or 6,
                              timeout_ms=DEFAULT_RECALL_TIMEOUT_MS)
        result, degraded, scopes = await service.recall_explain(query, budget, self._scopes(request))
        return web.json_response({
            "scopes": list(scopes), "degraded": list(degraded),
            "timings_ms": dict(result.timings_ms), "budget": {"max_items": budget.max_items,
                                                              "timeout_ms": budget.timeout_ms,
                                                              "item_chars": budget.max_item_chars,
                                                              "total_chars": budget.max_total_chars},
            "items": [{"id": item.memory_id, "title": item.title, "snippet": item.snippet, "score": item.score,
                       "rank_sources": dict(item.rank_sources), "why": item.why, "level": item.level.value,
                       "retention": item.retention.value, "source": item.provenance_ref, "revision": item.revision}
                      for item in result.items]})

    async def candidates(self, request: web.Request) -> web.Response:
        _only(request, set())
        service = self._service()
        found = await service.candidates()
        return web.json_response({"candidates": found, "available": service.candidates_available})


__all__ = ["MemoryProtocolRoutes", "PREFIX", "note_payload"]
