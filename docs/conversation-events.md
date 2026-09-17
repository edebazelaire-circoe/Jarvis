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
- Query and live API (Level 3, Slice 04): wire module
  `jarvis/domain/conversation_event_query.py`, Core service
  `jarvis/core/conversation_event_query.py`, `GET /v1/conversation-events...`
  routes and typed `LocalCoreClient` reads, Control Center view
  `jarvis/runtime/conversation_event_view.py` and trace drill-down
  `jarvis/runtime/conversation_event_trace.py` (see Query and live API).
- Timeline UI (Slice 05): `jarvis/runtime/control_center_timeline.js`
  (pure logic + browser block) and the `#timeline` view of
  `jarvis/runtime/control_center.html` (see Timeline UI).
- Projections (Slice 06): readable transcript
  `jarvis/domain/conversation_transcript.py`, JSONL export and offline importer
  `jarvis/domain/conversation_event_export.py`, bounded search
  `jarvis/domain/conversation_event_search.py` (scan in the SQLite adapter),
  Core routes `GET /v1/conversation-events/{transcript,export,search}`, Control
  Center `GET /api/conversations/{transcript,export,search}`, timeline panels
  (see Readable transcript, JSONL export, Search, Operations).
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
  `tests/integration/test_conversation_event_timeline.py`,
  `tests/unit/test_conversation_event_query_contract.py`,
  `tests/unit/test_conversation_event_trace.py`,
  `tests/integration/test_conversation_event_query_protocol.py`,
  `tests/integration/test_control_center_conversation_events.py`,
  `tests/unit/test_control_center_timeline_js.py`,
  `tests/unit/test_control_center_timeline_ui.py`,
  `tests/unit/test_conversation_transcript.py`,
  `tests/unit/test_conversation_event_export.py`,
  `tests/unit/test_conversation_event_search.py`,
  `tests/integration/test_conversation_event_projections_protocol.py`,
  `tests/integration/test_control_center_conversation_projections.py`,
  `tests/integration/test_conversation_event_rollout_gate.py` (end-to-end rollout gate),
  `tests/unit/test_conversation_event_query_limits.py` (hot-path admission).
- Golden fixtures: `tests/fixtures/conversation_events/overlapping_conversation.json`,
  `transcript_plain.txt`, `transcript_detailed.txt` (rendering of
  `tests/fakes/conversation_events.transcript_scenario`).
- Handoff: `tasks/jarvis-conversation-observability-timeline/` (Slice 01).

Status 2026-09-16: contract, durable store (Slice 02), Core-side producers plus
the ingestion route (Slice 03a), and the out-of-process producers (Slice 03b):
the voice runtime records Mouth speech, reflexes, tool spans and rejected turns,
the Control Center records sub-agent spans, both through a bounded forwarder that
posts batches to the ingestion route. Slice 04 adds the authenticated query
routes, a bounded long-poll, the Control Center proxy and the redacted trace
drill-down (Query and live API). Slice 05 adds the live four-lane timeline in
the Control Center (Timeline UI). Slice 06 adds the readable transcript, the
JSONL export with its offline importer, bounded search, and the end-to-end
rollout gate (real stacks, Core hard crash and restart); operations, sizing and
privacy boundaries are in Operations.

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
   projection. **PM decision, Slice 06:** the readable transcript is derived
   from events only (never from a second record); a Jarvis line shows the text
   sent for playback and an interrupted one is annotated with the heard
   duration the events carry (`[interrompu après 1,4 s entendues]`), never with
   a guess of the words heard. The header of every transcript says so.

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
  rejected. **Slice 04 obligation (met by the trace drill-down redaction, Query
  and live API):** the debug view must never render raw `tool.call` /
  `tool.result` trace lines unredacted (they hold raw arguments and results).
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
- **Trace drill-down** (implemented in Slice 04) starts from stored events and
  resolves their `trace_ref`; it never resolves a `conversation_event_id` found
  in a journal line (a provisional sub-agent line can name an event that was
  never stored).

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

## Query and live API

Slice 04. Core owns the store and serves it over authenticated loopback routes;
the browser never talks to Core: the Control Center proxies the same pages as
same-origin `/api/conversations...` routes. Both sides parse parameters and
encode pages with one module, `jarvis/domain/conversation_event_query.py`.

- Core: `LocalProtocolServer` routes → `ConversationEventQueryService`
  (`jarvis/core/conversation_event_query.py`) → `ConversationEventStore`.
- Client: typed `LocalCoreClient` methods (`list_event_conversations`,
  `list_event_sessions`, `list_conversation_events`, `lookup_conversation_events`,
  `get_conversation_event`) returning the store types
  (`ConversationEventSummaryPage`, `ConversationEventPage`,
  `StoredConversationEvent`), decoded strictly.
- Control Center: `ConversationEventView` + `CoreConversationEventReader`
  (`jarvis/runtime/conversation_event_view.py`, own loopback session, token file
  re-read and one retry after a 401), trace drill-down
  `jarvis/runtime/conversation_event_trace.py`.

### Routes

Core (bearer token and `X-Jarvis-Protocol` like every `/v1` route; 401
`unauthorized` otherwise):

| Route | Parameters | 200 body |
|---|---|---|
| `GET /v1/conversation-events/conversations` | `before_sequence` (optional, ≥ 0), `limit` 1..100 (50) | summary page |
| `GET /v1/conversation-events/sessions` | `conversation_id` (required), `after_sequence` ≥ 0 (0), `limit` 1..100 (50) | summary page |
| `GET /v1/conversation-events` | `conversation_id` (required), `after_sequence` ≥ 0 (0), `limit` 1..500 (100), `visibility` `public`\|`diagnostic` (all), `wait_ms` 0..25000 (0) | event page |
| `GET /v1/conversation-events/lookup` | `field` ∈ `session_id, turn_id, correlation_id, task_id, work_id, speech_id, outcome_id, span_id` (required), `value` (required), `conversation_id` (optional), `after_sequence`, `limit` 1..500, `visibility` | event page |
| `GET /v1/conversation-events/events/{event_id}` | none | `{"schema_version": 1, "sequence", "recorded_at", "event"}` |

Control Center (same parameters and 200 bodies):

| Route | Proxies |
|---|---|
| `GET /api/conversations` | conversations |
| `GET /api/conversations/sessions` | sessions |
| `GET /api/conversations/events` | events of a conversation (with long-poll) |
| `GET /api/conversations/lookup` | lookup by id |
| `GET /api/conversations/events/{event_id}` | one event (detail panel) |
| `GET /api/conversations/events/{event_id}/trace` | trace drill-down (Control Center only, below) |

Bodies:

- event page: `{"schema_version": 1, "events": [{"sequence", "recorded_at",
  "event"}], "next_cursor", "has_more", "skipped_rows"}`. `event` is the encoded
  canonical event **exactly as stored** (`encode_conversation_event`), decodable
  with `decode_conversation_event`; `recorded_at` is Core's store clock (wire time).
- summary page: `{"schema_version": 1, "summaries": [{"conversation_id",
  "session_id", "event_count", "first_sequence", "last_sequence",
  "first_occurred_at", "last_occurred_at", "last_recorded_at"}], "next_cursor",
  "has_more", "skipped_summaries"}` (`event_count` = raw row count, see Queries).

Parameters are strict: an unknown or repeated name, a non-decimal or
out-of-range number, an invalid id or lookup field, a malformed `event_id` →
400. Messages name the parameter and the rule, never the value.

### Cursor, reconnect and live

- The cursor is the store `sequence` (see Sequence and cursor). A consumer
  hydrates with `after_sequence=0`, follows `next_cursor` while `has_more`, then
  keeps polling from its last `next_cursor`. Events appended meanwhile always
  land after the cursor, so live polling never misses nor repeats one, and a
  reload (walk from 0) yields exactly the union of what live consumption
  received (tested with concurrent appends into two interleaved conversations).
- Reconnect: resume from the last `next_cursor` **received** (not the sequence
  of the last event rendered: the cursor may already be past filtered-out or
  unreadable rows). A consumer that keys rows by `event_id` (or `sequence`) can
  safely replay a page.
  A new Core process keeps the same sequences (durable store), so the cursor
  survives a Core restart.
- `next_cursor` is the last **scanned** sequence: it advances past rows that do
  not decode (`skipped_rows` > 0, diagnosed once by the store) and past events
  removed by the `visibility` filter. A filtered page can hold fewer events
  than `limit`, even none, with `has_more` true: keep paging.
- An unknown conversation is an empty page (`next_cursor` = request cursor),
  not a 404.
- Listing conversations is not a snapshot (see Queries): refresh page one after
  a walk.

**Long-poll (decision).** The Control Center page polls (1 s / 250 ms) and
Core's `/v1/events` WebSocket is live-only without replay; `/api/agent/notices`
already long-polls (`wait` ≤ 25 s). So no SSE or WebSocket was added:
`wait_ms` (≤ `MAX_WAIT_MS` = 25 000) turns `GET .../conversation-events` into a
long-poll, and long-poll and plain poll converge on the same cursor.

- Returns as soon as a page holds events **after the `visibility` filter**, or
  after `wait_ms`, or when the server stops (interrupt set before the runner
  waits for handlers), or when the HTTP client disconnected. Rows scanned
  meanwhile (filtered out, unreadable) advance the returned `next_cursor` and
  add up in `skipped_rows`; a filtered long-poll therefore keeps waiting past
  hidden events instead of returning an empty page early.
- Wake-up is **per conversation**: `ConversationEventStore.watch_appends(conversation_id)`
  (SQLite adapter: one shared `asyncio.Event` per watched conversation, created
  lazily, removed when its last reader leaves or when an append fires it). The
  reader enters the watch before querying, so an append between the query and
  the wait is not missed; appends to other conversations never re-query it
  (tested: 20 waiters, 30 appends elsewhere, 0 extra queries). In-process only:
  Core is the only writer.
- aiohttp does not cancel a handler whose client left. Core checks
  `request.transport` every `DISCONNECT_CHECK_S` = 1 s while waiting and ends
  the wait; the Control Center checks the browser connection every 0.25 s and
  cancels its Core request (closing that Core connection).
- Control Center bounds: at most `MAX_LONG_POLLS` = 8 long-polls wait at Core at
  once; a request over the cap is forwarded with `wait_ms=0` (answered at once,
  same page and cursor; counted in `long_polls_downgraded`). Long-polls use
  their own Core session (connection limit 10) and lists/details another (limit
  16), so held polls never starve detail reads. After a 401 the token file is
  re-read and set on both clients **without closing** their sessions (other
  in-flight polls continue). Once the view is closed (Control Center stopping)
  reads answer 503 `control_center_stopping` and no session is reopened.
- The client extends its request timeout by `wait_ms`; the Control Center read
  budget is 5 s + `wait_ms`.

**Slice 05 guidance, amended.** One long-poll per **browser profile**, not per
tab. Browsers allow about 6 connections per host, shared with the existing
1 s / 250 ms polls of the page, so one held long-poll per open timeline
saturated the budget: measured at 6 open timelines, `/api/status` went from
3-7 ms to 5-14 s and a live event took 14 s to reach every window.

The page therefore elects a leader per profile with `navigator.locks`, keyed by
conversation (`jarvis.timeline.<conversation_id>`), and relays over
`BroadcastChannel('jarvis.timeline')`:

- the **leader** holds the only long-poll and broadcasts each accepted page
  (`from`, `cursor`, `events`, `has_more`) plus a 10 s tick carrying its cursor
  and the state of its read;
- a **follower** never long-polls. It does one bounded `wait_ms=0` read on first
  load, on a gap (a relayed page starting past its cursor), on a tick whose
  cursor is ahead, and when the leader has been silent for 35 s (checked every
  5 s, so bounded at ~40 s);
- hiding a tab releases leadership and pauses it; it catches up on becoming
  visible. Closing, navigating or freezing the leader releases the lock and the
  browser hands it to a queued tab, which resumes at **its own** cursor — the
  route returns everything after that sequence, so no event is missed;
- without Web Locks or BroadcastChannel the page runs `solo`: one long-poll per
  tab, exactly the previous behaviour.

Nothing per-tab travels on the channel: the route takes only `conversation_id`,
`after_sequence`, `limit` and `wait_ms`, and every page filter (Tout/Public,
search, lanes, scale, selection) is applied afterwards on the rows held in the
tab. Tabs share the raw stream and each derives its own view. Two tabs on two
different conversations keep one leader each — the route cannot serve two
conversations in one request. Resume from the last `next_cursor` received.

### Errors

| Case | Core | Control Center |
|---|---|---|
| bad parameter | 400 `invalid_request` | 400 `invalid_request` (validated before calling Core) |
| missing/rotated token | 401 `unauthorized` | token file re-read, one retry; still refused → 502 `core_unauthorized` |
| store failure, repository closed (Core stopping) | 503 `conversation_events_unavailable` | 503 `conversation_events_unavailable` |
| Core down, token file missing, timeout | — | 503 `core_unreachable` |
| answer out of contract | — | 502 `invalid_core_response` |
| other Core refusal | — | 502 `core_refused` |
| event absent **or** unreadable | 404 `conversation_event_not_found` | 404 `conversation_event_not_found` |
| user event trace | — | 404 `trace_not_applicable` |
| trace file unreadable (I/O) | — | 503 `trace_unreadable` |
| unexpected drill-down failure | — | 503 `trace_drill_down_failed` |
| 2 drill-downs already running for 10 s | — | 503 `trace_busy` |
| foreign `Origin`, non-loopback `Host`, `Sec-Fetch-Site: cross-site` | — | 403 `forbidden_origin` |
| view not wired | — | 503 `not_configured` |
| Control Center stopping (view closed) | — | 503 `control_center_stopping` |

Core JSON errors keep the `/v1` shape `{"error": {"code", "message"}}`; Control
Center errors are `{"ok": false, "code", "error", "core_status"}`. An unreadable
row looked up by id is a 404 because the store returns None for it; its
`core.conversation_events.row_unreadable` diagnostic was already emitted by the
store.

Diagnostics (never a value): Core `core.conversation_events.query_failed`
(error, `operation`, `error_class`) once per failure episode and
`core.conversation_events.query_recovered` (info); Control Center
`ui.conversation_events_unavailable` (warning, `code`, `operation`,
`exception_type`, `core_status`) once per episode,
`ui.conversation_events_recovered` (info), `ui.conversation_events_invalid_response`
(error, once per exception type), `ui.conversation_event_trace_unreadable` (error,
`code`, `exception_type`, `event_id`, once per drill-down failure episode) and
`ui.conversation_event_trace_recovered` (info).

**Origin guard.** The Control Center guards `/api/conversations...` for every
method (the rest of its routes guard only mutating methods; `/api/trace` and
`/api/errors` are a tracked Issue): `Sec-Fetch-Site: cross-site` is refused; a
present `Origin` must be exactly `http(s)://<loopback>[:port]`; the `Host`
header must be a loopback host (DNS rebinding). Hosts are compared exactly
after splitting the port, without a URL parser: any `@ # / ? \ %` or space in
the authority refuses the request (`evil.com@127.0.0.1`, `127.0.0.1#.evil.com`).
Loopback hosts: `127.0.0.1`, `localhost`, `::1` (bracketed). Conversation
history holds user transcripts.

### Trace drill-down

`GET /api/conversations/events/{event_id}/trace` (Control Center, which already
reads `runtime/trace.jsonl`):

1. Validate `event_id`; load the **stored** event through Core (404 if absent or
   unreadable). The drill-down never starts from, nor follows, an id found in a
   journal line (a provisional sub-agent line may name an event never stored).
2. Actor `user` → 404 `trace_not_applicable` (locked intent).
3. `trace_ref` null → 200 `status: "no_trace_ref"` (the producer wrote no line).
4. `trace_ref.source == agent_task` → 200 `status: "agent_task"`, with
   `agent_task: {task_id, trace_url: "/api/agent/tasks/{task_id}/trace"}` (the
   existing route; nothing duplicated). Sub-agent events also carry this link.
5. `runtime_journal` → bounded newest-first scan in a worker thread (at most
   `MAX_TRACE_DRILL_DOWNS` = 2 at once; a third waits up to 10 s, then 503
   `trace_busy`) (`scan_trace`), each candidate line (contains the journal kind) decoded and
   matched with `trace_entry_matches`; 200 `status: "found"` or `"not_found"`
   with `scan: {entries, match_count, scanned_lines, scanned_bytes,
   corrupt_lines, oversized_lines, truncated, stopped_by}`.

Bounds (`ScanLimits`): 64 MiB read and 500 000 lines at most, lines above
256 KiB skipped (`oversized_lines`), stop at the first line older than
`occurred_at - 15 min` (`stopped_by: window_start`; journal lines are appended
in time order per process, interleaved by milliseconds across processes), lines
newer than `occurred_at + 15 min` not decoded, at most 8 matches (the contract
expects exactly one). `truncated` is true when a byte, line or match budget
stopped the scan (`stopped_by` `max_bytes` / `max_lines` / `max_matches`);
otherwise `stopped_by` is `window_start`, `file_start` or `missing_file`.
Undecodable candidate lines (torn, glued, binary) count as `corrupt_lines`.
Measured: a 4 MB synthetic trace scanned end to end well under a second in the
unit test; the live 14 MB file is inside the byte budget. Known limit: a
producer clock skewed by more than the window can stop the scan early.

Redaction (`project_trace_entry`, defined once in
`jarvis/runtime/conversation_event_trace.py`, total over any decoded JSON
object: a list or object `message`, odd keys or nested data are projected,
never raised on). Every returned line is a projection `{ts, kind, level,
message, message_redacted, data, redacted_keys, redacted_key_count}`:

- `data` keeps only allowlisted keys whose value passes the rule of its group
  (`_safe_data_value`); `null` and booleans pass everywhere:

  | group | keys | value rule |
  |---|---|---|
  | `TRACE_ID_KEYS` | `conversation_id, session_id, turn_id, correlation_id, task_id, work_id, speech_id, outcome_id, output_id, call_id, tool_use_id, parent_id, job_id, candidate_id` | printable string ≤ 256 chars without `@`, `/`, `\`, `=`, `+` or whitespace |
  | `TRACE_EVENT_ID_KEYS` | `conversation_event_id` | `cev-` + 64 lowercase hex |
  | `TRACE_CODE_KEYS` | `status, code, reason, kind, priority, provider, source, disposition` | `[a-z][a-z0-9_.-]{0,63}` or a finite number |
  | `TRACE_CLASS_KEYS` | `error_class, exception_type` | `[A-Z][A-Za-z0-9_]{0,63}` or a code token |
  | `TRACE_MODEL_KEYS` | `model, subagent_type` | `[a-z0-9][a-z0-9._:-]{0,63}` or a finite number |
  | `TRACE_NUMBER_KEYS` | `duplicate, background, duration_ms, played_ms, tokens, tool_uses, depth, revision, attempt` | booleans and finite numbers only |

  Every string whose lower-cased form starts with a credential prefix
  (`SECRET_PREFIXES`: `sk-`, `sk_`, `pk_`, `rk_`, `ghp_`, `gho_`, `ghs_`,
  `ghu_`, `github_pat_`, `glpat-`, `xox`, `akia`, `asia`, `aiza`, `ya29.`,
  `eyj` (JWT), `hf_`, `bearer`) is dropped whatever its key. Anything else —
  `arguments`, `result`, `error`, `text`, `summary`, `description`, nested
  objects, free text, emails, paths, URLs, base64 with padding — is dropped and
  counted in `redacted_key_count`; its key name is listed in `redacted_keys`
  only when it is a code identifier (`[a-z][a-z0-9_]{0,63}`). Checked against a
  scratch copy of the live `runtime/trace.jsonl` (13 123 lines, 2026-09-16):
  of the 48 279 allowlisted values the first rule kept, the current rule drops 0.
  Known limit: an id-shaped secret without a known prefix (base64url, no
  padding) is indistinguishable from an opaque id; allowlisted keys are written
  by Jarvis code, never by providers.
- `message` is returned only when it is a string equal to one of the constant
  messages the producer of that kind writes (`STATIC_MESSAGES`: `core.brain.*`
  trace kinds, `voice.speech.*`, `voice.reflex.started`; a test asserts each
  string still appears in its producer source). Tool (`tool.call` /
  `tool.result`: tool name), `voice.brain_turn_rejected` (exception text) and
  `agent.subagent.*` (description) messages are withheld (`message_redacted`).
  A producer that changes its wording only hides its message, never leaks.
- `agent.event` lines are never decoded into a result, even if a reference
  named that kind (the codec already refuses such a `trace_ref`).

Tests plant secrets in `arguments`, `result`, `error`, `text`, `summary`,
`description` and messages, and API keys, emails, paths, URLs, JWTs, base64,
forge tokens and bearer strings in **every** allowlisted key, and assert none
reaches a response; the Slice 03b multi-actor timeline test runs the drill-down
on the real Core, voice and Control Center journal lines interleaved with torn
fragments.

### Loss and health visibility

- Core `GET /v1/health` adds `conversation_events: {emitter: <all
  ConversationEventEmitterCounters>, store: {unreadable_rows,
  diagnostic_failures}, query_failures}`.
- Control Center `GET /api/status` adds `conversation_events`: this process's
  forwarder counters (`ConversationEventForwarderCounters`) plus `pending`, or
  null when no forwarder is wired. The voice process forwarder counters stay in
  its `conversation_events.forwarder_*` journal lines (no status route there).

### Limits and performance

Page and summary limits are the store maxima (500 / 100). A 5 000-event
conversation pages end to end over the real loopback in about 1.4 s (10 pages
of 500 or 50 pages of 100, `test_a_long_session_of_5000_events_pages_quickly`,
idle host). Every read decodes each row through the codec.

## Timeline UI

Slice 05. A full-screen, live transcript/debug view of one conversation in the
Control Center, built only on the Query and live API above. It never reads
`/api/trace` nor a raw journal line, and it never shows anything the events do
not carry (no hidden reasoning exists in them).

- Module: `jarvis/runtime/control_center_timeline.js`, inserted into
  the page at `/*__CONTROL_CENTER_TIMELINE_JS__*/` by `ControlCenter.index` like
  the other Control Center scripts. Pure part `JarvisTimelineCore` (executed as
  is by node tests); browser block `installJarvisTimeline` (DOM, focus, fetch).
- Markup and CSS: `jarvis/runtime/control_center.html` (`#timeline`, `.tl-*`),
  dock button **CNV** (`#openTimeline`), also in the Omega theme's icon bar.
- Tests: `tests/unit/test_control_center_timeline_js.py` (node logic, parity with
  `reconstruct_conversation`), `tests/unit/test_control_center_timeline_ui.py`
  (page contract).

### Lanes, colors and entries

Time runs downward on one axis shared by four lanes. Color always doubles a
text label, an icon and a status word.

| Lane (left → right) | Color token | Content |
|---|---|---|
| Utilisateur | `--tl-user` white | `user.transcript.accepted` cards (no drill-down: not a button, `role="article"`) |
| Jarvis · voix | `--tl-mouth` light blue | `mouth.speech.*` cards with the playback text and an exact-duration bar; `mouth.reflex.started` compact cards (marked "réflexe"); left rail: `mouth.speech.queued` dots; right rail: `tool.*` bars from `voice.*` producers; `system.failure` from `voice.*` producers as a red card |
| Brain | `--tl-brain` orange | `brain.message.published` cards; left rail: `brain.turn.accepted` and `brain.speech.requested` dots; right rail (next to the sub-agents): `brain.work.*` bars; `brain.turn.failed` and other `system.failure` as red cards |
| Sous-agents | `--tl-sub` red | `subagent.*` duration blocks with the text inside: name (type, or description when the type is generic), description, start · duration · status |

- **Lane rule** (`laneOf`): the actor's lane; `tool` and `system` go to the
  lane of their producer: `voice.*` → Jarvis · voix (the realtime model that
  speaks for Jarvis calls these tools), anything else → Brain.
- **Entry kinds** (`entryKind`):
  - *card*: public text (user transcript, Jarvis speech, public reflex, Brain
    message), **never clamped**: the card grows to fit its text; for a speech, a 3 px bar drawn
    from the start time has the exact duration (amber tip when the speech was
    cut, fading when still open). A card may extend past its end time.
  - *failure*: `brain.turn.failed` / `system.failure`, a red card whose label and
    code are always visible.
  - *dot*: diagnostic instants only (turn accepted, speech requested, queued,
    any unknown diagnostic type), a dot on an 18 px rail on the left of the lane.
    Its label appears on hover and on keyboard focus in a bounded box (at most
    28 rem or the viewport width minus 32 px, wrapped with `overflow-wrap:anywhere`,
    at most 240 characters then "…") placed in fixed position inside the visible
    timeline area, so it never widens the scroll area; the full description is in
    the `aria-label` and the drawer.
  - *bar*: Brain work and tool spans, a 14 px bar on the right rail with a
    vertical label when it is taller than 40 px; full information in the drawer.
  - *block*: a sub-agent, a red block of exact duration (at least 46 px, dashed
    beyond the exact fill when shorter) whose name, description and meta line
    wrap inside it; the number of lines comes from the block height.
- **Status marks**: statuses are written on cards and blocks ("interrompu",
  "en cours", "échec"…); open spans fade at their end and show a live duration;
  failures are hatched (bars, blocks) or red (cards).
- **Interrupted speech**: mouth `content` is the text sent for playback, not the
  text heard (note 5). The card text is italic and its label and detail say
  "Texte envoyé à la lecture · coupé après N s entendues" (`played_ms`), or that
  the heard duration is unknown.
- **Duplicate text** (projection obligation above, `collapseMessages`): a
  `brain.message.published` whose text equals the previous published message of
  the same `correlation_id` is merged into it (badge `×2`, both events listed in
  the detail). "Previous" means the last published message of that correlation,
  so A, B, A stays three entries.
- **Filter**: *Tout* (default: this is a debug surface, and sub-agent and Brain
  work spans are diagnostic) or *Public* (what was said, heard or shown).
  Filtering happens after pairing, on the item visibility, exactly like
  `include_diagnostic=False`: a public `mouth.speech.started` closed by a
  diagnostic `failed` still pairs. The page therefore never asks the server for
  `visibility=`.
- **Reflex** (PM decision): a public `mouth.reflex.started` is transcript text, a
  compact card in both *Tout* and *Public* views.
- **Unreadable time**: an event whose `occurred_at` does not parse is never
  placed at epoch 0; it is left out and counted in the partial-data notice
  (`readableEvents`).

### Axis, packing and virtualization

- **Pairing** (`reconstruct`): a line-by-line port of `reconstruct_conversation`
  (same keys, earliest open/close, clamping, anomalies, order). Tested for
  parity on the golden fixture (shuffled, with duplicates) and on every anomaly
  case against the Python output.
- **Scale**: linear, 60 px/s by default (20–160 selectable). Any silence longer
  than 6 s between two event instants is folded into a 44 px hatched band
  ("N sans événement · axe replié") placed below the cards already drawn. The
  mapping stays strictly increasing, so start positions, order and overlaps
  across lanes are preserved; durations are proportional outside folds and
  always written as text.
- **Lane widths**: weighted by need. A first packing at equal widths gives each
  lane its simultaneous text columns (capped at 4), sub-agent block columns and
  rails; the need is rails + columns × a minimum of 28 characters of text
  (150 px for an empty lane). The available width is shared in proportion to
  need; when the screen is narrower than the total need, every lane keeps its
  need and the timeline scrolls horizontally. A lane that never needs a second
  column (typically Utilisateur) stays narrow.
- **Packing and heights**: cards overlapping in time are laid out in columns
  (calendar algorithm per cluster). A card's height is computed at the width of
  the column it is finally drawn in: packing and measuring repeat until the
  heights no longer change. The measure simulates `pre-wrap` word wrapping with
  the character width the page measures on the real monospace font; after
  rendering, a card taller than its estimate records its real height for that
  width (`heightFix`) and the layout is recomputed, so text can never be clipped
  and cards never overlap. Cards use `min-height`, never a fixed height.
- **Open spans** grow to the browser clock every second (all processes are on
  the same host).
- **Virtualization**: only entries intersecting the viewport ± 700 px are in the
  DOM (`visibleRange`: binary search on a running maximum of bottoms, so a long
  span started far above stays visible). Keyed by `item_id`; a node is replaced
  only when its HTML changes. Keyboard order follows time (`model.order`), not
  the drawing order.

### Live strategy

One flow per tab (`createFeed`), and at most one request in flight:

1. hydrate: `GET /api/conversations/events?conversation_id=…&after_sequence=0&limit=500`
   and follow `next_cursor` while `has_more` (an empty filtered page with
   `has_more` is normal);
2. live: long-poll the same route with `wait_ms=25000` from the last
   `next_cursor` received; a page with `has_more` switches back to immediate
   catch-up; the client deadline is `wait_ms` + 10 s (hydration pages 15 s), so a
   request can never hang;
3. retryable failure (`core_unreachable`, `conversation_events_unavailable`,
   `control_center_stopping`, `core_unauthorized`, `core_refused`,
   `invalid_core_response`, network, timeout, any 5xx/408/429): state
   `reconnecting`, backoff 1 s doubling to 30 s, resume from the last cursor;
4. blocking failure (`invalid_request`, `forbidden_origin`, `not_configured`,
   HTTP 404 `missing_route`): state `blocked` until "Réessayer maintenant";
5. `following`: this tab is a follower — rows arrive by relay and no request is
   held. `paused`: the tab is hidden and asks for nothing. A follower shows the
   leader's own state, so "En direct" is never displayed while the leader is
   reconnecting or blocked, and after 25 s without a tick (two missed
   heartbeats, well before the ~40 s watchdog read) it says "Relais en retard"
   with how long it has heard nothing, rather than claiming to be up to date.

Rows are keyed by `event_id`: a replayed page adds nothing. Switching
conversation aborts the held long-poll once the selection has been stable for
350 ms (so arrowing through the list does not churn connections; the Control
Center frees its slot within 0.25 s) and hydrates the new one from cursor 0.
This holds in `shared` mode too: the lock is named per conversation, so the tab
releases the old conversation's lock and elects again on the new one, and taking
the lead always (re)starts the read — a tab that is already the leader is the
case that must restart, not the case to skip. Rows, cursor and the in-flight
request of the old conversation are dropped, and `merge` refuses any row whose
`conversation_id` is not the loaded one, so a late page of the old conversation
cannot land in the new one.
While the selected conversation is not the one loaded, the canvas says
"Chargement de la conversation…" and never shows the previous rows. Going back
to the current conversation within the settle window cancels the pending
switch. Closing the view stops the flow and cancels a pending switch; reopening
loads the conversation last selected. The conversation list (`/api/conversations`,
100 most recent) refreshes every 15 s (5 s after an error); "Plus récente"
follows the most active conversation until the user picks one. Sessions
(`/api/conversations/sessions`) are jump targets, not filters (Brain events
carry no session).

### States

The status pill always says whether something is happening, what, for how long,
and how to get out:

| Pill | Meaning |
|---|---|
| Chargement · N événements · T | hydration pages in progress |
| Rattrapage · N événements | a live page reported `has_more` |
| En direct · N événements · dernier reçu il y a T | long-poll held; events append without reload |
| *error title* · *server message* · nouvelle tentative dans T (essai N) · coupé depuis T, button "Réessayer maintenant" | retryable failure, cursor kept, rows kept |
| … · nouvelle tentative en cours (essai N) | the retry request is in flight |
| *error title* · *message* · *hint*, button | blocking failure |

Canvas states: "Aucune conversation enregistrée" (empty store), "Chargement de
la conversation…", "Cette conversation n'a encore aucun événement", "Aucun
événement public" with "Tout afficher", the error title before any data. Per
lane, an empty lane explains itself (for example the direct voice architectures
have no mouth lane; sub-agents from panel or spontaneous turns are not
recorded). A non-zero `skipped_rows` shows "N lignes illisibles ignorées par
Core … chronologie partielle", and events with an unreadable time are counted in
the same notice.

### Detail drawer and trace navigation

Enter or click on any non-user entry opens the drawer (a column on wide screens,
an overlay below 1100 px): status and visibility, text and playback note,
timing (start, end, duration, "Depuis la parole utilisateur" = latency from the
user turn of the same `correlation_id`, latency from the parent), outcome
attributes (provider status, reason, code, error class, heard duration, model,
sub-agent type, tokens, tools), anomalies, navigation (parent via
`parent_event_id`, in view or loaded with `GET /api/conversations/events/{event_id}`;
children; sub-agent task trace opens the Agents panel), then every event of the
entry (role, `event_id`, store sequence, producer, visibility, times, ids,
attributes, `trace_ref`) with its drill-down
`GET /api/conversations/events/{event_id}/trace`, fetched one at a time (the
Control Center runs at most two):

| Drill-down | Shown |
|---|---|
| `found` | "N ligne(s) de trace jointe(s)", each redacted projection (ts, kind, level, constant message or "message masqué", allowlisted data, count of masked fields), scan stats (`scanned_lines`, why it stopped, corrupt/oversized lines, "tronqué") |
| `not_found` | "Aucune ligne de trace jointe" + the same scan stats |
| `no_trace_ref` | "Le producteur n'écrit pas de ligne de trace pour ce fait" |
| `agent_task` | "Ouvrir la trace de la tâche dans Agents" |
| `trace_busy`, `trace_unreadable`, `trace_drill_down_failed`, `core_unreachable`, timeout (20 s) | error title, server message, hint, "Réessayer" |
| `trace_not_applicable` | never requested (user entries have no drawer) |

### Keyboard and accessibility

- The view is `role="dialog"` `aria-modal="true"`. While it is open every other
  child of `body` is `inert` (restored on close), Tab and Shift+Tab cycle only
  through its elements with `tabIndex >= 0`, a click in empty space focuses the
  scroll region, and the page's own shortcut handler ignores keys while
  `#timeline` is visible (verified in Chrome: 60 Tab presses, "s" and "t" after
  an empty click). Esc closes the drawer (focus returns to the entry), then the
  view (focus returns to the dock button).
- Entries use a roving tabindex: ↑/↓ previous/next in time, ←/→ nearest entry in
  the neighbouring lane, Home/End first/last, Enter opens the detail. Each entry
  has a full `aria-label` (lane, type, status, time, duration, playback note,
  text).
- Status changes and new events (throttled to one announcement per 15 s) are
  announced through a polite live region; `prefers-reduced-motion` stops the
  pulsing indicators.
- Below 700 px the toolbar is compact (title as an icon, field labels kept for
  screen readers only; toolbar + lane headers end at 130 px on a 390×844
  screen), the close button is a 44 px target, lanes keep their need and scroll
  horizontally under a sticky time ruler and sticky lane headers.

### Search, transcript and export panels (Slice 06)

Three toolbar buttons (`#tlSearchOpen` *Rechercher*, `#tlTranscriptOpen`
*Transcription*, `#tlExportOpen` *Exporter JSONL*; icon-only below 700 px,
label kept for screen readers; `aria-controls="tlDrawer"` + `aria-expanded`)
open a panel in the detail drawer; the drawer holds one thing at a time
(opening an entry's detail closes a panel and vice versa). Esc closes the
panel (focus back to its button), then the view; closing the view aborts any
request in flight. Every wait shows motion, what, a live counter and *Annuler*;
every failure shows the server's title, message and hint with *Réessayer*.

- **Recherche**: `role="search"` form (text, *Toutes les conversations*
  checked by default, otherwise the selected conversation), results newest
  first with who · what · day time, "autre conversation" when it is not the one
  shown, the highlighted snippet and the matched fields; *Plus de résultats* /
  *Continuer la recherche* (after `scan_limited`) follows `next_cursor`.
  Choosing a result switches conversation if needed (pinned), switches the
  filter to *Tout* when the event is diagnostic, waits for the rows, scrolls
  to the entry (a merged publication resolves to the entry that absorbed it),
  focuses it and outlines it (`is-found`). Below 1 100 px, where the drawer
  covers the timeline, the panel closes to show the entry (the results are
  kept: *Rechercher* reopens them). If the conversation is live and the event
  is not in it, the panel says so. The "↓ N nouveaux" pill counts only events
  arriving after the conversation was already hydrated (a switch or a jump no
  longer reports the last hydration page as new).
- **Toolbar cost** (headless Chrome, 2026-09-17): 390×844, the three icon
  buttons sit on the conversation row, lane headers end at 136 px (130 px
  without them); 1440×900, labelled buttons push the status to a second row,
  lane headers end at 116 px (90 px without them) or 132 px with the session
  selector (114 px).
- **Transcription**: *Simple* / *Détaillé*, fetches
  `/api/conversations/transcript` (70 s deadline), shows Core's text in a
  focusable `pre` (line count, size, render time) and *Télécharger .txt*
  (`conversation-….transcription[-detaillee].txt`, from the same bytes).
- **Export JSONL**: streams `/api/conversations/export` with the byte counter,
  30 s idle deadline and *Annuler*; the file is saved only when its last line
  is the complete trailer (`exportSummary`), otherwise the panel shows "Export
  incomplet" and *Réessayer*. The result line gives events, unreadable rows,
  size and file name.

The page never renders transcript text or export lines itself; tests assert
that the module holds no transcript wording and reads only the canonical
`/api/conversations...` routes.

### Performance and readability (measured 2026-09-16)

Real Core + Control Center on temp dirs, headless Chrome. 1440×900: demo
conversation, 10 public texts out of 11 text entries, **0 truncated**, 0 card
overlaps (whole canvas swept); 390×844: 12 public texts, 0 truncated, 0
overlaps. 2 400-event conversation hydrated in 1.5 s (5 pages of 500), 19–30
entry nodes in the DOM, reconstruct + layout 15 ms, live append visible 0.17 s
after the Core append. Node: 5 000 events reconstructed and laid out under the
3 s test budget, any viewport window computed in < 50 ms.

### Troubleshooting

| Symptom | Cause and action |
|---|---|
| "Core injoignable" with a countdown | Core stopped or restarting. Nothing to do: the view resumes at its cursor (rows are never duplicated). "Réessayer maintenant" skips the wait |
| "Jeton de session refusé par Core" | Core restarted and its token file changed; the Control Center re-reads it on the next attempt |
| "Origine refusée" | the page was opened through a non-loopback host name; open `http://127.0.0.1:<port>/` |
| "Route de conversation absente" | Control Center older than Slice 04: restart it |
| "Vue non reliée à Core" | the Control Center was started without a conversation reader (`not_configured`) |
| Lane *Jarvis · voix* empty during a voice session | direct voice architecture (simple, front_brain, duplex): no mouth events yet (Known limits) |
| A sub-agent seen in the Agents panel is missing | it was launched by a panel/console message or a spontaneous turn, or its attribution was rejected (`agent.subagent.conversation_unattributed` in the trace) |
| "Aucune ligne de trace jointe" | the journal line is outside the ±15 min window, beyond the scan budget, or the trace file was rotated; the scan stats say which |
| "N lignes illisibles ignorées par Core" | damaged rows skipped by the store (`core.conversation_events.row_unreadable`) |
| "Conversation trop longue pour la transcription" | more than 50 000 events to hold: use *Exporter JSONL* |
| "Export incomplet" | the stream stopped before its trailer after bytes were received (Core stopped, storage failure, network): *Réessayer*; nothing was saved |
| "Recherche déjà en cours" / "Core est occupé" | Core runs one search and two transcript/export builds at a time (another tab?): retry in a moment |
| A search result "absent de la chronologie" | its row became unreadable or was pruned since the search |
| Speech text longer than what was heard | expected: mouth text is the playback text; read "coupé après N s" |

## Readable transcript

Slice 06. A plain-text projection of one conversation, produced by one pure
renderer (`jarvis/domain/conversation_transcript.py`) for every surface: Core
renders it, the Control Center relays Core's bytes, the timeline shows and
downloads them, and an offline reader of an export calls the same function. No
model writes or rewrites a line; the same events always give the same bytes
(times in UTC, fixed French number format, no locale, no clock).

- **Basis**: `reconstruct_conversation`. *Plain* mode (`mode=plain`, default)
  keeps public items only: `Utilisateur` (user transcript), `Jarvis` (mouth
  speech span), `Jarvis (réflexe)` (public reflex), `Brain` (published
  message). *Detailed* mode (`mode=detailed`) adds diagnostic items, marked
  `--`: turn accepted (with `source`), speech requested (its text), Brain work,
  sub-agent and tool spans with status and duration (sub-agent type, model,
  tokens, tool uses; tool name and status), turn and system failures with
  `code`, `reason`, `error_class`, and speech that was never played. Only
  `mouth.speech.queued` is left out (its speech is the Jarvis line). Nothing
  outside the event envelope appears, so no prompt, tool argument, provider
  error text or journal line can.
- **Jarvis speech** is the text sent for playback (note 5). Annotations come
  from the close event: `[interrompu après N s entendues]` (`played_ms`),
  `[interrompu, durée entendue inconnue]`, `[en cours]`, `[lecture en échec]`
  (detailed: plus its codes), `[remplacé avant la fin]`, `[expiré avant la fin]`.
  A line without recorded text says `(texte non enregistré)`.
- **Duplicate publications** collapse with exactly the timeline rule
  (`collapseMessages`): a `brain.message.published` whose text equals the
  previous published message of the same `correlation_id` is merged (A, B, A
  stays three). Detailed mode writes `[publié N fois]`. Parity is tested by
  running the JS module under node on shared fixtures
  (`test_python_collapse_keeps_exactly_the_timeline_semantics`). The rollout
  gate also compares the plain body with QA's independent oracle
  (`tests/fakes/transcript_oracle.py`: raw stored JSON, no reconstruction).
- **Format**: a 4-line header (conversation id, "projection déterministe…",
  mode · heures UTC (or `UTC+02:00`) · N événements lus · K lignes illisibles
  ignorées par Core, the playback-text notice; detailed adds the `--` legend), a
  blank line, then one `— YYYY-MM-DD —` line per day and one line per item
  `[HH:MM:SS.mmm] Label [annotations] : text`; continuation lines of a
  multi-line text are indented by 4 spaces. Durations: `850 ms`, `1,4 s`,
  `2 min 05 s`, `1 h 02 min`. An empty conversation ends with
  `(aucun échange public enregistré)`.
- **Anomalies** (`close_before_open`…) are named in detailed mode only.
- **Local time (rework)**: `utc_offset_minutes` (integer, ±840, default 0)
  shifts every printed time and day line and is written in the header
  (`heures UTC+02:00`). It is a rendering input like `mode`: exports and
  offline reproduction default to UTC and reproduce a local rendering byte for
  byte when given the same offset (`transcript_from_export(…, utc_offset_minutes=120)`).
  The CNV panel sends the browser's current offset, so its times match the
  timeline's local clock (a daylight-saving change inside a conversation is not
  applied per event).
- **Unknown usage**: the Control Center tracker starts `tokens` / `tool_uses` at
  0 and only overwrites them when the CLI reports usage; the producer now
  leaves them out when they are still 0, and the renderer never prints a 0.

Sample (plain, from the rollout gate):

```text
Transcription de conversation · 38b2ad0d-15d6-4bb7-9162-0a1361eaff89
Projection déterministe des Conversation Events (contrat v1) ; aucune ligne n'est écrite par un modèle.
Mode : simple · heures UTC · 23 événements lus
Parole de Jarvis : texte envoyé à la lecture ; une parole coupée n'indique que la durée entendue.

— 2026-09-16 —
[22:34:33.585] Utilisateur : Prépare mon dossier de vol pour Lisbonne.
[22:34:33.604] Jarvis [interrompu après 400 ms entendues] : Je regarde tous les vols de la semaine vers Lisbonne.
[22:34:33.650] Utilisateur : Seulement le vol de Paul, s'il te plaît.
[22:34:33.660] Brain : Le vol de Paul pour Lisbonne part lundi à 9 heures.
[22:34:33.664] Jarvis : Le vol de Paul pour Lisbonne part lundi à 9 heures.
[22:34:33.686] Utilisateur : Et réserve l'hôtel aussi.
[22:34:34.360] Utilisateur : Question pendant la panne : le vol est-il confirmé ?
```

Detailed lines look like
`[10:00:00.600] -- Sous-agent « Rassemble les vols » : terminé en 1 min 34 s · type flight-finder · modèle claude-sonnet-5 · 1234 jetons · 5 outils`
and `[10:00:07.000] -- Brain : tour en échec (code brain_backend_exception, classe ConnectionResetError)`
(golden files `tests/fixtures/conversation_events/transcript_{plain,detailed}.txt`).

Rendering: `TranscriptBuilder` accumulates store pages (`PROJECTION_PAGE_LIMIT`
= 50 events per read, yielding to the loop between pages), keeps only the event
types the mode needs (it counts all of them), and renders in a worker thread.
Two budgets, checked at each kept event so a refusal is cheap: `MAX_TRANSCRIPT_EVENTS`
= 50 000 kept events and `MAX_TRANSCRIPT_CONTENT_BYTES` = 16 MiB of text (UTF-8
content + 64 bytes per kept event); past either, 413 `transcript_too_large`:
use the export. Core streams the rendered text in 64 KiB chunks and the Control
Center relays them (no second copy there); a client that leaves cancels the
build (the render itself, once started in its thread, runs to its end).
Measured: a 1 000-event conversation renders (paging + detailed rendering) in
0.12 s.

## JSONL export

Slice 06 (`jarvis/domain/conversation_event_export.py`). A projection of the
store, never a second record, UTF-8, one compact JSON object per line (keys
sorted):

```text
{"conversation_id", "counts": {"first_sequence", "last_sequence", "stored_rows"}, "export_version": 1,
 "exported_at", "format": "jarvis.conversation-events.export", "schema_version": 1, "through_sequence"}
{"event": <encoded canonical event, codec output>, "recorded_at", "sequence"}      (0..n, ascending sequence)
{"complete": true, "counts": {"events", "skipped_rows"}, "format": "jarvis.conversation-events.export"}
```

- Event lines are exactly the query API's stored-event items
  (`encode_stored_event`).
- **Frozen extent**: before the first byte Core reads the conversation's raw
  row count and last sequence (`ConversationEventStore.conversation_extent`,
  index only) into the header; pages are then read with
  `until_sequence=through_sequence`, so events appended while the file streams
  are not in it and the header describes exactly what follows.
- **Streaming**: 500 events per store read, one HTTP chunk per page; nothing
  holds the conversation in memory (tested with 1 234 events: exactly three
  reads of 500). The Control Center relays Core's chunks.
- **Trailer**: its presence proves the file is whole. A storage failure while
  streaming (Core) or a broken Core stream (Control Center, journaled once per
  episode as `ui.conversation_events_unavailable` with `code=export_interrupted`)
  closes the connection without trailer: the receiver gets a transport error
  and a file that reads as incomplete, never a silently short one.
- Unreadable stored rows are skipped by the store (diagnosed) and counted in
  the trailer's `skipped_rows`; `events + skipped_rows == stored_rows`.
- Download name: `conversation-<id with [A-Za-z0-9._-] kept, others as _>.events.jsonl`;
  when a character had to be replaced, `-<FNV-1a 32 of the UTF-8 id>` is
  appended so `réunion` and `rèunion` never share a name (`export_filename`,
  same rule and hash in the page, tested).
- **No integrity check**: the header/trailer counts detect a truncated or torn
  file, not a deliberate edit. A removed event line with edited counts, or an
  edited content that stays codec-valid, reads as complete. Keep exports where
  they cannot be modified if they serve as evidence.
- The page saves nothing for a conversation without events ("Aucun événement
  dans cette conversation"), although Core still answers a complete empty export.

**Offline importer.** `read_export(lines)` decodes a file line by line through
the codec: the header must be first (else `ExportFormatError`; a UTF-8 BOM
before it is accepted); every other
invalid line is skipped and reported with its number and a reason naming the
rule, never the value (`invalid_json`, `invalid_event` (codec or redaction
error), `other_conversation`, `sequence_out_of_order`, `oversized_line`
(> 1 MiB), `invalid_trailer`, `after_trailer`). `complete` is true only with a
trailer whose counts match the lines read and no invalid line.
`reconstruct_export(result)` and `transcript_from_export(result, mode=…)` use
the live functions, so they are byte-identical to the live rendering of the
same stored events (tested in unit, protocol, Control Center and rollout-gate
tests, including an unreadable stored row).

```python
from pathlib import Path
from jarvis.domain.conversation_event_export import read_export, reconstruct_export, transcript_from_export
from jarvis.domain.conversation_transcript import TranscriptMode

result = read_export(Path("conversation-….events.jsonl").read_bytes().splitlines(keepends=True))
print(result.complete, len(result.events), result.skipped_rows, result.invalid_lines)
items = reconstruct_export(result)
print(transcript_from_export(result, mode=TranscriptMode.DETAILED))
```

## Search

Slice 06 (`jarvis/domain/conversation_event_search.py`, scan in
`SQLiteConversationEventStore.search_events`).

- **Searched, per stored event, and nothing else**: `content` only when the
  event is **public**; `event_type`, `actor`, `event_id`, `conversation_id`,
  `session_id`, `turn_id`, `correlation_id`, `task_id`, `work_id`,
  `speech_id`, `outcome_id`, `span_id`; the status-code attributes `status`,
  `code`, `reason`, `error_class`. **Never**: diagnostic content (speech
  requests, sub-agent descriptions, work labels, never-played speech), other
  attributes (`tool_name`, `model`, `subagent_type`…), `producer`,
  `trace_ref`, times, journal lines (`runtime/trace.jsonl` is not read). A row
  that does not decode through the codec is never returned (skipped, counted,
  diagnosed); a redaction-violating row cannot decode.
- **Matching**: case- and accent-insensitive without dependency (`fold`: NFKD,
  combining marks removed, `casefold`, `œ æ ø ł đ` expanded, typographic
  apostrophes `’ ‘ ʼ` read as `'`); the query (1..200 characters, at most 8
  distinct terms) is split on whitespace and every term must occur in at least
  one searched field of the same event:
  - public content and status codes: substring;
  - ids: the whole id, or a substring of at least 6 characters
    (`MIN_ID_SUBSTRING`), otherwise `17` would match almost every event through
    the hex digits of its `event_id` (found by the browser probe);
  - `event_type` / `actor`: the whole value or a run of whole dotted tokens
    (`accepted`, `speech.interrupted`), never a fragment, so a short term such
    as `re` does not match every `…accepted` event.
- **Results**: newest first (descending store sequence). Hit =
  `{conversation_id, event_id, sequence, occurred_at, event_type, actor,
  visibility, matched: [field…], snippet, marks: [[start, end)…]}`; the
  snippet is ±60/120 characters of public content around the first term, or
  `event_type · field = value` for a metadata match; `marks` are code-point
  ranges (the page slices with `Array.from`). Page =
  `{schema_version: 1, hits, next_cursor, has_more, skipped_rows, scanned_rows,
  scan_limited}`; continue with `before_sequence=next_cursor` while `has_more`.
- **Bounds**: `limit` 1..50 (20); at most `MAX_SEARCH_SCAN_ROWS` = 50 000 rows
  scanned per request (`scan_limited: true` then, with the cursor to
  continue). Optional `conversation_id` (uses its index) and `visibility`.
- **How it scans (rework, Core's hot path first)**: each chunk of
  `SEARCH_SCAN_CHUNK` = 250 rows is one short read on the repository lock that
  returns only the searchable columns; SQLite extracts content (public rows
  only) and status codes from the JSON itself (`json_valid`, `->>`), so the
  stored document is never parsed in Python for a row that does not match.
  Matching then runs on the event loop in slices of at most `SEARCH_SLICE_S` =
  2 ms, with `await asyncio.sleep(0)` between slices and chunks; there is no
  worker thread competing for the GIL. Folding is C-level (`lower()` for ASCII;
  NFKD, one regex for U+0300–U+036F, a translate table for other combining
  marks), tested equal to the reference definition. Only matched rows are
  re-read whole and decoded. A cancelled search stops at its next yield. When the log ends exactly at the scan budget the page still
  says `has_more`; the next request returns an empty final page. A hit whose
  row no longer decodes ends the scan at that row, so rows after it are read by
  the next page, never skipped.
- **Decision: no FTS5, no schema change.** At Jarvis scale (thousands of
  events per week) a bounded cooperative scan is enough; FTS5 would need a
  state migration (v3), an accent-folding tokenizer and triggers. Revisit when
  the log passes several hundred thousand rows. Measurements are in Hot path.

## Hot path

Heavy reads must never slow what the user hears: appends (every Brain and Mouth
event, user turns) share the state repository lock and Core's event loop with
them.

- **Admission**: `ConversationEventQueryService` runs at most one search
  (`MAX_CONCURRENT_SEARCHES`) and two transcript/export builds
  (`MAX_CONCURRENT_PROJECTIONS`) at once. Over capacity the request is refused
  at once with 429 `search_busy` / `projection_busy` (Core and Control Center;
  not a failure episode; the page says a search or build is already running and
  offers *Réessayer*). Nothing is queued. Every exit gives the slot back:
  success, error, cancellation, a client that leaves mid-export, an export never
  iterated.
- **Cancellation**: aiohttp does not cancel a handler whose client left. Core's
  search and transcript routes run their work as a task and check the client
  connection every 0.25 s (`CLIENT_CHECK_S`), cancelling it when the client
  left or the server stops; an export stops at its next write. The Control
  Center watches the browser connection (as for long-polls) and cancels its
  Core request, which closes that connection, so an abandoned browser search is
  cancelled in Core within about a second (probe: 3 browser searches aborted
  after 0.5 s → the first cancelled in Core after 0.8 s, the other two refused 429).
- **Yielding**: search as above; transcript and export read 50 events per store
  read and yield between pages; export encoding yields every 2 ms.

Measured 2026-09-17 (scratch `slice06/hot/hotprobe.py` on a copy of QA's
80 001-row store, rows ≈1.4 KB; one-event appends every 5 ms; loop lag = time
for `await asyncio.sleep(0)` to return, sampled every 2 ms):

| Case | Before (append p50 / p95 / max, loop lag p95 / max) | After |
|---|---|---|
| idle | 2.1 / 3.4 / 45 ms, 0.7 / 0.9 ms | 2.7 / 3.5 / 19 ms, 0.7 / 1.6 ms |
| one search scanning 50 000 rows, repeated | 11.4 / 204.7 / 292 ms, 0.7 / 47 ms; 7.5 s per scan | 2.0 / 4.2 / 14 ms, 1.5 / 4.5 ms; 2.1 s per scan |
| 4 concurrent searches | 2.4 / 904 / 1 053 ms, lag max 62 ms (all 4 ran) | 2.1 / 3.8 / 19 ms, lag max 2.4 ms (1 runs, 3 refused 429) |
| transcript of 30 000 events (≈21 MiB of text) | 2.1 / 29.8 / 160 ms; rendered in 3.5 s | 1.9 / 2.4 / 11 ms; refused 413 after 2.7 s (text budget) |
| same, budget raised to 64 MiB (render cost) | — | 1.8 / 3.4 / 125 ms, lag max 16 ms; rendered in 5.1 s |
| export of 50 001 events (75 MB) | 13.0 / 87.3 / 105 ms; 10.7 s | 7.4 / 9.2 / 27 ms; 13.6 s |

QA's own probe (`qa06/lockprobe.py`, rerun on the copy): one search append p50 /
p95 2.0 / 4.2 ms (worst loop lag 18 ms); four searches started directly on the
store, bypassing the service cap, 30.7 / 37.8 ms. Search latency was traded for
nothing: the cooperative scan is faster than the threaded one (2.1 s vs 7.4 s
for 50 000 rows ≈ 1.4 KB) because SQLite extracts the fields and folding runs in
C. Known limit: rendering a transcript near its 16 MiB budget runs in a thread
and can still delay single appends by about 100 ms (p95 unaffected).

## Projection routes and errors

| Core route | Control Center route | Answer |
|---|---|---|
| `GET /v1/conversation-events/transcript?conversation_id=&mode=plain\|detailed&utc_offset_minutes=` | `GET /api/conversations/transcript` | 200 `text/plain; charset=utf-8`, streamed |
| `GET /v1/conversation-events/export?conversation_id=` | `GET /api/conversations/export` | 200 `application/x-ndjson; charset=utf-8`, `Content-Disposition: attachment`, streamed |
| `GET /v1/conversation-events/search?q=&conversation_id=&before_sequence=&limit=&visibility=` | `GET /api/conversations/search` | 200 search page |

Typed client: `LocalCoreClient.stream_conversation_transcript` (async iterator
of byte chunks; `get_conversation_transcript` joins them),
`export_conversation_events` (async iterator of byte chunks),
`search_conversation_events`. Errors follow the query API table: 400
`invalid_request` (strict parameters, message names the rule never the value),
401, 503 `conversation_events_unavailable` (diagnosed once per episode), plus
413 `transcript_too_large` and 429 `search_busy` / `projection_busy` (Core and
Control Center, see Hot path). Control Center: same
origin guard as every `/api/conversations...` route, 503 `core_unreachable` /
`not_configured` / `control_center_stopping`, 502 `core_unauthorized` (after one
token re-read, also before an export's first byte) / `core_refused` /
`invalid_core_response`; read budgets 60 s (transcript), 30 s (search), 15 s to
the export header then 30 s between chunks.

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
| `list_conversation_events(conversation_id, after_sequence, limit, until_sequence?)` | event page (`until_sequence`: never past it, used by the frozen export) |
| `conversation_extent(conversation_id)` | `ConversationEventExtent(stored_rows, first_sequence, last_sequence)` or None (index only, nothing decoded) |
| `search_events(query, conversation_id?, before_sequence?, limit, visibility?, max_scan_rows)` | search page (see Search) |
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

## Operations

### Export, search, read

- **Browser**: Control Center → **CNV** → *Exporter JSONL* (saved only when
  complete), *Transcription* (simple/détaillé, *Télécharger .txt*),
  *Rechercher* (jump to the entry). Direct URLs on the Control Center
  (loopback only): `http://127.0.0.1:17654/api/conversations/export?conversation_id=<id>`,
  `/api/conversations/transcript?conversation_id=<id>&mode=detailed`,
  `/api/conversations/search?q=<words>`.
- **Without the Control Center**: Core routes with the session bearer token
  (`runtime/core.token`, or `JARVIS_CORE_TOKEN_FILE`; rewritten at every Core start; Core listens on
  `JARVIS_CORE_HOST`, default `127.77.0.1`) and
  `X-Jarvis-Protocol: 1`, or `LocalCoreClient` (see Projection routes).
- **Offline**: `read_export` + `transcript_from_export` / `reconstruct_export`
  (snippet in JSONL export). Always check `result.complete` and
  `result.invalid_lines` before trusting a file.

### Recovery

- **Core crash**: acknowledged events are durable (WAL, `synchronous=FULL`).
  At start Core re-records user turns whose event a crash lost (Start-up
  backfill); Brain events in the ~60 ms commit window are lost by decision.
  Proven end to end by `test_conversation_event_rollout_gate.py` (child Core
  killed with `os._exit` while the user event is queued; restart; export,
  transcript, search and drill-down all consistent).
- **Voice / Control Center crash**: their forwarder queue (≤ 1024 events) is
  lost; nothing to recover (Forwarder, loss bounds). Counters:
  `GET /v1/health` → `conversation_events`, `GET /api/status` →
  `conversation_events`, voice `conversation_events.forwarder_*` journal lines.
- **Damaged rows**: never repaired or deleted; skipped, counted
  (`skipped_rows`, `unreadable_rows`) and diagnosed
  (`core.conversation_events.row_unreadable`). An export of the conversation
  keeps every readable event and states the skipped count.
- **Migration rollback**: `<db>.v1.bak`, procedure in
  [state model](state-model.md). Take a JSONL export of the conversations you
  care about first: a v1 binary cannot read the log.

### Storage size and retention

Measured 2026-09-17 on a scratch store filled with 23 000 copies of the
rollout-gate conversation's real events (voice, Brain, sub-agent, tool): stored
`data` averages **845 bytes** per event and the database grows by **≈1.8 KB per
event** after checkpoint (row, extracted columns, 10 indexes; ids are UUIDs).
An export line averages 923 bytes. That conversation stores 23 events for 4
user turns plus a crashed one, i.e. **≈5–6 events per turn** with work, a
sub-agent and a tool call. Estimate: 100 turns a day ≈ 600 events ≈ 1.1 MB/day
≈ 400 MB/year; a quiet day of 20 turns ≈ 80 MB/year. Retention exists
(`ConversationEventRetentionPolicy`, closed and idle conversations only) but is
**disabled and not scheduled**: nothing is ever deleted today. Export before
enabling it.

### Privacy boundaries

- The log holds user transcripts and what Jarvis said: private by nature. It
  lives only in the Core state DB (`data/state/jarvis.sqlite3`, git-tracked in
  this workstation layout: do not push it) and leaves Core only through
  authenticated loopback routes; the Control Center routes refuse any
  non-loopback `Host`/`Origin` and `Sec-Fetch-Site: cross-site`.
- Never in an event (so never in a transcript, export or search result): hidden
  reasoning, prompts (including sub-agent prompts), raw tool arguments and
  results, provider error text, audio, secrets (contract allowlist + recursive
  forbidden-key scan). Sub-agent summaries never leave the tracker.
- Search never reads diagnostic content or journal lines; the trace drill-down
  returns allowlisted, value-checked journal fields only.
- An exported file and a downloaded transcript are copies outside Jarvis's
  guards: store them like the conversation itself.

## Validation

```powershell
$env:PYTHONDONTWRITEBYTECODE=1; .venv/Scripts/python.exe -W error::ResourceWarning -m pytest -q -p no:cacheprovider tests/unit/test_conversation_events.py tests/unit/test_conversation_event_store.py tests/integration/test_conversation_event_store_recovery.py tests/unit/test_conversation_event_emitter.py tests/unit/test_conversation_event_producers.py tests/integration/test_conversation_event_ingest_protocol.py tests/integration/test_conversation_event_production.py tests/unit/test_conversation_event_forwarder.py tests/unit/test_conversation_event_mouth_producers.py tests/unit/test_conversation_event_voice_bridge.py tests/unit/test_conversation_event_subagents.py tests/integration/test_conversation_event_timeline.py tests/unit/test_conversation_event_query_contract.py tests/unit/test_conversation_event_trace.py tests/integration/test_conversation_event_query_protocol.py tests/integration/test_control_center_conversation_events.py tests/unit/test_control_center_timeline_js.py tests/unit/test_control_center_timeline_ui.py tests/unit/test_conversation_transcript.py tests/unit/test_conversation_event_export.py tests/unit/test_conversation_event_search.py tests/integration/test_conversation_event_projections_protocol.py tests/integration/test_control_center_conversation_projections.py tests/integration/test_conversation_event_rollout_gate.py tests/unit/test_conversation_event_query_limits.py
```
