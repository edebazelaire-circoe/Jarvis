# 02 - Architecture Specification

## 1. Responsibility split

### Realtime surface

Owns:

- microphone audio transport;
- server/manual VAD events;
- streaming transcription observations;
- output audio transport;
- immediate playback interruption;
- very small conversational reflexes;
- faithful rendering of brain speech requests.

Must not own:

- durable task state;
- operational truth;
- final interpretation of user intent;
- long-running tool execution;
- task success/failure claims;
- hidden reasoning persistence.

### Jarvis Core brain

Owns:

- authoritative completed user turns;
- conversation intent and revisions;
- structured working state;
- planning at the public/task-state level;
- job/tool dispatch;
- task cancellation decisions;
- public progress, question, and result wording;
- speech requests;
- correlation between conversation, work, and speech.

### Brain backend

The backend is the strong model/provider used by `BrainOrchestrator`. Initially this can wrap the existing Control Center Claude agent. Core depends only on a provider-neutral `BrainBackend` port.

## 2. Proposed domain contracts

Names may be adjusted to match project conventions, but semantics must remain stable.

```python
class SpeechKind(StrEnum):
    ACK = "ack"
    PROGRESS = "progress"
    QUESTION = "question"
    RESULT = "result"
    ERROR = "error"

class SpeechPriority(IntEnum):
    LOW = 10
    NORMAL = 20
    HIGH = 30
    IMMEDIATE = 40

@dataclass(frozen=True, slots=True)
class SpeechRequest:
    id: str
    conversation_id: str
    text: str
    kind: SpeechKind
    priority: SpeechPriority
    correlation_id: str
    work_id: str | None = None
    supersedes_key: str | None = None
    interruptible: bool = True
    expires_at: datetime | None = None
    provenance: str = "brain"
```

The exact integer implementation of priority is optional; ordering semantics are not.

Suggested safe working state:

```python
@dataclass(frozen=True, slots=True)
class BrainWorkingState:
    conversation_id: str
    revision: int
    current_user_intent: str
    conversation_goal: str
    active_work_ids: tuple[str, ...]
    known_public_facts: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    completed_work_ids: tuple[str, ...]
    updated_at: datetime
```

Do not add `thoughts`, `reasoning`, hidden scratchpad, or provider chain-of-thought fields.

## 3. Brain backend contract

A useful first contract is event-oriented rather than one final string:

```python
class BrainBackend(Protocol):
    async def run_turn(
        self,
        turn: BrainTurnInput,
        state: BrainWorkingState,
        emit: BrainEventSink,
    ) -> BrainTurnResult: ...
```

If the current Claude backend cannot stream immediately, the adapter may initially emit coarse `accepted` and final events. The Core contract must still support later progress without changing Voice again.

`BrainOrchestrator` owns provider-independent validation, state transitions, deduplication, and speech publication. The provider adapter does not publish directly onto `CoreEventBus`.

## 4. Authoritative turn ingress

Add one service/API operation that:

1. validates the conversation;
2. deduplicates by provider item id and/or correlation id;
3. persists the user turn;
4. marks it authoritative/final in metadata;
5. emits `brain.turn.accepted`;
6. starts or updates brain work asynchronously;
7. returns immediately with an acceptance object rather than waiting for the strong backend.

Example request shape:

```json
{
  "content": "Only look at Paul's emails, actually.",
  "correlation_id": "...",
  "provider_item_id": "item_...",
  "source": "realtime",
  "interrupted_speech_id": "speech_..."
}
```

The server endpoint should be nested under the conversation, for example:

`POST /v1/conversations/{conversation_id}/brain-turns`

Exact naming is provisional, but there must be a single authoritative path to persistence plus brain dispatch.

## 5. Event contract

Core events should remain `ProtocolEnvelope` instances.

Minimum new event set:

- `brain.turn.accepted`
- `brain.state.updated`
- `brain.speech.requested`
- `brain.work.started`
- `brain.work.progress`
- `brain.work.completed`
- `brain.work.failed`
- `brain.intent.revised`

Voice-originated interruption may be posted to Core as turn metadata rather than a standalone event. If a standalone event is useful, use `voice.user.interrupted` with a conversation id and speech id, not provider-specific JSON.

Existing `job.completed`, `job.failed`, and `job.interrupted` remain valid infrastructure events. Avoid duplicating job truth under two incompatible status systems.

See `docs/05-event-contracts.md` for payload guidance.

## 6. Speech scheduler

`SpeechScheduler` belongs in the Voice process because it owns the currently active Realtime session and audible output.

It consumes `brain.speech.requested` events from `LocalCoreClient.events()` and applies:

- conversation filtering;
- priority ordering;
- expiration/TTL;
- supersession of stale progress;
- one active brain speech output at a time;
- interruption cancellation;
- delivery status telemetry.

A final result should normally supersede pending progress for the same work id. A question should preempt low-priority progress. Old progress that was queued before a user intent revision should be dropped.

## 7. Realtime adapter controls

Extend the provider-neutral `RealtimeSession` surface with semantic methods, not raw OpenAI JSON.

Required capabilities:

- send microphone audio;
- request/finish an input turn when in manual mode;
- faithfully speak a `SpeechRequest` without fabricating a user turn;
- cancel active output;
- truncate conversation audio to the amount actually played when required by WebSocket interruption semantics;
- expose transcript deltas and completed transcripts with provider item ids;
- expose response/output ids needed for interruption bookkeeping;
- close cleanly.

A candidate contract may use:

```python
async def speak(self, request: SpeechRequest) -> str: ...  # returns provider response/output id
async def cancel_output(self, playback: PlaybackCursor | None = None) -> None: ...
```

Do not leak OpenAI event dictionaries into Core.

## 8. Realtime speech injection

The current `send_context(text)` creates a fake role=`user` message and then requests a response. Brain speech must not use this path.

The adapter should ask Realtime to speak the brain-provided text faithfully, using a response-level instruction/input mode that does not rewrite it as a user message. The adapter must associate a local `speech_id` or correlation id with the provider response for interruption and telemetry.

## 9. Surface reflex policy

Allowed autonomous surface behavior:

- short acknowledgement: "Yes.", "I am on it.";
- short turn-taking/backchannel;
- hearing repair: "I did not catch the last part.";
- a minimal clarification only when it is strictly about what was heard and does not alter task truth.

Forbidden autonomous behavior:

- "I found 12 files" unless brain said so;
- "The task is complete" unless brain said so;
- claiming a file/email/calendar operation happened;
- substantive factual answers that the brain has not supplied in async-brain mode;
- deciding to cancel/replace a background job;
- inventing progress to fill silence.

The fastest safe surface acknowledgement is preferable to fake progress.

## 10. Continuous LIVE lifecycle

Keep coarse `VoiceLifecycleState` values. In continuous mode:

- Wake -> CONNECTING -> ACTIVE.
- ACTIVE persists across multiple input commits and response completions.
- `response.done` updates activity/visual projection but does not call `mute()`.
- `Jarvis Mute` -> BACKGROUND.
- useful inactivity -> BACKGROUND.
- unrecoverable provider failure -> ERROR -> cleanup/BACKGROUND according to existing recovery policy.

Listening, speaking, and brain-working can overlap conceptually. Do not encode them as mutually exclusive lifecycle states.

## 11. Microphone and echo constraint

The current auto-turn path closes microphone input as soon as the provider commits a turn. Continuous conversation requires keeping or reopening microphone capture.

This introduces a real acoustic echo risk when speakers feed the microphone. The first implementation must:

- keep the concurrency behavior safe;
- stop local playback immediately on detected user speech;
- test with headphones and workstation speakers;
- retain a legacy/half-duplex fallback mode if acoustic behavior is unacceptable.

Do not claim software echo cancellation unless it is actually implemented and measured.

## 12. Barge-in sequence for current WebSocket topology

When user speech starts while Jarvis is speaking:

1. mark the current speech request interrupted locally;
2. stop/abort speaker playback as quickly as the audio backend safely permits;
3. request Realtime output cancellation if still generating;
4. truncate the provider conversation item to the amount actually played when the provider requires client-side truncation;
5. continue receiving microphone input;
6. on final transcript, submit an authoritative brain turn with interruption metadata;
7. brain revises intent/state;
8. stale queued speech is superseded/dropped;
9. jobs continue unless the brain explicitly cancels them.

## 13. Job and progress model

Reuse `JobService` for long-running executable work. Extend it with a provider-neutral progress emission seam instead of creating an unrelated task runner.

Possible approach:

```python
class JobProgressSink(Protocol):
    async def emit(self, job_id: str, progress: JobProgress) -> None: ...
```

The brain converts work progress into user-facing speech only when useful. Workers must not directly decide what Jarvis says.

## 14. Persistence

Persist:

- authoritative user/assistant turns;
- job lifecycle;
- high-level structured working state required for restart/continuation;
- final/public results;
- identifiers required for deduplication.

Do not persist:

- raw microphone audio;
- raw chain-of-thought;
- provider-only ephemeral event dumps as domain state.

## 15. Assistant-turn provenance

Persist assistant speech with metadata identifying whether it came from:

- `surface.reflex`;
- `brain.speech`;
- `system.notification`;
- other explicit source.

Include `speech_id`, `work_id`, and correlation id when available. This lets the brain know what the user actually heard and prevents duplicated progress statements.

## 16. Future WebRTC sideband seam

OpenAI's Realtime sideband architecture can later support a browser/WebRTC audio client plus a server control connection to the same session. This handoff does not require that migration. Keep semantic Realtime ports provider/transport-neutral so it can be introduced without moving brain ownership again.
