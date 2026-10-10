"""Plein écran générique de surface : vocabulaire et machine à états purs (studio de présentation, Slice 03).

Ce que ce fichier épingle, sans E/S :

- la table de transitions est **fermée** : tout couple (état, événement) absent est refusé (409), jamais deviné ;
- `needs_gesture` est un état d'attente, pas une erreur, et seul un événement du navigateur mène à `entered` ;
- les états rapportés par la page se traduisent en événements, `exited` pendant l'armement étant un retrait ;
- les demandes et les reçus sont validés : champs inconnus, écrans hors liste, échéance hors bornes, refus sans code.
"""

from __future__ import annotations

import itertools

import pytest

from jarvis.domain import surface_fullscreen as fs
from jarvis.domain.surface_fullscreen import SurfaceFullscreenError


def test_the_transition_table_is_closed_and_every_state_is_reachable():
    for (state, event), target in fs.TRANSITIONS.items():
        assert state in fs.STATES and event in fs.EVENTS and target in fs.STATES
    for state, event in itertools.product(fs.STATES, fs.EVENTS):
        if (state, event) in fs.TRANSITIONS:
            assert fs.next_state(state, event) == fs.TRANSITIONS[(state, event)]
        else:
            with pytest.raises(SurfaceFullscreenError) as caught:
                fs.next_state(state, event)
            assert caught.value.code == fs.INVALID_TRANSITION and caught.value.status == 409
    assert {target for target in fs.TRANSITIONS.values()} == set(fs.STATES)
    assert fs.DEFAULT_STATE in fs.STATES


def test_a_voice_request_arms_and_only_the_browser_can_enter():
    """R4 : une demande de la voix ne peut pas entrer ; elle arme, et `entered` n'arrive que de `fullscreenchange`."""

    assert fs.next_state("exited", "request_enter") == "needs_gesture"
    # Aucun événement de demande ne mène directement à `entered`.
    for state in fs.STATES:
        assert fs.TRANSITIONS.get((state, "request_enter")) != "entered" or state == "entered"
    assert fs.next_state("needs_gesture", "browser_entered") == "entered"
    assert fs.next_state("needs_gesture", "deadline") == "expired"
    assert fs.next_state("needs_gesture", "cancel") == "exited"
    assert fs.next_state("needs_gesture", "browser_denied") == "refused"


def test_escape_leaves_and_a_refusal_never_kicks_out_of_fullscreen():
    assert fs.next_state("entered", "browser_exited") == "exited"          # Échap, côté navigateur
    assert fs.next_state("entered", "browser_denied") == "entered"         # une 2e demande refusée ne sort pas
    assert fs.next_state("entered", "request_enter") == "entered"          # idempotent
    for resting in ("refused", "expired", "unsupported"):
        assert fs.next_state(resting, "request_enter") == "needs_gesture"  # on peut redemander
        assert fs.next_state(resting, "browser_exited") == "exited"
    # Un délai ou une annulation hors armement est une incohérence, pas un état.
    for state in ("exited", "entered", "refused", "expired", "unsupported"):
        for event in ("deadline", "cancel"):
            with pytest.raises(SurfaceFullscreenError):
                fs.next_state(state, event)


def test_reported_states_translate_to_events_and_exited_while_armed_is_a_cancel():
    assert fs.event_for_report("needs_gesture", "exited") == "cancel"
    assert fs.event_for_report("entered", "exited") == "browser_exited"
    assert fs.event_for_report("exited", "exited") == "browser_exited"
    assert fs.event_for_report("needs_gesture", "entered") == "browser_entered"
    assert fs.event_for_report("needs_gesture", "refused") == "browser_denied"
    assert fs.event_for_report("needs_gesture", "expired") == "deadline"
    assert fs.event_for_report("exited", "unsupported") == "unsupported"
    assert fs.event_for_report("refused", "needs_gesture") == "request_enter"
    with pytest.raises(SurfaceFullscreenError) as caught:
        fs.event_for_report("exited", "overlay")
    assert caught.value.code == fs.BAD_RECEIPT


def test_every_state_has_a_sentence_the_agent_can_say():
    assert set(fs.STATE_EXPLANATIONS) == set(fs.STATES)
    # Le cas qui ne doit jamais être annoncé comme un succès.
    assert "clic" in fs.STATE_EXPLANATIONS["needs_gesture"] and "Ne dis pas" in fs.STATE_EXPLANATIONS["needs_gesture"]


def test_request_defaults_and_exit_takes_no_field():
    enter = fs.parse_request({"action": "enter"})
    assert (enter.action, enter.object_id, enter.display, enter.keys, enter.arm_s) == (
        "enter", None, "current", "none", fs.ARM_DEFAULT_S)
    assert enter.to_wire() == {"action": "enter", "object_id": None, "display": "current", "keys": "none",
                               "arm_s": fs.ARM_DEFAULT_S}
    full = fs.parse_request({"action": "enter", "object_id": "obj_1", "display": 2, "keys": "none", "arm_s": 10})
    assert (full.object_id, full.display, full.keys, full.arm_s) == ("obj_1", 2, "none", 10.0)
    assert fs.parse_request({"action": "enter", "display": "other"}).display == "other"
    assert fs.parse_request({"action": "exit"}).to_wire() == {"action": "exit"}


@pytest.mark.parametrize("raw", [
    None, [], "enter", {}, {"action": "maximize"}, {"action": "enter", "force": True},
    {"action": "exit", "object_id": "x"},
    {"action": "enter", "object_id": 3}, {"action": "enter", "object_id": "a b"}, {"action": "enter", "object_id": ""},
    {"action": "enter", "display": "left"}, {"action": "enter", "display": -1}, {"action": "enter", "display": True},
    {"action": "enter", "display": fs.MAX_DISPLAY_INDEX + 1}, {"action": "enter", "display": 1.5},
    {"action": "enter", "keys": "frame"},
    {"action": "enter", "arm_s": 0}, {"action": "enter", "arm_s": fs.ARM_MIN_S - 0.1},
    {"action": "enter", "arm_s": fs.ARM_MAX_S + 1}, {"action": "enter", "arm_s": "30"}, {"action": "enter", "arm_s": True},
])
def test_invalid_requests_are_refused_with_a_stable_code(raw):
    with pytest.raises(SurfaceFullscreenError) as caught:
        fs.parse_request(raw)
    assert caught.value.code == fs.BAD_REQUEST and caught.value.status == 400


def test_arm_deadline_is_always_bounded_so_a_waiting_state_cannot_last_forever():
    assert 0 < fs.ARM_MIN_S <= fs.ARM_DEFAULT_S <= fs.ARM_MAX_S < float("inf")
    assert fs.parse_request({"action": "enter", "arm_s": fs.ARM_MAX_S}).arm_s == fs.ARM_MAX_S
    assert fs.parse_request({"action": "enter", "arm_s": fs.ARM_MIN_S}).arm_s == fs.ARM_MIN_S


def test_a_receipt_names_what_the_page_observed_and_cannot_invent_a_code():
    armed = fs.parse_receipt("enter", {"state": "needs_gesture", "display_selection": "denied", "object_id": "obj_1"})
    assert armed == {"state": "needs_gesture", "code": None, "reason": None, "display_selection": "denied",
                     "object_id": "obj_1", "id": None}
    refused = fs.parse_receipt("enter", {"state": "refused", "code": fs.DENIED, "reason": "x" * 999})
    assert refused["code"] == fs.DENIED and len(refused["reason"]) == fs.MAX_REASON_CHARS
    assert fs.parse_receipt("exit", {"state": "exited"})["state"] == "exited"
    for action, raw in (
        ("enter", None), ("enter", "entered"), ("enter", {}), ("enter", {"state": "exited"}),
        ("enter", {"state": "expired", "code": fs.ARM_EXPIRED}),                 # pas un état de reçu de remise
        ("enter", {"state": "refused"}),                                         # refus sans cause
        ("enter", {"state": "unsupported"}),
        ("enter", {"state": "refused", "code": "fullscreen_je_sais_pas"}),
        ("enter", {"state": "needs_gesture", "reason": 7}),
        ("enter", {"state": "needs_gesture", "display_selection": "everything"}),
        ("enter", {"state": "needs_gesture", "extra": 1}),
        ("enter", {"state": "needs_gesture", "object_id": "a b"}),
        ("enter", {"state": "needs_gesture", "id": "too"}),
        ("exit", {"state": "needs_gesture"}),
    ):
        with pytest.raises(SurfaceFullscreenError) as caught:
            fs.parse_receipt(action, raw)
        assert caught.value.code == fs.BAD_RECEIPT and caught.value.status == 400, (action, raw)


def test_state_reports_accept_all_states_but_demand_a_cause_for_the_failures():
    for state in ("entered", "exited", "needs_gesture"):
        assert fs.parse_state_report({"state": state})["state"] == state
    for state in ("refused", "expired", "unsupported"):
        with pytest.raises(SurfaceFullscreenError):
            fs.parse_state_report({"state": state})
        assert fs.parse_state_report({"state": state, "code": fs.PAGE_ERROR})["code"] == fs.PAGE_ERROR
    assert fs.parse_state_report({"state": "entered", "id": "AbCd-_12"})["id"] == "AbCd-_12"
    with pytest.raises(SurfaceFullscreenError):
        fs.parse_state_report({"state": "entered", "id": "x" * 40})   # l'identifiant complet est une capacité


def test_the_page_codes_are_a_closed_prefixed_list_and_the_command_id_is_checked():
    assert len(set(fs.PAGE_CODES)) == len(fs.PAGE_CODES) and all(code.startswith("fullscreen_") for code in fs.PAGE_CODES)
    for bad in (None, "", "court", "a" * 31, "a" * 65, "a/b" + "a" * 30, 42):
        with pytest.raises(SurfaceFullscreenError) as caught:
            fs.check_command_id(bad)
        assert caught.value.code == fs.UNKNOWN_COMMAND_ID and caught.value.status == 404
    assert fs.check_command_id("A" * 32) == "A" * 32
    assert fs.short_id("A" * 32) == "A" * 8
