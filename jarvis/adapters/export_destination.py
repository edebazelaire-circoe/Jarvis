"""Destination bornée d'un export (`docs/export.md` › *Destination policy*, *Atomic copy*).

La SEULE écriture de Jarvis hors de sa maison : la copie d'un fichier final, déjà vérifié, dans la racine
d'export. Aucune primitive « écrire à ce chemin » : l'appelant donne un fichier source interne (résolu par le
service à partir d'un Artifact), un nom déjà assaini par le domaine et une extension de classe.

Racine :
- par défaut `<Documents>\\Jarvis`, Documents résolu par `known_folders.documents_folder` (API des dossiers
  connus de Windows) ; `JARVIS_EXPORT_ROOT` (absolu) la remplace entière (tests, bac à sable, administration) ;
- refusée (`export_destination_unsafe`) : chemin relatif, `..`, racine de lecteur, chemin UNC ou de périphérique
  (`\\\\serveur\\partage`, `\\\\?\\`), base qui traverse un lien ou une jonction (`realpath` ≠ chemin), dossier
  d'export qui est un lien symbolique, une jonction ou un point d'analyse (seuls les dossiers de fichiers
  cloud de OneDrive, `IO_REPARSE_TAG_CLOUD*`, sont admis : ce sont des dossiers ordinaires pour l'utilisateur) ;
- refusée (`export_destination_forbidden`) : racine dans, ou contenant, un dossier interdit (racine de données,
  `CONTEXT_GLOBAL`, runtime, maison du produit `%LOCALAPPDATA%\\CIRCOE\\Jarvis`, dossier du programme) ;
- jamais créée avant le premier export : rien n'apparaît dans Documents sans un geste explicite.

Copie atomique : fichier temporaire créé exclusivement DANS la destination (`O_EXCL`), octets copiés et hachés,
`fsync`, taille et SHA-256 comparés à l'enregistrement de l'Artifact, puis renommage SANS écrasement (Windows :
`os.rename` échoue si la cible existe ; ailleurs : `os.link` puis effacement du temporaire). Un nom pris passe au
suivant (`candidate_names`) ; le temporaire est effacé sur tout échec.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import errno
import hashlib
import os
from pathlib import Path, PureWindowsPath
import secrets
import shutil
import stat

from jarvis.adapters import safe_folders
from jarvis.adapters.global_context import GLOBAL_CONTEXT_DIR
from jarvis.adapters.known_folders import KnownFolderError, documents_folder
from jarvis.domain.document_export import (
    DEFAULT_ROOT_LABEL, EXPORT_DIR_NAME, OVERRIDE_ROOT_LABEL, TEMP_SUFFIX, ExportError, ExportErrorCode as E,
    candidate_names,
)

EXPORT_ROOT_ENV = "JARVIS_EXPORT_ROOT"
CHUNK_BYTES = 1024 * 1024
#: Marge de disque libre exigée au-delà de la taille du fichier.
FREE_MARGIN_BYTES = 64 * 1024 * 1024
_REPARSE_ATTR = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
#: `IO_REPARSE_TAG_CLOUD` .. `IO_REPARSE_TAG_CLOUD_F` (fichiers à la demande de OneDrive) : `tag & 0xFFFF0FFF`.
_CLOUD_TAG = 0x9000001A


def _canonical(path: Path | str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))


def link_like(info: os.stat_result) -> bool:
    """Lien symbolique, jonction ou tout point d'analyse autre qu'un dossier cloud de OneDrive."""

    if stat.S_ISLNK(info.st_mode):
        return True
    if not getattr(info, "st_file_attributes", 0) & _REPARSE_ATTR:
        return False
    tag = int(getattr(info, "st_reparse_tag", 0) or 0)
    return (tag & 0xFFFF0FFF) != _CLOUD_TAG


def _unsafe(detail: str) -> ExportError:
    return ExportError(E.DESTINATION_UNSAFE, detail)


def check_root_shape(raw: str) -> Path:
    """Forme d'une racine : absolue, sans `..`, ni racine de lecteur, ni UNC, ni périphérique. Aucune E/S."""

    text = str(raw or "").strip()
    if not text:
        raise _unsafe("the export root is empty")
    win = PureWindowsPath(text)
    if text.startswith(("\\\\", "//")) or win.drive.startswith(("\\\\", "//")):
        raise _unsafe("a network (UNC) or device path is not an export root")
    path = Path(text)
    if not (path.is_absolute() or win.is_absolute()):
        raise _unsafe("the export root must be an absolute path")
    if any(part == ".." for part in win.parts) or any(part == ".." for part in path.parts):
        raise _unsafe("the export root must not contain '..'")
    if path.parent == path or win.parent == win:
        raise _unsafe("a drive root is not an export root")
    return path


@dataclass(frozen=True, slots=True)
class CopyOutcome:
    file_name: str
    size_bytes: int
    sha256: str
    renamed: bool


class ExportDestination:
    """Racine d'export et copie sans écrasement. Voir l'en-tête du module."""

    def __init__(self, *, forbidden: Iterable[Path], override: str | None = None,
                 documents: Callable[[], Path] = documents_folder) -> None:
        self._forbidden = tuple(Path(p) for p in forbidden)
        self._override = (override or "").strip() or None
        self._documents = documents

    @classmethod
    def from_environment(cls, *, data_root: Path, environ: Mapping[str, str] | None = None,
                         documents: Callable[[], Path] = documents_folder) -> ExportDestination:
        """Racine depuis l'environnement ; dossiers interdits : données, `CONTEXT_GLOBAL`, runtime, maison du produit, programme."""

        from jarvis.data_root import resolve_runtime_root
        from jarvis.installation import CODE_ROOT, detect_installation

        env = dict(os.environ if environ is None else environ)
        forbidden = [Path(data_root), Path(data_root) / GLOBAL_CONTEXT_DIR, CODE_ROOT]
        try:
            forbidden.append(resolve_runtime_root(env))
        except Exception:  # noqa: BLE001 - argued: an unresolvable runtime root removes no protection of the others
            pass
        try:
            installation = detect_installation(env)
            if installation.installed and installation.home is not None:
                forbidden.append(installation.home.root)
        except Exception:  # noqa: BLE001 - argued: Core refuses to start on a bad marker; here the other guards still hold
            pass
        return cls(forbidden=forbidden, override=env.get(EXPORT_ROOT_ENV), documents=documents)

    # ------------------------------------------------------------ racine

    @property
    def label(self) -> str:
        return OVERRIDE_ROOT_LABEL if self._override else DEFAULT_ROOT_LABEL

    def _base_and_root(self) -> tuple[Path, Path]:
        if self._override:
            root = check_root_shape(self._override)
            return root.parent, root
        try:
            base = self._documents()
        except KnownFolderError as exc:
            raise ExportError(E.DESTINATION_UNAVAILABLE, str(exc)) from exc
        except OSError as exc:
            raise ExportError(E.DESTINATION_UNAVAILABLE, f"the Documents folder is unavailable: {type(exc).__name__}") from exc
        base = check_root_shape(str(base))
        return base, base / EXPORT_DIR_NAME

    def _check_forbidden(self, root: Path) -> None:
        mine = _canonical(root)
        for other in self._forbidden:
            theirs = _canonical(other)
            if mine == theirs or mine.startswith(theirs.rstrip(os.sep) + os.sep) or theirs.startswith(mine.rstrip(os.sep) + os.sep):
                raise ExportError(E.DESTINATION_FORBIDDEN,
                                  "the export root overlaps Jarvis's internal storage or program folder: refused")

    def _check_base(self, base: Path) -> None:
        try:
            info = os.stat(base)
        except FileNotFoundError:
            raise ExportError(E.DESTINATION_UNAVAILABLE, "the folder that holds the export root does not exist") from None
        except OSError as exc:
            raise ExportError(E.DESTINATION_UNAVAILABLE, f"the export base is unreadable: {type(exc).__name__}") from exc
        if not stat.S_ISDIR(info.st_mode):
            raise _unsafe("the folder that holds the export root is not a directory")
        if _canonical(base) != os.path.normcase(os.path.abspath(base)):
            raise _unsafe("the folder that holds the export root goes through a link or junction")

    def _check_root_folder(self, root: Path, *, create: bool) -> bool:
        """Inspecte (et crée si `create`) le dossier d'export ; `True` s'il existe à la sortie."""

        try:
            info = os.lstat(root)
        except FileNotFoundError:
            if not create:
                return False
            try:
                os.mkdir(root)
            except FileExistsError:
                pass  # un concurrent l'a créé : inspecté ci-dessous
            except OSError as exc:
                raise ExportError(E.FAILED, f"the export folder could not be created: {type(exc).__name__}: {exc.strerror}") from exc
            info = os.lstat(root)
        if link_like(info):
            raise _unsafe("the export folder is a symbolic link, junction or reparse point")
        if not stat.S_ISDIR(info.st_mode):
            raise _unsafe("the export folder exists and is not a directory")
        return True

    def resolve(self, *, create: bool = False) -> tuple[Path, bool]:
        """(racine vérifiée, existe). Ne crée la racine que si `create` (premier export) ; jamais au démarrage."""

        base, root = self._base_and_root()
        self._check_base(base)
        self._check_forbidden(root)
        exists = self._check_root_folder(root, create=create)
        return root, exists

    def describe(self) -> dict:
        """État de la racine pour l'interface, sans chemin absolu et sans rien créer."""

        try:
            _root, exists = self.resolve(create=False)
        except ExportError as exc:
            return {"available": False, "root": self.label, "code": exc.code.value, "message": exc.detail}
        return {"available": True, "root": self.label, "exists": exists}

    # ------------------------------------------------------------ copie

    def copy_in(self, source: Path, *, stem: str, extension: str, expected_size: int | None,
                expected_sha256: str | None) -> CopyOutcome:
        """Copie `source` (fichier interne, jamais un lien) en `<racine>/<stem><extension>` sans rien écraser."""

        root, _ = self.resolve(create=True)
        try:
            source_info = os.lstat(source)
        except FileNotFoundError:
            raise ExportError(E.SOURCE_UNAVAILABLE, "the canonical payload is missing on disk") from None
        except OSError as exc:
            raise ExportError(E.SOURCE_UNAVAILABLE, f"the canonical payload is unreadable: {type(exc).__name__}") from exc
        if link_like(source_info) or not stat.S_ISREG(source_info.st_mode):
            raise ExportError(E.SOURCE_UNAVAILABLE, "the canonical payload is not a plain file")
        try:
            free = shutil.disk_usage(root).free
        except OSError:
            free = None
        if free is not None and free < source_info.st_size + FREE_MARGIN_BYTES:
            raise ExportError(E.FAILED, f"not enough free disk space at the export root ({free // (1024 * 1024)} MiB free, "
                                        f"{source_info.st_size // (1024 * 1024) + 64} MiB needed)")
        temp = root / f".{secrets.token_hex(6)}{TEMP_SUFFIX}"
        self._check_length(temp)
        try:
            size, digest = self._write_temp(source, temp)
            if expected_size is not None and size != expected_size:
                raise ExportError(E.SOURCE_UNAVAILABLE, f"the canonical payload is {size} bytes, its record says {expected_size}")
            if expected_sha256 and digest != expected_sha256:
                raise ExportError(E.SOURCE_UNAVAILABLE, "the canonical payload does not match its recorded SHA-256")
            name, renamed = self._publish(temp, root, stem, extension)
        except BaseException:
            _discard(temp)
            raise
        return CopyOutcome(name, size, digest, renamed)

    @staticmethod
    def _check_length(path: Path) -> None:
        try:
            safe_folders.check_file_path(path)
        except safe_folders.SafeFolderError as exc:
            raise ExportError(E.FAILED, f"the export path is too long for Windows (limit {exc.path_limit} characters)") from None

    @staticmethod
    def _write_temp(source: Path, temp: Path) -> tuple[int, str]:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(temp, flags, 0o644)
        except OSError as exc:
            raise ExportError(E.FAILED, f"the export folder refused a new file: {type(exc).__name__}: {exc.strerror}") from exc
        hasher, size = hashlib.sha256(), 0
        try:
            with os.fdopen(fd, "wb", closefd=True) as out, open(source, "rb") as src:
                while chunk := src.read(CHUNK_BYTES):
                    out.write(chunk)
                    hasher.update(chunk)
                    size += len(chunk)
                out.flush()
                os.fsync(out.fileno())
        except ExportError:
            raise
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise ExportError(E.FAILED, "the disk is full: the export was not kept") from exc
            raise ExportError(E.FAILED, f"copy failed: {type(exc).__name__}: {exc.strerror}") from exc
        return size, hasher.hexdigest()

    def _publish(self, temp: Path, root: Path, stem: str, extension: str) -> tuple[str, bool]:
        for index, name in enumerate(candidate_names(stem, extension)):
            final = root / name
            self._check_length(final)
            if _taken(final):
                continue
            try:
                _rename_no_replace(temp, final)
            except FileExistsError:
                continue  # pris entre-temps (un autre export, l'utilisateur) : le suivant
            except OSError as exc:
                raise ExportError(E.FAILED, f"the export could not be named: {type(exc).__name__}: {exc.strerror}") from exc
            return name, index > 0
        raise ExportError(E.COLLISION_EXHAUSTED, f"{stem}{extension} and its numbered variants are all taken")


def _taken(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True  # fichier, dossier ou lien, même pendant : jamais remplacé


def _rename_no_replace(temp: Path, final: Path) -> None:
    if os.name == "nt":
        os.rename(temp, final)  # MoveFileEx sans MOVEFILE_REPLACE_EXISTING : FileExistsError si la cible existe
        return
    os.link(temp, final)  # échoue (EEXIST) si la cible existe
    os.unlink(temp)


def _discard(temp: Path) -> None:
    try:
        os.unlink(temp)
    except FileNotFoundError:
        pass  # déjà renommé ou jamais créé
    except OSError:
        pass  # argued: a leftover hidden `.partial` is reported by its name; the original error is the one raised


__all__: Sequence[str] = ("EXPORT_ROOT_ENV", "CopyOutcome", "ExportDestination", "check_root_shape", "link_like")
