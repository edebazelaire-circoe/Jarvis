"""Intake public du Tool Brain pour le mode présentation (handoff jarvis-tool-brain-ui-orchestrator, S10). Contrat : §18.6.

Preuve de **suffisance** : un adaptateur factice `ToolBrainDisplaySink` (celui que la Slice 08 de
`jarvis-presentation-interaction-mode` écrira) implémente le vrai port `PresentationDisplaySink` avec **deux** appels,
`ToolBrainIntake.submit` et `ToolBrainIntake.withdraw`, sur la vraie pile runtime -> file -> exécuteur -> propriétaire.
Ce qui doit tenir :

- l'intention de sortie devient la MÊME intention typée que Jarvis publie, le Tool Brain reste maître des outils ;
- `publish` rend un reçu typé, jamais une exception attendue, et dit si le Tool Brain agira (`will_execute`) pour que le
  puits garde son repli quand ce n'est pas le cas (un seul exécuteur) ;
- `withdraw_speculative` annule en file ce qui n'est pas encore à l'écran, rend le compte, ne défait rien de ce qui l'est ;
- une décision en vol ne peut pas remettre en file une intention retirée ; le décideur ne la voit plus.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jarvis.core.presentation_display import DisplayReceipt, PresentationDisplaySink
from jarvis.core.ui_intents import UiIntentRegistry
from jarvis.domain.output_disposition import OutputDisposition
from jarvis.domain.presentation_intent import (
    DisplayIntent, DisplaySemantic, IntentUrgency, PresentationOutputIntent,
)
from jarvis.domain.presentation_policy import PresentationSituation
from jarvis.domain.ui_intent import UiIntentDraft, UiIntentKind, UiIntentRef, UiIntentRefKind, UiIntentTiming
from jarvis.runtime.mcp_catalog import build_catalog
from jarvis.runtime.tool_brain_intake import INVALID_INTENT, TOOL_BRAIN_OFF, ToolBrainIntake
from jarvis.runtime.tool_brain_runtime import ToolBrainMode
from tests.replay import tool_brain_replay as replay

A, B = "brain-note-a", "brain-note-b"
CONVERSATION, CORRELATION = "conv-p", "corr-p"
AT = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


class ToolBrainDisplaySink:
    """What Slice 08 writes: `PresentationDisplaySink` over the intake, nothing else (kept here as the conformance witness)."""

    __slots__ = ("_intake", "_conversation_id")

    def __init__(self, intake: ToolBrainIntake, conversation_id: str) -> None:
        self._intake, self._conversation_id = intake, conversation_id

    async def publish(self, intent: PresentationOutputIntent) -> DisplayReceipt:
        display = intent.display
        if display is None:
            return DisplayReceipt(False, "display_nothing_to_show")
        kind = {DisplaySemantic.REVEAL_PREPARED: UiIntentKind.REVEAL,
                DisplaySemantic.SHOW_ATTENTION: UiIntentKind.ATTENTION}[display.semantic]
        draft = UiIntentDraft(kind, tuple(UiIntentRef(UiIntentRefKind.OBJECT, ref) for ref in display.resource_refs),
                              timing=UiIntentTiming.NOW)
        receipt = self._intake.submit(draft, conversation_id=self._conversation_id,
                                      correlation_id=intent.correlation_id or CORRELATION,
                                      urgent=intent.urgency is IntentUrgency.IMMEDIATE)
        if not receipt.accepted:
            return DisplayReceipt(False, f"tool_brain_{receipt.code}")
        if not receipt.will_execute:  # the Tool Brain will not act: the composition keeps its direct sink
            return DisplayReceipt(False, "tool_brain_not_owner", detail=receipt.code)
        return DisplayReceipt(True, "tool_brain_intent_accepted", detail=receipt.intent_id or "")

    def withdraw_speculative(self, reason: str, *, correlation_id: str = "") -> int:
        return self._intake.withdraw(reason, correlation_id=correlation_id)


def output_intent(*refs: str, urgency=IntentUrgency.SOON, correlation=CORRELATION) -> PresentationOutputIntent:
    return PresentationOutputIntent(
        situation=PresentationSituation.VISUAL_COMMAND, disposition=OutputDisposition.VISUAL_ONLY,
        display=DisplayIntent(DisplaySemantic.REVEAL_PREPARED, tuple(refs)), urgency=urgency,
        reason="addressed_reveal", correlation_id=correlation)


def show(object_id: str, *, trigger=None, intent_id=None) -> dict:
    action = {"server": "jarvis-display", "tool": "scene_update_object", "reason": "reveal what the presenter asked",
              "arguments": {"object_id": object_id, "visibility": "visible"}}
    if trigger:
        action["trigger"] = trigger
    if intent_id:
        action["intent_id"] = intent_id
    return action


@pytest.fixture(scope="module")
def catalog():
    return asyncio.run(build_catalog())


class Stack:
    def __init__(self, rig, registry, intake, sink) -> None:
        self.rig, self.registry, self.intake, self.sink = rig, registry, intake, sink

    async def hidden(self) -> list[str]:
        return sorted(o.object_id for o in (await self.rig.scene.snapshot()).objects if o.visibility.value == "hidden")

    async def decide(self):
        assert await replay._settle_decision(self.rig) == replay.DECIDED
        return self.rig.runtime.decisions()[-1]


async def make_stack(catalog, replies, *, mode=ToolBrainMode.ACTIVE):
    scenario = {"id": "intake", "scene": {"objects": [
        {"id": A, "title": "Marge", "x": 0, "hidden": True}, {"id": B, "title": "Ventes", "x": 50, "hidden": True}]},
        "decider": {"kind": "scripted", "replies": replies}, "steps": []}
    registry = UiIntentRegistry(clock=lambda: AT)
    tmp = tempfile.TemporaryDirectory(prefix="tb-intake-")
    rig = await replay.build_rig(scenario, Path(tmp.name), catalog, replay.scripted_factory,
                                 intents_source=lambda c, k: [i.to_payload() for i in registry.list(c, correlation_id=k)])
    if mode is not ToolBrainMode.ACTIVE:
        rig.runtime._config = type(rig.runtime._config)(mode=mode)  # noqa: SLF001 - the mode seam, as test_tool_brain_active does
    intake = ToolBrainIntake(rig.runtime, registry)
    stack = Stack(rig, registry, intake, ToolBrainDisplaySink(intake, CONVERSATION))
    stack._tmp = tmp  # type: ignore[attr-defined]
    return stack


async def close(stack: Stack) -> None:
    await replay.close_rig(stack.rig)
    stack._tmp.cleanup()  # type: ignore[attr-defined]


async def test_the_witness_adapter_is_a_real_presentation_display_sink(catalog):
    stack = await make_stack(catalog, [{}])
    try:
        assert isinstance(stack.sink, PresentationDisplaySink)
    finally:
        await close(stack)


async def test_a_presentation_intent_is_decided_and_executed_by_the_tool_brain_through_the_owner(catalog):
    stack = await make_stack(catalog, [{"actions": [show(A, intent_id="INTENT")]}])
    try:
        receipt = await stack.sink.publish(output_intent(A))
        assert receipt.delivered and receipt.code == "tool_brain_intent_accepted" and receipt.detail.startswith("uiintent-")
        intent_id = receipt.detail
        stack.rig.decider._replies = [{"actions": [show(A, intent_id=intent_id)]}]  # noqa: SLF001 - recorded answer names its intent
        decision = await stack.decide()
        assert decision.trigger["classes"] == {"ui_intent": 1}
        assert [(a.action.tool, a.verdict) for a in decision.actions] == [("scene_update_object", "would_apply")]
        seen = stack.rig.decider.requests[0].intents
        assert seen[0]["intent_id"] == intent_id and seen[0]["kind"] == "reveal" and seen[0]["ref_refusals"] == []
        assert await stack.rig.runtime.pump() == 1 and await stack.hidden() == [B]  # one object shown, by the canonical owner
        assert stack.rig.scene.apply_if_calls == 1 and stack.rig.scene.other_writes == 0
    finally:
        await close(stack)


async def test_withdraw_cancels_what_is_queued_not_yet_shown_and_counts_it(catalog):
    stack = await make_stack(catalog, [{}])
    try:
        receipt = await stack.sink.publish(output_intent(A))
        stack.rig.decider._replies = [{"actions": [show(A, intent_id=receipt.detail, trigger={"type": "delay", "seconds": 10})]}]  # noqa: SLF001
        await stack.decide()
        assert stack.rig.queue.pending_count() == 1
        assert stack.sink.withdraw_speculative("addressed_turn_armed", correlation_id=CORRELATION) == 1
        (view,) = stack.rig.queue.views()
        assert (view.status, view.code) == ("cancelled", "intent_withdrawn")
        stack.rig.clock.advance(11)
        assert await stack.rig.runtime.pump() == 0 and await stack.hidden() == [A, B]  # it never ran
        assert stack.sink.withdraw_speculative("again", correlation_id=CORRELATION) == 0  # nothing left to withdraw
    finally:
        await close(stack)


async def test_withdrawal_does_not_undo_what_is_already_on_screen_and_only_counts_what_it_withdrew(catalog):
    stack = await make_stack(catalog, [{}])
    try:
        shown = await stack.sink.publish(output_intent(A, correlation="corr-1"))
        waiting = await stack.sink.publish(output_intent(B, correlation="corr-1"))
        stack.rig.decider._replies = [{"actions": [
            show(A, intent_id=shown.detail), show(B, intent_id=waiting.detail, trigger={"type": "delay", "seconds": 30})]}]  # noqa: SLF001
        await stack.decide()
        assert await stack.rig.runtime.pump() == 1 and await stack.hidden() == [B]
        assert stack.sink.withdraw_speculative("armed", correlation_id="corr-1") == 1  # only the one still waiting
        assert await stack.hidden() == [B]  # A stays shown: a withdrawal undoes nothing
    finally:
        await close(stack)


async def test_a_decision_in_flight_cannot_requeue_a_withdrawn_intent_and_the_decider_stops_seeing_it(catalog):
    stack = await make_stack(catalog, [{}])
    try:
        receipt = await stack.sink.publish(output_intent(A))
        assert stack.sink.withdraw_speculative("addressed_vocative_turn", correlation_id=CORRELATION) == 1
        stack.rig.decider._replies = [{"actions": [show(A, intent_id=receipt.detail)]}]  # noqa: SLF001 - a late answer
        decision = await stack.decide()
        assert stack.rig.decider.requests[0].intents == ()  # the withdrawn row is not shown to the decider
        assert decision.actions[0].queued["outcome"] == "rejected" and decision.actions[0].queued["code"] == "intent_withdrawn"
        assert stack.rig.queue.pending_count() == 0 and await stack.rig.runtime.pump() == 0 and await stack.hidden() == [A, B]
    finally:
        await close(stack)


async def test_when_the_tool_brain_will_not_act_the_receipt_says_so_and_the_sink_can_fall_back(catalog):
    shadow = await make_stack(catalog, [{}], mode=ToolBrainMode.SHADOW)
    try:
        receipt = shadow.intake.submit(UiIntentDraft(UiIntentKind.REVEAL, (UiIntentRef(UiIntentRefKind.OBJECT, A),),
                                                     timing=UiIntentTiming.NOW),
                                       conversation_id=CONVERSATION, correlation_id=CORRELATION)
        assert receipt.accepted and receipt.will_execute is False  # shadow observes: Jarvis / the direct sink keeps the screen
        refused = await shadow.sink.publish(output_intent(A, correlation="corr-2"))
        assert not refused.delivered and refused.code == "tool_brain_not_owner"
    finally:
        await close(shadow)
    off = await make_stack(catalog, [{}])
    try:
        off.rig.runtime._config = type(off.rig.runtime._config)(mode=ToolBrainMode.OFF)  # noqa: SLF001
        refused = await off.sink.publish(output_intent(A))
        assert (refused.delivered, refused.code) == (False, f"tool_brain_{TOOL_BRAIN_OFF}")
    finally:
        await close(off)


async def test_a_not_owning_active_tool_brain_accepts_but_does_not_promise_execution(catalog):
    stack = await make_stack(catalog, [{}])
    try:
        stack.rig.runtime._owner_gate = lambda: False  # noqa: SLF001 - S8 arbiter says Jarvis owns the screen
        receipt = await stack.sink.publish(output_intent(A))
        assert not receipt.delivered and receipt.code == "tool_brain_not_owner" and stack.intake.will_execute is False
    finally:
        await close(stack)


async def test_invalid_intents_and_the_per_turn_cap_are_typed_refusals_not_exceptions(catalog):
    stack = await make_stack(catalog, [{}])
    try:
        assert stack.intake.submit({"kind": "explode"}, conversation_id=CONVERSATION, correlation_id=CORRELATION).code == INVALID_INTENT
        assert stack.intake.submit(None, conversation_id=CONVERSATION, correlation_id=CORRELATION).code == INVALID_INTENT  # type: ignore[arg-type]
        draft = {"kind": "reveal", "subject": "marge", "timing": "now"}
        codes = [stack.intake.submit(draft, conversation_id=CONVERSATION, correlation_id="corr-cap").code for _ in range(9)]
        assert codes[:8] == ["intent_accepted"] * 8 and codes[8] == "too_many_intents"
    finally:
        await close(stack)
