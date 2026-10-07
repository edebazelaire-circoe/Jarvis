"""Real Tencent MemoryCore sidecar (memory handoff, Slice 06). Skipped by default.

Marker `live` (the repository's one marker for tests that touch a real remote
service) plus the opt-in `JARVIS_TENCENT_LIVE=1`. This is the only check of the
wire shape pinned in `docs/memory-tencent.md`: the CI fake is a double of the
documented shape, not of the real sidecar.

    JARVIS_TENCENT_LIVE=1 JARVIS_TENCENT_TOKEN=<token> [JARVIS_TENCENT_LIVE_URL=http://127.0.0.1:8420] \\
        .venv/Scripts/python.exe -m pytest tests/integration/test_tencent_live.py -s

It writes into a throwaway team (`jarvis-live-<random>`) of the sidecar and
removes what it wrote. Latency of the recall leg is printed (p50/p95 of 20
calls) as the optional PoC metric; nothing asserts on it.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import statistics
import time
import uuid

import pytest

from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
from jarvis.adapters.tencent_memory import (
    TencentClient,
    TencentConfig,
    TencentMemoryRetriever,
    TencentMirrorSink,
)
from jarvis.domain.memory import MemoryKind, MemoryLevel, MemoryNote, RecallQuery, RetentionClass
from jarvis.runtime.credentials import secret_for

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("JARVIS_TENCENT_LIVE") != "1", reason="requires JARVIS_TENCENT_LIVE=1"),
]

URL = os.getenv("JARVIS_TENCENT_LIVE_URL", "http://127.0.0.1:8420")
T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


async def test_mirror_recall_resync_and_cleanup_against_a_real_sidecar(tmp_path: Path):
    store = MarkdownMemoryBackend(tmp_path / "memory")
    token = secret_for({}, "tencent")
    client = TencentClient(TencentConfig(URL, team=f"jarvis-live-{uuid.uuid4().hex[:8]}"), lambda: token)
    leg, sink = TencentMemoryRetriever(client, store), TencentMirrorSink(client, store)
    marker = f"zebrafish{uuid.uuid4().hex[:6]}"
    store.create(MemoryNote(
        id=uuid.uuid4().hex, title="Live note", body=f"the {marker} migration is scheduled",
        level=MemoryLevel.L1, kind=MemoryKind.FACT, retention=RetentionClass.LONG_TERM, scope="shared",
        created_at=T0, updated_at=T0,
    ))
    try:
        first = await sink.resync()
        assert (first.pushed, first.failed) == (1, 0), client.last_error
        assert (await sink.resync()).unchanged == 1  # idempotent against the real API too
        recall = RecallQuery(text=marker, scopes=("shared",))
        result = await leg.hits(recall, 20, 2.0)
        assert [hit.title for hit in result.hits] == ["Live note"]
        timings = []
        for _ in range(20):
            started = time.perf_counter()
            await leg.hits(recall, 20, 2.0)
            timings.append((time.perf_counter() - started) * 1000)
        timings.sort()
        print(f"tencent recall leg: p50={statistics.median(timings):.1f} ms p95={timings[18]:.1f} ms")
    finally:
        for memory_id in sink._ledger.ids():  # noqa: SLF001 - cleanup of what this test wrote
            await sink._remove(memory_id)  # noqa: SLF001
        await client.aclose()
