"""Disposition du graphe d'architecture : positions des nœuds, interface seule (docs/architecture-graph.md §5).

Store séparé de la topologie, avec sa propre révision (`l-<n>`, compteur) : `<runtime>/architecture-layout.json`.
Aucun module du runtime ne le lit ; déplacer un nœud ne change jamais un comportement.
"""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.domain.architecture_graph import (
    LAYOUT_REVISION_STALE, LAYOUT_SCHEMA_VERSION, LAYOUT_WRITE_FAILED, ArchitectureGraphError, LayoutDocument,
    parse_layout_revision, validate_positions,
)

LAYOUT_FILE = "architecture-layout.json"


class ArchitectureLayoutStore:
    def __init__(self, runtime_root: Path | str, *, journal: Any = None) -> None:
        self.path = Path(runtime_root) / LAYOUT_FILE
        self.journal = journal
        self._lock = threading.Lock()

    def read(self) -> LayoutDocument:
        if not self.path.is_file():
            return LayoutDocument(0, {})  # argued: no layout yet is the normal state, the UI places nodes itself
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") != LAYOUT_SCHEMA_VERSION:
                raise ValueError("schema")
            revision = raw.get("revision")
            if type(revision) is not int or revision < 0:
                raise ValueError("revision")
            return LayoutDocument(revision, validate_positions(raw.get("positions", {})))
        except (OSError, ValueError, ArchitectureGraphError) as exc:
            # Disposition illisible : rien de fonctionnel n'en dépend. Signalée, puis traitée comme vide ;
            # la prochaine écriture (base « l-0 ») la remplace.
            self._emit("architecture.layout.unreadable", "Disposition du graphe illisible, ignorée",
                       {"error_class": type(exc).__name__}, level="warning")
            return LayoutDocument(0, {})

    def write(self, *, base_revision: object, positions: object) -> LayoutDocument:
        base = parse_layout_revision(base_revision)
        clean = validate_positions(positions)
        with self._lock:
            current = self.read()
            if base != current.revision:
                raise ArchitectureGraphError(LAYOUT_REVISION_STALE, "La disposition a changé depuis votre lecture ; "
                                             "relisez-la avant de l'enregistrer.")
            document = LayoutDocument(current.revision + 1, clean)
            payload = {"schema_version": LAYOUT_SCHEMA_VERSION, "revision": document.revision,
                       "positions": clean}
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                replace_with_retry(tmp, self.path)
            except OSError as exc:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass  # argued: the write failure below is what the caller sees
                self._emit("architecture.layout.write_failed", "Disposition non enregistrée",
                           {"error_class": type(exc).__name__}, level="error")
                raise ArchitectureGraphError(LAYOUT_WRITE_FAILED,
                                             f"Disposition non enregistrée : {type(exc).__name__}: {exc}") from exc
        self._emit("architecture.layout.saved", "Disposition du graphe enregistrée",
                   {"revision": document.revision_token, "nodes": len(clean)})
        return document

    def _emit(self, kind: str, message: str, data: dict, *, level: str = "info") -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except Exception:  # noqa: BLE001
            pass  # argued: journal delivery is evidence, never authority over the layout write
