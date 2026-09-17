"""Start-up backfill of `user.transcript.accepted` from durable user turns (Slice 03a rework, option C).

Real Core and SQLite state DB. A "lost" event is simulated by writing the user
turn durably without its event (what a crash between the turn write and the
emitter commit leaves); `test_conversation_event_production.py` does it with a
real process kill.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.core.voice_admission import (
    USER_EVENT_BACKFILL_FAILED_KIND, USER_EVENT_BACKFILL_KIND, USER_EVENT_BACKFILL_MARGIN,
)
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.v2 import AddressingDecision, BrainTurnInput, BrainTurnSource, TurnKind, utc_now
from jarvis.domain.work_attention_prompt import WORK_ATTENTION_WAKE_PROMPT
from tests.fakes.conversation_events import RecordingDiagnostics, wait_emitter_settled
from tests.unit.test_conversation_event_producers import admitted_request


async def start(tmp_path, diagnostics=None) -> JarvisCoreApplication:
    core = JarvisCoreApplication(data_root=tmp_path, diagnostics=diagnostics)
    await core.start()
    await wait_emitter_settled(core.conversation_event_emitter)
    return core


async def user_events(core, conversation_id):
    page = await core.conversation_events.list_conversation_events(conversation_id, limit=500)
    return [item.event for item in page.events if item.event.event_type is T.USER_TRANSCRIPT_ACCEPTED]


def backfill_report(diagnostics):
    return [entry[3] for entry in diagnostics.entries if entry[0] == USER_EVENT_BACKFILL_KIND]


async def test_empty_store_backfills_nothing_even_with_user_history(tmp_path):
    core = await start(tmp_path)
    conversation = await core.conversations.create()
    await core.conversations.append_turn(conversation.id, TurnKind.USER, "Avant la fonctionnalité", correlation_id="old")
    await core.stop()
    diagnostics = RecordingDiagnostics()
    core = await start(tmp_path, diagnostics)
    try:
        assert await user_events(core, conversation.id) == []
        assert backfill_report(diagnostics) == [{"candidates": 0, "recorded": 0, "reason": "empty_store"}]
    finally:
        await core.stop()


async def test_restart_repairs_a_lost_event_and_replays_identical_ones_as_duplicates(tmp_path):
    core = await start(tmp_path)
    try:
        conversation = await core.conversations.create()
        # A: normal admission, its event committed
        accepted = await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, correlation_id="a",
                                                          text="Première question", source=BrainTurnSource.TEXT,
                                                          addressing=AddressingDecision.UNCERTAIN))
        # B: durable user turn whose event was lost; C: too old for the watermark; W: Core wake prompt
        lost = await core.conversations.append_turn(conversation.id, TurnKind.USER, "Question perdue", correlation_id="b")
        old = await core.conversations.append_turn(conversation.id, TurnKind.USER, "Historique ancien", correlation_id="c",
                                                   created_at=utc_now() - USER_EVENT_BACKFILL_MARGIN - timedelta(minutes=5))
        await core.conversations.append_turn(conversation.id, TurnKind.USER, WORK_ATTENTION_WAKE_PROMPT,
                                             correlation_id="w", metadata={"source": "system"})
        await core.conversations.append_turn(conversation.id, TurnKind.ASSISTANT, "Réponse", correlation_id="a")
        await wait_emitter_settled(core.conversation_event_emitter)
        before = await user_events(core, conversation.id)
        assert [e.turn_id for e in before] == [accepted.turn_id]
    finally:
        await core.stop()

    diagnostics = RecordingDiagnostics()
    core = await start(tmp_path, diagnostics)
    try:
        after = await user_events(core, conversation.id)
        assert [e.turn_id for e in after] == [accepted.turn_id, lost.id]
        assert after[0] == before[0]  # rebuilt identically: stored copy untouched
        assert old.id not in {e.turn_id for e in after}
        counters = core.conversation_event_emitter.counters
        assert (counters.enqueued, counters.appended, counters.duplicates, counters.conflicts) == (2, 1, 1, 0)
        assert backfill_report(diagnostics) == [
            {"candidates": 3, "recorded": 2, "limit": 256, "capped": False, "margin_s": 600}]  # wake turn skipped
    finally:
        await core.stop()

    core = await start(tmp_path)  # a third start changes nothing
    try:
        assert [e.turn_id for e in await user_events(core, conversation.id)] == [accepted.turn_id, lost.id]
        assert core.conversation_event_emitter.counters.conflicts == 0
    finally:
        await core.stop()


async def test_direct_admission_session_is_rebuilt_so_the_replay_is_a_duplicate(tmp_path):
    core = await start(tmp_path)
    try:
        request = await admitted_request(core)
        admission = await core.voice_admission.admit_voice_turn(request)
        await wait_emitter_settled(core.conversation_event_emitter)
    finally:
        await core.stop()
    core = await start(tmp_path)
    try:
        events = await user_events(core, request.conversation_id)
        assert [(e.turn_id, e.session_id) for e in events] == [(admission.turn_id, "session-a")]
        counters = core.conversation_event_emitter.counters
        assert (counters.duplicates, counters.conflicts) == (1, 0)
    finally:
        await core.stop()


async def test_backfill_is_capped_newest_first(tmp_path):
    core = await start(tmp_path)
    try:
        conversation = await core.conversations.create()
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, correlation_id="seed", text="Graine"))
        turns = [await core.conversations.append_turn(conversation.id, TurnKind.USER, f"Tour {i}", correlation_id=f"t{i}")
                 for i in range(5)]
        await wait_emitter_settled(core.conversation_event_emitter)
    finally:
        await core.stop()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.state.initialize()
    try:
        diagnostics = RecordingDiagnostics()
        core.voice_admission.diagnostics = diagnostics
        recorded = await core.voice_admission.backfill_user_turns_accepted(core.conversation_events, limit=3)
        await wait_emitter_settled(core.conversation_event_emitter)
        assert recorded == 3
        assert {e.turn_id for e in await user_events(core, conversation.id)} >= {t.id for t in turns[2:]}
        assert turns[0].id not in {e.turn_id for e in await user_events(core, conversation.id)}
        assert backfill_report(diagnostics)[0]["capped"] is True
    finally:
        await core.conversation_event_emitter.stop()
        await core.state.close()


async def test_a_failing_backfill_is_diagnosed_and_never_blocks_core_start(tmp_path, monkeypatch):
    from jarvis.adapters.sqlite_conversation_events import SQLiteConversationEventStore
    from jarvis.domain.conversation_event_store import ConversationEventStoreError

    async def broken(self):
        raise ConversationEventStoreError("conversation event lookup failed: OperationalError: disk I/O error")

    monkeypatch.setattr(SQLiteConversationEventStore, "latest_recorded_at", broken)
    diagnostics = RecordingDiagnostics()
    core = await start(tmp_path, diagnostics)
    try:
        assert core.health.ready is True
        failed = [entry for entry in diagnostics.entries if entry[0] == USER_EVENT_BACKFILL_FAILED_KIND]
        assert failed and failed[0][2] == "error" and failed[0][3]["error_class"] == "ConversationEventStoreError"
    finally:
        await core.stop()


async def test_list_turns_since_filters_kind_time_and_limit(tmp_path):
    core = await start(tmp_path)
    try:
        conversation = await core.conversations.create()
        now = utc_now()
        await core.conversations.append_turn(conversation.id, TurnKind.USER, "vieux", correlation_id="0",
                                             created_at=now - timedelta(hours=1))
        recent = [await core.conversations.append_turn(conversation.id, TurnKind.USER, f"u{i}", correlation_id=f"u{i}",
                                                       created_at=now + timedelta(seconds=i)) for i in range(3)]
        await core.conversations.append_turn(conversation.id, TurnKind.ASSISTANT, "a", correlation_id="a", created_at=now)
        since = now - timedelta(minutes=1)
        assert [t.id for t in await core.state.list_turns_since(since, kind="user", limit=10)] == [t.id for t in recent]
        assert [t.id for t in await core.state.list_turns_since(since, kind="user", limit=2)] == [t.id for t in recent[1:]]
        with pytest.raises(ValueError):
            await core.state.list_turns_since(since.replace(tzinfo=None), kind="user", limit=1)
    finally:
        await core.stop()
