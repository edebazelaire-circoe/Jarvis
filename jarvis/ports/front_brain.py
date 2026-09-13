"""Optional advisory analysis; no access to Core or output controls."""
from typing import Protocol, runtime_checkable

from jarvis.domain.front_brain_hints import FrontBrainHintRequest, FrontBrainHintResult


@runtime_checkable
class FrontBrainAnalyzer(Protocol):
    async def analyze(self, request: FrontBrainHintRequest) -> FrontBrainHintResult:
        """Return an app-bound result; the model supplies only the hint value.

        The caller owns input admission, deadline, concurrency and cancellation.
        Preserve CancelledError. Refusal/incomplete output cannot be AVAILABLE.
        No Core/frontend/tool/executor handles are passed through this port.
        This port does not make analysis a dependency of ordinary conversation.
        """
        ...
