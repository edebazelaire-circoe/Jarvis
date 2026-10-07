"""Politique de rétention des sources de scène du Studio (handoff jarvis-interactive-presentation-studio, Slice 01a).

Pure : décide quelles versions d'un id `presentation-studio.*` Core peut archiver ; `PrefabService` l'exécute
sous son verrou d'écriture (`PrefabLibrary.retire`, un renommage vers `prefabs/.archive/`). Contrat :
`docs/prefabs.md` › *Retention of studio scene sources*.

Une version est archivable si et seulement si :

- elle est saine (une version `tampered` ou `unreadable` reste, visible, comme preuve) et dans la racine de
  données (jamais le paquet) ;
- elle n'est pas parmi les `keep_last` plus récentes de l'id (toutes versions confondues) ;
- aucun épinglage ne la nomme (`PrefabPinRegistry`).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING

from jarvis.ports.prefabs import PrefabPinRegistry, PrefabRoot

if TYPE_CHECKING:
    from jarvis.core.prefab_service import CatalogVersion

#: Un id du Studio publié depuis moins longtemps n'est jamais archivé en entier : son épinglage est peut-être
#: encore en cours d'écriture côté Studio (publication puis épinglage ne sont pas une seule transaction).
RETENTION_ID_GRACE_SECONDS = 3600


def retirable_versions(entries: Sequence[CatalogVersion], pinned: Collection[int], keep_last: int) -> list[int]:
    """Numéros archivables parmi les `entries` d'un id (triées par version), du plus ancien au plus récent."""

    protected = {entry.version for entry in sorted(entries, key=lambda item: item.version)[-keep_last:]} \
        if keep_last > 0 else set()
    return [entry.version for entry in sorted(entries, key=lambda item: item.version)
            if entry.ok and entry.root is PrefabRoot.DATA and entry.version not in protected
            and entry.version not in pinned]


class CompositePinRegistry:
    """Union de plusieurs registres (document de scène du Studio, modèles, objets de scène...) : un seul qui
    échoue fait échouer l'ensemble, jamais une réponse partielle."""

    def __init__(self, *registries: PrefabPinRegistry) -> None:
        self._registries = registries

    async def pinned_versions(self, prefab_ids: Collection[str]) -> Mapping[str, frozenset[int]]:
        merged: dict[str, frozenset[int]] = {prefab_id: frozenset() for prefab_id in prefab_ids}
        for registry in self._registries:
            for prefab_id, versions in (await registry.pinned_versions(prefab_ids)).items():
                merged[prefab_id] = merged.get(prefab_id, frozenset()) | frozenset(versions)
        return merged
