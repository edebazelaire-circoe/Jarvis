"""Les rôles de sous-agent : un registre, une méthode apposée par le hook, un cerveau qui classe la demande.

Ce qui est prouvé ici (tâche jarvis-subagent-roles-interview) : les marqueurs du
registre sont lisibles par le hook sans casser les loadouts existants, la méthode
d'un rôle est apposée une seule fois (texte enregistré par l'utilisateur, sinon
défaut du code, y compris quand l'instantané est illisible), le cerveau reçoit la
section « TYPE DE DEMANDE » avec la règle d'accord avant exécution, le suivi des
tâches expose le rôle, et l'onglet Sous-agents peut lire et éditer les rôles par
les routes du Control Center.
"""

from __future__ import annotations

import json
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.domain import subagent_roles
from jarvis.domain.agent_charter import CHARTER_MARK
from jarvis.domain.loadout_view import MANIFEST_MARK
from jarvis.domain.memory_settings import LOADOUT_ROLES
from jarvis.domain.prompt_registry import MAX_OVERRIDE_TEXT, PromptTarget, prompt_id
from jarvis.domain.subagent_roles import (
    EXECUTION_GATE_RULE, READY_PREFIX, QUESTION_PREFIX, ROLE_MARK, ROLES, brain_rules, role_for, with_role_instructions,
)
from jarvis.runtime import routing_hook, subagent_roles_snapshot
from jarvis.runtime.claude_local import BRAIN_SYSTEM_PROMPT, PRESENTATION_PRODUCTION_RULE, ClaudeLocalAgent
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.presentation_playbooks import PLAYBOOK_MARK


def call(description: str, prompt: str = "Fais-le.") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_use_id": "toolu-1",
        "tool_input": {"description": description, "prompt": prompt},
    }


def brief_of(output: dict) -> str:
    return str(((output.get("hookSpecificOutput") or {}).get("updatedInput") or {}).get("prompt") or "")


def trace(root: Path, kind: str) -> list[dict]:
    path = root / "trace.jsonl"
    items = read_jsonl_tail(path, limit=1000) if path.exists() else []
    return [item for item in items if item["kind"] == kind]


# ---------------------------------------------------------------- registre


def test_the_registry_holds_the_seven_roles_with_valid_unique_markers():
    # Les cinq ids d'origine indexent les surcharges enregistrées (`subagent_role.<id>`) : ils ne bougent pas.
    # Direction de recherche et Contrôle qualité s'ajoutent, désactivés jusqu'à leur câblage (Slices 04 et 07).
    assert [role.marker for role in ROLES] == [
        "interviewer", "research", "web-research", "coder", "concept", "research-lead", "qa"]
    assert len({role.id for role in ROLES}) == len({role.marker for role in ROLES}) == 7
    assert [role.id for role in ROLES if not role.enabled] == ["research-lead", "qa"]
    for role in ROLES:
        # Lisible par le motif des marqueurs du hook, et jamais confondu avec un profil.
        assert routing_hook._BRACKET.fullmatch(f"[{role.marker}] ")
        assert routing_hook.read_profile({"description": f"[{role.marker}] x"}) == "general"
        assert prompt_id(role.prompt_id) == f"subagent_role.{role.id}"
        # Éditable en entier : le défaut tient dans la borne d'une surcharge.
        assert len(role.instructions) <= MAX_OVERRIDE_TEXT
        assert role_for(role.marker.upper()) is (role if role.enabled else None)
    assert role_for("reviewer") is None and role_for("") is None
    # Les deux rôles de loadout repris gardent leur nom.
    assert {"research", "coder"} <= set(LOADOUT_ROLES) & {role.marker for role in ROLES}


def test_a_role_with_a_brace_or_an_unknown_profile_is_refused():
    base = ROLES[0]
    with pytest.raises(ValueError):
        subagent_roles.SubagentRole(**{**_fields(base), "instructions": "Texte {brief}"})
    with pytest.raises(ValueError):
        subagent_roles.SubagentRole(**{**_fields(base), "default_profile": "turbo"})
    with pytest.raises(ValueError):
        subagent_roles.SubagentRole(**{**_fields(base), "marker": "code"})


def _fields(role) -> dict:  # noqa: ANN001
    return {name: getattr(role, name) for name in role.__slots__}


def test_the_interviewer_reads_the_dossier_asks_one_question_and_ends_with_question_or_ready():
    text = role_for("interviewer").instructions
    for rule in ("Lisez d'abord le dossier de mission", "Ne reposez jamais une question déjà répondue",
                 "Une seule", QUESTION_PREFIX, READY_PREFIX, "Vous ne produisez rien de livrable"):
        assert rule in text, rule
    for marker in ("research", "web-research", "concept"):
        assert "dossier de mission" in role_for(marker).instructions


def test_role_instructions_are_appended_once_with_the_override_when_there_is_one():
    once = with_role_instructions("Consigne.", "interviewer")
    assert once.startswith("Consigne.\n\n" + ROLE_MARK + " (Intervieweur)\n")
    assert once.endswith(role_for("interviewer").instructions.strip())
    assert with_role_instructions(once, "interviewer") is None
    edited = with_role_instructions("Consigne.", "concept", {"concept": "Trois pistes, pas une de plus."})
    assert edited.endswith("Trois pistes, pas une de plus.")
    # Une surcharge vide ne vaut pas un rôle muet : le défaut revient.
    assert with_role_instructions("Consigne.", "coder", {"coder": "  "}).endswith(role_for("coder").instructions.strip())
    assert with_role_instructions("Consigne.", "reviewer") is None


# ---------------------------------------------------------------- cerveau


def test_the_brain_prompt_carries_the_request_types_and_the_execution_gate():
    rules = brain_rules()
    assert rules in BRAIN_SYSTEM_PROMPT
    assert EXECUTION_GATE_RULE in BRAIN_SYSTEM_PROMPT
    for text in ("TYPE DE DEMANDE", "A. Action claire", "B. Intention à cadrer", "C. Plusieurs expertises",
                 "[general] [interviewer]", "[code] [coder]", "SendMessage", "missions/"):
        assert text in rules, text
    # La puce remplacée a disparu, la règle de profil et la règle présentation restent.
    assert "Quand sa demande peut se lire de deux façons" not in BRAIN_SYSTEM_PROMPT
    assert routing_hook.PROFILE_RULE in BRAIN_SYSTEM_PROMPT
    assert PRESENTATION_PRODUCTION_RULE in BRAIN_SYSTEM_PROMPT


def test_the_gate_is_replaceable_on_its_own():
    rules = brain_rules(gate="Passage à l'exécution : lance sans demander.")
    assert EXECUTION_GATE_RULE not in rules and "lance sans demander" in rules


def test_a_disabled_role_is_not_offered_to_the_brain():
    from dataclasses import replace
    roles = [replace(role, enabled=False) if role.id == "concept" else role for role in ROLES]
    assert "[concept]" not in brain_rules(roles)


def test_the_brain_session_resolved_by_the_catalog_has_the_section():
    from jarvis.runtime.prompt_catalog import default_prompt_registry

    result = default_prompt_registry().resolve(PromptTarget(
        "backend", provider="claude", model="configured", compatibility="legacy", invocation="conversation_session"))
    text = next(item for item in result.channels if item["channel"] == "cli.append_system_prompt")["text"]
    assert "TYPE DE DEMANDE" in text and EXECUTION_GATE_RULE in text


def test_each_role_is_an_editable_prompt_of_the_catalog():
    from jarvis.runtime.prompt_catalog import default_prompt_registry

    registry = default_prompt_registry()
    for role in ROLES:
        descriptor = registry.require(role.prompt_id)
        assert descriptor.editable and descriptor.default_text == role.instructions
        assert descriptor.apply_policy == "next_invocation"


# ---------------------------------------------------------------- hook


def test_the_hook_reads_registry_markers_and_keeps_loadout_roles_intact():
    assert routing_hook.read_role({"description": "[general] [interviewer] Cadrer la vidéo"}) == "interviewer"
    assert routing_hook.read_role({"description": "[web-research] Chercher"}) == "web-research"
    assert routing_hook.read_role({"description": "[code] [coder] Corriger"}) == "coder"
    assert routing_hook.read_role({"description": "[code] [reviewer] Relire"}) == "reviewer"
    # Un rôle sans loadout garde celui de son profil.
    assert routing_hook.read_loadout_role({"description": "[general] [interviewer] Cadrer"}) is None
    assert routing_hook.read_loadout_role({"description": "[general] [research] Chercher"}) == "research"
    assert routing_hook.strip_profile("[general] [concept] Pistes visuelles") == "Pistes visuelles"


def test_the_hook_appends_the_role_method_after_the_charter_and_logs_it(tmp_path):
    output = routing_hook.run(call("[general] [interviewer] Cadrer la vidéo"), tmp_path)
    brief = brief_of(output)
    assert brief.startswith(CHARTER_MARK)
    assert brief.index("Fais-le.") < brief.index(ROLE_MARK)
    assert brief.endswith(role_for("interviewer").instructions.strip())
    assert routing_hook.ROLE_NOTE in output["hookSpecificOutput"]["permissionDecisionReason"]
    [event] = trace(tmp_path, "agent.role_applied")
    assert event["data"]["role"] == "interviewer" and event["data"]["profile"] == "general"
    assert event["data"]["source"] == "default"
    assert role_for("interviewer").instructions not in json.dumps(event)


def test_a_brief_without_role_gets_no_method_and_no_event(tmp_path):
    brief = brief_of(routing_hook.run(call("[code] Corriger le bug"), tmp_path))
    assert brief.startswith(CHARTER_MARK) and ROLE_MARK not in brief
    assert trace(tmp_path, "agent.role_applied") == []


def test_a_brief_already_carrying_the_method_is_not_given_a_second_one(tmp_path):
    first = brief_of(routing_hook.run(call("[general] [concept] Pistes"), tmp_path))
    again = routing_hook.charter_input(call("[general] [concept] Pistes", prompt=first))
    assert again is None


def test_the_saved_override_reaches_the_subagent(tmp_path):
    subagent_roles_snapshot.write_snapshot(tmp_path, {"interviewer": "Posez une seule question, puis PRÊT."})
    brief = brief_of(routing_hook.run(call("[general] [interviewer] Cadrer"), tmp_path))
    assert brief.endswith("Posez une seule question, puis PRÊT.")
    assert role_for("interviewer").instructions not in brief
    assert trace(tmp_path, "agent.role_applied")[0]["data"]["source"] == "override"


def test_an_unreadable_snapshot_falls_back_to_the_code_default(tmp_path):
    (tmp_path / subagent_roles_snapshot.SNAPSHOT_FILE).write_text("{pas du json", encoding="utf-8")
    brief = brief_of(routing_hook.run(call("[general] [web-research] Chercher"), tmp_path))
    assert brief.endswith(role_for("web-research").instructions.strip())
    [failure] = trace(tmp_path, "agent.role.failed")
    assert failure["data"]["code"] == "subagent_roles_snapshot_failed" and failure["level"] == "warning"


def test_the_role_method_lives_with_the_production_playbook(tmp_path):
    brief = brief_of(routing_hook.run(call("[code] [coder] [presentation-author] Construire la vidéo"), tmp_path))
    assert brief.count(PLAYBOOK_MARK) == 1 and brief.count(ROLE_MARK) == 1
    assert brief.index(PLAYBOOK_MARK) < brief.index(ROLE_MARK)


def test_a_role_without_loadout_keeps_the_manifest_of_its_profile(tmp_path):
    manifest = f"{MANIFEST_MARK} profil general"
    (tmp_path / "loadout-snapshot.json").write_text(json.dumps({
        "schema": 1, "written_at": "", "loadouts": {"general": {"manifest": manifest}},
    }), encoding="utf-8")
    brief = brief_of(routing_hook.run(call("[general] [interviewer] Cadrer"), tmp_path))
    assert brief.endswith(manifest) and ROLE_MARK in brief
    note = routing_hook._brief_note(True, True, role=True)
    assert note == f"{routing_hook.CHARTER_NOTE} {routing_hook.ROLE_NOTE} {routing_hook.LOADOUT_NOTE}"


# ---------------------------------------------------------------- instantané


def test_the_snapshot_keeps_only_known_roles_and_tolerates_absence(tmp_path):
    assert subagent_roles_snapshot.read_overrides(tmp_path) == {}
    path = subagent_roles_snapshot.write_snapshot(tmp_path, {"concept": "Deux pistes.", "inconnu": "x"})
    assert subagent_roles_snapshot.read_overrides(tmp_path) == {"concept": "Deux pistes."}
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["overrides"]["coder"] = "ok\x07"
    raw["overrides"]["research"] = 42
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert subagent_roles_snapshot.read_overrides(tmp_path) == {"concept": "Deux pistes.", "coder": "ok"}
    path.write_text(json.dumps({**raw, "schema": 99}), encoding="utf-8")
    assert subagent_roles_snapshot.read_overrides(tmp_path) == {}
    path.write_text(" " * (subagent_roles_snapshot.MAX_SNAPSHOT_BYTES + 1), encoding="utf-8")
    assert subagent_roles_snapshot.read_overrides(tmp_path) == {}


def test_refresh_writes_only_effective_overrides(tmp_path):
    from jarvis.runtime.prompt_catalog import default_prompt_registry

    descriptor = default_prompt_registry().require("subagent_role.research")
    document = {"schema_version": 1, "overrides": {
        "subagent_role.research": {"base_revision": descriptor.default_revision, "text": "Cherchez dans le Board."},
        # Surcharge périmée : le défaut a changé depuis, elle ne s'applique pas.
        "subagent_role.coder": {"base_revision": "0" * 64, "text": "Ancien texte."},
    }}
    assert subagent_roles_snapshot.refresh(tmp_path, document) == {"research": "Cherchez dans le Board."}
    assert subagent_roles_snapshot.read_overrides(tmp_path) == {"research": "Cherchez dans le Board."}
    assert subagent_roles_snapshot.refresh(tmp_path, None) == {}


def test_the_cli_launch_writes_the_snapshot_and_reports_a_failure(tmp_path, monkeypatch):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    agent._write_subagent_roles_snapshot()
    assert (tmp_path / subagent_roles_snapshot.SNAPSHOT_FILE).is_file()
    assert trace(tmp_path, "agent.subagent_roles_snapshot_written")

    def refuse(*_args, **_kwargs):
        raise PermissionError("disque refusé")

    monkeypatch.setattr(subagent_roles_snapshot, "write_snapshot", refuse)
    agent._write_subagent_roles_snapshot()
    [failure] = trace(tmp_path, "agent.subagent_roles_snapshot_failed")
    assert failure["level"] == "error" and failure["data"]["code"] == "subagent_roles_snapshot_write_failed"


# ---------------------------------------------------------------- suivi des tâches


def test_the_task_snapshot_carries_the_announced_role(tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    for tool_use_id, description in (("toolu_A", "[general] [interviewer] Cadrer la vidéo"),
                                     ("toolu_B", "Sans marqueur")):
        agent._record({"type": "assistant", "message": {"role": "assistant", "model": "claude-opus-5", "content": [
            {"type": "tool_use", "id": tool_use_id, "name": "Agent",
             "input": {"description": description, "prompt": "...", "run_in_background": True}},
        ]}})
    roles = {task["tool_use_id"]: task["role"] for task in agent.tasks_snapshot()["tasks"]}
    assert roles == {"toolu_A": "interviewer", "toolu_B": None}


# ---------------------------------------------------------------- Control Center


async def test_the_roles_route_lists_effective_instructions_and_an_edit_rewrites_the_snapshot(tmp_path, monkeypatch):
    from jarvis.runtime.control_center import ControlCenter

    monkeypatch.delenv("JARVIS_VOICE_ARCH", raising=False)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    async with TestClient(TestServer(control._app)) as client:
        response = await client.get("/api/subagent-roles")
        assert response.status == 200
        view = await response.json()
        assert [role["id"] for role in view["roles"]] == [role.id for role in ROLES]
        interviewer = view["roles"][0]
        assert interviewer["modified"] is False and interviewer["conflict"] is None
        assert interviewer["instructions"] == interviewer["default_instructions"] == ROLES[0].instructions
        assert interviewer["prompt_id"] == "subagent_role.interviewer" and interviewer["tools"]
        assert view["execution_gate"] == EXECUTION_GATE_RULE

        edited = await client.post("/api/prompts/subagent_role.interviewer", json={
            "action": "edit", "text": "Une question, puis PRÊT.",
            "base_revision": interviewer["default_revision"],
            "expected_effective_revision": interviewer["revision"],
        })
        assert edited.status == 200
        body = await edited.json()
        assert body["subagent_roles_snapshot"] == {"written": True, "modified_roles": ["interviewer"]}
        assert subagent_roles_snapshot.read_overrides(tmp_path) == {"interviewer": "Une question, puis PRÊT."}
        after = (await (await client.get("/api/subagent-roles")).json())["roles"][0]
        assert after["modified"] is True and after["instructions"] == "Une question, puis PRÊT."
        assert after["revision"] != interviewer["revision"]

        # Une édition concurrente est refusée, sans toucher l'instantané.
        stale = await client.post("/api/prompts/subagent_role.interviewer", json={
            "action": "edit", "text": "Autre.", "base_revision": interviewer["default_revision"],
            "expected_effective_revision": interviewer["revision"],
        })
        assert stale.status == 400 and stale.headers["X-Jarvis-Error-Code"] == "prompt_override_concurrent"
        assert subagent_roles_snapshot.read_overrides(tmp_path) == {"interviewer": "Une question, puis PRÊT."}

        reset = await client.post("/api/prompts/subagent_role.interviewer", json={"action": "reset"})
        assert reset.status == 200
        assert (await reset.json())["subagent_roles_snapshot"]["modified_roles"] == []
        assert subagent_roles_snapshot.read_overrides(tmp_path) == {}
        assert (await (await client.get("/api/subagent-roles")).json())["roles"][0]["modified"] is False

        # Une autre couche de prompt ne réécrit pas l'instantané des rôles.
        other = await client.post("/api/prompts/voice.persona", json={"action": "reset"})
        assert "subagent_roles_snapshot" not in await other.json()


async def test_a_snapshot_that_cannot_be_written_is_said_not_hidden(tmp_path, monkeypatch):
    from jarvis.runtime.control_center import ControlCenter

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)

    def refuse(*_args, **_kwargs):
        raise PermissionError("disque refusé")

    monkeypatch.setattr(subagent_roles_snapshot, "write_snapshot", refuse)
    async with TestClient(TestServer(control._app)) as client:
        role = (await (await client.get("/api/subagent-roles")).json())["roles"][4]
        edited = await client.post(f"/api/prompts/{role['prompt_id']}", json={
            "action": "edit", "text": "Deux pistes.", "base_revision": role["default_revision"]})
        assert edited.status == 200
        outcome = (await edited.json())["subagent_roles_snapshot"]
        assert outcome["written"] is False and outcome["code"] == "subagent_roles_snapshot_write_failed"
        # L'édition reste enregistrée : l'écran la montre modifiée.
        assert (await (await client.get("/api/subagent-roles")).json())["roles"][4]["modified"] is True
    [failure] = trace(tmp_path, "subagent_roles.snapshot_failed")
    assert failure["level"] == "error"


# ---------------------------------------------------------------- contrat de rôle (Slice 01, orchestration organique)


def test_the_handoff_names_map_to_the_kept_ids():
    from jarvis.domain.subagent_roles import role_by_id
    # Developer = coder, Document Research = research, Web Research = web-research, Conceptualizer = concept.
    assert role_by_id("coder").name == "Développement"
    assert role_by_id("research").name == "Recherche documentaire"
    assert role_by_id("web-research").name == "Recherche web"
    assert role_by_id("concept").name == "Conceptualisation"
    assert role_by_id("research-lead").name == "Direction de recherche"
    assert role_by_id("qa").name == "Contrôle qualité"
    assert role_by_id("reviewer") is None  # un alias n'est pas un rôle


@pytest.mark.parametrize(
    ("marker", "role_id", "status"),
    [
        ("coder", "coder", "declared"),
        ("CODER", "coder", "declared"),
        ("reviewer", "qa", "alias"),
        ("qa", "qa", "disabled"),
        ("research-lead", "research-lead", "disabled"),
        ("zorg", "unknown", "unknown"),
        ("", "undeclared", "undeclared"),
        (None, "undeclared", "undeclared"),
    ],
)
def test_markers_resolve_deterministically_or_degrade_explicitly(marker, role_id, status):
    from jarvis.domain.subagent_roles import resolve_role
    resolution = resolve_role(marker)
    assert (resolution.role_id, resolution.status.value) == (role_id, status)
    assert resolve_role(marker) == resolution


def test_each_role_has_its_own_visual_identity_and_coherent_capabilities():
    from jarvis.domain.subagent_roles import ROLE_ACCENTS, SPAWN_TOOL
    for key in ("icon", "accent", "badge"):
        assert len({getattr(role.visual, key) for role in ROLES}) == len(ROLES)
    for role in ROLES:
        assert role.visual.accent in ROLE_ACCENTS
        assert role.can_spawn == (SPAWN_TOOL in role.tools)
        assert not role.can_own_mission or role.can_spawn
        payload = role.as_dict()
        assert payload["visual"] == role.visual.as_dict() and payload["can_own_mission"] == role.can_own_mission
    owners = {role.id for role in ROLES if role.can_own_mission}
    assert owners == {"coder", "research-lead"}
    assert not role_for("interviewer").can_spawn  # « Vous ne lancez aucun autre agent »


def test_role_contract_fields_are_validated():
    from dataclasses import replace
    from jarvis.domain.subagent_roles import RoleVisual
    coder = role_for("coder")
    for changes in (
        {"can_own_mission": True, "can_spawn": False, "tools": ("Read",)},
        {"can_spawn": False},  # garde l'outil Agent
        {"work_methods": ("Pas Un Id",)},
        {"work_methods": ("a-method",), "default_work_method": "other-method"},
        {"loadout_role": "interviewer"},
        {"id": "unknown", "marker": "unknown"},
    ):
        with pytest.raises(ValueError):
            replace(coder, **changes)
    with pytest.raises(ValueError):
        RoleVisual(icon="code", accent="#ff0000", badge="DEV")
    with pytest.raises(ValueError):
        RoleVisual(icon="code", accent="amber", badge="dev")


def test_loadout_roles_of_the_registry_agree_with_what_the_hook_reads():
    # Pour un rôle dont le marqueur est déjà un rôle de loadout, le hook lit ce loadout-là ; `qa` emprunte
    # `reviewer` par contrat (câblage : Slice 04), et `[code] [reviewer]` garde son loadout d'aujourd'hui.
    for role in ROLES:
        read = routing_hook.read_loadout_role({"description": f"[general] [{role.marker}] x"})
        if role.loadout_role == role.marker:
            assert read == role.marker
        elif role.loadout_role is None:
            assert read is None
    assert role_for("qa") is None and subagent_roles.role_by_id("qa").loadout_role == "reviewer"
    assert routing_hook.read_loadout_role({"description": "[code] [reviewer] Relire"}) == "reviewer"


@pytest.mark.parametrize("marker", ["qa", "research-lead"])
def test_disabled_new_roles_change_nothing_live(marker):
    assert f"[{marker}]" not in brain_rules()
    assert with_role_instructions("Consigne.", marker) is None
    description = f"[code] [{marker}] Relire le diff"
    # Rôle annoncé, libellé et loadout : exactement ceux d'avant la définition du rôle.
    assert routing_hook.read_role({"description": description}) is None
    assert routing_hook.strip_profile(description) == f"[{marker}] Relire le diff"
    assert routing_hook.read_loadout_role({"description": description}) is None
    assert routing_hook.read_loadout_role({"description": description, "prompt": "[code] [coder] x"}) == "coder"
    assert routing_hook.read_profile({"description": description}) == "code"
