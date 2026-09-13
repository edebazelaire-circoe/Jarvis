"""Provider-neutral recovery seam for a retained Live session identity."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Protocol

from jarvis.domain.live_lifecycle import live_id, live_seconds


LIVE_CLOSE_REASONS = frozenset({
    "close_requested", "expired", "content", "remote_hangup", "connection_lost",
})


@dataclass(frozen=True, slots=True)
class LiveTerminalReceipt:
    provider_session_id: str
    reason: str
    usage_seconds: float

    def __post_init__(self) -> None:
        live_id(self.provider_session_id, "provider_session_id")
        if self.reason not in LIVE_CLOSE_REASONS:
            raise ValueError("invalid Live close reason")
        live_seconds(self.usage_seconds, "provider_usage_seconds")


class LiveSidebandCloser(Protocol):
    async def close_session(
        self, provider_session_id: str,
        on_receipt: Callable[[LiveTerminalReceipt], Awaitable[None]],
    ) -> LiveTerminalReceipt: ...
