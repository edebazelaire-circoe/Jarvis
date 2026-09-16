from __future__ import annotations

import pytest

from jarvis.domain.speech_arbitration import (
    SpeechArbiter,
    SpeechIdentity,
    SpeechLifecycleState,
    SpeechOutputOwner,
    SpeechTerminalReason,
)


def identity(*, output_id: str = "out-1", speech_id: str | None = "speech-1") -> SpeechIdentity:
    return SpeechIdentity(
        output_id=output_id,
        speech_id=speech_id,
        correlation_id="corr-1",
        owner=SpeechOutputOwner.BRAIN,
    )


def test_happy_path_requires_explicit_completed_reason() -> None:
    arbiter = SpeechArbiter()
    arbiter.register(identity())
    arbiter.advance("out-1", SpeechLifecycleState.GENERATING)
    arbiter.advance("out-1", SpeechLifecycleState.PLAYING)

    with pytest.raises(ValueError, match="explicit reason"):
        arbiter.advance("out-1", SpeechLifecycleState.COMPLETED)

    lifecycle = arbiter.advance(
        "out-1",
        SpeechLifecycleState.COMPLETED,
        reason=SpeechTerminalReason.OUTPUT_COMPLETED,
    )
    assert lifecycle.terminal
    assert lifecycle.terminal_reason is SpeechTerminalReason.OUTPUT_COMPLETED


def test_user_barge_in_terminates_speech_without_cancelling_brain_work() -> None:
    arbiter = SpeechArbiter()
    arbiter.register(identity())
    arbiter.advance("out-1", SpeechLifecycleState.GENERATING)
    arbiter.advance("out-1", SpeechLifecycleState.PLAYING)

    lifecycle = arbiter.advance(
        "out-1",
        SpeechLifecycleState.INTERRUPTED,
        reason=SpeechTerminalReason.USER_BARGE_IN,
        played_ms=420,
    )

    assert lifecycle.state is SpeechLifecycleState.INTERRUPTED
    assert lifecycle.played_ms == 420
    assert lifecycle.affects_brain_work is False
    assert lifecycle.trace_fields()["brain_work_cancelled"] is False


def test_supersede_is_cancellation_not_user_interruption() -> None:
    lifecycle = SpeechArbiter().register(identity())
    assert lifecycle.state is SpeechLifecycleState.RESERVED

    arbiter = SpeechArbiter()
    arbiter.register(identity())
    cancelled = arbiter.advance(
        "out-1",
        SpeechLifecycleState.CANCELLED,
        reason=SpeechTerminalReason.BRAIN_SUPERSEDED,
    )
    assert cancelled.state is SpeechLifecycleState.CANCELLED

    other = SpeechArbiter()
    other.register(identity())
    with pytest.raises(ValueError, match="requires state cancelled"):
        other.advance(
            "out-1",
            SpeechLifecycleState.INTERRUPTED,
            reason=SpeechTerminalReason.BRAIN_SUPERSEDED,
        )


def test_provider_status_is_evidence_not_terminal_business_truth() -> None:
    arbiter = SpeechArbiter()
    arbiter.register(identity())
    arbiter.advance("out-1", SpeechLifecycleState.GENERATING)

    observed = arbiter.observe_provider_status("out-1", "cancelled")

    assert observed.state is SpeechLifecycleState.GENERATING
    assert observed.terminal_reason is None
    assert observed.provider_status == "cancelled"


def test_late_provider_callback_cannot_overwrite_barge_in_reason() -> None:
    arbiter = SpeechArbiter()
    arbiter.register(identity())
    arbiter.advance("out-1", SpeechLifecycleState.GENERATING)
    interrupted = arbiter.advance(
        "out-1",
        SpeechLifecycleState.INTERRUPTED,
        reason=SpeechTerminalReason.USER_BARGE_IN,
        played_ms=100,
    )

    late = arbiter.observe_provider_status("out-1", "completed")

    assert late.state is SpeechLifecycleState.INTERRUPTED
    assert late.terminal_reason is SpeechTerminalReason.USER_BARGE_IN
    assert late.provider_status == "completed"
    assert interrupted.identity == late.identity


def test_duplicate_terminal_callback_is_idempotent() -> None:
    arbiter = SpeechArbiter()
    arbiter.register(identity())
    arbiter.advance("out-1", SpeechLifecycleState.GENERATING)
    first = arbiter.advance(
        "out-1",
        SpeechLifecycleState.INTERRUPTED,
        reason=SpeechTerminalReason.USER_BARGE_IN,
        played_ms=250,
    )
    duplicate = arbiter.advance(
        "out-1",
        SpeechLifecycleState.INTERRUPTED,
        reason=SpeechTerminalReason.USER_BARGE_IN,
    )

    assert duplicate is first
    assert duplicate.played_ms == 250


def test_contradictory_late_terminal_transition_fails_loudly() -> None:
    arbiter = SpeechArbiter()
    arbiter.register(identity())
    arbiter.advance("out-1", SpeechLifecycleState.GENERATING)
    arbiter.advance(
        "out-1",
        SpeechLifecycleState.INTERRUPTED,
        reason=SpeechTerminalReason.USER_BARGE_IN,
    )

    with pytest.raises(ValueError, match="cannot transition"):
        arbiter.advance(
            "out-1",
            SpeechLifecycleState.COMPLETED,
            reason=SpeechTerminalReason.OUTPUT_COMPLETED,
        )


def test_output_identity_reuse_with_different_speech_is_rejected() -> None:
    arbiter = SpeechArbiter()
    arbiter.register(identity())

    with pytest.raises(ValueError, match="reused with different identity"):
        arbiter.register(identity(speech_id="speech-2"))


def test_invalid_transition_and_reason_pair_are_rejected() -> None:
    arbiter = SpeechArbiter()
    arbiter.register(identity())

    with pytest.raises(ValueError, match="invalid speech transition"):
        arbiter.advance("out-1", SpeechLifecycleState.PLAYING)

    with pytest.raises(ValueError, match="requires state interrupted"):
        arbiter.advance(
            "out-1",
            SpeechLifecycleState.FAILED,
            reason=SpeechTerminalReason.USER_BARGE_IN,
        )


def test_reflex_identity_can_omit_speech_id() -> None:
    arbiter = SpeechArbiter()
    reflex = SpeechIdentity(
        output_id="reflex-1",
        speech_id=None,
        correlation_id="corr-1",
        owner=SpeechOutputOwner.SURFACE_REFLEX,
    )
    lifecycle = arbiter.register(reflex)
    lifecycle = arbiter.advance(
        "reflex-1",
        SpeechLifecycleState.CANCELLED,
        reason=SpeechTerminalReason.REFLEX_PREEMPTED,
    )

    assert lifecycle.identity.speech_id is None
    assert lifecycle.terminal_reason is SpeechTerminalReason.REFLEX_PREEMPTED
