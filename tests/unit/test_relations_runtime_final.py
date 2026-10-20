"""Dernière reprise QA de la Slice 06 : mutants R08, R16-R18, R22, R24, R29 et M15 ; import cassé dit ; balayage
de retrait non bloqué. Bases temporaires, vrais processus pour la réclamation et le filet de sécurité du hook."""

from __future__ import annotations

import functools
import json
import multiprocessing as mp
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

from aiohttp.test_utils import make_mocked_request
import pytest

from jarvis.domain import relation_runtime as rr
from jarvis.domain.agent_relations import AgentRelationKind as K
from jarvis.domain.agent_relations import ParticipantPosition as P
from jarvis.domain.agent_relations import RelationError, RelationMessageType as T, RelationOutcome as R
from jarvis.domain.missions import MissionStatus
from jarvis.runtime import agent_handoffs
from jarvis.runtime.relation_relay import RelationRelayError
from jarvis.runtime.relations_mcp_tools import CURRENT_CALLER, RelationTools
from tests.fakes.mission_history import SOURCE, at, instance
from tests.unit.test_relations_runtime_hook import ticket
from tests.unit.test_relations_runtime_relay import relay  # noqa: F401 - fixture
from tests.unit.test_relations_runtime_service import (  # noqa: F401 - fixture
    core, end, member, owner, packet, run, team, w,
)

ORCH = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ R08 : exclusivité en multiprocessus


def _claim_worker(module_file: str, root: str, barrier, queue) -> None:
    # Le module est chargé depuis le fichier même du parent : un mutant substitué au module est celui éprouvé.
    import importlib.util

    spec = importlib.util.spec_from_file_location("jarvis.runtime.agent_handoffs", module_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules["jarvis.runtime.agent_handoffs"] = module
    spec.loader.exec_module(module)
    barrier.wait()
    queue.put("claimed" if module.claim(Path(root), "agentA") is not None else "none")


def test_concurrent_processes_claim_a_ticket_once(tmp_path):
    context = mp.get_context("spawn")
    for round_ in range(6):
        root = tmp_path / f"p{round_}"
        agent_handoffs.write_ticket(root, ticket(f"hof_proc{round_:08d}"))
        barrier, queue = context.Barrier(4), context.Queue()
        workers = [context.Process(target=_claim_worker, args=(agent_handoffs.__file__, str(root), barrier, queue))
                   for _ in range(4)]
        [worker.start() for worker in workers]
        [worker.join(timeout=60) for worker in workers]
        results = sorted(queue.get(timeout=10) for _ in workers)
        assert results == ["claimed", "none", "none", "none"], (round_, results)


# ------------------------------------------------------------------ R16-R18 : le lecteur suit toute la chaîne


async def test_the_mcp_tool_sends_the_reader_to_the_control_center():
    seen = {}

    async def fake_call(tool, method, route, *, params=None, **kwargs):
        seen.update(params or {})
        return 200, {"relation": {"relation_id": "rel_1", "kind": "qa", "mission_id": "m", "purpose": "p",
                                  "status": "open", "participants": []}, "messages": [], "participants": []}

    tools = RelationTools(fake_call, lambda code, message: RuntimeError(message))
    token = CURRENT_CALLER.set(rr.caller_stamp({"agent_id": "agentC"}))
    try:
        await tools.read(relation_id="rel_1")
    finally:
        CURRENT_CALLER.reset(token)
    assert seen["caller_agent_id"] == "agentC"  # R16
    token = CURRENT_CALLER.set(rr.caller_stamp({}))  # le cerveau : aucun lecteur transmis
    try:
        seen.clear()
        await tools.read(relation_id="rel_1")
    finally:
        CURRENT_CALLER.reset(token)
    assert "caller_agent_id" not in seen


async def test_the_relay_forwards_the_reader_and_core_refuses_a_non_participant(relay):  # noqa: F811
    opened = await relay.relay.open(caller="agentQ", kind="qa", participants=[("self", "reviewer"),
                                                                              ("agentB", "reviewed")],
                                    purpose="Relire B", target_refs=[])
    relation_id = opened["relation"]["relation_id"]
    with pytest.raises(RelationRelayError) as refused:  # R17 : C n'est ni participant ni propriétaire
        await relay.relay.read(relation_id=relation_id, after=0, limit=10, caller="agentC")
    assert (refused.value.status, refused.value.code) == (403, "relation_read_not_allowed")
    assert (await relay.relay.read(relation_id=relation_id, after=0, limit=10, caller="agentA"))["relation"]


async def test_the_control_center_route_passes_the_reader_to_the_relay():
    from jarvis.runtime.control_center import ControlCenter

    received = {}

    class Relay:
        async def read(self, **kwargs):
            received.update(kwargs)
            return {"relation": {}}

    center = SimpleNamespace(relation_relay=Relay(), journal=SimpleNamespace(emit=lambda *a, **k: None),
                             RELATION_MAX_BYTES=ControlCenter.RELATION_MAX_BYTES)
    center._relation_call = functools.partial(ControlCenter._relation_call, center)
    request = make_mocked_request("GET", "/api/missions/relations/rel_1?caller_agent_id=agentC",
                                  match_info={"relation_id": "rel_1"})
    response = await ControlCenter.relations_read(center, request)
    assert response.status == 200 and received["caller"] == "agentC"  # R18
    request = make_mocked_request("GET", "/api/missions/relations/rel_1", match_info={"relation_id": "rel_1"})
    await ControlCenter.relations_read(center, request)
    assert received["caller"] is None


# ------------------------------------------------------------------ R22, R24 : la grâce, et rien d'inventé


async def test_withdrawal_and_late_closing_follow_the_grace(core):
    await team(core)
    qa = await core.service.open_relation(caller=w("Q"), kind=K.QA, purpose="Relire",
                                          participants=[(w("Q"), P.REVIEWER), (w("B"), P.REVIEWED)])
    duel = await core.service.open_relation(caller=w("A"), kind=K.ADVERSARY, purpose="Duel",
                                            participants=[(w("B"), P.PRODUCER), (w("C"), P.PRODUCER)])
    core.clock.minute = 32
    for key in ("B", "C", "Q"):
        await end(core, key, minute=31)
    await end(core, "A", minute=32)
    mission = await core.store.get_mission("mis_A")
    assert mission.status is MissionStatus.COMPLETED
    core.clock.minute = 32 + 9.9  # dans la grâce
    await core.service.publish_message(caller=w("B"), relation_id=duel.relation_id, type=T.MESSAGE, text="tard")
    await core.service._withdraw_stale_relations()
    assert (await core.store.get_relation(qa.relation_id)).is_open  # R24 : rien retiré pendant la grâce
    core.clock.minute = 32 + 10.2
    with pytest.raises(RelationError) as late:  # R22 : la clôture respecte la grâce
        await core.service.finish_relation(caller=w("Q"), relation_id=qa.relation_id, outcome=R.APPROVED)
    assert late.value.code == "mission_closed"
    await core.service._withdraw_stale_relations()
    for relation_id in (qa.relation_id, duel.relation_id):
        withdrawn = await core.store.get_relation(relation_id)
        assert (withdrawn.outcome, withdrawn.closed_by_instance_id, withdrawn.winner_instance_id) == (
            R.WITHDRAWN, None, None)
    assert await core.store.get_mission("mis_A") == mission  # la mission close reste gelée


async def test_a_closing_during_the_grace_is_kept(core):
    await team(core)
    qa = await core.service.open_relation(caller=w("Q"), kind=K.QA, purpose="Relire",
                                          participants=[(w("Q"), P.REVIEWER), (w("B"), P.REVIEWED)])
    for key in ("B", "C", "Q"):
        await end(core, key, minute=1)
    await end(core, "A", minute=2)
    core.clock.minute += 5
    closed = await core.service.finish_relation(caller=w("Q"), relation_id=qa.relation_id, outcome=R.APPROVED)
    assert closed.outcome is R.APPROVED


async def test_read_scope_on_a_mission_tree(core):
    """Sœurs et membres d'une autre branche ne lisent pas ; propriétaire parent oui (D04)."""

    await owner(core, "A")
    await run(core, "B")
    await member(core, "B", "A")
    for sub in ("L", "M"):
        await run(core, sub)
        await owner(core, sub, parent="A", role="research-lead")
    for key, parent in (("L1", "L"), ("L2", "L"), ("M1", "M")):
        await run(core, key)
        await member(core, key, parent)
    rel = await core.service.open_relation(caller=w("L"), kind=K.COMMUNICATION, purpose="Coordonner L1 L2",
                                           participants=[(w("L1"), P.MEMBER), (w("L2"), P.MEMBER)])
    out = {}
    for who in ("L1", "L2", "L", "A", None, "B", "M", "M1"):
        try:
            await core.service.read_relation(rel.relation_id, caller=w(who) if who else None)
            out[who] = "read"
        except RelationError as exc:
            out[who] = exc.code
    assert out == {"L1": "read", "L2": "read", "L": "read", "A": "read", None: "read",
                   "B": "relation_read_not_allowed", "M": "relation_read_not_allowed",
                   "M1": "relation_read_not_allowed"}
    response = await core.client.get(f"/v1/missions/relations/{rel.relation_id}", params={"caller_work_source": "x"})
    assert response.status == 400  # un lecteur à moitié n'est pas une lecture ouverte


# ------------------------------------------------------------------ balayage non bloqué


async def test_one_failing_withdrawal_does_not_stop_the_sweep_nor_retry_each_pass(core, monkeypatch):
    await team(core)
    first = await core.service.open_relation(caller=w("A"), kind=K.COMMUNICATION, purpose="Un",
                                             participants=[(w("B"), P.MEMBER), (w("C"), P.MEMBER)])
    second = await core.service.open_relation(caller=w("A"), kind=K.COMMUNICATION, purpose="Deux",
                                              participants=[(w("B"), P.MEMBER), (w("Q"), P.MEMBER)])
    for key in ("B", "C", "Q"):
        await end(core, key, minute=1)
    await end(core, "A", minute=2)
    core.clock.minute += 11
    real, attempts = core.service.close_relation, []

    async def flaky(relation_id, outcome, **kwargs):
        attempts.append(relation_id)
        if relation_id == first.relation_id:
            raise RelationError("magasin récalcitrant", code="relation_conflict")
        return await real(relation_id, outcome, **kwargs)

    monkeypatch.setattr(core.service, "close_relation", flaky)
    await core.service._withdraw_stale_relations()
    assert (await core.store.get_relation(second.relation_id)).outcome is R.WITHDRAWN  # la suivante continue
    assert (await core.store.get_relation(first.relation_id)).is_open
    failures = [data for kind, _level, data in core.journal.lines if data.get("relation_id") == first.relation_id
                and "retry_in_s" in data]
    assert failures and failures[0]["code"] == "relation_conflict"
    await core.service._withdraw_stale_relations()
    assert attempts.count(first.relation_id) == 1  # pas retentée à chaque passe
    core.clock.minute += 6  # après WITHDRAW_RETRY_S
    monkeypatch.setattr(core.service, "close_relation", real)
    await core.service._withdraw_stale_relations()
    assert (await core.store.get_relation(first.relation_id)).outcome is R.WITHDRAWN


# ------------------------------------------------------------------ R29 et import cassé : le vrai sous-processus

BREAK_IMPORT = r'''
import importlib.abc, runpy, sys
class Breaker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name == "jarvis.runtime.routing_hook":
            raise ImportError("import du hook cassé (test)")
        return None
sys.meta_path.insert(0, Breaker())
sys.argv = ["jarvis", *sys.argv[1:]]
runpy.run_module("jarvis", run_name="__main__", alter_sys=True)
'''


def _hook(tmp_path: Path, tool: str) -> subprocess.CompletedProcess:
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {}, "tool_use_id": "toolu_x"}
    return subprocess.run([sys.executable, "-c", BREAK_IMPORT, "routing-hook", "--runtime-root", str(tmp_path)],
                          input=json.dumps(event), capture_output=True, text=True, encoding="utf-8", cwd=ORCH,
                          timeout=120, env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def test_a_broken_hook_import_refuses_relation_tools_says_it_and_stays_fail_open(tmp_path):
    relation = _hook(tmp_path, "mcp__jarvis-workspace__relation_post")
    assert relation.returncode == 0, relation.stderr
    assert json.loads(relation.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"  # R29
    assert "hook indisponible" in relation.stderr
    agent = _hook(tmp_path, "Agent")
    assert (agent.returncode, agent.stdout) == (0, "")  # fail-open, code de sortie inchangé
    assert "hook indisponible" in agent.stderr
    events = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(e["kind"], e["data"]["code"], e["data"]["fail_closed"]) for e in events] == [
        ("agent.routing.failed", "routing_hook_import_failed", True),
        ("agent.routing.failed", "routing_hook_import_failed", False)]


# ------------------------------------------------------------------ M15 : la garde de l'adaptateur


async def test_the_adapter_refuses_a_retained_successor_never_in_a_relation(core):
    await owner(core, "A")
    pending = await core.service.prepare_handoff(caller=w("A"), purpose="Relais", packet=packet())
    successor = instance("ainst_s", role="coder", mission="mis_A", owner=True, minute=1, external="S")
    stored, created = await core.store.record_instance(successor)
    assert created
    relation = rr.handoff_relation(pending, relation_id="rel_m15b", successor=successor, at=at(40))
    with pytest.raises(Exception) as refused:
        await core.store.record_handoff(successor, declaration=None, relation=relation, at=at(40), summary="s")
    assert getattr(refused.value, "code", None) == "handoff_successor_not_fresh"
    assert await core.store.get_relation("rel_m15b") is None
    owner_a = (await core.store.find_instance(SOURCE, "A")).instance.instance_id
    assert (await core.store.get_mission("mis_A")).owner_instance_id == owner_a
