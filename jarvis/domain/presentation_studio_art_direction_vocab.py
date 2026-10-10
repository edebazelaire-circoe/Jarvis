"""Presentation Studio : vocabulaires clos, bornes et jetons validés de la direction artistique (handoff
jarvis-interactive-presentation-studio, Slice 09).

Tout ce qu'un champ de la DA peut valoir : énumérations closes, bornes, constantes CSS **du module** (piles de polices,
courbes), analyseurs de jetons (couleur `#rrggbb`, ligne de texte, liste bornée), mathématiques de contraste WCAG. Pur,
sans état, sans E/S. `presentation_studio_art_direction` réexporte tout ce qui est public ici.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
import re
from typing import Any

from jarvis.domain.presentation_studio_checks import _fail

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
#: Opacité du texte qui fait `--jv-wash` (fond d'un bouton, d'une pastille) : le texte doit y rester lisible.
WASH_OPACITY = 0.09
#: Un dégradé est échantillonné sur chaque segment entre deux arrêts (9 points, bornes comprises) : au plus 4 x 9 mesures par dégradé.
GRADIENT_SEGMENT_STEPS = 8

SLUG = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z")
FAMILY_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[ -][A-Za-z0-9]+)*\Z")


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


def parse_enum(kind: type[StrEnum], where: str, value: object) -> Any:
    if isinstance(value, kind):
        return value
    try:
        return kind(value)
    except (ValueError, TypeError):
        raise _fail(f"{where} must be one of {', '.join(m.value for m in kind)}") from None


def parse_color(where: str, value: object) -> str:
    """`#rrggbb` (la forme à 3 chiffres, les noms, `rgb()`, `var()`, `url()` sont refusés) -> minuscules."""

    if not isinstance(value, str) or not HEX_COLOR.fullmatch(value):
        raise _fail(f"{where} must be a #rrggbb colour")
    return value.lower()


def parse_line(where: str, value: object, limit: int) -> str:
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


def parse_slug(where: str, value: object) -> str:
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise _fail(f"{where} must match [a-z][a-z0-9_]{{0,39}}")
    return value


def parse_list(where: str, value: object, limit: int, low: int = 0) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise _fail(f"{where} must be a list")
    if not low <= len(value) <= limit:
        raise _fail(f"{where} must hold {low}..{limit} entries")
    return tuple(value)


def parse_choice(where: str, value: object, allowed: tuple[int, ...]) -> int:
    if type(value) is not int or value not in allowed:
        raise _fail(f"{where} must be one of {', '.join(map(str, allowed))}")
    return value


def parse_bool(where: str, value: object) -> bool:
    if type(value) is not bool:
        raise _fail(f"{where} must be a boolean")
    return value


def rgb_of(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def hex_of(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def relative_luminance(color: str) -> float:
    """Luminance relative WCAG 2.x d'une couleur `#rrggbb`, dans [0, 1]."""

    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = rgb_of(color)
    return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """Rapport de contraste WCAG 2.x entre deux couleurs `#rrggbb` : 1.0 (identiques) .. 21.0 (noir sur blanc)."""

    a, b = relative_luminance(parse_color("foreground", foreground)), relative_luminance(parse_color("background", background))
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


def blend(top: str, bottom: str, alpha: float) -> str:
    """`top` posé à l'opacité `alpha` (0..1) sur `bottom`, arrondi par canal."""

    t, b = rgb_of(top), rgb_of(bottom)
    return hex_of(tuple(round(t[i] * alpha + b[i] * (1 - alpha)) for i in range(3)))  # type: ignore[arg-type]


LENGTH = re.compile(r"([0-9]{1,4}(?:\.[0-9]{1,2})?)(px|rem|em)\Z")
#: Unités admises dans une longueur reçue (un signal d'agent) : un ensemble clos, converti en px.
LENGTH_UNITS: Mapping[str, float] = {"px": 1.0, "rem": 16.0, "em": 16.0}


def parse_length(value: object) -> int:
    """`"8px"`, `"0.5rem"` -> px entiers (borné à `MAX_RADIUS_PX`). Tout autre texte (`calc()`, `var()`, `url()`, `%`, `;`) est refusé."""

    if not isinstance(value, str) or not (found := LENGTH.fullmatch(value)):
        raise _fail("a length is a number followed by px, rem or em")
    return min(MAX_RADIUS_PX, round(float(found.group(1)) * LENGTH_UNITS[found.group(2)]))
