"""What the Brain may do with memory on demand (handoff jarvis-memory-intelligence-knowledge, Slice 05b).

`BrainMemoryTools` is the Core side of the `jarvis-memory` MCP server
(`jarvis/runtime/memory_mcp.py`): `search`, `read`, `propose`, `knowledge_search`,
`knowledge_read`. It owns three rules and nothing else:

- **Budget.** At most `MAX_TOOL_CALLS_PER_TURN` (3) tool calls per Brain turn, counted here
  (the MCP process is stateless and could be bypassed). `MemoryTurnContext` calls `begin_turn`
  when a user turn starts; the 4th call answers `memory_tool_budget_exceeded`.
- **Scope.** Reads go through the Brain policy (`MemoryService.policy`, deny by scope):
  a note outside the readable scopes answers `memory_scope_denied`, never its text. Knowledge
  assets are limited to the Brain loadout (`MemoryService.knowledge_loadout`).
- **No durable write.** `propose` saves a `proposed` candidate in `_candidates/` and nothing
  else: it never creates, revises or supersedes a note. A human accepts it in the Memory Center.

A query is never logged: the diagnostics carry the tool name, counts and codes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any

from jarvis.core.memory_consolidation import candidate_id_for, validate_proposal, DropDiagnostic
from jarvis.core.memory_context import build_query
from jarvis.core.memory_service import MemoryService, canonical_text
from jarvis.domain.knowledge import AssetHit, AssetKind, KnowledgeAsset
from jarvis.domain.memory import (
    DEFAULT_RECALL_TIMEOUT_MS,
    MAX_QUERY_CHARS,
    Candidate,
    MemoryErrorCode,
    MemoryNote,
    MemoryStoreError,
    Provenance,
    RecallBudget,
    RecallItem,
    SHARED_SCOPE,
    SourceType,
)
from jarvis.ports.knowledge import KnowledgeAssetProvider
from jarvis.ports.memory_candidates import CandidateStore
from jarvis.ports.v2 import DiagnosticSink

#: Tool calls a Brain turn may make (architecture 2.6).
MAX_TOOL_CALLS_PER_TURN = 3
MAX_SEARCH_ITEMS = 8
MAX_READ_CHARS = 6_000
MAX_KNOWLEDGE_HITS = 8
MAX_KNOWLEDGE_READ_CHARS = 8_000
#: A candidate the Brain proposes starts below the auto-commit floor: a human decides.
MAX_PROPOSED_CONFIDENCE = 0.6
DEFAULT_PROPOSED_CONFIDENCE = 0.5
BRAIN_TOOL_REF = "brain:memory_propose"

BUDGET_CODE = "memory_tool_budget_exceeded"
#: Stable code when the proposal does not satisfy the candidate schema.
INVALID_PROPOSAL = "invalid_request"


class MemoryToolBudgetError(MemoryStoreError):
    """The turn's tool budget is spent. Carries a stable code for the route (HTTP 429)."""

    def __init__(self) -> None:
        self.tool_message = f"at most {MAX_TOOL_CALLS_PER_TURN} memory tool calls per turn: answer with what you have"
        super().__init__(MemoryErrorCode.UNAVAILABLE, f"{BUDGET_CODE}: {self.tool_message}")
        self.tool_code = BUDGET_CODE


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    items: tuple[RecallItem, ...] = ()
    degraded: tuple[str, ...] = ()
    calls_left: int = 0


@dataclass(frozen=True, slots=True)
class KnowledgeOutcome:
    hits: tuple[AssetHit, ...] = ()
    degraded: tuple[str, ...] = ()
    calls_left: int = 0


class BrainMemoryTools:
    def __init__(
        self,
        service: MemoryService,
        candidates: CandidateStore | None,
        knowledge: Mapping[AssetKind, KnowledgeAssetProvider] | None,
        *,
        diagnostics: DiagnosticSink | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._service = service
        self._candidates = candidates
        self._knowledge = knowledge if knowledge is not None else {}
        self._diagnostics = diagnostics
        self._clock = clock
        self._calls = 0

    # ------------------------------------------------------------------ budget
    def begin_turn(self) -> None:
        self._calls = 0

    @property
    def calls_left(self) -> int:
        return max(0, MAX_TOOL_CALLS_PER_TURN - self._calls)

    def _charge(self, tool: str) -> None:
        if self._calls >= MAX_TOOL_CALLS_PER_TURN:
            self._emit("core.memory.tool_refused", tool, code=BUDGET_CODE)
            raise MemoryToolBudgetError()
        self._calls += 1

    def _emit(self, event: str, tool: str, **data: Any) -> None:
        if self._diagnostics is not None:
            self._diagnostics.emit(event, f"Outil mémoire du cerveau : {tool}", level="info", data={"tool": tool, **data})

    # ------------------------------------------------------------------ memory
    async def search(self, query: str, limit: int = MAX_SEARCH_ITEMS) -> SearchOutcome:
        self._charge("memory_search")
        words = build_query(query)
        if not words:
            raise ValueError("query has no searchable word")
        budget = RecallBudget(max_items=max(1, min(limit, MAX_SEARCH_ITEMS)), timeout_ms=DEFAULT_RECALL_TIMEOUT_MS)
        recalled = await self._service.recall_for_turn(words, budget)
        self._emit("core.memory.tool_called", "memory_search", items=len(recalled.result.items),
                   degraded=list(recalled.degraded))
        return SearchOutcome(recalled.result.items, recalled.degraded, self.calls_left)

    async def read(self, memory_id: str) -> tuple[MemoryNote, str, bool, int]:
        """`(note, canonical text clipped, clipped?, calls left)`. A scope the policy does not grant is refused."""

        self._charge("memory_read")
        note = await self._service.get_note(memory_id)
        self._service.policy.check_read(note.scope)
        text = canonical_text(note)
        clipped = len(text) > MAX_READ_CHARS
        self._emit("core.memory.tool_called", "memory_read", clipped=clipped)
        return note, text[:MAX_READ_CHARS], clipped, self.calls_left

    async def propose(self, raw: Mapping[str, Any], scope: str | None = None) -> tuple[Candidate, bool, int]:
        """Save one `proposed` candidate; `(candidate, already_known, calls left)`.

        The proposal is validated by the consolidation schema (`validate_proposal`: no protected class, no
        state, no id). Its scope must be one the Brain policy reads; its confidence is capped.
        """

        self._charge("memory_propose")
        if self._candidates is None:
            raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "candidate store is not available")
        data = dict(raw)
        confidence = data.setdefault("confidence", DEFAULT_PROPOSED_CONFIDENCE)
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            data["confidence"] = min(confidence, MAX_PROPOSED_CONFIDENCE)
        checked = validate_proposal(data, 0)
        if isinstance(checked, DropDiagnostic):
            raise ValueError(f"proposal refused: {checked.code}")
        granted = self._service.policy.narrow(self._service.policy.read_scopes)
        chosen = scope or (SHARED_SCOPE if SHARED_SCOPE in granted else (granted[0] if granted else ""))
        if chosen not in granted:
            raise MemoryStoreError(MemoryErrorCode.SCOPE_DENIED, "the Brain may not propose into that scope")
        now = self._clock()
        digest = hashlib.sha256(f"{BRAIN_TOOL_REF}\0{chosen}\0{checked.title}\0{checked.body}".encode("utf-8")).hexdigest()
        candidate = Candidate(
            id=candidate_id_for(digest, checked.title, checked.body), title=checked.title, body=checked.body,
            level=checked.level, kind=checked.kind, retention=checked.retention, scope=chosen,
            confidence=checked.confidence, evidence_hash=digest, created_at=now,
            sources=(Provenance(SourceType.TURN, BRAIN_TOOL_REF, now),))
        try:
            known = await asyncio.to_thread(self._candidates.get, candidate.id)
        except MemoryStoreError as exc:
            if exc.code is not MemoryErrorCode.NOT_FOUND:
                raise
            known = None
        if known is not None:
            self._emit("core.memory.tool_called", "memory_propose", already_known=True)
            return known, True, self.calls_left
        await asyncio.to_thread(self._candidates.save, candidate)
        self._emit("core.memory.tool_called", "memory_propose", already_known=False, kind=candidate.kind.value)
        return candidate, False, self.calls_left

    # --------------------------------------------------------------- knowledge
    def _allowed(self, kind: AssetKind, asset_id: str) -> bool:
        loadout = self._service.knowledge_loadout()
        ids = {AssetKind.WIKI: loadout.wiki_ids, AssetKind.SKILL: loadout.skill_ids,
               AssetKind.CODEGRAPH: loadout.codegraph_repos}[kind]
        return asset_id in ids

    async def knowledge_search(self, query: str, kind: AssetKind | None = None,
                               limit: int = MAX_KNOWLEDGE_HITS) -> KnowledgeOutcome:
        self._charge("knowledge_search")
        if not query.strip() or len(query) > MAX_QUERY_CHARS:
            raise ValueError("query must be 1 to %d characters" % MAX_QUERY_CHARS)
        limit = max(1, min(limit, MAX_KNOWLEDGE_HITS))
        providers = [(k, p) for k, p in self._knowledge.items() if kind is None or k is kind]
        hits: list[AssetHit] = []
        degraded: list[str] = []
        for provider_kind, provider in providers:
            try:
                found: Sequence[AssetHit] = await asyncio.to_thread(provider.search, query, limit * 3)
            except Exception as exc:  # noqa: BLE001 - a provider fails alone: its kind is reported degraded, others answer
                degraded.append(f"knowledge_{provider_kind.value}_unavailable")
                self._emit("core.memory.tool_provider_failed", "knowledge_search", exception_type=type(exc).__name__)
                continue
            hits.extend(hit for hit in found if self._allowed(provider_kind, hit.asset.asset_id))
        hits.sort(key=lambda hit: -float(hit.score))
        self._emit("core.memory.tool_called", "knowledge_search", hits=len(hits[:limit]), degraded=degraded)
        return KnowledgeOutcome(tuple(hits[:limit]), tuple(degraded), self.calls_left)

    async def knowledge_read(self, kind: AssetKind, asset_id: str) -> tuple[KnowledgeAsset, str, bool, int]:
        self._charge("knowledge_read")
        provider = self._knowledge.get(kind)
        if provider is None:
            raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, f"knowledge {kind.value} is not available")
        if not self._allowed(kind, asset_id):
            raise MemoryStoreError(MemoryErrorCode.SCOPE_DENIED, "that asset is not in the Brain loadout")
        asset = await asyncio.to_thread(provider.read, asset_id)
        clipped = len(asset.body) > MAX_KNOWLEDGE_READ_CHARS
        self._emit("core.memory.tool_called", "knowledge_read", kind=kind.value, clipped=clipped)
        return asset, asset.body[:MAX_KNOWLEDGE_READ_CHARS], clipped, self.calls_left


__all__ = ["BUDGET_CODE", "MAX_TOOL_CALLS_PER_TURN", "BrainMemoryTools", "KnowledgeOutcome", "MemoryToolBudgetError",
           "SearchOutcome"]
