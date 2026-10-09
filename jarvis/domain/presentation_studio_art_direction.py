"""Presentation Studio : le profil de direction artistique (`ArtDirectionProfile`) et son document stocké
(handoff jarvis-interactive-presentation-studio, Slice 09).

Une direction artistique (DA) est une **donnée structurée**, jamais du code : palette (dégradés compris),
typographie, espacement, formes, langage d'image, traitement des données, langage de mouvement, références et
provenance (fournie | inférée | générée). Contrat : `docs/presentation-studio.md` › *Art direction contract*.

Règles qui tiennent tout le module :

- **Aucun champ ne porte du CSS, du JS ou une URL.** Chaque valeur est un jeton validé : une couleur `#rrggbb`, un
  entier borné, un membre d'un vocabulaire **clos**. Le CSS n'est *produit* qu'ici, à partir de jetons déjà
  validés (`to_theme_variables`, `gradient_css`, `easing_css`) ; une chaîne reçue n'est jamais recopiée dans une
  valeur CSS. `url()`, `expression()`, `@import`, `var()`, `javascript:` ne sont refusés par aucune liste noire :
  ils ne sont tout simplement pas des couleurs, des entiers ni des membres d'un vocabulaire.
- **Le contraste est vérifié en chiffres** (ratio WCAG 2.x) à la construction : une palette illisible n'existe pas.
- **Le texte libre** (`name`, `notes`, `motifs`, titres de références) est une donnée non fiable : imprimable, borné,
  jamais interprété ni recopié dans une valeur CSS (`FREE_TEXT_FIELDS` classe chaque champ ; un test l'impose).
- Les références sont des `ResourceReference` `{kind, locator, title}` (réutilisées, hygiène de localisateur
  comprise) : un localisateur, jamais un contenu, jamais un dossier copié.
- Document strict : `schema` + `schema_version`, clé inconnue refusée, JSON canonique (jamais `==` pour comparer).

Pur : aucune E/S. La génération de repli, la divergence et la dérivation à partir de signaux sont dans
`presentation_studio_art_direction_authoring.py` (même contrat, mêmes types).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import math
import re
import unicodedata
from typing import Any, Protocol

from jarvis.domain.prefab import canonical_json
from jarvis.domain.presentation_studio import (
    ART_DIRECTION_ID, ART_DIRECTION_SCHEMA_VERSION, PRESENTATION_ID, SCHEMA_ART_DIRECTION, VARIANT_ID, PresentationVariant,
    _check_stamp, _percent_fixpoint, new_art_direction_id, resource_from_dict, resource_to_dict, stamp, upgrade_document,
)
from jarvis.domain.presentation_studio_checks import (
    PresentationStudioError, PresentationStudioErrorCode as C, _check_id, _check_int, _check_title, _exact_keys, _fail,
)
from jarvis.domain.presentation_working_set import ResourceReference

from jarvis.domain.presentation_studio_art_direction_vocab import *  # noqa: F401,F403 - the public vocabulary, re-exported


# ------------------------------------------------------------------ références

#: Un localisateur de DA est une **référence** (hygiène de `resource_from_dict` : schéma sur liste blanche, pas de `..`, d'UNC,
#: de caractère de contrôle). La DA y ajoute, par défense en profondeur, le refus de ce qui a la *forme* d'une injection
#: CSS/JS ou de gabarit, au cas où un jour quelqu'un interpolerait une référence dans un style : une fonction CSS (`url(`,
#: `expression(`, `var(`, `calc(`, `attr(`, `image-set(`, `env(` en début de mot), `@import`, un schéma exécutable
#: (`javascript:`, `vbscript:` en début de mot), et `< > { } " \``, bruts ou décodés en pourcentage. Ni `;`, ni `'`, ni
#: `data:` au milieu d'un mot (`metadata:v2`) : ce sont des localisateurs légitimes, et ils ne forment pas une injection.
_INJECTION_SHAPE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:url|expression|var|calc|attr|image-set|env)\s*\(|@import|"
    r"(?<![A-Za-z0-9])(?:javascript|vbscript)\s*:|[<>{}\"`]", re.I)


def check_reference(where: str, reference: ResourceReference) -> None:
    decoded = _percent_fixpoint(reference.locator)
    for text in (reference.locator, decoded or ""):
        found = _INJECTION_SHAPE.search(unicodedata.normalize("NFKC", text))
        if found:
            raise _fail(f"{where}.locator has the shape of CSS, script or template injection ({found.group(0)[:12]!r}): "
                        "a reference is a plain locator")


# ------------------------------------------------------------------ palette


@dataclass(frozen=True, slots=True)
class GradientStop:
    color: str
    at: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "color", parse_color("gradient stop color", self.color))
        _check_int("gradient stop at", self.at, 0, 100)

    def to_dict(self) -> dict[str, Any]:
        return {"color": self.color, "at": self.at}

    @classmethod
    def from_dict(cls, raw: object, where: str) -> GradientStop:
        data = _exact_keys(raw, where, {"color", "at"})
        return cls(data["color"], data["at"])


@dataclass(frozen=True, slots=True)
class Gradient:
    gradient_id: str
    kind: GradientKind
    angle: int
    stops: tuple[GradientStop, ...]
    text_token: TextToken

    def __post_init__(self) -> None:
        parse_slug("gradient_id", self.gradient_id)
        object.__setattr__(self, "kind", parse_enum(GradientKind, "gradient kind", self.kind))
        object.__setattr__(self, "text_token", parse_enum(TextToken, "gradient text_token", self.text_token))
        _check_int("gradient angle", self.angle, 0, 359)
        if self.kind is GradientKind.RADIAL and self.angle != 0:
            raise _fail("a radial gradient has angle 0")
        stops = parse_list("gradient stops", self.stops, MAX_STOPS, MIN_STOPS)
        if not all(isinstance(s, GradientStop) for s in stops):
            raise _fail("gradient stops must be stops")
        if any(a.at >= b.at for a, b in zip(stops, stops[1:])):
            raise _fail("gradient stops must strictly increase in position")
        object.__setattr__(self, "stops", stops)

    def samples(self) -> list[tuple[int, str]]:
        """`(position %, couleur)` le long de la rampe **telle que rendue** (interpolation linéaire en sRGB entre deux arrêts
        voisins) : chaque arrêt et `GRADIENT_SEGMENT_STEPS` pas par segment. La luminance est convexe le long d'une droite sRGB,
        son minimum peut tomber entre deux arrêts : c'est pour cela que le contraste se mesure ici et pas aux seuls arrêts."""

        out: dict[int, str] = {}
        for a, b in zip(self.stops, self.stops[1:]):
            ra, rb = rgb_of(a.color), rgb_of(b.color)
            for k in range(GRADIENT_SEGMENT_STEPS + 1):
                t = k / GRADIENT_SEGMENT_STEPS
                out.setdefault(round(a.at + (b.at - a.at) * t), hex_of(tuple(round(ra[i] + (rb[i] - ra[i]) * t) for i in range(3))))  # type: ignore[arg-type]
            out[a.at], out[b.at] = a.color, b.color
        return sorted(out.items())

    def to_dict(self) -> dict[str, Any]:
        return {"gradient_id": self.gradient_id, "kind": self.kind.value, "angle": self.angle,
                "stops": [s.to_dict() for s in self.stops], "text_token": self.text_token.value}

    @classmethod
    def from_dict(cls, raw: object, where: str) -> Gradient:
        data = _exact_keys(raw, where, {"gradient_id", "kind", "angle", "stops", "text_token"})
        stops = tuple(GradientStop.from_dict(s, f"{where}.stops[{n}]")
                      for n, s in enumerate(parse_list(f"{where}.stops", data["stops"], MAX_STOPS, MIN_STOPS)))
        return cls(data["gradient_id"], data["kind"], data["angle"], stops, data["text_token"])


def gradient_css(gradient: Gradient) -> str:
    """`linear-gradient(135deg, #aabbcc 0%, ...)` : fabriqué **uniquement** à partir de jetons déjà validés."""

    stops = ", ".join(f"{s.color} {s.at}%" for s in gradient.stops)
    if gradient.kind is GradientKind.RADIAL:
        return f"radial-gradient(circle, {stops})"
    return f"linear-gradient({gradient.angle}deg, {stops})"


def easing_css(easing: Easing) -> str:
    return EASING_CSS[parse_enum(Easing, "easing", easing)]


@dataclass(frozen=True, slots=True)
class Palette:
    background: str
    surface: str
    surface_opacity: int
    text: str
    muted: str
    accent: str
    accent_alt: str | None
    gradients: tuple[Gradient, ...]

    def __post_init__(self) -> None:
        for name in ("background", "surface", "text", "muted", "accent"):
            object.__setattr__(self, name, parse_color(f"palette.{name}", getattr(self, name)))
        if self.accent_alt is not None:
            object.__setattr__(self, "accent_alt", parse_color("palette.accent_alt", self.accent_alt))
        _check_int("palette.surface_opacity", self.surface_opacity, MIN_SURFACE_OPACITY, MAX_SURFACE_OPACITY)
        gradients = parse_list("palette.gradients", self.gradients, MAX_GRADIENTS)
        if not all(isinstance(g, Gradient) for g in gradients):
            raise _fail("palette.gradients must be gradients")
        if len({g.gradient_id for g in gradients}) != len(gradients):
            raise _fail("palette.gradients hold the same gradient_id twice")
        object.__setattr__(self, "gradients", gradients)
        failing = [row for row in self.contrast_report() if not row["ok"]]
        if failing:
            row = failing[0]
            raise _fail(f"palette contrast too low: {row['pair']} is {row['ratio']:.2f}:1, needs {row['required']}:1")

    def effective_surface(self) -> str:
        """La couleur réellement vue d'une surface : posée à son opacité sur le fond."""

        return blend(self.surface, self.background, self.surface_opacity / 100)

    def token(self, name: str) -> str:
        return {"text": self.text, "background": self.background}[name]

    def contrast_report(self) -> list[dict[str, Any]]:
        """Chaque paire texte/fond contrôlée, avec son ratio mesuré et son seuil. Une paire est `ok` si ratio >= seuil."""

        surface = self.effective_surface()
        pairs: list[tuple[str, str, str, float]] = [
            ("text on background", self.text, self.background, TEXT_RATIO),
            ("text on surface", self.text, surface, TEXT_RATIO),
            ("muted on background", self.muted, self.background, SECONDARY_RATIO),
            ("muted on surface", self.muted, surface, SECONDARY_RATIO),
            ("accent on background", self.accent, self.background, GRAPHIC_RATIO),
            ("accent on surface", self.accent, surface, GRAPHIC_RATIO),
            # `--jv-wash` is the text colour at 9% over what is behind it: the background of a button or a chip.
            ("text on wash", self.text, blend(self.text, self.background, WASH_OPACITY), TEXT_RATIO),
            ("text on wash over surface", self.text, blend(self.text, surface, WASH_OPACITY), TEXT_RATIO),
        ]
        if self.accent_alt is not None:
            pairs.append(("accent_alt on background", self.accent_alt, self.background, GRAPHIC_RATIO))
            pairs.append(("accent_alt on surface", self.accent_alt, surface, GRAPHIC_RATIO))
        for gradient in self.gradients:
            for position, color in gradient.samples():
                pairs.append((f"{gradient.text_token.value} on gradient {gradient.gradient_id} at {position}%",
                              self.token(gradient.text_token.value), color, TEXT_RATIO))
        return [{"pair": name, "foreground": fg, "background": bg, "ratio": (ratio := contrast_ratio(fg, bg)),
                 "required": required, "ok": ratio >= required} for name, fg, bg, required in pairs]

    def to_dict(self) -> dict[str, Any]:
        return {"background": self.background, "surface": self.surface, "surface_opacity": self.surface_opacity,
                "text": self.text, "muted": self.muted, "accent": self.accent, "accent_alt": self.accent_alt,
                "gradients": [g.to_dict() for g in self.gradients]}

    @classmethod
    def from_dict(cls, raw: object, where: str = "palette") -> Palette:
        data = _exact_keys(raw, where, {"background", "surface", "surface_opacity", "text", "muted", "accent",
                                        "accent_alt", "gradients"})
        gradients = tuple(Gradient.from_dict(g, f"{where}.gradients[{n}]")
                          for n, g in enumerate(parse_list(f"{where}.gradients", data["gradients"], MAX_GRADIENTS)))
        return cls(data["background"], data["surface"], data["surface_opacity"], data["text"], data["muted"],
                   data["accent"], data["accent_alt"], gradients)


# ------------------------------------------------------------------ typographie


@dataclass(frozen=True, slots=True)
class FontChoice:
    """Une pile système fermée et, en option, une famille **déclarée** (lettres, chiffres, espace, tiret) qui passe en premier."""

    stack: FontStack
    preferred: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stack", parse_enum(FontStack, "font stack", self.stack))
        if self.preferred is not None:
            value = self.preferred
            if (not isinstance(value, str) or len(value) > MAX_FAMILY_CHARS or not value.isascii()
                    or not FAMILY_NAME.fullmatch(value)):
                raise _fail("a preferred font family is a plain name: letters, digits, single spaces or hyphens "
                            f"(at most {MAX_FAMILY_CHARS} characters)")

    def css(self) -> str:
        """Pile CSS : la famille déclarée entre guillemets (caractères restreints, donc inerte) puis la pile fermée."""

        base = FONT_STACK_CSS[self.stack]
        return f'"{self.preferred}", {base}' if self.preferred else base

    def to_dict(self) -> dict[str, Any]:
        return {"stack": self.stack.value, "preferred": self.preferred}

    @classmethod
    def from_dict(cls, raw: object, where: str) -> FontChoice:
        data = _exact_keys(raw, where, {"stack", "preferred"})
        return cls(data["stack"], data["preferred"])


@dataclass(frozen=True, slots=True)
class Typography:
    heading: FontChoice
    body: FontChoice
    text_size: TextSize
    scale_ratio: ScaleRatio
    heading_weight: int
    body_weight: int
    label_case: LabelCase

    def __post_init__(self) -> None:
        if not isinstance(self.heading, FontChoice) or not isinstance(self.body, FontChoice):
            raise _fail("typography heading and body must be font choices")
        object.__setattr__(self, "text_size", parse_enum(TextSize, "typography.text_size", self.text_size))
        object.__setattr__(self, "scale_ratio", parse_enum(ScaleRatio, "typography.scale_ratio", self.scale_ratio))
        object.__setattr__(self, "label_case", parse_enum(LabelCase, "typography.label_case", self.label_case))
        parse_choice("typography.heading_weight", self.heading_weight, HEADING_WEIGHTS)
        parse_choice("typography.body_weight", self.body_weight, BODY_WEIGHTS)

    def to_dict(self) -> dict[str, Any]:
        return {"heading": self.heading.to_dict(), "body": self.body.to_dict(), "text_size": self.text_size.value,
                "scale_ratio": self.scale_ratio.value, "heading_weight": self.heading_weight,
                "body_weight": self.body_weight, "label_case": self.label_case.value}

    @classmethod
    def from_dict(cls, raw: object, where: str = "typography") -> Typography:
        data = _exact_keys(raw, where, {"heading", "body", "text_size", "scale_ratio", "heading_weight",
                                        "body_weight", "label_case"})
        return cls(FontChoice.from_dict(data["heading"], f"{where}.heading"),
                   FontChoice.from_dict(data["body"], f"{where}.body"), data["text_size"], data["scale_ratio"],
                   data["heading_weight"], data["body_weight"], data["label_case"])


# ------------------------------------------------------------------ espacement, formes, image, données, mouvement


@dataclass(frozen=True, slots=True)
class Spacing:
    density: Density
    margin: Margin

    def __post_init__(self) -> None:
        object.__setattr__(self, "density", parse_enum(Density, "spacing.density", self.density))
        object.__setattr__(self, "margin", parse_enum(Margin, "spacing.margin", self.margin))

    def to_dict(self) -> dict[str, Any]:
        return {"density": self.density.value, "margin": self.margin.value}

    @classmethod
    def from_dict(cls, raw: object, where: str = "spacing") -> Spacing:
        data = _exact_keys(raw, where, {"density", "margin"})
        return cls(data["density"], data["margin"])


@dataclass(frozen=True, slots=True)
class Shapes:
    radius_px: int
    stroke_px: int
    elevation: Elevation

    def __post_init__(self) -> None:
        _check_int("shapes.radius_px", self.radius_px, 0, MAX_RADIUS_PX)
        _check_int("shapes.stroke_px", self.stroke_px, 0, MAX_STROKE_PX)
        object.__setattr__(self, "elevation", parse_enum(Elevation, "shapes.elevation", self.elevation))

    def to_dict(self) -> dict[str, Any]:
        return {"radius_px": self.radius_px, "stroke_px": self.stroke_px, "elevation": self.elevation.value}

    @classmethod
    def from_dict(cls, raw: object, where: str = "shapes") -> Shapes:
        data = _exact_keys(raw, where, {"radius_px", "stroke_px", "elevation"})
        return cls(data["radius_px"], data["stroke_px"], data["elevation"])


@dataclass(frozen=True, slots=True)
class Imagery:
    photo: PhotoStyle
    illustration: IllustrationStyle
    icons: IconStyle
    treatment: ImageTreatment
    motifs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "photo", parse_enum(PhotoStyle, "imagery.photo", self.photo))
        object.__setattr__(self, "illustration", parse_enum(IllustrationStyle, "imagery.illustration", self.illustration))
        object.__setattr__(self, "icons", parse_enum(IconStyle, "imagery.icons", self.icons))
        object.__setattr__(self, "treatment", parse_enum(ImageTreatment, "imagery.treatment", self.treatment))
        motifs = tuple(parse_line("imagery.motifs[]", m, MAX_MOTIF_CHARS) for m in parse_list("imagery.motifs", self.motifs, MAX_MOTIFS))
        if len(set(motifs)) != len(motifs):
            raise _fail("imagery.motifs hold the same motif twice")
        object.__setattr__(self, "motifs", motifs)

    def to_dict(self) -> dict[str, Any]:
        return {"photo": self.photo.value, "illustration": self.illustration.value, "icons": self.icons.value,
                "treatment": self.treatment.value, "motifs": list(self.motifs)}

    @classmethod
    def from_dict(cls, raw: object, where: str = "imagery") -> Imagery:
        data = _exact_keys(raw, where, {"photo", "illustration", "icons", "treatment", "motifs"})
        return cls(data["photo"], data["illustration"], data["icons"], data["treatment"], data["motifs"])


@dataclass(frozen=True, slots=True)
class DataViz:
    mode: SeriesMode
    series: tuple[str, ...]
    grid: GridStyle
    labels: LabelPlacement
    emphasis: Emphasis

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", parse_enum(SeriesMode, "dataviz.mode", self.mode))
        object.__setattr__(self, "grid", parse_enum(GridStyle, "dataviz.grid", self.grid))
        object.__setattr__(self, "labels", parse_enum(LabelPlacement, "dataviz.labels", self.labels))
        object.__setattr__(self, "emphasis", parse_enum(Emphasis, "dataviz.emphasis", self.emphasis))
        series = tuple(parse_color("dataviz.series[]", c) for c in parse_list("dataviz.series", self.series, MAX_SERIES, MIN_SERIES))
        if len(set(series)) != len(series):
            raise _fail("dataviz.series hold the same colour twice")
        object.__setattr__(self, "series", series)

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "series": list(self.series), "grid": self.grid.value,
                "labels": self.labels.value, "emphasis": self.emphasis.value}

    @classmethod
    def from_dict(cls, raw: object, where: str = "dataviz") -> DataViz:
        data = _exact_keys(raw, where, {"mode", "series", "grid", "labels", "emphasis"})
        return cls(data["mode"], data["series"], data["grid"], data["labels"], data["emphasis"])


@dataclass(frozen=True, slots=True)
class Motion:
    tempo: Tempo
    enter_ms: int
    exit_ms: int
    emphasis_ms: int
    easing: Easing
    stagger_ms: int
    transition: TransitionStyle
    reduced_motion: ReducedMotion

    def __post_init__(self) -> None:
        object.__setattr__(self, "tempo", parse_enum(Tempo, "motion.tempo", self.tempo))
        object.__setattr__(self, "easing", parse_enum(Easing, "motion.easing", self.easing))
        object.__setattr__(self, "transition", parse_enum(TransitionStyle, "motion.transition", self.transition))
        object.__setattr__(self, "reduced_motion", parse_enum(ReducedMotion, "motion.reduced_motion", self.reduced_motion))
        for name in ("enter_ms", "exit_ms", "emphasis_ms"):
            parse_choice(f"motion.{name}", getattr(self, name), DURATIONS_MS)
        parse_choice("motion.stagger_ms", self.stagger_ms, STAGGERS_MS)

    def to_dict(self) -> dict[str, Any]:
        return {"tempo": self.tempo.value, "enter_ms": self.enter_ms, "exit_ms": self.exit_ms,
                "emphasis_ms": self.emphasis_ms, "easing": self.easing.value, "stagger_ms": self.stagger_ms,
                "transition": self.transition.value, "reduced_motion": self.reduced_motion.value}

    @classmethod
    def from_dict(cls, raw: object, where: str = "motion") -> Motion:
        data = _exact_keys(raw, where, {"tempo", "enter_ms", "exit_ms", "emphasis_ms", "easing", "stagger_ms",
                                        "transition", "reduced_motion"})
        return cls(data["tempo"], data["enter_ms"], data["exit_ms"], data["emphasis_ms"], data["easing"],
                   data["stagger_ms"], data["transition"], data["reduced_motion"])


# ------------------------------------------------------------------ provenance


@dataclass(frozen=True, slots=True)
class Provenance:
    """D'où vient la DA. `origin` vaut pour tout le profil ; `sections` en précise une partie. `fallback` : générée faute de mieux."""

    origin: Origin
    sections: Mapping[str, Origin] = field(default_factory=dict)
    fallback: bool = False
    confidence: float = 1.0
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", parse_enum(Origin, "provenance.origin", self.origin))
        if not isinstance(self.sections, Mapping):
            raise _fail("provenance.sections must be an object")
        sections = {parse_enum(Section, "provenance.sections key", key).value: parse_enum(Origin, "provenance.sections value", value)
                    for key, value in self.sections.items()}
        object.__setattr__(self, "sections", dict(sorted(sections.items())))
        parse_bool("provenance.fallback", self.fallback)
        if self.fallback and self.origin is not Origin.GENERATED:
            raise _fail("a fallback profile is generated: provenance.origin must be generated")
        if (isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float))
                or not math.isfinite(float(self.confidence)) or not 0.0 <= float(self.confidence) <= 1.0):
            raise _fail("provenance.confidence must be a finite number between 0 and 1")
        object.__setattr__(self, "confidence", round(float(self.confidence), 3))
        notes = tuple(parse_line("provenance.notes[]", n, MAX_NOTE_CHARS) for n in parse_list("provenance.notes", self.notes, MAX_NOTES))
        object.__setattr__(self, "notes", notes)

    def origin_of(self, section: Section) -> Origin:
        return self.sections.get(section.value, self.origin)

    def to_dict(self) -> dict[str, Any]:
        return {"origin": self.origin.value, "sections": {k: v.value for k, v in self.sections.items()},
                "fallback": self.fallback, "confidence": self.confidence, "notes": list(self.notes)}

    @classmethod
    def from_dict(cls, raw: object, where: str = "provenance") -> Provenance:
        data = _exact_keys(raw, where, {"origin", "sections", "fallback", "confidence", "notes"})
        if not isinstance(data["sections"], dict):
            raise _fail(f"{where}.sections must be an object")
        return cls(data["origin"], data["sections"], data["fallback"], data["confidence"], data["notes"])


# ------------------------------------------------------------------ profil

#: Les thèmes que l'hôte de prefab connaît (`shim.js` `THEME_VARS`) : le seul canal de la DA vers un cadre.
HOST_THEME_KEYS = ("accent", "text", "muted", "surface", "scale")
#: Les seules variables `--jv-*` que la DA écrit. Tout y est du **jeton** (couleur, nombre, pile fermée) : aucune
#: n'est un nouveau point d'exécution. Un test vérifie que chacune est déclarée dans `shell.css`.
ALLOWED_THEME_VARIABLES = frozenset({
    "--jv-accent", "--jv-text", "--jv-muted", "--jv-surface", "--jv-scale", "--jv-font", "--jv-radius", "--jv-gap",
    "--jv-ground", "--jv-veil", "--jv-title", "--jv-link", "--jv-body", "--jv-edge", "--jv-wash",
})

PROFILE_KEYS = ("name", "provenance", "palette", "typography", "spacing", "shapes", "imagery", "dataviz", "motion",
                "references")


@dataclass(frozen=True, slots=True)
class ArtDirectionProfile:
    name: str
    provenance: Provenance
    palette: Palette
    typography: Typography
    spacing: Spacing
    shapes: Shapes
    imagery: Imagery
    dataviz: DataViz
    motion: Motion
    references: tuple[ResourceReference, ...] = ()

    def __post_init__(self) -> None:
        _check_title("name", self.name)
        for key, kind in (("provenance", Provenance), ("palette", Palette), ("typography", Typography),
                          ("spacing", Spacing), ("shapes", Shapes), ("imagery", Imagery), ("dataviz", DataViz),
                          ("motion", Motion)):
            if not isinstance(getattr(self, key), kind):
                raise _fail(f"{key} must be a {kind.__name__}")
        references = parse_list("references", self.references, MAX_REFERENCES)
        if not all(isinstance(r, ResourceReference) for r in references):
            raise _fail("references must be resource references")
        if len({(r.kind, r.locator) for r in references}) != len(references):
            raise _fail("references hold the same reference twice")
        for n, reference in enumerate(references):
            check_reference(f"references[{n}]", reference)
        object.__setattr__(self, "references", references)
        low = [c for c in self.dataviz.series if contrast_ratio(c, self.palette.background) < GRAPHIC_RATIO]
        if low:
            raise _fail(f"dataviz.series colour {low[0]} has less than {GRAPHIC_RATIO}:1 contrast on the background")

    # -- thème : la seule sortie « CSS », construite à partir de jetons validés ---------------------------------

    def to_theme(self) -> dict[str, Any]:
        """Le `theme` que l'hôte de prefab applique déjà (`HOST_THEME_KEYS`) : `host.update`, sans nouveau canal."""

        p = self.palette
        r, g, b = rgb_of(p.surface)
        return {"accent": p.accent, "text": p.text, "muted": p.muted,
                "surface": f"rgba({r},{g},{b},{p.surface_opacity / 100:.2f})",
                "scale": TEXT_SCALE[self.typography.text_size]}

    def to_theme_variables(self) -> dict[str, str]:
        """Variables `--jv-*` de la coquille des prefabs, **uniquement** `ALLOWED_THEME_VARIABLES`. Les valeurs sont des
        couleurs `#rrggbb` / `rgba(n,n,n,0.nn)`, des nombres, des longueurs en px et une pile de police fermée ; aucun
        champ de texte libre n'y entre. Déterministe : le même profil donne les mêmes variables."""

        p, t = self.palette, self.typography
        tr, tg, tb = rgb_of(p.text)
        br, bg_, bb = rgb_of(p.background)
        soft = blend(p.text, p.background, 0.85)
        theme = self.to_theme()
        variables = {
            "--jv-accent": theme["accent"], "--jv-text": theme["text"], "--jv-muted": theme["muted"],
            "--jv-surface": theme["surface"], "--jv-scale": f"{theme['scale']:g}",
            "--jv-font": t.body.css(), "--jv-radius": f"{self.shapes.radius_px}px",
            "--jv-gap": f"{DENSITY_GAP_PX[self.spacing.density]}px",
            "--jv-ground": p.background, "--jv-veil": f"rgba({br},{bg_},{bb},0.97)",
            "--jv-title": p.text, "--jv-link": p.text,
            "--jv-body": soft if contrast_ratio(soft, p.background) >= TEXT_RATIO else p.text,
            "--jv-edge": f"rgba({tr},{tg},{tb},0.16)", "--jv-wash": f"rgba({tr},{tg},{tb},0.09)",
        }
        return variables  # exactly ALLOWED_THEME_VARIABLES: pinned by a test, not by a production assert

    # -- document -----------------------------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "provenance": self.provenance.to_dict(), "palette": self.palette.to_dict(),
                "typography": self.typography.to_dict(), "spacing": self.spacing.to_dict(),
                "shapes": self.shapes.to_dict(), "imagery": self.imagery.to_dict(), "dataviz": self.dataviz.to_dict(),
                "motion": self.motion.to_dict(), "references": [resource_to_dict(r) for r in self.references]}

    def canonical(self) -> str:
        """JSON canonique (clés triées) : l'identité de contenu d'un profil, pour comparer sans `==`."""

        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, raw: object, where: str = "profile") -> ArtDirectionProfile:
        data = _exact_keys(raw, where, set(PROFILE_KEYS))
        refs = tuple(resource_from_dict(r, f"{where}.references[{n}]")
                     for n, r in enumerate(parse_list(f"{where}.references", data["references"], MAX_REFERENCES)))
        return cls(data["name"], Provenance.from_dict(data["provenance"], f"{where}.provenance"),
                   Palette.from_dict(data["palette"], f"{where}.palette"),
                   Typography.from_dict(data["typography"], f"{where}.typography"),
                   Spacing.from_dict(data["spacing"], f"{where}.spacing"),
                   Shapes.from_dict(data["shapes"], f"{where}.shapes"),
                   Imagery.from_dict(data["imagery"], f"{where}.imagery"),
                   DataViz.from_dict(data["dataviz"], f"{where}.dataviz"),
                   Motion.from_dict(data["motion"], f"{where}.motion"), refs)


def parse_profile(raw: object) -> ArtDirectionProfile:
    """Corps ou document -> profil. Clé inconnue, valeur hors vocabulaire ou contraste insuffisant : refus nommé."""

    return ArtDirectionProfile.from_dict(raw)


#: Classement de **chaque** champ du modèle (un test échoue si un champ n'est pas classé, quelle que soit son annotation).
#: Les champs de texte libre sont les seuls à porter une chaîne arbitraire ; aucun n'est jamais interprété.
FREE_TEXT_FIELDS = frozenset({"name", "notes", "motifs", "title"})
ID_FIELDS = frozenset({"gradient_id"})
#: Couleurs (`#rrggbb`), familles déclarées (nom simple), localisateurs de référence : jetons contraints par motif.
TOKEN_FIELDS = frozenset({
    "background", "surface", "text", "muted", "accent", "accent_alt", "series", "color", "preferred", "locator"})
#: Entiers, drapeaux, nombres, énumérations clos et structures imbriquées.
STRUCTURE_FIELDS = frozenset({
    "at", "angle", "kind", "stops", "text_token", "surface_opacity", "gradients", "stack", "heading", "body",
    "text_size", "scale_ratio", "heading_weight", "body_weight", "label_case", "density", "margin", "radius_px",
    "stroke_px", "elevation", "photo", "illustration", "icons", "treatment", "mode", "grid", "labels", "emphasis",
    "tempo", "enter_ms", "exit_ms", "emphasis_ms", "easing", "stagger_ms", "transition", "reduced_motion", "origin",
    "sections", "fallback", "confidence", "provenance", "palette", "typography", "spacing", "shapes", "imagery",
    "dataviz", "motion", "references"})

MODEL_CLASSES = (GradientStop, Gradient, Palette, FontChoice, Typography, Spacing, Shapes, Imagery, DataViz, Motion,
                 Provenance, ArtDirectionProfile)


# ------------------------------------------------------------------ document stocké


@dataclass(frozen=True, slots=True)
class ArtDirection:
    """Le document `art_directions/<art_direction_id>.json` : un profil, sa variante, sa révision propre."""

    art_direction_id: str
    presentation_id: str
    variant_id: str
    profile: ArtDirectionProfile
    revision: int
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        _check_id("art_direction_id", self.art_direction_id, ART_DIRECTION_ID)
        _check_id("presentation_id", self.presentation_id, PRESENTATION_ID)
        _check_id("variant_id", self.variant_id, VARIANT_ID)
        if not isinstance(self.profile, ArtDirectionProfile):
            raise _fail("profile must be an art direction profile")
        _check_int("revision", self.revision, 1, 2**31 - 1)
        _check_stamp("created_at", self.created_at)
        _check_stamp("updated_at", self.updated_at)

    def to_document(self) -> dict[str, Any]:
        return {"schema": SCHEMA_ART_DIRECTION, "schema_version": ART_DIRECTION_SCHEMA_VERSION,
                "art_direction_id": self.art_direction_id, "presentation_id": self.presentation_id,
                "variant_id": self.variant_id, "profile": self.profile.to_dict(), "revision": self.revision,
                "created_at": self.created_at, "updated_at": self.updated_at}

    def canonical(self) -> str:
        return canonical_json(self.to_document())


def parse_art_direction(raw: object) -> ArtDirection:
    """Document au format disque -> `ArtDirection`. Version plus récente : refus ; clé inconnue : refus."""

    data = _exact_keys(upgrade_document(raw, SCHEMA_ART_DIRECTION), "art direction",
                       {"schema", "schema_version", "art_direction_id", "presentation_id", "variant_id", "profile",
                        "revision", "created_at", "updated_at"})
    return ArtDirection(data["art_direction_id"], data["presentation_id"], data["variant_id"],
                        parse_profile(data["profile"]), data["revision"], data["created_at"], data["updated_at"])


@dataclass(frozen=True, slots=True)
class ArtDirectionCreate:
    """Corps d'un `POST` : `expected_variant_revision` (la variante reçoit son `art_direction_id`) + le profil."""

    expected_variant_revision: int
    profile: ArtDirectionProfile


@dataclass(frozen=True, slots=True)
class ArtDirectionUpdate:
    expected_revision: int
    profile: ArtDirectionProfile


def parse_art_direction_create(raw: object) -> ArtDirectionCreate:
    data = _exact_keys(raw, "art direction create", {"expected_variant_revision", "profile"})
    _check_int("expected_variant_revision", data["expected_variant_revision"], 1, 2**31 - 1)
    return ArtDirectionCreate(data["expected_variant_revision"], parse_profile(data["profile"]))


def parse_art_direction_update(raw: object) -> ArtDirectionUpdate:
    data = _exact_keys(raw, "art direction update", {"expected_revision", "profile"})
    _check_int("expected_revision", data["expected_revision"], 1, 2**31 - 1)
    return ArtDirectionUpdate(data["expected_revision"], parse_profile(data["profile"]))


def new_art_direction_document(presentation_id: str, variant_id: str, profile: ArtDirectionProfile, now: Any, *,
                               art_direction_id: str | None = None) -> ArtDirection:
    at = stamp(now)
    return ArtDirection(art_direction_id or new_art_direction_id(), presentation_id, variant_id, profile, 1, at, at)


# ------------------------------------------------------------------ « chaque variante sérieuse résout une DA »


class ArtDirectionLookup(Protocol):
    """Ce que `require_art_direction` demande au magasin de profils : un document ou `None` (fichier absent)."""

    def find(self, presentation_id: str, art_direction_id: str) -> ArtDirection | None: ...


class Resolution(StrEnum):
    RESOLVED = "resolved"
    #: Variante exploratoire sans DA : permis (brouillon, candidats plus légers).
    MISSING = "missing"
    #: Variante exploratoire dont `art_direction_id` ne se résout plus : signalé, pas bloquant.
    DANGLING = "dangling"


@dataclass(frozen=True, slots=True)
class ArtDirectionResolution:
    status: Resolution
    art_direction: ArtDirection | None

    @property
    def is_fallback(self) -> bool:
        return self.art_direction is not None and self.art_direction.profile.provenance.fallback


def require_art_direction(variant: PresentationVariant, profile_store: ArtDirectionLookup, serious: bool = True) -> ArtDirectionResolution:
    """Une variante **sérieuse ou générée** résout une DA, sinon refus nommé ; un brouillon **exploratoire** peut n'en
    avoir aucune.

    | variante | `art_direction_id` | `serious=True` | `serious=False` |
    | --- | --- | --- | --- |
    | résolue | présent, document trouvé | `resolved` | `resolved` |
    | sans DA | `None` | refus `art_direction_required` | `missing` |
    | lien rompu | présent, document absent | refus `unknown_art_direction` | `dangling` |

    Une DA de repli (`provenance.fallback`) est une DA : elle résout, et `is_fallback` le dit (origine inspectable).
    Un document qui nomme une autre variante ou Presentation est une panne de données (`corrupt_document`).
    """

    if type(serious) is not bool:
        raise _fail("serious must be a boolean")
    art_direction_id = variant.art_direction_id
    if art_direction_id is None:
        if serious:
            raise PresentationStudioError(
                C.ART_DIRECTION_REQUIRED,
                f"variant {variant.variant_id} has no art direction: a serious or generated variant needs one "
                "(create it, or ask for the generated fallback)")
        return ArtDirectionResolution(Resolution.MISSING, None)
    found = profile_store.find(variant.presentation_id, art_direction_id)
    if found is None:
        if serious:
            raise PresentationStudioError(
                C.UNKNOWN_ART_DIRECTION,
                f"variant {variant.variant_id} names art direction {art_direction_id} but its file is absent: create it again")
        return ArtDirectionResolution(Resolution.DANGLING, None)
    if (found.art_direction_id, found.presentation_id, found.variant_id) != (
            art_direction_id, variant.presentation_id, variant.variant_id):
        raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{art_direction_id}: file names another art direction, variant or presentation")
    return ArtDirectionResolution(Resolution.RESOLVED, found)
