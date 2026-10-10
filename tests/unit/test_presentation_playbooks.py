"""La méthode de production d'une présentation est apposée d'office sur la consigne du sous-agent."""

from __future__ import annotations

import pytest

from jarvis.runtime import presentation_playbooks as playbooks
from jarvis.runtime import routing_hook
from jarvis.runtime.claude_local import BRAIN_SYSTEM_PROMPT, PRESENTATION_PRODUCTION_RULE


def _event(description: str, prompt: str = "Fais la vidéo de JARVIS, d'environ une minute.") -> dict:
    return {"tool_name": "Agent", "tool_input": {"description": description, "prompt": prompt}}


@pytest.mark.parametrize("description,role", [
    ("[general] [presentation-brief] Dossier de la vidéo", playbooks.BRIEF_ROLE),
    ("[code] [presentation-author] Construire la vidéo", playbooks.AUTHOR_ROLE),
    ("[presentation-review] Relire la vidéo", playbooks.REVIEW_ROLE),
])
def test_the_playbook_of_the_announced_role_is_appended_to_the_brief(description, role):
    changed = routing_hook.charter_input(_event(description))

    assert changed is not None
    prompt = changed["prompt"]
    assert "Fais la vidéo de JARVIS" in prompt
    assert playbooks.PLAYBOOK_MARK in prompt
    assert playbooks.BRIEF_PATH in prompt
    assert playbooks.PLAYBOOKS[role].splitlines()[1] in prompt


def test_the_author_gets_the_planner_rules_the_subagent_would_never_see():
    prompt = routing_hook.charter_input(_event("[code] [presentation-author] Vidéo"))["prompt"]

    assert "draft_guide" in prompt and "presentation_draft_assemble" in prompt


def test_a_playbook_is_never_doubled():
    first = routing_hook.charter_input(_event("[general] [presentation-brief] x"))["prompt"]
    again = routing_hook.charter_input({"tool_name": "Agent", "tool_input": {
        "description": "[general] [presentation-brief] x", "prompt": first}})

    assert again is None or again["prompt"].count(playbooks.PLAYBOOK_MARK) == 1


def test_an_ordinary_subagent_gets_no_playbook():
    changed = routing_hook.charter_input(_event("[general] [research] Chercher"))

    assert changed is None or playbooks.PLAYBOOK_MARK not in changed["prompt"]


def test_the_production_markers_do_not_leak_into_the_displayed_description():
    assert routing_hook.strip_profile("[general] [presentation-brief] Dossier") == "Dossier"
    assert routing_hook.strip_profile("[presentation-author] Vidéo") == "Vidéo"
    assert routing_hook.read_role({"description": "[general] [presentation-brief] Dossier"}) is None
    assert routing_hook.read_playbook_role({"description": "[general] [research] Chercher"}) is None


def test_the_brain_is_told_to_orchestrate_and_how_to_name_the_roles():
    assert PRESENTATION_PRODUCTION_RULE in BRAIN_SYSTEM_PROMPT
    for role in playbooks.PLAYBOOK_ROLES:
        assert f"[{role}]" in PRESENTATION_PRODUCTION_RULE
