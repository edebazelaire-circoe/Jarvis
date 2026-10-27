"""Port de la destination d'export explicite (presentation-edition-v1 Slice 03, `docs/export.md`).

`DocumentExportService` (cœur) ne connaît que ce contrat ; l'adaptateur `jarvis.adapters.export_destination`
(`ExportDestination`, racine `Documents\\Jarvis`, copie sans écrasement) le réalise et n'est construit que par la
composition (`v2_app.py`). Ajouté par la Slice 10 : le cœur importait l'adaptateur directement, ce que la porte
d'architecture `test_v2_architecture.py::test_core_does_not_import_concrete_adapters` refuse.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class CopyOutcomeLike(Protocol):
    file_name: str
    size_bytes: int
    sha256: str
    renamed: bool
    already_exported: bool


class ExportDestinationPort(Protocol):
    #: Racine montrée à l'utilisateur et au cerveau, sans chemin personnel (`Documents\Jarvis`).
    label: str
    #: `JARVIS_EXPORT_ROOT` posé dans un produit installé et ignoré (dit une fois au journal).
    ignored_override: bool

    def describe(self) -> dict[str, Any]:
        """Racine disponible ou non, libellé, codes ; ne crée rien."""

    def copy_in(self, source: Path, *, stem: str, extension: str, expected_size: int | None,
                expected_sha256: str | None) -> CopyOutcomeLike:
        """Copie vérifiée de `source` sous la racine, sans jamais écraser un fichier existant."""
