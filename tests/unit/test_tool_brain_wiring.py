"""Câblage du Tool Brain à Core (handoff jarvis-tool-brain-ui-orchestrator, S5) : sources de réveil et drapeau."""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace

import pytest

from jarvis.core.conversation_event_emitter import ConversationEventEmitter
from jarvis.core.v2_services import CoreEventBus
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.ports.scene import SceneStoreErrorCode, SceneUnavailableError
from jarvis.runtime.tool_brain_executor import UiActionExecutor
from jarvis.runtime.tool_brain_queue import ActionRecord, ToolBrainActionQueue, Trigger, TriggerContext
from jarvis.runtime.tool_brain_runtime import ToolBrainConfig, ToolBrainMode, ToolBrainRuntime, WakeClass
from jarvis.runtime.tool_brain_wiring import (
    EVENT_WAKES, ToolBrainWakeSources, build_tool_brain, mode_from_env, wake_from_event,
)
from tests.fakes.conversation_events import make_event


def _runtime(**config) -> ToolBrainRuntime:
    return ToolBrainRuntime(None, None, lambda: None, config=ToolBrainConfig(**config))


def _seen(runtime: ToolBrainRuntime) -> dict:
    return runtime.status()["wakes_by_class"]


@pytest.mark.parametrize("raw,expected", [(None, ToolBrainMode.OFF), ("", ToolBrainMode.OFF), ("off", ToolBrainMode.OFF),
                                          ("shadow", ToolBrainMode.SHADOW), (" SHADOW ", ToolBrainMode.SHADOW),
                                          ("active", ToolBrainMode.ACTIVE), (" Active ", ToolBrainMode.ACTIVE),
                                          ("1", ToolBrainMode.OFF), ("true", ToolBrainMode.OFF),
                                          ("activate", ToolBrainMode.OFF)])
def test_the_flag_defaults_to_off_and_an_unknown_value_never_turns_paid_calls_or_execution_on(raw, expected):
    assert mode_from_env({} if raw is None else {"JARVIS_TOOL_BRAIN": raw}) is expected


def test_off_builds_nothing_and_shadow_builds_a_runtime_without_any_executor():
    core = SimpleNamespace(scene=object(), boards=object(), events=CoreEventBus(), conversation_event_emitter=object(),
                           brain=SimpleNamespace(list_ui_intents=lambda c, correlation_id=None: []))
    kwargs = dict(control_settings=lambda: {}, cwd=".", runtime_root=".")
    assert build_tool_brain(core, environ={}, **kwargs) is None
    runtime, sources = build_tool_brain(core, environ={"JARVIS_TOOL_BRAIN": "shadow", "JARVIS_TOOL_BRAIN_TICK_S": "oops"},
                                        **kwargs)
    assert runtime.mode is ToolBrainMode.SHADOW and isinstance(sources, ToolBrainWakeSources)


@pytest.mark.parametrize("event_type,wake_class,urgent", [
    (T.USER_TRANSCRIPT_ACCEPTED, "user_turn", True), (T.BRAIN_TURN_ACCEPTED, "user_turn", True),
    (T.BRAIN_UI_INTENT_PUBLISHED, "ui_intent", True), (T.MOUTH_SPEECH_STARTED, "speech", False),
    (T.MOUTH_SPEECH_COMPLETED, "speech", False), (T.MOUTH_SPEECH_INTERRUPTED, "speech", True),
    (T.MOUTH_SPEECH_SUPERSEDED, "speech", True), (T.MOUTH_FLOOR_TAKEN, "speech", True)])
def test_conversation_facts_wake_the_runtime_with_the_documented_class(event_type, wake_class, urgent):
    runtime = _runtime()
    event = make_event(event_type, "w1", conversation_id="conv-9", correlation_id="corr-9")
    assert wake_from_event(runtime, event) is True
    assert _seen(runtime) == {wake_class: 1}
    pending = runtime.status()["pending"]
    assert pending["urgent"] is urgent and pending["conversation_id"] == "conv-9" and pending["correlation_id"] == "corr-9"


def test_facts_that_do_not_change_what_the_user_sees_do_not_wake():
    runtime = _runtime()
    assert wake_from_event(runtime, make_event(T.TOOL_CALL_FINISHED, "t1")) is False
    assert wake_from_event(runtime, make_event(T.MOUTH_SPEECH_QUEUED, "q1")) is False
    assert runtime.status()["pending"] is None and EVENT_WAKES


async def test_the_real_emitter_wakes_the_runtime_for_produced_and_ingested_events():
    class Store:
        async def append_many(self, events):
            from jarvis.domain.conversation_event_store import AppendResult, AppendStatus
            return tuple(AppendResult(e.event_id, i + 1, AppendStatus.APPENDED) for i, e in enumerate(events))

    runtime, emitter = _runtime(), ConversationEventEmitter(Store(), batch_linger_s=0)
    emitter.add_listener(lambda event: wake_from_event(runtime, event))
    emitter.emit(make_event(T.BRAIN_UI_INTENT_PUBLISHED, "e1"))
    await emitter.append_now([make_event(T.MOUTH_SPEECH_INTERRUPTED, "e2")])
    assert _seen(runtime) == {"ui_intent": 1, "speech": 1}
    await emitter.stop()


class _Scene:
    def __init__(self):
        self.revision, self.down, self.waits = 3, False, 0
        self.moved = asyncio.Event()

    async def snapshot(self):
        if self.down:
            raise SceneUnavailableError(SceneStoreErrorCode.UNAVAILABLE, "down")
        return SimpleNamespace(revision=self.revision)

    async def wait_for_revision(self, after, *, timeout_s):
        self.waits += 1
        await self.moved.wait()
        self.moved.clear()
        return self.revision


async def test_board_and_scene_changes_wake_the_runtime_and_other_bus_traffic_does_not():
    runtime, bus, scene = _runtime(), CoreEventBus(), _Scene()
    sources = ToolBrainWakeSources(runtime, emitter=SimpleNamespace(add_listener=lambda cb: None), events=bus,
                                   scene=scene)
    sources.start()
    try:
        await asyncio.sleep(0.02)
        assert _seen(runtime) == {}  # the initial read is a baseline, not a change
        await bus.publish(ProtocolEnvelope(message_type="board.switched", payload={}, conversation_id="c1"))
        await bus.publish(ProtocolEnvelope(message_type="brain.reply", payload={}, conversation_id="c1"))
        scene.revision = 4
        scene.moved.set()
        await asyncio.sleep(0.05)
        assert _seen(runtime) == {"ui_change": 2}  # one Board fact, one scene revision
        assert bus.subscriber_count == 1
    finally:
        await sources.close()
    assert bus.subscriber_count == 0


async def test_an_unserved_scene_is_watched_at_a_slow_pace_not_in_a_tight_loop(monkeypatch):
    import jarvis.runtime.tool_brain_wiring as wiring

    monkeypatch.setattr(wiring, "SCENE_RETRY_S", 0.05)
    scene = _Scene()
    scene.down = True
    calls = {"n": 0}
    original = scene.snapshot

    async def counting():
        calls["n"] += 1
        return await original()

    scene.snapshot = counting
    sources = ToolBrainWakeSources(_runtime(), emitter=SimpleNamespace(add_listener=lambda cb: None),
                                   events=CoreEventBus(), scene=scene)
    sources.start()
    await asyncio.sleep(0.3)
    await sources.close()
    assert 2 <= calls["n"] <= 8  # spaced by the retry delay


async def test_sources_are_idle_when_the_mode_is_off():
    runtime = _runtime(mode=ToolBrainMode.OFF)
    bus = CoreEventBus()
    sources = ToolBrainWakeSources(runtime, emitter=SimpleNamespace(add_listener=pytest.fail), events=bus, scene=_Scene())
    sources.start()
    assert bus.subscriber_count == 0
    await sources.close()


# ------------------------------------------------------------------ S6 : mode actif, file et autorité


def _core():
    return SimpleNamespace(scene=object(), boards=object(), events=CoreEventBus(), conversation_event_emitter=object(),
                           brain=SimpleNamespace(list_ui_intents=lambda c, correlation_id=None: []))


def test_active_builds_a_queue_and_an_executor_with_exactly_the_reviewed_adapters_and_shadow_none():
    kwargs = dict(control_settings=lambda: {}, cwd=".", runtime_root=".")
    runtime, _ = build_tool_brain(_core(), environ={"JARVIS_TOOL_BRAIN": "active"}, **kwargs)
    assert runtime.mode is ToolBrainMode.ACTIVE
    assert runtime._executor is not None and runtime._action_queue is not None
    # S6 : scene_move + board_switch ; S7 : mutateurs de scène réversibles et verbes de surface ; S8 : scene_archive (gardé).
    assert set(runtime._executor._adapters) == {
        ("jarvis-display", "scene_move"), ("jarvis-workspace", "board_switch"), ("jarvis-display", "scene_update_object"),
        ("jarvis-display", "scene_update_many"), ("jarvis-display", "scene_pin"), ("jarvis-display", "scene_link"),
        ("jarvis-display", "scene_unlink"), *(("jarvis-surface", f"surface_{verb}") for verb in
                                              ("open", "focus", "scroll", "history", "zoom")), ("jarvis-display", "scene_archive")}
    assert runtime._action_queue.add(  # a tool without an adapter cannot even be queued
        ActionRecord("a1", "jarvis-display", "scene_create_object", {"kind": "window"})).code == "unsupported_tool"
    shadow, _ = build_tool_brain(_core(), environ={"JARVIS_TOOL_BRAIN": "shadow"}, **kwargs)
    assert shadow._executor is None and shadow._action_queue is None
    for raw in ("", "off", "ACTIVE!", "yes"):
        assert build_tool_brain(_core(), environ={"JARVIS_TOOL_BRAIN": raw}, **kwargs) is None


async def test_authority_facts_empty_the_queue_other_board_facts_do_not_and_events_reach_the_queue():
    queue = ToolBrainActionQueue(clock=lambda: 0.0)
    executor = UiActionExecutor(object(), object(), queue, {}, gate=lambda: True)
    runtime = ToolBrainRuntime(object(), object(), lambda: None, config=ToolBrainConfig(mode=ToolBrainMode.ACTIVE),
                               queue=queue, executor=executor)
    for action_id in ("a1", "a2"):
        queue.add(ActionRecord(action_id, "jarvis-display", "scene_move", {"object_ids": [action_id]},
                               trigger=Trigger.from_payload({"type": "event", "name": "board.created"})))
    bus = CoreEventBus()
    sources = ToolBrainWakeSources(runtime, emitter=SimpleNamespace(add_listener=lambda cb: None), events=bus,
                                   scene=_Scene())
    sources.start()
    try:
        await asyncio.sleep(0.02)
        await bus.publish(ProtocolEnvelope(message_type="board.created", payload={}, conversation_id="c1"))
        await asyncio.sleep(0.02)
        assert queue.pending_count() == 2  # a new board is no authority change
        assert queue.ready(__import__("jarvis.runtime.tool_brain_queue", fromlist=["TriggerContext"]).TriggerContext(0.0)) \
            == ["a1", "a2"]  # ... and its fact fired the event triggers
        await bus.publish(ProtocolEnvelope(message_type="board.voice_binding.changed", payload={}, conversation_id="c1"))
        await asyncio.sleep(0.02)
        assert queue.pending_count() == 0 and runtime.status()["counters"]["authority_changes"] == 1
    finally:
        await sources.close()


def test_conversation_facts_also_feed_the_event_triggers_of_the_queue():
    queue = ToolBrainActionQueue(clock=lambda: 0.0)
    runtime = ToolBrainRuntime(object(), object(), lambda: None, config=ToolBrainConfig(mode=ToolBrainMode.ACTIVE),
                               queue=queue, executor=UiActionExecutor(object(), object(), queue, {}, gate=lambda: True))
    queue.add(ActionRecord("a1", "jarvis-display", "scene_move", {"object_ids": ["x"]},
                           trigger=Trigger.from_payload({"type": "event", "name": T.MOUTH_SPEECH_STARTED.value})))
    wake_from_event(runtime, make_event(T.MOUTH_SPEECH_STARTED, "w1"))
    assert queue.ready(TriggerContext(0.0)) == ["a1"]


async def test_the_executor_gate_reads_the_runtime_mode_at_every_call(tmp_path):
    runtime, sources = build_tool_brain(_core(), environ={"JARVIS_TOOL_BRAIN": "active"}, control_settings=lambda: {},
                                        cwd=str(tmp_path), runtime_root=tmp_path)
    gate = runtime._executor._gate
    assert gate() is False  # active but nothing proven yet: Jarvis owns the screen (S8)
    sources.arbiter._status = lambda: {"running": True, "counters": {"completed": 1}, "consecutive_failures": 0,
                                        "last_outcome": "completed"}
    assert gate() is True
    runtime._config = dataclasses.replace(runtime._config, mode=ToolBrainMode.SHADOW)
    assert gate() is False  # the gate follows the runtime, it is not a captured constant


# ------------------------------------------------------------------ S8 : propriété et preuve utilisateur


def test_user_speech_is_the_only_fact_that_feeds_the_user_turn_ledger_the_guard_reads(tmp_path):
    runtime, sources = build_tool_brain(_core(), environ={"JARVIS_TOOL_BRAIN": "active"}, control_settings=lambda: {},
                                        cwd=str(tmp_path), runtime_root=tmp_path)
    guard = runtime._executor._guard
    assert guard.configured and guard._turns is sources.user_turns  # the executor's guard reads the very ledger fed here
    sources._on_event(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1", conversation_id="conv-1", correlation_id="corr-1"))
    sources._on_event(make_event(T.BRAIN_TURN_ACCEPTED, "b1", conversation_id="conv-1", correlation_id="corr-brain"))
    sources._on_event(make_event(T.MOUTH_SPEECH_STARTED, "m1", conversation_id="conv-1", correlation_id="corr-mouth"))
    assert sources.user_turns.age_s("conv-1", "corr-1") is not None
    assert sources.user_turns.age_s("conv-1", "corr-brain") is None and sources.user_turns.age_s("conv-1", "corr-mouth") is None


async def test_the_arbiter_follows_the_sources_lifecycle_and_publishes_jarvis_on_close(tmp_path):
    from jarvis.runtime.tool_brain_ownership import OWNERSHIP_DIRECT, SHUTDOWN, read_ownership

    runtime, sources = build_tool_brain(_core(), environ={"JARVIS_TOOL_BRAIN": "active"}, control_settings=lambda: {},
                                        cwd=str(tmp_path), runtime_root=tmp_path)
    assert sources.arbiter is not None and sources.arbiter.view.ownership == OWNERSHIP_DIRECT
    sources._emitter = SimpleNamespace(add_listener=lambda callback: None)
    sources._scene = _Scene()
    sources.start()
    try:
        assert read_ownership(tmp_path).mode == "active"  # published at start, before any decision
    finally:
        await sources.close()
    assert read_ownership(tmp_path).reason == SHUTDOWN
    shadow_runtime, shadow_sources = build_tool_brain(_core(), environ={"JARVIS_TOOL_BRAIN": "shadow"},
                                                      control_settings=lambda: {}, cwd=str(tmp_path / "s"),
                                                      runtime_root=tmp_path / "s")
    assert shadow_sources.arbiter.owns() is False and shadow_runtime._owner_gate() is False
