# Conversation Events (contract, schema version 1)

Canonical record of what happened in a conversation, captured from backend
events and never rewritten by a model. Readable transcripts, exports and the live
timeline are projections of these events, not separate truths.

- Implementation (Level 3): `jarvis/domain/conversation_events.py` (pure domain:
  no I/O, no clock, no provider import).
- Conformance tests: `tests/unit/test_conversation_events.py`.
- Golden fixture: `tests/fixtures/conversation_events/overlapping_conversation.json`.
- Handoff: `tasks/jarvis-conversation-observability-timeline/` (Slice 01).

Status 2026-09-16: contract only. Storage (SQLite, store sequence) is Slice 02,
producer instrumentation Slice 03, query/stream API Slice 04. No producer emits
these events yet and no HTTP route exists.

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
| `user.transcript.accepted` | user | I | P | correlation, turn | req | two candidates, see note 1: journal `voice.brain_turn_submitted` (present in live traces); journal `core.voice.turn_admitted` + bus `voice.turn.admitted` (0 live lines on 2026-09-16) | `jarvis/runtime/realtime_audio.py`, `jarvis/core/voice_admission.py` |
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
| `system.failure` | system | I | D | — | — | journal `voice.brain_turn_rejected`, `voice.speech.stream_failed` | `jarvis/runtime/realtime_audio.py`, `jarvis/runtime/speech_scheduler.py` |

Notes:

1. **User turn producer.** Both sources above describe the same fact. Because
   `producer` is part of `event_id`, only one producer may emit
   `user.transcript.accepted`; Slice 03 chooses it from live evidence, Core
   admission preferred. The golden fixture shows one turn from each candidate.
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
| `user.transcript.accepted` | `(session_id, canonical turn id)` |
| `brain.turn.accepted`, `brain.turn.failed` | `(correlation_id,)` |
| `brain.message.published` | `(correlation_id, outcome_id)` |
| `brain.speech.requested`, `mouth.speech.*` | `(speech_id,)` |
| `brain.work.*` | `(work_id,)` |
| `mouth.reflex.started` | `(correlation_id, output_id)` |
| `subagent.*` | `(task_id,)` |
| `tool.call.*` | `(call_id,)` |
| `system.failure` | producer failure identity (e.g. `(correlation_id, code)`) |

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
- `agent.subagent.*` lines carry no `conversation_id`. Slice 03 must map
  `task_id` → conversation (and pick a stable sub-agent source id, since
  `AgentTaskTracker` can re-key a task from `tool_use_id` to `task_id`).

Events also join each other: user → brain by `correlation_id`/`turn_id`, brain
speech → mouth by `speech_id`, brain work → sub-agent by `work_id` and
`parent_event_id`.

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

## Validation

```powershell
$env:PYTHONDONTWRITEBYTECODE=1; .venv/Scripts/python.exe -W error::ResourceWarning -m pytest -q -p no:cacheprovider tests/unit/test_conversation_events.py
```
