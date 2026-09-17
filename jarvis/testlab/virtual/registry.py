"""Which implementation names the `virtual` profile actually runs.

Binding contract: `docs/testlab.md` ("Virtual profile"). Slice 04 reserved five virtual
names in `jarvis.testlab.implementations`; Slice 06 registers them here, through
`ImplementationRegistry.registering`, so that:

- the declaration module stays pure (it may not import a voice stack), and
- a supervisor or worker that never runs a virtual diagnostic never imports one either:
  every factory below resolves `jarvis.testlab.virtual.runners` only when it is called.

No manifest changed and no diagnostic version was bumped: availability lives in code,
which is exactly why Slice 04 put it there.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.testlab.implementations import ImplementationEntry, registered
from jarvis.testlab.profiles import ProfileName

SCENARIO_IMPLEMENTATION = "testlab.scenario.virtual"
SELF_ECHO_IMPLEMENTATION = "voice.self_echo.virtual"
PAYLOAD_INTEGRITY_IMPLEMENTATION = "speech.payload_integrity.virtual"
STALE_SUPERSESSION_IMPLEMENTATION = "speech.stale_supersession.virtual"
QUEUE_LATENCY_IMPLEMENTATION = "voice.queue_latency.virtual"

#: Implementation name -> runner class name in `jarvis.testlab.virtual.runners`.
VIRTUAL_RUNNERS: dict[str, str] = {
    SCENARIO_IMPLEMENTATION: "ScenarioRunner",
    SELF_ECHO_IMPLEMENTATION: "SelfEchoRunner",
    PAYLOAD_INTEGRITY_IMPLEMENTATION: "PayloadIntegrityRunner",
    STALE_SUPERSESSION_IMPLEMENTATION: "StaleSupersessionRunner",
    QUEUE_LATENCY_IMPLEMENTATION: "QueueLatencyRunner",
}


def _factory(class_name: str) -> Callable[[], Any]:
    """A factory that imports the voice stack only when a virtual run actually starts."""

    def build() -> Any:
        from jarvis.testlab.virtual import runners

        return getattr(runners, class_name)()

    build.__name__ = f"build_{class_name}"
    return build


def virtual_implementations() -> tuple[ImplementationEntry, ...]:
    """The registrations a supervisor and its workers compose over `default_implementations()`."""
    return tuple(registered(name, ProfileName.VIRTUAL, _factory(class_name))
                 for name, class_name in VIRTUAL_RUNNERS.items())
