from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse

from aiohttp import web

from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.visual_signals import VisualSignalBus


VOICE_HEARTBEAT_MAX_AGE_S = 5.0


class ControlCenter:
    def __init__(self, *, runtime_root: Path, project_root: Path, visualizer_url: str = "http://127.0.0.1:8790/faces/board/") -> None:
        self.runtime_root = runtime_root
        self.project_root = project_root
        self.visualizer_url = visualizer_url
        self.journal = RuntimeJournal(runtime_root)
        self.settings_path = runtime_root / "control-center-settings.json"
        self.agent = ClaudeLocalAgent(
            runtime_root=runtime_root,
            cwd=project_root,
            command=os.getenv("JARVIS_CLAUDE_CLI", "claude"),
        )
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
                    host = urlparse(origin).hostname
                except ValueError:
                    raise web.HTTPForbidden(text="invalid origin")
                if host not in {"127.0.0.1", "localhost", "::1"}:
                    raise web.HTTPForbidden(text="forbidden origin")
        return await handler(request)

    async def start(self, *, host: str = "127.0.0.1", port: int = 17654) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        settings = self._settings()
        self.agent.command = str(settings.get("claude_cli") or "claude")
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        await web.TCPSite(self._runner, host, port).start()
        self.journal.emit("ui.start", "Jarvis Control Center started", data={"host": host, "port": port})
        try:
            await self.agent.start()
        except RuntimeError as exc:
            self.journal.emit("agent.unavailable", str(exc), level="error")

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
        voice_online = False
        settings = self._settings()
        heartbeat_path = self.runtime_root / ".voice_heartbeat"
        try:
            heartbeat_at = float(heartbeat_path.read_text(encoding="utf-8").strip())
            heartbeat_age = max(0.0, time.time() - heartbeat_at)
            voice_online = heartbeat_age <= VOICE_HEARTBEAT_MAX_AGE_S
        except (OSError, ValueError):
            pass
        state_path = self.runtime_root / ".voice_state"
        if voice_online:
            try:
                voice_state = state_path.read_text(encoding="utf-8").strip() or "idle"
            except OSError:
                pass
        else:
            stale_paths = (
                state_path,
                self.runtime_root / ".voice_alert",
                self.runtime_root / ".voice_waveform",
            )
            try:
                stale_state = state_path.read_text(encoding="utf-8").strip()
            except OSError:
                stale_state = "idle"
            if stale_state != "idle" or any(path.exists() for path in stale_paths[1:]):
                VisualSignalBus(self.runtime_root).reset()
        return web.json_response({
            "voice_state": voice_state,
            "voice_online": voice_online,
            "manual_wake_key": str(settings.get("manual_wake_key") or "f9"),
            "agent": self.agent.snapshot(),
            "error_count": len(read_jsonl_tail(self.journal.error_path, limit=1000)),
        })

    async def trace(self, request: web.Request) -> web.Response:
        try:
            limit = min(max(int(request.query.get("limit", "100")), 1), 500)
        except ValueError:
            limit = 100
        return web.json_response(read_jsonl_tail(self.journal.trace_path, limit=limit))

    async def errors(self, request: web.Request) -> web.Response:
        try:
            limit = min(max(int(request.query.get("limit", "100")), 1), 500)
        except ValueError:
            limit = 100
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
        data.setdefault("manual_wake_key", os.getenv("JARVIS_MANUAL_WAKE_KEY", "f9"))
        data.setdefault("active_timeout_s", os.getenv("JARVIS_ACTIVE_TIMEOUT_S", "90"))
        return data

    def _write_settings(self, settings: dict[str, Any]) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix(self.settings_path.suffix + ".tmp")
        tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.settings_path)

    async def get_settings(self, request: web.Request) -> web.Response:
        del request
        settings = self._settings()
        return web.json_response({
            "claude_cli": settings.get("claude_cli", "claude"),
            "openai_api_key_set": bool(settings.get("openai_api_key")),
            "porcupine_access_key_set": bool(settings.get("porcupine_access_key")),
            "manual_wake_key": settings.get("manual_wake_key", "f9"),
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
        self._write_settings(current)
        self.agent.command = str(current.get("claude_cli") or "claude")
        self.journal.emit("settings.update", "Control Center settings updated", data={"keys": sorted(payload.keys())})
        return await self.get_settings(request)

    async def agent_status(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(self.agent.snapshot())

    async def agent_start(self, request: web.Request) -> web.Response:
        del request
        try:
            return web.json_response(await self.agent.start())
        except RuntimeError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc

    async def agent_restart(self, request: web.Request) -> web.Response:
        del request
        try:
            return web.json_response(await self.agent.restart())
        except RuntimeError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc

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
        except RuntimeError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc
