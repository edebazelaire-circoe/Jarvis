"""Runtime des relations dans Core (Slice 06) : QA, Adversary, communication, relais, délégation alignée.

Base temporaire, vrai `WorkStateStore`, vrai service, vraies routes (`aiohttp` sans middleware de jeton). Rien
n'impose de tours : chaque test noue, alimente et clôt une relation quand il le veut.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.core.mission_history import (
    MISSION_HISTORY_CLOSE_DEFERRED_KIND, MISSION_HISTORY_HANDOFF_FAILED_KIND, MISSION_HISTORY_HANDOFF_TRANSFERRED_KIND,
    MISSION_HISTORY_MESSAGE_AFTER_CLOSE_KIND, MISSION_HISTORY_RELATION_MESSAGE_KIND, MISSION_HISTORY_RELATION_REFUSED_KIND,
    MissionHistoryService,
)
from jarvis.core.work_state import WorkStateStore
from jarvis.domain.agent_relations import AgentRelationKind as K
from jarvis.domain.agent_relations import HandoffPacket, RelationError, RelationMessageType, RelationOutcome
from jarvis.domain.agent_relations import ParticipantPosition as P
from jarvis.domain.mission_history import AgentDeclarationFact, DeclarationOutcome as O, MissionOpening
from jarvis.domain.missions import MissionStatus
from jarvis.domain.relation_runtime import HANDOFF_TTL_S, delegation_relation_id
from jarvis.domain.subagent_roles import RoleStatus
from jarvis.domain.work_state import WorkStatus
from jarvis.protocol.mission_routes import MissionProtocolRoutes
from tests.fakes.mission_history import SOURCE, at, fact, observation, open_store

SENTINEL = "SENTINELLE-RAISONNEMENT-7f3a"


class Journal:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.lines.append((kind, level, dict(data or {})))

    def kinds(self, kind):
        return [data for name, _level, data in self.lines if name == kind]


class Clock:
    def __init__(self) -> None:
        self.minute = 30.0

    def now(self):
        return at(self.minute)


@pytest.fixture
async def core(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    clock = Clock()
    work = WorkStateStore(clock=clock)
    journal = Journal()
    service = MissionHistoryService(store, work_state=work, diagnostics=journal, clock=clock, sweep_interval_s=None)
    app = web.Application()
    app.add_routes(MissionProtocolRoutes(SimpleNamespace(mission_history=service, work_state=work,
                                                         _diagnostics=journal)).routes())
    client = TestClient(TestServer(app))
    await client.start_server()
    yield SimpleNamespace(service=service, store=store, work=work, journal=journal, client=client, clock=clock,
                          path=tmp_path / "jarvis.sqlite3")
    await client.close()
    await service.stop()
    await state.close()


def w(key: str) -> tuple[str, str]:
    return (SOURCE, key)


async def owner(core, key, *, parent=None, role="coder"):
    return await core.service.record_declaration(
        fact(key, role=role, mission_id=f"mis_{key}", owner=True, label=f"Objet {key}"), work_source=SOURCE,
        work_external_id=key, parent_work_external_id=parent,
        mission=MissionOpening(objective=f"Objet {key}", parent_from_caller=True), inherit_mission=True)


async def member(core, key, parent, role="coder"):
    result = await core.service.record_declaration(fact(key, role=role), work_source=SOURCE, work_external_id=key,
                                                   parent_work_external_id=parent, inherit_mission=True)
    assert result.outcome is O.RECORDED, result
    return result.instance


async def run(core, key, minute=0.1):
    await core.work.observe(observation(key, WorkStatus.RUNNING, minute=minute))


async def end(core, key, status=WorkStatus.COMPLETED, minute=1.0):
    await core.work.observe(observation(key, WorkStatus.RUNNING, minute=minute - 0.05))
    await core.work.observe(observation(key, status, minute=minute))
    item = next(i for i in core.work.current_snapshot().items if i.external_id == key)
    await core.service.observe_work_item(item)


def packet() -> HandoffPacket:
    return HandoffPacket(objective="Finir la correction du parseur", completed_work="Cause trouvée, test rouge écrit",
                         recommended_next_action="Écrire le correctif et faire passer le test",
                         key_decisions=("garder l'API publique",), open_points=("cas Unicode",),
                         artifact_refs=("art_1",), evidence_refs=("rel_qa_1",))


async def team(core):
    """A (coder, Mission Owner racine) lance B et C (producteurs) et Q (relecteur QA)."""

    await owner(core, "A")
    for key, role in (("B", "coder"), ("C", "coder"), ("Q", "qa")):
        await run(core, key)
        await member(core, key, "A", role)


# ------------------------------------------------------------------ QA


async def test_a_qa_is_an_asymmetric_review_opened_by_the_reviewer_and_closed_by_its_verdict(core):
    await team(core)
    qa = await core.service.open_relation(caller=w("Q"), kind=K.QA, purpose="Relire le correctif de B",
                                          participants=[(w("Q"), P.REVIEWER), (w("B"), P.REVIEWED)],
                                          target_refs=("art_fix",))
    reviewer, reviewed = qa.endpoints()
    assert qa.kind is K.QA and qa.mission_id == "mis_A" and qa.created_by_instance_id == reviewer
    _, critique = await core.service.publish_message(caller=w("Q"), relation_id=qa.relation_id,
                                                     type=RelationMessageType.CRITIQUE, text="Le cas vide n'est pas testé.")
    assert critique.author_instance_id == reviewer
    # Le producteur relu répond sur le même tableau ; aucun tour n'est imposé.
    await core.service.publish_message(caller=w("B"), relation_id=qa.relation_id, type=RelationMessageType.MESSAGE,
                                       text="Test ajouté.", reply_to_message_id=critique.message_id)
    with pytest.raises(RelationError) as refused:  # le relu ne rend pas le verdict de sa propre relecture
        await core.service.finish_relation(caller=w("B"), relation_id=qa.relation_id, outcome=RelationOutcome.APPROVED)
    assert refused.value.code == "relation_outcome_invalid"
    closed = await core.service.finish_relation(caller=w("Q"), relation_id=qa.relation_id,
                                                outcome=RelationOutcome.APPROVED, summary="Tient avec le test ajouté.")
    assert (closed.outcome, closed.closed_by_instance_id) == (RelationOutcome.APPROVED, reviewer)
    relation, thread, participants = await core.service.read_relation(qa.relation_id)
    assert [message.type for _seq, message in thread] == [RelationMessageType.CRITIQUE, RelationMessageType.MESSAGE]
    assert {view.stored.instance.role_id for view in participants} == {"qa", "coder"}
    assert reviewed != reviewer


async def test_the_owner_may_open_a_qa_but_a_qa_needs_a_reviewer_with_the_qa_role(core):
    await team(core)
    with pytest.raises(RelationError) as refused:
        await core.service.open_relation(caller=w("A"), kind=K.QA, purpose="Second regard",
                                         participants=[(w("C"), P.REVIEWER), (w("B"), P.REVIEWED)])
    assert refused.value.code == "qa_reviewer_role"
    qa = await core.service.open_relation(caller=w("A"), kind=K.QA, purpose="Second regard",
                                          participants=[(w("Q"), P.REVIEWER), (w("B"), P.REVIEWED)])
    assert qa.created_by_instance_id != qa.endpoints()[0]


# ------------------------------------------------------------------ Adversary


async def test_an_adversary_joins_competing_producers_and_the_owner_names_the_winner(core):
    await team(core)
    duel = await core.service.open_relation(caller=w("A"), kind=K.ADVERSARY, purpose="Deux approches du cache",
                                            participants=[(w("B"), P.PRODUCER), (w("C"), P.PRODUCER)])
    assert duel.endpoints() is None and {p.position for p in duel.participants} == {P.PRODUCER}
    for key, text in (("B", "Approche LRU : simple, mesurée à 92 %."), ("C", "Approche TTL : 88 %, moins de RAM.")):
        await core.service.publish_message(caller=w(key), relation_id=duel.relation_id,
                                           type=RelationMessageType.PROPOSAL, text=text)
    await core.service.publish_message(caller=w("C"), relation_id=duel.relation_id, type=RelationMessageType.CRITIQUE,
                                       text="La mesure LRU ignore les clés froides.")
    with pytest.raises(RelationError) as refused:  # un relecteur n'est pas un concurrent (D10)
        await core.service.open_relation(caller=w("A"), kind=K.ADVERSARY, purpose="Faux duel",
                                         participants=[(w("B"), P.PRODUCER), (w("Q"), P.PRODUCER)])
    assert refused.value.code == "adversary_producer_is_reviewer"
    with pytest.raises(RelationError) as refused:  # un producteur ne tranche pas son propre duel
        await core.service.finish_relation(caller=w("B"), relation_id=duel.relation_id, outcome=RelationOutcome.WINNER,
                                           winner=w("B"))
    assert refused.value.code == "relation_not_owner"
    closed = await core.service.finish_relation(caller=w("A"), relation_id=duel.relation_id,
                                                outcome=RelationOutcome.WINNER, winner=w("B"), summary="LRU retenue.")
    assert closed.winner_instance_id == duel.participants[0].instance_id


async def test_only_the_current_mission_owner_opens_an_adversary_or_a_communication(core):
    await team(core)
    for kind, position in ((K.ADVERSARY, P.PRODUCER), (K.COMMUNICATION, P.MEMBER)):
        with pytest.raises(RelationError) as refused:
            await core.service.open_relation(caller=w("B"), kind=kind, purpose="Sans autorité",
                                             participants=[(w("B"), position), (w("C"), position)])
        assert refused.value.code == "relation_not_owner"
    assert core.journal.kinds(MISSION_HISTORY_RELATION_REFUSED_KIND)[0]["code"] == "relation_not_owner"


# ------------------------------------------------------------------ communication et confidentialité


async def test_a_communication_board_keeps_deliberate_messages_and_refuses_private_reasoning(core):
    await team(core)
    talk = await core.service.open_relation(caller=w("A"), kind=K.COMMUNICATION, purpose="Coordonner B et C",
                                            participants=[(w("A"), P.MEMBER), (w("B"), P.MEMBER), (w("C"), P.MEMBER)])
    seq, _ = await core.service.publish_message(caller=w("B"), relation_id=talk.relation_id,
                                                type=RelationMessageType.QUESTION, text="Qui prend les tests ?",
                                                audience=[w("C")])
    for text, code in ((f"<thinking>{SENTINEL}</thinking> je pense que", "relation_private_content"),
                       (f'Voici: {{"reasoning": "{SENTINEL}"}}', "relation_private_content")):
        with pytest.raises(RelationError) as refused:
            await core.service.publish_message(caller=w("C"), relation_id=talk.relation_id,
                                               type=RelationMessageType.MESSAGE, text=text)
        assert refused.value.code == code
    with pytest.raises(RelationError) as refused:  # un non-participant ne publie pas
        await core.service.publish_message(caller=w("Q"), relation_id=talk.relation_id,
                                           type=RelationMessageType.MESSAGE, text="Bonjour")
    assert refused.value.code == "relation_not_participant"
    _relation, thread, _ = await core.service.read_relation(talk.relation_id)
    assert [s for s, _m in thread] == [seq]
    # Sonde de confidentialité : la sentinelle n'est écrite nulle part dans la base, ni au journal.
    assert SENTINEL.encode() not in core.path.read_bytes()
    assert SENTINEL not in repr(core.journal.lines)
    [logged] = core.journal.kinds(MISSION_HISTORY_RELATION_MESSAGE_KIND)
    assert "text" not in logged and logged["chars"] == len("Qui prend les tests ?")
    ended = await core.service.finish_relation(caller=w("C"), relation_id=talk.relation_id,
                                               outcome=RelationOutcome.ENDED)
    assert ended.closed_by_instance_id is not None
    with pytest.raises(RelationError) as refused:
        await core.service.publish_message(caller=w("B"), relation_id=talk.relation_id,
                                           type=RelationMessageType.MESSAGE, text="Encore un mot")
    assert refused.value.code == "relation_closed"


async def test_the_brain_reads_but_never_writes_and_an_unrecorded_agent_is_named(core):
    await team(core)
    with pytest.raises(RelationError) as refused:
        await core.service.open_relation(caller=None, kind=K.COMMUNICATION, purpose="Le cerveau",
                                         participants=[(w("B"), P.MEMBER), (w("C"), P.MEMBER)])
    assert refused.value.code == "relation_caller_not_instance"
    with pytest.raises(RelationError) as refused:  # un éphémère (ou un agent pas encore remis) n'est pas retenu
        await core.service.open_relation(caller=w("A"), kind=K.COMMUNICATION, purpose="Avec un éphémère",
                                         participants=[(w("B"), P.MEMBER), (w("EPH"), P.MEMBER)])
    assert refused.value.code == "relation_agent_not_recorded"


async def test_a_closed_mission_takes_no_new_relation_but_an_open_one_keeps_late_messages(core):
    await team(core)
    talk = await core.service.open_relation(caller=w("A"), kind=K.COMMUNICATION, purpose="Avant la fin",
                                            participants=[(w("B"), P.MEMBER), (w("C"), P.MEMBER)])
    for key in ("B", "C", "Q"):
        await end(core, key, minute=1)
    await end(core, "A", minute=2)
    assert (await core.store.get_mission("mis_A")).status is MissionStatus.COMPLETED
    with pytest.raises(RelationError) as refused:
        await core.service.open_relation(caller=w("A"), kind=K.QA, purpose="Trop tard",
                                         participants=[(w("Q"), P.REVIEWER), (w("B"), P.REVIEWED)])
    assert refused.value.code == "mission_closed"
    # Une relation encore ouverte garde ce qu'un participant y dit après la clôture (agent repris par SendMessage,
    # constaté en bac à sable) : retenu, et dit au journal.
    seq, _ = await core.service.publish_message(caller=w("B"), relation_id=talk.relation_id,
                                                type=RelationMessageType.MESSAGE, text="Après la fin")
    assert seq >= 1
    [late] = core.journal.kinds(MISSION_HISTORY_MESSAGE_AFTER_CLOSE_KIND)
    assert late["mission_status"] == "completed"


# ------------------------------------------------------------------ relais


def successor_fact(key: str, handoff_id: str, mission_id: str = "mis_A", *, minute: float = 0.5,
                   ephemeral: bool = False) -> AgentDeclarationFact:
    return AgentDeclarationFact(tool_use_id=key, declared_at=at(minute), role_id="coder",
                                role_status=RoleStatus.DECLARED, role_marker="coder", profile="code",
                                label="Suite du correctif", caller_agent_id="agentA", mission_id=mission_id,
                                mission_owner=True, handoff_id=handoff_id, ephemeral=ephemeral)


async def declare_successor(core, key, handoff_id, parent="A", **kwargs):
    return await core.service.record_declaration(successor_fact(key, handoff_id, **kwargs), work_source=SOURCE,
                                                 work_external_id=key, parent_work_external_id=parent,
                                                 inherit_mission=True)


async def test_a_handoff_moves_ownership_to_a_fresh_successor_with_its_packet_before_the_predecessor_ends(core):
    await team(core)
    await run(core, "A")
    pending = await core.service.prepare_handoff(caller=w("A"), purpose="Contexte à rafraîchir", packet=packet())
    assert (await core.store.get_mission("mis_A")).owner_instance_id == (await core.store.find_instance(*w("A"))).instance.instance_id
    await run(core, "S")
    result = await declare_successor(core, "S", pending.handoff_id)
    assert result.outcome is O.RECORDED and result.instance.mission_owner
    mission = await core.store.get_mission("mis_A")
    assert mission.owner_instance_id == result.instance.instance_id  # transfert fait, le prédécesseur vit encore
    tree = await core.store.mission_tree("mis_A")
    [handoff] = [item for item in tree.relations if item.kind is K.HANDOFF]
    assert handoff.handoff == packet() and handoff.outcome is RelationOutcome.TRANSFERRED
    assert [change.owner_instance_id for change in tree.ownership][-1] == result.instance.instance_id
    [done] = core.journal.kinds(MISSION_HISTORY_HANDOFF_TRANSFERRED_KIND)
    assert done["relation_id"] == handoff.relation_id
    # Le prédécesseur finit : la mission ne se clôt pas, son propriétaire est le successeur.
    for key in ("B", "C", "Q"):
        await end(core, key, minute=1)
    await end(core, "A", minute=2)
    assert (await core.store.get_mission("mis_A")).status is MissionStatus.OPEN
    await end(core, "S", minute=3)
    assert (await core.store.get_mission("mis_A")).status is MissionStatus.COMPLETED
    assert core.service.relation_refs(*w("S")) == (f"relais (successeur) {handoff.relation_id} close : transferred",)


async def test_a_prepared_handoff_defers_the_close_even_if_the_predecessor_ends_first(core):
    await owner(core, "A")
    await run(core, "A")
    pending = await core.service.prepare_handoff(caller=w("A"), purpose="Spécialité", packet=packet())
    await end(core, "A", minute=1)  # le prédécesseur finit avant que la déclaration du successeur n'arrive
    assert (await core.store.get_mission("mis_A")).status is MissionStatus.OPEN
    assert core.journal.kinds(MISSION_HISTORY_CLOSE_DEFERRED_KIND)[0]["handoff_id"] == pending.handoff_id
    await run(core, "S", minute=1.5)
    assert (await declare_successor(core, "S", pending.handoff_id)).outcome is O.RECORDED
    await core.service.sweep()
    assert (await core.store.get_mission("mis_A")).status is MissionStatus.OPEN  # S travaille
    await end(core, "S", minute=3)
    assert (await core.store.get_mission("mis_A")).status is MissionStatus.COMPLETED


async def test_an_expired_or_unknown_handoff_keeps_the_successor_without_ownership_and_says_so(core):
    await owner(core, "A")
    await run(core, "A")
    pending = await core.service.prepare_handoff(caller=w("A"), purpose="Spécialité", packet=packet())
    core.clock.minute += HANDOFF_TTL_S / 60 + 1
    await core.service.sweep()  # expiré : oublié, dit au journal
    assert core.journal.kinds(MISSION_HISTORY_HANDOFF_FAILED_KIND)[0]["code"] == "handoff_expired"
    result = await declare_successor(core, "S", pending.handoff_id)
    assert result.outcome is O.RECORDED  # l'agent a tourné : il est retenu (D18)
    a_id = (await core.store.find_instance(*w("A"))).instance.instance_id
    assert (await core.store.get_mission("mis_A")).owner_instance_id == a_id
    assert core.journal.kinds(MISSION_HISTORY_HANDOFF_FAILED_KIND)[-1]["code"] == "handoff_unknown"
    assert not [item for item in (await core.store.mission_tree("mis_A")).relations if item.kind is K.HANDOFF]


async def test_a_handoff_from_another_predecessor_or_after_the_close_is_refused(core):
    await team(core)
    with pytest.raises(RelationError) as refused:  # un membre ne passe pas la mission de son propriétaire
        await core.service.prepare_handoff(caller=w("B"), purpose="Usurpation", packet=packet())
    assert refused.value.code == "handoff_not_owner"
    pending = await core.service.prepare_handoff(caller=w("A"), purpose="Spécialité", packet=packet())
    result = await declare_successor(core, "S", pending.handoff_id, parent="B")  # lancé par un autre que A
    assert result.outcome is O.RECORDED
    assert core.journal.kinds(MISSION_HISTORY_HANDOFF_FAILED_KIND)[-1]["code"] == "handoff_wrong_predecessor"
    for key in ("B", "C", "Q", "S"):
        await end(core, key, minute=1)
    core.service._handoffs.clear()
    await end(core, "A", minute=2)
    assert (await core.store.get_mission("mis_A")).status is MissionStatus.COMPLETED
    with pytest.raises(RelationError) as refused:
        await core.service.prepare_handoff(caller=w("A"), purpose="Après la fin", packet=packet())
    assert refused.value.code == "mission_closed"


async def test_a_second_handoff_from_the_same_predecessor_is_a_fan_out(core):
    await owner(core, "A")
    pending = await core.service.prepare_handoff(caller=w("A"), purpose="Spécialité", packet=packet())
    assert (await declare_successor(core, "S", pending.handoff_id)).instance.mission_owner
    with pytest.raises(RelationError) as refused:  # A n'est plus propriétaire : il ne transmet pas deux fois
        await core.service.prepare_handoff(caller=w("A"), purpose="Encore", packet=packet())
    assert refused.value.code in {"handoff_not_owner", "handoff_fan_out"}


async def test_a_failed_handoff_transaction_writes_nothing_partial(core, monkeypatch):
    await owner(core, "A")
    pending = await core.service.prepare_handoff(caller=w("A"), purpose="Spécialité", packet=packet())
    from jarvis.adapters import sqlite_mission_history as adapter

    def boom(conn, *args, **kwargs):
        raise RelationError("injected after the instance and the relation", code="relation_conflict")

    monkeypatch.setattr(adapter, "_write_transfer", boom)
    result = await declare_successor(core, "S", pending.handoff_id)
    # Rien de partiel : ni relais sans transfert, ni successeur propriétaire. Le successeur est retenu ensuite,
    # sans la propriété, par une écriture ordinaire.
    tree = await core.store.mission_tree("mis_A")
    assert not [item for item in tree.relations if item.kind is K.HANDOFF]
    assert (await core.store.get_mission("mis_A")).owner_instance_id != result.instance.instance_id
    assert core.journal.kinds(MISSION_HISTORY_HANDOFF_FAILED_KIND)[-1]["code"] == "relation_conflict"


# ------------------------------------------------------------------ délégation alignée


async def test_a_sub_mission_is_a_delegation_returned_when_the_sub_mission_closes(core):
    await owner(core, "A")
    await run(core, "L")
    await owner(core, "L", parent="A", role="research-lead")
    delegation = await core.store.get_relation(delegation_relation_id("mis_L"))
    assert (delegation.kind, delegation.mission_id, delegation.sub_mission_id) == (K.DELEGATION, "mis_A", "mis_L")
    # Rejeu de la déclaration : identique, sans doublon.
    await owner(core, "L", parent="A", role="research-lead")
    assert len([item for item in (await core.store.mission_tree("mis_A")).relations if item.kind is K.DELEGATION]) == 1
    await end(core, "L", minute=1)
    closed = await core.store.get_relation(delegation_relation_id("mis_L"))
    assert (closed.status.value, closed.outcome) == ("closed", RelationOutcome.RETURNED)
    with pytest.raises(RelationError) as refused:  # délégation et relais se closent seuls
        await core.service.finish_relation(caller=w("A"), relation_id=closed.relation_id,
                                           outcome=RelationOutcome.WITHDRAWN)
    assert refused.value.code == "relation_closed_by_core"


async def test_relation_summaries_reach_the_brain_context_without_io(core):
    await team(core)
    qa = await core.service.open_relation(caller=w("Q"), kind=K.QA, purpose="Relire",
                                          participants=[(w("Q"), P.REVIEWER), (w("B"), P.REVIEWED)])
    [line] = core.service.relation_refs(*w("B"))
    assert line == f"QA (relu) {qa.relation_id} ouverte"
    assert core.service.relation_refs(*w("C")) == ()


# ------------------------------------------------------------------ routes


async def test_routes_return_actionable_coded_refusals(core):
    await team(core)
    ref = {"work_source": SOURCE, "work_external_id": "B"}
    response = await core.client.post("/v1/missions/relations", json={
        "caller": ref, "kind": "adversary", "purpose": "Sans autorité",
        "participants": [{"ref": ref, "position": "producer"},
                         {"ref": {"work_source": SOURCE, "work_external_id": "C"}, "position": "producer"}]})
    body = await response.json()
    assert response.status == 403 and body["error"]["code"] == "relation_not_owner"
    assert "À faire" in body["error"]["message"]
    response = await core.client.get("/v1/missions/relations/rel_absent")
    assert response.status == 404 and (await response.json())["error"]["code"] == "relation_unknown"
    response = await core.client.post("/v1/missions/relations", json={"caller": ref, "kind": "qa"})
    assert response.status == 400 and (await response.json())["error"]["code"] == "invalid_request"
    owner_ref = {"work_source": SOURCE, "work_external_id": "A"}
    response = await core.client.post("/v1/missions/relations", json={
        "caller": owner_ref, "kind": "communication", "purpose": "Coordonner",
        "participants": [{"ref": ref, "position": "member"},
                         {"ref": {"work_source": SOURCE, "work_external_id": "C"}, "position": "member"}],
        "round": 3})
    assert response.status == 400  # une clé de protocole n'entre même pas dans l'enveloppe
    response = await core.client.post("/v1/missions/relations", json={
        "caller": owner_ref, "kind": "communication", "purpose": "Coordonner",
        "participants": [{"ref": ref, "position": "member"},
                         {"ref": {"work_source": SOURCE, "work_external_id": "C"}, "position": "member"}]})
    relation_id = (await response.json())["relation"]["relation_id"]
    response = await core.client.post(f"/v1/missions/relations/{relation_id}/messages", json={
        "caller": ref, "type": "message", "text": f"<reasoning>{SENTINEL}</reasoning>"})
    body = await response.json()
    assert response.status == 409 and body["error"]["code"] == "relation_private_content"
    assert "jamais votre raisonnement" in body["error"]["message"] and SENTINEL not in body["error"]["message"]
    response = await core.client.post("/v1/missions/handoffs", json={
        "caller": owner_ref, "purpose": "Relais", "packet": {"objective": "x", "completed_work": "y"}})
    assert response.status == 409 and (await response.json())["error"]["code"] == "handoff_packet_incomplete"
    response = await core.client.post("/v1/missions/handoffs", json={
        "caller": owner_ref, "purpose": "Relais", "packet": packet().to_payload()})
    handoff = (await response.json())["handoff"]
    assert handoff["handoff_id"].startswith("hof_") and handoff["mission_id"] == "mis_A"
    assert handoff["packet"] == packet().to_payload()


async def test_the_handoff_successor_declaration_route_opens_no_new_mission(core):
    await owner(core, "A")
    pending = await core.service.prepare_handoff(caller=w("A"), purpose="Spécialité", packet=packet())
    response = await core.client.post("/v1/missions/declarations", json={"declarations": [{
        "fact": successor_fact("S", pending.handoff_id).to_payload(), "work_source": SOURCE,
        "work_external_id": "S", "parent_work_external_id": "A"}]})
    [result] = (await response.json())["results"]
    assert result["outcome"] == "recorded"
    assert await core.store.get_mission("mis_S") is None
    assert (await core.store.get_mission("mis_A")).owner_instance_id == result["instance_id"]


def test_a_successor_fact_is_a_non_ephemeral_mission_owner_and_keeps_old_facts_identical():
    from jarvis.domain.mission_history import MissionHistoryError

    with pytest.raises(MissionHistoryError):
        AgentDeclarationFact(tool_use_id="S", declared_at=at(0), role_id="coder", role_status=RoleStatus.DECLARED,
                             handoff_id="hof_x")
    assert "handoff_id" not in fact("X").to_payload()  # un fait ordinaire garde sa forme d'avant
    again = AgentDeclarationFact.from_payload(successor_fact("S", "hof_abcdefgh").to_payload())
    assert again.handoff_id == "hof_abcdefgh"


async def test_relation_timestamps_never_precede_the_clock(core):
    await team(core)
    core.clock.minute = 31
    talk = await core.service.open_relation(caller=w("A"), kind=K.COMMUNICATION, purpose="Heure",
                                            participants=[(w("B"), P.MEMBER), (w("C"), P.MEMBER)])
    assert talk.created_at == at(31)
    _, message = await core.service.publish_message(caller=w("B"), relation_id=talk.relation_id,
                                                    type=RelationMessageType.MESSAGE, text="Ok")
    assert message.created_at >= talk.created_at
    assert talk.created_at - at(30) == timedelta(minutes=1)
