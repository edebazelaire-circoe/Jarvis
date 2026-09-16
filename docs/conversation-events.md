# Conversation Events (contract, schema version 1)

Canonical record of what happened in a conversation, captured from backend
events and never rewritten by a model. Readable transcripts, exports and the live
timeline are projections of these events, not separate truths.

- Implementation (Level 3): `jarvis/domain/conversation_events.py` (pure domain:
  no I/O, no clock, no provider import).
- Storage (Level 3): port `jarvis/ports/v2.py::ConversationEventStore`, types
  `jarvis/domain/conversation_event_store.py`, adapter
  `jarvis/adapters/sqlite_conversation_events.py` (see Storage).
- Producers (Level 3, Core side): emitter `jarvis/core/conversation_event_emitter.py`,
  ingestion wire batch `jarvis/domain/conversation_event_ingest.py`, route
  `POST /v1/conversation-events` (see Producers and ingestion).
- Producers (Level 3, Voice and Control Center side, Slice 03b): forwarder
  `jarvis/runtime/conversation_event_forwarder.py` on the shared client batch loop
  `jarvis/runtime/core_forwarder.py` (also used by `WorkIngressForwarder`);
  producers `SpeechScheduler`, `RealtimeConversationBridge`, and `AgentTaskTracker`
  delegating sub-agent attribution to `jarvis/runtime/subagent_conversation.py`
  (see Forwarder, Sub-agent mapping rule).
- Conformance tests: `tests/unit/test_conversation_events.py`,
  `tests/unit/test_conversation_event_store.py`,
  `tests/integration/test_conversation_event_store_recovery.py`,
  `tests/unit/test_conversation_event_emitter.py`,
  `tests/unit/test_conversation_event_producers.py`,
  `tests/integration/test_conversation_event_ingest_protocol.py`,
  `tests/integration/test_conversation_event_production.py`,
  `tests/unit/test_conversation_event_forwarder.py`,
  `tests/unit/test_conversation_event_mouth_producers.py`,
  `tests/unit/test_conversation_event_voice_bridge.py`,
  `tests/unit/test_conversation_event_subagents.py`,
  `tests/integration/test_conversation_event_timeline.py`.
- Golden fixture: `tests/fixtures/conversation_events/overlapping_conversation.json`.
- Handoff: `tasks/jarvis-conversation-observability-timeline/` (Slice 01).

Status 2026-09-16: contract, durable store (Slice 02), Core-side producers plus
the ingestion route (Slice 03a), and the out-of-process producers (Slice 03b):
the voice runtime records Mouth speech, reflexes, tool spans and rejected turns,
the Control Center records sub-agent spans, both through a bounded forwarder that
posts batches to the ingestion route. Query/stream API is Slice 04.

## Relation to existing observability

`RuntimeJournal` (`runtime/trace.jsonl`, `{ts, kind, level, message, data}`) stays
the diagnostic telemetry. It has no version, no event id, no sequence and is
written concurrently by several processes, so it is not the conversation record.
A conversation event points to its diagnostic evidence through `trace_ref`
(below); it never depends on replaying trace lines as its only source.

The durable heard history (`ConversationService`, SQLite `turns`,
`voice_history_projections`, JSONL archive) stays authoritative for what the user
actually heard. Conversation events describe the timeline around it; they do not
replace the confirmed-range projection.

## Envelope

Every field is always present on the wire (null when absent). Unknown fields are
rejected.

| Field | Type | Rule |
|---|---|---|
| `schema_version` | int | `1`. Anything else is rejected. |
| `event_id` | string | `cev-` + 64 lowercase hex, derived (see Identity). |
| `event_type` | string | Closed vocabulary below. |
| `actor` | string | `user`, `mouth`, `brain`, `subagent`, `tool`, `system`; fixed by `event_type`. |
| `conversation_id` | id | Required. |
| `producer` | string | Emitting process/component, dotted lowercase token ≤ 64 (e.g. `core.brain_service`, `voice.speech_scheduler`, `control_center.agent_tasks`). |
| `visibility` | string | `public` or `diagnostic`; fixed by `event_type`. |
| `occurred_at` | time | Required. When the **fact** happened (producer clock), not when the event was emitted or retried. |
| `started_at` / `ended_at` | time or null | See Time and spans. |
| `span_id` | id or null | Required on span events. |
| `session_id`, `turn_id`, `correlation_id`, `task_id`, `work_id`, `speech_id`, `outcome_id` | id or null | Existing Jarvis identifiers, reused as-is. Required per type (table). `outcome_id` is the `BrainOutcomeService` record id. |
| `parent_event_id` | event id or null | Causal parent (e.g. sub-agent → brain work that spawned it). Must differ from `event_id`. |
| `trace_ref` | object or null | `{source, journal_kind, join_keys}`, see Trace correlation. |
| `content` | text or null | User-visible text or public status only, nonblank, ≤ 8192 chars. |
| `attributes` | object | Allowlisted keys, bounded values (see Redaction). Read-only after construction. |

An *id* is an opaque, nonempty, printable string ≤ 256 chars with no surrounding
whitespace (`voice_state.state_id`) and valid UTF-8 (no lone surrogate). IDs are
never parsed and compare **exactly**: code point equality, no Unicode
normalization, no case folding. `é` precomposed and `e` + combining accent are
different ids. All text (content, attribute strings, ids, `source_ids`) must be
valid Unicode; a lone surrogate is a `ConversationEventError`.

*time* on the wire is UTC ISO-8601 with milliseconds: `YYYY-MM-DDTHH:MM:SS.mmmZ`.
In memory it is a UTC `datetime` with millisecond precision; producers normalize
their clock reading with `to_event_time()`.

## Vocabulary and producer mapping

Shape: **I** instant, **O** span open, **C** span close. Visibility: **P** public,
**D** diagnostic. Content: req / opt / — (forbidden).

| event_type | actor | shape | vis | required ids | content | current source (journal kind / bus event) | owning file |
|---|---|---|---|---|---|---|---|
| `user.transcript.accepted` | user | I | P | correlation, turn | req | Core durable user turn (`VoiceTurnAdmissionService.persist_turn`, legacy `/turns`), see note 1 | `jarvis/core/voice_admission.py` |
| `brain.turn.accepted` | brain | I | D | correlation, turn | — | bus `brain.turn.accepted` | `jarvis/core/brain_service.py` |
| `brain.turn.failed` | brain | I | D | correlation | — | bus `brain.work.failed` with `work_id: null`; journal `core.brain.turn_failed` | `jarvis/core/brain_service.py` |
| `brain.message.published` | brain | I | P | correlation, outcome | req | journal `core.brain.outcome_retained` (available outcome) | `jarvis/core/brain_outcomes.py` |
| `brain.speech.requested` | brain | I | D | correlation, speech | req | bus `brain.speech.requested` | `jarvis/core/brain_service.py` |
| `brain.work.started` | brain | O | D | correlation, work | opt | bus `brain.work.started`; journal `core.brain.backend_task_started` | `jarvis/core/brain_service.py` |
| `brain.work.completed` | brain | C | D | correlation, work | opt | bus `brain.work.completed` | `jarvis/core/brain_service.py` |
| `brain.work.failed` | brain | C | D | correlation, work | opt | bus `brain.work.failed` (`work_id` set) | `jarvis/core/brain_service.py` |
| `brain.work.cancelled` | brain | C | D | correlation, work | opt | journal `core.brain.work_cancelled`; bus `brain.intent.revised` (cancel) | `jarvis/core/brain_service.py` |
| `mouth.speech.queued` | mouth | I | D | correlation, speech | opt | journal `voice.speech.queued` | `jarvis/runtime/speech_scheduler.py` |
| `mouth.speech.started` | mouth | O | P | correlation, speech | opt | journal `voice.speech.started` | `jarvis/runtime/speech_scheduler.py` |
| `mouth.speech.completed` | mouth | C | P | correlation, speech | opt | journal `voice.speech.completed` | `jarvis/runtime/speech_scheduler.py` |
| `mouth.speech.interrupted` | mouth | C | P | correlation, speech | opt | journal `voice.speech.interrupted` | `jarvis/runtime/speech_scheduler.py` |
| `mouth.speech.superseded` | mouth | C | D | correlation, speech | opt | journal `voice.speech.superseded` | `jarvis/runtime/speech_scheduler.py` |
| `mouth.speech.expired` | mouth | C | D | correlation, speech | opt | journal `voice.speech.expired` | `jarvis/runtime/speech_scheduler.py` |
| `mouth.speech.failed` | mouth | C | D | correlation, speech | opt | journal `voice.speech.speak_failed` (`code`, `exception_type` → `error_class`) | `jarvis/runtime/speech_scheduler.py` |
| `mouth.reflex.started` | mouth | I | P | correlation | opt | journal `voice.reflex.started` | `jarvis/runtime/speech_scheduler.py` |
| `subagent.started` | subagent | O | D | task | opt | journal `agent.subagent.started` | `jarvis/runtime/agent_tasks.py` |
| `subagent.finished` | subagent | C | D | task | opt | journal `agent.subagent.finished`, `status=completed` | `jarvis/runtime/agent_tasks.py` |
| `subagent.failed` | subagent | C | D | task | opt | journal `agent.subagent.finished`, `status=failed` **or any status not listed here** (raw status kept in `attributes.status`) | `jarvis/runtime/agent_tasks.py` |
| `subagent.stopped` | subagent | C | D | task | opt | journal `agent.subagent.finished`, `status` ∈ killed/stopped/interrupted (kept in `attributes.status`) | `jarvis/runtime/agent_tasks.py` |
| `tool.call.started` | tool | O | D | — (span = call id) | — | journal `tool.call` (arguments never copied) | `jarvis/runtime/realtime_audio.py` |
| `tool.call.finished` | tool | C | D | — (span = call id) | — | journal `tool.result` (result never copied) | `jarvis/runtime/realtime_audio.py` |
| `system.failure` | system | I | D | — | — | journal `core.brain.turn_settlement_failed` (Core); `voice.brain_turn_rejected` (03b) | `jarvis/core/brain_service.py`, `jarvis/runtime/realtime_audio.py` |

Notes:

1. **User turn producer (decided in Slice 03a).** Because `producer` is part of
   `event_id`, only one producer emits `user.transcript.accepted`: Core,
   `core.voice_admission`, once the user turn is durable and before any backend
   work. Live evidence (2026-09-16): the live voice architecture is
   `continuous_brain` (compatibility runtime), which submits through
   `POST .../brain-turns` -> `BrainOrchestrator.submit` -> `persist_turn`; the
   direct-admission route (`POST .../voice/admitted-turns`, journal
   `core.voice.turn_admitted`) is only used by the direct conversation
   architectures (simple / front_brain / duplex), hence its 0 live lines. Both
   routes share `persist_turn`, which is the emission point; the legacy
   architecture's `POST .../turns` (kind `user`) calls the same builder. The
   voice-side `voice.brain_turn_submitted` is written only after Core's
   acknowledgement and never covers typed or legacy input: it is not a producer.
   The golden fixture (Slice 01) still shows one turn from each former candidate;
   it is a codec fixture, not a producer reference.
2. **Failures carry no free text.** `core.brain.turn_failed` carries a raw error
   string (`data.error`); `brain.turn.failed` and `system.failure` therefore forbid
   `content` and keep only allowlisted `code` / `error_class` / `reason`.
3. **Sub-agent terminal statuses.** `completed` → `subagent.finished`;
   `killed`, `stopped`, `interrupted` → `subagent.stopped`; `failed` and any
   status unknown today → `subagent.failed`, with the raw status in
   `attributes.status`. An unknown status is never dropped and never reads as
   success.
4. **Reflex is instant.** The journal has `voice.reflex.started` but no reflex
   completion or interruption kind, so a span would stay `open` forever. It
   becomes a span only when such a terminal signal exists.
5. **Mouth content** is the text sent for playback (decided 2026-09-16). How
   much was heard stays in `attributes.played_ms` and in the durable heard
   projection; the readable transcript (Slice 06) must use the heard projection
   for Jarvis lines, not mouth `content`.

`public` = what the user said, heard or was shown. `diagnostic` = execution
evidence for the debug timeline. A `brain.speech.requested` is diagnostic because
a request is not a heard sentence; the heard counterpart is the `mouth.speech.*`
span. Mouth `content` is the text sent for playback; how much was heard stays in
`attributes.played_ms` and in the durable heard projection.

Adding a type is a contract change: update the enum, `_SPECS`, this table and the
tests together.

## Identity

```text
event_id = "cev-" + sha256_hex(json(["conversation-event", producer, event_type, conversation_id, *source_ids]))
```

(`derive_conversation_event_id`, compact JSON separators, UTF-8.) `source_ids` are
1 to 8 ids the producer already owns for the fact. Never a list position, counter
or clock reading. Re-emitting the same fact after a retry or restart yields the
same id. Recommended source ids:

| event types | source_ids |
|---|---|
| `user.transcript.accepted` | `(turn_id,)`: the Core durable turn id (`brain-turn-` + hash of conversation and correlation on the brain and admission paths, so stable across retries; for direct admission the correlation already encodes session and canonical turn) |
| `brain.turn.accepted`, `brain.turn.failed` | `(correlation_id,)` |
| `brain.message.published` | `(correlation_id, outcome_id)` |
| `brain.speech.requested`, `mouth.speech.*` | `(speech_id,)`; for mouth events the played chunk id (see Mouth speech identity) |
| `brain.work.*` | `(correlation_id, work_id)`: a later turn of the same conversation may reuse a work name |
| `mouth.reflex.started` | `(correlation_id, output_id)` |
| `subagent.*` | `(task_id,)` = the tracker's `conversation_key`: the task's first public id (`work_key`), frozen at attribution (see Sub-agent mapping rule) |
| `tool.call.*` | `(call_id,)` |
| `system.failure` | producer failure identity (e.g. `(correlation_id, code)`; voice rejected turn: `(correlation_id, "brain_turn_rejected")`) |

## Time, ordering and idempotency

- Producer timestamps are advisory across processes (UI, Voice, Core have
  independent clocks). A span's open and close always come from the same producer,
  so a span duration is measured on one clock.
- Canonical order is the **store sequence** assigned at append (Slice 02).
- A consumer without a sequence orders by `(occurred_at, event_id)`
  (`unsequenced_order_key`), which is deterministic.
- Append rule (`is_duplicate_event`): same `event_id` + identical payload = no-op;
  same `event_id` + different payload = `ConversationEventConflictError`.
- **Retries re-send the same fact.** A producer retry must rebuild the identical
  event: same `source_ids`, same `occurred_at` (fact time, never the retry time),
  same content and attributes. Stamping the emission time turns a replay into a
  conflict.
- **Duplicate admissions are not new facts.** When a source reports a replay
  (e.g. `voice_admission.py` admits with `duplicate: true`, `brain_service` returns
  `duplicate`), the producer does not emit a new event.
- **Store policy on conflict (implemented in Slice 02):** keep the first stored
  event, emit a diagnostic (journal, with both event ids, no content), and do not
  fail the producer's operation. The record stays append-only.
- `event_id` cannot be verified by a consumer: `source_ids` are not carried in the
  envelope. Only the producer can recompute it; consumers treat it as opaque.
- Events hash by `event_id` (consistent with equality, since equal events share
  the id); `attributes` is a read-only mapping and lists are stored as tuples.

## Instant and span events

- **Instant**: `started_at`, `ended_at`, `span_id` are null.
- **Span open**: `span_id` required, `started_at == occurred_at`, `ended_at` null.
- **Span close**: `span_id` required, `ended_at == occurred_at`, `started_at`
  optional (the producer's own start, e.g. `AgentTask.started_ms`) and never after
  `ended_at`.
- When the span has a natural id, `span_id` must equal it: `speech_id` (mouth
  speech), `work_id` (brain work), `task_id` (sub-agent). Tool spans use the call id.

Pairing (`reconstruct_conversation`): key = `(open event_type, span_id)`, where a
close maps to its open through `SPAN_OPENER`. Pairing does not depend on arrival
order. A close without an open renders from its `started_at` (or as an instant);
an open without a close renders as status `open` with `ended_at` null. Status =
last segment of the closing (or instant) type.

Reconstruction never raises on inconsistent data (a viewer must still render a
damaged record). It keeps the earliest open and the earliest close per key by
`(occurred_at, event_id)`, clamps a close earlier than its open to the open time,
keeps the first received copy of a conflicting duplicate, and records each case
on the item as `anomalies` entries `"<code>:<event_id>"` with codes
`duplicate_span_open`, `duplicate_span_close`, `close_before_open`,
`conflicting_duplicate`. It raises only for non-event input or events from
several conversations.

## Trace correlation

Jarvis has no `trace_id`. `trace_ref` is a join contract:

- `{"source": "runtime_journal", "journal_kind": K, "join_keys": [...]}`: a line of
  `runtime/trace.jsonl` is evidence of the event when `kind == K` and either
  `data.conversation_event_id == event_id` (written by instrumented producers,
  Slice 03; decisive when present) or every `join_keys` field (subset of
  `conversation_id, session_id, turn_id, correlation_id, task_id, work_id,
  speech_id, outcome_id`) is equal in `data`. Each named key must be set on the
  event. No keys means join by `conversation_event_id` only; a kind-only match
  never counts. Implemented by `trace_entry_matches`.
- `{"source": "agent_task", "journal_kind": null, "join_keys": ["task_id"]}`: the
  Control Center agent task trace, opened by `task_id` (`AgentTaskTracker.find`).

Source-specific join limits (checked against the live trace, 2026-09-16):

- `core.brain.outcome_retained` writes several lines per `correlation_id` (a
  `work_result` and a `turn_result`), so `brain.message.published` requires
  `outcome_id` and should join on `[correlation_id, outcome_id]`.
- `tool.call` / `tool.result` lines carry only `{call_id, arguments}` / `{call_id,
  result}`: no conversation, session or correlation id. Tool events must join by
  `conversation_event_id` only; a `trace_ref` with `join_keys` on a tool event is
  rejected. **Slice 04 obligation:** the debug view must never render raw
  `tool.call` / `tool.result` trace lines unredacted (they hold raw arguments and
  results).
- `agent.subagent.*` lines carry no `conversation_id`, and their `task_id` is the
  moving public id. Sub-agent events therefore join them by
  `conversation_event_id` only (no join keys), and map to a conversation only
  through Core's explicit scope (Slice 03b, Sub-agent mapping rule). The Control
  Center agent task trace stays reachable with the event's `task_id`
  (`AgentTaskTracker.find` falls back to `work_key`).

Events also join each other: user → brain by `correlation_id`/`turn_id`, brain
speech → mouth by `speech_id`, brain work → sub-agent by `work_id` and
`parent_event_id`.

## Producers and ingestion

Core owns the store; producers never open the state DB. Core producers record in
process through one emitter; other processes post batches to Core.

### Producer ownership

| event_type | emitting function (file) | producer | process | fact time (`occurred_at`) | `trace_ref` (journal kind, join keys) |
|---|---|---|---|---|---|
| `user.transcript.accepted` | `VoiceTurnAdmissionService.record_user_turn_accepted`, called by `persist_turn` (new admission only), by `LocalProtocolServer.append_turn` (legacy, kind `user`) and by the start-up backfill `backfill_user_turns_accepted` (`jarvis/core/voice_admission.py`) | `core.voice_admission` | Core | durable turn `created_at` | none (user entries have no drill-down) |
| `brain.turn.accepted` | `BrainOrchestrator.submit` (`jarvis/core/brain_service.py`), non-duplicate admission | `core.brain_service` | Core | acceptance | none (no Core journal line) |
| `brain.turn.failed` | `BrainOrchestrator._record_turn_failed`: backend exception (`_run_turn`), `FAILED` result or correlation mismatch (`_settle`) | `core.brain_service` | Core | failure | `core.brain.turn_failed` `[conversation_id, correlation_id]`; mismatch: `core.brain.backend_contract_violation` `[]` |
| `brain.message.published` | `BrainOutcomeService.retain`, first retention of an outcome (`jarvis/core/brain_outcomes.py`) | `core.brain_outcomes` | Core | outcome `created_at` | `core.brain.outcome_retained` `[correlation_id, outcome_id]` (a later kind maturation of the same outcome is journaled as `core.brain.outcome_matured`, with the same `conversation_event_id`, so the join matches exactly one line) |
| `brain.speech.requested` | `BrainOrchestrator._emit_speech` (backend speech, failure speech, notices) and `select_outcome` | `core.brain_service` | Core | `SpeechRequest.created_at` | selection only: `core.brain.outcome_selected` `[conversation_id, speech_id]` |
| `brain.work.started` | `_dispatch_backend_event` (`ACCEPTED`) | `core.brain_service` | Core | `BrainEvent.created_at` | `core.brain.backend_task_started` `[correlation_id, work_id]` |
| `brain.work.completed` | `_dispatch_backend_event` (`COMPLETED`) | `core.brain_service` | Core | `BrainEvent.created_at` | `core.brain.backend_task_result` `[correlation_id, work_id]` |
| `brain.work.failed` | `_dispatch_backend_event` (`FAILED`); `_settle_failed_turn_work` (orphan work of a failed turn, `code=turn_failed`) | `core.brain_service` | Core | event time / settlement | `core.brain.backend_task_result` `[correlation_id, work_id]`; orphan: none |
| `brain.work.cancelled` | `_cancel_work` | `core.brain_service` | Core | `BrainEvent.created_at` | `core.brain.work_cancelled` `[correlation_id, work_id]` |
| `system.failure` | `_run_turn`, settlement failure (`code=brain_turn_settlement_failed`) | `core.brain_service` | Core | failure | `core.brain.turn_settlement_failed` `[conversation_id, correlation_id]` |
| `mouth.speech.queued` | `SpeechScheduler._note_queued` (`_mouth_event`), first time only | `voice.speech_scheduler` | Voice | scheduler clock | `voice.speech.queued` `[]` (id only) |
| `mouth.speech.started` | `SpeechScheduler._speak`, after `speak_reserved` returned and admission still valid | `voice.speech_scheduler` | Voice | idem | `voice.speech.started` `[]` |
| `mouth.speech.completed` | `SpeechScheduler._speak` tail, provider status `completed`, only if this attempt recorded `started` | `voice.speech_scheduler` | Voice | idem | `voice.speech.completed` `[]` |
| `mouth.speech.interrupted` | `SpeechScheduler._speak` tail: barge-in (`reason=user_barge_in`, `played_ms`), provider status ≠ completed or admission invalidated (`reason=delivery_not_complete`); not after a failed start; only if this attempt recorded `started` (Mouth speech identity, span rule). Also the `CancelledError` branch of `_speak`: the voice goes to background while speaking (`SpeechScheduler.stop()`: auto-turn key / `voice.manual_cancel` → `mute()`, idle timeout, shutdown, bridge error) → `reason=voice_background` (`delivery_cancelled` for any other cancellation), provider `status`, `played_ms` when a barge-in cursor measured it; the tail never runs there, so exactly one close | `voice.speech_scheduler` | Voice | idem | `voice.speech.interrupted` `[]`; background cancel: none (no line is written) |
| `mouth.speech.superseded` | `SpeechScheduler._decision` (terminal status) and `_enqueue` (`superseded_on_arrival`) | `voice.speech_scheduler` | Voice | idem | `voice.speech.superseded` `[]` |
| `mouth.speech.expired` | `SpeechScheduler._decision` (`ttl`, `voice_background` on stop) | `voice.speech_scheduler` | Voice | idem | `voice.speech.expired` `[]` |
| `mouth.speech.failed` | `SpeechScheduler._speak` except branch (`code=speech_speak_failed`, `error_class`); no content when no start was recorded | `voice.speech_scheduler` | Voice | idem | `voice.speech.speak_failed` `[]` |
| `mouth.reflex.started` | `SpeechScheduler._maybe_speak_reflex` (`_reflex_event`) | `voice.speech_scheduler` | Voice | idem | `voice.reflex.started` `[]` |
| `tool.call.started` / `tool.call.finished` | `RealtimeConversationBridge._handle_tool_call` (`_tool_event`); a raising tool still closes (`status=failed|cancelled`, no `tool.result` line) | `voice.realtime_audio` | Voice | bridge UTC clock (`duration_ms` monotonic) | `tool.call` / `tool.result` `[]`; raised: none |
| `system.failure` (voice) | `RealtimeConversationBridge._submit_brain_turn`: non-503 refusal or transport error (`_turn_rejected_event`); a 503 deferral is not a failure | `voice.realtime_audio` | Voice | bridge UTC clock | `voice.brain_turn_rejected` `[]` |
| `subagent.started` | `SubagentConversations._record_start` (`subagent_conversation.py`), from `AgentTaskTracker._maybe_log_start` → `start_logged` (confirmed scope) or at turn confirmation (`settle`) | `control_center.agent_tasks` | Control Center | `AgentTask.started_ms` | `agent.subagent.started` `[]` (when that line was written after attribution) |
| `subagent.finished` / `failed` / `stopped` | `SubagentConversations._record_close`, from `AgentTaskTracker._log_finished` → `finish_logged` (`_finish`: notification, update, tool result, process start/stop) or at confirmation (`settle`); merge of two recorded halves (`stopped`, `reason=merged`, no line) | `control_center.agent_tasks` | Control Center | `AgentTask.ended_ms` (close `started_at` = recorded start) | `agent.subagent.finished` `[]` |

Every journal line named in a `trace_ref` (Core, Voice, Control Center) carries
`data.conversation_event_id` when its event was recorded, so `trace_entry_matches`
decides by id and joins exactly one line. A fact recorded twice (a request queued
again by `_replan`) is queued once: only the first line carries the id. Voice and
Control Center `trace_ref`s use no join keys: their lines either lack the
conversation ids (tools, sub-agents) or repeat them for later lines of the same
correlation (rejected-turn replays). Deliberately
not recorded: work progress (`brain.work.progress` has no vocabulary type), work
supersession (an intent revision, not a work end), a turn cancelled by Core
shutdown (the stop contract publishes nothing), Core-opened wake turns as user
input (`source=system`: their text is an internal prompt; the matching
`brain.turn.accepted` carries `attributes.source = "system"`), duplicate or
replayed admissions, and Core work state (`WorkStateStore` items carry no
conversation id; Claude sub-agents are Slice 03b's `agent.subagent.*` source).

Projection obligation (duplicate text): a turn that speaks its result
(`speech_result`, with `work_id`) and then ends with the same `public_summary`
(`turn_result`, no `work_id`) retains two distinct outcomes with identical text,
hence two `brain.message.published` events. The log stays faithful (no producer
dedupe). Public projections (Slice 05 timeline, Slice 06 readable transcript)
collapse consecutive `brain.message.published` with identical `content` for the
same `correlation_id`.

Content and failures: content is only text already public (the user's turn,
`public_summary` / `public_label`, the speech text, the outcome text). Failures
carry `code` and `error_class`; `error_class` is copied only when it is a
code-like token (`safe_error_class`: identifier or dotted class path of at most 64
characters), so a raw provider message (`core.brain.turn_failed` `data.error`)
never enters an event. Text above the content bound (8192) is not truncated: the
event is not recorded and `core.conversation_events.event_invalid` is diagnosed
(an outcome may hold up to 65536 characters).

### Emitter

`ConversationEventEmitter` (`JarvisCoreApplication.conversation_event_emitter`),
passed to `BrainOrchestrator`, `BrainOutcomeService` and
`VoiceTurnAdmissionService` (a `NullConversationEventEmitter` when none is wired):

- `record(...)` builds, validates and enqueues synchronously (no await, no I/O)
  and never raises into the caller; it returns the event id or None;
- bounded queue (`DEFAULT_QUEUE_CAPACITY` = 1024). **Overflow drops the newest
  event**, so queued events keep their causal order; counted
  (`dropped_queue_full`) and diagnosed once per overflow episode
  (`core.conversation_events.event_dropped`, warning, no content);
- one background task (started lazily on the running loop) appends batches of at
  most 32 through the store. Woken by an event, it first waits
  `DEFAULT_BATCH_LINGER_S` = 50 ms so the recording producer finishes its own
  state-DB awaits before a commit takes the shared repository lock (measured on
  the real Core: 40 submits 200 ms apart, 40/40 overlapped an event commit
  without the linger, 0/40 with it; commits 280 → 40-62, one per turn burst).
  A storage failure drops the batch (never retried in memory), counted (`dropped_store_error`), diagnosed once per failure episode
  (`core.conversation_events.append_failed`, error, `error_class` only), with
  `core.conversation_events.append_recovered` (info) when appends succeed again;
- a contract failure is counted (`invalid`) and diagnosed
  (`core.conversation_events.event_invalid`, warning, codec field-level message);
- `JarvisCoreApplication.stop()` stops it last, immediately before the state DB
  closes (after the Brain, scheduler, back-brain and job shutdown, so a stop that
  returns early on uncertain persistence is not lengthened by the drain): new
  events are refused (`dropped_stopped`), the queue drains for at most 2 s, the
  rest is counted (`dropped_shutdown`) and diagnosed; the final counters are
  journaled as `core.conversation_events.emitter_stopped` (info);
- the ingestion route (`append_now`) is acknowledged to its caller and counted
  apart (`ingest_appended`, `ingest_duplicates`, `ingest_conflicts`,
  `ingest_failures`): `enqueued = appended + duplicates + conflicts +
  dropped_store_error + dropped_shutdown` stays true for the queue alone;
- a failing diagnostic sink is counted (`diagnostic_failures`), never raised.

### Start-up backfill (user input)

`JarvisCoreApplication.start()` runs
`VoiceTurnAdmissionService.backfill_user_turns_accepted` right after
`state.initialize()`, before any route, task or recovery can admit a turn. It
re-records recent durable user turns through the same
`record_user_turn_accepted(turn, session_id=metadata["voice_admission"]["session_id"])`,
so a rebuilt event is identical to the original: the store answers `duplicate`
for what was committed and `appended` for what a crash lost (never `conflict`).

- Watermark: only user turns with `created_at >= latest recorded_at - 10 min`
  (`USER_EVENT_BACKFILL_MARGIN`); the latest `recorded_at` is the Core clock of the
  highest store sequence (`ConversationEventStore.latest_recorded_at`). An empty
  store backfills nothing, so pre-feature history is never converted.
- Bound: at most `USER_EVENT_BACKFILL_LIMIT` = 256 turns per start, newest kept
  (`StateRepository.list_turns_since`: conversations whose `updated_at` is past the
  watermark, then `idx_turns_conversation_time`, kind filtered in SQL). Wake turns
  (`source=system`) are skipped as at admission.
- Diagnostics, counts only: `core.conversation_events.user_backfill` (info:
  `candidates`, `recorded`, `limit`, `capped`, `margin_s`, or `reason=empty_store`);
  `core.conversation_events.user_backfill_failed` (error, `error_class`): Core
  still starts.
- Times are compared as stored ISO text; every Core writer stores UTC. A turn
  written with another offset could be missed by the SQL prefilter.

### Forwarder (Voice and Control Center)

`ConversationEventForwarder` (`jarvis/runtime/conversation_event_forwarder.py`),
one per process, built in `jarvis/app.py`: the voice process passes it to
`PersistentVoiceRuntime` (then to every `SpeechScheduler` and
`RealtimeConversationBridge`), the Control Center to `ControlCenter` (then to the
Claude agent's `AgentTaskTracker`). Transport: `CoreConversationEventTransport`,
its own loopback session, the session token file re-read after a 401. The send
loop, backoff and bounded close are the shared `CoreBatchForwarder`
(`jarvis/runtime/core_forwarder.py`), the same code as `WorkIngressForwarder`;
only the queue differs (append-only facts here, coalesced observations there).

- `record(...)`: same signature as the Core emitter
  (`ports.v2.ConversationEventRecorder`), same builder
  (`build_conversation_event`). Synchronous: build, validate, append to a deque.
  No await, no I/O on the normal path, never raises; returns the event id for
  the producer's journal line, or None when nothing was queued. Measured: p50
  29 µs / p95 36 µs per `mouth.speech.started` (5000 records).
- A fact recorded again while its id is among the last 4096 recorded ids is not
  queued again (`repeated`) and returns None, so only one journal line carries
  the id. Edge case: a repeat arriving after more than 4096 other events is
  queued again and its journal line gets the id too; the store answers
  `duplicate` (identical) or `conflict` (other `occurred_at`, first copy kept),
  and `trace_entry_matches` may then find two lines for that event. Producers
  repeat facts only within one speech (`_replan`), far below that window.
- Bounded queue (`DEFAULT_CAPACITY` = 1024). **Overflow drops the newest event**
  (`dropped_queue_full`), one `conversation_events.event_dropped` warning per
  overflow episode. An invalid fact is not queued (`invalid`), one
  `conversation_events.event_invalid` warning per (event type, producer) with the
  codec's field-level message.
- One task: waits for an event, lingers `flush_interval_s` (0.5 s), sends every
  queued event in batches of at most 32. Each ingestion POST is one FULL-sync
  commit on Core's shared state lock, so a burst of speech events costs one
  commit per 32 events instead of one per event (events queued while a POST is
  in flight follow in the same flush, without a second linger).
- Core unreachable, 503, 401 (token rotated), 408/429 or network error: the batch
  stays queued, `conversation_events.forwarder_unavailable` once per outage,
  retry after 1 s doubling to 30 s (no retry storm), `forwarder_restored` once
  when a batch is accepted again. Retrying is safe (same ids and `occurred_at`:
  `duplicate`).
- Core refuses a batch (400, 413, other 4xx, an event the codec refuses, or a
  JSON answer that does not match the batch, `ConversationEventAppendResponseError`):
  the batch is dropped (`dropped_rejected`), `conversation_events.forwarder_rejected`
  once per refusal series. An undecodable answer (`json.JSONDecodeError`,
  `UnicodeDecodeError`, e.g. a garbled body while Core restarts) is an
  unavailability: the batch is retried. `WorkIngressForwarder` already behaved
  this way (only HTTP 400 is a refusal there).
- `aclose()` (voice process after `voice.close()`, Control Center after the agents
  stopped, so interrupted sub-agents and expired speech are sent): refuses new
  events (`dropped_closed`), one last send bounded by 2 s, the rest counted
  (`dropped_shutdown`), final counters in `conversation_events.forwarder_stopped`.
  With Core down, each bounded close waits its full 2 s: the Control Center stop
  takes up to ~4 s more (work ingress 2 s, then conversation events 2 s), the
  voice process up to ~2 s more after `voice.close()`.
- Identity once closed: `enqueued = appended + duplicates + conflicts +
  dropped_rejected + dropped_shutdown`.

Loss bounds: a hard kill of the voice or Control Center process loses what is
queued (≤ 1024 events; normally the last 0.5 s of activity plus any Core outage
backlog); a Core outage keeps up to 1024 events then drops the newest; a Core
refusal drops that batch. Every loss is counted, and journaled once per episode.
None of these events is rebuilt after a crash (unlike Core's user-turn backfill).

Hot-path cost (scratch probe, real `SpeechScheduler` with fake session, 3 × 300
speeches, alternated variants): dispatch latency p50/p95 0.105/0.157 ms without
recorder, 0.179/0.261 ms with the forwarder (fake Core, 5 ms commits),
0.185/0.256 ms with a real Core in the same loop; `voice.speech.started` 0.117/0.174 ms
vs 0.257/0.375 ms and 0.265/0.368 ms. Journal disk writes are excluded in both.

### Mouth speech identity

`SpeechScheduler._enqueue` splits a Core speech request into paragraph chunks:
a one-paragraph request keeps its `speech_id`, a longer one gets a `uuid5` id per
chunk. Mouth events use the played chunk id (`speech_id` = `span_id`, source id)
and set `parent_event_id` to the Core `brain.speech.requested` event id derived
from the request id (`core.brain_service`, `(speech_id,)`), only for requests
received from `/v1/events` (Core records every one it publishes). Controller
speech enqueued locally has no parent.

Span rule for a delivery attempt (`_speak`): its `completed` / `interrupted`
close (tail or cancellation) is recorded **only if that same attempt recorded
`mouth.speech.started`**. A cancel landing during `speak_reserved`, or an output
invalidated before its start, records no close (the `queued` instant stays): a
close without an open would render as a public `interrupted`/`completed` item
carrying text the user never heard. `mouth.speech.failed` is kept when the start
failed before being recorded (diagnostic evidence that the speech was never
played, joined to `voice.speech.speak_failed`), but then **without content**.
`superseded` / `expired` closes of speech that was never attempted are
diagnostic and carry the withheld text.

`content` (the text sent for playback) is on `started`, or on a `superseded` /
`expired` close whose speech never started, never repeated on the other events;
text above 8192 characters is omitted, the event is still recorded. Attributes: `kind`,
`priority`, `output_id`, and on closes `reason`, `status` (provider status),
`played_ms`, `code`, `error_class` (code-like tokens only).

### Sub-agent mapping rule

A sub-agent span is recorded only when its conversation is explicitly known,
never inferred from labels, descriptions or timing:

1. `ControlCenterBrainBackend` sends `/api/agent/ask` a `conversation` block
   `{conversation_id, correlation_id, work_id}` (distinct from `context`; the
   Control Center never gives it to the prompt composer). The route builds a
   `SubagentConversationScope` (invalid ids dropped, never repaired) and passes it
   to `ClaudeLocalAgent.ask(conversation_scope=...)`.
2. Before writing the message, `AgentTaskTracker.begin_conversation_turn(scope,
   message_uuid)` opens a pending attribution. It is ambiguous when a brain turn
   was already running (`busy_at_send`) or another message was written meanwhile
   (panel/console `send`, a question without scope: `note_unscoped_input`).
3. A top-level `Agent` call observed while the pending attribution is not
   ambiguous is attributed **provisionally**; its journal lines already carry
   the id the event would have. A nested sub-agent inherits its parent task's
   scope (explicit `parent_tool_use_id`).
4. At the next top-level `result`: consumed uuids exactly `{message_uuid}` →
   confirmed, the spans are recorded (start, and close if already finished); our
   uuid among several (merged turn), a CLI that does not report consumed uuids, or
   an ambiguous turn → rejected; a result that does not consume our message
   (spontaneous `task-notification` turn, panel message) → its provisional tasks
   are rejected and the attribution stays pending for our turn. A brain process
   start/stop rejects provisional tasks. A new scoped question rejects the
   previous unresolved one.
5. A rejected or never-attributed sub-agent records nothing: counted in
   `AgentTaskTracker.conversation_counts[reason]` (`SubagentConversations.counts`) and journaled once per task as
   `agent.subagent.conversation_unattributed` (`reason` ∈ `no_conversation_scope`,
   `other_turn`, `turn_ambiguous`, `turn_unverifiable`, `turn_unresolved`,
   `process_stopped`). Its journal lines may carry the provisional id of an event
   that was never recorded (a pointer to nothing, never a wrong join).
6. A scoped turn whose `result` names no consumed message (`user_message_uuids` /
   `user_message_uuid` absent) is a CLI regression: counted
   (`unverifiable_results`) and journaled once per tracker as
   `agent.subagent.attribution_unverifiable` (warning, with `cli_version` from the
   `system/init` event's `claude_code_version`), even when no sub-agent was
   launched. Evidence 2026-09-16: CLI ≥ 2.1.270 carried the uuids on 90/90 scoped
   results, older CLIs never did.

**PM decision (2026-09-16): the strict rule is kept** (verified on CLI 2.1.273).
Consequences, accepted and documented: sub-agents launched by spontaneous turns
(`task-notification`) or by panel/console messages are not recorded; a foreground
sub-agent's start reaches Core only when its turn `result` arrives (its
`occurred_at` stays the real start).

Stable source id: `conversation_key`, the task's `work_key` (first public id,
usually the `tool_use_id`) frozen at attribution. `AgentTask.id` moves to the
`task_id` when `task_started` arrives; the key does not. When two halves merge,
the survivor keeps its key (or inherits the absorbed half's); if both halves had
recorded a start, the absorbed span is closed as `subagent.stopped`,
`reason=merged`. Parent: `parent_event_id` = Core's `brain.work.started` id derived
with `core.brain_service` and `(correlation_id, work_id)`, only when both came in
the scope; a nested sub-agent points to its parent sub-agent's start. Status
mapping as note 3 (raw status kept in `attributes.status`). Content: the
description on `subagent.started` only; the summary never leaves the tracker.
Attributes: `provider`, `background`, `depth`, `subagent_type`, `model`, and on
closes `status`, `tokens`, `tool_uses`, `duration_ms`.

### Tool redaction

`tool.call` / `tool.result` journal lines keep the raw `arguments` / `result`
(unchanged telemetry). Tool events carry `tool_name` (a code-like token, else
`unknown`), `arguments_redacted: true`, and on the close `status` (the result's
`status` or `disposition` token, else `ok`/`error` from its `ok` flag; `failed` or
`cancelled` when the call raised, with `error_class`) and `duration_ms`. No
content, no join keys, no correlation id (the surface does not know which turn a
tool call belongs to). A call without `call_id` records nothing.

### Known limits

- **Crash windows.** The queue is memory only. An event is committed about 55-70 ms
  after `record()` when the store is idle (linger 50 ms + one FULL-sync commit;
  scratch probe on the real Core, 30 turns with a 300 ms backend: p50/p95/max
  `user.transcript.accepted` 65/70/72 ms, `brain.turn.accepted` 60/65/67 ms,
  `brain.speech.requested` 60/64/70 ms, `brain.message.published` 56/65/72 ms,
  `brain.work.*` 56-65/60-68/64-71 ms), longer when the state DB is busy. A hard
  kill inside that window loses the event:
  - `user.transcript.accepted` is repaired by the start-up backfill (tested with
    a real `os._exit` inside a widened window,
    `test_crash_between_durable_admission_and_emitter_commit_is_repaired_on_restart`);
  - every Brain event (`brain.turn.accepted`, `brain.speech.requested`,
    `brain.message.published`, `brain.work.*`, `brain.turn.failed`,
    `system.failure`) is **accepted lost** (PM decision, option A): no rebuild.
- **Hot-path cost.** No await is added, but appends share the state repository
  connection and lock: an append in progress serializes with other state writes
  for one commit (`synchronous=FULL`). QA measured the speech-publish path at
  about +70-90 ms p95 under load. Voice-side producers (Slice 03b) must batch
  through their own bounded forwarder, never one request per event on the
  speech path.
- **Stop bound.** The 2 s drain bound cannot interrupt a native SQLite call that
  holds the repository lock: cancellation waits for it to return (QA measured a
  4.01 s stop with a stuck store).
- **Early stop.** When `stop()` returns early (`state_persistence_unknown` /
  `cleanup_unknown`, back brain or jobs still owned), the emitter is not stopped
  and keeps draining into the still-open repository; the next `stop()` call
  stops it.
- **Content bound.** Text above 8192 characters is not recorded (diagnosed).
  Mouth events omit such text and keep the event.
- **Voice / Control Center loss.** See Forwarder: memory queue, no rebuild after
  a crash of those processes.
- **Not recorded (03b).** Direct-conversation architectures (simple, front_brain,
  duplex) have no mouth lane yet: their `ConversationCandidate` carries no speech
  text and no Core speech request (tracked limit; the live architecture is
  continuous_brain). Reflex completion (no terminal
  signal, note 4; the reflex text is generated by the provider and unknown to
  the scheduler), `voice.speech.stream_failed` / `stream_closed` (a transport
  incident with no stable fact identity), `voice.brain_turn_deferred` (503, Core
  stopping: the provider replay is accepted later), background shell tasks
  (not sub-agents), Codex (no verified sub-task format).
- **Sub-agent attribution** needs the Claude CLI to report consumed message uuids
  in `result`; foreground sub-agents are confirmed when their turn ends, so their
  start reaches Core at that moment (with its real `occurred_at`). A sub-agent
  whose brain process dies before the turn result is not recorded.
- **Slice 04 trace drill-down** must start from stored events and resolve their
  `trace_ref`; it must never resolve a `conversation_event_id` found in a journal
  line (a provisional sub-agent line can name an event that was never stored).

### Ingestion route

`POST /v1/conversation-events` (bearer token and `X-Jarvis-Protocol` like every
`/v1` route). Client: `LocalCoreClient.append_conversation_events(events)`.

- Body: `{"schema_version": 1, "events": [1..32 encoded events]}`, exact keys
  (`encode_conversation_event_batch`). Every event is decoded through the codec.
- 400 `invalid_request`: malformed JSON, wrong shape or version, 0 or more than 32
  events, any codec error (message `events[i]: <field rule>`, never a value), or a
  Core-owned event (actor `user` or `brain`, or producer `core` / `core.*`). The
  whole batch is rejected, nothing is appended; diagnosed as
  `core.conversation_events.ingest_rejected`.
- 200: `{"schema_version": 1, "results": [{"event_id", "sequence", "status"}]}` in
  batch order, `status` one of `appended`, `duplicate`, `conflict` (first copy
  kept, store diagnostic).
- 503 `conversation_events_unavailable`: storage failed, the emitter is stopped
  or the repository is closed (Core stopping); nothing acknowledged, retrying the
  identical batch is safe (same ids, same `occurred_at`).
- Body limit: `MAX_CONVERSATION_EVENT_BATCH_BODY_BYTES` = 6 MiB, set as the Core
  app's `client_max_size` (so it applies to every `/v1` route). The largest
  contract-valid batch encoded by `json.dumps` (astral characters escape to 12
  bytes) is 4 446 461 bytes (4.24 MiB), above aiohttp's 1 MiB default
  (`worst_case_ingest_batch`, tested end to end). A larger body gets aiohttp's
  plain-text 413, which the client raises as `CoreProtocolError(413, "http_error")`
  (any non-JSON error response maps the same way).
- The client encodes (and so validates) before any network call, streams the
  body (`io.BytesIO`: aiohttp warns on raw bodies above 1 MiB) and checks that the
  results answer every event, in order.
- Accepted risk: Core cannot verify that an ingested `event_id` belongs to its
  producer (ids are derived from source ids the envelope does not carry). A
  non-Core process could pre-occupy the id of a future event of another non-Core
  producer, whose append then becomes `conflict`. Core-owned types and `core.*`
  producers are refused, and the route is loopback-only behind the session
  bearer token.

## Visibility and redaction

Allowlist first, denylist as defense in depth:

1. Envelope fields, event types, actors, visibilities and `trace_ref` fields are
   closed sets; unknown names are rejected.
2. `attributes` keys must be in `ATTRIBUTE_KEYS`: `addressing, arguments_redacted,
   background, code, delivery, depth, duplicate, duration_ms, error_class,
   interrupted_speech_id, job_id, kind, model, output_id, played_ms,
   priority, provider, reason, revision, source, status, subagent_type, tokens,
   tool_name, tool_uses`. At most 24 keys; values are JSON scalars (strings ≤ 512
   chars, integers |n| ≤ 2^53, finite floats) or lists of ≤ 16 scalars; ≤ 4096
   encoded bytes. No nested objects.
3. Forbidden names are refused at **any depth** of a raw payload (top level,
   `trace_ref`, attributes, nested values) with `ConversationEventRedactionError`:
   reasoning, thinking, thought(s), chain_of_thought, scratchpad, cot, signature,
   audio, pcm, wav, bytes, prompt(s), system_prompt, secret(s), password, token,
   api_key, access/refresh token, credential(s), authorization, cookie,
   arguments, args, raw_arguments, tool_input, input (snake, kebab, dotted and
   camelCase spellings). Raw `bytes` values are refused too. Container nesting
   deeper than 8 levels (or a cyclic structure) is a `ConversationEventError`
   before any recursion limit is reached.
4. `content` is text the user saw/heard/said or a public status. Hidden reasoning,
   prompts, raw tool arguments/results and provider payloads never go there;
   producers copy only the public field they already publish (e.g. speech text,
   `public_summary`, sub-agent description).
5. Tool calls carry no content: `tool_name` and `arguments_redacted: true` only.

**`agent.event` is never a source.** `claude_local.py` / `codex_local.py` journal
raw provider stream events, thinking blocks included (Decision 43,
`docs/OPERATIONS.md`). No event type maps to it, and a `trace_ref` naming
`agent.event` (or `agent.event.*`) is rejected. Sub-agent spans come from
`agent.subagent.*`, which carries curated fields only.

Error messages name the field path and the rule, never the offending value.

## Codec and errors

- `encode_conversation_event(event) -> dict` (JSON-ready; re-validated before return).
- `decode_conversation_event(payload) -> ConversationEvent` (redaction scan, exact
  fields, version, vocabularies, per-type rules).
- `validate_conversation_event(payload) -> None`.
- Errors: `ConversationEventError(ValueError)`; subclasses
  `ConversationEventRedactionError` and `ConversationEventConflictError`.
- Constructing `ConversationEvent` runs the same validation: an invalid event
  cannot exist in memory.

## Reconstruction

`reconstruct_conversation(events, include_diagnostic=True)` returns
`ConversationItem(item_id, actor, event_type, status, visibility, started_at,
ended_at, text, span_id, event_ids, anomalies)` sorted by `(started_at, item_id)`
for one conversation (mixed conversations raise). Identical duplicates collapse;
inconsistencies become `anomalies` (see Instant and span events).
For a span, text is the close's content when present, otherwise the open's.
`include_diagnostic=False` keeps only public items (the readable transcript
basis). Overlaps are preserved: a sub-agent span may cover several user and mouth
items.

## Storage

The store is the `conversation_events` table of the Core operational state DB
(`<data_root>/state/jarvis.sqlite3`, `SQLiteStateRepository`). It shares that
repository's file, single connection, asyncio lock, worker thread, lifecycle and
cancellation guarantee; there is no second database or connection model.

**Ownership.** Core owns the store. Only the Core process opens the state DB;
other processes (voice runtime, Control Center) must reach the log through Core
protocol paths (Slice 03/04), never by opening the file.

### Schema (state DB schema version 2)

```sql
CREATE TABLE conversation_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    conversation_id TEXT NOT NULL,
    session_id TEXT,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    visibility TEXT NOT NULL,
    occurred_at TEXT NOT NULL,          -- wire time, sorts lexicographically
    recorded_at TEXT NOT NULL,          -- Core clock when append* is called (not the commit instant)
    span_id TEXT, turn_id TEXT, correlation_id TEXT, task_id TEXT, work_id TEXT, speech_id TEXT,
    outcome_id TEXT,
    data TEXT NOT NULL);                -- encoded canonical event: the source of truth
CREATE INDEX idx_conversation_events_conversation ON conversation_events(conversation_id, sequence);
CREATE INDEX idx_conversation_events_occurred ON conversation_events(occurred_at, sequence);
-- for each of session_id, turn_id, correlation_id, task_id, work_id, speech_id, outcome_id, span_id:
CREATE INDEX idx_conversation_events_<id> ON conversation_events(<id>, sequence) WHERE <id> IS NOT NULL;
```

No foreign key to `conversations`: the log records a fact even when the
operational conversation row is missing. The extracted columns are copies for
indexing only.

### Append, duplicates and conflicts

- `append(event)` / `append_many(events)` (0 to `MAX_APPEND_BATCH` = 32; empty
  returns `()`) encode every event through the codec **before** touching storage
  (an invalid value raises `ConversationEventError`, nothing is written), then
  run one `BEGIN IMMEDIATE` transaction for the whole batch.
- Per event: no stored copy: insert, `AppendResult(event_id, sequence,
  appended)`; identical stored copy (`is_duplicate_event`): `duplicate` with the
  stored sequence, nothing written; different payload: `conflict` with the
  stored sequence, first copy kept. A stored copy that no longer decodes is also
  a `conflict` (reason `stored_copy_unreadable`). Duplicates and conflicts inside
  one batch follow the same rule.
- A conflict never raises. After commit the store emits
  `core.conversation_events.append_conflict` (warning) with `event_id`,
  `stored_sequence`, `reason`, `conversation_id`, `event_type`, `producer`, never
  content. A failing diagnostic sink is counted (`diagnostic_failures`) and never
  fails the append.
- A storage failure (SQLite error: disk full, lock timeout...) rolls the batch
  back and raises `ConversationEventStoreError`: **not acknowledged**, safe to
  retry whole. Using a closed repository raises `RuntimeError("state repository
  is not initialized")`.

### Durability and recovery

- `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=FULL` (set explicitly at
  initialize; FULL syncs the WAL on every commit). `append*` returns only after
  `COMMIT`, so an acknowledged event survives a process crash and an OS
  crash/power loss. SQLite busy timeout is the `sqlite3.connect` default (5 s).
- A process killed mid-batch leaves no partial batch: the uncommitted
  transaction is discarded by WAL recovery at next open
  (`tests/integration/test_conversation_event_store_recovery.py` kills a child
  process inside the third INSERT of a batch). Acknowledged events are intact and
  sequences continue.
- `initialize` still runs `PRAGMA quick_check` and refuses a corrupt file; the DB
  is never repaired by deletion.
- Several connections on the same file (tested with two repositories) serialize
  writers through `BEGIN IMMEDIATE`; sequences stay unique and a racing identical
  append yields one `appended` and one `duplicate`.

### Sequence and cursor

- `sequence` is assigned at insert, strictly increasing, and **never reused**
  (`AUTOINCREMENT`), even when retention deletes the newest rows. It is the
  canonical order; producer `occurred_at` never reorders stored events (equal or
  out-of-order timestamps keep append order).
- Event pages: ascending sequence, `after_sequence` cursor (exclusive, default
  0), `limit` 1..`MAX_EVENT_PAGE_LIMIT` = 500 (default 100). A page returns
  `next_cursor` = last **scanned** sequence (or the request cursor when empty),
  `has_more`, and `skipped_rows`. Events appended while a reader pages always
  land after its cursor, so incremental polling never misses or repeats an event.

### Queries (port `ConversationEventStore`)

| Method | Returns |
|---|---|
| `get_event(event_id)` | `StoredConversationEvent(sequence, recorded_at, event)` or None (absent **or** unreadable, the latter diagnosed) |
| `latest_recorded_at()` | `recorded_at` of the highest sequence, or None (empty store, or unparseable: diagnosed as `row_unreadable`); used by the start-up backfill |
| `list_conversation_events(conversation_id, after_sequence, limit)` | event page |
| `list_events_in_time_range(start, end, conversation_id?, after_sequence, limit)` | event page, `start <= occurred_at < end` (producer clock, ms), sequence order |
| `list_events_by_id(field, value, conversation_id?, after_sequence, limit)` | event page; `field` in `LOOKUP_FIELDS` = session, turn, correlation, task, work, speech, outcome, span id |
| `list_conversations(before_sequence?, limit)` | summaries by most recent store activity; `next_cursor` = last row's `last_sequence`, pass as `before_sequence` |
| `list_sessions(conversation_id, after_sequence, limit)` | per-session summaries (null session is its own group) by first appearance; `next_cursor` = last row's `first_sequence` |
| `apply_retention(policy, archive?)` | `RetentionReport` |

Summaries (`ConversationEventSummary`) carry `event_count`, first/last sequence,
first/last `occurred_at` and last `recorded_at`. `event_count` is the **raw stored
row count**: rows that do not decode are included (summaries do not decode rows).
Summary `limit` is 1..`MAX_SUMMARY_PAGE_LIMIT` = 100 (default 50). Listings
aggregate over the table (no summary table): fine at Jarvis scale, to revisit if
the log reaches millions of rows.

`list_conversations` is not a snapshot. A conversation that receives an event
between two page requests gets a new `last_sequence` above the cursor: it moves to
the top of the listing and **is omitted from the following pages** of that walk.
A client that needs every conversation refreshes page one after walking.

A summary group whose aggregated time columns do not parse as wire times (a
damaged `occurred_at` or `recorded_at`) is skipped, counted in the page's
`skipped_summaries`, and diagnosed once per group per store instance as
`core.conversation_events.summary_unreadable` (error) with the ids, the group's
first/last sequence and the field-level detail, never the value. The cursor comes
from the integer sequence columns, so paging walks past a skipped group.

The time-range query matches event **instants** (`occurred_at`): a span that
started before `start` and closes after `end` has no event in the window. A
timeline window that must show such spans reads the conversation by cursor.

Out-of-range limits, negative cursors, unknown lookup fields, blank ids, naive or
inverted time bounds raise `ValueError` (caller error).

### Undecodable rows

Every read decodes `data` through `decode_conversation_event` and checks that the
extracted columns equal the payload and that `recorded_at` parses. A row failing
any check (`invalid_json`, `invalid_event`, `column_mismatch`,
`invalid_recorded_at`) is skipped, counted in the page's `skipped_rows` and in
the store's `unreadable_rows`, and diagnosed as
`core.conversation_events.row_unreadable` (error) with `sequence`, `reason` and
the codec's field-level detail, never the value. The diagnostic is emitted once
per sequence per store instance (live polling would repeat it); counting never
stops. The row is not modified.

### Retention

`ConversationEventRetentionPolicy(enabled=False, max_age=180 days,
max_conversations_per_run=16)` (at most 64 per run). **Disabled by default**, and
nothing in Core schedules it yet. When enabled, a conversation's events are
deleted only when all of these hold. They are one SQL predicate
(`_CANDIDATES`), evaluated for selection and again inside the delete transaction:

1. its `conversations` row exists with status `closed` (an active, reopened or
   unknown conversation is never touched);
2. its newest `recorded_at` (Core clock, not producer clocks) is older than
   `now - max_age`;
3. every span it opened has a close of a matching type for its `span_id`;
4. every row is readable enough to judge: known `event_type`, valid JSON `data`,
   `occurred_at` and `recorded_at` in wire format (and the aggregated times parse);
5. no event was appended since selection (`max(sequence)` unchanged).

Conversations failing 3 or 4 are **blocked**: they are excluded before the
per-run budget, so they never starve prunable conversations, and are only counted
in `RetentionReport.blocked_open_span` / `blocked_unreadable` and in the run
diagnostic. `skipped` lists conversations selected in this run that could not be
pruned (`not_closed`, `new_activity`, `open_span`, `unreadable` on re-check, or
`archive_failed`).

**Known limit: orphaned spans.** A span whose close was never recorded (for
example a sub-agent running when Core crashed) keeps its conversation blocked
forever. This is the safe default: retention never auto-closes a span and never
deletes history it cannot prove finished. Clearing such a conversation needs an
explicit decision (a producer-side terminal event), not a retention change.

The optional `archive(summary)` hook runs before the delete and may page the
events through the store; if it raises, the events are kept (`archive_failed`,
diagnostic `core.conversation_events.archive_failed`). Only `conversation_events`
rows up to the selected sequence are deleted; turns, conversations and other
tables are never touched. Each enabled run emits
`core.conversation_events.retention_applied` (info) with counts.

### Migration

The state DB `schema_version` goes 1 to 2 through `sqlite_state._MIGRATIONS`:
forward-only, additive, one `BEGIN IMMEDIATE` transaction per step (DDL + version
bump), version re-read under the write lock; a failing `ROLLBACK` is attached to
the original error as a note, never raised instead of it. A fresh file starts at
v1 and takes the same steps, without backup. A crash mid-migration rolls back and
the next start retries.

Before the first step on an **existing** file, `SQLiteStateRepository` takes a
one-time online backup (`sqlite3.Connection.backup`) to `<db>.v1.bak` next to
the DB (written as `<db>.v1.bak.partial`, renamed when complete). An existing
`.bak` is never overwritten. If the backup fails, initialization raises
`RuntimeError` before any schema statement runs: the file stays v1. Rollback
procedure: [state model](state-model.md) (persistence section).

An existing v1 file (tested with the real v1 schema in
`tests/fixtures/sqlite_state/state_v1.sql`; a read-only backup copy of the live
`data/state/jarvis.sqlite3` is exercised only on opt-in with
`JARVIS_TEST_REAL_STATE_DB=1`, because it reads user data) upgrades in place with
every row kept. A v2 file
opened by a pre-Slice-02 binary fails with `state DB schema 2 is newer than
supported 1`; a future v3 file fails the same way for this binary.

Changing the event payload schema (event `schema_version` 2) will need a state
migration or a read-time upcaster; until then a stored row that is not event
version 1 is an unreadable row, never silently reinterpreted.

## Validation

```powershell
$env:PYTHONDONTWRITEBYTECODE=1; .venv/Scripts/python.exe -W error::ResourceWarning -m pytest -q -p no:cacheprovider tests/unit/test_conversation_events.py tests/unit/test_conversation_event_store.py tests/integration/test_conversation_event_store_recovery.py tests/unit/test_conversation_event_emitter.py tests/unit/test_conversation_event_producers.py tests/integration/test_conversation_event_ingest_protocol.py tests/integration/test_conversation_event_production.py tests/unit/test_conversation_event_forwarder.py tests/unit/test_conversation_event_mouth_producers.py tests/unit/test_conversation_event_voice_bridge.py tests/unit/test_conversation_event_subagents.py tests/integration/test_conversation_event_timeline.py
```
