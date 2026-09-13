"""Task08: unspoken outcomes survive real Core HTTP/SQLite and restart.

Only the external backend and one repository failure are controlled. Tests use
Core-owned event sinks; no fabricated Job, heard turn or playback completion.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from aiohttp.test_utils import TestServer

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import (
    BrainEvent, BrainEventKind, BrainTurnResult, SpeechKind, SpeechRequest,
)
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer


TEXT = "Le rapport demandé est prêt.\n\nIl contient trois recommandations."
WORK = "report-work"
SPEECH = BrainEventKind.SPEECH
COMPLETED = BrainEventKind.COMPLETED


class ControlledOutcomeBackend:
    """Run finite signal batches inside the real backend invocation."""

    def __init__(self):
        self.commands = {}

    async def run_turn(self, turn, state, emit):
        queue = asyncio.Queue()
        self.commands[turn.correlation_id] = queue
        while True:
            command = await queue.get()
            if command is None:
                return BrainTurnResult(correlation_id=turn.correlation_id)
            kinds, reply = command

            async def signal(kind):
                speech = SpeechRequest(
                    conversation_id=turn.conversation_id, text=TEXT,
                    kind=SpeechKind.RESULT, work_id=WORK,
                ) if kind is SPEECH else None
                await emit.emit(BrainEvent(
                    kind=kind, conversation_id=turn.conversation_id,
                    correlation_id=turn.correlation_id, work_id=WORK,
                    public_summary=TEXT if kind is COMPLETED else "",
                    speech=speech,
                ))

            results = await asyncio.gather(*(signal(kind) for kind in kinds), return_exceptions=True)
            if not reply.done():
                reply.set_result(results)

    async def batch(self, correlation, *kinds):
        async with asyncio.timeout(3):
            while correlation not in self.commands:
                await asyncio.sleep(.001)
            reply = asyncio.get_running_loop().create_future()
            await self.commands[correlation].put((kinds, reply))
            return await reply


@asynccontextmanager
async def core_stack(path, backend):
    core = JarvisCoreApplication(data_root=path, brain_backend=backend)
    await core.start()
    protocol = LocalProtocolServer(core, host="127.0.0.1", port=0, token="r" * 32)
    server = TestServer(protocol._app())
    await server.start_server()
    client = LocalCoreClient(host="127.0.0.1", port=server.port, token="r" * 32)
    try:
        yield core, client
    finally:
        await client.close()
        await server.close()
        await asyncio.wait_for(core.stop(), 3)


def take_events(queue):
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


async def assert_no_invented_history_or_job(core, conversation, expected_user_text):
    turns = await core.state.list_turns(conversation, limit=20)
    assert [turn.content for turn in turns] == expected_user_text
    assert all(turn.kind.value == "user" for turn in turns)
    assert not await core.state.list_jobs()


async def test_late_outcome_preserves_origin_across_restart_and_explicit_selection(tmp_path):
    backend = ControlledOutcomeBackend()
    async with core_stack(tmp_path, backend) as (core, client):
        conversation = (await client.create_conversation())["id"]
        accepted_a = await client.submit_brain_turn(conversation, content="Prépare le rapport.", correlation_id="origin-a")
        source_a = (await client.speech_context(conversation))["current_speech_source"]
        assert source_a["turn_id"] == accepted_a["turn_id"]
        assert source_a["correlation_id"] == "origin-a"
        assert source_a["turn_id"] != source_a["correlation_id"]
        assert await backend.batch("origin-a", BrainEventKind.ACCEPTED) == [None]

        await client.submit_brain_turn(conversation, content="Parlons maintenant du calendrier.", correlation_id="current-b")
        source_b = (await client.speech_context(conversation))["current_speech_source"]
        assert source_b["intent_epoch"] > source_a["intent_epoch"]
        events = core.events.subscribe()

        # Actual late backend notifications race and repeat after a new topic.
        assert await backend.batch("origin-a", SPEECH, COMPLETED, SPEECH, COMPLETED) == [None] * 4
        outcomes = (await client.list_brain_outcomes(conversation))["outcomes"]
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome["text"] == TEXT
        assert outcome["kind"] == "work_result"
        assert outcome["source"] == {**source_a, "dependencies": [
            {"work_id": WORK, "source_correlation_id": "origin-a"},
        ]}
        assert (await client.speech_context(conversation))["current_speech_source"] == source_b
        old_speeches = [event.payload for event in take_events(events)
                        if event.message_type == "brain.speech.requested" and event.payload.get("text") == TEXT]
        assert old_speeches
        assert all(speech["source"] == outcome["source"] and speech["outcome_id"] == outcome["id"]
                   for speech in old_speeches)
        await assert_no_invented_history_or_job(core, conversation, ["Prépare le rapport.", "Parlons maintenant du calendrier."])

    # New application, repository connection and HTTP server against the same DB.
    async with core_stack(tmp_path, ControlledOutcomeBackend()) as (core, client):
        assert await client.get_brain_outcome(conversation, outcome["id"]) == outcome
        assert (await client.speech_context(conversation))["current_speech_source"] == source_b
        selected, repeated = await asyncio.gather(*(
            client.select_brain_outcome(conversation, outcome["id"], selection_id="read-report-b") for _ in range(2)
        ))
        assert repeated["speech"] == selected["speech"]
        assert {selected["duplicate"], repeated["duplicate"]} == {False, True}
        speech = selected["speech"]
        assert speech["outcome_id"] == outcome["id"]
        assert speech["source"] == source_b
        assert speech["text"] == TEXT
        assert speech["speech_id"] not in {item["speech_id"] for item in old_speeches}
        assert await client.get_brain_outcome(conversation, outcome["id"]) == outcome
        await assert_no_invented_history_or_job(core, conversation, ["Prépare le rapport.", "Parlons maintenant du calendrier."])

        accepted_c = await client.submit_brain_turn(conversation, content="Passons au budget.", correlation_id="current-c")
        source_c = (await client.speech_context(conversation))["current_speech_source"]
        assert source_c["turn_id"] == accepted_c["turn_id"]
        assert source_c["intent_epoch"] > source_b["intent_epoch"]
        assert source_c["intent_id"] not in {source_a["intent_id"], source_b["intent_id"]}
        new_selection = await client.select_brain_outcome(conversation, outcome["id"], selection_id="read-report-c")
        assert new_selection["speech"]["source"] == source_c
        assert new_selection["speech"]["speech_id"] != speech["speech_id"]
        assert (await client.list_brain_outcomes(conversation))["outcomes"] == [outcome]


async def test_sqlite_failure_precedes_publication_and_concurrent_retry_retains_once(tmp_path, monkeypatch):
    backend = ControlledOutcomeBackend()
    async with core_stack(tmp_path, backend) as (core, client):
        conversation = (await client.create_conversation())["id"]
        await client.submit_brain_turn(conversation, content="Prépare le rapport.", correlation_id="failure-origin")
        assert await backend.batch("failure-origin", BrainEventKind.ACCEPTED) == [None]
        events = core.events.subscribe()
        save = core.state.save_brain_outcome
        failed = False

        async def fail_first_write(outcome):
            nonlocal failed
            if outcome.text == TEXT and not failed:
                failed = True
                raise OSError("controlled SQLite persistence failure")
            return await save(outcome)

        monkeypatch.setattr(core.state, "save_brain_outcome", fail_first_write)
        result = await backend.batch("failure-origin", SPEECH)
        assert len(result) == 1 and isinstance(result[0], OSError)
        assert (await client.list_brain_outcomes(conversation))["outcomes"] == []
        assert not [event for event in take_events(events) if event.message_type in {
            "brain.outcome.available", "brain.speech.requested", "brain.work.completed",
        }]

        # Observe the actual publication boundary, not merely eventual storage.
        publish = core.events.publish
        published_outcomes = []
        durable_channels = set()

        async def check_durable_before_publish(event):
            if event.message_type == "brain.outcome.available":
                advertised = event.payload["outcome"]
                stored = await core.state.get_brain_outcome(conversation, advertised["id"])
                assert stored is not None
                assert stored.text == advertised["text"]
                assert stored.source.to_payload() == advertised["source"]
                published_outcomes.append((advertised["id"], advertised["kind"]))
            elif event.message_type in {"brain.speech.requested", "brain.work.completed"}:
                reference = event.payload.get("outcome_id") or event.payload.get("result_ref")
                stored = await core.state.get_brain_outcome(conversation, reference)
                assert stored is not None and stored.text == TEXT
                durable_channels.add(event.message_type)
            await publish(event)

        monkeypatch.setattr(core.events, "publish", check_durable_before_publish)
        assert await backend.batch("failure-origin", COMPLETED, SPEECH, COMPLETED, SPEECH) == [None] * 4
        outcomes = (await client.list_brain_outcomes(conversation))["outcomes"]
        assert len(outcomes) == 1 and outcomes[0]["text"] == TEXT
        assert published_outcomes and {item[0] for item in published_outcomes} == {outcomes[0]["id"]}
        assert len(published_outcomes) == len(set(published_outcomes))
        assert durable_channels == {"brain.speech.requested", "brain.work.completed"}
        await assert_no_invented_history_or_job(core, conversation, ["Prépare le rapport."])

    async with core_stack(tmp_path, ControlledOutcomeBackend()) as (core, client):
        assert (await client.list_brain_outcomes(conversation))["outcomes"] == outcomes
        await assert_no_invented_history_or_job(core, conversation, ["Prépare le rapport."])
