"""Private filesystem primitives shared by the Test Lab stores (runs, bundles).

Binding contract: `docs/testlab.md` ("Storage", "DiagnosticBundle"). Extracted
from `filesystem_store.py` in Slice 03 so `FilesystemBundleStore` reuses exactly
the run store's conventions instead of copying them:

- `EntryLock`: exclusive OS lock file (`msvcrt.locking` / `flock`), released by
  the OS when the holder dies, `testlab_store_busy` after the timeout;
- `write_atomic`: hidden temp file + flush + fsync + `replace_with_retry`, the
  target is the old or the new content, never partial;
- `check_path_budget`: legacy Windows `MAX_PATH` budget checked before any write;
- `is_link`: symlink or junction (never followed by a store).

Error details name the entry (`run <id>`, `bundle <id>`) and the rule, never a
value or a local path.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import errno
import os
from pathlib import Path
import secrets
import time

from jarvis.testlab.store import STORE_BUSY, STORE_IO, STORE_PATH_UNSAFE, TestLabStoreError

if os.name == "nt":
    import msvcrt
else:
    import fcntl

#: Lock wait before `testlab_store_busy`. A lock only covers read-compare-write
#: (milliseconds), never a stream, so a long wait means a stuck writer.
DEFAULT_LOCK_TIMEOUT_S = 5.0
LOCK_POLL_S = 0.01
#: Temp names have a fixed length: prefix + 16 hex + `.tmp`.
TMP_TOKEN_HEX = 16
TMP_SUFFIX = ".tmp"
#: Windows `MAX_PATH` is 260 including the terminating NUL; `CreateDirectoryW`
#: also keeps 12 characters for an 8.3 file name inside the new directory.
WINDOWS_MAX_PATH_CHARS = 259
DIRECTORY_RESERVE_CHARS = 12

#: errno values meaning "another handle holds the lock" (msvcrt: EACCES/EDEADLOCK, flock: EWOULDBLOCK).
_LOCK_CONTENTION_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK})


def store_error(code: str, detail: str, exc: BaseException | None = None, *,
                kinds: Mapping[str, type[TestLabStoreError]] | None = None) -> TestLabStoreError:
    """Typed store error; `kinds` maps a code to its subclass (not found, conflict, corrupt)."""
    kind = (kinds or {}).get(code, TestLabStoreError)
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


def is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def tmp_name(prefix: str) -> str:
    return f"{prefix}{secrets.token_hex(TMP_TOKEN_HEX // 2)}{TMP_SUFFIX}"


def check_path_budget(path: Path, label: str, max_path_chars: int | None, *, directory: bool = False) -> None:
    """Refuse, before any write, a path the host cannot create (legacy Windows `MAX_PATH`)."""
    if max_path_chars is None:
        return
    budget = max_path_chars - (DIRECTORY_RESERVE_CHARS if directory else 0)
    length = len(os.path.abspath(path))
    if length > budget:
        raise TestLabStoreError(STORE_PATH_UNSAFE, f"{label}: path of {length} characters exceeds the "
                                                   f"{budget}-character path budget of this host")


def lock_fd(fd: int) -> None:
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_fd(fd: int) -> None:
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


class EntryLock:
    """Exclusive OS lock on one lock file (msvcrt on Windows, flock elsewhere).

    The OS releases it when the holder dies, so a crashed writer never leaves a
    stale lock. Locks are per open handle: two threads of one process exclude
    each other as two processes do. `label` names the entry in errors
    (`run <id>`, `bundle <id>`).
    """

    def __init__(self, path: Path, label: str, timeout_s: float) -> None:
        self._path = path
        self._label = label
        self._timeout_s = timeout_s
        self._fd: int | None = None

    def __enter__(self) -> EntryLock:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            raise store_error(STORE_IO, f"{self._label}: writer lock cannot be opened", exc) from exc
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                lock_fd(fd)
            except OSError as exc:
                if exc.errno not in _LOCK_CONTENTION_ERRNOS:
                    os.close(fd)
                    raise store_error(STORE_IO, f"{self._label}: writer lock failed", exc) from exc
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise store_error(STORE_BUSY, f"{self._label}: another writer holds the lock "
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
            unlock_fd(fd)
        except OSError:
            # intentional: closing the handle below releases an OS file lock anyway, and
            # the protected write has already committed or raised its own error.
            pass
        finally:
            os.close(fd)


def write_atomic(directory: Path, target_name: str, payload: bytes, *, label: str, tmp_prefix: str,
                 max_path_chars: int | None, replace: Callable[[Path, Path], None]) -> None:
    """Temp file + flush + fsync + `replace`: the target is old or new, never partial.

    `replace` is `jarvis.adapters.file_replace.replace_with_retry`, passed by the
    caller (retries brief Windows sharing violations). On failure the temp file is
    removed and `testlab_store_io` is raised; the previous content stays intact.
    Directory fsync is not attempted: a directory cannot be opened for writing on
    Windows, and NTFS journals the rename itself.
    """
    tmp = directory / tmp_name(tmp_prefix)
    check_path_budget(tmp, label, max_path_chars)
    try:
        with open(tmp, "xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        replace(tmp, directory / target_name)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            # intentional: the leftover is a hidden `.tmp` that readers ignore and the
            # temporaries sweep deletes; the write failure below is the error.
            pass
        raise store_error(STORE_IO, f"{label}: record write failed, previous record intact", exc) from exc


def tree_bytes(directory: Path) -> int:
    """Every byte under `directory`, links never followed (a link's target is not its bytes).

    Extracted from `filesystem_store.py` in Slice 12, unchanged, because the sweep and
    bundle stores now report their own usage to the retention planner and must count the
    same way the run store does. Never raises: an entry removed during the scan holds no
    bytes to count, which is also why usage is a snapshot and not a ledger.
    """
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
                if is_link(Path(entry.path)):
                    continue  # a link's target lies outside the tree: not its bytes
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                else:
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue  # intentional: a file removed during the scan holds no bytes to count
    return total
