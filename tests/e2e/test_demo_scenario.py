from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
from jarvis.core.actions import ActionBroker
from jarvis.core.executors import build_action_executors
from jarvis.core.orchestrator import JarvisOrchestrator
from jarvis.core.session import SessionStateMachine
from jarvis.core.tools import ToolRegistry
from jarvis.domain.messages import ToolCall

from conftest import RecordingBoard, RecordingStatePublisher, RecordingTTS, ScriptedAgent


def make_orchestrator(memory, board, agent, tts):
    state = SessionStateMachine(RecordingStatePublisher())
    tools = ToolRegistry()
    broker = ActionBroker(build_action_executors(memory, board), confirmation_timeout_s=30)
    return JarvisOrchestrator(
        agent=agent,
        tts=tts,
        state=state,
        tools=tools,
        broker=broker,
    )


@pytest.mark.asyncio
async def test_required_v1_demo_flow_survives_restart(tmp_path, agent_result_factory):
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    (memory_root / "Jarvis-V1.md").write_text(
        "# Jarvis V1\n\nProjet local, modulaire, push-to-talk et sécurisé.\n",
        encoding="utf-8",
    )
    memory = MarkdownMemoryBackend(memory_root)
    await memory.rebuild_index()
    board = RecordingBoard()
    tts = RecordingTTS()

    agent = ScriptedAgent(
        # 1) Question about the project -> memory search -> spoken answer.
        agent_result_factory(
            tool_calls=(ToolCall("s1", "memory_search", {"query": "projet Jarvis"}),),
            continuation_token="q1",
        ),
        agent_result_factory(text="Ton projet Jarvis est local, modulaire et sécurisé."),
        # 2) Show summary -> board -> acknowledgement.
        agent_result_factory(
            tool_calls=(ToolCall("b1", "board_present", {"title": "Jarvis V1", "body": "Local · modulaire · sécurisé"}),),
            continuation_token="q2",
        ),
        agent_result_factory(text="Le résumé est affiché sur le board."),
        # 3) Remember demo -> confirmation -> persisted acknowledgement.
        agent_result_factory(
            tool_calls=(ToolCall("m1", "memory_append", {"title": "Démo V1", "body": "La démo V1 a fonctionné."}),),
            continuation_token="q3",
        ),
        agent_result_factory(text="C'est mémorisé."),
    )
    jarvis = make_orchestrator(memory, board, agent, tts)
    await jarvis.state.initialize()

    first = await jarvis.handle_text("Quel est mon projet Jarvis ?")
    assert "local" in first.text
    shown = await jarvis.handle_text("Affiche un résumé sur le board")
    assert "affiché" in shown.text
    assert board.calls and board.calls[-1]["title"] == "Jarvis V1"
    pending = await jarvis.handle_text("Mémorise que la démo V1 a fonctionné")
    assert pending.awaiting_confirmation is True
    approved = await jarvis.handle_text("oui")
    assert approved.text == "C'est mémorisé."

    # 4) Simulated process restart: derived index is reopened from durable Markdown.
    restarted_memory = MarkdownMemoryBackend(memory_root)
    post_restart_agent = ScriptedAgent(
        agent_result_factory(
            tool_calls=(ToolCall("s2", "memory_search", {"query": "démo V1 fonctionné"}),),
            continuation_token="q4",
        ),
        agent_result_factory(text="Tu m'as demandé de retenir que la démo V1 a fonctionné."),
    )
    restarted = make_orchestrator(restarted_memory, RecordingBoard(), post_restart_agent, RecordingTTS())
    await restarted.state.initialize()
    remembered = await restarted.handle_text("Qu'est-ce que tu as mémorisé sur la démo ?")
    assert "fonctionné" in remembered.text
    assert post_restart_agent.turns[1].tool_outputs[0].output["output"]["hits"]
