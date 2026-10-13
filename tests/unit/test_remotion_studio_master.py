"""Remotion Studio master target (handoff jarvis-remotion-master-project-studio-export, Slice 05; `docs/remotion-master-project.md` § 9).

Pure domain (bodies, `state.json` schemas 1 and 2, edit classes) and the service on the fake runner, with REAL master plans (the Slice 03
planner on real parsed sources) served by a fake live reader. The scene lane is held by the unchanged `test_remotion_studio*.py`; the real
`remotion studio` proof is `test_remotion_studio_master_real_browser.py`.
"""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import stat

import pytest

from jarvis.adapters.remotion_studio_runner import RemotionStudioRunner
from jarvis.core.remotion_studio_service import RemotionStudioService
from jarvis.domain import remotion_studio as D
from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode
from jarvis.domain.remotion_master_files import plan_master_files
from jarvis.domain.remotion_master_generated import BOUNDARY_FILE, PACKAGE_FILE, PRESENTATION_FILE, ROOT_FILE
from jarvis.domain.remotion_master_project import MasterProjectPlan, PinSource, plan_master
from jarvis.domain.remotion_studio import MasterRequest, MasterTarget, StudioError, StudioErrorCode as C, StudioPin
from jarvis.domain.remotion_studio_master import (
    EditClass, MasterWorkspaceBase, classify_edits, generated_paths, public_owners_of_plan, public_owners_of_sources,
)
from jarvis.protocol.remotion_studio_routes import MAX_BODY_BYTES
from tests.fakes.remotion_scene import PNG_1X1, scene_files
from tests.fakes.remotion_studio import FakeStudioRunner
from tests.unit.test_remotion_master_project import IDS, PREFABS, inputs, pin, scene, source
from tests.unit.test_remotion_studio import PIN, Clock, Recorder, source_for

PID, VID = "pst_" + "0" * 32, "psv_" + "0" * 32
GENERATED = {PACKAGE_FILE, ROOT_FILE, PRESENTATION_FILE, BOUNDARY_FILE}


def sources(salt: str = "", extra_public: dict | None = None) -> dict[tuple[str, int], object]:
    """Three pins, different bytes, all bringing the same `public/dot.png` (merged once, owned by the three scenes); `extra_public`: files
    only scene 1 brings."""

    return {pin(n): source({**scene_files(title_suffix=f"// scene {n}{salt}\n"), **((extra_public or {}) if n == 0 else {})})
            for n in range(3)}


def plan_of(srcs=None, *, props: str = "T", revision: int = 3, extra_public: dict | None = None) -> MasterProjectPlan:
    srcs = srcs or sources(extra_public=extra_public)
    scenes = [scene(n, props={"title": f"{props}{n}"}) for n in range(3)]
    return plan_master(inputs(scenes, {key: PinSource.remotion(src) for key, src in srcs.items()}, revision=revision))


class Reader:
    """Fake `MasterProjectReader.live_plan`: the plan the live variant would give now."""

    def __init__(self, plan: MasterProjectPlan) -> None:
        self.plan = plan
        self.calls: list[tuple[str, str, bool]] = []
        self.error: Exception | None = None

    async def __call__(self, presentation_id: str, variant_id: str, *, trace: bool = True) -> MasterProjectPlan:
        self.calls.append((presentation_id, variant_id, trace))
        if self.error is not None:
            raise self.error
        return self.plan


class Stack:
    def __init__(self, plan: MasterProjectPlan | None = None, *, runner: FakeStudioRunner | None = None) -> None:
        self.runner = runner or FakeStudioRunner()
        self.clock = Clock()
        self.events = Recorder()
        self.srcs = sources()
        self.reader = Reader(plan or plan_of(self.srcs))
        self.announced: list[StudioPin] = []
        self.service = RemotionStudioService(self.runner, source_provider=self.provide, capability_status=lambda: "ready",
                                             diagnostics=self.events, clock=self.clock)
        self.service.bind_master_reader(self.reader)

        async def listen(p):
            self.announced.append(p)

        self.service.add_scene_listener(listen)

    async def provide(self, p: StudioPin):
        src = self.srcs.get((p.prefab_id, p.version))
        return (src, {}) if src is not None else (source_for(p), {"title": "Bonjour"})

    def request(self, key: str | None = None) -> MasterRequest:
        return MasterRequest(PID, VID, key or str(self.reader.plan.project_key))


@pytest.fixture
def stack():
    return Stack()


def body(key: str = "mpk_" + "a" * 24, **extra):
    return {"kind": "variant_master", "presentation_id": PID, "variant_id": VID, "project_key": key, D.PROJECT_ACK_FIELD: True, **extra}


# ------------------------------------------------------------------ bodies


def test_the_scene_body_is_unchanged_and_the_master_body_is_its_own_shape():
    assert D.parse_target({"prefab_id": PIN.prefab_id, "version": 1, D.ACK_FIELD: True}) == PIN
    assert D.parse_target(body()) == MasterRequest(PID, VID, "mpk_" + "a" * 24)
    assert D.parse_restart({D.ACK_FIELD: True}) == (None, False)
    assert D.parse_restart(body()) == (MasterRequest(PID, VID, "mpk_" + "a" * 24), False)


def test_restart_takes_discard_unpublished_only_with_a_master_body():
    """§ 9: the master body (with `discard_unpublished`) serves `restart` too; the scene restart body stays exactly `{ack}` (a scene
    restart never switches target, so its edits are always kept)."""

    assert D.parse_restart(body(discard_unpublished=True)) == (MasterRequest(PID, VID, "mpk_" + "a" * 24), True)
    for raw in (body(discard_unpublished=False), body(discard_unpublished="true"), {D.ACK_FIELD: True, "discard_unpublished": True}):
        with pytest.raises(StudioError) as caught:
            D.parse_restart(raw)
        assert caught.value.code is C.INVALID and caught.value.http_status == 400


@pytest.mark.parametrize("raw", [
    body(prefab_id="x"), body(version=1), body(**{D.ACK_FIELD: True}), {**body(), "kind": "scene"},
    {k: v for k, v in body().items() if k != "kind"}, body(key="mpk_short"), body(key="MPK_" + "a" * 24),
    {**body(), "presentation_id": "../etc"}, {**body(), "variant_id": ""}, {"prefab_id": PIN.prefab_id, "version": 1, D.PROJECT_ACK_FIELD: True},
])
def test_a_mixed_or_malformed_master_body_is_invalid(raw):
    with pytest.raises(StudioError) as caught:
        D.parse_target(raw)
    assert caught.value.code is C.INVALID and caught.value.http_status == 400


@pytest.mark.parametrize("ack", [None, False, "true", 1])
def test_a_master_body_without_its_acknowledgment_starts_nothing(ack):
    raw = {k: v for k, v in body().items() if k != D.PROJECT_ACK_FIELD}
    if ack is not None:
        raw[D.PROJECT_ACK_FIELD] = ack
    for parse in (D.parse_target, D.parse_restart):
        with pytest.raises(StudioError) as caught:
            parse(raw)
        assert caught.value.code is C.ACK_REQUIRED and caught.value.http_status == 400


def test_the_largest_master_body_fits_the_route_cap():
    ids = {"presentation_id": "p" * 128, "variant_id": "v" * 128}
    largest = json.dumps({**body(), **ids, "discard_unpublished": True}, ensure_ascii=False).encode("utf-8")
    assert len(largest) < MAX_BODY_BYTES, len(largest)
    assert isinstance(D.parse_target({**body(), **ids}), MasterRequest)


# ------------------------------------------------------------------ state.json


def target() -> MasterTarget:
    return MasterTarget(PID, VID, 3, "mpk_" + "b" * 24, ((IDS[0], StudioPin(PREFABS[0], 1)), (IDS[1], StudioPin(PREFABS[1], 2))))


def test_a_scene_state_is_still_schema_1_with_exactly_the_old_keys():
    state = D.StudioState(status=D.StudioStatus.READY, pin=PIN, port=41000)
    payload = state.to_payload()
    assert payload["schema"] == 1 and payload["pin"] == PIN.to_dict() and "target" not in payload
    assert set(payload) == {"schema", "status", "pin", "source_digest", "workspace_digest", "composition", "port", "process_ref", "launch_id",
                            "started_at", "ready_at", "synced_at", "syncs", "restarts", "last_error_code", "last_error_detail",
                            "stop_reason", "diagnostics", "edits_saved", "set_aside"}


def test_a_state_file_written_by_an_older_core_is_read_as_a_scene_target():
    old = {"schema": 1, "status": "stopped", "pin": {"prefab_id": PIN.prefab_id, "version": 1}, "source_digest": "x", "port": None,
           "edits_saved": 2}
    state = D.StudioState.from_payload(old)
    assert state.pin == PIN and state.master is None and state.target == PIN and state.edits_saved == 2
    assert D.target_view(state.target) == {"kind": "scene", **PIN.to_dict()}


def test_a_master_state_is_schema_2_with_a_target_instead_of_a_pin_and_round_trips():
    state = D.StudioState(status=D.StudioStatus.READY, master=target(), port=41001, syncs=2)
    payload = state.to_payload()
    assert payload["schema"] == 2 and "pin" not in payload
    assert payload["target"] == {"kind": "variant_master", "presentation_id": PID, "variant_id": VID, "variant_revision": 3,
                                 "project_key": "mpk_" + "b" * 24, "scenes": [{"scene_id": IDS[0], "prefab_id": PREFABS[0], "version": 1},
                                                                             {"scene_id": IDS[1], "prefab_id": PREFABS[1], "version": 2}]}
    again = D.StudioState.from_payload(json.loads(json.dumps(payload)))
    assert again.master == target() and again.pin is None and again.syncs == 2 and again.to_payload() == payload


@pytest.mark.parametrize("raw", [
    {"schema": 3, "status": "stopped"}, {"schema": True, "status": "stopped"}, {"schema": "2", "status": "stopped"},
    {"schema": 2, "status": "stopped", "pin": None, "target": target().to_dict()},
    {"schema": 2, "status": "stopped"}, {"schema": 2, "status": "stopped", "target": {**target().to_dict(), "kind": "scene"}},
    {"schema": 2, "status": "stopped", "target": {**target().to_dict(), "scenes": []}},
    {"schema": 2, "status": "stopped", "target": {**target().to_dict(), "project_key": "nope"}},
    {"schema": 2, "status": "stopped", "target": {**target().to_dict(), "scenes": [{"scene_id": "../x", "prefab_id": PREFABS[0], "version": 1}]}},
])
def test_an_unknown_schema_or_a_malformed_master_target_is_refused_never_guessed(raw):
    with pytest.raises((ValueError, StudioError)):
        D.StudioState.from_payload(raw)


@pytest.mark.parametrize("revision", ["absent", -1, None, "3", True])
async def test_a_schema_2_target_without_a_valid_variant_revision_is_unreadable(stack, revision):
    raw_target = target().to_dict()
    if revision == "absent":
        del raw_target["variant_revision"]
    else:
        raw_target["variant_revision"] = revision
    stack.runner.state = {"schema": 2, "status": "stopped", "target": raw_target}
    view = await stack.service.status()
    assert view["status"] == "failed" and view["last_error_code"] == C.STATE_UNREADABLE.value
    with pytest.raises(StudioError) as caught:
        await stack.service.open(stack.request(), acknowledged=True)
    assert caught.value.code is C.STATE_UNREADABLE and stack.runner.calls.count("launch") == 0


async def test_an_unreadable_master_state_fails_closed_and_is_never_rewritten(stack):
    stack.runner.state = {"schema": 2, "status": "ready", "target": {"kind": "variant_master"}}
    view = await stack.service.status()
    assert view["status"] == "failed" and view["last_error_code"] == C.STATE_UNREADABLE.value
    with pytest.raises(StudioError) as caught:
        await stack.service.open(stack.request(), acknowledged=True)
    assert caught.value.code is C.STATE_UNREADABLE and stack.runner.state == {"schema": 2, "status": "ready", "target": {"kind": "variant_master"}}


# ------------------------------------------------------------------ edit classes and generated paths


def test_master_edits_are_classified_generated_per_scene_or_shared():
    plan = plan_of(extra_public={"public/intro.mp3": b"ID3"})
    t = MasterTarget(PID, VID, 3, str(plan.project_key), tuple((s.scene_id, StudioPin(s.prefab_id, s.version)) for s in plan.scenes))
    owners = public_owners_of_plan(plan)
    assert owners["public/intro.mp3"] == (IDS[0],) and owners["public/dot.png"] == (IDS[0], IDS[1], IDS[2])
    paths = ["package.json", "studio-root.tsx", "src/master/Presentation.tsx", f"src/scenes/{IDS[1]}/Scene.tsx", "public/intro.mp3",
             "public/dot.png", "public/added.png", "src/scenes/pss_unknown/x.tsx", "remotion.config.ts", "<work folder unreadable or too large>"]
    rows = {row.path: (row.edit_class, row.scene_id) for row in classify_edits(paths, t, owners)}
    assert rows == {"package.json": (EditClass.GENERATED, None), "studio-root.tsx": (EditClass.GENERATED, None),
                    "src/master/Presentation.tsx": (EditClass.GENERATED, None), f"src/scenes/{IDS[1]}/Scene.tsx": (EditClass.SCENE, IDS[1]),
                    "public/intro.mp3": (EditClass.SCENE, IDS[0]), "public/dot.png": (EditClass.SHARED, None),
                    "public/added.png": (EditClass.SHARED, None), "src/scenes/pss_unknown/x.tsx": (EditClass.SHARED, None),
                    "remotion.config.ts": (EditClass.SHARED, None), "<work folder unreadable or too large>": (EditClass.SHARED, None)}
    rebuilt = public_owners_of_sources([(s.scene_id, s.source.files) for s in plan.scenes])
    assert rebuilt == owners, "after a Core restart the ownership is rebuilt from the immutable pins, identically"


def test_the_write_gate_view_blocks_a_scene_only_for_its_own_edits():
    plan = plan_of(extra_public={"public/intro.mp3": b"ID3"})
    t = MasterTarget(PID, VID, 3, str(plan.project_key), tuple((s.scene_id, StudioPin(s.prefab_id, s.version)) for s in plan.scenes))
    base = MasterWorkspaceBase(t, public_owners_of_plan(plan))
    edited = ("src/master/Presentation.tsx", "public/dot.png", f"src/scenes/{IDS[1]}/Scene.tsx", "public/intro.mp3")
    assert base.kind == "variant_master" and base.presentation_id == PID
    assert base.edits_on(IDS[1], edited) == (f"src/scenes/{IDS[1]}/Scene.tsx",)
    assert base.edits_on(IDS[0], edited) == ("public/intro.mp3",)
    assert base.edits_on(IDS[2], edited) == (), "generated and shared edits never block a voice edit"
    assert base.edits_on(IDS[2], None) is None and base.edits_on(IDS[2], ("<work folder unreadable or too large>",)) is None


def test_src_master_is_generated_only_in_a_master_workspace():
    master = plan_master_files(plan_of())
    assert generated_paths(master) == frozenset(GENERATED)
    scene_map = D.plan_workspace(source({**scene_files(), "src/master/Own.tsx": "export const x = 1;\n"}))
    assert generated_paths(scene_map) == frozenset({ROOT_FILE, PACKAGE_FILE}), "a scene's own src/master stays editable"


def test_the_real_runner_writes_src_master_read_only_and_switching_back_removes_it(tmp_path):
    runner = RemotionStudioRunner(lambda: tmp_path / "runtime")
    work = tmp_path / "runtime" / "studio" / "work"
    runner.sync_work(plan_master_files(plan_of()))

    def writable(path: str) -> bool:
        return bool(os.stat(work / path).st_mode & stat.S_IWRITE)

    assert not writable(PRESENTATION_FILE) and not writable(BOUNDARY_FILE) and not writable(ROOT_FILE)
    assert writable(f"src/scenes/{IDS[0]}/Scene.tsx") and writable("public/dot.png")
    assert runner.modified_work() == () and runner.enforce_shape(plan_master_files(plan_of())) == (), "the master layout is the shape"
    scene_map = D.plan_workspace(source({**scene_files(), "src/master/Own.tsx": "export const x = 1;\n"}))
    runner.sync_work(scene_map)
    assert not (work / "src" / "scenes").exists() and writable("src/master/Own.tsx") and not writable(ROOT_FILE)
    assert not (work / PRESENTATION_FILE).exists()


# ------------------------------------------------------------------ service: open, reuse, stale, incompatible


async def test_open_materializes_the_master_plan_and_records_a_schema_2_target(stack):
    view = await stack.service.open(stack.request(), acknowledged=True)
    plan = stack.reader.plan
    assert view["status"] == "ready" and view["pin"] is None
    assert view["target"]["kind"] == "variant_master" and view["target"]["scene_count"] == 3
    assert view["target"]["project_key"] == plan.project_key and view["target"]["stale"] is False
    assert view["composition"]["id"] == "JarvisPresentation" and view["composition"]["duration_in_frames"] == plan.composition.duration_in_frames
    assert stack.runner.work == plan_master_files(plan)
    assert stack.runner.state["schema"] == 2 and stack.runner.state["target"]["project_key"] == plan.project_key
    assert view["work_copy"]["classified"] == [] and view["work_copy"]["base"] is None
    assert stack.announced == [StudioPin(PREFABS[n], 1) for n in range(3)], "scene listeners once per mounted pin"
    kinds = stack.events.kinds()
    assert "remotion_studio.starting" in kinds and "remotion_studio.ready" in kinds
    ready = next(data for kind, _, data in stack.events.events if kind == "remotion_studio.ready")
    assert ready["project_key"] == plan.project_key and ready["scenes"] == 3


async def test_the_same_key_reuses_the_living_studio(stack):
    await stack.service.open(stack.request(), acknowledged=True)
    again = await stack.service.open(stack.request(), acknowledged=True)
    assert again["reused"] is True and stack.runner.launches == [None] and len(stack.reader.calls) == 2, "replanned, not relaunched"


async def test_opening_a_new_key_while_ready_syncs_instead_of_reusing(stack):
    """Target identity includes `project_key`: K1 open, the variant moves to K2, `open` K2 hot-syncs the same process (never « reused »)."""

    await stack.service.open(stack.request(), acknowledged=True)
    old_key = stack.reader.plan.project_key
    stack.reader.plan = plan_of(stack.srcs, props="Edited", revision=4)
    stack.events.events.clear()
    view = await stack.service.open(stack.request(), acknowledged=True)
    kinds = stack.events.kinds()
    assert "remotion_studio.synced" in kinds and "remotion_studio.reused" not in kinds
    assert view["target"]["project_key"] == stack.reader.plan.project_key != old_key and view["syncs"] == 1
    assert stack.runner.launches == [None] and stack.runner.work == plan_master_files(stack.reader.plan)


async def test_a_stale_key_is_refused_with_the_current_key_and_nothing_changes(stack):
    with pytest.raises(StudioError) as caught:
        await stack.service.open(stack.request("mpk_" + "f" * 24), acknowledged=True)
    plan = stack.reader.plan
    assert caught.value.code is C.MASTER_STALE and caught.value.http_status == 409
    assert caught.value.extra == {"project_key": plan.project_key, "variant_revision": 3, "scene_count": 3}
    assert "launch" not in stack.runner.calls and stack.runner.work == {} and stack.runner.state is None


async def test_an_incompatible_variant_is_refused_with_its_reason_and_nothing_starts():
    srcs = sources()
    bad = plan_master(inputs([scene(n) for n in range(3)], {**{k: PinSource.remotion(v) for k, v in srcs.items()},
                                                            pin(1): PinSource.unavailable("x@1 is tampered")}))
    stack = Stack(bad)
    with pytest.raises(StudioError) as caught:
        await stack.service.open(MasterRequest(PID, VID, "mpk_" + "a" * 24), acknowledged=True)
    assert caught.value.code is C.MASTER_INCOMPATIBLE and caught.value.http_status == 409
    assert caught.value.extra["reason"] == "master_source_unavailable" and caught.value.extra["scene_ids"] == [IDS[1]]
    assert caught.value.extra["detail"] and "launch" not in stack.runner.calls


async def test_an_unknown_variant_or_a_core_without_reader_is_said():
    stack = Stack()
    stack.reader.error = PresentationStudioError(PresentationStudioErrorCode.UNKNOWN_VARIANT, "variant psv_x is not in pst_y")
    with pytest.raises(StudioError) as caught:
        await stack.service.open(stack.request(), acknowledged=True)
    assert caught.value.code is C.SOURCE_UNAVAILABLE and "presentation_studio_unknown_variant" in caught.value.detail
    bare = RemotionStudioService(FakeStudioRunner(), source_provider=stack.provide, capability_status=lambda: "ready")
    with pytest.raises(StudioError) as caught:
        await bare.open(stack.request(), acknowledged=True)
    assert caught.value.code is C.UNAVAILABLE and caught.value.http_status == 503


async def test_status_says_stale_when_the_live_key_moves_and_a_sync_with_the_new_key_follows(stack):
    await stack.service.open(stack.request(), acknowledged=True)
    old_key = stack.reader.plan.project_key
    stack.reader.plan = plan_of(stack.srcs, props="Edited", revision=4)       # a voice edit: instance props changed, revision + 1
    stack.clock.now += 1
    assert (await stack.service.status())["target"]["stale"] is False, "the poll recomputes at most every 5 s"
    stack.clock.now += 10
    view = await stack.service.status()
    assert view["target"]["stale"] is True and view["target"]["current_project_key"] == stack.reader.plan.project_key != old_key
    assert view["target"]["project_key"] == old_key, "the running Studio never follows a new key by itself"
    assert stack.reader.calls[-1][2] is False, "the poll does not journal one plan line per read"
    with pytest.raises(StudioError) as caught:
        await stack.service.sync(None)
    assert caught.value.code is C.ACK_REQUIRED, "a master sync always carries its acknowledgment"
    synced = await stack.service.sync(stack.request(), acknowledged=True)
    assert synced["target"]["project_key"] == stack.reader.plan.project_key and synced["target"]["stale"] is False
    assert synced["target"]["variant_revision"] == 4 and stack.runner.launches == [None], "hot sync, same process"
    assert stack.runner.work == plan_master_files(stack.reader.plan)


# ------------------------------------------------------------------ unpublished master edits, switching, publish


async def test_an_unpublished_master_edit_blocks_a_rebuild_or_a_switch_until_discarded(stack):
    await stack.service.open(stack.request(), acknowledged=True)
    stack.runner.work[f"src/scenes/{IDS[1]}/Scene.tsx"] = b"// edited by the user\n"
    view = await stack.service.status()
    assert view["work_copy"]["classified"] == [{"path": f"src/scenes/{IDS[1]}/Scene.tsx", "class": "scene", "scene_id": IDS[1]}]
    stack.reader.plan = plan_of(stack.srcs, props="Edited", revision=4)
    for attempt in (lambda: stack.service.sync(stack.request(), acknowledged=True),
                    lambda: stack.service.open(PIN, acknowledged=True)):
        with pytest.raises(StudioError) as caught:
            await attempt()
        assert caught.value.code is C.UNPUBLISHED_EDITS
        assert caught.value.extra["classified"] == [{"path": f"src/scenes/{IDS[1]}/Scene.tsx", "class": "scene", "scene_id": IDS[1]}]
        assert caught.value.extra["target"]["kind"] == "variant_master" and "never published" in caught.value.detail
    assert stack.runner.work[f"src/scenes/{IDS[1]}/Scene.tsx"] == b"// edited by the user\n", "never overwritten"
    view = await stack.service.open(PIN, acknowledged=True, discard=True)
    assert view["target"] == {"kind": "scene", **PIN.to_dict()} and view["pin"] == PIN.to_dict()
    assert stack.runner.saved_aside == [(f"src/scenes/{IDS[1]}/Scene.tsx",)], "set aside in studio-edits, as confirmed"
    assert stack.runner.state["schema"] == 1 and "target" not in stack.runner.state, "back on a scene: schema 1 again"
    assert not any(path.startswith("src/scenes/") for path in stack.runner.work)


async def test_the_same_master_reopens_on_its_workspace_with_the_edits_kept(stack):
    await stack.service.open(stack.request(), acknowledged=True)
    await stack.service.close()
    stack.runner.work[ROOT_FILE] = b"// tampered"
    view = await stack.service.open(stack.request(), acknowledged=True)
    assert view["status"] == "ready" and stack.runner.work[ROOT_FILE] == b"// tampered"
    assert view["work_copy"]["classified"] == [{"path": ROOT_FILE, "class": "generated", "scene_id": None}]


async def test_switching_from_a_scene_to_the_master_follows_the_unpublished_protection(stack):
    await stack.service.open(PIN, acknowledged=True)
    stack.runner.work["src/Scene.tsx"] = b"// scene edit"
    with pytest.raises(StudioError) as caught:
        await stack.service.open(stack.request(), acknowledged=True)
    assert caught.value.code is C.UNPUBLISHED_EDITS and caught.value.extra["base"] == PIN.to_dict() and "publish them" in caught.value.detail
    view = await stack.service.open(stack.request(), acknowledged=True, discard=True)
    assert view["target"]["kind"] == "variant_master" and stack.runner.launches == [None], "one process, hot switch"


async def test_publish_on_a_master_is_refused_before_the_workspace_is_read(stack):
    from jarvis.domain.remotion_studio_workspace import PublishRequest

    class Publisher:
        async def current(self, *_):
            raise AssertionError("never reached")

    stack.service.bind_publisher(Publisher())
    await stack.service.open(stack.request(), acknowledged=True)
    stack.runner.calls.clear()
    with pytest.raises(StudioError) as caught:
        await stack.service.publish(PublishRequest(PID, VID, IDS[0], StudioPin(PREFABS[0], 1), "0" * 64))
    assert caught.value.code is C.PUBLISH_MASTER_UNSUPPORTED and caught.value.http_status == 409
    for read in ("workspace_diff", "has_workspace", "modified_work"):
        assert read not in stack.runner.calls, read
    assert stack.runner.calls == [], "refused before any workspace read"


async def test_restart_of_a_master_needs_the_master_body_and_replans(stack):
    await stack.service.open(stack.request(), acknowledged=True)
    with pytest.raises(StudioError) as caught:
        await stack.service.restart(acknowledged=True)
    assert caught.value.code is C.ACK_REQUIRED
    with pytest.raises(StudioError) as caught:
        await stack.service.restart(acknowledged=True, master=stack.request("mpk_" + "0" * 24))
    assert caught.value.code is C.MASTER_STALE and stack.runner.launches == [None], "refused before anything stops"
    view = await stack.service.restart(acknowledged=True, master=stack.request())
    assert view["status"] == "ready" and view["restarts"] == 1 and len(stack.runner.launches) == 2


async def test_a_refused_master_restart_to_another_key_leaves_the_studio_running(stack):
    """QA Slice 05: unpublished edits are checked BEFORE the restart stops anything; `discard_unpublished` then sets them aside."""

    await stack.service.open(stack.request(), acknowledged=True)
    edited = f"src/scenes/{IDS[1]}/Scene.tsx"
    stack.runner.work[edited] = b"// edited by the user\n"
    stack.reader.plan = plan_of(stack.srcs, props="Edited", revision=4)
    stack.runner.calls.clear()
    with pytest.raises(StudioError) as caught:
        await stack.service.restart(acknowledged=True, master=stack.request())
    assert caught.value.code is C.UNPUBLISHED_EDITS and caught.value.http_status == 409
    assert caught.value.extra["classified"] == [{"path": edited, "class": "scene", "scene_id": IDS[1]}]
    assert "stop" not in stack.runner.calls and stack.runner.stopped == [], "the refused restart stopped nothing"
    view = await stack.service.status()
    assert view["status"] == "ready" and view["restarts"] == 0 and stack.runner.work[edited] == b"// edited by the user\n"
    view = await stack.service.restart(acknowledged=True, master=stack.request(), discard=True)
    assert view["status"] == "ready" and view["restarts"] == 1 and len(stack.runner.launches) == 2
    assert view["target"]["project_key"] == stack.reader.plan.project_key and stack.runner.saved_aside == [(edited,)]
    assert stack.runner.work == plan_master_files(stack.reader.plan)


async def test_a_master_restart_on_the_same_key_keeps_its_edits(stack):
    await stack.service.open(stack.request(), acknowledged=True)
    edited = f"src/scenes/{IDS[0]}/Scene.tsx"
    stack.runner.work[edited] = b"// kept\n"
    view = await stack.service.restart(acknowledged=True, master=stack.request())
    assert view["status"] == "ready" and view["restarts"] == 1 and stack.runner.work[edited] == b"// kept\n"
    assert stack.runner.saved_aside == []


async def test_a_new_core_adopts_the_master_and_rebuilds_the_edit_ownership_from_the_pins(stack):
    await stack.service.open(stack.request(), acknowledged=True)
    stack.runner.work["public/dot.png"] = PNG_1X1 + b"x"
    fresh = RemotionStudioService(stack.runner, source_provider=stack.provide, capability_status=lambda: "ready", clock=stack.clock)
    fresh.bind_master_reader(stack.reader)
    view = await fresh.reconcile()
    assert view["status"] == "ready" and view["target"]["kind"] == "variant_master"
    base, edited = await fresh.workspace_base()
    assert isinstance(base, MasterWorkspaceBase) and edited == ("public/dot.png",)
    assert all(base.edits_on(scene_id, edited) == () for scene_id in IDS[:3]), "a shared public file blocks no scene"
    stack.runner.work[f"src/scenes/{IDS[2]}/Scene.tsx"] = b"// edit"
    base, edited = await fresh.workspace_base()
    assert base.edits_on(IDS[2], edited) == (f"src/scenes/{IDS[2]}/Scene.tsx",) and base.edits_on(IDS[0], edited) == ()


async def test_ownership_that_cannot_be_rebuilt_counts_as_unknown_edits(stack):
    await stack.service.open(stack.request(), acknowledged=True)
    stack.runner.work["public/dot.png"] = b"changed"

    async def broken(_pin):
        raise StudioError(C.SOURCE_UNAVAILABLE, "store unreadable")

    fresh = RemotionStudioService(stack.runner, source_provider=broken, capability_status=lambda: "ready")
    base, edited = await fresh.workspace_base()
    assert isinstance(base, MasterWorkspaceBase) and edited is None, "never « no edits » when the classes are unknown"


# ------------------------------------------------------------------ the agent write gate on a master workspace


async def test_the_agent_write_gate_blocks_scene_x_only_for_per_scene_edits_on_x(tmp_path):
    from jarvis.domain.presentation_studio_reload import ReloadStatus
    from tests.fakes.presentation_studio_reload import GOOD_STYLE, SID, SID2, Rig

    rig = await Rig(tmp_path).open()
    try:
        variant = await rig.variant()
        t = MasterTarget(rig.pid, rig.vid, variant.revision, "mpk_" + "c" * 24,
                         tuple((s.scene_id, StudioPin(s.prefab.prefab_id, s.prefab.version)) for s in variant.scenes))
        state = {"edited": (f"src/scenes/{SID2}/Scene.tsx", "src/master/Presentation.tsx", "public/shared.png")}

        async def probe():
            return MasterWorkspaceBase(t, {"public/shared.png": (SID, SID2)}), state["edited"]

        rig.reload._studio_workspace = probe
        rig.edits.record_authored_scenes(rig.pid, rig.vid, [SID, SID2], variant.revision)
        assert (await rig.edit({"style": GOOD_STYLE}, actor="brain", auto_request=False)).status is ReloadStatus.RELOADED, \
            "generated, shared and other-scene edits never block scene X"
        with pytest.raises(PresentationStudioError) as caught:
            await rig.edit({"style": GOOD_STYLE}, scene_id=SID2, actor="brain", auto_request=False)
        assert caught.value.code is PresentationStudioErrorCode.SCENE_EDITED_IN_REMOTION and caught.value.status == 409
        state["edited"] = None
        with pytest.raises(PresentationStudioError) as caught:
            await rig.edit({"style": "p{color:#010203}"}, actor="brain", auto_request=False)
        assert caught.value.code is PresentationStudioErrorCode.SCENE_EDITED_IN_REMOTION, "an unreadable listing blocks"
        assert (await rig.edit({"style": "p{color:#020304}"}, scene_id=SID2, actor="user")).status in (ReloadStatus.RELOADED,
                                                                                                         ReloadStatus.REPINNED)
        other = replace(t, presentation_id="pst_" + "9" * 32)

        async def elsewhere():
            return MasterWorkspaceBase(other, {}), (f"src/scenes/{SID}/Scene.tsx",)

        rig.reload._studio_workspace = elsewhere
        assert (await rig.edit({"style": "p{color:#030405}"}, actor="brain", auto_request=False)).status is ReloadStatus.RELOADED, \
            "a master of another presentation blocks nothing here"
    finally:
        await rig.close()


def test_the_docs_contract_names_the_new_codes():
    text = (Path(__file__).resolve().parents[2] / "docs" / "remotion-studio.md").read_text(encoding="utf-8")
    for code in (C.MASTER_INCOMPATIBLE, C.MASTER_STALE, C.PUBLISH_MASTER_UNSUPPORTED):
        assert f"`{code.value.removeprefix('remotion_studio_')}`" in text, code
