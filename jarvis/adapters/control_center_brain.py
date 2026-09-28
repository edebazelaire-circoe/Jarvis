"""Backend cerveau adossé à l'agent local hébergé par le Control Center.

Décision 23 : cet adaptateur vise `POST /api/agent/ask`, la route
**agent-agnostique** du Control Center. Le choix Claude/Codex est arbitré
là-bas, dans le processus qui possède les agents ; rien de ce choix ne remonte
dans `jarvis/core`, qui ne connaît que le port `BrainBackend`.

Propriété
---------
Cet adaptateur ne possède rien du tour : ni son état, ni sa persistance, ni sa
publication sur le bus. `BrainOrchestrator` possède la tâche asyncio qui
exécute `run_turn`, l'état de travail public et la traduction des `BrainEvent`
en `ProtocolEnvelope` (spec section 3). L'adaptateur ne possède que sa session
HTTP, qu'il crée paresseusement et que le composition root ferme.

Concurrence
-----------
`run_turn` peut être appelé pour plusieurs tours à la fois : chaque appel est
indépendant et n'écrit que dans des variables locales. Le seul état partagé est
la session `aiohttp`, dont la création est sérialisée par un verrou pour qu'une
soumission simultanée n'en ouvre pas deux.

Annulation
----------
`CancelledError` est propagé sans jamais être avalé : l'arrêt de Core annule
les tâches du cerveau et attend qu'elles soient soldées. Un adaptateur qui
transformerait l'annulation en échec bloquerait l'extinction et publierait une
panne là où il n'y a qu'une extinction propre.

Ce module remplace, côté Core, ce que `jarvis/runtime/claude_gateway.py` fait
côté Voice. La passerelle reste en place tant que le chemin legacy existe
(Décision 20) : elle n'est pas supprimée par cette migration.
"""

from __future__ import annotations

import asyncio
import re

import aiohttp

from jarvis.domain.v2 import (
    BRAIN_NOT_ADDRESSED_ANSWER,
    BrainEvent,
    BrainEventKind,
    BrainRunStatus,
    BrainTurnInput,
    BrainTurnResult,
    BrainTurnSource,
    BrainWorkingState,
    SpeechKind,
    SpeechPriority,
    SpeechRequest,
)
from jarvis.domain.brain_notice import NOTICE_TYPING_FIELDS
from jarvis.domain.brain_context import BrainContext, BrainPendingReply, BrainSpeechInterruption, BrainWorkContext
from jarvis.domain.interaction_mode import DEFAULT_INTERACTION_MODE, InteractionMode, behaving_interaction_mode
from jarvis.ports.v2 import BrainEventSink

# Jetons d'erreur stables publiés dans `brain.work.failed.error_class`. Ils
# classent une panne, ils ne la racontent pas : `docs/05-event-contracts.md`
# interdit d'y déverser une trace brute.
BACKEND_TIMEOUT = "brain_backend_timeout"
BACKEND_UNREACHABLE = "brain_backend_unreachable"
BACKEND_HTTP_ERROR = "brain_backend_http_error"
BACKEND_BAD_RESPONSE = "brain_backend_bad_response"
AGENT_TURN_FAILED = "agent_turn_failed"

# Phrase de repli quand l'agent échoue sans rien dire de prononçable.
_DEFAULT_ERROR_SPEECH = "L'agent local n'a pas pu traiter la demande."

_ALLOWED_TOKEN_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_.-"


class _NullSink:
    """Diagnostic par défaut, tant que Core n'a pas branché le sien."""

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        del kind, message, level, data


def _stable_token(value: object, fallback: str) -> str:
    """Réduire un code fournisseur à un jeton court, minuscule et stable."""

    text = str(value or "").strip().lower()
    cleaned = "".join(char if char in _ALLOWED_TOKEN_CHARS else "_" for char in text)
    return cleaned[:60].strip("_") or fallback


def _turn_context(
    turn: BrainTurnInput,
    state: BrainWorkingState | None,
    work: BrainWorkContext | None = None,
    interruptions: tuple[BrainSpeechInterruption, ...] = (),
    pending_replies: tuple[BrainPendingReply, ...] = (),
    interaction_mode: InteractionMode = DEFAULT_INTERACTION_MODE,
) -> dict[str, object]:
    """Le contexte public que Core joint au tour, et rien d'autre.

    Deux choses, décidées ailleurs :

    - `addressing` : ce que la surface a cru du tour au moment de le router.
      Depuis la Décision 44, un `uncertain` n'est plus jeté par la surface mais
      soumis au cerveau ; sans cette marque, l'agent traiterait un propos capté
      à côté exactement comme une demande directe. Le garde-fou de la décision
      est cette ligne-là.
    - `state` : la projection **publique** de l'état de travail, telle que Core
      la définit déjà pour la reprise de conversation (Décision 33). On réutilise
      `to_rehydration_payload()` au lieu d'inventer une projection : c'est ce qui
      garantit mécaniquement qu'aucun champ hors état public ne parte, et
      `BrainWorkingState` ne porte par construction aucun raisonnement caché
      (Décision 12, pinné par `tests/unit/test_v2_brain_contracts.py`).

    - `interaction_mode` : le mode qui pilote le comportement, lu de Core et
      jamais d'ici (Slice 07). Il est joint **à chaque tour** parce qu'il change
      à chaud sans redémarrer quoi que ce soit (Décision D15) : une consigne de
      session serait périmée dès le premier changement. Le runtime reste seul
      juge de ce qui se dit — cette ligne existe pour que le modèle ne rédige
      pas une phrase que la porte jettera, pas pour tenir la règle.
      **Absent au mode par défaut** : le contexte d'un tour assistant est
      exactement celui d'avant cette Slice, octet pour octet (Décision 14).

    Rien du tour lui-même n'est ajouté ici : le texte voyage dans `text`, et un
    identifiant de corrélation n'apprendrait rien à un modèle.
    """

    context: dict[str, object] = {"addressing": turn.addressing.value}
    if turn.source is BrainTurnSource.SYSTEM:
        # Un tour que Core ouvre lui-même (réveil de travail de fond) n'est pas
        # une parole de l'utilisateur : le Control Center ne doit pas le tenir
        # pour un accord (Bare Hands, calibration adaptative, décision 53).
        # Absent pour tout autre tour : leur contexte est celui d'avant.
        context["source"] = turn.source.value
    if interaction_mode is not DEFAULT_INTERACTION_MODE:
        context["interaction_mode"] = interaction_mode.value
    if state is not None:
        context["state"] = state.to_rehydration_payload()
    if work is not None:
        # Tâche 12 du handoff work-state : le travail en cours tel que Core le
        # tient, borné par `build_brain_work_context`. Absent quand Core ne l'a
        # pas lu (backend appelé par `run_turn`, ou lecture en échec).
        context["work"] = work.to_payload()
    if interruptions:
        # Réponses que l'utilisateur a coupées : ce qu'il en a entendu, pour que
        # l'agent ne tienne pas pour dit ce qui ne l'a pas été.
        context["interrupted_speech"] = [item.to_payload() for item in interruptions]
    if pending_replies:
        # Formulations écrites pour une intention passée et pas dites : la
        # bouche les retient, elles ne seront dites que si l'agent les redit
        # maintenant, reformulées (Décision 48, `render_pending_speech`).
        context["pending_speech"] = [item.to_payload() for item in pending_replies]
    return context


def _turn_conversation(turn: BrainTurnInput, work_id: str) -> dict[str, str]:
    """Identifiants du tour pour les Conversation Events des sous-agents (Slice 03b).

    Champ `conversation` de `/api/agent/ask`, distinct de `context` : le
    Control Center ne le donne jamais au modèle. Il permet de rattacher un
    sous-agent à sa conversation et au `brain.work.started` de ce tour
    (`work_id`) sans rien deviner.
    """

    return {"conversation_id": turn.conversation_id, "correlation_id": turn.correlation_id, "work_id": work_id}


#: Ce que l'agent écrit, seul sur une ligne, pour retirer une réponse qu'il a
#: rédigée et qui n'a pas encore été dite. Même nature que
#: `BRAIN_NOT_ADDRESSED_ANSWER` : un jeton convenu dans la réponse, parce que
#: c'est le seul canal que l'agent local possède vers Core (Décision 44). Le
#: `work_id` doit être l'un de ceux que Core vient de lui remettre : le cerveau
#: retire par désignation (Décision 35), et ne peut désigner que ce qui l'attend.
RETIRE_MARKER = "[[jarvis:retire "
#: Décision 48 : ce que l'agent écrit, seul sur une ligne, quand sa réponse
#: redit (reformulée) une formulation remise (`pending_speech`). C'est le lien
#: explicite de réémission (`BrainEvent.revalidates`) : sans lui, la nouvelle
#: réponse est dite quand même, seule l'ancienne formulation est soldée
#: `not_revalidated`. Honoré seulement pour les `speech_id` que Core a remis.
REDIT_MARKER = "[[jarvis:redit "

#: Un marqueur où qu'il soit dans la réponse — seul sur sa ligne, en fin de
#: phrase, suivi d'une ponctuation — n'est jamais prononcé (reprise QA S04 :
#: seul le marqueur isolé sur sa ligne était retiré, l'agent l'écrit aussi en
#: ligne). La ponctuation laissée orpheline est recollée par `_tidy`.
_MARKER = re.compile(r"[ \t]*\[\[jarvis:(retire|redit)\s+([^\]\s]{1,256})\s*\]\]")
#: Filet de dernier recours du règlement d'un tour réussi : tout reste de
#: `[[jarvis:…]]` (marqueur inconnu, mal formé) est retiré avant d'être dit.
_ANY_MARKER = re.compile(r"[ \t]*\[\[jarvis:[^\]]{0,300}\]\]")
_PUNCT_ONLY = re.compile(r"[.,;:!?…]+")


def _tidy(text: str) -> str:
    """Espaces, ponctuation orpheline et lignes vides laissés par un marqueur retiré."""
    lines: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]{2,}", " ", line).strip()
        line = re.sub(r"\s+([.,;:!?…])", r"\1", line)  # « mot . » -> « mot. »
        line = re.sub(r"([.!?…])[.,;:]+", r"\1", line)  # « mot.. » -> « mot. »
        if _PUNCT_ONLY.fullmatch(line):
            continue  # ponctuation seule sur sa ligne : celle du marqueur retiré
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _take_markers(answer: str, verb: str) -> tuple[str, tuple[str, ...]]:
    """Retirer les marqueurs `verb` (où qu'ils soient) et rendre leurs identifiants, dans l'ordre."""
    if f"[[jarvis:{verb}" not in answer:
        return answer, ()
    designated: list[str] = []

    def drop(match: re.Match[str]) -> str:
        if match.group(1) != verb:
            return match.group(0)
        if match.group(2) not in designated:
            designated.append(match.group(2))
        return ""

    return _tidy(_MARKER.sub(drop, answer)), tuple(designated)


def _take_retired(answer: str, pending: tuple[BrainPendingReply, ...]) -> tuple[str, tuple[str, ...]]:
    """Séparer, dans la réponse de l'agent, ce qu'il dit de ce qu'il retire.

    Le marqueur ne se prononce jamais : il est retiré du texte, quoi qu'il
    arrive. Un identifiant qui n'est pas dans ce que Core a remis est ignoré —
    un modèle ne retire pas un travail qu'on ne lui a pas soumis (un retrait
    touche une dépendance, pas seulement une présentation). Depuis la Décision
    48 ne pas redire une formulation suffit à la retirer : le marqueur n'est
    plus enseigné, mais reste honoré.
    """

    text, designated = _take_markers(answer, "retire")
    allowed = {item.work_id for item in pending if item.work_id}
    return text, tuple(work_id for work_id in designated if work_id in allowed)


def _take_redit(answer: str, pending: tuple[BrainPendingReply, ...]) -> tuple[str, tuple[str, ...]]:
    """Séparer, dans la réponse de l'agent, les formulations remises qu'il redit (Décision 48).

    Tous les identifiants nommés partent vers Core, même inconnus : c'est Core
    qui sait ce qu'il a remis à ce tour, qui filtre et qui trace
    (`core.brain.revalidation_ignored`) — un identifiant mal recopié par le
    modèle doit se voir, pas disparaître ici. `pending` n'est plus lu.
    """

    del pending
    return _take_markers(answer, "redit")


def _scrub_markers(answer: str) -> tuple[str, int]:
    """Dernier recours : retirer tout `[[jarvis:…]]` restant ; rend le texte et le nombre retiré."""
    if "[[jarvis:" not in answer:
        return answer, 0
    text, count = _ANY_MARKER.subn("", answer)
    return _tidy(text), count


#: Fin de phrase : une ponctuation terminale suivie d'un blanc ou de la fin du
#: texte. Le « suivie d'un blanc » evite de compter la virgule decimale d'une
#: date ou d'un montant (« du 30.06 »), qui ferait passer une vraie question
#: pour un paragraphe.
_SENTENCE_END = re.compile(r"[.!?…]+(?=\s|$)")


def public_answer_kind(answer: str) -> SpeechKind:
    """Nature de la reponse publique d'un tour : une question, ou un resultat.

    `SpeechKind.QUESTION` existe depuis l'origine et Core en implemente deja
    toute la semantique — une question devient un point ouvert de l'etat de
    travail (`BrainOrchestrator._revise_question`) au lieu d'un fait public
    acquis, et n'est pas retenue comme resultat durable. **Aucun producteur ne
    l'emettait**, donc cette voie etait morte, alors meme que la consigne
    systeme demande explicitement a l'agent de trancher une demande ambigue
    « en une question courte » (`claude_local.BRAIN_SYSTEM_PROMPT`).

    La nature est decidee **ici, par Core, a partir du contenu**, et jamais par
    un champ que l'agent remplirait. C'est ce qui la distingue d'une etiquette :
    l'agent ecrit du francais, il ne nomme pas de categorie, et une affirmation
    ne peut pas se declarer question sans cesser d'etre une affirmation. La
    borne est volontairement stricte — la reponse doit etre **une seule phrase
    interrogative et rien d'autre** — pour qu'une reponse ordinaire suivie
    d'une question de politesse (« Voila le bilan. Tu veux aussi le Q4 ? »)
    reste un resultat : sans cette borne, la nature deviendrait une porte de
    sortie qu'il suffirait de ponctuer.

    Le mode presentation en depend (`safety_speech_kinds`), mais la correction
    ne lui est pas propre : elle vaut dans les deux modes, parce que la voie
    qu'elle alimente n'a jamais ete specifique a la presentation.
    """

    trimmed = (answer or "").strip()
    if not trimmed.endswith("?"):
        return SpeechKind.RESULT
    return SpeechKind.QUESTION if len(_SENTENCE_END.findall(trimmed)) == 1 else SpeechKind.RESULT


def _public_answer(raw: object) -> str:
    """Ce que l'agent a écrit, sauf s'il a dit que le tour n'était pas pour lui.

    Décision 44 : sur un tour `uncertain`, l'agent peut conclure « ce n'était
    pas pour moi ». Il le dit par la réponse convenue, et ce verdict doit
    produire du silence, pas une phrase. Le tour se clôt alors comme un tour
    sans rien de public à annoncer — chemin qui existait déjà pour une réponse
    vide, aucune branche nouvelle en aval.

    La reconnaissance n'est pas conditionnée à l'adressage du tour : un agent
    qui rend ce jeton seul ne demande jamais qu'on le prononce.
    """

    answer = str(raw or "").strip()
    return "" if answer.casefold() == BRAIN_NOT_ADDRESSED_ANSWER.casefold() else answer


class ControlCenterBrainBackend:
    """`BrainBackend` qui délègue le tour à l'agent local du Control Center.

    Le cycle publié pour un tour est symétrique : un travail est ouvert
    (`ACCEPTED`), puis fermé (`COMPLETED` ou `FAILED`). Un tour en échec produit
    donc deux `brain.work.failed` : celui du travail, porteur du `work_id`, et
    celui du tour, que l'orchestrateur publie avec `work_id=None` en réponse au
    `BrainTurnResult`. Les deux sont voulus et distinguables ; un consommateur
    de parole doit dédupliquer par `work_id`, pas compter les événements.
    """

    #: Une tâche d'agent qui lit des fichiers et lance des commandes dure
    #: couramment plusieurs dizaines de secondes.
    DEFAULT_TIMEOUT_S = 600.0

    #: Attente longue demandée au Control Center pour les relais spontanés.
    NOTICE_WAIT_S = 25.0
    #: Pause après une panne de transport, pour ne pas tourner à vide.
    NOTICE_RETRY_S = 5.0
    #: Pause quand l'agent actif ne produit pas de relais (Codex).
    NOTICE_UNSUPPORTED_RETRY_S = 30.0

    def __init__(self, *, base_url: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._http: aiohttp.ClientSession | None = None
        self._http_lock = asyncio.Lock()
        # Curseur de lecture de `/api/agent/notices` : époque de la file et
        # dernier numéro reçu. Époque vide = premier appel, rien n'est rejoué.
        self._notice_epoch = ""
        self._notice_after = 0
        # Mode d'interaction effectif, observé de Core (Slice 07). Capacité
        # optionnelle détectée structurellement par le composition root, comme
        # `next_notices` : un Core sans mode laisse le défaut, c'est-à-dire le
        # comportement d'avant la fonctionnalité (Décision 14).
        self._interaction_mode = DEFAULT_INTERACTION_MODE
        # Trace de Core (`attach_diagnostics`), posée par le composition root.
        self._diagnostics = _NullSink()

    def attach_diagnostics(self, sink) -> None:  # noqa: ANN001 - DiagnosticSink
        """Recevoir le journal de diagnostic de Core (capacité optionnelle, `v2_app`)."""

        self._diagnostics = sink

    def observe_interaction_mode(self, value: object) -> None:
        """Prendre le mode effectif que Core vient d'appliquer.

        Signature exacte de l'abonné de `InteractionModeService.add_listener` :
        un seul argument positionnel, le mode typé (`_notify` appelle
        `listener(state.mode)`). Pas de `source=` — il n'était jamais passé ni
        jamais lu, et un paramètre mort se recopie dans les doubles de test
        jusqu'à ressembler à un contrat.

        `behaving_interaction_mode` et non `stored_` : cette valeur *pilote un
        comportement*, et un mode réservé ne doit jamais arriver jusqu'à une
        consigne de modèle sous la forme d'un comportement à tenir.
        """

        self._interaction_mode = behaving_interaction_mode(value)

    async def next_notices(self) -> tuple[dict[str, object], ...]:
        """Attendre les relais spontanés (fin d'un sous-agent, calibration).

        Le brain parle parfois sans question : quand un sous-agent d'arrière-
        plan se termine, le CLI lui ouvre un tour et il en résume le résultat ;
        le Control Center fait dire l'accusé d'une analyse de calibration puis
        cette analyse. Aucun tour Core n'attend ces paroles ; Core interroge
        donc cette méthode en boucle et fait dire ce qu'elle rend.

        Rend un tuple de notices `{text, kind, supersedes_key, ttl_s, work_id}`
        (contrat `jarvis/domain/brain_notice.py`), vide si rien n'est arrivé
        pendant l'attente. Le genre est **transmis tel que servi**, sans être
        jugé ici : c'est `announce_notice` qui le valide et trace un refus —
        ce client n'a aucun journal où le dire. Une notice de l'ancien format
        (sans `kind`) arrive sans genre et devient un `result`. Ne lève jamais,
        sauf `CancelledError` : une panne de transport se solde par une pause
        puis un tuple vide.
        """

        try:
            http = await self._session()
            async with http.get(
                f"{self.base_url}/api/agent/notices",
                params={"after": str(self._notice_after), "epoch": self._notice_epoch, "wait": str(self.NOTICE_WAIT_S)},
            ) as response:
                if response.status != 200:
                    raise ValueError(f"notices HTTP {response.status}")
                payload = await response.json()
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            await asyncio.sleep(self.NOTICE_RETRY_S)
            return ()
        if not isinstance(payload, dict) or not payload.get("supported"):
            await asyncio.sleep(self.NOTICE_UNSUPPORTED_RETRY_S)
            return ()
        epoch = str(payload.get("epoch") or "")
        notices = payload.get("notices") if isinstance(payload.get("notices"), list) else []
        if epoch != self._notice_epoch:
            # Premier appel ou file recréée : repartir de son dernier numéro.
            self._notice_epoch = epoch
            last_seq = payload.get("last_seq")
            self._notice_after = last_seq if isinstance(last_seq, int) else 0
        relayed: list[dict[str, object]] = []
        for notice in notices:
            if not isinstance(notice, dict):
                continue
            seq = notice.get("seq")
            if isinstance(seq, int) and not isinstance(seq, bool):
                self._notice_after = max(self._notice_after, seq)
            text = _public_answer(notice.get("text"))
            if text:
                relayed.append({"text": text, **{name: notice.get(name) for name in NOTICE_TYPING_FIELDS}})
        return tuple(relayed)

    async def run_turn(self, turn: BrainTurnInput, state: BrainWorkingState, emit: BrainEventSink) -> BrainTurnResult:
        """Exécuter un tour complet et rendre son issue à l'orchestrateur.

        L'état est lu, jamais modifié : les transitions appartiennent à
        l'orchestrateur. Il part avec le tour, dans le champ optionnel
        `context` de `/api/agent/ask` : la session propre de l'agent porte ce
        qu'il a lui-même fait, elle ne porte pas ce que Core sait (Décision 42).
        """

        return await self._run(turn, state, None, emit)

    async def run_turn_with_context(self, turn: BrainTurnInput, context: BrainContext, emit: BrainEventSink) -> BrainTurnResult:
        """Même tour, avec le travail en cours que Core a lu pour lui (capacité
        `ContextAwareBrainBackend`, tâche 12) : il part dans `context.work`."""

        return await self._run(turn, context.state, context.work, emit, interruptions=context.interruptions,
                               pending_replies=context.pending_replies)

    async def _run(
        self,
        turn: BrainTurnInput,
        state: BrainWorkingState | None,
        work: BrainWorkContext | None,
        emit: BrainEventSink,
        *,
        interruptions: tuple[BrainSpeechInterruption, ...] = (),
        pending_replies: tuple[BrainPendingReply, ...] = (),
    ) -> BrainTurnResult:
        work_id = f"brain-turn:{turn.correlation_id}"
        await emit.emit(
            BrainEvent(
                kind=BrainEventKind.ACCEPTED,
                conversation_id=turn.conversation_id,
                correlation_id=turn.correlation_id,
                work_id=work_id,
                public_summary="Demande transmise à l'agent local.",
            )
        )
        outcome = await self._ask(turn.text, _turn_context(turn, state, work, interruptions, pending_replies,
                                                           self._interaction_mode),
                                  conversation=_turn_conversation(turn, work_id))
        if outcome.get("ok"):
            answer, retired = _take_retired(_public_answer(outcome.get("text")), pending_replies)
            answer, revalidates = _take_redit(answer, pending_replies)
            answer, scrubbed = _scrub_markers(answer)
            if scrubbed:
                # Jamais attendu : les deux marqueurs connus sont déjà retirés.
                self._diagnostics.emit(
                    "core.brain.marker_scrubbed", "marqueur jarvis résiduel retiré de la réponse avant la parole",
                    level="warning", data={"conversation_id": turn.conversation_id,
                                           "correlation_id": turn.correlation_id, "count": scrubbed})
            return await self._settle_success(turn, work_id, answer, emit, retired=retired,
                                              revalidates=revalidates)
        return await self._settle_failure(
            turn,
            work_id,
            error=_stable_token(outcome.get("code"), AGENT_TURN_FAILED),
            speech=str(outcome.get("error") or "").strip() or _DEFAULT_ERROR_SPEECH,
            emit=emit,
        )

    async def _settle_success(self, turn: BrainTurnInput, work_id: str, answer: str, emit: BrainEventSink,
                              *, retired: tuple[str, ...] = (), revalidates: tuple[str, ...] = ()) -> BrainTurnResult:
        """Clore un tour réussi : ce que l'agent a écrit devient de la parole publique.

        Avant de dire ce tour-ci, l'agent solde ce qu'il retire : une réponse
        écrite plus tôt et pas encore dite, qu'il juge caduque après ce que
        l'utilisateur vient de dire. C'est la moitié « abandonnée explicitement »
        de la décision du 19/09/2026, et elle passe par le seul chemin de
        retrait qui existe : une désignation nommée (Décision 35).
        """

        for retired_work_id in retired:
            await emit.emit(
                BrainEvent(
                    kind=BrainEventKind.SUPERSEDED,
                    conversation_id=turn.conversation_id,
                    correlation_id=turn.correlation_id,
                    work_id=retired_work_id,
                )
            )
        await emit.emit(
            BrainEvent(
                kind=BrainEventKind.COMPLETED,
                conversation_id=turn.conversation_id,
                correlation_id=turn.correlation_id,
                work_id=work_id,
                public_summary=answer,
            )
        )
        if answer:
            # `supersedes_key` rattaché au travail : une progression du même
            # travail devient caduque dès que le résultat existe (spec §6).
            await emit.emit(
                BrainEvent(
                    kind=BrainEventKind.SPEECH,
                    conversation_id=turn.conversation_id,
                    correlation_id=turn.correlation_id,
                    work_id=work_id,
                    speech=SpeechRequest(
                        conversation_id=turn.conversation_id,
                        text=answer,
                        kind=public_answer_kind(answer),
                        priority=SpeechPriority.HIGH,
                        correlation_id=turn.correlation_id,
                        work_id=work_id,
                        supersedes_key=work_id,
                    ),
                    revalidates=revalidates,
                )
            )
        return BrainTurnResult(
            correlation_id=turn.correlation_id,
            status=BrainRunStatus.COMPLETED,
            public_summary=answer,
        )

    async def _settle_failure(self, turn: BrainTurnInput, work_id: str, *, error: str, speech: str, emit: BrainEventSink) -> BrainTurnResult:
        """Clore un tour en échec sans jamais casser la conversation.

        Une panne de l'agent revient sous forme de parole : l'utilisateur a
        attendu, il doit entendre pourquoi il n'aura pas de réponse.
        """

        await emit.emit(
            BrainEvent(
                kind=BrainEventKind.SPEECH,
                conversation_id=turn.conversation_id,
                correlation_id=turn.correlation_id,
                work_id=work_id,
                speech=SpeechRequest(
                    conversation_id=turn.conversation_id,
                    text=speech,
                    kind=SpeechKind.ERROR,
                    priority=SpeechPriority.HIGH,
                    correlation_id=turn.correlation_id,
                    work_id=work_id,
                    supersedes_key=work_id,
                ),
            )
        )
        await emit.emit(
            BrainEvent(
                kind=BrainEventKind.FAILED,
                conversation_id=turn.conversation_id,
                correlation_id=turn.correlation_id,
                work_id=work_id,
                public_summary=speech,
                error=error,
            )
        )
        return BrainTurnResult(
            correlation_id=turn.correlation_id,
            status=BrainRunStatus.FAILED,
            error=error,
        )

    # -- transport ----------------------------------------------------------

    async def _ask(self, text: str, context: dict[str, object],
                   conversation: dict[str, str] | None = None) -> dict[str, object]:
        """Aller-retour HTTP vers l'agent, traduit en issue neutre.

        Rend toujours un dictionnaire : aucune panne de transport ne remonte en
        exception, sauf `CancelledError`, qui doit traverser intact.

        `context` est un champ **optionnel** de la route : la passerelle legacy
        (`jarvis/runtime/claude_gateway.py`) et le panneau navigateur ne
        l'envoient pas et gardent exactement leur comportement d'avant.
        """

        request = (text or "").strip()
        if not request:
            return {"ok": False, "code": BACKEND_BAD_RESPONSE, "error": "La demande transmise au cerveau était vide."}
        try:
            http = await self._session()
            async with http.post(
                f"{self.base_url}/api/agent/ask",
                json={"text": request, "timeout_s": self.timeout_s, "context": context,
                      **({"conversation": conversation} if conversation is not None else {})},
            ) as response:
                if response.status != 200:
                    return {
                        "ok": False,
                        "code": BACKEND_HTTP_ERROR,
                        "error": f"L'agent local n'a pas pu être joint ({response.status}).",
                    }
                payload = await response.json()
        except asyncio.CancelledError:
            # Contrat d'arrêt : l'annulation appartient à l'orchestrateur.
            raise
        except asyncio.TimeoutError:
            return {"ok": False, "code": BACKEND_TIMEOUT, "error": "L'agent local met trop de temps à répondre."}
        except (aiohttp.ClientError, ValueError) as exc:
            # `ValueError` couvre une réponse annoncée JSON mais illisible.
            del exc
            return {"ok": False, "code": BACKEND_UNREACHABLE, "error": "L'agent local n'est pas joignable."}

        if not isinstance(payload, dict):
            return {"ok": False, "code": BACKEND_BAD_RESPONSE, "error": "Réponse inattendue de l'agent local."}
        if not payload.get("ok"):
            return {"ok": False, "code": payload.get("code") or AGENT_TURN_FAILED, "error": payload.get("error")}
        return {"ok": True, "text": payload.get("text") or ""}

    async def _session(self) -> aiohttp.ClientSession:
        async with self._http_lock:
            if self._http is None or self._http.closed:
                # La marge couvre le trajet HTTP : c'est le Control Center qui
                # arbitre le vrai délai d'attente de l'agent.
                self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout_s + 30))
            return self._http

    async def close(self) -> None:
        """Fermer la session HTTP. Appelé par le composition root, pas par Core."""

        async with self._http_lock:
            http, self._http = self._http, None
        if http is not None and not http.closed:
            await http.close()
