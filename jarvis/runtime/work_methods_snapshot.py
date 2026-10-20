"""Les versions promues des Work Methods, posées dans un fichier que le hook lit sans réseau (Slice 12).

Même schéma que `subagent_roles_snapshot` (instantané voisin) : le hook `PreToolUse`
(`routing_hook`) est un processus court qui ne parle ni à Core ni au Control Center.
Les versions promues vivent dans Core (`jarvis.sqlite3` v11, `work_method_versions`) ;
le Control Center les recopie dans `work-methods.json`, à la racine runtime :

- **écrire** : `write_snapshot(runtime_root, methods)`, appelé par le Control Center après
  une promotion réussie, au démarrage dès que Core répond, et à chaque lecture réussie de
  `GET /api/work-methods` ; écriture atomique, `OSError` si le disque refuse ;
- **lire** : `read_promoted(runtime_root)` rend `{method_id: dernière version promue}`.
  Fichier absent : `{}` (aucune promotion connue), les versions livrées s'appliquent. Le fichier
  est une entrée non fiable : taille bornée, schéma vérifié, chaque méthode décodée strictement
  (`WorkMethod.from_payload`, clés de plan refusées) et de provenance `promoted` ; sinon
  `ValueError`, et le hook se replie sur les versions livrées avec un diagnostic.

Seules les versions promues y figurent : le défaut vit dans le code. Contrat : `docs/work-methods.md`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from jarvis.domain.work_methods import MethodOrigin, WorkMethod, latest_methods

SNAPSHOT_FILE = "work-methods.json"
SNAPSHOT_SCHEMA = 1
#: Une méthode fait au plus ~10 Kio (12 principes et 12 critères de 300 caractères) ; au-delà, le fichier n'est pas
#: le nôtre.
MAX_SNAPSHOT_BYTES = 512 * 1024


def snapshot_path(runtime_root: Path) -> Path:
    return Path(runtime_root) / SNAPSHOT_FILE


def write_snapshot(runtime_root: Path, methods: Iterable[WorkMethod], *, now: datetime | None = None) -> Path:
    """Écrit l'instantané des versions promues (remplacement atomique). Lève `OSError` si le disque refuse."""
    from jarvis.adapters.file_replace import replace_with_retry  # paresseux : le hook ne fait que lire

    promoted = [method for method in methods if method.provenance.origin is MethodOrigin.PROMOTED]
    payload: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "written_at": (now or datetime.now(timezone.utc)).isoformat(),
        "methods": [method.to_payload() for method in sorted(promoted, key=lambda m: (m.method_id, m.version))],
    }
    target = snapshot_path(runtime_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".work-methods-", suffix=".tmp", dir=str(target.parent))
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
            pass  # intentional: the temporary file was renamed into place, nothing is left to remove
    return target


def read_payloads(runtime_root: Path) -> list[dict[str, Any]] | None:
    """Les charges utiles brutes de l'instantané, ou `None` s'il est absent. Lève `ValueError` / `OSError`."""
    path = snapshot_path(runtime_root)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None
    if size > MAX_SNAPSHOT_BYTES:
        raise ValueError(f"{SNAPSHOT_FILE} exceeds {MAX_SNAPSHOT_BYTES} bytes")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict) or raw.get("schema") != SNAPSHOT_SCHEMA or not isinstance(raw.get("methods"), list):
        raise ValueError(f"{SNAPSHOT_FILE} has no schema {SNAPSHOT_SCHEMA} method list")
    return raw["methods"]


def read_promoted(runtime_root: Path) -> dict[str, WorkMethod]:
    """`{method_id: dernière version promue}`, ou `{}` sans fichier. Lève `ValueError` (contenu) ou `OSError`."""
    payloads = read_payloads(runtime_root)
    if payloads is None:
        return {}
    methods = [WorkMethod.from_payload(item) for item in payloads]
    if any(method.provenance.origin is not MethodOrigin.PROMOTED for method in methods):
        raise ValueError(f"{SNAPSHOT_FILE} holds a version that was not promoted")
    return dict(latest_methods(methods))
