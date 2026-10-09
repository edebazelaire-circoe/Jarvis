"""Presentation Studio : la composition semantique de variantes (handoff jarvis-interactive-presentation-studio, Slice 19).

Composer, c'est creer **une nouvelle variante enfant** dont chaque *dimension semantique* est empruntee a une variante
source nommee : jamais un merge de fichiers. Quatre dimensions, fermees :

| Dimension | Ce qu'elle emprunte | Source par defaut |
| --- | --- | --- |
| `scenes` | la liste des scenes (structure, prefab epingle, valeurs, controles, ancres) ; une ou plusieurs tranches `{from, scene_ids?}` | la base |
| `narrative` | le texte dit (`text`), la note d'intention (`note`) et le `label` des items de la partition | la base |
| `motion` | tout le reste de la partition : squelette d'items, actions visuelles/mouvement, durees, cues, sequences, reprises | la base |
| `art_direction` | le document de direction artistique entier (copie profonde sous un nouvel id) | la base |

Les sources ne sont jamais ecrites. Ce module est le modele **pur** (aucune E/S) : la requete, les conflits types, la
provenance persistee, le choix des scenes et la fusion narrative d'une partition. Le service Core est
`jarvis/core/presentation_studio_composition.py`. Contrat : `docs/presentation-studio.md` > *Comparison and semantic
composition contract*.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from jarvis.domain.presentation_studio import PRESENTATION_ID
from jarvis.domain.presentation_studio_checks import (
    PresentationStudioError, PresentationStudioErrorCode, SCENE_ID, _check_id, _check_int, _check_title, _exact_keys, _fail, clip,
)
from jarvis.domain.presentation_studio_scene import StudioScene
from jarvis.domain.presentation_studio_score import Score, ScoreItem
from jarvis.domain.presentation_studio_variants import MAX_SOURCES, VARIANT_ID, check_rationale

#: Document de provenance `compositions/<variant_id>.json` (Slice 19), version 1. Hors `CURRENT_VERSIONS` : ce n'est pas un document
#: que les migrations du Studio rejouent, il est ecrit une fois avec sa variante et jamais reecrit.
SCHEMA_COMPOSITION = "jarvis.presentation_studio.composition"
COMPOSITION_SCHEMA_VERSION = 1
DIMENSIONS = ("scenes", "narrative", "motion", "art_direction")
#: Tranches de scenes d'une requete (`scenes: [{from, scene_ids?}, ...]`).
MAX_SEGMENTS = 4
MAX_SCENES = 64
#: Un refus nomme au plus ce nombre d'elements par conflit (les messages restent courts, `details.total` dit le reste).
MAX_LISTED = 12
#: La raison que l'utilisateur ecrit : le prefixe automatique de la composition tient dans le reste des 600 caracteres.
MAX_USER_RATIONALE = 400
ON_UNMAPPED = ("refuse", "keep_motion")
MAX_DETAIL_BYTES = 4096


class ConflictCode(StrEnum):
    """Codes **stables** d'un conflit de composition. Chacun porte `dimension`, un `message` et un `fix` actionnable."""

    TOO_MANY_SOURCES = "too_many_sources"
    SCENE_NOT_IN_SOURCE = "scene_not_in_source"
    DUPLICATE_SCENE = "duplicate_scene"
    TOO_MANY_SCENES = "too_many_scenes"
    SCENE_INCOMPATIBLE = "scene_incompatible"
    SOURCE_HAS_NO_SCORE = "source_has_no_score"
    SOURCE_HAS_NO_ART_DIRECTION = "source_has_no_art_direction"
    SOURCE_DOCUMENT_MISSING = "source_document_missing"
    SCORE_SCENE_MISSING = "score_scene_missing"
    SCORE_INCOMPATIBLE = "score_incompatible"
    NARRATIVE_UNMAPPED_ITEMS = "narrative_unmapped_items"
    NARRATIVE_ITEM_INCOMPATIBLE = "narrative_item_incompatible"
    SCORE_INVALID = "score_invalid"


@dataclass(frozen=True, slots=True)
class Conflict:
    """Un obstacle a la composition, **avant** toute ecriture : ce qui coince (`code`, `dimension`), pourquoi (`message`), comment
    s'en sortir (`fix`) et les identifiants utiles (`details`, bornes)."""

    code: ConflictCode
    dimension: str
    message: str
    fix: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "dimension": self.dimension, "message": clip(self.message, 300),
                "fix": clip(self.fix, 300), "details": dict(self.details)}


def listed(values: Iterable[str]) -> dict[str, Any]:
    """`{items: [<= MAX_LISTED], total}` : un detail borne, jamais une liste sans fin."""

    values = list(values)
    return {"items": values[:MAX_LISTED], "total": len(values)}


class CompositionRefused(PresentationStudioError):
    """La composition est refusee **avant toute ecriture** : `conflicts` (dicts `Conflict.to_dict()`) dit tout ce qui coince, pas
    seulement le premier. Statut 409, code `presentation_studio_composition_refused`."""

    def __init__(self, conflicts: Iterable[Conflict]) -> None:
        self.conflicts = [c.to_dict() for c in conflicts]
        first = self.conflicts[0]
        super().__init__(PresentationStudioErrorCode.COMPOSITION_REFUSED,
                         f"{len(self.conflicts)} conflict(s), first: {first['code']} on {first['dimension']}: {first['message']}")


# ------------------------------------------------------------------ requete

@dataclass(frozen=True, slots=True)
class SceneSegment:
    """Une tranche de scenes : `scene_ids` dans l'ordre voulu, ou `None` pour toutes celles de `variant_id`."""

    variant_id: str
    scene_ids: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"from": self.variant_id, **({} if self.scene_ids is None else {"scene_ids": list(self.scene_ids)})}


@dataclass(frozen=True, slots=True)
class CompositionRequest:
    title: str
    base: str
    rationale: str = ""
    #: `None` : la dimension vient de la base (heritee). Jamais une valeur par defaut cachee : la provenance le dit.
    scenes: tuple[SceneSegment, ...] | None = None
    narrative: str | None = None
    motion: str | None = None
    art_direction: str | None = None
    on_unmapped: str = "refuse"
    #: `variant_id -> revision` vue par l'appelant : une source qui a bouge refuse la composition (`stale_revision`).
    source_revisions: Mapping[str, int] = field(default_factory=dict)
    activate: bool = False
    actor: str = "user"
    expected_revision: int | None = None

    def segments(self) -> tuple[SceneSegment, ...]:
        return self.scenes if self.scenes is not None else (SceneSegment(self.base),)

    def source_of(self, dimension: str) -> str:
        return {"narrative": self.narrative, "motion": self.motion, "art_direction": self.art_direction}[dimension] or self.base

    def inherited(self, dimension: str) -> bool:
        return self.scenes is None if dimension == "scenes" else getattr(self, dimension) is None

    def sources(self) -> tuple[str, ...]:
        """Les variantes distinctes qui contribuent, la base d'abord (elle devient le parent), puis dans l'ordre des dimensions."""

        found: list[str] = [self.base]
        for dimension in DIMENSIONS:
            for variant_id in ([s.variant_id for s in self.segments()] if dimension == "scenes" else [self.source_of(dimension)]):
                if variant_id not in found:
                    found.append(variant_id)
        return tuple(found)


_REQUEST_KEYS = frozenset({"rationale", "scenes", "narrative", "motion", "art_direction", "on_unmapped", "source_revisions",
                           "activate", "actor", "expected_revision"})


def parse_composition(raw: object) -> CompositionRequest:
    """Corps d'une demande de composition -> `CompositionRequest`. Cle inconnue, id mal forme, tranche vide : refus type (400)
    avant toute lecture du disque. Le **fond** (existence, compatibilite) se juge dans le service, en conflits types."""

    data = _exact_keys(raw, "composition", {"title", "base"}, _REQUEST_KEYS)
    _check_title("title", data["title"])
    _check_id("base", data["base"], VARIANT_ID)
    rationale = check_rationale(data.get("rationale", ""))
    if len(rationale) > MAX_USER_RATIONALE:
        raise _fail(f"rationale exceeds {MAX_USER_RATIONALE} characters (the composition adds its own summary line)")
    segments: tuple[SceneSegment, ...] | None = None
    if data.get("scenes") is not None:
        segments = _parse_segments(data["scenes"])
    for name in ("narrative", "motion", "art_direction"):
        _check_id(name, data.get(name), VARIANT_ID, optional=True)
    on_unmapped = data.get("on_unmapped", "refuse")
    if on_unmapped not in ON_UNMAPPED:
        raise _fail(f"on_unmapped must be one of {', '.join(ON_UNMAPPED)}")
    revisions = data.get("source_revisions", {})
    if not isinstance(revisions, dict) or len(revisions) > MAX_SOURCES:
        raise _fail(f"source_revisions must be an object of at most {MAX_SOURCES} variant_id: revision pairs")
    for variant_id, revision in revisions.items():
        _check_id("source_revisions key", variant_id, VARIANT_ID)
        _check_int(f"source_revisions[{variant_id}]", revision, 1, 2**31 - 1)
    activate = data.get("activate", False)
    if type(activate) is not bool:
        raise _fail("activate must be true or false")
    actor = data.get("actor", "user")
    if actor not in ("user", "brain"):
        raise _fail("actor must be 'user' or 'brain'")
    expected = data.get("expected_revision")
    if expected is not None:
        _check_int("expected_revision", expected, 1, 2**31 - 1)
    return CompositionRequest(
        data["title"], data["base"], rationale, segments, data.get("narrative"), data.get("motion"),
        data.get("art_direction"), on_unmapped, dict(revisions), activate, actor, expected)


def _parse_segments(raw: object) -> tuple[SceneSegment, ...]:
    if isinstance(raw, str):
        _check_id("scenes", raw, VARIANT_ID)
        return (SceneSegment(raw),)
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_SEGMENTS:
        raise _fail(f"scenes must be a variant id or a list of 1..{MAX_SEGMENTS} segments {{from, scene_ids?}}")
    segments: list[SceneSegment] = []
    for index, item in enumerate(raw):
        data = _exact_keys(item, f"scenes[{index}]", {"from"}, frozenset({"scene_ids"}))
        _check_id(f"scenes[{index}].from", data["from"], VARIANT_ID)
        ids = data.get("scene_ids")
        if ids is not None:
            if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_SCENES:
                raise _fail(f"scenes[{index}].scene_ids must be a list of 1..{MAX_SCENES} scene ids (omit it for all scenes)")
            for scene_id in ids:
                _check_id(f"scenes[{index}].scene_ids[]", scene_id, SCENE_ID)
            if len(set(ids)) != len(ids):
                raise _fail(f"scenes[{index}].scene_ids names a scene twice")
            ids = tuple(ids)
        segments.append(SceneSegment(data["from"], ids))
    return tuple(segments)


# ------------------------------------------------------------------ scenes

def select_scenes(request: CompositionRequest, scenes_of: Mapping[str, tuple[StudioScene, ...]]
                  ) -> tuple[tuple[StudioScene, ...], list[Conflict]]:
    """Les scenes du resultat, dans l'ordre des tranches. Conflits : scene absente de sa source, meme scene prise deux fois,
    plus de `MAX_SCENES`. Pur ; `scenes_of` : `variant_id -> scenes` normalisees par la copie (pins confirmes)."""

    chosen: list[StudioScene] = []
    conflicts: list[Conflict] = []
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for segment in request.segments():
        available = {scene.scene_id: scene for scene in scenes_of[segment.variant_id]}
        wanted = segment.scene_ids if segment.scene_ids is not None else tuple(available)
        missing = [scene_id for scene_id in wanted if scene_id not in available]
        if missing:
            conflicts.append(Conflict(
                ConflictCode.SCENE_NOT_IN_SOURCE, "scenes", f"{len(missing)} scene(s) are not scenes of {segment.variant_id}",
                "Pick scene ids from the compare view of that variant, or change the source of the segment.",
                {"variant_id": segment.variant_id, "scene_ids": listed(missing)}))
            continue
        for scene_id in wanted:
            if scene_id in seen:
                duplicates.append(scene_id)
                continue
            seen[scene_id] = segment.variant_id
            chosen.append(available[scene_id])
    if duplicates:
        conflicts.append(Conflict(
            ConflictCode.DUPLICATE_SCENE, "scenes",
            f"{len(duplicates)} scene(s) are taken from more than one segment: a scene id appears once in a variant",
            "Take each equivalent scene from a single source (drop it from the other segment).",
            {"scene_ids": listed(duplicates)}))
    if len(chosen) > MAX_SCENES:
        conflicts.append(Conflict(
            ConflictCode.TOO_MANY_SCENES, "scenes", f"the result would hold {len(chosen)} scenes; the limit is {MAX_SCENES}",
            "Select fewer scenes.", {"count": len(chosen), "limit": MAX_SCENES}))
    return tuple(chosen), conflicts


# ------------------------------------------------------------------ narration

@dataclass(frozen=True, slots=True)
class NarrativeMerge:
    """Le resultat de l'emprunt de la narration : la partition (ou `None` si refusee) et ce qui s'est passe, pour la provenance."""

    score: Score | None
    matched_by_item_id: int = 0
    matched_by_scene_ordinal: int = 0
    kept_from_motion: tuple[str, ...] = ()
    dropped_source_items: int = 0
    conflicts: tuple[Conflict, ...] = ()

    def detail(self) -> dict[str, Any]:
        return {"fields": ["label", "text", "note"], "matched": {"item_id": self.matched_by_item_id,
                                                                  "scene_ordinal": self.matched_by_scene_ordinal},
                "kept_from_motion": list(self.kept_from_motion[:MAX_LISTED]), "kept_from_motion_total": len(self.kept_from_motion),
                "dropped_source_items": self.dropped_source_items}


def merge_narrative(motion: Score, narrative: Score, on_unmapped: str) -> NarrativeMerge:
    """La partition `motion` dont chaque item prend `label`, `text` et `note` de l'item **equivalent** de `narrative` : meme
    `item_id` (une branche garde les ids), a defaut le meme rang dans la meme scene. Un item sans equivalent est un conflit
    (`on_unmapped: refuse`) ou garde sa propre narration (`keep_motion`). Un item qui, ainsi narre, violerait la regle de
    parole de la partition (silence, hote de sequence verrouillee...) est un conflit nomme. Pur ; ne touche ni cues ni sequences."""

    source = {item.item_id: item for item in narrative.items}
    ordinal_source: dict[tuple[str, int], ScoreItem] = {}
    counters: dict[str, int] = defaultdict(int)
    for item in narrative.chain():
        ordinal_source[(item.scene_id, counters[item.scene_id])] = item
        counters[item.scene_id] += 1
    by_id = by_ordinal = 0
    unmapped: list[str] = []
    incompatible: list[tuple[str, str]] = []
    kept: list[str] = []
    used: set[str] = set()
    taken: dict[str, ScoreItem] = {}
    counters = defaultdict(int)
    for item in motion.chain():
        rank = counters[item.scene_id]
        counters[item.scene_id] += 1
        match = source.get(item.item_id)
        how = "id"
        if match is None:
            match = ordinal_source.get((item.scene_id, rank))
            how = "ordinal"
        if match is None or match.item_id in used:
            unmapped.append(item.item_id)
            if on_unmapped == "keep_motion":
                kept.append(item.item_id)
            continue
        try:
            taken[item.item_id] = replace(item, label=match.label, text=match.text, note=match.note)
        except PresentationStudioError as exc:
            incompatible.append((item.item_id, exc.message))
            continue
        used.add(match.item_id)
        by_id, by_ordinal = (by_id + 1, by_ordinal) if how == "id" else (by_id, by_ordinal + 1)
    conflicts: list[Conflict] = []
    if unmapped and on_unmapped == "refuse":
        conflicts.append(Conflict(
            ConflictCode.NARRATIVE_UNMAPPED_ITEMS, "narrative",
            f"{len(unmapped)} score item(s) of the motion source have no equivalent item in the narrative source",
            "Take narrative and motion from the same variant, or set on_unmapped to keep_motion to keep their own narration.",
            {"item_ids": listed(unmapped)}))
    if incompatible:
        conflicts.append(Conflict(
            ConflictCode.NARRATIVE_ITEM_INCOMPATIBLE, "narrative",
            f"{len(incompatible)} item(s) cannot carry the borrowed narration (speech rule of the score): {incompatible[0][1]}",
            "Take narrative and motion from the same variant, or choose a narrative source whose items speak like the motion source's.",
            {"item_ids": listed(i for i, _ in incompatible)}))
    if conflicts:
        return NarrativeMerge(None, by_id, by_ordinal, tuple(kept), 0, tuple(conflicts))
    items = tuple(taken.get(item.item_id, item) for item in motion.items)
    return NarrativeMerge(replace(motion, items=items), by_id, by_ordinal, tuple(kept),
                          len(narrative.items) - len(used))


def score_scene_conflicts(score: Score, scene_ids: Iterable[str], dimension: str, source_id: str) -> list[Conflict]:
    """Les scenes que la partition cite et que le resultat n'a pas : un conflit par partition, avec les scenes a ajouter."""

    present = set(scene_ids)
    wanted: dict[str, list[str]] = defaultdict(list)
    for item in score.items:
        if item.scene_id not in present:
            wanted[item.scene_id].append(item.item_id)
    if not wanted:
        return []
    return [Conflict(
        ConflictCode.SCORE_SCENE_MISSING, dimension,
        f"the score of {source_id} cites {len(wanted)} scene(s) that the composed scenes do not contain",
        "Take those scenes from the same variant (add a scenes segment), or take the score from a variant whose scenes you keep.",
        {"source_variant_id": source_id, "scene_ids": listed(wanted), "item_ids": listed(i for ids in wanted.values() for i in ids)})]


# ------------------------------------------------------------------ provenance persistee

MAX_PROVENANCE_WARNINGS = 8


@dataclass(frozen=True, slots=True)
class DimensionProvenance:
    """D'ou vient une dimension : les variantes sources (id, numero, **revision lue**, document emprunte), si elle vient de la base
    par defaut (`inherited`) et le detail propre a la dimension (ce qui a ete apparie, garde, ecarte)."""

    dimension: str
    inherited: bool
    sources: tuple[Mapping[str, Any], ...]
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "inherited": self.inherited, "sources": [dict(s) for s in self.sources],
                "detail": dict(self.detail)}


@dataclass(frozen=True, slots=True)
class CompositionProvenance:
    """`compositions/<variant_id>.json` : la provenance explicite, une entree par dimension (toujours les quatre, dans l'ordre)."""

    presentation_id: str
    variant_id: str
    base_variant_id: str
    created_at: str
    created_by: str
    dimensions: tuple[DimensionProvenance, ...]
    warnings: tuple[str, ...] = ()

    def to_document(self) -> dict[str, Any]:
        return {"schema": SCHEMA_COMPOSITION, "schema_version": COMPOSITION_SCHEMA_VERSION,
                "presentation_id": self.presentation_id, "variant_id": self.variant_id,
                "base_variant_id": self.base_variant_id, "created_at": self.created_at, "created_by": self.created_by,
                "dimensions": [d.to_dict() for d in self.dimensions], "warnings": list(self.warnings)}

    def sources(self) -> tuple[str, ...]:
        found: list[str] = [self.base_variant_id]
        for dimension in self.dimensions:
            for source in dimension.sources:
                if source["variant_id"] not in found:
                    found.append(source["variant_id"])
        return tuple(found)


def parse_provenance(raw: object) -> CompositionProvenance:
    """Document disque -> provenance. Cle inconnue ou dimension manquante : `invalid` (le service le rend `corrupt_document`)."""

    if isinstance(raw, dict) and (raw.get("schema"), raw.get("schema_version")) != (SCHEMA_COMPOSITION, COMPOSITION_SCHEMA_VERSION):
        raise _fail(f"composition document: unsupported schema {raw.get('schema')!r} version {raw.get('schema_version')!r}")
    data = _exact_keys(raw, "composition",
                       {"schema", "schema_version", "presentation_id", "variant_id", "base_variant_id", "created_at",
                        "created_by", "dimensions", "warnings"})
    _check_id("presentation_id", data["presentation_id"], PRESENTATION_ID)
    _check_id("variant_id", data["variant_id"], VARIANT_ID)
    _check_id("base_variant_id", data["base_variant_id"], VARIANT_ID)
    if data["created_by"] not in ("user", "brain"):
        raise _fail("created_by must be user or brain")
    rows = data["dimensions"]
    if not isinstance(rows, list) or [r.get("dimension") if isinstance(r, dict) else None for r in rows] != list(DIMENSIONS):
        raise _fail(f"dimensions must list {', '.join(DIMENSIONS)} in that order")
    dimensions: list[DimensionProvenance] = []
    for row in rows:
        entry = _exact_keys(row, "dimension", {"dimension", "inherited", "sources", "detail"})
        if type(entry["inherited"]) is not bool or not isinstance(entry["sources"], list) or not 1 <= len(entry["sources"]) <= MAX_SEGMENTS \
                or not isinstance(entry["detail"], dict):
            raise _fail(f"dimension {entry['dimension']}: malformed")
        for source in entry["sources"]:
            if not isinstance(source, dict):
                raise _fail("a provenance source must be an object")
            _check_id("sources[].variant_id", source.get("variant_id"), VARIANT_ID)
        dimensions.append(DimensionProvenance(entry["dimension"], entry["inherited"], tuple(entry["sources"]), entry["detail"]))
    warnings = data["warnings"]
    if not isinstance(warnings, list) or len(warnings) > MAX_PROVENANCE_WARNINGS or not all(isinstance(w, str) for w in warnings):
        raise _fail("warnings must be a short list of strings")
    return CompositionProvenance(data["presentation_id"], data["variant_id"], data["base_variant_id"], data["created_at"],
                                 data["created_by"], tuple(dimensions), tuple(warnings))


def summary_line(request: CompositionRequest, numbers: Mapping[str, int]) -> str:
    """La ligne que la raison de creation commence par : `composed from #1 (base); scenes #2; narrative #3; ...` (bornee)."""

    def label(variant_id: str) -> str:
        return f"#{numbers.get(variant_id, '?')}"

    parts = [f"composed on {label(request.base)}"]
    for dimension in DIMENSIONS:
        ids = [s.variant_id for s in request.segments()] if dimension == "scenes" else [request.source_of(dimension)]
        if not request.inherited(dimension):
            parts.append(f"{dimension} {'+'.join(dict.fromkeys(label(i) for i in ids))}")
    return "; ".join(parts) + "."


def compose_rationale(request: CompositionRequest, numbers: Mapping[str, int]) -> str:
    return check_rationale(f"{summary_line(request, numbers)} {request.rationale}".strip())


__all__ = [
    "COMPOSITION_SCHEMA_VERSION", "Conflict", "ConflictCode", "CompositionProvenance", "CompositionRefused", "CompositionRequest", "DIMENSIONS",
    "DimensionProvenance", "NarrativeMerge", "SceneSegment", "compose_rationale", "listed", "merge_narrative",
    "parse_composition", "parse_provenance", "score_scene_conflicts", "select_scenes", "summary_line",
]
