"""Port du magasin des versions promues de Work Method (handoff organic-agent-orchestration, Slice 12).

Table `work_method_versions` : étape v11 de `sqlite_state`, connexion partagée
(adaptateur `sqlite_work_methods`). Les versions livrées restent dans le code
(`work_methods.BUILTIN_METHODS`) ; ce magasin ne retient que les versions qu'une
personne a promues depuis un candidat (`work_method_learning`). Il n'ajoute que :
une version publiée ne se réécrit ni ne s'efface. Contrat : `docs/work-methods.md`.
"""

from __future__ import annotations

from typing import Protocol

from jarvis.domain.work_methods import WorkMethod
from jarvis.ports.mission_history import MissionHistoryStoreError, MissionHistoryUnavailable


class WorkMethodStoreError(MissionHistoryStoreError):
    """Ligne illisible ou qui contredit ses colonnes clés ; jamais réparée."""

    code = "work_method_store_unreadable"


class WorkMethodStoreUnavailable(MissionHistoryUnavailable):
    """SQLite a refusé l'opération (verrou, E/S) ; la cause SQLite reste dans le message."""

    code = "work_method_store_failed"


class WorkMethodRepository(Protocol):
    async def promoted_methods(self) -> tuple[WorkMethod, ...]:
        """Toutes les versions promues, par `(method_id, version)` croissants (bornées par le volume humain)."""
        ...

    async def publish(self, method: WorkMethod) -> WorkMethod:
        """Ajouter une version promue. Même `id@version` déjà présente : `MethodError`
        `work_method_version_conflict` (jamais une réécriture)."""
        ...
