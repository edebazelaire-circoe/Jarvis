# Target Architecture Specification

## Implemented configuration contract (Task 02, schema version 1)

`jarvis/domain/voice_architecture.py` defines `VoiceArchitectureId`, `VoiceModelRef`, `SimpleVoiceConfig`, `FrontBrainVoiceConfig`, `DuplexVoiceConfig`, `VoiceModelCapabilities`, and `VoiceModelDescriptor`. The existing `v2_config.VoiceArchitecture` enum remains unchanged. Provider IDs/model constants are populated outside domain in `runtime/voice_capabilities.py`.

Persistence uses a new `voice_architecture` key, independent of old `voice_arch`. `runtime/voice_architecture_config.py` supplies `load_voice_architecture`, `decode_voice_architecture`, `store_voice_architecture`, and `voice_architecture_query`. Exact envelope:

```json
{
  "schema_version": 1,
  "config": {
    "architecture": "simple",
    "conversation_model": {"provider_id": "openai", "model_id": "gpt-realtime-2.1-mini"}
  },
  "compatibility": null
}
```

Front Brain replaces `conversation_model` with `reflex_model` and `analysis_model` (same model-reference shape), plus boolean `speculative_deltas` (default true), and `reasoning_effort` (default `low`, nullable when no reasoning control is wanted). Duplex uses `conversation_model`, boolean `client_delegation` (must be true), and `idle_timeout_s` (finite number 5–3600, provisional default60). Saved legacy timeout0 is never copied into Duplex. These bounds/default are an initial safety configuration, not benchmark conclusions; disable-by-zero is rejected.

An absent new key creates a **Simple configuration projection with compatibility metadata**, not a behavior switch. Metadata keys: `execution_mode` (`legacy/continuous_brain`), `architecture_source`, `stack_id`, `stack_source`, `model_source`, `stack_settings`. Sources are `settings/env/default`; `model_source` can also be `missing`. This retains exact resolved model and scalar stack options; unknown old models and missing Gemini selection survive as explicit unsupported projections. Explicit new selections require registry validation. Nonempty saved old architecture/model/stack wins over environment; absent stack uses the same `JARVIS_VOICE_STACK` initial default as Control Center. New envelope overrides automatic projection. Loader never writes, and store modifies only the new key, preserving inactive profiles, prompts and old settings.

`VoiceCapabilityRegistry.query(architecture, role="conversation"|"analysis", ready_only=False)` supplies the future UI; `validate(config, require_ready=False)` checks selections. Supported frontend architecture profiles plus actual capabilities determine eligibility. Billing is separate: a free/token-billed future Duplex provider is valid. Analysis needs text and structured output, with reasoning effort optional. `adapter_status` is `legacy_only/planned/ready`; account `availability` is `unknown/available/unavailable`. Existing Realtime/Gemini entries remain `legacy_only`; GPT-Live/Luna remain `planned`. No new adapter is marked ready by this slice. Registry declarations and configuration representability are not claims of live account access or implemented runtime support.

Google registry entries require catalog `id` plus `methods` containing `bidiGenerateContent`; names and `roles=["realtime"]` alone prove nothing. No Gemini ID is invented. Unknown explicit models fail with stable `voice_model_unsupported`; invalid pairs, speculative delta support and reasoning effort have distinct actionable codes. Schema rejects unknown fields, bool versions, nonfinite timeout, truthy nonbooleans and nested compatibility field values. `voice_architecture_query` reports readiness problems separately from preserved compatibility selection.

Task02 intentionally does not call these APIs from the audio composition root or Settings handlers. Tasks05/10/12/14/17 must wire the real frontend and explicit switch; existing runtime execution remains unchanged until then. See `docs/voice-architectures/INDEX.md` and `docs/legacy/voice-architecture-selection.md` for ownership and migration removal gate.

## Core boundaries

### `ConversationCore`
Provider-agnostic authority for the current voice conversation. It owns canonical user/assistant speech events, provisional and committed transcript state, actually-spoken history, turn lineage, speech freshness/cancellation, active backend tasks, architecture/model identifiers, result routing, and observable metrics. It does not know provider wire event names.

### `VoiceFrontend`
Implemented Task03: `jarvis/ports/voice_frontend.py::VoiceFrontend`, with values in `jarvis/domain/voice_frontend.py` and `jarvis/domain/voice_events.py`. Existing `ports/v2.py::RealtimeSession` and `RealtimeOutputControl` stay unchanged until adapter migration. No new production frontend is composed by this slice.

Exact methods (all controls async, all require keyword `operation: VoiceOperation`):

```python
start(config: VoiceFrontendConfig, *, operation) -> VoiceOperationResult
stop(reason: VoiceStopReason, *, operation) -> VoiceOperationResult
send_audio(chunk: VoiceAudioChunk, *, operation) -> VoiceOperationResult
finish_input(*, operation) -> VoiceOperationResult
append_quiet_context(update: VoiceTextUpdate, *, operation) -> VoiceOperationResult
append_spoken_result(update: VoiceTextUpdate, *, operation) -> VoiceOperationResult
feed_runtime_instruction(update: VoiceTextUpdate, *, operation) -> VoiceOperationResult
cancel_speech(*, operation, playback: AssistantPlaybackEvidence | None = None) -> VoiceOperationResult
events() -> AsyncIterator[VoiceEvent]
```

Properties: `state: FrontendState`, `capabilities: VoiceModelCapabilities`. `VoiceFrontendConfig` holds the existing `VoiceModeConfig`, bounded `VoiceContext`, application instructions and input PCM format. PCM is mono signed16 little endian; each `VoiceAudioChunk` contains complete samples and at most one second, with explicit sample rate. Owner admission remains before upload. `finish_input` is an explicit manual commit/response request; providers without that operation return `UNSUPPORTED`, not an invented response trigger.

`VoiceOperation` carries `operation_id` and `VoiceCorrelation`. Results distinguish `ACCEPTED` (sent/queued), `COMPLETED` (operation-specific evidence), `UNSUPPORTED`, `REJECTED`, `FAILED`, and `UNKNOWN`. Acceptance never proves consumption or speech. Unsupported/failed/unknown results require `VoiceFrontendError` with stable `VoiceErrorCode`, operation, lifecycle state and optional sanitized provider code/message. Raw provider payloads, exceptions, credentials and SDK types do not cross the port. Runtime instruction text is application-authored; backend facts use quiet/spoken context operations. Adapters enforce provider token limits without silently truncating. The neutral context bound is 128 messages/32768 characters; message/update bounds are8192 characters, not a claim that any provider's token limit is satisfied.

Exact canonical payload classes and `kind` values:

| Payload | Kind / semantics |
|---|---|
| `FrontendLifecycleChanged` | `frontend.lifecycle_changed`; state `NEW/STARTING/ACTIVE/STOPPING/STOPPED/UNKNOWN_REAP_REQUIRED` |
| `UserSpeechActivity` | `user.speech_activity`; `STARTED/STOPPED`, source `LOCAL/PROVIDER`; VAD evidence, not owner authorization or transcript finality |
| `UserTurnOpened` | `user.turn_opened`; known input ordering through `previous_turn_id`, independent of ASR arrival; not a transcript commit |
| `UserTranscriptDelta` | `user.transcript_delta`; exact fragment, application transcript grouping ID and revision |
| `UserTranscriptRevised` | `user.transcript_revised`; Task04 explicit full replacement of provisional text at a newer revision; never a commit |
| `UserTranscriptCommitted` | `user.transcript_committed`; full text replacement/revision with explicit `PROVIDER/APPLICATION` commit source and required turn ID |
| `AssistantTranscriptDelta` | `assistant.transcript_delta`; generated fragment only |
| `AssistantTranscriptCompleted` | `assistant.transcript_completed`; provider-ended generated transcript, never heard proof |
| `AssistantGenerationStarted` | `assistant.generation_started`; provider generation began |
| `AssistantAudioChunk` | `assistant.audio_chunk`; normalized PCM for the local output queue |
| `AssistantGenerationFinished` | `assistant.generation_finished`; `COMPLETED/CANCELLED/FAILED/INCOMPLETE/UNKNOWN`; requires explicit generation evidence |
| `AssistantSpeechActivity` | `assistant.speech_activity`; local device `STARTED/STOPPED`, distinct from generation |
| `AssistantPlaybackEvidence` | `assistant.playback_evidence`; local cumulative `played_ms`, `UNPLAYED/PARTIAL/COMPLETE/UNKNOWN`, optional independently aligned `confirmed_text` |
| `UserInterruption` | `user.interruption`; `CANDIDATE/CONFIRMED`, source `LOCAL/PROVIDER`; retains owner/admission gating |
| `VoiceDelegationRequested` | `frontend.delegation_requested`; source context revision and opaque delegation correlation, no invented task text |
| `VoiceFrontendFailed` | `frontend.error`; typed, sanitized stable diagnostics |
| `VoiceUsageUpdated` | `frontend.usage_updated`; cumulative duration/token snapshots with `PROVIDER_SNAPSHOT/PROVIDER_FINAL/LOCAL_ESTIMATE` provenance; missing is unknown |

Every payload uses `VoiceEvent(event_id, sequence, correlation, observation, payload, operation_id?, provider_event_id?, provider_interval?)`. Sequence orders local observation, not turn chronology or provider causality. `VoiceObservation` separates timezone-aware wall-clock receipt from process-local integer monotonic nanoseconds; `VoiceSessionInterval` preserves optional provider session-relative `[start_ms,end_ms)` intervals. Those intervals are not playback time or word alignment. `VoiceCorrelation` carries opaque JARVIS session/turn/task/speech IDs and provider session/output/delegation/input/predecessor-input IDs. Session ID identifies one frontend incarnation; consumers must reject stale sessions and deduplicate session/event IDs. Provider input ordering and `UserTurnOpened` allow finalB-before-finalA ASR delivery without treating arrival order as conversation order.

`UserTranscriptDelta.revision` increases with observations inside one `transcript_id`; each `delta` appends exactly, including whitespace. A new revision never means resetting accumulated text. `UserTranscriptRevised.text` explicitly replaces provisional text; `UserTranscriptCommitted.text` is an explicit full-text replacement at the accepted revision. Task04's reducer owns stale revision checks and rejects provisional rewrites of committed history; do not overload append deltas to replace hypotheses or infer provider finality.

One adapter reader normalizes provider wire messages into `events()`. It is a single-consumer, bounded stream; cancelling/closing its iterator releases the subscription, not the remote session. Runtime owns local audio playback and can produce the same canonical envelopes for Core; hardware evidence is not fabricated by the provider adapter. Controls run concurrently with the reader. Start opens only once. Stop is bounded and idempotent, works during start, wakes/drains/ends the iterator, and does not cancel backend work. `STOPPED` requires confirmed closure (or never-started evidence); socket loss or close request alone leaves `UNKNOWN_REAP_REQUIRED`, retaining provider identity. Caller cancellation propagates while cleanup ownership remains explicit. Task13 supplies durable uncertain-session reaping.

The generated transcript may arrive before playback, differ from intended backend text, or arrive after cancellation. Zero-played output cannot carry confirmed text; partial or complete device delivery may still have unknown word alignment. `confirmed_text=None` must survive projection/switching. A complete transcript is not a complete playback event, and an empty audio queue is not end-of-output evidence. Live primary WebSocket lacks authoritative transcript finality and exact output alignment: emit deltas and uncertain/partial evidence without manufacturing completed transcript/turn/generation events from silence. Delegation does not commit a turn; Core selects bounded revision-tagged context and applies its action gates.

`tests/fakes/voice_frontend.py::FakeVoiceFrontend` is a permanent test-only fixture. It records controls and injects deterministic events, without synthesizing provider answers or playback on acceptance. Tests cover complete synthetic conversation, unsupported controls, double Stop, uncertain Stop, stop/cancellation during startup, reader cleanup, bounded queue overflow, exact fragments, out-of-order ASR and duplicate/stale event identity. The fake deliberately preserves injected duplicates/stale events so Task04 can test its reducer. Recursive AST tests in `test_v2_architecture.py` enforce SDK/layer boundaries including nested packages and relative imports, without extending the historical Core composition exception.

Observability/Test Contract: these domain/port definitions emit no runtime logs and create no sessions. Stable diagnostics and correlation fields define what future adapter/runtime boundaries must report through existing `DiagnosticSink`/`RuntimeJournal`; no new logging subsystem or fabricated journal evidence. Test fixture behavior is not a live-provider quality claim. Task03 focused gate: 103 tests across contract, architecture and configuration suites passed on2026-09-12; see feature INDEX for command.

### `BackBrainGateway`
Stable interface from Conversation Core to JARVIS reasoning/tasks/sub-agents. It accepts a request with selected context and returns typed progress/result events. It must not own the audio session or block the realtime input loop.

### `PromptRegistry`
Stores prompt layers with provenance and computes the effective application-controlled prompt for each runtime role.

### `ModelCapabilityRegistry`
Declares what a provider/model can do and therefore where it can appear in Settings.

## Architecture configurations

### Simple

```text
architecture: simple
conversation_model: <audio realtime model>
backend: existing JARVIS
```

Initial candidates after code discovery: OpenAI Realtime 2.1 Mini, OpenAI Realtime 2.1, and compatible existing Gemini voice model(s).

### Front Brain

```text
architecture: front_brain
reflex_model: <audio realtime model>
analysis_model: <fast text/reasoning model>
speculative_deltas: true|false
backend: existing JARVIS
```

Initial analysis candidate: GPT-5.6 Luna. Sidecar output is advisory and parallel.

### Duplex

```text
architecture: duplex
conversation_model: gpt-live-1
client_delegation: true
idle_timeout: configurable
manual_stop: mandatory
orphan_watchdog: mandatory
backend: existing JARVIS
```

Future duplex providers can appear if their capabilities satisfy the Duplex requirements.

## Capability registry

Suggested fields:

```text
provider_id
model_id
supports_audio_input
supports_audio_output
supports_full_duplex
supports_transcript_deltas
supports_semantic_vad
supports_native_interruptions
supports_function_tools
supports_backend_delegation
supports_quiet_context_injection
supports_spoken_result_injection
supports_usage_events
supports_prompt_update
supports_reasoning_effort
billable_session_time
```

## Conversation truth model

Keep separate intended speech, actually spoken speech, backend facts, provisional interpretation, and committed user turn. Only actually spoken output joins the heard-conversation ledger.

Task04 implements `domain/voice_state.py` immutable records and `core/voice_state.py::VoiceConversationState`, documented in [state-model.md](../../../docs/state-model.md). The reducer consumes canonical observations and maintains bounded user/turn/speech/task evidence with strict version1 snapshots, replay/session guards, and a heard-context projection. No provider adapter or legacy history writer is migrated by this slice. Task05 must merge provider/playback observations with one dispatch-time sequence allocator and integrate this projection with existing `ConversationService`; legacy rehydration text cannot substitute for playback evidence. Active tasks survive frontend replacement. Generated transcript, complete generation, and task completion never imply heard words or action authorization.

## Speech decision model

A conversation turn can yield:

```text
WAIT
BACKCHANNEL
SPEAK
PREAMBLE
DELEGATE
```

The gate considers whether the user is still speaking, address confidence, direct-answer availability, expected backend latency, whether silence is acceptable, candidate freshness, priority, and whether the user is merely confirming/correcting/declining.

## Speech chunks and freshness

Represent semantic chunks with `speech_id`, `source_turn_id`, optional `source_task_id`, priority, timestamps, freshness policy, state, and content/intent. New user speech can invalidate unstarted chunks; an interrupted response's remaining chunks may be dropped. Backend completion creates a candidate result, not forced FIFO speech.

## Front Brain sidecar

Task09 implements the narrow contract in `domain/front_brain_hints.py`, the
`FrontBrainAnalyzer` port and a deterministic `FrontBrainHintConsumer`.
Application-owned requests select a full `VoiceUserRecord`, bounded
`VoiceContext`, nullable actual `origin_source` and separate `context_source`,
configuration/admission identities and an original local monotonic deadline.
A provisional B may use committed A as context without borrowing A's Core turn
as B's origin. Core turn IDs, canonical voice turn IDs and explicit source
correlations remain distinct.

The strict version1 hint value contains only nullable suggested `ReflexAction`,
short intent hypothesis, addressing/overall confidence, likely backend need and
`SpeechPriority`. It contains no response plan, generated speech, tool arguments
or hidden reasoning. AVAILABLE without an action means no suggestion, never
WAIT. Refusal, unavailable, timeout, invalid output and transport failure are
explicit separate outcomes. Raw decoding rejects duplicate keys, unknown fields,
nonfinite numbers, huge confidence values and excessive size/depth.

The consumer retains one expected request and checks source/admission/commit
freshness and expiry at actual consumption. Re-registering a request cannot
extend its deadline or rearm a consumed result; a late old reply leaves the newer
expectation intact. Hints cannot mutate Core, speak, submit work or authorize
actions. Ready useful content is not blocked by WAIT; Task06 and Task08 remain
the policy/output owners. No model client, worker or second provider reader is
introduced in09. Exact schema, fake/consumer API, bounds, diagnostics and Task10
integration obligations: [Task09 hint contract](09-hint-contract.md).

## GPT-Live mapping

Use client delegation. JARVIS owns backend model choice, tools, permissions, confirmations, and task state. Map Live transcript deltas to canonical events; delegation to BackBrainGateway; quiet backend updates to Live thinking context; spoken backend results to Live commentary; urgent redirects/stops to Live instructions. Live output transcripts populate generated-text evidence; only separate local playback evidence can establish device delivery, with unknown word alignment retained in the spoken ledger.

Do not treat an append acknowledgement as proof that content was spoken.

## Prompt stack

Example layers:

```text
base role prompt
architecture prompt
provider prompt
model-specific prompt
user editable override/addition
runtime ephemeral instructions
```

Settings shows every JARVIS-controlled layer, provenance, editability, resolved effective prompt, reset/default action, and validation. Provider-internal hidden prompts are explicitly out of scope.

## GPT-Live lifecycle

```text
OFF -> STARTING -> ACTIVE -> IDLE_CANDIDATE -> STOPPING -> OFF
```

Errors/loss of control converge on safe stop or an explicit `UNKNOWN_REAP_REQUIRED` state. Active/possibly billable states require a visible badge, elapsed timer, manual Stop, model label, and usage/cost information when available. Watchdog is runtime-level, not UI-only.

## Switching architectures

Switch by snapshotting Conversation Core, stopping the current frontend, finalizing usage, starting the new adapter, seeding minimal recent context and active-task summaries, then resuming canonical events. Active back-brain tasks continue unless cancelled separately.

Task17 implements the switch as a supervised process boundary. Settings writes
the validated target and emits an atomic request containing source/target
configuration IDs, architecture and conversation-model identity. Voice polls
that request, reads the authoritative Core conversation and work snapshots,
then stops its current frontend with reason `switch`. It refuses to exit while
the local close is pending, a durable Live lease remains nonterminal, or Core's
Live status cannot be read.

After confirmed teardown, Voice writes a bounded handoff containing the Core
conversation ID plus snapshot fingerprints/counts; it does not copy transcript
text, task summaries or provider state to disk. The supervisor recognizes this
clean exit and restarts Voice without spending the crash-restart budget. The
new process retains the conversation ID. On its first activation it re-reads
Core, selects at most eight recent canonical user/actually-heard assistant
messages under the existing 8192-character bound, and appends at most eight
current public task summaries as developer context. This projection never
mutates the voice ledger, and Core jobs continue throughout the Voice restart.

`requested -> snapshot -> stopping -> blocked|ready_for_restart -> applied ->
frontend_active` is observable through correlated trace records and Settings.
The final activation trace records old/new configuration, architecture/model
identifiers and the new session's prompt program, layer revisions, fingerprint
and application status without prompt text. Same-architecture model changes use
the same restart path. Failed replacement startup remains explicit; the old
frontend is never reported as restored.

## Task11 implemented backend bridge

The conversation controller submits already-admitted Core10 sources to `BackBrainTaskService`, backed by the existing `JobService` and SQLite Jobs. Source validation, dispatch reservation and Job creation are one transaction; an independent owned worker executes after acceptance. The conversation-scoped `/back-brain/tasks` projection rehydrates actual Jobs and typed unavailable advisory references without changing `VoiceTaskRecord` or fabricating user commits. Results and exact context dependencies remain durable; speech requires a separate frontend decision. Speculative work is explicitly unavailable until enforced restrictions exist. See [Core contracts and evidence](11-core-back-brain-evidence.md) and [runtime/controller composition](11-runtime-implementation-evidence.md) for the implemented limits and recovery semantics.
