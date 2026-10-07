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

# ------------------------------------------------------------------ bornes

MAX_GRADIENTS = 6
MIN_STOPS, MAX_STOPS = 2, 5
MIN_SERIES, MAX_SERIES = 3, 8
MAX_REFERENCES = 12
MAX_NOTES = 8
MAX_NOTE_CHARS = 200
MAX_MOTIFS = 6
MAX_MOTIF_CHARS = 40
MAX_FAMILY_CHARS = 40
MAX_RADIUS_PX = 48
MAX_STROKE_PX = 6
MIN_SURFACE_OPACITY, MAX_SURFACE_OPACITY = 30, 100

#: Seuils de contraste (WCAG 2.x) : texte courant 4.5, texte secondaire et éléments graphiques 3.0.
TEXT_RATIO = 4.5
SECONDARY_RATIO = 3.0
GRAPHIC_RATIO = 3.0

_SLUG = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
_HEX = re.compile(r"#[0-9A-Fa-f]{6}\Z")
_FAMILY = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[ -][A-Za-z0-9]+)*\Z")


# ------------------------------------------------------------------ vocabulaires clos


class Origin(StrEnum):
    PROVIDED = "provided"
    INFERRED = "inferred"
    GENERATED = "generated"


class Section(StrEnum):
    """Les parties d'un profil qui peuvent porter leur propre provenance."""

    PALETTE = "palette"
    TYPOGRAPHY = "typography"
    SPACING = "spacing"
    SHAPES = "shapes"
    IMAGERY = "imagery"
    DATAVIZ = "dataviz"
    MOTION = "motion"


class GradientKind(StrEnum):
    LINEAR = "linear"
    RADIAL = "radial"


class FontStack(StrEnum):
    """Piles **système** uniquement : le cadre n'a ni réseau ni police embarquée (CSP `font-src data:`)."""

    SYSTEM_SANS = "system_sans"
    HUMANIST_SANS = "humanist_sans"
    GEOMETRIC_SANS = "geometric_sans"
    ROUNDED_SANS = "rounded_sans"
    CONDENSED_SANS = "condensed_sans"
    TRANSITIONAL_SERIF = "transitional_serif"
    OLD_STYLE_SERIF = "old_style_serif"
    SLAB_SERIF = "slab_serif"
    SYSTEM_MONO = "system_mono"


#: Texte CSS de chaque pile : des **constantes** de ce module, jamais une valeur reçue.
FONT_STACK_CSS: Mapping[FontStack, str] = {
    FontStack.SYSTEM_SANS: 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    FontStack.HUMANIST_SANS: '"Segoe UI", "Helvetica Neue", Calibri, Candara, sans-serif',
    FontStack.GEOMETRIC_SANS: '"Century Gothic", "Avenir Next", Futura, "Trebuchet MS", sans-serif',
    FontStack.ROUNDED_SANS: '"Arial Rounded MT Bold", "Varela Round", "Trebuchet MS", sans-serif',
    FontStack.CONDENSED_SANS: '"Arial Narrow", "Roboto Condensed", "Helvetica Neue", sans-serif',
    FontStack.TRANSITIONAL_SERIF: 'Georgia, "Times New Roman", Times, serif',
    FontStack.OLD_STYLE_SERIF: '"Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif',
    FontStack.SLAB_SERIF: 'Rockwell, "Courier New", Georgia, serif',
    FontStack.SYSTEM_MONO: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
}


class FontClass(StrEnum):
    SANS = "sans"
    SERIF = "serif"
    MONO = "mono"


FONT_CLASS: Mapping[FontStack, FontClass] = {
    FontStack.SYSTEM_SANS: FontClass.SANS, FontStack.HUMANIST_SANS: FontClass.SANS,
    FontStack.GEOMETRIC_SANS: FontClass.SANS, FontStack.ROUNDED_SANS: FontClass.SANS,
    FontStack.CONDENSED_SANS: FontClass.SANS, FontStack.TRANSITIONAL_SERIF: FontClass.SERIF,
    FontStack.OLD_STYLE_SERIF: FontClass.SERIF, FontStack.SLAB_SERIF: FontClass.SERIF,
    FontStack.SYSTEM_MONO: FontClass.MONO,
}


class TextSize(StrEnum):
    COMPACT = "compact"
    NORMAL = "normal"
    LARGE = "large"
    XLARGE = "xlarge"


TEXT_SCALE: Mapping[TextSize, float] = {TextSize.COMPACT: 0.9, TextSize.NORMAL: 1.0, TextSize.LARGE: 1.15,
                                        TextSize.XLARGE: 1.3}


class ScaleRatio(StrEnum):
    """Rapport entre deux niveaux de titre."""

    TIGHT = "tight"
    BALANCED = "balanced"
    COMFORTABLE = "comfortable"
    DRAMATIC = "dramatic"


SCALE_RATIO: Mapping[ScaleRatio, float] = {ScaleRatio.TIGHT: 1.125, ScaleRatio.BALANCED: 1.2,
                                           ScaleRatio.COMFORTABLE: 1.25, ScaleRatio.DRAMATIC: 1.5}
HEADING_WEIGHTS = (400, 500, 600, 700, 800)
BODY_WEIGHTS = (300, 400, 500)


class LabelCase(StrEnum):
    NONE = "none"
    UPPERCASE = "uppercase"


class Density(StrEnum):
    COMPACT = "compact"
    BALANCED = "balanced"
    AIRY = "airy"


#: Écart entre blocs (`--jv-gap`), en px, par densité.
DENSITY_GAP_PX: Mapping[Density, int] = {Density.COMPACT: 4, Density.BALANCED: 6, Density.AIRY: 10}


class Margin(StrEnum):
    NARROW = "narrow"
    STANDARD = "standard"
    WIDE = "wide"


class Elevation(StrEnum):
    FLAT = "flat"
    SOFT = "soft"
    DRAMATIC = "dramatic"


class PhotoStyle(StrEnum):
    NONE = "none"
    DOCUMENTARY = "documentary"
    EDITORIAL = "editorial"
    PRODUCT = "product"
    ABSTRACT = "abstract"


class IllustrationStyle(StrEnum):
    NONE = "none"
    FLAT = "flat"
    LINE = "line"
    ISOMETRIC = "isometric"
    HAND_DRAWN = "hand_drawn"
    GEOMETRIC = "geometric"


class IconStyle(StrEnum):
    OUTLINE = "outline"
    FILLED = "filled"
    DUOTONE = "duotone"
    ROUNDED = "rounded"
    SHARP = "sharp"


class ImageTreatment(StrEnum):
    NATURAL = "natural"
    DUOTONE = "duotone"
    MONOCHROME = "monochrome"
    HIGH_CONTRAST = "high_contrast"


class SeriesMode(StrEnum):
    CATEGORICAL = "categorical"
    SEQUENTIAL = "sequential"
    DIVERGING = "diverging"


class GridStyle(StrEnum):
    NONE = "none"
    SUBTLE = "subtle"
    FULL = "full"


class LabelPlacement(StrEnum):
    DIRECT = "direct"
    LEGEND = "legend"


class Emphasis(StrEnum):
    SINGLE_ACCENT = "single_accent"
    MULTI = "multi"


class Tempo(StrEnum):
    CALM = "calm"
    MEASURED = "measured"
    LIVELY = "lively"


#: Durées admises (ms) : un ensemble **clos**, jamais une valeur libre.
DURATIONS_MS = (0, 120, 200, 320, 480, 720)
STAGGERS_MS = (0, 40, 80, 120)


class Easing(StrEnum):
    LINEAR = "linear"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    STANDARD = "standard"
    EMPHASIZED = "emphasized"
    SNAPPY = "snappy"


EASING_CSS: Mapping[Easing, str] = {
    Easing.LINEAR: "linear", Easing.EASE_OUT: "cubic-bezier(0, 0, 0.2, 1)",
    Easing.EASE_IN_OUT: "cubic-bezier(0.4, 0, 0.2, 1)", Easing.STANDARD: "cubic-bezier(0.2, 0, 0, 1)",
    Easing.EMPHASIZED: "cubic-bezier(0.3, 0, 0, 1.15)", Easing.SNAPPY: "cubic-bezier(0.2, 0.9, 0.3, 1)",
}


class TransitionStyle(StrEnum):
    NONE = "none"
    FADE = "fade"
    SLIDE = "slide"
    SCALE = "scale"
    WIPE = "wipe"


class ReducedMotion(StrEnum):
    """Repli quand l'utilisateur demande moins de mouvement. Obligatoire, et jamais « garder le mouvement »."""

    FADE_ONLY = "fade_only"
    STATIC = "static"


class TextToken(StrEnum):
    """Quelle couleur de la palette se pose en texte sur un dégradé."""

    TEXT = "text"
    BACKGROUND = "background"


# ------------------------------------------------------------------ contrôles élémentaires


def _enum(kind: type[StrEnum], where: str, value: object) -> Any:
    if isinstance(value, kind):
        return value
    try:
        return kind(value)
    except (ValueError, TypeError):
        raise _fail(f"{where} must be one of {', '.join(m.value for m in kind)}") from None


def _color(where: str, value: object) -> str:
    """`#rrggbb` (la forme à 3 chiffres, les noms, `rgb()`, `var()`, `url()` sont refusés) -> minuscules."""

    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise _fail(f"{where} must be a #rrggbb colour")
    return value.lower()


def _line(where: str, value: object, limit: int) -> str:
    """Une ligne imprimable bornée, sans espace en bordure. **Donnée non fiable** : stockée telle quelle, jamais interprétée."""

    if not isinstance(value, str) or not value:
        raise _fail(f"{where} must be a non-empty string")
    if value != value.strip() or not value.isprintable() or len(value) > limit:
        raise _fail(f"{where} must be one printable line of at most {limit} characters, without surrounding spaces")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _fail(f"{where} holds a character that cannot be stored (lone surrogate)") from None
    return value


def _slug(where: str, value: object) -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise _fail(f"{where} must match [a-z][a-z0-9_]{{0,39}}")
    return value


def _tuple(where: str, value: object, limit: int, low: int = 0) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise _fail(f"{where} must be a list")
    if not low <= len(value) <= limit:
        raise _fail(f"{where} must hold {low}..{limit} entries")
    return tuple(value)


def _choice(where: str, value: object, allowed: tuple[int, ...]) -> int:
    if type(value) is not int or value not in allowed:
        raise _fail(f"{where} must be one of {', '.join(map(str, allowed))}")
    return value


def _bool(where: str, value: object) -> bool:
    if type(value) is not bool:
        raise _fail(f"{where} must be a boolean")
    return value


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def relative_luminance(color: str) -> float:
    """Luminance relative WCAG 2.x d'une couleur `#rrggbb`, dans [0, 1]."""

    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(color)
    return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """Rapport de contraste WCAG 2.x entre deux couleurs `#rrggbb` : 1.0 (identiques) .. 21.0 (noir sur blanc)."""

    a, b = relative_luminance(_color("foreground", foreground)), relative_luminance(_color("background", background))
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


def blend(top: str, bottom: str, alpha: float) -> str:
    """`top` posé à l'opacité `alpha` (0..1) sur `bottom`, arrondi par canal."""

    t, b = _rgb(top), _rgb(bottom)
    return _hex(tuple(round(t[i] * alpha + b[i] * (1 - alpha)) for i in range(3)))  # type: ignore[arg-type]


LENGTH = re.compile(r"([0-9]{1,4}(?:\.[0-9]{1,2})?)(px|rem|em)\Z")
#: Unités admises dans une longueur reçue (un signal d'agent) : un ensemble clos, converti en px.
LENGTH_UNITS: Mapping[str, float] = {"px": 1.0, "rem": 16.0, "em": 16.0}


def parse_length(value: object) -> int:
    """`"8px"`, `"0.5rem"` -> px entiers (borné à `MAX_RADIUS_PX`). Tout autre texte (`calc()`, `var()`, `url()`, `%`, `;`) est refusé."""

    if not isinstance(value, str) or not (found := LENGTH.fullmatch(value)):
        raise _fail("a length is a number followed by px, rem or em")
    return min(MAX_RADIUS_PX, round(float(found.group(1)) * LENGTH_UNITS[found.group(2)]))


# ------------------------------------------------------------------ références

#: Un localisateur de DA est une **référence** (hygiène de `resource_from_dict` : schéma sur liste blanche, pas de `..`, d'UNC,
#: de caractère de contrôle). La DA y ajoute, par défense en profondeur, le refus de tout ce qui a la *forme* d'une injection
#: CSS/JS ou de gabarit, au cas où un jour quelqu'un interpolerait une référence dans un style : fonctions CSS, `@import`,
#: schémas exécutables n'importe où dans le texte, et `< > { } " ; \` ` (brut ou décodé en pourcentage).
_INJECTION_SHAPE = re.compile(
    r"(?:url|expression|var|calc|attr|image-set|env)\s*\(|@import|javascript\s*:|vbscript\s*:|data\s*:|[<>{}\";`]", re.I)


def check_reference(where: str, reference: ResourceReference) -> None:
    decoded = _percent_fixpoint(reference.locator)
    for text in (reference.locator, decoded or ""):
        if _INJECTION_SHAPE.search(unicodedata.normalize("NFKC", text)):
            raise _fail(f"{where}.locator has the shape of CSS, script or template injection: a reference is a plain locator")


# ------------------------------------------------------------------ palette


@dataclass(frozen=True, slots=True)
class GradientStop:
    color: str
    at: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "color", _color("gradient stop color", self.color))
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
        _slug("gradient_id", self.gradient_id)
        object.__setattr__(self, "kind", _enum(GradientKind, "gradient kind", self.kind))
        object.__setattr__(self, "text_token", _enum(TextToken, "gradient text_token", self.text_token))
        _check_int("gradient angle", self.angle, 0, 359)
        if self.kind is GradientKind.RADIAL and self.angle != 0:
            raise _fail("a radial gradient has angle 0")
        stops = _tuple("gradient stops", self.stops, MAX_STOPS, MIN_STOPS)
        if not all(isinstance(s, GradientStop) for s in stops):
            raise _fail("gradient stops must be stops")
        if any(a.at >= b.at for a, b in zip(stops, stops[1:])):
            raise _fail("gradient stops must strictly increase in position")
        object.__setattr__(self, "stops", stops)

    def to_dict(self) -> dict[str, Any]:
        return {"gradient_id": self.gradient_id, "kind": self.kind.value, "angle": self.angle,
                "stops": [s.to_dict() for s in self.stops], "text_token": self.text_token.value}

    @classmethod
    def from_dict(cls, raw: object, where: str) -> Gradient:
        data = _exact_keys(raw, where, {"gradient_id", "kind", "angle", "stops", "text_token"})
        stops = tuple(GradientStop.from_dict(s, f"{where}.stops[{n}]")
                      for n, s in enumerate(_tuple(f"{where}.stops", data["stops"], MAX_STOPS, MIN_STOPS)))
        return cls(data["gradient_id"], data["kind"], data["angle"], stops, data["text_token"])


def gradient_css(gradient: Gradient) -> str:
    """`linear-gradient(135deg, #aabbcc 0%, ...)` : fabriqué **uniquement** à partir de jetons déjà validés."""

    stops = ", ".join(f"{s.color} {s.at}%" for s in gradient.stops)
    if gradient.kind is GradientKind.RADIAL:
        return f"radial-gradient(circle, {stops})"
    return f"linear-gradient({gradient.angle}deg, {stops})"


def easing_css(easing: Easing) -> str:
    return EASING_CSS[_enum(Easing, "easing", easing)]


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
            object.__setattr__(self, name, _color(f"palette.{name}", getattr(self, name)))
        if self.accent_alt is not None:
            object.__setattr__(self, "accent_alt", _color("palette.accent_alt", self.accent_alt))
        _check_int("palette.surface_opacity", self.surface_opacity, MIN_SURFACE_OPACITY, MAX_SURFACE_OPACITY)
        gradients = _tuple("palette.gradients", self.gradients, MAX_GRADIENTS)
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
        ]
        if self.accent_alt is not None:
            pairs.append(("accent_alt on background", self.accent_alt, self.background, GRAPHIC_RATIO))
        for gradient in self.gradients:
            for stop in gradient.stops:
                pairs.append((f"{gradient.text_token.value} on gradient {gradient.gradient_id} at {stop.at}%",
                              self.token(gradient.text_token.value), stop.color, TEXT_RATIO))
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
                          for n, g in enumerate(_tuple(f"{where}.gradients", data["gradients"], MAX_GRADIENTS)))
        return cls(data["background"], data["surface"], data["surface_opacity"], data["text"], data["muted"],
                   data["accent"], data["accent_alt"], gradients)


# ------------------------------------------------------------------ typographie


@dataclass(frozen=True, slots=True)
class FontChoice:
    """Une pile système fermée et, en option, une famille **déclarée** (lettres, chiffres, espace, tiret) qui passe en premier."""

    stack: FontStack
    preferred: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stack", _enum(FontStack, "font stack", self.stack))
        if self.preferred is not None:
            value = self.preferred
            if (not isinstance(value, str) or len(value) > MAX_FAMILY_CHARS or not value.isascii()
                    or not _FAMILY.fullmatch(value)):
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
        object.__setattr__(self, "text_size", _enum(TextSize, "typography.text_size", self.text_size))
        object.__setattr__(self, "scale_ratio", _enum(ScaleRatio, "typography.scale_ratio", self.scale_ratio))
        object.__setattr__(self, "label_case", _enum(LabelCase, "typography.label_case", self.label_case))
        _choice("typography.heading_weight", self.heading_weight, HEADING_WEIGHTS)
        _choice("typography.body_weight", self.body_weight, BODY_WEIGHTS)

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
        object.__setattr__(self, "density", _enum(Density, "spacing.density", self.density))
        object.__setattr__(self, "margin", _enum(Margin, "spacing.margin", self.margin))

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
        object.__setattr__(self, "elevation", _enum(Elevation, "shapes.elevation", self.elevation))

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
        object.__setattr__(self, "photo", _enum(PhotoStyle, "imagery.photo", self.photo))
        object.__setattr__(self, "illustration", _enum(IllustrationStyle, "imagery.illustration", self.illustration))
        object.__setattr__(self, "icons", _enum(IconStyle, "imagery.icons", self.icons))
        object.__setattr__(self, "treatment", _enum(ImageTreatment, "imagery.treatment", self.treatment))
        motifs = tuple(_line("imagery.motifs[]", m, MAX_MOTIF_CHARS) for m in _tuple("imagery.motifs", self.motifs, MAX_MOTIFS))
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
        object.__setattr__(self, "mode", _enum(SeriesMode, "dataviz.mode", self.mode))
        object.__setattr__(self, "grid", _enum(GridStyle, "dataviz.grid", self.grid))
        object.__setattr__(self, "labels", _enum(LabelPlacement, "dataviz.labels", self.labels))
        object.__setattr__(self, "emphasis", _enum(Emphasis, "dataviz.emphasis", self.emphasis))
        series = tuple(_color("dataviz.series[]", c) for c in _tuple("dataviz.series", self.series, MAX_SERIES, MIN_SERIES))
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
        object.__setattr__(self, "tempo", _enum(Tempo, "motion.tempo", self.tempo))
        object.__setattr__(self, "easing", _enum(Easing, "motion.easing", self.easing))
        object.__setattr__(self, "transition", _enum(TransitionStyle, "motion.transition", self.transition))
        object.__setattr__(self, "reduced_motion", _enum(ReducedMotion, "motion.reduced_motion", self.reduced_motion))
        for name in ("enter_ms", "exit_ms", "emphasis_ms"):
            _choice(f"motion.{name}", getattr(self, name), DURATIONS_MS)
        _choice("motion.stagger_ms", self.stagger_ms, STAGGERS_MS)

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
        object.__setattr__(self, "origin", _enum(Origin, "provenance.origin", self.origin))
        if not isinstance(self.sections, Mapping):
            raise _fail("provenance.sections must be an object")
        sections = {_enum(Section, "provenance.sections key", key).value: _enum(Origin, "provenance.sections value", value)
                    for key, value in self.sections.items()}
        object.__setattr__(self, "sections", dict(sorted(sections.items())))
        _bool("provenance.fallback", self.fallback)
        if self.fallback and self.origin is not Origin.GENERATED:
            raise _fail("a fallback profile is generated: provenance.origin must be generated")
        if (isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float))
                or not math.isfinite(float(self.confidence)) or not 0.0 <= float(self.confidence) <= 1.0):
            raise _fail("provenance.confidence must be a finite number between 0 and 1")
        object.__setattr__(self, "confidence", round(float(self.confidence), 3))
        notes = tuple(_line("provenance.notes[]", n, MAX_NOTE_CHARS) for n in _tuple("provenance.notes", self.notes, MAX_NOTES))
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
        references = _tuple("references", self.references, MAX_REFERENCES)
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
        r, g, b = _rgb(p.surface)
        return {"accent": p.accent, "text": p.text, "muted": p.muted,
                "surface": f"rgba({r},{g},{b},{p.surface_opacity / 100:.2f})",
                "scale": TEXT_SCALE[self.typography.text_size]}

    def to_theme_variables(self) -> dict[str, str]:
        """Variables `--jv-*` de la coquille des prefabs, **uniquement** `ALLOWED_THEME_VARIABLES`. Les valeurs sont des
        couleurs `#rrggbb` / `rgba(n,n,n,0.nn)`, des nombres, des longueurs en px et une pile de police fermée ; aucun
        champ de texte libre n'y entre. Déterministe : le même profil donne les mêmes variables."""

        p, t = self.palette, self.typography
        tr, tg, tb = _rgb(p.text)
        br, bg_, bb = _rgb(p.background)
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
                     for n, r in enumerate(_tuple(f"{where}.references", data["references"], MAX_REFERENCES)))
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
