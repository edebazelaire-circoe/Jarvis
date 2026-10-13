"""Master Remotion project planner: the single pure authority on whether a Presentation Variant is master-ready and, when it is, exactly
which project and composition to build (`docs/remotion-master-project.md` §2-5; handoff jarvis-remotion-master-project-studio-export,
Slice 03). Pure: no disk, no process, no clock.

Two input builders feed one planner:

- `live_inputs(presentation, variant, pins)`: the current variant, its presentation engine, and each active pin already resolved by Core
  (`jarvis.core.remotion_master_project` reads them through `PrefabService`, guards and SHA-256 checks included);
- `frozen_inputs(package)`: a verified `jarvis.presentation-snapshot/1` package; each active pin is revalidated with `parse_source` and its
  digest compared with the manifest's. Only the ACTIVE pin of each scene is mounted, in `variant.json` order (`held_pins` are ignored).

`plan_master(inputs)` checks the contract's eleven reasons in their fixed order and reports the first failing one. A ready plan carries the
`project_key`, the master composition, the scene timeline, the merged `public/**` and the workspace totals (generated files included,
`remotion_master_generated`). `MasterProjectPlan.to_wire()` is the only view that leaves Core; it never holds a path of the machine.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import posixpath
import re
from typing import Any

from jarvis.domain.presentation_render import MAX_MASTER_RENDER_FRAMES, RenderError, RenderErrorCode
from jarvis.domain.presentation_render_plan import LIVE_PUBLIC_DIR, merge_props
from jarvis.domain.presentation_snapshot_package import FrozenPackage
from jarvis.domain.presentation_studio import (
    Presentation, PresentationStudioError, PresentationVariant, StudioScene, parse_presentation, parse_variant,
)
from jarvis.domain.presentation_studio_engine import Engine
from jarvis.domain.remotion_import import resolve_relative, specifiers, strip_comments
from jarvis.domain.remotion_isolation import loader_finding
from jarvis.domain.remotion_master_generated import MASTER_COMPOSITION_ID, GeneratedScene, generated_files
from jarvis.domain.remotion_source import (
    MODULE_ROOT, RemotionSource, RemotionSourceError, parse_source, parse_source_block, path_set_problems,
)
from jarvis.domain.remotion_studio_workspace import refused_imports

#: Bumped whenever the generated files change for the same inputs (it is the first `project_key` input).
MASTER_GENERATOR_VERSION = 1
#: `MAX_MASTER_RENDER_FRAMES` (9000) lives with the render bounds in `presentation_render` and is re-exported here.
#: Whole workspace, generated files included: the minimum of the Studio workspace and snapshot package bounds.
MAX_MASTER_FILES = 400
MAX_MASTER_BYTES = 64 * 1024 * 1024
PROJECT_KEY = re.compile(r"mpk_[0-9a-f]{24}\Z")
SCENES_DIR = "src/scenes/"
MAX_DETAIL_CHARS = 300
#: Textual checks (defence in depth, not a guarantee: a computed name such as `remotion["get" + "InputProps"]` escapes them; the
#: isolation guard refuses the obfuscation patterns it knows).
_INPUT_PROPS = re.compile(r"\bgetInputProps\b")

__all__ = ["MASTER_COMPOSITION_ID", "MASTER_GENERATOR_VERSION", "MAX_MASTER_BYTES", "MAX_MASTER_FILES", "MAX_MASTER_RENDER_FRAMES",
           "MasterAsset", "MasterComposition", "MasterInputs", "MasterProjectPlan", "MasterReason", "MasterScene", "MasterStatus",
           "MasterTotals", "PinKind", "PinSource", "canonical_json", "frozen_inputs", "live_inputs", "plan_master", "props_digest"]


class MasterStatus(StrEnum):
    READY = "ready"
    INCOMPATIBLE = "incompatible"


class MasterReason(StrEnum):
    """The planner's reasons, declared in the order they are checked (§ 3)."""

    EMPTY = "master_empty"
    ENGINE_NOT_REMOTION = "master_engine_not_remotion"
    SOURCE_UNAVAILABLE = "master_source_unavailable"
    ENGINE_MISMATCH = "master_engine_mismatch"
    FPS_MISMATCH = "master_fps_mismatch"
    DIMENSIONS_MISMATCH = "master_dimensions_mismatch"
    SOURCE_IMPORT_REFUSED = "master_source_import_refused"
    INPUT_PROPS_READER = "master_input_props_reader"
    PUBLIC_ASSET_COLLISION = "master_public_asset_collision"
    PROJECT_TOO_LARGE = "master_project_too_large"
    TOO_LONG = "master_too_long"


class PinKind(StrEnum):
    REMOTION = "remotion"
    NOT_REMOTION = "not_remotion"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class PinSource:
    """One exact pin as the caller resolved it. `REMOTION`: `source` parsed and guarded, `digest` its `source_digest`, the manifest's
    props/data defaults; otherwise `problem` is a short English reason without any path (it ends up in `detail`)."""

    kind: PinKind
    source: RemotionSource | None = None
    digest: str = ""
    props_defaults: Mapping[str, Any] = field(default_factory=dict)
    data_defaults: Mapping[str, Any] = field(default_factory=dict)
    problem: str = ""

    @classmethod
    def remotion(cls, source: RemotionSource, *, props_defaults: Mapping[str, Any] | None = None,
                 data_defaults: Mapping[str, Any] | None = None) -> PinSource:
        return cls(PinKind.REMOTION, source, source.digest, dict(props_defaults or {}), dict(data_defaults or {}))

    @classmethod
    def not_remotion(cls, problem: str = "the pinned version is not a Remotion source") -> PinSource:
        return cls(PinKind.NOT_REMOTION, problem=problem)

    @classmethod
    def unavailable(cls, problem: str) -> PinSource:
        return cls(PinKind.UNAVAILABLE, problem=problem)


@dataclass(frozen=True, slots=True)
class MasterInputs:
    """Everything the planner reads. `live_copies`: frozen Board copies per pin (`{name+ext: bytes}`, render only, mounted under
    `public/live/`); empty for a live variant."""

    presentation_id: str
    variant_id: str
    variant_revision: int
    engine: Engine
    scenes: tuple[StudioScene, ...]
    pins: Mapping[tuple[str, int], PinSource]
    live_copies: Mapping[tuple[str, int], Mapping[str, bytes]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MasterComposition:
    width: int
    height: int
    fps: int
    duration_in_frames: int
    composition_id: str = MASTER_COMPOSITION_ID

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.composition_id, "width": self.width, "height": self.height, "fps": self.fps,
                "duration_in_frames": self.duration_in_frames}


@dataclass(frozen=True, slots=True)
class MasterScene:
    """One mounted scene. `source` and `props` (merged defaults + instance, what the generated composition passes) are for Slice 04's
    materialization; they are not part of the wire view."""

    scene_id: str
    prefab_id: str
    version: int
    source_digest: str
    engine_version: str
    from_frame: int
    duration_in_frames: int
    entry: str
    mount: str
    props_digest: str
    source: RemotionSource = field(compare=False, repr=False)
    props: Mapping[str, Any] = field(compare=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"scene_id": self.scene_id, "prefab_id": self.prefab_id, "version": self.version, "source_digest": self.source_digest,
                "engine_version": self.engine_version, "from_frame": self.from_frame, "duration_in_frames": self.duration_in_frames,
                "entry": self.entry, "mount": self.mount}


@dataclass(frozen=True, slots=True)
class MasterAsset:
    """One merged `public/**` file. `live`: a frozen Board copy (`public/live/**`, render only): in the collision check and the totals,
    never in the `project_key`."""

    path: str
    sha256: str
    size: int
    scene_ids: tuple[str, ...]
    live: bool
    data: bytes = field(compare=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "bytes": self.size, "scene_ids": list(self.scene_ids)}


@dataclass(frozen=True, slots=True)
class MasterTotals:
    files: int
    bytes: int

    def to_dict(self) -> dict[str, int]:
        return {"files": self.files, "bytes": self.bytes}


@dataclass(frozen=True, slots=True)
class MasterProjectPlan:
    presentation_id: str
    variant_id: str
    variant_revision: int
    status: MasterStatus
    generator_version: int = MASTER_GENERATOR_VERSION
    reason: MasterReason | None = None
    detail: str = ""
    scene_ids: tuple[str, ...] = ()
    project_key: str | None = None
    composition: MasterComposition | None = None
    scenes: tuple[MasterScene, ...] = ()
    public_assets: tuple[MasterAsset, ...] = ()
    totals: MasterTotals | None = None
    #: The generated set (`remotion_master_generated`), counted in `totals`; reused by Slice 04, never on the wire.
    generated: Mapping[str, bytes] = field(default_factory=dict, compare=False, repr=False)

    @property
    def ready(self) -> bool:
        return self.status is MasterStatus.READY

    def to_wire(self) -> dict[str, Any]:
        """The plan view of § 2: identifiers, status, reason or key, composition, timeline, merged assets, totals. No path of the machine
        (every path is workspace-relative), no source bytes, no props."""

        wire: dict[str, Any] = {"presentation_id": self.presentation_id, "variant_id": self.variant_id,
                                "variant_revision": self.variant_revision, "generator_version": self.generator_version,
                                "status": self.status.value}
        if not self.ready:
            assert self.reason is not None
            wire.update(reason=self.reason.value, detail=self.detail, scene_ids=list(self.scene_ids))
            return wire
        assert self.composition is not None and self.totals is not None
        wire.update(project_key=self.project_key, composition=self.composition.to_dict(), scenes=[s.to_dict() for s in self.scenes],
                    public_assets=[a.to_dict() for a in self.public_assets], totals=self.totals.to_dict())
        return wire


# ------------------------------------------------------------------ key

def canonical_json(value: Any) -> bytes:
    """§ 5: `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True)`."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def props_digest(scene: StudioScene) -> str:
    """SHA-256 of the canonical JSON of the scene's INSTANCE values `{"props": …, "data": …}` (defaults are bound by the source)."""

    return hashlib.sha256(canonical_json({"props": scene.props, "data": scene.data})).hexdigest()


def _project_key(composition: MasterComposition, scenes: tuple[MasterScene, ...], assets: tuple[MasterAsset, ...]) -> str:
    inputs = {"generator_version": MASTER_GENERATOR_VERSION,
              "spec": [composition.width, composition.height, composition.fps],
              "scenes": [[s.scene_id, s.prefab_id, s.version, s.source_digest, s.props_digest] for s in scenes],
              "public_assets": sorted([a.path, a.sha256] for a in assets if not a.live)}
    return "mpk_" + hashlib.sha256(canonical_json(inputs)).hexdigest()[:24]


# ------------------------------------------------------------------ input builders

def live_inputs(presentation: Presentation, variant: PresentationVariant, pins: Mapping[tuple[str, int], PinSource]) -> MasterInputs:
    """Inputs of a live variant. `pins` must name every active pin `(prefab_id, version)`; a missing one reads as unavailable."""

    return MasterInputs(variant.presentation_id, variant.variant_id, variant.revision, presentation.engine, tuple(variant.scenes),
                        dict(pins))


def _frozen_document(package: FrozenPackage, path: str) -> Any:
    try:
        return json.loads(package.files[path].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, ValueError):
        raise RenderError(RenderErrorCode.SNAPSHOT_INVALID, f"{path} is missing or unreadable in the package") from None


def _frozen_pin(package: FrozenPackage, row: Mapping[str, Any] | None, pin: tuple[str, int]) -> PinSource:
    label = f"{pin[0]}@{pin[1]}"
    if row is None:
        return PinSource.unavailable(f"{label} is not in the snapshot package")
    if row.get("kind") != "remotion":
        return PinSource.not_remotion(f"{label} is not a Remotion source")
    root = f"prefabs/{pin[0]}/{pin[1]}/"
    try:
        block = parse_source_block(json.loads(package.files[root + "source.json"].decode("utf-8")))
        files = {path[len(root):]: data for path, data in package.files.items()
                 if path.startswith(root) and path[len(root):].startswith(("src/", "public/"))}
        source = parse_source(block, files)
    except (KeyError, UnicodeDecodeError, ValueError, RemotionSourceError) as exc:
        # The real cause stays in the record: the first message of the refusal (source-relative paths only, never a machine path).
        reason = exc.errors[0] if isinstance(exc, RemotionSourceError) else "its source block is missing or unreadable"
        return PinSource.unavailable(f"{label} no longer passes validation: {reason}")
    if source.digest != row.get("source_digest"):
        return PinSource.unavailable(f"{label}: the frozen files do not match the recorded source digest")
    return PinSource.remotion(source, props_defaults=row.get("props_defaults") if isinstance(row.get("props_defaults"), dict) else {},
                              data_defaults=row.get("data_defaults") if isinstance(row.get("data_defaults"), dict) else {})


def frozen_inputs(package: FrozenPackage) -> MasterInputs:
    """Inputs of a verified snapshot package (`read_package`). Only the active pin of each scene is resolved and mounted. A package whose
    presentation documents are unreadable is `presentation_render_snapshot_invalid` (corruption, not incompatibility)."""

    raw_presentation = _frozen_document(package, "presentation/presentation.json")
    raw_variant = _frozen_document(package, "presentation/variant.json")
    try:
        presentation = parse_presentation(raw_presentation)
        variant = parse_variant(raw_variant)
    except (PresentationStudioError, ValueError, TypeError, KeyError) as exc:
        raise RenderError(RenderErrorCode.SNAPSHOT_INVALID, f"the frozen presentation documents are invalid: {str(exc)[:160]}") from None
    rows = {(r.get("prefab_id"), r.get("version")): r for r in package.manifest.get("prefabs", []) if isinstance(r, dict)}
    pins: dict[tuple[str, int], PinSource] = {}
    live: dict[tuple[str, int], dict[str, bytes]] = {}
    for scene in variant.scenes:
        pin = (scene.prefab.prefab_id, scene.prefab.version)
        if pin in pins:
            continue
        pins[pin] = _frozen_pin(package, rows.get(pin), pin)
        prefix = f"prefabs/{pin[0]}/{pin[1]}/live/"
        live[pin] = {path[len(prefix):]: data for path, data in package.files.items() if path.startswith(prefix)}
    return MasterInputs(variant.presentation_id, variant.variant_id, variant.revision, presentation.engine, tuple(variant.scenes),
                        pins, live)


# ------------------------------------------------------------------ planner

def _clip(text: str) -> str:
    return text if len(text) <= MAX_DETAIL_CHARS else text[: MAX_DETAIL_CHARS - 1] + "…"


def _name(position: int, scene_id: str) -> str:
    return f"scene {position} ({scene_id})"


def _incompatible(inputs: MasterInputs, reason: MasterReason, detail: str, scene_ids: tuple[str, ...] = ()) -> MasterProjectPlan:
    return MasterProjectPlan(inputs.presentation_id, inputs.variant_id, inputs.variant_revision, MasterStatus.INCOMPATIBLE,
                             reason=reason, detail=_clip(detail), scene_ids=scene_ids)


def _named_list(items: list[tuple[int, str]]) -> str:
    shown = ", ".join(_name(p, s) for p, s in items[:4])
    return shown + (f" and {len(items) - 4} more" if len(items) > 4 else "")


def _import_problem(scene_id: str, source: RemotionSource) -> str | None:
    """§ 8 a: bare specifiers only from `SCENE_ALLOWED_IMPORTS` (`refused_imports`, the Studio publish check); relative specifiers must
    resolve to a module of this scene's own source AS MOUNTED under `src/scenes/<scene_id>/` (`resolve_relative`, the importer's resolver:
    `../src/lib/x` from `src/Scene.tsx` resolves standalone but not once mounted, so it is refused); no dynamic `import(...)` /
    `require` in any form (call, reference, alias, `require.context`), no `.context(`, `import.meta`, `module.hot`, `__webpack_*` nor ASCII
    backslash-u escape (an escaped `require` IS `require`): the isolation guard's `LOADER_RULES`, re-run here over the raw text (comments included)."""

    texts = source.module_texts()
    refused = refused_imports(texts)
    if refused:
        return f"imports {refused[0]}, outside the allowed modules"
    mounted = {_mounted(scene_id, path): text for path, text in texts.items()}
    for (path, text), mounted_path in zip(texts.items(), mounted):
        rule = loader_finding(text)
        if rule is not None:
            return f"{path} breaks {rule.code} (a dynamic import, require in any form, .context() or an escaped name), which the master cannot check"
        for spec in specifiers(text):
            if spec.startswith(".") and resolve_relative(posixpath.dirname(mounted_path), spec, mounted) is None:
                return f"{path} imports {spec[:80]!r}, which is not a module of its own source once mounted"
    return None


def _reads_input_props(source: RemotionSource) -> str | None:
    for path, text in source.module_texts().items():
        if _INPUT_PROPS.search(strip_comments(text)):
            return path
    return None


def _mounted(scene_id: str, path: str) -> str:
    return SCENES_DIR + scene_id + "/" + path.removeprefix(MODULE_ROOT)


def plan_master(inputs: MasterInputs) -> MasterProjectPlan:
    """The plan of § 2: the first failing check of § 3, or a ready plan with its key, composition, timeline, assets and totals."""

    scenes = inputs.scenes
    if not scenes:
        return _incompatible(inputs, MasterReason.EMPTY, "the variant has no scene")
    if inputs.engine is not Engine.REMOTION:
        return _incompatible(inputs, MasterReason.ENGINE_NOT_REMOTION, f"the presentation engine is {inputs.engine.value}, not remotion")
    resolved = [(position, scene, inputs.pins.get((scene.prefab.prefab_id, scene.prefab.version),
                                                  PinSource.unavailable(f"{scene.prefab.prefab_id}@{scene.prefab.version} was not resolved")))
                for position, scene in enumerate(scenes, start=1)]
    for kind, reason in ((PinKind.NOT_REMOTION, MasterReason.ENGINE_NOT_REMOTION), (PinKind.UNAVAILABLE, MasterReason.SOURCE_UNAVAILABLE)):
        failing = [(p, s, pin) for p, s, pin in resolved if pin.kind is kind]
        if failing:
            first = failing[0]
            detail = f"{_named_list([(p, s.scene_id) for p, s, _ in failing])}: {first[2].problem}"
            return _incompatible(inputs, reason, detail, tuple(s.scene_id for _, s, _ in failing))
    sources = [(p, s, pin, pin.source) for p, s, pin in resolved]
    assert all(source is not None for *_, source in sources)
    engines = {(src.block.engine.version, src.block.engine.lock_sha256) for *_, src in sources}
    if len(engines) > 1:
        versions = sorted({version for version, _ in engines})
        what = f"versions {', '.join(versions)}" if len(versions) > 1 else f"version {versions[0]} with {len(engines)} different locks"
        return _incompatible(inputs, MasterReason.ENGINE_MISMATCH,
                             f"the scenes were written for {len(engines)} different engine pins ({what})",
                             tuple(s.scene_id for _, s, _, _ in sources))
    for reason, label, read in ((MasterReason.FPS_MISMATCH, "fps", lambda c: f"{c.fps}"),
                                (MasterReason.DIMENSIONS_MISMATCH, "size", lambda c: f"{c.width}x{c.height}")):
        values = [(p, s.scene_id, read(src.block.composition)) for p, s, _, src in sources]
        if len({v for *_, v in values}) > 1:
            first = values[0][2]
            odd = [(p, sid) for p, sid, v in values if v != first]
            return _incompatible(inputs, reason, f"{_name(values[0][0], values[0][1])} declares {label} {first}; "
                                                 f"{_named_list(odd)} declare{'s' if len(odd) == 1 else ''} another",
                                 tuple(sid for _, sid, _ in values))
    for p, s, _, src in sources:
        problem = _import_problem(s.scene_id, src)
        if problem:
            return _incompatible(inputs, MasterReason.SOURCE_IMPORT_REFUSED, f"{_name(p, s.scene_id)}: {problem}", (s.scene_id,))
    for p, s, _, src in sources:
        path = _reads_input_props(src)
        if path:
            return _incompatible(inputs, MasterReason.INPUT_PROPS_READER,
                                 f"{_name(p, s.scene_id)}: {path} calls getInputProps (it would read the master's input props)", (s.scene_id,))
    merged: dict[str, dict[str, Any]] = {}
    for p, s, _, src in sources:
        offered = [(path, src.files[path], False) for path in src.block.assets]
        offered += [(f"{LIVE_PUBLIC_DIR}/{name}", data, True)
                    for name, data in sorted(inputs.live_copies.get((s.prefab.prefab_id, s.prefab.version), {}).items())]
        for path, data, live in offered:
            digest = hashlib.sha256(data).hexdigest()
            row = merged.setdefault(path.lower(), {"path": path, "sha256": digest, "data": data, "live": live, "owners": []})
            if row["path"] != path or row["sha256"] != digest:
                owner = row["owners"][0] if row["owners"] else (p, s.scene_id)
                spelled = f" (spelled {row['path']})" if row["path"] != path else ""
                return _incompatible(inputs, MasterReason.PUBLIC_ASSET_COLLISION,
                                     f"{path}{spelled}: {_name(*owner)} and {_name(p, s.scene_id)} bring different files at one path",
                                     tuple(dict.fromkeys((owner[1], s.scene_id))))
            row["live"] = row["live"] and live  # a file a pin's own source brings is a key input, even if a frozen copy matches it
            if s.scene_id not in [sid for _, sid in row["owners"]]:
                row["owners"].append((p, s.scene_id))
    # The workspace check `plan_master_files` runs (`path_set_problems`), over the merged public paths frozen live copies included, so a
    # ready plan never fails there (`public/live/a.png` from a pin + a frozen copy `a.png/b.json`: a file that is also a folder).
    layout = path_set_problems(r["path"] for r in merged.values())
    if layout:
        bad = layout[0].split(": ", 1)[0]  # the deeper path; the file it runs through is one of its ancestors
        involved = [owner for r in merged.values() if bad == r["path"] or bad.startswith(r["path"] + "/") for owner in r["owners"]]
        return _incompatible(inputs, MasterReason.PUBLIC_ASSET_COLLISION,
                             f"{layout[0]} ({_named_list(sorted(set(involved)))})", tuple(dict.fromkeys(sid for _, sid in sorted(involved))))
    first_block = sources[0][3].block.composition
    planned: list[MasterScene] = []
    generated_input: list[GeneratedScene] = []
    start = 0
    for p, s, pin, src in sources:
        duration = src.block.composition.duration_in_frames
        props = merge_props(pin.props_defaults, pin.data_defaults, s.props, s.data)
        entry = _mounted(s.scene_id, src.block.entry)
        planned.append(MasterScene(s.scene_id, s.prefab.prefab_id, s.prefab.version, pin.digest, src.block.engine.version, start, duration,
                                   entry, f"{SCENES_DIR}{s.scene_id}/", props_digest(s), src, props))
        generated_input.append(GeneratedScene(s.scene_id, p, entry, duration, props))
        start += duration
    composition = MasterComposition(first_block.width, first_block.height, first_block.fps, start)
    assets = tuple(MasterAsset(r["path"], r["sha256"], len(r["data"]), tuple(sid for _, sid in r["owners"]), r["live"], r["data"])
                   for r in sorted(merged.values(), key=lambda r: r["path"]))
    generated = generated_files(width=composition.width, height=composition.height, fps=composition.fps, scenes=generated_input)
    modules = [(len(src.block.modules), sum(len(src.files[m]) for m in src.block.modules)) for *_, src in sources]
    totals = MasterTotals(sum(n for n, _ in modules) + len(assets) + len(generated),
                          sum(b for _, b in modules) + sum(a.size for a in assets) + sum(len(d) for d in generated.values()))
    ids = tuple(s.scene_id for s in scenes)
    if totals.files > MAX_MASTER_FILES or totals.bytes > MAX_MASTER_BYTES:
        return _incompatible(inputs, MasterReason.PROJECT_TOO_LARGE,
                             f"the workspace would hold {totals.files} files and {totals.bytes} bytes "
                             f"(at most {MAX_MASTER_FILES} files and {MAX_MASTER_BYTES} bytes, generated files included)", ids)
    if composition.duration_in_frames > MAX_MASTER_RENDER_FRAMES:
        return _incompatible(inputs, MasterReason.TOO_LONG,
                             f"the whole video lasts {composition.duration_in_frames} frames, at most {MAX_MASTER_RENDER_FRAMES}", ids)
    scenes_out = tuple(planned)
    return MasterProjectPlan(inputs.presentation_id, inputs.variant_id, inputs.variant_revision, MasterStatus.READY,
                             project_key=_project_key(composition, scenes_out, assets), composition=composition, scenes=scenes_out,
                             public_assets=assets, totals=totals, generated=generated)
