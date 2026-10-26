"""Lanceur unique du produit installé : `python -B -m jarvis launch` (Slice 07, `docs/product-install.md` › *Launcher*).

Le raccourci du menu Démarrer lance `runtime\\python\\pythonw.exe -B -m jarvis launch` : aucune console. Le lanceur :

1. vérifie l'installation (marqueur, `LOCALAPPDATA`) et crée la maison du produit (`data\\`, `runtime\\`, `config\\`,
   I-002 point 3) ; un refus est **visible** (boîte de dialogue sans console) et **durable**
   (`runtime\\logs\\launcher.log`, `errors.jsonl` ; `%TEMP%\\jarvis-launcher-error.log` quand la maison est
   introuvable : I-002 point 4) ;
2. garde **une seule instance** par utilisateur (`runtime\\launcher.lock`) : un second clic rouvre la page ;
3. démarre Core, attend `/v1/health`, puis le Control Center, attend sa page, puis la Voix (facultative) ; chaque
   enfant est lancé avec `-B` (aucun bytecode écrit dans le dossier du programme, `docs/windows-packaging.md`), sa
   sortie dans `runtime\\logs\\<rôle>.log`, et **contenu dans un Job Object** `KILL_ON_JOB_CLOSE` : si le lanceur
   meurt, Windows arrête tout l'arbre (MCP, Remotion, CLI) ; aucun orphelin ;
4. ouvre la page dans le navigateur (`JARVIS_OPEN_BROWSER=0` : non) ; le Control Center, lui, n'ouvre rien ;
5. veille : un enfant essentiel mort est relancé (au plus `MAX_RESTARTS` fois en `RESTART_WINDOW_S`), au-delà tout
   s'arrête et la cause est dite ; la Voix morte trop souvent est abandonnée sans emporter le reste ;
6. s'arrête proprement sur « Quitter JARVIS » (fichier `runtime\\launcher-stop.request`, écrit par
   `POST /api/product/quit`) ou Ctrl+C : Control Center et Voix d'abord, Core ensuite, puis le Job ferme le reste.

Variables (tests, administration) : `JARVIS_LAUNCH_VOICE=0` (pas de Voix), `JARVIS_LAUNCHER_START_TIMEOUT_S`,
plus celles de Core et du Control Center, transmises telles quelles.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, TextIO
import urllib.error
import urllib.request
import webbrowser

from jarvis.installation import Installation, detect_installation

STATE_FILE = "launcher.json"
STOP_FILE = "launcher-stop.request"
LOCK_FILE = "launcher.lock"
LOG_DIR = "logs"
STATE_SCHEMA = "jarvis.launcher-state"
FALLBACK_LOG = "jarvis-launcher-error.log"
MAX_RESTARTS = 3
RESTART_WINDOW_S = 120.0
DEFAULT_START_TIMEOUT_S = 120.0
POLL_S = 0.5
STOP_GRACE_S = 10.0
CREATE_NO_WINDOW = 0x08000000
TITLE = "JARVIS"


class LaunchError(RuntimeError):
    """Refus de démarrer : `code` stable, message en mots de produit, `detail` technique pour le journal."""

    def __init__(self, code: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------- avis visibles et durables


def default_notify(title: str, text: str) -> None:
    """Sans console (`pythonw.exe`) : une boîte de dialogue Windows ; avec console : la sortie d'erreur.
    `JARVIS_LAUNCHER_NOTIFY=stderr` (tests, essais sans surveillance) : jamais de boîte de dialogue."""

    quiet = os.environ.get("JARVIS_LAUNCHER_NOTIFY", "").strip().lower() == "stderr"
    if quiet or (sys.stderr is not None and getattr(sys.stderr, "isatty", lambda: False)()):
        if sys.stderr is not None:
            if quiet and hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # redirected console: cp1252 otherwise
            print(f"{title} : {text}", file=sys.stderr)
        return
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 | 0x40000)  # MB_ICONERROR | MB_TOPMOST
    elif sys.stderr is not None:
        print(f"{title} : {text}", file=sys.stderr)


class LauncherLog:
    """`runtime\\logs\\launcher.log` (une ligne JSON par événement) + `errors.jsonl` par le journal du runtime."""

    def __init__(self, path: Path, journal: Any | None = None) -> None:
        self.path = path
        self.journal = journal

    def emit(self, kind: str, message: str, *, level: str = "info", **data: Any) -> None:
        row = {"ts": utc_now(), "kind": kind, "level": level, "message": message, "data": data}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass  # intentional: the journal below (and the visible notice) still carry the event
        if self.journal is not None:
            try:
                self.journal.emit(f"launcher.{kind}", message, level=level, data=data)
            except OSError:
                pass  # intentional: launcher.log above already holds it


def fallback_log(exc: BaseException) -> Path:
    """Refus avant toute maison connue : `%TEMP%\\jarvis-launcher-error.log`."""

    path = Path(tempfile.gettempdir()) / FALLBACK_LOG
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": utc_now(), "kind": "launcher.refused", "level": "error",
                                     "message": str(exc), "exception_type": type(exc).__name__},
                                    ensure_ascii=False) + "\n")
    except OSError:
        pass  # intentional: the visible notice is the remaining channel
    return path


# ---------------------------------------------------------------------- instance unique


class InstanceLock:
    """Verrou d'une instance par maison (`msvcrt.locking`, libéré par Windows à la mort du processus)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover - V1 is Windows-first
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass  # intentional: closing the handle releases the lock anyway
        handle.close()


# ---------------------------------------------------------------------- enfants


@dataclass
class Role:
    name: str
    args: tuple[str, ...]
    essential: bool
    env: Mapping[str, str] = field(default_factory=dict)
    process: Any = None
    tree: Any = None
    log: TextIO | None = None
    restarts: list[float] = field(default_factory=list)
    abandoned: bool = False
    last_exit: int | None = None


def owned_tree_factory() -> Any | None:
    """Un Job Object `KILL_ON_JOB_CLOSE` par enfant (`owned_process_tree.OwnedProcessTree`), `None` hors Windows."""

    if os.name != "nt":
        return None
    from jarvis.runtime.owned_process_tree import OwnedProcessTree

    return OwnedProcessTree()


def tail(path: Path, lines: int = 12) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.strip().splitlines()[-lines:])


@dataclass
class LaunchPlan:
    """Ce que le lanceur démarre et où il le surveille (construit par `plan_from_environment`)."""

    python: str
    runtime_root: Path
    core_url: str
    ui_url: str
    token_file: Path
    roles: list[Role]
    env: dict[str, str]
    start_timeout_s: float = DEFAULT_START_TIMEOUT_S
    open_browser: bool = True


def plan_from_environment(environ: Mapping[str, str] | None = None) -> LaunchPlan:
    from jarvis.v2_config import V2Settings

    env = dict(os.environ if environ is None else environ)
    settings = V2Settings.load()
    ui_port = int(env.get("JARVIS_UI_PORT") or 17654)
    base = {**env, "PYTHONIOENCODING": "utf-8"}
    roles = [Role("core", ("core",), True), Role("ui", ("control-center",), True, {"JARVIS_OPEN_BROWSER": "0"})]
    if str(env.get("JARVIS_LAUNCH_VOICE", "1")).strip().lower() not in {"0", "false", "no", "off"}:
        roles.append(Role("voice", ("voice",), False))
    try:
        timeout = float(env.get("JARVIS_LAUNCHER_START_TIMEOUT_S") or DEFAULT_START_TIMEOUT_S)
    except ValueError:
        timeout = DEFAULT_START_TIMEOUT_S
    opened = str(env.get("JARVIS_OPEN_BROWSER", "1")).strip().lower() not in {"0", "false", "no", "off"}
    return LaunchPlan(python=sys.executable, runtime_root=settings.runtime_root,
                      core_url=f"http://{settings.core_host}:{settings.core_port}",
                      ui_url=f"http://127.0.0.1:{ui_port}/", token_file=settings.token_file, roles=roles, env=base,
                      start_timeout_s=timeout if timeout > 0 else DEFAULT_START_TIMEOUT_S, open_browser=opened)


def http_ok(url: str, *, headers: Mapping[str, str] | None = None, timeout_s: float = 3.0) -> tuple[bool, Any]:
    request = urllib.request.Request(url, headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - loopback only
            body = response.read(256 * 1024)
            return 200 <= response.status < 300, body
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, exc


class Launcher:
    def __init__(self, plan: LaunchPlan, *, log: LauncherLog, notify: Callable[[str, str], None] = default_notify,
                 open_url: Callable[[str], Any] = webbrowser.open, spawn: Callable[..., Any] = subprocess.Popen,
                 tree_factory: Callable[[], Any] = owned_tree_factory, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, probe: Callable[..., tuple[bool, Any]] = http_ok) -> None:
        self.plan = plan
        self.log = log
        self.notify = notify
        self.open_url = open_url
        self.spawn = spawn
        self.tree_factory = tree_factory
        self.clock = clock
        self.sleep = sleep
        self.probe = probe
        self.stop_path = plan.runtime_root / STOP_FILE
        self.state_path = plan.runtime_root / STATE_FILE
        self.stopping = False

    # ------------------------------------------------------------------ état publié

    def write_state(self) -> None:
        state = {"schema": STATE_SCHEMA, "schema_version": 1, "pid": os.getpid(), "started_at": utc_now(),
                 "ui_url": self.plan.ui_url,
                 "roles": {role.name: {"pid": getattr(role.process, "pid", None), "abandoned": role.abandoned,
                                       "last_exit": role.last_exit} for role in self.plan.roles}}
        temp = self.state_path.with_name(STATE_FILE + ".tmp")
        temp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.state_path)

    def clear_state(self) -> None:
        for path in (self.state_path, self.stop_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass  # intentional: already gone
            except OSError as exc:
                self.log.emit("state_cleanup_failed", f"{path.name} non effacé : {exc}", level="warning")

    # ------------------------------------------------------------------ enfants

    def start_role(self, role: Role) -> None:
        log_path = self.plan.runtime_root / LOG_DIR / f"{role.name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if role.log is not None:
            role.log.close()
        role.log = open(log_path, "a", encoding="utf-8")
        role.log.write(f"\n===== {utc_now()} lancement de {role.name} =====\n")
        role.log.flush()
        tree = self.tree_factory()
        flags = (getattr(tree, "creationflags", 0) or 0) | (CREATE_NO_WINDOW if os.name == "nt" else 0)
        argv = [self.plan.python, "-B", "-m", "jarvis", *role.args]
        try:
            process = self.spawn(argv, env={**self.plan.env, **role.env}, stdin=subprocess.DEVNULL, stdout=role.log,
                                 stderr=subprocess.STDOUT, creationflags=flags)
        except OSError as exc:
            raise LaunchError("child_unstartable", f"JARVIS n'a pas pu démarrer ({role.name}).",
                              f"{type(exc).__name__}: {exc}") from exc
        if tree is not None:
            try:
                tree.attach_and_resume(process.pid)
            except OSError as exc:
                process.kill()
                raise LaunchError("child_uncontained", f"JARVIS n'a pas pu démarrer ({role.name}).",
                                  f"job object: {exc}") from exc
        role.process, role.tree = process, tree
        self.log.emit("child_started", f"{role.name} lancé", role=role.name, pid=process.pid)

    def wait_ready(self, role: Role, url: str, *, headers: Callable[[], Mapping[str, str]] | None = None) -> None:
        deadline = self.clock() + self.plan.start_timeout_s
        started = self.clock()
        last: Any = None
        while self.clock() < deadline:
            if self.stop_requested():
                raise LaunchError("stopped_during_start", "Arrêt demandé pendant le démarrage.")
            code = role.process.poll()
            if code is not None:
                role.last_exit = code
                raise LaunchError("child_exited", self._exit_sentence(role),
                                  f"{role.name} exited with {code}: {tail(self._log_path(role), 6)}")
            ok, last = self.probe(url, headers=headers() if headers else None)
            if ok:
                self.log.emit("child_ready", f"{role.name} prêt en {self.clock() - started:.1f} s", role=role.name)
                return
            self.sleep(POLL_S)
        raise LaunchError("start_timeout", f"JARVIS n'a pas démarré en {self.plan.start_timeout_s:.0f} secondes ({role.name}).",
                          f"last probe: {last!r}"[:300])

    def _log_path(self, role: Role) -> Path:
        return self.plan.runtime_root / LOG_DIR / f"{role.name}.log"

    def _exit_sentence(self, role: Role) -> str:
        text = tail(self._log_path(role), 40)
        if "cannot bind" in text or "Errno 10048" in text or "address already in use" in text.lower():
            return ("JARVIS est peut-être déjà ouvert, ou une autre application utilise son port. "
                    "Fermez-la puis relancez JARVIS.")
        return f"Une partie de JARVIS ({role.name}) s'est arrêtée au démarrage."

    def core_headers(self) -> dict[str, str]:
        try:
            token = self.plan.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            return {}
        return {"Authorization": f"Bearer {token}"} if token else {}

    def stop_requested(self) -> bool:
        return self.stop_path.exists()

    def may_restart(self, role: Role) -> bool:
        now = self.clock()
        role.restarts = [at for at in role.restarts if now - at < RESTART_WINDOW_S]
        if len(role.restarts) >= MAX_RESTARTS:
            return False
        role.restarts.append(now)
        return True

    # ------------------------------------------------------------------ cycle

    def start_all(self) -> None:
        core, ui = self.plan.roles[0], self.plan.roles[1]
        self.start_role(core)
        self.wait_ready(core, self.plan.core_url + "/v1/health", headers=self.core_headers)
        self.start_role(ui)
        self.wait_ready(ui, self.plan.ui_url + "api/status")
        for role in self.plan.roles[2:]:
            self.start_role(role)
        self.write_state()
        if self.plan.open_browser:
            self.open_url(self.plan.ui_url)
        else:
            self.log.emit("browser_not_opened", "page non ouverte (JARVIS_OPEN_BROWSER=0)", url=self.plan.ui_url)

    def watch(self) -> int:
        while not self.stopping:
            if self.stop_requested():
                self.log.emit("stop_requested", "Arrêt demandé (Quitter JARVIS)")
                return 0
            for role in self.plan.roles:
                if role.abandoned or role.process is None:
                    continue
                code = role.process.poll()
                if code is None:
                    continue
                role.last_exit = code
                self.log.emit("child_exited", f"{role.name} arrêté (code {code})", level="warning" if role.essential else "info",
                              role=role.name, exit_code=code, tail=tail(self._log_path(role), 6))
                self._close_tree(role)
                if not self.may_restart(role):
                    if role.essential:
                        raise LaunchError("child_crash_loop", f"JARVIS s'est arrêté : {role.name} redémarrait sans cesse.",
                                          tail(self._log_path(role), 12))
                    role.abandoned = True
                    self.log.emit("child_abandoned", f"{role.name} abandonné après {MAX_RESTARTS} arrêts", level="warning",
                                  role=role.name)
                    self.write_state()
                    continue
                self.start_role(role)
                if role.name == "core":
                    self.wait_ready(role, self.plan.core_url + "/v1/health", headers=self.core_headers)
                self.write_state()
            self.sleep(POLL_S)
        return 0

    def _close_tree(self, role: Role) -> None:
        tree, role.tree = role.tree, None
        if tree is None:
            return
        try:
            tree.terminate()
        except OSError as exc:
            self.log.emit("job_terminate_failed", f"{role.name} : {exc}", level="warning", role=role.name)
        for _ in range(20):
            try:
                if tree.close_if_empty():
                    return
            except OSError as exc:
                self.log.emit("job_close_failed", f"{role.name} : {exc}", level="warning", role=role.name)
                return
            self.sleep(0.1)

    def stop_all(self) -> None:
        self.stopping = True
        order = [role for role in self.plan.roles if role.name != "core"] + [r for r in self.plan.roles if r.name == "core"]
        for role in order:
            process = role.process
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=STOP_GRACE_S)
                except subprocess.TimeoutExpired:
                    process.kill()
                except OSError as exc:
                    self.log.emit("child_stop_failed", f"{role.name} : {exc}", level="warning", role=role.name)
            self._close_tree(role)
            if role.log is not None:
                role.log.close()
                role.log = None
            self.log.emit("child_stopped", f"{role.name} arrêté", role=role.name)

    def run(self) -> int:
        try:
            self.stop_path.unlink(missing_ok=True)
            self.start_all()
            return self.watch()
        except LaunchError as exc:
            self.log.emit("failed", str(exc), level="error", code=exc.code, detail=exc.detail[:2000])
            self.notify(TITLE, f"{exc}\n\nDétails : {self.plan.runtime_root / LOG_DIR / 'launcher.log'}")
            return 1
        except KeyboardInterrupt:
            self.log.emit("interrupted", "Arrêt par Ctrl+C")
            return 130
        finally:
            self.stop_all()
            self.clear_state()


def ensure_home(installation: Installation) -> list[str]:
    """Crée `data\\`, `runtime\\`, `config\\` sous la maison du produit (produit installé seulement)."""

    home = installation.home
    if home is None:
        return []
    created = []
    for name, path in (("data", home.data), ("runtime", home.runtime), ("config", home.config)):
        if not path.is_dir():
            path.mkdir(parents=True, exist_ok=True)
            created.append(name)
    return created


def reopen_running(runtime_root: Path, *, open_url: Callable[[str], Any]) -> bool:
    try:
        state = json.loads((runtime_root / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    url = state.get("ui_url") if isinstance(state, dict) else None
    if isinstance(url, str) and url.startswith("http://127.0.0.1:"):
        open_url(url)
        return True
    return False


def main(*, notify: Callable[[str, str], None] = default_notify, environ: Mapping[str, str] | None = None) -> int:
    """Point d'entrée de `python -m jarvis launch`. Ne lève jamais : chaque refus est vu et écrit."""

    try:
        installation = detect_installation(os.environ if environ is None else environ)
        created = ensure_home(installation)
        plan = plan_from_environment(environ)
    except Exception as exc:  # noqa: BLE001 - surfaced: visible notice + %TEMP% log, then exit 1
        where = fallback_log(exc)
        notify(TITLE, f"JARVIS ne peut pas démarrer : {exc}\n\nDétails : {where}")
        return 1
    from jarvis.runtime.journal import RuntimeJournal

    plan.runtime_root.mkdir(parents=True, exist_ok=True)
    log = LauncherLog(plan.runtime_root / LOG_DIR / "launcher.log", RuntimeJournal(plan.runtime_root))
    log.emit("start", "Lanceur démarré", mode=installation.mode.value, created=created, pid=os.getpid())
    lock = InstanceLock(plan.runtime_root / LOCK_FILE)
    if not lock.acquire():
        reopened = reopen_running(plan.runtime_root, open_url=webbrowser.open if plan.open_browser else (lambda _url: None))
        opened = reopened and plan.open_browser
        log.emit("already_running", "JARVIS est déjà ouvert : page rouverte" if opened else
                 "JARVIS est déjà ouvert (page non rouverte : JARVIS_OPEN_BROWSER=0)" if reopened else "JARVIS démarre déjà",
                 reopened=opened)
        return 0
    try:
        return Launcher(plan, log=log, notify=notify).run()
    finally:
        lock.release()
        log.emit("exit", "Lanceur arrêté")
