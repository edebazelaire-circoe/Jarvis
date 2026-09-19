"""Filesystem adapter of the Test Lab sweep store.

Binding contract: `docs/testlab.md` ("Sweeps", "Storage"). Same root, same
conventions and the same shared helpers (`_fs.py`) as the run and bundle stores:

    <root>/sweeps/<sweep_id>/sweep.json      canonical JSON of the `SweepRecord`
    <root>/sweeps/<sweep_id>/summary.json    readable summary of a finished sweep
    <root>/sweeps/<sweep_id>/.sweep-*.tmp    write in progress (or crash leftover)
    <root>/locks/<sweep_id>.lock             single-writer OS lock of the sweep

A sweep record is rewritten as the sweep progresses, which is the one difference
with a `TestRun`: it is the orchestrator's own progress log, so a human watching
a long sweep sees points land and a crashed orchestrator leaves evidence of what
had already run. A TERMINAL sweep record is immutable, like a terminal run: the
conclusion of an experiment is not edited afterwards.

The runs themselves are not stored here. They are ordinary `TestRun` records in
the run store, tagged with this `sweep_id`, and the run store's own rules
(compare-and-swap, terminal immutability, artifact integrity) are what make them
evidence. This directory only holds what the runs cannot say: the declaration
that produced them and the order they were meant to run in.
"""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import secrets
import shutil
from typing import Any

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.ports.v2 import DiagnosticSink
from jarvis.testlab._diagnostics import SafeDiagnostics
from jarvis.testlab._fs import (
    DEFAULT_LOCK_TIMEOUT_S,
    EntryLock,
    check_path_budget,
    default_max_path_chars,
    is_link,
    store_error,
    tmp_name,
    tree_bytes,
    write_atomic,
)
from jarvis.testlab.identity import check_sweep_id, id_created_at
from jarvis.testlab.store import (
    STORE_BUSY,
    STORE_CONFLICT,
    STORE_CORRUPT,
    STORE_IO,
    STORE_NOT_FOUND,
    STORE_PATH_UNSAFE,
    CorruptRunEntry,
    EntryStorageUsage,
    EntryUsage,
    SweepNotFoundError,
    SweepPage,
    SweepQuery,
    SweepRecordCorruptError,
    TestLabStoreError,
)
from jarvis.testlab.sweeps import SWEEP_TERMINAL_STATUSES, SweepRecord
from jarvis.testlab.validation import (
    MAX_DOCUMENT_BYTES,
    TestLabError,
    canonical_json,
    decode_json_document,
    name_for_message,
)

SWEEPS_DIR = "sweeps"
LOCKS_DIR = "locks"
SWEEP_NAME = "sweep.json"
SUMMARY_NAME = "summary.json"
SWEEP_TMP_PREFIX = ".sweep-"
STAGING_PREFIX = ".staging-"
#: A sweep record holds one entry per point plus its declaration; four times the
#: default document budget keeps a 256-point sweep readable in one file.
MAX_SWEEP_DOCUMENT_BYTES = 4 * MAX_DOCUMENT_BYTES

_SWEEP_ERROR_KINDS = {STORE_NOT_FOUND: SweepNotFoundError, STORE_CORRUPT: SweepRecordCorruptError}


def _store_error(code: str, detail: str, exc: BaseException | None = None) -> TestLabStoreError:
    return store_error(code, detail, exc, kinds=_SWEEP_ERROR_KINDS)


class FilesystemSweepStore:
    """Durable `SweepStore` on a local directory (one directory per sweep)."""

    def __init__(self, root: Path, *, lock_timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
                 diagnostics: DiagnosticSink | None = None, max_path_chars: int | None | object = ...) -> None:
        #: Longest absolute path the store may create (None: unbounded).
        self.max_path_chars: int | None = default_max_path_chars() if max_path_chars is ... else max_path_chars  # type: ignore[assignment]
        self.root = Path(root)
        self.sweeps_dir = self.root / SWEEPS_DIR
        self.locks_dir = self.root / LOCKS_DIR
        self.lock_timeout_s = lock_timeout_s
        self._diagnostics = SafeDiagnostics(diagnostics)

    @property
    def diagnostic_failures(self) -> int:
        """Emissions the diagnostic sink refused (a broken sink never fails a store operation)."""
        return self._diagnostics.failures

    def _sweep_dir(self, sweep_id: str) -> Path:
        try:
            check_sweep_id(sweep_id)
        except TestLabError as exc:
            raise TestLabStoreError(STORE_PATH_UNSAFE, exc.detail) from None
        return self.sweeps_dir / sweep_id

    def _read_json(self, path: Path, sweep_id: str, what: str) -> Any:
        try:
            with open(path, "rb") as handle:
                raw = handle.read(MAX_SWEEP_DOCUMENT_BYTES + 1)
        except FileNotFoundError:
            raise SweepNotFoundError(STORE_NOT_FOUND, f"sweep {sweep_id}: {what} is missing") from None
        except OSError as exc:
            raise _store_error(STORE_IO, f"sweep {sweep_id}: {what} cannot be read", exc) from exc
        try:
            return decode_json_document(raw.decode("utf-8"), max_bytes=MAX_SWEEP_DOCUMENT_BYTES)
        except (UnicodeDecodeError, TestLabError) as exc:
            code = getattr(exc, "code", "not utf-8 text")
            raise SweepRecordCorruptError(STORE_CORRUPT, f"sweep {sweep_id}: {what} does not decode ({code})") from None

    def _read(self, sweep_dir: Path, sweep_id: str) -> SweepRecord:
        payload = self._read_json(sweep_dir / SWEEP_NAME, sweep_id, SWEEP_NAME)
        try:
            record = SweepRecord.from_dict(payload)
        except TestLabError as exc:
            raise SweepRecordCorruptError(STORE_CORRUPT,
                                          f"sweep {sweep_id}: record does not decode ({exc.code})") from None
        if record.sweep_id != sweep_id:
            raise SweepRecordCorruptError(STORE_CORRUPT, f"sweep {sweep_id}: record sweep_id differs from its directory")
        return record

    def _existing_dir(self, sweep_id: str) -> Path:
        sweep_dir = self._sweep_dir(sweep_id)
        try:
            if is_link(sweep_dir):
                raise TestLabStoreError(STORE_PATH_UNSAFE, f"sweep {sweep_id}: sweep directory is a link")
            if not sweep_dir.is_dir():
                raise SweepNotFoundError(STORE_NOT_FOUND, f"sweep {sweep_id} does not exist")
        except OSError as exc:
            raise _store_error(STORE_IO, f"sweep {sweep_id}: sweep directory cannot be inspected", exc) from exc
        return sweep_dir

    # ---------------------------------------------------------------- port

    def put_sweep(self, record: SweepRecord) -> SweepRecord:
        """Create the sweep directory, or rewrite a non-terminal record in place."""
        if not isinstance(record, SweepRecord):
            raise TypeError("put_sweep takes a SweepRecord")
        sweep_id, label = record.sweep_id, f"sweep {record.sweep_id}"
        final = self._sweep_dir(sweep_id)
        payload = canonical_json(record.to_dict()).encode("utf-8")
        if len(payload) > MAX_SWEEP_DOCUMENT_BYTES:
            raise TestLabStoreError(STORE_CONFLICT,
                                    f"{label}: record exceeds {MAX_SWEEP_DOCUMENT_BYTES} bytes")
        check_path_budget(final / SWEEP_NAME, label, self.max_path_chars)
        check_path_budget(final / tmp_name(SWEEP_TMP_PREFIX), label, self.max_path_chars)
        check_path_budget(self.locks_dir / f"{sweep_id}.lock", label, self.max_path_chars)
        with EntryLock(self.locks_dir / f"{sweep_id}.lock", label, self.lock_timeout_s):
            try:
                if is_link(final):
                    raise TestLabStoreError(STORE_PATH_UNSAFE, f"{label}: sweep directory is a link")
                exists = final.is_dir()
            except OSError as exc:
                raise _store_error(STORE_IO, f"{label}: sweep directory cannot be inspected", exc) from exc
            if exists:
                stored = self._read(final, sweep_id)
                if stored.status in SWEEP_TERMINAL_STATUSES:
                    raise TestLabStoreError(STORE_CONFLICT,
                                            f"{label} is {stored.status.value}: a terminal sweep is immutable")
                write_atomic(final, SWEEP_NAME, payload, label=label, tmp_prefix=SWEEP_TMP_PREFIX,
                             max_path_chars=self.max_path_chars, replace=replace_with_retry)
            else:
                self._create(final, label, payload)
        self._diagnostics.emit("testlab_sweep_stored", "Test Lab sweep record stored", sweep_id=sweep_id,
                               status=record.status.value, points=len(record.points), runs=len(record.run_ids))
        return record

    def _create(self, final: Path, label: str, payload: bytes) -> None:
        """A sweep directory appears complete or not at all (staging + directory replace)."""
        staging = self.sweeps_dir / f"{STAGING_PREFIX}{final.name}-{secrets.token_hex(4)}"
        check_path_budget(staging / tmp_name(SWEEP_TMP_PREFIX), label, self.max_path_chars)
        try:
            self.sweeps_dir.mkdir(parents=True, exist_ok=True)
            staging.mkdir()
            write_atomic(staging, SWEEP_NAME, payload, label=label, tmp_prefix=SWEEP_TMP_PREFIX,
                         max_path_chars=self.max_path_chars, replace=replace_with_retry)
            replace_with_retry(staging, final)
        except TestLabStoreError:
            shutil.rmtree(staging, ignore_errors=True)  # intentional: a hidden staging leftover is harmless
            raise
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)  # intentional: a hidden staging leftover is harmless
            raise _store_error(STORE_IO, f"{label}: creation failed", exc) from exc

    def get_sweep(self, sweep_id: str) -> SweepRecord:
        sweep_dir = self._existing_dir(sweep_id)
        try:
            return self._read(sweep_dir, sweep_id)
        except SweepRecordCorruptError as exc:
            self._diagnostics.emit("testlab_sweep_corrupt", "Test Lab sweep record unreadable", level="warning",
                                   sweep_id=sweep_id, detail=exc.detail)
            raise

    def list_sweeps(self, query: SweepQuery = SweepQuery()) -> SweepPage:
        """Sweeps in id order; stray and unreadable entries are reported in `corrupt`, never skipped."""
        if not isinstance(query, SweepQuery):
            raise TypeError("list_sweeps takes a SweepQuery")
        names, corrupt = self._entries()
        records: list[SweepRecord] = []
        more = False
        for sweep_id in sorted(names, reverse=query.newest_first):
            if query.after_sweep_id is not None and (
                    sweep_id >= query.after_sweep_id if query.newest_first else sweep_id <= query.after_sweep_id):
                continue
            if len(records) == query.limit:
                more = True
                break
            try:
                records.append(self._read(self.sweeps_dir / sweep_id, sweep_id))
            except TestLabStoreError as exc:
                corrupt.append(CorruptRunEntry(sweep_id, exc.code, exc.detail))
        if corrupt:
            self._diagnostics.emit("testlab_sweep_listing_corrupt", "Test Lab sweep listing met unreadable entries",
                                   level="warning", count=len(corrupt), entries=[item.entry for item in corrupt[:16]])
        return SweepPage(tuple(records), tuple(corrupt), records[-1].sweep_id if more else None)

    def _entries(self) -> tuple[list[str], list[CorruptRunEntry]]:
        try:
            entries = list(os.scandir(self.sweeps_dir))
        except FileNotFoundError:
            return [], []  # intentional: no sweep was ever stored (the first one creates the directory)
        except OSError as exc:
            raise _store_error(STORE_IO, "sweeps directory cannot be listed", exc) from exc
        names: list[str] = []
        stray: list[CorruptRunEntry] = []
        for entry in entries:
            if entry.name.startswith(STAGING_PREFIX):
                continue
            try:
                check_sweep_id(entry.name)
            except TestLabError:
                stray.append(CorruptRunEntry(name_for_message(entry.name), STORE_CORRUPT,
                                             "entry is not a sweep directory (unrecognized name)"))
                continue
            if is_link(Path(entry.path)) or not entry.is_dir(follow_symlinks=False):
                stray.append(CorruptRunEntry(entry.name, STORE_CORRUPT, "entry is not a plain sweep directory"))
                continue
            names.append(entry.name)
        return names, stray

    def delete_sweep(self, sweep_id: str) -> None:
        """Retention deletion of a TERMINAL sweep record and its summary (Slice 12).

        Refused while the sweep is running (`testlab_store_conflict`) and refused when
        the record does not decode: a corrupt entry is evidence of a defect, and nothing
        in the Test Lab deletes evidence of a defect automatically.

        The runs the sweep produced are NOT touched. They are ordinary `TestRun` records
        with their own retention; deleting the index never deletes the measurements.
        """
        self._existing_dir(sweep_id)  # not found before any lock file is created
        with EntryLock(self.locks_dir / f"{sweep_id}.lock", f"sweep {sweep_id}", self.lock_timeout_s):
            sweep_dir = self._existing_dir(sweep_id)
            record = self._read(sweep_dir, sweep_id)
            if record.status not in SWEEP_TERMINAL_STATUSES:
                raise _store_error(STORE_CONFLICT, f"sweep {sweep_id} is {record.status.value}: "
                                                   "only a terminal sweep can be deleted")
            try:
                shutil.rmtree(sweep_dir)
            except OSError as exc:
                raise _store_error(STORE_BUSY, f"sweep {sweep_id}: directory is held open, not deleted",
                                   exc) from exc
        try:
            (self.locks_dir / f"{sweep_id}.lock").unlink(missing_ok=True)
        except OSError:
            # intentional: another process still holds the (empty) lock file open on Windows.
            pass
        self._diagnostics.emit("testlab_sweep_deleted", "Test Lab sweep deleted by retention", sweep_id=sweep_id)

    def storage_usage(self) -> EntryStorageUsage:
        """Per-sweep disk usage for the retention planner. The record is read for its status only."""
        names, corrupt = self._entries()
        entries: list[EntryUsage] = []
        for sweep_id in sorted(names):
            sweep_dir = self.sweeps_dir / sweep_id
            try:
                record = self._read(sweep_dir, sweep_id)
            except TestLabStoreError as exc:
                corrupt.append(CorruptRunEntry(sweep_id, exc.code, exc.detail))
                continue
            entries.append(EntryUsage(sweep_id, id_created_at(sweep_id, "sweep_id"), tree_bytes(sweep_dir),
                                      active=record.status not in SWEEP_TERMINAL_STATUSES))
        return EntryStorageUsage(tuple(entries), tuple(corrupt))

    def put_sweep_summary(self, sweep_id: str, document: Mapping[str, object]) -> None:
        """Store the readable summary of a sweep next to its record. Write-once.

        Same rule as `put_sweep`, for the same reason: the conclusion of an experiment
        is not edited afterwards. A summary is only ever written when the sweep ends, so
        a second write would be a rewrite of a terminal conclusion, and the two calls
        disagreeing about that was a way to change what a finished sweep reports while
        its record said otherwise.
        """
        if not isinstance(document, Mapping):
            raise TypeError("put_sweep_summary takes a mapping")
        sweep_dir = self._existing_dir(sweep_id)
        label = f"sweep {sweep_id}"
        payload = canonical_json(dict(document)).encode("utf-8")
        if len(payload) > MAX_SWEEP_DOCUMENT_BYTES:
            raise TestLabStoreError(STORE_CONFLICT, f"{label}: summary exceeds {MAX_SWEEP_DOCUMENT_BYTES} bytes")
        check_path_budget(sweep_dir / SUMMARY_NAME, label, self.max_path_chars)
        with EntryLock(self.locks_dir / f"{sweep_id}.lock", label, self.lock_timeout_s):
            try:
                exists = (sweep_dir / SUMMARY_NAME).is_file()
            except OSError as exc:
                raise _store_error(STORE_IO, f"{label}: summary cannot be inspected", exc) from exc
            if exists:
                raise TestLabStoreError(STORE_CONFLICT, f"{label}: its summary is already stored and is not rewritten")
            write_atomic(sweep_dir, SUMMARY_NAME, payload, label=label, tmp_prefix=SWEEP_TMP_PREFIX,
                         max_path_chars=self.max_path_chars, replace=replace_with_retry)
        self._diagnostics.emit("testlab_sweep_summary_stored", "Test Lab sweep summary stored", sweep_id=sweep_id,
                               size_bytes=len(payload))

    def get_sweep_summary(self, sweep_id: str) -> Mapping[str, object]:
        sweep_dir = self._existing_dir(sweep_id)
        document = self._read_json(sweep_dir / SUMMARY_NAME, sweep_id, SUMMARY_NAME)
        if not isinstance(document, dict):
            raise SweepRecordCorruptError(STORE_CORRUPT, f"sweep {sweep_id}: summary is not an object")
        return document
