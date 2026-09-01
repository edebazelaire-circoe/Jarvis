from __future__ import annotations

from typing import Any


class UnavailableBoardClient:
    """Optional board boundary used when the UI is disabled or unavailable."""

    def __init__(self, reason: str = "board disabled") -> None:
        self.reason = reason

    async def present(
        self,
        title: str,
        body: str,
        *,
        x: float | None = None,
        y: float | None = None,
    ) -> dict[str, Any]:
        del title, body, x, y
        raise ConnectionError(self.reason)

    async def health(self) -> bool:
        return False
