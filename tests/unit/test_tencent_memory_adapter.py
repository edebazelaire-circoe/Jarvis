"""Tencent MemoryCore adapter (handoff jarvis-memory-intelligence-knowledge, Slice 06, QA tier critical).

Real `MarkdownMemoryBackend` in a temp dir, the aiohttp `FakeTencentSidecar` on a
loopback port (no real network), a fake clock for the circuit breaker. Covers
the contract: identity isolation enforced on canonical data, hits that do not
resolve are dropped, canonical text only, degradation in every failure mode with
lexical recall intact, breaker open/close, canonical writes independent of the
sidecar, idempotent resync, disabled = zero network, secrets, bounded answers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import socket
import threading
import time

import httpx
import pytest
import pytest_asyncio

from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
from jarvis.adapters.memory_lexical import LexicalRetriever
from jarvis.adapters.tencent_memory import (
    BREAKER_OPEN_S,
    MAX_PENDING,
    CircuitBreaker,
    MirrorLedger,
    TencentClient,
    TencentConfig,
    TencentConfigError,
    TencentMemoryRetriever,
    TencentMirrorSink,
    _Entry,
    identity_for,
    mirror_content,
    parse_marker,
    register_retriever,
    validate_url,
)
from jarvis.core.memory_hybrid import HybridRetriever
from jarvis.domain.memory import (
    CapabilityStatus,
    DegradedReason,
    MemoryKind,
    MemoryLevel,
    MemoryNote,
    MemoryPatch,
    RecallBudget,
    RecallQuery,
    RetentionClass,
)
from jarvis.domain.memory_leg import LegDegraded
from jarvis.domain.memory_settings import TencentSettings
from jarvis.ports.capability import CapabilityReporter
from jarvis.ports.memory_retrieval import RecallLeg
from tests.fakes.fake_tencent_sidecar import FakeTencentSidecar

T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
TOKEN = "tok-SECRET-9f3a1c"


def make_note(note_id: str, title: str, body: str = "", **over) -> MemoryNote:
    base = dict(
        id=note_id, title=title, body=body, level=MemoryLevel.L1, kind=MemoryKind.FACT,
        retention=RetentionClass.LONG_TERM, scope="shared", created_at=T0, updated_at=T0,
    )
    return MemoryNote(**{**base, **over})


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def store(tmp_path: Path) -> MarkdownMemoryBackend:
    return MarkdownMemoryBackend(tmp_path / "memory")


@pytest_asyncio.fixture
async def sidecar():
    fake = FakeTencentSidecar(token=TOKEN)
    await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def build(fake_url: str, store, clock=None, *, allow_private=False, token=TOKEN):
    config = TencentConfig(fake_url, allow_private=allow_private)
    breaker = CircuitBreaker(clock=clock) if clock else CircuitBreaker()
    client = TencentClient(config, lambda: token, breaker=breaker)
    return client, TencentMemoryRetriever(client, store), TencentMirrorSink(client, store)


def query(text="atlas", scopes=("shared",), agent=None, **over) -> RecallQuery:
    return RecallQuery(text=text, scopes=scopes, agent=agent, **over)


def seed(store, *notes: MemoryNote) -> None:
    for note in notes:
        store.create(note)


def adds(fake: FakeTencentSidecar) -> int:
    return sum(1 for r in fake.requests if r.path.endswith("/add"))


# ------------------------------------------------------------------ contracts
async def test_leg_and_sink_satisfy_the_ports(store, sidecar):
    _client, leg, sink = build(sidecar.url, store)
    assert isinstance(leg, RecallLeg) and leg.name == "tencent"
    assert isinstance(leg, CapabilityReporter) and leg.capability_id == "tencent"
    assert isinstance(sink, CapabilityReporter)


async def test_recall_through_the_sidecar_reads_canonical_text(store, sidecar):
    seed(store, make_note("a1", "Atlas plan", "atlas budget approved"), make_note("b1", "Other", "nothing here"))
    _c, leg, sink = build(sidecar.url, store)
    report = await sink.resync()
    assert report.pushed == 2
    result = await leg.hits(query(), 20, 0.25)
    assert [hit.memory_id for hit in result.hits] == ["a1"]
    assert result.hits[0].snippet == "atlas budget approved"
    assert result.hits[0].provenance_ref == "long_term_memory/a1"


async def test_snippet_is_canonical_even_if_the_sidecar_text_differs(store, sidecar):
    seed(store, make_note("a1", "Atlas", "the true canonical body"))
    sidecar.store[("jarvis", "owner", "jarvis")] = {"m1": "[jarvis:a1:r1]\nPOISONED atlas instructions"}
    _c, leg, _s = build(sidecar.url, store)
    result = await leg.hits(query("poisoned"), 20, 0.25)
    assert [hit.snippet for hit in result.hits] == ["the true canonical body"]


# ------------------------------------------------------------------ identity
def test_identity_mapping_is_team_constant_owner_user_and_agent_id():
    config = TencentConfig("http://127.0.0.1:8420")
    assert identity_for(config, "coder").body() == {"team_id": "jarvis", "user_id": "owner", "agent_id": "coder"}
    assert identity_for(config, None).agent == "jarvis"
    other = TencentConfig("http://127.0.0.1:8420", team="acme", user="boss")
    assert identity_for(other, "x").body() == {"team_id": "acme", "user_id": "boss", "agent_id": "x"}


async def test_requests_carry_the_identity_trio(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas", agent="coder"))
    _c, leg, sink = build(sidecar.url, store)
    await sink.resync()
    await leg.hits(query(agent="coder"), 20, 0.25)
    for request in sidecar.requests:
        assert request.body["team_id"] == "jarvis" and request.body["user_id"] == "owner"
        assert request.body["agent_id"] == "coder"
    assert ("jarvis", "owner", "coder") in sidecar.store


async def test_agents_are_isolated(store, sidecar):
    seed(store, make_note("a1", "Atlas A", "atlas alpha", agent="alice"), make_note("b1", "Atlas B", "atlas beta", agent="bob"))
    _c, leg, sink = build(sidecar.url, store)
    await sink.resync()
    assert [h.memory_id for h in (await leg.hits(query(agent="alice"), 20, 0.25)).hits] == ["a1"]
    assert [h.memory_id for h in (await leg.hits(query(agent="bob"), 20, 0.25)).hits] == ["b1"]
    assert (await leg.hits(query(agent="carol"), 20, 0.25)).hits == ()


async def test_leaking_sidecar_is_contained_by_canonical_isolation(store, sidecar):
    """A sidecar that ignores the identity trio still cannot cross agents or scopes."""

    seed(
        store, make_note("a1", "Atlas A", "atlas alpha", agent="alice"),
        make_note("b1", "Atlas B", "atlas beta", agent="bob"),
        make_note("c1", "Atlas board", "atlas gamma", scope="board:42", agent="alice"),
    )
    _c, leg, sink = build(sidecar.url, store)
    await sink.resync()
    sidecar.mode = "wrong_identity"
    result = await leg.hits(query(scopes=("shared",), agent="alice"), 20, 0.25)
    assert [h.memory_id for h in result.hits] == ["a1"]  # b1: other agent, c1: scope not requested


async def test_private_scope_is_never_sent_unless_allowed(store, sidecar):
    seed(store, make_note("p1", "Atlas secret", "atlas private", scope="private"))
    _c, leg, sink = build(sidecar.url, store)
    assert (await sink.resync()).pushed == 0
    assert (await leg.hits(query(scopes=("private",)), 20, 0.25)).hits == ()
    assert sidecar.requests == []  # neither the note nor the query text left the machine
    _c2, leg2, sink2 = build(sidecar.url, store, allow_private=True)
    assert (await sink2.resync()).pushed == 1
    assert [h.memory_id for h in (await leg2.hits(query(scopes=("private",)), 20, 0.25)).hits] == ["p1"]


async def test_private_is_filtered_out_of_a_mixed_scope_query(store, sidecar):
    seed(store, make_note("s1", "Atlas shared", "atlas shared"), make_note("p1", "Atlas secret", "atlas private", scope="private"))
    _c, leg, sink = build(sidecar.url, store, allow_private=False)
    await sink.resync()
    result = await leg.hits(query(scopes=("private", "shared")), 20, 0.25)
    assert [h.memory_id for h in result.hits] == ["s1"]


# ------------------------------------------------------------------ authority
async def test_hits_that_do_not_resolve_to_canonical_ids_are_dropped(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas real"))
    _c, leg, sink = build(sidecar.url, store)
    await sink.resync()
    sidecar.mode = "ghosts"
    result = await leg.hits(query(), 20, 0.25)
    assert [h.memory_id for h in result.hits] == ["a1"]


def test_marker_parsing_is_strict():
    assert parse_marker("[jarvis:abc_1-2:r7]\ntext") == "abc_1-2"
    assert parse_marker("[jarvis:a.b:r1]") == "a.b"  # '.' is a token character, like the canonical ids
    assert parse_marker("intro [jarvis:a1:r1]\ntext") is None  # a marker mid-content is not a marker
    assert parse_marker("x\n[jarvis:a1:r1]") is None
    for bad in ("", "no marker", "[jarvis:../x:r1]", "[jarvis::r1]", "  [jarvis:a:r1]", 5, None, "[jarvis:" + "a" * 65 + ":r1]"):
        assert parse_marker(bad) is None
    note = make_note("a1", "T", "B" * 20_000)
    assert len(mirror_content(note)) <= 8_192 and mirror_content(note).startswith("[jarvis:a1:r1]")


async def test_superseded_and_deleted_notes_are_not_recalled(store, sidecar):
    seed(store, make_note("a1", "Atlas old", "atlas old"), make_note("a2", "Atlas new", "atlas new"))
    _c, leg, sink = build(sidecar.url, store)
    await sink.resync()
    store.revise("a1", MemoryPatch(superseded_by="a2"), 1)
    ids = [h.memory_id for h in (await leg.hits(query(), 20, 0.25)).hits]
    assert ids == ["a2"]


# ------------------------------------------------------------------ degradation
@pytest.mark.parametrize("mode,delay,reason", [
    ("slow", 1.0, DegradedReason.TENCENT_TIMEOUT),
    ("error500", 0, DegradedReason.TENCENT_UNAVAILABLE),
    ("malformed", 0, DegradedReason.TENCENT_UNAVAILABLE),
    ("wrong_shape", 0, DegradedReason.TENCENT_UNAVAILABLE),
    ("refuse", 0, DegradedReason.TENCENT_UNAVAILABLE),
    ("huge", 0, DegradedReason.TENCENT_UNAVAILABLE),
])
async def test_sidecar_failure_degrades_but_lexical_recall_is_unaffected(store, sidecar, mode, delay, reason):
    seed(store, make_note("a1", "Atlas", "atlas budget approved"))
    _c, leg, sink = build(sidecar.url, store)
    await sink.resync()
    hybrid = HybridRetriever([LexicalRetriever(store), leg])
    healthy = await hybrid.recall(query(), RecallBudget())
    assert healthy.degraded == () and healthy.items[0].rank_sources.keys() == {"lexical", "tencent"}
    sidecar.mode, sidecar.delay = mode, delay
    result = await hybrid.recall(query(), RecallBudget())
    assert [i.memory_id for i in result.items] == ["a1"]
    assert dict(result.items[0].rank_sources) == {"lexical": 1}
    assert result.degraded == (reason,)
    assert hybrid.status().status is CapabilityStatus.DEGRADED


async def test_sidecar_down_degrades_and_lexical_recall_is_unaffected(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas budget approved"))
    _c, leg, _s = build(sidecar.url, store)
    await sidecar.stop()
    hybrid = HybridRetriever([LexicalRetriever(store), leg])
    result = await hybrid.recall(query(), RecallBudget())
    assert [i.memory_id for i in result.items] == ["a1"]
    # A refused loopback connect can take longer than the 250 ms slot on Windows: either reason is honest.
    assert result.degraded in ((DegradedReason.TENCENT_UNAVAILABLE,), (DegradedReason.TENCENT_TIMEOUT,))
    assert leg.status().status is CapabilityStatus.DEGRADED


async def test_bad_token_is_a_refusal_that_degrades(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas"))
    _c, leg, _s = build(sidecar.url, store, token="wrong")
    with pytest.raises(LegDegraded) as caught:
        await leg.hits(query(), 20, 0.25)
    assert caught.value.reason is DegradedReason.TENCENT_UNAVAILABLE and "401" in str(caught.value)


async def test_hostile_answers_are_bounded(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas"))
    _c, leg, sink = build(sidecar.url, store)
    await sink.resync()
    sidecar.mode = "flood"
    result = await leg.hits(query(), 5, 0.5)
    assert result.hits == ()  # 5 000 ghost ids: at most 100 are read, none resolves
    sidecar.mode = "huge"
    with pytest.raises(LegDegraded) as caught:
        await leg.hits(query(), 5, 0.5)
    assert "too large" in str(caught.value)


# ------------------------------------------------------------------ breaker
def test_breaker_opens_after_three_failures_and_closes_on_a_good_trial(clock):
    breaker = CircuitBreaker(clock=clock)
    assert breaker.allow()
    assert [breaker.record_failure() for _ in range(3)] == [False, False, True]
    assert not breaker.allow() and breaker.is_open
    clock.now += BREAKER_OPEN_S - 1
    assert not breaker.allow()
    clock.now += 1
    assert breaker.allow()  # the one half-open trial
    assert not breaker.allow()  # no second concurrent trial
    assert breaker.record_success() is True
    assert breaker.allow() and not breaker.is_open


def test_breaker_failed_trial_reopens_for_a_full_period(clock):
    breaker = CircuitBreaker(clock=clock)
    for _ in range(3):
        breaker.record_failure()
    clock.now += BREAKER_OPEN_S
    assert breaker.allow()
    assert breaker.record_failure() is True
    assert not breaker.allow()
    clock.now += BREAKER_OPEN_S - 1
    assert not breaker.allow()
    clock.now += 1
    assert breaker.allow()


def test_two_failures_then_a_success_never_open_the_breaker(clock):
    breaker = CircuitBreaker(clock=clock)
    for _ in range(5):
        assert breaker.record_failure() is False
        assert breaker.record_failure() is False
        assert breaker.allow() and not breaker.is_open
        breaker.record_success()
    assert breaker.allow() and not breaker.is_open


async def test_breaker_stops_calls_then_recovers_end_to_end(store, sidecar, clock):
    seed(store, make_note("a1", "Atlas", "atlas"))
    _c, leg, sink = build(sidecar.url, store, clock)
    await sink.resync()
    sidecar.mode = "error500"
    sidecar.requests.clear()
    for _ in range(3):
        with pytest.raises(LegDegraded):
            await leg.hits(query(), 20, 0.25)
    assert len(sidecar.requests) == 3
    assert leg.status().status is CapabilityStatus.DEGRADED and leg.status().reason_code == "tencent_unavailable"
    with pytest.raises(LegDegraded) as caught:  # open: refused at once, no request
        await leg.hits(query(), 20, 0.25)
    assert caught.value.reason is DegradedReason.TENCENT_UNAVAILABLE and "circuit open" in str(caught.value)
    assert len(sidecar.requests) == 3
    sidecar.mode = "normal"
    assert leg.status().status is CapabilityStatus.DEGRADED  # still open until the period passes
    clock.now += BREAKER_OPEN_S
    result = await leg.hits(query(), 20, 0.25)
    assert [h.memory_id for h in result.hits] == ["a1"]
    assert leg.status().is_ok
    assert len(sidecar.requests) == 4


async def test_timeouts_and_malformed_answers_count_toward_the_breaker(store, sidecar, clock):
    seed(store, make_note("a1", "Atlas", "atlas"))
    _c, leg, _s = build(sidecar.url, store, clock)
    sidecar.mode, sidecar.delay = "slow", 1.0
    for _ in range(3):
        with pytest.raises(LegDegraded):
            await leg.hits(query(), 20, 0.1)
    sidecar.requests.clear()
    sidecar.mode = "normal"
    with pytest.raises(LegDegraded):
        await leg.hits(query(), 20, 0.25)
    assert sidecar.requests == []
    # a malformed shape (not just a transport failure) also counts
    _c2, leg2, _s2 = build(sidecar.url, store, clock)
    sidecar.mode = "wrong_shape"
    for _ in range(3):
        with pytest.raises(LegDegraded):
            await leg2.hits(query(), 20, 0.25)
    sidecar.requests.clear()
    with pytest.raises(LegDegraded):
        await leg2.hits(query(), 20, 0.25)
    assert sidecar.requests == []


# ------------------------------------------------------------------ canonical writes and mirror
async def test_canonical_writes_succeed_with_the_sidecar_down(store, sidecar):
    client = TencentClient(TencentConfig(sidecar.url, mirror_timeout_s=0.3), lambda: TOKEN)
    sink = TencentMirrorSink(client, store)
    await sidecar.stop()
    await sink.start()
    try:
        created = store.create(make_note("w1", "Written", "written while down"))
        sink.notify_written("w1")
        await asyncio.sleep(0.2)  # the worker tries, fails, and keeps going
        assert store.get("w1").body == created.body
        revised = store.revise("w1", MemoryPatch(body="still writing"), 1)
        sink.notify_written("w1")
        assert revised.revision == 2
        for _ in range(60):  # the worker fails in the background; the writes above never waited for it
            if sink.status().reason_code == "tencent_mirror_behind":
                break
            await asyncio.sleep(0.1)
        assert sink.status().reason_code == "tencent_mirror_behind"
    finally:
        await sink.stop()


async def test_the_background_worker_mirrors_after_a_write(store, sidecar):
    _c, leg, sink = build(sidecar.url, store)
    await sink.start()
    try:
        store.create(make_note("w1", "Atlas", "atlas written"))
        sink.notify_written("w1")  # callable from any thread: here, the loop thread
        for _ in range(50):
            if adds(sidecar):
                break
            await asyncio.sleep(0.05)
        assert adds(sidecar) == 1
        assert [h.memory_id for h in (await leg.hits(query(), 20, 0.25)).hits] == ["w1"]
    finally:
        await sink.stop()


async def test_notify_before_start_and_from_another_thread_is_queued(store, sidecar):
    _c, _leg, sink = build(sidecar.url, store)
    store.create(make_note("w1", "Atlas", "atlas"))
    sink.notify_written("w1")  # before the loop runs
    await sink.start()
    try:
        for _ in range(50):
            if adds(sidecar):
                break
            await asyncio.sleep(0.05)
        assert adds(sidecar) == 1
        store.create(make_note("w2", "Atlas two", "atlas two"))
        await asyncio.to_thread(sink.notify_written, "w2")
        for _ in range(50):
            if adds(sidecar) == 2:
                break
            await asyncio.sleep(0.05)
        assert adds(sidecar) == 2
    finally:
        await sink.stop()


async def test_notify_overflow_loses_writes_quietly_and_reports_it(store, sidecar):
    _c, _leg, sink = build(sidecar.url, store)
    for index in range(MAX_PENDING + 5):
        sink.notify_written(f"id{index}")
    assert sink.status().reason_code == "tencent_mirror_behind"


async def test_resync_is_idempotent_and_never_duplicates(store, sidecar, tmp_path):
    seed(store, make_note("a1", "Atlas", "atlas one"), make_note("a2", "Atlas two", "atlas two"), make_note("p1", "Pri", "atlas", scope="private"))
    ledger_path = tmp_path / "ledger.json"
    client = TencentClient(TencentConfig(sidecar.url), lambda: TOKEN)
    sink = TencentMirrorSink(client, store, ledger=MirrorLedger(ledger_path))
    first = await sink.resync()
    assert (first.pushed, first.unchanged, first.failed) == (2, 0, 0)
    assert adds(sidecar) == 2
    second = await sink.resync()
    assert (second.pushed, second.unchanged, second.removed) == (0, 2, 0)
    assert adds(sidecar) == 2
    # a restart with the persisted ledger does not push again either
    again = TencentMirrorSink(TencentClient(TencentConfig(sidecar.url), lambda: TOKEN), store, ledger=MirrorLedger(ledger_path))
    assert (await again.resync()).unchanged == 2 and adds(sidecar) == 2
    # a revision replaces the mirrored message instead of adding a second one
    store.revise("a1", MemoryPatch(body="atlas one revised"), 1)
    third = await sink.resync()
    assert third.pushed == 1 and third.unchanged == 1
    bucket = sidecar.store[("jarvis", "owner", "jarvis")]
    assert sum("[jarvis:a1:" in content for content in bucket.values()) == 1
    # superseding a note unmirrors it
    store.revise("a2", MemoryPatch(superseded_by="a1"), 1)
    fourth = await sink.resync()
    assert fourth.removed == 1 and len(bucket) == 1


async def test_resync_with_the_sidecar_down_reports_and_stops_early(store, sidecar):
    seed(store, *(make_note(f"n{i}", f"Atlas {i}", "atlas") for i in range(6)))
    _c, _leg, sink = build(sidecar.url, store)
    await sidecar.stop()
    report = await sink.resync()
    assert report.pushed == 0 and report.stopped == "circuit_open" and report.failed == 3
    assert sink.status().reason_code == "tencent_mirror_behind"


async def test_resync_repairs_after_an_outage(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas"))
    client, leg, sink = build(sidecar.url, store)
    sidecar.mode = "error500"
    assert (await sink.resync()).failed == 1
    sidecar.mode = "normal"
    assert (await sink.resync()).pushed == 1
    assert [h.memory_id for h in (await leg.hits(query(), 20, 0.25)).hits] == ["a1"]


def test_ledger_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{not json", encoding="utf-8")
    assert MirrorLedger(path).ids() == []


# ------------------------------------------------------------------ disabled and wiring
@pytest.fixture
def socket_guard(monkeypatch):
    """Any attempt to open or resolve a connection fails the test and is recorded.

    Hooks the asyncio and socket entry points, not `socket.connect`: on Windows the
    event loop's own self-pipe (`socketpair`) is a loopback connect and must keep working.
    """

    calls: list[str] = []

    def refuse(name):
        def guard(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"network call attempted: {name}")
        return guard

    targets = [
        (socket, "getaddrinfo"), (socket, "create_connection"),
        (asyncio.BaseEventLoop, "create_connection"), (asyncio.BaseEventLoop, "getaddrinfo"),
        (asyncio.BaseEventLoop, "sock_connect"), (asyncio.BaseEventLoop, "open_connection"),
    ]
    for owner, name in targets:
        if hasattr(owner, name):
            monkeypatch.setattr(owner, name, refuse(name))
    for loop_class in ("ProactorEventLoop", "SelectorEventLoop"):
        owner = getattr(asyncio, loop_class, None)
        if owner is not None:
            monkeypatch.setattr(owner, "sock_connect", refuse("sock_connect"))
    return calls


async def test_disabled_by_default_makes_zero_network_calls(store, socket_guard):
    seed(store, make_note("a1", "Atlas", "atlas"))
    # The guard is live: a real attempt to reach a sidecar is stopped and recorded.
    probe = TencentMemoryRetriever(TencentClient(TencentConfig("http://127.0.0.1:9"), lambda: ""), store)
    with pytest.raises(LegDegraded):
        await probe.hits(query(), 20, 0.25)
    assert socket_guard, "the guard must record the attempted connection"
    socket_guard.clear()
    # The disabled path never gets that far.
    assert TencentSettings().enabled is False
    assert register_retriever(TencentSettings(), {}, store) is None
    assert register_retriever(TencentSettings(enabled=False, url="http://127.0.0.1:1"), {}, store) is None
    hybrid = HybridRetriever([LexicalRetriever(store)])
    result = await hybrid.recall(query(), RecallBudget())
    assert [i.memory_id for i in result.items] == ["a1"] and result.degraded == ()
    assert socket_guard == []


async def test_enabled_registration_builds_without_any_network_or_probe(store, socket_guard, tmp_path):
    registration = register_retriever(
        TencentSettings(enabled=True, url="http://127.0.0.1:8420"), {}, store, ledger_path=tmp_path / "l.json",
    )
    assert registration is not None and registration.sink is not None
    assert registration.leg.status().is_ok  # cheap, no probe
    await registration.start()
    await registration.aclose()
    assert socket_guard == []


async def test_registration_signature_end_to_end(store, sidecar, monkeypatch):
    monkeypatch.setenv("JARVIS_TENCENT_TOKEN", TOKEN)
    seed(store, make_note("a1", "Atlas", "atlas wired"))
    registration = register_retriever(TencentSettings(enabled=True, url=sidecar.url), {}, store)
    assert registration is not None
    try:
        await registration.start()
        registration.sink.notify_written("a1")
        for _ in range(50):
            if adds(sidecar):
                break
            await asyncio.sleep(0.05)
        assert adds(sidecar) == 1
        hybrid = HybridRetriever([LexicalRetriever(store), registration.leg])
        result = await hybrid.recall(query(), RecallBudget())
        assert dict(result.items[0].rank_sources) == {"lexical": 1, "tencent": 1}
    finally:
        await registration.aclose()


async def test_token_comes_from_credentials_on_every_call(store, sidecar, monkeypatch):
    seed(store, make_note("a1", "Atlas", "atlas"))
    monkeypatch.setenv("JARVIS_TENCENT_TOKEN", "wrong")
    registration = register_retriever(TencentSettings(enabled=True, url=sidecar.url), {}, store)
    try:
        with pytest.raises(LegDegraded):
            await registration.leg.hits(query(), 20, 0.25)
        monkeypatch.setenv("JARVIS_TENCENT_TOKEN", TOKEN)  # saved later: no restart
        registration.client.breaker.record_success()
        await registration.sink.resync()
        assert [h.memory_id for h in (await registration.leg.hits(query(), 20, 0.25)).hits] == ["a1"]
        assert sidecar.requests[-1].authorization == f"Bearer {TOKEN}"
    finally:
        await registration.aclose()


async def test_refused_url_never_calls_out_and_reports_unavailable(store, socket_guard):
    registration = register_retriever(
        TencentSettings(enabled=True, url="http://user:hunter2@127.0.0.1:8420"), {}, store,
    )
    assert registration is not None and registration.sink is None
    state = registration.leg.status()
    assert state.status is CapabilityStatus.UNAVAILABLE and state.reason_code == "tencent_config_invalid"
    assert "hunter2" not in state.reason
    with pytest.raises(LegDegraded):
        await registration.leg.hits(query(), 20, 0.25)
    assert socket_guard == []


def test_url_validation():
    assert validate_url("http://127.0.0.1:8420/") == "http://127.0.0.1:8420"
    assert validate_url("http://localhost:8420") == "http://localhost:8420"
    assert validate_url("https://memory.example.com/api/") == "https://memory.example.com/api"
    for bad in (
        "ftp://127.0.0.1", "http://", "127.0.0.1:8420", "http://memory.example.com", "http://u:p@127.0.0.1",
        "https://h.example/?token=x", "https://h.example/#frag", "http://127.0.0.1:notaport",
    ):
        with pytest.raises(TencentConfigError):
            validate_url(bad)


# ------------------------------------------------------------------ secrets
async def test_the_token_never_appears_in_status_errors_logs_or_ledger(store, sidecar, caplog, tmp_path):
    caplog.set_level(logging.DEBUG, logger="jarvis")
    seed(store, make_note("a1", "Atlas", "atlas"))
    ledger_path = tmp_path / "ledger.json"
    client = TencentClient(TencentConfig(sidecar.url), lambda: TOKEN)
    leg, sink = TencentMemoryRetriever(client, store), TencentMirrorSink(client, store, ledger=MirrorLedger(ledger_path))
    texts: list[str] = []
    await sink.resync()
    assert sidecar.requests[0].authorization == f"Bearer {TOKEN}"  # it IS sent, just never shown
    for mode in ("error500", "malformed", "refuse", "wrong_shape"):
        sidecar.mode = mode
        client.breaker.record_success()
        try:
            await leg.hits(query(), 20, 0.25)
        except LegDegraded as exc:
            texts.append(str(exc))
        texts.append(leg.status().reason)
        texts.append(sink.status().reason)
    await sidecar.stop()
    client.breaker.record_success()
    try:
        await leg.hits(query(), 20, 0.25)
    except LegDegraded as exc:
        texts.append(str(exc))
        texts.append(repr(exc.__cause__))
    texts.append(leg.status().reason)
    texts += [record.getMessage() for record in caplog.records]
    texts.append(ledger_path.read_text(encoding="utf-8"))
    assert texts and all(TOKEN not in text for text in texts)
    assert not any(TOKEN in str(getattr(record, "exc_info", "")) for record in caplog.records)


# ------------------------------------------------------------------ transport details
async def test_transport_never_follows_redirects_or_reads_proxy_env(store):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"location": "http://evil.example/"})

    client = TencentClient(TencentConfig("http://127.0.0.1:8420"), lambda: TOKEN, transport=httpx.MockTransport(handler))
    leg = TencentMemoryRetriever(client, store)
    with pytest.raises(LegDegraded):
        await leg.hits(query(), 20, 0.25)
    assert len(seen) == 1 and str(seen[0].url) == "http://127.0.0.1:8420/v3/conversation/search"
    await client.aclose()


# ------------------------------------------------------------------ rework: wire shapes (upstream doc @0468a2a)
async def test_delete_uses_message_ids_and_the_fake_rejects_the_old_shape(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas one"))
    _c, _leg, sink = build(sidecar.url, store)
    await sink.resync()
    store.revise("a1", MemoryPatch(body="atlas revised"), 1)
    assert (await sink.resync()).pushed == 1
    deletes = [r for r in sidecar.requests if r.path.endswith("/delete")]
    assert len(deletes) == 1 and "ids" not in deletes[0].body and deletes[0].body["message_ids"] == ["msg_1"]
    async with httpx.AsyncClient() as http:  # the fake itself holds to the real shape
        for bad in ({"ids": ["x"]}, {}, {"message_ids": []}):
            reply = await http.post(sidecar.url + "/v3/conversation/delete", json=bad, headers={"Authorization": f"Bearer {TOKEN}"})
            assert reply.status_code == 400


async def test_service_id_header_is_sent_when_configured_and_required_by_the_fake(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas"))
    sidecar.service_id = "svc-1"
    _c, leg, _s = build(sidecar.url, store)  # no service id: the data plane refuses
    with pytest.raises(LegDegraded) as caught:
        await leg.hits(query(), 20, 0.25)
    assert "401" in str(caught.value)
    client = TencentClient(TencentConfig(sidecar.url, service_id="svc-1"), lambda: TOKEN)
    sink, leg = TencentMirrorSink(client, store), TencentMemoryRetriever(client, store)
    assert (await sink.resync()).pushed == 1
    assert [h.memory_id for h in (await leg.hits(query(), 20, 0.25)).hits] == ["a1"]
    assert {r.service_id for r in sidecar.requests[-2:]} == {"svc-1"}
    with pytest.raises(TencentConfigError):
        TencentConfig(sidecar.url, service_id="bad id with spaces")


async def test_register_retriever_passes_the_service_id(store, sidecar, monkeypatch):
    monkeypatch.setenv("JARVIS_TENCENT_TOKEN", TOKEN)
    sidecar.service_id = "svc-9"
    seed(store, make_note("a1", "Atlas", "atlas"))
    registration = register_retriever(TencentSettings(enabled=True, url=sidecar.url), {}, store, service_id="svc-9")
    try:
        assert (await registration.sink.resync()).pushed == 1
        assert [h.memory_id for h in (await registration.leg.hits(query(), 20, 0.25)).hits] == ["a1"]
    finally:
        await registration.aclose()


async def test_the_add_message_has_a_documented_role_and_session(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas"))
    _c, _leg, sink = build(sidecar.url, store)
    await sink.resync()
    add = next(r for r in sidecar.requests if r.path.endswith("/add"))
    assert add.body["session_id"] and add.body["messages"][0]["role"] == "user"
    assert len(add.body["messages"][0]["content"]) <= 8_192


# ------------------------------------------------------------------ rework: breaker never wedges
class TokenBox:
    def __init__(self, value="") -> None:
        self.value = value
        self.error: Exception | None = None

    def __call__(self):
        if self.error is not None:
            raise self.error
        return self.value


async def _open_breaker(sidecar, leg, clock):
    sidecar.mode = "error500"
    for _ in range(3):
        with pytest.raises(LegDegraded):
            await leg.hits(query(), 20, 0.25)
    sidecar.mode = "normal"
    clock.now += BREAKER_OPEN_S


async def test_a_half_open_trial_that_raises_does_not_wedge_the_breaker(store, sidecar, clock):
    seed(store, make_note("a1", "Atlas", "atlas"))
    box = TokenBox(TOKEN)
    client = TencentClient(TencentConfig(sidecar.url), box, breaker=CircuitBreaker(clock=clock))
    leg, sink = TencentMemoryRetriever(client, store), TencentMirrorSink(client, store)
    await sink.resync()
    await _open_breaker(sidecar, leg, clock)
    box.error = RuntimeError("credential store exploded")
    with pytest.raises(LegDegraded) as caught:  # the trial raises something that is not a TencentError
        await leg.hits(query(), 20, 0.25)
    assert caught.value.reason is DegradedReason.TENCENT_UNAVAILABLE and "RuntimeError" in str(caught.value)
    assert "exploded" not in str(caught.value)
    assert client.breaker.is_open  # a failed trial re-opens it for a full period
    clock.now += BREAKER_OPEN_S
    box.error = None
    result = await leg.hits(query(), 20, 0.25)  # not wedged: the next trial runs and closes it
    assert [h.memory_id for h in result.hits] == ["a1"] and not client.breaker.is_open


async def test_a_cancelled_half_open_trial_releases_the_breaker(store, sidecar, clock):
    seed(store, make_note("a1", "Atlas", "atlas"))
    client = TencentClient(TencentConfig(sidecar.url), lambda: TOKEN, breaker=CircuitBreaker(clock=clock))
    leg, sink = TencentMemoryRetriever(client, store), TencentMirrorSink(client, store)
    await sink.resync()
    await _open_breaker(sidecar, leg, clock)
    sidecar.mode, sidecar.delay = "slow", 5.0
    task = asyncio.create_task(leg.hits(query(), 20, 10.0))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    sidecar.mode = "normal"
    assert [h.memory_id for h in (await leg.hits(query(), 20, 0.25)).hits] == ["a1"]


async def test_a_deeply_nested_answer_is_a_counted_failure_not_a_recursion_crash(store, sidecar, clock):
    seed(store, make_note("a1", "Atlas", "atlas"))
    _c, leg, _s = build(sidecar.url, store, clock)
    sidecar.mode = "deep"
    for _ in range(3):
        with pytest.raises(LegDegraded) as caught:
            await leg.hits(query(), 20, 0.5)
        assert "not JSON" in str(caught.value)
    sidecar.requests.clear()
    with pytest.raises(LegDegraded):
        await leg.hits(query(), 20, 0.25)
    assert sidecar.requests == []  # the three bad answers opened the breaker


async def test_a_non_ascii_token_is_refused_cleanly_and_never_quoted(store, sidecar, caplog):
    caplog.set_level(logging.DEBUG, logger="jarvis")
    seed(store, make_note("a1", "Atlas", "atlas"))
    bad = "tök€n-SECRETß"
    leg = TencentMemoryRetriever(TencentClient(TencentConfig(sidecar.url), lambda: bad), store)
    with pytest.raises(LegDegraded) as caught:
        await leg.hits(query(), 20, 0.25)
    texts = [str(caught.value), repr(caught.value.__cause__), leg.status().reason, *[r.getMessage() for r in caplog.records]]
    for text in texts:
        assert not any(fragment in text for fragment in ("ö", "€", "ß", "SECRET", "position"))
    assert "cannot carry" in str(caught.value)
    assert sidecar.requests == []  # refused before any network
    for odd in ("tok en", "tok\nen", 5):
        other = TencentMemoryRetriever(TencentClient(TencentConfig(sidecar.url), lambda odd=odd: odd), store)
        with pytest.raises(LegDegraded):
            await other.hits(query(), 20, 0.25)
    assert sidecar.requests == []


async def test_gzip_bomb_is_refused_without_decoding_and_identity_is_requested(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas"))
    _c, leg, _s = build(sidecar.url, store)
    sidecar.mode = "gzip_bomb"
    started = time.perf_counter()
    with pytest.raises(LegDegraded) as caught:
        await leg.hits(query(), 20, 1.0)
    assert "compressed" in str(caught.value) and time.perf_counter() - started < 1.0
    assert sidecar.requests[-1].accept_encoding == "identity"


# ------------------------------------------------------------------ rework: leg pool, mirror polish
class BlockingStore:
    """A store whose `get` hangs until released: the leg's pool must not starve the loop's executor."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.gate = threading.Event()

    def get(self, memory_id):
        self.gate.wait(10)
        return self.inner.get(memory_id)

    def list(self, filters):
        return self.inner.list(filters)


async def test_a_hung_store_call_reports_leg_busy_and_does_not_starve_the_default_executor(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas"))
    _c, _leg, sink = build(sidecar.url, store)
    await sink.resync()
    blocked = BlockingStore(store)
    leg = TencentMemoryRetriever(TencentClient(TencentConfig(sidecar.url), lambda: TOKEN), blocked)
    try:
        for _ in range(2):  # both pool workers are now stuck in `get`
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(leg.hits(query(), 20, 5.0), 0.3)
        with pytest.raises(LegDegraded) as caught:
            await leg.hits(query(), 20, 0.25)
        assert caught.value.reason is DegradedReason.LEG_BUSY
        assert await asyncio.wait_for(asyncio.to_thread(lambda: 1), 1.0) == 1  # the default executor is free
    finally:
        blocked.gate.set()
    for _ in range(50):
        if leg._pool.inflight == 0:  # noqa: SLF001
            break
        await asyncio.sleep(0.05)
    assert [h.memory_id for h in (await leg.hits(query(), 20, 0.25)).hits] == ["a1"]


async def test_resync_clears_the_dropped_counter(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas"))
    _c, _leg, sink = build(sidecar.url, store)
    for index in range(MAX_PENDING + 3):
        sink.notify_written(f"id{index}")
    assert sink.status().reason_code == "tencent_mirror_behind"
    report = await sink.resync()
    assert report.failed == 0 and report.stopped == ""
    assert sink.status().is_ok


async def test_a_failed_push_is_retried_with_backoff_while_writes_keep_arriving(store, sidecar, clock):
    seed(store, make_note("a1", "Atlas one", "atlas one"), make_note("a2", "Atlas two", "atlas two"))
    client = TencentClient(TencentConfig(sidecar.url, mirror_timeout_s=1.0), lambda: TOKEN)
    sink = TencentMirrorSink(client, store, retry_interval_s=100.0, clock=clock)
    sidecar.mode = "error500"
    await sink.start()
    try:
        sink.notify_written("a1")
        for _ in range(60):
            if sink.status().reason_code == "tencent_mirror_behind":
                break
            await asyncio.sleep(0.05)
        assert sink.status().reason_code == "tencent_mirror_behind"
        sidecar.mode = "normal"
        bucket = sidecar.store.setdefault(("jarvis", "owner", "jarvis"), {})
        sink.notify_written("a2")  # a write arrives, but a1's backoff is not over: it waits
        for _ in range(60):
            if len(bucket) == 1:
                break
            await asyncio.sleep(0.05)
        assert len(bucket) == 1 and sink.status().reason_code == "tencent_mirror_behind"
        clock.now += 100.0  # backoff over; the next write wakes the worker, which requeues a1 too
        sink.notify_written("a2")
        for _ in range(60):
            if len(bucket) == 2:
                break
            await asyncio.sleep(0.05)
        assert len(bucket) == 2 and sink.status().is_ok
    finally:
        await sink.stop()


async def test_resync_and_a_push_of_the_same_note_never_duplicate(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas"))
    _c, _leg, sink = build(sidecar.url, store)
    await asyncio.gather(sink.resync(), sink.push("a1"), sink.push("a1"), sink.resync())
    assert adds(sidecar) == 1
    assert len(sidecar.store[("jarvis", "owner", "jarvis")]) == 1


async def test_delete_goes_to_the_bucket_where_the_note_was_written(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas", agent="newagent"))
    client = TencentClient(TencentConfig(sidecar.url), lambda: TOKEN)
    ledger = MirrorLedger()
    ledger.set("a1", _Entry("stale-digest", ("msg_old",), "oldagent"))
    sink = TencentMirrorSink(client, store, ledger=ledger)
    await sink.push("a1")
    delete = next(r for r in sidecar.requests if r.path.endswith("/delete"))
    add = next(r for r in sidecar.requests if r.path.endswith("/add"))
    assert delete.body["agent_id"] == "oldagent" and add.body["agent_id"] == "newagent"


async def test_the_ledger_is_written_once_per_batch_off_the_loop(store, sidecar, tmp_path, monkeypatch):
    seed(store, *(make_note(f"n{i}", f"Atlas {i}", "atlas") for i in range(5)))
    ledger_path = tmp_path / "ledger.json"
    ledger = MirrorLedger(ledger_path)
    writes: list[str] = []
    original = ledger._write  # noqa: SLF001

    def counting(payload):
        writes.append(threading.current_thread().name)
        original(payload)

    monkeypatch.setattr(ledger, "_write", counting)
    sink = TencentMirrorSink(TencentClient(TencentConfig(sidecar.url), lambda: TOKEN), store, ledger=ledger)
    await sink.resync()
    assert len(writes) == 1 and writes[0] != threading.main_thread().name
    assert len(json.loads(ledger_path.read_text(encoding="utf-8"))["entries"]) == 5
    assert not ledger_path.with_name("ledger.json.tmp").exists()
    await sink.resync()
    assert len(writes) == 1  # nothing changed, nothing written


def test_ledger_loading_rejects_malformed_ids(tmp_path):
    path = tmp_path / "ledger.json"
    for ids in ("msg_1", {"a": 1}, [1, 2], None):
        path.write_text(json.dumps({"version": 1, "entries": {"a1": {"digest": "d", "ids": ids, "agent": "x"}}}), encoding="utf-8")
        assert MirrorLedger(path).ids() == []
    path.write_text(json.dumps({"version": 1, "entries": {"a1": {"digest": "d", "ids": ["m1"], "agent": "x"}}}), encoding="utf-8")
    assert MirrorLedger(path).ids() == ["a1"]


async def test_a_failing_mirror_does_not_degrade_recall(store, sidecar, monkeypatch):
    monkeypatch.setenv("JARVIS_TENCENT_TOKEN", TOKEN)
    seed(store, make_note("a1", "Atlas", "atlas"))
    registration = register_retriever(TencentSettings(enabled=True, url=sidecar.url), {}, store)
    try:
        assert registration.mirror_client is not registration.client
        assert registration.mirror_client.breaker is not registration.client.breaker
        await registration.sink.resync()
        store.create(make_note("a2", "Atlas two", "atlas two"))
        sidecar.mode = "error500"
        for _ in range(4):
            await registration.sink.resync()
        assert registration.mirror_client.breaker.is_open
        sidecar.mode = "normal"
        assert not registration.client.breaker.is_open and registration.leg.status().is_ok
        assert [h.memory_id for h in (await registration.leg.hits(query(), 20, 0.25)).hits] == ["a1"]
    finally:
        await registration.aclose()


async def test_marker_in_the_middle_of_a_hit_is_dropped(store, sidecar):
    seed(store, make_note("a1", "Atlas", "atlas"))
    _c, leg, sink = build(sidecar.url, store)
    await sink.resync()
    assert [h.memory_id for h in (await leg.hits(query(), 20, 0.25)).hits] == ["a1"]
    sidecar.mode = "midmarker"
    assert (await leg.hits(query(), 20, 0.25)).hits == ()
