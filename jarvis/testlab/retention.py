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

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from jarvis.testlab.runs import TERMINAL_STATUSES, ArtifactKind
from jarvis.testlab.store import CorruptRunEntry, RunUsage, StorageUsage, TestLabStoreError, TestRunStore
from jarvis.testlab.validation import check_number, check_time, fail

_GIB = 1024 * 1024 * 1024
_MIB = 1024 * 1024
MAX_DELETIONS_PER_APPLY = 1024


class RetentionReason(StrEnum):
    MAX_AGE = "max_age"
    MAX_RUNS = "max_runs"
    MAX_KIND_BYTES = "max_kind_bytes"
    MAX_TOTAL_BYTES = "max_total_bytes"


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
