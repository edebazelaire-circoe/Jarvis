"""Binding of the real memory adapters to Core's memory wiring (handoff jarvis-memory-intelligence-knowledge, Slice 05).

`jarvis/core/memory_wiring.py` assembles memory from injected `MemoryAdapters`
(the architecture gate forbids `core` from importing an adapter or the runtime
layer). This module is the one place that names the concrete ones: the Markdown
canonical store, the FTS5 lexical leg, the derived semantic index with its leg,
the OpenAI embedder (credentials read from the settings file at each call) and
the tolerant settings reader. `jarvis/app.py` calls `build_default_memory_wiring`;
tests call it with a `store_factory` or an `embedder` of their own.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from jarvis.adapters.embedding_openai import openai_embedder_from_settings
from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
from jarvis.adapters.memory_candidates import FileCandidateStore
from jarvis.adapters.memory_lexical import LexicalRetriever
from jarvis.adapters.memory_semantic import SemanticIndex, SemanticRetriever
from jarvis.adapters.tencent_memory import register_retriever as register_tencent
from jarvis.core.memory_context import RecentTurn
from jarvis.domain.memory_settings import TencentSettings
from jarvis.core.memory_wiring import MemoryAdapters, MemoryWiring, StoreFactory, build_memory_wiring
from jarvis.ports.memory_retrieval import EmbeddingProvider
from jarvis.ports.v2 import DiagnosticSink
from jarvis.runtime.memory_settings import read_memory_settings_file


def _semantic(path: Path, embedder: EmbeddingProvider, store: Any, allow_private: bool) -> tuple[SemanticIndex, SemanticRetriever]:
    index = SemanticIndex(path, embedder, store, allow_private=allow_private)
    return index, SemanticRetriever(index)


def _tencent(transport: Any) -> Callable[..., Any]:
    def register(settings: TencentSettings, credentials: Callable[[], Any], store: Any, ledger_path: Path) -> Any:
        return register_tencent(settings, credentials, store, ledger_path=ledger_path,
                                allow_private=settings.allow_private, service_id=settings.service_id, transport=transport)

    return register


def default_adapters(store_factory: StoreFactory | None = None, tencent_transport: Any = None) -> MemoryAdapters:
    return MemoryAdapters(
        store=store_factory or MarkdownMemoryBackend,
        lexical=LexicalRetriever,
        semantic=_semantic,
        embedder=openai_embedder_from_settings,
        read_settings=read_memory_settings_file,
        tencent=_tencent(tencent_transport),
        candidates=FileCandidateStore,
    )


def build_default_memory_wiring(
    data_root: Path,
    settings_path: Path,
    *,
    diagnostics: DiagnosticSink | None = None,
    recent_turn: RecentTurn | None = None,
    store_factory: StoreFactory | None = None,
    embedder: EmbeddingProvider | None = None,
    clock: Callable[[], float] | None = None,
    tencent_transport: Any = None,
) -> MemoryWiring:
    """`build_memory_wiring` with the real adapters (`store_factory`, `embedder`, `clock`, `tencent_transport`: test injections)."""

    return build_memory_wiring(data_root, settings_path, default_adapters(store_factory, tencent_transport),
                               diagnostics=diagnostics,
                               recent_turn=recent_turn, embedder=embedder, clock=clock)


def build_consolidation(
    wiring: MemoryWiring,
    memory_root: Path,
    *,
    agent_execution: Callable[[], Any],
    control_settings: Callable[[], Any],
    diagnostics: DiagnosticSink | None = None,
    model_factory: Callable[[], Any] | None = None,
) -> Any:
    """The Slice 04 `ConsolidationPipeline` over the wiring's store and retriever, installed as `wiring.consolidation`.

    The extractor is the zero-tool CLI agent (`CliTextModel`) on the routing policy's `fast` model when that policy
    is enabled and names a model of the running CLI. `None` (and nothing installed) when memory is unavailable.
    `model_factory` is the test injection of the `TextModel`.
    """

    if wiring.store is None or wiring.service is None:
        return None
    from jarvis.adapters.memory_candidates import FileCandidateStore
    from jarvis.adapters.memory_extractor_llm import CliTextModel, LlmCandidateExtractor
    from jarvis.core.memory_consolidation import ConsolidationPipeline
    from jarvis.domain.memory_settings import ConsolidationSettings
    from jarvis.runtime import agent_routing

    def fast_model() -> str | None:
        try:
            policy = agent_routing.load_policy(control_settings())
            entry = policy.for_profile("fast") if policy.enabled else None
            running = agent_execution().agent_cli
            for ref in (entry.candidates if entry is not None else ()):
                if ref.agent == running and ref.model:
                    return ref.model
        except Exception:  # noqa: BLE001 - routing is a preference: the CLI's configured model serves
            return None
        return None

    def sink(event: str, data: Any) -> None:
        if diagnostics is not None:
            diagnostics.emit(event, event, data=dict(data))

    pipeline = ConsolidationPipeline(
        store=wiring.store,
        candidates=FileCandidateStore(memory_root),
        extractor=LlmCandidateExtractor(model_factory() if model_factory else CliTextModel(agent_execution, fast_model)),
        settings=lambda: wiring.settings.current().consolidation if wiring.settings is not None else ConsolidationSettings(),
        retriever=wiring.service.retriever,
        sink=sink,
    )
    wiring.consolidation = pipeline
    return pipeline
