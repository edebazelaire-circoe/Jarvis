"""Slice 06 - la lane ambiante : la salle devient du texte récent, rien de plus.

Ce que cette suite doit prouver, et la manière dont elle le prouve :

- **D03 / G7.** Une phrase entendue dans la salle n'autorise rien, même à
  l'impératif. Prouvé sur le type (l'énumération de déclencheurs entière), sur
  l'analyse (des impératifs réels), et sur les deux refus d'admission qui
  existent déjà et qui ne doivent pas bouger.
- **D06.** Le fil de séance est écrit **avant** toute analyse, et le retard de
  l'enrichissement se lit dans l'instantané.
- **D04 / D08.** Un ouvrier ambiant délibérément lent ne retarde pas
  l'admission d'un déclencheur explicite — mesuré, pas affirmé — et une
  transcription qui tombe laisse la touche manuelle entière.
- Chaque phrase d'en-tête de la forme « X ne peut jamais arriver » a son test à
  l'endroit exact où elle se casserait (leçon des quatre blocages de la
  Slice 04).
- Aucun test n'inspecte du texte source, **sauf** les deux gardes de graphe
  d'imports, qui portent sur l'absence d'un import : voir leurs docstrings.
- **Le vrai micro n'est jamais ouvert** et aucun fournisseur de transcription
  réel n'est joint : la fabrique de flux et le transcripteur sont injectés.
"""

from __future__ import annotations

import array
import ast
import asyncio
import dataclasses
import json
import math
import time
from pathlib import Path

import pytest

from jarvis.audio import input_ownership
from jarvis.audio.ambient_segmenter import (
    DEFAULT_MAX_UTTERANCE_MS,
    FRAME_MS,
    AmbientSegment,
    AmbientSegmenter,
)
from jarvis.audio.capture import pcm16_to_wav
from jarvis.audio.capture_hub import AudioCaptureHub
from jarvis.core.presentation_working_set import PresentationStateResult, PresentationWorkingSetStore
from jarvis.core.voice_state import VoiceStateDisposition
from jarvis.domain.ambient_observation import (
    MAX_AMBIENT_TEXT_CHARS,
    MAX_TRIGGERS_PER_UTTERANCE,
    AmbientAnalysis,
    AmbientObservationError,
    AmbientTrigger,
    AmbientTriggerKind,
    AmbientUtterance,
    analyse_ambient_text,
    clip_ambient_text,
    is_low_value_filler,
    looks_imperative,
    utc_now,
)
from jarvis.domain.explicit_address import ExplicitAddressSource
from jarvis.domain.presentation_working_set import UtteranceOrigin
from jarvis.domain.v2 import AddressingDecision, BrainTurnInput
from jarvis.domain.voice_admission import VoiceTurnAdmissionRequest
from jarvis.runtime.ambient_lane import (
    _DISPOSITION_POLICY,
    MAX_CONSECUTIVE_TRANSCRIPTION_FAILURES,
    AmbientIngestionLane,
    AmbientLaneError,
)
from jarvis.runtime.presentation_audio import PresentationAudioSession

HUB_RATE = 24000
BLOCK_FRAMES = 1200  # 50 ms
SESSION = "presentation-session-1"
ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# Doubles
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_input_registry():
    """Le compteur de propriétaires d'entrée est un état de processus."""

    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


class RecordingJournal:
    """Journal en mémoire. Ce qui compte est ce qui a été **dit**."""

    def __init__(self, *, fail: bool = False) -> None:
        self.entries: list[dict[str, object]] = []
        self.fail = fail

    def emit(self, kind, message, *, level="info", data=None) -> None:  # noqa: ANN001
        if self.fail:
            raise RuntimeError("journal indisponible")
        self.entries.append({"kind": kind, "message": message, "level": level, "data": data or {}})

    def codes(self, level: str | None = None) -> list[str]:
        return [
            str(entry["data"].get("code"))  # type: ignore[union-attr]
            for entry in self.entries
            if (level is None or entry["level"] == level) and entry["data"].get("code")  # type: ignore[union-attr]
        ]

    def kinds(self) -> list[str]:
        return [str(entry["kind"]) for entry in self.entries]

    def blob(self) -> str:
        return json.dumps(self.entries, ensure_ascii=False, default=repr)


class FakeCaptureDevice:
    """Périphérique d'entrée faux : il compte ses ouvertures et pousse du PCM."""

    def __init__(self) -> None:
        self.opens = 0
        self.callback = None
        self.stopped = 0
        self.closed = 0

    def factory(self, *, samplerate, channels, dtype, device, blocksize, callback):  # noqa: ANN001
        self.opens += 1
        self.callback = callback
        return self

    def stop(self) -> None:
        self.stopped += 1

    def close(self) -> None:
        self.closed += 1

    def push_block(self, chunk: bytes) -> None:
        assert self.callback is not None, "le flux n'a pas été ouvert"
        self.callback(chunk, len(chunk) // 2, None, None)


class FakeTranscriber:
    """Transcripteur faux. Aucun réseau, aucun modèle, aucune clé.

    Satisfait `jarvis.ports.transcription.TranscriptionBackend` sans l'importer
    — exactement comme l'adaptateur réel, qui ne l'importe pas non plus.
    """

    def __init__(self, *texts: str, delay_s: float = 0.0, raises: BaseException | None = None) -> None:
        self.texts = list(texts) or ["une phrase ambiante quelconque"]
        self.delay_s = delay_s
        self.raises = raises
        self.calls = 0
        self.clips: list[object] = []

    async def transcribe(self, audio):  # noqa: ANN001
        self.calls += 1
        self.clips.append(audio)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.raises is not None:
            raise self.raises
        text = self.texts[min(self.calls - 1, len(self.texts) - 1)]
        return _Transcript(text)


@dataclasses.dataclass(frozen=True)
class _Transcript:
    text: str
    duration_ms: int = 0
    provider: str = "fake"
    model: str = "fake"


class ScriptedSink:
    """Magasin factice qui rend la disposition qu'on lui dicte."""

    def __init__(self, disposition: VoiceStateDisposition, code: str = "scripted") -> None:
        self.disposition = disposition
        self.code = code
        self.observed: list[tuple] = []
        self.applied: list[object] = []
        self.pruned = 0

    def _result(self) -> PresentationStateResult:
        return PresentationStateResult(disposition=self.disposition, code=self.code, revision=1)

    def observe(self, session_id, utterance_id, text, *, spoken_at=None, origin=None, revision=0):  # noqa: ANN001
        self.observed.append((session_id, utterance_id, text, revision))
        return self._result()

    def apply(self, observation):  # noqa: ANN001
        self.applied.append(observation)
        return self._result()

    def prune(self, now=None):  # noqa: ANN001
        self.pruned += 1
        return PresentationStateResult(disposition=VoiceStateDisposition.IGNORED, code="nothing", revision=1)

    @property
    def snapshot(self):
        raise AssertionError("un magasin scripté n'a pas d'instantané à lire")


class OrderSpySink:
    """Magasin réel enveloppé, qui note **l'ordre** des appels reçus."""

    def __init__(self, store: PresentationWorkingSetStore) -> None:
        self.store = store
        self.calls: list[str] = []

    def observe(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.calls.append("observe")
        return self.store.observe(*args, **kwargs)

    def apply(self, observation):  # noqa: ANN001
        self.calls.append("apply")
        return self.store.apply(observation)

    def prune(self, now=None):  # noqa: ANN001
        return self.store.prune(now)

    @property
    def snapshot(self):
        return self.store.snapshot


class FakeTriggerBackend:
    """Source d'adresse explicite pilotée par le test (la touche manuelle)."""

    def __init__(self, *, label: str = "f9") -> None:
        self.label = label
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False

    async def detections(self):
        while True:
            yield await self.queue.get()

    async def suspend(self) -> None: ...

    async def suspend_for_active_session(self) -> None: ...

    async def resume(self) -> None: ...

    async def close(self) -> None:
        self.closed = True

    def press(self) -> None:
        self.queue.put_nowait(self.label)


# --------------------------------------------------------------------------
# Générateurs de PCM
# --------------------------------------------------------------------------


def pcm(ms: int, amplitude: int, *, rate: int = HUB_RATE) -> bytes:
    count = rate * ms // 1000
    return array.array(
        "h", [int(amplitude * math.sin(2 * math.pi * 180 * index / rate)) for index in range(count)]
    ).tobytes()


def speech(ms: int = 1500) -> bytes:
    return pcm(ms, 9000)


def silence(ms: int = 1200) -> bytes:
    return pcm(ms, 15)


async def feed(device: FakeCaptureDevice, pcm: bytes) -> None:
    """Pousser du PCM comme le ferait PortAudio : bloc par bloc, dans le temps.

    Tout déverser en un seul tour de boucle ferait déborder la file bornée de
    l'abonné — la contre-pression est réelle et c'est un autre test qui
    l'exerce. Ici on veut la salle telle qu'elle parle.
    """

    block = BLOCK_FRAMES * 2
    for index, offset in enumerate(range(0, len(pcm), block)):
        device.push_block(pcm[offset : offset + block])
        if index % 8 == 7:
            await asyncio.sleep(0)
    await asyncio.sleep(0)


async def until(predicate, timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition jamais atteinte"
        await asyncio.sleep(0.005)


def build_store() -> PresentationWorkingSetStore:
    store = PresentationWorkingSetStore()
    store.bind_session(SESSION)
    return store


async def build_lane(
    *, transcriber=None, sink=None, journal=None, hub_journal=None, device=None, **kwargs,
) -> tuple[AmbientIngestionLane, FakeCaptureDevice, object]:
    device = device or FakeCaptureDevice()
    hub = AudioCaptureHub(
        sample_rate=HUB_RATE, block_frames=BLOCK_FRAMES, stream_factory=device.factory,
        journal=hub_journal if hub_journal is not None else journal,
    )
    await hub.open()
    sink = sink if sink is not None else build_store()
    lane = AmbientIngestionLane(
        hub=hub, transcriber=transcriber or FakeTranscriber(), sink=sink,
        session_id=SESSION, journal=journal, **kwargs,
    )
    await lane.start()
    return lane, device, hub


# ==========================================================================
# 1. D03 / G7 - l'ambiant n'autorise rien
# ==========================================================================


def test_aucun_declencheur_ambiant_n_autorise_une_action() -> None:
    """Toute l'énumération est parcourue, pas un échantillon.

    D03 dit « cannot authorize user-visible or persistent actions ». Un test
    qui ne vérifierait qu'une valeur laisserait une nature d'action entrer par
    la suivante.
    """

    assert AmbientTrigger.authorizes_actions is False
    for kind in AmbientTriggerKind:
        trigger = AmbientTrigger(kind=kind, utterance_id="amb-000001", text="quelque chose")
        assert trigger.authorizes_actions is False
        assert trigger.to_payload()["authorizes_actions"] is False
    # Le vocabulaire est fermé et ne décrit que de l'enquête.
    assert {kind.value for kind in AmbientTriggerKind} == {
        "checkable_claim", "external_reference", "open_question", "new_topic",
    }


def test_une_enonciation_ambiante_n_autorise_jamais_une_action() -> None:
    utterance = AmbientUtterance(
        utterance_id="amb-000001", session_id=SESSION, text="bonjour", spoken_at=utc_now(),
    )
    assert utterance.authorizes_actions is False
    assert AmbientAnalysis.authorizes_actions is False
    # `replace` est le chemin de mutation réaliste : il ne peut pas la lever.
    assert dataclasses.replace(utterance, text="autre").authorizes_actions is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        utterance.text = "autre"  # type: ignore[misc]


@pytest.mark.parametrize(
    "phrase",
    [
        "ouvre le fichier",
        "supprime la ligne 12",
        "Envoie le rapport à Marie et efface la note.",
        "Lance le déploiement maintenant.",
        "Affiche le tableau des ventes puis supprime la page 4.",
    ],
)
def test_une_phrase_a_l_imperatif_entendue_dans_la_salle_n_autorise_rien(phrase: str) -> None:
    """La forme est reconnue, **et rien n'en sort**.

    C'est la phrase d'en-tête « ambient text is context, never a command »
    exercée à l'endroit où elle se casserait : une analyse qui déciderait de
    fabriquer une consigne à partir d'un impératif.
    """

    analysis = analyse_ambient_text("amb-000001", phrase)
    assert analysis.imperative is True, "l'impératif doit être reconnu pour être compté"
    assert analysis.authorizes_actions is False
    for trigger in analysis.triggers:
        assert trigger.authorizes_actions is False
        assert trigger.kind in set(AmbientTriggerKind)
    # Une consigne n'est pas une affirmation vérifiable : rien à confronter.
    assert analysis.claims == ()


def test_un_tour_ambiant_ne_peut_pas_entrer_dans_l_admission_adressee() -> None:
    """Les deux refus qui existent déjà, exercés depuis cette Slice.

    G7 : ils ne bougent pas. Ce test tombe si quelqu'un les assouplit pour
    faire entrer de l'ambiant dans le cerveau.
    """

    with pytest.raises(ValueError):
        BrainTurnInput(
            conversation_id="c1", text="ouvre le fichier",
            addressing=AddressingDecision.AMBIENT,
        )
    with pytest.raises(ValueError):
        VoiceTurnAdmissionRequest(
            conversation_id="c1", text="ouvre le fichier",
            addressing=AddressingDecision.AMBIENT, session_id="s1",
            canonical_turn_id="t1", transcript_id="tr1", transcript_revision=0,
            provider_item_id="p1",
        )


def test_l_enum_d_adressage_reste_fermee() -> None:
    assert {value.value for value in AddressingDecision} == {"addressed", "ambient", "uncertain"}


async def test_une_consigne_entendue_dans_la_salle_ne_produit_aucune_autorisation_de_bout_en_bout() -> None:
    """Le même refus, mais par la lane complète plutôt que par l'analyse seule."""

    store = build_store()
    triggers: list[AmbientTrigger] = []
    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber("Ouvre le fichier des ventes et supprime la ligne 12."),
        sink=store, on_trigger=triggers.append,
    )
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: lane.counters.transcripts_ok >= 1)
        await until(lambda: lane.counters.imperative_utterances >= 1)

        assert lane.counters.imperative_utterances == 1
        assert all(trigger.authorizes_actions is False for trigger in triggers)
        snapshot = store.snapshot
        assert snapshot.authorizes_actions is False
        assert snapshot.tail.entries[-1].origin is UtteranceOrigin.AMBIENT
        # Rien de ce qui est rangé n'est une affirmation à vérifier, et rien
        # n'a pu devenir un tour adressé.
        assert snapshot.working_set.claims == ()
        with pytest.raises(ValueError):
            BrainTurnInput(
                conversation_id="c1", text=snapshot.tail.entries[-1].text,
                addressing=AddressingDecision.AMBIENT,
            )
    finally:
        await lane.stop()
        await hub.close()


# ==========================================================================
# 2. Analyse bon marché
# ==========================================================================


@pytest.mark.parametrize("phrase", ["euh", "bon voilà donc", "ok d'accord", "   ", "…"])
def test_le_remplissage_est_reconnu(phrase: str) -> None:
    assert is_low_value_filler(phrase) is True


@pytest.mark.parametrize("phrase", ["la marge a doublé", "le rapport est faux", "pourquoi ?"])
def test_une_phrase_courte_mais_porteuse_n_est_pas_du_remplissage(phrase: str) -> None:
    assert is_low_value_filler(phrase) is False


def test_une_affirmation_chiffree_devient_une_piste_de_verification() -> None:
    analysis = analyse_ambient_text("amb-000001", "La marge nette a atteint 14 pour cent cette annee.")
    kinds = {trigger.kind for trigger in analysis.triggers}
    assert AmbientTriggerKind.CHECKABLE_CLAIM in kinds
    assert analysis.claims


def test_une_reference_nommee_devient_une_piste_de_recherche() -> None:
    analysis = analyse_ambient_text("amb-000001", "Le rapport annuel de Deloitte le dit page 12.")
    kinds = {trigger.kind for trigger in analysis.triggers}
    assert AmbientTriggerKind.EXTERNAL_REFERENCE in kinds
    assert "Deloitte" in analysis.entities


def test_une_question_reste_une_question() -> None:
    analysis = analyse_ambient_text("amb-000001", "Pourquoi est-ce que la croissance ralentit ?")
    assert analysis.questions
    assert {trigger.kind for trigger in analysis.triggers} >= {AmbientTriggerKind.OPEN_QUESTION}


def test_l_analyse_reste_bornee_quoi_qu_on_lui_donne() -> None:
    """« Une énonciation ne peut pas produire une analyse illimitée. »"""

    phrase = " ".join(f"La mesure {index} a atteint {index} pour cent." for index in range(40))
    analysis = analyse_ambient_text("amb-000001", phrase[:MAX_AMBIENT_TEXT_CHARS])
    assert len(analysis.triggers) <= MAX_TRIGGERS_PER_UTTERANCE
    assert len(analysis.claims) <= MAX_TRIGGERS_PER_UTTERANCE
    assert len(analysis.topics) <= 2
    assert len(analysis.entities) <= 4


def test_une_analyse_ordinaire_contenant_un_chevron_ne_fait_pas_tomber_la_lane() -> None:
    """La leçon B4 de la Slice 04, exercée depuis son producteur.

    `bounded_text` vaut pour la parole, `safe_reference_text` pour les
    locators. « si la marge < 10 % » est une phrase française ordinaire.
    """

    analysis = analyse_ambient_text("amb-000001", "Si la marge < 10 % alors le plan tombe.")
    assert analysis.filler is False
    utterance = AmbientUtterance(
        utterance_id="amb-000001", session_id=SESSION,
        text="Si la marge < 10 % alors le plan tombe.", spoken_at=utc_now(),
    )
    assert "<" in utterance.text


def test_un_texte_de_fournisseur_trop_long_est_coupe_plutot_que_perdu() -> None:
    clipped = clip_ambient_text("a " * (MAX_AMBIENT_TEXT_CHARS * 2))
    assert len(clipped) <= MAX_AMBIENT_TEXT_CHARS
    assert clipped


def test_une_enonciation_refuse_un_tampon_d_audio_brut() -> None:
    for payload in (b"\x00\x01", bytearray(b"\x00\x01"), memoryview(b"\x00\x01")):
        with pytest.raises((TypeError, ValueError, AmbientObservationError)):
            AmbientUtterance(
                utterance_id="amb-000001", session_id=SESSION,
                text=payload, spoken_at=utc_now(),  # type: ignore[arg-type]
            )


def test_l_analyse_bon_marche_reste_bon_marche() -> None:
    """D08 : rien de cher par énonciation. Mesuré, pas supposé."""

    phrase = "La marge nette a atteint 14 pour cent selon le rapport annuel de Deloitte."
    started = time.perf_counter()
    for _ in range(200):
        analyse_ambient_text("amb-000001", phrase)
    per_call_ms = (time.perf_counter() - started) * 1000 / 200
    assert per_call_ms < 2.0, f"analyse trop chère : {per_call_ms:.3f} ms par énonciation"


# ==========================================================================
# 3. Segmentation
# ==========================================================================


def test_le_segmenteur_rend_une_enonciation_par_phrase() -> None:
    segmenter = AmbientSegmenter(sample_rate=HUB_RATE)
    out: list[AmbientSegment] = []
    for chunk in (silence(400), speech(1500), silence(1000), speech(1500), silence(900)):
        out.extend(segmenter.push(chunk))
    out.extend(segmenter.flush())
    assert len(out) == 2
    assert [segment.sequence for segment in out] == [1, 2]
    assert all(segment.truncated is False for segment in out)


def test_une_parole_trop_courte_est_jetee_et_comptee() -> None:
    segmenter = AmbientSegmenter(sample_rate=HUB_RATE)
    out: list[AmbientSegment] = []
    for chunk in (silence(400), speech(120), silence(1200)):
        out.extend(segmenter.push(chunk))
    out.extend(segmenter.flush())
    assert out == []
    assert segmenter.discarded_short >= 1


def test_un_orateur_qui_ne_respire_pas_est_coupe_d_office() -> None:
    """« Un tampon d'audio ne peut jamais grossir sans borne. »"""

    segmenter = AmbientSegmenter(sample_rate=HUB_RATE, max_utterance_ms=1000)
    out: list[AmbientSegment] = []
    for _ in range(6):
        out.extend(segmenter.push(speech(500)))
    assert out, "la coupe d'office doit rendre des segments"
    assert out[0].truncated is True
    assert segmenter.forced_cuts >= 2
    ceiling = (1000 // FRAME_MS + 1) * segmenter.frame_bytes
    assert segmenter.pending_bytes <= ceiling


def test_le_segmenteur_ne_retient_jamais_plus_que_sa_borne() -> None:
    segmenter = AmbientSegmenter(sample_rate=HUB_RATE)
    ceiling = (DEFAULT_MAX_UTTERANCE_MS // FRAME_MS + 2) * segmenter.frame_bytes
    for _ in range(40):
        segmenter.push(speech(1000))
        assert segmenter.pending_bytes <= ceiling


def test_un_segment_ne_montre_jamais_son_pcm() -> None:
    """Un `repr()` recopié dans un journal suffirait à faire fuir de l'audio."""

    marker = b"\x7f\x7e" * 32
    segment = AmbientSegment(
        sequence=1, pcm=marker + speech(600), sample_rate=HUB_RATE,
        started_at_s=0.0, duration_s=0.6,
    )
    assert "7f" not in repr(segment)
    assert marker.hex() not in repr(segment)
    assert "pcm" not in segment.to_payload()
    assert json.dumps(segment.to_payload()).find(marker.hex()) == -1


def test_le_segmenteur_travaille_a_la_frequence_du_hub_et_ne_convertit_rien() -> None:
    """Le rééchantillonneur du hub n'a pas de filtre anti-repliement.

    Contrainte reprise de la Slice 05 : un abonné qui transcrit demande la
    fréquence du hub. Prouvé par les octets : ce qui entre dans le segmenteur
    ressort tel quel dans le segment.
    """

    segmenter = AmbientSegmenter(sample_rate=HUB_RATE)
    body = speech(1500)
    out: list[AmbientSegment] = []
    for chunk in (body, silence(1000)):
        out.extend(segmenter.push(chunk))
    assert out
    assert out[0].sample_rate == HUB_RATE
    # Le corps de la phrase est présent octet pour octet, sans conversion.
    assert body[len(body) // 3 : len(body) // 3 + 256] in out[0].pcm


# ==========================================================================
# 4. La lane de bout en bout
# ==========================================================================


async def test_la_parole_continue_met_le_fil_a_jour() -> None:
    store = build_store()
    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber("La marge nette progresse.", "Le rapport le confirme."), sink=store,
    )
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000) + speech(1200) + silence(1000))
        await until(lambda: len(store.snapshot.tail.entries) >= 2)
        entries = store.snapshot.tail.entries
        assert [entry.text for entry in entries] == ["La marge nette progresse.", "Le rapport le confirme."]
        assert [entry.sequence for entry in entries] == [1, 2]
        assert all(entry.origin is UtteranceOrigin.AMBIENT for entry in entries)
    finally:
        await lane.stop()
        await hub.close()


async def test_le_fil_est_ecrit_avant_toute_analyse() -> None:
    """D06, dans l'ordre exact des appels.

    Si l'analyse passait d'abord, un déictique se résoudrait sur le dernier
    fait compris et non sur la dernière parole — la péremption que D06 existe
    pour empêcher.
    """

    spy = OrderSpySink(build_store())
    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber("La marge nette a atteint 14 pour cent."), sink=spy,
    )
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: "apply" in spy.calls)
        assert spy.calls[0] == "observe", spy.calls
        assert spy.calls.index("observe") < spy.calls.index("apply")
    finally:
        await lane.stop()
        await hub.close()


async def test_le_retard_de_l_enrichissement_se_lit_dans_l_instantane() -> None:
    """Le fil avance pendant que l'analyse est retenue : l'écart se mesure."""

    store = build_store()
    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber("La marge nette a atteint 14 pour cent."), sink=store,
    )
    try:
        # L'analyse est retenue : c'est exactement la situation que D06 décrit
        # — l'enrichissement a du retard, la parole n'en a pas.
        for task in lane._tasks:
            if task.get_name() == "ambient-analysis":
                task.cancel()
        await asyncio.sleep(0)
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: len(store.snapshot.tail.entries) >= 1)
        snapshot = store.snapshot
        assert snapshot.working_set.counts()["topics"] == 0
        assert snapshot.enrichment_lag_entries >= 1
        assert snapshot.enrichment_lag_s >= 0.0
    finally:
        await lane.stop()
        await hub.close()


async def test_une_coupe_d_office_revise_l_enonciation_au_lieu_d_en_creer_une_seconde() -> None:
    """La suite d'une phrase coupée est une **révision**, pas une phrase neuve.

    Sinon une seule phrase occuperait plusieurs rangs du fil et le déictique
    « ça » désignerait un morceau arbitraire.
    """

    store = build_store()
    segmenter = AmbientSegmenter(sample_rate=HUB_RATE, max_utterance_ms=1000, min_utterance_ms=200)
    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber("le début", "la suite"), sink=store, segmenter=segmenter,
    )
    try:
        await feed(device, speech(1800) + silence(1200))
        await until(lambda: lane.counters.revisions >= 1)
        entries = store.snapshot.tail.entries
        assert len(entries) == 1, [entry.text for entry in entries]
        assert entries[0].revision == 1
        assert entries[0].text == "le début la suite"
        # Le rang ne bouge pas : une correction tardive ne se fait jamais
        # passer pour la parole la plus fraîche.
        assert entries[0].sequence == 1
        assert segmenter.forced_cuts >= 1
        assert lane.counters.revisions == 1
    finally:
        await lane.stop()
        await hub.close()


async def test_deux_mentions_du_meme_sujet_sont_coalescees_et_non_dupliquees() -> None:
    store = build_store()
    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber(
            "La marge nette a atteint 14 pour cent.",
            "La marge nette a atteint 15 pour cent.",
        ),
        sink=store,
    )
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000) + speech(1200) + silence(1000))
        await until(lambda: len(store.snapshot.working_set.topics) >= 1 and lane.counters.transcripts_ok >= 2)
        await until(lambda: any(topic.mention_count >= 2 for topic in store.snapshot.working_set.topics))
        topics = store.snapshot.working_set.topics
        assert len({topic.topic_id for topic in topics}) == len(topics)
        assert any(topic.label == "marge" and topic.mention_count == 2 for topic in topics)
    finally:
        await lane.stop()
        await hub.close()


async def test_la_provenance_cite_le_rang_reel_de_l_enonciation() -> None:
    """Un rang inventé rendrait `enrichment_lag_entries` sans signification."""

    store = build_store()
    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber("Le rapport annuel dit autre chose.", "La marge a atteint 14 pour cent."),
        sink=store,
    )
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000) + speech(1200) + silence(1000))
        await until(lambda: store.snapshot.working_set.observed_sequence >= 2)
        records = store.snapshot.working_set.topics + store.snapshot.working_set.claims
        assert records
        sequences = {record.provenance.sequence for record in records}
        assert sequences <= {1, 2}
        assert 2 in sequences
    finally:
        await lane.stop()
        await hub.close()


async def test_le_remplissage_est_supprime_et_compte() -> None:
    store = build_store()
    lane, device, hub = await build_lane(transcriber=FakeTranscriber("euh bon voilà donc"), sink=store)
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: lane.counters.filler_suppressed >= 1)
        # La parole reste au fil — c'est de la parole — mais rien n'est enrichi.
        assert len(store.snapshot.tail.entries) == 1
        assert store.snapshot.working_set.topics == ()
        assert store.snapshot.working_set.claims == ()
    finally:
        await lane.stop()
        await hub.close()


async def test_une_transcription_vide_ne_range_rien() -> None:
    store = build_store()
    lane, device, hub = await build_lane(transcriber=FakeTranscriber("   "), sink=store)
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: lane.counters.transcripts_empty >= 1)
        assert store.snapshot.tail.entries == ()
        assert lane.counters.transcripts_ok == 0
    finally:
        await lane.stop()
        await hub.close()


# ==========================================================================
# 5. Bornes, contre-pression, annulation
# ==========================================================================


async def test_la_lane_est_un_abonne_queued_et_jamais_en_ligne() -> None:
    """Un abonné en ligne lent affame ses voisins sur le thread de capture.

    Mesuré dans la Slice 05 : 10 blocs en 0,506 s. La transcription est le
    consommateur le plus lent du système ; elle n'a rien à faire en ligne.
    """

    lane, device, hub = await build_lane()
    try:
        subscription = lane.stats()["subscription"]
        assert subscription["inline"] is False
        assert subscription["sample_rate"] == HUB_RATE
        assert subscription["policy"] == "drop_oldest"
    finally:
        await lane.stop()
        await hub.close()


async def test_une_file_de_segments_pleine_ecarte_le_plus_ancien_et_le_compte() -> None:
    held = asyncio.Event()
    journal = RecordingJournal()

    class HoldingTranscriber(FakeTranscriber):
        async def transcribe(self, audio):  # noqa: ANN001
            self.calls += 1
            await held.wait()
            return _Transcript("bloqué")

    lane, device, hub = await build_lane(
        transcriber=HoldingTranscriber(), journal=journal, segment_queue=2,
        segmenter=AmbientSegmenter(sample_rate=HUB_RATE, min_utterance_ms=200, silence_hangover_ms=200),
    )
    try:
        for _ in range(8):
            await feed(device, speech(400) + silence(400))
            await asyncio.sleep(0)
        await until(lambda: lane.counters.segments_dropped_queue >= 1)
        assert len(lane._segments) <= 2
        assert "ambient_segment_dropped" in journal.codes(level="warning")
        assert lane.stats()["counters"]["segments_dropped_queue"] >= 1
    finally:
        held.set()
        await lane.stop()
        await hub.close()


async def test_une_file_d_analyse_pleine_ecarte_la_plus_ancienne_et_le_compte() -> None:
    lane, device, hub = await build_lane(analysis_queue=1)
    try:
        for task in lane._tasks:
            if task.get_name() == "ambient-analysis":
                task.cancel()
        await asyncio.sleep(0)
        from jarvis.runtime.ambient_lane import _QueuedAnalysis

        for index in range(4):
            lane._offer_analysis(
                _QueuedAnalysis(
                    utterance=AmbientUtterance(
                        utterance_id=f"amb-{index:06d}", session_id=SESSION,
                        text="une phrase", spoken_at=utc_now(),
                    ),
                    sequence=index + 1, generation=lane._generation,
                )
            )
        assert len(lane._analyses) == 1
        assert lane.counters.analysis_dropped_queue == 3
    finally:
        await lane.stop()
        await hub.close()


async def test_le_travail_ambiant_en_attente_s_annule() -> None:
    """D08 : le spéculatif est sacrifiable, et l'annulation se compte."""

    held = asyncio.Event()

    class HoldingTranscriber(FakeTranscriber):
        async def transcribe(self, audio):  # noqa: ANN001
            self.calls += 1
            await held.wait()
            return _Transcript("trop tard")

    store = build_store()
    lane, device, hub = await build_lane(
        transcriber=HoldingTranscriber(), sink=store,
        segmenter=AmbientSegmenter(sample_rate=HUB_RATE, min_utterance_ms=200, silence_hangover_ms=200),
    )
    try:
        for _ in range(4):
            await feed(device, speech(400) + silence(400))
            await asyncio.sleep(0)
        await until(lambda: len(lane._segments) >= 1)
        generation = lane._generation
        dropped = lane.discard_pending("mode_changed")

        assert dropped >= 1
        assert len(lane._segments) == 0
        assert lane._generation == generation + 1
        assert lane.counters.segments_cancelled >= 1
        # Le segment déjà sorti de la file, en cours de transcription, est
        # reconnu périmé à son retour : il n'atterrit pas dans le fil.
        held.set()
        await asyncio.sleep(0.05)
        assert store.snapshot.tail.entries == ()
    finally:
        held.set()
        await lane.stop()
        await hub.close()


async def test_un_segment_trop_vieux_est_ecarte_plutot_que_servi_comme_du_frais() -> None:
    journal = RecordingJournal()
    store = build_store()
    lane, device, hub = await build_lane(
        sink=store, journal=journal, max_segment_age_s=0.0,
        segmenter=AmbientSegmenter(sample_rate=HUB_RATE, min_utterance_ms=200, silence_hangover_ms=200),
    )
    try:
        await feed(device, speech(600) + silence(600))
        await until(lambda: lane.counters.segments_dropped_stale >= 1)
        assert store.snapshot.tail.entries == ()
        assert "ambient_segment_stale_age" in journal.codes(level="warning")
    finally:
        await lane.stop()
        await hub.close()


async def test_une_lane_arretee_ne_se_relance_pas() -> None:
    """Une lane relancée rouvrirait un abonnement sur un hub déjà rendu."""

    lane, device, hub = await build_lane()
    await lane.stop()
    with pytest.raises(AmbientLaneError) as raised:
        await lane.start()
    assert raised.value.code == "ambient_lane_stopped"
    await hub.close()


async def test_la_lane_rend_son_abonnement_a_l_arret() -> None:
    lane, device, hub = await build_lane()
    assert len(hub.subscriptions) == 1
    await lane.stop()
    assert hub.subscriptions == ()
    await lane.stop()  # idempotent
    await hub.close()


# ==========================================================================
# 6. Dispositions du magasin - comptées et dites, jamais avalées
# ==========================================================================


def test_toutes_les_dispositions_du_magasin_ont_une_politique() -> None:
    """« Une disposition ne peut jamais être avalée. »

    Le vocabulaire appartient à la Slice 04 ; s'il s'élargit, cette lane doit
    tomber ici plutôt que de compter en silence.
    """

    assert {value.value for value in VoiceStateDisposition} <= set(_DISPOSITION_POLICY)


@pytest.mark.parametrize(
    ("disposition", "counter", "lost"),
    [
        (VoiceStateDisposition.APPLIED, "applied", False),
        (VoiceStateDisposition.DUPLICATE, "duplicate", False),
        (VoiceStateDisposition.IGNORED, "ignored", True),
        (VoiceStateDisposition.STALE, "stale", True),
        (VoiceStateDisposition.STALE_SESSION, "stale_session", True),
        (VoiceStateDisposition.CAPACITY, "capacity", True),
        (VoiceStateDisposition.REJECTED, "rejected", True),
    ],
)
async def test_chaque_disposition_du_fil_est_comptee_et_dite(
    disposition: VoiceStateDisposition, counter: str, lost: bool,
) -> None:
    journal = RecordingJournal()
    sink = ScriptedSink(disposition, code=f"presentation_tail_{counter}")
    lane, device, hub = await build_lane(sink=sink, journal=journal)
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: lane.counters.tail_dispositions.get(counter, 0) >= 1)
        assert lane.counters.tail_dispositions[counter] == 1
        if lost:
            refusals = [entry for entry in journal.entries if entry["kind"] == "presentation.ambient.refused"]
            assert refusals, journal.kinds()
            assert refusals[0]["data"]["disposition"] == counter  # type: ignore[index]
    finally:
        await lane.stop()
        await hub.close()


async def test_une_disposition_inconnue_est_dite_a_error_plutot_qu_ignoree() -> None:
    journal = RecordingJournal()

    class _Weird:
        disposition = "fromage"
        code = "weird"
        applied = False

    sink = ScriptedSink(VoiceStateDisposition.APPLIED)
    sink._result = lambda: _Weird()  # type: ignore[assignment,method-assign]
    lane, device, hub = await build_lane(sink=sink, journal=journal)
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: lane.counters.tail_dispositions.get("unknown", 0) >= 1)
        assert "ambient_disposition_unknown" in journal.codes(level="error")
    finally:
        await lane.stop()
        await hub.close()


# ==========================================================================
# 7. Isolation des pannes
# ==========================================================================


async def test_une_transcription_en_echec_laisse_la_touche_manuelle_vivante() -> None:
    """La panne ambiante ne désarme pas la voie de commande explicite.

    `docs/03-implementation-strategy.md` : « Ambient failure must not disable
    the explicit command lane. » Ici c'est la même capture partagée, le même
    processus, et la transcription tombe à chaque appel.
    """

    device = FakeCaptureDevice()
    manual = FakeTriggerBackend()
    journal = RecordingJournal()
    session = PresentationAudioSession.build(
        manual_backend=manual, stream_factory=device.factory,
        sample_rate=HUB_RATE, block_frames=BLOCK_FRAMES, journal=journal,
    )
    await session.start()
    store = build_store()
    lane = AmbientIngestionLane(
        hub=session.hub, transcriber=FakeTranscriber(raises=RuntimeError("provider hors service")),
        sink=store, session_id=SESSION, journal=journal,
    )
    await lane.start()
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: lane.counters.transcripts_failed >= 1)

        manual.press()
        triggers = session.lane.triggers()
        trigger = await asyncio.wait_for(anext(triggers), timeout=1.0)

        assert trigger.source is ExplicitAddressSource.MANUAL_KEY
        assert trigger.authorizes_actions is False
        assert store.snapshot.tail.entries == ()
        assert "ambient_transcription_failed" in journal.codes(level="error")
        # La panne cite les mots du fournisseur, pas une formule générique.
        assert any("provider hors service" in str(entry["message"]) for entry in journal.entries)
    finally:
        await lane.stop()
        await session.stop()


async def test_un_ouvrier_ambiant_lent_ne_retarde_pas_l_admission_d_un_declencheur() -> None:
    """D04, **mesuré**. L'arriéré ambiant n'entre pas dans la latence de commande."""

    device = FakeCaptureDevice()
    manual = FakeTriggerBackend()
    session = PresentationAudioSession.build(
        manual_backend=manual, stream_factory=device.factory,
        sample_rate=HUB_RATE, block_frames=BLOCK_FRAMES,
    )
    await session.start()
    store = build_store()
    lane = AmbientIngestionLane(
        hub=session.hub, transcriber=FakeTranscriber("phrase", delay_s=0.5),
        sink=store, session_id=SESSION,
        segmenter=AmbientSegmenter(sample_rate=HUB_RATE, min_utterance_ms=200, silence_hangover_ms=200),
    )
    await lane.start()
    try:
        for _ in range(6):
            await feed(device, speech(400) + silence(400))
            await asyncio.sleep(0)
        await until(lambda: lane.stats()["counters"]["segments_in"] >= 2)
        assert lane._segments or lane.counters.segments_dropped_queue, "la lane doit être en arriéré"

        triggers = session.lane.triggers()
        started = time.perf_counter()
        manual.press()
        trigger = await asyncio.wait_for(anext(triggers), timeout=1.0)
        admission_s = time.perf_counter() - started

        assert trigger.source is ExplicitAddressSource.MANUAL_KEY
        assert admission_s < 0.15, f"admission retardée par l'ambiant : {admission_s * 1000:.1f} ms"
    finally:
        await lane.stop()
        await session.stop()


async def test_trois_echecs_consecutifs_degradent_la_lane_et_le_disent_une_fois() -> None:
    journal = RecordingJournal()
    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber(raises=RuntimeError("quota épuisé")), journal=journal,
        segmenter=AmbientSegmenter(sample_rate=HUB_RATE, min_utterance_ms=200, silence_hangover_ms=200),
    )
    try:
        for _ in range(6):
            await feed(device, speech(400) + silence(400))
            await asyncio.sleep(0)
        await until(lambda: lane.degraded)
        assert lane.counters.transcripts_failed >= MAX_CONSECUTIVE_TRANSCRIPTION_FAILURES
        assert journal.codes(level="error").count("ambient_lane_degraded") == 1
        assert lane.stats()["degraded_reason"] == "ambient_transcription_failed"
    finally:
        await lane.stop()
        await hub.close()


async def test_une_lane_degradee_se_retablit_et_le_dit() -> None:
    journal = RecordingJournal()

    class FlakyTranscriber(FakeTranscriber):
        async def transcribe(self, audio):  # noqa: ANN001
            self.calls += 1
            if self.calls <= MAX_CONSECUTIVE_TRANSCRIPTION_FAILURES:
                raise RuntimeError("panne passagère")
            return _Transcript("la salle reparle")

    lane, device, hub = await build_lane(
        transcriber=FlakyTranscriber(), journal=journal,
        segmenter=AmbientSegmenter(sample_rate=HUB_RATE, min_utterance_ms=200, silence_hangover_ms=200),
    )
    try:
        for _ in range(10):
            await feed(device, speech(400) + silence(400))
            await asyncio.sleep(0)
        await until(lambda: lane.counters.transcripts_ok >= 1)
        assert lane.degraded is False
        assert "ambient_lane_recovered" in journal.codes()
    finally:
        await lane.stop()
        await hub.close()


async def test_un_delai_de_transcription_libere_l_ouvrier() -> None:
    journal = RecordingJournal()
    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber("jamais rendu", delay_s=5.0), journal=journal,
        transcription_timeout_s=0.05,
    )
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: lane.counters.transcripts_timeout >= 1)
        assert "ambient_transcription_timeout" in journal.codes(level="error")
    finally:
        await lane.stop()
        await hub.close()


async def test_un_consommateur_de_declencheur_en_echec_n_arrete_pas_la_parole() -> None:
    store = build_store()

    def explode(trigger):  # noqa: ANN001
        raise RuntimeError("consommateur cassé")

    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber("La marge nette a atteint 14 pour cent.", "Le rapport le confirme."),
        sink=store, on_trigger=explode,
    )
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000) + speech(1200) + silence(1000))
        await until(lambda: len(store.snapshot.tail.entries) >= 2)
        assert lane.counters.trigger_callback_failures >= 1
        assert lane.counters.triggers_emitted >= 1
    finally:
        await lane.stop()
        await hub.close()


async def test_un_journal_en_panne_n_arrete_pas_la_lane() -> None:
    store = build_store()
    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber("une phrase"), sink=store,
        journal=RecordingJournal(fail=True), hub_journal=RecordingJournal(),
    )
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: len(store.snapshot.tail.entries) >= 1)
    finally:
        await lane.stop()
        await hub.close()


async def test_le_silence_declenche_un_balayage_d_age() -> None:
    """« Sans parole, plus rien ne déclencherait les bornes d'âge. »"""

    sink = ScriptedSink(VoiceStateDisposition.APPLIED)
    lane, device, hub = await build_lane(sink=sink, idle_prune_period_s=0.01)
    try:
        await until(lambda: sink.pruned >= 2)
        assert lane.counters.prunes >= 2
    finally:
        await lane.stop()
        await hub.close()


# ==========================================================================
# 8. Aucun audio brut, aucune parole dans la trace
# ==========================================================================


async def test_aucune_ligne_de_journal_ne_porte_la_parole() -> None:
    secret = "Zorglubidule quarante-deux pour cent"
    journal = RecordingJournal()
    store = build_store()
    lane, device, hub = await build_lane(transcriber=FakeTranscriber(secret), sink=store, journal=journal)
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: len(store.snapshot.tail.entries) >= 1)
        await lane.stop()
        blob = journal.blob()
        assert "Zorglubidule" not in blob
        assert secret not in blob
        # …et le chemin normal est bien journalisé : un journal vide ne doit
        # pas pouvoir faire passer ce test.
        assert "presentation.ambient.transcribed" in journal.kinds()
        assert "presentation.ambient.analysed" in journal.kinds()
    finally:
        await hub.close()


async def test_aucune_ligne_de_journal_ne_porte_d_audio_brut() -> None:
    journal = RecordingJournal()
    lane, device, hub = await build_lane(journal=journal)
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: lane.counters.transcripts_ok >= 1)
        await lane.stop()
        blob = journal.blob()
        assert "\\x" not in blob
        assert "bytearray" not in blob
        for entry in journal.entries:
            for value in dict(entry["data"]).values():  # type: ignore[arg-type]
                assert not isinstance(value, (bytes, bytearray, memoryview))
    finally:
        await hub.close()


async def test_le_chemin_normal_est_journalise_autant_que_les_refus() -> None:
    journal = RecordingJournal()
    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber("La marge nette a atteint 14 pour cent."), journal=journal,
    )
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: lane.counters.transcripts_ok >= 1)
        await lane.stop()
        kinds = set(journal.kinds())
        assert {
            "presentation.ambient.started",
            "presentation.ambient.segmented",
            "presentation.ambient.transcribed",
            "presentation.ambient.analysed",
            "presentation.ambient.stopped",
        } <= kinds
    finally:
        await hub.close()


def test_le_wav_produit_pour_le_fournisseur_reste_en_memoire_et_porte_la_frequence() -> None:
    data = pcm16_to_wav(speech(200), HUB_RATE)
    assert data[:4] == b"RIFF"
    assert int.from_bytes(data[24:28], "little") == HUB_RATE


# ==========================================================================
# 9. Gardes de structure
# ==========================================================================


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_la_lane_ambiante_n_importe_aucune_voie_d_autorisation() -> None:
    """Garde de graphe d'imports : elle porte sur l'**absence** d'un import.

    La règle « aucun test n'assert sur le texte source » ne s'applique pas ici,
    pour la même raison que pour
    `test_every_site_that_opens_a_physical_input_registers_its_owner` de la
    Slice 05 : l'absence d'un appel n'est pas prouvable par le comportement.
    Un test comportemental ne peut montrer que « ce scénario-là n'a rien
    autorisé » ; il ne peut pas montrer qu'aucun scénario ne le peut. Ce test
    assert sur le graphe d'imports (des noms de modules, pas de la prose), la
    même technique que `test_v2_architecture.py`. **Ne pas le supprimer au nom
    de la règle** : il est l'exception qu'elle prévoit.
    """

    forbidden = {
        "jarvis.core.back_brain", "jarvis.core.brain_service", "jarvis.core.v2_tools",
        "jarvis.core.actions", "jarvis.core.orchestrator", "jarvis.core.voice_admission",
        "jarvis.domain.actions", "jarvis.domain.tools", "jarvis.domain.voice_admission",
    }
    for module in ("jarvis/runtime/ambient_lane.py", "jarvis/domain/ambient_observation.py",
                   "jarvis/audio/ambient_segmenter.py"):
        names = _imports(ROOT / module)
        assert not (names & forbidden), f"{module} importe une voie d'autorisation : {names & forbidden}"
        assert "BrainTurnInput" not in {name.rsplit(".", 1)[-1] for name in names}
        assert "VoiceTurnAdmissionRequest" not in {name.rsplit(".", 1)[-1] for name in names}
        assert "AddressingDecision" not in {name.rsplit(".", 1)[-1] for name in names}


def test_le_domaine_ambiant_ne_depend_que_de_la_bibliotheque_standard() -> None:
    """Même garde que la Slice 04 : le domaine n'importe ni IO, ni adaptateur."""

    names = _imports(ROOT / "jarvis/domain/ambient_observation.py")
    forbidden = {"sqlite3", "os", "io", "pathlib", "socket", "httpx", "aiohttp", "asyncio", "numpy"}
    assert not ({name.split(".")[0] for name in names} & forbidden), names
    external = {name for name in names if name.startswith("jarvis.")}
    assert external <= {
        "jarvis.domain._checks", "jarvis.domain._checks.check_text",
        "jarvis.domain.presentation_working_set",
    } | {f"jarvis.domain.presentation_working_set.{suffix}" for suffix in (
        "MAX_CLAIM_CHARS", "MAX_ENTITY_LABEL_CHARS", "MAX_PRESENTATION_ID_CHARS",
        "MAX_QUESTION_CHARS", "MAX_TAIL_ENTRY_CHARS", "MAX_TOPIC_LABEL_CHARS",
        "presentation_id",
    )}, external


# ==========================================================================
# 10. Propriété du micro et garde de séance
# ==========================================================================


async def test_la_lane_ambiante_n_ouvre_aucun_micro() -> None:
    """« PRESENTATION a exactement un propriétaire physique de l'entrée. »

    La lane s'abonne, elle n'ouvre pas. Le compte le dit plutôt que la prose.
    """

    lane, device, hub = await build_lane()
    try:
        assert input_ownership.open_input_stream_count() == 1
        assert device.opens == 1
        assert len(hub.subscriptions) == 1
    finally:
        await lane.stop()
        await hub.close()
        assert input_ownership.open_input_stream_count() == 0


async def test_une_seance_retiree_ecarte_la_parole_sans_la_ranger_ailleurs() -> None:
    """« Une observation d'une séance retirée n'atterrit pas dans la suivante. »"""

    journal = RecordingJournal()
    store = build_store()
    lane, device, hub = await build_lane(sink=store, journal=journal)
    try:
        store.end_session()
        store.bind_session("presentation-session-2")
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: lane.counters.tail_dispositions.get("stale_session", 0) >= 1)
        assert store.snapshot.tail.entries == ()
        assert "presentation.ambient.refused" in journal.kinds()
    finally:
        await lane.stop()
        await hub.close()


async def test_les_declencheurs_sont_remis_aux_consommateurs() -> None:
    """Slice 08 branche `on_trigger` ici et ne reçoit que de l'enquête."""

    seen: list[AmbientTrigger] = []
    utterances: list[tuple] = []
    lane, device, hub = await build_lane(
        transcriber=FakeTranscriber("Le rapport annuel de Deloitte dit 14 pour cent."),
        on_trigger=seen.append, on_utterance=lambda utterance, analysis: utterances.append((utterance, analysis)),
    )
    try:
        await feed(device, silence(400) + speech(1200) + silence(1000))
        await until(lambda: seen and utterances)
        assert all(trigger.authorizes_actions is False for trigger in seen)
        assert {trigger.kind for trigger in seen} <= set(AmbientTriggerKind)
        assert lane.counters.triggers_emitted == len(seen)
        assert utterances[0][0].authorizes_actions is False
        assert looks_imperative(utterances[0][0].text) is False
    finally:
        await lane.stop()
        await hub.close()


async def test_une_parole_refusee_par_le_fil_n_enrichit_rien() -> None:
    """« Un refus est compté et dit » ne suffit pas : il doit aussi arrêter la suite.

    Si l'ensemble de travail était enrichi à partir d'une parole que le fil a
    refusée, sa provenance citerait un rang d'énonciation qui n'existe pas, et
    `enrichment_lag_entries` — la mesure même de D06 — deviendrait du bruit.
    (Mutation M6 : `_account` rendant toujours « appliqué ». Elle survivait.)
    """

    for disposition in (
        VoiceStateDisposition.CAPACITY,
        VoiceStateDisposition.REJECTED,
        VoiceStateDisposition.STALE,
        VoiceStateDisposition.DUPLICATE,
    ):
        sink = ScriptedSink(disposition)
        lane, device, hub = await build_lane(
            transcriber=FakeTranscriber("La marge nette a atteint 14 pour cent."), sink=sink,
        )
        try:
            await feed(device, silence(400) + speech(1200) + silence(1000))
            await until(lambda: sink.observed)
            await asyncio.sleep(0.05)
            assert sink.applied == [], f"{disposition.value} a laissé passer un enrichissement"
        finally:
            await lane.stop()
            await hub.close()


async def test_apres_un_retablissement_un_echec_isole_ne_redegrade_pas_la_lane() -> None:
    """Le compteur d'échecs consécutifs repart de zéro, sinon il ne compte plus
    « consécutifs » mais « depuis toujours » — et un hoquet par heure finirait
    par déclarer la lane morte.

    (Mutation M14 : `_recover` ne remettant pas le compteur à zéro. Elle
    survivait : l'ancien test ne regardait que le drapeau et la ligne.)
    """

    class ThreeBadOneGoodOneBad(FakeTranscriber):
        """Échecs 1-3 (dégradation), succès 4 (rétablissement), échec 5 isolé."""

        async def transcribe(self, audio):  # noqa: ANN001
            self.calls += 1
            if self.calls <= MAX_CONSECUTIVE_TRANSCRIPTION_FAILURES or self.calls == 5:
                raise RuntimeError("panne passagère")
            return _Transcript("la salle reparle")

    journal = RecordingJournal()
    lane, device, hub = await build_lane(
        transcriber=ThreeBadOneGoodOneBad(), journal=journal,
        segmenter=AmbientSegmenter(sample_rate=HUB_RATE, min_utterance_ms=200, silence_hangover_ms=200),
    )
    try:
        for _ in range(10):
            await feed(device, speech(400) + silence(400))
            await asyncio.sleep(0)
        await until(lambda: lane.counters.transcripts_failed >= 4 and lane.counters.transcripts_ok >= 2)
        # Une seule dégradation : l'échec isolé qui suit le rétablissement ne
        # rouvre pas la série. Un compteur qui ne repart pas de zéro compterait
        # « depuis toujours » au lieu de « consécutifs ».
        assert journal.codes(level="error").count("ambient_lane_degraded") == 1
        assert journal.codes().count("ambient_lane_recovered") >= 1
        assert lane.degraded is False
    finally:
        await lane.stop()
        await hub.close()
