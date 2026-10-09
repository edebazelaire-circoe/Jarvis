"""Maintenance worker x consolidation pipeline (Slice 04).

The `jarvis:retain` rule stays one policy rule with provenance; the pipeline runs after it,
a pipeline failure never undoes it, and the daily schedule is unchanged (`execute(job)`).
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from jarvis.core.memory_maintenance import (
    MAX_EVIDENCE_NOTES,
    RETAIN_MARKER,
    MemoryMaintenanceWorker,
    short_term_evidence,
)
from jarvis.domain.memory import MemoryFilters, RetentionClass, SourceType
from tests.fakes.consolidation_harness import AUTO, build
from tests.fakes.fake_extractor import proposal


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "memory"


def write_short_term(h, title: str, body: str, *, retain: bool = False):
    record = asyncio.run(h.store.append_note(title, body + (f"\n{RETAIN_MARKER}" if retain else "")))
    return record


async def test_without_a_consolidator_the_worker_is_the_retain_rule_alone(root):
    h = build(root)
    await h.store.append_note("Keep me", f"body\n{RETAIN_MARKER}")
    result = await MemoryMaintenanceWorker(root, h.store).execute(None)
    assert result == {"promoted": 1}


async def test_retain_rule_then_pipeline_with_provenance_on_both(root):
    h = build(root, [proposal("Alice drinks green tea", "every morning", confidence=0.95)], AUTO)
    await h.store.append_note("Tea habit", "Alice drinks green tea every morning.")
    await h.store.append_note("Keep me", f"explicitly retained\n{RETAIN_MARKER}")
    worker = MemoryMaintenanceWorker(root, h.store, h.pipeline)
    result = await worker.execute(None)
    assert result["promoted"] == 1
    assert result["consolidation"]["mode"] == "auto" and len(result["consolidation"]["committed"]) == 1

    long_term = h.store.list(MemoryFilters(retentions=(RetentionClass.LONG_TERM,), limit=50))
    assert len(long_term) == 2
    for note in long_term:  # the retain rule and the pipeline both leave provenance
        assert note.sources and note.sources[-1].type in {SourceType.NOTE, SourceType.CONSOLIDATION}
    evidence_refs = {s.ref for n in long_term for s in n.sources if s.type is SourceType.NOTE}
    assert evidence_refs  # the pipeline note cites the short-term note it came from


async def test_the_daily_rerun_does_not_call_the_extractor_again_nor_duplicate(root):
    h = build(root, [proposal("Alice drinks green tea", "every morning", confidence=0.95)], AUTO)
    await h.store.append_note("Tea habit", "Alice drinks green tea every morning.")
    worker = MemoryMaintenanceWorker(root, h.store, h.pipeline)
    await worker.execute(None)
    again = await worker.execute(None)
    assert len(h.extractor.calls) == 1 and again["consolidation"]["committed"] == []
    assert len(h.store.list(MemoryFilters(retentions=(RetentionClass.LONG_TERM,), limit=50))) == 1


async def test_manual_mode_through_the_worker_commits_nothing(root):
    h = build(root, [proposal("Alice drinks green tea", "every morning", confidence=0.99)])
    await h.store.append_note("Tea habit", "Alice drinks green tea every morning.")
    result = await MemoryMaintenanceWorker(root, h.store, h.pipeline).execute(None)
    assert result["consolidation"]["committed"] == [] and result["consolidation"]["candidates"] == 1
    assert h.store.list(MemoryFilters(retentions=(RetentionClass.LONG_TERM,), limit=50)) == ()


async def test_a_pipeline_failure_is_reported_and_never_undoes_the_retain_rule(root):
    class Exploding:
        async def run(self, evidence):
            raise RuntimeError("pipeline bug")

    h = build(root)
    await h.store.append_note("Keep me", f"body\n{RETAIN_MARKER}")
    result = await MemoryMaintenanceWorker(root, h.store, Exploding()).execute(None)
    assert result["promoted"] == 1 and result["consolidation"] == {"error": "RuntimeError"}


async def test_an_extractor_outage_is_a_reported_failed_group_not_a_worker_failure(root):
    h = build(root, RuntimeError("model down"), AUTO)
    await h.store.append_note("Tea habit", "Alice drinks green tea.")
    result = await MemoryMaintenanceWorker(root, h.store, h.pipeline).execute(None)
    assert result["consolidation"]["failed_groups"] == 1 and result["consolidation"]["errors"] == ["extractor_failed:RuntimeError"]


async def test_evidence_is_the_newest_short_term_notes_each_cited_by_id_with_its_scope(root):
    h = build(root)
    await h.store.append_note("One", "first")
    await h.store.append_note("Two", "second")
    evidence = short_term_evidence(h.store)
    assert len(evidence) == 2 and {e.scope for e in evidence} == {"private"}
    assert all(e.source.type is SourceType.NOTE and e.source.ref for e in evidence)
    assert len(short_term_evidence(h.store, limit=1)) == 1 and MAX_EVIDENCE_NOTES >= 1


async def test_the_cancel_hook_and_daily_entry_point_are_unchanged(root):
    h = build(root)
    worker = MemoryMaintenanceWorker(root, h.store)
    assert await worker.cancel("job") is None
    assert inspect.iscoroutinefunction(worker.execute)
