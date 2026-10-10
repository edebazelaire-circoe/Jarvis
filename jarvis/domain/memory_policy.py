"""Memory policy: level x retention matrix, protected classes, per-agent scope rules.

Pure (Slice 01). The matrix and the scope rules are data here; enforcement
belongs to the store (matrix, protected classes) and the memory service (scopes).
Contract page: `docs/memory.md`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from jarvis.domain._checks import check_token, preview
from jarvis.domain.memory import (
    MemoryErrorCode,
    MemoryLevel,
    MemoryStoreError,
    PRIVATE_SCOPE,
    RetentionClass,
    check_scope,
)

#: Allowed levels per retention class. Two independent axes: a class says how
#: long a note lives, a level says how abstract it is. L0 (raw evidence) is
#: transient, so it only lives in `short_term_memory`; a traumatic note is a
#: specific episode or lesson, never a stable profile.
LEVELS_BY_RETENTION: Mapping[RetentionClass, frozenset[MemoryLevel]] = MappingProxyType({
    RetentionClass.SHORT_TERM: frozenset({MemoryLevel.L0, MemoryLevel.L1, MemoryLevel.L2}),
    RetentionClass.LONG_TERM: frozenset({MemoryLevel.L1, MemoryLevel.L2, MemoryLevel.L3}),
    RetentionClass.PLASTIC: frozenset({MemoryLevel.L1, MemoryLevel.L2, MemoryLevel.L3}),
    RetentionClass.TRAUMATIC: frozenset({MemoryLevel.L1, MemoryLevel.L2}),
    RetentionClass.ETERNAL: frozenset({MemoryLevel.L1, MemoryLevel.L2, MemoryLevel.L3}),
})

#: No consolidation path may delete or rewrite these. Supersession by a human only.
PROTECTED_RETENTIONS = frozenset({RetentionClass.TRAUMATIC, RetentionClass.ETERNAL})

#: Retention classes automatic consolidation may commit into.
AUTO_COMMIT_RETENTIONS = frozenset({RetentionClass.LONG_TERM, RetentionClass.PLASTIC})

#: Minimum confidence for an `auto` commit (architecture 2.7).
AUTO_MIN_CONFIDENCE = 0.8


def is_level_allowed(level: MemoryLevel, retention: RetentionClass) -> bool:
    return level in LEVELS_BY_RETENTION[retention]


def check_level_retention(level: MemoryLevel, retention: RetentionClass) -> None:
    """Refuse a level that its retention class does not allow (`ValueError`)."""

    if not is_level_allowed(level, retention):
        allowed = ", ".join(sorted(item.value for item in LEVELS_BY_RETENTION[retention]))
        raise ValueError(f"level {level.value} is not allowed in {retention.value} (allowed: {allowed})")


def is_protected(retention: RetentionClass) -> bool:
    return retention in PROTECTED_RETENTIONS


@dataclass(frozen=True, slots=True)
class AgentMemoryPolicy:
    """Which scopes an agent may read and propose into. Deny by scope.

    Scopes are matched exactly. `private` appears in either list only when
    `allow_private` is true: private memory never reaches a non-Brain agent by
    accident (a loadout or a sub-agent policy must say so explicitly).
    """

    agent_id: str
    read_scopes: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()
    allow_private: bool = False

    def __post_init__(self) -> None:
        check_token("agent_id", self.agent_id, 64, required=True)
        if type(self.allow_private) is not bool:
            raise TypeError("allow_private must be a boolean")
        for name in ("read_scopes", "write_scopes"):
            raw = getattr(self, name)
            if isinstance(raw, (str, bytes)) or not isinstance(raw, Iterable):
                raise TypeError(f"{name} must be a sequence of scopes")
            scopes = tuple(raw)
            for scope in scopes:
                check_scope(name, scope)
                if scope == PRIVATE_SCOPE and not self.allow_private:
                    raise ValueError(f"{name} names the private scope but allow_private is false")
            if len(set(scopes)) != len(scopes):
                raise ValueError(f"{name} must not repeat a scope")
            object.__setattr__(self, name, scopes)
        if not set(self.write_scopes) <= set(self.read_scopes):
            raise ValueError("write_scopes must be readable: write_scopes is a subset of read_scopes")

    def can_read(self, scope: str) -> bool:
        return scope in self.read_scopes

    def can_write(self, scope: str) -> bool:
        return scope in self.write_scopes

    def check_read(self, scope: str) -> None:
        if not self.can_read(scope):
            raise MemoryStoreError(
                MemoryErrorCode.SCOPE_DENIED,
                f"agent {self.agent_id} may not read scope {preview(scope)}",
            )

    def check_write(self, scope: str) -> None:
        if not self.can_write(scope):
            raise MemoryStoreError(
                MemoryErrorCode.SCOPE_DENIED,
                f"agent {self.agent_id} may not write scope {preview(scope)}",
            )

    def narrow(self, requested: Iterable[str]) -> tuple[str, ...]:
        """Requested scopes this agent may read, in request order (deny by scope)."""

        seen: dict[str, None] = {}
        for scope in requested:
            check_scope("scope", scope)
            if self.can_read(scope):
                seen[scope] = None
        return tuple(seen)


def deny_all_policy(agent_id: str) -> AgentMemoryPolicy:
    """Default for any agent without an explicit grant: reads and writes nothing."""

    return AgentMemoryPolicy(agent_id=agent_id)
