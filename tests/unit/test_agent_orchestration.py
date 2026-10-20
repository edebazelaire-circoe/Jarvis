"""Orchestration organique : grammaire des modificateurs, décisions du hook, charte consciente du rôle (Slice 05).

Handoff jarvis-organic-agent-orchestration. Module pur `jarvis/domain/agent_orchestration.py` ; contrat
`docs/agent-orchestration.md`.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain import agent_markers
from jarvis.domain.agent_charter import (
    CHARTER_MARK, DELEGATION_PARAGRAPH, MAX_DELEGATION_DEPTH, NO_DELEGATION_PARAGRAPH, sign_brief,
)
from jarvis.domain.agent_orchestration import (
    FALLBACK_OBJECTIVE, MAX_SPAWNS_PER_WINDOW, MISSION_MARK, NATIVE_MAX_SPAWN_DEPTH, NO_SPAWN_AGENT_TYPE,
    MissionDecision, agents_argument, decide_method, decide_mission, decide_spawn_guard, mission_brief,
    mission_id_for, no_spawn_agent_definition,
)
from jarvis.domain.subagent_roles import ROLES, role_for
from jarvis.domain.work_methods import BUILTIN_METHODS

head = agent_markers.parse_head


# ---------------------------------------------------------------- grammaire des modificateurs


@pytest.mark.parametrize(("text", "role", "mission", "method", "label"), [
    ("[general] [research-lead] [mission] Comparer", "research-lead", True, None, "Comparer"),
    ("[general] [research] [quick-research] Chercher", "research", False, "quick-research", "Chercher"),
    ("[general] [research-lead] [comparative-research] [mission] X", "research-lead", True, "comparative-research", "X"),
    ("[research-lead] [mission] X", "research-lead", True, None, "X"),
    ("[éphémère] [code] [coder] [mission] X", "coder", True, None, "X"),
])
def test_modifiers_follow_a_consumed_role(text, role, mission, method, label):
    parsed = head(text)
    assert (parsed.role, parsed.mission, parsed.method, parsed.label) == (role, mission, method, label)


@pytest.mark.parametrize("text", [
    "[general] [mission] Comparer",          # sans rôle : modificateur laissé dans le libellé
    "[code] [quick-research] Chercher",
    "[general] [research] [mission] [mission] X",  # doublon : le second reste dans le libellé
])
def test_modifiers_without_a_role_or_repeated_stay_in_the_label(text):
    parsed = head(text)
    if parsed.role is None:
        assert not parsed.mission and parsed.method is None
        assert "[mission]" in parsed.label or "[quick-research]" in parsed.label
    else:
        assert parsed.mission and parsed.label == "[mission] X"


def test_a_lone_first_word_is_consumed_as_before_and_declares_nothing():
    # Règle historique inchangée : le premier mot est toujours consommé ; ce n'est pas un modificateur.
    parsed = head("[mission] Comparer")
    assert (parsed.role, parsed.mission, parsed.label) == (None, False, "Comparer")


def test_the_playbook_role_is_still_read_among_the_three_first_words_only():
    from jarvis.runtime import routing_hook
    assert routing_hook.read_playbook_role({"description": "[general] [presentation-brief] Plan"}) == "presentation-brief"
    # Un quatrième mot n'a jamais été lu comme rôle de production : il ne l'est pas davantage.
    assert routing_hook.read_playbook_role({"description": "[general] [research] [mission] [presentation-brief] x"}) is None


def test_method_markers_are_the_builtin_method_ids():
    assert agent_markers.METHOD_MARKERS == {method.method_id for method in BUILTIN_METHODS}
    assert agent_markers.MISSION_MARKER not in agent_markers.METHOD_MARKERS


# ---------------------------------------------------------------- mission


def test_a_brain_level_role_that_can_own_a_mission_opens_a_root_mission():
    decision = decide_mission(head("[code] [coder] Corriger"), role_for("coder"), tool_use_id="toolu_1", nested=False)
    assert decision == MissionDecision(mission_owner=True, mission_id="mis_toolu_1", sub_mission=False)
    assert mission_id_for("toolu_1") == "mis_toolu_1"


def test_a_nested_agent_opens_a_sub_mission_only_with_the_marker():
    lead = role_for("research-lead")
    member = decide_mission(head("[general] [research-lead] Chercher"), lead, tool_use_id="t2", nested=True)
    assert member == MissionDecision()
    owner = decide_mission(head("[general] [research-lead] [mission] Chercher"), lead, tool_use_id="t2", nested=True)
    assert owner.mission_owner and owner.sub_mission and owner.mission_id == "mis_t2"


@pytest.mark.parametrize(("text", "marker", "nested", "refused"), [
    ("[general] [research] [mission] X", "research", True, "role_cannot_own_mission"),
    ("[general] [qa] [mission] X", "qa", False, "role_cannot_own_mission"),
    ("[éphémère] [code] [coder] [mission] X", "coder", True, "ephemeral_mission_owner"),
])
def test_an_impossible_mission_marker_is_refused_and_the_agent_stays_a_member(text, marker, nested, refused):
    decision = decide_mission(head(text), role_for(marker), tool_use_id="t", nested=nested)
    assert decision == MissionDecision(refused=refused)


def test_no_mission_without_role_ephemeral_or_tool_use_id():
    assert decide_mission(head("[general] Lister"), None, tool_use_id="t", nested=False) == MissionDecision()
    assert decide_mission(head("[éphémère] [code] [coder] X"), role_for("coder"), tool_use_id="t",
                          nested=False) == MissionDecision()
    assert decide_mission(head("[code] [coder] X"), role_for("coder"), tool_use_id=None, nested=False) == MissionDecision()


# ---------------------------------------------------------------- méthode


def test_a_chosen_method_replaces_the_default_only_when_the_role_allows_it():
    lead = role_for("research-lead")
    assert decide_method(head("[general] [research-lead] X"), lead).method_id == "deep-research"
    chosen = decide_method(head("[general] [research-lead] [quick-research] X"), lead)
    assert (chosen.method_id, chosen.chosen, chosen.refused) == ("quick-research", True, None)
    refused = decide_method(head("[general] [research-lead] [bug-investigation] X"), lead)
    assert (refused.method_id, refused.chosen, refused.refused) == ("deep-research", False, "method_not_allowed")
    assert decide_method(head("[general] X"), None).method_id is None


def test_the_role_brief_renders_the_chosen_method():
    from jarvis.domain.subagent_roles import role_brief
    lead = role_for("research-lead")
    assert "(quick-research@1)" in role_brief(lead, method="quick-research")
    assert "(deep-research@1)" in role_brief(lead, method="bug-investigation")  # étrangère au rôle : le défaut
    assert "(deep-research@1)" in role_brief(lead)


# ---------------------------------------------------------------- garde de lancement


def _event(description="[general] [qa] Relire", *, agent_type=None, subagent_type="general-purpose"):
    event = {"tool_name": "Agent", "tool_use_id": "t", "tool_input": {"description": description,
                                                                      "subagent_type": subagent_type}}
    if agent_type:
        event["agent_type"] = agent_type
    return event


def test_a_non_spawning_role_is_rewritten_to_the_restricted_type_when_enforced():
    guard = decide_spawn_guard(_event(), role_for("qa"), enforce=True)
    assert (guard.deny, guard.rewrite_agent_type, guard.code) == (False, NO_SPAWN_AGENT_TYPE, "can_spawn_enforced")
    assert decide_spawn_guard(_event(subagent_type=""), role_for("qa"), enforce=True).rewrite_agent_type
    # Sans le type déclaré au CLI : rien n'est réécrit (un type inconnu ferait échouer l'appel).
    assert decide_spawn_guard(_event(), role_for("qa"), enforce=False).rewrite_agent_type is None


def test_a_spawning_role_or_no_role_is_left_alone():
    for role in (role_for("coder"), role_for("research-lead"), None):
        guard = decide_spawn_guard(_event("[code] [coder] X"), role, enforce=True)
        assert not guard.deny and guard.rewrite_agent_type is None and guard.code is None


def test_another_agent_type_is_not_replaced_and_the_gap_is_named():
    guard = decide_spawn_guard(_event(subagent_type="Explore"), role_for("qa"), enforce=True)
    assert (guard.rewrite_agent_type, guard.code) == (None, "can_spawn_not_enforced")


def test_a_call_from_the_restricted_type_is_denied():
    guard = decide_spawn_guard(_event("[code] [coder] X", agent_type=NO_SPAWN_AGENT_TYPE), role_for("coder"),
                               enforce=True)
    assert guard.deny and guard.code == "caller_cannot_spawn" and guard.reason


def test_the_rate_cap_denies_with_a_readable_reason_and_is_resource_safety_only():
    assert not decide_spawn_guard(_event(), None, enforce=True, recent_spawns=MAX_SPAWNS_PER_WINDOW - 1).deny
    guard = decide_spawn_guard(_event(), None, enforce=True, recent_spawns=MAX_SPAWNS_PER_WINDOW)
    assert guard.deny and guard.code == "spawn_rate_cap" and str(MAX_SPAWNS_PER_WINDOW) in guard.reason
    assert MAX_SPAWNS_PER_WINDOW >= 100  # une borne de ressources, pas une politique de complexité


def test_the_restricted_type_definition_removes_only_the_spawning_tools():
    definition = no_spawn_agent_definition()[NO_SPAWN_AGENT_TYPE]
    assert definition["disallowedTools"] == ["Agent", "Task"]
    assert "tools" not in definition  # tous les autres outils hérités, MCP compris (constaté en bac à sable)
    assert json.loads(agents_argument()) == no_spawn_agent_definition()


# ---------------------------------------------------------------- consigne du Mission Owner


def test_only_a_mission_owner_gets_the_mission_brief():
    assert mission_brief(MissionDecision()) is None
    root = mission_brief(MissionDecision(mission_owner=True, mission_id="m"))
    sub = mission_brief(MissionDecision(mission_owner=True, mission_id="m", sub_mission=True))
    assert root.startswith(MISSION_MARK) and sub.startswith(MISSION_MARK) and root != sub
    for text in ("[mission]", "SendMessage", "TaskStop", "[code] [coder]", "[general] [research-lead]",
                 "une tâche nette se fait seul", "rien de ce que vous ne faites qu'envisager"):
        assert text in root


def test_the_mission_brief_is_heuristic_not_a_plan():
    text = mission_brief(MissionDecision(mission_owner=True, mission_id="m")).lower()
    for forbidden in ("étape 1", "d'abord", "ensuite", "toujours lancer", "au moins", "obligatoirement"):
        assert forbidden not in text


def test_the_owner_catalogue_lists_exactly_the_roles_that_can_own_a_mission():
    text = mission_brief(MissionDecision(mission_owner=True, mission_id="m"))
    for role in ROLES:
        marker = f"[{role.default_profile}] [{role.marker}]"
        expected = role.enabled and role.can_own_mission and role.offered_to_subagents
        assert (marker in text.split("porter une mission :")[1].split(")")[0]) is expected, role.id


# ---------------------------------------------------------------- charte


def test_the_charter_depth_is_the_native_depth():
    assert MAX_DELEGATION_DEPTH == NATIVE_MAX_SPAWN_DEPTH == 3
    assert f"ne dépasse pas {NATIVE_MAX_SPAWN_DEPTH} niveaux" in DELEGATION_PARAGRAPH.replace("\n", " ")


def test_the_charter_is_role_aware_and_signed_once():
    spawning, alone = sign_brief("Consigne."), sign_brief("Consigne.", can_spawn=False)
    assert DELEGATION_PARAGRAPH in spawning and NO_DELEGATION_PARAGRAPH not in spawning
    assert NO_DELEGATION_PARAGRAPH in alone and DELEGATION_PARAGRAPH not in alone
    assert spawning.count(CHARTER_MARK) == alone.count(CHARTER_MARK) == 1
    assert sign_brief(spawning, can_spawn=False) == spawning
    assert FALLBACK_OBJECTIVE
