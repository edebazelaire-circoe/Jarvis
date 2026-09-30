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
from typing import Mapping

from jarvis.environment import PROJECT_ROOT

DATA_ROOT_ENV = "JARVIS_DATA_ROOT"
#: Ancien emplacement, dans le dépôt : lu seulement pour la reprise.
LEGACY_DATA_ROOT = PROJECT_ROOT / "data"
#: Les bases reprises, relatives à la racine.
_DATABASES = (Path("state") / "jarvis.sqlite3", Path("state") / "scene.sqlite3")
#: Dossiers de fichiers repris tels quels (fichiers absents de la cible seulement).
_TREES = (Path("history"), Path("memory"))
#: Contenu versionné du dépôt, pas une donnée locale : jamais repris.
_VERSIONED = {Path("memory") / "Jarvis-V1.md"}
ADOPTION_RECORD = "legacy-adoption.json"
#: Témoin écrit dans l'ancien `./data` après une reprise réussie.
LEGACY_MARKER = "ADOPTED.json"


def default_data_root(project_root: Path = PROJECT_ROOT) -> Path:
    """`~/.jarvis/instances/<dossier>-<empreinte du chemin>/data` : propre à ce PC et à cette copie du dépôt."""

    resolved = Path(project_root).resolve()
    key = hashlib.sha256(os.path.normcase(str(resolved)).encode("utf-8")).hexdigest()[:8]
    return Path.home() / ".jarvis" / "instances" / f"{resolved.name}-{key}" / "data"


def resolve_data_root(environ: Mapping[str, str] | None = None, *, project_root: Path = PROJECT_ROOT) -> Path:
    env = os.environ if environ is None else environ
    raw = env.get(DATA_ROOT_ENV, "").strip()
    return (Path(raw) if raw else default_data_root(project_root)).expanduser().resolve()


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
