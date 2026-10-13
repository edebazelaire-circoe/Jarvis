"""Files of a master Remotion workspace (`docs/remotion-master-project.md` §6; handoff jarvis-remotion-master-project-studio-export, Slice 04).
Pure: a ready `MasterProjectPlan` in, the exact `{workspace path: bytes}` map out. Nothing is written here.

The map is what the existing runners already consume: `RemotionStudioRunner.sync_work(files)` (Slice 05, atomic per-file writes under the
Studio `work/`) and `RemotionRenderRunner.prepare(job_id, files)` (Slice 06, the job's `work/`). It holds

- the generated set (`package.json`, `studio-root.tsx`, `src/master/**`, `remotion_master_generated`);
- each mounted scene: the exact bytes of its pinned `src/**`, under `src/scenes/<scene_id>/` (relative imports unchanged, AUDIT A5);
- the merged `public/**` of the plan (identical files once; a frozen plan adds its `public/live/**` copies).

The scene lane's `plan_workspace` / `plan_files` are not used and not changed.
"""

from __future__ import annotations

from jarvis.domain.presentation_snapshot_package import package_path_problem
from jarvis.domain.presentation_studio_checks import is_scene_id
from jarvis.domain.remotion_master_generated import is_generated
from jarvis.domain.remotion_master_project import MAX_MASTER_BYTES, MAX_MASTER_FILES, SCENES_DIR, MasterProjectPlan
from jarvis.domain.remotion_source import MODULE_ROOT, path_set_problems


class MasterFilesError(ValueError):
    """The plan cannot be laid out as a workspace. Never expected for a plan `plan_master` made ready: each branch is a defence."""


def plan_master_files(plan: MasterProjectPlan) -> dict[str, bytes]:
    """`{path: bytes}` of the whole workspace of a READY plan, sorted by path. Every path is workspace-relative and lexically safe (the
    snapshot package rule: no drive, no `..`, no empty or dotted segment, no Windows device name); scene namespaces are scene ids."""

    if not plan.ready:
        raise MasterFilesError(f"the master plan is {plan.status.value} ({plan.reason.value if plan.reason else 'no reason'}): no workspace")
    files: dict[str, bytes] = {}

    def put(path: str, data: bytes) -> None:
        problem = package_path_problem(path)
        if problem is not None:
            raise MasterFilesError(f"{path[:120]}: {problem}")
        if path in files:
            raise MasterFilesError(f"{path[:120]} would be written twice")
        files[path] = bytes(data)

    for path, data in plan.generated.items():
        if not is_generated(path):
            raise MasterFilesError(f"{path[:120]} is not in the generated set")
        put(path, data)
    for scene in plan.scenes:
        if not is_scene_id(scene.scene_id) or scene.mount != f"{SCENES_DIR}{scene.scene_id}/":
            raise MasterFilesError(f"scene {str(scene.scene_id)[:40]}: its mount is not src/scenes/<scene id>/")
        for module in scene.source.block.modules:
            if not module.startswith(MODULE_ROOT):
                raise MasterFilesError(f"scene {scene.scene_id}: module {module[:80]} is not under src/")
            put(scene.mount + module[len(MODULE_ROOT):], scene.source.files[module])
    for asset in plan.public_assets:
        if not asset.path.startswith("public/"):
            raise MasterFilesError(f"{asset.path[:120]} is not under public/")
        put(asset.path, asset.data)
    problems = path_set_problems(files)
    if problems:
        raise MasterFilesError(problems[0])
    total = sum(len(data) for data in files.values())
    if len(files) > MAX_MASTER_FILES or total > MAX_MASTER_BYTES:
        raise MasterFilesError(f"{len(files)} files and {total} bytes exceed the master workspace bound")
    if plan.totals is None or (len(files), total) != (plan.totals.files, plan.totals.bytes):
        raise MasterFilesError(f"the workspace ({len(files)} files, {total} bytes) differs from the plan totals {plan.totals}")
    return dict(sorted(files.items()))
