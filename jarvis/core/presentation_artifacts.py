"""Pont Presentation (source éditable) -> registre d'Artifacts (Remotion Slice 07).

Contrat : `docs/presentation-artifacts.md`. Ce service ne possède **rien** de neuf :

- les Presentations restent écrites par `PresentationStudioService` (il ne fait que les lire) ;
- les Artifacts restent écrits par `ArtifactService` (acquisition `pending`, spool, `finalize`, `fail`, suppression) ;
- les Boards ne sont jamais écrits ici : ni `Board.artifact_refs`, ni une table. « Quels Boards montrent cette source ? » se
  lit dans `board_artifact_links` (lien automatique au Board actif à la création de l'Artifact, ou lien explicite fait par
  `WorkspaceService.artifact_link` sur l'id d'un **snapshot ou d'un rendu**).

Il apporte les gardes propres à la jonction : figer seulement la révision que la source porte encore, un id de snapshot
déterministe (jamais d'écrasement), un dérivé seulement d'un snapshot complet dont le moteur sait exporter, et la lecture
groupée « source -> snapshots -> rendus -> Boards » dont l'interface de Board (Slice 08) a besoin.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jarvis.core.artifact_service import ArtifactService
from jarvis.domain.artifacts import (
    Artifact, ArtifactError, ArtifactErrorCode, ArtifactQuery, ArtifactRelationKind, ArtifactState,
)
from jarvis.domain.presentation_artifacts import (
    ARTIFACT_SOURCE, MAX_SNAPSHOT_ATTEMPTS, PRESENTATION_ARTIFACT_KINDS, RENDER_KINDS, RENDERS, SNAPSHOT_KIND,
    SNAPSHOT_MIME, SNAPSHOT_PAYLOAD_NAME, SOURCE_MISSING, SOURCE_STALE, RenderFormat, SourceProvenance, SourceRef,
    check_content_hash, check_render_origin, is_stale, parse_render_format, require_current, snapshot_artifact_id,
)
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode
from jarvis.domain.presentation_studio_engine import Capability, require_capability
from jarvis.ports.artifacts import RelationDirection
from jarvis.ports.board_artifact_links import BoardArtifactLinkStore
from jarvis.ports.v2 import DiagnosticSink

#: Lecture du registre par pages de cette taille ; au-delà de `MAX_SCAN_PAGES` la réponse dit `truncated`.
SCAN_PAGE = 200
MAX_SCAN_PAGES = 25
_C = PresentationStudioErrorCode


class PresentationArtifacts:
    """Façade Core : figer (`begin_snapshot` / `finalize_snapshot`), dériver (`begin_render`), retrouver (`describe_source`,
    `sources_of_board`, `boards_of_source`)."""

    def __init__(self, studio: Any, artifacts: ArtifactService, links: BoardArtifactLinkStore, *,
                 diagnostics: DiagnosticSink | None = None) -> None:
        self._studio = studio
        self._artifacts = artifacts
        self._links = links
        self._diagnostics = diagnostics

    # ------------------------------------------------------------ figer

    async def begin_snapshot(self, presentation_id: str, variant_id: str, *, expected_presentation_revision: int,
                             expected_variant_revision: int, jarvis_session_id: str | None = None,
                             context_id: str | None = None) -> dict[str, Any]:
        """Ouvre le snapshot `pending` de **cette** révision, ou rend celui qui existe déjà (`created: false`).

        Révision différente de la source vivante : `presentation_studio_stale_revision`, rien n'est écrit. Variante
        archivée ou inconnue : `presentation_studio_unknown_variant`. Le même (variante, révisions) retombe sur le même
        Artifact tant qu'il est `pending` ou `complete` ; un essai `failed`/`partial` est terminal et laisse la place à
        l'essai suivant (`_a2`...), jamais écrasé.
        """

        provenance = await self._provenance(presentation_id, variant_id, expected_presentation_revision,
                                            expected_variant_revision)
        metadata = provenance.to_metadata()
        for attempt in range(1, MAX_SNAPSHOT_ATTEMPTS + 1):
            artifact_id = snapshot_artifact_id(presentation_id, variant_id, expected_presentation_revision,
                                               expected_variant_revision, attempt)
            existing = await self._find(artifact_id)
            if existing is not None and existing.state in (ArtifactState.PENDING, ArtifactState.COMPLETE):
                return self._began(existing, created=False)
            if existing is not None:
                continue
            try:
                created = await self._artifacts.create(
                    kind=SNAPSHOT_KIND, source=ARTIFACT_SOURCE, jarvis_session_id=jarvis_session_id,
                    context_id=context_id, payload_name=SNAPSHOT_PAYLOAD_NAME, mime_type=SNAPSHOT_MIME,
                    metadata=metadata, artifact_id=artifact_id)
            except ArtifactError as exc:
                if exc.code is not ArtifactErrorCode.ARTIFACT_CONFLICT:
                    raise
                winner = await self._find(artifact_id)  # un appel concurrent a créé le même instantané
                if winner is not None and winner.state in (ArtifactState.PENDING, ArtifactState.COMPLETE):
                    return self._began(winner, created=False)
                continue
            self._trace("core.presentation_artifacts.snapshot_begun", "Snapshot de présentation ouvert",
                        data={"artifact_id": created.artifact_id, "presentation_id": presentation_id,
                              "variant_id": variant_id, "attempt": attempt})
            return self._began(created, created=True)
        raise ArtifactError(ArtifactErrorCode.ARTIFACT_CONFLICT,
                            f"{MAX_SNAPSHOT_ATTEMPTS} snapshot attempts of this revision already ended without a complete "
                            "snapshot: fix the cause, edit the source, or delete a failed attempt explicitly")

    async def finalize_snapshot(self, artifact_id: str, *, content_sha256: str) -> Artifact:
        """`pending` -> `complete` si la source n'a pas bougé depuis `begin_snapshot` ; sinon l'instantané devient `failed`
        (`source_stale` / `source_missing`) et l'erreur est levée : jamais un « complet » d'une révision disparue.

        Le fichier `snapshot.zip` doit déjà être finalisé sur disque (spool de `ArtifactService`) ; `content_sha256` est
        celui du paquet, rangé dans les métadonnées d'acquisition avant le gel.
        """

        digest = check_content_hash(content_sha256)
        snapshot = await self._artifacts.get(artifact_id)
        provenance = SourceProvenance.of_snapshot(snapshot)
        if snapshot.state is not ArtifactState.PENDING:
            raise ArtifactError(ArtifactErrorCode.ARTIFACT_NOT_PENDING,
                                f"snapshot {artifact_id} is {snapshot.state.value}: a frozen snapshot never changes")
        try:
            live = await self._live(provenance.presentation_id, provenance.variant_id)
            require_current(f"presentation {provenance.presentation_id}",
                            expected_presentation=provenance.presentation_revision,
                            expected_variant=provenance.variant_revision, live_presentation=live[0], live_variant=live[1])
        except PresentationStudioError as exc:
            missing = exc.code in (_C.UNKNOWN_PRESENTATION, _C.UNKNOWN_VARIANT)
            await self._artifacts.fail(artifact_id, error_code=SOURCE_MISSING if missing else SOURCE_STALE)
            self._trace("core.presentation_artifacts.snapshot_refused", "Snapshot refusé : la source a changé",
                        level="warning", data={"artifact_id": artifact_id, "code": exc.code.value})
            raise
        await self._artifacts.update_pending(artifact_id, metadata={"content_sha256": digest})
        done = await self._artifacts.finalize(artifact_id)
        self._trace("core.presentation_artifacts.snapshot_complete", "Snapshot de présentation figé",
                    data={"artifact_id": artifact_id, "size_bytes": done.size_bytes})
        return done

    # ------------------------------------------------------------ dériver

    async def begin_render(self, snapshot_id: str, render_format: RenderFormat | str, *,
                           jarvis_session_id: str | None = None, context_id: str | None = None) -> Artifact:
        """Dérivé `pending` d'un snapshot **complet** : relation `rendered_from` écrite dans la transaction de création.

        Snapshot inconnu (orphelin) : `artifact_not_found`. Pas un snapshot, ou pas complet : `invalid_relation`. Moteur du
        snapshot qui n'exporte pas (Slidecar) : `presentation_studio_engine_unsupported`. La source vivante n'est pas
        consultée : un rendu d'un snapshot ancien reste un rendu valide de **ce** snapshot.
        """

        fmt = parse_render_format(render_format)
        snapshot = await self._artifacts.get(snapshot_id)
        provenance = check_render_origin(snapshot)
        require_capability(provenance.engine, Capability.EXPORT)
        spec = RENDERS[fmt]
        artifact = await self._artifacts.create(
            kind=spec.kind, source=ARTIFACT_SOURCE, jarvis_session_id=jarvis_session_id, context_id=context_id,
            payload_name=spec.payload_name, mime_type=spec.mime_type, metadata={"render_format": fmt.value},
            origins=((ArtifactRelationKind.RENDERED_FROM, snapshot_id),))
        self._trace("core.presentation_artifacts.render_begun", "Rendu de présentation ouvert",
                    data={"artifact_id": artifact.artifact_id, "snapshot_id": snapshot_id, "format": fmt.value})
        return artifact

    # ------------------------------------------------------------ retrouver

    async def describe_source(self, presentation_id: str) -> dict[str, Any]:
        """La source (vivante ou disparue), ses snapshots, leurs rendus, et les Boards qui les montrent."""

        ref = SourceRef(presentation_id)
        snapshots, truncated = await self._snapshots_of(presentation_id)
        live = await self._live_summary(presentation_id)
        groups = [await self._snapshot_entry(snapshot, live) for snapshot in snapshots]
        boards = sorted({board for entry in groups for board in entry["board_ids"]})
        return {"source_ref": str(ref), "presentation_id": presentation_id, "source": live,
                "snapshots": groups, "board_ids": boards, "truncated": truncated}

    async def boards_of_source(self, presentation_id: str) -> list[str]:
        """Ids de Boards qui montrent cette source = Boards liés à l'un de ses snapshots ou rendus. Rien d'autre."""

        return (await self.describe_source(presentation_id))["board_ids"]

    async def sources_of_board(self, board_id: str) -> dict[str, Any]:
        """Sources de Presentation visibles sur un Board : regroupement des Artifacts de présentation **liés à ce Board**.

        Une source jamais figée n'est sur aucun Board (rien à lier). Un rendu lié dont le snapshot n'est pas lié au Board
        apparaît sous son snapshot, `linked_here: false` pour ce dernier.
        """

        page = await self._artifacts.query(ArtifactQuery(
            board_id=board_id, kinds=tuple(sorted(PRESENTATION_ARTIFACT_KINDS, key=lambda k: k.value)),
            limit=SCAN_PAGE))
        linked = {a.artifact_id for a in page.items}
        snapshot_ids: dict[str, Artifact] = {}
        for artifact in page.items:
            snapshot = artifact
            if artifact.kind in RENDER_KINDS:
                origins = await self._artifacts.relations(artifact.artifact_id, RelationDirection.ORIGINS)
                origin = next((r.origin_artifact_id for r in origins if r.relation is ArtifactRelationKind.RENDERED_FROM), None)
                if origin is None:
                    continue  # un rendu sans origine ne peut pas exister (créé avec sa relation) : ignoré, pas deviné
                snapshot = await self._artifacts.get(origin)
            snapshot_ids[snapshot.artifact_id] = snapshot
        sources: dict[str, dict[str, Any]] = {}
        for snapshot in snapshot_ids.values():
            provenance = SourceProvenance.of_snapshot(snapshot)
            source = sources.get(provenance.presentation_id)
            if source is None:
                source = sources[provenance.presentation_id] = {
                    "source_ref": str(SourceRef(provenance.presentation_id)),
                    "presentation_id": provenance.presentation_id,
                    "source": await self._live_summary(provenance.presentation_id), "snapshots": []}
            live = source["source"]
            entry = await self._snapshot_entry(snapshot, live)
            entry["linked_here"] = snapshot.artifact_id in linked
            source["snapshots"].append(entry)
        return {"board_id": board_id, "sources": list(sources.values()), "truncated": page.next_cursor is not None}

    # ------------------------------------------------------------ interne

    async def _snapshot_entry(self, snapshot: Artifact, live: Mapping[str, Any]) -> dict[str, Any]:
        provenance = SourceProvenance.of_snapshot(snapshot)
        dependents = await self._artifacts.relations(snapshot.artifact_id, RelationDirection.DEPENDENTS)
        renders = []
        boards = {link.board_id for link in await self._links.boards_of_artifact(snapshot.artifact_id, limit=100)}
        for relation in dependents:
            if relation.relation is not ArtifactRelationKind.RENDERED_FROM:
                continue
            render = await self._artifacts.get(relation.artifact_id)
            boards |= {link.board_id for link in await self._links.boards_of_artifact(render.artifact_id, limit=100)}
            renders.append({"artifact_id": render.artifact_id, "kind": render.kind.value, "state": render.state.value,
                            "format": render.metadata.get("render_format")})
        stale = None
        if live.get("exists"):
            stale = is_stale(provenance, presentation_revision=live["revision"],
                             variant_revision=live["variant_revisions"].get(provenance.variant_id, -1))
        return {"artifact_id": snapshot.artifact_id, "state": snapshot.state.value, "variant_id": provenance.variant_id,
                "source_presentation_revision": provenance.presentation_revision,
                "source_variant_revision": provenance.variant_revision, "engine": provenance.engine.value,
                "content_sha256": snapshot.metadata.get("content_sha256"), "stale": stale, "renders": renders,
                "board_ids": sorted(boards)}

    async def _snapshots_of(self, presentation_id: str) -> tuple[list[Artifact], bool]:
        found: list[Artifact] = []
        cursor = None
        for _ in range(MAX_SCAN_PAGES):
            page = await self._artifacts.query(ArtifactQuery(kinds=(SNAPSHOT_KIND,), cursor=cursor, limit=SCAN_PAGE))
            found += [a for a in page.items if a.metadata.get("source_presentation_id") == presentation_id]
            if page.next_cursor is None:
                return found, False
            cursor = page.next_cursor
        return found, True

    async def _live(self, presentation_id: str, variant_id: str) -> tuple[int, int, Any]:
        """`(révision de la Presentation, révision de la variante, moteur)` vivants ; variante archivée = inconnue."""

        view = await self._studio.get(presentation_id)
        variant = next((v for v in view.variants if v.variant_id == variant_id), None)
        if variant is None:
            raise PresentationStudioError(_C.UNKNOWN_VARIANT, "unknown or archived variant")
        return view.presentation.revision, variant.revision, view.presentation.engine

    async def _live_summary(self, presentation_id: str) -> dict[str, Any]:
        try:
            view = await self._studio.get(presentation_id)
        except PresentationStudioError as exc:
            if exc.code is not _C.UNKNOWN_PRESENTATION:
                raise
            return {"exists": False}
        return {"exists": True, "title": view.presentation.title, "engine": view.presentation.engine.value,
                "revision": view.presentation.revision,
                "variant_revisions": {v.variant_id: v.revision for v in view.variants}}

    async def _provenance(self, presentation_id: str, variant_id: str, expected_presentation: int,
                          expected_variant: int) -> SourceProvenance:
        SourceRef(presentation_id, variant_id)  # ids bien formés avant toute lecture
        live_presentation, live_variant, engine = await self._live(presentation_id, variant_id)
        require_current(f"presentation {presentation_id}", expected_presentation=expected_presentation,
                        expected_variant=expected_variant, live_presentation=live_presentation, live_variant=live_variant)
        return SourceProvenance(presentation_id, variant_id, live_presentation, live_variant, engine)

    async def _find(self, artifact_id: str) -> Artifact | None:
        try:
            return await self._artifacts.get(artifact_id)
        except ArtifactError as exc:
            if exc.code is ArtifactErrorCode.ARTIFACT_NOT_FOUND:
                return None
            raise

    @staticmethod
    def _began(artifact: Artifact, *, created: bool) -> dict[str, Any]:
        return {"artifact": artifact, "created": created, "artifact_id": artifact.artifact_id,
                "state": artifact.state.value}

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not undo a committed write
            pass
