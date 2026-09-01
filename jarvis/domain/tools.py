from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


class ToolCatalog(Protocol):
    def definitions(self) -> tuple[ToolDefinition, ...]: ...
