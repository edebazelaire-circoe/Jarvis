"""Périmètre du cerveau de l'édition Presentation (V1.2, Slice 01 ; `docs/product-capabilities.md`).

Une seule politique, le manifeste `agent_capabilities` :

- le hook d'aiguillage refuse un rôle que l'édition n'offre pas (`role_unavailable_in_edition`), trace comprise ;
- les outils déclarés d'un rôle (`SubagentRole.tools`, descriptifs) suivent l'édition dans la charge utile ;
- la ligne `board_memory_write` dit ce que Core impose vraiment pour `replace` (`expected_sha256` recommandé) ;
- le prompt du cerveau décrit le rôle « projet Presentation » et refuse le développement.

En `full`, rien ne change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.domain.agent_capabilities import FORBIDDEN_NATIVE_TOOLS, PRESENTATION_CAPABILITIES, UNCONFINED
from jarvis.domain.product_connectors import ConnectorIntegration, connector_policy
from jarvis.domain.product_edition import ProductEdition
from jarvis.domain.subagent_roles import (
    MEMORY_WRITE_TOOL, ROLE_UNAVAILABLE_CODE, ROLES, edition_role_refusal, offers_role, role_for, role_tools,
)
from jarvis.runtime import agent_declarations, claude_local, routing_hook
from jarvis.runtime.claude_local import (
    BRAIN_PRESENTATION_PROJECT_MARK, BRAIN_WORKSPACE_MEMORY_WRITE_TOOL_LINE, presentation_project_section,
    render_brain_system_prompt, workspace_prompt_for,
)
from jarvis.runtime.journal import read_jsonl_tail

EDITIONS = ("full", "presentation")


def _event(head: str, tool_use_id: str = "toolu-scope-1") -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": tool_use_id,
            "tool_input": {"description": f"{head} Modifier le code", "prompt": f"{head} Consigne du cerveau."}}


def _decision(output: dict) -> str | None:
    return (output.get("hookSpecificOutput") or {}).get("permissionDecision")


def _refusals(runtime_root: Path) -> list[dict]:
    return [e for e in read_jsonl_tail(runtime_root / "trace.jsonl", limit=100) if e["kind"] == "agent.spawn_refused"]


# ------------------------------------------------------------------ 1. refus dur du hook


@pytest.mark.parametrize("edition", EDITIONS)
@pytest.mark.parametrize("role", ROLES, ids=lambda role: role.id)
def test_the_hook_refuses_exactly_the_roles_the_edition_does_not_offer(tmp_path, monkeypatch, edition, role):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", edition)
    capabilities = PRESENTATION_CAPABILITIES if edition == "presentation" else UNCONFINED
    output = routing_hook.run(_event(f"[{role.default_profile}] [{role.marker}]"), tmp_path)
    refused = _refusals(tmp_path)
    if offers_role(role, capabilities):
        assert _decision(output) != "deny"
        assert not [e for e in refused if e["data"]["code"] == ROLE_UNAVAILABLE_CODE]
        return
    assert edition == "presentation" and role.id == "coder"
    assert _decision(output) == "deny"
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert ROLE_UNAVAILABLE_CODE in reason and "[general] [research]" in reason and "[coder]" in reason
    assert str(tmp_path) not in reason and "\\" not in reason
    assert refused and refused[-1]["data"]["code"] == ROLE_UNAVAILABLE_CODE
    assert refused[-1]["data"]["role_id"] == "coder" and refused[-1]["data"]["written"] is False
    assert refused[-1]["level"] == "warning"
    # Rien n'est déclaré à Core : le sous-agent n'existe pas.
    assert agent_declarations.recent_stamps(tmp_path, 3600) == []


@pytest.mark.parametrize("head", ["[general] [coder]", "[code] [coder] [mission]", "[fast] [coder] [éphémère]"])
def test_a_forged_coder_marker_is_refused_whatever_profile_or_flag(tmp_path, monkeypatch, head):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    output = routing_hook.run(_event(head), tmp_path)
    assert _decision(output) == "deny", head
    assert _refusals(tmp_path)[-1]["data"]["code"] == ROLE_UNAVAILABLE_CODE


def test_a_nested_forged_coder_is_refused_too(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    event = {**_event("[general] [coder]"), "agent_id": "agent-lead-1", "agent_type": "general-purpose"}
    assert _decision(routing_hook.run(event, tmp_path)) == "deny"
    assert _refusals(tmp_path)[-1]["data"]["caller_agent_id"] == "agent-lead-1"


def test_the_alias_of_an_offered_role_still_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    assert _decision(routing_hook.run(_event("[general] [reviewer]"), tmp_path)) != "deny"


def test_full_launches_a_coder_as_before(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "full")
    output = routing_hook.run(_event("[code] [coder]"), tmp_path)
    assert _decision(output) != "deny"
    assert edition_role_refusal(role_for("coder"), UNCONFINED) is None
    assert edition_role_refusal(role_for("coder"), None) is None
    assert edition_role_refusal(None, PRESENTATION_CAPABILITIES) is None


def test_an_unreadable_edition_refuses_nothing(tmp_path, monkeypatch):
    # Le confinement réel est au lancement du CLI ; le hook ne refuse jamais sur une panne.
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentaton")
    assert _decision(routing_hook.run(_event("[code] [coder]"), tmp_path)) != "deny"


# ------------------------------------------------------------------ 2. outils de rôle selon l'édition


@pytest.mark.parametrize("role", ROLES, ids=lambda role: role.id)
def test_role_tools_never_show_a_tool_the_presentation_edition_refuses(role):
    tools = role_tools(role, PRESENTATION_CAPABILITIES)
    assert not set(tools) & set(FORBIDDEN_NATIVE_TOOLS)
    assert role.as_dict(PRESENTATION_CAPABILITIES)["tools"] == list(tools)
    if any(tool in ("Write", "Edit") for tool in role.tools):
        assert MEMORY_WRITE_TOOL in tools
    # `full` : la charge d'avant, octet pour octet.
    assert role_tools(role, UNCONFINED) is role.tools and role_tools(role, None) is role.tools
    assert role.as_dict(UNCONFINED) == role.as_dict() == role.as_dict(None)


def test_qa_no_longer_declares_bash_in_presentation():
    qa = role_for("qa")
    assert "Bash" in qa.tools
    assert role_tools(qa, PRESENTATION_CAPABILITIES) == ("Read", "Grep", "Glob")


@pytest.mark.parametrize("edition", EDITIONS)
def test_the_subagent_roles_payload_follows_the_edition(tmp_path, monkeypatch, edition):
    from jarvis.runtime.control_center import ControlCenter

    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", edition)
    payload = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)._subagent_roles_payload({})
    by_id = {role["id"]: role for role in payload["roles"]}
    for role in ROLES:
        if edition == "full":
            assert by_id[role.id]["tools"] == list(role.tools)
        else:
            assert not set(by_id[role.id]["tools"]) & set(FORBIDDEN_NATIVE_TOOLS), role.id


# ------------------------------------------------------------------ 3. expected_sha256 : la consigne dit le vrai


def test_the_workspace_line_recommends_expected_sha256_without_claiming_core_requires_it():
    line = BRAIN_WORKSPACE_MEMORY_WRITE_TOOL_LINE
    assert "exige" not in line and "expected_sha256" in line and "replace écrase tout le fichier" in line
    assert line in workspace_prompt_for("presentation")
    assert line not in workspace_prompt_for("full")


def test_the_store_accepts_a_replace_without_expected_sha256(tmp_path):
    """Pourquoi la consigne ne l'exige pas : `replace` crée un fichier absent (aucune lecture possible) et un fichier
    de plus de 1 Mio n'a pas d'empreinte ; l'onglet Dossier et le gestionnaire de workspace remplacent sans elle."""

    from jarvis.adapters.board_memory_store import FileBoardMemoryStore
    from jarvis.domain.board_memory import BoardMemoryPath
    from jarvis.ports.board_memory import WriteMode

    store = FileBoardMemoryStore(tmp_path)
    written = store.write("board_ab12", BoardMemoryPath.parse("summary.md"), "v1\n", mode=WriteMode.REPLACE)
    assert written.created
    again = store.write("board_ab12", BoardMemoryPath.parse("summary.md"), "v2\n", mode=WriteMode.REPLACE)
    assert not again.created


# ------------------------------------------------------------------ 4. rôle « projet Presentation »


def test_the_presentation_prompt_describes_the_project_role_and_refuses_development():
    prompt = render_brain_system_prompt(PRESENTATION_CAPABILITIES)
    section = presentation_project_section(PRESENTATION_CAPABILITIES)
    assert section and prompt.endswith(section) and prompt.count(BRAIN_PRESENTATION_PROJECT_MARK) == 1
    for marker in ("[general] [interviewer]", "[general] [research]", "[general] [web-research]",
                   "[general] [research-lead]"):
        assert marker in section
    assert "[coder]" not in section and "[code]" not in section
    assert "presentation_source" in section and "ne fait pas de développement" in section
    assert "dépôt de JARVIS" in section and "ne lancez aucun agent pour la tenter" in section
    labels = [spec.label for spec in connector_policy(ProductEdition.PRESENTATION).connectors]
    pending = [spec.label for spec in connector_policy(ProductEdition.PRESENTATION).connectors
               if spec.integration is ConnectorIntegration.CONTRACT_PENDING]
    assert pending and all(label not in section for label in pending)
    assert all(label in section for label in labels if label not in pending)


def test_the_project_section_is_derived_from_the_manifest():
    assert presentation_project_section(None) is None and presentation_project_section(UNCONFINED) is None
    assert BRAIN_PRESENTATION_PROJECT_MARK not in claude_local.BRAIN_SYSTEM_PROMPT
    assert BRAIN_PRESENTATION_PROJECT_MARK not in render_brain_system_prompt(UNCONFINED)
    # Un manifeste qui rouvrirait l'auto-développement perdrait la phrase de refus, pas le rôle positif.
    import dataclasses
    opened = dataclasses.replace(PRESENTATION_CAPABILITIES, self_development=True)
    text = presentation_project_section(opened)
    assert BRAIN_PRESENTATION_PROJECT_MARK in text and "ne fait pas de développement" not in text


def test_the_refusal_reason_is_plain_data_for_the_model():
    reason = edition_role_refusal(role_for("coder"), PRESENTATION_CAPABILITIES)
    assert reason is not None and json.loads(json.dumps(reason)) == reason
    for role in ROLES:
        if offers_role(role, PRESENTATION_CAPABILITIES) and role.offered_to_brain:
            assert f"[{role.marker}]" in reason
