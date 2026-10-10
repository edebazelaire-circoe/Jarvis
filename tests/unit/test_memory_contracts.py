"""Memory contracts (handoff jarvis-memory-intelligence-knowledge, Slice 01).

Pure models, policy, settings and ports: no I/O. Fakes below prove each port can
be implemented without owning canonical writes.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime, timedelta, timezone
import importlib
import inspect

import pytest

from jarvis.domain import memory as mem
from jarvis.domain.knowledge import (
    AssetHit,
    AssetKind,
    AssetScope,
    KnowledgeAsset,
    Loadout,
    SourceRef,
)
from jarvis.domain.memory import (
    CANDIDATE_TRANSITIONS,
    Candidate,
    CandidateDecision,
    CandidateState,
    CapabilityState,
    CapabilityStatus,
    DegradedReason,
    Evidence,
    MemoryErrorCode,
    MemoryFilters,
    MemoryKind,
    MemoryLevel,
    MemoryNote,
    MemoryPatch,
    MemoryStoreError,
    Provenance,
    RecallBudget,
    RecallItem,
    RecallQuery,
    RecallResult,
    RetentionClass,
    SourceType,
    can_transition,
    capability_ok,
    new_memory_id,
)
from jarvis.domain.memory_policy import (
    AUTO_COMMIT_RETENTIONS,
    LEVELS_BY_RETENTION,
    PROTECTED_RETENTIONS,
    AgentMemoryPolicy,
    check_level_retention,
    deny_all_policy,
    is_level_allowed,
)
from jarvis.domain.memory_settings import (
    ConsolidationMode,
    ConsolidationSettings,
    EmbeddingProviderId,
    MemorySettings,
    RecallSettings,
    SemanticSettings,
    TencentSettings,
)
from jarvis.ports.capability import CapabilityReporter
from jarvis.ports.knowledge import KnowledgeAssetProvider, LoadoutResolver, NullLoadoutResolver
from jarvis.ports.memory_consolidation import CandidateExtractor, MemoryConsolidator
from jarvis.ports.memory_retrieval import EmbeddingProvider, MemoryRetriever
from jarvis.ports.memory_store import CanonicalMemoryStore

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def note(**over) -> MemoryNote:
    base = dict(
        id="n1", title="Likes tea", body="Prefers green tea.", level=MemoryLevel.L1,
        kind=MemoryKind.PREFERENCE, retention=RetentionClass.LONG_TERM, scope="shared",
        created_at=NOW, updated_at=NOW,
    )
    base.update(over)
    return MemoryNote(**base)


def prov(**over) -> Provenance:
    base = dict(type=SourceType.TURN, ref="turn:42", at=NOW)
    base.update(over)
    return Provenance(**base)


def item(**over) -> RecallItem:
    base = dict(
        memory_id="n1", title="Likes tea", snippet="green tea", score=0.5, rank_sources={"lexical": 1},
        level=MemoryLevel.L1, retention=RetentionClass.LONG_TERM, provenance_ref="turn:42", revision=1,
    )
    base.update(over)
    return RecallItem(**base)


def source_ref() -> SourceRef:
    return SourceRef(uri="docs/memory.md", version_or_commit="abc123", fetched_at=NOW, path="docs/memory.md", line=3)


# ----------------------------------------------------------------- error codes
def test_error_code_values_are_stable():
    assert {code.name: code.value for code in MemoryErrorCode} == {
        "NOT_FOUND": "memory_not_found",
        "CONFLICT_REVISION": "memory_conflict_revision",
        "SCOPE_DENIED": "memory_scope_denied",
        "DEGRADED": "memory_degraded",
        "UNAVAILABLE": "memory_unavailable",
    }


def test_store_error_carries_code_and_prefixes_message():
    error = MemoryStoreError(MemoryErrorCode.NOT_FOUND, "no such note")
    assert error.code is MemoryErrorCode.NOT_FOUND
    assert str(error) == "memory_not_found: no such note"


def test_vocabulary_values_are_stable():
    assert [item.value for item in RetentionClass] == [
        "short_term_memory", "long_term_memory", "traumatic_memory", "eternal_memory", "plastic_memory",
    ]
    assert [item.value for item in MemoryLevel] == ["L0", "L1", "L2", "L3"]
    assert [item.value for item in DegradedReason] == [
        "lexical_timeout", "semantic_timeout", "semantic_unavailable", "semantic_capacity",
        "tencent_timeout", "tencent_unavailable", "recall_timeout", "store_unavailable", "leg_busy",
    ]
    assert [item.value for item in CapabilityStatus] == ["ok", "degraded", "disabled", "unavailable"]
    assert [item.value for item in AssetKind] == ["wiki", "codegraph", "skill"]
    assert mem.LEGACY_NOTES_DIR == "notes" and mem.LEGACY_NOTES_RETENTION is RetentionClass.LONG_TERM


def test_retention_classes_match_the_maintenance_worker():
    from jarvis.core.memory_maintenance import MEMORY_CLASSES

    assert tuple(item.value for item in RetentionClass) == MEMORY_CLASSES


# ------------------------------------------------------------------ MemoryNote
def test_note_defaults_and_helpers():
    built = note()
    assert built.revision == 1 and built.confidence == 1.0 and not built.is_superseded
    assert len(new_memory_id()) == 32 and new_memory_id() != new_memory_id()


@pytest.mark.parametrize("over, error", [
    ({"id": ""}, ValueError),
    ({"id": "a b"}, ValueError),
    ({"title": "  "}, ValueError),
    ({"title": "x" * (mem.MAX_TITLE_CHARS + 1)}, ValueError),
    ({"title": "two\nlines"}, ValueError),
    ({"body": "x" * (mem.MAX_BODY_CHARS + 1)}, ValueError),
    ({"level": "L1"}, TypeError),
    ({"retention": "notes"}, TypeError),
    ({"scope": "everyone"}, ValueError),
    ({"scope": "board:"}, ValueError),
    ({"created_at": datetime(2026, 1, 1)}, ValueError),
    ({"updated_at": NOW - timedelta(seconds=1)}, ValueError),
    ({"revision": 0}, ValueError),
    ({"revision": True}, TypeError),
    ({"confidence": 1.01}, ValueError),
    ({"confidence": float("nan")}, ValueError),
    ({"valid_from": NOW, "valid_to": NOW - timedelta(days=1)}, ValueError),
    ({"supersedes": ("n1",)}, ValueError),
    ({"superseded_by": "n1"}, ValueError),
    ({"contradicts": ("n2", "n2")}, ValueError),
    ({"supersedes": "n2"}, TypeError),
    ({"sources": ("turn:1",)}, TypeError),
])
def test_note_validation_refuses(over, error):
    with pytest.raises(error):
        note(**over)


def test_note_accepts_every_scope_form():
    for scope in ("private", "shared", "board:b_1", "project:jarvis"):
        assert note(scope=scope).scope == scope


def test_note_is_frozen_and_coerces_sequences_to_tuples():
    built = note(sources=[prov()], supersedes=["n2"], contradicts=["n3"])
    assert isinstance(built.sources, tuple) and built.supersedes == ("n2",) and built.contradicts == ("n3",)
    with pytest.raises(dataclasses.FrozenInstanceError):
        built.title = "other"
    assert note(superseded_by="n2").is_superseded


def test_note_bounds_links_and_sources():
    with pytest.raises(ValueError):
        note(supersedes=tuple(f"n{i}" for i in range(2, mem.MAX_LINKS + 3)))
    with pytest.raises(ValueError):
        note(sources=tuple(prov() for _ in range(mem.MAX_SOURCES + 1)))


def test_provenance_validation():
    with pytest.raises(ValueError):
        prov(ref="")
    with pytest.raises(ValueError):
        prov(at=datetime(2026, 1, 1))
    with pytest.raises(TypeError):
        prov(type="turn")
    with pytest.raises(ValueError):
        prov(ref="x" * (mem.MAX_REF_CHARS + 1))


# ----------------------------------------------------------- patch and filters
def test_patch_requires_a_change_and_validates_fields():
    with pytest.raises(ValueError):
        MemoryPatch()
    assert MemoryPatch(body="new").changed_fields == ("body",)
    assert MemoryPatch(add_sources=[prov()], confidence=0.0).changed_fields == ("confidence", "add_sources")
    with pytest.raises(ValueError):
        MemoryPatch(title=" ")
    with pytest.raises(ValueError):
        MemoryPatch(confidence=2)
    with pytest.raises(TypeError):
        MemoryPatch(level="L1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        MemoryPatch(body="x").body = "y"


def test_filters_defaults_and_bounds():
    filters = MemoryFilters()
    assert filters.limit == 50 and filters.offset == 0 and not filters.include_superseded
    assert MemoryFilters(retentions=[RetentionClass.ETERNAL]).retentions == (RetentionClass.ETERNAL,)
    for over in ({"limit": 0}, {"limit": 501}, {"offset": -1}, {"scopes": ("nope",)}):
        with pytest.raises(ValueError):
            MemoryFilters(**over)
    with pytest.raises(TypeError):
        MemoryFilters(levels=("L1",))


# --------------------------------------------------------------------- recall
def test_budget_defaults_match_resolved_architecture():
    budget = RecallBudget()
    assert (budget.max_items, budget.max_item_chars, budget.max_total_chars) == (6, 400, 3_000)
    assert (budget.timeout_ms, budget.lexical_timeout_ms) == (400, 150)
    assert (budget.semantic_timeout_ms, budget.tencent_timeout_ms) == (250, 250)


@pytest.mark.parametrize("over", [
    {"max_items": 0}, {"max_items": mem.MAX_RECALL_ITEMS + 1}, {"max_item_chars": 0},
    {"max_item_chars": mem.MAX_SNIPPET_CHARS + 1}, {"timeout_ms": 99}, {"timeout_ms": 1501},
    {"lexical_timeout_ms": 0}, {"max_items": 6.0},
])
def test_budget_bounds(over):
    with pytest.raises((ValueError, TypeError)):
        RecallBudget(**over)


def test_query_validation_and_deny_by_scope_default():
    query = RecallQuery(text="tea", scopes=["shared", "board:b1"])
    assert query.scopes == ("shared", "board:b1")
    assert RecallQuery(text="tea", scopes=()).scopes == ()
    for over, error in (
        ({"text": "x" * (mem.MAX_QUERY_CHARS + 1)}, ValueError),
        ({"scopes": ("everything",)}, ValueError),
        ({"levels": ("L1",)}, TypeError),
        ({"at": datetime(2026, 1, 1)}, ValueError),
    ):
        with pytest.raises(error):
            RecallQuery(**{"text": "tea", "scopes": ("shared",), **over})


def test_recall_item_is_frozen_bounded_and_freezes_rank_sources():
    source = {"lexical": 2, "semantic": 1}
    built = item(rank_sources=source)
    source["tencent"] = 9
    assert dict(built.rank_sources) == {"lexical": 2, "semantic": 1}
    with pytest.raises(TypeError):
        built.rank_sources["x"] = 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        built.score = 1.0
    for over, error in (
        ({"snippet": "x" * (mem.MAX_SNIPPET_CHARS + 1)}, ValueError),
        ({"score": float("inf")}, ValueError),
        ({"rank_sources": {"lexical": 0}}, ValueError),
        ({"rank_sources": {"bad leg": 1}}, ValueError),
        ({"provenance_ref": ""}, ValueError),
        ({"revision": 0}, ValueError),
        ({"why": "x" * (mem.MAX_WHY_CHARS + 1)}, ValueError),
        ({"memory_id": ""}, ValueError),
    ):
        with pytest.raises(error):
            item(**over)


def test_recall_result_degraded_is_data():
    assert not RecallResult().is_degraded
    result = RecallResult(
        items=[item()], degraded=[DegradedReason.SEMANTIC_CAPACITY], timings_ms={"lexical": 3.2},
    )
    assert result.is_degraded and result.items == (item(),) and result.timings_ms["lexical"] == 3.2
    with pytest.raises(TypeError):
        result.timings_ms["x"] = 1
    for kwargs, error in (
        ({"degraded": ("tencent_unavailable",)}, TypeError),
        ({"degraded": (DegradedReason.RECALL_TIMEOUT,) * 2}, ValueError),
        ({"items": ("x",)}, TypeError),
        ({"items": (item(),) * (mem.MAX_RECALL_ITEMS + 1)}, ValueError),
        ({"timings_ms": {"lexical": -1}}, ValueError),
    ):
        with pytest.raises(error):
            RecallResult(**kwargs)


# --------------------------------------------------------- candidate machine
def candidate(**over) -> Candidate:
    base = dict(
        id="c1", title="Likes tea", body="green", level=MemoryLevel.L1, kind=MemoryKind.PREFERENCE,
        retention=RetentionClass.LONG_TERM, scope="shared", confidence=0.9, evidence_hash="abc",
        created_at=NOW,
    )
    base.update(over)
    return Candidate(**base)


def test_candidate_state_machine_only_leaves_proposed():
    assert can_transition(CandidateState.PROPOSED, CandidateState.ACCEPTED)
    assert can_transition(CandidateState.PROPOSED, CandidateState.REJECTED)
    assert can_transition(CandidateState.PROPOSED, CandidateState.SUPERSEDED_BY_NEWER)
    for final in (CandidateState.ACCEPTED, CandidateState.REJECTED, CandidateState.SUPERSEDED_BY_NEWER):
        assert CANDIDATE_TRANSITIONS[final] == frozenset()
    assert [d.value for d in CandidateDecision] == ["accept", "reject"]


def test_candidate_invariants():
    assert candidate().state is CandidateState.PROPOSED
    decided = candidate(
        state=CandidateState.ACCEPTED, decided_at=NOW, decided_by="human", committed_memory_id="n9",
    )
    assert decided.committed_memory_id == "n9"
    for over in (
        {"state": CandidateState.REJECTED},
        {"decided_at": NOW, "decided_by": "human"},
        {"state": CandidateState.ACCEPTED, "decided_at": NOW, "decided_by": "human"},
        {"state": CandidateState.REJECTED, "decided_at": NOW, "decided_by": "human", "committed_memory_id": "n1"},
        {"evidence_hash": ""},
        {"confidence": -0.1},
    ):
        with pytest.raises(ValueError):
            candidate(**over)


def test_evidence_validation():
    assert Evidence(text="I like tea", source=prov(), scope="private").agent is None
    with pytest.raises(ValueError):
        Evidence(text=" ", source=prov(), scope="private")
    with pytest.raises(TypeError):
        Evidence(text="x", source="turn:1", scope="private")
    with pytest.raises(ValueError):
        Evidence(text="x" * (mem.MAX_EVIDENCE_CHARS + 1), source=prov(), scope="private")


# ----------------------------------------------------------------- capability
def test_capability_state_never_reads_ok_when_not_working():
    assert capability_ok().is_ok
    for status in (CapabilityStatus.DEGRADED, CapabilityStatus.DISABLED, CapabilityStatus.UNAVAILABLE):
        state = CapabilityState(status, reason_code="semantic_no_key", reason="No API key")
        assert not state.is_ok
        with pytest.raises(ValueError):
            CapabilityState(status)
    with pytest.raises(ValueError):
        CapabilityState(CapabilityStatus.OK, reason_code="x")
    with pytest.raises(ValueError):
        CapabilityState(CapabilityStatus.OK, reason="fine")
    with pytest.raises(ValueError):
        CapabilityState(CapabilityStatus.DEGRADED, reason_code="two words")


# --------------------------------------------------------------------- policy
# The table of docs/memory.md, cell by cell (L0, L1, L2, L3).
DOC_MATRIX = {
    RetentionClass.SHORT_TERM: ("L0", "L1", "L2"),
    RetentionClass.LONG_TERM: ("L1", "L2", "L3"),
    RetentionClass.PLASTIC: ("L1", "L2", "L3"),
    RetentionClass.TRAUMATIC: ("L1", "L2"),
    RetentionClass.ETERNAL: ("L1", "L2", "L3"),
}


def test_level_retention_matrix_is_exactly_the_documented_table():
    assert {r: {lv.value for lv in levels} for r, levels in LEVELS_BY_RETENTION.items()} == {
        r: set(levels) for r, levels in DOC_MATRIX.items()
    }
    for retention in RetentionClass:
        for level in MemoryLevel:
            if level.value in DOC_MATRIX[retention]:
                assert is_level_allowed(level, retention)
                check_level_retention(level, retention)
            else:
                assert not is_level_allowed(level, retention)
                with pytest.raises(ValueError, match=f"level {level.value} is not allowed in {retention.value}"):
                    check_level_retention(level, retention)


def test_level_retention_matrix():
    assert set(LEVELS_BY_RETENTION) == set(RetentionClass)
    for retention, levels in LEVELS_BY_RETENTION.items():
        assert (MemoryLevel.L0 in levels) is (retention is RetentionClass.SHORT_TERM)
        assert levels, retention
    assert is_level_allowed(MemoryLevel.L3, RetentionClass.ETERNAL)
    check_level_retention(MemoryLevel.L1, RetentionClass.TRAUMATIC)
    with pytest.raises(ValueError, match="L0 is not allowed in long_term_memory"):
        check_level_retention(MemoryLevel.L0, RetentionClass.LONG_TERM)
    with pytest.raises(ValueError):
        check_level_retention(MemoryLevel.L3, RetentionClass.TRAUMATIC)
    with pytest.raises(TypeError):
        LEVELS_BY_RETENTION[RetentionClass.ETERNAL] = frozenset()


def test_protected_classes_are_never_auto_commit_targets():
    assert PROTECTED_RETENTIONS == {RetentionClass.TRAUMATIC, RetentionClass.ETERNAL}
    assert not AUTO_COMMIT_RETENTIONS & PROTECTED_RETENTIONS
    assert AUTO_COMMIT_RETENTIONS == {RetentionClass.LONG_TERM, RetentionClass.PLASTIC}


def test_agent_policy_is_deny_by_scope():
    policy = AgentMemoryPolicy("coder", read_scopes=["shared", "project:jarvis"], write_scopes=["shared"])
    assert policy.can_read("shared") and not policy.can_read("private") and not policy.can_write("project:jarvis")
    assert policy.narrow(["private", "shared", "shared", "board:b1"]) == ("shared",)
    policy.check_read("shared")
    with pytest.raises(MemoryStoreError) as denied:
        policy.check_write("project:jarvis")
    assert denied.value.code is MemoryErrorCode.SCOPE_DENIED
    with pytest.raises(MemoryStoreError):
        policy.check_read("private")
    nothing = deny_all_policy("anyone")
    assert nothing.narrow(["shared", "private"]) == ()


@pytest.mark.parametrize("granted, near", [
    ("project:jarvis", "project:jarvis-secret"),
    ("project:jarvis", "project:jarvi"),
    ("board:b1", "board:b10"),
    ("board:b1", "board:b"),
    ("private", "private2"),
])
def test_scopes_match_exactly_never_by_prefix(granted, near):
    allow_private = granted == "private"
    policy = AgentMemoryPolicy(
        "a", read_scopes=(granted,), write_scopes=(granted,), allow_private=allow_private,
    )
    assert policy.can_read(granted) and policy.can_write(granted)
    if near != "private2":  # `private2` is not a valid scope at all: the narrow path refuses it
        assert not policy.can_read(near) and not policy.can_write(near)
        assert policy.narrow([near, granted]) == (granted,)
        with pytest.raises(MemoryStoreError):
            policy.check_read(near)
        with pytest.raises(MemoryStoreError):
            policy.check_write(near)
    else:
        assert not policy.can_read(near) and not policy.can_write(near)
        with pytest.raises(ValueError):
            policy.narrow([near])


def test_agent_policy_private_needs_explicit_opt_in_and_writes_are_readable():
    with pytest.raises(ValueError):
        AgentMemoryPolicy("coder", read_scopes=("private",))
    assert AgentMemoryPolicy("brain", read_scopes=("private",), allow_private=True).can_read("private")
    with pytest.raises(ValueError):
        AgentMemoryPolicy("coder", read_scopes=("shared",), write_scopes=("project:x",))
    with pytest.raises(ValueError):
        AgentMemoryPolicy("coder", read_scopes=("shared", "shared"))
    with pytest.raises(TypeError):
        AgentMemoryPolicy("coder", read_scopes="shared")
    with pytest.raises(dataclasses.FrozenInstanceError):
        deny_all_policy("x").agent_id = "y"


# ------------------------------------------------------------------ knowledge
def test_asset_and_source_ref_validation():
    asset = KnowledgeAsset(
        asset_id="wiki.memory", kind=AssetKind.WIKI, title="Memory", scope=AssetScope.PROJECT,
        source=source_ref(),
    )
    assert asset.body == "" and not asset.stale and asset.version == "1"
    with pytest.raises(dataclasses.FrozenInstanceError):
        asset.title = "x"
    for over, error in (
        ({"title": " "}, ValueError),
        ({"kind": "wiki"}, TypeError),
        ({"source": "docs"}, TypeError),
        ({"stale": 1}, TypeError),
        ({"summary": "x" * 1025}, ValueError),
        ({"asset_id": "a b"}, ValueError),
    ):
        with pytest.raises(error):
            dataclasses.replace(asset, **over)
    for over in ({"uri": ""}, {"version_or_commit": ""}, {"fetched_at": datetime(2026, 1, 1)}, {"line": 0}):
        with pytest.raises(ValueError):
            dataclasses.replace(source_ref(), **over)
    hit = AssetHit(asset=asset, snippet="memory", score=1)
    assert hit.asset is asset
    with pytest.raises(TypeError):
        AssetHit(asset="x", snippet="", score=1)


def test_loadout_denies_private_unless_explicit_and_freezes_reasons():
    reasons = {"scope:shared": "shared by default"}
    loadout = Loadout(profile="code", role="reviewer", memory_scopes=["shared"], skill_ids=["review"], reasons=reasons)
    reasons["x"] = "y"
    assert dict(loadout.reasons) == {"scope:shared": "shared by default"} and not loadout.is_empty
    with pytest.raises(TypeError):
        loadout.reasons["x"] = "y"
    assert Loadout(profile="fast").is_empty
    with pytest.raises(ValueError):
        Loadout(profile="code", memory_scopes=("private",))
    assert Loadout(profile="general", memory_scopes=("private",), allow_private=True).memory_scopes == ("private",)
    for over in ({"skill_ids": ("a", "a")}, {"memory_scopes": ("world",)}, {"wiki_ids": tuple(f"w{i}" for i in range(65))}):
        with pytest.raises(ValueError):
            Loadout(profile="code", **over)
    with pytest.raises(TypeError):
        Loadout(profile="code", wiki_ids="wiki")


def test_null_loadout_resolver_grants_nothing_and_conforms():
    resolver = NullLoadoutResolver()
    assert isinstance(resolver, LoadoutResolver)
    for profile, role in (("code", None), ("general", "research")):
        loadout = resolver.resolve(profile, role)
        assert loadout.is_empty and loadout.profile == profile and loadout.role == role
        assert not loadout.allow_private


# ------------------------------------------------------------------- settings
def test_settings_defaults_are_the_safe_local_configuration():
    settings = MemorySettings()
    assert settings.recall == RecallSettings(True, 6, 400)
    assert not settings.semantic.enabled and settings.semantic.provider is EmbeddingProviderId.NONE
    assert not settings.semantic.allow_private
    assert settings.consolidation.mode is ConsolidationMode.MANUAL
    assert not settings.tencent.enabled
    assert settings.knowledge.wiki_enabled and settings.knowledge.codegraph_enabled and settings.knowledge.skills_enabled
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.recall = RecallSettings()


@pytest.mark.parametrize("factory", [
    lambda: RecallSettings(max_items=0),
    lambda: RecallSettings(timeout_ms=99),
    lambda: RecallSettings(timeout_ms=1501),
    lambda: RecallSettings(enabled="yes"),
    lambda: SemanticSettings(provider="openai"),
    lambda: ConsolidationSettings(auto_min_confidence=1.5),
    lambda: ConsolidationSettings(max_candidates_per_run=0),
    lambda: TencentSettings(url="x" * 600),
    lambda: MemorySettings(recall={"enabled": True}),
])
def test_settings_field_validation(factory):
    with pytest.raises((ValueError, TypeError)):
        factory()


def test_settings_refuse_incompatible_combinations():
    with pytest.raises(ValueError, match="semantic.provider"):
        MemorySettings(semantic=SemanticSettings(enabled=True))
    with pytest.raises(ValueError, match="requires semantic.enabled"):
        MemorySettings(consolidation=ConsolidationSettings(mode=ConsolidationMode.AUTO))
    with pytest.raises(ValueError, match="tencent.url"):
        MemorySettings(tencent=TencentSettings(enabled=True, url="  "))
    semantic = SemanticSettings(enabled=True, provider=EmbeddingProviderId.OPENAI)
    ok = MemorySettings(
        semantic=semantic, consolidation=ConsolidationSettings(mode=ConsolidationMode.AUTO),
        tencent=TencentSettings(enabled=True, url="http://127.0.0.1:9000"),
    )
    assert ok.consolidation.mode is ConsolidationMode.AUTO
    with pytest.raises(ValueError) as several:
        MemorySettings(
            semantic=SemanticSettings(enabled=True), tencent=TencentSettings(enabled=True),
        )
    assert str(several.value).count(";") == 1


def test_settings_hold_no_secret_field():
    names = {field.name for cls in (TencentSettings, SemanticSettings) for field in dataclasses.fields(cls)}
    assert not {name for name in names if "key" in name or "token" in name or "secret" in name}


# ---------------------------------------------------------------- port fakes
class FakeStore:
    def __init__(self) -> None:
        self.notes: dict[str, list[MemoryNote]] = {}

    def get(self, memory_id):
        try:
            return self.notes[memory_id][-1]
        except KeyError:
            raise MemoryStoreError(MemoryErrorCode.NOT_FOUND, memory_id) from None

    def list(self, filters):
        return tuple(history[-1] for history in self.notes.values())[: filters.limit]

    def create(self, new):
        self.notes[new.id] = [new]
        return new

    def revise(self, memory_id, patch, expected_revision):
        current = self.get(memory_id)
        if current.revision != expected_revision:
            raise MemoryStoreError(MemoryErrorCode.CONFLICT_REVISION, f"at {current.revision}")
        revised = dataclasses.replace(current, revision=current.revision + 1, body=patch.body or current.body)
        self.notes[memory_id].append(revised)
        return revised

    def history(self, memory_id):
        self.get(memory_id)
        return tuple(self.notes[memory_id])

    def rebuild_indexes(self):
        return len(self.notes)


class FakeRetriever:
    capability_id = "lexical"

    async def recall(self, query, budget):
        return RecallResult(items=(item(),)[: budget.max_items], timings_ms={"lexical": 1.0})

    def status(self):
        return capability_ok()


class FakeEmbedder:
    model_id = "fake-1"
    dim = 3

    async def embed(self, texts, timeout):
        return [[0.0, 0.0, 1.0] for _ in texts]


class FakeConsolidator:
    def __init__(self) -> None:
        self.candidates: dict[str, Candidate] = {}

    async def propose(self, evidence):
        made = tuple(candidate(id=f"c{i}") for i, _ in enumerate(evidence))
        self.candidates.update({c.id: c for c in made})
        return made

    async def decide(self, candidate_id, decision, actor):
        current = self.candidates[candidate_id]
        if decision is CandidateDecision.REJECT:
            return dataclasses.replace(current, state=CandidateState.REJECTED, decided_at=NOW, decided_by=actor)
        return dataclasses.replace(
            current, state=CandidateState.ACCEPTED, decided_at=NOW, decided_by=actor, committed_memory_id="n1",
        )


class FakeExtractor:
    async def extract(self, evidence):
        return [{"title": "t", "body": "b"} for _ in evidence]


class FakeProvider:
    kind = AssetKind.WIKI

    def status(self):
        return capability_ok()

    def list(self, scope=None):
        return ()

    def search(self, query, limit, scope=None):
        return ()

    def read(self, asset_id):
        raise MemoryStoreError(MemoryErrorCode.NOT_FOUND, asset_id)

    def rebuild(self):
        return 0


def test_fakes_conform_to_every_port():
    assert isinstance(FakeStore(), CanonicalMemoryStore)
    assert isinstance(FakeRetriever(), MemoryRetriever) and isinstance(FakeRetriever(), CapabilityReporter)
    assert isinstance(FakeEmbedder(), EmbeddingProvider)
    assert isinstance(FakeConsolidator(), MemoryConsolidator)
    assert isinstance(FakeExtractor(), CandidateExtractor)
    assert isinstance(FakeProvider(), KnowledgeAssetProvider)
    assert not isinstance(object(), CanonicalMemoryStore)
    assert not isinstance(FakeRetriever(), CanonicalMemoryStore)


def test_store_contract_round_trip_with_optimistic_revision():
    store = FakeStore()
    created = store.create(note())
    revised = store.revise("n1", MemoryPatch(body="Prefers black tea."), expected_revision=1)
    assert revised.revision == 2 and [n.revision for n in store.history("n1")] == [1, 2]
    assert created.body == "Prefers green tea."  # a revision never edits the earlier one
    with pytest.raises(MemoryStoreError) as stale:
        store.revise("n1", MemoryPatch(body="x"), expected_revision=1)
    assert stale.value.code is MemoryErrorCode.CONFLICT_REVISION
    with pytest.raises(MemoryStoreError) as missing:
        store.get("nope")
    assert missing.value.code is MemoryErrorCode.NOT_FOUND
    assert store.list(MemoryFilters()) == (revised,) and store.rebuild_indexes() == 1


def test_retriever_embedder_and_consolidator_contracts_run():
    async def scenario():
        result = await FakeRetriever().recall(RecallQuery(text="tea", scopes=("shared",)), RecallBudget())
        vectors = await FakeEmbedder().embed(["a", "b"], timeout=0.2)
        consolidator = FakeConsolidator()
        proposed = await consolidator.propose([Evidence(text="I like tea", source=prov(), scope="private")])
        decided = await consolidator.decide(proposed[0].id, CandidateDecision.ACCEPT, "human")
        return result, vectors, proposed, decided

    result, vectors, proposed, decided = asyncio.run(scenario())
    assert result.items[0].memory_id == "n1" and not result.is_degraded
    assert len(vectors) == 2 and len(vectors[0]) == FakeEmbedder.dim
    assert proposed[0].state is CandidateState.PROPOSED and decided.state is CandidateState.ACCEPTED


def test_port_method_names_match_the_contract():
    def names(cls):
        return {name for name, _ in inspect.getmembers(cls) if not name.startswith("_")}

    assert {"get", "list", "create", "revise", "history", "rebuild_indexes"} <= names(CanonicalMemoryStore)
    assert {"recall", "status"} <= names(MemoryRetriever)
    assert {"model_id", "dim", "embed"} <= names(EmbeddingProvider)
    assert {"propose", "decide"} <= names(MemoryConsolidator)
    assert {"kind", "status", "list", "search", "read", "rebuild"} <= names(KnowledgeAssetProvider)
    assert "resolve" in names(LoadoutResolver)
    assert inspect.iscoroutinefunction(MemoryRetriever.recall)
    assert inspect.iscoroutinefunction(EmbeddingProvider.embed)
    assert not inspect.iscoroutinefunction(CanonicalMemoryStore.get)


# ------------------------------------------------------------ legacy and shape
def test_legacy_memory_backend_is_importable_and_unchanged():
    legacy = importlib.import_module("jarvis.ports.memory")
    backend = legacy.MemoryBackend
    members = {
        name: str(inspect.signature(fn))
        for name, fn in inspect.getmembers(backend, inspect.isfunction)
        if not name.startswith("_")
    }
    assert members == {
        "append_note": "(self, title: 'str', body: 'str') -> 'MemoryRecord'",
        "read": "(self, memory_id: 'str') -> 'MemoryRecord'",
        "rebuild_index": "(self) -> 'int'",
        "search": "(self, query: 'str', limit: 'int' = 5) -> 'list[MemoryHit]'",
    }
    results = importlib.import_module("jarvis.domain.results")
    assert [f.name for f in dataclasses.fields(results.MemoryRecord)] == ["memory_id", "title", "body"]
    assert [f.name for f in dataclasses.fields(results.MemoryHit)] == ["memory_id", "title", "snippet", "score"]


def test_markdown_adapter_still_offers_the_legacy_surface():
    from jarvis.adapters.markdown_memory import MarkdownMemoryBackend

    assert {"search", "read", "append_note", "rebuild_index"} <= set(dir(MarkdownMemoryBackend))
