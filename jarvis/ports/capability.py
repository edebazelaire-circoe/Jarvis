"""Capability reporting port (memory handoff, Slice 01).

Every optional leg (semantic index, Tencent sidecar, Wiki, CodeGraph, Skills)
reports one `CapabilityState`. Core aggregates them for `/v1/memory/status`;
a UI renders them and never shows plain "on" for a state that is not `ok`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from jarvis.domain.memory import CapabilityState


@runtime_checkable
class CapabilityReporter(Protocol):
    #: Stable key of the leg in the aggregated status (`lexical`, `semantic`, `tencent`...).
    capability_id: str

    def status(self) -> CapabilityState:
        """Cheap, never raises, never probes the network synchronously."""
        ...
