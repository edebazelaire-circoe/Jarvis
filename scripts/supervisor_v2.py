#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]


class Supervisor:
    def __init__(self) -> None:
        self.children: dict[str, asyncio.subprocess.Process] = {}
        self.stopping = False

    async def spawn(self, role: str, *args: str) -> asyncio.subprocess.Process:
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", "jarvis", *args, cwd=ROOT, env=os.environ.copy())
        self.children[role] = process
        return process

    async def wait_core_ready(self, *, timeout_s: float = 30.0) -> None:
        from jarvis.protocol.client import LocalCoreClient
        from jarvis.v2_config import V2Settings
        settings = V2Settings.load()
        deadline = asyncio.get_running_loop().time() + timeout_s
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            core = self.children.get("core")
            if core is not None and core.returncode is not None:
                raise RuntimeError(f"Core exited before readiness with code {core.returncode}")
            if settings.token_file.exists():
                client = LocalCoreClient(host=settings.core_host, port=settings.core_port, token=settings.token_file.read_text(encoding="utf-8").strip())
                try:
                    if (await client.health()).get("ready"):
                        return
                except Exception as exc:
                    last_error = exc
                finally:
                    await client.close()
            await asyncio.sleep(0.25)
        raise RuntimeError(f"Core readiness timeout: {last_error or 'no healthy response'}")

    async def run(self) -> int:
        await self.spawn("core", "core")
        await self.wait_core_ready()
        backoff = 1.0
        while not self.stopping:
            voice = await self.spawn("voice", "voice")
            waiter = asyncio.create_task(voice.wait())
            core_waiter = asyncio.create_task(self.children["core"].wait())
            done, pending = await asyncio.wait({waiter, core_waiter}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if core_waiter in done:
                return int(core_waiter.result() or 1)
            if self.stopping:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8.0)
        return 0

    async def stop(self) -> None:
        self.stopping = True
        processes = tuple(self.children.values())
        for process in processes:
            if process.returncode is None:
                process.terminate()
        if processes:
            try:
                await asyncio.wait_for(asyncio.gather(*(p.wait() for p in processes), return_exceptions=True), 8)
            except asyncio.TimeoutError:
                for process in processes:
                    if process.returncode is None:
                        process.kill()
                await asyncio.gather(*(p.wait() for p in processes), return_exceptions=True)


async def main() -> int:
    supervisor = Supervisor()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(supervisor.stop()))
        except (NotImplementedError, RuntimeError):
            pass
    try:
        return await supervisor.run()
    finally:
        await supervisor.stop()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
