"""The shape of a submission, for the model that has to write one (jarvis-interactive-presentation-studio, Slice 22 release gate).

The first real-model run of the authoring planner (`slices/22-end-to-end-hardening/evidence/authoring-real-traces.md`) found that the brain,
given only "AuthoringBrief" and "PresentationDraft" as argument descriptions, guessed key names (`flow`, `objective`) and was refused three
times by a gate that, by design, never echoes the author's keys. The fix is not a looser gate: it is to give the model the vocabulary. This
module is that vocabulary, read on demand (`presentation_inspect` target `draft_guide`) so the twelve-tool surface does not grow:

- the EXACT brief keys, read from the parser's own constants (they cannot drift from `parse_brief`);
- the shape of the draft (prefab bundle, scene, score item, cue, art direction), as a short table;
- ONE complete, valid, one-scene example of the form. `tests/unit/test_presentation_studio_authoring_guide.py` runs it through the real gate
  and the real assembly, so an example that stops being valid fails the build.

The example is a SHAPE to adapt, never content to reuse: its text says so and the model replaces all of it.
"""

from __future__ import annotations

import copy
from typing import Any

from jarvis.domain.presentation_studio_art_direction_authoring import SeedContext, diverge, generate_fallback_profile
from jarvis.domain.presentation_studio_authoring import _BRIEF_OPTIONAL, MAX_DRAFT_SCENES, Speech, Workflow

#: Where the draft's own key names are fixed by the parser (`parse_draft`): required, then optional.
DRAFT_KEYS = {"required": ["scenes", "score"], "optional": ["prefabs", "art_direction", "candidates"]}


SLIDE_TSX = """import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";

// `props.theme` is the art direction of the variant (Core fills it): read the colours, fonts and tempo from it, never hard-code them.
// `props.headline` and `props.data.body` are the editable content (controls edit them): never write the sentences in the source.
export default function Scene(props: {headline: string; data: {body: string}; theme: Record<string, any>}) {
  const frame = useCurrentFrame();
  const theme = props.theme;
  const enter = interpolate(frame, [0, 18], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: 96, justifyContent: "center"}}>
      <h1 style={{color: theme.accent, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: 72 * theme.scale,
                  opacity: enter, transform: `translateY(${(1 - enter) * 24}px)`}}>{props.headline}</h1>
      <p style={{color: theme.body, fontSize: 36 * theme.scale, opacity: enter}}>{props.data.body}</p>
    </AbsoluteFill>
  );
}
"""


def _bundle() -> dict[str, Any]:
    """The generator object of one Remotion source (Slice 15): a titled slide, headline and body as props, the art direction as `theme`.
    Core builds the manifest, the id, the catalog block and the `theme` prop; the brain writes the TSX and the content schema."""

    return {"remotion": {
        "title": "Diapositive", "description": "Une diapositive: un titre et un texte, aux couleurs de la direction artistique.",
        "composition": {"width": 1280, "height": 720, "fps": 30, "duration_in_frames": 300},
        "files": {"src/Scene.tsx": SLIDE_TSX},
        "props": {"type": "object", "properties": {"headline": {"type": "string", "max_length": 80, "default": "Titre"}}},
        "data": {"type": "object", "required": ["body"], "properties": {"body": {"type": "text", "max_length": 600}}},
        "sample": {"props": {"headline": "Titre"}, "data": {"body": "Exemple"}}}}


def example() -> dict[str, Any]:
    """A one-scene `one_shot` submission that passes the full gate: a report to display now, Jarvis reading one line."""

    body = "Le dossier compte quarante-deux fichiers : trente documents, dix tableurs et deux presentations."
    brief = {"title": "Contenu du dossier", "workflow": "one_shot", "purpose": "Afficher le contenu du dossier", "audience": "Moi",
             "duration_target_s": 20, "language": "fr", "speech": "jarvis"}
    draft = {
        "prefabs": [{"key": "slide", **_bundle()}],
        "scenes": [{
            "key": "rapport", "role": "single", "title": "Contenu du dossier", "prefab": {"bundle": "slide"},
            "props": {"headline": "Contenu du dossier"}, "data": {"body": body},
            "controls": [
                {"control_id": "headline", "path": "props.headline", "label": "Titre de la diapositive", "group": "content",
                 "meaning": "Le titre affiche en haut", "bounds": {"max_length": 60}},
                {"control_id": "accent", "path": "props.theme.accent", "label": "Couleur d'accent", "group": "visual",
                 "meaning": "Couleur du titre"}],
            "anchors": [{"anchor_id": "detail", "label": "Detail", "control_id": "accent", "at_ms": 3000}]}],
        "score": {"items": [{"scene": "rapport", "presenter": "jarvis", "target_duration_ms": 20_000,
                             "text": "Voici le contenu du dossier : quarante-deux fichiers, surtout des documents."}]},
        "art_direction": {"mode": "fallback"}}
    return {"brief": brief, "draft": draft}


#: How many ready-made divergent directions the exploratory guide hands over (the exploratory maximum).
EXPLORATORY_DIRECTIONS = 6


def exploratory_example() -> dict[str, Any]:
    """A three-scene `exploratory` submission with six candidates whose art directions are computed by Slice 09's `diverge`: divergent by
    construction, so the model never has to invent a full art-direction profile (the real-model run could not: wrong shapes, then four
    near-identical directions). The model keeps the first N (2..6), writes its own title and rationale for each, and its own scenes."""

    pair = example()
    bundle = pair["draft"]["prefabs"][0]
    scenes = []
    for key, role, title, body in (("idee", "opening", "Une idee simple", "Une presentation qui tient en trois temps."),
                                   ("changement", "body", "Ce qui change", "Le visuel porte le message, le texte reste court."),
                                   ("suite", "closing", "Et maintenant", "Choisissez la direction qui vous ressemble.")):
        scene = copy.deepcopy(pair["draft"]["scenes"][0])
        scene.update(key=key, role=role, title=title, props={"headline": title}, data={"body": body})
        scenes.append(scene)
    items = [{"scene": s["key"], "presenter": "jarvis", "target_duration_ms": 15_000, "text": f"{s['title']} : {s['data']['body']}"}
             for s in scenes]
    base = generate_fallback_profile(SeedContext("Exemple", "", "", ()))
    candidates = [{"title": f"Direction {n}", "rationale": "Ce qui la distingue, en une phrase.",
                   "art_direction": {"mode": "profile", "profile": profile.to_dict()}}
                  for n, profile in enumerate(diverge(base, EXPLORATORY_DIRECTIONS), 1)]
    candidates[1]["scenes_patch"] = {"idee": {"title": "Une autre accroche", "props": {"headline": "Une autre accroche"}}}
    brief = {"title": "Directions visuelles", "workflow": "exploratory", "purpose": "Choisir une direction", "audience": "Moi",
             "language": "fr", "speech": "jarvis"}
    return {"brief": brief, "draft": {"prefabs": [bundle], "scenes": scenes, "score": {"items": items}, "candidates": candidates}}


def draft_guide(kind: str | None = None) -> dict[str, Any]:
    """What `presentation_inspect` target `draft_guide` returns (`kind: "exploratory"`: the exploratory example). A fresh copy each time."""

    if kind == "exploratory":
        return {"note": ("FORME: 6 directions deja divergentes (profils calcules). Garde-en 2 a 6 dans l'ordre, ne les rapproche pas "
                         "(sinon candidates_not_divergent), ecris le titre et la raison de chacune, et tes propres scenes et textes. "
                         "N'invente pas de profil de direction artistique: copie ceux-ci."),
                "example": copy.deepcopy(exploratory_example())}
    return {
        "note": ("FORME seulement: l'exemple est valide mais n'est pas ton contenu. Garde les noms de cles exacts, remplace tout le "
                 "texte, les titres, les durees et la direction artistique par les tiens. Aucune autre cle n'est acceptee."),
        "brief": {"required": ["title", "workflow"], "optional": sorted(_BRIEF_OPTIONAL),
                  "workflow": [w.value for w in Workflow], "speech": [s.value for s in Speech],
                  "types": {"duration_target_s": "secondes (entier)", "tone": "liste de mots", "must_cover": "liste de lignes",
                            "literal_terms": "liste de mots", "resources": "liste de {kind, locator, title}", "language": "fr, en, fr-CA",
                            "max_scenes": f"1..{MAX_DRAFT_SCENES}", "strict_content": "booleen (exploratory seulement)"}},
        "draft": {**DRAFT_KEYS,
                  "prefabs": "[{key, remotion: {title, files: {'src/Scene.tsx': <TSX>, ...}, props: <schema>, data?: <schema>, sample?, composition?: {width, height, fps, duration_in_frames}, assets?, live_refs?, inspiration?}}] ; une scene Remotion lit props.theme (la DA) ; ou epingle une source Remotion existante",
                  "scenes": "[{key, role: opening|body|closing|single, title, prefab: {bundle: <key>} ou {id, version}, props, data, controls, anchors: [{anchor_id, label, control_id?, at_ms? (scene Remotion : ms depuis le debut de la composition)}]}]",
                  "score.items": "[{scene: <key>, presenter: jarvis|user|none, text (dit tel quel) OU note (intention), target_duration_ms, "
                                 "cue?: {label, armable, phrases}, visual?, motion?}]",
                  "art_direction": "{mode: fallback} | {mode: signals, signals: {sources, colors, fonts, radii}} | {mode: profile, profile}",
                  "candidates": "exploratory seulement: [{title, rationale, art_direction?, scenes_patch?}] (2 a 6)"},
        "example": copy.deepcopy(example())}


__all__ = ["DRAFT_KEYS", "EXPLORATORY_DIRECTIONS", "draft_guide", "example", "exploratory_example"]
