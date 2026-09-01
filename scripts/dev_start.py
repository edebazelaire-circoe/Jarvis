#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import webbrowser
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
THIRD_PARTY = ROOT / "third_party"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _without_provider_secrets(env: dict[str, str]) -> dict[str, str]:
    clean = env.copy()
    clean.pop("OPENAI_API_KEY", None)
    clean.pop("JARVIS_BOARD_TOKEN", None)
    return clean


def _write_runtime_configs(
    *,
    board: bool,
    visualizer: bool,
    memory_dir: Path,
    runtime_dir: Path,
    board_port: int,
    visualizer_port: int,
) -> None:
    if board:
        barehands = THIRD_PARTY / "barehands"
        config_path = barehands / "barehands.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid Barehands config: {config_path}") from exc
            if not isinstance(config, dict):
                raise ValueError(f"invalid Barehands config object: {config_path}")
        else:
            config = {"name": "JARVIS"}

        # Jarvis owns the port and its Memory orb on every launch so a
        # changed jarvis.toml cannot be shadowed by a stale generated file.
        # Other Barehands settings/orbs are preserved for user customization.
        config["port"] = board_port
        existing_orbs = config.get("orbs")
        if not isinstance(existing_orbs, list):
            existing_orbs = []
        memory_orb = {
            "title": "Memory",
            "path": str(memory_dir.resolve()),
            "kind": "notes",
            "jarvis_managed": True,
        }
        merged_orbs = []
        memory_written = False
        media_present = False
        for orb in existing_orbs:
            if not isinstance(orb, dict):
                continue
            is_managed_memory = bool(orb.get("jarvis_managed")) or (
                orb.get("kind") == "notes" and orb.get("title") == "Memory"
            )
            if is_managed_memory and not memory_written:
                merged_orbs.append(memory_orb)
                memory_written = True
                continue
            if orb.get("kind") == "media":
                media_present = True
            merged_orbs.append(orb)
        if not memory_written:
            merged_orbs.insert(0, memory_orb)
        if not media_present:
            merged_orbs.append({"title": "Props", "path": "media", "kind": "media"})
        config["orbs"] = merged_orbs
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    if visualizer:
        visualizer_root = THIRD_PARTY / "ai-visualizer"
        config = {
            "name": "JARVIS",
            "badge": "V1",
            "face": "board",
            "port": visualizer_port,
            "bus_dir": str(runtime_dir.resolve()),
            "thinking_sound": True,
        }
        (visualizer_root / "ai-visualizer.json").write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )


def _spawn(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    kwargs = {
        "cwd": str(cwd),
        "env": env,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch Jarvis V1 and optional local UI components")
    parser.add_argument("--no-board", action="store_true")
    parser.add_argument("--no-visualizer", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--no-preflight", action="store_true")
    parser.add_argument("--config", help="Path to jarvis.toml")
    args = parser.parse_args()

    from jarvis.config import AppConfig
    from jarvis.domain.errors import ConfigurationError

    try:
        config = AppConfig.load(args.config)
    except ConfigurationError as exc:
        raise SystemExit(f"Jarvis configuration error: {exc}") from None

    board_requested = config.board.enabled and not args.no_board
    visualizer_requested = config.visualizer.enabled and not args.no_visualizer

    if not (THIRD_PARTY / "INSTALL-STATE.json").is_file() and (board_requested or visualizer_requested):
        raise SystemExit("Third-party components are not installed. Run: python scripts/bootstrap_third_party.py")

    if board_requested or visualizer_requested:
        verify_env = _without_provider_secrets(os.environ.copy())
        verify = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "bootstrap_third_party.py"), "--verify"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            env=verify_env,
            check=False,
        )
        if verify.returncode:
            raise SystemExit("Third-party integrity verification failed; refusing to launch UI components.")

    from jarvis.security.session_token import generate_session_token

    env = os.environ.copy()
    session_token = generate_session_token()
    env["JARVIS_BAREHANDS_DIR"] = str((THIRD_PARTY / "barehands").resolve())
    env["JARVIS_BOARD_ENABLED"] = "true" if board_requested else "false"
    env["JARVIS_VISUALIZER_ENABLED"] = "true" if visualizer_requested else "false"
    if args.config:
        env["JARVIS_CONFIG"] = str(Path(args.config).expanduser().resolve())
    env.setdefault("PYTHONUNBUFFERED", "1")

    board_enabled = board_requested and (THIRD_PARTY / "barehands" / "server.py").is_file()
    visualizer_enabled = visualizer_requested and (THIRD_PARTY / "ai-visualizer" / "server.py").is_file()
    board_port = urlparse(config.board.url).port or 80
    visualizer_port = urlparse(config.visualizer.url).port or 80
    try:
        _write_runtime_configs(
            board=board_enabled,
            visualizer=visualizer_enabled,
            memory_dir=config.runtime.memory_dir,
            runtime_dir=config.runtime.runtime_dir,
            board_port=board_port,
            visualizer_port=visualizer_port,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Unable to prepare local UI configuration: {exc}") from None

    children: list[subprocess.Popen] = []
    try:
        if board_enabled:
            board_env = _without_provider_secrets(env)
            board_env["JARVIS_BOARD_TOKEN"] = session_token
            children.append(
                _spawn([sys.executable, "server.py"], cwd=THIRD_PARTY / "barehands", env=board_env)
            )
        if visualizer_enabled:
            visualizer_env = _without_provider_secrets(env)
            children.append(
                _spawn(
                    [sys.executable, "server.py", "--no-open"],
                    cwd=THIRD_PARTY / "ai-visualizer",
                    env=visualizer_env,
                )
            )
        time.sleep(0.6)
        for child in list(children):
            if child.poll() not in (None, 0):
                print(f"Optional UI process exited early with code {child.returncode}; voice will continue.", file=sys.stderr)

        if not args.no_open:
            if visualizer_enabled:
                webbrowser.open(f"{config.visualizer.url}/faces/board/")
            if board_enabled:
                webbrowser.open(f"{config.board.url}/stage.html")

        jarvis_cmd = [sys.executable, "-m", "jarvis", "run"]
        if args.no_preflight:
            jarvis_cmd.append("--no-preflight")
        jarvis_env = env.copy()
        jarvis_env["JARVIS_BOARD_TOKEN"] = session_token
        jarvis = _spawn(jarvis_cmd, cwd=ROOT, env=jarvis_env)
        children.append(jarvis)
        warned: set[int] = set()
        while jarvis.poll() is None:
            for child in children[:-1]:
                code = child.poll()
                if code is not None and child.pid not in warned:
                    warned.add(child.pid)
                    print(
                        f"Optional UI process {child.pid} exited with code {code}; voice continues.",
                        file=sys.stderr,
                    )
            time.sleep(0.5)
        raise SystemExit(jarvis.returncode or 0)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    finally:
        for child in reversed(children):
            _terminate(child)


if __name__ == "__main__":
    main()
