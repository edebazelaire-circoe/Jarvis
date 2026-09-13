# Task08 — Core source and available outcome persistence

Core owns `BrainOutcomeService` (`jarvis/core/brain_outcomes.py`) through
`BrainOrchestrator` and `JarvisCoreApplication.outcomes`. Its repository is the
existing `StateRepository` / `SQLiteStateRepository`. It neither executes work
nor appends an assistant history turn. Task11 retains the independent executor
and generic Job ingress. The canonical voice ledger remains the sole projection
of confirmed heard text.

## Source and ordering contract

`SpeechSource` carries the real persisted Core `ConversationTurn.id`, the input
correlation, an opaque `intent_id` equal to that Core turn ID, a durable arrival
`intent_epoch`, and exact dependency pairs `(work_id, source_correlation_id)`.
It does not carry an invented canonical voice turn or Job ID. Epochs increase
per conversation in SQLite and survive restart; they are not a
`BrainWorkingState.revision`, monotonic clock or transcript revision.

Each input gets its own origin at admission. An UNCERTAIN input leaves the
current source unchanged until Core promotes it. Promotion uses the existing
arrival-order rule and cannot replace a newer confirmed intent. The current
source is stored independently; cold derivation reads its actual user turn.
A completed outcome from A delivered after B therefore keeps source A.

`brain.turn.accepted` and `brain.intent.revised`, and the HTTP turn acceptance,
add `schema_version: 1`, `source` (the originating turn), and this projection:

```json
{
  "conversation_id": "opaque-conversation",
  "current_speech_source": null,
  "invalidated_dependencies": [],
  "source_complete": true
}
```

`current_speech_source` is a typed source payload or null. Consumers must use
it, not `source`, to advance presentation freshness. Invalidations retain the
exact dependency generation. The snapshot returns at most 256 invalidations;
overflow sets `source_complete: false`, requiring conservative deferral after
a stream gap. Truncation never pretends that the projection is complete.

When a backend A reports a work name now owned by a newer source B, its late
ACCEPTED/PROGRESS/COMPLETED/FAILED/CANCELLED/SUPERSEDED observation cannot mutate
B. A public terminal result is still retained before rejecting that mutation.
A newer authoritative turn can explicitly designate an older active work.
Missing source order for different owners is ambiguous and rejected, with a
diagnostic. This is a narrow compatibility rule for reusable backend work names,
not a substitute for immutable executor Job IDs in Task11.

If B describes a result using a work name currently owned by A, the public
result keeps origin B but no dependency generation is invented. Its source has
no asserted work dependency, and Core defers presentation with
`ambiguous_work_dependency`. Deduplication preserves that first provenance,
including after the owner disappears. An explicit selection under the current
intent remains possible. Control designation B→A is distinct and still allowed.

## Outcome identity and publication

`BackendOutcome` contains `id`, `conversation_id`, typed `source` or null,
optional `work_id`, exact public `text`, aware UTC `created_at`, `kind`
(`speech_result`, `work_result`, `turn_result`) and `status`
(`completed`, `failed`). The text bound is 65,536 characters. Provider SDK types,
PCM, hidden reasoning and executor permissions are absent.

The ID is a SHA-256 identity of conversation, originating correlation, optional
work ID, status and exact text. It is independent of event channel and temporary
speech ID. Thus repeated SPEECH and COMPLETED for the same content and work join
one result; kind may mature from `speech_result` to a terminal kind. The original
source, text, timestamp and identity remain immutable and conflicting writes
fail. A different terminal text creates another preserved content version.
When two observations both read no stored version and owner knowledge changes
between them, the losing save rejoins the first persisted provenance only after
checking exact content, identity and Core origin. Only unknown versus that same
origin's work dependency is admissible. The repository's strict conflict checks
remain unchanged and revalidate the retry; no new worker or queue is involved.
`BrainTurnResult` carries no work ID, so its turn aggregate remains separate from
identified work results; Core never guesses that linkage. A speech without a
work ID and the same turn settlement text join the same result.

Retention precedes `brain.outcome.available`, `brain.work.completed` and
`brain.speech.requested`. A result speech is retained before freshness or
invalidated-dependency filtering. `brain.outcome.available` carries
`{schema_version: 1, outcome: <payload>}`. Completion's `result_ref` references
that outcome when there is a public summary. Failed persistence propagates;
no result-available or speech publication claims success. Retrying identical
content is idempotent even after restart. SQLite's cancellation-safe native
worker ownership from Task05/07 is unchanged.

Available results can inform Brain's public knowledge after restart, but this
is never a claim that the user heard them. `rehydrate()` returns a bounded
`available_outcomes` list separately. Canonical conversational heard context
continues to come from the evidence ledger.

## Authenticated protocol

All routes reuse existing loopback token and protocol-version middleware.
There is no client outcome/source write endpoint.

`LocalCoreClient.events(on_connected=callback)` exposes the existing server
subscription acknowledgement as a local callback. A scheduler can await that
barrier before reading `speech_context`, avoiding a query-before-subscription
gap; the acknowledgement remains absent from the canonical event iterator.

| Client method | Route | Result |
| --- | --- | --- |
| `speech_context(conversation_id)` | GET `.../speech-context` | Versioned current source/dependencies projection |
| `list_brain_outcomes(conversation_id, limit=32)` | GET `.../outcomes?limit=N` | `{schema_version, conversation_id, outcomes}`; integer 1–128 |
| `get_brain_outcome(conversation_id, outcome_id)` | GET `.../outcomes/{id}` | Exact outcome payload |
| `select_brain_outcome(conversation_id, outcome_id, selection_id=...)` | POST `.../outcomes/{id}/select` | `{schema_version, outcome_id, speech, duplicate}` |

Selection accepts exactly a bounded printable `selection_id`. Core resolves
the existing outcome and current source itself. It persists a new candidate
with a deterministic speech ID, current origin, existing outcome ID and exact
semantic spans; the original outcome source remains unchanged. No backend or
Job runs. A repeated selection ID returns the same stored candidate without
republication, including after restart; choosing again requires a new ID.
An ID reused for a different outcome fails. No current or incomplete source
means selection is refused. A candidate that cannot fit semantic presentation
bounds is not silently truncated. Retrieval and Core restart never replay it.

Publication is live notification, not a durable replay queue: a crash after
selection persistence but before publication may leave that candidate unseen.
Its stored response remains inspectable on retry; a new explicit selection can
request fresh presentation. This avoids replaying stale speech on restart.

## Observability and verification

`DiagnosticSink` is wired to the existing `RuntimeJournal`. Normal milestones
are `core.brain.outcome_retained`, `core.brain.outcome_selected` and
`core.brain.speech_deferred`. Correlation uses conversation, originating Core
correlation, outcome and speech IDs. `core.brain.stale_work_observation` explains
older/unknown-source drops. Persistence failure uses
`core.brain.outcome_persistence_failed`, code
`brain_outcome_persistence_failed`, and exception class only. Public text,
storage exception detail, secrets and provider payloads are excluded.
The owned backend task observes a failed terminal settlement through
`core.brain.turn_settlement_failed` / `brain_turn_settlement_failed`; it neither
leaves an unobserved task exception nor converts Core persistence failure into
a successful available result or a fabricated backend failure.

`test_core_brain_outcomes.py` exercises exact versions, concurrent/restart
deduplication, immutable identity rejection, source order, UNCERTAIN late
delivery, reused work generations, invalidation capacity, defensive JSON copies,
strict ranges and the real RuntimeJournal's normal/error records. The project's
`read_jsonl_tail` journal reader verifies emitted records; no separate LogBroker
CLI exists in this repository. `test_brain_outcome_protocol.py` covers token
authorization, unknown conversations, strict request shapes and bounded queries.
Independent `test_voice_outcome_retention.py` uses real Core HTTP/SQLite to prove
retention before publication, restart without heard history, current-vs-old
source, explicit selection and retry after injected storage failure.

Final Core regression gate: **227 passed, 8.90 s**, warnings as errors
(outcome/protocol, Brain/intent/recovery, canonical ledger/codec, architecture/config).
The additional real Control Center backend test
`test_real_control_center_backend_retains_long_unpresentable_result` in
`tests/unit/test_core_brain_outcomes.py` delivers three cases through HTTP into
BrainService: a >8192-character single paragraph, an exact >8192-character
two-paragraph chain, and 17 paragraphs. All remain exact durable completed
outcomes after repository reopen. Only the eligible two-paragraph chain emits
speech, with two exact spans each <=8192; the other cases defer without false
failure or fabricated assistant history/Jobs. These tests plus Core outcomes
and adapter migration: **68 passed, 4.62 s**, warnings as errors.
Final parent release: **2294 passed, 4 skipped in 242.19 s**, all release
guards passed. Task08 accepted; see `review-08.md` for independent findings
and the repaired first-pass regressions.
