"""Provider-neutral, local evidence for a Live semantic-idle decision."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LiveIdleEvidence:
    sensor_known: bool
    device_known: bool
    user_speaking: bool
    output_pending: bool

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in (
            self.sensor_known, self.device_known,
            self.user_speaking, self.output_pending,
        )):
            raise ValueError("invalid Live idle evidence")

    @property
    def locally_idle(self) -> bool:
        return (
            self.sensor_known and self.device_known
            and not self.user_speaking and not self.output_pending
        )
