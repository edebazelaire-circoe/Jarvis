"""Slice 12: retention over `<root>/sweeps/` and `<root>/bundles/`, and what it reclaims.

Contract: `docs/testlab.md` ("Retention"). Slice 02 bounded `runs/` and left the other
two growing without bound; a sweep of 256 points writes 256 runs plus a record, so the
index grows fastest exactly when the store does.

Two halves, tested apart. The planner is pure, so its rules are asserted on constructed
usage: order, separate bounds per store, the three things it never selects. The apply
step runs against the REAL filesystem adapters, on a real temp root, and the assertion
is the one an operator cares about: the bytes are gone, and the entries that must
survive are still readable.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.testlab.filesystem_bundle_store import FilesystemBundleStore
from jarvis.testlab.filesystem_sweep_store import FilesystemSweepStore
from jarvis.testlab.identity import format_bundle_id, format_sweep_id, id_created_at
from jarvis.testlab.retention import (
    ArchiveKind,
    ArchiveUsage,
    RetentionReason,
    TestLabRetentionPolicy,
    apply_archive_retention_plan,
    plan_archive_retention,
    referenced_archive_ids,
)
from jarvis.testlab.runs import RunStatus
from jarvis.testlab.store import (
    STORE_CONFLICT,
    STORE_CORRUPT,
    EntryStorageUsage,
    EntryUsage,
    RunUsage,
    StorageUsage,
    TestLabStoreError,
)
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.sweeps import (
    SweepRecord,
    SweepSpec,
    SweepStatus,
    SweepTarget,
    SweptParameter,
)
from jarvis.testlab.bundle_builder import build_diagnostic_bundle
import tests.fakes.testlab_bundle as fx

NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
ON = TestLabRetentionPolicy(enabled=True)


def sweep_id(minutes: int) -> str:
    return format_sweep_id(NOW - timedelta(minutes=minutes), f"{minutes:016x}")


def bundle_id(minutes: int) -> str:
    return format_bundle_id(NOW - timedelta(minutes=minutes), f"{minutes:016x}")


def entry(entry_id: str, *, total_bytes: int = 1000, active: bool = False) -> EntryUsage:
    return EntryUsage(entry_id, id_created_at(entry_id), total_bytes, active=active)


def plan(policy: TestLabRetentionPolicy = ON, *, sweeps=(), bundles=(), corrupt=(), referenced=()):
    return plan_archive_retention(policy, ArchiveUsage(tuple(sweeps), tuple(bundles), tuple(corrupt)),
                                  now=NOW, referenced=referenced)


# --------------------------------------------------------------- the planner

def test_a_disabled_policy_deletes_nothing_and_still_says_what_it_saw():
    answer = plan(TestLabRetentionPolicy(), sweeps=[entry(sweep_id(1), active=True)], bundles=[entry(bundle_id(2))])
    assert answer.enabled is False and answer.deletions == () and answer.cutoff is None
    assert answer.blocked_active == 1


def test_age_takes_the_oldest_of_both_stores_and_leaves_the_rest():
    old_sweep, young_sweep = entry(sweep_id(60 * 24 * 40)), entry(sweep_id(5))
    old_bundle, young_bundle = entry(bundle_id(60 * 24 * 40)), entry(bundle_id(6))
    answer = plan(sweeps=[young_sweep, old_sweep], bundles=[young_bundle, old_bundle])
    assert {(item.kind, item.entry_id) for item in answer.deletions} == {
        (ArchiveKind.SWEEP, old_sweep.entry_id), (ArchiveKind.BUNDLE, old_bundle.entry_id)}
    assert {item.reason for item in answer.deletions} == {RetentionReason.MAX_AGE}


def test_the_two_stores_have_separate_count_bounds():
    """A thousand cheap bundles must not evict the sweep record somebody is reading."""
    policy = replace(ON, max_sweeps=2, max_bundles=1)
    answer = plan(policy, sweeps=[entry(sweep_id(n)) for n in (1, 2, 3, 4)],
                  bundles=[entry(bundle_id(n)) for n in (1, 2, 3)])
    deleted = {kind: [row.entry_id for row in answer.deletions if row.kind is kind] for kind in ArchiveKind}
    assert len(deleted[ArchiveKind.SWEEP]) == 2 and len(deleted[ArchiveKind.BUNDLE]) == 2
    # Oldest first: the ids sort by creation time, and the biggest `minutes` is the oldest.
    assert deleted[ArchiveKind.SWEEP] == sorted([sweep_id(4), sweep_id(3)])
    assert all(item.reason is RetentionReason.MAX_ENTRIES for item in answer.deletions)


def test_the_byte_bound_deletes_until_it_holds_and_no_further():
    policy = replace(ON, max_bundle_bytes=2500, max_bundles=100)
    answer = plan(policy, bundles=[entry(bundle_id(n), total_bytes=1000) for n in (1, 2, 3, 4)])
    assert len(answer.deletions) == 2
    assert {item.reason for item in answer.deletions} == {RetentionReason.MAX_TOTAL_BYTES}


def test_a_running_sweep_counts_toward_the_bound_and_is_never_selected():
    policy = replace(ON, max_sweeps=1)
    answer = plan(policy, sweeps=[entry(sweep_id(9), active=True), entry(sweep_id(1))])
    assert [item.entry_id for item in answer.deletions] == [sweep_id(1)]
    assert answer.blocked_active == 1


def test_a_bound_that_cannot_be_met_without_an_active_sweep_is_reported_unmet():
    answer = plan(replace(ON, max_sweeps=1), sweeps=[entry(sweep_id(n), active=True) for n in (1, 2)])
    assert answer.deletions == () and RetentionReason.MAX_ENTRIES in answer.unmet


def test_an_entry_a_stored_run_points_at_is_never_deleted():
    kept, goes = bundle_id(60 * 24 * 40), bundle_id(60 * 24 * 41)
    answer = plan(bundles=[entry(kept), entry(goes)], referenced={kept})
    assert [item.entry_id for item in answer.deletions] == [goes]
    assert answer.blocked_referenced == 1


def test_the_reference_set_is_every_sweep_and_bundle_a_stored_run_names():
    usage = StorageUsage(runs=(
        RunUsage("tlr-20260919T120000000Z-" + "0" * 16, NOW, RunStatus.PASSED, 10,
                 sweep_id=sweep_id(1), bundle_id=bundle_id(1)),
        RunUsage("tlr-20260919T120001000Z-" + "0" * 16, NOW, RunStatus.PASSED, 10),
    ))
    assert referenced_archive_ids(usage) == frozenset({sweep_id(1), bundle_id(1)})


def test_a_corrupt_entry_is_carried_into_the_plan_and_never_selected():
    from jarvis.testlab.store import CorruptRunEntry

    damaged = CorruptRunEntry("tlb-nonsense", STORE_CORRUPT, "entry is not a bundle directory")
    answer = plan(replace(ON, max_bundles=1), bundles=[entry(bundle_id(1))], corrupt=[damaged])
    assert answer.blocked_corrupt == (damaged,) and answer.deletions == ()


def test_work_is_bounded_per_pass_and_the_rest_is_deferred():
    answer = plan(replace(ON, max_bundles=1, max_deletions_per_apply=2),
                  bundles=[entry(bundle_id(n)) for n in range(1, 8)])
    assert len(answer.deletions) == 2 and answer.deferred == 4


# ------------------------------------------------------- the real filesystem

def sweep_record(entry_id: str, status: SweepStatus = SweepStatus.COMPLETED) -> SweepRecord:
    spec = SweepSpec(diagnostic_id="voice.self_echo", profile=ProfileName.VIRTUAL,
                     swept=(SweptParameter("turns", SweepTarget.PARAMETER, (1, 2)),))
    return SweepRecord(sweep_id=entry_id, created_at=id_created_at(entry_id), spec=spec, status=status,
                       diagnostic_version=1, diagnostic_fingerprint="a" * 64,
                       finished_at=None if status is SweepStatus.RUNNING else id_created_at(entry_id))


@pytest.fixture
def stores(tmp_path):
    return FilesystemSweepStore(tmp_path / "root"), FilesystemBundleStore(tmp_path / "root")


def root_bytes(path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def test_a_pass_reclaims_the_bytes_and_keeps_what_it_must(tmp_path, stores):
    """The assertion an operator cares about: the disk shrank, and nothing needed is gone."""
    sweeps, bundles = stores
    old = [sweep_id(60 * 24 * 40 + n) for n in range(3)]
    running = sweep_id(60 * 24 * 41)
    for item in old:
        sweeps.put_sweep(sweep_record(item))
        sweeps.put_sweep_summary(item, {"schema": "jarvis.testlab.sweep_summary", "points": []})
    sweeps.put_sweep(sweep_record(running, SweepStatus.RUNNING))
    stored_bundle = bundles.put_bundle(build_diagnostic_bundle(fx.selector(), context=fx.context())).bundle_id

    before = root_bytes(tmp_path / "root")
    usage = ArchiveUsage.of(sweeps.storage_usage(), bundles.storage_usage())
    assert {item.entry_id for item in usage.sweeps} == {*old, running}
    assert [item.active for item in usage.sweeps if item.entry_id == running] == [True]

    answer = plan_archive_retention(ON, usage, now=NOW, referenced={stored_bundle})
    report = apply_archive_retention_plan(answer, sweep_store=sweeps, bundle_store=bundles)

    assert sorted(item.entry_id for item in report.deleted) == sorted(old)
    assert report.skipped == ()
    after = root_bytes(tmp_path / "root")
    assert after < before, "retention reclaimed no space"
    # The running sweep and the referenced bundle are still readable.
    assert sweeps.get_sweep(running).status is SweepStatus.RUNNING
    assert bundles.get_bundle(stored_bundle).bundle_id == stored_bundle
    assert {item.entry_id for item in sweeps.storage_usage().entries} == {running}


def test_the_sweep_store_refuses_to_delete_a_running_sweep(stores):
    sweeps, _ = stores
    running = sweep_id(3)
    sweeps.put_sweep(sweep_record(running, SweepStatus.RUNNING))
    with pytest.raises(TestLabStoreError) as caught:
        sweeps.delete_sweep(running)
    assert caught.value.code == STORE_CONFLICT
    assert sweeps.get_sweep(running).status is SweepStatus.RUNNING


def test_an_unreadable_entry_is_refused_by_both_stores_and_stays_on_disk(tmp_path, stores):
    """An entry that does not decode is evidence of a defect; nothing here deletes it.

    The two stores find out at different moments, and that is deliberate. A sweep usage
    reads the record for its STATUS, so a broken one is `corrupt` in the plan and is never
    selected. A bundle usage decodes nothing (the age is in the id), so a broken one is an
    ordinary entry the planner may select - and `delete_bundle` refuses it, which the pass
    reports in `skipped`. Either way it survives, which is the invariant that matters.
    """
    sweeps, bundles = stores
    damaged_sweep, damaged_bundle = sweep_id(60 * 24 * 40), bundle_id(60 * 24 * 40)
    for directory, name in (("sweeps", damaged_sweep), ("bundles", damaged_bundle)):
        target = tmp_path / "root" / directory / name
        target.mkdir(parents=True)
        (target / f"{directory[:-1]}.json").write_text("{", encoding="utf-8")

    for call, entry_id in ((sweeps.delete_sweep, damaged_sweep), (bundles.delete_bundle, damaged_bundle)):
        with pytest.raises(TestLabStoreError) as caught:
            call(entry_id)
        assert caught.value.code == STORE_CORRUPT

    usage = ArchiveUsage.of(sweeps.storage_usage(), bundles.storage_usage())
    assert {item.entry for item in usage.corrupt} == {damaged_sweep}
    assert usage.sweeps == ()
    assert [item.entry_id for item in usage.bundles] == [damaged_bundle]

    report = apply_archive_retention_plan(plan_archive_retention(ON, usage, now=NOW),
                                          sweep_store=sweeps, bundle_store=bundles)
    assert report.deleted == ()
    assert report.skipped == (("bundle", damaged_bundle, STORE_CORRUPT),)
    assert (tmp_path / "root" / "sweeps" / damaged_sweep).is_dir()
    assert (tmp_path / "root" / "bundles" / damaged_bundle).is_dir()


def test_a_refusal_at_apply_time_is_reported_and_never_stops_the_pass(stores):
    sweeps, bundles = stores
    goes, stays = sweep_id(60 * 24 * 40), sweep_id(60 * 24 * 41)
    sweeps.put_sweep(sweep_record(goes))
    sweeps.put_sweep(sweep_record(stays, SweepStatus.RUNNING))
    # Plan against usage that (wrongly) believes the second one is terminal.
    stale = ArchiveUsage(sweeps=(entry(goes), entry(stays)))
    report = apply_archive_retention_plan(plan_archive_retention(ON, stale, now=NOW),
                                          sweep_store=sweeps, bundle_store=bundles)
    assert [item.entry_id for item in report.deleted] == [goes]
    assert report.skipped == (("sweep", stays, STORE_CONFLICT),)


def test_a_store_the_caller_did_not_compose_keeps_its_entries(stores):
    sweeps, bundles = stores
    item = sweep_id(60 * 24 * 40)
    sweeps.put_sweep(sweep_record(item))
    report = apply_archive_retention_plan(plan_archive_retention(ON, ArchiveUsage(sweeps=(entry(item),)), now=NOW),
                                          bundle_store=bundles)
    assert report.deleted == () and report.skipped == ()
    assert sweeps.get_sweep(item)


def test_an_empty_store_reports_no_usage_and_creates_nothing(tmp_path, stores):
    sweeps, bundles = stores
    assert sweeps.storage_usage() == EntryStorageUsage()
    assert bundles.storage_usage() == EntryStorageUsage()
    assert not (tmp_path / "root").exists()
