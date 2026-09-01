from __future__ import annotations

from dataclasses import dataclass
from jarvis.domain.actions import ActionKind, RiskLevel


@dataclass(frozen=True, slots=True)
class ActionPolicy:
    risk: RiskLevel
    requires_confirmation: bool


V1_ACTION_POLICY: dict[ActionKind, ActionPolicy] = {
    ActionKind.MEMORY_SEARCH: ActionPolicy(RiskLevel.READ, False),
    ActionKind.BOARD_PRESENT: ActionPolicy(RiskLevel.EPHEMERAL, False),
    ActionKind.MEMORY_APPEND: ActionPolicy(RiskLevel.WRITE, True),
}

FORBIDDEN_TOOL_NAMES = frozenset({
    "bash", "shell", "powershell", "cmd", "terminal", "filesystem_write",
    "delete_file", "send_email", "browser", "install_software",
})
