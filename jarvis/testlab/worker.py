"""The Test Lab worker process: `python -m jarvis.testlab.worker <job.json>`.

Binding contract: `docs/testlab.md` ("Supervisor and workers"). One worker
executes exactly one run and then exits. It never writes the run record: it
writes artifacts through the store, then a `result.json` the supervisor turns
into a terminal `TestRun`.

Isolation is checked before anything else runs. The supervisor points
`JARVIS_RUNTIME_DIR` and `JARVIS_DATA_ROOT` inside the per-run scratch and
copies the settings file there; the worker refuses to start unless the roots
`V2Settings` actually resolves are inside that scratch. The permanent
`runtime/control-center-settings.json` is therefore never a write target
(READINESS B4.2), and a mistake in the environment stops the run instead of
silently touching the live Jarvis.

Exit codes: 0 when the run produced measurements, 1 when it wrote a failed
result, 2 when it could not even write one (the supervisor then reports
`worker_crashed` from the exit code and the stderr tail).
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Any

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.testlab._fs import EntryLock, write_atomic
from jarvis.testlab.catalog import load_catalog
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.jobs import (
    CANCEL_FILE_NAME,
    DATA_DIR_NAME,
    FAILURE_CATALOG_UNAVAILABLE,
    FAILURE_CANCELLED,
    FAILURE_ISOLATION_VIOLATION,
    FAILURE_JOB_INVALID,
    FAILURE_RUNNER_FAILED,
    FAILURE_RUNNER_UNAVAILABLE,
    FAILURE_RUN_TIMEOUT,
    HEARTBEAT_FILE_NAME,
    RESULT_FILE_NAME,
    RUNTIME_DIR_NAME,
    WORKER_LOCK_NAME,
    WORKER_LOG_NAME,
    WorkerJob,
    WorkerResult,
    WorkerStatus,
    worker_failure,
)
from jarvis.testlab.primitives import DEFAULT_PRIMITIVES, ScenarioContext, check_scenario
from jarvis.testlab.runners import RunArtifacts, RunCancelled, RunContext, RunOutcome
from jarvis.testlab.runs import ArtifactRef
from jarvis.testlab.selftest import catalog_implementations
from jarvis.testlab.validation import TestLabError, canonical_json, decode_json_document

#: How many progress lines one run may write to its worker log.
MAX_LOG_LINES = 2000
MAX_LOG_LINE_CHARS = 512
#: The worker lock is taken once, immediately; contention means another worker owns this run.
LOCK_TIMEOUT_S = 2.0
RESULT_TMP_PREFIX = ".result-"

EXIT_MEASURED = 0
EXIT_FAILED = 1
EXIT_NO_RESULT = 2


class WorkerRefusal(Exception):
    """A structured refusal before or around the runner. Carries the failure code to persist."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def runtime_dir_of(scratch: Path) -> Path:
    return Path(scratch) / RUNTIME_DIR_NAME


def data_root_of(scratch: Path) -> Path:
    return Path(scratch) / DATA_DIR_NAME


def is_inside(path: Path, root: Path) -> bool:
    """True when `path` is `root` or below it, with both ends fully resolved."""
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except OSError:
        return False


def check_isolation(scratch: Path) -> None:
    """Refuse to run unless the roots this process resolves are inside the run scratch.

    This is the mechanical half of the isolation rule: the supervisor sets the
    environment, and the worker proves the settings actually landed there before
    a runner can open anything.
    """
    declared = os.environ.get("JARVIS_TESTLAB_RUN_SCRATCH")
    if not declared or not is_inside(Path(declared), scratch) or not is_inside(scratch, Path(declared)):
        raise WorkerRefusal(FAILURE_ISOLATION_VIOLATION,
                            "JARVIS_TESTLAB_RUN_SCRATCH does not name this run's scratch directory")
    try:
        from jarvis.v2_config import V2Settings

        settings = V2Settings.load()
    except Exception as exc:
        raise WorkerRefusal(FAILURE_ISOLATION_VIOLATION,
                            f"run-local settings cannot be resolved ({type(exc).__name__})") from exc
    for name, root in (("runtime_root", settings.runtime_root), ("data_root", settings.data_root)):
        if not is_inside(root, scratch):
            raise WorkerRefusal(FAILURE_ISOLATION_VIOLATION,
                                f"{name} resolves outside the run scratch directory")


# ------------------------------------------------------------- scratch I/O

@dataclass(slots=True)
class WorkerLog:
    """Bounded progress log of one run, committed as a `worker_log` artifact by the supervisor."""

    path: Path
    lines: int = 0

    def write(self, message: str) -> None:
        if self.lines >= MAX_LOG_LINES:
            return
        self.lines += 1
        text = str(message).replace("\r", " ").replace("\n", " ")[:MAX_LOG_LINE_CHARS]
        if self.lines == MAX_LOG_LINES:
            text = "worker log truncated: line budget reached"
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        try:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(f"{stamp}Z {text}\n")
        except OSError:
            # intentional: the progress log is evidence, not the run. Losing a line must
            # not fail a run; the supervisor still records the outcome and the stderr tail.
            self.lines = MAX_LOG_LINES


def write_heartbeat(scratch: Path, run_id: str, phase: str) -> None:
    """Refresh the liveness file. Its mtime is what the supervisor watches."""
    payload = json.dumps({"run_id": run_id, "pid": os.getpid(), "phase": phase, "stamp": time.time()})
    tmp = scratch / f".{HEARTBEAT_FILE_NAME}.tmp"
    try:
        tmp.write_text(payload, encoding="utf-8")
        replace_with_retry(tmp, scratch / HEARTBEAT_FILE_NAME)
    except OSError:
        # intentional: a missed heartbeat only costs the supervisor its progress reading;
        # the supervisor's own startup and run deadlines still bound the run.
        pass


def write_result(scratch: Path, result: WorkerResult) -> None:
    """Atomically publish the result: the supervisor reads either the old file or the whole new one."""
    write_atomic(Path(scratch), RESULT_FILE_NAME, canonical_json(result.to_dict()).encode("utf-8"),
                 label=f"run {result.run_id}", tmp_prefix=RESULT_TMP_PREFIX, max_path_chars=None,
                 replace=replace_with_retry)


def read_job(path: Path) -> WorkerJob:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkerRefusal(FAILURE_JOB_INVALID, f"job file cannot be read ({type(exc).__name__})") from exc
    try:
        return WorkerJob.from_dict(decode_json_document(text))
    except TestLabError as exc:
        raise WorkerRefusal(FAILURE_JOB_INVALID, f"job file does not decode ({exc.code})") from exc


# ------------------------------------------------------------- execution

def resolve_runner(job: WorkerJob) -> tuple[Any, Any]:
    """(DiagnosticSpec, runner) for this job, or a structured refusal.

    The implementation registry is the in-code one plus the self-test fixture
    names, which no official manifest may reference (`jarvis.testlab.selftest`).
    A reserved name (no factory yet) refuses with `runner_unavailable`.
    """
    registry = catalog_implementations()
    try:
        catalog = load_catalog(Path(job.catalog_root), implementations=registry)
        entry = catalog.describe(job.diagnostic_id, job.diagnostic_version)
    except TestLabError as exc:
        raise WorkerRefusal(FAILURE_CATALOG_UNAVAILABLE, f"catalog: {exc.code}") from exc
    spec = entry.diagnostic
    if spec.fingerprint() != job.diagnostic_fingerprint:
        raise WorkerRefusal(FAILURE_CATALOG_UNAVAILABLE,
                            "the catalog declaration changed since the run was queued")
    try:
        availability = entry.resources_and_cost(job.profile)
    except TestLabError as exc:
        raise WorkerRefusal(FAILURE_RUNNER_UNAVAILABLE, f"profile: {exc.code}") from exc
    implementation = availability.implementation
    if implementation.name != job.implementation:
        raise WorkerRefusal(FAILURE_RUNNER_UNAVAILABLE, "the profile resolves to another implementation name")
    if implementation.factory is None:
        raise WorkerRefusal(FAILURE_RUNNER_UNAVAILABLE,
                            f"implementation {implementation.name} is {implementation.unavailable_reason}")
    try:
        runner = implementation.factory()
    except Exception as exc:
        raise WorkerRefusal(FAILURE_RUNNER_UNAVAILABLE,
                            f"implementation {implementation.name} could not be built "
                            f"({type(exc).__name__})") from exc
    if not hasattr(runner, "run"):
        raise WorkerRefusal(FAILURE_RUNNER_UNAVAILABLE,
                            f"implementation {implementation.name} is not a DiagnosticRunner")
    return spec, runner


@dataclass(slots=True)
class _Stop:
    """Why the cooperative stop was requested. Kept by the heartbeat, read once the runner returns."""

    reason: str | None = None


async def _heartbeat(scratch: Path, run_id: str, context: RunContext, stop: _Stop, interval_s: float) -> None:
    """Prove the worker is alive, and notice a cooperative stop, on the same tick.

    It keeps ticking after a stop is requested: a runner that ignores the request
    is still alive, and the supervisor must tell that apart from a wedged worker
    (it kills the first on the cancel grace, the second on the heartbeat timeout).
    """
    cancel_marker = scratch / CANCEL_FILE_NAME
    while True:
        write_heartbeat(scratch, run_id, "stopping" if stop.reason else "running")
        if stop.reason is None:
            if cancel_marker.exists():
                stop.reason = FAILURE_CANCELLED
            elif context.remaining_s <= 0:
                stop.reason = FAILURE_RUN_TIMEOUT
            if stop.reason is not None:
                context.cancelled.set()
        await asyncio.sleep(interval_s)


async def execute(job: WorkerJob, log: WorkerLog) -> WorkerResult:
    """Resolve, run and measure. Every failure comes back as a `WorkerResult`, never as a traceback."""
    scratch = Path(job.scratch_root)
    spec, runner = resolve_runner(job)
    if job.scenario is not None:
        # The catalog already checked a manifest scenario; a supplied one is checked here,
        # against this diagnostic and this profile, before a single step executes.
        try:
            check_scenario(job.scenario, primitives=DEFAULT_PRIMITIVES, profiles=(job.profile,),
                           context=ScenarioContext.for_diagnostic(spec))
        except TestLabError as exc:
            raise WorkerRefusal(FAILURE_RUNNER_UNAVAILABLE, f"scenario refused ({exc.code})") from exc
    # The runner gets the artifact-only facade, never this store: the record is the
    # supervisor's, and another run is none of its business.
    store = FilesystemTestRunStore(Path(job.store_root))
    loop = asyncio.get_running_loop()
    context = RunContext(
        run_id=job.run_id,
        diagnostic=spec,
        profile=job.profile,
        parameters=job.parameters,
        overrides=job.overrides,
        scenario=job.scenario,
        runtime_dir=runtime_dir_of(scratch),
        data_root=data_root_of(scratch),
        artifacts=RunArtifacts(store, job.run_id),
        cancelled=asyncio.Event(),
        deadline=loop.time() + job.max_duration_s,
        log=log.write,
    )
    stop = _Stop()
    heartbeat = asyncio.create_task(_heartbeat(scratch, job.run_id, context, stop, job.heartbeat_interval_s),
                                    name=f"testlab-heartbeat-{job.run_id}")
    try:
        outcome = await runner.run(context)
    except RunCancelled:
        code = stop.reason or FAILURE_CANCELLED
        log.write(f"run stopped: {code}")
        return WorkerResult(job.run_id, WorkerStatus.FAILED, failure=worker_failure(
            code, f"the runner stopped on {code.replace('_', ' ')}"))
    except Exception as exc:
        # Captured, not swallowed: the failure becomes this run's terminal record, with
        # the exception type in the detail and the traceback on stderr for the artifact.
        code = getattr(exc, "code", None) if isinstance(exc, TestLabError) else None
        log.write(f"runner failed: {code or type(exc).__name__}")
        traceback.print_exc()  # the stderr tail becomes an artifact, so the cause stays readable
        return WorkerResult(job.run_id, WorkerStatus.FAILED,
                            failure=worker_failure(FAILURE_RUNNER_FAILED,
                                                   f"runner raised {code or type(exc).__name__}"))
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        write_heartbeat(scratch, job.run_id, "finished")
    if not isinstance(outcome, RunOutcome):
        return WorkerResult(job.run_id, WorkerStatus.FAILED,
                            failure=worker_failure(FAILURE_RUNNER_FAILED, "the runner did not return a RunOutcome"))
    artifacts = tuple(dict.fromkeys((*context.committed, *outcome.artifacts)))
    try:
        return WorkerResult(job.run_id, WorkerStatus.MEASURED, metrics=outcome.metrics, score=outcome.score,
                            join_ids=outcome.join_ids, artifacts=_refs(artifacts))
    except TestLabError as exc:
        return WorkerResult(job.run_id, WorkerStatus.FAILED,
                            failure=worker_failure(FAILURE_RUNNER_FAILED,
                                                   f"the runner's measurements are invalid ({exc.code})"))


def _refs(values: tuple[Any, ...]) -> tuple[ArtifactRef, ...]:
    return tuple(value for value in values if isinstance(value, ArtifactRef))


async def run_job(job: WorkerJob) -> int:
    scratch = Path(job.scratch_root)
    log = WorkerLog(scratch / WORKER_LOG_NAME)
    log.write(f"worker pid={os.getpid()} run={job.run_id} diagnostic={job.diagnostic_id}"
              f" v{job.diagnostic_version} profile={job.profile.value}")
    write_heartbeat(scratch, job.run_id, "starting")
    try:
        check_isolation(scratch)
        result = await execute(job, log)
    except WorkerRefusal as refusal:
        log.write(f"refused: {refusal.code}")
        result = WorkerResult(job.run_id, WorkerStatus.FAILED,
                              failure=worker_failure(refusal.code, refusal.detail))
    except Exception as exc:
        # Captured: whatever went wrong around the runner, this run still gets a result
        # file. Without one the supervisor can only report `worker_crashed` from an exit
        # code, which says nothing about the cause.
        traceback.print_exc()
        log.write(f"worker failed: {type(exc).__name__}")
        result = WorkerResult(job.run_id, WorkerStatus.FAILED, failure=worker_failure(
            FAILURE_RUNNER_FAILED, f"the worker raised {type(exc).__name__} around the runner"))
    write_result(scratch, result)
    log.write(f"result: {result.status.value}"
              + (f" {result.failure.code}" if result.failure is not None else ""))
    return EXIT_MEASURED if result.status is WorkerStatus.MEASURED else EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis.testlab.worker",
                                     description="Execute one Test Lab run described by a job file.")
    parser.add_argument("job", help="path of the run's job.json")
    arguments = parser.parse_args(argv)
    try:
        job = read_job(Path(arguments.job))
    except WorkerRefusal as refusal:
        # Nothing identifies the run yet, so no result file can be written: the
        # supervisor reports the exit code and this line of stderr.
        print(f"testlab worker refused: {refusal.code}: {refusal.detail}", file=sys.stderr, flush=True)
        return EXIT_NO_RESULT
    scratch = Path(job.scratch_root)
    try:
        with EntryLock(scratch / WORKER_LOCK_NAME, f"run {job.run_id}", LOCK_TIMEOUT_S):
            return asyncio.run(run_job(job))
    except TestLabError as exc:
        print(f"testlab worker refused: {exc.code}: {exc.detail}", file=sys.stderr, flush=True)
        return EXIT_NO_RESULT


if __name__ == "__main__":
    raise SystemExit(main())
