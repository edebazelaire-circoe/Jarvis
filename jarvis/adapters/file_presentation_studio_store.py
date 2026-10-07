"""Magasin de fichiers des Presentations (handoff jarvis-interactive-presentation-studio, Slice 02).

Disposition, une racine par installation (`<data_root>/presentations/`, hors
du dépôt : `docs/local-data.md`) :

```
presentations/<presentation_id>/presentation.json     # identité, index des variantes, ressources
presentations/<presentation_id>/variants/<variant_id>.json
presentations/.staging-<16 hex>/                      # création en cours, balayée au démarrage
```

Port : `jarvis.ports.presentation_studio.PresentationStudioStore`. Aucune
validation ici (le service relit chaque document avec le domaine).

Garanties (réutilisées, jamais refaites) :

- **écriture atomique d'un fichier** : temporaire de nom unique dans le même
  dossier, `fsync`, puis `file_replace.replace_with_retry` (`os.replace`) : un
  arrêt brutal laisse l'ancien texte entier ou le nouveau entier. Le nom unique
  évite qu'un `.tmp` resté d'un arrêt brutal bloque la sauvegarde suivante ;
  `sweep` les retire au démarrage ;
- **création tout ou rien** : une Presentation neuve s'écrit dans
  `.staging-<hex>/` (variantes d'abord, manifeste en dernier) puis le dossier est
  renommé (`os.rename`, échoue si la cible existe) : jamais de dossier de
  Presentation sans manifeste complet ;
- **ordre multi-fichiers** : une opération qui touche plusieurs fichiers écrit
  les variantes d'abord et `presentation.json` en dernier (le service);
- dossiers par `safe_folders` (racine absolue, aucun lien ni jonction, limite
  de chemin Windows), fichiers lus par `lstat` + `fstat` (même fichier,
  ordinaire, borné à `MAX_DOCUMENT_BYTES`) ;
- ne supprime jamais un document : `sweep` ne retire que des `.staging-*` et
  des `*.tmp` à nous (CLAUDE.md « Données locales »).
"""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import re
import secrets
import stat

from jarvis.adapters import safe_folders
from jarvis.adapters.file_replace import replace_with_retry, retry_on_permission
from jarvis.domain.presentation_studio import (
    MAX_DOCUMENT_BYTES, MAX_PRESENTATIONS, PresentationStudioError, PresentationStudioErrorCode as C,
    is_presentation_id, is_variant_id,
)
from jarvis.ports.presentation_studio import StoreProblem, StoreScan, SweepReport

STORE_DIR = "presentations"
MANIFEST_FILE = "presentation.json"
VARIANTS_DIR = "variants"
STAGING_PREFIX = ".staging-"
_STAGING = re.compile(r"\.staging-[0-9a-f]{16}\Z")
_TEMPORARY = re.compile(r".+\.[0-9a-f]{8}\.tmp\Z")


def _unsafe(exc: safe_folders.SafeFolderError, where: str) -> PresentationStudioError:
    return PresentationStudioError(C.STORAGE_IO, f"{where}: {exc.kind}: {exc.reason}")


def _io(exc: OSError, where: str) -> PresentationStudioError:
    return PresentationStudioError(C.STORAGE_IO, f"{where}: {type(exc).__name__}: {exc.strerror or exc}")


def _write_file(path: Path, text: str) -> None:
    """Temporaire neuf (nom unique), `fsync`, `replace_with_retry` : jamais un fichier à moitié écrit."""

    temporary = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    safe_folders.check_file_path(path)
    safe_folders.check_file_path(temporary)
    try:
        with open(temporary, "xb") as stream:
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        replace_with_retry(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass  # intentional: the file may not exist yet (open failed) or the replace consumed it; sweep() clears leftovers
        raise
    _sync_folder(path.parent)


def _sync_folder(folder: Path) -> None:
    """Durabilité du renommage sous POSIX ; Windows ne sait pas `fsync` un dossier : le renommage NTFS est journalisé."""

    if os.name == "nt":
        return
    try:
        descriptor = os.open(folder, os.O_RDONLY)
    except OSError:
        return  # intentional: best effort, the replace itself already happened
    try:
        os.fsync(descriptor)
    except OSError:
        pass  # intentional: some filesystems refuse directory fsync; durability is then the filesystem's
    finally:
        os.close(descriptor)


def _remove_staging(folder: Path) -> bool:
    """Retire un dossier de préparation à nous (fichiers ordinaires, un sous-dossier `variants/`). `False` s'il reste."""

    try:
        if safe_folders.is_link(os.lstat(folder)):
            return False  # intentional: never follow nor delete through a link; reported as failed by the caller
        for entry in os.scandir(folder):
            info = os.lstat(entry.path)
            if safe_folders.is_link(info):
                return False  # intentional: not something create writes; left for a human, reported as failed
            if stat.S_ISDIR(info.st_mode) and entry.name == VARIANTS_DIR:
                if not _remove_staging(Path(entry.path)):
                    return False
            elif stat.S_ISREG(info.st_mode):
                os.unlink(entry.path)
            else:
                return False  # intentional: unexpected entry kind, left for a human
        os.rmdir(folder)
    except FileNotFoundError:
        return True
    except OSError:
        return False  # intentional: the caller reports the folder as failed (sweep) or the create error first
    return True


#: A save lands (atomic replace) between our `lstat` and our `open`: the file is healthy, only newer. Re-inspect a few times.
READ_ATTEMPTS = 4


def _read_text(path: Path, label: str, *, missing: C) -> str:
    raw: bytes | None = None
    for _ in range(READ_ATTEMPTS):
        try:
            safe_folders.check_file_path(path)
            info = os.lstat(path)
        except FileNotFoundError:
            raise PresentationStudioError(missing, f"{label} does not exist") from None
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, label) from None
        except OSError as exc:
            raise _io(exc, label) from None
        if safe_folders.is_link(info) or not stat.S_ISREG(info.st_mode):
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{label}: not a regular file (link or folder refused)")

        def read_once() -> bytes | None:
            with open(path, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    return None  # replaced by a concurrent save between inspection and opening: look again
                return stream.read(MAX_DOCUMENT_BYTES + 1)

        try:
            # Windows refuses an open for a few ms while an antivirus, an indexer or a just-killed writer's handle
            # is still being released (seen by the kill test): same short bounded retry as the replace.
            raw = retry_on_permission(read_once)
        except FileNotFoundError:
            continue  # intentional: replaced and gone between lstat and open; the next pass reports absence if real
        except OSError as exc:
            raise _io(exc, label) from None
        if raw is not None:
            break
    if raw is None:
        raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{label}: kept changing under the reader ({READ_ATTEMPTS} attempts)")
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{label}: exceeds {MAX_DOCUMENT_BYTES} bytes")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{label}: not valid UTF-8") from None


def _check_ids(presentation_id: str, variant_id: str | None = None) -> None:
    """Un id est un composant de chemin : forme exacte exigée avant tout accès disque (aucun `..`, aucun séparateur)."""

    if not is_presentation_id(presentation_id):
        raise PresentationStudioError(C.INVALID_PRESENTATION, "presentation_id is not a valid id")
    if variant_id is not None and not is_variant_id(variant_id):
        raise PresentationStudioError(C.INVALID_PRESENTATION, "variant_id is not a valid id")


class FilePresentationStudioStore:
    """Voir l'en-tête du module. `data_root` : racine de données de cette installation."""

    def __init__(self, data_root: Path) -> None:
        self._data_root = Path(data_root)

    # ------------------------------------------------------------ lecture

    def scan(self) -> StoreScan:
        try:
            base = safe_folders.check_existing_tree(self._data_root, [STORE_DIR])
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, STORE_DIR) from None
        if base is None:
            return StoreScan()
        try:
            entries = sorted(os.scandir(base), key=lambda item: item.name)
        except OSError as exc:
            raise _io(exc, f"{STORE_DIR}: cannot list") from None
        ids: list[str] = []
        problems: list[StoreProblem] = []
        for entry in entries:
            if entry.name.startswith("."):
                continue  # intentional: staging folders and hidden files are never part of the listing
            try:
                info = os.lstat(entry.path)
            except OSError as exc:
                problems.append(StoreProblem(entry.name, f"cannot inspect: {type(exc).__name__}"))
                continue
            if safe_folders.is_link(info):
                problems.append(StoreProblem(entry.name, "symbolic link, junction or reparse point refused"))
            elif not stat.S_ISDIR(info.st_mode):
                continue  # intentional: a loose file beside the presentations is not one
            elif not is_presentation_id(entry.name):
                problems.append(StoreProblem(entry.name, "folder name is not a presentation id"))
            elif len(ids) >= MAX_PRESENTATIONS:
                problems.append(StoreProblem(entry.name, f"more than {MAX_PRESENTATIONS} presentations; rest ignored"))
                break
            else:
                ids.append(entry.name)
        return StoreScan(tuple(ids), tuple(problems))

    def _folder(self, presentation_id: str, *parts: str) -> Path | None:
        try:
            return safe_folders.check_existing_tree(self._data_root, [STORE_DIR, presentation_id, *parts])
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, presentation_id) from None

    def read_manifest(self, presentation_id: str) -> str:
        _check_ids(presentation_id)
        folder = self._folder(presentation_id)
        if folder is None:
            raise PresentationStudioError(C.UNKNOWN_PRESENTATION, f"{presentation_id} is not in the store")
        return _read_text(folder / MANIFEST_FILE, f"{presentation_id}/{MANIFEST_FILE}",
                          missing=C.CORRUPT_DOCUMENT)  # a folder without manifest is a torn state, not "unknown"

    def read_variant(self, presentation_id: str, variant_id: str) -> str:
        _check_ids(presentation_id, variant_id)
        folder = self._folder(presentation_id, VARIANTS_DIR)
        if folder is None:
            raise PresentationStudioError(C.UNKNOWN_VARIANT, f"{presentation_id}: variant {variant_id} is not stored")
        return _read_text(folder / f"{variant_id}.json", f"{presentation_id}/{variant_id}", missing=C.UNKNOWN_VARIANT)

    # ------------------------------------------------------------ écriture

    def create(self, presentation_id: str, manifest: str, variants: Mapping[str, str]) -> None:
        _check_ids(presentation_id)
        for variant_id in variants:
            _check_ids(presentation_id, variant_id)
        try:
            library, _ = safe_folders.ensure_folder_tree(self._data_root, [STORE_DIR])
            target = library / presentation_id
            if os.path.lexists(target):
                raise PresentationStudioError(C.ALREADY_EXISTS, f"{presentation_id} already exists")
            for name in (MANIFEST_FILE, *(f"{VARIANTS_DIR}/{v}.json" for v in variants)):
                safe_folders.check_file_path(target / name)
                safe_folders.check_file_path(target / (name + ".00000000.tmp"))
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, presentation_id) from None
        staging = library / f"{STAGING_PREFIX}{secrets.token_hex(8)}"
        try:
            os.mkdir(staging)
        except OSError as exc:
            raise _io(exc, f"{presentation_id}: cannot create staging folder") from None
        try:
            os.mkdir(staging / VARIANTS_DIR)
            for variant_id, text in variants.items():
                _write_file(staging / VARIANTS_DIR / f"{variant_id}.json", text)
            _write_file(staging / MANIFEST_FILE, manifest)  # last: a staging without manifest is never published
            retry_on_permission(lambda: os.rename(staging, target))
        except (FileExistsError, IsADirectoryError):
            _remove_staging(staging)
            raise PresentationStudioError(C.ALREADY_EXISTS, f"{presentation_id} already exists") from None
        except safe_folders.SafeFolderError as exc:
            _remove_staging(staging)
            raise _unsafe(exc, presentation_id) from None
        except OSError as exc:
            _remove_staging(staging)  # a leftover is swept at the next start
            raise _io(exc, presentation_id) from None
        _sync_folder(library)

    def write_variant(self, presentation_id: str, variant_id: str, text: str) -> None:
        _check_ids(presentation_id, variant_id)
        if self._folder(presentation_id) is None:
            raise PresentationStudioError(C.UNKNOWN_PRESENTATION, f"{presentation_id} is not in the store")
        try:
            folder, _ = safe_folders.ensure_folder_tree(self._data_root, [STORE_DIR, presentation_id, VARIANTS_DIR])
            _write_file(folder / f"{variant_id}.json", text)
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, f"{presentation_id}/{variant_id}") from None
        except OSError as exc:
            raise _io(exc, f"{presentation_id}/{variant_id}") from None

    def write_manifest(self, presentation_id: str, text: str) -> None:
        _check_ids(presentation_id)
        folder = self._folder(presentation_id)
        if folder is None:
            raise PresentationStudioError(C.UNKNOWN_PRESENTATION, f"{presentation_id} is not in the store")
        try:
            _write_file(folder / MANIFEST_FILE, text)
        except safe_folders.SafeFolderError as exc:
            raise _unsafe(exc, presentation_id) from None
        except OSError as exc:
            raise _io(exc, presentation_id) from None

    # ------------------------------------------------------------ balayage

    def sweep(self) -> SweepReport:
        try:
            base = safe_folders.check_existing_tree(self._data_root, [STORE_DIR])
        except safe_folders.SafeFolderError as exc:
            return SweepReport(failed=(f"{STORE_DIR}: {exc.reason}",))
        if base is None:
            return SweepReport()
        removed: list[str] = []
        failed: list[str] = []
        try:
            entries = list(os.scandir(base))
        except OSError as exc:
            return SweepReport(failed=(f"{STORE_DIR}: {type(exc).__name__}",))
        for entry in entries:
            if _STAGING.fullmatch(entry.name):
                (removed if _remove_staging(Path(entry.path)) else failed).append(entry.name)
            elif is_presentation_id(entry.name):
                for folder in (Path(entry.path), Path(entry.path) / VARIANTS_DIR):
                    self._sweep_temporaries(folder, entry.name, removed, failed)
        return SweepReport(tuple(removed), tuple(failed))

    @staticmethod
    def _sweep_temporaries(folder: Path, label: str, removed: list[str], failed: list[str]) -> None:
        try:
            names = [item.name for item in os.scandir(folder) if _TEMPORARY.fullmatch(item.name)]
        except OSError:
            return  # intentional: no variants/ folder yet, or unreadable: nothing of ours to sweep there
        for name in names:
            path = folder / name
            try:
                info = os.lstat(path)
                if safe_folders.is_link(info) or not stat.S_ISREG(info.st_mode):
                    failed.append(f"{label}/{name}")
                    continue
                os.unlink(path)
                removed.append(f"{label}/{name}")
            except OSError:
                failed.append(f"{label}/{name}")
