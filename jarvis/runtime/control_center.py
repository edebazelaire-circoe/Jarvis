from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse
import uuid

from aiohttp import web

from jarvis.runtime.audio_devices import AudioDiagnosticError, SoundDeviceAudioDiagnostics, normalize_device_id
from jarvis.runtime.claude_local import DEFAULT_PERMISSION_MODE, PERMISSION_MODES, ClaudeLocalAgent, normalize_permission_mode
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.visual_signals import VisualSignalBus
from jarvis.v2_config import REALTIME_VOICES, TURN_MODES


VOICE_HEARTBEAT_MAX_AGE_S = 5.0


class ControlCenter:
    def __init__(
        self,
        *,
        runtime_root: Path,
        project_root: Path,
        visualizer_url: str = "http://127.0.0.1:8790/faces/board/",
        audio_diagnostics: SoundDeviceAudioDiagnostics | None = None,
    ) -> None:
        self.runtime_root = runtime_root
        self.project_root = project_root
        self.visualizer_url = visualizer_url
        self.journal = RuntimeJournal(runtime_root)
        self.audio_diagnostics = audio_diagnostics or SoundDeviceAudioDiagnostics()
        self._audio_test_lock = asyncio.Lock()
        self.settings_path = runtime_root / "control-center-settings.json"
        self.agent = ClaudeLocalAgent(
            runtime_root=runtime_root,
            cwd=project_root,
            command=os.getenv("JARVIS_CLAUDE_CLI", "claude"),
            permission_mode=os.getenv("JARVIS_CLAUDE_PERMISSION_MODE", DEFAULT_PERMISSION_MODE),
        )
        self._app = web.Application(middlewares=[self._origin_guard])
        self._app.add_routes([
            web.get("/", self.index),
            web.get("/api/status", self.status),
            web.get("/api/trace", self.trace),
            web.get("/api/errors", self.errors),
            web.post("/api/errors/archive", self.archive_errors),
            web.get("/api/settings", self.get_settings),
            web.post("/api/settings", self.save_settings),
            web.get("/api/audio/devices", self.audio_devices),
            web.post("/api/audio/test", self.audio_test),
            web.get("/api/agent", self.agent_status),
            web.get("/api/agent/transcript", self.agent_transcript),
            web.post("/api/agent/console/open", self.agent_console_open),
            web.post("/api/agent/console/close", self.agent_console_close),
            web.post("/api/agent/start", self.agent_start),
            web.post("/api/agent/restart", self.agent_restart),
            web.post("/api/agent/kill", self.agent_kill),
            web.post("/api/agent/send", self.agent_send),
            web.post("/api/agent/ask", self.agent_ask),
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
        self.agent.permission_mode = normalize_permission_mode(settings.get("claude_permission_mode"))
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
            "voice_turn_mode": str(settings.get("voice_turn_mode") or "auto"),
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
        archived = str(request.query.get("archived", "")).strip().lower() in {"1", "true", "yes"}
        path = self.journal.archive_path if archived else self.journal.error_path
        return web.json_response(read_jsonl_tail(path, limit=limit))

    async def archive_errors(self, request: web.Request) -> web.Response:
        del request
        archived = self.journal.archive_errors()
        self.journal.emit("errors.archived", f"{archived} erreur(s) archivée(s)", data={"archived": archived})
        return web.json_response({"ok": True, "archived": archived})

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
        data.setdefault("audio_input_device", os.getenv("JARVIS_AUDIO_INPUT_DEVICE", ""))
        data.setdefault("audio_output_device", os.getenv("JARVIS_AUDIO_OUTPUT_DEVICE", ""))
        data.setdefault("active_timeout_s", os.getenv("JARVIS_ACTIVE_TIMEOUT_S", "90"))
        data.setdefault("realtime_voice", os.getenv("OPENAI_REALTIME_VOICE", "cedar"))
        data.setdefault("voice_turn_mode", os.getenv("JARVIS_VOICE_TURN_MODE", "auto"))
        data.setdefault("claude_permission_mode", os.getenv("JARVIS_CLAUDE_PERMISSION_MODE", DEFAULT_PERMISSION_MODE))
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
            "audio_input_device": settings.get("audio_input_device", ""),
            "audio_output_device": settings.get("audio_output_device", ""),
            "active_timeout_s": settings.get("active_timeout_s", "90"),
            "realtime_voice": settings.get("realtime_voice", "cedar"),
            "realtime_voices": list(REALTIME_VOICES),
            "voice_turn_mode": settings.get("voice_turn_mode", "auto"),
            "voice_turn_modes": sorted(TURN_MODES),
            "claude_permission_mode": normalize_permission_mode(settings.get("claude_permission_mode")),
            "claude_permission_modes": list(PERMISSION_MODES),
        })

    async def save_settings(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="settings must be an object")
        current = self._settings()
        for key in ("claude_cli", "manual_wake_key", "active_timeout_s"):
            if key in payload and payload[key] is not None:
                current[key] = str(payload[key]).strip()
        if payload.get("realtime_voice") is not None:
            voice = str(payload["realtime_voice"]).strip().lower()
            if voice not in REALTIME_VOICES:
                raise web.HTTPBadRequest(text=f"unknown realtime voice: {voice}")
            current["realtime_voice"] = voice
        if payload.get("claude_permission_mode") is not None:
            mode = str(payload["claude_permission_mode"]).strip()
            if mode not in PERMISSION_MODES:
                raise web.HTTPBadRequest(text=f"unknown Claude permission mode: {mode}")
            current["claude_permission_mode"] = mode
        if payload.get("voice_turn_mode") is not None:
            mode = str(payload["voice_turn_mode"]).strip().lower()
            if mode not in TURN_MODES:
                raise web.HTTPBadRequest(text=f"unknown voice turn mode: {mode}")
            current["voice_turn_mode"] = mode
        for key in ("audio_input_device", "audio_output_device"):
            if key in payload:
                try:
                    device = normalize_device_id(payload[key])
                except ValueError as exc:
                    raise web.HTTPBadRequest(text=str(exc)) from exc
                current[key] = "" if device is None else str(device)
        for key in ("openai_api_key", "porcupine_access_key"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                current[key] = value.strip()
        self._write_settings(current)
        self.agent.command = str(current.get("claude_cli") or "claude")
        self.agent.permission_mode = normalize_permission_mode(current.get("claude_permission_mode"))
        self.journal.emit("settings.update", "Control Center settings updated", data={"keys": sorted(payload.keys())})
        return await self.get_settings(request)

    async def audio_devices(self, request: web.Request) -> web.Response:
        del request
        correlation_id = uuid.uuid4().hex
        try:
            result = await asyncio.to_thread(self.audio_diagnostics.list_devices)
        except AudioDiagnosticError as exc:
            self.journal.emit(
                "audio.devices.failed",
                str(exc),
                level="error",
                data={"correlation_id": correlation_id, "code": exc.code, **exc.context},
            )
            return web.json_response(
                {"ok": False, "correlation_id": correlation_id, "code": exc.code, "error": str(exc)},
                status=503,
            )
        self.journal.emit(
            "audio.devices.listed",
            "Audio devices enumerated",
            data={
                "correlation_id": correlation_id,
                "input_count": len(result.get("inputs", [])),
                "output_count": len(result.get("outputs", [])),
            },
        )
        return web.json_response({"ok": True, "correlation_id": correlation_id, **result})

    async def audio_test(self, request: web.Request) -> web.Response:
        correlation_id = uuid.uuid4().hex
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("audio test payload must be an object")
            input_device = normalize_device_id(payload.get("input_device"))
            output_device = normalize_device_id(payload.get("output_device"))
        except (ValueError, json.JSONDecodeError) as exc:
            self.journal.emit(
                "audio.test.failed",
                "Invalid audio test request",
                level="error",
                data={"correlation_id": correlation_id, "code": "audio_test_invalid_request"},
            )
            return web.json_response(
                {"ok": False, "correlation_id": correlation_id, "code": "audio_test_invalid_request", "error": str(exc)},
                status=400,
            )

        if self._audio_test_lock.locked():
            self.journal.emit(
                "audio.test.failed",
                "An audio test is already running",
                level="error",
                data={"correlation_id": correlation_id, "code": "audio_test_busy"},
            )
            return web.json_response(
                {"ok": False, "correlation_id": correlation_id, "code": "audio_test_busy", "error": "Un test audio est déjà en cours."},
                status=409,
            )

        self.journal.emit(
            "audio.test.started",
            "Audio record and playback test started",
            data={"correlation_id": correlation_id, "input_device": input_device, "output_device": output_device},
        )
        try:
            async with self._audio_test_lock:
                result = await asyncio.to_thread(
                    self.audio_diagnostics.test_record_and_playback,
                    input_device=input_device,
                    output_device=output_device,
                )
        except AudioDiagnosticError as exc:
            self.journal.emit(
                "audio.test.failed",
                str(exc),
                level="error",
                data={"correlation_id": correlation_id, "code": exc.code, **exc.context},
            )
            return web.json_response(
                {"ok": False, "correlation_id": correlation_id, "code": exc.code, "error": str(exc), **exc.context},
                status=422,
            )
        except Exception as exc:
            self.journal.emit(
                "audio.test.failed",
                "Unexpected audio diagnostic failure",
                level="error",
                data={"correlation_id": correlation_id, "code": "audio_test_unexpected", "exception_type": type(exc).__name__},
            )
            return web.json_response(
                {"ok": False, "correlation_id": correlation_id, "code": "audio_test_unexpected", "error": "Le test audio a échoué de manière inattendue."},
                status=500,
            )

        self.journal.emit(
            "audio.test.completed",
            "Audio record and playback test completed",
            data={"correlation_id": correlation_id, "peak_dbfs": result.get("peak_dbfs"), "rms_dbfs": result.get("rms_dbfs")},
        )
        return web.json_response({"correlation_id": correlation_id, **result})

    async def agent_status(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(self.agent.snapshot())

    async def agent_console_open(self, request: web.Request) -> web.Response:
        """Ouvrir la véritable console Windows sur la conversation en cours."""
        del request
        try:
            return web.json_response(await self.agent.open_console())
        except RuntimeError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc

    async def agent_console_close(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(await self.agent.close_console())

    async def agent_transcript(self, request: web.Request) -> web.Response:
        """Historique lisible de l'agent, au-delà de l'extrait du statut."""
        try:
            limit = min(max(int(request.query.get("limit", "200")), 1), 500)
        except ValueError:
            limit = 200
        snapshot = self.agent.snapshot()
        return web.json_response({
            "state": snapshot["state"],
            "pid": snapshot["pid"],
            "returncode": snapshot["returncode"],
            "command": self.agent.command,
            "cwd": str(self.agent.cwd),
            "session_id": self.agent.session_id,
            "console": self.agent.console_snapshot(),
            "events": self.agent.transcript(limit=limit),
        })

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

    async def agent_ask(self, request: web.Request) -> web.Response:
        """Aller-retour complet : c'est ce que consomme la boucle vocale."""
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="ask payload must be an object")
        text = str(payload.get("text") or "").strip()
        if not text:
            raise web.HTTPBadRequest(text="text is required")
        try:
            timeout_s = min(max(float(payload.get("timeout_s") or 600.0), 5.0), 1800.0)
        except (TypeError, ValueError):
            timeout_s = 180.0
        return web.json_response(await self.agent.ask(text, timeout_s=timeout_s))

    async def agent_send(self, request: web.Request) -> web.Response:
        payload = await request.json()
        text = str(payload.get("text") or "") if isinstance(payload, dict) else ""
        try:
            return web.json_response(await self.agent.send(text))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        except RuntimeError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc
