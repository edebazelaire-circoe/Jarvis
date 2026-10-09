"""Memory facade of Core: store + retriever + policy + budgets (handoff jarvis-memory-intelligence-knowledge, Slice 05).

`MemoryService` is the one object Core talks to for memory. It owns no
persistence: the canonical store (Markdown, `jarvis/adapters/markdown_memory.py`)
and the retriever (`jarvis/core/memory_hybrid.py`) are injected by
`jarvis/core/memory_wiring.py`, so `core` imports ports and pure code only.

Two readers use it:

- the per-turn context builder (`jarvis/core/memory_context.py`) through
  `recall_for_turn`: the stable profile (L3, plus L2 notes of kind `profile`)
  and the dynamic recall, run concurrently, under the scopes the Brain policy
  grants (deny by scope: no readable scope, no recall);
- the read routes (`jarvis/protocol/memory_routes.py`): list, get, search,
  status, recall explanation. Those serve the owner (the Memory Center) and are
  not narrowed by the Brain policy; `recall_explain` is, because it answers
  "what would the Brain have been given".

Synchronous store calls run on the service's own two threads (a hung call is
skipped, never queued, and never starves the loop's executor). The service never
logs a query. While the store's start-up index sync runs (about 1.3 s warm /
10 s cold for 2 000 notes, amendment A2) a turn recall is reported degraded
(`index_syncing`) instead of waiting. The profile is canonical and independent of
the recall legs: a recall timeout or an unready index never costs it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging
import threading
from typing import Any

from jarvis.domain.errors import MemorySecurityError
from jarvis.core.loadout_resolver import preset_rule
from jarvis.domain.knowledge import Loadout
from jarvis.domain.memory import (
    MAX_SNIPPET_CHARS,
    CapabilityState,
    CapabilityStatus,
    DegradedReason,
    MemoryErrorCode,
    MemoryFilters,
    MemoryKind,
    MemoryLevel,
    MemoryNote,
    MemoryStoreError,
    RecallBudget,
    RecallQuery,
    RecallResult,
)
from jarvis.domain.memory_leg import is_valid_at
from jarvis.domain.memory_settings import BRAIN_PROFILE
from jarvis.domain.memory_policy import AgentMemoryPolicy
from jarvis.ports.knowledge import LoadoutResolver, NullLoadoutResolver
from jarvis.ports.memory_retrieval import MemoryRetriever
from jarvis.ports.memory_store import CanonicalMemoryStore

_LOG = logging.getLogger("jarvis")

#: Degraded codes the service adds to the retriever's `DegradedReason` values.
DEGRADED_INDEX_SYNCING = "index_syncing"
DEGRADED_PROFILE_UNAVAILABLE = "profile_unavailable"
DEGRADED_STORE_UNAVAILABLE = DegradedReason.STORE_UNAVAILABLE.value

#: Notes listed per profile query: the block holds 2 048 characters, a long list is dropped by the builder.
PROFILE_NOTE_LIMIT = 20

#: Agent id of the Brain policy.
BRAIN_AGENT_ID = "brain"


def brain_policy() -> AgentMemoryPolicy:
    """What the authoritative Brain may read: the scopes of the Brain preset of the loadout resolver.

    One source of truth (`jarvis.core.loadout_resolver.preset_rule`): the Brain preset names the private and
    the shared scope and is the only one that does. Writes nothing here.
    """

    rule = preset_rule(BRAIN_PROFILE)
    return AgentMemoryPolicy(agent_id=BRAIN_AGENT_ID, read_scopes=rule.memory_scopes, allow_private=rule.allow_private)


def canonical_text(note: MemoryNote) -> str:
    """The note's canonical body for injection: front matter is already parsed away; a leading `# <title>` line
    that repeats the title is dropped; line ends are normalised and blank runs collapsed. Dates, codes and the
    rest of the text are untouched."""

    lines = note.body.replace("\r\n", "\n").replace("\r", "\n").strip().split("\n")
    if lines and lines[0].lstrip("#").strip().casefold() == note.title.strip().casefold() and lines[0].startswith("#"):
        lines = lines[1:]
    kept: list[str] = []
    for line in lines:
        if not line.strip() and (not kept or not kept[-1].strip()):
            continue
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


@dataclass(frozen=True, slots=True)
class TurnRecall:
    """What one turn recalled: ranked items with their canonical text, and why it is partial (stable codes)."""

    result: RecallResult = field(default_factory=RecallResult)
    degraded: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TurnProfile:
    """The stable profile notes of one turn (canonical, no index needed), or why they are missing."""

    notes: tuple[MemoryNote, ...] = ()
    degraded: tuple[str, ...] = ()


class MemoryService:
    def __init__(
        self,
        store: CanonicalMemoryStore,
        retriever: MemoryRetriever,
        policy: AgentMemoryPolicy,
        *,
        loadouts: LoadoutResolver | None = None,
        index_ready: Callable[[], bool] | None = None,
        candidates: Callable[[], Sequence[Any]] | None = None,
    ) -> None:
        self.store = store
        self.retriever = retriever
        self.policy = policy
        self.loadouts: LoadoutResolver = loadouts or NullLoadoutResolver()
        self._index_ready = index_ready
        self._candidates = candidates
        self._reporters: dict[str, Callable[[], CapabilityState]] = {}
        # Own bounded threads for the profile and the canonical re-reads: a store call that hangs (disk stall,
        # start-up sync) holds one worker, never the loop's shared executor, and a next call is skipped
        # rather than queued behind it.
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="memory-service")
        self._busy = 0
        self._busy_lock = threading.Lock()
        self._turn_hooks: list[Callable[[], None]] = []

    async def _threaded(self, function: Callable[..., Any], *args: Any) -> Any:
        """`function` on the service's own threads; `MemoryStoreError(memory_unavailable)` when both are still busy."""

        with self._busy_lock:
            if self._busy >= 2:
                raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "the previous store reads are still running")
            self._busy += 1

        def release(_future: Any) -> None:
            with self._busy_lock:
                self._busy -= 1

        future = self._pool.submit(function, *args)
        future.add_done_callback(release)
        return await asyncio.wrap_future(future)

    # ------------------------------------------------------------- per turn
    def add_turn_hook(self, hook: Callable[[], None]) -> None:
        """`hook()` runs when a user turn starts (the Brain tool budget resets there, Slice 05b)."""

        self._turn_hooks.append(hook)

    def begin_turn(self) -> None:
        for hook in tuple(self._turn_hooks):
            try:
                hook()
            except Exception as exc:  # noqa: BLE001 - a hook must never cost the turn its memory block
                _LOG.warning("memory turn hook failed: %s", type(exc).__name__)

    @property
    def index_ready(self) -> bool:
        return True if self._index_ready is None else bool(self._index_ready())

    async def profile_for_turn(self) -> TurnProfile:
        """The stable profile. Canonical: it does not wait for, or depend on, the recall legs or their index
        (the adapter's `list` still waits for the start-up sync when it runs; the builder's deadline cuts it)."""

        scopes = self.policy.narrow(self.policy.read_scopes)
        if not scopes:
            return TurnProfile()
        try:
            notes = await self._threaded(self._profile_sync, scopes)
        except (MemoryStoreError, MemorySecurityError, OSError) as exc:
            _LOG.warning("memory profile unavailable: %s", type(exc).__name__)
            return TurnProfile(degraded=(DEGRADED_PROFILE_UNAVAILABLE,))
        return TurnProfile(notes=notes)

    async def recall_for_turn(self, query: str, budget: RecallBudget) -> TurnRecall:
        """Ranked items for `query`, each with its canonical text; degradation is data, nothing of the query is kept.

        An empty query (no content word) recalls nothing and is not degraded. An item needs evidence: a lexical
        or a semantic rank (a leg's own relevance floor already applied); a rank from the mirror alone is not.
        Raises only for a defect (a code bug in an adapter): the caller turns it into an error block.
        """

        scopes = self.policy.narrow(self.policy.read_scopes)
        if not scopes or not query.strip():
            return TurnRecall()
        if not self.index_ready:
            return TurnRecall(degraded=(DEGRADED_INDEX_SYNCING,))
        result, degraded = await self._recall(query, scopes, budget)
        items = tuple(item for item in result.items if "lexical" in item.rank_sources or "semantic" in item.rank_sources)
        try:
            notes = await self._threaded(self._notes, tuple(item.memory_id for item in items))
        except (MemoryStoreError, MemorySecurityError, OSError) as exc:
            _LOG.warning("memory recall canonical read unavailable: %s", type(exc).__name__)
            return TurnRecall(RecallResult(timings_ms=result.timings_ms), (*degraded, DEGRADED_STORE_UNAVAILABLE))
        kept = tuple(
            replace(item, snippet=text[:MAX_SNIPPET_CHARS])
            for item in items if (note := notes.get(item.memory_id)) is not None and (text := canonical_text(note))
        )
        return TurnRecall(RecallResult(items=kept, degraded=result.degraded, timings_ms=result.timings_ms), degraded)

    def _notes(self, memory_ids: tuple[str, ...]) -> dict[str, MemoryNote]:
        """The canonical latest revision of each id; one that vanished since the ranking is simply absent."""

        found: dict[str, MemoryNote] = {}
        for memory_id in memory_ids:
            try:
                note = self.store.get(memory_id)
            except MemoryStoreError as exc:
                if exc.code is not MemoryErrorCode.NOT_FOUND:
                    raise
                continue
            if not note.is_superseded:
                found[memory_id] = note
        return found

    async def _recall(self, query: str, scopes: tuple[str, ...], budget: RecallBudget) -> tuple[RecallResult, tuple[str, ...]]:
        try:
            result = await self.retriever.recall(RecallQuery(text=query, scopes=scopes, agent=self.policy.agent_id), budget)
        except MemoryStoreError as exc:
            _LOG.warning("memory recall unavailable: %s", exc.code.value)
            return RecallResult(), (DEGRADED_STORE_UNAVAILABLE,)
        return result, tuple(reason.value for reason in result.degraded)

    def _profile_sync(self, scopes: tuple[str, ...]) -> tuple[MemoryNote, ...]:
        l3 = self.store.list(MemoryFilters(scopes=scopes, levels=(MemoryLevel.L3,), limit=PROFILE_NOTE_LIMIT))
        l2 = self.store.list(MemoryFilters(scopes=scopes, levels=(MemoryLevel.L2,), kinds=(MemoryKind.PROFILE,),
                                           limit=PROFILE_NOTE_LIMIT))
        now = datetime.now(timezone.utc)
        notes = {note.id: note for note in (*l3, *l2)
                 if not note.is_superseded and is_valid_at(note.valid_from, note.valid_to, now)}
        return tuple(sorted(notes.values(), key=lambda note: (note.updated_at, note.id), reverse=True))

    def knowledge_loadout(self, profile: str = BRAIN_PROFILE, role: str | None = None) -> Loadout:
        """The Brain's loadout (null resolver: nothing). The resolver never raises by contract; a defect is the caller's."""

        return self.loadouts.resolve(profile, role)

    # ------------------------------------------------------------ read routes
    async def recall_explain(self, query: str, budget: RecallBudget, scopes: Sequence[str] = ()) -> tuple[RecallResult, tuple[str, ...], tuple[str, ...]]:
        """The Brain's recall of `query`, with the legs' ranks, timings and degraded codes; scopes narrowed by policy."""

        granted = self.policy.narrow(scopes or self.policy.read_scopes)
        if not granted:
            return RecallResult(), (), ()
        if not self.index_ready:
            return RecallResult(), (DEGRADED_INDEX_SYNCING,), granted
        try:
            result, degraded = await asyncio.wait_for(self._recall(query, granted, budget), budget.timeout_ms / 1000 + 0.05)
        except asyncio.TimeoutError:  # backstop: the retriever has its own wall clock, a hung adapter must not hang the route
            return RecallResult(), (DegradedReason.RECALL_TIMEOUT.value,), granted
        return result, degraded, granted

    async def get_note(self, memory_id: str) -> MemoryNote:
        return await asyncio.to_thread(self.store.get, memory_id)

    async def list_notes(self, filters: MemoryFilters) -> tuple[MemoryNote, ...]:
        return await asyncio.to_thread(self.store.list, filters)

    async def history(self, memory_id: str) -> tuple[MemoryNote, ...]:
        return await asyncio.to_thread(self.store.history, memory_id)

    async def search(self, query: str, limit: int, filters: MemoryFilters) -> list:
        """Lexical ranked search over canonical notes (the store's `search_ranked`), all scopes (owner view)."""

        return await asyncio.to_thread(self.store.search_ranked, query, limit, filters)  # type: ignore[attr-defined]

    async def candidates(self) -> list[Any]:
        """Proposed candidates; empty until the consolidation slice supplies a provider."""

        if self._candidates is None:
            return []
        return list(await asyncio.to_thread(self._candidates))

    @property
    def candidates_available(self) -> bool:
        return self._candidates is not None

    # ----------------------------------------------------------------- status
    def register_reporter(self, capability_id: str, reporter: Callable[[], CapabilityState]) -> None:
        """A leg or asset provider reports its health under `capability_id` (`lexical`, `semantic`, `tencent`, `knowledge:wiki`...)."""

        self._reporters[capability_id] = reporter

    def status(self) -> Mapping[str, CapabilityState]:
        """One state per registered reporter plus the store itself; a failing reporter is `unavailable`, never an exception."""

        states: dict[str, CapabilityState] = {"store": self._store_state()}
        for capability_id, reporter in self._reporters.items():
            try:
                states[capability_id] = reporter()
            except Exception as exc:  # noqa: BLE001 - a reporter must never take the status route down: its failure is its state
                states[capability_id] = CapabilityState(
                    CapabilityStatus.UNAVAILABLE, "status_failed", f"status probe failed: {type(exc).__name__}")
        return states

    def _store_state(self) -> CapabilityState:
        if not self.index_ready:
            return CapabilityState(CapabilityStatus.DEGRADED, DEGRADED_INDEX_SYNCING,
                                   "the start-up index sync is running: recall is skipped until it ends")
        return CapabilityState(CapabilityStatus.OK)
