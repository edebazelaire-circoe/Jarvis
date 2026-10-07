"""Recall quality on the FR + EN fixture corpus (handoff jarvis-memory-intelligence-knowledge, Slice 03).

`tests/fixtures/memory_recall/` holds a corpus (`corpus.json`), labelled
queries (`queries.json`: exact words, paraphrase with no shared word,
cross-lingual) and the concept table that makes `FakeEmbedder` place
synonyms and translations together, as a multilingual model would. The test
pins the acceptance criterion: hybrid recall@5 is at least the lexical
baseline, strictly better where the words differ, and lexical-only mode (no
embedding provider) is fully functional on its own.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
from jarvis.adapters.memory_lexical import LexicalRetriever
from jarvis.adapters.memory_semantic import SemanticIndex, SemanticRetriever
from jarvis.core.memory_hybrid import HybridRetriever
from jarvis.domain.memory import (
    MemoryKind,
    MemoryLevel,
    MemoryNote,
    RecallBudget,
    RecallQuery,
    RetentionClass,
)
from tests.fakes.fake_embedder import FakeEmbedder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "memory_recall"
T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
AT_5 = RecallBudget(max_items=5, max_item_chars=400, max_total_chars=3_000)


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


CORPUS = load("corpus.json")
QUERIES = load("queries.json")


@pytest.fixture
async def stack(tmp_path: Path):
    store = MarkdownMemoryBackend(tmp_path / "memory")
    for entry in CORPUS:
        store.create(MemoryNote(
            id=entry["id"], title=entry["title"], body=entry["body"], level=MemoryLevel.L1, kind=MemoryKind.FACT,
            retention=RetentionClass.LONG_TERM, scope="private", created_at=T0, updated_at=T0,
        ))
    embedder = FakeEmbedder(dim=256, concepts=load("concepts.json"))
    index = SemanticIndex(store.meta_dir / "semantic.sqlite3", embedder, store, allow_private=True)
    await index.reconcile()
    lexical_only = HybridRetriever([LexicalRetriever(store)])
    hybrid = HybridRetriever([LexicalRetriever(store), SemanticRetriever(index, min_score=0.15)])
    return lexical_only, hybrid


async def recall_at_5(retriever, entry) -> tuple[float, list[str]]:
    result = await retriever.recall(RecallQuery(text=entry["query"], scopes=("private",)), AT_5)
    found = [item.memory_id for item in result.items]
    relevant = set(entry["relevant"])
    return len(relevant & set(found)) / len(relevant), found


async def scores(retriever, kind: str | None = None) -> dict[str, float]:
    return {
        entry["id"]: (await recall_at_5(retriever, entry))[0]
        for entry in QUERIES if kind is None or entry["kind"] == kind
    }


def test_the_fixture_is_well_formed():
    ids = {entry["id"] for entry in CORPUS}
    assert len(ids) == len(CORPUS) >= 25
    assert {entry["kind"] for entry in QUERIES} == {"exact", "paraphrase", "crosslingual"}
    assert all(set(entry["relevant"]) <= ids for entry in QUERIES)
    # Both languages are represented, and the paraphrase queries share no word with their target note.
    assert any(note_id.startswith("fr-") for note_id in ids) and any(note_id.startswith("en-") for note_id in ids)
    by_id = {entry["id"]: entry for entry in CORPUS}
    words = lambda text: set(text.lower().replace("-", " ").split())  # noqa: E731
    for entry in QUERIES:
        if entry["kind"] == "paraphrase":
            for note_id in entry["relevant"]:
                note = by_id[note_id]
                assert not words(entry["query"]) & words(note["title"] + " " + note["body"]), entry["query"]


async def test_hybrid_recall_at_5_is_at_least_the_lexical_baseline(stack):
    lexical_only, hybrid = stack

    lexical = await scores(lexical_only)
    fused = await scores(hybrid)

    mean = lambda values: sum(values.values()) / len(values)  # noqa: E731
    assert mean(fused) >= mean(lexical)
    regressions = {key: (lexical[key], fused[key]) for key in lexical if fused[key] < lexical[key]}
    assert regressions == {}, f"hybrid lost ground on {regressions}"


async def test_hybrid_beats_lexical_where_the_words_differ(stack):
    lexical_only, hybrid = stack

    for kind in ("paraphrase", "crosslingual"):
        lexical = await scores(lexical_only, kind)
        fused = await scores(hybrid, kind)
        assert sum(fused.values()) > sum(lexical.values()), kind
    paraphrase = await scores(hybrid, "paraphrase")
    assert all(value == 1.0 for value in paraphrase.values()), paraphrase  # lexical finds none of them
    assert sum((await scores(lexical_only, "paraphrase")).values()) == 0.0


async def test_exact_queries_stay_exact_and_rank_the_target_first(stack):
    lexical_only, hybrid = stack

    for entry in QUERIES:
        if entry["kind"] != "exact":
            continue
        _, lexical_found = await recall_at_5(lexical_only, entry)
        _, hybrid_found = await recall_at_5(hybrid, entry)
        assert hybrid_found[0] in entry["relevant"] and lexical_found[0] in entry["relevant"], entry["query"]


async def test_lexical_only_mode_needs_no_embedder_and_never_degrades(stack):
    lexical_only, _ = stack

    for entry in QUERIES:
        result = await lexical_only.recall(RecallQuery(text=entry["query"], scopes=("private",)), AT_5)
        assert result.degraded == ()
        assert all(set(item.rank_sources) == {"lexical"} for item in result.items)
        assert all(item.why.startswith("lexical #") for item in result.items)
    assert lexical_only.status().is_ok


async def test_lexical_recall_folds_diacritics_and_case(stack):
    lexical_only, _ = stack

    for text in ("CAFE matin", "cafe", "Gouts musicaux"):
        result = await lexical_only.recall(RecallQuery(text=text, scopes=("private",)), AT_5)
        assert result.items, text
    result = await lexical_only.recall(RecallQuery(text="cafe", scopes=("private",)), AT_5)
    assert result.items[0].memory_id == "fr-coffee"


async def test_every_hybrid_item_says_why_it_is_there(stack):
    _, hybrid = stack

    result = await hybrid.recall(RecallQuery(text="peanut allergy", scopes=("private",)), AT_5)

    assert {"fr-allergy", "en-allergy"} <= {item.memory_id for item in result.items}
    for item in result.items:
        assert item.why and item.rank_sources and item.provenance_ref and item.revision >= 1
        assert item.score > 0
    by_id = {item.memory_id: item for item in result.items}
    assert set(by_id["en-allergy"].rank_sources) == {"lexical", "semantic"}  # both legs agree: ranked first
    assert result.items[0].memory_id == "en-allergy"
    assert set(by_id["fr-allergy"].rank_sources) == {"semantic"}  # the translation: only the vector leg
