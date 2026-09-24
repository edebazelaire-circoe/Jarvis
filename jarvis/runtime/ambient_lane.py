"""La lane ambiante : la salle devient du texte récent, et rien de plus.

Ce module est le **producteur** que `docs/presentation-working-set.md`
annonçait et que personne n'avait encore écrit. Il relie trois choses qui
existaient déjà séparément :

```text
AudioCaptureHub.subscribe(sample_rate=None, ...)   Slice 05, abonné *queued*
        -> AmbientSegmenter                        énonciations bornées
        -> TranscriptionBackend (port neutre)      jarvis/ports/transcription.py
        -> PresentationWorkingSetStore.observe()   Slice 04, le fil de séance
        -> analyse bon marché                      jarvis/domain/ambient_observation.py
        -> PresentationWorkingSetStore.apply()     l'ensemble de travail
```

Les cinq contraintes qui ont dicté la forme
-------------------------------------------

**D03 / G7 — l'ambiant n'est jamais un tour adressé.** Ce module n'importe ni
`BrainTurnInput`, ni `VoiceTurnAdmissionRequest`, ni `AddressingDecision`, ni
aucun service de cerveau ou d'outil ; il n'en a pas besoin, et un test de
graphe d'imports le vérifie. Ce qui sort d'ici est du texte pour le fil de
séance et des `AmbientTrigger` d'enquête, dont le type interdit l'autorisation
d'action. « Ouvre le fichier » entendu dans la salle produit exactement ce que
produirait « le fichier est ouvert » : au plus un sujet et une piste.

**D06 — le fil avant l'enrichissement.** `_transcribe_worker` appelle
`sink.observe()` **avant** de déposer quoi que ce soit sur la file d'analyse.
C'est l'ordre qui fait qu'un déictique (« montre-moi ça ») se résout sur la
dernière parole et pas sur la dernière chose comprise. L'analyse, même bon
marché, vit sur sa propre file : elle ne peut donc pas retarder la parole
suivante, jamais, pas même d'un tour de boucle.

**D04 / D08 — les lanes sont indépendantes et le spéculatif est sacrifiable.**
La lane ne détient aucune référence vers `ExplicitAddressLane`, n'attend rien
qui lui appartienne, et son abonnement au hub est **queued** : un abonné en
ligne lent affame ses voisins sur le thread de capture (mesuré dans la
Slice 05 : 10 blocs en 0,506 s), et la transcription est le consommateur le
plus lent du système. Toutes les files sont bornées, la politique est
`drop_oldest` — un consommateur en retard veut le présent, pas un arriéré
qu'il resservirait comme du frais — et **chaque rejet est compté**.

**Isolation des pannes.** Une transcription qui lève, qui expire, ou un
fournisseur absent : c'est compté, dit avec les mots de la panne réelle, et la
boucle continue. Rien de tout cela ne touche la touche manuelle ni le mot
d'éveil, qui vivent dans `PresentationAudioSession`. La lane ne se détache
jamais définitivement — un `AudioCaptureHub` détache un abonné en ligne
fautif, mais rendre PRESENTATION sourde pour le reste de la séance sur une
panne passagère serait exactement l'issue que cette politique existe pour
éviter ; elle passe donc en **dégradé**, le dit une fois, et continue.

**Aucun audio brut nulle part.** Le PCM vit dans le segmenteur et dans la file
de segments, tous deux bornés ; il sort vers le fournisseur sous forme de WAV
en mémoire et n'est écrit nulle part. Aucune ligne de journal de ce module ne
porte du texte de transcription ni un octet de PCM : uniquement des
identifiants, des comptes et des durées.

Une seule tâche transcrit
-------------------------

C'est délibéré et c'est un invariant : le fil de séance attribue le rang d'une
énonciation **au moment de l'appel** (`PresentationWorkingSetStore.observe`).
Deux transcriptions concurrentes rendraient donc l'ordre du fil dépendant de la
latence du fournisseur, et une phrase dite avant pourrait se ranger après. Le
parallélisme s'achèterait au prix de la seule chose que le fil garantit.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from jarvis.audio.ambient_segmenter import AmbientSegment, AmbientSegmenter
from jarvis.audio.capture import pcm16_to_wav
from jarvis.domain.ambient_observation import (
    AmbientAnalysis,
    AmbientTrigger,
    AmbientUtterance,
    analyse_ambient_text,
    clip_ambient_text,
    utc_now,
)
from jarvis.domain.messages import AudioClip
from jarvis.domain.presentation_working_set import (
    ClaimStatus,
    ObservationProvenance,
    OpenQuestion,
    PresentationClaim,
    PresentationEntity,
    PresentationObservation,
    PresentationTopic,
    UtteranceOrigin,
)
from jarvis.runtime.journal import RuntimeJournal

# --------------------------------------------------------------------------
# Budgets — chacun avec sa raison
# --------------------------------------------------------------------------

#: Blocs PCM gardés par l'abonnement au hub. 64 x 50 ms = 3,2 s. La tâche qui
#: les vide ne fait que de l'arithmétique d'énergie ; 3,2 s couvre une pause du
#: ramasse-miettes ou un ordonnancement contrarié sans perdre une phrase, et
#: pèse 150 Ko à 24 kHz.
DEFAULT_CAPTURE_BLOCKS = 64

#: Segments en attente de transcription. Trois, parce qu'un segment vaut au
#: plus 12 s : au-delà de ~36 s d'arriéré, le fil serait si en retard qu'un
#: déictique résolu dessus serait faux — exactement la péremption que D06
#: existe pour empêcher. Le plus ancien part en premier.
DEFAULT_SEGMENT_QUEUE = 3

#: Énonciations en attente d'analyse bon marché. Huit : l'analyse coûte des
#: microsecondes, cette file n'est là que pour absorber une rafale, et elle ne
#: doit jamais exercer de contre-pression sur le fil.
DEFAULT_ANALYSIS_QUEUE = 8

#: Au-delà, un fournisseur n'a plus rien d'utile à rendre : le plus gros
#: segment fait 12 s, et une réponse qui met plus de 20 s décrit une salle qui
#: a déjà changé de sujet. La tâche est libérée, le refus compté.
DEFAULT_TRANSCRIPTION_TIMEOUT_S = 20.0

#: Un segment qui a attendu si longtemps dans la file décrit de la parole qui
#: n'intéresse plus le fil : on l'écarte en le disant plutôt que de le ranger
#: derrière de la parole plus fraîche.
MAX_SEGMENT_AGE_S = 30.0

#: Combien d'échecs consécutifs avant de déclarer la lane dégradée. Trois, la
#: même valeur et la même raison que `MAX_CONSECUTIVE_SINK_FAILURES` du hub :
#: un ou deux décrivent un hoquet, trois décrivent une panne qui dure.
MAX_CONSECUTIVE_TRANSCRIPTION_FAILURES = 3

#: Balayage d'âge du magasin quand plus personne ne parle. `prune()` existe
#: pour ça (`docs/presentation-working-set.md` § Bornes) et c'est à la lane
#: ambiante, sur sa boucle de repos, de l'appeler.
IDLE_PRUNE_PERIOD_S = 30.0

#: Bornes journalisables, même règle que le Control Center et la Slice 04.
MAX_JOURNALLED_VALUE_CHARS = 64

AMBIENT_KIND = "presentation.ambient"


class AmbientLaneError(RuntimeError):
    """Refus nommé de la lane. `code` stable et anglais, message francophone."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PresentationObservationSink(Protocol):
    """Ce que la lane attend d'un magasin de séance.

    Structurellement satisfait par `jarvis.core.presentation_working_set.
    PresentationWorkingSetStore` **tel quel** : aucune méthode n'a été ajoutée
    à la Slice 04 pour ce raccord. Le protocole existe parce que Core et Voice
    sont deux processus (`jarvis core` / `jarvis voice`) et que la Slice 11
    devra peut-être glisser un relais ici ; il ne réécrit rien.
    """

    def observe(
        self, session_id: str, utterance_id: str, text: str, *,
        spoken_at: datetime | None = ..., origin: Any = ..., revision: int = ...,
    ) -> Any: ...

    def apply(self, observation: object) -> Any: ...

    def prune(self, now: datetime | None = ...) -> Any: ...

    @property
    def snapshot(self) -> Any: ...


class AmbientTranscriber(Protocol):
    """Le port de transcription du dépôt, cité ici pour l'intention.

    C'est **exactement** `jarvis.ports.transcription.TranscriptionBackend` : un
    `AudioClip` entre, un `TranscriptionResult` sort. Ce port existait déjà et
    n'est pas élargi — c'était la couture la moins dupliquée disponible, et le
    seul adaptateur du dépôt (`OpenAITranscriptionBackend`) le satisfait sans
    une ligne de changement.
    """

    async def transcribe(self, audio: AudioClip) -> Any: ...


#: Ce que chaque disposition du magasin veut dire pour la lane. Explicite et
#: exhaustif : une observation écartée doit être **comptée et dite**, jamais
#: avalée. Une disposition inconnue tombe dans `unknown` et se dit à `error`,
#: pour qu'un vocabulaire qui bougerait ne devienne pas un silence.
_DISPOSITION_POLICY: dict[str, tuple[str, str, bool]] = {
    # disposition -> (compteur, niveau de journal, « c'est une perte »)
    "applied": ("applied", "info", False),
    "duplicate": ("duplicate", "info", False),
    "ignored": ("ignored", "warning", True),
    "stale": ("stale", "warning", True),
    "stale_session": ("stale_session", "warning", True),
    "capacity": ("capacity", "warning", True),
    "rejected": ("rejected", "error", True),
}


def _short(value: object) -> str:
    text = str(value)
    return text if len(text) <= MAX_JOURNALLED_VALUE_CHARS else text[:MAX_JOURNALLED_VALUE_CHARS] + "…"


def _stable_id(prefix: str, label: str) -> str:
    """Identifiant déterministe et borné pour un libellé.

    Un sujet mentionné deux fois doit porter le **même** identifiant, sinon la
    coalescence du magasin ne monterait jamais `mention_count` et l'ensemble de
    travail se remplirait de doublons jusqu'à sa borne.
    """

    digest = hashlib.sha1(label.casefold().strip().encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _disposition_of(result: object) -> str:
    value = getattr(result, "disposition", None)
    return str(getattr(value, "value", value))


@dataclass(slots=True)
class _QueuedSegment:
    segment: AmbientSegment
    enqueued_at: float
    generation: int


@dataclass(slots=True)
class _QueuedAnalysis:
    utterance: AmbientUtterance
    sequence: int
    generation: int


@dataclass(slots=True)
class AmbientLaneCounters:
    """Toute la comptabilité de la lane, en un seul endroit lisible.

    Un invariant qu'on ne peut pas lire est un invariant qui dérive (leçon de
    la Slice 04 : `retired_resource_ids` a été exposé précisément pour qu'un
    test puisse distinguer « rien n'a été écrit » de « l'instantané n'a pas
    bougé »). Tout ce que ce module promet — file bornée, rejet compté, travail
    périmé annulé, impératif reconnu et sans effet — se lit ici.
    """

    blocks_in: int = 0
    segments_in: int = 0
    segments_dropped_queue: int = 0
    segments_dropped_stale: int = 0
    segments_cancelled: int = 0
    transcripts_ok: int = 0
    transcripts_empty: int = 0
    transcripts_failed: int = 0
    transcripts_timeout: int = 0
    transcripts_clipped: int = 0
    revisions: int = 0
    tail_dispositions: dict[str, int] = field(default_factory=dict)
    working_set_dispositions: dict[str, int] = field(default_factory=dict)
    analysis_dropped_queue: int = 0
    analysis_cancelled: int = 0
    filler_suppressed: int = 0
    imperative_utterances: int = 0
    triggers_emitted: int = 0
    trigger_callback_failures: int = 0
    prunes: int = 0

    def bump(self, table: dict[str, int], key: str) -> None:
        table[key] = table.get(key, 0) + 1

    def to_payload(self) -> dict[str, Any]:
        return {
            "blocks_in": self.blocks_in,
            "segments_in": self.segments_in,
            "segments_dropped_queue": self.segments_dropped_queue,
            "segments_dropped_stale": self.segments_dropped_stale,
            "segments_cancelled": self.segments_cancelled,
            "transcripts_ok": self.transcripts_ok,
            "transcripts_empty": self.transcripts_empty,
            "transcripts_failed": self.transcripts_failed,
            "transcripts_timeout": self.transcripts_timeout,
            "transcripts_clipped": self.transcripts_clipped,
            "revisions": self.revisions,
            "tail": dict(self.tail_dispositions),
            "working_set": dict(self.working_set_dispositions),
            "analysis_dropped_queue": self.analysis_dropped_queue,
            "analysis_cancelled": self.analysis_cancelled,
            "filler_suppressed": self.filler_suppressed,
            "imperative_utterances": self.imperative_utterances,
            "triggers_emitted": self.triggers_emitted,
            "trigger_callback_failures": self.trigger_callback_failures,
            "prunes": self.prunes,
        }


class AmbientIngestionLane:
    """La parole continue de la salle, jusqu'au fil de séance. Bornée, comptée."""

    def __init__(
        self,
        *,
        hub: Any,
        transcriber: AmbientTranscriber,
        sink: PresentationObservationSink,
        session_id: str,
        journal: RuntimeJournal | None = None,
        segmenter: AmbientSegmenter | None = None,
        capture_blocks: int = DEFAULT_CAPTURE_BLOCKS,
        segment_queue: int = DEFAULT_SEGMENT_QUEUE,
        analysis_queue: int = DEFAULT_ANALYSIS_QUEUE,
        transcription_timeout_s: float = DEFAULT_TRANSCRIPTION_TIMEOUT_S,
        max_segment_age_s: float = MAX_SEGMENT_AGE_S,
        idle_prune_period_s: float = IDLE_PRUNE_PERIOD_S,
        on_utterance: Callable[[AmbientUtterance, AmbientAnalysis], None] | None = None,
        on_trigger: Callable[[AmbientTrigger], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not session_id:
            raise AmbientLaneError("ambient_session_required", "Une lane ambiante appartient à une séance nommée.")
        self.hub = hub
        self.transcriber = transcriber
        self.sink = sink
        self.session_id = session_id
        self.journal = journal
        self.segmenter = segmenter or AmbientSegmenter(sample_rate=int(getattr(hub, "sample_rate", 24000)))
        self.capture_blocks = max(1, int(capture_blocks))
        self.transcription_timeout_s = float(transcription_timeout_s)
        self.max_segment_age_s = float(max_segment_age_s)
        self.idle_prune_period_s = float(idle_prune_period_s)
        self.on_utterance = on_utterance
        self.on_trigger = on_trigger
        self._clock = clock or utc_now
        self.counters = AmbientLaneCounters()
        self.segment_queue_size = max(1, int(segment_queue))
        self.analysis_queue_size = max(1, int(analysis_queue))
        self._segments: deque[_QueuedSegment] = deque()
        self._segment_ready = asyncio.Event()
        self._analyses: deque[_QueuedAnalysis] = deque()
        self._analysis_ready = asyncio.Event()
        self._subscription: Any | None = None
        self._tasks: list[asyncio.Task] = []
        self._consecutive_failures = 0
        self._generation = 0
        self._utterance_seq = 0
        #: L'énonciation en cours de révision : posée quand un segment a été
        #: coupé d'office, reprise par le segment suivant.
        self._pending_revision: tuple[str, str, int] | None = None
        self.started = False
        self.stopped = False
        self.degraded = False
        self.degraded_reason: str | None = None

    # -- traces ------------------------------------------------------------

    def _trace(self, kind: str, message: str, *, level: str = "info", **data: object) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=dict(data))
        except Exception:
            # Intentionnel : un journal en panne ne doit pas faire tomber la
            # lane qu'il observe. La Slice 04 tient la même position pour son
            # magasin (`test_un_journal_en_panne_n_empeche_pas_de_retenir_la_seance`),
            # et il n'existe aucun second canal vers lequel se rabattre ici.
            pass

    # -- cycle de vie ------------------------------------------------------

    async def start(self) -> None:
        """S'abonner au hub et lancer les deux ouvriers. Idempotent."""

        if self.stopped:
            raise AmbientLaneError(
                "ambient_lane_stopped",
                "Cette lane ambiante est arrêtée : composez-en une neuve plutôt que de la relancer.",
            )
        if self.started:
            return
        # `sample_rate=None` : la fréquence du hub, telle quelle. Le
        # rééchantillonneur du hub est une interpolation linéaire sans filtre
        # anti-repliement — juste pour un moteur de mot d'éveil, faux pour de
        # la transcription (`docs/presentation-audio-capture.md` § 7).
        self._subscription = self.hub.subscribe(
            "ambient_ingestion", sample_rate=None, max_blocks=self.capture_blocks,
        )
        self.started = True
        self._tasks = [
            asyncio.create_task(self._capture_worker(), name="ambient-capture"),
            asyncio.create_task(self._transcribe_worker(), name="ambient-transcribe"),
            asyncio.create_task(self._analysis_worker(), name="ambient-analysis"),
        ]
        self._trace(
            f"{AMBIENT_KIND}.started", "Lane ambiante ouverte sur la capture partagée",
            session_id=_short(self.session_id), sample_rate=self._subscription.sample_rate,
            capture_blocks=self.capture_blocks, segment_queue=self.segment_queue_size,
            analysis_queue=self.analysis_queue_size, code="ambient_lane_started",
        )

    async def stop(self) -> None:
        """Arrêter la lane. Terminal, idempotent, et il rend ce qu'il a pris."""

        if self.stopped:
            return
        self.stopped = True
        self.started = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                # Intentionnel : on ferme. Une tâche qui meurt en étant annulée
                # n'apprend rien à personne, et l'échec réel a déjà été dit par
                # l'ouvrier lui-même au moment où il s'est produit.
                pass
        self._tasks = []
        if self._subscription is not None:
            try:
                self._subscription.close()
            except Exception as exc:
                self._trace(
                    f"{AMBIENT_KIND}.unsubscribe_failed",
                    f"Fermeture de l'abonnement ambiant impossible: {type(exc).__name__}: {exc}",
                    level="error", code="ambient_unsubscribe_failed",
                )
            self._subscription = None
        cancelled = self.discard_pending("lane_stopped")
        self._trace(
            f"{AMBIENT_KIND}.stopped", "Lane ambiante fermée",
            cancelled=cancelled, code="ambient_lane_stopped", **self.counters.to_payload(),
        )

    def discard_pending(self, reason: str) -> int:
        """Annuler le travail ambiant en attente. Rendu : combien a été jeté.

        Le travail ambiant est **sacrifiable** (D08). Une séance qui se retire,
        un mode qui change, un appareil perdu : ce qui attendait ne vaut plus
        rien et doit disparaître tout de suite, pas être servi plus tard comme
        du frais. `generation` monte, si bien qu'un élément déjà sorti de la
        file — en cours de transcription — est reconnu périmé à son retour.
        """

        dropped = len(self._segments) + len(self._analyses)
        self.counters.segments_cancelled += len(self._segments)
        self.counters.analysis_cancelled += len(self._analyses)
        self._segments.clear()
        self._analyses.clear()
        self._generation += 1
        self._pending_revision = None
        self.segmenter.reset()
        if dropped:
            self._trace(
                f"{AMBIENT_KIND}.discarded", "Travail ambiant en attente annulé",
                level="warning", dropped=dropped, reason=_short(reason),
                generation=self._generation, code="ambient_pending_discarded",
            )
        return dropped

    # -- ouvrier 1 : capture et segmentation -------------------------------

    async def _capture_worker(self) -> None:
        subscription = self._subscription
        if subscription is None:  # pragma: no cover - start() pose toujours l'abonnement
            return
        try:
            async for block in subscription.blocks():
                self.counters.blocks_in += 1
                try:
                    segments = self.segmenter.push(block)
                except Exception as exc:
                    # Une trame mal découpée ne doit pas tuer la capture : on
                    # le dit, on repart d'un segmenteur propre.
                    self._trace(
                        f"{AMBIENT_KIND}.segmentation_failed",
                        f"Segmentation ambiante en échec: {type(exc).__name__}: {exc}",
                        level="error", code="ambient_segmentation_failed",
                    )
                    self.segmenter.reset()
                    continue
                for segment in segments:
                    self._offer_segment(segment)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._trace(
                f"{AMBIENT_KIND}.capture_failed",
                f"Capture ambiante interrompue: {type(exc).__name__}: {exc}. "
                "La touche manuelle et le mot d'éveil ne sont pas concernés.",
                level="error", code="ambient_capture_failed",
            )

    def _offer_segment(self, segment: AmbientSegment) -> None:
        """Déposer un segment. Borné, jamais bloquant, toujours compté."""

        self.counters.segments_in += 1
        if len(self._segments) >= self.segment_queue_size:
            self._segments.popleft()
            self.counters.segments_dropped_queue += 1
            self._trace(
                f"{AMBIENT_KIND}.backpressure", "File de segments pleine : le plus ancien est écarté",
                level="warning", policy="drop_oldest", queue=self.segment_queue_size,
                dropped=self.counters.segments_dropped_queue, code="ambient_segment_dropped",
            )
        self._segments.append(
            _QueuedSegment(segment=segment, enqueued_at=time.monotonic(), generation=self._generation)
        )
        self._segment_ready.set()
        self._trace(
            f"{AMBIENT_KIND}.segmented", "Énonciation ambiante découpée",
            pending=len(self._segments), code="ambient_segment_ready", **segment.to_payload(),
        )

    # -- ouvrier 2 : transcription, puis le fil, avant toute analyse -------

    async def _transcribe_worker(self) -> None:
        while True:
            item = await self._take_segment()
            if item is None:
                self._idle_prune()
                continue
            if item.generation != self._generation:
                self.counters.segments_dropped_stale += 1
                self._say_stale("generation", item)
                continue
            waited = time.monotonic() - item.enqueued_at
            if waited > self.max_segment_age_s:
                self.counters.segments_dropped_stale += 1
                self._say_stale("age", item, waited=round(waited, 3))
                continue
            await self._transcribe_and_observe(item, waited=waited)

    async def _take_segment(self) -> _QueuedSegment | None:
        """Attendre un segment, ou rendre `None` après la période de repos."""

        while True:
            if self._segments:
                return self._segments.popleft()
            self._segment_ready.clear()
            if self._segments:
                continue
            try:
                await asyncio.wait_for(self._segment_ready.wait(), self.idle_prune_period_s)
            except (asyncio.TimeoutError, TimeoutError):
                return None

    def _say_stale(self, reason: str, item: _QueuedSegment, **data: object) -> None:
        self._trace(
            f"{AMBIENT_KIND}.stale", "Segment ambiant périmé : écarté plutôt que servi comme du frais",
            level="warning", reason=reason, sequence=item.segment.sequence,
            duration_s=item.segment.duration_s, code=f"ambient_segment_stale_{reason}", **data,
        )

    async def _transcribe_and_observe(self, item: _QueuedSegment, *, waited: float) -> None:
        segment = item.segment
        clip = AudioClip(
            pcm16_to_wav(segment.pcm, segment.sample_rate),
            segment.sample_rate, 1, 2, "audio/wav",
        )
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self.transcriber.transcribe(clip), self.transcription_timeout_s,
            )
        except (asyncio.TimeoutError, TimeoutError):
            self.counters.transcripts_timeout += 1
            self._note_failure(
                "ambient_transcription_timeout",
                f"Transcription ambiante sans réponse après {self.transcription_timeout_s:.0f} s : "
                "le segment est abandonné, la capture continue.",
            )
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.counters.transcripts_failed += 1
            # Les mots de la panne réelle, jamais une formule générique : un
            # compte sans crédit n'est pas « temporairement indisponible ».
            self._note_failure(
                "ambient_transcription_failed",
                f"Transcription ambiante en échec: {type(exc).__name__}: {exc}. "
                "La lane d'adresse explicite n'est pas affectée.",
            )
            return
        if item.generation != self._generation:
            # Annulé pendant l'appel. Le travail ambiant est sacrifiable (D08) :
            # une transcription revenue après l'annulation décrit une séance qui
            # n'existe plus, et la ranger la ferait passer pour du frais.
            self.counters.segments_dropped_stale += 1
            self._say_stale("cancelled", item)
            return
        self._recover()
        text = clip_ambient_text(str(getattr(result, "text", "") or ""))
        raw_len = len(" ".join(str(getattr(result, "text", "") or "").split()))
        if raw_len > len(text):
            self.counters.transcripts_clipped += 1
        if not text:
            self.counters.transcripts_empty += 1
            self._trace(
                f"{AMBIENT_KIND}.empty", "Transcription ambiante vide : rien à ranger",
                level="warning", sequence=segment.sequence, duration_s=segment.duration_s,
                code="ambient_transcript_empty",
            )
            return
        self.counters.transcripts_ok += 1
        self._observe(segment, text, latency_s=time.monotonic() - started, waited=waited)

    def _observe(self, segment: AmbientSegment, text: str, *, latency_s: float, waited: float) -> None:
        """Le fil **d'abord** (D06), l'analyse ensuite et ailleurs."""

        revision = 0
        pending = self._pending_revision
        if pending is not None:
            held_id, held_text, held_revision = pending
            joined = clip_ambient_text(f"{held_text} {text}")
            if len(joined) > len(held_text):
                utterance_id, text, revision = held_id, joined, held_revision + 1
                self.counters.revisions += 1
            else:
                # La suite ne tient plus dans la borne : c'est une énonciation
                # neuve, pas une révision tronquée qui perdrait la fin.
                utterance_id = self._next_utterance_id()
        else:
            utterance_id = self._next_utterance_id()
        self._pending_revision = (utterance_id, text, revision) if segment.truncated else None

        spoken_at = self._clock() - timedelta(seconds=float(segment.duration_s))
        result = self.sink.observe(
            self.session_id, utterance_id, text,
            spoken_at=spoken_at, origin=UtteranceOrigin.AMBIENT, revision=revision,
        )
        applied = self._account(self.counters.tail_dispositions, result, "tail", utterance_id)
        self._trace(
            f"{AMBIENT_KIND}.transcribed", "Parole ambiante portée au fil de séance",
            level="info" if applied else "warning",
            utterance_id=_short(utterance_id), revision=revision, chars=len(text),
            duration_s=segment.duration_s, queue_wait_s=round(waited, 3),
            transcribe_s=round(latency_s, 3), truncated=segment.truncated,
            disposition=_disposition_of(result), code=_short(getattr(result, "code", "")),
        )
        if not applied:
            return
        sequence = self._tail_sequence(utterance_id)
        utterance = AmbientUtterance(
            utterance_id=utterance_id, session_id=self.session_id, text=text,
            spoken_at=spoken_at, duration_s=float(segment.duration_s),
            revision=revision, truncated=segment.truncated,
        )
        self._offer_analysis(_QueuedAnalysis(utterance=utterance, sequence=sequence, generation=self._generation))

    def _next_utterance_id(self) -> str:
        self._utterance_seq += 1
        return f"amb-{self._utterance_seq:06d}"

    def _tail_sequence(self, utterance_id: str) -> int:
        """Le rang que le magasin vient d'attribuer, relu dans l'instantané.

        C'est cette valeur qui fait de `enrichment_lag_entries` une mesure :
        sans elle, l'ensemble de travail citerait un rang inventé et le retard
        annoncé par l'instantané ne voudrait rien dire (D06).
        """

        try:
            tail = self.sink.snapshot.tail
            for entry in tail.entries:
                if entry.utterance_id == utterance_id:
                    return int(entry.sequence)
        except Exception as exc:  # pragma: no cover - un magasin conforme rend toujours un instantané
            self._trace(
                f"{AMBIENT_KIND}.sequence_unavailable",
                f"Rang d'énonciation illisible: {type(exc).__name__}: {exc}",
                level="error", code="ambient_sequence_unavailable",
            )
        return 1

    # -- ouvrier 3 : analyse bon marché ------------------------------------

    def _offer_analysis(self, item: _QueuedAnalysis) -> None:
        if len(self._analyses) >= self.analysis_queue_size:
            self._analyses.popleft()
            self.counters.analysis_dropped_queue += 1
            self._trace(
                f"{AMBIENT_KIND}.backpressure", "File d'analyse pleine : la plus ancienne est écartée",
                level="warning", policy="drop_oldest", queue=self.analysis_queue_size,
                dropped=self.counters.analysis_dropped_queue, code="ambient_analysis_dropped",
            )
        self._analyses.append(item)
        self._analysis_ready.set()

    async def _analysis_worker(self) -> None:
        while True:
            while not self._analyses:
                self._analysis_ready.clear()
                if self._analyses:
                    break
                await self._analysis_ready.wait()
            item = self._analyses.popleft()
            if item.generation != self._generation:
                self.counters.analysis_cancelled += 1
                continue
            try:
                self._analyse(item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._trace(
                    f"{AMBIENT_KIND}.analysis_failed",
                    f"Analyse ambiante en échec: {type(exc).__name__}: {exc}. "
                    "Le fil de séance a déjà la parole ; seule l'analyse manque.",
                    level="error", code="ambient_analysis_failed",
                )

    def _analyse(self, item: _QueuedAnalysis) -> None:
        utterance = item.utterance
        analysis = analyse_ambient_text(utterance.utterance_id, utterance.text)
        if analysis.imperative:
            # Compté, et rien d'autre. D03 : une phrase à l'impératif entendue
            # dans la salle n'autorise aucune action. Le compteur existe pour
            # qu'un test prouve que la forme a bien été reconnue *et* qu'il
            # n'en est rien sorti.
            self.counters.imperative_utterances += 1
        if analysis.filler:
            self.counters.filler_suppressed += 1
            self._trace(
                f"{AMBIENT_KIND}.analysed", "Énonciation sans valeur : rien à enrichir",
                utterance_id=_short(utterance.utterance_id), code="ambient_filler_suppressed",
                **analysis.to_journal(),
            )
            self._emit(utterance, analysis)
            return
        provenance = ObservationProvenance(
            utterance_id=utterance.utterance_id, sequence=item.sequence,
            observed_at=utterance.spoken_at, origin=UtteranceOrigin.AMBIENT,
        )
        for record in self._records(analysis, provenance, at=utterance.spoken_at):
            observation = PresentationObservation(
                observation_id=f"{utterance.utterance_id}-{record.record_id}"[:64],
                session_id=self.session_id, record=record,
            )
            result = self.sink.apply(observation)
            self._account(
                self.counters.working_set_dispositions, result, "working_set", observation.observation_id,
            )
        self._trace(
            f"{AMBIENT_KIND}.analysed", "Énonciation ambiante analysée",
            utterance_id=_short(utterance.utterance_id), sequence=item.sequence,
            code="ambient_analysed", **analysis.to_journal(),
        )
        self._emit(utterance, analysis)

    def _records(self, analysis: AmbientAnalysis, provenance: ObservationProvenance, *, at: datetime) -> list[Any]:
        records: list[Any] = []
        topic_id = _stable_id("topic", analysis.topics[0]) if analysis.topics else None
        for label in analysis.topics:
            records.append(
                PresentationTopic(
                    topic_id=_stable_id("topic", label), label=label, provenance=provenance,
                    first_seen_at=at, last_seen_at=at,
                )
            )
        for label in analysis.entities:
            records.append(
                PresentationEntity(
                    entity_id=_stable_id("entity", label), label=label, kind="mentioned",
                    provenance=provenance, first_seen_at=at, last_seen_at=at, topic_id=topic_id,
                )
            )
        for statement in analysis.claims:
            records.append(
                PresentationClaim(
                    claim_id=_stable_id("claim", statement), statement=statement,
                    provenance=provenance, first_seen_at=at, last_seen_at=at,
                    status=ClaimStatus.ASSERTED, topic_id=topic_id,
                )
            )
        for question in analysis.questions:
            records.append(
                OpenQuestion(
                    question_id=_stable_id("question", question), text=question,
                    provenance=provenance, asked_at=at, topic_id=topic_id,
                )
            )
        return records

    def _emit(self, utterance: AmbientUtterance, analysis: AmbientAnalysis) -> None:
        """Remettre l'observation typée et ses pistes d'enquête aux consommateurs.

        Les rappels sont isolés : un consommateur qui lève est compté et dit, et
        n'empêche ni le suivant ni la parole d'après. La Slice 08 branche
        `on_trigger` ici ; elle ne reçoit jamais autre chose que des
        `AmbientTrigger`, dont `authorizes_actions` vaut `False`.
        """

        self._call_consumer(self.on_utterance, utterance, analysis)
        for trigger in analysis.triggers:
            # Compté à la production, pas à la livraison : sans consommateur
            # branché, « zéro déclencheur émis » et « zéro déclencheur trouvé »
            # seraient la même ligne, et c'est exactement la confusion que ce
            # dépôt refuse ailleurs.
            self.counters.triggers_emitted += 1
            self._call_consumer(self.on_trigger, trigger)

    def _call_consumer(self, callback: Callable[..., Any] | None, *arguments: Any) -> None:
        if callback is None:
            return
        try:
            callback(*arguments)
        except Exception as exc:
            self.counters.trigger_callback_failures += 1
            self._trace(
                f"{AMBIENT_KIND}.consumer_failed",
                f"Consommateur ambiant en échec: {type(exc).__name__}: {exc}",
                level="error", code="ambient_consumer_failed",
            )

    # -- dispositions, pannes, repos ---------------------------------------

    def _account(self, table: dict[str, int], result: object, surface: str, key: str) -> bool:
        """Compter et **dire** la réponse du magasin. Jamais l'avaler."""

        disposition = _disposition_of(result)
        policy = _DISPOSITION_POLICY.get(disposition)
        if policy is None:
            self.counters.bump(table, "unknown")
            self._trace(
                f"{AMBIENT_KIND}.refused",
                f"Disposition inconnue rendue par le magasin de séance : {disposition}",
                level="error", surface=surface, disposition=_short(disposition),
                code="ambient_disposition_unknown",
            )
            return False
        name, level, lost = policy
        self.counters.bump(table, name)
        if lost:
            self._trace(
                f"{AMBIENT_KIND}.refused", "Observation ambiante écartée par le magasin de séance",
                level=level, surface=surface, disposition=name,
                reference=_short(key), code=_short(getattr(result, "code", "")) or f"ambient_{name}",
            )
        return bool(getattr(result, "applied", False))

    def _note_failure(self, code: str, message: str) -> None:
        self._consecutive_failures += 1
        self._trace(f"{AMBIENT_KIND}.transcription_failed", message, level="error", code=code)
        if self._consecutive_failures >= MAX_CONSECUTIVE_TRANSCRIPTION_FAILURES and not self.degraded:
            self.degraded = True
            self.degraded_reason = code
            self._trace(
                f"{AMBIENT_KIND}.degraded",
                f"Lane ambiante dégradée après {self._consecutive_failures} échecs consécutifs : "
                "plus rien n'alimente le fil de séance. L'adresse explicite reste entière.",
                level="error", failures=self._consecutive_failures, code="ambient_lane_degraded",
            )

    def _recover(self) -> None:
        if self.degraded:
            self.degraded = False
            self.degraded_reason = None
            self._trace(
                f"{AMBIENT_KIND}.recovered", "Lane ambiante de nouveau alimentée",
                level="info", code="ambient_lane_recovered",
            )
        self._consecutive_failures = 0

    def _idle_prune(self) -> None:
        """Personne ne parle : balayer les budgets d'âge du magasin.

        Les bornes d'âge du magasin se mesurent depuis la parole la plus
        récente ; sans parole, plus rien ne les déclencherait. C'est
        explicitement à la lane ambiante de le faire
        (`docs/presentation-working-set.md`).
        """

        try:
            result = self.sink.prune()
        except Exception as exc:
            self._trace(
                f"{AMBIENT_KIND}.prune_failed",
                f"Balayage d'âge impossible: {type(exc).__name__}: {exc}",
                level="error", code="ambient_prune_failed",
            )
            return
        self.counters.prunes += 1
        if getattr(result, "applied", False):
            self._trace(
                f"{AMBIENT_KIND}.pruned", "Séance balayée pendant le silence",
                code=_short(getattr(result, "code", "")), evicted=getattr(result, "evicted", 0),
            )

    # -- observation -------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        subscription = self._subscription
        return {
            "session_id": self.session_id,
            "started": self.started,
            "stopped": self.stopped,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "generation": self._generation,
            "consecutive_failures": self._consecutive_failures,
            "segment_queue": self.segment_queue_size,
            "segments_pending": len(self._segments),
            "analysis_queue": self.analysis_queue_size,
            "analysis_pending": len(self._analyses),
            "subscription": subscription.stats() if subscription is not None else None,
            "segmenter": self.segmenter.stats(),
            "counters": self.counters.to_payload(),
        }


__all__ = [
    "DEFAULT_ANALYSIS_QUEUE",
    "DEFAULT_CAPTURE_BLOCKS",
    "DEFAULT_SEGMENT_QUEUE",
    "DEFAULT_TRANSCRIPTION_TIMEOUT_S",
    "IDLE_PRUNE_PERIOD_S",
    "MAX_CONSECUTIVE_TRANSCRIPTION_FAILURES",
    "MAX_SEGMENT_AGE_S",
    "AmbientIngestionLane",
    "AmbientLaneCounters",
    "AmbientLaneError",
    "AmbientTranscriber",
    "PresentationObservationSink",
]
