"""Le tour adressé prioritaire : armé, ouvert, servi, et rendu à l'ambiant.

Handoff `jarvis-presentation-interaction-mode`, Slice 10. Ce service est ce qui
se passe entre un `ExplicitAddressTrigger` (Slice 05) et l'écran ou la phrase qui
répond. Il ne parle pas lui-même, n'ouvre aucun micro, ne lance aucun modèle : il
**décide** ce que le tour vise, ce qu'il réutilise, et ce qu'il laisse au cerveau.

D04 — l'admission ne peut pas attendre l'ambiant, et ce n'est pas une promesse
------------------------------------------------------------------------------

`arm()` et `open()` sont **synchrones**. Pas « rapides » : synchrones. Une
fonction sans `await` ne peut pas céder la boucle, donc aucun travail ambiant,
aucune transcription en vol, aucune préparation spéculative ne peut s'intercaler
entre le déclencheur et l'instantané de contexte. C'est la même forme
structurelle que l'admission de la lane de la Slice 05, et c'est ce qui rend la
garantie vérifiable autrement que par un chronomètre : un test d'AST refuse un
`await` dans ces deux méthodes, et un test de charge mesure la latence sous un
arriéré **constaté saturé** plutôt que supposé.

Ce que ce service **ne** prouve **pas**, et il faut le dire ici parce que la
Slice 08 s'est fait reprendre dessus : `free_explicit_slots` est honnête sur la
table de la voie spéculative et **n'est pas** une preuve que le tour adressé a de
la capacité. La capacité d'exécution du tour adressé est le sémaphore de
`OwnedJobExecution` (`asyncio.Semaphore(1)`), que la voie spéculative ne voit
pas et que cette Slice ne touche pas. Ce que fait ce service pour D08, et rien
de plus : appeler `note_addressed_turn()`, qui sacrifie du spéculatif pour
libérer une place **dans cette voie-là**.

D06 — la précédence est dans le domaine, pas ici
-------------------------------------------------

`jarvis/domain/presentation_addressed_turn.py` porte la règle et son argument :
le référent est toujours l'énonciation la plus récente du fil, une ressource
préparée ne répond que si elle est ancrée à ce référent, et la comparaison se
fait sur le rang attribué par le magasin — donc un cache ne peut pas annoncer un
rang que le fil ne détient pas. Ce service applique, il ne redécide pas.

D09/D10 — la politique de parole est celle de la Slice 07
----------------------------------------------------------

Le classement (`classify_addressed_situation`) et l'admission
(`admit_presentation_speech`) sont **injectés depuis le domaine**, pas recopiés.
La matrice reste la vérité entière. Une commande visuelle se termine sans un mot ;
une vraie question peut parler ; une clarification passe parce que la Slice 07 a
mis `QUESTION` dans les natures de sûreté de `VISUAL_COMMAND`. Si un jour elle
ne passait plus, ce service ne se tairait pas en silence : il compte le refus, le
dit, et rafraîchit plutôt que de montrer le mauvais écran.

Les deux fonctions sont des **champs** et non des appels directs, pour la raison
que la Slice 07 a écrite pour son propre classement : une garde qu'aucun test ne
peut faire échouer n'est pas une garde, c'est un vœu.

Ce qu'il rend, et ce qu'il ne lève pas
---------------------------------------

Toute entrée publique rend une valeur typée. Aucune ne laisse fuir d'exception —
et cette phrase est un **cas de test**, pas une promesse (leçon de la Slice 04,
répétée par la Slice 09) : le magasin qui lève, la voie spéculative qui lève, le
classement qui lève, le journal qui lève et l'horloge qui recule sont chacun
exercés dans l'état où ils font mal.

Ce qui ne rentre jamais dans une trace
---------------------------------------

Aucune parole. La projection a **deux** sorties nommées différemment :
`to_brain_context()` porte le fil récent, les libellés, les affirmations et le
`reason` d'un point d'attention — c'est ce que le modèle reçoit, en mémoire —
et `to_trace_payload()` porte des comptes, des identifiants et des codes. Seule
la seconde atteint le journal, et un test d'AST interdit tout appel de
`to_payload` dans les deux modules de la Slice, ce qui ferme la voie de la
Slice 09 (`AttentionItem.to_payload()` → … → `PresentationContextSnapshot
.to_payload()`) par construction plutôt que par absence.

Comme la Slice 08, et pour la même raison, les lignes d'échec portent
`error_class` et un code stable, **jamais** le texte de l'exception : le chemin
de rafraîchissement remet le texte du tour à la voie spéculative, et un appelant
qui recopierait son entrée dans un message d'erreur déposerait de la parole dans
un fichier durable. Le texte complet d'une panne appartient au canal de ce qui
l'a produite.

Rien n'est câblé
----------------

Aucun composition root ne construit ce service, exactement comme la session audio
(05), la lane ambiante (06), la voie spéculative (08) et le juge d'attention
(09). La Slice 11 branche ; la liste de ce qu'elle doit brancher est dans le
rapport de la Slice.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from jarvis.core.latency import LatencyTracker
from jarvis.core.voice_state import VoiceStateDisposition
from jarvis.domain.explicit_address import ExplicitAddressTrigger
from jarvis.domain.interaction_mode import InteractionMode, behaving_interaction_mode
from jarvis.domain.output_disposition import OutputDisposition
from jarvis.domain.presentation_addressed_turn import (
    DEFAULT_PREROLL_S,
    MAX_ADDRESSED_CONTEXT_CHARS,
    MAX_ADDRESSED_WINDOW_S,
    AddressedTurnAction,
    AddressedTurnContext,
    AddressedWindow,
    PresentationAddressedTurnError,
    ResourceResolution,
    ResourceVerdict,
    build_addressed_turn_context,
    decide_action,
    deictic_marker,
    resolve_prepared_resource,
    resolve_referent,
)
from jarvis.domain.presentation_policy import PresentationSituation
from jarvis.domain.presentation_response import (
    admit_presentation_speech,
    classify_addressed_situation,
)
from jarvis.domain.presentation_speculative import SpeculativeCapability
from jarvis.domain.presentation_working_set import ResourceKind
from jarvis.domain.v2 import SpeechKind, utc_now
from jarvis.ports.v2 import DiagnosticSink

#: Préfixe des lignes de journal de cette voie, sur le modèle de
#: `presentation.working_set.*`, `presentation.ambient.*` et
#: `presentation.speculative.*`.
ADDRESSED_KIND = "presentation.addressed"

#: Les trois mesures de cette Slice. Elles vivent **ici** et non dans
#: `LATENCY_MEASURES` : cette liste-là est l'inventaire exhaustif des six mesures
#: du handoff realtime-brain, elle est consommée par le testlab et un test la
#: fige à six. Le chronomètre, lui, est réutilisé tel quel.
#:
#: Ce que chacune borne, **exactement** — parce qu'une latence dont on ne sait
#: pas ce qu'elle mesure est un chiffre, pas une mesure :
#:
#: - `TRIGGER_TO_ADMISSION` : de l'estampille posée par la lane d'adresse
#:   explicite au moment où `open()` a fini de construire la projection du tour.
#:   C'est du travail en processus, sans E/S ; c'est la grandeur que D04 oblige
#:   à borner et la seule des trois que cette Slice contrôle de bout en bout ;
#: - `TRIGGER_TO_VISIBLE` : de la même estampille au moment où l'appelant
#:   déclare qu'une **réaction visible** a eu lieu. Ce n'est pas « un pixel a
#:   changé » : c'est le retour de l'appel qui l'a demandée. La distance qui
#:   reste entre ce point et l'œil de l'utilisateur appartient à la scène et au
#:   navigateur ;
#: - `TRIGGER_TO_AUDIBLE` : de la même estampille au moment où l'appelant
#:   déclare une **réaction audible**. La Slice 11 la fermera à l'entrée en file
#:   de la parole ou à la première trame jouée ; ce module ne choisit pas pour
#:   elle, il rend la mesure et dit ce qu'elle vaudra selon le point choisi.
#:
#: Les deux bornes de chaque mesure sont sur **une seule** horloge monotone, dans
#: **un seul** processus — la même contrainte que `LatencyTracker` s'impose déjà.
TRIGGER_TO_ADMISSION = "explicit_trigger_to_addressed_admission"
TRIGGER_TO_VISIBLE = "explicit_trigger_to_visible_reaction"
TRIGGER_TO_AUDIBLE = "explicit_trigger_to_audible_reaction"

ADDRESSED_LATENCY_MEASURES: tuple[str, ...] = (
    TRIGGER_TO_ADMISSION,
    TRIGGER_TO_VISIBLE,
    TRIGGER_TO_AUDIBLE,
)

#: Capacités ouvertes à un rafraîchissement demandé par un tour explicite. Le
#: montage d'un objet de scène (`STAGING_CAPABILITY`) en fait partie **parce que
#: l'origine est adressée** : un jeton ambiant qui la porterait ne peut pas se
#: construire (Slice 08). C'est exactement le cas que `reserve_explicit` existe
#: pour servir.
REFRESH_CAPABILITIES: tuple[SpeculativeCapability, ...] = (
    SpeculativeCapability.DISPLAY_PREPARATION,
    SpeculativeCapability.DOCUMENT_RESOLUTION,
)

#: Recopie maximale d'une valeur dans une ligne de journal. Même borne que la
#: Slice 04 et que le Control Center : un identifiant hostile ne fait pas
#: grossir le journal.
MAX_JOURNALLED_VALUE_CHARS = 64


def _short(value: object) -> str:
    return str(value)[:MAX_JOURNALLED_VALUE_CHARS]


def _trigger_key(trigger: ExplicitAddressTrigger) -> str:
    """Identité d'un déclencheur pour le chronomètre.

    Le rang est strictement croissant dans une lane, donc deux appuis ne
    partagent jamais la même clé — y compris quand ils partagent la même valeur
    de `time.monotonic()`, ce qui arrive sous Windows où la résolution est finie.
    C'est la raison pour laquelle `sequence` existe (Slice 05).
    """

    return f"trigger-{trigger.source.value}-{trigger.sequence}"


@dataclass(frozen=True, slots=True)
class AddressedTurnPlan:
    """Ce qu'un tour adressé a décidé, avant d'avoir rien fait."""

    correlation_id: str
    window: AddressedWindow
    context: AddressedTurnContext
    action: AddressedTurnAction
    #: Latence déclencheur → admission, en millisecondes. `None` quand elle n'a
    #: pas pu être mesurée honnêtement (horloges mélangées) : un `None` dit
    #: qu'on ne sait pas, un zéro dirait qu'on sait que c'était instantané.
    admission_latency_ms: float | None = None

    @property
    def situation(self) -> PresentationSituation:
        return self.context.situation

    @property
    def disposition(self) -> OutputDisposition:
        return self.context.disposition

    @property
    def resource_id(self) -> str:
        return self.context.resource.resource_id

    def to_trace_payload(self) -> dict[str, Any]:
        return {
            "correlation_id": _short(self.correlation_id),
            "action": self.action.value,
            "admission_latency_ms": self.admission_latency_ms,
            **self.window.to_trace_payload(),
            **self.context.to_trace_payload(),
        }


@dataclass(frozen=True, slots=True)
class AddressedTurnResult:
    """Réponse typée d'`arm()` et d'`open()`. Vocabulaire de la Slice 04.

    `VoiceStateDisposition` est réutilisé tel quel plutôt que redécliné : la
    question posée est la même — « est-ce que ça a été pris, et sinon pourquoi » —
    et deux vocabulaires pour une même question finissent par diverger.
    """

    disposition: VoiceStateDisposition
    code: str
    plan: AddressedTurnPlan | None = None

    @property
    def applied(self) -> bool:
        return self.disposition is VoiceStateDisposition.APPLIED


@dataclass(frozen=True, slots=True)
class AddressedTurnOutcome:
    """Ce que la livraison a produit. Jamais une exception, toujours une valeur."""

    action: AddressedTurnAction
    delivered: bool
    code: str
    resource_id: str = ""
    #: Vrai seulement si la matrice admet la parole de clarification. C'est une
    #: lecture de la matrice, pas une décision de ce module.
    speaks: bool = False
    speech_kind: SpeechKind | None = None

    def to_trace_payload(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "delivered": self.delivered,
            "code": self.code,
            "resource_id": _short(self.resource_id),
            "speaks": self.speaks,
            "speech_kind": None if self.speech_kind is None else self.speech_kind.value,
        }


@dataclass(frozen=True, slots=True)
class AddressedTurnSettlement:
    """Le solde d'un tour : où en est la séance **après** lui.

    Rendu comme une valeur et pas seulement journalisé, parce qu'un test doit
    pouvoir affirmer « la séance est restée en PRESENTATION » sans lire un
    journal — c'est la leçon d'invariante inobservable de la Slice 04.
    """

    still_presentation: bool
    session_active: bool
    session_id: str | None
    generation: int
    mode: InteractionMode

    def to_trace_payload(self) -> dict[str, Any]:
        return {
            "still_presentation": self.still_presentation,
            "session_active": self.session_active,
            "session_id": _short(self.session_id) if self.session_id else None,
            "generation": self.generation,
            "mode": self.mode.value,
        }


@dataclass
class AddressedTurnCounters:
    """Tout ce qui s'est passé, en nombres. Aucun texte, aucun identifiant."""

    armed: int = 0
    rearmed: int = 0
    stale_triggers: int = 0
    opened: int = 0
    refused: int = 0
    windows_expired: int = 0
    reused: int = 0
    revealed: int = 0
    refreshed: int = 0
    clarified: int = 0
    brain_turns: int = 0
    clarification_withheld: int = 0
    classification_failures: int = 0
    context_failures: int = 0
    store_failures: int = 0
    speculative_failures: int = 0
    preempted: int = 0
    reveal_failures: int = 0
    refresh_failures: int = 0
    latency_clock_mismatch: int = 0
    diagnostic_failures: int = 0
    settled: int = 0
    settled_outside_presentation: int = 0
    #: Une entrée par disposition rendue par le magasin de la Slice 04. Les sept
    #: sont pré-déclarées : un compteur qui n'apparaît qu'une fois rencontré ne
    #: permet pas de distinguer « jamais arrivé » de « jamais compté ».
    store_dispositions: dict[str, int] = field(
        default_factory=lambda: {item.value: 0 for item in VoiceStateDisposition}
    )
    #: Une entrée par disposition rendue par la voie spéculative (Slice 08).
    speculative_admissions: dict[str, int] = field(default_factory=dict)

    def to_trace_payload(self) -> dict[str, Any]:
        """Nommée comme les autres sorties de trace de la Slice, et **pas**
        `to_payload` : ce nom-là est celui des sérialiseurs d'instantané que la
        garde d'AST interdit d'appeler ici. Une méthode homonyme obligerait la
        garde à porter une exception, et une garde à exception est une garde
        qu'on finira par élargir."""

        return {
            name: (dict(value) if isinstance(value, dict) else value)
            for name, value in self.__dict__.items()
        }


class PresentationAddressedTurnService:
    """Arme, ouvre, sert et solde un tour adressé. Une porte par question."""

    def __init__(
        self,
        *,
        store: Any,
        speculative: Any | None = None,
        mode: Callable[[], object] | None = None,
        diagnostics: DiagnosticSink | None = None,
        latency: LatencyTracker | None = None,
        classify: Callable[[object], tuple[PresentationSituation, str]] = classify_addressed_situation,
        admit: Callable[..., Any] = admit_presentation_speech,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
        preroll_s: float = DEFAULT_PREROLL_S,
        window_s: float = MAX_ADDRESSED_WINDOW_S,
        context_budget: int = MAX_ADDRESSED_CONTEXT_CHARS,
    ) -> None:
        """`clock` doit être **l'horloge qui a estampillé le déclencheur**.

        La lane d'adresse explicite estampille avec sa propre `clock`
        (`time.monotonic` par défaut, injectable en test). Mélanger deux horloges
        ici donnerait un nombre qui a l'air d'une latence : c'est pourquoi le
        service refuse de mesurer quand l'horloge est en retard sur le
        déclencheur, plutôt que de rendre une valeur négative écrêtée à zéro.
        """

        self._store = store
        self._speculative = speculative
        self._mode = mode
        self._diagnostics = diagnostics
        self._clock = clock
        self._wall_clock = wall_clock or utc_now
        self._latency = (
            latency if latency is not None
            else LatencyTracker(_GuardedLatencySink(self), clock=clock)
        )
        self._classify = classify
        self._admit = admit
        self._preroll_s = float(preroll_s)
        self._window_s = float(window_s)
        self._context_budget = int(context_budget)
        self._window: AddressedWindow | None = None
        self._armed_correlation: str | None = None
        self.counters = AddressedTurnCounters()

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    @property
    def armed(self) -> bool:
        """Une fenêtre est-elle ouverte ? Lecture, jamais une décision."""

        return self._window is not None

    @property
    def window(self) -> AddressedWindow | None:
        return self._window

    def stats(self) -> dict[str, Any]:
        return {
            "armed": self.armed,
            "window": None if self._window is None else self._window.to_trace_payload(),
            "preroll_s": self._preroll_s,
            "window_s": self._window_s,
            "context_budget": self._context_budget,
            "latency_pending": self._latency.pending_count,
            "measures": list(ADDRESSED_LATENCY_MEASURES),
            "counters": self.counters.to_trace_payload(),
        }

    # ------------------------------------------------------------------
    # Armement — synchrone, par construction
    # ------------------------------------------------------------------

    def arm(self, trigger: object, *, correlation_id: str = "") -> AddressedTurnResult:
        """Lier le tour qui suit au déclencheur. **Synchrone et non bloquant.**

        Aucun `await` : rien de ce qui se passe ailleurs ne peut s'intercaler
        entre l'estampille du déclencheur et cette ligne. C'est la forme
        exécutable de D04, et c'est vérifié par un test d'AST plutôt que cru.
        """

        if not isinstance(trigger, ExplicitAddressTrigger):
            return self._refuse(VoiceStateDisposition.REJECTED, "addressed_trigger_invalid")
        if getattr(trigger, "authorizes_actions", False):
            # Impossible avec le type réel (`ClassVar` figé). Le contrôle existe
            # pour un transport qui reconstruirait l'objet — même garde que la
            # voie spéculative sur `AmbientTrigger`.
            return self._refuse(VoiceStateDisposition.REJECTED, "addressed_trigger_authorizing")
        mode = self._behaving_mode()
        if mode is not InteractionMode.PRESENTATION:
            return self._refuse(VoiceStateDisposition.IGNORED, "addressed_mode_not_presentation")
        if not self._session_active():
            return self._refuse(VoiceStateDisposition.IGNORED, "addressed_working_set_inactive")
        try:
            window = AddressedWindow(
                trigger=trigger, preroll_s=self._preroll_s, max_wait_s=self._window_s
            )
        except PresentationAddressedTurnError as exc:
            return self._refuse(VoiceStateDisposition.REJECTED, exc.code)
        now = self._now()
        if now is None:
            return self._refuse(VoiceStateDisposition.REJECTED, "addressed_clock_unreadable")
        if not trigger.is_fresh(now):
            # Jamais écarté. Perdre un appui de l'utilisateur est pire que d'en
            # servir un vieux — c'est la règle de la lane (Slice 05), tenue ici
            # aussi pour que les deux couches ne se contredisent pas.
            self.counters.stale_triggers += 1
            self._trace(
                "trigger_stale",
                "Déclencheur servi en retard : le tour est armé quand même",
                level="warning",
                data={"code": "addressed_trigger_stale",
                      "age_s": round(trigger.age_s(now), 3),
                      **window.to_trace_payload()},
            )
        if self._window is not None:
            self.counters.rearmed += 1
        self._window = window
        self._armed_correlation = _short(correlation_id) if correlation_id else None
        self.counters.armed += 1
        self._free_a_slot()
        self._seed(TRIGGER_TO_ADMISSION, _trigger_key(trigger), window)
        self._trace(
            "armed", "Tour adressé armé sur un déclencheur explicite",
            data={"code": "addressed_turn_armed",
                  "correlation_id": _short(correlation_id) or None,
                  "rearmed": self.counters.rearmed,
                  **window.to_trace_payload()},
        )
        return AddressedTurnResult(VoiceStateDisposition.APPLIED, "addressed_turn_armed")

    def _free_a_slot(self) -> None:
        """Demander à la voie spéculative de faire de la place (D08).

        C'est **tout** ce que cette Slice fait pour la capacité, et c'est dit
        ainsi exprès : `note_addressed_turn()` libère une place dans la table de
        la voie spéculative. Elle ne dit rien du sémaphore d'`OwnedJobExecution`,
        qui est là où le tour adressé s'exécute réellement.
        """

        if self._speculative is None:
            return
        try:
            preempted = self._speculative.note_addressed_turn()
        except Exception as exc:  # noqa: BLE001 - une voie en panne ne retarde pas un tour
            self.counters.speculative_failures += 1
            self._trace(
                "preemption_failed",
                "La voie spéculative n'a pas pu libérer de place : le tour continue",
                level="error",
                data={"code": "addressed_preemption_failed", "error_class": type(exc).__name__},
            )
            return
        count = len(preempted) if isinstance(preempted, (tuple, list)) else 0
        self.counters.preempted += count
        if count:
            self._trace(
                "preempted",
                "Travail spéculatif sacrifié pour le tour adressé",
                data={"code": "addressed_preempted", "jobs": count},
            )

    def _seed(self, measure: str, key: str, window: AddressedWindow) -> bool:
        """Poser une borne de départ **à l'estampille du déclencheur**, ou aucune.

        Aucune plutôt qu'une inventée : si l'horloge du service est en retard
        sur le déclencheur, les deux bornes ne viennent pas de la même horloge
        et la soustraction donnerait un nombre qui a l'air d'une mesure. Une
        latence absente dit « on ne sait pas » ; un zéro dirait « on sait que
        c'était instantané ».
        """

        if not key:
            return False
        now = self._now()
        if now is None or now < window.trigger.monotonic_s:
            self.counters.latency_clock_mismatch += 1
            self._trace(
                "latency_unavailable",
                "Latence non mesurée : l'horloge du service est en retard sur le "
                "déclencheur, donc les deux bornes ne viennent pas de la même horloge",
                level="warning",
                data={"code": "addressed_latency_clock_mismatch", "measure": measure,
                      **window.to_trace_payload()},
            )
            return False
        self._latency.mark(measure, key, at=window.trigger.monotonic_s)
        return True

    # ------------------------------------------------------------------
    # Ouverture — synchrone, par construction
    # ------------------------------------------------------------------

    def open(
        self,
        text: object,
        *,
        correlation_id: str,
        spoken_at_s: float | None = None,
    ) -> AddressedTurnResult:
        """Lier la parole entendue au déclencheur armé et projeter son contexte.

        **Synchrone**, pour la même raison qu'`arm()`. L'instantané du magasin
        est lu **une fois** : les deux moitiés viennent donc forcément du même
        instant, ce que la Slice 04 garantit en ne détenant qu'une référence.

        Une fenêtre sert **un** tour. Un second appel sans nouveau déclencheur
        est ignoré : sinon un seul appui adresserait deux phrases, dont la
        seconde n'a jamais été adressée à personne.
        """

        window = self._window
        if window is None:
            return self._refuse(VoiceStateDisposition.IGNORED, "addressed_no_window")
        now = self._now()
        if now is None:
            return self._refuse(VoiceStateDisposition.REJECTED, "addressed_clock_unreadable")
        if spoken_at_s is not None and not window.covers(spoken_at_s):
            self.counters.windows_expired += 1
            self._disarm()
            return self._refuse(VoiceStateDisposition.STALE, "addressed_speech_outside_window")
        if spoken_at_s is None and window.expired(now):
            self.counters.windows_expired += 1
            self._disarm()
            return self._refuse(VoiceStateDisposition.STALE, "addressed_window_expired")
        mode = self._behaving_mode()
        if mode is not InteractionMode.PRESENTATION:
            self._disarm()
            return self._refuse(VoiceStateDisposition.IGNORED, "addressed_mode_not_presentation")
        snapshot = self._snapshot()
        if snapshot is None:
            self._disarm()
            return self._refuse(VoiceStateDisposition.REJECTED, "addressed_snapshot_unreadable")
        if getattr(snapshot, "session_id", None) is None:
            self._disarm()
            return self._refuse(VoiceStateDisposition.IGNORED, "addressed_working_set_inactive")
        situation, evidence = self._classify_turn(text)
        deictic = deictic_marker(text)
        referent = resolve_referent(snapshot)
        if situation is not PresentationSituation.VISUAL_COMMAND or not deictic:
            # Une demande nommée porte son objet ; ce module ne rapproche pas un
            # nom d'une ressource, le cerveau reçoit la projection et le fait.
            resolution = ResourceResolution(
                ResourceVerdict.NOT_REQUESTED, code="addressed_no_deictic"
            )
        else:
            retired = self._retired_resource_ids()
            if retired is None:
                # Ne rien savoir des retraits n'autorise pas à montrer : une
                # ressource retirée ressuscitée est exactement l'écran périmé
                # que cette Slice existe pour empêcher. On rafraîchit.
                resolution = ResourceResolution(
                    ResourceVerdict.STALE, code="addressed_retired_unreadable"
                )
            else:
                resolution = resolve_prepared_resource(
                    snapshot, referent=referent, retired_resource_ids=retired,
                )
        try:
            context = build_addressed_turn_context(
                snapshot, situation=situation, evidence=evidence, deictic=deictic,
                referent=referent, resource=resolution, budget=self._context_budget,
            )
        except PresentationAddressedTurnError as exc:
            self.counters.context_failures += 1
            self._disarm()
            return self._refuse(VoiceStateDisposition.REJECTED, exc.code)
        action = decide_action(situation, resolution)
        latency_ms = self._latency.measure(
            TRIGGER_TO_ADMISSION, _trigger_key(window.trigger),
            kind=f"{ADDRESSED_KIND}.latency",
            data={"code": "addressed_admission_latency",
                  "correlation_id": _short(correlation_id) or None,
                  "source": window.trigger.source.value},
        )
        # Les deux mesures de réaction sont réamorcées sous la **corrélation** du
        # tour, parce que c'est l'identité que l'appelant détient encore quand
        # l'écran s'allume ou que la phrase part ; le déclencheur, lui, est déjà
        # derrière. Les deux bornes restent sur l'estampille du déclencheur.
        for measure in (TRIGGER_TO_VISIBLE, TRIGGER_TO_AUDIBLE):
            self._seed(measure, _short(correlation_id), window)
        plan = AddressedTurnPlan(
            correlation_id=_short(correlation_id), window=window, context=context,
            action=action, admission_latency_ms=latency_ms,
        )
        self._disarm()
        self.counters.opened += 1
        self._trace(
            "opened", "Tour adressé ouvert avec son contexte frais",
            data={"code": "addressed_turn_opened", **plan.to_trace_payload()},
        )
        return AddressedTurnResult(VoiceStateDisposition.APPLIED, "addressed_turn_opened", plan)

    def _classify_turn(self, text: object) -> tuple[PresentationSituation, str]:
        """Classer, ou parler. Le repli est la parole, jamais le silence.

        Même position que la porte de la Slice 07 : un tour adressé qu'on n'a pas
        su lire doit se comporter comme un tour illisible, pas comme un tour mis
        au silence.
        """

        try:
            situation, evidence = self._classify(text)
        except Exception as exc:  # noqa: BLE001 - un classement en panne ne fait pas taire JARVIS
            self.counters.classification_failures += 1
            self._trace(
                "classification_failed",
                "Tour adressé non classé : repli sur la parole",
                level="warning",
                data={"code": "addressed_classification_failed",
                      "error_class": type(exc).__name__},
            )
            return PresentationSituation.KNOWLEDGE_QUESTION, "classification_failed"
        if not isinstance(situation, PresentationSituation):
            self.counters.classification_failures += 1
            self._trace(
                "classification_failed",
                "Classement hors contrat : repli sur la parole",
                level="warning",
                data={"code": "addressed_classification_untyped"},
            )
            return PresentationSituation.KNOWLEDGE_QUESTION, "classification_untyped"
        return situation, str(evidence)[:64]

    # ------------------------------------------------------------------
    # Livraison
    # ------------------------------------------------------------------

    async def deliver(self, plan: object) -> AddressedTurnOutcome:
        """Exécuter la décision du plan. Réutiliser, rafraîchir, ou clarifier.

        Asynchrone, contrairement à `arm()` et `open()` : révéler un objet de
        scène est un aller-retour vers la scène. L'admission, elle, a déjà eu
        lieu — la latence que D04 borne est fermée avant cette ligne.
        """

        if not isinstance(plan, AddressedTurnPlan):
            return AddressedTurnOutcome(
                AddressedTurnAction.ASK_BRAIN, False, "addressed_plan_invalid"
            )
        if plan.action is AddressedTurnAction.SHOW_PREPARED:
            return await self._show_prepared(plan)
        if plan.action is AddressedTurnAction.CLARIFY:
            return self._clarify(plan)
        if plan.action is AddressedTurnAction.REFRESH:
            return self._refresh(plan)
        self.counters.brain_turns += 1
        self._trace(
            "brain_turn", "Tour adressé remis au cerveau avec son contexte",
            data={"code": "addressed_brain_turn", "correlation_id": _short(plan.correlation_id),
                  "situation": plan.situation.value},
        )
        return AddressedTurnOutcome(
            AddressedTurnAction.ASK_BRAIN, True, "addressed_brain_turn"
        )

    async def _show_prepared(self, plan: AddressedTurnPlan) -> AddressedTurnOutcome:
        """Montrer ce qui était déjà préparé, sans rien re-préparer.

        Un objet de scène se **révèle** par la voie spéculative, qui possède le
        monteur et réchauffe la ressource au passage (`use_resource`). Une autre
        nature de ressource n'a rien à révéler : elle est seulement réchauffée
        ici, pour que la température reflète qu'elle vient de servir.
        """

        resource_id = plan.resource_id
        kind = plan.context.resource.kind
        if kind is ResourceKind.SCENE_OBJECT and self._speculative is None:
            # Un objet de scène masqué ne se montre que par la voie qui l'a
            # monté. Sans elle, le réchauffer donnerait une ressource déclarée
            # servie et un écran toujours vide — « ça a marché » dit d'un tour
            # qui n'a rien montré.
            self.counters.reveal_failures += 1
            self._trace(
                "reveal_unavailable",
                "Aucune voie de préparation branchée : l'objet masqué ne peut pas être révélé",
                level="warning",
                data={"code": "addressed_reveal_unavailable",
                      "resource_id": _short(resource_id)},
            )
            return self._refresh(plan, after="reveal_unavailable")
        if kind is ResourceKind.SCENE_OBJECT:
            try:
                admission = await self._speculative.reveal(resource_id)
            except Exception as exc:  # noqa: BLE001 - une révélation ratée ne casse pas le tour
                self.counters.reveal_failures += 1
                self._trace(
                    "reveal_failed", "Révélation d'une ressource préparée en échec",
                    level="error",
                    data={"code": "addressed_reveal_failed", "resource_id": _short(resource_id),
                          "error_class": type(exc).__name__},
                )
                return self._refresh(plan, after="reveal_failed")
            name = self._account_speculative(admission)
            if name != "accepted":
                self.counters.reveal_failures += 1
                self._trace(
                    "reveal_refused", "Révélation refusée par la voie spéculative",
                    level="warning",
                    data={"code": "addressed_reveal_refused", "admission": name,
                          "resource_id": _short(resource_id)},
                )
                return self._refresh(plan, after="reveal_refused")
            self.counters.revealed += 1
        else:
            result = self._use_resource(resource_id)
            if result != VoiceStateDisposition.APPLIED.value:
                # Le magasin refuse : la ressource a été retirée, ou la séance
                # a bougé sous nos pieds. Rafraîchir plutôt que de montrer ce
                # qu'il vient de refuser.
                self._trace(
                    "reuse_refused", "Le magasin a refusé de réutiliser la ressource",
                    level="warning",
                    data={"code": "addressed_reuse_refused", "disposition": result,
                          "resource_id": _short(resource_id)},
                )
                return self._refresh(plan, after="reuse_refused")
        self.counters.reused += 1
        self._trace(
            "reused", "Ressource préparée réutilisée : rien n'a été re-préparé",
            data={"code": "addressed_resource_reused", "resource_id": _short(resource_id),
                  "kind": None if kind is None else kind.value,
                  "correlation_id": _short(plan.correlation_id)},
        )
        return AddressedTurnOutcome(
            AddressedTurnAction.SHOW_PREPARED, True, "addressed_resource_reused",
            resource_id=resource_id,
        )

    def _clarify(self, plan: AddressedTurnPlan) -> AddressedTurnOutcome:
        """Demander laquelle, plutôt que d'en choisir une au hasard.

        La question n'est audible que parce que la Slice 07 a mis
        `SpeechKind.QUESTION` dans les natures de sûreté de `VISUAL_COMMAND`.
        C'est la matrice qui répond, pas ce module — et si elle refusait, on
        rafraîchirait plutôt que de se taire : un tour sans écran **et** sans
        phrase est exactement le défaut que cette exception a été ajoutée pour
        fermer.
        """

        try:
            verdict = self._admit(situation=plan.situation, kind=SpeechKind.QUESTION)
            admitted = bool(getattr(verdict, "admitted", False))
        except Exception as exc:  # noqa: BLE001 - une politique en panne ne montre pas le mauvais écran
            self.counters.clarification_withheld += 1
            self._trace(
                "clarification_failed",
                "Admission de la clarification en panne : rafraîchissement plutôt que silence",
                level="error",
                data={"code": "addressed_clarification_failed",
                      "error_class": type(exc).__name__},
            )
            return self._refresh(plan, after="clarification_failed")
        if not admitted:
            self.counters.clarification_withheld += 1
            self._trace(
                "clarification_withheld",
                "La politique refuse la clarification : rafraîchissement plutôt que silence",
                level="warning",
                data={"code": "addressed_clarification_withheld",
                      "situation": plan.situation.value,
                      "reason": _short(getattr(verdict, "reason", ""))},
            )
            return self._refresh(plan, after="clarification_withheld")
        self.counters.clarified += 1
        self._trace(
            "clarified", "Deux ressources également ancrées : JARVIS demande laquelle",
            data={"code": "addressed_clarification", "tied": len(plan.context.resource.tied),
                  "correlation_id": _short(plan.correlation_id)},
        )
        return AddressedTurnOutcome(
            AddressedTurnAction.CLARIFY, True, "addressed_clarification",
            speaks=True, speech_kind=SpeechKind.QUESTION,
        )

    def _refresh(self, plan: AddressedTurnPlan, *, after: str = "") -> AddressedTurnOutcome:
        """Re-préparer, à P1, sans attendre : le tour ne se bloque pas dessus.

        `reserve_explicit` est le chemin de la Slice 08 pour une préparation
        demandée par un tour explicite : il prend une place de la réserve et
        préempte du spéculatif si le bassin est plein. Le sujet est
        l'**identifiant** de l'énonciation désignée, jamais son texte : une clé
        se journalise par son empreinte, mais le sujet nourrit aussi la
        déduplication et il n'y a aucune raison d'y mettre de la parole.
        """

        code = f"addressed_refresh_requested{':' + after if after else ''}"
        if self._speculative is None:
            self.counters.refresh_failures += 1
            self._trace(
                "refresh_unavailable",
                "Aucune voie de préparation branchée : rien n'a pu être rafraîchi",
                level="warning",
                data={"code": "addressed_refresh_unavailable", "after": after or None},
            )
            return AddressedTurnOutcome(
                AddressedTurnAction.REFRESH, False, "addressed_refresh_unavailable"
            )
        referent = plan.context.referent
        topic = f"addressed-{referent.utterance_id}" if referent is not None else "addressed-unknown"
        try:
            admission = self._speculative.reserve_explicit(
                topic=topic,
                capabilities=REFRESH_CAPABILITIES,
                utterance_id=referent.utterance_id if referent is not None else "addressed-unknown",
                text=topic,
                resource=plan.context.resource.verdict.value,
            )
        except Exception as exc:  # noqa: BLE001 - une voie en panne ne fait pas montrer un écran faux
            self.counters.refresh_failures += 1
            self.counters.speculative_failures += 1
            self._trace(
                "refresh_failed", "Demande de rafraîchissement en échec",
                level="error",
                data={"code": "addressed_refresh_failed", "after": after or None,
                      "error_class": type(exc).__name__},
            )
            return AddressedTurnOutcome(
                AddressedTurnAction.REFRESH, False, "addressed_refresh_failed"
            )
        name = self._account_speculative(admission)
        delivered = name in ("accepted", "coalesced")
        if not delivered:
            self.counters.refresh_failures += 1
        else:
            self.counters.refreshed += 1
        self._trace(
            "refresh_requested",
            "Rien de réutilisable : une préparation explicite est demandée",
            level="info" if delivered else "warning",
            data={"code": code, "admission": name, "after": after or None,
                  "verdict": plan.context.resource.verdict.value,
                  "resolution_code": plan.context.resource.code,
                  "correlation_id": _short(plan.correlation_id)},
        )
        return AddressedTurnOutcome(
            AddressedTurnAction.REFRESH, delivered,
            code if delivered else "addressed_refresh_refused",
        )

    # ------------------------------------------------------------------
    # Réactions et solde
    # ------------------------------------------------------------------

    def note_visible_reaction(self, correlation_id: str) -> float | None:
        """Fermer la mesure déclencheur → réaction visible. `None` s'il n'y a rien à fermer."""

        return self._close(TRIGGER_TO_VISIBLE, correlation_id, "addressed_visible_latency")

    def note_audible_reaction(self, correlation_id: str) -> float | None:
        """Fermer la mesure déclencheur → réaction audible. `None` s'il n'y a rien à fermer."""

        return self._close(TRIGGER_TO_AUDIBLE, correlation_id, "addressed_audible_latency")

    def _close(self, measure: str, correlation_id: str, code: str) -> float | None:
        key = _short(correlation_id)
        if not key:
            return None
        return self._latency.measure(
            measure, key, kind=f"{ADDRESSED_KIND}.latency",
            data={"code": code, "correlation_id": key},
        )

    def conclude(self, correlation_id: str = "") -> AddressedTurnSettlement:
        """Solder le tour et **rester en PRESENTATION ambiante**.

        Ce que cette méthode fait : lire où en est la séance et le dire. Ce
        qu'elle ne fait **pas**, et c'est tout l'objet du point « le runtime
        reste en présentation » : elle ne termine pas la séance, ne retire rien,
        ne change pas le mode, n'arrête aucune voie. Un tour adressé est un
        épisode dans une séance ambiante, pas une parenthèse assistant.

        Le solde est rendu comme une **valeur** : un test doit pouvoir affirmer
        que la séance a survécu sans lire un journal.
        """

        mode = self._behaving_mode()
        still = mode is InteractionMode.PRESENTATION
        snapshot = self._snapshot()
        session_id = getattr(snapshot, "session_id", None) if snapshot is not None else None
        settlement = AddressedTurnSettlement(
            still_presentation=still,
            session_active=session_id is not None,
            session_id=session_id,
            generation=int(getattr(snapshot, "generation", 0) or 0),
            mode=mode,
        )
        self.counters.settled += 1
        if not still:
            self.counters.settled_outside_presentation += 1
        self._latency.forget(TRIGGER_TO_VISIBLE, _short(correlation_id))
        self._latency.forget(TRIGGER_TO_AUDIBLE, _short(correlation_id))
        self._trace(
            "settled",
            "Tour adressé soldé : la séance PRESENTATION continue"
            if still else
            "Tour adressé soldé hors PRESENTATION : la séance n'est plus ambiante",
            level="info" if still else "warning",
            data={"code": "addressed_turn_settled" if still else "addressed_turn_left_presentation",
                  "correlation_id": _short(correlation_id) or None,
                  **settlement.to_trace_payload()},
        )
        return settlement

    # ------------------------------------------------------------------
    # Mécanique interne
    # ------------------------------------------------------------------

    def _disarm(self) -> None:
        self._window = None
        self._armed_correlation = None

    def _now(self) -> float | None:
        """L'instant monotone, ou `None` si l'horloge injectée ne répond pas.

        Une horloge qui lève est un cas de test, pas une impossibilité : elle
        est injectable, donc elle est atteignable.
        """

        try:
            value = self._clock()
        except Exception as exc:  # noqa: BLE001
            self._trace(
                "clock_failed", "Horloge monotone illisible",
                level="error",
                data={"code": "addressed_clock_unreadable", "error_class": type(exc).__name__},
            )
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _behaving_mode(self) -> InteractionMode:
        """Le mode qui **pilote un comportement**, comme partout dans ce handoff.

        Sans lecteur injecté, PRESENTATION est supposé : ce service ne se
        construit que dans une séance de présentation, et lui faire refuser tout
        par défaut en ferait un service inutilisable sans son voisin.
        `behaving_interaction_mode` ne rend jamais `None` — un mode illisible
        retombe sur ASSISTANT, ce qui est la direction sûre.
        """

        if self._mode is None:
            return InteractionMode.PRESENTATION
        try:
            value = self._mode()
        except Exception as exc:  # noqa: BLE001
            self._trace(
                "mode_unreadable", "Mode d'interaction illisible : repli sur ASSISTANT",
                level="error",
                data={"code": "addressed_mode_unreadable", "error_class": type(exc).__name__},
            )
            return InteractionMode.ASSISTANT
        return behaving_interaction_mode(value)

    def _session_active(self) -> bool:
        snapshot = self._snapshot()
        return snapshot is not None and getattr(snapshot, "session_id", None) is not None

    def _snapshot(self) -> Any | None:
        try:
            return self._store.snapshot
        except Exception as exc:  # noqa: BLE001 - un magasin conforme rend toujours un instantané
            self.counters.store_failures += 1
            self._trace(
                "snapshot_failed", "Instantané de séance illisible",
                level="error",
                data={"code": "addressed_snapshot_unreadable", "error_class": type(exc).__name__},
            )
            return None

    def _retired_resource_ids(self) -> tuple[str, ...] | None:
        """Les ressources déjà sorties de l'ensemble, ou `None` si on ne sait pas.

        Le magasin tient cette mémoire côté écriture (`apply` refuse une
        préparation tardive qui nomme une ressource jetée). Ici c'est le côté
        lecture : l'instantané peut encore montrer une ressource dont
        l'identifiant vient d'être retiré, et la montrer serait ressusciter ce
        que le magasin vient d'enterrer.

        `None` — et non un tuple vide — quand la lecture échoue ou rend autre
        chose qu'une collection d'identifiants. Un tuple vide voudrait dire
        « rien n'a été retiré », ce qui est précisément l'affirmation qu'on n'est
        pas en mesure de faire. Une `str` compte comme une erreur : itérée, elle
        donnerait un ensemble de **lettres** — un mauvais résultat portant la
        forme d'un bon, ce que la Slice 09 a payé une fois.
        """

        try:
            values = self._store.retired_resource_ids
        except Exception as exc:  # noqa: BLE001
            self.counters.store_failures += 1
            self._trace(
                "retired_unavailable",
                "Liste des ressources retirées illisible : aucune réutilisation n'est tentée",
                level="error",
                data={"code": "addressed_retired_unreadable", "error_class": type(exc).__name__},
            )
            return None
        if isinstance(values, (str, bytes)) or not isinstance(values, (tuple, list, set, frozenset)):
            self.counters.store_failures += 1
            self._trace(
                "retired_unavailable",
                "Liste des ressources retirées hors contrat : aucune réutilisation n'est tentée",
                level="error",
                data={"code": "addressed_retired_untyped", "value_type": type(values).__name__},
            )
            return None
        return tuple(str(item) for item in values)

    def _use_resource(self, resource_id: str) -> str:
        """Réchauffer la ressource qui vient de servir. Rend la disposition, en `str`."""

        try:
            result = self._store.use_resource(resource_id, at=self._wall_clock())
        except Exception as exc:  # noqa: BLE001 - le magasin promet une disposition, pas une exception
            self.counters.store_failures += 1
            self._trace(
                "store_failed", "Le magasin a levé au lieu de rendre une disposition",
                level="error",
                data={"code": "addressed_store_failed", "error_class": type(exc).__name__,
                      "resource_id": _short(resource_id)},
            )
            return "failed"
        return self._account_store(result)

    def _account_store(self, result: object) -> str:
        """Compter la disposition du magasin, **les sept**, sans en regrouper aucune.

        Une disposition inconnue est dite à `error` plutôt que rangée dans un cas
        par défaut : c'est la leçon `ambient_disposition_unknown` de la Slice 06.
        """

        disposition = getattr(result, "disposition", None)
        name = getattr(disposition, "value", None) or str(disposition)
        table = self.counters.store_dispositions
        if name not in table:
            self.counters.store_failures += 1
            self._trace(
                "store_disposition_unknown",
                "Disposition de magasin inconnue : elle n'est rangée dans aucun cas par défaut",
                level="error",
                data={"code": "addressed_store_disposition_unknown",
                      "disposition": _short(name)},
            )
            table[_short(name)] = table.get(_short(name), 0) + 1
            return _short(name)
        table[name] += 1
        return name

    def _account_speculative(self, admission: object) -> str:
        name = getattr(admission, "value", None) or str(admission)
        key = _short(name)
        table = self.counters.speculative_admissions
        table[key] = table.get(key, 0) + 1
        return key

    def _refuse(self, disposition: VoiceStateDisposition, code: str) -> AddressedTurnResult:
        """Refus journalisé, sans contenu. Un refus muet serait indiscernable."""

        self.counters.refused += 1
        self._trace(
            "refused", "Tour adressé écarté",
            level="info" if disposition in _EXPECTED else "warning",
            data={"code": code, "disposition": disposition.value},
        )
        return AddressedTurnResult(disposition, code)

    def _trace(
        self, event: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None
    ) -> None:
        self._emit(f"{ADDRESSED_KIND}.{event}", message, level=level, data=data)

    def _emit(
        self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None
    ) -> None:
        """La **seule** sortie vers le journal, gardée une fois pour toutes."""

        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=data or {})
        except Exception:  # noqa: BLE001 - un journal en panne ne décide pas d'un tour
            # Compté, jamais seulement avalé : `stats()` ne doit pas pouvoir
            # décrire une voie saine à côté d'une trace vide (Slice 08).
            self.counters.diagnostic_failures += 1


class _GuardedLatencySink:
    """Le puits que reçoit le chronomètre, et la raison pour laquelle il existe.

    `LatencyTracker.measure()` émet **directement** sur le puits qu'on lui donne,
    sans garde : lui passer le journal de production ferait d'un journal en panne
    une exception au milieu d'une mesure de latence. Ce que le reste du service
    interdit explicitement — un journal ne décide jamais d'un tour — ne doit pas
    se rouvrir par la porte de la télémétrie.
    """

    __slots__ = ("_service",)

    def __init__(self, service: PresentationAddressedTurnService) -> None:
        self._service = service

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        self._service._emit(kind, message, level=level, data=data)


#: Dispositions attendues d'un tour qui va bien : un tour hors présentation ou
#: sans séance est le quotidien d'un service branché avant son producteur. Elles
#: se journalisent en `info` ; le reste mérite un `warning`. Même liste et même
#: raison que `_EXPECTED` de la Slice 04.
_EXPECTED = frozenset(
    {
        VoiceStateDisposition.DUPLICATE,
        VoiceStateDisposition.IGNORED,
        VoiceStateDisposition.STALE_SESSION,
    }
)


__all__ = [
    "ADDRESSED_KIND",
    "ADDRESSED_LATENCY_MEASURES",
    "MAX_JOURNALLED_VALUE_CHARS",
    "REFRESH_CAPABILITIES",
    "TRIGGER_TO_ADMISSION",
    "TRIGGER_TO_AUDIBLE",
    "TRIGGER_TO_VISIBLE",
    "AddressedTurnCounters",
    "AddressedTurnOutcome",
    "AddressedTurnPlan",
    "AddressedTurnResult",
    "AddressedTurnSettlement",
    "PresentationAddressedTurnService",
]
