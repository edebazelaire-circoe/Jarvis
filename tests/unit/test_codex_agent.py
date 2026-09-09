"""L'agent Codex, second pilote possible de la boucle vocale.

Codex n'a pas de processus permanent : un tour = un `codex exec`. Ce qui doit
tenir, c'est que la passerelle vocale (`ask`) rende toujours une phrase et un
verdict, que le fil de conversation soit repris d'un tour à l'autre, et qu'une
panne du CLI ne se transforme pas en attente silencieuse.

Le format d'événements utilisé ici est celui réellement émis par
`codex exec --json`, relevé sur la machine : thread.started, turn.started,
item.completed, turn.completed.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.runtime import cli_catalog
from jarvis.runtime.codex_local import CodexLocalAgent
from jarvis.runtime.journal import read_jsonl_tail


class FakeStream:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""


class SlowStream:
    """Un flux qui ne rend jamais la main : le CLI est parti sans revenir."""

    async def readline(self) -> bytes:
        await asyncio.Event().wait()
        return b""


class FakeStdin:
    def __init__(self) -> None:
        self.written = b""
        self.closed = False

    def write(self, chunk: bytes) -> None:
        self.written += chunk

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, stdout, *, stderr=None, returncode: int = 0) -> None:  # noqa: ANN001
        self.stdin = FakeStdin()
        self.stdout = stdout
        self.stderr = stderr or FakeStream([])
        self.returncode: int | None = None
        self._final = returncode
        self.pid = 4321
        self.killed = False

    async def wait(self) -> int:
        self.returncode = self._final
        return self._final

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def terminate(self) -> None:
        self.returncode = self._final


def jsonl(*events: dict) -> list[bytes]:
    return [json.dumps(event).encode("utf-8") + b"\n" for event in events]


TURN = (
    {"type": "thread.started", "thread_id": "01a0815f-ec8b-7430-9af7-16ad8e881135"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "C'est fait."}},
    {"type": "turn.completed", "usage": {"input_tokens": 16156, "output_tokens": 6}},
)


@pytest.fixture
def agent(tmp_path, monkeypatch):
    async def always_available(command):  # noqa: ANN001
        return {"available": True, "path": "C:/fake/codex.exe", "version": "codex-cli 1.0", "error": ""}

    monkeypatch.setattr(cli_catalog, "probe", always_available)
    return CodexLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="codex")


def spawn(monkeypatch, *processes: FakeProcess) -> list[list[str]]:
    """Remplacer le lancement de processus et garder les lignes de commande."""
    calls: list[list[str]] = []
    queue = list(processes)

    async def fake_exec(*argv, **kwargs):  # noqa: ANN001, ANN002
        calls.append(list(argv))
        return queue.pop(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


async def test_a_turn_returns_the_agent_message_and_a_verdict(agent, monkeypatch):
    calls = spawn(monkeypatch, FakeProcess(FakeStream(jsonl(*TURN))))

    result = await agent.ask("range le bureau", timeout_s=5)

    assert result["ok"] is True
    assert result["text"] == "C'est fait."
    assert result["session_id"] == "01a0815f-ec8b-7430-9af7-16ad8e881135"
    assert result["duration_ms"] >= 0
    # La question part sur stdin : une phrase dictée peut contenir des
    # guillemets ou des sauts de ligne qu'une ligne de commande abîmerait.
    assert calls[0][-1] == "-"


async def test_the_second_question_resumes_the_same_thread(agent, monkeypatch):
    calls = spawn(
        monkeypatch,
        FakeProcess(FakeStream(jsonl(*TURN))),
        FakeProcess(FakeStream(jsonl({"type": "turn.completed", "usage": {}}))),
    )

    await agent.ask("première", timeout_s=5)
    await agent.ask("seconde", timeout_s=5)

    assert "resume" not in calls[0]
    assert calls[1][1:4] == ["exec", "resume", "01a0815f-ec8b-7430-9af7-16ad8e881135"]
    # `codex exec resume` refuse `-C` : le répertoire de travail vient du
    # processus, pas de la ligne de commande.
    assert "-C" not in calls[1]


async def test_the_sandbox_mode_and_the_model_reach_the_command_line(agent, monkeypatch):
    agent.model = "gpt-5-codex"
    agent.permission_mode = "read-only"
    calls = spawn(monkeypatch, FakeProcess(FakeStream(jsonl(*TURN))))

    await agent.ask("regarde", timeout_s=5)

    assert calls[0][calls[0].index("-m") + 1] == "gpt-5-codex"
    # `-s` n'existe que sur `codex exec`, pas sur `codex exec resume` : seul
    # l'override de configuration fonctionne des deux côtés.
    assert calls[0][calls[0].index("-c") + 1] == "sandbox_mode=read-only"
    assert "-s" not in calls[0]
    assert "--dangerously-bypass-approvals-and-sandbox" not in calls[0]


async def test_full_access_uses_the_flag_that_also_skips_approvals(agent, monkeypatch):
    """En vocal personne ne peut répondre à une demande d'approbation.

    `-s danger-full-access` lève le bac à sable mais laisse les confirmations :
    le tour resterait bloqué sur une question que personne n'entend.
    """
    agent.permission_mode = "danger-full-access"
    calls = spawn(monkeypatch, FakeProcess(FakeStream(jsonl(*TURN))))

    await agent.ask("agis", timeout_s=5)

    assert "--dangerously-bypass-approvals-and-sandbox" in calls[0]
    assert "-s" not in calls[0] and "-c" not in calls[0]


async def test_a_failed_turn_comes_back_as_a_verdict_not_as_an_exception(agent, monkeypatch):
    spawn(
        monkeypatch,
        FakeProcess(
            FakeStream(jsonl(
                {"type": "thread.started", "thread_id": "fil"},
                {"type": "turn.failed", "error": {"message": "quota dépassé"}},
            )),
            returncode=1,
        ),
    )

    result = await agent.ask("agis", timeout_s=5)

    assert result["ok"] is False
    assert result["error"] == "quota dépassé"
    assert result["code"] == "codex_turn_failed"


async def test_a_cli_that_never_answers_is_killed_and_reported(agent, monkeypatch, tmp_path):
    process = FakeProcess(SlowStream())
    spawn(monkeypatch, process)

    result = await agent.ask("agis", timeout_s=0.05)

    assert result["ok"] is False
    assert result["code"] == "codex_timeout"
    assert process.killed is True
    errors = read_jsonl_tail(agent.journal.error_path)
    assert errors[-1]["data"]["code"] == "codex_timeout"


async def test_an_uninstalled_cli_is_refused_at_start(tmp_path, monkeypatch):
    async def missing(command):  # noqa: ANN001
        return {"available": False, "path": "", "version": "", "error": "« codex » est introuvable dans le PATH."}

    monkeypatch.setattr(cli_catalog, "probe", missing)
    agent = CodexLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="codex")

    with pytest.raises(RuntimeError, match="introuvable"):
        await agent.start()
    assert agent.state == "stopped"


async def test_stderr_is_journalled_without_polluting_the_answer(agent, monkeypatch):
    spawn(
        monkeypatch,
        FakeProcess(
            FakeStream(jsonl(*TURN)),
            stderr=FakeStream([b"ERROR codex_skills_extension: failed to install\n"]),
        ),
    )

    result = await agent.ask("agis", timeout_s=5)

    assert result["text"] == "C'est fait."
    errors = read_jsonl_tail(agent.journal.error_path)
    assert any("codex_skills_extension" in item["message"] for item in errors)


def test_the_transcript_turns_raw_events_into_readable_entries(agent):
    for event in TURN:
        agent._record(event)
    agent._record({"type": "item.completed", "item": {"type": "command_execution", "command": "ls", "exit_code": 1}})

    entries = agent.transcript()
    by_title = {entry["title"]: entry for entry in entries}

    assert by_title["Codex"]["text"] == "C'est fait."
    assert by_title["Codex"]["role"] == "assistant"
    assert by_title["Fil Codex"]["text"] == "01a0815f-ec8b-7430-9af7-16ad8e881135"
    assert by_title["Commande"]["status"] == "bad"


def test_the_snapshot_names_the_agent_so_the_interface_can_say_which_one(agent):
    snapshot = agent.snapshot()
    assert snapshot["name"] == "Codex"
    assert snapshot["state"] == "stopped"
    assert snapshot["console"]["supported"] in {True, False}


async def test_restarting_opens_a_new_thread(agent, monkeypatch):
    spawn(monkeypatch, FakeProcess(FakeStream(jsonl(*TURN))))
    await agent.ask("première", timeout_s=5)
    assert agent.session_id

    await agent.restart()

    assert agent.session_id is None
    assert agent.transcript() == []
