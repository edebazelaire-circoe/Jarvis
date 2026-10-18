"""Core playback service against the real scene, prefab catalogue, edit service and file store (Slice 12).

What is proven here, with real objects and no mock of the code under test: one stable run surface of Variants patched (not
recreated, no Board object; native-studio-playback-fix Slice 09), the score's values as an ephemeral overlay (the variant file is
byte-identical across a full run), an explicit edit that pauses and commits, detour overlays that are always retired (stop,
crash), the Board windows an older Core left archived at start, the interaction mode switched and restored, art direction as a
port, and the armed-cue delivery with a fake follower.
Contract: `docs/presentation-studio.md` > *Playback runtime contract*.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_presentation_studio_stage_ledger import FileStageLedger, LEDGER_FILE, SCHEMA as LEDGER_SCHEMA
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_events import StudioPlaybackEvents
from jarvis.core.presentation_studio_playback import PlaybackStatus, PresentationStudioPlaybackService
from jarvis.core.presentation_studio_run_surface import RunSurface
from jarvis.core.presentation_studio_stage import LegacyStageReclaimer, StageLedger
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
    """The ledger an older Core left (read once, then kept aside: `retired`)."""

    def __init__(self, ids: list[str] | None = None) -> None:
        self.ids, self.retired = ids, None

    def read(self):
        return None if self.ids is None else list(self.ids)

    def retire(self):
        if self.ids is None:
            return None
        self.retired, self.ids = list(self.ids), None
        return "ledger.retired"


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
        self.gate, self.mono, self.bus = gate if gate is not None else Gate(), Mono(), Bus()
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
            # The Board-derived baseline (a Présentation Board restored at Core start): nothing else sets a mode.
            await self.mode.request(mode, source="board_restore")
        self.stage_ledger = StageLedger(self.ledger_store, diagnostics=env.sink)
        self.reclaimer = LegacyStageReclaimer(self.scene, self.stage_ledger, diagnostics=env.sink)
        self.stage = RunSurface(validator=env.prefabs, reclaimer=self.reclaimer, diagnostics=env.sink)
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
        """Board objects (Slice 09: a run never creates one)."""

        snapshot = await self.scene.snapshot()
        return [o for o in snapshot.objects if category is None or o.category == category]

    async def stage_object(self):
        """The run surface of Variants as the page reads it: `None`, or `.object_id` and `.payload` (title, prefab)."""

        snapshot = self.stage.snapshot()
        if snapshot is None:
            return None
        from types import SimpleNamespace
        return SimpleNamespace(object_id=snapshot["surface_id"], revision=snapshot["revision"], wire=snapshot,
                               payload=self.stage._shown)

    def overlays(self):
        """The detour overlays inside the surface (`visible`, `block`, `title`)."""

        return list(self.stage._overlays.values())

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

async def test_start_shows_one_stable_run_surface_and_next_patches_it_without_any_board_object(rig):
    board_before = (await rig.scene.snapshot()).revision
    state = applied(await rig.service.start(rig.start_body()))
    assert state["phase"] == "playing" and state["scene"]["title"] == "Un" and state["position"] == {"index": 1, "of": 4}
    stage = await rig.stage_object()
    assert stage.object_id == state["stage_object_id"] == "variants-run-r00000000000"
    assert state["surface"] == {"id": stage.object_id, "rev": stage.revision}            # the page refetches when `rev` moves
    assert stage.payload.title == "Un" and stage.payload.prefab.prefab_id == "lab.counter"
    assert rig.service.surface()["prefab"]["id"] == "lab.counter" and rig.service.surface()["overlays"] == []
    revision_first = stage.revision
    applied(await rig.run("next"))
    again = await rig.stage_object()
    assert again.object_id == stage.object_id and again.payload.title == "Deux"            # patched, same surface
    assert again.revision == revision_first + 1
    # The same payload shown again writes nothing (a frame's own state is not reset by a "resume").
    applied(await rig.run("previous"))
    applied(await rig.run("next"))
    assert (await rig.stage_object()).revision == revision_first + 3
    # PX-16: no Board object was created or touched by the whole run
    assert (await rig.scene.snapshot()).revision == board_before and await rig.objects() == []


async def test_stop_releases_the_surface_and_leaves_an_inspectable_record(rig):
    applied(await rig.service.start(rig.start_body()))
    state = applied(await rig.run("stop"))
    assert state["phase"] == "stopped" and state["running"] is False and "surface" not in state
    assert await rig.stage_object() is None and rig.service.surface() is None
    assert rig.service.where()["last_run"]["reason"] == "user" and rig.service.where()["last_run"]["problems"] == []
    again = await rig.run("stop")
    assert again.status is PlaybackStatus.REFUSED and again.reason == "not_running" and again.http_status == 409
    # a new run is possible afterwards and gets its own surface
    rig.build();
    applied(await rig.service.start(rig.start_body()))
    assert (await rig.stage_object()).object_id == "variants-run-r00000000001"


async def test_a_second_start_while_running_is_refused_without_touching_anything(rig):
    applied(await rig.service.start(rig.start_body()))
    revision = (await rig.stage_object()).revision
    second = await rig.service.start(rig.start_body())
    assert second.status is PlaybackStatus.REFUSED and second.reason == "already_running"
    assert (await rig.stage_object()).revision == revision and await rig.objects() == []


async def test_a_block_the_catalogue_refuses_never_reaches_the_surface_and_pauses_the_run(rig):
    """The surface is validated like the scene window was (`prefab_invalid`, the catalogue's reason), never shown unchecked."""

    applied(await rig.service.start(rig.start_body()))
    shown = (await rig.stage_object()).payload
    from jarvis.domain.scene import ScenePayload, ScenePrefabRef
    from jarvis.core.presentation_studio_stage import StageError
    with pytest.raises(StageError) as caught:
        await rig.stage.show(ScenePayload(title="x", prefab=ScenePrefabRef("lab.nothing", 1, {}, {})))
    assert caught.value.code == "prefab_invalid" and "lab.nothing" in caught.value.message
    assert (await rig.stage_object()).payload == shown


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

async def test_a_detour_is_an_overlay_inside_the_surface_hidden_then_visible_and_return_retires_it(rig):
    """PX-20: a detour shows as an overlay inside the Variants stage, never a Board window; `return` removes it; the frame underneath
    is unchanged."""

    applied(await rig.service.start(rig.start_body()))
    applied(await rig.run("next"))
    position = rig.service.where()["position"]
    under = (await rig.stage_object()).payload
    state = applied(await rig.run("detour", title="Annexe", prefab=AUX_BLOCK))
    assert state["phase"] == "detour" and state["detour"] == {"depth": 1, "title": "Annexe"}
    [aux] = rig.overlays()
    assert aux.visible is True and aux.block.props["label"] == "Annexe" and aux.title == "Annexe"
    assert rig.service.surface()["overlays"][0]["visible"] is True and await rig.objects() == []      # not a Board window
    stage = await rig.stage_object()
    assert stage.payload == under                                                        # the frame underneath is untouched
    assert (await rig.run("next")).reason == "in_detour"
    state = applied(await rig.run("return"))
    assert rig.overlays() == [] and (await rig.stage_object()).payload == under
    assert state["phase"] == "playing" and state["position"] == position


async def test_stop_in_the_middle_of_nested_detours_retires_every_overlay(rig):
    applied(await rig.service.start(rig.start_body()))
    for index in range(3):
        applied(await rig.run("detour", title=f"Annexe {index}", prefab=AUX_BLOCK))
    assert len(rig.overlays()) == 3
    applied(await rig.run("stop"))
    assert rig.overlays() == [] and await rig.stage_object() is None


async def test_an_aux_that_cannot_be_staged_is_reported_and_leaves_no_phantom_detour(rig):
    """Without a catalogue check up front the surface's catalogue check is the judge: the failure is reported (500, the real
    cause) and the transition is UNDONE, so `next` / `previous` / `pause` still work (QA-1 P2)."""

    applied(await rig.service.start(rig.start_body()))
    before = rig.service.where()
    result = await rig.run("detour", title="Annexe", prefab={**AUX_BLOCK, "id": "lab.nothing"})
    assert result.status is PlaybackStatus.STAGE_FAILED and result.reason == "prefab_invalid"
    after = rig.service.where()
    assert after["phase"] == "playing" and after["detour"] is None and after["problems"] == []
    assert after["armed"] == before["armed"] and after["generation"] > before["generation"]   # monotonic, never reused
    assert rig.overlays() == [] and await rig.objects() == []
    applied(await rig.run("next"))                                        # not stuck in a detour that never showed


async def test_a_crash_inside_a_command_ends_the_run_cleanly_and_propagates(rig):
    applied(await rig.service.start(rig.start_body("user_presenter")))
    applied(await rig.run("detour", title="Annexe", prefab=AUX_BLOCK))

    async def boom(payload, **kwargs):
        raise RuntimeError("kaboom")

    rig.stage.show = boom                       # not a StageError: an unexpected bug in the stage layer
    with pytest.raises(RuntimeError, match="kaboom"):
        await rig.run("return")
    state = rig.service.where()
    assert state["phase"] == "stopped" and state["last_run"]["reason"] == "crashed"
    assert rig.overlays() == [] and await rig.stage_object() is None
    assert rig.mode.mode is InteractionMode.ASSISTANT
    assert rig.env.sink.of("core.presentation_studio.playback_crashed")[0][0] == "error"


# ------------------------------------------------------------------ legacy: the Board windows an older Core left (Slice 09)

async def _legacy_window(scene, object_id: str, category: str, actor=None) -> None:
    from jarvis.domain.scene import (Representation, SceneActor, SceneCommand, SceneObjectFields, SceneObjectKind, SceneOp,
                                     ScenePayload, ScenePrefabRef)
    await scene.apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=actor or SceneActor.USER, object_id=object_id,
                                   fields=SceneObjectFields(kind=SceneObjectKind.WINDOW, category=category,
                                                            payload=ScenePayload(title=object_id, prefab=ScenePrefabRef(
                                                                "lab.counter", 1, {"label": "x"}, {"count": 1})),
                                                            representation=Representation.WINDOW)))


async def test_board_windows_an_older_core_left_are_archived_at_start_and_its_ledger_kept_aside(tmp_path):
    """PX-16 and persisted state: a `studio-stage-*` / `studio-aux-*` window of the retired floating viewer, persisted on the scene
    by an older Core (killed mid-run), is archived once at Core start (ledger ids AND a scan of the retired categories, the ledger is gone or not);
    the old ledger file is kept aside (`.retired-*`), never deleted; an object of a retired category with another id (a brain
    orphan: never drawn, refused to the Tool Brain) is archived too (Slice 09 rework); another category survives."""

    root = tmp_path / "studio"
    rig = Rig(tmp_path, ledger_store=FileStageLedger(root))
    await rig.open()
    try:
        await _legacy_window(rig.scene, "studio-stage-oldrun", "studio_stage")
        await _legacy_window(rig.scene, "studio-stage-lost-1", "studio_stage")          # not in the ledger: found by the scan
        await _legacy_window(rig.scene, "studio-aux-oldrun-a1", "studio_aux")
        from jarvis.domain.scene import SceneActor
        await _legacy_window(rig.scene, "brain-window-1", "studio_aux", SceneActor.BRAIN)  # retired category, another id: an orphan
        await _legacy_window(rig.scene, "studio-stage-note", "note")                       # our prefix, another category: survives
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "state" / LEDGER_FILE).write_text(json.dumps({"schema": LEDGER_SCHEMA, "object_ids": [
            "studio-stage-oldrun", "studio-aux-oldrun-a1", "studio-stage-already-archived"]}), encoding="utf-8")
        await rig.service.start_service()
        remaining = {o.object_id for o in await rig.objects()}
        assert remaining == {"studio-stage-note"}
        assert not (root / "state" / LEDGER_FILE).exists()
        assert len(list((root / "state").glob(LEDGER_FILE + ".retired-*"))) == 1        # kept aside, never deleted
        assert rig.env.sink.of("core.presentation_studio.legacy_stage_reclaimed")[0][1]["count"] == 4
        assert rig.service.where() == {"phase": "idle", "running": False}
        # a run afterwards creates no Board object, and a second pass has nothing left to do
        applied(await rig.service.start(rig.start_body()))
        assert {o.object_id for o in await rig.objects()} == {"studio-stage-note"}
    finally:
        await rig.close()


async def test_a_leftover_window_appearing_later_is_archived_before_the_next_run(rig):
    await _legacy_window(rig.scene, "studio-stage-late", "studio_stage")
    applied(await rig.service.start(rig.start_body()))
    assert await rig.objects() == []


async def test_an_unreadable_old_ledger_is_an_error_row_kept_aside_and_the_scan_still_runs(tmp_path):
    root = tmp_path / "studio"
    rig = Rig(tmp_path, ledger_store=FileStageLedger(root))
    await rig.open()
    try:
        await _legacy_window(rig.scene, "studio-stage-oldrun", "studio_stage")
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "state" / LEDGER_FILE).write_text("{not json", encoding="utf-8")
        await rig.service.start_service()
        assert await rig.objects() == []
        assert rig.env.sink.of("core.presentation_studio.stage_ledger_unreadable")[0][0] == "error"
        assert len(list((root / "state").glob(LEDGER_FILE + ".corrupt-*"))) == 1
    finally:
        await rig.close()


# ------------------------------------------------------------------ role and mode

async def test_user_presenter_switches_to_presentation_and_stop_restores_the_board_derived_baseline(rig):
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
    assert rig.mode.mode is InteractionMode.PRESENTATION                      # restored to the Board type's mode
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


async def test_a_board_switch_during_the_run_stops_it_and_leaves_the_new_boards_mode(rig):
    """Slice 01b: a Board switch is the only foreign change left (no protocol, setting or HUD writer)."""

    applied(await rig.service.start(rig.start_body("user_presenter")))
    applied(await rig.run("detour", title="Annexe", prefab=AUX_BLOCK))
    await rig.mode.request("assistant", source="board_switch")              # the user opens an Assistant Board
    await asyncio.gather(*list(rig.service._tasks))
    state = rig.service.where()
    assert state["phase"] == "stopped" and state["last_run"]["reason"] == "mode_changed_by_user"
    assert rig.mode.mode is InteractionMode.ASSISTANT and rig.mode.state.source == "board_switch"   # never forced back
    assert rig.overlays() == [] and await rig.stage_object() is None


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


async def test_a_playback_service_cannot_be_built_without_a_gate_and_a_checked_run_says_checked(tmp_path):
    rig = await Rig(tmp_path).open()
    for bad in (None, object()):
        with pytest.raises(ValueError, match="art direction gate"):
            PresentationStudioPlaybackService(rig.studio, rig.edit, rig.stage, rig.mode, gate=bad, bus=rig.bus)
    with pytest.raises(TypeError):
        PresentationStudioPlaybackService(rig.studio, rig.edit, rig.stage, rig.mode)  # type: ignore[call-arg]
    state = applied(await rig.service.start(rig.start_body()))
    assert state["art_direction"] == "checked"
    assert rig.env.sink.of("core.presentation_studio.playback_art_direction_unchecked") == []
    await rig.close()


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
    assert await rig.stage_object() is None and rig.overlays() == []
    assert rig.mode.mode is InteractionMode.ASSISTANT and rig.service.where()["last_run"]["reason"] == "shutdown"
