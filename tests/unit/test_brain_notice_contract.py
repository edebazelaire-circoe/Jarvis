"""Contrat des relais spontanés typés (Slice 03, `jarvis/domain/brain_notice.py`).

Les tests T6a–T6e (`test_speech_presentation_revalidation.py`,
`test_spontaneous_notice_typing.py`) tiennent le cas de la calibration. Ceux-ci
tiennent le reste du contrat, frontière par frontière :

- validation du genre (`NoticeTyping`) ;
- refus tracé, jamais silencieux, côté Control Center (`publish_notice`) et
  côté Core (`announce_notice`) ;
- compatibilité : une notice de l'ancien format (sans genre) est toujours dite,
  en `result` ;
- trace `core.brain.notice_relayed` enrichie (`speech_id`, `kind`,
  `supersedes_key`, `expires_at`), un `result` sans `work_id` compris ;
- relais de fin de sous-agent rattaché à son travail quand il est connu.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from jarvis.core.brain_service import BRAIN_SPEECH_REQUESTED
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.brain_notice import MAX_NOTICE_TTL_S, MIN_NOTICE_TTL_S, NoticeTyping
from jarvis.domain.speech_presentation import SpeechDependency
from jarvis.domain.v2 import BrainTurnInput, SpeechKind
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.journal import read_jsonl_tail
from tests.fakes.virtual_time_loop import run_virtual
from tests.unit.test_agent_tasks import agent_call, async_launched, feed, notification, task_started, tool_call
from tests.unit.test_brain_delegation import (
    TIMEOUT_S,
    NoticeBackend,
    ScriptedBackend,
    _drain,
    _idle,
    _orchestrator,
    _result,
)


# ------------------------------------------------------------------ contrat


def test_a_notice_without_kind_is_a_result_and_every_field_is_explicit_on_the_wire():
    typing = NoticeTyping.from_payload({"text": "Le transcript est prêt.", "seq": 3})
    assert typing.kind is SpeechKind.RESULT
    assert typing.to_payload() == {"kind": "result", "supersedes_key": None, "ttl_s": None, "work_id": None}
    assert NoticeTyping(kind="ack", supersedes_key="calibration:s:5", ttl_s=15).to_payload() == {
        "kind": "ack", "supersedes_key": "calibration:s:5", "ttl_s": 15.0, "work_id": None}


@pytest.mark.parametrize("fields", [
    {"kind": "shout"},
    {"kind": "ACK"},  # le vocabulaire est `SpeechKind` : pas de variante devinée
    {"kind": 3},
    {"kind": "error"},  # natures de sûreté : jamais déclarées par un relais
    {"kind": SpeechKind.QUESTION},
    {"ttl_s": 0},
    {"ttl_s": 1e-7},  # passait ]0 ; ...] puis faisait lever SpeechRequest dans Core
    {"ttl_s": MIN_NOTICE_TTL_S / 2},
    {"ttl_s": -1},
    {"ttl_s": True},
    {"ttl_s": float("nan")},
    {"ttl_s": MAX_NOTICE_TTL_S + 1},
    {"ttl_s": "15"},
    {"supersedes_key": ""},
    {"supersedes_key": " calibration:1"},
    {"work_id": "x" * 300},
])
def test_a_notice_outside_the_contract_is_refused(fields):
    with pytest.raises(ValueError):
        NoticeTyping(**fields)


# ------------------------------------------------------- Control Center (CLI)


def test_publish_notice_refuses_an_unknown_kind_and_journals_it(tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    assert agent.publish_notice("Bonjour.", origin="calibration_ack", kind="shout") is False
    assert agent.notices == []
    [refused] = [line for line in read_jsonl_tail(tmp_path / "trace.jsonl") if line["kind"] == "agent.notice_refused"]
    assert refused["level"] == "error"
    assert refused["data"]["code"] == "invalid_notice" and refused["data"]["origin"] == "calibration_ack"


def test_a_published_notice_is_served_with_its_kind_and_journaled_with_it(tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    assert agent.publish_notice("Je regarde.", origin="x", kind=SpeechKind.PROGRESS, supersedes_key="k:1", ttl_s=10)
    [notice] = agent.notices
    assert (notice["kind"], notice["supersedes_key"], notice["ttl_s"], notice["work_id"]) == ("progress", "k:1", 10.0, None)
    [line] = [line for line in read_jsonl_tail(tmp_path / "trace.jsonl") if line["kind"] == "agent.unsolicited_result"]
    assert (line["data"]["kind"], line["data"]["supersedes_key"], line["data"]["seq"]) == ("progress", "k:1", 1)


def _finished_background_task(agent: ClaudeLocalAgent, tool_use_id: str, task_id: str) -> None:
    feed(agent, agent_call(tool_use_id, f"Tâche {task_id}"), async_launched(tool_use_id, task_id),
         notification(task_id, tool_use_id, "completed", "fini"))


def test_a_subagent_relay_carries_the_work_it_concludes(tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    _finished_background_task(agent, "toolu_A", "a1")
    agent._push_notice(_result("Le sous-agent a fini.", origin="task-notification"))  # noqa: SLF001
    [notice] = agent.notices
    assert notice["kind"] == "result"
    assert notice["work_id"] == agent.subtasks.find("a1").work_key == "toolu_A"


def test_a_subagent_relay_after_several_completions_names_no_work_and_says_so(tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    _finished_background_task(agent, "toolu_A", "a1")
    _finished_background_task(agent, "toolu_B", "b1")
    agent._push_notice(_result("Les deux ont fini.", origin="task-notification"))  # noqa: SLF001
    # Le relais suivant ne voit plus ces candidates : la file a été vidée.
    agent._push_notice(_result("Rien de neuf.", origin="task-notification"))  # noqa: SLF001
    assert [(n["kind"], n["work_id"]) for n in agent.notices] == [("result", None), ("result", None)]
    unknown = [line["data"] for line in read_jsonl_tail(tmp_path / "trace.jsonl")
               if line["kind"] == "agent.notice_work_unknown"]
    assert [(data["reason"], data["candidates"]) for data in unknown] == [
        ("several_finished_background_tasks", 2), ("no_finished_background_task", 0)]


# ------------------------------------------------------------------- Core


async def test_core_refuses_a_notice_of_unknown_kind_visibly(tmp_path):
    brain, events, state, conversation_id, sink = await _orchestrator(tmp_path, ScriptedBackend())
    try:
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Lance la recherche."))
        await _idle(brain)
        queue = events.subscribe()
        assert await brain.announce_notice("Bonjour.", kind="shout") is False
        assert await brain.announce_notice("Bonjour.", kind=SpeechKind.ACK, ttl_s=-3) is False
        assert [e for e in _drain(queue) if e.message_type == BRAIN_SPEECH_REQUESTED] == []
        assert [data["reason"] for data in sink.of("core.brain.notice_dropped")] == ["invalid_notice", "invalid_notice"]
        assert [level for name, level, _ in sink.events if name == "core.brain.notice_dropped"] == ["error", "error"]
    finally:
        await brain.stop()
        await state.close()


async def test_every_relay_is_traced_with_its_presentation_identity_and_typing(tmp_path):
    brain, events, state, conversation_id, sink = await _orchestrator(tmp_path, ScriptedBackend())
    try:
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Lance la calibration."))
        await _idle(brain)
        queue = events.subscribe()
        assert await brain.announce_notice("Je regarde.", kind="ack", supersedes_key="calibration:s:5", ttl_s=15)
        assert await brain.announce_notice("Voilà l'analyse.")  # result, sans travail
        assert await brain.announce_notice("Le sous-agent a fini.", work_id="toolu_A")
        speeches = [e.payload for e in _drain(queue) if e.message_type == BRAIN_SPEECH_REQUESTED]
        relayed = sink.of("core.brain.notice_relayed")
        assert [s["text"] for s in speeches] == ["Je regarde.", "Voilà l'analyse.", "Le sous-agent a fini."]
        assert [r["speech_id"] for r in relayed] == [s["speech_id"] for s in speeches]
        ack, analysis, subagent = relayed
        assert (ack["kind"], ack["supersedes_key"]) == ("ack", "calibration:s:5")
        assert ack["expires_at"] == speeches[0]["expires_at"]
        created = datetime.fromisoformat(speeches[0]["created_at"])
        assert (datetime.fromisoformat(ack["expires_at"]) - created).total_seconds() == pytest.approx(15.0)
        assert (analysis["kind"], analysis["supersedes_key"], analysis["expires_at"], analysis["work_id"]) == (
            "result", None, None, None)
        assert analysis["speech_id"]
        assert (subagent["kind"], subagent["work_id"]) == ("result", "toolu_A")
        assert speeches[2]["work_id"] == "toolu_A"
        # Un accusé transitoire n'est pas un fait public ; un résultat l'est.
        facts = brain.working_state(conversation_id).known_public_facts
        assert "Je regarde." not in facts and "Voilà l'analyse." in facts
    finally:
        await brain.stop()
        await state.close()


async def test_an_ack_without_its_own_ttl_gets_cores_default_deadline(tmp_path):
    brain, events, state, conversation_id, sink = await _orchestrator(tmp_path, ScriptedBackend())
    try:
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Lance."))
        await _idle(brain)
        assert await brain.announce_notice("Je regarde.", kind=SpeechKind.ACK)
        [relayed] = sink.of("core.brain.notice_relayed")
        assert relayed["expires_at"] is not None
    finally:
        await brain.stop()
        await state.close()


async def test_an_old_format_notice_from_the_control_center_is_still_spoken_as_a_result(tmp_path):
    """Compatibilité : un Control Center d'avant la Slice 03 sert `{seq, text, origin}`,
    que `next_notices` transmet sans genre ; Core le dit, en `result`."""
    backend = NoticeBackend()
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend)
    await core.start()
    try:
        conversation = await core.conversations.create()
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, text="Fais le transcript."))
        await _idle(core.brain)
        queue = core.events.subscribe()
        await backend.queue.put(({"text": "Le transcript est prêt.", "kind": None, "supersedes_key": None,
                                  "ttl_s": None, "work_id": None},))
        speech = None
        while speech is None:
            envelope = await asyncio.wait_for(queue.get(), timeout=TIMEOUT_S)
            if envelope.message_type == BRAIN_SPEECH_REQUESTED:
                speech = envelope.payload
        assert (speech["text"], speech["kind"], speech["expires_at"]) == ("Le transcript est prêt.", "result", None)
    finally:
        await core.stop()


async def test_a_relay_is_visible_in_the_conversation_journal_with_its_kind_and_trace(tmp_path):
    """Le `brain.speech.requested` d'un relais porte son genre et se joint à la
    ligne `core.brain.notice_relayed` (clé, échéance, identité de présentation)."""
    from jarvis.domain.conversation_events import ConversationEventType, trace_entry_matches
    from tests.unit.test_conversation_event_producers import Journal, ScriptBackend, of_type, settle, start_core, stored

    journal = Journal()
    core = await start_core(tmp_path, ScriptBackend(), journal)
    try:
        conversation = await core.conversations.create()
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, text="Lance la calibration."))
        await settle(core)
        assert await core.brain.announce_notice("Je regarde.", kind="ack", supersedes_key="calibration:s:5", ttl_s=15)
        await settle(core)
        [speech] = [event for event in of_type(await stored(core, conversation.id),
                                               ConversationEventType.BRAIN_SPEECH_REQUESTED)
                    if event.content == "Je regarde."]
        assert speech.attributes["kind"] == "ack"
        [line] = journal.of("core.brain.notice_relayed")
        assert trace_entry_matches(speech, {"kind": "core.brain.notice_relayed", "data": line["data"]})
        assert line["data"]["supersedes_key"] == "calibration:s:5" and line["data"]["expires_at"]
    finally:
        await core.stop()



def test_the_shortest_declared_lifetime_is_one_second():
    assert NoticeTyping(kind="ack", ttl_s=MIN_NOTICE_TTL_S).ttl_s == 1.0


# ------------------------------------------- rattachement d'un relais (reprise QA)


def _finished_background_shell(agent: ClaudeLocalAgent, tool_use_id: str, task_id: str) -> None:
    feed(agent, tool_call(tool_use_id, "Bash", {"command": "sleep 60", "description": "wait"}),
         task_started(task_id, tool_use_id, "wait", task_type="local_bash", background=True),
         notification(task_id, tool_use_id, "completed", "done"))


def _unknown_reasons(tmp_path) -> list[str]:  # noqa: ANN001
    return [line["data"]["reason"] for line in read_jsonl_tail(tmp_path / "trace.jsonl")
            if line["kind"] == "agent.notice_work_unknown"]


def test_a_shell_relay_is_never_attached_to_an_earlier_subagent(tmp_path):
    """Sonde QA : A finit (sa notification absorbée ailleurs), puis une commande de
    fond finit et le CLI ouvre un tour pour elle. Le relais de la commande ne
    doit pas porter `toolu_A` : Core retiendrait le texte de la commande comme
    résultat de A et marquerait A comme dit."""
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    _finished_background_task(agent, "toolu_A", "a1")
    _finished_background_shell(agent, "toolu_S", "s1")
    agent._push_notice(_result("La commande a fini.", origin="task-notification"))  # noqa: SLF001
    [notice] = agent.notices
    assert notice["work_id"] is None
    assert _unknown_reasons(tmp_path) == ["several_finished_background_tasks"]


def test_a_lone_shell_relay_names_no_work(tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    _finished_background_shell(agent, "toolu_S", "s1")
    agent._push_notice(_result("La commande a fini.", origin="task-notification"))  # noqa: SLF001
    assert [notice["work_id"] for notice in agent.notices] == [None]
    assert _unknown_reasons(tmp_path) == ["finished_task_not_a_subagent"]


def test_a_completion_absorbed_by_another_turn_is_not_attached_to_the_next_relay(tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    _finished_background_task(agent, "toolu_A", "a1")
    # Un autre tour rend son `result` : la fin de A y a été absorbée.
    agent._on_result(_result("Voilà.", uuids=["panel-msg"]))  # noqa: SLF001
    agent._push_notice(_result("Autre chose a fini.", origin="task-notification"))  # noqa: SLF001
    assert [notice["work_id"] for notice in agent.notices] == [None]
    assert _unknown_reasons(tmp_path) == ["no_finished_background_task"]


def test_an_interrupted_background_task_is_not_a_relay_candidate(tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    feed(agent, agent_call("toolu_I", "Tâche i1"), async_launched("toolu_I", "i1"))
    agent.subtasks.process_stopped()  # l'agent principal s'arrête : i1 est interrompue
    assert agent.subtasks.find("i1").status == "interrupted"
    _finished_background_task(agent, "toolu_B", "b1")
    agent._push_notice(_result("B a fini.", origin="task-notification"))  # noqa: SLF001
    assert [notice["work_id"] for notice in agent.notices] == ["toolu_B"]


# ------------------------------------------------- boucle de relais de Core


class _SinkRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        del message
        self.events.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[tuple[str, dict]]:
        return [(level, data) for name, level, data in self.events if name == kind]


def test_a_relay_whose_announce_raises_is_traced_and_the_loop_goes_on(tmp_path):
    sink = _SinkRecorder()
    core = JarvisCoreApplication(data_root=tmp_path, diagnostics=sink)
    announced: list[str] = []

    async def announce(text, **fields):  # noqa: ANN001, ANN003
        del fields
        if text == "boum":
            raise ValueError("expires_at must be after created_at")
        announced.append(text)
        return True

    core.brain.announce_notice = announce  # type: ignore[method-assign]
    batches: list[object] = [RuntimeError("Control Center muet"), ({"text": "boum"}, {"text": "suivant"})]

    async def next_notices():
        if not batches:
            await asyncio.Event().wait()
        item = batches.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def scenario():
        task = asyncio.create_task(core._brain_notice_loop(next_notices))  # noqa: SLF001
        while "suivant" not in announced:
            await asyncio.sleep(0.5)
        assert not task.done(), "la boucle des relais est morte"
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    run_virtual(scenario())
    assert announced == ["suivant"]
    [(poll_level, poll)] = sink.of("core.brain.notice_poll_failed")
    assert poll_level == "error" and poll["exception_type"] == "RuntimeError"
    [(drop_level, drop)] = sink.of("core.brain.notice_dropped")
    assert drop_level == "error" and drop["reason"] == "announce_failed" and drop["exception_type"] == "ValueError"


async def test_a_relay_withheld_by_cores_speech_policy_is_dropped_not_relayed(tmp_path):
    brain, events, state, conversation_id, sink = await _orchestrator(tmp_path, ScriptedBackend())
    try:
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Lance."))
        await _idle(brain)
        current = await state.get_current_brain_source(conversation_id)
        cancelled = SpeechDependency("toolu_A", current.correlation_id)

        async def invalidated(conversation):  # noqa: ANN001 - le cerveau a annulé le travail A
            del conversation
            return {cancelled}

        brain.outcomes.repository.list_invalidated_brain_dependencies = invalidated
        queue = events.subscribe()
        assert await brain.announce_notice("A a fini.", work_id="toolu_A") is False
        assert [e for e in _drain(queue) if e.message_type == BRAIN_SPEECH_REQUESTED] == []
        assert sink.of("core.brain.notice_relayed") == []
        [dropped] = sink.of("core.brain.notice_dropped")
        assert dropped["reason"] == "work_cancelled" and dropped["work_id"] == "toolu_A"
        assert "A a fini." not in brain.working_state(conversation_id).known_public_facts
    finally:
        await brain.stop()
        await state.close()


async def test_a_relayed_ack_carries_its_key_and_deadline_as_event_attributes(tmp_path):
    from jarvis.domain.conversation_events import ConversationEventType
    from tests.unit.test_conversation_event_producers import Journal, ScriptBackend, of_type, settle, start_core, stored

    core = await start_core(tmp_path, ScriptBackend(), Journal())
    try:
        conversation = await core.conversations.create()
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, text="Lance la calibration."))
        await settle(core)
        assert await core.brain.announce_notice("Je regarde.", kind="ack", supersedes_key="calibration:s:5", ttl_s=15)
        assert await core.brain.announce_notice("Voilà l'analyse.")
        await settle(core)
        speeches = {event.content: event for event in of_type(await stored(core, conversation.id),
                                                               ConversationEventType.BRAIN_SPEECH_REQUESTED)}
        ack, analysis = speeches["Je regarde."], speeches["Voilà l'analyse."]
        assert ack.attributes["supersedes_key"] == "calibration:s:5"
        assert datetime.fromisoformat(ack.attributes["expires_at"]) > ack.occurred_at
        assert "supersedes_key" not in analysis.attributes and "expires_at" not in analysis.attributes
    finally:
        await core.stop()
