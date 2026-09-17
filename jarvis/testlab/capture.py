"""Test Lab run capturers: code identity, execution environment, configuration snapshot.

Binding contract: `docs/testlab.md` ("Storage", "Capture"). Each capturer takes
its probes as arguments so tests (and later runners) control every input:

- `read_git_revision` reads `.git` files directly (HEAD, loose refs,
  `packed-refs`, linked worktrees). No subprocess: `scripts/verify_release.py`
  forbids the blocking subprocess primitives under `jarvis/`, and plain files give a
  deterministic answer without git on PATH.
- `dirty` cannot be read from files without reimplementing git's index stat
  comparison, so it is an injected async probe. The default,
  `git_worktree_dirty`, reuses the argument-array `asyncio` git helper of
  `jarvis.runtime.worktrees`.
- `capture_environment` records only non-identifying facts and drops any value
  that contains the user name, host name or home path.
- `build_config_snapshot` redacts secret and private-content keys before the
  snapshot is written or fingerprinted;
- `redact_evidence` / `failure_detail` (Slice 05) clean the captured worker output
  before it is stored. They live here rather than in `redaction.py` because they
  need `identity_fragments()` (which reads the environment) and the credential
  vocabulary of `jarvis.runtime.conversation_event_trace`, and `redaction.py` is a
  pure contract module (`tests/unit/test_testlab_purity.py`) that may import
  neither.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
import getpass
import math
import os
from pathlib import Path, PurePath
import platform
import re
import socket
from types import MappingProxyType
from typing import Any

from jarvis.runtime.conversation_event_trace import SECRET_PREFIXES
from jarvis.runtime.worktrees import WorktreeError, git
from jarvis.testlab.redaction import (  # noqa: F401 - re-exported: moved to a pure module in Slice 03
    EMAIL_PLACEHOLDER,
    REDACTED,
    redact_identifying_text,
    redact_urls,
)
from jarvis.testlab.runs import MAX_FAILURE_DETAIL_CHARS, ArtifactKind, ArtifactRef, CodeIdentity
from jarvis.testlab.store import TestRunStore
from jarvis.testlab.validation import (
    FORBIDDEN_PRIVATE_DATA,
    LIMIT_EXCEEDED,
    TestLabError,
    TestLabRedactionError,
    canonical_json,
    check_open_key,
    check_scalar_value,
    content_fingerprint,
    fail,
    is_private_key,
    name_for_message,
)

CAPTURE_UNAVAILABLE = "testlab_capture_unavailable"


class TestLabCaptureError(TestLabError):
    """A capturer could not produce its fact (no repository, unresolvable HEAD, git failure)."""


# ------------------------------------------------------------------ code

_HEX_REVISION = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_REF_NAME = re.compile(r"refs/[A-Za-z0-9._/-]+")
_MAX_GIT_FILE_BYTES = 4096
_MAX_SYMREF_HOPS = 5


def _unavailable(detail: str) -> TestLabCaptureError:
    return TestLabCaptureError(CAPTURE_UNAVAILABLE, detail)


def _read_small(path: Path, what: str) -> str | None:
    try:
        with open(path, "rb") as handle:
            raw = handle.read(_MAX_GIT_FILE_BYTES + 1)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _unavailable(f"git {what} cannot be read ({type(exc).__name__})") from exc
    if len(raw) > _MAX_GIT_FILE_BYTES:
        raise _unavailable(f"git {what} is unexpectedly large")
    try:
        return raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise _unavailable(f"git {what} is not text") from None


def _git_dirs(repo_root: Path) -> tuple[Path, Path]:
    """(worktree git dir, common git dir). A linked worktree has a `.git` file `gitdir: <path>`."""
    dotgit = Path(repo_root) / ".git"
    if dotgit.is_dir():
        git_dir = dotgit
    elif dotgit.is_file():
        content = _read_small(dotgit, ".git file") or ""
        if not content.startswith("gitdir:"):
            raise _unavailable("git .git file has no gitdir line")
        git_dir = Path(content.removeprefix("gitdir:").strip())
        if not git_dir.is_absolute():
            git_dir = Path(repo_root) / git_dir
    else:
        raise _unavailable("no git repository at the repository root")
    common = git_dir
    commondir = _read_small(git_dir / "commondir", "commondir")
    if commondir:
        common = Path(commondir) if Path(commondir).is_absolute() else git_dir / commondir
    if (common / "reftable").is_dir():
        raise _unavailable("git reftable ref storage is not supported; supply the revision explicitly")
    return git_dir, common


def _packed_ref(common: Path, ref: str) -> str | None:
    try:
        with open(common / "packed-refs", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(("#", "^")):
                    continue
                parts = line.rstrip("\n").split(" ", 1)
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0]
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise _unavailable(f"git packed-refs cannot be read ({type(exc).__name__})") from exc
    return None


def read_git_revision(repo_root: Path) -> str:
    """The commit HEAD points to: detached HEAD, loose ref, `packed-refs`, linked worktree."""
    git_dir, common = _git_dirs(repo_root)
    value = _read_small(git_dir / "HEAD", "HEAD")
    if value is None:
        raise _unavailable("git HEAD is missing")
    for _ in range(_MAX_SYMREF_HOPS):
        if _HEX_REVISION.fullmatch(value):
            return value
        if not value.startswith("ref:"):
            raise _unavailable("git HEAD is neither a revision nor a symbolic ref")
        ref = value.removeprefix("ref:").strip()
        if not _REF_NAME.fullmatch(ref) or ".." in ref.split("/"):
            raise _unavailable("git HEAD names an invalid ref")
        resolved = _read_small(git_dir / ref, "ref")
        if resolved is None and common != git_dir:
            resolved = _read_small(common / ref, "ref")
        if resolved is None:
            resolved = _packed_ref(common, ref)
        if resolved is None:
            raise _unavailable("git HEAD points to a branch with no commit yet")
        value = resolved
    raise _unavailable("git symbolic refs nest too deeply")


DirtyProbe = Callable[[Path], Awaitable[bool]]

#: Tracked paths that are runtime state, not code: the running Jarvis rewrites
#: `data/state/jarvis.sqlite3` continuously (READINESS B4.3), which would make
#: every run look dirty.
DEFAULT_DIRTY_EXCLUDES = ("data/state",)


async def git_worktree_dirty(repo_root: Path, *, excludes: Iterable[str] = DEFAULT_DIRTY_EXCLUDES) -> bool:
    """True when `git status --porcelain` lists a change (untracked files included) outside `excludes`.

    `--no-optional-locks` keeps git from refreshing the index, so a Test Lab run
    never takes `index.lock` against the user's own concurrent git commands.
    """
    pathspecs = [".", *(f":(exclude){item}" for item in excludes)]
    try:
        output = await git("--no-optional-locks", "status", "--porcelain", "--", *pathspecs, cwd=Path(repo_root))
    except WorktreeError as exc:
        # The git message may carry local paths: keep only its stable code.
        raise _unavailable(f"git status failed ({exc.code})") from None
    return bool(output.strip())


async def capture_code_identity(repo_root: Path, *, dirty_probe: DirtyProbe = git_worktree_dirty) -> CodeIdentity:
    """`CodeIdentity` of the checkout at `repo_root`: revision from files, `dirty` from the probe."""
    revision = read_git_revision(repo_root)
    dirty = await dirty_probe(Path(repo_root))
    if type(dirty) is not bool:
        raise fail("dirty probe must return a boolean")
    return CodeIdentity(revision, dirty)


# ----------------------------------------------------------- environment

def _total_memory_bytes() -> int | None:
    if os.name == "nt":
        import ctypes

        class _MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.ullTotalPhys)
    try:
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, ValueError, OSError):
        return None  # intentional: platform without sysconf memory names; the fact is omitted


def _memory_bucket_gib() -> int | None:
    """Total RAM rounded to a power of two GiB: enough to compare hosts, too coarse to fingerprint one."""
    total = _total_memory_bytes()
    if not total:
        return None
    return max(1, 2 ** round(math.log2(total / 2**30))) if total >= 2**29 else 1


@dataclass(frozen=True, slots=True)
class EnvironmentProbe:
    """Where each environment fact comes from. Every name here is a closed, non-identifying fact."""

    os_family: Callable[[], object] = lambda: platform.system().lower()
    os_release: Callable[[], object] = platform.release
    os_version: Callable[[], object] = platform.version
    machine: Callable[[], object] = lambda: platform.machine().lower()
    python_implementation: Callable[[], object] = lambda: platform.python_implementation().lower()
    python_version: Callable[[], object] = platform.python_version
    cpu_count: Callable[[], object] = os.cpu_count
    memory_gib_bucket: Callable[[], object] = _memory_bucket_gib


#: Environment name -> probe attribute. The closed set a capturer may emit.
ENVIRONMENT_FACTS: Mapping[str, str] = MappingProxyType({
    "os": "os_family",
    "os_release": "os_release",
    "os_version": "os_version",
    "machine": "machine",
    "python_implementation": "python_implementation",
    "python_version": "python_version",
    "host.cpu_count": "cpu_count",
    "host.memory_gib_bucket": "memory_gib_bucket",
})

_MIN_FRAGMENT_CHARS = 3


def identity_fragments() -> tuple[str, ...]:
    """The current user name, host name and home path: values that must never reach a record."""
    candidates: list[str] = []
    for reader in (getpass.getuser, socket.gethostname, lambda: str(Path.home())):
        try:
            candidates.append(str(reader()))
        except (OSError, KeyError, RuntimeError, ImportError):
            continue  # intentional: an unknown identity cannot leak; the other fragments still apply
    for name in ("USERNAME", "USER", "COMPUTERNAME", "HOSTNAME", "USERDOMAIN", "USERPROFILE", "HOME"):
        value = os.environ.get(name)
        if value:
            candidates.append(value)
    return tuple(dict.fromkeys(item for item in candidates if len(item) >= _MIN_FRAGMENT_CHARS))


@dataclass(frozen=True, slots=True)
class EnvironmentCapture:
    #: Validated facts, ready for `TestRun.environment`.
    facts: Mapping[str, Any]
    #: (name, reason) for each fact not recorded: `probe_failed`, `unavailable`, `invalid`, `identifying`.
    omitted: tuple[tuple[str, str], ...] = ()


def capture_environment(probe: EnvironmentProbe = EnvironmentProbe(), *,
                        fragments: Iterable[str] | None = None) -> EnvironmentCapture:
    """Non-identifying execution facts. Never the home path, host name, user name, account or network ids.

    Only the closed `ENVIRONMENT_FACTS` names are emitted. Any value containing
    an identity fragment (case-insensitive) is dropped, whatever the probe returned.
    """
    lowered = [item.casefold() for item in (identity_fragments() if fragments is None else fragments)
               if len(item) >= _MIN_FRAGMENT_CHARS]
    facts: dict[str, Any] = {}
    omitted: list[tuple[str, str]] = []
    for name, attribute in ENVIRONMENT_FACTS.items():
        try:
            value = getattr(probe, attribute)()
        except Exception:
            # Capture as an omission: a probe failing on an exotic platform must not
            # fail the run; the reason is recorded next to the facts.
            omitted.append((name, "probe_failed"))
            continue
        if value is None or value == "":
            omitted.append((name, "unavailable"))
            continue
        try:
            check_open_key(name, "environment")
            check_scalar_value(value, f"environment.{name}")
        except TestLabError:
            omitted.append((name, "invalid"))
            continue
        if isinstance(value, str) and any(fragment in value.casefold() for fragment in lowered):
            omitted.append((name, "identifying"))
            continue
        facts[name] = value
    return EnvironmentCapture(MappingProxyType(facts), tuple(omitted))


# ------------------------------------------------------- config snapshot

CONFIG_SNAPSHOT_SCHEMA = "jarvis.testlab.config_snapshot"
CONFIG_SNAPSHOT_SCHEMA_VERSION = 1
CONFIG_SNAPSHOT_PATH = "config_snapshot.json"
CONFIG_SNAPSHOT_MEDIA_TYPE = "application/json"
MAX_CONFIG_SNAPSHOT_BYTES = 1024 * 1024
MAX_CONFIG_DEPTH = 16


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    """Redacted effective configuration of a run. `fingerprint` goes to `TestRun.config_fingerprint`."""

    document: Mapping[str, Any]
    fingerprint: str
    #: How many values were replaced by `<redacted>`, plus URLs stripped, SSH users dropped and emails replaced.
    redacted: int = 0
    encoded: bytes = field(default=b"", repr=False)


def _replace_home(text: str, homes: tuple[str, ...]) -> str:
    for home in homes:
        text = re.sub(re.escape(home), "~", text, flags=re.IGNORECASE)
    return text


def build_config_snapshot(settings: Mapping[str, Any] | Any, *, home: Path | None = None) -> ConfigSnapshot:
    """Normalize, redact and fingerprint an effective configuration (a mapping or a dataclass such as `V2Settings`).

    - a key the Test Lab name rule marks private (secrets, prompts, hidden
      reasoning, raw audio) keeps its key but its non-empty value becomes
      `<redacted>`: presence stays comparable, the secret is never written;
    - `Path` and `Enum` values become text; the home directory in any text
      becomes `~` (pass `home=None` to use the current user's home);
    - every URL in a text value keeps only `scheme://host[:port]/path`
      (userinfo, query and fragment are removed, `redact_urls`); SSH remotes
      drop their user; email addresses become `<email>` (`redact_identifying_text`);
    - raw bytes and non-JSON values are refused.

    The fingerprint covers the redacted document: hashing secret values would
    turn every record into an offline guessing oracle for them.
    """
    if home is None:
        try:
            home = Path.home()
        except RuntimeError:
            home = None  # intentional: no resolvable home, nothing to replace
    homes: tuple[str, ...] = ()
    if home is not None and len(str(home)) >= _MIN_FRAGMENT_CHARS:
        homes = tuple(dict.fromkeys((str(home), str(home).replace("\\", "/"))))
    redacted = 0

    def normalize(value: Any, path: str, depth: int) -> Any:
        nonlocal redacted
        if depth > MAX_CONFIG_DEPTH:
            raise fail(f"{path}: configuration nesting exceeds {MAX_CONFIG_DEPTH} levels", LIMIT_EXCEEDED)
        if is_dataclass(value) and not isinstance(value, type):
            value = {item.name: getattr(value, item.name) for item in fields(value)}
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise fail(f"{path}: configuration keys must be strings")
                where = f"{path}.{name_for_message(key)}"
                if is_private_key(key):
                    if item in (None, "", [], {}, ()):
                        result[key] = item if not isinstance(item, tuple) else []
                    else:
                        result[key] = REDACTED
                        redacted += 1
                    continue
                result[key] = normalize(item, where, depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [normalize(item, f"{path}[{index}]", depth + 1) for index, item in enumerate(value)]
        if isinstance(value, Enum):
            return normalize(value.value, path, depth)
        if isinstance(value, PurePath):
            return _replace_home(str(value), homes)
        if isinstance(value, (bytes, bytearray, memoryview)):
            raise TestLabRedactionError(FORBIDDEN_PRIVATE_DATA, f"{path}: raw bytes are forbidden")
        if isinstance(value, str):
            text, urls = redact_identifying_text(value)
            redacted += urls
            return _replace_home(text, homes)
        if value is None or type(value) in (bool, int):
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise fail(f"{path}: configuration numbers must be finite")
            return value
        raise fail(f"{path}: configuration value is not JSON data")

    document = {
        "schema": CONFIG_SNAPSHOT_SCHEMA,
        "schema_version": CONFIG_SNAPSHOT_SCHEMA_VERSION,
        "settings": normalize(settings, "settings", 0),
    }
    encoded = canonical_json(document).encode("utf-8")
    if len(encoded) > MAX_CONFIG_SNAPSHOT_BYTES:
        raise fail(f"configuration snapshot exceeds {MAX_CONFIG_SNAPSHOT_BYTES} bytes", LIMIT_EXCEEDED)
    return ConfigSnapshot(document=document, fingerprint=content_fingerprint(document), redacted=redacted,
                          encoded=encoded)


def store_config_snapshot(store: TestRunStore, run_id: str, snapshot: ConfigSnapshot) -> ArtifactRef:
    """Write the snapshot as the run's `config_snapshot` artifact; the caller adds the ref to the record."""
    return store.put_artifact(run_id, CONFIG_SNAPSHOT_PATH, kind=ArtifactKind.CONFIG_SNAPSHOT,
                              media_type=CONFIG_SNAPSHOT_MEDIA_TYPE, data=snapshot.encoded)


# -------------------------------------------------------- captured evidence

#: A word long enough to be a credential, checked against the canonical
#: `SECRET_PREFIXES` of `conversation_event_trace` (imported, never copied).
#: The 8-character minimum is deliberate: it keeps ordinary prose intact, and it
#: means a very short secret (`sk-ab`) is not caught by this pass. Short secrets
#: are the name rule's job, not a text scan's.
_SECRET_WORD = re.compile(r"[A-Za-z0-9_.\-]{8,}")
#: A hexadecimal blob: a token, a key or a hash, none of which belongs in evidence.
_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{32,}\b")
#: `Authorization:` (with or without a scheme) and the bare `Bearer`/`Basic`
#: schemes: what follows is the credential, whatever its own shape.
_AUTH_HEADER = re.compile(r"(?i)\b(authorization\s*[:=]\s*)((?:bearer|basic|token)\s+)?(\S+)")
#: A bare scheme has no header to disambiguate it, so the value must be at least 8
#: characters: a credential never is 6 ("basic checks passed" stays prose).
_AUTH_SCHEME = re.compile(r"(?i)\b(bearer|basic)(\s+)(\S{8,})")
#: `name=value` / `name: value` where the NAME says the value is a credential.
#: `token` is only an introducer with a separator, so "the token budget is 500" stays prose.
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b((?:api[-_]?key|apikey|secret|password|passwd|token|auth[-_]?token|access[-_]?token|"
    r"refresh[-_]?token|client[-_]?secret)\s*[:=]\s*)(\S+)")


def redact_evidence(text: str) -> str:
    """Everything captured worker output must lose: identity, home path, credentials.

    Four passes, in order: identifying text (URL credentials, SSH users, emails)
    through `redact_identifying_text`; the current user, host and home fragments;
    the value FOLLOWING a credential-introducing token (`Authorization:`,
    `Bearer`, `Basic`, `api_key=`, `password:` …), because a credential has no
    shape of its own — a real worker printed `Bearer QABEARERTOKEN` and the token
    survived every shape-based rule; then any word whose own shape is a credential
    (`SECRET_PREFIXES`) or a hexadecimal blob.

    A worker's stderr is arbitrary text: a traceback can carry the very key its
    provider call refused.
    """
    redacted, _ = redact_identifying_text(str(text))
    for fragment in identity_fragments():
        redacted = redacted.replace(fragment, REDACTED)
    redacted = _AUTH_HEADER.sub(lambda match: f"{match.group(1)}{match.group(2) or ''}{REDACTED}", redacted)
    redacted = _AUTH_SCHEME.sub(lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", redacted)
    redacted = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)
    redacted = _SECRET_WORD.sub(
        lambda match: REDACTED if match.group(0).lower().startswith(SECRET_PREFIXES) else match.group(0), redacted)
    return _LONG_HEX.sub(REDACTED, redacted)


def failure_detail(text: str, *, max_chars: int = MAX_FAILURE_DETAIL_CHARS) -> str:
    """A `RunFailure.detail`: one redacted, printable, bounded line, or a neutral fallback."""
    single = " ".join(redact_evidence(text).split())
    printable = "".join(char for char in single if char.isprintable())
    return printable[:max_chars].strip() or "no further detail"
