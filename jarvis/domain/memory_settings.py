"""Memory settings model: dataclasses, defaults and validation only (Slice 01).

Pure. Reading and writing `control-center-settings.json` is Slice 10a
(`jarvis/runtime/memory_settings.py`); this module only defines what a valid
`MemorySettings` is, so an invalid combination is unrepresentable. Secrets are
never fields here: they live in `credentials`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from jarvis.domain._checks import check_text
from jarvis.domain.memory import (
    DEFAULT_RECALL_MAX_ITEMS,
    DEFAULT_RECALL_TIMEOUT_MS,
    MAX_RECALL_TIMEOUT_MS,
    MIN_RECALL_TIMEOUT_MS,
    check_bool,
    check_enum,
    check_int_range,
    check_unit,
)
from jarvis.domain.memory_policy import AUTO_MIN_CONFIDENCE

MAX_SETTINGS_RECALL_ITEMS = 10
MAX_CANDIDATES_PER_RUN = 100
DEFAULT_CANDIDATES_PER_RUN = 20
MAX_URL_CHARS = 512


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

    def __post_init__(self) -> None:
        check_bool("tencent.enabled", self.enabled)
        check_text("tencent.url", self.url, MAX_URL_CHARS)


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
