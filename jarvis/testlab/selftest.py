"""TEST FIXTURE diagnostic: the one implementation Slice 05 registers, for its own tests.

Binding contract: `docs/testlab.md` ("Supervisor and workers", "Self-test
fixture"). This is NOT a seed diagnostic runner. It exists so the supervisor,
the worker protocol, the isolation rules and the failure paths can be exercised
with real processes without any voice stack, provider or device. Slice 06
registers the virtual runners of the seed diagnostics; nothing here is ever
referenced by a manifest under `jarvis/testlab/official/`, and the catalog lock
makes such a reference a reviewed change (`tests/unit/test_testlab_catalog.py`
and `tests/unit/test_testlab_supervisor_selftest.py` both assert it).

`selftest.worker` declares one `virtual` profile and a `mode` parameter that
selects the path to exercise, including the abnormal ones: a hard exit with no
result file, an uncancellable sleep, a spawned grandchild (to prove the process
tree is killed as a whole) and a metric the declaration does not contain.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import sys
import time
from typing import Any

from jarvis.testlab.diagnostics import (
    AssertionSpec,
    Comparator,
    DiagnosticSpec,
    MetricDirection,
    MetricSpec,
    MetricUnit,
    ParameterSpec,
    ParameterType,
    ScoreContract,
    ScoreMethod,
)
from jarvis.testlab.implementations import (
    RUNNER_NOT_REGISTERED,
    ImplementationEntry,
    ImplementationRegistry,
    default_implementations,
    registered,
    reserved,
)
from jarvis.testlab.manifests import CatalogLock, DiagnosticManifest, lock_entry_for, render_manifest
from jarvis.testlab.profiles import CostBounds, ProfileName, ProfileSpec
from jarvis.testlab.runners import RunContext, RunOutcome
from jarvis.testlab.runs import ArtifactKind
from jarvis.testlab.virtual.registry import virtual_implementations

SELFTEST_DIAGNOSTIC_ID = "selftest.worker"
SELFTEST_IMPLEMENTATION = "testlab.selftest.virtual"
#: A fixture name that is declared and never registered, so the `runner_unavailable`
#: path stays testable once every real reservation has been implemented by its Slice.
SELFTEST_RESERVED_IMPLEMENTATION = "testlab.selftest.reserved"
#: Prefix of every fixture implementation name, so the catalog test can assert that no
#: official manifest references one.
SELFTEST_IMPLEMENTATION_PREFIX = "testlab.selftest."
#: Exit code of the deliberate hard exit (`mode=crash`): no result file is written.
CRASH_EXIT_CODE = 3
#: File the `spawn_child` mode writes its grandchild pid into, inside the run scratch.
CHILD_PID_FILE = "child.pid"
#: A fixture credential line the `error` mode prints to its log and its stderr. It is
#: assembled from fragments so that no credential-shaped literal sits in the source, and
#: it exists so a test can prove that captured evidence is redacted before it is stored.
FIXTURE_CREDENTIAL = "Authorization: Bearer " + "QA" + "BEARERTOKEN"


class SelfTestMode(StrEnum):
    #: Report `selftest.value` and stop. `value` 0 passes the blocking assertion, anything else fails it.
    MEASURE = "measure"
    #: Sleep `sleep_ms`, honouring a cooperative stop, then report.
    SLEEP = "sleep"
    #: Sleep `sleep_ms` ignoring the cooperative stop: only the forced kill ends this run.
    HANG = "hang"
    #: Spawn a long-lived grandchild, then hang: proves the whole tree is killed.
    SPAWN_CHILD = "spawn_child"
    #: Die immediately without writing a result file (native-crash shape).
    CRASH = "crash"
    #: Raise inside the runner: the worker writes a `runner_failed` result.
    ERROR = "error"
    #: Report a metric the declaration does not contain: `check_run_against_spec` must refuse the run.
    UNDECLARED_METRIC = "undeclared_metric"
    #: Try to write its own verdict and to reach another run, then report a failing measurement.
    #: The stored run must be `failed` from the real measurement, and no other run may be touched.
    FORGE = "forge"


@dataclass(frozen=True, slots=True)
class SelfTestRunner:
    """Deterministic fixture runner. It measures a supplied number and, on demand, misbehaves."""

    async def run(self, context: RunContext) -> RunOutcome:
        mode = SelfTestMode(context.parameters["mode"])
        value = context.parameters["value"]
        sleep_s = context.parameters["sleep_ms"] / 1000
        started = time.monotonic()
        context.log(f"selftest start mode={mode.value} value={value} sleep_ms={context.parameters['sleep_ms']}")
        context.log(f"selftest roots runtime={context.runtime_dir} data={context.data_root}")
        if mode is SelfTestMode.CRASH:
            # Deliberate hard exit: no `finally`, no result file, no flush. This is the
            # shape of a native crash, which the supervisor must still make terminal.
            os._exit(CRASH_EXIT_CODE)
        if mode is SelfTestMode.SPAWN_CHILD:
            await self._spawn_child(context)
        if mode in (SelfTestMode.HANG, SelfTestMode.SPAWN_CHILD):
            await asyncio.sleep(sleep_s)  # deliberately ignores `context.cancelled`
        elif mode is SelfTestMode.SLEEP:
            await context.sleep(sleep_s)
        if mode is SelfTestMode.FORGE:
            value = self._attempt_escalation(context)
        if mode is SelfTestMode.ERROR:
            # A worker printing a credential is what the redaction of captured evidence
            # exists for; this fixture line proves it on both stored artifacts.
            context.log(f"selftest credential probe {FIXTURE_CREDENTIAL}")
            print(f"selftest credential probe {FIXTURE_CREDENTIAL}", file=sys.stderr, flush=True)
            raise RuntimeError("selftest runner failed on purpose")
        elapsed_ms = round((time.monotonic() - started) * 1000)
        context.put_artifact("selftest-report.json", kind=ArtifactKind.REPORT, media_type="application/json",
                             data=f'{{"mode": "{mode.value}", "value": {value}}}'.encode("utf-8"))
        context.log(f"selftest done elapsed_ms={elapsed_ms}")
        name = "selftest.undeclared" if mode is SelfTestMode.UNDECLARED_METRIC else "selftest.value"
        return RunOutcome(metrics={name: value, "selftest.elapsed_ms": elapsed_ms})

    @staticmethod
    def _attempt_escalation(context: RunContext) -> int:
        """Try every way a runner could write a record or reach another run; report what it found.

        Returns the value to measure: 500, which fails the blocking assertion. A run
        of this mode must therefore end `failed`; if it ever ends `passed`, a runner
        concluded its own run behind the supervisor.
        """
        reachable = sorted(name for name in ("update_run", "delete_run", "create_run", "list_runs", "get_run")
                           if hasattr(context.artifacts, name))
        context.log(f"selftest escalation: record methods reachable from the context: {reachable or 'none'}")
        context.log(f"selftest escalation: context exposes a store attribute: {hasattr(context, 'store')}")
        return 500

    @staticmethod
    async def _spawn_child(context: RunContext) -> None:
        """A grandchild that outlives a polite stop; only a tree kill removes it."""
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(600)",
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL)
        (Path(context.runtime_dir).parent / CHILD_PID_FILE).write_text(str(child.pid), encoding="utf-8")
        context.log(f"selftest spawned child pid={child.pid}")


def selftest_implementations() -> tuple[ImplementationEntry, ...]:
    """The fixture implementation entries a worker composes on top of `default_implementations()`."""
    return (registered(SELFTEST_IMPLEMENTATION, ProfileName.VIRTUAL, SelfTestRunner),
            reserved(SELFTEST_RESERVED_IMPLEMENTATION, ProfileName.VIRTUAL, RUNNER_NOT_REGISTERED,
                     "Fixture reservation: a declared name no Slice implements, on purpose."))


def catalog_implementations() -> ImplementationRegistry:
    """The registry a supervisor and its workers resolve implementation names with.

    One definition for both sides: a worker must resolve exactly the names its
    supervisor resolved, or a run could be queued against a declaration the worker
    reads differently. It is the declared catalog, with the reserved names a Slice
    has implemented turned into registrations (Slice 06: the five `virtual` names;
    Slice 08: two `audio` and two `live` names; Slice 09: the four `hardware:*` names;
    Bare Hands Slice 10: one replayed-trace `virtual` name), plus the fixture names. The fixture names are always present and always harmless:
    only a manifest can reference one, and official manifests are locked.

    Registering an `audio`, `live` or `hardware` name makes it RUNNABLE, never
    PERMITTED: the capability gate, the cost budget, device-contention detection, the
    device lease, the live opt-in and the guided presence opt-in all live in the
    supervisor's reservation path, and none of them is affected here.
    """
    from jarvis.testlab.audio.registry import audio_implementations
    from jarvis.testlab.barehands.registry import barehands_implementations
    from jarvis.testlab.hardware.registry import hardware_implementations
    from jarvis.testlab.live.registry import live_implementations

    return (default_implementations()
            .registering((*virtual_implementations(), *audio_implementations(), *live_implementations(),
                          *hardware_implementations(), *barehands_implementations()))
            .with_entries(selftest_implementations()))


def selftest_spec(*, max_duration_s: float = 60.0, implementation: str = SELFTEST_IMPLEMENTATION) -> DiagnosticSpec:
    """The fixture declaration. `max_duration_s` is the run timeout the supervisor enforces.

    `implementation` lets a test point the profile at `SELFTEST_RESERVED_IMPLEMENTATION`
    and exercise the `runner_unavailable` path.
    """
    return DiagnosticSpec(
        diagnostic_id=SELFTEST_DIAGNOSTIC_ID,
        version=1,
        title="Supervisor and worker self-test",
        domain="selftest",
        description="Fixture diagnostic of the Test Lab supervisor; measures a supplied number.",
        profiles={ProfileName.VIRTUAL: ProfileSpec(ProfileName.VIRTUAL, implementation,
                                                   CostBounds(max_duration_s, 0))},
        parameters=(
            ParameterSpec("mode", ParameterType.ENUM, SelfTestMode.MEASURE.value,
                          choices=tuple(mode.value for mode in SelfTestMode),
                          description="Which path of the fixture runner to exercise."),
            ParameterSpec("value", ParameterType.INT, 0, minimum=0, maximum=1000,
                          description="Number reported as selftest.value; 0 passes the blocking assertion."),
            ParameterSpec("sleep_ms", ParameterType.INT, 0, minimum=0, maximum=600000,
                          description="How long the sleeping modes wait."),
        ),
        metrics=(
            MetricSpec("selftest.value", MetricUnit.COUNT, MetricDirection.LOWER_BETTER,
                       description="The number the fixture runner was asked to report."),
            MetricSpec("selftest.elapsed_ms", MetricUnit.MS, MetricDirection.LOWER_BETTER,
                       description="Wall time the fixture runner spent."),
        ),
        assertions=(
            AssertionSpec("value_is_zero", "selftest.value", Comparator.EQ, 0, True,
                          description="The reported number must be zero."),
            AssertionSpec("quick_enough", "selftest.elapsed_ms", Comparator.LE, 600000, False,
                          description="Informational: the fixture runner is not slow."),
        ),
        score=ScoreContract(ScoreMethod.NONE),
    )


def selftest_manifest(*, max_duration_s: float = 60.0, override_allowlist: tuple[ParameterSpec, ...] = (),
                      implementation: str = SELFTEST_IMPLEMENTATION) -> DiagnosticManifest:
    """The fixture manifest. `override_allowlist` lets a test exercise run-local setting overrides."""
    return DiagnosticManifest(selftest_spec(max_duration_s=max_duration_s, implementation=implementation),
                              override_allowlist)


def write_selftest_catalog(root: Path | str, *, max_duration_s: float = 60.0,
                           override_allowlist: tuple[ParameterSpec, ...] = (),
                           implementation: str = SELFTEST_IMPLEMENTATION) -> Path:
    """Write a one-diagnostic catalog (manifest + lock) under `root`, ready for `load_catalog`."""
    manifest = selftest_manifest(max_duration_s=max_duration_s, override_allowlist=override_allowlist,
                                 implementation=implementation)
    base = Path(root)
    path = base / manifest.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_manifest(manifest), encoding="utf-8")
    (base / "catalog.lock.json").write_text(CatalogLock((lock_entry_for(manifest),)).render(), encoding="utf-8")
    return base


def selftest_parameters(mode: SelfTestMode | str = SelfTestMode.MEASURE, **changes: Any) -> dict[str, Any]:
    """Supplied parameters for one fixture run (`value`, `sleep_ms` default to the declaration)."""
    return {"mode": SelfTestMode(mode).value, **changes}
