"""Pins the canonical anchors of `docs/tool-brain-contracts.md` (Tool Brain, Slice S1).

No product behaviour: this file fails when a contract the Tool Brain slices build
on moves. When a later Slice creates something listed in the gap report, it
updates the document and the matching test here in the same change.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import re
import uuid

import pytest

from jarvis.core.conversation_event_emitter import build_conversation_event
from jarvis.core.scene_service import SceneService
from jarvis.domain import scene as scene_module
from jarvis.domain.conversation_events import (
    ATTRIBUTE_KEYS, SPAN_OPENER, TRACE_JOIN_FIELDS, ConversationActor, ConversationEventType as T, ConversationVisibility,
    EventShape, _SPECS, decode_conversation_event, derive_conversation_event_id, encode_conversation_event, event_actor,
    event_shape, event_visibility, reconstruct_conversation,
)
from jarvis.domain.scene import (
    ALLOWED_SCENE_OPS, SceneActor, SceneObjectKind, SceneOp, SceneSnapshot, apply_scene_command, is_runtime_reserved_id,
)
from jarvis.domain.speech_presentation import (
    SpeechChunk, SpeechTextSpan, presentation_chunk_ids, semantic_text_spans, single_output_spans,
)
from jarvis.domain.voice_admission import canonical_admitted_turn_id
from jarvis.runtime.mcp_tool_meta import SERVERS, server_meta, tool_meta

AT = datetime(2026, 10, 7, 9, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------- scene


def test_scene_authority_matrix_is_the_canonical_owner() -> None:
    assert set(ALLOWED_SCENE_OPS) == {SceneActor.RUNTIME, SceneActor.BRAIN, SceneActor.USER}
    # The brain has the user's hand; runtime keeps only projection ops.
    assert ALLOWED_SCENE_OPS[SceneActor.BRAIN] == frozenset(SceneOp)
    assert ALLOWED_SCENE_OPS[SceneActor.USER] == frozenset(SceneOp)
    assert ALLOWED_SCENE_OPS[SceneActor.RUNTIME] == frozenset(
        {SceneOp.UPSERT_OBJECT, SceneOp.PATCH_OBJECT, SceneOp.LINK, SceneOp.UNLINK, SceneOp.ATTACH_SIGNAL})
    # No focus operation exists in the reducer (docs/prefabs.md: "Focus has no op").
    assert not [op for op in SceneOp if "focus" in op.value]


def test_scene_object_kinds_and_actor_values() -> None:
    assert {kind.value for kind in SceneObjectKind} == {"agent", "job", "artifact", "attention", "window", "group"}
    assert {actor.value for actor in SceneActor} == {"runtime", "brain", "user"}


def test_scene_revision_semantics_are_snapshot_level_only() -> None:
    snapshot = SceneSnapshot(scene_id="scene-1")
    assert snapshot.revision == 0
    assert "revision" not in {name for name in scene_module.SceneObject.__dataclass_fields__}
    assert hasattr(SceneService, "apply_if") and inspect.iscoroutinefunction(SceneService.apply_if)
    assert isinstance(SceneService.epoch, property)
    for name in ("snapshot", "patches_since", "wait_for_revision", "apply"):
        assert inspect.iscoroutinefunction(getattr(SceneService, name)), name
    assert scene_module.MAX_REVISION == 2**63 - 1


def test_runtime_reserved_ids_and_brain_id_shape() -> None:
    assert is_runtime_reserved_id("claude:task-1")
    assert is_runtime_reserved_id("attention!x")
    assert is_runtime_reserved_id("parent_of#abc")
    assert not is_runtime_reserved_id("brain-window-0123456789ab")


def test_scene_command_is_a_pure_reducer_call() -> None:
    from jarvis.domain.scene import SceneCommand, Visibility

    command = SceneCommand(op=SceneOp.SET_VISIBILITY, actor=SceneActor.RUNTIME, object_id="x",
                           visibility=Visibility.HIDDEN)
    update = apply_scene_command(SceneSnapshot(scene_id="s"), command)
    # Authority is checked before the scene is even read (unknown object, still rejected_authority).
    assert update.outcome.value == "rejected_authority"
    assert update.reason is not None and update.reason.value == "op_not_allowed"
    assert update.snapshot.revision == 0


# ------------------------------------------------------- Board / Session / MCP


def test_board_and_session_owners_exist() -> None:
    from jarvis.core.board_service import BoardService
    from jarvis.core.session_manager import SessionManager
    from jarvis.core.speech_authority import BOARD_SWITCHED, BOARD_VOICE_BINDING_CHANGED
    from jarvis.domain.workspace_board import (
        BOARD_ID_PREFIX, DEFAULT_BOARD_ID, SESSION_ID_PREFIX, Board, SceneRefKind,
    )

    assert inspect.iscoroutinefunction(BoardService.switch)
    assert "origin" in inspect.signature(BoardService.switch).parameters
    assert inspect.iscoroutinefunction(SessionManager.start_new_session)
    assert "expected_session_id" in inspect.signature(SessionManager.start_new_session).parameters
    assert (DEFAULT_BOARD_ID, BOARD_ID_PREFIX, SESSION_ID_PREFIX) == ("default", "board_", "jsess_")
    assert BOARD_SWITCHED == "board.switched" and BOARD_VOICE_BINDING_CHANGED == "board.voice_binding.changed"
    # The scene is global in V1 and a Board has no revision.
    assert {kind.value for kind in SceneRefKind} == {"global"}
    assert "revision" not in Board.__dataclass_fields__


def test_board_route_origins_are_closed() -> None:
    from jarvis.runtime.board_routes import ORIGINS

    assert ORIGINS == frozenset({"user", "brain"})


def test_mcp_metadata_is_the_single_copy_and_carries_the_ui_projection() -> None:
    names = {meta.server: tuple(meta.tools) for meta in SERVERS}
    assert {"scene_move", "scene_archive", "scene_inspect", "prefab_events"} <= set(names["jarvis-display"])
    assert {"board_switch", "session_new", "board_get_active"} <= set(names["jarvis-workspace"])
    assert tool_meta("jarvis-display", "scene_move").side_effect == "write"
    assert tool_meta("jarvis-display", "scene_archive").side_effect == "destructive"
    assert tool_meta("jarvis-display", "scene_inspect").side_effect == "read"
    assert server_meta("jarvis-display").category == "scene"
    # Gap G2 closed by S2: the UI projection lives in the same single ToolMeta copy (docs/tool-brain-contracts.md §8).
    fields = set(type(tool_meta("jarvis-display", "scene_move")).__dataclass_fields__)
    assert fields == {"label", "side_effect", "idempotent", "atomicity", "output_format", "parameter_rules",
                      "output_notes", "deprecation", "ui_surface", "reversibility", "preconditions",
                      "choice_providers"}


def test_no_browser_or_window_navigation_tool_exists() -> None:
    """Gap G1: browser navigation does not exist. A Slice that creates it must update the contract."""

    banned = {"url", "urls", "browser", "navigate", "navigation", "scroll", "zoom", "focus", "surface", "history",
              "back", "forward", "page", "open"}
    offenders = [f"{meta.server}:{name}" for meta in SERVERS for name in meta.tools if banned & set(name.split("_"))]
    assert offenders == []


def test_catalog_introspects_real_servers_without_invoking_tools() -> None:
    import asyncio

    from jarvis.runtime.mcp_catalog import build_catalog

    catalog = asyncio.run(build_catalog())
    assert isinstance(catalog, dict) and catalog
    text = repr(catalog)
    for key in ("mcp__jarvis-display__scene_move", "side_effect", "input_schema", "parameter_rules"):
        assert key in text


# -------------------------------------------------------------------- speech


def test_chunk_ids_are_deterministic() -> None:
    text = "Premier paragraphe.\n\nSecond paragraphe.\n\nTroisieme."
    spans = semantic_text_spans(text)
    assert len(spans) == 3
    assert spans[0].start == 0 and spans[-1].end == len(text)
    assert all(a.end == b.start for a, b in zip(spans, spans[1:]))
    ids = presentation_chunk_ids("speech-1", spans)
    assert ids == presentation_chunk_ids("speech-1", spans)
    assert len(set(ids)) == 3
    for index, (span, chunk_id) in enumerate(zip(spans, ids)):
        expected = uuid.uuid5(uuid.NAMESPACE_URL, f"jarvis-speech:speech-1:{index}:{span.start}:{span.end}")
        assert chunk_id == str(expected)
    assert presentation_chunk_ids("speech-2", spans) != ids


def test_single_paragraph_keeps_the_request_id() -> None:
    spans = semantic_text_spans("Une seule phrase.")
    assert presentation_chunk_ids("speech-9", spans) == ("speech-9",)


def test_single_output_merge_changes_the_chunk_identity_set() -> None:
    spans = semantic_text_spans("A.\n\nB.")
    merged = single_output_spans(spans)
    assert len(merged) == 1
    # Core registers both identity sets (core/brain_service.py): the mouth may play either.
    assert presentation_chunk_ids("s", merged) == ("s",) != presentation_chunk_ids("s", spans)


def test_chunk_representation() -> None:
    chunk = SpeechChunk("req-1", 1, 3, SpeechTextSpan(10, 20))
    assert chunk.to_payload() == {"chain_id": "req-1", "index": 1, "count": 3, "span": {"start": 10, "end": 20}}
    with pytest.raises(ValueError):
        SpeechChunk("req-1", 3, 3, SpeechTextSpan(0, 1))


def test_scheduler_snapshot_and_interruption_surface() -> None:
    from jarvis.runtime.speech_scheduler import SpeechScheduler

    assert callable(SpeechScheduler.presentation_snapshot)
    for name in ("note_interruption", "note_floor_taken"):
        assert callable(getattr(SpeechScheduler, name)), name
    from jarvis.domain.brain_context import BrainContext, BrainSpeechInterruption, estimate_heard_text

    assert "interruptions" in BrainContext.__dataclass_fields__
    assert {"text", "heard_text", "played_ms", "total_ms"} <= set(BrainSpeechInterruption.__dataclass_fields__)
    # No word alignment: proportional estimate, cut back to a whole word, nothing played = nothing heard.
    assert estimate_heard_text("un deux trois quatre", 0, 1000) == ""
    assert estimate_heard_text("un deux trois quatre", 500, 1000) == "un deux"


# ------------------------------------------------------------ conversation events


def test_event_registry_invariants() -> None:
    assert set(_SPECS) == set(T)
    for event_type in T:
        # `<actor>.<noun>.<verb>` (or `<actor>.<verb>`): the type prefix is the actor value.
        assert event_type.value.startswith(event_actor(event_type).value + "."), event_type
        assert len(event_type.value.split(".")) in (2, 3), event_type
    for closer, opener in SPAN_OPENER.items():
        assert event_shape(closer) is EventShape.SPAN_CLOSE
        assert event_shape(opener) is EventShape.SPAN_OPEN
        assert event_actor(closer) is event_actor(opener)
    assert {actor.value for actor in ConversationActor} == {"user", "mouth", "brain", "subagent", "tool", "system"}
    assert set(TRACE_JOIN_FIELDS) == {"conversation_id", "session_id", "turn_id", "correlation_id", "task_id", "work_id",
                                      "speech_id", "outcome_id"}


def test_speech_and_interruption_event_vocabulary_already_exists() -> None:
    for name in ("mouth.speech.started", "mouth.speech.completed", "mouth.speech.interrupted", "mouth.floor.taken",
                 "mouth.floor.released", "brain.speech.requested", "brain.turn.accepted", "user.transcript.accepted",
                 "tool.call.started", "tool.call.finished"):
        assert T(name)
    assert event_visibility(T.MOUTH_SPEECH_INTERRUPTED) is ConversationVisibility.PUBLIC
    assert event_visibility(T.BRAIN_SPEECH_REQUESTED) is ConversationVisibility.DIAGNOSTIC


def test_tool_brain_events_do_not_exist_yet() -> None:
    """Gap G10: S9 registers `tool_brain` (actor + types). It then flips this test deliberately."""

    assert "tool_brain" not in {actor.value for actor in ConversationActor}
    assert not [event_type for event_type in T if event_type.value.startswith("tool_brain.")]
    # G7 closed by S4: the intent channel is `brain.ui_intent.published` (actor brain, Core-owned), nothing else.
    assert [event_type.value for event_type in T if "ui_intent" in event_type.value] == ["brain.ui_intent.published"]


def test_attribute_allowlist_covers_the_proposed_tool_brain_attributes() -> None:
    needed = {"reason", "code", "status", "kind", "source", "priority", "revision", "model", "tokens", "tool_name",
              "duration_ms", "arguments_redacted", "error_class"}
    assert needed <= ATTRIBUTE_KEYS


def test_ingestion_is_a_denylist_not_an_allowlist() -> None:
    from jarvis.domain.conversation_event_ingest import CORE_OWNED_ACTORS, CORE_PRODUCER_NAMESPACE, is_core_owned

    assert CORE_OWNED_ACTORS == frozenset({ConversationActor.USER, ConversationActor.BRAIN})
    assert CORE_PRODUCER_NAMESPACE == "core"
    event = _event(T.SYSTEM_FAILURE, "p", producer="tool_brain.runtime", source=("x",))
    assert not is_core_owned(event)
    assert is_core_owned(_event(T.SYSTEM_FAILURE, "p", producer="core.tool_brain", source=("x",)))


def _event(event_type, conversation_id="conv-1", *, producer, source, ms=0, **fields):
    if conversation_id == "p":
        conversation_id = "conv-1"
    return build_conversation_event(event_type, producer=producer, conversation_id=conversation_id, source_ids=source,
                                    occurred_at=AT + timedelta(milliseconds=ms), **fields)


def test_user_brain_mouth_correlation_fixture() -> None:
    """User -> Brain -> Mouth chunks -> interruption, joined by correlation_id, chunk id and parent_event_id."""

    conversation, correlation = "conv-1", "corr-1"
    turn_id = "brain-turn-" + "0" * 64
    request_id = "speech-req-1"
    spans = semantic_text_spans("Je regarde.\n\nVoici le resultat.")
    chunk_ids = presentation_chunk_ids(request_id, spans)
    assert len(chunk_ids) == 2

    user = _event(T.USER_TRANSCRIPT_ACCEPTED, conversation, producer="core.voice_admission", source=(turn_id,),
                  correlation_id=correlation, turn_id=turn_id, content="ouvre le bilan")
    accepted = _event(T.BRAIN_TURN_ACCEPTED, conversation, producer="core.brain_service", source=(correlation,),
                      ms=10, correlation_id=correlation, turn_id=turn_id)
    requested = _event(T.BRAIN_SPEECH_REQUESTED, conversation, producer="core.brain_service", source=(request_id,),
                       ms=20, correlation_id=correlation, speech_id=request_id, content="Je regarde.\n\nVoici le resultat.")
    parent = derive_conversation_event_id(producer="core.brain_service", event_type=T.BRAIN_SPEECH_REQUESTED,
                                          conversation_id=conversation, source_ids=(request_id,))
    assert requested.event_id == parent

    mouth = []
    for index, chunk in enumerate(chunk_ids):
        mouth.append(_event(T.MOUTH_SPEECH_QUEUED, conversation, producer="voice.speech_scheduler", source=(chunk,),
                            ms=30 + index, correlation_id=correlation, speech_id=chunk, parent_event_id=parent))
    first = chunk_ids[0]
    started = _event(T.MOUTH_SPEECH_STARTED, conversation, producer="voice.speech_scheduler", source=(first,), ms=100,
                     correlation_id=correlation, speech_id=first, span_id=first, parent_event_id=parent, content="Je regarde.")
    interrupted = _event(T.MOUTH_SPEECH_INTERRUPTED, conversation, producer="voice.speech_scheduler", source=(first,),
                         ms=400, correlation_id=correlation, speech_id=first, span_id=first, parent_event_id=parent,
                         started_at=AT + timedelta(milliseconds=100), attributes={"played_ms": 250, "reason": "barge_in"})
    floor = _event(T.MOUTH_FLOOR_TAKEN, conversation, producer="voice.speech_scheduler", source=("floor-1",), ms=390,
                   correlation_id=correlation, attributes={"while": "speaking"})
    superseded = _event(T.MOUTH_SPEECH_SUPERSEDED, conversation, producer="voice.speech_scheduler", source=(chunk_ids[1],),
                        ms=410, correlation_id=correlation, speech_id=chunk_ids[1], span_id=chunk_ids[1],
                        parent_event_id=parent, attributes={"reason": "floor_taken"})
    events = [user, accepted, requested, *mouth, started, floor, interrupted, superseded]

    for event in events:
        assert decode_conversation_event(encode_conversation_event(event)) == event
    assert {event.correlation_id for event in events} == {correlation}
    assert user.turn_id == accepted.turn_id == turn_id
    assert {event.parent_event_id for event in [*mouth, started, interrupted, superseded]} == {parent}
    assert {event.speech_id for event in mouth} == set(chunk_ids)
    assert started.span_id == interrupted.span_id == first

    items = reconstruct_conversation(events)
    by_span = {item.span_id: item for item in items if item.span_id}
    assert by_span[first].status == "interrupted"
    assert by_span[first].ended_at == AT + timedelta(milliseconds=400)
    assert interrupted.attributes["played_ms"] == 250
    # A Tool Brain trigger "when chunk 1 starts" can be computed before it plays.
    assert chunk_ids[1] == presentation_chunk_ids(request_id, semantic_text_spans("Je regarde.\n\nVoici le resultat."))[1]


def test_canonical_turn_id_shape() -> None:
    turn = canonical_admitted_turn_id("conv-1", "sess-1", "turn-1")
    assert re.fullmatch(r"brain-turn-[0-9a-f]{64}", turn)
    assert turn == canonical_admitted_turn_id("conv-1", "sess-1", "turn-1")
