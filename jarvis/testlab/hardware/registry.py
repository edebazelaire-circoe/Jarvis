"""Which implementation names the `hardware:auto` and `hardware:guided` profiles run.

Binding contract: `docs/testlab.md` ("Hardware profiles"). Same shape as
`jarvis.testlab.audio.registry`: the declaration module keeps the reviewed names and the
profile each one belongs to, the factory comes from here, and it is lazy — a supervisor
that never runs a hardware diagnostic never imports a voice stack, and never imports
`sounddevice`.

Registering a name makes a diagnostic RUNNABLE, never PERMITTED. A hardware run still
needs the device capabilities in the caller's grant, the Slice 08 contention gate to say
the live Jarvis is not using the microphone, the shared device lease, and — for
`hardware:guided` — `JARVIS_TESTLAB_GUIDED=1`, the operator saying a human is at this
keyboard now. Availability is a property of the code; every one of those is a property
of the request.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.testlab.implementations import ImplementationEntry, registered
from jarvis.testlab.profiles import ProfileName

SCENARIO_AUTO_IMPLEMENTATION = "testlab.scenario.hardware_auto"
SCENARIO_GUIDED_IMPLEMENTATION = "testlab.scenario.hardware_guided"
SELF_ECHO_AUTO_IMPLEMENTATION = "voice.self_echo.hardware_auto"
SELF_ECHO_GUIDED_IMPLEMENTATION = "voice.self_echo.hardware_guided"

#: Implementation name -> (profile, runner class name in `jarvis.testlab.hardware.runners`).
HARDWARE_RUNNERS: dict[str, tuple[ProfileName, str]] = {
    SCENARIO_AUTO_IMPLEMENTATION: (ProfileName.HARDWARE_AUTO, "HardwareScenarioRunner"),
    SCENARIO_GUIDED_IMPLEMENTATION: (ProfileName.HARDWARE_GUIDED, "GuidedScenarioRunner"),
    SELF_ECHO_AUTO_IMPLEMENTATION: (ProfileName.HARDWARE_AUTO, "SelfEchoHardwareRunner"),
    SELF_ECHO_GUIDED_IMPLEMENTATION: (ProfileName.HARDWARE_GUIDED, "SelfEchoGuidedRunner"),
}


def _factory(class_name: str) -> Callable[[], Any]:
    def build() -> Any:
        from jarvis.testlab.hardware import runners

        return getattr(runners, class_name)()

    build.__name__ = f"build_{class_name}"
    return build


def hardware_implementations() -> tuple[ImplementationEntry, ...]:
    """The registrations a supervisor and its workers compose over `default_implementations()`."""
    return tuple(registered(name, profile, _factory(class_name))
                 for name, (profile, class_name) in HARDWARE_RUNNERS.items())
