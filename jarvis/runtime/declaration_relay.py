"""Relais des déclarations de sous-agents vers Core : registre local → tâche suivie → `POST /v1/missions/declarations`.

Handoff jarvis-organic-agent-orchestration, Slice 05. Le hook `PreToolUse`
dépose un fait par appel `Agent` (`agent_declarations`) ; ce relais, dans le
processus du Control Center :

    agent-declarations/*.json ──scan (thread)──► faits par tool_use_id
    AgentTaskTracker ──tâche démarrée (task_id connu)──► jointure ──► file ──lots ≤ 32──► Core

- **jointure** : sur le `tool_use_id` de la tâche suivie (le `work_key` n'est
  pas forcément ce `tool_use_id` : quand `task_started` précède l'appel, la clé
  stable est le `task_id`, `agent_tasks._merge`). La déclaration n'est envoyée
  qu'une fois la tâche démarrée : sa clé est alors définitive, et un appel
  refusé (jamais démarré) ne laisse aucune instance ;
- **parent** : la clé de travail du parent dans le tracker (`parent_of`), comme
  les observations ; Core en déduit l'instance parente et la mission ;
- **rôle sur Work State** : `role_for(task)` donne au `TrackerWorkObserver`
  le rôle du fait joint, qu'il pose sur l'observation (`WorkObservation.role_id`,
  premier affirmé gagnant). `on_joined` lui fait renvoyer les tâches jointes ;
- **rejeu** : Core redémarré (`store_id` différent) → les déclarations des
  tâches encore suivies repartent (Core répond `duplicate` pour les durables et
  reconstitue les éphémères en attente). Control Center redémarré → le registre
  local est relu (les faits y restent jusqu'à `RETENTION_S`) ;
- Core injoignable : la file attend (bornée, la plus ancienne sort, comptée) ;
  lot refusé (400) : abandonné et consigné une fois par série.

Contrat : `docs/agent-orchestration.md` § Relais.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from jarvis.domain.mission_history import AgentDeclarationFact
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime import agent_declarations
from jarvis.runtime.agent_tasks import AgentTask, AgentTaskTracker
from jarvis.runtime.core_forwarder import CoreBatchForwarder, CoreBatchRejected, CoreLoopbackTransport
from jarvis.runtime.journal import RuntimeJournal

MAX_BATCH = 32
#: Faits et jointures retenus en mémoire ; au-delà, les plus anciens sortent (le registre local les garde).
MAX_FACTS = 1_024
MAX_PENDING = 256
#: Élagage du registre local, au plus une fois par intervalle.
PRUNE_INTERVAL_S = 60.0
#: Sonde de l'instance de Core (`GET /v1/missions/health`, `store_id`) quand rien n'est à envoyer et que des
#: tâches jointes sont encore suivies : un Core redémarré pendant un long sous-agent est reconnu sans attendre.
PROBE_INTERVAL_S = 30.0


class DeclarationsRejected(CoreBatchRejected):
    """Core a refusé un lot de déclarations (400) : le rejouer à l'identique ne servirait à rien."""


class CoreMissionTransport(CoreLoopbackTransport):
    """Accès aux routes `/v1/missions*` de Core par la boucle locale, jeton relu après un 401."""

    async def post(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            return await self.replay_on_401(lambda client: client.append_mission_declarations(items))
        except CoreProtocolError as exc:
            if exc.status == 400:
                raise DeclarationsRejected(str(exc)) from exc
            raise

    async def health(self) -> dict[str, Any]:
        return await self.replay_on_401(lambda client: client.mission_health())

    async def mission(self, mission_id: str) -> dict[str, Any]:
        return await self.replay_on_401(lambda client: client.mission_view(mission_id))

    async def for_work(self, work_source: str, work_external_id: str) -> dict[str, Any]:
        return await self.replay_on_401(lambda client: client.mission_for_work(work_source, work_external_id))


class DeclarationRelay(CoreBatchForwarder):
    """Voir le docstring du module."""

    TASK_NAME = "jarvis-declaration-relay"
    UNAVAILABLE_KIND = "missions.relay_unavailable"
    UNAVAILABLE_MESSAGE = "Core injoignable : les déclarations de sous-agents attendent, les agents continuent."
    RESTORED_KIND = "missions.relay_restored"
    RESTORED_MESSAGE = "Core joint : les déclarations de sous-agents lui parviennent de nouveau."
    REJECTED_KIND = "missions.relay_rejected"
    REJECTED_MESSAGE = "Core a refusé un lot de déclarations de sous-agents : lot abandonné."
    INVALID_KIND = "missions.declaration_invalid"
    SCAN_FAILED_KIND = "missions.ledger_unreadable"
    SENT_KIND = "missions.declarations_sent"

    def __init__(
        self,
        *,
        runtime_root: Any,
        source: str,
        transport: Any,
        journal: RuntimeJournal | None = None,
        poll_interval_s: float = 1.0,
        retry_min_s: float = 1.0,
        retry_max_s: float = 30.0,
        close_timeout_s: float = 2.0,
    ) -> None:
        super().__init__(
            transport=transport, journal=journal, flush_interval_s=poll_interval_s, retry_min_s=retry_min_s,
            retry_max_s=retry_max_s, close_timeout_s=close_timeout_s, idle_interval_s=None,
        )
        self.runtime_root = runtime_root
        self.source = source
        #: Appelé quand une tâche vient d'être jointe à sa déclaration : le Control Center y renvoie les
        #: observations (le rôle part alors sur Work State).
        self.on_joined: Callable[[], Any] | None = None
        self.dropped_total = 0
        self.rejected_total = 0
        self.sent_total = 0
        self._trackers: dict[int, AgentTaskTracker] = {}
        self._facts: OrderedDict[str, AgentDeclarationFact] = OrderedDict()
        self._seen: set[str] = set()
        self._invalid_reported: set[str] = set()
        self._joined: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._pending: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._store_id: str | None = None
        self._last_prune = 0.0
        self._last_probe = 0.0
        self._scan_failed = False

    # ------------------------------------------------------------ branchement

    def attach(self, tracker: AgentTaskTracker) -> None:
        self._trackers[id(tracker)] = tracker

    def detach(self, tracker: AgentTaskTracker) -> None:
        self._trackers.pop(id(tracker), None)

    def role_for(self, task: AgentTask) -> str | None:
        """Le rôle canonique déclaré pour cette tâche (fait joint par `tool_use_id`), ou `None`. Sans E/S."""

        fact = self._facts.get(task.tool_use_id or "")
        return fact.role_id if fact is not None else None

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def _send_due(self) -> bool:
        # Le relais sonde le registre à chaque intervalle : il y a toujours quelque chose à regarder.
        return True

    # ------------------------------------------------------------ registre

    async def _scan(self) -> None:
        """Relire le registre local (dans un thread : E/S de disque hors de la boucle) et retenir les faits neufs."""

        loop = asyncio.get_running_loop()
        try:
            if loop.time() - self._last_prune >= PRUNE_INTERVAL_S:
                self._last_prune = loop.time()
                await asyncio.to_thread(agent_declarations.prune, self.runtime_root)
            result = await asyncio.to_thread(agent_declarations.scan, self.runtime_root, seen=set(self._seen))
        except OSError as exc:
            if not self._scan_failed:
                self._scan_failed = True
                self._report(self.SCAN_FAILED_KIND, "Registre des déclarations illisible : aucune déclaration ne "
                             "part vers Core.", "error", exc)
            return
        self._scan_failed = False
        for item in result.facts:
            self._seen.add(item.name)
            self._facts[item.fact.tool_use_id] = item.fact
            self._facts.move_to_end(item.fact.tool_use_id)
        while len(self._facts) > MAX_FACTS:
            self._facts.popitem(last=False)
        for name, reason in result.invalid:
            self._seen.add(name)
            if name not in self._invalid_reported and len(self._invalid_reported) < MAX_FACTS:
                self._invalid_reported.add(name)
                self._report(self.INVALID_KIND, "Déclaration de sous-agent illisible ou hors contrat : ignorée.",
                             "warning", extra={"file": name, "reason": reason})
        if len(self._seen) > 4 * MAX_FACTS:
            # Oublier les noms déjà élagués du registre : relister suffit (un nom présent reste vu).
            try:
                present = set(await asyncio.to_thread(lambda: {p.name for p in
                                                               agent_declarations.ledger_dir(self.runtime_root).iterdir()}))
            except OSError:
                present = self._seen  # intentional: keep the memory as is; the next scan retries the listing
            self._seen &= present

    def join(self) -> int:
        """Joindre les faits connus aux tâches démarrées ; rend le nombre de jointures neuves. Sans E/S."""

        joined = 0
        for tracker in tuple(self._trackers.values()):
            for task in tracker.tasks():
                tool_use_id = task.tool_use_id
                if not tool_use_id or tool_use_id in self._joined or not task.task_id or not task.work_key:
                    continue
                fact = self._facts.get(tool_use_id)
                if fact is None:
                    continue
                parent = tracker.parent_of(task)
                parent_key = parent.work_key if parent is not None and parent.work_key not in ("", task.work_key) \
                    else None
                item = {"fact": fact.to_payload(), "work_source": self.source, "work_external_id": task.work_key,
                        "parent_work_external_id": parent_key}
                self._joined[tool_use_id] = item
                self._queue(tool_use_id, item)
                joined += 1
        while len(self._joined) > MAX_FACTS:
            self._joined.popitem(last=False)
        if joined and self.on_joined is not None:
            try:
                self.on_joined()
            except Exception as exc:  # noqa: BLE001 - reported; the declarations still go to Core
                self._report("missions.relay_observer_failed", "Renvoi des observations après jointure en échec.",
                             "error", exc)
        return joined

    def _queue(self, tool_use_id: str, item: dict[str, Any]) -> None:
        self._pending[tool_use_id] = item
        while len(self._pending) > MAX_PENDING:
            self._pending.popitem(last=False)
            self.dropped_total += 1

    def _replay_live(self) -> int:
        """Core a changé d'instance : renvoyer les déclarations des tâches encore suivies."""

        live = {task.tool_use_id for tracker in self._trackers.values() for task in tracker.tasks() if task.tool_use_id}
        replayed = 0
        for tool_use_id, item in self._joined.items():
            if tool_use_id in live and tool_use_id not in self._pending:
                self._queue(tool_use_id, item)
                replayed += 1
        return replayed

    # ------------------------------------------------------------ envoi

    async def flush(self) -> bool:
        await self._scan()
        self.join()
        if not self._pending and not await self._probe():
            return False
        while self._pending:
            keys = list(self._pending)[:MAX_BATCH]
            batch = [self._pending[key] for key in keys]
            try:
                response = await self.transport.post(batch)
            except asyncio.CancelledError:
                raise
            except CoreBatchRejected as exc:
                for key in keys:
                    self._pending.pop(key, None)
                self.rejected_total += len(keys)
                self._report_rejected(exc)
                continue
            except Exception as exc:  # noqa: BLE001 - Core arrêté, jeton absent, réseau : la file attend
                self._report_unavailable(exc)
                return False
            for key in keys:
                self._pending.pop(key, None)
            self.sent_total += len(keys)
            self._note_accepted()
            self._acknowledge(response, len(keys))
        return True

    async def _probe(self) -> bool:
        """Sonder l'instance de Core (au plus une fois par `PROBE_INTERVAL_S`, seulement avec des tâches jointes
        encore suivies) ; un `store_id` neuf réarme le renvoi. Faux si Core est injoignable."""

        loop = asyncio.get_running_loop()
        if self._store_id is None or not self._joined or loop.time() - self._last_probe < PROBE_INTERVAL_S:
            return True
        self._last_probe = loop.time()
        try:
            health = await self.transport.health()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Core arrêté, jeton absent, réseau : on réessaie plus tard
            self._report_unavailable(exc)
            return False
        self._note_accepted()
        self._note_store(health.get("store_id") if isinstance(health, dict) else None)
        return True

    def _note_store(self, store_id: Any) -> None:
        if not isinstance(store_id, str) or not store_id:
            return
        if self._store_id is not None and store_id != self._store_id:
            self._store_id = store_id
            replayed = self._replay_live()
            if replayed:
                self._report("missions.relay_replayed", "Core a redémarré : déclarations des tâches suivies renvoyées.",
                             "info", extra={"replayed": replayed, "store_id": store_id})
            return
        self._store_id = store_id

    def _acknowledge(self, response: Any, count: int) -> None:
        results = response.get("results") if isinstance(response, dict) else None
        outcomes: dict[str, int] = {}
        for result in results if isinstance(results, list) else ():
            outcome = str(result.get("outcome") if isinstance(result, dict) else "unknown")
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        self._report(self.SENT_KIND, "Déclarations de sous-agents remises à Core.", "info",
                     extra={"count": count, "outcomes": outcomes})
        self._note_store(response.get("store_id") if isinstance(response, dict) else None)

    def _report_data(self) -> dict[str, Any]:
        return {"source": self.source, "pending": len(self._pending), "dropped_total": self.dropped_total,
                "rejected_total": self.rejected_total}
