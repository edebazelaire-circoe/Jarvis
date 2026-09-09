from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from jarvis.ports.v2 import DiagnosticSink

# Les six mesures de `docs/handoff-realtime-brain/docs/04-testing-and-quality.md`,
# section « Latency telemetry ». Le nom décrit les deux bornes, jamais ce qui a
# été dit entre elles : c'est le seul vocabulaire partagé entre Core et le
# runtime vocal, et il doit rester lisible dans un journal brut.
SURFACE_FIRST_AUDIO = "speech_started_to_surface_first_audio"
BRAIN_TURN_ACCEPTED = "transcript_completed_to_brain_turn_accepted"
FIRST_BRAIN_AUDIO = "brain_speech_requested_to_first_brain_audio"
LOCAL_OUTPUT_STOPPED = "user_interrupt_detected_to_local_output_stopped"
FIRST_PUBLIC_PROGRESS = "brain_work_started_to_first_public_progress"
WORK_COMPLETED = "brain_work_started_to_completed"

#: Inventaire exhaustif. Un test s'appuie dessus pour vérifier qu'aucune des six
#: mesures n'a été perdue en route.
LATENCY_MEASURES: tuple[str, ...] = (
    SURFACE_FIRST_AUDIO,
    BRAIN_TURN_ACCEPTED,
    FIRST_BRAIN_AUDIO,
    LOCAL_OUTPUT_STOPPED,
    FIRST_PUBLIC_PROGRESS,
    WORK_COMPLETED,
)

#: Marques en attente conservées au plus. Une borne est indispensable : une
#: borne d'arrivée peut ne jamais venir (travail annulé, sortie muette, session
#: coupée), et une mesure sans fin ne doit pas faire grossir un processus qui
#: tourne des heures.
DEFAULT_PENDING_LIMIT = 256


class LatencyTracker:
    """Chronomètre des mesures de latence, sans jamais toucher au contenu.

    Propriété et concurrence
    ------------------------
    Un `LatencyTracker` appartient à un seul composant (le bridge vocal,
    l'ordonnanceur de parole, l'orchestrateur cerveau) et n'est manipulé que
    depuis la boucle asyncio de ce composant. Aucune méthode n'est un point de
    suspension, donc aucune n'a besoin de verrou ; cette invariante est à revoir
    si un jour deux tâches marquaient la même mesure.

    Confidentialité (contrat non négociable, `docs/04-testing-and-quality.md`)
    -------------------------------------------------------------------------
    Le message émis est **fabriqué ici** à partir du seul nom de la mesure et
    du temps écoulé : un appelant ne peut pas y glisser une transcription. Les
    champs de `data` restent de la responsabilité de l'appelant, qui n'y met que
    des identifiants, des types et des tailles — jamais un corps de
    transcription, une invite ou un raisonnement.

    Horloge
    -------
    `time.perf_counter` par défaut : monotone, donc insensible à un ajustement
    d'horloge système en cours de mesure. Les deux bornes d'une mesure sont donc
    prises dans le **même** processus ; une mesure qui traverserait Core et
    Voice serait fausse, et aucune des six ne le fait.
    """

    __slots__ = ("_sink", "_pending", "_pending_limit", "_clock")

    def __init__(
        self,
        sink: DiagnosticSink | None = None,
        *,
        pending_limit: int = DEFAULT_PENDING_LIMIT,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._sink = sink
        self._pending: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._pending_limit = max(1, pending_limit)
        self._clock = clock

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def mark(self, measure: str, key: str) -> None:
        """Poser la borne de départ d'une mesure, écrasant une marque homonyme.

        Écraser est voulu : deux départs sans arrivée signifient que le premier
        n'aboutira jamais (l'utilisateur a recommencé à parler, le travail a été
        relancé), et c'est le plus récent qui décrit ce qui se passe.
        """

        if not measure or not key:
            return
        self._pending[(measure, key)] = self._clock()
        self._pending.move_to_end((measure, key))
        while len(self._pending) > self._pending_limit:
            self._pending.popitem(last=False)

    def forget(self, measure: str, key: str) -> None:
        """Abandonner une mesure dont la borne d'arrivée ne viendra pas."""

        self._pending.pop((measure, key), None)

    def measure(
        self,
        measure: str,
        key: str,
        *,
        kind: str,
        data: dict[str, Any] | None = None,
    ) -> float | None:
        """Fermer une mesure et l'émettre, ou rendre `None` s'il n'y a rien à fermer.

        Rendre `None` est un cas normal, pas une anomalie : une sortie vocale
        peut commencer sans qu'aucune parole utilisateur ne l'ait précédée, et
        un travail peut se terminer alors que sa marque a été évincée. Émettre
        une latence dans ce cas donnerait un chiffre inventé.
        """

        started = self._pending.pop((measure, key), None)
        if started is None:
            return None
        elapsed_ms = round((self._clock() - started) * 1000, 1)
        if self._sink is not None:
            self._sink.emit(
                kind,
                f"Latence {measure}: {elapsed_ms} ms",
                level="info",
                data={**(data or {}), "measure": measure, "elapsed_ms": elapsed_ms},
            )
        return elapsed_ms
