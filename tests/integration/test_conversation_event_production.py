"""Conversation Events produced by a running Core, read back after restart or crash (Slice 03a).

- a Brain failure after a user turn leaves the user event and the authoritative
  failure in the store, readable by a fresh process;
- a hard process kill (no shutdown drain) keeps every event whose batch already
  committed;
- a multi-turn voice conversation through the real protocol and speech stack
  reconstructs from the store alone (`reconstruct_conversation`).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.conversation_event_store import MAX_EVENT_PAGE_LIMIT
from jarvis.domain.conversation_events import ConversationActor, ConversationEventType as T, reconstruct_conversation
from jarvis.domain.v2 import BrainTurnInput, SpeechKind
from tests.fakes.conversation_events import open_store, wait_emitter_settled
from tests.integration.async_conversation_harness import voice_stack

ROOT = Path(__file__).resolve().parents[2]


async def read_events(db: Path, conversation_id: str):
    state, store = await open_store(db)
    try:
        page = await store.list_conversation_events(conversation_id, limit=MAX_EVENT_PAGE_LIMIT)
        assert page.skipped_rows == 0 and not page.has_more
        return [item.event for item in page.events]
    finally:
        await state.close()


async def test_user_turn_and_brain_failure_survive_a_brain_crash_and_a_restart(tmp_path):
    started = asyncio.Event()

    class CrashingBackend:
        async def run_turn(self, turn, state, emit):
            started.set()
            raise ConnectionResetError("PRIVATE provider socket detail")

    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=CrashingBackend())
    await core.start()
    try:
        conversation = await core.conversations.create()
        acceptance = await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, correlation_id="corr-crash",
                                                            text="Envoie le rapport."))
        await asyncio.wait_for(started.wait(), 5)
        await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values()), return_exceptions=True), 5)
    finally:
        await core.stop()  # Core process ends; the next reader is a fresh repository

    events = await read_events(tmp_path / "state" / "jarvis.sqlite3", conversation.id)
    assert [event.event_type for event in events] == [
        T.USER_TRANSCRIPT_ACCEPTED, T.BRAIN_TURN_ACCEPTED, T.BRAIN_TURN_FAILED]
    user, _, failed = events
    assert (user.content, user.turn_id, user.correlation_id) == ("Envoie le rapport.", acceptance.turn_id, "corr-crash")
    assert dict(failed.attributes) == {"code": "brain_backend_exception", "error_class": "ConnectionResetError"}
    assert "PRIVATE" not in repr(events)


# The child accepts a user turn; its backend waits until the emitter has
# committed what was recorded so far, then kills the process with no shutdown.
CHILD = textwrap.dedent("""
    import asyncio, json, os, sys
    from pathlib import Path
    from jarvis.core.v2_app import JarvisCoreApplication
    from jarvis.domain.v2 import BrainTurnInput
    from tests.fakes.conversation_events import wait_emitter_settled

    class KillingBackend:
        core = None
        async def run_turn(self, turn, state, emit):
            await wait_emitter_settled(self.core.conversation_event_emitter)
            os._exit(9)

    async def main(root):
        backend = KillingBackend()
        core = JarvisCoreApplication(data_root=Path(root), brain_backend=backend)
        backend.core = core
        await core.start()
        conversation = await core.conversations.create()
        print(json.dumps({"conversation_id": conversation.id}), flush=True)
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, correlation_id="corr-kill",
                                               text="Question avant la panne."))
        await asyncio.sleep(30)
        print("unreachable", flush=True)

    asyncio.run(main(sys.argv[1]))
""")


async def test_hard_kill_keeps_events_the_emitter_already_committed(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    child = subprocess.run([sys.executable, "-c", CHILD, str(tmp_path)], cwd=ROOT, env=env, capture_output=True,
                           text=True, timeout=60)
    assert child.returncode == 9, child.stderr
    assert "unreachable" not in child.stdout
    conversation_id = json.loads(child.stdout.splitlines()[0])["conversation_id"]
    events = await read_events(tmp_path / "state" / "jarvis.sqlite3", conversation_id)
    assert [(event.event_type, event.content) for event in events] == [
        (T.USER_TRANSCRIPT_ACCEPTED, "Question avant la panne."), (T.BRAIN_TURN_ACCEPTED, None)]


async def test_a_three_turn_voice_conversation_reconstructs_from_the_store(tmp_path, monkeypatch):
    async with voice_stack(tmp_path, monkeypatch) as stack:
        await stack.wake()
        for index in (1, 2, 3):
            handle = await stack.user_says(f"Question numéro {index} ?")
            answer = await handle.say(f"Réponse numéro {index}.", kind=SpeechKind.RESULT, work_id=f"work-{index}")
            handle.finish(public_summary=answer.text)
            await stack.wait_spoken(index)
            await stack.speak_and_finish(transcript=answer.text)
        conversation_id = stack.conversation_id
        await wait_until_settled(stack.core)
    # voice_stack stopped Core: everything recorded was drained before the DB closed.
    events = await read_events(tmp_path / "state" / "jarvis.sqlite3", conversation_id)

    users = [e for e in events if e.event_type is T.USER_TRANSCRIPT_ACCEPTED]
    assert [e.content for e in users] == ["Question numéro 1 ?", "Question numéro 2 ?", "Question numéro 3 ?"]
    assert {e.producer for e in users} == {"core.voice_admission"}
    speeches = [e for e in events if e.event_type is T.BRAIN_SPEECH_REQUESTED]
    assert [e.content for e in speeches] == ["Réponse numéro 1.", "Réponse numéro 2.", "Réponse numéro 3."]
    for user, speech in zip(users, speeches):
        # user -> brain join by correlation, and the user fact is stored before the reply it caused
        assert speech.correlation_id == user.correlation_id
        assert events.index(user) < events.index(speech)
        accepted = [e for e in events if e.event_type is T.BRAIN_TURN_ACCEPTED and e.correlation_id == user.correlation_id]
        assert len(accepted) == 1 and accepted[0].turn_id == user.turn_id
        # Faithful record: the spoken result (speech_result, work_id set) and the turn
        # summary (turn_result) are two outcomes with the same text. Public
        # projections (Slice 05/06) collapse them; the log does not.
        published = [(e.content, e.work_id) for e in events if e.event_type is T.BRAIN_MESSAGE_PUBLISHED
                     and e.correlation_id == user.correlation_id]
        assert published == [(speech.content, speech.work_id), (speech.content, None)]
        assert speech.outcome_id is not None

    public = reconstruct_conversation(events, include_diagnostic=False)
    assert [(item.actor, item.text) for item in public if item.actor is ConversationActor.USER] == [
        (ConversationActor.USER, f"Question numéro {i} ?") for i in (1, 2, 3)]
    assert all(not item.anomalies for item in reconstruct_conversation(events))


async def wait_until_settled(core: JarvisCoreApplication) -> None:
    await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values()), return_exceptions=True), 10)
    await wait_emitter_settled(core.conversation_event_emitter)


# Turn A commits normally. Before turn B the drain linger is widened to 30 s, so
# B's user event is recorded but cannot commit; B's backend checks that the turn
# and its brain source are durable, then kills the process: the exact crash
# window between the durable admission and the emitter commit.
CRASH_IN_WINDOW = textwrap.dedent("""
    import asyncio, json, os, sys
    from pathlib import Path
    from jarvis.core.v2_app import JarvisCoreApplication
    from jarvis.domain.v2 import BrainTurnInput, BrainTurnResult
    from tests.fakes.conversation_events import wait_emitter_settled

    class Backend:
        core = None
        async def run_turn(self, turn, state, emit):
            if turn.correlation_id == "corr-a":
                return BrainTurnResult(correlation_id=turn.correlation_id)
            emitter = self.core.conversation_event_emitter
            source = await self.core.state.get_brain_source(turn.conversation_id, turn.correlation_id)
            print(json.dumps({"source_durable": source is not None, "pending": emitter.pending,
                              "appended": emitter.counters.appended}), flush=True)
            os._exit(9)

    async def main(root):
        backend = Backend()
        core = JarvisCoreApplication(data_root=Path(root), brain_backend=backend)
        backend.core = core
        await core.start()
        conversation = await core.conversations.create()
        print(json.dumps({"conversation_id": conversation.id}), flush=True)
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, correlation_id="corr-a", text="Question A."))
        await asyncio.gather(*tuple(core.brain._tasks.values()))
        await wait_emitter_settled(core.conversation_event_emitter)
        core.conversation_event_emitter._batch_linger_s = 30.0  # widen the commit window deterministically
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, correlation_id="corr-b", text="Question B."))
        await asyncio.sleep(60)
        print("unreachable", flush=True)

    asyncio.run(main(sys.argv[1]))
""")


async def test_crash_between_durable_admission_and_emitter_commit_is_repaired_on_restart(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    child = subprocess.run([sys.executable, "-c", CRASH_IN_WINDOW, str(tmp_path)], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=90)
    assert child.returncode == 9, child.stderr
    lines = [json.loads(line) for line in child.stdout.splitlines() if line.startswith("{")]
    conversation_id = lines[0]["conversation_id"]
    # In the child, at the kill: B's brain source durable, A's 2 events committed, B's user event
    # held by the lingering drain and B's brain.turn.accepted still queued.
    assert lines[1] == {"source_durable": True, "pending": 1, "appended": 2}
    db = tmp_path / "state" / "jarvis.sqlite3"

    lost = await read_events(db, conversation_id)
    assert [(e.event_type, e.content) for e in lost] == [
        (T.USER_TRANSCRIPT_ACCEPTED, "Question A."), (T.BRAIN_TURN_ACCEPTED, None)]  # B's user event is lost

    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()  # backfill runs before any route can accept a turn
    try:
        await wait_emitter_settled(core.conversation_event_emitter)
        counters = core.conversation_event_emitter.counters
        assert (counters.appended, counters.duplicates, counters.conflicts) == (1, 1, 0)
    finally:
        await core.stop()
    repaired = await read_events(db, conversation_id)
    users = [e for e in repaired if e.event_type is T.USER_TRANSCRIPT_ACCEPTED]
    assert [e.content for e in users] == ["Question A.", "Question B."]  # each exactly once
    assert len({e.event_id for e in users}) == 2
    # Accepted loss window (option A): B's brain.turn.accepted is not rebuilt.
    assert [e.correlation_id for e in repaired if e.event_type is T.BRAIN_TURN_ACCEPTED] == ["corr-a"]
