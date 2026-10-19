"""Les instructions effectives des rôles de sous-agent, posées dans un fichier que le hook lit sans réseau.

Même schéma que `loadout_snapshot` : le hook `PreToolUse` (`routing_hook`) est un
processus court qui ne parle ni à Core ni au Control Center. Les surcharges que
l'utilisateur a enregistrées (prompts `subagent_role.<id>`, Settings >
Sous-agents) sont donc recopiées dans `subagent-roles.json`, à la racine runtime :

- **écrire** : `refresh(runtime_root, overrides_document)`, appelé au lancement
  du CLI et après chaque édition ou réinitialisation via `POST /api/prompts/{id}` ;
  l'écriture est atomique et lève `OSError` si le disque refuse ;
- **lire** : `read_overrides(runtime_root)` rend `{id du rôle: texte}`, seulement
  pour les rôles modifiés. Fichier absent : `{}`, les défauts du code s'appliquent.
  Le fichier est une entrée non fiable : taille bornée, schéma vérifié, texte
  nettoyé et reborné ; un fichier illisible lève, et le hook se replie alors sur
  les défauts du code.

Seules les surcharges y figurent : le défaut vit dans le code, et un défaut
changé par une mise à jour n'est jamais masqué par une vieille copie.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from jarvis.domain.prompt_registry import MAX_OVERRIDE_TEXT
from jarvis.domain.subagent_roles import PROMPT_PREFIX, ROLES

SNAPSHOT_FILE = "subagent-roles.json"
SNAPSHOT_SCHEMA = 1
#: Cinq textes de 8 Ko au plus : au-delà, le fichier n'est pas le nôtre.
MAX_SNAPSHOT_BYTES = 256 * 1024

_ROLE_IDS = frozenset(role.id for role in ROLES)


def snapshot_path(runtime_root: Path) -> Path:
    return Path(runtime_root) / SNAPSHOT_FILE


def effective_overrides(registry: Any, overrides_document: object | None) -> dict[str, str]:
    """`{id du rôle: texte}` des rôles dont le texte effectif diffère du défaut.

    Calculé par le registre des prompts lui-même (`inspect`) : une surcharge
    périmée (défaut changé depuis) ou invalide y retombe sur le défaut, comme
    partout ailleurs.
    """
    inspected = registry.inspect(overrides_document)
    result: dict[str, str] = {}
    for layer in inspected["layers"]:
        identifier = str(layer.get("prompt_id") or "")
        role_id = identifier[len(PROMPT_PREFIX):] if identifier.startswith(PROMPT_PREFIX) else ""
        if role_id in _ROLE_IDS and layer.get("current_text") != layer.get("default_text"):
            result[role_id] = str(layer["current_text"])
    return result


def write_snapshot(runtime_root: Path, overrides: Mapping[str, str], *, now: datetime | None = None) -> Path:
    """Écrit l'instantané (remplacement atomique) et rend son chemin. Lève `OSError` si le disque refuse."""
    from jarvis.adapters.file_replace import replace_with_retry  # paresseux : le hook ne fait que lire

    payload: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "written_at": (now or datetime.now(timezone.utc)).isoformat(),
        "overrides": {key: str(text) for key, text in overrides.items() if key in _ROLE_IDS},
    }
    target = snapshot_path(runtime_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".subagent-roles-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(Path(tmp), target)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return target


def refresh(runtime_root: Path, overrides_document: object | None) -> dict[str, str]:
    """Recalcule les surcharges effectives depuis le document des prompts et réécrit l'instantané.

    Rend les surcharges écrites. Lève `OSError` (disque) ou `PromptError` (document invalide) : l'appelant
    journalise, le hook garde alors l'ancien instantané ou les défauts.
    """
    from jarvis.runtime.prompt_catalog import default_prompt_registry  # paresseux : le catalogue importe beaucoup

    overrides = effective_overrides(default_prompt_registry(), overrides_document)
    write_snapshot(runtime_root, overrides)
    return overrides


def _clean(text: str) -> str:
    """Le texte lu : imprimable (sauts de ligne permis), borné."""
    return "".join(ch for ch in text if ch == "\n" or ch.isprintable())[:MAX_OVERRIDE_TEXT].strip()


def read_overrides(runtime_root: Path) -> dict[str, str]:
    """Les surcharges des rôles connus, ou `{}` : fichier absent, trop gros ou d'un autre schéma.

    Lève `ValueError` (JSON illisible) ou `OSError` : le hook avale et prend les défauts du code.
    """
    path = snapshot_path(runtime_root)
    try:
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return {}
    except FileNotFoundError:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict) or raw.get("schema") != SNAPSHOT_SCHEMA:
        return {}
    entries = raw.get("overrides")
    if not isinstance(entries, dict):
        return {}
    cleaned = {key: _clean(text) for key, text in entries.items() if key in _ROLE_IDS and isinstance(text, str)}
    return {key: text for key, text in cleaned.items() if text}
