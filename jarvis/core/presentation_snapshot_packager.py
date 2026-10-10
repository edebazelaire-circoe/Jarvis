"""Gel d'une variante de Presentation en `snapshot.zip` autonome (Remotion Slice 09) et données vivantes d'une scène.

Contrat : `docs/presentation-artifacts.md` (« Snapshot package ») et `docs/presentation-live-refs.md`. Ce service ne possède
rien : la source reste au Studio, l'Artifact au registre, les sources de scène au `PrefabService`, les éléments de Board au
`LiveRefResolver`. Il assemble, écrit par le spool de l'`ArtifactService`, et pilote `begin_snapshot` / `finalize_snapshot`
de la Slice 07 avec le **vrai** SHA-256 du fichier.

Autorisation (refus par défaut) : la déclaration d'une scène ne décide **jamais** quel Board est lu. Le code Core appelant passe
`authorised_boards` (les Boards avec lesquels l'utilisateur travaille ou qu'il a explicitement accordés pour cette présentation ;
rien n'est persisté dans le Studio : les Slices 10/21 câblent l'appelant). Une référence vers un autre Board est `not_authorised`
(même état qu'un Board absent), rien n'est lu, le gel est refusé (`live_ref_not_authorised`) et le résultat du gel liste les Boards
réellement utilisés.

Ordre d'un gel (aucun paquet partiel) :

1. la source vivante est relue et doit avoir **exactement** les deux révisions attendues (sinon `presentation_studio_stale_revision`) ;
2. tout est assemblé **en mémoire** : documents, source exacte de chaque pin, référence vivante résolue une dernière fois ;
   une référence qui ne se résout pas ou n'est pas autorisée arrête le gel (`live_ref_unresolved` / `live_ref_not_authorised`),
   **aucun Artifact créé** ;
3. `begin_snapshot` (nouvelle garde de révision), écriture du spool, `finalize_snapshot` (re-garde, hash vérifié sur le fichier).
   Une erreur à l'écriture fait échouer le snapshot (`package_failed`) : jamais un `complete` sans fichier vérifié.

Rejeu : un snapshot déjà `complete` est rendu tel quel (`replayed: true`), son paquet n'est pas réécrit même si le Board a changé
depuis ; un `pending` dont le fichier final existe est vérifié (zip, empreintes, provenance) puis finalisé avec ce fichier ; s'il est
invalide, le snapshot devient `failed` (`package_invalid`). Deux gels simultanés des mêmes révisions se sérialisent (verrou par
instantané) : le second rejoue le premier.

Mémoire : le paquet est assemblé en mémoire, au pire ~ 2 x 64 Mio (membres + zip) par gel en cours ; des gels de présentations
différentes peuvent se superposer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection, Mapping
from datetime import datetime, timezone
from typing import Any

from jarvis.core.presentation_live_refs import LiveRefResolver
from jarvis.domain.artifacts import Artifact, ArtifactError, ArtifactErrorCode, ArtifactState
from jarvis.domain.prefab import validate_value
from jarvis.domain.presentation_artifacts import (
    MAX_SNAPSHOT_ATTEMPTS, SourceProvenance, require_current, snapshot_artifact_id,
)
from jarvis.domain.presentation_live_refs import (
    LIVE_REFS_PATH, LiveRef, LiveRefError, LiveRefErrorCode, ResolvedLiveRef, parse_declaration, parse_live_ref,
    sandbox_payload,
)
from jarvis.domain.presentation_snapshot_package import (
    MAX_PACKAGE_BYTES, FrozenPackage, build_package, canonical_json, read_package, sha256_hex,
)
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode, PresentationVariant
from jarvis.ports.v2 import DiagnosticSink

PACKAGE_FAILED = "package_failed"
PACKAGE_INVALID = "package_invalid"
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
        self._locks: dict[tuple[str, str, int, int], asyncio.Lock] = {}

    # ------------------------------------------------------------ pendant l'édition

    async def scene_live_data(self, presentation_id: str, variant_id: str, scene_id: str, *,
                              authorised_boards: Collection[str], expected: Mapping[str, str] | None = None) -> dict[str, Any]:
        """Données vivantes d'**une** scène de **cette** variante, sans jamais lever pour un état de référence :
        `{refs, declaration_errors, authorised_boards, payload}`. `refs` couvre **tous** les pins que la scène tient (le sien et
        ceux de ses variantes locales rangées), chaque ligne portant `prefab_id`, `version`, `active` ; `payload` (le message du
        bac à sable) ne vient que du pin courant. Une déclaration mal formée est une ligne de `declaration_errors`, pas une
        exception : l'écran la montre. Seuls les noms que la source du pin déclare existent, et seuls les Boards autorisés sont lus."""

        allowed = _authorised(authorised_boards)
        view = await self._studio.get(presentation_id)
        variant = next((v for v in view.variants if v.variant_id == variant_id), None)
        scene = None if variant is None else next((s for s in variant.scenes if s.scene_id == scene_id), None)
        if scene is None:
            raise LiveRefError(LiveRefErrorCode.UNKNOWN, "unknown scene in this presentation variant")
        current = (scene.prefab.prefab_id, scene.prefab.version)
        rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        payload: dict[str, Any] = {}
        for pin in sorted(scene.held_pins()):
            try:
                refs = await self._declared(*pin)
            except LiveRefError as exc:
                errors.append({"prefab_id": pin[0], "version": pin[1], "active": pin == current,
                               "code": exc.code.value, "message": str(exc)[:300]})
                self._trace("core.snapshot_packager.declaration_invalid", "Declaration de references vivantes invalide",
                            level="warning", data={"prefab_id": pin[0], "version": pin[1], "code": exc.code.value})
                continue
            resolved = await self._resolver.resolve_all(refs, authorised_boards=allowed,
                                                        expected=expected if pin == current else None)
            rows.extend({**item.status(), "prefab_id": pin[0], "version": pin[1], "active": pin == current}
                        for item in resolved.values())
            if pin == current:
                payload = sandbox_payload(resolved)
        return {"refs": rows, "declaration_errors": errors, "authorised_boards": sorted(allowed), "payload": payload}

    # ------------------------------------------------------------ geler

    async def freeze(self, presentation_id: str, variant_id: str, *, expected_presentation_revision: int,
                     expected_variant_revision: int, authorised_boards: Collection[str],
                     jarvis_session_id: str | None = None, context_id: str | None = None) -> dict[str, Any]:
        """Fige la variante. `authorised_boards` : voir l'en-tête (obligatoire). Le résultat porte `authorised_boards`, les Boards
        dont une donnée a réellement été copiée (pour la confirmation de l'utilisateur)."""

        allowed = _authorised(authorised_boards)
        key = (presentation_id, variant_id, expected_presentation_revision, expected_variant_revision)
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:  # two freezes of the same revisions never race on the spool: the second one replays
                return await self._freeze(presentation_id, variant_id, expected_presentation_revision,
                                          expected_variant_revision, allowed, jarvis_session_id, context_id)
        finally:
            if not lock.locked():
                self._locks.pop(key, None)

    async def _freeze(self, presentation_id: str, variant_id: str, expected_presentation_revision: int,
                      expected_variant_revision: int, allowed: frozenset[str], jarvis_session_id: str | None,
                      context_id: str | None) -> dict[str, Any]:
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
                        "content_sha256": known.metadata.get("content_sha256"),
                        "authorised_boards": await self._boards_of(known)}
            if known.state is ArtifactState.PENDING:
                info = self._artifacts.payload_info(known)
                resume = info is not None and info.final_bytes is not None
                break
        # Assembled BEFORE the snapshot exists: an unresolved or unauthorised live reference leaves no Artifact at all.
        assembled = None if resume else await self._assemble(view, variant, presentation_id, allowed)
        begun = await self._snapshots.begin_snapshot(
            presentation_id, variant_id, expected_presentation_revision=expected_presentation_revision,
            expected_variant_revision=expected_variant_revision, jarvis_session_id=jarvis_session_id, context_id=context_id)
        artifact: Artifact = begun["artifact"]
        info = self._artifacts.payload_info(artifact)
        if info is not None and info.final_bytes is not None:
            data = await self._read_all(artifact, info.final_bytes)  # an earlier attempt wrote it: verify, keep it
            try:
                package = await asyncio.to_thread(read_package, data)
                self._check_provenance(artifact, package)
            except LiveRefError as exc:
                await self._artifacts.fail(artifact.artifact_id, error_code=PACKAGE_INVALID)
                self._trace("core.snapshot_packager.resume_rejected", "Fichier de paquet en attente refuse", level="error",
                            data={"artifact_id": artifact.artifact_id, "reason": str(exc)[:200]})
                raise
            boards = _boards_in(package.manifest)
        else:
            if assembled is None:  # the file vanished between the check and begin: assemble now
                assembled = await self._assemble(view, variant, presentation_id, allowed)
            data, boards = assembled
            await self._write(artifact, data)
        digest = sha256_hex(data)
        done = await self._snapshots.finalize_snapshot(artifact.artifact_id, content_sha256=digest)
        self._trace("core.snapshot_packager.frozen", "Variante figee dans un paquet autonome",
                    data={"artifact_id": done.artifact_id, "size_bytes": len(data), "boards": len(boards)})
        return {"artifact": done, "artifact_id": done.artifact_id, "created": bool(begun["created"]), "replayed": False,
                "content_sha256": digest, "authorised_boards": sorted(boards)}

    async def read_snapshot(self, artifact_id: str) -> FrozenPackage:
        """Rouvre un snapshot **complet** à partir de son seul `snapshot.zip` : hash annoncé, puis chaque membre vérifié, puis
        la provenance du manifeste contre les métadonnées gelées de l'Artifact. Ne consulte ni le Board d'origine, ni la source
        vivante, ni le réseau. Toute falsification est journalisée (`core.snapshot_packager.tampered`, erreur) puis levée."""

        artifact = await self._artifacts.get(artifact_id)
        SourceProvenance.of_snapshot(artifact)
        if artifact.state is not ArtifactState.COMPLETE:
            raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT, f"snapshot {artifact_id} is {artifact.state.value}")
        info = self._artifacts.payload_info(artifact)
        if info is None or info.final_bytes is None:
            raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT, f"snapshot {artifact_id} has no snapshot.zip on disk")
        data = await self._read_all(artifact, info.final_bytes)
        try:
            if sha256_hex(data) != artifact.metadata.get("content_sha256"):
                raise LiveRefError(LiveRefErrorCode.PACKAGE_INVALID, "snapshot.zip no longer matches its recorded content_sha256")
            package = await asyncio.to_thread(read_package, data)
            self._check_provenance(artifact, package)
        except LiveRefError as exc:
            self._trace("core.snapshot_packager.tampered", "Paquet de snapshot falsifie ou corrompu", level="error",
                        data={"artifact_id": artifact_id, "reason": str(exc)[:200]})
            raise
        return package

    # ------------------------------------------------------------ interne

    @staticmethod
    def _check_provenance(artifact: Artifact, package: FrozenPackage) -> None:
        """La provenance écrite dans le manifeste est celle que l'Artifact a gelée : un paquet d'une autre variante ou révision,
        même bien formé, n'est jamais pris pour celui-ci."""

        if dict(package.manifest["provenance"]) != SourceProvenance.of_snapshot(artifact).to_metadata():
            raise LiveRefError(LiveRefErrorCode.PACKAGE_INVALID,
                               "the package manifest provenance differs from the snapshot's frozen source_* metadata")

    async def _boards_of(self, artifact: Artifact) -> list[str]:
        try:
            package = await self.read_snapshot(artifact.artifact_id)
        except (LiveRefError, ArtifactError):
            return []  # a replay still answers; the reopen path reports (and logs) the damage
        return sorted(_boards_in(package.manifest))

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

    async def _known(self, artifact_id: str) -> Artifact | None:
        try:
            return await self._artifacts.get(artifact_id)
        except ArtifactError as exc:
            if exc.code is ArtifactErrorCode.ARTIFACT_NOT_FOUND:
                return None
            raise

    async def _declared(self, prefab_id: str, version: int) -> tuple[LiveRef, ...]:
        manifest = await self._prefabs.manifest(prefab_id, version)
        if manifest.source is None or LIVE_REFS_PATH not in manifest.source.paths:
            return ()
        source = await self._prefabs.remotion_source(prefab_id, version)
        return parse_declaration(source.files[LIVE_REFS_PATH])

    async def _assemble(self, view: Any, variant: PresentationVariant, presentation_id: str,
                        allowed: frozenset[str]) -> tuple[bytes, set[str]]:
        """Tout le paquet, en mémoire, et les Boards dont une donnée est copiée. Lève avant d'avoir écrit quoi que ce soit."""

        presentation = view.presentation.to_document()
        # Only what the frozen variant needs: its index entry (no sibling variants, no archive history); `resources` stay.
        presentation["variants"] = [e for e in presentation["variants"] if e["variant_id"] == variant.variant_id]
        presentation["archived"] = []
        presentation["active_variant_id"] = variant.variant_id
        files: dict[str, bytes] = {
            "presentation/presentation.json": canonical_json(presentation),
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
        unresolved: dict[str, ResolvedLiveRef] = {}
        boards: set[str] = set()
        for prefab_id, version in pins:
            root = f"prefabs/{prefab_id}/{version}"
            manifest = await self._prefabs.manifest(prefab_id, version)
            row: dict[str, Any] = {"prefab_id": prefab_id, "version": version}
            if manifest.source is not None:
                source = await self._prefabs.remotion_source(prefab_id, version)
                for path, body in source.files.items():
                    files[f"{root}/{path}"] = body
                files[f"{root}/source.json"] = canonical_json(source.block.to_dict())
                # Défauts des propriétés figés avec la source (Slice 16) : le rendu part du paquet seul, jamais du manifeste vivant.
                defaults, _problems = validate_value(manifest.props, {}, "props")
                row.update(kind="remotion", source_digest=source.digest, engine=source.block.engine.to_dict(),
                           props_defaults=defaults if isinstance(defaults, dict) else {})
                refs = parse_declaration(source.files[LIVE_REFS_PATH]) if LIVE_REFS_PATH in source.files else ()
                resolved = await self._resolver.resolve_all(refs, authorised_boards=allowed)
                for item in resolved.values():
                    if item.state.value != "ok":
                        unresolved[f"{prefab_id}@{version}:{item.ref.name}"] = item
                        continue
                    assert item.data is not None
                    path = f"{root}/live/{item.ref.name}{item.extension}"
                    files[path] = item.data
                    boards.add(item.ref.board_id)
                    # `ref` keeps the original `board:<id>/...` string on purpose: it is the provenance of the copy.
                    live_rows.append({"prefab_id": prefab_id, "version": version, "name": item.ref.name,
                                      "ref": str(item.ref), "mime": item.mime, "size": len(item.data),
                                      "sha256": item.sha256, "path": path, "frozen_state": "ok"})
            else:
                bundle = await self._prefabs.bundle(prefab_id, version)
                files[f"{root}/bundle.json"] = canonical_json(
                    {k: bundle[k] for k in ("id", "version", "fingerprint", "manifest", "files")})
                row.update(kind="html", fingerprint=bundle["fingerprint"])
            prefab_rows.append(row)
        if unresolved:
            self._trace("core.snapshot_packager.refused", "Gel refuse : reference vivante non resolue ou non autorisee",
                        level="warning",
                        data={"presentation_id": presentation_id, "unresolved": len(unresolved),
                              "not_authorised": sum(i.state.value == "not_authorised" for i in unresolved.values())})
            LiveRefResolver.require_all_usable(unresolved)
        core = {
            "provenance": SourceProvenance(presentation_id, variant.variant_id, view.presentation.revision, variant.revision,
                                           view.presentation.engine).to_metadata(),
            "frozen_at": self._clock().astimezone(timezone.utc).isoformat(),
            "scenes": [{"scene_id": s.scene_id, "prefab": {"id": s.prefab.prefab_id, "version": s.prefab.version},
                        "pins": sorted([p, v] for p, v in s.held_pins())} for s in variant.scenes],
            "prefabs": prefab_rows, "live_refs": live_rows,
            "runtime": None if self._runtime is None else self._runtime(),
        }
        return await asyncio.to_thread(build_package, core, files), boards

    async def _write(self, artifact: Artifact, data: bytes) -> None:
        """Écrit `snapshot.zip` par le spool. Tout échec rend le snapshot `failed` (`package_failed`, preuve) et lève une erreur
        typée sans chemin de la machine. Un `.partial` laissé par une vie précédente n'est jamais écrasé ni supprimé : c'est un
        échec typé et l'essai suivant (`_aN`) repart propre."""

        try:
            spool = self._artifacts.open_spool(artifact)
        except Exception as exc:  # noqa: BLE001 - argued: every open failure becomes a typed failure + failed snapshot
            await self._fail_write(artifact, exc, "opening")
            raise self._typed(exc, "could not be opened for writing; a partial file from an earlier attempt may be there") from None
        try:
            await asyncio.to_thread(self._spool_write, spool, data)
        except BaseException as exc:
            spool.close()
            await self._fail_write(artifact, exc, "writing")
            if isinstance(exc, Exception):
                raise self._typed(exc, "could not be written") from None
            raise

    async def _fail_write(self, artifact: Artifact, exc: BaseException, step: str) -> None:
        await self._artifacts.fail(artifact.artifact_id, error_code=PACKAGE_FAILED)
        self._trace("core.snapshot_packager.write_failed", "Ecriture du paquet impossible", level="error",
                    data={"artifact_id": artifact.artifact_id, "step": step, "error": type(exc).__name__,
                          "code": getattr(exc, "code", None)})

    @staticmethod
    def _typed(exc: Exception, what: str) -> LiveRefError:
        code = getattr(exc, "code", None)
        suffix = f" ({code})" if isinstance(code, str) else f" ({type(exc).__name__})"
        return LiveRefError(LiveRefErrorCode.PACKAGE_FAILED, f"snapshot.zip {what}{suffix}")

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


def _authorised(boards: object) -> frozenset[str]:
    """Liste blanche obligatoire : une collection d'ids, jamais une chaîne (ses caractères ne sont pas des Boards)."""

    if isinstance(boards, (str, bytes)) or not isinstance(boards, Collection):
        raise LiveRefError(LiveRefErrorCode.INVALID, "authorised_boards must be a collection of Board ids")
    return frozenset(str(b) for b in boards)


def _boards_in(manifest: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for row in manifest["live_refs"]:
        try:
            out.add(parse_live_ref("x", row["ref"]).board_id)
        except (LiveRefError, KeyError, TypeError):
            continue
    return out
