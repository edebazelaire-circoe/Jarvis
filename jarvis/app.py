from __future__ import annotations

import argparse
import asyncio
import json
import sys

from jarvis.adapters.barehands_board import BarehandsBoardClient
from jarvis.audio.capture import SoundDeviceRecorder
from jarvis.audio.ptt import PTTKeyListener
from jarvis.config import AppConfig
from jarvis.domain.errors import JarvisError
from jarvis.runtime.factory import create_runtime
from jarvis.runtime.health import run_health_checks
from jarvis.runtime.voice import VoiceRuntime
from jarvis.security.session_token import generate_session_token


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="Jarvis V1 local assistant")
    parser.add_argument("--config", help="Path to jarvis.toml")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run push-to-talk voice loop")
    run.add_argument("--no-preflight", action="store_true", help="Skip microphone preflight")

    text = sub.add_parser("text", help="Run one text turn without audio playback")
    text.add_argument("message")

    health = sub.add_parser("health", help="Print local component health as JSON")
    health.add_argument("--skip-audio", action="store_true")

    sub.add_parser("reindex", help="Rebuild the disposable Markdown search index")
    return parser


async def _run_voice(config: AppConfig, *, no_preflight: bool) -> int:
    runtime = create_runtime(config, speech_enabled=True)
    if not no_preflight:
        runtime.recorder.preflight()
    await runtime.state.initialize()
    voice = VoiceRuntime(
        recorder=runtime.recorder,
        transcriber=runtime.transcriber,
        orchestrator=runtime.orchestrator,
        logger=runtime.logger,
    )
    ptt = PTTKeyListener(
        config.runtime.ptt_key,
        on_press=voice.press,
        on_release=voice.release,
    )
    print(f"Jarvis V1 prêt. Maintenez {config.runtime.ptt_key.upper()} pour parler. Ctrl+C pour quitter.")
    try:
        await ptt.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        ptt.stop()
        runtime.recorder.abort()
        await runtime.state.cleanup()
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
    recorder = SoundDeviceRecorder(
        sample_rate=config.audio.sample_rate,
        channels=config.audio.channels,
        input_device=config.audio.input_device,
    )
    report = await run_health_checks(
        config,
        board=board,
        check_audio=not skip_audio,
        recorder=recorder,
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 1 if report.status == "fail" else 0


async def _reindex(config: AppConfig) -> int:
    from jarvis.adapters.markdown_memory import MarkdownMemoryBackend

    memory = MarkdownMemoryBackend(config.runtime.memory_dir)
    count = await memory.rebuild_index()
    print(f"Index reconstruit depuis Markdown: {count} document(s).")
    return 0


async def _amain(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = AppConfig.load(args.config)
    command = args.command or "health"
    if command == "run":
        return await _run_voice(config, no_preflight=args.no_preflight)
    if command == "text":
        return await _run_text(config, args.message)
    if command == "health":
        return await _health(config, skip_audio=getattr(args, "skip_audio", False))
    if command == "reindex":
        return await _reindex(config)
    raise AssertionError(command)


def main() -> None:
    try:
        raise SystemExit(asyncio.run(_amain()))
    except JarvisError as exc:
        print(f"Jarvis: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
