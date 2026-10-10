"""Slice 12 rework (QA-1): the detour is validated before any state change, the follower is a visible state, a locked sequence has
a provisional exit, a commit is ours by identity, the stage the user closes is reported, and an unreadable ledger no longer
leaves studio windows on the scene. Contract: `docs/presentation-studio.md` > *Playback runtime contract*.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.adapters.file_presentation_studio_stage_ledger import KEEP_QUARANTINED, LEDGER_FILE, FileStageLedger
from jarvis.core.presentation_studio_playback import (
    FOLLOWER_GRACE_S, MAX_VIEW_BYTES, PlaybackStatus, PresentationStudioPlaybackService,
)
from jarvis.core.presentation_studio_stage import MAX_STAGE_REOPENS, SceneStage, StageLedger
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_studio_playback import EventKind
from jarvis.domain.scene import (
    Representation, SceneActor, SceneCommand, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload, ScenePrefabRef,
)
from jarvis.domain.scene_selection import SceneSelection
from tests.unit.test_presentation_studio_playback_service import (
    AUX_BLOCK, CUE, I1, I2, I3, S1, S2, S3, MemoryLedgerStore, Rig, applied,
)

@pytest.fixture
async def rig(tmp_path):
    made = await Rig(tmp_path).open()
    yield made
    await made.close()


def locked_content() -> dict:
    """I1 (user) -> I2 (Jarvis hosts a locked sequence) -> I3 (user)."""

    return {
        "start_item_id": I1,
        "items": [
            {"item_id": I1, "scene_id": S1, "presenter": "user", "kind": "speech", "note": "Intro", "next_item_id": I2},
            {"item_id": I2, "scene_id": S2, "presenter": "jarvis", "kind": "speech", "label": "Demo",
             "visual": [{"kind": "sequence", "sequence_id": "demo"}], "timing": "locked", "interruption": "at_boundary",
             "target_duration_ms": 9000, "next_item_id": I3},
            {"item_id": I3, "scene_id": S3, "presenter": "user", "kind": "speech", "note": "Fin"}],
        "cues": [],
        "sequences": [{"sequence_id": "demo", "label": "Demo", "duration_ms": 9000, "on_interrupt": "pause_resume",
                       "steps": [{"step_id": "intro", "offset_ms": 0, "speaker": "jarvis", "text": "Regardez."},
                                 {"step_id": "wrap", "offset_ms": 6500, "speaker": "jarvis", "text": "Voila."}]}],
        "recovery_points": []}


async def archive(rig: Rig, object_id: str) -> None:
    await rig.scene.apply(SceneCommand(op=SceneOp.ARCHIVE_SELECTION, actor=SceneActor.USER,
                                       selection=SceneSelection(ids=(object_id,))))


# ------------------------------------------------------------------ P2: the detour is validated BEFORE the state moves

@pytest.mark.parametrize("block", [
    {"id": "lab.nothing", "version": 1},                                       # unknown prefab
    {"id": "lab.counter", "version": 99},                                      # unknown version
    {"id": "lab.counter", "version": 1, "props": {"label": 12345678}},         # props the manifest refuses
])
async def test_an_invalid_detour_is_a_typed_4xx_and_the_state_is_unchanged(rig, block):
    rig.build(detour_validator=rig.env.prefabs)
    applied(await rig.service.start(rig.start_body()))
    before = rig.service.where()
    result = await rig.run("detour", title="Annexe", prefab=block)
    assert result.status is PlaybackStatus.REFUSED and result.reason == "detour_invalid" and result.http_status == 422
    assert result.to_dict()["error"]["code"] == "presentation_studio_playback_refused"
    assert rig.service.where() == before                                       # nothing moved, not even the generation
    assert await rig.objects("studio_aux") == []
    applied(await rig.run("next"))                                             # the run was never in a detour
    assert applied(await rig.run("detour", title="Annexe", prefab=AUX_BLOCK))["phase"] == "detour"


async def test_a_validator_that_fails_refuses_closed_and_says_why(rig):
    class Down:
        async def validate_instance(self, ref):
            raise RuntimeError("catalogue offline")

    rig.build(detour_validator=Down())
    applied(await rig.service.start(rig.start_body()))
    result = await rig.run("detour", title="Annexe", prefab=AUX_BLOCK)
    assert result.reason == "detour_invalid" and "RuntimeError" in result.message and "offline" not in result.message
    assert rig.service.where()["phase"] == "playing"


async def test_a_detour_that_fails_to_show_after_the_boundary_is_undone_not_left_as_a_phantom(tmp_path):
    """A deferred detour (the item waits for its boundary) that cannot be staged when it finally shows is rolled back too."""

    rig = await Rig(tmp_path).open(content=locked_content())
    try:
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        applied(await rig.run("next"))                                         # hosts the sequence; at_boundary
        queued = applied(await rig.run("detour", title="Annexe", prefab={**AUX_BLOCK, "id": "lab.nothing"}))
        assert queued["pending"] == "detour" and queued["detour"] is None
        result = await rig.service.notify(EventKind.BOUNDARY)
        assert result.status is PlaybackStatus.STAGE_FAILED
        state = rig.service.where()
        assert state["phase"] == "playing" and state["detour"] is None and state["pending"] is None
        assert await rig.objects("studio_aux") == []
    finally:
        await rig.close()


# ------------------------------------------------------------------ I1: the provisional exit of a locked sequence

async def test_skip_sequence_leaves_the_locked_sequence_and_continues_after_it(tmp_path):
    rig = await Rig(tmp_path).open(content=locked_content())
    try:
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        applied(await rig.run("next"))
        assert rig.service.where()["sequence"]["of"] == 2
        wedged = await rig.run("next")
        assert wedged.reason == "locked_sequence_active"
        state = applied(await rig.run("skip_sequence"))
        assert state["phase"] == "playing" and state["scene"]["title"] == "Trois" and state["sequence"] is None
        assert (await rig.stage_object()).payload.title == "Trois"             # the stage followed
        refused = await rig.run("skip_sequence")
        assert refused.reason == "no_sequence"
        applied(await rig.run("previous"))
    finally:
        await rig.close()


async def test_skip_sequence_while_paused_stays_paused_on_the_next_item_and_a_pending_pause_takes_effect(tmp_path):
    rig = await Rig(tmp_path).open(content=locked_content())
    try:
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        applied(await rig.run("next"))
        pending = applied(await rig.run("pause"))                              # at_boundary: asked, not yet taken
        assert pending["phase"] == "playing" and pending["pending"] == "pause"
        state = applied(await rig.run("skip_sequence"))
        assert state["phase"] == "paused" and state["scene"]["title"] == "Trois" and state["pending"] is None
    finally:
        await rig.close()


async def test_skip_sequence_is_a_user_action_the_brain_cannot_send(tmp_path):
    rig = await Rig(tmp_path).open(content=locked_content())
    try:
        applied(await rig.service.start(rig.start_body("jarvis_presenter")))
        applied(await rig.run("next"))
        with pytest.raises(ValueError, match="user action"):
            await rig.service.skip_sequence({"actor": "brain"})
        with pytest.raises(ValueError):
            await rig.service.skip_sequence({"actor": "user", "extra": 1})
        assert rig.service.where()["sequence"] is not None
    finally:
        await rig.close()


# ------------------------------------------------------------------ decision (a): the follower is a visible state

async def test_the_follower_is_waiting_then_absent_when_nobody_pulls_and_connected_once_it_does(rig):
    state = applied(await rig.service.start(rig.start_body("user_presenter")))
    assert state["follower"] == "waiting"
    rig.mono.t += FOLLOWER_GRACE_S - 1
    assert rig.service.where()["follower"] == "waiting"
    rig.mono.t += 2
    assert rig.service.where()["follower"] == "absent"                         # the run goes on, in manual mode
    assert rig.env.sink.of("core.presentation_studio.playback_follower_absent")[0][0] == "warning"
    applied(await rig.run("next"))                                             # ... and keyboard navigation still works
    rig.service.armed_set()                                                    # the follower arrives late: connected
    assert rig.service.where()["follower"] == "connected"
    applied(await rig.run("stop"))
    assert "follower" not in rig.service.where()


async def test_a_pull_inside_the_grace_period_is_connected_and_roles_without_cues_have_no_follower(rig):
    applied(await rig.service.start(rig.start_body("user_presenter")))
    rig.service.armed_set()
    rig.mono.t += 3600
    assert rig.service.where()["follower"] == "connected"                      # sticky: authority is a separate matter
    applied(await rig.run("stop"))
    state = applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    assert state["follower"] is None                                           # Jarvis speaks: no ambient cue lane
    applied(await rig.run("stop"))
    silent = applied(await rig.service.start(rig.start_body("rehearsal")))
    assert silent["follower"] == "waiting" and rig.mode.mode is InteractionMode.PRESENTATION


async def test_a_pull_before_the_start_does_not_count_for_the_next_run(rig):
    rig.service.armed_set()                                                    # idle: nobody to follow
    state = applied(await rig.service.start(rig.start_body("user_presenter")))
    assert state["follower"] == "waiting"


# ------------------------------------------------------------------ P5: a commit is ours by identity

async def test_a_foreign_commit_landing_while_our_own_edit_is_in_flight_is_still_seen(rig):
    applied(await rig.service.start(rig.start_body()))
    original, entered, release = rig.edit.edit, asyncio.Event(), asyncio.Event()

    async def slow(pid, vid, raw, **kw):
        if kw.get("origin") is not None:
            entered.set()
            await release.wait()
        return await original(pid, vid, raw, **kw)

    rig.edit.edit = slow
    variant = await rig.studio.get_variant(rig.pid, rig.vid)
    own = asyncio.create_task(rig.service.edit({"actor": "user", "ops": [
        {"op": "control.set", "scene_id": S1, "control_id": "density", "value": "compact"}]}))
    await entered.wait()
    foreign = asyncio.create_task(original(rig.pid, rig.vid, {
        "actor": "user", "mode": "commit", "basis": {"variant_revision": variant.revision},
        "ops": [{"op": "control.set", "scene_id": S2, "control_id": "headline", "value": "Ailleurs"}]}))
    await asyncio.sleep(0.05)
    release.set()
    await own
    await foreign
    await asyncio.sleep(0.05)
    statuses = [attrs["status"] for _, _, attrs in rig.conversation.recorded]
    assert "edit_committed" in statuses, "the foreign commit was swallowed by a service-wide flag"
    assert rig.service.where()["phase"] == "paused"


# ------------------------------------------------------------------ P4: the stage window the user closes

async def test_closing_the_stage_is_reported_the_old_id_leaves_the_ledger_and_a_clean_stop_erases_it(rig):
    applied(await rig.service.start(rig.start_body()))
    first = rig.stage.stage_object_id
    await archive(rig, first)
    state = applied(await rig.run("next"))
    second = state["stage_object_id"]
    assert second == first + "-1" and "stage_closed_by_user" in state["notices"]
    assert rig.stage_ledger.ids == (second,) and rig.ledger_store.ids == [second]
    assert rig.env.sink.of("core.presentation_studio.stage_reopened")[0][0] == "warning"
    applied(await rig.run("stop"))
    assert rig.stage_ledger.ids == () and rig.ledger_store.ids is None        # the file really disappears


async def test_a_stage_closed_again_and_again_is_not_fought_the_run_pauses_and_says_so(rig):
    applied(await rig.service.start(rig.start_body()))
    for _ in range(MAX_STAGE_REOPENS):
        await archive(rig, rig.stage.stage_object_id)
        applied(await rig.run("next" if rig.service.where()["position"]["index"] == 1 else "previous"))
    await archive(rig, rig.stage.stage_object_id)
    result = await rig.run("next")
    assert result.status is PlaybackStatus.STAGE_FAILED and result.reason == "stage_closed"
    state = rig.service.where()
    assert state["phase"] == "paused" and "stage_stage_closed" in state["problems"] or "stage_closed" in state["problems"]


# ------------------------------------------------------------------ P3: an unreadable ledger no longer leaks windows

class CorruptStore(MemoryLedgerStore):
    def __init__(self) -> None:
        super().__init__()
        self.corrupt, self.kept = False, []

    def read(self):
        if self.corrupt:
            raise ValueError("not a stage ledger")
        return super().read()

    def quarantine(self):
        self.kept.append("presentation-studio-stage-ledger.json.corrupt-x")
        self.corrupt = False
        return self.kept[-1]


async def test_a_corrupt_ledger_falls_back_to_a_namespaced_scan_keeps_the_file_and_warns(tmp_path):
    store = CorruptStore()
    first = await Rig(tmp_path, ledger_store=store).open()
    try:
        applied(await first.service.start(first.start_body()))
        applied(await first.run("detour", title="Annexe", prefab=AUX_BLOCK))
        # a look-alike of the brain (right category, wrong id) and a studio-looking id of another category must survive
        for object_id, category in (("brain-window-1", "studio_stage"), ("studio-stage-fake", "brain")):
            await first.scene.apply(SceneCommand(
                op=SceneOp.UPSERT_OBJECT, actor=SceneActor.USER, object_id=object_id,
                fields=SceneObjectFields(kind=SceneObjectKind.WINDOW, category=category, representation=Representation.WINDOW,
                                         payload=ScenePayload(title="x", prefab=ScenePrefabRef("lab.counter", 1, {"label": "x"}, {"count": 1})))))
        visible = {o.object_id for o in await first.objects()}
        assert {"brain-window-1", "studio-stage-fake"} <= visible and len(visible) == 4
        store.corrupt = True                                                      # Core killed, the ledger damaged
        reborn = PresentationStudioPlaybackService(
            first.studio, first.edit, SceneStage(first.scene, StageLedger(store, diagnostics=first.env.sink), diagnostics=first.env.sink), first.mode,
            gate=first.gate, diagnostics=first.env.sink, monotonic=first.mono)
        await reborn.start_service()
        remaining = {o.object_id for o in await first.objects()}
        assert remaining == {"brain-window-1", "studio-stage-fake"}, remaining
        assert store.kept and first.env.sink.of("core.presentation_studio.stage_ledger_quarantined")[0][0] == "warning"
        [(level, data)] = first.env.sink.of("core.presentation_studio.stage_ledger_scan_reclaimed")
        assert level == "warning" and data["count"] == 2
    finally:
        await first.close()


def test_the_file_ledger_keeps_a_corrupt_file_aside_and_never_silently_overwrites_it(tmp_path):
    ledger = FileStageLedger(tmp_path)
    ledger.write(["studio-stage-r1"])
    path = tmp_path / "state" / LEDGER_FILE
    path.write_text('{"schema": "x"', encoding="utf-8")                           # truncated by a crash
    with pytest.raises(ValueError):
        ledger.read()
    name = ledger.quarantine()
    assert name and name.startswith(LEDGER_FILE + ".corrupt-") and not path.exists()
    assert (tmp_path / "state" / name).read_text(encoding="utf-8") == '{"schema": "x"'
    ledger.write(["studio-stage-r2"])                                              # the next run's write: evidence intact
    assert (tmp_path / "state" / name).exists() and json.loads(path.read_text(encoding="utf-8"))["object_ids"] == ["studio-stage-r2"]
    (tmp_path / "empty").mkdir()
    assert FileStageLedger(tmp_path / "empty").quarantine() is None


def test_quarantined_files_are_bounded(tmp_path):
    ledger = FileStageLedger(tmp_path)
    for index in range(KEEP_QUARANTINED + 3):
        ledger.write([f"studio-stage-r{index}"])
        (tmp_path / "state" / LEDGER_FILE).write_text("not json", encoding="utf-8")
        ledger.quarantine()
    kept = list((tmp_path / "state").glob(LEDGER_FILE + ".corrupt-*"))
    assert len(kept) == KEEP_QUARANTINED


# ------------------------------------------------------------------ P8: the whole answer is bounded

async def test_the_whole_where_answer_stays_inside_its_bound_at_the_worst_case(tmp_path):
    long = "é" * 80
    content = locked_content()
    content["items"][0].update({"label": long})
    content["items"][1].update({"label": long})
    rig = await Rig(tmp_path).open(content=content)
    try:
        applied(await rig.service.start(rig.start_body("user_presenter")))
        applied(await rig.run("detour", title=long, prefab=AUX_BLOCK))
        wire = rig.service.where()
        assert len(json.dumps(wire).encode()) <= MAX_VIEW_BYTES
        pure = {k: v for k, v in wire.items() if k not in ("presentation_id", "variant_id", "stage_object_id", "art_direction",
                                                          "notices", "mode", "follower")}
        from jarvis.domain.presentation_studio_playback import MAX_WHERE_BYTES
        assert len(json.dumps(pure).encode()) <= MAX_WHERE_BYTES + 700             # ensure_ascii inflates accents x6
    finally:
        await rig.close()
