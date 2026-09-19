"""Filesystem adapter of the Test Lab bundle store.

Binding contract: `docs/testlab.md` ("DiagnosticBundle", "Storage"). Same root
and conventions as `FilesystemTestRunStore` (shared helpers in `_fs.py`):

    <root>/bundles/<bundle_id>/bundle.json       canonical JSON of the bundle (`DiagnosticBundle.encode`)
    <root>/bundles/<bundle_id>/.bundle-*.tmp     write in progress (or crash leftover)
    <root>/bundles/.staging-<bundle_id>-*        bundle being created
    <root>/locks/<bundle_id>.lock                single-writer OS lock of the bundle

A bundle is immutable once stored. `put_bundle` is idempotent: the bundle id is
derived from the evidence content, so storing the same session again answers
`duplicate` and keeps the first capture.
"""

from __future__ import annotations

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
from jarvis.testlab.bundle import MAX_BUNDLE_BYTES, DiagnosticBundle
from jarvis.testlab.identity import check_bundle_id, id_created_at
from jarvis.testlab.store import (
    STORE_BUSY,
    STORE_CONFLICT,
    STORE_CORRUPT,
    STORE_IO,
    STORE_NOT_FOUND,
    STORE_PATH_UNSAFE,
    BundleConflictError,
    BundleNotFoundError,
    BundlePage,
    BundlePutResult,
    BundlePutStatus,
    BundleQuery,
    BundleRecordCorruptError,
    BundleSummary,
    CorruptRunEntry,
    EntryStorageUsage,
    EntryUsage,
    TestLabStoreError,
)
from jarvis.testlab.validation import TestLabError, name_for_message

BUNDLES_DIR = "bundles"
LOCKS_DIR = "locks"
BUNDLE_NAME = "bundle.json"
BUNDLE_TMP_PREFIX = ".bundle-"
STAGING_PREFIX = ".staging-"

_BUNDLE_ERROR_KINDS = {STORE_NOT_FOUND: BundleNotFoundError, STORE_CONFLICT: BundleConflictError,
                       STORE_CORRUPT: BundleRecordCorruptError}


def _store_error(code: str, detail: str, exc: BaseException | None = None) -> TestLabStoreError:
    return store_error(code, detail, exc, kinds=_BUNDLE_ERROR_KINDS)


class FilesystemBundleStore:
    """Durable `BundleStore` on a local directory (one directory per bundle)."""

    def __init__(self, root: Path, *, lock_timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
                 diagnostics: DiagnosticSink | None = None, max_path_chars: int | None | object = ...) -> None:
        #: Longest absolute path the store may create (None: unbounded). Default: `default_max_path_chars()`.
        self.max_path_chars: int | None = default_max_path_chars() if max_path_chars is ... else max_path_chars  # type: ignore[assignment]
        self.root = Path(root)
        self.bundles_dir = self.root / BUNDLES_DIR
        self.locks_dir = self.root / LOCKS_DIR
        self.lock_timeout_s = lock_timeout_s
        self._diagnostics = SafeDiagnostics(diagnostics)

    @property
    def diagnostic_failures(self) -> int:
        """Emissions the diagnostic sink refused (a broken sink never fails a store operation)."""
        return self._diagnostics.failures

    def _diagnose(self, kind: str, message: str, *, level: str = "info", **data: Any) -> None:
        self._diagnostics.emit(kind, message, level=level, **data)

    def _bundle_dir(self, bundle_id: str) -> Path:
        try:
            check_bundle_id(bundle_id)
        except TestLabError as exc:
            raise TestLabStoreError(STORE_PATH_UNSAFE, exc.detail) from None
        return self.bundles_dir / bundle_id

    def _read(self, bundle_dir: Path, bundle_id: str) -> DiagnosticBundle:
        try:
            with open(bundle_dir / BUNDLE_NAME, "rb") as handle:
                raw = handle.read(MAX_BUNDLE_BYTES + 1)
        except FileNotFoundError:
            raise BundleRecordCorruptError(STORE_CORRUPT, f"bundle {bundle_id}: bundle.json is missing") from None
        except OSError as exc:
            raise _store_error(STORE_IO, f"bundle {bundle_id}: bundle cannot be read", exc) from exc
        try:
            bundle = DiagnosticBundle.decode(raw)
        except TestLabError as exc:
            raise BundleRecordCorruptError(STORE_CORRUPT,
                                           f"bundle {bundle_id}: bundle does not decode ({exc.code})") from None
        if bundle.bundle_id != bundle_id:
            raise BundleRecordCorruptError(STORE_CORRUPT, f"bundle {bundle_id}: bundle_id differs from its directory")
        return bundle

    # ---------------------------------------------------------------- port

    def put_bundle(self, bundle: DiagnosticBundle) -> BundlePutResult:
        if not isinstance(bundle, DiagnosticBundle):
            raise TypeError("put_bundle takes a DiagnosticBundle")
        bundle_id, label = bundle.bundle_id, f"bundle {bundle.bundle_id}"
        final = self._bundle_dir(bundle_id)
        payload = bundle.encode()
        staging = self.bundles_dir / f"{STAGING_PREFIX}{bundle_id}-{secrets.token_hex(4)}"
        check_path_budget(staging, label, self.max_path_chars, directory=True)
        check_path_budget(staging / tmp_name(BUNDLE_TMP_PREFIX), label, self.max_path_chars)
        check_path_budget(final / BUNDLE_NAME, label, self.max_path_chars)
        check_path_budget(self.locks_dir / f"{bundle_id}.lock", label, self.max_path_chars)
        with EntryLock(self.locks_dir / f"{bundle_id}.lock", label, self.lock_timeout_s):
            try:
                if is_link(final):
                    raise TestLabStoreError(STORE_PATH_UNSAFE, f"{label}: bundle directory is a link")
                exists = final.is_dir()
            except OSError as exc:
                raise _store_error(STORE_IO, f"{label}: bundle directory cannot be inspected", exc) from exc
            if exists:
                stored = self._read(final, bundle_id)
                if stored.content_fingerprint != bundle.content_fingerprint:
                    raise BundleConflictError(STORE_CONFLICT,
                                              f"{label}: already stored with a different content fingerprint")
                self._diagnose("testlab_bundle_duplicate", "Test Lab bundle already stored", bundle_id=bundle_id)
                return BundlePutResult(bundle_id, BundlePutStatus.DUPLICATE, bundle.content_fingerprint)
            try:
                self.bundles_dir.mkdir(parents=True, exist_ok=True)
                staging.mkdir()
                write_atomic(staging, BUNDLE_NAME, payload, label=label, tmp_prefix=BUNDLE_TMP_PREFIX,
                             max_path_chars=self.max_path_chars, replace=replace_with_retry)
                replace_with_retry(staging, final)
            except TestLabStoreError:
                shutil.rmtree(staging, ignore_errors=True)  # intentional: a hidden staging leftover is harmless
                raise
            except OSError as exc:
                shutil.rmtree(staging, ignore_errors=True)  # intentional: a hidden staging leftover is harmless
                raise _store_error(STORE_IO, f"{label}: creation failed", exc) from exc
        self._diagnose("testlab_bundle_stored", "Test Lab bundle stored", bundle_id=bundle_id, size_bytes=len(payload),
                       findings=len(bundle.findings))
        return BundlePutResult(bundle_id, BundlePutStatus.STORED, bundle.content_fingerprint)

    def get_bundle(self, bundle_id: str) -> DiagnosticBundle:
        bundle_dir = self._bundle_dir(bundle_id)
        try:
            if is_link(bundle_dir):
                raise TestLabStoreError(STORE_PATH_UNSAFE, f"bundle {bundle_id}: bundle directory is a link")
            if not bundle_dir.is_dir():
                raise BundleNotFoundError(STORE_NOT_FOUND, f"bundle {bundle_id} does not exist")
        except OSError as exc:
            raise _store_error(STORE_IO, f"bundle {bundle_id}: bundle directory cannot be inspected", exc) from exc
        try:
            return self._read(bundle_dir, bundle_id)
        except BundleRecordCorruptError as exc:
            self._diagnose("testlab_bundle_corrupt", "Test Lab bundle unreadable", level="warning",
                           bundle_id=bundle_id, detail=exc.detail)
            raise

    def delete_bundle(self, bundle_id: str) -> None:
        """Retention deletion of one stored bundle (Slice 12).

        Refused when the bundle does not decode, for the same reason the sweep store
        refuses it: an unreadable entry is evidence of a defect. A run that references
        this bundle is not consulted here — that rule lives in the planner, which has
        the run usage this store cannot see (`referenced_archive_ids`).
        """
        bundle_dir = self._bundle_dir(bundle_id)
        with EntryLock(self.locks_dir / f"{bundle_id}.lock", f"bundle {bundle_id}", self.lock_timeout_s):
            try:
                if is_link(bundle_dir):
                    raise TestLabStoreError(STORE_PATH_UNSAFE, f"bundle {bundle_id}: bundle directory is a link")
                if not bundle_dir.is_dir():
                    raise BundleNotFoundError(STORE_NOT_FOUND, f"bundle {bundle_id} does not exist")
            except OSError as exc:
                raise _store_error(STORE_IO, f"bundle {bundle_id}: bundle directory cannot be inspected",
                                   exc) from exc
            self._read(bundle_dir, bundle_id)
            try:
                shutil.rmtree(bundle_dir)
            except OSError as exc:
                raise _store_error(STORE_BUSY, f"bundle {bundle_id}: directory is held open, not deleted",
                                   exc) from exc
        try:
            (self.locks_dir / f"{bundle_id}.lock").unlink(missing_ok=True)
        except OSError:
            # intentional: another process still holds the (empty) lock file open on Windows.
            pass
        self._diagnose("testlab_bundle_deleted", "Test Lab bundle deleted by retention", bundle_id=bundle_id)

    def storage_usage(self) -> EntryStorageUsage:
        """Per-bundle disk usage for the retention planner.

        The age comes from the bundle id, not from a decoded document: a bundle is
        immutable and its id carries the session start, so a pass over a thousand
        bundles states a thousand directories instead of decoding a thousand documents.
        """
        entries: list[EntryUsage] = []
        corrupt: list[CorruptRunEntry] = []
        try:
            scanned = list(os.scandir(self.bundles_dir))
        except FileNotFoundError:
            return EntryStorageUsage()  # intentional: no bundle was ever stored
        except OSError as exc:
            raise _store_error(STORE_IO, "bundles directory cannot be listed", exc) from exc
        for entry in scanned:
            if entry.name.startswith(STAGING_PREFIX):
                continue
            try:
                check_bundle_id(entry.name)
            except TestLabError:
                corrupt.append(CorruptRunEntry(name_for_message(entry.name), STORE_CORRUPT,
                                               "entry is not a bundle directory (unrecognized name)"))
                continue
            if entry.is_symlink() or Path(entry.path).is_junction() or not entry.is_dir(follow_symlinks=False):
                corrupt.append(CorruptRunEntry(entry.name, STORE_CORRUPT, "entry is not a plain bundle directory"))
                continue
            entries.append(EntryUsage(entry.name, id_created_at(entry.name, "bundle_id"),
                                      tree_bytes(Path(entry.path))))
        return EntryStorageUsage(tuple(sorted(entries, key=lambda item: item.entry_id)), tuple(corrupt))

    def list_bundles(self, query: BundleQuery = BundleQuery()) -> BundlePage:
        """Bundles in id order (each read and decoded); stray and unreadable entries are reported in `corrupt`."""
        if not isinstance(query, BundleQuery):
            raise TypeError("list_bundles takes a BundleQuery")
        try:
            entries = list(os.scandir(self.bundles_dir))
        except FileNotFoundError:
            return BundlePage(())  # intentional: no bundle was ever stored
        except OSError as exc:
            raise _store_error(STORE_IO, "bundles directory cannot be listed", exc) from exc
        names: list[str] = []
        corrupt: list[CorruptRunEntry] = []
        for entry in entries:
            if entry.name.startswith(STAGING_PREFIX):
                continue
            try:
                check_bundle_id(entry.name)
            except TestLabError:
                corrupt.append(CorruptRunEntry(name_for_message(entry.name), STORE_CORRUPT,
                                               "entry is not a bundle directory (unrecognized name)"))
                continue
            if entry.is_symlink() or Path(entry.path).is_junction() or not entry.is_dir(follow_symlinks=False):
                corrupt.append(CorruptRunEntry(entry.name, STORE_CORRUPT, "entry is not a plain bundle directory"))
                continue
            names.append(entry.name)
        summaries: list[BundleSummary] = []
        more = False
        for bundle_id in sorted(names, reverse=query.newest_first):
            if query.after_bundle_id is not None and (
                    bundle_id >= query.after_bundle_id if query.newest_first else bundle_id <= query.after_bundle_id):
                continue
            try:
                bundle = self._read(self.bundles_dir / bundle_id, bundle_id)
            except TestLabStoreError as exc:
                corrupt.append(CorruptRunEntry(bundle_id, exc.code, exc.detail))
                continue
            if query.conversation_id is not None and query.conversation_id not in bundle.conversation_ids:
                continue
            if len(summaries) == query.limit:
                more = True
                break
            summaries.append(BundleSummary.of(bundle))
        if corrupt:
            self._diagnose("testlab_bundle_listing_corrupt", "Test Lab bundle listing met unreadable entries",
                           level="warning", count=len(corrupt), entries=[item.entry for item in corrupt[:16]])
        return BundlePage(tuple(summaries), tuple(corrupt), summaries[-1].bundle_id if more else None)
