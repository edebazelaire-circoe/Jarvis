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

import aiohttp

from jarvis.domain.v2 import (
    BRAIN_NOT_ADDRESSED_ANSWER,
    BrainEvent,
    BrainEventKind,
    BrainRunStatus,
    BrainTurnInput,
    BrainTurnResult,
    BrainWorkingState,
    SpeechKind,
    SpeechPriority,
    SpeechRequest,
)
from jarvis.domain.brain_context import BrainContext, BrainWorkContext
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


def _stable_token(value: object, fallback: str) -> str:
    """Réduire un code fournisseur à un jeton court, minuscule et stable."""

    text = str(value or "").strip().lower()
    cleaned = "".join(char if char in _ALLOWED_TOKEN_CHARS else "_" for char in text)
    return cleaned[:60].strip("_") or fallback


def _turn_context(
    turn: BrainTurnInput,
    state: BrainWorkingState | None,
    work: BrainWorkContext | None = None,
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

    Rien du tour lui-même n'est ajouté ici : le texte voyage dans `text`, et un
    identifiant de corrélation n'apprendrait rien à un modèle.
    """

    context: dict[str, object] = {"addressing": turn.addressing.value}
    if state is not None:
        context["state"] = state.to_rehydration_payload()
    if work is not None:
        # Tâche 12 du handoff work-state : le travail en cours tel que Core le
        # tient, borné par `build_brain_work_context`. Absent quand Core ne l'a
        # pas lu (backend appelé par `run_turn`, ou lecture en échec).
        context["work"] = work.to_payload()
    return context


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

    async def next_notices(self) -> tuple[str, ...]:
        """Attendre les relais spontanés du brain (fin d'un sous-agent).

        Le brain parle parfois sans question : quand un sous-agent d'arrière-
        plan se termine, le CLI lui ouvre un tour et il en résume le résultat.
        Aucun tour Core n'attend cette réponse ; Core interroge donc cette
        méthode en boucle et fait dire ce qu'elle rend.

        Rend un tuple de textes prononçables, vide si rien n'est arrivé pendant
        l'attente. Ne lève jamais, sauf `CancelledError` : une panne de transport
        se solde par une pause puis un tuple vide.
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
        texts: list[str] = []
        for notice in notices:
            if not isinstance(notice, dict):
                continue
            seq = notice.get("seq")
            if isinstance(seq, int) and not isinstance(seq, bool):
                self._notice_after = max(self._notice_after, seq)
            text = _public_answer(notice.get("text"))
            if text:
                texts.append(text)
        return tuple(texts)

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

        return await self._run(turn, context.state, context.work, emit)

    async def _run(
        self,
        turn: BrainTurnInput,
        state: BrainWorkingState | None,
        work: BrainWorkContext | None,
        emit: BrainEventSink,
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
        outcome = await self._ask(turn.text, _turn_context(turn, state, work))
        if outcome.get("ok"):
            return await self._settle_success(turn, work_id, _public_answer(outcome.get("text")), emit)
        return await self._settle_failure(
            turn,
            work_id,
            error=_stable_token(outcome.get("code"), AGENT_TURN_FAILED),
            speech=str(outcome.get("error") or "").strip() or _DEFAULT_ERROR_SPEECH,
            emit=emit,
        )

    async def _settle_success(self, turn: BrainTurnInput, work_id: str, answer: str, emit: BrainEventSink) -> BrainTurnResult:
        """Clore un tour réussi : ce que l'agent a écrit devient de la parole publique."""

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
                        kind=SpeechKind.RESULT,
                        priority=SpeechPriority.HIGH,
                        correlation_id=turn.correlation_id,
                        work_id=work_id,
                        supersedes_key=work_id,
                    ),
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

    async def _ask(self, text: str, context: dict[str, object]) -> dict[str, object]:
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
                json={"text": request, "timeout_s": self.timeout_s, "context": context},
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
