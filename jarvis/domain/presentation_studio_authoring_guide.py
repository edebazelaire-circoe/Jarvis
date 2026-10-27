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
from jarvis.domain.presentation_studio_authoring_remotion import NATIVE_DEFAULT_COMPOSITION

#: Where the draft's own key names are fixed by the parser (`parse_draft`): required, then optional.
DRAFT_KEYS = {"required": ["scenes", "score"], "optional": ["prefabs", "art_direction", "candidates"]}


SLIDE_TSX = """import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";
import {enterStyle, progress, size} from "./jarvis-kit";

// `props.theme` is the art direction of the variant (Core fills it): read colours, fonts and motion from it, never hard-code them.
// `./jarvis-kit` (added by Core) turns the direction's motion into frames: progress() is 0..1, enterStyle() is its transition.
// `props.headline` and `props.data.body` are the editable content (controls edit them): never write the sentences in the source.
export default function Scene(props: {headline: string; data: {body: string}; theme: Record<string, any>}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = props.theme;
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: 96, justifyContent: "center", gap: theme.gap}}>
      <h1 style={{color: theme.accent, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(72, theme),
                  margin: 0, ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h1>
      <p style={{color: theme.body, fontSize: size(36, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, 1), theme)}}>{props.data.body}</p>
    </AbsoluteFill>
  );
}
"""

#: Layouts for the other kinds of scene of a storyboard (same theme, same kit), each a complete generator object the model copies and adapts.
FIGURE_TSX = """import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";
import {enterStyle, progress, size} from "./jarvis-kit";

export default function Scene(props: {headline: string; data: {figure: string; caption: string}; theme: Record<string, any>}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = props.theme;
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: 96, justifyContent: "center", alignItems: "center", textAlign: "center", gap: theme.gap}}>
      <h2 style={{color: theme.muted, fontFamily: theme.font_heading, fontWeight: theme.body_weight, fontSize: size(40, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h2>
      <div style={{color: theme.accent, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(220, theme), lineHeight: 1, ...enterStyle(progress(frame, fps, theme, 1), theme)}}>{props.data.figure}</div>
      <p style={{color: theme.body, fontSize: size(34, theme), margin: 0, maxWidth: 900, ...enterStyle(progress(frame, fps, theme, 2), theme)}}>{props.data.caption}</p>
    </AbsoluteFill>
  );
}
"""

LIST_TSX = """import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";
import {enterStyle, progress, size} from "./jarvis-kit";

export default function Scene(props: {headline: string; data: {items: string[]}; theme: Record<string, any>}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = props.theme;
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: 96, justifyContent: "center", gap: theme.gap}}>
      <h1 style={{color: theme.accent, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(64, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h1>
      <ul style={{listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: theme.gap}}>
        {props.data.items.map((item, index) => (
          <li key={index} style={{color: theme.body, fontSize: size(38, theme), borderLeft: `6px solid ${theme.accent}`, paddingLeft: 24, borderRadius: theme.radius, ...enterStyle(progress(frame, fps, theme, index + 1), theme)}}>{item}</li>
        ))}
      </ul>
    </AbsoluteFill>
  );
}
"""

COVER_TSX = """import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";
import {enterStyle, progress, size} from "./jarvis-kit";

export default function Scene(props: {headline: string; data: {subtitle: string}; theme: Record<string, any>}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = props.theme;
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: 96, justifyContent: "center", gap: theme.gap}}>
      <div style={{width: 120, height: 8, background: theme.accent, borderRadius: theme.radius, ...enterStyle(progress(frame, fps, theme, 0), theme)}} />
      <h1 style={{color: theme.text, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(96, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, 1), theme)}}>{props.headline}</h1>
      <p style={{color: theme.muted, fontSize: size(40, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, 2), theme)}}>{props.data.subtitle}</p>
    </AbsoluteFill>
  );
}
"""


def layouts() -> dict[str, Any]:
    """Generator objects for the other kinds of scene (the storyboard picks one per scene): `cover`, `figure`, `list`. Each reads the theme and the
    kit, keeps its sentences in `props`/`data`, and passes the gate and the compiler (tests run them through both)."""

    def spec(title: str, tsx: str, data: dict[str, Any], use: str) -> dict[str, Any]:
        return {"use": use, "remotion": {
            "title": title, "composition": {"width": 1280, "height": 720, "fps": 30, "duration_in_frames": 300}, "files": {"src/Scene.tsx": tsx},
            "props": {"type": "object", "properties": {"headline": {"type": "string", "max_length": 80, "default": "Titre"}}},
            "data": data}}

    return {
        "cover": spec("Couverture", COVER_TSX, {"type": "object", "required": ["subtitle"], "properties": {"subtitle": {"type": "string", "max_length": 120}}},
                      "ouverture ou clôture : un grand titre et une ligne"),
        "figure": spec("Chiffre clé", FIGURE_TSX, {"type": "object", "required": ["figure", "caption"], "properties": {
            "figure": {"type": "string", "max_length": 16}, "caption": {"type": "text", "max_length": 200}}}, "un chiffre à retenir, en grand"),
        "list": spec("Liste", LIST_TSX, {"type": "object", "required": ["items"], "properties": {
            "items": {"type": "array", "max_items": 6, "items": {"type": "string", "max_length": 90}}}}, "trois à six points qui apparaissent un à un")}


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
             "duration_target_s": 20, "tone": ["sobre", "direct"], "language": "fr", "speech": "jarvis"}
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
             "tone": ["inspire"], "language": "fr", "speech": "jarvis"}
    return {"brief": brief, "draft": {"prefabs": [bundle], "scenes": scenes, "score": {"items": items}, "candidates": candidates}}


#: Slice 13 (native-studio-playback-fix): what a Claude agent writes in a plain Remotion project. Text and colours in the source, its own
#: helper module, no props, no theme: the native profile accepts it (only validity and safety block).
NATIVE_TITLE_TSX = """import React from "react";
import {interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";

export const Reveal: React.FC<{delay: number; children: React.ReactNode}> = ({delay, children}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame: frame - delay, fps, config: {damping: 200}});
  const y = interpolate(enter, [0, 1], [40, 0]);
  return <div style={{opacity: enter, transform: `translateY(${y}px)`}}>{children}</div>;
};
"""
NATIVE_SCENE_TSX = """import React from "react";
import {AbsoluteFill} from "remotion";
import {Reveal} from "./lib/Reveal";

// Normal Remotion code: the layout, the motion and the secondary colours are written here, helpers go to src/lib/*.tsx.
// The visible texts and the main colour are props (declared by the bundle, valued by the scene, exposed as controls): « Modifier » edits them.
export default function Scene(props: {titre: string; ligne: string; accent: string}) {
  return (
    <AbsoluteFill style={{background: "#0a0d14", color: "#f2f4f8", fontFamily: "Segoe UI, system-ui, sans-serif", padding: 140, justifyContent: "center"}}>
      <Reveal delay={0}><h1 style={{fontSize: 110, margin: 0}}>{props.titre}</h1></Reveal>
      <Reveal delay={12}><p style={{fontSize: 44, color: props.accent, margin: "24px 0 0"}}>{props.ligne}</p></Reveal>
    </AbsoluteFill>
  );
}
"""

#: presentation-edition-v1 Slice 09: what makes a native scene editable from « Modifier » (the gate refuses a native scene without a content
#: control, `NATIVE_REQUIRED`). The bundle declares the props with a default, the scene gives its values and exposes them as controls.
NATIVE_PROPS = {"type": "object", "properties": {
    "titre": {"type": "string", "max_length": 80, "default": "Titre"},
    "ligne": {"type": "string", "max_length": 160, "default": "Une ligne"},
    "accent": {"type": "color", "default": "#7cf0c4"}}}
NATIVE_CONTROLS = [
    {"control_id": "titre", "path": "props.titre", "label": "Titre", "group": "content", "meaning": "Le grand titre de la scene"},
    {"control_id": "ligne", "path": "props.ligne", "label": "Ligne sous le titre", "group": "content", "meaning": "La phrase sous le titre"},
    {"control_id": "accent", "path": "props.accent", "label": "Couleur d'accent", "group": "visual", "meaning": "La couleur de la ligne"}]


def native_example() -> dict[str, Any]:
    """A complete, valid native submission (two scenes, no score, no roles, no art direction): the SHAPE to adapt."""

    def bundle(key: str, frames: int) -> dict[str, Any]:
        return {"key": key, "remotion": {"title": f"Scene {key}", "composition": {**NATIVE_DECK_SPEC, "duration_in_frames": frames},
                                         "files": {"src/Scene.tsx": NATIVE_SCENE_TSX, "src/lib/Reveal.tsx": NATIVE_TITLE_TSX},
                                         "props": copy.deepcopy(NATIVE_PROPS)}}

    def scene(key: str, title: str, line: str) -> dict[str, Any]:
        return {"key": key, "title": title, "prefab": {"bundle": key}, "props": {"titre": title, "ligne": line, "accent": "#7cf0c4"},
                "controls": copy.deepcopy(NATIVE_CONTROLS)}

    return {"brief": {"title": "Titre de la presentation", "workflow": "directed", "authoring": "native", "language": "fr"},
            "draft": {"prefabs": [bundle("ouverture", 240), bundle("cloture", 210)],
                      "scenes": [scene("ouverture", "Ouverture", "Ce que la presentation promet, en une ligne."),
                                 scene("cloture", "Cloture", "Ce que le public retient, en une ligne.")]}}


#: The brief keys that mean something to a native deck (`strict_content` is exploratory-only and refused elsewhere; `literal_terms`,
#: `must_cover`, `resources` feed rules that are only warnings in native): the guide offers these, nothing else, so the author does not probe.
NATIVE_BRIEF_OPTIONAL = frozenset({"purpose", "audience", "duration_target_s", "tone", "language", "speech"})

#: The isolation guard (`remotion_isolation`, a case-insensitive filter, unchanged: the sandbox stays the wall) reads `<Link`, `<Frame`,
#: `<Meta`... as the forbidden HTML elements: a real native run lost two submissions to components named `Frame` and `Link`. Said up front.
ISOLATION_HINT = ("la garde d'isolation refuse les balises script, iframe, frame, frameset, embed, object, applet, link, meta, base, quelle que "
                  "soit la casse : ne nomme pas un composant Link, Frame, Meta, Base, Object ou Embed (Lien, Cadre, Etape...) ; pas de "
                  "window, document, fetch, eval, setTimeout avec une chaine ; le mot require et les echappements \\u (ASCII) sont refuses "
                  "meme dans un texte affiche : reformule (exiger, necessiter) et ecris les caracteres accentues eux-memes")

#: Master-project Slice 07 (`docs/remotion-master-project.md` § 12, M11): what makes a native deck ONE whole Remotion video by construction.
#: Technical compatibility only (spec, asset names, input props): nothing here restricts the content, the layout or the style.
NATIVE_DECK_SPEC = {key: NATIVE_DEFAULT_COMPOSITION[key] for key in ("width", "height", "fps")}
MASTER_HINT = ("VIDEO ENTIERE : les scenes d'un deck forment une seule video Remotion si elles ont toutes la meme composition width, height "
               "et fps (deck neuf : 1920x1080 a 30 ; scene ajoutee ou recodee : garde ceux de la variante, lus avec presentation_source read) ; "
               "seule la duree change. Nomme chaque fichier public/ avec le nom de sa scene (public/intro-voix.mp3, pas public/voix.mp3), "
               "le meme dans staticFile(). Jamais getInputProps : une scene lit ses props. Le resultat porte master (status, say) : "
               "incompatible = corrige ce qu'il nomme.")

NATIVE_LOOP = ("CODE REMOTION NATIF (brief.authoring: native). 1) Storyboard : une scene = une composition (taille, fps, duree en images) et "
               "une idee. 2) Ecris du React/TSX normal : texte, couleurs et mise en page dans le code, modules src/lib/*.tsx ; point d'entree "
               "src/Scene.tsx (export default) ; imports react et remotion seulement (polices systeme, pas de paquet) ; images en public/** "
               "(base64) ; aucun reseau. MODIFIABLE : les textes visibles et la couleur principale de chaque scene sont des props declarees "
               "par le bundle (props, avec default), lues par le TSX (props.titre), valuees par la scene (props) et exposees en controls "
               "(path props.titre, group content ; couleur : visual) : l'utilisateur les change depuis Modifier ; sans controle de contenu, "
               "la scene est refusee (scene_no_controls). 3) presentation_draft_assemble avec ce brief : seuls compilation, isolation, schema et references "
               "bloquent ; le reste revient en warnings (a lire, pas a negocier) ; la partition muette et les roles sont deduits. 4) "
               "presentation_source op preview sur chaque scene, puis Read de chaque image : juge lisibilite, hierarchie, debordements, "
               "mouvement. 5) Corrige avec presentation_source op write (fichiers complets), revois. Les ids viennent des resultats. "
               "6) Meme taille et meme fps pour toutes les scenes (voir master).")


def draft_guide(kind: str | None = None) -> dict[str, Any]:
    """What `presentation_inspect` target `draft_guide` returns (`kind: "exploratory"`: the exploratory example; `kind: "native"`: normal
    editable Remotion code, Slice 13). A fresh copy each time."""

    if kind == "native":
        return {"loop": NATIVE_LOOP,
                "brief": {"required": ["title", "workflow", "authoring"], "authoring": "native", "workflow": ["directed", "one_shot"],
                          "optional": sorted(NATIVE_BRIEF_OPTIONAL),
                          "types": {"duration_target_s": "secondes (entier)", "language": "fr, en, fr-CA", "tone": "liste de mots",
                                    "speech": "none (defaut natif), jarvis ou user"}},
                "draft": {"required": ["scenes"], "optional": ["prefabs", "score", "art_direction"],
                          "prefabs": "[{key, remotion: {title, files: {'src/Scene.tsx': <TSX>, 'src/lib/X.tsx': <TSX>}, props: <schema des textes et "
                                     "couleurs, avec default>, composition: {width, height, fps, duration_in_frames}, assets?: "
                                     "{'public/x.png': <base64>}}}]",
                          "scenes": "[{key, title, prefab: {bundle: <key>}, props, controls: [{control_id, path, label, group, meaning}], "
                                    "role?}] dans l'ordre du deck",
                          "keys": "key de bundle et de scene : minuscules, chiffres et _ , commence par une lettre (ouverture, scene_2)",
                          "isolation": ISOLATION_HINT, "master": MASTER_HINT},
                "note": "FORME seulement : remplace tout le texte, les couleurs, les durees et les mises en page par les tiens.",
                "example": copy.deepcopy(native_example())}
    if kind == "exploratory":
        return {"note": ("FORME: 6 directions deja divergentes (profils calcules). Garde-en 2 a 6 dans l'ordre, ne les rapproche pas "
                         "(sinon candidates_not_divergent), ecris le titre et la raison de chacune, et tes propres scenes et textes. "
                         "N'invente pas de profil de direction artistique: copie ceux-ci."),
                "example": copy.deepcopy(exploratory_example())}
    return {
        "storyboard": ("AVANT d'ecrire: pour chaque scene decide son role et sa mise en page (couverture, chiffre cle, liste, texte). Ecris 2 a 4 "
                       "sources, une par sorte de scene (`layouts` en donne trois, a copier et adapter), pas la meme pour tout le deck. "
                       "Toutes lisent `props.theme` (la DA de la variante) et `./jarvis-kit` (son mouvement): le deck reste coherent."),
        "layouts": layouts(),
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


__all__ = ["DRAFT_KEYS", "EXPLORATORY_DIRECTIONS", "MASTER_HINT", "NATIVE_DECK_SPEC", "NATIVE_LOOP", "draft_guide", "example", "exploratory_example", "layouts", "native_example"]
