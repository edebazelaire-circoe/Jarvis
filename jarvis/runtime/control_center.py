from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from aiohttp import web

from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail


class ControlCenter:
    def __init__(self, *, runtime_root: Path, project_root: Path, visualizer_url: str = "http://127.0.0.1:8790/faces/board/") -> None:
        self.runtime_root = runtime_root
        self.project_root = project_root
        self.visualizer_url = visualizer_url
        self.journal = RuntimeJournal(runtime_root)
        self.agent = ClaudeLocalAgent(
            runtime_root=runtime_root,
            cwd=project_root,
            command=os.getenv("JARVIS_CLAUDE_CLI", "claude"),
        )
        self.settings_path = runtime_root / "control-center-settings.json"
        self._app = web.Application(middlewares=[self._origin_guard])
        self._app.add_routes([
            web.get("/", self.index),
            web.get("/api/status", self.status),
            web.get("/api/trace", self.trace),
            web.get("/api/errors", self.errors),
            web.get("/api/settings", self.get_settings),
            web.post("/api/settings", self.save_settings),
            web.get("/api/agent", self.agent_status),
            web.post("/api/agent/start", self.agent_start),
            web.post("/api/agent/restart", self.agent_restart),
            web.post("/api/agent/kill", self.agent_kill),
            web.post("/api/agent/send", self.agent_send),
        ])
        self._runner: web.AppRunner | None = None

    @web.middleware
    async def _origin_guard(self, request: web.Request, handler):  # noqa: ANN001
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("Origin")
            if origin:
                try:
                    host = origin.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
                except (IndexError, ValueError):
                    raise web.HTTPForbidden(text="invalid origin")
                if host not in {"127.0.0.1", "localhost", "[::1]", "::1"}:
                    raise web.HTTPForbidden(text="forbidden origin")
        return await handler(request)

    async def start(self, *, host: str = "127.0.0.1", port: int = 17654) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        await web.TCPSite(self._runner, host, port).start()
        self.journal.emit("ui.start", "Jarvis Control Center started", data={"host": host, "port": port})

    async def stop(self) -> None:
        await self.agent.stop()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def index(self, request: web.Request) -> web.Response:
        del request
        html = (Path(__file__).with_name("control_center.html")).read_text(encoding="utf-8")
        html = html.replace("__VISUALIZER_URL__", self.visualizer_url)
        return web.Response(text=html, content_type="text/html")

    async def status(self, request: web.Request) -> web.Response:
        del request
        voice_state = "idle"
        state_path = self.runtime_root / ".voice_state"
        try:
            voice_state = state_path.read_text(encoding="utf-8").strip() or "idle"
        except OSError:
            pass
        return web.json_response({
            "voice_state": voice_state,
            "agent": self.agent.snapshot(),
            "error_count": len(read_jsonl_tail(self.journal.error_path, limit=1000)),
        })

    async def trace(self, request: web.Request) -> web.Response:
        limit = min(max(int(request.query.get("limit", "100")), 1), 500)
        return web.json_response(read_jsonl_tail(self.journal.trace_path, limit=limit))

    async def errors(self, request: web.Request) -> web.Response:
        limit = min(max(int(request.query.get("limit", "100")), 1), 500)
        return web.json_response(read_jsonl_tail(self.journal.error_path, limit=limit))

    def _settings(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.settings_path.is_file():
            try:
                loaded = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass
        data.setdefault("claude_cli", os.getenv("JARVIS_CLAUDE_CLI", "claude"))
        data.setdefault("openai_api_key", os.getenv("OPENAI_API_KEY", ""))
        data.setdefault("porcupine_access_key", os.getenv("PORCUPINE_ACCESS_KEY", ""))
        data.setdefault("manual_wake_key", os.getenv("JARVIS_MANUAL_WAKE_KEY", "f1"))
        data.setdefault("active_timeout_s", os.getenv("JARVIS_ACTIVE_TIMEOUT_S", "90"))
        return data

    async def get_settings(self, request: web.Request) -> web.Response:
        del request
        settings = self._settings()
        return web.json_response({
            "claude_cli": settings.get("claude_cli", "claude"),
            "openai_api_key_set": bool(settings.get("openai_api_key")),
            "porcupine_access_key_set": bool(settings.get("porcupine_access_key")),
            "manual_wake_key": settings.get("manual_wake_key", "f1"),
            "active_timeout_s": settings.get("active_timeout_s", "90"),
        })

    async def save_settings(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="settings must be an object")
        current = self._settings()
        for key in ("claude_cli", "manual_wake_key", "active_timeout_s"):
            if key in payload and payload[key] is not None:
                current[key] = str(payload[key]).strip()
        for key in ("openai_api_key", "porcupine_access_key"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                current[key] = value.strip()
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        self.agent.command = str(current.get("claude_cli") or "claude")
        self.journal.emit("settings.update", "Control Center settings updated", data={"keys": sorted(payload.keys())})
        return await self.get_settings(request)

    async def agent_status(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(self.agent.snapshot())

    async def agent_start(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(await self.agent.start())

    async def agent_restart(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(await self.agent.restart())

    async def agent_kill(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(await self.agent.stop())

    async def agent_send(self, request: web.Request) -> web.Response:
        payload = await request.json()
        text = str(payload.get("text") or "") if isinstance(payload, dict) else ""
        try:
            return web.json_response(await self.agent.send(text))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
