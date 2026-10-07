"""Metadata block of a memory note: flat `key: value` lines between two `---`.

Handoff jarvis-memory-intelligence-knowledge, Slice 02. Contract page:
`docs/memory.md` (Metadata schema). No YAML dependency, on purpose: a value is
one line of JSON (scalar, array or object), a key is an identifier.

    ---
    id: "3f2a..."
    level: "L1"
    confidence: 0.9
    sources: [{"type": "turn", "ref": "t-12", "at": "2026-10-07T09:00:00+00:00"}]
    ---
    # Title

    Body.

Reading never drops a note. A file without a block is a legacy note (empty
metadata, whole text is the body). A block that is not strictly valid (a line
that is not `key: json`, a duplicate key, bad JSON) is *corrupt*: the metadata
is empty and the body is the whole text, block included, so nothing the human
wrote is lost or hidden and the note stays searchable. Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import re
from types import MappingProxyType
from typing import Any

DELIMITER = "---"
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_LINE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*):[ \t]*(.+?)[ \t]*\Z")
_BOM = "﻿"


@dataclass(frozen=True, slots=True)
class FrontMatter:
    """Result of `parse`: `meta` (ordered, read-only), `body`, and what was found."""

    meta: Mapping[str, Any]
    body: str
    #: A well-formed block was present and parsed.
    has_block: bool = False
    #: A delimited block was present but invalid; `meta` is empty and `body` is the whole text.
    corrupt: bool = False


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def _block_end(lines: list[str]) -> int | None:
    """Index of the closing delimiter of a block that opens on line 0, else `None`."""

    if not lines or lines[0].rstrip("\r") != DELIMITER:
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r") == DELIMITER:
            return index
    return None


def parse(text: str) -> FrontMatter:
    """Split `text` into metadata and body. Never raises, never loses text."""

    candidate = text[1:] if text.startswith(_BOM) else text
    lines = candidate.split("\n")
    end = _block_end(lines)
    if end is None:
        return FrontMatter(MappingProxyType({}), text)
    meta: dict[str, Any] = {}
    for raw in lines[1:end]:
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        found = _LINE.fullmatch(line)
        if found is None or found.group(1) in meta:
            return FrontMatter(MappingProxyType({}), text, corrupt=True)
        try:
            meta[found.group(1)] = json.loads(found.group(2), parse_constant=_reject_constant)
        except ValueError:
            return FrontMatter(MappingProxyType({}), text, corrupt=True)
    return FrontMatter(MappingProxyType(meta), "\n".join(lines[end + 1:]), has_block=True)


def render(meta: Mapping[str, Any]) -> str:
    """The block for `meta`, in its iteration order, ending with a newline.

    Raises `ValueError` for a key that is not an identifier or a value that is
    not JSON-serialisable (including NaN): the writer never emits what the
    parser would refuse.
    """

    lines = [DELIMITER]
    for key, value in meta.items():
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ValueError(f"front-matter key {key!r} is not an identifier")
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"front-matter value of {key} is not JSON: {exc}") from exc
        # `json.dumps` never emits a raw newline; U+2028 and friends are legal
        # in a line because `parse` splits on "\n" only.
        lines.append(f"{key}: {encoded}")
    lines.append(DELIMITER)
    return "\n".join(lines) + "\n"


def compose(meta: Mapping[str, Any], body: str) -> str:
    """`render(meta)` followed by `body`: the file text of a canonical note."""

    return render(meta) + body
