"""Tests for the Test Lab retention policy, planner and apply step (docs/testlab.md, Retention)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.retention import (
    RetentionDeletion,
    RetentionReason,
    TestLabRetentionPolicy,
    apply_retention_plan,
    plan_retention,
)
from jarvis.testlab.runs import ArtifactKind, RunFailure, RunStatus, transition_run
from jarvis.testlab.store import STORE_CONFLICT, CorruptRunEntry, RunUsage, StorageUsage
from jarvis.testlab.validation import TestLabError
from tests.fakes.testlab import T0, at, queued_run

S = RunStatus
NOW = T0 + timedelta(days=100)
DAY = timedelta(days=1)


def usage(index: int, *, age_days: float = 1, status: RunStatus = S.PASSED, total: int = 10,
          kinds: dict | None = None, finished_days: float | None = None) -> RunUsage:
    created = NOW - timedelta(days=age_days)
    finished = None if finished_days is None else NOW - timedelta(days=finished_days)
    return RunUsage(format_run_id(created, f"{index:016x}"), created, status, total, kinds or {}, finished_at=finished)


def plan(policy: TestLabRetentionPolicy, *runs: RunUsage, corrupt=()):
    return plan_retention(policy, StorageUsage(runs=tuple(runs), corrupt=tuple(corrupt)), now=NOW)


def test_disabled_by_default_plans_nothing():
    runs = [usage(i, age_days=400) for i in range(5)]
    result = plan(TestLabRetentionPolicy(), *runs)
    assert not result.enabled and result.deletions == () and result.cutoff is None


def test_default_bounds():
    policy = TestLabRetentionPolicy()
    assert policy.max_age == timedelta(days=30) and policy.max_runs == 1000
    assert policy.max_total_bytes == 2 * 1024**3
    assert dict(policy.max_bytes_by_kind) == {ArtifactKind.AUDIO_CLIP: 256 * 1024**2}


def test_max_age_deletes_only_terminal_runs():
    old_done = usage(1, age_days=40)
    old_running = usage(2, age_days=41, status=S.RUNNING)
    recent = usage(3, age_days=2)
    result = plan(TestLabRetentionPolicy(enabled=True), old_done, old_running, recent)
    assert result.deletions == (RetentionDeletion(old_done.run_id, RetentionReason.MAX_AGE),)
    assert result.blocked_active == 1
    assert result.cutoff == NOW - timedelta(days=30)


def test_max_runs_deletes_oldest_terminal_first():
    runs = [usage(i, age_days=10 - i) for i in range(5)]
    active_oldest = usage(99, age_days=20, status=S.QUEUED)
    result = plan(TestLabRetentionPolicy(enabled=True, max_runs=3), active_oldest, *runs)
    assert [d.run_id for d in result.deletions] == [runs[0].run_id, runs[1].run_id, runs[2].run_id]
    assert {d.reason for d in result.deletions} == {RetentionReason.MAX_RUNS}


def test_kind_cap_then_total_bytes():
    audio_old = usage(1, age_days=5, total=300, kinds={ArtifactKind.AUDIO_CLIP: 290})
    plain_old = usage(2, age_days=4, total=100)
    audio_new = usage(3, age_days=3, total=300, kinds={ArtifactKind.AUDIO_CLIP: 290})
    plain_new = usage(4, age_days=2, total=100)
    policy = TestLabRetentionPolicy(enabled=True, max_bytes_by_kind={ArtifactKind.AUDIO_CLIP: 300},
                                    max_total_bytes=450)
    result = plan(policy, plain_new, audio_new, plain_old, audio_old)
    assert result.deletions == (
        RetentionDeletion(audio_old.run_id, RetentionReason.MAX_KIND_BYTES, ArtifactKind.AUDIO_CLIP),
        RetentionDeletion(plain_old.run_id, RetentionReason.MAX_TOTAL_BYTES),
    )
    assert result.unmet == ()


def test_unmet_bounds_when_only_active_runs_remain_and_corrupt_never_selected():
    active = [usage(i, status=S.RUNNING, total=1000) for i in range(3)]
    corrupt = (CorruptRunEntry("tlr-x", "testlab_store_corrupt", "unreadable"),)
    result = plan(TestLabRetentionPolicy(enabled=True, max_runs=1, max_total_bytes=10), *active, corrupt=corrupt)
    assert result.deletions == ()
    assert result.unmet == (RetentionReason.MAX_RUNS, RetentionReason.MAX_TOTAL_BYTES)
    assert result.blocked_active == 3 and result.blocked_corrupt == corrupt


def test_deletions_bounded_per_apply():
    runs = [usage(i, age_days=50 + i) for i in range(10)]
    result = plan(TestLabRetentionPolicy(enabled=True, max_deletions_per_apply=4), *runs)
    assert len(result.deletions) == 4 and result.deferred == 6
    assert [d.run_id for d in result.deletions] == sorted(r.run_id for r in runs)[:4]


@pytest.mark.parametrize("changes", [
    dict(enabled=1), dict(max_age=timedelta(0)), dict(max_runs=0), dict(max_total_bytes=-1),
    dict(max_bytes_by_kind={"audio_clip": 10}), dict(max_bytes_by_kind={ArtifactKind.AUDIO_CLIP: 0}),
    dict(max_deletions_per_apply=5000),
])
def test_policy_validation(changes):
    with pytest.raises(TestLabError):
        TestLabRetentionPolicy(**changes)


def test_planner_requires_utc_now():
    with pytest.raises(TestLabError):
        plan_retention(TestLabRetentionPolicy(), StorageUsage(runs=()), now=NOW.replace(tzinfo=None))


def test_apply_deletes_through_the_store_and_reports_refusals(tmp_path):
    store = FilesystemTestRunStore(tmp_path)
    old = queued_run(run_id=format_run_id(at(0), "0000000000000001"), created_at=at(0))
    store.create_run(old)
    store.update_run(transition_run(old, S.CANCELLED, at=at(1), failure=RunFailure("operator_cancel")), expected=old)
    racing = queued_run(run_id=format_run_id(at(5), "0000000000000002"), created_at=at(5))
    store.create_run(racing)
    usage_now = store.storage_usage()
    # Plan as if `racing` were terminal (stale usage): apply must still refuse it.
    stale = StorageUsage(runs=tuple(replace(item, status=S.CANCELLED) for item in usage_now.runs))
    result_plan = plan_retention(TestLabRetentionPolicy(enabled=True, max_age=DAY), stale, now=at(0) + 2 * DAY)
    assert len(result_plan.deletions) == 2
    report = apply_retention_plan(store, result_plan)
    assert report.deleted == (old.run_id,)
    assert report.skipped == ((racing.run_id, STORE_CONFLICT),)
    assert [run.run_id for run in store.list_runs().runs] == [racing.run_id]


def test_max_age_counts_from_finished_at_when_present():
    long_run_finished_recently = usage(1, age_days=40, finished_days=1)
    finished_long_ago = usage(2, age_days=45, finished_days=31)
    no_finish_time = usage(3, age_days=40)
    result = plan(TestLabRetentionPolicy(enabled=True), long_run_finished_recently, finished_long_ago, no_finish_time)
    assert [d.run_id for d in result.deletions] == sorted([finished_long_ago.run_id, no_finish_time.run_id])


def test_storage_usage_carries_finished_at(tmp_path):
    store = FilesystemTestRunStore(tmp_path)
    run = queued_run()
    store.create_run(run)
    done = store.update_run(transition_run(run, S.CANCELLED, at=at(7), failure=RunFailure("operator_cancel")),
                            expected=run)
    assert store.storage_usage().runs[0].finished_at == done.finished_at
