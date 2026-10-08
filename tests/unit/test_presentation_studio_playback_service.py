"""Core playback service against the real scene, prefab catalogue, edit service and file store (Slice 12).

What is proven here, with real objects and no mock of the code under test: one stable stage window patched (not
recreated), the score's values as an ephemeral overlay (the variant file is byte-identical across a full run), an explicit
edit that pauses and commits, auxiliary windows that are always retired (stop, crash, killed Core), the interaction mode
switched and restored, art direction as a port, and the armed-cue delivery with a fake follower.
Contract: `docs/presentation-studio.md` > *Playback runtime contract*.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_presentation_studio_stage_ledger import FileStageLedger, LEDGER_FILE
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_events import StudioPlaybackEvents
from jarvis.core.presentation_studio_playback import PlaybackStatus, PresentationStudioPlaybackService
from jarvis.core.presentation_studio_stage import SceneStage, StageLedger
from jarvis.core.scene_service import SceneService, SceneState
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_armed_set import ARMED_CHANGED
from jarvis.domain.presentation_studio_playback import EventKind, Phase
from jarvis.domain.presentation_studio_roles import STUDIO_RUN_MODE_SOURCE
from tests.unit.test_presentation_studio_score_service import CUE, Env, I1, I2, I3, S1, S2, scene_body

S3 = "pss_0000000000a3"
I4 = "psi_000000000004"
CUE2 = "psc_000000000002"
AUX_BLOCK = {"id": "lab.counter", "version": 1, "props": {"label": "Annexe"}, "data": {"count": 1}}


def scenes_body():
    return [{**scene_body(S1), "title": "Un"}, {**scene_body(S2), "title": "Deux"}, {**scene_body(S3), "title": "Trois"}]


def score_content():
    return {
        "start_item_id": I1,
        "items": [
            {"item_id": I1, "scene_id": S1, "presenter": "user", "kind": "speech", "note": "Intro", "label": "Intro",
             "visual": [{"kind": "control_set", "scene_id": S1, "control_id": "headline", "value": "Un"}],
             "next_item_id": I2},
            {"item_id": I2, "scene_id": S2, "presenter": "user", "kind": "speech", "note": "Milieu", "cue_id": CUE,
             "visual": [{"kind": "control_set", "scene_id": S2, "control_id": "headline", "value": "Deux"},
                        {"kind": "reveal", "scene_id": S2, "anchor_id": "marker"}], "next_item_id": I3},
            {"item_id": I3, "scene_id": S2, "presenter": "none", "kind": "silence",
             "motion": [{"kind": "control_set", "scene_id": S2, "control_id": "density", "value": "compact"}],
             "next_item_id": I4},
            {"item_id": I4, "scene_id": S3, "presenter": "user", "kind": "speech", "note": "Fin", "cue_id": CUE2,
             "visual": [{"kind": "reveal", "scene_id": S3, "anchor_id": "reveal"}]}],
        "cues": [{"cue_id": CUE, "label": "Go", "armable": True, "predicate": {"phrases": ["passons a la suite"]}},
                 {"cue_id": CUE2, "label": "Fin", "armable": True, "predicate": {"phrases": ["voila la fin"]}}],
        "sequences": [], "recovery_points": []}


class Bus:
    def __init__(self) -> None:
        self.messages: list = []

    async def publish(self, envelope) -> None:
        self.messages.append((envelope.message_type, dict(envelope.payload)))


class Mono:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Conversation:
    def __init__(self) -> None:
        self.recorded: list[tuple[T, tuple[str, ...], dict]] = []

    def record(self, event_type, *, producer, conversation_id, source_ids, occurred_at, attributes, **_):
        self.recorded.append((event_type, source_ids, dict(attributes)))
        return "cev-" + "0" * 64


class MemoryLedgerStore:
    def __init__(self) -> None:
        self.ids: list[str] | None = None

    def read(self):
        return None if self.ids is None else list(self.ids)

    def write(self, ids):
        self.ids = list(ids)

    def erase(self):
        self.ids = None


class Gate:
    def __init__(self, *, fail: PresentationStudioError | None = None, revision: int = 1) -> None:
        self.calls: list[tuple[str, str, bool]] = []
        self.fail, self.revision = fail, revision

    async def require_art_direction(self, presentation_id, variant_id, *, serious=True):
        self.calls.append((presentation_id, variant_id, serious))
        if self.fail is not None:
            raise self.fail
        return {"status": "resolved", "fallback": False, "art_direction": {"revision": self.revision}}


class Rig:
    def __init__(self, tmp_path: Path, *, gate=None, ledger_store=None) -> None:
        self.env = Env(tmp_path)
        self.tmp = tmp_path
        self.gate, self.mono, self.bus = gate, Mono(), Bus()
        self.conversation, self.ledger_store = Conversation(), ledger_store or MemoryLedgerStore()

    async def open(self, *, scenes=None, content=None, with_score=True, mode=InteractionMode.ASSISTANT):
        env = self.env
        self.studio = await env.service()
        self.scene = SceneService(SQLiteSceneRepository(self.tmp / "scene.sqlite3"), prefab_validator=env.prefabs)
        assert (await self.scene.start()).state is SceneState.READY
        self.edit = PresentationStudioEditService(self.studio, diagnostics=env.sink, new_id=lambda: "pss_0000000000f1")
        self.pid, self.vid = await env.presentation(self.studio, [])
        variant = await self.studio.get_variant(self.pid, self.vid)
        await self.studio.save_variant(self.pid, self.vid, {
            "expected_revision": variant.revision, "title": variant.title, "scenes": scenes or scenes_body(),
            "art_direction_id": None, "score_id": None})
        if with_score:
            variant = await self.studio.get_variant(self.pid, self.vid)
            await self.studio.create_score(self.pid, self.vid, {"expected_variant_revision": variant.revision,
                                                                **(content or score_content())})
        self.mode = InteractionModeService(events=self.bus, epoch="epoch-1")
        if mode is not InteractionMode.ASSISTANT:
            await self.mode.request(mode, source="control_center")
        self.stage_ledger = StageLedger(self.ledger_store, diagnostics=env.sink)
        self.stage = SceneStage(self.scene, self.stage_ledger, diagnostics=env.sink)
        self.build()
        return self

    def build(self, **overrides):
        self.service = PresentationStudioPlaybackService(
            self.studio, self.edit, self.stage, self.mode, gate=self.gate, bus=self.bus,
            events=StudioPlaybackEvents(self.conversation, lambda: "conv-1"), diagnostics=self.env.sink,
            monotonic=self.mono, new_run_id=self._run_ids, **overrides)
        return self.service

    def _run_ids(self) -> str:
        self._runs = getattr(self, "_runs", -1) + 1
        return f"r{self._runs:011d}"

    @property
    def variant_file(self) -> Path:
        return self.env.root / "presentations" / self.pid / "variants" / f"{self.vid}.json"

    def digest(self) -> str:
        return hashlib.sha256(self.variant_file.read_bytes()).hexdigest()

    def tree_digest(self) -> dict[str, str]:
        root = self.env.root
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*.json"))}

    async def objects(self, category: str | None = None):
        snapshot = await self.scene.snapshot()
        return [o for o in snapshot.objects if category is None or o.category == category]

    async def stage_object(self):
        found = await self.objects("studio_stage")
        assert len(found) <= 1, "ONE stable stage window per run"
        return found[0] if found else None

    def start_body(self, role="user_presenter", **extra):
        return {"actor": "user", "presentation_id": self.pid, "role": role, **extra}

    async def run(self, verb: str, **fields):
        body = {"actor": "user", **fields}
        return await getattr(self.service, "back_from_detour" if verb == "return" else verb)(body)

    async def close(self):
        await self.scene.close()


@pytest.fixture
async def rig(tmp_path):
    made = await Rig(tmp_path).open()
    yield made
    await made.close()


def applied(result):
    assert result.status is PlaybackStatus.APPLIED, result.to_dict()
    return result.to_dict()["state"]


# ------------------------------------------------------------------ start, stage, stop

async def test_start_shows_one_stable_stage_window_and_next_patches_it_instead_of_recreating(rig):
    state = applied(await rig.service.start(rig.start_body()))
    assert state["phase"] == "playing" and state["scene"]["title"] == "Un" and state["position"] == {"index": 1, "of": 4}
    stage = await rig.stage_object()
    assert stage.object_id == state["stage_object_id"] == "studio-stage-r00000000000"
    assert stage.payload.title == "Un" and stage.payload.prefab.prefab_id == "lab.counter"
    revision_first = (await rig.scene.snapshot()).revision
    applied(await rig.run("next"))
    again = await rig.stage_object()
    assert again.object_id == stage.object_id and again.payload.title == "Deux"            # patched, same window
    assert [o.object_id for o in await rig.objects("studio_stage")] == [stage.object_id]
    assert (await rig.scene.snapshot()).revision == revision_first + 1
    assert rig.stage_ledger.ids == (stage.object_id,)
    # The same payload shown again writes nothing (a frame's own state is not reset by a "resume").
    revision = (await rig.scene.snapshot()).revision
    applied(await rig.run("previous"))
    applied(await rig.run("next"))
    assert (await rig.scene.snapshot()).revision == revision + 2


async def test_stop_archives_the_stage_clears_the_ledger_and_leaves_an_inspectable_record(rig):
    applied(await rig.service.start(rig.start_body()))
    state = applied(await rig.run("stop"))
    assert state["phase"] == "stopped" and state["running"] is False
    assert await rig.stage_object() is None and rig.stage_ledger.ids == () and rig.ledger_store.ids is None
    assert rig.service.where()["last_run"]["reason"] == "user" and rig.service.where()["last_run"]["problems"] == []
    again = await rig.run("stop")
    assert again.status is PlaybackStatus.REFUSED and again.reason == "not_running" and again.http_status == 409
    # a new run is possible afterwards and gets a stage window again
    rig.build();
    applied(await rig.service.start(rig.start_body()))
    assert (await rig.stage_object()) is not None


async def test_a_second_start_while_running_is_refused_without_touching_anything(rig):
    applied(await rig.service.start(rig.start_body()))
    revision = (await rig.scene.snapshot()).revision
    second = await rig.service.start(rig.start_body())
    assert second.status is PlaybackStatus.REFUSED and second.reason == "already_running"
    assert (await rig.scene.snapshot()).revision == revision


async def test_the_stage_the_user_closed_is_recreated_once_under_a_new_generation(rig):
    applied(await rig.service.start(rig.start_body()))
    stage = await rig.stage_object()
    from jarvis.domain.scene import SceneActor, SceneCommand, SceneOp
    from jarvis.domain.scene_selection import SceneSelection
    await rig.scene.apply(SceneCommand(op=SceneOp.ARCHIVE_SELECTION, actor=SceneActor.USER,
                                       selection=SceneSelection(ids=(stage.object_id,))))
    assert await rig.stage_object() is None
    state = applied(await rig.run("next"))
    now = await rig.stage_object()
    assert now.object_id == stage.object_id + "-1" and state["stage_object_id"] == now.object_id
    assert now.payload.title == "Deux"


# ------------------------------------------------------------------ the overlay never writes the variant

async def test_a_full_run_with_control_set_actions_leaves_every_stored_file_byte_identical(rig):
    before = rig.tree_digest()
    revision = (await rig.studio.get_variant(rig.pid, rig.vid)).revision
    applied(await rig.service.start(rig.start_body()))
    assert (await rig.stage_object()).payload.prefab.props["label"] == "Un"            # item 1: headline := "Un"
    applied(await rig.run("next"))
    stage = await rig.stage_object()
    assert stage.payload.prefab.props["label"] == "Deux"                               # item 2: headline := "Deux"
    assert stage.payload.prefab.props["mode"] == "full"                                # not yet "compact"
    applied(await rig.run("next"))
    assert (await rig.stage_object()).payload.prefab.props["mode"] == "compact"        # item 3: density (motion)
    applied(await rig.run("previous"))
    assert (await rig.stage_object()).payload.prefab.props["mode"] == "full"           # back: the value is restored
    for verb in ("next", "next"):
        applied(await rig.run(verb))
    applied(await rig.run("stop"))
    assert rig.tree_digest() == before, "playback wrote a stored document"
    assert (await rig.studio.get_variant(rig.pid, rig.vid)).revision == revision


async def test_a_marker_reveal_is_progress_only_and_a_control_bound_non_toggle_anchor_is_a_visible_notice(rig):
    applied(await rig.service.start(rig.start_body()))
    applied(await rig.run("goto", position=4))                      # item 4 reveals "reveal", bound to the integer `count`
    state = rig.service.where()
    assert state["phase"] == "playing" and "anchor_control_not_toggle" in state["notices"]
    assert state["revealed"] == ["reveal"]
    stage = await rig.stage_object()
    assert stage.payload.prefab.data["count"] == 12                  # the integer control did not move
    assert (await rig.run("hide", anchor_id="reveal")).status is PlaybackStatus.APPLIED


async def test_a_value_the_overlay_cannot_apply_pauses_the_run_with_a_visible_cause(rig):
    applied(await rig.service.start(rig.start_body()))

    async def broken(*args, **kwargs):
        raise PresentationStudioError(C.PREFAB_UNAVAILABLE, "the catalogue is down")

    rig.edit.render_overlay = broken
    result = await rig.run("next")
    assert result.status is PlaybackStatus.STAGE_FAILED and result.http_status == 500
    assert "catalogue is down" in result.message and result.to_dict()["error"]["code"] == C.PLAYBACK_STAGE_FAILED.value
    state = rig.service.where()
    assert state["phase"] == "paused" and state["problems"] == ["stage_presentation_studio_prefab_unavailable"]
    assert state["position"]["index"] == 2                          # the position moved, the stage did not: said, not hidden


# ------------------------------------------------------------------ explicit edit pauses and commits; improvisation never

async def test_an_explicit_edit_pauses_commits_through_the_edit_service_and_the_stage_follows(rig):
    applied(await rig.service.start(rig.start_body()))
    before = rig.digest()
    revision = (await rig.studio.get_variant(rig.pid, rig.vid)).revision
    result = await rig.service.edit({"actor": "user", "ops": [
        {"op": "control.set", "scene_id": S1, "control_id": "headline", "value": "Nouveau titre"}]})
    assert result.status is PlaybackStatus.APPLIED and result.to_dict()["edit"]["committed"] is True
    assert rig.digest() != before and (await rig.studio.get_variant(rig.pid, rig.vid)).revision == revision + 1
    state = rig.service.where()
    assert state["phase"] == "paused"                               # pause first, resume on purpose
    stored = (await rig.studio.get_variant(rig.pid, rig.vid)).scenes[0]
    assert stored.props["label"] == "Nouveau titre"
    # the overlay of item 1 still wins on screen for scene 1 (the score sets headline := "Un"); the score is the author's
    # script, the committed value is the canonical base: both facts hold
    assert (await rig.stage_object()).payload.prefab.props["label"] == "Un"
    applied(await rig.run("resume"))
    assert rig.service.where()["phase"] == "playing"


async def test_an_edit_the_edit_service_refuses_is_reported_and_writes_nothing(rig):
    applied(await rig.service.start(rig.start_body()))
    before = rig.digest()
    result = await rig.service.edit({"actor": "user", "ops": [
        {"op": "control.set", "scene_id": S1, "control_id": "nope", "value": 1}]})
    assert result.status is PlaybackStatus.REFUSED and result.reason == C.UNKNOWN_CONTROL.value
    assert rig.digest() == before and rig.service.where()["phase"] == "paused"


async def test_an_edit_made_elsewhere_during_the_run_pauses_it_and_the_stage_follows(rig):
    applied(await rig.service.start(rig.start_body()))
    variant = await rig.studio.get_variant(rig.pid, rig.vid)
    result = await rig.edit.edit(rig.pid, rig.vid, {
        "actor": "user", "mode": "commit", "basis": {"variant_revision": variant.revision},
        "ops": [{"op": "control.set", "scene_id": S1, "control_id": "density", "value": "compact"}]})
    assert result.committed
    assert rig.service.where()["phase"] == "paused"
    assert (await rig.stage_object()).payload.prefab.props["mode"] == "compact"           # the visible window followed
    assert rig.service.state.problems == ()


async def test_speaking_cues_and_navigation_are_improvisation_and_never_write(rig):
    before = rig.tree_digest()
    applied(await rig.service.start(rig.start_body()))
    await rig.service.notify(EventKind.SPEAKING, speaker=None)
    applied(await rig.run("goto", position=3))
    applied(await rig.run("reveal", anchor_id="marker"))
    applied(await rig.run("stop"))
    assert rig.tree_digest() == before


# ------------------------------------------------------------------ detour: aux windows are always retired

async def test_a_detour_stages_the_aux_window_hidden_then_visible_and_return_retires_it(rig):
    applied(await rig.service.start(rig.start_body()))
    applied(await rig.run("next"))
    position = rig.service.where()["position"]
    state = applied(await rig.run("detour", title="Annexe", prefab=AUX_BLOCK))
    assert state["phase"] == "detour" and state["detour"] == {"depth": 1, "title": "Annexe"}
    [aux] = await rig.objects("studio_aux")
    assert aux.visibility.value == "visible" and aux.payload.prefab.props["label"] == "Annexe"
    assert aux.object_id in rig.stage_ledger.ids and len(rig.stage_ledger.ids) == 2
    stage = await rig.stage_object()
    assert stage.payload.title == "Deux"                                                 # the stage is untouched
    assert (await rig.run("next")).reason == "in_detour"
    state = applied(await rig.run("return"))
    assert await rig.objects("studio_aux") == [] and rig.stage_ledger.ids == (stage.object_id,)
    assert state["phase"] == "playing" and state["position"] == position


async def test_stop_in_the_middle_of_nested_detours_retires_every_aux_window(rig):
    applied(await rig.service.start(rig.start_body()))
    for index in range(3):
        applied(await rig.run("detour", title=f"Annexe {index}", prefab=AUX_BLOCK))
    assert len(await rig.objects("studio_aux")) == 3
    applied(await rig.run("stop"))
    assert await rig.objects("studio_aux") == [] and await rig.stage_object() is None
    assert rig.stage_ledger.ids == ()


async def test_an_aux_that_cannot_be_staged_is_a_visible_problem_not_a_silent_detour(rig):
    applied(await rig.service.start(rig.start_body()))
    result = await rig.run("detour", title="Annexe", prefab={**AUX_BLOCK, "id": "lab.nothing"})
    assert result.status is PlaybackStatus.STAGE_FAILED and "aux_stage_failed" in rig.service.where()["problems"]
    assert await rig.objects("studio_aux") == []
    applied(await rig.run("return"))                                      # the run is not stuck in the detour


async def test_a_crash_inside_a_command_ends_the_run_cleanly_and_propagates(rig):
    applied(await rig.service.start(rig.start_body("user_presenter")))
    applied(await rig.run("detour", title="Annexe", prefab=AUX_BLOCK))

    async def boom(payload):
        raise RuntimeError("kaboom")

    rig.stage.show = boom                       # not a StageError: an unexpected bug in the stage layer
    with pytest.raises(RuntimeError, match="kaboom"):
        await rig.run("return")
    state = rig.service.where()
    assert state["phase"] == "stopped" and state["last_run"]["reason"] == "crashed"
    assert await rig.objects("studio_aux") == [] and await rig.stage_object() is None
    assert rig.stage_ledger.ids == () and rig.mode.mode is InteractionMode.ASSISTANT
    assert rig.env.sink.of("core.presentation_studio.playback_crashed")[0][0] == "error"


# ------------------------------------------------------------------ killed Core: reclaim by id list

async def test_a_core_killed_mid_run_is_reclaimed_at_the_next_start_by_id_list(tmp_path):
    root = tmp_path / "studio"
    first = Rig(tmp_path, ledger_store=FileStageLedger(root))
    await first.open()
    applied(await first.service.start(first.start_body()))
    applied(await first.run("detour", title="Annexe", prefab=AUX_BLOCK))
    leftovers = {o.object_id for o in await first.objects() if o.category.startswith("studio_")}
    assert len(leftovers) == 2 and (root / "state" / LEDGER_FILE).exists()
    # a brain object of the same shape that the Studio did NOT create must survive the reclaim
    from jarvis.domain.scene import (Representation, SceneActor, SceneCommand, SceneObjectFields, SceneObjectKind, SceneOp,
                                     ScenePayload, ScenePrefabRef)
    await first.scene.apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id="brain-window-1",
                                         fields=SceneObjectFields(kind=SceneObjectKind.WINDOW,
                                                                  category="studio_aux",
                                                                  payload=ScenePayload(title="Brain's", prefab=ScenePrefabRef(
                                                                      "lab.counter", 1, {"label": "x"}, {"count": 1})),
                                                                  representation=Representation.WINDOW)))
    # no stop, no close: the process "dies". A new life with the same scene and the same ledger file:
    second_ledger = StageLedger(FileStageLedger(root), diagnostics=first.env.sink)
    second_stage = SceneStage(first.scene, second_ledger, diagnostics=first.env.sink)
    reborn = PresentationStudioPlaybackService(first.studio, first.edit, second_stage, first.mode,
                                               diagnostics=first.env.sink, monotonic=first.mono)
    await reborn.start_service()
    remaining = {o.object_id for o in await first.objects()}
    assert not (leftovers & remaining) and "brain-window-1" in remaining
    assert not (root / "state" / LEDGER_FILE).exists()
    assert reborn.where() == {"phase": "idle", "running": False}
    await first.close()


# ------------------------------------------------------------------ role and mode

async def test_user_presenter_switches_to_presentation_and_stop_restores_without_touching_the_preference(rig):
    assert rig.mode.mode is InteractionMode.ASSISTANT
    state = applied(await rig.service.start(rig.start_body("user_presenter")))
    assert rig.mode.mode is InteractionMode.PRESENTATION and rig.mode.state.source == STUDIO_RUN_MODE_SOURCE
    assert state["role"] == "user_presenter" and state["mode"] == "presentation"
    applied(await rig.run("stop"))
    assert rig.mode.mode is InteractionMode.ASSISTANT and rig.mode.state.source == STUDIO_RUN_MODE_SOURCE


async def test_jarvis_presenter_runs_in_assistant_and_needs_no_switch(rig):
    revision = rig.mode.revision
    state = applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    assert rig.mode.mode is InteractionMode.ASSISTANT and rig.mode.revision == revision and state["jarvis_speaks"] is True
    applied(await rig.run("stop"))
    assert rig.mode.revision == revision


async def test_rehearsal_with_a_speaking_jarvis_runs_in_assistant_and_a_silent_one_in_presentation(tmp_path):
    rig = await Rig(tmp_path, gate=Gate()).open(mode=InteractionMode.PRESENTATION)
    applied(await rig.service.start(rig.start_body("rehearsal", jarvis_speaks=True)))
    assert rig.mode.mode is InteractionMode.ASSISTANT
    applied(await rig.run("stop"))
    assert rig.mode.mode is InteractionMode.PRESENTATION                      # restored to what the user had
    applied(await rig.service.start(rig.start_body("rehearsal")))
    assert rig.mode.mode is InteractionMode.PRESENTATION
    assert rig.gate.calls[-1][2] is False and rig.gate.calls[0][2] is False   # a rehearsal is not a serious run
    await rig.close()


async def test_the_brain_cannot_switch_the_mode_unless_it_declares_an_explicit_user_request(rig):
    body = rig.start_body("user_presenter", actor="brain")
    refused = await rig.service.start(body)
    assert refused.status is PlaybackStatus.REFUSED and refused.reason == "mode_switch_refused"
    assert rig.mode.mode is InteractionMode.ASSISTANT and await rig.stage_object() is None
    ok = await rig.service.start({**body, "origin": "explicit_user_request"})
    assert ok.status is PlaybackStatus.APPLIED and rig.mode.mode is InteractionMode.PRESENTATION
    for origin in ("ambient_text", "score_content", "system_replay"):
        with pytest.raises(ValueError):
            await rig.service.start({**body, "origin": origin, "actor": "user"})


async def test_a_manual_mode_change_during_the_run_stops_it_and_leaves_the_users_choice(rig):
    applied(await rig.service.start(rig.start_body("user_presenter")))
    applied(await rig.run("detour", title="Annexe", prefab=AUX_BLOCK))
    await rig.mode.request("assistant", source="control_center")            # the user picks SIMPLE by hand
    await asyncio.gather(*list(rig.service._tasks))
    state = rig.service.where()
    assert state["phase"] == "stopped" and state["last_run"]["reason"] == "mode_changed_by_user"
    assert rig.mode.mode is InteractionMode.ASSISTANT and rig.mode.state.source == "control_center"   # never forced back
    assert await rig.objects("studio_aux") == [] and await rig.stage_object() is None


async def test_our_own_switch_and_restore_never_stop_the_run(rig):
    applied(await rig.service.start(rig.start_body("user_presenter")))
    await asyncio.sleep(0)
    assert not rig.service._tasks and rig.service.where()["phase"] == "playing"


async def test_a_restore_that_fails_is_a_visible_error_and_the_run_still_ends(rig, monkeypatch):
    applied(await rig.service.start(rig.start_body("user_presenter")))

    async def unavailable(value, *, source):
        raise ValueError("the mode service is unavailable")

    monkeypatch.setattr(rig.mode, "request", unavailable)
    result = await rig.run("stop")
    assert result.status is PlaybackStatus.STAGE_FAILED and result.reason == "mode_restore_failed"
    assert "mode service is unavailable" in result.message             # the real cause, not a generic label
    state = rig.service.where()
    assert state["phase"] == "stopped" and state["last_run"]["problems"] == ["mode_restore_failed"]
    assert rig.env.sink.of("core.presentation_studio.mode_restore_failed")[0][0] == "error"
    assert rig.mode.mode is InteractionMode.PRESENTATION                # left as is, no retry loop
    assert await rig.stage_object() is None                             # the rest of the cleanup still happened


# ------------------------------------------------------------------ art direction gate, score problems

async def test_the_art_direction_gate_runs_before_a_run_and_a_refusal_changes_nothing(tmp_path):
    refusal = PresentationStudioError(C.INVALID_PRESENTATION, "art_direction_required: no art direction")
    rig = await Rig(tmp_path, gate=Gate(fail=refusal)).open()
    with pytest.raises(PresentationStudioError, match="art_direction_required"):
        await rig.service.start(rig.start_body())
    assert rig.gate.calls == [(rig.pid, rig.vid, True)]
    assert rig.mode.mode is InteractionMode.ASSISTANT and await rig.stage_object() is None
    assert rig.service.where() == {"phase": "idle", "running": False}
    await rig.close()


async def test_without_a_gate_the_run_says_so_and_with_one_it_says_checked(tmp_path):
    rig = await Rig(tmp_path).open()
    state = applied(await rig.service.start(rig.start_body()))
    assert state["art_direction"] == "unchecked"
    assert rig.env.sink.of("core.presentation_studio.playback_art_direction_unchecked")[0][0] == "warning"
    await rig.close()
    other = tmp_path / "gated"
    other.mkdir()
    gated = await Rig(other, gate=Gate()).open()
    assert applied(await gated.service.start(gated.start_body()))["art_direction"] == "checked"
    await gated.close()


async def test_art_direction_changing_while_paused_is_a_notice_on_resume(tmp_path):
    gate = Gate(revision=1)
    rig = await Rig(tmp_path, gate=gate).open()
    state = applied(await rig.service.start(rig.start_body()))
    assert state["art_direction"] == "checked"
    applied(await rig.run("pause"))
    gate.revision = 2                                   # saved apart: `variant.revision` does not move
    applied(await rig.run("resume"))
    assert "art_direction_changed" in rig.service.where()["notices"]
    await rig.close()


async def test_a_score_whose_scene_was_removed_is_refused_at_start_with_the_problem(tmp_path):
    rig = await Rig(tmp_path).open()
    variant = await rig.studio.get_variant(rig.pid, rig.vid)
    await rig.studio.save_variant(rig.pid, rig.vid, {
        "expected_revision": variant.revision, "title": variant.title, "scenes": scenes_body()[:2],
        "art_direction_id": None, "score_id": variant.score_id})
    with pytest.raises(PresentationStudioError) as caught:
        await rig.service.start(rig.start_body())
    assert caught.value.code is C.SCORE_INCOMPATIBLE and "no longer resolve" in caught.value.message
    assert await rig.stage_object() is None
    await rig.close()


async def test_a_variant_without_a_score_cannot_be_played(tmp_path):
    rig = await Rig(tmp_path).open(with_score=False)
    with pytest.raises(PresentationStudioError) as caught:
        await rig.service.start(rig.start_body())
    assert caught.value.code is C.UNKNOWN_SCORE
    await rig.close()


async def test_removing_a_scene_during_a_paused_run_is_a_problem_not_a_crash(rig):
    applied(await rig.service.start(rig.start_body()))
    applied(await rig.run("pause"))
    variant = await rig.studio.get_variant(rig.pid, rig.vid)
    await rig.studio.save_variant(rig.pid, rig.vid, {
        "expected_revision": variant.revision, "title": variant.title, "scenes": scenes_body()[:2],
        "art_direction_id": None, "score_id": variant.score_id})
    applied(await rig.run("resume"))
    state = rig.service.where()
    assert "score_problems" in state["problems"] + state["notices"]
    assert state["phase"] in ("paused", "playing")


# ------------------------------------------------------------------ armed-cue delivery with a fake follower

class Follower:
    """What Slice 13 will be: hears the content-free bus message, pulls the set, reports a typed id. Never text."""

    def __init__(self, service: PresentationStudioPlaybackService, bus: Bus) -> None:
        self.service, self.bus, self.seen = service, bus, 0

    def messages(self):
        new = [p for t, p in self.bus.messages[self.seen:] if t == ARMED_CHANGED]
        self.seen = len(self.bus.messages)
        return new

    def pull(self):
        return self.service.armed_set()

    async def report(self, message, cue_id=None, **override):
        cue = cue_id or message["cues"][0]["cue_id"]
        return await self.service.report_cue({"run_id": message["run_id"], "generation": message["generation"],
                                              "cue_id": cue, **override})


async def test_the_follower_learns_the_set_from_a_content_free_message_then_pulls_and_reports(rig):
    follower = Follower(rig.service, rig.bus)
    applied(await rig.service.start(rig.start_body()))
    [announced] = follower.messages()
    assert announced == {"run_id": "r00000000000", "generation": 1, "count": 1}       # item 2's cue is armed
    for _, payload in rig.bus.messages:
        assert "passons" not in json.dumps(payload)
    message = follower.pull()
    assert message["cues"][0]["phrases"] == ["passons a la suite"] and message["generation"] == announced["generation"]
    answer = await follower.report(message)
    assert answer["status"] == "fired" and answer["http_status"] == 200
    assert rig.service.where()["position"]["index"] == 2
    [after] = follower.messages()
    assert after["generation"] == announced["generation"] + 1


async def test_stale_generation_stale_run_unarmed_expired_and_rate_limited_reports_are_refused(rig):
    follower = Follower(rig.service, rig.bus)
    applied(await rig.service.start(rig.start_body()))
    message = follower.pull()
    position = rig.service.where()["position"]
    refused = await follower.report(message, generation=message["generation"] + 1)
    assert refused["code"] == "stale_generation" and refused["http_status"] == 409
    refused = await follower.report(message, run_id="someone-else")
    assert refused["code"] == "stale_run"
    refused = await follower.report(message, cue_id=CUE2)
    assert refused["code"] == "cue_not_armed" and refused["reason"] == "cue_not_armed"
    refused = await follower.report(message, cue_id="psc_ffffffffffff")
    assert refused["code"] == "cue_not_armed"
    assert rig.service.where()["position"] == position                          # nothing moved
    rig.mono.t += 91                                                             # the follower went silent for > TTL
    refused = await follower.report(message)
    assert refused["code"] == "armed_set_expired"
    follower.pull()                                                              # a pull renews its authority
    assert (await follower.report(message))["status"] == "fired"
    with pytest.raises(ValueError):
        await rig.service.report_cue({"run_id": "r", "generation": 1, "cue_id": CUE, "text": "passons a la suite"})


async def test_a_report_that_fired_is_idempotent_and_never_fires_twice(rig):
    follower = Follower(rig.service, rig.bus)
    applied(await rig.service.start(rig.start_body()))
    message = follower.pull()
    first = await follower.report(message)
    second = await follower.report(message)
    assert first["status"] == "fired" and second == {**first, "duplicate": True}
    assert rig.service.where()["position"]["index"] == 2                          # advanced once, not twice
    third = await follower.report(message, cue_id=CUE2)                           # the old generation, another cue
    assert third["code"] == "stale_generation"


async def test_reports_are_rate_limited(rig):
    follower = Follower(rig.service, rig.bus)
    applied(await rig.service.start(rig.start_body()))
    message = follower.pull()
    codes = [(await follower.report(message, cue_id="psc_ffffffffffff")).get("code") for _ in range(8)]
    assert codes[:5] == ["cue_not_armed"] * 5 and codes[5:] == ["rate_limited"] * 3
    rig.mono.t += 2
    assert (await follower.report(message, cue_id="psc_ffffffffffff"))["code"] == "cue_not_armed"


async def test_nothing_is_armed_while_paused_or_detoured_and_the_pull_says_so(rig):
    follower = Follower(rig.service, rig.bus)
    applied(await rig.service.start(rig.start_body()))
    assert follower.pull()["cues"]
    applied(await rig.run("pause"))
    paused = follower.pull()
    assert paused["cues"] == [] and paused["run_id"] == "r00000000000"
    refused = await follower.report({"run_id": paused["run_id"], "generation": paused["generation"]}, cue_id=CUE)
    assert refused["code"] == "cue_not_armed"
    applied(await rig.run("resume"))
    assert follower.pull()["cues"]


async def test_a_stopped_run_arms_nothing_and_old_reports_are_stale_run(rig):
    follower = Follower(rig.service, rig.bus)
    applied(await rig.service.start(rig.start_body()))
    message = follower.pull()
    applied(await rig.run("stop"))
    assert follower.pull()["cues"] == []
    assert (await follower.report(message))["code"] == "stale_run"


async def test_a_bus_that_fails_does_not_stop_the_run_but_is_an_error_row(rig):
    async def broken(envelope):
        raise ConnectionError("bus down")

    rig.bus.publish = broken
    applied(await rig.service.start(rig.start_body()))
    assert rig.env.sink.of("core.presentation_studio.armed_publish_failed")[0][0] == "error"
    assert rig.service.armed_set()["cues"]                                         # the pull still works: nothing lost


# ------------------------------------------------------------------ events and read model

async def test_playback_events_are_content_free_status_words(rig):
    applied(await rig.service.start(rig.start_body()))
    applied(await rig.run("pause"))
    applied(await rig.run("resume"))
    applied(await rig.run("detour", title="Titre secret", prefab=AUX_BLOCK))
    applied(await rig.run("return"))
    applied(await rig.run("stop"))
    statuses = [a["status"] for t, _, a in rig.conversation.recorded if t is T.SYSTEM_PRESENTATION_STUDIO_PLAYBACK_CHANGED]
    assert statuses == ["started", "paused", "resumed", "detour", "returned", "stopped"]
    text = json.dumps(rig.conversation.recorded, default=str)
    assert "Titre secret" not in text and "passons" not in text
    keys = {k for t, _, a in rig.conversation.recorded for k in a}
    assert keys <= {"presentation_id", "variant_id", "status", "role", "depth"}
    ids = [s for _, s, _ in rig.conversation.recorded]
    assert len(set(ids)) == len(ids), "each fact has its own identity"


async def test_where_are_we_through_the_service_is_bounded_and_holds_no_script(rig):
    applied(await rig.service.start(rig.start_body()))
    state = rig.service.where()
    assert len(json.dumps(state, ensure_ascii=False).encode()) < 2600
    assert "Intro" not in json.dumps(state["next"]) and state["next"]["cue"]["label"] == "Go"
    assert state["presentation_id"] == rig.pid and state["stage_object_id"]
    assert rig.service.where()["elapsed"]["item_ms"] == 0
    rig.mono.t += 5
    assert rig.service.where()["elapsed"]["item_ms"] == 5000


async def test_close_ends_a_live_run_cleanly(rig):
    applied(await rig.service.start(rig.start_body("user_presenter")))
    applied(await rig.run("detour", title="Annexe", prefab=AUX_BLOCK))
    await rig.service.close()
    assert await rig.stage_object() is None and await rig.objects("studio_aux") == []
    assert rig.mode.mode is InteractionMode.ASSISTANT and rig.service.where()["last_run"]["reason"] == "shutdown"
