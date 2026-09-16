"""Multi-actor conversation reconstructed from the durable store (Slice 03b end to end).

Real Core (`JarvisCoreApplication`, SQLite store), real loopback protocol and
ingestion route, real voice runtime (`PersistentVoiceRuntime` → `SpeechScheduler`
+ `RealtimeConversationBridge`, fake provider session and audio device), and a
real Control Center `AgentTaskTracker` fed with Claude `stream-json` events, each
process side with its own `ConversationEventForwarder` posting to Core.

Scenario: the user asks, Brain opens work and launches a background sub-agent,
Jarvis starts speaking and is cut by the user while the sub-agent runs, the
surface issues a tool call, the user asks again, Jarvis answers in full, the
sub-agent completes. Core then stops; a fresh repository (restart) reads the
store and `reconstruct_conversation` must show the overlap, the interrupted vs
completed speech, the sub-agent duration and exactly-one trace joins.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jarvis.domain.conversation_event_store import MAX_EVENT_PAGE_LIMIT
from jarvis.domain.conversation_events import (
    ConversationActor,
    ConversationEventType as T,
    reconstruct_conversation,
)
from jarvis.domain.v2 import SpeechKind
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.agent_tasks import AgentTaskTracker
from jarvis.runtime.subagent_conversation import SubagentConversationScope
from jarvis.runtime.conversation_event_forwarder import ConversationEventForwarder, CoreConversationEventTransport
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.realtime_audio import CLAUDE_TOOL
from tests.fakes.conversation_events import (
    assert_drill_down_joins_one_line,
    assert_each_trace_ref_joins_one_line,
    open_store,
    wait_emitter_settled,
)
from tests.integration.async_conversation_harness import CHUNK_MS, TOKEN, free_port, voice_stack, wait_until
from tests.unit.test_agent_tasks import SESSION, agent_call, async_launched, notification


def forwarder_to(port: int, token_file: Path, journal=None, **options) -> ConversationEventForwarder:  # noqa: ANN001
    return ConversationEventForwarder(
        transport=CoreConversationEventTransport(host="127.0.0.1", port=port, token_file=token_file),
        journal=journal, flush_interval_s=options.pop("flush_interval_s", 0.02),
        retry_min_s=options.pop("retry_min_s", 0.02), retry_max_s=options.pop("retry_max_s", 0.1), **options)


def delivered(forwarder: ConversationEventForwarder) -> bool:
    c = forwarder.counters
    return forwarder.pending_count == 0 and c.enqueued == c.appended + c.duplicates + c.conflicts


async def read_store(db: Path, conversation_id: str):
    state, store = await open_store(db)
    try:
        page = await store.list_conversation_events(conversation_id, limit=MAX_EVENT_PAGE_LIMIT)
        assert page.skipped_rows == 0 and not page.has_more
        return [item.event for item in page.events]
    finally:
        await state.close()


async def test_a_multi_actor_conversation_with_an_interruption_during_a_subagent_reconstructs_after_restart(
        tmp_path, monkeypatch):
    token_file = tmp_path / "core.token"
    token_file.write_text(TOKEN, encoding="utf-8")
    voice_events: list[ConversationEventForwarder] = []

    def voice_forwarder(port: int, token: str) -> ConversationEventForwarder:
        assert token == TOKEN
        voice_events.append(forwarder_to(port, token_file))
        return voice_events[-1]

    cc_journal = RuntimeJournal(tmp_path / "control-center")
    tracker = AgentTaskTracker(provider="claude", journal=cc_journal)

    async with voice_stack(tmp_path, monkeypatch, conversation_events_factory=voice_forwarder) as stack:
        cc_events = forwarder_to(stack.port, token_file, journal=cc_journal)
        tracker.conversation_events = cc_events
        cc_events.start()
        try:
            await stack.wake()
            conversation_id = stack.conversation_id

            # 1. User asks; Brain opens the Control Center work of the turn.
            first = await stack.user_says("Prépare mon dossier de vol.")
            work_id = f"brain-turn:{first.correlation_id}"
            await first.start_work(work_id, label="Demande transmise à l'agent local.")

            # 2. The Control Center agent launches a background sub-agent for that ask.
            tracker.begin_conversation_turn(
                SubagentConversationScope(conversation_id, first.correlation_id, work_id), message_uuid="ask-1")
            tracker.turn_started()
            for event in (agent_call("toolu_A", "Rassemble les vols", model="claude-sonnet-5"),
                          async_launched("toolu_A", "agent-a1"),
                          {"type": "result", "subtype": "success", "result": "Lancé.", "session_id": SESSION,
                           "user_message_uuids": ["ask-1"]}):
                tracker.observe_claude(event)

            # 3. Jarvis speaks; the user cuts it after 200 ms while the sub-agent runs.
            progress = await first.say("Je regarde tous les vols de la semaine.", work_id=work_id)
            await stack.wait_spoken(1)
            await stack.session.play_audio(chunks=2)
            await wait_until(lambda: stack.audio.played_output_ms >= 2 * CHUNK_MS, message="audio joué")
            await stack.session.interrupt()
            await stack.journal.wait_until(lambda: stack.journal.count("voice.speech.interrupted") == 1)

            # 4. The surface issues a tool call (refused in continuous mode: still a span).
            await stack.session.tool_call(CLAUDE_TOOL, {"request": "PRIVATE tool argument"}, call_id="call-7")
            await stack.journal.wait_until(lambda: stack.journal.count("tool.result") == 1)

            # 5. The user asks again and hears the whole answer.
            second = await stack.user_says("En fait, seulement le vol de Paul.")
            answer = await second.say("Le vol de Paul part à 9 heures.", kind=SpeechKind.RESULT)
            await stack.wait_spoken(2)
            await stack.speak_and_finish(transcript=answer.text)
            await stack.journal.wait_until(lambda: stack.journal.count("voice.speech.completed") == 1)
            second.finish(public_summary=answer.text)
            first.finish()

            # 6. The sub-agent completes after all of that.
            tracker.observe_claude(notification("agent-a1", "toolu_A", "completed", "Trois vols trouvés."))

            await wait_until(lambda: all(delivered(f) for f in (*voice_events, cc_events)), message="events sent")
            await wait_emitter_settled(stack.core.conversation_event_emitter)
        finally:
            await cc_events.aclose()
    # After teardown: lines written while the voice stopped (and drained to Core) are included.
    voice_journal, core_journal = list(stack.journal.events), list(stack.core_journal.events)

    # Core stopped: a fresh repository reads the durable store (restart).
    events = await read_store(tmp_path / "state" / "jarvis.sqlite3", conversation_id)
    by_type = {}
    for event in events:
        by_type.setdefault(event.event_type, []).append(event)
    assert {event.actor for event in events} == set(ConversationActor) - {ConversationActor.SYSTEM}

    items = reconstruct_conversation(events)
    assert all(not item.anomalies for item in items), [item.anomalies for item in items if item.anomalies]
    speech_items = {item.span_id: item for item in items if item.event_type is T.MOUTH_SPEECH_STARTED}
    interrupted, completed = speech_items[progress.id], speech_items[answer.id]
    assert interrupted.status == "interrupted" and completed.status == "completed"
    [cut] = by_type[T.MOUTH_SPEECH_INTERRUPTED]
    assert dict(cut.attributes)["played_ms"] == 2 * CHUNK_MS and dict(cut.attributes)["reason"] == "user_barge_in"

    [subagent] = [item for item in items if item.actor is ConversationActor.SUBAGENT]
    assert subagent.status == "finished" and subagent.text == "Rassemble les vols"
    assert subagent.ended_at > subagent.started_at  # duration reconstructable from events alone
    # The interrupted speech happened inside the sub-agent span: overlap preserved, not flattened.
    assert subagent.started_at <= interrupted.started_at and interrupted.ended_at <= subagent.ended_at

    [tool] = [item for item in items if item.actor is ConversationActor.TOOL]
    assert tool.status == "finished" and tool.span_id == "call-7"
    assert "PRIVATE" not in repr(events)

    # Causal links resolve to stored Core events.
    ids = {event.event_id for event in events}
    [work_started] = [e for e in by_type[T.BRAIN_WORK_STARTED] if e.work_id == work_id]
    assert {e.parent_event_id for e in events if e.actor is ConversationActor.SUBAGENT} == {work_started.event_id}
    requested = {e.speech_id: e.event_id for e in by_type[T.BRAIN_SPEECH_REQUESTED]}
    for event in events:
        if event.actor is ConversationActor.MOUTH:
            assert event.parent_event_id == requested[event.speech_id]
    assert all(event.parent_event_id in ids for event in events if event.parent_event_id)
    # User turns precede the replies they caused, in store order.
    users = by_type[T.USER_TRANSCRIPT_ACCEPTED]
    assert [e.content for e in users] == ["Prépare mon dossier de vol.", "En fait, seulement le vol de Paul."]

    # Every event with a trace_ref joins exactly one diagnostic journal line, across the three journals.
    cc_lines = read_jsonl_tail(tmp_path / "control-center" / "trace.jsonl", limit=1000)
    assert_each_trace_ref_joins_one_line(events, [*voice_journal, *core_journal, *cc_lines])
    # Slice 04: the Control Center drill-down finds that same line in one interleaved trace file, redacted.
    assert_drill_down_joins_one_line(events, [*voice_journal, *core_journal, *cc_lines], tmp_path / "trace.jsonl")
    for forwarder in (*voice_events, cc_events):
        c = forwarder.counters
        assert (c.invalid, c.conflicts, c.dropped_queue_full, c.dropped_rejected, c.dropped_shutdown) == (0, 0, 0, 0, 0)


def queued_fact(forwarder: ConversationEventForwarder, speech_id: str) -> str:
    event_id = forwarder.record(T.MOUTH_SPEECH_QUEUED, producer="voice.speech_scheduler", conversation_id="conv-r",
                                source_ids=(speech_id,), occurred_at=datetime.now(timezone.utc),
                                correlation_id="corr-r", speech_id=speech_id)
    assert event_id is not None
    return event_id


async def test_voice_events_survive_a_core_restart_with_a_rotated_token(tmp_path):
    """Core down then back with a new session token: the queue waits (bounded) and delivers once."""
    from jarvis.core.v2_app import JarvisCoreApplication

    port = free_port()
    token_file = tmp_path / "core.token"
    token_file.write_text("a" * 48, encoding="utf-8")
    journal_entries: list[dict] = []

    class Journal:
        def emit(self, kind, message, *, level="info", data=None):  # noqa: ANN001
            journal_entries.append({"kind": kind, "level": level, "data": dict(data or {})})

    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token="a" * 48)
    await server.start()
    forwarder = forwarder_to(port, token_file, journal=Journal())
    forwarder.start()
    try:
        first = queued_fact(forwarder, "one")
        await wait_until(lambda: delivered(forwarder), message="first delivery")

        await server.stop()  # Core's protocol goes away
        second = queued_fact(forwarder, "two")
        await wait_until(lambda: any(e["kind"] == "conversation_events.forwarder_unavailable" for e in journal_entries),
                         message="unavailability reported")
        assert forwarder.pending_count == 1

        # Core comes back on the same port with a rotated token; the file is rewritten.
        token_file.write_text("b" * 48, encoding="utf-8")
        server = LocalProtocolServer(core, host="127.0.0.1", port=port, token="b" * 48)
        await server.start()
        await wait_until(lambda: delivered(forwarder), message="delivery after restart")
        assert any(e["kind"] == "conversation_events.forwarder_restored" for e in journal_entries)
        page = await core.conversation_events.list_conversation_events("conv-r")
        assert [item.event.event_id for item in page.events] == [first, second]
    finally:
        await forwarder.aclose()
        await server.stop()
        await core.stop()
