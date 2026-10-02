"""Contrat pur des captures : identifiants, machine d'état, codes, sérialisation stricte.

Handoff session-context-recording, Slice 05. Contrat : `docs/capture.md`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import itertools

import pytest

from jarvis.domain.artifacts import ArtifactKind
from jarvis.domain.capture import (
    _NEXT, HTTP_STATUS, OPEN_STATES, TERMINAL_STATES, CaptureChannel, CaptureError, CaptureErrorCode, CaptureMode,
    CaptureRecord, CaptureState, StopReason, activate, artifact_kind_of, attach_artifact, check_capture_id,
    check_capture_update, finish, new_capture, request_stop,
)

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
SID = "jsess_0123456789abcdef"
CTX = "jctx_0123456789abcdef"


def t(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def cap(**kw) -> CaptureRecord:  # noqa: ANN003
    return new_capture(channel=CaptureChannel.AUDIO, mode=CaptureMode.CONTINUOUS, source="fake", now=T0,
                       jarvis_session_id=SID, context_id=CTX, **kw)


def test_ids_are_lowercase_path_safe_and_prefixed():
    record = cap()
    assert record.capture_id.startswith("jcap_") and record.capture_id == record.capture_id.lower()
    for bad in ("jcap_", "jcap_A", "jart_x", "jcap_../x", "jcap_a.b", 3, None):
        with pytest.raises(CaptureError) as caught:
            check_capture_id(bad)
        assert caught.value.code is CaptureErrorCode.INVALID_CAPTURE


def test_the_required_failure_vocabulary_is_stable_and_has_an_http_status():
    required = {"source_unavailable", "permission_denied", "already_active", "storage_unavailable", "storage_full",
                "write_failed", "source_lost", "finalize_failed", "unsupported_platform", "unsupported_source",
                "recoverable_partial", "transcription_unavailable", "transcription_timeout"}
    assert required <= {code.value for code in CaptureErrorCode}
    assert set(HTTP_STATUS) == set(CaptureErrorCode)
    assert CaptureError(CaptureErrorCode.ALREADY_ACTIVE, "x", capture_id="jcap_a").status == 409


def test_nominal_lifecycle_starting_active_stopping_complete():
    record = attach_artifact(cap(), "jart_a", now=t(1))
    record = activate(record, now=t(2))
    assert (record.state, record.activated_at) == (CaptureState.ACTIVE, t(2))
    record = request_stop(record, now=t(3), reason=StopReason.USER)
    assert (record.state, record.stop_requested_at, record.stop_reason) == (CaptureState.STOPPING, t(3),
                                                                            StopReason.USER)
    done = finish(record, now=t(4), state=CaptureState.COMPLETE, bytes_written=10)
    assert (done.state, done.ended_at, done.bytes_written, done.is_terminal) == (CaptureState.COMPLETE, t(4), 10, True)


def test_every_transition_outside_the_table_is_refused():
    for source, target in itertools.product(CaptureState, CaptureState):
        record = cap()
        if source is not CaptureState.STARTING:
            record = replace(record, state=source, ended_at=T0 if source in TERMINAL_STATES else None,
                             error_code="x" if source in (CaptureState.PARTIAL, CaptureState.FAILED) else None)
        allowed = target in _NEXT.get(source, frozenset())
        try:
            if target is CaptureState.ACTIVE:
                activate(record, now=t(1))
            elif target is CaptureState.STOPPING:
                moved = request_stop(record, now=t(1), reason=StopReason.USER)
                if moved is record:
                    assert source is CaptureState.STOPPING or source in TERMINAL_STATES
                    continue
            elif target is CaptureState.STARTING:
                raise CaptureError(CaptureErrorCode.INVALID_TRANSITION, "never back to starting")
            else:
                finish(record, now=t(1), state=target, error_code=None if target is CaptureState.COMPLETE else "x")
        except CaptureError as exc:
            assert not allowed, (source, target)
            assert exc.code is CaptureErrorCode.INVALID_TRANSITION
        else:
            assert allowed, (source, target)


def test_complete_only_from_stopping_and_never_with_an_error():
    active = activate(cap(), now=t(1))
    with pytest.raises(CaptureError):
        finish(active, now=t(2), state=CaptureState.COMPLETE)
    stopping = request_stop(active, now=t(2), reason=StopReason.USER)
    with pytest.raises(CaptureError) as caught:
        finish(stopping, now=t(3), state=CaptureState.COMPLETE, error_code="source_lost")
    assert caught.value.code is CaptureErrorCode.INVALID_CAPTURE
    for state in (CaptureState.PARTIAL, CaptureState.FAILED):
        with pytest.raises(CaptureError):
            finish(stopping, now=t(3), state=state)  # partial/failed disent pourquoi
    with pytest.raises(CaptureError):
        finish(stopping, now=t(3), state=CaptureState.ACTIVE)


def test_request_stop_is_idempotent_and_keeps_the_first_reason():
    stopping = request_stop(activate(cap(), now=t(1)), now=t(2), reason=StopReason.SOURCE_LOST)
    assert request_stop(stopping, now=t(5), reason=StopReason.USER) is stopping
    done = finish(stopping, now=t(3), state=CaptureState.PARTIAL, error_code="source_lost")
    assert request_stop(done, now=t(6), reason=StopReason.USER) is done
    assert request_stop(cap(), now=t(1), reason=StopReason.USER).state is CaptureState.STOPPING  # stop en starting


def test_artifact_is_attached_once_during_start_only():
    record = attach_artifact(cap(), "jart_a", now=t(1))
    with pytest.raises(CaptureError):
        attach_artifact(record, "jart_b", now=t(2))
    with pytest.raises(CaptureError):
        attach_artifact(activate(cap(), now=t(1)), "jart_b", now=t(2))


def test_time_never_goes_back_and_association_needs_a_session():
    assert activate(cap(), now=T0 - timedelta(hours=1)).updated_at == T0
    with pytest.raises(CaptureError):
        new_capture(channel=CaptureChannel.AUDIO, mode=CaptureMode.CONTINUOUS, source="fake", now=T0,
                    context_id=CTX)
    with pytest.raises(CaptureError):
        new_capture(channel=CaptureChannel.AUDIO, mode=CaptureMode.CONTINUOUS, source="fake",
                    now=datetime(2026, 10, 1))


def test_store_guard_freezes_identity_and_terminal_rows():
    record = cap()
    with pytest.raises(CaptureError):
        check_capture_update(record, replace(record, context_id=None, jarvis_session_id=None))
    with pytest.raises(CaptureError):
        check_capture_update(record, replace(record, device="other"))
    done = finish(request_stop(record, now=t(1), reason=StopReason.USER), now=t(2), state=CaptureState.FAILED,
                  error_code="permission_denied")
    with pytest.raises(CaptureError):
        check_capture_update(done, replace(done, data={"x": 1}))
    with pytest.raises(CaptureError):
        check_capture_update(record, replace(record, state=CaptureState.COMPLETE, ended_at=t(1)))
    attached = attach_artifact(record, "jart_a", now=t(1))
    with pytest.raises(CaptureError):
        check_capture_update(attached, replace(attached, artifact_id="jart_b"))


def test_payload_round_trip_is_strict():
    record = finish(request_stop(attach_artifact(cap(data={"note": "x"}), "jart_a", now=t(1)), now=t(2),
                                 reason=StopReason.USER), now=t(3), state=CaptureState.PARTIAL,
                    error_code="capture_gap", gaps=2, bytes_written=99)
    assert CaptureRecord.from_payload(record.to_payload()) == record
    payload = record.to_payload()
    for broken in ({**payload, "extra": 1}, {k: v for k, v in payload.items() if k != "gaps"},
                   {**payload, "state": "paused"}, {**payload, "created_at": "2026-10-01T09:00:00"},
                   {**payload, "gaps": -1}, {**payload, "channel": "camera"}):
        with pytest.raises(CaptureError):
            CaptureRecord.from_payload(broken)
    with pytest.raises(CaptureError):
        cap(data={f"k{i}": i for i in range(17)})


def test_open_and_terminal_states_partition_the_machine():
    assert OPEN_STATES | TERMINAL_STATES == set(CaptureState) and not OPEN_STATES & TERMINAL_STATES


def test_artifact_kind_per_channel_and_mode():
    assert artifact_kind_of(CaptureChannel.AUDIO, CaptureMode.CONTINUOUS) is ArtifactKind.AUDIO_RECORDING
    assert artifact_kind_of(CaptureChannel.SCREEN, CaptureMode.CONTINUOUS) is ArtifactKind.SCREEN_RECORDING
    assert artifact_kind_of(CaptureChannel.SCREEN, CaptureMode.ONE_SHOT) is ArtifactKind.SCREENSHOT
    with pytest.raises(CaptureError) as caught:
        artifact_kind_of(CaptureChannel.AUDIO, CaptureMode.ONE_SHOT)
    assert caught.value.code is CaptureErrorCode.UNSUPPORTED_SOURCE
