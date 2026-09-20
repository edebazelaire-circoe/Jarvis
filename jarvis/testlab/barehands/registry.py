"""Which implementation names the Bare Hands diagnostics actually run.

Same shape as `jarvis/testlab/virtual/registry.py`, and for the same two reasons:
the declaration module (`jarvis.testlab.implementations`) stays import-pure, and a
supervisor that never runs a Bare Hands diagnostic never imports node, `subprocess`
or the replay driver either — every factory below resolves
`jarvis.testlab.barehands.runners` only when it is called.

They live in their own package rather than under `virtual/` because the virtual
package *is* the voice stack: `virtual/runners.py` imports sessions, speech kinds and
an echo guard, none of which a replayed hand trace has any business loading.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.testlab.implementations import ImplementationEntry, registered
from jarvis.testlab.profiles import ProfileName

INPUT_QUALITY_IMPLEMENTATION = "barehands.input_quality.virtual"

#: Implementation name -> runner class name in `jarvis.testlab.barehands.runners`.
BAREHANDS_RUNNERS: dict[str, str] = {
    INPUT_QUALITY_IMPLEMENTATION: "InputQualityRunner",
}


def _factory(class_name: str) -> Callable[[], Any]:
    """A factory that imports the replay driver only when a run actually starts."""

    def build() -> Any:
        from jarvis.testlab.barehands import runners

        return getattr(runners, class_name)()

    build.__name__ = f"build_{class_name}"
    return build


def barehands_implementations() -> tuple[ImplementationEntry, ...]:
    """The registrations a supervisor and its workers compose over `default_implementations()`."""
    return tuple(registered(name, ProfileName.VIRTUAL, _factory(class_name))
                 for name, class_name in BAREHANDS_RUNNERS.items())
