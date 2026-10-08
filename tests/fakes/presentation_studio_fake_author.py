"""A scripted "fake author" for the Slice 11 authoring planner (handoff jarvis-interactive-presentation-studio).

The real author is the Jarvis brain (an LLM, reached through tools that Slice 21 will expose). The deterministic side that
Slice 11 delivers (the draft schema, the quality gate, the atomic assembly) is exercised here WITHOUT a model: this module is the
stand-in for what a competent brain would submit, and for what a careless one would. It is a rig, not a trace of Claude:
nothing here says anything about whether the real model follows `PLANNER_PROMPT`.

- `good_one_shot()` : a one-scene report, shown at once.
- `good_deck()` : a 12-scene directed review with a score, cues, and a derived art direction.
- `exploratory(n)` : `n` divergent candidates over shared scenes.
- `VIOLATIONS` : one mutation per gate rule, each with the code it must raise.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from tests.fakes.presentation_studio_art_direction import base_dict

NAMESPACE = "presentation-studio."
SLIDE = NAMESPACE + "slide"
FIXED_BRIEF_RESOURCES = [
    {"kind": "document", "locator": "doc:revue-trimestrielle", "title": "Revue trimestrielle"},
    {"kind": "web_page", "locator": "https://example.com/charte", "title": "Charte graphique"}]


def slide_bundle(prefab_id: str = SLIDE, *, animated: bool = True, guarded: bool = True, body_max: int = 600) -> dict[str, Any]:
    """A prefab candidate: one slide with a headline, a body, an accent colour, a reveal flag and a stagger (all curated)."""

    style = ".jv-panel h2 { color: var(--jv-accent); }\n"
    if animated:
        style += ".jv-panel h2 { transition: opacity 0.3s; }\n"
        if guarded:
            style += "@media (prefers-reduced-motion: reduce) { .jv-panel h2 { transition: none; } }\n"
    return {
        "manifest": {
            "schema": "jarvis.prefab", "schema_version": 1, "id": prefab_id, "version": 1, "title": "Diapositive",
            "description": "A titled slide: headline, body text, accent colour.", "family": "window", "tags": ["slide"],
            "aliases": [], "scene": {"kind": "window", "default_size": {"w": 64, "h": 40}},
            "inputs": {
                "props": {"type": "object", "properties": {
                    "headline": {"type": "string", "max_length": 80, "default": "Titre"},
                    "accent": {"type": "color", "default": "#6ee7ff"},
                    "reveal": {"type": "boolean", "default": True},
                    "stagger_ms": {"type": "integer", "min": 0, "max": 400, "default": 80},
                    "density": {"type": "enum", "values": ["compact", "airy"], "default": "airy"}}},
                "data": {"type": "object", "required": ["body"], "properties": {
                    "body": {"type": "text", "max_length": body_max},
                    "figure": {"type": "integer"}}}},
            "sample": {"props": {}, "data": {"body": "Exemple"}},
            "files": {"template": "template.html", "style": "style.css", "behavior": "behavior.js"}},
        "template": '<section class="jv-panel"><h2 data-jv-text="props.headline"></h2><p data-jv-text="data.body"></p></section>\n',
        "style": style,
        "behavior": "jarvis.on('init', function () {});\n"}


def controls() -> list[dict[str, Any]]:
    return [
        {"control_id": "headline", "path": "props.headline", "label": "Titre de la diapositive", "group": "content",
         "meaning": "Le titre affiche en haut", "bounds": {"max_length": 60}},
        {"control_id": "accent", "path": "props.accent", "label": "Couleur d'accent", "group": "visual",
         "meaning": "Couleur du titre et des reperes"},
        {"control_id": "stagger", "path": "props.stagger_ms", "label": "Decalage d'apparition", "group": "motion",
         "meaning": "Delai entre deux apparitions, en millisecondes"}]


def scene(key: str, role: str, title: str, body: str, *, bundle: str = "slide", **extra: Any) -> dict[str, Any]:
    return {"key": key, "role": role, "title": title, "prefab": {"bundle": bundle},
            "props": {"headline": title[:60]}, "data": {"body": body}, "controls": controls(),
            "anchors": [{"anchor_id": "detail", "label": "Detail", "control_id": "accent"}], **extra}


def item(scene_key: str, line: str, *, ms: int = 30_000, presenter: str = "jarvis", cue: dict | None = None,
         **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"scene": scene_key, "presenter": presenter, "target_duration_ms": ms, **extra}
    if presenter != "none":
        body["text" if presenter == "jarvis" and "note" not in extra else "note"] = line
    if cue is not None:
        body["cue"] = cue
    return body


def signals_da() -> dict[str, Any]:
    """The design signals an agent would report from a brand sheet it inspected (inspect-then-derive)."""

    return {"mode": "signals", "signals": {
        "sources": [{"kind": "document", "locator": "doc:charte-graphique", "title": "Charte graphique"}],
        "colors": [{"value": "#0b1020", "role": "background", "weight": 40}, {"value": "#e8ecf4", "role": "text", "weight": 30},
                   {"value": "#ff7a00", "role": "accent", "weight": 12}, {"value": "#9aa4b8", "role": "muted", "weight": 8}],
        "fonts": [{"family": "Playfair Display", "role": "heading"}, {"family": "Inter", "role": "body"}],
        "radii": ["8px", "12px"], "mentions": ["launch", "keynote"]}}


def brief(workflow: str = "directed", **changes: Any) -> dict[str, Any]:
    body = {"title": "Revue du trimestre", "workflow": workflow, "purpose": "Presenter les resultats et decider des priorites",
            "audience": "Direction et chefs d'equipe", "duration_target_s": 600, "tone": ["sobre", "direct"], "language": "fr",
            "speech": "jarvis", "resources": copy.deepcopy(FIXED_BRIEF_RESOURCES), "must_cover": ["resultats", "risques"],
            **changes}
    return {k: v for k, v in body.items() if v is not None}


#: Twelve real-looking beats of a quarterly review: (title, on-screen body, spoken line, cue phrase or None).
DECK = (
    ("Revue du trimestre", "Resultats, risques et priorites du troisieme trimestre.",
     "Bonjour a tous, voici la revue du troisieme trimestre : ce qui a marche, ce qui nous freine, et ce que nous decidons.", None),
    ("Le trimestre en un coup d'oeil", "Chiffre d'affaires en hausse de douze pour cent, marge stable, trois lancements tenus.",
     "En un coup d'oeil, le chiffre d'affaires progresse de douze pour cent et la marge reste stable.", "passons au chiffre d'affaires"),
    ("Chiffre d'affaires", "Hausse portee par les abonnements annuels, les ventes ponctuelles reculent legerement.",
     "La hausse vient surtout des abonnements annuels, pendant que les ventes ponctuelles reculent un peu.", None),
    ("Marge et couts", "Les couts d'hebergement baissent, les couts de support montent avec le volume.",
     "Cote couts, l'hebergement baisse mais le support suit le volume, ce qui garde la marge stable.", "regardons les couts de support"),
    ("Les trois lancements", "Application mobile, export comptable, tableau de bord partage : tous livres a la date prevue.",
     "Nous avons tenu les trois lancements : l'application mobile, l'export comptable et le tableau de bord partage.", None),
    ("Ce que disent les clients", "Satisfaction a quatre virgule deux sur cinq, trois demandes reviennent sans cesse.",
     "Les clients nous donnent quatre virgule deux sur cinq, avec trois demandes qui reviennent a chaque entretien.", "voyons le retour des clients"),
    ("Demande numero un", "Importer ses donnees depuis un tableur sans ressaisie.",
     "La premiere demande est l'import depuis un tableur, pour ne plus ressaisir des centaines de lignes.", None),
    ("Risques principaux", "Dependance a un fournisseur unique, charge du support, delais de recrutement.",
     "Trois risques : un fournisseur unique, un support sous tension et des recrutements trop lents.", "parlons des risques principaux"),
    ("Plan d'action", "Double source pour le fournisseur, deux recrutements support, import tableur au prochain trimestre.",
     "Pour y repondre, nous doublons la source fournisseur, recrutons deux personnes au support et livrons l'import tableur.", None),
    ("Priorites du prochain trimestre", "Import tableur, fiabilite du support, nouvelle offre equipe.",
     "Les priorites : l'import tableur, la fiabilite du support et la nouvelle offre equipe.", "fixons les priorites du trimestre"),
    ("Decisions attendues", "Valider le budget recrutement et le calendrier de l'import tableur.",
     "Ce que j'attends de vous aujourd'hui : valider le budget de recrutement et le calendrier de l'import.", None),
    ("Merci", "Questions et discussion.", "Merci de votre attention, je vous laisse la parole pour vos questions.", None),
)


def good_deck(count: int = 12, *, da: dict | None = None) -> dict[str, Any]:
    beats = DECK[:count - 1] + (DECK[-1],) if count < len(DECK) else DECK
    scenes, items = [], []
    for index, (title, body, line, phrase) in enumerate(beats):
        key = f"s{index + 1:02d}"
        role = "opening" if index == 0 else "closing" if index == len(beats) - 1 else "body"
        scenes.append(scene(key, role, title, body))
        cue = {"label": title[:60], "armable": True, "phrases": [phrase]} if phrase else None
        motion = [{"kind": "control_set", "control_id": "stagger", "value": 120}] if index else []
        items.append(item(key, line, ms=50_000, cue=cue, motion=motion,
                          visual=[{"kind": "control_set", "control_id": "accent", "value": "#ff7a00"}] if index % 2 else []))
    return {"prefabs": [{"key": "slide", "candidate": slide_bundle()}], "scenes": scenes, "score": {"items": items},
            "art_direction": da or signals_da()}


def good_one_shot() -> tuple[dict[str, Any], dict[str, Any]]:
    """A report shown at once: one scene, one line, the generated fallback DA (nothing to derive from)."""

    body = "Le dossier compte quarante-deux fichiers : trente documents, dix tableurs et deux presentations."
    draft = {"prefabs": [{"key": "slide", "candidate": slide_bundle()}],
             "scenes": [scene("rapport", "single", "Contenu du dossier", body)],
             "score": {"items": [item("rapport", "Voici le contenu du dossier : quarante-deux fichiers, surtout des documents.", ms=20_000)]},
             "art_direction": {"mode": "fallback"}}
    return brief("one_shot", title="Contenu du dossier", duration_target_s=20, resources=[], must_cover=[], tone=[],
                 purpose="Afficher le contenu du dossier", audience="Moi"), draft


def exploratory(count: int = 3) -> tuple[dict[str, Any], dict[str, Any]]:
    """`count` divergent directions over three shared scenes. The DA of each candidate is computed by the Slice 09 `diverge`."""

    from jarvis.domain.presentation_studio_art_direction_authoring import diverge
    from tests.fakes.presentation_studio_art_direction import base_profile

    profiles = diverge(base_profile(), count)
    roles = ("opening", "body", "closing")
    scenes = [scene(f"s{n + 1}", roles[n], t, b) for n, (t, b) in enumerate((
        ("Une idee simple", "Une presentation qui tient en trois temps."),
        ("Ce qui change", "Le visuel porte le message, le texte reste court."),
        ("Et maintenant", "Choisissez la direction qui vous ressemble.")))]
    items = [item(s["key"], f"{s['title']} : {s['data']['body']}", ms=15_000) for s in scenes]
    candidates = [{"title": f"Direction {n + 1}", "rationale": f"Piste {n + 1} : {p.name}",
                   "art_direction": {"mode": "profile", "profile": p.to_dict()},
                   **({"scenes_patch": {"s1": {"title": f"Variante {n + 1}", "props": {"headline": f"Variante {n + 1}"}}}} if n else {})}
                  for n, p in enumerate(profiles)]
    draft = {"prefabs": [{"key": "slide", "candidate": slide_bundle()}], "scenes": scenes, "score": {"items": items},
             "candidates": candidates}
    return brief("exploratory", duration_target_s=None, purpose="Trouver une direction", resources=[], must_cover=[]), draft


# ------------------------------------------------------------------ the careless author: one violation per gate rule

Mutation = Callable[[dict[str, Any], dict[str, Any]], None]


def _set(path: str, value: Any) -> Mutation:
    def apply(b: dict[str, Any], d: dict[str, Any]) -> None:
        node: Any = d
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        node[int(parts[-1]) if isinstance(node, list) else parts[-1]] = value
    return apply


def _drop_da(b: dict[str, Any], d: dict[str, Any]) -> None:
    d.pop("art_direction")


def _drop_items_of(key: str) -> Mutation:
    def apply(b: dict[str, Any], d: dict[str, Any]) -> None:
        d["score"]["items"] = [i for i in d["score"]["items"] if i["scene"] != key]
    return apply


def _many_controls(b: dict[str, Any], d: dict[str, Any]) -> None:
    """Thirteen curated controls on one scene (a wide manifest: one string field each, beside the three usual ones)."""

    d["prefabs"][0]["candidate"]["manifest"]["inputs"]["data"]["properties"].update(
        {f"f{n}": {"type": "string", "max_length": 20, "default": ""} for n in range(10)})
    d["scenes"][1]["controls"] += [{"control_id": f"c{n}", "path": f"data.f{n}", "label": f"Champ {n} visible", "group": "content",
                                    "meaning": "Un champ de plus"} for n in range(10)]


def _unlabelled(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["scenes"][1]["controls"][0]["label"] = "headline"


def _unbounded(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["scenes"][1]["controls"].append({"control_id": "figure", "path": "data.figure", "label": "Chiffre cle", "group": "content"})


def _dense(b: dict[str, Any], d: dict[str, Any]) -> None:
    words = [c + v + e for c in "bcdfghjklm" for v in "aeiou" for e in "rst"]  # 150 distinct three-letter words
    d["scenes"][3]["data"]["body"] = " ".join(words)[:599]
    d["scenes"][3]["props"]["headline"] = "Beaucoup de contenu"
    # about 150 words, over the 120-word cap, none of them a placeholder


def _weak_cue(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["score"]["items"][1]["cue"] = {"label": "Suite", "armable": True, "phrases": ["voila"]}


def _ambiguous(b: dict[str, Any], d: dict[str, Any]) -> None:
    for index in (1, 2):
        d["score"]["items"][index]["cue"] = {"label": f"Cue {index}", "armable": True, "phrases": ["passons a la suite du programme"]}


def _contrast(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["score"]["items"][2]["visual"] = [{"kind": "control_set", "control_id": "accent", "value": "#0c1224"}]


def _bad_motion(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["prefabs"][0]["candidate"] = slide_bundle(guarded=False)


def _light_da_without_colours(d: dict[str, Any], profile: dict[str, Any]) -> None:
    """Swap the DA for a (light) profile and drop the orange colour sets that would not keep contrast on it."""

    d["art_direction"] = {"mode": "profile", "profile": profile}
    for entry in d["score"]["items"]:
        entry["visual"] = []


def _no_motion_no_transition(b: dict[str, Any], d: dict[str, Any]) -> None:
    profile = base_dict()
    profile["motion"]["transition"] = "none"
    _light_da_without_colours(d, profile)
    for entry in d["score"]["items"]:
        entry["motion"] = []


def _provided_without_reference(b: dict[str, Any], d: dict[str, Any]) -> None:
    profile = base_dict()
    profile["provenance"] = {"origin": "provided", "sections": {}, "fallback": False, "confidence": 0.9, "notes": []}
    _light_da_without_colours(d, profile)


def _scene_roles(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["scenes"][0]["role"] = "body"


def _wrong_namespace(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["prefabs"][0]["candidate"] = slide_bundle("custom.slide")


def _bad_pin(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["scenes"][1]["prefab"] = {"id": "lab.absent", "version": 1}


def _control_not_in_manifest(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["scenes"][1]["controls"].append({"control_id": "ghost", "path": "props.nothing", "label": "Controle fantome", "group": "visual"})


def _score_bad_ref(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["score"]["items"][1]["visual"] = [{"kind": "reveal", "anchor_id": "nothing_here"}]


def _jarvis_in_user_deck(b: dict[str, Any], d: dict[str, Any]) -> None:
    b["speech"] = "user"


def _speech_in_silent_brief(b: dict[str, Any], d: dict[str, Any]) -> None:
    b["speech"] = "none"


def _short(b: dict[str, Any], d: dict[str, Any]) -> None:
    b["duration_target_s"] = 1800


def _silence_scene(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["score"]["items"][4] = {"scene": "s05", "presenter": "none", "target_duration_ms": 50_000}


def _repeat_filler(b: dict[str, Any], d: dict[str, Any]) -> None:
    for index in (2, 3, 4):
        d["scenes"][index]["data"]["body"] = "Cette phrase de remplissage est repetee dans plusieurs scenes."


def _thin_scene(b: dict[str, Any], d: dict[str, Any]) -> None:
    scene = d["scenes"][3]
    scene["title"], scene["data"]["body"], scene["props"]["headline"] = "Alpha", "...", "-"


def _numeric_filler(b: dict[str, Any], d: dict[str, Any]) -> None:
    for n in range(1, 5):
        d["scenes"][n]["data"]["body"] = f"Voici le point numero {n} du trimestre pour tous"


def _stopword_cue(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["score"]["items"][1]["cue"] = {"label": "Suite", "armable": True, "phrases": ["et puis voila"]}


def _label_symbols(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["scenes"][1]["controls"][0]["label"] = "???"


def _uncovered(b: dict[str, Any], d: dict[str, Any]) -> None:
    b["must_cover"] = ["cryptographie quantique"]


def _wrong_language(b: dict[str, Any], d: dict[str, Any]) -> None:
    b["language"] = "de"


def _risky_source(b: dict[str, Any], d: dict[str, Any]) -> None:
    d["prefabs"][0]["candidate"]["behavior"] = "jarvis.on('init', function () { fetch('https://collect.example/x'); });"


VIOLATIONS: tuple[tuple[str, Mutation], ...] = (
    ("da_missing", _drop_da),
    ("da_incoherent", _provided_without_reference),
    ("contrast_low", _contrast),
    ("arc_incomplete", _scene_roles),
    ("scene_no_score", _drop_items_of("s05")),
    ("transition_missing", _no_motion_no_transition),
    ("placeholder_text", _set("scenes.2.data.body", "Lorem ipsum dolor sit amet, a completer plus tard.")),
    ("repeated_filler", _repeat_filler),
    ("text_density", _dense),
    ("duration_off", _short),
    ("presenter_mismatch", _jarvis_in_user_deck),
    ("controls_too_many", _many_controls),
    ("control_unlabelled", _unlabelled),
    ("control_unbounded", _unbounded),
    ("cue_weak", _weak_cue),
    ("cue_ambiguous", _ambiguous),
    ("motion_unguarded", _bad_motion),
    ("prefab_namespace", _wrong_namespace),
    ("pin_unknown", _bad_pin),
    ("scene_incompatible", _control_not_in_manifest),
    ("score_incompatible", _score_bad_ref),
    ("notes_missing", _silence_scene),
    ("content_thin", _thin_scene),
    ("filler_numeric_variants", _numeric_filler),
    ("cue_stopword_phrase", _stopword_cue),
    ("control_label_meaningless", _label_symbols),
    ("must_cover_missing", _uncovered),
    ("language_mismatch", _wrong_language),
    ("behavior_risky", _risky_source),
)


def violate(code: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """A good directed deck with exactly the damage of `code` done to it."""

    b, d = brief("directed"), good_deck()
    dict(VIOLATIONS)[code](b, d)
    return b, d
