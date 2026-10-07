"""Knowledge assets (Wiki, CodeGraph, Skills) and agent loadouts, pure (Slice 01).

Assets live under `<data_root>/knowledge/{wiki,codegraph,skills}/`, outside the
personal memory root. They are derived or imported material, never canonical
memory, and each one carries a `SourceRef` so "where does this come from?" is
always answerable. A `Loadout` names what one agent profile may see; it is
deny-by-scope. Contract page: `docs/memory.md`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from jarvis.domain._checks import check_text, check_token
from jarvis.domain.memory import (
    MAX_BODY_CHARS,
    MAX_REASON_CHARS,
    MAX_REF_CHARS,
    MAX_TITLE_CHARS,
    PRIVATE_SCOPE,
    check_aware,
    check_enum,
    check_int_range,
    check_optional_token,
    check_scope,
)

MAX_ASSET_SUMMARY_CHARS = 1_024
MAX_LOADOUT_ENTRIES = 64
#: Longest manifest a loadout may render into a sub-agent brief.
MAX_LOADOUT_MANIFEST_CHARS = 1_024


class AssetKind(StrEnum):
    WIKI = "wiki"
    CODEGRAPH = "codegraph"
    SKILL = "skill"


class AssetScope(StrEnum):
    PRIVATE = "private"
    PROJECT = "project"
    SHARED = "shared"


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Origin of an asset: where it was read, at which version, when and where in it."""

    uri: str
    version_or_commit: str
    fetched_at: datetime
    path: str | None = None
    line: int | None = None

    def __post_init__(self) -> None:
        check_text("uri", self.uri, MAX_REF_CHARS)
        if not self.uri:
            raise ValueError("uri is required")
        check_text("version_or_commit", self.version_or_commit, 128)
        if not self.version_or_commit:
            raise ValueError("version_or_commit is required")
        check_aware("fetched_at", self.fetched_at)
        if self.path is not None:
            check_text("path", self.path, MAX_REF_CHARS)
        if self.line is not None:
            check_int_range("line", self.line, 1, 10 ** 9)


@dataclass(frozen=True, slots=True)
class KnowledgeAsset:
    """One asset. `list` and `search` return it with an empty `body`; `read` fills it.

    `stale` is true when the source moved on since the snapshot (CodeGraph HEAD
    or tree differs, a wiki source hash changed). `confidence` labels how the
    answer was derived (CodeGraph uses `name_match`).
    """

    asset_id: str
    kind: AssetKind
    title: str
    scope: AssetScope
    source: SourceRef
    summary: str = ""
    body: str = ""
    version: str = "1"
    stale: bool = False
    confidence: str | None = None

    def __post_init__(self) -> None:
        check_token("asset_id", self.asset_id, 128, required=True)
        check_enum("kind", self.kind, AssetKind)
        check_text("title", self.title, MAX_TITLE_CHARS)
        if not self.title.strip():
            raise ValueError("title is required")
        check_enum("scope", self.scope, AssetScope)
        if not isinstance(self.source, SourceRef):
            raise TypeError("source must be a SourceRef")
        check_text("summary", self.summary, MAX_ASSET_SUMMARY_CHARS, single_line=False)
        check_text("body", self.body, MAX_BODY_CHARS, single_line=False)
        check_token("version", self.version, 64, required=True)
        if type(self.stale) is not bool:
            raise TypeError("stale must be a boolean")
        check_optional_token("confidence", self.confidence, 32)


@dataclass(frozen=True, slots=True)
class AssetHit:
    """A search result: the asset (without body), a bounded snippet and a rank score."""

    asset: KnowledgeAsset
    snippet: str
    score: float

    def __post_init__(self) -> None:
        if not isinstance(self.asset, KnowledgeAsset):
            raise TypeError("asset must be a KnowledgeAsset")
        check_text("snippet", self.snippet, 2_000, single_line=False)
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise TypeError("score must be a number")


def _ids(owner: object, name: str, value: object, *, token: bool = True) -> None:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise TypeError(f"{name} must be a sequence")
    items = tuple(value)
    if len(items) > MAX_LOADOUT_ENTRIES:
        raise ValueError(f"{name} holds at most {MAX_LOADOUT_ENTRIES} entries")
    for item in items:
        if token:
            check_token(name, item, 128, required=True)
        else:
            check_scope(name, item)
    if len(set(items)) != len(items):
        raise ValueError(f"{name} must not repeat an entry")
    object.__setattr__(owner, name, items)


@dataclass(frozen=True, slots=True)
class Loadout:
    """What one agent profile (plus optional role) may see. Deny by scope.

    `profile` is a routing task profile (`desktop|code|fast|general`), `role` an
    optional tag (`coder|reviewer|research`). `reasons` maps an included entry
    (`scope:<scope>`, `wiki:<id>`, `codegraph:<repo>`, `skill:<id>`) to why it is
    there, so the effective loadout is inspectable. The private scope is refused
    unless `allow_private` is set explicitly.
    """

    profile: str
    role: str | None = None
    memory_scopes: tuple[str, ...] = ()
    wiki_ids: tuple[str, ...] = ()
    codegraph_repos: tuple[str, ...] = ()
    skill_ids: tuple[str, ...] = ()
    allow_private: bool = False
    reasons: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        check_token("profile", self.profile, 32, required=True)
        check_optional_token("role", self.role, 32)
        _ids(self, "memory_scopes", self.memory_scopes, token=False)
        _ids(self, "wiki_ids", self.wiki_ids)
        _ids(self, "codegraph_repos", self.codegraph_repos)
        _ids(self, "skill_ids", self.skill_ids)
        if type(self.allow_private) is not bool:
            raise TypeError("allow_private must be a boolean")
        if PRIVATE_SCOPE in self.memory_scopes and not self.allow_private:
            raise ValueError("memory_scopes names the private scope but allow_private is false")
        if not isinstance(self.reasons, Mapping):
            raise TypeError("reasons must be a mapping")
        if len(self.reasons) > 4 * MAX_LOADOUT_ENTRIES:
            raise ValueError("reasons holds too many entries")
        for key, reason in self.reasons.items():
            check_text("reasons key", key, 160)
            check_text("reasons value", reason, MAX_REASON_CHARS)
        object.__setattr__(self, "reasons", MappingProxyType(dict(self.reasons)))

    @property
    def is_empty(self) -> bool:
        return not (self.memory_scopes or self.wiki_ids or self.codegraph_repos or self.skill_ids)
