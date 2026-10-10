"""Ports des capacités locales (handoff jarvis-remotion-presentation-integration, Slice 03 ; `docs/local-capabilities.md`)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from jarvis.domain.local_capabilities import CapabilityManifest, CapabilityState


class LocalCapabilityStore(Protocol):
    """Un état par capacité, sous la racine de données du poste ; écriture atomique."""

    def load(self, capability_id: str) -> CapabilityState | None: ...

    def save(self, state: CapabilityState) -> None: ...

    def list_ids(self) -> tuple[str, ...]: ...

    def runtime_dir(self, capability_id: str) -> Path:
        """Dossier propriétaire de la capacité (créé au besoin) : le runner n'écrit nulle part ailleurs."""


class CapabilityRunner(Protocol):
    """Seul endroit où une capacité touche le réseau, npm ou un processus.

    Le socle n'en câble aucun par défaut (`UnavailableRunner`) ; les tests y
    mettent un faux. Toute erreur lève `LocalCapabilityError` (code stable) ou
    une exception quelconque, que l'hôte convertit en code de l'opération.
    """

    def check_requirements(self, manifest: CapabilityManifest) -> tuple[str, ...]:
        """Exigences du poste NON satisfaites (texte court), vide si tout va bien."""

    def install(self, manifest: CapabilityManifest, runtime_dir: Path) -> Mapping[str, str]:
        """Installe les composants épinglés dans `runtime_dir` ; rend les versions réellement posées."""

    def verify(self, manifest: CapabilityManifest, runtime_dir: Path, installed: Mapping[str, str]) -> None:
        """Sonde de santé ; lève si la capacité est inutilisable."""

    def start(self, manifest: CapabilityManifest, runtime_dir: Path) -> str:
        """Lance le processus enfant ; rend sa référence opaque (pid)."""

    def stop(self, process_ref: str) -> None: ...

    def is_alive(self, process_ref: str) -> bool: ...

    def remove(self, manifest: CapabilityManifest, runtime_dir: Path) -> None:
        """Retire ce que `install` a posé, dans `runtime_dir` seulement."""
