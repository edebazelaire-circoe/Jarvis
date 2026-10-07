"""Recall latency and quality report (memory handoff, Slice 03). Evidence only, no gate.

    python benchmarks/memory_recall.py [--notes 5000] [--queries 200] [--no-numpy] [--json out.json]

Builds a synthetic FR + EN vault in a temporary directory (never a real data
root), then reports p50 / p95 / max in milliseconds for:

- `store.search_ranked` (the FTS5 query alone);
- the lexical leg, and a lexical-only `HybridRetriever` (provider `none`);
- the semantic leg and the full hybrid, with the deterministic `FakeEmbedder`
  (so the numbers measure the scan, the fusion and the store reads, not a
  remote model);

and recall@5 of lexical-only versus hybrid on `tests/fixtures/memory_recall/`.
The slice acceptance figure is the lexical p95 at 5 000 notes (target < 60 ms
on the dev machine, reported, not enforced).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import platform
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.adapters.markdown_memory import MarkdownMemoryBackend  # noqa: E402
from jarvis.adapters.memory_lexical import LexicalRetriever  # noqa: E402
from jarvis.adapters import memory_semantic  # noqa: E402
from jarvis.adapters.memory_semantic import SemanticIndex, SemanticRetriever  # noqa: E402
from jarvis.core.memory_hybrid import HybridRetriever  # noqa: E402
from jarvis.domain.memory import (  # noqa: E402
    MemoryKind,
    MemoryLevel,
    MemoryNote,
    RecallBudget,
    RecallQuery,
    RetentionClass,
)
from tests.fakes.fake_embedder import FakeEmbedder  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "memory_recall"
WORDS_FR = (
    "projet budget voiture entretien rendez-vous dentiste voyage billet réunion équipe client contrat facture "
    "livraison cuisine recette jardin maison famille anniversaire cadeau musique film livre lecture sport course "
    "santé médecin ordonnance banque prêt assurance impôt travail bureau ordinateur logiciel serveur réseau mot passe "
    "sécurité sauvegarde mémoire appel message courriel agenda tâche objectif idée décision priorité retard"
).split()
WORDS_EN = (
    "project budget car service appointment dentist trip ticket meeting team customer contract invoice delivery "
    "kitchen recipe garden house family birthday gift music movie book reading sport run health doctor prescription "
    "bank loan insurance tax work office computer software server network password security backup memory call "
    "message email calendar task goal idea decision priority delay"
).split()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]


def summarize(samples: list[float]) -> dict[str, float]:
    return {
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(percentile(samples, 0.95), 3),
        "max_ms": round(max(samples), 3),
        "n": len(samples),
    }


def build_vault(root: Path, notes: int, rng: random.Random) -> list[list[str]]:
    """Legacy notes (no front matter) written straight to disk: fast and realistic."""

    vocabulary = [*WORDS_FR, *WORDS_EN, *(f"terme{n:04d}" for n in range(1_500))]
    weights = [1.0 / (rank + 1) ** 0.8 for rank in range(len(vocabulary))]
    directory = root / "long_term_memory"
    directory.mkdir(parents=True)
    bodies: list[list[str]] = []
    for number in range(notes):
        words = rng.choices(vocabulary, weights, k=rng.randint(25, 90))
        bodies.append(words)
        title = " ".join(words[:4]).capitalize()
        (directory / f"{number:05d}.md").write_text(f"# {title}\n\n{' '.join(words)}\n", encoding="utf-8")
    return bodies


async def timed(retriever, texts: list[str], budget: RecallBudget) -> list[float]:
    samples = []
    for text in texts:
        started = time.perf_counter()
        await retriever.recall(RecallQuery(text=text, scopes=("private",)), budget)
        samples.append((time.perf_counter() - started) * 1000)
    return samples


async def fixture_quality() -> dict[str, float]:
    corpus = json.loads((FIXTURES / "corpus.json").read_text(encoding="utf-8"))
    queries = json.loads((FIXTURES / "queries.json").read_text(encoding="utf-8"))
    concepts = json.loads((FIXTURES / "concepts.json").read_text(encoding="utf-8"))
    stamp = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory(prefix="jarvis-bench-quality-") as tmp:
        store = MarkdownMemoryBackend(Path(tmp) / "memory")
        for entry in corpus:
            store.create(MemoryNote(
                id=entry["id"], title=entry["title"], body=entry["body"], level=MemoryLevel.L1, kind=MemoryKind.FACT,
                retention=RetentionClass.LONG_TERM, scope="private", created_at=stamp, updated_at=stamp,
            ))
        index = SemanticIndex(
            store.meta_dir / "semantic.sqlite3", FakeEmbedder(dim=256, concepts=concepts), store, allow_private=True,
        )
        await index.reconcile()
        legs = {
            "lexical": HybridRetriever([LexicalRetriever(store)]),
            "hybrid": HybridRetriever([LexicalRetriever(store), SemanticRetriever(index, min_score=0.15)]),
        }
        budget = RecallBudget(max_items=5)
        report: dict[str, float] = {}
        for name, retriever in legs.items():
            per_kind: dict[str, list[float]] = {}
            for entry in queries:
                result = await retriever.recall(RecallQuery(text=entry["query"], scopes=("private",)), budget)
                found = {item.memory_id for item in result.items}
                relevant = set(entry["relevant"])
                per_kind.setdefault(entry["kind"], []).append(len(relevant & found) / len(relevant))
            everything = [value for values in per_kind.values() for value in values]
            report[f"{name}_recall@5"] = round(sum(everything) / len(everything), 3)
            for kind, values in sorted(per_kind.items()):
                report[f"{name}_recall@5_{kind}"] = round(sum(values) / len(values), 3)
        return report


async def run(notes: int, queries: int, semantic: bool) -> dict:
    rng = random.Random(20261007)
    report: dict = {
        "python": platform.python_version(), "platform": platform.platform(), "notes": notes,
        "numpy": memory_semantic._numpy() is not None, "embedder": "FakeEmbedder(dim=64), no network",
    }
    with tempfile.TemporaryDirectory(prefix="jarvis-bench-memory-") as tmp:
        root = Path(tmp) / "memory"
        bodies = build_vault(root, notes, rng)
        started = time.perf_counter()
        store = MarkdownMemoryBackend(root)
        store.rebuild_indexes()  # waits for the start-up sync
        report["fts_build_s"] = round(time.perf_counter() - started, 2)
        texts = [" ".join(rng.sample(rng.choice(bodies), 3)) for _ in range(queries)]
        budget = RecallBudget(timeout_ms=1_500, lexical_timeout_ms=1_500, semantic_timeout_ms=1_500)

        ranked = []
        for text in texts:
            started = time.perf_counter()
            store.search_ranked(text, 20)
            ranked.append((time.perf_counter() - started) * 1000)
        lexical = LexicalRetriever(store)
        lexical_leg = []
        for text in texts:
            started = time.perf_counter()
            await lexical.hits(RecallQuery(text=text, scopes=("private",)), 20, 1.5)
            lexical_leg.append((time.perf_counter() - started) * 1000)
        report["latency"] = {
            "store.search_ranked": summarize(ranked),
            "lexical leg": summarize(lexical_leg),
            "lexical-only hybrid (provider none)": summarize(await timed(HybridRetriever([lexical]), texts, budget)),
        }
        if semantic:
            embedder = FakeEmbedder(dim=64)
            index = SemanticIndex(store.meta_dir / "semantic.sqlite3", embedder, store, allow_private=True)
            started = time.perf_counter()
            await index.reconcile()
            report["semantic_build_s"] = round(time.perf_counter() - started, 2)
            report["semantic_chunks"] = index.count()
            leg = SemanticRetriever(index)
            semantic_samples = []
            for text in texts:
                started = time.perf_counter()
                await leg.hits(RecallQuery(text=text, scopes=("private",)), 20, 1.5)
                semantic_samples.append((time.perf_counter() - started) * 1000)
            report["latency"]["semantic leg"] = summarize(semantic_samples)
            report["latency"]["hybrid (lexical + semantic)"] = summarize(
                await timed(HybridRetriever([lexical, leg]), texts, budget),
            )
    report["fixture_quality"] = await fixture_quality()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--notes", type=int, default=5_000)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--no-semantic", action="store_true", help="skip the semantic leg and the hybrid")
    parser.add_argument("--no-numpy", action="store_true", help="force the pure-Python scan (numpy stays optional)")
    parser.add_argument("--json", type=Path, help="also write the report here")
    args = parser.parse_args()
    if args.no_numpy:
        memory_semantic._numpy = lambda: None
    report = asyncio.run(run(args.notes, args.queries, not args.no_semantic))
    print(f"memory recall benchmark: {report['notes']} notes, python {report['python']}, numpy {report['numpy']}")
    for key in ("fts_build_s", "semantic_build_s", "semantic_chunks"):
        if key in report:
            print(f"  {key}: {report[key]}")
    print(f"  {'leg':<40}{'p50 ms':>10}{'p95 ms':>10}{'max ms':>10}")
    for name, row in report["latency"].items():
        print(f"  {name:<40}{row['p50_ms']:>10}{row['p95_ms']:>10}{row['max_ms']:>10}")
    print("  fixture recall@5:", json.dumps(report["fixture_quality"]))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
