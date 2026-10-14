"""Machine d'état du canal vocal vue de Core (`docs/chat.md` › *State machine*), domaine pur."""

from __future__ import annotations

import pytest

from jarvis.domain.voice_channel import (
    VOICE_CHANNEL_FRESH_S, VOICE_DISABLE_TIMEOUT_S, DisableRequest, DisableStatus, VoiceChannelReport,
    VoiceChannelState, channel_view, locked_reason_for,
)

STARTED = 1000.0
LATER = STARTED + 60.0  # bien après la période de grâce


def report(state: str = "active", *, seq: int = 1, at: float = LATER, incarnation: str = "voice-a",
           ack: dict | None = None) -> VoiceChannelReport:
    return VoiceChannelReport.from_payload(
        {"schema_version": 1, "voice_incarnation_id": incarnation, "seq": seq, "lifecycle_state": state,
         "conversation_id": "conv-1", "ack": ack}, received_at=at)


def request(at: float = LATER, status: DisableStatus = DisableStatus.PENDING) -> DisableRequest:
    return DisableRequest("vcr-1", "c1", at, "2026-10-14T00:00:00+00:00", status)


@pytest.mark.parametrize(("last", "pending", "expected", "writable", "reason"), [
    (None, False, "absent", True, None),
    ("background", False, "background", True, None),
    ("connecting", False, "connecting", False, "voice_connecting"),
    ("active", False, "active", False, "voice_active"),
    ("error", False, "error", False, "voice_error"),
    ("active", True, "switching", False, "voice_switching"),
    ("connecting", True, "switching", False, "voice_switching"),
    ("error", True, "switching", False, "voice_switching"),
    ("background", True, "background", True, None),  # dernier rapport = background : jamais switching
    ("listening", False, "unknown", False, "voice_unknown"),  # état illisible mais bien formé
])
def test_the_full_state_table(last, pending, expected, writable, reason):
    view = channel_view(None if last is None else report(last), request() if pending else None, LATER + 1, STARTED)

    assert view == (VoiceChannelState(expected), writable, reason)


@pytest.mark.parametrize(("age", "expected"), [(4.9, "active"), (VOICE_CHANNEL_FRESH_S, "active"), (5.1, "absent")])
def test_freshness_boundary(age, expected):
    state, writable, _ = channel_view(report("active"), None, LATER + age, STARTED)

    assert state.value == expected
    assert writable is (expected == "absent")


def test_a_stale_report_with_a_pending_request_is_absent_and_writable():
    assert channel_view(report("active"), request(), LATER + 5.1, STARTED)[:2] == (VoiceChannelState.ABSENT, True)


@pytest.mark.parametrize(("since_start", "expected"), [(0.0, "unknown"), (4.9, "unknown"), (5.0, "absent"),
                                                       (5.1, "absent")])
def test_startup_grace_without_any_report(since_start, expected):
    state, writable, reason = channel_view(None, None, STARTED + since_start, STARTED)

    assert state.value == expected
    assert (writable, reason) == ((False, "voice_unknown") if expected == "unknown" else (True, None))


def test_a_fresh_report_ends_the_grace_period_at_once():
    assert channel_view(report("background", at=STARTED + 0.2), None, STARTED + 0.3, STARTED)[0] \
        is VoiceChannelState.BACKGROUND


def test_an_expired_request_no_longer_means_switching():
    view = channel_view(report("active", at=LATER + VOICE_DISABLE_TIMEOUT_S), request(),
                        LATER + VOICE_DISABLE_TIMEOUT_S, STARTED)

    assert view[0] is VoiceChannelState.ACTIVE
    assert request().live(LATER + VOICE_DISABLE_TIMEOUT_S - 0.1)
    assert not request().live(LATER + VOICE_DISABLE_TIMEOUT_S)


@pytest.mark.parametrize("status", [DisableStatus.ACCEPTED, DisableStatus.FAILED, DisableStatus.EXPIRED])
def test_a_settled_request_never_means_switching(status):
    assert channel_view(report("active"), request(status=status), LATER + 1, STARTED)[0] is VoiceChannelState.ACTIVE


def test_seq_ordering_and_incarnations():
    first = report(seq=5)

    assert not report(seq=5).supersedes(first)  # même seq : refusé
    assert not report(seq=4).supersedes(first)
    assert report(seq=6).supersedes(first)
    assert report(seq=1, incarnation="voice-b").supersedes(first)  # nouvelle incarnation : remplace
    assert report(seq=1).supersedes(None)


def test_locked_reasons():
    assert {state: locked_reason_for(state) for state in VoiceChannelState} == {
        VoiceChannelState.ABSENT: None, VoiceChannelState.BACKGROUND: None,
        VoiceChannelState.UNKNOWN: "voice_unknown", VoiceChannelState.CONNECTING: "voice_connecting",
        VoiceChannelState.ACTIVE: "voice_active", VoiceChannelState.ERROR: "voice_error",
        VoiceChannelState.SWITCHING: "voice_switching"}


def test_ack_is_parsed():
    parsed = report("background", ack={"request_id": "vcr-1", "result": "failed", "code": "voice_disable_failed"})

    assert (parsed.ack.request_id, parsed.ack.accepted, parsed.ack.code) == ("vcr-1", False, "voice_disable_failed")


BASE = {"schema_version": 1, "voice_incarnation_id": "voice-a", "seq": 1, "lifecycle_state": "active",
        "conversation_id": None, "ack": None}


@pytest.mark.parametrize("change", [
    {"schema_version": 2}, {"schema_version": True}, {"seq": -1}, {"seq": True}, {"seq": "1"}, {"seq": 1.0},
    {"lifecycle_state": ""}, {"lifecycle_state": 3}, {"lifecycle_state": "x" * 33},
    {"voice_incarnation_id": ""}, {"voice_incarnation_id": "a b"}, {"voice_incarnation_id": None},
    {"conversation_id": 7}, {"extra": 1},
    {"ack": "vcr-1"}, {"ack": {"request_id": "vcr-1", "result": "maybe"}},
    {"ack": {"request_id": "vcr-1", "result": "accepted", "code": "Bad Code"}},
    {"ack": {"request_id": "vcr-1", "result": "accepted", "extra": 1}},
])
def test_strict_validation(change):
    with pytest.raises(ValueError):
        VoiceChannelReport.from_payload({**BASE, **change}, received_at=0.0)


def test_missing_field_is_refused():
    payload = dict(BASE)
    del payload["seq"]
    with pytest.raises(ValueError):
        VoiceChannelReport.from_payload(payload, received_at=0.0)
