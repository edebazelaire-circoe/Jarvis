"""Presentation Studio: the lexical helpers of the first-draft gate (handoff jarvis-interactive-presentation-studio, Slice 11 rework).

Pure, deterministic, no model, no I/O. The gate (`presentation_studio_authoring_gate.py`) judges *structure*; this module judges *words*:
how much meaningful text a scene or a spoken line holds (a floor, not a quality score), what is a placeholder and what only looks like
one (a colour, a number, a table cell), digit-insensitive filler, a cheap French/English guess, whether a `must_cover` item is traceable
in the scene texts, and the risky constructs of a brain-authored source.

What a deterministic check can NOT do is stated rather than faked: `purpose`, `audience` and `tone` of the brief are untrusted prose and
are not machine-checkable; they steer the model through the prompt and seed the art direction fallback, nothing more.

Every function returns a kind, a count or a boolean; none returns the author's words, so the gate's messages can name a *kind* of problem.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
import re
import unicodedata

# ------------------------------------------------------------------ thresholds (the rule table and the prompt quote them)

#: Meaningful words a scene shows (its title and its prose leaves together): a floor, so "...", "-", one word, an emoji row do not pass.
MIN_SCENE_WORDS = 3
#: ... and at least this many of them outside the title (a title alone is a divider, not a scene: `"..."` or `"a"` under a real title is empty).
MIN_BODY_WORDS = 2
#: Meaningful words of a spoken line or a speaker note (silence items are exempt).
MIN_LINE_WORDS = 3
#: Share of the significant tokens of a `must_cover` item that must be found in the scene texts (stems of 5 letters).
MUST_COVER_THRESHOLD = 0.6
#: Hits of one language needed, and the lead over the other, before the guess is trusted.
LANGUAGE_MIN_HITS = 6
LANGUAGE_LEAD = 2.0
#: Titles or texts that differ only by digits: this many scenes make filler.
NUMERIC_FILLER_SCENES = 3
NUMERIC_TITLE_SCENES = 4
MIN_FILLER_CHARS = 12

_I = re.IGNORECASE
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_LETTER_RUN = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
_COLOR_OR_URL = re.compile(r"(?:#[0-9a-fA-F]{3,8}|https?://\S+)\Z")
_NUMBERISH = re.compile(r"[\d\s.,:;%+\-/()€$£]*\Z")


def fold(text: str) -> str:
    """Casefolded, accents removed."""

    return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(c))


def is_literal(text: str) -> bool:
    """A colour, a URL, a number or something with no letter at all: data, not prose (never a placeholder, never counted as words)."""

    stripped = text.strip()
    return not stripped or bool(_COLOR_OR_URL.match(stripped)) or bool(_NUMBERISH.match(stripped)) \
        or not any(c.isalpha() for c in stripped)


def count_words(text: str) -> int:
    """Words for the density cap: runs of letters and digits (underscore separates), and a CJK run counts one word per two characters."""

    cjk = len(_CJK.findall(text))
    return len(_TOKEN.findall(_CJK.sub(" ", text))) + (cjk + 1) // 2


def meaningful_words(text: str) -> int:
    """Words that carry a meaning: a run of at least two letters; digits, punctuation and emoji carry none; CJK counts one per two characters."""

    cjk = len(_CJK.findall(text))
    return len(_LETTER_RUN.findall(_CJK.sub(" ", text))) + cjk // 2


def prose_leaves(leaves: Iterable[str]) -> Iterator[str]:
    """The string leaves that are prose (not a colour, a URL, a number)."""

    return (leaf for leaf in leaves if not is_literal(leaf))


# ------------------------------------------------------------------ placeholders

_PLACEHOLDERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("lorem", re.compile(r"\b(?:lorem|ipsum|dolor sit amet|consectetur)\b", _I)),
    ("todo", re.compile(r"\b(?:todo|tbd|tbc|fixme|wip)\b", _I)),
    ("xxx", re.compile(r"\bx{3,}\b|\?{3,}", _I)),
    ("blank", re.compile(r"\b(?:placeholder|your (?:text|title|name|content) here|insert [^.]{0,30} here|texte (?:ici|a venir|à venir|à compléter|a compléter)"
                         r"|titre ici|à compléter|a completer|à remplir|a remplir|contenu à venir)\b", _I)),
    ("bracket", re.compile(r"\[(?:insert|titre|title|texte|text|nom|name|à [^\]]{0,20}|a [^\]]{0,20}|your [^\]]{0,20}|\.{3})[^\]]{0,30}\]", _I)),
    ("repeated_word", re.compile(r"\b(\w{2,})\b(?:\W+\1\b){3,}", _I)),
)
_REPEATED_CHAR = re.compile(r"([^\W\d_])\1{5,}")
_GENERIC_TITLE = re.compile(r"(?:slide|scene|scène|diapositive|page|untitled|sans titre|titre|title|new slide|nouvelle diapo)\s*\d*\Z", _I)


def placeholder_hits(text: str, *, title: bool = False) -> list[tuple[str, str]]:
    """Every `(kind, matched span)` for which `text` is a placeholder (empty: it is not). Only prose is judged: a colour (`#ffffff`), a URL,
    a number or a numeric table cell is never a placeholder, and the character-variety kinds need a mostly-alphabetic text. All the
    matches are returned (not the first only) so that an allowed term cannot hide another placeholder in the same text."""

    stripped = text.strip()
    if _COLOR_OR_URL.match(stripped):
        return []                                    # a colour or a URL is data: `#ffffff`, `https://x.test/todo`
    if title and stripped and not any(c.isalpha() for c in stripped):
        return [("generic_title", stripped)]         # a title that is only digits or punctuation
    if title and _GENERIC_TITLE.match(stripped):
        return [("generic_title", stripped)]
    found = [(kind, m.group(0)) for kind, pattern in _PLACEHOLDERS for m in pattern.finditer(text)][:8]
    letters = [c for c in text.casefold() if c.isalpha()]
    significant = [c for c in text if not c.isspace()]
    if significant and len(letters) / len(significant) >= 0.6:
        run = _REPEATED_CHAR.search(text)
        if run:
            found.append(("repeated_char", run.group(0)))
        elif len(letters) >= 8 and len(set(letters)) <= 2:
            found.append(("low_variety", text.strip()[:12]))
    return found


def placeholder_hit(text: str, *, title: bool = False) -> tuple[str, str] | None:
    hits = placeholder_hits(text, title=title)
    return hits[0] if hits else None


def placeholder_kind(text: str, *, title: bool = False) -> str | None:
    hit = placeholder_hit(text, title=title)
    return None if hit is None else hit[0]


def is_allowed(hit_span: str, allowed: tuple[str, ...]) -> bool:
    """`brief.literal_terms`: a term the author declared legitimate (a status deck that says `todo` or `WIP`). It lifts the placeholder
    rule for the span that triggered it, case- and accent-insensitively (the term is the span, contains it, or is contained in it)."""

    span = fold(hit_span).strip()
    return any(term and (term == span or term in span or span in term) for term in (fold(t).strip() for t in allowed))


def normalise_filler(text: str) -> str:
    """Casefolded, accents folded, every digit run one `#`, every other non-letter run one space: `Point 1` and `point 12` are the same."""

    folded = fold(text)
    folded = re.sub(r"\d+", "#", folded)
    return " ".join(re.sub(r"[^\w#]+|_", " ", folded).split())


# ------------------------------------------------------------------ labels

_MEANINGLESS_LABEL = re.compile(r"(?:ctrl|control|controle|champ|field|param|parametre|reglage|setting|val|value|input|c|x|opt|option)[\s_-]*\d*\Z", _I)


def label_meaningless(label: str) -> bool:
    """`???`, `-`, `x`, `ctrl1`, `12`: a label with fewer than two letters or a generic name with an index."""

    letters = sum(1 for c in label if c.isalpha())
    return letters < 2 or bool(_MEANINGLESS_LABEL.match(fold(label).strip()))


# ------------------------------------------------------------------ must_cover

_STOP_FR = frozenset("les des une aux dans pour avec sans sous sur par est sont etre avoir plus tout tous cette cet ces leur leurs nous vous ils elles mais donc car que qui quoi dont".split())
_STOP_EN = frozenset("the and for with from that this these those their there where which what when will would about into over under than then your our are was were have has been".split())


def significant_tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(fold(text)) if len(t) >= 4 and t.isalpha() and t not in _STOP_FR and t not in _STOP_EN]


def stems(text: str) -> set[str]:
    return {t[:5] for t in significant_tokens(text)}


def covers(item: str, corpus_stems: set[str], corpus_folded: str) -> bool:
    """Is a `must_cover` item traceable in the texts? At least `MUST_COVER_THRESHOLD` of its significant tokens (compared by 5-letter stem);
    an item with no significant token (short words only) must appear as a phrase."""

    tokens = significant_tokens(item)
    if not tokens:
        return fold(item).strip() in corpus_folded
    hit = sum(1 for t in tokens if t[:5] in corpus_stems)
    return hit / len(tokens) >= MUST_COVER_THRESHOLD


# ------------------------------------------------------------------ language guess (French / English only)

_FR = frozenset("le la les un une des du de et est en dans pour avec sur par que qui nous vous ils elles ce cette ces au aux mais ou donc plus pas sont etre avons ont ete comme tres bien tout tous leur leurs sans sous chez voici notre votre".split())
_EN = frozenset("the a an and of to in is are was were for with on by that this these those it as at be we you they their our your not but or from have has been will can more all just here".split())


def guess_language(texts: Iterable[str]) -> str | None:
    """`fr`, `en` or `None` (not enough evidence, or another language). Counts stop-words of each; trusted only with `LANGUAGE_MIN_HITS`
    hits and a lead of `LANGUAGE_LEAD` times the other. Cheap on purpose: it cannot judge a language it has no list for."""

    tokens = [t for text in texts for t in _TOKEN.findall(fold(text))]
    fr, en = sum(1 for t in tokens if t in _FR), sum(1 for t in tokens if t in _EN)
    if fr >= LANGUAGE_MIN_HITS and fr >= LANGUAGE_LEAD * en:
        return "fr"
    if en >= LANGUAGE_MIN_HITS and en >= LANGUAGE_LEAD * fr:
        return "en"
    return None


# ------------------------------------------------------------------ sources

_ANIMATED = re.compile(r"@keyframes|(?<![\w-])animation(?:-name)?\s*:|(?<![\w-])transition(?:-property)?\s*:", _I)
_ANIMATED_JS = re.compile(r"requestAnimationFrame|\.animate\s*\(", _I)
_GUARD = re.compile(r"prefers-reduced-motion", _I)


def is_motion_unguarded(style: str, behavior: str) -> bool:
    """A source that animates (CSS animation or transition, `requestAnimationFrame`, Web Animations) and never mentions
    `prefers-reduced-motion`. The DA contract forces a reduced-motion fallback on the theme, a published source has to honour it itself."""

    animated = bool(_ANIMATED.search(style) or _ANIMATED_JS.search(behavior))
    return animated and not (_GUARD.search(style) or _GUARD.search(behavior))


_RISKY_CODE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("network", re.compile(r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b", _I)),
    ("dynamic_import", re.compile(r"\bimport\s*\(|\bimportScripts\b")),
    ("eval", re.compile(r"\beval\s*\(|\bnew\s+Function\b|\bsetTimeout\s*\(\s*['\"]|\bsetInterval\s*\(\s*['\"]")),
    ("javascript_url", re.compile(r"javascript\s*:", _I)),
    ("parent_access", re.compile(r"\b(?:window\.(?:parent|top)|top\.location|parent\.postMessage|document\.cookie)\b")),
)
_REMOTE_REF = re.compile(r"""(?:src|href|data|action|poster|srcset|xlink:href)\s*=\s*["']?\s*(?:https?:)?//""", _I)


def risky_constructs(template: str, style: str, behavior: str) -> list[str]:
    """Kinds of risky constructs in a brain-authored source (network, dynamic import, eval, `javascript:`, parent access, remote src/href).
    A lint, not a wall: the host sandbox (`allow-scripts`, opaque origin) and the CSP stay the real boundary (docs/prefabs.md)."""

    found = [kind for kind, pattern in _RISKY_CODE if pattern.search(behavior) or (kind == "javascript_url" and pattern.search(template))]
    if _REMOTE_REF.search(template) or re.search(r"@import|url\(\s*['\"]?\s*(?:https?:)?//", style, _I):
        found.append("remote_reference")
    return sorted(set(found))
