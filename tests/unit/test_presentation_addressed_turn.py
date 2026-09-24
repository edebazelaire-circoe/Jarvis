"""Slice 10 — le tour adressé prioritaire : frais, immédiat, et qui réutilise.

Ce que cette suite doit prouver, et comment elle le prouve :

- **D04.** L'admission d'un tour adressé n'attend aucun travail ambiant. Prouvé
  deux fois : *structurellement*, parce qu'`arm()` et `open()` sont synchrones
  et qu'une fonction sans `await` ne peut pas céder la boucle ; et *mesuré*,
  sous un arriéré ambiant **constaté saturé** et un bassin spéculatif
  **constaté plein**, avec des travaux d'ordre de la minute qui sont encore en
  vol après la mesure.
- **D06.** Le référent d'un déictique est toujours l'énonciation la plus récente
  du fil, et un cache préparé sur une parole plus ancienne **perd**. Le test qui
  le prouve atteint l'état exact où la faute serait commise : une ressource
  chaude, vivante, ancrée à un sujet vivant, pendant que l'enrichissement a trois
  énonciations de retard.
- **D08.** Ce que cette Slice fait pour la capacité est nommé et rien de plus :
  `note_addressed_turn()`. Un test constate la préemption sur un bassin
  **réellement** plein ; aucun test ne prétend que `free_explicit_slots` dit
  quoi que ce soit de la capacité d'exécution du tour adressé.
- **D09/D10.** La politique de parole n'est pas redécidée : les sept
  dispositions du tour sont comparées à celles de la matrice, une commande
  visuelle se termine sans un mot, une vraie question peut parler, et la
  clarification est audible **parce que** la matrice le dit.
- Chaque phrase d'en-tête de la forme « X ne lève jamais » a son test à l'endroit
  exact où elle se casserait : le magasin qui lève, la voie spéculative qui lève,
  le classement qui lève, le journal qui lève, l'horloge qui recule.
- Chaque garde est exercée **dans l'état pour lequel elle existe**, pas seulement
  sur son chemin de code : une ressource réellement retirée, un bassin réellement
  saturé, une fenêtre réellement expirée, une matrice qui refuse réellement.
- Aucun test n'inspecte du texte source, **sauf deux**, qui portent tous deux sur
  l'**absence** d'une chose : voir leurs docstrings. C'est la règle de la
  Slice 03 et l'exception posée par la Slice 05.
- **Aucun micro, aucun réseau, aucun modèle.** La fabrique de flux, le
  transcripteur, l'exécutant spéculatif et le monteur de scène sont injectés.
"""

from __future__ import annotations

import array
import ast
import asyncio
import dataclasses
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.audio import input_ownership
from jarvis.audio.ambient_segmenter import AmbientSegmenter
from jarvis.core.latency import LATENCY_MEASURES, LatencyTracker
from jarvis.core.presentation_addressed_turn import (
    ADDRESSED_KIND,
    ADDRESSED_LATENCY_MEASURES,
    REFRESH_CAPABILITIES,
    TRIGGER_TO_ADMISSION,
    TRIGGER_TO_AUDIBLE,
    TRIGGER_TO_VISIBLE,
    AddressedTurnOutcome,
    AddressedTurnPlan,
    PresentationAddressedTurnService,
)
from jarvis.core.presentation_speculative import (
    PresentationSpeculativeService,
    SpeculativeOutcome,
)
from jarvis.core.presentation_working_set import PresentationWorkingSetStore
from jarvis.core.voice_state import VoiceStateDisposition
from jarvis.domain.explicit_address import (
    MAX_TRIGGER_AGE_S,
    ExplicitAddressSource,
    ExplicitAddressTrigger,
)
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.output_disposition import OutputDisposition
from jarvis.domain.presentation_addressed_turn import (
    DEICTIC_MARKERS,
    MAX_ADDRESSED_CONTEXT_CHARS,
    MAX_ADDRESSED_TAIL_ENTRIES,
    MAX_ADDRESSED_WINDOW_S,
    AddressedTurnAction,
    AddressedTurnContext,
    AddressedWindow,
    ContextOrigin,
    PresentationAddressedTurnError,
    ResolvedReferent,
    ResourceResolution,
    ResourceVerdict,
    build_addressed_turn_context,
    decide_action,
    deictic_marker,
    resolve_prepared_resource,
    resolve_referent,
)
from jarvis.domain.presentation_policy import (
    PRESENTATION_POLICY,
    PresentationSituation,
    may_speak,
    policy_for,
)
from jarvis.domain.presentation_response import (
    PresentationSpeechVerdict,
    admit_presentation_speech,
)
from jarvis.domain.presentation_speculative import (
    MAX_SPECULATIVE_POOL,
    RESERVED_EXPLICIT_SLOTS,
    SpeculativeAdmission,
    SpeculativeCapability,
)
from jarvis.domain.presentation_working_set import (
    AttentionCategory,
    AttentionItem,
    AttentionSeverity,
    ObservationProvenance,
    OpenQuestion,
    PreparedResource,
    PresentationClaim,
    PresentationEntity,
    PresentationObservation,
    PresentationTopic,
    ResourceKind,
    ResourceReference,
    ResourceTemperature,
    UtteranceOrigin,
)
from jarvis.domain.v2 import SpeechKind
from jarvis.runtime.ambient_lane import AmbientIngestionLane
from jarvis.runtime.presentation_audio import PresentationAudioSession

ROOT = Path(__file__).resolve().parents[2]
SESSION = "seance-10"
NOW = datetime(2026, 9, 24, 10, 0, 0, tzinfo=timezone.utc)
HUB_RATE = 24000
BLOCK_FRAMES = 1200
#: Coût nominal d'un travail de l'arriéré simulé. Une présentation dure des
#: dizaines de minutes ; un travail d'une minute n'a rien d'extraordinaire, et
#: c'est l'échelle que SLICE.md demande de simuler.
BACKLOG_JOB_S = 120.0
MAX_SPEC = MAX_SPECULATIVE_POOL - RESERVED_EXPLICIT_SLOTS


# ==========================================================================
# Doublures — toutes namespacées `S10` pour ne rien partager avec les autres
# suites de ce handoff.
# ==========================================================================


class S10Journal:
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


class S10Clock:
    """Horloge monotone pilotée par le test. Elle n'a pas le droit de reculer."""

    def __init__(self, value: float = 10_000.0) -> None:
        self.value = float(value)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


class S10Stager:
    """Monteur de scène faux : il note ce qu'on lui demande, dans l'ordre."""

    def __init__(self, *, fail_reveal: bool = False) -> None:
        self.revealed: list[str] = []
        self.staged: list[dict[str, str]] = []
        self.discarded: list[str] = []
        self.fail_reveal = fail_reveal
        self._n = 0

    async def stage_hidden(self, *, category: str, title: str, summary: str) -> str:
        self._n += 1
        object_id = f"scene-{self._n:03d}"
        self.staged.append({"object_id": object_id, "category": category, "title": title})
        return object_id

    async def reveal(self, object_id: str) -> None:
        if self.fail_reveal:
            raise RuntimeError("scene injoignable")
        self.revealed.append(object_id)

    async def discard(self, object_ids) -> None:  # noqa: ANN001
        self.discarded.extend(object_ids)


class S10Runner:
    """Exécutant spéculatif faux. Son coût est déclaré, jamais réellement payé."""

    def __init__(self, *, hold: asyncio.Event | None = None, duration_s: float = BACKLOG_JOB_S) -> None:
        self.hold = hold
        self.duration_s = duration_s
        self.calls = 0

    async def prepare(self, request):  # noqa: ANN001
        self.calls += 1
        if self.hold is not None:
            await self.hold.wait()
        else:
            await asyncio.sleep(self.duration_s)
        return SpeculativeOutcome(findings=())


class S10Speculative:
    """Voie spéculative scriptée : elle dit ce qu'on lui dicte et note ses appels."""

    def __init__(
        self,
        *,
        preempted: tuple[str, ...] = (),
        reveal: SpeculativeAdmission = SpeculativeAdmission.ACCEPTED,
        reserve: SpeculativeAdmission = SpeculativeAdmission.ACCEPTED,
        raise_on: str = "",
    ) -> None:
        self.preempted = preempted
        self._reveal = reveal
        self._reserve = reserve
        self.raise_on = raise_on
        self.notes = 0
        self.reveals: list[str] = []
        self.reserves: list[dict[str, object]] = []

    def note_addressed_turn(self) -> tuple[str, ...]:
        self.notes += 1
        if self.raise_on == "note":
            raise RuntimeError("voie hors service")
        return self.preempted

    async def reveal(self, resource_id: str) -> SpeculativeAdmission:
        if self.raise_on == "reveal":
            raise RuntimeError("revelation impossible")
        self.reveals.append(resource_id)
        return self._reveal

    def reserve_explicit(self, **kwargs) -> SpeculativeAdmission:  # noqa: ANN003
        if self.raise_on == "reserve":
            raise RuntimeError("reservation impossible")
        self.reserves.append(dict(kwargs))
        return self._reserve


class S10BrokenStore:
    """Magasin qui lève là où le contrat promet une disposition."""

    def __init__(self, *, on: str) -> None:
        self.on = on
        self.inner = build_store()

    @property
    def snapshot(self):
        if self.on == "snapshot":
            raise RuntimeError("instantane illisible")
        return self.inner.snapshot

    @property
    def retired_resource_ids(self):
        if self.on == "retired":
            raise RuntimeError("memoire des retraits illisible")
        if self.on == "retired_str":
            return "pas-une-collection"
        return self.inner.retired_resource_ids

    def use_resource(self, resource_id, *, at=None):  # noqa: ANN001
        if self.on == "use":
            raise RuntimeError("magasin en panne")
        return self.inner.use_resource(resource_id, at=at)


class S10CaptureDevice:
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


class S10HeldTranscriber:
    """Transcripteur qui ne rend jamais la main : l'arriéré ambiant, en personne."""

    def __init__(self, hold: asyncio.Event) -> None:
        self.hold = hold
        self.calls = 0

    async def transcribe(self, audio):  # noqa: ANN001
        self.calls += 1
        await self.hold.wait()
        return _S10Transcript("jamais rendu")


@dataclasses.dataclass(frozen=True)
class _S10Transcript:
    text: str
    duration_ms: int = 0
    provider: str = "fake"
    model: str = "fake"


class S10TriggerBackend:
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


@pytest.fixture(autouse=True)
def clean_input_registry():
    """Le compteur de propriétaires d'entrée est un état de processus."""

    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


# ==========================================================================
# Fabriques
# ==========================================================================


def build_store(**kwargs) -> PresentationWorkingSetStore:  # noqa: ANN003
    store = PresentationWorkingSetStore(**kwargs)
    store.bind_session(SESSION)
    return store


def say(store: PresentationWorkingSetStore, index: int, text: str, *, at: datetime | None = None) -> str:
    """Faire entendre une énonciation et rendre son identifiant."""

    utterance_id = f"u-{index:03d}"
    result = store.observe(
        SESSION, utterance_id, text, spoken_at=at or (NOW + timedelta(seconds=index))
    )
    assert result.applied, result.code
    return utterance_id


def sequence_of(store: PresentationWorkingSetStore, utterance_id: str) -> int:
    """Le rang que le **magasin** a attribué. Jamais un rang inventé.

    C'est la lecture que la lane ambiante fait déjà (`_tail_sequence`) et c'est
    la dépendance de données sur laquelle repose toute la précédence de D06 :
    une provenance ne peut citer qu'un rang qui existe déjà.
    """

    for entry in store.snapshot.tail.entries:
        if entry.utterance_id == utterance_id:
            return entry.sequence
    raise AssertionError(f"{utterance_id} n'est pas au fil")


def provenance(store: PresentationWorkingSetStore, utterance_id: str, *, at: datetime | None = None) -> ObservationProvenance:
    entry = next(
        item for item in store.snapshot.tail.entries if item.utterance_id == utterance_id
    )
    return ObservationProvenance(
        utterance_id=utterance_id, sequence=entry.sequence,
        observed_at=at or entry.spoken_at, origin=UtteranceOrigin.AMBIENT,
    )


def apply(store: PresentationWorkingSetStore, record: object, *, observation_id: str) -> None:
    result = store.apply(
        PresentationObservation(observation_id=observation_id, session_id=SESSION, record=record)
    )
    assert result.applied, result.code


def topic(store, utterance_id, *, topic_id="t-bilan", label="le bilan Q3", at=None):  # noqa: ANN001
    moment = at or (NOW + timedelta(seconds=60))
    apply(
        store,
        PresentationTopic(
            topic_id=topic_id, label=label, provenance=provenance(store, utterance_id),
            first_seen_at=moment, last_seen_at=moment,
        ),
        observation_id=f"obs-topic-{topic_id}-{utterance_id}",
    )


def resource(
    store,  # noqa: ANN001
    utterance_id,  # noqa: ANN001
    *,
    resource_id="r-courbe",
    topic_id="t-bilan",
    kind=ResourceKind.SCENE_OBJECT,
    locator="scene:obj-001",
    temperature=ResourceTemperature.WARM,
    at=None,  # noqa: ANN001
) -> None:
    moment = at or (NOW + timedelta(seconds=60))
    apply(
        store,
        PreparedResource(
            resource_id=resource_id,
            reference=ResourceReference(kind=kind, locator=locator, title="courbe"),
            provenance=provenance(store, utterance_id),
            prepared_at=moment, last_used_at=moment, temperature=temperature,
            topic_id=topic_id,
        ),
        observation_id=f"obs-res-{resource_id}-{utterance_id}",
    )


def trigger(clock: S10Clock, *, sequence: int = 0, source=ExplicitAddressSource.MANUAL_KEY) -> ExplicitAddressTrigger:  # noqa: ANN001
    return ExplicitAddressTrigger.admitted(source, "f9", sequence=sequence, clock=clock)


def build_service(
    store=None,  # noqa: ANN001
    *,
    clock: S10Clock | None = None,
    speculative=None,  # noqa: ANN001
    journal=None,  # noqa: ANN001
    mode=None,  # noqa: ANN001
    wall=None,  # noqa: ANN001
    **kwargs,  # noqa: ANN003
) -> PresentationAddressedTurnService:
    clock = clock or S10Clock()
    return PresentationAddressedTurnService(
        store=store if store is not None else build_store(),
        speculative=speculative,
        mode=mode,
        diagnostics=journal,
        clock=clock,
        wall_clock=wall or (lambda: NOW + timedelta(seconds=90)),
        **kwargs,
    )


def open_turn(service, clock, text, *, correlation_id="corr-1", seq=0):  # noqa: ANN001
    armed = service.arm(trigger(clock, sequence=seq), correlation_id=correlation_id)
    assert armed.applied, armed.code
    clock.advance(0.002)
    return service.open(text, correlation_id=correlation_id)


def pcm(ms: int, amplitude: int, *, rate: int = HUB_RATE) -> bytes:
    count = rate * ms // 1000
    return array.array(
        "h", [int(amplitude * math.sin(2 * math.pi * 180 * index / rate)) for index in range(count)]
    ).tobytes()


async def feed(device: S10CaptureDevice, chunk: bytes) -> None:
    block = BLOCK_FRAMES * 2
    for index, offset in enumerate(range(0, len(chunk), block)):
        device.push_block(chunk[offset : offset + block])
        if index % 8 == 7:
            await asyncio.sleep(0)
    await asyncio.sleep(0)


async def until(predicate, timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition jamais atteinte"
        await asyncio.sleep(0.005)


# ==========================================================================
# 1. La fenêtre adressée
# ==========================================================================


def test_la_fenetre_s_ouvre_avant_le_declencheur_et_se_ferme_apres() -> None:
    """Le pré-roll est une borne de la fenêtre, pas seulement du PCM.

    Le détecteur de mot d'éveil ne se déclenche jamais sur la première syllabe :
    la parole qui adresse JARVIS a **commencé avant** l'estampille.
    """

    clock = S10Clock(500.0)
    window = AddressedWindow(trigger(clock), preroll_s=1.5, max_wait_s=12.0)

    assert window.opens_at_s == pytest.approx(498.5)
    assert window.closes_at_s == pytest.approx(512.0)
    assert window.covers(499.0)
    assert window.covers(500.0)
    assert window.covers(511.9)
    assert not window.covers(498.4)
    assert not window.covers(512.1)


def test_une_fenetre_ne_peut_pas_s_ouvrir_avant_l_origine_de_l_horloge() -> None:
    """`time.monotonic()` est positif ; un pré-roll plus long que lui ne recule pas."""

    clock = S10Clock(0.5)
    window = AddressedWindow(trigger(clock), preroll_s=5.0)
    assert window.opens_at_s == 0.0
    assert window.covers(0.0)


def test_une_fenetre_expiree_refuse_le_tour_et_le_compte() -> None:
    """L'état visé est atteint : la fenêtre est **réellement** passée."""

    clock = S10Clock()
    service = build_service(clock=clock)
    assert service.arm(trigger(clock)).applied
    clock.advance(MAX_ADDRESSED_WINDOW_S + 0.5)

    result = service.open("montre-moi ca", correlation_id="corr-1")

    assert result.disposition is VoiceStateDisposition.STALE
    assert result.code == "addressed_window_expired"
    assert service.counters.windows_expired == 1
    assert not service.armed


def test_une_parole_hors_fenetre_n_est_pas_adressee() -> None:
    """Une phrase dite bien après l'appui appartient à la salle, pas au tour."""

    clock = S10Clock()
    service = build_service(clock=clock)
    service.arm(trigger(clock))

    result = service.open(
        "montre-moi ca", correlation_id="corr-1", spoken_at_s=clock.value + 30.0
    )

    assert result.code == "addressed_speech_outside_window"
    assert not service.armed


def test_une_parole_du_preroll_est_bien_celle_du_tour() -> None:
    clock = S10Clock()
    store = build_store()
    say(store, 1, "montre-moi ca")
    service = build_service(store, clock=clock)
    service.arm(trigger(clock))

    result = service.open(
        "montre-moi ca", correlation_id="corr-1", spoken_at_s=clock.value - 1.0
    )

    assert result.applied


def test_une_fenetre_ne_sert_qu_un_seul_tour() -> None:
    """Sinon un seul appui adresserait deux phrases, dont la seconde à personne."""

    clock = S10Clock()
    store = build_store()
    say(store, 1, "montre-moi ca")
    service = build_service(store, clock=clock)

    first = open_turn(service, clock, "montre-moi ca")
    second = service.open("et celui-la aussi", correlation_id="corr-2")

    assert first.applied
    assert second.disposition is VoiceStateDisposition.IGNORED
    assert second.code == "addressed_no_window"


def test_un_second_appui_remplace_la_fenetre_et_le_compte() -> None:
    clock = S10Clock()
    service = build_service(clock=clock)
    service.arm(trigger(clock, sequence=0))
    clock.advance(1.0)
    service.arm(trigger(clock, sequence=1))

    assert service.counters.armed == 2
    assert service.counters.rearmed == 1
    assert service.window is not None
    assert service.window.trigger.sequence == 1


def test_un_declencheur_hors_type_est_refuse_sans_rien_armer() -> None:
    service = build_service()
    result = service.arm("f9")
    assert result.disposition is VoiceStateDisposition.REJECTED
    assert result.code == "addressed_trigger_invalid"
    assert not service.armed


def test_un_declencheur_qui_pretend_autoriser_une_action_est_refuse() -> None:
    """D03, et la garde est atteinte **dans l'état pour lequel elle existe**.

    Un objet qui n'est pas un `ExplicitAddressTrigger` est écarté par le
    contrôle de type une ligne plus haut et n'atteint jamais ce refus-ci : un
    test bâti ainsi exercerait `arm()` sans jamais toucher la garde. Il faut donc
    un objet qui **est** un déclencheur et qui prétend quand même autoriser —
    exactement la forme qu'aurait un transport reconstruisant l'objet.
    """

    class ForgedTrigger(ExplicitAddressTrigger):
        authorizes_actions = True  # type: ignore[assignment]

    forged = ForgedTrigger(ExplicitAddressSource.MANUAL_KEY, "f9", 10_000.0, 0)
    assert isinstance(forged, ExplicitAddressTrigger)
    assert forged.authorizes_actions is True

    service = build_service()
    result = service.arm(forged)

    assert result.disposition is VoiceStateDisposition.REJECTED
    assert result.code == "addressed_trigger_authorizing"
    assert not service.armed


def test_un_declencheur_reel_n_autorise_jamais_une_action() -> None:
    clock = S10Clock()
    stamped = trigger(clock)
    assert stamped.authorizes_actions is False
    # `authorizes_actions` est un `ClassVar` : `replace` ne peut pas le tourner.
    assert dataclasses.replace(stamped, label="f10").authorizes_actions is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        stamped.label = "f10"  # type: ignore[misc]


def test_une_fenetre_hors_nombre_echoue_du_cote_sur() -> None:
    """Un `covers` faux et un `expired` vrai : on n'adresse pas par défaut."""

    window = AddressedWindow(trigger(S10Clock()))
    for value in (None, "maintenant", True, object()):
        assert window.covers(value) is False
        assert window.expired(value) is True


def test_une_fenetre_de_duree_nulle_est_refusee() -> None:
    clock = S10Clock()
    with pytest.raises(PresentationAddressedTurnError) as excinfo:
        AddressedWindow(trigger(clock), max_wait_s=0.0)
    assert excinfo.value.code == "addressed_window_bound_invalid"


def test_une_fenetre_se_construit_sur_un_declencheur_type() -> None:
    with pytest.raises(PresentationAddressedTurnError) as excinfo:
        AddressedWindow("f9")  # type: ignore[arg-type]
    assert excinfo.value.code == "addressed_window_trigger_invalid"


def test_un_declencheur_perime_arme_quand_meme_et_le_dit() -> None:
    """Règle de la Slice 05 tenue ici aussi : perdre un appui est pire.

    Les deux couches doivent se contredire nulle part ; l'état visé est celui
    d'un déclencheur **réellement** plus vieux que `MAX_TRIGGER_AGE_S`.
    """

    clock = S10Clock()
    journal = S10Journal()
    service = build_service(clock=clock, journal=journal)
    stamped = trigger(clock)
    clock.advance(MAX_TRIGGER_AGE_S + 0.5)

    result = service.arm(stamped)

    assert result.applied
    assert service.counters.stale_triggers == 1
    assert "addressed_trigger_stale" in journal.codes(level="warning")


def test_un_tour_sans_seance_liee_est_ignore() -> None:
    store = PresentationWorkingSetStore()
    service = build_service(store)
    result = service.arm(trigger(S10Clock()))
    assert result.disposition is VoiceStateDisposition.IGNORED
    assert result.code == "addressed_working_set_inactive"


# ==========================================================================
# 2. D04 — l'admission n'attend pas l'ambiant
# ==========================================================================


def test_l_admission_d_un_tour_adresse_ne_peut_pas_ceder_la_boucle() -> None:
    """Lecture de **source**, et c'est l'exception justifiée de la Slice 05.

    Aucun test de comportement ne prouve l'**absence** d'un `await` : il prouve
    au mieux qu'un chemin donné n'en a pas rencontré. Or la garantie D04 est
    structurelle — une fonction synchrone ne peut pas rendre la main à la boucle,
    donc aucun travail ambiant ne peut s'intercaler entre l'estampille du
    déclencheur et l'instantané de contexte.

    Ne pas supprimer ce test au motif que « les tests n'inspectent pas la
    source » : c'est exactement le cas que cette règle excepte.
    """

    module = ast.parse(
        (ROOT / "jarvis" / "core" / "presentation_addressed_turn.py").read_text(encoding="utf-8")
    )
    service = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "PresentationAddressedTurnService"
    )
    checked = []
    for name in ("arm", "open"):
        method = next(
            (node for node in service.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name == name),
            None,
        )
        assert method is not None, f"{name} a disparu de la voie adressée"
        assert isinstance(method, ast.FunctionDef), f"{name} est devenue asynchrone : D04 tombe"
        awaits = [node for node in ast.walk(method) if isinstance(node, ast.Await)]
        assert not awaits, f"{name} attend quelque chose : l'ambiant peut s'intercaler"
        checked.append(name)
    assert checked == ["arm", "open"]


@pytest.mark.asyncio
async def test_le_declencheur_est_admis_immediatement_malgre_un_arriere_a_l_echelle_de_la_minute() -> None:
    """D04, **mesuré contre un arriéré constaté saturé**.

    Trois saturations réelles, vérifiées avant la mesure et **encore vraies
    après** — une mesure prise sur un arriéré qui se serait vidé entre-temps ne
    dirait rien :

    1. la file de segments de la lane ambiante est à sa borne et a déjà perdu
       des segments ;
    2. le transcripteur est bloqué et ne rendra pas la main ;
    3. le bassin spéculatif est plein de travaux dont le coût déclaré est de
       deux minutes chacun, et aucun n'est terminé.
    """

    device = S10CaptureDevice()
    manual = S10TriggerBackend()
    held = asyncio.Event()
    session = PresentationAudioSession.build(
        manual_backend=manual, stream_factory=device.factory,
        sample_rate=HUB_RATE, block_frames=BLOCK_FRAMES,
    )
    await session.start()
    store = build_store()
    lane = AmbientIngestionLane(
        hub=session.hub, transcriber=S10HeldTranscriber(held), sink=store, session_id=SESSION,
        segmenter=AmbientSegmenter(sample_rate=HUB_RATE, min_utterance_ms=200, silence_hangover_ms=200),
    )
    await lane.start()
    speculative = PresentationSpeculativeService(
        store=store, runner=S10Runner(), job_timeout_s=BACKLOG_JOB_S * 4,
    )
    speculative.bind_session(SESSION)
    service = PresentationAddressedTurnService(
        store=store, speculative=speculative, clock=time.monotonic,
        wall_clock=lambda: NOW + timedelta(seconds=90),
    )
    try:
        for _ in range(14):
            await feed(device, pcm(400, 9000) + pcm(400, 15))
            await asyncio.sleep(0)
        await until(lambda: lane.counters.segments_dropped_queue >= 3)
        assert lane.stats()["segments_pending"] == lane.segment_queue_size
        assert not held.is_set()

        from jarvis.domain.ambient_observation import AmbientTrigger, AmbientTriggerKind

        for index in range(MAX_SPEC):
            admission = speculative.submit_trigger(
                AmbientTrigger(
                    kind=AmbientTriggerKind.NEW_TOPIC,
                    utterance_id=f"amb-{index:03d}",
                    text=f"un sujet numero {index} qui demande une preparation",
                )
            )
            assert admission is SpeculativeAdmission.ACCEPTED, admission
        await asyncio.sleep(0)
        assert speculative.speculative_in_flight == MAX_SPEC
        backlog_s = MAX_SPEC * BACKLOG_JOB_S
        assert backlog_s >= 60.0, "l'arriéré simulé doit être d'ordre de la minute"

        triggers = session.lane.triggers()
        manual.press()
        pressed = await asyncio.wait_for(anext(triggers), timeout=1.0)
        armed = service.arm(pressed, correlation_id="corr-charge")
        say(store, 1, "montre-moi ca")
        opened = service.open("montre-moi ca", correlation_id="corr-charge")

        assert armed.applied and opened.applied
        latency_ms = opened.plan.admission_latency_ms
        assert latency_ms is not None
        # Trois ordres de grandeur sous l'arriéré : la marge n'est pas serrée,
        # et ce que le test prouve vraiment est que l'arriéré n'entre pas dedans.
        assert latency_ms < 250.0, f"admission retardée par l'ambiant : {latency_ms} ms"
        assert latency_ms < backlog_s * 1000 / 100

        # L'arriéré est **toujours** là : la mesure n'a pas été prise sur une
        # file qui s'était vidée entre-temps.
        assert lane.stats()["segments_pending"] == lane.segment_queue_size
        assert speculative.speculative_in_flight >= MAX_SPEC - 1
        assert not held.is_set()
    finally:
        held.set()
        await speculative.stop("test")
        await lane.stop()
        await session.stop()


def test_le_tour_adresse_demande_a_la_voie_speculative_de_faire_de_la_place() -> None:
    """D08, la moitié active — et **seulement** ce que cette Slice fait pour elle."""

    clock = S10Clock()
    journal = S10Journal()
    speculative = S10Speculative(preempted=("prep-1-3",))
    service = build_service(clock=clock, speculative=speculative, journal=journal)

    service.arm(trigger(clock))

    assert speculative.notes == 1
    assert service.counters.preempted == 1
    assert "addressed_preempted" in journal.codes()


@pytest.mark.asyncio
async def test_un_bassin_reellement_plein_sacrifie_un_travail_speculatif() -> None:
    """La garde est exercée dans l'état pour lequel elle existe : bassin plein.

    Un bassin seulement *spéculativement* plein laisse la réserve libre et
    `note_addressed_turn()` ne sacrifie rien — c'est voulu. Pour atteindre le
    filtre de victimes il faut que la réserve soit prise aussi, donc des rangs
    explicites en vol.
    """

    store = build_store()
    speculative = PresentationSpeculativeService(
        store=store, runner=S10Runner(), job_timeout_s=BACKLOG_JOB_S * 4,
    )
    speculative.bind_session(SESSION)
    try:
        from jarvis.domain.ambient_observation import AmbientTrigger, AmbientTriggerKind

        for index in range(MAX_SPEC):
            speculative.submit_trigger(
                AmbientTrigger(
                    kind=AmbientTriggerKind.NEW_TOPIC, utterance_id=f"amb-{index:03d}",
                    text=f"sujet numero {index} a explorer tranquillement",
                )
            )
        for index in range(RESERVED_EXPLICIT_SLOTS):
            speculative.reserve_explicit(
                topic=f"explicite-{index}", capabilities=(SpeculativeCapability.DOCUMENT_RESOLUTION,),
                utterance_id=f"exp-{index:03d}", text=f"preparation explicite {index}",
            )
        await asyncio.sleep(0)
        assert len(speculative.in_flight) == MAX_SPECULATIVE_POOL
        assert speculative.free_explicit_slots == 0

        clock = S10Clock()
        service = build_service(store, clock=clock, speculative=speculative)
        service.arm(trigger(clock))
        await asyncio.sleep(0)

        assert service.counters.preempted == 1
        assert speculative.counters.preempted == 1
        assert speculative.explicit_in_flight == RESERVED_EXPLICIT_SLOTS
    finally:
        await speculative.stop("test")


def test_une_voie_speculative_en_panne_ne_retarde_pas_le_tour() -> None:
    """« X ne lève jamais » est un cas de test : la voie lève, le tour continue."""

    clock = S10Clock()
    journal = S10Journal()
    service = build_service(
        clock=clock, speculative=S10Speculative(raise_on="note"), journal=journal
    )

    result = service.arm(trigger(clock))

    assert result.applied
    assert service.counters.speculative_failures == 1
    assert "addressed_preemption_failed" in journal.codes(level="error")
    assert "voie hors service" not in journal.blob()


def test_sans_voie_speculative_le_tour_s_arme_quand_meme() -> None:
    clock = S10Clock()
    service = build_service(clock=clock, speculative=None)
    assert service.arm(trigger(clock)).applied


# ==========================================================================
# 3. D06 — la précédence de contexte
# ==========================================================================


def test_le_referent_est_toujours_la_parole_la_plus_recente() -> None:
    store = build_store()
    say(store, 1, "on parlait du chiffre d affaires")
    say(store, 2, "et maintenant de la marge brute")

    referent = resolve_referent(store.snapshot)

    assert referent is not None
    assert referent.utterance_id == "u-002"
    assert referent.sequence == sequence_of(store, "u-002")
    assert referent.origin is ContextOrigin.TAIL
    assert referent.enrichment_lag_entries == 2


def test_le_referent_dit_que_l_enrichissement_a_rattrape() -> None:
    store = build_store()
    say(store, 1, "le bilan Q3 montre une marge en baisse")
    topic(store, "u-001")

    referent = resolve_referent(store.snapshot)

    assert referent is not None
    assert referent.origin is ContextOrigin.WORKING_SET
    assert referent.enrichment_lag_entries == 0
    assert referent.enrichment_lag_s == 0.0


def test_un_fil_vide_ne_designe_rien() -> None:
    """Inventer un référent ferait montrer le dernier écran préparé."""

    assert resolve_referent(build_store().snapshot) is None
    assert resolve_referent("pas un instantane") is None


def test_un_cache_perime_perd_contre_une_parole_plus_fraiche() -> None:
    """D06, à l'endroit exact où la faute serait commise.

    L'état atteint est le pire possible pour la règle : la ressource est
    **chaude**, **vivante**, ancrée à un sujet **encore présent** — tout ce qui
    donnerait envie de la montrer. Seul le rang dit qu'elle a été préparée sur
    une parole plus ancienne que ce que l'utilisateur vient de désigner.
    """

    store = build_store()
    say(store, 1, "regardons le bilan Q3")
    topic(store, "u-001")
    resource(store, "u-001", temperature=ResourceTemperature.HOT)
    # L'analyse prend du retard : trois phrases entrent au fil sans être
    # enrichies. La dernière est celle que « ça » désigne.
    say(store, 2, "mais le vrai sujet c est la tresorerie")
    say(store, 3, "et notamment le besoin en fonds de roulement")
    say(store, 4, "montre-moi ca")

    snapshot = store.snapshot
    referent = resolve_referent(snapshot)
    resolution = resolve_prepared_resource(snapshot, referent=referent)

    assert referent is not None and referent.utterance_id == "u-004"
    assert snapshot.enrichment_lag_entries == 3
    assert snapshot.working_set.resources[0].temperature is ResourceTemperature.HOT
    assert resolution.verdict is ResourceVerdict.STALE
    assert resolution.code == "addressed_enrichment_behind_referent"
    assert resolution.resource_id == ""
    assert decide_action(PresentationSituation.VISUAL_COMMAND, resolution) is AddressedTurnAction.REFRESH


def test_la_precedence_se_compare_sur_un_rang_que_seul_le_magasin_attribue() -> None:
    """La règle tient par une **dépendance de données**, pas par un ordre de lignes.

    Une provenance est recopiée d'une entrée du fil que le magasin a acceptée
    avant : il n'existe donc aucune exécution où l'ensemble de travail cite un
    rang supérieur à celui que le fil détient. Le test conduit le magasin comme
    la production le conduit — parler, relire le rang attribué, ranger — et
    vérifie l'inégalité à **chaque** pas, y compris quand l'enrichissement prend
    du retard puis le rattrape.
    """

    store = build_store()
    observed = []
    for index in range(1, 9):
        say(store, index, f"phrase numero {index} de la presentation")
        if index % 3 == 0:
            topic(store, f"u-{index:03d}", topic_id=f"t-{index}", label=f"sujet {index}")
        snapshot = store.snapshot
        observed.append(
            (snapshot.working_set.observed_sequence, snapshot.tail.latest_sequence)
        )
        assert snapshot.working_set.observed_sequence <= snapshot.tail.latest_sequence

    assert any(cached < spoken for cached, spoken in observed), "le retard n'a jamais été atteint"
    assert any(cached == spoken for cached, spoken in observed), "le rattrapage n'a jamais eu lieu"


def test_le_referent_survit_a_une_revision_de_transcription() -> None:
    """Une correction tardive garde son rang : elle ne devient pas « le plus frais »."""

    store = build_store()
    say(store, 1, "la marge est a douze")
    say(store, 2, "montre-moi ca")
    store.observe(SESSION, "u-001", "la marge est a douze pourcent",
                  spoken_at=NOW + timedelta(seconds=30), revision=1)

    referent = resolve_referent(store.snapshot)
    assert referent is not None
    assert referent.utterance_id == "u-002"


# ==========================================================================
# 4. Le résolveur de ressource préparée
# ==========================================================================


def test_une_ressource_ancree_au_referent_est_reutilisable() -> None:
    store = build_store()
    say(store, 1, "voici la courbe de marge")
    topic(store, "u-001")
    resource(store, "u-001")

    snapshot = store.snapshot
    resolution = resolve_prepared_resource(snapshot, referent=resolve_referent(snapshot))

    assert resolution.verdict is ResourceVerdict.REUSABLE
    assert resolution.resource_id == "r-courbe"
    assert resolution.kind is ResourceKind.SCENE_OBJECT
    assert resolution.code == "addressed_resource_anchored_to_referent"


def test_une_ressource_ancree_a_un_sujet_vivant_est_reutilisable() -> None:
    """L'ancrage indirect : le sujet est vivant et l'enrichissement a rattrapé."""

    store = build_store()
    say(store, 1, "parlons du bilan Q3")
    topic(store, "u-001")
    resource(store, "u-001")
    say(store, 2, "montre-moi ca")
    topic(store, "u-002", topic_id="t-bilan", label="le bilan Q3")

    snapshot = store.snapshot
    referent = resolve_referent(snapshot)
    resolution = resolve_prepared_resource(snapshot, referent=referent)

    assert referent is not None and referent.utterance_id == "u-002"
    assert snapshot.enrichment_lag_entries == 0
    assert resolution.verdict is ResourceVerdict.REUSABLE
    assert resolution.code == "addressed_resource_anchored_to_live_topic"


def test_une_ressource_retiree_ne_ressuscite_pas() -> None:
    """Le côté lecture du retrait : le magasin le tient déjà côté écriture."""

    store = build_store()
    say(store, 1, "voici la courbe")
    topic(store, "u-001")
    resource(store, "u-001")

    snapshot = store.snapshot
    living = resolve_prepared_resource(snapshot, referent=resolve_referent(snapshot))
    retired = resolve_prepared_resource(
        snapshot, referent=resolve_referent(snapshot), retired_resource_ids=("r-courbe",),
    )

    assert living.verdict is ResourceVerdict.REUSABLE
    assert retired.verdict is ResourceVerdict.ABSENT
    assert retired.code == "addressed_no_live_resource"


def test_une_ressource_reellement_retiree_par_le_magasin_n_est_pas_montree() -> None:
    """L'état est atteint par le magasin lui-même, pas par un paramètre de test.

    Le sujet quitte l'ensemble, la cascade rend la ressource `discardable`,
    l'éviction la sort, et le magasin l'inscrit aux retraits. C'est la voie que
    la production emprunte.
    """

    store = build_store(record_max_age_s=30.0)
    say(store, 1, "voici la courbe de marge")
    topic(store, "u-001", at=NOW + timedelta(seconds=1))
    resource(store, "u-001", at=NOW + timedelta(seconds=1))
    assert store.snapshot.working_set.resources

    # Une observation bien plus tardive fait vieillir le sujet hors de la borne
    # d'âge ; la ressource suit et sort.
    say(store, 2, "on passe a la tresorerie", at=NOW + timedelta(seconds=200))
    topic(store, "u-002", topic_id="t-treso", label="la tresorerie",
          at=NOW + timedelta(seconds=200))

    assert "r-courbe" in store.retired_resource_ids
    snapshot = store.snapshot
    assert all(item.resource_id != "r-courbe" for item in snapshot.working_set.resources)
    resolution = resolve_prepared_resource(
        snapshot, referent=resolve_referent(snapshot),
        retired_resource_ids=store.retired_resource_ids,
    )
    assert resolution.verdict is not ResourceVerdict.REUSABLE


def test_une_ressource_froide_n_est_pas_montree() -> None:
    """`discardable` : son sujet a disparu ou elle dort depuis dix minutes."""

    store = build_store()
    say(store, 1, "voici la courbe")
    topic(store, "u-001", topic_id="t-autre", label="autre sujet")
    # `topic_id` pointe un sujet absent : la cascade la déclare `discardable`.
    resource(store, "u-001", topic_id="t-disparu")

    snapshot = store.snapshot
    assert snapshot.working_set.resources[0].temperature is ResourceTemperature.DISCARDABLE
    resolution = resolve_prepared_resource(snapshot, referent=resolve_referent(snapshot))

    assert resolution.verdict is ResourceVerdict.ABSENT
    assert resolution.code == "addressed_no_live_resource"


def test_deux_ressources_a_egalite_font_demander_laquelle() -> None:
    """« ça » est réellement ambigu : deux préparations pour la même phrase."""

    store = build_store()
    say(store, 1, "compare les deux scenarios")
    topic(store, "u-001")
    resource(store, "u-001", resource_id="r-scenario-a", locator="scene:obj-a")
    resource(store, "u-001", resource_id="r-scenario-b", locator="scene:obj-b")

    snapshot = store.snapshot
    resolution = resolve_prepared_resource(snapshot, referent=resolve_referent(snapshot))

    assert resolution.verdict is ResourceVerdict.AMBIGUOUS
    assert set(resolution.tied) == {"r-scenario-a", "r-scenario-b"}
    assert resolution.resource_id == ""
    assert decide_action(PresentationSituation.VISUAL_COMMAND, resolution) is AddressedTurnAction.CLARIFY


def test_l_egalite_n_est_pas_brisee_par_l_identifiant() -> None:
    """Sinon « montre-moi ça » choisirait au hasard alphabétique.

    Les `sort_key` du magasin finissent par l'identifiant pour rendre l'éviction
    déterministe ; ici ce serait un départage arbitraire déguisé en décision.
    """

    store = build_store()
    say(store, 1, "compare les deux scenarios")
    topic(store, "u-001")
    resource(store, "u-001", resource_id="r-aaa", locator="scene:obj-a")
    resource(store, "u-001", resource_id="r-zzz", locator="scene:obj-z")

    snapshot = store.snapshot
    held = {item.resource_id: item for item in snapshot.working_set.resources}
    from jarvis.domain.presentation_addressed_turn import _resource_rank

    assert _resource_rank(held["r-aaa"]) == _resource_rank(held["r-zzz"])
    assert resolve_prepared_resource(
        snapshot, referent=resolve_referent(snapshot)
    ).verdict is ResourceVerdict.AMBIGUOUS


def test_la_plus_fraichement_ancree_gagne_sans_ambiguite() -> None:
    """Deux candidates **dans le même vivier** : c'est le classement qui tranche.

    La première version de ce test laissait l'ancrage direct ne retenir qu'une
    seule candidate, donc le tri n'était jamais consulté — une mutation qui
    inversait l'ordre survivait. Ici les deux passent par l'ancrage **par sujet**,
    donc le vivier en contient deux et le rang décide vraiment.
    """

    store = build_store()
    say(store, 1, "un premier point sur le bilan")
    topic(store, "u-001")
    resource(store, "u-001", resource_id="r-ancienne", locator="scene:obj-old")
    say(store, 2, "un second point, toujours sur le bilan")
    topic(store, "u-002", topic_id="t-bilan", label="le bilan Q3")
    resource(store, "u-002", resource_id="r-recente", locator="scene:obj-new",
             at=NOW + timedelta(seconds=61))
    say(store, 3, "montre-moi ca")
    topic(store, "u-003", topic_id="t-bilan", label="le bilan Q3")

    snapshot = store.snapshot
    held = {item.resource_id for item in snapshot.working_set.resources}
    assert held == {"r-ancienne", "r-recente"}, "le vivier doit contenir les deux"
    resolution = resolve_prepared_resource(snapshot, referent=resolve_referent(snapshot))

    assert resolution.code == "addressed_resource_anchored_to_live_topic"
    assert resolution.verdict is ResourceVerdict.REUSABLE
    assert resolution.resource_id == "r-recente"


def test_aucune_ressource_pour_le_referent_est_un_refus_et_pas_un_choix() -> None:
    store = build_store()
    say(store, 1, "parlons du bilan")
    topic(store, "u-001", topic_id="t-vivant", label="sujet vivant")
    # Ressource sans sujet du tout : elle ne pend à rien de vivant et sa
    # provenance ne cite pas le référent.
    apply(
        store,
        PreparedResource(
            resource_id="r-orpheline",
            reference=ResourceReference(kind=ResourceKind.NOTE, locator="note:1"),
            provenance=provenance(store, "u-001"),
            prepared_at=NOW + timedelta(seconds=60), last_used_at=NOW + timedelta(seconds=60),
            topic_id=None,
        ),
        observation_id="obs-orpheline",
    )
    say(store, 2, "montre-moi ca")
    topic(store, "u-002", topic_id="t-vivant", label="sujet vivant")

    snapshot = store.snapshot
    resolution = resolve_prepared_resource(snapshot, referent=resolve_referent(snapshot))

    assert resolution.verdict is ResourceVerdict.STALE
    assert resolution.code == "addressed_no_resource_for_referent"


def test_une_resolution_reutilisable_porte_toujours_son_identifiant() -> None:
    with pytest.raises(PresentationAddressedTurnError) as excinfo:
        ResourceResolution(ResourceVerdict.REUSABLE)
    assert excinfo.value.code == "addressed_resolution_invalid"


def test_seule_une_resolution_reutilisable_nomme_un_identifiant() -> None:
    with pytest.raises(PresentationAddressedTurnError) as excinfo:
        ResourceResolution(ResourceVerdict.STALE, resource_id="r-1")
    assert excinfo.value.code == "addressed_resolution_invalid"


def test_un_instantane_illisible_ne_donne_jamais_une_ressource() -> None:
    resolution = resolve_prepared_resource(
        "pas un instantane",
        referent=ResolvedReferent("u-1", 1, NOW, ContextOrigin.TAIL, 0, 0.0),
    )
    assert resolution.verdict is ResourceVerdict.ABSENT


# ==========================================================================
# 5. Le déictique
# ==========================================================================


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Jarvis, montre-moi ça", "ca"),
        ("affiche cela", "cela"),
        ("montre celui de gauche", "celui"),
        ("affiche le dernier", "le_dernier"),
        ("montre ce dont on parle", "ce_dont_on_parle"),
        ("montre-moi la courbe", ""),
        ("affiche le bilan Q3", ""),
        ("ouvre la note intitulee synthese", ""),
        ("", ""),
    ],
)
def test_le_deictique_est_reconnu_ou_absent(text: str, expected: str) -> None:
    assert deictic_marker(text) == expected


def test_le_deictique_ne_confond_pas_l_article_avec_la_designation() -> None:
    """`normalized_tokens` décompose « là » en `la` : l'article ne doit pas entrer."""

    assert "la" not in DEICTIC_MARKERS
    assert "ce" not in DEICTIC_MARKERS
    assert deictic_marker("montre la marge") == ""


def test_le_deictique_ne_leve_jamais() -> None:
    for value in (None, 42, b"octets", object(), ["liste"]):
        assert deictic_marker(value) == ""


# ==========================================================================
# 6. Réutilisation contre re-préparation
# ==========================================================================


@pytest.mark.asyncio
async def test_le_materiel_prepare_est_reutilise_et_rien_n_est_re_prepare() -> None:
    """Le cœur du contrat : réutiliser, pas refaire. Constaté des deux côtés."""

    store = build_store()
    say(store, 1, "voici la courbe de marge")
    topic(store, "u-001")
    resource(store, "u-001")
    clock = S10Clock()
    speculative = S10Speculative()
    journal = S10Journal()
    service = build_service(store, clock=clock, speculative=speculative, journal=journal)

    opened = open_turn(service, clock, "montre-moi ca")
    outcome = await service.deliver(opened.plan)

    assert opened.plan.action is AddressedTurnAction.SHOW_PREPARED
    assert outcome.delivered and outcome.code == "addressed_resource_reused"
    assert outcome.resource_id == "r-courbe"
    assert speculative.reveals == ["r-courbe"]
    assert speculative.reserves == [], "une ressource valide ne doit rien faire re-préparer"
    assert service.counters.reused == 1
    assert service.counters.revealed == 1
    assert service.counters.refreshed == 0
    assert "addressed_resource_reused" in journal.codes()


@pytest.mark.asyncio
async def test_une_ressource_non_scenique_est_rechauffee_par_le_magasin() -> None:
    """La réutilisation est **observable** : la température monte à `hot`."""

    store = build_store()
    say(store, 1, "voici le tableau de synthese")
    topic(store, "u-001")
    resource(store, "u-001", resource_id="r-tableau", kind=ResourceKind.DOCUMENT,
             locator="doc:synthese")
    clock = S10Clock()
    speculative = S10Speculative()
    service = build_service(store, clock=clock, speculative=speculative)

    before = store.snapshot.working_set.resources[0]
    opened = open_turn(service, clock, "montre-moi ca")
    outcome = await service.deliver(opened.plan)
    after = store.snapshot.working_set.resources[0]

    assert before.temperature is ResourceTemperature.WARM
    assert after.temperature is ResourceTemperature.HOT
    assert after.last_used_at > before.last_used_at
    assert outcome.delivered
    assert speculative.reveals == []
    assert speculative.reserves == []
    assert service.counters.store_dispositions["applied"] == 1


@pytest.mark.asyncio
async def test_rien_de_reutilisable_declenche_une_preparation_explicite() -> None:
    """Rafraîchir plutôt que montrer le mauvais écran — et à P1, pas à P0."""

    store = build_store()
    say(store, 1, "regardons le bilan Q3")
    topic(store, "u-001")
    resource(store, "u-001", temperature=ResourceTemperature.HOT)
    say(store, 2, "en fait parlons de la tresorerie")
    say(store, 3, "montre-moi ca")
    clock = S10Clock()
    speculative = S10Speculative()
    service = build_service(store, clock=clock, speculative=speculative)

    opened = open_turn(service, clock, "montre-moi ca")
    outcome = await service.deliver(opened.plan)

    assert opened.plan.action is AddressedTurnAction.REFRESH
    assert outcome.delivered
    assert speculative.reveals == []
    assert len(speculative.reserves) == 1
    reserved = speculative.reserves[0]
    assert reserved["capabilities"] == REFRESH_CAPABILITIES
    assert reserved["utterance_id"] == "u-003"
    assert service.counters.refreshed == 1
    assert service.counters.reused == 0


@pytest.mark.asyncio
async def test_le_sujet_de_la_preparation_ne_porte_aucune_parole() -> None:
    """Le sujet nourrit la déduplication : il n'y a aucune raison d'y mettre du dit."""

    store = build_store()
    say(store, 1, "la marmotte confidentielle de la trente-septieme diapositive")
    clock = S10Clock()
    speculative = S10Speculative()
    service = build_service(store, clock=clock, speculative=speculative)

    opened = open_turn(service, clock, "montre-moi ca")
    await service.deliver(opened.plan)

    blob = json.dumps(speculative.reserves, ensure_ascii=False, default=repr)
    assert "marmotte" not in blob
    assert "montre-moi" not in blob


@pytest.mark.asyncio
async def test_une_revelation_en_echec_ne_pretend_pas_avoir_montre() -> None:
    store = build_store()
    say(store, 1, "voici la courbe")
    topic(store, "u-001")
    resource(store, "u-001")
    clock = S10Clock()
    speculative = S10Speculative(raise_on="reveal")
    journal = S10Journal()
    service = build_service(store, clock=clock, speculative=speculative, journal=journal)

    opened = open_turn(service, clock, "montre-moi ca")
    assert opened.plan.action is AddressedTurnAction.SHOW_PREPARED, "la garde n'est pas atteinte"
    outcome = await service.deliver(opened.plan)

    assert outcome.action is AddressedTurnAction.REFRESH
    assert service.counters.reveal_failures == 1
    assert service.counters.reused == 0
    assert "addressed_reveal_failed" in journal.codes(level="error")
    assert "revelation impossible" not in journal.blob()


@pytest.mark.asyncio
async def test_une_revelation_refusee_rafraichit_au_lieu_de_compter_un_succes() -> None:
    store = build_store()
    say(store, 1, "voici la courbe")
    topic(store, "u-001")
    resource(store, "u-001")
    clock = S10Clock()
    speculative = S10Speculative(reveal=SpeculativeAdmission.REJECTED)
    service = build_service(store, clock=clock, speculative=speculative)

    opened = open_turn(service, clock, "montre-moi ca")
    assert opened.plan.action is AddressedTurnAction.SHOW_PREPARED, "la garde n'est pas atteinte"
    outcome = await service.deliver(opened.plan)

    assert outcome.action is AddressedTurnAction.REFRESH
    assert service.counters.reused == 0
    assert service.counters.speculative_admissions["rejected"] == 1


@pytest.mark.asyncio
async def test_un_objet_masque_sans_monteur_ne_passe_pas_pour_montre() -> None:
    """Sinon on déclarerait servie une ressource et l'écran resterait vide."""

    store = build_store()
    say(store, 1, "voici la courbe")
    topic(store, "u-001")
    resource(store, "u-001")
    clock = S10Clock()
    journal = S10Journal()
    service = build_service(store, clock=clock, speculative=None, journal=journal)

    opened = open_turn(service, clock, "montre-moi ca")
    outcome = await service.deliver(opened.plan)

    assert opened.plan.action is AddressedTurnAction.SHOW_PREPARED
    assert outcome.action is AddressedTurnAction.REFRESH
    assert outcome.delivered is False
    assert "addressed_reveal_unavailable" in journal.codes(level="warning")
    # Et le refus est **nommé**, pas une `AttributeError` déguisée en refus :
    # tomber dans la branche de révélation avec un monteur absent produirait la
    # même ligne d'avertissement plus une panne, et la version précédente de ce
    # test ne les distinguait pas.
    assert "addressed_reveal_failed" not in journal.codes(level="error")
    assert service.counters.reveal_failures == 1


@pytest.mark.asyncio
async def test_un_magasin_qui_refuse_la_reutilisation_fait_rafraichir() -> None:
    store = build_store()
    say(store, 1, "voici le tableau")
    topic(store, "u-001")
    resource(store, "u-001", resource_id="r-tableau", kind=ResourceKind.DOCUMENT,
             locator="doc:synthese")
    clock = S10Clock()
    speculative = S10Speculative()
    # Une horloge murale **antérieure** au dernier usage : le magasin répond
    # `stale` (`presentation_resource_use_stale`), ce qui est le refus réel.
    service = build_service(store, clock=clock, speculative=speculative,
                            wall=lambda: NOW - timedelta(seconds=10))

    opened = open_turn(service, clock, "montre-moi ca")
    assert opened.plan.action is AddressedTurnAction.SHOW_PREPARED, "la garde n'est pas atteinte"
    outcome = await service.deliver(opened.plan)

    assert outcome.action is AddressedTurnAction.REFRESH
    assert service.counters.store_dispositions["stale"] == 1
    assert service.counters.reused == 0
    assert len(speculative.reserves) == 1


@pytest.mark.asyncio
async def test_sans_voie_de_preparation_le_rafraichissement_est_dit_et_pas_avale() -> None:
    store = build_store()
    say(store, 1, "parlons d autre chose")
    clock = S10Clock()
    journal = S10Journal()
    service = build_service(store, clock=clock, speculative=None, journal=journal)

    opened = open_turn(service, clock, "montre-moi ca")
    outcome = await service.deliver(opened.plan)

    assert outcome.delivered is False
    assert outcome.code == "addressed_refresh_unavailable"
    assert service.counters.refresh_failures == 1
    assert "addressed_refresh_unavailable" in journal.codes(level="warning")


@pytest.mark.asyncio
async def test_une_reservation_en_panne_est_dite_sans_son_texte() -> None:
    store = build_store()
    say(store, 1, "parlons d autre chose")
    clock = S10Clock()
    journal = S10Journal()
    service = build_service(store, clock=clock, speculative=S10Speculative(raise_on="reserve"),
                            journal=journal)

    opened = open_turn(service, clock, "montre-moi ca")
    outcome = await service.deliver(opened.plan)

    assert outcome.delivered is False
    assert outcome.code == "addressed_refresh_failed"
    assert "addressed_refresh_failed" in journal.codes(level="error")
    assert "reservation impossible" not in journal.blob()


@pytest.mark.asyncio
async def test_une_reservation_coalescee_compte_comme_rafraichie() -> None:
    store = build_store()
    say(store, 1, "parlons d autre chose")
    clock = S10Clock()
    speculative = S10Speculative(reserve=SpeculativeAdmission.COALESCED)
    service = build_service(store, clock=clock, speculative=speculative)

    opened = open_turn(service, clock, "montre-moi ca")
    outcome = await service.deliver(opened.plan)

    assert outcome.delivered
    assert service.counters.refreshed == 1
    assert service.counters.speculative_admissions["coalesced"] == 1


@pytest.mark.asyncio
async def test_un_plan_hors_type_ne_livre_rien() -> None:
    service = build_service()
    outcome = await service.deliver("pas un plan")
    assert isinstance(outcome, AddressedTurnOutcome)
    assert outcome.delivered is False
    assert outcome.code == "addressed_plan_invalid"


# ==========================================================================
# 7. D09 / D10 — la politique de parole n'est pas redécidée
# ==========================================================================


@pytest.mark.asyncio
async def test_une_commande_visuelle_se_termine_sans_un_mot() -> None:
    store = build_store()
    say(store, 1, "voici la courbe")
    topic(store, "u-001")
    resource(store, "u-001")
    clock = S10Clock()
    service = build_service(store, clock=clock, speculative=S10Speculative())

    opened = open_turn(service, clock, "montre-moi ca")
    outcome = await service.deliver(opened.plan)

    assert opened.plan.situation is PresentationSituation.VISUAL_COMMAND
    assert opened.plan.disposition is OutputDisposition.VISUAL_ONLY
    assert outcome.speaks is False
    assert outcome.speech_kind is None
    for kind in (SpeechKind.ACK, SpeechKind.PROGRESS, SpeechKind.RESULT):
        assert not may_speak(PresentationSituation.VISUAL_COMMAND, kind)


@pytest.mark.asyncio
async def test_une_vraie_question_peut_parler() -> None:
    store = build_store()
    say(store, 1, "la marge est a douze pourcent")
    clock = S10Clock()
    service = build_service(store, clock=clock)

    opened = open_turn(service, clock, "pourquoi la marge baisse ?")
    outcome = await service.deliver(opened.plan)

    assert opened.plan.situation is PresentationSituation.KNOWLEDGE_QUESTION
    assert opened.plan.disposition is OutputDisposition.VISUAL_AND_VOICE
    assert opened.plan.action is AddressedTurnAction.ASK_BRAIN
    assert may_speak(PresentationSituation.KNOWLEDGE_QUESTION, SpeechKind.RESULT)
    assert outcome.delivered and outcome.code == "addressed_brain_turn"
    assert service.counters.brain_turns == 1


def test_une_demande_explicite_de_parole_reste_vocale() -> None:
    clock = S10Clock()
    store = build_store()
    say(store, 1, "le total du trimestre")
    service = build_service(store, clock=clock)

    opened = open_turn(service, clock, "dis-moi le total")

    assert opened.plan.situation is PresentationSituation.EXPLICIT_SPEAK_REQUEST
    assert opened.plan.disposition is OutputDisposition.VOICE_ONLY
    assert opened.plan.action is AddressedTurnAction.ASK_BRAIN


def test_la_disposition_du_tour_est_exactement_celle_de_la_matrice() -> None:
    """Aucune seconde vérité : la ligne de matrice est la seule source."""

    for situation, policy in PRESENTATION_POLICY.items():
        assert policy_for(situation).disposition is policy.disposition
    store = build_store()
    say(store, 1, "un enonce quelconque")
    for text, situation in (
        ("montre-moi le bilan", PresentationSituation.VISUAL_COMMAND),
        ("pourquoi la marge baisse", PresentationSituation.KNOWLEDGE_QUESTION),
        ("dis-moi le total", PresentationSituation.EXPLICIT_SPEAK_REQUEST),
    ):
        clock = S10Clock()
        service = build_service(store, clock=clock)
        opened = open_turn(service, clock, text)
        assert opened.plan.situation is situation
        assert opened.plan.disposition is policy_for(situation).disposition


@pytest.mark.asyncio
async def test_la_clarification_est_audible_parce_que_la_matrice_le_dit() -> None:
    """La Slice 07 a mis `QUESTION` dans les natures de sûreté de `VISUAL_COMMAND`.

    Si cette ligne bougeait, ce test tomberait ici — et non dans un silence
    constaté trois mois plus tard par un utilisateur sans écran ni phrase.
    """

    assert admit_presentation_speech(
        situation=PresentationSituation.VISUAL_COMMAND, kind=SpeechKind.QUESTION
    ).admitted

    store = build_store()
    say(store, 1, "compare les deux scenarios")
    topic(store, "u-001")
    resource(store, "u-001", resource_id="r-a", locator="scene:obj-a")
    resource(store, "u-001", resource_id="r-b", locator="scene:obj-b")
    clock = S10Clock()
    journal = S10Journal()
    service = build_service(store, clock=clock, speculative=S10Speculative(), journal=journal)

    opened = open_turn(service, clock, "montre-moi ca")
    outcome = await service.deliver(opened.plan)

    assert opened.plan.action is AddressedTurnAction.CLARIFY
    assert outcome.speaks is True
    assert outcome.speech_kind is SpeechKind.QUESTION
    assert service.counters.clarified == 1
    assert "addressed_clarification" in journal.codes()


@pytest.mark.asyncio
async def test_une_politique_qui_refuse_la_clarification_fait_rafraichir_pas_taire() -> None:
    """La garde est **atteignable** : l'admission est un champ injectable.

    C'est la forme que la Slice 07 a donnée à son propre classement — une garde
    qu'aucun test ne peut faire échouer n'est pas une garde.
    """

    store = build_store()
    say(store, 1, "compare les deux scenarios")
    topic(store, "u-001")
    resource(store, "u-001", resource_id="r-a", locator="scene:obj-a")
    resource(store, "u-001", resource_id="r-b", locator="scene:obj-b")
    clock = S10Clock()
    speculative = S10Speculative()
    journal = S10Journal()
    service = build_service(
        store, clock=clock, speculative=speculative, journal=journal,
        admit=lambda **_: PresentationSpeechVerdict(False, None, "policy_forbids"),
    )

    opened = open_turn(service, clock, "montre-moi ca")
    assert opened.plan.action is AddressedTurnAction.CLARIFY, "la garde n'est pas atteinte"
    outcome = await service.deliver(opened.plan)

    assert outcome.action is AddressedTurnAction.REFRESH
    assert outcome.speaks is False
    assert service.counters.clarification_withheld == 1
    assert len(speculative.reserves) == 1
    assert "addressed_clarification_withheld" in journal.codes(level="warning")


@pytest.mark.asyncio
async def test_une_admission_de_parole_en_panne_ne_montre_pas_le_mauvais_ecran() -> None:
    store = build_store()
    say(store, 1, "compare les deux scenarios")
    topic(store, "u-001")
    resource(store, "u-001", resource_id="r-a", locator="scene:obj-a")
    resource(store, "u-001", resource_id="r-b", locator="scene:obj-b")
    clock = S10Clock()
    journal = S10Journal()

    def boom(**_):  # noqa: ANN003
        raise RuntimeError("politique cassee")

    service = build_service(store, clock=clock, speculative=S10Speculative(),
                            journal=journal, admit=boom)

    opened = open_turn(service, clock, "montre-moi ca")
    assert opened.plan.action is AddressedTurnAction.CLARIFY, "la garde n'est pas atteinte"
    outcome = await service.deliver(opened.plan)

    assert outcome.action is AddressedTurnAction.REFRESH
    assert "addressed_clarification_failed" in journal.codes(level="error")
    assert "politique cassee" not in journal.blob()


def test_une_situation_non_visuelle_ne_resout_aucune_ressource() -> None:
    """Le module ne rapproche pas un nom d'une ressource ; il le dit."""

    store = build_store()
    say(store, 1, "voici la courbe")
    topic(store, "u-001")
    resource(store, "u-001")
    clock = S10Clock()
    service = build_service(store, clock=clock)

    opened = open_turn(service, clock, "pourquoi cette courbe baisse ?")

    assert opened.plan.context.resource.verdict is ResourceVerdict.NOT_REQUESTED
    assert opened.plan.action is AddressedTurnAction.ASK_BRAIN


def test_une_commande_visuelle_nommee_laisse_le_cerveau_resoudre() -> None:
    store = build_store()
    say(store, 1, "voici la courbe")
    topic(store, "u-001")
    resource(store, "u-001")
    clock = S10Clock()
    service = build_service(store, clock=clock)

    opened = open_turn(service, clock, "montre-moi le bilan Q3")

    assert opened.plan.situation is PresentationSituation.VISUAL_COMMAND
    assert opened.plan.context.resource.verdict is ResourceVerdict.NOT_REQUESTED
    assert opened.plan.context.resource.code == "addressed_no_deictic"
    assert opened.plan.action is AddressedTurnAction.ASK_BRAIN


def test_decide_action_couvre_tous_les_verdicts() -> None:
    expected = {
        ResourceVerdict.REUSABLE: AddressedTurnAction.SHOW_PREPARED,
        ResourceVerdict.AMBIGUOUS: AddressedTurnAction.CLARIFY,
        ResourceVerdict.NOT_REQUESTED: AddressedTurnAction.ASK_BRAIN,
        ResourceVerdict.STALE: AddressedTurnAction.REFRESH,
        ResourceVerdict.ABSENT: AddressedTurnAction.REFRESH,
    }
    assert set(expected) == set(ResourceVerdict)
    for verdict, action in expected.items():
        resolution = (
            ResourceResolution(verdict, resource_id="r-1")
            if verdict is ResourceVerdict.REUSABLE
            else ResourceResolution(verdict)
        )
        assert decide_action(PresentationSituation.VISUAL_COMMAND, resolution) is action
        assert decide_action(PresentationSituation.KNOWLEDGE_QUESTION, resolution) is AddressedTurnAction.ASK_BRAIN


# ==========================================================================
# 8. Le runtime reste en PRESENTATION
# ==========================================================================


@pytest.mark.asyncio
async def test_apres_le_tour_la_seance_reste_en_presentation_ambiante() -> None:
    """Le tour adressé est un épisode, pas une parenthèse assistant."""

    store = build_store()
    say(store, 1, "voici la courbe")
    topic(store, "u-001")
    resource(store, "u-001")
    clock = S10Clock()
    mode = [InteractionMode.PRESENTATION]
    journal = S10Journal()
    service = build_service(store, clock=clock, speculative=S10Speculative(),
                            mode=lambda: mode[0], journal=journal)
    generation_before = store.generation

    opened = open_turn(service, clock, "montre-moi ca")
    await service.deliver(opened.plan)
    settlement = service.conclude("corr-1")

    assert settlement.still_presentation is True
    assert settlement.session_active is True
    assert settlement.session_id == SESSION
    assert settlement.mode is InteractionMode.PRESENTATION
    assert store.generation == generation_before
    assert store.snapshot.session_id == SESSION
    assert store.active is True
    assert "addressed_turn_settled" in journal.codes()
    # Un second tour part immédiatement : la voie est toujours armable.
    assert service.arm(trigger(clock, sequence=1)).applied


def test_conclure_ne_retire_rien_du_magasin() -> None:
    store = build_store()
    say(store, 1, "une phrase")
    clock = S10Clock()
    service = build_service(store, clock=clock)
    revision_before = store.revision

    service.conclude("corr-1")

    assert store.revision == revision_before
    assert store.snapshot.tail.entries
    assert store.active


def test_quitter_la_presentation_est_dit_et_pas_pretendu() -> None:
    store = build_store()
    clock = S10Clock()
    mode = [InteractionMode.PRESENTATION]
    journal = S10Journal()
    service = build_service(store, clock=clock, mode=lambda: mode[0], journal=journal)

    mode[0] = InteractionMode.ASSISTANT
    settlement = service.conclude("corr-1")

    assert settlement.still_presentation is False
    assert settlement.mode is InteractionMode.ASSISTANT
    assert service.counters.settled_outside_presentation == 1
    assert "addressed_turn_left_presentation" in journal.codes(level="warning")


def test_reunion_ne_se_comporte_pas_comme_presentation() -> None:
    """`behaving_interaction_mode` : REUNION n'a aucun comportement en V1."""

    service = build_service(mode=lambda: InteractionMode.MEETING)
    result = service.arm(trigger(S10Clock()))
    assert result.code == "addressed_mode_not_presentation"
    assert service.conclude().still_presentation is False


def test_un_mode_illisible_retombe_sur_assistant() -> None:
    def boom():
        raise RuntimeError("mode injoignable")

    journal = S10Journal()
    service = build_service(mode=boom, journal=journal)
    result = service.arm(trigger(S10Clock()))

    assert result.code == "addressed_mode_not_presentation"
    assert "addressed_mode_unreadable" in journal.codes(level="error")
    assert "mode injoignable" not in journal.blob()


def test_quitter_la_presentation_en_cours_de_tour_ferme_la_fenetre() -> None:
    store = build_store()
    say(store, 1, "montre-moi ca")
    clock = S10Clock()
    mode = [InteractionMode.PRESENTATION]
    service = build_service(store, clock=clock, mode=lambda: mode[0])
    service.arm(trigger(clock))

    mode[0] = InteractionMode.ASSISTANT
    result = service.open("montre-moi ca", correlation_id="corr-1")

    assert result.disposition is VoiceStateDisposition.IGNORED
    assert result.code == "addressed_mode_not_presentation"
    assert not service.armed


def test_une_seance_retiree_ferme_le_tour() -> None:
    store = build_store()
    say(store, 1, "montre-moi ca")
    clock = S10Clock()
    service = build_service(store, clock=clock)
    service.arm(trigger(clock))

    store.retire("test")
    result = service.open("montre-moi ca", correlation_id="corr-1")

    assert result.code == "addressed_working_set_inactive"


# ==========================================================================
# 9. Pannes — « X ne lève jamais » est un cas de test
# ==========================================================================


def test_un_magasin_dont_l_instantane_leve_donne_un_refus_type() -> None:
    clock = S10Clock()
    journal = S10Journal()
    service = build_service(S10BrokenStore(on="snapshot"), clock=clock, journal=journal)

    armed = service.arm(trigger(clock))

    assert armed.disposition is VoiceStateDisposition.IGNORED
    assert service.counters.store_failures >= 1
    assert "addressed_snapshot_unreadable" in journal.codes(level="error")
    assert "instantane illisible" not in journal.blob()


def test_une_memoire_des_retraits_illisible_interdit_toute_reutilisation() -> None:
    """Ne rien savoir des retraits n'autorise pas à montrer."""

    broken = S10BrokenStore(on="retired")
    say(broken.inner, 1, "voici la courbe")
    topic(broken.inner, "u-001")
    resource(broken.inner, "u-001")
    clock = S10Clock()
    journal = S10Journal()
    service = build_service(broken, clock=clock, journal=journal)

    # Témoin : avec le même magasin en état de marche, la ressource **serait**
    # réutilisée. Sans ce témoin, le refus ne prouverait rien.
    control_clock = S10Clock()
    control = build_service(broken.inner, clock=control_clock)
    assert open_turn(
        control, control_clock, "montre-moi ca", correlation_id="corr-temoin"
    ).plan.context.resource.verdict is ResourceVerdict.REUSABLE

    opened = open_turn(service, clock, "montre-moi ca")

    assert opened.plan.context.resource.verdict is ResourceVerdict.STALE
    assert opened.plan.context.resource.code == "addressed_retired_unreadable"
    assert opened.plan.action is AddressedTurnAction.REFRESH
    assert "addressed_retired_unreadable" in journal.codes(level="error")


def test_une_memoire_des_retraits_en_chaine_n_est_pas_un_ensemble_de_lettres() -> None:
    """Une `str` itérée donnerait un ensemble de **lettres** : un mauvais
    résultat portant la forme d'un bon, ce que la Slice 09 a payé une fois."""

    broken = S10BrokenStore(on="retired_str")
    say(broken.inner, 1, "voici la courbe")
    topic(broken.inner, "u-001")
    resource(broken.inner, "u-001")
    clock = S10Clock()
    journal = S10Journal()
    service = build_service(broken, clock=clock, journal=journal)

    control_clock = S10Clock()
    control = build_service(broken.inner, clock=control_clock)
    assert open_turn(
        control, control_clock, "montre-moi ca", correlation_id="corr-temoin"
    ).plan.context.resource.verdict is ResourceVerdict.REUSABLE

    opened = open_turn(service, clock, "montre-moi ca")

    assert opened.plan.context.resource.verdict is ResourceVerdict.STALE
    assert "addressed_retired_untyped" in journal.codes(level="error")


@pytest.mark.asyncio
async def test_un_magasin_qui_leve_au_rechauffement_fait_rafraichir() -> None:
    broken = S10BrokenStore(on="use")
    say(broken.inner, 1, "voici le tableau")
    topic(broken.inner, "u-001")
    resource(broken.inner, "u-001", resource_id="r-tableau", kind=ResourceKind.DOCUMENT,
             locator="doc:synthese")
    clock = S10Clock()
    journal = S10Journal()
    service = build_service(broken, clock=clock, speculative=S10Speculative(), journal=journal)

    opened = open_turn(service, clock, "montre-moi ca")
    assert opened.plan.action is AddressedTurnAction.SHOW_PREPARED, "la garde n'est pas atteinte"
    outcome = await service.deliver(opened.plan)

    assert outcome.action is AddressedTurnAction.REFRESH
    assert service.counters.store_failures >= 1
    assert "addressed_store_failed" in journal.codes(level="error")
    assert "magasin en panne" not in journal.blob()


def test_un_classement_en_panne_retombe_sur_la_parole() -> None:
    """Le repli est la parole, jamais le silence : une panne d'analyse ne doit
    pas devenir un JARVIS muet (position de la Slice 07)."""

    def boom(_text):  # noqa: ANN001
        raise RuntimeError("classement casse")

    store = build_store()
    say(store, 1, "montre-moi ca")
    clock = S10Clock()
    journal = S10Journal()
    service = build_service(store, clock=clock, journal=journal, classify=boom)

    opened = open_turn(service, clock, "montre-moi ca")

    assert opened.plan.situation is PresentationSituation.KNOWLEDGE_QUESTION
    assert opened.plan.context.evidence == "classification_failed"
    assert service.counters.classification_failures == 1
    assert "addressed_classification_failed" in journal.codes(level="warning")
    assert "classement casse" not in journal.blob()


def test_un_classement_hors_contrat_retombe_aussi_sur_la_parole() -> None:
    store = build_store()
    say(store, 1, "montre-moi ca")
    clock = S10Clock()
    journal = S10Journal()
    service = build_service(store, clock=clock, journal=journal,
                            classify=lambda _text: ("visual_command", "bidon"))

    opened = open_turn(service, clock, "montre-moi ca")

    assert opened.plan.situation is PresentationSituation.KNOWLEDGE_QUESTION
    assert "addressed_classification_untyped" in journal.codes(level="warning")


@pytest.mark.asyncio
async def test_un_journal_en_panne_ne_decide_pas_d_un_tour() -> None:
    store = build_store()
    say(store, 1, "voici la courbe")
    topic(store, "u-001")
    resource(store, "u-001")
    clock = S10Clock()
    journal = S10Journal(fail=True)
    service = build_service(store, clock=clock, speculative=S10Speculative(), journal=journal)

    opened = open_turn(service, clock, "montre-moi ca")
    outcome = await service.deliver(opened.plan)
    settlement = service.conclude("corr-1")

    assert opened.applied and outcome.delivered and settlement.still_presentation
    assert service.counters.diagnostic_failures > 0
    assert journal.entries == []


def test_une_horloge_qui_leve_refuse_le_tour_plutot_que_d_inventer() -> None:
    def boom():
        raise RuntimeError("horloge cassee")

    journal = S10Journal()
    service = PresentationAddressedTurnService(
        store=build_store(), clock=boom, diagnostics=journal,
    )
    result = service.arm(
        ExplicitAddressTrigger(ExplicitAddressSource.MANUAL_KEY, "f9", 10_000.0, 0)
    )

    assert result.disposition is VoiceStateDisposition.REJECTED
    assert result.code == "addressed_clock_unreadable"
    assert "horloge cassee" not in journal.blob()


def test_une_horloge_hors_type_refuse_le_tour() -> None:
    service = PresentationAddressedTurnService(store=build_store(), clock=lambda: "maintenant")
    result = service.arm(
        ExplicitAddressTrigger(ExplicitAddressSource.MANUAL_KEY, "f9", 10_000.0, 0)
    )
    assert result.code == "addressed_clock_unreadable"


def test_les_sept_dispositions_du_magasin_sont_pre_declarees() -> None:
    """Un compteur qui n'apparaît qu'une fois rencontré ne distingue pas
    « jamais arrivé » de « jamais compté »."""

    table = build_service().counters.store_dispositions
    assert set(table) == {item.value for item in VoiceStateDisposition}
    assert len(table) == 7
    assert set(table.values()) == {0}


def test_une_disposition_de_magasin_inconnue_est_dite_et_pas_rangee_par_defaut() -> None:
    """Leçon `ambient_disposition_unknown` de la Slice 06."""

    class Alien:
        disposition = "quelque_chose_de_neuf"
        code = "alien"

    journal = S10Journal()
    service = build_service(journal=journal)
    name = service._account_store(Alien())

    assert name == "quelque_chose_de_neuf"
    assert service.counters.store_dispositions["quelque_chose_de_neuf"] == 1
    assert "addressed_store_disposition_unknown" in journal.codes(level="error")


def test_chaque_disposition_du_magasin_est_comptee_sous_son_propre_nom() -> None:
    service = build_service()
    for disposition in VoiceStateDisposition:
        service._account_store(
            type("R", (), {"disposition": disposition, "code": "x"})()
        )
    assert all(value == 1 for value in service.counters.store_dispositions.values())


# ==========================================================================
# 10. La projection
# ==========================================================================


def test_la_projection_porte_la_parole_recente_et_le_motif_d_attention() -> None:
    """C'est tout l'objet de D06 — et la réponse à « qu'est-ce que tu as trouvé ? »."""

    store = build_store()
    say(store, 1, "la marge est a douze pourcent")
    say(store, 2, "montre-moi ca")
    topic(store, "u-001")
    apply(
        store,
        AttentionItem(
            attention_id="a-1", category=AttentionCategory.CONTRADICTION,
            severity=AttentionSeverity.WARNING, confidence=0.8,
            raised_at=NOW + timedelta(seconds=70),
            reason="la source publique dit neuf pourcent",
        ),
        observation_id="obs-attention",
    )
    clock = S10Clock()
    service = build_service(store, clock=clock)

    opened = open_turn(service, clock, "montre-moi ca")
    payload = opened.plan.context.to_brain_context()

    assert [item["text"] for item in payload["recent_speech"]] == [
        "la marge est a douze pourcent", "montre-moi ca",
    ]
    assert payload["attention"][0]["reason"] == "la source publique dit neuf pourcent"
    assert payload["authorizes_actions"] is False


def test_aucune_parole_n_entre_dans_une_ligne_de_journal() -> None:
    """Phrase plantée dans les trois champs qui peuvent porter du dit, puis
    toute la voie conduite : fil, motif d'attention, affirmation."""

    marker = "confidentiel-marmotte-42"
    store = build_store()
    say(store, 1, f"le chiffre {marker} vient du rapport interne")
    say(store, 2, "montre-moi ca")
    topic(store, "u-001", label=f"sujet {marker}")
    apply(
        store,
        PresentationClaim(
            claim_id="c-1", statement=f"affirmation contenant {marker}",
            provenance=provenance(store, "u-001"),
            first_seen_at=NOW + timedelta(seconds=60), last_seen_at=NOW + timedelta(seconds=60),
        ),
        observation_id="obs-claim",
    )
    apply(
        store,
        AttentionItem(
            attention_id="a-1", category=AttentionCategory.CONTRADICTION,
            severity=AttentionSeverity.WARNING, confidence=0.8,
            raised_at=NOW + timedelta(seconds=70), reason=f"motif {marker}",
        ),
        observation_id="obs-attention",
    )
    clock = S10Clock()
    journal = S10Journal()
    speculative = S10Speculative()
    service = build_service(store, clock=clock, speculative=speculative, journal=journal)

    opened = open_turn(service, clock, f"montre-moi ca et le {marker}")
    outcome = asyncio.run(service.deliver(opened.plan))
    service.note_visible_reaction("corr-1")
    service.conclude("corr-1")

    assert opened.applied and outcome is not None
    assert journal.entries, "la voie doit avoir parlé dans son journal"
    assert marker not in journal.blob()
    assert marker in json.dumps(opened.plan.context.to_brain_context(), ensure_ascii=False)
    assert marker not in json.dumps(opened.plan.to_trace_payload(), ensure_ascii=False)


def test_aucun_serialiseur_d_instantane_n_est_appele_par_la_slice() -> None:
    """Lecture de **source** : prouver l'**absence** d'un appel.

    Précondition laissée par la Slice 09 : `reason` est le seul champ qui puisse
    transporter de la parole de salle, et il traverse déjà
    `AttentionItem.to_payload()` → `PresentationWorkingSet.to_payload()` →
    `PresentationContextSnapshot.to_payload()`. Tant que rien n'appelait ces
    sérialiseurs la contrainte tenait *par absence*. Cette Slice est celle qui
    voulait lire `reason` : elle le lit sur l'objet, en mémoire, et n'appelle
    aucun `to_payload`. Aucun test de comportement ne sait prouver ça.

    Ne pas supprimer au motif que « les tests n'inspectent pas la source ».
    """

    offenders = []
    for relative in (
        Path("jarvis") / "domain" / "presentation_addressed_turn.py",
        Path("jarvis") / "core" / "presentation_addressed_turn.py",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "to_payload"
            ):
                offenders.append(f"{relative.as_posix()}:{node.lineno}")
    assert not offenders, f"un sérialiseur d'instantané est appelé : {offenders}"


def test_la_projection_tient_dans_son_budget_et_nomme_ce_qu_elle_coupe() -> None:
    """Une section absente et une section vide ne doivent pas se lire pareil."""

    store = build_store()
    for index in range(1, 13):
        say(store, index, f"phrase numero {index} " + "x" * 300)
    topic(store, "u-012")
    for index in range(6):
        apply(
            store,
            PresentationEntity(
                entity_id=f"e-{index}", label="entite " + "y" * 80, kind="chiffre",
                provenance=provenance(store, "u-012"),
                first_seen_at=NOW + timedelta(seconds=60), last_seen_at=NOW + timedelta(seconds=60),
            ),
            observation_id=f"obs-e-{index}",
        )
        apply(
            store,
            OpenQuestion(
                question_id=f"q-{index}", text="question " + "z" * 180,
                provenance=provenance(store, "u-012"), asked_at=NOW + timedelta(seconds=60),
            ),
            observation_id=f"obs-q-{index}",
        )

    snapshot = store.snapshot
    context = build_addressed_turn_context(
        snapshot, situation=PresentationSituation.VISUAL_COMMAND, evidence="visual_verb:montre",
        deictic="ca", referent=resolve_referent(snapshot),
        resource=ResourceResolution(ResourceVerdict.ABSENT, code="x"), budget=4000,
    )

    assert context.chars <= 4000
    assert len(context.clipped) >= 2, "une seule section coupée ne prouve pas un ordre"
    assert context.clipped[:2] == ("questions", "entities")
    assert "topics" not in context.clipped, "les sujets tombent après, pas avant"
    assert len(context.tail) == MAX_ADDRESSED_TAIL_ENTRIES, "le fil n'a pas eu à être touché"
    assert context.topics, "les sujets ont survécu à ce budget"
    for name in context.clipped:
        if name != "tail":
            assert not getattr(context, name), f"{name} est annoncée coupée sans l'être"


def test_le_fil_est_la_derniere_section_a_tomber() -> None:
    """D06 : une projection sans parole récente serait le contexte périmé que
    cette Slice existe pour écarter."""

    store = build_store()
    for index in range(1, 6):
        say(store, index, f"phrase numero {index} " + "w" * 400)
    snapshot = store.snapshot
    context = build_addressed_turn_context(
        snapshot, situation=PresentationSituation.VISUAL_COMMAND, evidence="e", deictic="ca",
        referent=resolve_referent(snapshot),
        resource=ResourceResolution(ResourceVerdict.ABSENT, code="x"), budget=700,
    )

    assert "tail" in context.clipped
    assert len(context.tail) == 1
    assert context.tail[0][0] == "u-005", "la parole gardée est la plus récente"


def test_la_projection_borne_le_fil_meme_sans_pression_de_budget() -> None:
    store = build_store()
    for index in range(1, 13):
        say(store, index, f"phrase {index}")
    snapshot = store.snapshot
    context = build_addressed_turn_context(
        snapshot, situation=PresentationSituation.VISUAL_COMMAND, evidence="e", deictic="ca",
        referent=resolve_referent(snapshot),
        resource=ResourceResolution(ResourceVerdict.ABSENT, code="x"),
    )
    assert len(context.tail) == MAX_ADDRESSED_TAIL_ENTRIES
    # Et ce sont les **plus récentes**. Compter huit entrées ne dit pas
    # lesquelles : une projection des huit plus anciennes est exactement le
    # contexte périmé que D06 existe pour écarter, et elle compte pareil.
    assert [item[0] for item in context.tail] == [f"u-{index:03d}" for index in range(5, 13)]
    assert [item[1] for item in context.tail] == list(range(5, 13))
    assert context.clipped == ()


def test_la_projection_refuse_un_instantane_hors_type() -> None:
    with pytest.raises(PresentationAddressedTurnError) as excinfo:
        build_addressed_turn_context(
            "pas un instantane", situation=PresentationSituation.VISUAL_COMMAND,
            evidence="e", deictic="", referent=None,
            resource=ResourceResolution(ResourceVerdict.ABSENT),
        )
    assert excinfo.value.code == "addressed_context_snapshot_invalid"


def test_la_projection_refuse_une_situation_hors_type() -> None:
    with pytest.raises(PresentationAddressedTurnError) as excinfo:
        build_addressed_turn_context(
            build_store().snapshot, situation="visual_command",  # type: ignore[arg-type]
            evidence="e", deictic="", referent=None,
            resource=ResourceResolution(ResourceVerdict.ABSENT),
        )
    assert excinfo.value.code == "addressed_context_situation_invalid"


def test_une_projection_de_contexte_n_autorise_jamais_une_action() -> None:
    """D03, sur le type : `authorizes_actions` est un `ClassVar` figé."""

    store = build_store()
    say(store, 1, "une phrase")
    snapshot = store.snapshot
    context = build_addressed_turn_context(
        snapshot, situation=PresentationSituation.VISUAL_COMMAND, evidence="e", deictic="",
        referent=resolve_referent(snapshot),
        resource=ResourceResolution(ResourceVerdict.ABSENT),
    )
    assert context.authorizes_actions is False
    assert dataclasses.replace(context).authorizes_actions is False
    assert AddressedTurnContext.authorizes_actions is False
    assert AddressedWindow.authorizes_actions is False


def test_le_budget_par_defaut_est_celui_annonce() -> None:
    """Le budget de prompt appartient à cette Slice (doc de la Slice 04)."""

    from jarvis.domain.brain_context import MAX_BRAIN_WORK_CONTEXT_CHARS

    assert MAX_ADDRESSED_CONTEXT_CHARS == MAX_BRAIN_WORK_CONTEXT_CHARS


def test_un_budget_hors_type_retombe_sur_le_defaut_sans_lever() -> None:
    store = build_store()
    say(store, 1, "une phrase")
    snapshot = store.snapshot
    for bad in (0, -5, True, "gros", None):
        context = build_addressed_turn_context(
            snapshot, situation=PresentationSituation.VISUAL_COMMAND, evidence="e",
            deictic="", referent=resolve_referent(snapshot),
            resource=ResourceResolution(ResourceVerdict.ABSENT), budget=bad,  # type: ignore[arg-type]
        )
        assert context.chars <= MAX_ADDRESSED_CONTEXT_CHARS


# ==========================================================================
# 11. Télémétrie de latence
# ==========================================================================


def test_la_latence_d_admission_part_de_l_estampille_du_declencheur() -> None:
    clock = S10Clock(1000.0)
    store = build_store()
    say(store, 1, "montre-moi ca")
    journal = S10Journal()
    service = build_service(store, clock=clock, journal=journal)

    service.arm(trigger(clock), correlation_id="corr-1")
    clock.advance(0.037)
    opened = service.open("montre-moi ca", correlation_id="corr-1")

    assert opened.plan.admission_latency_ms == pytest.approx(37.0, abs=0.2)
    latency_lines = [
        entry for entry in journal.entries if entry["kind"] == f"{ADDRESSED_KIND}.latency"
    ]
    assert latency_lines
    assert latency_lines[0]["data"]["measure"] == TRIGGER_TO_ADMISSION  # type: ignore[index]


def test_les_reactions_se_mesurent_depuis_le_meme_declencheur() -> None:
    clock = S10Clock(1000.0)
    store = build_store()
    say(store, 1, "montre-moi ca")
    journal = S10Journal()
    service = build_service(store, clock=clock, journal=journal)

    armed = service.arm(trigger(clock), correlation_id="corr-1")
    clock.advance(0.010)
    opened = service.open("montre-moi ca", correlation_id="corr-1")
    clock.advance(0.040)
    visible = service.note_visible_reaction("corr-1")
    clock.advance(0.100)
    audible = service.note_audible_reaction("corr-1")

    assert armed.applied and isinstance(opened.plan, AddressedTurnPlan)
    assert visible == pytest.approx(50.0, abs=0.2)
    assert audible == pytest.approx(150.0, abs=0.2)
    assert audible > visible
    # Les trois mesures portent leur propre nom : une seule grandeur rendue
    # trois fois ne dirait rien de plus qu'une.
    measures = [
        entry["data"]["measure"]  # type: ignore[index]
        for entry in journal.entries if entry["kind"] == f"{ADDRESSED_KIND}.latency"
    ]
    assert measures == [TRIGGER_TO_ADMISSION, TRIGGER_TO_VISIBLE, TRIGGER_TO_AUDIBLE]


def test_une_reaction_sans_mesure_ouverte_ne_rend_rien() -> None:
    """`None` est un cas normal, pas une anomalie : rien à fermer."""

    service = build_service()
    assert service.note_visible_reaction("inconnue") is None
    assert service.note_audible_reaction("") is None


def test_une_horloge_en_retard_sur_le_declencheur_ne_produit_aucune_latence() -> None:
    """Un `None` dit « on ne sait pas » ; un zéro dirait « c'était instantané »."""

    clock = S10Clock(1000.0)
    store = build_store()
    say(store, 1, "montre-moi ca")
    journal = S10Journal()
    service = build_service(store, clock=clock, journal=journal)
    stamped = ExplicitAddressTrigger(ExplicitAddressSource.MANUAL_KEY, "f9", 1_000_000.0, 0)

    armed = service.arm(stamped, correlation_id="corr-1")
    opened = service.open("montre-moi ca", correlation_id="corr-1")

    assert armed.applied and opened.applied
    assert opened.plan.admission_latency_ms is None
    assert service.counters.latency_clock_mismatch >= 1
    assert "addressed_latency_clock_mismatch" in journal.codes(level="warning")


def test_conclure_libere_les_mesures_restees_ouvertes() -> None:
    clock = S10Clock()
    store = build_store()
    say(store, 1, "montre-moi ca")
    service = build_service(store, clock=clock)
    open_turn(service, clock, "montre-moi ca")

    assert service.stats()["latency_pending"] == 2
    service.conclude("corr-1")
    assert service.stats()["latency_pending"] == 0


def test_les_mesures_de_la_slice_ne_polluent_pas_l_inventaire_realtime_brain() -> None:
    """`LATENCY_MEASURES` est l'inventaire des six mesures du handoff
    realtime-brain, consommé par le testlab. Trois de plus l'auraient cassé."""

    assert len(LATENCY_MEASURES) == 6
    assert not set(ADDRESSED_LATENCY_MEASURES) & set(LATENCY_MEASURES)
    assert len(set(ADDRESSED_LATENCY_MEASURES)) == 3


def test_le_chronometre_partage_garde_son_comportement_par_defaut() -> None:
    """`mark(at=)` est une extension ; sans `at`, rien ne bouge."""

    ticks = iter([100.0, 100.5, 200.0, 200.25])
    tracker = LatencyTracker(clock=lambda: next(ticks))
    tracker.mark("m", "k")
    assert tracker.measure("m", "k", kind="test") == pytest.approx(500.0)
    tracker.mark("m", "k", at=199.0)
    assert tracker.measure("m", "k", kind="test") == pytest.approx(1000.0)


# ==========================================================================
# 12. Observabilité
# ==========================================================================


def test_le_chemin_normal_est_journalise_autant_que_les_refus() -> None:
    """Sinon « rien dans le journal » voudrait dire à la fois « tout va bien »
    et « plus rien ne rentre »."""

    store = build_store()
    say(store, 1, "voici la courbe")
    topic(store, "u-001")
    resource(store, "u-001")
    clock = S10Clock()
    journal = S10Journal()
    service = build_service(store, clock=clock, speculative=S10Speculative(), journal=journal)

    opened = open_turn(service, clock, "montre-moi ca")
    asyncio.run(service.deliver(opened.plan))
    service.conclude("corr-1")

    kinds = set(journal.kinds())
    for event in ("armed", "opened", "reused", "settled"):
        assert f"{ADDRESSED_KIND}.{event}" in kinds
    assert all(entry["level"] == "info" for entry in journal.entries)


def test_un_refus_est_journalise_plutot_que_muet() -> None:
    journal = S10Journal()
    service = build_service(journal=journal)
    service.open("montre-moi ca", correlation_id="corr-1")

    assert "addressed_no_window" in journal.codes()
    assert service.counters.refused == 1


def test_les_compteurs_disent_tout_ce_qui_s_est_passe() -> None:
    clock = S10Clock()
    store = build_store()
    say(store, 1, "montre-moi ca")
    service = build_service(store, clock=clock)
    open_turn(service, clock, "montre-moi ca")

    payload = service.stats()
    assert payload["armed"] is False
    assert payload["counters"]["armed"] == 1
    assert payload["counters"]["opened"] == 1
    assert set(payload["measures"]) == set(ADDRESSED_LATENCY_MEASURES)
    assert json.dumps(payload, ensure_ascii=False, default=repr)


def test_le_plan_se_journalise_sans_parole() -> None:
    clock = S10Clock()
    store = build_store()
    say(store, 1, "la phrase secrete du presentateur")
    service = build_service(store, clock=clock)
    opened = open_turn(service, clock, "montre-moi ca")

    payload = opened.plan.to_trace_payload()
    assert payload["deictic"] is True
    assert payload["tail_entries"] == 1
    assert "secrete" not in json.dumps(payload, ensure_ascii=False)
