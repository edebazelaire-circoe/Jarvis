"""Bounded result-only jobs; provenance is produced by Core, never a model."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import hashlib

from jarvis.domain.speech_presentation import SpeechSource, speech_id


def back_brain_job_id(conversation_id: str, source_correlation_id: str) -> str:
    return "back-brain-" + hashlib.sha256(json.dumps((conversation_id, source_correlation_id), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def speculative_job_id(conversation_id: str, session_id: str, delegation_id: str) -> str:
    return "back-analysis-" + hashlib.sha256(json.dumps((conversation_id, session_id, delegation_id), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def decode_provenance(value):
    return (BackBrainProvenance if isinstance(value, dict) and "source" in value else BackBrainSpeculativeProvenance).from_payload(value)


def provenance_job_id(proof):
    return (back_brain_job_id(proof.conversation_id, proof.source.correlation_id) if isinstance(proof, BackBrainProvenance)
            else speculative_job_id(proof.conversation_id, proof.session_id, proof.delegation_id))


class BackBrainUnavailable(ValueError):
    def __init__(self, code: str):
        if code not in {"back_brain_capacity", "back_brain_already_reserved", "back_brain_stopping", "back_brain_worker_unavailable"}:
            raise ValueError("invalid backend availability code")
        self.code = code
        super().__init__(code)


def _text(value, name, limit, *, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(f"invalid {name}")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"invalid {name} encoding") from exc


def _version(value):
    if type(value) is not int or value != 1:
        raise ValueError("unsupported back brain schema")


def _shape(value, cls):
    if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
        raise ValueError(f"invalid {cls.__name__} fields")
    return dict(value)


def decode_request(raw: bytes) -> dict:
    if len(raw) > 16384:
        raise ValueError("back brain request exceeds byte bound")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError("nonfinite JSON number")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid request encoding") from exc
    if not isinstance(result, dict):
        raise ValueError("request must be an object")
    return result


@dataclass(frozen=True, slots=True)
class BackBrainContextDependency:
    turn_id: str
    kind: str
    text_sha256: str

    def __post_init__(self):
        speech_id(self.turn_id, "context turn_id")
        if self.kind not in {"user", "assistant"} or not isinstance(self.text_sha256, str) or len(self.text_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.text_sha256):
            raise ValueError("invalid context dependency")

    @classmethod
    def from_turn(cls, turn):
        from jarvis.domain.voice_admission import admitted_turn_binding, admitted_turn_order
        if turn.kind.value == "user":
            if admitted_turn_binding(turn) is None or admitted_turn_order(turn) is None:
                raise ValueError("context user has no canonical admission")
        elif turn.kind.value == "assistant":
            start, end, key = (turn.metadata.get(name) for name in ("confirmed_start", "confirmed_end", "output_key"))
            if (turn.metadata.get("voice_evidence") is not True or type(start) is not int or type(end) is not int
                    or start < 0 or end - start != len(turn.content) or turn.id != f"voice-heard-{key}-{start}-{end}"):
                raise ValueError("context assistant has no confirmed voice range")
        else:
            raise ValueError("unsupported context turn")
        return cls(turn.id, turn.kind.value, hashlib.sha256(turn.content.encode("utf-8")).hexdigest())

    def matches(self, turn):
        try:
            return self == self.from_turn(turn)
        except (ValueError, AttributeError):
            return False

    def to_payload(self):
        return asdict(self)

    @classmethod
    def from_payload(cls, value):
        return cls(**_shape(value, cls))


@dataclass(frozen=True, slots=True)
class BackBrainProvenance:
    conversation_id: str
    source: SpeechSource
    session_id: str
    canonical_turn_id: str
    transcript_id: str
    transcript_revision: int
    provider_item_id: str
    snapshot_revision: int
    context_dependencies: tuple[BackBrainContextDependency, ...] = ()

    def __post_init__(self):
        for name in ("conversation_id", "session_id", "canonical_turn_id", "transcript_id", "provider_item_id"):
            speech_id(getattr(self, name), name)
        if not isinstance(self.source, SpeechSource):
            raise ValueError("invalid job source")
        for name in ("transcript_revision", "snapshot_revision"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 2**63 - 1:
                raise ValueError(f"invalid {name}")
        if not isinstance(self.context_dependencies, tuple) or len(self.context_dependencies) > 16 or any(not isinstance(item, BackBrainContextDependency) for item in self.context_dependencies):
            raise ValueError("invalid context dependencies")
        if len({item.turn_id for item in self.context_dependencies}) != len(self.context_dependencies):
            raise ValueError("duplicate context dependency")

    def to_payload(self):
        return {**asdict(self), "source": self.source.to_payload(), "context_dependencies": [item.to_payload() for item in self.context_dependencies]}

    @classmethod
    def from_payload(cls, value):
        value = _shape(value, cls)
        value["source"] = SpeechSource.from_payload(value["source"])
        if not isinstance(value["context_dependencies"], list) or len(value["context_dependencies"]) > 16:
            raise ValueError("invalid context dependency array")
        value["context_dependencies"] = tuple(BackBrainContextDependency.from_payload(item) for item in value["context_dependencies"])
        return cls(**value)


@dataclass(frozen=True, slots=True)
class BackBrainWorkPayload:
    request_text: str = field(repr=False)
    context_text: str = field(repr=False)
    provenance: BackBrainProvenance | BackBrainSpeculativeProvenance
    scope: str = "admitted_work"
    schema_version: int = 1

    def __post_init__(self):
        _version(self.schema_version)
        expected = BackBrainProvenance if self.scope == "admitted_work" else BackBrainSpeculativeProvenance if self.scope == "speculative_analysis" else None
        if expected is None or not isinstance(self.provenance, expected):
            raise ValueError("unsupported job scope or provenance")
        _text(self.request_text, "request_text", 8192, empty=False)
        _text(self.context_text, "context_text", 8192)

    def to_payload(self):
        return {**asdict(self), "provenance": self.provenance.to_payload()}

    @classmethod
    def from_payload(cls, value):
        value = _shape(value, cls)
        value["provenance"] = decode_provenance(value["provenance"])
        return cls(**value)


@dataclass(frozen=True, slots=True)
class BackBrainResult:
    text: str = field(repr=False)
    provider: str
    model: str
    session_id: str | None
    code: str = "completed"
    schema_version: int = 1

    def __post_init__(self):
        _version(self.schema_version)
        _text(self.text, "result text", 16384, empty=False)
        _text(self.provider, "provider", 64, empty=False)
        _text(self.model, "model", 256)
        speech_id(self.session_id, "session_id", optional=True)
        if self.code != "completed":
            raise ValueError("invalid result code")

    def to_payload(self):
        return asdict(self)

    @classmethod
    def from_payload(cls, value):
        return cls(**_shape(value, cls))


@dataclass(frozen=True, slots=True)
class BackBrainSubmitRequest:
    conversation_id: str
    source_correlation_id: str | None = None
    scope: str = "admitted_work"
    session_id: str | None = None
    delegation_id: str | None = None
    schema_version: int = 1

    def __post_init__(self):
        _version(self.schema_version)
        speech_id(self.conversation_id, "conversation_id")
        for name in ("source_correlation_id", "session_id", "delegation_id"):
            speech_id(getattr(self, name), name, optional=True)
        if self.scope == "admitted_work":
            if self.source_correlation_id is None or self.session_id is not None or self.delegation_id is not None:
                raise ValueError("admitted work requires only a Core source")
        elif self.scope == "speculative_analysis":
            if self.source_correlation_id is not None or self.session_id is None or self.delegation_id is None:
                raise ValueError("speculative reference requires session and delegation")
        else:
            raise ValueError("unsupported back brain scope")

    def to_payload(self):
        return asdict(self)

    @classmethod
    def from_payload(cls, value):
        return cls(**_shape(value, cls))


@dataclass(frozen=True, slots=True)
class BackBrainSubmission:
    status: str
    job_id: str | None = None
    duplicate: bool = False
    reason: str | None = None
    provenance: BackBrainProvenance | BackBrainSpeculativeProvenance | None = None
    schema_version: int = 1

    def __post_init__(self):
        _version(self.schema_version)
        speech_id(self.job_id, "job_id", optional=True)
        if type(self.duplicate) is not bool or self.status not in {"accepted", "unavailable"}:
            raise ValueError("invalid submission")
        if self.status == "accepted":
            if self.job_id is None or not isinstance(self.provenance, (BackBrainProvenance, BackBrainSpeculativeProvenance)) or self.reason is not None:
                raise ValueError("invalid accepted job")
        else:
            reasons = {"restricted_execution_unavailable", "analysis_context_unavailable", "backend_worker_unavailable", "back_brain_capacity", "back_brain_already_reserved", "back_brain_stopping", "back_brain_worker_unavailable"}
            if self.job_id is not None or self.provenance is not None or self.duplicate or not isinstance(self.reason, str) or self.reason not in reasons:
                raise ValueError("unavailable is not a job acceptance")

    def to_payload(self):
        return {**asdict(self), "provenance": self.provenance.to_payload() if self.provenance else None}

    @classmethod
    def from_payload(cls, value):
        value = _shape(value, cls)
        if value["provenance"] is not None:
            value["provenance"] = decode_provenance(value["provenance"])
        return cls(**value)


@dataclass(frozen=True, slots=True)
class BackBrainAdvisoryDependency:
    session_id: str
    transcript_id: str
    revision: int
    provider_item_id: str | None
    committed: bool
    text: str = field(repr=False)

    def __post_init__(self):
        speech_id(self.session_id, "dependency session")
        speech_id(self.transcript_id, "dependency transcript")
        speech_id(self.provider_item_id, "dependency item", optional=True)
        if type(self.revision) is not int or not 0 <= self.revision <= 2**63 - 1 or type(self.committed) is not bool:
            raise ValueError("invalid advisory dependency revision")
        _text(self.text, "advisory input", 8192)

    def to_payload(self):
        return asdict(self)

    @classmethod
    def from_payload(cls, value):
        return cls(**_shape(value, cls))


@dataclass(frozen=True, slots=True)
class BackBrainSpeculativeProvenance:
    conversation_id: str
    session_id: str
    delegation_id: str
    snapshot_revision: int
    dependencies: tuple[BackBrainAdvisoryDependency, ...]
    authorizes_actions: bool = False

    def __post_init__(self):
        for name in ("conversation_id", "session_id", "delegation_id"):
            speech_id(getattr(self, name), name)
        if type(self.snapshot_revision) is not int or not 0 <= self.snapshot_revision <= 2**63 - 1 or self.authorizes_actions is not False:
            raise ValueError("invalid speculative provenance")
        if (not isinstance(self.dependencies, tuple) or not 1 <= len(self.dependencies) <= 8
                or any(not isinstance(d, BackBrainAdvisoryDependency) or d.session_id != self.session_id for d in self.dependencies)
                or len({d.transcript_id for d in self.dependencies}) != len(self.dependencies)
                or not any(d.text.strip() for d in self.dependencies)
                or sum(len(d.text) for d in self.dependencies) > 8192):
            raise ValueError("invalid speculative dependencies")
        if len(json.dumps(self.to_payload(), ensure_ascii=False).encode()) > 16384:
            raise ValueError("speculative provenance exceeds byte bound")

    def to_payload(self):
        return {**asdict(self), "dependencies": [d.to_payload() for d in self.dependencies]}

    @classmethod
    def from_payload(cls, value):
        value = _shape(value, cls)
        if not isinstance(value["dependencies"], list) or len(value["dependencies"]) > 8:
            raise ValueError("invalid speculative dependency list")
        value["dependencies"] = tuple(BackBrainAdvisoryDependency.from_payload(d) for d in value["dependencies"])
        return cls(**value)


@dataclass(frozen=True, slots=True)
class BackBrainAdvisoryReference:
    reference_id: str
    conversation_id: str
    session_id: str
    delegation_id: str
    snapshot_revision: int
    dependencies: tuple[BackBrainAdvisoryDependency, ...]
    created_at: str
    status: str = "unavailable"
    reason: str = "restricted_execution_unavailable"
    capability: str = "speculative_analysis"
    authorizes_actions: bool = False
    schema_version: int = 1

    def __post_init__(self):
        from datetime import datetime
        _version(self.schema_version)
        for name in ("reference_id", "conversation_id", "session_id", "delegation_id"):
            speech_id(getattr(self, name), name)
        if type(self.snapshot_revision) is not int or not 0 <= self.snapshot_revision <= 2**63 - 1:
            raise ValueError("invalid advisory snapshot revision")
        if (self.status != "unavailable" or self.reason != "restricted_execution_unavailable"
                or self.capability != "speculative_analysis" or self.authorizes_actions is not False):
            raise ValueError("advisory reference cannot authorize execution")
        if not isinstance(self.dependencies, tuple) or len(self.dependencies) > 8:
            raise ValueError("invalid advisory dependencies")
        for dependency in self.dependencies:
            if not isinstance(dependency, BackBrainAdvisoryDependency) or dependency.session_id != self.session_id:
                raise ValueError("invalid advisory dependency")
        if len({(d.session_id, d.transcript_id) for d in self.dependencies}) != len(self.dependencies):
            raise ValueError("duplicate advisory dependency")
        if not isinstance(self.created_at, str) or len(self.created_at) > 64:
            raise ValueError("invalid advisory time")
        parsed = datetime.fromisoformat(self.created_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("advisory time requires timezone")
        if len(json.dumps(self.to_payload(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 16384:
            raise ValueError("advisory source projection exceeds 16KiB")

    def to_payload(self):
        result = asdict(self)
        result["dependencies"] = [item.to_payload() for item in self.dependencies]
        return result

    @classmethod
    def from_payload(cls, value):
        value = _shape(value, cls)
        if not isinstance(value["dependencies"], list) or len(value["dependencies"]) > 8:
            raise ValueError("invalid advisory dependency arrays")
        value["dependencies"] = tuple(BackBrainAdvisoryDependency.from_payload(item) for item in value["dependencies"])
        return cls(**value)


@dataclass(frozen=True, slots=True)
class BackBrainAdvisorySnapshot:
    reference: BackBrainAdvisoryReference
    freshness: str

    def __post_init__(self):
        if not isinstance(self.reference, BackBrainAdvisoryReference) or self.freshness not in {"current", "stale", "unknown"}:
            raise ValueError("invalid advisory projection")

    def to_payload(self):
        return {"reference": self.reference.to_payload(), "freshness": self.freshness}

    @classmethod
    def from_payload(cls, value):
        value = _shape(value, cls)
        return cls(BackBrainAdvisoryReference.from_payload(value["reference"]), value["freshness"])


@dataclass(frozen=True, slots=True)
class BackBrainProgress:
    phase: str | None
    fraction: float | None
    public_summary: str = field(repr=False)

    def __post_init__(self):
        import math
        if self.phase is not None:
            _text(self.phase, "progress phase", 256)
        _text(self.public_summary, "progress summary", 1000)
        if self.fraction is not None and (type(self.fraction) not in (int, float) or not math.isfinite(self.fraction) or not 0 <= self.fraction <= 1):
            raise ValueError("invalid progress fraction")

    def to_payload(self):
        return asdict(self)

    @classmethod
    def from_payload(cls, value):
        return cls(**_shape(value, cls))


@dataclass(frozen=True, slots=True)
class BackBrainTaskSnapshot:
    job_id: str
    conversation_id: str
    status: str
    revision: int
    cancellation: str
    cancel_requested: bool
    provenance: BackBrainProvenance | BackBrainSpeculativeProvenance
    source_current: bool
    dependencies_current: bool | None
    fresh: bool
    progress: BackBrainProgress | None
    result: BackBrainResult | None
    error: str | None
    created_at: str
    completed_at: str | None
    persistence_error: str | None = None
    authorizes_actions: bool = False
    schema_version: int = 1

    def __post_init__(self):
        from datetime import datetime
        _version(self.schema_version)
        speech_id(self.job_id, "job_id")
        speech_id(self.conversation_id, "conversation_id")
        if not isinstance(self.provenance, (BackBrainProvenance, BackBrainSpeculativeProvenance)) or self.provenance.conversation_id != self.conversation_id:
            raise ValueError("invalid snapshot provenance")
        if self.job_id != provenance_job_id(self.provenance):
            raise ValueError("invalid snapshot job identity")
        if type(self.revision) is not int or not 0 <= self.revision <= 2**63 - 1:
            raise ValueError("invalid task revision")
        if self.status not in {"pending", "running", "completed", "failed", "cancelled", "interrupted"}:
            raise ValueError("invalid task status")
        if self.cancellation not in {"none", "requested", "cleanup_unknown", "confirmed"}:
            raise ValueError("invalid task cleanup state")
        if type(self.cancel_requested) is not bool:
            raise ValueError("invalid task cancel request")
        if type(self.source_current) is not bool or self.authorizes_actions is not False:
            raise ValueError("invalid task authority")
        if self.dependencies_current is not None and type(self.dependencies_current) is not bool:
            raise ValueError("invalid dependency freshness")
        if type(self.fresh) is not bool or self.fresh != (self.source_current and self.dependencies_current is True):
            raise ValueError("invalid task freshness")
        if self.progress is not None and not isinstance(self.progress, BackBrainProgress):
            raise ValueError("invalid task progress")
        if self.result is not None and not isinstance(self.result, BackBrainResult):
            raise ValueError("invalid task result")
        if self.status == "completed" and self.result is None:
            raise ValueError("completed task requires its durable result")
        if self.error is not None:
            speech_id(self.error, "error code")
        if self.persistence_error not in {None, "state_persistence_unavailable"}:
            raise ValueError("invalid persistence error")
        for value in (self.created_at, self.completed_at):
            if value is None:
                continue
            if not isinstance(value, str) or len(value) > 64:
                raise ValueError("invalid task timestamp")
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("task timestamp requires timezone")
        if self.created_at is None:
            raise ValueError("task creation time required")
        if self.status in {"completed", "failed", "cancelled", "interrupted"} and self.completed_at is None:
            raise ValueError("terminal task completion time required")

    def to_payload(self):
        return {**asdict(self), "provenance": self.provenance.to_payload(),
                "progress": self.progress.to_payload() if self.progress else None,
                "result": self.result.to_payload() if self.result else None}

    @classmethod
    def from_payload(cls, value):
        value = _shape(value, cls)
        value["provenance"] = decode_provenance(value["provenance"])
        if value["progress"] is not None:
            value["progress"] = BackBrainProgress.from_payload(value["progress"])
        if value["result"] is not None:
            value["result"] = BackBrainResult.from_payload(value["result"])
        return cls(**value)


@dataclass(frozen=True, slots=True)
class BackBrainTaskList:
    conversation_id: str
    tasks: tuple[BackBrainTaskSnapshot, ...]
    advisory_unavailable: tuple[BackBrainAdvisorySnapshot, ...]
    schema_version: int = 1

    def __post_init__(self):
        _version(self.schema_version)
        speech_id(self.conversation_id, "conversation_id")
        for items, kind in ((self.tasks, BackBrainTaskSnapshot), (self.advisory_unavailable, BackBrainAdvisorySnapshot)):
            if not isinstance(items, tuple) or len(items) > 32 or any(not isinstance(item, kind) for item in items):
                raise ValueError("invalid task list records")
        if any(item.conversation_id != self.conversation_id for item in self.tasks) or any(item.reference.conversation_id != self.conversation_id for item in self.advisory_unavailable):
            raise ValueError("task list conversation mismatch")
        if len({item.job_id for item in self.tasks}) != len(self.tasks) or len({item.reference.reference_id for item in self.advisory_unavailable}) != len(self.advisory_unavailable):
            raise ValueError("duplicate task list identity")

    def to_payload(self):
        return {"schema_version": 1, "conversation_id": self.conversation_id, "tasks": [item.to_payload() for item in self.tasks],
                "advisory_unavailable": [item.to_payload() for item in self.advisory_unavailable]}

    @classmethod
    def from_payload(cls, value):
        value = _shape(value, cls)
        if (not isinstance(value["tasks"], list) or not isinstance(value["advisory_unavailable"], list)
                or len(value["tasks"]) > 32 or len(value["advisory_unavailable"]) > 32):
            raise ValueError("invalid task list arrays")
        value["tasks"] = tuple(BackBrainTaskSnapshot.from_payload(item) for item in value["tasks"])
        value["advisory_unavailable"] = tuple(BackBrainAdvisorySnapshot.from_payload(item) for item in value["advisory_unavailable"])
        return cls(**value)
