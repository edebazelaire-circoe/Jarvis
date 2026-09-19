"""Native Test Lab API: the one facade the CLI and the Control Center both call.

Binding contract: `docs/testlab.md` ("Native API, CLI and HTTP"). Everything here is a
thin call onto Slices 01-09 plus a documented JSON shape; there is no domain logic, no
threshold and no judgement in this module. That is the point: three surfaces that agree
by construction, because they are one implementation.

Three rules this module holds:

1. **The store is synchronous.** Every call into it goes through `asyncio.to_thread`, so
   an aiohttp handler never blocks the Control Center's event loop on a file lock.
2. **The shapes are stable and render-ready.** `RunOutcomeSummary.to_dict()`,
   `CatalogEntry.to_dict()`, `RunComparison.to_dict()` and the sweep summary document are
   returned as they are: the UI (Slice 11) renders them and derives nothing.
3. **A caller cannot widen its authority.** `grant=` is intersected with the grant the
   composition layer read from the process environment (`narrow_grant`), so a request
   body can only ask for less. Every other gate — the live opt-in, the guided presence
   opt-in, device contention, the device lease, the cost budget — stays exactly where
   Slices 05, 08 and 09 put it, inside the supervisor's reservation path.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.testlab.bundle_builder import SessionSelector
from jarvis.testlab.bundle_capture import (
    EventSource,
    StateDatabaseEventSource,
    capture_diagnostic_bundle,
)
from jarvis.testlab.capture import capture_code_identity
from jarvis.testlab.catalog import CatalogEntry
from jarvis.testlab.compare import RunComparison, compare_runs
from jarvis.testlab.composition import TestLab, narrow_grant
from jarvis.testlab.hardware.channel import PromptWatcher
from jarvis.testlab.maintenance import MaintenanceReport
from jarvis.testlab.outcomes import classify_run
from jarvis.testlab.primitives import DEFAULT_PRIMITIVES
from jarvis.testlab.profiles import ProfileName, ResourceGrant
from jarvis.testlab.retention import (
    ArchiveRetentionPlan,
    ArchiveRetentionReport,
    ArchiveUsage,
    RetentionPlan,
    apply_archive_retention_plan,
    plan_archive_retention,
    plan_retention,
    referenced_archive_ids,
)
from jarvis.testlab.run_bundle import run_session_selector, select_trace_artifact
from jarvis.testlab.runs import TERMINAL_STATUSES, RunStatus, TestRun
from jarvis.testlab.scenarios import Scenario
from jarvis.testlab.store import (
    BundleQuery,
    BundleSummary,
    RunQuery,
    SweepQuery,
    TestLabStoreError,
)
from jarvis.testlab.supervisor import RunRequest, SupervisorError
from jarvis.testlab.sweeps import SweepRecord, SweepSpec
from jarvis.testlab.validation import TestLabError, fail, format_time

#: `wait_s` ceiling of a long poll. Longer than the Control Center's own event long poll
#: would hold a connection past the point a browser or a proxy keeps it open.
MAX_WAIT_S = 30.0
#: How many event-loop turns `start_sweep` gives the sweep task to register its id.
_SWEEP_HANDSHAKE_TURNS = 50
#: How long `start_sweep` waits for the first sweep record to reach the disk (at most
#: 100 x 20 ms = 2 s). The sweep is already running: this only makes the id usable.
_SWEEP_RECORD_TURNS = 100
_SWEEP_RECORD_POLL_S = 0.02

API_NOT_FOUND = "testlab_api_not_found"
API_INVALID = "testlab_api_invalid"
API_UNAVAILABLE = "testlab_api_unavailable"


class TestLabApiError(TestLabError):
    """A request the facade refuses: an unknown id, an argument it cannot read, a missing source."""


def _not_found(detail: str) -> TestLabApiError:
    return TestLabApiError(API_NOT_FOUND, detail)


# ------------------------------------------------------------------- shapes

def run_view(run: TestRun) -> dict[str, Any]:
    """`{"run": <TestRun>, "outcome": <RunOutcomeSummary>}`: the shape every surface lists.

    The outcome is derived ONCE, here, from the stored record. Slice 11 renders
    `outcome.outcome`, `outcome.failed_assertions` and `outcome.missing_assertions`
    directly and must never re-derive a verdict in JavaScript.
    """
    return {"run": run.to_dict(), "outcome": classify_run(run).to_dict()}


def bundle_view(summary: BundleSummary) -> dict[str, Any]:
    return {"bundle_id": summary.bundle_id, "captured_at": format_time(summary.captured_at),
            "started_at": format_time(summary.started_at), "ended_at": format_time(summary.ended_at),
            "conversation_ids": list(summary.conversation_ids), "session_ids": list(summary.session_ids),
            "finding_count": summary.finding_count, "content_fingerprint": summary.content_fingerprint}


def corrupt_view(entries: Iterable[Any]) -> list[dict[str, Any]]:
    return [{"entry": item.entry, "code": item.code, "detail": item.detail} for item in entries]


def plan_view(plan: RetentionPlan) -> dict[str, Any]:
    """The retention plan as data. A plan is a proposal: nothing here has been deleted."""
    return {"enabled": plan.enabled, "cutoff": format_time(plan.cutoff),
            "deletions": [{"run_id": item.run_id, "reason": item.reason.value,
                           "kind": None if item.kind is None else item.kind.value}
                          for item in plan.deletions],
            "deferred": plan.deferred, "blocked_active": plan.blocked_active,
            "blocked_corrupt": corrupt_view(plan.blocked_corrupt),
            "unmet": [reason.value for reason in plan.unmet]}


def archive_plan_view(plan: ArchiveRetentionPlan) -> dict[str, Any]:
    """What archive retention WOULD delete from `sweeps/` and `bundles/`. Nothing is deleted."""
    return {"enabled": plan.enabled, "cutoff": format_time(plan.cutoff),
            "deletions": [{"kind": item.kind.value, "entry_id": item.entry_id, "reason": item.reason.value}
                          for item in plan.deletions],
            "deferred": plan.deferred, "blocked_active": plan.blocked_active,
            "blocked_referenced": plan.blocked_referenced,
            "blocked_corrupt": corrupt_view(plan.blocked_corrupt),
            "unmet": [reason.value for reason in plan.unmet]}


def archive_maintenance_view(report: ArchiveRetentionReport | None) -> dict[str, Any]:
    if report is None:
        return {"ran": False, "deleted": [], "delete_failures": []}
    return {"ran": True,
            "deleted": [{"kind": item.kind.value, "entry_id": item.entry_id} for item in report.deleted],
            "delete_failures": [{"kind": kind, "entry_id": entry_id, "code": code}
                                for kind, entry_id, code in report.skipped]}


def maintenance_view(report: MaintenanceReport | None) -> dict[str, Any]:
    """What one upkeep pass did, or why none ran."""
    if report is None:
        return {"ran": False, "reason": "a run is active or maintenance is disabled"}
    retention = report.retention
    return {"ran": True, "swept": report.swept, "sweep_error": report.sweep_error,
            "skipped_active": list(report.skipped_active),
            "deleted": [] if retention is None else list(retention.deleted),
            # A refused deletion is reported with its stable code, never dropped: the next
            # pass re-plans, and an operator must be able to see a run that will not go.
            "delete_failures": [] if retention is None else [
                {"run_id": run_id, "code": code} for run_id, code in retention.skipped]}


def sweep_view(record: SweepRecord, summary: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"sweep": record.to_dict(), "summary": None if summary is None else dict(summary)}


# --------------------------------------------------------------------- API

class TestLabApi:
    """Every Test Lab operation, once, for the CLI, the HTTP routes and any script."""

    __test__ = False  # not a pytest test class, despite the name

    def __init__(self, lab: TestLab) -> None:
        if not isinstance(lab, TestLab):
            raise fail("TestLabApi takes a composed TestLab")
        self._lab = lab
        self._sweep_tasks: set[asyncio.Task[Any]] = set()

    @property
    def lab(self) -> TestLab:
        return self._lab

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> dict[str, Any]:
        """Start the supervisor and report what it adopted from a previous process."""
        report = await self._lab.start()
        return {"reaped": [{"run_id": run_id, "code": code} for run_id, code in report.reaped],
                "recovered": list(report.recovered), "active_elsewhere": list(report.active_elsewhere),
                "failed": [{"run_id": run_id, "code": code} for run_id, code in report.failed],
                "scratch_removed": report.scratch_removed}

    async def aclose(self) -> None:
        """Stop every sweep this facade started, then the supervisor."""
        for task in sorted(self._sweep_tasks, key=id):
            task.cancel()
        if self._sweep_tasks:
            await asyncio.gather(*self._sweep_tasks, return_exceptions=True)
            self._sweep_tasks.clear()
        await self._lab.aclose()

    # --------------------------------------------------------------- catalog

    async def list_diagnostics(self) -> dict[str, Any]:
        """The latest published version of every official diagnostic."""
        catalog = await asyncio.to_thread(lambda: self._lab.catalog)
        return {"diagnostics": [entry.to_dict() for entry in catalog.list_diagnostics()]}

    async def describe(self, diagnostic_id: str, version: int | None = None) -> dict[str, Any]:
        """One version (the latest by default), with every version of it listed beside."""
        entry = await asyncio.to_thread(self._entry, diagnostic_id, version)
        history = self._lab.catalog.history(diagnostic_id)
        return {"diagnostic": entry.to_dict(), "versions": [item.version for item in history]}

    def _entry(self, diagnostic_id: str, version: int | None) -> CatalogEntry:
        return self._lab.catalog.describe(diagnostic_id, version)

    def _entry_or_none(self, run: TestRun) -> CatalogEntry | None:
        """The declaration a stored run was judged by, or None when it is not in this catalog."""
        try:
            return self._lab.catalog.describe(run.diagnostic_id, run.diagnostic_version)
        except TestLabError:
            # Captured, argued: a run of an ad-hoc or withdrawn diagnostic is still a
            # record a caller must be able to read. The view says so with `declaration: null`
            # instead of refusing the whole response.
            return None

    # ------------------------------------------------------------------ runs

    async def check_run_request(self, diagnostic_id: str, profile: ProfileName | str, *,
                                version: int | None = None,
                                scenario: Scenario | Mapping[str, Any] | None = None) -> CatalogEntry:
        """Every refusal a run request earns BEFORE anything is created or locked.

        The profile name, whether the resolved declaration DECLARES that profile, the
        ad-hoc scenario's vocabulary and the existence of the declaration are all questions
        for the catalog, which needs no work root. Both surfaces call this before taking
        one, so an unknown diagnostic never leaves a directory and a lock behind on a
        machine where nothing was ever run.

        The declared-profile check is here and not only in the supervisor because of what
        the operator sees otherwise: `run voice.barge_in_response` takes `--profile virtual`
        by default and that diagnostic is `hardware:guided` only, so the run went as far as
        the work root before being refused - and while the Control Center holds it, the
        refusal that came back was `testlab_supervisor_work_root_busy`, which names the
        wrong cause entirely.

        It only MOVES a refusal earlier: `submit_run` resolves the entry again and the
        supervisor stays the authority on what a run is queued against.
        """
        resolved = _profile(profile)
        _scenario(scenario)
        entry = await asyncio.to_thread(self._entry, diagnostic_id, version)
        entry.resources_and_cost(resolved)
        return entry

    async def submit_run(self, diagnostic_id: str, profile: ProfileName | str, *, version: int | None = None,
                         parameters: Mapping[str, Any] | None = None,
                         overrides: Mapping[str, Any] | None = None,
                         scenario: Scenario | Mapping[str, Any] | None = None,
                         bundle_id: str | None = None, sweep_id: str | None = None,
                         parent_run_id: str | None = None, grant: ResourceGrant | None = None,
                         allow_audio_artifacts: bool = False) -> dict[str, Any]:
        """Queue one run and return its id at once. Long work never blocks the caller.

        `scenario` replaces the manifest scenario (this is the "submit a scenario"
        operation): a mapping is decoded against the registered primitive vocabulary, so
        an ad-hoc scenario can reach nothing a manifest could not declare.
        """
        request = RunRequest(
            diagnostic_id=diagnostic_id, profile=_profile(profile), version=version,
            parameters=dict(parameters or {}), overrides=dict(overrides or {}),
            scenario=_scenario(scenario), bundle_id=bundle_id, sweep_id=sweep_id,
            parent_run_id=parent_run_id, grant=narrow_grant(self._lab.config.grant, grant),
            allow_audio_artifacts=bool(allow_audio_artifacts))
        run_id = await self._lab.supervisor.submit(request)
        return {"run_id": run_id}

    async def get_run(self, run_id: str, *, wait_s: float | None = None) -> dict[str, Any]:
        """One run. With `wait_s`, wait (bounded) for it to become terminal before answering.

        The wait is the progress mechanism for a caller that cannot hold a coroutine: a
        browser polls with `wait_s`, gets the terminal record as soon as there is one, and
        otherwise gets the current record back when the bound expires — never nothing.
        """
        run = await self._read_run(run_id)
        if wait_s and run.status not in TERMINAL_STATUSES:
            run = await self._wait_bounded(run_id, min(float(wait_s), MAX_WAIT_S))
        return run_view(run)

    async def _wait_bounded(self, run_id: str, timeout_s: float) -> TestRun:
        try:
            return await self._lab.supervisor.wait(run_id, timeout_s=timeout_s)
        except (asyncio.TimeoutError, SupervisorError):
            # Captured, argued: the bound expiring is the normal answer of a long poll,
            # and a run THIS supervisor does not hold (adopted from a previous process)
            # still has a readable record. Both mean "here is where it is now".
            return await self._read_run(run_id)

    async def show_run(self, run_id: str, *, wait_s: float | None = None) -> dict[str, Any]:
        """One run with its outcome, its artifacts and the declaration it was judged by.

        `wait_s` bounds a wait for the terminal record first, so one shape answers both
        "what is it now" and "tell me when it is done".
        """
        run = await self._read_run(run_id)
        if wait_s and run.status not in TERMINAL_STATUSES:
            run = await self._wait_bounded(run_id, min(float(wait_s), MAX_WAIT_S))
        entry = await asyncio.to_thread(self._entry_or_none, run)
        view = run_view(run)
        view["declaration"] = None if entry is None else entry.to_dict()
        view["artifacts"] = [ref.to_dict() for ref in run.artifacts]
        return view

    async def cancel_run(self, run_id: str, *, reason: str | None = None) -> dict[str, Any]:
        """Ask a run to stop. `held` is false when this supervisor does not own it."""
        run = await self._read_run(run_id)
        held = await self._lab.supervisor.cancel(run_id, reason=reason)
        return {"run_id": run_id, "held": held, "status": run.status.value,
                "terminal": run.status in TERMINAL_STATUSES}

    async def query_runs(self, **filters: Any) -> dict[str, Any]:
        """Stored runs, newest first by default. Filters are exactly `RunQuery`'s."""
        query = _run_query(filters)
        page = await asyncio.to_thread(self._lab.store.list_runs, query)
        return {"runs": [run_view(run) for run in page.runs], "corrupt": corrupt_view(page.corrupt),
                "next_cursor": page.next_cursor}

    async def read_artifact(self, run_id: str, path: str) -> tuple[bytes, dict[str, Any]]:
        """`(bytes, ArtifactRef)` of one stored artifact, verified against its recorded sha256."""
        run = await self._read_run(run_id)
        ref = next((item for item in run.artifacts if item.path == path), None)
        if ref is None:
            raise _not_found(f"run {run_id} has no artifact at that path")
        data = await asyncio.to_thread(self._lab.store.read_artifact, run_id, path)
        return data, ref.to_dict()

    async def _read_run(self, run_id: str) -> TestRun:
        return await asyncio.to_thread(self._lab.store.get_run, run_id)

    # ----------------------------------------------------------- comparison

    async def compare(self, baseline_run_id: str, candidate_run_id: str) -> dict[str, Any]:
        """Two runs of one diagnostic, compared against their own declarations."""
        baseline = await self._read_run(baseline_run_id)
        candidate = await self._read_run(candidate_run_id)
        comparison = await asyncio.to_thread(self._compare, baseline, candidate)
        return comparison.to_dict()

    def _compare(self, baseline: TestRun, candidate: TestRun) -> RunComparison:
        base_entry, candidate_entry = self._entry_or_none(baseline), self._entry_or_none(candidate)
        return compare_runs(baseline, candidate,
                            metrics=None if base_entry is None else base_entry.diagnostic,
                            candidate_metrics=None if candidate_entry is None else candidate_entry.diagnostic)

    # ---------------------------------------------------------------- sweeps

    async def run_sweep(self, spec: SweepSpec | Mapping[str, Any], *,
                        grant: ResourceGrant | None = None) -> dict[str, Any]:
        """Execute a whole sweep and return its final record (blocking: the CLI uses this)."""
        record = await self._lab.sweep_runner.run(sweep_spec(spec),
                                                  grant=narrow_grant(self._lab.config.grant, grant))
        summary = await self._sweep_summary_or_none(record.sweep_id)
        return sweep_view(record, summary)

    async def start_sweep(self, spec: SweepSpec | Mapping[str, Any], *,
                          grant: ResourceGrant | None = None) -> dict[str, Any]:
        """Start a sweep in the background and return its id (non-blocking: HTTP uses this).

        A sweep is minutes of work, so the HTTP surface must not hold the request open for
        it. The id comes from the runner's own registry, which `SweepRunner.run` fills
        before its first await; a declaration the runner refuses surfaces here, as an
        error, rather than disappearing into a background task nobody looks at.

        The answer waits until the record is actually ON DISK: handing back an id that
        `GET /api/testlab/sweeps/{id}` would answer 404 for is worse than a slightly later
        202, and a poller has no way to tell that 404 from a mistyped id.
        """
        runner = self._lab.sweep_runner
        before = set(runner.active_sweep_ids)
        task = asyncio.create_task(runner.run(sweep_spec(spec),
                                              grant=narrow_grant(self._lab.config.grant, grant)),
                                   name="testlab-sweep")
        self._sweep_tasks.add(task)
        task.add_done_callback(self._sweep_tasks.discard)
        for _ in range(_SWEEP_HANDSHAKE_TURNS):
            await asyncio.sleep(0)
            started = sorted(set(runner.active_sweep_ids) - before)
            if started:
                await self._await_sweep_record(started[0], task)
                return {"sweep_id": started[0]}
            if task.done():
                # Either it was refused (the exception is the honest answer) or it
                # finished before we looked, which a one-point sweep can genuinely do.
                return {"sweep_id": task.result().sweep_id}
        raise TestLabApiError(API_UNAVAILABLE, "the sweep did not start within the handshake window")

    async def _await_sweep_record(self, sweep_id: str, task: asyncio.Task[Any]) -> None:
        """Wait (bounded) for the sweep's first record to be written, or give up quietly.

        Giving up quietly is deliberate: the sweep IS running and its id is valid, so the
        caller must have it. A poller that gets one 404 before the first write retries,
        which is what it would do anyway.
        """
        for _ in range(_SWEEP_RECORD_TURNS):
            try:
                await asyncio.to_thread(self._lab.sweep_store.get_sweep, sweep_id)
                return
            except TestLabStoreError:
                if task.done():
                    return
                await asyncio.sleep(_SWEEP_RECORD_POLL_S)

    async def cancel_sweep(self, sweep_id: str) -> dict[str, Any]:
        held = await self._lab.sweep_runner.cancel(sweep_id)
        return {"sweep_id": sweep_id, "held": held}

    async def get_sweep(self, sweep_id: str) -> dict[str, Any]:
        record = await asyncio.to_thread(self._lab.sweep_store.get_sweep, sweep_id)
        return sweep_view(record, await self._sweep_summary_or_none(sweep_id))

    async def list_sweeps(self, **filters: Any) -> dict[str, Any]:
        query = SweepQuery(**{name: value for name, value in filters.items() if value is not None})
        page = await asyncio.to_thread(self._lab.sweep_store.list_sweeps, query)
        return {"sweeps": [record.to_dict() for record in page.sweeps], "corrupt": corrupt_view(page.corrupt),
                "next_cursor": page.next_cursor}

    async def _sweep_summary_or_none(self, sweep_id: str) -> Mapping[str, Any] | None:
        try:
            return await asyncio.to_thread(self._lab.sweep_store.get_sweep_summary, sweep_id)
        except TestLabStoreError:
            # Captured, argued: the summary is written when the sweep ENDS, so its absence
            # is the normal state of a sweep in flight, not a fault.
            return None

    # --------------------------------------------------------------- bundles

    async def capture_bundle(self, selector: SessionSelector, *, with_events: bool = True,
                             store: bool = True) -> dict[str, Any]:
        """Normalize one real session into a DiagnosticBundle (the "inspect a session" operation).

        The journal is the live `runtime/trace.jsonl`; Conversation Events are read
        STRICTLY read-only from Core's state database when it exists. A source that is
        absent is reported as `not_requested` / `unavailable` in the bundle's own
        coverage, never silently dropped.
        """
        config = self._lab.config
        code = await capture_code_identity(config.repo_root)
        result = await capture_diagnostic_bundle(
            selector, captured_at=self._lab.supervisor.clock(), trace_path=_existing(config.trace_path),
            event_source=await asyncio.to_thread(self._event_source) if with_events else None,
            reports_directory=_existing(config.reports_directory), code=code,
            store=self._lab.bundle_store if store else None, diagnostics=self._lab.diagnostics)
        bundle = result.bundle
        return {"bundle": bundle_view(BundleSummary.of(bundle)),
                "stored": None if result.put is None else result.put.status.value,
                "coverage": dict(bundle.document["coverage"]),
                "findings": [dict(item) for item in bundle.findings]}

    def _event_source(self) -> EventSource | None:
        path = self._lab.config.state_database
        return StateDatabaseEventSource(path) if path.is_file() else None

    async def capture_run_bundle(self, run_id: str, *, session_id: str | None = None,
                                 attach: bool = True, store: bool = True) -> dict[str, Any]:
        """Normalize a stored RUN's own trace into a bundle, and reference it from the run.

        The other half of `capture_bundle`: same reader, same rules, same document, over
        the `trace_excerpt` a run committed instead of the live journal. Conversation
        Events are never read here — a run writes none, and pointing this at the live
        state database would mix a reproduction with whatever the workstation was doing.

        `attach` writes `TestRun.bundle_id`, which is the point: `runs --bundle-id <id>`
        then finds every run that normalized to the same evidence. It is idempotent (a
        bundle id is content-derived) and it is the only field of a terminal record the
        store will write. `store=False` builds the document and keeps nothing, and it
        therefore attaches nothing either: a record may not point at a bundle that was
        never written.
        """
        run = await self._read_run(run_id)
        ref = select_trace_artifact(run)
        path = await asyncio.to_thread(self._lab.store.artifact_path, run_id, ref.path)
        result = await capture_diagnostic_bundle(
            run_session_selector(run, session_id=session_id), captured_at=self._lab.supervisor.clock(),
            trace_path=path, event_source=None, code=run.code, config_fingerprint=run.config_fingerprint,
            store=self._lab.bundle_store if store else None, diagnostics=self._lab.diagnostics)
        bundle = result.bundle
        attached = run.bundle_id
        if attach and store:
            attached = (await asyncio.to_thread(self._lab.store.attach_bundle, run_id, bundle.bundle_id)).bundle_id
        return {"run_id": run_id, "artifact": ref.path, "attached_bundle_id": attached,
                # Did THIS call make the reference? A run captured twice, or captured with
                # `store=False` after it was already attached, still HAS a bundle id, and
                # reporting that as "now references" would credit this call with somebody
                # else's write.
                "attached": bool(attach and store and run.bundle_id is None and attached is not None),
                "bundle": bundle_view(BundleSummary.of(bundle)),
                "stored": None if result.put is None else result.put.status.value,
                "coverage": dict(bundle.document["coverage"]),
                "findings": [dict(item) for item in bundle.findings]}

    async def list_bundles(self, **filters: Any) -> dict[str, Any]:
        query = BundleQuery(**{name: value for name, value in filters.items() if value is not None})
        page = await asyncio.to_thread(self._lab.bundle_store.list_bundles, query)
        return {"bundles": [bundle_view(summary) for summary in page.bundles],
                "corrupt": corrupt_view(page.corrupt), "next_cursor": page.next_cursor}

    async def get_bundle(self, bundle_id: str, *, document: bool = False) -> dict[str, Any]:
        bundle = await asyncio.to_thread(self._lab.bundle_store.get_bundle, bundle_id)
        view: dict[str, Any] = {"bundle": bundle_view(BundleSummary.of(bundle)),
                                "coverage": dict(bundle.document["coverage"]),
                                "findings": [dict(item) for item in bundle.findings]}
        if document:
            view["document"] = bundle.to_dict()
        return view

    # ---------------------------------------------------------- guided prompts

    def prompt_watcher(self, run_id: str) -> PromptWatcher:
        """The presenter's half of the guided channel for one run, in its own scratch."""
        return PromptWatcher(Path(self._lab.config.work_root) / run_id)

    async def pending_prompt(self, run_id: str) -> dict[str, Any]:
        """The prompt awaiting a human, with the deadline and how much of it is left.

        `remaining_s` is computed from the worker's own `shown_at`, so a presenter never
        shows a human more time than the run will actually wait. `null` when no prompt is
        open, which is also the answer for a run that is not guided.
        """
        watcher = self.prompt_watcher(run_id)
        pending = await asyncio.to_thread(watcher.pending_shown)
        if pending is None:
            return {"run_id": run_id, "prompt": None}
        prompt, sequence, shown_at = pending
        elapsed = max(0.0, self._lab.supervisor.clock().timestamp() - shown_at)
        return {"run_id": run_id, "prompt": prompt.to_dict(), "sequence": sequence,
                "shown_at": shown_at, "elapsed_s": round(elapsed, 3),
                "remaining_s": round(max(0.0, prompt.deadline_s - elapsed), 3)}

    async def acknowledge_prompt(self, run_id: str, prompt_id: str, sequence: int, *,
                                 refused: bool = False, note: str | None = None) -> dict[str, Any]:
        """Answer the open prompt. A refusal is allowed and is never a product failure."""
        watcher = self.prompt_watcher(run_id)
        await asyncio.to_thread(watcher.acknowledge, prompt_id, sequence, refused=refused, note=note)
        return {"run_id": run_id, "prompt_id": prompt_id, "sequence": sequence, "refused": bool(refused)}

    # ------------------------------------------------------ status and upkeep

    async def status(self) -> dict[str, Any]:
        """What this Test Lab is, right now: composition, queue, reservations, devices."""
        supervisor = self._lab.supervisor
        contention = await asyncio.to_thread(self._lab.contention.detect)
        usage = await asyncio.to_thread(self._lab.store.storage_usage)
        return {"config": self._lab.config.to_dict(), "started": self._lab.started,
                "active_runs": list(supervisor.active_run_ids), "pending_runs": list(supervisor.pending_run_ids),
                "reserved_capabilities": sorted(item.value for item in supervisor.reserved_capabilities),
                "active_sweeps": list(self._lab.sweep_runner.active_sweep_ids),
                # `available` and `reason` are derived by the domain here, once, so a CLI
                # table and the Slice 11 panel say the same thing about the microphone.
                "contention": {**contention.to_dict(), "available": contention.available,
                               "reason": contention.reason()},
                "storage": {"runs": len(usage.runs), "corrupt": len(usage.corrupt),
                            "total_bytes": sum(item.total_bytes for item in usage.runs)}}

    async def retention_plan(self) -> dict[str, Any]:
        """What retention WOULD delete, in all three stores. Nothing is deleted by reading this."""
        policy = self._lab.config.policy.maintenance.retention
        now = self._lab.supervisor.clock()
        usage = await asyncio.to_thread(self._lab.store.storage_usage)
        archive, referenced = await asyncio.to_thread(self._archive_usage, usage)
        return {**plan_view(await asyncio.to_thread(plan_retention, policy, usage, now=now)),
                "archive": archive_plan_view(await asyncio.to_thread(plan_archive_retention, policy, archive,
                                                                     now=now, referenced=referenced))}

    def _archive_usage(self, usage: Any) -> tuple[ArchiveUsage, frozenset[str]]:
        """`sweeps/` and `bundles/` usage, plus the ids a stored run points at. Synchronous."""
        return (ArchiveUsage.of(self._lab.sweep_store.storage_usage(), self._lab.bundle_store.storage_usage()),
                referenced_archive_ids(usage))

    async def maintain(self) -> dict[str, Any]:
        """Run one upkeep pass over all three stores, if no run is active.

        The RUN half is the supervisor's, because a temporaries sweep can race a
        `put_artifact` and only the supervisor knows no run of its own is writing. The
        ARCHIVE half runs here and takes no such gate: it touches neither `runs/` nor a
        run scratch, and the one thing it must not disturb — a sweep in flight — it reads
        from the sweep runner and from each record's own status.
        """
        report = await self._lab.supervisor.maintain()
        view = maintenance_view(report)
        view["archive"] = archive_maintenance_view(None if report is None else await self._maintain_archive())
        return view

    async def _maintain_archive(self) -> ArchiveRetentionReport:
        policy = self._lab.config.policy.maintenance.retention
        now = self._lab.supervisor.clock()
        usage = await asyncio.to_thread(self._lab.store.storage_usage)
        archive, referenced = await asyncio.to_thread(self._archive_usage, usage)
        plan = await asyncio.to_thread(plan_archive_retention, policy, archive, now=now,
                                       referenced=referenced | frozenset(self._lab.sweep_runner.active_sweep_ids))
        return await asyncio.to_thread(apply_archive_retention_plan, plan,
                                       sweep_store=self._lab.sweep_store, bundle_store=self._lab.bundle_store)


# ------------------------------------------------------------------ decoding

def _profile(value: ProfileName | str) -> ProfileName:
    if isinstance(value, ProfileName):
        return value
    try:
        return ProfileName(value)
    except ValueError:
        raise TestLabApiError(API_INVALID, f"unknown profile (expected one of "
                                           f"{', '.join(item.value for item in ProfileName)})") from None


def _scenario(value: Scenario | Mapping[str, Any] | None) -> Scenario | None:
    if value is None or isinstance(value, Scenario):
        return value
    return Scenario.from_dict(value, primitives=DEFAULT_PRIMITIVES)


def sweep_spec(value: SweepSpec | Mapping[str, Any]) -> SweepSpec:
    """A `SweepSpec` from a declaration document, or the one already given.

    Public because the HTTP route decodes the spec BEFORE taking the work root, so a
    declaration the domain refuses never creates a directory.
    """
    return value if isinstance(value, SweepSpec) else SweepSpec.from_dict(value)


def _run_query(filters: Mapping[str, Any]) -> RunQuery:
    """`RunQuery` from loose filters: `None` means "no filter", statuses may be strings."""
    given = {name: value for name, value in filters.items() if value is not None}
    if "profile" in given:
        given["profile"] = _profile(given["profile"])
    statuses = given.get("statuses")
    if statuses is not None:
        given["statuses"] = frozenset(item if isinstance(item, RunStatus) else RunStatus(item)
                                      for item in statuses)
    return RunQuery(**given)


def _existing(path: Path) -> Path | None:
    """The path when it exists, else None, which the bundle records as `not_requested`."""
    return path if path.exists() else None


def parse_time_argument(value: str | None, name: str) -> datetime | None:
    """An ISO-8601 UTC instant from a CLI argument or a query string, or None."""
    if value is None or value == "":
        return None
    from jarvis.testlab.validation import to_event_time

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise TestLabApiError(API_INVALID, f"{name} must be an ISO-8601 instant") from None
    if parsed.tzinfo is None:
        raise TestLabApiError(API_INVALID, f"{name} must carry a timezone (use ...Z or +00:00)")
    return to_event_time(parsed)
