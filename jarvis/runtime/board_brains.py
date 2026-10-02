"""Pool des cerveaux de Board du Control Center (handoff board-session, Slice 04a).

Core possède les Boards, les Sessions et les liaisons ; le Control Center
possède les **processus** d'agent (06 section A/B, `docs/boards.md`). Ce module
tient un agent par liaison (`BoardConversationBinding`), indexé par la
conversation Core de la liaison, avec exactement **un** foreground.

Cycle de vie d'une entrée (`BrainLifecycle`) :

- `foreground` : CLI vivant, reçoit les tours, ses relais sont dits ;
- `background_running` : CLI gardé vivant parce qu'il a du travail (sous-agents
  en cours, ou un tour pas encore rendu) ; aucun tour ne lui est routé, ses
  relais sont journalisés `spoken: false` ;
- `suspended` : `stop()`, identifiant de reprise gardé (`session_id` Claude,
  fil Codex) ; la reprise est `start(resume=True)`, donc `--resume <id>`.

Règles tenues ici :

- **Aucune transition n'annule du travail.** Rétrograder un agent occupé le
  garde vivant ; il se suspend seul `idle_suspend_s` (60 s) après la fin de son
  dernier sous-agent. Le plafond de CLI vivants (3) ne suspend que des agents
  **inactifs** ; au-delà, il le dit (`board_brain.cap_exceeded`, warning) et
  laisse tourner.
- **Codex** n'a pas de processus permanent (un processus par tour) : jamais
  `background_running`, et le pool n'appelle **jamais** son `restart()`, qui
  efface le fil.
- **Prêt veut dire prêt** (reprise QA 04a, A1) : une activation ne réussit
  qu'une fois le CLI réellement debout. Claude : `wait_ready()` (init reçu, ou
  processus encore vivant au bout de `ready_settle_s`) ; un CLI qui sort
  pendant la fenêtre fait échouer l'activation (`RuntimeError` -> 502
  `board_activation_failed`, rien de validé). Si ce démarrage reprenait un
  identifiant gardé (`--resume <id>` refusé : session effacée, expirée), un
  seul nouvel essai part avec un CLI **neuf**
  (`board_brain.resume_failed_fresh_start`, warning) ; le fil est perdu, le
  contexte du Board reste. Codex : `start()` résout le
  binaire et lui fait répondre `--version` ; c'est toute sa disponibilité
  avant un tour, puisqu'aucun processus ne vit entre deux tours.
- L'entrée foreground de départ n'est liée à rien (`key=None`) tant que Core ne
  l'a pas nommée : le Control Center l'**adopte** comme liaison foreground au
  démarrage (`GET /v1/sessions/current`) ou à la première activation.

Le pool ne parle pas à Core et ne connaît pas HTTP : le Control Center câble
chaque agent créé (`on_agent`), route les tours et rapporte à Core.
Horloge et minuterie injectables (`call_later`) pour les tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from jarvis.domain.workspace_board import (
    BindingStatus, BoardConversationBinding, BoardError, BoardErrorCode, BrainLifecycle,
)
from jarvis.runtime.claude_local import READY_SETTLE_S
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.prompt_runtime import accepts_keyword_argument

#: Délai de suspension d'un agent rétrogradé après la fin de son dernier sous-agent.
IDLE_SUSPEND_S = 60.0
#: CLI vivants au plus, foreground compris. Ne suspend jamais un agent qui travaille.
MAX_LIVE_CLIS = 3
#: CLI sans processus permanent : jamais `background_running`, jamais `restart()`.
PER_TURN_CLIS = frozenset({"codex"})

AgentFactory = Callable[[str], Any]
CallLater = Callable[[float, Callable[[], None]], Any]


@dataclass(eq=False)
class BoardBrain:
    """Une entrée du pool : la liaison, ses agents (un par CLI), son cycle de vie.

    `agents` peut tenir les deux CLI pour le foreground (bascule Claude <->
    Codex des réglages) ; `agent_cli` désigne celui qui reçoit les tours.
    """

    key: str | None
    binding: BoardConversationBinding | None
    agent_cli: str
    lifecycle: BrainLifecycle
    agents: dict[str, Any] = field(default_factory=dict)
    #: Identifiant de reprise gardé à la suspension (ou reçu de Core à l'activation).
    saved_session_id: str | None = None
    #: CLI qui a produit `saved_session_id` : un identifiant Claude ne reprend
    #: jamais un Codex (ni l'inverse) après un changement de CLI des réglages.
    saved_cli: str | None = None
    #: `(notice_epoch, last_notice_seq)` de l'agent à sa promotion : ce qui était
    #: déjà dans sa file n'est jamais rejoué comme un relais du foreground.
    notice_floor: tuple[str, int] | None = None
    #: La Session de la liaison est close : l'entrée ne redevient jamais foreground.
    closed: bool = False
    idle_handle: Any = None

    @property
    def agent(self) -> Any | None:
        return self.agents.get(self.agent_cli)

    @property
    def board_id(self) -> str | None:
        return self.binding.board_id if self.binding is not None else None

    def resume_id(self, cli: str) -> str | None:
        """L'identifiant de reprise gardé, seulement s'il vient de ce CLI."""

        return self.saved_session_id if self.saved_cli == cli else None

    def save_resume_id(self, cli: str, session_id: str | None) -> None:
        if session_id:
            self.saved_session_id, self.saved_cli = session_id, cli

    @property
    def jarvis_session_id(self) -> str | None:
        return self.binding.jarvis_session_id if self.binding is not None else None

    def to_payload(self) -> dict[str, Any]:
        agent = self.agent
        return {
            "conversation_id": self.key,
            "board_id": self.board_id,
            "jarvis_session_id": self.jarvis_session_id,
            "agent_cli": self.agent_cli,
            "agent_session_id": agent_session_id(agent) or self.resume_id(self.agent_cli),
            "lifecycle": self.lifecycle.value,
            "closed": self.closed,
        }


def agent_session_id(agent: Any) -> str | None:
    value = getattr(agent, "session_id", None) if agent is not None else None
    return value if isinstance(value, str) and value else None


def has_work(agent: Any) -> bool:
    """Un tour en vol ou un sous-agent (commande shell comprise) en cours."""

    tracker = getattr(agent, "subtasks", None)
    if tracker is None:
        return False
    if getattr(tracker, "busy", False):
        return True
    counts = tracker.counts()
    return bool(counts.get("active") or counts.get("running_shell"))


class BoardBrainPool:
    """Un agent par liaison, un seul foreground. Voir l'en-tête du module."""

    def __init__(
        self,
        *,
        factory: AgentFactory,
        selected_cli: Callable[[], str],
        journal: RuntimeJournal,
        on_agent: Callable[[BoardBrain, str, Any], None] | None = None,
        on_evict: Callable[[BoardBrain], None] | None = None,
        call_later: CallLater | None = None,
        idle_suspend_s: float = IDLE_SUSPEND_S,
        max_live: int = MAX_LIVE_CLIS,
        ready_settle_s: float = READY_SETTLE_S,
    ) -> None:
        if idle_suspend_s <= 0 or max_live < 1 or ready_settle_s < 0:
            raise ValueError("idle_suspend_s must be positive, max_live at least 1, ready_settle_s not negative")
        self._factory = factory
        self._selected_cli = selected_cli
        self.journal = journal
        self._on_agent = on_agent
        self._on_evict = on_evict
        self._call_later = call_later
        self.idle_suspend_s = idle_suspend_s
        self.max_live = max_live
        self.ready_settle_s = ready_settle_s
        foreground = BoardBrain(key=None, binding=None, agent_cli=selected_cli(), lifecycle=BrainLifecycle.FOREGROUND)
        self._foreground = foreground
        self._entries: dict[str | None, BoardBrain] = {None: foreground}
        self._tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------ lecture

    @property
    def foreground(self) -> BoardBrain:
        return self._foreground

    def entries(self) -> tuple[BoardBrain, ...]:
        return tuple(self._entries.values())

    def find(self, conversation_id: str | None) -> BoardBrain | None:
        """L'entrée de cette conversation Core, ou `None` (inconnue ou absente)."""

        if not conversation_id:
            return None
        return self._entries.get(conversation_id)

    def entry_of(self, agent: Any) -> BoardBrain | None:
        for entry in self._entries.values():
            if any(candidate is agent for candidate in entry.agents.values()):
                return entry
        return None

    def foreground_agent(self) -> Any:
        """L'agent du CLI choisi dans les réglages, pour le foreground ; construit au besoin."""

        entry = self._foreground
        entry.agent_cli = self._selected_cli()
        return self.agent_for(entry, entry.agent_cli)

    def agent_for(self, entry: BoardBrain, cli: str) -> Any:
        existing = entry.agents.get(cli)
        if existing is not None:
            return existing
        agent = self._factory(cli)
        entry.agents[cli] = agent
        self._attach(entry, cli, agent)
        return agent

    def live_count(self) -> int:
        return sum(1 for entry in self._entries.values() if self._live(entry))

    def snapshot(self) -> list[dict[str, Any]]:
        return [entry.to_payload() for entry in self._entries.values()]

    # ------------------------------------------------------------ transitions

    def adopt(self, binding: BoardConversationBinding) -> BoardBrain | None:
        """Nommer le foreground non lié d'après la liaison que Core dit foreground.

        Aucun processus n'est touché : l'agent qui tourne devient celui de la
        liaison (06 section H). Rend `None` si le foreground est déjà lié à une
        autre conversation (c'est alors une activation, pas une adoption).
        """

        entry = self._foreground
        if entry.key == binding.conversation_id:
            self._rebind(entry, binding)
            return entry
        if entry.key is not None:
            return None
        del self._entries[None]
        entry.key = binding.conversation_id
        self._entries[entry.key] = entry
        self._rebind(entry, binding)
        # Session reprise après un redémarrage (handoff session-context-recording,
        # Slice 03) : l'identifiant de reprise que Core garde sur la liaison est
        # retenu ; `relaunch` le reprend (`--resume`) tant que l'agent adopté n'a
        # encore servi aucun tour. Aucun processus n'est touché ici.
        entry.save_resume_id(binding.agent_cli, binding.agent_session_id)
        self._trace("board_brain.adopted", "Agent en cours adopté comme cerveau du Board", entry,
                    data={"resumable": entry.resume_id(entry.agent_cli) is not None})
        return entry

    def resume_pending(self, entry: BoardBrain) -> bool:
        """Vrai si l'agent de l'entrée n'a encore servi aucun tour alors qu'un fil gardé l'attend.

        Cas d'un démarrage du Control Center : son agent est lancé neuf avant
        que Core ne nomme la liaison reprise (et son `agent_session_id`).
        """

        agent = entry.agent
        return (entry.agent_cli not in PER_TURN_CLIS and agent is not None and agent_session_id(agent) is None
                and entry.resume_id(entry.agent_cli) is not None)

    async def relaunch(self, entry: BoardBrain, *, reason: str) -> bool:
        """Relancer le CLI d'une entrée pour qu'il relise ses arguments de lancement (reprise du fil gardé).

        Pour un CLI à processus permanent (Claude) seulement, et seulement s'il
        n'a pas de travail (un tour ou un sous-agent ne sont jamais coupés) :
        arrêt voulu, puis `_bring_up` — `--resume` de l'identifiant gardé ou du
        fil en cours, attente « prêt », un seul essai neuf si la reprise est
        refusée. Codex (un processus par tour) relit ses arguments à chaque
        tour : rien à faire. Rend vrai si le CLI a été relancé.
        """

        cli = entry.agent_cli
        agent = entry.agent
        if cli in PER_TURN_CLIS or agent is None:
            return False
        if has_work(agent):
            self._trace("board_brain.relaunch_deferred", "Relance du cerveau remise : il travaille", entry,
                        data={"reason": reason})
            return False
        await self._stop_agent(entry, cli, agent, reason=reason)
        await self._bring_up(entry, cli)
        self._trace("board_brain.relaunched", "Cerveau de Board relancé", entry,
                    data={"reason": reason, "agent_session_id": agent_session_id(agent)})
        return True

    async def activate(self, binding: BoardConversationBinding) -> BoardBrain:
        """Rendre foreground l'agent de `binding` : garder, reprendre ou démarrer son CLI.

        L'agent cible est prêt **avant** que le précédent soit rétrogradé : un
        échec de démarrage lève sans rien changer (Core abandonne la bascule).
        Le précédent est rétrogradé, jamais tué : suspendu s'il est inactif,
        `background_running` s'il travaille.
        """

        if binding.status is BindingStatus.CLOSED:
            raise BoardError(BoardErrorCode.SESSION_CLOSED,
                             f"binding {binding.key} is closed and cannot become foreground")
        cli = self._selected_cli()
        previous = self._foreground
        target = self._entries.get(binding.conversation_id)
        adopted = False
        if target is None and previous.key is None:
            target = self.adopt(binding)
            adopted = target is not None
        created = target is None
        if target is None:
            target = BoardBrain(key=binding.conversation_id, binding=binding, agent_cli=cli,
                                lifecycle=BrainLifecycle.SUSPENDED)
            target.save_resume_id(binding.agent_cli, binding.agent_session_id)
            self._entries[target.key] = target
        else:
            self._rebind(target, binding)
        if target.closed:
            raise BoardError(BoardErrorCode.SESSION_CLOSED,
                             f"binding {binding.key} belongs to a closed session")
        try:
            await self._bring_up(target, cli)
        except BaseException:
            if created:
                self._evict(target)
            elif adopted:
                # Rien ne change sur un échec, adoption comprise (reprise QA 04a).
                self._unadopt(target)
            raise
        if target is not previous:
            self._promote(target)
            await self.demote(previous)
        # Une seule Session est ouverte à la fois : activer la liaison d'une
        # Session veut dire que toutes les autres sont closes (nouvelle Session
        # voulue par Core, Core redémarré) — l'ancien foreground **et** les
        # entrées de fond de cette Session-là (reprise QA 04a, A2).
        self._close_other_sessions(binding.jarvis_session_id)
        await self.enforce_cap()
        self._trace("board_brain.activated", "Cerveau de Board au premier plan", target,
                    data={"created": created, "previous_conversation_id": previous.key})
        return target

    async def start_fresh(self, binding: BoardConversationBinding, *, previous_closed: bool = True) -> BoardBrain:
        """Nouvelle Session : un CLI **neuf** pour `binding`, l'ancien foreground rétrogradé.

        `previous_closed` : la Session de l'ancien foreground vient d'être
        close ; son entrée est oubliée dès qu'elle est suspendue.
        """

        previous = self._foreground
        if previous.key == binding.conversation_id:
            raise BoardError(BoardErrorCode.BINDING_CONFLICT,
                             f"conversation {binding.conversation_id} is already the foreground binding")
        cli = self._selected_cli()
        target = BoardBrain(key=binding.conversation_id, binding=binding, agent_cli=cli,
                            lifecycle=BrainLifecycle.SUSPENDED)
        self._entries[target.key] = target
        try:
            await self._bring_up(target, cli)
        except BaseException:
            self._evict(target)
            raise
        previous.closed = previous.closed or previous_closed
        self._promote(target)
        await self.demote(previous)
        if previous_closed:
            self._close_other_sessions(binding.jarvis_session_id)
        await self.enforce_cap()
        self._trace("board_brain.activated", "Nouvelle Session : cerveau neuf au premier plan", target,
                    data={"created": True, "previous_conversation_id": previous.key})
        return target

    async def demote(self, entry: BoardBrain) -> None:
        """Retirer l'autorité de parole : suspendre si inactif, garder vivant s'il travaille."""

        if entry is self._foreground:
            raise BoardError(BoardErrorCode.BINDING_CONFLICT, "the foreground brain is demoted only by a promotion")
        for agent in entry.agents.values():
            _set_speaks(agent, False)
        working = [cli for cli, agent in entry.agents.items()
                   if cli not in PER_TURN_CLIS and self._agent_live(cli, agent) and has_work(agent)]
        if working:
            entry.lifecycle = BrainLifecycle.BACKGROUND_RUNNING
            self._trace("board_brain.demoted", "Cerveau rétrogradé : gardé vivant pour son travail en cours", entry,
                        data={"to": "background_running"})
            self.on_activity(entry)
            return
        await self._suspend(entry, reason="demoted")

    def on_activity(self, entry: BoardBrain) -> None:
        """Abonné au suivi des sous-tâches : arme ou désarme la suspension d'un agent de fond.

        Appelé sur le chemin de lecture du flux du CLI : ne bloque jamais.
        """

        if entry.lifecycle is not BrainLifecycle.BACKGROUND_RUNNING or entry is self._foreground:
            self._cancel_idle(entry)
            return
        if any(has_work(agent) for cli, agent in entry.agents.items() if cli not in PER_TURN_CLIS):
            self._cancel_idle(entry)
            return
        if entry.idle_handle is None:
            call_later = self._call_later or asyncio.get_running_loop().call_later
            entry.idle_handle = call_later(self.idle_suspend_s, lambda: self._idle_expired(entry))

    async def enforce_cap(self) -> None:
        """Au-delà de `max_live` CLI vivants, suspendre les plus anciens **inactifs**, jamais un occupé."""

        live = [entry for entry in self._entries.values() if self._live(entry)]
        if len(live) <= self.max_live:
            return
        idle = [entry for entry in live if entry is not self._foreground and not self._busy(entry)]
        idle.sort(key=lambda entry: entry.binding.last_active_at if entry.binding is not None
                  else datetime.min.replace(tzinfo=timezone.utc))
        excess = len(live) - self.max_live
        for entry in idle[:excess]:
            await self._suspend(entry, reason="cap")
        remaining = self.live_count()
        if remaining > self.max_live:
            self.journal.emit(
                "board_brain.cap_exceeded",
                f"{remaining} CLI d'agent vivants pour un plafond de {self.max_live} : "
                "les autres travaillent, aucun n'est arrêté",
                level="warning",
                data={"code": "board_brain_cap_exceeded", "live": remaining, "max_live": self.max_live},
            )

    async def aclose(self) -> None:
        """Arrêt du Control Center : tout arrêter, sans jamais rester bloqué."""

        for task in tuple(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for entry in tuple(self._entries.values()):
            self._cancel_idle(entry)
            for cli, agent in tuple(entry.agents.items()):
                try:
                    await _stop(agent, "shutdown")
                except Exception as exc:  # noqa: BLE001 - l'arrêt du serveur ne doit jamais rester bloqué
                    self._stop_failed(entry, cli, exc, reason="shutdown")

    # ------------------------------------------------------------ interne

    def _attach(self, entry: BoardBrain, cli: str, agent: Any) -> None:
        self._bind_journal(entry, agent)
        _set_speaks(agent, entry is self._foreground)
        tracker = getattr(agent, "subtasks", None)
        if tracker is not None and callable(getattr(tracker, "subscribe", None)):
            tracker.subscribe(lambda: self.on_activity(entry))
        if self._on_agent is not None:
            self._on_agent(entry, cli, agent)

    def _close_other_sessions(self, jarvis_session_id: str) -> None:
        """Marquer closes les entrées liées à une autre Session ; oublier celles déjà suspendues.

        Même règle d'éviction que `_suspend` : une entrée close et suspendue
        n'a plus de raison d'être ; une entrée close qui travaille reste
        (`background_running`, `closed: true`) jusqu'à sa suspension, puis part.
        """

        for entry in tuple(self._entries.values()):
            if entry is self._foreground or entry.binding is None or entry.jarvis_session_id == jarvis_session_id:
                continue
            entry.closed = True
            if entry.lifecycle is BrainLifecycle.SUSPENDED and not self._live(entry):
                self._evict(entry)

    def _unadopt(self, entry: BoardBrain) -> None:
        """Défaire une adoption faite par une activation qui a échoué : le foreground redevient non lié."""

        if entry is not self._foreground or self._entries.get(entry.key) is not entry:
            return
        del self._entries[entry.key]
        entry.key, entry.binding, entry.closed = None, None, False
        self._entries[None] = entry
        for agent in entry.agents.values():
            self._bind_journal(entry, agent)

    def _rebind(self, entry: BoardBrain, binding: BoardConversationBinding) -> None:
        # Core est la vérité : une liaison qu'il dit ouverte l'est (retour
        # arrière d'une nouvelle Session annulée, Slice 04b), une close l'est.
        entry.binding = binding
        entry.closed = binding.status is BindingStatus.CLOSED
        for agent in entry.agents.values():
            self._bind_journal(entry, agent)

    @staticmethod
    def _bind_journal(entry: BoardBrain, agent: Any) -> None:
        journal = getattr(agent, "journal", None)
        if callable(getattr(journal, "bind", None)):
            journal.bind(board_id=entry.board_id, jarvis_session_id=entry.jarvis_session_id)

    async def _bring_up(self, entry: BoardBrain, cli: str) -> None:
        """Démarrer ou reprendre le CLI `cli` de l'entrée ; arrêter l'autre CLI s'il est inactif."""

        entry.agent_cli = cli
        agent = self.agent_for(entry, cli)
        for other_cli, other in tuple(entry.agents.items()):
            if other_cli != cli and self._agent_live(other_cli, other) and not has_work(other):
                await self._stop_agent(entry, other_cli, other, reason="cli_switch")
        resumed = False
        saved = entry.resume_id(cli)
        if saved and not agent_session_id(agent):
            if self._agent_live(cli, agent) and not has_work(agent):
                # Agent lancé neuf (démarrage du Control Center) puis adopté pour
                # une liaison reprise : il n'a servi aucun tour, son fil est vide.
                # Relancé avec `--resume <id gardé>` pour retrouver celui de la
                # Session (handoff session-context-recording, Slice 03).
                await self._stop_agent(entry, cli, agent, reason="resume_adopted")
            agent.session_id = saved
        if cli in PER_TURN_CLIS or getattr(agent, "state", None) != "running":
            resume_id = agent_session_id(agent)
            resumed = resume_id is not None
            await agent.start(resume=True)
            try:
                await self._wait_ready(entry, cli, agent)
            except RuntimeError as refused:
                if not resumed or cli in PER_TURN_CLIS:
                    raise
                await self._start_fresh_after_resume_failure(entry, cli, agent, resume_id, refused)
                resumed = False
            self._trace("board_brain.resumed" if resumed else "board_brain.started",
                        "Cerveau de Board repris" if resumed else "Cerveau de Board démarré", entry)
        entry.save_resume_id(cli, agent_session_id(agent))

    async def _start_fresh_after_resume_failure(self, entry: BoardBrain, cli: str, agent: Any,
                                                old_id: str | None, refused: RuntimeError) -> None:
        """`--resume <id>` refusé au démarrage (session Claude effacée, expirée) : un essai, CLI neuf.

        Sans cela le Board resterait impossible à activer pour toujours. Le fil
        de conversation est perdu ; le contexte du Board (bloc `board` de chaque
        tour) réhydrate le CLI neuf. Son nouvel identifiant remonte à Core par
        la réponse d'activation (s'il est déjà connu) ou par le rapport de
        liaison du premier tour ; l'ancien n'est plus rapporté.
        Si le démarrage neuf échoue aussi, l'entrée retrouve son identifiant et
        l'échec neuf est levé (502, rien de validé).
        """

        saved = (entry.saved_session_id, entry.saved_cli)
        self.journal.emit(
            "board_brain.resume_failed_fresh_start",
            f"Reprise du cerveau de Board refusée ({refused}) : démarrage d'un CLI neuf, fil de conversation perdu",
            level="warning",
            data={"code": "board_brain_resume_failed", "conversation_id": entry.key, "board_id": entry.board_id,
                  "jarvis_session_id": entry.jarvis_session_id, "agent_cli": cli,
                  "old_agent_session_id": old_id, "exit_detail": str(refused)[:400]},
        )
        agent.session_id = None
        entry.saved_session_id = entry.saved_cli = None
        try:
            await agent.start(resume=False)
            await self._wait_ready(entry, cli, agent)
        except RuntimeError as fresh_failed:
            agent.session_id = old_id
            entry.saved_session_id, entry.saved_cli = saved
            raise fresh_failed from refused

    async def _wait_ready(self, entry: BoardBrain, cli: str, agent: Any) -> None:
        """Le CLI démarré est-il vraiment debout ? Sinon : l'arrêter proprement et lever `RuntimeError`.

        Un agent sans `wait_ready` (Codex : `start()` a déjà vérifié le
        binaire ; doublures) est prêt quand `start()` a rendu.
        """

        wait_ready = getattr(agent, "wait_ready", None)
        if not callable(wait_ready):
            return
        try:
            await wait_ready(settle_s=self.ready_settle_s)
        except RuntimeError:
            # Le processus est déjà sorti : on récupère ses tâches de lecture.
            # L'échec lui-même est dit une fois, par l'appelant (activation refusée).
            await self._stop_agent(entry, cli, agent, reason="start_failed")
            raise

    def _promote(self, entry: BoardBrain) -> None:
        self._cancel_idle(entry)
        self._foreground = entry
        entry.lifecycle = BrainLifecycle.FOREGROUND
        agent = entry.agent
        for candidate in entry.agents.values():
            _set_speaks(candidate, True)
        epoch = getattr(agent, "notice_epoch", None)
        if epoch is not None:
            entry.notice_floor = (str(epoch), int(getattr(agent, "last_notice_seq", 0) or 0))

    async def _suspend(self, entry: BoardBrain, *, reason: str) -> None:
        if entry is self._foreground:
            return
        self._cancel_idle(entry)
        busy = [cli for cli, agent in entry.agents.items()
                if cli not in PER_TURN_CLIS and self._agent_live(cli, agent) and has_work(agent)]
        if busy:
            # Du travail est reparti entre l'échéance et maintenant : on garde.
            entry.lifecycle = BrainLifecycle.BACKGROUND_RUNNING
            self.on_activity(entry)
            return
        for cli, agent in tuple(entry.agents.items()):
            if cli in PER_TURN_CLIS and has_work(agent):
                continue  # un tour Codex se termine avec son processus : ne pas le couper
            if cli in PER_TURN_CLIS or self._agent_live(cli, agent):
                await self._stop_agent(entry, cli, agent, reason=reason)
        entry.save_resume_id(entry.agent_cli, agent_session_id(entry.agent))
        entry.lifecycle = BrainLifecycle.SUSPENDED
        self._trace("board_brain.suspended", "Cerveau de Board suspendu", entry,
                    data={"reason": reason, "resumable": entry.saved_session_id is not None})
        if entry.closed:
            self._evict(entry)

    async def _stop_agent(self, entry: BoardBrain, cli: str, agent: Any, *, reason: str) -> None:
        try:
            await _stop(agent, reason)
        except Exception as exc:  # noqa: BLE001 - capture: une suspension ratée ne casse pas la bascule
            self._stop_failed(entry, cli, exc, reason=reason)

    def _stop_failed(self, entry: BoardBrain, cli: str, exc: Exception, *, reason: str) -> None:
        self.journal.emit(
            "board_brain.stop_failed",
            f"Arrêt du CLI {cli} imparfait ({reason}) : {type(exc).__name__}: {str(exc)[:200]}",
            level="warning",
            data={"code": "board_brain_stop_failed", "agent_cli": cli, "reason": reason,
                  "conversation_id": entry.key, "board_id": entry.board_id,
                  "exception_type": type(exc).__name__},
        )

    def _idle_expired(self, entry: BoardBrain) -> None:
        entry.idle_handle = None
        if entry.lifecycle is not BrainLifecycle.BACKGROUND_RUNNING or entry is self._foreground:
            return
        task = asyncio.get_running_loop().create_task(self._suspend(entry, reason="idle"),
                                                      name="jarvis-board-brain-idle-suspend")
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self.journal.emit(
                "board_brain.suspend_failed",
                f"Suspension automatique en échec : {type(exc).__name__}: {str(exc)[:200]}",
                level="error", data={"code": "board_brain_suspend_failed", "exception_type": type(exc).__name__},
            )

    async def drain(self) -> None:
        """Attendre les suspensions automatiques en cours (tests, arrêt)."""

        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    @staticmethod
    def _cancel_idle(entry: BoardBrain) -> None:
        handle, entry.idle_handle = entry.idle_handle, None
        if handle is not None:
            handle.cancel()

    def _evict(self, entry: BoardBrain) -> None:
        if entry is self._foreground or self._entries.get(entry.key) is not entry:
            return
        self._cancel_idle(entry)
        del self._entries[entry.key]
        if self._on_evict is not None:
            self._on_evict(entry)

    @staticmethod
    def _agent_live(cli: str, agent: Any) -> bool:
        return cli not in PER_TURN_CLIS and getattr(agent, "state", None) == "running"

    def _live(self, entry: BoardBrain) -> bool:
        return any(self._agent_live(cli, agent) for cli, agent in entry.agents.items())

    def _busy(self, entry: BoardBrain) -> bool:
        return any(has_work(agent) for cli, agent in entry.agents.items() if self._agent_live(cli, agent))

    def _trace(self, kind: str, message: str, entry: BoardBrain, *, data: dict[str, Any] | None = None) -> None:
        self.journal.emit(kind, message, data={
            "conversation_id": entry.key, "board_id": entry.board_id, "jarvis_session_id": entry.jarvis_session_id,
            "agent_cli": entry.agent_cli, "lifecycle": entry.lifecycle.value, "live_clis": self.live_count(),
            **(data or {}),
        })


async def _stop(agent: Any, reason: str) -> Any:
    """Arrêt voulu par le pool : la raison suit jusqu'au journal de l'agent (`agent.exit` en info, QA 04b S3).

    Un agent sans l'option (Codex, doublures) est arrêté comme avant.
    """

    if accepts_keyword_argument(agent.stop, "reason"):
        return await agent.stop(reason=reason)
    return await agent.stop()


def _set_speaks(agent: Any, speaks: bool) -> None:
    if hasattr(agent, "speaks_notices"):
        agent.speaks_notices = speaks
