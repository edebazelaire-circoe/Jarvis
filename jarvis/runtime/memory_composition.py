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
