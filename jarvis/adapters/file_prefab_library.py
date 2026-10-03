"""Bibliothèque de prefabs sur disque (handoff jarvis-scene-window-prefab-foundation, Slice 02).

Deux racines, même disposition `<prefab_id>/<version>/{manifest.json, template.html,
style.css, behavior.js, publication.json}` :

- **paquet** (`jarvis/prefabs/base/`) : prefabs de base livrés, **jamais écrit**
  ici — ce module n'y fait que lire ;
- **racine de données** (`<data_root>/prefabs/`) : la bibliothèque de cette
  installation, où `publish` écrit.

Port : `jarvis.ports.prefabs.PrefabLibrary`. Contrat : `docs/prefabs.md` ›
*Storage and library*. Aucune validation ici : le service relit chaque version
avec le domaine (`jarvis.domain.prefab`) et recalcule son empreinte.

Défenses (réutilisées, jamais refaites) :

- dossiers par `safe_folders.ensure_folder_tree` (écriture) et
  `check_existing_tree` (lecture, ne crée rien) : racine absolue, chaque
  composant inspecté par `lstat`, lien, jonction ou point d'analyse refusé ;
  chaque fichier par `check_file_path` (limite Windows). Au balayage, un
  dossier d'id ou de version qui est un lien est signalé, jamais suivi ;
- **publication immuable** : les fichiers sont écrits dans
  `<data_root>/prefabs/.staging-<16 hex>/`, chacun par temporaire puis
  `file_replace.replace_with_retry`, puis le dossier est renommé
  (`os.rename`) en `<prefab_id>/<version>`, ce qui échoue si la cible
  existe : une version publiée n'est jamais réécrite, et un arrêt entre
  deux fichiers ne laisse aucune version, seulement un `.staging-*` ;
- `sweep` retire les `.staging-*` restés d'un arrêt brutal : fichiers
  ordinaires seulement ; un lien ou un sous-dossier dedans laisse le dossier
  en place (`failed`), jamais suivi.

`FilePrefabRuntime` (Slice 03) lit le runtime injecté dans chaque cadre
(`jarvis/prefabs/runtime/shim.js`, `shell.css`) avec les mêmes défenses de
lecture ; port `jarvis.ports.prefabs.PrefabRuntimeSource`.
"""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import re
import secrets
import stat

from jarvis.adapters import safe_folders
from jarvis.adapters.file_replace import replace_with_retry, retry_on_permission
from jarvis.domain.prefab import (
    FILES, MANIFEST_FILE, MAX_BEHAVIOR_BYTES, MAX_MANIFEST_BYTES, MAX_PREFAB_IDS, MAX_PUBLICATION_BYTES,
    MAX_STYLE_BYTES, MAX_TEMPLATE_BYTES, MAX_VERSIONS_PER_ID, PUBLICATION_FILE, PrefabBundle, Publication, is_prefab_id, is_version, version_folder_name,
)
from jarvis.ports.prefabs import (
    PrefabRuntimeFiles, PrefabRoot, PrefabScan, PrefabStoreError, PrefabStoreErrorCode, ScannedVersion, ScanProblem, StoredFiles,
    SweepReport,
)

#: Sous-dossier de la racine de données.
LIBRARY_DIR = "prefabs"
STAGING_PREFIX = ".staging-"
#: Runtime des cadres (Slice 03) : fichiers et bornes en octets.
RUNTIME_SHIM_FILE = "shim.js"
RUNTIME_SHELL_FILE = "shell.css"
MAX_RUNTIME_SHIM_BYTES = 64 * 1024
MAX_RUNTIME_SHELL_BYTES = 32 * 1024
STAGING_NAME = re.compile(r"\.staging-[0-9a-f]{16}\Z")
#: Fichiers d'une version et leur borne en octets ; `publication.json` en dernier à l'écriture.
_FILE_LIMITS = {
    MANIFEST_FILE: MAX_MANIFEST_BYTES,
    FILES["template"]: MAX_TEMPLATE_BYTES,
    FILES["style"]: MAX_STYLE_BYTES,
    FILES["behavior"]: MAX_BEHAVIOR_BYTES,
    PUBLICATION_FILE: MAX_PUBLICATION_BYTES,
}
_C = PrefabStoreErrorCode


def _store_error(code: PrefabStoreErrorCode, message: str) -> PrefabStoreError:
    return PrefabStoreError(code, message)


def _unsafe(exc: safe_folders.SafeFolderError, where: str) -> PrefabStoreError:
    return _store_error(_C.STORAGE_IO, f"{where}: {exc.kind}: {exc.reason}")


def _write_file(path: Path, text: str) -> None:
    """Temporaire neuf du même dossier, `fsync`, puis `replace_with_retry` : jamais un fichier à moitié écrit."""

    safe_folders.check_file_path(path)
    temporary = path.with_name(path.name + ".tmp")
    safe_folders.check_file_path(temporary)
    with open(temporary, "xb") as stream:
        stream.write(text.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    replace_with_retry(temporary, path)


def _remove_staging(folder: Path) -> bool:
    """Retire un dossier de préparation à nous : fichiers ordinaires seulement. `False` s'il reste."""

    try:
        if safe_folders.is_link(os.lstat(folder)):
            return False  # intentional: never follow nor delete through a link; reported as failed by the caller
        for entry in os.scandir(folder):
            info = os.lstat(entry.path)
            if not stat.S_ISREG(info.st_mode) or safe_folders.is_link(info):
                return False  # intentional: not something publish writes; left for a human, reported as failed
            os.unlink(entry.path)
        os.rmdir(folder)
    except FileNotFoundError:
        return True
    except OSError:
        return False  # intentional: the caller reports the folder as failed (sweep) or the publish error first
    return True


class FilePrefabLibrary:
    """Voir l'en-tête du module. `package_root` : `jarvis/prefabs/base` ; `data_root` : racine de données."""

    def __init__(self, package_root: Path, data_root: Path) -> None:
        self._package_root = Path(package_root)
        self._data_root = Path(data_root)

    # ------------------------------------------------------------ lecture

    def scan(self) -> PrefabScan:
        versions: list[ScannedVersion] = []
        problems: list[ScanProblem] = []
        try:
            package = safe_folders.resolve_root(self._package_root)
        except safe_folders.SafeFolderError as exc:
            problems.append(ScanProblem(PrefabRoot.PACKAGE, ".", f"package root unavailable: {exc.reason}"))
        else:
            self._scan_root(PrefabRoot.PACKAGE, package, versions, problems)
        try:
            library = safe_folders.check_existing_tree(self._data_root, [LIBRARY_DIR])
        except safe_folders.SafeFolderError as exc:
            problems.append(ScanProblem(PrefabRoot.DATA, LIBRARY_DIR, f"{exc.kind}: {exc.reason}"))
        else:
            if library is not None:
                self._scan_root(PrefabRoot.DATA, library, versions, problems)
        return PrefabScan(tuple(versions), tuple(problems))

    def _scan_root(self, root: PrefabRoot, base: Path, versions: list[ScannedVersion],
                   problems: list[ScanProblem]) -> None:
        try:
            entries = sorted(os.scandir(base), key=lambda item: item.name)
        except OSError as exc:
            problems.append(ScanProblem(root, ".", f"cannot list: {type(exc).__name__}: {exc}"))
            return
        ids = 0
        for entry in entries:
            if entry.name.startswith("."):
                continue  # intentional: staging folders and hidden files are never part of the catalogue
            try:
                info = os.lstat(entry.path)
            except OSError as exc:
                problems.append(ScanProblem(root, entry.name, f"cannot inspect: {type(exc).__name__}"))
                continue
            if safe_folders.is_link(info):
                problems.append(ScanProblem(root, entry.name, "symbolic link, junction or reparse point refused"))
                continue
            if not stat.S_ISDIR(info.st_mode):
                continue  # intentional: files beside the id folders (catalog.lock.json) are not versions
            if not is_prefab_id(entry.name):
                problems.append(ScanProblem(root, entry.name, "folder name is not a prefab id"))
                continue
            ids += 1
            if ids > MAX_PREFAB_IDS:
                problems.append(ScanProblem(root, entry.name, f"more than {MAX_PREFAB_IDS} prefab ids; rest ignored"))
                return
            self._scan_id(root, Path(entry.path), entry.name, versions, problems)

    def _scan_id(self, root: PrefabRoot, folder: Path, prefab_id: str, versions: list[ScannedVersion],
                 problems: list[ScanProblem]) -> None:
        found: list[tuple[int, Path]] = []
        try:
            entries = list(os.scandir(folder))
        except OSError as exc:
            problems.append(ScanProblem(root, prefab_id, f"cannot list: {type(exc).__name__}"))
            return
        for entry in entries:
            label = f"{prefab_id}/{entry.name}"
            version = version_folder_name(entry.name)
            try:
                info = os.lstat(entry.path)
            except OSError:
                continue  # intentional: vanished between listing and inspection; nothing to catalogue
            if safe_folders.is_link(info):
                problems.append(ScanProblem(root, label, "symbolic link, junction or reparse point refused"))
                continue
            if version is None or not stat.S_ISDIR(info.st_mode):
                problems.append(ScanProblem(root, label, "not a version folder (1..9999)"))
                continue
            found.append((version, Path(entry.path)))
        found.sort()
        if len(found) > MAX_VERSIONS_PER_ID:
            problems.append(ScanProblem(root, prefab_id, f"more than {MAX_VERSIONS_PER_ID} versions; "
                                                         "the highest are ignored"))
            found = found[:MAX_VERSIONS_PER_ID]
        for version, path in found:
            signature = []
            for name in _FILE_LIMITS:
                try:
                    info = os.lstat(path / name)
                except OSError:
                    continue  # intentional: a missing file is reported by read_version (tampered)
                signature.append((name, info.st_size, info.st_mtime_ns))
            if not any(name == MANIFEST_FILE for name, _, _ in signature):
                problems.append(ScanProblem(root, f"{prefab_id}/{version}", "no manifest.json"))
                continue
            versions.append(ScannedVersion(root, prefab_id, version, tuple(signature)))

    def read_version(self, root: PrefabRoot, prefab_id: str, version: int) -> StoredFiles:
        if not is_prefab_id(prefab_id):
            raise _store_error(_C.UNKNOWN_PREFAB, "not a prefab id")
        if not is_version(version):
            raise _store_error(_C.UNKNOWN_VERSION, f"{prefab_id}: version must be 1..9999")
        base, parts = ((self._package_root, [prefab_id, str(version)]) if root is PrefabRoot.PACKAGE
                       else (self._data_root, [LIBRARY_DIR, prefab_id, str(version)]))
        try:
            folder = safe_folders.check_existing_tree(base, parts)
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, f"{prefab_id}/{version}") from None
        if folder is None:
            raise _store_error(_C.UNKNOWN_VERSION, f"{prefab_id}@{version} is not in the {root.value} library")
        texts = {name: self._read_text(folder / name, limit, f"{prefab_id}/{version}/{name}")
                 for name, limit in _FILE_LIMITS.items()}
        for name in (MANIFEST_FILE, *FILES.values()):
            if texts[name] is None:
                raise _store_error(_C.TAMPERED, f"{prefab_id}@{version}: {name} is missing")
        return StoredFiles(manifest=texts[MANIFEST_FILE], template=texts[FILES["template"]],  # type: ignore[arg-type]
                           style=texts[FILES["style"]], behavior=texts[FILES["behavior"]],  # type: ignore[arg-type]
                           publication=texts[PUBLICATION_FILE])

    @staticmethod
    def _read_text(path: Path, limit: int, label: str) -> str | None:
        try:
            safe_folders.check_file_path(path)
            info = os.lstat(path)
        except FileNotFoundError:
            return None
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, label) from None
        except OSError as exc:
            raise _store_error(_C.STORAGE_IO, f"{label}: {type(exc).__name__}: {exc}") from None
        if safe_folders.is_link(info) or not stat.S_ISREG(info.st_mode):
            raise _store_error(_C.TAMPERED, f"{label}: not a regular file (link or folder refused)")
        try:
            with open(path, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise _store_error(_C.TAMPERED, f"{label}: replaced between inspection and opening")
                raw = stream.read(limit + 1)
        except OSError as exc:
            raise _store_error(_C.STORAGE_IO, f"{label}: {type(exc).__name__}: {exc}") from None
        if len(raw) > limit:
            raise _store_error(_C.TAMPERED, f"{label}: exceeds {limit} bytes")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise _store_error(_C.TAMPERED, f"{label}: not valid UTF-8") from None

    # ------------------------------------------------------------ écriture

    def publish(self, bundle: PrefabBundle, publication: Publication) -> str:
        prefab_id, version = publication.prefab_id, publication.version
        if (bundle.manifest.prefab_id, bundle.manifest.version) != (prefab_id, version):
            raise _store_error(_C.INVALID_DEFINITION, "bundle and publication name different versions")
        label = f"{prefab_id}/{version}"
        try:
            library, _ = safe_folders.ensure_folder_tree(self._data_root, [LIBRARY_DIR])
            id_folder, _ = safe_folders.ensure_folder_tree(self._data_root, [LIBRARY_DIR, prefab_id])
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, label) from None
        target = id_folder / str(version)
        if os.path.lexists(target):
            raise _store_error(_C.VERSION_EXISTS, f"{prefab_id}@{version} is already published; versions are "
                                                  "never rewritten")
        contents = {
            MANIFEST_FILE: json.dumps(dict(bundle.manifest.raw), ensure_ascii=False, indent=2) + "\n",
            FILES["template"]: bundle.template,
            FILES["style"]: bundle.style,
            FILES["behavior"]: bundle.behavior,
            PUBLICATION_FILE: publication.render(),
        }
        try:
            for name in contents:
                safe_folders.check_file_path(target / name)
                safe_folders.check_file_path(target / (name + ".tmp"))
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, label) from None
        staging = library / f"{STAGING_PREFIX}{secrets.token_hex(8)}"
        try:
            os.mkdir(staging)
        except OSError as exc:
            raise _store_error(_C.STORAGE_IO, f"{label}: cannot create staging folder: {type(exc).__name__}: "
                                              f"{exc}") from None
        try:
            for name, text in contents.items():
                _write_file(staging / name, text)
            retry_on_permission(lambda: os.rename(staging, target))
        except (FileExistsError, IsADirectoryError) as exc:
            _remove_staging(staging)
            raise _store_error(_C.VERSION_EXISTS, f"{prefab_id}@{version} is already published") from exc
        except OSError as exc:
            _remove_staging(staging)  # a leftover is swept at the next start
            if exc.errno in (errno.EEXIST, errno.ENOTEMPTY):  # POSIX: rename onto an existing folder
                raise _store_error(_C.VERSION_EXISTS, f"{prefab_id}@{version} is already published") from None
            raise _store_error(_C.STORAGE_IO, f"{label}: {type(exc).__name__}: {exc}") from None
        except safe_folders.SafeFolderError as exc:
            _remove_staging(staging)
            raise _unsafe(exc, label) from None
        try:
            landed = safe_folders.check_existing_tree(self._data_root, [LIBRARY_DIR, prefab_id, str(version)])
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, f"{label} (after publish)") from None
        if landed is None:
            raise _store_error(_C.STORAGE_IO, f"{label}: published folder vanished right after the rename")
        return label

    def sweep(self) -> SweepReport:
        try:
            library = safe_folders.check_existing_tree(self._data_root, [LIBRARY_DIR])
        except safe_folders.SafeFolderError as exc:
            return SweepReport(failed=(f"{LIBRARY_DIR}: {exc.reason}",))
        if library is None:
            return SweepReport()
        removed: list[str] = []
        failed: list[str] = []
        try:
            entries = [entry for entry in os.scandir(library) if STAGING_NAME.fullmatch(entry.name)]
        except OSError as exc:
            return SweepReport(failed=(f"{LIBRARY_DIR}: {type(exc).__name__}",))
        for entry in entries:
            (removed if _remove_staging(Path(entry.path)) else failed).append(entry.name)
        return SweepReport(tuple(removed), tuple(failed))


class FilePrefabRuntime:
    """`<runtime_root>/{shim.js, shell.css}` (`jarvis/prefabs/runtime/`), relus à chaque appel : jamais écrits."""

    def __init__(self, runtime_root: Path) -> None:
        self._root = Path(runtime_root)

    def read_runtime(self) -> PrefabRuntimeFiles:
        texts: dict[str, str] = {}
        for name, limit in ((RUNTIME_SHIM_FILE, MAX_RUNTIME_SHIM_BYTES), (RUNTIME_SHELL_FILE, MAX_RUNTIME_SHELL_BYTES)):
            text = FilePrefabLibrary._read_text(self._root / name, limit, f"runtime/{name}")
            if text is None:
                raise _store_error(_C.STORAGE_IO, f"prefab runtime file runtime/{name} is missing")
            texts[name] = text
        return PrefabRuntimeFiles(shim=texts[RUNTIME_SHIM_FILE], shell_css=texts[RUNTIME_SHELL_FILE])
