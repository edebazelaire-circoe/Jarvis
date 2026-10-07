"""Recall wiring on the FR + EN fixture corpus (handoff jarvis-memory-intelligence-knowledge, Slice 03).

What this proves, and what it does not. `tests/fixtures/memory_recall/` holds a
corpus (`corpus.json`), labelled queries (`queries.json`: exact words,
paraphrase with no shared word, cross-lingual), a held-out set
(`queries_heldout.json`) and a concept table that makes `FakeEmbedder` place
chosen synonyms and translations together. So the paraphrase and cross-lingual
gains show that the **wiring** works (the vector leg is queried, fused by RRF,
hydrated and filtered, and lexical recall is not hurt); they say nothing about
the semantic quality of a real model. Two controls keep that honest: with an
empty concept table the gain vanishes, and queries whose words are not in the
table gain nothing. Real-model calibration is `benchmarks/memory_recall.py
--real-embed` (opt-in, human validation H4/H5).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
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


async def build_stack(tmp_path: Path, concepts: dict):
    store = MarkdownMemoryBackend(tmp_path / "memory")
    for entry in CORPUS:
        store.create(MemoryNote(
            id=entry["id"], title=entry["title"], body=entry["body"], level=MemoryLevel.L1, kind=MemoryKind.FACT,
            retention=RetentionClass.LONG_TERM, scope="private", created_at=T0, updated_at=T0,
        ))
    embedder = FakeEmbedder(dim=256, concepts=concepts)
    index = SemanticIndex(store.meta_dir / "semantic.sqlite3", embedder, store, allow_private=True)
    await index.reconcile()
    lexical_only = HybridRetriever([LexicalRetriever(store)])
    hybrid = HybridRetriever([LexicalRetriever(store), SemanticRetriever(index, min_score=0.15)])
    return lexical_only, hybrid


@pytest.fixture
async def stack(tmp_path: Path):
    return await build_stack(tmp_path, load("concepts.json"))


async def recall_at_5(retriever, entry) -> tuple[float, list[str]]:
    result = await retriever.recall(RecallQuery(text=entry["query"], scopes=("private",)), AT_5)
    found = [item.memory_id for item in result.items]
    relevant = set(entry["relevant"])
    return len(relevant & set(found)) / len(relevant), found


async def scores(retriever, kind: str | None = None, queries=QUERIES) -> dict[str, float]:
    return {
        entry["id"]: (await recall_at_5(retriever, entry))[0]
        for entry in queries if kind is None or entry["kind"] == kind
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


async def test_wiring_hybrid_recall_at_5_is_at_least_the_lexical_baseline(stack):
    lexical_only, hybrid = stack

    lexical = await scores(lexical_only)
    fused = await scores(hybrid)

    mean = lambda values: sum(values.values()) / len(values)  # noqa: E731
    assert mean(fused) >= mean(lexical)
    regressions = {key: (lexical[key], fused[key]) for key in lexical if fused[key] < lexical[key]}
    assert regressions == {}, f"hybrid lost ground on {regressions}"


async def test_wiring_hybrid_beats_lexical_where_the_concept_table_links_the_words(stack):
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


async def test_control_with_an_empty_concept_table_the_paraphrase_gain_vanishes(tmp_path):
    lexical_only, hybrid = await build_stack(tmp_path, {})

    paraphrase = await scores(hybrid, "paraphrase")
    crosslingual_hybrid = await scores(hybrid, "crosslingual")
    crosslingual_lexical = await scores(lexical_only, "crosslingual")

    # No shared word and no table: the fake embedder knows nothing about meaning.
    assert sum(paraphrase.values()) == 0.0, paraphrase
    assert crosslingual_hybrid == crosslingual_lexical  # translations are not found either


HELDOUT = load("queries_heldout.json")


async def test_held_out_queries_hybrid_is_not_worse_and_unmapped_words_gain_nothing(stack):
    lexical_only, hybrid = stack

    lexical = await scores(lexical_only, queries=HELDOUT)
    fused = await scores(hybrid, queries=HELDOUT)

    assert all(fused[key] >= lexical[key] for key in lexical)
    exact = [entry["id"] for entry in HELDOUT if entry["kind"] == "exact"]
    assert all(lexical[key] == fused[key] == 1.0 for key in exact)
    unmapped = [entry["id"] for entry in HELDOUT if entry["kind"] == "unmapped"]
    # Words outside the table: a stand-in for the limits of the fake, stated rather than hidden.
    assert all(fused[key] == lexical[key] == 0.0 for key in unmapped), {key: fused[key] for key in unmapped}


@pytest.mark.skipif(os.environ.get("JARVIS_MEMORY_REAL_EMBED") != "1", reason="opt-in: a real embedding provider (network)")
async def test_real_embedder_calibration_report():
    """Opt-in (JARVIS_MEMORY_REAL_EMBED=1 and an OpenAI key): prints cosine floors and recall@5 per floor."""

    import importlib.util

    path = Path(__file__).resolve().parents[2] / "benchmarks" / "memory_recall.py"
    spec = importlib.util.spec_from_file_location("memory_recall_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = await module.real_embed_report()

    assert report["relevant_cosine"]["p50"] >= report["irrelevant_cosine"]["p50"]

