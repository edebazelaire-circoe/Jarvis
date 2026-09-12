"""Suivi des sous-tâches de l'agent piloté (sous-agents, commandes de fond).

Le brain — l'agent CLI que pilote le Control Center — délègue : Claude Code
lance des sous-agents avec son outil `Agent` (anciennement `Task`) et des
commandes longues en tâches de fond (`local_bash`). Aucune de ces tâches n'a
d'existence propre côté Jarvis : il faut les reconstituer à partir du flux
d'événements, où elles se croisent dans le désordre.

`AgentTaskTracker` tient cet état — qui tourne, depuis quand, avec quel
modèle, ce qu'il fait en ce moment, sa trace — indépendamment du fournisseur.
Seul `observe_claude` connaît un format : le `stream-json` de Claude Code, le
seul flux où l'on sait aujourd'hui lire des sous-tâches. Un autre CLI
n'alimente que l'état du brain (`turn_started`, `process_stopped`...), et
branchera son propre `observe_*` le jour où son format sera vérifié.

Tout s'exécute dans la boucle asyncio : pas de verrou, et aucune I/O hormis le
journal, qui écrit déjà chaque événement brut.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import math
import re
import time
from typing import Any, Callable

from jarvis.runtime.journal import RuntimeJournal


#: Entrées gardées par tâche : un sous-agent bavard produit ~2 entrées par outil.
MAX_TRACE_ENTRIES = 400
#: Tâches terminées gardées pour consultation ; les plus anciennes sortent.
MAX_FINISHED_TASKS = 30
#: Au-delà, une chaîne du JSON brut conservé est tronquée. Un `tool_result` de
#: 200 Ko (un fichier lu en entier) ne doit pas être gardé tel quel N fois.
MAX_RAW_STRING = 2_000
MAX_RAW_ITEMS = 100
#: Budget d'une entrée sérialisée : au-delà, elle est recompactée plus sévèrement.
MAX_ENTRY_CHARS = 12_000
MAX_TEXT = 4_000
MAX_PROMPT = 4_000
MAX_SUMMARY = 1_000
MAX_LABEL = 160
#: Clés de travail retirées par une fusion, en attente d'être closes côté Core.
MAX_RETIRED_WORK_KEYS = 64

AGENT_TOOLS = frozenset({"Agent", "Task"})
SYNTHETIC_MODEL = "<synthetic>"
#: Statuts qui ne terminent pas une tâche. Tout le reste la termine, et une
#: valeur inconnue est conservée telle quelle plutôt que traduite.
NON_TERMINAL = frozenset({"", "running", "pending", "queued", "started"})
#: Fins anormales : le journal les signale en avertissement.
WARNING_STATUSES = frozenset({"failed", "killed", "interrupted"})
TASK_SUBTYPES = frozenset({"task_started", "task_progress", "task_notification", "task_updated"})

_HINT_KEYS = ("description", "command", "file_path", "notebook_path", "pattern", "query", "url", "path", "skill", "prompt")
_PATH_KEYS = frozenset({"file_path", "notebook_path"})

Formatter = Callable[[dict[str, Any]], dict[str, Any]]


# ----------------------------------------------------------------- utilitaires


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (+{len(text) - limit} caractères)"


def compact(value: Any, *, limit: int = MAX_RAW_STRING, items: int = MAX_RAW_ITEMS, depth: int = 0) -> Any:
    """Copie bornée d'un événement : chaînes tronquées, listes raccourcies."""
    if isinstance(value, str):
        return truncate(value, limit)
    if depth >= 10:
        return "…"
    if isinstance(value, dict):
        return {str(key): compact(item, limit=limit, items=items, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        kept = [compact(item, limit=limit, items=items, depth=depth + 1) for item in value[:items]]
        if len(value) > items:
            kept.append(f"… (+{len(value) - items} éléments)")
        return kept
    return value


def compact_event(event: dict[str, Any]) -> dict[str, Any]:
    reduced = compact(event)
    try:
        size = len(json.dumps(reduced, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        size = MAX_ENTRY_CHARS + 1
    if size > MAX_ENTRY_CHARS:
        # Beaucoup de chaînes moyennes peuvent encore peser lourd ensemble.
        reduced = compact(event, limit=300, items=20)
    return reduced


def format_duration(ms: int | float | None) -> str:
    """« 45 s », « 3 min 12 s », « 1 h 05 min »."""
    seconds = max(0, int(round((ms or 0) / 1000)))
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


def describe_tool(name: str, payload: Any) -> str:
    """Libellé court d'un appel d'outil : « Agent · Persist voice arch setting »."""
    hint = ""
    if isinstance(payload, dict):
        for key in _HINT_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                hint = value.strip().splitlines()[0]
                if key in _PATH_KEYS:
                    hint = re.split(r"[\\/]", hint)[-1] or hint
                break
    hint = truncate(hint, 120)
    return f"{name} · {hint}" if hint else name


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    # `json.loads` accepte `NaN` et `Infinity` : `int()` lèverait dessus.
    if isinstance(value, float) and math.isfinite(value):
        return int(value)
    return None


def _kind_for(task_type: str) -> str | None:
    if task_type == "local_bash" or "bash" in task_type or "shell" in task_type:
        return "shell"
    if task_type == "local_agent" or "agent" in task_type:
        return "agent"
    return None


def _default_formatter(event: dict[str, Any]) -> dict[str, Any]:
    kind = str(event.get("type") or "event")
    return {"role": kind, "title": kind, "text": "", "status": "ok", "raw": event}


def _result_text(block: dict[str, Any]) -> str:
    payload = block.get("content")
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        parts = [str(item.get("text") or "") for item in payload if isinstance(item, dict) and item.get("type") == "text"]
        return "\n".join(part for part in parts if part)
    return ""


# ---------------------------------------------------------------------- tâche


@dataclass(slots=True)
class AgentTask:
    """Une sous-tâche. Son identifiant public est le `task_id` dès qu'il est connu."""

    task_id: str | None = None
    tool_use_id: str | None = None
    kind: str = "other"
    subagent_type: str = ""
    description: str = ""
    status: str = "running"
    background: bool = False
    depth: int = 1
    parent_tool_use_id: str | None = None
    started_ms: int = 0
    ended_ms: int | None = None
    activity: str = ""
    last_tool: str = ""
    tokens: int = 0
    tool_uses: int = 0
    prompt: str = ""
    summary: str = ""
    # Trois sources de modèle, de la plus sûre à la plus vague : ce que le
    # sous-agent déclare dans ses messages, ce que le CLI a résolu au
    # lancement, ce que le brain a demandé.
    observed_model: str = ""
    resolved_model: str = ""
    requested_model: str = ""
    start_logged: bool = False
    # Identité stable de la tâche pour l'état de travail Core : son premier
    # identifiant public. `id` passe du `tool_use_id` au `task_id` quand le
    # `task_started` arrive ; Core, lui, doit voir un seul travail.
    work_key: str = ""
    trace: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_TRACE_ENTRIES))

    @property
    def id(self) -> str:
        return self.task_id or self.tool_use_id or ""

    @property
    def model(self) -> str:
        return self.observed_model or self.resolved_model or self.requested_model

    @property
    def running(self) -> bool:
        return self.status == "running"


# -------------------------------------------------------------------- tracker


class AgentTaskTracker:
    def __init__(
        self,
        *,
        provider: str,
        journal: RuntimeJournal | None = None,
        formatter: Formatter | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.provider = provider
        self.journal = journal
        self.formatter = formatter or _default_formatter
        # Horloge du serveur, à la réception : c'est elle que le client
        # compare à `now_ms` pour corriger son propre décalage.
        self.clock = clock
        self._tasks: list[AgentTask] = []
        self._by_task_id: dict[str, AgentTask] = {}
        self._by_tool_use: dict[str, AgentTask] = {}
        self.busy = False
        self.turn_started_ms: int | None = None
        self.started_ms: int | None = None
        self.brain_model = ""
        self.brain_activity = ""
        # L'appel d'outil que décrit `brain_activity` : sa réponse la périme.
        self._brain_call: str | None = None
        # Types d'exception déjà consignés par `report_failure`.
        self._failures: set[str] = set()
        # Observateurs prévenus après chaque changement possible (l'état de
        # travail Core, tâche 11 du handoff work-state), et types d'exception
        # qu'ils ont déjà levés.
        self._listeners: list[Callable[[], None]] = []
        self._listener_failures: set[str] = set()
        # Clés de travail d'une tâche absorbée par `_merge`.
        self._retired_work_keys: deque[str] = deque(maxlen=MAX_RETIRED_WORK_KEYS)

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    def report_failure(self, exc: Exception, event: dict[str, Any]) -> None:
        """Consigner l'échec du suivi sur un événement, une fois par type d'exception.

        L'agent qui nous alimente avale l'exception (sa lecture du flux doit
        survivre) et nous la confie : un événement malformé qui se répète à
        chaque ligne ne doit pas inonder le journal ni son compteur d'erreurs.
        """
        name = type(exc).__name__
        if name in self._failures or self.journal is None:
            return
        self._failures.add(name)
        self.journal.emit(
            "agent.subtasks_failed",
            f"Suivi des sous-tâches en échec ({name}) : événement ignoré, l'agent continue.",
            level="error",
            data={
                "code": "agent_tasks_failed",
                "provider": self.provider,
                "exception_type": name,
                "error": truncate(str(exc), 300),
                "event_type": truncate(str(event.get("type") or ""), 60),
            },
        )

    # ------------------------------------------------------- observateurs

    def subscribe(self, listener: Callable[[], None]) -> None:
        """Être prévenu après chaque événement et chaque arrêt/démarrage du processus.

        L'observateur relit l'état (`tasks()`) : il ne reçoit aucun événement
        brut. Il est appelé dans la boucle, sur le chemin de lecture du flux :
        il ne doit ni bloquer ni attendre.
        """
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            try:
                listener()
            except Exception as exc:  # noqa: BLE001
                # Un observateur défaillant ne doit casser ni le suivi ni la
                # lecture du flux qui l'alimente : consigné une fois par type.
                self._report_listener_failure(exc)

    def _report_listener_failure(self, exc: Exception) -> None:
        name = type(exc).__name__
        if name in self._listener_failures or self.journal is None:
            return
        self._listener_failures.add(name)
        self.journal.emit(
            "agent.work_state_failed",
            f"Relais de l'état des sous-tâches vers Core en échec ({name}) : l'agent continue.",
            level="error",
            data={"code": "agent_work_state_failed", "provider": self.provider, "exception_type": name, "error": truncate(str(exc), 300)},
        )

    def drain_retired_work_keys(self) -> list[str]:
        """Clés de travail retirées par une fusion depuis le dernier appel."""
        keys = list(self._retired_work_keys)
        self._retired_work_keys.clear()
        return keys

    # ------------------------------------------------------------ brain

    def process_started(self, *, now_ms: int | None = None) -> None:
        now = self.now_ms() if now_ms is None else now_ms
        # Des tâches encore « en cours » à ce stade appartenaient au processus
        # précédent : elles sont mortes avec lui.
        self._interrupt_all(now)
        self.turn_finished()
        self.started_ms = now
        self._notify()

    def process_stopped(self, *, now_ms: int | None = None) -> None:
        """Arrêt, redémarrage ou sortie du brain : ses sous-tâches meurent avec lui."""
        self._interrupt_all(self.now_ms() if now_ms is None else now_ms)
        self.turn_finished()
        self.started_ms = None
        self._notify()

    def turn_started(self, *, now_ms: int | None = None) -> None:
        if self.busy:
            return
        self.busy = True
        self.turn_started_ms = self.now_ms() if now_ms is None else now_ms

    def turn_finished(self) -> None:
        self.busy = False
        self.turn_started_ms = None
        self.brain_activity, self._brain_call = "", None

    def note_brain_activity(self, activity: str) -> None:
        self.brain_activity, self._brain_call = truncate(activity, MAX_LABEL), None

    # --------------------------------------------------- flux Claude Code

    @staticmethod
    def belongs_to_brain(event: dict[str, Any]) -> bool:
        """Un événement du brain lui-même, par opposition à ceux de ses sous-tâches.

        Les messages des sous-agents portent le `tool_use_id` de l'appel qui les
        a lancés dans `parent_tool_use_id`. `task_progress` arrive à chaque
        outil d'un sous-agent : il noierait l'historique du brain.
        """
        if event.get("parent_tool_use_id"):
            return False
        return not (event.get("type") == "system" and event.get("subtype") == "task_progress")

    def observe_claude(self, event: dict[str, Any], *, now_ms: int | None = None) -> None:
        """Intégrer un événement `stream-json` de Claude Code."""
        try:
            self._observe_claude(event, self.now_ms() if now_ms is None else now_ms)
        finally:
            # Même après un événement malformé : ce qui a déjà changé est vrai.
            self._notify()

    def _observe_claude(self, event: dict[str, Any], now: int) -> None:
        kind = event.get("type")
        parent = _text(event.get("parent_tool_use_id"))
        if kind == "system":
            self._on_system(event, now)
        elif kind == "assistant":
            self._on_assistant(event, parent, now)
        elif kind == "user":
            self._on_user(event, parent, now)
        elif kind == "result":
            if not parent:
                self.turn_finished()
        elif parent:
            # `tool_progress` et consorts : rattachés à leur tâche, s'il y en a une.
            task = self._by_tool_use.get(parent)
            if task is not None:
                self._append(task, event, now)

    def _on_system(self, event: dict[str, Any], now: int) -> None:
        # Toujours une chaîne : une liste ou un objet ici ferait lever le test
        # d'appartenance à `TASK_SUBTYPES` (valeur non hachable).
        subtype = _text(event.get("subtype"))
        if subtype == "init":
            model = _text(event.get("model"))
            if model:
                self.brain_model = model
            return
        if subtype not in TASK_SUBTYPES:
            return
        task_id = _text(event.get("task_id")) or None
        tool_use_id = _text(event.get("tool_use_id")) or None
        task = self._resolve(task_id, tool_use_id)
        if task is None:
            # Une notification ou une mise à jour d'une tâche inconnue ne suffit
            # pas à la décrire : mieux vaut ne rien afficher qu'une tâche fantôme.
            if subtype not in {"task_started", "task_progress"} or not (task_id or tool_use_id):
                return
            task = self._create(task_id=task_id, tool_use_id=tool_use_id, now=now)
            if event.get("subagent_type"):
                task.kind = "agent"

        if subtype == "task_started":
            self._apply_started(task, event)
        elif subtype == "task_progress":
            self._apply_progress(task, event)
        self._append(task, event, now)

        if subtype == "task_notification":
            self._apply_usage(task, event.get("usage"))
            summary = _text(event.get("summary")).strip()
            if summary:
                task.summary = truncate(summary, MAX_SUMMARY)
            status = _text(event.get("status")) or "completed"
            if status not in NON_TERMINAL:
                self._finish(task, status, now)
        elif subtype == "task_updated":
            patch = event.get("patch") if isinstance(event.get("patch"), dict) else {}
            if "is_backgrounded" in patch:
                task.background = bool(patch.get("is_backgrounded"))
            status = _text(patch.get("status"))
            if status and status not in NON_TERMINAL:
                self._finish(task, status, now)
            elif not status and patch.get("end_time") is not None:
                self._finish(task, "completed", now)
        self._maybe_log_start(task)

    def _apply_started(self, task: AgentTask, event: dict[str, Any]) -> None:
        kind = _kind_for(_text(event.get("task_type")))
        if kind is not None:
            task.kind = kind
        elif task.kind == "other" and event.get("subagent_type"):
            task.kind = "agent"
        description = _text(event.get("description")).strip()
        if description:
            task.description = truncate(description, MAX_LABEL)
        subagent_type = _text(event.get("subagent_type"))
        if subagent_type:
            task.subagent_type = subagent_type
        prompt = _text(event.get("prompt"))
        if prompt and not task.prompt:
            task.prompt = truncate(prompt, MAX_PROMPT)
        if "is_backgrounded" in event:
            task.background = bool(event.get("is_backgrounded"))
        depth = _int(event.get("spawn_depth"))
        if depth is not None and depth > 0:
            task.depth = depth

    def _apply_progress(self, task: AgentTask, event: dict[str, Any]) -> None:
        # Ici `description` décrit l'activité courante, pas la tâche.
        activity = _text(event.get("description")).strip()
        if activity:
            task.activity = truncate(activity, MAX_LABEL)
        last_tool = _text(event.get("last_tool_name"))
        if last_tool:
            task.last_tool = last_tool
        subagent_type = _text(event.get("subagent_type"))
        if subagent_type and not task.subagent_type:
            task.subagent_type = subagent_type
        self._apply_usage(task, event.get("usage"))

    @staticmethod
    def _apply_usage(task: AgentTask, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        tokens = _int(usage.get("total_tokens"))
        if tokens is not None:
            task.tokens = tokens
        tool_uses = _int(usage.get("tool_uses"))
        if tool_uses is not None:
            task.tool_uses = tool_uses

    def _on_assistant(self, event: dict[str, Any], parent: str, now: int) -> None:
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        task = self._by_tool_use.get(parent) if parent else None
        if task is not None:
            model = _text(message.get("model"))
            if model and model != SYNTHETIC_MODEL:
                task.observed_model = model
            self._append(task, event, now)
        elif not parent:
            # Un tour peut démarrer sans entrée écrite par nous (reprise après
            # la fin d'une tâche de fond) : le brain qui parle est occupé.
            self.turn_started(now_ms=now)
        content = message.get("content")
        for block in content if isinstance(content, list) else ():
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = _text(block.get("name")) or "outil"
            if name in AGENT_TOOLS:
                self._on_agent_call(block, parent or None, now)
            label = truncate(describe_tool(name, block.get("input")), MAX_LABEL)
            if task is not None:
                task.activity, task.last_tool = label, name
            elif not parent:
                self.brain_activity, self._brain_call = label, _text(block.get("id")) or None
        if task is not None:
            self._maybe_log_start(task)

    def _on_agent_call(self, block: dict[str, Any], parent_tool_use_id: str | None, now: int) -> None:
        tool_use_id = _text(block.get("id")) or None
        if tool_use_id is None:
            return
        payload = block.get("input") if isinstance(block.get("input"), dict) else {}
        task = self._by_tool_use.get(tool_use_id)
        if task is None:
            task = self._create(task_id=None, tool_use_id=tool_use_id, now=now)
        task.kind = "agent"
        description = _text(payload.get("description")).strip()
        if description and not task.description:
            task.description = truncate(description, MAX_LABEL)
        subagent_type = _text(payload.get("subagent_type"))
        if subagent_type and not task.subagent_type:
            task.subagent_type = subagent_type
        model = _text(payload.get("model"))
        if model:
            task.requested_model = model
        prompt = _text(payload.get("prompt"))
        if prompt and not task.prompt:
            task.prompt = truncate(prompt, MAX_PROMPT)
        if payload.get("run_in_background") is True:
            task.background = True
        if parent_tool_use_id:
            task.parent_tool_use_id = parent_tool_use_id
            parent = self._by_tool_use.get(parent_tool_use_id)
            if parent is not None and task.depth <= parent.depth:
                task.depth = parent.depth + 1
        self._maybe_log_start(task)

    def _on_user(self, event: dict[str, Any], parent: str, now: int) -> None:
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        content = message.get("content")
        results = [
            block for block in (content if isinstance(content, list) else ())
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        if parent:
            task = self._by_tool_use.get(parent)
            if task is not None:
                self._append(task, event, now)
        elif not results:
            # Vraie entrée utilisateur : un tour commence. Un `tool_result` de
            # premier niveau n'est que la suite du tour en cours.
            self.turn_started(now_ms=now)
        elif self._brain_call and any(block.get("tool_use_id") == self._brain_call for block in results):
            # Le brain a sa réponse — pour un sous-agent d'arrière-plan, la
            # confirmation du lancement : il n'attend plus cet outil.
            self.brain_activity, self._brain_call = "", None
        extra = event.get("tool_use_result")
        for block in results:
            # `tool_use_result` décrit l'unique résultat du message ; s'il y en a
            # plusieurs, l'attribuer serait deviner.
            self._on_tool_result(block, extra if len(results) == 1 else None, now)

    def _on_tool_result(self, block: dict[str, Any], extra: Any, now: int) -> None:
        tool_use_id = _text(block.get("tool_use_id")) or None
        extra = extra if isinstance(extra, dict) else {}
        # `agentId` (sous-agent d'arrière-plan) et `backgroundTaskId` (commande
        # lancée en fond, ou basculée en fond après son délai) sont des `task_id`.
        task_id = _text(extra.get("agentId")) or _text(extra.get("backgroundTaskId")) or None
        task = self._resolve(task_id, tool_use_id) if task_id else self._by_tool_use.get(tool_use_id or "")
        if task is None:
            return
        launched = extra.get("isAsync") is True or extra.get("status") == "async_launched" or bool(extra.get("backgroundTaskId"))
        entry = self._entry({"type": "user", "message": {"role": "user", "content": [block]}, "tool_use_result": extra}, now)
        # Le texte brut du résultat, pas sa sérialisation : c'est le compte rendu.
        entry["text"] = truncate(_result_text(block).strip(), MAX_TEXT)
        if launched or (task.background and not block.get("is_error")):
            entry.update(role="launch", title="En arrière-plan", status="busy")
        else:
            entry.update(role="result", title="Résultat de la tâche", status="bad" if block.get("is_error") else "ok")
        task.trace.append(entry)

        resolved = _text(extra.get("resolvedModel"))
        if resolved:
            task.resolved_model = resolved
        tokens = _int(extra.get("totalTokens"))
        if tokens is not None:
            task.tokens = tokens
        tool_uses = _int(extra.get("totalToolUseCount"))
        if tool_uses is not None:
            task.tool_uses = tool_uses

        if launched:
            # Lancement (ou bascule) en arrière-plan : la tâche continue, elle ne
            # finit pas. Sa fin viendra par `task_notification`/`task_updated`.
            task.background = True
            self._maybe_log_start(task)
            return
        if block.get("is_error"):
            status = "failed"
        elif task.background:
            # Tâche de fond : sa fin viendra par `task_notification`/`task_updated`.
            self._maybe_log_start(task)
            return
        else:
            raw_status = _text(extra.get("status"))
            status = raw_status if raw_status and raw_status not in NON_TERMINAL else "completed"
        if not task.summary:
            text = _result_text(block).strip()
            if text:
                task.summary = truncate(text, MAX_SUMMARY)
        self._finish(task, status, now)

    # ------------------------------------------------------------ registre

    def _create(self, *, task_id: str | None, tool_use_id: str | None, now: int) -> AgentTask:
        task = AgentTask(task_id=task_id, tool_use_id=tool_use_id, started_ms=now)
        task.work_key = task.id
        self._tasks.append(task)
        self._index(task)
        return task

    def _index(self, task: AgentTask) -> None:
        if task.task_id:
            self._by_task_id[task.task_id] = task
        if task.tool_use_id:
            self._by_tool_use[task.tool_use_id] = task

    def _resolve(self, task_id: str | None, tool_use_id: str | None) -> AgentTask | None:
        """Retrouver une tâche par l'un ou l'autre identifiant, en fusionnant au besoin.

        L'appel `Agent` (connu par son `tool_use_id`) et le `task_started`
        (qui apporte le `task_id`) arrivent dans un ordre quelconque : les deux
        désignent la même tâche, qui ne doit apparaître qu'une fois.
        """
        by_id = self._by_task_id.get(task_id) if task_id else None
        by_call = self._by_tool_use.get(tool_use_id) if tool_use_id else None
        if by_id is not None and by_call is not None and by_id is not by_call:
            self._merge(by_id, by_call)
        task = by_id or by_call
        if task is not None:
            if task_id and not task.task_id:
                task.task_id = task_id
            if tool_use_id and not task.tool_use_id:
                task.tool_use_id = tool_use_id
            self._index(task)
        return task

    def _merge(self, keep: AgentTask, drop: AgentTask) -> None:
        # Une seule identité survit côté Core : celle de la plus ancienne des
        # deux tâches, déjà vue le plus tôt. L'autre clé est retirée, pour que
        # l'observateur clôture le doublon qu'il aurait déjà publié.
        if drop.work_key and (not keep.work_key or drop.started_ms < keep.started_ms):
            keep.work_key, retired = drop.work_key, keep.work_key
        else:
            retired = drop.work_key
        if retired and retired != keep.work_key:
            self._retired_work_keys.append(retired)
        for name in (
            "tool_use_id", "subagent_type", "description", "parent_tool_use_id", "activity", "last_tool",
            "prompt", "summary", "observed_model", "resolved_model", "requested_model",
        ):
            if not getattr(keep, name) and getattr(drop, name):
                setattr(keep, name, getattr(drop, name))
        if keep.kind == "other":
            keep.kind = drop.kind
        keep.background = keep.background or drop.background
        keep.depth = max(keep.depth, drop.depth)
        keep.started_ms = min(keep.started_ms, drop.started_ms)
        keep.tokens = max(keep.tokens, drop.tokens)
        keep.tool_uses = max(keep.tool_uses, drop.tool_uses)
        keep.start_logged = keep.start_logged or drop.start_logged
        if keep.running and not drop.running:
            keep.status, keep.ended_ms = drop.status, drop.ended_ms
        entries = sorted([*drop.trace, *keep.trace], key=lambda entry: entry.get("ts_ms") or 0)
        keep.trace = deque(entries, maxlen=MAX_TRACE_ENTRIES)
        self._forget(drop)
        self._index(keep)

    def _forget(self, task: AgentTask) -> None:
        self._tasks = [item for item in self._tasks if item is not task]
        if task.task_id and self._by_task_id.get(task.task_id) is task:
            del self._by_task_id[task.task_id]
        if task.tool_use_id and self._by_tool_use.get(task.tool_use_id) is task:
            del self._by_tool_use[task.tool_use_id]

    def _entry(self, event: dict[str, Any], now: int) -> dict[str, Any]:
        entry = dict(self.formatter(compact_event(event)))
        entry["text"] = truncate(str(entry.get("text") or ""), MAX_TEXT)
        entry["ts_ms"] = now
        return entry

    def _append(self, task: AgentTask, event: dict[str, Any], now: int) -> None:
        task.trace.append(self._entry(event, now))

    def _finish(self, task: AgentTask, status: str, now: int) -> None:
        if not task.running:
            return
        task.status = status
        task.ended_ms = now
        task.activity = ""
        self._maybe_log_start(task)
        self._log_finished(task)
        self._prune()

    def _interrupt_all(self, now: int) -> None:
        for task in [item for item in self._tasks if item.running]:
            self._finish(task, "interrupted", now)

    def _prune(self) -> None:
        finished = [task for task in self._tasks if not task.running]
        excess = len(finished) - MAX_FINISHED_TASKS
        if excess <= 0:
            return
        finished.sort(key=lambda task: task.ended_ms or 0)
        for task in finished[:excess]:
            self._forget(task)

    # ------------------------------------------------------------- journal

    def _maybe_log_start(self, task: AgentTask) -> None:
        """Annoncer un sous-agent une fois son modèle connu (ou à sa fin)."""
        if task.kind != "agent" or task.start_logged or (task.running and not task.model):
            return
        task.start_logged = True
        if self.journal is None:
            return
        details = ", ".join(part for part in (task.subagent_type, task.model) if part)
        label = task.description or "(sans description)"
        self.journal.emit(
            "agent.subagent.started",
            f"Sous-agent lancé : {label}" + (f" ({details})" if details else ""),
            data=self._journal_data(task),
        )

    def _log_finished(self, task: AgentTask) -> None:
        if task.kind != "agent" or self.journal is None:
            return
        duration = format_duration((task.ended_ms or 0) - task.started_ms)
        label = task.description or "(sans description)"
        messages = {
            "completed": f"Sous-agent terminé en {duration} : {label}",
            "failed": f"Sous-agent en échec après {duration} : {label}",
            "killed": f"Sous-agent tué après {duration} : {label}",
            "stopped": f"Sous-agent arrêté après {duration} : {label}",
            "interrupted": f"Sous-agent interrompu après {duration} (agent principal arrêté) : {label}",
        }
        message = messages.get(task.status, f"Sous-agent terminé ({task.status}) après {duration} : {label}")
        self.journal.emit(
            "agent.subagent.finished",
            message,
            level="warning" if task.status in WARNING_STATUSES else "info",
            data={
                **self._journal_data(task),
                "status": task.status,
                "duration_ms": (task.ended_ms or 0) - task.started_ms,
                "tokens": task.tokens,
                "tool_uses": task.tool_uses,
                "summary": truncate(task.summary, 300),
            },
        )

    def _journal_data(self, task: AgentTask) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "task_id": task.id,
            "tool_use_id": task.tool_use_id,
            "subagent_type": task.subagent_type,
            "description": task.description,
            "model": task.model,
            "background": task.background,
            "depth": task.depth,
            "parent_id": self._parent_id(task),
        }

    # -------------------------------------------------------------- lecture

    def parent_of(self, task: AgentTask) -> AgentTask | None:
        # Résolu à la lecture : le parent a pu changer d'identifiant public
        # (son `task_started` est arrivé) depuis le lancement de l'enfant.
        if not task.parent_tool_use_id:
            return None
        return self._by_tool_use.get(task.parent_tool_use_id)

    def _parent_id(self, task: AgentTask) -> str | None:
        parent = self.parent_of(task)
        return parent.id if parent is not None else None

    def find(self, task_id: str) -> AgentTask | None:
        """Par `task_id`, ou par `tool_use_id` : un client peut encore tenir l'ancien.

        En dernier recours par `work_key`, l'`external_id` que Core connaît :
        le panneau ouvre la trace d'un travail Core sous cet identifiant
        (tâche 13), même si une fusion l'a rendu étranger aux deux autres.
        """
        found = self._by_task_id.get(task_id) or self._by_tool_use.get(task_id)
        if found is None and task_id:
            found = next((task for task in self._tasks if task.work_key == task_id), None)
        return found

    def tasks(self) -> list[AgentTask]:
        running = sorted((task for task in self._tasks if task.running), key=lambda task: task.started_ms)
        finished = sorted((task for task in self._tasks if not task.running), key=lambda task: -(task.ended_ms or 0))
        return [*running, *finished]

    def counts(self) -> dict[str, int]:
        """`active` : sous-tâches en cours hors commandes shell — ce que le panneau
        range sous « Sous-agents en cours », type inconnu (`other`) compris.
        Le brain n'est pas une tâche : il n'y figure jamais."""
        return {
            "active": sum(1 for task in self._tasks if task.running and task.kind != "shell"),
            "running_shell": sum(1 for task in self._tasks if task.running and task.kind == "shell"),
        }

    def task_snapshot(self, task: AgentTask) -> dict[str, Any]:
        return {
            "id": task.id,
            # Clé de jointure avec l'état Core (`external_id`) : stable, alors
            # que `id` passe du `tool_use_id` au `task_id` (tâche 13).
            "work_key": task.work_key,
            "tool_use_id": task.tool_use_id,
            "kind": task.kind,
            "provider": self.provider,
            "subagent_type": task.subagent_type,
            "description": task.description,
            "model": task.model,
            "status": task.status,
            "background": task.background,
            "depth": task.depth,
            "parent_id": self._parent_id(task),
            "started_ms": task.started_ms,
            "ended_ms": task.ended_ms,
            "activity": task.activity,
            "last_tool": task.last_tool,
            "tokens": task.tokens,
            "tool_uses": task.tool_uses,
            "prompt": task.prompt,
            "summary": task.summary,
            "trace_count": len(task.trace),
        }

    def brain_snapshot(self, *, state: str, session_id: str | None, configured_model: str = "") -> dict[str, Any]:
        return {
            "id": "brain",
            "provider": self.provider,
            "role": "Brain",
            "model": self.brain_model or configured_model or "",
            "state": state,
            "busy": self.busy,
            "turn_started_ms": self.turn_started_ms if self.busy else None,
            "started_ms": self.started_ms,
            "activity": self.brain_activity,
            "session_id": session_id,
        }

    def payload(self, *, state: str, session_id: str | None, configured_model: str = "") -> dict[str, Any]:
        return {
            "now_ms": self.now_ms(),
            "active_count": self.counts()["active"],
            "brain": self.brain_snapshot(state=state, session_id=session_id, configured_model=configured_model),
            "tasks": [self.task_snapshot(task) for task in self.tasks()],
        }

    def trace(self, task_id: str, *, limit: int = 300) -> dict[str, Any] | None:
        task = self.find(task_id)
        if task is None:
            return None
        entries = list(task.trace)[-max(1, limit):]
        return {"task": self.task_snapshot(task), "entries": entries}
