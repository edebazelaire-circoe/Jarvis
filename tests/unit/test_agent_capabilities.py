"""Confinement des agents en édition `presentation` (Slice 04, `docs/product-capabilities.md`).

Ce que le CLI reçoit (pas ce que la consigne promet) : outils intégrés exacts, refus de session hérités
par les sous-agents, MCP stricts, ni `--chrome` ni `bypassPermissions`, dossier de travail interne.
L'édition `full` garde le lancement d'avant, octet pour octet. Aucun vrai CLI n'est lancé ici.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.adapters.global_context import render_global_context_prompt
from jarvis.domain import agent_orchestration
from jarvis.domain.agent_capabilities import (
    CONFINED_NATIVE_TOOLS, FORBIDDEN_NATIVE_TOOLS, PRESENTATION_CAPABILITIES, UNCONFINED, AgentCapabilityError,
    agent_capability_policy,
)
from jarvis.domain.product_edition import PRESENTATION_EDITION, ProductEdition
from jarvis.runtime import claude_local
from jarvis.runtime.agent_settings import effective_agent_cli, resolve_agent_execution, resolve_agent_settings
from jarvis.runtime.claude_local import (
    BRAIN_CONFINED_CAPABILITIES_PROMPT, BRAIN_MEMORY_FILE_LINE, ClaudeLocalAgent, launched_append_prompt,
)
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.settings_mcp import ConsoleMcpTarget
from jarvis.runtime.tools_gateway_mcp import ToolsGatewayTarget

PRESENTATION = {"JARVIS_PRODUCT_EDITION": "presentation"}
FULL = {"JARVIS_PRODUCT_EDITION": "full"}
#: Outils qui écrivent, exécutent ou lancent : aucun ne doit exister pour un agent confiné.
DANGEROUS = {"Bash", "PowerShell", "Write", "Edit", "MultiEdit", "NotebookEdit", "REPL", "Monitor"}


class _Empty:
    async def readline(self) -> bytes:
        return b""


class _Process:
    pid = 4343

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


async def _launch(monkeypatch, agent: ClaudeLocalAgent) -> tuple[list[str], dict]:
    started: list[tuple[list[str], dict]] = []

    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        started.append(([str(arg) for arg in args], kwargs))
        return _Process()

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    if agent._process_tree is not None:
        monkeypatch.setattr(agent._process_tree, "attach_and_resume", lambda pid: None)
    await agent.start()
    agent.process.returncode = 0  # type: ignore[union-attr]
    await agent.stop()
    return started[0]


def _value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def _brain(tmp_path: Path, **kwargs) -> ClaudeLocalAgent:
    token = tmp_path / "core.token"
    token.write_text("x", encoding="utf-8")
    runtime = tmp_path / "runtime"
    return ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path / "code", permission_mode="bypassPermissions",
                            console_mcp=ConsoleMcpTarget("127.0.0.1", 47002, runtime),
                            tools_mcp=ToolsGatewayTarget("127.0.0.1", 47001, token, runtime), **kwargs)


# ------------------------------------------------------------------ manifeste


def test_the_manifest_derives_from_the_edition_and_full_imposes_nothing():
    assert agent_capability_policy(PRESENTATION_EDITION) is PRESENTATION_CAPABILITIES
    assert agent_capability_policy(ProductEdition.FULL) is UNCONFINED
    assert UNCONFINED.cli_args(["jarvis-console"]) == []
    assert not DANGEROUS & set(CONFINED_NATIVE_TOOLS)
    assert DANGEROUS <= set(FORBIDDEN_NATIVE_TOOLS)
    assert PRESENTATION_CAPABILITIES.permission_mode == "dontAsk" and not PRESENTATION_CAPABILITIES.chrome
    assert PRESENTATION_CAPABILITIES.agent_clis == ("claude",)


def test_allowed_rules_name_only_jarvis_servers():
    rules = PRESENTATION_CAPABILITIES.allowed_rules(["jarvis-console", "my-personal-server", "jarvis-console"])
    assert rules == (*CONFINED_NATIVE_TOOLS, "mcp__jarvis-console")


def test_refusals_are_typed():
    with pytest.raises(AgentCapabilityError) as cli:
        PRESENTATION_CAPABILITIES.ensure_agent_cli("codex")
    assert cli.value.code == "agent_cli_unavailable_in_edition"
    for capability in ("debug_console", "self_development"):
        with pytest.raises(AgentCapabilityError) as refused:
            PRESENTATION_CAPABILITIES.ensure(capability)
        assert refused.value.code == f"{capability}_unavailable_in_edition"
    UNCONFINED.ensure("debug_console")
    assert UNCONFINED.ensure_agent_cli("codex") == "codex"


# ------------------------------------------------------------------ lancement du cerveau


async def test_the_presentation_brain_is_confined_by_the_cli_itself(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    agent = _brain(tmp_path)
    argv, kwargs = await _launch(monkeypatch, agent)

    assert "--restricted" in argv and "--strict-mcp-config" in argv and "--disable-slash-commands" in argv
    assert "--chrome" not in argv and "--dangerously-skip-permissions" not in argv
    assert _value(argv, "--permission-mode") == "dontAsk" and "bypassPermissions" not in argv
    assert _value(argv, "--permission-prompts") == "none"
    tools = _value(argv, "--tools").split(",")
    assert tools == list(CONFINED_NATIVE_TOOLS)
    assert not DANGEROUS & set(tools)
    assert DANGEROUS <= set(_value(argv, "--disallowedTools").split(","))
    allowed = _value(argv, "--allowedTools").split(",")
    assert {"mcp__jarvis-console", "mcp__jarvis-tools"} <= set(allowed)
    assert not DANGEROUS & set(allowed)
    # Dossier de travail interne, jamais le code (I-002 point 6).
    workdir = tmp_path / "runtime" / "agent-workdir"
    assert kwargs["cwd"] == str(workdir) and workdir.is_dir()
    add_dirs = argv[argv.index("--add-dir") + 1:]
    assert str(tmp_path / "runtime" / "render" / "previews") in add_dirs
    assert str(tmp_path / "code") not in " ".join(argv)
    # Les sous-agents : le type restreint n'a pas de liste d'outils propre, il hérite de l'ensemble confiné.
    agents = json.loads(_value(argv, "--agents"))
    assert all("tools" not in definition for definition in agents.values())
    snapshot = agent.snapshot()
    assert snapshot["confined"] is True and snapshot["permission_mode"] == "dontAsk"
    start = [e for e in read_jsonl_tail(tmp_path / "runtime" / "trace.jsonl", limit=30) if e["kind"] == "agent.start"][-1]
    assert start["data"]["confined"] is True and start["data"]["chrome"] is False
    assert start["data"]["launch_permission_mode"] == "dontAsk"


async def test_the_presentation_prompt_describes_only_real_capabilities(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    agent = _brain(tmp_path)
    context = tmp_path / "data" / "CONTEXT_GLOBAL"
    agent.global_context_dir = context
    argv, _ = await _launch(monkeypatch, agent)
    prompt = launched_append_prompt(argv) or ""
    assert BRAIN_CONFINED_CAPABILITIES_PROMPT.splitlines()[0] in prompt
    assert BRAIN_MEMORY_FILE_LINE not in prompt and "board_memory_write" in prompt
    assert "JARVIS_FEEDBACK_DIR" not in prompt
    assert "vous ne pouvez pas le modifier" in prompt
    assert "Tu peux ajouter, retirer" not in prompt


async def test_the_full_edition_launch_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "full")
    agent = _brain(tmp_path)
    argv, kwargs = await _launch(monkeypatch, agent)
    assert "--chrome" in argv and _value(argv, "--permission-mode") == "bypassPermissions"
    for flag in ("--restricted", "--strict-mcp-config", "--tools", "--allowedTools", "--disallowedTools"):
        assert flag not in argv
    assert kwargs["cwd"] == str(tmp_path / "code")
    prompt = launched_append_prompt(argv) or ""
    assert BRAIN_MEMORY_FILE_LINE in prompt and BRAIN_CONFINED_CAPABILITIES_PROMPT.splitlines()[0] not in prompt
    assert agent.snapshot()["confined"] is False


async def test_a_never_delegation_merges_the_spawn_tools_into_the_session_refusals(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    monkeypatch.setattr(claude_local.brain_config_store, "load", lambda root: SimpleNamespace(
        document=SimpleNamespace(delegation_for=lambda brain: claude_local.DelegationTendency.NEVER), error_code=None))
    argv, _ = await _launch(monkeypatch, _brain(tmp_path))
    denied = _value(argv, "--disallowedTools").split(",")
    assert set(agent_orchestration.SPAWN_TOOLS) <= set(denied) and DANGEROUS <= set(denied)
    assert argv.count("--disallowedTools") == 1


async def test_a_back_brain_job_is_confined_too(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    agent = ClaudeLocalAgent(runtime_root=tmp_path / "runtime", cwd=tmp_path / "code",
                             permission_mode="bypassPermissions", execution_profile="job_result")
    argv, kwargs = await _launch(monkeypatch, agent)
    assert "--restricted" in argv and "--chrome" not in argv and _value(argv, "--permission-mode") == "dontAsk"
    assert not DANGEROUS & set(_value(argv, "--tools").split(","))
    assert _value(argv, "--allowedTools").split(",") == list(CONFINED_NATIVE_TOOLS)
    assert kwargs["cwd"] == str(tmp_path / "runtime" / "agent-workdir")


async def test_restricted_profiles_keep_their_own_stricter_launch(monkeypatch, tmp_path):
    launches = {}
    for edition in ("full", "presentation"):
        monkeypatch.setenv("JARVIS_PRODUCT_EDITION", edition)
        agent = ClaudeLocalAgent(runtime_root=tmp_path / edition, cwd=tmp_path, execution_profile="speculative_analysis")
        monkeypatch.setattr(claude_local, "resolve_command", lambda command: "C:/bin/claude.exe")
        argv, _ = await _launch(monkeypatch, agent)
        launches[edition] = [arg.replace(str(tmp_path / edition), "<rt>") for arg in argv]
    assert launches["full"] == launches["presentation"]
    assert _value(launches["presentation"], "--tools") == ""


# ------------------------------------------------------------------ console, Codex, réglages, jobs, self-dev


async def test_the_debug_console_is_refused_in_presentation(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    monkeypatch.setattr(claude_local.os, "name", "nt")
    spawned = []
    monkeypatch.setattr(claude_local.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    with pytest.raises(AgentCapabilityError) as refused:
        await agent.open_console()
    assert refused.value.code == "debug_console_unavailable_in_edition" and spawned == []
    assert read_jsonl_tail(tmp_path / "trace.jsonl")[-1]["kind"] == "agent.console_refused"


async def test_codex_is_refused_in_presentation(monkeypatch, tmp_path):
    from jarvis.runtime import codex_local
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    probed = []

    async def probe(command):  # noqa: ANN001
        probed.append(command)
        return {"available": True}

    monkeypatch.setattr("jarvis.runtime.cli_catalog.probe", probe)
    agent = codex_local.CodexLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="codex")
    with pytest.raises(AgentCapabilityError) as refused:
        await agent.start()
    assert refused.value.code == "agent_cli_unavailable_in_edition" and probed == []


def test_settings_cannot_widen_the_presentation_profile():
    stored = {"agent_cli": "codex", "agent_cli_settings": {"claude": {"permission_mode": "bypassPermissions"}}}
    assert resolve_agent_settings(stored, "claude", environ=PRESENTATION)["permission_mode"] == "dontAsk"
    assert resolve_agent_settings(stored, "claude", environ=FULL)["permission_mode"] == "bypassPermissions"
    assert resolve_agent_settings(stored, "claude", environ=PRESENTATION, edition_lock=False)["permission_mode"] \
        == "bypassPermissions"
    assert effective_agent_cli("codex", environ=PRESENTATION) == "claude"
    assert effective_agent_cli("codex", environ=FULL) == "codex"
    execution = resolve_agent_execution(stored, cwd=Path("."), runtime_root=Path("."), environ=PRESENTATION)
    assert execution.agent_cli == "claude" and execution.permission_mode == "dontAsk"


def test_the_control_center_refuses_codex_and_a_wider_permission_in_presentation(monkeypatch):
    from jarvis.runtime import cli_catalog
    from jarvis.runtime.control_center import ControlCenter
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    stored: list = []
    fake = SimpleNamespace(_store_agent=lambda current, agent_id, values: stored.append((agent_id, values)),
                           _refuse_locked_permission=ControlCenter._refuse_locked_permission)
    with pytest.raises(cli_catalog.CliSettingsError) as codex:
        ControlCenter._apply_cli(fake, {}, {"cli": {"agent": "codex"}})
    assert codex.value.code == "agent_cli_unavailable_in_edition"
    with pytest.raises(cli_catalog.CliSettingsError) as widen:
        ControlCenter._apply_cli(fake, {}, {"cli": {"settings": {"claude": {"permission_mode": "bypassPermissions"}}}})
    assert widen.value.code == "agent_permission_locked_by_edition" and stored == []
    # Le formulaire renvoyé tel qu'affiché (mode imposé) reste accepté.
    ControlCenter._apply_cli(fake, {}, {"cli": {"settings": {"claude": {"permission_mode": "dontAsk"}}}})
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "full")
    assert ControlCenter._apply_cli(fake, {"agent_cli": "claude"}, {"cli": {"agent": "codex"}}) == "codex"


def test_a_back_brain_codex_job_is_refused_in_presentation(monkeypatch, tmp_path):
    from jarvis.runtime.agent_settings import AgentExecutionSettings
    from jarvis.runtime.back_brain_worker import BackBrainWorkerError, create_job_agent
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    settings = AgentExecutionSettings("codex", "openai", "codex", "", "danger-full-access", tmp_path, tmp_path)
    with pytest.raises(BackBrainWorkerError) as refused:
        create_job_agent(settings, "job-1")
    assert refused.value.code == "agent_cli_unavailable_in_edition"


def test_self_development_is_refused_in_presentation(monkeypatch, tmp_path):
    from jarvis.runtime.self_dev import SelfDevError
    from jarvis.runtime.self_dev_service import SelfDevelopmentService
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    service = SelfDevelopmentService(project_root=tmp_path, runtime_root=tmp_path / "rt",
                                     settings=lambda: {"self_development": {"enabled": True, "auto_deploy": True}})
    assert service.gate() == {"enabled": False, "auto_deploy": False, "unavailable_in_edition": True}
    with pytest.raises(SelfDevError) as refused:
        service.start("modifie le code")
    assert refused.value.code == "self_development_unavailable_in_edition"
    assert service.jobs.all() == []


def test_the_global_context_rules_are_read_only_when_confined():
    value = {"root": "C:/data/CONTEXT_GLOBAL", "text": "x"}
    assert "Tu peux ajouter" in render_global_context_prompt(value)
    read_only = render_global_context_prompt({**value, "read_only": True})
    assert "vous ne pouvez pas le modifier" in read_only and "Tu peux ajouter" not in read_only
