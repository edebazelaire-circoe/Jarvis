"""Processus enfants bornés : exécution avec délai, arrêt de l'arbre entier, vivacité fiable.

Seul endroit qui lance ou tue un processus pour les capacités locales
(`docs/local-capabilities.md` §4, `docs/remotion-runtime.md`). Sous Windows,
`Popen.kill()` ne tue que le processus direct : `npm.cmd`, `node` et leurs
petits-enfants survivraient. On tue donc l'arbre, mais jamais par
`taskkill /T` : Windows ne rafraîchit pas le PID parent d'un orphelin, et
`/T` tuerait un processus étranger dont le PPID périmé égale un PID vivant.
L'arbre est parcouru ici : un enfant n'en fait partie que s'il est né après
son parent (heure de création), et chaque processus est tué par une poignée
ouverte après relecture de son identité. Une référence de processus est
`pid:début` (heure de création) pour qu'un pid réutilisé par un autre
programme ne passe jamais pour notre enfant ; `kill_tree(pid, started=…)`
refuse de suivre un pid dont l'heure de création a changé.

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

from jarvis import private_runtime

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
    # Produit installé : le Node privé du paquet passe devant le PATH du poste (`docs/windows-packaging.md`) ;
    # inchangé dans un checkout de développement.
    path_key = next((key for key in env if key.upper() == "PATH"), "PATH")
    env[path_key] = private_runtime.child_path(env.get(path_key, ""))
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


def _windows_parent_table() -> list[tuple[int, int]]:
    """(pid, ppid) de chaque processus du poste, par un instantané Toolhelp ; [] si l'instantané échoue."""

    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return []
    rows: list[tuple[int, int]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return rows


def verified_descendants(pid: int, started: str, table: Sequence[tuple[int, int]],
                         born_of: Callable[[int], str | None]) -> list[tuple[int, str]]:
    """Descendants de `pid` (né à `started`) qu'un PPID périmé ne peut pas usurper : chaque enfant est né après son parent.

    Pur (la table et la lecture des heures sont injectées) : `born_of` rend l'heure de création comparable (FILETIME en
    entier décimal) ou None si le processus est parti. Ordre : du plus proche au plus lointain.
    """

    children: dict[int, list[int]] = {}
    for child, parent in table:
        if child != parent:
            children.setdefault(parent, []).append(child)
    found: list[tuple[int, str]] = []
    seen = {pid}
    queue: deque[tuple[int, str]] = deque([(pid, started)])
    while queue:
        parent, parent_born = queue.popleft()
        for child in children.get(parent, ()):
            if child in seen:
                continue
            born = born_of(child)
            if not born or not born.isdigit() or not parent_born.isdigit() or int(born) < int(parent_born):
                continue  # né avant son « parent » : orphelin dont le PPID a été réemployé, jamais suivi
            seen.add(child)
            found.append((child, born))
            queue.append((child, born))
    return found


def _windows_terminate_if(pid: int, started: str) -> None:
    """Tue `pid` par une poignée ouverte, seulement si son heure de création est toujours `started`."""

    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x0001 | 0x1000, False, pid)  # PROCESS_TERMINATE | QUERY_LIMITED_INFORMATION
    if not handle:
        return  # parti, ou inaccessible : rien à tuer sous notre identité
    try:
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            return
        if str((created.dwHighDateTime << 32) | created.dwLowDateTime) != started:
            return  # pid réemployé entre le parcours et l'arrêt
        kernel32.TerminateProcess(handle, 1)
    finally:
        kernel32.CloseHandle(handle)


def kill_tree(pid: int, started: str | None = None) -> bool:
    """Tue le processus et ses descendants vérifiés ; rend vrai si l'arbre n'existe plus.

    `started` (heure de création d'une référence `pid:début`) : si le pid vit sous une autre identité, rien n'est tué
    et l'arbre est tenu pour parti (le nôtre n'existe plus). Sans `started`, l'heure lue maintenant fait foi.
    """

    if pid <= 0:
        return True
    if IS_WINDOWS:
        root_born = _windows_start_time(pid)
        if root_born is None or (started is not None and root_born != started):
            return True  # parti, ou ce pid appartient désormais à un autre programme : on ne le suit jamais
        tree = [(pid, root_born), *verified_descendants(pid, root_born, _windows_parent_table(), _windows_start_time)]
        for member, born in tree:  # racine d'abord : elle ne relance plus d'enfant pendant qu'on tue les autres
            _windows_terminate_if(member, born)
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


def spawn_tracked(argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], log_path: Path) -> subprocess.Popen:
    """Comme `spawn_detached`, mais rend la poignée : l'appelant lit le code de sortie et ne peut pas confondre le pid avec un autre
    programme tant qu'il la tient (rendu Remotion, Slice 16)."""

    log = open(log_path, "ab")
    try:
        return subprocess.Popen(list(argv), cwd=str(cwd), env=dict(env), stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=_creationflags(), start_new_session=not IS_WINDOWS)
    finally:
        log.close()  # l'enfant a hérité de sa propre poignée


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
    try:  # Linux : champ 22 de /proc/<pid>/stat
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return stat.rsplit(")", 1)[1].split()[19]
    except OSError:
        pass
    try:  # macOS / BSD : `ps -o lstart=` (heure de lancement lisible)
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=10, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return out or ""  # "" = identité inconnue : jamais une valeur inventée


def pid_exists(pid: int) -> bool:
    return (_windows_start_time(pid) if IS_WINDOWS else _posix_start_time(pid)) is not None  # "" = existe, identité inconnue


def make_process_ref(pid: int) -> str:
    """`pid:début`, ou "" si l'identité du processus est introuvable (l'appelant refuse alors de le suivre, ni arrêt ni vivacité à l'aveugle)."""

    started = _windows_start_time(pid) if IS_WINDOWS else _posix_start_time(pid)
    return f"{pid}:{started}" if started else ""


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
    return bool(now) and now == started
