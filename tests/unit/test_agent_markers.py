"""La grammaire composée des marqueurs de tête (I-005) : une seule, lue de la même façon par le hook et le suivi.

Avant : `[éphémère]` devait mener la description pour le suivi des tâches, tandis que le hook lisait
`[profil] [rôle]` en tête avec un motif ASCII seulement. `[éphémère] [code] [coder] …` perdait profil et rôle
côté hook ; `[code] [coder] [éphémère] …` perdait le drapeau côté suivi. Ici, chaque ordre est prouvé des deux
côtés, ainsi que le repli historique sur la clé `prompt` et l'échec sûr des formes mal écrites.
"""

from __future__ import annotations

import pytest

from jarvis.domain import agent_markers
from jarvis.domain.agent_markers import (
    ANNOUNCED_ROLES, EPHEMERAL_MARKER, declaration_from_hook_event, declaration_from_tool_input, parse_head,
)
from jarvis.domain.memory_settings import LOADOUT_ROLES
from jarvis.domain.subagent_roles import RoleStatus
from jarvis.runtime import agent_tasks, routing_hook
from jarvis.runtime.agent_tasks import AgentTaskTracker, parse_ephemeral_description


def tool_input(description: str, prompt: str = "Fais-le.") -> dict:
    return {"description": description, "prompt": prompt}


# ---------------------------------------------------------------- ordres


ORDERS = [
    "[éphémère] [code] [coder] Corriger la coquille",
    "[code] [éphémère] [coder] Corriger la coquille",
    "[code] [coder] [éphémère] Corriger la coquille",
]


@pytest.mark.parametrize("description", ORDERS)
def test_every_order_carries_profile_role_and_ephemeral_on_both_sides(description):
    head = parse_head(description)
    assert (head.profile, head.role, head.ephemeral) == ("code", "coder", True)
    assert head.description == "[code] [coder] Corriger la coquille"
    assert head.label == "Corriger la coquille"
    # Hook.
    assert routing_hook.read_profile(tool_input(description)) == "code"
    assert routing_hook.read_role(tool_input(description)) == "coder"
    assert routing_hook.read_loadout_role(tool_input(description)) == "coder"
    assert routing_hook.strip_profile(description) == "Corriger la coquille"
    # Suivi des tâches : le drapeau, et le rôle relu sur la description gardée, comme le hook le lit.
    kept, ephemeral = parse_ephemeral_description(description)
    assert ephemeral is True and kept == "[code] [coder] Corriger la coquille"
    assert routing_hook.read_role({"description": kept}) == "coder"


@pytest.mark.parametrize("description", ORDERS + ["[code] [coder] Corriger", "[éphémère] Liste", "[reviewer] R"])
def test_the_hook_and_the_tracker_read_one_grammar(description):
    head = parse_head(description)
    assert parse_ephemeral_description(description) == (head.description, head.ephemeral)
    assert routing_hook.read_role({"description": description}) == head.role
    assert agent_tasks.EPHEMERAL_MARKER == EPHEMERAL_MARKER == "[éphémère]"


def test_the_ephemeral_marker_alone_with_a_role_only():
    head = parse_head("[éphémère] [reviewer] Relire le diff")
    assert (head.profile, head.role, head.ephemeral, head.label) == (None, "reviewer", True, "Relire le diff")
    assert routing_hook.read_profile(tool_input("[éphémère] [reviewer] Relire le diff")) == "general"


def test_the_accented_token_never_matches_the_ascii_word_patterns():
    # `[éphémère]` n'est pas un mot de marqueur : il n'est jamais lu comme un profil inconnu consommé.
    assert routing_hook.PROFILE_PATTERN.match("[éphémère] x") is None
    assert routing_hook._BRACKET.match("[éphémère] x") is None
    assert parse_head("[éphémère] x").words == ()


def test_the_prompt_fallback_still_gives_profile_and_role_but_never_the_flag():
    call = {"description": "Corriger la coquille", "prompt": "[éphémère] [code] [coder] Corrige."}
    assert routing_hook.read_profile(call) == "code"
    assert routing_hook.read_role(call) == "coder"
    declaration = declaration_from_tool_input(call)
    assert declaration.ephemeral is False  # l'éphémère ne se déclare que dans la description
    assert declaration.role.role_id == "coder"


def test_without_any_marker_the_hook_defaults_to_general_and_no_role():
    call = tool_input("Corriger la coquille", prompt="Corrige.")
    assert routing_hook.read_profile(call) == "general" and routing_hook.read_role(call) is None


# ---------------------------------------------------------------- échec sûr


@pytest.mark.parametrize(
    "description",
    [
        "[code] [coder] [Éphémère] Corriger",
        "[code] [coder] [éphémère]Corriger",
        "[code] [éphémère] [éphémère] Corriger",
        "[code] [coder] Corriger [éphémère] la coquille",
        "[code] [coder] [éphémère]",
        "[code] [ephemere] Corriger",
    ],
)
def test_malformed_ephemeral_markers_declare_nothing_and_keep_the_text(description):
    head = parse_head(description)
    assert head.ephemeral is False
    assert head.description == description.strip()
    assert parse_ephemeral_description(description) == (description.strip(), False)


def test_two_ephemeral_markers_stop_the_head_at_the_first():
    head = parse_head("[éphémère] [éphémère] [code] [coder] x")
    assert head.ephemeral is False and head.words == () and head.role is None


def test_an_ephemeral_marker_after_an_unconsumed_word_is_still_in_the_head():
    head = parse_head("[code] [inconnu] [éphémère] Corriger")
    assert head.ephemeral is True and head.role is None
    assert head.description == "[code] [inconnu] Corriger"
    assert head.label == "[inconnu] Corriger"  # un second mot inconnu n'est pas consommé, comme avant


def test_the_head_end_includes_the_ephemeral_marker_that_belongs_to_it():
    for text in ORDERS:
        assert text[parse_head(text).head_end:] == "Corriger la coquille"
    assert routing_hook._markers("[code] [coder] [éphémère] Corriger") == (len("[code] [coder] [éphémère] "), "coder")


def test_playbook_roles_are_read_across_the_ephemeral_marker():
    call = tool_input("[éphémère] [general] [presentation-brief] Cadrer")
    assert routing_hook.read_playbook_role(call) == "presentation-brief"
    assert routing_hook.strip_profile(call["description"]) == "Cadrer"


def test_the_announced_roles_cover_loadout_roles_active_registry_markers_and_aliases():
    assert {"coder", "reviewer", "research", "interviewer", "web-research", "concept"} <= set(ANNOUNCED_ROLES)
    # Activés par la Slice 04, `qa` et `research-lead` sont annoncés ; un rôle désactivé ne le serait pas.
    assert {"research-lead", "qa"} <= set(ANNOUNCED_ROLES)
    from jarvis.domain.subagent_roles import ROLES
    assert set(ANNOUNCED_ROLES) == {*LOADOUT_ROLES, *(role.marker for role in ROLES if role.enabled), "reviewer"}
    assert routing_hook.ANNOUNCED_ROLES == ANNOUNCED_ROLES


# ---------------------------------------------------------------- corrections QA (N1 à N4)


@pytest.mark.parametrize("description", [
    "[éphémère] [éphémère]", "[éphémère] [éphémère]x", "[éphémère] [éphémère] Liste",
    "[code] [éphémère] [éphémère] x", "[code] [coder] [éphémère] [éphémère]",
])
def test_a_duplicated_marker_never_makes_a_task_silent(description):
    assert parse_ephemeral_description(description) == (description.strip(), False)


def test_a_second_marker_after_a_profile_is_a_duplicate_now():
    # Avant : vrai, description « [code] [éphémère] x ». Désormais deux marqueurs dans la tête = doublon,
    # tâche ordinaire : écart voulu, du côté sûr.
    text = "[éphémère] [code] [éphémère] x"
    assert parse_ephemeral_description(text) == (text, False)


@pytest.mark.parametrize("description", [
    "[ CODE ] [éphémère] ", "[éphémère] [code]", "[éphémère] [code] [coder]", "[code] [coder] [éphémère]\t",
    "[éphémère] [code] [foo]",
])
def test_no_declaration_without_a_label_after_every_head_marker(description):
    head = parse_head(description)
    assert head.ephemeral is False and head.description == description.strip()


def test_an_activated_role_in_the_description_wins_over_the_prompt_role():
    # Écart voulu de la Slice 04 : `[qa]` est un rôle actif, il est lu dans la description, consommé du libellé,
    # et c'est son loadout (`reviewer`) qui s'applique, plus celui de la consigne.
    call = {"description": "[code] [qa] Relire le diff", "prompt": "[code] [coder] Relis."}
    assert routing_hook.read_role(call) == "qa"
    assert routing_hook.read_loadout_role(call) == "reviewer"
    assert routing_hook.strip_profile(call["description"]) == "Relire le diff"
    from jarvis.domain.subagent_roles import resolve_role
    assert resolve_role("qa").status is RoleStatus.DECLARED


# ---------------------------------------------------------------- déclaration (D25)


def test_the_hook_event_yields_a_stable_declaration_for_core():
    event = {
        "tool_name": "Agent", "tool_use_id": "toolu-9", "agent_id": "agent-parent",
        "tool_input": {"description": "[éphémère] [code] [reviewer] Relire", "prompt": "Relis."},
    }
    payload = declaration_from_hook_event(event).to_payload()
    assert payload == {
        "profile": "code", "role_id": "qa", "role_marker": "reviewer", "role_status": "alias",
        "ephemeral": True, "label": "Relire", "tool_use_id": "toolu-9", "caller_agent_id": "agent-parent",
    }


def test_a_declaration_without_role_is_undeclared_never_guessed_from_the_label():
    declaration = declaration_from_tool_input(tool_input("Développeur : corriger le bug"))
    assert declaration.role.status is RoleStatus.UNDECLARED and declaration.role.role_id == "undeclared"
    assert declaration.profile == "general" and declaration.ephemeral is False


def test_a_hook_event_with_odd_fields_degrades_to_none():
    declaration = declaration_from_hook_event({"tool_input": None, "tool_use_id": 3, "agent_id": ["x"]})
    assert declaration.tool_use_id is None and declaration.caller_agent_id is None
    assert declaration.role.status is RoleStatus.UNDECLARED


# ---------------------------------------------------------------- suivi des tâches


def test_the_tracker_keeps_the_flag_and_the_role_in_every_order():
    for index, description in enumerate(ORDERS):
        tracker = AgentTaskTracker(provider="claude")
        tracker.observe_claude({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": f"toolu_{index}", "name": "Agent",
                                     "input": {"description": description, "prompt": "Corrige."}}]},
        }, now_ms=1_000)
        task = tracker.task_snapshot(tracker.tasks()[0])
        assert task["ephemeral"] is True, description
        assert task["role"] == "coder", description
        assert task["description"] == "[code] [coder] Corriger la coquille"


def test_the_module_is_the_only_owner_of_the_grammar():
    assert not hasattr(agent_tasks, "_EPHEMERAL_RE")
    # Slice 05 : quatre mots (profil, rôle, `[mission]`, méthode) et le marqueur éphémère.
    assert agent_markers.MAX_HEAD_MARKERS == 5
