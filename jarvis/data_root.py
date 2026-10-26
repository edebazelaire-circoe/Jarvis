"""Racine des données locales de ce PC, hors du dépôt git (règle du dépôt, `CLAUDE.md`).

Chaque PC a ses propres bases (`state/jarvis.sqlite3`, `state/scene.sqlite3`),
son historique (`history/`) et sa mémoire d'exécution (`memory/`). Ils vivaient
sous `./data`, dans l'arbre de travail : un `git checkout` ou un rebase pouvait
les retirer du disque (incident du 2026-09-30, `docs/local-data.md`).

- `resolve_data_root` : `JARVIS_DATA_ROOT` si défini, sinon
  `~/.jarvis/instances/<dossier du dépôt>-<empreinte>/data`. Même réponse
  quel que soit le dossier courant. Une racine par copie du dépôt, pas une
  seule par PC : le bac à sable `jarvis-dst` et les worktrees des agents
  tournent sur le même PC que le JARVIS vivant, et deux Core ne doivent
  jamais partager une base.
- `adopt_legacy_data` : au premier démarrage de Core sur la nouvelle racine,
  copie les données de l'ancien `./data` du dépôt, base par base, par l'API de
  sauvegarde SQLite (WAL compris), vérifiées avant d'être mises en place.
  L'ancien dossier n'est jamais modifié ni supprimé ; seul un fichier témoin
  `ADOPTED.json` y est ajouté, pour qu'il ne soit jamais repris deux fois (par
  exemple après un déplacement du dépôt, qui changerait la racine par défaut
  et ferait sinon reprendre une copie périmée). Une donnée déjà présente dans
  la nouvelle racine n'est jamais écrasée.

Produit installé (`jarvis/installation.py`, `docs/local-data.md` › *Produit
installé*) : quand le paquet a posé `jarvis-product.json`, la racine par défaut
est `%LOCALAPPDATA%/CIRCOE/Jarvis/data` et le runtime
`%LOCALAPPDATA%/CIRCOE/Jarvis/runtime`, quel que soit le dossier
d'installation ou le dossier courant. `JARVIS_DATA_ROOT` / `JARVIS_RUNTIME_DIR`
gardent la priorité dans les deux modes (tests, administration). Le produit ne
reprend jamais l'ancien `./data` (qui serait dans le dossier du programme) ;
une reprise de profil est explicite (`adopt_data_root`), copie d'abord, vers
une racine vide seulement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
from typing import Mapping

from jarvis.adapters import safe_folders
from jarvis.adapters.global_context import GLOBAL_CONTEXT_DIR
from jarvis.adapters.safe_tree import UnsafeTree, copy_tree
from jarvis.environment import PROJECT_ROOT
from jarvis.installation import PRODUCT_HOME_LABEL, Installation, detect_installation

DATA_ROOT_ENV = "JARVIS_DATA_ROOT"
RUNTIME_DIR_ENV = "JARVIS_RUNTIME_DIR"
#: Ancien emplacement, dans le dépôt : lu seulement pour la reprise.
LEGACY_DATA_ROOT = PROJECT_ROOT / "data"
#: Les bases reprises, relatives à la racine.
_DATABASES = (Path("state") / "jarvis.sqlite3", Path("state") / "scene.sqlite3")
#: Dossiers de fichiers repris tels quels (fichiers absents de la cible seulement).
_TREES = (Path("history"), Path("memory"))
#: Contenu versionné du dépôt, pas une donnée locale : jamais repris.
_VERSIONED = {Path("memory") / "Jarvis-V1.md"}
ADOPTION_RECORD = "legacy-adoption.json"
#: Témoin écrit dans un dossier mémoire après la reprise de l'ancien `./data/memory`.
MEMORY_ADOPTION_RECORD = ".legacy-memory-adoption.json"
#: Témoin écrit dans l'ancien `./data` après une reprise réussie.
LEGACY_MARKER = "ADOPTED.json"


def default_data_root(project_root: Path = PROJECT_ROOT) -> Path:
    """`~/.jarvis/instances/<dossier>-<empreinte du chemin>/data` : propre à ce PC et à cette copie du dépôt."""

    resolved = Path(project_root).resolve()
    key = hashlib.sha256(os.path.normcase(str(resolved)).encode("utf-8")).hexdigest()[:8]
    return Path.home() / ".jarvis" / "instances" / f"{resolved.name}-{key}" / "data"


def resolve_data_root(environ: Mapping[str, str] | None = None, *, project_root: Path | None = None) -> Path:
    """`JARVIS_DATA_ROOT`, sinon `<maison du produit>/data` (produit installé), sinon la racine de développement.

    `project_root` est la racine du code : son empreinte nomme la racine de
    développement, et son marqueur `jarvis-product.json` dit si c'est un
    produit installé. La racine installée ne dépend jamais de ce chemin.
    """

    env = os.environ if environ is None else environ
    raw = env.get(DATA_ROOT_ENV, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    installation = detect_installation(env, code_root=project_root)
    if installation.installed:
        return installation.home.data.resolve()
    return default_data_root(project_root or PROJECT_ROOT).expanduser().resolve()


def default_runtime_root(environ: Mapping[str, str] | None = None, *, project_root: Path | None = None,
                         dev_default: Path | str = "./runtime") -> Path:
    """Runtime quand `JARVIS_RUNTIME_DIR` n'est pas fixé : `<maison du produit>/runtime` installé, sinon `dev_default`.

    `dev_default` garde le défaut historique de chaque appelant en développement
    (`./runtime` relatif au dossier courant pour Core et le Control Center,
    `<dépôt>/runtime` pour le hook de routage et les catalogues de modèles).
    """

    installation = detect_installation(os.environ if environ is None else environ, code_root=project_root)
    if installation.installed:
        return installation.home.runtime.resolve()
    return Path(dev_default).expanduser().resolve()


def resolve_runtime_root(environ: Mapping[str, str] | None = None, *, project_root: Path | None = None,
                         dev_default: Path | str = "./runtime") -> Path:
    """`JARVIS_RUNTIME_DIR` (relatif : au dossier courant), sinon `default_runtime_root`. Valeur vide = absente."""

    env = os.environ if environ is None else environ
    raw = str(env.get(RUNTIME_DIR_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return default_runtime_root(env, project_root=project_root, dev_default=dev_default)


def installation_diagnostics(data_root: Path, runtime_root: Path, environ: Mapping[str, str] | None = None, *,
                             project_root: Path | None = None) -> dict:
    """Bloc `installation` de `/v1/health` et du journal de démarrage : mode et provenance des racines.

    Aucun chemin absolu : la maison du produit est nommée `%LOCALAPPDATA%/CIRCOE/Jarvis`
    (jamais le nom de l'utilisateur), une racine imposée par variable est `override`,
    la racine de développement garde son seul nom de dossier (`<dépôt>-<empreinte>`).
    """

    env = os.environ if environ is None else environ
    installation: Installation = detect_installation(env, code_root=project_root)

    def describe(root: Path, sub: str, *, override: bool) -> dict:
        root = Path(root).resolve()
        if installation.installed and root == (getattr(installation.home, sub)).resolve():
            return {"source": "product_home", "label": PRODUCT_HOME_LABEL + "\\" + sub}
        if override:
            return {"source": "override", "label": None}
        if sub == "data" and root == default_data_root(project_root or PROJECT_ROOT).resolve():
            return {"source": "development_default", "label": root.parent.name}
        return {"source": "development_default" if sub == "runtime" else "followed", "label": None}

    return {"mode": installation.mode.value,
            "product_home": PRODUCT_HOME_LABEL if installation.installed else None,
            "data_root": describe(data_root, "data", override=bool(env.get(DATA_ROOT_ENV, "").strip())),
            "runtime_root": describe(runtime_root, "runtime", override=bool(str(env.get(RUNTIME_DIR_ENV) or "").strip()))}


@dataclass
class AdoptionReport:
    source: str
    target: str
    databases: dict[str, dict] = field(default_factory=dict)
    files_copied: int = 0
    skipped: list[str] = field(default_factory=list)
    #: Racine où l'ancien `./data` a déjà été repris, si ce n'est pas `target`
    #: et qu'elle existe encore : Core doit s'en servir (dépôt déplacé).
    adopted_elsewhere: str | None = None

    @property
    def adopted(self) -> bool:
        return bool(self.databases) or self.files_copied > 0

    def to_payload(self) -> dict:
        return {"source": self.source, "target": self.target, "databases": self.databases,
                "files_copied": self.files_copied, "skipped": self.skipped}


class LegacyAdoptionError(RuntimeError):
    """Une base ancienne n'a pas pu être copiée proprement : rien n'a été mis en place pour elle."""


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in tables}


def _copy_database(source: Path, target: Path) -> dict:
    """Copier une base (et son WAL) par l'API de sauvegarde, vérifier, puis renommer."""

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.adopting.partial")
    partial.unlink(missing_ok=True)
    # Lecture seule : l'ancienne base n'est jamais écrite. Le WAL est lu avec
    # elle, si bien que la copie contient tout ce qui y a été validé.
    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    try:
        check = src.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise LegacyAdoptionError(f"{source}: integrity_check {check!r}: base ancienne laissée en place, non reprise")
        expected = _counts(src)
        dst = sqlite3.connect(partial)
        try:
            src.backup(dst)
            copied = _counts(dst)
            copy_check = dst.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dst.close()
    finally:
        src.close()
    if copy_check != "ok" or copied != expected:
        partial.unlink(missing_ok=True)
        raise LegacyAdoptionError(f"{source}: la copie diffère de l'original ({copy_check}, {copied} != {expected})")
    os.replace(partial, target)
    return {"from": str(source), "rows": expected}


def adopt_legacy_data(target: Path, legacy: Path = LEGACY_DATA_ROOT) -> AdoptionReport:
    """Reprendre les données de l'ancien `./data` dans `target`, sans jamais écraser ni toucher la source."""

    target = Path(target).resolve()
    legacy = Path(legacy).resolve()
    report = AdoptionReport(source=str(legacy), target=str(target))
    if target == legacy or not legacy.is_dir():
        return report
    marker = legacy / LEGACY_MARKER
    if marker.exists():
        try:
            adopted_by = json.loads(marker.read_text(encoding="utf-8")).get("target")
        except (OSError, ValueError, AttributeError):
            adopted_by = None
        if adopted_by != str(target):
            report.skipped.append(f"ancien dossier déjà repris vers {adopted_by} : non repris une seconde fois")
            if adopted_by and Path(adopted_by).is_dir():
                report.adopted_elsewhere = adopted_by
            return report
    for relative in _DATABASES:
        source, destination = legacy / relative, target / relative
        if os.path.lexists(destination) or os.path.lexists(destination.with_name(destination.name + "-wal")):
            if source.exists():
                report.skipped.append(f"{relative.as_posix()}: déjà présent dans la nouvelle racine")
            continue
        if not source.is_file():
            if source.with_name(source.name + "-wal").exists():
                report.skipped.append(f"{relative.as_posix()}: -wal sans sa base dans l'ancien dossier, laissé en place")
            continue
        report.databases[relative.as_posix()] = _copy_database(source, destination)
    for tree in _TREES:
        root = legacy / tree
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(legacy)
            if relative in _VERSIONED or ".jarvis" in relative.parts:
                continue
            destination = target / relative
            if path.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if destination.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            report.files_copied += 1
    # `CONTEXT_GLOBAL` (docs/context-global.md) : repris en bloc, seulement si la nouvelle racine n'en a pas.
    # Jamais fusionné fichier par fichier : un fichier que l'agent a supprimé doit rester supprimé.
    context = legacy / GLOBAL_CONTEXT_DIR
    if context.is_dir():
        if os.path.lexists(target / GLOBAL_CONTEXT_DIR):
            report.skipped.append(f"{GLOBAL_CONTEXT_DIR}: déjà présent dans la nouvelle racine")
        else:
            report.files_copied += _copy_tree_staged(context, target / GLOBAL_CONTEXT_DIR)
    if report.adopted:
        record = target / ADOPTION_RECORD
        payload = {"adopted_at": datetime.now(timezone.utc).isoformat(), **report.to_payload()}
        previous = []
        if record.exists():
            try:
                previous = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                previous = []
        record.write_text(json.dumps([*(previous if isinstance(previous, list) else []), payload],
                                     ensure_ascii=False, indent=2), encoding="utf-8")
        if not marker.exists():
            marker.write_text(json.dumps({"target": str(target), "adopted_at": payload["adopted_at"],
                                          "note": "données reprises hors du dépôt, voir docs/local-data.md"},
                                         ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def adopt_legacy_memory(memory_dir: Path, legacy: Path = LEGACY_DATA_ROOT) -> int:
    """Copier l'ancien `./data/memory` dans `memory_dir`, une seule fois ; renvoie le nombre de fichiers copiés.

    Pour le chemin V1 (`RuntimeConfig.memory_dir`), qui n'ouvre pas Core et ne
    passe donc pas par `adopt_legacy_data`. Même règles : copie seulement (la
    source n'est ni modifiée ni supprimée, aucun témoin n'y est ajouté), un
    fichier déjà présent n'est jamais écrasé, `Jarvis-V1.md` (contenu versionné)
    et l'index dérivé `.jarvis/` sont ignorés, les liens symboliques aussi. Un
    témoin dans `memory_dir` évite de rejouer la copie, sans quoi une note
    supprimée ici reviendrait au démarrage suivant ; l'ancien dossier déjà repris
    par `adopt_legacy_data` (`ADOPTED.json`) n'est pas repris une seconde fois.
    """

    memory_dir = Path(memory_dir).resolve()
    source_root = Path(legacy).resolve() / "memory"
    record = memory_dir / MEMORY_ADOPTION_RECORD
    if source_root == memory_dir or not source_root.is_dir() or record.exists():
        return 0
    if (Path(legacy).resolve() / LEGACY_MARKER).exists():
        return 0
    copied = 0
    for path in sorted(source_root.rglob("*")):
        relative = path.relative_to(source_root)
        if (Path("memory") / relative) in _VERSIONED or ".jarvis" in relative.parts or path.is_symlink():
            continue
        destination = memory_dir / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            copied += 1
    if copied:
        record.write_text(json.dumps({"adopted_at": datetime.now(timezone.utc).isoformat(), "source": str(source_root),
                                      "files_copied": copied}, ensure_ascii=False, indent=2), encoding="utf-8")
    return copied


def _copy_tree_staged(source: Path, destination: Path) -> int:
    """Copier un dossier sûr (aucun lien suivi, tailles vérifiées) à côté, puis le mettre en place par renommage."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.adopting-{os.urandom(4).hex()}")
    try:
        count = copy_tree(source, staging)
        os.replace(staging, destination)
    except UnsafeTree as exc:
        shutil.rmtree(staging, ignore_errors=True)  # notre propre dossier de copie, jamais la source
        raise LegacyAdoptionError(f"{source.name}: {exc} : dossier ancien laissé en place, non repris") from exc
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return count.files


# -- reprise explicite d'un profil complet -----------------------------------------------------------------------

#: Témoin écrit dans la racine cible après une reprise de profil.
PROFILE_ADOPTION_RECORD = "profile-adoption.json"
#: Préfixes de dossiers jamais repris : restes d'écriture atomique, d'une purge interrompue, d'une copie en cours.
_TRANSIENT_DIR_PREFIXES = (".staging-", ".purging-", ".adopting-")
#: Suffixes de fichiers jamais repris : écritures inachevées.
_TRANSIENT_FILE_SUFFIXES = (".partial", ".tmp")


class ProfileAdoptionError(RuntimeError):
    """La reprise d'un profil est refusée ou a échoué : la cible n'a pas été mise en place, la source est intacte."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass
class ProfileAdoptionReport:
    source: str
    target: str
    databases: dict[str, dict] = field(default_factory=dict)
    files_copied: int = 0
    bytes_copied: int = 0
    skipped: list[str] = field(default_factory=list)
    global_context_files: int = 0

    def to_payload(self) -> dict:
        return {"source": self.source, "target": self.target, "databases": self.databases,
                "files_copied": self.files_copied, "bytes_copied": self.bytes_copied, "skipped": self.skipped,
                "global_context_files": self.global_context_files}


def _profile_skip_reason(relative: Path, is_dir: bool) -> str | None:
    """Pourquoi une entrée d'un profil n'est pas reprise, ou `None` si elle l'est."""

    parts = relative.parts
    name = parts[-1]
    if is_dir and name.startswith(_TRANSIENT_DIR_PREFIXES):
        return "reste d'une écriture interrompue"
    if not is_dir and name.endswith(_TRANSIENT_FILE_SUFFIXES):
        return "écriture inachevée"
    if parts[:1] == ("memory",) and ".jarvis" in parts:
        return "index dérivé, reconstruit"
    if parts[:1] == ("local_capabilities",) and len(parts) >= 3 and parts[2] in {"runtime", "compiled"}:
        return "moteur ou cache de capacité locale, à réinstaller"
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _inventory_profile(source: Path, report: ProfileAdoptionReport) -> tuple[list[Path], list[Path], list[Path]]:
    """`(dossiers, bases, fichiers)` relatifs à reprendre. Un lien, une jonction ou une entrée spéciale refuse tout."""

    folders: list[Path] = []
    databases: list[Path] = []
    files: list[Path] = []

    def visit(current: Path) -> None:
        for entry in sorted(os.scandir(current), key=lambda item: item.name):
            path = Path(entry.path)
            relative = path.relative_to(source)
            info = os.lstat(path)
            if safe_folders.is_link(info):
                raise ProfileAdoptionError("source_unsafe", f"{relative.as_posix()}: lien, jonction ou point d'analyse refusé")
            is_dir = stat.S_ISDIR(info.st_mode)
            if not is_dir and not stat.S_ISREG(info.st_mode):
                raise ProfileAdoptionError("source_unsafe", f"{relative.as_posix()}: ni dossier ni fichier ordinaire")
            reason = _profile_skip_reason(relative, is_dir)
            if reason:
                report.skipped.append(f"{relative.as_posix()}: {reason}")
                continue
            if is_dir:
                folders.append(relative)
                visit(path)
                continue
            if relative.name.endswith(("-wal", "-shm")):
                if not path.with_name(relative.name[:-4]).is_file():
                    # Doctrine CLAUDE.md : un -wal sans sa base se met de côté, il ne se rejoue jamais ailleurs.
                    report.skipped.append(f"{relative.as_posix()}: -wal/-shm sans sa base, laissé dans la source")
                continue  # avec sa base : son contenu validé passe par l'API de sauvegarde
            (databases if relative.suffix == ".sqlite3" else files).append(relative)

    visit(source)
    return folders, databases, files


def adopt_data_root(source: Path, target: Path) -> ProfileAdoptionReport:
    """Reprendre un profil complet (`source`, une racine de données) dans `target`, qui doit être vide ou absent.

    Décision Slice 02 (`docs/local-data.md` › *Reprise d'un profil*) : jamais
    automatique, jamais vers une racine qui a déjà du contenu (pas de fusion de
    deux racines). Copie d'abord dans un dossier voisin : chaque base `*.sqlite3`
    par l'API de sauvegarde (lecture seule, WAL compris, `integrity_check` et
    comptes de lignes), chaque fichier vérifié par SHA-256, `CONTEXT_GLOBAL`
    compris. Mise en place par un seul renommage, après toutes les vérifications.
    La source n'est ni modifiée ni marquée. En cas d'échec, rien n'est en place.
    """

    source, target = Path(source).resolve(), Path(target).resolve()
    report = ProfileAdoptionReport(source=str(source), target=str(target))
    if source == target or source in target.parents or target in source.parents:
        raise ProfileAdoptionError("roots_overlap", "la source et la cible se chevauchent")
    if not source.is_dir():
        raise ProfileAdoptionError("source_missing", "la racine source n'existe pas")
    if os.path.lexists(target):
        if safe_folders.is_link(os.lstat(target)) or not target.is_dir() or any(target.iterdir()):
            raise ProfileAdoptionError("target_not_empty", "la racine cible a déjà du contenu : jamais de fusion")
    folders, databases, files = _inventory_profile(source, report)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.adopting-{os.urandom(4).hex()}")
    staging.mkdir()
    try:
        for relative in folders:
            (staging / relative).mkdir(parents=True, exist_ok=True)
        for relative in databases:
            report.databases[relative.as_posix()] = _copy_database(source / relative, staging / relative)
        for relative in files:
            origin, copy = source / relative, staging / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, copy, follow_symlinks=False)
            if _sha256(origin) != _sha256(copy):
                raise ProfileAdoptionError("copy_mismatch", f"{relative.as_posix()}: la copie diffère de l'original")
            report.files_copied += 1
            report.bytes_copied += copy.stat().st_size
            if relative.parts[0] == GLOBAL_CONTEXT_DIR:
                report.global_context_files += 1
        if (source / GLOBAL_CONTEXT_DIR).is_dir() and not (staging / GLOBAL_CONTEXT_DIR).is_dir():
            raise ProfileAdoptionError("global_context_missing", f"{GLOBAL_CONTEXT_DIR} absent de la copie")
        (staging / PROFILE_ADOPTION_RECORD).write_text(json.dumps(
            {"adopted_at": datetime.now(timezone.utc).isoformat(), **report.to_payload()},
            ensure_ascii=False, indent=2), encoding="utf-8")
        if os.path.lexists(target):
            os.rmdir(target)  # vide (vérifié plus haut) ; os.rmdir refuse un dossier rempli entre-temps
        os.replace(staging, target)
    except (LegacyAdoptionError, sqlite3.Error) as exc:
        shutil.rmtree(staging, ignore_errors=True)  # seulement notre dossier de copie, jamais la source
        raise ProfileAdoptionError("database_copy_failed", str(exc)) from exc
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return report
