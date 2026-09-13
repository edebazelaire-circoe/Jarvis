from __future__ import annotations

import asyncio
import hmac
import json

from aiohttp import web

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import PROTOCOL_VERSION, AddressingDecision, BrainTurnInput, BrainTurnSource, TurnKind, jsonable
from jarvis.domain.work_state import WorkObservationBatch
from jarvis.domain.live_lifecycle import LiveCloseEvidence, LiveLifecycleConflict, LiveLifecycleState
from jarvis.v2_config import validate_loopback_host


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
        app = web.Application(middlewares=[self._auth])
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
            web.get("/v1/events", self.events),
        ])
        return app

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app(), access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        try:
            await self._site.start()
        except OSError as exc:
            await self.stop()
            raise RuntimeError(f"Jarvis Core cannot bind {self.host}:{self.port}: {exc}") from exc

    async def stop(self) -> None:
        site, self._site = self._site, None
        runner, self._runner = self._runner, None
        if site is not None:
            await site.stop()
        if runner is not None:
            await runner.cleanup()

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"protocol_version": PROTOCOL_VERSION, "ready": self.core.health.ready, "status": self.core.health.status, "detail": self.core.health.detail})

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
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result
        def nonfinite(_value):
            raise ValueError("nonfinite JSON number")
        try:
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
        except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("invalid canonical voice JSON") from exc
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

        Corps : `WorkObservationBatch` (`source`, `producer_id`, 1 à 64
        `observations`). Strict : un champ inconnu, à l'enveloppe comme dans
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

    async def work_snapshot(self, request: web.Request) -> web.Response:
        """État de travail normalisé tenu par Core, indépendant de tout Control Center."""

        snapshot = await self.core.work_state.snapshot()
        return web.json_response({"store_id": self.core.work_state.store_id, **snapshot.to_payload()})

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
