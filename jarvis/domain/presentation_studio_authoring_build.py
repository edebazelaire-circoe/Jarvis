"""Presentation Studio: from a validated draft to the documents of a whole Presentation (Slice 11).

Where `presentation_studio_authoring.py` parses what the brain submitted, this module **allocates every id** and assembles
the documents the Studio stores: the `Presentation` manifest, one `PresentationVariant` per direction, each with its own
`Score` and (when it has one) `ArtDirection`. Nothing here writes anything: Core (`core/presentation_studio_authoring.py`)
publishes the prefab bundles, calls `build_presentation` with the real pins, validates, then stores the result in ONE
atomic folder rename (`PresentationStudioStore.create`).

- **Same graph the Slice 16 branching builds.** A serious draft is variant 1. An exploratory draft is `n` candidates: candidate 1 is
  the root (number 1), the others are its children (parent and `sources` = the root, numbers 2..n). Every candidate shares the
  scenes and the score of the draft; it differs by its art direction and by the light `scenes_patch` it carries.
  Scene ids are the same in every variant (as in a Slice 16 branch), item and cue ids too; documents are separate files.
- **Candidates are drafts.** Their rationale starts with `DRAFT_RATIONALE_PREFIX`, `BuiltVariant.draft` is true.
- **`validate_built` is pure.** It judges the built documents against the prefab manifests the caller provides (scene controls
  and values, the score against the scenes, the score values against the manifests) and returns `Problem` rows; it never raises
  for a bad draft.

Pure but for the ids (`secrets`) and the clock the caller passes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
import json
from typing import Any

from jarvis.domain.prefab import PrefabManifest, PrefabRef, validate_value
from jarvis.domain.presentation_studio import (
    Presentation, PresentationVariant, PresentationView, dump_document, new_presentation_id, new_scene_id,
    new_variant_id, stamp,
)
from jarvis.domain.presentation_studio_art_direction import (
    ArtDirection, new_art_direction_document, require_art_direction,
)
from jarvis.domain.presentation_studio_authoring import (
    DRAFT_RATIONALE_PREFIX, AuthoringBrief, DraftAction, DraftItem, PresentationDraft, Problem,
)
from jarvis.domain.presentation_studio_authoring_remotion import THEME_PROP, apply_theme
from jarvis.domain.presentation_studio_engine import DEFAULT_ENGINE, Engine
from jarvis.domain.presentation_studio_checks import PresentationStudioError
from jarvis.domain.presentation_studio_scene import StudioScene, check_scene
from jarvis.domain.presentation_studio_score import (
    Presenter, Score, check_score, check_score_values, new_cue_id, new_score, new_score_item_id, parse_content,
)
from jarvis.domain.presentation_studio_variants import VariantIndexEntry


class BuildFailure(Exception):
    """The draft cannot be assembled into documents; `problems` say why, by logical key."""

    def __init__(self, problems: tuple[Problem, ...]) -> None:
        self.problems = problems
        super().__init__("; ".join(p.message for p in problems[:3]))


@dataclass(frozen=True, slots=True)
class BuiltVariant:
    variant: PresentationVariant
    score: Score
    art: ArtDirection | None
    #: An exploratory candidate: a draft until the user picks it.
    draft: bool
    #: Position in the draft's directions (1-based): the `candidate:<n>` of a report.
    position: int


@dataclass(frozen=True, slots=True)
class StoredDocuments:
    """The text of every file of the Presentation, as `PresentationStudioStore.create` takes them."""

    manifest: str
    variants: Mapping[str, str]
    scores: Mapping[str, str]
    art_directions: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class BuiltPresentation:
    presentation: Presentation
    variants: tuple[BuiltVariant, ...]
    #: Logical scene key -> allocated `pss_` id.
    scene_ids: Mapping[str, str]

    def view(self) -> PresentationView:
        return PresentationView(self.presentation, tuple(v.variant for v in self.variants))

    def key_of(self, scene_id: str) -> str:
        return next((key for key, value in self.scene_ids.items() if value == scene_id), scene_id)

    def documents(self) -> StoredDocuments:
        """Serialised (and size-checked: `limit_reached` when a document would exceed the cap)."""

        return StoredDocuments(
            dump_document(self.presentation.to_document()),
            {v.variant.variant_id: dump_document(v.variant.to_document()) for v in self.variants},
            {v.score.score_id: dump_document(v.score.to_document()) for v in self.variants},
            {v.art.art_direction_id: dump_document(v.art.to_document()) for v in self.variants if v.art is not None})

    def sizes(self) -> dict[str, Any]:
        """Bytes each document takes on disk (no cap applied): what the headroom rules read."""

        def size(document: Mapping[str, Any]) -> int:
            return len((json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8", errors="replace"))

        first = self.variants[0].variant
        return {"manifest": size(self.presentation.to_document()),
                "variant": max(size(v.variant.to_document()) for v in self.variants),
                "score": max(size(v.score.to_document()) for v in self.variants),
                "scene_payload": {self.key_of(s.scene_id): s.budget() for s in first.scenes}}


def _action_dict(action: DraftAction, own_scene_id: str, scene_ids: Mapping[str, str]) -> dict[str, Any]:
    wire = action.action.to_dict()
    wire["scene_id"] = scene_ids[action.scene] if action.scene is not None else own_scene_id
    return wire


def _score_content(draft: PresentationDraft, scene_ids: Mapping[str, str]) -> dict[str, Any]:
    ids = [new_score_item_id() for _ in draft.items]
    cues: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for index, item in enumerate(draft.items):
        scene_id = scene_ids[item.scene]
        cue_id = None
        if item.cue is not None:
            cue_id = new_cue_id()
            cues.append({"cue_id": cue_id, "label": item.cue.label, "predicate": item.cue.predicate.to_dict(),
                         "armable": item.cue.armable})
        items.append(_item_dict(item, ids[index], scene_id, cue_id, ids[index + 1] if index + 1 < len(ids) else None,
                                scene_ids))
    return parse_content({"start_item_id": ids[0] if ids else None, "items": items, "cues": cues, "sequences": [],
                          "recovery_points": []})


def _item_dict(item: DraftItem, item_id: str, scene_id: str, cue_id: str | None, next_id: str | None,
               scene_ids: Mapping[str, str]) -> dict[str, Any]:
    silent = item.presenter is Presenter.NONE
    return {
        "item_id": item_id, "scene_id": scene_id, "presenter": item.presenter.value,
        "kind": "silence" if silent else "speech", "label": item.label, "text": item.text, "note": item.note,
        "cue_id": cue_id, "visual": [_action_dict(a, scene_id, scene_ids) for a in item.visual],
        "motion": [_action_dict(a, scene_id, scene_ids) for a in item.motion],
        "target_duration_ms": item.target_duration_ms, "timing": "soft", "interruption": item.interruption.value,
        "recovery": "continue_item", "recovery_point_id": None, "next_item_id": next_id, "loop": None}


def _themed(draft: PresentationDraft, key: str | None) -> bool:
    """The scene is shown by a Remotion source of this draft that declares the reserved `theme` prop: its art direction travels as data."""

    bundle = next((b for b in draft.bundles if b.key == key), None) if key is not None else None
    return bundle is not None and bundle.is_remotion and THEME_PROP in bundle.bundle.manifest.raw.get("inputs", {}).get("props", {}).get("properties", {})


def _scenes_for(draft: PresentationDraft, scene_ids: Mapping[str, str], pins: Mapping[str, PrefabRef],
                patch: Mapping[str, Mapping[str, Any]], where: str, problems: list[Problem], profile: Any = None) -> tuple[StudioScene, ...]:
    out: list[StudioScene] = []
    for scene in draft.scenes:
        pin = pins[scene.bundle_key] if scene.bundle_key is not None else scene.scene.prefab
        change = patch.get(scene.key, {})
        try:
            merged = {name: {**getattr(scene.scene, name), **change[name]} for name in ("props", "data") if name in change}
            if profile is not None and _themed(draft, scene.bundle_key):
                # Slice 15: the art direction of THIS variant is the scene's `theme` (under what the scene or the candidate sets).
                merged["props"] = apply_theme(merged.get("props", scene.scene.props), profile)
            out.append(replace(scene.scene, scene_id=scene_ids[scene.key], prefab=pin,
                               **({"title": change["title"]} if "title" in change else {}), **merged))
        except PresentationStudioError as exc:
            problems.append(Problem("scene_incompatible", f"{where}scene:{scene.key}", exc.message))
    return tuple(out)


def build_presentation(brief: AuthoringBrief, draft: PresentationDraft, pins: Mapping[str, PrefabRef], now: datetime,
                       actor: str, engine: Engine = DEFAULT_ENGINE) -> BuiltPresentation:
    """Allocates the ids and assembles the documents. `pins` maps each bundle key to the pin the scenes will carry (the real
    published pin when Core writes, the candidate's own provisional pin when it only checks). Raises `BuildFailure`.

    `engine` (Remotion Slice 15): the engine of the Presentation, `remotion` unless a caller says otherwise (an agent draft is Remotion,
    always: Core's authoring refuses an HTML source or pin before it gets here)."""

    problems: list[Problem] = []
    pid = new_presentation_id()
    at = stamp(now)
    scene_ids = {scene.key: new_scene_id() for scene in draft.scenes}
    content = _score_content(draft, scene_ids)
    exploratory = not brief.workflow.serious
    root_id = new_variant_id()
    built: list[BuiltVariant] = []
    entries: list[VariantIndexEntry] = []
    count = len(draft.directions)
    for position, direction in enumerate(draft.directions, start=1):
        vid = root_id if position == 1 else new_variant_id()
        where = f"candidate:{position}/" if exploratory else ""
        scenes = _scenes_for(draft, scene_ids, pins, direction.patch, where, problems, direction.profile)
        if len(scenes) != len(draft.scenes):
            continue  # reported above; nothing more can be assembled for this direction
        art = new_art_direction_document(pid, vid, direction.profile, now) if direction.profile is not None else None
        score = new_score(pid, vid, content, now)
        variant = PresentationVariant(pid, vid, position, direction.title, None if position == 1 else root_id, scenes,
                                      art.art_direction_id if art else None, score.score_id, 1, at, at)
        rationale = f"{DRAFT_RATIONALE_PREFIX} {position}/{count}: {direction.rationale}" if exploratory else direction.rationale
        entries.append(VariantIndexEntry(vid, position, rationale, actor, () if position == 1 else (root_id,)))
        built.append(BuiltVariant(variant, score, art, exploratory, position))
    if problems:
        raise BuildFailure(tuple(problems))
    presentation = Presentation(pid, brief.title, root_id, count, tuple(entries), brief.resources, 1, at, at, engine=engine)
    result = BuiltPresentation(presentation, tuple(built), scene_ids)
    try:
        result.view()  # the index and the variants say the same thing (check_consistency, the graph invariant)
    except PresentationStudioError as exc:
        raise BuildFailure((Problem("document_invalid", "draft", exc.message),)) from exc
    return result


def provisional_pins(draft: PresentationDraft) -> dict[str, PrefabRef]:
    """Each bundle key -> the candidate's own `(id, version)`: enough to check a draft that nothing has published yet."""

    return {b.key: PrefabRef(b.bundle.manifest.prefab_id, b.bundle.manifest.version) for b in draft.bundles}


def require_art_directions(built: BuiltPresentation, *, serious: bool) -> None:
    """The Slice 09 rule, on the documents about to be stored (carry-forward of its QA, I1): a serious or generated variant
    resolves a DA. Raises `art_direction_required`; the gate has already said so by rule code, this is the invariant behind it."""

    arts = {v.art.art_direction_id: v.art for v in built.variants if v.art is not None}

    class _Lookup:
        def find(self, presentation_id: str, art_direction_id: str) -> ArtDirection | None:
            return arts.get(art_direction_id)

    for item in built.variants:
        require_art_direction(item.variant, _Lookup(), serious)


def validate_built(built: BuiltPresentation, manifests: Mapping[tuple[str, int], PrefabManifest]) -> list[Problem]:
    """Scene controls and values against their manifests, the score against the scenes and the manifests. Rows are
    `scene_incompatible` / `score_incompatible` / `pin_unknown` problems named by logical key; empty means compatible."""

    problems: list[Problem] = []
    for item in built.variants:
        prefix = f"candidate:{item.position}/" if item.draft else ""
        by_scene: dict[str, PrefabManifest] = {}
        for scene in item.variant.scenes:
            key = built.key_of(scene.scene_id)
            manifest = manifests.get((scene.prefab.prefab_id, scene.prefab.version))
            if manifest is None:
                problems.append(Problem("pin_unknown", f"{prefix}scene:{key}",
                                        f"{scene.prefab.prefab_id}@{scene.prefab.version} has no manifest"))
                continue
            by_scene[scene.scene_id] = manifest
            found = list(check_scene(scene, manifest))
            for root, schema, values in (("props", manifest.props, scene.props), ("data", manifest.data, scene.data)):
                _, errors = validate_value(schema, values, root)
                found.extend(errors[:3])
            problems.extend(Problem("scene_incompatible", f"{prefix}scene:{key}", text) for text in found[:4])
        if len(by_scene) != len(item.variant.scenes):
            continue  # a score cannot be judged against a scene without manifest
        for text in check_score(item.score, item.variant.scenes)[:4]:
            problems.append(Problem("score_incompatible", f"{prefix}score", _keyed(text, built)))
        for text in check_score_values(item.score, item.variant.scenes, by_scene)[:4]:
            problems.append(Problem("score_incompatible", f"{prefix}score", _keyed(text, built)))
    return problems[:40]


def _keyed(message: str, built: BuiltPresentation) -> str:
    """The domain messages name ids; the brain knows only its keys. Rewrites `pss_...` to `scene <key>`."""

    for key, scene_id in built.scene_ids.items():
        message = message.replace(scene_id, f"{key!r}")
    for position, item in enumerate(built.variants[0].score.items, start=1):
        message = message.replace(f"item {item.item_id}", f"item:{position}").replace(item.item_id, f"item:{position}")
    return message
