"""Knowledge asset ports (memory handoff, Slice 01): providers and loadouts.

One `KnowledgeAssetProvider` per kind (Wiki, CodeGraph, Skills). Assets are
imported or derived material under `<data_root>/knowledge`, never canonical
memory. Synchronous (disk), called from Core through a thread.

`LoadoutResolver` decides what an agent profile may see. `NullLoadoutResolver`
is the default until Slice 09 ships the real one: it grants nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from jarvis.domain.knowledge import AssetHit, AssetKind, AssetScope, KnowledgeAsset, Loadout
from jarvis.domain.memory import CapabilityState


@runtime_checkable
class KnowledgeAssetProvider(Protocol):
    @property
    def kind(self) -> AssetKind: ...

    def status(self) -> CapabilityState: ...

    def list(self, scope: AssetScope | None = None) -> tuple[KnowledgeAsset, ...]:
        """Assets without body, optionally limited to one scope."""
        ...

    def search(self, query: str, limit: int, scope: AssetScope | None = None) -> Sequence[AssetHit]: ...

    def read(self, asset_id: str) -> KnowledgeAsset:
        """The asset with its body. `memory_not_found` when unknown."""
        ...

    def rebuild(self) -> int:
        """Rebuild the derived index; returns assets indexed. Nothing durable is lost."""
        ...


@runtime_checkable
class LoadoutResolver(Protocol):
    def resolve(self, profile: str, role: str | None = None) -> Loadout:
        """Effective loadout with the reason each entry is included. Never raises."""
        ...


class NullLoadoutResolver:
    """Grants nothing (deny by scope). Replaced by the real resolver in Slice 09."""

    def resolve(self, profile: str, role: str | None = None) -> Loadout:
        return Loadout(profile=profile, role=role)
