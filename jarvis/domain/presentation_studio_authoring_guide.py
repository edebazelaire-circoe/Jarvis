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

from jarvis.domain.presentation_studio_authoring import _BRIEF_OPTIONAL, MAX_DRAFT_SCENES, Speech, Workflow

#: Where the draft's own key names are fixed by the parser (`parse_draft`): required, then optional.
DRAFT_KEYS = {"required": ["scenes", "score"], "optional": ["prefabs", "art_direction", "candidates"]}


def _bundle() -> dict[str, Any]:
    """A complete prefab candidate: one titled slide (headline, body text, accent colour). Motion respects `prefers-reduced-motion`."""

    return {
        "manifest": {
            "schema": "jarvis.prefab", "schema_version": 1, "id": "presentation-studio.slide", "version": 1, "title": "Diapositive",
            "description": "Une diapositive: un titre, un texte, une couleur d'accent.", "family": "window", "tags": ["slide"],
            "aliases": [], "scene": {"kind": "window", "default_size": {"w": 64, "h": 40}},
            "inputs": {
                "props": {"type": "object", "properties": {
                    "headline": {"type": "string", "max_length": 80, "default": "Titre"},
                    "accent": {"type": "color", "default": "#6ee7ff"},
                    "stagger_ms": {"type": "integer", "min": 0, "max": 400, "default": 80}}},
                "data": {"type": "object", "required": ["body"], "properties": {"body": {"type": "text", "max_length": 600}}}},
            "sample": {"props": {}, "data": {"body": "Exemple"}},
            "files": {"template": "template.html", "style": "style.css", "behavior": "behavior.js"}},
        "template": '<section class="jv-panel"><h2 data-jv-text="props.headline"></h2><p data-jv-text="data.body"></p></section>\n',
        "style": (".jv-panel h2 { color: var(--jv-accent); transition: opacity 0.3s; }\n"
                  "@media (prefers-reduced-motion: reduce) { .jv-panel h2 { transition: none; } }\n"),
        "behavior": "jarvis.on('init', function () {});\n"}


def example() -> dict[str, Any]:
    """A one-scene `one_shot` submission that passes the full gate: a report to display now, Jarvis reading one line."""

    body = "Le dossier compte quarante-deux fichiers : trente documents, dix tableurs et deux presentations."
    brief = {"title": "Contenu du dossier", "workflow": "one_shot", "purpose": "Afficher le contenu du dossier", "audience": "Moi",
             "duration_target_s": 20, "language": "fr", "speech": "jarvis"}
    draft = {
        "prefabs": [{"key": "slide", "candidate": _bundle()}],
        "scenes": [{
            "key": "rapport", "role": "single", "title": "Contenu du dossier", "prefab": {"bundle": "slide"},
            "props": {"headline": "Contenu du dossier"}, "data": {"body": body},
            "controls": [
                {"control_id": "headline", "path": "props.headline", "label": "Titre de la diapositive", "group": "content",
                 "meaning": "Le titre affiche en haut", "bounds": {"max_length": 60}},
                {"control_id": "accent", "path": "props.accent", "label": "Couleur d'accent", "group": "visual",
                 "meaning": "Couleur du titre"}],
            "anchors": [{"anchor_id": "detail", "label": "Detail", "control_id": "accent"}]}],
        "score": {"items": [{"scene": "rapport", "presenter": "jarvis", "target_duration_ms": 20_000,
                             "text": "Voici le contenu du dossier : quarante-deux fichiers, surtout des documents."}]},
        "art_direction": {"mode": "fallback"}}
    return {"brief": brief, "draft": draft}


def draft_guide() -> dict[str, Any]:
    """What `presentation_inspect` target `draft_guide` returns. A fresh copy each time: the caller may keep it."""

    return {
        "note": ("FORME seulement: l'exemple est valide mais n'est pas ton contenu. Garde les noms de cles exacts, remplace tout le "
                 "texte, les titres, les durees et la direction artistique par les tiens. Aucune autre cle n'est acceptee."),
        "brief": {"required": ["title", "workflow"], "optional": sorted(_BRIEF_OPTIONAL),
                  "workflow": [w.value for w in Workflow], "speech": [s.value for s in Speech],
                  "types": {"duration_target_s": "secondes (entier)", "tone": "liste de mots", "must_cover": "liste de lignes",
                            "literal_terms": "liste de mots", "resources": "liste de {kind, locator, title}", "language": "fr, en, fr-CA",
                            "max_scenes": f"1..{MAX_DRAFT_SCENES}", "strict_content": "booleen (exploratory seulement)"}},
        "draft": {**DRAFT_KEYS,
                  "prefabs": "[{key, candidate: {manifest, template, style, behavior}}] ; id sous presentation-studio. ; ou epingle un prefab existant",
                  "scenes": "[{key, role: opening|body|closing|single, title, prefab: {bundle: <key>} ou {id, version}, props, data, controls, anchors}]",
                  "score.items": "[{scene: <key>, presenter: jarvis|user|none, text (dit tel quel) OU note (intention), target_duration_ms, "
                                 "cue?: {label, armable, phrases}, visual?, motion?}]",
                  "art_direction": "{mode: fallback} | {mode: signals, signals: {sources, colors, fonts, radii}} | {mode: profile, profile}",
                  "candidates": "exploratory seulement: [{title, rationale, art_direction?, scenes_patch?}] (2 a 6)"},
        "example": copy.deepcopy(example())}


__all__ = ["DRAFT_KEYS", "draft_guide", "example"]
