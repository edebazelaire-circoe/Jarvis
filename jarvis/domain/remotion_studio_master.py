"""Remotion Studio master target: unpublished-edit classes and generated paths (`docs/remotion-master-project.md` § 6, § 9; handoff
jarvis-remotion-master-project-studio-export, Slice 05). Pure: paths in, classes out.

A master workspace is never a publish source (M6). Its unpublished edits are only CLASSIFIED, so a refusal names what would be lost and
the agent's write gate blocks a scene only for edits that belong to that scene:

1. **generated**: `package.json`, `studio-root.tsx`, `src/master/**` (read-only on disk, rewritten at every materialization);
2. **scene**: `src/scenes/<scene_id>/**` of a mounted scene, or a `public/**` file that exactly one mounted scene brings;
3. **shared**: a `public/**` file several scenes (or none) bring, anything else, and the runner's unreadable-listing marker.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any

from jarvis.domain.remotion_master_generated import MASTER_PACKAGE_NAME, is_generated
from jarvis.domain.remotion_master_project import SCENES_DIR, MasterProjectPlan
from jarvis.domain.remotion_studio import GENERATED_TOP_LEVEL, WORK_PACKAGE, MasterTarget

PUBLIC_DIR = "public/"
#: What `RemotionStudioRunner.workspace_listing` reports instead of paths when the workspace cannot be read (`<...>`).
UNREADABLE_PREFIX = "<"


class EditClass(StrEnum):
    GENERATED = "generated"
    SCENE = "scene"
    SHARED = "shared"


@dataclass(frozen=True, slots=True)
class ClassifiedEdit:
    path: str
    edit_class: EditClass
    scene_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "class": self.edit_class.value, "scene_id": self.scene_id}


def public_owners_of_plan(plan: MasterProjectPlan) -> dict[str, tuple[str, ...]]:
    """`{public path: scene ids that bring it}` from a ready plan's merged assets (frozen `public/live/**` copies excluded: render only)."""

    return {asset.path: tuple(asset.scene_ids) for asset in plan.public_assets if not asset.live}


def public_owners_of_sources(sources: Iterable[tuple[str, Iterable[str]]]) -> dict[str, tuple[str, ...]]:
    """Same map, rebuilt from each mounted scene's pinned source paths (`(scene_id, paths)`), e.g. after a Core restart."""

    owners: dict[str, list[str]] = {}
    for scene_id, paths in sources:
        for path in paths:
            if path.startswith(PUBLIC_DIR) and scene_id not in owners.setdefault(path, []):
                owners[path].append(scene_id)
    return {path: tuple(ids) for path, ids in owners.items()}


def classify(path: str, scene_ids: Iterable[str], public_owners: Mapping[str, tuple[str, ...]]) -> ClassifiedEdit:
    if is_generated(path):
        return ClassifiedEdit(path, EditClass.GENERATED)
    if path.startswith(SCENES_DIR):
        scene_id = path[len(SCENES_DIR):].split("/", 1)[0]
        if scene_id in set(scene_ids):
            return ClassifiedEdit(path, EditClass.SCENE, scene_id)
    if path.startswith(PUBLIC_DIR):
        owners = public_owners.get(path, ())
        if len(owners) == 1:
            return ClassifiedEdit(path, EditClass.SCENE, owners[0])
    return ClassifiedEdit(path, EditClass.SHARED)


def classify_edits(paths: Iterable[str], target: MasterTarget, public_owners: Mapping[str, tuple[str, ...]]) -> tuple[ClassifiedEdit, ...]:
    scene_ids = [scene_id for scene_id, _ in target.scenes]
    return tuple(classify(path, scene_ids, public_owners) for path in paths)


@dataclass(frozen=True, slots=True)
class MasterWorkspaceBase:
    """What the Studio service tells the agent write gate while a master target is recorded (`workspace_base`): the target and the
    `public/**` ownership. `edits_on` answers « which unpublished edits belong to scene X »; `None` = unknown (unreadable listing)."""

    target: MasterTarget
    public_owners: Mapping[str, tuple[str, ...]]

    @property
    def kind(self) -> str:
        return self.target.kind

    @property
    def presentation_id(self) -> str:
        return self.target.presentation_id

    def edits_on(self, scene_id: str, edited: Iterable[str] | None) -> tuple[str, ...] | None:
        if edited is None:
            return None
        paths = tuple(edited)
        if any(path.startswith(UNREADABLE_PREFIX) for path in paths):
            return None
        return tuple(row.path for row in classify_edits(paths, self.target, self.public_owners)
                     if row.edit_class is EditClass.SCENE and row.scene_id == scene_id)


def generated_paths(files: Mapping[str, bytes]) -> frozenset[str]:
    """Paths of a planned workspace that are read-only on disk: the two top-level generated files, plus `src/master/**` when the map is a
    master project (its `package.json` names `jarvis-studio-master`). A scene workspace keeps exactly today's set: a scene's own
    `src/master/x.tsx` stays editable."""

    try:
        package = json.loads(bytes(files.get(WORK_PACKAGE, b"{}")).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        package = None  # not a Jarvis-generated package: only the top-level set is generated
    master = isinstance(package, dict) and package.get("name") == MASTER_PACKAGE_NAME
    return frozenset(path for path in files if path in GENERATED_TOP_LEVEL or (master and is_generated(path)))


__all__ = ["ClassifiedEdit", "EditClass", "MasterWorkspaceBase", "classify", "classify_edits", "generated_paths", "public_owners_of_plan",
           "public_owners_of_sources"]
