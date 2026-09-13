from __future__ import annotations

from dataclasses import asdict, replace
import asyncio
import json
import socket
import threading

import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.core.voice_ledger import VoiceLedgerService
from jarvis.domain import voice_events as events
from jarvis.domain.v2 import ConversationTurn, TurnKind
from jarvis.domain.voice_event_codec import encode_voice_event
from jarvis.domain.voice_frontend import FrontendState, VoiceCorrelation, VoiceSessionId
from jarvis.domain.voice_state import VoiceConversationSnapshot
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from tests.fakes.voice_frontend import FakeVoiceFrontend


SESSION = VoiceCorrelation(VoiceSessionId("session-a"))
TURN = replace(SESSION, turn_id="turn-a")
OUTPUT = replace(TURN, speech_id="speech-a", output_id="local-a", provider_output_id="response-a")


def observation(source, payload, correlation=OUTPUT):
    return encode_voice_event(source.event(payload, correlation=correlation))


@pytest.fixture
async def stack(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token="t" * 48)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token="t" * 48)
    try:
        yield core, server, client
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def test_authenticated_ingress_owns_evidence_without_duplicate_user_or_unheard_history(stack):
    core, _, client = stack
    conversation_id = (await client.create_conversation())["id"]
    assert (await client.voice_snapshot(conversation_id))["snapshot"] is None
    await client.append_turn(conversation_id, kind="assistant", content="legacy history")
    assert (await client.context(conversation_id))["recent_turns"][0]["content"] == "legacy history"
    bound = await client.bind_voice_session(conversation_id, SESSION.session_id)
    assert bound["result"]["disposition"] == "applied"
    assert (await client.context(conversation_id))["recent_turns"] == []
    await client.submit_brain_turn(conversation_id, content="question", correlation_id=TURN.turn_id)
    source = FakeVoiceFrontend()
    user = [
        observation(source, events.UserTurnOpened(None, events.VoiceActivitySource.PROVIDER), TURN),
        observation(source, events.UserTranscriptCommitted("user", "question", 1, events.UserCommitSource.PROVIDER), TURN),
    ]
    await client.submit_voice_observations(conversation_id, SESSION.session_id, user)
    assert len([turn for turn in await core.conversations.list_turns(conversation_id, limit=20) if turn.kind.value == "user"]) == 1
    queued = await client.register_voice_speech(conversation_id, asdict(OUTPUT), "intended but unspoken")
    assert queued["result"]["disposition"] == "applied"
    generated = observation(source, events.AssistantTranscriptCompleted("generated", "provider paraphrase"))
    result = await client.submit_voice_observations(conversation_id, SESSION.session_id, [generated])
    assert result["history_updates"] == 0
    assert [t["content"] for t in (await client.context(conversation_id))["recent_turns"]] == ["question"]
    heard = observation(source, events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.PARTIAL, 20, "heard"))
    assert (await client.submit_voice_observations(conversation_id, SESSION.session_id, [heard]))["history_updates"] == 1
    retry = await client.submit_voice_observations(conversation_id, SESSION.session_id, [heard])
    assert retry["results"][0]["disposition"] == "duplicate" and retry["history_updates"] == 0
    extension = observation(source, events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.COMPLETE, 40, "heard more"))
    await client.submit_voice_observations(conversation_id, SESSION.session_id, [extension])
    archived = [turn for turn in await core.conversations.list_turns(conversation_id, limit=30) if turn.metadata.get("voice_evidence")]
    assert [turn.content for turn in archived] == ["heard", " more"]
    assert [turn.metadata["delivery"] for turn in archived] == ["partial", "complete"]
    assert [t["content"] for t in (await client.context(conversation_id))["recent_turns"]] == ["question", "heard more"]
    with pytest.raises(CoreProtocolError) as refused:
        await client.append_turn(conversation_id, kind="assistant", content="bypass intended")
    assert refused.value.status == 400
    snapshot = VoiceConversationSnapshot.from_dict((await client.voice_snapshot(conversation_id))["snapshot"])
    assert snapshot.speeches[0].intended_text == "intended but unspoken"
    assert snapshot.speeches[0].generated_text == "provider paraphrase"


async def test_batch_validation_is_atomic_and_sessions_cannot_be_spoofed(stack):
    core, server, client = stack
    conversation_id = (await client.create_conversation())["id"]
    await client.bind_voice_session(conversation_id, SESSION.session_id)
    source = FakeVoiceFrontend()
    valid = observation(source, events.AssistantAudioReceived(20))
    malformed = {**valid, "provider_raw": {"private": "data"}}
    for batch in ([], [valid] * 33, [valid, malformed]):
        with pytest.raises(CoreProtocolError) as failed:
            await client.submit_voice_observations(conversation_id, SESSION.session_id, batch)
        assert failed.value.status == 400
    assert (await client.voice_snapshot(conversation_id))["snapshot"]["speeches"] == []
    with pytest.raises(CoreProtocolError):
        await client.submit_voice_observations(conversation_id, "different-batch-session", [valid])
    malformed_pcm = {**valid, "payload": {"kind": "assistant.audio_chunk", "audio": "AAAA"}}
    with pytest.raises(CoreProtocolError):
        await client.submit_voice_observations(conversation_id, SESSION.session_id, [malformed_pcm])
    wrong = LocalCoreClient(host="127.0.0.1", port=server.port, token="wrong")
    try:
        with pytest.raises(CoreProtocolError) as failed:
            await wrong.bind_voice_session(conversation_id, "hijack")
        assert failed.value.status == 401
    finally:
        await wrong.close()
    with pytest.raises(CoreProtocolError) as missing:
        await client.voice_snapshot("missing-conversation")
    assert missing.value.status == 404
    core.health.ready = False
    with pytest.raises(CoreProtocolError) as stopping:
        await client.submit_voice_observations(conversation_id, SESSION.session_id, [valid])
    assert stopping.value.status == 503


async def test_output_only_identity_multiple_items_and_cumulative_audio_survive_roundtrip(stack):
    _, _, client = stack
    conversation_id = (await client.create_conversation())["id"]
    await client.bind_voice_session(conversation_id, SESSION.session_id)
    source = FakeVoiceFrontend()
    local = replace(SESSION, output_id="local-output")
    response = replace(local, provider_output_id="response", provider_item_id="item-one")
    second = replace(response, provider_item_id="item-two")
    payloads = [
        observation(source, events.AssistantAudioReceived(20), local),
        observation(source, events.AssistantTranscriptCompleted("part-one", "first "), response),
        observation(source, events.AssistantTranscriptCompleted("part-two", "second"), second),
        observation(source, events.AssistantAudioReceived(40), second),
    ]
    result = await client.submit_voice_observations(conversation_id, SESSION.session_id, payloads)
    assert all(item["disposition"] == "applied" for item in result["results"])
    snapshot = VoiceConversationSnapshot.from_dict((await client.voice_snapshot(conversation_id))["snapshot"])
    assert len(snapshot.speeches) == 1
    speech = snapshot.speeches[0]
    assert speech.generated_text == "first second"
    assert speech.received_audio_ms == 40
    assert speech.provider_item_ids == ("item-one", "item-two")
    assert speech.correlation.provider_item_id is None
    assert speech.correlation.output_id == "local-output"


async def test_speech_lineage_survives_sparse_events_without_inventing_canonical_task(stack):
    core, _, client = stack
    conversation_id = (await client.create_conversation())["id"]
    await client.bind_voice_session(conversation_id, SESSION.session_id)
    lineage = replace(OUTPUT, source_correlation_id="brain-correlation", backend_work_id="backend-work")
    result = await client.register_voice_speech(conversation_id, asdict(lineage), "intended")
    assert result["result"]["disposition"] == "applied"
    source = FakeVoiceFrontend()
    await client.submit_voice_observations(conversation_id, SESSION.session_id, [
        observation(source, events.AssistantAudioReceived(20)),
    ])
    snapshot = VoiceConversationSnapshot.from_dict((await client.voice_snapshot(conversation_id))["snapshot"])
    assert snapshot.speeches[0].correlation == lineage
    assert snapshot.speeches[0].correlation.task_id is None
    assert snapshot.tasks == ()
    conflict = observation(source, events.AssistantAudioReceived(30), replace(lineage, backend_work_id="other-work"))
    result = await client.submit_voice_observations(conversation_id, SESSION.session_id, [conflict])
    assert result["results"][0]["code"] == "voice_state_correlation_conflict"
    assert (await client.voice_snapshot(conversation_id))["snapshot"]["speeches"][0]["received_audio_ms"] == 20
    await client.submit_voice_observations(conversation_id, SESSION.session_id, [
        observation(source, events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.PARTIAL, 10, "heard")),
    ])
    archived = (await core.history.read(conversation_id=conversation_id))[0]
    assert archived.correlation_id == "brain-correlation"
    assert archived.metadata["source_correlation_id"] == "brain-correlation"
    assert archived.metadata["backend_work_id"] == "backend-work"
    assert archived.metadata["task_id"] is None


async def test_projection_chronology_uses_playback_order_and_never_scans_archive(stack, monkeypatch):
    core, _, client = stack
    conversation_id = (await client.create_conversation())["id"]
    await client.bind_voice_session(conversation_id, SESSION.session_id)
    second = replace(OUTPUT, speech_id="speech-b", output_id="local-b", provider_output_id="response-b")
    await client.register_voice_speech(conversation_id, asdict(OUTPUT), "first request")
    await client.register_voice_speech(conversation_id, asdict(second), "second request")
    async def forbidden_scan(**kwargs):
        raise AssertionError("archive scan entered hot path")
    monkeypatch.setattr(core.history, "read", forbidden_scan)
    source = FakeVoiceFrontend()
    observations = [
        observation(source, events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.COMPLETE, 10, "second heard first"), second),
        observation(source, events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.COMPLETE, 10, "first heard later"), OUTPUT),
    ]
    await client.submit_voice_observations(conversation_id, SESSION.session_id, observations)
    turns = await core.conversations.list_turns(conversation_id)
    assert [turn.content for turn in turns] == ["second heard first", "first heard later"]


@pytest.mark.parametrize("failure_point", ["before_turn", "before_archive", "before_index_complete"])
@pytest.mark.parametrize("restart", [False, True])
async def test_exact_pending_range_recovers_before_extended_confirmation(tmp_path, monkeypatch, failure_point, restart):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    conversation_id = (await core.conversations.create()).id
    await core.voice_ledger.bind_session(conversation_id, SESSION.session_id)
    source = FakeVoiceFrontend()
    first = observation(source, events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.PARTIAL, 20, "hello"))
    target, method = {
        "before_turn": (core.conversations, "append_turn"),
        "before_archive": (core.history, "append"),
        "before_index_complete": (core.state, "complete_voice_projection"),
    }[failure_point]
    original = getattr(target, method)
    async def failure(*args, **kwargs):
        raise OSError("injected projection failure")
    monkeypatch.setattr(target, method, failure)
    try:
        with pytest.raises(OSError):
            await core.voice_ledger.ingest(conversation_id, SESSION.session_id, [first])
        typed = VoiceConversationSnapshot.from_dict((await core.voice_ledger.snapshot(conversation_id))["snapshot"]).speeches[0]
        key = core.voice_ledger._output_key(conversation_id, typed)
        offset, pending = await core.state.get_voice_projection(conversation_id, key)
        assert offset == 0 and pending.content == "hello"
        assert pending.metadata["confirmed_start"] == 0 and pending.metadata["confirmed_end"] == 5
        monkeypatch.setattr(target, method, original)
        if restart:
            await core.stop()
            core = JarvisCoreApplication(data_root=tmp_path)
            await core.start()
            await core.voice_ledger.bind_session(conversation_id, SESSION.session_id)
        longer = observation(source, events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.COMPLETE, 30, "hello!!"))
        await core.voice_ledger.ingest(conversation_id, SESSION.session_id, [longer])
        records = [record for record in await core.history.read(conversation_id=conversation_id) if record.metadata.get("voice_evidence")]
        assert [record.content for record in records] == ["hello", "!!"]
        assert [(record.metadata["confirmed_start"], record.metadata["confirmed_end"]) for record in records] == [(0, 5), (5, 7)]
        assert len({record.id for record in records}) == 2
        assert await core.state.get_voice_projection(conversation_id, key) == (7, None)
    finally:
        await core.stop()


async def test_interrupted_complete_audio_archives_partial_words_and_real_journal_is_private(tmp_path, monkeypatch):
    from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail

    journal = RuntimeJournal(tmp_path / "runtime")
    core = JarvisCoreApplication(data_root=tmp_path / "data", diagnostics=journal)
    await core.start()
    try:
        conversation_id = (await core.conversations.create()).id
        await core.voice_ledger.bind_session(conversation_id, SESSION.session_id)
        source = FakeVoiceFrontend()
        batch = [
            observation(source, events.AssistantTranscriptCompleted("generated", "PRIVATE_GENERATED_TAIL")),
            observation(source, events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.PARTIAL, 10, "PRIVATE_HEARD")),
            observation(source, events.UserInterruption(events.VoiceInterruptionStage.CONFIRMED, events.VoiceActivitySource.LOCAL)),
            observation(source, events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.COMPLETE, 10)),
        ]
        original = core.history.append
        async def fail(record):
            raise OSError("PRIVATE_STORAGE_DETAIL")
        monkeypatch.setattr(core.history, "append", fail)
        with pytest.raises(OSError):
            await core.voice_ledger.ingest(conversation_id, SESSION.session_id, batch)
        monkeypatch.setattr(core.history, "append", original)
        await core.voice_ledger.ingest(conversation_id, SESSION.session_id, batch)
        records = await core.history.read(conversation_id=conversation_id)
        assert len(records) == 1 and records[0].content == "PRIVATE_HEARD"
        assert records[0].metadata["delivery"] == "partial"
        errors = read_jsonl_tail(journal.error_path)
        assert [row["data"]["code"] for row in errors] == ["voice_history_projection_failed"]
        rows = read_jsonl_tail(journal.trace_path)
        assert any(row["kind"] == "voice.ledger.projected" and row["level"] == "info" for row in rows)
        assert "PRIVATE_" not in json.dumps(rows)
    finally:
        await core.stop()


async def test_stopped_ledger_eviction_recovers_heard_state_and_failure_does_not_evict(tmp_path, monkeypatch):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    service = VoiceLedgerService(core.conversations, max_conversations=1)
    try:
        first = (await core.conversations.create()).id
        second = (await core.conversations.create()).id
        await service.bind_session(first, SESSION.session_id)
        with pytest.raises(ValueError, match="capacity"):
            await service.bind_session(second, "session-b")
        source = FakeVoiceFrontend()
        await service.ingest(first, SESSION.session_id, [
            observation(source, events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.COMPLETE, 20, "preserved heard")),
            observation(source, events.FrontendLifecycleChanged(FrontendState.STOPPED), SESSION),
        ])
        original = core.state.save_voice_snapshot
        async def fail(snapshot):
            raise OSError("snapshot unavailable")
        monkeypatch.setattr(core.state, "save_voice_snapshot", fail)
        with pytest.raises(OSError):
            await service.bind_session(second, "session-b")
        assert (await service.snapshot(first))["snapshot"]["speeches"][0]["confirmed_text"] == "preserved heard"
        monkeypatch.setattr(core.state, "save_voice_snapshot", original)
        await service.bind_session(second, "session-b")
        await service.ingest(second, "session-b", [observation(FakeVoiceFrontend(), events.FrontendLifecycleChanged(FrontendState.STOPPED), replace(SESSION, session_id="session-b"))])
        rebound = await service.bind_session(first, "session-c")
        assert rebound["result"]["disposition"] == "applied"
        assert (await service.snapshot(first))["snapshot"]["speeches"][0]["confirmed_text"] == "preserved heard"
        stale = await service.ingest(first, SESSION.session_id, [observation(source, events.AssistantPlaybackEvidence(events.VoicePlaybackStatus.COMPLETE, 30, "old tail"))])
        assert stale["results"][0]["disposition"] == "stale_session"
    finally:
        await core.stop()


@pytest.mark.parametrize("next_operation", ["read", "close"])
@pytest.mark.parametrize("worker_fails", [False, True])
async def test_cancelled_sqlite_stage_retains_connection_until_worker_finishes(tmp_path, monkeypatch, next_operation, worker_fails):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    release = threading.Event()
    worker_finished = threading.Event()
    entered = asyncio.Event()
    loop = asyncio.get_running_loop()
    stage = following = None
    try:
        conversation_id = (await core.conversations.create()).id
        original = core.state._voice_projection
        def blocked(conn, conversation_id, output_key):
            assert conn.in_transaction
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(3):
                raise TimeoutError("test worker was not released")
            if worker_fails:
                raise OSError("injected native failure")
            return original(conn, conversation_id, output_key)
        monkeypatch.setattr(core.state, "_voice_projection", blocked)
        turn = ConversationTurn(conversation_id=conversation_id, kind=TurnKind.ASSISTANT,
                                content="heard", metadata={"confirmed_end": 5})
        original_run = core.state._run
        async def tracked_run(fn):
            def tracked(conn):
                try:
                    return fn(conn)
                finally:
                    worker_finished.set()
            return await original_run(tracked)
        monkeypatch.setattr(core.state, "_run", tracked_run)
        stage = asyncio.create_task(core.state.stage_voice_projection(conversation_id, "output", 0, turn))
        await asyncio.wait_for(entered.wait(), 1)
        monkeypatch.setattr(core.state, "_run", original_run)
        stage.cancel()
        async def following_operation():
            async with core.state._lock:
                # A regression must fail before entering concurrent native SQLite.
                assert worker_finished.is_set()
            return await (core.state.get_conversation(conversation_id) if next_operation == "read" else core.state.close())
        following = asyncio.create_task(following_operation())
        await asyncio.sleep(0)
        stage.cancel()  # Repeated shutdown cancellation must not release ownership either.
        await asyncio.sleep(0)
        assert not stage.done()
        assert not following.done()
        assert core.state._lock.locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(stage, 1)
        result = await asyncio.wait_for(following, 1)
        if next_operation == "read":
            assert result.id == conversation_id
            monkeypatch.setattr(core.state, "_voice_projection", original)
            offset, pending = await core.state.get_voice_projection(conversation_id, "output")
            assert offset == 0
            assert (pending is None) == worker_fails
        else:
            assert core.state._conn is None
    finally:
        release.set()
        if stage is not None:
            assert await asyncio.to_thread(worker_finished.wait, 3)
        await asyncio.gather(*(task for task in (stage, following) if task is not None), return_exceptions=True)
        await core.stop()
