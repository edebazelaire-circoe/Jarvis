"""Crash recovery and the file-backed candidate store (Slice 04, critical tier).

A crash between the canonical commit and the candidate update must be recoverable: a re-run
converges, with no duplicate note and the original actor. Every mutating call of a commit and
of a run is made to fail in turn.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from jarvis.adapters.memory_candidates import FileCandidateStore
from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.memory import (
    Candidate,
    CandidateDecision,
    CandidateState,
    MemoryErrorCode,
    MemoryKind,
    MemoryLevel,
    MemoryStoreError,
    Provenance,
    RetentionClass,
    SourceType,
)
from jarvis.ports.memory_candidates import CandidateStore, DecisionIntent
from tests.fakes.consolidation_harness import AUTO, T0, Harness, build, evidence, make_note
from tests.fakes.fake_extractor import proposal

LATER = T0.replace(day=27)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "memory"


class Faults:
    """Fails the k-th mutating call (1-based) among the ones that matter to a commit or a run."""

    def __init__(self, h: Harness) -> None:
        self.count = 0
        self.fail_at: int | None = None
        for owner, names in ((h.store, ("create", "revise")),
                             (h.cands, ("save", "mark_run", "begin_decision", "end_decision"))):
            for name in names:
                setattr(owner, name, self._wrap(getattr(owner, name), f"{type(owner).__name__}.{name}"))

    def _wrap(self, real, label):
        def call(*args, **kwargs):
            self.count += 1
            if self.fail_at == self.count:
                raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, f"injected fault at {label}")
            return real(*args, **kwargs)
        return call


def candidate(**over) -> Candidate:
    base = dict(
        id="d" * 32, title="Hand made", body="b", level=MemoryLevel.L1, kind=MemoryKind.FACT,
        retention=RetentionClass.LONG_TERM, scope="private", confidence=0.9, evidence_hash="h" * 16,
        created_at=T0, sources=(Provenance(SourceType.MANUAL, "me", T0),),
    )
    return Candidate(**{**base, **over})


# -------------------------------------------------------------- commit crashes
async def test_a_crash_after_the_commit_and_before_the_candidate_update_is_recovered_without_a_duplicate(root):
    h = build(root, [proposal("Alice drinks tea")])
    (cand,) = await h.pipeline.propose([evidence("tea")])
    real_save = h.cands.save

    def failing_save(item):
        if item.state is CandidateState.ACCEPTED:
            raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "disk full")
        return real_save(item)

    h.cands.save = failing_save
    with pytest.raises(MemoryStoreError):
        await h.pipeline.decide(cand.id, CandidateDecision.ACCEPT, "clarice")
    assert len(h.notes()) == 1 and h.cands.get(cand.id).state is CandidateState.PROPOSED
    assert [i.actor for i in h.cands.pending_decisions()] == ["clarice"]

    h.cands.save = real_save
    assert await h.pipeline.recover() == 1
    done = h.cands.get(cand.id)
    assert done.state is CandidateState.ACCEPTED and done.decided_by == "clarice"  # the original actor, not the system
    assert len(h.notes()) == 1 and done.committed_memory_id == h.notes()[0].id and h.cands.pending_decisions() == ()
    assert await h.pipeline.recover() == 0


async def test_retrying_the_decision_instead_of_recovering_converges_too(root):
    h = build(root, [proposal("Alice drinks tea")])
    (cand,) = await h.pipeline.propose([evidence("tea")])
    faults = Faults(h)
    faults.fail_at = faults.count + 3  # begin_decision, create, then the accepted save fails
    with pytest.raises(MemoryStoreError):
        await h.pipeline.decide(cand.id, CandidateDecision.ACCEPT, "clarice")
    faults.fail_at = None
    done = await h.pipeline.decide(cand.id, CandidateDecision.ACCEPT, "clarice")
    assert done.state is CandidateState.ACCEPTED and len(h.notes()) == 1


async def test_a_run_recovers_an_unfinished_decision_before_anything_else(root):
    h = build(root, [proposal("Alice drinks tea")])
    (cand,) = await h.pipeline.propose([evidence("tea")])
    h.cands.begin_decision(DecisionIntent(cand.id, CandidateDecision.ACCEPT, "clarice", T0))
    report = await h.pipeline.run([])
    assert report.recovered == 1 and h.cands.get(cand.id).decided_by == "clarice" and len(h.notes()) == 1


async def test_a_recovery_that_fails_keeps_its_intent_and_is_reported(root):
    h = build(root, [proposal("Alice drinks tea")])
    (cand,) = await h.pipeline.propose([evidence("tea")])
    h.cands.begin_decision(DecisionIntent(cand.id, CandidateDecision.ACCEPT, "clarice", T0))
    faults = Faults(h)
    faults.fail_at = 1
    report = await h.pipeline.run([])
    assert report.recovered == 0 and report.errors and len(h.cands.pending_decisions()) == 1
    faults.fail_at = None
    assert (await h.pipeline.run([])).recovered == 1


async def test_orphan_and_stale_intents_are_cleared(root):
    h = build(root, [proposal("Alice drinks tea")])
    (cand,) = await h.pipeline.propose([evidence("tea")])
    await h.pipeline.decide(cand.id, CandidateDecision.REJECT, "clarice")
    h.cands.begin_decision(DecisionIntent(cand.id, CandidateDecision.ACCEPT, "clarice", T0))  # already decided
    h.cands.begin_decision(DecisionIntent("e" * 32, CandidateDecision.ACCEPT, "clarice", T0))  # no such candidate
    assert await h.pipeline.recover() == 0 and h.cands.pending_decisions() == () and h.notes() == ()


async def _supersession_scenario(root: Path):
    h = build(root, [proposal("Alice prefers light mode", "", kind="preference", confidence=0.95)])
    old = h.store.create(make_note(title="Alice prefers dark mode", body="", kind=MemoryKind.PREFERENCE))
    (cand,) = await h.pipeline.propose([evidence("light", at=LATER)])
    return h, old, cand


async def test_a_fault_at_every_step_of_a_superseding_accept_converges(root, tmp_path):
    h, old, cand = await _supersession_scenario(root / "probe")
    faults = Faults(h)
    start = faults.count
    await h.pipeline.decide(cand.id, CandidateDecision.ACCEPT, "clarice")
    steps = faults.count - start
    assert steps >= 5  # begin, create, revise(old), save, end

    for step in range(1, steps + 1):
        h, old, cand = await _supersession_scenario(tmp_path / f"fault{step}")
        faults = Faults(h)
        faults.fail_at = faults.count + step
        with pytest.raises(MemoryStoreError):
            await h.pipeline.decide(cand.id, CandidateDecision.ACCEPT, "clarice")
        faults.fail_at = None
        await h.pipeline.recover()
        done = await h.pipeline.decide(cand.id, CandidateDecision.ACCEPT, "clarice")
        live = h.notes()
        assert done.state is CandidateState.ACCEPTED, step
        assert len(live) == 1 and live[0].supersedes == (old.id,), step  # exactly one new note
        closed = h.store.get(old.id)
        assert closed.superseded_by == live[0].id and closed.valid_to == LATER and closed.revision == 2, step
        assert h.cands.pending_decisions() == (), step


async def test_a_fault_at_every_step_of_an_auto_run_converges(root, tmp_path):
    async def scenario(path: Path):
        return build(path, [proposal("Alice drinks tea", "tea", confidence=0.95)], AUTO)

    h = await scenario(root / "probe")
    faults = Faults(h)
    await h.pipeline.run([evidence("tea")])
    steps = faults.count
    assert steps >= 6  # save, mark_run, begin, create, save accepted, end

    for step in range(1, steps + 1):
        h = await scenario(tmp_path / f"auto{step}")
        faults = Faults(h)
        faults.fail_at = step
        try:
            await h.pipeline.run([evidence("tea")])
        except MemoryStoreError:
            pass  # a fault outside the commit may surface; the next run must converge anyway
        faults.fail_at = None
        for _ in range(3):
            await h.pipeline.run([evidence("tea")])
        (final,) = h.cands.list()
        assert final.state is CandidateState.ACCEPTED, step
        assert len(h.notes()) == 1 and h.notes()[0].id == final.committed_memory_id, step
        assert h.cands.pending_decisions() == (), step
        assert h.cands.run_candidates(next(iter(_hashes(h)))) is not None, step


def _hashes(h: Harness):
    return [c.evidence_hash for c in h.cands.list()]


async def test_a_crash_between_candidate_files_and_the_run_marker_converges_even_if_the_model_rewords(root):
    h = build(root, [proposal("Alice drinks green tea", "every morning")])
    faults = Faults(h)
    faults.fail_at = 2  # candidate saved, marker fails
    with pytest.raises(MemoryStoreError):
        await h.pipeline.run([evidence("tea")])
    faults.fail_at = None
    assert len(h.cands.list()) == 1
    h.extractor.script = [proposal("Alice drinks green tea!", "every morning.")]  # nondeterministic model: other words
    await h.pipeline.run([evidence("tea")])
    assert len(h.cands.list()) == 1  # dedup against the pending candidate absorbed the rewording
    h.extractor.script = [proposal("Alice drinks green tea", "every morning")]
    await h.pipeline.run([evidence("tea")])
    assert len(h.cands.list()) == 1 and len(h.extractor.calls) == 2  # marker now written: no third extraction


async def test_a_failed_auto_commit_is_reported_and_finished_by_the_next_run(root):
    h = build(root, [proposal("Alice drinks tea", "tea", confidence=0.95)], AUTO)
    real_create = h.store.create
    h.store.create = lambda note: (_ for _ in ()).throw(MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "disk"))
    report = await h.pipeline.run([evidence("tea")])
    assert report.committed == () and report.errors == ("commit_failed:memory_unavailable",)
    assert h.notes() == () and len(h.cands.pending_decisions()) == 1
    h.store.create = real_create
    report = await h.pipeline.run([evidence("tea")])
    assert report.recovered == 1 and len(h.notes()) == 1


# ------------------------------------------------------------ candidate store
def test_file_store_implements_the_port_and_round_trips_a_candidate(root):
    store = FileCandidateStore(root)
    assert isinstance(store, CandidateStore)
    original = candidate(conflicts=("n1",), state=CandidateState.ACCEPTED, decided_at=T0, decided_by="human",
                         committed_memory_id="m1", body="line one\n\n# not a title\n---\nline two")
    store.save(original)
    assert store.get(original.id) == original
    assert store.list() == (original,) and store.list(CandidateState.PROPOSED) == ()
    text = (root / "_candidates" / f"{original.id}.md").read_text(encoding="utf-8")
    assert text.startswith("---\n") and "# Hand made" in text


def test_a_candidate_edited_by_hand_is_read_back_edited(root):
    store = FileCandidateStore(root)
    cand = candidate()
    store.save(cand)
    path = root / "_candidates" / f"{cand.id}.md"
    path.write_text(path.read_text(encoding="utf-8").replace("# Hand made", "# Reworded by a human"), encoding="utf-8")
    assert store.get(cand.id).title == "Reworded by a human"


async def test_a_human_edit_is_what_a_later_accept_commits(root):
    h = build(root, [proposal("Alice drinks tea", "tea")])
    (cand,) = await h.pipeline.propose([evidence("tea")])
    path = root / "_candidates" / f"{cand.id}.md"
    path.write_text(path.read_text(encoding="utf-8").replace("# Alice drinks tea", "# Alice drinks black tea"), encoding="utf-8")
    done = await h.pipeline.decide(cand.id, CandidateDecision.ACCEPT, "clarice")
    assert h.store.get(done.committed_memory_id).title == "Alice drinks black tea"


def test_damaged_candidate_and_side_files_are_skipped_not_raised(root):
    store = FileCandidateStore(root)
    good = candidate()
    store.save(good)
    directory = root / "_candidates"
    (directory / "broken.md").write_text("no front matter at all", encoding="utf-8")
    (directory / ("f" * 32 + ".md")).write_text("---\nid: \"" + "f" * 32 + "\"\n---\n# x\n", encoding="utf-8")  # no fields
    (directory / ("a" * 32 + ".md")).write_bytes(b"\xff\xfe\x00bad utf8")
    (directory / ("b" * 32 + ".md")).write_text("x" * 600_000, encoding="utf-8")
    (directory / (("c" * 32) + ".md")).write_text(  # id inside differs from the file name
        (directory / f"{good.id}.md").read_text(encoding="utf-8"), encoding="utf-8")
    assert store.list() == (good,)
    for missing in ("broken", "f" * 32, "a" * 32, "b" * 32, "c" * 32):
        with pytest.raises((MemoryStoreError, MemorySecurityError)):
            store.get(missing)
    (directory / ".runs").mkdir()
    (directory / ".runs" / ("1" * 16 + ".json")).write_text("{not json", encoding="utf-8")
    (directory / ".runs" / ("2" * 16 + ".json")).write_text('{"candidate_ids": ["../x"]}', encoding="utf-8")
    assert store.run_candidates("1" * 16) is None and store.run_candidates("2" * 16) is None
    (directory / ".intents").mkdir()
    (directory / ".intents" / ("d" * 32 + ".json")).write_text('{"candidate_id": "x"}', encoding="utf-8")
    assert store.pending_decisions() == ()


def test_ids_that_are_paths_are_refused_everywhere(root):
    store = FileCandidateStore(root)
    for bad in ("../x", "a/b", "..\\x", "a.b", "", "x" * 65, "C:evil"):
        with pytest.raises(MemorySecurityError):
            store.get(bad)
        with pytest.raises(MemorySecurityError):
            store.begin_decision(DecisionIntent(bad, CandidateDecision.ACCEPT, "h", T0))
    with pytest.raises(MemorySecurityError):
        store.run_candidates("../../etc")
    with pytest.raises(MemorySecurityError):
        store.mark_run("a/b" * 5, [])


def test_the_candidate_directory_may_not_be_a_link(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    try:
        os.symlink(outside, root / "_candidates", target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            pytest.skip("symlinks are not permitted here")
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "_candidates"), str(outside)], capture_output=True)
        if made.returncode != 0:
            pytest.skip("neither symlinks nor junctions are permitted here")
    store = FileCandidateStore(root)
    with pytest.raises(MemorySecurityError):
        store.save(candidate())
    assert store.list() == () and list(outside.iterdir()) == []


def test_a_write_failure_is_a_coded_error_and_leaves_no_temp_file(root, monkeypatch):
    from jarvis.adapters import memory_candidates
    store = FileCandidateStore(root)
    store.save(candidate())

    def boom(*args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(memory_candidates, "replace_with_retry", boom)
    with pytest.raises(MemoryStoreError) as raised:
        store.save(candidate(title="Changed"))
    assert raised.value.code is MemoryErrorCode.UNAVAILABLE
    assert store.get("d" * 32).title == "Hand made"
    assert not list((root / "_candidates").glob(".jarvis-cand-*"))


def test_unrepresentable_text_is_a_coded_error(root):
    store = FileCandidateStore(root)
    with pytest.raises(MemoryStoreError):
        store.save(candidate(body="lone surrogate \ud800"))
