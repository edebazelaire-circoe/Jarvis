"""Candidats de Work Method appris de l'historique et promotion explicite : le domaine (Slice 12).

Arbres de mission construits en mémoire avec les valeurs du domaine : jamais une base réelle.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from jarvis.domain.agent_relations import (
    AgentRelation, AgentRelationKind as K, ParticipantPosition as P, RelationOutcome as O, RelationParticipant,
)
from jarvis.domain.mission_history import (
    AgentDeclarationFact, MissionHistoryError, MissionTree, OwnershipChange, StoredInstance,
)
from jarvis.domain.missions import AgentInstance, Mission, MissionStatus
from jarvis.domain.subagent_roles import RoleStatus
from jarvis.domain.work_method_learning import (
    DEFAULT_THRESHOLDS, HUMAN_PROMOTERS, ApproachSignature, CandidateStatus as S, CandidateThresholds,
    QualityRating as Q, ScanReport, detect_candidates, promoted_method, rate_use, uses_from_tree,
)
from jarvis.domain.work_methods import (
    BUILTIN_METHODS, FORBIDDEN_PLAN_KEYS, MethodError, MethodOrigin, WorkMethod, check_revision, latest_methods,
)
from tests.fakes.mission_history import at

CATALOGUE = latest_methods(BUILTIN_METHODS)
NOW = at(120)


def _fact(tool_use_id: str, role: str, *, mission_id: str | None, owner: bool, method: str | None,
          chosen: bool = False) -> AgentDeclarationFact:
    return AgentDeclarationFact(tool_use_id=tool_use_id, declared_at=at(0), role_id=role,
                                role_status=RoleStatus.DECLARED, role_marker=role, label="Tâche", mission_id=mission_id,
                                mission_owner=owner, work_method=method, work_method_chosen=chosen)


def _instance(instance_id: str, role: str, mission_id: str, *, owner: bool = False, parent: str | None = None,
              method: str | None = None, chosen: bool = False, declared: bool = True) -> StoredInstance:
    inst = AgentInstance(instance_id=instance_id, work_source="claude", work_external_id=f"toolu_{instance_id}",
                         role_id=role, created_at=at(0), role_marker=role if role != "undeclared" else None,
                         mission_id=mission_id, mission_owner=owner, parent_instance_id=parent)
    fact = _fact(f"toolu_{instance_id}", role, mission_id=mission_id, owner=owner, method=method, chosen=chosen)
    return StoredInstance(inst, declaration=fact if declared else None)


def _relation(relation_id: str, kind: K, mission_id: str, pairs, outcome: O | None, *, minute: float = 5,
              closed_by: str | None = None, winner: str | None = None) -> AgentRelation:
    relation = AgentRelation(relation_id=relation_id, kind=kind, mission_id=mission_id,
                             participants=tuple(RelationParticipant(i, p) for i, p in pairs),
                             purpose=f"But de {relation_id}", created_at=at(1))
    if outcome is None:
        return relation
    return relation.close(outcome, at(minute), closed_by=closed_by, winner_instance_id=winner)


def tree(mid: str, *, role: str = "research-lead", method: str | None = "deep-research@1", chosen: bool = False,
         kinds: tuple[str, ...] = ("delegation", "adversary"), qa: tuple[O, ...] = (O.APPROVED,),
         status: MissionStatus = MissionStatus.COMPLETED, declared: bool = True, members: int = 2,
         withdrawn: tuple[str, ...] = ()) -> MissionTree:
    """Une mission close : un propriétaire `role`, des membres, les relations demandées, les verdicts QA donnés."""

    owner, reviewer = f"o-{mid}", f"q-{mid}"
    workers = [f"w{n}-{mid}" for n in range(members)]
    instances = [_instance(owner, role, mid, owner=True, method=method, chosen=chosen, declared=declared),
                 _instance(reviewer, "qa", mid, parent=owner),
                 *(_instance(w, "web-research", mid, parent=owner) for w in workers)]
    relations: list[AgentRelation] = []
    for kind in kinds:
        if kind == "delegation":
            relations.append(_relation(f"rd-{mid}", K.DELEGATION, mid, [(owner, P.DELEGATOR), (workers[0], P.DELEGATEE)],
                                       O.RETURNED))
        elif kind == "adversary":
            relations.append(_relation(f"ra-{mid}", K.ADVERSARY, mid, [(w, P.PRODUCER) for w in workers], O.WINNER,
                                       closed_by=owner, winner=workers[0]))
        elif kind == "communication":
            relations.append(_relation(f"rc-{mid}", K.COMMUNICATION, mid, [(w, P.MEMBER) for w in workers], O.ENDED))
    for kind in withdrawn:
        relations.append(_relation(f"rx-{kind}-{mid}", K.COMMUNICATION, mid, [(w, P.MEMBER) for w in workers],
                                   O.WITHDRAWN))
    for n, verdict in enumerate(qa):
        relations.append(_relation(f"rq{n}-{mid}", K.QA, mid, [(reviewer, P.REVIEWER), (workers[0], P.REVIEWED)],
                                   verdict, minute=10 + n, closed_by=reviewer))
    mission = Mission(mission_id=mid, objective=f"Objectif {mid}", owner_instance_id=owner, created_at=at(0))
    if status is not MissionStatus.OPEN:
        mission = mission.close(status, at(30))
    return MissionTree(root_mission_id=mid, missions=(mission,), instances=tuple(instances),
                       relations=tuple(relations), ownership=(OwnershipChange(mid, owner, at(0)),))


def uses_of(*trees: MissionTree, report: ScanReport | None = None):
    return [use for t in trees for use in uses_from_tree(t, report)]


def only(candidates):
    assert len(candidates) == 1, candidates
    return candidates[0]


# ------------------------------------------------------------------ preuves et qualité


def test_one_successful_run_is_never_a_candidate():
    candidate = only(detect_candidates(uses_of(tree("m1")), CATALOGUE))
    assert (candidate.status, candidate.reason) == (S.OBSERVING, "not_enough_uses")
    assert (candidate.uses, candidate.positive) == (1, 1)


def test_repetition_plus_positive_quality_makes_a_candidate_with_its_evidence():
    # m3 : relue (constats) sans verdict d'adéquation -> non notée, même approche.
    candidate = only(detect_candidates(uses_of(tree("m1"), tree("m2"), tree("m3", qa=(O.FINDINGS,))), CATALOGUE))
    assert (candidate.status, candidate.reason) == (S.CANDIDATE, "thresholds_met")
    assert (candidate.uses, candidate.positive, candidate.negative, candidate.unrated) == (3, 2, 0, 1)
    assert candidate.signature == ApproachSignature("research-lead", "deep-research", ("delegation", "adversary", "qa"))
    # Les preuves : les missions bonnes et la relation QA qui a approuvé, des ids seulement.
    assert set(candidate.evidence_refs) == {"m1", "rq0-m1", "m2", "rq0-m2"}
    assert "m3" not in candidate.evidence_refs
    assert candidate.base_method_key == "deep-research@1"
    assert candidate.draft["version"] == 2
    assert candidate.draft["useful_relations"] == ["delegation", "adversary", "qa"]
    assert candidate.draft["principles"] == list(CATALOGUE["deep-research"].principles)
    assert "provenance" not in candidate.draft


def test_a_repeated_approach_with_poor_outcomes_is_never_proposed():
    trees = [tree("m1"), tree("m2", qa=(O.REJECTED,)), tree("m3", qa=(O.CORRECTION_REQUESTED,)),
             tree("m4", status=MissionStatus.FAILED)]
    candidate = only(detect_candidates(uses_of(*trees), CATALOGUE))
    assert (candidate.status, candidate.reason) == (S.INSUFFICIENT_QUALITY, "positive_share_below_threshold")
    assert (candidate.positive, candidate.negative) == (1, 3)


def test_completion_without_a_verdict_is_not_approval():
    trees = [tree(f"m{n}", qa=()) for n in range(6)]
    uses = uses_of(*trees)
    assert {(use.rating, use.rating_reason) for use in uses} == {(Q.UNRATED, "no_quality_evidence")}
    candidate = only(detect_candidates(uses, CATALOGUE))
    assert (candidate.status, candidate.reason) == (S.OBSERVING, "not_enough_quality_evidence")
    assert candidate.evidence_refs == ()


@pytest.mark.parametrize(("status", "qa", "expected"), [
    (MissionStatus.FAILED, (O.APPROVED,), (Q.NEGATIVE, "mission_failed")),
    (MissionStatus.CANCELLED, (), (Q.NEGATIVE, "mission_cancelled")),
    (MissionStatus.COMPLETED, (O.CORRECTION_REQUESTED, O.APPROVED), (Q.POSITIVE, "qa_approved")),
    (MissionStatus.COMPLETED, (O.APPROVED, O.REJECTED), (Q.NEGATIVE, "qa_rejected")),
    (MissionStatus.COMPLETED, (O.FINDINGS,), (Q.UNRATED, "qa_findings")),
    (MissionStatus.COMPLETED, (O.WITHDRAWN,), (Q.UNRATED, "no_quality_evidence")),
])
def test_quality_comes_from_the_mission_end_and_the_last_qa_verdict(status, qa, expected):
    t = tree("m1", status=status, qa=qa)
    rating, reason, refs = rate_use(t.missions[0], t.relations)
    assert (rating, reason) == expected
    if rating is not Q.NEGATIVE or reason.startswith("qa_"):
        assert all(ref.startswith("rq") for ref in refs)


def test_an_approach_already_described_by_its_method_has_nothing_to_learn():
    trees = [tree(f"m{n}", kinds=("delegation",)) for n in range(3)]  # deep-research cite déjà délégation et QA
    candidate = only(detect_candidates(uses_of(*trees), CATALOGUE))
    assert (candidate.status, candidate.reason) == (S.MATCHES_METHOD, "nothing_beyond_the_method")


def test_the_recurrence_key_is_an_approach_not_a_topology():
    small = tree("m1", members=2)
    large = tree("m2", members=5)
    assert {use.signature for use in uses_of(small, large)} == {
        ApproachSignature("research-lead", "deep-research", ("delegation", "adversary", "qa"))}
    # La version de la méthode et le choix explicite ne changent pas l'approche.
    v_other = tree("m3", method="deep-research@1", chosen=True)
    assert uses_of(v_other)[0].signature == uses_of(small)[0].signature
    assert uses_of(v_other)[0].method_chosen is True


def test_withdrawn_relations_and_unusable_missions_are_left_out_and_counted():
    report = ScanReport()
    uses = uses_of(tree("m1", withdrawn=("communication",)), tree("m2", status=MissionStatus.OPEN),
                   tree("m3", declared=False), report=report)
    assert [use.mission_id for use in uses] == ["m1"]
    assert "communication" not in uses[0].signature.relation_kinds
    assert report.skipped == {"mission_open": 1, "declaration_missing": 1}
    assert (report.missions, report.uses) == (3, 1)


def test_an_approach_without_qa_is_another_approach_and_never_rated_good():
    """Sans relation QA, aucune preuve de qualité : l'approche « sans relecture » ne devient jamais candidate."""

    uses = uses_of(*(tree(f"m{n}", qa=()) for n in range(5)))
    assert {use.signature.relation_kinds for use in uses} == {("delegation", "adversary")}
    assert only(detect_candidates(uses, CATALOGUE)).status is S.OBSERVING


def test_a_mission_without_a_method_proposes_no_draft_text():
    trees = [tree(f"m{n}", role="coder", method=None, kinds=("delegation",)) for n in range(3)]
    candidate = only(detect_candidates(uses_of(*trees), CATALOGUE))
    assert candidate.status is S.CANDIDATE
    assert candidate.signature.method_id is None and candidate.draft is None


def test_thresholds_are_data_and_one_run_can_never_be_enough():
    assert DEFAULT_THRESHOLDS.to_payload() == {"min_uses": 3, "min_positive": 2, "min_positive_share": 0.75,
                                               "scan_root_missions": 64}
    for bad in ({"min_uses": 1}, {"min_positive": 0}, {"min_positive": 4}, {"min_positive_share": 0.5},
                {"scan_root_missions": 0}):
        with pytest.raises(ValueError):
            CandidateThresholds(**bad)
    lenient = CandidateThresholds(min_uses=2, min_positive=1)
    assert only(detect_candidates(uses_of(tree("m1"), tree("m2", qa=(O.FINDINGS,))), CATALOGUE,
                                  thresholds=lenient)).status is S.CANDIDATE


# ------------------------------------------------------------------ promotion


def _eligible():
    return only(detect_candidates(uses_of(tree("m1"), tree("m2"), tree("m3")), CATALOGUE))


def _promote(candidate, payload=None, **kwargs):
    defaults = {"latest": CATALOGUE["deep-research"], "expected_version": 1, "promoted_by": "user",
                "promoted_at": NOW}
    return promoted_method(candidate, dict(candidate.draft) if payload is None else payload, **{**defaults, **kwargs})


def test_a_promotion_publishes_the_next_version_with_its_provenance():
    candidate = _eligible()
    method = _promote(candidate)
    assert isinstance(method, WorkMethod) and method.key == "deep-research@2"
    check_revision(CATALOGUE["deep-research"], method)
    provenance = method.provenance
    assert provenance.origin is MethodOrigin.PROMOTED
    assert (provenance.candidate_id, provenance.promoted_by) == (candidate.candidate_id, "user")
    assert isinstance(provenance.promoted_at, datetime) and provenance.promoted_at.tzinfo is not None
    assert provenance.evidence_refs == candidate.evidence_refs
    # Des heuristiques, jamais un plan : aucune clé de plan dans ce qui est publié.
    assert not FORBIDDEN_PLAN_KEYS & method.to_payload().keys()


@pytest.mark.parametrize("promoter", ["qa", "research-lead", "jarvis", "brain", "agent"])
def test_no_agent_can_promote(promoter):
    assert promoter not in HUMAN_PROMOTERS
    with pytest.raises(MethodError) as caught:
        _promote(_eligible(), promoted_by=promoter)
    assert caught.value.code == "work_method_promoter_not_human"


def test_only_an_eligible_candidate_is_promoted():
    observing = only(detect_candidates(uses_of(tree("m1")), CATALOGUE))
    with pytest.raises(MethodError) as caught:
        promoted_method(observing, {}, latest=None, expected_version=0, promoted_by="user", promoted_at=NOW)
    assert caught.value.code == "work_method_candidate_not_eligible"


@pytest.mark.parametrize("key", sorted(FORBIDDEN_PLAN_KEYS))
def test_a_candidate_that_would_be_a_plan_is_refused(key):
    candidate = _eligible()
    with pytest.raises(MethodError) as caught:
        _promote(candidate, {**candidate.draft, key: ["chercher", "puis comparer"]})
    assert caught.value.code == "work_method_is_not_a_plan"


def test_the_caller_never_writes_the_provenance():
    candidate = _eligible()
    with pytest.raises(MethodError):
        _promote(candidate, {**candidate.draft, "provenance": {"origin": "builtin"}})


@pytest.mark.parametrize(("change", "kwargs", "code"), [
    ({}, {"expected_version": 0}, "work_method_revision_conflict"),
    ({"version": 3}, {}, "work_method_revision_invalid"),
    ({"version": 1}, {}, "work_method_version_conflict"),
    ({"role_ids": ["qa"]}, {}, "work_method_not_applicable"),
    ({"principles": []}, {}, "work_method_invalid"),
])
def test_the_revision_is_optimistic_and_never_overwrites(change, kwargs, code):
    candidate = _eligible()
    with pytest.raises(MethodError) as caught:
        _promote(candidate, {**candidate.draft, **change}, **kwargs)
    assert caught.value.code == code


def test_a_new_method_starts_at_version_one_and_is_written_by_the_person():
    trees = [tree(f"m{n}", role="coder", method=None, kinds=("delegation",)) for n in range(3)]
    candidate = only(detect_candidates(uses_of(*trees), CATALOGUE))
    payload = {"method_id": "delegated-fix", "version": 1, "name": "Correction déléguée",
               "summary": "Déléguer la reproduction, garder la correction.", "role_ids": ["coder"],
               "principles": ["Confier la reproduction à un agent dédié quand elle est longue."],
               "useful_relations": ["delegation", "qa"]}
    method = promoted_method(candidate, payload, latest=None, expected_version=0, promoted_by="user",
                             promoted_at=NOW)
    assert method.key == "delegated-fix@1" and method.provenance.origin is MethodOrigin.PROMOTED
    with pytest.raises(MethodError) as caught:
        promoted_method(candidate, {**payload, "version": 2}, latest=None, expected_version=0, promoted_by="user",
                        promoted_at=NOW)
    assert caught.value.code == "work_method_revision_invalid"


def test_a_promoted_candidate_is_reported_as_promoted_and_not_proposed_again():
    candidate = _eligible()
    method = _promote(candidate)
    again = only(detect_candidates(uses_of(tree("m1"), tree("m2"), tree("m3")),
                                   latest_methods((*BUILTIN_METHODS, method)), promoted=(method,)))
    assert (again.status, again.promoted_keys) == (S.PROMOTED, ("deep-research@2",))
    with pytest.raises(MethodError) as caught:
        _promote(again, latest=method, expected_version=2)
    assert caught.value.code == "work_method_candidate_not_eligible"


# ------------------------------------------------------------------ fait de déclaration


def test_the_declaration_fact_carries_the_method_only_when_one_was_applied():
    plain = _fact("toolu_a", "coder", mission_id=None, owner=False, method=None)
    assert "work_method" not in plain.to_payload() and "work_method_chosen" not in plain.to_payload()
    chosen = _fact("toolu_b", "research-lead", mission_id="m1", owner=True, method="quick-research@1", chosen=True)
    assert AgentDeclarationFact.from_payload(chosen.to_payload()) == chosen
    assert chosen.to_payload()["work_method"] == "quick-research@1"
    with pytest.raises(MissionHistoryError):
        replace(plain, work_method="quick-research")
    with pytest.raises(MissionHistoryError):
        replace(plain, work_method_chosen=True)
