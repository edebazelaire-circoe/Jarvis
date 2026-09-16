# Canonical voice conversation state — Task04

`jarvis/core/voice_state.py::VoiceConversationState` owns a bounded, immutable projection of canonical voice evidence. `jarvis/domain/voice_state.py` defines its records and version1 snapshot codec. The reducer does not send audio, dispatch tasks, grant permissions, or write durable conversation history. Task05 adds `VoiceLedgerService`, owned by `JarvisCoreApplication`, to ingest canonical observations and project confirmed words through the existing `ConversationService` writer. See the Task05 section below for authenticated ingress, durable range recovery and cache eviction.

## Public API and ownership

| Entry point | Responsibility |
|---|---|
| `VoiceConversationState(conversation_id, diagnostics?, max_users?, max_speeches?, max_tasks?, max_seen_events?)` | One synchronous owner on the Core event loop; updates contain no awaits and commit atomically |
| `bind_session(session_id)` | Bind a new frontend incarnation while preserving conversation/task/heard evidence; duplicate binding is inert; unresolved active ownership blocks replacement |
| `apply(VoiceEvent)` | Reduce canonical evidence with identity, revision, replay and capacity checks |
| `queue_speech(VoiceCorrelation, intended_text)` | Register an intended speech candidate; never play it or convert it to heard history |
| `update_task(VoiceTaskRecord)` | Mirror an existing authorized Core task and its result; never create work from frontend delegation alone |
| `snapshot` | Immutable `VoiceConversationSnapshot`, including retained users, turn order, speech, task references, session and replay metadata |
| `active_tasks` / `speech_candidates` | Immutable tuples for task routing and later speech scheduling |
| `recent_context(limit=12)` | Bounded `VoiceContext` containing committed ordered user text and independently confirmed heard words |
| `VoiceConversationSnapshot.to_dict()` / `from_dict(payload)` | Defensive-copy, strict JSON-compatible version1 serialization |
| `VoiceConversationState.from_snapshot(snapshot, diagnostics?)` | Rehydrate evidence; clear process-local clock and active device claims; unresolved saved sessions become `UNKNOWN_REAP_REQUIRED` |

No method executes an action. Both `VoiceStateResult.authorizes_actions` and `VoiceConversationSnapshot.authorizes_actions` are false. Existing Core action/confirmation gates remain mandatory even after a provider transcript is committed. Task records are references to existing Core work, using the existing domain `WorkStatus` and transition rules. Their source must be a retained committed user turn. A task result changes task data only; it does not enqueue speech. Frontend replacement does not cancel active backend tasks.

`VoiceStateResult` exposes disposition, stable code, and current revision. Dispositions are `APPLIED`, `IGNORED`, `DUPLICATE`, `STALE`, `STALE_SESSION`, `REJECTED`, and `CAPACITY`. Rejected updates leave the previous snapshot unchanged. Canonical audio chunks retain only cumulative received duration; PCM bytes never enter the snapshot.

## User transcript and input ordering

`VoiceUserRecord` keeps correlation, transcript ID, text, revision, committed flag, and explicit `UserCommitSource`. A `UserTranscriptDelta` appends exactly, including whitespace. Its increasing revision indicates observation progression, not replacement. Task04 adds `UserTranscriptRevised` (`user.transcript_revised`) for explicit full replacement of provisional text. Both remain provisional. `UserTranscriptCommitted` supplies a full accepted text replacement and explicit provider/application commit source. Stale revisions are ignored; an already committed grouping cannot be rewritten by a later provisional event. A subsequent correction belongs to a new accepted turn rather than silently changing past action input.

JARVIS turn IDs are globally unique within the conversation, across frontend incarnations. Provider input IDs remain separate, opaque correlation values. `UserTurnOpened.previous_turn_id` establishes input chronology independently of ASR final arrival. `VoiceTurnOrder` retains this relation and a durable observation order. FinalB-before-finalA updates both records without moving active intent back from B to A. The reducer also handles B's ordering observation before A arrives; cycles and conflicting parent identity are rejected. A transcript lacking known turn order remains available as evidence but is not arbitrarily inserted into ordered rehydration context.

Delegation and VAD observations do not commit transcripts or create tasks. In particular, Live delegation does not establish authoritative transcript finality. Replacements and speculative text cannot dispatch irreversible work through this state API.

## Intended, generated, delivered and heard

`VoiceSpeechRecord` retains these independently:

- `intended_text`: original application/backend request, if any;
- `generated`: bounded `VoiceGeneratedText` parts with transcript IDs and provider completion flags;
- `generation_status`: provider generation evidence, independent of playback;
- `received_audio_ms`: cumulative normalized PCM duration received, without retaining bytes;
- `played_ms`, `playback_status`: cumulative local device evidence;
- `confirmed_text`: cumulative independently aligned heard prefix, or unknown;
- `state`, `local_active`: candidate/generation/interruption history and explicit local activity;
- `first_played_order`: durable observation ordering for context, not a clock duration.

Speech evidence needs an application speech ID, local output ID or provider output ID. `output_id` identifies the local frontend output; `provider_output_id` retains the actual provider response ID. Correlation may be enriched with missing identity, but conflicting session/turn/task/speech/output/response identities are rejected. Response-level records retain up to16 distinct `provider_item_ids`; aggregate correlation's `provider_item_id` becomes null when more than one item exists, while each generated transcript retains its own grouping ID. Multiple provider items therefore do not become correlation conflicts or disappear. Adapters must assign application grouping identity where providers have no output item ID; never fabricate provider IDs or infer exact alignment.

States are `QUEUED`, `GENERATING`, `PLAYING`, `COMPLETE`, `INTERRUPTED`, `CANCELLED`, `UNKNOWN`, and `UNSPOKEN`. Provider-generated text and completed generation never establish complete local playback. A completed silent generation with no received/played audio becomes `UNSPOKEN`, remains unheard, and is eligible for retention eviction. Received audio waiting for local playback remains pending. Local STOP alone does not establish end-of-output or heard words.

`confirmed_text` is cumulative, not a delta. Repeated or extended confirmation replaces that value without duplicating words. A shorter or conflicting prefix is rejected, as are retrograde playback cursors. Later unknown word alignment retains any earlier confirmed prefix; it never appends the generated tail. Zero played audio cannot carry confirmed text. Full device delivery can still have unknown words.

Interruption evidence does not itself prove the local device stopped: explicit local activity/playback remains separate. A later valid positive playback observation can establish that part of a cancelled output was delivered, changing its state to `INTERRUPTED`. A late generation/transcript completion cannot do this. `playback_status=COMPLETE` may coexist with `state=INTERRUPTED`: all audio covered by the explicit playback evidence finished, while interruption history remains. This never promotes generated text to heard text; only independently supplied cumulative confirmation is retained. The producer must establish an actual output boundary before declaring complete playback; queue emptiness alone is insufficient.

Valid delayed playback remains evidence even after a newer user turn. Recent context places those words after user turns already observed when playback began; it does not regroup a late answer to A before the newer question B merely because A is its source turn.

Closing/stopped/uncertain frontends cannot accept new speech candidates or resurrect activity through late STARTED/input/interruption observations. Historical output transcripts and valid playback confirmations can still be recorded while the old session remains bound. After a new incarnation is bound, old-session events are rejected. Existing ledger and task references survive the bind.

## Bounded retention and replay

Default hard maxima: 64 user transcript records, 128 turn ordering records, 64 speech records, 32 task references, 512 deduplication entries, 16 generated parts per output. User/intended/generated/confirmed/task-result text is bounded to8192 characters; task summaries to1000. An output's combined generated text is bounded to8192. Collections and counters are validated before mutation.

Only inactive speech and terminal task references may be evicted to make room. User turns referenced by retained tasks, active speech or current intent are protected; current provisional input is protected. Unreferenced ordering records can be evicted while predecessor IDs remain opaque history references. If active/current records fill a bound, the update returns `CAPACITY` and reports a warning rather than silently dropping active task references or changing existing state. Bounded recent context is selected from retained evidence; this is not long-term semantic memory.

Deduplication uses the current session plus event ID. The bounded cache records canonical sequences; after eviction, a sequence floor rejects expired replay instead of allowing an old event to mutate newly retained state. Distinct event IDs claiming the same retained sequence are rejected. Snapshot restore retains deduplication state. A frontend ID must never be reused for a later incarnation.

**Task05 integration requirement: provider observations and local playback observations need one shared canonical sequence allocator at the merged Core submission boundary.** Existing bridge output events wait behind ordered playout while urgent input events can bypass that queue. Do not use independent provider/audio counters, or a provider receipt sequence that becomes stale only because valid playback dispatch was delayed. Allocate sequence when dispatching into the canonical reducer; retain provider event IDs and provider intervals separately. Out-of-order ASR text still uses turn/predecessor identity for conversation order. This is an integration invariant, not an assumption that the current legacy bridge already meets it.

## Snapshot schema and rehydration

Version1 contains exact root fields: `conversation_id`, `current_session_id`, `lifecycle`, `revision`, `active_turn_id`, `users`, `turns`, `speeches`, `tasks`, `seen_events`, `sequence_floor`, `last_observed_at`, `schema_version`. Record field names correspond directly to frozen domain dataclasses. Enums encode as strings, records as objects, tuples as JSON arrays, and the optional timezone-aware wall-clock observation as ISO8601. Unknown fields or missing fields are rejected, including nested records and correlations. The codec validates version/type, opaque IDs, integer revisions/order/counters, finite nonnegative durations, collection/text bounds, duplicate identities, acyclic ordering, committed source-task references, and impossible playback/confirmation combinations.

`to_dict` creates fresh nested containers; input mutation after `from_dict` cannot change restored state. No provider SDK types, payload dictionaries, credentials, audio bytes, or process-local monotonic timestamps are stored. `last_observed_at` is historical observation time, not a current timer. Rehydration clears `last_monotonic_ns` and local activity; saved active/starting/stopping sessions become uncertain and require external lifecycle reconciliation. Snapshot rehydration does not claim provider connectivity or start billing timers. Provider/model/prompt fingerprints and durable lifecycle ownership belong to later Tasks13/17.

Recent task summaries are available through `active_tasks`, separately from recent conversation messages. Facts and pending candidates are never promoted to assistant history. The existing `ConversationService.rehydration_context` strips history metadata and can expose historical partial intended text; **canonical sessions now use the ledger context instead of that legacy context.** Unbound legacy/Gemini conversations retain the existing behavior. Provider session ownership and later provider-switch recovery remain separate from this history projection.

## Observability and validation contract

Use the existing `DiagnosticSink` with `RuntimeJournal`; no new logging subsystem. The canonical, user-visible conversation timeline (as opposed to these diagnostics) is defined by [Conversation Events](conversation-events.md); its events join these journal lines through `trace_ref` and never copy the private fields this section excludes. Normal application/binding, duplicate/stale/session-rejected replay and task/candidate updates emit `voice.state.updated` at info with stable `voice_state_*` code. Generated/intended divergence emits `voice.state.diverged` at info, with code `voice_state_generated_divergence`; divergence is evidence, not a failed operation. Invalid/capacity updates emit `voice.state.rejected` at warning. A canonical frontend failure emits `voice.state.frontend_error` at error with the original stable `VoiceErrorCode`, without the raw exception/message. High-frequency audio receipt does not emit a diagnostic per chunk.

Diagnostics contain conversation/session/revision and event/turn/task/speech IDs where supplied, never transcript, intended/generated/confirmed text, task result, PCM or raw provider payload. Invalid identity is omitted rather than copied into rejection logs. Diagnostic sink failures do not undo applied evidence and are counted in `diagnostic_failures`; the host can inspect that count. There are no temporary probes.

Validation command:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_voice_conversation_state.py tests/unit/test_voice_frontend_contract.py tests/unit/test_voice_architecture_config.py tests/unit/test_v2_architecture.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

2026-09-12: **146 passed in1.66s**, including43 state tests. Tests exercise the deterministic frontend through the real reducer, divergence before/after playback, partial unknown alignment, cancellation, cumulative confirmation, delayed valid playback chronology, ASR ordering, explicit provisional replacement, task survival, retention, replay, strict JSON round-trip, mutation isolation, malformed input and closed-session activity rejection. Real `RuntimeJournal` files are queried with supported `read_jsonl_tail`: normal/drop/divergence info, capacity warning, one intentional transport error, and no private content leakage. Provider/audio hardware access is neither required nor claimed.

## Task05: Core ingress and the durable heard projection

`JarvisCoreApplication.voice_ledger` owns `VoiceLedgerService`. The client cannot replace its snapshot or supply a new history projection. `domain/voice_event_codec.py` supplies strict `encode_voice_event`, `decode_voice_event` and `decode_voice_correlation`. Encoded events have version1, exact envelope/payload fields and canonical `kind`; invalid IDs, enums, versions, nested types, nonfinite counters and unknown/provider fields are rejected. `AssistantAudioChunk` is forbidden at this boundary. Runtime sends `AssistantAudioReceived(received_ms)` with cumulative decoded duration; a lower cumulative duration is stale. `VoiceToolCallRequested` carries bounded JSON arguments but neither its codec nor reducer executes the tool or grants authority.

The authenticated loopback protocol exposes these `LocalCoreClient` methods:

| Client method | Endpoint and body |
|---|---|
| `bind_voice_session(conversation_id, session_id)` | POST `.../voice/session`, `{session_id}` |
| `submit_voice_observations(conversation_id, session_id, events)` | POST `.../voice/observations`, `{session_id,events}`; 1–32 encoded events |
| `voice_snapshot(conversation_id)` | GET `.../voice/snapshot` |
| `register_voice_speech(conversation_id, correlation, intended_text)` | POST `.../voice/speech`, `{correlation,intended_text}` |

Here `...` means `/v1/conversations/{conversation_id}`. Bind/register responses contain `conversation_id`, currently bound `session_id`, `revision` and `result:{disposition,code,revision}`. Observation responses contain the same identity/revision plus ordered `results` and `history_updates` (durable range completions). Snapshot returns `{conversation_id,snapshot}`, with null when no canonical ledger exists. Malformed bodies/events return400; unknown conversation404; authentication401; incompatible protocol426; mutation while Core stops503. Valid stale/duplicate/rejected observations return200 with explicit reducer dispositions. The whole transport batch is decoded before any state mutation. No snapshot-write endpoint exists.

Canonical user evidence does not append user history. Existing brain-turn admission or legacy admitted-user append remains its sole writer. Task05 buffers provider user observations locally until existing admission succeeds, preventing rejected ambient/failed input from pinning protected Core provisional records; the canonical frontend still exposes deltas, and later speculative analysis needs its own explicit lifecycle if it retains unadmitted state.

`core.context` selects `VoiceLedgerService.context` for a bound or persisted canonical ledger. It contains only ordered committed users and independently confirmed heard prefixes, an empty summary, and canonical revision/session metadata. It does not read `brain.known_public_facts`, generated text or legacy intended assistant text. `created_at` is null where message-level time is unavailable, not an invented timestamp. Generic assistant `/turns` append is refused for canonical conversations; the migrated runtime must submit playback evidence instead. Legacy/Gemini conversations without a ledger keep the existing context and append behavior.

### Append-only confirmed ranges and crash recovery

Speech lineage may retain `source_correlation_id` (opaque originating Brain correlation) and `backend_work_id` (opaque existing backend work reference). Neither implies a canonical `task_id` or creates a task. Sparse later events preserve these fields; conflicting known lineage is rejected. Snapshot and confirmed-history metadata retain both, and archival correlation prefers the source Brain correlation when available.

`ConversationService.project_confirmed_voice_text` is the sole new assistant-history projection. Both existing turn and archive stores are append-only/idempotent by record ID, so this method appends only newly confirmed suffix ranges. Example: confirmations `hello` then `hello!!` archive `hello` (0:5) and `!!` (5:7), never overlapping full prefixes. Each range records source session/output/speech/turn/task IDs, played extent, confirmed character boundaries and complete/partial delivery. Interrupted speech remains partial even if all audio covered by its playback observation completed. Generated or intended text is never used as a fallback.

SQLite's indexed `voice_history_projections` table stores `(conversation_id,output_key)`, committed end offset and the exact pending `ConversationTurn`. Staging happens transactionally **before** either existing store write. Projection then replays that exact pending range through `ConversationService.append_turn`, and only after both SQLite turn and JSONL archive accept it does a transaction advance the offset and clear pending. If archive0:5 succeeds but index completion fails, later confirmation0:7 first replays the exact pending0:5 ID idempotently, then appends5:7. The same sequence recovers failure immediately after staging or before archive append, including a Core restart. No phrase-level JSONL scan occurs; offsets and pending records use the SQLite primary key. A bounded in-memory cursor cache is only an optimization.

Projection follows `first_played_order`, not candidate creation order. Archive `created_at` is range creation time; exact pending retries retain that time and ID. Existing conversation `updated_at` cannot move backward during retry. Canonical context still uses full heard text and its evidence chronology, rather than concatenating archive ranges as repeated assistant messages.

### Bounded ledger registry and persistence

The state DB runs WAL with `synchronous=FULL` (explicit since schema v2): a committed transaction is on disk before the call returns. `schema_version` migrations are forward-only, one transaction per step (`sqlite_state._MIGRATIONS`); v2 adds the Conversation Event log (`conversation_events`), which shares this connection and lock through `SQLiteStateRepository.run_serialized`. A `run_serialized` callback cannot leave that shared connection inside a transaction: on failure it is rolled back (the original error kept), and a callback that returns with a transaction still open is rolled back and raises `RuntimeError`. Its append/cursor/conflict/recovery/retention guarantees are in [Conversation Events, Storage](conversation-events.md#storage). A binary older than the file refuses to open it (`newer than supported`); the DB is never downgraded or repaired by deletion.

Before migrating an **existing** file, Core writes a one-time online backup `<db>.v<old version>.bak` next to it (for the 1 → 2 step: `jarvis.sqlite3.v1.bak`), never overwriting an existing one; if the backup fails, startup fails and the file is unchanged. Rollback to the pre-migration state (also the way back to an older Core binary):

1. Stop Core (and anything else holding the DB open).
2. Keep the migrated file aside if its newer data matters (`jarvis.sqlite3` → `jarvis.sqlite3.v2.kept`).
3. Replace the DB with the backup: copy `jarvis.sqlite3.v1.bak` to `jarvis.sqlite3`.
4. Delete `jarvis.sqlite3-wal` and `jarvis.sqlite3-shm`; they belong to the replaced file and would corrupt the restored one.
5. Start the older binary. Everything written after the backup (turns, jobs, conversation events) is lost in the restored file; a newer binary would migrate it again (and, the `.bak` existing, not back it up again).

`data/state/jarvis.sqlite3` is git-tracked and used live. The first Core start with schema v2 migrates it in place, so git shows it modified, and creates `data/state/jarvis.sqlite3.v1.bak`, an untracked copy of the same private data (not covered by `.gitignore`, which only lists `-wal`/`-shm`): never commit it. Restoring the tracked v1 file with `git checkout` is equivalent to step 3 only when the working copy had no newer data.

SQLite initialization, operations and close retain the repository connection lock until native thread work finishes, including repeated caller cancellation. Cancellation is re-raised after that boundary, never translated into successful staging. Native transaction failure still rolls back; a cancelled caller does not permit a second transaction or close to race the worker. This wait preserves connection ownership and does not claim that SQLite thread work can be forcibly cancelled.

The registry holds at most128 conversations by default. A new ledger can evict only a STOPPED ledger with no active canonical task references or speech. Its strict Core snapshot is saved in `voice_conversation_snapshots` before removal; persistence failure leaves it retained and propagates failure. Later bind/context/snapshot loads that trusted Core-owned snapshot, preserving heard evidence and task references. Active capacity is rejected explicitly instead of dropping current work. A ledger transaction lock serializes ingress/projection with registry eviction; awaited storage does not take the separate brain/job execution locks.

Snapshots are saved at terminal close or eligible eviction, not on audio chunks. A crash during an active session is not claimed to have a fresh complete snapshot or a finalized remote session; durable session-owner recovery remains Task13/17 work. The pending history range is independently durable even when the latest active reducer snapshot is unavailable. Client-provided snapshots are never accepted.

Normal range completion emits `voice.ledger.projected` at info with correlation and character counts, never text. Projection failure emits `voice.ledger.projection_failed` at error with stable `voice_history_projection_failed`, leaving pending state retryable. A failed diagnostic sink is counted and cannot undo a durable range or replace the storage error. The actual Task05 device producer remains conservative PARTIAL/UNKNOWN until a real drain boundary is validated; injected COMPLETE/confirmed-text tests demonstrate codec/state/projection behavior, not device playback accuracy.

## Task07: exact audio-part inventory and checked device join

`domain/voice_playback.py` defines immutable neutral `VoiceAudioPart(item_id, content_index, output_index=None)`, part byte extents, `VoicePlaybackManifest`, and `VoiceDevicePlaybackProof`. The manifest identifies session/local output/provider response and every positive received part extent. Device proof additionally carries audio-instance identity, output/playback epochs, operation ID, actual written parts and written/confirmed byte counts. `completed` requires positive fully confirmed bytes; unknown/failed/stale never qualify. Device ownership and epoch validation belong to the actual audio worker, not to the provider ledger.

The low-level Realtime adapter preserves wire item/content/output indices on audio and transcript observations. `AssistantAudioPartCompleted` closes one identified provider part; it does not finish a response or prove playback. `AssistantGenerationFinished` optionally carries the ordered `audio_parts` inventory and aligned `audio_transcripts` from the explicit final response. Missing inventory (`None`) differs from a known empty tuple. Known text/output_text content is excluded from audio heard text; unknown content or incomplete assistant items make the inventory ineligible. Audio/output_audio variants are normalized. GPT-Live pauses do not produce an invented completed inventory.

`runtime/voice_playback_manifest.py::VoicePlaybackManifests` joins these facts through the actual facade. `playback_manifest(payload)` freezes a matching completed response only when all expected parts have positive received bytes and audio closure, with no unidentified/extra part. `observe_device_completion(manifest, proof)` accepts only exact session/output/response and part-byte equality after the runtime's checked device drain. The playback worker owns that native operation; these methods neither perform a drain nor fabricate its result. Rejected/dropped writes, missing parts, stale identity and non-complete proof cannot produce heard text.

A valid drain can first emit COMPLETE with no confirmed text. Full generated words are added only when every matching audio transcript final is present, in manifest order, and agrees with any transcript supplied by the final inventory. No prefix is estimated from milliseconds. Part closure/delta/audio contradictions after freeze are rechecked before publication. Duplicate proof causes no second projection. A final transcript for an old output can join its retained proof after a newer output begins; interruption, explicit close, invalidated preamble, failure or retention eviction remove eligibility. Finals arriving only during/after explicit close remain conservatively unconfirmed. No guarantee of transcript recovery across process restart is made.

The join retains at most 128 output records and **16 effective audio parts per output**, matching the existing Core generated-part bound. Neutral input types allow up to 128 indexed parts for strict bounded decoding, but that larger type bound does not claim runtime completion support. Total retained final transcript per output is 8192 characters. These volatile proof records are not persisted or transferred as live device authority. Core continues to own the sole durable confirmed-range projection.

`VoiceGeneratedText.part` persists exact item/content/output indices in the existing version1 state snapshot. Pre-Task07 version1 records missing this optional field migrate to `None`, which means unknown identity. Event codec likewise defaults only the newly optional part/inventory fields for old version1 events; unknown fields, malformed indices (including booleans), oversized text and PCM remain rejected. Existing confirmed historical evidence is preserved; loading a snapshot never manufactures a new drain certificate.

`PlaybackCursor.content_index` and the optional `AssistantPlaybackEvidence.part` used by cancellation control preserve the playing part through facade/frontend/low-level truncate. The provider truncate offset is relative to that part and bounded by its received duration, not the last part received. Legacy cursors may infer a single known part; ambiguous multipart truncation without an index is rejected. This does not add partial-word alignment to canonical history.

Canonical integration gate (2026-09-12): **178 passed in 10.37 s**, warnings as errors. The new manifest suite injects explicit proof values to exercise identity, strict codec, migration, multipart/late transcript, contradiction, cancellation and projection; it does not claim native drain accuracy. Real wrapper/device integration is owned by the Task07 audio lead. Exact command and evidence limits are in `tasks/jarvis_voice_architectures_handoff/docs/evidence07-canonical.md`.

## Task08: available outcomes and speech source

Core now persists ordinary public backend results through `BrainOutcomeService`
and the existing SQLite state repository. These records are **available
outcomes**, separate from generated transcripts, queued intent and confirmed
heard history. They survive a muted surface, stale candidate and Core restart
without an assistant turn or synthetic Job. An outcome does not authorize work
or promise presentation. Explicit selection creates a fresh candidate while
preserving the original outcome source.

`SpeechSource` names the persisted Core turn and correlation, with a durable
per-conversation arrival epoch. It is distinct from a canonical voice turn,
provider item and the mutable Brain state revision. An uncertain turn owns its
source but does not advance current intent until Core confirms it in arrival
order. Old asynchronous results retain their origin. Dependency invalidation
uses the exact work name plus owner correlation; unknown generation is deferred.

The existing Core loopback protocol exposes bounded outcome list/get, explicit
selection and a versioned current-source projection for scheduler recovery.
Neither frontend reconnect nor stream-gap recovery replays candidates. The
projection becomes explicitly incomplete on invalidation-capacity overflow.
Full schema, dedup/versioning, authentication, compatibility limits and journal
contract: [Task08 Core outcomes](../tasks/jarvis_voice_architectures_handoff/docs/08-core-outcomes.md).
