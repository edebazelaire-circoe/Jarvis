"""Tendance de délégation du cerveau Core : prompt, outil retiré au lancement, refus du hook (Slice 02).

Contrat : docs/brain-config.md § 3. Aucun JARVIS n'est lancé : le CLI est simulé (argv capturé) et le hook est
exécuté hors ligne, en processus réel (`python -m jarvis routing-hook`) avec un événement `PreToolUse` réaliste.
La trace réelle d'un CLI cerveau en `never` reste à faire en Slice 08.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from jarvis.domain.brain_config import (
    DELEGATION_RULES, STANDARD_DELEGATION_SENTENCE, BrainConfigError, DelegationTendency, apply_delegation_rule,
    parse_delegation,
)
from jarvis.domain.prompt_registry import PromptTarget
from jarvis.runtime import agent_declarations, claude_local, routing_hook
from jarvis.runtime.brain_config_store import STORE_FILE, BrainConfigStore, delegation_for, load
from jarvis.runtime.claude_local import BRAIN_SYSTEM_PROMPT, ClaudeLocalAgent, launched_append_prompt
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.prompt_catalog import conversation_session_name, default_prompt_registry
from jarvis.runtime.prompt_runtime import prompt_channel

ROOT = Path(__file__).resolve().parents[2]


def _set(root: Path, level: str) -> None:
    store = BrainConfigStore(root)
    store.set_delegation("core", DelegationTendency(level), base_revision=store.load().revision_token)


def agent_call(*, agent_id: str | None = None, tool_use_id: str = "toolu_01") -> dict:
    """Ce que le CLI Claude 2.1.x envoie au hook avant un appel `Agent` du cerveau (forme vue dans `trace.jsonl`)."""

    event = {"session_id": "5c1f", "transcript_path": "C:/x.jsonl", "cwd": "C:/Projects/jarvis",
             "permission_mode": "bypassPermissions", "hook_event_name": "PreToolUse", "tool_name": "Agent",
             "tool_use_id": tool_use_id,
             "tool_input": {"description": "[general] [research] Comparer deux offres", "prompt": "Compare A et B.",
                            "subagent_type": "general-purpose", "run_in_background": True}}
    if agent_id:
        event["agent_id"] = agent_id
    return event


# ------------------------------------------------------------------ vocabulaire


def test_the_five_levels_round_trip_through_the_store_and_an_unknown_value_is_refused(tmp_path):
    for level in DelegationTendency:
        assert parse_delegation(level.value) is level
        _set(tmp_path, level.value)
        assert delegation_for(tmp_path) is level
        assert json.loads((tmp_path / STORE_FILE).read_text(encoding="utf-8"))["brains"]["core"]["delegation"] == level.value
    for bad in ("Never", "auto", "", None, 3):
        with pytest.raises(BrainConfigError) as caught:
            parse_delegation(bad)
        assert caught.value.code == "brain_config_delegation_invalid"
    assert [level.value for level in DelegationTendency] == ["never", "rare", "standard", "proactive", "exploratory"]


def test_an_absent_file_is_standard_and_an_unknown_stored_value_is_reported_not_rewritten(tmp_path):
    assert delegation_for(tmp_path) is DelegationTendency.STANDARD and load(tmp_path).revision_token == "bc-0"
    (tmp_path / STORE_FILE).write_text(json.dumps({"schema_version": 1, "revision": 4,
                                                   "brains": {"core": {"delegation": "sometimes"}, "future": {"x": 1}}}),
                                       encoding="utf-8")
    loaded = load(tmp_path)
    assert loaded.error_code == "" and loaded.document.invalid == {"core": "sometimes"}
    assert loaded.document.delegation_for("core") is DelegationTendency.STANDARD
    _set(tmp_path, "rare")
    raw = json.loads((tmp_path / STORE_FILE).read_text(encoding="utf-8"))
    assert raw["revision"] == 5 and raw["brains"]["future"] == {"x": 1}  # entrée inconnue conservée


def test_an_unreadable_file_reads_standard_and_is_never_overwritten(tmp_path):
    (tmp_path / STORE_FILE).write_text("{pas du json", encoding="utf-8")
    assert delegation_for(tmp_path) is DelegationTendency.STANDARD
    with pytest.raises(BrainConfigError) as caught:
        BrainConfigStore(tmp_path).set_delegation("core", DelegationTendency.NEVER, base_revision="bc-0")
    assert caught.value.code == "brain_config_store_unreadable"
    assert (tmp_path / STORE_FILE).read_text(encoding="utf-8") == "{pas du json"


def test_a_stale_store_revision_is_refused(tmp_path):
    _set(tmp_path, "rare")
    with pytest.raises(BrainConfigError) as caught:
        BrainConfigStore(tmp_path).set_delegation("core", DelegationTendency.NEVER, base_revision="bc-0")
    assert caught.value.code == "brain_config_revision_stale" and caught.value.status == 409
    assert delegation_for(tmp_path) is DelegationTendency.RARE


# ------------------------------------------------------------------ prompt


def _conversation_prompt(variables: dict, **capabilities) -> str:
    name = conversation_session_name(tools=capabilities.get("tools", False), display=capabilities.get("display", False),
                                     hands=capabilities.get("hands", False))
    resolution = default_prompt_registry().resolve(
        PromptTarget("backend", None, "claude", None, None, f"conversation_{name}"), variables=variables)
    return prompt_channel(resolution, "cli.append_system_prompt")


@pytest.mark.parametrize("capabilities", [{}, {"tools": True}, {"display": True, "hands": True}])
def test_standard_keeps_the_brain_prompt_byte_for_byte(capabilities):
    without = _conversation_prompt({}, **capabilities)
    standard = _conversation_prompt({"brain_delegation": "standard"}, **capabilities)
    assert standard == without
    assert standard.startswith(BRAIN_SYSTEM_PROMPT)  # le socle rendu est la constante, inchangée
    assert BRAIN_SYSTEM_PROMPT.count(STANDARD_DELEGATION_SENTENCE) == 1


@pytest.mark.parametrize("level", [level for level in DelegationTendency if level is not DelegationTendency.STANDARD])
def test_each_other_level_replaces_exactly_the_standard_sentence(level):
    rendered = _conversation_prompt({"brain_delegation": level.value})
    expected = _conversation_prompt({}).replace(STANDARD_DELEGATION_SENTENCE, DELEGATION_RULES[level], 1)
    assert rendered == expected and STANDARD_DELEGATION_SENTENCE not in rendered.split("RETOURS UTILISATEUR")[0]
    assert apply_delegation_rule(BRAIN_SYSTEM_PROMPT, level) in rendered


def test_an_unexpected_variable_renders_standard_and_a_prompt_without_the_sentence_is_refused():
    assert _conversation_prompt({"brain_delegation": "bogus"}) == _conversation_prompt({})
    with pytest.raises(ValueError):
        apply_delegation_rule("Un prompt réécrit sans la phrase.", DelegationTendency.RARE)


# ------------------------------------------------------------------ lancement du CLI


class _Empty:
    async def readline(self) -> bytes:
        return b""


class _Process:
    pid = 4245

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


async def _launch(monkeypatch, agent: ClaudeLocalAgent) -> list[str]:
    started: list[list[str]] = []

    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        started.append([str(arg) for arg in args])
        return _Process()

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    if agent._process_tree is not None:
        monkeypatch.setattr(agent._process_tree, "attach_and_resume", lambda pid: None)
    await agent.start()
    agent.process.returncode = 0  # type: ignore[union-attr]
    await agent.stop()
    return started[0]


@pytest.mark.parametrize("profile", ["conversation", "job_result"])
async def test_never_removes_the_agent_tool_from_the_brain_cli_command(monkeypatch, tmp_path, profile):
    runtime = tmp_path / "runtime"
    _set(runtime, "never")
    argv = await _launch(monkeypatch, ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path, execution_profile=profile))
    index = argv.index("--disallowedTools")
    assert argv[index + 1:index + 3] == ["Agent", "Task"] and argv[index + 3].startswith("--")  # variadique, borné
    assert "--settings" in argv  # le hook reste déclaré : défense en profondeur
    [start] = [e for e in read_jsonl_tail(runtime / "trace.jsonl", limit=20) if e["kind"] == "agent.start"]
    assert start["data"]["delegation"] == "never" and start["data"]["spawn_tools_removed"] is True
    if profile == "conversation":
        prompt = launched_append_prompt(argv)
        assert DELEGATION_RULES[DelegationTendency.NEVER] in prompt and STANDARD_DELEGATION_SENTENCE not in prompt


@pytest.mark.parametrize("level", ["standard", "rare", "proactive", "exploratory"])
async def test_other_levels_keep_the_agent_tool(monkeypatch, tmp_path, level):
    runtime = tmp_path / "runtime"
    _set(runtime, level)
    argv = await _launch(monkeypatch, ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path))
    assert "--disallowedTools" not in argv
    assert DELEGATION_RULES[DelegationTendency(level)] in launched_append_prompt(argv)


async def test_a_restricted_profile_is_unchanged_by_never(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    plain = await _launch(monkeypatch, ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path,
                                                        execution_profile="speculative_analysis",
                                                        command=sys.executable))
    _set(runtime, "never")
    never = await _launch(monkeypatch, ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path,
                                                        execution_profile="speculative_analysis",
                                                        command=sys.executable))
    assert never == plain and "--disallowedTools" not in never  # `--tools ""` : aucun outil de lancement déjà


# ------------------------------------------------------------------ hook


def _section(output: dict) -> dict:
    return output.get("hookSpecificOutput") or {}


def test_the_hook_refuses_a_brain_agent_call_when_delegation_is_never_and_journals_it(tmp_path):
    _set(tmp_path, "never")
    output = routing_hook.run(agent_call(), tmp_path)
    assert _section(output)["permissionDecision"] == "deny"
    assert "« Jamais »" in _section(output)["permissionDecisionReason"]
    [refused] = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl", limit=50) if e["kind"] == "agent.spawn_refused"]
    assert refused["data"]["code"] == routing_hook.DELEGATION_NEVER_CODE
    assert refused["data"]["caller_agent_id"] is None and refused["data"]["written"] is False
    assert not agent_declarations.scan(tmp_path).facts  # rien n'est déclaré pour un appel refusé


def test_the_hook_lets_a_nested_call_and_any_other_level_through(tmp_path):
    _set(tmp_path, "never")
    nested = routing_hook.run(agent_call(agent_id="a-17", tool_use_id="toolu_02"), tmp_path)
    assert _section(nested).get("permissionDecision") != "deny"
    _set(tmp_path, "rare")
    brain = routing_hook.run(agent_call(tool_use_id="toolu_03"), tmp_path)
    assert _section(brain).get("permissionDecision") != "deny"


def test_an_unreadable_store_never_blocks_the_hook(tmp_path):
    (tmp_path / STORE_FILE).write_text("{abîmé", encoding="utf-8")
    output = routing_hook.run(agent_call(), tmp_path)
    assert _section(output).get("permissionDecision") != "deny"
    kinds = [e["kind"] for e in read_jsonl_tail(tmp_path / "trace.jsonl", limit=50)]
    assert "agent.delegation.unreadable" in kinds


def test_offline_hook_process_denies_a_realistic_pretooluse_event(tmp_path):
    """Essai hors ligne : le vrai point d'entrée du hook, en processus, comme le CLI le lance (`hook_settings`)."""

    _set(tmp_path, "never")
    completed = subprocess.run(
        [sys.executable, "-m", "jarvis", "routing-hook", "--runtime-root", str(tmp_path)],
        input=json.dumps(agent_call(), ensure_ascii=False).encode("utf-8"), capture_output=True, cwd=ROOT, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    decision = json.loads(completed.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse" and decision["permissionDecision"] == "deny"
    trace = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl", limit=50) if e["kind"] == "agent.spawn_refused"]
    assert trace and trace[-1]["data"]["code"] == "brain_delegation_never"
    assert trace[-1]["data"]["tool_use_id"] == "toolu_01"
