"""D'un paquet gelé à la source exacte d'un rendu (Remotion Slice 16). Pur : un `FrozenPackage` vérifié en entrée.

Le rendu ne lit RIEN d'autre que le paquet : ni la bibliothèque de prefabs vivante, ni la présentation vivante, ni un Board. Les octets
de la source sont ceux du gel (`prefabs/<id>/<version>/src|public/**`, bloc `source.json`), les valeurs des propriétés sont celles de la
variante figée (`presentation/variant.json`) posées sur les valeurs par défaut figées dans le manifeste (`props_defaults`), les données de
Board sont les copies figées (`live/`, déposées sous `public/live/`). La source est REVALIDÉE (bornes + gardes d'isolation de la Slice 06)
avant d'être écrite : un paquet intact dont la source ne passerait plus une garde plus récente n'est pas rendu.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from jarvis.domain.presentation_render import RenderError, RenderErrorCode as C, SceneTarget, scene_target
from jarvis.domain.presentation_snapshot_package import FrozenPackage
from jarvis.domain.remotion_source import RemotionSource, RemotionSourceError, parse_source, parse_source_block
from jarvis.domain.remotion_studio import plan_workspace

LIVE_PUBLIC_DIR = "public/live"


def _root(prefab_id: str, version: int) -> str:
    return f"prefabs/{prefab_id}/{version}"


def remotion_pins(package: FrozenPackage) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[tuple[str, int], str]]:
    """`({(prefab_id, version): bloc source}, {…: empreinte})` des pins Remotion du paquet ; un bloc illisible est refusé."""

    blocks: dict[tuple[str, int], dict[str, Any]] = {}
    digests: dict[tuple[str, int], str] = {}
    for row in package.manifest["prefabs"]:
        if row.get("kind") != "remotion":
            continue
        key = (row["prefab_id"], row["version"])
        raw = package.files.get(f"{_root(*key)}/source.json")
        if raw is None:
            raise RenderError(C.SNAPSHOT_INVALID, f"pin {key[0]}@{key[1]} has no source.json in the package")
        try:
            block = parse_source_block(json.loads(raw.decode("utf-8")))
        except (ValueError, RemotionSourceError) as exc:
            raise RenderError(C.SNAPSHOT_INVALID, f"pin {key[0]}@{key[1]}: its source block is unreadable ({str(exc)[:120]})") from None
        blocks[key] = block.to_dict()
        digests[key] = str(row.get("source_digest", ""))
    return blocks, digests


def choose_scene(package: FrozenPackage, scene_id: str | None) -> SceneTarget:
    blocks, digests = remotion_pins(package)
    return scene_target(package.manifest, scene_id, source_blocks=blocks, digests=digests)


def scene_document(package: FrozenPackage, scene_id: str) -> Mapping[str, Any]:
    try:
        variant = json.loads(package.files["presentation/variant.json"].decode("utf-8"))
        return next(scene for scene in variant["scenes"] if scene["scene_id"] == scene_id)
    except (KeyError, ValueError, StopIteration, TypeError):
        raise RenderError(C.SNAPSHOT_INVALID, f"scene {scene_id} is not in the frozen variant document") from None


def still_scenes(package: FrozenPackage) -> list[dict[str, Any]]:
    """The scenes an image or a PDF can be made of (`RENDERS`: one scene each, `settings.scene_id`), in the frozen order: `{scene_id,
    position, title}` of every Remotion scene of the frozen variant. What a page offers as the scene choice of an image or PDF export
    (presentation-edition-v1 Slice 09); an unreadable variant document gives ids without titles (the render itself then says why)."""

    blocks, _ = remotion_pins(package)
    try:
        titles = {s["scene_id"]: str(s.get("title", ""))[:120] for s in
                  json.loads(package.files["presentation/variant.json"].decode("utf-8"))["scenes"]}
    except (KeyError, ValueError, TypeError):
        titles = {}  # intentional: titles are a courtesy of the choice; the render reads the document again and refuses it with its code
    rows = [s for s in package.manifest["scenes"] if (s["prefab"]["id"], s["prefab"]["version"]) in blocks]
    return [{"scene_id": s["scene_id"], "position": n, "title": titles.get(s["scene_id"], "")} for n, s in enumerate(rows, 1)]


def representative_frame(package: FrozenPackage, target: SceneTarget) -> int:
    """The still that stands for the scene when nobody names a frame (presentation-edition-v1 Slice 09, PM decision): the frame where its
    entrance is over, which the scene declares with its first timed anchor (`at_ms`, the moment its content is revealed); a scene that
    declares none gives its middle frame. Frame 0 is never the default: a scene whose content fades in is blank there. Clamped to the
    composition. The same rule rests the Variants preview (`control_center_prefab_host.js` › `representativeFrame`)."""

    scene = scene_document(package, target.scene_id)
    times = [a.get("at_ms") for a in scene.get("anchors", []) if isinstance(a, dict)] if isinstance(scene.get("anchors"), list) else []
    times = [t for t in times if type(t) is int and t >= 0]
    last = max(0, target.duration_in_frames - 1)
    # Half up, like the page's `Math.round` (Python's `round` goes to even: 2.5 -> 2 here, 3 there).
    frame = int(min(times) * target.fps / 1000 + 0.5) if times else target.duration_in_frames // 2
    return max(0, min(last, frame))


def render_props(package: FrozenPackage, target: SceneTarget) -> dict[str, Any]:
    """Valeurs d'entrée de la composition : défauts figés du manifeste, puis valeurs d'instance de la scène figée."""

    row = next((r for r in package.manifest["prefabs"] if (r["prefab_id"], r["version"]) == (target.prefab_id, target.version)), {})
    scene = scene_document(package, target.scene_id)
    instance = scene.get("props", {})
    if not isinstance(instance, dict):
        raise RenderError(C.SNAPSHOT_INVALID, f"scene {target.scene_id}: props must be an object")
    instance_data = scene.get("data", {})
    if not isinstance(instance_data, dict):
        raise RenderError(C.SNAPSHOT_INVALID, f"scene {target.scene_id}: data must be an object")
    return merge_props(row.get("props_defaults"), row.get("data_defaults"), instance, instance_data)


def merge_props(props_defaults: object, data_defaults: object, props: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    """The input props of a scene composition: manifest defaults, then the instance `props`. Slice 22: `data` is an input too
    (`inputProps.data`, as in the Player): defaults then instance values, under `props.data`; a scene that does not use `data` (empty on
    both sides) gets no key. Shared by the scene render and the master planner (`remotion_master_project`)."""

    merged_props: dict[str, Any] = dict(props_defaults) if isinstance(props_defaults, dict) else {}
    merged_props.update(props)
    merged_data = {**(data_defaults if isinstance(data_defaults, dict) else {}), **data}
    if merged_data and "data" not in merged_props:
        merged_props["data"] = merged_data
    return merged_props


def plan_files(package: FrozenPackage, target: SceneTarget) -> tuple[dict[str, bytes], dict[str, Any]]:
    """`(fichiers du dossier de travail, props)`. Revalide la source gelée ; `RenderError(source_refused)` au premier écart."""

    root = _root(target.prefab_id, target.version) + "/"
    blocks, _ = remotion_pins(package)
    block = parse_source_block(blocks[(target.prefab_id, target.version)])
    files = {path[len(root):]: data for path, data in package.files.items()
             if path.startswith(root) and path[len(root):].startswith(("src/", "public/"))}
    try:
        source = parse_source(block, files)
    except RemotionSourceError as exc:
        raise RenderError(C.SOURCE_REFUSED, f"the frozen source no longer passes validation: {str(exc)[:200]}") from None
    live_prefix = root + "live/"
    live = {path[len(live_prefix):]: data for path, data in package.files.items() if path.startswith(live_prefix)}
    props = render_props(package, target)
    planned = plan_workspace(RemotionSource(source.block, dict(source.files)), props)
    for name, data in live.items():
        planned[f"{LIVE_PUBLIC_DIR}/{name}"] = data
    return planned, props
