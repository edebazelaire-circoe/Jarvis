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


def render_props(package: FrozenPackage, target: SceneTarget) -> dict[str, Any]:
    """Valeurs d'entrée de la composition : défauts figés du manifeste, puis valeurs d'instance de la scène figée."""

    row = next((r for r in package.manifest["prefabs"] if (r["prefab_id"], r["version"]) == (target.prefab_id, target.version)), {})
    defaults = row.get("props_defaults")
    props: dict[str, Any] = dict(defaults) if isinstance(defaults, dict) else {}
    scene = scene_document(package, target.scene_id)
    instance = scene.get("props", {})
    if not isinstance(instance, dict):
        raise RenderError(C.SNAPSHOT_INVALID, f"scene {target.scene_id}: props must be an object")
    props.update(instance)
    # Slice 22: `data` is an input of the composition too (`inputProps.data`, as in the Player): the frozen defaults of the manifest, then the
    # frozen values of the scene. A scene that does not use `data` (empty on both sides) gets no key, exactly as before.
    data_defaults = row.get("data_defaults")
    instance_data = scene.get("data", {})
    if not isinstance(instance_data, dict):
        raise RenderError(C.SNAPSHOT_INVALID, f"scene {target.scene_id}: data must be an object")
    merged = {**(data_defaults if isinstance(data_defaults, dict) else {}), **instance_data}
    if merged and "data" not in props:
        props["data"] = merged
    return props


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
