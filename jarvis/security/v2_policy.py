from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ActionDisposition(StrEnum):
    EXECUTE = "execute"
    CLARIFY = "clarify"
    CONFIRM = "confirm"
    DENY = "deny"


class ActionImpact(StrEnum):
    READ_ONLY = "read_only"
    REVERSIBLE_LOCAL = "reversible_local"
    PERSISTENT = "persistent"
    DESTRUCTIVE = "destructive"
    EXTERNAL = "external"


@dataclass(frozen=True, slots=True)
class V2ActionPolicy:
    impact: ActionImpact
    confirm: bool = False


POLICIES: dict[str, V2ActionPolicy] = {
    "memory_search": V2ActionPolicy(ActionImpact.READ_ONLY),"memory_append": V2ActionPolicy(ActionImpact.PERSISTENT, confirm=True),"board_present": V2ActionPolicy(ActionImpact.REVERSIBLE_LOCAL),"reminder_create": V2ActionPolicy(ActionImpact.REVERSIBLE_LOCAL),"reminder_cancel": V2ActionPolicy(ActionImpact.REVERSIBLE_LOCAL),"calendar_list": V2ActionPolicy(ActionImpact.READ_ONLY),"calendar_get": V2ActionPolicy(ActionImpact.READ_ONLY),"calendar_create": V2ActionPolicy(ActionImpact.REVERSIBLE_LOCAL),"calendar_update": V2ActionPolicy(ActionImpact.REVERSIBLE_LOCAL),"calendar_delete": V2ActionPolicy(ActionImpact.DESTRUCTIVE, confirm=True),"calendar_invite": V2ActionPolicy(ActionImpact.EXTERNAL, confirm=True),"job_cancel": V2ActionPolicy(ActionImpact.REVERSIBLE_LOCAL),
}


class V2ActionBroker:
    """Server-owned action policy; callers cannot self-assert risk/safety."""

    def evaluate(self, action_name: str, *, explicit_request: bool, ambiguous: bool) -> ActionDisposition:
        policy = POLICIES.get(action_name)
        if policy is None:
            return ActionDisposition.DENY
        if ambiguous:
            return ActionDisposition.CLARIFY
        if policy.confirm:
            return ActionDisposition.CONFIRM
        if policy.impact is not ActionImpact.READ_ONLY and not explicit_request:
            return ActionDisposition.CLARIFY
        return ActionDisposition.EXECUTE
