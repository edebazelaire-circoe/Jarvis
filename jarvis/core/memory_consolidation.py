"""Consolidation pipeline: evidence -> candidates -> policy gate -> canonical notes (Slice 04).

    L0 evidence
      -> CandidateExtractor            (LLM in production, a fake in tests; output is untrusted)
      -> schema validation             (untrusted Mappings; malformed ones dropped with a diagnostic)
      -> dedup                         (lexical + semantic similarity vs notes and pending candidates)
      -> conflict detection            (related notes of the same kind; extractor hints are hints only)
      -> scoring                       (extractor confidence, capped when the evidence looks hostile)
      -> policy gate                   (manual: a human decides; auto: confidence + no conflict)

State machine of a candidate (`jarvis.domain.memory`): `proposed -> accepted |
rejected | superseded_by_newer`; the three others are final. `accepted`
commits one canonical note with provenance. Deciding actors: a human (any
actor not `system.*`) or the pipeline (`SYSTEM_ACTOR`, for `superseded_by_newer`,
for an `auto` commit and for a duplicate found at the gate).

Invariants (risk R5, architecture 2.5 and 2.7):

- `manual` (default) commits nothing: every candidate waits for `decide`.
- `auto` commits only a candidate with `confidence >= auto_min_confidence`
  (and >= `AUTO_FLOOR`), no conflict, retention in `long_term_memory` or
  `plastic_memory`, a level the class allows, and at least one source. It
  never writes a protected class and never rewrites or supersedes anything.
- The extractor cannot choose a scope (the evidence's scope is the candidate's
  scope: private evidence never yields a shared note), cannot target a protected
  class, cannot set a state, an id or a decision. Anything outside the schema
  drops the proposal.
- A conflicting candidate is never auto-committed. On a human accept, a
  `preference` or `profile` newer than the old note supersedes it (old note:
  `valid_to` closed, `superseded_by` set, revision kept in `.history/`); any
  other kind, a stale candidate or a protected old note is linked `contradicts`
  and both stay valid. Nothing is ever overwritten.
- Runs are idempotent per evidence hash; candidate ids and committed note ids
  are derived from content, so a replay converges instead of duplicating.
- A crash between the canonical commit and the candidate update is completed by
  `recover` (decision intent written first), with the original actor.

The pipeline imports ports and domain only: the store, the candidate store, the
retriever and the embedder are injected. Contract page: `docs/memory.md`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import re
import unicodedata
from typing import Any

from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.memory import (
    MAX_LINKS,
    MAX_SOURCES,
    MAX_TITLE_CHARS,
    Candidate,
    CandidateDecision,
    CandidateState,
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
    RecallQuery,
    RetentionClass,
    SourceType,
    can_transition,
)
from jarvis.domain.memory_policy import (
    AUTO_COMMIT_RETENTIONS,
    check_level_retention,
    is_level_allowed,
    is_protected,
)
from jarvis.domain.memory_settings import ConsolidationMode, ConsolidationSettings
from jarvis.ports.memory_candidates import CandidateStore, DecisionIntent
from jarvis.ports.memory_consolidation import CandidateExtractor, RelatedNote
from jarvis.ports.memory_retrieval import EmbeddingProvider, MemoryRetriever
from jarvis.ports.memory_store import CanonicalMemoryStore

_LOG = logging.getLogger("jarvis")

#: Actor of every decision the pipeline takes itself. Public `decide` refuses it.
SYSTEM_ACTOR = "system.consolidation"
#: Auto never commits below this, whatever the knob says (a suspect candidate is capped under it).
AUTO_FLOOR = 0.5
SUSPECT_CAP = 0.4

#: Lexical similarity (Jaccard of normalised tokens) at or above which a candidate repeats a note.
DUPLICATE_SIMILARITY = 0.8
#: Related enough, with the same kind, to be a possible contradiction (human review).
CONFLICT_SIMILARITY = 0.5
#: Embedding cosine that widens the review band (never drops anything on its own).
SEMANTIC_CONFLICT_COSINE = 0.9
#: Embedding cosine that, with some lexical overlap, makes a duplicate.
SEMANTIC_DUPLICATE_COSINE = 0.97
SEMANTIC_DUPLICATE_MIN_JACCARD = 0.5

#: Kinds describing a current state: a newer one replaces the older (temporal supersession).
TEMPORAL_KINDS = frozenset({MemoryKind.PREFERENCE, MemoryKind.PROFILE})

MAX_CANDIDATE_BODY_CHARS = 4_000
MAX_HINTS = 8
MAX_RAW_PROPOSALS = 200
#: Notes compared against per candidate (newest first) and embedded per semantic check.
MAX_NEIGHBOURS = 200
#: Related notes pulled by full-text search / the retriever, beyond the newest `MAX_NEIGHBOURS`.
MAX_WIDENED_NEIGHBOURS = 30
#: Notes shown to the extractor as citable data, and evidence per extraction call (the adapter refuses more).
MAX_RELATED_FOR_PROMPT = 8
EXTRACT_BATCH_SIZE = 40
EXTRACT_BATCH_CHARS = 60_000
MAX_SEMANTIC_NEIGHBOURS = 50
DEFAULT_EXTRACT_TIMEOUT_S = 120.0
EMBED_TIMEOUT_S = 5.0

_ALLOWED_KEYS = frozenset({"title", "body", "kind", "level", "retention", "confidence", "supersedes", "reason"})
_PROPOSABLE_RETENTIONS = frozenset({RetentionClass.SHORT_TERM, RetentionClass.LONG_TERM, RetentionClass.PLASTIC})
#: Short-term notes are the evidence pool (a candidate extracted from one would otherwise "duplicate"
#: its own source): dedup and conflict detection compare against durable notes only.
_EVIDENCE_RETENTION = RetentionClass.SHORT_TERM
_DURABLE_RETENTIONS = tuple(item for item in RetentionClass if item is not _EVIDENCE_RETENTION)
_DEFAULT_LEVEL = {
    MemoryKind.PROFILE: MemoryLevel.L3, MemoryKind.SCENARIO: MemoryLevel.L2,
}
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_CANDIDATE_ID = re.compile(r"[A-Za-z0-9]{1,64}\Z")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_PATH_LIKE = re.compile(r"(^|[\\/])\.\.([\\/]|$)|^[\\/~]|^[A-Za-z]:")
_STOPWORDS = frozenset(
    "a an the i me my is are was were be to of in on at and or for with it this that "
    "le la les un une des de du et ou en au aux je mon ma mes est sont a ce cette ces".split()
)
#: Instruction-like text inside evidence. Heuristic defence in depth: the policy never reads
#: evidence text, this only caps the score of what such text produced.
_INJECTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above|earlier)|disregard (the |all |any )?(previous|above|instructions)"
    r"|system prompt|you are now|new instructions|auto[- ]?accept|set (the )?confidence|confidence\s*[:=]"
    r"|override (the )?(policy|gate|rules)|developer mode|jailbreak"
    r"|ignore (toutes )?les instructions|instructions pr[eé]c[eé]dentes|oublie (toutes )?les instructions",
    re.IGNORECASE,
)

Sink = Callable[[str, Mapping[str, Any]], None]


def _log_sink(event: str, data: Mapping[str, Any]) -> None:
    _LOG.info("%s %s", event, dict(data))


# ----------------------------------------------------------------------- report
@dataclass(frozen=True, slots=True)
class DropDiagnostic:
    """One proposal that did not become a candidate, and why (never carries evidence text)."""

    index: int
    code: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ConsolidationReport:
    """What one `run` did. Counts and ids only."""

    mode: str
    candidates: tuple[Candidate, ...] = ()
    committed: tuple[str, ...] = ()
    dropped: tuple[DropDiagnostic, ...] = ()
    duplicates: tuple[tuple[str, str], ...] = ()
    superseded_candidates: tuple[str, ...] = ()
    skipped_groups: int = 0
    deferred_groups: int = 0
    failed_groups: int = 0
    recovered: int = 0
    errors: tuple[str, ...] = ()
    #: Why the run was weaker than asked (`auto_needs_dedup`, `memory_unavailable`): data, not an exception.
    degraded: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "candidates": len(self.candidates), "committed": list(self.committed),
            "dropped": [{"index": d.index, "code": d.code} for d in self.dropped],
            "duplicates": len(self.duplicates), "superseded_candidates": len(self.superseded_candidates),
            "skipped_groups": self.skipped_groups, "deferred_groups": self.deferred_groups,
            "failed_groups": self.failed_groups, "recovered": self.recovered, "errors": list(self.errors),
            "degraded": list(self.degraded),
        }


@dataclass(slots=True)
class _Progress:
    """Mutable accumulator of one run."""

    candidates: list[Candidate] = field(default_factory=list)
    committed: list[str] = field(default_factory=list)
    dropped: list[DropDiagnostic] = field(default_factory=list)
    duplicates: list[tuple[str, str]] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    skipped: int = 0
    deferred: int = 0
    failed: int = 0
    recovered: int = 0
    errors: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)

    def freeze(self, mode: str) -> ConsolidationReport:
        return ConsolidationReport(
            mode, tuple(self.candidates), tuple(self.committed), tuple(self.dropped), tuple(self.duplicates),
            tuple(self.superseded), self.skipped, self.deferred, self.failed, self.recovered, tuple(self.errors),
            tuple(self.degraded),
        )


@dataclass(frozen=True, slots=True)
class _Proposal:
    """A schema-valid extractor proposal (still a proposal, not a candidate)."""

    title: str
    body: str
    kind: MemoryKind
    level: MemoryLevel
    retention: RetentionClass
    confidence: float
    hints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Assessment:
    duplicate_of: str | None = None
    conflicts: tuple[str, ...] = ()
    replaced_pending: tuple[str, ...] = ()
    stale: bool = False


# --------------------------------------------------------------------- pure helpers
def is_system_actor(actor: str) -> bool:
    """`system`, `system.*` in any case or Unicode spelling: never passes as a human."""

    if not isinstance(actor, str):
        return False
    folded = unicodedata.normalize("NFKC", actor).strip().casefold()
    return folded == "system" or folded.startswith("system.")


def evidence_hash(evidence: Sequence[Evidence]) -> str:
    """Idempotence key of a group of evidence: text, scope and source identity, order-free."""

    items = sorted([item.scope, item.text, item.source.type.value, item.source.ref] for item in evidence)
    raw = json.dumps(["v1", items], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def similarity_tokens(title: str, body: str) -> frozenset[str]:
    return frozenset(t for t in _WORD.findall(_normalise(f"{title} {body}")) if t not in _STOPWORDS)


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


def candidate_id_for(evidence_hash_: str, title: str, body: str) -> str:
    """Deterministic: the same evidence and the same proposal are the same candidate."""

    raw = "\0".join((evidence_hash_, " ".join(_normalise(title).split()), " ".join(_normalise(body).split())))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def note_id_for(candidate_id: str) -> str:
    """Deterministic note id: a replayed commit finds its own note instead of duplicating it."""

    return hashlib.sha256(f"note:{candidate_id}".encode("ascii")).hexdigest()[:32]


def looks_hostile(evidence: Iterable[Evidence]) -> bool:
    return any(_INJECTION.search(item.text) for item in evidence)


def score_candidate(confidence: float, *, suspect: bool) -> float:
    """Candidate score: the extractor's confidence, capped when the evidence reads like an injection.

    Deliberately thin: the policy gate, not the score, is the safety mechanism.
    """

    score = min(max(confidence, 0.0), 1.0)
    if suspect:
        score = min(score, SUSPECT_CAP)
    return round(score, 4)


def evidence_time(sources: Sequence[Provenance], fallback: datetime) -> datetime:
    return max((s.at for s in sources), default=fallback)


def validate_proposal(raw: object, index: int) -> _Proposal | DropDiagnostic:
    """Schema-check one untrusted proposal. Never raises; anything off-schema is a `DropDiagnostic`."""

    def drop(code: str, detail: str = "") -> DropDiagnostic:
        return DropDiagnostic(index, code, detail[:120])

    if not isinstance(raw, Mapping):
        return drop("not_a_mapping", type(raw).__name__)
    try:
        keys = list(raw.keys())
    except Exception:  # noqa: BLE001 - a hostile Mapping may raise anywhere; it is dropped, never trusted
        return drop("unreadable_mapping")
    if not all(isinstance(key, str) for key in keys):
        return drop("non_string_key")
    unknown = sorted(set(keys) - _ALLOWED_KEYS)
    if unknown:
        return drop("unknown_fields", ", ".join(key[:24] for key in unknown[:5]))

    title = raw.get("title")
    if not isinstance(title, str) or len(title) > 4 * MAX_TITLE_CHARS:
        return drop("bad_title")
    title = " ".join(title.split())
    if not title or len(title) > MAX_TITLE_CHARS or not title.isprintable():
        return drop("bad_title")
    if _PATH_LIKE.search(title):
        return drop("title_path_like")

    body = raw.get("body", "")
    if not isinstance(body, str) or len(body) > 2 * MAX_CANDIDATE_BODY_CHARS:
        return drop("bad_body")
    body = body.replace("\r\n", "\n").strip()
    if len(body) > MAX_CANDIDATE_BODY_CHARS or "\x00" in body:
        return drop("bad_body")

    try:
        kind = MemoryKind(raw.get("kind", MemoryKind.FACT.value))
    except (ValueError, TypeError):
        return drop("bad_kind")
    default_level = _DEFAULT_LEVEL.get(kind, MemoryLevel.L1)
    try:
        level = MemoryLevel(raw.get("level", default_level.value))
        retention = RetentionClass(raw.get("retention", RetentionClass.LONG_TERM.value))
    except (ValueError, TypeError):
        return drop("bad_level_or_retention")
    if level is MemoryLevel.L0:
        return drop("level_l0", "L0 is evidence, not a candidate")
    if retention not in _PROPOSABLE_RETENTIONS:
        return drop("protected_class" if is_protected(retention) else "bad_retention", retention.value)
    if not is_level_allowed(level, retention):
        return drop("level_retention_violation", f"{level.value} in {retention.value}")

    confidence = raw.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return drop("bad_confidence")
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        return drop("bad_confidence")

    hints_raw = raw.get("supersedes", ())
    if isinstance(hints_raw, (str, bytes)) or not isinstance(hints_raw, (list, tuple)) or len(hints_raw) > MAX_HINTS:
        return drop("bad_hints")
    if not all(isinstance(item, str) and _TOKEN.fullmatch(item) for item in hints_raw):
        return drop("bad_hints")
    reason = raw.get("reason", "")
    if not isinstance(reason, str) or len(reason) > 1_000:
        return drop("bad_reason")
    return _Proposal(title, body, kind, level, retention, float(confidence), tuple(dict.fromkeys(hints_raw)))


def gate_auto(candidate: Candidate, settings: ConsolidationSettings) -> str | None:
    """Why `auto` must NOT commit `candidate`, or `None` when it may. Pure: the whole policy gate.

    Evidence text never reaches this function.
    """

    if settings.mode is not ConsolidationMode.AUTO:
        return "mode_manual"
    if candidate.state is not CandidateState.PROPOSED:
        return "not_proposed"
    if candidate.confidence < max(settings.auto_min_confidence, AUTO_FLOOR):
        return "below_threshold"
    if candidate.conflicts:
        return "has_conflicts"
    if candidate.retention not in AUTO_COMMIT_RETENTIONS or is_protected(candidate.retention):
        return "retention_not_auto"
    if not is_level_allowed(candidate.level, candidate.retention):
        return "level_retention_violation"
    if not candidate.sources:
        return "no_provenance"
    return None


# ---------------------------------------------------------------------- pipeline
class ConsolidationPipeline:
    """`MemoryConsolidator` (`propose`, `decide`) plus `run`, `recover` and the candidate queue."""

    def __init__(
        self,
        *,
        store: CanonicalMemoryStore,
        candidates: CandidateStore,
        extractor: CandidateExtractor,
        settings: ConsolidationSettings | Callable[[], ConsolidationSettings] = ConsolidationSettings(),
        retriever: MemoryRetriever | None = None,
        embedder: EmbeddingProvider | None = None,
        sink: Sink = _log_sink,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        extract_timeout_s: float = DEFAULT_EXTRACT_TIMEOUT_S,
    ) -> None:
        self._store = store
        self._cands = candidates
        self._extractor = extractor
        self._settings = settings if callable(settings) else (lambda: settings)
        self._retriever = retriever
        self._embedder = embedder
        self._sink = sink
        self._clock = clock
        self._extract_timeout_s = extract_timeout_s
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ public port
    async def propose(self, evidence: Sequence[Evidence]) -> tuple[Candidate, ...]:
        """Candidates for this evidence (new and already known). Idempotent per evidence hash."""

        return (await self.run(evidence)).candidates

    async def decide(self, candidate_id: str, decision: CandidateDecision, actor: str) -> Candidate:
        """Human decision on a `proposed` candidate. `memory_not_found` when unknown.

        An already decided candidate answers the same decision with itself (a retry is
        harmless) and any other decision with `memory_conflict_revision`. The `system.`
        actors belong to the pipeline: refused here with `memory_scope_denied`.
        """

        if not isinstance(decision, CandidateDecision):
            raise TypeError("decision must be a CandidateDecision")
        if not isinstance(actor, str) or not _TOKEN.fullmatch(actor):
            raise ValueError("actor must be a short token")
        if is_system_actor(actor):
            raise MemoryStoreError(MemoryErrorCode.SCOPE_DENIED, "system actors decide through the pipeline only")
        if not isinstance(candidate_id, str) or not _CANDIDATE_ID.fullmatch(candidate_id):
            raise MemoryStoreError(MemoryErrorCode.NOT_FOUND, "no such candidate")
        async with self._lock:
            try:
                return await asyncio.to_thread(self._decide_sync, candidate_id, decision, actor)
            except MemorySecurityError as exc:
                raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, f"candidate store refused its path: {exc}") from exc

    async def recover(self) -> int:
        """Complete decisions announced but not finished (crash between commit and update)."""

        async with self._lock:
            progress = _Progress()
            await asyncio.to_thread(self._recover_sync, progress)
            return progress.recovered

    async def candidates(self, state: CandidateState | None = None, limit: int = 500) -> tuple[Candidate, ...]:
        """The review queue (for Core routes: list)."""

        return tuple(await asyncio.to_thread(self._cands.list, state, limit))

    async def candidate(self, candidate_id: str) -> Candidate:
        return await asyncio.to_thread(self._cands.get, candidate_id)

    async def run(self, evidence: Sequence[Evidence]) -> ConsolidationReport:
        """One consolidation pass. Never raises for a refused path (a link in the memory root):
        that is a degraded report (`memory_unavailable`), like the worker's own boundary."""

        requested = self._settings()
        settings = requested
        progress = _Progress()
        if requested.mode is ConsolidationMode.AUTO and self._retriever is None and self._embedder is None:
            # Without a retriever or an embedder, dedup and conflicts only see the newest notes and the
            # full-text hits: auto would commit on a partial view. Propose, never commit.
            settings = replace(requested, mode=ConsolidationMode.MANUAL)
            progress.degraded.append("auto_needs_dedup")
            self._emit("memory.consolidation.auto_refused", {"reason": "no_retriever_or_embedder"})
        async with self._lock:
            try:
                await self._run_locked(evidence, settings, progress)
            except MemorySecurityError as exc:
                progress.degraded.append("memory_unavailable")
                progress.errors.append(f"memory_security:{type(exc).__name__}")
                self._emit("memory.consolidation.refused_path", {"error": type(exc).__name__})
        report = progress.freeze(requested.mode.value)
        self._emit("memory.consolidation.run", report.to_payload())
        return report

    async def _run_locked(self, evidence: Sequence[Evidence], settings: ConsolidationSettings, progress: _Progress) -> None:
        await asyncio.to_thread(self._recover_sync, progress)
        budget = settings.max_candidates_per_run
        produced = 0
        for scope, items in self._group(evidence):
            # The idempotence unit is one evidence item: only the unseen ones reach the extractor.
            fresh: list[Evidence] = []
            known_ids: dict[str, None] = {}
            for item in items:
                marker = await asyncio.to_thread(self._cands.run_candidates, evidence_hash([item]))
                if marker is None:
                    fresh.append(item)
                else:
                    known_ids.update(dict.fromkeys(marker))
            if known_ids:
                # Already processed: listed, never settled. `auto` only commits what THIS run created, so
                # a backlog left waiting (manual mode, a refused auto) stays for a human.
                progress.skipped += 1
                progress.candidates.extend(await asyncio.to_thread(self._load_known, tuple(known_ids)))
            for batch in self._batches(fresh):
                if produced >= budget:
                    progress.deferred += 1
                    self._emit("memory.consolidation.deferred", {"scope_kind": scope.partition(":")[0]})
                    continue
                produced += await self._process_group(scope, batch, budget - produced, settings, progress)
        progress.candidates = list({item.id: item for item in progress.candidates}.values())

    @staticmethod
    def _batches(items: Sequence[Evidence]) -> list[list[Evidence]]:
        """Chunks the extractor can take whole (count and characters), so no evidence is cut off unprocessed."""

        batches: list[list[Evidence]] = []
        current: list[Evidence] = []
        size = 0
        for item in items:
            if current and (len(current) >= EXTRACT_BATCH_SIZE or size + len(item.text) > EXTRACT_BATCH_CHARS):
                batches.append(current)
                current, size = [], 0
            current.append(item)
            size += len(item.text)
        if current:
            batches.append(current)
        return batches

    # ------------------------------------------------------------- one group
    @staticmethod
    def _group(evidence: Sequence[Evidence]) -> list[tuple[str, list[Evidence]]]:
        groups: dict[str, list[Evidence]] = {}
        for item in evidence:
            if not isinstance(item, Evidence):
                raise TypeError("evidence must hold Evidence values only")
            groups.setdefault(item.scope, []).append(item)
        return list(groups.items())

    async def _process_group(
        self, scope: str, items: list[Evidence], room: int, settings: ConsolidationSettings, progress: _Progress,
    ) -> int:
        digest = evidence_hash(items)
        related = await self._related_notes(scope, items)
        try:
            raw = await asyncio.wait_for(self._extractor.extract(tuple(items), related=related), self._extract_timeout_s)
        except Exception as exc:  # noqa: BLE001 - extractor boundary: any failure leaves the group unmarked (retried next run)
            progress.failed += 1
            progress.errors.append(f"extractor_failed:{type(exc).__name__}")
            self._emit("memory.consolidation.extractor_failed", {"error": type(exc).__name__, "evidence": len(items)})
            return 0
        if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Sequence):
            progress.failed += 1
            progress.errors.append("extractor_output_not_a_list")
            self._emit("memory.consolidation.dropped", {"code": "extractor_output_not_a_list"})
            return 0
        limit = min(MAX_RAW_PROPOSALS, max(4 * room, 8))
        if len(raw) > limit:
            self._drop(progress, DropDiagnostic(-1, "extractor_output_truncated", f"{len(raw)} > {limit}"))
        valid: list[_Proposal] = []
        for index, item in enumerate(raw[:limit]):
            checked = validate_proposal(item, index)
            if isinstance(checked, DropDiagnostic):
                self._drop(progress, checked)
            else:
                valid.append(checked)
        valid.sort(key=lambda proposal: -proposal.confidence)
        suspect = looks_hostile(items)
        if suspect:
            self._emit("memory.consolidation.injection_suspected", {"evidence": len(items)})
        sources = tuple(sorted((item.source for item in items), key=lambda s: (s.at, s.type.value, s.ref))[:MAX_SOURCES])
        now = self._clock()
        made: list[Candidate] = []
        produced = 0
        overflow = 0
        for proposal in valid:
            if produced >= room:
                overflow += 1
                self._drop(progress, DropDiagnostic(-1, "cap_reached", "kept for the next run"))
                continue
            candidate = Candidate(
                id=candidate_id_for(digest, proposal.title, proposal.body), title=proposal.title,
                body=proposal.body, level=proposal.level, kind=proposal.kind, retention=proposal.retention,
                scope=scope, confidence=score_candidate(proposal.confidence, suspect=suspect),
                evidence_hash=digest, created_at=now, sources=sources,
            )
            known = await asyncio.to_thread(self._known_candidate, candidate.id)
            if known is not None:
                made.append(known)  # a replay of an earlier, interrupted run: same proposal, same file
                continue
            assessment = await self._assess(candidate, proposal.hints, progress)
            if assessment.duplicate_of is not None:
                progress.duplicates.append((candidate.id, assessment.duplicate_of))
                self._emit("memory.consolidation.duplicate", {"candidate": candidate.id, "of": assessment.duplicate_of})
                continue
            if assessment.stale:
                self._drop(progress, DropDiagnostic(-1, "stale_vs_pending", candidate.id))
                continue
            for pending_id in assessment.replaced_pending:
                await asyncio.to_thread(self._supersede_pending, pending_id, progress)
            candidate = replace(candidate, conflicts=assessment.conflicts[:MAX_LINKS])
            await asyncio.to_thread(self._cands.save, candidate)
            made.append(candidate)
            produced += 1
            self._emit("memory.consolidation.proposed", {
                "candidate": candidate.id, "conflicts": len(candidate.conflicts), "confidence": candidate.confidence,
            })
        progress.candidates.extend(made)
        settled = await self._settle(made, settings, progress)
        if not settled:
            progress.deferred += 1
            return produced
        if overflow:
            # Proposals beyond the cap were not written: leave the evidence unmarked so the next run
            # extracts again (the candidates already written are recognised by id, not counted again).
            progress.deferred += 1
            self._emit("memory.consolidation.overflow", {"kept_for_next_run": overflow})
            return produced
        made_ids = [item.id for item in made]
        await asyncio.to_thread(self._cands.mark_run, digest, made_ids)
        for item in items:
            if len(items) > 1:
                await asyncio.to_thread(self._cands.mark_run, evidence_hash([item]), made_ids)
        return produced

    def _load_known(self, ids: Sequence[str]) -> list[Candidate]:
        found = []
        for candidate_id in ids:
            known = self._known_candidate(candidate_id)
            if known is not None:
                found.append(known)
        return found

    def _known_candidate(self, candidate_id: str) -> Candidate | None:
        try:
            return self._cands.get(candidate_id)
        except MemoryStoreError as exc:
            if exc.code is MemoryErrorCode.NOT_FOUND:
                return None
            raise

    def _drop(self, progress: _Progress, diagnostic: DropDiagnostic) -> None:
        progress.dropped.append(diagnostic)
        self._emit("memory.consolidation.dropped", {"index": diagnostic.index, "code": diagnostic.code, "detail": diagnostic.detail})

    def _emit(self, event: str, data: Mapping[str, Any]) -> None:
        try:
            self._sink(event, data)
        except Exception as exc:  # noqa: BLE001 - a broken diagnostics sink must never break consolidation
            _LOG.warning("memory consolidation sink failed on %s: %s", event, type(exc).__name__)

    # ------------------------------------------------------ dedup and conflicts
    def _neighbour_notes(self, scope: str, text: str = "") -> list[MemoryNote]:
        """Durable notes a candidate is compared with: the newest `MAX_NEIGHBOURS`, plus (when `text`
        is given and the store can rank) the best full-text matches, so an old near-duplicate is not
        missed because newer notes crowd the window."""

        notes = {n.id: n for n in self._store.list(MemoryFilters(scopes=(scope,), retentions=_DURABLE_RETENTIONS, limit=MAX_NEIGHBOURS))}
        ranked = getattr(self._store, "search_ranked", None)
        if text and ranked is not None:
            try:
                hits = ranked(text[:1_000], MAX_WIDENED_NEIGHBOURS, MemoryFilters(scopes=(scope,), retentions=_DURABLE_RETENTIONS))
            except Exception as exc:  # noqa: BLE001 - full-text widening is an aid: the newest-notes window still applies
                _LOG.warning("memory consolidation full-text lookup failed: %s", type(exc).__name__)
                hits = []
            for hit in hits:
                if hit.memory_id not in notes:
                    try:
                        notes[hit.memory_id] = self._store.get(hit.memory_id)
                    except MemoryStoreError:
                        continue  # intentional: a hit that vanished since indexing is skipped
        now = self._clock()
        return [n for n in notes.values() if n.valid_to is None or n.valid_to > now]

    async def _assess(self, candidate: Candidate, hints: tuple[str, ...], progress: _Progress) -> _Assessment:
        notes = await asyncio.to_thread(self._neighbour_notes, candidate.scope, f"{candidate.title}\n{candidate.body}")
        pool = {note.id: note for note in notes}
        for note in await self._recalled(candidate, progress):
            pool.setdefault(note.id, note)
        return await self._assess_against(candidate, list(pool.values()), hints, progress)

    async def _related_notes(self, scope: str, items: Sequence[Evidence]) -> tuple[RelatedNote, ...]:
        """Top related durable notes of the same scope, shown to the extractor as citable DATA.

        Scope-filtered twice (the query, then each note), never protected, superseded or short-term.
        Failure only means fewer hints: it never stops a run."""

        text = "\n".join(item.text for item in items)[:2_000]
        ids: dict[str, None] = {}
        try:
            if self._retriever is not None:
                result = await self._retriever.recall(
                    RecallQuery(text=text, scopes=(scope,), retentions=_DURABLE_RETENTIONS),
                    RecallBudget(max_items=MAX_RELATED_FOR_PROMPT),
                )
                ids.update(dict.fromkeys(item.memory_id for item in result.items))
            ranked = getattr(self._store, "search_ranked", None)
            if ranked is not None and len(ids) < MAX_RELATED_FOR_PROMPT:
                hits = await asyncio.to_thread(
                    ranked, text[:1_000], MAX_RELATED_FOR_PROMPT, MemoryFilters(scopes=(scope,), retentions=_DURABLE_RETENTIONS),
                )
                ids.update(dict.fromkeys(hit.memory_id for hit in hits))
        except Exception as exc:  # noqa: BLE001 - related notes are an aid to the extractor, not a requirement
            _LOG.warning("memory consolidation related-notes lookup failed: %s", type(exc).__name__)
        related: list[RelatedNote] = []
        for note_id in ids:
            if len(related) >= MAX_RELATED_FOR_PROMPT:
                break
            try:
                note = await asyncio.to_thread(self._store.get, note_id)
            except (MemoryStoreError, MemorySecurityError):
                continue
            if note.scope != scope or is_protected(note.retention) or note.retention is _EVIDENCE_RETENTION or note.is_superseded:
                continue
            related.append(RelatedNote(note.id, note.title, " ".join(note.body.split())[:160]))
        return tuple(related)

    async def _assess_against(
        self, candidate: Candidate, notes: list[MemoryNote], hints: tuple[str, ...], progress: _Progress,
    ) -> _Assessment:
        own_note = note_id_for(candidate.id)
        tokens = similarity_tokens(candidate.title, candidate.body)
        duplicate: tuple[float, str] | None = None
        conflicts: dict[str, None] = {}
        for note in notes:
            if note.id == own_note or note.scope != candidate.scope or note.is_superseded or note.retention is _EVIDENCE_RETENTION:
                continue
            sim = jaccard(tokens, similarity_tokens(note.title, note.body))
            if sim >= DUPLICATE_SIMILARITY:
                if duplicate is None or sim > duplicate[0]:
                    duplicate = (sim, note.id)
            elif sim >= CONFLICT_SIMILARITY and note.kind is candidate.kind:
                conflicts[note.id] = None
        pending_duplicate: str | None = None
        replaced: list[str] = []
        stale = False
        mine = evidence_time(candidate.sources, candidate.created_at)
        pending = await asyncio.to_thread(self._cands.list, CandidateState.PROPOSED, 500)
        for other in pending:
            if other.id == candidate.id or other.scope != candidate.scope:
                continue
            sim = jaccard(tokens, similarity_tokens(other.title, other.body))
            if sim >= DUPLICATE_SIMILARITY:
                pending_duplicate = pending_duplicate or other.id
            elif sim >= CONFLICT_SIMILARITY and other.kind is candidate.kind and candidate.kind in TEMPORAL_KINDS:
                if mine >= evidence_time(other.sources, other.created_at):
                    replaced.append(other.id)
                else:
                    stale = True
        if self._embedder is not None and duplicate is None:
            for note_id, cos, lexical in await self._semantic(candidate, notes, tokens, progress):
                if cos >= SEMANTIC_DUPLICATE_COSINE and lexical >= SEMANTIC_DUPLICATE_MIN_JACCARD:
                    duplicate = (cos, note_id)
                    break
                if cos >= SEMANTIC_CONFLICT_COSINE:
                    conflicts[note_id] = None
        for hint in hints:
            verdict = await asyncio.to_thread(self._hint_verdict, hint, candidate)
            if verdict == "ok":
                conflicts[hint] = None
            else:
                self._drop(progress, DropDiagnostic(-1, f"hint_{verdict}", hint))
        if duplicate is not None:
            return _Assessment(duplicate_of=duplicate[1])
        if pending_duplicate is not None:
            return _Assessment(duplicate_of=pending_duplicate)
        return _Assessment(conflicts=tuple(conflicts), replaced_pending=tuple(replaced), stale=stale)

    def _hint_verdict(self, hint: str, candidate: Candidate) -> str:
        """An extractor-named note id is only a hint: it must exist, share the scope, and be neither
        protected, short-term evidence nor already superseded."""

        try:
            note = self._store.get(hint)
        except MemoryStoreError:
            return "unknown"
        except Exception:  # noqa: BLE001 - a hostile id (unsafe token) is refused, never raised
            return "refused"
        if note.scope != candidate.scope:
            return "scope"
        if is_protected(note.retention):
            return "protected"
        if note.retention is _EVIDENCE_RETENTION:
            return "evidence"
        if note.is_superseded:
            return "superseded"
        return "ok"

    async def _recalled(self, candidate: Candidate, progress: _Progress) -> list[MemoryNote]:
        if self._retriever is None:
            return []
        try:
            result = await self._retriever.recall(
                RecallQuery(
                    text=f"{candidate.title}\n{candidate.body}"[:2_000], scopes=(candidate.scope,),
                    retentions=_DURABLE_RETENTIONS,
                ),
                RecallBudget(max_items=MAX_WIDENED_NEIGHBOURS),
            )
            found = []
            for item in result.items:
                try:
                    found.append(await asyncio.to_thread(self._store.get, item.memory_id))
                except MemoryStoreError:
                    continue  # intentional: a hit that no longer resolves is dropped (the retriever may lag)
            return found
        except Exception as exc:  # noqa: BLE001 - recall is an aid to dedup, its failure must not stop a run
            progress.errors.append(f"recall_failed:{type(exc).__name__}")
            self._emit("memory.consolidation.recall_failed", {"error": type(exc).__name__})
            return []

    async def _semantic(
        self, candidate: Candidate, notes: list[MemoryNote], tokens: frozenset[str], progress: _Progress,
    ) -> list[tuple[str, float, float]]:
        assert self._embedder is not None
        pool = [n for n in notes if n.scope == candidate.scope and not n.is_superseded][:MAX_SEMANTIC_NEIGHBOURS]
        if not pool:
            return []
        try:
            texts = [f"{candidate.title}\n{candidate.body}", *(f"{n.title}\n{n.body}" for n in pool)]
            vectors = await self._embedder.embed(texts, EMBED_TIMEOUT_S)
            if len(vectors) != len(texts):
                raise ValueError("embedder answered the wrong number of vectors")
        except Exception as exc:  # noqa: BLE001 - semantic similarity is optional: lexical dedup still runs
            progress.errors.append(f"semantic_failed:{type(exc).__name__}")
            self._emit("memory.consolidation.semantic_failed", {"error": type(exc).__name__})
            return []
        return [
            (note.id, cosine(vectors[0], vector), jaccard(tokens, similarity_tokens(note.title, note.body)))
            for note, vector in zip(pool, vectors[1:])
        ]

    def _supersede_pending(self, pending_id: str, progress: _Progress) -> None:
        pending = self._known_candidate(pending_id)
        if pending is None or not can_transition(pending.state, CandidateState.SUPERSEDED_BY_NEWER):
            return
        self._cands.save(replace(
            pending, state=CandidateState.SUPERSEDED_BY_NEWER, decided_at=self._clock(), decided_by=SYSTEM_ACTOR,
        ))
        progress.superseded.append(pending_id)
        self._emit("memory.consolidation.superseded_by_newer", {"candidate": pending_id})

    # ------------------------------------------------------------- policy gate
    async def _settle(self, candidates: Sequence[Candidate], settings: ConsolidationSettings, progress: _Progress) -> bool:
        """Apply the policy gate to candidates created by THIS run. `manual` returns at once.

        False when a commit failed: the caller then leaves the evidence unmarked, so the next run
        settles these candidates again (a failure before the decision intent exists is not recoverable otherwise)."""

        if settings.mode is not ConsolidationMode.AUTO:
            return True
        clean = True
        for candidate in candidates:
            if candidate.state is not CandidateState.PROPOSED:
                continue
            try:
                current = await asyncio.to_thread(self._cands.get, candidate.id)
                if current.state is not CandidateState.PROPOSED:
                    continue
                refusal = gate_auto(current, settings)
                if refusal is not None:
                    self._emit("memory.consolidation.gate_refused", {"candidate": current.id, "reason": refusal})
                    continue
                fresh = await self._assess(current, (), progress)
                if fresh.duplicate_of is not None:
                    await asyncio.to_thread(self._reject_sync, current, SYSTEM_ACTOR)
                    progress.duplicates.append((current.id, fresh.duplicate_of))
                    continue
                if fresh.conflicts:
                    merged = tuple(dict.fromkeys((*current.conflicts, *fresh.conflicts)))[:MAX_LINKS]  # hints are kept
                    await asyncio.to_thread(self._cands.save, replace(current, conflicts=merged))
                    self._emit("memory.consolidation.gate_refused", {"candidate": current.id, "reason": "has_conflicts"})
                    continue
                await asyncio.to_thread(
                    self._cands.begin_decision, DecisionIntent(current.id, CandidateDecision.ACCEPT, SYSTEM_ACTOR, self._clock()),
                )
                done = await asyncio.to_thread(self._commit_sync, current, SYSTEM_ACTOR)
                progress.committed.append(done.committed_memory_id or "")
                self._emit("memory.consolidation.auto_committed", {"candidate": done.id, "note": done.committed_memory_id})
            except MemoryStoreError as exc:
                # The intent stays: `recover` completes it on the next run. Never raised past the run.
                clean = False
                progress.errors.append(f"commit_failed:{exc.code.value}")
                self._emit("memory.consolidation.commit_failed", {"candidate": candidate.id, "code": exc.code.value})
            except OSError as exc:
                clean = False
                progress.errors.append(f"commit_failed:{type(exc).__name__}")
                self._emit("memory.consolidation.commit_failed", {"candidate": candidate.id, "error": type(exc).__name__})
        return clean

    # ----------------------------------------------------------- decisions (sync)
    def _decide_sync(self, candidate_id: str, decision: CandidateDecision, actor: str) -> Candidate:
        candidate = self._cands.get(candidate_id)
        if candidate.state is not CandidateState.PROPOSED:
            wanted = CandidateState.ACCEPTED if decision is CandidateDecision.ACCEPT else CandidateState.REJECTED
            if candidate.state is wanted:
                return candidate
            raise MemoryStoreError(
                MemoryErrorCode.CONFLICT_REVISION, f"candidate {candidate_id} is already {candidate.state.value}",
            )
        if decision is CandidateDecision.REJECT:
            return self._reject_sync(candidate, actor)
        self._cands.begin_decision(DecisionIntent(candidate.id, decision, actor, self._clock()))
        return self._commit_sync(candidate, actor)

    def _reject_sync(self, candidate: Candidate, actor: str) -> Candidate:
        if not can_transition(candidate.state, CandidateState.REJECTED):
            raise MemoryStoreError(MemoryErrorCode.CONFLICT_REVISION, f"candidate {candidate.id} is already decided")
        done = replace(candidate, state=CandidateState.REJECTED, decided_at=self._clock(), decided_by=actor)
        self._cands.save(done)
        self._cands.end_decision(candidate.id)
        self._emit("memory.consolidation.rejected", {"candidate": candidate.id, "actor_kind": "system" if is_system_actor(actor) else "human"})
        return done

    def _recover_sync(self, progress: _Progress) -> None:
        for intent in self._cands.pending_decisions():
            try:
                candidate = self._cands.get(intent.candidate_id)
            except MemoryStoreError:
                self._cands.end_decision(intent.candidate_id)  # orphan intent: its candidate is gone
                continue
            if candidate.state is not CandidateState.PROPOSED:
                self._cands.end_decision(intent.candidate_id)
                continue
            try:
                if intent.decision is CandidateDecision.ACCEPT:
                    self._commit_sync(candidate, intent.actor)
                else:
                    self._reject_sync(candidate, intent.actor)
            except (MemoryStoreError, OSError) as exc:
                progress.errors.append(f"recover_failed:{type(exc).__name__}")
                self._emit("memory.consolidation.recover_failed", {"candidate": candidate.id, "error": type(exc).__name__})
                continue
            progress.recovered += 1
            self._emit("memory.consolidation.recovered", {"candidate": candidate.id})

    def _commit_sync(self, candidate: Candidate, actor: str) -> Candidate:
        """Commit one candidate as a canonical note, then close it. Replay-safe at every step.

        Order: (1) create the note (it already names what it supersedes and contradicts),
        (2) close the superseded notes and link the contradicted ones, (3) mark the
        candidate `accepted`. A crash after (1) or (2) is finished by running this again:
        the note id is derived from the candidate id, so the existing note is reused.
        """

        if is_protected(candidate.retention):
            raise MemoryStoreError(MemoryErrorCode.SCOPE_DENIED, f"{candidate.retention.value} is protected")
        try:
            check_level_retention(candidate.level, candidate.retention)
        except ValueError as exc:
            raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, f"candidate {candidate.id} is invalid: {exc}") from exc
        now = self._clock()
        note_id = note_id_for(candidate.id)
        note = self._existing_note(note_id)
        if note is None:
            supersede, contradict = self._plan_links(candidate, note_id)
            when = min(evidence_time(candidate.sources, now), now)
            note = self._store.create(MemoryNote(
                id=note_id, title=candidate.title, body=candidate.body, level=candidate.level, kind=candidate.kind,
                retention=candidate.retention, scope=candidate.scope, created_at=now, updated_at=now,
                valid_from=when if supersede else None, confidence=candidate.confidence,
                sources=(*candidate.sources[-(MAX_SOURCES - 1):], Provenance(SourceType.CONSOLIDATION, f"candidate/{candidate.id}", now)),
                supersedes=tuple(supersede), contradicts=tuple(contradict),
            ))
            self._emit("memory.consolidation.committed", {
                "candidate": candidate.id, "note": note.id, "supersedes": len(supersede), "contradicts": len(contradict),
            })
        else:
            supersede, contradict = list(note.supersedes), list(note.contradicts)
        when = min(evidence_time(candidate.sources, now), now)
        for old_id in supersede:
            self._close_old(old_id, note.id, when)
        for old_id in contradict:
            self._link_old(old_id, note.id)
        done = replace(
            candidate, state=CandidateState.ACCEPTED, decided_at=now, decided_by=actor, committed_memory_id=note.id,
        )
        self._cands.save(done)
        self._cands.end_decision(candidate.id)
        return done

    def _existing_note(self, note_id: str) -> MemoryNote | None:
        try:
            return self._store.get(note_id)
        except MemoryStoreError as exc:
            if exc.code is MemoryErrorCode.NOT_FOUND:
                return None
            raise

    def _plan_links(self, candidate: Candidate, note_id: str) -> tuple[list[str], list[str]]:
        """Which notes the new one supersedes (temporal) and which it only contradicts."""

        ids = dict.fromkeys(candidate.conflicts)
        tokens = similarity_tokens(candidate.title, candidate.body)
        for note in self._neighbour_notes(candidate.scope, f"{candidate.title}\n{candidate.body}"):
            sim = jaccard(tokens, similarity_tokens(note.title, note.body))
            if note.id != note_id and CONFLICT_SIMILARITY <= sim < DUPLICATE_SIMILARITY and note.kind is candidate.kind:
                ids[note.id] = None
        when = evidence_time(candidate.sources, candidate.created_at)
        supersede: list[str] = []
        contradict: list[str] = []
        for old_id in ids:
            try:
                old = self._store.get(old_id)
            except MemoryStoreError:
                continue  # intentional: a conflict whose note vanished needs no link
            if old.id == note_id or old.scope != candidate.scope:
                continue
            starts = old.valid_from or old.created_at
            if (candidate.kind in TEMPORAL_KINDS and not is_protected(old.retention)
                    and not old.is_superseded and when >= starts):
                supersede.append(old.id)
            else:
                contradict.append(old.id)
        return supersede[:MAX_LINKS], contradict[:MAX_LINKS]

    def _close_old(self, old_id: str, new_id: str, when: datetime) -> None:
        """Close the old note's validity and point it at its successor (history keeps its revision)."""

        for _ in range(3):
            try:
                old = self._store.get(old_id)
            except MemoryStoreError:
                return
            if old.superseded_by == new_id or is_protected(old.retention):
                return
            if old.superseded_by is not None:
                self._emit("memory.consolidation.supersede_skipped", {"old": old_id, "by": old.superseded_by})
                return
            patch = MemoryPatch(valid_to=when if old.valid_to is None else None, superseded_by=new_id)
            try:
                self._store.revise(old_id, patch, old.revision)
                return
            except MemoryStoreError as exc:
                if exc.code is not MemoryErrorCode.CONFLICT_REVISION:
                    raise
        raise MemoryStoreError(MemoryErrorCode.CONFLICT_REVISION, f"note {old_id} kept changing; commit not finished")

    def _link_old(self, old_id: str, new_id: str) -> None:
        """Flag the older side of a contradiction (a protected note is never touched)."""

        for _ in range(3):
            try:
                old = self._store.get(old_id)
            except MemoryStoreError:
                return
            if new_id in old.contradicts or is_protected(old.retention):
                return
            try:
                self._store.revise(old_id, MemoryPatch(add_contradicts=(new_id,)), old.revision)
                return
            except MemoryStoreError as exc:
                if exc.code is not MemoryErrorCode.CONFLICT_REVISION:
                    raise
        raise MemoryStoreError(MemoryErrorCode.CONFLICT_REVISION, f"note {old_id} kept changing; commit not finished")
