"""Filesystem adapter of the Test Lab run store.

Binding contract: `docs/testlab.md` ("Storage"). The root directory is
injected; resolving it from `V2Settings.runtime_root` / `JARVIS_RUNTIME_DIR`
(`<runtime>/testlab/`) belongs to the composition layer. TestRun storage never
touches `data/state/jarvis.sqlite3` (READINESS B4.3).

Layout::

    <root>/runs/<run_id>/record.json      canonical JSON of TestRun.to_dict()
    <root>/runs/<run_id>/.artifacts.json  write-time manifest: kind, media type, sha256, size per path
    <root>/runs/<run_id>/<artifact path>  artifact bytes (paths from ArtifactRef)
    <root>/runs/<run_id>/.record-*.tmp    write in progress (or crash leftover)
    <root>/runs/<run_id>/.artifact-*.tmp  stream in progress (or crash leftover)
    <root>/runs/.staging-<run_id>-*       run being created
    <root>/runs/.deleting-<16 hex>        run being deleted (never longer than a run id)
    <root>/locks/<run_id>.lock            single-writer OS lock of the run

Hidden names can never be artifact paths (the `ArtifactRef` path rule refuses
hidden segments), so protocol files never collide with evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
import errno
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import threading
import time
from typing import Any, BinaryIO

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.ports.v2 import DiagnosticSink
from jarvis.testlab.identity import check_run_id
from jarvis.testlab.runs import (
    TERMINAL_STATUSES,
    ArtifactKind,
    ArtifactRef,
    RunStatus,
    TestRun,
    check_artifact_path,
)
from jarvis.testlab.store import (
    STORE_ARTIFACT_MISMATCH,
    STORE_ARTIFACT_REFUSED,
    STORE_ARTIFACT_TOO_LARGE,
    STORE_BUSY,
    STORE_CONFLICT,
    STORE_CORRUPT,
    STORE_DELETION_PENDING,
    STORE_IO,
    STORE_NOT_FOUND,
    STORE_PATH_UNSAFE,
    STORE_RUN_EXISTS,
    ArtifactWriteLimits,
    CorruptRunEntry,
    RunConflictError,
    RunNotFoundError,
    RunPage,
    RunQuery,
    RunRecordCorruptError,
    RunUsage,
    StorageUsage,
    TestLabStoreError,
    check_run_environment,
    check_run_update,
)
from jarvis.testlab.validation import (
    LIMIT_EXCEEDED,
    check_document_header,
    exact_fields,
    MAX_DOCUMENT_BYTES,
    TestLabError,
    canonical_json,
    decode_json_document,
    name_for_message,
)

if os.name == "nt":
    import msvcrt
else:
    import fcntl

RECORD_NAME = "record.json"
#: Hidden per-run manifest of what `put_artifact` wrote (the authority for kind and media type).
MANIFEST_NAME = ".artifacts.json"
MANIFEST_SCHEMA = "jarvis.testlab.artifact_manifest"
MANIFEST_SCHEMA_VERSION = 1
MAX_MANIFEST_ENTRIES = 1024
MAX_MANIFEST_BYTES = 1024 * 1024
RUNS_DIR = "runs"
LOCKS_DIR = "locks"
STAGING_PREFIX = ".staging-"
DELETING_PREFIX = ".deleting-"
RECORD_TMP_PREFIX = ".record-"
ARTIFACT_TMP_PREFIX = ".artifact-"
TMP_SUFFIX = ".tmp"

#: Lock wait before `testlab_store_busy`. The lock only covers read-compare-write
#: (milliseconds), never a stream, so a long wait means a stuck writer.
DEFAULT_LOCK_TIMEOUT_S = 5.0
LOCK_POLL_S = 0.01
#: Protocol temporaries older than this are crash leftovers (an active stream
#: refreshes its temporary's mtime on every chunk).
DEFAULT_STALE_TEMPORARY_S = 3600.0
STREAM_CHUNK_BYTES = 256 * 1024
#: Temp names have a fixed length: `.record-` / `.artifact-` + 16 hex + `.tmp`.
_TMP_TOKEN_HEX = 16
#: Windows `MAX_PATH` is 260 including the terminating NUL; `CreateDirectoryW`
#: also keeps 12 characters for an 8.3 file name inside the new directory.
WINDOWS_MAX_PATH_CHARS = 259
_DIRECTORY_RESERVE_CHARS = 12

#: Device names Windows resolves in any directory, with any extension.
_WINDOWS_RESERVED = frozenset({"con", "prn", "aux", "nul", "conin$", "conout$",
                               *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))})


#: errno values meaning "another handle holds the lock" (msvcrt: EACCES/EDEADLOCK, flock: EWOULDBLOCK).
_LOCK_CONTENTION_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK})


def _store_error(code: str, detail: str, exc: BaseException | None = None) -> TestLabStoreError:
    kind = {STORE_NOT_FOUND: RunNotFoundError, STORE_CONFLICT: RunConflictError,
            STORE_CORRUPT: RunRecordCorruptError}.get(code, TestLabStoreError)
    if exc is not None:
        detail = f"{detail} ({type(exc).__name__})"
    return kind(code, detail)


def default_max_path_chars() -> int | None:
    """The path budget of this host: 259 on Windows unless `LongPathsEnabled` is 1, else unbounded (None)."""
    if os.name != "nt":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            enabled, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
    except OSError:
        return WINDOWS_MAX_PATH_CHARS  # intentional: no policy value means the legacy limit applies
    return None if enabled == 1 else WINDOWS_MAX_PATH_CHARS


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


class _RunLock:
    """Exclusive OS lock on `<root>/locks/<run_id>.lock` (msvcrt on Windows, flock elsewhere).

    The OS releases it when the holder dies, so a crashed writer never leaves a
    stale lock. Locks are per open handle: two threads of one process exclude
    each other as two processes do.
    """

    def __init__(self, path: Path, run_id: str, timeout_s: float) -> None:
        self._path = path
        self._run_id = run_id
        self._timeout_s = timeout_s
        self._fd: int | None = None

    def __enter__(self) -> _RunLock:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            raise _store_error(STORE_IO, f"run {self._run_id}: writer lock cannot be opened", exc) from exc
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                _lock_fd(fd)
            except OSError as exc:
                if exc.errno not in _LOCK_CONTENTION_ERRNOS:
                    os.close(fd)
                    raise _store_error(STORE_IO, f"run {self._run_id}: writer lock failed", exc) from exc
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise _store_error(STORE_BUSY, f"run {self._run_id}: another writer holds the run lock "
                                                   f"for more than {self._timeout_s:g} s") from None
                time.sleep(LOCK_POLL_S)
                continue
            self._fd = fd
            return self

    def __exit__(self, *_: object) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock_fd(fd)
        except OSError:
            # intentional: closing the handle below releases an OS file lock anyway, and
            # the protected write has already committed or raised its own error.
            pass
        finally:
            os.close(fd)


def _lock_fd(fd: int) -> None:
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_fd(fd: int) -> None:
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _chunks(data: bytes | Iterable[bytes] | BinaryIO) -> Iterator[bytes]:
    if isinstance(data, (bytes, bytearray, memoryview)):
        yield bytes(data)
        return
    read = getattr(data, "read", None)
    if callable(read):
        while True:
            chunk = read(STREAM_CHUNK_BYTES)
            if not chunk:
                return
            if not isinstance(chunk, (bytes, bytearray)):
                raise TestLabStoreError(STORE_ARTIFACT_REFUSED, "artifact stream must yield bytes")
            yield bytes(chunk)
    for chunk in data:  # type: ignore[union-attr]
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise TestLabStoreError(STORE_ARTIFACT_REFUSED, "artifact stream must yield bytes")
        yield bytes(chunk)


class FilesystemTestRunStore:
    """Durable `TestRunStore` on a local directory (one directory per run)."""

    __test__ = False  # not a pytest test class, despite the name

    def __init__(self, root: Path, *, limits: ArtifactWriteLimits = ArtifactWriteLimits(),
                 lock_timeout_s: float = DEFAULT_LOCK_TIMEOUT_S, diagnostics: DiagnosticSink | None = None,
                 max_path_chars: int | None | object = ...) -> None:
        if not isinstance(limits, ArtifactWriteLimits):
            raise TypeError("limits must be ArtifactWriteLimits")
        #: Longest absolute path the store may create (None: unbounded). Default: `default_max_path_chars()`.
        self.max_path_chars: int | None = default_max_path_chars() if max_path_chars is ... else max_path_chars  # type: ignore[assignment]
        self.root = Path(root)
        self.runs_dir = self.root / RUNS_DIR
        self.locks_dir = self.root / LOCKS_DIR
        self.limits = limits
        self.lock_timeout_s = lock_timeout_s
        self._diagnostics = diagnostics
        #: Emissions the diagnostic sink refused (a broken sink never fails a store operation).
        self.diagnostic_failures = 0
        self._counter_lock = threading.Lock()

    # ------------------------------------------------------------ plumbing

    def _diagnose(self, kind: str, message: str, *, level: str = "info", **data: Any) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            # A broken diagnostic sink cannot undo a committed write or turn a
            # read into a failure; the host inspects `diagnostic_failures`.
            with self._counter_lock:
                self.diagnostic_failures += 1

    def _run_dir(self, run_id: str) -> Path:
        try:
            check_run_id(run_id)
        except TestLabError as exc:
            raise TestLabStoreError(STORE_PATH_UNSAFE, exc.detail) from None
        return self.runs_dir / run_id

    def _check_path_budget(self, path: Path, run_id: str, *, directory: bool = False) -> None:
        """Refuse, before any write, a path the host cannot create (legacy Windows `MAX_PATH`)."""
        if self.max_path_chars is None:
            return
        budget = self.max_path_chars - (_DIRECTORY_RESERVE_CHARS if directory else 0)
        length = len(os.path.abspath(path))
        if length > budget:
            raise TestLabStoreError(STORE_PATH_UNSAFE, f"run {run_id}: path of {length} characters exceeds the "
                                                       f"{budget}-character path budget of this host")

    @staticmethod
    def _tmp_name(prefix: str) -> str:
        return f"{prefix}{secrets.token_hex(_TMP_TOKEN_HEX // 2)}{TMP_SUFFIX}"

    def _lock(self, run_id: str) -> _RunLock:
        return _RunLock(self.locks_dir / f"{run_id}.lock", run_id, self.lock_timeout_s)

    def _existing_run_dir(self, run_id: str) -> Path:
        run_dir = self._run_dir(run_id)
        try:
            if _is_link(run_dir):
                raise TestLabStoreError(STORE_PATH_UNSAFE, f"run {run_id}: run directory is a link")
            if not run_dir.is_dir():
                raise RunNotFoundError(STORE_NOT_FOUND, f"run {run_id} does not exist")
        except OSError as exc:
            raise _store_error(STORE_IO, f"run {run_id}: run directory cannot be inspected", exc) from exc
        return run_dir

    def _write_atomic(self, directory: Path, target_name: str, payload: bytes, run_id: str) -> None:
        """Temp file + flush + fsync + `replace_with_retry`: the target is old or new, never partial."""
        tmp = directory / self._tmp_name(RECORD_TMP_PREFIX)
        self._check_path_budget(tmp, run_id)
        try:
            with open(tmp, "xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            replace_with_retry(tmp, directory / target_name)
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                # intentional: the leftover is a hidden `.tmp` that readers ignore and
                # `remove_stale_temporaries` deletes; the write failure below is the error.
                pass
            raise _store_error(STORE_IO, f"run {run_id}: record write failed, previous record intact", exc) from exc
        # Directory fsync is not available on Windows (a directory cannot be opened
        # for writing); NTFS journals the rename itself, so it is not attempted.

    def _read_record(self, run_dir: Path, run_id: str) -> TestRun:
        record = run_dir / RECORD_NAME
        try:
            with open(record, "rb") as handle:
                raw = handle.read(MAX_DOCUMENT_BYTES + 1)
        except FileNotFoundError:
            raise RunRecordCorruptError(STORE_CORRUPT, f"run {run_id}: record.json is missing") from None
        except OSError as exc:
            raise _store_error(STORE_IO, f"run {run_id}: record cannot be read", exc) from exc
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise RunRecordCorruptError(STORE_CORRUPT, f"run {run_id}: record is not UTF-8 text") from None
        try:
            run = TestRun.from_dict(decode_json_document(text))
        except TestLabError as exc:
            raise RunRecordCorruptError(STORE_CORRUPT, f"run {run_id}: record does not decode ({exc.code})") from None
        if run.run_id != run_id:
            raise RunRecordCorruptError(STORE_CORRUPT, f"run {run_id}: record run_id differs from its directory")
        return run

    @staticmethod
    def _encode(run: TestRun) -> bytes:
        payload = canonical_json(run.to_dict()).encode("utf-8")
        if len(payload) > MAX_DOCUMENT_BYTES:
            raise TestLabStoreError(LIMIT_EXCEEDED, f"run {run.run_id}: record exceeds {MAX_DOCUMENT_BYTES} bytes")
        return payload

    # ------------------------------------------------------------- records

    def create_run(self, run: TestRun) -> TestRun:
        if not isinstance(run, TestRun):
            raise TypeError("create_run takes a TestRun")
        if run.status is not RunStatus.QUEUED or run.artifacts:
            raise TestLabStoreError(STORE_CONFLICT, f"run {run.run_id}: a new run is stored queued, without artifacts")
        check_run_environment(run)
        final = self._run_dir(run.run_id)
        payload = self._encode(run)
        staging = self.runs_dir / f"{STAGING_PREFIX}{run.run_id}-{secrets.token_hex(4)}"
        # The longest paths this run will need: its staging record temp file (longer than
        # any run-directory temp or manifest), its directories and its lock file.
        self._check_path_budget(staging, run.run_id, directory=True)
        self._check_path_budget(staging / self._tmp_name(RECORD_TMP_PREFIX), run.run_id)
        self._check_path_budget(final / self._tmp_name(ARTIFACT_TMP_PREFIX), run.run_id)
        self._check_path_budget(self.locks_dir / f"{run.run_id}.lock", run.run_id)
        try:
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            if final.exists() or _is_link(final):
                raise TestLabStoreError(STORE_RUN_EXISTS, f"run {run.run_id} already exists")
            staging.mkdir()
            self._write_atomic(staging, RECORD_NAME, payload, run.run_id)
            # A directory replace refuses an existing target on Windows and a non-empty
            # one on POSIX (a concurrent creator's directory always holds its record),
            # so the run directory appears complete, or not at all.
            replace_with_retry(staging, final)
        except (FileExistsError, IsADirectoryError, NotADirectoryError) as exc:
            shutil.rmtree(staging, ignore_errors=True)  # intentional: a hidden staging leftover is swept later
            raise _store_error(STORE_RUN_EXISTS, f"run {run.run_id} already exists", exc) from exc
        except TestLabStoreError:
            shutil.rmtree(staging, ignore_errors=True)  # intentional: a hidden staging leftover is swept later
            raise
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)  # intentional: a hidden staging leftover is swept later
            if final.exists():
                raise _store_error(STORE_RUN_EXISTS, f"run {run.run_id} already exists", exc) from exc
            raise _store_error(STORE_IO, f"run {run.run_id}: creation failed", exc) from exc
        self._diagnose("testlab_run_created", "Test Lab run stored", run_id=run.run_id,
                       diagnostic_id=run.diagnostic_id, profile=run.profile.value)
        return run

    def get_run(self, run_id: str) -> TestRun:
        run_dir = self._existing_run_dir(run_id)
        try:
            return self._read_record(run_dir, run_id)
        except RunRecordCorruptError as exc:
            self._diagnose("testlab_run_record_corrupt", "Test Lab run record unreadable", level="warning",
                           run_id=run_id, detail=exc.detail)
            raise

    def update_run(self, updated: TestRun, *, expected: TestRun) -> TestRun:
        if not isinstance(updated, TestRun) or not isinstance(expected, TestRun):
            raise TypeError("update_run takes TestRun records")
        run_id = expected.run_id
        self._existing_run_dir(run_id)  # not found before any lock file is created
        with self._lock(run_id):
            run_dir = self._existing_run_dir(run_id)
            stored = self._read_record(run_dir, run_id)
            if stored.status is not expected.status:
                raise RunConflictError(STORE_CONFLICT, f"run {run_id}: stored status is {stored.status.value}, "
                                                       f"expected {expected.status.value}")
            if stored.to_dict() != expected.to_dict():
                raise RunConflictError(STORE_CONFLICT, f"run {run_id}: stored record changed since it was read")
            check_run_update(stored, updated)
            if len({ref.path.casefold() for ref in updated.artifacts}) != len(updated.artifacts):
                raise TestLabStoreError(STORE_PATH_UNSAFE,
                                        f"run {run_id}: artifact paths differing only by case name one file")
            known = {ref.path for ref in stored.artifacts}
            new_refs = [ref for ref in updated.artifacts if ref.path not in known]
            manifest = self._read_manifest(run_dir, run_id) if new_refs else {}
            for ref in new_refs:
                self._check_new_ref(run_dir, run_id, ref, manifest)
            self._write_atomic(run_dir, RECORD_NAME, self._encode(updated), run_id)
        if updated.status is not stored.status:
            self._diagnose("testlab_run_status_changed", "Test Lab run status stored", run_id=run_id,
                           previous=stored.status.value, status=updated.status.value)
        return updated

    def list_runs(self, query: RunQuery = RunQuery()) -> RunPage:
        if not isinstance(query, RunQuery):
            raise TypeError("list_runs takes a RunQuery")
        runs: list[TestRun] = []
        corrupt: list[CorruptRunEntry] = []
        names, unrecognized = self._entries()
        corrupt.extend(unrecognized)
        more = False
        for run_id in sorted(names, reverse=query.newest_first):
            if not query.id_in_range(run_id):
                continue
            run = self._scan_record(run_id, corrupt)
            if run is None or not query.matches(run):
                continue
            if len(runs) == query.limit:
                more = True
                break
            runs.append(run)
        if corrupt:
            self._diagnose("testlab_run_listing_corrupt", "Test Lab listing met unreadable entries", level="warning",
                           count=len(corrupt), entries=[entry.entry for entry in corrupt[:16]])
        return RunPage(runs=tuple(runs), corrupt=tuple(corrupt), next_cursor=runs[-1].run_id if more else None)

    def _scan_record(self, run_id: str, corrupt: list[CorruptRunEntry]) -> TestRun | None:
        """Read one listed run; an unreadable one is appended to `corrupt`, a vanished one is skipped."""
        run_dir = self.runs_dir / run_id
        try:
            run = self._read_record(run_dir, run_id)
        except TestLabStoreError as exc:
            if not run_dir.is_dir():
                return None  # intentional: deleted by retention between listing and reading; not corrupt
            corrupt.append(CorruptRunEntry(run_id, exc.code, exc.detail))
            return None
        try:
            self._read_manifest(run_dir, run_id)
        except TestLabStoreError as exc:
            # The record stays readable and listed; the manifest defect is reported next
            # to it, because no new artifact can be put or committed until it is repaired.
            if run_dir.is_dir():
                corrupt.append(CorruptRunEntry(run_id, exc.code, exc.detail))
        return run

    def _entries(self) -> tuple[list[str], list[CorruptRunEntry]]:
        """Run directory names, and stray entries reported as corrupt. Protocol temporaries are not runs."""
        try:
            entries = list(os.scandir(self.runs_dir))
        except FileNotFoundError:
            return [], []  # intentional: no run was ever stored (first run creates the directory)
        except OSError as exc:
            raise _store_error(STORE_IO, "runs directory cannot be listed", exc) from exc
        names: list[str] = []
        stray: list[CorruptRunEntry] = []
        for entry in entries:
            if entry.name.startswith(DELETING_PREFIX):
                # Never invisible: a deletion in progress, or one that could not finish
                # (file held open); `remove_stale_temporaries` retries it on every pass.
                stray.append(CorruptRunEntry(name_for_message(entry.name), STORE_DELETION_PENDING,
                                             "run deletion not finished; the temporaries sweep retries it"))
                continue
            if entry.name.startswith(STAGING_PREFIX):
                continue
            try:
                check_run_id(entry.name)
            except TestLabError:
                stray.append(CorruptRunEntry(name_for_message(entry.name), STORE_CORRUPT,
                                             "entry is not a run directory (unrecognized name)"))
                continue
            if entry.is_symlink() or Path(entry.path).is_junction() or not entry.is_dir(follow_symlinks=False):
                stray.append(CorruptRunEntry(entry.name, STORE_CORRUPT, "entry is not a plain run directory"))
                continue
            names.append(entry.name)
        return names, stray

    def delete_run(self, run_id: str) -> None:
        self._existing_run_dir(run_id)  # not found before any lock file is created
        with self._lock(run_id):
            run_dir = self._existing_run_dir(run_id)
            stored = self._read_record(run_dir, run_id)
            if stored.status not in TERMINAL_STATUSES:
                raise RunConflictError(STORE_CONFLICT, f"run {run_id} is {stored.status.value}: "
                                                       "only a terminal run can be deleted")
            # `.deleting-` + 16 hex is 26 characters, shorter than the 45 of a run id: every
            # path inside keeps within the budget it was written under, so rmtree can reach it.
            hidden = self.runs_dir / f"{DELETING_PREFIX}{secrets.token_hex(8)}"
            try:
                replace_with_retry(run_dir, hidden)
            except OSError as exc:
                raise _store_error(STORE_BUSY, f"run {run_id}: run directory is held open, not deleted", exc) from exc
        try:
            shutil.rmtree(hidden)
        except OSError as exc:
            # Capture and continue: the run is already gone from every read (hidden
            # name); `remove_stale_temporaries` finishes the removal later.
            self._diagnose("testlab_run_delete_incomplete", "Test Lab run hidden but not fully removed",
                           level="warning", run_id=run_id, entry=hidden.name, error=type(exc).__name__)
        self._remove_lock_file(run_id)
        self._diagnose("testlab_run_deleted", "Test Lab run deleted by retention", run_id=run_id)

    def _remove_lock_file(self, run_id: str) -> None:
        try:
            (self.locks_dir / f"{run_id}.lock").unlink(missing_ok=True)
        except OSError:
            # intentional: another process still has the lock file open (Windows refuses
            # the unlink); the file is empty and `remove_stale_temporaries` retries.
            pass

    # ----------------------------------------------------------- artifacts

    def _artifact_target(self, run_dir: Path, run_id: str, path: str) -> Path:
        try:
            check_artifact_path(path)
        except TestLabError as exc:
            raise TestLabStoreError(STORE_PATH_UNSAFE, f"run {run_id}: {exc.detail}") from None
        segments = path.split("/")
        if len(segments) == 1 and segments[0].casefold() == RECORD_NAME:
            raise TestLabStoreError(STORE_PATH_UNSAFE, f"run {run_id}: artifact.path {RECORD_NAME} is reserved")
        if any(segment.split(".", 1)[0].casefold() in _WINDOWS_RESERVED for segment in segments):
            raise TestLabStoreError(STORE_PATH_UNSAFE, f"run {run_id}: artifact.path uses a reserved device name")
        target = run_dir
        try:
            for segment in segments:
                target = target / segment
                if _is_link(target):
                    raise TestLabStoreError(STORE_PATH_UNSAFE, f"run {run_id}: artifact.path crosses a link")
            if not target.resolve().is_relative_to(run_dir.resolve()):
                raise TestLabStoreError(STORE_PATH_UNSAFE, f"run {run_id}: artifact.path escapes the run directory")
        except OSError as exc:
            raise _store_error(STORE_IO, f"run {run_id}: artifact.path cannot be inspected", exc) from exc
        return target

    def _read_manifest(self, run_dir: Path, run_id: str) -> dict[str, ArtifactRef]:
        try:
            with open(run_dir / MANIFEST_NAME, "rb") as handle:
                raw = handle.read(MAX_MANIFEST_BYTES + 1)
        except FileNotFoundError:
            return {}  # intentional: no artifact was written to this run yet
        except OSError as exc:
            raise _store_error(STORE_IO, f"run {run_id}: artifact manifest cannot be read", exc) from exc
        try:
            payload = decode_json_document(raw.decode("utf-8"), max_bytes=MAX_MANIFEST_BYTES)
            data = exact_fields(payload, frozenset({"schema", "schema_version", "artifacts"}), "artifact manifest")
            check_document_header(data, MANIFEST_SCHEMA, MANIFEST_SCHEMA_VERSION, "artifact manifest")
            entries = data["artifacts"]
            if not isinstance(entries, dict) or len(entries) > MAX_MANIFEST_ENTRIES:
                raise TestLabError(STORE_CORRUPT, "artifact manifest entries are not a bounded object")
            manifest = {key: ArtifactRef.from_dict(value) for key, value in entries.items()}
            if any(key != ref.path for key, ref in manifest.items()):
                raise TestLabError(STORE_CORRUPT, "artifact manifest key differs from its path")
        except (UnicodeDecodeError, TestLabError) as exc:
            code = exc.code if isinstance(exc, TestLabError) else "utf8"
            raise RunRecordCorruptError(STORE_CORRUPT, f"run {run_id}: artifact manifest does not decode ({code})") from None
        return manifest

    def _write_manifest(self, run_dir: Path, run_id: str, manifest: dict[str, ArtifactRef]) -> None:
        document = {"schema": MANIFEST_SCHEMA, "schema_version": MANIFEST_SCHEMA_VERSION,
                    "artifacts": {path: ref.to_dict() for path, ref in sorted(manifest.items())}}
        self._write_atomic(run_dir, MANIFEST_NAME, canonical_json(document).encode("utf-8"), run_id)

    def _check_new_ref(self, run_dir: Path, run_id: str, ref: ArtifactRef, manifest: dict[str, ArtifactRef]) -> None:
        """A new reference must be what `put_artifact` wrote (kind, media type, sha256, size), under these limits.

        The manifest makes the write-time kind authoritative: bytes put as a
        `report` cannot be re-labelled `audio_clip` (audio opt-in) or
        `config_snapshot` (smaller cap). The limits are checked again because a
        store may be reopened with stricter limits than the one that wrote.
        """
        try:
            self.limits.check_ref(ref)
        except TestLabStoreError as exc:
            raise TestLabStoreError(exc.code, f"run {run_id}: {exc.detail}") from None
        if manifest.get(ref.path) != ref:
            raise TestLabStoreError(STORE_ARTIFACT_MISMATCH, f"run {run_id}: reference differs from what put_artifact "
                                                             "wrote (kind, media type, sha256 or size)")
        self._verify_artifact(run_dir, run_id, ref)

    def put_artifact(self, run_id: str, path: str, *, kind: ArtifactKind, media_type: str,
                     data: bytes | Iterable[bytes] | BinaryIO) -> ArtifactRef:
        if not isinstance(kind, ArtifactKind):
            raise TestLabStoreError(STORE_ARTIFACT_REFUSED, "artifact.kind must be an ArtifactKind")
        if kind is ArtifactKind.AUDIO_CLIP and not self.limits.allow_audio:
            raise TestLabStoreError(STORE_ARTIFACT_REFUSED,
                                    f"run {run_id}: audio artifacts are opt-in and this store does not allow them")
        run_dir = self._existing_run_dir(run_id)
        target = self._artifact_target(run_dir, run_id, path)
        self._check_artifact_slot(self._read_record(run_dir, run_id), path)
        cap = self.limits.max_bytes_by_kind[kind]
        tmp = run_dir / self._tmp_name(ARTIFACT_TMP_PREFIX)
        self._check_path_budget(tmp, run_id)
        self._check_path_budget(target, run_id)
        parent = target.parent
        while parent != run_dir:
            self._check_path_budget(parent, run_id, directory=True)
            parent = parent.parent
        digest = hashlib.sha256()
        size = 0
        try:
            try:
                with open(tmp, "xb") as handle:
                    for chunk in _chunks(data):
                        size += len(chunk)
                        if size > cap:
                            raise TestLabStoreError(STORE_ARTIFACT_TOO_LARGE,
                                                    f"run {run_id}: {kind.value} artifact exceeds {cap} bytes")
                        digest.update(chunk)
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                ref = ArtifactRef(kind, path, media_type, digest.hexdigest(), size)
            except TestLabError as exc:
                if isinstance(exc, TestLabStoreError):
                    raise
                raise TestLabStoreError(STORE_ARTIFACT_REFUSED, f"run {run_id}: {exc.detail}") from None
            with self._lock(run_id):
                self._check_artifact_slot(self._read_record(self._existing_run_dir(run_id), run_id), path)
                manifest = self._read_manifest(run_dir, run_id)
                if path not in manifest and len(manifest) >= MAX_MANIFEST_ENTRIES:
                    raise TestLabStoreError(STORE_ARTIFACT_REFUSED,
                                            f"run {run_id}: more than {MAX_MANIFEST_ENTRIES} artifacts written")
                target.parent.mkdir(parents=True, exist_ok=True)
                self._artifact_target(run_dir, run_id, path)  # re-check: no link appeared meanwhile
                # Bytes first, then the manifest entry: a crash in between leaves bytes
                # without a matching entry, which no reference can ever commit.
                replace_with_retry(tmp, target)
                manifest[path] = ref
                self._write_manifest(run_dir, run_id, manifest)
        except OSError as exc:
            raise _store_error(STORE_IO, f"run {run_id}: artifact write failed", exc) from exc
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                # intentional: a hidden `.artifact-*.tmp` leftover is ignored by readers and
                # removed by `remove_stale_temporaries`; the primary outcome is already decided.
                pass
        self._diagnose("testlab_artifact_stored", "Test Lab artifact stored", run_id=run_id, artifact_kind=kind.value,
                       size_bytes=size)
        return ref

    @staticmethod
    def _check_artifact_slot(run: TestRun, path: str) -> None:
        if run.status in TERMINAL_STATUSES:
            raise RunConflictError(STORE_CONFLICT, f"run {run.run_id} is {run.status.value}: a terminal run is immutable")
        for ref in run.artifacts:
            if ref.path == path:
                raise TestLabStoreError(STORE_ARTIFACT_REFUSED,
                                        f"run {run.run_id}: artifact.path is already referenced by the record")
            if ref.path.casefold() == path.casefold():
                raise TestLabStoreError(STORE_PATH_UNSAFE,
                                        f"run {run.run_id}: artifact.path differs from a referenced path only by case")

    def _verify_artifact(self, run_dir: Path, run_id: str, ref: ArtifactRef) -> None:
        target = self._artifact_target(run_dir, run_id, ref.path)
        digest = hashlib.sha256()
        size = 0
        try:
            with open(target, "rb") as handle:
                while chunk := handle.read(STREAM_CHUNK_BYTES):
                    size += len(chunk)
                    if size > ref.size_bytes:
                        break
                    digest.update(chunk)
        except FileNotFoundError:
            raise TestLabStoreError(STORE_ARTIFACT_MISMATCH, f"run {run_id}: referenced artifact is not stored") from None
        except OSError as exc:
            raise _store_error(STORE_IO, f"run {run_id}: artifact cannot be read", exc) from exc
        if size != ref.size_bytes or digest.hexdigest() != ref.sha256:
            raise TestLabStoreError(STORE_ARTIFACT_MISMATCH,
                                    f"run {run_id}: stored artifact bytes differ from the reference (size or sha256)")

    def _referenced(self, run_id: str, path: str) -> tuple[Path, ArtifactRef]:
        run_dir = self._existing_run_dir(run_id)
        run = self._read_record(run_dir, run_id)
        for ref in run.artifacts:
            if ref.path == path:
                return self._artifact_target(run_dir, run_id, path), ref
        raise TestLabStoreError(STORE_NOT_FOUND, f"run {run_id}: artifact.path is not referenced by the record")

    def read_artifact(self, run_id: str, path: str, *, verify: bool = True) -> bytes:
        """One read; with `verify`, the returned bytes themselves are hashed and sized against the reference."""
        target, ref = self._referenced(run_id, path)
        try:
            with open(target, "rb") as handle:
                data = handle.read(ref.size_bytes + 1)
        except FileNotFoundError:
            raise TestLabStoreError(STORE_ARTIFACT_MISMATCH, f"run {run_id}: referenced artifact is not stored") from None
        except OSError as exc:
            raise _store_error(STORE_IO, f"run {run_id}: artifact cannot be read", exc) from exc
        if len(data) != ref.size_bytes:
            raise TestLabStoreError(STORE_ARTIFACT_MISMATCH, f"run {run_id}: stored artifact size differs from the reference")
        if verify and hashlib.sha256(data).hexdigest() != ref.sha256:
            raise TestLabStoreError(STORE_ARTIFACT_MISMATCH, f"run {run_id}: stored artifact sha256 differs from the reference")
        return data

    def open_artifact(self, run_id: str, path: str) -> BinaryIO:
        target, _ = self._referenced(run_id, path)
        try:
            return open(target, "rb")
        except FileNotFoundError:
            raise TestLabStoreError(STORE_ARTIFACT_MISMATCH, f"run {run_id}: referenced artifact is not stored") from None
        except OSError as exc:
            raise _store_error(STORE_IO, f"run {run_id}: artifact cannot be opened", exc) from exc

    def list_artifacts(self, run_id: str) -> tuple[ArtifactRef, ...]:
        return self.get_run(run_id).artifacts

    # ------------------------------------------------------ usage, cleanup

    def storage_usage(self) -> StorageUsage:
        names, corrupt = self._entries()
        usage: list[RunUsage] = []
        for run_id in sorted(names):
            run_dir = self.runs_dir / run_id
            run = self._scan_record(run_id, corrupt)
            if run is None:
                continue
            by_kind: dict[ArtifactKind, int] = {}
            for ref in run.artifacts:
                by_kind[ref.kind] = by_kind.get(ref.kind, 0) + ref.size_bytes
            usage.append(RunUsage(run_id, run.created_at, run.status, _tree_bytes(run_dir), by_kind,
                                  finished_at=run.finished_at))
        return StorageUsage(runs=tuple(usage), corrupt=tuple(corrupt))

    def remove_stale_temporaries(self, *, older_than_s: float = DEFAULT_STALE_TEMPORARY_S) -> int:
        """Remove crash leftovers older than `older_than_s`.

        Staging and deleting directories, `.tmp` files, empty subdirectories left
        inside a run (never the run directory, the record or the manifest), and lock
        files whose run no longer exists.

        Returns how many entries were removed. Adapter maintenance, not part of the
        port; nothing schedules it in Slice 02.
        """
        horizon = time.time() - older_than_s
        removed = 0
        try:
            entries = list(os.scandir(self.runs_dir))
        except FileNotFoundError:
            entries = []  # intentional: nothing was ever stored
        except OSError as exc:
            raise _store_error(STORE_IO, "runs directory cannot be listed", exc) from exc
        for entry in entries:
            try:
                if _is_link(Path(entry.path)):
                    continue  # never follow a link (symlink or junction) out of the store
                if entry.name.startswith(DELETING_PREFIX):
                    # The run is already gone from every read: retry at any age. A leftover
                    # with a longer name (older layout) is first renamed to the short form so
                    # that its deepest paths fit the budget they were written under.
                    target = Path(entry.path)
                    if len(entry.name) > len(DELETING_PREFIX) + 16:
                        shorter = self.runs_dir / f"{DELETING_PREFIX}{secrets.token_hex(8)}"
                        replace_with_retry(target, shorter)
                        target = shorter
                    shutil.rmtree(target)
                    removed += 1
                elif entry.name.startswith(STAGING_PREFIX):
                    if entry.stat(follow_symlinks=False).st_mtime < horizon:
                        shutil.rmtree(entry.path)
                        removed += 1
                elif entry.is_dir(follow_symlinks=False):
                    for child in os.scandir(entry.path):
                        if (child.name.startswith((RECORD_TMP_PREFIX, ARTIFACT_TMP_PREFIX))
                                and child.name.endswith(TMP_SUFFIX)
                                and not _is_link(Path(child.path))
                                and child.is_file(follow_symlinks=False)
                                and child.stat(follow_symlinks=False).st_mtime < horizon):
                            os.unlink(child.path)
                            removed += 1
                    removed += _remove_empty_subdirectories(Path(entry.path), horizon)
            except OSError as exc:
                self._diagnose("testlab_store_cleanup_failed", "Test Lab temporary not removed", level="warning",
                               entry=name_for_message(entry.name), error=type(exc).__name__)
        try:
            locks = list(os.scandir(self.locks_dir))
        except FileNotFoundError:
            locks = []  # intentional: no writer ever locked a run
        except OSError as exc:
            raise _store_error(STORE_IO, "locks directory cannot be listed", exc) from exc
        for lock in locks:
            run_id = lock.name.removesuffix(".lock")
            if run_id != lock.name and not (self.runs_dir / run_id).exists():
                try:
                    os.unlink(lock.path)
                    removed += 1
                except OSError:
                    # intentional: a writer still has it open (it will find the run gone);
                    # the next sweep retries.
                    pass
        if removed:
            self._diagnose("testlab_store_cleanup", "Test Lab crash leftovers removed", removed=removed)
        return removed


def _remove_empty_subdirectories(run_dir: Path, horizon: float) -> int:
    """Bottom-up removal of empty, old, non-link subdirectories of a run (the run directory itself stays)."""
    removed = 0

    def visit(directory: Path) -> bool:
        nonlocal removed
        # mtime before visiting: removing an empty child refreshes it.
        mtime = os.stat(directory, follow_symlinks=False).st_mtime
        empty = True
        for entry in list(os.scandir(directory)):
            if entry.is_dir(follow_symlinks=False) and not _is_link(Path(entry.path)):
                if not visit(Path(entry.path)):
                    empty = False
            else:
                empty = False
        if directory == run_dir or not empty or mtime >= horizon:
            return False
        os.rmdir(directory)
        removed += 1
        return True

    visit(run_dir)
    return removed


def _tree_bytes(directory: Path) -> int:
    total = 0
    stack = [directory]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue  # intentional: a directory removed during the scan holds no bytes to count
        for entry in entries:
            try:
                if _is_link(Path(entry.path)):
                    continue  # a link's target lies outside the run: not its bytes
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                else:
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue  # intentional: a file removed during the scan holds no bytes to count
    return total
