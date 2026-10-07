"""Slice 11 — the deterministic PRESENTATION scenario matrix, end to end.

Handoff `jarvis-presentation-interaction-mode`, `docs/04-testing-and-quality.md`
scenarios 1–12, plus the SIMPLE-identity variant. Every case drives the rig of
`tests/fakes/presentation_scenario.py`: the real composition, coordinator, mode
follower (P1), bridge, scheduler and speech gate, the real `RuntimeJournal`, a
real forwarder into a real SQLite Conversation Event store, and the real
staged-object ledger. Core, transcription, the CLI sub-agent and the scene
tools are doubles.

The visual path asserted is today's: `PresentationDisplaySink` →
`DirectSceneDisplaySink` → stager → `SceneDisplayTools.update_object`. The
Tool Brain (Slice 08) and prefab-backed resources (Slice 09) are deferred.

No microphone, no network, no model.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from jarvis.adapters.control_center_brain import _turn_context
from jarvis.audio import input_ownership
from jarvis.domain.ambient_observation import AmbientTrigger, AmbientTriggerKind
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_speculative import SpeculativeAdmission
from jarvis.domain.v2 import AddressingDecision, BrainTurnInput, SpeechKind
from tests.fakes.presentation_scenario import Rig, build_rig
from tests.unit.test_ambient_ingestion_lane import feed, silence, speech, until

COURBE = {"kind": "url", "locator": "https://example.org/courbe", "title": "Courbe des ventes"}
CLAIM = "le chiffre d'affaires a doublé cette année, plus de 40 pour cent selon le rapport annuel"


@pytest.fixture(autouse=True)
def clean_input_registry():
    """The input-owner registry is **process** state."""

    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


@pytest.fixture
async def rig(tmp_path):
    built = await build_rig(tmp_path, mode=InteractionMode.PRESENTATION)
    try:
        yield built
    finally:
        await built.close()


def _types(events) -> list[str]:  # noqa: ANN001
    return [event.event_type.value for event in events]


def _attrs(event) -> dict:  # noqa: ANN001
    return dict(event.attributes)


async def _stage_courbe(rig: Rig) -> str:
    """The room names the sales curve; a first deictic finds nothing and asks for an explicit preparation.

    That preparation (an explicit token carries `DISPLAY_PREPARATION`) stages
    one hidden scene object. Returns its object id.
    """

    await rig.room("regardons maintenant la courbe des ventes")
    await rig.stack.speculative.drain()
    rig.agents.findings = [COURBE]
    turn = await rig.addressed("montre-moi ça")
    assert turn["presentation_context"]["action"] == "refresh", turn["presentation_context"]
    await rig.stack.speculative.drain()
    rig.agents.findings = []
    [created] = rig.scene.created
    assert created["visibility"] == "hidden" and rig.scene.revealed == []
    return created["object_id"]


async def _fill_pool(rig: Rig) -> None:
    """Two ambient preparations and one explicit refresh, all running: the pool (2 + 1) is full."""

    rig.agents.gate = asyncio.Event()
    await rig.room(CLAIM)
    await until(lambda: rig.stack.speculative.stats()["speculative_in_flight"] == 2, timeout=5.0)
    turn = await rig.addressed("montre-moi ça")
    assert turn["presentation_context"]["action"] == "refresh"
    await until(lambda: rig.stack.speculative.stats()["in_flight"] == 3, timeout=5.0)
    assert rig.stack.speculative.free_explicit_slots == 0, "the discriminating state: no free slot"


# ==========================================================================
# 1. Ambient monologue only
# ==========================================================================


async def test_s01_ambient_monologue_updates_context_and_never_answers(rig) -> None:
    """Guard. The room fills the working set; no turn, no speech, no screen, no text in the trace."""

    sentences = ("bonjour à tous, merci d'être venus ce matin",
                 "on passe au slide suivant ?",
                 "le budget marketing a été revu en septembre")
    for sentence in sentences:
        await rig.room(sentence)
    await rig.stack.speculative.drain()
    await rig.quiesce()

    tail = [entry.text for entry in rig.stack.store.snapshot.tail.entries]
    assert tail == list(sentences), "the context is updated, freshest last"
    assert rig.core.brain_turns == [] and rig.calls["addressed"] == 0
    assert rig.session.spoken == [] and rig.scene.created == []
    lines = [line for line in rig.trace() if line["kind"] == "voice.transcript"]
    assert len(lines) == 3
    assert all(line["data"] == {"addressing": "ambient", "chars": len(text)}
               for line, text in zip(lines, sentences)), lines
    trace = rig.journal.trace_path.read_text(encoding="utf-8")
    assert all(sentence not in trace for sentence in sentences)


# ==========================================================================
# 2. Deictic visual command
# ==========================================================================


async def test_s02_deictic_command_reveals_the_prepared_object_without_speech(rig) -> None:
    """Guard. "montre-moi ça" → SHOW_PREPARED → display sink → reveal; the brain's words are withheld."""

    object_id = await _stage_courbe(rig)

    async def brain(rig_: Rig, turn: dict) -> None:
        await rig_.brain_says(turn["correlation_id"], "Voici la courbe des ventes du trimestre.")

    rig.core.brain = brain
    turn = await rig.addressed("montre-moi ça")
    await until(lambda: rig.journal.trace_path.read_text(encoding="utf-8").count(
        "voice.presentation.speech_withheld") == 1, timeout=5.0)

    assert turn["presentation_context"]["action"] == "show_prepared"
    assert rig.scene.revealed == [object_id]
    kinds = rig.kinds()
    assert kinds.index("presentation.intent.published") < kinds.index("presentation.staging.revealed"), (
        "the reveal went through the display sink's intent"
    )
    assert rig.session.spoken == [], "no filler, no confirmation: the screen is the answer"
    events = await rig.stored_events()
    [withheld] = [event for event in events if event.event_type is T.MOUTH_SPEECH_SUPERSEDED]
    assert _attrs(withheld)["reason"] == "presentation_withheld"


# ==========================================================================
# 3. Knowledge question
# ==========================================================================


async def test_s03_knowledge_question_preempts_background_and_may_speak(rig) -> None:
    """Guard. Under a full pool the explicit question frees a slot, carries its context and is spoken."""

    await _fill_pool(rig)
    answer = "Le chiffre d'affaires du trimestre est de douze millions."

    async def brain(rig_: Rig, turn: dict) -> None:
        await rig_.brain_says(turn["correlation_id"], answer)

    rig.core.brain = brain
    preempted = rig.stack.speculative.stats()["preempted"]
    turn = await rig.addressed("quel est le chiffre d'affaires du trimestre ?")
    await until(lambda: rig.session.texts() == [answer], timeout=5.0)

    assert rig.stack.speculative.stats()["preempted"] == preempted + 1
    context = turn["presentation_context"]
    assert context["situation"] == "knowledge_question" and context["action"] == "ask_brain"
    assert context["recent_speech"][0]["text"] == CLAIM, "the freshest room speech travels with the turn (P4)"
    latencies = [line for line in rig.trace() if line["data"].get("code") == "addressed_admission_latency"]
    assert latencies and latencies[-1]["data"]["elapsed_ms"] is not None
    rig.agents.gate.set()


# ==========================================================================
# 4. Background preload
# ==========================================================================


async def test_s04_background_preload_is_prepared_and_never_manifested(rig) -> None:
    """Guard. Ambient triggers run bounded preparations in an empty cwd; nothing is shown or said."""

    rig.agents.findings = [{"kind": "url", "locator": "https://example.org/rapport-annuel", "title": "Rapport"}]
    await rig.room(CLAIM)
    await rig.stack.speculative.drain()
    await rig.quiesce()

    stats = rig.stack.speculative.stats()
    assert stats["admitted"] >= 1 and stats["completed"] == stats["admitted"]
    assert stats["max_speculative"] == 2, "the default pool is 2 + 1 reserved"
    assert rig.stack.store.snapshot.working_set.resources, "the preload landed in the working set"
    assert rig.scene.created == [] and rig.session.spoken == [] and rig.core.brain_turns == []
    prep_root = rig.data / "presentation" / "prep"
    for agent in rig.agents.agents:
        assert agent.cwd is not None and agent.cwd.parent == prep_root and agent.cwd_was_empty
        assert not agent.cwd.exists(), "the job's workspace is removed at job end"
        assert Path(rig.root) not in (agent.cwd, agent.cwd.parent)
    events = await rig.stored_events()
    spans = [event for event in events if event.event_type.value.startswith("subagent.")]
    assert _types(spans).count("subagent.started") == stats["admitted"]
    assert _types(spans).count("subagent.finished") == stats["admitted"]


# ==========================================================================
# 5. Background hit (named)
# ==========================================================================


async def test_s05_named_hit_is_revealed_by_object_id_through_the_projection(rig) -> None:
    """Guard. A named request is the brain's: the P5 projection names the object, the brain reveals it."""

    object_id = await _stage_courbe(rig)

    async def brain(rig_: Rig, turn: dict) -> None:
        # What the real brain does with `scene_update_object(visibility="visible")`.
        for resource in turn["presentation_context"]["prepared_resources"]:
            if "courbe" in resource["title"].lower():
                await rig_.scene.update_object(object_id=resource["object_id"], visibility="visible")

    rig.core.brain = brain
    turn = await rig.addressed("Jarvis, montre la courbe des ventes")
    await rig.quiesce()

    context = turn["presentation_context"]
    assert context["action"] == "ask_brain" and context["deictic"] == ""
    assert [r["object_id"] for r in context["prepared_resources"]] == [object_id]
    assert rig.scene.revealed == [object_id], "revealed by the brain, through the projected object id"
    assert rig.session.spoken == []


# ==========================================================================
# 6. Stale context
# ==========================================================================


async def test_s06_stale_enrichment_never_overrides_a_fresher_tail(rig) -> None:
    """Guard. The object prepared for an older sentence is not shown for "ça" after the room moved on."""

    await _stage_courbe(rig)
    await rig.room("passons maintenant au budget marketing de l'an prochain")
    await rig.stack.speculative.drain()

    turn = await rig.addressed("montre-moi ça")

    context = turn["presentation_context"]
    assert context["recent_speech"][0]["text"].startswith("passons maintenant au budget")
    assert context["referent"]["utterance_id"] == context["recent_speech"][0]["utterance_id"]
    assert context["prepared_resource"]["verdict"] == "stale"
    assert context["action"] == "refresh"
    assert rig.scene.revealed == [], "the stale object stays hidden"


# ==========================================================================
# 7–8. Contradictions
# ==========================================================================


async def test_s07_contradiction_raises_discreet_attention_and_no_speech(rig) -> None:
    """Guard. A confident contradiction is a card and a soft cue, never an unsolicited explanation."""

    rig.agents.assess = ("contradicted", 0.9)
    await rig.room(CLAIM)
    await rig.stack.speculative.drain()
    await rig.quiesce()

    assert rig.stack.attention.stats()["raised"] == 1
    assert rig.session.spoken == [] and rig.core.brain_turns == []
    events = await rig.stored_events()
    [raised] = [event for event in events if event.event_type is T.SYSTEM_ATTENTION_RAISED]
    assert _attrs(raised)["kind"] == "contradiction" and raised.content is None
    assert "presentation_attention_added" in rig.codes()


@pytest.mark.parametrize("verdict, confidence", [("contradicted", 0.4), ("unverifiable", 0.9)])
async def test_s08_weak_contradiction_stays_internal(rig, verdict, confidence) -> None:
    """Guard. Below threshold, or unverifiable: no card, no event, no speech."""

    rig.agents.assess = (verdict, confidence)
    await rig.room(CLAIM)
    await rig.stack.speculative.drain()
    await rig.quiesce()

    stats = rig.stack.attention.stats()
    assert stats["assessed"] >= 1 and stats["raised"] == 0
    events = await rig.stored_events()
    assert T.SYSTEM_ATTENTION_RAISED not in [event.event_type for event in events]
    assert rig.session.spoken == []


# ==========================================================================
# 9. Explicit interruption
# ==========================================================================


async def test_s09_explicit_turn_preempts_speculative_and_withdraws_display(rig) -> None:
    """Guard. The press frees a slot by cancelling speculative work and withdraws queued display (0 here)."""

    await _fill_pool(rig)
    service = rig.stack.turns
    withdrawals = service.counters.display_withdrawals
    running = [agent for agent in rig.agents.agents if not agent.cancelled]

    await rig.press()

    assert service.counters.display_withdrawals == withdrawals + 1
    assert service.counters.display_withdrawn == 0, "the direct sink queues nothing: withdraw = 0"
    await until(lambda: sum(agent.cancelled for agent in running) == 1, timeout=5.0)
    withdraw_lines = [line for line in rig.trace() if line["kind"] == "presentation.display.withdraw_noop"]
    assert withdraw_lines and withdraw_lines[-1]["data"]["withdrawn"] == 0
    rig.agents.gate.set()
    await rig.stack.speculative.drain()
    assert rig.scene.revealed == [], "no preparation surfaces over the explicit turn"
    events = await rig.stored_events()
    stopped = [event for event in events if event.event_type is T.SUBAGENT_STOPPED]
    assert [_attrs(event)["reason"] for event in stopped] == ["preempted"]


# ==========================================================================
# 10. Mode exit
# ==========================================================================


async def test_s10_mode_exit_stops_lane_and_scheduling_within_one_drain(rig) -> None:
    """Guard. One drain after Core says SIMPLE: no session, no lane, no job, SIMPLE routing back."""

    rig.agents.gate = asyncio.Event()
    await rig.room(CLAIM)
    await until(lambda: rig.stack.speculative.stats()["speculative_in_flight"] == 2, timeout=5.0)
    stack, agents = rig.stack, list(rig.agents.agents)
    heard = rig.transcriber.calls

    await rig.set_mode(InteractionMode.ASSISTANT)   # exactly one coordinator drain

    assert rig.coordinator.stack is None and stack.stopped
    assert all(agent.cancelled for agent in agents), "running preparations are cancelled"
    trigger = AmbientTrigger(kind=AmbientTriggerKind.NEW_TOPIC, utterance_id="u-late", text="sujet", confidence=0.3)
    assert stack.speculative.submit_trigger(trigger) is SpeculativeAdmission.INACTIVE
    assert rig.device.closed >= 1 and rig.simple.resumes >= 1
    await feed(rig.device, speech(900))
    assert rig.transcriber.calls == heard, "nothing is transcribed after exit"
    assert not any((rig.data / "presentation" / "prep").iterdir())
    events = await rig.stored_events()
    left = [event for event in events if event.event_type is T.SYSTEM_MODE_CHANGED][-1]
    assert (_attrs(left)["kind"], _attrs(left)["reason"]) == ("simple", "left")
    # SIMPLE routing is back: a long unaddressed sentence goes to the brain as `uncertain` (Décision 44).
    await rig.hear("le chiffre d'affaires du trimestre a beaucoup progressé grâce aux nouveaux clients")
    assert [turn["addressing"] for turn in rig.core.brain_turns] == [AddressingDecision.UNCERTAIN.value]
    assert rig.core.brain_turns[0]["presentation_context"] is None


# ==========================================================================
# 11. Recording boundary
# ==========================================================================


async def test_s11_presentation_creates_no_recording_artifact(tmp_path) -> None:
    """Guard. After a full session the only new files are the journal, the event store and the ledger."""

    rig = await build_rig(tmp_path, mode=InteractionMode.ASSISTANT)
    try:
        before = {path for path in tmp_path.rglob("*") if path.is_file()}
        await rig.set_mode(InteractionMode.PRESENTATION)
        await _stage_courbe(rig)
        await rig.room(CLAIM)
        await rig.stack.speculative.drain()
        await rig.set_mode(InteractionMode.ASSISTANT)
        await until(lambda: rig.scene.archived, timeout=5.0)
    finally:
        await rig.close()

    created = {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")
               if path.is_file() and path not in before}
    allowed = {"runtime/trace.jsonl", "runtime/errors.jsonl", "runtime/presentation-staged-objects.json",
               "data/jarvis.sqlite3", "data/jarvis.sqlite3-wal", "data/jarvis.sqlite3-shm"}
    assert created <= allowed, created - allowed
    assert json.loads((tmp_path / "runtime" / "presentation-staged-objects.json").read_text())["object_ids"] == []
    room_pcm = speech(900)[:4096]
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert room_pcm not in path.read_bytes(), f"room audio in {path.name}"
    assert not list((tmp_path / "data" / "presentation" / "prep").iterdir())


# ==========================================================================
# 12. Restart / recovery
# ==========================================================================


async def test_s12_restart_readopts_the_mode_and_replays_no_ambient(tmp_path) -> None:
    """Guard. A new Voice life enters PRESENTATION from Core's snapshot, fresh, and reclaims the old screen."""

    first = await build_rig(tmp_path, mode=InteractionMode.PRESENTATION)
    old_session = first.stack.session_id
    object_id = await _stage_courbe(first)
    await first.room("une phrase de la salle avant l'arrêt brutal")
    ledger = first.runtime / "presentation-staged-objects.json"
    crashed = ledger.read_bytes()
    assert object_id.encode() in crashed
    await first.close()
    ledger.write_bytes(crashed)   # what an unclean stop leaves behind
    input_ownership.reset_for_test()

    second = await build_rig(tmp_path, mode=InteractionMode.PRESENTATION)
    try:
        assert second.stack is not None and second.stack.session_id != old_session, "P1: re-adopted, new session"
        assert second.stack.store.snapshot.tail.entries == (), "old room speech is gone"
        assert second.scene.archived and object_id in second.scene.archived[0], "old hidden object reclaimed"
        await asyncio.sleep(0.05)
        await second.quiesce()
        assert second.core.brain_turns == [] and second.session.spoken == []
        assert second.calls["addressed"] == 0
    finally:
        await second.close()


# ==========================================================================
# SIMPLE identity
# ==========================================================================


SIMPLE_SCRIPT = (
    "Jarvis, quelle heure est-il ?",
    "le chiffre d'affaires du trimestre a beaucoup progressé grâce aux nouveaux clients en europe",
    "euh",
    "et la météo de demain ?",
)
#: Clock readings and random output ids: timing, not behaviour.
_VOLATILE_KEYS = ("ts", "at", "output_id")
_VOLATILE_SUFFIXES = ("_ms", "_s", "_at")


def _comparable(rig: Rig) -> list[tuple]:
    out = []
    for line in rig.trace():
        if not line["kind"].startswith("voice."):
            continue
        data = {key: value for key, value in line.get("data", {}).items() 
                if key not in _VOLATILE_KEYS and not key.endswith(_VOLATILE_SUFFIXES)}
        # A latency line's message carries the measured milliseconds: timing, not behaviour.
        message = "" if line["kind"].startswith("voice.latency.") else line["message"]
        out.append((line["kind"], line["level"], message, json.dumps(data, sort_keys=True)))
    return out


async def _run_simple(root: Path, *, wired: bool) -> Rig:
    rig = await build_rig(root, mode=InteractionMode.ASSISTANT)
    if not wired:
        # The pre-task code path: no PRESENTATION hook anywhere.
        rig.bridge.presentation_turns = None
        rig.scheduler.presentation_turns = None

    async def brain(rig_: Rig, turn: dict) -> None:
        if turn["addressing"] == "addressed":
            await rig_.brain_says(turn["correlation_id"], f"Réponse à {turn['provider_item_id']}.")

    rig.core.brain = brain
    for text in SIMPLE_SCRIPT:
        await rig.hear(text)
        await rig.quiesce()
        await asyncio.sleep(0.05)
    await until(lambda: rig.session.spoken, timeout=5.0)
    await rig.quiesce()
    return rig


async def test_simple_identity_bridge_scheduler_and_brief(tmp_path) -> None:
    """Outside PRESENTATION the wired runtime is the unwired one, byte for byte (D14 of 2026-09)."""

    wired = await _run_simple(tmp_path / "wired", wired=True)
    bare = await _run_simple(tmp_path / "bare", wired=False)
    try:
        assert wired.coordinator.stack is None
        assert wired.core.brain_turns == bare.core.brain_turns
        assert all(turn["presentation_context"] is None for turn in wired.core.brain_turns)
        assert wired.session.texts() == bare.session.texts() and wired.session.texts()
        assert _comparable(wired) == _comparable(bare)
        for turn in wired.core.brain_turns:
            brief = _turn_context(BrainTurnInput(
                conversation_id=turn["conversation_id"], text=turn["content"],
                correlation_id=turn["correlation_id"], addressing=AddressingDecision(turn["addressing"]),
            ), None)
            assert "presentation" not in brief
        wired_events = [(e.event_type, e.content) for e in await wired.stored_events()]
        bare_events = [(e.event_type, e.content) for e in await bare.stored_events()]
        assert wired_events == bare_events
    finally:
        await wired.close()
        await bare.close()


# ==========================================================================
# Privacy: the planted room phrase reaches no durable sink
# ==========================================================================


#: ASCII, so that a byte search finds it in any file, SQLite pages included.
PLANTED = "ornithorynque-confidentiel-5530"


def _sinks_containing(root: Path, needle: str) -> list[str]:
    """Every file under `root`, read as raw bytes (`-wal` and `-shm` included)."""

    patterns = (needle.encode("utf-8"), needle.encode("utf-16-le"))
    return [path.relative_to(root).as_posix() for path in root.rglob("*")
            if path.is_file() and any(pattern in path.read_bytes() for pattern in patterns)]


async def test_no_planted_room_phrase_in_any_durable_sink(tmp_path) -> None:
    """A full composed session over a **real** Core and a **real** Control Center.

    The room phrase is planted everywhere it could enter: the ambient lane, the
    realtime transcript of the room (P10), a noise drop inside a live window
    (Issue 002), a claim offered to a preparation (whose sub-agent copies its
    prompt into its cwd) and a verdict's reason. The addressed question goes
    to the real brain path: Core → Control Center → `ClaudeLocalAgent` → the
    CLI's stdin, the one place the room is allowed to reach (B1 and B2 are the
    accepted limits outside this root).

    Every file under the test root is then read byte by byte, twice: while
    Core runs (its `-wal` not yet checkpointed) and after everything stopped.
    Sinks: Voice trace and errors, Core trace and state DB with its
    Conversation Events, the Control Center journal, the staged-object ledger,
    the status files and the preparation workspace root.
    """

    from aiohttp import web

    from jarvis.adapters.control_center_brain import ControlCenterBrainBackend
    from jarvis.runtime.control_center import ControlCenter
    from jarvis.runtime.conversation_event_forwarder import CoreConversationEventTransport
    from jarvis.runtime.journal import RuntimeJournal
    from tests.integration.test_v2_brain_protocol import TOKEN
    from tests.unit.test_presentation_brain_context_transport import _Process, core_stack, idle

    token_file = tmp_path / "core.token"
    token_file.write_text(TOKEN, encoding="utf-8")
    control = ControlCenter(runtime_root=tmp_path / "cc", project_root=tmp_path / "cc")
    agent = control.agent
    assert type(agent).__name__ == "ClaudeLocalAgent", "the real agent, with its real journal"
    agent.process = _Process(agent)
    app = web.Application()
    app.add_routes([web.post("/api/agent/ask", control.agent_ask)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    backend = ControlCenterBrainBackend(base_url=f"http://127.0.0.1:{runner.addresses[0][1]}", timeout_s=5)
    core_journal = RuntimeJournal(tmp_path / "core-runtime")
    during: list[str] = []
    try:
        async with core_stack(tmp_path / "core", backend, diagnostics=core_journal) as (core, client, port):
            conversation = (await client.create_conversation())["id"]
            await client.set_interaction_mode("presentation", source="test")
            rig = await build_rig(
                tmp_path / "voice", mode=InteractionMode.PRESENTATION, core=client,
                conversation_id=conversation,
                events_transport=CoreConversationEventTransport(host="127.0.0.1", port=port,
                                                                token_file=token_file),
            )
            try:
                rig.agents.assess = ("contradicted", 0.9)
                rig.agents.reason = f"faux : {PLANTED} ne dit pas cela"
                await rig.room(f"selon {PLANTED} la marge nette a doublé, plus de 40 pour cent cette année")
                await rig.stack.speculative.drain()
                await rig.press()
                await rig.hear(f"Merci d'avoir regardé cette vidéo {PLANTED}")   # noise in a live window
                rig.agents.findings = [COURBE]
                await rig.addressed("montre-moi ça")
                await rig.stack.speculative.drain()
                await rig.addressed("de quoi on parle ?")
                await until(lambda: agent.process.stdin.written, timeout=5.0)
                await idle(core)
                await until(lambda: rig.session.spoken, timeout=5.0)
                await rig.set_mode(InteractionMode.ASSISTANT)
                await rig.forwarder.flush()
                during = _sinks_containing(tmp_path, PLANTED)
            finally:
                await rig.close()
                await rig.forwarder.aclose()
    finally:
        await backend.close()
        await runner.cleanup()

    stdin = agent.process.stdin.written.decode("utf-8")
    assert PLANTED in stdin, "the model receives the room: otherwise this test proves nothing"
    assert rig.stack is None and rig.agents.agents, "the session ran preparations and ended"
    assert any(PLANTED in prompt for agent_ in rig.agents.agents for prompt in agent_.asked), (
        "a sub-agent was given the planted claim: its scratch file had it"
    )
    assert during == [], during
    assert _sinks_containing(tmp_path, PLANTED) == []

    # Each sink was written: an empty journal would prove nothing.
    voice = rig.journal.trace_path.read_text(encoding="utf-8")
    assert '"addressing": "ambient"' in voice and '"code": "transcript_hallucination"' in voice
    assert "presentation.attention" in voice and "presentation.staging.staged" in voice
    assert "core.brain" in core_journal.trace_path.read_text(encoding="utf-8")
    assert '"agent.input"' in agent.journal.trace_path.read_text(encoding="utf-8")
    assert (tmp_path / "core" / "state" / "jarvis.sqlite3").exists()
    assert (rig.runtime / "presentation-staged-objects.json").exists()
    prep_root = rig.data / "presentation" / "prep"
    assert prep_root.is_dir() and not any(prep_root.iterdir())
    async with core_stack(tmp_path / "core", backend) as (core, client, _):
        page = await core.conversation_events.list_conversation_events(conversation, limit=500)
        types = {item.event.event_type for item in page.events}
    assert {T.SYSTEM_MODE_CHANGED, T.SUBAGENT_STARTED, T.SYSTEM_ATTENTION_RAISED} <= types


# ==========================================================================
# Latency and concurrency: ambient load must not slow an explicit turn
# ==========================================================================

TURNS = 12
#: Quiet and loaded runs alternate this many times; the verdict is the median over them.
REPEATS = 5
#: The slow provider of the loaded run: each ambient transcription takes this long.
SLOW_PROVIDER_S = 0.05
#: What the test guarantees (wall-clock on fakes, so absolute, not a ratio): the median p50 may
#: grow by at most max(10 %, P50_FLOOR_MS), and the median p95 never exceeds P95_CEILING_MS.
#: Measured quiet baseline is 4-7 ms; a 30 ms admission delay under load breaks both.
P50_FLOOR_MS = 5.0
P95_CEILING_MS = 20.0


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def _median(values: list[float]) -> float:
    return _percentile(values, 0.5)


def _admission_ms(rig: Rig) -> list[float]:
    return [float(line["data"]["elapsed_ms"]) for line in rig.trace()
            if line["data"].get("code") == "addressed_admission_latency"]


async def _explicit_turns(rig: Rig, *, loaded: bool) -> list[float]:
    """TURNS addressed questions; when `loaded`, each lands on a busy pool and a slow provider.

    Loaded: two ambient preparations are running when the key is pressed, and
    the pool bound (`in_flight <= pool`, speculative <= max) holds at every step.
    """

    if loaded:
        rig.agents.gate = asyncio.Event()
        rig.transcriber.delay_s = SLOW_PROVIDER_S
    for index in range(TURNS):
        if loaded:
            await rig.room(f"{CLAIM}, version {index} du rapport {index * 7}")
            await until(lambda: rig.stack.speculative.stats()["speculative_in_flight"] == 2, timeout=5.0)
        before = len(rig.core.brain_turns)
        await rig.addressed(f"quelle est la réponse numéro {index} ?")
        assert len(rig.core.brain_turns) == before + 1, "the explicit turn is always admitted"
        stats = rig.stack.speculative.stats()
        assert stats["in_flight"] <= stats["pool"], stats
        assert stats["speculative_in_flight"] <= stats["max_speculative"], stats
    return _admission_ms(rig)


async def _one_run(root: Path, *, loaded: bool) -> list[float]:
    rig = await build_rig(root, mode=InteractionMode.PRESENTATION)
    try:
        samples = await _explicit_turns(rig, loaded=loaded)
        if loaded:
            assert rig.transcriber.calls >= TURNS, "the slow provider really served the ambient lane"
            rig.agents.gate.set()
            await rig.stack.speculative.drain()
        return samples
    finally:
        await rig.close()
        input_ownership.reset_for_test()   # process state: this run's stream is gone


async def test_explicit_turn_latency_is_unchanged_by_ambient_load_and_running_preparations(tmp_path) -> None:
    """Median over REPEATS alternating runs: p50 within max(10 %, 5 ms) of quiet, p95 under an absolute ceiling."""

    quiet_p50, quiet_p95, loaded_p50, loaded_p95 = [], [], [], []
    for repeat in range(REPEATS):
        for loaded, p50s, p95s in ((False, quiet_p50, quiet_p95), (True, loaded_p50, loaded_p95)):
            samples = await _one_run(tmp_path / f"{'busy' if loaded else 'quiet'}-{repeat}", loaded=loaded)
            assert len(samples) == TURNS
            p50s.append(_percentile(samples, 0.5))
            p95s.append(_percentile(samples, 0.95))

    base, load = _median(quiet_p50), _median(loaded_p50)
    p95 = _median(loaded_p95)
    print(f"admission latency ms: p50 quiet {base:.2f} loaded {load:.2f}; "
          f"p95 quiet {_median(quiet_p95):.2f} loaded {p95:.2f}")
    assert load - base <= max(0.10 * base, P50_FLOOR_MS), (quiet_p50, loaded_p50)
    assert p95 <= P95_CEILING_MS, (quiet_p95, loaded_p95)
