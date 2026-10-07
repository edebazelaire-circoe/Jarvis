"""Per-turn memory block of the Brain context (handoff jarvis-memory-intelligence-knowledge, Slice 05).

Same pattern as `jarvis/core/board_hydration.py`: a never-raising, bounded
builder. `MemoryTurnContext` is the `memory_context` callable of
`BrainOrchestrator`: `turn -> BrainMemoryContext | None`.

- **Query** (`build_query`): the user's utterance, plus at most one recent user
  turn when the utterance is under `SHORT_UTTERANCE_WORDS` words (it resolves
  pronouns). No LLM call: the latency is fixed. The query is never logged, never
  put in a diagnostic and never in the block.
- **Settings**: `CachedMemorySettings` re-reads `control-center-settings.json`
  at most every 2 s and only parses again when the file changed, so
  `memory.recall.enabled=false` (or a new timeout) applies from the next turn,
  without a restart. `recall.enabled=false` turns the whole block off (no
  profile either): the turn context is the one from before, byte for byte.
- **Time**: blocking disk I/O runs in a thread; the whole build runs under
  `asyncio.wait_for(recall.timeout_ms)`. The retriever gets 50 ms less than that
  wall clock so that it answers with its partial result (and its `degraded`
  codes) before the backstop cancels the build; the backstop gives the
  `recall_timeout` degraded block. A turn is never held longer than the setting.
- **Failure**: a store that is missing, refused or slow degrades the block
  (`store_unavailable`, `recall_timeout`, `index_syncing`...); a defect inside
  the build gives `error=memory_failed`. Either way the turn proceeds.
- **Budgets**: `BrainMemoryContext.bounded` (2 048 profile, 6 items of 400
  characters, 3 000 recall, 1 024 manifest, 6 000 block).

Contract page: `docs/memory.md` (Injection into the Brain context).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import json
import logging
from pathlib import Path
import time
from typing import Any

from jarvis.core.memory_service import MemoryService, TurnRecall
from jarvis.domain.brain_context import (
    MAX_BRAIN_MEMORY_ITEM_CHARS,
    MAX_BRAIN_MEMORY_RECALL_ITEMS,
    BrainMemoryContext,
    BrainMemoryItem,
)
from jarvis.domain.knowledge import Loadout
from jarvis.domain.memory import (
    MAX_QUERY_CHARS,
    MemoryNote,
    RecallBudget,
)
from jarvis.domain.memory_leg import provenance_ref
from jarvis.domain.memory_settings import KnowledgeSettings, MemorySettings
from jarvis.domain.v2 import BrainTurnInput, BrainTurnSource
from jarvis.domain.work_state import clip_text

_LOG = logging.getLogger("jarvis")

#: An utterance under this many words borrows the previous user turn to resolve its pronouns.
SHORT_UTTERANCE_WORDS = 8
#: Characters of the borrowed turn: it only needs to name its subject.
RECENT_TURN_CHARS = 300
#: Settings are looked at most this often (seconds), architecture 2.10.
SETTINGS_REFRESH_S = 2.0
#: The retriever's wall clock is this much shorter than the build's backstop (seconds).
RETRIEVER_MARGIN_S = 0.05
#: Stable codes of `BrainMemoryContext.error` and of the degraded block.
ERROR_MEMORY_FAILED = "memory_failed"
DEGRADED_RECALL_TIMEOUT = "recall_timeout"
DEGRADED_STORE_UNAVAILABLE = "store_unavailable"

RecentTurn = Callable[[BrainTurnInput], Awaitable[str]]


class CachedMemorySettings:
    """`MemorySettings` of the settings file, re-read at most every `SETTINGS_REFRESH_S`, parsed again only on change.

    `read` turns the whole settings file into `MemorySettings` (injected: `core` does
    not import the runtime layer; `jarvis.runtime.memory_settings.read_memory_settings_file`).
    `current()` is synchronous and blocking (a `stat`, rarely a read): call it in
    a thread. It never raises: an unreadable file keeps the last good value, or
    the defaults on first read (`read` is tolerant by contract).
    `raw()` is the whole settings file (credentials are read from it by the
    embedder), under the same cache.
    """

    def __init__(self, path: Path, read: Callable[[Mapping[str, Any]], MemorySettings], *,
                 clock: Callable[[], float] = time.monotonic, refresh_s: float = SETTINGS_REFRESH_S) -> None:
        self._path = Path(path)
        self._read = read
        self._clock = clock
        self._refresh_s = refresh_s
        self._checked: float | None = None
        self._stamp: tuple[int, int] | None = None
        self._raw: dict[str, Any] = {}
        self._value: MemorySettings = read({})

    def current(self) -> MemorySettings:
        self._refresh()
        return self._value

    def raw(self) -> dict[str, Any]:
        self._refresh()
        return self._raw

    def _refresh(self) -> None:
        now = self._clock()
        if self._checked is not None and 0 <= now - self._checked < self._refresh_s:
            return
        self._checked = now
        try:
            stat = self._path.stat()
        except FileNotFoundError:
            # intentional: no settings file is the normal first run; the defaults apply.
            stamp = None
        except OSError as exc:
            _LOG.warning("memory settings file not readable: %s", type(exc).__name__)
            return
        else:
            stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp == self._stamp:
            return
        raw: dict[str, Any] = {}
        if stamp is not None:
            try:
                loaded = json.loads(self._path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                _LOG.warning("memory settings file not parsed: %s", type(exc).__name__)
                return  # the previous good value stays; the next refresh retries
            raw = loaded if isinstance(loaded, dict) else {}
        self._stamp, self._raw = stamp, raw
        self._value = self._read(raw)


def build_query(text: str, recent: str = "") -> str:
    """The recall query: the utterance, preceded by one recent turn when the utterance is short. No LLM, no I/O."""

    utterance = text.strip()
    previous = clip_text(recent, RECENT_TURN_CHARS) if recent.strip() else ""
    if previous and len(utterance.split()) < SHORT_UTTERANCE_WORDS:
        utterance = f"{previous} {utterance}"
    return utterance[:MAX_QUERY_CHARS]


def render_knowledge_manifest(loadout: Loadout, settings: KnowledgeSettings) -> str:
    """Names and ids of what the Brain's loadout offers (never bodies); only the kinds the settings leave on."""

    parts: list[str] = []
    for label, enabled, ids in (
        ("wiki", settings.wiki_enabled, loadout.wiki_ids),
        ("codegraph", settings.codegraph_enabled, loadout.codegraph_repos),
        ("skills", settings.skills_enabled, loadout.skill_ids),
    ):
        if enabled and ids:
            parts.append(f"{label}: {', '.join(ids)}")
    return "; ".join(parts)


def render_profile(notes: tuple[MemoryNote, ...]) -> str:
    """The stable block: one line per note, newest first, each with its canonical address and revision."""

    lines = []
    for note in notes:
        body = " ".join(note.body.split())
        lines.append(f"- {note.title} [{provenance_ref(note.retention, note.id)} r{note.revision}]: {body}")
    return "\n".join(lines)


class MemoryTurnContext:
    """`BrainOrchestrator`'s `memory_context`: `turn -> BrainMemoryContext | None`. Never raises (but cancellation)."""

    def __init__(self, service: MemoryService | None, settings: CachedMemorySettings, *,
                 recent_turn: RecentTurn | None = None, unavailable: str | None = None) -> None:
        self._service = service
        self._settings = settings
        self._recent_turn = recent_turn
        self._unavailable = unavailable

    def bind_recent_turn(self, recent_turn: RecentTurn) -> None:
        """Late binding: the lookup needs Core's conversations, built after the wiring."""

        self._recent_turn = recent_turn

    async def __call__(self, turn: BrainTurnInput) -> BrainMemoryContext | None:
        if turn.source is BrainTurnSource.SYSTEM:
            return None  # a turn Core opens itself is not the user speaking: nothing to recall
        started = time.perf_counter()
        try:
            settings = await asyncio.to_thread(self._settings.current)
        except Exception as exc:  # noqa: BLE001 - never-raising builder: the failure is the block's error, said by the caller
            return self._failed(started, exc)
        if not settings.recall.enabled:
            return None
        budget = self._budget(settings.recall.timeout_ms, settings.recall.max_items)
        try:
            return await asyncio.wait_for(self._build(turn, settings, budget), settings.recall.timeout_ms / 1000)
        except asyncio.TimeoutError:
            return BrainMemoryContext.bounded(degraded=(DEGRADED_RECALL_TIMEOUT,),
                                              timings_ms={"total": _ms(started)})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - never-raising builder: a defect gives an error block, the turn leaves anyway
            return self._failed(started, exc)

    @staticmethod
    def _budget(timeout_ms: int, max_items: int) -> RecallBudget:
        wall = max(100, timeout_ms - int(RETRIEVER_MARGIN_S * 1000))
        return RecallBudget(max_items=min(max_items, MAX_BRAIN_MEMORY_RECALL_ITEMS),
                            max_item_chars=MAX_BRAIN_MEMORY_ITEM_CHARS, timeout_ms=wall)

    def _failed(self, started: float, exc: BaseException) -> BrainMemoryContext:
        # Type and stable code only: a message can carry a path, and the query never leaves the builder.
        code = str(getattr(getattr(exc, "code", None), "value", None) or ERROR_MEMORY_FAILED)[:64]
        _LOG.warning("memory context failed: %s (%s)", type(exc).__name__, code)
        return BrainMemoryContext.bounded(error=code, timings_ms={"total": _ms(started)})

    async def _build(self, turn: BrainTurnInput, settings: MemorySettings, budget: RecallBudget) -> BrainMemoryContext:
        started = time.perf_counter()
        if self._service is None:
            return BrainMemoryContext.bounded(degraded=(self._unavailable or DEGRADED_STORE_UNAVAILABLE,))
        recent = ""
        if self._recent_turn is not None and len(turn.text.split()) < SHORT_UTTERANCE_WORDS:
            try:
                recent = await self._recent_turn(turn)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the previous turn only sharpens the query: without it, recall goes on
                _LOG.warning("memory recall query without the previous turn: %s", type(exc).__name__)
        query = build_query(turn.text, recent)
        recalled, loadout = await asyncio.gather(
            self._service.recall_for_turn(query, budget),
            asyncio.to_thread(self._manifest, settings.knowledge),
        )
        return self._block(recalled, loadout, budget, started)

    def _manifest(self, knowledge: KnowledgeSettings) -> str:
        if self._service is None:
            return ""
        try:
            return render_knowledge_manifest(self._service.knowledge_loadout(), knowledge)
        except Exception as exc:  # noqa: BLE001 - the manifest is a convenience: a failing resolver costs the line, not the turn
            _LOG.warning("memory knowledge manifest failed: %s", type(exc).__name__)
            return ""

    @staticmethod
    def _block(recalled: TurnRecall, manifest: str, budget: RecallBudget, started: float) -> BrainMemoryContext:
        items = tuple(BrainMemoryItem.bounded(
            memory_id=item.memory_id, title=item.title, text=item.snippet, level=item.level.value,
            retention=item.retention.value, source=item.provenance_ref, revision=item.revision, why=item.why)
            for item in recalled.result.items)
        timings = {**dict(recalled.result.timings_ms), "build": _ms(started)}
        return BrainMemoryContext.bounded(
            profile=render_profile(recalled.profile), recall=items,
            knowledge_manifest=manifest, degraded=recalled.degraded, max_items=budget.max_items, timings_ms=timings)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
