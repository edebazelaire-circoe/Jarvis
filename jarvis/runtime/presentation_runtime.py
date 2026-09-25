"""La composition de PRESENTATION : cinq sous-systèmes, une séance, un micro.

Slice 11. Les Slices 05, 06, 08, 09 et 10 ont livré leurs sous-systèmes
délibérément **non câblés** — « no producer, no consumer » — parce que les
câbler plus tôt aurait ouvert le micro de la salle en production sans que
personne n'en consomme le son. Ce module est l'endroit où ils se rejoignent, et
il est le seul.

## Où vit l'état de séance, et pourquoi ici

`PresentationObservationSink` (Slice 06) est **synchrone**. La Slice 06 a
laissé la question à la rollout : le magasin de la Slice 04 est-il joint en
processus, ou par un relais vers Core ?

La réponse est **en processus, dans Voice**, et elle n'est pas une préférence :

1. `PresentationAddressedTurnService.open()` (Slice 10) est **synchrone par
   garde AST** — un `await` dans `arm()` ou `open()` fait tomber un test par son
   nom — et il lit `store.snapshot` dans ce cadre. Un magasin joint par relais
   rendrait cette lecture bloquante sur la boucle d'évènements de Voice, la
   même qui porte la voie d'adresse explicite. Ce n'est pas réparable sans
   casser la garde qui prouve D04 ;
2. le puits ambiant est appelé depuis `_transcribe_and_observe`, une tâche de
   cette même boucle. Un POST synchrone y gèle tout ce que la boucle porte —
   pendant le temps d'un aller-retour quand Core répond, et pendant le délai de
   connexion quand il ne répond pas ;
3. aucun relais n'existe : il faudrait inventer une surface protocolaire
   `/v1/presentation/*` avec son propre budget de latence, ce que la Slice 06
   avait déjà refusé de faire pour cette raison.

Conséquence, dite plutôt que laissée à découvrir : `V2App.presentation_working_set`
(`jarvis/core/v2_app.py`) reste ce qu'il était — un magasin **sans producteur**,
dont le seul câblage est le retrait sur changement de mode. La séance vivante
est celle de ce module. Deux magasins existent donc, et un seul est alimenté ;
c'est écrit dans `docs/ARCHITECTURE.md` et dans le rapport de la Slice plutôt
que corrigé ici, parce que retirer celui de Core est une régression de la
Slice 04 avec sa propre surface de tests.

## Un micro, compté, jamais deux

En SIMPLE, deux flux d'entrée coexistent (`PorcupineWakeWordBackend` et
`SoundDeviceRealtimeAudio`) et ne sont jamais ouverts en même temps. En
PRESENTATION, l'écoute est continue : rien ne se suspend, donc cet arrangement
ne tient plus. `PresentationAudioSession` devient le propriétaire unique, et
`PersistentVoiceRuntime._shared_input_source()` donne son PCM au bridge.

Le basculement passe donc par l'ordre, et l'ordre est la garantie :

- SIMPLE → PRESENTATION : **suspendre** la pile d'éveil de SIMPLE (ce qui ferme
  le flux Porcupine et le retire du registre), *puis* démarrer la séance. Si la
  suspension échoue, `PresentationAudioSession.start()` compte deux
  propriétaires et **refuse** — bruyamment, jamais en ouvrant un second flux ;
- PRESENTATION → SIMPLE : **arrêter** la séance (le hub relâche le
  périphérique), *puis* reprendre la pile d'éveil.

## Ce qui reste vrai en SIMPLE

Rien de ce module ne s'exécute. `PresentationWakeRouter` sans séance vivante
rend exactement les détections de la pile d'éveil qu'on lui a donnée, et aucun
sous-système n'est construit. C'est la frontière de non-régression de D14, et
elle est testée plutôt qu'affirmée.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Sequence

from jarvis.core.presentation_attention import PresentationAttentionService
from jarvis.core.presentation_addressed_turn import PresentationAddressedTurnService
from jarvis.core.presentation_speculative import PresentationSpeculativeService
from jarvis.core.presentation_working_set import PresentationWorkingSetStore
from jarvis.domain.interaction_mode import InteractionMode, behaving_interaction_mode
from jarvis.domain.presentation_working_set import (
    PresentationObservation,
    PresentationSource,
    ResourceKind,
)
from jarvis.domain.v2 import utc_now
from jarvis.runtime.ambient_lane import AmbientIngestionLane
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.presentation_preparation import PreparationClaim

__all__ = [
    "PRESENTATION_RUNTIME_KIND",
    "DIAGNOSTICS_PERIOD_S",
    "StagedObjectLedger",
    "LedgeredSceneStager",
    "PresentationStack",
    "PresentationWakeRouter",
    "PresentationCoordinator",
    "PresentationComposition",
    "PresentationRuntimeError",
    "claims_reader",
    "source_recorder",
    "new_session_id",
]

#: Préfixe des lignes de trace de ce module.
PRESENTATION_RUNTIME_KIND = "presentation.runtime"

#: Période du relevé de diagnostics, tant qu'une séance vit. Trente secondes :
#: assez pour qu'un retard s'installe et se voie, assez peu pour que la trace
#: d'une présentation d'une heure reste lisible (120 lignes).
DIAGNOSTICS_PERIOD_S = 30.0

#: Objets de scène dont on garde l'identifiant sur le disque. Deux fois la borne
#: du service (`MAX_STAGED_OBJECTS = 8`), pour qu'un arrêt brutal juste après un
#: montage ne perde rien, et borné pour qu'un fichier abîmé reste petit.
MAX_LEDGER_IDS = 16


class PresentationRuntimeError(RuntimeError):
    """Refus nommé de la composition. Code stable, cause conservée."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def new_session_id() -> str:
    """Un identifiant de séance, unique par activation."""

    return f"pres-{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------
# Reprise des objets montés après un arrêt non propre
# --------------------------------------------------------------------------


class StagedObjectLedger:
    """Les identifiants des objets de scène montés, sur le disque.

    ## Pourquoi un fichier, alors que D13 interdit la persistance

    D13 interdit qu'une **préparation survive** à la séance. Un objet de scène
    monté est durable — il descend jusqu'à `INSERT INTO scene_objects` et
    survit au redémarrage (Slice 08, B3). `PresentationSpeculativeService.retire()`
    les reprend, mais seulement sur le chemin ordonné : un Voice tué, un écran
    bleu, un arrêt de courant laissent les lignes en place pour toujours, contre
    les 512 de `MAX_SCENE_OBJECTS`, et un `scene_set_visibility(scope="all_hidden")`
    du cerveau les révélerait toutes d'un coup.

    Ce registre existe donc **pour pouvoir les supprimer**, ce qui est l'inverse
    d'une persistance de préparation : il ne porte aucun contenu, aucune parole,
    aucun titre — seulement des identifiants d'objets à reprendre. Il est vidé
    dès que la reprise a eu lieu.

    ## Pourquoi pas un filtre sur la scène

    Reprendre par filtre (`kind=artifact, category=preparation, visibility=hidden`)
    archiverait aussi les objets du cerveau ou de l'utilisateur qui partagent
    cette forme. Une liste d'identifiants **écrits par nous** ne peut atteindre
    que ce que nous avons posé.
    """

    def __init__(self, path: Path, *, journal: RuntimeJournal | None = None) -> None:
        self.path = Path(path)
        self._journal = journal
        self._ids: list[str] = []

    # -- lecture / écriture ------------------------------------------------

    def load(self) -> tuple[str, ...]:
        """Lire le registre. Un fichier absent est le premier démarrage, pas une panne."""

        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # Intentionnel : l'absence du fichier est l'état normal d'un premier
            # lancement et d'un arrêt propre (il est vidé à l'arrêt).
            self._ids = []
            return ()
        except OSError as exc:
            self._trace(
                "ledger_unreadable",
                f"Registre des objets montés illisible : {type(exc).__name__}: {exc}",
                level="error", code="presentation_ledger_unreadable", path=str(self.path),
            )
            self._ids = []
            return ()
        try:
            payload = json.loads(raw)
            values = payload.get("object_ids") if isinstance(payload, dict) else None
            ids = [str(value) for value in values if isinstance(value, str) and value.strip()] if isinstance(values, list) else None
        except (ValueError, TypeError, AttributeError):
            ids = None
        if ids is None:
            # Un fichier abîmé ne doit pas passer pour un registre vide : la
            # différence est « rien à reprendre » contre « on ne sait plus quoi
            # reprendre », et elle se dit.
            self._trace(
                "ledger_corrupt", "Registre des objets montés illisible : contenu inattendu",
                level="error", code="presentation_ledger_corrupt", path=str(self.path),
                bytes=len(raw),
            )
            self._ids = []
            return ()
        self._ids = ids[:MAX_LEDGER_IDS]
        return tuple(self._ids)

    def _write(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"object_ids": self._ids[:MAX_LEDGER_IDS]}), encoding="utf-8",
            )
        except OSError as exc:
            self._trace(
                "ledger_unwritable",
                f"Registre des objets montés non écrit : {type(exc).__name__}: {exc}",
                level="error", code="presentation_ledger_unwritable", path=str(self.path),
            )

    # -- mutations ---------------------------------------------------------

    def add(self, object_id: str) -> None:
        if not isinstance(object_id, str) or not object_id.strip():
            return
        if object_id in self._ids:
            return
        self._ids.append(object_id)
        if len(self._ids) > MAX_LEDGER_IDS:
            # **La fuite est le risque asymétrique, donc elle se dit.** Reprendre
            # deux fois un objet déjà archivé ne coûte rien — la scène répond
            # sans rien changer. Perdre un identifiant, en revanche, laisse une
            # ligne durable dans `scene_objects` que plus rien ne reprendra, et
            # le plafond le faisait en silence. Le service n'en monte que huit
            # (`MAX_STAGED_OBJECTS`), donc atteindre seize signifie qu'une vie
            # précédente n'a pas été reprise : c'est un fait, pas une routine.
            dropped = self._ids[:-MAX_LEDGER_IDS]
            self._trace(
                "ledger_overflow",
                "Registre des objets montés plein : des identifiants ne seront plus repris",
                level="error", code="presentation_ledger_overflow",
                dropped=len(dropped), kept=MAX_LEDGER_IDS, path=str(self.path),
            )
            del self._ids[:-MAX_LEDGER_IDS]
        self._write()

    def remove(self, object_ids: Sequence[str]) -> None:
        wanted = {value for value in object_ids if isinstance(value, str)}
        if not wanted:
            return
        kept = [value for value in self._ids if value not in wanted]
        if len(kept) == len(self._ids):
            return
        self._ids = kept
        self._write()

    def clear(self) -> None:
        self._ids = []
        try:
            self.path.unlink()
        except FileNotFoundError:
            # Intentionnel : ne rien avoir à effacer est un succès.
            pass
        except OSError as exc:
            self._trace(
                "ledger_unwritable",
                f"Registre des objets montés non effacé : {type(exc).__name__}: {exc}",
                level="error", code="presentation_ledger_unwritable", path=str(self.path),
            )

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._ids)

    def _trace(self, event: str, message: str, *, level: str = "info", **data: object) -> None:
        if self._journal is None:
            return
        try:
            self._journal.emit(f"{PRESENTATION_RUNTIME_KIND}.{event}", message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001
            # Intentionnel : un journal en panne ne casse pas la reprise qu'il observe.
            pass


class LedgeredSceneStager:
    """`HiddenSceneStager` qui inscrit ce qu'il pose, pour pouvoir le reprendre.

    L'ordre compte des deux côtés : l'identifiant est inscrit **après** que la
    scène l'a rendu (inscrire avant noterait un objet qui n'existe pas), et
    effacé **après** que l'archivage a réussi (effacer avant perdrait la trace
    d'un objet toujours à l'écran).
    """

    def __init__(self, inner: Any, ledger: StagedObjectLedger) -> None:
        self._inner = inner
        self._ledger = ledger

    async def stage_hidden(self, *, category: str, title: str, summary: str) -> str:
        object_id = await self._inner.stage_hidden(category=category, title=title, summary=summary)
        self._ledger.add(object_id)
        return object_id

    async def reveal(self, object_id: str) -> None:
        await self._inner.reveal(object_id)

    async def discard(self, object_ids: Sequence[str]) -> None:
        await self._inner.discard(object_ids)
        self._ledger.remove(object_ids)

    async def reclaim(self) -> tuple[str, ...]:
        """Reprendre ce qu'un arrêt non propre a laissé. Rendu : ce qui a été repris."""

        pending = self._ledger.load()
        if not pending:
            return ()
        await self._inner.discard(pending)
        self._ledger.clear()
        return pending


# --------------------------------------------------------------------------
# La séance
# --------------------------------------------------------------------------


class PresentationStack:
    """Les cinq sous-systèmes d'une séance PRESENTATION, démarrés ensemble.

    Une séance est **terminale**, comme `PresentationAudioSession` :
    `PresentationAudioSession.stop()` est définitif (Slice 05, B2 — un
    `stop()` puis `start()` donnait une Presentation sourde qui se déclarait
    saine). Repasser en PRESENTATION compose donc une pile neuve, et c'est
    pourquoi le contrôleur reçoit une **fabrique** et non une instance.
    """

    def __init__(
        self,
        *,
        session_id: str,
        store: PresentationWorkingSetStore,
        audio: Any,
        ambient: Any,
        speculative: Any,
        attention: Any,
        turns: Any,
        stager: LedgeredSceneStager | None = None,
        journal: RuntimeJournal | None = None,
    ) -> None:
        if not session_id:
            raise PresentationRuntimeError(
                "presentation_session_required", "Une séance PRESENTATION porte un identifiant."
            )
        self.session_id = session_id
        self.store = store
        self.audio = audio
        self.ambient = ambient
        self.speculative = speculative
        self.attention = attention
        self.turns = turns
        self.stager = stager
        self.journal = journal
        self.started = False
        self.stopped = False
        #: Objets repris au démarrage, après un arrêt non propre. Observable
        #: plutôt que seulement journalisé : un invariant qu'on ne peut pas lire
        #: est un invariant qui dérive (Slice 04).
        self.reclaimed: tuple[str, ...] = ()

    # -- traces -----------------------------------------------------------

    def _trace(self, event: str, message: str, *, level: str = "info", **data: object) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(f"{PRESENTATION_RUNTIME_KIND}.{event}", message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001
            # Intentionnel : même position que la Slice 06 — un journal en panne
            # ne fait pas tomber la séance qu'il observe.
            pass

    # -- cycle de vie ------------------------------------------------------

    async def start(self) -> None:
        """Ouvrir la séance. Le micro d'abord, le reste ensuite.

        L'ordre est le sujet. Le micro est ce qui peut **refuser** — un second
        propriétaire, un périphérique absent —, et il refuse avant que quoi que
        ce soit d'autre n'ait été lié : une séance à moitié ouverte serait un
        état que personne ne sait décrire.
        """

        if self.stopped:
            raise PresentationRuntimeError(
                "presentation_stack_stopped",
                "Cette séance PRESENTATION est arrêtée : composez-en une neuve.",
            )
        if self.started:
            return
        if self.stager is not None:
            # Avant toute chose, et avant qu'un seul objet neuf ne soit posé :
            # ce qu'un arrêt non propre a laissé à l'écran de la séance d'avant.
            try:
                self.reclaimed = await self.stager.reclaim()
            except Exception as exc:  # noqa: BLE001 - une reprise ratée ne bloque pas la séance
                self._trace(
                    "reclaim_failed",
                    f"Reprise des objets montés en échec : {type(exc).__name__}: {exc}",
                    level="error", code="presentation_reclaim_failed",
                )
            else:
                if self.reclaimed:
                    self._trace(
                        "reclaimed",
                        "Objets de scène d'une séance précédente repris au démarrage",
                        level="warning", code="presentation_staged_reclaimed",
                        objects=len(self.reclaimed),
                    )
        await self.audio.start()
        self.store.bind_session(self.session_id)
        self.speculative.bind_session(self.session_id)
        try:
            await self.ambient.start()
        except Exception:
            # La voie ambiante est ce qui rend PRESENTATION *attentive*. Sans
            # elle, garder le micro ouvert et la séance liée donnerait une
            # Presentation qui écoute sans rien entendre — exactement le
            # « positif qui veut dire mort » de la Slice 05.
            await self._teardown("ambient_start_failed")
            raise
        self.started = True
        self._trace(
            "started", "Séance PRESENTATION ouverte : un micro, une mémoire, une voie ambiante",
            session_id=self.session_id,
            physical_input_owners=self.audio.physical_input_owners(),
            reclaimed=len(self.reclaimed),
        )

    async def stop(self, reason: str = "mode_left_presentation") -> None:
        """Fermer la séance. Tout est retiré, même si une étape échoue."""

        if self.stopped:
            return
        self.stopped = True
        await self._teardown(reason)
        self._trace(
            "stopped", "Séance PRESENTATION fermée : rien de la salle ne survit",
            session_id=self.session_id, reason=reason,
            physical_input_owners=self.audio.physical_input_owners(),
        )

    async def _teardown(self, reason: str) -> None:
        """Arrêter chaque moitié, sans qu'un échec en épargne une autre.

        Chaque étape a son propre `try` : une voie ambiante qui refuse de
        s'arrêter ne doit pas laisser le micro ouvert, et un micro qui refuse de
        se fermer ne doit pas laisser la mémoire de la salle en place.
        """

        for label, call in (
            ("ambient", lambda: self.ambient.stop()),
            ("speculative", lambda: self.speculative.stop(reason)),
            ("audio", lambda: self.audio.stop()),
        ):
            try:
                result = call()
                if hasattr(result, "__await__"):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._trace(
                    "teardown_failed",
                    f"Arrêt de « {label} » en échec : {type(exc).__name__}: {exc}",
                    level="error", code="presentation_teardown_failed", part=label,
                )
        # Le retrait du magasin vient en dernier et hors de la boucle : c'est la
        # seule étape qui *doit* réussir, elle est purement en mémoire, et elle
        # est ce qui rend vraie la phrase « rien de ce qui a été dit dans la
        # salle ne survit à la séance ».
        self.store.retire(reason)

    # -- diagnostics -------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Tout ce que la séance sait d'elle-même, en nombres.

        C'est la réponse à « retard de file, arriéré, travaux spéculatifs en
        vol, latence du déclencheur » : les quatre mesures que SLICE.md demande
        sont ici, chacune lue de son propriétaire et jamais recalculée.
        """

        audio = _safe_stats(self.audio)
        ambient = _safe_stats(self.ambient)
        speculative = _safe_stats(self.speculative)
        turns = _safe_stats(self.turns)
        snapshot = getattr(self.store, "snapshot", None)
        lane = audio.get("lane") if isinstance(audio, dict) else None
        return {
            "session_id": self.session_id,
            "started": self.started,
            "stopped": self.stopped,
            "reclaimed": len(self.reclaimed),
            # -- le micro, compté
            "physical_input_owners": audio.get("physical_input_owners") if isinstance(audio, dict) else None,
            # -- latence du déclencheur explicite
            "trigger_latency_s": lane.get("last_delivery_latency_s") if isinstance(lane, dict) else None,
            "trigger_stale_deliveries": lane.get("stale_deliveries") if isinstance(lane, dict) else None,
            "triggers_pending": lane.get("pending") if isinstance(lane, dict) else None,
            # -- arriéré de la voie ambiante
            "segments_pending": ambient.get("segments_pending"),
            "segment_queue": ambient.get("segment_queue"),
            "analysis_pending": ambient.get("analysis_pending"),
            "analysis_queue": ambient.get("analysis_queue"),
            "ambient_deaf": ambient.get("deaf"),
            "ambient_degraded": ambient.get("degraded"),
            # -- retard d'enrichissement, la mesure de la Slice 04
            "enrichment_lag_s": getattr(snapshot, "enrichment_lag_s", None),
            "enrichment_lag_entries": getattr(snapshot, "enrichment_lag_entries", None),
            # -- travaux spéculatifs
            "speculative_in_flight": speculative.get("in_flight"),
            "speculative_free_explicit_slots": speculative.get("free_explicit_slots"),
            "speculative_staged": speculative.get("staged"),
            # -- tours adressés
            "addressed": turns.get("counters"),
            "detail": {
                "audio": audio, "ambient": ambient,
                "speculative": speculative, "turns": turns,
            },
        }

    def emit_diagnostics(self) -> dict[str, Any]:
        """Poser le relevé dans la trace, et le rendre.

        Rendu **et** journalisé : un test lit la valeur, un opérateur lit la
        ligne, et les deux disent la même chose parce qu'il n'y a qu'un calcul.
        """

        payload = self.stats()
        detail = payload.pop("detail", None)
        self._trace(
            "diagnostics",
            "Relevé PRESENTATION : file, arriéré, travaux en vol, latence du déclencheur",
            **payload,
        )
        payload["detail"] = detail
        return payload


def _safe_stats(subject: Any) -> dict[str, Any]:
    """`stats()` d'un sous-système, ou un dictionnaire vide. Ne lève jamais."""

    reader = getattr(subject, "stats", None)
    if not callable(reader):
        return {}
    try:
        value = reader()
    except Exception:  # noqa: BLE001 - un relevé n'est jamais une raison de tomber
        return {}
    return value if isinstance(value, dict) else {}


# --------------------------------------------------------------------------
# L'aiguillage de l'éveil
# --------------------------------------------------------------------------


class PresentationWakeRouter:
    """Le `WakeWordBackend` du processus Voice : SIMPLE, ou la voie d'adresse.

    ## Pourquoi un aiguillage plutôt que deux compositions

    D15 interdit un redémarrage sur changement de mode : le mode bouge à chaud,
    pendant qu'une présentation est en cours. `PersistentVoiceRuntime.run()`
    appelle `detections()` **une fois** et itère jusqu'à l'arrêt. Il faut donc un
    seul objet, dont la source change sous lui.

    ## Ce qu'il fait de plus, et pourquoi c'est ici

    En PRESENTATION il consomme `ExplicitAddressLane.triggers()` — la vue
    **typée**, jumelle de `detections()` et pas une seconde file — et arme le
    tour adressé (`PresentationAddressedTurnService.arm`) avec le déclencheur
    **avant** d'en rendre l'étiquette. C'est la seule place où l'instant gelé du
    déclencheur est encore disponible : plus bas, le bridge ne voit qu'un texte.
    """

    def __init__(
        self,
        *,
        simple: Any,
        journal: RuntimeJournal | None = None,
    ) -> None:
        self.simple = simple
        self.journal = journal
        self._stack: PresentationStack | None = None
        self._switched = asyncio.Event()
        self._iterators: dict[int, AsyncIterator[Any]] = {}
        self._pending: asyncio.Task[Any] | None = None
        self._pending_key: int | None = None
        self._closed = False
        #: Comptes observables : un aiguillage qui se trompe de source doit se
        #: constater, pas se déduire d'un journal.
        self.simple_detections = 0
        self.presentation_detections = 0
        self.armed = 0
        self.arm_failures = 0
        self.switches = 0
        #: Itérateurs jetés à une bascule. Observable parce qu'une fuite ici se
        #: lit autrement comme « le mot d'éveil ne répond plus ».
        self.dropped_iterators = 0

    # -- état --------------------------------------------------------------

    @property
    def stack(self) -> PresentationStack | None:
        return self._stack

    def adopt(self, stack: PresentationStack | None) -> None:
        """Changer de source. Le prochain tour de `detections()` la prendra.

        L'itérateur de l'ancienne source est jeté **ici** et pas seulement dans
        `_drop_pending()`. Celui-ci ne s'exécute que lorsqu'une attente est en
        vol ; une bascule qui arrive entre deux tours laissait donc un
        générateur ouvert dans `_iterators`, indexé par `id(source)` — et cet
        identifiant est réutilisable par un objet neuf après un ramassage,
        ce qui ferait servir un itérateur mort pour une source vivante.
        """

        if stack is self._stack:
            return
        previous = self._stack
        self._stack = stack
        self._forget_iterator(getattr(getattr(previous, "audio", None), "lane", None))
        self.switches += 1
        self._switched.set()

    def _forget_iterator(self, source: Any) -> None:
        """Oublier l'itérateur d'une source qui ne servira plus."""

        if source is None:
            return
        iterator = self._iterators.pop(id(source), None)
        if iterator is not None:
            self.dropped_iterators += 1

    def _source(self) -> Any:
        stack = self._stack
        if stack is None or not stack.started or stack.stopped:
            return self.simple
        return stack.audio.lane

    # -- contrat WakeWordBackend -------------------------------------------

    async def detections(self) -> AsyncIterator[str]:
        """Les éveils, d'où qu'ils viennent. Un seul générateur pour la vie du processus."""

        while not self._closed:
            source = self._source()
            key = id(source)
            if self._pending is not None and self._pending_key != key:
                self._drop_pending()
            if self._pending is None:
                self._pending_key = key
                self._pending = asyncio.create_task(
                    anext(self._iterator(source, key)), name="jarvis-presentation-wake",
                )
            switch = asyncio.create_task(self._switched.wait(), name="jarvis-presentation-wake-switch")
            try:
                done, _ = await asyncio.wait({self._pending, switch}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                switch.cancel()
            if self._pending in done:
                task, self._pending, self._pending_key = self._pending, None, None
                try:
                    value = task.result()
                except StopAsyncIteration:
                    # La source s'est fermée. En SIMPLE c'est la fin du
                    # processus ; en PRESENTATION c'est une séance qui s'arrête,
                    # et le tour suivant reprendra sur SIMPLE.
                    self._iterators.pop(key, None)
                    if source is self.simple:
                        return
                    continue
                yield self._label(source, value)
                continue
            # Le mode a bougé : on repart sur la nouvelle source au tour suivant.
            self._switched.clear()

    def _iterator(self, source: Any, key: int) -> AsyncIterator[Any]:
        iterator = self._iterators.get(key)
        if iterator is None:
            iterator = source.triggers() if source is not self.simple else source.detections()
            self._iterators[key] = iterator
        return iterator

    def _drop_pending(self) -> None:
        """Abandonner l'attente en cours sur l'ancienne source.

        Le générateur abandonné est **jeté** avec elle : annuler un `anext`
        lance `CancelledError` dans le générateur au point d'attente, ce qui le
        ferme. En redemander un neuf au prochain passage est correct pour les
        deux sources — la file de `CompositeWakeWordBackend` survit à son
        générateur, et une lane de PRESENTATION ne revient jamais.
        """

        task, self._pending = self._pending, None
        key, self._pending_key = self._pending_key, None
        if task is not None:
            task.cancel()
        if key is not None:
            self._iterators.pop(key, None)

    def _label(self, source: Any, value: Any) -> str:
        """L'étiquette à rendre, et l'armement du tour adressé quand il y en a un."""

        if source is self.simple:
            self.simple_detections += 1
            return str(value)
        self.presentation_detections += 1
        stack = self._stack
        turns = getattr(stack, "turns", None) if stack is not None else None
        if turns is not None:
            try:
                turns.arm(value)
                self.armed += 1
            except Exception as exc:  # noqa: BLE001 - armer ne doit jamais perdre un appui
                self.arm_failures += 1
                self._trace(
                    "arm_failed",
                    f"Armement du tour adressé en échec : {type(exc).__name__}: {exc}",
                    level="error", code="presentation_arm_failed",
                )
        return str(getattr(value, "label", value))

    # -- délégation --------------------------------------------------------

    # `suspend`/`resume` vont **aux deux** sources, toujours.
    #
    # Les résoudre par `_source()` rendait la paire asymétrique : un changement
    # de mode entre un `suspend_for_active_session()` et le `resume()` qui le
    # solde envoyait les deux à des backends différents, laissant l'un suspendu
    # pour toujours — un mot d'éveil mort, sans une ligne pour le dire.
    #
    # Les deux sont idempotents et sûrs sur une source inactive : la pile de
    # SIMPLE est suspendue pendant toute la séance de toute façon, et une lane
    # fermée refuse proprement. Le coût est un appel de plus ; le bénéfice est
    # qu'aucune bascule ne peut dépareiller la paire.

    async def suspend(self) -> None:
        await self._both("suspend")

    async def suspend_for_active_session(self) -> None:
        await self._both("suspend_for_active_session")

    async def resume(self) -> None:
        await self._both("resume")

    async def _both(self, name: str) -> None:
        """Appeler `name` sur la pile de SIMPLE **et** sur la lane vivante."""

        stack = self._stack
        lane = getattr(getattr(stack, "audio", None), "lane", None) if stack is not None else None
        for source in (self.simple, lane):
            if source is None:
                continue
            try:
                await getattr(source, name)()
            except Exception as exc:  # noqa: BLE001 - l'une en panne ne dispense pas l'autre
                self._trace(
                    "wake_call_failed",
                    f"« {name} » a échoué sur une source d'éveil : {type(exc).__name__}: {exc}",
                    level="error", code="presentation_wake_call_failed", call=name,
                )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._drop_pending()
        self._switched.set()
        await self.simple.close()

    def stats(self) -> dict[str, Any]:
        return {
            "routing": "presentation" if self._source() is not self.simple else "simple",
            "simple_detections": self.simple_detections,
            "presentation_detections": self.presentation_detections,
            "armed": self.armed,
            "arm_failures": self.arm_failures,
            "switches": self.switches,
        }

    def _trace(self, event: str, message: str, *, level: str = "info", **data: object) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(f"{PRESENTATION_RUNTIME_KIND}.{event}", message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001
            # Intentionnel : un journal en panne ne casse pas l'aiguillage.
            pass


# --------------------------------------------------------------------------
# Lecture de l'ensemble de travail, pour l'exécutant
# --------------------------------------------------------------------------


def claims_reader(store: PresentationWorkingSetStore) -> Callable[[str], tuple[PreparationClaim, ...]]:
    """Les affirmations attachées à une énonciation, pour l'exécutant.

    Lecture seule, en mémoire, synchrone : c'est le corollaire direct du choix
    « en processus » écrit en tête de module. Un relais rendrait cette lecture
    bloquante sur la boucle qui porte la voie d'adresse explicite.
    """

    def read(utterance_id: str) -> tuple[PreparationClaim, ...]:
        snapshot = getattr(store, "snapshot", None)
        working_set = getattr(snapshot, "working_set", None)
        claims = getattr(working_set, "claims", ()) or ()
        chosen = [
            PreparationClaim(claim_id=claim.record_id, statement=claim.statement)
            for claim in claims
            if getattr(getattr(claim, "provenance", None), "utterance_id", None) == utterance_id
        ]
        # Rien pour cette énonciation : la vérification porte alors sur ce que la
        # séance retient de plus récent. Une préparation qui ne vérifie rien
        # parce que l'enrichissement a pris une seconde de retard serait une
        # occasion perdue, pas une garantie.
        return tuple(chosen) if chosen else tuple(
            PreparationClaim(claim_id=claim.record_id, statement=claim.statement)
            for claim in claims[-2:]
        )

    return read


def source_recorder(
    store: PresentationWorkingSetStore,
    *,
    session_id: str,
    clock: Callable[[], datetime] = utc_now,
) -> Callable[[ResourceKind, str, str], str | None]:
    """Ranger une source citée et rendre son identifiant, ou `None`.

    C'est ce qui rend `decide_attention` capable de vérifier une provenance
    plutôt que de la croire : l'identifiant cité par un verdict est celui d'un
    enregistrement que le magasin a réellement accepté.

    ## La course d'éviction : ce qui est fermé, et ce qui ne l'est pas

    La collection de sources est bornée à douze (`MAX_WORKING_SET_SOURCES`), et
    deux choses différentes peuvent en découler. Elles n'ont pas le même remède.

    **Ce que la disposition ferme.** Un enregistrement que le magasin refuse —
    plein, périmé, séance close — rend `None`, et c'est ce qui empêche de citer
    un identifiant qui n'est jamais entré. Le cas le plus subtil est couvert par
    là : une source horodatée plus vieux que les douze retenues n'est pas
    acceptée puis évincée, elle est **refusée** en
    `presentation_record_too_old`.

    **Ce qui reste ouvert, et qu'aucune relecture ici ne fermerait.** Entre ce
    rangement et le moment où `decide_attention` vérifie la provenance, d'autres
    préparations rangent les leurs — jusqu'à six travaux concurrents, et une
    énonciation peut en produire quatre. Une source acceptée à l'instant peut
    donc être évincée **avant** le verdict. Relire l'instantané juste après
    `apply()` n'y changerait rien : la fenêtre est *après* le retour de cette
    fonction, pas dedans. Une version de cette Slice ajoutait cette relecture ;
    une mutation a montré qu'elle était du code mort, et elle a été retirée
    plutôt que gardée pour l'apparence de la prudence.

    Le comportement dans ce cas est déjà celui qu'on veut : le juge refuse sous
    `attention_provenance_unknown`, par son nom, et la contradiction n'est pas
    levée. Une alerte perdue, jamais une provenance inventée — le sens dans
    lequel cette voie choisit d'échouer partout ailleurs. C'est écrit dans les
    limites du rapport de la Slice.
    """

    def record(kind: ResourceKind, locator: str, title: str) -> str | None:
        source_id = f"src-{uuid.uuid4().hex[:12]}"
        try:
            observation = PresentationObservation(
                observation_id=source_id,
                session_id=session_id,
                record=PresentationSource(
                    source_id=source_id, kind=kind, reference=locator,
                    title=title, retrieved_at=clock(),
                ),
            )
        except (TypeError, ValueError):
            # Un locator que la Slice 04 refuse : la source n'est pas rangée,
            # donc le verdict partira sans pièce et le juge le refusera par son
            # nom. C'est la bonne fin — jamais une source inventée.
            return None
        result = store.apply(observation)
        return source_id if getattr(result, "applied", False) else None

    return record


# --------------------------------------------------------------------------
# Le contrôleur : ce que le processus Voice tient d'un bout à l'autre
# --------------------------------------------------------------------------


class PresentationCoordinator:
    """Une vie de processus Voice, zéro ou plusieurs séances PRESENTATION.

    Il tient la fabrique, la séance en cours, l'aiguillage d'éveil et le relevé
    de diagnostics. `PersistentVoiceRuntime` ne lui demande que deux choses :
    la capture partagée (`audio`), et le service de tour adressé (`turns`).

    ## Pourquoi une fabrique, et pas une séance

    `PresentationAudioSession.stop()` est **terminal** (Slice 05, B2) : un
    `stop()` suivi d'un `start()` donnait une Presentation sourde qui se
    déclarait saine. SIMPLE ⇄ PRESENTATION doit pouvoir aller et venir sans
    redémarrage (D15), donc chaque entrée compose une pile neuve.

    ## Ce qui se passe quand l'entrée échoue

    Jamais un silence. La ligne part à `error`, la pastille visuelle le dit, la
    pile d'éveil de SIMPLE est reprise, et `audio` rend `None` — donc le bridge
    ouvre son **unique** flux comme en SIMPLE. PRESENTATION reste le mode
    annoncé par Core (ce module ne décide pas du mode), mais l'écoute continue
    n'a pas lieu, et cela se lit.
    """

    def __init__(
        self,
        *,
        router: PresentationWakeRouter,
        build: Callable[[str], "PresentationStack"],
        journal: RuntimeJournal | None = None,
        signals: Any | None = None,
        diagnostics_period_s: float = DIAGNOSTICS_PERIOD_S,
        precondition: Callable[[], str | None] | None = None,
        blockers: tuple[tuple[str, str], ...] = (),
        reclaimer: Callable[[], Any] | None = None,
    ) -> None:
        if not callable(build):
            raise ValueError("build must be a callable returning a PresentationStack")
        self.router = router
        self._build = build
        #: Ce qui doit être vrai du processus **avant** de prendre le micro.
        #: Rend la phrase du refus, ou `None` quand tout va bien. Voir
        #: `_refused_by_precondition`.
        self._precondition = precondition
        #: Blocages nommés, dits une fois à la première entrée (voir
        #: `PresentationComposition.blockers`).
        self._blockers = tuple(blockers)
        self._blockers_said = False
        #: Reprise des objets montés au **démarrage du processus**, sans
        #: attendre une entrée en PRESENTATION. Voir `reclaim_orphans`.
        self._reclaimer = reclaimer
        self.journal = journal
        self.signals = signals
        self.diagnostics_period_s = float(diagnostics_period_s)
        self._stack: PresentationStack | None = None
        self._lock = asyncio.Lock()
        self._applying: asyncio.Task[None] | None = None
        self._pending_mode: object | None = None
        self._diagnostics: asyncio.Task[None] | None = None
        self._closed = False
        #: Observables : entrées réussies, entrées refusées, sorties.
        self.entered = 0
        self.entry_failures = 0
        self.left = 0
        self.last_failure_code: str | None = None

    # -- lecture ----------------------------------------------------------

    @property
    def stack(self) -> "PresentationStack | None":
        stack = self._stack
        return stack if stack is not None and stack.started and not stack.stopped else None

    @property
    def audio(self) -> Any | None:
        """La capture partagée, ou rien. C'est ce que `voice_v2` interroge."""

        stack = self.stack
        return None if stack is None else stack.audio

    @property
    def turns(self) -> Any | None:
        """Le service de tour adressé de la séance en cours, ou rien."""

        stack = self.stack
        return None if stack is None else stack.turns

    @property
    def speculative(self) -> Any | None:
        stack = self.stack
        return None if stack is None else stack.speculative

    # -- le mode ----------------------------------------------------------

    def observe_mode(self, mode: object) -> None:
        """Abonné **synchrone** du mode, appelé par l'observateur de Voice.

        Il ne fait qu'ordonnancer : ouvrir ou fermer une séance demande de
        l'audio, donc des `await`. Une seule application est en vol à la fois,
        et celle qui tourne relit le mode en sortant — ce qui rend un
        aller-retour rapide SIMPLE → PRESENTATION → SIMPLE convergent plutôt
        que sériel, et garantit que le **dernier** mode gagne toujours.
        """

        if self._closed:
            return
        self._pending_mode = mode
        if self._applying is not None and not self._applying.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Hors boucle (construction, arrêt) : rien à ordonnancer. Le mode
            # retenu sera appliqué au prochain passage qui a une boucle.
            return
        self._applying = loop.create_task(self._drain(), name="jarvis-presentation-mode")

    async def _drain(self) -> None:
        """Appliquer le dernier mode connu, jusqu'à ce qu'il ne bouge plus."""

        while not self._closed:
            mode, self._pending_mode = self._pending_mode, None
            if mode is None:
                return
            try:
                await self.apply(mode)
            except Exception as exc:  # noqa: BLE001 - une entrée ratée ne tue pas Voice
                self._trace(
                    "mode_apply_failed",
                    f"Application du mode PRESENTATION en échec : {type(exc).__name__}: {exc}",
                    level="error", code="presentation_mode_apply_failed",
                )

    async def apply(self, mode: object) -> None:
        """Ouvrir ou fermer la séance pour ce mode. Sérialisé, idempotent."""

        async with self._lock:
            if self._closed:
                return
            wanted = behaving_interaction_mode(mode) is InteractionMode.PRESENTATION
            if wanted and self._stack is None:
                await self._enter()
            elif not wanted and self._stack is not None:
                await self._leave("mode_left_presentation")

    # -- entrée / sortie ---------------------------------------------------

    async def _enter(self) -> None:
        """Suspendre SIMPLE, **puis** ouvrir la séance. Jamais l'inverse.

        L'ordre est ce qui tient « un seul micro » : la pile d'éveil de SIMPLE
        possède un flux Porcupine, et `PresentationAudioSession.start()` compte
        les propriétaires avant d'ouvrir le sien. Suspendre après ouvrirait le
        hub sur un périphérique déjà pris.
        """

        refusal = self._refused_by_precondition()
        if refusal is not None:
            # **Avant** de toucher au micro : une architecture qui ne peut pas
            # servir un tour adressé ne doit pas se retrouver avec la salle
            # ouverte et personne pour l'écouter.
            self.entry_failures += 1
            self.last_failure_code = "presentation_architecture_unsupported"
            self._trace(
                "entry_refused", refusal, level="error",
                code=self.last_failure_code,
                physical_input_owners=None,
            )
            self._alert(refusal)
            return
        await self._suspend_simple()
        session_id = new_session_id()
        stack = self._build(session_id)
        try:
            await stack.start()
        except Exception as exc:  # noqa: BLE001 - l'échec est dit, jamais avalé
            self.entry_failures += 1
            self.last_failure_code = str(getattr(exc, "code", type(exc).__name__))
            self._trace(
                "entry_failed",
                f"PRESENTATION n'a pas pu prendre le micro : {type(exc).__name__}: {exc}. "
                "L'ecoute continue n'a pas lieu ; les tours passent par le micro direct.",
                level="error", code=self.last_failure_code,
                physical_input_owners=_owner_count(stack),
            )
            self._alert(
                "PRESENTATION n'a pas pu ouvrir le micro partagé. "
                "JARVIS reste adressable, mais n'écoute pas la salle."
            )
            try:
                await stack.stop("entry_failed")
            except Exception:  # noqa: BLE001
                # Intentionnel : la pile n'a jamais démarré ; l'échec de son
                # arrêt est déjà journalisé par `_teardown`, et il ne doit pas
                # empêcher la reprise de SIMPLE juste en dessous.
                pass
            await self._resume_simple()
            return
        self._stack = stack
        self.entered += 1
        self._say_blockers()
        self.router.adopt(stack)
        self._start_diagnostics()
        self._alert(None)
        self._trace(
            "entered", "PRESENTATION écoute la salle : un micro, une séance",
            session_id=session_id, physical_input_owners=_owner_count(stack),
        )

    def _say_blockers(self) -> None:
        """Dire les blocages nommés, une fois, au moment où ils comptent."""

        if self._blockers_said or not self._blockers:
            return
        self._blockers_said = True
        for code, message in self._blockers:
            self._trace("blocked", message, level="warning", code=code)

    async def _leave(self, reason: str) -> None:
        """Fermer la séance, **puis** reprendre SIMPLE."""

        stack, self._stack = self._stack, None
        self.router.adopt(None)
        await self._stop_diagnostics()
        if stack is not None:
            try:
                await stack.stop(reason)
            except Exception as exc:  # noqa: BLE001
                self._trace(
                    "exit_failed",
                    f"Fermeture de la séance PRESENTATION en échec : {type(exc).__name__}: {exc}",
                    level="error", code="presentation_exit_failed",
                )
        self.left += 1
        await self._resume_simple()
        self._trace(
            "left", "PRESENTATION rendue : le micro repart au chemin de SIMPLE",
            reason=reason, physical_input_owners=_owner_count(stack),
        )

    def _refused_by_precondition(self) -> str | None:
        """La phrase du refus, ou `None`. Ne lève jamais.

        ## Pourquoi cette porte existe

        Le tour adressé passe par `SpeechScheduler`, et `PersistentVoiceRuntime`
        n'en construit un que lorsqu'une session ACTIVE couvre plusieurs tours
        (`continuous`). Sur `voice_arch=legacy`, il n'y en a pas : le bridge
        reçoit `on_addressed_turn=None` et le tour adressé ne s'ouvre **jamais**.

        Sans cette porte, entrer en PRESENTATION là-bas ouvrait le micro de la
        salle, lançait la voie ambiante et la préparation spéculative — et
        laissait l'utilisateur sans aucun moyen d'être servi. C'est exactement
        « rendre Presentation spécifique à une architecture en silence », que
        `SLICE.md` interdit, et c'est la forme du défaut de la Slice 07 que
        cette Slice avait pour consigne de ne pas répéter.

        Refuser **avant** de prendre le micro est ce qui rend l'échec lisible :
        JARVIS reste exactement ce qu'il était, et la ligne dit quoi changer.
        """

        if self._precondition is None:
            return None
        try:
            refusal = self._precondition()
        except Exception as exc:  # noqa: BLE001 - une pré-condition en panne ne prend pas le micro
            return (
                f"Impossible de vérifier que cette architecture vocale peut servir un tour "
                f"adressé ({type(exc).__name__}: {exc}) : PRESENTATION ne prend pas le micro."
            )
        return refusal if isinstance(refusal, str) and refusal.strip() else None

    async def _suspend_simple(self) -> None:
        try:
            await self.router.simple.suspend()
        except Exception as exc:  # noqa: BLE001 - dit, puis la séance refusera d'elle-même
            self._trace(
                "simple_suspend_failed",
                f"Pile d'éveil de SIMPLE non suspendue : {type(exc).__name__}: {exc}. "
                "La séance PRESENTATION refusera si un second flux reste ouvert.",
                level="error", code="presentation_simple_suspend_failed",
            )

    async def _resume_simple(self) -> None:
        try:
            await self.router.simple.resume()
        except Exception as exc:  # noqa: BLE001
            self._trace(
                "simple_resume_failed",
                f"Pile d'éveil de SIMPLE non reprise : {type(exc).__name__}: {exc}. "
                "Le mot d'éveil peut être perdu ; la touche manuelle reste.",
                level="error", code="presentation_simple_resume_failed",
            )

    # -- diagnostics -------------------------------------------------------

    def _start_diagnostics(self) -> None:
        if self.diagnostics_period_s <= 0 or self._diagnostics is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - `_enter` tourne toujours dans une boucle
            return
        self._diagnostics = loop.create_task(
            self._diagnostics_loop(), name="jarvis-presentation-diagnostics",
        )

    async def _diagnostics_loop(self) -> None:
        """Poser un relevé tant que la séance vit. Le chemin **attendu** est journalisé.

        C'est la règle « ne journaliser que les pannes rend "rien dans le
        journal" indiscernable de "c'est mort" » appliquée à une fonctionnalité
        dont le comportement normal est le **silence**.
        """

        while True:
            await asyncio.sleep(self.diagnostics_period_s)
            stack = self.stack
            if stack is None:
                return
            stack.emit_diagnostics()

    async def _stop_diagnostics(self) -> None:
        task, self._diagnostics = self._diagnostics, None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    # -- reprise au démarrage du processus ---------------------------------

    async def reclaim_orphans(self) -> tuple[str, ...]:
        """Reprendre ce qu'un arrêt brutal a laissé, **au démarrage de Voice**.

        La reprise vivait seulement à l'entrée en PRESENTATION. Un opérateur
        dont Voice est tué pendant une présentation, et qui repasse ensuite des
        semaines en SIMPLE, gardait donc ses objets fantômes à l'écran — la
        seule chose que ce registre existe pour empêcher, laissée dépendre du
        geste que personne ne refait.

        Sûre à appeler deux fois : archiver un objet déjà archivé fait répondre
        la scène sans rien changer. C'est pour cela qu'elle s'ajoute à la
        reprise d'entrée au lieu de la remplacer — la fuite est le risque
        asymétrique, la double reprise n'en est pas un.
        """

        if self._closed or self._reclaimer is None:
            return ()
        try:
            reclaimed = await self._reclaimer()
        except Exception as exc:  # noqa: BLE001 - une reprise ratée ne bloque pas Voice
            self._trace(
                "reclaim_failed",
                f"Reprise des objets montés au démarrage en échec : {type(exc).__name__}: {exc}",
                level="error", code="presentation_reclaim_failed",
            )
            return ()
        if reclaimed:
            self._trace(
                "reclaimed",
                "Objets de scène d'une vie précédente repris au démarrage de Voice",
                level="warning", code="presentation_staged_reclaimed",
                objects=len(reclaimed),
            )
        return tuple(reclaimed)

    # -- arrêt -------------------------------------------------------------

    async def aclose(self, reason: str = "voice_stopped") -> None:
        """Fermer ce que le processus laisse : la séance, puis les tâches.

        C'est le chemin **ordonné**. Ce qu'un arrêt brutal laisse est repris au
        démarrage suivant par `StagedObjectLedger` ; les deux existent parce que
        l'un ne couvre pas l'autre.
        """

        if self._closed:
            return
        self._closed = True
        task, self._applying = self._applying, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self._lock:
            if self._stack is not None:
                await self._leave(reason)
            else:
                await self._stop_diagnostics()

    # -- observabilité -----------------------------------------------------

    def stats(self) -> dict[str, Any]:
        stack = self.stack
        return {
            "entered": self.entered,
            "entry_failures": self.entry_failures,
            "left": self.left,
            "last_failure_code": self.last_failure_code,
            "active": stack is not None,
            "router": self.router.stats(),
            "session": stack.stats() if stack is not None else None,
        }

    def _alert(self, message: str | None) -> None:
        if self.signals is None:
            return
        try:
            self.signals.alert(message)
        except Exception:  # noqa: BLE001
            # Intentionnel : la pastille visuelle est un supplément, la ligne de
            # journal est le récit ; perdre l'une ne doit pas perdre l'autre.
            pass

    def _trace(self, event: str, message: str, *, level: str = "info", **data: object) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(
                f"{PRESENTATION_RUNTIME_KIND}.{event}", message, level=level, data=dict(data),
            )
        except Exception:  # noqa: BLE001
            # Intentionnel : un journal en panne ne casse pas le contrôleur.
            pass


def _owner_count(stack: "PresentationStack | None") -> int | None:
    """Le compte de flux d'entrée physiques, ou `None` s'il n'est pas lisible."""

    audio = getattr(stack, "audio", None)
    reader = getattr(audio, "physical_input_owners", None)
    if not callable(reader):
        return None
    try:
        return int(reader())
    except Exception:  # noqa: BLE001 - un compte illisible ne casse pas une trace
        return None


# --------------------------------------------------------------------------
# La composition, en un seul endroit
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PresentationComposition:
    """Tout ce qu'une séance PRESENTATION a besoin de savoir du processus.

    Elle est une **donnée**, pas un appel : le composition root de Voice
    (`jarvis/app.py`) la remplit une fois, et chaque entrée en PRESENTATION en
    fait une pile neuve. C'est ce qui rend la composition de production
    testable sans processus Voice — un test construit la même dataclasse avec
    des doubles et obtient exactement la pile qui part en production.

    `transcriber` est le seul membre qui peut manquer. Sans lui, la voie
    ambiante n'existe pas : c'est le **blocage nommé** des piles vocales sans
    clé OpenAI (Gemini Live), et il est déclaré ici plutôt que découvert au
    premier segment.
    """

    runtime_root: Path
    cwd: Path
    journal: RuntimeJournal
    mode: Callable[[], object]
    manual_key: str = "f9"
    keyword: str = "jarvis"
    wake_access_key: str = ""
    device: int | str | None = None
    sample_rate: int = 24000
    transcriber: Any | None = None
    scene_tools_factory: Callable[[], Any] | None = None
    agent_factory: Callable[[tuple[str, ...]], Any] | None = None
    ledger_path: Path | None = None
    #: Ouvreur de flux d'entrée. `None` : `sounddevice`, c'est-à-dire la
    #: production. Un test injecte un faux périphérique par là, et c'est le
    #: **même** chemin de composition qui part en production — ce qui est tout
    #: l'intérêt d'avoir fait de la composition une donnée.
    stream_factory: Any | None = None
    #: Fabrique de la touche manuelle. `None` : `KeyboardWakeWordBackend`, qui
    #: demande `pynput` et pose un crochet clavier global au démarrage.
    manual_backend_factory: Callable[[], Any] | None = None
    #: L'horloge du déclencheur. Elle **doit** être celle dont
    #: `ExplicitAddressLane` se sert pour geler ses instants, sans quoi le tour
    #: adressé refuse de mesurer et la télémétrie part blanche (Slice 10).
    clock: Callable[[], float] = time.monotonic
    #: Blocages nommés constatés à la composition : `(code, phrase)`.
    #:
    #: **Portés plutôt que journalisés tout de suite.** Ils sont découverts au
    #: démarrage de Voice, où la composition est bâtie — mais les dire là
    #: mettrait deux `warning` par lancement dans la trace d'un opérateur qui
    #: restera en SIMPLE toute sa vie, pour une fonctionnalité qu'il n'emploie
    #: pas. D14 demande que SIMPLE ne régresse pas, et une trace qui se remplit
    #: est une régression. Le contrôleur les dit **une fois**, à la première
    #: entrée en PRESENTATION, c'est-à-dire au moment où ils comptent.
    blockers: tuple[tuple[str, str], ...] = ()

    def build(self, session_id: str) -> PresentationStack:
        """Composer une séance. Rien n'est démarré ici."""

        from jarvis.adapters.wakeword_keyboard import KeyboardWakeWordBackend
        from jarvis.adapters.wakeword_shared_pcm import porcupine_engine_factory
        from jarvis.runtime.presentation_audio import PresentationAudioSession
        from jarvis.runtime.presentation_preparation import PresentationPreparationRunner

        store = PresentationWorkingSetStore(diagnostics=self.journal)
        audio = PresentationAudioSession.build(
            # Une touche manuelle **neuve** par séance, jamais celle de la pile
            # de SIMPLE : `CompositeWakeWordBackend` garde une tâche de pompage
            # par enfant, et partager l'objet ferait consommer la même file par
            # deux consommateurs — un appui sur deux perdu, en silence.
            manual_backend=(
                self.manual_backend_factory() if self.manual_backend_factory is not None
                else KeyboardWakeWordBackend(key_name=self.manual_key)
            ),
            wake_engine_factory=(
                porcupine_engine_factory(access_key=self.wake_access_key, keyword=self.keyword)
                if self.wake_access_key else None
            ),
            keyword=self.keyword,
            sample_rate=self.sample_rate,
            device=self.device,
            stream_factory=self.stream_factory,
            journal=self.journal,
        )
        # L'horloge du service **est** celle de la lane, par construction et non
        # par convention : c'est le piège que la Slice 10 a légué à celle-ci.
        audio.lane.clock = self.clock
        attention = PresentationAttentionService(store=store, diagnostics=self.journal)
        stager = self._stager()
        runner = PresentationPreparationRunner(
            agent_factory=self.agent_factory,
            record_source=source_recorder(store, session_id=session_id),
            claims_for=claims_reader(store),
            journal=self.journal,
        ) if self.agent_factory is not None else None
        speculative = PresentationSpeculativeService(
            store=store,
            runner=runner if runner is not None else _AbsentRunner(self.journal),
            stager=stager,
            attention=attention,
            diagnostics=self.journal,
        )
        ambient = AmbientIngestionLane(
            hub=audio.hub,
            transcriber=self.transcriber if self.transcriber is not None else _AbsentTranscriber(),
            sink=store,
            session_id=session_id,
            journal=self.journal,
            on_trigger=speculative.submit_trigger,
        )
        turns = PresentationAddressedTurnService(
            store=store,
            speculative=speculative,
            mode=self.mode,
            diagnostics=self.journal,
            clock=self.clock,
        )
        return PresentationStack(
            session_id=session_id, store=store, audio=audio, ambient=ambient,
            speculative=speculative, attention=attention, turns=turns,
            stager=stager, journal=self.journal,
        )

    def reclaimer(self) -> Callable[[], Any] | None:
        """La reprise des objets montés, utilisable **sans composer de séance**.

        Le contrôleur l'appelle au démarrage de Voice. Elle bâtit son propre
        monteur, parce que reprendre ne demande ni micro, ni voie ambiante, ni
        magasin — seulement la scène et le registre.
        """

        if self.scene_tools_factory is None:
            return None

        async def reclaim() -> tuple[str, ...]:
            stager = self._stager()
            return () if stager is None else await stager.reclaim()

        return reclaim

    def _stager(self) -> LedgeredSceneStager | None:
        if self.scene_tools_factory is None:
            return None
        from jarvis.runtime.presentation_staging import DisplaySceneStager

        ledger = StagedObjectLedger(
            self.ledger_path or (self.runtime_root / "presentation-staged-objects.json"),
            journal=self.journal,
        )
        return LedgeredSceneStager(
            DisplaySceneStager(self.scene_tools_factory(), journal=self.journal), ledger,
        )


class _AbsentRunner:
    """L'exécutant qu'on n'a pas. Il refuse, et il dit pourquoi, une fois par travail.

    Un `None` aurait été refusé par `PresentationSpeculativeService`, dont le
    port `runner` est obligatoire ; un objet qui lève sans rien dire aurait
    donné un compteur `failed` sans cause. Celui-ci nomme la sienne.
    """

    def __init__(self, journal: RuntimeJournal | None = None) -> None:
        self._journal = journal
        self.refused = 0
        self._said = False

    async def prepare(self, request: Any) -> Any:
        from jarvis.core.presentation_speculative import SpeculativeOutcome

        self.refused += 1
        # **Une fois, pas une par travail.** L'absence d'exécutant est un
        # blocage nommé et permanent : avec quatre déclencheurs par énonciation
        # (`MAX_TRIGGERS_PER_UTTERANCE`), le dire à chaque travail met quatre
        # `warning` par phrase entendue dans la trace, en continu, pour une
        # condition qui ne changera pas de la séance. C'est la même correction
        # qu'à `PresentationPreparationRunner._cli_tools`, et la même leçon
        # qu'à la Slice 02 : une trace que personne ne peut lire ne dit plus
        # rien. Le **compte** reste exact dans `refused`.
        if self._journal is not None and not self._said:
            self._said = True
            try:
                self._journal.emit(
                    f"{PRESENTATION_RUNTIME_KIND}.runner_absent",
                    "Aucun exécutant de préparation n'est configuré : les travaux rendent le vide",
                    level="warning",
                    data={"code": "presentation_runner_absent",
                          "job_id": getattr(request, "job_id", "")},
                )
            except Exception:  # noqa: BLE001
                # Intentionnel : un journal en panne ne change pas le refus.
                pass
        return SpeculativeOutcome()


class _AbsentTranscriber:
    """La transcription qu'on n'a pas. Elle lève, et la lane le compte.

    `AmbientIngestionLane` traite un transcripteur qui lève comme une panne
    nommée : elle compte, journalise, et devient **sourde** après trois échecs
    rapprochés — un état lisible, pas un silence. C'est exactement ce qu'on
    veut d'une pile vocale sans clé de transcription, et c'est pourquoi la
    lane est construite quand même plutôt qu'omise : « la voie ambiante est
    sourde parce qu'il n'y a pas de transcription » se lit dans `stats()`,
    « il n'y a pas de voie ambiante » ne se lit nulle part.
    """

    async def transcribe(self, audio: Any) -> Any:
        raise RuntimeError(
            "Aucun fournisseur de transcription n'est configuré pour la voie ambiante."
        )
