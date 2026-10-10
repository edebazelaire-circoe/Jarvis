"""Sources integrees d'un modele de presentation (handoff jarvis-remotion-presentation-integration, Slice 19).

Decision du PM : promouvoir une presentation publie **un seul artefact** (le document `ptp_...`), jamais une scene par prefab dans la
bibliotheque partagee. Les sources des scenes y sont **integrees** par empreinte de contenu (`StudioTemplate.embedded`), privees au modele ;
l'instanciation les publie comme des prefabs **propres a la presentation neuve** (`presentation-studio.p<presentation>.s<scene>`, l'espace
reserve a la retention), par la porte de publication de Core (`PrefabService.save`), comme tout prefab de scene du Studio.

Ce module porte ce que le service de modeles delegue : le document de l'enregistrement (catalogue `presentation`, partition), la
verification avant instanciation et la publication des sources. Contrat : `docs/presentation-studio.md` > *Template and prefab promotion
contract* > *One artefact per presentation*.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from jarvis.domain.prefab import PrefabRef
from jarvis.domain.presentation_studio_template_remotion import (
    candidate_of, embedded_bytes, is_intact, licence_of, promotion_catalog, remotion_parts,
)
from jarvis.domain.presentation_studio_template_sanitize import MAX_FINDINGS, Finding, scan_text
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_reload import source_prefab_id
from jarvis.domain.presentation_studio_template import StudioTemplate
from jarvis.domain.remotion_source import decode_candidate_files, source_digest
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode as PC

PREFAB_STATUS = {PC.INVALID_DEFINITION: C.SOURCE_INVALID, PC.VERSION_LIMIT: C.LIMIT_REACHED, PC.ID_LIMIT: C.LIMIT_REACHED,
                 PC.STORAGE_IO: C.STORAGE_IO, PC.VERSION_EXISTS: C.ALREADY_EXISTS, PC.BASE_PROTECTED: C.SOURCE_INVALID}


def prefab_error(exc: PrefabStoreError) -> PresentationStudioError:
    return PresentationStudioError(PREFAB_STATUS.get(exc.code, C.PREFAB_UNAVAILABLE), f"shared library: {exc.code.value}: {exc.message}",
                                   warn=exc.code is not PC.STORAGE_IO)


def record_catalog(entries: Sequence[tuple[bool, Mapping[str, Any]]], acks: Sequence[str]) -> dict[str, Any]:
    """Le bloc `catalog` de l'enregistrement d'une presentation : `type: presentation`, compatibilite par moteur (natif seulement quand
    **toutes** les scenes le sont), pile, licences et amonts des sources (declaration publique, jamais la valeur d'un projet).
    `entries` : `(est_remotion, manifeste promu)` par scene."""

    engines = {"remotion": all(r for r, _ in entries), "slidecar": not any(r for r, _ in entries)}
    stack: list[str] = []
    licences: list[str] = []
    upstreams: list[dict[str, Any]] = []
    for _, manifest in entries:
        block = manifest.get("catalog") or {}
        stack += [t for t in block.get("stack", ()) if t not in stack]
        licence = block.get("license") or (block.get("upstream") or {}).get("license")
        if licence and licence not in licences:
            licences.append(licence)
        up = block.get("upstream")
        if isinstance(up, dict):
            row = {k: up[k] for k in ("name", "url", "ref", "license", "author") if up.get(k)}
            if row not in upstreams:
                upstreams.append(row)
    for tag in ("html", "css", "javascript") if engines["slidecar"] else ("react", "remotion", "typescript"):
        if tag not in stack:
            stack.append(tag)
    return {"type": "presentation", "compatibility": {e: "native" if ok else "unsupported" for e, ok in engines.items()},
            "stack": stack[:12], "licences": licences[:16], "upstreams": upstreams[:16], "licence_ack": sorted(acks)}


class EmbeddedSources:
    """Verifie puis publie les sources integrees d'un modele dans une presentation neuve."""

    def __init__(self, prefabs: Any) -> None:
        self._prefabs = prefabs

    async def precheck(self, template: StudioTemplate) -> None:
        """Avant toute ecriture : chaque source integree passe encore la validation et les gardes d'aujourd'hui (une garde posee depuis
        la promotion refuse la source ici, sans presentation a moitie creee)."""

        for digest, candidate in (template.embedded or {}).items():
            check = self._prefabs.validate_candidate(self._with_id(candidate, "presentation-studio.p000000000000.s000000000000"))
            if not check.ok:
                raise PresentationStudioError(C.SOURCE_INVALID, f"embedded source {digest[:12]} is refused today: {check.errors[0][:200]}")
            await self._provenance(candidate)

    async def install(self, template: StudioTemplate, presentation_id: str, scene_ids: Sequence[str],
                      actor: str) -> tuple[list[PrefabRef], list[dict[str, str]]]:
        """Un prefab propre a la presentation par scene (deux scenes de meme source = deux ids de meme contenu)."""

        refs: list[PrefabRef] = []
        states: list[dict[str, str]] = []
        for row, scene_id in zip(template.scenes, scene_ids):
            assert row.source is not None
            candidate = self._with_id((template.embedded or {})[row.source], source_prefab_id(presentation_id, scene_id))
            state = await self._provenance(candidate)
            if state == "declared_not_reverified":
                candidate = self._declared_only(candidate)
            try:
                publication = await self._prefabs.save(candidate, actor=actor, verified_import=state == "verified")
            except PrefabStoreError as exc:
                raise prefab_error(exc) from None
            refs.append(PrefabRef(publication.prefab_id, publication.version))
            states.append({"scene_id": scene_id, "provenance": state})
        return refs, states

    @staticmethod
    def _with_id(candidate: Mapping[str, Any], prefab_id: str) -> dict[str, Any]:
        out = copy.deepcopy(dict(candidate))
        out["manifest"]["id"] = prefab_id
        return out

    @staticmethod
    def _declared_only(candidate: Mapping[str, Any]) -> dict[str, Any]:
        """The same source with the importer-written keys removed: its origin stays a declaration, never a verification."""

        out = copy.deepcopy(dict(candidate))
        block = out["manifest"].get("catalog") or {}
        for key in ("commit", "archive_sha256", "imported_at", "changes", "source_sha256"):
            (block.get("upstream") or {}).pop(key, None)
        block.pop("runtime_license", None)
        return out

    async def _provenance(self, candidate: Mapping[str, Any]) -> str:
        """`none` (no claim), `verified` (the files match AND the library still holds the original verified import) or
        `declared_not_reverified` (the files match the claim, but nothing Core holds witnesses it: a hand-edited record can be self-consistent).
        A claim the files contradict is refused (`corrupt_document`)."""

        if not self._claims(candidate):
            return "none"
        up = (candidate["manifest"].get("catalog") or {}).get("upstream") or {}
        self._verified(candidate)   # raises when the files contradict the claim
        held = await self._prefabs.holds_verified_import(commit=str(up.get("commit", "")), archive_sha256=str(up.get("archive_sha256", "")),
                                                         source_sha256=str(up.get("source_sha256", "")))
        return "verified" if held else "declared_not_reverified"

    @staticmethod
    def _claims(candidate: Mapping[str, Any]) -> bool:
        block = candidate["manifest"].get("catalog") or {}
        up = block.get("upstream") or {}
        return any(up.get(k) for k in ("commit", "archive_sha256", "imported_at", "changes", "source_sha256")) \
            or bool(block.get("runtime_license"))

    @staticmethod
    def _verified(candidate: Mapping[str, Any]) -> bool:
        """The importer's keys survive only if the embedded files give back `source_sha256` (recomputed here)."""

        block = candidate["manifest"].get("catalog") or {}
        up = block.get("upstream") or {}
        claims = any(up.get(k) for k in ("commit", "archive_sha256", "imported_at", "changes", "source_sha256")) \
            or bool(block.get("runtime_license"))
        if not claims:
            return False
        if "sources" not in candidate:
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, "an embedded HTML source claims a verified import")
        try:
            files = decode_candidate_files(candidate["sources"], candidate["assets"])
        except ValueError:
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, "an embedded source holds files that cannot be decoded") from None
        if not up.get("source_sha256") or source_digest(files) != up["source_sha256"]:
            raise PresentationStudioError(C.CORRUPT_DOCUMENT,
                                          "an embedded source claims a verified import its files do not match")
        return True


def complete_remotion(a: Any, item: Any, tsx: Any, manifest: Mapping[str, Any]) -> None:
    """Slice 19: the TSX modules join the candidate as text (searched like any source, never rewritten), the manifest gets its
    engine-tagged catalog block, the provenance keeps only what it still deserves, assets need an explicit keep."""

    where = f"scene:{item.key}"
    modules, assets = remotion_parts(tsx)
    intact = is_intact(tsx, manifest)
    promoted, item.verified, found = promotion_catalog(item.build.candidate["manifest"], remotion=True, intact=intact, where=where)
    item.build.candidate.update(candidate_of(promoted, modules, assets))
    for path in sorted(modules):
        found.extend(scan_text(f"{where}.source.{path}", modules[path], a.terms, urls=True))
    for path in sorted(assets):   # an SVG is text: its title, desc and metadata can carry project words (other binaries are not read)
        if path.lower().endswith(".svg"):
            found.extend(scan_text(f"{where}.source.{path}", assets[path].decode("utf-8", errors="replace"), a.terms, urls=True))
    if assets and not intact and not a.request.keep_assets:
        found.append(Finding("assets_need_acknowledgement", f"{where}.source",
                             f"{len(assets)} asset(s) of public/ may be project media: pass keep_assets: true to keep them"))
    a.findings.extend(found[:MAX_FINDINGS])
    note_licence(a, item, promoted)


def note_licence(a: Any, item: Any, manifest: Mapping[str, Any]) -> None:
    licence = licence_of(manifest)
    if licence is not None:
        a.licences.setdefault(licence, []).append(f"scene:{item.key}")


def inventory(candidate: Mapping[str, Any]) -> dict[str, Any]:
    if "sources" in candidate:
        return {"engine": "remotion", "modules": sorted(candidate["sources"]), "assets": sorted(candidate["assets"]),
                "bytes": embedded_bytes(candidate)}
    return {"engine": "slidecar", "files": ["template", "style", "behavior"], "bytes": embedded_bytes(candidate)}
