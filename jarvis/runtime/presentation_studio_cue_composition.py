"""Composition of the Studio cue follower for one PRESENTATION session (handoff jarvis-interactive-presentation-studio, Slice 13).

Kept out of `presentation_runtime.py` (already far above the size rule of thumb): this module only wires the follower's
read-only probes to the addressed-turn service. It builds nothing that can act: the follower itself is the contract.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.domain.interaction_mode import InteractionMode
from jarvis.runtime.presentation_studio_cue_follower import PresentationStudioCueFollower


def build_cue_follower(*, cue_core: Any | None, turns: Any, mode: Callable[[], object], journal: Any | None) -> PresentationStudioCueFollower | None:
    """The follower of a session, or `None` without a Core client. It reads the explicit address through `turns` and never writes to it."""

    if cue_core is None:
        return None

    def in_flight() -> bool:
        # An addressed turn is open and not yet concluded: its latency measure is in flight (`conclude` forgets it).
        return int(turns.stats().get("latency_pending") or 0) > 0

    return PresentationStudioCueFollower(
        core=cue_core, window_live=turns.window_live, turn_in_flight=in_flight,
        address_marker=lambda: int(turns.counters.armed),  # grows each time an explicit address is armed
        mode_ok=lambda: mode() is InteractionMode.PRESENTATION, journal=journal,
    )
