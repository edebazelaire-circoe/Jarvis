"""Pure memory contracts (handoff jarvis-memory-intelligence-knowledge, Slice 01).

Vocabulary and models shared by the canonical store, the retrievers, the
consolidator and the knowledge assets. Contract page: `docs/memory.md`.

Two independent axes describe a note (never merged in one badge):

- `RetentionClass`: lifetime policy, the directory under `<data_root>/memory`;
- `MemoryLevel`: abstraction, front-matter `level` (L0 evidence .. L3 profile).

Authority: only the canonical store owns durable truth. Everything a retriever
returns references a canonical `memory_id` (or is labelled derived). No I/O, no
dependency outside the standard library and `jarvis.domain._checks`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import math
import re
from types import MappingProxyType
import uuid

from jarvis.domain._checks import check_text, check_token, preview

# ----------------------------------------------------------------------- bounds
MAX_TITLE_CHARS = 200
#: Canonical note body. Generous: notes are files, but a contract needs a bound.
MAX_BODY_CHARS = 64_000
MAX_SNIPPET_CHARS = 2_000
MAX_WHY_CHARS = 200
MAX_QUERY_CHARS = 2_000
MAX_EVIDENCE_CHARS = 8_000
MAX_REF_CHARS = 512
MAX_LINKS = 32
MAX_SOURCES = 32
MAX_RECALL_ITEMS = 50
MAX_BATCH = 100
MAX_REASON_CHARS = 300

# --------------------------------------------------------------- recall budgets
# Defaults of Slice 00 resolved architecture 2.4. Hard ceilings are the contract
# bounds; the defaults are what `RecallBudget()` gives.
DEFAULT_RECALL_MAX_ITEMS = 6
DEFAULT_RECALL_ITEM_CHARS = 400
DEFAULT_RECALL_TOTAL_CHARS = 3_000
DEFAULT_RECALL_TIMEOUT_MS = 400
MIN_RECALL_TIMEOUT_MS = 100
MAX_RECALL_TIMEOUT_MS = 1_500
DEFAULT_LEXICAL_TIMEOUT_MS = 150
DEFAULT_SEMANTIC_TIMEOUT_MS = 250
DEFAULT_TENCENT_TIMEOUT_MS = 250

#: Legacy `notes/` directory written by `MemoryBackend.append_note`. Not one of
#: the five retention classes: recall treats it as `long_term_memory`, and it is
#: never moved.
LEGACY_NOTES_DIR = "notes"


class RetentionClass(StrEnum):
    """Lifetime policy = directory name (mirrors `MEMORY_CLASSES`)."""

    SHORT_TERM = "short_term_memory"
    LONG_TERM = "long_term_memory"
    TRAUMATIC = "traumatic_memory"
    ETERNAL = "eternal_memory"
    PLASTIC = "plastic_memory"


#: Legacy `notes/` is recalled as this class.
LEGACY_NOTES_RETENTION = RetentionClass.LONG_TERM


class MemoryLevel(StrEnum):
    """Abstraction level: L0 evidence, L1 atomic, L2 scenario, L3 stable profile."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    SCENARIO = "scenario"
    PROFILE = "profile"
    EPISODE = "episode"


class SourceType(StrEnum):
    TURN = "turn"
    NOTE = "note"
    BOARD = "board"
    MANUAL = "manual"
    CONSOLIDATION = "consolidation"


class MemoryErrorCode(StrEnum):
    """Stable refusal codes. Values travel in routes, MCP and logs: never rename."""

    NOT_FOUND = "memory_not_found"
    CONFLICT_REVISION = "memory_conflict_revision"
    SCOPE_DENIED = "memory_scope_denied"
    DEGRADED = "memory_degraded"
    UNAVAILABLE = "memory_unavailable"


class MemoryStoreError(Exception):
    """Coded refusal or failure of a memory operation (store, retriever, consolidator)."""

    def __init__(self, code: MemoryErrorCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.message = message


class DegradedReason(StrEnum):
    """Why a recall leg did not contribute. Lexical keeps working in every case."""

    LEXICAL_TIMEOUT = "lexical_timeout"
    SEMANTIC_TIMEOUT = "semantic_timeout"
    SEMANTIC_UNAVAILABLE = "semantic_unavailable"
    SEMANTIC_CAPACITY = "semantic_capacity"
    TENCENT_TIMEOUT = "tencent_timeout"
    TENCENT_UNAVAILABLE = "tencent_unavailable"
    RECALL_TIMEOUT = "recall_timeout"
    STORE_UNAVAILABLE = "store_unavailable"


class CapabilityStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


# -------------------------------------------------------------------- validators
_SCOPE = re.compile(r"(private|shared|(board|project):[A-Za-z0-9][A-Za-z0-9_.-]{0,95})\Z")
#: Scope without a qualifier.
PRIVATE_SCOPE = "private"
SHARED_SCOPE = "shared"


def check_scope(name: str, value: object) -> None:
    """`private`, `shared`, `board:<id>` or `project:<id>`; anything else is refused."""

    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not _SCOPE.fullmatch(value):
        raise ValueError(f"{name} must be private, shared, board:<id> or project:<id>, got {preview(value)}")


def check_optional_token(name: str, value: object, limit: int) -> None:
    """`None`, or a short token (`check_token` alone refuses `None`)."""

    if value is not None:
        check_token(name, value, limit, required=True)


def new_memory_id() -> str:
    """Stable identity, independent of the file path (a move keeps the id)."""

    return uuid.uuid4().hex


def check_aware(name: str, value: object, *, required: bool = True) -> None:
    if value is None and not required:
        return
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def check_enum(name: str, value: object, enum: type[StrEnum]) -> None:
    if not isinstance(value, enum):
        raise TypeError(f"{name} must be a {enum.__name__}")


def check_unit(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within 0..1")


def check_int_range(name: str, value: object, low: int, high: int) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if not low <= value <= high:
        raise ValueError(f"{name} must be within {low}..{high}")


def check_bool(name: str, value: object) -> None:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")


def _freeze_ids(owner: object, name: str, value: object, *, limit: int = MAX_LINKS) -> None:
    """Coerce an iterable of memory ids to a tuple of valid, distinct ids."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise TypeError(f"{name} must be a sequence of ids")
    items = tuple(value)
    if len(items) > limit:
        raise ValueError(f"{name} holds at most {limit} ids")
    for item in items:
        check_token(name, item, 64, required=True)
    if len(set(items)) != len(items):
        raise ValueError(f"{name} must not repeat an id")
    object.__setattr__(owner, name, items)


def _freeze_sources(owner: object, name: str, value: object) -> None:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise TypeError(f"{name} must be a sequence of Provenance")
    items = tuple(value)
    if len(items) > MAX_SOURCES:
        raise ValueError(f"{name} holds at most {MAX_SOURCES} sources")
    if not all(isinstance(item, Provenance) for item in items):
        raise TypeError(f"{name} must hold Provenance values only")
    object.__setattr__(owner, name, items)


# ------------------------------------------------------------------------ models
@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a fact came from: kind of source, a reference into it, and when."""

    type: SourceType
    ref: str
    at: datetime

    def __post_init__(self) -> None:
        check_enum("type", self.type, SourceType)
        check_text("ref", self.ref, MAX_REF_CHARS)
        if not self.ref:
            raise ValueError("ref is required")
        check_aware("at", self.at)


@dataclass(frozen=True, slots=True)
class MemoryNote:
    """A canonical note. `id` is assigned by the caller of `create` (`new_memory_id`).

    `revision` starts at 1 and only the store advances it. Links (`supersedes`,
    `superseded_by`, `contradicts`) are written by the consolidation pipeline or
    a human, never by a retriever. The `level` x `retention` pairing is checked
    by `memory_policy.check_level_retention`, not here, so a legacy note can be
    represented before it is classified.
    """

    id: str
    title: str
    body: str
    level: MemoryLevel
    kind: MemoryKind
    retention: RetentionClass
    scope: str
    created_at: datetime
    updated_at: datetime
    revision: int = 1
    agent: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    confidence: float = 1.0
    sources: tuple[Provenance, ...] = ()
    supersedes: tuple[str, ...] = ()
    superseded_by: str | None = None
    contradicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        check_token("id", self.id, 64, required=True)
        check_text("title", self.title, MAX_TITLE_CHARS)
        if not self.title.strip():
            raise ValueError("title is required")
        check_text("body", self.body, MAX_BODY_CHARS, single_line=False)
        check_enum("level", self.level, MemoryLevel)
        check_enum("kind", self.kind, MemoryKind)
        check_enum("retention", self.retention, RetentionClass)
        check_scope("scope", self.scope)
        check_aware("created_at", self.created_at)
        check_aware("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        check_int_range("revision", self.revision, 1, 2 ** 31 - 1)
        check_optional_token("agent", self.agent, 64)
        check_aware("valid_from", self.valid_from, required=False)
        check_aware("valid_to", self.valid_to, required=False)
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not precede valid_from")
        check_unit("confidence", self.confidence)
        _freeze_sources(self, "sources", self.sources)
        _freeze_ids(self, "supersedes", self.supersedes)
        _freeze_ids(self, "contradicts", self.contradicts)
        check_optional_token("superseded_by", self.superseded_by, 64)
        if self.id in self.supersedes or self.id in self.contradicts or self.id == self.superseded_by:
            raise ValueError("a note cannot link to itself")

    @property
    def is_superseded(self) -> bool:
        return self.superseded_by is not None


@dataclass(frozen=True, slots=True)
class MemoryPatch:
    """Fields `revise` may change; `None` means unchanged. At least one is required.

    Identity, `created_at`, `revision`, `retention` and `scope` are not
    patchable: moving a note between classes or scopes is a promotion, owned by
    the consolidation policy, not an edit.
    """

    title: str | None = None
    body: str | None = None
    level: MemoryLevel | None = None
    kind: MemoryKind | None = None
    valid_to: datetime | None = None
    confidence: float | None = None
    superseded_by: str | None = None
    add_sources: tuple[Provenance, ...] = ()
    add_supersedes: tuple[str, ...] = ()
    add_contradicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.title is not None:
            check_text("title", self.title, MAX_TITLE_CHARS)
            if not self.title.strip():
                raise ValueError("title must not be empty")
        if self.body is not None:
            check_text("body", self.body, MAX_BODY_CHARS, single_line=False)
        if self.level is not None:
            check_enum("level", self.level, MemoryLevel)
        if self.kind is not None:
            check_enum("kind", self.kind, MemoryKind)
        check_aware("valid_to", self.valid_to, required=False)
        if self.confidence is not None:
            check_unit("confidence", self.confidence)
        check_optional_token("superseded_by", self.superseded_by, 64)
        _freeze_sources(self, "add_sources", self.add_sources)
        _freeze_ids(self, "add_supersedes", self.add_supersedes)
        _freeze_ids(self, "add_contradicts", self.add_contradicts)
        if not self.changed_fields:
            raise ValueError("a patch must change at least one field")

    @property
    def changed_fields(self) -> tuple[str, ...]:
        return tuple(
            name for name in (
                "title", "body", "level", "kind", "valid_to", "confidence", "superseded_by",
                "add_sources", "add_supersedes", "add_contradicts",
            )
            if getattr(self, name) not in (None, ())
        )


@dataclass(frozen=True, slots=True)
class MemoryFilters:
    """Listing filters of `CanonicalMemoryStore.list`. Empty tuples mean no filter."""

    scopes: tuple[str, ...] = ()
    retentions: tuple[RetentionClass, ...] = ()
    levels: tuple[MemoryLevel, ...] = ()
    kinds: tuple[MemoryKind, ...] = ()
    include_superseded: bool = False
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        for name, enum in (("retentions", RetentionClass), ("levels", MemoryLevel), ("kinds", MemoryKind)):
            items = tuple(getattr(self, name))
            if not all(isinstance(item, enum) for item in items):
                raise TypeError(f"{name} must hold {enum.__name__} values only")
            object.__setattr__(self, name, items)
        scopes = tuple(self.scopes)
        for scope in scopes:
            check_scope("scopes", scope)
        object.__setattr__(self, "scopes", scopes)
        check_bool("include_superseded", self.include_superseded)
        check_int_range("limit", self.limit, 1, 500)
        check_int_range("offset", self.offset, 0, 10 ** 9)


@dataclass(frozen=True, slots=True)
class RecallBudget:
    """Count, size and time budgets of one recall (defaults: architecture 2.4)."""

    max_items: int = DEFAULT_RECALL_MAX_ITEMS
    max_item_chars: int = DEFAULT_RECALL_ITEM_CHARS
    max_total_chars: int = DEFAULT_RECALL_TOTAL_CHARS
    timeout_ms: int = DEFAULT_RECALL_TIMEOUT_MS
    lexical_timeout_ms: int = DEFAULT_LEXICAL_TIMEOUT_MS
    semantic_timeout_ms: int = DEFAULT_SEMANTIC_TIMEOUT_MS
    tencent_timeout_ms: int = DEFAULT_TENCENT_TIMEOUT_MS

    def __post_init__(self) -> None:
        check_int_range("max_items", self.max_items, 1, MAX_RECALL_ITEMS)
        check_int_range("max_item_chars", self.max_item_chars, 1, MAX_SNIPPET_CHARS)
        check_int_range("max_total_chars", self.max_total_chars, 1, MAX_RECALL_ITEMS * MAX_SNIPPET_CHARS)
        check_int_range("timeout_ms", self.timeout_ms, MIN_RECALL_TIMEOUT_MS, MAX_RECALL_TIMEOUT_MS)
        for name in ("lexical_timeout_ms", "semantic_timeout_ms", "tencent_timeout_ms"):
            check_int_range(name, getattr(self, name), 1, MAX_RECALL_TIMEOUT_MS)


@dataclass(frozen=True, slots=True)
class RecallQuery:
    """What to recall. `scopes` are already narrowed by `AgentMemoryPolicy`.

    Empty `scopes` recalls nothing (deny by scope). `at` selects temporal
    validity (`valid_from <= at < valid_to`); `None` means now.
    """

    text: str
    scopes: tuple[str, ...]
    retentions: tuple[RetentionClass, ...] = ()
    levels: tuple[MemoryLevel, ...] = ()
    include_history: bool = False
    at: datetime | None = None
    agent: str | None = None

    def __post_init__(self) -> None:
        check_text("text", self.text, MAX_QUERY_CHARS, single_line=False)
        scopes = tuple(self.scopes)
        for scope in scopes:
            check_scope("scopes", scope)
        object.__setattr__(self, "scopes", scopes)
        for name, enum in (("retentions", RetentionClass), ("levels", MemoryLevel)):
            items = tuple(getattr(self, name))
            if not all(isinstance(item, enum) for item in items):
                raise TypeError(f"{name} must hold {enum.__name__} values only")
            object.__setattr__(self, name, items)
        check_bool("include_history", self.include_history)
        check_aware("at", self.at, required=False)
        check_optional_token("agent", self.agent, 64)


@dataclass(frozen=True, slots=True)
class RecallItem:
    """One recalled note: answers "why is this here?" (source, revision, rank legs)."""

    memory_id: str
    title: str
    snippet: str
    score: float
    rank_sources: Mapping[str, int]
    level: MemoryLevel
    retention: RetentionClass
    provenance_ref: str
    revision: int
    why: str = ""

    def __post_init__(self) -> None:
        check_token("memory_id", self.memory_id, 64, required=True)
        check_text("title", self.title, MAX_TITLE_CHARS)
        check_text("snippet", self.snippet, MAX_SNIPPET_CHARS, single_line=False)
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)) or not math.isfinite(self.score):
            raise ValueError("score must be a finite number")
        if not isinstance(self.rank_sources, Mapping):
            raise TypeError("rank_sources must be a mapping")
        for leg, rank in self.rank_sources.items():
            check_token("rank_sources key", leg, 32, required=True)
            check_int_range(f"rank_sources[{leg!r}]", rank, 1, 10 ** 6)
        object.__setattr__(self, "rank_sources", MappingProxyType(dict(self.rank_sources)))
        check_enum("level", self.level, MemoryLevel)
        check_enum("retention", self.retention, RetentionClass)
        check_text("provenance_ref", self.provenance_ref, MAX_REF_CHARS)
        if not self.provenance_ref:
            raise ValueError("provenance_ref is required")
        check_int_range("revision", self.revision, 1, 2 ** 31 - 1)
        check_text("why", self.why, MAX_WHY_CHARS)


@dataclass(frozen=True, slots=True)
class RecallResult:
    """Ranked items plus how the recall degraded. Degraded is data, never an exception."""

    items: tuple[RecallItem, ...] = ()
    degraded: tuple[DegradedReason, ...] = ()
    timings_ms: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        items = tuple(self.items)
        if len(items) > MAX_RECALL_ITEMS:
            raise ValueError(f"items holds at most {MAX_RECALL_ITEMS} entries")
        if not all(isinstance(item, RecallItem) for item in items):
            raise TypeError("items must hold RecallItem values only")
        object.__setattr__(self, "items", items)
        degraded = tuple(self.degraded)
        if not all(isinstance(item, DegradedReason) for item in degraded):
            raise TypeError("degraded must hold DegradedReason values only")
        if len(set(degraded)) != len(degraded):
            raise ValueError("degraded must not repeat a reason")
        object.__setattr__(self, "degraded", degraded)
        if not isinstance(self.timings_ms, Mapping):
            raise TypeError("timings_ms must be a mapping")
        for leg, value in self.timings_ms.items():
            check_token("timings_ms key", leg, 32, required=True)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"timings_ms[{leg!r}] must be a finite non-negative number")
        object.__setattr__(self, "timings_ms", MappingProxyType(dict(self.timings_ms)))

    @property
    def is_degraded(self) -> bool:
        return bool(self.degraded)


@dataclass(frozen=True, slots=True)
class Evidence:
    """L0 raw evidence handed to the consolidator (a turn excerpt, a note import)."""

    text: str
    source: Provenance
    scope: str
    agent: str | None = None

    def __post_init__(self) -> None:
        check_text("text", self.text, MAX_EVIDENCE_CHARS, single_line=False)
        if not self.text.strip():
            raise ValueError("text is required")
        if not isinstance(self.source, Provenance):
            raise TypeError("source must be a Provenance")
        check_scope("scope", self.scope)
        check_optional_token("agent", self.agent, 64)


class CandidateState(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED_BY_NEWER = "superseded_by_newer"


class CandidateDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


#: Legal moves of the candidate state machine (architecture 2.7). Only
#: `proposed` leaves its state; the three others are final.
CANDIDATE_TRANSITIONS: Mapping[CandidateState, frozenset[CandidateState]] = MappingProxyType({
    CandidateState.PROPOSED: frozenset({
        CandidateState.ACCEPTED, CandidateState.REJECTED, CandidateState.SUPERSEDED_BY_NEWER,
    }),
    CandidateState.ACCEPTED: frozenset(),
    CandidateState.REJECTED: frozenset(),
    CandidateState.SUPERSEDED_BY_NEWER: frozenset(),
})


def can_transition(current: CandidateState, target: CandidateState) -> bool:
    return target in CANDIDATE_TRANSITIONS[current]


@dataclass(frozen=True, slots=True)
class Candidate:
    """A proposed note awaiting a decision. Lives in `_candidates/`, never recalled."""

    id: str
    title: str
    body: str
    level: MemoryLevel
    kind: MemoryKind
    retention: RetentionClass
    scope: str
    confidence: float
    evidence_hash: str
    created_at: datetime
    state: CandidateState = CandidateState.PROPOSED
    sources: tuple[Provenance, ...] = ()
    conflicts: tuple[str, ...] = ()
    decided_at: datetime | None = None
    decided_by: str | None = None
    committed_memory_id: str | None = None

    def __post_init__(self) -> None:
        check_token("id", self.id, 64, required=True)
        check_text("title", self.title, MAX_TITLE_CHARS)
        if not self.title.strip():
            raise ValueError("title is required")
        check_text("body", self.body, MAX_BODY_CHARS, single_line=False)
        check_enum("level", self.level, MemoryLevel)
        check_enum("kind", self.kind, MemoryKind)
        check_enum("retention", self.retention, RetentionClass)
        check_scope("scope", self.scope)
        check_unit("confidence", self.confidence)
        check_token("evidence_hash", self.evidence_hash, 128, required=True)
        check_aware("created_at", self.created_at)
        check_enum("state", self.state, CandidateState)
        _freeze_sources(self, "sources", self.sources)
        _freeze_ids(self, "conflicts", self.conflicts)
        check_aware("decided_at", self.decided_at, required=False)
        check_optional_token("decided_by", self.decided_by, 64)
        check_optional_token("committed_memory_id", self.committed_memory_id, 64)
        decided = self.state is not CandidateState.PROPOSED
        if decided != (self.decided_at is not None) or decided != (self.decided_by is not None):
            raise ValueError("decided_at and decided_by are set exactly when the candidate is decided")
        if (self.committed_memory_id is not None) != (self.state is CandidateState.ACCEPTED):
            raise ValueError("committed_memory_id is set exactly when the candidate is accepted")


@dataclass(frozen=True, slots=True)
class CapabilityState:
    """Health of one leg or asset kind. Never plain "ok" when it does not work.

    `ok` carries no reason; every other status states a stable `reason_code`
    (machine) and a human `reason`, so a UI cannot show "on" for a leg that is
    degraded, disabled or unavailable.
    """

    status: CapabilityStatus
    reason_code: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        check_enum("status", self.status, CapabilityStatus)
        check_optional_token("reason_code", self.reason_code, 64)
        check_text("reason", self.reason, MAX_REASON_CHARS)
        if self.status is CapabilityStatus.OK:
            if self.reason_code is not None or self.reason:
                raise ValueError("an ok capability carries no reason")
        elif self.reason_code is None:
            raise ValueError(f"a {self.status.value} capability requires a reason_code")

    @property
    def is_ok(self) -> bool:
        return self.status is CapabilityStatus.OK


def capability_ok() -> CapabilityState:
    return CapabilityState(CapabilityStatus.OK)


def describe_scope_kind(scope: str) -> str:
    """`private`, `shared`, `board` or `project` for a valid scope."""

    check_scope("scope", scope)
    return scope.partition(":")[0]

