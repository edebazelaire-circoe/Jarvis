"""Le fichier `<runtime>/brain-config.json` : la tendance de délégation des cerveaux, révisée (docs/brain-config.md).

Seule valeur **propre** à la configuration des cerveaux : tout le reste (modèle, fournisseur, instructions,
activation) a déjà un propriétaire et n'est jamais copié ici.

Pourquoi un fichier dédié et non une clé de `control-center-settings.json` : `POST /api/settings` relit ce
fichier, y applique son corps puis le réécrit entier, **sans révision ni verrou partagé**. Une clé à l'intérieur
pourrait être perdue par un enregistrement concurrent de la page Réglages (lecture avant notre écriture,
réécriture après), et la révision de ce réglage (C8 : `409` sur révision périmée) ne protégerait rien. Même choix
que la politique par rôle (`subagent_role_routing.py`). Le fichier a un seul écrivain (`BrainConfigStore`), sa
révision, et il est lu à froid par trois lecteurs hors du Control Center :

- le hook `PreToolUse` (`routing_hook.py`), à **chaque** appel `Agent` : refus quand `core` vaut `never` ;
- `ClaudeLocalAgent.start` (`claude_local.py`), à chaque lancement d'un CLI cerveau ou d'un job Back Brain : outil
  `Agent` retiré pour `never`, consigne du prompt par niveau ;
- la projection du graphe (`architecture_graph.py`) : liaison gouvernée `core.agents->subagents.spawn`.

Forme (`schema_version` 1) ::

    {"schema_version": 1, "revision": 2,
     "brains": {"core": {"delegation": "never", "updated_at": "2026-10-23T12:00:00+00:00"}}}

Absent = premier démarrage : chaque cerveau a `standard`, révision 0, rien n'est écrit (aucune migration). Une
entrée de cerveau inconnu est conservée telle quelle au fil des écritures. **Lire est tolérant, écrire est
strict** : un fichier illisible se lit comme le défaut (`standard`, le comportement d'avant), se dit au journal
et dans le descripteur, et n'est jamais réécrit (écriture refusée `brain_config_store_unreadable`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.domain.brain_config import (
    DEFAULT_DELEGATION, REVISION_STALE, STORE_UNREADABLE, WRITE_FAILED, BrainConfigError, DelegationTendency,
)

STORE_FILE = "brain-config.json"
SCHEMA_VERSION = 1
REVISION_PREFIX = "bc-"
#: Les cerveaux qui portent une tendance aujourd'hui : seul `core` lance réellement des sous-agents.
DELEGATING_BRAINS = frozenset({"core"})

UNREADABLE_REASON = ("Le fichier de configuration des cerveaux est illisible ; il n'est pas réécrit et chaque "
                     "cerveau garde le comportement standard. Mettez-le de côté pour repartir du défaut.")


def format_revision(revision: int) -> str:
    return f"{REVISION_PREFIX}{revision}"


@dataclass(frozen=True, slots=True)
class BrainConfigDocument:
    revision: int = 0
    delegation: Mapping[str, DelegationTendency] = field(default_factory=dict)
    #: Valeur enregistrée mais inconnue, par cerveau : rapportée, jamais réécrite en silence.
    invalid: Mapping[str, str] = field(default_factory=dict)

    def delegation_for(self, brain_id: str) -> DelegationTendency:
        return self.delegation.get(brain_id, DEFAULT_DELEGATION)


@dataclass(frozen=True, slots=True)
class LoadedBrainConfig:
    document: BrainConfigDocument
    raw: dict[str, Any]
    #: `""` si le fichier est lisible ou absent ; sinon `brain_config_store_unreadable`.
    error_code: str = ""
    error_reason: str = ""

    @property
    def revision_token(self) -> str:
        return format_revision(self.document.revision)


class _Unreadable(ValueError):
    pass


def _parse(raw: Mapping[str, Any]) -> BrainConfigDocument:
    revision = raw.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise _Unreadable("« revision » doit être un entier positif")
    brains = raw.get("brains", {})
    if not isinstance(brains, Mapping):
        raise _Unreadable("« brains » doit être un objet")
    delegation: dict[str, DelegationTendency] = {}
    invalid: dict[str, str] = {}
    for brain_id, entry in brains.items():
        if not isinstance(entry, Mapping):
            raise _Unreadable(f"l'entrée « {str(brain_id)[:24]} » doit être un objet")
        if "delegation" not in entry:
            continue
        value = entry["delegation"]
        try:
            delegation[str(brain_id)] = DelegationTendency(value)
        except ValueError:
            # Une valeur inconnue (version future, édition à la main) n'est pas un fichier illisible : elle est
            # rapportée pour ce cerveau, qui garde le défaut, et l'écriture suivante la remplace explicitement.
            invalid[str(brain_id)] = str(value)[:40]
    return BrainConfigDocument(revision, delegation, invalid)


def load(runtime_root: Path | str) -> LoadedBrainConfig:
    """Le document enregistré, sans jamais lever. Absent = défaut partout, révision 0."""

    path = Path(runtime_root) / STORE_FILE
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return LoadedBrainConfig(BrainConfigDocument(), {})  # normal au premier démarrage : le défaut s'applique
    except OSError as exc:
        return LoadedBrainConfig(BrainConfigDocument(), {}, STORE_UNREADABLE,
                                 f"{UNREADABLE_REASON} ({type(exc).__name__})")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return LoadedBrainConfig(BrainConfigDocument(), {}, STORE_UNREADABLE,
                                 f"{UNREADABLE_REASON} (JSON invalide, ligne {exc.lineno})")
    if not isinstance(raw, dict):
        return LoadedBrainConfig(BrainConfigDocument(), {}, STORE_UNREADABLE, f"{UNREADABLE_REASON} (objet attendu)")
    try:
        document = _parse(raw)
    except _Unreadable as exc:
        return LoadedBrainConfig(BrainConfigDocument(), {}, STORE_UNREADABLE, f"{UNREADABLE_REASON} ({exc})")
    return LoadedBrainConfig(document, raw)


def delegation_for(runtime_root: Path | str, brain_id: str = "core") -> DelegationTendency:
    """Pour les lecteurs à froid (hook, lancement du CLI, graphe) : la tendance effective, jamais d'exception."""

    return load(runtime_root).document.delegation_for(brain_id)


class BrainConfigStore:
    """Seul écrivain de `brain-config.json` : révision vérifiée, écriture atomique (temporaire puis remplacement)."""

    def __init__(self, runtime_root: Path | str) -> None:
        self.runtime_root = Path(runtime_root)
        self.path = self.runtime_root / STORE_FILE
        self._lock = RLock()

    def load(self) -> LoadedBrainConfig:
        return load(self.runtime_root)

    def set_delegation(self, brain_id: str, level: DelegationTendency, *, base_revision: object) -> LoadedBrainConfig:
        with self._lock:
            loaded = self.load()
            if loaded.error_code:
                raise BrainConfigError(loaded.error_code, loaded.error_reason, field="delegation")
            if base_revision != loaded.revision_token:
                raise BrainConfigError(REVISION_STALE, "La configuration des cerveaux a changé depuis votre lecture "
                                       f"(révision actuelle {loaded.revision_token}) ; relisez-la.", field="delegation")
            raw = dict(loaded.raw)
            brains = dict(raw.get("brains") or {})
            entry = dict(brains.get(brain_id) or {})
            entry.update({"delegation": level.value,
                          "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            brains[brain_id] = entry
            raw.update({"schema_version": SCHEMA_VERSION, "revision": loaded.document.revision + 1, "brains": brains})
            self.runtime_root.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                replace_with_retry(tmp, self.path)
            except OSError as exc:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass  # argued: the temporary holds no secret; the write failure below is what the caller sees
                raise BrainConfigError(WRITE_FAILED, f"Tendance de délégation non enregistrée ({type(exc).__name__}) ; "
                                       "rien n'a changé.", field="delegation") from exc
            return LoadedBrainConfig(_parse(raw), raw)
