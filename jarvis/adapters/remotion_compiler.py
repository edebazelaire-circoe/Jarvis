"""Compilateur de scènes Remotion : TSX -> bundle navigateur pour le Player (Slice 05 ; `docs/remotion-source.md` §5).

Processus géré **de la capacité Remotion** : un `node runtime-host.mjs --compile <requête>` par compilation, lancé par le
runner de la capacité (`NodeCapabilityRunner.run_script` : environnement en liste blanche, délai, arbre tué au dépassement
ou à l'arrêt de Core), dans l'unique arbre `node_modules` de `<racine>/local_capabilities/remotion/runtime/`. Aucune
installation par scène, aucun accès disque de la scène (le compilateur lit des modules **en mémoire**).

Sortie : `<racine>/local_capabilities/remotion/compiled/<clé>/{scene.js|host.js, public/**, compile.json}`, clé =
contenu de la source + arbre installé (`jarvis.domain.remotion_compile.scene_cache_key`). C'est un cache **dérivé** : le
supprimer ne perd rien, la source (prefab) fait foi. Écriture atomique (dossier temporaire puis renommage), relecture
vérifiée (taille et SHA-256), une seule compilation à la fois par clé, élagage (`CACHE_KEEP_ENTRIES`, `CACHE_MAX_BYTES`).

Synchrone : l'appelant asynchrone passe par `asyncio.to_thread`.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import threading
import time
from typing import Any, Protocol

from jarvis.adapters.process_tree import ProcessResult
from jarvis.domain.remotion_compile import (
    CACHE_KEEP_ENTRIES, CACHE_KEY, CACHE_MAX_BYTES, COMPILE_CONTRACT, HOST_FILE, HOST_TIMEOUT_S, MAX_DIAGNOSTICS,
    MAX_HOST_BUNDLE_BYTES, MAX_SCENE_BUNDLE_BYTES, PUBLIC_DIR, RESULT_FILE, SCENE_ALLOWED_IMPORTS, SCENE_FILE, SCENE_TIMEOUT_S,
    CompileDiagnostic, CompiledArtifact, CompiledFile, CompileErrorCode as E, CompileTarget, InstalledEngine,
    RemotionCompileError, host_cache_key, scene_cache_key,
)
from jarvis.domain.remotion_source import ASSET_ROOT, RemotionSource, source_path_problem

TMP_PREFIX = ".tmp-"
TMP_MAX_AGE_S = 3600.0
RECORD_FILE = "install-record.json"


class ScriptRunner(Protocol):
    def run_script(self, runtime_dir: Path, args: list[str], *, timeout_s: float) -> ProcessResult: ...


def read_installed_engine(runtime_dir: Path) -> InstalledEngine | None:
    """Versions réellement installées et empreinte du verrou, d'après `install-record.json` ; `None` si illisible."""

    try:
        record = json.loads((Path(runtime_dir) / RECORD_FILE).read_text(encoding="utf-8"))
        installed = record["installed"]
        return InstalledEngine(str(installed["remotion"]), str(installed["react"]), str(record["lock_sha256"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


class RemotionCompiler:
    """Voir l'en-tête du module.

    `readiness()` rend `None` si la capacité est utilisable, sinon la raison (affichée telle quelle dans
    `compile_runtime_unavailable`). `diagnostics` : puits `emit(kind, message, level=, data=)` ; le chemin normal est
    journalisé (`remotion.compile.done`), chaque échec aussi, avec son code.
    """

    def __init__(self, *, runner: ScriptRunner, runtime_dir: Path, cache_dir: Path, readiness: Callable[[], str | None],
                 diagnostics: Any = None, scene_timeout_s: float = SCENE_TIMEOUT_S, host_timeout_s: float = HOST_TIMEOUT_S,
                 allowed_imports: tuple[str, ...] = SCENE_ALLOWED_IMPORTS) -> None:
        self._runner = runner
        self._runtime_dir = Path(runtime_dir)
        self._cache_dir = Path(cache_dir)
        self._readiness = readiness
        self._diagnostics = diagnostics
        self._timeouts = {CompileTarget.SCENE: scene_timeout_s, CompileTarget.HOST: host_timeout_s}
        self._allowed = tuple(allowed_imports)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    # ------------------------------------------------------------------ API

    def compile_scene(self, source: RemotionSource, *, minify: bool = True) -> CompiledArtifact:
        """Compile une source déjà validée (`PrefabService.remotion_source`). Rend le résultat, du cache s'il y est."""

        engine = self._ready_engine()
        key = scene_cache_key(source.digest, source.block.entry, engine, allowed_imports=self._allowed, minify=minify)
        pinned = source.block.engine.to_dict()

        def request(out_dir: Path) -> dict[str, Any]:
            return {"contract": COMPILE_CONTRACT, "target": "scene", "out_dir": str(out_dir), "entry": source.block.entry,
                    "modules": source.module_texts(), "allowed_imports": list(self._allowed), "minify": minify,
                    "digest": source.digest}

        def extras(out_dir: Path) -> list[str]:
            return self._copy_public(source, out_dir)

        return self._build(CompileTarget.SCENE, key, engine, request, extras, source_digest=source.digest, pinned=pinned)

    def compile_host(self, *, minify: bool = True) -> CompiledArtifact:
        """Le `host.js` partagé par toutes les scènes (React, Remotion, Player), une fois par arbre installé."""

        engine = self._ready_engine()
        key = host_cache_key(engine, minify=minify)
        return self._build(CompileTarget.HOST, key, engine,
                           lambda out_dir: {"contract": COMPILE_CONTRACT, "target": "host", "out_dir": str(out_dir),
                                            "minify": minify}, lambda out_dir: [], source_digest=None, pinned=None)

    def resolve_output_file(self, cache_key: str, relative: str) -> Path:
        """Chemin disque d'un fichier d'une entrée de cache (pour que Core le serve), après vérification : clé bien formée,
        chemin déclaré dans `compile.json`, ni lien ni sortie du dossier. `RemotionCompileError(cache_io)` sinon."""

        if not isinstance(cache_key, str) or not CACHE_KEY.fullmatch(cache_key):
            raise RemotionCompileError(E.CACHE_IO, "not a compile cache key")
        folder = self._cache_dir / cache_key
        artifact = self._read_cached(folder, cache_key, verify=False)
        declared = {f.path: f for f in artifact.files} if artifact is not None else {}
        if relative not in declared:
            raise RemotionCompileError(E.CACHE_IO, f"{cache_key} has no compiled file {relative[:60]!r}")
        path = folder.joinpath(*relative.split("/"))
        try:
            info = os.lstat(path)
        except OSError:
            raise RemotionCompileError(E.CACHE_IO, f"{cache_key}/{relative[:60]} is missing from the cache") from None
        if _is_link(info) or not stat.S_ISREG(info.st_mode) or info.st_size != declared[relative].bytes:
            raise RemotionCompileError(E.CACHE_IO, f"{cache_key}/{relative[:60]} differs from compile.json; recompile")
        return path

    def prune(self, *, keep: int = CACHE_KEEP_ENTRIES, max_bytes: int = CACHE_MAX_BYTES, protect: str | None = None) -> list[str]:
        """Retire les entrées les moins récemment utilisées au-delà de `keep` entrées ou `max_bytes` octets, et les
        dossiers temporaires abandonnés (> 1 h). Jamais `protect`. Rend les noms retirés."""

        removed: list[str] = []
        try:
            entries = [entry for entry in os.scandir(self._cache_dir)]
        except FileNotFoundError:
            return removed
        except OSError as exc:
            self._emit("remotion.compile.cache_error", "Cache de compilation illisible", level="error", error=type(exc).__name__)
            return removed
        now = time.time()
        live: list[tuple[float, int, os.DirEntry]] = []
        for entry in entries:
            try:
                info = os.lstat(entry.path)
            except OSError:
                continue
            if _is_link(info) or not stat.S_ISDIR(info.st_mode):
                continue  # intentional: never follow or delete what is not our own plain folder
            if entry.name.startswith(TMP_PREFIX):
                if now - info.st_mtime > TMP_MAX_AGE_S and self._remove_tree(Path(entry.path)):
                    removed.append(entry.name)
                continue
            if CACHE_KEY.fullmatch(entry.name):
                live.append((info.st_mtime, self._tree_bytes(Path(entry.path)), entry))
        live.sort(key=lambda item: item[0], reverse=True)  # most recently used first
        total = 0
        for index, (_, size, entry) in enumerate(live):
            total += size
            if entry.name == protect:
                continue
            if index >= keep or total > max_bytes:
                if self._remove_tree(Path(entry.path)):
                    removed.append(entry.name)
                    total -= size
        if removed:
            self._emit("remotion.compile.pruned", "Entrées de cache de compilation retirées", removed=len(removed))
        return removed

    # ------------------------------------------------------------------ cœur

    def _build(self, target: CompileTarget, key: str, engine: InstalledEngine, make_request: Callable[[Path], dict[str, Any]],
               extras: Callable[[Path], list[str]], *, source_digest: str | None, pinned: dict[str, str] | None) -> CompiledArtifact:
        with self._lock_for(key):
            final = self._cache_dir / key
            cached = self._read_cached(final, key)
            if cached is not None:
                self._touch(final)
                self._emit("remotion.compile.reused", "Compilation Remotion relue du cache", target=target.value, cache_key=key)
                return cached
            started = time.monotonic()
            tmp = self._cache_dir / f"{TMP_PREFIX}{secrets.token_hex(8)}"
            try:
                out = tmp / "out"
                self._mkdir(out)
                request_path = tmp / "request.json"
                request_path.write_text(json.dumps(make_request(out), ensure_ascii=False), encoding="utf-8")
                result = self._runner.run_script(self._runtime_dir, ["--compile", str(request_path)], timeout_s=self._timeouts[target])
                report = self._interpret(result, out, target)
                scene_file = SCENE_FILE if target is CompileTarget.SCENE else HOST_FILE
                limit = MAX_SCENE_BUNDLE_BYTES if target is CompileTarget.SCENE else MAX_HOST_BUNDLE_BYTES
                size = (out / scene_file).stat().st_size
                if size > limit:
                    raise RemotionCompileError(E.OUTPUT_TOO_LARGE, f"{scene_file} is {size} bytes, at most {limit}")
                (out / "result.json").unlink(missing_ok=True)
                names = [scene_file, *extras(out)]
                files = tuple(CompiledFile(name, (out / name).stat().st_size, _sha256((out / name).read_bytes()))
                              for name in sorted(set(names)))
                artifact = CompiledArtifact(target, key, files, engine, source_digest, pinned, False,
                                            int((time.monotonic() - started) * 1000), int(report.get("warnings", 0)))
                (out / RESULT_FILE).write_text(json.dumps(artifact.to_record(), indent=2) + "\n", encoding="utf-8")
                self._publish(out, final)
            except RemotionCompileError as exc:
                self._emit("remotion.compile.failed", "Compilation Remotion refusée", level="error" if exc.code in (
                    E.COMPILER_FAILED, E.CACHE_IO, E.RUNTIME_UNAVAILABLE) else "warning", target=target.value, code=exc.code.value,
                           detail=exc.message, diagnostics=len(exc.diagnostics))
                raise
            except OSError as exc:
                self._emit("remotion.compile.failed", "Cache de compilation inutilisable", level="error", target=target.value,
                           code=E.CACHE_IO.value, error=type(exc).__name__)
                raise RemotionCompileError(E.CACHE_IO, f"the compile cache could not be written ({type(exc).__name__})") from None
            finally:
                self._remove_tree(tmp)
            self._emit("remotion.compile.done", "Compilation Remotion terminée", target=target.value, cache_key=key,
                       files=len(artifact.files), duration_ms=artifact.duration_ms, drift=artifact.engine_drift)
            self.prune(protect=key)
            return artifact

    def _interpret(self, result: ProcessResult, out: Path, target: CompileTarget) -> dict[str, Any]:
        if not result.started:
            raise RemotionCompileError(E.RUNTIME_UNAVAILABLE, "node could not be launched: " + self._clean(result.output))
        if result.timed_out:
            raise RemotionCompileError(E.TIMEOUT, f"the {target.value} compile took more than {int(self._timeouts[target])} s "
                                                  "and its process tree was stopped")
        try:
            report = json.loads((out / "result.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RemotionCompileError(E.COMPILER_FAILED, f"the compiler produced no result (exit {result.returncode}): "
                                                          f"{self._clean(result.output)}") from None
        if report.get("ok") is True and result.returncode == 0:
            return report
        try:
            code = E(report.get("code"))
        except ValueError:
            code = E.COMPILER_FAILED
        diagnostics = tuple(CompileDiagnostic(str(d.get("file", ""))[:120], int(d.get("line") or 0), int(d.get("column") or 0),
                                              str(d.get("text", ""))[:300])
                            for d in (report.get("diagnostics") or [])[:MAX_DIAGNOSTICS] if isinstance(d, dict))
        raise RemotionCompileError(code, str(report.get("message") or "the compiler failed"), diagnostics=diagnostics)

    def _clean(self, output: str) -> str:
        """Fin de la sortie du processus, sans chemin du poste (racine du runtime, du cache, du profil)."""

        text = " | ".join(line.strip() for line in output.strip().splitlines()[-3:])
        for secret in (str(self._runtime_dir), str(self._cache_dir), str(self._runtime_dir).replace("\\", "/"),
                       str(self._cache_dir).replace("\\", "/")):
            text = text.replace(secret, "<capability>")
        return text[:240] or "no output"

    # ------------------------------------------------------------------ disque

    def _ready_engine(self) -> InstalledEngine:
        reason = self._readiness()
        if reason:
            raise RemotionCompileError(E.RUNTIME_UNAVAILABLE, reason)
        engine = read_installed_engine(self._runtime_dir)
        if engine is None:
            raise RemotionCompileError(E.RUNTIME_UNAVAILABLE, "the Remotion install record is missing: run repair on the capability")
        return engine

    def _copy_public(self, source: RemotionSource, out: Path) -> list[str]:
        names: list[str] = []
        for path in source.block.assets:
            if source_path_problem(path, root=ASSET_ROOT, extensions=frozenset({os.path.splitext(path)[1]})) is not None:
                raise RemotionCompileError(E.INVALID_SOURCE, f"{path[:80]}: unsafe asset path")
            target = out.joinpath(PUBLIC_DIR, *path[len(ASSET_ROOT):].split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.files[path])
            names.append(f"{PUBLIC_DIR}/{path[len(ASSET_ROOT):]}")
        return names

    def _mkdir(self, path: Path) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        if _is_link(os.lstat(self._cache_dir)):
            raise RemotionCompileError(E.CACHE_IO, "the compile cache folder is a link; refused")
        path.mkdir(parents=True)

    def _publish(self, out: Path, final: Path) -> None:
        """Renomme `out` en entrée de cache. Une entrée déjà là et saine (autre fil, même clé, mêmes octets) est gardée ;
        une entrée abîmée (relue plus haut comme invalide) est retirée puis remplacée."""

        try:
            os.rename(out, final)
            return
        except OSError:
            if not os.path.lexists(final):
                raise
        if self._read_cached(final, final.name) is not None:
            return
        if not self._remove_tree(final):
            raise OSError(f"{final.name}: damaged cache entry could not be replaced")
        os.rename(out, final)

    def _read_cached(self, folder: Path, key: str, *, verify: bool = True) -> CompiledArtifact | None:
        try:
            if _is_link(os.lstat(folder)):
                return None
            artifact = CompiledArtifact.from_record(json.loads((folder / RESULT_FILE).read_text(encoding="utf-8")))
            if artifact is None or artifact.cache_key != key:
                return None
            for item in artifact.files:
                if source_path_bad(item.path):
                    return None
                if not verify:
                    continue
                path = folder.joinpath(*item.path.split("/"))
                info = os.lstat(path)
                if _is_link(info) or not stat.S_ISREG(info.st_mode) or info.st_size != item.bytes \
                        or _sha256(path.read_bytes()) != item.sha256:
                    return None
            return artifact
        except (OSError, ValueError):
            return None

    @staticmethod
    def _touch(folder: Path) -> None:
        try:
            os.utime(folder, None)
        except OSError:
            pass  # intentional: only the pruning order is affected

    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    @staticmethod
    def _tree_bytes(folder: Path) -> int:
        total = 0
        for base, _dirs, files in os.walk(folder):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(base, name))
                except OSError:
                    pass
        return total

    @staticmethod
    def _remove_tree(folder: Path) -> bool:
        try:
            if not folder.exists() and not os.path.lexists(folder):
                return True
            if _is_link(os.lstat(folder)):
                return False
            shutil.rmtree(folder)
            return True
        except OSError:
            return False

    def _emit(self, kind: str, message: str, *, level: str = "info", **data: Any) -> None:
        if self._diagnostics is not None:
            self._diagnostics.emit(kind, message, level=level, data=data)


def source_path_bad(path: str) -> bool:
    """Chemin de fichier de sortie indigne de confiance (relu de `compile.json`) : seuls `scene.js`, `host.js` et `public/**`."""

    if path in (SCENE_FILE, HOST_FILE):
        return False
    if not path.startswith(PUBLIC_DIR + "/"):
        return True
    return source_path_problem(ASSET_ROOT + path[len(PUBLIC_DIR) + 1:], root=ASSET_ROOT,
                               extensions=frozenset({os.path.splitext(path)[1]})) is not None


def build_remotion_compiler(host: Any, store: Any, runner: ScriptRunner, *, diagnostics: Any = None,
                            capability_id: str = "remotion") -> RemotionCompiler:
    """Compilateur branché sur l'hôte des capacités locales : prêt seulement si la capacité est `ready` ou `running`."""

    runtime_dir = Path(store.runtime_dir(capability_id))

    def readiness() -> str | None:
        view = host.status(capability_id)
        if view.get("status") in ("ready", "running"):
            return None
        detail = f" ({view['last_error_code']})" if view.get("last_error_code") else ""
        return (f"the Remotion capability is {view.get('status')}{detail}; install or repair it from the local capabilities "
                "(POST /v1/local-capabilities/remotion/install or repair)")

    return RemotionCompiler(runner=runner, runtime_dir=runtime_dir, cache_dir=runtime_dir.parent / "compiled", readiness=readiness,
                            diagnostics=diagnostics)


def shipped_engine_pin() -> "EnginePin":
    """Le jeu de paquets livré avec Jarvis (version Remotion, version React, empreinte du `package-lock.json` livré) : ce que
    la source d'une scène neuve déclare dans `source.engine` (`jarvis.domain.remotion_capability` en est la source unique)."""

    from jarvis.domain.remotion_capability import REACT_VERSION, REMOTION_VERSION
    from jarvis.domain.remotion_source import ENGINE_NAME, EnginePin
    lock = Path(__file__).resolve().parents[1] / "capabilities" / "remotion" / "package-lock.json"
    return EnginePin(ENGINE_NAME, REMOTION_VERSION, REACT_VERSION, hashlib.sha256(lock.read_bytes()).hexdigest())
