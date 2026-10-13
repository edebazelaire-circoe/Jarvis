"""Whole-video (master) render of a frozen package (handoff jarvis-remotion-master-project-studio-export, Slice 06;
`docs/remotion-master-project.md` §10). Pure: a verified `FrozenPackage` in.

The master render reads nothing but the package, like the scene render (`presentation_render_plan`): `frozen_inputs` revalidates every
active pin (`parse_source`, digest), `plan_master` decides readiness and the `project_key`, `plan_master_files` lays out the workspace (the
render's `public/live/**` copies included). The scene path (`choose_scene` / `plan_files`) is not used and not changed.
"""

from __future__ import annotations

import re

from jarvis.domain.presentation_render import MasterTarget, RenderError, RenderErrorCode as C
from jarvis.domain.presentation_snapshot_package import FrozenPackage
from jarvis.domain.remotion_import import strip_comments
from jarvis.domain.remotion_master_files import MasterFilesError, plan_master_files
from jarvis.domain.remotion_master_project import MasterProjectPlan, frozen_inputs, plan_master

#: A mounted scene that plays an `<Audio>` element (JSX, comments stripped): its MP4 must carry an audio stream. A `<Video>` /
#: `<OffthreadVideo>` alone does not require one (its clip may be silent: Remotion then writes no audio track).
_AUDIO_ELEMENT = re.compile(r"<\s*(?:Audio|Html5Audio)\b")


def frozen_plan(package: FrozenPackage) -> MasterProjectPlan:
    """The master plan of the package (ready or incompatible). `presentation_render_snapshot_invalid` for unreadable documents."""

    return plan_master(frozen_inputs(package))


def audio_ranges(plan: MasterProjectPlan) -> tuple[tuple[int, int], ...]:
    """`(from_frame, duration_in_frames)` of each mounted scene whose modules contain an `<Audio>` element (textual, comments stripped:
    `import {Audio as Sound}` escapes it, a user component named `Audio` or a muted `<Audio>` is counted)."""

    return tuple((scene.from_frame, scene.duration_in_frames) for scene in plan.scenes
                 if any(_AUDIO_ELEMENT.search(strip_comments(text)) for text in scene.source.module_texts().values()))


def master_target(plan: MasterProjectPlan) -> MasterTarget:
    if not plan.ready:
        assert plan.reason is not None
        raise RenderError(C.MASTER_INCOMPATIBLE, f"{plan.reason.value}: {plan.detail}",
                          extra={"reason": plan.reason.value, "detail": plan.detail, "scene_ids": list(plan.scene_ids)})
    assert plan.composition is not None and plan.project_key is not None
    engine = plan.scenes[0].source.block.engine
    c = plan.composition
    return MasterTarget(c.composition_id, c.width, c.height, c.fps, c.duration_in_frames, engine.version, engine.lock_sha256,
                        plan.project_key, tuple(s.scene_id for s in plan.scenes), audio_ranges(plan))


def choose_master(package: FrozenPackage) -> MasterTarget:
    """The master target of a frozen package, or `presentation_render_master_incompatible` (409) with the plan's reason."""

    return master_target(frozen_plan(package))


def master_files(package: FrozenPackage, target: MasterTarget) -> dict[str, bytes]:
    """The workspace of the job, re-planned from the package re-read at execution: the same package gives the same `project_key`; anything
    else is `presentation_render_snapshot_invalid` (never a render of something other than what was requested)."""

    plan = frozen_plan(package)
    if not plan.ready or plan.project_key != target.project_key:
        raise RenderError(C.SNAPSHOT_INVALID, f"the frozen package no longer plans the requested master project ({target.project_key})")
    try:
        return plan_master_files(plan)
    except MasterFilesError as exc:
        raise RenderError(C.SOURCE_REFUSED, f"the master workspace could not be laid out: {str(exc)[:200]}") from None
