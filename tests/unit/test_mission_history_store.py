"""Adaptateur SQLite de l'historique des missions (v10) : transactions, contraintes, refus des contrats.

Bases temporaires seulement. Contrat : `docs/mission-history.md`.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from jarvis.domain.agent_relations import AgentRelationKind as K
from jarvis.domain.agent_relations import ParticipantPosition as P
from jarvis.domain.agent_relations import RelationError, RelationOutcome
from jarvis.domain.mission_history import MissionHistoryError
from jarvis.domain.missions import MissionError, MissionStatus
from jarvis.ports.mission_history import MissionHistoryStoreError, MissionHistoryUnavailable
from tests.fakes.mission_history import at, fact, instance, message, mission, open_store, packet, relation


@pytest.fixture
async def store(tmp_path):
    state, repository = await open_store(tmp_path / "jarvis.sqlite3")
    yield repository
    await state.close()


async def _mission_with_owner(store, mission_id="m1", owner_id="own"):
    owner = instance(owner_id, mission=mission_id, owner=True)
    await store.record_instance(owner, declaration=fact(f"toolu_{owner_id}", mission_id=mission_id, owner=True),
                                mission=mission(mission_id, owner_id))
    return owner


# ------------------------------------------------------------------ instances


async def test_an_instance_survives_a_restart_and_a_replay_is_a_duplicate(tmp_path):
    path = tmp_path / "jarvis.sqlite3"
    state, store = await open_store(path)
    stored, created = await store.record_instance(instance("a1", label=""), declaration=fact("toolu_a1"))
    assert created and stored.instance.instance_id == "a1"
    await state.close()

    state, store = await open_store(path)  # Core redémarré : Work State est vide, l'historique ne l'est pas
    try:
        found = await store.find_instance("claude", "toolu_a1")
        assert found is not None and found.instance.role_id == "coder" and found.declaration.session_id == "sess-1"
        # Rejeu sous un autre id : l'id déjà attribué fait foi, rien n'est réécrit hormis un libellé vide.
        again, created = await store.record_instance(instance("other-id", external="toolu_a1", label="Corriger le bug"))
        assert not created and again.instance.instance_id == "a1" and again.instance.label == "Corriger le bug"
        assert (await store.get_instance("a1")).instance.label == "Corriger le bug"
    finally:
        await state.close()


async def test_a_replay_cannot_rewrite_the_role(store):
    await store.record_instance(instance("a1"))
    with pytest.raises(MissionError) as caught:
        await store.record_instance(instance("a1", role="research"))
    assert caught.value.code == "immutable_field" and caught.value.field == "role_id"
    assert (await store.get_instance("a1")).instance.role_id == "coder"


async def test_no_row_is_ever_written_for_an_ephemeral_instance(store, tmp_path):
    with pytest.raises(MissionHistoryError) as caught:
        await store.record_instance(instance("e1", ephemeral=True))
    assert caught.value.code == "ephemeral_not_retained"
    assert await store.find_instance("claude", "toolu_e1") is None
    assert (await store.counts())["agent_instances"] == 0


async def test_the_table_itself_refuses_an_ephemeral_row_and_a_role_rewrite(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    await store.record_instance(instance("a1"))
    await state.close()
    conn = sqlite3.connect(tmp_path / "jarvis.sqlite3")
    try:
        data = json.loads(conn.execute("SELECT data FROM agent_instances").fetchone()[0])
        ephemeral = {**data, "instance_id": "e1", "work_external_id": "toolu_e1", "ephemeral": True}
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO agent_instances(instance_id,work_source,work_external_id,role_id,mission_owner,"
                         "created_at,data) VALUES('e1','claude','toolu_e1','coder',0,'x',?)", (json.dumps(ephemeral),))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE agent_instances SET role_id='research' WHERE instance_id='a1'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE agent_instances SET data=json_set(data,'$.role_id','research') WHERE instance_id='a1'")
    finally:
        conn.close()


async def test_an_unknown_mission_or_parent_is_refused(store):
    with pytest.raises(MissionError) as caught:
        await store.record_instance(instance("a1", mission="nowhere"))
    assert caught.value.code == "mission_unknown"
    with pytest.raises(MissionError) as caught:
        await store.record_instance(instance("a2", parent="ghost"))
    assert caught.value.code == "mission_parent_missing"


async def test_a_corrupted_row_is_reported_never_repaired(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    await store.record_instance(instance("a1"))
    await state.close()
    conn = sqlite3.connect(tmp_path / "jarvis.sqlite3")
    conn.execute("DROP TRIGGER agent_instances_immutable")  # simule une écriture hors de l'adaptateur
    conn.execute("UPDATE agent_instances SET work_external_id='toolu_other' WHERE instance_id='a1'")
    conn.commit()
    conn.close()
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    try:
        with pytest.raises(MissionHistoryStoreError, match="key columns disagree"):
            await store.get_instance("a1")
    finally:
        await state.close()


async def test_sqlite_refusal_is_unavailable_with_its_cause(store, monkeypatch):
    async def locked(fn):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store._state, "run_serialized", locked)
    with pytest.raises(MissionHistoryUnavailable, match="database is locked"):
        await store.record_instance(instance("a1"))


# ------------------------------------------------------------------ missions


async def test_a_mission_opens_with_its_owner_in_one_transaction(store):
    await _mission_with_owner(store)
    found = await store.get_mission("m1")
    assert found.owner_instance_id == "own" and found.root_mission_id == "m1"
    assert [(c.owner_instance_id, c.handoff_relation_id) for c in await store.ownership("m1")] == [("own", None)]
    # La mission ne s'ouvre pas deux fois, et pas par une autre instance.
    with pytest.raises(MissionError) as caught:
        await store.record_instance(instance("x", mission="m1", owner=True), mission=mission("m1", "x"))
    assert caught.value.code == "mission_conflict"
    with pytest.raises(MissionError) as caught:
        await store.record_instance(instance("y", mission="m9", owner=True), mission=mission("m9", "someone"))
    assert caught.value.code == "ownership_invalid"
    assert await store.find_instance("claude", "toolu_y") is None  # rien d'écrit : une transaction


async def test_a_sub_mission_names_a_stored_parent_and_its_root(store):
    await _mission_with_owner(store)
    sub_owner = instance("sub", mission="m1.a", owner=True, parent="own", minute=1)
    await store.record_instance(sub_owner, mission=mission("m1.a", "sub", parent="m1", root="m1", minute=1))
    tree = await store.mission_tree("m1.a")
    assert tree.root_mission_id == "m1" and [m.mission_id for m in tree.missions] == ["m1", "m1.a"]
    with pytest.raises(MissionError) as caught:
        await store.record_instance(instance("bad", mission="m1.b", owner=True),
                                    mission=mission("m1.b", "bad", parent="m1", root="m1.a"))
    assert caught.value.field == "root_mission_id"


async def test_a_closed_mission_is_frozen(store):
    await _mission_with_owner(store)
    closed = await store.close_mission("m1", MissionStatus.COMPLETED, at(10))
    assert closed.status is MissionStatus.COMPLETED
    assert await store.close_mission("m1", MissionStatus.COMPLETED, at(10)) == closed  # idempotent
    with pytest.raises(MissionError) as caught:
        await store.close_mission("m1", MissionStatus.FAILED, at(11))
    assert caught.value.code == "mission_closed"
    with pytest.raises(RelationError) as caught:
        await store.create_relation(relation("r1", K.COMMUNICATION, "m1", [("own", P.MEMBER), ("own", P.MEMBER)]))


# ------------------------------------------------------------------ relations, relais, messages


async def test_a_handoff_writes_relation_participants_and_packet_then_transfers_ownership(store):
    await _mission_with_owner(store)
    successor = instance("succ", mission="m1", owner=True, minute=2)  # N8 : plusieurs Mission Owner, un seul courant
    await store.record_instance(successor)
    handoff = relation("h1", K.HANDOFF, "m1", [("own", P.PREDECESSOR), ("succ", P.SUCCESSOR)], minute=3,
                       handoff=packet())
    assert await store.create_relation(handoff) == handoff
    assert await store.create_relation(handoff) == handoff  # rejeu identique : sans effet

    moved = await store.transfer_ownership("m1", "succ", handoff_relation_id="h1", at=at(4))
    assert moved.owner_instance_id == "succ"
    assert [c.owner_instance_id for c in await store.ownership("m1")] == ["own", "succ"]
    tree = await store.mission_tree("m1")
    assert tree.relations == (handoff,) and tree.relations[0].handoff == packet()
    assert {s.instance.instance_id for s in tree.instances} == {"own", "succ"}
    counts = await store.counts()
    assert counts["agent_handoff_packets"] == 1 and counts["agent_relation_participants"] == 2


async def test_ownership_moves_only_through_a_handoff_from_the_current_owner(store):
    await _mission_with_owner(store)
    await store.record_instance(instance("succ", mission="m1", owner=True, minute=2))
    await store.record_instance(instance("dev", mission="m1", minute=2))
    await store.create_relation(relation("c1", K.COMMUNICATION, "m1", [("own", P.MEMBER), ("dev", P.MEMBER)]))
    with pytest.raises(MissionError) as caught:
        await store.transfer_ownership("m1", "succ", handoff_relation_id="c1", at=at(4))
    assert caught.value.code == "ownership_invalid"
    assert (await store.get_mission("m1")).owner_instance_id == "own"


async def test_relation_checks_run_inside_the_store(store):
    await _mission_with_owner(store)
    await store.record_instance(instance("dev", mission="m1", minute=1))
    await store.record_instance(instance("rev", role="research", mission="m1", minute=1))
    # QA : le relecteur doit avoir un rôle QA (D11).
    with pytest.raises(RelationError) as caught:
        await store.create_relation(relation("q1", K.QA, "m1", [("rev", P.REVIEWER), ("dev", P.REVIEWED)]))
    assert caught.value.code == "qa_reviewer_role"
    # Un participant que l'historique ne connaît pas (une éphémère n'y est jamais) est refusé.
    with pytest.raises(RelationError) as caught:
        await store.create_relation(relation("c9", K.COMMUNICATION, "m1", [("dev", P.MEMBER), ("ghost", P.MEMBER)]))
    assert caught.value.code == "relation_participant_missing"
    # Relais en éventail : refusé par `check_handoff_chain`.
    await store.record_instance(instance("s1", mission="m1", owner=True, minute=2))
    await store.record_instance(instance("s2", mission="m1", owner=True, minute=2))
    await store.create_relation(relation("h1", K.HANDOFF, "m1", [("own", P.PREDECESSOR), ("s1", P.SUCCESSOR)],
                                         minute=3, handoff=packet()))
    with pytest.raises(RelationError) as caught:
        await store.create_relation(relation("h2", K.HANDOFF, "m1", [("own", P.PREDECESSOR), ("s2", P.SUCCESSOR)],
                                             minute=4, handoff=packet()))
    assert caught.value.code == "handoff_fan_out"
    assert (await store.counts())["agent_relations"] == 1


async def test_a_relation_id_reused_with_other_content_is_refused(store):
    await _mission_with_owner(store)
    await store.record_instance(instance("dev", mission="m1", minute=1))
    await store.create_relation(relation("c1", K.COMMUNICATION, "m1", [("own", P.MEMBER), ("dev", P.MEMBER)]))
    with pytest.raises(RelationError) as caught:
        await store.create_relation(relation("c1", K.COMMUNICATION, "m1", [("own", P.MEMBER), ("dev", P.MEMBER)],
                                             minute=5))
    assert caught.value.code == "relation_conflict"


async def test_the_thread_order_is_the_acceptance_order(store):
    await _mission_with_owner(store)
    await store.record_instance(instance("dev", mission="m1", minute=1))
    await store.create_relation(relation("c1", K.COMMUNICATION, "m1", [("own", P.MEMBER), ("dev", P.MEMBER)]))
    first = await store.append_message(message("msg1", "c1", "own", minute=5))
    # Posté après, daté avant : l'ordre du fil reste celui de l'acceptation.
    second = await store.append_message(message("msg2", "c1", "dev", minute=3))
    third = await store.append_message(message("msg3", "c1", "dev", minute=6, reply_to="msg1"))
    assert first < second < third
    assert [m.message_id for _seq, m in await store.thread("c1")] == ["msg1", "msg2", "msg3"]
    assert [m.message_id for _seq, m in await store.thread("c1", after=first)] == ["msg2", "msg3"]
    assert await store.append_message(message("msg1", "c1", "own", minute=5)) == first  # rejeu identique
    with pytest.raises(RelationError) as caught:
        await store.append_message(message("msg1", "c1", "own", minute=5, text="Autre texte"))
    assert caught.value.code == "message_conflict"
    with pytest.raises(RelationError) as caught:
        await store.append_message(message("msg4", "c1", "dev", minute=7, reply_to="nope"))
    assert caught.value.code == "relation_reply_invalid"
    with pytest.raises(RelationError) as caught:
        await store.append_message(message("msg5", "c1", "dev", minute=7, text="<thinking>privé</thinking>"))
    assert caught.value.code == "relation_private_content"


async def test_a_closed_relation_accepts_no_message(store):
    await _mission_with_owner(store)
    await store.record_instance(instance("dev", mission="m1", minute=1))
    await store.create_relation(relation("c1", K.COMMUNICATION, "m1", [("own", P.MEMBER), ("dev", P.MEMBER)]))
    closed = await store.close_relation("c1", RelationOutcome.ENDED, at(9), summary="Accord trouvé")
    assert not closed.is_open and (await store.get_relation("c1")) == closed
    with pytest.raises(RelationError) as caught:
        await store.append_message(message("late", "c1", "dev", minute=10))
    assert caught.value.code == "relation_closed"
    with pytest.raises(RelationError) as caught:
        await store.close_relation("c1", RelationOutcome.WITHDRAWN, at(11))
    assert caught.value.code == "relation_closed"
