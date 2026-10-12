"""Runner réel du Studio Remotion optionnel (Slice 11 ; `docs/remotion-studio.md`).

Tout effet disque et processus du Studio passe ici. Il n'écrit que sous `<runtime>/studio/` (le dossier `runtime/` de la
capacité, `docs/remotion-runtime.md` §1) :

    studio/state.json          état persistant (service)
    studio/work/               le SEUL dossier que le Studio sert : l'ESPACE DE TRAVAIL (Slice 12 de native-studio-playback-fix) ;
                               `src/**` et `public/**` modifiables, `studio-root.tsx` et `package.json` générés en lecture seule
    studio/work.files.json     empreintes de la BASE (la version matérialisée, ou publiée depuis cet espace) : ce qui en diffère
                               est une modification non publiée
    ../studio-edits/<horodatage>/ copie des fichiers non publiés avant qu'une action CONFIRMÉE (mettre de côté) ou un changement
                               de la capacité les remplace, et ce que `enforce_shape` déplace avant un lancement ; HORS de
                               `runtime/` : une désinstallation ne l'emporte pas. Nom triable et monotone
                               (`AAAAMMJJTHHMMSS.ffffff-<seq>`) ; au plus 5 dossiers, le plus ancien retiré et nommé (`take_rotated`)
    studio/studio-guard.cjs    copie du garde livré (`jarvis/capabilities/remotion/studio-guard.cjs`), comparée à chaque lancement
    studio/studio.log          sortie du processus (plafonnée)
    studio/listening.json, activity.json   écrits par le garde dans le processus du Studio

Le processus est `node --require studio-guard.cjs @remotion/cli/remotion-cli.js studio ...`, cwd = `work/`, environnement en
liste blanche (`process_tree.clean_env` : aucune variable `JARVIS_*` sauf les deux identifiants de lancement, aucune clé, aucun
jeton), lancé sans fenêtre ni navigateur (`--no-open`). Aucune route de Core, aucune base, aucun Board n'est lisible depuis ce
dossier ; les écritures vers la bibliothèque de prefabs ne passent JAMAIS par ici : la publication lit l'espace de travail
(`workspace_diff`) et passe par la porte d'édition de source de la variante (`RemotionStudioService.publish`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import itertools
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
from jarvis.adapters.node_capability_runner import _is_link, _remove_tree, extended_path
from jarvis.domain import remotion_studio as D
from jarvis.domain.remotion_studio import StudioError, StudioErrorCode as C
from jarvis.domain.remotion_studio_workspace import WorkspaceDiff, listing_digest
from jarvis.ports.remotion_studio import LaunchResult, SyncReport

CLI_ENTRY = Path("node_modules") / "@remotion" / "cli" / "remotion-cli.js"
SHIPPED_GUARD = Path(__file__).resolve().parents[1] / "capabilities" / "remotion" / D.GUARD_FILE
LOG_FILE = "studio.log"
LOG_MAX_BYTES = 1_000_000
STATE_FILE = "state.json"
MANIFEST_FILE = "work.files.json"
#: Copies des fichiers non publiés, à côté de `runtime/` (jamais dedans : `uninstall` vide `runtime/`).
EDITS_DIR = "studio-edits"
#: Fichiers générés par Jarvis (lecture seule) ; tout le reste de l'espace de travail (`src/**`, `public/**`) est modifiable.
GENERATED_FILES = (D.WORK_ROOT_FILE, D.WORK_PACKAGE)
#: Le cache de l'outil (webpack de Remotion) au premier niveau de l'espace : vidé par `launch`, jamais scanné ni mis de côté.
TOOL_CACHE_DIR = "node_modules"
UNREADABLE_WORK = "<work folder unreadable or too large>"
#: Départage des mises de côté créées dans la même microseconde (nom triable : `...ffffff-<seq>`).
_EDITS_SEQ = itertools.count(1)
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


def safe_relative(path: object) -> str:
    """Chemin de fichier de la copie de travail : relatif, séparateur `/`, aucun segment vide, `.` ou `..`, ni lecteur ni deux-points,
    ni antislash, ni NUL. Appliqué à tout chemin qui va toucher le disque (écriture, mise de côté)."""

    if (not isinstance(path, str) or not path or len(path) > 400 or path.startswith("/") or "\\" in path or ":" in path
            or "\x00" in path or any(part in ("", ".", "..") for part in path.split("/"))):
        raise StudioError(C.SYNC_FAILED, "a work file path is not a plain relative path: refused")
    return path


def _plain_file(info: os.stat_result) -> bool:
    """Fichier ordinaire à un seul nom : ni lien, ni jonction, ni lien dur (`st_nlink` > 1 : le même contenu sous un nom ailleurs)."""

    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not _is_link(info)


def _final_path(handle_fd: int, fallback: Path) -> str:
    """Chemin réel du fichier OUVERT (lié au descripteur, pas au nom) : sous Windows `GetFinalPathNameByHandleW`, qui résout les
    jonctions et liens des dossiers parents tels qu'ils étaient à l'ouverture ; ailleurs `/proc/self/fd`, sinon le nom résolu."""

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetFinalPathNameByHandleW.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
        kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        handle = msvcrt.get_osfhandle(handle_fd)
        size = 512
        while True:
            buffer = ctypes.create_unicode_buffer(size)
            length = kernel32.GetFinalPathNameByHandleW(handle, buffer, size, 0)
            if length == 0:
                raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
            if length < size:
                return _strip_extended(buffer.value)
            size = length + 1
    proc = Path(f"/proc/self/fd/{handle_fd}")
    return os.path.realpath(proc if proc.exists() else fallback)


def _strip_extended(text: str) -> str:
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    if text.startswith("\\\\?\\"):
        return text[4:]
    return text


def _inside(path: str, root: str) -> bool:
    path, root = os.path.normcase(os.path.normpath(path)), os.path.normcase(os.path.normpath(root))
    try:
        return os.path.commonpath([path, root]) == root and path != root
    except ValueError:  # deux lecteurs différents
        return False


def _clear_readonly(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


class RemotionStudioRunner:
    def __init__(self, runtime_dir: Callable[[], Path], *, which: Callable[[str], str | None] = shutil.which,
                 environ: Mapping[str, str] | None = None, spawn=process_tree.spawn_detached, clock=time.monotonic,
                 sleep=time.sleep, start_timeout_s: float = D.START_TIMEOUT_S,
                 port_chooser: Callable[[], int] = free_loopback_port, wall_ns: Callable[[], int] = time.time_ns) -> None:
        self._runtime_dir = runtime_dir
        self._wall_ns = wall_ns
        self._last_edits_us = 0
        self._rotated: list[str] = []
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

    @property
    def _edits(self) -> Path:
        return Path(self._runtime_dir()).parent / EDITS_DIR

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

    #: Dossiers de la copie de travail qui sont LA source (le reste est du travail de l'outil : le cache de webpack de Remotion vit
    #: dans `node_modules/.cache` de l'espace, il n'est ni lu, ni compté, ni retiré par une synchronisation ; `launch` le vide).
    SOURCE_DIRS = ("src", "public")

    def _scan_work(self) -> dict[str, str]:
        """`{chemin: empreinte}` de la source : `src/**`, `public/**` et les FICHIERS de premier niveau. Un lien, une jonction ou un lien
        dur (`st_nlink` > 1) est signalé `link` (jamais lu). Un fichier de premier niveau ajouté (un `remotion.config.ts` que Node
        exécuterait) est vu ici comme modification non publiée, jamais publié ; ce n'est PAS ce relevé qui le retire : `enforce_shape`
        le met de côté avant chaque lancement, `sync_work` le retire en matérialisant. Les DOSSIERS de premier niveau autres que
        `src` / `public` ne sont pas relevés (le cache de l'outil, ou un dossier étranger : mis de côté par `enforce_shape`)."""

        found: dict[str, str] = {}
        work = self._work
        if not work.is_dir():
            return found
        total = 0

        def add(path: Path, relative: str) -> None:
            nonlocal total
            info = os.lstat(path)
            if _is_link(info) or (stat.S_ISREG(info.st_mode) and info.st_nlink > 1):
                found[relative] = "link"
                return
            total += info.st_size
            if len(found) >= MAX_WORK_FILES or total > MAX_WORK_BYTES:
                raise StudioError(C.SYNC_FAILED, "the Studio work folder holds too many or too large files")
            found[relative] = _sha(path.read_bytes())

        for entry in sorted(os.scandir(work), key=lambda item: item.name):
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False) and not _is_link(os.lstat(path)):
                if entry.name not in self.SOURCE_DIRS:
                    continue
                for root, dirs, names in os.walk(path):
                    for name in list(dirs):
                        if _is_link(os.lstat(Path(root) / name)):
                            found[(Path(root) / name).relative_to(work).as_posix() + "/"] = "link"
                            dirs.remove(name)
                    for name in names:
                        add(Path(root) / name, (Path(root) / name).relative_to(work).as_posix())
            elif entry.name in self.SOURCE_DIRS:
                found[entry.name + "/"] = "link"  # `src` ou `public` remplacé par un lien ou une jonction
            else:
                add(path, entry.name)
        return found

    def _manifest(self) -> dict[str, str]:
        try:
            raw = json.loads((self._studio / MANIFEST_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}

    def workspace_listing(self) -> tuple[tuple[str, ...], str]:
        """`(chemins modifiés, empreinte)` : les fichiers qui diffèrent de la base et `listing_digest` de leur état sur le disque
        (empreinte, `link`, ou `None` si supprimé). La page renvoie cette empreinte avec `publish` (QA Slice 12, I1)."""

        if not self._work.is_dir():
            return (), listing_digest({})
        try:
            disk, recorded = self._scan_work(), self._manifest()
        except (OSError, StudioError):
            return (UNREADABLE_WORK,), ""  # dit, jamais tu : l'écran l'affiche comme fichier modifié ; aucune empreinte, rien de publiable
        changed = [path for path in sorted(set(disk) | set(recorded)) if disk.get(path) != recorded.get(path)]
        return tuple(changed), listing_digest({path: disk.get(path) for path in changed})

    def modified_work(self) -> tuple[str, ...]:
        return self.workspace_listing()[0]

    def sync_work(self, files: Mapping[str, bytes]) -> SyncReport:
        studio, work = self._studio, self._work
        try:
            work.mkdir(parents=True, exist_ok=True)
            edited = self.modified_work()
            saved = self._save_edits(edited)
            disk = self._scan_work()
            for path in [p for p, kind in disk.items() if kind == "link"]:  # un lien posé dans la source : retiré (jamais sa cible) AVANT d'écrire
                _remove_tree(work.joinpath(*path.rstrip("/").split("/")))
                disk.pop(path)
            for path in files:
                safe_relative(path)
            wanted = {path: _sha(bytes(data)) for path, data in files.items()}
            written = unchanged = removed = 0
            for path in sorted(files):
                target = work.joinpath(*path.split("/"))
                self._check_inside(target)
                if disk.get(path) == wanted[path]:
                    unchanged += 1
                    if path not in GENERATED_FILES:  # une copie d'avant la Slice 12 était en lecture seule : l'espace devient modifiable
                        _clear_readonly(target)
                    continue
                self._write_file(path, bytes(files[path]))
                written += 1
            for path in sorted(set(disk) - set(files)):
                target = work.joinpath(*path.split("/"))
                _clear_readonly(target)
                _remove_tree(target)
                removed += 1
            for name in self.SOURCE_DIRS:
                if (work / name).is_dir():
                    self._prune_empty_dirs(work / name)
            shutil.rmtree(studio / ".tmp", ignore_errors=True)
            record = studio / (MANIFEST_FILE + ".tmp")
            record.write_text(json.dumps(wanted, sort_keys=True), encoding="utf-8")
            os.replace(record, studio / MANIFEST_FILE)
        except StudioError:
            raise
        except OSError as exc:
            raise StudioError(C.SYNC_FAILED, f"{type(exc).__name__}: the Studio work folder could not be written") from None
        return SyncReport(written, removed, unchanged, tuple(saved))

    def _write_file(self, path: str, data: bytes) -> None:
        """Écrit un fichier de l'espace par renommage atomique ; un fichier généré (`GENERATED_FILES`) est en lecture seule."""

        target = self._work.joinpath(*path.split("/"))
        temp = self._studio / ".tmp"
        temp.mkdir(exist_ok=True)
        staged = temp / f"{secrets.token_hex(6)}.part"
        staged.write_bytes(data)
        if path in GENERATED_FILES:  # généré depuis le manifeste : jamais une source, lecture seule
            os.chmod(staged, stat.S_IREAD)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            _clear_readonly(target)
        os.replace(staged, target)

    @staticmethod
    def _prune_empty_dirs(root: Path) -> None:
        for current, dirs, _ in os.walk(root, topdown=False):
            for name in dirs:
                folder = Path(current) / name
                try:
                    folder.rmdir()  # ne réussit que si vide
                except OSError:
                    pass

    # ------------------------------------------------------------------ mises de côté (`studio-edits/`)

    def _new_edits_folder(self) -> Path:
        """Un nouveau dossier de mise de côté. Son nom est triable ET monotone dans ce processus (`AAAAMMJJTHHMMSS.ffffff-<seq>`, heure
        locale comme les dossiers d'avant ; la microseconde ne recule jamais) : la rotation retire toujours les plus anciens, même
        pour sept mises de côté dans la même seconde (QA Slice 12, I4 : l'ancien suffixe aléatoire en retirait d'autres)."""

        edits = self._edits
        edits.mkdir(parents=True, exist_ok=True)
        while True:
            micro_total = max(self._wall_ns() // 1000, self._last_edits_us + 1)
            self._last_edits_us = micro_total
            seconds, micro = divmod(micro_total, 1_000_000)
            name = time.strftime("%Y%m%dT%H%M%S", time.localtime(seconds)) + f".{micro:06d}-{next(_EDITS_SEQ) % 10_000:04d}"
            try:
                (edits / name).mkdir()
            except FileExistsError:
                continue
            return edits / name

    def _rotate_edits(self) -> None:
        """Garde les `MAX_SAVED_EDITS` dossiers les plus récents ; chaque dossier retiré est nommé (`take_rotated`, journalisé par le
        service) : une mise de côté n'est jamais effacée en silence."""

        edits = self._edits
        folders = sorted(item.name for item in edits.iterdir() if item.is_dir())
        for name in folders[: max(0, len(folders) - D.MAX_SAVED_EDITS)]:
            _remove_tree(edits / name)
            self._rotated.append(name)

    def take_rotated(self) -> tuple[str, ...]:
        rotated, self._rotated = tuple(self._rotated), []
        return rotated

    def _save_edits(self, edited: tuple[str, ...]) -> list[str]:
        """Copie les fichiers modifiés hors de Jarvis AVANT qu'une synchronisation les remplace : rien n'est perdu en silence."""

        for path in edited:
            if not path.endswith("/") and not path.startswith("<"):
                safe_relative(path)  # un chemin hostile est refusé AVANT tout accès au disque
        saved = [path for path in edited if not path.endswith("/") and not path.startswith("<") and (self._work / path).is_file()]
        if not saved:
            return []
        destination = self._new_edits_folder()
        for path in saved:
            safe_relative(path)
            target = destination.joinpath(*path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self._work / path, target)
        self._rotate_edits()
        return saved

    def save_modified(self) -> tuple[str, ...]:
        try:
            return tuple(self._save_edits(self.modified_work()))
        except OSError as exc:
            raise StudioError(C.SYNC_FAILED, f"{type(exc).__name__}: the modified Studio files could not be saved") from None

    def enforce_shape(self, files: Mapping[str, bytes]) -> tuple[str, ...]:
        """Avant CHAQUE lancement (QA Slice 12, B1) : l'espace n'a que sa forme. Au premier niveau, `src/` et `public/` (vrais dossiers),
        les fichiers générés ÉGAUX à ceux que Jarvis génère (`files`, régénérés sinon) et le cache de l'outil ; dans `src/**` et
        `public/**`, des fichiers ordinaires seulement. Tout le reste (un `remotion.config.js` / `.ts` que Node exécuterait, tout
        fichier ou dossier de premier niveau ajouté, tout lien, jonction ou lien dur, n'importe où) est DÉPLACÉ dans un nouveau dossier
        `studio-edits/` (jamais supprimé, jamais suivi : on déplace le lien, pas sa cible). Rend les chemins mis de côté (`/` final
        pour un dossier). Un déplacement impossible lève `SYNC_FAILED` : le lancement n'a pas lieu."""

        work = self._work
        if not work.is_dir():
            return ()
        aside: list[str] = []
        destination: Path | None = None

        def move(path: Path, folder: bool) -> None:
            nonlocal destination
            relative = path.relative_to(work).as_posix()
            if destination is None:
                destination = self._new_edits_folder()
            target = destination.joinpath(*relative.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(extended_path(path), extended_path(target))  # renomme l'entrée elle-même (lien, jonction) : sa cible ne bouge pas
            aside.append(relative + ("/" if folder else ""))

        try:
            for entry in sorted(os.scandir(work), key=lambda item: item.name):
                path = Path(entry.path)
                info = os.lstat(extended_path(path))
                link, folder = _is_link(info), stat.S_ISDIR(info.st_mode)
                if entry.name in self.SOURCE_DIRS and folder and not link:
                    self._shape_source(path, move)
                elif entry.name == TOOL_CACHE_DIR and folder and not link:
                    continue  # le cache de l'outil : vidé par `launch`
                elif (entry.name in GENERATED_FILES and _plain_file(info)
                      and _sha(Path(extended_path(path)).read_bytes()) == _sha(bytes(files[entry.name]))):
                    continue
                else:
                    move(path, folder and not link)
            for name in GENERATED_FILES:
                if not os.path.lexists(extended_path(work / name)):
                    self._write_file(name, bytes(files[name]))
        except StudioError:
            raise
        except (OSError, KeyError) as exc:
            raise StudioError(C.SYNC_FAILED, f"{type(exc).__name__}: the Studio workspace could not be brought back to its shape "
                                             "(a foreign file could not be set aside): not launched") from None
        finally:
            if destination is not None:
                self._rotate_edits()
        return tuple(aside)

    @staticmethod
    def _shape_source(root: Path, move: Callable[[Path, bool], None]) -> None:
        for current, dirs, names in os.walk(root):
            for name in list(dirs):
                path = Path(current) / name
                if _is_link(os.lstat(extended_path(path))):
                    dirs.remove(name)
                    move(path, False)
            for name in names:
                path = Path(current) / name
                if not _plain_file(os.lstat(extended_path(path))):
                    move(path, False)

    # ------------------------------------------------------------------ espace de travail (Slice 12)

    def workspace_diff(self) -> WorkspaceDiff:
        """Relevé de l'espace de travail contre sa base : octets des fichiers ajoutés ou changés, `None` pour un fichier supprimé,
        liens à part, et `digest` (`listing_digest` des octets LUS). Un lien, une jonction (fichier OU dossier, sur le chemin compris)
        n'est jamais suivi ni lu ; un fichier remplacé entre le relevé et la lecture, ou lu à travers un dossier devenu jonction, est
        vu (`_read_regular`) ; aucun chemin hors de `work/`."""

        work = self._work
        try:
            disk, base = self._scan_work(), self._manifest()
            changed: dict[str, bytes | None] = {}
            links: list[str] = [path for path, kind in disk.items() if kind == "link"]
            for path in sorted(set(disk) | set(base)):
                if path in links or disk.get(path) == base.get(path):
                    continue
                if path not in disk:
                    changed[path] = None
                    continue
                try:
                    safe_relative(path)
                except StudioError:
                    raise StudioError(C.PUBLISH_INVALID_FILE, f"{path[:120]!r} is not a plain relative path: refused") from None
                target = work.joinpath(*path.split("/"))
                try:
                    self._check_inside(target)
                except StudioError:
                    links.append(path)
                    continue
                data = self._read_regular(target, work)
                if data is None:
                    links.append(path)
                else:
                    changed[path] = data
        except StudioError:
            raise
        except OSError as exc:
            raise StudioError(C.SYNC_FAILED, f"{type(exc).__name__}: the Remotion Studio workspace could not be read") from None
        entries: dict[str, str | None] = {path: None if data is None else _sha(data) for path, data in changed.items()}
        entries.update({path: "link" for path in links})
        return WorkspaceDiff(base=base, changed=changed, links=tuple(sorted(links)), digest=listing_digest(entries))

    @staticmethod
    def _read_regular(target: Path, work: Path) -> bytes | None:
        """Octets d'un fichier ordinaire de `work`, ou `None` si c'est (ou c'est devenu pendant la lecture) un lien, une jonction, un
        lien dur, autre chose, ou si le fichier OUVERT n'est pas dans `work` (un dossier parent changé en jonction entre la vérification
        des dossiers et l'ouverture : QA Slice 12, I2). Trois preuves : `lstat` avant ; le descripteur ouvert (`fstat` : même fichier
        ordinaire, et son chemin réel lié au descripteur dans `work`) ; `lstat` après, du même fichier."""

        name = extended_path(target)
        before = os.lstat(name)
        if not _plain_file(before):
            return None
        with open(name, "rb") as handle:
            opened = os.fstat(handle.fileno())
            real = _final_path(handle.fileno(), target)
            data = handle.read()
        after = os.lstat(name)
        same = {(info.st_ino, info.st_dev) for info in (before, opened, after)}
        if not _plain_file(opened) or not _plain_file(after) or len(same) != 1:
            return None
        if not _inside(real, os.path.realpath(work)):
            return None
        return data

    def rebase_work(self, files: Mapping[str, bytes]) -> None:
        """Après une publication : la base devient la version publiée (ses empreintes), sans toucher un fichier du disque (le
        rechargement à chaud continue ; ce qui a été modifié pendant la publication reste une modification non publiée)."""

        for path in files:
            safe_relative(path)
        try:
            self._studio.mkdir(parents=True, exist_ok=True)
            record = self._studio / (MANIFEST_FILE + f".{secrets.token_hex(3)}.tmp")
            record.write_text(json.dumps({path: _sha(bytes(data)) for path, data in files.items()}, sort_keys=True), encoding="utf-8")
            os.replace(record, self._studio / MANIFEST_FILE)
        except OSError as exc:
            raise StudioError(C.STORE_FAILED, f"{type(exc).__name__}: the workspace base could not be recorded") from None

    def has_workspace(self) -> bool:
        return (self._work / D.WORK_ROOT_FILE).is_file()

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

    def bind_parent(self) -> None:
        """Écrit `parent.json` : le Core QUI surveille ce Studio (pid + heure de création). Le garde le relit à chaque passage et vérifie
        l'identité (un pid réutilisé par un autre programme n'est pas ce Core). Appelé au lancement ET à l'adoption par un nouveau Core."""

        ref = process_tree.make_process_ref(os.getpid())
        pid, _, created = ref.partition(":")
        self._studio.mkdir(parents=True, exist_ok=True)
        temporary = self._studio / f"parent.json.{secrets.token_hex(3)}.tmp"
        temporary.write_text(json.dumps({"pid": os.getpid(), "created": created}), encoding="utf-8")
        os.replace(temporary, self._studio / "parent.json")

    def _env(self, launch_id: str, idle_s: float) -> dict[str, str]:
        return process_tree.clean_env({"JARVIS_STUDIO_DIR": str(self._studio), "JARVIS_STUDIO_LAUNCH": launch_id, "NO_COLOR": "1",
                                       "JARVIS_STUDIO_IDLE_S": str(int(idle_s)),
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
        _remove_tree(self._work / "node_modules")  # le cache de webpack n'est pas scanné : jamais gardé d'un lancement à l'autre
        self.bind_parent()
        launch_id = secrets.token_hex(8)
        for stale in ("listening.json", "activity.json", "exit.json"):
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
