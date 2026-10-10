"""Presentation Studio: the Remotion scene generator behind the authoring draft (handoff jarvis-remotion-presentation-integration, Slice 15).

The brain writes the TSX; Core makes it a **Remotion source** of the Studio and judges it. This module is the pure half of that:

- `generate_source(key, raw, pin)` : the brain's `{title, files, props?, data?, sample?, composition?, assets?, live_refs?, inspiration?}`
  becomes the candidate `{manifest, sources, assets}` (manifest v2, v3 with the catalog block) that `PrefabService.save` and
  `parse_candidate` already take (Slice 05 `build_candidate`). No second source format, no second publisher.
- **The art direction reaches the scene as the reserved `theme` prop.** Remotion scenes get no CSS variables from the host (the sandbox
  has none), so the direction is *data*: Core declares `props.theme` in every generated manifest (`THEME_SCHEMA`), fills it per variant
  from that variant's art direction (`theme_values`, `apply_theme`) and the source reads it (`props.theme.accent`). A direction that
  differs from another differs by this prop, which is exactly what an exploratory candidate is. A brain that declares `theme` itself is
  refused: the binding is Core's, not the model's.
- **Catalog block v3** (Slice 17), written by Core: `composition`, Remotion `native`, Slidecar `unsupported`, stack and dependencies of the
  shipped engine. Never an `upstream` block: only the importer (Slice 18) writes provenance of an upstream template.
- **Live Board references** (Slice 09) are declared in `src/live-refs.json`; here only their grammar is judged (`parse_declaration`).
  Which Board may be read is Core's decision (`authorised_boards`), never the declaration's.
- **Inspiration** : `inspiration {id, version}` names an existing Remotion source the author drew on. Core accepts it only when that source
  carries a Core-verified upstream provenance (Slice 18) and records the lineage as `derived_from`; nothing is ever copied or chosen for the
  author (`remotion-import.md`: an upstream template is optional inspiration, only when selected).

Everything the brain wrote is untrusted data. Pure but for the hash of the content (the id is derived from it, so the same source is the
same id and a different one a different id).
"""

from __future__ import annotations

from collections.abc import Mapping
import base64
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from jarvis.domain.prefab import PrefabRef, canonical_json
from jarvis.domain.presentation_live_refs import LiveRef, LiveRefError, parse_declaration, LIVE_REFS_PATH
from jarvis.domain.presentation_studio_art_direction import ArtDirectionProfile
from jarvis.domain.presentation_studio_authoring_kit import KIT_PATH, KIT_SOURCE, KIT_VERSION
from jarvis.domain.presentation_studio_checks import _exact_keys, _fail
from jarvis.domain.remotion_source import (
    ASSET_ROOT, COMPOSITION_ID, DEFAULT_ENTRY, MODULE_ROOT, Composition, EnginePin, build_candidate,
)

#: Reserved prop: the art direction of the variant, as data. Declared by Core; the source reads it.
THEME_PROP = "theme"
NAMESPACE = "presentation-studio."
#: What the model may put in the generator object (exact keys, like every other object of the draft).
SPEC_REQUIRED = frozenset({"title", "files"})
SPEC_OPTIONAL = frozenset({"description", "composition", "props", "data", "sample", "assets", "live_refs", "inspiration"})
COMPOSITION_KEYS = frozenset({"width", "height", "fps", "duration_in_frames"})
DEFAULT_COMPOSITION = {"width": 1280, "height": 720, "fps": 30, "duration_in_frames": 150}
MAX_TITLE = 80
MAX_DESCRIPTION = 200
MAX_LIVE_REFS = 8
CATALOG_STACK = ("react", "remotion", "typescript")

#: The shape and neutral defaults of the `theme` prop. Colours are `#rrggbb` (the art direction contract), the rest bounded tokens.
NEUTRAL_THEME: dict[str, Any] = {
    "background": "#0b1020", "text": "#e8ecf4", "accent": "#6ee7ff", "muted": "#9aa4b8", "body": "#cfd6e4",
    "surface": "rgba(255,255,255,0.08)", "font_heading": "system-ui, sans-serif", "font_body": "system-ui, sans-serif",
    "heading_weight": 700, "body_weight": 400, "radius": 12, "gap": 24, "scale": 1.0, "enter_ms": 400, "stagger_ms": 80,
    "easing": "ease_out", "transition": "fade"}


def _theme_schema() -> dict[str, Any]:
    colour = lambda key: {"type": "color", "default": NEUTRAL_THEME[key]}  # noqa: E731 - a table of one-line schemas
    text = lambda key, limit: {"type": "string", "max_length": limit, "default": NEUTRAL_THEME[key]}  # noqa: E731
    whole = lambda key, low, high: {"type": "integer", "min": low, "max": high, "default": NEUTRAL_THEME[key]}  # noqa: E731
    return {"type": "object", "properties": {
        "background": colour("background"), "text": colour("text"), "accent": colour("accent"), "muted": colour("muted"),
        "body": colour("body"), "surface": text("surface", 40), "font_heading": text("font_heading", 200),
        "font_body": text("font_body", 200), "heading_weight": whole("heading_weight", 100, 900),
        "body_weight": whole("body_weight", 100, 900), "radius": whole("radius", 0, 64), "gap": whole("gap", 0, 96),
        "scale": {"type": "number", "min": 0.5, "max": 2.0, "default": NEUTRAL_THEME["scale"]},
        "enter_ms": whole("enter_ms", 0, 5000), "stagger_ms": whole("stagger_ms", 0, 2000), "easing": text("easing", 24),
        "transition": text("transition", 16)}}


THEME_SCHEMA = _theme_schema()


def theme_values(profile: ArtDirectionProfile) -> dict[str, Any]:
    """The `theme` prop of one art direction. Deterministic and made only of tokens the art direction already validated (closed
    vocabularies, `#rrggbb`, bounded integers): no free text, no URL, no CSS."""

    variables = profile.to_theme_variables()
    palette, typography, motion = profile.palette, profile.typography, profile.motion
    return {
        "background": palette.background, "text": palette.text, "accent": palette.accent, "muted": palette.muted,
        "body": variables["--jv-body"], "surface": variables["--jv-surface"], "font_heading": typography.heading.css(),
        "font_body": typography.body.css(), "heading_weight": typography.heading_weight, "body_weight": typography.body_weight,
        "radius": profile.shapes.radius_px, "gap": int(variables["--jv-gap"].removesuffix("px")),
        "scale": float(variables["--jv-scale"]), "enter_ms": motion.enter_ms, "stagger_ms": motion.stagger_ms,
        "easing": motion.easing.value, "transition": motion.transition.value}


def apply_theme(props: Mapping[str, Any], profile: ArtDirectionProfile | None, patch: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The scene's props with the art direction under them: `theme` = the direction's tokens, then what the scene sets, then what a
    candidate's `scenes_patch` sets (a key at a time: a draft may nudge `accent` and leave the rest to the direction)."""

    base = dict(theme_values(profile)) if profile is not None else {}
    for layer in (props.get(THEME_PROP), (patch or {}).get(THEME_PROP)):
        if isinstance(layer, Mapping):
            base.update(layer)
    return {**props, THEME_PROP: base} if base else dict(props)


@dataclass(frozen=True, slots=True)
class GeneratedSource:
    """The result of `generate_source`: the candidate, plus what the gate and Core read without re-parsing it."""

    candidate: dict[str, Any]
    prefab_id: str
    live_refs: tuple[LiveRef, ...]
    inspiration: PrefabRef | None


def source_id(key: str, title: str, files: Mapping[str, Any], props: object, composition: Mapping[str, Any]) -> str:
    """`presentation-studio.rm-<key>-<8 hex of the content>`: inside the retention namespace, stable for one content, distinct for two."""

    digest = hashlib.sha256(canonical_json({"key": key, "title": title, "props": props, "composition": dict(composition),
                                            "files": {path: hashlib.sha256(
                                                body if isinstance(body, bytes) else str(body).encode("utf-8", "replace")).hexdigest()
                                                      for path, body in sorted(files.items())}}).encode("utf-8")).hexdigest()
    return f"{NAMESPACE}rm-{key[:18]}-{digest[:8]}"


def _composition(raw: object, where: str) -> Composition:
    data = _exact_keys(raw if raw is not None else {}, where, set(), COMPOSITION_KEYS)
    merged = {**DEFAULT_COMPOSITION, **data}
    return Composition(COMPOSITION_ID_DEFAULT, merged["width"], merged["height"], merged["fps"], merged["duration_in_frames"])


COMPOSITION_ID_DEFAULT = "Scene"
assert COMPOSITION_ID.fullmatch(COMPOSITION_ID_DEFAULT)


def _inspiration(raw: object, where: str) -> PrefabRef | None:
    if raw is None:
        return None
    data = _exact_keys(raw, where, {"id", "version"})
    try:
        return PrefabRef.from_dict(data, where)
    except Exception as exc:  # noqa: BLE001 - argued: PrefabRef raises its own typed refusals; here they are one schema problem
        raise _fail(f"{where} must be an existing prefab pin {{id, version}}") from exc


def _live_refs(raw: object, where: str) -> tuple[list[dict[str, str]], tuple[LiveRef, ...]]:
    if raw is None:
        return [], ()
    if not isinstance(raw, list) or len(raw) > MAX_LIVE_REFS:
        raise _fail(f"{where} must be a list of at most {MAX_LIVE_REFS} references")
    refs = []
    for index, item in enumerate(raw):
        entry = _exact_keys(item, f"{where}[{index}]", {"name", "ref"})
        refs.append({"name": entry["name"], "ref": entry["ref"]})
    declaration = {"format": "jarvis.live-refs/1", "refs": refs}
    try:
        parsed = parse_declaration(json.dumps(declaration).encode("utf-8"))
    except LiveRefError as exc:
        raise _fail(f"{where}: {exc.code.value}: {exc}") from None
    return refs, parsed


def _files(raw: object, where: str, live_declared: bool) -> dict[str, str]:
    if not isinstance(raw, dict) or not raw:
        raise _fail(f"{where} must be an object {{path: text}} with at least {DEFAULT_ENTRY}")
    if DEFAULT_ENTRY not in raw:
        raise _fail(f"{where} must hold the entry module {DEFAULT_ENTRY} (export default a React component)")
    for path, body in raw.items():
        if not isinstance(path, str) or not path.startswith(MODULE_ROOT):
            raise _fail(f"{where}: modules live under {MODULE_ROOT} (assets go in `assets`, under {ASSET_ROOT})")
        if not isinstance(body, str):
            raise _fail(f"{where}: every module is text")
    if KIT_PATH in raw:
        raise _fail(f"{where}: {KIT_PATH} is added by Core (the motion kit of the art direction): import it, do not provide it")
    if live_declared and LIVE_REFS_PATH in raw:
        raise _fail(f"{where}: {LIVE_REFS_PATH} is written from `live_refs`: give one or the other")
    return dict(raw)


def _props_schema(raw: object, where: str) -> dict[str, Any]:
    schema = raw if raw is not None else {"type": "object", "properties": {}}
    if not isinstance(schema, dict) or schema.get("type") != "object" or not isinstance(schema.get("properties", {}), dict):
        raise _fail(f"{where} must be an object schema {{type: object, properties: {{...}}}}")
    if THEME_PROP in schema.get("properties", {}):
        raise _fail(f"{where}: `{THEME_PROP}` is reserved: Core declares it and fills it from the art direction")
    return {**schema, "properties": {**schema.get("properties", {}), THEME_PROP: THEME_SCHEMA}}


def _example_of(schema: object, depth: int = 0) -> Any:
    """A valid value for a schema node, for the library's sample: the author writes the real content in the scenes, not in a sample."""

    if not isinstance(schema, dict) or depth > 4:
        return None
    kind = schema.get("type")
    if "default" in schema:
        return schema["default"]
    if kind in ("string", "text"):
        return "Exemple"[: int(schema.get("max_length", 7))]
    if kind in ("integer", "number"):
        return schema.get("min", 0)
    if kind == "boolean":
        return False
    if kind == "color":
        return "#000000"
    if kind == "enum":
        return (schema.get("values") or [None])[0]
    if kind == "array":
        return []
    if kind == "object":
        required = schema.get("required") or []
        return {name: _example_of(sub, depth + 1) for name, sub in (schema.get("properties") or {}).items() if name in required}
    return None


def _sample(schema: object, given: object) -> dict[str, Any]:
    """The author's sample, completed with a valid value for every REQUIRED key it left out."""

    base = _example_of(schema)
    return {**(base if isinstance(base, dict) else {}), **(given if isinstance(given, dict) else {})}


def generate_source(key: str, raw: object, pin: EnginePin, where: str) -> GeneratedSource:
    """`{title, files, ...}` -> the candidate of a Remotion source. Raises `PresentationStudioError` (a schema problem) on a bad shape;
    the manifest, the module paths and the bounds are then judged ONCE by `parse_candidate` (the caller), with every error."""

    data = _exact_keys(raw, where, SPEC_REQUIRED, SPEC_OPTIONAL)
    title = data["title"]
    if not isinstance(title, str) or not title or len(title) > MAX_TITLE or not title.isprintable() or title != title.strip():
        raise _fail(f"{where}.title must be one printable line of at most {MAX_TITLE} characters")
    description = data.get("description", "")
    if not isinstance(description, str) or len(description) > MAX_DESCRIPTION or not description.isprintable():
        raise _fail(f"{where}.description must be one printable line of at most {MAX_DESCRIPTION} characters")
    refs_raw, refs = _live_refs(data.get("live_refs"), f"{where}.live_refs")
    files: dict[str, Any] = _files(data["files"], f"{where}.files", bool(refs_raw))
    files[KIT_PATH] = KIT_SOURCE
    if refs_raw:
        files[LIVE_REFS_PATH] = json.dumps({"format": "jarvis.live-refs/1", "refs": refs_raw}, indent=2, ensure_ascii=False) + "\n"
    assets = data.get("assets", {})
    if not isinstance(assets, dict):
        raise _fail(f"{where}.assets must be an object {{public/<name>: base64}}")
    for path, body in assets.items():
        if not isinstance(path, str) or not path.startswith(ASSET_ROOT) or not isinstance(body, str):
            raise _fail(f"{where}.assets: {{public/<name>: base64 text}}")
        try:
            files[path] = base64.b64decode(body, validate=True)
        except ValueError:
            raise _fail(f"{where}.assets: `{path[:60]}` is not base64") from None
    composition = _composition(data.get("composition"), f"{where}.composition")
    props = _props_schema(data.get("props"), f"{where}.props")
    sample = data.get("sample", {})
    sample = _exact_keys(sample, f"{where}.sample", set(), {"props", "data"})
    sample_props = {**dict(sample.get("props", {})), THEME_PROP: dict(NEUTRAL_THEME)} if isinstance(sample.get("props", {}), dict) else None
    if sample_props is None:
        raise _fail(f"{where}.sample.props must be an object")
    prefab_id = source_id(key, title, files, props, {**composition.to_dict(), "kit": KIT_VERSION})
    catalog = {"type": "composition", "compatibility": {"remotion": "native", "slidecar": "unsupported"}, "stack": list(CATALOG_STACK),
               "dependencies": [{"name": "remotion", "version": pin.version}]}
    candidate = build_candidate(
        prefab_id=prefab_id, title=title, composition=composition, engine=pin, files=files, props=props, data=data.get("data"),
        sample={"props": _sample(props, sample_props), "data": _sample(data.get("data"), sample.get("data"))}, description=description, catalog=catalog)
    return GeneratedSource(candidate, prefab_id, refs, _inspiration(data.get("inspiration"), f"{where}.inspiration"))


__all__ = ["CATALOG_STACK", "DEFAULT_COMPOSITION", "GeneratedSource", "NAMESPACE", "NEUTRAL_THEME", "SPEC_OPTIONAL", "SPEC_REQUIRED",
           "THEME_PROP", "THEME_SCHEMA", "apply_theme", "generate_source", "source_id", "theme_values"]
