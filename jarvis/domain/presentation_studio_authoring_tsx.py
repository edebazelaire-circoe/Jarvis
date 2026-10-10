"""Presentation Studio: what the authoring gate can read in the TSX of a Remotion scene (handoff jarvis-remotion-presentation-integration, Slice 15).

A scene written by the brain is TypeScript, not data: the content rules of the first-draft gate (placeholder text, density, must-cover, language) read
`props` and `data`, so text hidden in the source would escape them, and the Slice 13 controls only edit what the source reads from its props. This module is
the **lint** that closes those gaps. It is deliberately *not* a parser (the same line as `remotion_isolation`: a regular expression over JavaScript is a
filter, never a wall; the isolation guards and the sandbox are the wall). Every pattern is bounded (no unbounded repeat over author text), the input is
bounded by the source limits (256 KiB a module), and a miss only means a warning is not raised: the gate is a FLOOR (`presentation-studio.md`).

`tsx_facts(modules)` returns a `TsxFacts` (all counts and names, never a copy of the author's text except `literals`, which the gate already treats as
untrusted prose and never echoes). Pure: no I/O, no clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

#: Modules that are code (a `.json` module is data: it does not draw, animate or read props).
CODE_SUFFIXES = (".tsx", ".ts", ".jsx", ".js")
#: Lines of `src/Scene.tsx` above which one file is a monolith when it is the only module (`tsx_monolith`).
MONOLITH_LINES = 250
#: Distinct colour literals above which the palette is not the art direction's (`tsx_color_hardcoded`).
MAX_COLOR_LITERALS = 3
#: Words of literal text in the source above which the content is hard-coded rather than a prop (`tsx_text_hardcoded`). A short label
#: (`Q3`, `Suivant`, `Oui / Non`) is chrome; a sentence is content.
MAX_LITERAL_WORDS = 3
MAX_LITERALS = 40
_INTERPOLATE_WINDOW = 600

# One pass that keeps strings and drops comments (so `"http://x"` is not a comment and `// "text"` is not a literal).
_TOKENS = re.compile(r"""//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`""", re.DOTALL)
_JSX_TEXT = re.compile(r">([^<>{}\n;=()]{3,200})<")
_JSX_TEXT_LINES = re.compile(r">\s*\n([^<>{}=;()]{3,300})\n\s*<")
_ATTR_TEXT = re.compile(r"""\b(?:alt|title|aria-label|label|placeholder|caption|subtitle|heading)=(?:\{\s*)?(?P<q>["'])(?P<text>[^"'\n]{3,200})(?P=q)""")
_EXPR_TEXT = re.compile(r"""\{\s*(?P<q>["'])(?P<text>[^"'\n]{3,200})(?P=q)\s*\}""")
_LETTER_WORD = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
_FRAME = re.compile(r"\buseCurrentFrame\s*\(|<\s*(?:Sequence|Series)\b")
# The `theme` PROP: `props.theme`, `p.theme`, `["theme"]` or a destructured `{theme}`; a local variable called theme is not the art direction.
_THEME = re.compile(r"""\.\s*theme\b|\[\s*["']theme["']\s*\]|[{,]\s*theme\s*[,}:=]""")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_RGB = re.compile(r"\brgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}(?:\s*,\s*[0-9.]{1,5})?\s*\)")
_PROPS_DOT = re.compile(r"\bprops\s*\.\s*([A-Za-z_]\w{0,39})")
_PROPS_BRACKET = re.compile(r"""\bprops\s*\[\s*["']([A-Za-z_]\w{0,39})["']\s*\]""")
_DESTRUCTURE = re.compile(r"(?:function\s+\w{0,40}\s*\(|=\s*\(|\bconst\s+)\s*\{([^{}]{0,400})\}\s*(?::[^)=]{0,200})?(?:\)\s*(?:=>|:|\{)|=\s*props\b)")
_NAME = re.compile(r"[A-Za-z_]\w{0,39}")


@dataclass(frozen=True, slots=True)
class TsxFacts:
    #: The scene is a function of time (it reads the current frame or composes sequences).
    reads_frame: bool
    #: `interpolate(` calls with no `extrapolate*` option: past the input range the value keeps going.
    unclamped_interpolations: int
    #: The source mentions the reserved `theme` prop (the art direction can reach it).
    reads_theme: bool
    #: Distinct colour literals (`#rrggbb`, `rgb(...)`) in code.
    color_literals: int
    #: Visible text literals found in JSX (untrusted prose: counted and judged, never echoed).
    literals: tuple[str, ...]
    #: Prop names the entry module reads (`props.title`, `({title}) =>`).
    props_read: frozenset[str]
    #: Text of the code modules with comments removed, for "is this key mentioned anywhere" questions.
    mentions: str
    entry_lines: int
    code_modules: int


def strip_comments(text: str) -> str:
    return _TOKENS.sub(lambda m: m.group(0) if m.group(0)[0] in "\"'`" else " ", text)


def _words(text: str) -> int:
    return len(_LETTER_WORD.findall(text))


def literal_texts(code: str) -> list[str]:
    """Visible text in JSX: text nodes, JSX expression strings and the text-bearing attributes. A string that reads as code, a CSS value
    or a path (a symbol, a colour, a function call, no two letter-words) is not text."""

    found: list[str] = []
    for pattern, group in ((_JSX_TEXT, 1), (_JSX_TEXT_LINES, 1), (_ATTR_TEXT, "text"), (_EXPR_TEXT, "text")):
        for match in pattern.finditer(code):
            text = " ".join(match.group(group).split())
            if _words(text) >= 1 and not text.startswith(("#", "http", "/", ".")) and "rgba(" not in text and "px" not in text.split()[:1]:
                found.append(text)
            if len(found) >= MAX_LITERALS:
                return found
    return found


def _interpolations(code: str) -> tuple[int, int]:
    """`(calls, unclamped)`: the call text is cut at its closing parenthesis (bounded)."""

    calls = unclamped = 0
    position = 0
    while (start := code.find("interpolate(", position)) != -1:
        position = start + 12
        if start and (code[start - 1].isalnum() or code[start - 1] == "_"):
            continue                                                  # `myinterpolate(`
        depth, end = 1, position
        limit = min(len(code), position + _INTERPOLATE_WINDOW)
        while end < limit and depth:
            depth += {"(": 1, ")": -1}.get(code[end], 0)
            end += 1
        calls += 1
        if "extrapolate" not in code[position:end]:
            unclamped += 1
    return calls, unclamped


def _props_read(entry: str) -> frozenset[str]:
    names = set(_PROPS_DOT.findall(entry)) | set(_PROPS_BRACKET.findall(entry))
    for match in _DESTRUCTURE.finditer(entry):
        for part in match.group(1).split(","):
            head = part.split(":")[0].split("=")[0].strip()
            if head.startswith("..."):
                continue
            if _NAME.fullmatch(head):
                names.add(head)
    names.discard("data")
    return frozenset(names)


def tsx_facts(modules: Mapping[str, str], entry: str = "src/Scene.tsx") -> TsxFacts:
    """Facts of the code modules of one Remotion source (`modules`: path -> text)."""

    code = {path: strip_comments(text) for path, text in modules.items() if path.endswith(CODE_SUFFIXES)}
    joined = "\n".join(code.values())
    colours = {c.lower() for c in _HEX.findall(joined)} | {re.sub(r"\s+", "", c) for c in _RGB.findall(joined)}
    literals: list[str] = []
    for text in code.values():
        literals.extend(literal_texts(text))
    entry_code = code.get(entry, "")
    return TsxFacts(
        reads_frame=bool(_FRAME.search(joined)), unclamped_interpolations=_interpolations(joined)[1],
        reads_theme=bool(_THEME.search(joined)), color_literals=len(colours), literals=tuple(literals[:MAX_LITERALS]),
        props_read=_props_read(entry_code), mentions=joined, entry_lines=entry_code.count("\n") + 1 if entry_code else 0,
        code_modules=len(code))


def mentions(facts: TsxFacts, name: str) -> bool:
    """The identifier appears in code (not as part of a longer word): a declared prop nothing reads is a dead control."""

    return re.search(rf"(?<![\w$]){re.escape(name)}(?![\w$])", facts.mentions) is not None


def hard_coded_words(facts: TsxFacts) -> int:
    """Words of literal text beyond the chrome allowance: the sum over the literals longer than `MAX_LITERAL_WORDS` words."""

    return sum(_words(text) for text in facts.literals if _words(text) > MAX_LITERAL_WORDS)
