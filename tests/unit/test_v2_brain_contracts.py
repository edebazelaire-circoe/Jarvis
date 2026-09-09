from __future__ import annotations

import dataclasses
import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.domain.v2 import (
    BrainEvent,
    BrainEventKind,
    BrainRunStatus,
    BrainTurnAcceptance,
    BrainTurnInput,
    BrainTurnResult,
    BrainTurnSource,
    BrainWorkingState,
    PlaybackCursor,
    ProtocolEnvelope,
    SpeechKind,
    SpeechPriority,
    SpeechProvenance,
    SpeechRequest,
    jsonable,
    utc_now,
)
from jarvis.ports.v2 import (
    BrainBackend,
    BrainEventSink,
    RealtimeOutputControl,
    RealtimeSession,
    supports_output_control,
)

REASONING_MARKERS = ("thought", "reason", "scratchpad", "chain_of", "cot", "internal_monologue", "deliberation")

BRAIN_CONTRACTS = (
    SpeechRequest,
    PlaybackCursor,
    BrainTurnInput,
    BrainTurnAcceptance,
    BrainWorkingState,
    BrainEvent,
    BrainTurnResult,
)


def speech(**overrides) -> SpeechRequest:
    payload = {"conversation_id": "conv-1", "text": "Je regarde les mails de Paul."}
    payload.update(overrides)
    return SpeechRequest(**payload)


# --- SpeechRequest -----------------------------------------------------------


def test_speech_request_defaults_are_public_and_interruptible():
    request = speech()
    assert request.kind is SpeechKind.PROGRESS
    assert request.priority is SpeechPriority.NORMAL
    assert request.provenance is SpeechProvenance.BRAIN
    assert request.interruptible is True
    assert request.correlation_id and request.id


@pytest.mark.parametrize(
    "overrides",
    [
        {"conversation_id": ""},
        {"text": "   "},
        {"correlation_id": ""},
        {"created_at": datetime(2026, 9, 9, 12, 0)},
    ],
)
def test_speech_request_rejects_incomplete_values(overrides):
    with pytest.raises(ValueError):
        speech(**overrides)


def test_speech_request_rejects_expiry_before_creation():
    created = utc_now()
    with pytest.raises(ValueError):
        speech(created_at=created, expires_at=created - timedelta(seconds=1))


def test_speech_request_expiry_is_evaluated_against_a_clock():
    created = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    request = speech(created_at=created, expires_at=created + timedelta(seconds=30))
    assert request.is_expired(created + timedelta(seconds=10)) is False
    assert request.is_expired(created + timedelta(seconds=30)) is True
    assert speech(created_at=created).is_expired(created + timedelta(days=1)) is False


def test_speech_priority_orders_by_urgency_then_fifo():
    base = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    low = speech(priority=SpeechPriority.LOW, created_at=base)
    first_normal = speech(priority=SpeechPriority.NORMAL, created_at=base)
    second_normal = speech(priority=SpeechPriority.NORMAL, created_at=base + timedelta(seconds=1))
    immediate = speech(priority=SpeechPriority.IMMEDIATE, created_at=base + timedelta(seconds=5))

    ordered = sorted([second_normal, low, immediate, first_normal], key=lambda item: item.ordering_key)
    assert [item.id for item in ordered] == [immediate.id, first_normal.id, second_normal.id, low.id]


def test_speech_priority_label_round_trip_and_rejection():
    for priority in SpeechPriority:
        assert SpeechPriority.from_label(priority.label) is priority
    assert SpeechPriority.from_label(" Immediate ") is SpeechPriority.IMMEDIATE
    with pytest.raises(ValueError):
        SpeechPriority.from_label("urgent")


def test_result_supersedes_pending_progress_of_the_same_work():
    progress = speech(kind=SpeechKind.PROGRESS, work_id="work-1")
    result = speech(kind=SpeechKind.RESULT, work_id="work-1")
    assert result.supersedes(progress) is True
    assert progress.supersedes(result) is False
    assert result.supersedes(result) is False


def test_supersession_key_wins_over_kind_and_never_crosses_conversations():
    base = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    older = speech(kind=SpeechKind.PROGRESS, supersedes_key="work-1-progress", created_at=base)
    newer = speech(
        kind=SpeechKind.PROGRESS,
        supersedes_key="work-1-progress",
        created_at=base + timedelta(seconds=5),
    )
    assert newer.supersedes(older) is True
    assert older.supersedes(newer) is False

    other_conversation = speech(conversation_id="conv-2", kind=SpeechKind.RESULT, work_id="work-1")
    assert other_conversation.supersedes(speech(kind=SpeechKind.PROGRESS, work_id="work-1")) is False

    unrelated = speech(kind=SpeechKind.RESULT, work_id="work-2")
    assert unrelated.supersedes(speech(kind=SpeechKind.PROGRESS, work_id="work-1")) is False


def test_speech_request_round_trips_through_a_protocol_envelope():
    request = speech(
        kind=SpeechKind.QUESTION,
        priority=SpeechPriority.HIGH,
        work_id="work-1",
        supersedes_key="work-1-progress",
        interruptible=False,
        expires_at=utc_now() + timedelta(minutes=2),
    )
    envelope = ProtocolEnvelope(
        message_type="brain.speech.requested",
        payload=request.to_payload(),
        correlation_id=request.correlation_id,
        conversation_id=request.conversation_id,
    )
    wire = json.loads(json.dumps(jsonable(envelope)))

    assert wire["payload"]["priority"] == "high"
    assert wire["payload"]["kind"] == "question"
    assert wire["payload"]["provenance"] == "brain.speech"
    assert SpeechRequest.from_payload(wire["payload"]) == request


def test_speech_request_dataclass_dump_stays_json_serializable():
    json.dumps(jsonable(speech(priority=SpeechPriority.IMMEDIATE)))


# --- PlaybackCursor ----------------------------------------------------------


def test_playback_cursor_requires_a_speech_id_and_a_positive_position():
    cursor = PlaybackCursor(speech_id="speech-1", played_ms=1200, provider_response_id="resp-1")
    assert cursor.played_ms == 1200
    with pytest.raises(ValueError):
        PlaybackCursor(speech_id="")
    with pytest.raises(ValueError):
        PlaybackCursor(speech_id="speech-1", played_ms=-1)


# --- BrainTurnInput / acceptance --------------------------------------------


def test_brain_turn_deduplicates_on_correlation_id_only():
    turn = BrainTurnInput(conversation_id="conv-1", text="Regarde plutot les mails de Paul.")
    assert turn.dedup_key == turn.correlation_id
    assert turn.secondary_dedup_key is None

    with_provider = BrainTurnInput(conversation_id="conv-1", text="x", provider_item_id="item_42")
    assert with_provider.dedup_key == with_provider.correlation_id
    assert with_provider.secondary_dedup_key == "item_42"


@pytest.mark.parametrize(
    "overrides",
    [{"conversation_id": ""}, {"text": ""}, {"correlation_id": ""}, {"received_at": datetime(2026, 9, 9, 12, 0)}],
)
def test_brain_turn_rejects_incomplete_values(overrides):
    payload = {"conversation_id": "conv-1", "text": "bonjour"}
    payload.update(overrides)
    with pytest.raises(ValueError):
        BrainTurnInput(**payload)


def test_brain_turn_payload_round_trip_keeps_interruption_metadata():
    turn = BrainTurnInput(
        conversation_id="conv-1",
        text="Non, seulement les mails de Paul.",
        source=BrainTurnSource.REALTIME,
        provider_item_id="item_42",
        interrupted_speech_id="speech-9",
    )
    payload = json.loads(json.dumps(jsonable(turn.to_payload())))
    assert payload["content"] == turn.text
    assert BrainTurnInput.from_payload(payload) == turn


def test_brain_turn_acceptance_validates_revision_and_exposes_dedup_state():
    acceptance = BrainTurnAcceptance(
        turn_id="turn-1",
        conversation_id="conv-1",
        correlation_id="corr-1",
        revision=7,
        duplicate=True,
    )
    assert acceptance.to_payload()["revision"] == 7
    assert acceptance.to_payload()["duplicate"] is True
    with pytest.raises(ValueError):
        BrainTurnAcceptance(turn_id="turn-1", conversation_id="conv-1", correlation_id="corr-1", revision=-1)
    with pytest.raises(ValueError):
        BrainTurnAcceptance(turn_id="", conversation_id="conv-1", correlation_id="corr-1")


# --- BrainWorkingState -------------------------------------------------------


def test_working_state_public_payload_exposes_counts_not_question_text():
    state = BrainWorkingState(
        conversation_id="conv-1",
        revision=8,
        current_user_intent="Restreindre la recherche aux mails de Paul",
        active_work_ids=("work-1",),
        unresolved_questions=("Faut-il inclure les archives ?",),
        completed_work_ids=("work-0", "work-2"),
    )
    payload = state.to_public_payload()
    assert payload["unresolved_question_count"] == 1
    assert payload["completed_work_count"] == 2
    assert payload["active_work_ids"] == ["work-1"]
    assert "Faut-il inclure les archives ?" not in json.dumps(payload)


def test_working_state_rejects_missing_conversation_or_negative_revision():
    with pytest.raises(ValueError):
        BrainWorkingState(conversation_id="")
    with pytest.raises(ValueError):
        BrainWorkingState(conversation_id="conv-1", revision=-1)


# --- BrainEvent / BrainTurnResult -------------------------------------------


def test_brain_event_binds_speech_to_its_own_conversation():
    request = speech()
    event = BrainEvent(
        kind=BrainEventKind.SPEECH,
        conversation_id="conv-1",
        correlation_id="corr-1",
        speech=request,
    )
    assert event.speech is request

    with pytest.raises(ValueError):
        BrainEvent(kind=BrainEventKind.SPEECH, conversation_id="conv-1", correlation_id="corr-1")
    with pytest.raises(ValueError):
        BrainEvent(
            kind=BrainEventKind.SPEECH,
            conversation_id="conv-2",
            correlation_id="corr-1",
            speech=request,
        )
    with pytest.raises(ValueError):
        BrainEvent(
            kind=BrainEventKind.PROGRESS,
            conversation_id="conv-1",
            correlation_id="corr-1",
            speech=request,
        )


def test_brain_failure_events_and_results_must_name_the_error():
    with pytest.raises(ValueError):
        BrainEvent(kind=BrainEventKind.FAILED, conversation_id="conv-1", correlation_id="corr-1")
    with pytest.raises(ValueError):
        BrainTurnResult(correlation_id="corr-1", status=BrainRunStatus.FAILED)
    with pytest.raises(ValueError):
        BrainTurnResult(correlation_id="corr-1", status=BrainRunStatus.COMPLETED, error="boom")

    failed = BrainTurnResult(correlation_id="corr-1", status=BrainRunStatus.FAILED, error="provider_unavailable")
    assert failed.error == "provider_unavailable"
    assert BrainTurnResult(correlation_id="corr-1").status is BrainRunStatus.COMPLETED


# --- Decision 12: no hidden reasoning ---------------------------------------


def test_brain_contracts_expose_no_hidden_reasoning_field():
    for contract in BRAIN_CONTRACTS:
        for name in (f.name for f in dataclasses.fields(contract)):
            lowered = name.lower()
            assert not any(marker in lowered for marker in REASONING_MARKERS), f"{contract.__name__}.{name}"


def test_serialized_brain_payloads_expose_no_hidden_reasoning_key():
    payloads = [
        speech().to_payload(),
        BrainTurnInput(conversation_id="conv-1", text="bonjour").to_payload(),
        BrainTurnAcceptance(turn_id="t", conversation_id="conv-1", correlation_id="c").to_payload(),
        BrainWorkingState(conversation_id="conv-1").to_public_payload(),
    ]
    for payload in payloads:
        for key in payload:
            assert not any(marker in key.lower() for marker in REASONING_MARKERS), key


# --- Ports -------------------------------------------------------------------


class _OutputControlStub:
    async def speak(self, request: SpeechRequest) -> str:
        return "resp-1"

    async def cancel_output(self, cursor: PlaybackCursor | None = None) -> None:
        return None

    async def truncate(self, cursor: PlaybackCursor) -> None:
        return None


class _LegacySessionStub:
    async def send_audio(self, pcm: bytes) -> None: ...
    async def finish_input(self) -> bool:
        return True

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None: ...
    async def send_context(self, text: str) -> None: ...
    async def keepalive(self) -> None: ...
    async def events(self): ...
    async def close(self) -> None: ...


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[BrainEvent] = []

    async def emit(self, event: BrainEvent) -> None:
        self.events.append(event)


class _EchoBackend:
    async def run_turn(self, turn: BrainTurnInput, state: BrainWorkingState, emit: BrainEventSink) -> BrainTurnResult:
        await emit.emit(
            BrainEvent(
                kind=BrainEventKind.SPEECH,
                conversation_id=turn.conversation_id,
                correlation_id=turn.correlation_id,
                speech=SpeechRequest(
                    conversation_id=turn.conversation_id,
                    text=turn.text,
                    kind=SpeechKind.RESULT,
                    correlation_id=turn.correlation_id,
                ),
            )
        )
        return BrainTurnResult(correlation_id=turn.correlation_id)


def test_realtime_session_port_is_not_widened_by_the_output_control_port():
    """Decision 22: les implementations et doubles existants ne doivent pas casser."""

    assert {name for name in dir(RealtimeSession) if not name.startswith("_")} == {
        "send_audio",
        "finish_input",
        "send_tool_result",
        "send_context",
        "keepalive",
        "events",
        "close",
    }
    assert {name for name in dir(RealtimeOutputControl) if not name.startswith("_")} == {
        "speak",
        "cancel_output",
        "truncate",
    }


def test_output_control_capability_is_detectable_at_runtime():
    assert supports_output_control(_OutputControlStub()) is True
    assert supports_output_control(_LegacySessionStub()) is False
    assert supports_output_control(object()) is False


def test_brain_backend_port_matches_its_production_adapter():
    """Ce que ce test prouve : la forme reelle du port, tenue contre l'adaptateur reel.

    `BrainBackend` n'est pas `@runtime_checkable` — annoter un double
    `backend: BrainBackend = _EchoBackend()` ne verifie donc rien a l'execution,
    l'annotation est inerte. La seule preuve utile est structurelle : la
    signature du port et celle de son unique implementation de production
    doivent rester identiques. `ControlCenterBrainBackend` n'est pas instancie —
    la classe suffit, et l'instancier ouvrirait une session HTTP.

    Casse si le port gagne une methode, si un parametre est renomme, reordonne
    ou retype, ou si l'adaptateur derive de la signature du port.
    """

    from jarvis.adapters.control_center_brain import ControlCenterBrainBackend

    assert [name for name in vars(BrainBackend) if not name.startswith("_")] == ["run_turn"]
    assert inspect.iscoroutinefunction(ControlCenterBrainBackend.run_turn)
    assert inspect.signature(ControlCenterBrainBackend.run_turn) == inspect.signature(BrainBackend.run_turn)


async def test_a_backend_drives_the_event_sink_it_is_handed():
    """Ce que ce test prouve : le contrat d'`emit`, sur un double, et rien de plus.

    Un backend conforme decrit ce qu'il fait via le puits qu'on lui passe et
    rend une issue portant le meme `correlation_id` que le tour. Il ne prouve
    aucun cablage de production : le backend et le puits sont tous deux des
    doubles de ce fichier. La forme du port face au vrai adaptateur est
    verifiee par `test_brain_backend_port_matches_its_production_adapter`.
    """

    backend = _EchoBackend()
    sink = _RecordingSink()
    turn = BrainTurnInput(conversation_id="conv-1", text="Resume ma journee.")
    state = BrainWorkingState(conversation_id="conv-1")

    result = await backend.run_turn(turn, state, sink)

    assert result.status is BrainRunStatus.COMPLETED
    assert result.correlation_id == turn.correlation_id
    assert [event.kind for event in sink.events] == [BrainEventKind.SPEECH]
    assert sink.events[0].speech is not None
    assert sink.events[0].speech.text == turn.text
