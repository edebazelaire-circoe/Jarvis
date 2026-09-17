"""Sub-agent spans as Conversation Events, attributed only from Core's explicit scope (Slice 03b).

Binding contract: `docs/conversation-events.md`, "Sub-agent mapping rule".
`AgentTaskTracker` (`agent_tasks.py`) rebuilds sub-tasks from the Claude
`stream-json` flow; this module decides which of them belong to which
conversation, and records their spans through the process recorder
(`ConversationEventForwarder`). The tracker delegates to `SubagentConversations`
at five points: an `Agent` call, a top-level `result`, a brain process
start/stop, the start/finish journal lines, and the merge of two halves.

Rule, never inferred from labels, descriptions or timing:

1. Core names the conversation of a question (`/api/agent/ask` `conversation`
   block → `SubagentConversationScope`); `begin_turn` opens a pending
   attribution before the message is written. It is ambiguous when a brain turn
   was already running, or when another message was written meanwhile.
2. A top-level `Agent` call during a non-ambiguous pending attribution is
   attributed provisionally; a nested sub-agent takes its parent task's scope.
3. The next top-level `result` confirms (consumed uuids exactly the scoped
   message) or rejects (merged turn, unverifiable CLI, ambiguity). A result that
   does not consume the scoped message rejects that turn's provisional tasks and
   keeps waiting.
4. Unattributed sub-agents record nothing: counted and journaled once per task.

Span identity: `SubagentSpan.key`, the task's `work_key` frozen at attribution,
stable when `AgentTask.id` moves from `tool_use_id` to `task_id`.

Nothing here raises into the tracker: a recording bug is counted and journaled
once per exception type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from jarvis.core.conversation_event_emitter import PRODUCER_BRAIN_SERVICE, journal_ref, journal_trace
from jarvis.domain.conversation_events import ConversationEventType
from jarvis.ports.v2 import ConversationEventRecorder
from jarvis.runtime.conversation_event_forwarder import PRODUCER_AGENT_TASKS, optional_id, public_text

if TYPE_CHECKING:
    from jarvis.runtime.agent_tasks import AgentTask, AgentTaskTracker

UNATTRIBUTED_KIND = "agent.subagent.conversation_unattributed"
ATTRIBUTION_UNVERIFIABLE_KIND = "agent.subagent.attribution_unverifiable"
EVENT_FAILED_KIND = "agent.subagent.conversation_event_failed"

#: Contract mapping (`docs/conversation-events.md`, note 3): completed → finished;
#: killed/stopped/interrupted → stopped; failed and any other status → failed.
_STOPPED_STATUSES = frozenset({"killed", "stopped", "interrupted"})


def utc_from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def subagent_close_type(status: str) -> ConversationEventType:
    if status == "completed":
        return ConversationEventType.SUBAGENT_FINISHED
    if status in _STOPPED_STATUSES:
        return ConversationEventType.SUBAGENT_STOPPED
    return ConversationEventType.SUBAGENT_FAILED


def consumed_message_uuids(event: dict[str, Any]) -> set[str] | None:
    """Messages utilisateur qu'un `result` a consommés, ou None si le CLI ne le dit pas.

    Un tour peut en consommer plusieurs (message écrit pendant le tour et
    fusionné), ou aucun : le CLI ouvre de lui-même un tour quand une tâche de
    fond se termine, et le marque d'un `origin`.
    """
    uuids = event.get("user_message_uuids")
    if isinstance(uuids, list):
        return {str(value) for value in uuids if value}
    single = event.get("user_message_uuid")
    if isinstance(single, str) and single:
        return {single}
    if isinstance(event.get("origin"), dict):
        return set()
    return None


def _bounded_label(value: Any) -> str | None:
    """Short printable label for a Conversation Event attribute, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip().encode("utf-8", "replace").decode("utf-8")
    if not text or len(text) > 256 or not text.isprintable():
        return None
    return text


@dataclass(frozen=True, slots=True)
class SubagentConversationScope:
    """Conversation d'une question Core, transmise explicitement par `/api/agent/ask`.

    `correlation_id` et `work_id` sont ceux du tour cerveau qui pose la question
    (`ControlCenterBrainBackend`) : présents ensemble, ils désignent le
    `brain.work.started` parent des sous-agents lancés pendant ce tour.
    """

    conversation_id: str
    correlation_id: str | None = None
    work_id: str | None = None

    @classmethod
    def from_payload(cls, value: Any) -> "SubagentConversationScope | None":
        """None when absent or not a valid explicit scope (never inferred from anything else)."""
        if not isinstance(value, dict):
            return None
        conversation_id = optional_id(value.get("conversation_id"))
        if conversation_id is None:
            return None
        # An invalid optional id is dropped, never repaired: the parent link then
        # simply does not exist (`_parent_event_id` needs both).
        return cls(conversation_id, optional_id(value.get("correlation_id")), optional_id(value.get("work_id")))


@dataclass(slots=True)
class SubagentSpan:
    """Conversation state of one task (`AgentTask.conversation`)."""

    scope: SubagentConversationScope | None = None
    confirmed: bool = False
    key: str = ""
    parent_key: str = ""
    started_ms: int | None = None
    start_journal_event_id: str | None = None
    finish_journal_event_id: str | None = None
    start_recorded: bool = False
    close_recorded: bool = False
    skipped: bool = False


@dataclass(slots=True)
class _PendingScope:
    scope: SubagentConversationScope
    message_uuid: str
    #: Un tour tournait déjà à l'envoi : ce qui s'y lance n'est pas attribuable.
    busy_at_send: bool = False
    #: Un autre message est parti pendant l'attente : le CLI peut les fusionner.
    foreign_input: bool = False
    tasks: list["AgentTask"] = field(default_factory=list)


def _span(task: "AgentTask") -> SubagentSpan:
    if task.conversation is None:
        task.conversation = SubagentSpan()
    return task.conversation


class SubagentConversations:
    """Attribution and span recording for the sub-tasks of one `AgentTaskTracker`."""

    def __init__(self, tracker: "AgentTaskTracker") -> None:
        self._tracker = tracker
        #: Synchronous process recorder (`ConversationEventForwarder`). None: nothing.
        self.recorder: ConversationEventRecorder | None = None
        #: Attributed sub-agents, and unattributed ones by reason.
        self.counts: dict[str, int] = {}
        #: `claude_code_version` of the `system/init` event, when the CLI gives it.
        self.cli_version: str | None = None
        self._pending: _PendingScope | None = None
        self._failures: set[str] = set()
        self._unverifiable_reported = False
        #: Scoped turns whose `result` did not name the consumed messages.
        self.unverifiable_results = 0

    # -- turn attribution --------------------------------------------------------

    def begin_turn(self, scope: SubagentConversationScope, *, message_uuid: str) -> None:
        if self.recorder is None:
            return
        previous = self._pending
        if previous is not None:
            # Question précédente jamais soldée (délai dépassé, résultat perdu) :
            # ses sous-agents provisoires ne sont plus attribuables avec certitude.
            self._reject(previous.tasks, "turn_unresolved")
        self._pending = _PendingScope(scope=scope, message_uuid=message_uuid, busy_at_send=self._tracker.busy)

    def note_unscoped_input(self) -> None:
        if self._pending is not None:
            self._pending.foreign_input = True

    def attribute(self, task: "AgentTask", parent: "AgentTask | None", *, nested: bool) -> None:
        """Rattacher une tâche d'agent à une conversation, sans jamais deviner."""
        if self.recorder is None or (task.conversation is not None and task.conversation.scope is not None):
            return
        pending = self._pending
        if nested:
            if parent is None or parent is task or parent.conversation is None or parent.conversation.scope is None:
                return
            span, parent_span = _span(task), parent.conversation
            span.scope, span.confirmed, span.parent_key = parent_span.scope, parent_span.confirmed, parent_span.key
            if not span.confirmed and pending is not None and parent in pending.tasks:
                pending.tasks.append(task)
        else:
            if pending is None or pending.busy_at_send or pending.foreign_input:
                return
            _span(task).scope = pending.scope
            pending.tasks.append(task)
        task.conversation.key = task.work_key or task.id

    def settle(self, event: dict[str, Any]) -> None:
        """Au `result` d'un tour du brain : confirmer ou retirer l'attribution provisoire."""
        pending = self._pending
        if pending is None:
            return
        consumed = consumed_message_uuids(event)
        if consumed is None:
            self._pending = None
            self._report_unverifiable()
            self._reject(pending.tasks, "turn_unverifiable")
            return
        if pending.message_uuid not in consumed:
            # Un autre tour s'est terminé (relais spontané, message du panneau) :
            # ce qui y a été lancé n'est pas à nous, et notre message attend encore.
            self._reject(pending.tasks, "other_turn")
            pending.tasks = []
            pending.busy_at_send = False
            return
        self._pending = None
        if len(consumed) != 1 or pending.busy_at_send or pending.foreign_input:
            self._reject(pending.tasks, "turn_ambiguous")
            return
        for task in pending.tasks:
            span = task.conversation
            if span is None or span.scope != pending.scope:
                continue
            span.confirmed = True
            self.counts["attributed"] = self.counts.get("attributed", 0) + 1
            self._record_start(task)
            self._record_close(task)

    def process_boundary(self) -> None:
        """Le processus du brain démarre ou s'arrête : ses tours en cours meurent avec lui.

        La question en attente reste attendue (elle peut être la cause du
        démarrage), mais ce qui avait été lancé à titre provisoire est retiré.
        """
        pending = self._pending
        if pending is None:
            return
        self._reject(pending.tasks, "process_stopped")
        pending.tasks = []
        pending.busy_at_send = False

    def note_cli_version(self, value: Any) -> None:
        label = _bounded_label(value)
        if label:
            self.cli_version = label[:64]

    # -- journal lines -------------------------------------------------------------

    def start_logged(self, task: "AgentTask", *, journaled: bool) -> dict[str, str]:
        """`agent.subagent.started` is about to be written: its `data` join entry, and record when confirmed."""
        span = task.conversation
        if self.recorder is None or span is None:
            return {}
        try:
            event_id = self._event_id(task, ConversationEventType.SUBAGENT_STARTED) if journaled else None
            span.start_journal_event_id = event_id
            if span.scope is not None and span.started_ms is None:
                span.started_ms = task.started_ms
        except Exception as exc:  # noqa: BLE001 - instrumentation never breaks the stream reader
            self._report_failure(exc, ConversationEventType.SUBAGENT_STARTED)
            return {}
        self._record_start(task)
        return journal_ref(event_id)

    def finish_logged(self, task: "AgentTask", *, journaled: bool) -> dict[str, str]:
        """`agent.subagent.finished` is about to be written (or would be, without a journal)."""
        if self.recorder is None:
            return {}
        span = task.conversation
        if span is None or span.scope is None:
            self._note_unattributed(task, "no_conversation_scope")
            return {}
        try:
            event_id = self._event_id(task, subagent_close_type(task.status)) if journaled else None
            span.finish_journal_event_id = event_id
        except Exception as exc:  # noqa: BLE001 - instrumentation never breaks the stream reader
            self._report_failure(exc, subagent_close_type(task.status))
            return {}
        self._record_close(task)
        return journal_ref(event_id)

    def merge(self, keep: "AgentTask", drop: "AgentTask") -> None:
        """Fusion de deux moitiés d'une tâche : une seule identité de span survit."""
        dropped = drop.conversation
        if dropped is None or dropped.scope is None:
            return
        pending = self._pending
        kept = keep.conversation
        if kept is None or kept.scope is None:
            keep.conversation = dropped
            if pending is not None and drop in pending.tasks:
                pending.tasks[pending.tasks.index(drop)] = keep
            return
        if pending is not None and drop in pending.tasks:
            pending.tasks.remove(drop)
        if dropped.key != kept.key and dropped.start_recorded and not dropped.close_recorded:
            # Le span de la moitié absorbée était déjà ouvert : il est clos, pas laissé ouvert pour toujours.
            self._record_close(drop, status="stopped", reason="merged", ended_ms=self._tracker.now_ms())

    # -- recording -----------------------------------------------------------------

    def _event_id(self, task: "AgentTask", event_type: ConversationEventType) -> str | None:
        span = task.conversation
        if self.recorder is None or span is None or span.scope is None or not span.key:
            return None
        return self.recorder.derive_event_id(event_type, producer=PRODUCER_AGENT_TASKS,
                                             conversation_id=span.scope.conversation_id, source_ids=(span.key,))

    def _parent_event_id(self, span: SubagentSpan) -> str | None:
        scope, recorder = span.scope, self.recorder
        if scope is None or recorder is None:
            return None
        if span.parent_key:
            return recorder.derive_event_id(ConversationEventType.SUBAGENT_STARTED, producer=PRODUCER_AGENT_TASKS,
                                            conversation_id=scope.conversation_id, source_ids=(span.parent_key,))
        if scope.correlation_id and scope.work_id:
            # Le travail cerveau qui a posé la question : ids explicites de Core.
            return recorder.derive_event_id(ConversationEventType.BRAIN_WORK_STARTED,
                                            producer=PRODUCER_BRAIN_SERVICE, conversation_id=scope.conversation_id,
                                            source_ids=(scope.correlation_id, scope.work_id))
        return None

    def _attributes(self, task: "AgentTask") -> dict[str, Any]:
        attributes: dict[str, Any] = {"provider": self._tracker.provider, "background": task.background,
                                      "depth": task.depth}
        for key, value in (("subagent_type", task.subagent_type), ("model", task.model)):
            text = _bounded_label(value)
            if text:
                attributes[key] = text
        return attributes

    def _record_start(self, task: "AgentTask") -> None:
        recorder, span = self.recorder, task.conversation
        if (recorder is None or span is None or span.scope is None or not span.confirmed or span.start_recorded
                or not task.start_logged or task.kind != "agent"):
            return
        span.start_recorded = True
        try:
            if span.started_ms is None:
                span.started_ms = task.started_ms
            event_id = self._event_id(task, ConversationEventType.SUBAGENT_STARTED)
            recorder.record(
                ConversationEventType.SUBAGENT_STARTED, producer=PRODUCER_AGENT_TASKS,
                conversation_id=span.scope.conversation_id, source_ids=(span.key,),
                occurred_at=utc_from_ms(span.started_ms), span_id=span.key, task_id=span.key,
                correlation_id=span.scope.correlation_id, work_id=span.scope.work_id,
                parent_event_id=self._parent_event_id(span),
                trace_ref=(journal_trace("agent.subagent.started")
                           if event_id is not None and span.start_journal_event_id == event_id else None),
                content=public_text(task.description), attributes=self._attributes(task))
        except Exception as exc:  # noqa: BLE001 - instrumentation never breaks the stream reader nor agent stop
            self._report_failure(exc, ConversationEventType.SUBAGENT_STARTED)

    def _record_close(self, task: "AgentTask", *, status: str | None = None, reason: str | None = None,
                      ended_ms: int | None = None) -> None:
        """`subagent.finished|stopped|failed` for a finished task (or an explicit status, e.g. merged)."""
        recorder, span = self.recorder, task.conversation
        raw = status if status is not None else task.status
        end = ended_ms if ended_ms is not None else task.ended_ms
        if (recorder is None or span is None or span.scope is None or not span.confirmed or span.close_recorded
                or task.kind != "agent" or (status is None and task.running) or end is None):
            return
        self._record_start(task)
        span.close_recorded = True
        event_type = subagent_close_type(raw)
        try:
            event_id = self._event_id(task, event_type)
            attributes = {**self._attributes(task), "status": _bounded_label(raw) or "unknown"}
            # The tracker starts usage at 0 and only overwrites it when the CLI reports it:
            # 0 means "not reported", never recorded as a measured value.
            attributes.update({key: value for key, value in (("tokens", task.tokens), ("tool_uses", task.tool_uses))
                               if value})
            fields: dict[str, Any] = {}
            if span.start_recorded and span.started_ms is not None and span.started_ms <= end:
                fields["started_at"] = utc_from_ms(span.started_ms)
                attributes["duration_ms"] = end - span.started_ms
            if reason is not None:
                attributes["reason"] = reason
            recorder.record(
                event_type, producer=PRODUCER_AGENT_TASKS, conversation_id=span.scope.conversation_id,
                source_ids=(span.key,), occurred_at=utc_from_ms(end), span_id=span.key, task_id=span.key,
                correlation_id=span.scope.correlation_id, work_id=span.scope.work_id,
                parent_event_id=self._parent_event_id(span),
                trace_ref=(journal_trace("agent.subagent.finished")
                           if event_id is not None and span.finish_journal_event_id == event_id else None),
                attributes=attributes, **fields)
        except Exception as exc:  # noqa: BLE001 - instrumentation never breaks the stream reader nor agent stop
            self._report_failure(exc, event_type)

    # -- diagnostics -----------------------------------------------------------------

    def _reject(self, tasks: list["AgentTask"], reason: str) -> None:
        for task in tasks:
            span = task.conversation
            if span is None or span.confirmed or span.scope is None:
                continue
            span.scope = None
            self._note_unattributed(task, reason)

    def _note_unattributed(self, task: "AgentTask", reason: str) -> None:
        span = _span(task)
        if span.skipped:
            return
        span.skipped = True
        self.counts[reason] = self.counts.get(reason, 0) + 1
        self._emit(UNATTRIBUTED_KIND, "Sous-agent sans conversation certaine : aucun Conversation Event enregistré",
                   "info", {"provider": self._tracker.provider, "task_id": span.key or task.work_key or task.id,
                            "reason": reason, "count": self.counts[reason]})

    def _report_unverifiable(self) -> None:
        """A scoped turn's `result` names no consumed message: the CLI regressed. Once per tracker."""
        self.unverifiable_results += 1
        if self._unverifiable_reported:
            return
        self._unverifiable_reported = True
        self._emit(ATTRIBUTION_UNVERIFIABLE_KIND,
                   "Le CLI ne dit plus quels messages un tour a consommés : aucun sous-agent ne peut être attribué",
                   "warning", {"code": "subagent_attribution_unverifiable", "provider": self._tracker.provider,
                               "cli_version": self.cli_version, "unverifiable_results": self.unverifiable_results})

    def _report_failure(self, exc: Exception, event_type: ConversationEventType) -> None:
        """A recording bug is journaled once per exception type, never raised into the tracker."""
        self.counts["producer_failed"] = self.counts.get("producer_failed", 0) + 1
        name = type(exc).__name__
        if name in self._failures:
            return
        self._failures.add(name)
        self._emit(EVENT_FAILED_KIND, f"Conversation Event de sous-agent non enregistré ({name}) : l'agent continue.",
                   "error", {"code": "subagent_conversation_event_failed", "provider": self._tracker.provider,
                             "event_type": event_type.value, "exception_type": name})

    def _emit(self, kind: str, message: str, level: str, data: dict[str, Any]) -> None:
        journal = self._tracker.journal
        if journal is None:
            return
        try:
            journal.emit(kind, message, level=level, data=data)
        except Exception:  # noqa: BLE001 - counted: a failing journal never breaks the stream reader
            self.counts["diagnostic_failures"] = self.counts.get("diagnostic_failures", 0) + 1
