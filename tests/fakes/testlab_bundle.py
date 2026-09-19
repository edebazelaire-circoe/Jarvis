"""Synthetic session evidence for DiagnosticBundle tests (docs/testlab.md, "DiagnosticBundle").

One conversation (`conv-lab`, voice session `sess-lab`) with Conversation Events
and the matching `RuntimeJournal` lines, using journal kinds and data shapes
taken from the live `runtime/trace.jsonl` inventory (2026-09-17):

- s1: normal answer, spoken (queued, dispatched, started, first write, drain);
- s2: real interruption (pending local speech, confirmed barge-in, user turn after);
- s3: superseded, then started and completed anyway (delivered after supersession);
- s4: same payload as s1 (duplicate payload) plus a duplicate span close (reconstruction anomaly);
- s5: self barge-in (confirmed while speaking, no user turn afterwards), slow first audio (latency);
- s6: queued, never delivered, a native audio failure right after (missing delivery outcome with a cause);
- s7: second speech of turn c4, queued while s4 plays (serial playback: raw queue wait above the
  threshold, queue-free wait below it; its first audio is not the turn's first audio);
- s4 also gets a `voice.state.spoken_diverged` (payload divergence);
- user activity (VAD onset and input commits), brain budget and supersession facts, realtime usage;
- provider connect / models failure / error / disconnect, a rejected barge-in, a line of another
  conversation, a torn line, an oversized line, raw provider stream and tool lines;
- one voice session segment closed by `voice.stop`, then a later session that closes the capture window.

Private values are planted everywhere a leak could come from (`SECRET` markers).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from jarvis.domain.conversation_event_export import encode_export_line, export_header, export_trailer
from jarvis.domain.conversation_event_query import encode_stored_event
from jarvis.domain.conversation_event_store import ConversationEventExtent, StoredConversationEvent
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.testlab.bundle_builder import CaptureContext, SessionSelector
from tests.fakes.conversation_events import BASE, make_event

CONVERSATION = "conv-lab"
SESSION = "sess-lab"
OTHER_CONVERSATION = "conv-other"
CONFIGURATION = "ab" * 32
SECRET_MARKERS = ("SECRET", "hunter2", "sk-live", "paul@example.com", "token=abc")
CAPTURED_AT = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)


def at(ms: int) -> datetime:
    return BASE + timedelta(milliseconds=ms)


def _ts(ms: int, micro: int = 123) -> str:
    return (at(ms) + timedelta(microseconds=micro)).isoformat()


def _requested(source: str, speech: str, correlation: str, ms: int, content: str):
    return make_event(T.BRAIN_SPEECH_REQUESTED, source, conversation_id=CONVERSATION, ms=ms,
                      producer="core.brain_service", correlation_id=correlation, speech_id=speech, content=content,
                      attributes={"kind": "result", "priority": "high"})


def _mouth(event_type: T, source: str, speech: str, correlation: str, ms: int, parent, **fields):
    return make_event(event_type, source, conversation_id=CONVERSATION, ms=ms, producer="voice.speech_scheduler",
                      correlation_id=correlation, speech_id=speech, parent_event_id=parent.event_id, **fields)


LYON = "Demain à Lyon, 21 degrés et du soleil."


def session_events() -> list[StoredConversationEvent]:
    r1 = _requested("s1", "s1", "c1", 1200, LYON)
    r2 = _requested("s2", "s2", "c2", 11000, "Il était une fois un dragon qui gardait une montagne.")
    r3 = _requested("s3", "s3", "c3", 14600, "Voici une histoire courte SECRET-DIAGNOSTIC-REQUEST.")
    r4 = _requested("s4", "s4", "c4", 20000, LYON)
    r5 = _requested("s5", "s5", "c5", 30000, "Je lance la recherche tout de suite.")
    r6 = _requested("s6", "s6", "c5", 33000, "Toujours en cours de recherche.")
    r7 = _requested("s7", "s7", "c4", 20015, "Et après-demain, un peu de pluie.")
    events = [
        make_event(T.USER_TRANSCRIPT_ACCEPTED, "t1", conversation_id=CONVERSATION, ms=0, producer="core.voice_admission",
                   correlation_id="c1", turn_id="brain-turn-1", session_id=SESSION,
                   content="Quelle est la météo à Lyon demain ? Écris à paul@example.com via https://u:p@meteo.fr/x?token=abc"),
        make_event(T.BRAIN_TURN_ACCEPTED, "c1", conversation_id=CONVERSATION, ms=50, producer="core.brain_service",
                   correlation_id="c1", turn_id="brain-turn-1"),
        r1,
        _mouth(T.MOUTH_SPEECH_QUEUED, "s1-queued", "s1", "c1", 1210, r1, attributes={"output_id": "o1"}),
        _mouth(T.MOUTH_SPEECH_STARTED, "s1-started", "s1", "c1", 1300, r1, content=LYON,
               attributes={"output_id": "o1"}),
        _mouth(T.MOUTH_SPEECH_COMPLETED, "s1-completed", "s1", "c1", 4000, r1, attributes={"output_id": "o1"}),
        make_event(T.USER_TRANSCRIPT_ACCEPTED, "t2", conversation_id=CONVERSATION, ms=10000,
                   producer="core.voice_admission", correlation_id="c2", turn_id="brain-turn-2", session_id=SESSION,
                   content="Raconte-moi une longue histoire."),
        r2,
        _mouth(T.MOUTH_SPEECH_QUEUED, "s2-queued", "s2", "c2", 11010, r2),
        _mouth(T.MOUTH_SPEECH_STARTED, "s2-started", "s2", "c2", 11100, r2,
               content="Il était une fois un dragon qui gardait une montagne.", attributes={"output_id": "o2"}),
        _mouth(T.MOUTH_SPEECH_INTERRUPTED, "s2-interrupted", "s2", "c2", 13210, r2,
               attributes={"reason": "user_barge_in", "played_ms": 1800, "status": "cancelled"}),
        make_event(T.USER_TRANSCRIPT_ACCEPTED, "t3", conversation_id=CONVERSATION, ms=14520,
                   producer="core.voice_admission", correlation_id="c3", turn_id="brain-turn-3", session_id=SESSION,
                   content="Non, plutôt une courte."),
        r3,
        _mouth(T.MOUTH_SPEECH_QUEUED, "s3-queued", "s3", "c3", 14610, r3),
        _mouth(T.MOUTH_SPEECH_SUPERSEDED, "s3-superseded", "s3", "c3", 14700, r3,
               content="Voici une histoire courte SECRET-DIAGNOSTIC-REQUEST.",
               attributes={"reason": "dependency_revoked"}),
        make_event(T.USER_TRANSCRIPT_ACCEPTED, "t4", conversation_id=CONVERSATION, ms=19000,
                   producer="core.voice_admission", correlation_id="c4", turn_id="brain-turn-4", session_id=SESSION,
                   content="Et demain à Lyon ?"),
        r4,
        _mouth(T.MOUTH_SPEECH_QUEUED, "s4-queued", "s4", "c4", 20010, r4),
        _mouth(T.MOUTH_SPEECH_STARTED, "s4-started", "s4", "c4", 20100, r4, content=LYON,
               attributes={"output_id": "o4"}),
        _mouth(T.MOUTH_SPEECH_COMPLETED, "s4-completed", "s4", "c4", 22000, r4),
        _mouth(T.MOUTH_SPEECH_COMPLETED, "s4-completed-again", "s4", "c4", 22050, r4),
        r7,
        _mouth(T.MOUTH_SPEECH_QUEUED, "s7-queued", "s7", "c4", 20020, r7),
        _mouth(T.MOUTH_SPEECH_STARTED, "s7-started", "s7", "c4", 24050, r7,
               content="Et après-demain, un peu de pluie.", attributes={"output_id": "o7"}),
        _mouth(T.MOUTH_SPEECH_COMPLETED, "s7-completed", "s7", "c4", 29000, r7),
        make_event(T.USER_TRANSCRIPT_ACCEPTED, "t5", conversation_id=CONVERSATION, ms=21000,
                   producer="core.voice_admission", correlation_id="c5", turn_id="brain-turn-5", session_id=SESSION,
                   content="Cherche les vols pour Lisbonne."),
        r5,
        _mouth(T.MOUTH_SPEECH_QUEUED, "s5-queued", "s5", "c5", 30010, r5),
        _mouth(T.MOUTH_SPEECH_STARTED, "s5-started", "s5", "c5", 30100, r5,
               content="Je lance la recherche tout de suite.", attributes={"output_id": "o5"}),
        _mouth(T.MOUTH_SPEECH_INTERRUPTED, "s5-interrupted", "s5", "c5", 31010, r5,
               attributes={"reason": "user_barge_in", "played_ms": 500, "status": "cancelled"}),
        r6,
        _mouth(T.MOUTH_SPEECH_QUEUED, "s6-queued", "s6", "c5", 33010, r6),
        make_event(T.USER_TRANSCRIPT_ACCEPTED, "t6", conversation_id=CONVERSATION, ms=60000,
                   producer="core.voice_admission", correlation_id="c6", turn_id="brain-turn-6", session_id=SESSION,
                   content="Tu es toujours là ?"),
    ]
    events.sort(key=lambda event: (event.occurred_at, event.event_id))
    return [StoredConversationEvent(sequence=index + 1, recorded_at=event.occurred_at, event=event)
            for index, event in enumerate(events)]


def _line(ms: int, journal_kind: str, message: str = "", /, *, level: str = "info", **data) -> dict:
    return {"ts": _ts(ms), "kind": journal_kind, "level": level, "message": message, "data": data}


def _ids(**data) -> dict:
    return {"conversation_id": CONVERSATION, "session_id": SESSION, **data}


def session_trace_entries() -> list[dict | str]:
    """Journal entries in append order; a `str` item is written raw (torn or oversized line)."""
    return [
        _line(-5000, "voice.start", "Voice runtime started"),
        _line(-2000, "voice.connecting", "Opening Realtime session"),
        _line(-1000, "provider.models_failed", "Ajoutez une clé SECRET", provider="anthropic", code="catalog_no_key"),
        _line(-1500, "voice.active", "Realtime session active", conversation_id=CONVERSATION, arch="continuous_brain"),
        _line(-1400, "voice.stack", "Pile vocale", stack="openai_realtime", arch="continuous_brain",
              configuration_id=CONFIGURATION, voice="cedar"),
        _line(-20, "voice.brain_turn_submitted", "SECRET-TRANSCRIPT-MESSAGE", **_ids(
            correlation_id="c1", turn_id="vt1", addressing="addressed", duplicate=False)),
        _line(40, "voice.latency.brain_turn_accepted", "Latence", conversation_id=CONVERSATION, correlation_id="c1",
              turn_id="vt1", measure="transcript_completed_to_brain_turn_accepted", elapsed_ms=60.5),
        _line(45, "agent.event", "assistant", type="assistant", thinking="SECRET-THINKING-BLOCK"),
        _line(60, "tool.call", "reminder_create", call_id="call_1", arguments={"password": "hunter2"}),
        _line(1211, "voice.speech.queued", "SECRET-SPEECH-MESSAGE", **_ids(
            speech_id="s1", correlation_id="c1", work_id="w1", kind="result", priority="high")),
        _line(1250, "voice.speech.dispatched", "Speech dispatched to frontend", **_ids(
            speech_id="s1", correlation_id="c1", output_id="o1", queue_wait_ms=38.0, kind="result")),
        _line(1301, "voice.speech.started", "Speech generation requested", **_ids(
            speech_id="s1", correlation_id="c1", output_id="o1")),
        _line(1302, "voice.output_started", "Sortie vocale ouverte", conversation_id=CONVERSATION, output_id="o1",
              speech_id="s1"),
        _line(1500, "voice.latency.provider_first_pcm", "First provider PCM received", **_ids(
            speech_id="s1", output_id="o1", elapsed_ms=199.0, delivery_boundary="provider_pcm_received")),
        _line(1600, "voice.latency.output_first_write", "Output first write", **_ids(
            speech_id="s1", output_id="o1", elapsed_ms=300.0, source="brain.speech")),
        _line(2000, "voice.state.updated", "Canonical voice state observation", **_ids(code="voice_state_x")),
        _line(3000, "voice.speech.started", "other conversation", conversation_id=OTHER_CONVERSATION,
              session_id=SESSION, speech_id="s-other", output_id="o-other"),
        "{\"ts\": \"" + _ts(3100) + "\", \"kind\": \"voice.speech.queued\", \"data\": {\"conver",
        json.dumps(_line(3200, "voice.transcript", "x" * 300000)),
        _line(3990, "audio.drain_result", "Audio device lifecycle", session_id=SESSION, output_id="o1",
              status="completed", elapsed_ms=180.0, code="audio_drain_completed"),
        _line(4001, "voice.speech.completed", "Speech completed", **_ids(speech_id="s1", output_id="o1")),
        _line(9500, "voice.input_submitted", "Server VAD closed a turn", conversation_id=CONVERSATION,
              captured_bytes=1000, sent_bytes=1000, sent_duration_ms=900.0),
        _line(9990, "voice.brain_turn_submitted", "SECRET-TRANSCRIPT-2", **_ids(correlation_id="c2", turn_id="vt2")),
        _line(11101, "voice.speech.started", "Speech generation requested", **_ids(
            speech_id="s2", correlation_id="c2", output_id="o2")),
        _line(11102, "voice.output_started", "Sortie vocale ouverte", conversation_id=CONVERSATION, output_id="o2",
              speech_id="s2"),
        _line(11400, "voice.latency.output_first_write", "Output first write", **_ids(
            speech_id="s2", output_id="o2", elapsed_ms=400.0)),
        _line(13000, "voice.barge_in_pending", "Parole détectée localement", conversation_id=CONVERSATION,
              authority="acoustic"),
        _line(13200, "voice.barge_in", "L'utilisateur a coupé la parole", **_ids(
            speech_id="s2", output_id="o2", played_ms=1800, stop_latency_ms=2.1, device_stopped=True,
            cleanup_pending=False, measure="local_output_stopped", elapsed_ms=2.1)),
        _line(13211, "voice.speech.interrupted", "Speech interrupted", level="warning", **_ids(
            speech_id="s2", output_id="o2", status="cancelled", played_ms=1800)),
        _line(14200, "voice.input_submitted", "Server VAD closed a turn", conversation_id=CONVERSATION),
        _line(14300, "core.brain.replies_superseded", "SECRET intention text", conversation_id=CONVERSATION,
              correlation_id="c3", work_ids=["w2", "w3"]),
        _line(14500, "voice.brain_turn_submitted", "SECRET-TRANSCRIPT-3", **_ids(
            correlation_id="c3", turn_id="vt3", interrupted_speech_id="s2")),
        _line(14611, "voice.speech.queued", "Speech queued", **_ids(speech_id="s3", correlation_id="c3")),
        _line(14701, "voice.speech.superseded", "Speech presentation retired", **_ids(
            speech_id="s3", correlation_id="c3", reason="dependency_revoked")),
        _line(15000, "voice.speech.started", "Speech generation requested", **_ids(
            speech_id="s3", correlation_id="c3", output_id="o3")),
        _line(17000, "voice.speech.completed", "Speech completed", **_ids(speech_id="s3", output_id="o3")),
        _line(18000, "core.brain.turn_failed", "SECRET-PROVIDER-ERROR", level="error", conversation_id=CONVERSATION,
              correlation_id="c3", error="sk-live-SECRET provider exploded"),
        _line(20101, "voice.speech.started", "Speech generation requested", **_ids(
            speech_id="s4", correlation_id="c4", output_id="o4")),
        _line(20500, "voice.latency.output_first_write", "Output first write", **_ids(
            speech_id="s4", output_id="o4", elapsed_ms=400.0)),
        _line(20021, "voice.speech.queued", "Speech queued", **_ids(speech_id="s7", correlation_id="c4")),
        _line(21000, "voice.state.spoken_diverged", "Canonical voice state observation", **_ids(
            speech_id="s4", code="voice_state_spoken_divergence", revision=12)),
        _line(22001, "voice.speech.completed", "Speech completed", **_ids(speech_id="s4", output_id="o4")),
        _line(24051, "voice.speech.started", "Speech generation requested", **_ids(
            speech_id="s7", correlation_id="c4", output_id="o7")),
        _line(28000, "voice.latency.output_first_write", "Output first write", **_ids(
            speech_id="s7", output_id="o7", elapsed_ms=3950.0)),
        _line(29001, "voice.speech.completed", "Speech completed", **_ids(speech_id="s7", output_id="o7")),
        _line(29500, "core.brain.turn_over_budget", "tour cerveau SECRET", conversation_id=CONVERSATION,
              correlation_id="c5", duration_ms=9200, budget_ms=8000),
        _line(20990, "voice.brain_turn_submitted", "SECRET-TRANSCRIPT-5", **_ids(correlation_id="c5", turn_id="vt5")),
        _line(30101, "voice.speech.started", "Speech generation requested", **_ids(
            speech_id="s5", correlation_id="c5", output_id="o5")),
        _line(30102, "voice.output_started", "Sortie vocale ouverte", conversation_id=CONVERSATION, output_id="o5",
              speech_id="s5"),
        _line(30900, "voice.latency.output_first_write", "Output first write", **_ids(
            speech_id="s5", output_id="o5", elapsed_ms=800.0)),
        _line(31000, "voice.barge_in", "L'utilisateur a coupé la parole", **_ids(
            speech_id="s5", output_id="o5", played_ms=500, stop_latency_ms=1.3, device_stopped=True)),
        _line(31011, "voice.speech.interrupted", "Speech interrupted", level="warning", **_ids(
            speech_id="s5", output_id="o5", status="cancelled", played_ms=500)),
        _line(31500, "voice.transcript_dropped", ".", conversation_id=CONVERSATION, reason="no_letters",
              near_playback=True, code="transcript_no_letters"),
        _line(33011, "voice.speech.queued", "Speech queued", **_ids(speech_id="s6", correlation_id="c5")),
        _line(34000, "audio.native_failed", "Audio device lifecycle", audio_instance_id="dev-1",
              code="audio_native_failed", operation="close", exception_type="RuntimeError"),
        _line(44900, "voice.barge_in_pending", "Parole détectée localement", conversation_id=CONVERSATION,
              authority="acoustic"),
        _line(45000, "provider.error", "Error committing input audio buffer SECRET", level="error",
              code="input_audio_buffer_commit_empty"),
        _line(45100, "voice.barge_in_rejected", "Parole locale non confirmée", **_ids(code="barge_in_not_confirmed")),
        _line(65000, "provider.disconnected", "Connexion Realtime perdue: SECRET", level="warning",
              conversation_id=CONVERSATION, code="realtime_disconnected"),
        _line(62000, "voice.realtime.usage", "Realtime session usage updated", **_ids(
            input_tokens=136, output_tokens=115, duration_seconds=None, source="provider_snapshot")),
        _line(66000, "voice.stop", "Voice runtime stopped"),
        _line(95000, "voice.speech.started", "later conversation", conversation_id=OTHER_CONVERSATION,
              speech_id="s-later"),
        _line(96000, "voice.start", "Voice runtime started (later session)"),
    ]


def write_trace(path: Path, entries: list[dict | str] | None = None) -> list[int]:
    """Write journal lines like `RuntimeJournal` (one JSON per line); returns each line's byte offset."""
    offsets, position = [], 0
    with open(path, "wb") as handle:
        for entry in session_trace_entries() if entries is None else entries:
            text = entry if isinstance(entry, str) else json.dumps(entry, ensure_ascii=False)
            data = (text + "\n").encode("utf-8")
            offsets.append(position)
            handle.write(data)
            position += len(data)
    return offsets


def write_export(path: Path, events: list[StoredConversationEvent] | None = None) -> None:
    events = session_events() if events is None else events
    extent = ConversationEventExtent(len(events), events[0].sequence, events[-1].sequence)
    with open(path, "wb") as handle:
        handle.write(encode_export_line(export_header(CONVERSATION, exported_at=CAPTURED_AT, extent=extent)))
        for stored in events:
            handle.write(encode_export_line(encode_stored_event(stored)))
        handle.write(encode_export_line(export_trailer(events=len(events), skipped_rows=0)))


def selector(**changes) -> SessionSelector:
    return SessionSelector(**{"conversation_id": CONVERSATION, **changes})


def context(**changes) -> CaptureContext:
    return CaptureContext(**{"captured_at": CAPTURED_AT, **changes})
