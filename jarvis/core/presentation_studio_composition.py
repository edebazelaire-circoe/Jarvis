"""Service Core de la composition semantique de variantes (handoff jarvis-interactive-presentation-studio, Slice 19).

Composer = creer **une variante enfant** de la base dont chaque dimension (scenes, narration, mouvement, direction artistique) est
empruntee a la variante source que la demande nomme ; la provenance de chaque dimension est ecrite avec la variante
(`compositions/<variant_id>.json`). Ce n'est pas un merge : les sources sont des **entrees immuables** (leurs fichiers, leurs
partitions et leurs directions artistiques ne sont jamais ecrits), le resultat est toujours un nouveau noeud du graphe.

Le travail d'ecriture est celui de la branche de la Slice 16 (`PresentationStudioVariants.create_branch(compose=...)`) : meme
verrou, meme numero alloue avant toute ecriture, meme `persist_variant_locked` (donc le registre de pins voit la variante
composee avant qu'elle soit sur le disque, `variant_pins` y compris les variantes locales), meme manifeste ecrit en dernier,
meme evenement `created`, memes arrets bruts (reconciliation). Ce service ajoute le **composeur** : il lit les sources, juge
toute la demande et ne laisse rien s'ecrire tant qu'un conflit existe.

| Etape (sous le verrou, rien d'ecrit) | Refus |
| --- | --- |
| sources vivantes ; `source_revisions` | `unknown_variant`, `stale_revision` |
| au plus 4 variantes sources ; scenes choisies (tranches) ; prefabs des scenes | conflits `too_many_sources`, `scene_not_in_source`, `duplicate_scene`, `too_many_scenes`, `scene_incompatible` |
| partition : mouvement + narration (`merge_narrative`) ; valide contre les scenes du resultat | `source_has_no_score`, `source_document_missing`, `narrative_*`, `score_*` |
| direction artistique | `source_has_no_art_direction`, `source_document_missing` |

Tous les conflits sont rendus ensemble (`CompositionRefused.conflicts`), chacun avec un `fix`. `plan` execute exactement le meme
composeur sans rien ecrire ni depenser de numero. Contrat : `docs/presentation-studio.md` > *Comparison and semantic composition
contract*.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from jarvis.core.presentation_studio_linked import LinkedCopy
from jarvis.core.presentation_studio_variants import BranchComposition, PresentationStudioVariants
from jarvis.domain.presentation_studio import (
    PresentationStudioError, PresentationStudioErrorCode as C, PresentationVariant, dump_document, is_presentation_id, stamp,
)
from jarvis.domain.presentation_studio_composition import (
    DIMENSIONS, CompositionProvenance, CompositionRefused, CompositionRequest, Conflict, ConflictCode,
    DimensionProvenance, merge_narrative, parse_composition, parse_provenance, score_scene_conflicts, select_scenes,
    compose_rationale,
)
from jarvis.domain.presentation_studio_checks import _fail
from jarvis.domain.presentation_studio_score import Score, new_score_id, parse_score
from jarvis.domain.presentation_studio_variants import MAX_SOURCES, VARIANT_ID

#: Les refus du catalogue de prefabs qui sont des conflits de contenu (le reste, panne de disque ou de catalogue, se leve tel quel).
_SCENE_CONFLICT_CODES = frozenset({C.SCENE_INCOMPATIBLE, C.PREFAB_UNAVAILABLE, C.VALUE_REFUSED, C.UNKNOWN_CONTROL})


class PresentationStudioComposition:
    def __init__(self, studio: Any, variants: PresentationStudioVariants) -> None:
        self._studio = studio
        self._variants = variants

    # ------------------------------------------------------------ operations

    async def plan(self, presentation_id: str, raw: object) -> dict[str, Any]:
        """**A blanc** : juge la demande exactement comme `compose` et rend `{ok, conflicts, composition}`. N'ecrit rien, ne depense
        aucun numero. Un conflit n'est pas une erreur ici (200, `ok: false`) ; une demande mal formee reste un 400."""

        self._require(presentation_id)
        request = parse_composition(raw)
        try:
            answer = await self._variants.create_branch(presentation_id, self._branch_body(request),
                                                        compose=self._composer(presentation_id, request), dry_run=True)
        except CompositionRefused as refused:
            self._trace("composition_planned", presentation_id, request, ok=False, conflicts=len(refused.conflicts))
            return {"ok": False, "dry_run": True, "conflicts": refused.conflicts, "composition": None}
        self._trace("composition_planned", presentation_id, request, ok=True, conflicts=0)
        return {"ok": True, "dry_run": True, "conflicts": [], "composition": answer["composition"]}

    async def compose(self, presentation_id: str, raw: object) -> dict[str, Any]:
        """Cree la variante composee. Conflits : `CompositionRefused` (409) **avant** toute ecriture. Succes : la reponse d'une
        branche (`variant`, `node`, `presentation_revision`, `activated`, `source_variant_id`, `linked`) plus `composition` (la
        provenance ecrite)."""

        self._require(presentation_id)
        request = parse_composition(raw)
        try:
            answer = await self._variants.create_branch(presentation_id, self._branch_body(request),
                                                        compose=self._composer(presentation_id, request))
        except CompositionRefused as refused:
            self._trace("composition_refused", presentation_id, request, ok=False, conflicts=len(refused.conflicts))
            raise
        self._trace("composition_created", presentation_id, request, ok=True, conflicts=0)
        return answer

    async def provenance(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        """La provenance ecrite d'une variante composee. `presentation_studio_unknown_composition` (404) si elle ne vient pas d'une composition."""

        self._require(presentation_id)
        if not VARIANT_ID.fullmatch(variant_id):
            raise PresentationStudioError(C.UNKNOWN_VARIANT, "unknown variant id")

        async def read() -> dict[str, Any]:
            async with self._studio.exclusive():
                try:
                    text = await self._studio.run_blocking("composition", presentation_id, self._studio.store.read_composition,
                                                           presentation_id, variant_id)
                except PresentationStudioError as exc:
                    if exc.code is C.UNKNOWN_VARIANT:
                        raise PresentationStudioError(C.UNKNOWN_COMPOSITION, f"{variant_id} is not the result of a composition") from None
                    raise
                provenance = self._studio.parse_stored(parse_provenance, text, f"{presentation_id}/compositions/{variant_id}")
                if (provenance.presentation_id, provenance.variant_id) != (presentation_id, variant_id):
                    raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{presentation_id}/compositions/{variant_id}: names another variant")
                return {"composition": provenance.to_document()}

        return await self._studio.guarded("composition", presentation_id, read())

    # ------------------------------------------------------------ le composeur

    @staticmethod
    def _branch_body(request: CompositionRequest) -> dict[str, Any]:
        """Le corps d'une branche de la base (la raison finale est celle du composeur : elle porte le resume de la composition)."""

        return {"title": request.title, "source_variant_id": request.base, "rationale": request.rationale,
                "activate": request.activate, "actor": request.actor,
                **({} if request.expected_revision is None else {"expected_revision": request.expected_revision})}

    def _composer(self, presentation_id: str, request: CompositionRequest):
        async def compose(variants: Mapping[str, PresentationVariant], base: PresentationVariant, new_id: str,
                          now: datetime) -> BranchComposition:
            return await self._compose_locked(presentation_id, request, variants, base, new_id, now)

        return compose

    async def _compose_locked(self, presentation_id: str, request: CompositionRequest,
                              variants: Mapping[str, PresentationVariant], base: PresentationVariant, new_id: str,
                              now: datetime) -> BranchComposition:
        ids = request.sources()
        for variant_id in ids:
            if variant_id not in variants:
                raise PresentationStudioError(C.UNKNOWN_VARIANT, f"{variant_id} is not a live variant of this presentation "
                                                                 "(an archived variant must be restored first)")
        for variant_id, revision in request.source_revisions.items():
            if variant_id not in ids:
                raise _fail(f"source_revisions names {variant_id}, which is not a source of this composition")
            if variants[variant_id].revision != revision:
                raise PresentationStudioError(
                    C.STALE_REVISION, f"{variant_id} is at revision {variants[variant_id].revision}, not {revision}: "
                                      "reload the comparison, then retry")
        if len(ids) > MAX_SOURCES:
            raise CompositionRefused([Conflict(
                ConflictCode.TOO_MANY_SOURCES, "scenes", f"the request draws on {len(ids)} variants; the limit is {MAX_SOURCES}",
                "Use fewer distinct source variants.", {"variant_ids": list(ids)})])
        conflicts: list[Conflict] = []
        at = stamp(now)
        numbers = {v: variants[v].variant_number for v in ids}

        def source_row(variant_id: str, document_id: str | None = None, **extra: Any) -> dict[str, Any]:
            return {"variant_id": variant_id, "variant_number": numbers[variant_id],
                    "source_revision": variants[variant_id].revision, "document_id": document_id, **extra}

        # ---- scenes
        normalized: dict[str, tuple[Any, ...]] = {base.variant_id: base.scenes}
        for segment in request.segments():
            if segment.variant_id not in normalized:
                normalized[segment.variant_id] = await self._studio.scenes_for_copy(presentation_id, variants[segment.variant_id])
        scenes, scene_conflicts = select_scenes(request, normalized)
        conflicts += scene_conflicts
        if not scene_conflicts:
            try:
                await self._studio.check_scenes(presentation_id, base.variant_id, scenes, base.scenes)
            except PresentationStudioError as exc:
                if exc.code not in _SCENE_CONFLICT_CODES:
                    raise
                conflicts.append(Conflict(
                    ConflictCode.SCENE_INCOMPATIBLE, "scenes", f"the chosen scenes do not pass their prefab checks ({exc.code.value}): {exc.message}",
                    "Take the scenes from a variant whose prefab versions are available, or fix the scene in its own variant first.",
                    {"code": exc.code.value}))
        used_sources = {s.variant_id for s in request.segments()}
        scene_rows = []
        for segment in request.segments():
            chosen = segment.scene_ids if segment.scene_ids is not None else tuple(s.scene_id for s in normalized[segment.variant_id])
            scene_rows.append(source_row(segment.variant_id, scene_ids=list(chosen)))
        dims: dict[str, DimensionProvenance] = {
            "scenes": DimensionProvenance("scenes", request.inherited("scenes"), tuple(scene_rows),
                                          {"scene_count": len(scenes), "segments": len(scene_rows)})}
        candidate = replace(base, scenes=scenes)

        # ---- score (motion + narrative)
        score, score_copy, score_dims, warnings = await self._score(
            presentation_id, request, variants, candidate, new_id, at, conflicts, source_row)
        dims.update(score_dims)

        # ---- art direction
        art_copy, art_dim = await self._art_direction(presentation_id, request, variants, new_id, now, conflicts, source_row)
        dims["art_direction"] = art_dim
        if conflicts:
            raise CompositionRefused(conflicts)

        rationale = compose_rationale(request, numbers)
        provenance = CompositionProvenance(
            presentation_id, new_id, request.base, at, request.actor, tuple(dims[d] for d in DIMENSIONS), tuple(warnings[:8]))
        text = dump_document(provenance.to_document())
        copies = await self._copies(presentation_id, base, new_id, now, score_copy, art_copy)

        async def write_provenance() -> None:
            await self._studio.run_blocking("compose_provenance", presentation_id, self._studio.store.write_composition,
                                            presentation_id, new_id, text)

        report = {**provenance.to_document(), "result": {
            "scene_count": len(scenes), "scene_ids": [s.scene_id for s in scenes][:64],
            "has_score": score_copy is not None and score_copy.new_ref is not None,
            "has_art_direction": art_copy is not None and art_copy.new_ref is not None,
            "item_count": 0 if score is None else len(score.items), "sources": list(request.sources()),
            "parent_variant_id": request.base, "summary": rationale}}
        return BranchComposition(candidate, copies, request.sources(), (write_provenance,), rationale, report)

    async def _score(self, presentation_id: str, request: CompositionRequest, variants: Mapping[str, PresentationVariant],
                     candidate: PresentationVariant, new_id: str, at: str, conflicts: list[Conflict], source_row: Any
                     ) -> tuple[Score | None, LinkedCopy | None, dict[str, DimensionProvenance], list[str]]:
        motion_id, narrative_id = request.source_of("motion"), request.source_of("narrative")
        motion_var, narrative_var = variants[motion_id], variants[narrative_id]
        warnings: list[str] = []
        none = LinkedCopy("score", None, None, "none")

        def dimension(name: str, variant_id: str, applied: bool, document_id: str | None, detail: dict[str, Any]) -> DimensionProvenance:
            return DimensionProvenance(name, request.inherited(name), (source_row(variant_id, document_id),),
                                       {"applied": applied, **detail})

        async def load(variant: PresentationVariant, *names: str) -> Score | None:
            name = names[0]
            if variant.score_id is None:
                for named in names:
                    if not request.inherited(named):
                        conflicts.append(Conflict(
                            ConflictCode.SOURCE_HAS_NO_SCORE, named, f"{variant.variant_id} has no score to borrow {named} from",
                            "Pick a source variant that has a score, or leave this dimension to the base.",
                            {"source_variant_id": variant.variant_id}))
                return None
            try:
                return await self._studio.load_score_locked(presentation_id, variant)
            except PresentationStudioError as exc:
                if exc.code is not C.UNKNOWN_SCORE:
                    raise
                conflicts.append(Conflict(
                    ConflictCode.SOURCE_DOCUMENT_MISSING, name, f"the score file of {variant.variant_id} is missing",
                    "Repair that variant's score first (score routes), or pick another source.", {"source_variant_id": variant.variant_id}))
                return None

        motion_score = await load(motion_var, *(("motion", "narrative") if narrative_id == motion_id else ("motion",)))
        narrative_score = motion_score if narrative_id == motion_id else await load(narrative_var, "narrative")
        dims: dict[str, DimensionProvenance] = {}
        merged = motion_score
        narrative_detail: dict[str, Any] = {}
        narrative_applied = narrative_score is not None
        if motion_score is None:
            if narrative_score is not None and narrative_id != motion_id and not request.inherited("narrative"):
                conflicts.append(Conflict(
                    ConflictCode.SOURCE_HAS_NO_SCORE, "motion",
                    f"narrative is borrowed from {narrative_id} but the motion source {motion_id} has no score to carry it",
                    "Take motion from a variant that has a score (for example the narrative source), or drop the narrative dimension.",
                    {"source_variant_id": motion_id}))
            narrative_applied = False
        elif narrative_score is not None and narrative_id != motion_id:
            outcome = merge_narrative(motion_score, narrative_score, request.on_unmapped)
            conflicts += list(outcome.conflicts)
            narrative_detail = outcome.detail()
            merged = outcome.score
            if outcome.kept_from_motion:
                warnings.append(f"{len(outcome.kept_from_motion)} item(s) kept their own narration (no equivalent in the narrative source)")
            if outcome.dropped_source_items:
                warnings.append(f"{outcome.dropped_source_items} item(s) of the narrative source were not used (no equivalent in the motion source)")
        elif narrative_score is None and narrative_id != motion_id:
            narrative_applied = False  # the base has no narration to lend: the motion source keeps its own
        dims["motion"] = dimension("motion", motion_id, motion_score is not None, motion_var.score_id if motion_score else None,
                                   {"fields": ["items", "actions", "timing", "cues", "sequences", "recovery_points"]})
        dims["narrative"] = dimension("narrative", narrative_id, narrative_applied, narrative_var.score_id if narrative_score else None,
                                      narrative_detail or {"fields": ["label", "text", "note"], "same_as_motion": narrative_id == motion_id})
        if merged is None:
            return None, None, dims, warnings
        copied = replace(merged, score_id=new_score_id(), variant_id=new_id, revision=1, created_at=at, updated_at=at)
        problems_before = len(conflicts)
        try:
            parse_score(copied.to_document())
        except PresentationStudioError as exc:
            conflicts.append(Conflict(ConflictCode.SCORE_INVALID, "motion", f"the composed score is invalid: {exc.message}",
                                      "Take narrative and motion from the same variant.", {}))
        conflicts += score_scene_conflicts(copied, (s.scene_id for s in candidate.scenes), "motion", motion_id)
        if len(conflicts) == problems_before:  # the scene references resolve: now controls, anchors and values
            try:
                await self._studio.check_candidate_score(copied, candidate)
            except PresentationStudioError as exc:
                if exc.code not in (C.SCORE_INCOMPATIBLE, C.PREFAB_UNAVAILABLE):
                    raise
                conflicts.append(Conflict(
                    ConflictCode.SCORE_INCOMPATIBLE, "motion", f"the score does not fit the composed scenes: {exc.message}",
                    "Take the scenes from the variant that owns the score (a control, anchor or value differs), or take the score from another variant.",
                    {"code": exc.code.value}))
        text = dump_document(copied.to_document())
        studio = self._studio

        async def write() -> None:
            await studio.run_blocking("compose_score", presentation_id, studio.store.write_score, presentation_id, copied.score_id, text)

        return copied, LinkedCopy("score", motion_var.score_id, copied.score_id, "copied", write), dims, warnings

    async def _art_direction(self, presentation_id: str, request: CompositionRequest, variants: Mapping[str, PresentationVariant],
                             new_id: str, now: datetime, conflicts: list[Conflict], source_row: Any
                             ) -> tuple[LinkedCopy | None, DimensionProvenance]:
        source_id = request.source_of("art_direction")
        source = variants[source_id]
        kind = next((k for k in self._variants.linked.kinds if k.name == "art_direction"), None)
        copy: LinkedCopy | None = None
        if source.art_direction_id is None:
            if not request.inherited("art_direction"):
                conflicts.append(Conflict(
                    ConflictCode.SOURCE_HAS_NO_ART_DIRECTION, "art_direction", f"{source_id} has no art direction to borrow",
                    "Pick a source variant that has an art direction, or leave this dimension to the base.", {"source_variant_id": source_id}))
        else:
            self._variants.linked.refuse_unsupported(source)
            copy = await kind.prepare(presentation_id, source, new_id, now)  # type: ignore[union-attr]
            if copy.status == "missing_source":
                conflicts.append(Conflict(
                    ConflictCode.SOURCE_DOCUMENT_MISSING, "art_direction", f"the art direction file of {source_id} is missing",
                    "Repair that variant's art direction first, or pick another source.", {"source_variant_id": source_id}))
        row = source_row(source_id, source.art_direction_id if copy is not None else None)
        return copy, DimensionProvenance("art_direction", request.inherited("art_direction"), (row,), {"applied": copy is not None})

    async def _copies(self, presentation_id: str, base: PresentationVariant, new_id: str, now: datetime,
                      score_copy: LinkedCopy | None, art_copy: LinkedCopy | None) -> tuple[LinkedCopy, ...]:
        """Un `LinkedCopy` par genre enregistre, dans l'ordre ; un genre que cette Slice ne connait pas est copie depuis la base."""

        out: list[LinkedCopy] = []
        for kind in self._variants.linked.kinds:
            if kind.name == "score":
                out.append(score_copy or LinkedCopy("score", None, None, "none"))
            elif kind.name == "art_direction":
                out.append(art_copy or LinkedCopy("art_direction", None, None, "none"))
            else:
                out.append(await kind.prepare(presentation_id, base, new_id, now))
        return tuple(out)

    # ------------------------------------------------------------ interne

    @staticmethod
    def _require(presentation_id: str) -> None:
        if not is_presentation_id(presentation_id):
            raise PresentationStudioError(C.UNKNOWN_PRESENTATION, "unknown presentation id")

    def _trace(self, kind: str, presentation_id: str, request: CompositionRequest, *, ok: bool, conflicts: int) -> None:
        # Ids, counts and flags only: never a title, a rationale or a text.
        self._studio.trace(
            f"core.presentation_studio.{kind}", "Composition de variantes", level="info" if ok else "warning",
            data={"presentation_id": presentation_id, "base": request.base, "sources": len(request.sources()),
                  "inherited": [d for d in DIMENSIONS if request.inherited(d)], "ok": ok, "conflicts": conflicts,
                  "actor": request.actor})

