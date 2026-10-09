"""Gel d'une variante de Presentation en `snapshot.zip` autonome (Remotion Slice 09) et données vivantes d'une scène.

Contrat : `docs/presentation-artifacts.md` (« Snapshot package ») et `docs/presentation-live-refs.md`. Ce service ne possède
rien : la source reste au Studio, l'Artifact au registre, les sources de scène au `PrefabService`, les éléments de Board au
`LiveRefResolver`. Il assemble, écrit par le spool de l'`ArtifactService`, et pilote `begin_snapshot` / `finalize_snapshot`
de la Slice 07 avec le **vrai** SHA-256 du fichier.

Ordre d'un gel (aucun paquet partiel) :

1. la source vivante est relue et doit avoir **exactement** les deux révisions attendues (sinon `presentation_studio_stale_revision`) ;
2. tout est assemblé **en mémoire** : documents, source exacte de chaque pin, référence vivante résolue une dernière fois ;
   une référence qui ne se résout pas (`missing`, `too_large`...) arrête le gel : `live_ref_unresolved`, **aucun Artifact créé** ;
3. `begin_snapshot` (nouvelle garde de révision), écriture du spool, `finalize_snapshot` (re-garde, hash vérifié sur le fichier).
   Une erreur à l'écriture fait échouer le snapshot (`package_failed`) : jamais un `complete` sans fichier vérifié.

Rejeu : un snapshot déjà `complete` est rendu tel quel (`replayed: true`), son paquet n'est pas réécrit même si le Board a changé
depuis ; un `pending` dont le fichier final existe est vérifié puis finalisé avec ce fichier.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from jarvis.core.presentation_live_refs import LiveRefResolver
from jarvis.domain.artifacts import Artifact, ArtifactError, ArtifactErrorCode, ArtifactState
from jarvis.domain.presentation_artifacts import (
    MAX_SNAPSHOT_ATTEMPTS, SourceProvenance, require_current, snapshot_artifact_id,
)
from jarvis.domain.presentation_live_refs import (
    LIVE_REFS_PATH, LiveRef, LiveRefError, LiveRefErrorCode, ResolvedLiveRef, parse_declaration, sandbox_payload,
)
from jarvis.domain.presentation_snapshot_package import (
    MAX_PACKAGE_BYTES, FrozenPackage, build_package, canonical_json, read_package, sha256_hex,
)
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode, PresentationVariant
from jarvis.ports.v2 import DiagnosticSink

PACKAGE_FAILED = "package_failed"
HASH_CHUNK = 1 << 20
_C = PresentationStudioErrorCode


class PresentationPackager:
    def __init__(self, *, studio: Any, artifacts: Any, snapshots: Any, prefabs: Any, resolver: LiveRefResolver,
                 runtime: Callable[[], Mapping[str, Any] | None] | None = None,
                 clock: Callable[[], datetime] | None = None, diagnostics: DiagnosticSink | None = None) -> None:
        """`snapshots` = `PresentationArtifacts` ; `prefabs` = `PrefabService` (`manifest`, `remotion_source`, `bundle`) ;
        `runtime` rend ce que la capacité locale a réellement installé (`InstalledEngine.to_dict()`), `None` si inconnu."""

        self._studio = studio
        self._artifacts = artifacts
        self._snapshots = snapshots
        self._prefabs = prefabs
        self._resolver = resolver
        self._runtime = runtime
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._diagnostics = diagnostics

    # ------------------------------------------------------------ pendant l'édition

    async def scene_live_data(self, presentation_id: str, variant_id: str, scene_id: str, *,
                              expected: Mapping[str, str] | None = None) -> dict[str, Any]:
        """Données vivantes d'**une** scène de **cette** variante : `{refs: [statut...], payload: <message bac à sable>}`.
        Seuls les noms que la source du pin de la scène déclare existent ; l'état de chaque référence est dit, jamais caché."""

        view = await self._studio.get(presentation_id)
        variant = next((v for v in view.variants if v.variant_id == variant_id), None)
        scene = None if variant is None else next((s for s in variant.scenes if s.scene_id == scene_id), None)
        if scene is None:
            raise LiveRefError(LiveRefErrorCode.UNKNOWN, "unknown scene in this presentation variant")
        refs = await self._declared(scene.prefab.prefab_id, scene.prefab.version)
        resolved = await self._resolver.resolve_all(refs, expected=expected)
        return {"refs": [item.status() for item in resolved.values()], "payload": sandbox_payload(resolved)}

    # ------------------------------------------------------------ geler

    async def freeze(self, presentation_id: str, variant_id: str, *, expected_presentation_revision: int,
                     expected_variant_revision: int, jarvis_session_id: str | None = None,
                     context_id: str | None = None) -> dict[str, Any]:
        view, variant = await self._current(presentation_id, variant_id, expected_presentation_revision,
                                            expected_variant_revision)
        resume = False
        for attempt in range(1, MAX_SNAPSHOT_ATTEMPTS + 1):
            known = await self._known(snapshot_artifact_id(presentation_id, variant_id, expected_presentation_revision,
                                                           expected_variant_revision, attempt))
            if known is None:
                break
            if known.state is ArtifactState.COMPLETE:  # replay: nothing is read from the Board, nothing is rewritten
                self._trace("core.snapshot_packager.replayed", "Gel rejoue : snapshot deja complet",
                            data={"artifact_id": known.artifact_id})
                return {"artifact": known, "artifact_id": known.artifact_id, "created": False, "replayed": True,
                        "content_sha256": known.metadata.get("content_sha256")}
            if known.state is ArtifactState.PENDING:
                info = self._artifacts.payload_info(known)
                resume = info is not None and info.final_bytes is not None
                break
        # Assembled BEFORE the snapshot exists: an unresolved live reference leaves no Artifact at all.
        data = None if resume else await self._assemble(view, variant, presentation_id)
        begun = await self._snapshots.begin_snapshot(
            presentation_id, variant_id, expected_presentation_revision=expected_presentation_revision,
            expected_variant_revision=expected_variant_revision, jarvis_session_id=jarvis_session_id, context_id=context_id)
        artifact: Artifact = begun["artifact"]
        info = self._artifacts.payload_info(artifact)
        if info is not None and info.final_bytes is not None:
            data = await self._read_all(artifact, info.final_bytes)  # an earlier attempt wrote it: verify, keep it
            await asyncio.to_thread(read_package, data)
        else:
            if data is None:  # the file vanished between the check and begin: assemble now
                data = await self._assemble(view, variant, presentation_id)
            await self._write(artifact, data)
        digest = sha256_hex(data)
        done = await self._snapshots.finalize_snapshot(artifact.artifact_id, content_sha256=digest)
        self._trace("core.snapshot_packager.frozen", "Variante figee dans un paquet autonome",
                    data={"artifact_id": done.artifact_id, "size_bytes": len(data)})
        return {"artifact": done, "artifact_id": done.artifact_id, "created": bool(begun["created"]), "replayed": False,
                "content_sha256": digest}

    async def _known(self, artifact_id: str) -> Artifact | None:
        try:
            return await self._artifacts.get(artifact_id)
        except ArtifactError as exc:
            if exc.code is ArtifactErrorCode.ARTIFACT_NOT_FOUND:
                return None
            raise

    async def read_snapshot(self, artifact_id: str) -> FrozenPackage:
        """Rouvre un snapshot **complet** à partir de son seul `snapshot.zip` : hash annoncé, puis chaque membre vérifié.
        Ne consulte ni le Board d'origine, ni la source vivante, ni le réseau."""

        artifact = await self._artifacts.get(artifact_id)
        SourceProvenance.of_snapshot(artifact)
        if artifact.state is not ArtifactState.COMPLETE:
            raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT, f"snapshot {artifact_id} is {artifact.state.value}")
        info = self._artifacts.payload_info(artifact)
        if info is None or info.final_bytes is None:
            raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT, f"snapshot {artifact_id} has no snapshot.zip on disk")
        data = await self._read_all(artifact, info.final_bytes)
        if sha256_hex(data) != artifact.metadata.get("content_sha256"):
            raise LiveRefError(LiveRefErrorCode.PACKAGE_INVALID, "snapshot.zip no longer matches its recorded content_sha256")
        package = await asyncio.to_thread(read_package, data)
        return package

    # ------------------------------------------------------------ interne

    async def _current(self, presentation_id: str, variant_id: str, expected_presentation: int,
                       expected_variant: int) -> tuple[Any, PresentationVariant]:
        view = await self._studio.get(presentation_id)
        variant = next((v for v in view.variants if v.variant_id == variant_id), None)
        if variant is None:
            raise PresentationStudioError(_C.UNKNOWN_VARIANT, "unknown or archived variant")
        require_current(f"presentation {presentation_id}", expected_presentation=expected_presentation,
                        expected_variant=expected_variant, live_presentation=view.presentation.revision,
                        live_variant=variant.revision)
        return view, variant

    async def _declared(self, prefab_id: str, version: int) -> tuple[LiveRef, ...]:
        manifest = await self._prefabs.manifest(prefab_id, version)
        if manifest.source is None or LIVE_REFS_PATH not in manifest.source.paths:
            return ()
        source = await self._prefabs.remotion_source(prefab_id, version)
        return parse_declaration(source.files[LIVE_REFS_PATH])

    async def _assemble(self, view: Any, variant: PresentationVariant, presentation_id: str) -> bytes:
        """Tout le paquet, en mémoire. Lève avant d'avoir écrit quoi que ce soit."""

        files: dict[str, bytes] = {
            "presentation/presentation.json": canonical_json(view.presentation.to_document()),
            "presentation/variant.json": canonical_json(variant.to_document()),
        }
        if variant.art_direction_id is not None:
            files["presentation/art_direction.json"] = canonical_json(
                (await self._studio.get_art_direction(presentation_id, variant.variant_id))["art_direction"])
        if variant.score_id is not None:
            files["presentation/score.json"] = canonical_json(
                (await self._studio.get_score(presentation_id, variant.variant_id))["score"])
        pins = sorted({pin for scene in variant.scenes for pin in scene.held_pins()})
        prefab_rows: list[dict[str, Any]] = []
        live_rows: list[dict[str, Any]] = []
        unresolved: list[ResolvedLiveRef] = []
        for prefab_id, version in pins:
            root = f"prefabs/{prefab_id}/{version}"
            manifest = await self._prefabs.manifest(prefab_id, version)
            row: dict[str, Any] = {"prefab_id": prefab_id, "version": version}
            if manifest.source is not None:
                source = await self._prefabs.remotion_source(prefab_id, version)
                for path, body in source.files.items():
                    files[f"{root}/{path}"] = body
                files[f"{root}/source.json"] = canonical_json(source.block.to_dict())
                row.update(kind="remotion", source_digest=source.digest, engine=source.block.engine.to_dict())
                refs = parse_declaration(source.files[LIVE_REFS_PATH]) if LIVE_REFS_PATH in source.files else ()
                resolved = await self._resolver.resolve_all(refs)
                for item in resolved.values():
                    if item.state.value != "ok":
                        unresolved.append(item)
                        continue
                    assert item.data is not None
                    path = f"{root}/live/{item.ref.name}{item.extension}"
                    files[path] = item.data
                    live_rows.append({"prefab_id": prefab_id, "version": version, "name": item.ref.name,
                                      "ref": str(item.ref), "mime": item.mime, "size": len(item.data),
                                      "sha256": item.sha256, "path": path, "frozen_state": "ok"})
            else:
                bundle = await self._prefabs.bundle(prefab_id, version)
                files[f"{root}/bundle.json"] = canonical_json({k: bundle[k] for k in ("id", "version", "fingerprint", "manifest", "files")})
                row.update(kind="html", fingerprint=bundle["fingerprint"])
            prefab_rows.append(row)
        if unresolved:
            self._trace("core.snapshot_packager.refused", "Gel refusé : référence vivante non résolue", level="warning",
                        data={"presentation_id": presentation_id, "unresolved": len(unresolved)})
            LiveRefResolver.require_all_usable({f"{u.ref.name}@{i}": u for i, u in enumerate(unresolved)})
        core = {
            "provenance": SourceProvenance(presentation_id, variant.variant_id, view.presentation.revision, variant.revision,
                                           view.presentation.engine).to_metadata(),
            "frozen_at": self._clock().astimezone(timezone.utc).isoformat(),
            "scenes": [{"scene_id": s.scene_id, "prefab": {"id": s.prefab.prefab_id, "version": s.prefab.version},
                        "pins": sorted([p, v] for p, v in s.held_pins())} for s in variant.scenes],
            "prefabs": prefab_rows, "live_refs": live_rows,
            "runtime": None if self._runtime is None else self._runtime(),
        }
        return await asyncio.to_thread(build_package, core, files)

    async def _write(self, artifact: Artifact, data: bytes) -> None:
        spool = self._artifacts.open_spool(artifact)
        try:
            await asyncio.to_thread(self._spool_write, spool, data)
        except BaseException:
            spool.close()
            await self._artifacts.fail(artifact.artifact_id, error_code=PACKAGE_FAILED)
            self._trace("core.snapshot_packager.write_failed", "Écriture du paquet impossible", level="error",
                        data={"artifact_id": artifact.artifact_id})
            raise

    @staticmethod
    def _spool_write(spool: Any, data: bytes) -> None:
        spool.write(data)
        spool.finalize()

    async def _read_all(self, artifact: Artifact, size: int) -> bytes:
        if size > MAX_PACKAGE_BYTES:
            raise LiveRefError(LiveRefErrorCode.PACKAGE_TOO_LARGE, f"snapshot.zip is {size} bytes, at most {MAX_PACKAGE_BYTES}")

        def read() -> bytes:
            chunks, offset = [], 0
            while True:
                chunk = self._artifacts.read_payload(artifact, offset, HASH_CHUNK)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                offset += len(chunk)

        return await asyncio.to_thread(read)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is not None:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
