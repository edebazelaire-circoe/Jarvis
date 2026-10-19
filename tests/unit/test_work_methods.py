"""Work Methods : des heuristiques versionnées, jamais un plan d'exécution (D06), promues explicitement (D24)."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timezone

import pytest

from jarvis.domain import subagent_roles
from jarvis.domain.work_methods import (
    FORBIDDEN_PLAN_KEYS, MAX_PRINCIPLES, USEFUL_RELATION_KINDS, MethodError, MethodOrigin, MethodProvenance,
    WorkMethod, check_revision, check_role_methods, latest_methods,
)

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)


def method(**changes) -> WorkMethod:
    values = {
        "method_id": "comparative-research",
        "version": 1,
        "name": "Recherche comparée",
        "summary": "Comparer plusieurs sources avant de recommander.",
        "role_ids": ("research-lead",),
        "principles": ("Chercher des sources indépendantes du fabricant.", "Confronter les sources qui divergent."),
        "quality_checks": ("Chaque affirmation de la synthèse a sa source.",),
        "useful_relations": ("delegation", "qa"),
        **changes,
    }
    return WorkMethod(**values)


def test_a_method_has_no_ordered_step_field():
    names = {item.name for item in fields(WorkMethod)}
    assert not names & FORBIDDEN_PLAN_KEYS
    assert method().key == "comparative-research@1"


@pytest.mark.parametrize("key", sorted(FORBIDDEN_PLAN_KEYS))
def test_a_plan_shaped_payload_is_refused_by_name(key):
    with pytest.raises(MethodError) as error:
        WorkMethod.from_payload({**method().to_payload(), key: ["a", "b"]})
    assert error.value.code == "work_method_is_not_a_plan"


def test_round_trip_and_strict_decode():
    original = method()
    assert WorkMethod.from_payload(original.to_payload()) == original
    with pytest.raises(MethodError):
        WorkMethod.from_payload({**original.to_payload(), "extra": 1})
    with pytest.raises(MethodError):
        WorkMethod.from_payload({"method_id": "x"})


def test_bounds_and_values():
    with pytest.raises(MethodError):
        method(principles=())
    with pytest.raises(MethodError):
        method(principles=tuple(f"p{index}" for index in range(MAX_PRINCIPLES + 1)))
    with pytest.raises(MethodError):
        method(principles=("même", "même"))
    with pytest.raises(ValueError):
        method(principles=("x" * 301,))
    with pytest.raises(MethodError):
        method(useful_relations=("vote",))
    with pytest.raises(MethodError):
        method(method_id="Recherche Comparée")
    with pytest.raises(MethodError):
        method(version=0)
    with pytest.raises(MethodError):
        method(role_ids=())
    with pytest.raises(MethodError):
        method(role_ids=("Direction",))
    assert set(USEFUL_RELATION_KINDS) == {"delegation", "communication", "adversary", "qa", "handoff"}


def test_promotion_is_explicit_and_traced():
    promoted = MethodProvenance(origin=MethodOrigin.PROMOTED, candidate_id="cand-1", promoted_by="user",
                                promoted_at=T0, evidence_refs=("m-1", "qa-7"))
    assert method(provenance=promoted).provenance.origin is MethodOrigin.PROMOTED
    assert MethodProvenance.from_payload(promoted.to_payload()) == promoted
    with pytest.raises(MethodError):
        MethodProvenance(origin=MethodOrigin.PROMOTED, candidate_id="cand-1", promoted_at=T0)  # sans auteur
    with pytest.raises(MethodError):
        MethodProvenance(origin=MethodOrigin.BUILTIN, candidate_id="cand-1")
    with pytest.raises(MethodError):
        MethodProvenance(origin=MethodOrigin.PROMOTED, candidate_id="c", promoted_by="user",
                         promoted_at=datetime(2026, 10, 20))


def test_a_version_is_never_rewritten_silently():
    first = method()
    check_revision(first, first)
    check_revision(first, replace(first, version=2, principles=("Autre principe.",)))
    with pytest.raises(MethodError) as error:
        check_revision(first, replace(first, principles=("Autre principe.",)))
    assert error.value.code == "work_method_version_conflict"
    with pytest.raises(MethodError):
        check_revision(first, replace(first, version=3))
    with pytest.raises(MethodError):
        check_revision(first, replace(first, method_id="other-method"))
    with pytest.raises(MethodError):
        latest_methods([first, replace(first, summary="Autre.")])
    assert latest_methods([first, replace(first, version=2)])["comparative-research"].version == 2


def test_roles_cite_only_existing_applicable_methods():
    lead = replace(subagent_roles.role_by_id("research-lead"), work_methods=("comparative-research",),
                   default_work_method="comparative-research")
    check_role_methods([lead], [method()])
    with pytest.raises(MethodError) as error:
        check_role_methods([lead], [])
    assert error.value.code == "work_method_unknown"
    coder = replace(subagent_roles.role_by_id("coder"), work_methods=("comparative-research",))
    with pytest.raises(MethodError) as error:
        check_role_methods([coder], [method()])
    assert error.value.code == "work_method_not_applicable"
    # Le registre livré ne cite encore aucune méthode : le catalogue est la Slice 04.
    check_role_methods(subagent_roles.ROLES, [])
