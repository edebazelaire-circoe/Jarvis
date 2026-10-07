"""Public intake of the Tool Brain for semantic UI intents and their withdrawal (handoff jarvis-tool-brain-ui-orchestrator, S10).

Contract: `docs/tool-brain-contracts.md` section 18.6 (Level 3). This is the seam the deferred Slice 08 of
`jarvis-presentation-interaction-mode` plugs into: its `ToolBrainDisplaySink` implements `PresentationDisplaySink`
(`jarvis/core/presentation_display.py`) on top of **two calls** and nothing else:

- `PresentationDisplaySink.publish(PresentationOutputIntent)` -> `ToolBrainIntake.submit(UiIntentDraft, ...)`: the sink maps
  the output intent to the SAME typed `UiIntentDraft` Jarvis publishes (`reveal_prepared` -> `reveal`, `show_attention` ->
  `attention`, `resource_refs` -> object refs); the Tool Brain stays the decision owner of tools, timing and ids;
- `PresentationDisplaySink.withdraw_speculative(reason, correlation_id=)` -> `ToolBrainIntake.withdraw(reason, ...)`: the
  queue cancellation (`intent_withdrawn`) of what was submitted and is not yet on screen.

What the intake does NOT do: it chooses no tool, executes nothing, and does not bypass ownership. `IntakeReceipt.will_execute`
tells the sink whether the Tool Brain will act (mode `active` and the screen owned); when it is false the sink keeps its own
fallback (`DirectSceneDisplaySink`), so exactly one executor ever acts (the S8 rule).

Process boundary (known limit, S08's first task): the intake is an in-process object of Core, next to the Tool Brain. The
presentation composition runs in the voice process; its sink reaches the intake through a thin Core route that S08 adds over
these two methods. `POST /v1/ui-intents` is NOT that route: it is Jarvis's tool route and refuses without a turn in flight.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

from jarvis.core.ui_intents import UiIntentRefused, UiIntentRegistry
from jarvis.domain.ui_intent import UiIntentDraft
from jarvis.runtime.tool_brain_runtime import ToolBrainMode, ToolBrainRuntime, WakeClass

INVALID_INTENT = "invalid_intent"
TOOL_BRAIN_OFF = "tool_brain_off"
MAX_TRACKED_INTENTS = 128


@dataclass(frozen=True, slots=True)
class IntakeReceipt:
    """Typed answer, never an exception for an expected refusal. `code` is stable; `detail` is a code too."""

    accepted: bool
    code: str
    intent_id: str | None = None
    #: True only when the Tool Brain can act on it now (`active` and the screen is its). False: keep the sink's fallback.
    will_execute: bool = False

    def to_trace_payload(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "code": self.code, "intent_id": self.intent_id,
                "will_execute": self.will_execute}


class ToolBrainIntake:
    def __init__(self, runtime: ToolBrainRuntime, registry: UiIntentRegistry, *,
                 max_tracked: int = MAX_TRACKED_INTENTS) -> None:
        self._runtime = runtime
        self._registry = registry
        self._tracked: deque[tuple[str, str, str]] = deque(maxlen=max_tracked)  # (intent_id, conversation, correlation)

    @property
    def will_execute(self) -> bool:
        return self._runtime.can_execute

    def submit(self, intent: UiIntentDraft | Mapping[str, Any], *, conversation_id: str, correlation_id: str,
               urgent: bool | None = None) -> IntakeReceipt:
        """Register a semantic UI intent for the turn `correlation_id` and wake the Tool Brain. Never raises."""

        if self._runtime.mode is ToolBrainMode.OFF:
            return IntakeReceipt(False, TOOL_BRAIN_OFF)
        try:
            draft = intent if isinstance(intent, UiIntentDraft) else UiIntentDraft.from_payload(dict(intent))
        except (ValueError, TypeError):
            return IntakeReceipt(False, INVALID_INTENT)  # the message would name a field, never its value: not echoed
        try:
            stored = self._registry.publish(conversation_id, correlation_id, draft)
        except UiIntentRefused as refusal:
            return IntakeReceipt(False, refusal.code)
        except ValueError:
            return IntakeReceipt(False, INVALID_INTENT)
        self._tracked.append((stored.intent_id, conversation_id, correlation_id))
        self._runtime.wake(WakeClass.UI_INTENT, "presentation_intent", urgent=urgent, conversation_id=conversation_id,
                           correlation_id=correlation_id)
        return IntakeReceipt(True, "intent_accepted", stored.intent_id, self._runtime.can_execute)

    def withdraw(self, reason: str, *, correlation_id: str = "") -> int:
        """Retire what this intake submitted (for `correlation_id`, or everything when blank) and is not on screen yet.

        Rends the number of intents actually withdrawn (the `withdraw_speculative` count): an intent whose action already
        ran is not withdrawn (a withdrawal does not undo the screen). Pending queue actions of the others are cancelled
        (`intent_withdrawn`), a decision in flight cannot re-queue them, and the decider no longer sees them.
        """

        wanted = [item for item in self._tracked if not correlation_id or item[2] == correlation_id]
        done = self._runtime.withdraw_intents([item[0] for item in wanted], reason)
        gone = set(done)
        remaining = [item for item in self._tracked if item[0] not in gone]
        self._tracked.clear()
        self._tracked.extend(remaining)
        return len(done)


__all__ = ["INVALID_INTENT", "IntakeReceipt", "MAX_TRACKED_INTENTS", "TOOL_BRAIN_OFF", "ToolBrainIntake"]
