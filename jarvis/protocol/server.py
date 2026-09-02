from __future__ import annotations

import asyncio
import hmac

from aiohttp import web

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import PROTOCOL_VERSION, TurnKind, jsonable
from jarvis.v2_config import validate_loopback_host


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
            web.post("/v1/tools/call", self.call_tool),
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

    async def call_tool(self, request: web.Request) -> web.Response:
        body = await request.json()
        name = str(body.get("name") or "").strip()
        arguments = body.get("arguments") or {}
        if not name or not isinstance(arguments, dict):
            raise ValueError("tool name and object arguments are required")
        result = await self.core.tools.call(name, arguments, conversation_id=body.get("conversation_id"))
        return web.json_response(result)

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
