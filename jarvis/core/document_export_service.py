"""Export explicite d'un fichier final vers `Documents\\Jarvis` (handoff jarvis-presentation-edition-v1, Slice 03).

Contrat : `docs/export.md`. Le service ne prend qu'un `artifact_id` (et un nom facultatif, assaini) : il lit
l'Artifact canonique, vérifie qu'il est d'une classe exportable (`EXPORT_CLASSES`) et `complete`, retrouve son
payload interne par `ArtifactService.payload_files` (jamais un chemin reçu), puis confie la COPIE à
`ExportDestination`. L'état interne n'est jamais déplacé ni modifié ; le résultat n'est pas enregistré dans
l'Artifact (information pour l'appelant et le journal seulement) : un fichier exporté peut disparaître sans
rien casser.

Journal : `core.export.completed` (info), `core.export.refused` (warning), `core.export.failed` (error) ; jamais un
chemin absolu, seulement le libellé de la racine et le nom du fichier.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from jarvis.domain.artifacts import Artifact, ArtifactError, ArtifactErrorCode, ArtifactState
from jarvis.domain.document_export import (
    ExportError, ExportErrorCode as E, ExportResult, default_stem, export_class_of, file_stem,
)
from jarvis.ports.artifacts import ArtifactPayloadError
from jarvis.ports.document_export import ExportDestinationPort

#: Qui a demandé : l'interface (geste de l'utilisateur) ou le cerveau (sur la demande de l'utilisateur, attestée par son outil).
ACTORS = frozenset({"user", "brain"})


class DocumentExportService:
    def __init__(self, *, artifacts: Any, destination: ExportDestinationPort,
                 title_of: Callable[[Artifact], Awaitable[str | None]] | None = None, diagnostics: Any | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self._artifacts = artifacts
        self._destination = destination
        self._title_of = title_of
        self._diagnostics = diagnostics
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if getattr(destination, "ignored_override", False):
            self._trace("override_ignored", "JARVIS_EXPORT_ROOT ignoré : produit installé, la racine reste Documents\\Jarvis",
                        level="warning", data={"root": destination.label})

    @property
    def destination(self) -> ExportDestinationPort:
        return self._destination

    def root(self) -> dict[str, Any]:
        """Racine d'export : disponible ou non, libellé, codes ; ne crée rien."""

        return self._destination.describe()

    async def export(self, artifact_id: object, *, file_name: object = None, actor: str = "user") -> ExportResult:
        try:
            return await self._export(artifact_id, file_name, actor)
        except ExportError as exc:
            level = "error" if exc.status >= 500 else "warning"
            self._trace("failed" if level == "error" else "refused", "Export refusé" if level == "warning" else "Export échoué",
                        level=level, data={"artifact_id": str(artifact_id)[:80], "actor": actor, "code": exc.code.value,
                                           "detail": exc.detail, "root": self._destination.label})
            raise

    async def _export(self, artifact_id: object, file_name: object, actor: str) -> ExportResult:
        if actor not in ACTORS:
            raise ExportError(E.INVALID, "actor must be user or brain")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ExportError(E.INVALID, "artifact_id is required (an export names a Jarvis artifact, never a path)")
        if file_name is not None and not isinstance(file_name, str):
            raise ExportError(E.INVALID, "file_name must be a string")
        try:
            artifact = await self._artifacts.get(artifact_id)
        except ArtifactError as exc:
            if exc.code in (ArtifactErrorCode.ARTIFACT_NOT_FOUND, ArtifactErrorCode.INVALID_ARTIFACT):
                raise ExportError(E.SOURCE_NOT_FOUND, f"artifact {artifact_id[:80]!r} does not exist") from None
            raise ExportError(E.SOURCE_NOT_FOUND, f"artifact {artifact_id[:80]!r} is unreadable: {exc.code.value}") from None
        cls = export_class_of(artifact.kind)
        if artifact.state is not ArtifactState.COMPLETE:
            raise ExportError(E.SOURCE_NOT_EXPORTABLE, f"artifact {artifact.artifact_id} is {artifact.state.value}: only a complete file is exported")
        if artifact.payload_name != cls.payload_name:
            raise ExportError(E.SOURCE_NOT_EXPORTABLE, f"artifact {artifact.artifact_id} has no {cls.format} payload")
        try:
            files = self._artifacts.payload_files(artifact)
        except ArtifactPayloadError as exc:
            raise ExportError(E.SOURCE_UNAVAILABLE, f"the canonical payload folder is refused ({exc.code})") from None
        if files is None:
            raise ExportError(E.SOURCE_UNAVAILABLE, f"artifact {artifact.artifact_id} has no payload")
        stem = file_stem(file_name) if file_name and file_name.strip() else default_stem(await self._title(artifact), cls)
        expected_sha = artifact.metadata.get("render_output_sha256")
        outcome = await asyncio.to_thread(
            self._destination.copy_in, files.final_path, stem=stem, extension=cls.extension,
            expected_size=artifact.size_bytes, expected_sha256=expected_sha if isinstance(expected_sha, str) else None)
        result = ExportResult(artifact_id=artifact.artifact_id, format=cls.format, file_name=outcome.file_name,
                              root_label=self._destination.label, size_bytes=outcome.size_bytes, sha256=outcome.sha256,
                              exported_at=self._clock().isoformat(), renamed=outcome.renamed,
                              already_exported=outcome.already_exported)
        self._trace("already_exported" if outcome.already_exported else "completed",
                    "Déjà exporté à l'identique : aucune copie de plus" if outcome.already_exported else "Copie exportée", data={"artifact_id": artifact.artifact_id, "actor": actor, "format": cls.format,
                                                       "file_name": outcome.file_name, "root": self._destination.label,
                                                       "size_bytes": outcome.size_bytes, "renamed": outcome.renamed})
        return result

    async def _title(self, artifact: Artifact) -> str | None:
        if self._title_of is None:
            return None
        try:
            return await self._title_of(artifact)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - argued: the name falls back to a neutral one, and the cause is journalled
            self._trace("title_unavailable", "Titre de la présentation illisible : nom neutre", level="warning",
                        data={"artifact_id": artifact.artifact_id, "exception": type(exc).__name__})
            return None

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(f"core.export.{kind}", message, level=level, data=data or {})
        except Exception:  # noqa: BLE001 - argued: an unavailable journal never changes an export's outcome
            pass


def presentation_title_reader(artifacts: Any, studio: Any) -> Callable[[Artifact], Awaitable[str | None]]:
    """Titre de la présentation d'un dérivé : relation `rendered_from` -> snapshot -> source -> titre vivant (sinon `None`)."""

    from jarvis.domain.presentation_artifacts import SourceProvenance
    from jarvis.ports.artifacts import RelationDirection

    async def title_of(artifact: Artifact) -> str | None:
        for relation in await artifacts.relations(artifact.artifact_id, RelationDirection.ORIGINS):
            if getattr(relation.relation, "value", relation.relation) != "rendered_from":
                continue
            snapshot = await artifacts.get(relation.origin_artifact_id)
            provenance = SourceProvenance.of_snapshot(snapshot)
            view = await studio.get(provenance.presentation_id)
            return str(view.presentation.title or "") or None
        return None

    return title_of
