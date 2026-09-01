from __future__ import annotations

from typing import Protocol, Any


class BoardClient(Protocol):
    async def present(self, title: str, body: str, *, x: float | None = None, y: float | None = None) -> dict[str, Any]: ...
    async def health(self) -> bool: ...
