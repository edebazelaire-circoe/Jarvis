"""Conformance tests for Test Lab profiles and permission gates (docs/testlab.md, Profiles and permissions)."""

from __future__ import annotations

import json

import pytest

from jarvis.testlab.profiles import (
    Capability,
    CostBounds,
    DenialReason,
    PermissionDenial,
    ProfileName,
    ProfileSpec,
    ResourceGrant,
    check_profile_permission,
    profiles_by_name,
)
from jarvis.testlab.validation import FIELDS_MISMATCH, TestLabError
from tests.fakes.testlab import guided_profile, live_profile, virtual_profile

C = Capability


def test_profile_vocabulary_is_closed():
    assert [name.value for name in ProfileName] == ["virtual", "audio", "live", "hardware:auto", "hardware:guided"]
    with pytest.raises(ValueError):
        ProfileName("hardware")


@pytest.mark.parametrize("profile", [virtual_profile(), live_profile(), guided_profile(),
                                     ProfileSpec(ProfileName.AUDIO, "testlab.audio.chain", CostBounds(30, 0)),
                                     ProfileSpec(ProfileName.HARDWARE_AUTO, "testlab.hardware.auto", CostBounds(90, 0.2),
                                                 frozenset({C.AUDIO_OUTPUT_DEVICE, C.AUDIO_INPUT_DEVICE}))])
def test_profile_round_trip(profile):
    payload = json.loads(json.dumps(profile.to_dict()))
    assert ProfileSpec.from_dict(payload) == profile
    assert payload["requires"] == sorted(payload["requires"])


@pytest.mark.parametrize("name, requires, cost", [
    (ProfileName.VIRTUAL, {C.LLM_PROVIDER}, 0),
    (ProfileName.VIRTUAL, set(), 0.01),
    (ProfileName.AUDIO, {C.REALTIME_PROVIDER}, 0),
    (ProfileName.AUDIO, {C.HUMAN_PRESENCE}, 0),
    (ProfileName.LIVE, set(), 0.5),
    (ProfileName.LIVE, {C.REALTIME_PROVIDER, C.HUMAN_PRESENCE}, 0.5),
    (ProfileName.HARDWARE_AUTO, {C.REALTIME_PROVIDER}, 0.5),
    (ProfileName.HARDWARE_AUTO, {C.AUDIO_INPUT_DEVICE, C.HUMAN_PRESENCE}, 0.5),
    (ProfileName.HARDWARE_GUIDED, {C.AUDIO_INPUT_DEVICE}, 0.5),
    (ProfileName.HARDWARE_GUIDED, {C.HUMAN_PRESENCE}, 0.5),
])
def test_profile_name_implies_minimal_requirements(name, requires, cost):
    with pytest.raises(TestLabError):
        ProfileSpec(name, "testlab.impl", CostBounds(10, cost), frozenset(requires))


@pytest.mark.parametrize("implementation", ["import os", "testlab/virtual", "Testlab.virtual", "", None,
                                            "a." + "b" * 100])
def test_implementation_is_a_registered_name_never_code(implementation):
    with pytest.raises(TestLabError):
        ProfileSpec(ProfileName.VIRTUAL, implementation, CostBounds(10, 0))


@pytest.mark.parametrize("duration, cost", [(0, 0), (-1, 0), (86401, 0), (10, -0.1), (10, 1001), (float("inf"), 0),
                                            (True, 0), (10, "0")])
def test_cost_bounds_are_validated(duration, cost):
    with pytest.raises(TestLabError):
        CostBounds(duration, cost)


def test_profile_requires_must_be_a_frozenset_of_capabilities():
    with pytest.raises(TestLabError):
        ProfileSpec(ProfileName.LIVE, "testlab.live", CostBounds(10, 1), {C.LLM_PROVIDER})
    with pytest.raises(TestLabError):
        ProfileSpec(ProfileName.LIVE, "testlab.live", CostBounds(10, 1), frozenset({"llm_provider"}))


def test_profile_decode_is_strict():
    payload = live_profile().to_dict()
    with pytest.raises(TestLabError) as caught:
        ProfileSpec.from_dict({**payload, "command": "x"})
    assert caught.value.code == FIELDS_MISMATCH
    with pytest.raises(TestLabError):
        ProfileSpec.from_dict({**payload, "requires": ["realtime_provider", "realtime_provider"]})
    with pytest.raises(TestLabError):
        ProfileSpec.from_dict({**payload, "requires": ["gpu"]})
    with pytest.raises(TestLabError):
        ProfileSpec.from_dict({**payload, "name": "hardware"})
    with pytest.raises(TestLabError):
        ProfileSpec.from_dict({**payload, "cost": {"max_duration_s": 1, "max_cost_usd": 0, "extra": 1}})


def test_virtual_runs_with_the_default_grant():
    decision = check_profile_permission(virtual_profile(), ResourceGrant())
    assert decision.allowed
    assert decision.to_dict() == {"profile": "virtual", "allowed": True, "denials": []}


def test_denial_lists_everything_missing_in_a_stable_order():
    decision = check_profile_permission(guided_profile(), ResourceGrant(frozenset({C.AUDIO_INPUT_DEVICE}), 0.25, 60))
    assert not decision.allowed
    assert decision.denials == (
        PermissionDenial(DenialReason.CAPABILITY_MISSING, capability=C.REALTIME_PROVIDER),
        PermissionDenial(DenialReason.CAPABILITY_MISSING, capability=C.AUDIO_OUTPUT_DEVICE),
        PermissionDenial(DenialReason.CAPABILITY_MISSING, capability=C.HUMAN_PRESENCE),
        PermissionDenial(DenialReason.COST_BUDGET_EXCEEDED, required=1, granted=0.25),
        PermissionDenial(DenialReason.DURATION_BUDGET_EXCEEDED, required=600, granted=60),
    )
    assert json.loads(json.dumps(decision.to_dict()))["denials"][3] == {
        "reason": "cost_budget_exceeded", "capability": None, "required": 1, "granted": 0.25}


def test_full_grant_allows_live_and_no_duration_budget_means_unbounded():
    grant = ResourceGrant(frozenset(Capability), 5)
    assert check_profile_permission(live_profile(), grant).allowed
    assert check_profile_permission(guided_profile(), grant).allowed
    assert not check_profile_permission(live_profile(), ResourceGrant(frozenset(Capability), 5, 119)).allowed


def test_grant_round_trip_and_validation():
    grant = ResourceGrant(frozenset({C.LLM_PROVIDER, C.REALTIME_PROVIDER}), 2.5, 300)
    assert ResourceGrant.from_dict(json.loads(json.dumps(grant.to_dict()))) == grant
    with pytest.raises(TestLabError):
        ResourceGrant.from_dict({**grant.to_dict(), "unlimited": True})
    for bad in (dict(max_cost_usd=-1), dict(max_duration_s=-5), dict(capabilities={C.LLM_PROVIDER})):
        with pytest.raises(TestLabError):
            ResourceGrant(**bad)
    with pytest.raises(TestLabError):
        check_profile_permission(virtual_profile(), {"capabilities": []})


def test_profiles_by_name_rejects_duplicates():
    assert list(profiles_by_name([live_profile(), virtual_profile()])) == [ProfileName.LIVE, ProfileName.VIRTUAL]
    with pytest.raises(TestLabError):
        profiles_by_name([virtual_profile(), virtual_profile()])
