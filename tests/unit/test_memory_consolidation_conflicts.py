"""Contradictions, temporal supersession and the candidate state machine (Slice 04, critical tier).

A conflicting new fact never overwrites: it supersedes (temporal kinds, history kept) or it is
flagged `contradicts` and left to a human. Protected notes are never rewritten by any path.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from jarvis.core.memory_consolidation import SYSTEM_ACTOR
from jarvis.domain.memory import (
    CANDIDATE_TRANSITIONS,
    CandidateDecision,
    CandidateState,
    MemoryErrorCode,
    MemoryFilters,
    MemoryKind,
    MemoryStoreError,
    RetentionClass,
    can_transition,
)
from tests.fakes.consolidation_harness import AUTO, T0, build, evidence, make_note
from tests.fakes.fake_extractor import proposal

LATER = T0 + timedelta(days=20)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "memory"


def preference(title: str, **extra):
    return proposal(title, "", kind="preference", confidence=0.95, **extra)


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*.md") if "_candidates" not in p.parts}


# ------------------------------------------------------------ temporal supersession
async def test_a_changed_preference_supersedes_the_old_one_and_history_is_kept(root):
    h = build(root, [preference("Alice prefers light mode")])
    old = h.store.create(make_note(title="Alice prefers dark mode", body="", kind=MemoryKind.PREFERENCE))
    (candidate,) = await h.pipeline.propose([evidence("switched to light", at=LATER)])
    assert candidate.conflicts == (old.id,)
    assert h.store.get(old.id).superseded_by is None  # proposing changes nothing

    done = await h.pipeline.decide(candidate.id, CandidateDecision.ACCEPT, "clarice")
    new = h.store.get(done.committed_memory_id)
    closed = h.store.get(old.id)
    assert new.supersedes == (old.id,) and new.valid_from == LATER and new.contradicts == ()
    assert closed.superseded_by == new.id and closed.valid_to == LATER and closed.revision == 2
    assert (closed.title, closed.body) == (old.title, old.body)  # never overwritten
    first = h.store.history(old.id)[0]
    assert first.revision == 1 and first.valid_to is None and first.superseded_by is None  # history keeps the old state
    assert [n.id for n in h.notes()] == [new.id]
    assert {n.id for n in h.notes(include_superseded=True)} == {new.id, old.id}


async def test_a_stale_preference_does_not_supersede_a_newer_note_it_is_linked_instead(root):
    h = build(root, [preference("Alice prefers light mode")])
    old = h.store.create(make_note(
        title="Alice prefers dark mode", body="", kind=MemoryKind.PREFERENCE, created_at=LATER, updated_at=LATER))
    (candidate,) = await h.pipeline.propose([evidence("an old remark", at=T0)])
    done = await h.pipeline.decide(candidate.id, CandidateDecision.ACCEPT, "clarice")
    new, kept = h.store.get(done.committed_memory_id), h.store.get(old.id)
    assert new.supersedes == () and new.contradicts == (old.id,)
    assert kept.superseded_by is None and kept.valid_to is None and kept.contradicts == (new.id,)


async def test_a_fact_contradiction_is_flagged_both_ways_and_nothing_is_overwritten(root):
    h = build(root, [proposal("Alice lives in Paris", confidence=0.99)], AUTO)
    old = h.store.create(make_note(title="Alice lives in Lyon", body=""))
    before = snapshot(root)
    report = await h.pipeline.run([evidence("she moved?", at=LATER)])
    # unresolved: not committed (even at 0.99 in auto), queued for a human, the old note untouched
    assert report.committed == () and snapshot(root) == before
    (candidate,) = h.cands.list(CandidateState.PROPOSED)
    assert candidate.conflicts == (old.id,)

    done = await h.pipeline.decide(candidate.id, CandidateDecision.ACCEPT, "clarice")
    new, kept = h.store.get(done.committed_memory_id), h.store.get(old.id)
    assert new.contradicts == (old.id,) and new.supersedes == ()
    assert kept.contradicts == (new.id,) and kept.superseded_by is None and kept.valid_to is None
    assert (kept.title, kept.body) == (old.title, old.body)
    assert {n.id for n in h.notes()} == {new.id, old.id}  # both stay recallable until a human resolves it


async def test_a_protected_note_is_never_superseded_or_rewritten_not_even_on_a_human_accept(root):
    h = build(root, [preference("Alice prefers light mode")])
    eternal = h.store.create(make_note(
        title="Alice prefers dark mode", body="", kind=MemoryKind.PREFERENCE, retention=RetentionClass.ETERNAL))
    (candidate,) = await h.pipeline.propose([evidence("light now", at=LATER)])
    before = snapshot(root)
    done = await h.pipeline.decide(candidate.id, CandidateDecision.ACCEPT, "clarice")
    new = h.store.get(done.committed_memory_id)
    assert new.contradicts == (eternal.id,) and new.supersedes == ()
    after = snapshot(root)
    assert {k: v for k, v in after.items() if k.startswith("eternal_memory/")} == {
        k: v for k, v in before.items() if k.startswith("eternal_memory/")}
    assert h.store.get(eternal.id).revision == 1 and not (root / ".history").exists()


async def test_two_old_notes_one_protected_one_not(root):
    h = build(root, [preference("Alice prefers light mode")])
    free = h.store.create(make_note(title="Alice prefers dark mode", body="", kind=MemoryKind.PREFERENCE))
    locked = h.store.create(make_note(
        title="Alice prefers dim mode", body="", kind=MemoryKind.PREFERENCE, retention=RetentionClass.TRAUMATIC))
    (candidate,) = await h.pipeline.propose([evidence("light", at=LATER)])
    assert set(candidate.conflicts) == {free.id, locked.id}
    new = h.store.get((await h.pipeline.decide(candidate.id, CandidateDecision.ACCEPT, "clarice")).committed_memory_id)
    assert new.supersedes == (free.id,) and new.contradicts == (locked.id,)
    assert h.store.get(locked.id).revision == 1 and h.store.get(free.id).superseded_by == new.id


async def test_a_note_in_another_scope_is_never_a_conflict(root):
    h = build(root, [preference("Alice prefers light mode")])
    h.store.create(make_note(title="Alice prefers dark mode", body="", kind=MemoryKind.PREFERENCE, scope="shared"))
    (candidate,) = await h.pipeline.propose([evidence("light", scope="private", at=LATER)])
    assert candidate.conflicts == ()


async def test_a_kind_mismatch_is_not_a_conflict(root):
    h = build(root, [proposal("Alice lives in Paris", confidence=0.9, kind="fact")])
    h.store.create(make_note(title="Alice lives in Lyon", body="", kind=MemoryKind.PREFERENCE))
    (candidate,) = await h.pipeline.propose([evidence("x")])
    assert candidate.conflicts == ()


async def test_an_already_superseded_note_is_history_not_a_conflict(root):
    h = build(root, [preference("Alice prefers light mode")])
    ancient = h.store.create(make_note(title="Alice prefers dark mode", body="", kind=MemoryKind.PREFERENCE))
    successor = h.store.create(make_note(title="Unrelated successor", body="zzz"))
    from jarvis.domain.memory import MemoryPatch
    h.store.revise(ancient.id, MemoryPatch(superseded_by=successor.id, valid_to=LATER), 1)
    (candidate,) = await h.pipeline.propose([evidence("light", at=LATER)])
    assert candidate.conflicts == ()


# ------------------------------------------------------- pending candidates
async def test_a_newer_conflicting_preference_supersedes_the_pending_candidate(root):
    h = build(root, [preference("Alice prefers dark mode")])
    (first,) = await h.pipeline.propose([evidence("dark", "t1", at=T0 + timedelta(days=1))])
    h.extractor.script = [preference("Alice prefers light mode")]
    (second,) = await h.pipeline.propose([evidence("light", "t2", at=T0 + timedelta(days=2))])
    old = h.cands.get(first.id)
    assert old.state is CandidateState.SUPERSEDED_BY_NEWER and old.decided_by == SYSTEM_ACTOR
    assert h.cands.get(second.id).state is CandidateState.PROPOSED
    assert "memory.consolidation.superseded_by_newer" in h.event_names()
    with pytest.raises(MemoryStoreError) as raised:
        await h.pipeline.decide(first.id, CandidateDecision.ACCEPT, "clarice")
    assert raised.value.code is MemoryErrorCode.CONFLICT_REVISION and h.notes() == ()


async def test_an_older_conflicting_preference_arriving_late_is_dropped_as_stale(root):
    h = build(root, [preference("Alice prefers light mode")])
    await h.pipeline.propose([evidence("light", "t2", at=T0 + timedelta(days=2))])
    h.extractor.script = [preference("Alice prefers dark mode")]
    report = await h.pipeline.run([evidence("dark", "t1", at=T0 + timedelta(days=1))])
    assert report.candidates == () and any(d.code == "stale_vs_pending" for d in report.dropped)
    assert [c.title for c in h.cands.list()] == ["Alice prefers light mode"]


async def test_non_temporal_pending_candidates_stay_side_by_side_for_a_human(root):
    h = build(root, [proposal("Alice lives in Lyon")])
    await h.pipeline.propose([evidence("a", "t1", at=T0 + timedelta(days=1))])
    h.extractor.script = [proposal("Alice lives in Paris")]
    await h.pipeline.propose([evidence("b", "t2", at=T0 + timedelta(days=2))])
    assert {c.state for c in h.cands.list()} == {CandidateState.PROPOSED} and len(h.cands.list()) == 2


# --------------------------------------------------------------- state machine
def test_the_state_machine_only_leaves_proposed():
    proposed = CandidateState.PROPOSED
    assert CANDIDATE_TRANSITIONS[proposed] == {
        CandidateState.ACCEPTED, CandidateState.REJECTED, CandidateState.SUPERSEDED_BY_NEWER}
    for final in (CandidateState.ACCEPTED, CandidateState.REJECTED, CandidateState.SUPERSEDED_BY_NEWER):
        assert not any(can_transition(final, target) for target in CandidateState)


async def test_a_decided_candidate_cannot_be_decided_again_except_by_an_identical_retry(root):
    h = build(root, [proposal("Alice drinks tea")])
    (candidate,) = await h.pipeline.propose([evidence("t")])
    accepted = await h.pipeline.decide(candidate.id, CandidateDecision.ACCEPT, "clarice")
    assert await h.pipeline.decide(candidate.id, CandidateDecision.ACCEPT, "someone-else") == accepted
    with pytest.raises(MemoryStoreError) as raised:
        await h.pipeline.decide(candidate.id, CandidateDecision.REJECT, "clarice")
    assert raised.value.code is MemoryErrorCode.CONFLICT_REVISION
    assert len(h.notes()) == 1 and h.cands.get(candidate.id).decided_by == "clarice"


async def test_a_reject_never_touches_the_store_and_keeps_the_candidate_file(root):
    h = build(root, [preference("Alice prefers light mode")])
    old = h.store.create(make_note(title="Alice prefers dark mode", body="", kind=MemoryKind.PREFERENCE))
    (candidate,) = await h.pipeline.propose([evidence("light", at=LATER)])
    before = snapshot(root)
    rejected = await h.pipeline.decide(candidate.id, CandidateDecision.REJECT, "clarice")
    assert rejected.state is CandidateState.REJECTED and snapshot(root) == before
    assert (root / "_candidates" / f"{candidate.id}.md").is_file()  # candidates are never auto-deleted
    assert h.store.get(old.id).revision == 1
    assert h.store.list(MemoryFilters()) and len(h.notes()) == 1
