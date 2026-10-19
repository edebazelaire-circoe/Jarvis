"""Relations typées, messages de relation et paquet de relais (Slice 02).

Critères prouvés ici : les cinq natures sont des données explicites ; Adversary est une compétition entre
pairs (deux producteurs ou plus) et QA une revue dirigée, sans position commune ; aucune relation n'impose de
nombre ni d'ordre de tours ; les messages sont des enregistrements explicites et bornés ; un relais exige un
paquet complet ; aucun raisonnement caché ni JSON brut du fournisseur n'entre dans le contrat.
"""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
import itertools

import pytest

from jarvis.domain import agent_relations as rel
from jarvis.domain import work_methods
from jarvis.domain.agent_relations import (
    FORBIDDEN_PROTOCOL_KEYS, MAX_MESSAGE_CHARS, MAX_PARTICIPANTS, OUTCOMES_BY_KIND, QA_REVIEWER_ROLE_IDS,
    RELATION_KINDS, AgentRelation, AgentRelationKind as Kind, HandoffPacket, ParticipantPosition as Pos,
    RelationError, RelationMessage, RelationMessageType as MsgType, RelationOutcome as Outcome, RelationParticipant,
    RelationStatus, check_collaboration_text, check_handoff_chain, check_message, check_relation_participants,
)
from jarvis.domain.conversation_events import is_forbidden_key
from jarvis.domain.missions import AgentInstance, Mission
from jarvis.domain.subagent_roles import ROLES, resolve_role

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=5)


def p(instance_id: str, position: Pos) -> RelationParticipant:
    return RelationParticipant(instance_id, position)


PACKET = HandoffPacket(
    objective="Terminer l'export CSV",
    completed_work="Cause trouvée : séparateur codé en dur ; test rouge écrit.",
    recommended_next_action="Rendre le séparateur configurable puis faire passer le test.",
    key_decisions=("Garder le format actuel par défaut",),
    open_points=("Faut-il migrer les exports existants ?",),
    artifact_refs=("art-test-export",),
    evidence_refs=("rel-qa-1",),
)

SHAPES = {
    Kind.DELEGATION: (p("i-lead", Pos.DELEGATOR), p("i-web", Pos.DELEGATEE)),
    Kind.COMMUNICATION: (p("i-lead", Pos.MEMBER), p("i-web", Pos.MEMBER), p("i-doc", Pos.MEMBER)),
    Kind.ADVERSARY: (p("i-dev-a", Pos.PRODUCER), p("i-dev-b", Pos.PRODUCER), p("i-dev-c", Pos.PRODUCER)),
    Kind.QA: (p("i-qa", Pos.REVIEWER), p("i-dev-a", Pos.REVIEWED)),
    Kind.HANDOFF: (p("i-dev-a", Pos.PREDECESSOR), p("i-dev-2", Pos.SUCCESSOR)),
}


def relation(kind: Kind = Kind.COMMUNICATION, **changes) -> AgentRelation:
    values = {
        "relation_id": f"rel-{kind.value}", "kind": kind, "mission_id": "m-root", "participants": SHAPES[kind],
        "purpose": "Coordonner la recherche", "created_at": T0,
        **({"handoff": PACKET} if kind is Kind.HANDOFF else {}), **changes,
    }
    return AgentRelation(**values)


def message(**changes) -> RelationMessage:
    values = {
        "message_id": "msg-1", "relation_id": "rel-communication", "author_instance_id": "i-lead",
        "type": MsgType.PROPOSAL, "text": "Je propose de comparer les deux sources.", "created_at": T1, **changes,
    }
    return RelationMessage(**values)


def code_of(call, *args, **kwargs) -> str:
    with pytest.raises(RelationError) as info:
        call(*args, **kwargs)
    return info.value.code


# ---------------------------------------------------------------- vocabulaire


def test_the_five_kinds_are_closed_data_and_work_methods_reuse_them():
    assert RELATION_KINDS == ("delegation", "communication", "adversary", "qa", "handoff")
    assert work_methods.USEFUL_RELATION_KINDS is RELATION_KINDS
    assert set(OUTCOMES_BY_KIND) == set(Kind)
    assert code_of(AgentRelation.from_payload, {**relation().to_payload(), "kind": "review"}) == "relation_invalid"


def test_qa_reviewer_roles_are_registry_ids():
    ids = {role.id for role in ROLES}
    assert QA_REVIEWER_ROLE_IDS <= ids
    assert resolve_role("reviewer").role_id in QA_REVIEWER_ROLE_IDS


@pytest.mark.parametrize("kind", list(Kind))
def test_every_kind_round_trips(kind):
    item = relation(kind)
    assert AgentRelation.from_payload(item.to_payload()) == item
    for outcome in OUTCOMES_BY_KIND[kind]:
        closer = item.participant_ids[0]
        closed = item.close(outcome, T1, summary="Fini.", closed_by=closer,
                            winner_instance_id="i-dev-a" if outcome is Outcome.WINNER else None)
        assert AgentRelation.from_payload(closed.to_payload()) == closed


# ---------------------------------------------------------------- forme : Adversary != QA


def test_adversary_is_symmetric_competition_between_two_or_more_producers():
    two = relation(Kind.ADVERSARY, participants=SHAPES[Kind.ADVERSARY][:2])
    assert not two.directed and two.endpoints() is None
    assert relation(Kind.ADVERSARY).at(Pos.PRODUCER) == ("i-dev-a", "i-dev-b", "i-dev-c")
    assert code_of(relation, Kind.ADVERSARY, participants=SHAPES[Kind.ADVERSARY][:1]) == "relation_participants_invalid"
    many = tuple(p(f"i-{n}", Pos.PRODUCER) for n in range(MAX_PARTICIPANTS + 1))
    assert code_of(relation, Kind.ADVERSARY, participants=many) == "relation_participants_invalid"


def test_qa_is_directed_review_with_no_position_shared_with_adversary():
    qa = relation(Kind.QA)
    assert qa.directed and qa.endpoints() == ("i-qa", "i-dev-a")
    adversary_positions = {Pos.PRODUCER}
    qa_positions = {Pos.REVIEWER, Pos.REVIEWED}
    assert not adversary_positions & qa_positions
    # Une QA à trois, ou entre « producteurs », n'existe pas ; un Adversary avec un relecteur non plus.
    assert code_of(relation, Kind.QA, participants=SHAPES[Kind.QA] + (p("i-x", Pos.REVIEWED),)) \
        == "relation_participants_invalid"
    assert code_of(relation, Kind.QA, participants=SHAPES[Kind.ADVERSARY][:2]) == "relation_participants_invalid"
    assert code_of(relation, Kind.ADVERSARY, participants=SHAPES[Kind.QA]) == "relation_participants_invalid"
    assert code_of(relation, Kind.ADVERSARY,
                   participants=(p("i-a", Pos.PRODUCER), p("i-b", Pos.REVIEWER))) == "relation_participants_invalid"


@pytest.mark.parametrize("kind", [Kind.DELEGATION, Kind.QA, Kind.HANDOFF])
def test_directed_kinds_need_exactly_their_two_positions(kind):
    source, target = SHAPES[kind]
    assert code_of(relation, kind, participants=(source, p("i-z", source.position))) == "relation_participants_invalid"
    assert code_of(relation, kind, participants=(source,)) == "relation_participants_invalid"
    assert code_of(relation, kind, participants=(source, p(source.instance_id, target.position))) \
        == "relation_participant_duplicate"


def test_communication_joins_peer_members():
    assert code_of(relation, participants=SHAPES[Kind.COMMUNICATION][:1]) == "relation_participants_invalid"
    assert code_of(relation, participants=(p("i-a", Pos.MEMBER), p("i-b", Pos.DELEGATOR))) \
        == "relation_participants_invalid"


# ---------------------------------------------------------------- champs propres à une nature


def test_kind_fields_belong_to_their_kind_only():
    assert relation(Kind.DELEGATION, sub_mission_id="m-sub").sub_mission_id == "m-sub"
    assert relation(Kind.QA, target_refs=("art-diff",)).target_refs == ("art-diff",)
    assert code_of(relation, Kind.QA, sub_mission_id="m-sub") == "relation_field_not_for_kind"
    assert code_of(relation, Kind.ADVERSARY, target_refs=("art-1",)) == "relation_field_not_for_kind"
    assert code_of(relation, Kind.COMMUNICATION, handoff=PACKET) == "relation_field_not_for_kind"
    assert code_of(relation, Kind.DELEGATION, sub_mission_id="m-root") == "relation_invalid"


def test_handoff_requires_its_complete_packet():
    assert code_of(relation, Kind.HANDOFF, handoff=None) == "handoff_packet_incomplete"
    payload = PACKET.to_payload()
    for key in payload:
        truncated = {k: v for k, v in payload.items() if k != key}
        assert code_of(HandoffPacket.from_payload, truncated) == "handoff_packet_incomplete", key
    for key in ("objective", "completed_work", "recommended_next_action"):
        assert code_of(replace, PACKET, **{key: "  "}) == "relation_invalid"
    # Listes vides permises, mais dites.
    empty = {**payload, "key_decisions": [], "open_points": [], "artifact_refs": [], "evidence_refs": []}
    assert HandoffPacket.from_payload(empty).open_points == ()
    assert code_of(replace, PACKET, open_points=tuple(f"point {n}" for n in range(17))) == "relation_invalid"
    assert code_of(replace, PACKET, completed_work="x" * 2_001) == "relation_invalid"


# ---------------------------------------------------------------- cycle de vie, pas de protocole


def test_relation_closes_once_with_an_outcome_of_its_kind():
    item = relation(Kind.QA)
    closed = item.close(Outcome.FINDINGS, T1, summary="Deux constats bloquants.", closed_by="i-qa")
    assert closed.status is RelationStatus.CLOSED and not closed.is_open
    assert closed.closed_by_instance_id == "i-qa"
    assert closed.close(Outcome.FINDINGS, T1, summary="Deux constats bloquants.", closed_by="i-qa") is closed
    assert code_of(closed.close, Outcome.APPROVED, T1, closed_by="i-qa") == "relation_closed"
    assert code_of(item.close, Outcome.WINNER, T1) == "relation_outcome_invalid"
    assert code_of(item.close, Outcome.APPROVED, T0 - timedelta(seconds=1), closed_by="i-qa") == "relation_invalid"
    assert code_of(relation, Kind.QA, outcome=Outcome.APPROVED) == "relation_invalid"
    assert code_of(relation, Kind.QA, closed_by_instance_id="i-qa") == "relation_invalid"


def test_qa_verdict_is_given_by_its_reviewer():
    item = relation(Kind.QA)
    for outcome in (Outcome.APPROVED, Outcome.FINDINGS, Outcome.CORRECTION_REQUESTED, Outcome.REJECTED):
        assert code_of(item.close, outcome, T1) == "relation_outcome_invalid"
        assert code_of(item.close, outcome, T1, closed_by="i-dev-a") == "relation_outcome_invalid"
        assert item.close(outcome, T1, closed_by="i-qa").outcome is outcome
    # Retirer une QA n'est pas un verdict : le Mission Owner peut le faire, ou Core sans auteur.
    assert item.close(Outcome.WITHDRAWN, T1, closed_by="i-lead").closed_by_instance_id == "i-lead"
    assert item.close(Outcome.WITHDRAWN, T1).closed_by_instance_id is None


def test_adversary_names_a_winner_only_among_its_producers():
    item = relation(Kind.ADVERSARY)
    won = item.close(Outcome.WINNER, T1, winner_instance_id="i-dev-b", closed_by="i-lead")
    assert (won.winner_instance_id, won.closed_by_instance_id) == ("i-dev-b", "i-lead")
    assert code_of(item.close, Outcome.WINNER, T1, winner_instance_id="i-dev-b") == "relation_outcome_invalid"
    assert code_of(item.close, Outcome.WINNER, T1, closed_by="i-lead") == "relation_outcome_invalid"
    assert code_of(item.close, Outcome.WINNER, T1, winner_instance_id="i-qa", closed_by="i-lead") \
        == "relation_outcome_invalid"
    assert code_of(item.close, Outcome.SYNTHESIS, T1, winner_instance_id="i-dev-a") == "relation_outcome_invalid"
    assert item.close(Outcome.UNRESOLVED, T1).outcome is Outcome.UNRESOLVED


def test_no_round_count_or_order_is_representable():
    names = {f.name for f in fields(AgentRelation)} | {f.name for f in fields(RelationMessage)}
    assert not names & FORBIDDEN_PROTOCOL_KEYS
    assert not any("round" in name or "turn" in name or "step" in name for name in names)
    for key in ("rounds", "max_rounds", "phases", "protocol", "steps", "order", "Round", "turn", "maxTurns",
                "max-iterations", "iteration"):
        assert code_of(AgentRelation.from_payload, {**relation().to_payload(), key: 3}) == "relation_is_not_a_protocol"
    # Une relation se clôt à n'importe quel moment, sans message préalable.
    assert relation(Kind.ADVERSARY).close(Outcome.SYNTHESIS, T0).outcome is Outcome.SYNTHESIS


# ---------------------------------------------------------------- messages


def test_message_is_an_explicit_bounded_record():
    item = message(audience=("i-web",), artifact_refs=("art-1",))
    assert RelationMessage.from_payload(item.to_payload()) == item
    check_message(relation(), item)
    assert {t.value for t in MsgType} == {
        "message", "proposal", "critique", "question", "decision", "result_summary", "handoff_note"}
    assert code_of(message, text="") == "relation_invalid"
    assert code_of(message, text="x" * (MAX_MESSAGE_CHARS + 1)) == "relation_invalid"
    assert code_of(message, audience=("i-lead",)) == "relation_invalid"
    assert code_of(RelationMessage.from_payload, {**item.to_payload(), "type": "thought"}) == "relation_invalid"
    assert code_of(RelationMessage.from_payload, {**item.to_payload(), "seq": 3}) == "relation_invalid"


def test_message_enters_only_an_open_board_from_a_participant():
    board = relation()
    assert code_of(check_message, board, message(author_instance_id="i-out")) == "relation_not_participant"
    assert code_of(check_message, board, message(audience=("i-out",))) == "relation_not_participant"
    assert code_of(check_message, board, message(relation_id="rel-other")) == "relation_invalid"
    assert code_of(check_message, board, message(created_at=T0 - timedelta(seconds=1))) == "relation_invalid"
    assert code_of(check_message, board.close(Outcome.ENDED, T1), message()) == "relation_closed"
    assert code_of(check_message, board, message(type=MsgType.HANDOFF_NOTE)) == "relation_message_type_invalid"
    handoff = relation(Kind.HANDOFF)
    check_message(handoff, message(relation_id=handoff.relation_id, author_instance_id="i-dev-a",
                                   type=MsgType.HANDOFF_NOTE))


def test_every_kind_accepts_explicit_messages_in_any_order():
    for kind in Kind:
        item = relation(kind)
        author, other = item.participant_ids[:2]
        for index, kind_of_message in enumerate([MsgType.DECISION, MsgType.QUESTION, MsgType.CRITIQUE]):
            check_message(item, message(message_id=f"m{index}", relation_id=item.relation_id,
                                        author_instance_id=[author, other][index % 2], type=kind_of_message))


# ---------------------------------------------------------------- confidentialité


@pytest.mark.parametrize("key", ["reasoning", "thinking", "chain_of_thought", "system_prompt", "raw_arguments",
                                 "tool_input", "providerThinking", "api_key"])
def test_private_keys_are_refused_at_any_depth(key):
    assert code_of(RelationMessage.from_payload, {**message().to_payload(), key: "x"}) == "relation_private_content"
    nested = relation(Kind.HANDOFF).to_payload()
    nested["handoff"] = {**nested["handoff"], key: "x"}
    assert code_of(AgentRelation.from_payload, nested) == "relation_private_content"
    deep = relation().to_payload()
    deep["participants"][0] = {**deep["participants"][0], "meta": {key: "x"}}
    assert code_of(AgentRelation.from_payload, deep) == "relation_private_content"


def test_contract_keys_are_never_mistaken_for_private_ones():
    keys = (rel._RELATION_KEYS | rel._MESSAGE_KEYS | rel._PACKET_KEYS | rel._PARTICIPANT_KEYS)
    assert not [key for key in keys if is_forbidden_key(key)]


@pytest.mark.parametrize("text", [
    "<thinking>je me demande si</thinking> Proposition : A",
    "Résultat </reasoning>",
    "<thinking>privé",
    "<scratchpad>notes",
    "<think>I secretly plan X</think>",
    "<thinking_process>x</thinking_process>",
    "<reasoning_content>x",
    "<reasoning-content>x",
    "&lt;thinking&gt;x",
    "&#60;think&#62;x",
    "<\uff54hinking>x",
    "\uff1cthinking\uff1ex",
    "<thin\u200bking>x",
    "<\u00adthinking>x",
    "< / Reasoning >",
    "<thinking>x",
    "<redacted_thinking>x",
    "<chain-of-thought>x",
    # Faux positif accepté : une prose qui cite la balise est refusée, le message dit comment la nommer.
    "La regex ne détecte pas la balise <thinking> des modèles",
])
def test_reasoning_tags_never_enter_a_board_or_a_packet(text):
    assert code_of(message, text=text) == "relation_private_content"
    assert code_of(replace, PACKET, completed_work=text) == "relation_private_content"
    assert code_of(relation, purpose=text) == "relation_private_content"
    with pytest.raises(RelationError) as info:
        check_collaboration_text("text", text, MAX_MESSAGE_CHARS)
    assert "without angle brackets" in str(info.value) and "never your reasoning" in str(info.value)


@pytest.mark.parametrize("text", [
    '[{"type": "thinking", "thinking": "..."}]',
    '{"reasoning": "x"}',
    '```json\n{"type":"content_block_delta","delta":{"thinking":"x"}}\n```',
    'Event: {"type":"thinking","thinking":"secret"}',
    '{"thinking": "secret"} trailing',
    '{"ok": true, "meta": {"system_prompt": "x"}}',
])
def test_json_quoting_a_private_field_is_refused(text):
    with pytest.raises(RelationError) as info:
        check_collaboration_text("text", text, MAX_MESSAGE_CHARS)
    assert info.value.code == "relation_private_content"
    assert info.value.field == "text"
    assert "remove reasoning" in str(info.value) and "secret" not in str(info.value)


def test_json_too_deep_to_check_is_refused():
    assert code_of(check_collaboration_text, "text", "[" * 3_000 + "]" * 3_000, 10_000) == "relation_raw_payload"
    assert code_of(check_collaboration_text, "text", '{"a":' * 40 + "1" + "}" * 40, 10_000) == "relation_raw_payload"


@pytest.mark.parametrize("text", [
    "[1] est la meilleure source", "{à voir} plus tard", "Décision : A, car plus simple.",
    '{"winner": "A", "score": 3}', '["A","B"]', '[1, 2, 3]', "{}", '"just a json string"',
    'Options: ["A", "B"]', 'Résultat :\n```json\n{"ok": true}\n```', "[ ] tâche à faire\n[x] faite",
    '{"type": "assistant", "message": {"content": []}}', "[thinking] x", "<thinker>", "le mot think",
    "Thinking: first I consider the options",
])
def test_ordinary_prose_and_plain_json_are_accepted(text):
    check_collaboration_text("text", text, MAX_MESSAGE_CHARS)


def test_raw_bytes_are_refused():
    assert code_of(rel.scan_private_keys, {"text": b"\x00"}) == "relation_raw_payload"


# ---------------------------------------------------------------- cohérence avec les instances


def inst(instance_id: str, role_id: str = "coder", *, mission_id: str | None = "m-root", **changes) -> AgentInstance:
    return AgentInstance(instance_id=instance_id, work_source="claude", work_external_id=f"toolu-{instance_id}",
                         role_id=role_id, created_at=changes.pop("created_at", T0), mission_id=mission_id, **changes)


INSTANCES = {
    "i-lead": inst("i-lead", "research"), "i-web": inst("i-web", "web-research"), "i-doc": inst("i-doc", "research"),
    "i-dev-a": inst("i-dev-a"), "i-dev-b": inst("i-dev-b"), "i-dev-c": inst("i-dev-c"),
    "i-qa": inst("i-qa", "qa"), "i-dev-2": inst("i-dev-2", "research", created_at=T1),
}


@pytest.mark.parametrize("kind", list(Kind))
def test_coherent_relations_pass(kind):
    check_relation_participants(relation(kind), INSTANCES)


def test_participants_are_known_and_never_ephemeral():
    missing = {k: v for k, v in INSTANCES.items() if k != "i-doc"}
    assert code_of(check_relation_participants, relation(), missing) == "relation_participant_missing"
    ephemeral = {**INSTANCES, "i-web": inst("i-web", "web-research", mission_id=None, ephemeral=True)}
    assert code_of(check_relation_participants, relation(), ephemeral) == "ephemeral_relation_participant"


def test_qa_reviewer_must_hold_a_qa_role_and_producers_must_not():
    not_qa = {**INSTANCES, "i-qa": inst("i-qa", "coder")}
    assert code_of(check_relation_participants, relation(Kind.QA), not_qa) == "qa_reviewer_role"
    reviewer_as_producer = relation(Kind.ADVERSARY, participants=(p("i-qa", Pos.PRODUCER), p("i-dev-a", Pos.PRODUCER)))
    assert code_of(check_relation_participants, reviewer_as_producer, INSTANCES) == "adversary_producer_is_reviewer"


def test_delegation_to_a_sub_mission():
    sub = {**INSTANCES, "i-web": inst("i-web", "web-research", mission_id="m-sub")}
    missions = {
        "m-root": Mission(mission_id="m-root", objective="Trouver un écran", owner_instance_id="i-lead",
                          created_at=T0),
        "m-sub": Mission(mission_id="m-sub", objective="Avis indépendants", owner_instance_id="i-web", created_at=T0,
                         parent_mission_id="m-root", root_mission_id="m-root"),
    }
    delegation = relation(Kind.DELEGATION, sub_mission_id="m-sub")
    check_relation_participants(delegation, sub, missions=missions)
    assert code_of(check_relation_participants, delegation, INSTANCES) == "delegation_sub_mission"
    orphan = {**missions, "m-sub": replace(missions["m-sub"], parent_mission_id="m-other", root_mission_id="m-other")}
    assert code_of(check_relation_participants, delegation, sub, missions=orphan) == "delegation_sub_mission"
    assert code_of(check_relation_participants, relation(), INSTANCES, missions={}) == "relation_mission_missing"


def test_handoff_goes_to_a_fresh_instance_of_the_same_mission_and_may_change_role():
    handoff = relation(Kind.HANDOFF)
    check_relation_participants(handoff, INSTANCES)  # coder -> research : un changement de rôle passe par un relais
    older = {**INSTANCES, "i-dev-2": inst("i-dev-2", created_at=T0 - timedelta(minutes=1))}
    assert code_of(check_relation_participants, handoff, older) == "handoff_successor_not_fresh"
    other = {**INSTANCES, "i-dev-2": inst("i-dev-2", mission_id="m-other", created_at=T1)}
    assert code_of(check_relation_participants, handoff, other) == "handoff_mission_mismatch"


def test_handoff_chain_never_reuses_a_successor_nor_loops():
    def handoff(relation_id: str, source: str, target: str, **changes) -> AgentRelation:
        return relation(Kind.HANDOFF, relation_id=relation_id,
                        participants=(p(source, Pos.PREDECESSOR), p(target, Pos.SUCCESSOR)), **changes)

    chain = [handoff("h1", "a", "b"), handoff("h2", "b", "c"), handoff("h3", "c", "d")]
    check_handoff_chain(chain + [relation()])
    assert code_of(check_handoff_chain, chain + [handoff("h4", "x", "c")]) == "handoff_successor_reused"
    assert code_of(check_handoff_chain, chain + [handoff("h4", "a", "e")]) == "handoff_fan_out"
    assert code_of(check_handoff_chain, [handoff("h1", "a", "b"), handoff("h2", "b", "a")]) == "handoff_cycle"
    withdrawn = handoff("h4", "a", "c").close(Outcome.WITHDRAWN, T1)
    check_handoff_chain(chain + [withdrawn])


def test_decode_is_strict_and_bounded():
    payload = relation().to_payload()
    with pytest.raises(RelationError) as info:
        AgentRelation.from_payload({**payload, "color": "red"})
    assert (info.value.code, info.value.field) == ("relation_invalid", "color")
    with pytest.raises(RelationError) as info:
        RelationMessage.from_payload({**message().to_payload(), "innerMonologue": "x"})
    assert (info.value.code, info.value.field) == ("relation_invalid", "innerMonologue")
    with pytest.raises(RelationError) as info:
        AgentRelation.from_payload({k: v for k, v in payload.items() if k != "mission_id"})
    assert info.value.field == "mission_id"
    assert code_of(AgentRelation.from_payload, {k: v for k, v in payload.items() if k != "purpose"}) \
        == "relation_invalid"
    assert code_of(AgentRelation.from_payload, {**payload, "participants": "i-a,i-b"}) == "relation_invalid"
    assert code_of(AgentRelation.from_payload, {**payload, "created_at": "2026-10-20T09:00:00"}) == "relation_invalid"
    assert code_of(AgentRelation.from_payload, [payload]) == "relation_invalid"
    deep: dict = {}
    cursor = deep
    for _ in itertools.repeat(None, 10):
        cursor["x"] = {}
        cursor = cursor["x"]
    assert code_of(AgentRelation.from_payload, {**payload, "nest": deep}) == "relation_invalid"


# ---------------------------------------------------------------- passe de corrections QA (PASS_WITH_NOTES)


def test_scope_depth_matches_the_mission_contract():
    from jarvis.domain.missions import MAX_MISSION_DEPTH

    assert rel.MAX_SCOPE_DEPTH == MAX_MISSION_DEPTH


MISSIONS = {
    "m-root": Mission(mission_id="m-root", objective="Choisir un écran", owner_instance_id="i-lead", created_at=T0),
    "m-a": Mission(mission_id="m-a", objective="Avis", owner_instance_id="i-web", created_at=T0,
                   parent_mission_id="m-root", root_mission_id="m-root"),
    "m-b": Mission(mission_id="m-b", objective="Prix", owner_instance_id="i-doc", created_at=T0,
                   parent_mission_id="m-root", root_mission_id="m-root"),
    "m-a1": Mission(mission_id="m-a1", objective="Forums", owner_instance_id="i-dev-a", created_at=T0,
                    parent_mission_id="m-a", root_mission_id="m-root"),
    "m-other": Mission(mission_id="m-other", objective="Autre", owner_instance_id="i-x", created_at=T0),
}


def test_communication_may_join_sister_sub_missions_but_not_another_mission():
    sisters = {**INSTANCES, "i-web": inst("i-web", "web-research", mission_id="m-a"),
               "i-doc": inst("i-doc", "research", mission_id="m-b")}
    check_relation_participants(relation(), sisters, missions=MISSIONS)
    # Sans les missions, une sous-mission ne se reconnaît pas : le message dit quoi fournir.
    with pytest.raises(RelationError) as info:
        check_relation_participants(relation(), sisters)
    assert info.value.code == "relation_mission_mismatch" and "pass missions" in str(info.value)
    outsider = {**sisters, "i-doc": inst("i-doc", "research", mission_id="m-other")}
    assert code_of(check_relation_participants, relation(), outsider, missions=MISSIONS) == "relation_mission_mismatch"
    unattached = {**INSTANCES, "i-doc": inst("i-doc", "research", mission_id=None)}
    assert code_of(check_relation_participants, relation(), unattached) == "relation_mission_mismatch"


def test_adversary_producers_stay_within_the_mission_tree():
    deep = {**INSTANCES, "i-dev-c": inst("i-dev-c", mission_id="m-a1")}
    check_relation_participants(relation(Kind.ADVERSARY), deep, missions=MISSIONS)
    other = {**INSTANCES, "i-dev-c": inst("i-dev-c", mission_id="m-other")}
    assert code_of(check_relation_participants, relation(Kind.ADVERSARY), other, missions=MISSIONS) \
        == "relation_mission_mismatch"


def test_qa_reviews_an_instance_of_the_mission_or_a_sub_mission():
    sub = {**INSTANCES, "i-dev-a": inst("i-dev-a", mission_id="m-a")}
    check_relation_participants(relation(Kind.QA), sub, missions=MISSIONS)
    # Le relecteur n'est pas contraint par le périmètre.
    check_relation_participants(relation(Kind.QA), {**sub, "i-qa": inst("i-qa", "qa", mission_id=None)},
                                missions=MISSIONS)
    other = {**INSTANCES, "i-dev-a": inst("i-dev-a", mission_id="m-other")}
    assert code_of(check_relation_participants, relation(Kind.QA), other, missions=MISSIONS) \
        == "relation_mission_mismatch"


def test_delegation_without_sub_mission_keeps_both_ends_in_the_mission():
    away = {**INSTANCES, "i-web": inst("i-web", "web-research", mission_id="m-a")}
    assert code_of(check_relation_participants, relation(Kind.DELEGATION), away, missions=MISSIONS) \
        == "relation_mission_mismatch"
    delegator_away = {**INSTANCES, "i-lead": inst("i-lead", "research", mission_id="m-a")}
    assert code_of(check_relation_participants, relation(Kind.DELEGATION), delegator_away) \
        == "relation_mission_mismatch"


def test_handoff_successor_must_not_have_taken_part_in_an_earlier_relation():
    handoff = relation(Kind.HANDOFF, created_at=T1 + timedelta(hours=5))
    instances = {**INSTANCES, "i-dev-2": inst("i-dev-2", created_at=T1)}
    earlier = relation(Kind.COMMUNICATION, relation_id="rel-early", created_at=T1,
                       participants=(p("i-lead", Pos.MEMBER), p("i-dev-2", Pos.MEMBER)))
    with pytest.raises(RelationError) as info:
        check_relation_participants(handoff, instances, relations=[earlier, handoff])
    assert info.value.code == "handoff_successor_not_fresh" and "rel-early" in str(info.value)
    # Une relation nouée après le relais, ou dans une autre mission, ne compte pas ; le relais lui-même non plus.
    later = replace(earlier, created_at=handoff.created_at + timedelta(minutes=1))
    elsewhere = replace(earlier, mission_id="m-other")
    check_relation_participants(handoff, instances, relations=[later, elsewhere, handoff])
    # Sondes de la QA : un pair qui travaille depuis des heures mais créé après le prédécesseur reste accepté
    # sans relations fournies ; sa fraîcheur réelle relève de l'aide de relais (Slice 06).
    check_relation_participants(handoff, instances)


def test_reply_targets_an_earlier_message_of_the_same_board():
    first = message()
    reply = message(message_id="msg-2", author_instance_id="i-web", type=MsgType.CRITIQUE,
                    created_at=T1 + timedelta(minutes=1), reply_to_message_id="msg-1")
    assert RelationMessage.from_payload(reply.to_payload()) == reply
    board = relation()
    check_message(board, reply, thread=[first])
    check_message(board, reply)  # sans le fil, la cible n'est pas vérifiable : Slice 03/06 la fournit
    assert code_of(check_message, board, reply, thread=[]) == "relation_reply_invalid"
    assert code_of(check_message, board, reply, thread=[replace(first, relation_id="rel-other")]) \
        == "relation_reply_invalid"
    assert code_of(check_message, board, reply, thread=[replace(first, created_at=T1 + timedelta(hours=1))]) \
        == "relation_reply_invalid"
    assert code_of(message, reply_to_message_id="msg-1") == "relation_reply_invalid"
