"""The Jarvis presenter and locked sequences over the real wire (jarvis-interactive-presentation-studio, Slice 14).

Real `JarvisCoreApplication` (its real `BrainOrchestrator`, emitter, playback service and presenter, on the real clock) behind the real
`LocalProtocolServer`, with the real Control Center relay in front. What is proven here that the in-process tests cannot: the
presenter is wired in Core and runs on its own loop; a run started from the page reaches `jarvis_presenter` with the mode switched
and the relay's forced `user` actor; a speech stack that cannot take the line (no current intention in Core: the state right after a
Core restart) is a visible pause, not a hang; a locked sequence is executed on the real clock and returns the timeline to the user;
`skip_sequence` stays the user's escape; no script text is in any answer. NOT proven: audible output.
"""

from __future__ import annotations

import asyncio
import json

from tests.fakes.presentation_studio_presenter import SECRET
from tests.unit.test_presentation_studio_playback_routes import (
    AUTH, CONTROLS, PLAYBACK, PLAYBACK_ROUTE, S1, S2, S3, I1, I2, I3, post, scene, start_body,
)
from tests.unit.test_presentation_studio_routes import Core, variant_body
from tests.unit.test_presentation_studio_score_service import Sink

JARVIS_TEXT = f"Bonjour {SECRET} premiere ligne."


def jarvis_score(revision: int) -> dict:
    return {"expected_variant_revision": revision, "start_item_id": I1, "items": [
        {"item_id": I1, "scene_id": S1, "presenter": "jarvis", "kind": "speech", "text": JARVIS_TEXT, "next_item_id": I2},
        {"item_id": I2, "scene_id": S2, "presenter": "none", "kind": "silence", "target_duration_ms": 1000, "next_item_id": I3},
        {"item_id": I3, "scene_id": S3, "presenter": "user", "kind": "speech", "note": "Fin"}],
        "cues": [], "sequences": [], "recovery_points": []}


def locked_score(revision: int, *, duration_ms: int = 800) -> dict:
    return {"expected_variant_revision": revision, "start_item_id": I1, "items": [
        {"item_id": I1, "scene_id": S1, "presenter": "user", "kind": "speech", "note": "Intro", "next_item_id": I2},
        {"item_id": I2, "scene_id": S2, "presenter": "user", "kind": "speech", "note": "Regardez",
         "visual": [{"kind": "sequence", "sequence_id": "demo"}], "timing": "locked", "interruption": "at_boundary",
         "target_duration_ms": duration_ms, "next_item_id": I3},
        {"item_id": I3, "scene_id": S3, "presenter": "none", "kind": "silence"}],
        "cues": [], "sequences": [{"sequence_id": "demo", "label": "Demo", "duration_ms": duration_ms, "on_interrupt": "pause_resume",
                                   "steps": [{"step_id": "a", "offset_ms": 0, "visual": [
                                       {"kind": "control_set", "scene_id": S2, "control_id": "body", "value": "Etape A"}]},
                                             {"step_id": "b", "offset_ms": duration_ms // 2, "visual": [
                                                 {"kind": "control_set", "scene_id": S2, "control_id": "body", "value": "Etape B"}]}]}],
        "recovery_points": []}


async def presentation(core: Core, make_score) -> str:
    _, created = await core.call("POST", "", json={"title": "Lecture"})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    vid = variant["variant_id"]
    status, saved = await core.call("PUT", f"/{pid}/variants/{vid}", json=variant_body(
        variant, scenes=[scene(S1, "Un"), scene(S2, "Deux"), scene(S3, "Trois")]))
    assert status == 200, saved
    status, made = await core.call("POST", f"/{pid}/variants/{vid}/score", json=make_score(saved["revision"]))
    assert status == 201, made
    status, art = await core.call("POST", f"/{pid}/variants/{vid}/art-direction/fallback",
                                  json={"expected_variant_revision": saved["revision"] + 1})
    assert status == 201, art
    return pid


async def until(core: Core, predicate, *, timeout: float = 5.0) -> dict:
    """Poll the relayed bounded state until `predicate(state)`; the real presenter loop runs on the real clock."""

    deadline = asyncio.get_running_loop().time() + timeout
    state: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        _, body, _ = await core.stack.call("GET", PLAYBACK_ROUTE)
        state = body["state"]
        if predicate(state):
            return state
        await asyncio.sleep(0.05)
    raise AssertionError(f"state never reached: {json.dumps(state)[:600]}")


async def stage_body(core: Core, stage_id: str, expected: str, *, timeout: float = 3.0) -> str:
    """The stage follows the state a moment later (the state moves under the service lock, the scene write ends it)."""

    deadline = asyncio.get_running_loop().time() + timeout
    body = None
    while asyncio.get_running_loop().time() < deadline:
        snapshot = await core.stack.core.scene.snapshot()
        body = snapshot.get_object(stage_id).payload.prefab.data["body"]
        if body == expected:
            break
        await asyncio.sleep(0.03)
    return body


async def test_the_presenter_is_wired_in_core_and_a_jarvis_run_started_from_the_page_switches_the_mode_and_restores_it(tmp_path):
    async with Core(tmp_path) as core:
        app = core.stack.core
        assert app.presentation_studio_presenter is not None
        pid = await presentation(core, jarvis_score)
        await app.interaction_mode.request("presentation", source="control_center")        # what the user had
        status, started, _ = await core.stack.call(
            "POST", f"{PLAYBACK_ROUTE}/start", json={**start_body(pid, role="jarvis_presenter"), "actor": "brain"})
        assert status == 200 and started["state"]["role"] == "jarvis_presenter" and started["state"]["jarvis_speaks"] is True
        assert started["state"]["mode"] == "assistant"                                     # the relay forced `user`: an explicit request
        assert app.interaction_mode.mode.value == "assistant" and app.interaction_mode.state.source == "presentation_studio_run"
        await core.stack.call("POST", f"{PLAYBACK_ROUTE}/stop", json={})
        assert app.interaction_mode.mode.value == "presentation"                           # restored to the user's own mode


async def test_a_speech_stack_that_cannot_take_the_line_is_a_visible_pause_over_the_wire_never_a_hang(tmp_path):
    """A fresh Core has no current intention: `announce_notice` publishes nothing (`no_current_source`). The run says so."""

    async with Core(tmp_path) as core:
        sink = Sink()
        core.stack.core.presentation_studio_presenter._diagnostics = sink      # Core's own sink is null in this stack
        pid = await presentation(core, jarvis_score)
        await core.stack.call("POST", f"{PLAYBACK_ROUTE}/start", json=start_body(pid, role="jarvis_presenter"))
        state = await until(core, lambda s: s["phase"] == "paused")
        assert "announce_refused" in state["problems"] and state["presenter"]["problem"] == "announce_refused"
        assert state["presenter"]["lines"] == 1 and state["speaking"] is None
        wire = json.dumps(state, ensure_ascii=False)
        assert SECRET not in wire and "Bonjour" not in wire and len(wire.encode()) < 3072
        assert sink.of("core.presentation_studio.presenter_announce_refused"), "the refusal is a diagnostic row of Core"
        # the user's explicit continue is the retry (it fails the same way until Core has an intention), still visible
        status, again, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/resume", json={})
        assert status == 200
        state = await until(core, lambda s: s["phase"] == "paused" and s["presenter"]["lines"] == 2)
        status, stopped, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/stop", json={})
        assert status == 200 and stopped["state"]["last_run"]["reason"] == "user"
        assert core.stack.core.interaction_mode.mode.value == "assistant"


async def test_a_locked_sequence_runs_on_the_real_clock_and_gives_the_timeline_back(tmp_path):
    async with Core(tmp_path) as core:
        pid = await presentation(core, locked_score)
        await core.stack.call("POST", f"{PLAYBACK_ROUTE}/start", json=start_body(pid))
        status, moved, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/next", json={})
        assert status == 200 and moved["state"]["owner"] == "sequence"
        stage_id = moved["state"]["stage_object_id"]
        await until(core, lambda s: s["sequence"] is not None and s["sequence"]["step"] >= 1)
        assert await stage_body(core, stage_id, "Etape A") == "Etape A"                         # step a's action, on the stage
        done = await until(core, lambda s: s["owner"] == "user")
        assert done["sequence"] is None and done["item"]["timing"] == "locked"
        assert await stage_body(core, stage_id, "Etape B") == "Etape B"                         # step b ran at its offset
        status, nxt, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/next", json={})        # no longer wedged
        assert status == 200 and nxt["state"]["scene"]["title"] == "Trois"
        await core.stack.call("POST", f"{PLAYBACK_ROUTE}/stop", json={})


async def test_skip_sequence_stays_the_users_escape_while_the_executor_runs(tmp_path):
    async with Core(tmp_path) as core:
        pid = await presentation(core, lambda revision: locked_score(revision, duration_ms=30_000))
        await core.stack.call("POST", f"{PLAYBACK_ROUTE}/start", json=start_body(pid))
        await core.stack.call("POST", f"{PLAYBACK_ROUTE}/next", json={})
        await until(core, lambda s: s["sequence"] is not None and s["sequence"]["step"] >= 1)
        status, refused = await post(core, f"{PLAYBACK}/skip_sequence", {"actor": "brain"})
        assert status == 400 and "user action" in refused["error"]["message"]                 # the brain cannot send it
        status, nxt, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/next", json={})
        assert status == 409 and nxt["reason"] == "locked_sequence_active"                     # navigation is refused meanwhile
        status, skipped, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/skip_sequence", json={"actor": "brain"})
        assert status == 200 and skipped["state"]["scene"]["title"] == "Trois" and skipped["state"]["owner"] == "user"
        await core.stack.call("POST", f"{PLAYBACK_ROUTE}/stop", json={})
