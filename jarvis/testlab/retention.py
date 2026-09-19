"""Test Lab run retention: policy, pure planner and apply step.

Binding contract: `docs/testlab.md` ("Storage", "Retention"). The planner is
pure (usage and the current time are arguments); `apply_retention_plan` only
calls the store port. Nothing schedules retention in Slice 02: the policy is
disabled unless explicitly enabled, like `ConversationEventRetentionPolicy`.

Retention deletes whole terminal runs only. Deleting a single artifact would
leave a terminal record referencing missing bytes, and a queued or running
run still has a writer.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from jarvis.testlab.runs import TERMINAL_STATUSES, ArtifactKind
from jarvis.testlab.store import (
    BundleStore,
    CorruptRunEntry,
    EntryStorageUsage,
    EntryUsage,
    RunUsage,
    StorageUsage,
    SweepStore,
    TestLabStoreError,
    TestRunStore,
)
from jarvis.testlab.validation import check_number, check_time, fail

_GIB = 1024 * 1024 * 1024
_MIB = 1024 * 1024
MAX_DELETIONS_PER_APPLY = 1024


class RetentionReason(StrEnum):
    MAX_AGE = "max_age"
    MAX_RUNS = "max_runs"
    MAX_KIND_BYTES = "max_kind_bytes"
    MAX_TOTAL_BYTES = "max_total_bytes"
    #: Archive bound: too many sweep records, or too many bundles.
    MAX_ENTRIES = "max_entries"


class ArchiveKind(StrEnum):
    """The two stores beside `runs/` that also grow without bound."""

    SWEEP = "sweep"
    BUNDLE = "bundle"


@dataclass(frozen=True, slots=True)
class TestLabRetentionPolicy:
    """Bounds of the run store. Disabled unless explicitly enabled.

    Audio clips get their own small byte budget: they are the only artifact kind
    that can carry a voice, so they are opt-in at write time
    (`ArtifactWriteLimits.allow_audio`) and bounded here.
    """

    __test__ = False  # not a pytest test class, despite the name

    enabled: bool = False
    max_age: timedelta = timedelta(days=30)
    max_runs: int = 1000
    max_total_bytes: int = 2 * _GIB
    max_bytes_by_kind: Mapping[ArtifactKind, int] = field(
        default_factory=lambda: {ArtifactKind.AUDIO_CLIP: 256 * _MIB})
    #: Bounded work per apply; the rest is deferred to the next pass.
    max_deletions_per_apply: int = 128
    #: `<root>/sweeps/`: how many sweep records, and how many bytes they may hold.
    max_sweeps: int = 500
    max_sweep_bytes: int = 256 * _MIB
    #: `<root>/bundles/`: how many bundles, and how many bytes they may hold. A bundle is
    #: a normalized document of a session, so it is small; a lot of them are not.
    max_bundles: int = 500
    max_bundle_bytes: int = 512 * _MIB

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise fail("retention enabled must be a boolean")
        if not isinstance(self.max_age, timedelta) or self.max_age <= timedelta(0):
            raise fail("retention max_age must be a positive timedelta")
        check_number(self.max_runs, "retention max_runs", minimum=1, integer=True)
        check_number(self.max_total_bytes, "retention max_total_bytes", minimum=1, integer=True)
        if not isinstance(self.max_bytes_by_kind, Mapping):
            raise fail("retention max_bytes_by_kind must map artifact kinds to byte caps")
        for kind, cap in self.max_bytes_by_kind.items():
            if not isinstance(kind, ArtifactKind):
                raise fail("retention max_bytes_by_kind keys must be ArtifactKind")
            check_number(cap, f"retention max_bytes_by_kind.{kind.value}", minimum=1, integer=True)
        check_number(self.max_deletions_per_apply, "retention max_deletions_per_apply", minimum=1,
                     maximum=MAX_DELETIONS_PER_APPLY, integer=True)
        check_number(self.max_sweeps, "retention max_sweeps", minimum=1, integer=True)
        check_number(self.max_sweep_bytes, "retention max_sweep_bytes", minimum=1, integer=True)
        check_number(self.max_bundles, "retention max_bundles", minimum=1, integer=True)
        check_number(self.max_bundle_bytes, "retention max_bundle_bytes", minimum=1, integer=True)
        object.__setattr__(self, "max_bytes_by_kind", MappingProxyType(dict(self.max_bytes_by_kind)))


@dataclass(frozen=True, slots=True)
class RetentionDeletion:
    run_id: str
    reason: RetentionReason
    #: Set for `max_kind_bytes`.
    kind: ArtifactKind | None = None


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    enabled: bool
    #: Runs created before this are past `max_age`. None when disabled.
    cutoff: datetime | None
    #: Oldest first, at most `max_deletions_per_apply`.
    deletions: tuple[RetentionDeletion, ...] = ()
    #: Selected but beyond `max_deletions_per_apply`: left for the next pass.
    deferred: int = 0
    #: Queued or running runs: never deleted, still counted in the bounds.
    blocked_active: int = 0
    #: Unreadable entries: never deleted automatically (they are evidence of a defect).
    blocked_corrupt: tuple[CorruptRunEntry, ...] = ()
    #: Bounds still exceeded after every deletable run was selected.
    unmet: tuple[RetentionReason, ...] = ()


def plan_retention(policy: TestLabRetentionPolicy, usage: StorageUsage, *, now: datetime) -> RetentionPlan:
    """Which terminal runs to delete, oldest first, and why. Pure.

    `max_age` ages a terminal run from `finished_at` (from `created_at` when
    absent): a long run finished yesterday is not old. Order of the rules: `max_age`, then `max_runs`, then each per-kind byte cap
    (vocabulary order), then `max_total_bytes`. Each rule deletes the oldest
    remaining terminal runs until its bound holds; active runs count toward
    every bound but are never selected.
    """
    if not isinstance(policy, TestLabRetentionPolicy) or not isinstance(usage, StorageUsage):
        raise fail("plan_retention takes a TestLabRetentionPolicy and a StorageUsage")
    check_time(now, "now")
    active = sum(1 for run in usage.runs if run.status not in TERMINAL_STATUSES)
    if not policy.enabled:
        return RetentionPlan(enabled=False, cutoff=None, blocked_active=active, blocked_corrupt=usage.corrupt)
    cutoff = now - policy.max_age
    remaining: list[RunUsage] = sorted(usage.runs, key=lambda run: run.run_id)
    selected: list[RetentionDeletion] = []
    unmet: list[RetentionReason] = []

    def take(run: RunUsage, reason: RetentionReason, kind: ArtifactKind | None = None) -> None:
        remaining.remove(run)
        selected.append(RetentionDeletion(run.run_id, reason, kind))

    def deletable() -> list[RunUsage]:
        return [run for run in remaining if run.status in TERMINAL_STATUSES]

    for run in deletable():
        if (run.finished_at or run.created_at) < cutoff:
            take(run, RetentionReason.MAX_AGE)

    while len(remaining) > policy.max_runs:
        candidates = deletable()
        if not candidates:
            unmet.append(RetentionReason.MAX_RUNS)
            break
        take(candidates[0], RetentionReason.MAX_RUNS)

    for kind in ArtifactKind:
        cap = policy.max_bytes_by_kind.get(kind)
        if cap is None:
            continue
        while sum(run.bytes_by_kind.get(kind, 0) for run in remaining) > cap:
            candidates = [run for run in deletable() if run.bytes_by_kind.get(kind, 0) > 0]
            if not candidates:
                unmet.append(RetentionReason.MAX_KIND_BYTES)
                break
            take(candidates[0], RetentionReason.MAX_KIND_BYTES, kind)

    while sum(run.total_bytes for run in remaining) > policy.max_total_bytes:
        candidates = deletable()
        if not candidates:
            unmet.append(RetentionReason.MAX_TOTAL_BYTES)
            break
        take(candidates[0], RetentionReason.MAX_TOTAL_BYTES)

    ordered = sorted(selected, key=lambda deletion: deletion.run_id)
    limit = policy.max_deletions_per_apply
    return RetentionPlan(enabled=True, cutoff=cutoff, deletions=tuple(ordered[:limit]),
                         deferred=max(0, len(ordered) - limit), blocked_active=active,
                         blocked_corrupt=usage.corrupt, unmet=tuple(dict.fromkeys(unmet)))


@dataclass(frozen=True, slots=True)
class RetentionReport:
    plan: RetentionPlan
    deleted: tuple[str, ...] = ()
    #: (run_id, store error code): refused at apply time (state changed, file held open, I/O).
    skipped: tuple[tuple[str, str], ...] = ()


def apply_retention_plan(store: TestRunStore, plan: RetentionPlan) -> RetentionReport:
    """Delete the planned runs through the store port. One refusal never stops the pass.

    `delete_run` re-checks under the run lock that the run is still terminal,
    so a plan computed from stale usage cannot delete an active run.
    """
    if not isinstance(plan, RetentionPlan):
        raise fail("apply_retention_plan takes a RetentionPlan")
    deleted: list[str] = []
    skipped: list[tuple[str, str]] = []
    for deletion in plan.deletions:
        try:
            store.delete_run(deletion.run_id)
        except TestLabStoreError as exc:
            # Capture, then continue: the refusal is reported with its stable
            # code, and the next pass re-plans from fresh usage.
            skipped.append((deletion.run_id, exc.code))
            continue
        deleted.append(deletion.run_id)
    return RetentionReport(plan=plan, deleted=tuple(deleted), skipped=tuple(skipped))


# ------------------------------------------------------- the other two stores

@dataclass(frozen=True, slots=True)
class ArchiveUsage:
    """What `<root>/sweeps/` and `<root>/bundles/` hold: the two adapters' `storage_usage()`."""

    sweeps: tuple[EntryUsage, ...] = ()
    bundles: tuple[EntryUsage, ...] = ()
    corrupt: tuple[CorruptRunEntry, ...] = ()

    @classmethod
    def of(cls, sweeps: EntryStorageUsage, bundles: EntryStorageUsage) -> "ArchiveUsage":
        """The two store usages as one input, corrupt entries merged."""
        return cls(sweeps.entries, bundles.entries, (*sweeps.corrupt, *bundles.corrupt))


@dataclass(frozen=True, slots=True)
class ArchiveDeletion:
    kind: ArchiveKind
    entry_id: str
    reason: RetentionReason


@dataclass(frozen=True, slots=True)
class ArchiveRetentionPlan:
    enabled: bool
    cutoff: datetime | None
    deletions: tuple[ArchiveDeletion, ...] = ()
    deferred: int = 0
    #: Sweeps still running: never deleted, still counted in the bounds.
    blocked_active: int = 0
    #: Entries a STORED RUN points at (`sweep_id`, `bundle_id`): never deleted.
    blocked_referenced: int = 0
    blocked_corrupt: tuple[CorruptRunEntry, ...] = ()
    unmet: tuple[RetentionReason, ...] = ()


def referenced_archive_ids(usage: StorageUsage) -> frozenset[str]:
    """Every sweep id and bundle id a STORED RUN points at. Pure.

    Deleting one of these would leave a terminal record referring to evidence that is
    gone, which is exactly what the run rule ("whole terminal runs only") exists to
    prevent. The reference set is taken from ALL stored runs, including the ones this
    very pass plans to delete: a run deletion can be refused at apply time, so a bundle
    whose last run disappears is collected by the NEXT pass rather than by an optimistic
    one. Retention converges in two passes instead of one, and never ahead of itself.
    """
    if not isinstance(usage, StorageUsage):
        raise fail("referenced_archive_ids takes a StorageUsage")
    return frozenset({item for run in usage.runs for item in (run.sweep_id, run.bundle_id) if item is not None})


def plan_archive_retention(policy: TestLabRetentionPolicy, usage: ArchiveUsage, *, now: datetime,
                           referenced: Collection[str] = ()) -> ArchiveRetentionPlan:
    """Which sweeps and bundles to delete, oldest first, and why. Pure.

    Same shape and same rule order as `plan_retention`: `max_age`, then the count bound,
    then the byte bound, each deleting the oldest deletable entries until it holds.
    Sweeps and bundles have SEPARATE bounds and are planned independently - a thousand
    cheap bundles must not evict the sweep an operator is reading.

    Three things are never selected, and each is counted rather than hidden: an active
    sweep, an entry a stored run references, and a corrupt entry.
    """
    if not isinstance(policy, TestLabRetentionPolicy) or not isinstance(usage, ArchiveUsage):
        raise fail("plan_archive_retention takes a TestLabRetentionPolicy and an ArchiveUsage")
    check_time(now, "now")
    protected = frozenset(referenced)
    blocked_active = sum(1 for item in usage.sweeps if item.active)
    blocked_referenced = sum(1 for group in (usage.sweeps, usage.bundles)
                             for item in group if item.entry_id in protected)
    if not policy.enabled:
        return ArchiveRetentionPlan(enabled=False, cutoff=None, blocked_active=blocked_active,
                                    blocked_referenced=blocked_referenced, blocked_corrupt=usage.corrupt)
    cutoff = now - policy.max_age
    selected: list[ArchiveDeletion] = []
    unmet: list[RetentionReason] = []
    for kind, entries, max_entries, max_bytes in (
            (ArchiveKind.SWEEP, usage.sweeps, policy.max_sweeps, policy.max_sweep_bytes),
            (ArchiveKind.BUNDLE, usage.bundles, policy.max_bundles, policy.max_bundle_bytes)):
        remaining = sorted(entries, key=lambda item: item.entry_id)
        deletable = [item for item in remaining if not item.active and item.entry_id not in protected]

        def take(item: EntryUsage, reason: RetentionReason, group: ArchiveKind = kind) -> None:
            remaining.remove(item)
            deletable.remove(item)
            selected.append(ArchiveDeletion(group, item.entry_id, reason))

        for item in list(deletable):
            if item.created_at < cutoff:
                take(item, RetentionReason.MAX_AGE)
        while len(remaining) > max_entries:
            if not deletable:
                unmet.append(RetentionReason.MAX_ENTRIES)
                break
            take(deletable[0], RetentionReason.MAX_ENTRIES)
        while sum(item.total_bytes for item in remaining) > max_bytes:
            if not deletable:
                unmet.append(RetentionReason.MAX_TOTAL_BYTES)
                break
            take(deletable[0], RetentionReason.MAX_TOTAL_BYTES)
    ordered = sorted(selected, key=lambda deletion: (deletion.kind.value, deletion.entry_id))
    limit = policy.max_deletions_per_apply
    return ArchiveRetentionPlan(enabled=True, cutoff=cutoff, deletions=tuple(ordered[:limit]),
                                deferred=max(0, len(ordered) - limit), blocked_active=blocked_active,
                                blocked_referenced=blocked_referenced, blocked_corrupt=usage.corrupt,
                                unmet=tuple(dict.fromkeys(unmet)))


@dataclass(frozen=True, slots=True)
class ArchiveRetentionReport:
    plan: ArchiveRetentionPlan
    deleted: tuple[ArchiveDeletion, ...] = ()
    #: `(kind, entry id, store error code)`: refused at apply time (held open, I/O, gone).
    skipped: tuple[tuple[str, str, str], ...] = ()


def apply_archive_retention_plan(plan: ArchiveRetentionPlan, *, sweep_store: SweepStore | None = None,
                                 bundle_store: BundleStore | None = None) -> ArchiveRetentionReport:
    """Delete the planned sweeps and bundles through their ports. One refusal never stops the pass.

    A store the caller did not give keeps its entries: that is how a composition with
    only one of the two, or a test, asks for half the pass.
    """
    if not isinstance(plan, ArchiveRetentionPlan):
        raise fail("apply_archive_retention_plan takes an ArchiveRetentionPlan")
    deleted: list[ArchiveDeletion] = []
    skipped: list[tuple[str, str, str]] = []
    for deletion in plan.deletions:
        is_sweep = deletion.kind is ArchiveKind.SWEEP
        store = sweep_store if is_sweep else bundle_store
        if store is None:
            continue  # intentional: a store this caller did not compose keeps its entries
        try:
            if is_sweep:
                store.delete_sweep(deletion.entry_id)
            else:
                store.delete_bundle(deletion.entry_id)
        except TestLabStoreError as exc:
            # Captured, then continue: the refusal is reported with its stable code and
            # the next pass re-plans from fresh usage.
            skipped.append((deletion.kind.value, deletion.entry_id, exc.code))
            continue
        deleted.append(deletion)
    return ArchiveRetentionReport(plan=plan, deleted=tuple(deleted), skipped=tuple(skipped))
