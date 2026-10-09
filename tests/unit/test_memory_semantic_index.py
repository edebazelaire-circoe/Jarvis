"""Semantic index, retriever and OpenAI embedder (handoff jarvis-memory-intelligence-knowledge, Slice 03).

Real `MarkdownMemoryBackend` in a temp dir, `FakeEmbedder` (deterministic, no
network), `httpx.MockTransport` for the remote provider (no network either).
Covers the derived-index contract: chunking, rebuild after a model change or a
deleted/corrupt/old file, capacity guard, async queue off the write path,
degraded legs leaving lexical recall intact, scope, supersession, validity.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import threading
import time

import httpx
import pytest

from jarvis.adapters import memory_semantic
from jarvis.adapters.embedding_openai import OpenAIEmbedder, openai_embedder_from_settings
from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
from jarvis.adapters.memory_lexical import LexicalRetriever
from jarvis.adapters.memory_semantic import (
    CHUNK_CHARS,
    SCHEMA_VERSION,
    SemanticCapacityExceeded,
    SemanticIndex,
    SemanticRetriever,
    chunk_body,
    embedding_texts,
)
from jarvis.core.memory_hybrid import HybridRetriever
from jarvis.domain.memory import (
    CapabilityStatus,
    DegradedReason,
    MemoryErrorCode,
    MemoryKind,
    MemoryLevel,
    MemoryNote,
    MemoryPatch,
    MemoryStoreError,
    RecallBudget,
    RecallQuery,
    RetentionClass,
)
from tests.fakes.fake_embedder import FakeEmbedder

T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
CONCEPTS = {"voiture": "car", "auto": "car", "car": "car", "chat": "cat", "cat": "cat", "felin": "cat"}


def make_note(note_id: str, title: str, body: str = "", **over) -> MemoryNote:
    base = dict(
        id=note_id, title=title, body=body, level=MemoryLevel.L1, kind=MemoryKind.FACT,
        retention=RetentionClass.LONG_TERM, scope="private", created_at=T0, updated_at=T0,
    )
    return MemoryNote(**{**base, **over})


@pytest.fixture
def store(tmp_path: Path) -> MarkdownMemoryBackend:
    return MarkdownMemoryBackend(tmp_path / "memory")


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder(dim=64, concepts=CONCEPTS)


def make_index(store, embedder, **options) -> SemanticIndex:
    options.setdefault("allow_private", True)
    return SemanticIndex(store.meta_dir / "semantic.sqlite3", embedder, store, **options)


def hybrid_of(store, index) -> HybridRetriever:
    return HybridRetriever([LexicalRetriever(store), SemanticRetriever(index)])


def query(text: str, *scopes: str, **over) -> RecallQuery:
    return RecallQuery(text=text, scopes=scopes or ("private",), **over)


def recalled(result) -> list[str]:
    return [item.memory_id for item in result.items]


def seed_cars(store) -> None:
    store.create(make_note("car-fr", "Voiture", "révision annuelle"))
    store.create(make_note("cat-fr", "Chat", "croquettes du soir"))


# ------------------------------------------------------------------------ chunking
def test_a_short_note_is_one_chunk():
    assert chunk_body("x" * (CHUNK_CHARS - 1)) == ["x" * (CHUNK_CHARS - 1)]
    assert chunk_body("") == [""]


def test_a_long_note_is_cut_into_paragraph_windows():
    paragraphs = [f"paragraph {n} " + "w" * 700 for n in range(6)]
    chunks = chunk_body("\n\n".join(paragraphs))

    assert len(chunks) == 3  # two 700-char paragraphs fit one window of 1 500
    assert all(len(chunk) <= CHUNK_CHARS for chunk in chunks)
    assert "\n\n".join(chunks) == "\n\n".join(paragraphs)  # paragraphs are never split here


def test_a_paragraph_larger_than_a_window_is_hard_cut():
    chunks = chunk_body("y" * 4_000)

    assert [len(chunk) for chunk in chunks] == [1_500, 1_500, 1_000]


def test_the_title_prefixes_every_chunk():
    note = make_note("long", "Titre", "\n\n".join(["p" * 900, "q" * 900]))

    texts = embedding_texts(note)

    assert len(texts) == 2 and all(text.startswith("Titre\n") for text in texts)


# ------------------------------------------------------------ index file and contract
async def test_index_stores_normalised_float32_blobs_with_a_user_version(store, embedder):
    store.create(make_note("n1", "Voiture", "révision annuelle"))
    index = make_index(store, embedder)

    assert await index.reconcile() == 1

    conn = sqlite3.connect(index.path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        row = conn.execute("SELECT memory_id, revision, model_id, chunk_no, dim, length(vec) FROM chunks").fetchone()
        blob = conn.execute("SELECT vec FROM chunks").fetchone()[0]
    finally:
        conn.close()
    assert row == ("n1", 1, embedder.model_id, 0, 64, 64 * 4)
    from array import array
    vector = array("f")
    vector.frombytes(blob)
    assert sum(value * value for value in vector) == pytest.approx(1.0, abs=1e-5)
    assert index.path == store.meta_dir / "semantic.sqlite3"


async def test_reconcile_embeds_only_what_changed(store, embedder):
    seed_cars(store)
    index = make_index(store, embedder)
    assert await index.reconcile() == 2
    calls = len(embedder.calls)

    assert await index.reconcile() == 0
    assert len(embedder.calls) == calls  # same (id, revision, digest): nothing re-embedded

    store.revise("car-fr", MemoryPatch(body="vidange"), 1)
    assert await index.reconcile() == 1
    assert index.indexed()["car-fr"][0] == 2
    conn = sqlite3.connect(index.path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM chunks WHERE memory_id='car-fr'").fetchone()[0] == 1  # old revision gone
    finally:
        conn.close()


async def test_semantic_recall_finds_what_lexical_cannot(store, embedder):
    seed_cars(store)
    index = make_index(store, embedder)
    await index.reconcile()

    result = await hybrid_of(store, index).recall(query("auto"), RecallBudget())

    assert recalled(result) == ["car-fr"]  # "auto" appears in no note: only the vector leg can find it
    item = result.items[0]
    assert dict(item.rank_sources) == {"semantic": 1}
    assert item.why.startswith("semantic #1: cosine ")
    assert result.degraded == ()


async def test_pure_python_scan_ranks_like_numpy(store, embedder, monkeypatch):
    seed_cars(store)
    store.create(make_note("car-en", "Car", "annual service of the car"))
    with_numpy = make_index(store, embedder)
    await with_numpy.reconcile()
    expected = await hybrid_of(store, with_numpy).recall(query("auto voiture"), RecallBudget())

    monkeypatch.setattr(memory_semantic, "_numpy", lambda: None)
    pure = make_index(store, embedder)
    got = await hybrid_of(store, pure).recall(query("auto voiture"), RecallBudget())

    assert pure._snapshot().numpy is None and isinstance(pure._snapshot().vectors, list)
    assert [(i.memory_id, round(i.score, 9)) for i in got.items] == [(i.memory_id, round(i.score, 9)) for i in expected.items]


# ------------------------------------------------------------ rebuild: model, file, schema
async def test_a_model_change_invalidates_and_rebuilds(store):
    seed_cars(store)
    first = FakeEmbedder(dim=64, concepts=CONCEPTS, model_id="model-a")
    index = make_index(store, first)
    await index.reconcile()
    assert index.count() == 2

    second = FakeEmbedder(dim=32, concepts=CONCEPTS, model_id="model-b")
    changed = make_index(store, second)  # same file, new model

    assert not changed.ready  # the other model's vectors are gone: a rebuild is owed
    conn = sqlite3.connect(changed.path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    finally:
        conn.close()
    assert await changed.reconcile() == 2
    assert second.calls and changed.ready
    conn = sqlite3.connect(changed.path)
    try:
        assert {row[0] for row in conn.execute("SELECT DISTINCT model_id FROM chunks")} == {"model-b"}
        assert {row[0] for row in conn.execute("SELECT DISTINCT dim FROM chunks")} == {32}
    finally:
        conn.close()
    result = await hybrid_of(store, changed).recall(query("auto"), RecallBudget())
    assert recalled(result) == ["car-fr"]


async def test_a_model_swapped_on_a_live_index_is_purged_at_the_next_reconcile(store):
    seed_cars(store)
    embedder = FakeEmbedder(dim=64, concepts=CONCEPTS, model_id="model-a")
    index = make_index(store, embedder)
    await index.reconcile()

    embedder.model_id = "model-b"
    assert await index.reconcile() == 2

    assert set(index.indexed()) == {"car-fr", "cat-fr"}
    conn = sqlite3.connect(index.path)
    try:
        assert {row[0] for row in conn.execute("SELECT DISTINCT model_id FROM chunks")} == {"model-b"}
    finally:
        conn.close()


async def test_a_deleted_semantic_db_rebuilds_and_nothing_durable_is_lost(store, embedder):
    seed_cars(store)
    index = make_index(store, embedder)
    await index.reconcile()
    index.path.unlink()

    # While the file is gone: lexical recall is intact, the semantic leg says it is rebuilding.
    result = await hybrid_of(store, index).recall(query("voiture"), RecallBudget())
    assert recalled(result) == ["car-fr"]
    assert result.degraded == (DegradedReason.SEMANTIC_UNAVAILABLE,)
    assert index.path.exists() and not index.ready

    await index.sync()

    assert index.ready and index.count() == 2
    result = await hybrid_of(store, index).recall(query("auto"), RecallBudget())
    assert recalled(result) == ["car-fr"] and result.degraded == ()
    assert store.get("car-fr").body == "révision annuelle"  # canonical untouched


async def test_a_corrupt_semantic_db_is_recreated(store, embedder):
    seed_cars(store)
    path = store.meta_dir / "semantic.sqlite3"
    path.write_bytes(b"this is not a database" * 100)

    index = make_index(store, embedder)
    await index.sync()

    assert index.count() == 2 and index.ready


async def test_a_different_schema_version_is_dropped_and_rebuilt(store, embedder):
    seed_cars(store)
    index = make_index(store, embedder)
    await index.reconcile()
    conn = sqlite3.connect(index.path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 7}")
    conn.commit()
    conn.close()

    reopened = make_index(store, embedder)

    assert reopened.count() == 0 and not reopened.ready
    await reopened.sync()
    assert reopened.count() == 2
    conn = sqlite3.connect(reopened.path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        conn.close()


# ---------------------------------------------------------------- capacity guard
async def test_the_capacity_guard_degrades_the_semantic_leg_only(store, embedder):
    for number in range(5):
        store.create(make_note(f"n{number}", f"Voiture {number}", "révision"))
    index = make_index(store, embedder, capacity=3)
    await index.reconcile()
    assert index.capacity_hit and index.count() <= 3

    result = await hybrid_of(store, index).recall(query("voiture"), RecallBudget())

    assert result.degraded == (DegradedReason.SEMANTIC_CAPACITY,)
    assert len(result.items) == 5  # lexical recall continues untouched
    assert all(set(item.rank_sources) == {"lexical"} for item in result.items)
    state = SemanticRetriever(index).status()
    assert (state.status, state.reason_code) == (CapabilityStatus.DEGRADED, "semantic_capacity")


async def test_an_index_larger_than_the_capacity_refuses_to_scan(store, embedder):
    seed_cars(store)
    full = make_index(store, embedder)
    await full.reconcile()

    smaller = make_index(store, embedder, capacity=1)

    with pytest.raises(SemanticCapacityExceeded):
        smaller.search(embedder.vector("auto"), scopes=("private",))


# --------------------------------------------------- degraded legs leave lexical intact
async def test_embedder_timeout_leaves_lexical_intact_and_sets_degraded(store, embedder):
    seed_cars(store)
    index = make_index(store, embedder)
    await index.reconcile()
    embedder.delay = 1.0

    started = time.perf_counter()
    result = await hybrid_of(store, index).recall(query("voiture"), RecallBudget(semantic_timeout_ms=60))

    assert time.perf_counter() - started < 0.5
    assert recalled(result) == ["car-fr"]
    assert result.degraded == (DegradedReason.SEMANTIC_TIMEOUT,)
    assert dict(result.items[0].rank_sources) == {"lexical": 1}


async def test_embedder_exception_leaves_lexical_intact_and_sets_degraded(store, embedder):
    seed_cars(store)
    index = make_index(store, embedder)
    await index.reconcile()
    embedder.fail = MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "provider down")

    result = await hybrid_of(store, index).recall(query("voiture"), RecallBudget())

    assert recalled(result) == ["car-fr"]
    assert result.degraded == (DegradedReason.SEMANTIC_UNAVAILABLE,)
    state = SemanticRetriever(index).status()
    assert state.status is CapabilityStatus.OK  # the index itself is fine; only the query embedding failed


async def test_an_unexpected_embedder_error_is_degraded_never_raised(store, embedder):
    seed_cars(store)
    index = make_index(store, embedder)
    await index.reconcile()
    embedder.fail = ZeroDivisionError("bug in the provider")

    result = await hybrid_of(store, index).recall(query("voiture"), RecallBudget())

    assert recalled(result) == ["car-fr"] and result.degraded == (DegradedReason.SEMANTIC_UNAVAILABLE,)


async def test_a_failing_embedder_during_the_build_is_reported_and_retried(store, embedder):
    seed_cars(store)
    embedder.fail = MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "no key")
    index = make_index(store, embedder)

    assert await index.reconcile() == 0
    assert not index.ready and "no key" in index.last_error
    state = SemanticRetriever(index).status()
    assert (state.status, state.reason_code) == (CapabilityStatus.DEGRADED, "semantic_unavailable")
    result = await hybrid_of(store, index).recall(query("voiture"), RecallBudget())
    assert recalled(result) == ["car-fr"]  # lexical unaffected while the build fails

    embedder.fail = None
    await index.sync()
    assert index.ready and index.count() == 2 and index.last_error == ""


async def test_lexical_only_with_no_provider_is_fully_functional(store):
    seed_cars(store)
    hybrid = HybridRetriever([LexicalRetriever(store)])

    result = await hybrid.recall(query("voiture révision"), RecallBudget())

    assert recalled(result) == ["car-fr"]
    assert result.degraded == ()
    item = result.items[0]
    assert dict(item.rank_sources) == {"lexical": 1}
    assert item.why == "lexical #1: terms voiture, revision"
    assert item.provenance_ref == "long_term_memory/car-fr"
    assert item.revision == 1 and item.level is MemoryLevel.L1 and item.retention is RetentionClass.LONG_TERM
    assert hybrid.status().is_ok


# --------------------------------------------------- async queue, off the write path
async def test_a_write_never_embeds_inline(store, embedder):
    index = make_index(store, embedder)
    await index.sync()
    calls = len(embedder.calls)

    store.create(make_note("fresh", "Voiture", "nouvelle"))
    index.notify_written("fresh")

    assert len(embedder.calls) == calls  # notify queued it; nothing was embedded on the write path
    assert "fresh" not in index.indexed()
    await index.process_pending()
    assert index.indexed()["fresh"][0] == 1


async def test_notify_written_is_thread_safe_and_never_blocks(store, embedder):
    index = make_index(store, embedder)
    await index.sync()
    for number in range(20):
        store.create(make_note(f"t{number:02d}", f"Voiture {number}", "x"))
    workers = [threading.Thread(target=lambda n=n: index.notify_written(f"t{n:02d}")) for n in range(20)]
    started = time.perf_counter()
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert time.perf_counter() - started < 1.0
    assert await index.process_pending() == 20
    assert len(index.indexed()) == 20


async def test_the_background_worker_embeds_after_a_write(store, embedder):
    index = make_index(store, embedder, retry_interval_s=5)
    index.start()
    try:
        await _until(lambda: index.ready)
        store.create(make_note("later", "Voiture", "plus tard"))
        index.notify_written("later")
        await _until(lambda: "later" in index.indexed())
    finally:
        await index.stop()


async def test_a_failed_queue_item_is_parked_and_retried(store, embedder):
    index = make_index(store, embedder)
    await index.sync()
    store.create(make_note("retry", "Voiture", "bientôt"))
    embedder.fail = MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "down")
    index.notify_written("retry")

    assert await index.process_pending() == 0
    assert "retry" not in index.indexed() and "down" in index.last_error
    embedder.fail = None
    index.notify_written("retry")
    assert await index.process_pending() == 1
    assert "retry" in index.indexed() and index.last_error == ""


async def test_a_deleted_note_loses_its_vectors_and_never_surfaces(store, embedder):
    seed_cars(store)
    index = make_index(store, embedder)
    await index.reconcile()
    for victim in [p for p in store.root.rglob("*.md") if "car-fr" in p.read_text(encoding="utf-8")]:
        victim.unlink()
    store.rebuild_indexes()

    result = await hybrid_of(store, index).recall(query("auto"), RecallBudget())

    assert "car-fr" not in recalled(result)  # the vector row is stale: canonical says the note is gone
    await index.process_pending()  # the hydration queued the id; the worker step drops the vectors
    assert "car-fr" not in index.indexed()


# ------------------------------------------------------------- filters and policies
async def test_superseded_notes_are_excluded_by_default_in_both_legs(store, embedder):
    store.create(make_note("old", "Voiture", "ancienne adresse du garage"))
    store.create(make_note("new", "Voiture", "nouvelle adresse du garage"))
    index = make_index(store, embedder)
    await index.reconcile()
    store.revise("old", MemoryPatch(superseded_by="new"), 1)
    index.notify_written("old")
    await index.process_pending()
    hybrid = hybrid_of(store, index)

    default = await hybrid.recall(query("voiture garage"), RecallBudget())
    history = await hybrid.recall(query("voiture garage", include_history=True), RecallBudget())

    assert recalled(default) == ["new"]
    assert set(recalled(history)) == {"old", "new"}
    old = next(item for item in history.items if item.memory_id == "old")
    assert old.revision == 2


async def test_a_stale_semantic_row_cannot_resurrect_a_superseded_note(store, embedder):
    store.create(make_note("old", "Voiture", "ancienne"))
    index = make_index(store, embedder)
    await index.reconcile()
    store.revise("old", MemoryPatch(superseded_by="new"), 1)  # no notify: the vector row is still revision 1, live

    result = await hybrid_of(store, index).recall(query("auto"), RecallBudget())

    assert recalled(result) == []


async def test_the_scope_filter_applies_to_both_legs(store, embedder):
    store.create(make_note("mine", "Voiture", "privée", scope="private"))
    store.create(make_note("team", "Voiture", "partagée", scope="shared"))
    store.create(make_note("board", "Voiture", "tableau", scope="board:alpha"))
    index = make_index(store, embedder)
    await index.reconcile()
    hybrid = hybrid_of(store, index)

    only_shared = await hybrid.recall(query("voiture", "shared"), RecallBudget())
    two = await hybrid.recall(query("auto", "shared", "board:alpha"), RecallBudget())
    nothing = await hybrid.recall(RecallQuery(text="voiture", scopes=()), RecallBudget())

    assert recalled(only_shared) == ["team"]
    assert set(recalled(two)) == {"team", "board"}  # "auto" is semantic-only
    assert nothing.items == ()


async def test_retention_and_level_filters(store, embedder):
    store.create(make_note("lt", "Voiture", "a", retention=RetentionClass.LONG_TERM, level=MemoryLevel.L3))
    store.create(make_note("st", "Voiture", "b", retention=RetentionClass.SHORT_TERM, level=MemoryLevel.L1))
    index = make_index(store, embedder)
    await index.reconcile()
    hybrid = hybrid_of(store, index)

    by_retention = await hybrid.recall(query("voiture", retentions=(RetentionClass.SHORT_TERM,)), RecallBudget())
    by_level = await hybrid.recall(query("auto", levels=(MemoryLevel.L3,)), RecallBudget())

    assert recalled(by_retention) == ["st"]
    assert recalled(by_level) == ["lt"]


async def test_temporal_validity_is_filtered_in_both_legs(store, embedder):
    store.create(make_note("expired", "Voiture", "ancienne", valid_to=datetime(2020, 1, 1, tzinfo=timezone.utc)))
    store.create(make_note("future", "Voiture", "demain", valid_from=datetime(2100, 1, 1, tzinfo=timezone.utc)))
    store.create(make_note("current", "Voiture", "actuelle"))
    index = make_index(store, embedder)
    await index.reconcile()
    hybrid = hybrid_of(store, index)

    now = await hybrid.recall(query("voiture"), RecallBudget())
    semantic_only = await hybrid.recall(query("auto"), RecallBudget())
    back_then = await hybrid.recall(
        query("voiture", at=datetime(2019, 6, 1, tzinfo=timezone.utc), include_history=False), RecallBudget(),
    )
    history = await hybrid.recall(query("voiture", include_history=True), RecallBudget())

    assert recalled(now) == ["current"] and recalled(semantic_only) == ["current"]
    assert "expired" in recalled(back_then)  # at=2019: valid_to 2020 had not passed yet
    assert set(recalled(history)) == {"expired", "future", "current"}


# ---------------------------------------------------------- remote embedding privacy
class RecordingEmbedder(FakeEmbedder):
    """Stands for a remote provider: records every text it is sent."""


async def test_private_notes_are_never_sent_unless_allowed(store):
    store.create(make_note("secret", "Voiture", "mot de passe du coffre", scope="private"))
    store.create(make_note("open", "Voiture", "entretien", scope="shared"))
    remote = RecordingEmbedder(dim=64, concepts=CONCEPTS)
    index = make_index(store, remote, allow_private=False)

    await index.reconcile()

    assert set(index.indexed()) == {"open"}
    assert not any("coffre" in text for text in remote.texts_seen)

    # A query that may only reach private notes sends nothing either.
    before = len(remote.calls)
    private_only = await hybrid_of(store, index).recall(query("voiture", "private"), RecallBudget())
    assert len(remote.calls) == before
    assert recalled(private_only) == ["secret"]  # lexical still serves the owner locally

    # A mixed query searches the non-private scopes only.
    mixed = await hybrid_of(store, index).recall(query("auto", "private", "shared"), RecallBudget())
    assert recalled(mixed) == ["open"]


async def test_allow_private_embeds_private_notes(store):
    store.create(make_note("secret", "Voiture", "coffre", scope="private"))
    remote = RecordingEmbedder(dim=64, concepts=CONCEPTS)
    index = make_index(store, remote, allow_private=True)

    await index.reconcile()

    assert set(index.indexed()) == {"secret"}
    assert any("coffre" in text for text in remote.texts_seen)


async def test_turning_allow_private_off_drops_the_private_vectors(store, embedder):
    store.create(make_note("secret", "Voiture", "coffre", scope="private"))
    on = make_index(store, embedder, allow_private=True)
    await on.reconcile()
    assert "secret" in on.indexed()

    off = make_index(store, embedder, allow_private=False)
    await off.reconcile()

    assert off.indexed() == {}


# ------------------------------------------------------------------- OpenAI embedder
def openai_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def embeddings_body(vectors: list[list[float]]) -> dict:
    return {"data": [{"index": position, "embedding": vector} for position, vector in enumerate(vectors)]}


async def test_openai_embedder_posts_the_batch_and_parses_by_index():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        data = embeddings_body([[1.0, 0.0], [0.0, 1.0]])["data"]
        return httpx.Response(200, json={"data": list(reversed(data))})  # out of order on purpose

    embedder = OpenAIEmbedder("sk-test-123", dim=2, client=openai_client(handler))
    vectors = await embedder.embed(["a", "b"], timeout=2)

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    request = seen[0]
    assert request.url == "https://api.openai.com/v1/embeddings"
    assert request.headers["authorization"] == "Bearer sk-test-123"
    import json
    assert json.loads(request.content) == {"model": "text-embedding-3-small", "input": ["a", "b"], "dimensions": 2}
    assert embedder.model_id == "openai:text-embedding-3-small:2" and embedder.dim == 2


async def test_openai_embedder_without_a_key_fails_before_any_request():
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("no request without a key")

    embedder = OpenAIEmbedder("  ", client=openai_client(handler))

    with pytest.raises(MemoryStoreError) as excinfo:
        await embedder.embed(["a"], timeout=1)
    assert excinfo.value.code is MemoryErrorCode.UNAVAILABLE


async def test_openai_embedder_errors_are_coded_and_never_leak_the_key():
    key = "sk-very-secret-key"

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": f"Incorrect API key provided: {key}"}})

    embedder = OpenAIEmbedder(key, dim=2, client=openai_client(unauthorized))
    with pytest.raises(MemoryStoreError) as excinfo:
        await embedder.embed(["a"], timeout=1)
    assert excinfo.value.code is MemoryErrorCode.UNAVAILABLE
    assert "401" in str(excinfo.value) and key not in str(excinfo.value)

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach host with {key}")

    embedder = OpenAIEmbedder(key, dim=2, client=openai_client(broken))
    with pytest.raises(MemoryStoreError) as excinfo:
        await embedder.embed(["a"], timeout=1)
    assert key not in str(excinfo.value)


@pytest.mark.parametrize("answer", [
    httpx.Response(200, text="not json"),
    httpx.Response(200, json={"nope": 1}),
    httpx.Response(200, json=embeddings_body([[1.0, 2.0, 3.0]])),  # wrong dim
    httpx.Response(200, json=embeddings_body([[1.0, 0.0], [0.0, 1.0]])),  # wrong count
    httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, "x"]}]}),
])
async def test_openai_embedder_refuses_a_malformed_answer(answer):
    embedder = OpenAIEmbedder("sk-x", dim=2, client=openai_client(lambda request: answer))

    with pytest.raises(MemoryStoreError) as excinfo:
        await embedder.embed(["only one text"], timeout=1)
    assert excinfo.value.code is MemoryErrorCode.UNAVAILABLE


async def test_openai_embedder_times_out_as_unavailable():
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.0)
        return httpx.Response(200, json=embeddings_body([[1.0, 0.0]]))

    embedder = OpenAIEmbedder("sk-x", dim=2, client=openai_client(slow))

    with pytest.raises(MemoryStoreError) as excinfo:
        await embedder.embed(["a"], timeout=0.05)
    assert excinfo.value.code is MemoryErrorCode.UNAVAILABLE


async def test_openai_embedder_batches_large_inputs():
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        count = len(json.loads(request.content)["input"])
        sizes.append(count)
        return httpx.Response(200, json=embeddings_body([[1.0, 0.0]] * count))

    embedder = OpenAIEmbedder("sk-x", dim=2, client=openai_client(handler))
    vectors = await embedder.embed([f"t{n}" for n in range(150)], timeout=2)

    assert sizes == [64, 64, 22] and len(vectors) == 150


async def test_openai_embedder_reads_the_key_from_the_credential_store(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json=embeddings_body([[1.0, 0.0]]))

    embedder = openai_embedder_from_settings({}, dim=2, client=openai_client(handler))
    await embedder.embed(["a"], timeout=1)

    assert seen == ["Bearer sk-from-env"]


def test_openai_embedder_does_nothing_at_construction():
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("no network at construction")

    OpenAIEmbedder("sk-x", client=openai_client(handler))
    openai_embedder_from_settings({})


async def _until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


# ======================================================================= QA polish
# --------------------------------------------------- damage while running (item 1)
def _delete_note(store, note_id: str) -> None:
    for path in [p for p in store.root.rglob("*.md") if f'id: "{note_id}"' in p.read_text(encoding="utf-8").splitlines()]:
        path.unlink()


def _garble(path: Path) -> None:
    path.write_bytes(b"this is not a database" * 400)


def _truncate(path: Path) -> None:
    data = path.read_bytes()
    path.write_bytes(data[: max(len(data) // 2, 100)])


def _empty(path: Path) -> None:
    path.write_bytes(b"")


@pytest.mark.parametrize("damage", [_garble, _truncate, _empty], ids=["garbled", "truncated", "zero-byte"])
async def test_a_damaged_file_while_running_is_recreated_and_refilled(store, embedder, damage):
    for number in range(30):  # enough pages for a truncation to cut into
        store.create(make_note(f"n{number:02d}", f"Voiture {number}", "révision annuelle"))
    index = make_index(store, embedder)
    await index.reconcile()
    assert index.count() == 30
    damage(index.path)

    assert index.count() == 0  # the first read finds the damage, recreates the file, owes a rebuild
    assert not index.ready
    result = await hybrid_of(store, index).recall(query("voiture"), RecallBudget())
    assert result.items and DegradedReason.SEMANTIC_UNAVAILABLE in result.degraded  # lexical intact, leg says so

    await index.sync()
    assert index.ready and index.count() == 30
    again = await hybrid_of(store, index).recall(query("auto"), RecallBudget())
    assert len(again.items) > 0 and again.degraded == ()


async def test_damage_found_by_a_queued_write_is_refilled_in_the_same_step(store, embedder):
    seed_cars(store)
    index = make_index(store, embedder)
    await index.reconcile()
    _garble(index.path)
    index.notify_written("car-fr")

    await index.sync()

    assert index.ready and set(index.indexed()) == {"car-fr", "cat-fr"}


# -------------------------------------------------------- capacity guard clears (item 2)
async def test_the_capacity_flag_clears_once_removals_bring_the_index_back_under(store, embedder):
    for number in range(5):
        store.create(make_note(f"n{number}", f"Voiture {number}", "révision"))
    index = make_index(store, embedder, capacity=3)
    await index.reconcile()
    assert index.capacity_hit and index.count() == 3
    kept = sorted(index.indexed())

    index.remove(kept[:1])  # 2 chunks left, under the guard: serve again, and refill what was refused

    assert not index.capacity_hit and not index.ready
    for doomed in (f"n{i}" for i in range(5) if f"n{i}" not in kept):
        _delete_note(store, doomed)
    store.rebuild_indexes()
    await index.sync()
    assert index.ready and not index.capacity_hit
    result = await hybrid_of(store, index).recall(query("auto"), RecallBudget())
    assert result.degraded == () and result.items


# ------------------------------------------------------------ poison note (item 3)
async def test_a_note_the_embedder_refuses_is_parked_and_the_others_are_indexed(store):
    for number in range(4):
        store.create(make_note(f"ok{number}", f"Voiture {number}", "révision"))
    store.create(make_note("bad", "Voiture", "contenu POISON"))
    embedder = FakeEmbedder(dim=64, concepts=CONCEPTS, poison=["POISON"])
    index = make_index(store, embedder, retry_interval_s=0.2)

    assert await index.reconcile() == 4

    assert index.ready and index.poisoned == 1
    assert set(index.indexed()) == {f"ok{n}" for n in range(4)}
    state = SemanticRetriever(index).status()
    assert (state.status, state.reason_code) == (CapabilityStatus.DEGRADED, "semantic_unavailable")
    result = await hybrid_of(store, index).recall(query("auto"), RecallBudget())
    assert {item.memory_id for item in result.items} == {f"ok{n}" for n in range(4)}
    assert result.degraded == (DegradedReason.SEMANTIC_UNAVAILABLE,)  # partial coverage is said, not hidden

    # Backed off: an immediate second pass does not hammer the provider with the same note.
    calls = len(embedder.calls)
    await index.reconcile()
    assert len(embedder.calls) == calls

    # After the delay it is tried again; once the provider accepts it, the leg is whole.
    await asyncio.sleep(0.3)
    await index.reconcile()
    assert len(embedder.calls) == calls + 1 and index.poisoned == 1  # tried again, refused again, longer delay
    embedder.poison = []
    await asyncio.sleep(0.5)
    await index.reconcile()
    assert index.poisoned == 0 and "bad" in index.indexed() and index.last_error == ""


async def test_a_refused_note_in_the_queue_does_not_stop_the_others(store):
    for name in ("a", "b", "c"):
        store.create(make_note(name, "Voiture", "POISON" if name == "b" else "révision"))
    embedder = FakeEmbedder(dim=64, concepts=CONCEPTS, poison=["POISON"])
    index = make_index(store, embedder)
    await index.sync()
    for name in ("a", "b", "c"):
        index.notify_written(name)

    assert await index.process_pending() == 2

    assert set(index.indexed()) == {"a", "c"} and index.poisoned == 1
    index.notify_written("b")  # a new write is a new chance, no waiting out the delay
    embedder.poison = []
    assert await index.process_pending() == 1
    assert index.poisoned == 0 and "b" in index.indexed()


async def test_a_provider_that_is_down_stops_the_pass_instead_of_parking_every_note(store):
    for number in range(8):
        store.create(make_note(f"n{number}", "Voiture", "révision"))
    embedder = FakeEmbedder(dim=64, concepts=CONCEPTS, fail=MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "down"))
    index = make_index(store, embedder)

    assert await index.reconcile() == 0

    assert not index.ready and index.poisoned == 0  # owed again, nothing parked
    assert len(embedder.calls) <= 3  # stopped after the run of failures
    embedder.fail = None
    await index.sync()
    assert index.ready and len(index.indexed()) == 8


# --------------------------------------------------------- incremental snapshot (item 4)
@pytest.mark.parametrize("use_numpy", [True, False], ids=["numpy", "pure"])
async def test_a_write_moves_the_snapshot_forward_and_recall_does_not_rebuild_it(store, embedder, monkeypatch, use_numpy):
    if not use_numpy:
        monkeypatch.setattr(memory_semantic, "_numpy", lambda: None)
    seed_cars(store)
    index = make_index(store, embedder)
    await index.reconcile()
    hybrid = hybrid_of(store, index)
    await hybrid.recall(query("auto"), RecallBudget())  # builds the snapshot
    store.create(make_note("car-new", "Voiture", "nouvelle voiture"))
    store.revise("cat-fr", MemoryPatch(body="félin du jardin"), 1)
    reads: list[str] = []
    original = SemanticIndex._run
    monkeypatch.setattr(SemanticIndex, "_run", lambda self, work, after=None: (reads.append("db"), original(self, work, after))[1])

    index.notify_written("car-new")
    index.notify_written("cat-fr")
    await index.process_pending()
    reads.clear()
    result = await hybrid.recall(query("auto"), RecallBudget())

    assert reads == []  # no scan of the file, no COUNT: the snapshot and the count moved with the writes
    assert {item.memory_id for item in result.items} == {"car-fr", "car-new"}
    fresh = make_index(store, embedder)
    await fresh.reconcile()
    expected = await hybrid_of(store, fresh).recall(query("auto"), RecallBudget())
    assert [(i.memory_id, round(i.score, 9)) for i in result.items] == [(i.memory_id, round(i.score, 9)) for i in expected.items]
    cat = await hybrid.recall(query("felin"), RecallBudget())
    assert [item.memory_id for item in cat.items][:1] == ["cat-fr"] and cat.items[0].revision == 2  # old revision replaced


async def test_a_removal_moves_the_snapshot_forward(store, embedder):
    seed_cars(store)
    index = make_index(store, embedder)
    await index.reconcile()
    await hybrid_of(store, index).recall(query("auto"), RecallBudget())

    index.remove(["car-fr"])

    assert index._snapshot_cache is not None and index._snapshot_cache.generation == index._generation
    assert [row.memory_id for row in index._snapshot_cache.rows] == ["cat-fr"]
    assert index.search(embedder.vector("auto"), scopes=("private",)) == []


# ----------------------------------------------------- hung store, dedicated pools (item 5)
class SleepingStore:
    """A store whose ranked search hangs for a second (a stalled disk)."""

    def __init__(self) -> None:
        self.calls = 0
        self.delay = 1.0

    def search_ranked(self, text, limit=20, filters=None):
        self.calls += 1
        time.sleep(self.delay)
        return []


async def test_a_hung_store_thread_does_not_starve_the_pool_or_the_other_legs(store):
    seed_cars(store)
    sleeper = SleepingStore()
    stuck = HybridRetriever([LexicalRetriever(sleeper)])
    fast = HybridRetriever([LexicalRetriever(store)])
    budget = RecallBudget(lexical_timeout_ms=40)
    started = time.perf_counter()
    reasons: list[tuple] = []

    for _ in range(60):
        reasons.append((await stuck.recall(query("voiture"), budget)).degraded)

    assert time.perf_counter() - started < 0.6  # two waits of 40 ms, the rest refused at once
    assert sleeper.calls == 2  # only the pool's two workers ever entered the hung store
    assert reasons[0] == (DegradedReason.LEXICAL_TIMEOUT,)
    assert reasons[-1] == (DegradedReason.LEG_BUSY,)
    # The loop's shared executor is free, and a healthy store still answers.
    assert await asyncio.wait_for(asyncio.to_thread(lambda: "free"), 0.5) == "free"
    assert recalled(await fast.recall(query("voiture"), RecallBudget())) == ["car-fr"]
    await asyncio.sleep(1.2)  # the hung threads end: the leg serves again
    sleeper.delay = 0.0
    assert (await stuck.recall(query("voiture"), RecallBudget())).degraded == ()


async def test_leg_pool_refuses_work_past_its_workers_and_frees_a_slot_when_a_thread_ends():
    from jarvis.adapters.memory_leg_pool import LegPool
    from jarvis.domain.memory_leg import LegDegraded

    pool = LegPool("test", workers=2)
    first = asyncio.ensure_future(pool.run(time.sleep, 0.3))
    second = asyncio.ensure_future(pool.run(time.sleep, 0.3))
    await asyncio.sleep(0.05)

    with pytest.raises(LegDegraded) as excinfo:
        await pool.run(lambda: None)
    assert excinfo.value.reason is DegradedReason.LEG_BUSY
    await asyncio.gather(first, second)
    assert await pool.run(lambda: "ok") == "ok" and pool.inflight == 0


# ------------------------------------------------------------ zero-norm vectors (item 7)
def test_zero_and_non_finite_vectors_are_refused():
    for vector in ([0.0, 0.0], [float("nan"), 1.0], [float("inf"), 1.0], [1e200, 1e200]):
        with pytest.raises(MemoryStoreError) as excinfo:
            memory_semantic._normalized(vector)
        assert excinfo.value.code is MemoryErrorCode.UNAVAILABLE


async def test_a_zero_vector_is_never_stored_and_degrades_the_leg(store):
    store.create(make_note("fine", "Voiture", "révision"))
    store.create(make_note("blank", "Voiture", "ZEROVEC"))
    embedder = FakeEmbedder(dim=64, concepts=CONCEPTS, zero=["ZEROVEC"])
    index = make_index(store, embedder)

    await index.reconcile()

    assert set(index.indexed()) == {"fine"} and index.poisoned == 1
    result = await hybrid_of(store, index).recall(query("auto"), RecallBudget())
    assert recalled(result) == ["fine"] and result.degraded == (DegradedReason.SEMANTIC_UNAVAILABLE,)


async def test_a_zero_query_vector_degrades_and_lexical_answers(store, embedder):
    seed_cars(store)
    index = make_index(store, embedder)
    await index.reconcile()

    result = await hybrid_of(store, index).recall(query("le la les voiture"), RecallBudget())  # "voiture" counts: not zero
    assert recalled(result) == ["car-fr"] and result.degraded == ()
    zero = FakeEmbedder(dim=64, concepts=CONCEPTS, zero=["le la"])
    index.embedder = zero
    zero_result = await hybrid_of(store, index).recall(query("le la"), RecallBudget())
    assert zero_result.degraded == (DegradedReason.SEMANTIC_UNAVAILABLE,)


# --------------------------------------------- scope filtered before the cut (item 9)
async def test_in_scope_hits_are_not_crowded_out_by_stronger_out_of_scope_chunks(store, embedder):
    for number in range(25):  # 25 notes outside the scope, each a perfect match for "auto"
        store.create(make_note(f"other{number:02d}", "Voiture", "", scope="board:alpha"))
    store.create(make_note("mine", "Voiture entretien garage annuel", "révision complète du véhicule", scope="shared"))
    index = make_index(store, embedder)
    await index.reconcile()
    leg = SemanticRetriever(index)

    found = await leg.hits(query("auto", "shared"), 20, 1.0)
    result = await hybrid_of(store, index).recall(query("auto", "shared"), RecallBudget())

    assert [hit.memory_id for hit in found.hits] == ["mine"]
    assert recalled(result) == ["mine"]


async def test_the_default_cosine_floor_is_low_and_injectable(store, embedder):
    assert memory_semantic.DEFAULT_MIN_SCORE == 0.18
    store.create(make_note("weak", "Voiture", "un deux trois quatre cinq six sept huit"))
    index = make_index(store, embedder)
    await index.reconcile()

    default = await SemanticRetriever(index).hits(query("auto"), 20, 1.0)
    strict = await SemanticRetriever(index, min_score=0.9).hits(query("auto"), 20, 1.0)

    assert [hit.memory_id for hit in default.hits] == ["weak"]  # cosine about 0.30: kept by the lower floor
    assert strict.hits == ()


# ------------------------------------------------------------- OpenAI answers (item 8)
class _Chunks(httpx.AsyncByteStream):
    def __init__(self, parts: list[bytes]) -> None:
        self._parts = parts

    async def __aiter__(self):
        for part in self._parts:
            yield part


async def test_openai_embedder_refuses_an_oversized_answer(monkeypatch):
    from jarvis.adapters import embedding_openai

    monkeypatch.setattr(embedding_openai, "MAX_RESPONSE_BYTES", 1_000)
    declared = httpx.Response(200, content=b"x" * 5_000)  # Content-Length says it
    streamed = httpx.Response(200, stream=_Chunks([b"y" * 600, b"y" * 600]))  # no length: counted while reading

    for answer in (declared, streamed):
        embedder = OpenAIEmbedder("sk-x", dim=2, client=openai_client(lambda request, a=answer: a))
        with pytest.raises(MemoryStoreError) as excinfo:
            await embedder.embed(["a"], timeout=1)
        assert excinfo.value.code is MemoryErrorCode.UNAVAILABLE and "larger" in str(excinfo.value)


@pytest.mark.parametrize("data", [
    [{"index": 0, "embedding": [True, 0.0]}],  # a bool is not a number
    [{"index": True, "embedding": [1.0, 0.0]}],  # nor an index
    [{"index": "0", "embedding": [1.0, 0.0]}],
    [{"index": 0, "embedding": [1.0, 0.0]}, {"index": 0, "embedding": [0.0, 1.0]}],  # duplicate
    [{"index": 1, "embedding": [1.0, 0.0]}, {"index": 2, "embedding": [0.0, 1.0]}],  # missing 0
    [{"embedding": [1.0, 0.0]}],  # no index at all
    [{"index": 0, "embedding": "ab"}],
])
async def test_openai_embedder_refuses_bad_indexes_and_values(data):
    texts = ["t"] * len(data)
    embedder = OpenAIEmbedder("sk-x", dim=2, client=openai_client(lambda request: httpx.Response(200, json={"data": data})))

    with pytest.raises(MemoryStoreError) as excinfo:
        await embedder.embed(texts, timeout=1)
    assert excinfo.value.code is MemoryErrorCode.UNAVAILABLE
