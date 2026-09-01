from __future__ import annotations

from typing import Protocol
from jarvis.domain.actions import ActionRequest, ActionResult


class ActionBrokerPort(Protocol):
    async def request(self, action: ActionRequest, *, turn_id: str) -> ActionResult: ...
    async def resolve_confirmation(self, text: str, *, action_id: str) -> ActionResult: ...
