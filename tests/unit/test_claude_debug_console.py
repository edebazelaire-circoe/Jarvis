"""La véritable console Claude, ouverte dans une fenêtre Windows.

Le transcript du panneau reste une représentation. La console, elle, est le
vrai `claude` interactif relancé sur la même conversation via `--resume`, dans
sa propre fenêtre. Une session Claude ne pouvant pas être écrite par deux
processus à la fois, l'agent piloté par pipes rend la main : c'est assumé, la
console est un mode de debug.

Aucun test n'ouvre de fenêtre : le lanceur est remplacé.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.runtime import claude_local
from jarvis.runtime.claude_local import CREATE_NEW_CONSOLE, ClaudeLocalAgent
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.journal import read_jsonl_tail


class FakeConsoleProcess:
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.alive = True
        self.terminated = False

    def poll(self):
        return None if self.alive else 0

    def terminate(self) -> None:
        self.terminated = True
        self.alive = False

    def wait(self) -> int:
        return 0

    def kill(self) -> None:
        self.alive = False


@pytest.fixture
def spawner(monkeypatch):
    """Remplace Popen : les tests ne doivent jamais ouvrir de vraie fenêtre."""
    calls: list[dict] = []

    def fake_popen(command, **kwargs):  # noqa: ANN001
        calls.append({"command": list(command), **kwargs})
        return FakeConsoleProcess()

    monkeypatch.setattr(claude_local.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(claude_local.os, "name", "nt")
    monkeypatch.setattr(claude_local, "raise_console_window", lambda pid: True)
    return calls


def _agent(tmp_path: Path) -> ClaudeLocalAgent:
    return ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")


async def test_console_resumes_the_current_conversation_in_its_own_window(tmp_path, spawner):
    agent = _agent(tmp_path)
    agent._record({"type": "system", "subtype": "init", "session_id": "4a890ce3-230c"})

    result = await agent.open_console()

    # La console hérite du même mode d'autorisation que l'agent piloté : les
    # deux vues doivent se comporter pareil sur la même conversation.
    assert spawner[0]["command"] == ["claude", "--permission-mode", "bypassPermissions", "--resume", "4a890ce3-230c"]
    # Sans ce drapeau le processus n'aurait aucune fenêtre : c'est lui qui fait
    # la différence entre « vraie console » et agent headless.
    assert spawner[0]["creationflags"] == CREATE_NEW_CONSOLE
    assert spawner[0]["cwd"] == str(tmp_path)
    assert result["open"] is True
    assert result["already_open"] is False

    entry = read_jsonl_tail(tmp_path / "trace.jsonl")[-1]
    assert entry["kind"] == "agent.console_open"
    assert entry["data"]["session_id"] == "4a890ce3-230c"
    assert "conversation reprise" in entry["message"]


async def test_console_starts_a_fresh_conversation_when_none_exists(tmp_path, spawner):
    agent = _agent(tmp_path)

    await agent.open_console()

    assert spawner[0]["command"] == ["claude", "--permission-mode", "bypassPermissions"]
    assert "nouvelle conversation" in read_jsonl_tail(tmp_path / "trace.jsonl")[-1]["message"]


async def test_session_id_is_captured_from_any_event(tmp_path):
    agent = _agent(tmp_path)
    agent._record({"type": "assistant", "session_id": "abc-123", "message": {"role": "assistant", "content": []}})

    assert agent.session_id == "abc-123"
    assert agent.snapshot()["session_id"] == "abc-123"


async def test_reopening_raises_the_existing_window_instead_of_spawning_a_second(tmp_path, spawner):
    agent = _agent(tmp_path)
    await agent.open_console()

    result = await agent.open_console()

    assert len(spawner) == 1
    assert result["already_open"] is True
    assert result["raised"] is True
    assert read_jsonl_tail(tmp_path / "trace.jsonl")[-1]["kind"] == "agent.console_focus"


async def test_piped_agent_cannot_be_restarted_while_the_console_holds_the_session(tmp_path, spawner):
    agent = _agent(tmp_path)
    await agent.open_console()

    with pytest.raises(RuntimeError, match="Fermez-la avant"):
        await agent.start()

    assert len(spawner) == 1


async def test_closing_the_console_hands_the_session_back(tmp_path, spawner):
    agent = _agent(tmp_path)
    await agent.open_console()

    state = await agent.close_console()

    assert state["open"] is False
    assert read_jsonl_tail(tmp_path / "trace.jsonl")[-1]["kind"] == "agent.console_close"


async def test_closing_a_console_that_is_not_open_is_harmless(tmp_path, spawner):
    agent = _agent(tmp_path)

    assert (await agent.close_console())["open"] is False


async def test_console_reports_a_spawn_failure_instead_of_failing_silently(tmp_path, monkeypatch):
    agent = _agent(tmp_path)
    monkeypatch.setattr(claude_local.os, "name", "nt")
    monkeypatch.setattr(claude_local.subprocess, "Popen", _raise_oserror)

    with pytest.raises(RuntimeError, match="Impossible d'ouvrir la console Claude"):
        await agent.open_console()

    errors = read_jsonl_tail(tmp_path / "errors.jsonl")
    assert errors[-1]["data"]["code"] == "claude_console_spawn_failed"


@pytest.mark.asyncio
async def test_control_center_exposes_open_and_close(tmp_path, spawner):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    control.agent._record({"type": "system", "session_id": "sid-1"})

    opened = json.loads((await control.agent_console_open(None)).text)
    status = json.loads((await control.agent_status(None)).text)
    closed = json.loads((await control.agent_console_close(None)).text)

    assert opened["open"] is True and opened["session_id"] == "sid-1"
    assert status["console"]["open"] is True
    assert closed["open"] is False


@pytest.mark.asyncio
async def test_control_center_surfaces_a_console_failure_as_503(tmp_path, monkeypatch):
    from aiohttp import web

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    monkeypatch.setattr(claude_local.os, "name", "nt")
    monkeypatch.setattr(claude_local.subprocess, "Popen", _raise_oserror)

    with pytest.raises(web.HTTPServiceUnavailable):
        await control.agent_console_open(None)


def test_console_is_refused_outside_windows(tmp_path, monkeypatch):
    agent = _agent(tmp_path)
    monkeypatch.setattr(claude_local.os, "name", "posix")

    assert agent.console_snapshot()["supported"] is False


def _raise_oserror(command, **kwargs):  # noqa: ANN001
    raise OSError("The system cannot find the file specified")
