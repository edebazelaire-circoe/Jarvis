"""Single-owner synchronous reducer for canonical voice evidence.

This is not a history writer, scheduler, permission gate or task executor.
Production composition and migration of ConversationService projection follow
in Task05. Provider and local audio producers share a canonical sequence source.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from enum import StrEnum
from typing import ClassVar

from jarvis.domain.voice_events import (
    AssistantAudioChunk, AssistantAudioReceived, AssistantGenerationFinished, AssistantGenerationStarted,
    AssistantPlaybackEvidence, AssistantSpeechActivity, AssistantTranscriptCompleted,
    AssistantTranscriptDelta, FrontendLifecycleChanged, UserInterruption,
    UserTranscriptCommitted, UserTranscriptDelta, UserTranscriptRevised, UserTurnOpened,
    VoiceEvent, VoiceFrontendFailed, VoiceGenerationStatus, VoiceInterruptionStage,
    VoicePlaybackStatus, VoiceSpeechPhase,
)
from jarvis.domain.voice_frontend import (
    FrontendState, VoiceContext, VoiceContextMessage, VoiceContextRole, VoiceCorrelation,
)
from jarvis.domain.voice_state import (
    MAX_SEEN_EVENTS, MAX_SPEECHES, MAX_TASKS, MAX_TURNS, MAX_USERS, SeenVoiceEvent,
    VoiceConversationSnapshot, VoiceGeneratedText, VoiceSpeechRecord, VoiceSpeechState,
    VoiceTaskRecord, VoiceTurnOrder, VoiceUserRecord, correlation_valid, state_id,
)
from jarvis.domain.work_state import can_transition
from jarvis.ports.v2 import DiagnosticSink


class VoiceStateDisposition(StrEnum):
    APPLIED = "applied"
    IGNORED = "ignored"
    DUPLICATE = "duplicate"
    STALE = "stale"
    STALE_SESSION = "stale_session"
    REJECTED = "rejected"
    CAPACITY = "capacity"


@dataclass(frozen=True, slots=True)
class VoiceStateResult:
    disposition: VoiceStateDisposition
    code: str
    revision: int
    authorizes_actions: ClassVar[bool] = False


class _Rejected(ValueError):
    def __init__(self, code: str, disposition: VoiceStateDisposition = VoiceStateDisposition.REJECTED):
        super().__init__(code)
        self.code = code
        self.disposition = disposition


class VoiceConversationState:
    """Atomic between awaits: call from one Core event-loop owner, never threads.

    Read immutable snapshot properties; no provider dictionaries or mutable
    containers escape. Retention refuses capacity rather than dropping active
    task references, current turn, provisional input or active speech candidates.
    """

    def __init__(
        self, conversation_id: str, *, diagnostics: DiagnosticSink | None = None,
        max_users: int = MAX_USERS, max_speeches: int = MAX_SPEECHES,
        max_tasks: int = MAX_TASKS, max_seen_events: int = MAX_SEEN_EVENTS,
    ) -> None:
        self._snapshot = VoiceConversationSnapshot(conversation_id)
        self._diagnostics = diagnostics
        self.diagnostic_failures = 0
        self.last_monotonic_ns: int | None = None
        self._limits = {"users": max_users, "speeches": max_speeches, "tasks": max_tasks, "seen_events": max_seen_events}
        for name, maximum in (("users", MAX_USERS), ("speeches", MAX_SPEECHES), ("tasks", MAX_TASKS), ("seen_events", MAX_SEEN_EVENTS)):
            if type(self._limits[name]) is not int or not 1 <= self._limits[name] <= maximum:
                raise ValueError(f"invalid {name} retention limit")

    @property
    def snapshot(self) -> VoiceConversationSnapshot:
        return self._snapshot

    @property
    def active_tasks(self) -> tuple[VoiceTaskRecord, ...]:
        return tuple(task for task in self.snapshot.tasks if not task.status.is_terminal)

    @property
    def speech_candidates(self) -> tuple[VoiceSpeechRecord, ...]:
        return tuple(speech for speech in self.snapshot.speeches if speech.state == VoiceSpeechState.QUEUED)

    @classmethod
    def from_snapshot(cls, snapshot: VoiceConversationSnapshot, *, diagnostics: DiagnosticSink | None = None) -> VoiceConversationState:
        result = cls(snapshot.conversation_id, diagnostics=diagnostics)
        # Revalidate through the public codec; no mutable containers or stale
        # process-local playback/session activity claims survive rehydration.
        restored = VoiceConversationSnapshot.from_dict(snapshot.to_dict())
        uncertain = restored.lifecycle not in (FrontendState.NEW, FrontendState.STOPPED)
        result._snapshot = replace(
            restored,
            lifecycle=FrontendState.UNKNOWN_REAP_REQUIRED if uncertain else restored.lifecycle,
            speeches=tuple(replace(s, local_active=False, state=VoiceSpeechState.UNKNOWN) if s.active else s for s in restored.speeches),
        )
        return result

    def bind_session(self, session_id: str) -> VoiceStateResult:
        state_id(session_id, "session_id")
        if self.snapshot.current_session_id == session_id:
            return self._result(VoiceStateDisposition.DUPLICATE, "voice_state_session_already_bound")
        if self.snapshot.current_session_id is not None and self.snapshot.lifecycle not in (FrontendState.NEW, FrontendState.STOPPED):
            return self._result(VoiceStateDisposition.REJECTED, "voice_state_close_required")
        speeches = tuple(replace(s, local_active=False, state=VoiceSpeechState.INTERRUPTED if s.played_ms else VoiceSpeechState.CANCELLED) if s.active else s for s in self.snapshot.speeches)
        self._snapshot = replace(self.snapshot, current_session_id=session_id, lifecycle=FrontendState.NEW,
                                 speeches=speeches, seen_events=(), sequence_floor=-1,
                                 revision=self.snapshot.revision + 1)
        self.last_monotonic_ns = None
        return self._result(VoiceStateDisposition.APPLIED, "voice_state_session_bound")

    def apply(self, event: VoiceEvent) -> VoiceStateResult:
        try:
            correlation_valid(event.correlation)
            state_id(event.event_id, "event_id")
            if event.correlation.session_id != self.snapshot.current_session_id:
                return self._result(VoiceStateDisposition.STALE_SESSION, "voice_state_stale_session", event)
            if any(item.event_id == event.event_id for item in self.snapshot.seen_events):
                return self._result(VoiceStateDisposition.DUPLICATE, "voice_state_duplicate", event)
            if event.sequence <= self.snapshot.sequence_floor:
                return self._result(VoiceStateDisposition.STALE, "voice_state_replay_expired", event)
            if any(item.sequence == event.sequence for item in self.snapshot.seen_events):
                raise _Rejected("voice_state_sequence_conflict")
            changes = self._reduce(event)
            self._commit(changes, event)
        except _Rejected as exc:
            return self._result(exc.disposition, exc.code, event)
        except (ValueError, TypeError):
            # Boundary values are rejected atomically with sanitized diagnostics;
            # source text/exception messages are deliberately never logged.
            return self._result(VoiceStateDisposition.REJECTED, "voice_state_invalid_event", event)
        self.last_monotonic_ns = event.observation.monotonic_ns
        result = self._result(VoiceStateDisposition.APPLIED if changes else VoiceStateDisposition.IGNORED,
                              "voice_state_applied" if changes else "voice_state_observed", event,
                              log=not isinstance(event.payload, (AssistantAudioChunk, AssistantAudioReceived)))
        if isinstance(event.payload, AssistantTranscriptCompleted):
            speech = self._find_speech(event.correlation)
            if speech and speech.intended_text is not None and speech.generated_text != speech.intended_text:
                self._diagnose("voice.state.diverged", "voice_state_generated_divergence", "info", event)
        if isinstance(event.payload, AssistantPlaybackEvidence) and event.payload.status == VoicePlaybackStatus.COMPLETE:
            speech = self._find_speech(event.correlation)
            if (speech and speech.confirmed_text is not None and speech.intended_text is not None
                    and speech.confirmed_text != speech.intended_text):
                self._diagnose("voice.state.spoken_diverged", "voice_state_spoken_divergence", "info", event)
        if isinstance(event.payload, VoiceFrontendFailed):
            self._diagnose("voice.state.frontend_error", event.payload.error.code.value, "error", event)
        return result

    def queue_speech(self, correlation: VoiceCorrelation, intended_text: str) -> VoiceStateResult:
        """Register a candidate only. Neither queue registration nor a task result plays it."""
        try:
            correlation_valid(correlation)
            if correlation.session_id != self.snapshot.current_session_id:
                raise _Rejected("voice_state_stale_session", VoiceStateDisposition.STALE_SESSION)
            if self.snapshot.lifecycle not in (FrontendState.NEW, FrontendState.STARTING, FrontendState.ACTIVE):
                raise _Rejected("voice_state_frontend_closed")
            if correlation.speech_id is None:
                raise _Rejected("voice_state_speech_id_required")
            if correlation.task_id is not None and not any(t.task_id == correlation.task_id for t in self.snapshot.tasks):
                raise _Rejected("voice_state_task_missing")
            existing = self._find_speech(correlation)
            if existing:
                if existing.intended_text == intended_text:
                    return self._result(VoiceStateDisposition.DUPLICATE, "voice_state_duplicate")
                raise _Rejected("voice_state_speech_intent_conflict")
            self._commit({"speeches": (*self.snapshot.speeches, VoiceSpeechRecord(correlation, intended_text))})
        except _Rejected as exc:
            return self._result(exc.disposition, exc.code)
        except (ValueError, TypeError):
            # Public typed input rejected before mutation; report only stable code.
            return self._result(VoiceStateDisposition.REJECTED, "voice_state_invalid_candidate")
        return self._result(VoiceStateDisposition.APPLIED, "voice_state_candidate_queued")

    def update_task(self, task: VoiceTaskRecord) -> VoiceStateResult:
        """Mirror authorized Core work; frontend events never call this implicitly."""
        if not isinstance(task, VoiceTaskRecord):
            return self._result(VoiceStateDisposition.REJECTED, "voice_state_invalid_task")
        if not any(u.committed and u.correlation.turn_id == task.source_turn_id for u in self.snapshot.users):
            return self._result(VoiceStateDisposition.REJECTED, "voice_state_committed_source_required")
        previous = next((t for t in self.snapshot.tasks if t.task_id == task.task_id), None)
        if previous:
            if task == previous:
                return self._result(VoiceStateDisposition.DUPLICATE, "voice_state_duplicate")
            if task.revision <= previous.revision:
                return self._result(VoiceStateDisposition.STALE, "voice_state_stale_revision")
            if task.source_turn_id != previous.source_turn_id or (task.status != previous.status and not can_transition(previous.status, task.status)):
                return self._result(VoiceStateDisposition.REJECTED, "voice_state_task_transition_invalid")
        tasks = tuple(task if t.task_id == task.task_id else t for t in self.snapshot.tasks) if previous else (*self.snapshot.tasks, task)
        try:
            self._commit({"tasks": tasks})
        except _Rejected as exc:
            return self._result(exc.disposition, exc.code)
        return self._result(VoiceStateDisposition.APPLIED, "voice_state_task_updated")

    def _reduce(self, event: VoiceEvent) -> dict:
        payload = event.payload
        closing = self.snapshot.lifecycle in (FrontendState.STOPPING, FrontendState.STOPPED, FrontendState.UNKNOWN_REAP_REQUIRED)
        starts_activity = isinstance(payload, (UserTurnOpened, UserTranscriptDelta, UserTranscriptRevised,
                                                UserTranscriptCommitted, AssistantGenerationStarted, UserInterruption))
        starts_activity |= isinstance(payload, AssistantSpeechActivity) and payload.phase == VoiceSpeechPhase.STARTED
        if closing and starts_activity:
            raise _Rejected("voice_state_frontend_closed", VoiceStateDisposition.STALE)
        if isinstance(payload, FrontendLifecycleChanged):
            transitions = {
                FrontendState.NEW: {FrontendState.STARTING, FrontendState.STOPPING, FrontendState.STOPPED},
                FrontendState.STARTING: {FrontendState.ACTIVE, FrontendState.STOPPING, FrontendState.UNKNOWN_REAP_REQUIRED},
                FrontendState.ACTIVE: {FrontendState.STOPPING, FrontendState.UNKNOWN_REAP_REQUIRED},
                FrontendState.STOPPING: {FrontendState.STOPPED, FrontendState.UNKNOWN_REAP_REQUIRED},
                FrontendState.UNKNOWN_REAP_REQUIRED: {FrontendState.STOPPING, FrontendState.STOPPED},
                FrontendState.STOPPED: set(),
            }
            if payload.state != self.snapshot.lifecycle and payload.state not in transitions[self.snapshot.lifecycle]:
                raise _Rejected("voice_state_lifecycle_conflict")
            changes = {"lifecycle": payload.state}
            if payload.state == FrontendState.STOPPED:
                changes["speeches"] = tuple(replace(s, local_active=False, state=VoiceSpeechState.UNKNOWN) if s.active else s for s in self.snapshot.speeches)
            return changes
        if isinstance(payload, UserTurnOpened):
            previous = next((t for t in self.snapshot.turns if t.turn_id == event.correlation.turn_id), None)
            turn = VoiceTurnOrder(event.correlation.session_id, event.correlation.turn_id, payload.previous_turn_id,
                                  previous.observation_order if previous else self.snapshot.revision + 1)
            if previous and previous != turn:
                raise _Rejected("voice_state_turn_order_conflict")
            turns = self.snapshot.turns if previous else (*self.snapshot.turns, turn)
            active = self.snapshot.active_turn_id
            lookup = {t.turn_id: t for t in turns}
            cursor = turn.previous_turn_id
            visited = {turn.turn_id}
            descends_from_active = False
            while cursor in lookup:
                if cursor in visited:
                    raise _Rejected("voice_state_turn_order_cycle")
                visited.add(cursor)
                descends_from_active |= cursor == active
                cursor = lookup[cursor].previous_turn_id
            if active is None or lookup[active].session_id != turn.session_id or descends_from_active:
                active = turn.turn_id
            return {"turns": turns, "active_turn_id": active}
        if isinstance(payload, (UserTranscriptDelta, UserTranscriptRevised, UserTranscriptCommitted)):
            return self._user(event)
        if isinstance(payload, (AssistantAudioChunk, AssistantAudioReceived, AssistantTranscriptDelta, AssistantTranscriptCompleted, AssistantGenerationStarted,
                                AssistantGenerationFinished, AssistantSpeechActivity, AssistantPlaybackEvidence)):
            return self._speech(event)
        if isinstance(payload, UserInterruption) and payload.stage == VoiceInterruptionStage.CONFIRMED:
            speech = self._find_speech(event.correlation)
            if speech is None or speech.state in (VoiceSpeechState.COMPLETE, VoiceSpeechState.UNSPOKEN):
                return {}
            updated = replace(speech, state=VoiceSpeechState.INTERRUPTED if speech.played_ms else VoiceSpeechState.CANCELLED)
            return {"speeches": tuple(updated if s is speech else s for s in self.snapshot.speeches)}
        # VAD, delegation and usage are evidence for their policy/lifecycle owner.
        # None commits a transcript, starts tasks, authorizes actions, or speaks.
        return {}

    def _user(self, event: VoiceEvent) -> dict:
        payload = event.payload
        existing = next((u for u in self.snapshot.users if (u.correlation.session_id, u.transcript_id) == (event.correlation.session_id, payload.transcript_id)), None)
        if existing:
            if payload.revision <= existing.revision:
                raise _Rejected("voice_state_stale_revision", VoiceStateDisposition.STALE)
            if existing.committed:
                raise _Rejected("voice_state_turn_already_committed")
            correlation = self._merge_correlation(existing.correlation, event.correlation)
        else:
            correlation = event.correlation
        committed = isinstance(payload, UserTranscriptCommitted)
        text = ((existing.text if existing else "") + payload.delta) if isinstance(payload, UserTranscriptDelta) else payload.text
        record = VoiceUserRecord(correlation, payload.transcript_id, payload.revision, text, committed,
                                 payload.source if committed else None)
        users = tuple(record if u is existing else u for u in self.snapshot.users) if existing else (*self.snapshot.users, record)
        return {"users": users}

    def _find_speech(self, correlation: VoiceCorrelation) -> VoiceSpeechRecord | None:
        matches = [s for s in self.snapshot.speeches if s.correlation.session_id == correlation.session_id and (
            correlation.speech_id is not None and s.correlation.speech_id == correlation.speech_id
            or correlation.output_id is not None and s.correlation.output_id == correlation.output_id
            or correlation.provider_output_id is not None and s.correlation.provider_output_id == correlation.provider_output_id
        )]
        if len(matches) > 1:
            raise _Rejected("voice_state_output_identity_conflict")
        return matches[0] if matches else None

    @staticmethod
    def _merge_correlation(old: VoiceCorrelation, new: VoiceCorrelation) -> VoiceCorrelation:
        values = {}
        for item in fields(VoiceCorrelation):
            before, after = getattr(old, item.name), getattr(new, item.name)
            if before is not None and after is not None and before != after:
                raise _Rejected("voice_state_correlation_conflict")
            values[item.name] = before if before is not None else after
        return VoiceCorrelation(**values)

    def _speech(self, event: VoiceEvent) -> dict:
        payload = event.payload
        previous = self._find_speech(event.correlation)
        no_active_evidence = self.snapshot.lifecycle in (FrontendState.STOPPING, FrontendState.STOPPED, FrontendState.UNKNOWN_REAP_REQUIRED)
        no_active_evidence |= isinstance(payload, AssistantPlaybackEvidence)
        no_active_evidence |= isinstance(payload, AssistantSpeechActivity) and payload.phase == VoiceSpeechPhase.STOPPED
        initial_state = VoiceSpeechState.UNKNOWN if no_active_evidence else VoiceSpeechState.GENERATING
        speech = previous or VoiceSpeechRecord(event.correlation, state=initial_state)
        item_ids = tuple(dict.fromkeys((*speech.provider_item_ids,
                                       *((speech.correlation.provider_item_id,) if speech.correlation.provider_item_id else ()),
                                       *((event.correlation.provider_item_id,) if event.correlation.provider_item_id else ()))))
        aggregate_item = item_ids[0] if len(item_ids) == 1 else None
        merged = self._merge_correlation(replace(speech.correlation, provider_item_id=None),
                                         replace(event.correlation, provider_item_id=None))
        speech = replace(speech, correlation=replace(merged, provider_item_id=aggregate_item), provider_item_ids=item_ids)
        cancelled = speech.state in (VoiceSpeechState.CANCELLED, VoiceSpeechState.INTERRUPTED)
        if isinstance(payload, AssistantAudioChunk):
            received_ms = len(payload.audio.pcm) * 1000 / (payload.audio.format.sample_rate_hz * 2)
            speech = replace(speech, received_audio_ms=speech.received_audio_ms + received_ms)
        elif isinstance(payload, AssistantAudioReceived):
            if payload.received_ms < speech.received_audio_ms:
                raise _Rejected("voice_state_audio_regression", VoiceStateDisposition.STALE)
            speech = replace(speech, received_audio_ms=payload.received_ms)
        elif isinstance(payload, (AssistantTranscriptDelta, AssistantTranscriptCompleted)):
            part = next((p for p in speech.generated if p.transcript_id == payload.transcript_id), None)
            if part and part.completed:
                raise _Rejected("voice_state_generated_already_completed", VoiceStateDisposition.STALE)
            text = payload.text if isinstance(payload, AssistantTranscriptCompleted) else (part.text if part else "") + payload.delta
            if part is not None and part.part is not None and payload.part != part.part:
                raise _Rejected("voice_state_generated_part_conflict")
            updated = VoiceGeneratedText(payload.transcript_id, text, isinstance(payload, AssistantTranscriptCompleted), payload.part)
            speech = replace(speech, generated=tuple(updated if p is part else p for p in speech.generated) if part else (*speech.generated, updated))
        elif isinstance(payload, AssistantGenerationStarted):
            if not cancelled and not speech.local_active and speech.state != VoiceSpeechState.COMPLETE:
                speech = replace(speech, state=VoiceSpeechState.GENERATING)
        elif isinstance(payload, AssistantGenerationFinished):
            speech = replace(speech, generation_status=payload.status)
            if payload.status == VoiceGenerationStatus.COMPLETED and not speech.received_audio_ms and not speech.played_ms and not speech.local_active and not cancelled:
                speech = replace(speech, state=VoiceSpeechState.UNSPOKEN)
            if payload.status in (VoiceGenerationStatus.CANCELLED, VoiceGenerationStatus.FAILED, VoiceGenerationStatus.INCOMPLETE) and speech.state != VoiceSpeechState.COMPLETE:
                speech = replace(speech, state=VoiceSpeechState.INTERRUPTED if speech.played_ms else VoiceSpeechState.CANCELLED)
        elif isinstance(payload, AssistantSpeechActivity):
            if payload.phase == VoiceSpeechPhase.STARTED and not cancelled and speech.state != VoiceSpeechState.COMPLETE:
                speech = replace(speech, state=VoiceSpeechState.PLAYING, local_active=True)
            elif payload.phase == VoiceSpeechPhase.STOPPED:
                speech = replace(speech, local_active=False)
        elif isinstance(payload, AssistantPlaybackEvidence):
            if speech.played_ms is not None and ((payload.played_ms is None and speech.played_ms > 0) or (payload.played_ms is not None and payload.played_ms < speech.played_ms)):
                raise _Rejected("voice_state_playback_regression", VoiceStateDisposition.STALE)
            if speech.playback_status == VoicePlaybackStatus.COMPLETE and payload.status != VoicePlaybackStatus.COMPLETE:
                raise _Rejected("voice_state_playback_regression", VoiceStateDisposition.STALE)
            if speech.confirmed_text and payload.confirmed_text is not None and not payload.confirmed_text.startswith(speech.confirmed_text):
                raise _Rejected("voice_state_confirmation_regression", VoiceStateDisposition.STALE)
            # Confirmation is cumulative independently aligned text, never a
            # string delta. Unknown later alignment retains the known prefix.
            text = payload.confirmed_text if payload.confirmed_text is not None else speech.confirmed_text
            state = speech.state
            if cancelled and payload.played_ms:
                state = VoiceSpeechState.INTERRUPTED
            if payload.status == VoicePlaybackStatus.COMPLETE and not cancelled:
                state = VoiceSpeechState.COMPLETE
            elif payload.status == VoicePlaybackStatus.UNKNOWN and not cancelled:
                state = VoiceSpeechState.UNKNOWN
            speech = replace(speech, playback_status=payload.status, played_ms=payload.played_ms,
                             confirmed_text=text, state=state,
                             first_played_order=speech.first_played_order or (self.snapshot.revision + 1 if payload.played_ms else None),
                             local_active=False if payload.status == VoicePlaybackStatus.COMPLETE else speech.local_active)
        speeches = tuple(speech if s is previous else s for s in self.snapshot.speeches) if previous else (*self.snapshot.speeches, speech)
        return {"speeches": speeches}

    def _commit(self, changes: dict, event: VoiceEvent | None = None) -> None:
        values = {"users": self.snapshot.users, "turns": self.snapshot.turns,
                  "speeches": self.snapshot.speeches, "tasks": self.snapshot.tasks, **changes}
        self._prune(values)
        if event is not None:
            seen = (*self.snapshot.seen_events, SeenVoiceEvent(event.event_id, event.sequence))
            floor = self.snapshot.sequence_floor
            if len(seen) > self._limits["seen_events"]:
                floor = max(floor, seen[0].sequence)
                seen = tuple(item for item in seen[1:] if item.sequence > floor)
            values.update(seen_events=seen, sequence_floor=floor, last_observed_at=event.observation.observed_at)
        self._snapshot = replace(self.snapshot, **values, revision=self.snapshot.revision + 1)

    def _prune(self, values: dict) -> None:
        def trim(name: str, limit: int, removable) -> None:
            items = list(values[name])
            while len(items) > limit:
                index = next((i for i, item in enumerate(items) if removable(item)), None)
                if index is None:
                    raise _Rejected("voice_state_capacity", VoiceStateDisposition.CAPACITY)
                items.pop(index)
            values[name] = tuple(items)

        trim("tasks", self._limits["tasks"], lambda t: t.status.is_terminal)
        trim("speeches", self._limits["speeches"], lambda s: not s.active)
        pinned = {t.source_turn_id for t in values["tasks"]}
        pinned.update(s.correlation.turn_id for s in values["speeches"] if s.active)
        pinned.add(values.get("active_turn_id", self.snapshot.active_turn_id))
        pinned.discard(None)  # No turn identity pins nothing; GPT-Live never assigns one.
        newest_user = values["users"][-1] if values["users"] else None
        # An uncommitted record superseded by a later one in the same session is an
        # abandoned provisional epoch: GPT-Live never commits, and trimming only
        # ever drops the oldest removable record once the bound is exceeded.
        trim("users", self._limits["users"], lambda u: u.correlation.turn_id not in pinned and (
            u.committed or u.correlation.session_id != self.snapshot.current_session_id or u is not newest_user))
        pinned.update(u.correlation.turn_id for u in values["users"])
        trim("turns", MAX_TURNS, lambda t: t.turn_id not in pinned)

    def recent_context(self, *, limit: int = 12) -> VoiceContext:
        """Bounded provider seed: committed user text + independently heard words.

        Partial text is included only when words were independently confirmed;
        intended/generated/unknown words and task results are never assistant history.
        """
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("context limit must be between 1 and 128")
        turns = {t.turn_id: t for t in self.snapshot.turns}
        ordered: list[str] = []
        def visit(turn_id: str) -> None:
            if turn_id in ordered or turn_id not in turns:
                return
            parent = turns[turn_id].previous_turn_id
            if parent is not None:
                visit(parent)
            ordered.append(turn_id)
        for turn in self.snapshot.turns:
            visit(turn.turn_id)
        timeline = []
        for index, turn_id in enumerate(ordered):
            timeline.extend(((index, 0, 0), VoiceContextMessage(VoiceContextRole.USER, u.text)) for u in self.snapshot.users if u.committed and u.correlation.turn_id == turn_id)
        for speech in self.snapshot.speeches:
            if not speech.confirmed_text:
                continue
            # A late answer to A may play after user B. Heard chronology must
            # reflect that observation, not regroup speech under its source turn.
            index = max((i for i, turn_id in enumerate(ordered) if turns[turn_id].observation_order <= speech.first_played_order), default=-1)
            timeline.append(((index, 1, speech.first_played_order), VoiceContextMessage(VoiceContextRole.ASSISTANT, speech.confirmed_text)))
        messages = [message for _, message in sorted(timeline, key=lambda item: item[0])]
        selected = []
        size = 0
        for message in reversed(messages):
            if len(selected) == limit or size + len(message.text) > 32768:
                break
            selected.append(message)
            size += len(message.text)
        return VoiceContext(self.snapshot.revision, tuple(reversed(selected)))

    def _result(self, disposition: VoiceStateDisposition, code: str, event: VoiceEvent | None = None, *, log: bool = True) -> VoiceStateResult:
        if log:
            rejected = disposition in (VoiceStateDisposition.REJECTED, VoiceStateDisposition.CAPACITY)
            self._diagnose("voice.state.rejected" if rejected else "voice.state.updated", code, "warning" if rejected else "info", event)
        return VoiceStateResult(disposition, code, self.snapshot.revision)

    def _diagnose(self, kind: str, code: str, level: str, event: VoiceEvent | None) -> None:
        if self._diagnostics is None:
            return
        data = {"code": code, "conversation_id": self.snapshot.conversation_id,
                "session_id": self.snapshot.current_session_id, "revision": self.snapshot.revision}
        if event:
            try:
                correlation_valid(event.correlation)
                state_id(event.event_id, "event_id")
            except (ValueError, TypeError):
                # Invalid identity is not safe diagnostic data; keep only the
                # trusted state identity and stable rejection code.
                event = None
        if event:
            data.update(event_id=event.event_id, turn_id=event.correlation.turn_id,
                        task_id=event.correlation.task_id, speech_id=event.correlation.speech_id)
        try:
            self._diagnostics.emit(kind, "Canonical voice state observation", level=level, data=data)
        except Exception:
            # A failed diagnostic sink must not roll back applied evidence or
            # trigger duplicate execution. Failure remains countable to the host.
            self.diagnostic_failures += 1
