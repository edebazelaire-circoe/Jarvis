from __future__ import annotations

from typing import Protocol
from jarvis.domain.messages import UserTurn
from jarvis.domain.results import AgentResult
from jarvis.domain.tools import ToolCatalog


class AgentBackend(Protocol):
    async def respond(self, turn: UserTurn, tools: ToolCatalog) -> AgentResult: ...
