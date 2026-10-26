"""Consignes dérivées du manifeste de capacités (reprise QA Slice 04, M1 ; `docs/product-capabilities.md`).

En édition `presentation`, aucune consigne vue par un modèle — cerveau, méthode de chaque rôle proposé, consigne
signée par le hook d'aiguillage — ne cite un outil de `--disallowedTools`, ni un profil ou rôle de code ou de
bureau. Le dossier de mission s'écrit par `board_memory_write`. En `full`, chaque texte reste octet pour octet
celui d'avant.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from jarvis.domain import agent_orchestration, relation_runtime
from jarvis.domain.agent_capabilities import (
    FORBIDDEN_NATIVE_TOOLS, PRESENTATION_CAPABILITIES, SUBAGENT_CONFINED_MARK, UNCONFINED, AgentCapabilityError,
)
from jarvis.domain.subagent_roles import (
    _DOSSIER, _DOSSIER_TOOL, ROLES, adapt_instructions, brain_rules, offers_role, role_brief, role_for,
)
from jarvis.runtime import claude_local, routing_hook, subagent_roles_snapshot
from jarvis.runtime.claude_local import (
    BRAIN_SYSTEM_PROMPT, PromptAdaptationError, brain_system_prompt, render_brain_system_prompt, workspace_prompt_for,
)
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.presentation_playbooks import PLAYBOOK_ROLES

#: Profils et rôles qui supposent écrire du code, des fichiers ou piloter le poste.
ABSENT_MARKERS = ("[code]", "[coder]", "[desktop]")
_PROGRAM = "conversation_display_studio_barehands_session"


def _absent_mentions(text: str) -> list[str]:
    """Les outils refusés (mot entier, casse exacte) et marqueurs absents que `text` cite."""

    found = [tool for tool in FORBIDDEN_NATIVE_TOOLS if re.search(rf"(?<![\w-]){re.escape(tool)}(?![\w-])", text)]
    return found + [marker for marker in ABSENT_MARKERS if marker in text]


def _resolved_append_prompt(edition: str | None) -> str:
    from jarvis.domain.prompt_registry import PromptTarget
    from jarvis.runtime.prompt_runtime import prompt_channel, resolve_prompt

    variables = {} if edition is None else {"product_edition": edition}
    resolved = resolve_prompt(PromptTarget("backend", None, "claude", None, None, _PROGRAM), variables=variables)
    return prompt_channel(resolved, "cli.append_system_prompt")


def _event(head: str, tool_use_id: str = "toolu-1") -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": tool_use_id,
            "tool_input": {"description": f"{head} Préparer le sujet", "prompt": f"{head} Consigne du cerveau."}}


def _heads() -> list[str]:
    """Chaque tête qu'un cerveau `presentation` peut écrire : rôles proposés, rôles de production, mission."""

    offered = [role for role in ROLES if role.enabled and offers_role(role, PRESENTATION_CAPABILITIES)]
    heads = [f"[{role.default_profile}] [{role.marker}]" for role in offered]
    heads += [f"[{role.default_profile}] [{role.marker}] [mission]" for role in offered if role.can_own_mission]
    heads += [f"[general] [{name}]" for name in sorted(PLAYBOOK_ROLES)] + ["[general]", "[fast]"]
    return heads


# ------------------------------------------------------------------ manifeste


def test_the_presentation_manifest_offers_neither_code_nor_desktop_profiles():
    assert PRESENTATION_CAPABILITIES.offered_task_profiles == ("fast", "general")
    assert UNCONFINED.offered_task_profiles == ("desktop", "code", "fast", "general")
    assert not PRESENTATION_CAPABILITIES.writes_files and UNCONFINED.writes_files
    assert not offers_role(role_for("coder"), PRESENTATION_CAPABILITIES)
    assert offers_role(role_for("coder"), UNCONFINED) and offers_role(role_for("coder"), None)
    assert UNCONFINED.subagent_note() is None


# ------------------------------------------------------------------ full : octet pour octet


def test_full_texts_are_the_texts_from_before():
    assert render_brain_system_prompt() == BRAIN_SYSTEM_PROMPT
    assert render_brain_system_prompt(UNCONFINED) == BRAIN_SYSTEM_PROMPT
    assert brain_system_prompt("full") is BRAIN_SYSTEM_PROMPT and brain_system_prompt(None) is BRAIN_SYSTEM_PROMPT
    assert routing_hook.profile_rule(UNCONFINED) == routing_hook.PROFILE_RULE == routing_hook.profile_rule()
    assert brain_rules(capabilities=UNCONFINED) == brain_rules()
    assert claude_local.presentation_production_rule() == claude_local.PRESENTATION_PRODUCTION_RULE
    assert workspace_prompt_for("full") == claude_local.BRAIN_WORKSPACE_PROMPT
    for role in ROLES:
        assert role_brief(role, capabilities=UNCONFINED) == role_brief(role)
    assert _resolved_append_prompt("full") == _resolved_append_prompt(None)


@pytest.mark.parametrize("head", _heads() + ["[code] [coder]", "[code] [coder] [mission]", "[desktop]"])
def test_the_full_hook_signs_exactly_as_before(head):
    event = _event(head)
    assert routing_hook.charter_input(event, capabilities=UNCONFINED) == routing_hook.charter_input(event)


# ------------------------------------------------------------------ presentation : parité


def test_the_presentation_brain_prompt_mentions_no_absent_tool_profile_or_role():
    prompt = _resolved_append_prompt("presentation")
    assert _absent_mentions(prompt) == []
    assert "outils fichiers" not in prompt and "navigateur)" not in prompt
    assert "expected_sha256" in prompt and "board_memory_write" in prompt
    # Le cas B garde l'Intervieweur et le dossier de mission, désigné dans la mémoire du Board actif.
    assert "[general] [interviewer]" in prompt and "dans la mémoire du Board actif" in prompt
    assert "[general] [presentation-author]" in prompt
    # Le rendu full, lui, garde tout (référence de la mesure ci-dessus).
    assert "[code] [coder]" in _resolved_append_prompt("full")


@pytest.mark.parametrize("role", [role for role in ROLES if offers_role(role, PRESENTATION_CAPABILITIES)],
                         ids=lambda role: role.id)
def test_each_offered_role_brief_mentions_no_absent_tool(role):
    brief = role_brief(role, capabilities=PRESENTATION_CAPABILITIES)
    assert _absent_mentions(brief) == []
    if _DOSSIER in role.instructions:
        assert _DOSSIER_TOOL in brief and _DOSSIER not in brief
        assert "mode append" in brief and "expected_sha256" in brief


@pytest.mark.parametrize("head", _heads())
def test_the_presentation_hook_signs_with_real_tools_only(head):
    signed = routing_hook.charter_input(_event(head), capabilities=PRESENTATION_CAPABILITIES)["prompt"]
    assert _absent_mentions(signed) == [], head
    assert signed.count(SUBAGENT_CONFINED_MARK) == 1


def test_mission_and_relation_briefs_name_only_the_offered_roles():
    decision = agent_orchestration.MissionDecision(mission_owner=True)
    brief = agent_orchestration.mission_brief(decision, capabilities=PRESENTATION_CAPABILITIES)
    assert "[coder]" not in brief and "[general] [qa]" in brief and "[general] [research-lead]" in brief
    assert agent_orchestration.mission_brief(decision) == agent_orchestration.mission_brief(decision, capabilities=UNCONFINED)
    assert "[code] [qa]" in relation_runtime.relations_brief() and "[general] [qa]" in relation_runtime.relations_brief("general")


# ------------------------------------------------------------------ surcharges, pannes : jamais en silence


def test_an_override_that_changed_a_rewritten_passage_is_reported_and_still_gets_the_dossier_rule():
    interviewer = role_for("interviewer")
    text, missed = adapt_instructions(interviewer, "Mon intervieweur : créez mission.md et éditez-le.",
                                      PRESENTATION_CAPABILITIES)
    assert missed == ("mission_dossier",)
    assert text.endswith(_DOSSIER_TOOL)
    assert adapt_instructions(interviewer, interviewer.instructions, PRESENTATION_CAPABILITIES)[1] == ()
    assert adapt_instructions(interviewer, "x", UNCONFINED) == ("x", ())


def test_the_hook_journals_a_missed_adaptation_in_the_presentation_edition(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    subagent_roles_snapshot.write_snapshot(tmp_path, {"interviewer": "Créez le fichier mission.md."})
    output = routing_hook.run(_event("[general] [interviewer]"), tmp_path)
    prompt = output["hookSpecificOutput"]["updatedInput"]["prompt"]
    assert _DOSSIER_TOOL in prompt and SUBAGENT_CONFINED_MARK in prompt
    events = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl", limit=50)
              if e["kind"] == "agent.role.confined_adaptation_missed"]
    assert events and events[-1]["data"]["missed"] == ["mission_dossier"]
    assert events[-1]["data"]["source"] == "override" and events[-1]["level"] == "warning"


def test_the_full_hook_run_adds_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "full")
    output = routing_hook.run(_event("[general] [interviewer]"), tmp_path)
    prompt = output["hookSpecificOutput"]["updatedInput"]["prompt"]
    assert SUBAGENT_CONFINED_MARK not in prompt and _DOSSIER in prompt


def test_an_unreadable_edition_in_the_hook_is_journaled(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentaton")
    routing_hook.run(_event("[general] [research]"), tmp_path)
    kinds = [e["kind"] for e in read_jsonl_tail(tmp_path / "trace.jsonl", limit=50)]
    assert "agent.capabilities.unreadable" in kinds


def test_a_missing_workspace_line_is_an_error_not_a_silent_skip(monkeypatch):
    monkeypatch.setattr(claude_local, "BRAIN_WORKSPACE_PROMPT",
                        claude_local.BRAIN_WORKSPACE_PROMPT.replace(claude_local.BRAIN_WORKSPACE_MEMORY_WRITE_LINE, ""))
    with pytest.raises(PromptAdaptationError):
        workspace_prompt_for("presentation")


async def test_an_impossible_confined_workdir_is_a_typed_logged_refusal(tmp_path, monkeypatch):
    agent = claude_local.ClaudeLocalAgent(runtime_root=tmp_path / "runtime", cwd=tmp_path / "code")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "agent-workdir").write_text("un fichier, pas un dossier", encoding="utf-8")
    with pytest.raises(AgentCapabilityError) as raised:
        agent._confined_workdir(PRESENTATION_CAPABILITIES)
    assert raised.value.code == "agent_workdir_unavailable"
    events = [e for e in read_jsonl_tail(tmp_path / "runtime" / "trace.jsonl", limit=20)
              if e["kind"] == "agent.workdir_unavailable"]
    assert events and events[-1]["data"]["code"] == "agent_workdir_unavailable"
