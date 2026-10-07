"""Le loadout résolu, posé dans un fichier que le hook lit sans réseau (Slice 09).

Le hook `PreToolUse` (`routing_hook`) est un processus court, relancé à chaque
appel d'outil : il ne parle ni à Core ni à un fournisseur. Core écrit donc, hors
du hook, un instantané `loadout-snapshot.json` dans la racine runtime ; le hook en
lit une ligne, le manifeste du couple (profil, rôle) de l'appel.

- **écrire** : `write_loadout_snapshot(runtime_root, views)`, atomique, appelé par
  le câblage de Core quand les assets, les skills ou les réglages changent ;
- **lire** : `read_manifest(runtime_root, profile, role)` rend le texte du
  manifeste, ou `""` quand il n'y en a pas. Le fichier est une entrée non fiable :
  taille bornée, texte reborné et nettoyé, marque vérifiée. Toute panne se solde
  par `""` ou par une exception que l'appelant avale ; jamais par un appel perdu.

Le fichier porte aussi, par clé, la vue complète (raisons, versions, perdants,
pannes de fournisseur) : c'est la donnée d'inspection du loadout effectif.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from jarvis.domain.knowledge import MAX_LOADOUT_MANIFEST_CHARS
from jarvis.domain.loadout_view import MANIFEST_MARK, LoadoutView, render_manifest
from jarvis.domain.memory_settings import loadout_key

SNAPSHOT_FILE = "loadout-snapshot.json"
SNAPSHOT_SCHEMA = 1
#: Au-delà, le fichier est ignoré : un hook ne lit pas un fichier de plusieurs mégaoctets à chaque appel.
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024


def snapshot_path(runtime_root: Path) -> Path:
    return Path(runtime_root) / SNAPSHOT_FILE


def write_loadout_snapshot(
    runtime_root: Path, views: Mapping[str, LoadoutView], *, now: datetime | None = None
) -> Path:
    """Écrit l'instantané (remplacement atomique) et rend son chemin. Lève `OSError` si le disque refuse.

    `views` est `resolver.explain_all()` : une vue par clé `<profil>` ou `<profil>:<rôle>`.
    """
    from jarvis.adapters.file_replace import replace_with_retry  # paresseux : le hook ne lit que

    payload: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "written_at": (now or datetime.now(timezone.utc)).isoformat(),
        "loadouts": {
            key: {"manifest": render_manifest(view), "view": view.as_dict()} for key, view in views.items()
        },
    }
    target = snapshot_path(runtime_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".loadout-", suffix=".tmp", dir=str(target.parent))
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


def _clean(text: str) -> str:
    """Le manifeste lu : imprimable (sauts de ligne permis), borné, ou `""` s'il ne porte pas la marque."""
    kept = "".join(ch for ch in text if ch == "\n" or ch.isprintable())[:MAX_LOADOUT_MANIFEST_CHARS].strip()
    return kept if kept.startswith(MANIFEST_MARK) else ""


def read_manifest(runtime_root: Path, profile: str, role: str | None = None) -> str:
    """Le manifeste du couple, ou `""` : fichier absent, trop gros, d'un autre schéma, clé absente ou texte invalide."""
    path = snapshot_path(runtime_root)
    try:
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return ""
    except FileNotFoundError:
        return ""
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict) or raw.get("schema") != SNAPSHOT_SCHEMA:
        return ""
    entries = raw.get("loadouts")
    entry = entries.get(loadout_key(profile, role)) if isinstance(entries, dict) else None
    manifest = entry.get("manifest") if isinstance(entry, dict) else None
    return _clean(manifest) if isinstance(manifest, str) else ""
