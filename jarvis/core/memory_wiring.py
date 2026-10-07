"""The one composition of Core's memory (handoff jarvis-memory-intelligence-knowledge, Slice 05).

`build_memory_wiring` is the only place that builds the canonical store, the
derived semantic index, the hybrid retriever, the service and the per-turn
context builder, and the only place that knows which adapters exist: `core`
code (service, context, routes) depends on ports. `JarvisCoreApplication`
receives the result (`memory=`) and starts and stops it; `jarvis/app.py` builds
it once and hands the *same* store to `MemoryMaintenanceWorker`, so a promotion
reaches the derived index (R3) and there is one store lock per process.

Startup never blocks and never fails Core:

- the store's index sync runs in its own thread (Slice 02); until it ends a turn
  recall is reported degraded (`index_syncing`, amendment A2);
- a root that cannot be created or opened (a file in its place, a refused
  disk) gives a wiring without store: every turn carries a degraded block
  (`store_unavailable`), the routes answer `memory_unavailable`, Core starts. It
  is built again on the next start, not retried while running;
- the semantic leg exists only when `memory.semantic` is enabled with a provider
  (or an embedder is injected); its worker starts with Core (`start()`), its
  embeddings are computed in the background after every write (`notify_written`).
  Turning semantic recall on or off, or changing its provider, applies at the
  next start (recall budgets, `recall.enabled` and the knowledge toggles apply at
  the next turn).

The concrete adapters are injected (`MemoryAdapters`): `core` imports none, as the architecture gate
(`tests/unit/test_v2_architecture.py`) requires. `jarvis/runtime/memory_composition.py` binds the real ones.

Hooks the next slices call (they never edit this file's logic):

- `register_retriever(leg)`: add a recall leg (Slice 06, the Tencent leg); the
  hybrid is rebuilt with it, lexical stays the fallback;
- `register_write_listener(callback)`: called with the memory id after every
  store mutation (Slice 06 mirror sink);
- `register_knowledge(provider)` and `set_loadout_resolver(resolver)`: Slice 09
  (Wiki, CodeGraph, Skills, the real resolver replacing `NullLoadoutResolver`).

Contract page: `docs/memory.md` (Core wiring).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import asyncio
import logging
from pathlib import Path
from typing import Any

from jarvis.core.memory_context import CachedMemorySettings, MemoryTurnContext, RecentTurn
from jarvis.core.memory_hybrid import HybridRetriever
from jarvis.core.memory_service import MemoryService, brain_policy
from jarvis.domain.knowledge import AssetKind
from jarvis.domain.memory import SHARED_SCOPE, CapabilityState, MemoryNote, MemoryPatch, RecallQuery
from jarvis.domain.memory_leg import LEG_LEXICAL, LEG_SEMANTIC
from jarvis.domain.memory_settings import EmbeddingProviderId, MemorySettings, TencentSettings
from jarvis.domain.v2 import utc_now
from jarvis.ports.knowledge import KnowledgeAssetProvider, LoadoutResolver
from jarvis.ports.memory_retrieval import EmbeddingProvider, RecallLeg
from jarvis.ports.memory_store import CanonicalMemoryStore
from jarvis.ports.v2 import DiagnosticSink

_LOG = logging.getLogger("jarvis")

#: Stable code when the store could not be opened at startup.
STORE_UNAVAILABLE = "memory_unavailable"
#: Longest the background lexical warm-up waits (seconds).
WARMUP_TIMEOUT_S = 1.5
#: Stable code when Core runs without memory (tests, headless).
NOT_CONFIGURED = "memory_not_configured"

WriteListener = Callable[[str], None]
StoreFactory = Callable[[Path], CanonicalMemoryStore]


class NotifyingStore:
    """The canonical store plus a write notification: every mutation tells the listeners which note changed.

    Reads and everything else (the legacy `MemoryBackend` port, `search_ranked`,
    `rebuild_indexes`) go straight to the wrapped store. A listener that raises
    is reported and skipped: a derived index never fails a canonical write.
    `append_note` (V1 only) is not notified; the semantic reconcile picks it up.
    """

    def __init__(self, store: Any, diagnostics: DiagnosticSink | None = None) -> None:
        self._store = store
        self._diagnostics = diagnostics
        self._listeners: list[WriteListener] = []

    def add_listener(self, listener: WriteListener) -> None:
        self._listeners.append(listener)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    @property
    def index_ready(self) -> bool:
        return bool(getattr(self._store, "index_ready", True))

    def create(self, note: MemoryNote, **options: Any) -> MemoryNote:
        stored = self._store.create(note, **options)
        self._written(stored.id)
        return stored

    def revise(self, memory_id: str, patch: MemoryPatch, expected_revision: int, **options: Any) -> MemoryNote:
        stored = self._store.revise(memory_id, patch, expected_revision, **options)
        self._written(stored.id)
        return stored

    def promote_file(self, source_rel: str, target: Any) -> MemoryNote | None:
        stored = self._store.promote_file(source_rel, target)
        if stored is not None:
            self._written(stored.id)
        return stored

    def _written(self, memory_id: str) -> None:
        for listener in tuple(self._listeners):
            try:
                listener(memory_id)
            except Exception as exc:  # noqa: BLE001 - a derived index or mirror must never fail the canonical write
                _LOG.warning("memory write listener failed: %s", type(exc).__name__)
                if self._diagnostics is not None:
                    self._diagnostics.emit("core.memory.write_listener_failed",
                                           "un abonné d'écriture de la mémoire a échoué : la note est écrite",
                                           level="warning", data={"exception_type": type(exc).__name__})


@dataclass(slots=True)
class MemoryWiring:
    """What Core holds of memory. Every field but `settings` is `None` when memory is absent or unavailable."""

    store: NotifyingStore | None = None
    service: MemoryService | None = None
    context: MemoryTurnContext | None = None
    settings: CachedMemorySettings | None = None
    semantic: Any = None
    #: `memory_not_configured` (no wiring), `memory_unavailable` (store refused at startup), or `None`.
    unavailable: str | None = NOT_CONFIGURED
    hybrid_legs: list[RecallLeg] | None = None
    knowledge: dict[AssetKind, KnowledgeAssetProvider] | None = None
    #: The Tencent registration (leg + mirror sink) when `memory.tencent` is enabled; `None`: no network, ever.
    tencent: Any = None
    _warm_task: Any = None

    @classmethod
    def absent(cls) -> MemoryWiring:
        """Core without memory: no block, no store, routes answer `memory_unavailable`."""

        return cls()

    @property
    def available(self) -> bool:
        return self.service is not None

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        """Start the background workers (semantic embeddings, Tencent mirror, lexical warm-up). Never raises, never blocks."""

        if self.semantic is not None:
            try:
                self.semantic.start()
            except Exception as exc:  # noqa: BLE001 - the derived index must not stop Core from starting
                _LOG.warning("memory semantic index not started: %s", type(exc).__name__)
        if self.tencent is not None:
            try:
                await self.tencent.start()
            except Exception as exc:  # noqa: BLE001 - the optional sidecar must not stop Core from starting
                _LOG.warning("memory tencent mirror not started: %s", type(exc).__name__)
        if self.hybrid_legs:
            self._warm_task = asyncio.create_task(self._warm(self.hybrid_legs[0]), name="memory-lexical-warmup")

    @staticmethod
    async def _warm(lexical: RecallLeg) -> None:
        """The first recall after boot cost 100-210 ms (thread pool, sqlite connection): pay it here, in the
        background, with a query no one sent. Lexical only: the warm-up never reaches an embedder or the network."""

        try:
            await asyncio.wait_for(lexical.hits(RecallQuery(text="warmup", scopes=(SHARED_SCOPE,)), 1, WARMUP_TIMEOUT_S),
                                   WARMUP_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a warm-up is a courtesy: its failure is the first recall's own to report
            _LOG.debug("memory lexical warm-up did not finish: %s", type(exc).__name__)

    async def stop(self) -> None:
        warm, self._warm_task = self._warm_task, None
        if warm is not None and not warm.done():
            warm.cancel()
            await asyncio.gather(warm, return_exceptions=True)
        if self.tencent is not None:
            try:
                await self.tencent.aclose()
            except Exception as exc:  # noqa: BLE001 - shutdown goes on: the mirror is derived, a resync repairs it
                _LOG.warning("memory tencent not closed cleanly: %s", type(exc).__name__)
        if self.semantic is None:
            return
        try:
            await self.semantic.stop()
        except Exception as exc:  # noqa: BLE001 - shutdown goes on: a derived index holds nothing durable
            _LOG.warning("memory semantic index not stopped cleanly: %s", type(exc).__name__)

    def bind_recent_turn(self, recent_turn: RecentTurn) -> None:
        """Core hands the lookup of the previous user turn once its conversations exist (the wiring is built before Core)."""

        if self.context is not None:
            self.context.bind_recent_turn(recent_turn)

    # ----------------------------------------------------------------- hooks
    def register_retriever(self, leg: RecallLeg, *, reporter: Callable[[], CapabilityState] | None = None) -> None:
        """Add a recall leg (Slice 06). The hybrid is rebuilt; a leg name already present is refused (`ValueError`)."""

        if self.service is None or self.hybrid_legs is None:
            return  # memory absent or unavailable: nothing to extend
        hybrid = HybridRetriever((*self.hybrid_legs, leg), policy=self.service.policy)  # raises on a duplicate or unknown name
        self.hybrid_legs.append(leg)
        self.service.retriever = hybrid
        self.service.register_reporter(leg.name, reporter or leg.status)

    def register_write_listener(self, listener: WriteListener) -> None:
        if self.store is not None:
            self.store.add_listener(listener)

    def register_knowledge(self, provider: KnowledgeAssetProvider) -> None:
        """A knowledge asset provider (Slice 09): its health joins `/v1/memory/status` as `knowledge:<kind>`."""

        if self.service is None or self.knowledge is None:
            return
        self.knowledge[provider.kind] = provider
        self.service.register_reporter(f"knowledge:{provider.kind.value}", provider.status)

    def set_loadout_resolver(self, resolver: LoadoutResolver) -> None:
        if self.service is not None:
            self.service.loadouts = resolver


@dataclass(frozen=True, slots=True)
class MemoryAdapters:
    """The concrete adapters, injected: `core` never imports one (`tests/unit/test_v2_architecture.py`).

    `jarvis/runtime/memory_composition.py` binds the real ones; tests bind fakes.

    - `store(root)`: the canonical store (blocking constructor work happens in its own thread);
    - `lexical(store)`: the lexical `RecallLeg`;
    - `semantic(path, embedder, store, allow_private)`: `(index, leg)`, the derived vector index
      (`start`, `stop`, `notify_written`) and its `RecallLeg`;
    - `embedder(settings)`: the `EmbeddingProvider` of the configured provider, `settings` being a loader of
      the whole settings file (credentials are read from it at each call);
    - `tencent(settings, credentials, store, ledger_path)`: the Tencent registration (leg, mirror sink, `start`,
      `aclose`) or `None`; called only when `memory.tencent.enabled` and a URL are set, so disabled means no
      adapter code and no network;
    - `read_settings(file)`: `MemorySettings` from the whole settings file, tolerant, never raising.
    """

    store: StoreFactory
    lexical: Callable[[Any], RecallLeg]
    semantic: Callable[[Path, EmbeddingProvider, Any, bool], tuple[Any, RecallLeg]]
    embedder: Callable[[Callable[[], Mapping[str, Any]]], EmbeddingProvider]
    read_settings: Callable[[Mapping[str, Any]], MemorySettings]
    tencent: Callable[[TencentSettings, Callable[[], Mapping[str, Any]], Any, Path], Any] | None = None


def build_memory_wiring(
    data_root: Path,
    settings_path: Path,
    adapters: MemoryAdapters,
    *,
    diagnostics: DiagnosticSink | None = None,
    recent_turn: RecentTurn | None = None,
    embedder: EmbeddingProvider | None = None,
    clock: Callable[[], float] | None = None,
) -> MemoryWiring:
    """Memory of one data root: `<data_root>/memory` (store), `<memory>/.jarvis/semantic.sqlite3` (derived index).

    `settings_path` is `control-center-settings.json`. `embedder` and `clock` are injections for tests. Never
    raises: a store or index that cannot be opened is reported (journal and log) and left out.
    """

    cached = CachedMemorySettings(settings_path, adapters.read_settings, **({} if clock is None else {"clock": clock}))
    root = Path(data_root) / "memory"
    try:
        store = NotifyingStore(adapters.store(root), diagnostics)
    except Exception as exc:  # noqa: BLE001 - adapter boundary: whatever the disk or database refuses, Core starts without memory, said here
        _LOG.warning("memory store unavailable at startup: %s", type(exc).__name__)
        if diagnostics is not None:
            diagnostics.emit("core.memory.unavailable", "mémoire canonique illisible au démarrage : Core démarre sans elle",
                             level="error", data={"code": STORE_UNAVAILABLE, "exception_type": type(exc).__name__,
                                                  "at": utc_now().isoformat()})
        return MemoryWiring(settings=cached, unavailable=STORE_UNAVAILABLE,
                            context=MemoryTurnContext(None, cached, recent_turn=recent_turn, unavailable="store_unavailable"))
    settings = cached.current()
    legs: list[RecallLeg] = []
    semantic = None
    reporters: dict[str, Callable[[], CapabilityState]] = {}
    lexical = adapters.lexical(store)
    legs.append(lexical)
    reporters[LEG_LEXICAL] = lexical.status
    provider = embedder
    if provider is None and settings.semantic.enabled and settings.semantic.provider is not EmbeddingProviderId.NONE:
        provider = adapters.embedder(cached.raw)
    if provider is not None:
        try:
            semantic, leg = adapters.semantic(root / ".jarvis" / "semantic.sqlite3", provider, store,
                                              settings.semantic.allow_private)
            legs.append(leg)
            reporters[LEG_SEMANTIC] = leg.status
            store.add_listener(semantic.notify_written)
        except Exception as exc:  # noqa: BLE001 - adapter boundary: the semantic leg is optional, lexical recall is the whole of recall without it
            semantic = None
            _LOG.warning("memory semantic index unavailable at startup: %s", type(exc).__name__)
            if diagnostics is not None:
                diagnostics.emit("core.memory.semantic_unavailable",
                                 "index sémantique indisponible au démarrage : rappel lexical seul", level="warning",
                                 data={"code": "semantic_unavailable", "exception_type": type(exc).__name__})
    policy = brain_policy()
    service = MemoryService(store, HybridRetriever(legs, policy=policy), policy, index_ready=lambda: store.index_ready)
    for capability_id, reporter in reporters.items():
        service.register_reporter(capability_id, reporter)
    wiring = MemoryWiring(
        store=store, service=service, settings=cached, semantic=semantic, unavailable=None, hybrid_legs=legs,
        knowledge={}, context=MemoryTurnContext(service, cached, recent_turn=recent_turn),
    )
    _wire_tencent(wiring, settings.tencent, adapters, cached, store, root, diagnostics)
    return wiring


def _wire_tencent(wiring: MemoryWiring, tencent: TencentSettings, adapters: MemoryAdapters, cached: CachedMemorySettings,
                  store: NotifyingStore, root: Path, diagnostics: DiagnosticSink | None) -> None:
    """Slice 06: with `memory.tencent.enabled` and a URL, the leg joins the hybrid (the hook), the mirror sink
    follows every canonical write, and both are started and closed with Core. Disabled: nothing is built."""

    if not tencent.enabled or not tencent.url.strip() or adapters.tencent is None:
        return
    try:
        registration = adapters.tencent(tencent, cached.raw, store, root / ".jarvis" / "tencent-mirror.json")
    except Exception as exc:  # noqa: BLE001 - adapter boundary: the optional sidecar never stops Core, lexical recall goes on
        _LOG.warning("memory tencent sidecar not registered: %s", type(exc).__name__)
        if diagnostics is not None:
            diagnostics.emit("core.memory.tencent_unavailable", "sidecar Tencent non enregistré : rappel local seul",
                             level="warning", data={"code": "tencent_unavailable", "exception_type": type(exc).__name__})
        return
    if registration is None:
        return
    wiring.tencent = registration
    wiring.register_retriever(registration.leg)
    if registration.sink is not None:
        wiring.register_write_listener(registration.sink.notify_written)
        wiring.service.register_reporter(registration.sink.capability_id, registration.sink.status)


def capability_summary(states: Mapping[str, CapabilityState]) -> dict[str, dict[str, str | None]]:
    """JSON form of a status mapping (stable keys; a degraded or unavailable leg always carries its code)."""

    return {name: {"status": state.status.value, "reason_code": state.reason_code, "reason": state.reason}
            for name, state in states.items()}


__all__ = [
    "NOT_CONFIGURED", "STORE_UNAVAILABLE", "MemoryAdapters", "MemoryWiring", "NotifyingStore", "build_memory_wiring",
    "capability_summary",
]
