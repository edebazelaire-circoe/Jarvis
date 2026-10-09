"""Roles de lecture du Studio et autorite de parole (jarvis-interactive-presentation-studio, Slice 01c, option A).

Prouve : le mode exige par role, qu'aucun texte ambiant ne peut demander une bascule, le protocole
de restauration, l'ensemble d'arguments de `announce_notice`, et que la porte de parole existante est
intacte (la ligne scriptee est retenue en PRESENTATION, admise hors PRESENTATION).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_policy import LOCKED_DECISIONS
from jarvis.domain.presentation_studio_roles import (
    DEFAULT_SCORE_LINE_TTL_S, SCORE_LINE_KIND, STUDIO_RUN_MODE_SOURCE, TRANSIENT_MODE_SOURCES, AmbientLanePolicy,
    ModeEventKind, RestoreAction, ScoreLineNotice, SpeechPolicy, StudioRole, SwitchOrigin, classify_mode_event,
    decide_restore, mode_switch_allowed, plan_mode_entry, requirements,
)
from jarvis.domain.v2 import TRANSIENT_SPEECH_KINDS, SpeechKind
from jarvis.runtime.presentation_speech_gate import PresentationSpeechGate

ROOT = Path(__file__).resolve().parents[2]
A, P = InteractionMode.ASSISTANT, InteractionMode.PRESENTATION


# ------------------------------------------------------------------ role -> requirements

@pytest.mark.parametrize(("role", "speaks", "mode", "lane", "speech"), [
    (StudioRole.USER_PRESENTER, None, P, AmbientLanePolicy.ARMED_CUES_ONLY, SpeechPolicy.PRESENTATION_SILENCE),
    (StudioRole.JARVIS_PRESENTER, None, A, AmbientLanePolicy.OFF, SpeechPolicy.SCORE_LINES),
    (StudioRole.REHEARSAL, None, P, AmbientLanePolicy.ARMED_CUES_ONLY, SpeechPolicy.PRESENTATION_SILENCE),
    (StudioRole.REHEARSAL, False, P, AmbientLanePolicy.ARMED_CUES_ONLY, SpeechPolicy.PRESENTATION_SILENCE),
    (StudioRole.REHEARSAL, True, A, AmbientLanePolicy.OFF, SpeechPolicy.SCORE_LINES),
])
def test_every_role_maps_to_one_mode_lane_and_speech_policy(role, speaks, mode, lane, speech):
    got = requirements(role, jarvis_speaks=speaks)
    assert (got.mode, got.ambient_lane, got.speech) == (mode, lane, speech)
    assert got.jarvis_speaks is (speech is SpeechPolicy.SCORE_LINES)


def test_the_table_is_exhaustive_and_never_meeting():
    for role in StudioRole:
        for speaks in (None, False, True):
            try:
                got = requirements(role, jarvis_speaks=speaks)
            except ValueError:
                continue
            assert got.mode in (A, P)  # REUNION is never a studio mode
            # The invariant of decision A: spoken score lines <=> outside PRESENTATION <=> no ambient lane.
            assert (got.speech is SpeechPolicy.SCORE_LINES) == (got.mode is A) == (got.ambient_lane is AmbientLanePolicy.OFF)


def test_contradictory_role_flags_are_refused():
    with pytest.raises(ValueError):
        requirements(StudioRole.USER_PRESENTER, jarvis_speaks=True)
    with pytest.raises(ValueError):
        requirements(StudioRole.JARVIS_PRESENTER, jarvis_speaks=False)
    with pytest.raises(ValueError):
        requirements("nobody")


# ------------------------------------------------------------------ who may switch

def test_only_an_explicit_user_request_may_switch_the_mode():
    assert [o for o in SwitchOrigin if mode_switch_allowed(o)] == [SwitchOrigin.EXPLICIT_USER_REQUEST]
    assert not mode_switch_allowed("something_new")


@pytest.mark.parametrize("role", list(StudioRole))
@pytest.mark.parametrize("current", [A, P])
def test_ambient_text_can_never_request_a_mode_switch(role, current):
    for origin in (SwitchOrigin.AMBIENT_TEXT, SwitchOrigin.SCORE_CONTENT, SwitchOrigin.BRAIN_SPONTANEOUS,
                   SwitchOrigin.SYSTEM_REPLAY):
        for speaks in (None, True):
            if role is StudioRole.USER_PRESENTER and speaks:
                continue
            plan = plan_mode_entry(role, origin, current, jarvis_speaks=speaks)
            assert (plan.allowed, plan.switch_needed, plan.target, plan.code) == (
                False, False, None, "mode_switch_origin_refused")


def test_an_explicit_request_plans_the_switch_with_the_transient_source():
    plan = plan_mode_entry(StudioRole.JARVIS_PRESENTER, SwitchOrigin.EXPLICIT_USER_REQUEST, P)
    assert (plan.allowed, plan.switch_needed, plan.target, plan.code) == (True, True, A, "ok")
    assert plan.source == STUDIO_RUN_MODE_SOURCE
    assert plan.source in TRANSIENT_MODE_SOURCES
    same = plan_mode_entry(StudioRole.JARVIS_PRESENTER, SwitchOrigin.EXPLICIT_USER_REQUEST, A)
    assert (same.allowed, same.switch_needed, same.code) == (True, False, "already_in_mode")
    back = plan_mode_entry(StudioRole.USER_PRESENTER, SwitchOrigin.EXPLICIT_USER_REQUEST, A)
    assert (back.target, back.switch_needed) == (P, True)


# ------------------------------------------------------------------ mode events and restore

def test_mode_events_are_read_against_the_run_switch():
    base = dict(applied_epoch="e1", applied_revision=3)
    assert classify_mode_event(**base, event_epoch="e1", event_revision=3, event_source="x") is ModeEventKind.OWN_OR_STALE
    assert classify_mode_event(**base, event_epoch="e1", event_revision=2, event_source="x") is ModeEventKind.OWN_OR_STALE
    assert classify_mode_event(**base, event_epoch="e1", event_revision=4,
                               event_source=STUDIO_RUN_MODE_SOURCE) is ModeEventKind.OWN_OR_STALE
    for source in ("control_center", "board_switch", "save_retry", "protocol"):
        assert classify_mode_event(**base, event_epoch="e1", event_revision=4,
                                   event_source=source) is ModeEventKind.FOREIGN_CHANGE
    assert classify_mode_event(**base, event_epoch="e2", event_revision=1,
                               event_source="board_restore") is ModeEventKind.CORE_RESTARTED


def _restore(**over):
    args = dict(previous_mode=P, applied_epoch="e1", applied_revision=3, current_mode=A, current_epoch="e1",
                current_revision=3)
    args.update(over)
    return decide_restore(**args)


def test_restore_protocol():
    ok = _restore()
    assert (ok.action, ok.target) == (RestoreAction.RESTORE, P)
    assert _restore(previous_mode=None, applied_epoch=None, applied_revision=None).action is RestoreAction.NONE
    assert _restore(current_revision=4).action is RestoreAction.LEAVE_USER_CHOICE  # user clicked meanwhile
    assert _restore(current_revision=4, current_mode=P).action is RestoreAction.LEAVE_USER_CHOICE
    assert _restore(current_epoch="e2", current_revision=1).action is RestoreAction.CORE_RESTARTED
    assert _restore(current_mode=P).action is RestoreAction.NONE


# ------------------------------------------------------------------ announce_notice arguments

def test_the_score_line_argument_set():
    notice = ScoreLineNotice("Bienvenue.", run_id="run_01")
    assert notice.call_kwargs() == {"kind": SpeechKind.PROGRESS, "supersedes_key": "presentation_studio:run_01",
                                    "ttl_s": DEFAULT_SCORE_LINE_TTL_S}
    assert SCORE_LINE_KIND in TRANSIENT_SPEECH_KINDS  # deadline, never retained as a public outcome
    assert set(notice.call_kwargs()) == {"kind", "supersedes_key", "ttl_s"}  # no work_id, no verbatim flag


@pytest.mark.parametrize("bad", [
    dict(text="  ", run_id="r"), dict(text="[pas-pour-moi]", run_id="r"), dict(text="ok", run_id="has space"),
    dict(text="ok", run_id=""), dict(text="ok", run_id="r", ttl_s=0.2), dict(text="ok", run_id="r", ttl_s=99999),
    dict(text=None, run_id="r"),
])
def test_a_bad_score_line_is_refused_not_dropped_later(bad):
    with pytest.raises(ValueError):
        ScoreLineNotice(**bad)


# ------------------------------------------------------------------ the existing gate is untouched

def test_a_score_line_is_admitted_outside_presentation():
    gate = PresentationSpeechGate(mode=lambda: A)
    verdict = gate.admit(correlation_id="c1", kind=SCORE_LINE_KIND)
    assert verdict.admitted and verdict.reason == "mode_not_presentation"


def test_the_same_line_stays_withheld_in_presentation_so_the_role_needs_the_other_mode():
    gate = PresentationSpeechGate(mode=lambda: P)
    assert not gate.admit(correlation_id="c1", kind=SCORE_LINE_KIND).admitted
    assert not gate.admit(correlation_id=None, kind=SpeechKind.RESULT).admitted
    assert gate.admit(correlation_id=None, kind=SpeechKind.ERROR).admitted  # safety kind, unchanged
    assert len(LOCKED_DECISIONS) == 14  # decision A adds no decision and no matrix row


def test_the_roles_module_is_pure_domain():
    source = (ROOT / "jarvis/domain/presentation_studio_roles.py").read_text(encoding="utf-8")
    for forbidden in ("jarvis.core", "jarvis.runtime", "jarvis.adapters", "import asyncio"):
        assert forbidden not in source


def test_the_contract_page_states_the_code_names():
    text = (ROOT / "docs/presentation-studio.md").read_text(encoding="utf-8")
    section = text[text.index("## Playback roles and speech authority"):]
    section = section[:section.index("\n## Reused owners")]
    for name in ("STUDIO_RUN_MODE_SOURCE", "TRANSIENT_MODE_SOURCES", "NON_PERSISTED_SOURCES", "ScoreLineNotice", "plan_mode_entry",
                 "decide_restore", "classify_mode_event", "interaction.mode.changed", "presentation_studio_run", "SpeechKind.PROGRESS",
                 "leave_user_choice", "mode_switch_origin_refused", "presentation_studio:<run_id>"):
        assert name in section, name
    for role in StudioRole:
        assert f"`{role.value}`" in section
