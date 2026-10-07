"""Real Tencent MemoryCore sidecar (memory handoff, Slice 06). Skipped by default.

Marker `live` (the repository's one marker for tests that touch a real remote
service) plus the opt-in `JARVIS_TENCENT_LIVE=1`. This is the only check of the
wire shape pinned in `docs/memory-tencent.md`: the CI fake is a double of the
documented shape, not of the real sidecar. It exercises exactly the points the
page lists as NOT verified: the identity trio filtering `conversation/search`,
`conversation/delete` by `message_ids`, a fixed `session_id` with role `user`,
and the ranking of a verbatim marker message.

    JARVIS_TENCENT_LIVE=1 JARVIS_TENCENT_TOKEN=<token> [JARVIS_TENCENT_SERVICE_ID=<instance id>] \\
        [JARVIS_TENCENT_LIVE_URL=http://127.0.0.1:8420] \\
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
import pytest_asyncio

from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
from jarvis.adapters.tencent_memory import (
    TencentClient,
    TencentConfig,
    TencentMemoryRetriever,
    TencentMirrorSink,
)
from jarvis.domain.memory import MemoryKind, MemoryLevel, MemoryNote, MemoryPatch, RecallQuery, RetentionClass
from jarvis.runtime.credentials import secret_for

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("JARVIS_TENCENT_LIVE") != "1", reason="requires JARVIS_TENCENT_LIVE=1"),
]

URL = os.getenv("JARVIS_TENCENT_LIVE_URL", "http://127.0.0.1:8420")
T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


def make_note(body: str, **over) -> MemoryNote:
    base = dict(
        id=uuid.uuid4().hex, title="Live note", body=body, level=MemoryLevel.L1, kind=MemoryKind.FACT,
        retention=RetentionClass.LONG_TERM, scope="shared", created_at=T0, updated_at=T0,
    )
    return MemoryNote(**{**base, **over})


@pytest_asyncio.fixture
async def live(tmp_path: Path):
    store = MarkdownMemoryBackend(tmp_path / "memory")
    token = secret_for({}, "tencent")
    config = TencentConfig(URL, team=f"jarvis-live-{uuid.uuid4().hex[:8]}", service_id=os.getenv("JARVIS_TENCENT_SERVICE_ID", ""))
    client = TencentClient(config, lambda: token)
    leg, sink = TencentMemoryRetriever(client, store), TencentMirrorSink(client, store)
    yield store, client, leg, sink
    try:
        for memory_id in sink._ledger.ids():  # noqa: SLF001 - cleanup of what this test wrote
            await sink._remove(memory_id)  # noqa: SLF001
    finally:
        await client.aclose()


async def test_mirror_recall_resync_and_latency(live):
    store, client, leg, sink = live
    marker = f"zebrafish{uuid.uuid4().hex[:6]}"
    store.create(make_note(f"the {marker} migration is scheduled"))
    first = await sink.resync()  # add with role "user" and the fixed session id: accepted by the real API
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


async def test_revise_then_replace_leaves_one_message(live):
    """`conversation/delete` by `message_ids`, then add: the old text is gone, the new one ranks."""

    store, client, leg, sink = live
    old, new = f"quokka{uuid.uuid4().hex[:6]}", f"wombat{uuid.uuid4().hex[:6]}"
    note = store.create(make_note(f"first text about the {old}"))
    assert (await sink.resync()).pushed == 1, client.last_error
    assert [h.memory_id for h in (await leg.hits(RecallQuery(text=old, scopes=("shared",)), 20, 2.0)).hits] == [note.id]
    store.revise(note.id, MemoryPatch(body=f"second text about the {new}"), 1)
    report = await sink.resync()
    assert (report.pushed, report.failed) == (1, 0), client.last_error  # the real delete accepted `message_ids`
    # The sidecar no longer returns the old text; if it did, canonical re-reading would still hide it,
    # so look at the raw answer too.
    raw = await client.post(
        "/v3/conversation/search",
        {"query": old, "limit": 10, "team_id": client.config.team, "user_id": client.config.user, "agent_id": "jarvis"},
        timeout_s=2.0,
    )
    assert all(old not in str(message.get("content")) for message in raw["messages"])
    assert [h.memory_id for h in (await leg.hits(RecallQuery(text=new, scopes=("shared",)), 20, 2.0)).hits] == [note.id]


async def test_agents_are_isolated_by_the_real_identity_trio(live):
    """The sidecar's own isolation (the second layer) separates agents too."""

    store, client, leg, sink = live
    marker = f"narwhal{uuid.uuid4().hex[:6]}"
    alice = store.create(make_note(f"{marker} belongs to alice", agent="alice"))
    store.create(make_note(f"{marker} belongs to bob", agent="bob"))
    assert (await sink.resync()).pushed == 2, client.last_error
    for agent in ("alice", "bob", "carol"):
        answer = await client.post(
            "/v3/conversation/search",
            {"query": marker, "limit": 10, "team_id": client.config.team, "user_id": client.config.user, "agent_id": agent},
            timeout_s=2.0,
        )
        contents = [str(message.get("content")) for message in answer["messages"]]
        other = "bob" if agent == "alice" else "alice"
        assert all(f"belongs to {other}" not in text for text in contents), f"{agent} saw {other}'s message"
        if agent == "carol":
            assert contents == []
    found = await leg.hits(RecallQuery(text=marker, scopes=("shared",), agent="alice"), 20, 2.0)
    assert [hit.memory_id for hit in found.hits] == [alice.id]
