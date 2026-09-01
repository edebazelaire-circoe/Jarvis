from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
import uuid


class ActionKind(StrEnum):
    MEMORY_SEARCH = "memory_search"
    MEMORY_APPEND = "memory_append"
    BOARD_PRESENT = "board_present"


class RiskLevel(StrEnum):
    READ = "read"
    EPHEMERAL = "ephemeral"
    WRITE = "write"


class ActionStatus(StrEnum):
    EXECUTED = "executed"
    PENDING = "pending"
    DENIED = "denied"
    FAILED = "failed"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ActionRequest:
    kind: ActionKind
    summary: str
    risk: RiskLevel
    payload: dict[str, Any]
    requires_confirmation: bool
    action_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True, slots=True)
class ActionResult:
    action_id: str
    status: ActionStatus
    message: str
    output: Any = None

    @property
    def terminal(self) -> bool:
        return self.status not in {ActionStatus.PENDING}
