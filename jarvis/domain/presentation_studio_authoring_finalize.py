"""Presentation Studio: re-gating a stored variant as `directed` (handoff jarvis-interactive-presentation-studio, Slice 11 rework).

An exploratory request delivers candidates under the lighter gate. A candidate becomes the deck the user presents only after
`finalize`: the stored variant, its score and its art direction are turned back into a `PresentationDraft` and judged by the SAME gate
as a `directed` draft. This module is the pure conversion; `PresentationStudioAuthoring.finalize` loads the documents and decides.

What a stored variant does not keep, and what the gate therefore cannot judge, is said in the report (`not_judged`) rather than
guessed: the brief (duration target, must-cover, language, who speaks), the scene roles (inferred from position: first opening, last
closing, the others body; one scene is `single`), `long_form` (the long-form word cap applies: nothing says a scene is not a document)
and `cut` (every cut is taken as declared, so `transition_missing` is not re-judged).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from jarvis.domain.prefab import PrefabBundle
from jarvis.domain.presentation_studio import Presentation, PresentationVariant
from jarvis.domain.presentation_studio_art_direction import ArtDirection
from jarvis.domain.presentation_studio_authoring import (
    AuthoringBrief, DraftAction, DraftBundle, DraftCue, DraftDirection, DraftItem, DraftScene, PresentationDraft, SceneRole, Speech,
    Workflow,
)
from jarvis.domain.presentation_studio_authoring_build import BuiltPresentation, BuiltVariant
from jarvis.domain.presentation_studio_score import Presenter, Score

#: Rules that need the brief or an attestation a stored variant does not keep: reported as not judged, never guessed.
NOT_JUDGED = frozenset({"presenter_mismatch", "duration_off", "duration_missing", "must_cover_missing", "language_mismatch",
                        "transition_missing", "cues_sparse", "notes_missing", "candidates_count", "candidates_not_divergent"})


def infer_speech(score: Score) -> Speech:
    presenters = {item.presenter for item in score.items}
    if Presenter.JARVIS in presenters:
        return Speech.JARVIS
    return Speech.USER if Presenter.USER in presenters else Speech.NONE


def draft_from_stored(presentation: Presentation, variant: PresentationVariant, score: Score, art: ArtDirection | None,
                      bundles: Sequence[tuple[str, dict, PrefabBundle]] = ()) -> tuple[PresentationDraft, AuthoringBrief, BuiltPresentation]:
    """`(draft, brief, built)` for the gate. `bundles`: `(key, candidate, parsed)` of the Studio-namespace sources the scenes pin."""

    count = len(variant.scenes)
    scenes = tuple(
        DraftScene(scene.scene_id,
                   SceneRole.SINGLE if count == 1 else SceneRole.OPENING if n == 0 else SceneRole.CLOSING if n == count - 1 else SceneRole.BODY,
                   scene, None, long_form=True, cut=True)
        for n, scene in enumerate(variant.scenes))
    cues = {cue.cue_id: cue for cue in score.cues}
    items = []
    for number, item in enumerate(score.chain(), start=1):
        cue = cues.get(item.cue_id) if item.cue_id else None
        items.append(DraftItem(
            item.scene_id, item.presenter, item.text, item.note, item.label,
            DraftCue(cue.label, cue.predicate, cue.armable) if cue is not None else None,
            tuple(DraftAction(a, a.scene_id) for a in item.visual), tuple(DraftAction(a, a.scene_id) for a in item.motion),
            item.target_duration_ms, item.interruption, number))
    direction = DraftDirection(variant.title, "stored variant", art.profile if art is not None else None)
    draft = PresentationDraft(tuple(DraftBundle(key, candidate, parsed) for key, candidate, parsed in bundles), scenes, tuple(items),
                              (direction,))
    brief = AuthoringBrief(presentation.title, Workflow.DIRECTED, speech=infer_speech(score), resources=presentation.resources)
    built = BuiltPresentation(presentation, (BuiltVariant(variant, score, art, False, 1),), {s.scene_id: s.scene_id for s in variant.scenes})
    return draft, brief, built


def manifests_by_scene(variant: PresentationVariant, manifests: Mapping[tuple[str, int], object]) -> dict[str, object]:
    return {scene.scene_id: manifests[(scene.prefab.prefab_id, scene.prefab.version)] for scene in variant.scenes
            if (scene.prefab.prefab_id, scene.prefab.version) in manifests}
