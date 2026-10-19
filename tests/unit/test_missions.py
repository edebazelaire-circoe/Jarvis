"""Missions, sous-missions et instances d'agent : identité, immuabilité, propriété récursive sans cycle.

Critères de la Slice 01 prouvés ici : le rôle d'une instance est explicite et immuable ; Mission Owner est un
statut d'instance et non un rôle ; la propriété d'une sous-mission se représente récursivement sans cycle ;
l'éphémère est une donnée déclarée, jamais déduite d'une durée ; aucun statut d'exécution n'est dupliqué.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.domain.agent_markers import declaration_from_tool_input
from jarvis.domain.missions import (
    IMMUTABLE_INSTANCE_FIELDS, MAX_MISSION_DEPTH, AgentInstance, Mission, MissionError, MissionStatus,
    check_dossier_path, check_mission_tree, instance_from_declaration, reconcile_instance, retained_in_history,
    transfer_ownership,
)
from jarvis.domain.subagent_roles import ROLES
from jarvis.domain.work_state import EPHEMERAL_WORK_STATUSES, WorkStatus

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)


def instance(instance_id: str = "i-dev", **changes) -> AgentInstance:
    values = {
        "instance_id": instance_id, "work_source": "claude", "work_external_id": f"toolu-{instance_id}",
        "role_id": "coder", "created_at": T0, **changes,
    }
    return AgentInstance(**values)


def mission(mission_id: str = "m-root", owner: str = "i-dev", **changes) -> Mission:
    return Mission(mission_id=mission_id, objective="Corriger le bug d'export", owner_instance_id=owner,
                   created_at=T0, **changes)


# ---------------------------------------------------------------- rôle et instance


def test_role_is_explicit_and_frozen_on_the_instance():
    agent = instance()
    with pytest.raises(FrozenInstanceError):
        agent.role_id = "research"  # type: ignore[misc]
    with pytest.raises(MissionError) as error:
        instance(role_id="")
    assert error.value.field == "role_id"
    with pytest.raises(MissionError):
        instance(role_id="Développeur")  # un libellé n'est pas un id


def test_no_execution_status_lives_on_the_instance():
    names = {item.name for item in fields(AgentInstance)}
    assert not names & {"status", "progress", "progress_fraction", "activity", "ended_at", "error_class"}
    assert instance().work_identity == ("claude", "toolu-i-dev")


@pytest.mark.parametrize("name", IMMUTABLE_INSTANCE_FIELDS)
def test_reconciling_a_changed_immutable_field_is_refused(name):
    current = instance(mission_id="m-root")
    other = {
        "work_source": "codex", "work_external_id": "toolu-x", "role_id": "research", "role_marker": "research",
        "ephemeral": True, "mission_id": "m-other", "mission_owner": True, "parent_instance_id": "i-parent",
    }[name]
    incoming = replace(current, **{name: other})
    with pytest.raises(MissionError) as error:
        reconcile_instance(current, incoming)
    assert error.value.code == "immutable_field" and error.value.field == name


def test_reconciling_the_same_declaration_is_idempotent_and_only_enriches_the_label():
    current = instance()
    assert reconcile_instance(current, instance()) is current
    enriched = reconcile_instance(current, instance(label="Corriger l'export", created_at=T0 + timedelta(seconds=5)))
    assert enriched.label == "Corriger l'export" and enriched.created_at == T0
    assert reconcile_instance(enriched, instance(label="Autre")).label == "Corriger l'export"


def test_an_unknown_role_id_is_kept_and_degrades_visibly():
    agent = instance(role_id="unknown", role_marker="zorg")
    assert agent.role_known is False
    retired = instance(role_id="ancien-role")  # id d'un rôle que le registre ne connaît plus
    assert retired.role_known is False and retired.role_id == "ancien-role"
    assert instance(role_id="undeclared").role_known is False
    assert instance().role_known is True


# ---------------------------------------------------------------- Mission Owner


def test_mission_owner_is_a_status_not_a_role():
    owner = instance(mission_id="m-root", mission_owner=True)
    assert owner.role_id == "coder" and owner.mission_owner is True
    assert all(role.id not in {"mission-owner", "owner", "orchestrator"} for role in ROLES)


def test_only_a_capable_role_can_own_a_mission():
    with pytest.raises(MissionError) as error:
        instance(role_id="interviewer", mission_id="m-root", mission_owner=True)
    assert error.value.code == "role_cannot_own_mission"
    with pytest.raises(MissionError):
        instance(role_id="unknown", role_marker="zorg", mission_id="m-root", mission_owner=True)
    assert instance(role_id="research-lead", mission_id="m-r", mission_owner=True).mission_owner
    with pytest.raises(MissionError):
        instance(mission_owner=True)  # sans mission


def test_an_ephemeral_instance_cannot_own_a_mission():
    with pytest.raises(MissionError) as error:
        instance(ephemeral=True, mission_id="m-root", mission_owner=True)
    assert error.value.code == "ephemeral_mission_owner"
    assert instance(ephemeral=True).ephemeral  # un développeur éphémère pour une coquille : valide


def test_ownership_changes_only_through_an_explicit_handoff():
    first = instance("i-dev-1", mission_id="m-root", mission_owner=True)
    second = instance("i-dev-2", mission_id="m-root", mission_owner=True)
    root = mission(owner=first.instance_id)
    moved = transfer_ownership(root, second, handoff_ref="h-1")
    assert moved.owner_instance_id == "i-dev-2" and root.owner_instance_id == "i-dev-1"
    with pytest.raises(MissionError):
        transfer_ownership(root, second, handoff_ref="")
    with pytest.raises(MissionError):
        transfer_ownership(root, instance("i-helper", mission_id="m-root"), handoff_ref="h-2")
    with pytest.raises(MissionError):
        transfer_ownership(root.close(MissionStatus.COMPLETED, T0), second, handoff_ref="h-3")


# ---------------------------------------------------------------- sous-missions


def _team():
    lead = instance("i-dev", mission_id="m-root", mission_owner=True)
    research_lead = instance("i-rl", role_id="research-lead", mission_id="m-research", mission_owner=True,
                             parent_instance_id="i-dev")
    web = instance("i-web", role_id="web-research", mission_id="m-research", parent_instance_id="i-rl")
    root = mission("m-root", owner="i-dev")
    sub = mission("m-research", owner="i-rl", parent_mission_id="m-root", root_mission_id="m-root")
    return [root, sub], [lead, research_lead, web]


def test_sub_mission_ownership_is_recursive_and_consistent():
    missions, instances = _team()
    check_mission_tree(missions, instances)
    assert missions[1].is_root is False and missions[0].root_mission_id == "m-root"


def test_a_mission_cycle_is_refused():
    a = mission("m-a", parent_mission_id="m-b", root_mission_id="m-a2")
    b = mission("m-b", parent_mission_id="m-a", root_mission_id="m-a2")
    owner = instance(mission_id="m-a", mission_owner=True)
    with pytest.raises(MissionError) as error:
        check_mission_tree([a, b], [owner])
    assert error.value.code == "mission_cycle"
    with pytest.raises(MissionError):
        mission("m-a", parent_mission_id="m-a", root_mission_id="m-x")


def test_an_instance_cycle_and_a_missing_parent_are_refused():
    missions, _ = _team()
    lead = instance("i-dev", mission_id="m-root", mission_owner=True, parent_instance_id="i-rl")
    rl = instance("i-rl", role_id="research-lead", mission_id="m-research", mission_owner=True,
                  parent_instance_id="i-dev")
    with pytest.raises(MissionError) as error:
        check_mission_tree(missions, [lead, rl])
    assert error.value.code == "mission_cycle"
    orphan = mission("m-orphan", owner="i-dev", parent_mission_id="m-ghost", root_mission_id="m-ghost")
    with pytest.raises(MissionError) as error:
        check_mission_tree([orphan], [instance(mission_id="m-orphan", mission_owner=True)])
    assert error.value.code == "mission_parent_missing"


def test_a_wrong_root_or_owner_is_refused():
    missions, instances = _team()
    wrong_root = mission("m-research", owner="i-rl", parent_mission_id="m-root", root_mission_id="m-research2")
    with pytest.raises(MissionError):
        check_mission_tree([missions[0], wrong_root], instances)
    not_owner = mission("m-research", owner="i-web", parent_mission_id="m-root", root_mission_id="m-root")
    with pytest.raises(MissionError) as error:
        check_mission_tree([missions[0], not_owner], instances)
    assert error.value.code == "ownership_invalid"


def test_the_depth_is_bounded():
    chain = [mission("m-0", owner="i-0")]
    owners = [instance("i-0", mission_id="m-0", mission_owner=True)]
    for depth in range(1, MAX_MISSION_DEPTH + 1):
        chain.append(mission(f"m-{depth}", owner=f"i-{depth}", parent_mission_id=f"m-{depth - 1}",
                             root_mission_id="m-0"))
        owners.append(instance(f"i-{depth}", mission_id=f"m-{depth}", mission_owner=True))
    with pytest.raises(MissionError) as error:
        check_mission_tree(chain, owners)
    assert error.value.code == "mission_too_deep"
    check_mission_tree(chain[:MAX_MISSION_DEPTH], owners[:MAX_MISSION_DEPTH])


# ---------------------------------------------------------------- mission


def test_a_mission_references_the_shared_dossier_by_path():
    assert mission(dossier_path="missions/belle-vidéo-20261020/mission.md").dossier_path
    for bad in ("missions/../mission.md", "C:/x/mission.md", "missions/x/mission.md",
                "missions/sujet-20261020/notes.md", "missions\\sujet-20261020\\mission.md", "/missions/a-20261020/mission.md"):
        with pytest.raises(MissionError):
            check_dossier_path(bad)


def test_the_mission_lifecycle_is_open_then_closed_once():
    root = mission()
    assert root.status is MissionStatus.OPEN and root.closed_at is None
    done = root.close(MissionStatus.COMPLETED, T0 + timedelta(minutes=3))
    assert done.close(MissionStatus.COMPLETED, T0 + timedelta(minutes=3)) is done
    with pytest.raises(MissionError) as error:
        done.close(MissionStatus.FAILED, T0 + timedelta(minutes=4))
    assert error.value.code == "mission_closed"
    with pytest.raises(MissionError):
        root.close(MissionStatus.OPEN, T0)
    with pytest.raises(MissionError):
        mission(status=MissionStatus.COMPLETED)  # close sans date
    with pytest.raises(MissionError):
        root.close(MissionStatus.COMPLETED, T0 - timedelta(seconds=1))


def test_objective_is_bounded_and_required():
    with pytest.raises(MissionError):
        Mission(mission_id="m", objective="  ", owner_instance_id="i", created_at=T0)
    with pytest.raises(MissionError):
        Mission(mission_id="m", objective="x" * 1_001, owner_instance_id="i", created_at=T0)
    with pytest.raises(MissionError):
        Mission(mission_id="m", objective="x", owner_instance_id="i", created_at=datetime(2026, 10, 20))


# ---------------------------------------------------------------- fil


def test_mission_and_instance_round_trip_and_reject_unknown_fields():
    missions, instances = _team()
    for item in missions:
        assert Mission.from_payload(item.to_payload()) == item
    for item in instances:
        assert AgentInstance.from_payload(item.to_payload()) == item
    with pytest.raises(MissionError):
        Mission.from_payload({**missions[0].to_payload(), "steps": []})
    with pytest.raises(MissionError):
        AgentInstance.from_payload({**instances[0].to_payload(), "status": "running"})
    with pytest.raises(MissionError):
        AgentInstance.from_payload({"instance_id": "i"})


# ---------------------------------------------------------------- éphémère


def test_ephemeral_is_declared_data_not_inferred_from_duration():
    quick = instance_from_declaration(
        declaration_from_tool_input({"description": "[éphémère] [code] [coder] Corriger la coquille"}),
        instance_id="i-typo", work_source="claude", work_external_id="toolu-typo", created_at=T0,
    )
    assert quick.ephemeral is True and quick.role_id == "coder" and quick.label == "Corriger la coquille"
    long_but_declared = instance_from_declaration(
        declaration_from_tool_input({"description": "[code] [coder] Refondre l'export"}),
        instance_id="i-long", work_source="claude", work_external_id="toolu-long", created_at=T0,
    )
    assert long_but_declared.ephemeral is False  # la durée n'y change rien : aucun champ de durée n'existe


def test_an_ephemeral_instance_is_kept_in_history_only_when_its_work_ends_badly():
    quick = instance(ephemeral=True)
    for status in WorkStatus:
        assert retained_in_history(quick, status) is (status not in EPHEMERAL_WORK_STATUSES), status
        assert retained_in_history(instance(), status) is True


def test_a_declaration_maps_aliases_and_unknown_roles_explicitly():
    review = instance_from_declaration(
        declaration_from_tool_input({"description": "[code] [reviewer] Relire"}),
        instance_id="i-qa", work_source="claude", work_external_id="toolu-qa", created_at=T0,
    )
    assert (review.role_id, review.role_marker) == ("qa", "reviewer")
    bare = instance_from_declaration(
        declaration_from_tool_input({"description": "Relire le diff"}),
        instance_id="i-bare", work_source="claude", work_external_id="toolu-bare", created_at=T0,
    )
    assert (bare.role_id, bare.role_marker, bare.role_known) == ("undeclared", None, False)
