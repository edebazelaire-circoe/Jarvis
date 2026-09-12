"""Vérificateur de locuteur : port, faux déterministe et télémétrie en ombre.

Handoff Solo Owner, tâche 02. Ces tests figent :

1. le verdict typé et la sémantique du score (plus haut = plus probablement le
   propriétaire, sur [0, 1]) ;
2. un faux vérificateur qui rejoue des suites propriétaire / étranger / ambiguë ;
3. une télémétrie bornée, sans audio ni empreinte, qui survit aux pannes du
   moteur ;
4. un fil de travail qui ne freine jamais la capture (file bornée).

Tâche 04 (vérification glissante) : l'état du propriétaire n'existe que dans un
candidat acoustique, suit le dernier verdict sans verrou, se publie à chaque
changement, et reste borné.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Sequence

import pytest

from jarvis.adapters.fake_speaker_verifier import ScriptedSpeakerVerifier
from jarvis.adapters.null_speaker_verifier import NullSpeakerVerifier
from jarvis.audio.duplex import FRAME_MS, CaptureFrameContext
from jarvis.audio.speaker_shadow import (
    OWNER_CANDIDATE,
    OWNER_CONFIRMED,
    OWNER_LISTENER_FAILED,
    OWNER_OVERRUN,
    OWNER_REJECTED,
    OWNER_UNAVAILABLE,
    ShadowOwnerTelemetry,
    SpeakerVerificationWorker,
)
from jarvis.domain.speaker import (
    MAX_SPEAKER_ID_CHARS,
    OwnerState,
    OwnerStateSnapshot,
    SpeakerVerification,
    VerificationStatus,
    VerifierAvailability,
)

RATE = 24000
HOP = bytes(RATE // 10 * 2)  # 100 ms, la fenêtre par défaut du fil
FRAME = bytes(RATE // 100 * 2)  # 10 ms, une trame de capture
HOP_FRAMES = 10
TIMEOUT_S = 2.0


def ctx(stream_ms: int, *, near: bool = True, far: bool = False, rate: int = RATE) -> CaptureFrameContext:
    """Contexte d'une trame tel que la capture le donnerait."""

    return CaptureFrameContext(
        stream_ms=stream_ms, sample_rate=rate, near_end=near, far_end=far, near_end_latched=False, gate_open=not far
    )


def hop_contexts(start_ms: int, flags: Sequence[bool] | None = None, *, far: bool = False, rate: int = RATE):  # noqa: ANN201
    flags = [True] * HOP_FRAMES if flags is None else list(flags)
    return tuple(ctx(start_ms + index * FRAME_MS, near=near, far=far, rate=rate) for index, near in enumerate(flags))


def owner_verdict(score: float, evidence_ms: int) -> SpeakerVerification:
    return SpeakerVerification(
        status=VerificationStatus.OK, engine="fake-speaker/1", owner_score=score, owner_detected=True,
        evidence_ms=evidence_ms, profile_id="owner-test",
    )


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})

    def kinds(self) -> list[str]:
        return [str(event["kind"]) for event in self.events]

    def of(self, kind: str) -> list[dict[str, object]]:
        return [event["data"] for event in self.events if event["kind"] == kind]  # type: ignore[misc]


def telemetry_for(verifier, **options):  # noqa: ANN001, ANN003
    journal = RecordingJournal()
    return ShadowOwnerTelemetry(verifier, sample_rate=RATE, diagnostics=journal, **options), journal


def feed_all(telemetry: ShadowOwnerTelemetry, windows: int, *, near: bool = True, far: bool = False) -> None:
    """Fenêtres de 100 ms, dix trames chacune, à la suite sur l'horloge de la session."""

    for _ in range(windows):
        telemetry.feed(HOP, hop_contexts(telemetry._last_end_ms, [near] * HOP_FRAMES, far=far))


def feed_flags(telemetry: ShadowOwnerTelemetry, flags: Sequence[bool], *, far: bool = False) -> None:
    """Une trame par drapeau de parole proche, regroupées en fenêtres de 100 ms."""

    for start in range(0, len(flags), HOP_FRAMES):
        telemetry.feed(HOP, hop_contexts(telemetry._last_end_ms, flags[start:start + HOP_FRAMES], far=far))


def listen(telemetry: ShadowOwnerTelemetry) -> list[OwnerStateSnapshot]:
    published: list[OwnerStateSnapshot] = []
    telemetry.publisher.add(published.append)
    return published


#: 600 ms de silence : le candidat se referme.
QUIET_HOPS = 6


# --------------------------------------------------------------------------
# 1. Le verdict typé


def test_a_judged_window_carries_a_score_between_zero_and_one():
    verdict = SpeakerVerification(
        status=VerificationStatus.OK, engine="engine/1", owner_score=0.82, owner_detected=True, evidence_ms=900, profile_id="owner"
    )

    assert verdict.availability is VerifierAvailability.READY
    with pytest.raises(AttributeError):
        verdict.owner_score = 0.1  # type: ignore[misc]


@pytest.mark.parametrize("score", [-0.01, 1.01, math.nan, True, None, "0.5"])
def test_a_judged_window_refuses_a_score_outside_the_common_scale(score):  # noqa: ANN001
    with pytest.raises((ValueError, TypeError)):
        SpeakerVerification(status=VerificationStatus.OK, engine="engine/1", owner_score=score)


@pytest.mark.parametrize(
    "status",
    [VerificationStatus.INSUFFICIENT_AUDIO, VerificationStatus.NO_PROFILE, VerificationStatus.UNAVAILABLE, VerificationStatus.ERROR],
)
def test_only_a_judged_window_carries_a_score_or_a_detection(status):  # noqa: ANN001
    with pytest.raises(ValueError):
        SpeakerVerification(status=status, engine="engine/1", owner_score=0.9)
    with pytest.raises(ValueError):
        SpeakerVerification(status=status, engine="engine/1", owner_detected=True)


@pytest.mark.parametrize(
    "fields",
    [
        {"engine": ""},
        {"engine": "e" * (MAX_SPEAKER_ID_CHARS + 1)},
        {"profile_id": ""},
        {"evidence_ms": -1},
        {"evidence_ms": 1.5},
        {"owner_detected": 1},
    ],
)
def test_the_verdict_stays_small_and_typed(fields):  # noqa: ANN001
    values = {"status": VerificationStatus.INSUFFICIENT_AUDIO, "engine": "engine/1", **fields}
    with pytest.raises((ValueError, TypeError)):
        SpeakerVerification(**values)


def test_each_status_says_what_it_means_for_the_verifier():
    availability = {
        status: SpeakerVerification(status=status, engine="e").availability
        for status in VerificationStatus
        if status is not VerificationStatus.OK
    }

    assert availability == {
        VerificationStatus.INSUFFICIENT_AUDIO: VerifierAvailability.READY,
        VerificationStatus.NO_PROFILE: VerifierAvailability.NO_OWNER_PROFILE,
        VerificationStatus.UNAVAILABLE: VerifierAvailability.NOT_INSTALLED,
        VerificationStatus.ERROR: VerifierAvailability.FAILED,
    }


# --------------------------------------------------------------------------
# 2. Faux et vérificateur nul


@pytest.mark.parametrize("verifier", [ScriptedSpeakerVerifier(), NullSpeakerVerifier()])
def test_the_doubles_implement_the_port(verifier):  # noqa: ANN001
    for name in ("engine", "availability", "reset", "process", "close"):
        assert hasattr(verifier, name)
    assert isinstance(verifier.availability, VerifierAvailability)


def test_the_fake_replays_owner_non_owner_and_ambiguous_windows():
    verifier = ScriptedSpeakerVerifier([0.9, 0.2, 0.65, None, VerificationStatus.NO_PROFILE], threshold=0.7)

    owner, stranger, ambiguous, silent, no_profile, exhausted = (verifier.process(HOP, RATE) for _ in range(6))

    assert (owner.owner_score, owner.owner_detected, owner.evidence_ms) == (0.9, True, 100)
    assert (stranger.owner_detected, stranger.evidence_ms) == (False, 200)
    assert (ambiguous.owner_score, ambiguous.owner_detected) == (0.65, False)
    assert silent.status is VerificationStatus.INSUFFICIENT_AUDIO and silent.owner_score is None
    assert no_profile.status is VerificationStatus.NO_PROFILE
    assert exhausted.status is VerificationStatus.INSUFFICIENT_AUDIO
    assert verifier.calls == [(len(HOP), RATE)] * 6


def test_the_fake_reset_clears_the_evidence_but_not_the_script():
    verifier = ScriptedSpeakerVerifier([0.9, 0.9, 0.8])
    verifier.process(HOP, RATE)
    verifier.process(HOP, RATE)

    verifier.reset()
    after = verifier.process(HOP, RATE)

    assert (after.owner_score, after.evidence_ms, verifier.resets) == (0.8, 100, 1)


def test_the_fake_raises_what_it_is_told_to():
    verifier = ScriptedSpeakerVerifier([RuntimeError("model crashed")])

    with pytest.raises(RuntimeError):
        verifier.process(HOP, RATE)
    verifier.close()
    with pytest.raises(RuntimeError):
        verifier.process(HOP, RATE)


def test_the_null_verifier_never_pretends_to_recognise_anyone():
    verifier = NullSpeakerVerifier()

    verdict = verifier.process(HOP, RATE)

    assert verifier.availability is VerifierAvailability.NOT_INSTALLED
    assert verdict.status is VerificationStatus.UNAVAILABLE
    assert verdict.owner_score is None and not verdict.owner_detected


# --------------------------------------------------------------------------
# 3. Télémétrie en ombre


def test_an_owner_sequence_is_a_candidate_then_a_confirmation():
    telemetry, journal = telemetry_for(ScriptedSpeakerVerifier([None, None, 0.8, 0.9], threshold=0.7))
    published = listen(telemetry)

    feed_all(telemetry, 4)
    feed_all(telemetry, QUIET_HOPS, near=False)

    assert journal.kinds() == [OWNER_CANDIDATE, OWNER_CONFIRMED]
    candidate, confirmed = journal.of(OWNER_CANDIDATE)[0], journal.of(OWNER_CONFIRMED)[0]
    # Le candidat s'ouvre sur la 12e trame proche (2e fenêtre), daté de la 1re.
    assert (candidate["status"], candidate["far_end"]) == ("insufficient_audio", False)
    # Latence de l'ombre : du début du candidat (0) à la fin de la 3e fenêtre.
    assert (confirmed["owner_score"], confirmed["confirm_ms"], confirmed["evidence_ms"]) == (0.8, 300, 100)
    assert (confirmed["after_non_owner"], confirmed["far_end"]) == (False, False)
    assert confirmed["mode"] == "shadow" and confirmed["engine"] == "fake-speaker/1"
    # Parole finie : preuve vidée (candidat), puis 600 ms sans parole proche.
    assert [snapshot.state for snapshot in published] == [
        OwnerState.CANDIDATE, OwnerState.OWNER_CONFIRMED, OwnerState.CANDIDATE, OwnerState.IDLE
    ]
    owner = published[1]
    assert (owner.candidate_onset_ms, owner.owner_onset_ms, owner.confirmed_ms, owner.stream_ms) == (0, 0, 300, 300)
    assert telemetry.publisher.latest == published[-1] and published[-1].candidate_onset_ms is None


def test_a_non_owner_sequence_is_a_candidate_then_a_rejection():
    telemetry, journal = telemetry_for(ScriptedSpeakerVerifier([0.2, 0.2, 0.3, 0.1]))

    feed_all(telemetry, 4)
    feed_all(telemetry, QUIET_HOPS, near=False)

    assert journal.kinds() == [OWNER_CANDIDATE, OWNER_REJECTED]
    # La 1re fenêtre précède le candidat : son verdict ne compte pas.
    assert journal.of(OWNER_REJECTED)[0].items() >= {
        "best_score": 0.3, "episode_ms": 400, "reason": "non_owner", "far_end": False
    }.items()


def test_an_ambiguous_sequence_never_crosses_the_engine_threshold():
    telemetry, journal = telemetry_for(ScriptedSpeakerVerifier([0.6, 0.6, 0.69, 0.65], threshold=0.7))

    feed_all(telemetry, 4)
    feed_all(telemetry, QUIET_HOPS, near=False)

    assert journal.kinds() == [OWNER_CANDIDATE, OWNER_REJECTED]
    assert journal.of(OWNER_REJECTED)[0]["best_score"] == 0.69


def test_speech_too_short_to_judge_is_rejected_for_insufficient_audio():
    telemetry, journal = telemetry_for(ScriptedSpeakerVerifier([None] * 3))

    feed_all(telemetry, 3)
    feed_all(telemetry, QUIET_HOPS, near=False)

    assert journal.kinds() == [OWNER_CANDIDATE, OWNER_REJECTED]
    assert journal.of(OWNER_REJECTED)[0].items() >= {"best_score": None, "reason": "insufficient_audio"}.items()


def test_the_owner_is_confirmed_while_a_stranger_keeps_talking():
    """D06 : quatre secondes d'étranger, puis le propriétaire, sans un silence."""

    stranger, owner = [0.2] * 40, [owner_verdict(0.9, 1500)] * 20
    telemetry, journal = telemetry_for(ScriptedSpeakerVerifier([*stranger, *owner]))
    published = listen(telemetry)

    feed_all(telemetry, 60)

    assert [snapshot.state for snapshot in published] == [OwnerState.REJECTED, OwnerState.OWNER_CONFIRMED]
    confirmed = published[-1]
    # Confirmé à la fin de la 41e fenêtre ; début estimé = début de la preuve
    # qui l'a reconnu (1,5 s plus tôt), pas le début de l'étranger.
    assert (confirmed.candidate_onset_ms, confirmed.confirmed_ms, confirmed.owner_onset_ms) == (0, 4100, 2600)
    assert (confirmed.owner_score, confirmed.evidence_ms) == (0.9, 1500)
    assert journal.kinds() == [OWNER_CANDIDATE, OWNER_CONFIRMED]
    assert journal.of(OWNER_CONFIRMED)[0].items() >= {"confirm_ms": 4100, "after_non_owner": True}.items()


def test_overlapping_voices_follow_the_latest_verdict_window_by_window():
    """Chevauchement scripté : chaque verdict jugé décide, sans verrou ni hystérésis."""

    script = [0.2, 0.2, 0.9, 0.3, owner_verdict(0.95, 300), 0.9, 0.2]
    telemetry, journal = telemetry_for(ScriptedSpeakerVerifier(script))
    published = listen(telemetry)

    feed_all(telemetry, len(script))

    assert [snapshot.state for snapshot in published] == [
        OwnerState.REJECTED, OwnerState.OWNER_CONFIRMED, OwnerState.REJECTED, OwnerState.OWNER_CONFIRMED, OwnerState.REJECTED
    ]
    again = published[3]
    assert (again.confirmed_ms, again.owner_onset_ms) == (500, 200)
    # Rejeté ensuite : les instants de la dernière confirmation restent posés.
    assert (published[-1].confirmed_ms, published[-1].owner_onset_ms) == (500, 200)
    assert [snapshot.sequence for snapshot in published] == [1, 2, 3, 4, 5]
    assert journal.kinds() == [OWNER_CANDIDATE, OWNER_CONFIRMED]  # au plus deux par épisode


def test_verdicts_outside_an_acoustic_candidate_never_make_an_owner():
    """Écho seul, clics de clavier, chocs : le verdict « propriétaire » est ignoré."""

    telemetry, journal = telemetry_for(ScriptedSpeakerVerifier([0.99] * 200))
    published = listen(telemetry)

    feed_all(telemetry, 50, near=False, far=True)  # JARVIS parle, personne d'autre
    clicks = ([True, True] + [False] * 11) * 30  # 20 ms toutes les 130 ms
    feed_flags(telemetry, clicks)
    feed_flags(telemetry, clicks, far=True)
    feed_flags(telemetry, [True] * 5 + [False] * 5)  # un choc de 50 ms

    assert published == [] and journal.events == []
    assert telemetry.publisher.latest.state is OwnerState.IDLE


def test_a_reset_closes_the_episode_without_a_verdict_and_resets_the_engine():
    verifier = ScriptedSpeakerVerifier([0.2, 0.3, None, 0.9])
    telemetry, journal = telemetry_for(verifier)
    feed_all(telemetry, 2)

    telemetry.reset()
    feed_all(telemetry, 2)

    assert verifier.resets == 1
    # Pas de rejet pour une phrase coupée par la fin de session ; la suivante
    # repart d'une preuve vide, sur l'horloge de la nouvelle session.
    assert journal.kinds() == [OWNER_CANDIDATE, OWNER_CANDIDATE, OWNER_CONFIRMED]
    assert journal.of(OWNER_CONFIRMED)[0].items() >= {"evidence_ms": 100, "confirm_ms": 200}.items()
    latest = telemetry.publisher.latest
    assert (latest.session, latest.state, latest.confirmed_ms) == (1, OwnerState.OWNER_CONFIRMED, 200)


def test_a_crashing_verifier_is_degraded_once_and_voice_goes_on():
    verifier = ScriptedSpeakerVerifier([0.3, 0.3, RuntimeError("onnx session lost"), None, 0.9])
    telemetry, journal = telemetry_for(verifier)

    feed_all(telemetry, 5)

    assert telemetry.availability is VerifierAvailability.FAILED
    assert len(verifier.calls) == 3  # plus consulté après la panne
    assert telemetry.publisher.latest.state is OwnerState.IDLE  # candidat abandonné, sans verdict
    unavailable = journal.of(OWNER_UNAVAILABLE)
    assert unavailable == [
        {"mode": "shadow", "engine": "fake-speaker/1", "availability": "failed", "code": "verifier_exception", "error": "RuntimeError"}
    ]
    assert OWNER_REJECTED not in journal.kinds()

    telemetry.reset()  # nouvelle session : nouvelle chance
    feed_all(telemetry, 2)

    assert telemetry.availability is VerifierAvailability.READY
    assert journal.kinds()[-2:] == [OWNER_CANDIDATE, OWNER_CONFIRMED]


def test_a_verifier_breaking_the_contract_is_treated_as_failed():
    class Liar(ScriptedSpeakerVerifier):
        def process(self, pcm: bytes, sample_rate: int):  # noqa: ANN201
            return {"owner_score": 1.0}

    telemetry, journal = telemetry_for(Liar())

    feed_all(telemetry, 1)

    assert telemetry.availability is VerifierAvailability.FAILED
    assert journal.of(OWNER_UNAVAILABLE)[0]["error"] == "TypeError"


def test_a_failing_reset_is_degraded_not_fatal():
    class BrokenReset(ScriptedSpeakerVerifier):
        def reset(self) -> None:
            raise OSError("profile file locked")

    verifier = BrokenReset([0.9])
    telemetry, journal = telemetry_for(verifier)

    telemetry.reset()
    feed_all(telemetry, 1)

    assert telemetry.availability is VerifierAvailability.FAILED
    assert verifier.calls == []
    assert journal.of(OWNER_UNAVAILABLE)[0]["code"] == "verifier_reset_failed"


@pytest.mark.parametrize(
    "verifier,availability",
    [
        (NullSpeakerVerifier(), VerifierAvailability.NOT_INSTALLED),
        (ScriptedSpeakerVerifier([0.9], availability=VerifierAvailability.NO_OWNER_PROFILE), VerifierAvailability.NO_OWNER_PROFILE),
    ],
)
def test_an_unready_verifier_is_reported_once_per_session_and_never_consulted(verifier, availability):  # noqa: ANN001
    telemetry, journal = telemetry_for(verifier)

    feed_all(telemetry, 20)
    telemetry.reset()
    feed_all(telemetry, 20)

    assert telemetry.availability is availability
    assert journal.kinds() == [OWNER_UNAVAILABLE, OWNER_UNAVAILABLE]
    assert journal.of(OWNER_UNAVAILABLE)[0].items() >= {"code": "verifier_not_ready", "availability": availability.value}.items()
    assert getattr(verifier, "calls", []) == []


def test_error_windows_report_the_change_of_state_not_every_window():
    error = VerificationStatus.ERROR
    telemetry, journal = telemetry_for(ScriptedSpeakerVerifier([0.3, 0.3, error, error, error, 0.3, 0.3]))

    feed_all(telemetry, 7)
    feed_all(telemetry, QUIET_HOPS, near=False)

    # Le candidat interrompu par la panne est abandonné sans verdict ; le
    # suivant repart de zéro, candidat acoustique compris.
    assert journal.kinds() == [OWNER_CANDIDATE, OWNER_UNAVAILABLE, OWNER_CANDIDATE, OWNER_REJECTED]
    assert journal.of(OWNER_UNAVAILABLE)[0].items() >= {"code": "verifier_error", "availability": "failed", "status": "error"}.items()
    assert telemetry.availability is VerifierAvailability.READY


def test_a_continuous_stream_cannot_flood_the_trace():
    # Vingt épisodes de 200 ms de parole et 600 ms de silence : quarante
    # évènements possibles en seize secondes de flux, trois autorisés par minute.
    episode = [0.2, 0.2] + [None] * QUIET_HOPS
    telemetry, journal = telemetry_for(ScriptedSpeakerVerifier(episode * 20 + [None] * 600 + [0.2, 0.2]), max_events_per_minute=3)

    for _ in range(20):
        feed_all(telemetry, 2)
        feed_all(telemetry, QUIET_HOPS, near=False)
    assert len(journal.events) == 3

    feed_all(telemetry, 600, near=False)  # une minute plus tard
    feed_all(telemetry, 2)

    assert len(journal.events) == 4
    assert journal.events[-1]["kind"] == OWNER_CANDIDATE
    assert journal.events[-1]["data"]["suppressed"] == 37


def test_telemetry_carries_rounded_metadata_only():
    verifier = ScriptedSpeakerVerifier([0.1, 0.123456, 0.987654] + [None] * QUIET_HOPS + [0.1, 0.1, RuntimeError("x")])
    telemetry, journal = telemetry_for(verifier)

    def broken_listener(snapshot: OwnerStateSnapshot) -> None:
        raise ValueError("consumer bug")

    telemetry.publisher.add(broken_listener)
    telemetry.skip(300)

    feed_all(telemetry, 3)
    feed_all(telemetry, QUIET_HOPS, near=False)
    feed_all(telemetry, 3)

    assert {OWNER_OVERRUN, OWNER_CANDIDATE, OWNER_CONFIRMED, OWNER_UNAVAILABLE, OWNER_LISTENER_FAILED} <= set(journal.kinds())
    scalars = (str, int, float, bool, type(None))
    for event in journal.events:
        for key, value in event["data"].items():  # type: ignore[union-attr]
            assert isinstance(value, scalars), (key, value)
            assert not isinstance(value, str) or len(value) <= MAX_SPEAKER_ID_CHARS, (key, value)
            assert not any(word in key for word in ("pcm", "audio", "embedding", "vector", "sample"))
    assert journal.of(OWNER_CANDIDATE)[0]["owner_score"] == 0.123
    assert journal.of(OWNER_CONFIRMED)[0]["owner_score"] == 0.988


def test_a_journal_that_fails_does_not_stop_the_measure():
    class BrokenJournal:
        def emit(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            raise OSError("disk full")

    verifier = ScriptedSpeakerVerifier([0.2, 0.9])
    telemetry = ShadowOwnerTelemetry(verifier, sample_rate=RATE, diagnostics=BrokenJournal())

    feed_all(telemetry, 2)

    assert len(verifier.calls) == 2 and telemetry.availability is VerifierAvailability.READY
    assert telemetry.publisher.latest.state is OwnerState.OWNER_CONFIRMED


def test_a_failing_listener_is_dropped_once_and_the_others_still_hear():
    telemetry, journal = telemetry_for(ScriptedSpeakerVerifier([0.2, 0.2, 0.9]))
    calls: list[OwnerState] = []

    def broken(snapshot: OwnerStateSnapshot) -> None:
        calls.append(snapshot.state)
        raise RuntimeError("consumer bug")

    telemetry.publisher.add(broken)
    healthy = listen(telemetry)

    feed_all(telemetry, 3)

    assert calls == [OwnerState.REJECTED]  # retiré après sa première panne
    assert [snapshot.state for snapshot in healthy] == [OwnerState.REJECTED, OwnerState.OWNER_CONFIRMED]
    assert journal.of(OWNER_LISTENER_FAILED) == [
        {"mode": "shadow", "engine": "fake-speaker/1", "availability": "ready", "code": "owner_listener_failed", "error": "RuntimeError"}
    ]


def test_listeners_are_bounded_and_can_unsubscribe():
    telemetry, _ = telemetry_for(ScriptedSpeakerVerifier([0.2, 0.9]))
    seen: list[OwnerStateSnapshot] = []
    unsubscribe = telemetry.publisher.add(seen.append)
    for _ in range(telemetry.publisher.max_listeners - 1):
        telemetry.publisher.add(lambda snapshot: None)

    with pytest.raises(ValueError):
        telemetry.publisher.add(lambda snapshot: None)
    unsubscribe()
    feed_all(telemetry, 2)

    assert seen == []
    assert telemetry.publisher.latest.state is OwnerState.OWNER_CONFIRMED


def test_a_new_sample_rate_starts_a_new_stream():
    verifier = ScriptedSpeakerVerifier([0.2, 0.9, 0.9])
    telemetry, _ = telemetry_for(verifier)
    published = listen(telemetry)
    feed_all(telemetry, 2)
    assert published[-1].state is OwnerState.OWNER_CONFIRMED

    telemetry.feed(bytes(16000 // 10 * 2), hop_contexts(0, rate=16000))

    assert published[-1].state is OwnerState.IDLE and published[-1].session == 1
    assert verifier.resets == 1
    assert verifier.calls[-1] == (16000 // 10 * 2, 16000)
    assert telemetry.sample_rate == 16000


def test_owner_state_snapshots_stay_coherent_by_construction():
    with pytest.raises(ValueError):
        OwnerStateSnapshot(state=OwnerState.IDLE, candidate_onset_ms=10)
    with pytest.raises(ValueError):
        OwnerStateSnapshot(state=OwnerState.OWNER_CONFIRMED, candidate_onset_ms=0)
    with pytest.raises(ValueError):
        OwnerStateSnapshot(sequence=-1)
    with pytest.raises(TypeError):
        OwnerStateSnapshot(state="owner_confirmed")  # type: ignore[arg-type]
    snapshot = OwnerStateSnapshot()
    with pytest.raises(AttributeError):
        snapshot.state = OwnerState.REJECTED  # type: ignore[misc]


def test_owner_state_stays_bounded_over_a_long_run():
    """Vingt minutes de conversation mêlée : aucune structure ne grandit."""

    pattern = [0.2] * 30 + [owner_verdict(0.9, 1500)] * 15 + [None] * 15 + [0.95] * 10
    verifier = ScriptedSpeakerVerifier(pattern * 200)
    telemetry, journal = telemetry_for(verifier)
    published: list[int] = []
    telemetry.publisher.add(lambda snapshot: published.append(snapshot.sequence))

    for _ in range(200):
        feed_all(telemetry, 45)  # étranger puis propriétaire, sans silence
        feed_all(telemetry, 15, near=False)  # silence : le candidat se referme
        feed_all(telemetry, 10, near=False, far=True)  # JARVIS parle seul

    assert telemetry._last_end_ms == 200 * 70 * 100
    machine = telemetry.machine
    assert len(machine._near) <= 40 and machine.region is None and machine.state is OwnerState.IDLE
    assert len(telemetry._sent) <= telemetry.max_events_per_minute
    assert len(telemetry.publisher._listeners) == 1
    # Quatre changements par cycle (rejeté, confirmé, preuve vidée, idle) ;
    # l'écho seul n'en provoque aucun.
    assert published == list(range(1, 4 * 200 + 1))
    assert journal.kinds() == [OWNER_CANDIDATE, OWNER_CONFIRMED] * 200  # deux par épisode


# --------------------------------------------------------------------------
# 4. Le fil du vérificateur


@pytest.fixture
def workers():
    started: list[SpeakerVerificationWorker] = []
    yield started
    for worker in started:
        worker.close()


def make_worker(workers, verifier, **options):  # noqa: ANN001, ANN003
    journal = RecordingJournal()
    worker = SpeakerVerificationWorker(verifier, sample_rate=RATE, diagnostics=journal, **options)
    workers.append(worker)
    return worker, journal


def observe_frames(worker, count: int, *, start_ms: int = 0, near: bool = True, far: bool = False, rate: int = RATE, pcm=None) -> int:  # noqa: ANN001
    """Trames de 10 ms comme la capture les remet ; rend l'instant suivant."""

    frame = bytes(rate // 100 * 2) if pcm is None else pcm
    for index in range(count):
        worker.observe(frame, ctx(start_ms + index * FRAME_MS, near=near, far=far, rate=rate))
    return start_ms + count * FRAME_MS


class RecordingPcm(ScriptedSpeakerVerifier):
    """Garde ce que le moteur a reçu, pour vérifier le masquage de l'écho."""

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.received: list[bytes] = []

    def process(self, pcm: bytes, sample_rate: int) -> SpeakerVerification:
        self.received.append(pcm)
        return super().process(pcm, sample_rate)


def test_the_worker_hands_fixed_windows_to_the_verifier_in_its_own_thread(workers):
    threads: list[str] = []

    class Recording(ScriptedSpeakerVerifier):
        def process(self, pcm: bytes, sample_rate: int) -> SpeakerVerification:
            threads.append(threading.current_thread().name)
            return super().process(pcm, sample_rate)

    verifier = Recording([0.2, 0.9])
    worker, journal = make_worker(workers, verifier)
    published: list[tuple[str, OwnerState]] = []
    worker.add_owner_listener(lambda snapshot: published.append((threading.current_thread().name, snapshot.state)))

    observe_frames(worker, 25)  # 250 ms de trames de 10 ms
    assert worker.flush(TIMEOUT_S)

    assert verifier.calls == [(len(HOP), RATE)] * 2  # la troisième fenêtre n'est pas complète
    assert set(threads) == {"jarvis-speaker-verifier"}
    assert journal.kinds() == [OWNER_CANDIDATE, OWNER_CONFIRMED]
    # L'état se publie dans le fil du vérificateur, jamais dans la capture.
    assert published == [("jarvis-speaker-verifier", OwnerState.OWNER_CONFIRMED)]
    assert worker.owner_state.state is OwnerState.OWNER_CONFIRMED and worker.owner_state.confirmed_ms == 200


def test_echo_only_frames_reach_the_verifier_as_digital_silence(workers):
    verifier = RecordingPcm([0.5] * 20)
    worker, _ = make_worker(workers, verifier)
    loud = (b"\x10\x27" * (RATE // 100))  # trame non nulle

    at = observe_frames(worker, 10, far=True, near=False, pcm=loud)  # JARVIS seul : masqué
    at = observe_frames(worker, 1, start_ms=at, far=True, near=True, pcm=loud)  # parole proche
    at = observe_frames(worker, 39, start_ms=at, far=True, near=False, pcm=loud)  # 300 ms gardées, puis masquées
    observe_frames(worker, 10, start_ms=at, far=False, near=False, pcm=loud)  # JARVIS se tait : tout passe
    assert worker.flush(TIMEOUT_S)

    frames = [pcm[i:i + len(loud)] for pcm in verifier.received for i in range(0, len(pcm), len(loud))]
    kept = [frame == loud for frame in frames]
    assert [frame == bytes(len(loud)) for frame in frames] == [not flag for flag in kept]
    assert kept == [False] * 10 + [True] * 31 + [False] * 9 + [True] * 10


def test_a_new_sample_rate_drops_the_partial_window_and_restarts_the_state(workers):
    verifier = ScriptedSpeakerVerifier([0.2, 0.9, 0.5, 0.5])
    worker, _ = make_worker(workers, verifier)
    at = observe_frames(worker, 20)
    observe_frames(worker, 5, start_ms=at)  # demi-fenêtre en cours à 24 kHz
    assert worker.flush(TIMEOUT_S)
    assert worker.owner_state.state is OwnerState.OWNER_CONFIRMED

    observe_frames(worker, 20, rate=16000, near=False)
    assert worker.flush(TIMEOUT_S)

    assert verifier.calls == [(len(HOP), RATE)] * 2 + [(16000 // 10 * 2, 16000)] * 2
    assert worker.owner_state.state is OwnerState.IDLE and worker.owner_state.session == 1


def test_a_slow_verifier_never_holds_the_capture_and_the_queue_stays_bounded(workers):
    entered, gate = threading.Event(), threading.Event()

    class Slow(ScriptedSpeakerVerifier):
        def process(self, pcm: bytes, sample_rate: int) -> SpeakerVerification:
            entered.set()
            assert gate.wait(TIMEOUT_S)
            return super().process(pcm, sample_rate)

    verifier = Slow([0.5] * 100)
    worker, journal = make_worker(workers, verifier, max_pending_ms=500)
    at = observe_frames(worker, 10)
    assert entered.wait(TIMEOUT_S)

    for _ in range(40):  # 4 s de capture pendant que le moteur est bloqué
        at = observe_frames(worker, 10, start_ms=at)
        assert worker.pending <= worker.max_pending
    gate.set()
    assert worker.flush(TIMEOUT_S)

    assert worker.dropped_ms >= 3000
    assert len(verifier.calls) <= 1 + worker.max_pending
    # Audio sauté : une trace par session, et le moteur repart d'une fenêtre vide.
    assert journal.kinds().count(OWNER_OVERRUN) == 1
    assert journal.of(OWNER_OVERRUN)[0].items() >= {"code": "verifier_overrun"}.items()
    assert verifier.resets >= 1


def test_a_crash_in_the_verifier_does_not_kill_the_worker(workers):
    verifier = ScriptedSpeakerVerifier([RuntimeError("boom"), 0.9, 0.9])
    worker, journal = make_worker(workers, verifier)

    observe_frames(worker, 30)
    assert worker.flush(TIMEOUT_S)
    assert worker.availability is VerifierAvailability.FAILED

    worker.reset()
    observe_frames(worker, 20)
    assert worker.flush(TIMEOUT_S)

    assert worker.availability is VerifierAvailability.READY
    assert journal.kinds() == [OWNER_UNAVAILABLE, OWNER_CANDIDATE, OWNER_CONFIRMED]


def test_an_unexpected_error_in_the_shadow_suspends_it_without_killing_the_thread(workers):
    verifier = ScriptedSpeakerVerifier([0.9] * 10)
    worker, journal = make_worker(workers, verifier)

    def broken_step(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("state machine bug")

    worker.telemetry.machine.step = broken_step  # type: ignore[method-assign]
    observe_frames(worker, 20)
    assert worker.flush(TIMEOUT_S)

    assert worker._thread.is_alive()
    assert worker.availability is VerifierAvailability.FAILED
    assert len(verifier.calls) == 1  # plus consulté jusqu'à la session suivante
    assert journal.of(OWNER_UNAVAILABLE)[0].items() >= {"code": "shadow_exception", "error": "AssertionError"}.items()


def test_a_reset_drops_pending_audio_and_resets_the_engine_in_the_worker(workers):
    entered, gate = threading.Event(), threading.Event()

    class Held(ScriptedSpeakerVerifier):
        def process(self, pcm: bytes, sample_rate: int) -> SpeakerVerification:
            entered.set()
            assert gate.wait(TIMEOUT_S)
            return super().process(pcm, sample_rate)

    verifier = Held([0.2] * 10)
    worker, _ = make_worker(workers, verifier)
    at = observe_frames(worker, 10)
    assert entered.wait(TIMEOUT_S)  # la première fenêtre est en calcul
    at = observe_frames(worker, 40, start_ms=at)
    observe_frames(worker, 5, start_ms=at)  # une demi-fenêtre en cours d'assemblage

    worker.reset()
    gate.set()
    assert worker.flush(TIMEOUT_S)

    assert verifier.resets == 1
    assert len(verifier.calls) == 1  # seule la fenêtre déjà en calcul
    assert (worker.owner_state.session, worker.owner_state.state) == (1, OwnerState.IDLE)
    observe_frames(worker, 5)
    assert worker.flush(TIMEOUT_S)
    assert len(verifier.calls) == 1  # la demi-fenêtre d'avant a été oubliée


def test_close_stops_the_thread_and_closes_the_verifier(workers):
    verifier = ScriptedSpeakerVerifier([0.9])
    worker, _ = make_worker(workers, verifier)

    worker.close()
    worker.close()
    worker.observe(HOP, ctx(0))

    assert not worker._thread.is_alive()
    assert verifier.closed
    assert verifier.calls == []


# --------------------------------------------------------------------------
# 5. Cycle de vie côté Voice


async def test_voice_shutdown_closes_the_duplex_capture_once():
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime

    class Closable:
        async def close(self) -> None:
            return None

    class Capture:
        closed = 0

        def close(self) -> None:
            Capture.closed += 1

    runtime = PersistentVoiceRuntime(wakeword=Closable(), core=Closable(), realtime_factory=None)  # type: ignore[arg-type]
    runtime._capture = Capture()

    await runtime.close()
    await runtime.close()

    assert Capture.closed == 1


async def test_returning_to_background_ends_the_capture_session_once_the_microphone_is_closed():
    """Fin de session : l'état du propriétaire ne survit pas au retour au fond."""

    import asyncio

    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime

    class Wake:
        async def resume(self) -> None:
            return None

    class Capture:
        def __init__(self) -> None:
            self.resets = 0

        def reset(self) -> None:
            self.resets += 1

    runtime = PersistentVoiceRuntime(wakeword=Wake(), core=object(), realtime_factory=None)  # type: ignore[arg-type]
    capture = runtime._capture = Capture()
    closed = asyncio.Event()

    async def bridge() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()  # le bridge referme micro et haut-parleurs

    runtime._bridge_task = asyncio.create_task(bridge())
    await asyncio.sleep(0)
    await runtime.mute()

    assert closed.is_set() and capture.resets == 1

    async def muted_from_the_bridge() -> None:
        await runtime.mute()  # micro encore ouvert : pas de remise à zéro ici

    task = runtime._bridge_task = asyncio.create_task(muted_from_the_bridge())
    await task

    assert capture.resets == 1
