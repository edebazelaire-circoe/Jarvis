"""The seam between the Test Lab worker and a diagnostic implementation.

Binding contract: `docs/testlab.md` ("Supervisor and workers"). A registered
implementation name (`jarvis.testlab.implementations`) resolves to a factory
that builds a `DiagnosticRunner`; the worker gives it a `RunContext` and expects
a `RunOutcome`. Slice 05 ships the seam and one test fixture runner
(`jarvis.testlab.selftest`); Slices 06, 08 and 09 ship the real runners.

A runner measures. It never decides a verdict, never writes the run record and
never touches the live Jarvis runtime: its roots are the per-run scratch
directories in the context, and its only durable output is what it commits
through `put_artifact` plus the metrics it returns. The context hands it
`RunArtifacts`, an artifact-only facade scoped to its own run, not the store.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from jarvis.testlab.diagnostics import DiagnosticSpec, MetricValue
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runs import ArtifactKind, ArtifactRef
from jarvis.testlab.scenarios import Scenario
from jarvis.testlab.store import TestRunStore
from jarvis.testlab.validation import TestLabError, fail


class RunArtifacts:
    """The only store access a runner gets: the artifacts of ITS OWN run.

    A runner used to receive the whole `TestRunStore`, which let it conclude its
    own run (a forged `passed` verdict the supervisor then found already terminal)
    and delete other runs. The facade removes both: no `update_run`, no
    `delete_run`, no other run id. The record stays the supervisor's alone.

    **Invariant: no attribute of this object is a store.** The four operations are
    bound at construction and nothing else is kept, so no chain of attribute
    accesses from a `RunContext` reaches `update_run` or `delete_run`; `__slots__`
    keeps it that way. A determined caller can still reach the store through
    `__self__` of a bound method, through `gc`, or by opening the store directory
    by absolute path: that is the documented threat model (docs/testlab.md,
    "Threat model"), and the supervisor's out-of-band conclusion check is its
    backstop. What this class guarantees is that nobody gets there by accident.
    """

    __slots__ = ("_run_id", "_put", "_read", "_open", "_list")

    def __init__(self, store: TestRunStore, run_id: str) -> None:
        self._run_id = run_id
        self._put = store.put_artifact
        self._read = store.read_artifact
        self._open = store.open_artifact
        self._list = store.list_artifacts

    @property
    def run_id(self) -> str:
        return self._run_id

    def put(self, path: str, *, kind: ArtifactKind, media_type: str,
            data: bytes | Iterable[bytes] | BinaryIO) -> ArtifactRef:
        """Stream evidence bytes to `path` inside this run's directory."""
        return self._put(self._run_id, path, kind=kind, media_type=media_type, data=data)

    def read(self, path: str, *, verify: bool = True) -> bytes:
        return self._read(self._run_id, path, verify=verify)

    def open(self, path: str) -> BinaryIO:
        return self._open(self._run_id, path)

    def list(self) -> tuple[ArtifactRef, ...]:
        """The references committed in this run's record."""
        return self._list(self._run_id)


class RunCancelled(TestLabError):
    """Raised inside a runner when the supervisor asked it to stop.

    Cooperative stop: the worker turns it into a `cancelled` result. A runner
    that swallows it is killed instead (the supervisor's forced kill), which is
    slower and loses the partial evidence, so runners should let it propagate.
    """

    def __init__(self, detail: str = "the supervisor asked this run to stop") -> None:
        super().__init__("testlab_run_cancelled", detail)


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """What a runner measured. The verdict is derived from `metrics` by the supervisor."""

    metrics: Mapping[str, MetricValue] = field(default_factory=dict)
    #: 0..100 synthesis when the runner computes one; Slice 07 owns the score contract.
    score: float | None = None
    #: Conversation Events join values (`TRACE_JOIN_FIELDS` names -> opaque ids).
    join_ids: Mapping[str, str] = field(default_factory=dict)
    #: Extra references committed outside `RunContext.put_artifact` (rare).
    artifacts: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        for name in ("metrics", "join_ids"):
            if not isinstance(getattr(self, name), Mapping):
                raise fail(f"outcome.{name} must be a mapping")
        if not isinstance(self.artifacts, tuple):
            raise fail("outcome.artifacts must be a tuple of ArtifactRef")


@dataclass(slots=True)
class RunContext:
    """Everything a runner may use, and the only places it may write.

    `runtime_dir` and `data_root` are inside the run scratch: a runner that
    resolves `V2Settings` from the environment gets these, never the live
    `runtime/` and `data/` of the workstation.
    """

    run_id: str
    diagnostic: DiagnosticSpec
    profile: ProfileName
    #: Effective parameters (declared defaults merged with the supplied values).
    parameters: Mapping[str, Any]
    #: Run-local setting overrides, already applied to the scratch settings copy.
    overrides: Mapping[str, Any]
    scenario: Scenario | None
    runtime_dir: Path
    data_root: Path
    #: Artifact-only access to this run (never the record, never another run).
    artifacts: RunArtifacts
    #: Cooperative stop: set by the worker when the supervisor asks, or on the run deadline.
    cancelled: asyncio.Event
    #: `asyncio` loop time at which the run must be over.
    deadline: float
    #: One bounded progress line, written to the worker log and visible in the run artifacts.
    log: Callable[[str], None]
    #: References committed through `put_artifact`, in order.
    committed: list[ArtifactRef] = field(default_factory=list)

    @property
    def remaining_s(self) -> float:
        """Seconds left before the run deadline (0 when it has passed)."""
        return max(0.0, self.deadline - asyncio.get_running_loop().time())

    def check_cancelled(self) -> None:
        """Raise `RunCancelled` when a stop was requested. Call it between steps."""
        if self.cancelled.is_set():
            raise RunCancelled()

    async def sleep(self, seconds: float) -> None:
        """Sleep, returning early and raising `RunCancelled` as soon as a stop is requested."""
        self.check_cancelled()
        try:
            await asyncio.wait_for(self.cancelled.wait(), timeout=max(0.0, seconds))
        except asyncio.TimeoutError:
            return
        raise RunCancelled()

    def put_artifact(self, path: str, *, kind: ArtifactKind, media_type: str,
                     data: bytes | Iterable[bytes] | BinaryIO) -> ArtifactRef:
        """Commit evidence bytes to the run directory and remember the reference."""
        ref = self.artifacts.put(path, kind=kind, media_type=media_type, data=data)
        self.committed.append(ref)
        return ref


class DiagnosticRunner(Protocol):
    """What a registered implementation factory produces."""

    async def run(self, context: RunContext) -> RunOutcome:
        """Execute one run and return its measurements. May raise `RunCancelled`."""
        ...
