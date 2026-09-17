from __future__ import annotations

import asyncio
from dataclasses import asdict
import hmac

from aiohttp import web

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.scene import SceneActor, SceneCommand
from jarvis.domain.conversation_event_ingest import (
    MAX_CONVERSATION_EVENT_BATCH_BODY_BYTES, decode_conversation_event_batch, encode_append_results,
)
from jarvis.domain.conversation_event_export import EXPORT_MEDIA_TYPE, export_filename
from jarvis.domain.conversation_event_query import (
    CONVERSATIONS_PARAMS, EVENTS_PARAMS, EXPORT_PARAMS, LOOKUP_PARAMS, SESSIONS_PARAMS, TRANSCRIPT_PARAMS,
    check_event_id, conversations_query, encode_event_page, encode_event_response, encode_summary_page, events_query,
    export_query, lookup_query, query_params, sessions_query, transcript_query,
)
from jarvis.domain.conversation_event_search import SEARCH_PARAMS, encode_search_page, search_query
from jarvis.core.conversation_event_query import ConversationEventBusyError
from jarvis.domain.conversation_event_store import ConversationEventStoreError
from jarvis.domain.conversation_transcript import TranscriptTooLargeError
from jarvis.domain.conversation_events import ConversationEventError
from jarvis.domain.v2 import PROTOCOL_VERSION, AddressingDecision, BrainTurnInput, BrainTurnSource, TurnKind, jsonable
from jarvis.domain.work_state import WorkObservationBatch
from jarvis.domain.live_lifecycle import LiveCloseEvidence, LiveLifecycleConflict, LiveLifecycleState
from jarvis.ports.scene import ScenePatchWindow, SceneStoreError, SceneUnavailableError
from jarvis.protocol import scene_wire
from jarvis.core.scene_capture import SceneCaptureError
from jarvis.domain.scene_capture import CAPTURE_CANCELLED, MAX_CAPTURE_BYTES, MAX_CAPTURE_REQUEST_BYTES
from jarvis.protocol.strict_json import loads_strict_json
from jarvis.v2_config import validate_loopback_host


#: How often a long Core read checks that its HTTP client is still there.
CLIENT_CHECK_S = 0.25
#: Characters per streamed transcript chunk.
TEXT_CHUNK_CHARS = 64 * 1024


def _optional_text(value: object, field: str) -> str | None:
    """Normaliser un champ texte optionnel de la requête.

    Absent, `null` et chaîne vide désignent la même chose : « non fourni ».
    Un type non textuel est en revanche une erreur de l'appelant, pas une
    absence, et doit produire un 400 plutôt qu'un silence.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string when present")
    return value.strip() or None


def _live_enum(enum_type, value: object, field: str):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc


class LocalProtocolServer:
    def __init__(self, core: JarvisCoreApplication, *, host: str, port: int, token: str) -> None:
        self.core = core
        self.host = validate_loopback_host(host)
        self.port = port
        if len(token) < 32:
            raise ValueError("local protocol token must contain at least 32 characters")
        self.token = token
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        #: Levé par `stop()` avant que le runner attende les handlers en vol :
        #: tout long-poll (scène, Conversation Events) et toute lecture longue
        #: (`_unless_client_left`) rendent la main sans attendre leur échéance.
        #: Un seul signal pour les deux fonctionnalités ; recréé par `start()`.
        self._stopping = asyncio.Event()

    def _authorized(self, request: web.Request) -> bool:
        return hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {self.token}")

    @web.middleware
    async def _auth(self, request: web.Request, handler):
        if not self._authorized(request):
            return web.json_response({"error": {"code": "unauthorized", "message": "invalid local session credential"}}, status=401)
        if request.headers.get("X-Jarvis-Protocol", str(PROTOCOL_VERSION)) != str(PROTOCOL_VERSION):
            return web.json_response({"error": {"code": "protocol_mismatch", "message": f"supported version is {PROTOCOL_VERSION}"}}, status=426)
        try:
            return await handler(request)
        except KeyError as exc:
            return web.json_response({"error": {"code": "not_found", "message": str(exc)}}, status=404)
        except ValueError as exc:
            return web.json_response({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
        except LiveLifecycleConflict as exc:
            status = 503 if exc.code == "live_core_not_accepting" else 409
            return web.json_response({"error": {"code": exc.code, "message": exc.code}}, status=status)

    def _app(self) -> web.Application:
        # Largest body of any `/v1` route: a worst-case conversation event batch
        # (aiohttp's 1 MiB default would answer 413). Applies to every route.
        app = web.Application(middlewares=[self._auth], client_max_size=MAX_CONVERSATION_EVENT_BATCH_BODY_BYTES)
        app.add_routes([
            web.get("/v1/health", self.health),
            web.post("/v1/conversations", self.create_conversation),
            web.get("/v1/conversations/{conversation_id}/context", self.context),
            web.post("/v1/conversations/{conversation_id}/turns", self.append_turn),
            web.post("/v1/conversations/{conversation_id}/brain-turns", self.submit_brain_turn),
            web.get("/v1/conversations/{conversation_id}/speech-context", self.speech_context),
            web.get("/v1/conversations/{conversation_id}/outcomes", self.list_brain_outcomes),
            web.get("/v1/conversations/{conversation_id}/outcomes/{outcome_id}", self.get_brain_outcome),
            web.post("/v1/conversations/{conversation_id}/outcomes/{outcome_id}/select", self.select_brain_outcome),
            web.post("/v1/conversations/{conversation_id}/voice/session", self.bind_voice_session),
            web.post("/v1/conversations/{conversation_id}/voice/observations", self.submit_voice_observations),
            web.post("/v1/conversations/{conversation_id}/voice/admitted-turns", self.admit_voice_turn),
            web.post("/v1/conversations/{conversation_id}/back-brain/tasks", self.submit_back_brain_task),
            web.get("/v1/conversations/{conversation_id}/back-brain/tasks", self.list_back_brain_tasks),
            web.get("/v1/conversations/{conversation_id}/back-brain/tasks/{job_id}", self.back_brain_task_status),
            web.post("/v1/conversations/{conversation_id}/back-brain/tasks/{job_id}/cancel", self.cancel_back_brain_task),
            web.get("/v1/conversations/{conversation_id}/voice/snapshot", self.voice_snapshot),
            web.post("/v1/conversations/{conversation_id}/voice/speech", self.register_voice_speech),
            web.post("/v1/live/sessions/reserve", self.reserve_live_session),
            web.get("/v1/live/sessions/current", self.live_session_status),
            web.get("/v1/live/sessions/{session_id}", self.live_session_status),
            web.post("/v1/live/sessions/{session_id}/mark-start", self.mark_live_session_start),
            web.post("/v1/live/sessions/{session_id}/bind", self.bind_live_session),
            web.post("/v1/live/sessions/{session_id}/heartbeat", self.heartbeat_live_session),
            web.post("/v1/live/sessions/{session_id}/transition", self.transition_live_session),
            web.post("/v1/live/sessions/{session_id}/usage", self.update_live_session_usage),
            web.post("/v1/live/sessions/{session_id}/claim-reap", self.claim_live_session_reap),
            web.post("/v1/live/sessions/{session_id}/finalize", self.finalize_live_session),
            web.post("/v1/tools/call", self.call_tool),
            web.post("/v1/actions/{action_id}/confirmation", self.confirm_action),
            web.post("/v1/work/observations", self.ingest_work_observations),
            web.get("/v1/work/snapshot", self.work_snapshot),
            web.post("/v1/work/cancel", self.cancel_work),
            web.get("/v1/scene/snapshot", self.scene_snapshot),
            web.get("/v1/scene/patches", self.scene_patches),
            web.post("/v1/scene/commands", self.scene_command),
            web.post("/v1/scene/captures", self.scene_capture),
            web.put("/v1/scene/captures/{capture_id}", self.scene_capture_upload),
            web.post("/v1/conversation-events", self.ingest_conversation_events),
            web.get("/v1/conversation-events", self.list_conversation_events),
            web.get("/v1/conversation-events/conversations", self.list_event_conversations),
            web.get("/v1/conversation-events/sessions", self.list_event_sessions),
            web.get("/v1/conversation-events/lookup", self.lookup_conversation_events),
            web.get("/v1/conversation-events/events/{event_id}", self.get_conversation_event),
            web.get("/v1/conversation-events/transcript", self.conversation_transcript),
            web.get("/v1/conversation-events/export", self.export_conversation_events),
            web.get("/v1/conversation-events/search", self.search_conversation_events),
            web.get("/v1/events", self.events),
        ])
        return app

    async def start(self) -> None:
        # Nouvel événement plutôt que `clear()` : un `asyncio.Event` déjà
        # attendu reste lié à sa boucle, un redémarrage sur une autre boucle
        # lèverait `RuntimeError`.
        self._stopping = asyncio.Event()
        self._runner = web.AppRunner(self._app(), access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        try:
            await self._site.start()
        except OSError as exc:
            await self.stop()
            raise RuntimeError(f"Jarvis Core cannot bind {self.host}:{self.port}: {exc}") from exc

    async def stop(self) -> None:
        self._stopping.set()
        # Une capture en attente rend la main tout de suite (`capture_cancelled`).
        self.core.scene_captures.close()
        site, self._site = self._site, None
        runner, self._runner = self._runner, None
        if site is not None:
            await site.stop()
        if runner is not None:
            await runner.cleanup()

    async def health(self, request: web.Request) -> web.Response:
        store = self.core.conversation_events
        return web.json_response({"protocol_version": PROTOCOL_VERSION, "ready": self.core.health.ready, "status": self.core.health.status, "detail": self.core.health.detail,
                                  # `scene` : disponibilité de la scène constellation (Slice 03). Elle ne
                                  # change pas `ready` : une scène refusée n'empêche pas Core de servir.
                                  "scene": scene_wire.availability_block(self.core.scene.availability, self.core.scene.capacity),
                                  # Loss visibility (Slice 04): Core emitter + ingestion counters, store read health.
                                  "conversation_events": {
                                      "emitter": asdict(self.core.conversation_event_emitter.counters),
                                      "store": {"unreadable_rows": store.unreadable_rows,
                                                "diagnostic_failures": store.diagnostic_failures},
                                      "query_failures": self.core.conversation_event_queries.failures}})

    async def create_conversation(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        conversation = await self.core.conversations.create(device_id=str(body.get("device_id") or "windows-desktop"))
        return web.json_response(jsonable(conversation), status=201)

    async def context(self, request: web.Request) -> web.Response:
        conversation_id = request.match_info["conversation_id"]
        context = await self.core.voice_ledger.context(conversation_id)
        return web.json_response(context if context is not None else await self.core.conversations.rehydration_context(conversation_id))

    def _voice_unavailable(self) -> web.Response | None:
        if not self.core.health.ready:
            return web.json_response({"error": {"code": "core_stopping", "message": "Core is not accepting voice observations"}}, status=503)
        return None

    @staticmethod
    async def _voice_body(request: web.Request, keys: set[str]) -> dict:
        raw = await request.read()
        if len(raw) > 1_048_576:
            raise ValueError("canonical voice request exceeds byte bound")
        body = loads_strict_json(raw, invalid_message="invalid canonical voice JSON")
        if not isinstance(body, dict) or set(body) != keys:
            raise ValueError("invalid canonical voice request fields")
        return body

    async def bind_voice_session(self, request: web.Request) -> web.Response:
        unavailable = self._voice_unavailable()
        if unavailable is not None:
            return unavailable
        body = await self._voice_body(request, {"session_id"})
        return web.json_response(await self.core.voice_ledger.bind_session(request.match_info["conversation_id"], body["session_id"]))

    async def submit_voice_observations(self, request: web.Request) -> web.Response:
        unavailable = self._voice_unavailable()
        if unavailable is not None:
            return unavailable
        body = await self._voice_body(request, {"session_id", "events"})
        return web.json_response(await self.core.voice_ledger.ingest(request.match_info["conversation_id"], body["session_id"], body["events"]))

    async def voice_snapshot(self, request: web.Request) -> web.Response:
        return web.json_response(await self.core.voice_ledger.snapshot(request.match_info["conversation_id"]))

    async def _back_brain_body(self, request):
        from jarvis.domain.back_brain import decode_request
        if request.query:
            raise ValueError("unexpected query")
        raw = bytearray()
        async for chunk in request.content.iter_chunked(4096):
            raw.extend(chunk)
            if len(raw) > 16384:
                raise ValueError("back brain request exceeds byte bound")
        return decode_request(bytes(raw))

    async def submit_back_brain_task(self, request):
        from jarvis.domain.back_brain import BackBrainSubmitRequest
        if not self.core.health.ready:
            return web.json_response({"error": {"code": "core_unavailable"}}, status=503)
        value = BackBrainSubmitRequest.from_payload(await self._back_brain_body(request))
        if value.conversation_id != request.match_info["conversation_id"]:
            raise ValueError("conversation identity mismatch")
        result = await self.core.back_brain.submit(value)
        return web.json_response(result.to_payload())

    async def list_back_brain_tasks(self, request):
        if set(request.query) - {"limit"} or len(request.query.getall("limit", [])) > 1:
            raise ValueError("unexpected list query")
        raw = request.query.get("limit", "32")
        if not raw.isascii() or not raw.isdigit():
            raise ValueError("invalid list limit")
        return web.json_response(await self.core.back_brain.list(request.match_info["conversation_id"], limit=int(raw)))

    async def back_brain_task_status(self, request):
        if request.query:
            raise ValueError("unexpected status query")
        return web.json_response(await self.core.back_brain.status(request.match_info["conversation_id"], request.match_info["job_id"]))

    async def cancel_back_brain_task(self, request):
        value = await self._back_brain_body(request)
        if set(value) != {"schema_version"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("invalid cancel request")
        return web.json_response(await self.core.back_brain.cancel(request.match_info["conversation_id"], request.match_info["job_id"]))

    async def admit_voice_turn(self, request: web.Request) -> web.Response:
        from jarvis.domain.voice_admission import MAX_ADMISSION_JSON_BYTES, decode_voice_admission
        unavailable = self._voice_unavailable()
        if unavailable is not None:
            return unavailable
        if request.query:
            raise ValueError("unexpected voice admission query")
        raw = bytearray()
        async for chunk in request.content.iter_chunked(8192):
            raw.extend(chunk)
            if len(raw) > MAX_ADMISSION_JSON_BYTES:
                raise ValueError("voice admission request exceeds byte bounds")
        admission = decode_voice_admission(bytes(raw))
        if admission.conversation_id != request.match_info["conversation_id"]:
            raise ValueError("voice admission conversation differs from route")
        result = await self.core.voice_admission.admit_voice_turn(admission)
        return web.json_response(result.to_payload())

    async def speech_context(self, request: web.Request) -> web.Response:
        if request.query:
            raise ValueError("unexpected speech context query")
        return web.json_response(await self.core.brain.speech_context(request.match_info["conversation_id"]))

    async def list_brain_outcomes(self, request: web.Request) -> web.Response:
        if set(request.query) - {"limit"} or len(request.query.getall("limit", [])) > 1:
            raise ValueError("invalid outcome query")
        value = request.query.get("limit", "32")
        if not value.isascii() or not value.isdecimal() or len(value) > 3:
            raise ValueError("invalid outcome limit")
        return web.json_response(await self.core.outcomes.list(request.match_info["conversation_id"], limit=int(value)))

    async def get_brain_outcome(self, request: web.Request) -> web.Response:
        if request.query:
            raise ValueError("unexpected outcome query")
        outcome = await self.core.outcomes.get(request.match_info["conversation_id"], request.match_info["outcome_id"])
        return web.json_response(outcome.to_payload())

    async def select_brain_outcome(self, request: web.Request) -> web.Response:
        unavailable = self._voice_unavailable()
        if unavailable is not None:
            return unavailable
        if request.query:
            raise ValueError("unexpected selection query")
        body = await self._voice_body(request, {"selection_id"})
        return web.json_response(await self.core.brain.select_outcome(
            request.match_info["conversation_id"], request.match_info["outcome_id"], body["selection_id"]))

    async def register_voice_speech(self, request: web.Request) -> web.Response:
        unavailable = self._voice_unavailable()
        if unavailable is not None:
            return unavailable
        body = await self._voice_body(request, {"correlation", "intended_text"})
        return web.json_response(await self.core.voice_ledger.register_speech(request.match_info["conversation_id"], body["correlation"], body["intended_text"]))

    @staticmethod
    def _live_response(record) -> web.Response:
        return web.json_response({"record": record.to_payload() if record is not None else None})

    async def reserve_live_session(self, request: web.Request) -> web.Response:
        unavailable = self._voice_unavailable()
        if unavailable is not None:
            return unavailable
        body = await self._voice_body(request, {
            "session_id", "owner_incarnation_id",
        })
        record = await self.core.live_lifecycle.reserve(
            body["session_id"], body["owner_incarnation_id"],
        )
        return self._live_response(record)

    async def live_session_status(self, request: web.Request) -> web.Response:
        if request.query:
            raise ValueError("unexpected Live status query")
        return self._live_response(await self.core.live_lifecycle.status(
            request.match_info.get("session_id")
        ))

    async def bind_live_session(self, request: web.Request) -> web.Response:
        body = await self._voice_body(request, {
            "owner_incarnation_id", "owner_epoch", "expected_revision",
            "provider_session_id",
        })
        return self._live_response(await self.core.live_lifecycle.bind(
            request.match_info["session_id"], body["owner_incarnation_id"],
            body["owner_epoch"], body["expected_revision"], body["provider_session_id"],
        ))

    async def mark_live_session_start(self, request: web.Request) -> web.Response:
        unavailable = self._voice_unavailable()
        if unavailable is not None:
            return unavailable
        body = await self._voice_body(request, {
            "owner_incarnation_id", "owner_epoch", "expected_revision",
        })
        return self._live_response(await self.core.live_lifecycle.mark_start(
            request.match_info["session_id"], body["owner_incarnation_id"],
            body["owner_epoch"], body["expected_revision"],
        ))

    async def heartbeat_live_session(self, request: web.Request) -> web.Response:
        body = await self._voice_body(request, {
            "owner_incarnation_id", "owner_epoch", "expected_revision",
        })
        return self._live_response(await self.core.live_lifecycle.heartbeat(
            request.match_info["session_id"], body["owner_incarnation_id"],
            body["owner_epoch"], body["expected_revision"],
        ))

    async def transition_live_session(self, request: web.Request) -> web.Response:
        body = await self._voice_body(request, {
            "owner_incarnation_id", "owner_epoch", "expected_revision", "target", "close_reason",
        })
        return self._live_response(await self.core.live_lifecycle.transition(
            request.match_info["session_id"], body["owner_incarnation_id"],
            body["owner_epoch"], body["expected_revision"],
            _live_enum(LiveLifecycleState, body["target"], "target"),
            body["close_reason"],
        ))

    async def update_live_session_usage(self, request: web.Request) -> web.Response:
        body = await self._voice_body(request, {
            "owner_incarnation_id", "owner_epoch", "expected_revision",
            "active_seconds", "provider_usage_seconds", "provider_usage_final",
        })
        return self._live_response(await self.core.live_lifecycle.usage(
            request.match_info["session_id"], body["owner_incarnation_id"],
            body["owner_epoch"], body["expected_revision"], body["active_seconds"],
            body["provider_usage_seconds"], body["provider_usage_final"],
        ))

    async def claim_live_session_reap(self, request: web.Request) -> web.Response:
        body = await self._voice_body(request, {
            "reaper_incarnation_id", "expected_revision",
        })
        return self._live_response(await self.core.live_lifecycle.claim_reap(
            request.match_info["session_id"], body["reaper_incarnation_id"],
            body["expected_revision"],
        ))

    async def finalize_live_session(self, request: web.Request) -> web.Response:
        body = await self._voice_body(request, {
            "owner_incarnation_id", "owner_epoch", "expected_revision",
            "provider_session_id", "active_seconds", "provider_usage_seconds",
            "close_reason", "close_evidence",
        })
        return self._live_response(await self.core.live_lifecycle.finalize(
            request.match_info["session_id"], body["owner_incarnation_id"],
            body["owner_epoch"], body["expected_revision"], body["provider_session_id"],
            body["active_seconds"], body["provider_usage_seconds"],
            body["close_reason"],
            _live_enum(LiveCloseEvidence, body["close_evidence"], "close_evidence"),
        ))

    async def append_turn(self, request: web.Request) -> web.Response:
        body = await request.json()
        kind = TurnKind(str(body.get("kind", "user")))
        content = body.get("content")
        correlation_id = str(body.get("correlation_id") or "").strip()
        if not isinstance(content, str) or not correlation_id:
            raise ValueError("content and correlation_id are required")
        if kind == TurnKind.ASSISTANT and await self.core.voice_ledger.has_ledger(request.match_info["conversation_id"]):
            raise ValueError("canonical assistant history requires confirmed voice observations")
        turn = await self.core.conversations.append_turn(request.match_info["conversation_id"], kind, content, correlation_id=correlation_id, reference_id=body.get("reference_id"), metadata=body.get("metadata") or {})
        # Legacy voice ingress (`VoiceArchitecture.LEGACY`): the durable user
        # turn is the accepted transcript. Same single producer as admission.
        self.core.voice_admission.record_user_turn_accepted(turn)
        return web.json_response(jsonable(turn), status=201)

    async def submit_brain_turn(self, request: web.Request) -> web.Response:
        """Ingress autoritaire d'un tour utilisateur complet (spec section 4).

        Voie unique
        -----------
        Ce handler ne persiste rien lui-même : il délègue à
        `BrainOrchestrator.submit()`, seul propriétaire du triptyque
        « déduplication → persistance → dépêche cerveau ». `POST .../turns`
        reste le chemin des tours ordinaires ; un tour routé vers le cerveau ne
        doit jamais emprunter les deux, sinon il serait écrit deux fois.

        Réponse immédiate
        -----------------
        L'accusé est rendu sans attendre le modèle fort : `submit()` publie
        `brain.turn.accepted` puis lance le backend dans une tâche possédée par
        Core. Les suites du tour (`brain.speech.requested`, `brain.work.*`)
        arrivent par le flux `/v1/events` déjà existant (Décision 05).

        Idempotence et fenêtre de crash
        -------------------------------
        `correlation_id` est la clé de déduplication obligatoire ;
        `provider_item_id` n'est qu'une clé secondaire, absente des surfaces qui
        n'en produisent pas (Décision 24). Un rejeu portant la même corrélation
        rend l'accusé d'origine avec `duplicate=true` et ne redéclenche aucun
        travail. Cette déduplication est **en mémoire** : elle ne survit pas à un
        redémarrage de Core (Décision 29). Si Core redémarre entre la
        persistance d'un tour et le rejeu de ce tour par la surface, le tour
        sera persisté et dépêché une seconde fois. Cette fenêtre est assumée et
        documentée, pas colmatée : aucune garantie transactionnelle n'est
        promise ici. La corriger supposerait une déduplication persistée, qui
        relève d'une décision d'architecture et non de ce endpoint.

        Codes de statut
        ---------------
        - 202 : tour accepté et dépêché ;
        - 200 : rejeu reconnu comme doublon, rien de nouveau n'a été écrit ;
        - 400 : corps invalide (JSON illisible, `content`/`correlation_id`
          manquants, champ optionnel mal typé, `source` ou `addressing`
          inconnue, `addressing="ambient"`) ;
        - 401 / 426 : authentification ou version de protocole (middleware) ;
        - 404 : conversation inconnue ;
        - 503 : Core en cours d'arrêt, aucun nouveau tour n'est accepté.
        """

        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("brain turn body must be a JSON object")
        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content is required")
        correlation_id = _optional_text(body.get("correlation_id"), "correlation_id")
        if not correlation_id:
            raise ValueError("correlation_id is required")
        source = _optional_text(body.get("source"), "source") or BrainTurnSource.REALTIME.value
        # Décision 44 : la surface dit ce qu'elle a cru du tour. Absent, le tour
        # vaut `addressed` — c'est le cas de toutes les surfaces existantes.
        # `ambient` est refusé par le domaine, donc rendu 400 ici : un tour non
        # adressé n'entre pas dans le cerveau par ce chemin ni par un autre.
        addressing = _optional_text(body.get("addressing"), "addressing") or AddressingDecision.ADDRESSED.value
        turn = BrainTurnInput(
            conversation_id=request.match_info["conversation_id"],
            text=content,
            correlation_id=correlation_id,
            source=BrainTurnSource(source),
            addressing=AddressingDecision(addressing),
            provider_item_id=_optional_text(body.get("provider_item_id"), "provider_item_id"),
            interrupted_speech_id=_optional_text(body.get("interrupted_speech_id"), "interrupted_speech_id"),
        )
        try:
            acceptance = await self.core.brain.submit(turn)
        except RuntimeError as exc:
            # `submit()` refuse tout nouveau tour pendant l'arrêt de Core. Ce
            # n'est pas une erreur de l'appelant : la surface peut réessayer sur
            # une instance vivante, avec la même corrélation.
            return web.json_response({"error": {"code": "core_stopping", "message": str(exc)}}, status=503)
        source = await self.core.outcomes.source(turn.conversation_id, acceptance.correlation_id)
        payload = {**jsonable(acceptance), **await self.core.brain.speech_context(turn.conversation_id),
                   "source": source.to_payload() if source else None}
        return web.json_response(payload, status=200 if acceptance.duplicate else 202)

    async def call_tool(self, request: web.Request) -> web.Response:
        body = await request.json()
        name = str(body.get("name") or "").strip()
        arguments = body.get("arguments") or {}
        if not name or not isinstance(arguments, dict):
            raise ValueError("tool name and object arguments are required")
        result = await self.core.tools.call(name, arguments, conversation_id=body.get("conversation_id"))
        return web.json_response(result)

    async def confirm_action(self, request: web.Request) -> web.Response:
        body = await request.json()
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("confirmation text is required")
        return web.json_response(await self.core.tools.resolve_confirmation(request.match_info["action_id"], text))

    async def ingest_work_observations(self, request: web.Request) -> web.Response:
        """Ingress des observateurs de travail d'un autre processus (handoff work-state, tâche 11).

        Corps : `WorkObservationBatch` (`source`, `producer_id`, 0 à 64
        `observations` ; un lot vide revendique seulement la source pour ce
        producteur, Slice 10). Strict : un champ inconnu, à l'enveloppe comme dans
        une observation, rend 400 et rien n'est appliqué — une trace brute de
        fournisseur n'entre pas dans Core. Une observation valide mais périmée,
        en double ou contredisant une fin n'est pas une erreur : elle est
        comptée dans `outcomes` et ignorée.

        Réponse 200 : `store_id` (change à chaque démarrage de Core : le
        producteur renvoie alors son état complet), `revision`, `outcomes`,
        `interrupted` (éléments d'une instance précédente du producteur).
        """

        body = await request.json()
        try:
            batch = WorkObservationBatch.from_payload(body)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid work observation batch: {exc}") from exc
        result = await self.core.work_state.ingest(batch)
        return web.json_response(result.to_payload())

    async def ingest_conversation_events(self, request: web.Request) -> web.Response:
        """Ingress des Conversation Events produits hors de Core (voix, Control Center).

        Corps : `{"schema_version": 1, "events": [1..32 événements encodés]}`
        (`conversation_event_ingest.encode_conversation_event_batch`). Strict :
        un événement invalide, un champ interdit ou un événement réservé à Core
        (`user.*`, `brain.*`, producteur `core.*`) rend 400 et rien n'est écrit ;
        le message nomme l'index et la règle, jamais la valeur.

        Réponse 200 : `{"schema_version": 1, "results": [{"event_id",
        "sequence", "status"}]}` dans l'ordre du lot, `status` parmi `appended`,
        `duplicate`, `conflict` (le premier exemplaire est gardé). 503
        `conversation_events_unavailable` : stockage en échec, rien n'est
        acquitté, rejouer le même lot est sûr.
        """

        body = await request.json()
        try:
            events = decode_conversation_event_batch(body)
        except ConversationEventError as exc:
            count = len(body["events"]) if isinstance(body, dict) and isinstance(body.get("events"), list) else None
            self.core.conversation_event_emitter.note_ingest_rejected(str(exc), event_count=count)
            raise
        try:
            results = await self.core.conversation_event_emitter.append_now(events)
        except ConversationEventStoreError:
            return web.json_response({"error": {"code": "conversation_events_unavailable",
                                                "message": "conversation event store unavailable; retry the same batch"}},
                                     status=503)
        return web.json_response(encode_append_results(results))

    # -- Conversation Event query API (Slice 04) --------------------------------
    #
    # Contract: `docs/conversation-events.md`, "Query and live API". Parameters
    # are strict (`conversation_event_query`): 400 `invalid_request` naming the
    # parameter, never its value. Storage failure or Core stopping: 503
    # `conversation_events_unavailable`. An unknown conversation is an empty page.

    @staticmethod
    def _events_unavailable() -> web.Response:
        return web.json_response({"error": {"code": "conversation_events_unavailable",
                                            "message": "conversation event store unavailable; retry"}}, status=503)

    async def list_event_conversations(self, request: web.Request) -> web.Response:
        """Conversations by most recent store activity; page with `before_sequence=next_cursor`."""
        query = conversations_query(query_params(request.query.items(), CONVERSATIONS_PARAMS))
        try:
            page = await self.core.conversation_event_queries.conversations(**query)
        except ConversationEventStoreError:
            return self._events_unavailable()
        return web.json_response(encode_summary_page(page))

    async def list_event_sessions(self, request: web.Request) -> web.Response:
        """Sessions of one conversation by first appearance; page with `after_sequence=next_cursor`."""
        query = sessions_query(query_params(request.query.items(), SESSIONS_PARAMS))
        try:
            page = await self.core.conversation_event_queries.sessions(query.pop("conversation_id"), **query)
        except ConversationEventStoreError:
            return self._events_unavailable()
        return web.json_response(encode_summary_page(page))

    async def list_conversation_events(self, request: web.Request) -> web.Response:
        """Events of one conversation after `after_sequence` (exclusive), ascending sequence.

        `wait_ms` (0 to 25000) turns the request into a long-poll that returns as
        soon as a page holds visible events, or after `wait_ms` with the cursor
        advanced past what was scanned; it also ends when the client disconnects.
        """
        query = events_query(query_params(request.query.items(), EVENTS_PARAMS))
        try:
            page = await self.core.conversation_event_queries.events(
                query["conversation_id"], after_sequence=query["after_sequence"], limit=query["limit"],
                visibility=query["visibility"], wait_s=query["wait_ms"] / 1000, interrupt=self._stopping,
                # aiohttp does not cancel a handler whose client left: stop holding the wait ourselves.
                disconnected=lambda: request.transport is None or request.transport.is_closing())
        except ConversationEventStoreError:
            return self._events_unavailable()
        return web.json_response(encode_event_page(page))

    async def lookup_conversation_events(self, request: web.Request) -> web.Response:
        """Events carrying one lookup id (`field` in `LOOKUP_FIELDS`), ascending sequence."""
        query = lookup_query(query_params(request.query.items(), LOOKUP_PARAMS))
        try:
            page = await self.core.conversation_event_queries.lookup(query.pop("field"), query.pop("value"), **query)
        except ConversationEventStoreError:
            return self._events_unavailable()
        return web.json_response(encode_event_page(page))

    async def get_conversation_event(self, request: web.Request) -> web.Response:
        """One stored event. 404 `conversation_event_not_found` when absent or unreadable (store diagnosed it)."""
        query_params(request.query.items(), frozenset())
        event_id = check_event_id(request.match_info["event_id"])
        try:
            stored = await self.core.conversation_event_queries.event(event_id)
        except ConversationEventStoreError:
            return self._events_unavailable()
        if stored is None:
            return web.json_response({"error": {"code": "conversation_event_not_found",
                                                "message": "no readable stored conversation event has this id"}},
                                     status=404)
        return web.json_response(encode_event_response(stored))

    # -- Slice 06: readable transcript, JSONL export, search -------------------
    #
    # Contract: `docs/conversation-events.md`, "Readable transcript", "JSONL
    # export", "Search". Same strict parameters and error shapes as the reads above.

    @staticmethod
    def _busy(exc: ConversationEventBusyError) -> web.Response:
        return web.json_response({"error": {"code": exc.code, "message": str(exc)}}, status=429)

    async def _unless_client_left(self, request: web.Request, work):
        """Run `work` (a coroutine), cancelling it when the HTTP client disconnects or the server stops.

        aiohttp does not cancel a handler whose client left: an abandoned search or
        transcript would otherwise keep costing Core CPU. Returns None when cancelled.
        """
        task = asyncio.ensure_future(work)
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=CLIENT_CHECK_S)
                if done:
                    return task.result()
                if request.transport is None or request.transport.is_closing() or self._stopping.is_set():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    return None
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def conversation_transcript(self, request: web.Request) -> web.StreamResponse:
        """Readable transcript (`text/plain`), rendered by the pure domain renderer.

        `mode` = `plain` (public items) or `detailed` (plus diagnostic items);
        `utc_offset_minutes` (default 0) shifts the printed times and is stated in
        the header. 413 `transcript_too_large` above the event or text budget (use
        the export); 429 `projection_busy` when two builds already run. The text is
        streamed in 64 KiB chunks; the build stops if the client leaves.
        """
        query = transcript_query(query_params(request.query.items(), TRANSCRIPT_PARAMS))
        try:
            text = await self._unless_client_left(request, self.core.conversation_event_queries.transcript(
                query["conversation_id"], mode=query["mode"], utc_offset_minutes=query["utc_offset_minutes"]))
        except ConversationEventStoreError:
            return self._events_unavailable()
        except ConversationEventBusyError as exc:
            return self._busy(exc)
        except TranscriptTooLargeError as exc:
            return web.json_response({"error": {"code": "transcript_too_large", "message": str(exc)}}, status=413)
        if text is None:
            return web.Response(status=499)
        response = web.StreamResponse(headers={"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"})
        await response.prepare(request)
        for start in range(0, len(text), TEXT_CHUNK_CHARS):
            await response.write(text[start:start + TEXT_CHUNK_CHARS].encode("utf-8"))
        await response.write_eof()
        return response

    async def export_conversation_events(self, request: web.Request) -> web.StreamResponse:
        """JSONL export streamed page by page: header, stored events, trailer.

        The extent is frozen before the response starts (a storage failure then is
        a plain 503, 429 `projection_busy` when two builds already run). A failure
        while streaming closes the connection without a trailer: the receiver sees
        an incomplete file, never a silently short one. A client that leaves stops
        the export at its next write and frees its slot.
        """
        query = export_query(query_params(request.query.items(), EXPORT_PARAMS))
        try:
            export = await self.core.conversation_event_queries.open_export(query["conversation_id"])
        except ConversationEventStoreError:
            return self._events_unavailable()
        except ConversationEventBusyError as exc:
            return self._busy(exc)
        chunks = export.chunks()
        try:
            filename = export_filename(query["conversation_id"])
            response = web.StreamResponse(headers={
                "Content-Type": f"{EXPORT_MEDIA_TYPE}; charset=utf-8",
                "Content-Disposition": f"attachment; filename=\"{filename}\"",
                "Cache-Control": "no-store"})
            await response.prepare(request)
            try:
                async for chunk in chunks:
                    await response.write(chunk)
            except ConversationEventStoreError:
                if request.transport is not None:
                    request.transport.close()  # no trailer, no clean end: the file reads as incomplete
                return response
            await response.write_eof()
            return response
        finally:
            await chunks.aclose()
            export.release()

    async def search_conversation_events(self, request: web.Request) -> web.Response:
        """Bounded newest-first search over public content and safe metadata; page with `before_sequence`.

        One search at a time (429 `search_busy`); it stops if the client leaves.
        """
        query = search_query(query_params(request.query.items(), SEARCH_PARAMS))
        try:
            page = await self._unless_client_left(
                request, self.core.conversation_event_queries.search(query.pop("query"), **query))
        except ConversationEventStoreError:
            return self._events_unavailable()
        except ConversationEventBusyError as exc:
            return self._busy(exc)
        if page is None:
            return web.Response(status=499)
        return web.json_response(encode_search_page(page))

    async def work_snapshot(self, request: web.Request) -> web.Response:
        """État de travail normalisé tenu par Core, indépendant de tout Control Center."""

        snapshot = await self.core.work_state.snapshot()
        return web.json_response({"store_id": self.core.work_state.store_id, **snapshot.to_payload()})

    async def cancel_work(self, request: web.Request) -> web.Response:
        """Arrêter le travail d'une étoile de la scène, à la demande de l'utilisateur (Slice 08).

        Corps strict `{"schema_version": 1, "source", "external_id"}` : le
        `work_ref` de l'étoile. Seuls les jobs Core (`source = job`) s'arrêtent :
        un sous-agent Claude n'a aucun arrêt individuel (409 `not_cancellable`,
        rien n'est touché). Job inconnu : 404. Réponse 200
        `{source, external_id, outcome, status}` avec `outcome` ∈ `cancelled`,
        `cancel_requested`, `cleanup_unknown`, `already_terminal`
        (`JobService.cancel_for_user`). Corps au-delà de 4 Kio : 413.
        """

        from jarvis.core.v2_services import JOB_WORK_SOURCE
        from jarvis.domain._checks import check_id

        if request.query:
            raise ValueError("unexpected cancel query")
        try:
            raw = await scene_wire.read_bounded_body(request, limit=scene_wire.MAX_WORK_CANCEL_BYTES)
        except scene_wire.SceneBodyTooLarge:
            return web.json_response(
                scene_wire.error_body(scene_wire.PAYLOAD_TOO_LARGE, f"work cancel request exceeds {scene_wire.MAX_WORK_CANCEL_BYTES} bytes"),
                status=413,
            )
        value = loads_strict_json(raw, invalid_message="invalid work cancel JSON")
        if not isinstance(value, dict) or set(value) != {"schema_version", "source", "external_id"}:
            raise ValueError("work cancel request must be {schema_version, source, external_id}")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("unsupported work cancel schema_version")
        source, external_id = value["source"], value["external_id"]
        if not isinstance(source, str) or not isinstance(external_id, str):
            raise ValueError("source and external_id must be strings")
        check_id("external_id", external_id, required=True)
        if source != JOB_WORK_SOURCE:
            return web.json_response(
                {"error": {"code": "not_cancellable", "message": "only Core jobs can be stopped; this work has no individual stop"}},
                status=409,
            )
        if not self.core.health.ready:
            return web.json_response({"error": {"code": "core_unavailable", "message": "core is not ready"}}, status=503)
        outcome, job = await self.core.jobs.cancel_for_user(external_id)
        return web.json_response({"source": source, "external_id": external_id, "outcome": outcome, "status": job.status.value})

    # ------------------------------------------------------------ scène (Slice 03)

    def _scene_failure(self, exc: SceneStoreError) -> web.Response:
        """503 d'une scène non servie (`scene_unavailable`) ou d'une écriture échouée (`scene_persist_failed`).

        L'état de la scène (`error.scene`) et le code du magasin
        (`error.store_code`) voyagent avec l'erreur : le client distingue un
        fichier refusé d'une écriture momentanément impossible.
        """

        code = scene_wire.SCENE_UNAVAILABLE if isinstance(exc, SceneUnavailableError) else scene_wire.SCENE_PERSIST_FAILED
        return web.json_response(
            scene_wire.error_body(code, str(exc), scene=scene_wire.availability_block(self.core.scene.availability, self.core.scene.capacity), store_code=exc.code.value),
            status=503,
        )

    async def scene_snapshot(self, request: web.Request) -> web.Response:
        """Instantané complet de la scène active, avec `scene_id`, `epoch` et `revision`.

        L'encodage (jusqu'à ~11 MiB au pire, ~1,4 MiB réaliste) se fait hors de
        la boucle de Core : un instantané lu ne retarde pas la voix.
        """

        if request.query:
            raise ValueError("unexpected query")
        scene = self.core.scene
        try:
            snapshot = await scene.snapshot()
        except SceneUnavailableError as exc:
            return self._scene_failure(exc)
        body = await asyncio.to_thread(scene_wire.snapshot_body, snapshot, scene.epoch)
        return web.Response(text=body, content_type="application/json")

    async def scene_patches(self, request: web.Request) -> web.Response:
        """Long-poll des patchs postérieurs à `after` (`scene_id`, `epoch`, `after`, `wait_s`).

        Autre époque ou autre `scene_id`, `after` hors de l'anneau ou en avance
        sur Core : `resync_required` aussitôt, sans attendre et sans instantané.
        Sinon, rien de neuf : attente locale (`SceneService.wait_for_revision`,
        jamais `CoreEventBus`), bornée par Core à 30 s et interrompue par
        `stop()`, puis patchs rendus. Réponse bornée (`more: true` au-delà).
        """

        query = scene_wire.parse_patch_query(request.query)
        scene = self.core.scene
        try:
            window = await self._scene_window(query)
        except SceneUnavailableError as exc:
            return self._scene_failure(exc)
        capture = self.core.scene_captures.deliver(long_poll=query.wait_s > 0) if not window.resync_required else None
        body = scene_wire.patch_window_body(window, epoch=scene.epoch, after=query.after, capture_request=capture)
        return web.Response(text=body, content_type="application/json")

    async def _scene_window(self, query: scene_wire.PatchQuery) -> ScenePatchWindow:
        scene = self.core.scene
        if query.epoch != scene.epoch:
            current = await scene.snapshot()
            return ScenePatchWindow(current.scene_id, current.revision, (), resync_required=True)
        window = await scene.patches_since(query.after, scene_id=query.scene_id)
        if window.patches or window.resync_required or query.wait_s <= 0 or self._stopping.is_set():
            return window
        # Slice 09 (partie 2) : une demande de capture réveille aussi l'attente ;
        # une demande déjà donnée n'est redonnée qu'après `CAPTURE_REDELIVER_S`.
        captures = self.core.scene_captures
        wake = captures.wake_event()
        due = captures.delivery_due()
        if due == 0:
            return window
        wait_s = query.wait_s if due is None else min(query.wait_s, due)
        waiter = asyncio.ensure_future(scene.wait_for_revision(query.after, timeout_s=wait_s))
        closing = asyncio.ensure_future(self._stopping.wait())
        woken = asyncio.ensure_future(wake.wait())
        try:
            await asyncio.wait({waiter, closing, woken}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (waiter, closing, woken):
                task.cancel()
            await asyncio.gather(waiter, closing, woken, return_exceptions=True)
        if not waiter.cancelled() and waiter.exception() is not None:
            raise waiter.exception()
        return await scene.patches_since(query.after, scene_id=query.scene_id)

    async def scene_command(self, request: web.Request) -> web.Response:
        """Une `SceneCommand` d'un appelant authentifié par jeton.

        Acteurs acceptés : `brain` et `user`. `runtime` est refusé (403
        `scene_actor_forbidden`) : l'écrivain runtime vit dans Core (Slice 04)
        et n'a pas besoin de HTTP. Un refus du domaine n'est pas une erreur
        HTTP : 200 avec `outcome` et `reason`. Corps illisible : 400 ; trop
        gros : 413 ; scène indisponible ou écriture échouée : 503.
        """

        if request.query:
            raise ValueError("unexpected query")
        try:
            raw = await scene_wire.read_bounded_body(request, scene_wire.MAX_SCENE_COMMAND_BYTES)
        except scene_wire.SceneBodyTooLarge:
            return web.json_response(
                scene_wire.error_body(scene_wire.PAYLOAD_TOO_LARGE, f"scene command exceeds {scene_wire.MAX_SCENE_COMMAND_BYTES} bytes"),
                status=413,
            )
        try:
            command = SceneCommand.from_payload(loads_strict_json(raw, invalid_message="invalid scene command JSON"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid scene command: {exc}") from exc
        if command.actor is SceneActor.RUNTIME:
            return web.json_response(
                scene_wire.error_body(scene_wire.SCENE_ACTOR_FORBIDDEN, "actor runtime writes inside Core, never over HTTP"),
                status=403,
            )
        scene = self.core.scene
        try:
            update = await scene.apply(command)
        except SceneStoreError as exc:
            return self._scene_failure(exc)
        return web.json_response(scene_wire.command_body(update, epoch=scene.epoch), dumps=scene_wire.compact_json)

    # ------------------------------------------------------------ capture (Slice 09, partie 2)

    @staticmethod
    def _capture_failure(exc: SceneCaptureError) -> web.Response:
        return web.json_response(scene_wire.error_body(exc.code, str(exc)), status=exc.status)

    async def scene_capture(self, request: web.Request) -> web.Response:
        """Demande de capture du cerveau : `{schema_version: 1, actor: "brain"}`, rendue quand la page a envoyé le PNG.

        200 `{capture_id, name, path, bytes, width, height, duration_ms}` ;
        409 `capture_busy` ; 504 `no_visible_page` (échéance 5 s) ; 503
        `capture_unavailable`, `scene_unavailable` ou `capture_cancelled` ; 403
        pour un autre acteur. Aucune route du Control Center ne la déclenche.
        """

        if request.query:
            raise ValueError("unexpected query")
        try:
            raw = await scene_wire.read_bounded_body(request, MAX_CAPTURE_REQUEST_BYTES)
        except scene_wire.SceneBodyTooLarge:
            return web.json_response(scene_wire.error_body(scene_wire.PAYLOAD_TOO_LARGE, "capture request too large"), status=413)
        body = loads_strict_json(raw, invalid_message="invalid capture request JSON")
        if not isinstance(body, dict) or set(body) != {"schema_version", "actor"} or body["schema_version"] != 1:
            raise ValueError("capture request must be {schema_version: 1, actor}")
        if body["actor"] != SceneActor.BRAIN.value:
            return web.json_response(
                scene_wire.error_body(scene_wire.SCENE_ACTOR_FORBIDDEN, "only the brain requests a scene capture"), status=403,
            )
        if self.core.scene.availability.state.value != "ready":
            return web.json_response(
                scene_wire.error_body(scene_wire.SCENE_UNAVAILABLE, "scene is not served: nothing to capture",
                                      scene=scene_wire.availability_block(self.core.scene.availability, self.core.scene.capacity)),
                status=503,
            )
        try:
            # Client parti (brain abandonné, CLI tué) : la demande est annulée aussitôt,
            # la place se libère au lieu d'un `capture_busy` jusqu'à l'échéance.
            result = await self._unless_client_left(request, self.core.scene_captures.request())
        except SceneCaptureError as exc:
            return self._capture_failure(exc)
        if result is None:
            self.core.scene_captures.cancel()
            return self._capture_failure(SceneCaptureError(CAPTURE_CANCELLED, "capture request abandoned by its client", 503))
        return web.json_response(result)

    async def scene_capture_upload(self, request: web.Request) -> web.Response:
        """PNG d'une capture en attente, relayé par le Control Center depuis la page meneuse (≤ 2 MiB)."""

        if request.query:
            raise ValueError("unexpected query")
        capture_id = request.match_info["capture_id"]
        try:
            raw = await scene_wire.read_bounded_body(request, MAX_CAPTURE_BYTES)
        except scene_wire.SceneBodyTooLarge:
            return web.json_response(
                scene_wire.error_body(scene_wire.PAYLOAD_TOO_LARGE, f"capture exceeds {MAX_CAPTURE_BYTES} bytes"), status=413,
            )
        try:
            result = await self.core.scene_captures.complete(capture_id, raw)
        except SceneCaptureError as exc:
            return self._capture_failure(exc)
        return web.json_response({key: result[key] for key in ("capture_id", "bytes", "width", "height", "duration_ms")})

    async def events(self, request: web.Request) -> web.StreamResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        queue = self.core.events.subscribe()
        try:
            await ws.send_json({"protocol_version": PROTOCOL_VERSION, "message_type": "connected", "payload": {}})
            while not ws.closed:
                event_task = asyncio.create_task(queue.get())
                receive_task = asyncio.create_task(ws.receive())
                done, pending = await asyncio.wait({event_task, receive_task}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if event_task in done:
                    await ws.send_json(jsonable(event_task.result()))
                if receive_task in done:
                    message = receive_task.result()
                    if message.type in {web.WSMsgType.CLOSE, web.WSMsgType.CLOSED, web.WSMsgType.ERROR}:
                        break
                    if message.type == web.WSMsgType.TEXT:
                        await ws.send_json({"protocol_version": PROTOCOL_VERSION, "message_type": "ack", "payload": {"received": True}})
        finally:
            self.core.events.unsubscribe(queue)
            await ws.close()
        return ws
