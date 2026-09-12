from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any

from jarvis.core.latency import (
    FIRST_PUBLIC_PROGRESS as LATENCY_FIRST_PUBLIC_PROGRESS,
    WORK_COMPLETED as LATENCY_WORK_COMPLETED,
    LatencyTracker,
)
from jarvis.core.v2_services import (
    BRAIN_WORK_PROGRESS,
    ConversationService,
    CoreEventBus,
    NullDiagnosticSink,
)
from jarvis.domain.v2 import (
    BRAIN_NOT_ADDRESSED_ANSWER,
    DEFAULT_TRANSIENT_SPEECH_TTL_S,
    SPEECH_DELIVERY_PARTIAL,
    AddressingDecision,
    BrainEvent,
    BrainEventKind,
    BrainIntentRevision,
    BrainRunStatus,
    BrainTurnAcceptance,
    BrainTurnInput,
    BrainTurnResult,
    BrainWorkingState,
    ProtocolEnvelope,
    SpeechKind,
    SpeechPriority,
    SpeechProvenance,
    SpeechRequest,
    TurnKind,
    new_id,
    utc_now,
)
from jarvis.core.brain_context import BrainContextBuilder
from jarvis.domain.brain_context import BrainContext
from jarvis.ports.v2 import BrainBackend, DiagnosticSink, WorkCanceller, supports_brain_context

# Types d'événements publiés sur `CoreEventBus`. Les charges utiles suivent
# `docs/handoff-realtime-brain/docs/05-event-contracts.md` ; les clés que le
# contrat définit mais dont aucune source n'existe encore (`job_id`, `phase`,
# `fraction`, `result_ref`) sont publiées à `null` plutôt qu'omises, pour que le
# consommateur n'ait pas à distinguer « absent » de « inconnu ».
BRAIN_TURN_ACCEPTED = "brain.turn.accepted"
BRAIN_STATE_UPDATED = "brain.state.updated"
BRAIN_SPEECH_REQUESTED = "brain.speech.requested"
BRAIN_WORK_STARTED = "brain.work.started"
BRAIN_WORK_COMPLETED = "brain.work.completed"
BRAIN_WORK_FAILED = "brain.work.failed"
BRAIN_INTENT_REVISED = "brain.intent.revised"

# Canaux de diagnostic (Décision 27 : l'observabilité passe par un
# `DiagnosticSink`, que le composition root branche sur `RuntimeJournal`).
BRAIN_TURN_FAILED_KIND = "core.brain.turn_failed"
BRAIN_TURN_CANCELLED_KIND = "core.brain.turn_cancelled"
BRAIN_BACKEND_CONTRACT_KIND = "core.brain.backend_contract_violation"
BRAIN_WORK_CANCELLED_KIND = "core.brain.work_cancelled"
BRAIN_WORK_CANCEL_FAILED_KIND = "core.brain.work_cancel_failed"
BRAIN_SPEECH_DROPPED_KIND = "core.brain.speech_dropped"
# Disponibilité du cerveau : un tour qui dépasse son budget fait attendre
# l'utilisateur (et les tours suivants). `turn_slow` part au franchissement,
# `turn_over_budget` à la fin, avec la durée réelle.
BRAIN_TURN_SLOW_KIND = "core.brain.turn_slow"
BRAIN_TURN_OVER_BUDGET_KIND = "core.brain.turn_over_budget"
BRAIN_REPLIES_SUPERSEDED_KIND = "core.brain.replies_superseded"
BRAIN_NOTICE_RELAYED_KIND = "core.brain.notice_relayed"
BRAIN_NOTICE_DROPPED_KIND = "core.brain.notice_dropped"

#: Budget d'un tour cerveau, en secondes : au-delà, la conversation attend.
DEFAULT_TURN_BUDGET_S = 8.0

# Mesures 5 et 6 des six de `docs/04-testing-and-quality.md`. Elles se joignent
# par `work_id`, l'identifiant que le cerveau a lui-même nommé, et ne portent ni
# libellé public ni résumé : une latence n'a pas besoin de savoir ce qui a été
# fait, seulement combien de temps cela a pris.
BRAIN_FIRST_PROGRESS_LATENCY_KIND = "core.brain.latency.first_public_progress"
BRAIN_WORK_COMPLETED_LATENCY_KIND = "core.brain.latency.work_completed"

NO_BACKEND_ERROR = "brain_backend_not_configured"


def _stable_error_class(value: str | None) -> str:
    """Réduire une erreur backend à un jeton court et stable.

    Un `error_class` sert à classer une panne, pas à la raconter :
    `docs/05-event-contracts.md` interdit d'y déverser une trace brute. Le
    détail complet part au journal de diagnostic, jamais sur le bus.
    """

    first_line = (value or "").strip().splitlines()
    token = first_line[0].strip() if first_line else ""
    return token[:120] or "brain_backend_error"


class NullBrainBackend:
    """Backend cerveau inerte, utilisé quand aucun modèle fort n'est injecté.

    Objet nul défini dans le cœur (Décision 28) : ce n'est pas un adaptateur
    fournisseur, donc sa place ici ne contourne pas le gate d'architecture.

    Il rend délibérément un échec plutôt qu'un succès vide : un tour « terminé »
    sans qu'aucun cerveau ne l'ait traité laisserait croire à l'appelant que la
    demande a été prise en charge. Le mode headless doit être visible, pas
    silencieux.
    """

    async def run_turn(self, turn: BrainTurnInput, state: BrainWorkingState, emit) -> BrainTurnResult:
        return BrainTurnResult(
            correlation_id=turn.correlation_id,
            status=BrainRunStatus.FAILED,
            error=NO_BACKEND_ERROR,
        )


@dataclass(slots=True)
class _TurnEventSink:
    """`BrainEventSink` lié à un tour, remis au backend le temps de son exécution.

    Le backend ne connaît jamais `CoreEventBus` (spec section 3) : il alimente
    ce puits, et l'orchestrateur seul traduit en `ProtocolEnvelope`. Le puits
    est confiné à la tâche du tour, donc sans concurrence interne ; les
    transitions d'état qu'il déclenche sont sérialisées par le verrou de
    l'orchestrateur.
    """

    orchestrator: BrainOrchestrator
    turn: BrainTurnInput

    async def emit(self, event: BrainEvent) -> None:
        if event.correlation_id != self.turn.correlation_id:
            raise ValueError("brain event correlation_id must match the running turn")
        if event.conversation_id != self.turn.conversation_id:
            raise ValueError("brain event conversation_id must match the running turn")
        await self.orchestrator._dispatch_backend_event(event)


class BrainOrchestrator:
    """Cerveau autoritaire de Jarvis, possédé par Core (Décisions 01 et 03).

    Propriété
    ---------
    - L'orchestrateur possède l'état de travail public de chaque conversation
      et est le seul à en produire les révisions. Le backend décrit ce qu'il
      observe, il ne transitionne rien.
    - L'orchestrateur possède les tâches asyncio d'exécution du backend : une
      tâche par `correlation_id`, indexée dans `_tasks`. `BrainBackend` n'expose
      volontairement pas de `cancel()` ; l'annulation passe par l'annulation de
      la tâche, donc par un `CancelledError` levé dans `run_turn`.
    - Un seul cerveau, pas de pool ni d'ordonnanceur multi-agents (Décision 03).
    - L'orchestrateur possède la **révision d'intention** : lui seul publie
      `brain.intent.revised`, et lui seul décide du sort du travail en cours.
      La règle est la rétention : un nouveau tour utilisateur, fût-il une
      interruption, garde tout ce qui tourne. Retirer du travail exige une
      décision explicite du cerveau désignant un `work_id`
      (`BrainEventKind.SUPERSEDED` ou `CANCELLED`) ; ni la surface vocale ni
      l'ordonnanceur de parole n'en ont le droit (spec section 9).
    - Corollaire de la Décision 44 : un tour dont la surface n'était pas sûre
      qu'il lui était adressé n'écrit pas l'intention en arrivant. Il est
      persisté et dépêché, mais l'état public reste celui d'avant jusqu'à ce que
      le cerveau montre qu'il le prend. Décider qu'un propos est une demande est
      une décision d'intention, et l'intention appartient au cerveau.

    Concurrence
    -----------
    - `submit()` rend une `BrainTurnAcceptance` sans jamais attendre le backend
      (spec section 4) : la persistance et la publication sont synchrones, le
      travail fort est différé dans une tâche.
    - `_lock` sérialise le triptyque indissociable « déduplication → persistance
      → révision d'état », de sorte que deux soumissions concurrentes portant la
      même corrélation ne puissent ni doubler l'écriture ni doubler la dépêche
      (Décision 06).
    - Les événements de bus sont publiés depuis la tâche qui les provoque, donc
      dans l'ordre causal : `brain.turn.accepted` précède toujours la parole du
      tour, puisqu'il est publié avant même la création de la tâche.

    Confidentialité
    ---------------
    Rien de ce qui est publié ne sort de `BrainWorkingState.to_public_payload()`
    ou d'un texte rédigé pour l'utilisateur (Décision 12).
    """

    #: Profondeur de relecture pour la dérivation d'état après redémarrage.
    #: Assez pour couvrir plusieurs échanges, assez peu pour que la lecture
    #: reste bornée : au-delà, ce n'est plus une reprise, c'est un historique.
    REHYDRATION_TURN_LIMIT = 50

    def __init__(
        self,
        *,
        conversations: ConversationService,
        events: CoreEventBus,
        backend: BrainBackend | None = None,
        jobs: WorkCanceller | None = None,
        diagnostics: DiagnosticSink | None = None,
        transient_speech_ttl_s: float = DEFAULT_TRANSIENT_SPEECH_TTL_S,
        supersede_stale_replies: bool = True,
        turn_budget_s: float = DEFAULT_TURN_BUDGET_S,
        work_context: BrainContextBuilder | None = None,
    ) -> None:
        self._conversations = conversations
        self._events = events
        self._backend: BrainBackend = backend or NullBrainBackend()
        # Optionnel : sans executeur cable, une annulation reste une decision
        # d'etat publiee, elle n'arrete simplement aucun job.
        self._jobs = jobs
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        # Chronomètre des deux mesures dont Core possède les deux bornes : le
        # travail commence et se solde ici, la surface vocale n'en voit rien.
        self._latency = LatencyTracker(self._diagnostics)
        self._transient_speech_ttl_s = transient_speech_ttl_s
        self._lock = asyncio.Lock()
        self._states: dict[str, BrainWorkingState] = {}
        self._accepted: dict[str, BrainTurnAcceptance] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # Seul le tour qui active un travail en devient propriétaire. Un tour
        # qui décrit un travail déjà actif ne peut pas le solder en échouant.
        # Aucun lien avec l'annulation des jobs exécutés indépendamment de Core.
        self._work_owners: dict[tuple[str, str], str] = {}
        # Corrélations dont l'échec a déjà été rédigé en parole. Un tour en
        # échec publie deux `brain.work.failed` (portée travail puis portée
        # tour) et le backend peut en plus émettre sa propre parole d'erreur :
        # l'utilisateur ne doit entendre la nouvelle qu'une fois. L'entrée est
        # retirée quand la tâche du tour se solde.
        self._error_spoken: set[str] = set()
        # Travaux annules explicitement par le cerveau, par conversation. Sert a
        # trancher la course « le resultat arrive pendant la revision » : une
        # parole dont le travail vient d'etre annule n'est plus vraie, meme si
        # la tache qui l'emet n'a pas encore vu l'annulation. Borne par le
        # nombre de travaux d'une conversation.
        self._cancelled_work: dict[str, set[str]] = {}
        # Tours `uncertain` soumis mais dont le cerveau n'a pas encore montré
        # qu'il les prenait (Décision 44). Indexés par corrélation, retirés dès
        # la promotion ou à la fin de la tâche du tour : bornés par le nombre de
        # tours en vol.
        self._unconfirmed_turns: dict[str, tuple[int, BrainTurnInput]] = {}
        # L'ordre d'arrivée distingue l'intention de l'ordre des réponses async.
        # Une confirmation ancienne ne remplace pas une intention plus récente ;
        # un tour encore incertain, lui, ne bloque aucune confirmation.
        self._turn_seq = 0
        self._confirmed_turn_order: dict[str, int] = {}
        self._stopping = False
        # Retour utilisateur n° 8 : une réponse prête mais encore en file quand
        # l'utilisateur relance n'est plus cohérente avec ce qu'il vient de
        # dire, et bouchait la file (30 à 37 s de retard mesurés). Travaux
        # dont le cerveau a déjà émis la parole, par conversation, avec le
        # numéro d'ordre de cette parole ; vidé à chaque nouvelle intention.
        self._supersede_stale_replies = supersede_stale_replies
        self._spoken_works: dict[str, dict[str, int]] = {}
        # Numéro d'ordre des paroles émises ; un tour incertain retient celui
        # de son arrivée (`_unconfirmed_since`), borné comme `_unconfirmed_turns`.
        self._speech_seq = 0
        self._unconfirmed_since: dict[str, int] = {}
        self._turn_budget_s = turn_budget_s
        # Conversation du dernier tour reçu : c'est là que va un relais
        # spontané du cerveau, qu'aucun tour n'attend (`announce_notice`).
        self._last_conversation_id: str | None = None
        # Travail en cours lu dans l'état de travail Core à chaque tour (tâche
        # 12 du handoff work-state), remis aux seuls backends qui savent le
        # recevoir (`supports_brain_context`).
        self._work_context = work_context

    # -- lecture ------------------------------------------------------------

    @property
    def backend(self) -> BrainBackend:
        return self._backend

    @property
    def active_turn_count(self) -> int:
        """Nombre de tours dont la tâche backend est encore en vol."""

        return len(self._tasks)

    def working_state(self, conversation_id: str) -> BrainWorkingState:
        """État public courant d'une conversation, révision 0 si jamais touchée."""

        return self._states.get(conversation_id) or BrainWorkingState(conversation_id=conversation_id)

    async def rehydrate(self, conversation_id: str) -> dict[str, Any]:
        """Rendre de quoi reprendre une conversation après un mute (Décision 33).

        `Jarvis Mute` ne réveille pas la surface pour prononcer un résultat :
        la parole périme, le travail continue dans Core. Ce que l'utilisateur
        n'a pas entendu doit donc rester **lisible**, et c'est ce que rend
        cette projection — dont `known_public_facts`, où atterrit le résumé
        public de chaque tour terminé.

        Persistance (question ouverte n°2) : aucun schéma dédié. Tant que Core
        tourne, l'état vit en mémoire et le mute — le cas visé par la
        Décision 33 — est entièrement couvert. Si Core a redémarré, l'état est
        **dérivé** des tours persistés : la dernière intention utilisateur
        faisant autorité, et les paroles cerveau réellement prononcées, que
        l'ordonnanceur persiste avec leur provenance (spec section 15).

        Limite assumée, symétrique de la Décision 29 : un résultat produit
        pendant un mute n'a jamais été prononcé, donc aucun tour ne le porte —
        un redémarrage de Core dans cette fenêtre le perd. Le corriger
        demanderait de persister de la parole que l'utilisateur n'a pas
        entendue, donc un schéma neuf pour une fenêtre étroite.
        """

        state = await self._ensure_state(conversation_id)
        return state.to_rehydration_payload()

    async def _ensure_state(self, conversation_id: str) -> BrainWorkingState:
        """Résoudre l'état public d'une conversation, en le dérivant s'il est froid.

        Unique couture de la reprise à froid (Décision 38) : `rehydrate()` et
        `submit()` passent tous deux par ici, donc un tour faisant autorité qui
        arrive après un redémarrage de Core repart de la **même** dérivation
        que la réhydratation, et non d'un état vide. Sans cela, le cerveau
        commençait son premier tour aveugle alors que la dérivation dont il a
        besoin existait déjà juste à côté.

        L'état dérivé est mémorisé : les révisions suivantes repartent de lui
        plutôt que d'un état vide, et le magasin n'est plus relu.

        Verrou : ni `rehydrate()` ni `_derive_state()` ne prennent `_lock`, donc
        l'appel depuis `submit()` — qui le tient — ne peut pas s'auto-bloquer.

        Coût sur le chemin d'ingress : la lecture n'a lieu qu'une fois par
        conversation et par processus (dès la première résolution, `_states`
        répond), elle est bornée par `REHYDRATION_TURN_LIMIT`, et `submit()`
        écrit déjà dans ce même magasin sous ce même verrou. Elle n'ajoute donc
        pas de classe d'attente nouvelle, et l'invariant de la Tâche 03 tient :
        l'accusé est rendu avant toute exécution du backend, qui n'est lancé
        qu'ensuite.
        """

        cached = self._states.get(conversation_id)
        if cached is not None:
            return cached
        derived = await self._derive_state(conversation_id)
        # `setdefault` : une réhydratation concurrente a pu gagner la course
        # pendant la lecture du magasin ; c'est l'état déjà publié qui fait foi.
        return self._states.setdefault(conversation_id, derived)

    async def _derive_state(self, conversation_id: str) -> BrainWorkingState:
        """Reconstruire un état public à partir des seuls tours persistés.

        Rien n'est inventé : l'intention vient d'un tour utilisateur marqué
        `authoritative`, les faits publics des tours assistants dont la
        provenance est `brain.speech` et le genre `result`. Les questions
        retenues sont celles posées **après** le dernier tour utilisateur ;
        au-delà, l'utilisateur a déjà repris la main.

        La révision repart de 0 : les numéros ne sont monotones que dans la
        vie d'un processus, et un consommateur qui redémarre avec Core repart
        lui aussi de zéro (Décision 31 : on ne rejoue pas, on réhydrate).

        Adressage incertain (Décision 44) : un tour marqué `uncertain` ne
        devient pas l'intention du seul fait d'être persisté — il l'est
        toujours, la Décision 06 l'exige — mais reste **en attente** jusqu'à
        trouver, plus loin dans le journal, une parole du cerveau portant sa
        corrélation. C'est la trace persistée de la même confirmation qu'en vol :
        le cerveau s'est adressé à l'utilisateur sur ce tour. Un tour récusé par
        `[pas-pour-moi]` ne produit aucune parole, donc rien ne le ressuscite.
        """

        intent = ""
        facts: list[str] = []
        questions: list[str] = []
        # Tours incertains vus mais pas encore confirmés, par corrélation. Le
        # journal est chronologique : l'arrivée du tour confirmé le plus récent
        # fait l'intention, même si une réponse plus ancienne arrive après.
        pending_uncertain: dict[str, tuple[int, str]] = {}
        confirmed_order = -1
        turns = await self._conversations.list_turns(conversation_id, limit=self.REHYDRATION_TURN_LIMIT)
        for order, turn in enumerate(turns):
            metadata = turn.metadata or {}
            if turn.kind is TurnKind.USER and metadata.get("authoritative"):
                if metadata.get("addressing") == AddressingDecision.UNCERTAIN.value:
                    pending_uncertain[turn.correlation_id] = (order, turn.content)
                    continue
                intent = turn.content
                confirmed_order = order
                # Un nouveau tour utilisateur clôt les questions ouvertes,
                # exactement comme en vol.
                questions.clear()
                pending_uncertain.clear()
                continue
            if turn.kind is not TurnKind.ASSISTANT:
                continue
            if metadata.get("provenance") != SpeechProvenance.BRAIN.value:
                continue
            speech_kind = str(metadata.get("speech_kind") or "")
            if speech_kind != SpeechKind.ERROR.value:
                confirmed = pending_uncertain.pop(turn.correlation_id, None)
                if confirmed is not None and confirmed[0] > confirmed_order:
                    # Résolu avant les filtres ci-dessous : une phrase coupée
                    # prouve quand même que le cerveau a pris ce tour, même si
                    # son contenu ne compte pas comme fait public.
                    confirmed_order, intent = confirmed
                    questions.clear()
            if metadata.get("delivery") == SPEECH_DELIVERY_PARTIAL:
                # Phrase coupee par la parole de l'utilisateur : elle est dans
                # l'historique parce que Jarvis l'a commencee, mais elle n'a pas
                # ete entendue jusqu'au bout. La compter comme un fait public
                # connu - ou comme une question posee - ferait exactement ce que
                # le critere d'acceptation 2 interdit.
                continue
            if speech_kind == SpeechKind.RESULT.value and turn.content not in facts:
                facts.append(turn.content)
            elif speech_kind == SpeechKind.QUESTION.value and turn.content not in questions:
                questions.append(turn.content)
        return BrainWorkingState(
            conversation_id=conversation_id,
            current_user_intent=intent,
            known_public_facts=tuple(facts),
            unresolved_questions=tuple(questions),
        )

    # -- ingress ------------------------------------------------------------

    async def submit(self, turn: BrainTurnInput) -> BrainTurnAcceptance:
        """Accepter un tour utilisateur faisant autorité et rendre l'accusé immédiatement.

        Retourne avant toute exécution du backend. Un tour déjà accepté est
        reconnu comme doublon : il n'est ni repersisté, ni republié, ni
        redépêché, et l'accusé d'origine est rendu avec `duplicate=True`.

        Deux régimes, selon ce que la surface a cru de l'adressage (Décision 44) :

        - `addressed` : le tour devient l'intention courante sur-le-champ, comme
          il l'a toujours fait. Rien ne change pour le mode `legacy`, qui ne
          produit jamais d'autre marque.
        - `uncertain` : le tour est persisté et dépêché au cerveau, mais l'état
          public n'est **pas** révisé. Il ne le sera que si le cerveau montre
          qu'il prenait ce tour (`_promote_uncertain_turn`).

        Lève `KeyError` si la conversation est inconnue (validation avant toute
        écriture) et `RuntimeError` si l'orchestrateur est en cours d'arrêt.
        """

        if self._stopping:
            raise RuntimeError("brain orchestrator is stopping; no new turn is accepted")
        async with self._lock:
            duplicate = self._find_duplicate(turn)
            if duplicate is not None:
                return replace(duplicate, duplicate=True)

            record = await self._conversations.append_turn(
                turn.conversation_id,
                TurnKind.USER,
                turn.text,
                correlation_id=turn.correlation_id,
                metadata={
                    "authoritative": True,
                    "final": True,
                    "source": turn.source.value,
                    # Décision 44 : un tour routé sans certitude d'adressage
                    # reste reconnaissable après coup, dans l'historique comme
                    # dans les traces. Il est autoritaire au même titre — c'est
                    # bien un transcript complet — mais le cerveau, et le
                    # lecteur de l'historique, savent d'où vient le doute.
                    "addressing": turn.addressing.value,

                    "provider_item_id": turn.provider_item_id,
                    "interrupted_speech_id": turn.interrupted_speech_id,
                },
            )
            # Le nouveau tour vaut réponse ou changement de sujet : les
            # questions restées ouvertes cessent de l'être. Le travail actif,
            # lui, n'est pas touché — c'est le cerveau qui décide de le réviser
            # ou de l'annuler (Décision 16).
            # Reprise à froid (Décision 38) : sur une conversation sans état en
            # cache — typiquement après un redémarrage de Core — l'état est
            # dérivé des tours persistés avant de réviser, sinon le cerveau
            # recevrait un état vide au premier tour faisant autorité. Résolu
            # ici, donc après `append_turn` : la conversation est validée, et
            # rien n'entre dans `_states` pour une conversation inconnue. Le
            # tour qu'on vient d'écrire est relu par la dérivation, sans
            # conséquence : sur un tour adressé, la révision ci-dessous impose
            # de toute façon cette intention et vide les questions ouvertes ; sur
            # un tour incertain, la dérivation le laisse en attente au lieu d'en
            # faire une intention (voir `_derive_state`).
            state = await self._ensure_state(turn.conversation_id)
            self._turn_seq += 1
            self._last_conversation_id = turn.conversation_id
            revision: BrainIntentRevision | None = None
            superseded: tuple[str, ...] = ()
            if turn.addressing is AddressingDecision.UNCERTAIN:
                # Moitié aval de la Décision 44. La surface ne jette plus un
                # tour douteux, elle transmet le doute : Core ne doit donc pas
                # le convertir aussitôt en vérité. Tant que le cerveau n'a pas
                # montré qu'il prenait ce tour, l'état public reste celui
                # d'avant — l'intention courante et les questions ouvertes
                # survivent. C'est exactement cet état-là que la Décision 45
                # renvoie au cerveau : une phrase captée à la télévision ne doit
                # pas devenir ce que Core lui affirme.
                self._unconfirmed_turns[turn.correlation_id] = (self._turn_seq, turn)
                # Repère pour la promotion : seules les réponses émises avant
                # l'arrivée de ce tour pourront alors être déclarées périmées.
                self._unconfirmed_since[turn.correlation_id] = self._speech_seq
            else:
                self._confirmed_turn_order[turn.conversation_id] = self._turn_seq
                state = self._revise(turn.conversation_id, current_user_intent=turn.text, unresolved_questions=())
                # Rétention par défaut, rendue explicite et observable : une
                # nouvelle intention utilisateur — y compris celle qui a coupé la
                # parole à Jarvis — garde tout le travail en cours. Core ne peut
                # d'ailleurs pas savoir ici ce que le cerveau va décider : seule une
                # décision explicite ultérieure retirera un travail.
                # Seule exception, qui ne retire aucun travail : la parole déjà
                # émise par les tours précédents et pas encore dite est périmée
                # (`superseded`), l'utilisateur ayant relancé entre-temps.
                # L'ordonnanceur ne la retire que de sa file : une phrase en
                # cours de lecture n'est jamais coupée par ce chemin.
                superseded = self._take_stale_replies(turn.conversation_id, before_seq=None)
                revision = BrainIntentRevision(
                    conversation_id=turn.conversation_id,
                    revision=state.revision,
                    previous_revision=state.revision - 1,
                    superseded_work_ids=superseded,
                    retained_work_ids=tuple(work_id for work_id in state.active_work_ids if work_id not in superseded),
                )
            acceptance = BrainTurnAcceptance(
                turn_id=record.id,
                conversation_id=turn.conversation_id,
                correlation_id=turn.correlation_id,
                revision=state.revision,
                provider_item_id=turn.provider_item_id,
                interrupted_speech_id=turn.interrupted_speech_id,
            )
            self._remember(turn, acceptance)

            # L'accusé est dû dans tous les cas : le tour a bien été reçu et
            # persisté. Sur un tour incertain il porte la révision **courante**,
            # inchangée, et aucune révision d'intention ne le suit — en publier
            # une qui ne révise rien serait un mensonge. Répéter un numéro ne
            # désynchronise personne : `SpeechScheduler._note_revision` ne
            # s'alarme que d'un **saut** (Décision 31), et la promotion, quand
            # elle vient, reprend la suite à `revision + 1`.
            await self._publish(BRAIN_TURN_ACCEPTED, acceptance.to_payload(), turn.conversation_id, turn.correlation_id)
            if revision is not None:
                await self._publish(BRAIN_INTENT_REVISED, revision.to_payload(), turn.conversation_id, turn.correlation_id)
                await self._publish(BRAIN_STATE_UPDATED, state.to_public_payload(), turn.conversation_id, turn.correlation_id)
            self._note_superseded_replies(turn.conversation_id, turn.correlation_id, superseded)

            task = asyncio.create_task(self._run_turn(turn, state), name=f"jarvis-brain-{turn.correlation_id}")
            self._tasks[turn.correlation_id] = task
            return acceptance

    async def stop(self) -> None:
        """Annuler et solder tout travail cerveau en vol.

        Contrat d'arrêt : chaque tâche reçoit un `CancelledError`, l'arrêt attend
        qu'elles soient toutes soldées, et un tour annulé ne publie rien sur le
        bus — les abonnés disparaissent avec Core, et un `brain.work.failed`
        émis pendant l'arrêt ferait passer une extinction propre pour une panne.
        La trace reste dans le journal de diagnostic.
        """

        self._stopping = True
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    # -- relais spontanés ---------------------------------------------------

    async def announce_notice(self, text: str, *, conversation_id: str | None = None) -> bool:
        """Faire dire un relais que le cerveau a rédigé sans qu'aucun tour l'attende.

        Cas d'usage : un sous-agent d'arrière-plan se termine, le backend
        ouvre de lui-même un tour et le cerveau en résume le résultat. Aucun
        `run_turn` ne porte cette réponse ; sans cette voie, elle était perdue,
        ou livrée à la question suivante à la place de la sienne.

        Le texte est celui du cerveau, jamais reformulé (Décision 13) ; Core
        n'en fabrique aucun (Décision 14). Il part vers la conversation du
        dernier tour reçu, avec sa propre corrélation, et devient un fait
        public comme le résumé d'un tour terminé. La réponse convenue de
        silence (`[pas-pour-moi]`) et un texte vide ne produisent rien.

        Rend True si une parole a été publiée.
        """

        summary = (text or "").strip()
        target = conversation_id or self._last_conversation_id
        if not summary or summary.casefold() == BRAIN_NOT_ADDRESSED_ANSWER.casefold():
            return False
        if self._stopping or not target:
            self._diagnostics.emit(
                BRAIN_NOTICE_DROPPED_KIND,
                "relais du cerveau sans conversation où le dire",
                level="warning",
                data={"reason": "stopping" if self._stopping else "no_conversation", "text": summary[:300]},
            )
            return False
        correlation_id = f"brain-notice:{new_id()}"
        await self._emit_speech(
            SpeechRequest(
                conversation_id=target,
                text=summary,
                kind=SpeechKind.RESULT,
                priority=SpeechPriority.NORMAL,
                correlation_id=correlation_id,
                provenance=SpeechProvenance.BRAIN,
            )
        )
        async with self._lock:
            facts = self.working_state(target).known_public_facts
            state = None if summary in facts else self._revise(target, known_public_facts=facts + (summary,))
        if state is not None:
            await self._publish(BRAIN_STATE_UPDATED, state.to_public_payload(), target, correlation_id)
        self._diagnostics.emit(
            BRAIN_NOTICE_RELAYED_KIND,
            "relais spontané du cerveau transmis à la voix",
            level="info",
            data={"conversation_id": target, "correlation_id": correlation_id},
        )
        return True

    # -- déduplication ------------------------------------------------------

    def _find_duplicate(self, turn: BrainTurnInput) -> BrainTurnAcceptance | None:
        """Chercher un tour déjà accepté (Décision 24).

        `correlation_id` est la clé obligatoire ; `provider_item_id` n'est
        qu'une clé secondaire, absente des surfaces qui n'en produisent pas.
        Elle est portée par conversation, car un identifiant fournisseur n'est
        unique que dans le contexte d'une session.
        """

        for key in self._dedup_keys(turn):
            found = self._accepted.get(key)
            if found is not None:
                return found
        return None

    def _remember(self, turn: BrainTurnInput, acceptance: BrainTurnAcceptance) -> None:
        for key in self._dedup_keys(turn):
            self._accepted[key] = acceptance

    @staticmethod
    def _dedup_keys(turn: BrainTurnInput) -> tuple[str, ...]:
        keys = [f"correlation:{turn.dedup_key}"]
        secondary = turn.secondary_dedup_key
        if secondary:
            keys.append(f"provider_item:{turn.conversation_id}:{secondary}")
        return tuple(keys)

    # -- état ---------------------------------------------------------------

    def _revise(self, conversation_id: str, **changes) -> BrainWorkingState:
        """Produire la révision suivante de l'état public. À appeler sous verrou."""

        current = self.working_state(conversation_id)
        updated = replace(current, revision=current.revision + 1, updated_at=utc_now(), **changes)
        self._states[conversation_id] = updated
        return updated

    def _revise_work(
        self,
        conversation_id: str,
        *,
        activate: str | None = None,
        complete: str | None = None,
        drop: str | None = None,
    ) -> BrainWorkingState | None:
        """Réviser les identifiants de travail, ou rendre None si rien ne change.

        Les révisions ne doivent pas s'incrémenter à vide : une progression qui
        ne modifie aucun identifiant ne mérite pas de nouvel état, sinon les
        numéros de révision perdent leur valeur de repère.
        """

        current = self.working_state(conversation_id)
        active = list(current.active_work_ids)
        completed = list(current.completed_work_ids)
        if activate and activate not in active:
            active.append(activate)
        for work_id in (complete, drop):
            if work_id and work_id in active:
                active.remove(work_id)
        if complete and complete not in completed:
            completed.append(complete)
        if tuple(active) == current.active_work_ids and tuple(completed) == current.completed_work_ids:
            return None
        return self._revise(conversation_id, active_work_ids=tuple(active), completed_work_ids=tuple(completed))

    def _revise_question(self, conversation_id: str, question: str) -> BrainWorkingState | None:
        """Enregistrer une question ouverte du cerveau. À appeler sous verrou.

        Le travail en cours n'est pas touché : `active_work_ids` reste tel
        quel, donc une question peut être posée — et répondue — pendant que le
        travail continue (TASK.md, étape 6). La question est retirée de l'état
        au tour utilisateur suivant, qui vaut réponse ou changement de sujet.
        """

        current = self.working_state(conversation_id)
        text = (question or "").strip()
        if not text or text in current.unresolved_questions:
            return None
        return self._revise(conversation_id, unresolved_questions=current.unresolved_questions + (text,))

    # -- réponses périmées --------------------------------------------------

    def _take_stale_replies(self, conversation_id: str, *, before_seq: int | None) -> tuple[str, ...]:
        """Retirer et rendre les travaux dont la parole a déjà été émise.

        Appelée quand une nouvelle intention s'impose : un tour adressé à son
        arrivée (`before_seq=None`, tout ce qui a été émis jusque-là), ou un
        tour incertain au moment où le cerveau le prend (`before_seq` = repère
        de son arrivée : une réponse émise après lui reste due, comme pour un
        tour adressé). Ne touche aucun travail : seule la parole en attente
        est visée, et l'ordonnanceur vocal ne la retire que de sa file.
        """

        if not self._supersede_stale_replies:
            return ()
        spoken = self._spoken_works.get(conversation_id)
        if not spoken:
            return ()
        stale = tuple(work_id for work_id, seq in spoken.items() if before_seq is None or seq <= before_seq)
        for work_id in stale:
            del spoken[work_id]
        return stale

    def _note_superseded_replies(self, conversation_id: str, correlation_id: str, work_ids: tuple[str, ...]) -> None:
        if work_ids:
            self._diagnostics.emit(
                BRAIN_REPLIES_SUPERSEDED_KIND,
                "nouvelle intention : la parole encore en attente des tours précédents est périmée",
                level="info",
                data={"conversation_id": conversation_id, "correlation_id": correlation_id, "work_ids": list(work_ids)},
            )

    # -- adressage incertain ------------------------------------------------

    async def _promote_uncertain_turn(self, correlation_id: str) -> None:
        """Faire d'un tour `uncertain` l'intention courante, le cerveau l'ayant pris.

        Moitié aval de la Décision 44 : la surface transmet le doute, le cerveau
        le tranche. Ce n'est pas un jeton dédié qui le dit — il n'en existe qu'un,
        et c'est celui de la **récusation** (`BRAIN_NOT_ADDRESSED_ANSWER`, mappé
        en réponse vide par l'adaptateur). Le signal retenu est donc le plus
        honnête disponible sans rien inventer au contrat : le cerveau a produit,
        sur ce tour, quelque chose adressé à l'utilisateur — une parole qui n'est
        pas une erreur, ou un résumé public non vide en fin de tour. Un tour qui
        échoue, qui est annulé, ou qui se solde sans un mot ne prouve rien : il
        laisse l'état public exactement où il était.

        Idempotente : le premier signal promeut, les suivants ne trouvent plus
        rien à promouvoir, donc un tour ne consomme jamais deux révisions.

        Ne prend pas `_lock` à l'entrée : elle est appelée depuis des chemins
        qui le prennent juste après (`_emit_speech`, `_settle`), et
        `asyncio.Lock` n'est pas réentrant.
        """

        pending = self._unconfirmed_turns.pop(correlation_id, None)
        arrived_at = self._unconfirmed_since.pop(correlation_id, self._speech_seq)
        if pending is None:
            return
        turn_order, turn = pending
        async with self._lock:
            if turn_order <= self._confirmed_turn_order.get(turn.conversation_id, 0):
                # Le travail et son résultat restent valides ; seule la promotion
                # de cette ancienne intention est désormais sans effet.
                return
            self._confirmed_turn_order[turn.conversation_id] = turn_order
            previous_revision = self.working_state(turn.conversation_id).revision
            state = self._revise(turn.conversation_id, current_user_intent=turn.text, unresolved_questions=())
            # Même règle qu'à l'arrivée d'un tour adressé, appliquée au moment
            # où ce tour devient l'intention.
            superseded = self._take_stale_replies(turn.conversation_id, before_seq=arrived_at)
            revision = BrainIntentRevision(
                conversation_id=turn.conversation_id,
                revision=state.revision,
                previous_revision=previous_revision,
                superseded_work_ids=superseded,
                retained_work_ids=tuple(work_id for work_id in state.active_work_ids if work_id not in superseded),
            )
        # Même séquence que pour un tour adressé, simplement décalée au moment
        # où elle devient vraie. Le consommateur qui suit les numéros de révision
        # voit `previous_revision` suivre l'accusé sans trou (Décision 31).
        await self._publish(BRAIN_INTENT_REVISED, revision.to_payload(), turn.conversation_id, turn.correlation_id)
        await self._publish(BRAIN_STATE_UPDATED, state.to_public_payload(), turn.conversation_id, turn.correlation_id)
        self._note_superseded_replies(turn.conversation_id, turn.correlation_id, superseded)

    # -- exécution ----------------------------------------------------------

    async def _run_turn(self, turn: BrainTurnInput, state: BrainWorkingState) -> None:
        """Corps de la tâche possédée par l'orchestrateur pour un tour."""

        sink = _TurnEventSink(orchestrator=self, turn=turn)
        loop = asyncio.get_running_loop()
        started = loop.time()
        # Chien de garde de disponibilité : il ne coupe rien et ne fait rien
        # dire (Décision 14), il rend visible dans la trace un tour qui fait
        # attendre la conversation, au moment même où il la fait attendre.
        slow = loop.call_later(self._turn_budget_s, self._note_slow_turn, turn) if self._turn_budget_s > 0 else None
        cancelled = False
        try:
            result = await self._call_backend(turn, state, sink)
        except asyncio.CancelledError:
            cancelled = True
            self._diagnostics.emit(
                BRAIN_TURN_CANCELLED_KIND,
                "tour cerveau annulé avant la fin du backend",
                level="info",
                data={"conversation_id": turn.conversation_id, "correlation_id": turn.correlation_id},
            )
            raise
        except Exception as exc:
            self._diagnostics.emit(
                BRAIN_TURN_FAILED_KIND,
                "le backend cerveau a échoué",
                level="error",
                data={
                    "conversation_id": turn.conversation_id,
                    "correlation_id": turn.correlation_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            await self._publish_turn_failure(turn, error_class=type(exc).__name__)
        else:
            await self._settle(turn, result)
        finally:
            if slow is not None:
                slow.cancel()
            elapsed_s = loop.time() - started
            if not cancelled and self._turn_budget_s > 0 and elapsed_s > self._turn_budget_s:
                self._diagnostics.emit(
                    BRAIN_TURN_OVER_BUDGET_KIND,
                    f"tour cerveau de {elapsed_s:.1f} s, au-delà de son budget",
                    level="warning",
                    data={
                        "conversation_id": turn.conversation_id,
                        "correlation_id": turn.correlation_id,
                        "duration_ms": round(elapsed_s * 1000),
                        "budget_ms": round(self._turn_budget_s * 1000),
                    },
                )
            self._tasks.pop(turn.correlation_id, None)
            for key, owner in tuple(self._work_owners.items()):
                if key[0] == turn.conversation_id and owner == turn.correlation_id:
                    self._work_owners.pop(key)
            self._error_spoken.discard(turn.correlation_id)
            # Un tour incertain que le cerveau n'a pas pris ne peut plus l'être
            # une fois sa tâche soldée : l'entrée s'en va avec elle.
            self._unconfirmed_turns.pop(turn.correlation_id, None)
            self._unconfirmed_since.pop(turn.correlation_id, None)

    async def _call_backend(self, turn: BrainTurnInput, state: BrainWorkingState, sink: _TurnEventSink) -> BrainTurnResult:
        """Appeler le backend avec le contexte le plus riche qu'il sait recevoir.

        Un backend qui déclare `run_turn_with_context` reçoit un `BrainContext` :
        l'état public du tour et le travail en cours lu par Core à cet instant
        (Décision D16). Les autres reçoivent `run_turn(turn, state, emit)` comme
        avant, et l'état de travail n'est même pas lu pour eux : les
        changements retenus par la politique attendent un backend qui les
        transmette.
        """

        if not supports_brain_context(self._backend):
            return await self._backend.run_turn(turn, state, sink)
        work = None
        if self._work_context is not None:
            work = await self._work_context.work_context(correlation_id=turn.correlation_id)
        return await self._backend.run_turn_with_context(turn, BrainContext(state=state, work=work), sink)

    def _note_slow_turn(self, turn: BrainTurnInput) -> None:
        self._diagnostics.emit(
            BRAIN_TURN_SLOW_KIND,
            "tour cerveau au-delà de son budget : la conversation attend",
            level="warning",
            data={
                "conversation_id": turn.conversation_id,
                "correlation_id": turn.correlation_id,
                "budget_ms": round(self._turn_budget_s * 1000),
                # Tours en vol derrière celui-ci : ceux que l'utilisateur attend.
                "other_turns_in_flight": max(0, len(self._tasks) - 1),
            },
        )

    async def _settle(self, turn: BrainTurnInput, result: BrainTurnResult) -> None:
        if result.correlation_id != turn.correlation_id:
            self._diagnostics.emit(
                BRAIN_BACKEND_CONTRACT_KIND,
                "le backend a rendu un résultat portant une autre corrélation",
                level="error",
                data={
                    "conversation_id": turn.conversation_id,
                    "expected_correlation_id": turn.correlation_id,
                    "returned_correlation_id": result.correlation_id,
                },
            )
            await self._publish_turn_failure(turn, error_class="backend_correlation_mismatch")
            return
        if result.status is BrainRunStatus.FAILED:
            self._diagnostics.emit(
                BRAIN_TURN_FAILED_KIND,
                "le backend cerveau a rendu un échec",
                level="warning",
                data={
                    "conversation_id": turn.conversation_id,
                    "correlation_id": turn.correlation_id,
                    "error": result.error,
                },
            )
            await self._publish_turn_failure(
                turn,
                error_class=_stable_error_class(result.error),
                public_summary=result.public_summary,
            )
            return
        if result.status is BrainRunStatus.CANCELLED:
            # Le backend a renoncé sans lever : rien à annoncer, mais la trace
            # doit exister, sinon un tour disparaît sans explication.
            self._diagnostics.emit(
                BRAIN_TURN_CANCELLED_KIND,
                "le backend cerveau a rendu une annulation",
                level="info",
                data={"conversation_id": turn.conversation_id, "correlation_id": turn.correlation_id},
            )
            return

        # Un tour qui se termine sans rien apprendre de public ne produit pas de
        # révision : même règle que pour les signaux de travail, sinon le numéro
        # de révision cesse de désigner un changement réel.
        summary = result.public_summary.strip()
        # Décision 44 : un résumé public non vide est la preuve que le cerveau a
        # répondu à ce tour, donc qu'il le prenait pour lui. Un résumé vide est
        # au contraire ce que produit la récusation `[pas-pour-moi]`.
        # La promotion précède l'ajout du fait pour que la révision d'intention
        # arrive avant l'état qui la porte.
        if summary:
            await self._promote_uncertain_turn(turn.correlation_id)
        async with self._lock:
            facts = self.working_state(turn.conversation_id).known_public_facts
            if not summary or summary in facts:
                return
            state = self._revise(turn.conversation_id, known_public_facts=facts + (summary,))
        await self._publish(BRAIN_STATE_UPDATED, state.to_public_payload(), turn.conversation_id, turn.correlation_id)

    async def _publish_turn_failure(self, turn: BrainTurnInput, *, error_class: str, public_summary: str = "") -> None:
        """Signaler l'échec d'un tour entier, et le faire dire si le cerveau l'a rédigé.

        `work_id` est nul : la panne porte sur le tour, pas sur une unité de
        travail identifiée. Le contrat `brain.work.failed` reste le seul canal
        d'échec factuel, et l'envelope porte déjà la corrélation du tour.
        """

        await self._settle_failed_turn_work(turn, error_class=error_class)
        await self._publish(
            BRAIN_WORK_FAILED,
            {
                "work_id": None,
                "job_id": None,
                "error_class": error_class,
                "public_summary": public_summary,
            },
            turn.conversation_id,
            turn.correlation_id,
        )
        await self._speak_failure(
            conversation_id=turn.conversation_id,
            correlation_id=turn.correlation_id,
            work_id=None,
            public_summary=public_summary,
        )

    async def _settle_failed_turn_work(self, turn: BrainTurnInput, *, error_class: str) -> None:
        """Solder les travaux backend orphelins, sans annuler aucun job.

        L'échec du tour ne dit rien des travaux d'autres tours. Les événements
        terminaux et les annulations explicites ont déjà retiré leur propriété.
        La transition sous verrou précède la publication, comme celle d'un
        événement FAILED du backend. Aucune parole d'erreur n'est inventée.
        """

        settled: list[tuple[str, BrainWorkingState]] = []
        async with self._lock:
            for key, owner in tuple(self._work_owners.items()):
                conversation_id, work_id = key
                if conversation_id != turn.conversation_id or owner != turn.correlation_id:
                    continue
                self._work_owners.pop(key)
                state = self._revise_work(conversation_id, drop=work_id)
                work_key = self._work_latency_key(conversation_id, work_id)
                self._latency.forget(LATENCY_FIRST_PUBLIC_PROGRESS, work_key)
                self._latency.forget(LATENCY_WORK_COMPLETED, work_key)
                if state is not None:
                    settled.append((work_id, state))
        for work_id, state in settled:
            await self._publish(
                BRAIN_WORK_FAILED,
                {"work_id": work_id, "job_id": None, "error_class": error_class, "public_summary": ""},
                turn.conversation_id,
                turn.correlation_id,
            )
            await self._publish(BRAIN_STATE_UPDATED, state.to_public_payload(), turn.conversation_id, turn.correlation_id)

    @staticmethod
    def _work_latency_key(conversation_id: str, work_id: str | None) -> str:
        # Deux conversations peuvent nommer leur travail de la même façon.
        return repr((conversation_id, work_id)) if work_id else ""

    async def _speak_failure(
        self,
        *,
        conversation_id: str,
        correlation_id: str,
        work_id: str | None,
        public_summary: str,
    ) -> None:
        """Décider de dire une panne — décision qui appartient à Core, pas à la surface.

        Décision 13 : le cerveau émet une parole complète ; la surface la
        restitue. Laisser l'ordonnanceur vocal fabriquer une phrase d'erreur à
        partir d'un `public_summary` remettrait de la politique de parole dans
        la surface, ce que la Décision 13 lui interdit.

        Décision 14 : sans texte rédigé par le cerveau, **rien** n'est
        prononcé. On ne fabrique aucune formulation de repli — l'échec reste
        visible dans `brain.work.failed`, dans le journal et dans l'état
        public.

        Une seule erreur par corrélation : voir `_error_spoken`.
        """

        summary = (public_summary or "").strip()
        if not summary or correlation_id in self._error_spoken:
            return
        await self._emit_speech(
            SpeechRequest(
                conversation_id=conversation_id,
                text=summary,
                kind=SpeechKind.ERROR,
                priority=SpeechPriority.HIGH,
                correlation_id=correlation_id,
                work_id=work_id,
                supersedes_key=work_id,
                provenance=SpeechProvenance.BRAIN,
            )
        )

    # -- traduction des signaux backend -------------------------------------

    async def _dispatch_backend_event(self, event: BrainEvent) -> None:
        """Traduire un `BrainEvent` en événements `brain.*` sur le bus."""

        if event.kind is BrainEventKind.SPEECH:
            await self._publish_speech(event)
            return
        # Les deux décisions de retrait sortent tôt : elles ne publient pas de
        # `brain.work.*` — retirer du travail n'est ni un avancement ni une
        # panne — mais une révision d'intention, qui est leur contrat propre.
        if event.kind is BrainEventKind.SUPERSEDED:
            await self._supersede_work(event)
            return
        if event.kind is BrainEventKind.CANCELLED:
            await self._cancel_work(event)
            return

        state: BrainWorkingState | None = None
        work_key = self._work_latency_key(event.conversation_id, event.work_id)
        if event.kind is BrainEventKind.ACCEPTED:
            async with self._lock:
                self._claim_work(event)
                state = self._revise_work(event.conversation_id, activate=event.work_id)
            # Bornes de départ des mesures 5 et 6 : un travail accepté est un
            # travail qui commence, et c'est de là que l'utilisateur attend.
            self._latency.mark(LATENCY_FIRST_PUBLIC_PROGRESS, work_key)
            self._latency.mark(LATENCY_WORK_COMPLETED, work_key)
            await self._publish(
                BRAIN_WORK_STARTED,
                {
                    "work_id": event.work_id,
                    "job_id": None,
                    "kind": None,
                    "public_label": event.public_summary,
                },
                event.conversation_id,
                event.correlation_id,
            )
        elif event.kind is BrainEventKind.PROGRESS:
            async with self._lock:
                self._claim_work(event)
                state = self._revise_work(event.conversation_id, activate=event.work_id)
            # Mesure 5 : seule la **première** progression compte, et la marque
            # est consommée, donc les suivantes n'émettent rien.
            self._latency.measure(
                LATENCY_FIRST_PUBLIC_PROGRESS,
                work_key,
                kind=BRAIN_FIRST_PROGRESS_LATENCY_KIND,
                data={
                    "conversation_id": event.conversation_id,
                    "correlation_id": event.correlation_id,
                    "work_id": event.work_id,
                },
            )
            await self._publish(
                BRAIN_WORK_PROGRESS,
                {
                    "work_id": event.work_id,
                    "job_id": None,
                    "phase": None,
                    "fraction": None,
                    "public_summary": event.public_summary,
                },
                event.conversation_id,
                event.correlation_id,
            )
        elif event.kind is BrainEventKind.COMPLETED:
            async with self._lock:
                self._work_owners.pop((event.conversation_id, event.work_id), None)
                state = self._revise_work(event.conversation_id, complete=event.work_id)
            # Mesure 6. Un travail qui se termine sans avoir jamais progressé
            # publiquement n'a pas de mesure 5 : sa marque est abandonnée, pas
            # fermée sur la fin, sinon les deux chiffres seraient le même.
            self._latency.measure(
                LATENCY_WORK_COMPLETED,
                work_key,
                kind=BRAIN_WORK_COMPLETED_LATENCY_KIND,
                data={
                    "conversation_id": event.conversation_id,
                    "correlation_id": event.correlation_id,
                    "work_id": event.work_id,
                },
            )
            self._latency.forget(LATENCY_FIRST_PUBLIC_PROGRESS, work_key)
            await self._publish(
                BRAIN_WORK_COMPLETED,
                {
                    "work_id": event.work_id,
                    "job_id": None,
                    "result_ref": None,
                    "public_summary": event.public_summary,
                },
                event.conversation_id,
                event.correlation_id,
            )
        else:  # BrainEventKind.FAILED
            async with self._lock:
                self._work_owners.pop((event.conversation_id, event.work_id), None)
                state = self._revise_work(event.conversation_id, drop=event.work_id)
            # Une panne n'est pas une durée d'exécution : mesurer un travail qui
            # a échoué mélangerait deux populations dans le même chiffre.
            self._latency.forget(LATENCY_FIRST_PUBLIC_PROGRESS, work_key)
            self._latency.forget(LATENCY_WORK_COMPLETED, work_key)
            await self._publish(
                BRAIN_WORK_FAILED,
                {
                    "work_id": event.work_id,
                    "job_id": None,
                    "error_class": _stable_error_class(event.error),
                    "public_summary": event.public_summary,
                },
                event.conversation_id,
                event.correlation_id,
            )
            # Correction d'orchestrateur A : un backend peut rapporter un échec
            # prononçable sans émettre lui-même de parole. C'est à Core de
            # décider qu'il faut le dire, pas à l'ordonnanceur vocal.
            await self._speak_failure(
                conversation_id=event.conversation_id,
                correlation_id=event.correlation_id,
                work_id=event.work_id,
                public_summary=event.public_summary,
            )

        if state is not None:
            await self._publish(BRAIN_STATE_UPDATED, state.to_public_payload(), event.conversation_id, event.correlation_id)

    def _claim_work(self, event: BrainEvent) -> None:
        """Rattacher une nouvelle activation au tour, sous `_lock`."""

        if event.work_id and event.work_id not in self.working_state(event.conversation_id).active_work_ids:
            self._work_owners[(event.conversation_id, event.work_id)] = event.correlation_id

    # -- révision d'intention -----------------------------------------------

    async def _supersede_work(self, event: BrainEvent) -> None:
        """Déclarer périmée la parole en file d'un travail, sans l'arrêter.

        Moitié non destructrice de la révision : le travail reste actif — il
        est donc republié dans `retained_work_ids` — mais ce qui attendait
        d'être dit à son sujet ne décrit plus l'intention courante. C'est
        exactement la Décision 31 appliquée à un travail précis : on périme, on
        ne rejoue pas, et on ne réécrit pas la phrase à la place du cerveau.

        Un travail déjà annulé n'est pas supersédable : il n'y a plus rien à
        périmer, et republier son identifiant ferait croire qu'il tourne.

        La révision est incrémentée bien qu'aucun champ de l'état public ne
        change : la révision **est** le message. Elle est donc annoncée par
        `brain.intent.revised` seul, sans `brain.state.updated` qui répéterait
        une charge utile identique sans dire ce qui a bougé.
        """

        work_id = str(event.work_id)  # garanti non vide par BrainEvent
        async with self._lock:
            if work_id in self._cancelled_work.get(event.conversation_id, ()):
                return
            current = self.working_state(event.conversation_id)
            previous_revision = current.revision
            state = self._revise(event.conversation_id)
            retained = tuple(item for item in state.active_work_ids if item != work_id)
        await self._publish_revision(
            BrainIntentRevision(
                conversation_id=event.conversation_id,
                revision=state.revision,
                previous_revision=previous_revision,
                superseded_work_ids=(work_id,),
                retained_work_ids=retained,
            ),
            correlation_id=event.correlation_id,
        )

    async def _cancel_work(self, event: BrainEvent) -> None:
        """Arrêter un travail sur décision explicite du cerveau, et lui seul.

        Seule voie d'annulation du projet : ni une interruption de la parole,
        ni un nouveau tour utilisateur ne retirent du travail (spec section 12,
        point 9). L'appelant a nommé un `work_id` ; rien d'autre n'est touché.

        Idempotente : annuler deux fois le même travail ne produit qu'une
        révision. Sans cela, un cerveau bavard ferait avancer les numéros de
        révision sans qu'aucun changement ne leur corresponde.
        """

        work_id = str(event.work_id)  # garanti non vide par BrainEvent
        async with self._lock:
            cancelled = self._cancelled_work.setdefault(event.conversation_id, set())
            if work_id in cancelled:
                return
            cancelled.add(work_id)
            self._work_owners.pop((event.conversation_id, work_id), None)
            # Un travail annulé n'aboutira pas : ses deux mesures sont
            # abandonnées, pas fermées.
            work_key = self._work_latency_key(event.conversation_id, work_id)
            self._latency.forget(LATENCY_FIRST_PUBLIC_PROGRESS, work_key)
            self._latency.forget(LATENCY_WORK_COMPLETED, work_key)
            current = self.working_state(event.conversation_id)
            previous_revision = current.revision
            retained = tuple(item for item in current.active_work_ids if item != work_id)
            state = self._revise(event.conversation_id, active_work_ids=retained)
        job_ids = await self._cancel_jobs(work_id)
        self._diagnostics.emit(
            BRAIN_WORK_CANCELLED_KIND,
            "travail annulé sur décision explicite du cerveau",
            level="info",
            data={
                "conversation_id": event.conversation_id,
                "correlation_id": event.correlation_id,
                "work_id": work_id,
                "job_ids": list(job_ids),
                "retained_work_ids": list(retained),
            },
        )
        await self._publish_revision(
            BrainIntentRevision(
                conversation_id=event.conversation_id,
                revision=state.revision,
                previous_revision=previous_revision,
                cancelled_work_ids=(work_id,),
                retained_work_ids=retained,
            ),
            correlation_id=event.correlation_id,
        )
        # L'annulation retire un identifiant de `active_work_ids` : là, l'état
        # public change vraiment, donc il est republié.
        await self._publish(BRAIN_STATE_UPDATED, state.to_public_payload(), event.conversation_id, event.correlation_id)

    async def _cancel_jobs(self, work_id: str) -> tuple[str, ...]:
        """Répercuter l'annulation sur le travail exécutable, s'il y en a.

        Une absence d'exécuteur ou un échec d'annulation ne doit pas empêcher
        la révision d'être publiée : la décision du cerveau reste vraie, et un
        job qui survit doit être visible au diagnostic plutôt que de faire
        échouer le tour en cours.
        """

        if self._jobs is None:
            return ()
        try:
            return tuple(await self._jobs.cancel_work(work_id) or ())
        except Exception as exc:
            self._diagnostics.emit(
                BRAIN_WORK_CANCEL_FAILED_KIND,
                "annulation du travail exécutable en échec",
                level="error",
                data={
                    "work_id": work_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return ()

    async def _publish_revision(self, revision: BrainIntentRevision, *, correlation_id: str) -> None:
        await self._publish(
            BRAIN_INTENT_REVISED,
            revision.to_payload(),
            revision.conversation_id,
            correlation_id,
        )

    async def _publish_speech(self, event: BrainEvent) -> None:
        """Publier une demande de parole, réancrée sur la corrélation du tour.

        Le backend peut fabriquer une `SpeechRequest` avec sa propre corrélation ;
        l'orchestrateur impose celle du tour, sans quoi la parole ne serait plus
        rattachable à ce que l'utilisateur a dit.
        """

        speech: SpeechRequest = event.speech  # garanti non nul par BrainEvent
        if speech.correlation_id != event.correlation_id:
            speech = replace(speech, correlation_id=event.correlation_id)
        await self._emit_speech(speech)

    async def _emit_speech(self, speech: SpeechRequest) -> None:
        """Appliquer la politique de parole de Core, puis publier.

        Deux règles, toutes deux du ressort du cerveau et non de la surface :

        - une parole **transitoire** (progression, accusé) part toujours avec
          une échéance. Sans elle, rien ne la périme hors révision d'intention
          ou trou de flux, et une étape depuis longtemps dépassée reste
          prononçable (Décision 31). Une échéance déjà fixée par le backend est
          respectée : il en sait plus que la valeur par défaut.
        - une question devient un point ouvert de l'état de travail, sans
          fermer le travail en cours : l'utilisateur peut y répondre pendant que
          le travail continue.
        """

        # Course « le résultat arrive au moment de la révision » : la tâche du
        # tour précédent peut être en train d'émettre la parole d'un travail que
        # le cerveau vient d'annuler. Elle est retenue ici, sans attendre que la
        # surface la filtre — l'ordonnanceur vocal ne verrait qu'une phrase
        # légitime, et la Décision 13 lui interdit d'en juger le contenu.
        if speech.work_id and speech.work_id in self._cancelled_work.get(speech.conversation_id, ()):
            self._diagnostics.emit(
                BRAIN_SPEECH_DROPPED_KIND,
                "parole abandonnée : son travail a été annulé par le cerveau",
                level="info",
                data={
                    "conversation_id": speech.conversation_id,
                    "correlation_id": speech.correlation_id,
                    "speech_id": speech.id,
                    "work_id": speech.work_id,
                    "kind": speech.kind.value,
                },
            )
            return

        speech = speech.with_default_ttl(self._transient_speech_ttl_s)
        if speech.kind is SpeechKind.ERROR:
            self._error_spoken.add(speech.correlation_id)
        else:
            # Décision 44 : le cerveau s'adresse à l'utilisateur sur ce tour —
            # il répond, il questionne, il annonce ce qu'il fait. C'est qu'il
            # l'a pris pour lui. Une parole d'**erreur** est exclue : une panne
            # de l'agent ne dit rien de l'adressage. La promotion passe avant
            # `_revise_question`, sinon elle effacerait la question que le
            # cerveau vient de poser sur ce tour-là.
            await self._promote_uncertain_turn(speech.correlation_id)
        # Après la promotion, qui périme la parole des tours précédents : celle-ci
        # sera périmée à son tour par la prochaine intention, si elle attend
        # encore d'être dite. Une parole transitoire a déjà son échéance.
        if self._supersede_stale_replies and speech.work_id and not speech.is_transient:
            self._speech_seq += 1
            self._spoken_works.setdefault(speech.conversation_id, {})[speech.work_id] = self._speech_seq
        state: BrainWorkingState | None = None
        if speech.kind is SpeechKind.QUESTION:
            async with self._lock:
                state = self._revise_question(speech.conversation_id, speech.text)
        await self._publish(BRAIN_SPEECH_REQUESTED, speech.to_payload(), speech.conversation_id, speech.correlation_id)
        if state is not None:
            await self._publish(BRAIN_STATE_UPDATED, state.to_public_payload(), speech.conversation_id, speech.correlation_id)

    async def _publish(self, message_type: str, payload: dict, conversation_id: str, correlation_id: str) -> None:
        await self._events.publish(
            ProtocolEnvelope(
                message_type=message_type,
                payload=payload,
                correlation_id=correlation_id,
                conversation_id=conversation_id,
            )
        )
