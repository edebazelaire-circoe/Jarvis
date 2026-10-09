"""Wiring of the knowledge loadouts into Core (handoff jarvis-memory-intelligence-knowledge, Slice 09, integration step).

Core imports no adapter and no runtime module, so this runtime-layer module builds the Wiki and Skills providers,
the `KnowledgeLoadoutResolver`, hands them to the `MemoryWiring` (`register_knowledge`, `set_loadout_resolver`) and
keeps the hook snapshot (`runtime/loadout-snapshot.json`) current: written at start-up, then re-written by a
light poll whenever the rendered loadouts differ (a skill enabled, a wiki page imported, `memory.loadouts` edited,
by whichever process did it). Contract page: `docs/skills-and-loadouts.md`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from jarvis.adapters.knowledge_skills import SkillRegistry
from jarvis.adapters.knowledge_wiki import WikiProvider
from jarvis.core.loadout_resolver import KnowledgeLoadoutResolver, register_knowledge
from jarvis.core.memory_wiring import MemoryWiring
from jarvis.domain.loadout_view import render_manifest
from jarvis.domain.memory import MemoryStoreError
from jarvis.ports.v2 import DiagnosticSink
from jarvis.runtime.loadout_snapshot import snapshot_path, write_loadout_snapshot
from jarvis.runtime.memory_settings import SETTING_KEY, read_loadout_policy, read_memory_settings

_LOG = logging.getLogger(__name__)
#: Seconds between two checks for a change of skills, wiki pages or loadout rules.
DEFAULT_POLL_S = 15.0


class LoadoutSnapshotKeeper:
    """Writes the snapshot when what it would hold changed. `refresh()` is also the manual trigger after a change."""

    def __init__(self, resolver: KnowledgeLoadoutResolver, runtime_root: Path, *,
                 diagnostics: DiagnosticSink | None = None, poll_s: float = DEFAULT_POLL_S) -> None:
        self._resolver = resolver
        self._root = Path(runtime_root)
        self._diagnostics = diagnostics
        self._poll_s = poll_s
        self._signature: str | None = None
        self._task: asyncio.Task[None] | None = None

    def refresh(self) -> bool:
        """True when the file was (re)written. Never raises: a refusal is journaled as `loadout_snapshot_failed`."""

        try:
            views = self._resolver.explain_all()
            signature = json.dumps({k: [render_manifest(v), v.as_dict()] for k, v in views.items()},
                                   sort_keys=True, ensure_ascii=False, default=str)
            if signature == self._signature and snapshot_path(self._root).is_file():
                return False
            write_loadout_snapshot(self._root, views)
            self._signature = signature
            return True
        except Exception as exc:  # noqa: BLE001 - the snapshot is a courtesy to the hook; a sub-agent then gets no manifest
            _LOG.warning("loadout snapshot not written: %s", type(exc).__name__)
            if self._diagnostics is not None:
                self._diagnostics.emit("agent.loadout.failed", "Instantané des loadouts non écrit", level="warning",
                                       data={"code": "loadout_snapshot_failed", "exception_type": type(exc).__name__})
            return False

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._poll(), name="loadout-snapshot-keeper")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _poll(self) -> None:
        while True:
            await asyncio.sleep(self._poll_s)
            await asyncio.to_thread(self.refresh)


def _memory_block(wiring: MemoryWiring) -> Any:
    try:
        raw = wiring.settings.raw() if wiring.settings is not None else {}
    except Exception:  # noqa: BLE001 - tolerant reader: no settings means presets
        return None
    return raw.get(SETTING_KEY) if isinstance(raw, dict) else None


def wire_knowledge(wiring: MemoryWiring, data_root: Path, runtime_root: Path, *,
                   diagnostics: DiagnosticSink | None = None, project_id: str | None = None,
                   poll_s: float = DEFAULT_POLL_S) -> LoadoutSnapshotKeeper | None:
    """Build the providers under `<data_root>/knowledge`, install the resolver and write the first snapshot.

    `None` when memory is unavailable. A provider whose root is refused is left out (its kind is then absent from
    every loadout); the other kinds stay.
    """

    if wiring.service is None:
        return None
    root = Path(data_root) / "knowledge"
    providers: dict[str, Any] = {}
    for name, factory in (("wiki", lambda: WikiProvider(root / "wiki")), ("skills", lambda: SkillRegistry(root / "skills"))):
        try:
            providers[name] = factory()
        except (MemoryStoreError, OSError) as exc:
            _LOG.warning("knowledge %s not mounted: %s", name, type(exc).__name__)
    resolver = register_knowledge(
        wiki=providers.get("wiki"), skills=providers.get("skills"),
        policy=lambda: read_loadout_policy(_memory_block(wiring)),
        knowledge=lambda: read_memory_settings(_memory_block(wiring)).knowledge,
        project_id=project_id)
    for provider in (providers.get("wiki"), providers.get("skills")):
        if provider is not None:
            wiring.register_knowledge(provider)
    wiring.set_loadout_resolver(resolver)
    keeper = LoadoutSnapshotKeeper(resolver, runtime_root, diagnostics=diagnostics, poll_s=poll_s)
    keeper.refresh()
    wiring.lifecycle.append(keeper)
    return keeper
