"""Which implementation names the `audio` profile runs.

Binding contract: `docs/testlab.md` ("Audio profile"). Same shape as
`jarvis.testlab.virtual.registry`: the declaration module keeps the reviewed
names and their profile, the factory comes from here, and it is lazy — a
supervisor that never runs an audio diagnostic never imports a voice stack or an
echo canceller.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.testlab.implementations import ImplementationEntry, registered
from jarvis.testlab.profiles import ProfileName

SCENARIO_IMPLEMENTATION = "testlab.scenario.audio"
SELF_ECHO_IMPLEMENTATION = "voice.self_echo.audio"

#: Implementation name -> runner class name in `jarvis.testlab.audio.runners`.
AUDIO_RUNNERS: dict[str, str] = {
    SCENARIO_IMPLEMENTATION: "AudioScenarioRunner",
    SELF_ECHO_IMPLEMENTATION: "SelfEchoAudioRunner",
}


def _factory(class_name: str) -> Callable[[], Any]:
    def build() -> Any:
        from jarvis.testlab.audio import runners

        return getattr(runners, class_name)()

    build.__name__ = f"build_{class_name}"
    return build


def audio_implementations() -> tuple[ImplementationEntry, ...]:
    """The registrations a supervisor and its workers compose over `default_implementations()`."""
    return tuple(registered(name, ProfileName.AUDIO, _factory(class_name))
                 for name, class_name in AUDIO_RUNNERS.items())
