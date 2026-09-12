"""Solo Owner : seule la voix du propriétaire constitue un tour (tâche 07).

Handoff `tasks/jarvis_solo_owner_duplex_handoff/`, D05–D11, spec §1.4, §2, §3.
Ce fichier prouve, vérificateur scripté et détecteur piloté (déterministe) :

- capture : garde au propriétaire, JARVIS silencieux, une autre voix n'atteint
  jamais le fournisseur ; le propriétaire est rejoué depuis son début, une fois ;
  une réponse brève reconnue à la fin de son candidat est rejouée entière ;
- vérificateur et état : verdict de fin de candidat (accepté, écarté, trop
  bref), preuve neuve pour chaque candidat, passage de relais sans silence
  borné ; `voice.input.non_owner_dropped` sans audio ni texte ;
- bridge : une conversation de fond ne crée ni tour, ni activité utile, ni
  accusé ; le propriétaire garde l'adressage (`addressed` / `uncertain`,
  Décision 44) ; l'ordonnanceur n'est tenu que le temps du jugement ;
- runtime : refus de Solo Owner pour chaque cause, même verdict côté Control
  Center ; vérificateur perdu en cours de session → entrée fermée, session
  désactivée, nouvelle chance au réveil suivant ; cycle mute / fond inchangé.

La salle ouverte reste prouvée par les fichiers existants, inchangés.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import numpy as np
import pytest

from jarvis.adapters.fake_speaker_verifier import ScriptedSpeakerVerifier
from jarvis.audio.duplex import FRAME_MS, OWNER_REPLAY, CaptureProcessor
from jarvis.audio.owner_verifier import EmbeddingSpeakerVerifier, SpeechGate
from jarvis.audio.speaker_shadow import OWNER_CONFIRMED, OWNER_INPUT_DROPPED, OWNER_REJECTED
from jarvis.domain.speaker import (
    ConversationAuthorization,
    ConversationAuthorizationError,
    ConversationMode,
    OwnerState,
    OwnerStateSnapshot,
    SpeakerVerificationMode,
    VerificationStatus,
    VerifierAvailability,
)
from jarvis.domain.v2 import VoiceLifecycleState
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.realtime_audio import (
    AUTHORIZATION_REFUSED_KIND,
    INPUT_NON_OWNER_DROPPED_KIND,
    OWNER_REPLAY_KIND,
    RealtimeConversationBridge,
)
from jarvis.runtime.visual_signals import VisualSignalBus
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture, parse_speaker_verifier_settings
from tests.unit.test_owner_barge_in import FakeOwnerSource, Live, event, jarvis_speaking, until
from tests.unit.test_owner_replay import MARGIN_FRAMES, ReplayRig, ScriptedDetector, feed, frames, sent
from tests.unit.test_owner_voice import OWNER_HZ, STRANGER_HZ, hops, silence, tone, verifier_for
from tests.unit.test_speaker_verifier import QUIET_HOPS, feed_all, feed_flags, listen, telemetry_for
from tests.unit.test_v2_continuous_live import (
    ContinuousSession,
    FakeAudio,
    FakeClock,
    FakeCore,
    FakeWakeWord,
    RecordingJournal as LiveJournal,
)

RATE = 24000
SOLO_OWNER = ConversationAuthorization(mode=ConversationMode.SOLO_OWNER, verification=SpeakerVerificationMode.ENFORCE)


# --------------------------------------------------------------------------
# 1. Capture : le point de filtrage le plus tôt


def owner_capture(*, far=lambda index: False, **options):  # noqa: ANN001, ANN003, ANN202
    processor = CaptureProcessor(
        capture_rate=RATE,
        render_rate=RATE,
        detector=ScriptedDetector(far=far),  # type: ignore[arg-type]
        owner_buffer_ms=2500,
        **options,
    )
    assert processor.set_owner_gate(True)
    return processor


def test_jarvis_silent_another_voice_never_reaches_the_provider():
    """Cinq minutes de conversation de fond, JARVIS muet : pas un échantillon ne part."""

    processor = owner_capture()
    out, signals = feed(processor, 0, 30_000, block_frames=50)

    assert sent(out) == [] and len(out) == 30_000 * RATE // 100 * 2  # du silence, à la même cadence
    assert OWNER_REPLAY not in signals and not processor.gate_open


def test_open_room_with_jarvis_silent_still_forwards_everything():
    """Retour arrière : sans garde au propriétaire, le micro part tel quel quand JARVIS se tait."""

    processor = CaptureProcessor(
        capture_rate=RATE, render_rate=RATE, detector=ScriptedDetector(far=lambda index: False), owner_buffer_ms=2500  # type: ignore[arg-type]
    )
    out, _ = feed(processor, 0, 300)

    assert sent(out) == list(range(0, 300))


def test_the_owner_is_replayed_from_his_onset_once_while_jarvis_is_silent():
    processor = owner_capture()
    feed(processor, 0, 300)  # 1 s d'une autre voix, puis le propriétaire à 1 s, confirmé à 3 s
    processor.open_owner_flow(1000, candidate_onset_ms=1000)
    out, signals = feed(processor, 300, 400)

    assert sent(out) == list(range(100 - MARGIN_FRAMES, 400))
    assert signals.count(OWNER_REPLAY) == 1


def test_a_short_reply_confirmed_at_the_end_of_its_candidate_is_replayed_whole_then_closed():
    """Confirmation et fin du candidat arrivent ensemble : rejeu du candidat, puis silence."""

    processor = owner_capture()
    feed(processor, 0, 250)  # « oui, vas-y » de 1 à 1,8 s, candidat refermé à 2,4 s
    processor.open_owner_flow(1000, candidate_onset_ms=1000)
    processor.close_owner_flow()  # avant le bloc suivant : l'ouverture n'est pas perdue
    replayed, signals = feed(processor, 250, 255)
    after, _ = feed(processor, 255, 400)

    assert sent(replayed) == list(range(100 - MARGIN_FRAMES, 250))
    assert signals.count(OWNER_REPLAY) == 1
    assert sent(after) == []  # quelqu'un reprend ensuite : rien ne part
    (replay,) = processor.take_owner_replays()
    assert replay.until_ms == 2500 and replay.clamped_ms == 0


def test_a_close_without_pending_opening_just_closes():
    processor = owner_capture()
    processor.open_owner_flow(0)
    feed(processor, 0, 10)
    processor.close_owner_flow()
    out, _ = feed(processor, 10, 50)

    assert sent(out) == []


# --------------------------------------------------------------------------
# 2. Vérificateur : réponses brèves, preuve neuve, passage de relais


def short_verifier(**kwargs):  # noqa: ANN003, ANN202
    kwargs.setdefault("evidence_ms", 1500)
    kwargs.setdefault("short_evidence_ms", 600)
    kwargs.setdefault("short_margin", 0.1)
    return verifier_for(**kwargs)


def feed_samples(verifier: EmbeddingSpeakerVerifier, samples: np.ndarray):  # noqa: ANN201
    return [verifier.process(chunk, RATE) for chunk in hops(samples)]


def test_a_short_owner_reply_is_judged_once_at_the_end_of_its_candidate():
    verifier = short_verifier()
    verdicts = feed_samples(verifier, tone(OWNER_HZ, 800))

    assert all(verdict.status is VerificationStatus.INSUFFICIENT_AUDIO for verdict in verdicts)  # < 1,5 s
    verdict = verifier.finish_candidate(judge=True)

    assert verdict.status is VerificationStatus.OK and verdict.owner_detected
    assert verdict.owner_score >= verifier.short_threshold == pytest.approx(0.6)
    assert 700 <= verdict.evidence_ms <= 800 and verifier.short_verdicts == 1
    # Preuve oubliée : rien ne reste pour le candidat suivant.
    assert verifier.finish_candidate(judge=True).status is VerificationStatus.INSUFFICIENT_AUDIO


def test_a_short_stranger_reply_is_judged_and_rejected():
    verifier = short_verifier()
    feed_samples(verifier, tone(STRANGER_HZ, 800))

    verdict = verifier.finish_candidate(judge=True)

    assert verdict.status is VerificationStatus.OK and not verdict.owner_detected


def test_a_reply_below_the_minimum_is_not_judged():
    verifier = short_verifier()
    feed_samples(verifier, tone(OWNER_HZ, 400))  # un « oui » isolé

    verdict = verifier.finish_candidate(judge=True)

    assert verdict.status is VerificationStatus.INSUFFICIENT_AUDIO and verifier.short_verdicts == 0


def test_the_strict_threshold_rejects_a_short_window_the_full_window_would_accept():
    """Même score, deux règles : 0,55 passe la fenêtre complète (0,5), pas la réponse brève (0,6)."""

    from tests.unit.test_owner_voice import CosineEmbedder

    full = verifier_for(CosineEmbedder(0.55), evidence_ms=500)
    short = verifier_for(CosineEmbedder(0.55), evidence_ms=1500, short_evidence_ms=600, short_margin=0.1)
    assert feed_samples(full, tone(OWNER_HZ, 600))[-1].owner_detected
    feed_samples(short, tone(OWNER_HZ, 800))

    assert not short.finish_candidate(judge=True).owner_detected


def test_a_candidate_already_judged_is_not_judged_again_at_its_end():
    verifier = short_verifier()
    assert feed_samples(verifier, tone(OWNER_HZ, 1800))[-1].owner_detected
    computed = verifier.embeddings_computed

    verdict = verifier.finish_candidate(judge=True)

    assert verdict.status is VerificationStatus.INSUFFICIENT_AUDIO
    assert verifier.embeddings_computed == computed and verifier.short_verdicts == 0


class AlwaysVoiced(SpeechGate):
    """Porte qui prend tout pour de la parole : la preuve ne se vide plus d'elle-même."""

    def update(self, level: float) -> bool:
        super().update(level)
        return True


def test_the_end_of_a_candidate_forgets_the_evidence_so_the_next_one_starts_fresh():
    """Sans `finish_candidate`, le verdict du propriétaire, gardé en cache, servirait à la voix suivante."""

    lingering, fresh = verifier_for(gate=AlwaysVoiced()), verifier_for(gate=AlwaysVoiced())
    for verifier in (lingering, fresh):
        assert feed_samples(verifier, tone(OWNER_HZ, 2000))[-1].owner_detected
        feed_samples(verifier, silence(700))
    fresh.finish_candidate(judge=False)  # le candidat du propriétaire s'est refermé

    stranger = tone(STRANGER_HZ, 400)
    assert feed_samples(lingering, stranger)[0].owner_detected  # la preuve du propriétaire traîne
    first = feed_samples(fresh, stranger)
    assert all(verdict.status is VerificationStatus.INSUFFICIENT_AUDIO for verdict in first)


def voiced_ms_until_rejected(verifier: EmbeddingSpeakerVerifier) -> int:
    """Le propriétaire parle 2 s, un autre enchaîne sans silence : parole de l'autre avant le rejet."""

    assert feed_samples(verifier, tone(OWNER_HZ, 2000))[-1].owner_detected
    for index, verdict in enumerate(feed_samples(verifier, tone(STRANGER_HZ, 3000)), start=1):
        if not verdict.owner_detected:
            return index * 100
    raise AssertionError("jamais rejeté")


def test_a_handover_without_silence_is_bounded_by_the_recent_subwindow():
    """Borne du passage de relais : fenêtre récente (0,6 s) + recalcul (0,5 s), au lieu de la fenêtre entière."""

    without = voiced_ms_until_rejected(verifier_for(evidence_ms=1500))
    with_rule = voiced_ms_until_rejected(short_verifier())

    assert without == 1500  # l'embedder de bandes : fenêtre mêlée jugée « propriétaire » jusqu'au bout
    assert with_rule == 1000 and with_rule <= 600 + 500 + 100


def test_the_recent_subwindow_keeps_the_owner_while_he_keeps_talking():
    verifier = short_verifier()
    verdicts = feed_samples(verifier, tone(OWNER_HZ, 6000))

    assert all(verdict.owner_detected for verdict in verdicts[14:])  # jamais de faux rejet sur sa voix


def test_short_utterance_settings_are_bounded_and_can_be_disabled(tmp_path):
    parsed = parse_speaker_verifier_settings({}, runtime_root=tmp_path)
    assert (parsed.short_evidence_ms, parsed.short_margin) == (600, 0.1)
    assert parse_speaker_verifier_settings({"owner_short_evidence_ms": 0}, runtime_root=tmp_path).short_evidence_ms is None
    assert parse_speaker_verifier_settings({"owner_evidence_ms": 500}, runtime_root=tmp_path).short_evidence_ms == 400
    for bad in ({"owner_short_evidence_ms": 200}, {"owner_short_evidence_ms": 1500}, {"owner_short_evidence_ms": "x"}):
        with pytest.raises(ConversationAuthorizationError) as caught:
            parse_speaker_verifier_settings(bad, runtime_root=tmp_path)
        assert caught.value.code == "owner_short_evidence_invalid"
    for bad in ({"owner_short_margin": 0.5}, {"owner_short_margin": -0.1}, {"owner_short_margin": True}):
        with pytest.raises(ConversationAuthorizationError) as caught:
            parse_speaker_verifier_settings(bad, runtime_root=tmp_path)
        assert caught.value.code == "owner_short_margin_invalid"


# --------------------------------------------------------------------------
# 3. État du propriétaire : verdict de fin de candidat, entrée écartée


def test_a_short_owner_reply_is_confirmed_at_the_end_of_its_candidate():
    verifier = ScriptedSpeakerVerifier([None] * 20, candidate_script=[0.9])
    telemetry, journal = telemetry_for(verifier, enforce=True)
    published = listen(telemetry)

    feed_all(telemetry, 8)  # 800 ms de parole, jamais assez pour la fenêtre
    feed_all(telemetry, QUIET_HOPS, near=False)

    assert verifier.finish_calls == [True]
    assert [item.state for item in published] == [OwnerState.CANDIDATE, OwnerState.OWNER_CONFIRMED, OwnerState.IDLE]
    owner = published[1]
    assert (owner.candidate_onset_ms, owner.owner_onset_ms, owner.confirmed_ms) == (0, 0, 1400)
    confirmed = journal.of(OWNER_CONFIRMED)[0]
    assert confirmed["verdict"] == "candidate_end" and confirmed["confirm_ms"] == 1400
    assert journal.of(OWNER_INPUT_DROPPED) == [] and journal.of(OWNER_REJECTED) == []


@pytest.mark.parametrize(
    "candidate_script, reason, best_score",
    [([0.3], "short_not_owner", 0.3), ([None], "insufficient_audio", None)],
    ids=["short_stranger", "too_short"],
)
def test_a_short_utterance_that_is_not_the_owner_is_dropped_and_said(candidate_script, reason, best_score):  # noqa: ANN001
    verifier = ScriptedSpeakerVerifier([None] * 20, candidate_script=candidate_script)
    telemetry, journal = telemetry_for(verifier, enforce=True)
    published = listen(telemetry)

    feed_all(telemetry, 5)
    feed_all(telemetry, QUIET_HOPS, near=False)

    assert OwnerState.OWNER_CONFIRMED not in [item.state for item in published]
    (dropped,) = journal.of(OWNER_INPUT_DROPPED)
    assert dropped.items() >= {
        "mode": "enforce", "source": "capture", "reason": reason, "best_score": best_score, "candidate_ms": 500
    }.items()
    # Scalaires seulement : ni audio, ni empreinte, ni texte.
    assert all(value is None or isinstance(value, (int, float, str, bool)) for value in dropped.values())


def test_a_judged_stranger_candidate_is_dropped_without_an_end_verdict():
    verifier = ScriptedSpeakerVerifier([0.2] * 20, candidate_script=[0.99])
    telemetry, journal = telemetry_for(verifier, enforce=True)

    feed_all(telemetry, 20)
    feed_all(telemetry, QUIET_HOPS, near=False)

    assert verifier.finish_calls == [False]  # déjà jugé : pas de verdict bref, preuve oubliée
    assert journal.of(OWNER_INPUT_DROPPED)[0]["reason"] == "non_owner"


def test_shadow_mode_measures_without_calling_anything_dropped():
    verifier = ScriptedSpeakerVerifier([0.2] * 5)
    telemetry, journal = telemetry_for(verifier)

    feed_all(telemetry, 5)
    feed_all(telemetry, QUIET_HOPS, near=False)

    assert journal.of(OWNER_REJECTED) and journal.of(OWNER_INPUT_DROPPED) == []


def test_a_new_candidate_after_a_gap_is_verified_again_from_fresh_evidence():
    """Le propriétaire, 600 ms de silence, puis une autre voix : jamais « propriétaire » d'office."""

    verifier = ScriptedSpeakerVerifier([0.9] * 20 + [None] * QUIET_HOPS + [None] * 14 + [0.2] * 5)
    telemetry, journal = telemetry_for(verifier, enforce=True)
    published = listen(telemetry)

    feed_all(telemetry, 20)
    feed_all(telemetry, QUIET_HOPS, near=False)
    second = len(published)
    feed_all(telemetry, 19)
    feed_all(telemetry, QUIET_HOPS, near=False)

    assert verifier.finish_calls == [False, False]  # chaque fin de candidat efface la preuve
    states = [item.state for item in published[second:]]
    assert states[0] is OwnerState.CANDIDATE and OwnerState.OWNER_CONFIRMED not in states
    assert journal.of(OWNER_INPUT_DROPPED)[0]["reason"] == "non_owner"


def test_the_owner_handover_closes_on_the_first_stranger_verdict():
    """Pas de verrou : le premier verdict « étranger » du candidat publie `rejected` (le bridge referme)."""

    verifier = ScriptedSpeakerVerifier([0.9] * 20 + [0.2] * 5)
    telemetry, _ = telemetry_for(verifier)
    published = listen(telemetry)

    feed_flags(telemetry, [True] * 250)

    assert [item.state for item in published][-2:] == [OwnerState.OWNER_CONFIRMED, OwnerState.REJECTED]
    assert published[-1].stream_ms == 2100  # la fenêtre du premier verdict « étranger »


def test_a_verifier_failure_is_published_so_the_bridge_learns_it_at_once():
    verifier = ScriptedSpeakerVerifier([None, RuntimeError("onnx")])
    telemetry, _ = telemetry_for(verifier)
    availability_seen: list[VerifierAvailability] = []
    telemetry.publisher.add(lambda snapshot_: availability_seen.append(telemetry.availability))

    feed_all(telemetry, 1, near=False)
    feed_all(telemetry, 1, near=False)

    assert availability_seen == [VerifierAvailability.FAILED]  # idle publié, disponibilité déjà à jour


def test_the_worker_gives_a_failed_engine_a_new_chance_at_the_next_session():
    from jarvis.audio.speaker_shadow import SpeakerVerificationWorker

    worker = SpeakerVerificationWorker(ScriptedSpeakerVerifier([RuntimeError("boom")]), sample_rate=RATE)
    try:
        worker.telemetry.availability = VerifierAvailability.FAILED
        worker.reset()
        assert worker.availability is VerifierAvailability.READY  # lu par Voice avant d'ouvrir le micro
    finally:
        worker.close()
    unready = SpeakerVerificationWorker(
        ScriptedSpeakerVerifier(availability=VerifierAvailability.NO_OWNER_PROFILE), sample_rate=RATE
    )
    try:
        assert unready.availability is VerifierAvailability.NO_OWNER_PROFILE  # déclaré, pas supposé prêt
    finally:
        unready.close()


# --------------------------------------------------------------------------
# 4. Bridge : identité avant adressage, activité utile, ordonnanceur


class AddressingCore:
    def __init__(self) -> None:
        self.brain_turns: list[dict[str, object]] = []
        self.turns: list[dict[str, object]] = []

    async def submit_brain_turn(self, conversation_id: str, *, content: str, correlation_id: str, source: str = "realtime", addressing: str = "addressed", provider_item_id=None, interrupted_speech_id=None):  # noqa: ANN001,E501
        self.brain_turns.append({"content": content, "addressing": addressing})
        return {"turn_id": f"turn-{len(self.brain_turns)}", "revision": len(self.brain_turns), "duplicate": False}

    async def append_turn(self, conversation_id: str, *, kind: str, content: str, correlation_id=None, metadata=None):  # noqa: ANN001
        self.turns.append({"kind": kind, "content": content})
        return {"id": f"turn-{len(self.turns)}"}


def gate_rig(*, far=lambda index: False):  # noqa: ANN001, ANN202
    rig = ReplayRig(far=far)
    rig.core = AddressingCore()
    rig.bridge.core = rig.core
    rig.addressed, rig.ambient, rig.speech, rig.reflexes = [], [], [], []
    rig.bridge.on_addressed = lambda: rig.addressed.append(True)
    rig.bridge.on_ambient = lambda: rig.ambient.append(True)
    rig.bridge.on_user_speech = rig.speech.append
    rig.bridge.on_reflex = lambda *args, **kwargs: rig.reflexes.append(args)
    return rig


def candidate(sequence: int, state: OwnerState, *, onset: int, far_end: bool = False, confirmed: int | None = None) -> OwnerStateSnapshot:
    return OwnerStateSnapshot(
        sequence=sequence,
        session=1,
        state=state,
        stream_ms=confirmed or onset + 200,
        candidate_onset_ms=None if state is OwnerState.IDLE else onset,
        owner_onset_ms=onset if state is OwnerState.OWNER_CONFIRMED else None,
        confirmed_ms=confirmed if state is OwnerState.OWNER_CONFIRMED else None,
        owner_score=0.2 if state is OwnerState.REJECTED else (0.9 if state is OwnerState.OWNER_CONFIRMED else None),
        evidence_ms=1500,
        far_end=far_end,
    )


async def test_a_background_conversation_never_becomes_a_turn_nor_useful_activity():
    """Cinq phrases d'une autre voix, JARVIS muet : ni audio transmis, ni tour, ni réflexe, ni texte au journal."""

    rig = gate_rig()
    async with Live(rig.bridge) as live:
        sequence = 0
        for index in range(5):
            onset = rig.frame * FRAME_MS
            rig.capture(100)
            for state in (OwnerState.CANDIDATE, OwnerState.REJECTED):
                sequence += 1
                rig.source.publish(candidate(sequence, state, onset=onset))
            rig.capture(100)
            sequence += 1
            rig.source.publish(candidate(sequence, OwnerState.IDLE, onset=onset))
            await live.idle()
        # Si le fournisseur segmentait quand même (reste d'avant la garde) :
        await live.send(
            event("realtime.speech_started", item_id="item-voisin"),
            event("realtime.transcript", text="Jarvis, envoie le rapport à Paul", item_id="item-voisin"),
        )

    assert sent(bytes(rig.sent)) == []
    assert rig.core.brain_turns == [] and rig.core.turns == []
    assert rig.addressed == [] and rig.reflexes == []
    assert rig.speech == [True, False] * 5  # tenu le temps du jugement, puis relâché
    reasons = [item["data"]["reason"] for item in rig.journal.of(INPUT_NON_OWNER_DROPPED_KIND)]
    assert reasons == ["provider_speech_unverified", "transcript_unverified"]
    assert not any("rapport" in str(item["message"]) or "rapport" in str(item["data"]) for item in rig.journal.events)
    assert rig.journal.of("voice.transcript") == [] and rig.journal.of("voice.speech_started") == []


async def test_an_owner_follow_up_becomes_an_addressed_turn_and_useful_activity():
    rig = gate_rig()
    async with Live(rig.bridge) as live:
        rig.capture(300)
        rig.source.publish(candidate(1, OwnerState.CANDIDATE, onset=1000))
        rig.source.publish(candidate(2, OwnerState.OWNER_CONFIRMED, onset=1000, confirmed=3000))
        await live.idle()
        rig.capture(20)
        await live.idle()
        await live.send(
            event("realtime.speech_started", item_id="item-owner"),
            event("realtime.speech_stopped", item_id="item-owner"),
            event("realtime.transcript", text="Quelle est la météo demain ?", item_id="item-owner"),
        )
        rig.source.publish(candidate(3, OwnerState.IDLE, onset=1000))
        await live.idle()

    assert sent(bytes(rig.sent)) == list(range(100 - MARGIN_FRAMES, 320))  # du début, une fois
    assert rig.core.brain_turns == [{"content": "Quelle est la météo demain ?", "addressing": "addressed"}]
    assert rig.addressed  # l'activité utile est réarmée, comme avant
    assert rig.journal.of(INPUT_NON_OWNER_DROPPED_KIND) == []
    assert rig.speech == [True, False]  # candidat et VAD fournisseur confondus, sans doublon
    assert rig.journal.of(OWNER_REPLAY_KIND)[0]["data"]["barge_in"] is False


async def test_an_uncertain_owner_sentence_still_follows_the_brain_ownership_rule():
    """Décision 44 : identité d'abord, puis l'adressage ; le doute part au cerveau, sans activité utile."""

    rig = gate_rig()
    async with Live(rig.bridge) as live:
        rig.clock.now += rig.bridge.engagement_window_s + 1  # plus engagé
        rig.capture(200)
        rig.source.publish(candidate(1, OwnerState.OWNER_CONFIRMED, onset=500, confirmed=2000))
        await live.idle()
        rig.capture(10)
        await live.send(
            event("realtime.speech_started", item_id="item-owner"),
            event(
                "realtime.transcript",
                text="Le comité a validé le budget du trimestre prochain pour l'équipe marketing",
                item_id="item-owner",
            ),
        )

    assert rig.core.brain_turns == [
        {"content": "Le comité a validé le budget du trimestre prochain pour l'équipe marketing", "addressing": "uncertain"}
    ]
    assert rig.addressed == [] and rig.ambient and rig.reflexes == []


async def test_a_short_owner_reply_is_replayed_whole_and_becomes_a_turn():
    rig = gate_rig()
    async with Live(rig.bridge) as live:
        rig.capture(250)
        rig.source.publish(candidate(1, OwnerState.CANDIDATE, onset=1000))
        # Verdict de fin de candidat : confirmé, puis `idle`, d'un seul geste.
        rig.source.publish(candidate(2, OwnerState.OWNER_CONFIRMED, onset=1000, confirmed=2500))
        rig.source.publish(candidate(3, OwnerState.IDLE, onset=1000))
        await live.idle()
        rig.capture(100)
        await live.idle()
        await live.send(
            event("realtime.speech_started", item_id="item-oui"),
            event("realtime.transcript", text="Oui, vas-y.", item_id="item-oui"),
        )

    assert sent(bytes(rig.sent)) == list(range(100 - MARGIN_FRAMES, 250))  # tout le candidat, puis silence
    assert rig.core.brain_turns[-1]["content"] == "Oui, vas-y."


async def test_a_short_stop_confirmed_at_the_end_of_its_candidate_still_cuts_jarvis():
    rig = gate_rig(far=lambda index: True)
    async with Live(rig.bridge) as live:
        await live.send(*jarvis_speaking(chunks=6))
        rig.capture(200)
        rig.source.publish(candidate(1, OwnerState.OWNER_CONFIRMED, onset=1200, confirmed=2000, far_end=True))
        rig.source.publish(candidate(2, OwnerState.IDLE, onset=1200))
        await until(lambda: rig.audio.stop_output_calls == 1)
        await live.idle()
        rig.capture(10)
        await live.idle()

    assert rig.calls == ["stop_output", "cancel_output", "truncate", "replay"]
    assert sent(bytes(rig.sent)) == list(range(120 - MARGIN_FRAMES, 200))


async def test_the_owner_flow_closes_on_handover_and_the_stranger_is_not_forwarded():
    rig = gate_rig()
    async with Live(rig.bridge) as live:
        rig.capture(200)
        rig.source.publish(candidate(1, OwnerState.OWNER_CONFIRMED, onset=500, confirmed=2000))
        await live.idle()
        rig.capture(50)
        rig.source.publish(candidate(2, OwnerState.REJECTED, onset=500))
        await live.idle()
        rig.capture(100)
        await live.idle()

    indices = sent(bytes(rig.sent))
    assert indices[0] == 50 - MARGIN_FRAMES and indices[-1] == 249  # jusqu'au premier verdict « étranger »


async def test_a_provider_segment_long_after_the_owner_flow_closed_is_not_his():
    rig = gate_rig()
    async with Live(rig.bridge) as live:
        rig.capture(200)
        rig.source.publish(candidate(1, OwnerState.OWNER_CONFIRMED, onset=500, confirmed=2000))
        rig.source.publish(candidate(2, OwnerState.IDLE, onset=500))
        await live.idle()
        rig.capture(10)
        await live.send(event("realtime.speech_started", item_id="item-owner"))  # dans le délai
        rig.clock.now += RealtimeConversationBridge.OWNER_SEGMENT_GRACE_S + 0.1
        await live.send(
            event("realtime.speech_started", item_id="item-late"),
            event("realtime.transcript", text="Jarvis, annule tout.", item_id="item-late"),
            event("realtime.transcript", text="Merci.", item_id="item-owner"),
        )

    assert [turn["content"] for turn in rig.core.brain_turns] == ["Merci."]
    assert [item["data"]["reason"] for item in rig.journal.of(INPUT_NON_OWNER_DROPPED_KIND)] == [
        "provider_speech_unverified",
        "transcript_unverified",
    ]


async def test_a_verifier_already_failed_when_the_bridge_subscribes_ends_the_session_at_once():
    """Accepté à l'activation, le moteur lâche pendant la connexion (chargement du modèle) : entrée fermée."""

    rig = gate_rig()
    rig.source.availability = VerifierAvailability.FAILED
    live = Live(rig.bridge)
    async with live:
        await until(lambda: live.task.done())
        rig.capture(100)

    assert sent(bytes(rig.sent)) == [] and rig.processor.owner_gate
    (refused,) = rig.journal.of(AUTHORIZATION_REFUSED_KIND)
    assert refused["data"]["phase"] == "session" and refused["data"]["availability"] == "failed"


async def test_provider_drop_traces_are_bounded():
    rig = gate_rig()
    async with Live(rig.bridge) as live:
        for index in range(40):
            await live.send(event("realtime.speech_started", item_id=f"item-{index}"))
        rig.clock.now += 61
        await live.send(event("realtime.speech_started", item_id="item-later"))

    drops = rig.journal.of(INPUT_NON_OWNER_DROPPED_KIND)
    assert len(drops) == RealtimeConversationBridge.MAX_DROP_TRACES_PER_MINUTE + 1
    assert drops[-1]["data"]["suppressed"] == 10


# --------------------------------------------------------------------------
# 5. Runtime : refus, fermeture sûre, cycle de vie


class OwnerObserver(FakeOwnerSource):
    """Vérificateur branché sur la capture : état publié et nouvelle chance à chaque session."""

    def __init__(self, availability: VerifierAvailability = VerifierAvailability.READY) -> None:
        super().__init__()
        self.declared = availability
        self.availability = availability
        self.resets = 0

    def observe(self, frame: bytes, context) -> None:  # noqa: ANN001
        del frame, context

    def reset(self) -> None:
        self.resets += 1
        self.availability = self.declared

    def close(self) -> None:
        return None


class QuietAudio(FakeAudio):
    """Aucun bloc hors capture : tout ce qui part vers le fournisseur est passé par la garde."""

    instances: list["QuietAudio"] = []

    async def start(self) -> None:
        self.started.set()


class RecordingSession(ContinuousSession):
    def __init__(self) -> None:
        super().__init__()
        self.audio = bytearray()

    async def send_audio(self, pcm: bytes) -> None:
        await super().send_audio(pcm)
        self.audio += pcm


def solo_capture(observer: OwnerObserver | None = None, *, buffer_ms: int | None = 2500) -> CaptureProcessor:
    return CaptureProcessor(
        capture_rate=RATE,
        render_rate=RATE,
        detector=ScriptedDetector(far=lambda index: False),  # type: ignore[arg-type]
        observer=observer,  # type: ignore[arg-type]
        owner_buffer_ms=buffer_ms,
    )


def solo_runtime(
    monkeypatch,  # noqa: ANN001
    *,
    capture: CaptureProcessor | None = None,
    authorization: ConversationAuthorization | None = SOLO_OWNER,
    error: ConversationAuthorizationError | None = None,
    arch: VoiceArchitecture = VoiceArchitecture.CONTINUOUS_BRAIN,
    signals=None,  # noqa: ANN001
    clock: FakeClock | None = None,
    timeout_s: float = 10.0,
):  # noqa: ANN202
    import jarvis.runtime.realtime_audio as realtime_audio

    QuietAudio.instances.clear()
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", QuietAudio)
    session = RecordingSession()
    connects: list[object] = []

    async def factory(context):  # noqa: ANN001, ANN202
        connects.append(context)
        return session

    wakeword, core, journal = FakeWakeWord(), FakeCore(), LiveJournal()
    runtime = PersistentVoiceRuntime(
        wakeword=wakeword,  # type: ignore[arg-type]
        core=core,  # type: ignore[arg-type]
        realtime_factory=factory,  # type: ignore[arg-type]
        active_timeout_s=timeout_s,
        clock=clock,
        signals=signals,
        journal=journal,  # type: ignore[arg-type]
        auto_turn=True,
        voice_arch=arch,
        capture_factory=(lambda: capture) if capture is not None else None,
        authorization=authorization,
        authorization_error=error,
    )
    return SimpleNamespace(
        runtime=runtime, session=session, connects=connects, wakeword=wakeword, core=core, journal=journal
    )


def _invalid() -> ConversationAuthorizationError:
    return ConversationAuthorizationError("conversation_mode_unknown", "Mode de conversation inconnu : « salon ».")


REFUSALS = {
    "invalid_settings": (lambda: {"error": _invalid(), "authorization": None, "capture": solo_capture(OwnerObserver())}, "conversation_mode_unknown"),
    "legacy": (lambda: {"arch": VoiceArchitecture.LEGACY}, "solo_owner_requires_continuous_brain"),
    "no_capture": (lambda: {}, "solo_owner_unavailable"),
    "no_verifier": (lambda: {"capture": solo_capture(None)}, "solo_owner_unavailable"),
    "no_profile": (lambda: {"capture": solo_capture(OwnerObserver(VerifierAvailability.NO_OWNER_PROFILE))}, "solo_owner_unavailable"),
    "failed_verifier": (lambda: {"capture": solo_capture(OwnerObserver(VerifierAvailability.FAILED))}, "solo_owner_unavailable"),
    "capture_without_replay": (
        lambda: {"capture": solo_capture(OwnerObserver(), buffer_ms=None)},
        "solo_owner_capture_unsupported",
    ),
}


@pytest.mark.parametrize("cause", list(REFUSALS))
async def test_solo_owner_that_cannot_apply_is_refused_at_activation_never_run_open_room(cause, monkeypatch, tmp_path):  # noqa: ANN001
    options, code = REFUSALS[cause]
    signals = VisualSignalBus(tmp_path)
    rig = solo_runtime(monkeypatch, signals=signals, **options())

    await rig.runtime.activate()

    assert rig.runtime.runtime.state is VoiceLifecycleState.BACKGROUND
    assert rig.connects == [] and rig.wakeword.suspensions == 0 and QuietAudio.instances == []  # rien n'écoute
    (refused,) = [item for item in rig.journal.events if item["kind"] == AUTHORIZATION_REFUSED_KIND]
    assert refused["level"] == "warning" and refused["data"]["code"] == code and refused["data"]["phase"] == "activation"
    assert "open_room" in refused["message"]
    assert (tmp_path / ".voice_alert").read_text(encoding="utf-8").strip() == refused["message"]
    report = json.loads((tmp_path / VisualSignalBus.AUTHORIZATION_FILE).read_text(encoding="utf-8"))
    assert (report["status"], report["code"], report["phase"]) == ("refused", code, "activation")


async def test_a_static_refusal_is_announced_as_soon_as_voice_starts(monkeypatch, tmp_path):
    signals = VisualSignalBus(tmp_path)
    rig = solo_runtime(monkeypatch, signals=signals, error=_invalid(), authorization=None)

    rig.runtime._announce_static_refusal()

    (refused,) = [item for item in rig.journal.events if item["kind"] == AUTHORIZATION_REFUSED_KIND]
    assert refused["data"]["phase"] == "startup" and refused["data"]["code"] == "conversation_mode_unknown"


async def test_open_room_announces_nothing_and_writes_no_report(monkeypatch, tmp_path):
    signals = VisualSignalBus(tmp_path)
    rig = solo_runtime(monkeypatch, signals=signals, authorization=None)

    rig.runtime._announce_static_refusal()
    assert rig.runtime._authorization_refusal(None) is None
    assert not (tmp_path / VisualSignalBus.AUTHORIZATION_FILE).exists()


@pytest.mark.parametrize("verifier", list(VerifierAvailability))
def test_the_architecture_is_the_first_reason_and_never_touches_the_open_room(verifier):  # noqa: ANN001
    from jarvis.domain.speaker import AuthorizationStatus, assess_authorization

    solo = assess_authorization(SOLO_OWNER, verifier, continuous=False)
    room = assess_authorization(ConversationAuthorization(), verifier, continuous=False)

    assert (solo.status, solo.code) == (AuthorizationStatus.REFUSED, "solo_owner_requires_continuous_brain")
    assert "open_room" in solo.message
    assert room.status is AuthorizationStatus.READY


class ReadyProbe:
    availability = VerifierAvailability.READY

    def payload(self) -> dict[str, object]:
        return {"availability": "ready", "code": "ready"}


def control_center(tmp_path, monkeypatch, settings: dict[str, object]) -> ControlCenter:  # noqa: ANN001
    import jarvis.runtime.control_center as control_module

    for name in ("OPENAI_API_KEY", "PORCUPINE_ACCESS_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(control_module, "probe_owner_verifier", lambda *args, **kwargs: ReadyProbe())
    (tmp_path / "control-center-settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


async def authorization_of(control: ControlCenter) -> dict[str, object]:
    return json.loads((await control.get_settings(None)).text)["voice"]["authorization"]


async def test_a_refusal_only_voice_can_see_reaches_the_settings_api(monkeypatch, tmp_path):
    """La sonde dit « prêt », le moteur réellement branché ne l'est pas : l'API dit ce que Voice applique."""

    control = control_center(tmp_path, monkeypatch, {"voice_arch": "continuous_brain", "conversation_mode": "solo_owner"})
    assert (await authorization_of(control))["status"] == "ready"
    signals = VisualSignalBus(tmp_path)
    rig = solo_runtime(monkeypatch, signals=signals, capture=solo_capture(OwnerObserver(VerifierAvailability.FAILED)))

    signals.heartbeat()
    await rig.runtime.activate()
    authorization = await authorization_of(control)

    assert (authorization["status"], authorization["code"], authorization["status_source"]) == (
        "refused",
        "solo_owner_unavailable",
        "voice",
    )
    assert authorization["runtime"]["phase"] == "activation" and authorization["runtime"]["status"] == "refused"
    # Voice arrêtée (plus de battement) : l'état d'exécution disparaît, la sonde reprend la main.
    signals.offline()
    authorization = await authorization_of(control)
    assert authorization["status"] == "ready" and "runtime" not in authorization


async def test_the_api_and_voice_give_the_same_reason_under_legacy(monkeypatch, tmp_path):
    control = control_center(tmp_path, monkeypatch, {"voice_arch": "legacy", "conversation_mode": "solo_owner"})
    rig = solo_runtime(monkeypatch, arch=VoiceArchitecture.LEGACY)

    api = await authorization_of(control)
    code, message, _ = rig.runtime._authorization_refusal(None)

    assert (api["status"], api["code"], api["problem"]) == ("refused", code, message)


async def test_a_ready_activation_is_reported_and_the_gate_belongs_to_the_owner(monkeypatch, tmp_path):
    signals = VisualSignalBus(tmp_path)
    observer = OwnerObserver()
    capture = solo_capture(observer)
    rig = solo_runtime(monkeypatch, signals=signals, capture=capture)
    run_task = asyncio.create_task(rig.runtime.run())
    try:
        await rig.wakeword.queue.put("f9")
        await rig.journal.wait_until(lambda: rig.journal.count("audio.start") == 1)
        await until(lambda: len(observer.listeners) == 1)

        assert rig.runtime.runtime.state is VoiceLifecycleState.ACTIVE
        report = json.loads((tmp_path / VisualSignalBus.AUTHORIZATION_FILE).read_text(encoding="utf-8"))
        assert (report["status"], report["conversation_mode"]) == ("ready", "solo_owner")
        assert capture._owner_gate_wanted  # garde au propriétaire avant le premier bloc capté
    finally:
        rig.wakeword.closed = True
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def _wake_solo(rig, observer: OwnerObserver) -> asyncio.Task:  # noqa: ANN001
    task = asyncio.create_task(rig.runtime.run())
    await rig.wakeword.queue.put("f9")
    await rig.journal.wait_until(lambda: rig.journal.count("audio.start") == rig.journal.count("voice.active"))
    await until(lambda: len(observer.listeners) == 1)
    return task


def _drive(audio: QuietAudio, first: int, count: int) -> None:
    """La capture tourne comme sous PortAudio : garde, puis file d'envoi."""

    for start in range(first, first + count, 5):
        raw = frames(start, start + 5)
        processed, signals = audio.capture.process(raw)
        audio._deliver_capture(len(raw), processed, signals)


async def test_background_talk_lets_the_session_time_out_and_an_owner_follow_up_rearms_it(monkeypatch):
    """Session ACTIVE, délai 10 s : l'autre voix ne réarme rien ; le propriétaire, si."""

    clock = FakeClock()
    observer = OwnerObserver()
    rig = solo_runtime(monkeypatch, capture=solo_capture(observer), clock=clock, timeout_s=10)
    task = await _wake_solo(rig, observer)
    try:
        audio = QuietAudio.instances[-1]
        frame, sequence = 0, 0
        for _ in range(2):  # une autre voix, par phrases de 1 s
            onset = frame * FRAME_MS
            _drive(audio, frame, 100)
            frame += 100
            for state in (OwnerState.CANDIDATE, OwnerState.REJECTED, OwnerState.IDLE):
                sequence += 1
                observer.publish(candidate(sequence, state, onset=onset))
            await asyncio.sleep(0.01)
            clock.advance(4)
            assert await rig.runtime.check_timeout() is False
        # Le propriétaire enchaîne : reconnu, rejoué, tour adressé.
        _drive(audio, frame, 200)
        sequence += 1
        observer.publish(candidate(sequence, OwnerState.OWNER_CONFIRMED, onset=frame * FRAME_MS, confirmed=(frame + 200) * FRAME_MS))
        frame += 200
        await asyncio.sleep(0.05)
        _drive(audio, frame, 10)
        frame += 10
        await rig.session.push("realtime.speech_started", item_id="item-owner")
        await rig.session.push("realtime.transcript", text="Jarvis, rappelle-moi le rendez-vous.", item_id="item-owner")
        await until(lambda: len(rig.core.brain_turns) == 1)
        clock.advance(8)  # 16 s depuis le réveil, 8 s depuis le propriétaire
        assert await rig.runtime.check_timeout() is False
        sequence += 1
        observer.publish(candidate(sequence, OwnerState.IDLE, onset=0))
        await asyncio.sleep(0.05)  # le bridge referme le flux avant le bloc suivant
        for _ in range(3):  # de nouveau l'autre voix
            _drive(audio, frame, 50)
            frame += 50
            for state in (OwnerState.CANDIDATE, OwnerState.REJECTED, OwnerState.IDLE):
                sequence += 1
                observer.publish(candidate(sequence, state, onset=frame * FRAME_MS))
            await asyncio.sleep(0.01)
            clock.advance(1)
        await asyncio.sleep(0.05)
        heard = bytes(rig.session.audio)
        assert await rig.runtime.check_timeout() is True  # 11 s sans parole utile : retour au fond
    finally:
        rig.wakeword.closed = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert rig.core.brain_turns[0]["content"] == "Jarvis, rappelle-moi le rendez-vous."
    assert len(rig.core.brain_turns) == 1
    assert rig.runtime.runtime.state is VoiceLifecycleState.BACKGROUND
    # Seul le propriétaire est parti : ses 2 s depuis son début (marge comprise), puis 100 ms de direct.
    assert sent(heard) == list(range(200 - MARGIN_FRAMES, 410))


async def test_a_verifier_lost_mid_session_closes_the_input_and_the_next_wake_gets_a_new_chance(monkeypatch, tmp_path):
    signals = VisualSignalBus(tmp_path)
    observer = OwnerObserver()
    capture = solo_capture(observer)
    rig = solo_runtime(monkeypatch, capture=capture, signals=signals)
    task = await _wake_solo(rig, observer)
    try:
        audio = QuietAudio.instances[-1]
        observer.availability = VerifierAvailability.FAILED
        observer.publish(candidate(1, OwnerState.IDLE, onset=0))
        await rig.journal.wait_until(lambda: rig.journal.count("voice.background") == 1)
        _drive(audio, 0, 100)  # micro encore ouvert le temps de la fermeture : garde fermée
        await rig.journal.wait_until(lambda: rig.journal.count("audio.stop") == 1)
        # Laisser la boucle du runtime constater la fin du bridge : une touche
        # pressée pendant qu'il se referme serait prise pour un « stop ».
        await asyncio.sleep(0.05)
        assert sent(bytes(rig.session.audio)) == []
        report = json.loads((tmp_path / VisualSignalBus.AUTHORIZATION_FILE).read_text(encoding="utf-8"))
        assert (report["status"], report["phase"], report["code"]) == ("refused", "session", "owner_verifier_unavailable")
        assert "open_room" in (tmp_path / ".voice_alert").read_text(encoding="utf-8")

        # Réveil suivant : la capture est remise à zéro, le moteur a sa nouvelle chance.
        await rig.wakeword.queue.put("f9")
        await rig.journal.wait_until(lambda: rig.journal.count("voice.active") == 2)
        assert rig.runtime.runtime.state is VoiceLifecycleState.ACTIVE
        assert not (tmp_path / ".voice_alert").exists()
    finally:
        rig.wakeword.closed = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    refused = [item for item in rig.journal.events if item["kind"] == AUTHORIZATION_REFUSED_KIND]
    assert [item["data"]["phase"] for item in refused] == ["session"]


async def test_mute_and_background_transitions_are_unchanged_in_solo_owner(monkeypatch):
    observer = OwnerObserver()
    capture = solo_capture(observer)
    rig = solo_runtime(monkeypatch, capture=capture)
    task = await _wake_solo(rig, observer)
    try:
        await rig.wakeword.queue.put("f9")  # la touche de réveil coupe, comme toujours
        await asyncio.wait_for(rig.wakeword.resumed.wait(), timeout=1.0)
        await rig.journal.wait_until(lambda: rig.journal.count("voice.background") == 1)
        assert rig.runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert not capture.owner_gate and capture.stream_ms == 0  # capture remise à zéro au fond
        assert observer.listeners == []
    finally:
        rig.wakeword.closed = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert rig.session.closed
