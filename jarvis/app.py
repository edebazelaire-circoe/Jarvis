from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import webbrowser

from jarvis.adapters.barehands_board import BarehandsBoardClient
from jarvis.audio.capture import SoundDeviceRecorder
from jarvis.audio.ptt import PTTKeyListener
from jarvis.config import AppConfig
from jarvis.domain.errors import JarvisError
from jarvis.runtime.factory import create_runtime
from jarvis.runtime.health import run_health_checks
from jarvis.runtime.voice import VoiceRuntime
from jarvis.security.session_token import generate_session_token


ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="Jarvis local assistant")
    parser.add_argument("--config", help="Path to legacy jarvis.toml")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="Run legacy push-to-talk fallback")
    run.add_argument("--no-preflight", action="store_true")
    text = sub.add_parser("text", help="Run one legacy text turn")
    text.add_argument("message")
    health = sub.add_parser("health", help="Print legacy component health")
    health.add_argument("--skip-audio", action="store_true")
    sub.add_parser("reindex", help="Rebuild the disposable Markdown search index")
    sub.add_parser("core", help="Run persistent v0.2 Core daemon")
    sub.add_parser("voice", help="Run v0.2 wake-word + Realtime Voice client")
    sub.add_parser("control-center", help="Run Jarvis visualizer + Control Center + local Claude agent")
    return parser


async def _run_voice(config: AppConfig, *, no_preflight: bool) -> int:
    runtime = create_runtime(config, speech_enabled=True)
    if not no_preflight:
        runtime.recorder.preflight()
    await runtime.state.initialize()
    voice = VoiceRuntime(recorder=runtime.recorder, transcriber=runtime.transcriber, orchestrator=runtime.orchestrator, logger=runtime.logger)
    ptt = PTTKeyListener(config.runtime.ptt_key, on_press=voice.press, on_release=voice.release)
    print(f"Jarvis PTT fallback prêt. Maintenez {config.runtime.ptt_key.upper()} pour parler.")
    try:
        await ptt.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        ptt.stop(); runtime.recorder.abort(); await runtime.state.cleanup()
    return 0


async def _run_text(config: AppConfig, message: str) -> int:
    runtime = create_runtime(config, speech_enabled=False)
    await runtime.state.initialize()
    try:
        result = await runtime.orchestrator.handle_text(message)
        print(result.text)
        if result.awaiting_confirmation:
            print(f"[confirmation:{result.action_id}]", file=sys.stderr)
        return 0
    finally:
        await runtime.state.cleanup()


async def _health(config: AppConfig, *, skip_audio: bool) -> int:
    token = generate_session_token()
    board = BarehandsBoardClient(config.board.url, token) if config.board.enabled else None
    recorder = SoundDeviceRecorder(sample_rate=config.audio.sample_rate, channels=config.audio.channels, input_device=config.audio.input_device)
    report = await run_health_checks(config, board=board, check_audio=not skip_audio, recorder=recorder)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 1 if report.status == "fail" else 0


async def _reindex(config: AppConfig) -> int:
    from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
    memory = MarkdownMemoryBackend(config.runtime.memory_dir)
    count = await memory.rebuild_index()
    print(f"Index reconstruit depuis Markdown: {count} document(s).")
    return 0


def _write_session_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(token, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _calendar_backend_from_env():
    provider = os.getenv("JARVIS_CALENDAR_PROVIDER", "fake").strip().lower()
    if provider in {"", "fake", "none"}:
        return None
    if provider != "google":
        raise RuntimeError(f"Unsupported calendar provider: {provider}")
    from jarvis.adapters.google_calendar import GoogleCalendarBackend
    secret = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET")
    token = os.getenv("GOOGLE_CALENDAR_TOKEN")
    if not secret or not token:
        raise RuntimeError("Google Calendar requires GOOGLE_CALENDAR_CLIENT_SECRET and GOOGLE_CALENDAR_TOKEN paths")
    return GoogleCalendarBackend.from_oauth_files(Path(secret), Path(token), calendar_id=os.getenv("GOOGLE_CALENDAR_ID", "primary"))


def _control_settings(runtime_root: Path) -> dict[str, object]:
    path = runtime_root / "control-center-settings.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


async def _run_core_v2() -> int:
    from jarvis.adapters.windows_notifications import NullNotificationDelivery, WindowsNotificationDelivery
    from jarvis.core.memory_maintenance import MemoryMaintenanceWorker
    from jarvis.core.v2_app import JarvisCoreApplication
    from jarvis.protocol.server import LocalProtocolServer
    from jarvis.v2_config import V2Settings
    settings = V2Settings.load()
    token = generate_session_token()
    _write_session_token(settings.token_file, token)
    delivery = WindowsNotificationDelivery() if os.name == "nt" and os.getenv("JARVIS_WINDOWS_NOTIFICATIONS", "0") in {"1", "true", "yes"} else NullNotificationDelivery()
    workers = {"memory_maintenance": MemoryMaintenanceWorker(settings.data_root / "memory")}
    core = JarvisCoreApplication(data_root=settings.data_root, timezone=settings.timezone, calendar_backend=_calendar_backend_from_env(), notification_delivery=delivery, workers=workers)
    server = LocalProtocolServer(core, host=settings.core_host, port=settings.core_port, token=token)
    try:
        await core.start(); await server.start()
        print(f"Jarvis Core v0.2 ready on http://{settings.core_host}:{settings.core_port}")
        await core.wait()
    finally:
        await server.stop(); await core.stop(); settings.token_file.unlink(missing_ok=True)
    return 0


async def _run_voice_v2() -> int:
    from jarvis.adapters.openai_realtime import OpenAIRealtimeSession
    from jarvis.adapters.wakeword_composite import CompositeWakeWordBackend
    from jarvis.adapters.wakeword_keyboard import KeyboardWakeWordBackend
    from jarvis.adapters.wakeword_porcupine import PorcupineWakeWordBackend
    from jarvis.protocol.client import LocalCoreClient
    from jarvis.runtime.journal import RuntimeJournal
    from jarvis.runtime.realtime_tools import REALTIME_TOOLS
    from jarvis.runtime.visual_signals import VisualSignalBus
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
    from jarvis.v2_config import V2Settings
    settings = V2Settings.load()
    overrides = _control_settings(settings.runtime_root)
    if not settings.token_file.exists():
        raise RuntimeError("Core session token is missing; start `jarvis core` first")
    token = settings.token_file.read_text(encoding="utf-8").strip()
    api_key = str(overrides.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for Realtime voice")
    core = LocalCoreClient(host=settings.core_host, port=settings.core_port, token=token)
    health = await core.health()
    if not health.get("ready"):
        await core.close(); raise RuntimeError(f"Core is not ready: {health}")

    manual_key = str(overrides.get("manual_wake_key") or os.getenv("JARVIS_MANUAL_WAKE_KEY", "f1")).strip() or "f1"
    wake_backends = [KeyboardWakeWordBackend(key_name=manual_key)]
    wake_key = str(overrides.get("porcupine_access_key") or os.getenv("PORCUPINE_ACCESS_KEY", "")).strip()
    if wake_key:
        wake_backends.append(PorcupineWakeWordBackend(access_key=wake_key, keyword=os.getenv("JARVIS_WAKE_KEYWORD", "jarvis")))
    wake = CompositeWakeWordBackend(wake_backends)
    try:
        active_timeout = float(overrides.get("active_timeout_s") or settings.active_timeout_s)
    except (TypeError, ValueError):
        active_timeout = settings.active_timeout_s

    async def realtime_factory(context: dict[str, object]):
        return await OpenAIRealtimeSession.connect(api_key=api_key, model=settings.realtime_model, voice=settings.realtime_voice, context=context, tools=REALTIME_TOOLS)

    signals = VisualSignalBus(settings.runtime_root)
    journal = RuntimeJournal(settings.runtime_root)
    voice = PersistentVoiceRuntime(
        wakeword=wake,
        core=core,
        realtime_factory=realtime_factory,
        active_timeout_s=active_timeout,
        signals=signals,
        journal=journal,
    )
    timeout_task = asyncio.create_task(_voice_timeout_loop(voice), name="jarvis-voice-timeout")
    if wake_key:
        print(f"Jarvis Voice v0.2 en arrière-plan. Dites 'Jarvis' ou appuyez sur {manual_key.upper()} pour activer; 'Jarvis Mute' pour revenir en arrière-plan.")
    else:
        print(f"Jarvis Voice v0.2 en arrière-plan. Appuyez sur {manual_key.upper()} pour activer (Porcupine non configuré); 'Jarvis Mute' pour revenir en arrière-plan.")
    try:
        await voice.run()
    finally:
        timeout_task.cancel(); await asyncio.gather(timeout_task, return_exceptions=True); await voice.close()
    return 0


async def _run_control_center_v2() -> int:
    from jarvis.runtime.control_center import ControlCenter
    from jarvis.runtime.journal import RuntimeJournal
    from jarvis.v2_config import V2Settings

    settings = V2Settings.load()
    runtime_root = settings.runtime_root
    journal = RuntimeJournal(runtime_root)
    visualizer_root = ROOT / "third_party" / "ai-visualizer"
    server_path = visualizer_root / "server.py"
    if not server_path.is_file():
        raise RuntimeError("ai-visualizer is not installed; run `python scripts/bootstrap_third_party.py` first")

    visualizer_port = int(os.getenv("JARVIS_VISUALIZER_PORT", "8790"))
    ui_port = int(os.getenv("JARVIS_UI_PORT", "17654"))
    config = {
        "name": "JARVIS",
        "badge": "MVP",
        "face": "board",
        "port": visualizer_port,
        "bus_dir": str(runtime_root.resolve()),
        "thinking_sound": True,
    }
    (visualizer_root / "ai-visualizer.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    visualizer_env = os.environ.copy()
    visualizer_env.pop("OPENAI_API_KEY", None)
    visualizer_env.pop("PORCUPINE_ACCESS_KEY", None)
    visualizer = await asyncio.create_subprocess_exec(
        sys.executable,
        "server.py",
        "--no-open",
        cwd=str(visualizer_root),
        env=visualizer_env,
    )
    visualizer_url = f"http://127.0.0.1:{visualizer_port}/faces/board/"
    control = ControlCenter(runtime_root=runtime_root, project_root=ROOT, visualizer_url=visualizer_url)
    await control.start(port=ui_port)
    url = f"http://127.0.0.1:{ui_port}/"
    print(f"Jarvis Control Center ready on {url}")
    journal.emit("ui.visualizer", "ai-visualizer launched", data={"url": visualizer_url, "pid": visualizer.pid})
    try:
        await asyncio.sleep(0.5)
        webbrowser.open(url)
        waiter = asyncio.create_task(visualizer.wait(), name="jarvis-visualizer-wait")
        stop = asyncio.create_task(asyncio.Event().wait(), name="jarvis-control-center-wait")
        done, pending = await asyncio.wait({waiter, stop}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if waiter in done and visualizer.returncode not in (None, 0):
            raise RuntimeError(f"ai-visualizer exited with code {visualizer.returncode}")
        return 0
    finally:
        await control.stop()
        if visualizer.returncode is None:
            visualizer.terminate()
            try:
                await asyncio.wait_for(visualizer.wait(), timeout=3)
            except asyncio.TimeoutError:
                visualizer.kill(); await visualizer.wait()


async def _voice_timeout_loop(voice) -> None:
    while True:
        await asyncio.sleep(1.0)
        await voice.check_timeout()


async def _amain(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = args.command or "health"
    if command == "core": return await _run_core_v2()
    if command == "voice": return await _run_voice_v2()
    if command == "control-center": return await _run_control_center_v2()
    config = AppConfig.load(args.config)
    if command == "run": return await _run_voice(config, no_preflight=args.no_preflight)
    if command == "text": return await _run_text(config, message=args.message)
    if command == "health": return await _health(config, skip_audio=getattr(args, "skip_audio", False))
    if command == "reindex": return await _reindex(config)
    raise AssertionError(command)


def main() -> None:
    try:
        raise SystemExit(asyncio.run(_amain()))
    except JarvisError as exc:
        print(f"Jarvis: {exc}", file=sys.stderr); raise SystemExit(2) from None
    except RuntimeError as exc:
        print(f"Jarvis: {exc}", file=sys.stderr); raise SystemExit(2) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
