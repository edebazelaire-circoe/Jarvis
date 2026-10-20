"""Hook `PreToolUse`, billets de relais et règles pures du runtime des relations (Slice 06).

Le hook reste court et hors ligne : il appose l'identité de l'appelant sur les outils de relation, réclame le
billet d'un relais préparé pour `[relais]` et appose le paquet sur la consigne du successeur. Aucun réseau.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from jarvis.domain import agent_markers
from jarvis.domain.agent_orchestration import MissionDecision, decide_mission
from jarvis.domain.agent_relations import AgentRelation, AgentRelationKind as K, HandoffPacket, RelationError
from jarvis.domain.agent_relations import ParticipantPosition as P
from jarvis.domain.agent_relations import RelationOutcome, RelationParticipant
from jarvis.domain.missions import AgentInstance, Mission, MissionStatus
from jarvis.domain import relation_runtime as rr
from jarvis.domain.subagent_roles import role_for
from jarvis.runtime import agent_handoffs, routing_hook
from tests.unit.test_routing_hook_orchestration import call, facts, section, trace

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
ORCH = Path(__file__).resolve().parents[2]


def packet() -> HandoffPacket:
    return HandoffPacket(objective="Finir", completed_work="Cause trouvée", recommended_next_action="Corriger",
                         key_decisions=("garder l'API",), open_points=(), artifact_refs=("art_1",))


def ticket(handoff_id="hof_0123456789ab", agent="agentA", expires_ms=None) -> agent_handoffs.HandoffTicket:
    return agent_handoffs.HandoffTicket(
        handoff_id=handoff_id, mission_id="mis_toolu_A", predecessor_agent_id=agent, purpose="Contexte neuf",
        packet=packet(), expires_at_ms=expires_ms or int(time.time() * 1000) + 60_000)


def relation_call(tool: str, tool_input: dict, *, agent_id: str | None = None) -> dict:
    event = {"hook_event_name": "PreToolUse", "tool_name": f"mcp__jarvis-workspace__{tool}", "tool_use_id": "toolu_R",
             "tool_input": tool_input}
    if agent_id:
        event["agent_id"] = agent_id
        event["agent_type"] = "general-purpose"
    return event


# ------------------------------------------------------------------ identité apposée


def test_the_hook_stamps_the_real_caller_and_overwrites_a_forged_one(tmp_path):
    forged = {"kind": "qa", "purpose": "x", rr.CALLER_STAMP_KEY: {"stamped": True, "agent_id": "someone_else"}}
    out = section(routing_hook.run(relation_call("relation_open", forged, agent_id="a2a69a1d01cba9282"), tmp_path))
    assert out["permissionDecision"] == "allow"
    stamp = out["updatedInput"][rr.CALLER_STAMP_KEY]
    assert stamp == {"stamped": True, "agent_id": "a2a69a1d01cba9282", "agent_type": "general-purpose"}
    assert out["updatedInput"]["kind"] == "qa"
    brain = section(routing_hook.run(relation_call("relation_read", {"relation_id": "rel_1"}), tmp_path))
    assert brain["updatedInput"][rr.CALLER_STAMP_KEY]["agent_id"] is None  # le cerveau : apposé, sans agent
    [line, _] = trace(tmp_path, "agent.relation_call")
    assert line["data"]["caller_agent_id"] == "a2a69a1d01cba9282"
    # Aucun fait de déclaration pour un outil de relation : seul `Agent` en dépose.
    assert facts(tmp_path) == []


def test_other_tools_of_the_server_are_left_alone(tmp_path):
    assert routing_hook.run(relation_call("board_list", {}), tmp_path) == {}


def test_the_mcp_server_refuses_an_unstamped_call_with_an_actionable_reason():
    with pytest.raises(RelationError) as refused:
        rr.read_caller_stamp({})
    assert refused.value.code == "relation_caller_unstamped"
    assert "relancer JARVIS" in rr.actionable(refused.value.code, str(refused.value))
    with pytest.raises(RelationError):
        rr.read_caller_stamp({rr.CALLER_STAMP_KEY: {"stamped": True, "agent_id": "../etc"}})


# ------------------------------------------------------------------ [relais]


def test_relais_is_an_orchestration_modifier_read_after_the_role_only():
    head = agent_markers.parse_head("[code] [coder] [relais] Suite du correctif")
    assert (head.role, head.handoff, head.label) == ("coder", True, "Suite du correctif")
    assert not agent_markers.parse_head("[code] [relais] Suite").handoff  # sans rôle : reste dans le libellé
    coder = role_for("coder")
    head = agent_markers.parse_head("[code] [coder] [relais] Suite")
    assert decide_mission(head, coder, tool_use_id="t", nested=True) == MissionDecision(mission_owner=True,
                                                                                         handoff=True)
    refused = decide_mission(head, coder, tool_use_id="t", nested=False)  # le cerveau ne passe pas de relais
    assert (refused.refused, refused.mission_id) == ("handoff_from_brain", "mis_t")
    research = agent_markers.parse_head("[general] [research] [relais] Suite")
    assert decide_mission(research, role_for("research"), tool_use_id="t", nested=True).refused == \
        "role_cannot_own_mission"


def test_relais_without_a_prepared_handoff_is_denied_with_what_to_do(tmp_path):
    out = section(routing_hook.run(call("[code] [coder] [relais] Suite", agent_id="agentA"), tmp_path))
    assert out["permissionDecision"] == "deny" and "relation_handoff" in out["permissionDecisionReason"]
    assert facts(tmp_path) == []
    assert trace(tmp_path, "agent.handoff.failed")[0]["data"]["code"] == "handoff_ticket_missing"


def test_relais_claims_the_ticket_once_declares_the_successor_and_hands_it_the_packet(tmp_path):
    agent_handoffs.write_ticket(tmp_path, ticket())
    out = section(routing_hook.run(call("[code] [coder] [relais] Suite", agent_id="agentA", tool_use_id="toolu_S"),
                                   tmp_path))
    prompt = out["updatedInput"]["prompt"]
    assert rr.HANDOFF_MARK in prompt and "Cause trouvée" in prompt and "garder l'API" in prompt
    assert prompt.count(rr.RELATIONS_MARK) == 1  # le successeur est Mission Owner : il a la boîte à outils
    assert "relais" in prompt.split(rr.HANDOFF_MARK)[0]  # la responsabilité de mission dit le relais
    [fact] = facts(tmp_path)
    assert (fact.mission_owner, fact.mission_id, fact.handoff_id) == (True, "mis_toolu_A", "hof_0123456789ab")
    # Réclamé une fois : un second appel ne le retrouve pas.
    again = section(routing_hook.run(call("[code] [coder] [relais] Encore", agent_id="agentA", tool_use_id="toolu_T"),
                                     tmp_path))
    assert again["permissionDecision"] == "deny"
    # Le billet d'un autre prédécesseur n'est jamais réclamé.
    agent_handoffs.write_ticket(tmp_path, ticket("hof_bbbbbbbbbbbb", agent="agentB"))
    assert agent_handoffs.claim(tmp_path, "agentA") is None


def test_an_expired_or_unreadable_ticket_is_never_claimed(tmp_path):
    agent_handoffs.write_ticket(tmp_path, ticket(expires_ms=int(time.time() * 1000) - 1))
    assert agent_handoffs.claim(tmp_path, "agentA") is None
    (agent_handoffs.folder(tmp_path) / "hof_cccccccccccc.json").write_text("{pas du json", encoding="utf-8")
    assert agent_handoffs.claim(tmp_path, "agentA") is None
    old = agent_handoffs.folder(tmp_path) / "hof_cccccccccccc.json"
    os.utime(old, (time.time() - agent_handoffs.RETENTION_S - 10,) * 2)
    assert agent_handoffs.prune(tmp_path) >= 1 and not old.exists()


def test_the_ticket_folder_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_handoffs, "MAX_FILES", 2)
    agent_handoffs.write_ticket(tmp_path, ticket("hof_aaaaaaaaaaa1"))
    agent_handoffs.write_ticket(tmp_path, ticket("hof_aaaaaaaaaaa2"))
    with pytest.raises(agent_handoffs.HandoffTicketError):
        agent_handoffs.write_ticket(tmp_path, ticket("hof_aaaaaaaaaaa3"))
    with pytest.raises(agent_handoffs.HandoffTicketError):
        agent_handoffs.write_ticket(tmp_path, ticket("../../evil"))


def test_the_qa_reviewer_and_only_owners_get_their_relation_blocks(tmp_path):
    qa = section(routing_hook.run(call("[code] [qa] Relire", agent_id="agentA"), tmp_path))["updatedInput"]["prompt"]
    assert rr.REVIEWER_MARK in qa and rr.RELATIONS_MARK not in qa
    member = section(routing_hook.run(call("[code] [coder] Aider", agent_id="agentA", tool_use_id="t2"),
                                      tmp_path))["updatedInput"]["prompt"]
    assert rr.RELATIONS_MARK not in member and rr.REVIEWER_MARK not in member


def test_the_relation_blocks_teach_tools_not_a_protocol():
    for text in (rr.relations_brief(), rr.reviewer_brief()):
        lowered = text.lower()
        assert not any(word in lowered for word in ("round", "tour 1", "étape 1", "phase", "d'abord vous devez"))
    assert "aucune n'impose de tours" in rr.relations_brief()
    for tool in rr.RELATION_TOOLS:
        assert tool in rr.relations_brief(), tool


def test_the_real_hook_process_stamps_a_relation_call_offline(tmp_path):
    """Le vrai sous-processus `jarvis routing-hook` : sortie 0, identité apposée, sans réseau."""

    event = relation_call("relation_post", {"relation_id": "rel_1", "text": "Bonjour"}, agent_id="agentZ")
    done = subprocess.run([sys.executable, "-m", "jarvis", "routing-hook", "--runtime-root", str(tmp_path)],
                          input=json.dumps(event), capture_output=True, text=True, encoding="utf-8", cwd=ORCH,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    stamp = json.loads(done.stdout)["hookSpecificOutput"]["updatedInput"][rr.CALLER_STAMP_KEY]
    assert stamp["agent_id"] == "agentZ"


# ------------------------------------------------------------------ règles pures


def inst(instance_id, *, mission="mis_A", owner=False, role="coder", minute=0):
    return AgentInstance(instance_id=instance_id, work_source="claude", work_external_id=f"w_{instance_id}",
                         role_id=role, created_at=T0, mission_id=mission, mission_owner=owner)


def rel(kind, pairs, *, creator="A"):
    return AgentRelation(relation_id="rel_x", kind=kind, mission_id="mis_A",
                         participants=tuple(RelationParticipant(i, p) for i, p in pairs), purpose="But",
                         created_at=T0, created_by_instance_id=creator)


MISSIONS = {"mis_A": Mission(mission_id="mis_A", objective="O", owner_instance_id="A", created_at=T0),
            "mis_S": Mission(mission_id="mis_S", objective="S", owner_instance_id="L", created_at=T0,
                             parent_mission_id="mis_A", root_mission_id="mis_A")}


def test_authority_owner_and_ancestor_owner_open_and_the_reviewer_opens_its_own_qa():
    duel = rel(K.ADVERSARY, [("B", P.PRODUCER), ("C", P.PRODUCER)])
    rr.check_open_authority(inst("A", owner=True), duel, MISSIONS)
    sub = AgentRelation(relation_id="rel_y", kind=K.COMMUNICATION, mission_id="mis_S",
                        participants=(RelationParticipant("R1", P.MEMBER), RelationParticipant("R2", P.MEMBER)),
                        purpose="Sous-équipe", created_at=T0)
    rr.check_open_authority(inst("A", owner=True), sub, MISSIONS)  # le propriétaire parent supervise (D04)
    with pytest.raises(RelationError):
        rr.check_open_authority(inst("B"), duel, MISSIONS)
    review = rel(K.QA, [("Q", P.REVIEWER), ("B", P.REVIEWED)], creator="Q")
    rr.check_open_authority(inst("Q", role="qa"), review, MISSIONS)
    closed = {**MISSIONS, "mis_A": Mission(mission_id="mis_A", objective="O", owner_instance_id="A", created_at=T0,
                                           status=MissionStatus.COMPLETED, closed_at=T0)}
    with pytest.raises(RelationError) as refused:
        rr.check_open_authority(inst("A", owner=True), duel, closed)
    assert refused.value.code == "mission_closed"


def test_close_authority_keeps_core_closed_kinds_and_member_endings():
    talk = rel(K.COMMUNICATION, [("B", P.MEMBER), ("C", P.MEMBER)])
    rr.check_close_authority(inst("C"), talk, RelationOutcome.ENDED, MISSIONS)
    with pytest.raises(RelationError):
        rr.check_close_authority(inst("D"), talk, RelationOutcome.ENDED, MISSIONS)
    handoff = AgentRelation(relation_id="rel_h", kind=K.HANDOFF, mission_id="mis_A",
                            participants=(RelationParticipant("A", P.PREDECESSOR), RelationParticipant("S", P.SUCCESSOR)),
                            purpose="Relais", created_at=T0, handoff=packet())
    with pytest.raises(RelationError) as refused:
        rr.check_close_authority(inst("A", owner=True), handoff, RelationOutcome.WITHDRAWN, MISSIONS)
    assert refused.value.code == "relation_closed_by_core"


def test_the_successor_relation_and_the_pending_handoff_expire():
    pending = rr.PendingHandoff(handoff_id="hof_1", mission_id="mis_A", predecessor_instance_id="A", purpose="Relais",
                                packet=packet(), prepared_at=T0)
    successor = inst("S", owner=True)
    relation = rr.handoff_relation(pending, relation_id="rel_h", successor=successor, at=T0)
    assert relation.endpoints() == ("A", "S") and relation.handoff == packet()
    with pytest.raises(RelationError):
        rr.handoff_relation(pending, relation_id="rel_h", successor=inst("S"), at=T0)  # pas Mission Owner
    assert not pending.expired(T0) and pending.expired(pending.expires_at)


def test_a_summary_names_kind_position_and_state():
    review = rel(K.QA, [("Q", P.REVIEWER), ("B", P.REVIEWED)])
    assert rr.relation_summary(review, "Q") == "QA (relecteur) rel_x ouverte"
    assert rr.relation_summary(review.close(RelationOutcome.APPROVED, T0, closed_by="Q"), "B") == \
        "QA (relu) rel_x close : approved"
