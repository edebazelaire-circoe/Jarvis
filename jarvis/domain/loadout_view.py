"""The effective loadout as data, and its manifest, pure (Slice 09).

`LoadoutView` is what the resolver knows beyond the port's `Loadout`: the version
of each entry, the skill versions that lost, and which providers could not answer.
The manifest is the only text a sub-agent brief receives: ids and versions, never a
body (bodies are fetched on demand), capped at `MAX_LOADOUT_MANIFEST_CHARS`.
Contract page: `docs/skills-and-loadouts.md`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jarvis.domain._checks import check_text, check_token
from jarvis.domain.knowledge import MAX_LOADOUT_MANIFEST_CHARS, Loadout
from jarvis.domain.skills import SkillConflict

#: First words of a manifest. A brief that already holds it is never given a second one.
MANIFEST_MARK = "[loadout JARVIS]"
_ELLIPSIS = "…"
#: Display order and label of each entry kind.
_GROUPS = (("skill", "skills"), ("wiki", "wiki"), ("codegraph", "codegraph"), ("scope", "mémoire"))


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One included asset: `kind` is `scope|wiki|codegraph|skill`, `version` is optional."""

    kind: str
    id: str
    version: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {kind for kind, _label in _GROUPS}:
            raise ValueError(f"unknown manifest kind {self.kind!r}")
        check_text("id", self.id, 128)
        if not self.id:
            raise ValueError("id is required")
        if self.version is not None:
            check_token("version", self.version, 64, required=True)

    @property
    def label(self) -> str:
        return self.id if self.version is None else f"{self.id}@{self.version}"


@dataclass(frozen=True, slots=True)
class LoadoutView:
    """A `Loadout` with its entries' versions, skill conflicts and provider failures.

    `degraded` is `(asset kind, reason code)` for each provider that could not answer:
    its entries are then absent (deny by default), never guessed.
    """

    loadout: Loadout
    entries: tuple[ManifestEntry, ...] = ()
    conflicts: tuple[SkillConflict, ...] = ()
    degraded: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.loadout, Loadout):
            raise TypeError("loadout must be a Loadout")
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(self, "conflicts", tuple(self.conflicts))
        object.__setattr__(self, "degraded", tuple(self.degraded))

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready inspection payload: the loadout, why each entry is there, losers, failures."""

        loadout = self.loadout
        return {
            "profile": loadout.profile,
            "role": loadout.role,
            "memory_scopes": list(loadout.memory_scopes),
            "wiki_ids": list(loadout.wiki_ids),
            "codegraph_repos": list(loadout.codegraph_repos),
            "skill_ids": list(loadout.skill_ids),
            "allow_private": loadout.allow_private,
            "reasons": dict(loadout.reasons),
            "versions": {f"{entry.kind}:{entry.id}": entry.version for entry in self.entries if entry.version},
            "conflicts": [conflict.as_dict() for conflict in self.conflicts],
            "degraded": [{"kind": kind, "reason_code": code} for kind, code in self.degraded],
        }


def _lines(groups: Mapping[str, list[str]], hidden: int, header: str) -> str:
    lines = [header]
    lines += [f"{label}: {', '.join(groups[kind])}" for kind, label in _GROUPS if groups.get(kind)]
    if hidden:
        lines.append(f"(+{hidden} autres, voir knowledge_search)")
    return "\n".join(lines)


def render_manifest(view: LoadoutView, limit: int = MAX_LOADOUT_MANIFEST_CHARS) -> str:
    """The manifest text, or `""` for an empty loadout. Never longer than `limit` characters.

    Entries are dropped from the longest group's tail until it fits, and the count of
    dropped entries is stated. Ids and versions only: titles and bodies never appear.
    """

    if not view.entries:
        return ""
    loadout = view.loadout
    role = f", rôle {loadout.role}" if loadout.role else ""
    header = (f"{MANIFEST_MARK} profil {loadout.profile}{role}. Références disponibles "
              "(identifiants seulement ; le contenu se lit à la demande) :")
    groups: dict[str, list[str]] = {}
    for entry in view.entries:
        groups.setdefault(entry.kind, []).append(entry.label)
    hidden = 0
    text = _lines(groups, hidden, header)
    while len(text) > limit and any(groups.values()):
        longest = max(groups, key=lambda kind: len(groups[kind]))
        groups[longest].pop()
        hidden += 1
        text = _lines(groups, hidden, header)
    if len(text) > limit:  # the header alone overflows a tiny limit: clip, never exceed
        text = text[: max(0, limit - 1)] + _ELLIPSIS if limit > 0 else ""
    return text
