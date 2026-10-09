"""Runner réel du Studio Remotion optionnel (Slice 11 ; `docs/remotion-studio.md`).

Tout effet disque et processus du Studio passe ici. Il n'écrit que sous `<runtime>/studio/` (le dossier `runtime/` de la
capacité, `docs/remotion-runtime.md` §1) :

    studio/state.json          état persistant (service)
    studio/work/               le SEUL dossier que le Studio sert : copie matérialisée, en lecture seule, de la source d'une scène
    studio/work.files.json     empreintes de la dernière synchronisation (détecte une modification faite hors de Jarvis)
    studio/edits/<horodatage>/ copie des fichiers modifiés hors de Jarvis avant qu'une synchronisation les remplace
    studio/studio-guard.cjs    copie du garde livré (`jarvis/capabilities/remotion/studio-guard.cjs`), comparée à chaque lancement
    studio/studio.log          sortie du processus (plafonnée)
    studio/listening.json, activity.json   écrits par le garde dans le processus du Studio

Le processus est `node --require studio-guard.cjs @remotion/cli/remotion-cli.js studio ...`, cwd = `work/`, environnement en
liste blanche (`process_tree.clean_env` : aucune variable `JARVIS_*` sauf les deux identifiants de lancement, aucune clé, aucun
jeton), lancé sans fenêtre ni navigateur (`--no-open`). Aucune route de Core, aucune base, aucun Board n'est lisible depuis ce
dossier ; les écritures vers la bibliothèque de prefabs ne passent JAMAIS par ici (elles passent par `PrefabService`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import time
from urllib import request as urlrequest

from jarvis.adapters import process_tree
from jarvis.adapters.node_capability_runner import _remove_tree, extended_path
from jarvis.domain import remotion_studio as D
from jarvis.domain.remotion_studio import StudioError, StudioErrorCode as C
from jarvis.ports.remotion_studio import LaunchResult, SyncReport

CLI_ENTRY = Path("node_modules") / "@remotion" / "cli" / "remotion-cli.js"
SHIPPED_GUARD = Path(__file__).resolve().parents[1] / "capabilities" / "remotion" / D.GUARD_FILE
LOG_FILE = "studio.log"
LOG_MAX_BYTES = 1_000_000
STATE_FILE = "state.json"
MANIFEST_FILE = "work.files.json"
MAX_WORK_FILES = 400
MAX_WORK_BYTES = 64 * 1024 * 1024
STUDIO_NODE_FLAGS = ("--max-old-space-size=2048",)
HEALTH_PATH = "/__jarvis_studio__/health"
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _clear_readonly(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


class RemotionStudioRunner:
    def __init__(self, runtime_dir: Callable[[], Path], *, which: Callable[[str], str | None] = shutil.which,
                 environ: Mapping[str, str] | None = None, spawn=process_tree.spawn_detached, clock=time.monotonic,
                 sleep=time.sleep, start_timeout_s: float = D.START_TIMEOUT_S,
                 port_chooser: Callable[[], int] = free_loopback_port) -> None:
        self._runtime_dir = runtime_dir
        self._which = which
        self._environ = os.environ if environ is None else environ
        self._spawn = spawn
        self._clock = clock
        self._sleep = sleep
        self._start_timeout_s = start_timeout_s
        self._choose_port = port_chooser

    # ------------------------------------------------------------------ emplacements

    @property
    def _studio(self) -> Path:
        return Path(self._runtime_dir()) / D.STUDIO_DIR

    @property
    def _work(self) -> Path:
        return self._studio / D.WORK_DIR

    def configured_port(self) -> int | None:
        raw = self._environ.get("JARVIS_REMOTION_STUDIO_PORT", "").strip()
        if not raw:
            return None
        if not raw.isdigit() or not D.valid_port(int(raw)):
            raise StudioError(C.INVALID, f"JARVIS_REMOTION_STUDIO_PORT must be an integer between {D.MIN_PORT} and {D.MAX_PORT}")
        return int(raw)

    def runtime_ready(self) -> str | None:
        runtime = Path(self._runtime_dir())
        if self._which("node") is None:
            return "node_missing: Node.js is no longer on PATH"
        if not (runtime / CLI_ENTRY).is_file():
            return "cli_missing: @remotion/cli is not installed in the Remotion runtime; run repair"
        return None

    # ------------------------------------------------------------------ dossier de travail

    def _check_inside(self, target: Path) -> None:
        """`target` est dans `work/` et aucun de ses dossiers n'est un lien ou une jonction."""

        work = self._work
        try:
            relative = target.relative_to(work)
        except ValueError:
            raise StudioError(C.SYNC_FAILED, "a work file path leaves the work folder") from None
        current = work
        for part in relative.parts[:-1]:
            current = current / part
            try:
                info = os.lstat(extended_path(current))
            except FileNotFoundError:
                return
            if stat.S_ISLNK(info.st_mode) or (getattr(info, "st_file_attributes", 0) & 0x400):
                raise StudioError(C.SYNC_FAILED, "a work folder is a link: refused")

    def _scan_work(self) -> dict[str, str]:
        found: dict[str, str] = {}
        work = self._work
        if not work.is_dir():
            return found
        total = 0
        for root, dirs, files in os.walk(work):
            for name in list(dirs):
                info = os.lstat(Path(root) / name)
                if stat.S_ISLNK(info.st_mode) or (getattr(info, "st_file_attributes", 0) & 0x400):
                    found[(Path(root) / name).relative_to(work).as_posix() + "/"] = "link"
                    dirs.remove(name)
            for name in files:
                path = Path(root) / name
                info = os.lstat(path)
                relative = path.relative_to(work).as_posix()
                if stat.S_ISLNK(info.st_mode):
                    found[relative] = "link"
                    continue
                total += info.st_size
                if len(found) >= MAX_WORK_FILES or total > MAX_WORK_BYTES:
                    found["<too-many-files>"] = "bound"
                    return found
                found[relative] = _sha(path.read_bytes())
        return found

    def _manifest(self) -> dict[str, str]:
        try:
            raw = json.loads((self._studio / MANIFEST_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}

    def modified_work(self) -> tuple[str, ...]:
        if not self._work.is_dir():
            return ()
        try:
            disk, recorded = self._scan_work(), self._manifest()
        except OSError:
            return ()
        changed = [path for path in sorted(set(disk) | set(recorded)) if disk.get(path) != recorded.get(path)]
        return tuple(changed)

    def sync_work(self, files: Mapping[str, bytes]) -> SyncReport:
        studio, work = self._studio, self._work
        try:
            work.mkdir(parents=True, exist_ok=True)
            edited = self.modified_work()
            saved = self._save_edits(edited)
            disk = self._scan_work()
            wanted = {path: _sha(bytes(data)) for path, data in files.items()}
            written = unchanged = removed = 0
            temp = studio / ".tmp"
            temp.mkdir(exist_ok=True)
            for path in sorted(files):
                target = work.joinpath(*path.split("/"))
                self._check_inside(target)
                if disk.get(path) == wanted[path]:
                    unchanged += 1
                    continue
                staged = temp / f"{secrets.token_hex(6)}.part"
                staged.write_bytes(bytes(files[path]))
                os.chmod(staged, stat.S_IREAD)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    _clear_readonly(target)
                os.replace(staged, target)
                written += 1
            for path in sorted(set(disk) - set(files)):
                if path.endswith("/") or disk[path] in ("link", "bound"):
                    _remove_tree(work.joinpath(*path.rstrip("/").split("/")))
                    removed += 1
                    continue
                target = work.joinpath(*path.split("/"))
                _clear_readonly(target)
                _remove_tree(target)
                removed += 1
            self._prune_empty_dirs(work)
            shutil.rmtree(temp, ignore_errors=True)
            record = studio / (MANIFEST_FILE + ".tmp")
            record.write_text(json.dumps(wanted, sort_keys=True), encoding="utf-8")
            os.replace(record, studio / MANIFEST_FILE)
        except StudioError:
            raise
        except OSError as exc:
            raise StudioError(C.SYNC_FAILED, f"{type(exc).__name__}: the Studio work folder could not be written") from None
        return SyncReport(written, removed, unchanged, tuple(saved))

    @staticmethod
    def _prune_empty_dirs(root: Path) -> None:
        for current, dirs, _ in os.walk(root, topdown=False):
            for name in dirs:
                folder = Path(current) / name
                try:
                    folder.rmdir()  # ne réussit que si vide
                except OSError:
                    pass

    def _save_edits(self, edited: tuple[str, ...]) -> list[str]:
        """Copie les fichiers modifiés hors de Jarvis AVANT qu'une synchronisation les remplace : rien n'est perdu en silence."""

        saved = [path for path in edited if not path.endswith("/") and (self._work / path).is_file()]
        if not saved:
            return []
        edits = self._studio / "edits"
        destination = edits / (time.strftime("%Y%m%dT%H%M%S") + f"-{secrets.token_hex(2)}")
        for path in saved:
            target = destination.joinpath(*path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self._work / path, target)
        folders = sorted(item for item in edits.iterdir() if item.is_dir())
        for old in folders[: max(0, len(folders) - D.MAX_SAVED_EDITS)]:
            _remove_tree(old)
        return saved

    def save_modified(self) -> tuple[str, ...]:
        try:
            return tuple(self._save_edits(self.modified_work()))
        except OSError as exc:
            raise StudioError(C.SYNC_FAILED, f"{type(exc).__name__}: the modified Studio files could not be saved") from None

    # ------------------------------------------------------------------ processus

    def _copy_guard(self) -> Path:
        target = self._studio / D.GUARD_FILE
        data = SHIPPED_GUARD.read_bytes()
        if not target.is_file() or _sha(target.read_bytes()) != _sha(data):
            target.write_bytes(data)
        return target

    def _rotate_log(self) -> None:
        log = self._studio / LOG_FILE
        try:
            if log.stat().st_size > LOG_MAX_BYTES:
                os.replace(log, self._studio / (LOG_FILE + ".1"))
        except OSError:
            pass

    def _env(self, launch_id: str, idle_s: float) -> dict[str, str]:
        return process_tree.clean_env({"JARVIS_STUDIO_DIR": str(self._studio), "JARVIS_STUDIO_LAUNCH": launch_id, "NO_COLOR": "1",
                                       "JARVIS_STUDIO_PARENT": str(os.getpid()), "JARVIS_STUDIO_IDLE_S": str(int(idle_s)),
                                       "FORCE_COLOR": "0", "BROWSER": "none", "CI": "1"}, environ=self._environ)

    def launch(self, *, port: int | None, idle_s: float = D.DEFAULT_IDLE_TIMEOUT_S + D.IDLE_GUARD_MARGIN_S) -> LaunchResult:
        node = self._which("node")
        runtime = Path(self._runtime_dir())
        if node is None:
            raise StudioError(C.START_FAILED, "node_missing: Node.js is no longer on PATH")
        if not (runtime / CLI_ENTRY).is_file():
            raise StudioError(C.RUNTIME_UNAVAILABLE, "cli_missing: @remotion/cli is not installed; run repair")
        if not (self._work / D.WORK_ROOT_FILE).is_file():
            raise StudioError(C.START_FAILED, "work_missing: the Studio work folder is not materialised")
        if port is not None and not port_is_free(port):
            raise StudioError(C.PORT_UNAVAILABLE, f"port {port} is already in use on 127.0.0.1")
        chosen = port if port is not None else self._choose_port()
        guard = self._copy_guard()
        launch_id = secrets.token_hex(8)
        for stale in ("listening.json", "activity.json"):
            try:
                (self._studio / stale).unlink()
            except OSError:
                pass
        self._rotate_log()
        argv = [node, *STUDIO_NODE_FLAGS, "--require", str(guard), str((runtime / CLI_ENTRY).resolve()), "studio", D.WORK_ROOT_FILE,
                f"--port={chosen}", "--no-open", "--ipv4", "--disable-ask-ai", "--disable-git-source"]
        pid = self._spawn(argv, cwd=self._work, env=self._env(launch_id, idle_s), log_path=self._studio / LOG_FILE)
        try:
            self._wait_ready(pid, chosen, launch_id)
            ref = process_tree.make_process_ref(pid)
            if not ref:
                raise StudioError(C.START_FAILED, "process_identity_unavailable: the Studio start time could not be read")
        except BaseException:
            process_tree.kill_tree(pid)
            raise
        return LaunchResult(ref, chosen, launch_id)

    def _wait_ready(self, pid: int, port: int, launch_id: str) -> None:
        deadline = self._clock() + self._start_timeout_s
        last = "no answer yet"
        while self._clock() < deadline:
            if not process_tree.pid_exists(pid):
                raise StudioError(C.START_FAILED, f"process_exited: {self._tail_text()}")
            try:
                self.probe(port, launch_id)
                self._get_root(port)
                return
            except StudioError as exc:
                last = exc.detail
                if exc.code is C.HEALTH_FAILED and "another" in exc.detail:
                    raise
            self._sleep(0.4)
        raise StudioError(C.START_TIMEOUT, f"the Studio did not answer within {int(self._start_timeout_s)} s ({last}); {self._tail_text()}")

    @staticmethod
    def _opener():
        return urlrequest.build_opener(urlrequest.ProxyHandler({}))  # jamais le proxy d'environnement pour la boucle locale

    def probe(self, port: int, launch_id: str) -> None:
        try:
            with self._opener().open(f"http://127.0.0.1:{port}{HEALTH_PATH}", timeout=4) as response:  # noqa: S310 - loopback only
                body = json.loads(response.read(4096).decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise StudioError(C.HEALTH_FAILED, f"{type(exc).__name__}: no answer on the Studio port") from None
        if body.get("ok") is not True or body.get("launch") != launch_id:
            raise StudioError(C.HEALTH_FAILED, "another program answers on the Studio port (launch identifier differs)")

    def _get_root(self, port: int) -> None:
        try:
            with self._opener().open(f"http://127.0.0.1:{port}/", timeout=20) as response:  # noqa: S310 - loopback only
                head = response.read(2048).decode("utf-8", "replace")
                if response.status != 200 or "Remotion" not in head:
                    raise StudioError(C.HEALTH_FAILED, "the Studio page did not load")
        except OSError as exc:
            raise StudioError(C.HEALTH_FAILED, f"{type(exc).__name__}: the Studio page did not load") from None

    def is_alive(self, process_ref: str) -> bool:
        return process_tree.ref_alive(process_ref)

    def stop(self, process_ref: str) -> None:
        parsed = process_tree.parse_process_ref(process_ref)
        if parsed is None or not process_tree.ref_alive(process_ref):
            return  # déjà parti, ou le pid appartient à un autre programme : on ne tue jamais à l'aveugle
        if not process_tree.kill_tree(parsed[0]):
            raise StudioError(C.STOP_FAILED, "the Studio process tree is still alive after the kill")

    def activity(self, launch_id: str) -> Mapping[str, object]:
        try:
            raw = json.loads((self._studio / "activity.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) and raw.get("launch") == launch_id else {}

    def _tail_text(self) -> str:
        return " | ".join(self.log_tail(4)) or "no Studio log"

    def log_tail(self, lines: int = 8) -> list[str]:
        try:
            text = (self._studio / LOG_FILE).read_text(encoding="utf-8", errors="replace")[-6000:]
        except OSError:
            return []
        out = [_ANSI.sub("", line).strip() for line in text.splitlines()]
        return [line[:200] for line in out if line][-lines:]

    # ------------------------------------------------------------------ état

    def read_state(self) -> Mapping[str, object] | None:
        try:
            raw = json.loads((self._studio / STATE_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise StudioError(C.STORE_FAILED, f"{type(exc).__name__}: the Studio state file is unreadable") from None
        return raw if isinstance(raw, dict) else None

    def write_state(self, payload: Mapping[str, object]) -> None:
        try:
            self._studio.mkdir(parents=True, exist_ok=True)
            temporary = self._studio / (STATE_FILE + f".{secrets.token_hex(3)}.tmp")
            temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(temporary, self._studio / STATE_FILE)
        except OSError as exc:
            raise StudioError(C.STORE_FAILED, f"{type(exc).__name__}: the Studio state could not be written") from None
