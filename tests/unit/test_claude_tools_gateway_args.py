"""La passerelle `jarvis-tools` dans l'argv du cerveau Claude (plugins MCP, Slice 05, ARCH §8.1).

Contrat : `docs/mcp/plugins.md` §10. Profil `conversation` seulement, un
quatrième `--mcp-config` après celui de la console, fichier sans jeton ;
`JARVIS_TOOLS_NATIVE_SERVERS` = les serveurs natifs réellement déclarés à ce
lancement ; profils restreints et `job_result` inchangés octet pour octet.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.runtime import claude_local, tools_gateway_mcp
from jarvis.runtime.claude_local import launched_append_prompt
from jarvis.runtime.barehands_mcp import SERVER_NAME as BAREHANDS_SERVER, BarehandsMcpTarget
from jarvis.runtime.claude_local import BRAIN_TOOLS_PROMPT, ClaudeLocalAgent
from jarvis.runtime.display_mcp import SERVER_NAME as DISPLAY_SERVER, DisplayMcpTarget
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.settings_mcp import SERVER_NAME as CONSOLE_SERVER, ConsoleMcpTarget
from jarvis.runtime.tools_gateway_mcp import CONFIG_FILE_NAME, ENV_AGENT, ENV_NATIVE_SERVERS, SERVER_NAME, ToolsGatewayTarget

SENTINEL = "SENTINEL-SECRET-7f3a"
_TOOLS_HEADLINE = BRAIN_TOOLS_PROMPT.strip().splitlines()[0]


class _Empty:
    async def readline(self) -> bytes:
        return b""


class _Process:
    pid = 4243

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdin = None
        self.stdout = _Empty()
        self.stderr = _Empty()

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9


def _targets(tmp_path: Path) -> dict[str, object]:
    token = tmp_path / "dossier avec espaces" / "core.token"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(SENTINEL, encoding="utf-8")
    runtime = tmp_path / "runtime"
    return {
        "display": DisplayMcpTarget("127.0.0.1", 47001, token, runtime),
        "hands": BarehandsMcpTarget("127.0.0.1", 47002, runtime),
        "console": ConsoleMcpTarget("127.0.0.1", 47002, runtime),
        "tools": ToolsGatewayTarget("127.0.0.1", 47001, token, runtime),
    }


async def _launch(monkeypatch, agent: ClaudeLocalAgent, *, check_snapshot: bool = False) -> list[str]:
    started: list[list[str]] = []

    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        started.append([str(arg) for arg in args])
        return _Process()

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    if agent._process_tree is not None:
        monkeypatch.setattr(agent._process_tree, "attach_and_resume", lambda pid: None)
    await agent.start()
    if check_snapshot:
        assert agent.snapshot()["tools_gateway"] is (agent.tools_mcp is not None)
    agent.process.returncode = 0  # type: ignore[union-attr]
    assert agent.snapshot()["tools_gateway"] is False  # processus fini : plus rien d'annoncé
    await agent.stop()
    return started[0]


def _config_paths(argv: list[str]) -> list[Path]:
    return [Path(argv[index + 1]) for index, arg in enumerate(argv) if arg == "--mcp-config"]


async def test_the_conversation_brain_gets_one_gateway_config_after_the_console_without_the_token(monkeypatch, tmp_path):
    targets = _targets(tmp_path)
    agent = ClaudeLocalAgent(runtime_root=tmp_path / "runtime", cwd=tmp_path, console_mcp=targets["console"],
                             tools_mcp=targets["tools"])
    argv = await _launch(monkeypatch, agent, check_snapshot=True)
    paths = _config_paths(argv)
    assert len(paths) == 2 and paths[-1].name == CONFIG_FILE_NAME
    gateway = paths[-1]
    # Juste après la console, et l'argument suivant est une autre option (drapeau variadique).
    assert argv.index(str(gateway)) == argv.index(str(paths[0])) + 2
    assert argv[argv.index(str(gateway)) + 1].startswith("--")
    text = gateway.read_text(encoding="utf-8")
    assert SENTINEL not in text and SENTINEL not in " ".join(argv)
    server = json.loads(text)["mcpServers"][SERVER_NAME]
    assert server["args"] == ["-m", "jarvis", "tools-mcp"]
    assert server["env"]["JARVIS_CORE_TOKEN_FILE"].endswith("core.token")  # le chemin, jamais le jeton
    assert server["env"][ENV_AGENT] == "claude"
    assert server["env"][ENV_NATIVE_SERVERS] == CONSOLE_SERVER
    assert "--strict-mcp-config" not in argv
    starts = [e for e in read_jsonl_tail(tmp_path / "runtime" / "trace.jsonl", limit=20) if e["kind"] == "agent.start"]
    assert starts[-1]["data"]["tools_mcp"] is True
    assert BRAIN_TOOLS_PROMPT.strip().splitlines()[0] in launched_append_prompt(argv)


@pytest.mark.parametrize(("display", "hands", "expected"), [
    (False, False, CONSOLE_SERVER),
    (True, False, f"{DISPLAY_SERVER},{CONSOLE_SERVER}"),
    (False, True, f"{BAREHANDS_SERVER},{CONSOLE_SERVER}"),
    (True, True, f"{DISPLAY_SERVER},{BAREHANDS_SERVER},{CONSOLE_SERVER}"),
])
async def test_the_native_set_is_exactly_the_servers_declared_this_launch(monkeypatch, tmp_path, display, hands, expected):
    targets = _targets(tmp_path)
    agent = ClaudeLocalAgent(runtime_root=tmp_path / "runtime", cwd=tmp_path, console_mcp=targets["console"],
                             display_mcp=targets["display"] if display else None,
                             barehands_mcp=targets["hands"] if hands else None, tools_mcp=targets["tools"])
    argv = await _launch(monkeypatch, agent)
    declared = [path.name for path in _config_paths(argv)]
    assert len(declared) == 2 + display + hands and declared[-1] == CONFIG_FILE_NAME
    env = json.loads(_config_paths(argv)[-1].read_text(encoding="utf-8"))["mcpServers"][SERVER_NAME]["env"]
    assert env[ENV_NATIVE_SERVERS] == expected


async def test_a_console_that_failed_to_be_declared_is_not_listed_by_the_gateway(monkeypatch, tmp_path):
    targets = _targets(tmp_path)
    agent = ClaudeLocalAgent(runtime_root=tmp_path / "runtime", cwd=tmp_path, tools_mcp=targets["tools"])
    argv = await _launch(monkeypatch, agent)
    env = json.loads(_config_paths(argv)[-1].read_text(encoding="utf-8"))["mcpServers"][SERVER_NAME]["env"]
    assert env[ENV_NATIVE_SERVERS] == ""


@pytest.mark.parametrize("profile", ["job_result", "speculative_analysis", "presentation_preparation"])
async def test_restricted_and_job_profiles_are_unchanged_byte_for_byte(monkeypatch, tmp_path, profile):
    monkeypatch.setattr(claude_local, "resolve_command", lambda command: "C:/tools/claude.exe")
    targets = _targets(tmp_path)
    runtime = tmp_path / "runtime"
    tools = ["Read"] if profile == "presentation_preparation" else []
    without = await _launch(monkeypatch, ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path, execution_profile=profile,
                                                          console_mcp=targets["console"], allowed_tools=tools))
    with_gateway = await _launch(monkeypatch, ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path,
                                                               execution_profile=profile, console_mcp=targets["console"],
                                                               tools_mcp=targets["tools"], allowed_tools=tools))
    assert with_gateway == without
    assert not (runtime / CONFIG_FILE_NAME).exists()
    assert BRAIN_TOOLS_PROMPT not in " ".join(with_gateway)
    # Reprise QA S5 (F4b) : les profils restreints gardent `--strict-mcp-config` (aucun serveur hérité).
    assert ("--strict-mcp-config" in with_gateway) is (profile in claude_local.RESTRICTED_PROFILES)


async def test_a_gateway_config_that_cannot_be_written_is_journaled_and_the_brain_still_starts(monkeypatch, tmp_path):
    def refuse(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise PermissionError("disque verrouillé")

    monkeypatch.setattr(tools_gateway_mcp, "write_mcp_config", refuse)
    targets = _targets(tmp_path)
    runtime = tmp_path / "runtime"
    agent = ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path, console_mcp=targets["console"],
                             tools_mcp=targets["tools"])
    started: list[list[str]] = []

    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        started.append([str(arg) for arg in args])
        return _Process()

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    await agent.start()
    assert agent.state == "running" and agent.snapshot()["tools_gateway"] is False
    assert agent.snapshot()["console_tools"] is True
    assert len(_config_paths(started[0])) == 1
    # Reprise QA S5 (F3, E20) : passerelle non déclarée ⇒ sa consigne n'est pas composée.
    assert _TOOLS_HEADLINE not in launched_append_prompt(started[0])
    assert agent.prompt_applications[-1]["program_id"] == "backend.claude.conversation.session"
    agent.process.returncode = 0  # type: ignore[union-attr]
    await agent.stop()
    [failure] = [e for e in read_jsonl_tail(runtime / "errors.jsonl", limit=10) if e["kind"] == "agent.tools_mcp_failed"]
    assert failure["level"] == "error" and failure["data"]["code"] == "tools_mcp_config_write_failed"
    assert "PermissionError" in failure["message"]


async def test_the_tools_layer_is_composed_only_when_the_gateway_is_declared(monkeypatch, tmp_path):
    """Reprise QA S5 (F3, ARCH E20) : `BRAIN_TOOLS_PROMPT` suit la passerelle réellement déclarée."""

    targets = _targets(tmp_path)
    runtime = tmp_path / "runtime"
    plain = ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path, console_mcp=targets["console"])
    argv = await _launch(monkeypatch, plain)
    assert _TOOLS_HEADLINE not in launched_append_prompt(argv)
    assert plain.prompt_applications[-1]["program_id"] == "backend.claude.conversation.session"
    shown = ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path, console_mcp=targets["console"],
                             display_mcp=targets["display"], tools_mcp=targets["tools"])
    argv = await _launch(monkeypatch, shown)
    assert _TOOLS_HEADLINE in launched_append_prompt(argv)
    assert shown.prompt_applications[-1]["program_id"] == "backend.claude.conversation.tools_display_session"


def test_the_prompt_names_the_gateway_tools_in_full_and_stays_short():
    # Q5 (Slice 05) : `jarvis-tools` est différé derrière ToolSearch ; le nom complet est ce qui le charge.
    assert "mcp__jarvis-tools__list_tools" in BRAIN_TOOLS_PROMPT
    assert "mcp__jarvis-tools__call_tool" in BRAIN_TOOLS_PROMPT
    assert "list_tools" in BRAIN_TOOLS_PROMPT and "prérequis" in BRAIN_TOOLS_PROMPT
    assert len(BRAIN_TOOLS_PROMPT.encode("utf-8")) <= 900
