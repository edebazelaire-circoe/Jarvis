"""Test Lab run store port: TestRun records and their artifacts.

Binding contract: `docs/testlab.md` ("Storage"). Pure: this module declares
the store interface, its value types, its errors and the update rule every
adapter enforces (`check_run_update`); it performs no I/O. The local adapter is
`jarvis.testlab.filesystem_store.FilesystemTestRunStore`.

Why the port lives here and not in `jarvis/ports/v2.py`: the Test Lab is a
self-contained subsystem whose callers (supervisor, worker, CLI, Control Center
routes) are all Test Lab code, and `ports/v2.py` is the Core composition
surface edited by parallel voice work. The shape follows `ConversationEventStore`
(Protocol + frozen value types + typed errors with a stable code).

Why synchronous: the store is local files guarded by an OS file lock, used by
worker subprocesses and the CLI. Async callers (Control Center) wrap calls in
`asyncio.to_thread`; offloading changes nothing in the locking semantics.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import BinaryIO, Protocol

from jarvis.testlab.bundle import DiagnosticBundle
from jarvis.testlab.identity import (
    check_bundle_id,
    check_diagnostic_id,
    check_diagnostic_version,
    check_run_id,
    check_sweep_id,
    id_timestamp,
)
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runs import (
    TERMINAL_STATUSES,
    TRANSITION_ILLEGAL,
    ArtifactKind,
    ArtifactRef,
    RunStatus,
    RunTransitionError,
    TestRun,
    check_transition,
)
from jarvis.testlab.sweeps import SweepRecord
from jarvis.testlab.validation import TestLabError, check_enum, check_number, check_time, fail

# Stable store error codes (docs/testlab.md, "Storage").
STORE_NOT_FOUND = "testlab_store_not_found"
STORE_RUN_EXISTS = "testlab_store_run_exists"
STORE_CONFLICT = "testlab_store_conflict"
STORE_BUSY = "testlab_store_busy"
STORE_CORRUPT = "testlab_store_corrupt"
STORE_IO = "testlab_store_io"
STORE_IMMUTABLE_FIELD = "testlab_store_immutable_field"
STORE_PATH_UNSAFE = "testlab_store_path_unsafe"
STORE_ARTIFACT_TOO_LARGE = "testlab_store_artifact_too_large"
STORE_ARTIFACT_REFUSED = "testlab_store_artifact_refused"
STORE_ARTIFACT_MISMATCH = "testlab_store_artifact_mismatch"
STORE_ENVIRONMENT_REFUSED = "testlab_store_environment_refused"
STORE_DELETION_PENDING = "testlab_store_deletion_pending"

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 500

_MIB = 1024 * 1024


class TestLabStoreError(TestLabError):
    """A store operation was refused or failed. `code` is stable; `detail` names the run and the rule."""


class RunNotFoundError(TestLabStoreError):
    """No run directory exists for this run id."""


class RunConflictError(TestLabStoreError):
    """Compare-and-swap lost: the stored record is not the one the caller based its update on."""


class RunRecordCorruptError(TestLabStoreError):
    """The stored record cannot be read or decoded. Never silently skipped."""


# ------------------------------------------------------------------ query

@dataclass(frozen=True, slots=True)
class RunQuery:
    """Filters for `list_runs`. Every filter is optional; all given filters must match.

    Time range is on `created_at` (the run id time), half-open
    `[created_from, created_until)`. Order is by run id, which is creation time
    then nonce: stable and total. `after_run_id` continues a previous page.
    """

    diagnostic_id: str | None = None
    diagnostic_version: int | None = None
    profile: ProfileName | None = None
    statuses: frozenset[RunStatus] = frozenset()
    sweep_id: str | None = None
    bundle_id: str | None = None
    created_from: datetime | None = None
    created_until: datetime | None = None
    limit: int = DEFAULT_PAGE_LIMIT
    newest_first: bool = True
    after_run_id: str | None = None

    def __post_init__(self) -> None:
        if self.diagnostic_id is not None:
            check_diagnostic_id(self.diagnostic_id)
        if self.diagnostic_version is not None:
            check_diagnostic_version(self.diagnostic_version)
        if self.profile is not None:
            check_enum(ProfileName, self.profile, "profile")
        if not isinstance(self.statuses, frozenset):
            raise fail("statuses must be a frozenset of RunStatus")
        for status in self.statuses:
            check_enum(RunStatus, status, "statuses")
        check_sweep_id(self.sweep_id, optional=True)
        check_bundle_id(self.bundle_id, optional=True)
        check_time(self.created_from, "created_from", optional=True)
        check_time(self.created_until, "created_until", optional=True)
        if self.created_from is not None and self.created_until is not None and self.created_until <= self.created_from:
            raise fail("created_until must be after created_from")
        check_number(self.limit, "limit", minimum=1, maximum=MAX_PAGE_LIMIT, integer=True)
        if type(self.newest_first) is not bool:
            raise fail("newest_first must be a boolean")
        check_run_id(self.after_run_id, "after_run_id", optional=True)

    def id_in_range(self, run_id: str) -> bool:
        """Time and cursor filters, decided from the run id alone (no record read)."""
        stamp = run_id.split("-")[1]
        if self.created_from is not None and stamp < id_timestamp(self.created_from):
            return False
        if self.created_until is not None and stamp >= id_timestamp(self.created_until):
            return False
        if self.after_run_id is not None:
            return run_id < self.after_run_id if self.newest_first else run_id > self.after_run_id
        return True

    def matches(self, run: TestRun) -> bool:
        """Record filters (the id filters are checked by `id_in_range`)."""
        return ((self.diagnostic_id is None or run.diagnostic_id == self.diagnostic_id)
                and (self.diagnostic_version is None or run.diagnostic_version == self.diagnostic_version)
                and (self.profile is None or run.profile is self.profile)
                and (not self.statuses or run.status in self.statuses)
                and (self.sweep_id is None or run.sweep_id == self.sweep_id)
                and (self.bundle_id is None or run.bundle_id == self.bundle_id))


@dataclass(frozen=True, slots=True)
class CorruptRunEntry:
    """A stored entry that is not a readable run (or bundle): reported distinctly, never skipped in silence."""

    #: Directory name (a run or bundle id when it has that shape).
    entry: str
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class RunPage:
    runs: tuple[TestRun, ...]
    #: Corrupt entries met while scanning this page (they never count toward `limit`).
    corrupt: tuple[CorruptRunEntry, ...] = ()
    #: Pass as `after_run_id` for the next page; None when no further run matches.
    next_cursor: str | None = None


# ------------------------------------------------------------------ usage

@dataclass(frozen=True, slots=True)
class RunUsage:
    """Disk usage of one readable run, input of the retention planner."""

    run_id: str
    created_at: datetime
    status: RunStatus
    #: Every byte under the run directory (record, artifacts, orphan and temporary files).
    total_bytes: int
    #: Referenced artifact bytes per kind (from the record).
    bytes_by_kind: Mapping[ArtifactKind, int] = field(default_factory=dict)
    #: When the run became terminal (retention ages terminal runs from here).
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bytes_by_kind", MappingProxyType(dict(self.bytes_by_kind)))


@dataclass(frozen=True, slots=True)
class StorageUsage:
    runs: tuple[RunUsage, ...]
    corrupt: tuple[CorruptRunEntry, ...] = ()


# -------------------------------------------------------- artifact limits

#: Per-artifact byte caps enforced while streaming (docs/testlab.md, "Storage").
DEFAULT_ARTIFACT_MAX_BYTES: Mapping[ArtifactKind, int] = MappingProxyType({
    ArtifactKind.CONFIG_SNAPSHOT: 1 * _MIB,
    ArtifactKind.SCENARIO: 1 * _MIB,
    ArtifactKind.METRICS: 4 * _MIB,
    ArtifactKind.REPORT: 16 * _MIB,
    ArtifactKind.EVENT_LOG: 64 * _MIB,
    ArtifactKind.TRACE_EXCERPT: 64 * _MIB,
    ArtifactKind.WORKER_LOG: 64 * _MIB,
    #: About 11 minutes of 24 kHz mono PCM16; refused unless `allow_audio`.
    ArtifactKind.AUDIO_CLIP: 32 * _MIB,
})


@dataclass(frozen=True, slots=True)
class ArtifactWriteLimits:
    """What the store accepts to write. Audio is opt-in (off by default) and bounded like every kind."""

    max_bytes_by_kind: Mapping[ArtifactKind, int] = DEFAULT_ARTIFACT_MAX_BYTES
    allow_audio: bool = False

    def check_ref(self, ref: ArtifactRef) -> None:
        """A reference must be writable under these limits: audio opt-in, size within the cap of its kind."""
        if ref.kind is ArtifactKind.AUDIO_CLIP and not self.allow_audio:
            raise TestLabStoreError(STORE_ARTIFACT_REFUSED, "audio artifacts are opt-in and this store does not allow them")
        cap = self.max_bytes_by_kind[ref.kind]
        if ref.size_bytes > cap:
            raise TestLabStoreError(STORE_ARTIFACT_TOO_LARGE, f"{ref.kind.value} artifact exceeds {cap} bytes")

    def __post_init__(self) -> None:
        if not isinstance(self.max_bytes_by_kind, Mapping) or set(self.max_bytes_by_kind) != set(ArtifactKind):
            raise fail("max_bytes_by_kind must give a cap for every artifact kind")
        for kind, cap in self.max_bytes_by_kind.items():
            check_number(cap, f"max_bytes_by_kind.{kind}", minimum=1, maximum=2**40, integer=True)
        if type(self.allow_audio) is not bool:
            raise fail("allow_audio must be a boolean")
        object.__setattr__(self, "max_bytes_by_kind", MappingProxyType(dict(self.max_bytes_by_kind)))


# ---------------------------------------------------------- environment

#: The closed set of environment fact names a run may record. The single source
#: for `jarvis.testlab.capture.ENVIRONMENT_FACTS`; the store refuses any other
#: name so the no-identifying-facts rule does not rest on runner discipline.
#: Adding a probe (Slice 05 and later) means extending this set, in review.
ENVIRONMENT_FACT_NAMES = frozenset({
    "os", "os_release", "os_version", "machine", "python_implementation", "python_version", "host.cpu_count",
    "host.memory_gib_bucket",
})


def check_run_environment(run: TestRun, *, baseline: TestRun | None = None) -> None:
    """`run.environment` names must belong to `ENVIRONMENT_FACT_NAMES` (`testlab_store_environment_refused`).

    With `baseline` (an update), only names absent from the stored record are
    checked: a legacy or foreign record can still be cancelled, errored and
    deleted, but no update can add a name outside the set.
    """
    known = set() if baseline is None else set(baseline.environment)
    unknown = sorted(set(run.environment) - ENVIRONMENT_FACT_NAMES - known)
    if unknown:
        raise TestLabStoreError(STORE_ENVIRONMENT_REFUSED,
                                f"run {run.run_id}: environment holds {len(unknown)} name(s) outside the captured "
                                "fact set")


# ------------------------------------------------------------ update rule

#: Fields fixed when the run is queued. Changing them would make the record lie about what executed.
IMMUTABLE_RUN_FIELDS = (
    "run_id", "diagnostic_id", "diagnostic_version", "profile", "created_at", "code", "config_fingerprint",
    "diagnostic_fingerprint", "parameters", "overrides", "bundle_id", "sweep_id", "parent_run_id", "scenario_id",
    "scenario_fingerprint",
)


def check_run_update(stored: TestRun, updated: TestRun) -> None:
    """The update rule every store enforces, whatever built `updated`.

    `dataclasses.replace` can construct a valid record with any status, so the
    store (not the caller) checks: a terminal record is immutable (only
    retention deletes it); a status change must be allowed by `can_transition`;
    identity fields never change; `started_at` never changes once set; artifact
    references are only added, never removed or rewritten; environment names
    added by the update stay within `ENVIRONMENT_FACT_NAMES`.
    """
    if not isinstance(stored, TestRun) or not isinstance(updated, TestRun):
        raise fail("check_run_update takes two TestRun records")
    if updated.run_id != stored.run_id:
        raise TestLabStoreError(STORE_IMMUTABLE_FIELD, "run_id cannot change")
    if stored.status in TERMINAL_STATUSES:
        raise RunTransitionError(TRANSITION_ILLEGAL,
                                 f"run {stored.run_id} is {stored.status.value}: a terminal run is immutable")
    if updated.status is not stored.status:
        check_transition(stored.status, updated.status)
    check_run_environment(updated, baseline=stored)
    before, after = stored.to_dict(), updated.to_dict()
    for name in IMMUTABLE_RUN_FIELDS:
        if before[name] != after[name]:
            raise TestLabStoreError(STORE_IMMUTABLE_FIELD, f"run {stored.run_id}: {name} cannot change")
    if stored.started_at is not None and updated.started_at != stored.started_at:
        raise TestLabStoreError(STORE_IMMUTABLE_FIELD, f"run {stored.run_id}: started_at cannot change once set")
    kept = {ref.path: ref for ref in updated.artifacts}
    for ref in stored.artifacts:
        if kept.get(ref.path) != ref:
            raise TestLabStoreError(STORE_IMMUTABLE_FIELD,
                                    f"run {stored.run_id}: artifact references are only added, never removed or changed")


# ------------------------------------------------------------------- port

class TestRunStore(Protocol):
    """Durable TestRun records and artifacts (docs/testlab.md, "Storage").

    Every method raises `TestLabStoreError` (or a subclass) with a stable code;
    `OSError` never escapes. Records are decoded through the strict
    `TestRun.from_dict` codec on every read.
    """

    __test__ = False  # not a pytest test class, despite the name

    def create_run(self, run: TestRun) -> TestRun:
        """Store a new `queued` run without artifacts. `testlab_store_run_exists` if the id is taken."""
        ...

    def get_run(self, run_id: str) -> TestRun:
        """`RunNotFoundError` or `RunRecordCorruptError` instead of a record."""
        ...

    def update_run(self, updated: TestRun, *, expected: TestRun) -> TestRun:
        """Compare-and-swap under the run's writer lock.

        Fails with `RunConflictError` when the stored record differs from
        `expected` (status first), then applies `check_run_update`. New
        artifact references must match stored bytes (size and sha256).
        """
        ...

    def list_runs(self, query: RunQuery = RunQuery()) -> RunPage: ...

    def delete_run(self, run_id: str) -> None:
        """Retention deletion of a terminal run (the only way a terminal record changes)."""
        ...

    def put_artifact(self, run_id: str, path: str, *, kind: ArtifactKind, media_type: str,
                     data: bytes | Iterable[bytes] | BinaryIO) -> ArtifactRef:
        """Stream bytes to `path` inside a non-terminal run; returns the reference to add to the record.

        The record is not changed: the writer adds the reference in its next
        `update_run` (or `complete_run(artifacts=...)`).
        """
        ...

    def read_artifact(self, run_id: str, path: str, *, verify: bool = True) -> bytes:
        """Bytes of an artifact referenced by the record; `verify` re-checks size and sha256."""
        ...

    def open_artifact(self, run_id: str, path: str) -> BinaryIO:
        """Binary handle on a referenced artifact (caller closes it; an open handle delays deletion)."""
        ...

    def list_artifacts(self, run_id: str) -> tuple[ArtifactRef, ...]:
        """The artifact references committed in the record."""
        ...

    def storage_usage(self) -> StorageUsage: ...


# ------------------------------------------------------------ bundle port

class BundleNotFoundError(TestLabStoreError):
    """No bundle directory exists for this bundle id."""


class BundleConflictError(TestLabStoreError):
    """A bundle id is already stored with a different content fingerprint."""


class BundleRecordCorruptError(TestLabStoreError):
    """The stored bundle cannot be read or decoded. Never silently skipped."""


class BundlePutStatus(StrEnum):
    #: New bundle written.
    STORED = "stored"
    #: Same id and same content fingerprint already stored; nothing written (the first capture is kept).
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class BundlePutResult:
    bundle_id: str
    status: BundlePutStatus
    content_fingerprint: str


@dataclass(frozen=True, slots=True)
class BundleQuery:
    """Filters for `list_bundles`. Order is by bundle id (session start time, then fingerprint prefix)."""

    limit: int = DEFAULT_PAGE_LIMIT
    newest_first: bool = True
    after_bundle_id: str | None = None
    conversation_id: str | None = None

    def __post_init__(self) -> None:
        check_number(self.limit, "limit", minimum=1, maximum=MAX_PAGE_LIMIT, integer=True)
        if type(self.newest_first) is not bool:
            raise fail("newest_first must be a boolean")
        check_bundle_id(self.after_bundle_id, "after_bundle_id", optional=True)
        if self.conversation_id is not None and (not isinstance(self.conversation_id, str) or not self.conversation_id):
            raise fail("conversation_id must be a nonempty identifier")


@dataclass(frozen=True, slots=True)
class BundleSummary:
    bundle_id: str
    captured_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    conversation_ids: tuple[str, ...]
    session_ids: tuple[str, ...]
    finding_count: int
    content_fingerprint: str

    @classmethod
    def of(cls, bundle: DiagnosticBundle) -> BundleSummary:
        return cls(bundle.bundle_id, bundle.captured_at, bundle.started_at, bundle.ended_at,
                   tuple(bundle.conversation_ids), tuple(bundle.session_ids), len(bundle.findings),
                   bundle.content_fingerprint)


@dataclass(frozen=True, slots=True)
class BundlePage:
    bundles: tuple[BundleSummary, ...]
    #: Unreadable bundle directories and stray entries met while scanning (never counted toward `limit`).
    corrupt: tuple[CorruptRunEntry, ...] = ()
    next_cursor: str | None = None


class SweepNotFoundError(TestLabStoreError):
    """No sweep directory exists for this sweep id."""


class SweepRecordCorruptError(TestLabStoreError):
    """The stored sweep record cannot be read or decoded. Never silently skipped."""


@dataclass(frozen=True, slots=True)
class SweepQuery:
    """Filters for `list_sweeps`. Order is by sweep id, which is creation time then nonce."""

    limit: int = DEFAULT_PAGE_LIMIT
    newest_first: bool = True
    after_sweep_id: str | None = None

    def __post_init__(self) -> None:
        check_number(self.limit, "limit", minimum=1, maximum=MAX_PAGE_LIMIT, integer=True)
        if type(self.newest_first) is not bool:
            raise fail("newest_first must be a boolean")
        check_sweep_id(self.after_sweep_id, "after_sweep_id", optional=True)


@dataclass(frozen=True, slots=True)
class SweepPage:
    sweeps: tuple[SweepRecord, ...]
    #: Unreadable sweep directories and stray entries met while scanning.
    corrupt: tuple[CorruptRunEntry, ...] = ()
    next_cursor: str | None = None


class SweepStore(Protocol):
    """Durable sweep records and their summary artifact (docs/testlab.md, "Sweeps").

    A sweep record is REWRITTEN as the sweep progresses (unlike a `TestRun`, whose
    terminal record is immutable): it is the orchestrator's own progress log, while
    the evidence of each point lives in the `TestRun` records the sweep produced and
    those obey the run store's rules. A terminal sweep record is never rewritten.
    """

    def put_sweep(self, record: SweepRecord) -> SweepRecord:
        """Create or update a sweep record. Refuses to rewrite a terminal one."""
        ...

    def get_sweep(self, sweep_id: str) -> SweepRecord:
        """`SweepNotFoundError` or `SweepRecordCorruptError` instead of a record."""
        ...

    def list_sweeps(self, query: SweepQuery = SweepQuery()) -> SweepPage: ...

    def put_sweep_summary(self, sweep_id: str, document: Mapping[str, object]) -> None:
        """Store the readable summary artifact of a finished sweep (canonical JSON).

        Write-once, like a terminal record: a second write is `testlab_store_conflict`.
        """
        ...

    def get_sweep_summary(self, sweep_id: str) -> Mapping[str, object]:
        """The stored summary document; `SweepNotFoundError` when the sweep has none."""
        ...


class BundleStore(Protocol):
    """Durable DiagnosticBundles (docs/testlab.md, "DiagnosticBundle", "Storage").

    Every method raises `TestLabStoreError` (or a subclass) with a stable code;
    `OSError` never escapes. Bundles are decoded through the strict
    `DiagnosticBundle` codec on every read. `TestRun.bundle_id` references them.
    """

    def put_bundle(self, bundle: DiagnosticBundle) -> BundlePutResult:
        """Store a bundle once. Same id and fingerprint: `duplicate`; same id, other fingerprint: `BundleConflictError`."""
        ...

    def get_bundle(self, bundle_id: str) -> DiagnosticBundle:
        """`BundleNotFoundError` or `BundleRecordCorruptError` instead of a bundle."""
        ...

    def list_bundles(self, query: BundleQuery = BundleQuery()) -> BundlePage: ...
