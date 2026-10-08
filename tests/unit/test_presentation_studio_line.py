"""Progress of a scripted Jarvis line, pure (jarvis-interactive-presentation-studio, Slice 14).

The fold reads the facts the existing speech stack already records and shares its phase vocabulary with the read-only projection
`jarvis/runtime/tool_brain_speech.py` (one source of truth for "what happened to this speech"). It cannot hold the spoken text.
"""

from __future__ import annotations

import dataclasses

import pytest

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.presentation_studio_line import (
    FACT_OF_EVENT, TERMINAL, FactKind, LinePhase, SpeechFact, SpeechLine, observe,
)
from jarvis.domain.speech_presentation import SpeechCandidateStatus
from jarvis.runtime import tool_brain_speech as tbs


def fresh(**kw) -> SpeechLine:
    return SpeechLine("psi_000000000001", 1000, 41, **kw)


def fact(kind, speech_id="sp-1", at=1500, **kw) -> SpeechFact:
    return SpeechFact(kind, at, speech_id, **kw)


def test_a_line_walks_pending_playing_heard_and_binds_its_speech_id_once():
    line = observe(fresh(), fact(FactKind.REQUESTED))
    assert (line.speech_id, line.phase) == ("sp-1", LinePhase.PENDING)
    assert observe(line, fact(FactKind.REQUESTED, "sp-2")).speech_id == "sp-1"            # bound once
    line = observe(line, fact(FactKind.STARTED, at=1800))
    assert (line.phase, line.started_ms) == (LinePhase.PLAYING, 1800)
    assert observe(line, fact(FactKind.STARTED, at=2500)).started_ms == 1800               # the first start counts
    line = observe(line, fact(FactKind.COMPLETED, at=4000))
    assert (line.phase, line.ended_ms, line.terminal) == (LinePhase.HEARD, 4000, True)


def test_facts_of_another_speech_or_before_the_binding_change_nothing():
    line = fresh()
    assert observe(line, fact(FactKind.STARTED)) is line                                  # not bound yet
    line = observe(line, fact(FactKind.REQUESTED))
    assert observe(line, fact(FactKind.STARTED, "other")) is line
    assert observe(line, fact(FactKind.REQUESTED, None)) is line


@pytest.mark.parametrize("kind, phase", [
    (FactKind.INTERRUPTED, LinePhase.INTERRUPTED), (FactKind.SUPERSEDED, LinePhase.OBSOLETE), (FactKind.EXPIRED, LinePhase.OBSOLETE),
    (FactKind.FAILED, LinePhase.FAILED), (FactKind.UNCONFIRMED, LinePhase.UNCONFIRMED)])
def test_every_terminal_fact_closes_the_line_and_a_closed_line_never_reopens(kind, phase):
    line = observe(fresh(), fact(FactKind.REQUESTED))
    closed = observe(line, fact(kind, at=2000, reason="user_barge_in", played_ms=1200))
    assert closed.phase is phase and closed.terminal and closed.reason == "user_barge_in" and closed.played_ms == 1200
    assert observe(closed, fact(FactKind.STARTED)) is closed and observe(closed, fact(FactKind.COMPLETED)) is closed


def test_the_floor_and_a_user_turn_are_not_tied_to_one_speech():
    line = observe(fresh(), fact(FactKind.REQUESTED))
    assert observe(line, SpeechFact(FactKind.FLOOR_TAKEN, 2000)) is line
    assert observe(line, SpeechFact(FactKind.USER_TURN, 2000)) is line


def test_the_presenter_listens_to_exactly_these_conversation_events():
    assert set(FACT_OF_EVENT) == {
        T.BRAIN_SPEECH_REQUESTED, T.MOUTH_SPEECH_STARTED, T.MOUTH_SPEECH_COMPLETED, T.MOUTH_SPEECH_INTERRUPTED,
        T.MOUTH_SPEECH_SUPERSEDED, T.MOUTH_SPEECH_EXPIRED, T.MOUTH_SPEECH_FAILED, T.MOUTH_SPEECH_UNCONFIRMED, T.MOUTH_FLOOR_TAKEN,
        T.USER_TRANSCRIPT_ACCEPTED}
    assert set(FACT_OF_EVENT.values()) == set(FactKind)


def test_the_phase_words_are_the_ones_of_the_tool_brain_speech_projection():
    """One source of truth: `tool_brain_speech` owns pending / playing / heard / interrupted / obsolete / unconfirmed."""

    shared = {LinePhase.PENDING: tbs.PENDING, LinePhase.PLAYING: tbs.PLAYING, LinePhase.HEARD: tbs.HEARD,
              LinePhase.INTERRUPTED: tbs.INTERRUPTED, LinePhase.OBSOLETE: tbs.OBSOLETE, LinePhase.UNCONFIRMED: tbs.UNCONFIRMED}
    assert all(phase.value == word for phase, word in shared.items())
    # and the scheduler statuses it projects land on the same words as our facts do
    by_status = {SpeechCandidateStatus.COMPLETED: LinePhase.HEARD, SpeechCandidateStatus.INTERRUPTED: LinePhase.INTERRUPTED,
                 SpeechCandidateStatus.SUPERSEDED: LinePhase.OBSOLETE, SpeechCandidateStatus.EXPIRED: LinePhase.OBSOLETE,
                 SpeechCandidateStatus.UNCONFIRMED: LinePhase.UNCONFIRMED, SpeechCandidateStatus.STARTED: LinePhase.PLAYING}
    for status, phase in by_status.items():
        assert tbs._PHASE_OF[status] == phase.value
    assert TERMINAL == {LinePhase.HEARD, LinePhase.INTERRUPTED, LinePhase.OBSOLETE, LinePhase.UNCONFIRMED, LinePhase.FAILED}


def test_a_line_and_a_fact_have_no_field_that_could_hold_the_spoken_text():
    for cls in (SpeechLine, SpeechFact):
        for field in dataclasses.fields(cls):
            assert field.name not in {"text", "content", "note", "message"}, field.name
    assert fresh().chars == 41                          # a count, never the sentence


def test_wait_is_measured_from_the_issue():
    assert fresh().wait_ms(1750) == 750 and fresh().wait_ms(500) == 0
