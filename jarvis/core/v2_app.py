from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.v2_services import ConversationService, CoreEventBus, SchedulerService
from jarvis.domain.v2 import Device


@dataclass(slots=True)
class CoreHealth:
    ready: bool = False
    status: str = "starting"
    detail: str = ""


class JarvisCoreApplication:
    """Long-lived provider-neutral v0.2 application container."""

    def __init__(self, *, data_root: Path) -> None:
        root = Path(data_root).resolve()
        self.state = SQLiteStateRepository(root / "state" / "jarvis.sqlite3")
        self.history = JsonlHistoryStore(root / "history")
        self.events = CoreEventBus()
        self.conversations = ConversationService(self.state, self.history)
        self.scheduler = SchedulerService(self.state, self.events)
        self.health = CoreHealth()
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        try:
            await self.state.initialize()
            await self.state.save_device(Device())
            await self.scheduler.start()
            self.health.ready = True
            self.health.status = "ok"
        except Exception as exc:
            self.health.ready = False
            self.health.status = "fail"
            self.health.detail = f"{type(exc).__name__}: {exc}"
            raise

    async def stop(self) -> None:
        self.health.ready = False
        self.health.status = "stopping"
        await self.scheduler.stop()
        await self.state.close()
        self.health.status = "stopped"
        self._stopped.set()

    async def wait(self) -> None:
        await self._stopped.wait()
