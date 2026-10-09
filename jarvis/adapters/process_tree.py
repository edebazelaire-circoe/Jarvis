"""Processus enfants bornés : exécution avec délai, arrêt de l'arbre entier, vivacité fiable.

Seul endroit qui lance ou tue un processus pour les capacités locales
(`docs/local-capabilities.md` §4, `docs/remotion-runtime.md`). Sous Windows,
`Popen.kill()` ne tue que le processus direct : `npm.cmd`, `node` et leurs
petits-enfants survivraient. On tue donc l'arbre par `taskkill /T /F`. Une
référence de processus est `pid:début` (heure de création) pour qu'un pid
réutilisé par un autre programme ne passe jamais pour notre enfant.

Aucun secret : l'environnement de l'enfant est une liste blanche (`clean_env`).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

IS_WINDOWS = sys.platform == "win32"
#: Variables que l'enfant a le droit de voir : rien de ce qui ressemble à un secret de Jarvis.
ENV_ALLOWLIST = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "HOME",
                 "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "PROGRAMFILES",
                 "PROGRAMFILES(X86)", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS", "LANG", "LC_ALL", "TZ",
                 "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS")
OUTPUT_TAIL_LINES = 80
KILL_GRACE_S = 3.0


def clean_env(extra: Mapping[str, str] | None = None, *, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    wanted = {name.upper() for name in ENV_ALLOWLIST}
    env = {key: value for key, value in source.items() if key.upper() in wanted}
    env.update(extra or {})
    return env


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    output: str  # fin de la sortie standard+erreur, bornée
    timed_out: bool
    duration_s: float
    started: bool = True


def _creationflags() -> int:
    if not IS_WINDOWS:
        return 0
    return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW


def kill_tree(pid: int) -> bool:
    """Tue le processus et tous ses descendants ; rend vrai si l'arbre n'existe plus."""

    if pid <= 0:
        return True
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=20,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + KILL_GRACE_S
    while time.monotonic() < deadline:
        if not pid_exists(pid):
            return True
        time.sleep(0.1)
    return not pid_exists(pid)


def run_bounded(argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout_s: float,
                on_start: Callable[[int], None] | None = None) -> ProcessResult:
    """Lance, attend au plus `timeout_s`, tue l'arbre au dépassement. Ne lève que si le lancement lui-même échoue."""

    start = time.monotonic()
    tail: deque[str] = deque(maxlen=OUTPUT_TAIL_LINES)
    try:
        proc = subprocess.Popen(list(argv), cwd=str(cwd), env=dict(env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, creationflags=_creationflags(), start_new_session=not IS_WINDOWS,
                                text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        return ProcessResult(None, f"{type(exc).__name__}: {exc}", False, time.monotonic() - start, started=False)
    if on_start is not None:
        on_start(proc.pid)

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            tail.append(line.rstrip("\r\n")[:400])

    reader = threading.Thread(target=pump, name="process-output", daemon=True)
    reader.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc.pid)
        try:
            proc.wait(timeout=KILL_GRACE_S)
        except subprocess.TimeoutExpired:  # pragma: no cover - taskkill /F failed
            proc.kill()
    except BaseException:
        kill_tree(proc.pid)  # interruption du thread appelant : jamais d'enfant laissé derrière
        raise
    reader.join(timeout=KILL_GRACE_S)
    return ProcessResult(proc.returncode, "\n".join(tail), timed_out, time.monotonic() - start)


def spawn_detached(argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], log_path: Path) -> int:
    """Lance un enfant de longue durée (sortie dans `log_path`) ; rend son pid."""

    with open(log_path, "ab") as log:
        proc = subprocess.Popen(list(argv), cwd=str(cwd), env=dict(env), stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=_creationflags(), start_new_session=not IS_WINDOWS)
    return proc.pid


# ------------------------------------------------------------- vivacité d'un pid

def _windows_open(pid: int):
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000 | 0x0400, False, pid)  # QUERY_LIMITED_INFORMATION | QUERY_INFORMATION
    return kernel32, handle


def _windows_start_time(pid: int) -> str | None:
    """Heure de création (FILETIME) si le processus existe ET n'est pas terminé, sinon None."""

    import ctypes
    from ctypes import wintypes
    kernel32, handle = _windows_open(pid)
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return None
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
    finally:
        kernel32.CloseHandle(handle)


def _posix_start_time(pid: int) -> str | None:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    try:  # Linux : champ 22 de /proc/<pid>/stat ; ailleurs, le pid seul fait foi
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return stat.rsplit(")", 1)[1].split()[19]
    except OSError:
        return "0"


def pid_exists(pid: int) -> bool:
    return (_windows_start_time(pid) if IS_WINDOWS else _posix_start_time(pid)) is not None


def make_process_ref(pid: int) -> str:
    started = (_windows_start_time(pid) if IS_WINDOWS else _posix_start_time(pid)) or "0"
    return f"{pid}:{started}"


def parse_process_ref(ref: str) -> tuple[int, str] | None:
    pid, _, started = str(ref).partition(":")
    if not pid.isdigit() or int(pid) <= 0 or not started:
        return None
    return int(pid), started


def ref_alive(ref: str) -> bool:
    """Vrai seulement si ce pid existe encore avec la MÊME heure de création."""

    parsed = parse_process_ref(ref)
    if parsed is None:
        return False
    pid, started = parsed
    now = _windows_start_time(pid) if IS_WINDOWS else _posix_start_time(pid)
    return now is not None and now == started
