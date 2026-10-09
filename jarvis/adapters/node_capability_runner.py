"""Runner réel des capacités locales Node (Slice 04 ; `docs/remotion-runtime.md`).

Implémente `CapabilityRunner` (`jarvis/ports/local_capabilities.py`) pour une
capacité faite de paquets npm épinglés par un `package-lock.json` livré avec le
code. Tout effet (npm, node, processus) passe par `process_tree` ; le runner
n'écrit que dans `runtime_dir` (`<racine de données>/local_capabilities/<id>/runtime`) :

- jamais le dépôt, jamais `npm -g`, jamais d'arbre `node_modules` par présentation ;
- `npm ci` depuis le verrou livré : versions ET empreintes `integrity` (sha512) de
  tout l'arbre sont imposées par npm, qui refuse un tarball altéré (`EINTEGRITY`) ;
- cache, `.npmrc` utilisateur et variables d'environnement isolés (liste blanche) ;
- délai et arrêt de l'arbre entier de processus ; verrou d'installation avec
  détection d'un verrou périmé ; chaque échec devient un code typé et lisible.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import threading
import time
from urllib import request as urlrequest

from jarvis.adapters import process_tree
from jarvis.adapters.process_tree import ProcessResult
from jarvis.domain.local_capabilities import CapabilityManifest, LocalCapabilityError, LocalCapabilityErrorCode as C

RECORD_FILE = "install-record.json"
LOCK_FILE = ".install.lock"
WORKER_FILE = "worker.json"
WORKER_LOG = "worker.log"
WORKER_LOG_MAX_BYTES = 1_000_000
SCRIPT_FILE = "runtime-host.mjs"
REGISTRY = "https://registry.npmjs.org/"
RECORD_SCHEMA = 1
#: Fichiers livrés avec le code et copiés à l'installation (le verrou fait foi des versions).
SHIPPED_FILES = ("package.json", "package-lock.json", SCRIPT_FILE)
#: Chemin de dossier au-delà duquel Windows sans « chemins longs » casse l'arbre npm.
WINDOWS_SAFE_RUNTIME_PATH = 130


@dataclass(frozen=True)
class NodeRuntimeSpec:
    assets_dir: Path
    node_minimum: str
    npm_minimum: str
    supported_platforms: frozenset[str]
    install_timeout_s: float = 900.0
    probe_timeout_s: float = 90.0
    start_timeout_s: float = 45.0
    min_free_bytes: int = 1_500_000_000
    lock_stale_s: float = 1800.0


# ------------------------------------------------------------------ utilitaires

def parse_version(text: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_npm_failure(output: str) -> tuple[C, str]:
    """Sortie d'un `npm ci` en échec -> (code typé, jeton court). Ordre : le plus spécifique d'abord."""

    low = output.lower()
    if "eintegrity" in low or "integrity checksum failed" in low or "sha512" in low and "expected" in low:
        return C.INSTALL_INTEGRITY_FAILED, "integrity_failed"
    if "enospc" in low or "no space left" in low or "not enough space" in low:
        return C.INSTALL_DISK_FULL, "disk_full"
    if "eacces" in low or "eperm" in low or "operation not permitted" in low or "permission denied" in low:
        return C.INSTALL_PERMISSION_DENIED, "permission_denied"
    if "ebusy" in low or "resource busy or locked" in low:
        return C.INSTALL_PERMISSION_DENIED, "file_locked"
    if any(token in low for token in ("enotfound", "eai_again", "econnrefused", "econnreset", "etimedout", "enetunreach",
                                      "ehostunreach", "network", "getaddrinfo", "fetch failed", "socket hang up",
                                      "unable to get local issuer", "self-signed", "cert_")):
        return C.INSTALL_OFFLINE, "offline"
    if "e404" in low or "e401" in low or "e403" in low:
        return C.INSTALL_FAILED, "registry_refused"
    return C.INSTALL_FAILED, "npm_failed"


def _last_lines(text: str, count: int = 6) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " | ".join(lines[-count:])


def _remove_tree(path: Path) -> None:
    """Supprime `path` sans suivre aucun lien ni jonction ; réessaie un fichier verrouillé (antivirus, indexeur)."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(info.st_mode) and not _is_link(info):
        with os.scandir(path) as entries:
            children = [Path(entry.path) for entry in entries]
        for child in children:
            _remove_tree(child)
        _retry(lambda: os.rmdir(path))
    else:
        _retry(lambda: _unlink(path, info))


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _unlink(path: Path, info: os.stat_result) -> None:
    if stat.S_ISDIR(info.st_mode):  # jonction / lien de dossier : on retire le lien, jamais sa cible
        os.rmdir(path)
        return
    try:
        os.unlink(path)
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)
        os.unlink(path)


def _retry(action: Callable[[], None], attempts: int = 5) -> None:
    for attempt in range(attempts):
        try:
            action()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.3 * (attempt + 1))


# ---------------------------------------------------------------------- runner

class NodeCapabilityRunner:
    def __init__(self, spec: NodeRuntimeSpec, *, execute: Callable[..., ProcessResult] = process_tree.run_bounded,
                 which: Callable[[str], str | None] = shutil.which, environ: Mapping[str, str] | None = None,
                 free_bytes: Callable[[Path], int] | None = None, windows: bool | None = None) -> None:
        self._spec = spec
        self._execute = execute
        self._which = which
        self._environ = os.environ if environ is None else environ
        self._free_bytes = free_bytes or (lambda path: shutil.disk_usage(path).free)
        self._windows = process_tree.IS_WINDOWS if windows is None else windows
        self._active: set[int] = set()
        self._active_guard = threading.Lock()
        self._cancel = threading.Event()

    def _run(self, argv: list[str], *, cwd: Path, env: Mapping[str, str], timeout_s: float) -> ProcessResult:
        """Tout enfant passe ici : suivi pour que `cancel_all` (arrêt de Core) puisse tuer son arbre."""

        pids: list[int] = []

        def started(pid: int) -> None:
            pids.append(pid)
            with self._active_guard:
                self._active.add(pid)

        try:
            return self._execute(argv, cwd=cwd, env=env, timeout_s=timeout_s, on_start=started)
        finally:
            with self._active_guard:
                self._active.difference_update(pids)

    def cancel_all(self) -> None:
        """Arrêt de Core : tue l'arbre de chaque npm/node en cours ; l'installation en vol finit `failed` (reprise par `repair`)."""

        self._cancel.set()
        with self._active_guard:
            pids = list(self._active)
        for pid in pids:
            process_tree.kill_tree(pid)

    # ------------------------------------------------------------- outils du poste

    def _node(self) -> str | None:
        return self._which("node")

    def _npm_argv(self, node: str) -> list[str] | None:
        """`node npm-cli.js` (jamais `npm.cmd` : pas de shell, pas de guillemets à échapper)."""

        cli = Path(node).resolve().parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if cli.is_file():
            return [node, str(cli)]
        exe = self._which("npm.cmd" if self._windows else "npm")
        return [exe] if exe else None

    def _env(self, runtime_dir: Path | None = None) -> dict[str, str]:
        extra = {"npm_config_update_notifier": "false", "npm_config_fund": "false", "npm_config_audit": "false",
                 "npm_config_progress": "false", "npm_config_loglevel": "error", "npm_config_registry": REGISTRY,
                 "npm_config_fetch_retries": "2", "npm_config_fetch_retry_mintimeout": "2000",
                 "npm_config_fetch_retry_maxtimeout": "10000", "npm_config_ignore_scripts": "true"}
        if runtime_dir is not None:  # cache et configuration npm propres : ni ~/.npmrc (jetons) ni cache global
            extra.update({"npm_config_cache": str(runtime_dir / ".npm-cache"), "npm_config_userconfig": str(runtime_dir / ".npmrc"),
                          "npm_config_globalconfig": str(runtime_dir / ".npmrc-global")})
        return process_tree.clean_env(extra, environ=self._environ)

    def _query(self, argv: list[str], cwd: Path, timeout_s: float = 30.0) -> ProcessResult:
        return self._run(argv, cwd=cwd, env=self._env(), timeout_s=timeout_s)

    # ------------------------------------------------------------------- exigences

    def check_requirements(self, manifest: CapabilityManifest) -> tuple[str, ...]:
        """Exigences du poste non satisfaites, une ligne `jeton: explication` chacune. N'installe jamais Node."""

        spec = self._spec
        node = self._node()
        if node is None:
            return (f"node_missing: Node.js >= {spec.node_minimum} was not found on PATH; install it, Jarvis does not",)
        missing: list[str] = []
        cwd = Path(node).resolve().parent
        probe = self._query([node, "-p", "process.version+' '+process.platform+'-'+process.arch"], cwd)
        parts = probe.output.strip().splitlines()[-1].split() if probe.returncode == 0 and probe.output.strip() else []
        node_version = parse_version(parts[0]) if parts else None
        if node_version is None:
            return (f"node_unusable: `node` did not answer with a version ({_last_lines(probe.output, 2)})",)
        if node_version < parse_version(spec.node_minimum):
            missing.append(f"node_too_old: found {parts[0].lstrip('v')}, need >= {spec.node_minimum}")
        platform = parts[1] if len(parts) > 1 else "unknown"
        if platform not in spec.supported_platforms:
            missing.append(f"platform_unsupported: {platform} (supported: {', '.join(sorted(spec.supported_platforms))})")
        npm_argv = self._npm_argv(node)
        if npm_argv is None:
            missing.append(f"npm_missing: npm >= {spec.npm_minimum} was not found next to Node.js")
        else:
            npm = self._query([*npm_argv, "--version"], cwd)
            npm_version = parse_version(npm.output) if npm.returncode == 0 else None
            if npm_version is None:
                missing.append(f"npm_unusable: `npm --version` failed ({_last_lines(npm.output, 2)})")
            elif npm_version < parse_version(spec.npm_minimum):
                missing.append(f"npm_too_old: found {'.'.join(map(str, npm_version))}, need >= {spec.npm_minimum}")
        return tuple(missing)

    # ---------------------------------------------------------------- installation

    def install(self, manifest: CapabilityManifest, runtime_dir: Path) -> Mapping[str, str]:
        runtime_dir = Path(runtime_dir)
        started = time.monotonic()
        self._check_runtime_dir(manifest, runtime_dir)
        shipped = self._load_shipped(manifest)
        node = self._node()
        npm_argv = self._npm_argv(node) if node else None
        if node is None or npm_argv is None:
            raise LocalCapabilityError(C.REQUIREMENT_MISSING, "node_missing: node or npm disappeared since the requirement check")
        self._preflight(runtime_dir)
        self._cancel.clear()
        with self._install_lock(runtime_dir):
            self._clean_runtime(runtime_dir)
            for name in SHIPPED_FILES:
                shutil.copyfile(self._spec.assets_dir / name, runtime_dir / name)
            (runtime_dir / ".npmrc").write_text("", encoding="utf-8")
            (runtime_dir / ".npmrc-global").write_text("", encoding="utf-8")
            result = self._run([*npm_argv, "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=runtime_dir,
                                   env=self._env(runtime_dir), timeout_s=self._spec.install_timeout_s)
            if self._cancel.is_set():
                raise LocalCapabilityError(C.INSTALL_FAILED, "cancelled: Jarvis Core is stopping; run repair to resume")
            if result.timed_out:
                raise LocalCapabilityError(C.INSTALL_TIMEOUT, f"npm ci exceeded {int(self._spec.install_timeout_s)} s and its process tree was killed")
            if not result.started:
                raise LocalCapabilityError(C.INSTALL_FAILED, f"npm_unlaunchable: {_last_lines(result.output, 2)}")
            if result.returncode != 0:
                code, token = classify_npm_failure(result.output)
                raise LocalCapabilityError(code, f"{token}: npm ci exited {result.returncode}: {_last_lines(result.output)}")
            self._check_tree(runtime_dir, platform=self._node_platform(node, runtime_dir))
            installed = {name: self._installed_version(runtime_dir, name) for name in dict(manifest.components)}
            self._write_record(runtime_dir, shipped, installed, node, npm_argv, time.monotonic() - started)
            return installed

    def _check_runtime_dir(self, manifest: CapabilityManifest, runtime_dir: Path) -> None:
        if runtime_dir.name != "runtime" or runtime_dir.parent.name != manifest.capability_id:
            raise LocalCapabilityError(C.INSTALL_FAILED, "runtime_dir is not <data_root>/local_capabilities/<id>/runtime: refused")
        if self._windows and len(str(runtime_dir)) > WINDOWS_SAFE_RUNTIME_PATH and not self._windows_long_paths():
            raise LocalCapabilityError(C.INSTALL_FAILED, f"path_too_long: the runtime folder path is {len(str(runtime_dir))} characters; "
                                                         f"enable Windows long paths or use a shorter JARVIS_DATA_ROOT")

    @staticmethod
    def _windows_long_paths() -> bool:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
                return int(winreg.QueryValueEx(key, "LongPathsEnabled")[0]) == 1
        except OSError:
            return False

    def _load_shipped(self, manifest: CapabilityManifest) -> dict[str, str]:
        assets = self._spec.assets_dir
        try:
            declared = json.loads((assets / "package.json").read_text(encoding="utf-8")).get("dependencies", {})
            hashes = {name: sha256_file(assets / name) for name in SHIPPED_FILES}
        except (OSError, ValueError) as exc:
            raise LocalCapabilityError(C.INSTALL_FAILED, f"shipped_files_unreadable: {type(exc).__name__}") from None
        if declared != dict(manifest.components):
            raise LocalCapabilityError(C.INSTALL_FAILED, "manifest_mismatch: the shipped package.json does not match the pinned manifest")
        return hashes

    def _preflight(self, runtime_dir: Path) -> None:
        try:
            probe = runtime_dir / f".write-probe-{os.getpid()}"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
        except PermissionError as exc:
            raise LocalCapabilityError(C.INSTALL_PERMISSION_DENIED, f"permission_denied: the runtime folder is not writable ({type(exc).__name__})") from None
        except OSError as exc:
            raise LocalCapabilityError(C.INSTALL_FAILED, f"runtime_dir_unusable: {type(exc).__name__}: {exc}") from None
        free = self._free_bytes(runtime_dir)
        if free < self._spec.min_free_bytes:
            raise LocalCapabilityError(C.INSTALL_DISK_FULL, f"disk_full: {free // 1_000_000} MB free, {self._spec.min_free_bytes // 1_000_000} MB needed")

    def _clean_runtime(self, runtime_dir: Path) -> None:
        """Retire un reste d'installation (arbre partiel, ancien verrou) ; garde le cache npm (contenu adressé, vérifié à l'usage)."""

        for name in ("node_modules", *SHIPPED_FILES, RECORD_FILE, WORKER_FILE, ".npmrc", ".npmrc-global"):
            _remove_tree(runtime_dir / name)

    # ----------------------------------------------------------------- verrou

    def _install_lock(self, runtime_dir: Path):
        runner = self

        class _Lock:
            path = runtime_dir / LOCK_FILE

            def __enter__(self_inner):
                for _ in range(2):
                    try:
                        fd = os.open(self_inner.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    except FileExistsError:
                        if not runner._lock_is_stale(self_inner.path):
                            raise LocalCapabilityError(C.BUSY, "another installation holds the runtime lock") from None
                        _remove_tree(self_inner.path)
                        continue
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump({"ref": process_tree.make_process_ref(os.getpid()), "at": time.time()}, handle)
                    return self_inner
                raise LocalCapabilityError(C.BUSY, "the runtime lock could not be taken")

            def __exit__(self_inner, *exc_info):
                _remove_tree(self_inner.path)
                return False

        return _Lock()

    def _lock_is_stale(self, path: Path) -> bool:
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
            if process_tree.ref_alive(str(info["ref"])) and time.time() - float(info["at"]) < self._spec.lock_stale_s:
                return False
        except (OSError, ValueError, KeyError, TypeError):
            pass  # verrou illisible : considéré périmé
        return True

    # --------------------------------------------------------- arbre et empreinte

    def _node_platform(self, node: str, runtime_dir: Path) -> str:
        result = self._query([node, "-p", "process.platform+'-'+process.arch"], runtime_dir)
        return result.output.strip().splitlines()[-1] if result.returncode == 0 and result.output.strip() else ""

    @staticmethod
    def _applies(entry: Mapping, platform: str) -> bool:
        """Un paquet natif d'une autre plate-forme (os/cpu/libc) n'est pas attendu sur le disque."""

        os_name, _, cpu = platform.partition("-")
        for key, value in (("os", os_name), ("cpu", cpu)):
            wanted = entry.get(key)
            if wanted and value not in wanted:
                return False
        return True

    def _check_tree(self, runtime_dir: Path, *, platform: str) -> None:
        """Chaque paquet du verrou (de cette plate-forme) est sur le disque à la version du verrou."""

        try:
            lock = json.loads((runtime_dir / "package-lock.json").read_text(encoding="utf-8"))["packages"]
        except (OSError, ValueError, KeyError) as exc:
            raise LocalCapabilityError(C.HEALTH_FAILED, f"lock_unreadable: {type(exc).__name__}") from None
        bad: list[str] = []
        for key, entry in lock.items():
            if not key or entry.get("link") or not self._applies(entry, platform) or entry.get("libc"):  # libc : musl/glibc non devinable ici
                continue
            manifest_path = runtime_dir / key / "package.json"
            try:
                version = json.loads(manifest_path.read_text(encoding="utf-8")).get("version")
            except (OSError, ValueError):
                version = None
            if version is None and entry.get("optional") and not (entry.get("os") or entry.get("cpu")):
                continue  # dépendance optionnelle sans contrainte de plate-forme (aides wasm) : npm peut légitimement l'omettre
            if version != entry.get("version"):
                bad.append(f"{key}@{entry.get('version')} ({'missing or unreadable' if version is None else 'found ' + str(version)})")
                if len(bad) >= 5:
                    break
        if bad:
            raise LocalCapabilityError(C.HEALTH_FAILED, f"tree_corrupt: {'; '.join(bad)}")

    def _installed_version(self, runtime_dir: Path, name: str) -> str:
        try:
            return str(json.loads((runtime_dir / "node_modules" / name / "package.json").read_text(encoding="utf-8"))["version"])
        except (OSError, ValueError, KeyError) as exc:
            raise LocalCapabilityError(C.INSTALL_FAILED, f"component_missing: {name} ({type(exc).__name__})") from None

    def _fingerprint(self, runtime_dir: Path, names) -> str:
        """Empreinte (chemin, taille) des fichiers de chaque paquet épinglé : une troncature ou une suppression la change."""

        digest = hashlib.sha256()
        for name in sorted(names):
            base = runtime_dir / "node_modules" / name
            entries = []
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d != "node_modules"]  # dépendances : couvertes par le verrou, pas par l'empreinte
                for file in files:
                    full = Path(root) / file
                    entries.append((full.relative_to(base).as_posix(), full.stat().st_size))
            for rel, size in sorted(entries):
                digest.update(f"{name}/{rel}:{size}\n".encode())
        return digest.hexdigest()

    def _write_record(self, runtime_dir: Path, shipped: Mapping[str, str], installed: Mapping[str, str], node: str,
                      npm_argv: list[str], duration_s: float) -> None:
        platform = self._node_platform(node, runtime_dir)
        record = {"schema": RECORD_SCHEMA, "installed": dict(installed), "shipped_sha256": dict(shipped),
                  "lock_sha256": sha256_file(runtime_dir / "package-lock.json"),
                  "fingerprint": self._fingerprint(runtime_dir, installed), "platform": platform,
                  "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "duration_s": round(duration_s, 1)}
        tmp = runtime_dir / (RECORD_FILE + ".tmp")
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, runtime_dir / RECORD_FILE)

    # ------------------------------------------------------------------- santé

    def verify(self, manifest: CapabilityManifest, runtime_dir: Path, installed: Mapping[str, str]) -> None:
        """Sonde : verrou/empreinte/arbre sur disque, puis chargement réel des paquets par Node. Lève un échec typé."""

        runtime_dir = Path(runtime_dir)
        try:
            record = json.loads((runtime_dir / RECORD_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise LocalCapabilityError(C.HEALTH_FAILED, "record_missing: the install record is missing or unreadable") from None
        if record.get("installed") != dict(manifest.components) or dict(installed) != dict(manifest.components):
            raise LocalCapabilityError(C.HEALTH_FAILED, "version_mismatch: installed versions differ from the pinned ones")
        recorded = record.get("shipped_sha256", {})
        changed = []
        for name in SHIPPED_FILES:
            try:
                shipped_now, on_disk = sha256_file(self._spec.assets_dir / name), sha256_file(runtime_dir / name)
            except OSError:
                changed.append(name)
                continue
            if shipped_now != recorded.get(name) or on_disk != recorded.get(name):
                changed.append(name)
        if changed or sha256_file(runtime_dir / "package-lock.json") != record.get("lock_sha256"):
            raise LocalCapabilityError(C.HEALTH_FAILED, f"shipped_files_changed: {', '.join(changed) or 'package-lock.json'} differ from what was installed; repair re-syncs them")
        node = self._node()
        if node is None:
            raise LocalCapabilityError(C.HEALTH_FAILED, "node_missing: node is no longer on PATH")
        self._check_tree(runtime_dir, platform=record.get("platform", ""))
        if self._fingerprint(runtime_dir, installed) != record.get("fingerprint"):
            raise LocalCapabilityError(C.HEALTH_FAILED, "tree_corrupt: a pinned package has missing, extra or truncated files")
        if not (runtime_dir / SCRIPT_FILE).is_file():
            raise LocalCapabilityError(C.HEALTH_FAILED, f"tree_corrupt: {SCRIPT_FILE} is missing")
        result = self._run([node, SCRIPT_FILE, "--probe"], cwd=runtime_dir, env=self._env(), timeout_s=self._spec.probe_timeout_s)
        if result.timed_out:
            raise LocalCapabilityError(C.HEALTH_FAILED, f"probe_timeout: loading the packages took more than {int(self._spec.probe_timeout_s)} s")
        if result.returncode != 0:
            raise LocalCapabilityError(C.HEALTH_FAILED, f"probe_failed: {_last_lines(result.output, 3)}")

    # ----------------------------------------------------------------- processus

    def start(self, manifest: CapabilityManifest, runtime_dir: Path) -> str:
        runtime_dir = Path(runtime_dir)
        node = self._node()
        if node is None:
            raise LocalCapabilityError(C.START_FAILED, "node_missing: node is no longer on PATH")
        _remove_tree(runtime_dir / WORKER_FILE)
        log = runtime_dir / WORKER_LOG
        try:
            if log.stat().st_size > WORKER_LOG_MAX_BYTES:  # plafond : une génération précédente, jamais un journal sans fin
                os.replace(log, runtime_dir / (WORKER_LOG + ".1"))
        except OSError:
            pass
        pid = process_tree.spawn_detached([node, SCRIPT_FILE, "--serve"], cwd=runtime_dir, env=self._env(), log_path=runtime_dir / WORKER_LOG)
        deadline = time.monotonic() + self._spec.start_timeout_s
        info = None
        while time.monotonic() < deadline:
            try:
                info = json.loads((runtime_dir / WORKER_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = None
            if info and info.get("pid") == pid:
                break
            if not process_tree.pid_exists(pid):
                break
            time.sleep(0.2)
        try:
            if not info or info.get("pid") != pid:
                raise LocalCapabilityError(C.START_FAILED, f"worker_not_ready: {self._log_tail(runtime_dir)}")
            self._get_health(int(info["port"]), pid)
        except LocalCapabilityError:
            process_tree.kill_tree(pid)
            raise
        ref = process_tree.make_process_ref(pid)
        if not ref:  # identité introuvable : on ne suit pas, donc on n'arrêtera jamais « à l'aveugle » un pid réutilisé
            process_tree.kill_tree(pid)
            raise LocalCapabilityError(C.START_FAILED, "process_identity_unavailable: the worker's start time could not be read")
        return ref

    @staticmethod
    def _get_health(port: int, pid: int) -> None:
        """GET /health en boucle locale, SANS proxy d'environnement ; la réponse doit venir de NOTRE worker (pid)."""

        opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
        try:
            with opener.open(f"http://127.0.0.1:{port}/health", timeout=5) as response:  # noqa: S310 - loopback only
                body = json.loads(response.read(65536).decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise LocalCapabilityError(C.START_FAILED, f"worker_unhealthy: {type(exc).__name__}") from None
        if body.get("ok") is not True or body.get("pid") != pid:
            raise LocalCapabilityError(C.START_FAILED, "worker_unhealthy: /health did not answer ok from our worker")

    @staticmethod
    def _log_tail(runtime_dir: Path) -> str:
        try:
            return _last_lines((runtime_dir / WORKER_LOG).read_text(encoding="utf-8", errors="replace")[-4000:], 3)
        except OSError:
            return "no worker log"

    def stop(self, process_ref: str) -> None:
        parsed = process_tree.parse_process_ref(process_ref)
        if parsed is None or not process_tree.ref_alive(process_ref):
            return
        if not process_tree.kill_tree(parsed[0]):
            raise LocalCapabilityError(C.STOP_FAILED, "the process tree is still alive after taskkill/kill")

    def is_alive(self, process_ref: str) -> bool:
        return process_tree.ref_alive(process_ref)

    # ------------------------------------------------------------------ retrait

    def remove(self, manifest: CapabilityManifest, runtime_dir: Path) -> None:
        """Vide `runtime_dir` (jamais au-dessus, jamais un lien suivi). Aucune source de présentation n'est ici."""

        runtime_dir = Path(runtime_dir)
        if runtime_dir.name != "runtime" or runtime_dir.parent.name != manifest.capability_id:
            raise LocalCapabilityError(C.UNINSTALL_FAILED, "runtime_dir is not <data_root>/local_capabilities/<id>/runtime: refused")
        try:
            with os.scandir(runtime_dir) as entries:
                children = [Path(entry.path) for entry in entries]
            for child in children:
                _remove_tree(child)
        except FileNotFoundError:
            return
        except PermissionError as exc:
            raise LocalCapabilityError(C.INSTALL_PERMISSION_DENIED, f"permission_denied: {type(exc).__name__}: a file is locked or read-only") from None


def default_remotion_runner() -> NodeCapabilityRunner:
    from jarvis.domain.remotion_capability import NODE_MINIMUM, NPM_MINIMUM, SUPPORTED_PLATFORMS
    return NodeCapabilityRunner(NodeRuntimeSpec(Path(__file__).resolve().parents[1] / "capabilities" / "remotion",
                                                NODE_MINIMUM, NPM_MINIMUM, SUPPORTED_PLATFORMS))
