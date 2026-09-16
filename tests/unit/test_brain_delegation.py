"""Le brain reste disponible : il aiguille, il n'exécute pas.

Retours utilisateur n° 8 et 10 du 11/09/2026 : le brain a fait une recherche
web de 85 s dans le tour, les phrases suivantes ont attendu derrière lui, et
les réponses arrivaient 30 à 37 s trop tard, dans le désordre.

Deux moitiés, testées séparément :

- **règles** : la consigne de délégation est au niveau système du CLI (et
  rappelée dans le contexte par tour quand du travail tourne déjà), et rien ne
  retire l'outil `Agent` au brain ;
- **back-end** : les réponses sont attribuées par `uuid` (le tour que le CLI
  ouvre seul à la fin d'un sous-agent ne vole plus la réponse de la question
  suivante), ce relais est dit à la voix, une nouvelle intention périme les
  réponses encore en file, et un tour trop long est mesuré dans la trace.

Ce qui n'est pas prouvé ici : que le modèle obéit à la consigne. Seuls des
essais réels le montrent, et `agent.turn_over_budget` est là pour les mesurer.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from aiohttp import web

from jarvis.adapters.control_center_brain import ControlCenterBrainBackend
from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.brain_service import (
    BRAIN_INTENT_REVISED,
    BRAIN_SPEECH_REQUESTED,
    BrainOrchestrator,
)
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.core.v2_services import ConversationService, CoreEventBus
from jarvis.domain.v2 import (
    BRAIN_NOT_ADDRESSED_ANSWER,
    AddressingDecision,
    BrainEvent,
    BrainEventKind,
    BrainTurnInput,
    BrainTurnResult,
    ProtocolEnvelope,
    SpeechKind,
    SpeechRequest,
)
from jarvis.runtime import claude_local
from jarvis.runtime.claude_local import BRAIN_SYSTEM_PROMPT, ClaudeLocalAgent, cli_prompt_argument
from jarvis.runtime.control_center import BRIEF_DELEGATION_REMINDER, ControlCenter, build_agent_brief
from jarvis.runtime.journal import read_jsonl_tail

TIMEOUT_S = 5.0


# ===========================================================================
# Règles
# ===========================================================================


def test_the_system_prompt_makes_delegation_a_firm_rule_with_concrete_criteria():
    prompt = BRAIN_SYSTEM_PROMPT
    assert "RÈGLE ABSOLUE" in prompt
    # Le moyen, nommé tel que le modèle le voit.
    assert "outil Agent" in prompt and "run_in_background à true" in prompt
    # Les critères concrets du retour n° 10, pas un conseil vague.
    for criterion in ("WebSearch", "WebFetch", "plusieurs fichiers", "modification de code", "plusieurs étapes", "quelques secondes"):
        assert criterion in prompt, criterion
    assert "Ne fais jamais ce travail toi-même" in prompt
    # Réponse immédiate d'une phrase, puis relais court à la fin du sous-agent.
    assert "réponds en une phrase" in prompt
    assert "relaie le résultat en une à trois phrases" in prompt
    # Le relais qui ne mérite rien se tait par la réponse convenue.
    assert BRAIN_NOT_ADDRESSED_ANSWER in prompt
    # Réponses lues à voix haute.
    assert "Pas de markdown" in prompt and "tableaux" in prompt


class _FakePipedProcess:
    pid = 4321

    def __init__(self) -> None:
        self.returncode = 0
        self.stdin = None
        self.stdout = _EmptyStream()
        self.stderr = _EmptyStream()

    async def wait(self) -> int:
        return 0


class _EmptyStream:
    async def readline(self) -> bytes:
        return b""


async def test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available(tmp_path, monkeypatch):
    started: list[list[str]] = []

    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        started.append(list(args))
        return _FakePipedProcess()

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    await agent.start()

    argv = started[0]
    index = argv.index("--append-system-prompt")
    assert argv[index + 1] == cli_prompt_argument(BRAIN_SYSTEM_PROMPT, argv[0])
    # Rien ne restreint les outils du brain : l'outil Agent (sous-agents) reste
    # disponible, et le mode par défaut ne demande aucune approbation.
    for restriction in ("--tools", "--allowedTools", "--allowed-tools", "--disallowedTools", "--disallowed-tools", "--restricted"):
        assert restriction not in argv
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"


def test_a_cmd_shim_receives_the_rule_on_a_single_line():
    """`cmd.exe` couperait la commande au premier retour à la ligne."""

    flat = cli_prompt_argument(BRAIN_SYSTEM_PROMPT, r"C:\npm\claude.CMD")
    assert "\n" not in flat and "RÈGLE ABSOLUE" in flat
    assert cli_prompt_argument(BRAIN_SYSTEM_PROMPT, r"C:\bin\claude.exe") == BRAIN_SYSTEM_PROMPT


def test_the_turn_context_recalls_the_rule_only_when_work_is_already_running():
    busy = build_agent_brief({"addressing": "addressed", "state": {"active_work_ids": ["brain-turn:corr-1"]}}, "Et le prix en euros ?")
    idle = build_agent_brief({"addressing": "addressed", "state": {"active_work_ids": []}}, "Salut")

    assert BRIEF_DELEGATION_REMINDER in busy
    # Le rappel précède la demande, qu'il doit encadrer.
    assert busy.index(BRIEF_DELEGATION_REMINDER) < busy.index("[Demande]")
    assert BRIEF_DELEGATION_REMINDER not in idle
    assert "sous-agent d'arrière-plan" in BRIEF_DELEGATION_REMINDER


# ===========================================================================
# Back-end : attribution des réponses du CLI
# ===========================================================================


class FakeStdin:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None


class FakeProcess:
    pid = 1234

    def __init__(self) -> None:
        self.stdin = FakeStdin()
        self.returncode = None

    def terminate(self) -> None:
        self.returncode = 1

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


def _running_agent(tmp_path: Path) -> ClaudeLocalAgent:
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    agent.process = FakeProcess()  # type: ignore[assignment]
    return agent


async def test_composed_prompt_reaches_claude_but_private_layers_stay_out_of_history(tmp_path):
    agent = _running_agent(tmp_path)
    marker = "PRIVATE_BACKEND_TURN_MARKER"
    composed = f"{marker}\n[Demande]\nquestion publique"

    await agent.send(
        composed,
        prompt_evidence={"program_id": "backend.claude.turn", "application": "sent"},
        input_text="question publique",
    )

    payload = json.loads(agent.process.stdin.written[-1].decode("utf-8"))  # type: ignore[union-attr]
    assert marker in payload["message"]["content"]
    assert marker not in json.dumps(agent.snapshot(), ensure_ascii=False)
    assert marker not in json.dumps(read_jsonl_tail(tmp_path / "trace.jsonl"), ensure_ascii=False)
    assert agent.prompt_applications == [{"program_id": "backend.claude.turn", "application": "sent"}]


async def test_failed_claude_start_discards_one_shot_prompt_evidence(tmp_path, monkeypatch):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)

    async def fail_start() -> None:
        raise RuntimeError("cli missing")

    monkeypatch.setattr(agent, "start", fail_start)
    agent.set_next_prompt_evidence({"program_id": "old-turn"})
    with pytest.raises(RuntimeError, match="cli missing"):
        await agent.send("premier tour")

    assert agent._next_prompt_evidence is None
    agent.process = FakeProcess()  # type: ignore[assignment]
    await agent.send("tour suivant")
    assert agent.prompt_applications == []


async def _sent_uuid(agent: ClaudeLocalAgent, index: int = -1) -> str:
    for _ in range(100):
        written = agent.process.stdin.written  # type: ignore[union-attr]
        if written and (index < 0 or len(written) > index):
            return json.loads(written[index].decode("utf-8"))["uuid"]
        await asyncio.sleep(0)
    raise AssertionError("aucun message écrit")


def _result(text: str, *, uuids: list[str] | None = None, origin: str | None = None, **extra) -> dict:
    event = {"type": "result", "subtype": "success", "result": text, "session_id": "sid", **extra}
    if uuids is not None:
        event["user_message_uuids"] = uuids
        if uuids:
            event["user_message_uuid"] = uuids[0]
    if origin is not None:
        event["origin"] = {"kind": origin}
    return event


async def test_the_turn_opened_by_a_finished_subagent_no_longer_steals_the_next_answer(tmp_path):
    """Trace du 11/09, 15:50 : le relais du sous-agent devenait la réponse de
    « Totalement, totalement », puis chaque réponse glissait d'un cran."""

    agent = _running_agent(tmp_path)
    waiting = asyncio.create_task(agent.ask("Totalement, totalement.", timeout_s=TIMEOUT_S))
    uid = await _sent_uuid(agent)

    # Le CLI termine d'abord le tour qu'il a ouvert seul pour le sous-agent.
    agent._resolve_pending(_result("Le sous-agent a répondu : le silence est facturé.", origin="task-notification"))
    await asyncio.sleep(0)
    assert not waiting.done()

    agent._resolve_pending(_result("D'accord.", uuids=[uid]))
    answer = await asyncio.wait_for(waiting, timeout=TIMEOUT_S)

    assert answer["text"] == "D'accord."
    # Le relais n'est pas perdu : il attend d'être dit.
    assert [notice["text"] for notice in agent.notices] == ["Le sous-agent a répondu : le silence est facturé."]
    assert any(e["kind"] == "agent.unsolicited_result" for e in read_jsonl_tail(tmp_path / "trace.jsonl"))


async def test_a_turn_that_merged_the_question_answers_it(tmp_path):
    """Un message écrit pendant un tour peut y être fusionné : le `result` les couvre tous."""

    agent = _running_agent(tmp_path)
    waiting = asyncio.create_task(agent.ask("Et en euros ?", timeout_s=TIMEOUT_S))
    uid = await _sent_uuid(agent)

    agent._resolve_pending(_result("Environ 4 centimes.", uuids=["un-autre-message", uid]))

    assert (await asyncio.wait_for(waiting, timeout=TIMEOUT_S))["text"] == "Environ 4 centimes."
    assert agent.notices == []


async def test_an_answer_to_another_message_is_not_handed_to_the_voice_question(tmp_path):
    agent = _running_agent(tmp_path)
    waiting = asyncio.create_task(agent.ask("Quelle heure est-il ?", timeout_s=TIMEOUT_S))
    uid = await _sent_uuid(agent)

    # Réponse à un message du panneau, écrit hors de la boucle vocale.
    agent._resolve_pending(_result("Réponse au panneau.", uuids=["message-du-panneau"]))
    await asyncio.sleep(0)
    assert not waiting.done()
    assert agent.notices == []

    agent._resolve_pending(_result("Il est midi.", uuids=[uid]))
    assert (await asyncio.wait_for(waiting, timeout=TIMEOUT_S))["text"] == "Il est midi."


async def test_a_late_answer_is_recognised_by_its_uuid(tmp_path):
    agent = _running_agent(tmp_path)
    first = await agent.ask("question abandonnée", timeout_s=0.05)
    assert first["code"] == "claude_timeout"
    abandoned = await _sent_uuid(agent, 0)

    waiting = asyncio.create_task(agent.ask("nouvelle question", timeout_s=TIMEOUT_S))
    fresh = await _sent_uuid(agent, 1)
    agent._resolve_pending(_result("réponse en retard", uuids=[abandoned]))
    await asyncio.sleep(0)
    assert not waiting.done()
    agent._resolve_pending(_result("la bonne réponse", uuids=[fresh]))

    assert (await asyncio.wait_for(waiting, timeout=TIMEOUT_S))["text"] == "la bonne réponse"
    assert agent.notices == []
    assert agent._abandoned == 0


async def test_a_relay_that_deserves_nothing_stays_silent(tmp_path):
    agent = _running_agent(tmp_path)
    agent._resolve_pending(_result(BRAIN_NOT_ADDRESSED_ANSWER, origin="task-notification"))
    agent._resolve_pending({**_result("boom", origin="task-notification"), "subtype": "error_during_execution", "is_error": True})

    assert agent.notices == []
    silent = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"] == "agent.unsolicited_result"]
    assert [e["data"]["spoken"] for e in silent] == [False, False]


async def test_waiting_for_notices_wakes_up_on_a_relay_and_times_out_quietly(tmp_path):
    agent = _running_agent(tmp_path)
    assert await agent.wait_notices(0, timeout_s=0.01) == []

    waiting = asyncio.create_task(agent.wait_notices(0, timeout_s=TIMEOUT_S))
    await asyncio.sleep(0)
    agent._resolve_pending(_result("Le transcript est prêt.", origin="task-notification"))
    notices = await asyncio.wait_for(waiting, timeout=TIMEOUT_S)

    assert [(n["seq"], n["text"]) for n in notices] == [(1, "Le transcript est prêt.")]
    assert await agent.wait_notices(1, timeout_s=0.01) == []


# ===========================================================================
# Back-end : mesure du travail fait dans le tour
# ===========================================================================


def _assistant_tool(name: str, *, parent: str | None = None) -> dict:
    return {
        "type": "assistant",
        "parent_tool_use_id": parent,
        "message": {"role": "assistant", "content": [{"type": "tool_use", "id": f"toolu-{name}", "name": name, "input": {}}]},
    }


def _over_budget_events(tmp_path: Path) -> list[dict]:
    return [e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"] == "agent.turn_over_budget"]


async def test_a_long_turn_done_inline_is_flagged_in_the_trace(tmp_path):
    agent = _running_agent(tmp_path)
    agent.turn_budget_s = 8.0
    for event in (_assistant_tool("WebSearch"), _assistant_tool("WebFetch"), _assistant_tool("Read", parent="toolu-agent")):
        agent._audit_turn(event)
    agent._audit_turn(_result("Voici les prix.", uuids=["u1"], duration_ms=85_000))

    [flag] = _over_budget_events(tmp_path)
    assert flag["level"] == "warning"
    assert flag["data"]["code"] == "brain_inline_work"
    # L'outil du sous-agent (parent_tool_use_id) n'est pas compté au brain.
    assert flag["data"]["inline_tools"] == {"WebSearch": 1, "WebFetch": 1}
    assert flag["data"]["delegated"] is False


async def test_a_delegating_turn_is_not_blamed_and_a_short_turn_is_not_logged(tmp_path):
    agent = _running_agent(tmp_path)
    agent.turn_budget_s = 8.0
    agent._audit_turn(_assistant_tool("Agent"))
    agent._audit_turn(_result("C'est lancé.", uuids=["u1"], duration_ms=9_500))
    agent._audit_turn(_assistant_tool("Read"))
    agent._audit_turn(_result("Oui.", uuids=["u2"], duration_ms=2_000))

    [flag] = _over_budget_events(tmp_path)
    assert flag["level"] == "info"
    assert flag["data"]["code"] == "brain_turn_slow"
    assert flag["data"]["delegated"] is True and flag["data"]["inline_tools"] == {}


# ===========================================================================
# Back-end : relais jusqu'à la voix
# ===========================================================================


class QueryRequest:
    def __init__(self, **query: str) -> None:
        self.query = query


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


async def test_the_notices_route_never_replays_history_to_a_new_reader(control):
    agent = control.agent
    agent._push_notice(_result("Ancien relais.", origin="task-notification"))

    first = json.loads((await control.agent_notices(QueryRequest(after="0", wait="0"))).text)
    assert first["supported"] is True and first["notices"] == []
    assert first["last_seq"] == 1 and first["epoch"] == agent.notice_epoch

    agent._push_notice(_result("Le sous-agent a fini.", origin="task-notification"))
    fresh = json.loads((await control.agent_notices(QueryRequest(after="1", wait="0", epoch=first["epoch"]))).text)
    assert [n["text"] for n in fresh["notices"]] == ["Le sous-agent a fini."]

    # Agent recréé : le lecteur reçoit ce que la nouvelle file contient déjà.
    changed = json.loads((await control.agent_notices(QueryRequest(after="7", wait="0", epoch="ancienne"))).text)
    assert [n["seq"] for n in changed["notices"]] == [1, 2]


async def test_an_agent_without_relays_says_so(control):
    control._agent_id = "codex"
    payload = json.loads((await control.agent_notices(QueryRequest(after="0"))).text)
    assert payload["supported"] is False and payload["notices"] == []


async def _serve_notices(responses: list[dict], seen: list[dict]) -> tuple[ControlCenterBrainBackend, web.AppRunner]:
    async def handler(request: web.Request) -> web.Response:
        seen.append(dict(request.query))
        return web.json_response(responses.pop(0))

    app = web.Application()
    app.add_routes([web.get("/api/agent/notices", handler)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    return ControlCenterBrainBackend(base_url=f"http://127.0.0.1:{port}", timeout_s=5), runner


async def test_the_brain_backend_follows_the_notice_cursor(tmp_path):
    del tmp_path
    seen: list[dict] = []
    responses = [
        {"ok": True, "supported": True, "notices": [], "epoch": "e1", "last_seq": 4},
        {"ok": True, "supported": True, "epoch": "e1", "last_seq": 6, "notices": [
            {"seq": 5, "text": "Le transcript est prêt."},
            {"seq": 6, "text": BRAIN_NOT_ADDRESSED_ANSWER},
        ]},
        {"ok": True, "supported": True, "notices": [], "epoch": "e1", "last_seq": 6},
    ]
    backend, runner = await _serve_notices(responses, seen)
    try:
        assert await backend.next_notices() == ()
        assert await backend.next_notices() == ("Le transcript est prêt.",)
        assert await backend.next_notices() == ()
    finally:
        await backend.close()
        await runner.cleanup()

    assert seen[0]["epoch"] == "" and seen[0]["after"] == "0"
    assert (seen[1]["epoch"], seen[1]["after"]) == ("e1", "4")
    assert seen[2]["after"] == "6"


async def test_an_unreachable_control_center_does_not_break_the_relay_loop():
    backend = ControlCenterBrainBackend(base_url="http://127.0.0.1:9", timeout_s=1)
    backend.NOTICE_RETRY_S = 0.0
    try:
        assert await backend.next_notices() == ()
    finally:
        await backend.close()


# --- Core ---------------------------------------------------------------------


@dataclass(slots=True)
class RecordingSink:
    events: list[tuple[str, str, dict]] = field(default_factory=list)

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        del message
        self.events.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[dict]:
        return [data for name, _level, data in self.events if name == kind]


@dataclass(slots=True)
class ScriptedBackend:
    """Backend dont chaque tour émet la parole qu'on lui dicte, puis attend `release`."""

    replies: dict[str, str] = field(default_factory=dict)
    release: dict[str, asyncio.Event] = field(default_factory=dict)
    delay_s: float = 0.0

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        del state
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        reply = self.replies.get(turn.text)
        work_id = f"brain-turn:{turn.correlation_id}"
        if reply:
            await emit.emit(
                BrainEvent(
                    kind=BrainEventKind.SPEECH,
                    conversation_id=turn.conversation_id,
                    correlation_id=turn.correlation_id,
                    work_id=work_id,
                    speech=SpeechRequest(conversation_id=turn.conversation_id, text=reply, kind=SpeechKind.RESULT, work_id=work_id),
                )
            )
        gate = self.release.get(turn.text)
        if gate is not None:
            await gate.wait()
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary=reply or "")


async def _orchestrator(tmp_path, backend, **options):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    events = CoreEventBus()
    sink = RecordingSink()
    brain = BrainOrchestrator(conversations=conversations, events=events, backend=backend, diagnostics=sink, **options)
    conversation = await conversations.create()
    return brain, events, state, conversation.id, sink


async def _idle(brain) -> None:
    async def loop() -> None:
        while brain.active_turn_count:
            await asyncio.sleep(0)

    await asyncio.wait_for(loop(), timeout=TIMEOUT_S)


def _drain(queue: asyncio.Queue[ProtocolEnvelope]) -> list[ProtocolEnvelope]:
    collected: list[ProtocolEnvelope] = []
    while not queue.empty():
        collected.append(queue.get_nowait())
    return collected


async def test_a_new_intent_supersedes_the_replies_still_waiting_to_be_said(tmp_path):
    """Retour n° 8 : « C'est à voir » prêt à 15:43:29, lu 30 s plus tard, après
    que l'utilisateur avait déjà relancé."""

    backend = ScriptedBackend(replies={"C'est à voir.": "D'accord, on verra."})
    brain, events, state, conversation_id, sink = await _orchestrator(tmp_path, backend)
    try:
        first = BrainTurnInput(conversation_id=conversation_id, text="C'est à voir.")
        await brain.submit(first)
        await _idle(brain)

        queue = events.subscribe()
        second = BrainTurnInput(conversation_id=conversation_id, text="Attends, je réfléchis.")
        await brain.submit(second)
        [revision] = [e.payload for e in _drain(queue) if e.message_type == BRAIN_INTENT_REVISED]

        stale = f"brain-turn:{first.correlation_id}"
        assert revision["superseded_work_ids"] == [stale]
        assert stale not in revision["retained_work_ids"]
        assert revision["cancelled_work_ids"] == []
        assert sink.of("core.brain.replies_superseded")[0]["work_ids"] == [stale]

        # Déjà traité : la même parole n'est pas périmée deux fois.
        await _idle(brain)
        queue = events.subscribe()
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Bon."))
        [again] = [e.payload for e in _drain(queue) if e.message_type == BRAIN_INTENT_REVISED]
        assert again["superseded_work_ids"] == []
    finally:
        await brain.stop()
        await state.close()


async def test_the_supersession_can_be_switched_off(tmp_path):
    backend = ScriptedBackend(replies={"Question.": "Réponse."})
    brain, events, state, conversation_id, _sink = await _orchestrator(tmp_path, backend, supersede_stale_replies=False)
    try:
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Question."))
        await _idle(brain)
        queue = events.subscribe()
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Autre chose."))
        [revision] = [e.payload for e in _drain(queue) if e.message_type == BRAIN_INTENT_REVISED]
        assert revision["superseded_work_ids"] == []
    finally:
        await brain.stop()
        await state.close()


async def test_an_uncertain_turn_supersedes_only_replies_older_than_itself(tmp_path):
    """Promu quand le cerveau le prend, un tour incertain ne périme que ce qui
    était déjà émis à son arrivée : une réponse émise après lui reste due."""

    gate = asyncio.Event()
    backend = ScriptedBackend(
        replies={"Vieux.": "Vieille réponse.", "En vol.": "Réponse du tour en vol.", "hmm, et le prix ?": "Quatre centimes."},
        release={"En vol.": gate},
    )
    brain, events, state, conversation_id, _sink = await _orchestrator(tmp_path, backend)
    try:
        old = BrainTurnInput(conversation_id=conversation_id, text="Vieux.")
        await brain.submit(old)
        await _idle(brain)
        # Un tour dont la réponse part avant l'arrivée du tour incertain,
        # mais qui reste en vol ensuite.
        in_flight = BrainTurnInput(conversation_id=conversation_id, text="En vol.")
        await brain.submit(in_flight)
        for _ in range(50):
            await asyncio.sleep(0)

        queue = events.subscribe()
        uncertain = BrainTurnInput(conversation_id=conversation_id, text="hmm, et le prix ?", addressing=AddressingDecision.UNCERTAIN)
        await brain.submit(uncertain)
        gate.set()
        await _idle(brain)

        revisions = [e.payload for e in _drain(queue) if e.message_type == BRAIN_INTENT_REVISED]
        superseded = {work for payload in revisions for work in payload["superseded_work_ids"]}
        assert f"brain-turn:{in_flight.correlation_id}" in superseded
        assert f"brain-turn:{uncertain.correlation_id}" not in superseded
    finally:
        await brain.stop()
        await state.close()


async def test_a_relay_is_spoken_in_the_last_conversation_and_becomes_a_public_fact(tmp_path):
    backend = ScriptedBackend()
    brain, events, state, conversation_id, sink = await _orchestrator(tmp_path, backend)
    try:
        # Sans conversation, rien ne peut être dit : c'est visible, pas silencieux.
        assert await brain.announce_notice("Trop tôt.") is False
        assert sink.of("core.brain.notice_dropped")[0]["reason"] == "no_conversation"

        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Lance la recherche."))
        await _idle(brain)
        queue = events.subscribe()

        assert await brain.announce_notice(BRAIN_NOT_ADDRESSED_ANSWER) is False
        assert await brain.announce_notice("Le sous-agent a fini : le silence est facturé.") is True

        [speech] = [e for e in _drain(queue) if e.message_type == BRAIN_SPEECH_REQUESTED]
        assert speech.conversation_id == conversation_id
        assert speech.payload["text"] == "Le sous-agent a fini : le silence est facturé."
        assert speech.payload["kind"] == SpeechKind.RESULT.value
        assert speech.correlation_id.startswith("brain-notice:")
        assert "Le sous-agent a fini : le silence est facturé." in brain.working_state(conversation_id).known_public_facts
    finally:
        await brain.stop()
        await state.close()


async def test_a_turn_over_budget_is_measured_while_it_makes_the_conversation_wait(tmp_path):
    backend = ScriptedBackend(delay_s=0.15)
    brain, _events, state, conversation_id, sink = await _orchestrator(tmp_path, backend, turn_budget_s=0.05)
    try:
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Compare les prix."))
        await _idle(brain)

        assert len(sink.of("core.brain.turn_slow")) == 1
        [over] = sink.of("core.brain.turn_over_budget")
        assert over["duration_ms"] >= 100 and over["budget_ms"] == 50
    finally:
        await brain.stop()
        await state.close()


async def test_a_quick_turn_leaves_no_budget_trace(tmp_path):
    brain, _events, state, conversation_id, sink = await _orchestrator(tmp_path, ScriptedBackend())
    try:
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Salut."))
        await _idle(brain)
        assert sink.of("core.brain.turn_slow") == [] and sink.of("core.brain.turn_over_budget") == []
    finally:
        await brain.stop()
        await state.close()


class BusCore:
    """Core vu de l'ordonnanceur vocal, branché sur le vrai bus de l'orchestrateur."""

    def __init__(self, bus: CoreEventBus, brain: BrainOrchestrator) -> None:
        self.bus = bus
        self.brain = brain
        self.subscribed = asyncio.Event()

    async def events(self, *, on_connected=None):
        queue = self.bus.subscribe()
        if on_connected is not None:
            on_connected()
        self.subscribed.set()
        try:
            while True:
                yield await queue.get()
        finally:
            self.bus.unsubscribe(queue)

    async def speech_context(self, conversation_id):
        return await self.brain.speech_context(conversation_id)

    async def append_turn(self, conversation_id, *, kind, content, correlation_id=None, metadata=None):  # noqa: ANN001
        del conversation_id, kind, content, correlation_id, metadata
        return {"id": "turn"}


class PlayingSession:
    """Surface vocale : une sortie joue tant que le test ne la termine pas."""

    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.requests: dict[str, SpeechRequest] = {}
        self.admission = None
        self.invalidated: list[str] = []
        self.active_output_id: str | None = None
        self.cancelled = 0

    async def speak_reserved(self, request: SpeechRequest, *, output_id: str) -> str:
        self.requests[output_id] = request
        self.active_output_id = output_id
        return self.active_output_id

    def begin_write(self, output_id: str) -> bool:
        token = self.admission(output_id)
        assert token is not None  # Actual scheduler08 reservation, not a fixture flag.
        if not token.begin_write():
            return False
        self.spoken.append(self.requests[output_id].text)
        return True

    async def invalidate_unstarted_output(self, output_id: str) -> None:
        self.invalidated.append(output_id)
        if self.active_output_id == output_id:
            self.active_output_id = None

    async def cancel_output(self, cursor=None) -> None:  # noqa: ANN001
        del cursor
        self.cancelled += 1

    async def truncate(self, cursor) -> None:  # noqa: ANN001
        del cursor


async def _until(predicate) -> None:
    for _ in range(1000):
        if predicate():
            return
        await asyncio.sleep(0.002)
    raise AssertionError("condition jamais atteinte")


@pytest.mark.parametrize("write_started", [False, True], ids=["zero-write", "write-started"])
async def test_a_superseded_reply_leaves_the_queue_but_never_cuts_what_is_playing(tmp_path, write_started):
    """Bout à bout, orchestrateur → ordonnanceur vocal : la réponse en cours de
    lecture va au bout, celle qui attendait derrière n'est jamais dite."""

    from jarvis.runtime.speech_scheduler import SpeechScheduler
    from jarvis.runtime.output_admission import OutputAdmissionState

    backend = ScriptedBackend(replies={"Un.": "Réponse une, en cours de lecture.", "Deux.": "Réponse deux, en attente."})
    brain, events, state, conversation_id, _sink = await _orchestrator(tmp_path, backend)
    session, journal, core = PlayingSession(), RecordingSink(), BusCore(events, brain)
    scheduler = SpeechScheduler(core=core, conversation_id=conversation_id, session=session, journal=journal, reconnect_delay_s=0.0, output_timeout_s=5.0)
    session.admission = scheduler.output_admission
    await scheduler.start()
    try:
        await asyncio.wait_for(core.subscribed.wait(), timeout=TIMEOUT_S)
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Un."))
        await _until(lambda: len(session.requests) == 1)
        output_id = session.active_output_id
        token = scheduler.output_admission(output_id)
        assert token.state is OutputAdmissionState.RESERVED
        if write_started:
            assert session.begin_write(output_id)
            assert token.state is OutputAdmissionState.WRITE_STARTED

        # L'utilisateur relance pendant la lecture : la réponse deux arrive et attend.
        second_turn = BrainTurnInput(conversation_id=conversation_id, text="Deux.")
        await brain.submit(second_turn)
        await _until(lambda: scheduler.pending_count == 1)
        [second_queued] = [data for data in journal.of("voice.speech.queued")
                           if data["correlation_id"] == second_turn.correlation_id]
        second_speech_id = second_queued["speech_id"]
        # Il relance encore avant qu'elle soit dite.
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Trois."))
        await _until(lambda: scheduler.pending_count == 0)

        assert session.cancelled == 0
        if write_started:
            assert session.invalidated == [] and session.active_output_id == output_id
            assert token.state is OutputAdmissionState.WRITE_STARTED
            token.finish_write(succeeded=True)
        else:
            await _until(lambda: session.invalidated == [output_id])
            assert token.state is OutputAdmissionState.INVALIDATED
            assert not session.begin_write(output_id) and session.spoken == []
        await scheduler.note_output_event(ProtocolEnvelope(message_type="realtime.response_done", payload={"output_id": output_id, "status": "completed"}))
        await asyncio.sleep(0.05)

        assert session.spoken == (["Réponse une, en cours de lecture."] if write_started else [])
        assert len(session.requests) == 1  # The queued second answer never gets an output reservation.
        dropped = [data for kind, _level, data in journal.events if kind == "voice.speech.superseded"]
        [second_dropped] = [data for data in dropped if data["speech_id"] == second_speech_id]
        assert (second_dropped["correlation_id"], second_dropped["work_id"], second_dropped["reason"]) == (
            second_turn.correlation_id, f"brain-turn:{second_turn.correlation_id}", "dependency_revoked")
        # The first candidate may also acquire a stale dependency diagnosis;
        # this is separate from cancelling its already-started native write.
        other_dropped = [data for data in dropped if data["speech_id"] != second_speech_id]
        assert all(data["speech_id"] == session.requests[output_id].id for data in other_dropped)
    finally:
        await scheduler.stop()
        await brain.stop()
        await state.close()


class NoticeBackend(ScriptedBackend):
    """Backend Control Center simulé : un relais, puis plus rien."""

    def __init__(self) -> None:
        super().__init__()
        self.queue: asyncio.Queue[tuple[str, ...]] = asyncio.Queue()

    async def next_notices(self) -> tuple[str, ...]:
        return await self.queue.get()


async def test_core_speaks_the_relay_as_soon_as_the_backend_hands_it_over(tmp_path):
    backend = NoticeBackend()
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend)
    await core.start()
    try:
        conversation = await core.conversations.create()
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, text="Fais le transcript."))
        await _idle(core.brain)
        queue = core.events.subscribe()

        await backend.queue.put(("Le transcript est prêt dans le dossier transcripts.",))
        speech = None
        while speech is None:
            envelope = await asyncio.wait_for(queue.get(), timeout=TIMEOUT_S)
            if envelope.message_type == BRAIN_SPEECH_REQUESTED:
                speech = envelope
        assert speech.payload["text"] == "Le transcript est prêt dans le dossier transcripts."
        assert speech.conversation_id == conversation.id
    finally:
        await core.stop()
