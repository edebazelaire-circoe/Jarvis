"""End-to-end rollout gate of the Conversation Event log (Slice 06).

One conversation lives through the whole observability path:

1. **real stacks, in process**: Core (SQLite store, ingestion route), the voice
   runtime (`SpeechScheduler` + `RealtimeConversationBridge`, fake provider and
   audio device) and a Control Center `AgentTaskTracker`, each non-Core process
   posting through its own `ConversationEventForwarder`. The user asks, Brain
   opens work and a sub-agent, Jarvis is cut by the user while the sub-agent
   runs, the surface calls a tool, the user asks again and hears the full
   answer (published twice: collapsed), a third turn fails in the backend.
   Private values are planted where Jarvis really keeps them: tool arguments,
   the backend error text, the sub-agent prompt and summary, a journal-only line;
2. **Core hard crash**: a child Core process on the same data root accepts a
   user turn whose event is still in the emitter queue and is killed
   (`os._exit`), the pattern of `test_conversation_event_production`;
3. **restart**: a fresh Core backfills the lost user event; a real Control
   Center (origin guard, `ConversationEventView`) serves the projections.

Then, through the Control Center routes only: the JSONL export re-imports to
the same reconstruction and the same transcript bytes, the readable transcript
matches the canonical visible sequence, search finds what was said and never a
planted value, and every stored event's trace drill-down joins exactly one
redacted journal line.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap

from aiohttp.test_utils import TestClient, TestServer

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.conversation_event_export import read_export, reconstruct_export, transcript_from_export
from jarvis.domain.conversation_events import (
    ConversationActor, ConversationEventType as T, ConversationVisibility, reconstruct_conversation,
)
from jarvis.domain.conversation_transcript import TranscriptMode, transcript_entries
from jarvis.domain.v2 import BrainRunStatus, SpeechKind
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.agent_tasks import AgentTaskTracker
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.conversation_event_view import ConversationEventView, CoreConversationEventReader
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.realtime_audio import CLAUDE_TOOL
from jarvis.runtime.subagent_conversation import SubagentConversationScope
from tests.fakes.conversation_events import assert_drill_down_joins_one_line, wait_emitter_settled
from tests.fakes.transcript_oracle import body_of, plain_body
from tests.integration.async_conversation_harness import CHUNK_MS, TOKEN, free_port, voice_stack, wait_until
from tests.integration.test_conversation_event_timeline import delivered, forwarder_to, read_store
from tests.unit.test_agent_tasks import SESSION, agent_call, async_launched, notification

ROOT = Path(__file__).resolve().parents[2]
PLANTED = {
    "tool_argument": "PLANTEDTOOLARG",
    "backend_error": "PLANTEDBACKENDERROR",
    "subagent_prompt": "PLANTEDSUBAGENTPROMPT",
    "subagent_summary": "PLANTEDSUBAGENTSUMMARY",
    "journal_only": "PLANTEDJOURNALONLY",
}

CRASH = textwrap.dedent("""
    import asyncio, json, os, sys
    from pathlib import Path
    from jarvis.core.v2_app import JarvisCoreApplication
    from jarvis.domain.v2 import BrainTurnInput
    from tests.fakes.conversation_events import wait_emitter_settled

    class KillingBackend:
        core = None
        async def run_turn(self, turn, state, emit):
            emitter = self.core.conversation_event_emitter
            source = await self.core.state.get_brain_source(turn.conversation_id, turn.correlation_id)
            print(json.dumps({"source_durable": source is not None, "pending": emitter.pending}), flush=True)
            os._exit(9)

    async def main(root, conversation_id):
        backend = KillingBackend()
        core = JarvisCoreApplication(data_root=Path(root), brain_backend=backend)
        backend.core = core
        await core.start()
        await wait_emitter_settled(core.conversation_event_emitter)  # start-up backfill (duplicates) committed
        core.conversation_event_emitter._batch_linger_s = 30.0  # the user event cannot commit before the kill
        await core.brain.submit(BrainTurnInput(conversation_id=conversation_id, correlation_id="corr-crash",
                                               text="Question pendant la panne : le vol est-il confirmé ?"))
        await asyncio.sleep(60)
        print("unreachable", flush=True)

    asyncio.run(main(sys.argv[1], sys.argv[2]))
""")


async def run_live_conversation(tmp_path: Path, monkeypatch) -> tuple[str, list[dict]]:
    """Phase 1: the real multi-process conversation. Returns its id and every journal line written."""
    token_file = tmp_path / "core.token"
    token_file.write_text(TOKEN, encoding="utf-8")
    voice_events = []

    def voice_forwarder(port: int, token: str):
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
            first = await stack.user_says("Prépare mon dossier de vol pour Lisbonne.")
            work_id = f"brain-turn:{first.correlation_id}"
            await first.start_work(work_id, label="Demande transmise à l'agent local.")
            tracker.begin_conversation_turn(SubagentConversationScope(conversation_id, first.correlation_id, work_id),
                                            message_uuid="ask-1")
            tracker.turn_started()
            for event in (agent_call("toolu_A", "Rassemble les vols", model="claude-sonnet-5",
                                     prompt=f"Cherche {PLANTED['subagent_prompt']} dans la boîte mail."),
                          async_launched("toolu_A", "agent-a1"),
                          {"type": "result", "subtype": "success", "result": "Lancé.", "session_id": SESSION,
                           "user_message_uuids": ["ask-1"]}):
                tracker.observe_claude(event)

            progress = await first.say("Je regarde tous les vols de la semaine vers Lisbonne.", work_id=work_id)
            await stack.wait_spoken(1)
            await stack.session.play_audio(chunks=4)
            await wait_until(lambda: stack.audio.played_output_ms >= 4 * CHUNK_MS, message="audio joué")
            await stack.session.interrupt()
            await stack.journal.wait_until(lambda: stack.journal.count("voice.speech.interrupted") == 1)

            await stack.session.tool_call(CLAUDE_TOOL, {"request": f"{PLANTED['tool_argument']} carte 4242"},
                                          call_id="call-9")
            await stack.journal.wait_until(lambda: stack.journal.count("tool.result") == 1)

            second = await stack.user_says("Seulement le vol de Paul, s'il te plaît.")
            answer = await second.say("Le vol de Paul pour Lisbonne part lundi à 9 heures.", kind=SpeechKind.RESULT,
                                      work_id="work-answer")
            await stack.wait_spoken(2)
            await stack.speak_and_finish(transcript=answer.text)
            await stack.journal.wait_until(lambda: stack.journal.count("voice.speech.completed") == 1)
            second.finish(public_summary=answer.text)
            first.finish()

            tracker.observe_claude(notification("agent-a1", "toolu_A", "completed",
                                                f"Trois vols trouvés {PLANTED['subagent_summary']}."))
            third = await stack.user_says("Et réserve l'hôtel aussi.")
            third.finish(status=BrainRunStatus.FAILED,
                         error=f"{PLANTED['backend_error']} quota exceeded for account paul@example.com")
            stack.core_journal.emit("core.diagnostic.note", PLANTED["journal_only"],
                                    data={"text": PLANTED["journal_only"], "conversation_id": conversation_id})

            await wait_until(lambda: all(delivered(f) for f in (*voice_events, cc_events)), message="events sent")
            await wait_emitter_settled(stack.core.conversation_event_emitter)
        finally:
            await cc_events.aclose()
    assert progress.id and answer.id
    lines = [*stack.journal.events, *stack.core_journal.events,
             *read_jsonl_tail(tmp_path / "control-center" / "trace.jsonl", limit=1000)]
    return conversation_id, lines


def crash_core_mid_turn(tmp_path: Path, conversation_id: str) -> None:
    """Phase 2: a Core process killed while the admitted user turn's event is still queued."""
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    child = subprocess.run([sys.executable, "-c", CRASH, str(tmp_path), conversation_id], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=90)
    assert child.returncode == 9, child.stderr[-2000:]
    report = json.loads(next(line for line in child.stdout.splitlines() if line.startswith("{")))
    # User event held by the lingering drain, brain.turn.accepted still queued: neither committed.
    assert report == {"source_durable": True, "pending": 1}


async def test_the_conversation_event_log_passes_the_rollout_gate(tmp_path, monkeypatch):
    conversation_id, journal_lines = await run_live_conversation(tmp_path, monkeypatch)
    before_crash = await read_store(tmp_path / "state" / "jarvis.sqlite3", conversation_id)

    crash_core_mid_turn(tmp_path, conversation_id)
    lost = await read_store(tmp_path / "state" / "jarvis.sqlite3", conversation_id)
    assert [e.event_id for e in lost] == [e.event_id for e in before_crash]  # the crashed turn left no event

    port = free_port()
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()  # start-up backfill re-records the crashed user turn
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    (tmp_path / "cc-runtime").mkdir()
    control = ControlCenter(runtime_root=tmp_path / "cc-runtime", project_root=tmp_path,
                            conversation_event_view=ConversationEventView(CoreConversationEventReader(
                                host="127.0.0.1", port=port, token_file=tmp_path / "core.token"), timeout_s=10.0))
    control.conversation_event_view.journal = control.journal
    client = TestClient(TestServer(control._app))
    await client.start_server()
    try:
        await wait_emitter_settled(core.conversation_event_emitter)
        assert core.conversation_event_emitter.counters.appended == 1
        page = await core.conversation_events.list_conversation_events(conversation_id, limit=500)
        assert not page.has_more and page.skipped_rows == 0
        events = [item.event for item in page.events]
        [crashed] = [e for e in events if e.correlation_id == "corr-crash"]
        assert crashed.event_type is T.USER_TRANSCRIPT_ACCEPTED and crashed.content.startswith("Question pendant la panne")

        # ---- export -> re-import -> same reconstruction and transcript bytes
        response = await client.get("/api/conversations/export", params={"conversation_id": conversation_id})
        assert response.status == 200
        exported = await response.read()
        result = read_export(exported.splitlines(keepends=True))
        assert result.complete and not result.invalid_lines and result.events == page.events
        assert reconstruct_export(result) == reconstruct_conversation(events)
        transcripts = {}
        for mode in TranscriptMode:
            response = await client.get("/api/conversations/transcript",
                                        params={"conversation_id": conversation_id, "mode": mode.value})
            assert response.status == 200
            transcripts[mode] = await response.text()
            assert transcripts[mode] == transcript_from_export(result, mode=mode)

        if os.environ.get("JARVIS_ROLLOUT_GATE_DUMP"):  # evidence for the handoff log (scratch directory only)
            dump = Path(os.environ["JARVIS_ROLLOUT_GATE_DUMP"])
            dump.mkdir(parents=True, exist_ok=True)
            (dump / "export.jsonl").write_bytes(exported)
            for mode, text in transcripts.items():
                (dump / f"transcript-{mode.value}.txt").write_text(text, encoding="utf-8")
        # ---- the readable transcript is the canonical visible sequence
        plain = transcripts[TranscriptMode.PLAIN]
        raw_events = [json.loads(line)["event"] for line in exported.decode("utf-8").splitlines()[1:-1]]
        assert body_of(plain) == plain_body(raw_events)  # QA's oracle: raw JSON only, no Jarvis reconstruction
        assert f"Jarvis [interrompu après {4 * CHUNK_MS} ms entendues] : Je regarde tous les vols" in plain
        assert "Utilisateur : Question pendant la panne : le vol est-il confirmé ?" in plain
        assert plain.count("Brain : Le vol de Paul pour Lisbonne part lundi à 9 heures.") == 1  # collapsed
        assert len([e for e in transcript_entries(events) if e.collapsed]) == 1
        detailed = transcripts[TranscriptMode.DETAILED]
        assert "-- Sous-agent « Rassemble les vols » : terminé" in detailed
        assert "-- Brain : tour en échec (code brain_backend_failed)" in detailed
        assert re.search(r"-- Outil claude[_a-z]* : terminé", detailed)

        # ---- search: said/heard text and safe metadata, never a planted value
        async def search(q: str, **params) -> dict:
            response = await client.get("/api/conversations/search", params={"q": q, **params})
            assert response.status == 200
            return await response.json()

        hits = (await search("LISBONNE dossier"))["hits"]
        assert [h["event_type"] for h in hits] == ["user.transcript.accepted"]
        panne = (await search("panne confirme", conversation_id=conversation_id))["hits"]
        assert [h["event_id"] for h in panne] == [crashed.event_id]
        assert {h["event_type"] for h in (await search("interrupted"))["hits"]} == {"mouth.speech.interrupted"}
        failed = (await search("brain_backend_failed"))["hits"]
        assert [h["matched"] for h in failed] == [["attributes.code"]]
        for planted in (*PLANTED.values(), "4242", "paul@example.com", "boîte mail", "Trois vols trouvés"):
            body = await search(planted)
            assert body["hits"] == [], planted
        public_only = (await search("vol", visibility="public"))["hits"]
        assert public_only and all(h["visibility"] == ConversationVisibility.PUBLIC.value for h in public_only)

        # ---- every trace_ref joins exactly one redacted line, directly and through the route
        assert_drill_down_joins_one_line(events, journal_lines, control.journal.trace_path)
        drilled = 0
        for event in events:
            if event.trace_ref is None or event.actor is ConversationActor.USER:
                continue
            response = await client.get(f"/api/conversations/events/{event.event_id}/trace")
            body = await response.json()
            assert response.status == 200 and body["status"] == "found", (event.event_type, body)
            [entry] = body["scan"]["entries"]
            assert entry["data"]["conversation_event_id"] == event.event_id
            assert not any(value in json.dumps(body, ensure_ascii=False) for value in PLANTED.values())
            drilled += 1
        assert drilled >= 10

        # ---- nothing planted leaves Core through any projection
        surfaces = exported.decode("utf-8") + "".join(transcripts.values())
        for planted in (*PLANTED.values(), "4242", "paul@example.com"):
            assert planted not in surfaces, planted
        assert any(PLANTED["backend_error"] in json.dumps(line, ensure_ascii=False, default=str) for line in journal_lines)
    finally:
        await client.close()
        await control.conversation_event_view.aclose()
        await server.stop()
        await core.stop()
