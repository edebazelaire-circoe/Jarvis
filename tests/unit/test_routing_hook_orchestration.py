"""Le hook `PreToolUse` source des déclarations (D25) : fait déposé, garde `can_spawn`, borne, mission (Slice 05).

Handoff jarvis-organic-agent-orchestration. Le hook reste court et hors ligne : il dépose un fait dans le registre
local (`agent_declarations`), jamais un appel vers Core. Dossiers temporaires seulement.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from jarvis.domain.agent_orchestration import (
    MAX_SPAWNS_PER_WINDOW, MISSION_MARK, NO_SPAWN_AGENT_TYPE, SPAWN_GUARD_ENV, SPAWN_GUARD_VALUE,
)
from jarvis.domain import delivery_quality
from jarvis.domain.mission_history import AgentDeclarationFact
from jarvis.runtime import agent_declarations, routing_hook
from jarvis.runtime.journal import read_jsonl_tail


def call(description: str, *, tool_use_id: str = "toolu_A", agent_id: str | None = None,
         agent_type: str | None = None, subagent_type: str = "general-purpose", prompt: str = "Fais-le.") -> dict:
    event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": tool_use_id, "session_id": "s1",
             "tool_input": {"description": description, "prompt": prompt, "subagent_type": subagent_type,
                            "run_in_background": False}}
    if agent_id:
        event["agent_id"] = agent_id
    if agent_type:
        event["agent_type"] = agent_type
    return event


def section(output: dict) -> dict:
    return output.get("hookSpecificOutput") or {}


def facts(root: Path) -> list[AgentDeclarationFact]:
    return [item.fact for item in agent_declarations.scan(root).facts]


def trace(root: Path, kind: str) -> list[dict]:
    return [event for event in read_jsonl_tail(root / "trace.jsonl", limit=500) if event.get("kind") == kind]


def test_the_hook_deposits_a_bounded_fact_without_any_content(tmp_path):
    output = routing_hook.run(call("[code] [coder] Corriger le bug", prompt="Secret 4291 du prompt"), tmp_path)
    assert section(output)["permissionDecision"] == "allow"
    [fact] = facts(tmp_path)
    assert (fact.tool_use_id, fact.role_id, fact.profile, fact.label) == ("toolu_A", "coder", "code", "Corriger le bug")
    assert (fact.mission_owner, fact.mission_id, fact.session_id) == (True, "mis_toolu_A", "s1")
    raw = next(agent_declarations.ledger_dir(tmp_path).glob("*.json")).read_text(encoding="utf-8")
    assert "4291" not in raw and "prompt" not in json.loads(raw)
    [line] = trace(tmp_path, "agent.declared")
    assert line["data"]["written"] is True and line["data"]["mission_owner"] is True


def test_the_mission_owner_brief_is_appended_last_and_only_for_owners(tmp_path):
    owner = section(routing_hook.run(call("[code] [coder] Corriger"), tmp_path))["updatedInput"]["prompt"]
    # Slice 11 : le paragraphe de restitution clôt le bloc de mission, juste après sa dernière phrase.
    assert owner.rstrip().endswith(delivery_quality.delivery_brief("[code] [coder] Corriger\nFais-le."))
    assert "rien de ce que vous ne faites qu'envisager.\n\nRESTITUTION (JARVIS)" in owner
    assert owner.count(MISSION_MARK) == 1
    member = section(routing_hook.run(call("[code] [coder] Corriger", tool_use_id="t2", agent_id="a1"), tmp_path))
    assert MISSION_MARK not in member["updatedInput"]["prompt"]
    plain = section(routing_hook.run(call("[general] Lister", tool_use_id="t3"), tmp_path))
    assert MISSION_MARK not in plain["updatedInput"]["prompt"]


def test_a_nested_mission_marker_opens_a_sub_mission(tmp_path):
    routing_hook.run(call("[general] [research-lead] [mission] Comparer", tool_use_id="t9", agent_id="a1"), tmp_path)
    [fact] = facts(tmp_path)
    assert (fact.mission_owner, fact.mission_id, fact.caller_agent_id, fact.label) == (True, "mis_t9", "a1", "Comparer")
    [line] = trace(tmp_path, "agent.declared")
    assert line["data"]["sub_mission"] is True


def test_an_impossible_mission_marker_is_journaled_and_the_agent_still_starts(tmp_path):
    output = routing_hook.run(call("[general] [research] [mission] Chercher", agent_id="a1"), tmp_path)
    assert section(output)["permissionDecision"] == "allow"
    [fact] = facts(tmp_path)
    assert not fact.mission_owner and fact.mission_id is None
    assert trace(tmp_path, "agent.declared")[0]["data"]["mission_refused"] == "role_cannot_own_mission"


def test_the_chosen_method_is_applied_and_traced(tmp_path):
    prompt = section(routing_hook.run(call("[general] [research] [quick-research] Chercher"), tmp_path))
    assert "(quick-research@1)" in prompt["updatedInput"]["prompt"]
    [role] = trace(tmp_path, "agent.role_applied")
    assert role["data"]["work_method"] == "quick-research@1"
    assert trace(tmp_path, "agent.declared")[0]["data"]["work_method_chosen"] is True


def test_can_spawn_false_rewrites_the_agent_type_only_with_the_guard(tmp_path):
    guarded = section(routing_hook.run(call("[general] [qa] Relire"), tmp_path, spawn_guard=True))
    assert guarded["updatedInput"]["subagent_type"] == NO_SPAWN_AGENT_TYPE
    assert routing_hook.GUARD_NOTE in guarded["permissionDecisionReason"]
    unguarded = section(routing_hook.run(call("[general] [qa] Relire", tool_use_id="t2"), tmp_path))
    assert unguarded["updatedInput"]["subagent_type"] == "general-purpose"
    coder = section(routing_hook.run(call("[code] [coder] X", tool_use_id="t3"), tmp_path, spawn_guard=True))
    assert coder["updatedInput"]["subagent_type"] == "general-purpose"
    codes = [line["data"]["spawn_guard"] for line in trace(tmp_path, "agent.declared")]
    assert codes == ["can_spawn_enforced", None, None]


def test_a_call_from_the_restricted_type_is_denied_and_declares_nothing(tmp_path):
    output = routing_hook.run(call("[code] [coder] X", agent_id="a1", agent_type=NO_SPAWN_AGENT_TYPE), tmp_path,
                              spawn_guard=True)
    assert section(output)["permissionDecision"] == "deny"
    assert facts(tmp_path) == []
    [refused] = trace(tmp_path, "agent.spawn_refused")
    assert refused["data"]["code"] == "caller_cannot_spawn" and refused["level"] == "warning"


def test_the_rate_cap_denies_beyond_the_window(tmp_path):
    folder = agent_declarations.ledger_dir(tmp_path)
    folder.mkdir(parents=True)
    now = int(__import__("time").time() * 1000)
    for index in range(MAX_SPAWNS_PER_WINDOW):
        (folder / f"{now - index}-toolu_{index}.json").write_text("{}", encoding="utf-8")
    output = routing_hook.run(call("[general] Lister", tool_use_id="toolu_new"), tmp_path)
    assert section(output)["permissionDecision"] == "deny"
    reason = section(output)["permissionDecisionReason"]
    assert "Borne de sûreté" in reason and "La fenêtre libère une place dans" in reason
    assert "Attendez la fin des agents" not in reason
    seconds = int(reason.split("place dans ")[1].split(" s")[0])
    assert 590 <= seconds <= 600  # la plus ancienne vient d'être écrite : elle sort dans ~10 min
    assert trace(tmp_path, "agent.spawn_refused")[0]["data"]["code"] == "spawn_rate_cap"


def test_a_routing_deny_declares_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(routing_hook, "_route", lambda *args: routing_hook._output("deny", "aucun modèle"))
    output = routing_hook.run(call("[code] [coder] X"), tmp_path)
    assert section(output)["permissionDecision"] == "deny"
    assert facts(tmp_path) == [] and trace(tmp_path, "agent.declared") == []


def test_a_ledger_failure_never_blocks_the_call(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise PermissionError("disque refusé")

    monkeypatch.setattr(agent_declarations, "write_fact", broken)
    output = routing_hook.run(call("[code] [coder] X"), tmp_path)
    assert section(output)["permissionDecision"] == "allow"
    [failure] = trace(tmp_path, "agent.declaration.failed")
    assert failure["data"]["code"] == "declaration_write_failed" and failure["level"] == "error"
    assert trace(tmp_path, "agent.declared")[0]["data"]["written"] is False


def test_an_unreadable_ledger_lets_the_call_through_and_says_so(tmp_path, monkeypatch):
    def unreadable(*args, **kwargs):
        raise OSError("dossier illisible")

    monkeypatch.setattr(agent_declarations, "recent_stamps", unreadable)
    assert section(routing_hook.run(call("[general] Lister"), tmp_path))["permissionDecision"] == "allow"
    assert trace(tmp_path, "agent.declaration.failed")[0]["data"]["code"] == "declaration_ledger_unreadable"


def test_an_event_without_tool_use_id_cannot_be_joined_and_is_journaled(tmp_path):
    event = call("[code] [coder] X")
    del event["tool_use_id"]
    assert section(routing_hook.run(event, tmp_path))["permissionDecision"] == "allow"
    assert facts(tmp_path) == []
    assert trace(tmp_path, "agent.declaration.failed")[0]["data"]["code"] == "declaration_unjoinable"


def test_other_tools_are_untouched(tmp_path):
    assert routing_hook.run({"tool_name": "Bash", "tool_use_id": "t", "tool_input": {"command": "ls"}}, tmp_path) == {}
    assert not agent_declarations.ledger_dir(tmp_path).exists()


def test_the_hook_command_carries_no_new_flag_and_the_guard_comes_from_the_environment(tmp_path, monkeypatch):
    # Reprise QA M1 : le lanceur ne met plus rien de neuf sur la ligne de commande du hook.
    settings = json.loads(routing_hook.hook_settings(tmp_path))
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert routing_hook.SPAWN_GUARD_FLAG not in command and command.endswith(f'--runtime-root "{tmp_path}"')
    # Un ancien hook (argparse strict, seul `--runtime-root` connu) lit cette commande sans sortir en 2.
    import argparse
    import shlex
    old = argparse.ArgumentParser(prog="jarvis")
    old.add_subparsers(dest="command").add_parser("routing-hook").add_argument("--runtime-root", default="")
    argv = shlex.split(command, posix=False)[2:]  # après l'exécutable et `-m jarvis`
    assert argv[0] == "jarvis"
    assert old.parse_args([arg.strip('"') for arg in argv[1:]]).command == "routing-hook"
    # Le nouveau hook ne s'arme que par la variable du lanceur, dans la version exacte du contrat.
    event = call("[general] [qa] Relire")
    for value, expected in ((None, "general-purpose"), ("jarvis-no-spawn@999", "general-purpose"),
                            (SPAWN_GUARD_VALUE, NO_SPAWN_AGENT_TYPE)):
        if value is None:
            monkeypatch.delenv(SPAWN_GUARD_ENV, raising=False)
        else:
            monkeypatch.setenv(SPAWN_GUARD_ENV, value)
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
        out = io.StringIO()
        monkeypatch.setattr("sys.stdout", out)
        assert routing_hook.main(["--runtime-root", str(tmp_path)]) == 0
        assert json.loads(out.getvalue())["hookSpecificOutput"]["updatedInput"]["subagent_type"] == expected


def test_the_cli_entry_tolerates_an_unknown_flag_and_never_exits_2(tmp_path):
    # Reprise QA M1, sens « nouveau code, lanceur plus récent » : un drapeau inconnu est ignoré, sortie 0.
    import subprocess
    import sys
    event = json.dumps(call("[general] Lister"))
    root = Path(__file__).resolve().parents[2]
    env = {key: value for key, value in os.environ.items() if key != SPAWN_GUARD_ENV}
    for extra in ([], ["--spawn-guard"], ["--drapeau-futur", "valeur"]):
        done = subprocess.run([sys.executable, "-m", "jarvis", "routing-hook", "--runtime-root", str(tmp_path),
                               *extra], input=event.encode("utf-8"), capture_output=True, cwd=root, env=env,
                              timeout=120)
        assert done.returncode == 0, (extra, done.stderr.decode("utf-8", "replace")[-400:])
    from jarvis.app import _parser
    with pytest.raises(SystemExit):  # les autres commandes restent strictes
        _parser().parse_args(["health", "--drapeau-futur"])


def test_a_crashing_hook_exits_0_lets_the_call_through_and_says_so(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("panne interne")

    monkeypatch.setattr(routing_hook, "run", broken)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(call("[code] [coder] X"))))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    assert routing_hook.main(["--runtime-root", str(tmp_path)]) == 0
    assert out.getvalue() == ""  # aucune sortie : le CLI garde la consigne d'origine
    [failure] = trace(tmp_path, "agent.routing.failed")
    assert failure["data"]["code"] == "routing_hook_crashed" and failure["level"] == "error"


def test_the_guard_compares_general_purpose_without_case_and_keeps_its_note(tmp_path, monkeypatch):
    for agent_type in ("General-Purpose", "GENERAL-PURPOSE", " general-purpose ", "claude", "Claude"):
        out = section(routing_hook.run(call("[general] [qa] Relire", tool_use_id=f"t{len(agent_type)}",
                                            subagent_type=agent_type), tmp_path, spawn_guard=True))
        assert out["updatedInput"]["subagent_type"] == NO_SPAWN_AGENT_TYPE
    for agent_type in ("fork", "Explore", "Plan", "mon-type"):
        out = section(routing_hook.run(call("[general] [qa] Relire", tool_use_id=agent_type,
                                            subagent_type=agent_type), tmp_path, spawn_guard=True))
        assert out["updatedInput"]["subagent_type"] == agent_type
    assert [line["data"]["spawn_guard"] for line in trace(tmp_path, "agent.declared")][-4:] == [
        "can_spawn_not_enforced"] * 4
    # Consigne inchangée (charte en panne) : la note de la garde reste dans la raison.
    monkeypatch.setattr(routing_hook, "charter_input", lambda *args: None)
    out = section(routing_hook.run(call("[general] [qa] Relire", tool_use_id="tz"), tmp_path, spawn_guard=True))
    assert out["updatedInput"]["subagent_type"] == NO_SPAWN_AGENT_TYPE
    assert out["permissionDecisionReason"] == routing_hook.GUARD_NOTE


def test_an_unsafe_tool_use_id_never_becomes_a_path(tmp_path):
    from tests.fakes.mission_history import fact
    from jarvis.domain.mission_history import AgentDeclarationFact
    for raw in ("toolu_A.B", "con", "a" * 120):
        assert agent_declarations.file_key(raw) == raw or agent_declarations.file_key(raw).startswith("h_")
    assert agent_declarations.file_key("toolu_01Abc-_9") == "toolu_01Abc-_9"
    assert agent_declarations.file_key("toolu_A.B").startswith("h_")
    weird = AgentDeclarationFact.from_payload({**fact("toolu_1").to_payload(), "tool_use_id": "x.y.z"})
    path = agent_declarations.write_fact(tmp_path, weird)
    assert path.parent == agent_declarations.ledger_dir(tmp_path) and ".y" not in path.name
    assert agent_declarations.scan(tmp_path).facts[0].fact.tool_use_id == "x.y.z"


# ---------------------------------------------------------------- registre local


def test_the_ledger_writes_atomically_scans_once_and_prunes(tmp_path):
    from tests.fakes.mission_history import fact
    first = agent_declarations.write_fact(tmp_path, fact("toolu_1"), now_ms=1_000_000_000_000)
    agent_declarations.write_fact(tmp_path, fact("toolu_2"), now_ms=1_000_000_700_000)
    assert [p.name for p in agent_declarations.ledger_dir(tmp_path).iterdir()] == sorted(
        p.name for p in agent_declarations.ledger_dir(tmp_path).iterdir())
    scanned = agent_declarations.scan(tmp_path)
    assert [item.fact.tool_use_id for item in scanned.facts] == ["toolu_1", "toolu_2"]
    assert agent_declarations.scan(tmp_path, seen={first.name}).facts[0].fact.tool_use_id == "toolu_2"
    assert agent_declarations.recent_count(tmp_path, 600, now_ms=1_000_000_700_000) == 1
    assert agent_declarations.prune(tmp_path, older_than_s=100, now_ms=1_000_000_700_000) == 1
    assert [item.fact.tool_use_id for item in agent_declarations.scan(tmp_path).facts] == ["toolu_2"]


def test_the_ledger_reports_invalid_files_without_reading_them_twice_or_repairing(tmp_path):
    folder = agent_declarations.ledger_dir(tmp_path)
    folder.mkdir()
    (folder / "1000000000000-toolu_bad.json").write_text('{"prompt": "x"}', encoding="utf-8")
    (folder / "1000000000001-toolu_big.json").write_bytes(b"x" * (agent_declarations.MAX_FACT_BYTES + 1))
    (folder / "notes.txt").write_text("ignored", encoding="utf-8")
    result = agent_declarations.scan(tmp_path)
    assert result.facts == () and {name for name, _ in result.invalid} == {
        "1000000000000-toolu_bad.json", "1000000000001-toolu_big.json"}
    assert (folder / "1000000000000-toolu_bad.json").exists()  # jamais réparé ni effacé hors élagage


def test_the_ledger_is_bounded(tmp_path, monkeypatch):
    from tests.fakes.mission_history import fact
    monkeypatch.setattr(agent_declarations, "MAX_FILES", 2)
    agent_declarations.write_fact(tmp_path, fact("toolu_1"))
    agent_declarations.write_fact(tmp_path, fact("toolu_2"))
    with pytest.raises(agent_declarations.DeclarationLedgerFull):
        agent_declarations.write_fact(tmp_path, fact("toolu_3"))
    assert not [name for name in os.listdir(agent_declarations.ledger_dir(tmp_path)) if name.endswith(".tmp")]


# ---------------------------------------------------------------- lancement du cerveau


async def test_the_brain_declares_the_restricted_type_with_the_guarded_hook(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from test_brain_delegation import _FakePipedProcess  # noqa: E402 - le faux processus du harnais existant

    from jarvis.domain.agent_orchestration import agents_argument
    from jarvis.runtime import claude_local
    from jarvis.runtime.claude_local import ClaudeLocalAgent

    started: list[list[str]] = []

    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        started.append(list(args))
        return _FakePipedProcess()

    envs: list[dict] = []

    async def fake_exec_env(*args, **kwargs):  # noqa: ANN002, ANN003
        envs.append(dict(kwargs.get("env") or {}))
        return await fake_exec(*args, **kwargs)

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec_env)
    await ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path).start()
    argv = started[0]
    assert argv[argv.index("--agents") + 1] == agents_argument()
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert routing_hook.SPAWN_GUARD_FLAG not in settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    # L'activation passe par l'environnement du CLI, hérité par le hook (constaté sur le CLI 2.1.304).
    assert envs[0][SPAWN_GUARD_ENV] == SPAWN_GUARD_VALUE
