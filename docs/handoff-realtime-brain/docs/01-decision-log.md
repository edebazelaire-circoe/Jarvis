# 01 - Decision Log

## Decision 01 - Core owns the brain

**Status:** locked

**Decision:** The authoritative `BrainOrchestrator` is a long-lived Core service, not a member of the Voice runtime.

**Rationale:** Voice can mute, reconnect, or crash without destroying durable work. Core already owns conversations, jobs, state, and an async event bus.

**Implications:** Voice submits turns over the local protocol and receives brain speech/work events through Core.

**Tests / enforcement:** Core unit tests run with fake brain backends and no microphone/OpenAI dependency.

## Decision 02 - Realtime is a surface, not the authority

**Status:** locked

**Decision:** Realtime handles audio, turn-taking, barge-in signals, and strict reflex conversation. It does not own task truth or operational claims.

**Rationale:** This keeps latency low without allowing a small surface model to hallucinate work state.

**Implications:** Prompts and tests must explicitly prevent unverified task-progress claims.

**Tests / enforcement:** Reflex-policy tests and provenance metadata on assistant turns.

## Decision 03 - One brain first

**Status:** locked

**Decision:** Implement one orchestrator/brain in this project slice.

**Rationale:** Multi-agent execution adds scheduling, ownership, cancellation, and merge complexity that is not required to prove the architecture.

**Implications:** Contracts include correlation/work identifiers but no multi-agent scheduler is implemented.

**Tests / enforcement:** No task should add agent-pool logic unless the task plan is explicitly revised.

## Decision 04 - Reuse `ProtocolEnvelope` and `CoreEventBus`

**Status:** locked

**Decision:** Brain events use the existing provider-neutral `ProtocolEnvelope` and existing Core event bus.

**Rationale:** The repository already has correlation and conversation identifiers plus an event WebSocket.

**Implications:** Do not invent a parallel event framework in Voice.

**Tests / enforcement:** Protocol/event tests verify brain event serialization through `/v1/events`.

## Decision 05 - Reuse `/v1/events` for Core -> Voice

**Status:** locked

**Decision:** Voice subscribes to Core brain events through the current `LocalCoreClient.events()` WebSocket.

**Rationale:** It is already authenticated, loopback-only, versioned, and asynchronous.

**Implications:** New event types may be added, but a second IPC server is not needed.

## Decision 06 - Explicit brain-turn ingress

**Status:** locked

**Decision:** Add a Core API/service entrypoint that atomically persists an authoritative completed user turn and dispatches it to the brain once.

**Rationale:** The current Voice path appends turns separately; adding brain dispatch beside it would create double-write or race risks.

**Implications:** Migration must remove the old duplicate append path for brain-routed turns.

## Decision 07 - Completed transcript is authoritative

**Status:** locked

**Decision:** Input transcript deltas may be observed as tentative context, but irreversible work/tools begin only from a completed addressed user turn.

**Rationale:** Streaming transcription can revise words and must not trigger unsafe duplicate work.

**Implications:** Partial input support is an optimization seam, not an execution trigger.

## Decision 08 - Continuous LIVE session

**Status:** locked

**Decision:** `response.done` no longer implies `mute()` in continuous mode.

**Rationale:** A LIVE conversation must span multiple user/assistant turns.

**Implications:** BACKGROUND is entered only by explicit mute/manual stop, useful inactivity timeout, or unrecoverable session failure.

## Decision 09 - Lifecycle and activity are separate

**Status:** locked

**Decision:** Keep coarse lifecycle states such as BACKGROUND/CONNECTING/ACTIVE/ERROR, while listening/speaking/working are independent activity projections rather than exclusive lifecycle states.

**Rationale:** The system may be listening while brain work is active, or speaking while jobs continue.

## Decision 10 - Useful activity excludes ambient audio

**Status:** locked

**Decision:** Ambient noise and background speech do not reset the LIVE timeout.

**Rationale:** The user previously required inactivity to mean no meaningful order/interaction, not silence in the room.

**Implications:** Only addressed turns and meaningful Jarvis work/speech events count as useful activity.

## Decision 11 - `Jarvis Mute` never cancels Core work by default

**Status:** locked

**Decision:** Mute closes/suspends the Realtime voice surface and returns wake-word handling, while Core jobs continue.

**Rationale:** Mute is a voice-state command, not a task-cancellation command.

## Decision 12 - No raw chain-of-thought persistence

**Status:** locked

**Decision:** Store structured public working state, not hidden reasoning traces.

**Rationale:** The orchestrator needs durable state, but raw hidden reasoning is unnecessary and creates coupling and privacy risk.

## Decision 13 - Brain speaks through typed speech requests

**Status:** locked

**Decision:** Core emits `SpeechRequest` events containing complete public text plus priority/provenance metadata.

**Rationale:** Realtime should render/speak brain output, not reinterpret operational truth.

**Implications:** Replace the use of `send_context()` as a fake user-message injection for brain speech.

## Decision 14 - Strict surface reflex policy

**Status:** locked

**Decision:** Realtime may autonomously produce only short acknowledgements/backchannels and simple hearing clarification. It must not invent progress, results, or success/failure.

**Rationale:** The brain owns truth and intent.

## Decision 15 - User interruption stops speech, not work

**Status:** locked

**Decision:** Barge-in immediately stops audible output and synchronizes the Realtime conversation history, but active Core jobs are not cancelled automatically.

**Rationale:** The user's new turn may merely refine or ask about ongoing work.

## Decision 16 - Brain decides intent revision/cancellation

**Status:** locked

**Decision:** The completed interruption turn is authoritative input to the brain; the brain decides whether work is revised, superseded, cancelled, or retained.

## Decision 17 - WebSocket first; sideband later

**Status:** locked

**Decision:** Keep the current direct OpenAI Realtime WebSocket topology for the first implementation.

**Rationale:** Jarvis is already a local server-side Python client, so OpenAI sideband is not required to create a server-control path now.

**Implications:** Adapter contracts should remain transport-neutral enough to support WebRTC plus sideband later.

## Decision 18 - Model ids remain configuration

**Status:** locked

**Decision:** Do not hard-code the surface model into business logic. `gpt-realtime-2.1-mini` is a recommended low-latency surface configuration, not a domain constant.

**Rationale:** Provider model availability changes faster than architecture.

## Decision 19 - Existing Claude integration becomes a backend adapter

**Status:** locked

**Decision:** The existing local Claude path is initially reused behind a `BrainBackend` port. Voice must stop owning direct `ClaudeGateway` orchestration.

**Rationale:** This preserves current capability while putting orchestration ownership in the correct process.

## Decision 20 - Roll out behind a compatibility mode

**Status:** locked

**Decision:** Keep a legacy voice path or feature switch until continuous async brain mode passes automated and workstation acceptance gates.

**Rationale:** Audio interruption and echo behavior are hardware-sensitive; migration must be reversible.

---

# Orchestration decisions (Task 00, added 2026-09-09)

These decisions were taken by the implementation orchestrator after verifying the
handoff snapshot against the live repository. They resolve divergences the handoff
could not know about. None of them contradicts Decisions 01-20; where a locked
decision is refined, the refinement is stated explicitly.

## Decision 21 - Gemini Live stays on the legacy path

**Status:** locked by orchestrator

**Context:** After the handoff snapshot, the repository gained a second
`RealtimeSession` implementation, `jarvis/adapters/gemini_live.py`, plus a voice
stack registry `jarvis/runtime/voice_stack.py`. The handoff assumes a single
OpenAI adapter.

**Decision:** `JARVIS_VOICE_ARCH=continuous_brain` is supported only by a voice
stack that implements the new semantic output-control contract. Gemini Live keeps
working unchanged on the legacy path and is out of scope for Tasks 04, 06, 08, 09.

**Rationale:** Reaching parity would roughly double the cost of four tasks for a
surface that is not the target of this architecture. Decision 20 already requires a
reversible rollout with a legacy mode; leaving Gemini there is the same mechanism.

**Implications:** Selecting Gemini while `continuous_brain` is requested must fail
loudly at configuration time, not silently degrade. Gemini can adopt the control
port later without touching Core.

## Decision 22 - Do not widen `RealtimeSession`; add a separate control port

**Status:** locked by orchestrator

**Decision:** The semantic output controls required by continuous mode
(`speak`, `cancel_output`, `truncate`) go into a new, separate provider-neutral
port, not into the existing `RealtimeSession` Protocol.

**Rationale:** `RealtimeSession` has two implementations plus at least four test
fakes. Widening it breaks all of them at once and forces Gemini into scope,
contradicting Decision 21. A separate port lets a stack advertise the capability.

**Implications:** Runtime must be able to ask whether the active session supports
brain output control, and refuse continuous mode when it does not.

## Decision 23 - `BrainBackend` targets the agent-agnostic Control Center endpoint

**Status:** locked by orchestrator

**Context:** Decision 19 assumed "the existing local Claude path". The repository
now selects between `ClaudeLocalAgent` and `CodexLocalAgent` inside the Control
Center process, behind one HTTP route `POST /api/agent/ask`.

**Decision:** The first `BrainBackend` adapter calls `/api/agent/ask` and stays
agent-agnostic. Claude/Codex selection remains a Control Center concern. The
adapter lives in `jarvis/adapters/`, never in `jarvis/core/`, and is injected at the
Core composition root.

**Rationale:** This honours Decision 19's intent (reuse the existing capability,
move ownership, not the provider) while absorbing the Claude/Codex split for free.
It also keeps `aiohttp` out of Core.

**Implications:** `jarvis/runtime/claude_gateway.py` is the reference for the HTTP
call, but Voice must stop calling it directly (Task 07). Do not delete it before
the legacy path is retired.

## Decision 24 - Deduplicate on `correlation_id`; provider item id is optional

**Status:** locked by orchestrator

**Context:** Decision 06 and Task 03 assume deduplication by provider item id.
Today only `realtime.input_committed` carries an `item_id`, and Gemini emits none.

**Decision:** `correlation_id` is the mandatory deduplication key for authoritative
brain turns. `provider_item_id` is an optional secondary key used when present.

**Rationale:** Keeps Task 03 executable without waiting on Task 04, and keeps the
contract honest for surfaces that cannot supply provider ids.

## Decision 25 - Event-bus subscriber eviction must be observable

**Status:** locked by orchestrator

**Context:** `CoreEventBus.publish()` silently unsubscribes any subscriber whose
bounded queue is full. With `brain.*` events this would drop the voice surface
without any trace.

**Decision:** The bus stays bounded (per open question 6). Eviction must emit a
structured journal event so it is diagnosable, and the speech consumer must
reconnect. Do not make the bus unbounded and do not add a second bus.

## Decision 26 - Strengthen the architecture gate before injecting any backend

**Status:** locked by orchestrator

**Context:** `tests/unit/test_v2_architecture.py` forbids only
`jarvis.adapters.google_*` and `jarvis.adapters.openai_realtime` inside
`jarvis/core`. It does not block `aiohttp`, `openai`, `jarvis.adapters.gemini_live`,
or `jarvis.runtime.*`.

**Decision:** The gate is widened before any brain backend is wired into Core.

## Decision 27 - `coding-guideline` observability maps onto `RuntimeJournal`

**Status:** locked by orchestrator

**Context:** The mandated `/coding-guideline` skill lives in `~/.codex/skills/`, not
`~/ai/skills/`, and requires a "LogBroker" and `python -m observability.cli` that do
not exist in this repository.

**Decision:** The skill's workflow, question protocol, and quality gates apply. Its
observability contract is satisfied through `jarvis/runtime/journal.py`
(`RuntimeJournal`, structured `kind`/`level`/`data` events). The `observability.cli`
commands and `docs/legacy/*.md` requirements are not applicable unless a temporary
shim is actually introduced.

## Plan adjustment - Task 09 needs a playback cursor

Task 09 assumes truncation "to the amount actually played". No playback position
exists today: `SoundDeviceRealtimeAudio._write_output` writes 100 ms blocks under a
lock and tracks nothing, and stopping is a best-effort `abort()` with a documented
PortAudio access-violation risk. Task 09 must therefore first add playback-position
accounting, or the orchestrator splits it into 09a (cursor) and 09b (barge-in).

## Decision 28 - Inject `BrainBackend` as a parameter, with an in-core null default

**Status:** locked by orchestrator

**Context:** The widened architecture gate (Decision 26) records one pre-existing
violation: `jarvis/core/v2_app.py` is a composition root that lives inside Core and
imports four concrete adapters. It is covered by a named, exhaustive exception list,
not a blanket waiver. Moving the composition root out of Core would be a non-trivial
refactor that no task in this handoff asks for.

**Decision:** Do not refactor the composition root now, and do not extend the gate
exception list. `BrainBackend` is injected into `JarvisCoreApplication.__init__` as
an optional keyword parameter, exactly like `calendar_backend` and `drive_backend`.
The real HTTP adapter (Decision 23) is constructed in `jarvis/app.py` and passed in.
The default used for headless startup and tests is a **null/no-op backend defined
inside Core**, not an adapter import.

**Rationale:** This keeps the gate exception frozen at its current four entries, so
the anti-loosening test stays meaningful. A null object is not a provider adapter;
placing it in Core is correct layering, not a workaround.

**Implications:** If a future task cannot avoid importing a new adapter into
`jarvis/core/v2_app.py`, that is the signal to do the composition-root refactor
deliberately, as its own task - not to widen the exception list.

## Decision 29 - In-memory deduplication is sufficient; document the crash window

**Status:** locked by orchestrator

**Context:** Task 02 raised that `BrainOrchestrator` keeps its deduplication index in
memory. A Core restart can therefore re-dispatch a turn that the surface replays,
even though the turn itself is persisted correctly.

**Decision:** Do not add restart-persistent deduplication. Task 03 must document the
crash window explicitly - in the endpoint docstring and in the task report - rather
than imply a guarantee that does not exist.

**Rationale:** Task 03's own handoff notes already settle this: "Avoid a transaction
illusion if the existing repository cannot atomically combine persistence and task
launch. Guarantee logical idempotency and document the crash window instead of
hiding it." Rebuilding the index from `state.list_turns` at startup is a real option,
but no task asks for it and it trades a narrow, documented window for new startup
cost and a new failure mode.

**Revisit when:** integration scenarios in Task 11 show a realistic replay path that
crosses a Core restart, or the surface gains automatic retry on reconnect.

## Decision 30 - The duplicate append path must be removed mechanically, not by convention

**Status:** locked by orchestrator

**Context:** Task 03 delivered `POST /v1/conversations/{id}/brain-turns` beside the
existing `POST /v1/conversations/{id}/turns`. Nothing prevents Voice from calling
both for the same user turn, which would persist it twice. Task 03 could only
document the exclusivity, since Voice does not call either path yet.

**Decision:** Decision 06 already requires that "migration must remove the old
duplicate append path for brain-routed turns". Task 07 must satisfy this
mechanically: in `continuous_brain` mode, the Voice bridge must have no reachable
code path that appends a user turn through `append_turn()`. Add a test that fails if
one reappears - a documentation-only guarantee is not acceptable for a double-write
risk.

**Note:** `append_turn()` remains valid for legacy mode and for assistant turns with
provenance metadata (spec section 15). The exclusivity applies to authoritative user
turns routed to the brain.

## Decision 31 - No event replay after reconnect; rehydrate from Core state

**Status:** locked by orchestrator, per open question 7

**Context:** Tasks 02 and 03 both flagged that `/v1/events` is live-only: events
published while a subscriber is disconnected are lost, and an evicted subscriber sees
only silence rather than an error.

**Decision:** Do not build a durable event log now. The speech consumer in Task 08
must (a) detect the silent stream close and resubscribe, and (b) expire stale speech
rather than replay it. `brain.state.updated` carries a monotonic revision, so a
consumer can detect that it missed something and rehydrate from Core state instead of
replaying speech that is no longer true.

**Rationale:** Open question 7 already settles this: "Initial behavior should expire
stale speech and rely on Core state/notifications after reconnect. A durable event log
is a later enhancement unless tests prove it is required now." Replaying stale
progress after a gap is worse than saying nothing.

## Decision 32 - Brain work in flight counts as useful activity

**Status:** locked by orchestrator

**Context:** Task 07 moved long work into Core. Voice's inactivity timeout defaults to
90 s, so a brain turn that takes three minutes would see the voice session drop to
BACKGROUND while the work is still running - the work would survive, but the user
would have to wake Jarvis to hear the answer.

**Decision:** Brain lifecycle events (`brain.turn.accepted`, work started/progress,
speech requested) count as useful activity and rearm the inactivity timeout. The
timeout still runs from the **last** brain event, so a hung or silent brain eventually
releases the session instead of pinning it open forever.

**Rationale:** Decision 10 already defines the rule - "Only addressed turns and
meaningful Jarvis work/speech events count as useful activity." Brain work is the
clearest possible case of meaningful Jarvis work. Ambient audio still does not count;
nothing about Decision 10's intent is weakened.

## Decision 33 - Mute does not auto-wake when the result arrives

**Status:** locked by orchestrator

**Context:** Decision 11 keeps Core work running through `Jarvis Mute`. The result can
therefore arrive while the voice surface is in BACKGROUND. Task 07 asked what happens
to that speech.

**Decision:** Do not auto-wake the voice surface to speak a result the user muted
through. The speech request expires per Decision 31. The result remains available in
Core - persisted turns and public working state - so the user hears it on the next
activation via rehydration, not through a surprise unmute.

**Rationale:** `Jarvis Mute` is an explicit user command to stop the voice surface.
Speaking anyway because a background job finished would override the user's own
instruction, which is exactly what Decision 11 protects against in the other
direction. Silence-on-mute is recoverable; an unrequested voice is not.

**Implications:** Task 08 must expire, not queue indefinitely. Task 10's public working
state is the recovery path.

## Decision 34 - The surface exposes no Core tools in continuous mode

**Status:** locked by orchestrator

**Context:** Task 06 surfaced a race the handoff never anticipated. In continuous mode
the complete user turn is submitted to the brain **and** the surface still holds the
Core tool catalogue - including `calendar_create/update/delete/invite`,
`drive_create/update/delete/share` and `reminder_create`. "Delete that file from
Drive" can therefore execute twice, or execute while the brain is deciding it should
not. Prompt wording cannot prevent this.

**Decision:** In `continuous_brain` mode the surface receives an **empty** tool
catalogue. Every substantive request - read or write - goes to the brain. Legacy mode
keeps the full catalogue unchanged.

**Rationale:** This is what spec section 9 already says, read strictly. The allowed
autonomous surface behaviour is an exhaustive list - short acknowledgement,
backchannel, hearing repair, hearing-scoped clarification - and it contains no
substantive action. The forbidden list explicitly includes "claiming a file/email/
calendar operation happened" and "substantive factual answers that the brain has not
supplied in async-brain mode". Section 1 likewise denies the surface "long-running
tool execution" and "task success/failure claims". Keeping write tools on the surface
would contradict the one boundary the handoff calls non-negotiable.

The asymmetry of harm settles the rest: a duplicated `drive_delete` or `calendar_invite`
is irreversible and user-visible, while a capability temporarily unavailable in an
opt-in, non-default mode is only a limitation. Decision 20 keeps `legacy` the default,
so nothing regresses for current users.

**Implications and required follow-up:**
- Continuous mode now depends on the brain having equivalent access. Drive is already
  exposed to the CLI agent through `jarvis/runtime/drive_mcp.py`; calendar and reminder
  access is **not verified**.
- Task 11 must add a scenario proving that no Core tool executes from the surface in
  continuous mode.
- Task 12 must document this as a **blocking** acceptance gate: continuous mode must
  not become the default until the brain's calendar/reminder access is confirmed, or
  the gap is accepted in writing.

## Decision 35 - Work is removed only by an explicit, named brain decision

**Status:** locked by orchestrator (proposed by Task 09b, ratified 2026-09-09)

**Context:** Task 09 step 6 requires "retain jobs by default, cancel only through
explicit brain decision", and `docs/05-event-contracts.md` gives
`brain.intent.revised` three buckets (`superseded_work_ids`, `cancelled_work_ids`,
`retained_work_ids`). Before 09b nothing published that event, and a backend had no
way to express either outcome: `BrainEventKind` only carried accepted/progress/
speech/completed/failed.

**Decision:** Two new backend event kinds, both requiring a `work_id`:

- `BrainEventKind.SUPERSEDED` - the work keeps running; only the speech already
  queued about it is stale. Publishes `brain.intent.revised` with the work in
  `superseded_work_ids`, and no `brain.state.updated` (the public state content
  did not change - the revision itself is the message).
- `BrainEventKind.CANCELLED` - the work stops. Core cancels the linked jobs through
  the new `WorkCanceller` port (`JobService.cancel_work`, selecting on the existing
  `_WorkLink.work_id`), drops the id from `active_work_ids`, and publishes both
  `brain.intent.revised` and `brain.state.updated`.

A new authoritative user turn publishes `brain.intent.revised` with **every** active
work id in `retained_work_ids` and the two other buckets empty. Interruption is
therefore never cancellation, and the retention rule is observable rather than
implicit. The three buckets partition the previously active work; the domain object
rejects an id appearing twice, and rejects a revision that does not advance.

**Rationale:** Without a producer, `superseded_work_ids` would be permanently empty
and the scheduler requirement ("invalidate queued speech whose work was superseded
or cancelled") would be untestable. Splitting the destructive and non-destructive
halves is what makes "interrupting is not cancelling" expressible at all: the brain
can retire a stale sentence without killing the work that produced it.

**Implications:**
- Core suppresses any `brain.speech.requested` whose `work_id` was cancelled, so the
  race "backend emits its result just as the brain cancels the work" resolves
  deterministically in Core rather than in the voice surface (Decision 13 forbids the
  scheduler from judging speech content).
- `SpeechScheduler` drops queued speech by designated `work_id`, including durable
  kinds (result, question), because the brain - not the surface - is retiring it
  (Decision 14). Retained work is never touched.
- Cancellation is idempotent: cancelling the same work twice produces one revision.
- A missing or failing `WorkCanceller` does not hide the decision; the revision is
  still published and the failure is reported to the diagnostic sink.
- Task 09c wires the surface: it only has to pass `interrupted_speech_id` on the next
  authoritative turn. Nothing in the barge-in path may cancel work by itself.

---

## Decision 36 - A truncated sentence is persisted, and marked as partly heard

**Status:** locked by orchestrator (proposed by Task 09c, ratified 2026-09-09)

**Context:** Acceptance criterion 2 requires that "conversation history does not claim
the user heard audio that was truncated". Before 09c the scheduler simply persisted
nothing when an output did not complete, which satisfies the letter of the criterion
but leaves a hole: the brain has no record that it started answering, so on the next
turn it can repeat the whole sentence the user cut off precisely because they had
heard enough. The opposite - persisting the full text as if delivered - is exactly
what the criterion forbids, and `BrainOrchestrator._derive_state` would then promote
it to a `known_public_fact`.

**Decision:** A speech request cut off by the user is persisted with its **full**
text - Decision 13 forbids the surface from rewriting a single word, and nobody can
say where a sentence was cut mid-word - plus two metadata keys: `delivery`
(`SPEECH_DELIVERY_PARTIAL`, from the domain) and `played_ms`, taken from the playback
cursor. `_derive_state` skips any brain turn marked partial, so it becomes neither a
known public fact nor an asked question. A speech interrupted before any audio
reached the device (`played_ms == 0`, or no cursor at all) is **not** persisted:
nothing was heard, so the history asserts nothing.

**Rationale:** The two failure modes are asymmetric. Claiming a truncated answer was
heard makes the brain silently wrong about what the user knows; forgetting that it
spoke at all only makes it repetitive. Marking the delivery keeps both honest with one
record, and puts the judgement in Core - where the public state is derived - rather
than in the voice surface, which is not allowed to decide what the brain knows.

**Implications:**
- `delivery`/`played_ms` are part of the assistant-turn metadata contract of spec
  section 15, alongside `provenance`, `speech_id`, `work_id`, `speech_kind`.
- A backend that reads history must treat a partial turn as "said, not necessarily
  heard". No consumer may promote it to a delivered fact.
- Concurrency invariant that came out of the same slice: a barge-in invalidates the
  in-flight write through a **playback epoch**, not a flag cleared when
  `stop_output()` returns. The writing thread and the interrupting thread compete for
  the same PortAudio lock, and a flag released too early lets the writer resume right
  after `abort()` - the sound would restart a few milliseconds after the user spoke.
  The accounting epoch stays separate, so the block that really was played keeps
  being credited and the truncation point stays exact.

---

## Decision 37 - The public brain state needs a reachable path back to the surface

**Status:** proposed by Task 11, not locked - the orchestrator decides

**Context:** Task 11 wired the whole chain end to end and found that Decision 33's
recovery promise has no code path. `BrainOrchestrator.rehydrate()` exists and does
hold what the user missed, but no `/v1` route exposes it, `LocalCoreClient` has no
method for it, and `PersistentVoiceRuntime.activate()` reads only
`GET /v1/conversations/{id}/context`, which returns the conversation summary plus
persisted turns. Speech that was never spoken is never persisted, so a result
produced while the user was muted leaves no trace in what the surface reads when it
comes back. `test_jarvis_mute_leaves_the_work_in_core_and_speaks_nothing_stale`
asserts both halves of the gap rather than hiding it.

**Proposal:** add the missing seam as its own task, before continuous mode can
become the default: a read-only Core operation for the public working state, a
client method, and a call at activation. The substantive question is not the
plumbing but what the surface does with the state - Decision 33 forbids waking the
user to speak a missed result, and it says nothing about what should happen on a
user-initiated wake. The safe default is silent context (the brain knows what it
already told the user), with speaking it left to the brain's own judgement on the
next turn.

**Why not fixed in Task 11:** it is not a localized defect. It needs a new public
Core operation, a change to the voice activation path, and a behavioural decision
about the first seconds after a wake. Hiding that inside an integration-test slice
is exactly what this task's handoff notes forbid.

**Tests / enforcement:** the mute scenario already pins the current behaviour; it
must be updated, not deleted, when the seam lands.

## Decision 38 - Ruling on Decision 37: the recovery path exists; the cold state is the real defect

**Status:** locked by orchestrator, 2026-09-09. Amends and narrows Decision 37.

**Context:** Task 11 proposed Decision 37 - "Decision 33's recovery promise has no code
path" - and asked the orchestrator to decide. The orchestrator verified the claim
against the code rather than the report.

**Findings:**

1. `BrainBackend.run_turn(turn, state, emit)` already receives the public working
   state on every turn (`jarvis/ports/v2.py:159`). While Core is running - the mute
   case Decision 33 actually addresses - `_states` still holds the result the user
   missed, so the brain has it on the user's next turn and can decide to mention it.
   The recovery path exists; it runs through the brain, not through the surface.
2. The real defect is narrower and was not what Decision 37 described:
   `submit()` derives its state from `working_state()`
   (`jarvis/core/brain_service.py:210`), which returns an **empty** state when the
   cache is cold, while `rehydrate()` rebuilds it from persisted turns
   (`brain_service.py:238`). After a Core restart the brain therefore starts the
   first turn blind, even though the derivation it needs already exists.

**Decision:**

- **Fix** the cold-state asymmetry: an authoritative turn on a conversation with no
  cached state must resolve that state through the same derivation `rehydrate()` uses.
  One seam, no new schema.
- **Do not** wire the public working state into the voice activation path.
  `PersistentVoiceRuntime.activate()` feeds what it reads to the Realtime surface, and
  Decision 34 plus spec section 9 forbid that surface from stating substantive results.
  Handing it results it is not allowed to speak would rebuild the exact hazard Task 06
  removed. Silence on wake is the intended behaviour, not a gap.
- **Do not** add a read-only `/v1` route for the working state now.
  `brain.state.updated` already streams the same payload over `/v1/events`, so
  diagnostics and UI have a path. A convenience route is not a blocker and would widen
  the public surface for no proven need.

**Rationale:** Decision 33 forbids waking the user to speak a result they muted
through. A user-initiated wake is not an authorization to blurt out a stale answer, and
the brain - which owns truth - is the right place for that judgement. What is not
acceptable is a brain that has forgotten everything because Core restarted.

**Tests / enforcement:** Task 11's mute scenario must be updated, not deleted: it
should pin that the brain receives the missed result on the next turn, and that the
surface receives nothing on activation. Add a test that a cold Core still hands the
brain a derived state on the first authoritative turn.

## Decision 39 - The Decision 34 rollout gate is a list in code, not a sentence in a document

**Status:** locked by orchestrator (proposed by Task 12a, ratified 2026-09-09). A gate
that a test can check is worth more than a paragraph nobody re-reads before a release.

**Context:** Decision 34 requires Task 12 to document a **blocking** acceptance gate:
continuous mode must not become the default until the brain's calendar/reminder access
is confirmed, or the gap is accepted in writing. A sentence in a document is not
checkable; the previous default lived as a hard-coded `VoiceArchitecture.LEGACY` inside
`parse_voice_arch`, where nothing tied it to the reason it exists.

**Proposal:**

- The gate is `CONTINUOUS_BRAIN_DEFAULT_BLOCKERS` in `jarvis/v2_config.py`, today
  `("brain_calendar_access_unverified", "brain_reminder_access_unverified")`.
- `default_voice_arch()` returns `legacy` while that tuple is non-empty, and
  `parse_voice_arch()` is its only consumer. Removing `JARVIS_VOICE_ARCH` from the
  environment therefore returns to `legacy` mechanically - that is the rollback path
  Decision 20 promises, expressed once.
- Emptying the tuple is the deliberate act that flips the default. It requires either
  wiring the missing brain access, or accepting the gap in writing as Decision 34
  allows. `tests/unit/test_v2_latency_telemetry.py` pins both directions: the default is
  `legacy` while a blocker stands, and clearing the list is what would flip it.
- Explicit opt-in is untouched: `JARVIS_VOICE_ARCH=continuous_brain` still works. What
  is locked is a **default**, not a mode.

**What this does not claim:** nothing here verifies the brain's calendar or reminder
access. The blockers are still blockers. Task 12a only made them fail loudly instead of
silently.

**Verification status:** the gate and the rollback path are covered by deterministic
tests. No hardware or live-provider recipe was run in Task 12a; those remain unverified.


## Decision 40 - The local trace keeps its truncated text; only the new telemetry is id-only

**Status:** locked by orchestrator, 2026-09-09

**Context:** Task 12a delivered the six latency measures carrying identifiers only, then
correctly raised that this leaves the privacy line of `docs/04-testing-and-quality.md` -
"transcript/prompt body not logged by default" - satisfied for the new telemetry but not
for the journal as a whole: `voice.transcript`, `voice.assistant`,
`voice.brain_turn_submitted` and the scheduler's `voice.speech.*` have always logged
`text[:300]` as their message. It asked the orchestrator to arbitrate rather than
changing it inside a telemetry slice.

**Finding:** that text is not an accidental leak. `RuntimeJournal` writes to a local
`trace.jsonl` under the runtime root, the Control Center serves it
(`jarvis/runtime/control_center.py:266`), and existing tests assert on the message
bodies it contains (`tests/unit/test_claude_debug_console.py:97`). The debug console the
user built depends on reading what was actually said. Nothing leaves the machine.

**Decision:** keep it. Do not strip transcript text from the pre-existing journal events
as part of this handoff.

- New telemetry stays id-only, enforced by test: `LatencyTracker.measure()` builds its
  own message from the measure name, so a caller cannot smuggle content in.
- The deviation from the wording of `04-testing-and-quality.md` is recorded here rather
  than silently closed. Read strictly, that line described a stance this repository does
  not actually hold for its local trace.
- A configuration switch to redact journal message bodies is future scope. It is a
  product decision about the debug console, not a migration decision, and removing a
  working diagnostic surface to satisfy a sentence would be the wrong trade - Task 12's
  own handoff notes forbid dropping fallback behaviour to tidy the final picture.

**Enforcement:** the privacy tests must keep proving that the latency events carry no
content. They must not be extended to forbid text in the console-facing events, which
would break the debug console.

---

## Decision 41 - The repository privacy claim was wrong; the documents were corrected, not the code

**Status:** locked by orchestrator (proposed by Task 12b, ratified 2026-09-09).
Applies Decision 40 to the Git documentation. A document that promises a privacy
guarantee the code does not implement is worse than no document: it is the one place a
user would check before trusting the tool.

**Context:** Decision 40 ruled that the pre-existing runtime journal keeps its
truncated transcript text, because the Control Center debug console is built on
reading it back. Task 12b then found that three repository documents assert the
opposite as a *security default*:

- `README.md`: "Transcript/prompt/body content is redacted from logs by default
  (`log_content = false`)";
- `docs/SECURITY.md` §10: "Structured JSONL logs retain event type, timing and
  error class while redacting transcript/prompt/body-like fields";
- `docs/OPERATIONS.md`, Diagnostics: "With default privacy settings, content
  fields are redacted".

All three are true of `jarvis/diagnostics/logger.py`, the V1 push-to-talk path,
where `JARVIS_LOG_CONTENT` really does gate `_sanitize`. None of them is true of
`jarvis/runtime/journal.py`, the v0.2 path: `RuntimeJournal.emit()` has no
content switch at all, and `voice.transcript`, `voice.assistant`,
`voice.brain_turn_submitted` and the scheduler's `voice.speech.*` pass
`text[:300]` as their message. The two journals were never distinguished in the
documentation, so the V1 guarantee silently covered a path that does not hold it.

**Decision:** correct the documents, do not touch the code.

- Each of the three places now names both journals and says which one redacts and
  which one does not, that `JARVIS_LOG_CONTENT` does not reach the v0.2 journal,
  and that the file is local and leaves the machine nowhere.
- The new latency telemetry is documented as identifier-only, which it is by
  construction and by test.
- Anyone wanting a content-free local trace is told it is a change to the debug
  console, because no setting does it today.

**Rationale:** Decision 40 already weighed the trade and kept the text; reopening
it inside a documentation slice would be exactly the "drop a working fallback to
tidy the final picture" that Task 12's handoff notes forbid. The defect worth
fixing was the *claim*, not the behaviour: a security document that promises
redaction it does not perform is worse than one that describes a deliberate local
diagnostic. This is also the one divergence Task 12b found where the documentation
described a behaviour the code does not have, and the task's own constraint was to
report it rather than change code to match prose.

**Tests / enforcement:** none added. The privacy tests already forbid content in
the latency events and must not be extended to the console-facing events
(Decision 40). This decision is a documentation invariant: if a future task makes
the v0.2 journal redactable, these three passages must change with it.

## Decision 42 - Correction: Decision 38's stated basis was wrong; its conclusion survives for a different reason

**Status:** locked by orchestrator, 2026-09-09. Corrects Decision 38.

**Context:** the independent critique checked Decision 38 against the code instead of
against the report, and found the argument false. Decision 38 refused a `/v1` route and
an activation wiring on the grounds that "`BrainBackend.run_turn(turn, state, emit)`
already receives the public working state, so the recovery path exists". That is true of
the port and false of the only production backend:
`jarvis/adapters/control_center_brain.py` **did** `del state` and sent nothing but
`turn.text` to `/api/agent/ask`. (Closed since, by Decision 45: the backend now sends
`context: {addressing, state}`. This paragraph records the state at the time of the
ruling, not the state of the code.)

**What is actually true:** the recovery path exists, but through a different mechanism.
The local CLI agent keeps its own conversational session and is resumed by
`--resume <session_id>` (`jarvis/runtime/claude_local.py:181,316`). A result the agent
produced while the user was muted is in that agent's own memory, so the user gets it by
asking on the next turn. The brain remembers; Core's public state is simply not what
carries it.

**Decision:**

- The refusals stand: no route, no activation wiring. The reason is unchanged and was
  never the faulty half - feeding the Realtime surface substantive results it is
  forbidden to state would rebuild the hazard Task 06 removed (Decision 34).
- The cold-state fix (`brain_service.py:_ensure_state`) stands and remains correct: Core
  must not hand the brain an empty state after a restart, whatever today's backend does
  with it.
- **Recorded residual gap, not closed here:** `ControlCenterBrainBackend` conveys no
  Core context at all - no public state, no known facts, no work list. Continuity rests
  entirely on the CLI agent's own session. If that session is lost, restarted, or taken
  over by the debug console (`claude_local.py:308`), the brain starts blind while Core
  still holds the truth. Wiring `state` into the `/api/agent/ask` payload is the obvious
  follow-up task and should precede making continuous mode the default.

**Lesson recorded deliberately:** the orchestrator ruled on a port signature without
checking the implementation behind it. A capability that exists in a protocol and not in
the only adapter is not a capability.

## Decision 43 - Scope the chain-of-thought claim to what the code actually guarantees

**Status:** locked by the user, 2026-09-09. Narrows Decision 40, corrects the final
report.

**Authority note, recorded deliberately.** This decision was first locked by the
orchestrator alone. The second independent critique judged the disclosure exemplary and
the authority illegitimate: the orchestrator had narrowed a point of intent the *user*
had locked - "no raw chain-of-thought is stored or exposed" - which was not its to
requalify. The critique was right. The question was put back to the user, who chose
"I accept, it is my debug console" with the deviation documented and the file named.
The decision now stands on the user's authority, and its content is unchanged.

**Context:** the locked project intent says "No raw chain-of-thought is stored or
exposed", and `FINAL-REPORT.md` restated it as a delivered property. The critique found
that false at system level: `jarvis/runtime/claude_local.py:477` journals every raw
stream-json event - `thinking` blocks included - into `runtime/trace.jsonl`, and
`claude_local.py:284` renders those blocks as `[réflexion] ...` in the Control Center
console (same for Codex, `codex_local.py:156`). Decision 40 audited that same file for
privacy and missed it, having looked only at the `text[:300]` transcript messages.

**Decision:** correct the claim; keep the feature.

- What the code guarantees, and what the documents may claim: no reasoning field exists
  in Core's domain state, no reasoning is persisted in conversation turns, none is
  carried by `brain.state.updated` or any speech request, and none reaches the Realtime
  surface. That is the boundary the handoff was built to protect, and it holds -
  `tests/unit/test_v2_brain_contracts.py` pins it.
- What the documents must stop claiming: that no raw reasoning is stored or exposed
  *anywhere*. The local agent's own trace and debug console carry its reasoning by
  design, on the user's machine, in a console the user built to watch the agent work.
- Removing it is not this handoff's call: it is a pre-existing product feature, and
  Decision 40's reasoning applies unchanged - a working diagnostic surface is not
  demolished to make a sentence true.

**Enforcement:** `FINAL-REPORT.md`, `README.md`, `docs/SECURITY.md` and
`docs/OPERATIONS.md` must state the scoped claim and name `runtime/trace.jsonl` as
carrying the local agent's reasoning, so a reader who cares can look before trusting it.

## Decision 44 - In continuous mode an uncertain turn goes to the brain, not to the bin

**Status:** locked by the user, 2026-09-09. Answers the critique's finding A.

**Context:** the independent critique found that in `continuous_brain` mode a completed
user turn reaches Core only if `ConservativeAddressingClassifier` returns `ADDRESSED`
(`jarvis/runtime/realtime_audio.py:1258`). The classifier returns `UNCERTAIN` for any
sentence over eight words that neither starts with "jarvis" nor ends with a question
mark - which is most real requests. Those turns are dropped silently, while the surface,
driven by server VAD with `create_response: true`, answers anyway and is allowed by its
own prompt to say it is taking care of it. Verified: "Regarde dans mon Drive le fichier
des comptes de janvier et donne moi le total" classifies as `uncertain`.

That is the non-negotiable boundary taken from behind. Deciding that a request is not a
request is an intent decision, and intent belongs to the brain.

**Decision (the user chose this among four options):** in `continuous_brain` mode, an
`UNCERTAIN` turn is submitted to the brain, which decides whether it was addressed to
it. The surface stops adjudicating substantive routing.

**Boundaries of the change, so it does not undo Decision 10:**

- `AMBIENT` is untouched: empty text, and any turn while the session is not active, are
  still dropped. Only `UNCERTAIN` - a real sentence, during an already ACTIVE session -
  is routed.
- Ambient noise still does not count as useful activity. Routing a turn to the brain and
  rearming the inactivity timer are two different things; the locked intent "ambient
  noise never counts as useful activity" stands.
- `legacy` mode is unchanged. There the surface holds the tools and answers itself, and
  the classifier keeps its current role.

**Accepted cost, stated by the user's choice:** a long sentence spoken near Jarvis during
an active session now reaches the local agent - latency, cost, and the possibility of
unnecessary work. That is preferred to Jarvis promising work that nobody does.

## Decision 45 - Core's truth reaches the brain: the context payload closes Decisions 42 and 44

**Status:** locked by orchestrator, 2026-09-09. Closes the residual gap of Decision 42
and makes Decision 44's safeguard real rather than nominal.

**Context:** two decisions had left the same hole. Decision 42 recorded that
`ControlCenterBrainBackend` conveyed no Core context at all and named the wiring as the
follow-up that must precede making continuous mode the default. Decision 44 - the
user's own choice - routes an `UNCERTAIN` turn to the brain "which decides whether it
was addressed to it", but the backend did not forward the marker either, so the agent
treated overheard speech exactly like a direct request. The safeguard existed in the
contract and not in the product.

**Decision:** `POST /api/agent/ask` accepts an optional `context: {addressing, state}`.
The backend fills it from the turn and from `BrainWorkingState.to_rehydration_payload()`;
the Control Center - which owns the agent (Decision 23) - renders it as a short brief
ahead of the request.

- **Only public state travels.** Reusing `to_rehydration_payload()` rather than a
  bespoke projection is the mechanical guarantee that nothing outside Core's public
  state leaves, and `BrainWorkingState` carries no reasoning by construction
  (Decision 12). The rendering is a whitelist, so an unknown field - including one
  called `reasoning` injected by some other caller - never reaches the model.
- **The marker is explained, not merely sent.** An `uncertain` turn carries an explicit
  way out: judge whether it was for you, and if not, do nothing, use no tool, and answer
  `[pas-pour-moi]`. The backend maps that token to an empty answer, which is the
  existing no-speech path. An `addressed` turn gets no such escape hatch.
- **The optional field keeps every other caller unchanged.** `/api/agent/ask` has two
  other callers and the browser panel is not one of them (it uses `/api/agent/send`);
  a call without `context` reaches the agent byte-for-byte as before, and a non-object
  `context` is ignored rather than rejected.

**What this does not guarantee:** that a model honours the instruction. The tests prove
the brief is sent and that the token, if returned, produces silence - not that the
judgement is sound. Like every prompt-level guarantee in this system, it narrows the
output space without constraining it, and only workstation and live-provider use can
say more.

## Decision 46 - An uncertain turn writes Core's intent only once the brain takes it

**Status:** locked by orchestrator, 2026-09-09. Downstream half of Decision 44, which the
user locked; this completes it rather than reopening it.

**Context:** the second independent critique found - and demonstrated by running the code
- that Decision 44 had been applied upstream only. `submit()` revised
`current_user_intent` and cleared `unresolved_questions` unconditionally, so a turn Core
itself had marked `uncertain` became Core's truth before the brain could judge it:

```
after an addressed turn   intent='Jarvis fais les comptes'   questions=('Quel mois ?',)
after an uncertain turn   intent='il faudrait vraiment que quelqu un rappelle le plombier...'   questions=()
```

Decision 45 made it worse rather than better: that polluted state is exactly what the
brain is handed as "current intent" on the next turn. Overheard speech was becoming the
truth Core asserts, and a question Jarvis had just asked the user vanished without trace.

**Decision:** an `uncertain` turn is persisted and dispatched exactly as before - the
ingress stays single (Decisions 06 and 30) - but it does not revise the public state. It
is held pending, and promoted only when the brain produces something addressed to the
user on that turn.

- **Promotion signal:** a brain speech whose kind is not `ERROR`, or a `COMPLETED`
  outcome with a non-empty public summary. The contract only ever had a token for
  *recusal* (`[pas-pour-moi]`), so the inverse signal is the honest one available.
  `BrainEventKind.ACCEPTED` is explicitly not a promotion: the production backend emits
  it before it even asks the agent.
- **Event sequence:** `brain.turn.accepted` is still published - the turn was received
  and written - carrying the current, unchanged revision, with no
  `brain.intent.revised` / `brain.state.updated` behind it. The full sequence moves to
  the moment of promotion, where it becomes true. Repeating a revision number is licit
  under Decision 31: `SpeechScheduler._note_revision` only flags a *gap*.
- **Cold rebuild:** confirmation is reconstructible from the correlation shared by the
  uncertain turn and the brain speech that answered it. No new field, no new write.

**Recorded residuals, not closed:** a recused turn still transits a `work_id` through
`active_work_ids` then `completed_work_ids`, because the backend opens the work before
asking the agent; moving that would break the start marks of latency measures 5 and 6.
And `brain.turn.accepted` still drops transient queued speech even for an uncertain turn.
Both are narrower than the boundary this decision protects, and both are named here
rather than left to be rediscovered.

## Decision 47 — A stale answer is spoken or explicitly settled, never buried
**Status:** locked by the user on 2026-09-19.

**Context:** Decision 14 says the brain owns truth, and that the surface never throws a
`result`, `error` or `question` away. Decision 35 says work — and the queued speech that
describes it — is removed only by an explicit, named brain decision. Both were contradicted
in practice by two mechanical rules of age:

- `SpeechScheduler._eligibility` deferred any durable utterance whose intent was no longer
  current. `_deferred` is only drained when that exact intent becomes current again, which
  never happens: the entry was a silent grave. 22 occurrences in `runtime/trace.jsonl`, one
  survivor.
- `BrainOrchestrator._take_stale_replies` invalidated, on every new intent, the dependency
  of every reply already emitted and not yet spoken — a removal in bulk, without the brain
  naming anything.

**Decision:** relevance is judged by the brain, not by age.

- The surface carries a durable utterance of a past intent over to the current intent and
  speaks it (`reason: carried_over`), after what the current intent already has queued. A
  transient one (`progress`, `ack`) is still dropped: its truth evaporated on its own.
- Between two origins, authority comes from the intent, not from the writing time: an
  utterance of the *current* intent replaces a carried-over one occupying the same speech
  slot (same `supersedes_key` or same `work_id`); never the reverse.
- Core hands the brain, at its next turn, the replies it has written and that the mouth has
  not said yet (`BrainContext.pending_replies`, rendered in the agent brief). This is the
  "context between what must be said and what is about to be said" the user asked for: the
  brain does not repeat them, and can retire one by naming it.
- A durable utterance that dies unspoken is settled out loud: `voice.speech.abandoned`, at
  `warning`, carrying the withheld text and the reason. Silence is never the record.

**Residual, named rather than rediscovered:** the only instrument the Control Center brain
has to retire a pending reply is a token in its own answer
(`[[jarvis:retire <work_id>]]`, `control_center_brain.RETIRE_MARKER`), stripped before
speech and honoured only for the ids Core just handed it. It is the same shape as
`BRAIN_NOT_ADDRESSED_ANSWER` (Decision 44) and for the same reason: the agent's answer is
the only channel it owns towards Core. A real tool would be better.
