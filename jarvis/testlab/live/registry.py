"""Which implementation names the `live` profile runs.

Binding contract: `docs/testlab.md` ("Live profile"). Registering a name does NOT
make a provider call possible: a `live` run still needs the `realtime_provider`
capability in the caller's grant, a budget that covers the declared cost,
`JARVIS_TESTLAB_LIVE=1` in the supervisor's environment and `OPENAI_API_KEY` in
the worker's. Availability says "this diagnostic has a runner", never "this
diagnostic may spend money".
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.testlab.implementations import ImplementationEntry, registered
from jarvis.testlab.profiles import ProfileName

SCENARIO_IMPLEMENTATION = "testlab.scenario.live"
QUEUE_LATENCY_IMPLEMENTATION = "voice.queue_latency.live"

#: Implementation name -> runner class name in `jarvis.testlab.live.runners`.
LIVE_RUNNERS: dict[str, str] = {
    SCENARIO_IMPLEMENTATION: "LiveScenarioRunner",
    QUEUE_LATENCY_IMPLEMENTATION: "QueueLatencyLiveRunner",
}


def _factory(class_name: str) -> Callable[[], Any]:
    def build() -> Any:
        from jarvis.testlab.live import runners

        return getattr(runners, class_name)()

    build.__name__ = f"build_{class_name}"
    return build


def live_implementations() -> tuple[ImplementationEntry, ...]:
    """The registrations a supervisor and its workers compose over `default_implementations()`."""
    return tuple(registered(name, ProfileName.LIVE, _factory(class_name))
                 for name, class_name in LIVE_RUNNERS.items())
