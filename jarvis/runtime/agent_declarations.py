"""Le registre local des déclarations de sous-agents : du hook au Control Center, sans réseau (Slice 05).

Le hook `PreToolUse` (`routing_hook.py`) est un processus court et hors ligne :
il ne peut ni attendre Core ni l'appeler sans retarder le lancement. Il dépose
donc chaque déclaration (`mission_history.AgentDeclarationFact`, contrat v1)
dans un **fichier par fait**, écrit atomiquement (fichier temporaire puis
renommage), sous `<runtime>/agent-declarations/`. Le Control Center relit ce
dossier (`scan`), joint chaque fait à la tâche suivie de même `tool_use_id`, et
le remet à Core (`declaration_relay.py`).

Un fichier par fait plutôt qu'un journal partagé : des hooks lancés en
parallèle (appels `Agent` simultanés) n'écrivent jamais dans le même fichier,
et un fait se lit entier ou pas du tout.

- Nom : `<ms>-<tool_use_id>.json` (horloge du hook) ; le compte des fichiers
  récents sert la borne de sûreté des lancements (`recent_count`) sans rien lire ;
- borne : au plus `MAX_FILES` fichiers ; au-delà, le hook n'écrit plus (refus
  consigné) — l'agent part, sa déclaration est perdue et cela se voit ;
- rétention : le hook et le Control Center élaguent les faits plus vieux que
  `RETENTION_S` (`prune`). Un fait n'est pas effacé dès sa remise à Core : le
  Control Center redémarré le relit et Core répond `duplicate`, et il compte
  dans la borne de sûreté ;
- un fichier illisible ou hors contrat n'est jamais réparé : `scan` le signale
  (`invalid`) et le laisse à l'élagage.

Contrat : `docs/agent-orchestration.md` § Registre des déclarations.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
import time

from jarvis.domain.mission_history import AgentDeclarationFact, MissionHistoryError

DECLARATIONS_DIR = "agent-declarations"
#: Fichiers au plus dans le dossier : une borne de disque, très au-dessus d'un usage normal.
MAX_FILES = 1_024
#: Âge au-delà duquel un fait est élagué (secondes). Plus long que la fenêtre de la borne de sûreté.
RETENTION_S = 3_600
#: Taille maximale d'un fait sur disque : au-delà, le fichier n'est pas lu.
MAX_FACT_BYTES = 8_192
_NAME = re.compile(r"(\d{10,16})-([A-Za-z0-9_.-]{1,128})\.json\Z")


class DeclarationLedgerFull(OSError):
    """Le dossier des déclarations a atteint `MAX_FILES` : le fait n'est pas écrit."""


def ledger_dir(runtime_root: Path) -> Path:
    return Path(runtime_root) / DECLARATIONS_DIR


def _now_ms() -> int:
    return int(time.time() * 1000)


def _entries(folder: Path) -> list[tuple[int, str, Path]]:
    """(horodatage ms, `tool_use_id`, chemin) des faits du dossier, sans lire leur contenu."""

    try:
        names = os.listdir(folder)
    except FileNotFoundError:
        return []  # intentional: no folder yet is the normal first-run state (no declaration written)
    entries = []
    for name in names:
        found = _NAME.fullmatch(name)
        if found is not None:
            entries.append((int(found.group(1)), found.group(2), folder / name))
    entries.sort()
    return entries


def write_fact(runtime_root: Path, fact: AgentDeclarationFact, *, now_ms: int | None = None) -> Path:
    """Écrire `fact` atomiquement ; rend le chemin. Lève `DeclarationLedgerFull` ou `OSError`."""

    folder = ledger_dir(runtime_root)
    folder.mkdir(parents=True, exist_ok=True)
    if len(_entries(folder)) >= MAX_FILES:
        raise DeclarationLedgerFull(f"{MAX_FILES} declarations already waiting in {folder}")
    stamp = now_ms if now_ms is not None else _now_ms()
    target = folder / f"{stamp}-{fact.tool_use_id}.json"
    body = json.dumps(fact.to_payload(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handle, temp = tempfile.mkstemp(prefix=".fact-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(body)
        os.replace(temp, target)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass  # intentional: the temp file is already gone or the folder is unwritable; the write error is raised
        raise
    return target


def recent_count(runtime_root: Path, window_s: float, *, now_ms: int | None = None) -> int:
    """Faits écrits dans les `window_s` dernières secondes (d'après leur nom, sans les lire)."""

    floor = (now_ms if now_ms is not None else _now_ms()) - int(window_s * 1000)
    return sum(1 for stamp, _tool_use_id, _path in _entries(ledger_dir(runtime_root)) if stamp >= floor)


def prune(runtime_root: Path, *, older_than_s: float = RETENTION_S, now_ms: int | None = None) -> int:
    """Effacer les faits plus vieux que `older_than_s` ; rend le nombre effacé. Un échec d'effacement est ignoré
    (le fichier sera retenté au prochain élagage) ; la lecture du dossier peut lever `OSError`."""

    floor = (now_ms if now_ms is not None else _now_ms()) - int(older_than_s * 1000)
    removed = 0
    for stamp, _tool_use_id, path in _entries(ledger_dir(runtime_root)):
        if stamp >= floor:
            break
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue  # intentional: a file still open elsewhere is retried at the next prune
    return removed


@dataclass(frozen=True, slots=True)
class ScannedFact:
    name: str
    fact: AgentDeclarationFact


@dataclass(frozen=True, slots=True)
class ScanResult:
    facts: tuple[ScannedFact, ...]
    #: Noms des fichiers illisibles ou hors contrat, avec la raison (jamais leur contenu).
    invalid: tuple[tuple[str, str], ...]


def scan(runtime_root: Path, *, seen: Iterable[str] = ()) -> ScanResult:
    """Les faits du dossier dont le nom n'est pas dans `seen`, dans l'ordre d'écriture. Peut lever `OSError`."""

    known = set(seen)
    facts: list[ScannedFact] = []
    invalid: list[tuple[str, str]] = []
    for _stamp, _tool_use_id, path in _entries(ledger_dir(runtime_root)):
        if path.name in known:
            continue
        try:
            if path.stat().st_size > MAX_FACT_BYTES:
                raise ValueError(f"declaration exceeds {MAX_FACT_BYTES} bytes")
            payload = json.loads(path.read_text(encoding="utf-8"))
            fact = AgentDeclarationFact.from_payload(payload)
        except FileNotFoundError:
            continue  # intentional: pruned between the listing and the read
        except (OSError, ValueError, MissionHistoryError) as exc:
            invalid.append((path.name, f"{type(exc).__name__}: {str(exc)[:160]}"))
            continue
        facts.append(ScannedFact(path.name, fact))
    return ScanResult(tuple(facts), tuple(invalid))
