"""Slice 11 - PRESENTATION câblée : un micro, une séance, et SIMPLE intact.

Ce que cette suite doit prouver, et comment :

- **D14, la seule qui compte le plus.** Tant qu'aucune séance ne vit, rien de
  PRESENTATION n'est construit et l'aiguillage d'éveil rend **exactement** les
  détections qu'on lui a données. Prouvé par comportement, jamais par lecture
  de source.
- **Jamais deux micros.** Le compte de propriétaires est lu avant, pendant et
  après ; une entrée qui trouverait un second flux refuse **bruyamment**, et
  c'est le cas hostile qui est construit, pas seulement le cas heureux.
- **D04 sous charge.** Le montage d'ingestion lente est **déterministe** : le
  transcripteur ne rend jamais, la file de segments est saturée et **mesurée
  saturée**, et c'est dans cet état que le déclencheur explicite est admis.
- **Aucune parole de la salle dans un puits durable.** Une phrase plantée dans
  l'ambiant, dans une affirmation et dans un `reason` est cherchée dans la
  trace entière, message compris.
- **Le `--tools` du profil de préparation** est lu sur l'`argv` réellement
  construit, pas sur une intention.
- Chaque phrase d'en-tête de la forme « X ne peut jamais arriver » a son test
  (leçon de la Slice 04), et l'état discriminant est construit **avant** d'être
  attaqué (leçon répétée huit fois dans cette tâche).

Aucun test ici n'inspecte du texte source. Aucun vrai micro n'est ouvert, aucun
fournisseur de transcription n'est joint, aucun CLI n'est lancé.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.audio import input_ownership
from jarvis.core.presentation_speculative import (
    PreparedFinding,
    SpeculativeOutcome,
    SpeculativeRequest,
)
from jarvis.core.presentation_working_set import PresentationWorkingSetStore
from jarvis.domain.explicit_address import ExplicitAddressSource
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_attention import AttentionEvidence, FactCheckAssessment
from jarvis.domain.presentation_addressed_turn import AddressedTurnAction
from jarvis.domain.presentation_response import PresentationSituation
from jarvis.domain.presentation_speculative import (
    SpeculativeCapability,
    SpeculativeGrant,
    SpeculativeJobKey,
    SpeculativePriority,
)
from jarvis.domain.presentation_working_set import (
    ClaimStatus,
    ObservationProvenance,
    PreparedResource,
    PresentationClaim,
    PresentationObservation,
    PresentationSource,
    PresentationTopic,
    ResourceKind,
    ResourceTemperature,
    UtteranceOrigin,
)
from jarvis.domain.v2 import SpeechKind, utc_now
from jarvis.runtime.claude_local import CLI_GRANTABLE_TOOLS, ClaudeLocalAgent
from jarvis.runtime.interaction_mode_observer import InteractionModeObserver
from jarvis.runtime.presentation_audio import PresentationAudioError
from jarvis.runtime.presentation_preparation import (
    PreparationClaim,
    PresentationPreparationRunner,
)
from jarvis.runtime.presentation_runtime import (
    LedgeredSceneStager,
    PresentationComposition,
    PresentationCoordinator,
    PresentationStack,
    PresentationWakeRouter,
    StagedObjectLedger,
    claims_reader,
    source_recorder,
)

from tests.fakes.speech_context import context as speech_context
from tests.unit.test_ambient_ingestion_lane import (
    FakeCaptureDevice,
    FakeTranscriber,
    RecordingJournal,
    feed,
    silence,
    speech,
    until,
)

HUB_RATE = 24000
CONVERSATION = "conv-presentation-11"
ROOT = Path(__file__).resolve().parents[2]


# ==========================================================================
# Doubles propres à cette Slice
# ==========================================================================


@pytest.fixture(autouse=True)
def clean_input_registry():
    """Le compte de propriétaires d'entrée est un état de **processus**."""

    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


class FakeManualKey:
    """La touche manuelle, sans `pynput` et sans crochet clavier global."""

    def __init__(self, label: str = "f9") -> None:
        self.label = label
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.suspended = 0
        self.resumed = 0
        self.closed = False

    async def detections(self):
        while not self.closed:
            yield await self.queue.get()

    async def suspend(self) -> None:
        self.suspended += 1

    async def suspend_for_active_session(self) -> None: ...

    async def resume(self) -> None:
        self.resumed += 1

    async def close(self) -> None:
        self.closed = True

    def press(self) -> None:
        self.queue.put_nowait(self.label)


class FakeSimpleWake:
    """La pile d'éveil de SIMPLE : un composite factice qui compte ses gestes.

    Elle **possède un flux d'entrée enregistré** tant qu'elle n'est pas
    suspendue : c'est ce qui rend « jamais deux micros » mesurable plutôt
    qu'affirmé, et c'est exactement ce que `PorcupineWakeWordBackend` fait en
    production.
    """

    def __init__(self, *, owns_device: bool = True) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.suspends = 0
        self.resumes = 0
        self.closed = False
        self.suspend_raises: BaseException | None = None
        self._owns_device = owns_device
        self._stream: object | None = None
        if owns_device:
            self._open()

    def _open(self) -> None:
        self._stream = object()
        input_ownership.register_input_stream(
            input_ownership.OWNER_WAKEWORD_PORCUPINE, self._stream, label="fake",
        )

    async def detections(self):
        while not self.closed:
            yield await self.queue.get()

    async def suspend(self) -> None:
        self.suspends += 1
        if self.suspend_raises is not None:
            raise self.suspend_raises
        stream, self._stream = self._stream, None
        if stream is not None:
            input_ownership.release_input_stream(stream)

    async def suspend_for_active_session(self) -> None:
        await self.suspend()

    async def resume(self) -> None:
        self.resumes += 1
        if self._owns_device and self._stream is None:
            self._open()

    async def close(self) -> None:
        self.closed = True
        stream, self._stream = self._stream, None
        if stream is not None:
            input_ownership.release_input_stream(stream)

    def detect(self, label: str = "jarvis") -> None:
        self.queue.put_nowait(label)


class FakeSceneTools:
    """La scène, réduite à ce que le monteur lui demande. Aucun réseau."""

    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.revealed: list[str] = []
        self.archived: list[list[str]] = []
        self._next = 0

    async def create_object(self, **fields):  # noqa: ANN003
        self._next += 1
        object_id = f"obj-{self._next}"
        self.created.append({"object_id": object_id, **fields})
        return {"object_id": object_id}

    async def set_visibility(self, *, object_id: str, visibility: str):
        self.revealed.append(object_id)
        return {"ok": True, "visibility": visibility}

    async def archive(self, *, select=None, object_ids=None):  # noqa: ANN001
        self.archived.append(list(object_ids or []))
        return {"archived": len(object_ids or [])}


class SilentRunner:
    """Un exécutant de préparation qui rend exactement ce qu'on lui dicte."""

    def __init__(self, outcome: SpeculativeOutcome | None = None) -> None:
        self.outcome = outcome or SpeculativeOutcome()
        self.requests: list[SpeculativeRequest] = []

    async def prepare(self, request: SpeculativeRequest) -> SpeculativeOutcome:
        self.requests.append(request)
        return self.outcome


class NeverAnsweringTranscriber:
    """Le transcripteur du montage de charge lente : il ne rend **jamais**.

    Déterministe au sens fort : il n'y a pas de délai à calibrer, donc pas de
    course. La file de segments se remplit jusqu'à sa borne et y reste, ce que
    le test **mesure** avant d'admettre le déclencheur explicite — c'est la
    leçon des huit occurrences : construire l'état discriminant d'abord.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.release = asyncio.Event()

    async def transcribe(self, audio):  # noqa: ANN001
        self.calls += 1
        await self.release.wait()
        return SimpleNamespace(text="phrase relâchée", duration_ms=0, provider="fake", model="fake")


def composition(
    tmp_path: Path,
    journal: RecordingJournal,
    *,
    mode=lambda: InteractionMode.PRESENTATION,
    transcriber=None,
    scene=None,
    device=None,
    manual=None,
) -> tuple[PresentationComposition, FakeCaptureDevice, FakeManualKey, FakeSceneTools]:
    """Le **même** chemin de composition qu'en production, avec des doubles."""

    device = device or FakeCaptureDevice()
    manual = manual or FakeManualKey()
    scene = scene if scene is not None else FakeSceneTools()
    built = PresentationComposition(
        runtime_root=tmp_path,
        cwd=tmp_path,
        journal=journal,
        mode=mode,
        transcriber=transcriber if transcriber is not None else FakeTranscriber(),
        scene_tools_factory=lambda: scene,
        agent_factory=None,
        stream_factory=device.factory,
        manual_backend_factory=lambda: manual,
        sample_rate=HUB_RATE,
    )
    return built, device, manual, scene


async def started_stack(tmp_path, journal, **kwargs):
    built, device, manual, scene = composition(tmp_path, journal, **kwargs)
    stack = built.build("pres-test-1")
    await stack.start()
    return stack, device, manual, scene


def anchored_working_set(store: PresentationWorkingSetStore, *, session: str) -> str:
    """Un sujet, une ressource préparée, et une énonciation qui les ancre.

    Construit **avant** toute attaque : c'est l'état discriminant dont les
    tests de réutilisation ont besoin, et le construire dans le test plutôt que
    de l'espérer est ce que cette tâche a appris huit fois.
    """

    observation = store.observe(session, "u-001", "regardons le bilan Q3", origin=UtteranceOrigin.AMBIENT)
    assert observation.applied
    rank = store.assigned_sequence
    provenance = ObservationProvenance(
        utterance_id="u-001", sequence=rank, observed_at=utc_now(), origin=UtteranceOrigin.AMBIENT,
    )
    store.apply(PresentationObservation(
        observation_id="obs-topic", session_id=session,
        record=PresentationTopic(topic_id="t-bilan", label="bilan Q3", provenance=provenance),
    ))
    store.apply(PresentationObservation(
        observation_id="obs-res", session_id=session,
        record=PreparedResource(
            resource_id="r-bilan", kind=ResourceKind.SCENE_OBJECT, locator="obj-7",
            title="Bilan Q3", temperature=ResourceTemperature.HOT, topic_id="t-bilan",
            provenance=provenance,
        ),
    ))
    return "r-bilan"


# ==========================================================================
# 1. D14 - SIMPLE reste SIMPLE, et rien de PRESENTATION n'existe
# ==========================================================================


async def test_sans_seance_l_aiguillage_rend_exactement_les_detections_de_simple() -> None:
    """D14. L'aiguillage est transparent : mêmes valeurs, même ordre.

    Test de **comportement** : on pousse trois éveils et on lit ce qui sort,
    plutôt que d'affirmer que le code délègue.
    """

    simple = FakeSimpleWake(owns_device=False)
    router = PresentationWakeRouter(simple=simple)
    detections = router.detections()
    for label in ("jarvis", "f9", "jarvis"):
        simple.detect(label)
    got = [await asyncio.wait_for(anext(detections), 1.0) for _ in range(3)]
    assert got == ["jarvis", "f9", "jarvis"]
    assert router.stats()["routing"] == "simple"
    assert router.presentation_detections == 0
    await detections.aclose()


async def test_le_mode_simple_ne_compose_aucun_sous_systeme_de_presentation(tmp_path) -> None:
    """D14. La fabrique n'est pas appelée. Zéro micro, zéro voie ambiante.

    « PRESENTATION est un mode, pas une fourche d'architecture » : en SIMPLE la
    fourche n'existe pas parce que rien n'est construit.
    """

    journal = RecordingJournal()
    simple = FakeSimpleWake()
    built: list[str] = []

    def build(session_id: str):
        built.append(session_id)
        raise AssertionError("SIMPLE ne compose aucune séance PRESENTATION")

    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=simple), build=build, journal=journal,
    )
    await coordinator.apply(InteractionMode.ASSISTANT)
    assert built == []
    assert coordinator.audio is None
    assert coordinator.turns is None
    assert simple.suspends == 0
    await coordinator.aclose()


async def test_un_mode_reserve_se_comporte_comme_simple(tmp_path) -> None:
    """REUNION n'est pas activable : il ne doit pas ouvrir de séance.

    `behaving_interaction_mode` le ramène déjà au défaut ; ce test est là pour
    que la lecture reste celle-là et pas `stored_`.
    """

    journal = RecordingJournal()
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake()),
        build=lambda session_id: pytest.fail("REUNION ne compose aucune séance"),
        journal=journal,
    )
    await coordinator.apply(InteractionMode.MEETING)
    assert coordinator.audio is None
    await coordinator.aclose()


# ==========================================================================
# 2. Jamais deux micros - compté, avant, pendant, après
# ==========================================================================


async def test_entrer_en_presentation_laisse_exactement_un_flux_d_entree(tmp_path) -> None:
    """La contrainte se **compte**. 1 avant (Porcupine), 1 pendant, 1 après.

    L'état discriminant est construit : la pile d'éveil de SIMPLE possède un
    flux enregistré au départ, donc l'ordre « suspendre puis ouvrir » est
    réellement exercé et pas seulement décrit.
    """

    journal = RecordingJournal()
    simple = FakeSimpleWake()
    assert input_ownership.open_input_stream_count() == 1
    built, device, manual, _ = composition(tmp_path, journal)
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=simple, journal=journal),
        build=built.build, journal=journal,
    )
    await coordinator.apply(InteractionMode.PRESENTATION)
    assert coordinator.audio is not None
    assert input_ownership.open_input_stream_count() == 1
    assert coordinator.audio.physical_input_owners() == 1
    assert device.opens == 1
    assert simple.suspends == 1

    await coordinator.apply(InteractionMode.ASSISTANT)
    assert coordinator.audio is None
    assert simple.resumes == 1
    assert input_ownership.open_input_stream_count() == 1
    await coordinator.aclose()


async def test_une_entree_qui_trouve_un_second_micro_refuse_bruyamment(tmp_path) -> None:
    """« Une activation ne peut jamais ouvrir un second flux. »

    L'état est construit exprès : la suspension de SIMPLE **échoue**, donc le
    flux Porcupine reste enregistré quand la séance essaie d'ouvrir le sien.
    Le refus est attendu, la ligne d'erreur est attendue, et SIMPLE est repris.
    """

    journal = RecordingJournal()
    simple = FakeSimpleWake()
    simple.suspend_raises = RuntimeError("le périphérique ne se rend pas")
    built, device, _, _ = composition(tmp_path, journal)
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=simple, journal=journal),
        build=built.build, journal=journal, signals=SimpleNamespace(alert=lambda message: None),
    )
    await coordinator.apply(InteractionMode.PRESENTATION)

    assert coordinator.audio is None, "aucune séance ne doit s'établir sur deux micros"
    assert device.opens == 0, "le hub n'a pas ouvert de second flux"
    assert coordinator.entry_failures == 1
    assert "presentation_simple_suspend_failed" in journal.codes("error")
    assert any(code.startswith("presentation_audio") or "owner" in code
               for code in journal.codes("error")) or coordinator.last_failure_code
    assert simple.resumes == 1, "SIMPLE est repris : JARVIS reste adressable"

    # Et la séance ratée n'est **pas** retenue. Sans cette assertion, un
    # contrôleur qui garderait la pile morte passerait : `audio` rendrait déjà
    # `None` puisqu'elle n'a jamais démarré. Ce qui se perdrait est la
    # **reprise** — un second passage en PRESENTATION verrait `_stack` occupé
    # et ne rebâtirait rien, donc un micro momentanément pris condamnerait la
    # séance jusqu'au prochain redémarrage de Voice. Une mutation est passée
    # exactement par là.
    simple.suspend_raises = None
    await coordinator.apply(InteractionMode.ASSISTANT)
    await coordinator.apply(InteractionMode.PRESENTATION)
    assert coordinator.audio is not None, "la seconde tentative doit recomposer une séance"
    assert device.opens == 1, "et ouvrir le micro cette fois-ci"
    assert coordinator.entered == 1
    await coordinator.aclose()


async def test_une_seconde_entree_compose_une_pile_neuve(tmp_path) -> None:
    """« Une séance arrêtée ne redémarre jamais. »

    La Slice 05 rend `stop()` terminal ; sans pile neuve, le deuxième passage
    en PRESENTATION donnerait une Presentation sourde qui se déclare saine.
    Ce test fait l'aller-retour et lit le compte d'ouvertures du périphérique.
    """

    journal = RecordingJournal()
    devices: list[FakeCaptureDevice] = []

    def build(session_id: str):
        device = FakeCaptureDevice()
        devices.append(device)
        built, _, _, _ = composition(tmp_path, journal, device=device)
        return built.build(session_id)

    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake(), journal=journal),
        build=build, journal=journal,
    )
    await coordinator.apply(InteractionMode.PRESENTATION)
    first = coordinator.audio
    await coordinator.apply(InteractionMode.ASSISTANT)
    await coordinator.apply(InteractionMode.PRESENTATION)
    second = coordinator.audio

    assert first is not None and second is not None and first is not second
    assert second.started and not second.stopped
    assert [device.opens for device in devices] == [1, 1]
    assert input_ownership.open_input_stream_count() == 1
    await coordinator.aclose()


# ==========================================================================
# 3. Le déclencheur explicite arme le tour adressé
# ==========================================================================


async def test_la_touche_manuelle_arme_le_tour_adresse_et_rend_son_etiquette(tmp_path) -> None:
    """Le déclencheur typé sert deux consommateurs sans être dédoublé.

    `triggers()` et `detections()` sont deux vues d'**une** file : l'aiguillage
    consomme la vue typée, arme le service, puis rend l'étiquette que
    `PersistentVoiceRuntime` attend.
    """

    journal = RecordingJournal()
    stack, _, manual, _ = await started_stack(tmp_path, journal)
    router = PresentationWakeRouter(simple=FakeSimpleWake(owns_device=False), journal=journal)
    router.adopt(stack)
    detections = router.detections()

    manual.press()
    label = await asyncio.wait_for(anext(detections), 2.0)

    assert label == "f9"
    assert router.armed == 1
    assert router.arm_failures == 0
    assert stack.turns.armed is not None, "la fenêtre adressée est ouverte"
    await detections.aclose()
    await stack.stop("test")


async def test_l_horloge_du_service_est_celle_qui_estampille_les_declencheurs(tmp_path) -> None:
    """Le piège légué par la Slice 10 : deux horloges = télémétrie fausse ou blanche.

    ## Pourquoi la mesure seule ne prouvait rien

    Une première version affirmait seulement `admission_latency_ms is not None`.
    Une mutation l'a traversée : donner `time.perf_counter` à la lane et laisser
    `time.monotonic` au service produit, sur cette machine, deux nombres assez
    proches pour que la garde de dérive ne se déclenche pas — donc une latence
    **plausible et fausse**, exactement ce que la Slice 10 a corrigé en
    rendant `None` plutôt qu'un `502.0 ms` inventé. L'état discriminant n'était
    jamais construit.

    Ici il l'est : une horloge contrôlée traverse la composition, on la fait
    avancer de 50 ms **entre** l'appui et l'ouverture, et on lit exactement 50.
    Deux horloges différentes ne peuvent pas rendre ce nombre-là.
    """

    class StepClock:
        """Une horloge monotone que le test fait avancer, et lui seul."""

        def __init__(self) -> None:
            self.value = 1_000.0

        def __call__(self) -> float:
            return self.value

        def advance(self, seconds: float) -> None:
            self.value += seconds

    journal = RecordingJournal()
    clock = StepClock()
    built, _, manual, _ = composition(tmp_path, journal)
    built = dataclasses.replace(built, clock=clock)
    stack = built.build("pres-clock-1")
    await stack.start()
    try:
        router = PresentationWakeRouter(simple=FakeSimpleWake(owns_device=False))
        router.adopt(stack)
        detections = router.detections()
        manual.press()
        await asyncio.wait_for(anext(detections), 2.0)

        clock.advance(0.050)
        result = stack.turns.open("montre-moi ça", correlation_id="corr-1")

        assert result.applied, result.code
        assert result.plan.admission_latency_ms == pytest.approx(50.0), (
            "la latence doit être celle de l'horloge du déclencheur, au millimètre"
        )
        await detections.aclose()
    finally:
        await stack.stop("test")


async def test_une_seance_arretee_n_est_plus_annoncee_vivante(tmp_path) -> None:
    """« Une séance arrêtée ne peut jamais être servie au bridge. »

    L'état discriminant est construit : la séance est arrêtée **hors** du
    contrôleur, comme le ferait un arrêt d'urgence, sans que `_stack` soit
    remis à `None`. Sans cette lecture, `_shared_input_source()` rendrait le
    hub d'une séance morte et le tour s'ouvrirait sur un flux fermé.
    """

    journal = RecordingJournal()
    built, _, _, _ = composition(tmp_path, journal)
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake(), journal=journal),
        build=built.build, journal=journal,
    )
    await coordinator.apply(InteractionMode.PRESENTATION)
    stack = coordinator.stack
    assert stack is not None

    await stack.stop("device_lost")

    assert coordinator.stack is None
    assert coordinator.audio is None
    assert coordinator.turns is None
    await coordinator.aclose()


def test_un_abonne_du_mode_en_panne_n_empeche_pas_les_suivants() -> None:
    """« Un abonné qui lève ne peut ni annuler le mode ni faire taire les autres. »

    L'état discriminant : **deux** abonnés, le premier qui lève. Avec un seul,
    « la boucle continue » et « la boucle s'arrête » sont indiscernables, et
    c'est exactement par là qu'une mutation est passée.
    """

    journal = RecordingJournal()
    observer = InteractionModeObserver(journal=journal)
    seen: list[InteractionMode] = []

    def explodes(mode):
        raise RuntimeError("cet abonné refuse de lâcher la séance")

    observer.add_listener(explodes)
    observer.add_listener(seen.append)

    assert observer.adopt({"mode": "presentation", "revision": 1, "epoch": "life-1"})

    assert seen == [InteractionMode.PRESENTATION], "le second abonné doit être prévenu"
    assert observer.mode is InteractionMode.PRESENTATION, "le mode a bougé malgré la panne"
    assert "interaction_mode_listener_failed" in journal.codes("error")


# ==========================================================================
# 4. D04 sous charge ambiante lente - le montage déterministe
# ==========================================================================


async def test_une_voie_ambiante_saturee_ne_retarde_pas_le_declencheur_explicite(tmp_path) -> None:
    """D04 / D08, contre un arriéré **mesuré saturé**, pas supposé.

    Le montage est déterministe : le transcripteur ne rend jamais tant que le
    test ne le relâche pas, donc la file de segments monte jusqu'à sa borne et
    y reste. L'assertion sur la saturation vient **avant** l'appui : sans elle,
    ce test mesurerait une lane au repos et prouverait l'inverse de son nom.
    """

    journal = RecordingJournal()
    transcriber = NeverAnsweringTranscriber()
    stack, device, manual, _ = await started_stack(tmp_path, journal, transcriber=transcriber)
    try:
        for _ in range(8):
            await feed(device, speech(900))
            await feed(device, silence(900))
        await until(lambda: transcriber.calls >= 1, timeout=5.0)
        await until(lambda: stack.ambient.stats()["segments_pending"] >= 1, timeout=5.0)
        saturated = stack.stats()
        assert saturated["segments_pending"] >= 1, "l'arriéré doit exister avant d'être opposé"

        router = PresentationWakeRouter(simple=FakeSimpleWake(owns_device=False))
        router.adopt(stack)
        detections = router.detections()
        manual.press()
        await asyncio.wait_for(anext(detections), 2.0)
        result = stack.turns.open("montre-moi ça", correlation_id="corr-charge")

        assert result.applied, result.code
        assert result.plan.admission_latency_ms is not None
        assert result.plan.admission_latency_ms < 250.0, result.plan.admission_latency_ms
        assert stack.ambient.stats()["segments_pending"] >= 1, (
            "l'arriéré est toujours là après l'admission : rien ne l'a vidé pour faire passer le tour"
        )
        await detections.aclose()
    finally:
        transcriber.release.set()
        await stack.stop("test")


async def test_le_releve_de_diagnostics_nomme_les_quatre_mesures(tmp_path) -> None:
    """Retard de file, arriéré, travaux en vol, latence du déclencheur.

    SLICE.md les demande ; ce test lit les quatre dans un relevé pris sur une
    séance réellement chargée, et vérifie qu'ils atteignent aussi la trace.
    """

    journal = RecordingJournal()
    transcriber = NeverAnsweringTranscriber()
    stack, device, manual, _ = await started_stack(tmp_path, journal, transcriber=transcriber)
    try:
        await feed(device, speech(900))
        await feed(device, silence(900))
        await until(lambda: transcriber.calls >= 1, timeout=5.0)
        router = PresentationWakeRouter(simple=FakeSimpleWake(owns_device=False))
        router.adopt(stack)
        detections = router.detections()
        manual.press()
        await asyncio.wait_for(anext(detections), 2.0)
        await detections.aclose()

        payload = stack.emit_diagnostics()
        for name in ("segments_pending", "analysis_pending", "speculative_in_flight",
                     "trigger_latency_s", "physical_input_owners", "enrichment_lag_s"):
            assert name in payload, name
        assert payload["trigger_latency_s"] is not None
        assert payload["physical_input_owners"] == 1
        line = [entry for entry in journal.entries
                if entry["kind"] == "presentation.runtime.diagnostics"]
        assert line, "le relevé doit atteindre la trace, pas seulement l'appelant"
        assert line[-1]["data"]["trigger_latency_s"] is not None
    finally:
        transcriber.release.set()
        await stack.stop("test")


# ==========================================================================
# 5. Vie privée - rien de la salle dans un puits durable
# ==========================================================================


async def test_aucune_parole_de_la_salle_n_entre_dans_la_trace(tmp_path) -> None:
    """La phrase plantée est cherchée dans **toute** la trace, message compris.

    Trois portes d'entrée sont exercées en même temps : le texte ambiant, un
    énoncé d'affirmation, et le `reason` d'un verdict — le champ que la
    Slice 09 a explicitement réservé à une lecture en processus.
    """

    secret = "la marge nette atteint quarante-deux pour cent"
    journal = RecordingJournal()
    stack, device, _, _ = await started_stack(
        tmp_path, journal, transcriber=FakeTranscriber(secret),
    )
    try:
        await feed(device, speech(900))
        await feed(device, silence(900))
        await until(lambda: stack.store.snapshot.tail.entries, timeout=5.0)

        provenance = ObservationProvenance(
            utterance_id=stack.store.snapshot.tail.entries[-1].utterance_id,
            sequence=stack.store.assigned_sequence, observed_at=utc_now(),
            origin=UtteranceOrigin.AMBIENT,
        )
        stack.store.apply(PresentationObservation(
            observation_id="obs-claim", session_id=stack.session_id,
            record=PresentationClaim(
                claim_id="c-1", statement=secret, provenance=provenance,
                first_seen_at=provenance.observed_at, last_seen_at=provenance.observed_at,
            ),
        ))
        stack.store.apply(PresentationObservation(
            observation_id="obs-src", session_id=stack.session_id,
            record=PresentationSource(
                source_id="s-1", kind=ResourceKind.WEB_PAGE, reference="https://example.org/a",
                title="Rapport", retrieved_at=utc_now(),
            ),
        ))
        stack.attention.raise_from_assessments(
            [FactCheckAssessment(
                claim_id="c-1", verdict=ClaimStatus.CONTRADICTED, confidence=0.9,
                evidence=(AttentionEvidence(source_id="s-1", locator="https://example.org/a"),),
                reason=secret, searched=True,
            )],
            job_id="job-1", session_id=stack.session_id, may_verify=True,
        )

        assert secret in stack.store.snapshot.tail.entries[-1].text, (
            "la phrase doit bien être dans l'ensemble de travail : sinon ce test ne prouve rien"
        )
        assert secret not in journal.blob()
        for word in ("quarante-deux", "marge nette"):
            assert word not in journal.blob(), word
    finally:
        await stack.stop("test")


async def test_le_retrait_de_la_seance_ne_laisse_rien_de_la_salle(tmp_path) -> None:
    """« Rien de ce qui a été dit dans la salle ne survit à la séance. »"""

    journal = RecordingJournal()
    stack, device, _, _ = await started_stack(
        tmp_path, journal, transcriber=FakeTranscriber("une phrase de la salle"),
    )
    await feed(device, speech(900))
    await feed(device, silence(900))
    await until(lambda: stack.store.snapshot.tail.entries, timeout=5.0)
    assert stack.store.snapshot.session_id == stack.session_id

    await stack.stop("test")

    assert stack.store.snapshot.session_id is None
    assert stack.store.snapshot.tail.entries == ()
    assert stack.store.snapshot.working_set.topics == ()


async def test_aucun_audio_brut_n_atteint_l_ensemble_de_travail(tmp_path) -> None:
    """« L'audio n'entre jamais dans l'ensemble de travail. »

    Attaqué par le type, sur la porte réelle : `observe` reçoit des octets.
    """

    store = PresentationWorkingSetStore()
    store.bind_session("pres-x")
    result = store.observe("pres-x", "u-1", b"\x00\x01\x02\x03")
    assert not result.applied
    assert result.code == "presentation_tail_entry_invalid"
    assert store.snapshot.tail.entries == ()


# ==========================================================================
# 6. Reprise après un arrêt non propre
# ==========================================================================


async def test_les_objets_montes_par_une_vie_precedente_sont_repris_au_demarrage(tmp_path) -> None:
    """`retire()` ne couvre que l'arrêt ordonné. Celui-ci couvre l'autre.

    L'état discriminant est construit pour de vrai : un registre écrit par une
    vie précédente, que rien n'a effacé.
    """

    journal = RecordingJournal()
    ledger_path = tmp_path / "presentation-staged-objects.json"
    ledger_path.write_text(json.dumps({"object_ids": ["obj-a", "obj-b"]}), encoding="utf-8")
    scene = FakeSceneTools()
    stack, _, _, _ = await started_stack(tmp_path, journal, scene=scene)
    try:
        assert scene.archived == [["obj-a", "obj-b"]]
        assert stack.reclaimed == ("obj-a", "obj-b")
        assert not ledger_path.exists()
        assert "presentation_staged_reclaimed" in journal.codes("warning")
    finally:
        await stack.stop("test")


async def test_un_registre_abime_est_dit_et_ne_passe_pas_pour_vide(tmp_path) -> None:
    """« Rien à reprendre » et « on ne sait plus quoi reprendre » ne sont pas pareils."""

    journal = RecordingJournal()
    path = tmp_path / "staged.json"
    path.write_text("{ceci n'est pas du JSON", encoding="utf-8")
    ledger = StagedObjectLedger(path, journal=journal)
    assert ledger.load() == ()
    assert "presentation_ledger_corrupt" in journal.codes("error")


async def test_un_objet_monte_est_inscrit_puis_efface_quand_il_est_repris(tmp_path) -> None:
    """L'ordre est la garantie : inscrit après la scène, effacé après l'archivage."""

    scene = FakeSceneTools()
    path = tmp_path / "staged.json"
    from jarvis.runtime.presentation_staging import DisplaySceneStager

    ledger = StagedObjectLedger(path)
    stager = LedgeredSceneStager(DisplaySceneStager(scene), ledger)
    object_id = await stager.stage_hidden(category="preparation", title="t", summary="s")
    assert ledger.load() == (object_id,)
    await stager.discard([object_id])
    assert ledger.load() == ()


# ==========================================================================
# 7. Le `--tools` du profil de préparation
# ==========================================================================


def _argv(monkeypatch) -> list[list[str]]:
    """Capturer l'`argv` réellement construit, sans lancer de processus."""

    calls: list[list[str]] = []

    class FakeProcess:
        pid = 4242
        stdin = SimpleNamespace(write=lambda data: None, drain=None)
        stdout = SimpleNamespace(readline=None)
        stderr = SimpleNamespace(readline=None)

    async def fake_exec(*argv, **kwargs):  # noqa: ANN002, ANN003
        calls.append(list(argv))
        raise RuntimeError("argv capturé : aucun processus n'est lancé")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    return calls


async def test_le_profil_de_preparation_nomme_les_outils_accordes(tmp_path, monkeypatch) -> None:
    """La réponse au `--tools ""`, lue sur l'`argv`, pas sur une intention."""

    calls = _argv(monkeypatch)
    monkeypatch.setattr("jarvis.runtime.cli_catalog.resolve_command", lambda command: "C:/fake/claude.exe")
    agent = ClaudeLocalAgent(
        runtime_root=tmp_path, cwd=tmp_path, command="claude",
        execution_profile="presentation_preparation",
        allowed_tools=("Glob", "Grep", "Read", "WebSearch"),
    )
    with pytest.raises(RuntimeError):
        await agent.start(resume=False)

    argv = calls[-1]
    assert "--restricted" in argv
    assert argv[argv.index("--tools") + 1] == "Glob,Grep,Read,WebSearch"
    for hardening in ("--strict-mcp-config", "--safe-mode", "--no-chrome",
                      "--disable-slash-commands", "--no-session-persistence"):
        assert hardening in argv, hardening
    assert "--resume" not in argv


async def test_le_profil_speculatif_garde_ses_zero_outils(tmp_path, monkeypatch) -> None:
    """« Élargir ce profil changerait le comportement de ses consommateurs. »

    Le test qui rend cette phrase vérifiable : la voie historique part toujours
    avec `--tools ""`, quelles que soient les Slices ajoutées à côté.
    """

    calls = _argv(monkeypatch)
    monkeypatch.setattr("jarvis.runtime.cli_catalog.resolve_command", lambda command: "C:/fake/claude.exe")
    agent = ClaudeLocalAgent(
        runtime_root=tmp_path, cwd=tmp_path, command="claude",
        execution_profile="speculative_analysis",
    )
    with pytest.raises(RuntimeError):
        await agent.start(resume=False)

    argv = calls[-1]
    assert argv[argv.index("--tools") + 1] == ""


def test_un_outil_hors_liste_ne_peut_pas_atteindre_l_argv(tmp_path) -> None:
    """« Un nom hors de la table déclarée ne part jamais au CLI. »

    Refusé à la **construction**, donc avant qu'un processus existe.
    """

    for forbidden in ("Bash", "Edit", "Write", "memory_search", "scene_create_object"):
        with pytest.raises(ValueError):
            ClaudeLocalAgent(
                runtime_root=tmp_path, cwd=tmp_path,
                execution_profile="presentation_preparation", allowed_tools=(forbidden,),
            )


def test_seul_le_profil_de_preparation_peut_nommer_des_outils(tmp_path) -> None:
    """Un profil qui n'accorde rien ne doit pas pouvoir recevoir une liste."""

    with pytest.raises(ValueError):
        ClaudeLocalAgent(
            runtime_root=tmp_path, cwd=tmp_path,
            execution_profile="speculative_analysis", allowed_tools=("Read",),
        )


def test_aucun_outil_accorde_par_la_table_n_execute_de_code() -> None:
    """La liste du CLI est un sous-ensemble sûr de ce que la table accorde."""

    from jarvis.domain.presentation_speculative import CAPABILITY_TOOLS

    granted = {tool for tools in CAPABILITY_TOOLS.values() for tool in tools}
    assert CLI_GRANTABLE_TOOLS <= granted, "le CLI ne peut nommer que des outils accordés"
    for name in CLI_GRANTABLE_TOOLS:
        assert name not in {"Bash", "PowerShell", "Edit", "Write", "NotebookEdit"}


# ==========================================================================
# 8. L'exécutant : ce qui passe la frontière et ce qui est retenu
# ==========================================================================


def _request(*capabilities: SpeculativeCapability, text: str = "le bilan Q3 a doublé",
             origin: UtteranceOrigin = UtteranceOrigin.AMBIENT) -> SpeculativeRequest:
    return SpeculativeRequest(
        job_id="job-1", key=SpeculativeJobKey(topic_key="bilan"),
        priority=SpeculativePriority.P2_FACT_VERIFICATION,
        grant=SpeculativeGrant(tuple(capabilities), origin=origin),
        session_id="pres-1", utterance_id="u-001", text=text,
    )


class ScriptedAgent:
    """Un sous-agent qui rend le texte qu'on lui dicte, sans processus."""

    def __init__(self, answer: str, *, ok: bool = True) -> None:
        self.answer = answer
        self.ok = ok
        self.asked: list[str] = []
        self.closed = 0

    async def start(self, *, resume: bool = True) -> dict:
        return {"ok": True}

    async def ask(self, text: str, *, timeout_s: float = 180.0, **kwargs):  # noqa: ANN003
        self.asked.append(text)
        return {"ok": self.ok, "text": self.answer, "code": None if self.ok else "claude_timeout"}

    async def close_owned(self) -> bool:
        self.closed += 1
        return True


async def test_les_outils_mcp_accordes_sont_retenus_et_le_retrait_est_dit(tmp_path) -> None:
    """« Une capacité accordée mais inatteignable ne doit pas être un silence. »"""

    journal = RecordingJournal()
    seen: list[tuple[str, ...]] = []

    def agent_factory(tools):
        seen.append(tools)
        return ScriptedAgent('{"findings": [], "assessments": []}')

    runner = PresentationPreparationRunner(
        agent_factory=agent_factory, record_source=lambda kind, locator, title: None,
        journal=journal,
    )
    await runner.prepare(_request(SpeculativeCapability.RESEARCH_SEARCH))

    assert seen == [("WebSearch", "Grep", "Glob")] or set(seen[0]) == {"WebSearch", "Grep", "Glob"}
    assert "memory_search" not in seen[0]
    assert "presentation_preparation_tools_unavailable" in journal.codes("warning")

    # Une fois, pas une par travail. L'état discriminant est construit : un
    # **second** travail du même jeton. Sans lui, « dit une fois » et « dit à
    # chaque fois » sont indiscernables — un vrai trace de séance portait sept
    # avertissements identiques pour deux phrases entendues.
    await runner.prepare(_request(SpeculativeCapability.RESEARCH_SEARCH))
    assert journal.codes("warning").count("presentation_preparation_tools_unavailable") == 1
    assert runner.tools_withheld == 2, "le compte, lui, reste exact"


async def test_un_travail_sans_un_seul_outil_atteignable_ne_lance_aucun_processus(tmp_path) -> None:
    """`DISPLAY_PREPARATION` n'accorde que des outils MCP : rien à nommer."""

    journal = RecordingJournal()
    launched: list[object] = []
    runner = PresentationPreparationRunner(
        agent_factory=lambda tools: launched.append(tools) or ScriptedAgent("{}"),
        record_source=lambda kind, locator, title: None, journal=journal,
    )
    outcome = await runner.prepare(_request(
        SpeculativeCapability.DISPLAY_PREPARATION, origin=UtteranceOrigin.ADDRESSED,
    ))

    assert launched == []
    assert outcome.findings == () and outcome.assessments == ()
    assert "presentation.preparation.no_tool" in journal.kinds()


async def test_un_verdict_cite_une_source_que_le_magasin_connait(tmp_path) -> None:
    """La provenance reste **vérifiée**, pas déclarée.

    Sans producteur de `PresentationSource`, `decide_attention` refusait tout
    verdict en `attention_provenance_unknown` — un trou que rien n'atteignait
    parce que rien ne câblait la chaîne. Ce test parcourt la chaîne entière et
    lit le point d'attention rangé.
    """

    journal = RecordingJournal()
    store = PresentationWorkingSetStore(diagnostics=journal)
    store.bind_session("pres-1")
    store.observe("pres-1", "u-001", "le bilan Q3 a doublé", origin=UtteranceOrigin.AMBIENT)
    provenance = ObservationProvenance(
        utterance_id="u-001", sequence=store.assigned_sequence, observed_at=utc_now(),
        origin=UtteranceOrigin.AMBIENT,
    )
    store.apply(PresentationObservation(
        observation_id="obs-c", session_id="pres-1",
        record=PresentationClaim(
            claim_id="c-1", statement="le bilan Q3 a doublé", provenance=provenance,
            first_seen_at=provenance.observed_at, last_seen_at=provenance.observed_at,
        ),
    ))
    answer = json.dumps({
        "findings": [],
        "assessments": [{"id": "c-1", "verdict": "contradicted", "confidence": 0.9,
                         "source": "https://example.org/rapport",
                         "reason": "le rapport dit le contraire"}],
    })
    runner = PresentationPreparationRunner(
        agent_factory=lambda tools: ScriptedAgent(answer),
        record_source=source_recorder(store, session_id="pres-1"),
        claims_for=claims_reader(store),
        journal=journal,
    )
    outcome = await runner.prepare(_request(
        SpeculativeCapability.FACT_VERIFICATION, SpeculativeCapability.RESEARCH_SEARCH,
    ))

    assert len(outcome.assessments) == 1
    assessment = outcome.assessments[0]
    assert assessment.claim_id == "c-1"
    assert assessment.verdict is ClaimStatus.CONTRADICTED
    known = {source.record_id for source in store.snapshot.working_set.sources}
    assert assessment.evidence and assessment.evidence[0].source_id in known, (
        "la source citée doit exister dans l'ensemble de travail"
    )

    from jarvis.core.presentation_attention import PresentationAttentionService

    decisions = PresentationAttentionService(store=store, diagnostics=journal).raise_from_assessments(
        outcome.assessments, job_id="job-1", session_id="pres-1", may_verify=True,
    )
    assert decisions[0].refusal is None, decisions[0].code
    assert store.snapshot.working_set.attention


async def test_une_affirmation_inconnue_rendue_par_le_modele_est_refusee(tmp_path) -> None:
    """« Le modèle ne peut pas inventer un identifiant d'affirmation. »"""

    journal = RecordingJournal()
    store = PresentationWorkingSetStore()
    store.bind_session("pres-1")
    store.observe("pres-1", "u-001", "le bilan Q3 a doublé", origin=UtteranceOrigin.AMBIENT)
    provenance = ObservationProvenance(
        utterance_id="u-001", sequence=store.assigned_sequence, observed_at=utc_now(),
        origin=UtteranceOrigin.AMBIENT,
    )
    store.apply(PresentationObservation(
        observation_id="obs-c", session_id="pres-1",
        record=PresentationClaim(
            claim_id="c-1", statement="le bilan Q3 a doublé", provenance=provenance,
            first_seen_at=provenance.observed_at, last_seen_at=provenance.observed_at,
        ),
    ))
    answer = json.dumps({"assessments": [
        {"id": "c-INVENTEE", "verdict": "contradicted", "confidence": 1.0,
         "source": "https://example.org/x"},
    ]})
    runner = PresentationPreparationRunner(
        agent_factory=lambda tools: ScriptedAgent(answer),
        record_source=source_recorder(store, session_id="pres-1"),
        claims_for=claims_reader(store), journal=journal,
    )
    outcome = await runner.prepare(_request(
        SpeculativeCapability.FACT_VERIFICATION, SpeculativeCapability.RESEARCH_SEARCH,
    ))
    assert outcome.assessments == ()
    assert runner.assessments_dropped == 1


async def test_une_reponse_illisible_n_est_pas_une_panne(tmp_path) -> None:
    """Le modèle bavarde : cela rend le vide, compté, jamais une exception."""

    journal = RecordingJournal()
    runner = PresentationPreparationRunner(
        agent_factory=lambda tools: ScriptedAgent("je n'ai pas compris la question"),
        record_source=lambda kind, locator, title: None, journal=journal,
    )
    outcome = await runner.prepare(_request(SpeculativeCapability.RESEARCH_SEARCH))
    assert outcome.findings == () and outcome.assessments == ()
    assert runner.unparsable == 1


async def test_le_sous_agent_est_toujours_ferme(tmp_path) -> None:
    """« Un sous-agent laissé ouvert est un processus CLI de plus. »"""

    agents: list[ScriptedAgent] = []

    def factory(tools):
        agent = ScriptedAgent("pas de JSON du tout", ok=False)
        agents.append(agent)
        return agent

    runner = PresentationPreparationRunner(
        agent_factory=factory, record_source=lambda kind, locator, title: None,
    )
    await runner.prepare(_request(SpeculativeCapability.RESEARCH_SEARCH))
    assert agents and agents[0].closed == 1


async def test_une_decouverte_ne_peut_pas_se_declarer_deja_montee(tmp_path) -> None:
    """« Le montage est une décision du service, jamais une demande de l'exécutant. »"""

    answer = json.dumps({"findings": [
        {"kind": "url", "locator": "https://example.org/a", "title": "A", "stage_hidden": True},
    ]})
    runner = PresentationPreparationRunner(
        agent_factory=lambda tools: ScriptedAgent(answer),
        record_source=lambda kind, locator, title: None,
    )
    outcome = await runner.prepare(_request(SpeculativeCapability.RESEARCH_SEARCH))
    assert len(outcome.findings) == 1
    assert outcome.findings[0].stage_hidden is False


# ==========================================================================
# 9. Le tour adressé, de bout en bout, dans l'ordonnanceur
# ==========================================================================


def _queued(scheduler) -> list:
    """Les paroles que l'ordonnanceur a **acceptées**, en file ou différées.

    Différer n'est pas refuser : un ordonnanceur nu n'a pas d'admission de
    sortie (le bridge la lui donne en production), donc la question attend. Ce
    qui est prouvé ici est qu'elle est entrée — c'est-à-dire que la porte de la
    Slice 07 ne l'a pas retenue.
    """

    return list(scheduler._pending) + list(scheduler._deferred.values())


def _scheduler(turns, *, mode=InteractionMode.PRESENTATION, journal=None, correlation="corr-1"):
    """Un ordonnanceur câblé comme `voice_v2` le fait, avec la Slice 10 branchée."""

    from jarvis.runtime.speech_scheduler import SpeechScheduler

    observer = InteractionModeObserver()
    observer.adopt({"mode": mode.value, "revision": 1, "epoch": "life-1"})
    scheduler = SpeechScheduler(
        core=SimpleNamespace(), conversation_id=CONVERSATION,
        session=SimpleNamespace(), journal=journal, interaction_mode=observer,
        presentation_turns=lambda: turns,
    )
    # L'autorité d'intention de Core, telle qu'un ordonnanceur vivant la reçoit
    # par `/v1/events`. Sans elle, toute parole est différée en
    # `unknown_source` — donc un test qui l'omettrait mesurerait la file, pas
    # la politique.
    scheduler.update_speech_context(speech_context(CONVERSATION, correlation))
    return scheduler


async def test_le_tour_adresse_decide_la_situation_et_la_porte_ne_reclasse_pas(tmp_path) -> None:
    """« Une décision, une vérité. »

    L'état discriminant : le tour adressé rend une situation que le
    classificateur de la porte ne choisirait **pas** pour ce texte. Sans le
    passage explicite, la porte reclasserait et les deux différeraient.
    """

    journal = RecordingJournal()
    plan = SimpleNamespace(
        correlation_id="corr-1", situation=PresentationSituation.VISUAL_COMMAND,
    )
    turns = SimpleNamespace(
        open=lambda text, *, correlation_id: SimpleNamespace(applied=True, plan=plan, code="ok"),
        deliver=None,
    )

    async def deliver(plan):
        return SimpleNamespace(action=AddressedTurnAction.ASK_BRAIN, delivered=True,
                               code="ok", resource_id="", speaks=False, speech_kind=None)

    turns.deliver = deliver
    turns.note_visible_reaction = lambda correlation_id: None
    turns.note_audible_reaction = lambda correlation_id: None
    concluded: list[str] = []
    turns.conclude = concluded.append

    scheduler = _scheduler(turns, journal=journal)
    scheduler.note_addressed_turn("quel est le total ?", correlation_id="corr-1")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    outcome = scheduler.presentation.outcome("corr-1")
    assert outcome is not None
    assert outcome.situation is PresentationSituation.VISUAL_COMMAND, (
        "la situation vient du tour adressé, pas d'un second classement"
    )
    assert outcome.evidence == "addressed_turn"
    await until(lambda: concluded == ["corr-1"], timeout=2.0)


async def test_une_clarification_est_dite_et_une_seule_nature_est_possible(tmp_path) -> None:
    """La seule parole que cette voie produise, et son plafond.

    La Slice 07 n'admet `QUESTION` sous `VISUAL_COMMAND` que comme nature de
    **sûreté** ; ce site écrit le littéral et refuse tout autre verdict.
    """

    journal = RecordingJournal()
    plan = SimpleNamespace(correlation_id="corr-2", situation=PresentationSituation.VISUAL_COMMAND)

    async def deliver(plan):
        return SimpleNamespace(action=AddressedTurnAction.CLARIFY, delivered=True,
                               code="addressed_clarification", resource_id="",
                               speaks=True, speech_kind=SpeechKind.QUESTION)

    turns = SimpleNamespace(
        open=lambda text, *, correlation_id: SimpleNamespace(applied=True, plan=plan, code="ok"),
        deliver=deliver, note_visible_reaction=lambda correlation_id: None,
        note_audible_reaction=lambda correlation_id: None, conclude=lambda correlation_id: None,
    )
    scheduler = _scheduler(turns, journal=journal, correlation="corr-2")
    scheduler.note_addressed_turn("montre-moi ça", correlation_id="corr-2")
    await until(lambda: _queued(scheduler), timeout=2.0)

    request = _queued(scheduler)[0]
    assert request.kind is SpeechKind.QUESTION
    assert request.correlation_id == "corr-2"
    assert request.source is not None, "sans source, une parole est différée pour toujours"
    assert request.text
    assert "presentation_speech_withheld" not in journal.codes(), (
        "la matrice admet QUESTION sous VISUAL_COMMAND : c'est la nature de sûreté de la Slice 07"
    )


async def test_un_verdict_d_une_autre_nature_ne_fait_rien_dire(tmp_path) -> None:
    """« Ce site ne peut produire qu'une question. »

    L'état est construit : la Slice 10 rend `speaks=True` avec une nature que
    la matrice n'admet pas sous ce plafond. Rien n'est mis en file, et la ligne
    le dit.
    """

    journal = RecordingJournal()
    plan = SimpleNamespace(correlation_id="corr-3", situation=PresentationSituation.VISUAL_COMMAND)

    async def deliver(plan):
        return SimpleNamespace(action=AddressedTurnAction.CLARIFY, delivered=True, code="x",
                               resource_id="", speaks=True, speech_kind=SpeechKind.RESULT)

    turns = SimpleNamespace(
        open=lambda text, *, correlation_id: SimpleNamespace(applied=True, plan=plan, code="ok"),
        deliver=deliver, note_visible_reaction=lambda correlation_id: None,
        note_audible_reaction=lambda correlation_id: None, conclude=lambda correlation_id: None,
    )
    scheduler = _scheduler(turns, journal=journal, correlation="corr-3")
    scheduler.note_addressed_turn("montre-moi ça", correlation_id="corr-3")
    await until(lambda: "presentation_clarification_kind_unexpected" in journal.codes("error"),
                timeout=2.0)
    assert _queued(scheduler) == []


async def test_sans_seance_l_ordonnanceur_se_comporte_comme_avant(tmp_path) -> None:
    """D14 dans l'ordonnanceur : `presentation_turns` rend `None`, rien ne change."""

    journal = RecordingJournal()
    scheduler = _scheduler(None, mode=InteractionMode.ASSISTANT, journal=journal)
    scheduler.note_addressed_turn("quel est le total ?", correlation_id="corr-4")
    await asyncio.sleep(0)
    assert scheduler.presentation.outcome("corr-4") is None
    assert _queued(scheduler) == []
    assert scheduler._addressed_tasks == set()


async def test_un_tour_adresse_en_panne_ne_fait_pas_taire_jarvis(tmp_path) -> None:
    """« Un tour adressé en panne n'avale pas la parole. »"""

    journal = RecordingJournal()

    def boom(text, *, correlation_id):
        raise RuntimeError("le service est cassé")

    scheduler = _scheduler(SimpleNamespace(open=boom), journal=journal)
    scheduler.note_addressed_turn("montre-moi le bilan", correlation_id="corr-5")
    await asyncio.sleep(0)

    assert "presentation_turn_open_failed" in journal.codes("error")
    outcome = scheduler.presentation.outcome("corr-5")
    assert outcome is not None, "la porte a quand même classé le tour"


# ==========================================================================
# 10. La composition de production, et la matrice d'architectures
# ==========================================================================


def _runtime(monkeypatch, *, architecture, voice_arch, mode, coordinator):
    """Un `PersistentVoiceRuntime` composé comme `jarvis/app.py` le compose.

    La pré-condition est celle de la production, lue sur la propriété du
    runtime : c'est elle qui décide si une architecture peut servir un tour
    adressé, et la câbler ici est ce qui rend la matrice discriminante.
    """

    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime

    async def factory(context):
        raise AssertionError("aucune session temps réel n'est ouverte dans ce test")

    runtime = PersistentVoiceRuntime(
        wakeword=coordinator.router, core=SimpleNamespace(), realtime_factory=factory,
        auto_turn=True, voice_arch=voice_arch, conversation_architecture=architecture,
        presentation=coordinator,
    )
    coordinator._precondition = lambda: None if runtime.continuous else UNSUPPORTED_ARCH
    runtime.interaction_mode.adopt({"mode": mode.value, "revision": 1, "epoch": "life-1"})
    return runtime


UNSUPPORTED_ARCH = (
    "PRESENTATION demande une session vocale continue : sur « un tour par appui » "
    "aucun tour adressé ne peut s'ouvrir."
)

#: `label, typed architecture, voice_arch, sert-elle un tour adressé ?`
#:
#: La dernière colonne est ce qui manquait. Les cinq lignes différaient
#: auparavant par un champ qu'aucun chemin conduit ne lisait — dix tests qui
#: étaient deux tests joués cinq fois. `continuous` est le seul fait qui
#: décide : sans lui pas de `SpeechScheduler`, donc `on_addressed_turn=None`,
#: donc aucun tour adressé ne s'ouvre jamais.
ARCHITECTURES = [
    ("legacy", None, "legacy", False),
    ("continuous_brain", None, "continuous_brain", True),
    ("simple", "SIMPLE", "legacy", True),
    ("front_brain", "FRONT_BRAIN", "legacy", True),
    ("duplex", "DUPLEX", "legacy", True),
]


def _build_runtime(tmp_path, monkeypatch, journal, typed, legacy, mode):
    from jarvis.domain.voice_architecture import VoiceArchitectureId
    from jarvis.v2_config import VoiceArchitecture

    built, device, _, _ = composition(tmp_path, journal)
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake(owns_device=False), journal=journal),
        build=built.build, journal=journal,
    )
    runtime = _runtime(
        monkeypatch, architecture=getattr(VoiceArchitectureId, typed) if typed else None,
        voice_arch=VoiceArchitecture(legacy), mode=mode, coordinator=coordinator,
    )
    return runtime, coordinator, device


@pytest.mark.parametrize("label,typed,legacy,addressable", ARCHITECTURES)
async def test_la_matrice_des_architectures(
    tmp_path, monkeypatch, label, typed, legacy, addressable,
) -> None:
    """La matrice, et cette fois elle discrimine.

    ## Pourquoi la première version ne prouvait rien

    Elle conduisait `presentation_session()`, `_shared_input_source()` et
    `presentation_turns()` — dont aucun ne lit `voice_arch` ni
    `conversation_architecture`. Les cinq lignes passaient donc le même chemin
    avec un champ ignoré, et une mutation posant `on_addressed_turn=None`
    n'était attrapée que par un test **hérité** de la Slice 07.

    Ce qui décide vraiment est `PersistentVoiceRuntime.continuous` : sans lui
    aucun `SpeechScheduler` n'est construit, donc le bridge reçoit
    `on_addressed_turn=None` et le tour adressé ne s'ouvre jamais. La matrice
    l'affirme ligne par ligne, et vérifie que PRESENTATION **refuse le micro**
    exactement là où elle ne pourrait pas être adressée.
    """

    journal = RecordingJournal()
    runtime, coordinator, device = _build_runtime(
        tmp_path, monkeypatch, journal, typed, legacy, InteractionMode.PRESENTATION,
    )
    try:
        assert runtime.continuous is addressable, label
        await coordinator.apply(InteractionMode.PRESENTATION)

        if addressable:
            assert runtime.presentation_session() is not None, label
            assert runtime._shared_input_source() is not None, label
            assert runtime.presentation_turns() is not None, label
            assert device.opens == 1, label
        else:
            # Le point du blocage : le micro de la salle n'est **pas** pris.
            assert runtime.presentation_session() is None, label
            assert runtime._shared_input_source() is None, label
            assert device.opens == 0, label
            assert coordinator.last_failure_code == "presentation_architecture_unsupported"
            assert "presentation_architecture_unsupported" in journal.codes("error")
    finally:
        await coordinator.aclose()


@pytest.mark.parametrize("label,typed,legacy,addressable", ARCHITECTURES)
async def test_aucune_architecture_ne_partage_la_capture_hors_presentation(
    tmp_path, monkeypatch, label, typed, legacy, addressable,
) -> None:
    """D14 sur la matrice : en SIMPLE, le bridge ouvre son flux comme avant."""

    journal = RecordingJournal()
    runtime, coordinator, device = _build_runtime(
        tmp_path, monkeypatch, journal, typed, legacy, InteractionMode.ASSISTANT,
    )
    try:
        await coordinator.apply(InteractionMode.ASSISTANT)
        assert runtime._shared_input_source() is None, label
        assert device.opens == 0, label
    finally:
        await coordinator.aclose()


async def test_le_refus_d_architecture_ne_touche_jamais_la_pile_d_eveil(tmp_path, monkeypatch) -> None:
    """« Une architecture refusée laisse JARVIS exactement ce qu'il était. »

    L'état discriminant : une pile d'éveil de SIMPLE qui **possède** un flux.
    Si le refus arrivait après la suspension, le mot d'éveil serait perdu pour
    rien — un refus qui casse ce qu'il protège.
    """

    from jarvis.v2_config import VoiceArchitecture

    journal = RecordingJournal()
    built, device, _, _ = composition(tmp_path, journal)
    simple = FakeSimpleWake()
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=simple, journal=journal),
        build=built.build, journal=journal,
    )
    _runtime(monkeypatch, architecture=None, voice_arch=VoiceArchitecture.LEGACY,
             mode=InteractionMode.PRESENTATION, coordinator=coordinator)
    try:
        await coordinator.apply(InteractionMode.PRESENTATION)

        assert simple.suspends == 0, "la pile d'éveil de SIMPLE n'est pas touchée"
        assert input_ownership.open_input_stream_count() == 1, "son flux est toujours là"
        assert device.opens == 0
        assert coordinator.entry_failures == 1
    finally:
        await coordinator.aclose()


async def test_une_precondition_en_panne_ne_prend_pas_le_micro(tmp_path) -> None:
    """« Une pré-condition qu'on ne sait pas évaluer ne vaut pas un oui. »"""

    journal = RecordingJournal()
    built, device, _, _ = composition(tmp_path, journal)

    def explodes():
        raise RuntimeError("impossible de lire l'architecture")

    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake(), journal=journal),
        build=built.build, journal=journal, precondition=explodes,
    )
    await coordinator.apply(InteractionMode.PRESENTATION)

    assert coordinator.audio is None
    assert device.opens == 0
    assert "presentation_architecture_unsupported" in journal.codes("error")
    await coordinator.aclose()


async def test_le_changement_de_mode_ouvre_et_ferme_la_seance_sans_redemarrer_voice(
    tmp_path, monkeypatch,
) -> None:
    """D15 : le mode voyage par évènement, et il ouvre la séance à chaud.

    Le chemin réel : `InteractionModeObserver.adopt` → abonné → contrôleur.
    """

    from jarvis.v2_config import VoiceArchitecture

    journal = RecordingJournal()
    built, device, _, _ = composition(tmp_path, journal)
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake(), journal=journal),
        build=built.build, journal=journal,
    )
    runtime = _runtime(
        monkeypatch, architecture=None, voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN,
        mode=InteractionMode.ASSISTANT, coordinator=coordinator,
    )
    try:
        assert runtime.presentation_session() is None
        runtime.interaction_mode.adopt({"mode": "presentation", "revision": 2, "epoch": "life-1"})
        await until(lambda: coordinator.audio is not None, timeout=3.0)
        assert device.opens == 1

        runtime.interaction_mode.adopt({"mode": "assistant", "revision": 3, "epoch": "life-1"})
        await until(lambda: coordinator.audio is None, timeout=3.0)
        assert input_ownership.open_input_stream_count() == 1, "le micro est rendu à SIMPLE"
    finally:
        await coordinator.aclose()


# ==========================================================================
# 11. Le composition root de production
# ==========================================================================


async def _startup(tmp_path, monkeypatch, **overrides):
    """Monter `jarvis/app.py:_run_voice_v2` jusqu'au runtime, sans audio ni réseau.

    Le harnais est celui de `test_app.py`, réemployé plutôt que recopié : il
    est déjà ce que le composition root de production traverse, et une seconde
    copie divergerait le jour où l'un des deux bouge.
    """

    from jarvis import app
    from tests.unit.test_app import _StopVoice, _voice_startup

    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides=dict(overrides))
    with pytest.raises(_StopVoice):
        await app._run_voice_v2()
    return captured


async def test_le_composition_root_donne_l_aiguillage_et_la_composition_au_runtime(
    tmp_path, monkeypatch,
) -> None:
    """Le câblage de production, lu sur ce que le runtime **reçoit**.

    C'est le test qu'une régression de `jarvis/app.py` doit faire tomber : la
    Slice 05 avait livré `presentation_audio=` et personne ne le passait, ce
    qu'aucun test ne disait parce qu'aucun ne regardait le composition root.
    """

    from jarvis.adapters.wakeword_composite import CompositeWakeWordBackend

    captured = await _startup(tmp_path, monkeypatch, voice_arch="continuous_brain")

    router = captured["wakeword"]
    assert isinstance(router, PresentationWakeRouter)
    assert isinstance(router.simple, CompositeWakeWordBackend), (
        "l'aiguillage doit envelopper la pile d'éveil de SIMPLE, pas la remplacer"
    )
    coordinator = captured["presentation"]
    assert isinstance(coordinator, PresentationCoordinator)
    assert coordinator.router is router


async def test_le_composition_root_n_ouvre_aucune_seance_au_demarrage(tmp_path, monkeypatch) -> None:
    """D14 au démarrage : construire la composition ne compose aucune séance.

    Le défaut est SIMPLE ; un micro ouvert ici serait ouvert pour tout le monde,
    y compris ceux qui n'emploieront jamais PRESENTATION.
    """

    captured = await _startup(tmp_path, monkeypatch, voice_arch="continuous_brain")

    coordinator = captured["presentation"]
    assert coordinator.audio is None
    assert coordinator.turns is None
    assert coordinator.entered == 0
    assert input_ownership.open_input_stream_count() == 0


# ==========================================================================
# 12. Dégradations : ce qui manque se dit, et ne s'arrête jamais en silence
# ==========================================================================


async def test_sans_scene_la_seance_s_ouvre_quand_meme(tmp_path) -> None:
    """Scène éteinte : PRESENTATION écoute, prépare, et ne monte rien.

    `SLICE.md` demande la dégradation « Scene unavailable ». Elle est héritée
    plutôt que construite — la Slice 08 compte déjà `stage_unavailable`, la
    Slice 10 retombe déjà de `SHOW_PREPARED` sur `REFRESH` — mais la **branche
    de composition** est neuve, et c'est elle qui est exercée ici.
    """

    journal = RecordingJournal()
    built, device, _, _ = composition(tmp_path, journal)
    built = dataclasses.replace(built, scene_tools_factory=None)
    stack = built.build("pres-sans-scene")
    await stack.start()
    try:
        assert stack.stager is None
        assert stack.reclaimed == ()
        assert stack.audio.physical_input_owners() == 1
        assert stack.ambient.started
    finally:
        await stack.stop("test")


async def test_sans_cle_d_eveil_la_touche_manuelle_reste_la_seule_voie(tmp_path) -> None:
    """Mot d'éveil indisponible : JARVIS reste adressable, et le dit en données.

    `live_sources` est la lecture qui le rend constatable plutôt que déduit
    d'une absence de clé dans un fichier de réglages.
    """

    journal = RecordingJournal()
    built, _, _, _ = composition(tmp_path, journal)
    assert built.wake_access_key == "", "le montage de ce test n'a pas de clé"
    stack = built.build("pres-sans-eveil")
    await stack.start()
    try:
        assert stack.audio.wake is None
        assert stack.audio.lane.sources == (ExplicitAddressSource.MANUAL_KEY,)
    finally:
        await stack.stop("test")


async def test_sans_transcription_la_voie_ambiante_devient_sourde_et_le_dit(tmp_path) -> None:
    """Le blocage nommé des piles non-OpenAI, rendu **lisible**.

    La lane est construite quand même, avec un transcripteur qui lève. « La
    voie ambiante est sourde parce qu'il n'y a pas de transcription » se lit
    dans `stats()` et dans la trace ; « il n'y a pas de voie ambiante » ne se
    lirait nulle part — et c'est cette différence-là qui fait qu'un opérateur
    sait quoi chercher.
    """

    journal = RecordingJournal()
    built, device, _, _ = composition(tmp_path, journal)
    built = dataclasses.replace(built, transcriber=None)
    stack = built.build("pres-sans-transcription")
    await stack.start()
    try:
        for _ in range(4):
            await feed(device, speech(900))
            await feed(device, silence(900))
        await until(lambda: stack.ambient.stats()["deaf"]
                    or stack.ambient.stats()["degraded"], timeout=10.0)

        reading = stack.stats()
        assert reading["ambient_deaf"] or reading["ambient_degraded"], (
            "la surdité doit apparaître dans le relevé que l'opérateur lit"
        )
        assert any("transcription" in code for code in journal.codes("error")), journal.codes("error")
        # Et l'adresse explicite, elle, n'est pas touchée : c'est tout le sujet.
        assert stack.audio.started and stack.audio.physical_input_owners() == 1
    finally:
        await stack.stop("test")


async def test_sans_executant_aucune_preparation_n_est_lancee_et_c_est_dit(tmp_path) -> None:
    """Le blocage nommé des CLI autres que Claude.

    L'état discriminant est construit : un travail spéculatif est réellement
    admis, donc l'exécutant absent est **atteint**. Un test qui n'admettrait
    aucun travail passerait quelle que soit l'implantation.
    """

    journal = RecordingJournal()
    built, device, _, _ = composition(tmp_path, journal)
    assert built.agent_factory is None, "le montage de ce test n'a pas d'exécutant"
    stack = built.build("pres-sans-executant")
    await stack.start()
    try:
        await feed(device, speech(900))
        await feed(device, silence(900))
        await until(lambda: "presentation_runner_absent" in journal.codes("warning"),
                    timeout=10.0)
        assert stack.speculative.stats()["admitted"] >= 1, (
            "sans travail admis, ce test ne prouverait rien"
        )
    finally:
        await stack.stop("test")


# ==========================================================================
# 13. La carte du Control Center, atteinte depuis la trace réelle
# ==========================================================================


async def test_une_contradiction_atteint_le_registre_d_arriere_plan_du_control_center(
    tmp_path,
) -> None:
    """« Slice 11 doit câbler le juge » — et voici la preuve qu'il est atteint.

    La Slice 09 a livré la carte et le signal, et n'a pas pu les atteindre :
    rien ne construisait le juge ni la voie qui le nourrit. Le chemin réel n'est
    pas un appel, c'est un **fichier** : le juge pose une ligne dans
    `runtime/trace.jsonl`, et le registre d'arrière-plan du Control Center la
    classe en `attention`.

    Ce test parcourt ce chemin-là en entier, avec le vrai journal, la vraie
    ligne et le vrai registre — et vérifie au passage que le condensé qui part
    vers la page ne porte **aucune** parole de la salle.
    """

    from jarvis.core.presentation_attention import PresentationAttentionService
    from jarvis.runtime.background_events import BackgroundEventLedger, TraceFollower
    from jarvis.runtime.journal import RuntimeJournal

    secret = "la marge nette atteint quarante-deux pour cent"
    journal = RuntimeJournal(tmp_path)
    store = PresentationWorkingSetStore(diagnostics=journal)
    store.bind_session("pres-card")
    store.observe("pres-card", "u-001", secret, origin=UtteranceOrigin.AMBIENT)
    provenance = ObservationProvenance(
        utterance_id="u-001", sequence=store.assigned_sequence, observed_at=utc_now(),
        origin=UtteranceOrigin.AMBIENT,
    )
    store.apply(PresentationObservation(
        observation_id="obs-c", session_id="pres-card",
        record=PresentationClaim(
            claim_id="c-1", statement=secret, provenance=provenance,
            first_seen_at=provenance.observed_at, last_seen_at=provenance.observed_at,
        ),
    ))
    source_id = source_recorder(store, session_id="pres-card")(
        ResourceKind.WEB_PAGE, "https://example.org/rapport", "Rapport officiel",
    )
    assert source_id, "sans source rangée ce test ne prouverait rien"

    decisions = PresentationAttentionService(store=store, diagnostics=journal).raise_from_assessments(
        [FactCheckAssessment(
            claim_id="c-1", verdict=ClaimStatus.CONTRADICTED, confidence=0.92,
            evidence=(AttentionEvidence(source_id=source_id,
                                        locator="https://example.org/rapport",
                                        title="Rapport officiel"),),
            reason=secret, searched=True,
        )],
        job_id="job-card", session_id="pres-card", may_verify=True,
    )
    assert decisions[0].refusal is None, decisions[0].code

    ledger = BackgroundEventLedger()
    for entry in TraceFollower(journal.trace_path, offset=0).poll():
        ledger.observe(entry.get("kind", ""), entry.get("message", ""),
                       level=entry.get("level", "info"), data=entry.get("data") or {},
                       ts=entry.get("ts", ""))

    assert ledger.counts().get("attention") == 1, ledger.counts()
    digest = ledger.attention_digest()
    assert len(digest) == 1
    assert digest[0]["attention"]["category"] == "contradiction"
    assert digest[0]["attention"]["evidence"][0]["source_id"] == source_id
    assert secret not in json.dumps(digest, ensure_ascii=False), (
        "le condensé qui part vers la page ne porte jamais ce qui a été dit"
    )
    assert secret not in journal.trace_path.read_text(encoding="utf-8")


async def test_un_arret_qui_se_passe_mal_rend_quand_meme_le_micro_de_la_salle(tmp_path) -> None:
    """« Le micro de la salle ne peut jamais survivre à l'arrêt de Voice. »

    L'état discriminant est celui qui compte : `close()` a deux sorties
    anticipées — fournisseur non confirmé, nettoyage audio en vol — et les deux
    rendent la main **avant** de fermer la pile d'éveil. Ce test construit la
    seconde, celle qu'un arrêt raté produit vraiment, et vérifie que la séance
    a été rendue quand même. Avec la fermeture placée après `mute()`, le hub
    resterait ouvert précisément ici.
    """

    from jarvis.v2_config import VoiceArchitecture

    journal = RecordingJournal()
    built, device, _, _ = composition(tmp_path, journal)
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake(), journal=journal),
        build=built.build, journal=journal,
    )
    runtime = _runtime(
        None, architecture=None, voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN,
        mode=InteractionMode.PRESENTATION, coordinator=coordinator,
    )
    await coordinator.apply(InteractionMode.PRESENTATION)
    assert coordinator.audio is not None
    assert input_ownership.open_input_stream_count() == 1

    # Un arrêt qui se passe mal : un nettoyage audio que le système n'a pas
    # encore confirmé. `close()` sortira par là.
    runtime._pending_audio = object()
    runtime.core = SimpleNamespace(close=_noop)
    await runtime.close()

    assert coordinator.audio is None, "la séance doit être rendue malgré la sortie anticipée"
    assert input_ownership.open_input_stream_count() == 1, (
        "seul le flux de SIMPLE reste : le hub a rendu le sien"
    )


async def _noop() -> None:
    return None


async def test_le_vrai_sous_agent_ne_recopie_pas_la_parole_de_la_salle(tmp_path) -> None:
    """« La parole n'entre jamais dans un puits durable » — sur le **vrai** agent.

    ## Pourquoi ce test existe en plus de celui d'à côté

    `test_aucune_parole_de_la_salle_n_entre_dans_la_trace` cherche la phrase
    dans toute la trace et passait — contre un `ScriptedAgent` qui n'a pas de
    journal du tout. Il atteignait le code de la garde et jamais l'état pour
    lequel la garde existe : dixième fois que ce motif frappe cette tâche, et
    le cas le plus net, parce que le double choisi ne pouvait pas échouer.

    Ici le `ClaudeLocalAgent` de production est conduit, avec un vrai
    `RuntimeJournal`, jusqu'à la ligne qui écrivait la phrase :
    `journal.emit("agent.input", visible_text)`. Aucun processus n'est lancé —
    seule l'écriture sur `stdin` est simulée, et c'est après elle que l'écho
    partait.
    """

    from jarvis.runtime.claude_local import ClaudeLocalAgent
    from jarvis.runtime.journal import RuntimeJournal

    class _Stdin:
        def write(self, data) -> None: ...

        async def drain(self) -> None: ...

    class _Process:
        returncode = None
        pid = 4242
        stdin = _Stdin()

    secret = "la marge nette atteint quarante-deux pour cent"
    agent = ClaudeLocalAgent(
        runtime_root=tmp_path, cwd=tmp_path,
        execution_profile="presentation_preparation", allowed_tools=("Read",),
    )
    agent.process = _Process()

    # Exactement le message que `PresentationPreparationRunner._message` bâtit.
    await agent.send(f"Job nature: 2.\nHeard in the room: {secret}")

    trace = RuntimeJournal(tmp_path).trace_path.read_text(encoding="utf-8")
    assert "agent.input" in trace, (
        "le tour doit bien être journalisé : sinon ce test ne prouve rien"
    )
    assert secret not in trace
    for fragment in ("marge nette", "quarante-deux", "Heard in the room"):
        assert fragment not in trace, fragment
    assert "restricted_input_withheld" in trace


async def test_le_profil_ordinaire_continue_de_recopier_sa_question(tmp_path) -> None:
    """Et la console de debug garde son écho. La retenue vise **un** profil.

    L'état discriminant de l'autre sens : sans ce test, supprimer l'écho partout
    passerait aussi, et la console de debug n'afficherait plus que des réponses
    sans les questions — ce que le commentaire de `send()` dit exister pour
    empêcher.
    """

    from jarvis.runtime.claude_local import ClaudeLocalAgent
    from jarvis.runtime.journal import RuntimeJournal

    class _Stdin:
        def write(self, data) -> None: ...

        async def drain(self) -> None: ...

    class _Process:
        returncode = None
        pid = 4242
        stdin = _Stdin()

    agent = ClaudeLocalAgent(
        runtime_root=tmp_path, cwd=tmp_path, execution_profile="conversation",
    )
    agent.process = _Process()
    await agent.send("quelle est la météo demain ?")

    trace = RuntimeJournal(tmp_path).trace_path.read_text(encoding="utf-8")
    assert "quelle est la météo demain" in trace
    assert "restricted_input_withheld" not in trace


async def test_la_voie_speculative_historique_beneficie_de_la_meme_retenue(tmp_path) -> None:
    """`speculative_analysis` porte une transcription provisoire : même règle.

    Ce profil-ci n'est pas le mien, mais la fuite est la même et le correctif
    est un seul `if` : le retenir pour le seul profil neuf aurait laissé la
    moitié du trou ouverte, sur le chemin qui, lui, est **durable**.
    """

    from jarvis.runtime.claude_local import ClaudeLocalAgent
    from jarvis.runtime.journal import RuntimeJournal

    class _Stdin:
        def write(self, data) -> None: ...

        async def drain(self) -> None: ...

    class _Process:
        returncode = None
        pid = 4242
        stdin = _Stdin()

    secret = "le chiffre d affaires du troisieme trimestre"
    agent = ClaudeLocalAgent(
        runtime_root=tmp_path, cwd=tmp_path, execution_profile="speculative_analysis",
    )
    agent.process = _Process()
    await agent.send(secret)

    trace = RuntimeJournal(tmp_path).trace_path.read_text(encoding="utf-8")
    assert secret not in trace
    assert "restricted_input_withheld" in trace


# ==========================================================================
# 14. « Montre-moi ça » montre vraiment quelque chose
# ==========================================================================


async def test_une_preparation_explicite_monte_un_objet_de_scene(tmp_path) -> None:
    """« Une ressource réutilisable est un objet de scène, pas seulement une note. »

    L'état discriminant, et il n'existait pas : `stage_hidden` n'avait **aucun
    producteur de production**. La table le prévoyait, `_show_prepared` savait
    le révéler, `retire()` savait le reprendre — et rien ne le demandait, donc
    aucune ressource n'était un `SCENE_OBJECT`, donc « montre-moi ça »
    réchauffait une ressource et ne dessinait rien.

    Ici le jeton d'un **tour explicite** est construit pour de vrai
    (`REFRESH_CAPABILITIES` porte `DISPLAY_PREPARATION`), et on lit ce que le
    monteur a réellement reçu.
    """

    from jarvis.core.presentation_addressed_turn import REFRESH_CAPABILITIES

    journal = RecordingJournal()
    answer = json.dumps({"findings": [
        {"kind": "url", "locator": "https://example.org/bilan", "title": "Bilan Q3"},
        {"kind": "url", "locator": "https://example.org/autre", "title": "Autre"},
    ]})
    runner = PresentationPreparationRunner(
        agent_factory=lambda tools: ScriptedAgent(answer),
        record_source=lambda kind, locator, title: None, journal=journal,
    )
    outcome = await runner.prepare(_request(*REFRESH_CAPABILITIES,
                                            origin=UtteranceOrigin.ADDRESSED))

    assert len(outcome.findings) == 2
    assert outcome.findings[0].stage_hidden is True, "la première est montée"
    assert outcome.findings[1].stage_hidden is False, (
        "une seule par travail : huit objets pour la séance, quatre par travail les rempliraient"
    )
    assert runner.stats()["staging_requested"] == 1


async def test_une_preparation_ambiante_ne_monte_jamais_rien(tmp_path) -> None:
    """D03 / D13 : la salle n'ouvre aucune écriture durable, et un écran en est une."""

    journal = RecordingJournal()
    answer = json.dumps({"findings": [
        {"kind": "url", "locator": "https://example.org/bilan", "title": "Bilan"},
    ]})
    runner = PresentationPreparationRunner(
        agent_factory=lambda tools: ScriptedAgent(answer),
        record_source=lambda kind, locator, title: None, journal=journal,
    )
    outcome = await runner.prepare(_request(SpeculativeCapability.RESEARCH_SEARCH))

    assert outcome.findings and outcome.findings[0].stage_hidden is False
    assert runner.stats()["staging_requested"] == 0


async def test_le_modele_ne_peut_pas_demander_lui_meme_un_ecran(tmp_path) -> None:
    """« Le montage est une décision du jeton, jamais une demande de l'exécutant. »"""

    journal = RecordingJournal()
    answer = json.dumps({"findings": [
        {"kind": "url", "locator": "https://example.org/x", "title": "X", "stage_hidden": True},
    ]})
    runner = PresentationPreparationRunner(
        agent_factory=lambda tools: ScriptedAgent(answer),
        record_source=lambda kind, locator, title: None, journal=journal,
    )
    outcome = await runner.prepare(_request(SpeculativeCapability.RESEARCH_SEARCH))

    assert outcome.findings[0].stage_hidden is False, (
        "le champ du modèle est ignoré : seul le jeton décide"
    )


async def test_un_objet_monte_est_revele_et_inscrit_au_registre(tmp_path) -> None:
    """La chaîne entière : montage masqué -> registre -> révélation.

    C'est ce que `SHOW_PREPARED` promet, et ce que rien n'atteignait. Le
    registre d'objets montés était vide en production pour la même raison, donc
    les deux affirmations du rapport à son sujet n'étaient vraies que parce que
    le chemin était mort.
    """

    from jarvis.core.presentation_addressed_turn import REFRESH_CAPABILITIES

    journal = RecordingJournal()
    built, _, _, scene = composition(tmp_path, journal)
    ledger_path = tmp_path / "presentation-staged-objects.json"
    built = dataclasses.replace(
        built, ledger_path=ledger_path,
        agent_factory=lambda tools: ScriptedAgent(json.dumps({"findings": [
            {"kind": "url", "locator": "https://example.org/bilan", "title": "Bilan Q3"},
        ]})),
    )
    stack = built.build("pres-stage-1")
    await stack.start()
    try:
        speak = stack.store.observe("pres-stage-1", "u-001", "regardons le bilan Q3",
                                    origin=UtteranceOrigin.AMBIENT)
        assert speak.applied
        admission = stack.speculative.reserve_explicit(
            topic="addressed-u-001", capabilities=REFRESH_CAPABILITIES,
            utterance_id="u-001", text="addressed-u-001",
        )
        assert admission.value == "accepted", admission
        await stack.speculative.drain()

        assert scene.created, "la scène a reçu une création"
        assert scene.created[0]["visibility"] == "hidden"
        assert ledger_path.exists(), "l'objet monté est inscrit, sinon un arrêt brutal le perd"

        resources = [r for r in stack.store.snapshot.working_set.resources
                     if r.reference.kind is ResourceKind.SCENE_OBJECT]
        assert resources, "la ressource rangée pointe vers l'objet, pas vers le locator"
        assert resources[0].reference.locator == scene.created[0]["object_id"]

        await stack.speculative.reveal(resources[0].resource_id)
        assert scene.revealed == [scene.created[0]["object_id"]], scene.revealed
    finally:
        await stack.stop("test")


async def test_une_reutilisation_sans_ecran_ne_ferme_pas_la_mesure_visible(tmp_path) -> None:
    """« Une mesure visible ne peut jamais compter un écran qui n'a pas bougé. »

    L'état discriminant : une ressource **qui n'est pas** un objet de scène.
    `_show_prepared` la réchauffe et rend `delivered=True` — c'est juste, elle
    a servi — mais rien n'a été dessiné, et fermer la borne visible là-dessus
    donnait un nombre qui prétendait mesurer un écran.
    """

    journal = RecordingJournal()
    plan = SimpleNamespace(
        correlation_id="corr-web", situation=PresentationSituation.VISUAL_COMMAND,
        context=SimpleNamespace(resource=SimpleNamespace(kind=ResourceKind.WEB_PAGE)),
    )

    async def deliver(plan):
        return SimpleNamespace(action=AddressedTurnAction.SHOW_PREPARED, delivered=True,
                               code="addressed_resource_reused", resource_id="r-1",
                               speaks=False, speech_kind=None)

    visible: list[str] = []
    turns = SimpleNamespace(
        open=lambda text, *, correlation_id: SimpleNamespace(applied=True, plan=plan, code="ok"),
        deliver=deliver, note_visible_reaction=visible.append,
        note_audible_reaction=lambda correlation_id: None, conclude=lambda correlation_id: None,
    )
    scheduler = _scheduler(turns, journal=journal, correlation="corr-web")
    scheduler.note_addressed_turn("montre-moi ça", correlation_id="corr-web")
    await until(lambda: "presentation_reuse_without_screen" in journal.codes("warning"),
                timeout=2.0)

    assert visible == [], "aucune réaction visible n'est mesurée sans écran"


async def test_une_reutilisation_d_objet_de_scene_ferme_bien_la_mesure_visible(tmp_path) -> None:
    """Le bras de contrôle : avec un écran, la mesure se ferme.

    Sans lui, « on ne mesure jamais rien » passerait aussi.
    """

    journal = RecordingJournal()
    plan = SimpleNamespace(
        correlation_id="corr-scene", situation=PresentationSituation.VISUAL_COMMAND,
        context=SimpleNamespace(resource=SimpleNamespace(kind=ResourceKind.SCENE_OBJECT)),
    )

    async def deliver(plan):
        return SimpleNamespace(action=AddressedTurnAction.SHOW_PREPARED, delivered=True,
                               code="addressed_resource_reused", resource_id="r-2",
                               speaks=False, speech_kind=None)

    visible: list[str] = []
    turns = SimpleNamespace(
        open=lambda text, *, correlation_id: SimpleNamespace(applied=True, plan=plan, code="ok"),
        deliver=deliver, note_visible_reaction=visible.append,
        note_audible_reaction=lambda correlation_id: None, conclude=lambda correlation_id: None,
    )
    scheduler = _scheduler(turns, journal=journal, correlation="corr-scene")
    scheduler.note_addressed_turn("montre-moi ça", correlation_id="corr-scene")
    await until(lambda: visible == ["corr-scene"], timeout=2.0)

    assert "presentation_reuse_without_screen" not in journal.codes("warning")


async def test_le_tour_remis_au_cerveau_ne_pretend_pas_lui_avoir_donne_le_contexte(
    tmp_path,
) -> None:
    """« Une ligne de trace ne peut jamais affirmer une livraison qui n'a pas eu lieu. »

    ## L'état que rien ne construisait

    `deliver()` n'était conduit sur la branche `ASK_BRAIN` par aucun test, et
    c'est la Slice 11 qui l'a rendue atteignable en production
    (`SpeechScheduler` appelle `turns.deliver(plan)`). La ligne disait « remis
    au cerveau **avec son contexte** » — or `submit_brain_turn` ne porte aucun
    paramètre de contexte et le tour est classé *après* sa soumission. Une
    limitation connue devenait une affirmation fausse écrite dans l'artefact
    sur lequel la recette sera lue.

    Ce test conduit le **vrai** service, depuis un vrai déclencheur, jusqu'à la
    vraie ligne.
    """

    journal = RecordingJournal()
    stack, _, manual, _ = await started_stack(tmp_path, journal)
    router = PresentationWakeRouter(simple=FakeSimpleWake(owns_device=False))
    router.adopt(stack)
    detections = router.detections()
    try:
        # Une parole dans la salle, pour que la fenêtre ait un référent.
        stack.store.observe(stack.session_id, "u-001", "parlons du chiffre d affaires",
                            origin=UtteranceOrigin.AMBIENT)
        manual.press()
        await asyncio.wait_for(anext(detections), 2.0)

        result = stack.turns.open("quel est le total ?", correlation_id="corr-brain")
        assert result.applied, result.code
        assert result.plan.action is AddressedTurnAction.ASK_BRAIN, result.plan.action

        outcome = await stack.turns.deliver(result.plan)
        assert outcome.action is AddressedTurnAction.ASK_BRAIN
        assert outcome.delivered is True
        assert outcome.speaks is False, "un tour cerveau ne parle pas depuis cette voie"

        lines = [entry for entry in journal.entries
                 if entry["data"].get("code") == "addressed_brain_turn"]
        assert lines, "la ligne doit exister : sinon ce test ne prouve rien"
        assert "contexte" not in lines[-1]["message"], lines[-1]["message"]
        assert lines[-1]["data"]["context_projected"] is False, (
            "la seule chose vraie à dire du contexte est que personne ne l'a reçu"
        )
    finally:
        await detections.aclose()
        await stack.stop("test")


async def test_le_tour_cerveau_ne_ferme_aucune_mesure_visible(tmp_path) -> None:
    """Rien n'est montré sur cette branche, donc rien n'est mesuré comme montré."""

    journal = RecordingJournal()
    plan = SimpleNamespace(
        correlation_id="corr-ask", situation=PresentationSituation.KNOWLEDGE_QUESTION,
        context=SimpleNamespace(resource=SimpleNamespace(kind=None)),
    )

    async def deliver(plan):
        return SimpleNamespace(action=AddressedTurnAction.ASK_BRAIN, delivered=True,
                               code="addressed_brain_turn", resource_id="",
                               speaks=False, speech_kind=None)

    visible: list[str] = []
    concluded: list[str] = []
    turns = SimpleNamespace(
        open=lambda text, *, correlation_id: SimpleNamespace(applied=True, plan=plan, code="ok"),
        deliver=deliver, note_visible_reaction=visible.append,
        note_audible_reaction=lambda correlation_id: None, conclude=concluded.append,
    )
    scheduler = _scheduler(turns, journal=journal, correlation="corr-ask")
    scheduler.note_addressed_turn("quel est le total ?", correlation_id="corr-ask")
    await until(lambda: concluded == ["corr-ask"], timeout=2.0)

    assert visible == []
    assert _queued(scheduler) == [], "et rien n'est dit : le cerveau répondra lui-même"


# ==========================================================================
# 15. Hygiène : ce qui se dit, quand, et combien de fois
# ==========================================================================


async def test_un_blocage_nomme_ne_pollue_pas_le_demarrage_de_simple(tmp_path) -> None:
    """D14 au démarrage : un opérateur de SIMPLE n'entend pas parler des blocages.

    L'état discriminant : une composition qui **porte** deux blocages, et un
    contrôleur qui n'entre jamais en PRESENTATION. Les deux lignes existaient
    au lancement de Voice, donc à chaque démarrage, pour une fonctionnalité
    qu'un utilisateur de SIMPLE n'emploie pas — et une trace qui se remplit est
    une régression de SIMPLE.
    """

    journal = RecordingJournal()
    built, _, _, _ = composition(tmp_path, journal)
    built = dataclasses.replace(built, blockers=(
        ("presentation_transcription_unavailable", "pas de transcription"),
        ("presentation_runner_unavailable", "pas d'exécutant"),
    ))
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake(), journal=journal),
        build=built.build, journal=journal, blockers=built.blockers,
    )
    await coordinator.apply(InteractionMode.ASSISTANT)

    assert journal.codes() == [], "SIMPLE ne dit rien du tout"
    await coordinator.aclose()


async def test_un_blocage_nomme_est_dit_une_fois_a_la_premiere_entree(tmp_path) -> None:
    """Et il est dit **au moment où il compte**, une seule fois.

    L'aller-retour est l'état discriminant : sans lui, « dit une fois » et
    « dit à chaque entrée » sont indiscernables.
    """

    journal = RecordingJournal()
    built, _, _, _ = composition(tmp_path, journal)
    blockers = (("presentation_runner_unavailable", "pas d'exécutant"),)
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake(), journal=journal),
        build=built.build, journal=journal, blockers=blockers,
    )
    try:
        await coordinator.apply(InteractionMode.PRESENTATION)
        assert journal.codes("warning").count("presentation_runner_unavailable") == 1

        await coordinator.apply(InteractionMode.ASSISTANT)
        await coordinator.apply(InteractionMode.PRESENTATION)
        assert journal.codes("warning").count("presentation_runner_unavailable") == 1, (
            "une seconde entrée ne le redit pas"
        )
    finally:
        await coordinator.aclose()


async def test_l_executant_absent_ne_se_plaint_qu_une_fois(tmp_path) -> None:
    """Quatre déclencheurs par phrase : une plainte par travail est un flot.

    L'état discriminant est construit : **deux** travaux. Avec un seul, « dit
    une fois » et « dit à chaque fois » se ressemblent — c'est la correction
    déjà faite chez le voisin (`_cli_tools`), et elle manquait ici.
    """

    from jarvis.runtime.presentation_runtime import _AbsentRunner

    journal = RecordingJournal()
    runner = _AbsentRunner(journal)
    await runner.prepare(SimpleNamespace(job_id="job-1"))
    await runner.prepare(SimpleNamespace(job_id="job-2"))

    assert journal.codes("warning").count("presentation_runner_absent") == 1
    assert runner.refused == 2, "le compte, lui, reste exact"


async def test_une_source_evincee_par_son_propre_rangement_n_est_pas_citee(tmp_path) -> None:
    """« Un identifiant rendu désigne toujours un enregistrement qui existe. »

    ## L'état que la première version ne construisait pas

    Elle remplissait la collection, constatait l'éviction d'une ancienne source,
    puis vérifiait qu'une source **fraîche** était bien rendue — ce qui est vrai
    avec ou sans la relecture. Une mutation retirant la relecture a donc
    survécu : le test atteignait le code de la garde et jamais son état.

    L'état réel est celui-ci : une source dont l'horodatage est **plus vieux**
    que les douze retenues est la victime de sa propre éviction. Le magasin
    répond `applied`, et sans la relecture l'enregistreur rendrait l'identifiant
    d'un enregistrement qui n'existe déjà plus — une provenance fantôme, que le
    juge croirait vérifiée. C'est atteignable par une horloge qui recule, et ce
    sera atteignable par tout appelant qui voudra horodater une source à la date
    de sa découverte plutôt qu'à celle de son rangement.
    """

    from jarvis.domain.presentation_working_set import MAX_WORKING_SET_SOURCES

    store = PresentationWorkingSetStore()
    store.bind_session("pres-race")
    now = utc_now()

    fresh = source_recorder(store, session_id="pres-race", clock=lambda: now)
    for index in range(MAX_WORKING_SET_SOURCES):
        assert fresh(ResourceKind.WEB_PAGE, f"https://example.org/{index}", f"T{index}")
    assert len(store.snapshot.working_set.sources) == MAX_WORKING_SET_SOURCES, (
        "la collection doit être pleine, sinon rien ne peut être évincé"
    )

    stale = source_recorder(store, session_id="pres-race",
                            clock=lambda: now - timedelta(hours=1))
    got = stale(ResourceKind.WEB_PAGE, "https://example.org/vieille", "Vieille")

    assert got is None, (
        "une source évincée par son propre rangement ne peut pas être citée"
    )
    held = {source.record_id for source in store.snapshot.working_set.sources}
    assert len(held) == MAX_WORKING_SET_SOURCES

    # Bras de contrôle : une source fraîche est toujours rendue. Sans lui,
    # « ne jamais rien rendre » passerait aussi.
    kept = fresh(ResourceKind.WEB_PAGE, "https://example.org/fraiche", "Fraîche")
    assert kept is not None
    assert kept in {s.record_id for s in store.snapshot.working_set.sources}


async def test_un_registre_qui_deborde_le_dit_plutot_que_de_perdre_en_silence(tmp_path) -> None:
    """« Un objet monté ne peut jamais cesser d'être repris sans qu'on le sache. »

    Reprendre deux fois est gratuit ; perdre un identifiant laisse une ligne
    durable dans `scene_objects` que plus rien ne reprendra. Le plafond le
    faisait en silence.
    """

    from jarvis.runtime.presentation_runtime import MAX_LEDGER_IDS

    journal = RecordingJournal()
    ledger = StagedObjectLedger(tmp_path / "staged.json", journal=journal)
    for index in range(MAX_LEDGER_IDS):
        ledger.add(f"obj-{index}")
    assert journal.codes("error") == [], "sous la borne, rien à dire"

    ledger.add("obj-de-trop")

    assert "presentation_ledger_overflow" in journal.codes("error")
    assert len(ledger.ids) == MAX_LEDGER_IDS
    assert "obj-de-trop" in ledger.ids, "le plus récent est gardé"


async def test_les_orphelins_sont_repris_au_demarrage_meme_sans_entrer_en_presentation(
    tmp_path,
) -> None:
    """« Un objet fantôme ne peut jamais attendre le prochain geste de l'opérateur. »

    La reprise vivait seulement à l'entrée en PRESENTATION. Un Voice tué
    pendant une présentation, puis des semaines en SIMPLE, gardait ses objets à
    l'écran — la seule chose que ce registre existe pour empêcher.
    """

    journal = RecordingJournal()
    ledger_path = tmp_path / "presentation-staged-objects.json"
    ledger_path.write_text(json.dumps({"object_ids": ["obj-fantome"]}), encoding="utf-8")
    scene = FakeSceneTools()
    built, _, _, _ = composition(tmp_path, journal, scene=scene)
    built = dataclasses.replace(built, ledger_path=ledger_path)
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=FakeSimpleWake(), journal=journal),
        build=built.build, journal=journal, reclaimer=built.reclaimer(),
    )

    reclaimed = await coordinator.reclaim_orphans()

    assert reclaimed == ("obj-fantome",)
    assert scene.archived == [["obj-fantome"]]
    assert not ledger_path.exists()
    assert coordinator.audio is None, "et aucune séance n'a été composée pour autant"
    await coordinator.aclose()


async def test_une_composition_qui_leve_n_empeche_pas_simple_de_demarrer(tmp_path) -> None:
    """« Composer PRESENTATION ne peut jamais empêcher Voice de démarrer. »

    Le contrôleur est `None` et le runtime s'en accommode : l'aiguillage sert
    la pile d'éveil, `_shared_input_source()` rend `None`, et le bridge ouvre
    son unique flux comme il l'a toujours fait.
    """

    from jarvis.v2_config import VoiceArchitecture
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime

    journal = RecordingJournal()
    simple = FakeSimpleWake()
    router = PresentationWakeRouter(simple=simple, journal=journal)

    async def factory(context):
        raise AssertionError("aucune session temps réel dans ce test")

    runtime = PersistentVoiceRuntime(
        wakeword=router, core=SimpleNamespace(), realtime_factory=factory,
        auto_turn=True, voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN,
        presentation=None,
    )
    runtime.interaction_mode.adopt({"mode": "presentation", "revision": 1, "epoch": "life-1"})

    assert runtime.presentation_session() is None
    assert runtime._shared_input_source() is None
    assert runtime.presentation_turns() is None

    detections = router.detections()
    simple.detect("jarvis")
    assert await asyncio.wait_for(anext(detections), 2.0) == "jarvis"
    await detections.aclose()


async def test_une_bascule_de_mode_ne_depareille_jamais_suspend_et_resume(tmp_path) -> None:
    """« Une source d'éveil ne peut jamais rester suspendue toute seule. »

    L'état discriminant : la bascule arrive **entre** le `suspend` et le
    `resume`. Résolus par la source *courante*, les deux partaient à des
    backends différents et l'un restait suspendu pour toujours — un mot d'éveil
    mort, sans une ligne pour le dire.
    """

    journal = RecordingJournal()
    stack, _, manual, _ = await started_stack(tmp_path, journal)
    simple = FakeSimpleWake(owns_device=False)
    router = PresentationWakeRouter(simple=simple, journal=journal)
    try:
        await router.suspend_for_active_session()
        router.adopt(stack)          # le mode bascule entre les deux
        await router.resume()

        assert simple.suspends == 1 and simple.resumes == 1, (
            "la pile de SIMPLE est reprise autant de fois qu'elle a été suspendue"
        )
    finally:
        await stack.stop("test")


async def test_une_bascule_hors_attente_ne_laisse_pas_d_iterateur_ouvert(tmp_path) -> None:
    """« Un itérateur de source morte ne peut jamais rester indexé. »

    L'état discriminant : la bascule arrive alors qu'**aucune** attente n'est
    en vol, ce que `_drop_pending()` ne voit pas. `_iterators` est indexé par
    `id(source)`, et cet identifiant est réutilisable après un ramassage : un
    générateur oublié là pouvait donc être servi à une source neuve.
    """

    journal = RecordingJournal()
    stack, _, manual, _ = await started_stack(tmp_path, journal)
    router = PresentationWakeRouter(simple=FakeSimpleWake(owns_device=False), journal=journal)
    router.adopt(stack)
    detections = router.detections()
    try:
        manual.press()
        await asyncio.wait_for(anext(detections), 2.0)
        # L'attente est retombée : `_pending` est None, et c'est là que la
        # bascule passait sans rien nettoyer.
        assert router.dropped_iterators == 0

        router.adopt(None)

        assert router.dropped_iterators == 1
        assert router.stats()["routing"] == "simple"
    finally:
        await detections.aclose()
        await stack.stop("test")
