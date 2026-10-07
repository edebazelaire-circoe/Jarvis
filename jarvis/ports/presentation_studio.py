"""Port du magasin des Presentations (handoff jarvis-interactive-presentation-studio, Slice 02).

`PresentationStudioStore` : textes bruts des documents d'une Presentation
(`presentation.json`, `variants/<variant_id>.json`). Adaptateur :
`jarvis.adapters.file_presentation_studio_store.FilePresentationStudioStore`
(`<data_root>/presentations/`). Il écrit atomiquement et ne valide rien : le
service (`jarvis.core.presentation_studio_service`) relit chaque document avec
le domaine (`jarvis.domain.presentation_studio`). Synchrone ; le service
l'appelle hors de la boucle. Refus et pannes : `PresentationStudioError`
(codes du domaine, `presentation_studio_*`).

Contrat : `docs/presentation-studio.md` › *Presentation contract*, *Storage*.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from jarvis.domain.prefab import PrefabInstanceRef, PrefabManifest
from jarvis.ports.prefabs import InstanceValidation


@dataclass(frozen=True, slots=True)
class StoreProblem:
    #: Nom du dossier vu (jamais un chemin absolu).
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class StoreScan:
    #: Identifiants (`pst_...`) des dossiers de Presentation vus, triés.
    presentation_ids: tuple[str, ...] = ()
    problems: tuple[StoreProblem, ...] = ()


@dataclass(frozen=True, slots=True)
class SweepReport:
    removed: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()


class PrefabCatalog(Protocol):
    """Ce que le Studio demande aux prefabs (Slice 04) : le manifeste d'un pin exact et la validation d'une instance.

    `jarvis.core.prefab_service.PrefabService` en est l'unique implémentation ; le Studio ne revalide rien lui-même.
    `manifest` lève `PrefabStoreError` (version inconnue, altérée, disque).
    """

    async def manifest(self, prefab_id: str, version: int) -> PrefabManifest: ...

    async def validate_instance(self, ref: PrefabInstanceRef) -> InstanceValidation: ...


class PresentationStudioStore(Protocol):
    def scan(self) -> StoreScan: ...

    def read_manifest(self, presentation_id: str) -> str:
        """Texte de `presentation.json`. `unknown_presentation` s'il manque, `corrupt_document` si ce n'est pas un fichier sûr."""

    def read_variant(self, presentation_id: str, variant_id: str) -> str:
        """Texte de `variants/<variant_id>.json`. `unknown_variant` s'il manque."""

    def read_score(self, presentation_id: str, score_id: str) -> str:
        """Texte de `scores/<score_id>.json` (Slice 10). `unknown_score` s'il manque."""

    def write_score(self, presentation_id: str, score_id: str, text: str) -> None:
        """Remplace (ou crée) une partition, atomiquement, comme `write_variant`. Écrite **avant** la variante qui la cite."""

    def create(self, presentation_id: str, manifest: str, variants: Mapping[str, str]) -> None:
        """Dossier complet d'une Presentation neuve, publié d'un seul renommage : tout ou rien. `already_exists` si l'id est pris."""

    def write_variant(self, presentation_id: str, variant_id: str, text: str) -> None:
        """Remplace (ou crée) une variante, atomiquement : l'ancien texte entier ou le nouveau, jamais un mélange."""

    def write_manifest(self, presentation_id: str, text: str) -> None:
        """Remplace `presentation.json`, atomiquement. Écrit **en dernier** quand une opération touche plusieurs fichiers."""

    def sweep(self) -> SweepReport:
        """Retire les restes d'un arrêt brutal (`.staging-*`, `*.tmp`). Jamais un document."""
