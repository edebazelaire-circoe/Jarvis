"""Scheduled upkeep of the Test Lab store: crash leftovers and retention.

Binding contract: `docs/testlab.md` ("Supervisor and workers", "Maintenance").
Slice 02 built both halves but scheduled neither, and left one warning: a
temporaries sweep can race a `put_artifact` into a run directory it is tidying
(an empty subdirectory removed between the `mkdir` and the write), which the
store reports as a retryable `testlab_store_io`. The supervisor therefore runs a
pass only when it has NO active run and holds the start gate for its duration,
so no run of this supervisor can be writing while the sweep walks the tree.

A pass never deletes an active run: `plan_retention` only selects terminal runs,
and `apply_retention_plan` re-checks under the run lock. On top of that the
supervisor passes the ids it is executing, which are removed from the plan
before it is applied, so even a stale usage snapshot cannot select one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime

from jarvis.testlab.filesystem_store import DEFAULT_STALE_TEMPORARY_S
from jarvis.testlab.retention import (
    RetentionReport,
    TestLabRetentionPolicy,
    apply_retention_plan,
    plan_retention,
)
from jarvis.testlab.store import TestLabStoreError, TestRunStore
from jarvis.testlab.validation import check_number, check_time, fail


@dataclass(frozen=True, slots=True)
class MaintenancePolicy:
    """When upkeep runs and what it enforces. Retention stays disabled unless enabled explicitly."""

    enabled: bool = True
    #: Delay between passes. A pass is skipped (not queued) while a run is active.
    interval_s: float = 900.0
    stale_temporary_s: float = DEFAULT_STALE_TEMPORARY_S
    retention: TestLabRetentionPolicy = field(default_factory=TestLabRetentionPolicy)

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise fail("maintenance enabled must be a boolean")
        check_number(self.interval_s, "maintenance interval_s", minimum=1, maximum=24 * 60 * 60)
        check_number(self.stale_temporary_s, "maintenance stale_temporary_s", minimum=0)
        if not isinstance(self.retention, TestLabRetentionPolicy):
            raise fail("maintenance retention must be a TestLabRetentionPolicy")


@dataclass(frozen=True, slots=True)
class MaintenanceReport:
    """What one pass did. `skipped_active` names the runs kept out of the retention plan."""

    swept: int = 0
    retention: RetentionReport | None = None
    skipped_active: tuple[str, ...] = ()
    #: Stable store error code when the sweep itself failed (the pass continues with retention).
    sweep_error: str | None = None


def run_maintenance_pass(store: TestRunStore, policy: MaintenancePolicy, *, now: datetime,
                         active_run_ids: Iterable[str] = ()) -> MaintenanceReport:
    """One synchronous upkeep pass. The caller guarantees no run of its own is executing.

    Wrapped in `asyncio.to_thread` by the supervisor, like every other store call.
    """
    if not isinstance(policy, MaintenancePolicy):
        raise fail("run_maintenance_pass takes a MaintenancePolicy")
    check_time(now, "now")
    active = frozenset(active_run_ids)
    swept, sweep_error = 0, None
    sweep = getattr(store, "remove_stale_temporaries", None)
    if callable(sweep):
        try:
            swept = int(sweep(older_than_s=policy.stale_temporary_s))
        except TestLabStoreError as exc:
            # Captured: a sweep failure is upkeep, not the run path. Retention still runs and
            # the code is reported, so an operator sees which half of the pass did not happen.
            sweep_error = exc.code
    plan = plan_retention(policy.retention, store.storage_usage(), now=now)
    skipped = tuple(sorted(deletion.run_id for deletion in plan.deletions if deletion.run_id in active))
    if skipped:
        plan = replace(plan, deletions=tuple(deletion for deletion in plan.deletions
                                             if deletion.run_id not in active))
    return MaintenanceReport(swept=swept, retention=apply_retention_plan(store, plan), skipped_active=skipped,
                             sweep_error=sweep_error)
