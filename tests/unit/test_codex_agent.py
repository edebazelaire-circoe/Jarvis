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


async def test_composed_prompt_reaches_codex_but_private_layers_stay_out_of_history(agent, monkeypatch, tmp_path):
    process = FakeProcess(FakeStream(jsonl(*TURN)))
    spawn(monkeypatch, process)
    marker = "PRIVATE_BACKEND_TURN_MARKER"
    composed = f"{marker}\n[Demande]\nquestion publique"

    await agent.ask(
        composed,
        timeout_s=5,
        prompt_evidence={"program_id": "backend.codex.turn", "application": "sent"},
        input_text="question publique",
    )

    assert marker in process.stdin.written.decode("utf-8")
    assert marker not in json.dumps(agent.snapshot(), ensure_ascii=False)
    assert marker not in json.dumps(read_jsonl_tail(tmp_path / "trace.jsonl"), ensure_ascii=False)
    assert agent.prompt_applications == [{"program_id": "backend.codex.turn", "application": "sent"}]


async def test_busy_codex_send_discards_one_shot_prompt_evidence(agent, monkeypatch):
    pending = asyncio.create_task(asyncio.Event().wait())
    agent._background = pending
    agent.set_next_prompt_evidence({"program_id": "old-turn"})
    try:
        with pytest.raises(RuntimeError, match="déjà en cours"):
            await agent.send("premier tour")
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)

    assert agent._next_prompt_evidence is None
    agent._background = None
    spawn(monkeypatch, FakeProcess(FakeStream(jsonl(*TURN))))
    await agent.ask("tour suivant", timeout_s=5)
    assert agent.prompt_applications == []


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


# ------------------------------------------------ passerelle jarvis-tools (plugins MCP, Slice 05)

import os  # noqa: E402
import shutil  # noqa: E402
import sys  # noqa: E402
from dataclasses import replace  # noqa: E402

from jarvis.runtime import codex_local  # noqa: E402
from jarvis.runtime.claude_local import BRAIN_TOOLS_PROMPT  # noqa: E402
from jarvis.runtime.prompt_runtime import compose_agent_turn  # noqa: E402
from jarvis.runtime.tools_gateway_mcp import ToolsGatewayTarget, codex_config_overrides  # noqa: E402

GATEWAY_SENTINEL = "SENTINEL-SECRET-7f3a"
NPM_SHIM = "C:/Users/u/AppData/Roaming/npm/codex.CMD"


def _gateway(tmp_path, folder: str = "dossier avec espaces") -> ToolsGatewayTarget:
    token = tmp_path / folder / "core.token"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(GATEWAY_SENTINEL, encoding="utf-8")
    # Serveurs natifs volontairement renseignés : Codex n'en reçoit aucun, l'agent les vide.
    return ToolsGatewayTarget("127.0.0.1", 47001, token, tmp_path / folder / "runtime",
                              native_servers=("jarvis-console",))


def _codex_view(target: ToolsGatewayTarget) -> ToolsGatewayTarget:
    return replace(target, native_servers=(), agent="codex")


def _overrides(argv: list[str]) -> list[str]:
    return [argv[index + 1] for index, arg in enumerate(argv)
            if arg == "-c" and argv[index + 1].startswith("mcp_servers.jarvis-tools.")]


def spawn_with_env(monkeypatch, *processes: FakeProcess) -> list[tuple[list[str], dict[str, str]]]:
    """Comme `spawn`, en gardant aussi l'environnement donné au processus Codex."""
    calls: list[tuple[list[str], dict[str, str]]] = []
    queue = list(processes)

    async def fake_exec(*argv, **kwargs):  # noqa: ANN001, ANN002
        calls.append((list(argv), dict(kwargs.get("env") or {})))
        return queue.pop(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


@pytest.fixture
def npm_shim(monkeypatch):
    """Le cas réel de cette machine : `codex` résolu vers le shim npm `codex.CMD`, lancé par `cmd.exe`."""
    monkeypatch.setattr(codex_local, "resolve_command", lambda command: NPM_SHIM)
    monkeypatch.setattr(sys, "executable", "C:/Python/python.exe")


@pytest.mark.parametrize("sandbox", ["danger-full-access", "workspace-write"])
async def test_the_gateway_overrides_reach_exec_and_exec_resume_before_stdin(agent, monkeypatch, tmp_path, sandbox,
                                                                             npm_shim):
    agent.tools_mcp = _gateway(tmp_path)
    agent.permission_mode = sandbox
    calls = spawn_with_env(monkeypatch, FakeProcess(FakeStream(jsonl(*TURN))),
                           FakeProcess(FakeStream(jsonl({"type": "turn.completed", "usage": {}}))))
    await agent.ask("première", timeout_s=5)
    await agent.ask("seconde", timeout_s=5)
    expected = codex_config_overrides(_codex_view(agent.tools_mcp))
    for argv, env in calls:
        assert argv[-1] == "-"
        overrides = _overrides(argv)
        assert len(overrides) == 4 and overrides == expected[1::2]
        assert argv[-1 - len(expected):-1] == expected
        assert GATEWAY_SENTINEL not in " ".join(argv)
        # Les valeurs voyagent dans l'environnement du processus Codex (E20).
        assert {name: env[name] for name in _codex_view(agent.tools_mcp).env()} == _codex_view(agent.tools_mcp).env()
        assert GATEWAY_SENTINEL not in json.dumps(env)
    assert calls[1][0][1:3] == ["exec", "resume"]
    assert ("mcp_servers.jarvis-tools.env_vars=['JARVIS_CORE_HOST','JARVIS_CORE_PORT','JARVIS_CORE_TOKEN_FILE',"
            "'JARVIS_RUNTIME_DIR','JARVIS_TOOLS_NATIVE_SERVERS','JARVIS_TOOLS_AGENT']") in _overrides(calls[0][0])
    assert calls[0][1]["JARVIS_TOOLS_NATIVE_SERVERS"] == "" and calls[0][1]["JARVIS_TOOLS_AGENT"] == "codex"
    assert "mcp_servers.jarvis-tools.tool_timeout_sec=130" in _overrides(calls[0][0])


@pytest.mark.parametrize("folder", ["R&D", "pct%PATH%x", "car^et"])
async def test_runtime_paths_never_reach_argv_and_travel_in_the_environment(agent, monkeypatch, tmp_path, folder,
                                                                           npm_shim):
    """Reprise QA S5 (F1a) : `&` couperait la commande, `%PATH%` serait développé, `^` retiré par `cmd.exe`."""

    agent.tools_mcp = _gateway(tmp_path, folder)
    calls = spawn_with_env(monkeypatch, FakeProcess(FakeStream(jsonl(*TURN))))
    result = await agent.ask("regarde", timeout_s=5)
    [(argv, env)] = calls
    assert result["ok"] is True and argv[0] == NPM_SHIM
    assert all(folder not in arg for arg in argv) and str(tmp_path) not in " ".join(argv)
    assert env["JARVIS_CORE_TOKEN_FILE"] == str((tmp_path / folder / "core.token").resolve())
    assert env["JARVIS_RUNTIME_DIR"] == str((tmp_path / folder / "runtime").resolve())
    assert len(_overrides(argv)) == 4 and agent.snapshot()["tools_gateway"] is True
    events = read_jsonl_tail(tmp_path / "trace.jsonl", limit=50)
    assert not [e for e in events if e["kind"] == "agent.tools_mcp_failed"]


@pytest.mark.parametrize("python", ["C:/R&D/python.exe", "C:/pct%PATH%/python.exe", "C:/car^et/python.exe"])
async def test_an_interpreter_path_unsafe_through_cmd_drops_the_gateway_for_the_turn(agent, monkeypatch, tmp_path,
                                                                                    python, npm_shim):
    """Reprise QA S5 (F1b) : le tour part sans la passerelle, panne dite, snapshot honnête."""

    monkeypatch.setattr(sys, "executable", python)
    agent.tools_mcp = _gateway(tmp_path)
    await agent.start()
    assert agent.snapshot()["tools_gateway"] is False
    calls = spawn_with_env(monkeypatch, FakeProcess(FakeStream(jsonl(*TURN))))
    result = await agent.ask("regarde", timeout_s=5)
    [(argv, env)] = calls
    assert result["ok"] is True and argv[-1] == "-"
    assert _overrides(argv) == [] and python not in " ".join(argv)
    assert "JARVIS_TOOLS_AGENT" not in env
    assert agent.snapshot()["tools_gateway"] is False and agent.turn_declares_tools_gateway() is False
    [failure] = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl", limit=50) if e["kind"] == "agent.tools_mcp_failed"]
    assert failure["level"] == "error" and failure["data"]["code"] == "tools_mcp_unsafe_argv"


async def test_a_native_codex_executable_keeps_the_gateway_whatever_the_interpreter_path(agent, monkeypatch, tmp_path):
    # Pas de `cmd.exe` entre Jarvis et un `.exe` : `CreateProcess` rend l'argument intact.
    monkeypatch.setattr(codex_local, "resolve_command", lambda command: "C:/tools/codex.exe")
    monkeypatch.setattr(sys, "executable", "C:/R&D/python.exe")
    agent.tools_mcp = _gateway(tmp_path)
    calls = spawn_with_env(monkeypatch, FakeProcess(FakeStream(jsonl(*TURN))))
    await agent.ask("regarde", timeout_s=5)
    assert "mcp_servers.jarvis-tools.command='C:/R&D/python.exe'" in _overrides(calls[0][0])


async def test_without_a_gateway_target_the_command_line_is_unchanged(agent, monkeypatch):
    calls = spawn_with_env(monkeypatch, FakeProcess(FakeStream(jsonl(*TURN))))
    await agent.ask("regarde", timeout_s=5)
    assert _overrides(calls[0][0]) == [] and "JARVIS_TOOLS_AGENT" not in calls[0][1]
    assert agent.snapshot()["tools_gateway"] is False


async def test_the_snapshot_announces_the_gateway_as_soon_as_the_session_lives(agent, monkeypatch, tmp_path, npm_shim):
    """Reprise QA S5 (F2) : chaque tour lit la cible courante — rien à redémarrer, rien à attendre."""

    agent.tools_mcp = _gateway(tmp_path)
    assert agent.snapshot()["tools_gateway"] is False  # session arrêtée
    await agent.start()
    assert agent.snapshot()["state"] == "ready" and agent.snapshot()["tools_gateway"] is True  # avant tout tour
    spawn(monkeypatch, FakeProcess(FakeStream(jsonl(*TURN))))
    await agent.ask("regarde", timeout_s=5)
    assert agent.snapshot()["tools_gateway"] is True
    await agent.stop()
    assert agent.snapshot()["tools_gateway"] is False


@pytest.mark.parametrize(("sandbox", "with_target", "expected"), [
    ("danger-full-access", True, True),
    ("workspace-write", True, False),  # Q4 : `call_tool` refusé par Codex
    ("read-only", True, False),
    ("danger-full-access", False, False),
])
def test_the_tools_layer_is_composed_only_when_the_turn_can_use_the_gateway(agent, tmp_path, npm_shim,
                                                                            sandbox, with_target, expected):
    """Reprise QA S5 (F3, ARCH E20) : programme `backend.codex.tools_turn` seulement si utile."""

    agent.permission_mode = sandbox
    agent.tools_mcp = _gateway(tmp_path) if with_target else None
    prompt, evidence = compose_agent_turn(agent_id="codex", model=None, request_text="regarde", overrides=None,
                                          behavior_active=False, context={}, agent=agent)
    assert (BRAIN_TOOLS_PROMPT in prompt) is expected
    assert evidence["program_id"] == ("backend.codex.tools_turn" if expected else "backend.codex.turn")


def test_an_unsafe_interpreter_path_also_drops_the_tools_layer(agent, monkeypatch, tmp_path, npm_shim):
    monkeypatch.setattr(sys, "executable", "C:/R&D/python.exe")
    agent.tools_mcp = _gateway(tmp_path)
    prompt, _evidence = compose_agent_turn(agent_id="codex", model=None, request_text="regarde", overrides=None,
                                           behavior_active=False, context={}, agent=agent)
    assert BRAIN_TOOLS_PROMPT not in prompt


@pytest.mark.skipif(shutil.which("codex") is None, reason="requires_codex: codex CLI absent")
@pytest.mark.parametrize("folder", ["dossier avec espaces", "l'apostrophe", "R&D"])
async def test_requires_codex_the_real_cli_reads_the_overrides_back(tmp_path, folder):
    """`codex mcp get jarvis-tools --json` par le vrai shim, lancé comme l'agent le lance (argv + env)."""

    target = _codex_view(_gateway(tmp_path, folder))
    executable = codex_local.resolve_command("codex")
    process = await asyncio.create_subprocess_exec(
        executable, *codex_config_overrides(target), "mcp", "get", "jarvis-tools", "--json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **target.env()},
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
    assert process.returncode == 0, stderr.decode("utf-8", "replace")[-400:]
    shown = json.loads(stdout.decode("utf-8"))
    transport = shown.get("transport", shown)
    assert transport["command"] == sys.executable
    assert transport["args"] == ["-m", "jarvis", "tools-mcp"]
    assert transport["env_vars"] == list(target.env())
    assert not transport.get("env")  # aucune valeur dans la configuration : elles sont dans l'environnement
    assert GATEWAY_SENTINEL not in stdout.decode("utf-8")
