"""Runtime du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, Slice 5). Contrat : docs/tool-brain-contracts.md §13.

Déterministe : décideur factice, horloge factice (`step()` est piloté à la main). Ce qui doit tenir :

- chaque classe de réveil décide, un réveil urgent n'attend ni la fenêtre de calme ni le tick ;
- le tick de sûreté marche sans événement et ne paie un appel que si l'état perçu a changé ;
- coalescence et espacement minimal ; backoff explicite (échec, absence de décideur), sans appel pendant l'attente ;
- le mode `shadow` ne mute rien (aucun service d'écriture n'existe pour lui) ;
- les plans invalides sont refusés (ids inventés, outil hors interface, état périmé) ;
- les lectures ciblées sont bornées et contraintes ; une décision dépassée ne rend aucune action.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.scene import (
    SceneActor, SceneCommand, SceneCommandOutcome, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload,
    SceneSnapshot, apply_scene_command,
)
from jarvis.domain.workspace_board import Board, BoardStatus
from jarvis.ports.tool_brain import (
    DECIDER_FAILED, DECIDER_INVALID_OUTPUT, DECIDER_TIMEOUT, DECIDER_UNAVAILABLE, DeciderError, InspectionRequest,
    ProposedAction, ToolBrainReply, ToolBrainRequest, reply_from_payload,
)
from jarvis.ports.scene import SceneStoreErrorCode, SceneUnavailableError
from jarvis.runtime.mcp_catalog import build_catalog
from jarvis.runtime.tool_brain_runtime import (
    BACKOFF, COALESCING, COMPLETED, DECIDED, FAILED, IDLE, OFF, RATE_LIMITED, REJECTED, SUPERSEDED, UNAVAILABLE,
    UNCHANGED, WOULD_APPLY, ToolBrainConfig, ToolBrainMode, ToolBrainRuntime, WakeClass,
)

AT = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
NOTE = "brain-note-000000000001"
DISPLAY = "jarvis-display"


@pytest.fixture(scope="module")
def catalog():
    return asyncio.run(build_catalog())


# ------------------------------------------------------------------ doubles


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _note(snapshot: SceneSnapshot, object_id: str) -> SceneSnapshot:
    update = apply_scene_command(snapshot, SceneCommand(
        op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id=object_id,
        fields=SceneObjectFields(kind=SceneObjectKind.ARTIFACT, category="note", payload=ScenePayload(title=object_id))))
    assert update.outcome is SceneCommandOutcome.APPLIED
    return update.snapshot


class FakeScene:
    """Lecture seule : tout autre appel que `snapshot`/`epoch` ferait échouer l'attribut (aucune écriture offerte)."""

    def __init__(self) -> None:
        self.snapshot_value = _note(SceneSnapshot(scene_id="scene-1"), NOTE)
        self.epoch = "e1"
        self.down = False
        self.calls: list[str] = []

    async def snapshot(self):
        self.calls.append("snapshot")
        if self.down:
            raise SceneUnavailableError(SceneStoreErrorCode.UNAVAILABLE, "down")
        return self.snapshot_value

    def add_note(self, object_id: str) -> None:
        self.snapshot_value = _note(self.snapshot_value, object_id)


class FakeBoards:
    def __init__(self) -> None:
        self.active = "default"
        self.calls: list[str] = []

    async def list(self, *, include_archived=False):
        self.calls.append("list")
        return (Board(board_id="default", title="Principal", created_at=AT, updated_at=AT),
                Board(board_id="board_aaa", title="Projet A", created_at=AT, updated_at=AT),
                Board(board_id="board_old", title="Ancien", created_at=AT, updated_at=AT, status=BoardStatus.ARCHIVED))

    async def active_board_id(self):
        self.calls.append("active")
        return self.active


class FakeDecider:
    """Rend les réponses du script dans l'ordre (la dernière se répète) ; une exception est levée."""

    name = "fake"

    def __init__(self, *replies) -> None:
        self.replies = list(replies) or [ToolBrainReply()]
        self.requests: list[ToolBrainRequest] = []

    async def decide(self, request, *, timeout_s):
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, BaseException):
            raise reply
        return reply


class Rig:
    def __init__(self, catalog, decider=None, *, config=None, intents=None, available=True):
        self.clock, self.scene, self.boards = Clock(), FakeScene(), FakeBoards()
        self.decider = decider if decider is not None else FakeDecider()
        self.diagnostics = _Diagnostics()

        async def catalog_now():
            return catalog

        self.runtime = ToolBrainRuntime(
            self.scene, self.boards, (lambda: self.decider) if available else (lambda: None),
            config=config or ToolBrainConfig(), catalog=catalog_now, intents_source=intents,
            diagnostics=self.diagnostics, clock=self.clock, wall_clock=lambda: AT)


class _Diagnostics:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.rows.append((kind, level))


def _action(tool="scene_get", **arguments) -> ProposedAction:
    server = "jarvis-workspace" if tool.startswith("board_") else DISPLAY
    return ProposedAction(server, tool, arguments or {"object_ids": [NOTE]}, "because")


# ------------------------------------------------------------------ réveils


@pytest.mark.parametrize("wake_class,urgent", [
    (WakeClass.USER_TURN, None), (WakeClass.UI_INTENT, None), (WakeClass.SPEECH, True)])
async def test_urgent_wakes_decide_at_once_without_waiting_for_the_calm_window_or_the_tick(catalog, wake_class, urgent):
    rig = Rig(catalog)
    assert rig.runtime.wake(wake_class, "now", urgent=urgent) is True
    assert await rig.runtime.step() == DECIDED  # same instant: no coalesce wait, no tick
    decision = rig.runtime.decisions()[-1]
    assert decision.outcome == COMPLETED and decision.trigger["classes"] == {wake_class.value: 1}
    assert decision.trigger["urgent"] is True


@pytest.mark.parametrize("wake_class", [WakeClass.UI_CHANGE, WakeClass.SPEECH])
async def test_ordinary_wakes_wait_for_a_calm_window_then_decide(catalog, wake_class):
    rig = Rig(catalog)
    rig.runtime.wake(wake_class, "moved")
    assert await rig.runtime.step() == COALESCING
    assert rig.decider.requests == []
    rig.clock.advance(0.31)
    assert await rig.runtime.step() == DECIDED
    assert len(rig.decider.requests) == 1


async def test_a_steady_stream_of_ordinary_wakes_is_cut_by_the_maximum_delay(catalog):
    rig = Rig(catalog)
    for _ in range(10):
        rig.runtime.wake(WakeClass.UI_CHANGE, "drag")
        rig.clock.advance(0.2)  # never calm for 0.3 s
    assert await rig.runtime.step() == DECIDED  # 2.0 s since the first wake


async def test_burst_of_wakes_makes_one_decision_and_names_every_class(catalog):
    rig = Rig(catalog)
    for _ in range(4):
        rig.runtime.wake(WakeClass.UI_CHANGE, "scene_revision")
    rig.runtime.wake(WakeClass.USER_TURN, "user.transcript.accepted", conversation_id="c1", correlation_id="r1")
    assert await rig.runtime.step() == DECIDED
    assert await rig.runtime.step() == IDLE
    (decision,) = rig.runtime.decisions()
    assert decision.trigger["wakes"] == 5 and decision.trigger["classes"] == {"ui_change": 4, "user_turn": 1}
    assert decision.trigger["correlation_id"] == "r1"
    assert rig.runtime.status()["counters"]["wakes_coalesced"] == 4


async def test_decisions_are_spaced_by_the_minimum_interval_even_for_urgent_wakes(catalog):
    rig = Rig(catalog)
    rig.runtime.wake(WakeClass.USER_TURN)
    assert await rig.runtime.step() == DECIDED
    rig.clock.advance(0.2)
    rig.runtime.wake(WakeClass.USER_TURN)
    assert await rig.runtime.step() == RATE_LIMITED
    assert len(rig.decider.requests) == 1
    rig.clock.advance(0.9)
    assert await rig.runtime.step() == DECIDED


# ------------------------------------------------------------------ tick de sûreté


async def test_tick_decides_when_nothing_else_happened_and_skips_when_the_world_is_unchanged(catalog):
    rig = Rig(catalog)
    rig.runtime.wake(WakeClass.TICK, "safety_tick")
    assert await rig.runtime.step() == COALESCING  # a tick is never urgent
    rig.clock.advance(0.5)
    assert await rig.runtime.step() == DECIDED
    rig.clock.advance(5)
    rig.runtime.wake(WakeClass.TICK, "safety_tick")
    rig.clock.advance(0.5)
    assert await rig.runtime.step() == UNCHANGED  # same perception: no paid call
    assert len(rig.decider.requests) == 1 and rig.runtime.status()["counters"]["ticks_unchanged"] == 1
    rig.scene.add_note("brain-note-000000000002")  # a missed wake: only the tick can catch it
    rig.runtime.wake(WakeClass.TICK, "safety_tick")
    rig.clock.advance(0.5)
    assert await rig.runtime.step() == DECIDED
    assert len(rig.decider.requests) == 2


async def test_the_loop_ticks_by_itself_with_no_event_at_all(catalog):
    config = ToolBrainConfig(tick_interval_s=0.05, coalesce_s=0.0, min_interval_s=0.0)
    rig = Rig(catalog, config=config)
    rig.runtime._clock = __import__("time").monotonic  # the loop waits in real time
    rig.runtime.start()
    try:
        for _ in range(100):
            if rig.decider.requests:
                break
            await asyncio.sleep(0.02)
    finally:
        await rig.runtime.close()
    assert rig.decider.requests, "the periodic safety tick never woke the Tool Brain"
    assert rig.runtime.decisions()[0].trigger["classes"] == {"tick": 1}


async def test_the_loop_wakes_on_an_event_long_before_the_tick(catalog):
    config = ToolBrainConfig(tick_interval_s=3600.0, coalesce_s=0.0, min_interval_s=0.0)
    rig = Rig(catalog, config=config)
    rig.runtime._clock = __import__("time").monotonic
    rig.runtime.start()
    try:
        await asyncio.sleep(0.02)
        rig.runtime.wake(WakeClass.USER_TURN, "user.transcript.accepted")
        for _ in range(100):
            if rig.decider.requests:
                break
            await asyncio.sleep(0.02)
    finally:
        await rig.runtime.close()
    assert len(rig.decider.requests) == 1


# ------------------------------------------------------------------ pannes et backoff


async def test_a_failing_decider_backs_off_with_growing_delays_and_is_not_called_while_waiting(catalog):
    boom = DeciderError(DECIDER_FAILED, "provider said no")
    rig = Rig(catalog, FakeDecider(boom))
    delays = []
    for _ in range(5):
        rig.runtime.wake(WakeClass.USER_TURN, "turn")
        assert await rig.runtime.step() == DECIDED
        delays.append(rig.runtime.decisions()[-1].backoff_s)
        calls = len(rig.decider.requests)
        rig.clock.advance(delays[-1] - 1)
        rig.runtime.wake(WakeClass.USER_TURN, "again")
        assert await rig.runtime.step() == BACKOFF  # explicit wait, no thrash
        assert len(rig.decider.requests) == calls
        rig.clock.advance(1.01)
    assert delays == [5.0, 30.0, 120.0, 600.0, 600.0]
    last = rig.runtime.decisions()[-1]
    assert last.outcome == FAILED and last.error_code == DECIDER_FAILED and "provider said no" in last.error_detail


async def test_a_good_decision_resets_the_backoff_and_pending_wakes_survive_it(catalog):
    rig = Rig(catalog, FakeDecider(DeciderError(DECIDER_TIMEOUT, "slow"), ToolBrainReply()))
    rig.runtime.wake(WakeClass.USER_TURN, "turn", conversation_id="c1")
    await rig.runtime.step()
    assert rig.runtime.status()["consecutive_failures"] == 1
    rig.runtime.wake(WakeClass.UI_INTENT, "intent")
    rig.clock.advance(5.1)
    assert await rig.runtime.step() == DECIDED
    ok = rig.runtime.decisions()[-1]
    assert ok.outcome == COMPLETED
    assert ok.trigger["classes"] == {"ui_intent": 1, "user_turn": 1}  # the failed round's wake was not lost
    assert rig.runtime.status()["consecutive_failures"] == 0


async def test_without_a_configured_decider_the_runtime_is_unavailable_with_a_long_backoff_and_ui_untouched(catalog):
    rig = Rig(catalog, available=False)
    rig.runtime.wake(WakeClass.USER_TURN, "turn")
    assert await rig.runtime.step() == DECIDED
    decision = rig.runtime.decisions()[-1]
    assert (decision.outcome, decision.error_code, decision.backoff_s) == (UNAVAILABLE, DECIDER_UNAVAILABLE, 60.0)
    rig.runtime.wake(WakeClass.USER_TURN, "turn")
    assert await rig.runtime.step() == BACKOFF
    assert rig.scene.calls == []  # not even a state read: nothing to decide with
    rig.clock.advance(61)
    await rig.runtime.step()
    assert rig.runtime.decisions()[-1].backoff_s == 300.0
    assert rig.runtime.status()["counters"]["unavailable"] == 2


async def test_a_decider_that_never_answers_times_out_into_a_failure(catalog):
    class Hang:
        name = "hang"

        async def decide(self, request, *, timeout_s):
            await asyncio.sleep(60)

    rig = Rig(catalog, Hang(), config=ToolBrainConfig(decision_timeout_s=0.05))
    rig.runtime.wake(WakeClass.USER_TURN)
    await rig.runtime.step()
    decision = rig.runtime.decisions()[-1]
    assert (decision.outcome, decision.error_code) == (FAILED, DECIDER_TIMEOUT)


async def test_an_unreadable_state_is_a_failure_not_a_guess(catalog):
    rig = Rig(catalog)

    async def broken():
        raise OSError("db locked")

    rig.boards.list = lambda **_: broken()
    rig.runtime.wake(WakeClass.USER_TURN)
    await rig.runtime.step()
    decision = rig.runtime.decisions()[-1]
    assert decision.error_code == "tool_brain_state_unreadable" and rig.decider.requests == []


# ------------------------------------------------------------------ shadow : rien n'est exécuté


async def test_shadow_mode_records_what_it_would_do_and_mutates_nothing(catalog):
    plan = ToolBrainReply(actions=(_action(), _action("board_switch", board_id="board_aaa")), rationale="show it")
    rig = Rig(catalog, FakeDecider(plan))
    before = rig.scene.snapshot_value
    rig.runtime.wake(WakeClass.USER_TURN)
    await rig.runtime.step()
    decision = rig.runtime.decisions()[-1]
    assert [(a.action.tool, a.verdict) for a in decision.actions] == [("scene_get", WOULD_APPLY),
                                                                      ("board_switch", WOULD_APPLY)]
    assert rig.scene.snapshot_value is before and rig.boards.active == "default"
    assert set(rig.scene.calls) <= {"snapshot"} and set(rig.boards.calls) <= {"list", "active"}
    for forbidden in ("execute", "apply", "enqueue", "submit"):
        assert not hasattr(rig.runtime, forbidden)  # no executor exists before Slice 6
    assert rig.runtime.mode is ToolBrainMode.SHADOW


def test_only_off_and_shadow_modes_exist():
    assert {mode.value for mode in ToolBrainMode} == {"off", "shadow"}
    with pytest.raises(ValueError):
        ToolBrainRuntime(None, None, lambda: None, config=ToolBrainConfig(mode="active"))  # type: ignore[arg-type]


async def test_off_mode_ignores_wakes_and_starts_nothing(catalog):
    rig = Rig(catalog, config=ToolBrainConfig(mode=ToolBrainMode.OFF))
    assert rig.runtime.wake(WakeClass.USER_TURN) is False
    assert await rig.runtime.step() == OFF
    rig.runtime.start()
    assert rig.runtime.status()["running"] is False and rig.decider.requests == []


# ------------------------------------------------------------------ plans invalides


async def test_invalid_plans_are_rejected_with_the_owner_codes_and_never_marked_applicable(catalog):
    plan = ToolBrainReply(actions=(
        _action(object_ids=["brain-note-INVENTED000000"]),                 # invented id
        ProposedAction(DISPLAY, "scene_get", {"object_ids": [NOTE, "brain-note-INVENTED000000"]}),  # one bad in a list
        ProposedAction(DISPLAY, "memory_write", {"text": "x"}),            # not a UI tool
        ProposedAction(DISPLAY, "no_such_tool", {}),                       # unknown
        _action("board_switch", board_id="board_old"),                     # archived Board
        _action(),                                                         # the only valid one
    ))
    rig = Rig(catalog, FakeDecider(plan))
    rig.runtime.wake(WakeClass.USER_TURN)
    await rig.runtime.step()
    verdicts = rig.runtime.decisions()[-1].actions
    assert [v.verdict for v in verdicts] == [REJECTED] * 5 + [WOULD_APPLY]
    codes = [[r["code"] for r in v.refusals] for v in verdicts]
    assert codes[0] == ["unknown_object"] and codes[1] == ["unknown_object"]
    assert codes[2] == ["not_ui_tool"] or codes[2] == ["unknown_tool"]
    assert codes[3] == ["unknown_tool"] and codes[4] == ["board_archived"]
    assert rig.runtime.status()["counters"]["actions_rejected"] == 5


async def test_validation_uses_the_fresh_state_not_the_one_the_decider_saw(catalog):
    class Slow:
        name = "slow"

        def __init__(self, scene):
            self.scene = scene

        async def decide(self, request, *, timeout_s):
            self.scene.epoch = "e2"  # the world changed while the model was thinking
            return ToolBrainReply(actions=(_action(),))

    rig = Rig(catalog)
    rig.decider = Slow(rig.scene)
    rig.runtime.wake(WakeClass.USER_TURN)
    await rig.runtime.step()
    (verdict,) = rig.runtime.decisions()[-1].actions
    assert verdict.verdict == REJECTED and verdict.refusals[0]["code"] == "stale_scene_epoch"


async def test_a_non_plan_from_the_decider_is_a_failure():
    class Bad:
        name = "bad"

        async def decide(self, request, *, timeout_s):
            return {"actions": []}

    rig = Rig({"tools": []}, Bad())
    rig.runtime.wake(WakeClass.USER_TURN)
    await rig.runtime.step()
    assert rig.runtime.decisions()[-1].error_code == DECIDER_FAILED


@pytest.mark.parametrize("payload", [
    [], {"unknown": 1}, {"actions": "x"}, {"actions": [{"server": "s"}]},
    {"actions": [{"server": "s", "tool": "t", "arguments": [1]}]},
    {"actions": [{"server": "s", "tool": "t", "arguments": {}, "code": "rm -rf"}]},
    {"actions": [{"server": "s", "tool": "t", "arguments": {}}] * 7},
    {"inspections": [{"read": "list_related", "id": 3}]},
    {"inspections": [{"read": "get_queue_state"}] * 4},
    {"actions": [{"server": "s", "tool": "t", "arguments": {"x": "y" * 3000}}]},
])
def test_the_plan_codec_refuses_anything_that_is_not_a_bounded_structured_plan(payload):
    with pytest.raises(DeciderError) as caught:
        reply_from_payload(payload)
    assert caught.value.code == DECIDER_INVALID_OUTPUT


def test_the_plan_codec_keeps_a_valid_plan_bounded():
    reply = reply_from_payload({"inspections": [{"read": "get_queue_state"}], "rationale": "r " * 400,
                                "actions": [{"server": DISPLAY, "tool": "scene_get", "arguments": {"object_ids": ["a"]},
                                             "reason": "x" * 999, "intent_id": "uiintent-1"}]}, model="m")
    assert reply.inspections == (InspectionRequest("get_queue_state", None),)
    assert len(reply.rationale) <= 300 and len(reply.actions[0].reason) <= 200 and reply.model == "m"


# ------------------------------------------------------------------ lectures ciblées bornées


async def test_inspection_rounds_are_bounded_and_every_read_is_choice_constrained(catalog):
    nosy = ToolBrainReply(inspections=(InspectionRequest("get_information_on", NOTE),
                                       InspectionRequest("get_information_on", "brain-note-INVENTED000000"),
                                       InspectionRequest("delete_everything", NOTE)))
    rig = Rig(catalog, FakeDecider(nosy), config=ToolBrainConfig(max_inspection_rounds=2))
    rig.runtime.wake(WakeClass.USER_TURN)
    await rig.runtime.step()
    decision = rig.runtime.decisions()[-1]
    assert len(rig.decider.requests) == 3 and decision.rounds == 2  # round 0, 1 and the forced last one
    assert [r.inspections_left for r in rig.decider.requests] == [2, 1, 0]
    results = rig.decider.requests[-1].inspections
    ok = [r for r in results if r["ok"]]
    assert ok and all(r["kind"] == "object" for r in ok)
    refusals = {(r.get("code")) for r in results if not r["ok"]}
    assert refusals == {"unknown_id", "unknown_read"}  # invented ids never reach a state read
    assert decision.inspections[-1]["code"] == "budget_exhausted"
    assert decision.outcome == COMPLETED and decision.actions == ()


async def test_a_read_that_needs_an_id_without_one_is_refused(catalog):
    rig = Rig(catalog, FakeDecider(ToolBrainReply(inspections=(InspectionRequest("list_related", None),
                                                               InspectionRequest("get_queue_state", None)))),
              config=ToolBrainConfig(max_inspection_rounds=1))
    rig.runtime.wake(WakeClass.USER_TURN)
    await rig.runtime.step()
    codes = [(r["ok"], r.get("code")) for r in rig.decider.requests[-1].inspections]
    assert codes == [(False, "missing_id"), (True, None)]  # the queue read is a placeholder until Slice 6


async def test_inspection_results_reach_the_decider_which_then_concludes(catalog):
    looking = ToolBrainReply(inspections=(InspectionRequest("get_available_actions", NOTE),))
    done = ToolBrainReply(actions=(_action(),), rationale="seen")
    rig = Rig(catalog, FakeDecider(looking, done))
    rig.runtime.wake(WakeClass.USER_TURN)
    await rig.runtime.step()
    first, second = rig.decider.requests
    assert first.inspections == () and first.round == 0
    assert second.round == 1 and second.inspections[0]["kind"] == "actions"
    assert rig.runtime.decisions()[-1].actions[0].verdict == WOULD_APPLY


async def test_the_decider_receives_the_perception_the_manifest_and_the_checked_intents(catalog):
    intents = [{"intent_id": "ui1", "kind": "reveal", "refs": [{"kind": "object", "id": NOTE},
                                                               {"kind": "object", "id": "brain-note-GONE000000000"}],
                "subject": "", "timing": "now"}]
    seen = []
    rig = Rig(catalog, intents=lambda conversation, correlation: seen.append((conversation, correlation)) or intents)
    rig.runtime.wake(WakeClass.UI_INTENT, "intent", conversation_id="c1", correlation_id="r1")
    await rig.runtime.step()
    (request,) = rig.decider.requests
    assert seen == [("c1", "r1")]
    assert request.perception["schema"] == "tool_brain.perception/1" and request.manifest["schema"] == "tool_brain.manifest/1"
    assert request.intents[0]["ref_refusals"] == ["unknown_object"]  # checked now, a hint is never a right
    decision = rig.runtime.decisions()[-1]
    assert decision.perception_digest and decision.manifest_tools >= 17


# ------------------------------------------------------------------ annulation


async def test_an_urgent_wake_cancels_the_in_flight_decision_and_no_stale_action_survives(catalog):
    started, cancelled = asyncio.Event(), []

    class Blocking:
        name = "blocking"
        calls = 0

        async def decide(self, request, *, timeout_s):
            Blocking.calls += 1
            if Blocking.calls > 1:
                return ToolBrainReply(actions=(_action(),))
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

    rig = Rig(catalog, Blocking())
    rig.runtime.wake(WakeClass.UI_CHANGE, "drag")
    rig.clock.advance(1)
    step = asyncio.create_task(rig.runtime.step())
    await asyncio.wait_for(started.wait(), 1)
    rig.runtime.wake(WakeClass.USER_TURN, "user.transcript.accepted")  # newer, higher priority
    assert await asyncio.wait_for(step, 1) == DECIDED
    stale = rig.runtime.decisions()[-1]
    assert cancelled == [True] and stale.outcome == SUPERSEDED and stale.actions == ()
    assert rig.runtime.status()["counters"]["superseded"] == 1
    # a superseded decision does not count towards the minimum interval: the newer wake goes straight away
    assert await rig.runtime.step() == DECIDED
    fresh = rig.runtime.decisions()[-1]
    assert fresh.outcome == COMPLETED and fresh.actions[0].verdict == WOULD_APPLY
    assert fresh.trigger["classes"] == {"user_turn": 1}


# ------------------------------------------------------------------ historique et métriques


async def test_history_is_bounded_and_readable_for_later_slices(catalog):
    rig = Rig(catalog, config=ToolBrainConfig(history_size=3, min_interval_s=0.0))
    for _ in range(5):
        rig.runtime.wake(WakeClass.USER_TURN)
        await rig.runtime.step()
    kept = rig.runtime.decisions(10)
    assert [d.seq for d in kept] == [3, 4, 5] and rig.runtime.decisions(2)[0].seq == 4
    assert rig.runtime.get_decision(kept[0].decision_id) is kept[0] and rig.runtime.get_decision("tbd-000001") is None
    wire = kept[-1].to_dict()
    assert wire["schema"] == "tool_brain.decision/1" and wire["outcome"] == COMPLETED and wire["trigger"]["wakes"] == 1
    assert rig.runtime.decisions(0) == ()


async def test_status_exposes_latency_wake_and_error_metrics(catalog):
    rig = Rig(catalog)
    rig.runtime.wake(WakeClass.USER_TURN)
    await rig.runtime.step()
    status = rig.runtime.status()
    assert status["wakes_by_class"] == {"user_turn": 1} and status["counters"]["decisions"] == 1
    assert status["latency_ms"]["samples"] == 1 and status["backoff_remaining_s"] == 0
    assert ("tool_brain.decision", "info") in rig.diagnostics.rows


async def test_a_raising_diagnostic_sink_never_breaks_a_decision(catalog):
    rig = Rig(catalog)

    class Raising:
        def emit(self, *a, **k):
            raise OSError("disk full")

    rig.runtime._diagnostics = Raising()
    rig.runtime.wake(WakeClass.USER_TURN)
    assert await rig.runtime.step() == DECIDED


def test_the_event_loop_wake_helper_covers_the_documented_event_types():
    from jarvis.runtime.tool_brain_wiring import EVENT_WAKES

    assert {T.USER_TRANSCRIPT_ACCEPTED, T.BRAIN_UI_INTENT_PUBLISHED, T.MOUTH_SPEECH_INTERRUPTED} <= set(EVENT_WAKES)


async def test_the_rule_decider_runs_end_to_end_through_the_runtime(catalog):
    from jarvis.runtime.tool_brain_decider import RuleToolBrainDecider

    intents = [{"intent_id": "ui1", "kind": "reveal", "refs": [{"kind": "object", "id": NOTE},
                                                               {"kind": "board", "id": "board_aaa"}],
                "subject": "", "timing": "now"}]
    rig = Rig(catalog, RuleToolBrainDecider(), intents=lambda conversation, correlation: intents)
    rig.runtime.wake(WakeClass.UI_INTENT, "intent", conversation_id="c1", correlation_id="r1")
    await rig.runtime.step()
    decision = rig.runtime.decisions()[-1]
    assert decision.rounds == 1 and decision.inspections[0]["read"] == "get_information_on" and decision.inspections[0]["ok"]
    assert [(a.action.tool, a.verdict, a.action.intent_id) for a in decision.actions] == [
        ("scene_get", WOULD_APPLY, "ui1"), ("board_switch", WOULD_APPLY, "ui1")]
