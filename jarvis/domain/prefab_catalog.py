"""Semantic catalog metadata of a Prefab (handoff jarvis-remotion-presentation-integration, Slice 17).

Contract (Level 2): `docs/prefabs.md` > *Semantic catalog (manifest v3)*. Pure module: no I/O.

A Prefab is the one library identity. What a person browses by is declared once, in the same words for every engine:

- `type`: fixed vocabulary `component | composition | page | presentation | asset` (`SemanticType`). Never translated per
  engine, never inferred by a renderer.
- `compatibility`: `{engine: native|adapter|unsupported}` per `Engine`. Undeclared is `unsupported`
  (`presentation_studio_engine.classify_compatibility`), never a promise.
- `stack`, `dependencies` (name + version), `license`, `upstream` (declared provenance of an imported source: Core does
  not verify it, Slice 18 owns the importer that writes it).

A manifest that declares a `catalog` block is written at schema_version 3 (the lowest version that expresses it); versions 1
and 2 never carry it and are never rewritten. `derive_catalog` reads the same fields for those OLDER versions from what they
are (legacy HTML -> Slidecar native, Remotion unsupported; Remotion source -> Remotion native), flagged `declared: false`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any
from urllib.parse import urlsplit

from jarvis.domain.presentation_studio_checks import PresentationStudioError
from jarvis.domain.presentation_studio_engine import (
    Engine, Support, classify_compatibility, legacy_html_compatibility,
)

#: Manifest version that carries the `catalog` block.
CATALOG_MANIFEST_VERSION = 3

MAX_STACK = 12
MAX_DEPENDENCIES = 32
_STACK_TOKEN = re.compile(r"[a-z][a-z0-9.+_-]{0,23}\Z")
_DEP_NAME = re.compile(r"(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*\Z")
_DEP_VERSION = re.compile(r"[0-9A-Za-z^~<>=*][0-9A-Za-z.+_<>=^~ -]{0,39}\Z")
MAX_DEP_NAME = 80
MAX_LICENSE = 64
MAX_UPSTREAM_TEXT = 120
MAX_URL = 300

CATALOG_KEYS = frozenset({"type", "compatibility", "stack", "dependencies", "license", "upstream"})
CATALOG_REQUIRED = frozenset({"type", "compatibility", "stack"})
UPSTREAM_KEYS = frozenset({"name", "url", "ref", "license", "author"})
UPSTREAM_REQUIRED = frozenset({"name", "url"})


class SemanticType(StrEnum):
    COMPONENT = "component"
    COMPOSITION = "composition"
    PAGE = "page"
    PRESENTATION = "presentation"
    ASSET = "asset"


#: Legacy `family` -> type (read only, for manifests that predate the catalog). Anything else is a Component.
_LEGACY_FAMILY_TYPE: Mapping[str, SemanticType] = {
    "composition": SemanticType.COMPOSITION, "video": SemanticType.COMPOSITION, "scene": SemanticType.COMPOSITION,
    "page": SemanticType.PAGE, "deck": SemanticType.PRESENTATION, "presentation": SemanticType.PRESENTATION,
    "asset": SemanticType.ASSET, "image": SemanticType.ASSET, "media": SemanticType.ASSET,
}
HTML_STACK = ("html", "css", "javascript")
REMOTION_STACK = ("react", "remotion", "typescript")


@dataclass(frozen=True, slots=True)
class Dependency:
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class Upstream:
    name: str
    url: str
    ref: str = ""
    license: str = ""
    author: str = ""

    def to_dict(self) -> dict[str, str]:
        return {key: value for key, value in (("name", self.name), ("url", self.url), ("ref", self.ref),
                                              ("license", self.license), ("author", self.author)) if value}


@dataclass(frozen=True, slots=True)
class CatalogBlock:
    """The parsed `catalog` block of a v3 manifest."""

    type: SemanticType
    compatibility: Mapping[Engine, Support]
    stack: tuple[str, ...]
    dependencies: tuple[Dependency, ...] = ()
    license: str = ""
    upstream: Upstream | None = None


def _line(value: object, limit: int) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= limit and value.isprintable()


def _is_http_url(value: object) -> bool:
    if not isinstance(value, str) or not 0 < len(value) <= MAX_URL or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def parse_catalog_block(raw: object) -> tuple[CatalogBlock | None, list[str]]:
    """Strict block; returns every error seen (path-prefixed `catalog...`). No guess, no default for a missing field."""

    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["catalog: must be an object"]
    unknown = sorted(str(key)[:40] for key in raw if key not in CATALOG_KEYS)
    missing = sorted(CATALOG_REQUIRED - raw.keys())
    if unknown:
        errors.append(f"catalog: unknown fields {unknown[:5]}")
    if missing:
        errors.append(f"catalog: missing fields {missing}")
    if unknown or missing:
        return None, errors
    kind = None
    try:
        kind = SemanticType(raw["type"])
    except ValueError:
        errors.append(f"catalog.type: must be one of {[item.value for item in SemanticType]}")
    compatibility = _parse_compatibility(raw["compatibility"], errors)
    stack = raw["stack"]
    if (not isinstance(stack, list) or not 1 <= len(stack) <= MAX_STACK or len(set(map(str, stack))) != len(stack)
            or any(not isinstance(item, str) or not _STACK_TOKEN.fullmatch(item) for item in stack)):
        errors.append(f"catalog.stack: must be 1..{MAX_STACK} distinct lowercase tokens (for example html, react, remotion)")
        stack = []
    dependencies = _parse_dependencies(raw.get("dependencies", []), errors)
    licence = raw.get("license", "")
    if licence != "" and not _line(licence, MAX_LICENSE):
        errors.append(f"catalog.license: must be one line of at most {MAX_LICENSE} characters (an SPDX id is best)")
        licence = ""
    upstream = _parse_upstream(raw["upstream"], errors) if "upstream" in raw else None
    if errors or kind is None or compatibility is None:
        return None, errors
    return CatalogBlock(kind, compatibility, tuple(stack), dependencies, licence, upstream), []


def _parse_compatibility(raw: object, errors: list[str]) -> Mapping[Engine, Support] | None:
    if not isinstance(raw, dict) or not raw:
        errors.append("catalog.compatibility: must be a non-empty {engine: native|adapter|unsupported} object")
        return None
    parsed: dict[Engine, Support] = {}
    for key, value in raw.items():
        try:
            engine = Engine(key)
            parsed[engine] = Support(value)
        except ValueError:
            errors.append(f"catalog.compatibility: {str(key)[:40]!r}: engine must be one of "
                          f"{[e.value for e in Engine]} and support one of {[s.value for s in Support]}")
    return None if len(parsed) != len(raw) else parsed


def _parse_dependencies(raw: object, errors: list[str]) -> tuple[Dependency, ...]:
    if not isinstance(raw, list) or len(raw) > MAX_DEPENDENCIES:
        errors.append(f"catalog.dependencies: must be at most {MAX_DEPENDENCIES} {{name, version}} entries")
        return ()
    found: list[Dependency] = []
    for index, item in enumerate(raw):
        path = f"catalog.dependencies[{index}]"
        if not isinstance(item, dict) or set(item) != {"name", "version"}:
            errors.append(f"{path}: must be exactly {{name, version}}")
        elif (not isinstance(item["name"], str) or len(item["name"]) > MAX_DEP_NAME or not _DEP_NAME.fullmatch(item["name"])
              or not isinstance(item["version"], str) or not _DEP_VERSION.fullmatch(item["version"])):
            errors.append(f"{path}: name is a lowercase package name, version a short version or range (never empty)")
        else:
            found.append(Dependency(item["name"], item["version"]))
    if len({dep.name for dep in found}) != len(found):
        errors.append("catalog.dependencies: a package is listed once")
    return tuple(found)


def _parse_upstream(raw: object, errors: list[str]) -> Upstream | None:
    if (not isinstance(raw, dict) or not UPSTREAM_REQUIRED <= raw.keys() <= UPSTREAM_KEYS):
        errors.append(f"catalog.upstream: must be {{name, url}} with optional {sorted(UPSTREAM_KEYS - UPSTREAM_REQUIRED)}")
        return None
    bad = [key for key in raw if key != "url" and not _line(raw[key], MAX_UPSTREAM_TEXT)]
    if bad or not _is_http_url(raw["url"]):
        errors.append(f"catalog.upstream: {bad or ['url']} must be one line of at most {MAX_UPSTREAM_TEXT} characters "
                      "(url: http or https)")
        return None
    return Upstream(**{key: raw[key] for key in raw})


def check_body_kind(block: CatalogBlock, *, remotion: bool) -> list[str]:
    """Cross-check of the declaration against what the bundle IS (a declaration cannot contradict its own files).

    - Remotion source (`source`): `remotion` must be `native` or `adapter`; `slidecar` must not be `native`.
    - HTML bundle (`files`): `remotion` must not be `native`; `slidecar` must be `native` or `adapter` (omitted = unsupported
      = refused, like `legacy_html_compatibility()`), because a Slidecar bundle that Slidecar cannot run is not a prefab.
    """

    remotion_support = _classify(block.compatibility, Engine.REMOTION)
    slidecar_support = _classify(block.compatibility, Engine.SLIDECAR)
    errors: list[str] = []
    if remotion:
        if remotion_support is Support.UNSUPPORTED:
            errors.append("catalog.compatibility: a Remotion source must declare remotion native or adapter")
        if slidecar_support is Support.NATIVE:
            errors.append("catalog.compatibility: a Remotion source cannot be slidecar native (adapter at most)")
    else:
        if remotion_support is Support.NATIVE:
            errors.append("catalog.compatibility: an HTML bundle cannot be remotion native (adapter at most)")
        if slidecar_support is Support.UNSUPPORTED:
            errors.append("catalog.compatibility: an HTML bundle must declare slidecar native or adapter")
    return errors


def block_to_dict(block: CatalogBlock) -> dict[str, Any]:
    body: dict[str, Any] = {"type": block.type.value,
                            "compatibility": {e.value: s.value for e, s in block.compatibility.items()},
                            "stack": list(block.stack),
                            "dependencies": [{"name": d.name, "version": d.version} for d in block.dependencies],
                            "license": block.license or None,
                            "upstream": None if block.upstream is None else block.upstream.to_dict()}
    return body


def semantic_type_of_legacy(family: str, *, remotion: bool) -> SemanticType:
    if remotion:
        return SemanticType.COMPOSITION
    return _LEGACY_FAMILY_TYPE.get(family, SemanticType.COMPONENT)


def derive_catalog(*, block: CatalogBlock | None, family: str, remotion: bool) -> dict[str, Any]:
    """The catalog view of one manifest: declared (v3) or derived at read from an older version. Never written back.

    `compatibility` always lists EVERY engine: an engine the manifest does not declare reads `unsupported` (visible, not
    guessed); the legacy HTML prefab is the one explicit exception (`legacy_html_compatibility`).
    """

    if block is not None:
        declared: Mapping[Engine, Support] = block.compatibility
        body = block_to_dict(block)
        body["declared"] = True
    else:
        declared = {Engine.REMOTION: Support.NATIVE} if remotion else legacy_html_compatibility()
        body = {"type": semantic_type_of_legacy(family, remotion=remotion).value,
                "stack": list(REMOTION_STACK if remotion else HTML_STACK), "dependencies": [], "license": None,
                "upstream": None, "declared": False}
    body["compatibility"] = {engine.value: _classify(declared, engine).value for engine in Engine}
    return body


def _classify(declared: Mapping[Engine, Support], engine: Engine) -> Support:
    try:
        return classify_compatibility(declared, engine)
    except PresentationStudioError:  # a block parsed here is valid; fail closed all the same
        return Support.UNSUPPORTED


def matches(view: Mapping[str, Any], *, kind: str | None = None, engine: str | None = None,
            stack: str | None = None) -> bool:
    """Server-side filters of `GET /v1/prefabs`: an engine matches when it is `native` or `adapter`, never `unsupported`."""

    if kind is not None and view["type"] != kind:
        return False
    if engine is not None and view["compatibility"].get(engine, Support.UNSUPPORTED.value) == Support.UNSUPPORTED.value:
        return False
    return stack is None or stack in view["stack"]
