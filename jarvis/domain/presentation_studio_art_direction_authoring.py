"""Presentation Studio : de quoi **produire** une direction artistique sans modèle de langage (handoff
jarvis-interactive-presentation-studio, Slice 09). Pur, déterministe, sans E/S.

Trois entrées, un même type de sortie (`ArtDirectionProfile`, donc déjà validé en contraste, vocabulaire et bornes) :

- `generate_fallback_profile(seed)` : repli quand personne n'a fourni de DA. Le contexte (titre, public, objectif,
  mots de ton) choisit un **archétype** par un lexique fermé (FR + EN), à défaut par un condensat stable du contexte :
  la même entrée donne toujours le même profil. Provenance `generated`, `fallback: true`.
- `diverge(profile, n)` : `n` candidats **distinguables** pour le mode exploratoire, choisis sur des axes définis
  (palette, typographie, formes, densité, mouvement, image) par éloignement maximal ; `profile_distance` est la métrique.
- `derive_from_signals(signals)` : construit un profil à partir de signaux **déjà extraits** par les outils d'un agent
  (couleurs hex, noms de polices, rayons, mentions). Ce module n'accède ni au disque ni au réseau : il ne lit rien, il
  reçoit des données. Provenance `inférée`, section par section.

Les décisions de goût (inspecter le projet, poser la bonne question, écrire des candidats par prompt) appartiennent
aux Slices 11 et 21 ; la politique est dans `docs/presentation-studio.md` › *Art direction authoring policy*.
Aucune chaîne reçue n'est recopiée dans le profil, sauf comme **famille déclarée** (nom simple) ou titre/localisateur
de référence, tous deux contraints par le domaine.
"""

from __future__ import annotations

import colorsys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import re
import unicodedata
from typing import Any

from jarvis.domain.prefab import canonical_json
from jarvis.domain.presentation_studio import resource_from_dict, resource_to_dict
from jarvis.domain.presentation_studio_art_direction import (
    GRAPHIC_RATIO, MAX_FAMILY_CHARS, MAX_RADIUS_PX, MAX_REFERENCES,
    SECONDARY_RATIO, TEXT_RATIO, ArtDirectionProfile, DataViz, Density, Easing, Elevation, Emphasis, FontChoice,
    FONT_CLASS, FontStack, Gradient, GradientKind, GradientStop, GridStyle, IconStyle, IllustrationStyle, Imagery,
    ImageTreatment, LabelCase, LabelPlacement, Margin, Motion, Origin, Palette, PhotoStyle, Provenance, ReducedMotion,
    ScaleRatio, Section, SeriesMode, Shapes, Spacing, Tempo, TextSize, TextToken, TransitionStyle, Typography, _FAMILY,
    _color, _enum, _line, _tuple, blend, check_reference, contrast_ratio, parse_length, relative_luminance,
)
from jarvis.domain.presentation_studio_checks import PresentationStudioError, _exact_keys, _fail
from jarvis.domain.presentation_working_set import ResourceReference

MAX_DIVERGE = 6
#: Éloignement minimal (métrique `profile_distance`) entre deux candidats, et entre un candidat et le profil de départ.
MIN_DIVERGENCE = 0.2
MAX_TONE_WORDS = 8
MAX_TONE_CHARS = 24
MAX_CONTEXT_CHARS = 200
MAX_SIGNAL_COLORS = 32
MAX_SIGNAL_FONTS = 8
MAX_SIGNAL_RADII = 16
MAX_SIGNAL_MENTIONS = 16
MAX_MENTION_CHARS = 60
MAX_COLOR_WEIGHT = 1000


# ------------------------------------------------------------------ archétypes


class Archetype(StrEnum):
    CORPORATE_CALM = "corporate_calm"
    EDITORIAL_BOLD = "editorial_bold"
    TECHNICAL_DARK = "technical_dark"
    PLAYFUL_BRIGHT = "playful_bright"
    LUXURY_MINIMAL = "luxury_minimal"
    WARM_HUMAN = "warm_human"
    BOLD_CONTRAST = "bold_contrast"


LIGHT_SERIES = ("#0b6bcb", "#c2410c", "#0f766e", "#7e22ce", "#a16207")
DARK_SERIES = ("#38bdf8", "#fb923c", "#34d399", "#c084fc", "#facc15")
LIGHT_ACCENT, DARK_ACCENT = "#0b6bcb", "#38bdf8"
LIGHT_TEXT, DARK_TEXT = "#18181b", "#f4f4f5"

_MOTION: Mapping[Tempo, Motion] = {
    Tempo.CALM: Motion(Tempo.CALM, 480, 320, 320, Easing.STANDARD, 80, TransitionStyle.FADE, ReducedMotion.FADE_ONLY),
    Tempo.MEASURED: Motion(Tempo.MEASURED, 320, 200, 200, Easing.EASE_OUT, 40, TransitionStyle.SLIDE,
                           ReducedMotion.FADE_ONLY),
    Tempo.LIVELY: Motion(Tempo.LIVELY, 200, 120, 200, Easing.SNAPPY, 40, TransitionStyle.SCALE, ReducedMotion.FADE_ONLY),
}


@dataclass(frozen=True, slots=True)
class _Spec:
    label: str
    words: frozenset[str]
    dark: bool
    colors: tuple[str, str, str, str]  # background, surface, text, muted
    accents: tuple[str, str, str]
    heading: FontStack
    body: FontStack
    weights: tuple[int, int]  # heading, body
    text_size: TextSize
    ratio: ScaleRatio
    case: LabelCase
    density: Density
    margin: Margin
    shapes: tuple[int, int, Elevation]  # radius, stroke, elevation
    imagery: tuple[PhotoStyle, IllustrationStyle, IconStyle, ImageTreatment, tuple[str, ...]]
    dataviz: tuple[SeriesMode, GridStyle, LabelPlacement, Emphasis]
    tempo: Tempo


def _words(text: str) -> frozenset[str]:
    return frozenset(w for w in (w.strip() for w in re.split(r"[^a-z0-9]+", _fold(text))) if w)


def _fold(text: str) -> str:
    """Minuscules sans accents (NFKD) : « Éducation » et « education » sont le même mot du lexique."""

    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


_SPECS: Mapping[Archetype, _Spec] = {
    Archetype.CORPORATE_CALM: _Spec(
        "Corporate calm", _words("corporate entreprise business sobre serieux professionnel professional finance "
                                 "financier banque bank investisseur investor board comite conformite audit rapport "
                                 "report assurance calme clean trust confiance"),
        False, ("#f7f9fb", "#ffffff", "#14212b", "#4a5b68"), ("#0b6bcb", "#0f766e", "#5b4bd6"),
        FontStack.HUMANIST_SANS, FontStack.HUMANIST_SANS, (600, 400), TextSize.NORMAL, ScaleRatio.BALANCED,
        LabelCase.NONE, Density.BALANCED, Margin.STANDARD, (6, 1, Elevation.SOFT),
        (PhotoStyle.DOCUMENTARY, IllustrationStyle.FLAT, IconStyle.OUTLINE, ImageTreatment.NATURAL, ("people", "workplace")),
        (SeriesMode.CATEGORICAL, GridStyle.SUBTLE, LabelPlacement.DIRECT, Emphasis.SINGLE_ACCENT), Tempo.CALM),
    Archetype.EDITORIAL_BOLD: _Spec(
        "Editorial bold", _words("editorial magazine presse journal news medias media story narratif narrative culture "
                                 "essai essay manifeste bold audacieux impact percutant cinema"),
        False, ("#fbf7f0", "#fffdf8", "#1a1410", "#5c5047"), ("#c2410c", "#9d174d", "#1d4ed8"),
        FontStack.TRANSITIONAL_SERIF, FontStack.TRANSITIONAL_SERIF, (800, 400), TextSize.LARGE, ScaleRatio.DRAMATIC,
        LabelCase.UPPERCASE, Density.AIRY, Margin.WIDE, (0, 2, Elevation.FLAT),
        (PhotoStyle.EDITORIAL, IllustrationStyle.LINE, IconStyle.SHARP, ImageTreatment.HIGH_CONTRAST, ("portrait", "texture")),
        (SeriesMode.CATEGORICAL, GridStyle.NONE, LabelPlacement.DIRECT, Emphasis.SINGLE_ACCENT), Tempo.MEASURED),
    Archetype.TECHNICAL_DARK: _Spec(
        "Technical dark", _words("tech technique technical ingenierie engineering developpeur developer dev code logiciel "
                                 "software data donnees ia cloud architecture securite security devops startup produit"),
        True, ("#0b1118", "#121b25", "#e6eef5", "#94a7b8"), ("#38bdf8", "#34d399", "#a78bfa"),
        FontStack.SYSTEM_SANS, FontStack.SYSTEM_SANS, (600, 400), TextSize.NORMAL, ScaleRatio.TIGHT,
        LabelCase.UPPERCASE, Density.COMPACT, Margin.STANDARD, (4, 1, Elevation.FLAT),
        (PhotoStyle.NONE, IllustrationStyle.GEOMETRIC, IconStyle.OUTLINE, ImageTreatment.MONOCHROME, ("diagram", "grid")),
        (SeriesMode.CATEGORICAL, GridStyle.FULL, LabelPlacement.LEGEND, Emphasis.MULTI), Tempo.MEASURED),
    Archetype.PLAYFUL_BRIGHT: _Spec(
        "Playful bright", _words("fun ludique playful enfants kids jeunes jeune ecole school education formation atelier "
                                 "workshop joyeux color colore colorful creatif creative festif communaute community"),
        False, ("#fffbeb", "#ffffff", "#231942", "#5b4b8a"), ("#e11d48", "#ea580c", "#7c3aed"),
        FontStack.ROUNDED_SANS, FontStack.ROUNDED_SANS, (700, 400), TextSize.LARGE, ScaleRatio.COMFORTABLE,
        LabelCase.NONE, Density.AIRY, Margin.STANDARD, (20, 2, Elevation.SOFT),
        (PhotoStyle.ABSTRACT, IllustrationStyle.HAND_DRAWN, IconStyle.ROUNDED, ImageTreatment.NATURAL, ("shapes", "characters")),
        (SeriesMode.CATEGORICAL, GridStyle.NONE, LabelPlacement.DIRECT, Emphasis.MULTI), Tempo.LIVELY),
    Archetype.LUXURY_MINIMAL: _Spec(
        "Luxury minimal", _words("luxe luxury premium elegant elegance minimal minimaliste haut gamme joaillerie mode "
                                 "fashion architecte design gallery galerie exclusif"),
        True, ("#0d0d0d", "#171717", "#f3efe6", "#a39e92"), ("#c9a96e", "#b8b8b8", "#d4af37"),
        FontStack.OLD_STYLE_SERIF, FontStack.HUMANIST_SANS, (400, 300), TextSize.NORMAL, ScaleRatio.COMFORTABLE,
        LabelCase.UPPERCASE, Density.AIRY, Margin.WIDE, (0, 1, Elevation.FLAT),
        (PhotoStyle.EDITORIAL, IllustrationStyle.NONE, IconStyle.OUTLINE, ImageTreatment.MONOCHROME, ("material", "detail")),
        (SeriesMode.SEQUENTIAL, GridStyle.NONE, LabelPlacement.DIRECT, Emphasis.SINGLE_ACCENT), Tempo.CALM),
    Archetype.WARM_HUMAN: _Spec(
        "Warm human", _words("humain human chaleureux warm equipe team rh ressources recrutement accueil sante health "
                             "bien etre wellbeing famille associatif association ong solidarite nature ecologie durable"),
        False, ("#fdf6ee", "#fffaf3", "#2b1d14", "#6a5444"), ("#b45309", "#15803d", "#be123c"),
        FontStack.OLD_STYLE_SERIF, FontStack.SYSTEM_SANS, (700, 400), TextSize.LARGE, ScaleRatio.BALANCED,
        LabelCase.NONE, Density.AIRY, Margin.STANDARD, (14, 1, Elevation.SOFT),
        (PhotoStyle.DOCUMENTARY, IllustrationStyle.HAND_DRAWN, IconStyle.ROUNDED, ImageTreatment.NATURAL, ("hands", "daylight")),
        (SeriesMode.CATEGORICAL, GridStyle.SUBTLE, LabelPlacement.DIRECT, Emphasis.SINGLE_ACCENT), Tempo.CALM),
    Archetype.BOLD_CONTRAST: _Spec(
        "Bold contrast", _words("lancement launch keynote conference evenement event energie energy sport innovation futur "
                                "future dynamique dynamic gaming jeu pitch demo"),
        True, ("#10002b", "#240046", "#f8f0ff", "#c4a7e7"), ("#ff9e00", "#ff4d6d", "#00f5d4"),
        FontStack.CONDENSED_SANS, FontStack.SYSTEM_SANS, (800, 400), TextSize.XLARGE, ScaleRatio.DRAMATIC,
        LabelCase.UPPERCASE, Density.BALANCED, Margin.NARROW, (10, 2, Elevation.DRAMATIC),
        (PhotoStyle.ABSTRACT, IllustrationStyle.ISOMETRIC, IconStyle.FILLED, ImageTreatment.DUOTONE, ("gradient", "motion")),
        (SeriesMode.CATEGORICAL, GridStyle.SUBTLE, LabelPlacement.LEGEND, Emphasis.MULTI), Tempo.LIVELY),
}
ARCHETYPES = tuple(Archetype)


def build_archetype_profile(archetype: Archetype, accent_index: int, *, name: str, provenance: Provenance,
                            references: tuple[ResourceReference, ...] = ()) -> ArtDirectionProfile:
    """Le profil complet et valide d'un archétype (`accent_index` 0..2 choisit l'accent). Les constantes ci-dessus sont
    vérifiées par un test (contraste de chaque combinaison archétype x accent)."""

    spec = _SPECS[archetype]
    background, surface, text, muted = spec.colors
    accent = spec.accents[accent_index % 3]
    alt = spec.accents[(accent_index + 1) % 3]
    palette = Palette(background, surface, 100 if spec.dark else 96, text, muted, accent, alt,
                      (Gradient("backdrop", GradientKind.LINEAR, 160,
                                (GradientStop(background, 0), GradientStop(surface, 100)), TextToken.TEXT),))
    series = list(DARK_SERIES if spec.dark else LIGHT_SERIES)
    series = [accent, alt, *[c for c in series if c not in (accent, alt)]][:5]
    photo, illustration, icons, treatment, motifs = spec.imagery
    mode, grid, labels, emphasis = spec.dataviz
    radius, stroke, elevation = spec.shapes
    return ArtDirectionProfile(
        name, provenance, palette,
        Typography(FontChoice(spec.heading, None), FontChoice(spec.body, None), spec.text_size, spec.ratio,
                   spec.weights[0], spec.weights[1], spec.case),
        Spacing(spec.density, spec.margin), Shapes(radius, stroke, elevation),
        Imagery(photo, illustration, icons, treatment, motifs), DataViz(mode, tuple(series), grid, labels, emphasis),
        _MOTION[spec.tempo], references)


# ------------------------------------------------------------------ contexte de repli


@dataclass(frozen=True, slots=True)
class SeedContext:
    """Ce que l'on sait de la présentation quand personne n'a fourni de DA. Tout est facultatif. Texte non fiable : il ne sert
    qu'à choisir dans un lexique fermé et à calculer un condensat, rien n'en est recopié dans le profil."""

    title: str = ""
    audience: str = ""
    purpose: str = ""
    tone: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("title", "audience", "purpose"):
            value = getattr(self, name)
            if value != "":
                _line(f"seed_context.{name}", value, MAX_CONTEXT_CHARS)
        tone = tuple(_line("seed_context.tone[]", w, MAX_TONE_CHARS) for w in _tuple("seed_context.tone", self.tone, MAX_TONE_WORDS))
        object.__setattr__(self, "tone", tone)

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "audience": self.audience, "purpose": self.purpose, "tone": list(self.tone)}


def parse_seed_context(raw: object) -> SeedContext:
    data = _exact_keys(raw, "seed_context", set(), frozenset({"title", "audience", "purpose", "tone"}))
    return SeedContext(data.get("title", ""), data.get("audience", ""), data.get("purpose", ""), data.get("tone", []))


def _digest(value: object) -> int:
    return int.from_bytes(hashlib.sha256(canonical_json(value).encode("utf-8")).digest()[:8], "big")


def choose_archetype(words: frozenset[str], digest: int) -> tuple[Archetype, int, bool]:
    """`(archétype, indice d'accent, lexique touché)`. Le plus de mots du lexique gagne (égalité : ordre de `ARCHETYPES`) ;
    sans aucun mot connu, le condensat stable du contexte décide."""

    scores = [(len(words & _SPECS[a].words), -i, a) for i, a in enumerate(ARCHETYPES)]
    best = max(scores)
    accent = (digest >> 8) % 3
    if best[0] > 0:
        return best[2], accent, True
    return ARCHETYPES[digest % len(ARCHETYPES)], accent, False


def generate_fallback_profile(seed_context: SeedContext | Mapping[str, Any] | None = None) -> ArtDirectionProfile:
    """Un profil complet et cohérent à partir du titre, du public, de l'objectif et des mots de ton, **stable** pour une
    entrée donnée, de provenance `generated` et marqué `fallback`. Une présentation résout ainsi toujours une DA."""

    seed = seed_context if isinstance(seed_context, SeedContext) else parse_seed_context(seed_context or {})
    words = _words(" ".join((seed.title, seed.audience, seed.purpose, *seed.tone)))
    key = [_fold(seed.title), _fold(seed.audience), _fold(seed.purpose), [_fold(w) for w in seed.tone]]
    archetype, accent, matched = choose_archetype(words, _digest(key))
    label = _SPECS[archetype].label
    provenance = Provenance(
        Origin.GENERATED, {}, True, 0.5 if matched else 0.3,
        ("Generated fallback: no art direction was provided or inferable from the project.",
         f"Direction: {label}, chosen from {'the brief wording' if matched else 'a stable hash of the brief'}.",
         "Replace it as soon as a provided or inferred source exists."))
    return build_archetype_profile(archetype, accent, name=f"Fallback - {label}", provenance=provenance)


# ------------------------------------------------------------------ divergence


def _hue(color: str) -> tuple[float, float]:
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, _ = colorsys.rgb_to_hsv(r, g, b)
    return h * 360, s


def _ordinal(kind: type[StrEnum], value: StrEnum) -> float:
    members = list(kind)
    return members.index(value) / max(1, len(members) - 1)


#: Les axes de divergence et leur poids (somme 1). La distance est la somme pondérée des écarts par axe, chacun dans [0, 1].
AXES: Mapping[str, float] = {"palette": 0.30, "typography": 0.20, "shape": 0.15, "density": 0.10, "motion": 0.15,
                             "imagery": 0.10}


def axis_distances(a: ArtDirectionProfile, b: ArtDirectionProfile) -> dict[str, float]:
    """Écart de chaque axe entre deux profils, chacun dans [0, 1] ; symétrique."""

    la, lb = relative_luminance(a.palette.background), relative_luminance(b.palette.background)
    (ha, sa), (hb, sb) = _hue(a.palette.accent), _hue(b.palette.accent)
    if sa < 0.12 or sb < 0.12:
        hue = 0.0 if (sa < 0.12 and sb < 0.12) else 0.5
    else:
        turn = abs(ha - hb)
        hue = min(turn, 360 - turn) / 180
    palette = 0.5 * abs(la - lb) + 0.5 * hue
    ta, tb = a.typography, b.typography
    typography = (0.4 * (FONT_CLASS[ta.heading.stack] != FONT_CLASS[tb.heading.stack])
                  + 0.2 * (FONT_CLASS[ta.body.stack] != FONT_CLASS[tb.body.stack])
                  + 0.2 * (ta.heading.stack != tb.heading.stack)
                  + 0.2 * min(1.0, abs(ta.heading_weight - tb.heading_weight) / 400))
    shape = (0.6 * abs(a.shapes.radius_px - b.shapes.radius_px) / MAX_RADIUS_PX
             + 0.4 * abs(_ordinal(Elevation, a.shapes.elevation) - _ordinal(Elevation, b.shapes.elevation)))
    density = abs(_ordinal(Density, a.spacing.density) - _ordinal(Density, b.spacing.density))
    motion = (0.5 * abs(_ordinal(Tempo, a.motion.tempo) - _ordinal(Tempo, b.motion.tempo))
              + 0.25 * (a.motion.easing != b.motion.easing) + 0.25 * (a.motion.transition != b.motion.transition))
    ia, ib = a.imagery, b.imagery
    imagery = sum((ia.photo != ib.photo, ia.illustration != ib.illustration, ia.icons != ib.icons,
                   ia.treatment != ib.treatment)) / 4
    return {"palette": palette, "typography": typography, "shape": shape, "density": density, "motion": motion,
            "imagery": imagery}


def profile_distance(a: ArtDirectionProfile, b: ArtDirectionProfile) -> float:
    """Éloignement perceptible entre deux profils, 0.0 (même direction) .. 1.0, pondéré par `AXES`. Sert à choisir des
    candidats qui se distinguent vraiment (`diverge`) et à comparer sans `==`."""

    axes = axis_distances(a, b)
    return sum(AXES[name] * axes[name] for name in AXES)


def diverge(profile: ArtDirectionProfile, n: int) -> tuple[ArtDirectionProfile, ...]:
    """`n` (1..`MAX_DIVERGE`) candidats générés qui se distinguent du profil de départ **et** entre eux : parmi les
    combinaisons archétype x accent, on prend chaque fois celle qui maximise la distance minimale à tout ce qui est déjà
    retenu (départ compris). Déterministe : mêmes entrées, mêmes candidats, même ordre. Rien n'est écrit."""

    if type(n) is not int or not 1 <= n <= MAX_DIVERGE:
        raise _fail(f"n must be an integer in 1..{MAX_DIVERGE}")
    pool: list[tuple[int, Archetype, int, ArtDirectionProfile]] = []
    for archetype in ARCHETYPES:
        for accent in range(3):
            pool.append((len(pool), archetype, accent, build_archetype_profile(
                archetype, accent, name="x", provenance=Provenance(Origin.GENERATED))))
    anchors = [profile]
    chosen: list[ArtDirectionProfile] = []
    for k in range(1, n + 1):
        best = max(pool, key=lambda row: (min(profile_distance(row[3], other) for other in anchors), -row[0]))
        pool.remove(best)
        _, archetype, accent, _built = best
        label = _SPECS[archetype].label
        candidate = build_archetype_profile(
            archetype, accent, name=f"Direction {k} - {label}",
            provenance=Provenance(Origin.GENERATED, {}, False, 0.4,
                                  (f"Divergent candidate {k} of {n}: {label}.",
                                   "Chosen to differ on palette, typography, shape, density, motion and imagery.")))
        chosen.append(candidate)
        anchors.append(candidate)
    return tuple(chosen)


# ------------------------------------------------------------------ signaux déjà extraits


class ColorRole(StrEnum):
    BACKGROUND = "background"
    SURFACE = "surface"
    TEXT = "text"
    MUTED = "muted"
    ACCENT = "accent"
    UNKNOWN = "unknown"


class FontRole(StrEnum):
    HEADING = "heading"
    BODY = "body"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ColorSignal:
    value: str
    role: ColorRole = ColorRole.UNKNOWN
    weight: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _color("signal colour", self.value))
        object.__setattr__(self, "role", _enum(ColorRole, "signal colour role", self.role))
        if type(self.weight) is not int or not 1 <= self.weight <= MAX_COLOR_WEIGHT:
            raise _fail(f"signal colour weight must be an integer in 1..{MAX_COLOR_WEIGHT}")

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "role": self.role.value, "weight": self.weight}


@dataclass(frozen=True, slots=True)
class FontSignal:
    family: str
    role: FontRole = FontRole.UNKNOWN

    def __post_init__(self) -> None:
        if (not isinstance(self.family, str) or len(self.family) > MAX_FAMILY_CHARS or not self.family.isascii()
                or not _FAMILY.fullmatch(self.family)):
            raise _fail("a signal font family is a plain name: letters, digits, single spaces or hyphens")
        object.__setattr__(self, "role", _enum(FontRole, "signal font role", self.role))

    def to_dict(self) -> dict[str, Any]:
        return {"family": self.family, "role": self.role.value}


@dataclass(frozen=True, slots=True)
class DesignSignals:
    """Le schéma de ce que les outils d'un agent rapportent d'un projet. **Des données, pas des fichiers** : l'agent a lu, ce
    module reçoit. `sources` : ce qui a été inspecté (références, jamais copié) ; `radii_px` : rayons déjà en px
    (`parse_length` convertit `rem`/`em`) ; `mentions` : mots de ton lus dans des documents (texte non fiable)."""

    sources: tuple[ResourceReference, ...] = ()
    colors: tuple[ColorSignal, ...] = ()
    fonts: tuple[FontSignal, ...] = ()
    radii_px: tuple[int, ...] = ()
    mentions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(isinstance(r, ResourceReference) for r in _tuple("sources", self.sources, MAX_REFERENCES)):
            raise _fail("sources must be resource references")
        for n, source in enumerate(self.sources):
            check_reference(f"sources[{n}]", source)
        if not all(isinstance(c, ColorSignal) for c in _tuple("colors", self.colors, MAX_SIGNAL_COLORS)):
            raise _fail("colors must be colour signals")
        if not all(isinstance(f, FontSignal) for f in _tuple("fonts", self.fonts, MAX_SIGNAL_FONTS)):
            raise _fail("fonts must be font signals")
        radii = _tuple("radii_px", self.radii_px, MAX_SIGNAL_RADII)
        if not all(type(r) is int and 0 <= r <= MAX_RADIUS_PX for r in radii):
            raise _fail(f"radii_px must be integers in 0..{MAX_RADIUS_PX}")
        object.__setattr__(self, "mentions", tuple(_line("mentions[]", m, MAX_MENTION_CHARS)
                                                   for m in _tuple("mentions", self.mentions, MAX_SIGNAL_MENTIONS)))

    @property
    def usable(self) -> bool:
        return bool(self.colors or self.fonts or self.radii_px or self.mentions)

    def to_dict(self) -> dict[str, Any]:
        return {"sources": [resource_to_dict(r) for r in self.sources], "colors": [c.to_dict() for c in self.colors],
                "fonts": [f.to_dict() for f in self.fonts], "radii_px": list(self.radii_px), "mentions": list(self.mentions)}


def parse_design_signals(raw: object) -> DesignSignals:
    """`{sources, colors, fonts, radii, mentions}` -> `DesignSignals` ; clé inconnue, couleur qui n'est pas `#rrggbb`, longueur
    qui n'est pas un nombre suivi de px/rem/em, famille qui n'est pas un nom simple : refus nommé."""

    data = _exact_keys(raw, "design signals", set(), frozenset({"sources", "colors", "fonts", "radii", "mentions"}))
    sources = tuple(resource_from_dict(r, f"sources[{n}]") for n, r in enumerate(_tuple("sources", data.get("sources", []), MAX_REFERENCES)))
    colors = tuple(ColorSignal(**_exact_keys(c, f"colors[{n}]", {"value"}, frozenset({"role", "weight"})))
                   for n, c in enumerate(_tuple("colors", data.get("colors", []), MAX_SIGNAL_COLORS)))
    fonts = tuple(FontSignal(**_exact_keys(f, f"fonts[{n}]", {"family"}, frozenset({"role"})))
                  for n, f in enumerate(_tuple("fonts", data.get("fonts", []), MAX_SIGNAL_FONTS)))
    radii = tuple(parse_length(r) for r in _tuple("radii", data.get("radii", []), MAX_SIGNAL_RADII))
    return DesignSignals(sources, colors, fonts, radii, data.get("mentions", []))


_FAMILY_HINTS: tuple[tuple[FontStack, tuple[str, ...]], ...] = (
    (FontStack.SYSTEM_MONO, ("mono", "code", "consolas", "courier", "menlo", "fira")),
    (FontStack.SLAB_SERIF, ("slab", "rockwell", "clarendon")),
    (FontStack.OLD_STYLE_SERIF, ("palatino", "garamond", "book", "baskerville", "caslon", "bembo")),
    (FontStack.TRANSITIONAL_SERIF, ("georgia", "times", "playfair", "merriweather", "lora", "didot", "bodoni",
                                    "cambria", "serif")),
    (FontStack.ROUNDED_SANS, ("rounded", "nunito", "quicksand", "varela", "comfortaa")),
    (FontStack.CONDENSED_SANS, ("condensed", "narrow", "oswald", "bebas")),
    (FontStack.GEOMETRIC_SANS, ("futura", "gothic", "avenir", "montserrat", "poppins", "geometric")),
    (FontStack.HUMANIST_SANS, ("segoe", "calibri", "candara", "frutiger", "humanist", "open", "lato", "noto", "source")),
)


def classify_family(family: str) -> FontStack:
    """Une famille déclarée -> la pile **fermée** la plus proche (lexique de noms ; « sans » l'emporte sur « serif »)."""

    folded = _fold(family)
    tokens = _words(folded)
    if "sans" in tokens and "serif" in tokens:
        return FontStack.SYSTEM_SANS
    for stack, hints in _FAMILY_HINTS:
        if any(hint in folded for hint in hints):
            return stack
    return FontStack.SYSTEM_SANS


def _is_dark(color: str) -> bool:
    return contrast_ratio(color, "#ffffff") > contrast_ratio(color, "#000000")


def _try_palette(**kwargs: Any) -> Palette | None:
    try:
        return Palette(**kwargs)
    except PresentationStudioError:
        return None


def _derive_palette(signals: DesignSignals, base: ArtDirectionProfile, dark_base: bool) -> tuple[Palette, bool]:
    """Palette depuis les couleurs reçues, **réparée** jusqu'à passer le contraste (jamais refusée) : indices de rôle d'abord,
    puis heuristique de luminance et de saturation, puis le gabarit de l'archétype. `bool` : une couleur reçue a servi."""

    weights: Counter[str] = Counter()
    roles: dict[ColorRole, Counter[str]] = {}
    for signal in signals.colors:
        weights[signal.value] += signal.weight
        roles.setdefault(signal.role, Counter())[signal.value] += signal.weight

    def hinted(role: ColorRole) -> str | None:
        counts = roles.get(role)
        return min(counts, key=lambda c: (-counts[c], c)) if counts else None

    def heaviest(candidates: list[str]) -> str | None:
        return min(candidates, key=lambda c: (-weights[c], c)) if candidates else None

    if not weights:
        return base.palette, False
    background = hinted(ColorRole.BACKGROUND) or heaviest(
        [c for c in weights if relative_luminance(c) < 0.08 or relative_luminance(c) > 0.8]) or base.palette.background
    dark = _is_dark(background)
    text = hinted(ColorRole.TEXT)
    if text is None or contrast_ratio(text, background) < TEXT_RATIO:
        text = heaviest([c for c in weights if contrast_ratio(c, background) >= TEXT_RATIO and c != background]) \
            or (DARK_TEXT if dark else LIGHT_TEXT)
    surface = hinted(ColorRole.SURFACE) or (base.palette.surface if dark == dark_base else blend(text, background, 0.06))
    muted = hinted(ColorRole.MUTED)
    if muted is None or contrast_ratio(muted, background) < SECONDARY_RATIO:
        muted = blend(text, background, 0.65)
    taken = {background, text, surface, muted}
    saturated = sorted((c for c in weights if c not in taken and contrast_ratio(c, background) >= GRAPHIC_RATIO),
                       key=lambda c: (-(weights[c] * (0.2 + _hue(c)[1])), c))
    accent = hinted(ColorRole.ACCENT)
    if accent is None or contrast_ratio(accent, background) < GRAPHIC_RATIO:
        accent = saturated[0] if saturated else (DARK_ACCENT if dark else LIGHT_ACCENT)
    alt = next((c for c in saturated if c != accent and _hue_gap(c, accent) >= 40), None)
    gradient = Gradient("backdrop", GradientKind.LINEAR, 160, (GradientStop(background, 0), GradientStop(surface, 100)),
                        TextToken.TEXT)
    attempts = [
        dict(background=background, surface=surface, surface_opacity=96, text=text, muted=muted, accent=accent,
             accent_alt=alt, gradients=(gradient,)),
        dict(background=background, surface=surface, surface_opacity=100, text=text, muted=muted, accent=accent,
             accent_alt=alt, gradients=()),
        dict(background=background, surface=background, surface_opacity=100, text=text, muted=text, accent=accent,
             accent_alt=None, gradients=()),
        dict(background=background, surface=background, surface_opacity=100, text=DARK_TEXT if dark else LIGHT_TEXT,
             muted=DARK_TEXT if dark else LIGHT_TEXT, accent=DARK_ACCENT if dark else LIGHT_ACCENT, accent_alt=None,
             gradients=()),
    ]
    for attempt in attempts:
        palette = _try_palette(**attempt)
        if palette is not None:
            return palette, True
    return base.palette, False  # unreachable in practice (the last attempt is valid by construction); a valid palette anyway


def _hue_gap(a: str, b: str) -> float:
    turn = abs(_hue(a)[0] - _hue(b)[0])
    return min(turn, 360 - turn)


#: Dernier recours d'une série de données sur un fond de ton moyen : des gris, dont l'un des deux bouts passe toujours 3:1.
GREY_STEPS = tuple("#%02x%02x%02x" % (v, v, v) for v in (0x00, 0x22, 0x44, 0xcc, 0xee, 0xff))


def _series(palette: Palette) -> tuple[str, ...]:
    pool = [palette.accent, *([palette.accent_alt] if palette.accent_alt else []), palette.text,
            *(DARK_SERIES if _is_dark(palette.background) else LIGHT_SERIES), *GREY_STEPS]
    seen: list[str] = []
    for color in pool:
        if color not in seen and contrast_ratio(color, palette.background) >= GRAPHIC_RATIO:
            seen.append(color)
    return tuple(seen[:5])


def derive_from_signals(signals: DesignSignals) -> ArtDirectionProfile:
    """Un profil à partir de signaux déjà extraits. Provenance `inferred` : `palette`, `typography` et `shapes` le sont si des
    couleurs, des polices ou des rayons ont servi ; le reste est complété par l'archétype choisi sur les mentions (`generated`).
    Sans aucun signal exploitable : le repli (`fallback: true`). Jamais d'erreur sur des signaux valides : une palette qui
    échoue au contraste est réparée, et la réparation est dite dans `notes`."""

    if not isinstance(signals, DesignSignals):
        raise _fail("signals must be design signals")
    if not signals.usable:
        fallback = generate_fallback_profile(SeedContext())
        notes = (*fallback.provenance.notes[:2], "No usable design signal was extracted from the inspected sources.")
        return replace(fallback, provenance=replace(fallback.provenance, notes=notes), references=signals.sources)
    words = _words(" ".join(signals.mentions))
    archetype, accent, matched = choose_archetype(words, _digest(signals.to_dict()))
    spec = _SPECS[archetype]
    base = build_archetype_profile(archetype, accent, name="base", provenance=Provenance(Origin.GENERATED))
    palette, used_colors = _derive_palette(signals, base, spec.dark)

    typography = base.typography
    used_fonts = bool(signals.fonts)
    if used_fonts:
        heading = next((f for f in signals.fonts if f.role is FontRole.HEADING), signals.fonts[0])
        body = next((f for f in signals.fonts if f.role is FontRole.BODY),
                    signals.fonts[1] if len(signals.fonts) > 1 else heading)
        typography = replace(typography, heading=FontChoice(classify_family(heading.family), heading.family),
                             body=FontChoice(classify_family(body.family), body.family))
    shapes = base.shapes
    used_radii = bool(signals.radii_px)
    if used_radii:
        ordered = sorted(signals.radii_px)
        shapes = replace(shapes, radius_px=ordered[(len(ordered) - 1) // 2])

    sections: dict[str, Origin] = {s.value: Origin.GENERATED for s in Section}
    for used, section in ((used_colors, Section.PALETTE), (used_fonts, Section.TYPOGRAPHY), (used_radii, Section.SHAPES)):
        if used:
            sections[section.value] = Origin.INFERRED
    inferred = sum((used_colors, used_fonts, used_radii))
    confidence = min(0.85, 0.35 + 0.15 * inferred + (0.05 if signals.sources else 0))
    notes = (f"Derived from {len(signals.colors)} colour, {len(signals.fonts)} font, {len(signals.radii_px)} radius "
             f"and {len(signals.mentions)} mention signals.",
             f"Gaps filled with the generated '{spec.label}' direction ({'from the mentions' if matched else 'stable hash'}).")
    dataviz = replace(base.dataviz, series=_series(palette))
    return ArtDirectionProfile(
        "Derived direction", Provenance(Origin.INFERRED, sections, False, confidence, notes), palette, typography,
        base.spacing, shapes, base.imagery, dataviz, base.motion, signals.sources)
