from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from jarvis.runtime.journal import RuntimeJournal


class ClaudeLocalAgent:
    def __init__(self, *, runtime_root: Path, cwd: Path, command: str = "claude") -> None:
        self.runtime_root = runtime_root
        self.cwd = cwd
        self.command = command
        self.journal = RuntimeJournal(runtime_root)
        self.process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._events: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        if self.process is None:
            return "stopped"
        if self.process.returncode is None:
            return "running"
        return "exited"

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": "Claude",
            "state": self.state,
            "pid": self.process.pid if self.process and self.process.returncode is None else None,
            "returncode": self.process.returncode if self.process else None,
            "events": self._events[-80:],
        }

    async def start(self) -> dict[str, Any]:
        async with self._lock:
            if self.process is not None and self.process.returncode is None:
                return self.snapshot()
            env = os.environ.copy()
            env.setdefault("PYTHONUNBUFFERED", "1")
            try:
                self.process = await asyncio.create_subprocess_exec(
                    self.command,
                    "-p",
                    "--input-format",
                    "stream-json",
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    cwd=str(self.cwd),
                    env=env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                self.journal.emit("agent.start", "Claude CLI not found", level="error", data={"command": self.command})
                raise RuntimeError("Claude CLI not found; install Claude Code and ensure `claude` is in PATH") from exc
            self.journal.emit("agent.start", "Claude local agent started", data={"pid": self.process.pid})
            self._reader_task = asyncio.create_task(self._read_stdout(), name="jarvis-claude-stdout")
            self._stderr_task = asyncio.create_task(self._read_stderr(), name="jarvis-claude-stderr")
            return self.snapshot()

    async def send(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise ValueError("message cannot be empty")
        if self.process is None or self.process.returncode is not None:
            await self.start()
        assert self.process is not None and self.process.stdin is not None
        payload = {"type": "user", "message": {"role": "user", "content": text}}
        self.process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await self.process.stdin.drain()
        self.journal.emit("agent.input", text)
        return self.snapshot()

    async def restart(self) -> dict[str, Any]:
        await self.stop()
        return await self.start()

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            process = self.process
            if process is None:
                return self.snapshot()
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            for task in (self._reader_task, self._stderr_task):
                if task is not None:
                    task.cancel()
            await asyncio.gather(*(t for t in (self._reader_task, self._stderr_task) if t is not None), return_exceptions=True)
            self._reader_task = self._stderr_task = None
            self.journal.emit("agent.stop", "Claude local agent stopped", data={"returncode": process.returncode})
            return self.snapshot()

    async def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        while True:
            raw = await self.process.stdout.readline()
            if not raw:
                break
            text = raw.decode("utf-8", errors="replace").rstrip()
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                event = {"type": "stdout", "text": text}
            if isinstance(event, dict):
                self._events.append(event)
                if len(self._events) > 500:
                    del self._events[:-500]
                self.journal.emit("agent.event", str(event.get("type") or "event"), data=event)
        if self.process is not None:
            await self.process.wait()
            self.journal.emit("agent.exit", "Claude local agent exited", level="error" if self.process.returncode else "info", data={"returncode": self.process.returncode})

    async def _read_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        while True:
            raw = await self.process.stderr.readline()
            if not raw:
                break
            text = raw.decode("utf-8", errors="replace").rstrip()
            self._events.append({"type": "stderr", "text": text})
            self.journal.emit("agent.stderr", text, level="error")
