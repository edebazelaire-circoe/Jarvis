"""Core admission of canonical input, independent of backend execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import hashlib

from jarvis.domain.speech_presentation import SpeechSource, speech_id
from jarvis.domain.v2 import AddressingDecision, ConversationTurn, TurnKind
from jarvis.domain.voice_state import VoiceTurnOrder

VOICE_TURN_ADMITTED = "voice.turn.admitted"
BRAIN_SOURCE_CHANGED = "brain.source.changed"
MAX_ADMISSION_TEXT = 8192
MAX_ADMISSION_JSON_BYTES = 65536


def _identity(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def admission_correlation_id(request: VoiceTurnAdmissionRequest) -> str:
    return "voice-source-" + _identity(request.conversation_id, request.session_id, request.canonical_turn_id)


def canonical_admitted_turn_id(conversation_id: str, session_id: str, canonical_turn_id: str) -> str:
    correlation = "voice-source-" + _identity(conversation_id, session_id, canonical_turn_id)
    return "brain-turn-" + _identity(conversation_id, correlation)


def admitted_turn_binding(turn: ConversationTurn) -> VoiceTurnAdmissionRequest | None:
    """A marker object alone never proves a direct-admitted USER identity."""
    try:
        request = VoiceTurnAdmissionRequest.from_payload(turn.metadata.get("voice_admission"))
    except ValueError:
        return None
    correlation = admission_correlation_id(request)
    if (turn.kind is not TurnKind.USER or turn.conversation_id != request.conversation_id
            or turn.content != request.text or turn.correlation_id != correlation
            or turn.id != "brain-turn-" + _identity(request.conversation_id, correlation)
            or turn.metadata.get("authoritative") is not True or turn.metadata.get("final") is not True
            or turn.metadata.get("source") != "realtime" or turn.metadata.get("addressing") != request.addressing.value
            or turn.metadata.get("provider_item_id") != request.provider_item_id):
        return None
    return request


def canonical_input_matches(snapshot, request: VoiceTurnAdmissionRequest) -> bool:
    return snapshot.conversation_id == request.conversation_id and any(
        item.committed and item.correlation.session_id == request.session_id
        and item.correlation.turn_id == request.canonical_turn_id and item.transcript_id == request.transcript_id
        and item.revision == request.transcript_revision and item.text == request.text
        and item.correlation.provider_input_id == request.provider_item_id for item in snapshot.users)


def admitted_turn_order(turn: ConversationTurn) -> VoiceTurnOrder | None:
    binding = admitted_turn_binding(turn)
    raw = turn.metadata.get("voice_admission_order")
    fields = {"schema_version", "session_id", "turn_id", "previous_turn_id", "observation_order"}
    if binding is None or not isinstance(raw, dict) or set(raw) != fields:
        return None
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        return None
    try:
        order = VoiceTurnOrder(**{key: value for key, value in raw.items() if key != "schema_version"})
    except ValueError:
        return None
    if order.session_id != binding.session_id or order.turn_id != binding.canonical_turn_id:
        return None
    return order


def canonical_input_is_newer(snapshot, candidate: VoiceTurnAdmissionRequest,
                             current: VoiceTurnAdmissionRequest, *, candidate_order: VoiceTurnOrder | None,
                             current_order: VoiceTurnOrder | None, durable_orders: tuple[VoiceTurnOrder, ...] = ()) -> bool:
    """Server canonical predecessor order, with server observation order fallback.

    Missing retained evidence cannot grant promotion. Allocation epochs are
    identities, not evidence of the order in which canonical input occurred.
    """
    if (snapshot.current_session_id != candidate.session_id or not canonical_input_matches(snapshot, candidate)
            or candidate_order is None or current_order is None):
        return False
    if candidate.session_id != current.session_id:
        return True  # Only the currently bound incarnation can supersede the old one.
    turns = {turn.turn_id: turn for turn in snapshot.turns if turn.session_id == candidate.session_id}
    for order in (*durable_orders, candidate_order, current_order):
        if order.session_id != candidate.session_id:
            return False
        if order.turn_id in turns and turns[order.turn_id] != order:
            return False
        turns[order.turn_id] = order

    def ancestry(turn_id):
        path = []
        visited = set()
        while turn_id is not None:
            if turn_id in visited:
                return None  # A combined persisted/window cycle is not order evidence.
            visited.add(turn_id)
            path.append(turn_id)
            turn = turns.get(turn_id)
            if turn is None:
                return path, False
            turn_id = turn.previous_turn_id
        return path, True

    candidate_ancestry, current_ancestry = ancestry(candidate_order.turn_id), ancestry(current_order.turn_id)
    if candidate_ancestry is None or current_ancestry is None:
        return False
    candidate_path, candidate_complete = candidate_ancestry
    current_path, current_complete = current_ancestry
    if current_order.turn_id in candidate_path:
        return True
    if candidate_order.turn_id in current_path:
        return False
    if set(candidate_path) & set(current_path):
        return False  # Explicit siblings/forks are not a later linear intention.
    if not candidate_complete or not current_complete:
        return False  # An explicit missing predecessor cannot be invented from an ordinal.
    # The server observation ordinal survives in each admitted USER record.
    # Unlike an allocation epoch, it predates the HTTP admission and remains
    # usable when the old current turn leaves the bounded canonical window.
    return candidate_order.observation_order > current_order.observation_order


@dataclass(frozen=True, slots=True)
class VoiceTurnAdmissionRequest:
    conversation_id: str
    text: str = field(repr=False)
    addressing: AddressingDecision
    session_id: str
    canonical_turn_id: str
    transcript_id: str
    transcript_revision: int
    provider_item_id: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("voice admission schema version must be integer 1")
        for name in ("conversation_id", "session_id", "canonical_turn_id", "transcript_id", "provider_item_id"):
            speech_id(getattr(self, name), name)
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text) > MAX_ADMISSION_TEXT:
            raise ValueError("voice admission text must be nonempty and bounded")
        try:
            self.text.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("voice admission text must be valid Unicode") from exc
        if type(self.transcript_revision) is not int or not 0 <= self.transcript_revision <= 2**63 - 1:
            raise ValueError("voice admission transcript revision must be bounded integer")
        if not isinstance(self.addressing, AddressingDecision) or self.addressing not in (AddressingDecision.ADDRESSED, AddressingDecision.UNCERTAIN):
            raise ValueError("voice admission requires addressed or uncertain input")

    def to_payload(self) -> dict:
        return {**asdict(self), "addressing": self.addressing.value}

    @classmethod
    def from_payload(cls, value: object) -> VoiceTurnAdmissionRequest:
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("invalid voice admission fields")
        if not isinstance(value["addressing"], str):
            raise ValueError("invalid voice admission addressing")
        return cls(**{**value, "addressing": AddressingDecision(value["addressing"])})


def decode_voice_admission(raw: bytes) -> VoiceTurnAdmissionRequest:
    if not isinstance(raw, bytes) or len(raw) > MAX_ADMISSION_JSON_BYTES:
        raise ValueError("voice admission request exceeds byte bounds")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate voice admission JSON key")
            result[key] = value
        return result
    def invalid_constant(_value):
        raise ValueError("nonfinite voice admission JSON number")
    try:
        return VoiceTurnAdmissionRequest.from_payload(json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid_constant))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid voice admission encoding or nesting") from exc


@dataclass(frozen=True, slots=True)
class VoiceTurnAdmissionAcceptance:
    conversation_id: str
    turn_id: str
    correlation_id: str
    source: SpeechSource
    duplicate: bool
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1 or type(self.duplicate) is not bool:
            raise ValueError("invalid voice admission acceptance version or duplicate")
        for name in ("conversation_id", "turn_id", "correlation_id"):
            speech_id(getattr(self, name), name)
        if not isinstance(self.source, SpeechSource) or self.source.turn_id != self.turn_id or self.source.correlation_id != self.correlation_id:
            raise ValueError("voice admission source does not match accepted turn")

    def to_payload(self) -> dict:
        return {"schema_version": 1, "conversation_id": self.conversation_id, "turn_id": self.turn_id,
                "correlation_id": self.correlation_id, "source": self.source.to_payload(), "duplicate": self.duplicate}

    @classmethod
    def from_payload(cls, value: object) -> VoiceTurnAdmissionAcceptance:
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("invalid voice admission acceptance fields")
        return cls(**{**value, "source": SpeechSource.from_payload(value["source"])})
