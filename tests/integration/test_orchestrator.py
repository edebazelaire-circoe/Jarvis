from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
from jarvis.core.actions import ActionBroker
from jarvis.core.executors import build_action_executors
from jarvis.core.orchestrator import JarvisOrchestrator
from jarvis.core.session import SessionStateMachine
from jarvis.core.tools import ToolRegistry
from jarvis.domain.events import JarvisState
from jarvis.domain.messages import ToolCall

from conftest import RecordingBoard, RecordingStatePublisher, RecordingTTS, ScriptedAgent


def _orchestrator(tmp_path: Path, agent, *, board=None, tts=None):
    memory = MarkdownMemoryBackend(tmp_path / "memory")
    board = board or RecordingBoard()
    tts = tts or RecordingTTS()
    publisher = RecordingStatePublisher()
    state = SessionStateMachine(publisher)
    tools = ToolRegistry()
    broker = ActionBroker(build_action_executors(memory, board), confirmation_timeout_s=30)
    orchestrator = JarvisOrchestrator(
        agent=agent,
        tts=tts,
        state=state,
        tools=tools,
        broker=broker,
    )
    return orchestrator, memory, board, tts, publisher


@pytest.mark.asyncio
async def test_board_present_executes_without_confirmation_and_voice_continues(tmp_path, agent_result_factory):
    agent = ScriptedAgent(
        agent_result_factory(
            tool_calls=(ToolCall("call-1", "board_present", {"title": "Résumé", "body": "Trois points"}),),
            continuation_token="local-cont",
        ),
        agent_result_factory(text="Le résumé est affiché."),
    )
    orchestrator, _, board, tts, _ = _orchestrator(tmp_path, agent)
    await orchestrator.state.initialize()
    outcome = await orchestrator.handle_text("Affiche un résumé sur le board")
    assert not outcome.awaiting_confirmation
    assert outcome.text == "Le résumé est affiché."
    assert board.calls[0]["title"] == "Résumé"
    assert len(agent.turns) == 2
    assert agent.turns[1].tool_outputs[0].is_error is False
    assert tts.texts == ["Le résumé est affiché."]
    assert orchestrator.state.state == JarvisState.IDLE


@pytest.mark.asyncio
async def test_memory_write_requires_confirmation_then_persists(tmp_path, agent_result_factory):
    agent = ScriptedAgent(
        agent_result_factory(
            tool_calls=(ToolCall("call-m", "memory_append", {"title": "Démo V1", "body": "La démo a fonctionné"}),),
            continuation_token="continue-memory",
        ),
        agent_result_factory(text="C'est mémorisé."),
    )
    orchestrator, memory, _, tts, _ = _orchestrator(tmp_path, agent)
    await orchestrator.state.initialize()
    pending = await orchestrator.handle_text("Mémorise que la démo V1 a fonctionné")
    assert pending.awaiting_confirmation
    assert pending.action_id
    assert await memory.search("fonctionné") == []
    assert orchestrator.state.state == JarvisState.AWAITING_CONFIRMATION

    ambiguous = await orchestrator.handle_text("je pense que oui peut-être")
    assert ambiguous.awaiting_confirmation
    assert await memory.search("fonctionné") == []

    approved = await orchestrator.handle_text("oui")
    assert not approved.awaiting_confirmation
    hits = await memory.search("fonctionné")
    assert hits and hits[0].title == "Démo V1"
    assert approved.text == "C'est mémorisé."
    assert tts.texts[0].startswith("Confirmation requise")
    assert "Confirmation ambigue" in tts.texts[1]
    assert tts.texts[-1] == "C'est mémorisé."


@pytest.mark.asyncio
async def test_memory_write_denial_never_persists(tmp_path, agent_result_factory):
    agent = ScriptedAgent(
        agent_result_factory(
            tool_calls=(ToolCall("call-m", "memory_append", {"title": "Secret", "body": "Ne pas écrire"}),),
            continuation_token="continue-memory",
        ),
        agent_result_factory(text="D'accord, je n'ai rien enregistré."),
    )
    orchestrator, memory, _, _, _ = _orchestrator(tmp_path, agent)
    await orchestrator.state.initialize()
    await orchestrator.handle_text("Mémorise ceci")
    outcome = await orchestrator.handle_text("non")
    assert "rien enregistré" in outcome.text
    assert await memory.search("écrire") == []
    assert agent.turns[-1].tool_outputs[-1].is_error is True


@pytest.mark.asyncio
async def test_unknown_tool_is_denied_before_execution(tmp_path, agent_result_factory):
    agent = ScriptedAgent(
        agent_result_factory(
            tool_calls=(ToolCall("bad", "shell", {"command": "rm -rf /"}),),
            continuation_token="continue-bad",
        ),
        agent_result_factory(text="Cette action n'est pas autorisée."),
    )
    orchestrator, _, board, _, _ = _orchestrator(tmp_path, agent)
    await orchestrator.state.initialize()
    result = await orchestrator.handle_text("fais-le")
    assert result.text == "Cette action n'est pas autorisée."
    assert board.calls == []
    assert agent.turns[1].tool_outputs[0].is_error is True


@pytest.mark.asyncio
async def test_board_failure_is_tool_failure_not_voice_loop_crash(tmp_path, agent_result_factory):
    board = RecordingBoard(fail=True)
    agent = ScriptedAgent(
        agent_result_factory(
            tool_calls=(ToolCall("board", "board_present", {"title": "X", "body": "Y"}),),
            continuation_token="continue-board",
        ),
        agent_result_factory(text="Le board est indisponible, mais je reste utilisable."),
    )
    orchestrator, _, _, _, _ = _orchestrator(tmp_path, agent, board=board)
    await orchestrator.state.initialize()
    outcome = await orchestrator.handle_text("affiche")
    assert "reste utilisable" in outcome.text
    assert orchestrator.state.state == JarvisState.IDLE
    assert agent.turns[1].tool_outputs[0].is_error is True


class BlockingTTS:
    def __init__(self):
        self.started = asyncio.Event()
        self.cancel_observed = asyncio.Event()

    async def speak(self, text, *, interrupt):
        from jarvis.domain.results import SpeechResult

        self.started.set()
        for _ in range(200):
            if interrupt.cancelled:
                self.cancel_observed.set()
                return SpeechResult(1, True, "fake", "fake")
            await asyncio.sleep(0.001)
        return SpeechResult(200, False, "fake", "fake")


@pytest.mark.asyncio
async def test_push_to_talk_interrupts_speech_without_state_race(tmp_path, agent_result_factory):
    tts = BlockingTTS()
    agent = ScriptedAgent(agent_result_factory(text="Une réponse assez longue."))
    orchestrator, _, _, _, _ = _orchestrator(tmp_path, agent, tts=tts)
    await orchestrator.state.initialize()
    turn_task = asyncio.create_task(orchestrator.handle_text("parle"))
    await tts.started.wait()
    accepted = await orchestrator.begin_listening(turn_id="interrupt")
    assert accepted is True
    await asyncio.wait_for(tts.cancel_observed.wait(), timeout=1)
    await turn_task
    assert orchestrator.state.state == JarvisState.LISTENING

class FailingAgent:
    async def respond(self, turn, tools):
        from jarvis.domain.errors import ProviderError
        raise ProviderError("openai", "agent", "network down", retryable=True)


class FailingTTS:
    async def speak(self, text, *, interrupt):
        raise ConnectionError("tts down too")


@pytest.mark.asyncio
async def test_provider_failure_is_announced_and_session_recovers(tmp_path):
    tts = RecordingTTS()
    orchestrator, _, _, _, publisher = _orchestrator(tmp_path, FailingAgent(), tts=tts)
    await orchestrator.state.initialize()
    outcome = await orchestrator.handle_text("question")
    assert "service d'IA" in outcome.text
    assert outcome.diagnostics["error_class"] == "ProviderError"
    assert tts.texts == [outcome.text]
    assert any(event.state == JarvisState.ERROR for event in publisher.events)
    assert orchestrator.state.state == JarvisState.IDLE


@pytest.mark.asyncio
async def test_provider_and_tts_failure_still_returns_to_idle(tmp_path):
    orchestrator, _, _, _, _ = _orchestrator(tmp_path, FailingAgent(), tts=FailingTTS())
    await orchestrator.state.initialize()
    outcome = await orchestrator.handle_text("question")
    assert "service d'IA" in outcome.text
    assert outcome.diagnostics["error_class"] == "ProviderError"
    assert orchestrator.state.state == JarvisState.IDLE

class TwoPhaseTTS:
    def __init__(self):
        self.calls = 0
        self.first_started = asyncio.Event()
        self.first_cancelled = asyncio.Event()

    async def speak(self, text, *, interrupt):
        from jarvis.domain.results import SpeechResult
        self.calls += 1
        if self.calls == 1:
            self.first_started.set()
            for _ in range(200):
                if interrupt.cancelled:
                    self.first_cancelled.set()
                    return SpeechResult(1, True, "fake", "fake")
                await asyncio.sleep(0.001)
        return SpeechResult(1, False, "fake", "fake")


@pytest.mark.asyncio
async def test_repeated_interrupt_then_next_reply_stays_synchronized(tmp_path, agent_result_factory):
    tts = TwoPhaseTTS()
    agent = ScriptedAgent(
        agent_result_factory(text="Première réponse longue."),
        agent_result_factory(text="Deuxième réponse."),
    )
    orchestrator, _, _, _, _ = _orchestrator(tmp_path, agent, tts=tts)
    await orchestrator.state.initialize()
    first = asyncio.create_task(orchestrator.handle_text("première"))
    await tts.first_started.wait()
    await orchestrator.begin_listening(turn_id="interrupt")
    await asyncio.wait_for(tts.first_cancelled.wait(), 1)
    await first
    assert orchestrator.state.state == JarvisState.LISTENING
    await orchestrator.begin_transcribing(turn_id="second")
    second = await orchestrator.handle_text("deuxième", turn_id="second")
    assert second.text == "Deuxième réponse."
    assert orchestrator.state.state == JarvisState.IDLE
    assert tts.calls == 2
