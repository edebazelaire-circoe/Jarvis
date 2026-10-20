"""Reprise QA de la Slice 06 : B1 et notes N1 à N8, mutants M15 et M19.

Chaque test nomme le constat qu'il ferme. Base temporaire, vrai service, vrai hook ; aucun réseau.
"""

from __future__ import annotations

from datetime import timedelta
import io
import json
import re
import threading
import time

import pytest

from jarvis.core.mission_history import (
    MISSION_HISTORY_MESSAGE_AFTER_CLOSE_KIND, MISSION_HISTORY_RELATION_WITHDRAWN_KIND,
)
from jarvis.domain import relation_runtime as rr
from jarvis.domain.agent_relations import AgentRelationKind as K
from jarvis.domain.agent_relations import ParticipantPosition as P
from jarvis.domain.agent_relations import RelationError, RelationMessageType as T, RelationOutcome as R
from jarvis.domain.agent_relations import check_collaboration_text
from jarvis.domain.mission_history import DeclarationOutcome as O
from jarvis.domain.missions import MissionStatus
from jarvis.runtime import agent_handoffs, hook_failsafe, routing_hook
from jarvis.runtime.relations_mcp_tools import RelationTools
from tests.fakes.mission_history import SOURCE, at
from tests.unit.test_relations_runtime_hook import ticket
from tests.unit.test_relations_runtime_service import (  # noqa: F401 - fixture
    core, declare_successor, end, member, owner, packet, run, team, w,
)
from tests.unit.test_routing_hook_orchestration import call, facts, section, trace


# ------------------------------------------------------------------ B1 : un [relais] impossible est refusé


@pytest.mark.parametrize("description, agent_id", [
    ("[code] [qa] [relais] Suite", "agentA"),                    # rôle sans can_own_mission
    ("[éphémère] [code] [coder] [relais] Suite", "agentA"),      # éphémère
    ("[code] [coder] [mission] [relais] Suite", "agentA"),       # [mission] en plus
    ("[code] [coder] [relais] Suite", None),                     # depuis le cerveau
])
def test_an_impossible_relais_is_denied_before_the_ticket_is_claimed(tmp_path, description, agent_id):
    prepared = ticket()
    agent_handoffs.write_ticket(tmp_path, prepared)
    out = section(routing_hook.run(call(description, agent_id=agent_id), tmp_path))
    assert out["permissionDecision"] == "deny"
    assert "coder, research-lead" in out["permissionDecisionReason"] and "[éphémère] ni [mission]" in \
        out["permissionDecisionReason"]
    assert facts(tmp_path) == []  # rien n'est déclaré
    assert trace(tmp_path, "agent.handoff.failed")[0]["data"]["code"] != "handoff_ticket_claimed"
    # Le billet attend l'appel corrigé.
    assert agent_handoffs.claim(tmp_path, "agentA").handoff_id == prepared.handoff_id


async def test_relation_handoff_says_the_successor_rule_when_preparing():
    async def fake_call(tool, method, route, **kwargs):
        return 200, {"handoff": {"handoff_id": "hof_x", "mission_id": "mis_A", "expires_at": "2026-10-20T10:00:00"}}

    tools = RelationTools(fake_call, lambda code, message: RuntimeError(message))
    from jarvis.runtime.relations_mcp_tools import CURRENT_CALLER

    token = CURRENT_CALLER.set(rr.caller_stamp({"agent_id": "agentA"}))
    try:
        result = await tools.handoff(purpose="p", objective="o", completed_work="c", recommended_next_action="n")
    finally:
        CURRENT_CALLER.reset(token)
    assert "coder, research-lead" in result["next"] and "[éphémère] ni [mission]" in result["next"]


# ------------------------------------------------------------------ N1 : une seule réclamation, Windows compris


def test_concurrent_claims_never_take_one_ticket_twice(tmp_path):
    for round_ in range(15):
        root = tmp_path / f"r{round_}"
        agent_handoffs.write_ticket(root, ticket(f"hof_race{round_:08d}"))
        barrier, results = threading.Barrier(6), []

        def claim():
            barrier.wait()
            results.append(agent_handoffs.claim(root, "agentA"))

        workers = [threading.Thread(target=claim) for _ in range(6)]
        [worker.start() for worker in workers]
        [worker.join() for worker in workers]
        assert sum(1 for item in results if item is not None) == 1, round_
        # N6 : le billet réclamé n'est plus sur disque (effacé à la réclamation, ou au plus tard au prochain
        # élagage si un lecteur concurrent le tenait ouvert sous Windows) ; seul reste le marqueur.
        agent_handoffs.prune(root)
        assert sorted(path.suffix for path in agent_handoffs.folder(root).iterdir()) == [".claim"]


def test_expired_tickets_are_pruned_at_the_next_claim(tmp_path):
    agent_handoffs.write_ticket(tmp_path, ticket("hof_expired000001", expires_ms=int(time.time() * 1000) - 1))
    assert agent_handoffs.claim(tmp_path, "agentA") is None
    assert list(agent_handoffs.folder(tmp_path).iterdir()) == []


# ------------------------------------------------------------------ N2 : échec fermé, version d'apposition


def test_a_crashing_hook_fails_closed_for_relation_tools_and_open_for_others(tmp_path, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("hook cassé")

    monkeypatch.setattr(routing_hook, "run", boom)
    for name, closed in (("mcp__jarvis-workspace__relation_post", True), ("Agent", False)):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": name, "tool_input": {}})))
        assert routing_hook.main(["--runtime-root", str(tmp_path)]) == 0
        written = capsys.readouterr().out
        if closed:
            assert json.loads(written)["hookSpecificOutput"]["permissionDecision"] == "deny"
        else:
            assert written == ""
    from jarvis.runtime.journal import read_jsonl_tail

    failures = [row for row in read_jsonl_tail(tmp_path / "errors.jsonl", limit=20)
                if row.get("kind") == "agent.routing.failed"]
    assert [row["data"]["fail_closed"] for row in failures] == [True, False]


def test_the_standalone_failsafe_refuses_only_relation_tools(capsys):
    assert hook_failsafe.RELATION_TOOL_PREFIX == rr.RELATION_TOOL_PREFIX
    hook_failsafe.main(json.dumps({"tool_name": "mcp__jarvis-workspace__relation_open"}))
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    hook_failsafe.main(json.dumps({"tool_name": "Agent"}))
    hook_failsafe.main("pas du json")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("stamp", [
    {"stamped": True, "agent_id": "agentA"},                                 # hook ancien : pas de version
    {"stamped": True, "hook": "relation-stamp@0", "agent_id": "agentA"},     # version inconnue
    {"stamped": True, "hook": None, "agent_id": "agentA"},
])
def test_a_stamp_without_the_current_hook_version_is_refused(stamp):
    with pytest.raises(RelationError) as refused:
        rr.read_caller_stamp({rr.CALLER_STAMP_KEY: stamp})
    assert refused.value.code == "relation_caller_unstamped"
    assert rr.read_caller_stamp({rr.CALLER_STAMP_KEY: rr.caller_stamp({"agent_id": "agentA"})}).agent_id == "agentA"


# ------------------------------------------------------------------ N3 : matcher ancré, comportement


@pytest.mark.parametrize("tool, fires", [
    ("Agent", True), ("Task", True), ("mcp__jarvis-workspace__relation_open", True),
    ("mcp__jarvis-workspace__relation_handoff", True),
    ("Glob", False), ("TaskStop", False), ("TaskOutput", False), ("SendMessage", False), ("AgentX", False),
    ("mcp__jarvis-workspace__board_list", False), ("xmcp__jarvis-workspace__relation_open", False),
])
def test_the_hook_matcher_fires_only_on_its_tools(tool, fires):
    # Le CLI compare le matcher comme une expression régulière (constaté sur le CLI 2.1.304 avec ce motif ancré).
    assert bool(re.search(routing_hook.HOOK_MATCHER, tool)) is fires


# ------------------------------------------------------------------ N4 : grâce de 10 min, puis retrait


async def test_a_closed_mission_takes_late_gestures_only_during_the_grace(core):
    await team(core)
    talk = await core.service.open_relation(caller=w("A"), kind=K.COMMUNICATION, purpose="Fin",
                                            participants=[(w("B"), P.MEMBER), (w("C"), P.MEMBER)])
    for key in ("B", "C", "Q"):
        await end(core, key, minute=1)
    await end(core, "A", minute=2)
    closed_at = (await core.store.get_mission("mis_A")).closed_at
    core.clock.minute += 5  # pendant la grâce
    await core.service.publish_message(caller=w("B"), relation_id=talk.relation_id, type=T.MESSAGE, text="Tardif")
    assert core.journal.kinds(MISSION_HISTORY_MESSAGE_AFTER_CLOSE_KIND)
    core.clock.minute += 6  # au-delà des 10 min
    assert core.clock.now() - closed_at > timedelta(seconds=rr.CLOSED_MISSION_GRACE_S)
    with pytest.raises(RelationError) as refused:
        await core.service.publish_message(caller=w("B"), relation_id=talk.relation_id, type=T.MESSAGE, text="Trop")
    assert refused.value.code == "mission_closed" and "10 min" in rr.actionable("mission_closed", "x")
    await core.service.sweep()
    withdrawn = await core.store.get_relation(talk.relation_id)
    assert (withdrawn.outcome, withdrawn.winner_instance_id, withdrawn.closed_by_instance_id) == (
        R.WITHDRAWN, None, None)
    assert core.journal.kinds(MISSION_HISTORY_RELATION_WITHDRAWN_KIND)[0]["relation_id"] == talk.relation_id


# ------------------------------------------------------------------ N5 : successeur d'un relais échoué


async def test_a_failed_successor_is_recorded_without_the_owner_flag_and_replays_identically(core):
    await owner(core, "A")
    result = await declare_successor(core, "S", "hof_doesnotexist")
    stored = await core.store.find_instance(*w("S"))
    assert result.outcome is O.RECORDED and stored.instance.mission_owner is False
    assert (await declare_successor(core, "S", "hof_doesnotexist")).outcome is O.DUPLICATE
    await run(core, "S", minute=0.5)
    await run(core, "A", minute=0.5)
    await end(core, "S", minute=1)  # la fin du successeur raté ne clôt rien : il n'est pas propriétaire
    assert (await core.store.get_mission("mis_A")).status is MissionStatus.OPEN


# ------------------------------------------------------------------ N7 : lecture restreinte


async def test_a_relation_is_read_by_its_participants_owners_and_the_brain_only(core):
    await team(core)
    qa = await core.service.open_relation(caller=w("Q"), kind=K.QA, purpose="Relire B",
                                          participants=[(w("Q"), P.REVIEWER), (w("B"), P.REVIEWED)])
    for reader in (w("Q"), w("B"), w("A"), None):
        relation, _thread, _ = await core.service.read_relation(qa.relation_id, caller=reader)
        assert relation.relation_id == qa.relation_id
    with pytest.raises(RelationError) as refused:
        await core.service.read_relation(qa.relation_id, caller=w("C"))
    assert refused.value.code == "relation_read_not_allowed"
    response = await core.client.get(f"/v1/missions/relations/{qa.relation_id}",
                                     params={"caller_work_source": SOURCE, "caller_work_external_id": "C"})
    body = await response.json()
    assert response.status == 403 and "Mission Owners" in body["error"]["message"]


# ------------------------------------------------------------------ N8 : <antThinking>


@pytest.mark.parametrize("text", ["<antThinking>x</antThinking>", "<ant_thinking>x", "< /antThinking >",
                                  "<ANT-THINKING>", "<antThinking>x"])
def test_ant_thinking_variants_are_private(text):
    with pytest.raises(RelationError) as refused:
        check_collaboration_text("text", text, 200)
    assert refused.value.code == "relation_private_content"


def test_words_starting_with_ant_stay_allowed():
    for text in ("<antenne>", "anthologie <a>", "[antThinking]"):
        check_collaboration_text("text", text, 200)


# ------------------------------------------------------------------ mutants M15 et M19


async def test_record_handoff_refuses_an_instance_that_already_exists(core):
    """M15 : un successeur déjà retenu n'est pas neuf ; rien n'est écrit de plus."""

    await owner(core, "A")
    pending = await core.service.prepare_handoff(caller=w("A"), purpose="Relais", packet=packet())
    first = await declare_successor(core, "S", pending.handoff_id)
    successor = first.instance
    owners_before = len((await core.store.mission_tree("mis_A")).ownership)
    relation = rr.handoff_relation(pending, relation_id="rel_m15", successor=successor, at=at(40))
    with pytest.raises(Exception) as refused:
        await core.store.record_handoff(successor, declaration=None, relation=relation, at=at(40), summary="s")
    assert getattr(refused.value, "code", None) == "handoff_successor_not_fresh"
    assert await core.store.get_relation("rel_m15") is None
    assert len((await core.store.mission_tree("mis_A")).ownership) == owners_before


async def test_a_qa_opened_by_neither_the_owner_nor_the_reviewer_is_refused(core):
    await team(core)
    with pytest.raises(RelationError) as refused:
        await core.service.open_relation(caller=w("C"), kind=K.QA, purpose="Pas à moi",
                                         participants=[(w("Q"), P.REVIEWER), (w("B"), P.REVIEWED)])
    assert refused.value.code == "relation_not_owner"
