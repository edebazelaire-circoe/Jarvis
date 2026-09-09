from __future__ import annotations

import asyncio
import hmac

from aiohttp import web

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import PROTOCOL_VERSION, AddressingDecision, BrainTurnInput, BrainTurnSource, TurnKind, jsonable
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

    def _app(self) -> web.Application:
        app = web.Application(middlewares=[self._auth])
        app.add_routes([
            web.get("/v1/health", self.health),
            web.post("/v1/conversations", self.create_conversation),
            web.get("/v1/conversations/{conversation_id}/context", self.context),
            web.post("/v1/conversations/{conversation_id}/turns", self.append_turn),
            web.post("/v1/conversations/{conversation_id}/brain-turns", self.submit_brain_turn),
            web.post("/v1/tools/call", self.call_tool),
            web.post("/v1/actions/{action_id}/confirmation", self.confirm_action),
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
        return web.json_response(await self.core.conversations.rehydration_context(request.match_info["conversation_id"]))

    async def append_turn(self, request: web.Request) -> web.Response:
        body = await request.json()
        kind = TurnKind(str(body.get("kind", "user")))
        content = body.get("content")
        correlation_id = str(body.get("correlation_id") or "").strip()
        if not isinstance(content, str) or not correlation_id:
            raise ValueError("content and correlation_id are required")
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
        return web.json_response(jsonable(acceptance), status=200 if acceptance.duplicate else 202)

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
