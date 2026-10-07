"""Memory settings model: dataclasses, defaults and validation only (Slice 01).

Pure. Reading and writing `control-center-settings.json` is Slice 10a
(`jarvis/runtime/memory_settings.py`); this module only defines what a valid
`MemorySettings` is, so an invalid combination is unrepresentable. Secrets are
never fields here: they live in `credentials`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import re
from enum import StrEnum
from types import MappingProxyType

from jarvis.domain._checks import check_text
from jarvis.domain.knowledge import MAX_LOADOUT_ENTRIES
from jarvis.domain.memory import (
    PRIVATE_SCOPE,
    DEFAULT_RECALL_MAX_ITEMS,
    DEFAULT_RECALL_TIMEOUT_MS,
    MAX_RECALL_TIMEOUT_MS,
    MIN_RECALL_TIMEOUT_MS,
    check_bool,
    check_enum,
    check_int_range,
    check_scope,
    check_unit,
)
from jarvis.domain.memory_policy import AUTO_MIN_CONFIDENCE
from jarvis.domain.routing import TASK_PROFILE_IDS

MAX_SETTINGS_RECALL_ITEMS = 10
MAX_CANDIDATES_PER_RUN = 100
DEFAULT_CANDIDATES_PER_RUN = 20
MAX_URL_CHARS = 512
MAX_SERVICE_ID_CHARS = 128
SERVICE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


class EmbeddingProviderId(StrEnum):
    NONE = "none"
    OPENAI = "openai"


class ConsolidationMode(StrEnum):
    MANUAL = "manual"
    AUTO = "auto"


@dataclass(frozen=True, slots=True)
class RecallSettings:
    enabled: bool = True
    max_items: int = DEFAULT_RECALL_MAX_ITEMS
    timeout_ms: int = DEFAULT_RECALL_TIMEOUT_MS

    def __post_init__(self) -> None:
        check_bool("recall.enabled", self.enabled)
        check_int_range("recall.max_items", self.max_items, 1, MAX_SETTINGS_RECALL_ITEMS)
        check_int_range("recall.timeout_ms", self.timeout_ms, MIN_RECALL_TIMEOUT_MS, MAX_RECALL_TIMEOUT_MS)


@dataclass(frozen=True, slots=True)
class SemanticSettings:
    enabled: bool = False
    provider: EmbeddingProviderId = EmbeddingProviderId.NONE
    #: Private scopes are not sent to a remote embedder unless the user allows it.
    allow_private: bool = False

    def __post_init__(self) -> None:
        check_bool("semantic.enabled", self.enabled)
        check_enum("semantic.provider", self.provider, EmbeddingProviderId)
        check_bool("semantic.allow_private", self.allow_private)


@dataclass(frozen=True, slots=True)
class ConsolidationSettings:
    mode: ConsolidationMode = ConsolidationMode.MANUAL
    auto_min_confidence: float = AUTO_MIN_CONFIDENCE
    max_candidates_per_run: int = DEFAULT_CANDIDATES_PER_RUN

    def __post_init__(self) -> None:
        check_enum("consolidation.mode", self.mode, ConsolidationMode)
        check_unit("consolidation.auto_min_confidence", self.auto_min_confidence)
        check_int_range("consolidation.max_candidates_per_run", self.max_candidates_per_run, 1, MAX_CANDIDATES_PER_RUN)


@dataclass(frozen=True, slots=True)
class TencentSettings:
    """Optional sidecar. The token is a credential, never a field."""

    enabled: bool = False
    url: str = ""
    #: Instance id sent as `x-tdai-service-id`: an identifier, not a credential. Empty: no header.
    service_id: str = ""
    #: Private notes leave the machine for the sidecar only when the user allows it (risk R12).
    allow_private: bool = False

    def __post_init__(self) -> None:
        check_bool("tencent.enabled", self.enabled)
        check_text("tencent.url", self.url, MAX_URL_CHARS)
        check_text("tencent.service_id", self.service_id, MAX_SERVICE_ID_CHARS)
        if self.service_id and not SERVICE_ID.fullmatch(self.service_id):
            raise ValueError("tencent.service_id must be a short identifier")
        check_bool("tencent.allow_private", self.allow_private)


@dataclass(frozen=True, slots=True)
class KnowledgeSettings:
    wiki_enabled: bool = True
    codegraph_enabled: bool = True
    skills_enabled: bool = True

    def __post_init__(self) -> None:
        check_bool("knowledge.wiki_enabled", self.wiki_enabled)
        check_bool("knowledge.codegraph_enabled", self.codegraph_enabled)
        check_bool("knowledge.skills_enabled", self.skills_enabled)


def combination_errors(settings: MemorySettings) -> tuple[str, ...]:
    """Every incompatibility of a settings object, empty when it is coherent."""

    errors: list[str] = []
    if settings.semantic.enabled and settings.semantic.provider is EmbeddingProviderId.NONE:
        errors.append("semantic.enabled requires a semantic.provider other than none")
    if settings.consolidation.mode is ConsolidationMode.AUTO and not settings.semantic.enabled:
        errors.append("consolidation.mode=auto requires semantic.enabled")
    if settings.tencent.enabled and not settings.tencent.url.strip():
        errors.append("tencent.enabled requires tencent.url")
    return tuple(errors)


@dataclass(frozen=True, slots=True)
class MemorySettings:
    """Effective memory settings. Defaults are the safe local-only configuration."""

    recall: RecallSettings = field(default_factory=RecallSettings)
    semantic: SemanticSettings = field(default_factory=SemanticSettings)
    consolidation: ConsolidationSettings = field(default_factory=ConsolidationSettings)
    tencent: TencentSettings = field(default_factory=TencentSettings)
    knowledge: KnowledgeSettings = field(default_factory=KnowledgeSettings)

    def __post_init__(self) -> None:
        for name, kind in (
            ("recall", RecallSettings), ("semantic", SemanticSettings),
            ("consolidation", ConsolidationSettings), ("tencent", TencentSettings),
            ("knowledge", KnowledgeSettings),
        ):
            if not isinstance(getattr(self, name), kind):
                raise TypeError(f"{name} must be a {kind.__name__}")
        errors = combination_errors(self)
        if errors:
            raise ValueError("; ".join(errors))


# ---------------------------------------------------------------------- loadouts
#: Role tags a sub-agent brief may carry (architecture 2.9), and the Brain's own key.
LOADOUT_ROLES = ("coder", "reviewer", "research")
BRAIN_PROFILE = "brain"
LOADOUT_PROFILES = (*TASK_PROFILE_IDS, BRAIN_PROFILE)


def loadout_key(profile: str, role: str | None = None) -> str:
    """`<profile>` or `<profile>:<role>`: how a loadout rule and a snapshot entry are named."""

    return profile if role is None else f"{profile}:{role}"


def check_loadout_key(name: str, value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    profile, _sep, role = value.partition(":")
    if profile not in LOADOUT_PROFILES or (_sep and role not in LOADOUT_ROLES):
        raise ValueError(f"{name} must be <profile> or <profile>:<role> (profiles {', '.join(LOADOUT_PROFILES)}; roles {', '.join(LOADOUT_ROLES)})")


@dataclass(frozen=True, slots=True)
class LoadoutRule:
    """A user rule that REPLACES the built-in preset for one loadout key (deny by default).

    `memory_scopes` is exactly what the loadout may read; a project scope is concrete
    (`project:<id>`). The private scope needs `allow_private` as well: naming it is the
    explicit policy rule that lets private memory reach a non-Brain loadout.
    """

    memory_scopes: tuple[str, ...] = ()
    allow_private: bool = False
    wiki: bool = True
    codegraph: bool = True
    skills: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.memory_scopes, (str, bytes)) or not isinstance(self.memory_scopes, Iterable):
            raise TypeError("loadouts.memory_scopes must be a sequence")
        scopes = tuple(self.memory_scopes)
        if len(scopes) > MAX_LOADOUT_ENTRIES:
            raise ValueError(f"loadouts.memory_scopes holds at most {MAX_LOADOUT_ENTRIES} entries")
        for scope in scopes:
            check_scope("loadouts.memory_scopes", scope)
        if len(set(scopes)) != len(scopes):
            raise ValueError("loadouts.memory_scopes must not repeat a scope")
        check_bool("loadouts.allow_private", self.allow_private)
        if PRIVATE_SCOPE in scopes and not self.allow_private:
            raise ValueError("loadouts.memory_scopes names the private scope but allow_private is false")
        for name in ("wiki", "codegraph", "skills"):
            check_bool(f"loadouts.{name}", getattr(self, name))
        object.__setattr__(self, "memory_scopes", scopes)


@dataclass(frozen=True, slots=True)
class LoadoutPolicy:
    """`memory.loadouts`: user rules by loadout key. Empty means the built-in presets apply."""

    rules: Mapping[str, LoadoutRule] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not isinstance(self.rules, Mapping):
            raise TypeError("loadouts must be a mapping")
        for key, rule in self.rules.items():
            check_loadout_key("loadouts key", key)
            if not isinstance(rule, LoadoutRule):
                raise TypeError("loadouts values must be LoadoutRule")
        object.__setattr__(self, "rules", MappingProxyType(dict(self.rules)))

    def rule_for(self, key: str) -> LoadoutRule | None:
        return self.rules.get(key)
