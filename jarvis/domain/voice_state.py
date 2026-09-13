"""Immutable canonical conversation evidence and strict versioned snapshots.

No execution authority, provider history, audio bytes, or process-local clock
values are persisted here. Active tasks are references to existing Core work.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from jarvis.domain.voice_events import UserCommitSource, VoiceGenerationStatus, VoicePlaybackStatus
from jarvis.domain.voice_playback import VoiceAudioPart
from jarvis.domain.voice_frontend import (
    FrontendState, VoiceCorrelation, bounded_text, nonnegative, nonnegative_int,
)
from jarvis.domain.work_state import WorkStatus

MAX_USERS = 64
MAX_TURNS = 128
MAX_SPEECHES = 64
MAX_TASKS = 32
MAX_SEEN_EVENTS = 512
MAX_GENERATED_PARTS = 16
MAX_STATE_TEXT = 8192


def state_id(value: object, name: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not value or len(value) > 256 or value != value.strip() or not value.isprintable():
        raise ValueError(f"{name} must be a nonempty bounded opaque identifier")


def correlation_valid(value: VoiceCorrelation) -> None:
    if not isinstance(value, VoiceCorrelation):
        raise ValueError("correlation must be VoiceCorrelation")
    for item in fields(VoiceCorrelation):
        state_id(getattr(value, item.name), item.name, optional=item.name != "session_id")


def _enum(value: object, enum: type[StrEnum], name: str) -> None:
    if not isinstance(value, enum):
        raise ValueError(f"{name} has an invalid value")


def _records(values: tuple, cls: type, limit: int, name: str) -> None:
    if not isinstance(values, tuple) or len(values) > limit or any(not isinstance(item, cls) for item in values):
        raise ValueError(f"{name} must be a bounded immutable tuple of {cls.__name__}")


@dataclass(frozen=True, slots=True)
class VoiceUserRecord:
    correlation: VoiceCorrelation
    transcript_id: str
    revision: int
    text: str = field(repr=False)
    committed: bool = False
    commit_source: UserCommitSource | None = None

    def __post_init__(self) -> None:
        correlation_valid(self.correlation)
        state_id(self.transcript_id, "transcript_id")
        nonnegative_int(self.revision, "revision")
        bounded_text(self.text, MAX_STATE_TEXT, "user text")
        if type(self.committed) is not bool or self.committed != (self.commit_source is not None):
            raise ValueError("committed requires an explicit commit source")
        if self.commit_source is not None:
            _enum(self.commit_source, UserCommitSource, "commit_source")
            state_id(self.correlation.turn_id, "committed turn_id")


@dataclass(frozen=True, slots=True)
class VoiceTurnOrder:
    session_id: str
    turn_id: str
    previous_turn_id: str | None
    observation_order: int

    def __post_init__(self) -> None:
        state_id(self.session_id, "session_id")
        state_id(self.turn_id, "turn_id")
        state_id(self.previous_turn_id, "previous_turn_id", optional=True)
        nonnegative_int(self.observation_order, "observation_order")
        if self.turn_id == self.previous_turn_id:
            raise ValueError("turn cannot precede itself")


@dataclass(frozen=True, slots=True)
class VoiceGeneratedText:
    transcript_id: str
    text: str = field(repr=False)
    completed: bool = False
    part: VoiceAudioPart | None = None

    def __post_init__(self) -> None:
        state_id(self.transcript_id, "transcript_id")
        bounded_text(self.text, MAX_STATE_TEXT, "generated text")
        if type(self.completed) is not bool:
            raise ValueError("completed must be boolean")
        if self.part is not None and not isinstance(self.part, VoiceAudioPart):
            raise ValueError("Generated part identity must be typed")


class VoiceSpeechState(StrEnum):
    QUEUED = "queued"
    GENERATING = "generating"
    PLAYING = "playing"
    COMPLETE = "complete"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"
    UNSPOKEN = "unspoken"


@dataclass(frozen=True, slots=True)
class VoiceSpeechRecord:
    correlation: VoiceCorrelation
    intended_text: str | None = field(default=None, repr=False)
    generated: tuple[VoiceGeneratedText, ...] = ()
    state: VoiceSpeechState = VoiceSpeechState.QUEUED
    generation_status: VoiceGenerationStatus | None = None
    playback_status: VoicePlaybackStatus = VoicePlaybackStatus.UNPLAYED
    played_ms: float | None = 0
    confirmed_text: str | None = field(default=None, repr=False)
    local_active: bool = False
    received_audio_ms: float = 0
    first_played_order: int | None = None
    provider_item_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        correlation_valid(self.correlation)
        if self.correlation.speech_id is None and self.correlation.output_id is None and self.correlation.provider_output_id is None:
            raise ValueError("speech evidence needs speech, local output or provider output identity")
        if self.intended_text is not None:
            bounded_text(self.intended_text, MAX_STATE_TEXT, "intended_text")
        _records(self.generated, VoiceGeneratedText, MAX_GENERATED_PARTS, "generated")
        if len({item.transcript_id for item in self.generated}) != len(self.generated):
            raise ValueError("duplicate generated transcript identity")
        if sum(len(item.text) for item in self.generated) > MAX_STATE_TEXT:
            raise ValueError("generated text exceeds output bound")
        _enum(self.state, VoiceSpeechState, "speech state")
        _enum(self.playback_status, VoicePlaybackStatus, "playback_status")
        if self.generation_status is not None:
            _enum(self.generation_status, VoiceGenerationStatus, "generation_status")
        if self.played_ms is not None:
            nonnegative(self.played_ms, "played_ms")
        nonnegative(self.received_audio_ms, "received_audio_ms")
        if self.first_played_order is not None:
            nonnegative_int(self.first_played_order, "first_played_order")
        if self.played_ms and self.first_played_order is None:
            raise ValueError("played evidence requires observation ordering")
        if not isinstance(self.provider_item_ids, tuple) or len(self.provider_item_ids) > 16 or len(set(self.provider_item_ids)) != len(self.provider_item_ids):
            raise ValueError("provider items must be a bounded unique tuple")
        for item_id in self.provider_item_ids:
            state_id(item_id, "provider_item_id")
        if self.playback_status == VoicePlaybackStatus.UNPLAYED and self.played_ms != 0:
            raise ValueError("unplayed output requires a zero cursor")
        if self.playback_status in (VoicePlaybackStatus.PARTIAL, VoicePlaybackStatus.COMPLETE) and not self.played_ms:
            raise ValueError("played output requires positive cursor")
        if self.confirmed_text is not None:
            bounded_text(self.confirmed_text, MAX_STATE_TEXT, "confirmed_text")
            if not self.played_ms:
                raise ValueError("confirmed words require positive playback evidence")
        if self.state == VoiceSpeechState.COMPLETE and self.playback_status != VoicePlaybackStatus.COMPLETE:
            raise ValueError("complete speech requires complete local playback evidence")
        if type(self.local_active) is not bool:
            raise ValueError("local_active must be boolean")
        if self.state == VoiceSpeechState.UNSPOKEN and (self.played_ms or self.confirmed_text or self.local_active):
            raise ValueError("unspoken speech cannot contain played evidence")
        if self.state == VoiceSpeechState.COMPLETE and self.local_active:
            raise ValueError("complete speech cannot remain locally active")

    @property
    def active(self) -> bool:
        return self.local_active or self.state in (VoiceSpeechState.QUEUED, VoiceSpeechState.GENERATING, VoiceSpeechState.PLAYING)

    @property
    def generated_text(self) -> str:
        return "".join(part.text for part in self.generated)


@dataclass(frozen=True, slots=True)
class VoiceTaskRecord:
    """Summary/reference to Core work. This value never grants execution authority."""

    task_id: str
    source_turn_id: str
    status: WorkStatus
    revision: int
    summary: str = field(default="", repr=False)
    result: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        state_id(self.task_id, "task_id")
        state_id(self.source_turn_id, "source_turn_id")
        _enum(self.status, WorkStatus, "task status")
        nonnegative_int(self.revision, "task revision")
        bounded_text(self.summary, 1000, "task summary")
        if self.result is not None:
            bounded_text(self.result, MAX_STATE_TEXT, "task result")


@dataclass(frozen=True, slots=True)
class SeenVoiceEvent:
    event_id: str
    sequence: int

    def __post_init__(self) -> None:
        state_id(self.event_id, "event_id")
        nonnegative_int(self.sequence, "sequence")


@dataclass(frozen=True, slots=True)
class VoiceConversationSnapshot:
    conversation_id: str
    current_session_id: str | None = None
    lifecycle: FrontendState = FrontendState.NEW
    revision: int = 0
    active_turn_id: str | None = None
    users: tuple[VoiceUserRecord, ...] = ()
    turns: tuple[VoiceTurnOrder, ...] = ()
    speeches: tuple[VoiceSpeechRecord, ...] = ()
    tasks: tuple[VoiceTaskRecord, ...] = ()
    seen_events: tuple[SeenVoiceEvent, ...] = ()
    sequence_floor: int = -1
    last_observed_at: datetime | None = None
    schema_version: int = 1
    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        state_id(self.conversation_id, "conversation_id")
        state_id(self.current_session_id, "current_session_id", optional=True)
        state_id(self.active_turn_id, "active_turn_id", optional=True)
        _enum(self.lifecycle, FrontendState, "lifecycle")
        nonnegative_int(self.revision, "revision")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported voice snapshot version")
        if type(self.sequence_floor) is not int or self.sequence_floor < -1:
            raise ValueError("invalid sequence floor")
        if self.last_observed_at is not None and (not isinstance(self.last_observed_at, datetime) or self.last_observed_at.tzinfo is None or self.last_observed_at.utcoffset() is None):
            raise ValueError("last_observed_at must be timezone-aware")
        for name, cls, limit in (("users", VoiceUserRecord, MAX_USERS), ("turns", VoiceTurnOrder, MAX_TURNS),
                                 ("speeches", VoiceSpeechRecord, MAX_SPEECHES), ("tasks", VoiceTaskRecord, MAX_TASKS),
                                 ("seen_events", SeenVoiceEvent, MAX_SEEN_EVENTS)):
            _records(getattr(self, name), cls, limit, name)
        identities = [((u.correlation.session_id, u.transcript_id)) for u in self.users]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate user transcript identity")
        for values in ([t.turn_id for t in self.turns], [t.task_id for t in self.tasks], [e.event_id for e in self.seen_events], [e.sequence for e in self.seen_events]):
            if len(set(values)) != len(values):
                raise ValueError("duplicate snapshot identity")
        for attr in ("speech_id", "output_id", "provider_output_id"):
            identities = [(s.correlation.session_id, getattr(s.correlation, attr)) for s in self.speeches if getattr(s.correlation, attr) is not None]
            if len(set(identities)) != len(identities):
                raise ValueError("duplicate speech identity")
        turn_map = {t.turn_id: t for t in self.turns}
        if self.active_turn_id is not None and self.active_turn_id not in turn_map:
            raise ValueError("active turn ordering reference is missing")
        for turn in self.turns:
            visited = {turn.turn_id}
            parent = turn.previous_turn_id
            while parent in turn_map:
                if parent in visited:
                    raise ValueError("cyclic turn ordering")
                visited.add(parent)
                parent = turn_map[parent].previous_turn_id
        committed_turns = {u.correlation.turn_id for u in self.users if u.committed}
        if len(committed_turns) != sum(u.committed for u in self.users):
            raise ValueError("duplicate committed turn identity")
        if any(task.source_turn_id not in committed_turns for task in self.tasks):
            raise ValueError("task references require retained committed source turns")
        if any(event.sequence <= self.sequence_floor for event in self.seen_events):
            raise ValueError("seen event precedes retention floor")
        if self.current_session_id is None and (self.seen_events or self.lifecycle != FrontendState.NEW):
            raise ValueError("session state requires a bound session")

    def to_dict(self) -> dict[str, object]:
        """Fresh nested containers every call; never share mutable state."""
        result = asdict(self)
        result["last_observed_at"] = self.last_observed_at.isoformat() if self.last_observed_at else None
        # JSON arrays are explicit even before a JSON encoder is used.
        for name in ("users", "turns", "speeches", "tasks", "seen_events"):
            result[name] = list(result[name])
        for speech in result["speeches"]:
            speech["generated"] = list(speech["generated"])
            speech["provider_item_ids"] = list(speech["provider_item_ids"])
        return result

    @classmethod
    def from_dict(cls, payload: object) -> VoiceConversationSnapshot:
        """Strict public codec: reject extras, malformed identity and impossible evidence."""
        data = _shape(payload, cls)
        data["lifecycle"] = FrontendState(data["lifecycle"])
        if data["last_observed_at"] is not None:
            if not isinstance(data["last_observed_at"], str):
                raise ValueError("invalid snapshot observation time")
            data["last_observed_at"] = datetime.fromisoformat(data["last_observed_at"])
        users = []
        for value in _array(data["users"], MAX_USERS):
            row = _shape(value, VoiceUserRecord)
            row["correlation"] = _decode_correlation(row["correlation"])
            if row["commit_source"] is not None:
                row["commit_source"] = UserCommitSource(row["commit_source"])
            users.append(VoiceUserRecord(**row))
        data["users"] = tuple(users)
        speeches = []
        for value in _array(data["speeches"], MAX_SPEECHES):
            row = _shape(value, VoiceSpeechRecord)
            row["correlation"] = _decode_correlation(row["correlation"])
            generated = []
            for item in _array(row["generated"], MAX_GENERATED_PARTS):
                if not isinstance(item, dict):
                    raise ValueError("Invalid generated text record")
                item = _shape({"part": None, **item}, VoiceGeneratedText)
                if item["part"] is not None:
                    item["part"] = VoiceAudioPart(**_shape(item["part"], VoiceAudioPart))
                generated.append(VoiceGeneratedText(**item))
            row["generated"] = tuple(generated)
            row["provider_item_ids"] = tuple(_array(row["provider_item_ids"], 16))
            row["state"] = VoiceSpeechState(row["state"])
            row["playback_status"] = VoicePlaybackStatus(row["playback_status"])
            if row["generation_status"] is not None:
                row["generation_status"] = VoiceGenerationStatus(row["generation_status"])
            speeches.append(VoiceSpeechRecord(**row))
        data["speeches"] = tuple(speeches)
        tasks = []
        for value in _array(data["tasks"], MAX_TASKS):
            row = _shape(value, VoiceTaskRecord)
            row["status"] = WorkStatus(row["status"])
            tasks.append(VoiceTaskRecord(**row))
        data["tasks"] = tuple(tasks)
        data["turns"] = tuple(VoiceTurnOrder(**_shape(item, VoiceTurnOrder)) for item in _array(data["turns"], MAX_TURNS))
        data["seen_events"] = tuple(SeenVoiceEvent(**_shape(item, SeenVoiceEvent)) for item in _array(data["seen_events"], MAX_SEEN_EVENTS))
        return cls(**data)


def _shape(value: object, cls: type) -> dict:
    if not isinstance(value, dict) or set(value) != {item.name for item in fields(cls)}:
        raise ValueError(f"invalid {cls.__name__} snapshot fields")
    return dict(value)


def _array(value: object, limit: int) -> list:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("invalid snapshot collection")
    return value


def _decode_correlation(value: object) -> VoiceCorrelation:
    result = VoiceCorrelation(**_shape(value, VoiceCorrelation))
    correlation_valid(result)
    return result
