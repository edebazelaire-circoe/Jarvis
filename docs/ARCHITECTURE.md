# Jarvis V1 architecture

## Design intent

The implementation follows the handoff's central rule: Jarvis owns an independent core. `fullstack-agent` is reference-only; Barehands and ai-visualizer are optional local processes at the boundary.

The design is ports/adapters rather than a monolithic agent process. Provider dictionaries, OpenAI transport concerns, sounddevice types and browser implementation details stop at adapters.

## Runtime flow

1. `PTTKeyListener` emits press/release callbacks.
2. `VoiceRuntime` owns only microphone capture lifecycle and delegates state/agent behavior to `JarvisOrchestrator`.
3. `SoundDeviceRecorder` produces one in-memory `AudioClip` on release.
4. `TranscriptionBackend` returns a typed `TranscriptionResult`.
5. `JarvisOrchestrator` transitions to thinking and sends a typed `UserTurn` to `AgentBackend`.
6. The agent can either return text or request one/more of the three registered tools.
7. `ToolRegistry` validates the tool name and arguments and translates the call to a server-owned `ActionRequest` with a locked policy classification.
8. `ActionBroker` either executes read/ephemeral actions or pauses persistent writes for exact confirmation.
9. Tool outputs are returned to the agent through the provider adapter's continuation mechanism.
10. Final text is sent to `TTSBackend`; a new PTT press cancels current speech and returns to listening.
11. Every state transition is published to the file bus; optional UI publishers fail soft.

## State machine

Canonical states:

- `idle`
- `listening`
- `transcribing`
- `thinking`
- `awaiting_confirmation`
- `speaking`
- `error`

Illegal transitions raise a typed state error rather than being silently accepted. Error announcements can be interrupted by PTT, then the next turn can begin cleanly.

ai-visualizer has a narrower vocabulary, so its adapter maps:

- `idle` -> `idle`
- `listening` / `transcribing` -> `listening`
- `thinking` / `awaiting_confirmation` / `error` -> `thinking`
- `speaking` -> `speaking`

An `.voice_alert` file is additionally published while Jarvis is in `error`.

## Core contracts

Key ports live under `jarvis/ports/`:

- `AgentBackend`
- `TranscriptionBackend`
- `TTSBackend`
- `MemoryBackend`
- `BoardClient`
- `StatePublisher`
- action execution contract

Typed domain objects live under `jarvis/domain/`. The release verifier parses the core AST and fails if OpenAI/HTTP/audio/keyboard provider packages leak into `jarvis/core`.

Domain state models with their own contract page: canonical voice conversation state ([state-model.md](state-model.md)), Core work state (*Core work state* below) and the constellation scene projection ([scene-model.md](scene-model.md): objects, relations, layers, authority matrix, revision/patch semantics).

## V1 tool surface

The registry intentionally exposes only:

- `memory_search(query, limit?)`
- `memory_append(title, body)`
- `board_present(title, body, x?, y?)`

There is no generic shell, browser, HTTP fetch, send-message, delete-file or arbitrary filesystem tool.

## ActionBroker

The model cannot choose whether an action is safe. Tool name -> action kind -> risk/confirmation policy is owned by Jarvis code.

- `memory_search`: read-only, no confirmation.
- `board_present`: ephemeral UI mutation, no confirmation.
- `memory_append`: persistent write, confirmation required.

Only one confirmation can be pending. It has an action id and expiry. Exact normalized `oui`/`yes` approves; exact `non`/`no` denies. Other text remains ambiguous and cannot execute the write.

## Memory

Markdown is the source of truth in `data/memory/` (or configured memory directory). Search metadata is a derived SQLite index at `<memory>/.jarvis/index.sqlite3`.

- Appends use atomic file replacement.
- Search uses SQLite FTS5 when available and falls back to a plain indexed table.
- Deleting/corrupting the derived index does not lose canonical memory; it can be rebuilt from Markdown. Startup always resynchronizes derived search state from the Markdown files, including external edits made while Jarvis was stopped.
- Resolved-path containment and repeated URL decoding protect against traversal and encoded traversal.
- Symlinks resolving outside the memory root are rejected.

## OpenAI adapters

The implementation uses direct HTTP rather than importing an OpenAI SDK into the core:

- STT: `/audio/transcriptions`
- agent: `/responses`
- TTS: `/audio/speech`

Models are configuration, not business constants. The example configuration reflects models verified during implementation, but every model id can be overridden without changing core code.

The Responses adapter exposes only the V1 function schemas and keeps continuation payload mechanics private to the adapter. `store: false` is sent for agent responses.

## TTS interruption

`CancellationToken` is provider-neutral. The sounddevice playback adapter writes WAV chunks and checks cancellation between chunks.

A critical concurrency rule is enforced in `VoiceRuntime`: its lock protects microphone capture ownership only. The lock is released before STT/agent/TTS, allowing a new PTT press during speech to reach the orchestrator and cancel playback rather than blocking behind the previous turn.

## UI seams

### ai-visualizer

Read-only consumer of files under the runtime signal directory. It receives no board session token from the launcher.

### Barehands

Optional local process. Jarvis sends board commands via loopback HTTP. The upstream snapshot is patched at bootstrap to require:

- `X-Jarvis-Token` on `/cmd`;
- a non-empty random per-launch token;
- loopback Origin when Origin is present;
- security headers/CSP;
- local verified Three.js, MediaPipe JS/WASM and hand-landmarker model paths.

Gesture/browser code remains upstream-owned; Jarvis does not copy it into the core.

## Process topology

`scripts/dev_start.py` is the single launcher:

- verifies third-party integrity before UI launch;
- generates one random board token;
- passes the board token only to Jarvis and Barehands processes;
- strips the OpenAI API key from Barehands, ai-visualizer and bootstrap-verifier environments;
- generates runtime configs for external UI components;
- starts optional Barehands and visualizer subprocesses;
- starts Jarvis voice process;
- cleans up child process groups on exit.

UI startup failures are warnings; the Jarvis voice process remains independently runnable via `--no-board --no-visualizer`.

---

# Realtime + async brain architecture (v0.2 path)

The sections above describe the V1 push-to-talk loop. The repository also runs a
v0.2 realtime stack, delivered by the handoff under
`docs/handoff-realtime-brain/`. It does not replace V1; it is a separate set of
processes with its own lifecycle.

## Processes

| Process | Command | Owns |
| --- | --- | --- |
| Core | `python -m jarvis core` | conversations, jobs, tools, confirmation policy, public brain state; loopback HTTP + `/v1/events` WebSocket |
| Voice | `python -m jarvis voice` | wake word, microphone/speakers, the Realtime session, speech scheduling |
| Control Center | `python -m jarvis control-center` | browser panel, trace/error console, settings, the local Claude/Codex agent behind `POST /api/agent/ask` |

Core and Voice are separate processes. Muting or crashing Voice does not stop
Core work; that separation is the point of the architecture.

## Two voice architectures

`JARVIS_VOICE_ARCH` selects the code path, and the Control Center's
**Architecture** field (`voice_arch` in `runtime/control-center-settings.json`)
takes precedence over it; `jarvis/v2_config.py` owns the parsing and the computed
default, so removing both returns to `legacy` mechanically.

- `legacy` (default) - one wake press, one turn, back to background when the
  answer completes. The surface receives the full Core tool catalogue from
  `jarvis/runtime/realtime_tools.py` and reaches the strong agent itself through
  its `claude_task` tool and `ClaudeGateway`.
- `continuous_brain` (opt-in) - one ACTIVE session spans several turns. The
  surface receives an **empty** tool catalogue, `ClaudeGateway` is not even
  constructed, and every completed user turn is submitted to Core.

The default is not hard-coded. `default_voice_arch()` returns `legacy` while
`CONTINUOUS_BRAIN_DEFAULT_BLOCKERS` is non-empty, and `parse_voice_arch()` is its
only consumer, so unsetting the environment variable returns to `legacy`
mechanically.

Continuous mode fails loudly instead of degrading: it refuses manual turn mode,
and it refuses any voice stack that does not implement the semantic output
controls (Gemini Live today).

## Surface and brain

The boundary is: **the surface has the reflexes, the brain has the truth.**

In continuous mode the Realtime model may autonomously produce only a short
acknowledgement, a hearing repair, or a clarification about what it heard. It is
forbidden from announcing a result, a progress, a success or a failure, and it
holds no tools at all - the prompt says so and the empty catalogue enforces it.
Duplicated writes are what the empty catalogue prevents: the complete turn is
already on its way to the brain, so a surface-side `drive_delete` would execute
twice or execute while the brain is deciding it should not.

The brain is a Core service, `BrainOrchestrator` in `jarvis/core/brain_service.py`.
It owns turns, public working state, work identifiers and revisions. The
provider behind it is a `BrainBackend` port; the shipped adapter,
`jarvis/adapters/control_center_brain.py`, calls the agent-agnostic
`POST /api/agent/ask` route of the Control Center and is injected at the Core
composition root. Core itself defaults to a null backend and imports no adapter.

Each brain turn carries an optional `context` field on that route: the surface's
addressing verdict (`addressed` / `uncertain`), the public working state, as
produced by `BrainWorkingState.to_rehydration_payload()`, and — when Core could
read it — the bounded current-work snapshot `work` (see "Brain work context and
event policy" below) — nothing else, and no
reasoning. The Control Center renders it as a short French preamble in front of
the request; an `uncertain` turn is told it may conclude the words were not for
it and answer `[pas-pour-moi]`, which the backend turns into silence instead of
speech. Callers that send no `context` (the legacy `ClaudeGateway`, the browser
panel) reach the agent with their text unchanged. A second optional field,
`conversation` (`{conversation_id, correlation_id, work_id}` of the turn), is never
rendered into the prompt: the Control Center only uses it to attribute the
sub-agents of that turn to their conversation (Conversation Events, "Sub-agent
mapping rule").

```text
microphone ──► Realtime surface (reflexes only, no tools)
                    │  completed user turn
                    ▼
        POST /v1/conversations/{id}/brain-turns
                    ▼
              Core BrainOrchestrator ──► BrainBackend ──► Control Center agent
                    │                                       (Claude or Codex)
                    │  brain.* envelopes on /v1/events
                    ▼
              Voice SpeechScheduler ──► session.speak() ──► speakers
```

## Contracts

Provider-neutral ports live in `jarvis/ports/v2.py`: `BrainBackend` (and its
optional capability `ContextAwareBrainBackend`, probed by
`supports_brain_context`), `RealtimeOutputControl` (`speak` / `cancel_output` / `truncate`, probed as an
optional capability rather than widening `RealtimeSession`), `WorkCanceller`,
`JobProgressSink`, `DiagnosticSink`; the normalized work-state ports
(`WorkObservationSink`, `WorkStateReader`) live in `jarvis/ports/work_state.py`
(see "Core work state" below), and the speaker-verification port
`SpeakerVerifier` lives in `jarvis/ports/speaker.py` (see "Speaker verification:
shadow, then Solo Owner authority" below). Brain events reuse the existing
`ProtocolEnvelope` and `CoreEventBus` rather than a second event framework:
`brain.turn.accepted`, `brain.state.updated`, `brain.speech.requested`,
`brain.work.started`, `brain.work.progress`, `brain.work.completed`,
`brain.work.failed`, `brain.intent.revised`.

Authoritative turns are deduplicated on `correlation_id`; the provider item id is
an optional secondary key. The deduplication index is in memory, so a Core
restart leaves a documented replay window.

`/v1/events` is live-only. There is no replay: a consumer that missed events
expires stale speech and rehydrates from Core state.

The canonical conversation record is a separate, versioned contract:
[Conversation Events](conversation-events.md) (`jarvis/domain/conversation_events.py`).
It maps user transcript admission, the `brain.*` envelopes above, the
`voice.speech.*` / `voice.reflex.*` delivery telemetry, `agent.subagent.*` and
tool calls to one strict, redacted envelope with deterministic `event_id`,
instant/span timing and a `trace_ref` join to `runtime/trace.jsonl`. It never
ingests `agent.event`. Durable storage: the `conversation_events` table of the
Core state DB (schema v2), behind the `ConversationEventStore` port.

Producers: Core records user input (`core.voice_admission`, once the user turn is
durable, before any backend work) and Brain events (`core.brain_service`,
`core.brain_outcomes`) in process through `ConversationEventEmitter`
(`jarvis/core/conversation_event_emitter.py`): synchronous enqueue into a bounded
queue drained by one background task (50 ms linger, batches ≤ 32), newest event dropped on overflow, storage
failures dropped and diagnosed, never an exception or an await on the turn and
speech path. Other processes post to Core through one bounded
`ConversationEventForwarder` each (`jarvis/runtime/conversation_event_forwarder.py`,
send loop shared with `WorkIngressForwarder` in `jarvis/runtime/core_forwarder.py`):
the voice runtime records Mouth speech and reflexes (`SpeechScheduler`), tool spans
and rejected turns (`RealtimeConversationBridge`); the Control Center records
sub-agent spans (`AgentTaskTracker`, attribution in `jarvis/runtime/subagent_conversation.py`), attributed to a conversation only from the
explicit `conversation` block Core sends with `/api/agent/ask` and confirmed by the
turn `result`. Producers call a synchronous `record()` (no await, no I/O, never
raises) and write the returned id into their existing journal line
(`conversation_event_id`); the forwarder lingers 0.5 s, posts batches ≤ 32, keeps
the batch and backs off 1 s → 30 s when Core is unreachable (re-reading the token
after a 401), drops a refused batch, drops the newest event past 1024 queued, and
counts every loss.

```text
Voice / Control Center                          Core process
----------------------                          ------------
SpeechScheduler / Bridge / AgentTaskTracker
  -> ConversationEventForwarder.record (bounded deque, own task, batches <= 32)
  -> LocalCoreClient.append_conversation_events ---> POST /v1/conversation-events
                                                  -> ConversationEventEmitter.append_now -> conversation_events table
                                                BrainOrchestrator / VoiceTurnAdmissionService
                                                  -> ConversationEventEmitter.record (bounded queue) -> same table
```

`POST /v1/conversation-events` takes `{"schema_version": 1, "events": [...]}`.
Invalid batch, codec error or Core-owned event (`user.*`, `brain.*`, producer
`core.*`) -> 400 `invalid_request`, nothing appended, message names the index and
rule, never a value. 200 -> `{"schema_version": 1, "results": [{"event_id",
"sequence", "status"}]}` (`appended` / `duplicate` / `conflict`). Storage failure
(or Core stopping) -> 503 `conversation_events_unavailable`, retry the same batch.
Body limit: the Core app's `client_max_size` is 6 MiB for every `/v1` route (the
largest contract-valid batch is 4.24 MiB on the wire; aiohttp's 1 MiB default
would answer 413, which `LocalCoreClient` raises as `CoreProtocolError(413)`).
On start, Core re-records recent durable user turns whose event a crash lost
(bounded backfill); Brain events lost in the ~60 ms commit window are not rebuilt. Details and the
producer ownership table: [Conversation Events](conversation-events.md),
"Producers and ingestion".

Reading the log (Slice 04). Core serves the store over authenticated loopback
routes; the browser only reads the Control Center, which proxies them through
`LocalCoreClient` (`ConversationEventView`, own session, token re-read after a
401). Pages carry each event exactly as stored plus its store `sequence` and
`recorded_at`; the cursor is the sequence (`next_cursor`, `has_more`,
`skipped_rows`), so reload and live polling yield the same event set.

| Core route | Control Center route | Purpose |
|---|---|---|
| `GET /v1/conversation-events/conversations` | `GET /api/conversations` | conversations by recent activity (`before_sequence`, `limit` ≤ 100) |
| `GET /v1/conversation-events/sessions` | `GET /api/conversations/sessions` | sessions of a conversation (`conversation_id`, `after_sequence`, `limit` ≤ 100) |
| `GET /v1/conversation-events` | `GET /api/conversations/events` | events after a cursor (`conversation_id`, `after_sequence`, `limit` ≤ 500, `visibility`, long-poll `wait_ms` ≤ 25 000) |
| `GET /v1/conversation-events/lookup` | `GET /api/conversations/lookup` | events by `session_id`/`turn_id`/`correlation_id`/`task_id`/`work_id`/`speech_id`/`outcome_id`/`span_id` |
| `GET /v1/conversation-events/events/{event_id}` | `GET /api/conversations/events/{event_id}` | one stored event (404 `conversation_event_not_found`) |
| — | `GET /api/conversations/events/{event_id}/trace` | redacted journal evidence of a stored event (bounded newest-first scan of `runtime/trace.jsonl`; user events 404 `trace_not_applicable`; sub-agent/agent-task link to `/api/agent/tasks/{task_id}/trace`) |
| `GET /v1/conversation-events/transcript` | `GET /api/conversations/transcript` | readable transcript, streamed `text/plain` (`conversation_id`, `mode` = `plain`\|`detailed`, `utc_offset_minutes`; 413 `transcript_too_large` above 50 000 events or 16 MiB of text; 429 `projection_busy`) |
| `GET /v1/conversation-events/export` | `GET /api/conversations/export` | JSONL export streamed page by page (header, stored events, trailer; frozen at the conversation's last sequence) |
| `GET /v1/conversation-events/search` | `GET /api/conversations/search` | bounded newest-first search over public content and safe metadata (`q`, `conversation_id`, `before_sequence`, `limit` ≤ 50, `visibility`) |

Errors: 400 `invalid_request` (never echoes a value), 401 `unauthorized` (Core),
503 `conversation_events_unavailable` (store failing or Core stopping), and on
the Control Center 503 `core_unreachable`, 502 `core_unauthorized` /
`core_refused` / `invalid_core_response`, 503 `control_center_stopping` /
`trace_busy` / `trace_drill_down_failed`, 403 `forbidden_origin` (every method
under `/api/conversations` requires an exact loopback `Origin` when present and
`Host`, and no `Sec-Fetch-Site: cross-site`). Long-poll: woken per conversation,
ended when the client disconnects; the Control Center lets at most 8 wait at
Core (extras are sent as plain polls) on a Core session separate from list and
detail reads. Loss visibility: `GET /v1/health` → `conversation_events`
(emitter counters, unreadable rows, query failures); `GET /api/status` →
`conversation_events` (Control Center forwarder counters). Contract, cursor and
long-poll semantics, drill-down bounds and the redaction allowlist:
[Conversation Events](conversation-events.md), "Query and live API".

Timeline view (Slice 05). The Control Center dock button **CNV** opens a
full-screen `role="dialog"` over the page: four lanes (Utilisateur, Jarvis ·
voix, Brain, Sous-agents) on one downward time axis, live. Its logic is
`jarvis/runtime/control_center_timeline.js`, inserted at
`/*__CONTROL_CENTER_TIMELINE_JS__*/` like the other page scripts: the pure part
(`JarvisTimelineCore`: a port of `reconstruct_conversation` tested for parity,
lane rule, duplicate-message collapse, folded-silence axis, need-weighted lane
widths, column packing measured at the final column width, viewport windowing, hydration + long-poll state machine, status /
detail / trace models) runs unchanged under node tests; the browser block holds
DOM, focus and fetch. It reads only `GET /api/conversations`,
`GET /api/conversations/sessions`, `GET /api/conversations/events` (one request
in flight per tab: pages then `wait_ms=25000` long-poll from the last
`next_cursor`, backoff 1 → 30 s on retryable codes),
`GET /api/conversations/events/{event_id}` and
`GET /api/conversations/events/{event_id}/trace`; never `/api/trace`. UX, states
and troubleshooting: [Conversation Events](conversation-events.md), "Timeline UI".

Projections (Slice 06). The readable transcript, the JSONL export and search
are derived from the stored events only, never a second record. One pure
renderer, `jarvis/domain/conversation_transcript.py` (on top of
`reconstruct_conversation`, with the timeline's duplicate-publication collapse
rule, parity-tested against the JS), serves Core's transcript route, the
Control Center (which relays Core's text) and offline readers of an export
(`jarvis/domain/conversation_event_export.py`: `read_export`,
`transcript_from_export`, `reconstruct_export`, byte-identical to the live
rendering). The export streams store pages under a frozen extent
(`ConversationEventStore.conversation_extent`, `until_sequence`) and ends with a
trailer whose absence marks an incomplete file. Search
(`jarvis/domain/conversation_event_search.py`, scan in
`SQLiteConversationEventStore.search_events`) matches public content and
allowlisted metadata only, accent- and case-insensitively: 250-row chunks whose
searchable fields SQLite extracts, matched on the event loop in 2 ms slices that
yield (≤ 50 000 rows per request; no FTS5, no schema change). Core's hot path
comes first: one search and two transcript/export builds at a time (429
`search_busy` / `projection_busy`), cancelled when the client leaves, 50-event
projection pages; with a search scanning 80 000 rows, append p95 stays at 4 ms. The CNV view adds *Rechercher*,
*Transcription* and *Exporter JSONL* panels in its drawer; a search result jumps
to its entry. `tests/integration/test_conversation_event_rollout_gate.py` runs
the whole path with real stacks, a Core hard crash and a restart. Details,
sizing and privacy boundaries: [Conversation Events](conversation-events.md),
"Readable transcript", "JSONL export", "Search", "Operations".

## Speech, interruption and work

`SpeechScheduler` (`jarvis/runtime/speech_scheduler.py`) consumes `/v1/events`,
filters by conversation, orders by priority then FIFO, expires TTL, honours
`supersedes_key`, resubscribes after a silent close without replaying, and stays
silent while Voice is in background. Its lifetime is the lifetime of the ACTIVE
voice transport, not of the work.

Barge-in has a fixed order in `RealtimeConversationBridge._barge_in()`: local
stop first (one call into PortAudio), then freeze the playback cursor, then
`cancel_output`, then `truncate`. The user stops hearing Jarvis before any
network round trip. Nothing is cancelled: interruption is not cancellation. The
next authoritative turn simply carries `interrupted_speech_id`, and the brain
decides. Work is removed only by an explicit, named brain decision published as
`brain.intent.revised`.

A truncated sentence is persisted with its full text plus `delivery=partial` and
`played_ms`, and is excluded from the derived public facts, so the brain knows it
spoke without claiming the user heard it. A speech interrupted before any audio
reached the device is not persisted at all.

### Barge-in authority: acoustic vs owner (Solo Owner, task 05)

What *triggers* `_barge_in()` is a policy, `BargeInAuthority`
(`jarvis/runtime/realtime_audio.py`), chosen once per voice activation by
`PersistentVoiceRuntime._barge_in_policy()`. The stop mechanism above (local stop,
cursor, blacklist of received outputs, `cancel_output` + `truncate` with degraded
handling) is shared and unchanged.

| | `ACOUSTIC` (open room, default, rollback) | `OWNER` (Solo Owner) |
| --- | --- | --- |
| Local near-end latch (`near_end` signal) | duck to `barge_in_duck_gain` (30 %), wait `barge_in_confirm_s` (0.8 s) for the provider | **no gain change, no cut**; since task 06 it **no longer opens the echo guard** either (the provider keeps receiving silence while JARVIS is audible, see "Owner replay buffer"); the 0.8 s timer releases the latch (`release_near_end`) only once the verifier's candidate has closed |
| Provider `speech_started` while JARVIS is audible | cuts (if the echo guard was open) | **never cuts**. Correlation only, logged `voice.barge_in.provider_advisory` (`relation = awaiting_owner`); with the owner-held guard the provider can only hear audio sent before JARVIS became audible |
| Owner confirmed (`OwnerStateSnapshot`) | ignored (not subscribed) | **cuts**: local `stop_output()` immediately, then provider cancel/truncate as best-effort follow-up, then the buffered sentence start is replayed to the provider (task 06) |
| JARVIS silent | every voice reaches the provider | only the owner's flow reaches the provider (task 07, "Owner input gate") |

Owner trigger. `_consume()` subscribes to the `OwnerStateSource` (the
`SpeakerVerificationWorker` of the duplex capture) for its own lifetime; the
listener only does `loop.call_soon_threadsafe(_post, "owner_state", snapshot)`
(worker thread → main task, like `near_end`, never behind queued audio). The
subscription starts from the source's current snapshot: a snapshot whose
`sequence` is not newer than the last one accepted, or whose `session` is older,
is dropped. The cut edge is `state == owner_confirmed` **and** `far_end` (JARVIS
was audible in the confirming window) **and** an output that is playing, or
received and still to play, and has not already been cut
(`_interruptible_output()`: queued blocks below the cut mark or of blacklisted
outputs do not count). A confirmation while JARVIS is silent stops nothing; it
opens the owner flow (task 07). Provider `speech_started` order is
irrelevant: before the confirmation it is advisory; after it, it is correlated
(`relation = after_owner_stop`, `lag_ms`) and never cuts a second time; if it
never comes, the local stop has already happened. Interruption still never
cancels Core work: the next brain turn carries `interrupted_speech_id`.

Effective authority. `OWNER` is chosen only when `conversation_mode = solo_owner`
(verification `enforce`, coherent by construction), the voice architecture is
`continuous_brain`, and the duplex capture carries a verifier worker whose
`availability` is `ready` and an owner replay ring (`assess_authorization` →
`ready`). Since task 07 there is **no open-room fallback** any more: a Solo Owner
that cannot apply is refused at activation, and a verifier lost during a session
closes the input and ends the session — see "Owner input gate", *Refusal
policy*.

Diagnostics (scalars only, capture stream clock — the same clock as the owner
state, reset per session):

| Kind | When | Data |
| --- | --- | --- |
| `voice.barge_in.authority` | accepted Solo Owner activation (`authority = owner`, `status = ready`); verifier lost mid-session (`input = closed`, `code = owner_verifier_unavailable` / `owner_listener_unavailable`, warning) | `configured`, `authority`, `status`, `code`, `availability`, `input`, `conversation_mode`, `speaker_verification`, `arch` |
| `voice.barge_in.owner_confirmed` | owner cut, right after the local stop, before the provider calls | `session`, `sequence`, `candidate_onset_ms`, `owner_onset_ms`, `confirmed_ms`, `stop_stream_ms`, `confirm_ms` (onset → confirmation), `confirm_to_stop_ms` (verifier queue + marshalling + stop), `onset_to_stop_ms`, `stop_latency_ms` (the stop call, wall clock), `owner_score`, `evidence_ms`, `speech_id`, `output_id`, `played_ms`, `provider_speech_started`, `provider_lead_ms` |
| `voice.barge_in.provider_advisory` | provider `speech_started` in Solo Owner while JARVIS is audible, or ≤ 5 s after an owner cut | `relation` (`awaiting_owner` \| `after_owner_stop`), `owner_state`, `guard_open`, `lag_ms`, `replay_ms` (length of the last owner replay, `after_owner_stop` only) |
| `voice.owner.replay` | the capture replayed an owner prefix (every owner cut, or any opening that replayed or lost audio) | `session`, `sequence`, `candidate_onset_ms`, `owner_onset_ms`, `confirmed_ms`, `stop_stream_ms`, `barge_in`, `requested_from_ms`, `replay_from_ms`, `replay_until_ms`, `replay_ms`, `margin_ms`, `already_sent_ms`, `clamped_ms`, `buffer_ms`, `confirm_to_replay_ms`; warning + `code = owner_replay_clamped` when `clamped_ms > 0` |
| `voice.owner.replay` (warning) | the input queue lost a block carrying a replay: that sentence start never reached the provider | `code = owner_replay_dropped`, `dropped_replays` (running count) |

The existing `voice.barge_in` event is still emitted for every cut; an owner cut
adds `trigger = owner`. `voice.barge_in_pending` / `voice.barge_in_rejected` carry
`authority = owner` in Solo Owner (no duck happened).

Known limit: the owner state publishes changes only. If JARVIS starts speaking
while the owner is already confirmed and keeps talking, no new edge arrives; the
speech scheduler does not start over a speaking user (provider VAD, and since
task 07 the local hold on an open candidate or a confirmed owner,
`note_user_speech`), and the next verdict change would cut.

### Owner replay buffer (Solo Owner, task 06)

Owner verification takes 0.5–2 s (D07); the 150/400 ms acoustic pre-roll cannot
cover that. `CaptureProcessor` therefore holds a separate **owner-verification
ring buffer** when it is built with `owner_buffer_ms` (Voice does so only when
`conversation_mode = solo_owner`; the open room has no ring at all):

- **Content and bound.** The last `owner_buffer_ms / 10` 10 ms frames as they
  leave `_cancel_echo()` (the bytes that would have been sent — echo-cancelled
  only while a canceller runs, see "What 'as it leaves `_cancel_echo()`' means"
  below), so the canceller's render/capture pairing and the reference feed order
  are untouched.
  Memory = `owner_buffer_ms × capture_rate × 2 / 1000` bytes (2500 ms: 80 KB at
  16 kHz, 120 KB at 24 kHz, 240 KB at 48 kHz). RAM only: never persisted, never
  logged, never passed to diagnostics. Setting `owner_buffer_ms` (500–5000,
  default 2500) is read once at Voice start
  (`parse_conversation_authorization(...).owner_buffer_ms`).
- **Index.** Frame `i` starts at `i × 10` ms of the capture stream clock
  (`CaptureProcessor.stream_ms`, reset per session) — the clock of
  `OwnerStateSnapshot`, so `owner_onset_ms` is directly a ring index. The capture
  rate is fixed per processor (a different stack rate builds a new capture, hence
  a new ring).
- **Sent / not sent.** One watermark, `_sent_until`: the index after the last real
  frame handed to the provider (live, acoustic pre-roll or replay). Anything below
  it was sent or is forfeited. A replay only sends frames at or after the
  watermark, so it can never duplicate a frame nor put audio behind audio the
  provider already received; an owner replay also marks the whole acoustic
  pre-roll as sent, so a later acoustic opening cannot leak the non-owner prefix.
- **Reset.** `reset()` (session activation and return to background) clears the
  ring, the watermark, the owner flow and any pending command, and hands the
  guard back to the acoustic rule (the next Solo Owner bridge takes it again
  before its first captured block).

**Owner-held guard.** With `OWNER` authority and a ring, the bridge calls
`audio.set_owner_gate(True)` before the microphone opens and again when it
subscribes to the owner state, and keeps it until the capture is reset (a
verifier failure closes the flow, it never hands the guard back — task 07). The
provider then receives digital silence unless the owner flow is open, **whether
JARVIS is audible or silent** (task 07): neither the near-end latch nor JARVIS's
silence opens anything. The latch still emits `near_end` (candidate bookkeeping).

**Replay.** `_on_owner_state()` on `owner_confirmed`: if JARVIS is audible and
interruptible, `_barge_in(owner=…)` runs first (local stop, then cancel + truncate
sent), then `audio.open_owner_flow(owner_onset_ms, candidate_onset_ms=…)`. The
request is stored under the capture lock and applied by the capture thread at
the start of the next block, before that block's frames: the unsent prefix from
`owner_onset_ms − margin` (margin `OWNER_REPLAY_MARGIN_MS` = 150 ms, only when the
owner onset is the candidate onset — never when a non-owner verdict preceded in
the same candidate; clamped to the stream start, to the watermark and to the ring)
is prepended to the block output, then frames flow live until the owner state
turns `rejected` or `idle` (`close_owner_flow()`), which closes the guard again.
Exactly once: an opening while the flow is open is a no-op; commands coalesce to
the latest one per block, except that a close arriving while an opening is still
pending keeps the opening's replay and closes right after it (a short reply
confirmed when its candidate closes: `owner_confirmed` then `idle`, task 07). The
replay rides the normal
capture path (`_deliver_capture` → input queue → `pump_input` →
`send_audio`), never playout. The capture signals `owner_replay`; the bridge
traces `voice.owner.replay` from `take_owner_replays()` (≤ 4 reports kept).
The 64-slot input queue drops its oldest block when the provider send path
stalls — except a block carrying a replay: the capture has already marked that
prefix sent (`_sent_until`), so nothing would ever offer it again. While such a
block is at the head the newest live block is dropped instead; a replay lost all
the same (two replays stuck behind one stalled send) is counted
(`SoundDeviceRealtimeAudio.dropped_replays`) and traced, never reported as a
successful replay.

**Provider turn detection.** The provider hears: silence (gated frames), then the
replay burst (up to `owner_buffer_ms`, faster than real time, one
`input_audio_buffer.append`), then live audio. No pacing: OpenAI server/semantic
VAD segments the input buffer on its audio timeline, not on arrival time, so the
burst is one contiguous utterance preceded by silence; the append size (≤ 240 KB
at 48 kHz) is far below the event limit. Provider `speech_started` then marks the
replayed segment's start: it is a segmentation/correlation signal after the local
authorization (`relation = after_owner_stop`, `lag_ms`, `replay_ms`). Gemini Live
is refused in `continuous_brain`, so no duplex/replay path exists there.

**Acoustic timer in owner-held mode.** The provider no longer hears near-end speech
during JARVIS speech, so its silence is no longer evidence of echo. Releasing the
latch after 0.8 s would raise the detector's coupling to the level of whoever is
talking and make it deaf to the owner. `_on_barge_timeout()` therefore re-arms
while the verifier's candidate is open (owner state ≠ `idle`) and releases only
once it has closed, on a window that contains echo only.

Limits: a very late confirmation (> `owner_buffer_ms` after the onset) loses the
oldest part (`clamped_ms`, warning). The owner onset after a non-owner verdict is
an estimate (`confirmed_ms − evidence_ms`), so a mixed window may start slightly
inside the other voice or slightly after the owner's first syllable.

### Owner input gate (Solo Owner, task 07)

Goal: "only my voice constitutes a user turn". Other speakers can talk
indefinitely, JARVIS speaking or silent, without controlling session state.

**Gate point — the capture guard.** The single earliest safe point is
`CaptureProcessor.process()` with the owner-held guard: `should_open =
self._owner_flow`, whatever `far_recent` says. Earlier is impossible (the verifier
needs post-`_cancel_echo()` frames and ~1.5 s of evidence; the ring keeps the sentence start
meanwhile); any later point (provider `speech_started`, transcript) would let the
provider hear, segment, transcribe and possibly answer another voice. Gated frames
become digital silence at the same cadence, so the provider's VAD sees silence,
never a partial non-owner turn. Owner speech is replayed from its onset through
the Task 06 ring (single watermark: no duplicate). Open room (`ACOUSTIC`, no ring)
is byte-for-byte unchanged.

**Defense in depth — provider events.** With the guard owner-held
(`_input_gated()`), a provider `speech_started` is admitted only while the owner
flow is open or within `OWNER_SEGMENT_GRACE_S` (3 s) of its closing (the provider
segments the replay burst late; a short reply is replayed and closed at once); the
decision is kept per `item_id` for the transcript. A non-admitted segment is
dropped before anything else — no user-speech notification, no latency segment, no
barge-in — and its transcript is dropped **before** the `voice.transcript` trace
and before addressing: its text is never logged, classified or submitted. Identity
is never inferred from text. The transcript filters (`turn_filters`: noise, echo)
stay unchanged behind the identity gate.

**Addressing unchanged for the owner.** Admitted owner speech goes through the
existing `ConservativeAddressingClassifier` and the Decision 44 rule: `addressed` →
brain turn + `on_addressed` (useful activity) + reflex request; `uncertain` →
brain turn marked uncertain, `on_ambient` only (no useful activity, no reflex).

**Useful activity.** `UsefulActivityTracker` is only reset by addressed owner
transcripts, JARVIS's own speech and brain activity, as before. Non-owner speech
produces no provider event, hence no reset, no acknowledgement, no reflex, no
brain turn and no work; owner-state handling itself never resets activity.

**Speech scheduler.** `on_user_speech` is the OR of the provider VAD (as before)
and a local hold (`_hold_for_candidate`): an acoustic candidate without a verdict
yet (it may be the owner, not recognized yet) and a confirmed owner hold the
scheduler; a `rejected` verdict or the end of the candidate releases it. So
acknowledgements never start over a possibly-owner voice (D14), while another
voice delays JARVIS at most until its verdict (≈ the evidence window, ~1.6–2 s per
candidate) — never indefinitely — and the scheduler's own 8 s cap still applies.
Accepted side effect: another voice may cancel a pending acknowledgement (skip
reason `user_speaking`); it never creates one. `_user_speaking` (read by the
barge-in) stays provider-only.

**Short utterances — end-of-candidate verdict.** Replies shorter than the 1.5 s
evidence window (« oui, vas-y », « non merci », « stop ») were never confirmed.
Optional port capability `CandidateAwareVerifier.finish_candidate(judge)`
(`jarvis/ports/speaker.py`), called by `ShadowOwnerTelemetry` on the worker thread
when the state machine closes a candidate (600 ms without near-end):

- `judge=True` (no verdict in this candidate): `EmbeddingSpeakerVerifier` scores
  the candidate's voiced speech once if it reaches `owner_short_evidence_ms`
  (default 600; 300 up to evidence − 1; 0 disables) — this per-candidate buffer is
  cleared by `finish_candidate`/`reset`, not by the 600 ms gap — against the
  stricter threshold `owner_threshold + owner_short_margin` (default 0.6 + 0.1 =
  0.7; margin 0–0.3). Owner → the telemetry publishes `owner_confirmed` for the
  closed candidate (`owner_onset_ms` = candidate onset, `confirmed_ms` = closing
  window) then `idle`; the bridge opens then closes the flow and the capture
  replays the whole candidate once (and cuts JARVIS first if he is audible: a
  short « stop » interrupts). Otherwise the candidate is dropped
  (`reason = short_not_owner`, or `insufficient_audio` below the minimum).
- Trade-off: the turn starts ≈ 0.6–0.8 s after the owner stops (candidate release
  + one short embedding); a shorter or looser rule accepts more impostors (fewer
  voiced frames per verdict), hence the stricter threshold. A lone monosyllable
  (< 600 ms voiced) is still dropped. The replay of a short reply spans utterance +
  600 ms release + 150 ms margin: utterances longer than ≈ `owner_buffer_ms − 0.75 s`
  are clamped (`owner_replay_clamped`). Task 14 tunes both values on hardware.

**Lingering confirmation.** Owner authorization is scoped to the current owner
speech:

- *New candidate after a gap* — every closed candidate calls `finish_candidate`,
  which always forgets the evidence: the next candidate starts in `candidate` with
  the flow closed and needs a fresh verdict before any of its audio is forwarded
  (the verifier's cached verdict can no longer cross the 600 ms gap, even when its
  energy gate kept counting "voiced" frames). The flow itself closes when the
  candidate closes (`idle`).
- *Continuous handover without silence* — the flow closes on the first non-owner
  verdict (`rejected`, no latch). The sliding window still holds up to 1.5 s of
  owner speech, so whenever the full window says "owner" the verifier also scores
  the most recent `owner_short_evidence_ms` of it; below
  `owner_threshold − owner_short_margin` (0.5 by default) the verdict becomes "not
  owner". Bound on the other voice forwarded after the handover: ≈ recent window +
  stride + hop = 0.6 + 0.5 + 0.1 ≈ 1.2 s worst case (1.0 s on the deterministic
  band embedder of the tests), versus evidence + stride ≈ 2.0 s without the rule
  (1.5 s on that embedder). Cost: one extra, shorter embedding per re-score while
  the owner is confirmed (≈ +40 % verifier CPU during owner speech). Residual
  limits: the leaked audio joins the owner's turn (it never forms its own turn); a
  false rejection of the owner on the short window closes the flow until the next
  re-score (≤ 500 ms, then replayed); after a stranger → owner handover the replay
  may still start up to 1.5 s back inside the stranger's speech (Task 04 onset
  estimate).

**Refusal policy (replaces the Task 05 open-room fallbacks).**
`PersistentVoiceRuntime.activate()` decides before opening anything (no provider
session, no microphone, wake word not suspended), with the same
`assess_authorization(authorization, verifier, continuous=…)` the Control Center
uses (same order: architecture first, then verifier), plus what only Voice sees —
the verifier actually attached to the duplex capture and an owner replay ring:

| Cause | `code` |
| --- | --- |
| hand-written invalid authorization (Voice starts, every wake is refused) | the parse code (`conversation_mode_unknown`, `solo_owner_requires_enforce`, `owner_buffer_out_of_range`, …) |
| `solo_owner` under `legacy` — and, in the Control Center probe, under a `continuous_brain` Voice would refuse to start (Gemini Live stack, manual turn end), whose own reason replaces the message | `solo_owner_requires_continuous_brain` |
| no verifier / no enrolled profile / failed engine | `solo_owner_unavailable` (+ `availability`) |
| duplex capture without owner replay ring | `solo_owner_capture_unsupported` |

A refusal traces `voice.authorization_refused` (warning, French operator message
naming the rollback, `phase = startup | activation | session`), raises the visual
alert (`.voice_alert`) and publishes the runtime state with
`VisualSignalBus.authorization()` (`runtime/.voice_authorization`, removed by
`reset()`/`offline()`). Static causes (invalid file, `legacy`) are announced at
Voice start as well. The Control Center reads that file while Voice's heartbeat
is fresh: `GET /api/settings` → `voice.authorization.runtime` (`status`, `code`,
`problem`, `conversation_mode`, `arch`, `phase`, `ts`); a runtime refusal for the
configured mode overrides a probe that says ready (`status = refused`,
`status_source = voice`). Rollback: `conversation_mode = open_room` (or remove the
key) and restart Voice.

**Capture state for the Control Center (task 08).** Alongside it,
`PersistentVoiceRuntime._report_capture()` publishes what the duplex capture
actually applies with `VisualSignalBus.capture()` (`runtime/.voice_capture`,
removed by `reset()`/`offline()`): `echo_cancellation.{requested, active, code}`
(`aec_active`, `aec_disabled`, `aec_unavailable` = canceller never built,
`aec_failed` = `CaptureProcessor.canceller_failed` during a session, traced once
as `voice.duplex` / `duplex_aec_failed`, `duplex_capture_unavailable`), the
worker's `verifier.{availability, dropped_ms}`, `speaker_verification`, `arch`,
`phase` (`activation` after the capture reset, `session_end` before it). Scalars
only. `requested` comes from the stack's `echo_cancellation` setting passed by
`app.py`; no second configuration path. The Control Center reads it only while the
heartbeat is fresh, sanitizes every key, and lets it override its own cheap probe
(`echo_cancellation_installed()`: `find_spec("livekit.rtc")`, native library never
loaded) only when it describes the current request (`status_source = voice`);
otherwise it reports `restart_required`. The UI never decides identity: every
verdict shown comes from `assess_authorization` or from these Voice reports.

Publishing those reports, and resetting the capture, are best effort: a failure
leaves the Control Center on an older state (or the next activation resets the
capture anyway) and is traced once, with the exception type name only.

| Kind | When | Data |
| --- | --- | --- |
| `voice.capture_report_failed` | `_report_capture()` could not publish the capture state (warning) | `code = capture_report_failed` |
| `voice.authorization_report_failed` | `_report_authorization()` could not publish the authorization state (warning) | `code = authorization_report_failed` |
| `voice.duplex_reset_failed` | the duplex capture refused `reset()` at session end (warning) | `code = duplex_reset_failed` |

**Mid-session verifier failure — fail closed.** Every availability change is
published by the telemetry as an `idle` snapshot, availability updated first. The
bridge (`_owner_authority()` → `_lose_owner()`) keeps the guard owner-held and
closes the flow (nothing captured reaches the provider), never falls back to the
acoustic rule (near-end and provider `speech_started` neither duck nor cut),
traces `voice.barge_in.authority` (`input = closed`) and
`voice.authorization_refused` (`phase = session`), calls `on_authorization_refused`
(alert + runtime report) and ends the session like « Jarvis mute ». Recovery: the
next wake resets the capture and the worker restores the availability the engine
declared at construction, so the engine gets a new chance; if it fails again the
session closes again. Wake/background/mute lifecycle is otherwise unchanged.

**Diagnostics.** `voice.input.non_owner_dropped`, scalars only (never audio,
transcript text or embeddings):

| `source` | Emitted by | When | Data |
| --- | --- | --- | --- |
| `capture` | `ShadowOwnerTelemetry(enforce=True)` (worker thread, shared 30/min budget) | a candidate closed without ever being recognized: nothing of it was forwarded | `mode = enforce`, `reason` (`non_owner`, `short_not_owner`, `insufficient_audio`), `candidate_ms` (onset → last near-end frame), `best_score`, `far_end` |
| `provider` | bridge (≤ 30/min, overflow counted in `suppressed`) | defense in depth: a provider segment or transcript outside the owner flow | `mode = enforce`, `reason` (`provider_speech_unverified`, `transcript_unverified`), `code` |

`voice.owner.confirmed` gains `verdict = candidate_end` for a short reply.

`Jarvis Mute` stops the voice surface, never Core work, and never auto-wakes to
speak a result the user muted through.

## Speaker verification: shadow, then Solo Owner authority

Solo Owner handoff (`tasks/jarvis_solo_owner_duplex_handoff/`), task 02: a
provider-neutral boundary for a local speaker verifier, run in shadow mode. A
baseline local engine ships since task 03 and a rolling owner state since task 04
(both below). Since task 05 the owner state is the barge-in authority in
`solo_owner` (see "Barge-in authority" above) and, since task 06, opens the
provider flow while JARVIS speaks ("Owner replay buffer"); since task 07 it is the
only way into the provider, JARVIS speaking or silent ("Owner input gate").
`NearEndDetector` stays the acoustic prefilter, the verifier is the identity
authority (D03, D05).

Types:

| Type | Where | Role |
| --- | --- | --- |
| `SpeakerVerification` | `jarvis/domain/speaker.py` | frozen verdict: `status`, `engine`, `owner_score`, `owner_detected`, `evidence_ms`, `profile_id` |
| `VerificationStatus` | `jarvis/domain/speaker.py` | `ok`, `insufficient_audio`, `no_profile`, `unavailable`, `error` |
| `SpeakerVerifier` | `jarvis/ports/speaker.py` | `engine`, `availability`, `reset()`, `process(pcm, sample_rate)`, `close()` |
| `ScriptedSpeakerVerifier` | `jarvis/adapters/fake_speaker_verifier.py` | deterministic fake: one scripted verdict per `process()` call |
| `NullSpeakerVerifier` | `jarvis/adapters/null_speaker_verifier.py` | "no verifier": `availability = not_installed`, never a score |
| `CaptureObserver`, `CaptureFrameContext` | `jarvis/audio/duplex.py` | passive tap on `CaptureProcessor`: `observe(frame, context)` |
| `SpeakerVerificationWorker`, `ShadowOwnerTelemetry` | `jarvis/audio/speaker_shadow.py` | worker thread + bounded shadow diagnostics |
| `OwnerStateMachine`, `OwnerStatePublisher` | `jarvis/audio/speaker_shadow.py` | rolling owner state (task 04) and its thread-safe publication |
| `OwnerState`, `OwnerStateSnapshot` | `jarvis/domain/speaker.py` | `idle` / `candidate` / `owner_confirmed` / `rejected` + stream timestamps |
| `OwnerStateSource` | `jarvis/ports/speaker.py` | `owner_state`, `add_owner_listener()`: the seam tasks 05–07 consume |
| `CandidateAwareVerifier` | `jarvis/ports/speaker.py` | optional capability `finish_candidate(judge)`: end-of-candidate short verdict + evidence reset (task 07) |

Score semantics. `owner_score` lies in `[0.0, 1.0]`, **higher = more likely the
enrolled owner**, whatever the engine's native scale (cosine similarity,
log-likelihood ratio, probability): the adapter normalizes it. `0.5` is not a
threshold: the decision is `owner_detected`, computed by the adapter with its
calibrated threshold, and consumers read that. A score exists only when
`status == ok`; every other status carries `owner_score = None` and
`owner_detected = False` (enforced by construction). `evidence_ms` is the audio
duration the verdict rests on. `engine` and `profile_id` are at most 64
characters. The verdict never carries an embedding or audio, so it is safe to
log. `SpeakerVerification.availability` maps a status onto the existing
`VerifierAvailability` (`ok`/`insufficient_audio` → `ready`, `no_profile` →
`no_owner_profile`, `unavailable` → `not_installed`, `error` → `failed`).

Port contract:

- all methods are called from **one dedicated worker thread** — never from the
  PortAudio callback, never from the asyncio loop — so a call may spend tens of
  milliseconds of CPU; it never does network I/O;
- `process()` receives contiguous int16 mono PCM windows of equal duration
  (100 ms by default) taken after `_cancel_echo()` — echo-cancelled only while a
  canceller runs (caveat below) — in stream order, and returns the verdict on the
  audio accumulated since the last `reset()`; the engine owns its sliding window;
  it may raise. While JARVIS speaks, frames without near-end speech arrive as
  digital silence (task 04, below);
- `reset()` forgets accumulated audio/evidence (new voice session, or audio
  dropped by the worker); the owner profile stays loaded;
- `close()` releases the engine; no call follows;
- a verifier whose `availability` is not `ready` at session start is not
  consulted.

Threading decision. Embedding models cost roughly 10–50 ms per window, too much
for the PortAudio callback, which also runs echo cancellation. The callback only
calls `CaptureObserver.observe(frame, context)` with each 10 ms frame **as it
leaves `_cancel_echo()`** and the echo guard, plus a `CaptureFrameContext`
(below); `SpeakerVerificationWorker.observe` appends it to a hop buffer and, per complete
window, to a bounded queue (2 s by default), then returns (≈ 3 µs per frame
measured, i.e. ≈ 0.03 % of a core). When the queue is full the oldest window is
dropped and counted (`dropped_ms`); the capture never waits, and the verifier is
reset before the next window since its input is no longer contiguous.
`CaptureProcessor.reset()` (voice activation, and return to background once the
bridge has closed the microphone) forwards to the worker, which resets the
verifier and the owner state in its own thread; `CaptureProcessor.close()` stops
the worker, which closes the verifier. `PersistentVoiceRuntime.close()` closes the
duplex capture after `mute()`.

What "as it leaves `_cancel_echo()`" means, exactly. The frame is echo-cancelled
only while a canceller is actually running. On three branches `_cancel_echo` is a
pass-through (`jarvis/audio/duplex.py:777-792`) — `echo_cancellation` switched off
in the settings, LiveKit/AEC3 not installed, or the canceller having raised once
during the session — and the verifier (and the Task 06 ring) then receive the
**raw microphone frame**, so a double-talk frame reaches the verifier's evidence
with JARVIS's own voice still in it. Nothing downstream compensates for it: what
the design guarantees instead is that each of those branches is *visible* rather
than silent (`aec_disabled` / `aec_not_installed` / `aec_unavailable` /
`aec_failed`, shown as `dégradée` in the Control Center, journalled `voice.duplex`
— see [`docs/OPERATIONS.md`](OPERATIONS.md)), and that the echo guard alone keeps
running, with the coupling forced pessimistic after a failure. Wherever another
page calls the verified audio "AEC-cleaned" (the task's implementation report
still does), read it as "post-`_cancel_echo()`" with this caveat. The benchmark
figures in `docs/results/speaker-benchmark/` were measured on clean synthetic
audio, so they say nothing about a degraded branch.

Shadow guarantee. The observer receives a copy of the frame and an immutable
context; nothing flows back. Emitted PCM, the echo-guard state, pre-roll,
`near_end` signals and the detector's learned state (coupling, floor, warm-up) are
byte-for-byte identical with or without a verifier, including when the verifier,
an owner-state listener or the observer raises: an observer exception disables the
observer (`observer_failed`) instead of escaping into the callback, which would
otherwise fall back to the raw microphone.

Diagnostics (`DiagnosticSink`, i.e. `RuntimeJournal` in Voice, called from the
worker thread). Since task 04 an *episode* is an **acoustic candidate** (see
"Rolling owner verification" below), not a run of verdicts.

| Kind | When | Extra data |
| --- | --- | --- |
| `voice.owner.candidate` | an acoustic candidate opens (sustained near-end speech) | verdict fields of that window, `far_end` (JARVIS audible) |
| `voice.owner.confirmed` | first owner confirmation inside the candidate | verdict fields, `confirm_ms` (shadow latency: candidate onset → confirmation, stream ms), `after_non_owner` (a non-owner verdict preceded it: handover or overlap), `far_end`; `verdict = candidate_end` for a short reply judged when its candidate closed (task 07) |
| `voice.owner.rejected` | candidate closed (600 ms without near-end speech) without any confirmation | `best_score` (`None` if never judged), `episode_ms` (onset → last near-end frame), `reason` (`non_owner` \| `short_not_owner` \| `insufficient_audio`), `far_end` |
| `voice.owner.unavailable` | verifier not ready at session start, exception, or a change to `no_profile`/`unavailable`/`error` | `code` (`verifier_not_ready`, `verifier_exception`, `verifier_reset_failed`, `shadow_exception`, `verifier_<status>`), `error` (exception type name only) |
| `voice.owner.overrun` | the worker dropped audio (once per session) | `dropped_ms`, `code = verifier_overrun` |
| `voice.owner.listener_failed` | an owner-state listener raised (it is removed) | `code = owner_listener_failed`, `error` (type name) |

Every payload carries `mode = shadow`, `engine`, `availability`; verdict fields
are `status`, `owner_score` (rounded to 3 decimals), `owner_detected`,
`evidence_ms`, `profile_id`. Only scalars — never PCM, arrays or embeddings.
Bounds: at most two events per episode (later flips inside the same candidate
are published, not journaled), one `unavailable` per state change, one
`overrun` per session, and `max_events_per_minute` (30) overall in stream time;
suppressed events are counted into the next payload (`suppressed`). A session
reset, verifier failure or overrun abandons the open candidate without an event.

Failure policy. A verifier exception or a contract violation (a `process()`
result that is not a `SpeakerVerification`) marks it `failed` and stops
consulting it until the next session; the owner state falls back to `idle`, and
that change is published even when the state was already `idle` (availability
updated first) so a Solo Owner bridge learns it at once (task 07). The worker's
`availability` starts at, and returns on every `reset()` to, what the engine
declared at construction. In the open room Voice carries on; in Solo Owner the
bridge fails closed ("Owner input gate"). The worker exposes `availability`, `dropped_ms` and
`owner_state`; the Control Center shows them since task 08.

Wiring. `jarvis/app.py::_speaker_verifier(overrides, runtime_root, journal)`
returns `None` — no worker, the duplex capture exactly as before — unless the
parsed authorization has `speaker_verification != off` **and** the local engine,
its model and a compatible owner profile are usable (otherwise one
`voice.owner.unavailable` with a stable `code`). The worker never changes the
captured audio itself; in `solo_owner` its owner state decides barge-in (task 05)
and the only provider flow, JARVIS speaking (task 06) or silent (task 07), and the
worker is built with `enforce=True` (`voice.input.non_owner_dropped`). Tests
inject the fake by monkeypatching it.

### Rolling owner verification (task 04)

Decision: **every frame reaches the verifier, echo-only frames masked, identity
only inside acoustic candidates.**

- Every frame, in contiguous 100 ms windows. The engine's own energy gate already
  drops silence/noise for < 1 ms per window; only voiced speech costs an
  embedding (90 ms p50 / 135 ms p95 every 500 ms of voiced speech, task 03: at most
  18–27 % of one core during uninterrupted voiced audio, ≈ 11 % measured on real
  speech). Feeding only near-end candidate regions would save almost nothing when
  JARVIS is silent (the engine gate and the candidate retain the same speech) but
  would delay evidence by the detector latency (≥ 120 ms) and drop the sentence
  start; the engine also needs contiguous input to learn its noise floor.
- Echo masking. While JARVIS is audible (`far_end`), a frame with no near-end
  speech is replaced by digital silence before the window is assembled; a near-end
  frame keeps the following 300 ms as is (syllable gaps). The AEC residual thus
  never enters the engine's evidence (its 600 ms gap rule clears it), playback
  alone costs zero embeddings, and the window stays contiguous and time-aligned.
- Identity only inside a candidate. The owner state exists only while an acoustic
  candidate is open, so echo-only playback, keyboard clicks or desk impacts never
  become the owner, whatever the verdict says.

`CaptureFrameContext` (built in the callback, no I/O, only when an observer is
attached): `stream_ms` (frame start, capture clock reset by
`CaptureProcessor.reset()`, also exposed as `CaptureProcessor.stream_ms`),
`sample_rate`, `near_end` (the frame alone clears the noise floor — and, while
JARVIS speaks, the predicted echo — by `NearEndDetector`'s margins; exposed as the
informational `NearEndDetector.last_near`, no detector decision depends on it),
`far_end` (`far_recent`), `near_end_latched`, `gate_open`.

State machine (`OwnerStateMachine`, worker thread only, O(1) memory: 40 booleans
and one candidate):

- Acoustic candidate: opens when the `NearEndDetector` latch rule holds on the
  per-frame flags (≥ 12 near-end frames among the last 40, ≥ 6 in a row), dated
  from the first near-end frame of the burst; closes after 600 ms without a
  near-end frame (the engine's own evidence-clearing gap). Independent of the
  bridge's `release_near_end()`.
- `idle`: no candidate (silence, short noise, echo only, verifier unavailable).
  `candidate`: candidate open, no judged verdict yet (or evidence cleared).
  `owner_confirmed` / `rejected`: the **latest** judged verdict of the candidate.
- No latch: `rejected → owner_confirmed` and back happen inside one candidate
  without silence (a stranger talking for minutes, then the owner, is confirmed
  once the engine's 1.5 s window holds the owner, i.e. ≤ one 500 ms re-score after
  the window turns over). Overlap: the engine's verdict on the mixed window
  decides, window by window; the fake-verifier tests pin this.
- Timestamps (capture stream ms): `candidate_onset_ms`; on each entry into
  `owner_confirmed`, `confirmed_ms` = end of the confirming window and
  `owner_onset_ms` = candidate onset, or — when a non-owner verdict preceded it in
  the same candidate — `max(candidate_onset_ms, confirmed_ms - evidence_ms)`, the
  start of the evidence that recognized the owner (voiced-only evidence, so the
  true onset may be slightly earlier). Both stay set until the candidate closes.
- Resets: session reset (activation and return to background), sample-rate change
  (new stream: `session + 1`), verifier failure and worker overrun (candidate
  abandoned, `idle`). At most one published change per 100 ms window, except a
  short reply confirmed when its candidate closes (`owner_confirmed` then `idle`,
  task 07).
- End of candidate (task 07): a verifier with `finish_candidate` forgets its
  evidence at every candidate close and may judge an unjudged short candidate
  once (see "Owner input gate").

Downstream seam (`OwnerStateSource`, implemented by `SpeakerVerificationWorker`,
reachable as `SoundDeviceRealtimeAudio.capture.observer`): `owner_state` returns
the latest `OwnerStateSnapshot` (`sequence` increasing over the worker's life,
`session`, `state`, `stream_ms`, `candidate_onset_ms`, `owner_onset_ms`,
`confirmed_ms`, `owner_score`, `evidence_ms`, `far_end`), readable from any
thread; `add_owner_listener(listener)` (≤ 4, returns an unsubscribe function)
calls `listener(snapshot)` on the worker thread for each change — the consumer
marshals it (`loop.call_soon_threadsafe`) and never calls back into the worker;
a raising listener is removed and journaled once. No history is kept. Since
task 05 the Solo Owner barge-in consumes the seam (one listener per voice session,
see "Barge-in authority"); `availability` is also part of `OwnerStateSource`.

Known limits (hardware, tasks 09/14): a candidate needs `NearEndDetector`'s floor
margin (12 dB) — a very quiet owner under a long loud conversation may not open
one; a canceller that stops cancelling lets echo pass as near-end until the bridge
releases it (the verifier then decides, JARVIS's voice is not the owner); an
owner → stranger handover without silence keeps `owner_confirmed` until a
re-score says otherwise — while the 1.5 s window still holds the owner, up to
≈ 2.0 s of speech; bounded to ≈ 1.2 s since task 07 by the recent sub-window
(see "Owner input gate").

### Local verifier adapter and owner profile (task 03)

The engine kept by the task 14 benchmark, still provisional until real voices are
measured (task 09 compared eight local models). Layers:

| Piece | Where | Role |
| --- | --- | --- |
| `SherpaSpeakerEmbedder` | `jarvis/adapters/sherpa_speaker_embedder.py` | the only module importing `sherpa_onnx` (lazily, first use); pinned model id/URL/SHA-256/size, `download_model`, `verify_model`; one ONNX thread |
| `OwnerVoiceProfile`, `save/load/delete_profile` | `jarvis/adapters/owner_voice_profile.py` | versioned JSON profile; errors as `OwnerProfileError(code)`; `metadata()` is the only public view (no voiceprint, not even in `repr`) |
| `EmbeddingSpeakerVerifier`, `SpeechGate`, `enroll_embedding` | `jarvis/audio/owner_verifier.py` | engine-neutral `SpeakerVerifier`: any `SpeakerEmbedder` (model id, dim, sample rate, `embed()`) plugs in |
| `probe_owner_verifier`, `open/build_owner_verifier`, CLI | `jarvis/runtime/owner_voice.py` | cheap probe for the Control Center, factory for Voice, `jarvis owner-voice …` |
| `SpeakerVerifierSettings` | `jarvis/v2_config.py` | `owner_threshold`, `owner_evidence_ms`, `owner_profile_path`, `owner_short_evidence_ms`, `owner_short_margin` (settings file only) |

Per `process()` call (100 ms hop): 20 ms frames go through an adaptive energy gate
(low-percentile floor, bounded like `NearEndDetector`'s); voiced frames enter a
sliding window bounded to `evidence_ms` of speech (default 1500). Below that →
`insufficient_audio`; a silence of 600 ms clears the window (the next speaker never
inherits the previous one's evidence) → `insufficient_audio`. Once full, the window
is resampled to the model rate (FFT, stateless), embedded, and compared with the
owner voiceprint; the embedding is recomputed every 500 ms of new speech and the
last verdict is returned in between. `owner_score` = cosine clipped to [0, 1];
`owner_detected` = score ≥ threshold (engine default 0.6 since task 14, provisional:
see "Defaults" below). A sample-rate change or
`reset()` clears the evidence; `reset()` also loads the model on the worker thread
(first wake), so the asyncio loop never pays the ~1.4 s load.

Profile compatibility is decided on the model SHA-256, embedding dimension and
sample rate, never on the library version. The Control Center probe
(`GET /api/settings` → `voice.authorization.verifier` and `verifier_detail`)
checks the module spec, the model file (size **and** pinned SHA-256) and the
profile metadata; it never loads the model and never returns the voiceprint. The
fingerprint is cached on `(size, st_mtime_ns)` (`cached_file_sha256`), so the
27 MB file is read once and repeated `GET /api/settings` calls stay cheap —
without it a corrupt model of the right size would be announced `ready` while
`SherpaSpeakerEmbedder.load` refuses it. Availability mapping: engine or model
missing → `not_installed`; model of the wrong size or content, unreadable model,
or invalid setting → `failed` (`speaker_model_mismatch`,
`speaker_model_unreadable`); profile missing, corrupt or incompatible →
`no_owner_profile`.

`owner_profile_path` is settings-file only and must resolve **inside**
`runtime_root` (git-ignored): an absolute path, `~` or `../..` is refused with
`owner_profile_path_outside_runtime`, so a voiceprint cannot be dropped into the
repository under a name `.gitignore` does not match.

**Defaults (task 14, provisional).** `owner_threshold` 0.6, `owner_evidence_ms`
1500, `owner_short_evidence_ms` 600, `owner_short_margin` 0.1, `owner_buffer_ms`
2500, engine = the sherpa-onnx CAM++ baseline. They come from the *synthetic*
benchmark (`docs/results/speaker-benchmark/`), whose gate replay drives the real
capture, verifier thread and input gate and therefore measures what the provider
would receive: at 0.5 the gate opened on 4 of 24 colleague turns, at 0.6 on one,
at 0.65 on none but with one owner turn in ten missed. Real voices decide the
final values — `docs/HARDWARE_ACCEPTANCE.md`. Writing a profile is atomic and
retried when Windows briefly holds the file (`jarvis/adapters/file_replace.py`,
shared with the model downloads): after the retries it fails with
`owner_profile_write_failed` and the previous profile is intact, never
half-written.

## Core work state

Handoff `tasks/jarvis_solo_owner_duplex_handoff/`, task 10 (contracts), task
11 (Core store and provider ingress), task 12 (brain work context and event
policy) and task 13 (Control Center task view). Goal: the brain and the UI read the same normalized
truth about ongoing work (decisions D15–D17), instead of subtask details living
only in `AgentTaskTracker`, a runtime projection inside the Control Center.

### Contracts

Neutral types in `jarvis/domain/work_state.py`, ports in
`jarvis/ports/work_state.py`:

| Type | Role |
| --- | --- |
| `WorkStatus` | `pending`, `running`, `blocked` (waits for the user), then four ends: `completed`, `failed`, `cancelled`, `interrupted` (its host vanished). `ALLOWED_WORK_TRANSITIONS` / `can_transition` define the allowed moves. |
| `WorkObservation` | one observer's statement at one instant: `source`, `external_id`, `status`, `observed_at` and, when known, `kind`, `label`, `activity`, `summary`, `model`, `parent_external_id`, `link`, `progress_fraction` ∈ [0, 1], `error_class`, `tool_uses`, `tokens`, `background`, `started_at`. |
| `WorkObservationBatch` | what crosses the process boundary: `source`, `producer_id` (one observer instance), 1–64 observations of that source. |
| `WorkItem` | the state Core keeps for one piece of work: same public fields, plus `revision`, `started_at`, `updated_at`, `ended_at` (set exactly when the status is terminal). |
| `WorkSnapshot` | global `revision`, `items` (at most `MAX_WORK_ITEMS` = 64, unique per `(source, external_id)`), `updated_at`. |
| `WorkLink` | explicit link to the brain: `work_id` (the one of `brain.work.*`) and `correlation_id` (the turn). |
| `WorkObservationSink.observe()` | observer input (`AgentTaskTracker` through the ingress, `JobService`, a future Codex observer). |
| `WorkStateReader.snapshot()` | read-only access, shared by the brain and the UI. |

Identifiers. Work is identified by `(source, external_id)` — the provider's
identity. Its brain `work_id` and `correlation_id` stay `None` until an emitter
asserts them; they are never inferred from a label nor equated with the external
id. An established link is never rewritten: a contradicting observation is
reported (`WorkUpdate.conflicts`) and the established value is kept. Same rule
for `parent_external_id`.

Ordering and terminality (`apply_observation`, a pure function):

1. the first observation creates the item, whatever its status;
2. a finished item never reopens: an observation with another status is refused
   (`terminal`), the first observed end wins; an observation with the same
   terminal status may only enrich the description (summary, counters), never
   the end date. The single exception lives in the store, not in this pure
   function: an interruption Core itself posted while claiming a source, which
   the source's current claimant may revoke (see *State lifetime and restart
   behaviour*);
3. a terminal observation ends the work even when it arrives after more recent
   progress: an end is a fact;
4. a non-terminal observation older than the last change is ignored (`stale`):
   late progress rewinds nothing;
5. a forbidden transition (back to `pending`) is refused (`invalid_transition`);
6. otherwise fields merge one by one: empty/`None` means "not observed" and the
   known value stays; only `activity` describes the instant and is replaced
   (cleared at the end). If nothing but the observation time changes, it is a
   `duplicate` and the revision does not move.

The global revision moves by exactly one per created or changed item;
`WorkItem.revision` is the revision of its last change and never exceeds the
snapshot's. A consumer that sees a gap re-reads the snapshot.

Bounds and wire form. Strings are capped (ids 128, label and activity 160,
summary 1 000, model 80; `source`, `kind`, `error_class` are short tokens):
validation refuses what exceeds, and observers truncate first with `clip_text`.
`to_payload` / `from_payload` carry declared fields only. In process,
`WorkObservation.from_payload` ignores unknown keys; across processes,
`WorkObservationBatch.from_payload` is strict and rejects any unknown key, on the
envelope or in an observation (`OBSERVATION_WIRE_KEYS`): a provider JSON (raw
trace, `prompt`, `subagent_type`…) cannot enter Core. The full prompt and trace
of a subtask stay in `AgentTaskTracker`.

### Store and ingress

```text
Control Center process                             Core process
──────────────────────                             ────────────
Claude stream-json                                 JobService ──observe()────────┐
  └► AgentTaskTracker   (raw trace, prompt)                                       ▼
       └► TrackerWorkObserver  (state diff)        POST /v1/work/observations ─► WorkStateStore
            └► WorkIngressForwarder (bounded queue) ─┘                             ├► core.work.updated (CoreEventBus, /v1/events)
                                                                                  └► snapshot(): GET /v1/work/snapshot, WorkStateReader
```

`WorkStateStore` (`jarvis/core/work_state.py`, `JarvisCoreApplication.work_state`)
implements both ports. It folds observations with `apply_observation` inside
Core's event loop, computing the revision and storing the item without yielding,
so two concurrent observations never share a revision. Core never polls a
tracker: observers push, Core decides.

- Retention: at most 64 items. Creating one more evicts the oldest finished item
  (by `ended_at`); an active item is never evicted, and when all 64 are active
  the creation is refused (`capacity`, warning diagnostic). The last
  `MAX_EVICTED_KEYS` = 4096 evicted keys are remembered so a late replay does not
  resurrect them (`evicted`). That cap sits above everything a full resend can
  replay — at most `MAX_PRODUCERS` = 32 sources, each replaying at most the 64
  items Core would hold plus the ~30 finished tasks its own tracker keeps, so
  ≈ 3 000 keys. Past the cap (tens of thousands of pieces of work in one Core
  lifetime) the oldest key is forgotten and a late replay would recreate that
  finished work as new: a deliberate bound, not an accident.
- Snapshot order: active items oldest first (`started_at`), then finished items
  newest first (`ended_at`).
- `JobService` observes in process: source `job`, `external_id` = job id,
  `kind = job`, `label` = job kind, `running` → throttled progress (same cadence
  as `brain.work.progress`) → `completed` / `failed` (`error_class` = exception
  type name, `error` if not a token) / `cancelled`. Its `WorkLink` comes only from
  the `work_id` / `correlation_id` explicitly passed to `submit()`; the synthetic
  `job:<id>` fallback used by `WorkCanceller` never becomes a brain link. A
  failing store never fails a job (`core.job.work_state_failed`).
- Claude subtasks come from the Control Center (source `claude`).
  `AgentTaskTracker.subscribe()` calls `TrackerWorkObserver.sync` after each
  stream event and each process start/stop; the observer emits one observation
  per task whose public state changed. `external_id` is `AgentTask.work_key`, the
  first public id seen (`tool_use_id` or `task_id`), stable when the public id
  switches; when the tracker merges two tasks, the retired key is closed as
  `cancelled` / `merged`. Status mapping: `running` → `running`; `completed`;
  `failed`; `killed`, `stopped`, `cancelled` → `cancelled` (raw status kept as
  `error_class`); `interrupted` → `interrupted` / `process_stopped`; any other
  terminal value → `failed` / `unknown_status`. Codex has no relay: no Codex
  subtask format is verified.

`POST /v1/work/observations` (same bearer token and protocol header as the rest
of `/v1`) takes `WorkObservationBatch.to_payload()`. Invalid or non-declared
content → 400 `invalid_request`, nothing applied. A valid but duplicate, stale,
terminal-contradicting or evicted observation is not an error. Response 200:
`{"store_id", "revision", "outcomes": {outcome: count}, "interrupted": n}`, with
outcomes among `created`, `updated`, `duplicate`, `stale`, `terminal`,
`invalid_transition`, `capacity`, `evicted`. `GET /v1/work/snapshot` returns
`{"store_id", "revision", "items": [WorkItem payload…], "updated_at"}`, served by
Core alone. Python client: `LocalCoreClient.ingest_work_observations()` /
`work_snapshot()`.

Events. `core.work.updated` is published on `CoreEventBus` (hence `/v1/events`)
once per created or changed item, never for an ignored observation nor an
eviction. Payload: `{"store_id", "revision", "previous_status" (null on
creation), "item": WorkItem.to_payload()}`; the envelope carries the item's
`correlation_id` when its link has one. Completion, failure and interruption are
read from `item.status` and `previous_status`: there is no separate
`core.work.failed`, so the bounded bus does not carry each end twice. A state
change is not speech (D17): Voice ignores these events; Core's
`WorkAttentionPolicy` reads them and never speaks (see "Brain work context and
event policy" below).

Diagnostics (`DiagnosticSink` → `runtime/trace.jsonl`), all scalar, never
provider content:

| Kind | Where | When |
| --- | --- | --- |
| `core.work.observation_ignored` | Core | `terminal`, `invalid_transition` or `capacity`, once per item and outcome; `duplicate`, `stale`, `evicted` are only counted (`WorkStateStore.outcome_totals`) |
| `core.work.observation_conflict` | Core | an observation contradicts an established link or parent |
| `core.work.producer_restarted` | Core | a new instance of a producer took over a source |
| `core.work.attention_invalid_event` | Core | `WorkAttentionPolicy` could not read a work-state event, or failed on one (the note is skipped; `error` is the exception type name only) |
| `core.job.work_state_failed` | Core | `JobService` could not update the work state |
| `agent.work_state_failed` | Control Center | a tracker listener raised (once per exception type) |
| `work.ingress_unavailable` / `work.ingress_restored` | Control Center | Core unreachable (warning, once per outage) / reachable again |
| `work.ingress_rejected` / `work.ingress_resync_failed` | Control Center | Core refused a batch (dropped, not replayed; once per run of refusals, reset by the next accepted batch) / full resend failed |
| `core.event_bus.event_dropped` | Core | a lossy subscriber's queue was full: oldest event dropped, subscription kept (once per message type) |

Failure isolation. The stream reader never waits for Core:
`WorkIngressForwarder.offer()` is synchronous, performs no I/O and raises no
transport error; the tracker catches any listener exception, so the stream,
`ask()` results and Voice keep working. Pending observations are coalesced per
task (the latest full state wins, a pending end is never overwritten by
progress) and bounded (256); overflow drops the oldest and forces a full resend.
Batches of at most 64 leave every 0.5 s from the forwarder's own task; Core
unreachable → re-queued, exponential retry from 1 s to 30 s; HTTP 401 → the
session token file is re-read (Core restarted); HTTP 400 → the batch is dropped
(replaying it would fail the same way) and counts as a loss, so a full resend
follows the next accepted batch. A full resend
(`TrackerWorkObserver.resync`) happens on first contact with a `store_id`, when
the `store_id` changes, after a loss, and after 30 s without anything to send
while the tracker holds tasks; duplicates cost Core no revision and no event. A
resend clears what the observer believes Core knows but keeps the closures it
still owes (a merged duplicate retired from the tracker), which the tracker
would never hand out twice.

### State lifetime and restart behaviour

The store is in memory only; nothing is persisted (the SQLite `jobs` table stays
the source of truth for jobs). `revision` is monotonic within one `store_id`
only: a consumer that sees a new `store_id` drops what it holds and re-reads the
snapshot.

| Situation | Result |
| --- | --- |
| Claude process stops, exits or crashes (Control Center alive) | `AgentTaskTracker.process_stopped()` → every running subtask `interrupted` / `process_stopped`, forwarded to Core |
| Claude process started again | `process_started()` interrupts leftovers the same way |
| Core restarts | empty store, new `store_id`, revision 0. Jobs running at the crash: `JobService.recover()` → `interrupted` / `core_restarted`. Claude subtasks: the forwarder sees the new `store_id` at its next send — at worst its 30 s idle resend — and resends the tracker's full state (running tasks and its last 30 finished ones); older finished items are gone |
| Control Center restarts | new `producer_id`; Core claims the source **after** applying that first batch and interrupts only the still-active `claude` items **Core attributes to the replaced instance** and that the batch does not mention (`interrupted` / `producer_restarted`). A later batch that reports such an item still active reopens it — the one narrow exception to "terminal is final". Reopening is authorised by Core alone: the key must be one Core itself interrupted while claiming the source, and the batch must come from the source's current claimant. No field a producer writes on the wire (`error_class` included) grants it, and the observation is still ordered like any other, so one older than the interruption stays `stale`. Core keeps the owning `producer_id` per item and the set of keys it interrupted as private state: neither reaches `WorkItem.to_payload`, `core.work.updated` or the snapshot |
| Two Control Centers on one Core (unsupported, but survivable) | each takeover interrupts the other instance's items once (`producer_restarted`) and neither can reopen the other's, so the flapping is bounded: with two items each and alternating batches, revision settles after the second exchange and the brain sees one attention note per item instead of a permanent stream. The price of that bound is stated plainly: **every item ends `interrupted` / `producer_restarted` and stays there** — whichever instance spoke last has had its items taken over by the other, and only the source's current claimant could reopen them. Each *new* item costs one more (true, but useless) attention note. The work itself keeps running in its Control Center; only Core's view of it is dead. Run one Control Center |
| Control Center stops gracefully | agents stop first (subtasks interrupted), then one last flush bounded by 2 s |
| Control Center killed and not restarted, or Core down during its graceful stop | its active items stay `running` in Core until a Control Center starts again or Core restarts. There is deliberately no lease: expiring after a timeout would end work irreversibly after a laptop sleep. Core's brain backend lives in that same Control Center, so brain turns fail meanwhile anyway |

### Brain work context and event policy

Task 12. The brain answers "where are my tasks?" from the same store the UI
reads, and learns about an unexpected failure without anyone asking; neither
path produces speech by itself.

```text
WorkStateStore ──snapshot()──► BrainContextBuilder ──► BrainOrchestrator._call_backend
      │                               ▲                     │ supports_brain_context?
      │ core.work.updated             │ take_delivered()    ├─ yes: run_turn_with_context(turn, BrainContext, emit)
      ▼                               │                     └─ no:  run_turn(turn, state, emit)   (unchanged)
WorkAttentionPolicy ──────────────────┘
      └► core.work.attention (diagnostic) · optional wake hook · never a SpeechRequest
```

Shape. `BrainContext` (`jarvis/domain/brain_context.py`) is the aggregate a
backend receives: `state` (the `BrainWorkingState` `run_turn` gets) and `work`, a
`BrainWorkContext`. Staged compatibility: `BrainBackend` is not widened; a
backend opts in by also implementing `run_turn_with_context` (the
`ContextAwareBrainBackend` capability, detected structurally like
`ProgressReportingJobWorker`). Backends without it — every test double, the null
backend — keep receiving `run_turn(turn, state, emit)`, and the store is not
even read for them. `ControlCenterBrainBackend` implements both: `run_turn`
sends `context = {addressing, state}` as before, `run_turn_with_context` adds
`context.work = BrainWorkContext.to_payload()`. `BrainWorkingState` and its
frequently published `to_public_payload()` are untouched: work detail never
rides on `brain.state.updated`, and `AgentTaskTracker` never reaches the brain.

Assembly. At the start of each brain turn (inside the turn task, before the
backend call) `BrainContextBuilder` awaits `WorkStateReader.snapshot()` on
`core.work_state` and reduces it with the pure `build_brain_work_context`:

| Field | Content |
| --- | --- |
| `revision`, `store_id` | those of the store read — the same pair `GET /v1/work/snapshot` returns, so a test can prove the brain and the UI read one source |
| `generated_at`, `active_total`, `finished_total` | assembly time; counts of the whole snapshot |
| `items` | `BrainWorkEntry`: `source`, `external_id`, `status`, `label`, `activity`, `summary`, `model`, `started_at`, `ended_at`, `elapsed_s` (to now, or to the end), `ended_ago_s`, `error_class`, `work_id` (only from an explicit `WorkLink`), `parent_external_id`, `progress_fraction`, `background` |
| `attention` | `WorkAttention` notes retained by the policy since the previous context-aware turn |

Bounds (hard): at most 12 active entries (blocked first, then oldest started
first), then 6 finished (newest end first), 8 attention notes; label and
activity clipped to 120 characters, summary to 240; and the compact JSON of the
whole context never exceeds 6 000 characters — past the budget an entry stops
its group and is only counted in the totals. The budget is served **attention
first**, then active entries, then finished ones: attention notes are the only
channel by which the brain learns that a piece of work failed, was interrupted
or is waiting for the user, and a busy workstation (many active items with long
labels) is exactly the case that would otherwise drop them; 8 short notes cost
about 1.6 kB of the 6 000, and an active item that does not fit is still there
next turn. Only declared `WorkItem` public fields are copied: no prompt, trace,
provider JSON or reasoning. A snapshot that cannot be read yields `work = None`
(`core.brain.work_context_failed`, once per exception type); the turn still runs
and retained notes wait for the next one. Every assembled context emits
`core.brain.work_context` (`correlation_id`, `store_id`, `revision`, totals,
`listed`, `attention`).

Prompt. The Control Center renders `context.work` through
`jarvis/runtime/work_brief.py::render_work_brief` into a few French lines
before `[Demande]`: one line per listed task (status, "depuis"/"il y a"
durations, label, activity, model, error, summary, progress), an omitted-count
line, a "new since your last turn" line for attention notes with the reminder
that knowing is not announcing, and a closing note that the list is Core's state.
Whitelist reading, like the state fields: ids, revision and raw timestamps stay
in the payload. An empty snapshot renders "aucune", a context without `work`
renders nothing.

Event policy. `WorkAttentionPolicy` (`jarvis/core/brain_context.py`) subscribes
to `CoreEventBus` (lossy queue of 512; the loop does no I/O) and reads each
`core.work.updated`. It retains a change only when an **active** item moves to
`failed`, `interrupted` or `blocked` (`needs_attention(previous_status,
status)`). Not retained: progress, completion (the normal result path — the
Claude CLI's own sub-agent relay, job notifications — owns it), cancellation (an
explicit decision), and creations already terminal (a producer's resend after a
Core restart would otherwise flood the brain with old news). Retained notes are
one per item, the latest 8, and only those a context-aware turn actually
carried are consumed (`take_delivered(context.attention)`): a note that did not
fit the char budget, or a newer note for the same item noticed meanwhile, stays
pending for the next turn. Each emits `core.work.attention` (warning, `info` for `blocked`; scalar:
`source`, `external_id`, `status`, `previous_status`, `error_class`, `work_id`,
`revision`, `pending`, `wake`; at most 20 per minute, the rest counted in
`suppressed`).

Wake. The policy accepts an optional `wake(notes)` hook, called at most once per
60 s, never twice in flight, without consuming the notes; a failing hook is
reported once (`core.work.attention_wake_failed`). **Core wires no hook**: the
decision is to deliver the change on the next brain turn rather than open a
proactive one, because (1) the brain is a single CLI session and a proactive
turn would delay the user's next turn (user feedback 8/10), (2) the Claude CLI
already wakes itself when a background sub-agent ends (task-notification relayed
by `announce_notice`), so a Core wake would double it, (3) failed jobs already
raise a Windows notification, (4) a `process_stopped` interruption means that
same brain process is down, and (5) no observer emits `blocked` yet and Claude
subtasks carry no `work_id` link. When a proactive turn is wanted, the hook is
the seam; its speech must still be a brain `SpeechRequest` through the
`SpeechScheduler`.

Invariants kept. The policy never publishes `brain.*`, never revises
`BrainWorkingState`, never cancels or supersedes: a failure of work linked to a
brain `work_id` leaves `active_work_ids` and the intent revision as they were,
and removing work is still only the brain's explicit `CANCELLED` /
`SUPERSEDED` naming a `work_id`. The surface stays tool-free and owns no task
state. The policy loop is stopped before the brain on Core shutdown.

Its subscription is one of the two `CoreEventBus.subscribe(lossy=True)` in Core
(the other is the runtime scene projector, for the same reason): nothing re-subscribes the policy, so the default eviction of a saturated
subscriber would end work attention for the lifetime of the process. A lossy
subscriber keeps its subscription and drops the **oldest** queued event
instead — the bus stays just as bounded (the queue never grows past 512) and
the cost of a burst is at most one "new since your last turn" line, because the
fact itself survives: the item still carries its `failed` / `interrupted` /
`blocked` status in the snapshot the brain reads every turn. Each first drop
per message type is reported as `core.event_bus.event_dropped` (warning;
`message_type`, `queue_maxsize`, `dropped_total`) and every drop is counted in
`CoreEventBus.dropped_total`. Every other subscriber keeps the eviction policy
(`core.event_bus.subscriber_evicted`).

### Task visualization in the Control Center

Task 13. The Agents panel is a projection of Core, not a second state machine.

```text
Browser (Agents panel, 1 s poll while open)
  ├─ GET /api/work ─► CoreWorkView ─► CoreWorkTransport.snapshot() ─► GET /v1/work/snapshot   (card state)
  └─ GET /api/agent/tasks ─► AgentTaskTracker                                              (brain card + diagnostic)
       └─ GET /api/agent/tasks/{task_id}/trace                                              (raw provider trace)
```

Data source per field. Sub-agent cards take `status`, `label`, `activity`,
`model`, `started_at` / `ended_at`, `summary`, `error_class`, counters, parent
and `work_id` from Core's `WorkItem` only. The tracker contributes what Core
deliberately does not carry — prompt, `subagent_type`, `tool_use_id`, last tool,
depth, trace — joined on `(source, external_id)` = `(provider, work_key)`;
`/api/agent/tasks` now exposes `work_key` for that join, and
`AgentTaskTracker.find()` also resolves a `work_key`, so the trace opens from a
Core id. The UI labels the two: "État normalisé · Core (fait foi)" versus
"Diagnostic fournisseur · brut, non autoritaire" / "Trace brute du fournisseur
· diagnostic". The brain card (process, PID, session, console) is not Core work
and still comes from the tracker. Core items whose source is not an agent CLI
(Core jobs) get their own "Autres travaux Core" section.

`GET /api/work` (`ControlCenter.work`, `jarvis/runtime/work_view.py`) returns
`{"source": "core", "core_reachable", "store_id", "revision", "items":
[WorkItem payload…], "updated_at", "stale", "error", "now_ms", "agent_cli",
"subtasks_supported"}`. It is the only work route of the Control Center and it
is `GET`-only: nothing in the Control Center UI writes work state; the only
writer from that process remains the stream observer
(`WorkIngressForwarder`). It also constructs nothing: it reads the clock of the
already-built agent when there is one and the process clock otherwise, because
building an agent would subscribe another tracker observer and rebind
`work_ingress.on_resync`. The response is decoded with
`WorkSnapshot.from_payload` and re-serialized, so only declared fields reach the
browser. `CoreWorkView` uses its own `CoreWorkTransport` (token file re-read, one
retry after a 401), separate from the relay's, with a 2 s read timeout.

Revisions. `accept_snapshot(held, store_id, revision)` (server) and the
identical `acceptWork(held, next)` (page) keep the last accepted snapshot: an
older revision of the same `store_id` never replaces it (`stale: true`, the
held state is served), a different `store_id` (Core restarted) replaces it
whatever its revision. The panel polls the snapshot and does not consume
`/v1/events`, so the "apply only revision + 1" rule for events does not arise.
Elapsed time is `ended_at - started_at`, or `now - started_at` while active,
`now` being the browser clock corrected by the Control Center's `now_ms`; no
separately mutated counter remains. End-of-task toasts compare successive
accepted snapshots of the same store; a new store or a switch between Core and
the degraded projection resets that memory without notifying.
`WorkAttentionPolicy` is never consumed from the UI: neither `take_pending()`
nor `take_delivered()` is reachable from a Control Center route.

Where the page's pure logic lives. `acceptWork`, `coreTask`, `isRunning`,
`taskElapsed`, `clockSkew` and `authDraftAfterChange` (the mode/verification
coherence of task 08) are in `jarvis/runtime/control_center_work.js`, which
`ControlCenter.index` inserts verbatim into the page at the
`/*__CONTROL_CENTER_WORK_JS__*/` marker. The page therefore stays a single
document with no external resource — no cache can serve a version the server no
longer has — while the tests execute that same file with `node` instead of
matching strings in the HTML (`tests/conftest.py::page_logic`,
`tests/unit/test_work_view.py`, `tests/unit/test_control_center_quality.py`).

Degradation. Core unreachable, token missing, timeout or refused read →
`core_reachable: false`, no items, `error.code` among `not_configured`,
`core_unreachable`, `core_refused`, `invalid_snapshot` (the last journaled once
per exception type as `work.view_invalid_snapshot`). The page then shows the
tracker's local projection under an explicit "Core indisponible … Affichage
dégradé … non autoritaire" banner; it is never presented as Core state and the
brain never sees it. An active agent that relays no subtasks (Codex:
`subtasks_supported: false`) gets a clean empty state.

Compatibility. `/api/agent/tasks` and its trace route are unchanged apart from
the added `work_key`; the closed-panel dock badge still uses the tracker counts
of `/api/status` as a cheap poll trigger (while the panel is open the badge
follows the Core cards). Deleting `/api/agent/tasks` as a *state* source is
possible once parity is confirmed on the workstation (task 14,
`docs/HARDWARE_ACCEPTANCE.md` §7); its diagnostic
role (prompt, raw trace, brain card) has no Core equivalent by design and
would need a replacement route first.

## Constellation scene store

Handoff `tasks/jarvis-constellation-scene-runtime/`, Slice 02. The scene model
itself (objects, authority matrix, revisions, patches) is
[scene-model.md](scene-model.md); this section covers who owns it at runtime and
how it survives a restart; *Scene transport* below covers the HTTP routes
(Slice 03); *Runtime scene projection* covers the runtime writer (Slice 04).

```text
SceneCommand ─► SceneService.apply()  (Core, asyncio lock)
                  ├► apply_scene_command()            pure domain decision
                  ├► SQLiteSceneRepository.commit()   one transaction  ─► data/state/scene.sqlite3
                  ├► memory snapshot + patch ring (512)
                  └► wake wait_for_revision() waiters   (never CoreEventBus)
```

| Piece | File | Role |
| --- | --- | --- |
| Ports | `jarvis/ports/scene.py` | `SceneCommandSink.apply`, `SceneReader` (`snapshot`, `patches_since`, `wait_for_revision`, `archived_history`), `SceneRepository`, `SceneStoreError` + stable `SceneStoreErrorCode` |
| Adapter | `jarvis/adapters/sqlite_scene.py` | `SQLiteSceneRepository`, dedicated SQLite file |
| Service | `jarvis/core/scene_service.py` | `SceneService` = `JarvisCoreApplication.scene` |

Command path. Commands are serialized by one asyncio lock. The domain decides
the outcome; a refused (`rejected_authority`, `invalid`) or `duplicate` command
writes nothing, wakes nobody and returns its `SceneUpdate` (refusals are
journaled once per actor/op/reason as `core.scene.command_refused`). An applied
command is **persisted before anyone can see it**: commit, then the in-memory
snapshot advances, the patch enters the ring, and waiters of
`wait_for_revision` are woken.
The application runs in a shielded task, so cancelling a caller mid-write never
leaves the file ahead of memory. `patches_since(revision, scene_id=)` returns the
patches after `revision`, or `resync_required` when the ring (512 patches, empty
after a restart) no longer covers the gap, when the revision is ahead of Core or
when the `scene_id` differs: the consumer then re-reads the snapshot
(decision 20).

Change notification. The scene is deliberately **not** on `CoreEventBus`:
`LocalProtocolServer.events()` forwards every bus event, unfiltered, to every
`/v1/events` WebSocket client, Voice included. Scene patches (up to 1 536 ops since Slice 08)
would weigh megabytes on the voice socket, and a projector burst could fill a
non-lossy 128-slot subscriber queue and evict Voice. No component needs a
broadcast: the projector (Slice 04) listens to work state, never to the scene, and the transport
(*Scene transport* below) long-polls locally. `wait_for_revision(after, *, timeout_s)` returns
the current revision as soon as it exceeds `after`, or unchanged at the
deadline; `timeout_s` is clamped to [0, 30] s (`MAX_REVISION_WAIT_S`). It raises
`SceneUnavailableError` at once when the scene is unavailable or closed, and
wakes with that error when `close()` or a divergence happens during the wait.
It is an `asyncio.Event` swapped on every commit, close and divergence;
cancelling a waiter leaves no task and no registration behind. A failed commit
wakes nobody.

### Persistence

Durable, unlike Core work state: a scene restart restores the identical active
snapshot, the same `scene_id` and the same revision (decision 11).

Why a **separate file**, `data/state/scene.sqlite3`, rather than tables in
`jarvis.sqlite3`: the scene gets its own `schema_version` and can evolve without
touching the operational state schema (still 1, no migration framework), and a
refused scene file only disables the scene — conversations, jobs and schedules
live in a file it never touches.

Conventions copied from `sqlite_state.py`: a `schema_version` table, JSON `data`
columns, one connection serialized by a lock, native work in a thread that
cancellation cannot interrupt (`run_sqlite_in_thread`, shared), WAL; plus
`synchronous=FULL`, because a revision Core has exposed must survive a power cut.

| Table | Content |
| --- | --- |
| `schema_version` | one row, `1` |
| `scene_meta` | singleton row: `scene_id`, `revision`, `wire_schema_version` (= `SCENE_SCHEMA_VERSION` of the JSON columns), `created_at`, `updated_at` |
| `scene_objects` | `object_id`, `position`, `data` (`SceneObject.to_payload()`) |
| `scene_relations` | `relation_id`, `position`, `data` |
| `scene_tombstones` | `object_id`, `position` — `SceneSnapshot.archived_ids`, evicted beyond 4 096 like the domain |
| `scene_history` | `object_id`, `revision`, `archived_at`, `data` — the archived form written by each `archive_object` op; not pruned in V1 (one row per user archive) |

`position` restores the exact tuple order of the snapshot (a replaced object
keeps its place, a new one is appended). The store keeps the **state** produced
by each patch, never a log of patches to replay: `commit` applies the patch ops
to the tables inside one `BEGIN IMMEDIATE … COMMIT`, checks that the stored
revision is the one Core started from and that row counts match the resulting
snapshot, then moves `revision`. A crash leaves the previous or the next
revision, never half of one. Loading decodes every row through the strict domain
decoders (`SceneObject.from_payload`, `SceneSnapshot` invariants); nothing is
replayed, so the immutable-field guard a patch replay would need is not required.

Opening, in order:

0. **Sweep** (`sweep_leftovers`, called by `SceneService.start()` first):
   removes interrupted-creation temporaries `scene.sqlite3.<random>.creating`
   (and `-journal`) from the scene's own directory only, when they are older
   than 10 minutes (a concurrent creation is never cut) and are regular files
   checked with `os.lstat` (a symlink or junction is never followed nor
   removed). **Nothing outside the scene's directory is ever read or touched.**
   Removals are journaled `core.scene.swept` (info), failures
   `core.scene.sweep_failed` (warning); a sweep never blocks the start.
1. **Missing file** (and no orphan `-wal`): created atomically. Schema,
   `schema_version` and the `scene_meta` row (new `scene_id`, revision 0) are
   written to a temporary file in the same directory, then renamed onto
   `scene.sqlite3` (`replace_with_retry`). A crash leaves at worst that
   temporary file, never an empty or partial `scene.sqlite3`. This is the only
   path that creates a scene.
2. **Existing file**: `os.access` on the file and its directory before opening
   (a read-only file is refused `storage_io` and leaves no trace), then the
   real file is opened read-write through a `file:…?mode=rw` URI, which never
   creates it: a file that vanished in between is refused `storage_io` instead
   of leaving an empty file, and the next start creates a scene. An empty or table-less file is refused
   `corrupted` by a read before any write (switching to WAL would write its
   header), never recreated.
3. **Validation under the write lock**: `BEGIN IMMEDIATE` on that connection,
   then `schema_version`, table list, `quick_check`, wire version, full decode
   of the scene and a write probe (`UPDATE schema_version SET version =
   version`), then `ROLLBACK`. Holding the lock means a concurrent writer
   cannot tear what is validated, and nothing can change between validation
   and use: the accepted connection is the one the store keeps. No copy of
   the scene is ever made.

Refusal guarantee: a refused file's **logical content** is never modified,
rewritten, recreated or deleted. Only physical changes may happen (WAL
checkpoint on close, journal-mode header switched to WAL for a file in
rollback-journal mode), so byte identity of the file, `-wal` and `-shm` is not
promised. What SQLite
reports as not-a-database or malformed is `corrupted`; lock, permission and
I/O conditions are `storage_io`.

Failure semantics:

| Situation | Result |
| --- | --- |
| first start, file missing | created atomically (temporary file + rename), new `scene_id`, revision 0, `core.scene.loaded` (`created: true`) |
| `schema_version` newer than 1 | refused `schema_newer` |
| version unreadable/unknown, foreign database, `wire_schema_version` ≠ 1 | refused `schema_unknown` (or `schema_newer` for a newer wire version) |
| empty (0 bytes) or table-less file, not a SQLite file, `quick_check` failure, missing table, missing `scene_meta` row, row that does not decode, `-wal` without its database | refused `corrupted` |
| path is a directory, file or directory not writable (read-only, ACL), write lock held by another process beyond the 5 s busy timeout, I/O error | refused `storage_io` |
| any refusal at start | `core.scene.unavailable` (error); scene unavailable (`SceneUnavailableError`), **rest of Core starts normally**; the file's logical content is never modified, rewritten, recreated or deleted (physical-only changes: WAL checkpoint, journal-mode header) |
| file vanishes between the access check and the open | refused `storage_io`, no file created; the next start creates a scene |
| commit fails (I/O, lock) | transaction rolled back (including a failure right after `BEGIN`); no revision advance, nothing in the ring, no waiter woken; `core.scene.persist_failed` (error) **once per outage**: an identical failure (same code, same exception type) repeated before a successful commit is only counted, a different one is journaled with `suppressed` = the count silenced so far, a divergence always is; the first successful commit after failures journals `core.scene.persist_restored` (info, `code`, `suppressed`); caller gets `ScenePersistenceError` every time; the next command may succeed |
| rollback fails, connection left inside a transaction | same, reported `storage_io` with `fatal`; the scene becomes unavailable until Core restarts |
| stored revision ≠ Core's (`revision_conflict`), or an integrity constraint fails during the write | same, and the scene becomes unavailable until Core restarts; current waiters get `SceneUnavailableError` |
| `COMMIT` durable on disk but reported as failed (I/O error at the very end) | caller gets `ScenePersistenceError` although the command may already be durable; memory did not advance, so the next command fails closed with `revision_conflict` (scene unavailable) and a restart loads the revision actually written. Nothing is lost silently |

Lifecycle: `SceneService.start()` runs right after `jarvis.sqlite3` opens in
`JarvisCoreApplication.start()` and never raises; `close()` runs in `stop()`
after the back brain and job shutdown, in a `finally` that also covers their
early returns and exceptions, and always right after the runtime projector has
stopped (see *Runtime scene projection* › *Start and stop ordering*). `jarvis/core/v2_app.py` builds the adapter itself, like
`SQLiteStateRepository`; `sqlite_scene` is listed in the named composition-root
exception of `tests/unit/test_v2_architecture.py`.

### Scene transport

Handoff Slice 03 (decision 20: full snapshot, then monotonic revision patches,
resync on any doubt). The browser never talks to Core: it has no token. The
Control Center relays, without holding any scene state.

```text
Browser (control_center_scene.js pure client; rendering: see Scene renderer)
  ├─ GET  /api/scene           ─► CoreSceneView.snapshot() ─► GET  /v1/scene/snapshot
  ├─ GET  /api/scene/patches   ─► CoreSceneView.patches()  ─► GET  /v1/scene/patches   (long-poll)
  ├─ POST /api/scene/commands  ─► CoreSceneView.command()  ─► POST /v1/scene/commands  (actor forced to user)
  └─ POST /api/jobs/cancel     ─► CoreSceneView.cancel_work() ─► POST /v1/work/cancel  (job stars only, Slice 08)
Brain display MCP (Slice 06) ───────────────────────────────► POST /v1/scene/commands  (actor brain, bearer token)
Runtime projector (Slice 04) ─► SceneService.apply() inside Core, never HTTP
```

| Piece | File | Role |
| --- | --- | --- |
| Wire shape | `jarvis/protocol/scene_wire.py` | bounds, stable error codes, query parsing, bounded body reading and response encoding shared by Core, its client and the proxy |
| Strict JSON | `jarvis/protocol/strict_json.py` | duplicate keys and `NaN`/`Infinity` refused; shared with the canonical voice routes |
| Core routes | `jarvis/protocol/server.py` | `scene_snapshot`, `scene_patches`, `scene_command`, scene block in `health` |
| Client | `jarvis/protocol/client.py` | `LocalCoreClient.scene_snapshot/scene_patches/scene_command` (response read bounded to 16 MiB) |
| Proxy | `jarvis/runtime/scene_view.py` | `CoreSceneView` (stateless relay, degraded payloads), `CoreSceneTransport` (token re-read on 401, like `CoreWorkTransport`) |
| Pure client | `jarvis/runtime/control_center_scene.js` | `window.JarvisSceneClient`, injected at `/*__CONTROL_CENTER_SCENE_JS__*/`; no DOM, network or timer |

Core routes (bearer token and protocol-version check, like every `/v1` route):

| Route | Success | Errors |
| --- | --- | --- |
| `GET /v1/scene/snapshot` | 200 `{scene_id, epoch, revision, snapshot}` (`snapshot` = `SceneSnapshot.to_payload()`), compact UTF-8 JSON encoded off Core's event loop | 401, 426, 400 (query present), 503 `scene_unavailable` |
| `GET /v1/scene/patches?scene_id=&epoch=&after=&wait_s=` | 200 `{scene_id, epoch, revision, resync_required, more, patches}` | 401, 426, 400 (missing/unknown/repeated parameter, `after` not a non-negative integer, `wait_s` not a plain non-negative number), 503 `scene_unavailable` |
| `POST /v1/scene/commands` | 200 `{outcome, reason, scene_id, epoch, revision, patch}` for **every** domain outcome (`applied`, `duplicate`, `rejected_authority`, `invalid`); `patch` is `null` unless applied | 401, 426, 400 `invalid_request` (not JSON, duplicate key, non-finite number, any `ValueError`/`TypeError` of `SceneCommand.from_payload`), 403 `scene_actor_forbidden` (actor `runtime`), 413 `payload_too_large` (> 64 KiB, announced or streamed), 503 `scene_unavailable` / `scene_persist_failed` |

A 503 carries `error.scene` (`{state, code}` of `SceneService.availability`) and
`error.store_code` (`SceneStoreErrorCode`). Malformed input is caught only as
`ValueError`/`TypeError` and mapped to 400 by the existing middleware; the
message is the decoder's (received values echoed ≤ 80 characters), never a stack
trace. `GET /v1/health` keeps `protocol_version`, `ready`, `status`, `detail`
unchanged and adds `scene: {state, code, saturated, objects, object_limit}`
(`objects` is `null` when the scene is not served; the capacity fields were
added in Slice 04 and the 503 `error.scene` block carries them too); an unavailable scene never turns
`ready` false (the scene is a projection).

Long-poll. `GET /v1/scene/patches` answers at once with `resync_required: true`
(no patch, no snapshot) when `epoch` differs from the current load, `scene_id`
differs, `after` is ahead of Core, or the 512-patch ring no longer reaches
`after + 1` (always the case right after a restart). With patches already past
`after`, it answers at once. Otherwise it waits on
`SceneService.wait_for_revision` (local wait, never `CoreEventBus`), clamped by
Core to 30 s, then answers with what arrived (possibly nothing). Stopping the
server releases pending long-polls immediately (without that, aiohttp's
shutdown waited for them, up to 30 s). `revision` is the revision the client
reaches by applying `patches`. The body is bounded to 1 MiB
(`MAX_PATCH_RESPONSE_BYTES`) but always carries at least one whole patch; when
the bound cuts the list, `more: true` tells the client to ask again at once.

Epoch. `SceneService.epoch` is a random id generated at each `start()` and
exposed read-only; every snapshot, patch and command response carries it.
`(scene_id, revision)` alone is not a safe cache key: restoring an older
`scene.sqlite3` keeps the `scene_id` and reuses revisions. A client that sees
another epoch refetches the snapshot, whatever the revision says.

Actor rule. Over HTTP, Core accepts only `brain` and `user`. `runtime` is
refused with 403 `scene_actor_forbidden`: the runtime writer lives inside Core
(Slice 04) and needs no network path. The Control Center proxy forces `user`:
a body without `actor` gets `user`, any other value (`brain`, `runtime`, empty,
non-string, `USER`) is refused with 403 before Core is called, so the browser
can never act as the brain. `_origin_guard` applies to the command route like
every other `POST`. Authority itself is still decided by the reducer: a brain
archive reaches Core and comes back 200 `rejected_authority/op_not_allowed`.

**Threat-model limit (stated plainly).** The token is a loopback session
credential, not a boundary between local processes of the same user. The brain
runs as the Claude CLI with `--permission-mode bypassPermissions` under the same
OS user, so it can read `runtime/core.token` and call `POST /v1/scene/commands`
itself claiming `user` — archiving, pinning, anything the user may do. In V1 the
guarantee that the brain does not archive is the display MCP tool catalog
(decision 14: the operation is absent from the brain's tools) plus reducer
authority for honest callers. It is **not** a local security boundary, and the
actor field is a declaration, not an authentication.

Control Center proxy. `GET /api/scene` and `GET /api/scene/patches` answer
400 for a malformed query; otherwise they answer 200 whatever the state of
Core or of the scene, shaped like `/api/work`: `source`, `core_reachable`
(`null` when Core was not asked), `scene` (`{state, code}` or `null` when
unknown), `scene_id`, `epoch`, `revision`, `snapshot` (or `patches`,
`resync_required`, `more`) and `error` (`null`, or `{code, message}` with
`not_configured`, `core_unreachable`, `core_refused`, `invalid_scene_response`,
`scene_unavailable`, `patch_waits_busy`). Core's answers are decoded with the
strict domain decoders before reaching the page. Journal: a read outage once,
`scene.view_unavailable` (warning), and its end once, `scene.view_restored`
(info); an out-of-contract answer once per read kind (`snapshot`, `patches`,
`command`) until the next good answer, `scene.view_invalid_response` (error).
The full cause (file paths included) stays in the journal; every message sent
to the page goes through `page_text`, which replaces file paths with
`<chemin>`.

Load. Long-polls use their own connection pool to Core
(`CoreSceneTransport._polls`), so snapshot reads and commands never wait for a
pool slot held by a long-poll (QA measured a 504 at 200 concurrent long-polls
when they shared aiohttp's 100-connection pool). At most 32 long-polls are
relayed at once (`MAX_CONCURRENT_PATCH_WAITS`); beyond that the answer is
immediate, no connection held or opened: 200 with `error.code =
patch_waits_busy`, `core_reachable: null` and `retry_after_ms: 1000`, which the
pure client maps to action `retry` (keep the state, ask again after the delay).
Busy refusals are journaled `scene.view_busy` (warning) at most once a minute
with the number silenced. The proxy clamps `wait_s` to 25 s and gives up after
the wait plus 5 s (HTTP timeout, then a second `asyncio.wait_for` bound), so a
hung Core cannot hold the page. Snapshot reads time out after 10 s.

`POST /api/scene/commands` validates the body locally (64 KiB, strict JSON,
`SceneCommand`) and answers 200 with the domain outcome, 400/413 for form, 403
for another actor, 503 when Core or the scene is unavailable (`scene` block
included) or the write failed, and 502 when Core refused the call
(`core_refused`) or answered out of contract. Two timeouts tell "not sent" from
"unknown": no connection to Core within 3 s (aiohttp `ConnectionTimeoutError`,
pool wait included) is 503 `command_not_sent` — nothing was applied, retrying
is safe; a connection refused or a missing token is 503 `core_unreachable`
("commande non envoyée"); no answer within 10 s once the request is sent
(`SocketTimeoutError`, or the outer bound) is 504 `core_timeout` — the command
may have been applied, the client re-reads the scene. Relayed commands are
journaled `scene.command` (info: op, outcome, reason, revision), failures
`scene.command_failed` (warning, with the full cause), refused actors
`scene.command_forbidden` (warning, at most once a minute per actor value, with
the number silenced).

Pure client (`JarvisSceneClient`). `fromSnapshot(response)` builds
`{scene_id, epoch, revision, objects: Map, relations: Map, archived_ids: Set}`;
`acceptSnapshot(held, response)` never rewinds the same scene and epoch;
`applyPatch(state, patch)` applies one patch with exactly
`apply_scene_patch`'s semantics (order kept, tombstones evicted beyond 4 096)
and returns a new state or `{ok: false, reason}` without touching the old one;
`applyPatchResponse(state, response)` returns `{state, action, reason}` with
`action` `retry` (Control Center busy: wait `retry_after_ms`), `unavailable`
(retry later), `resync` (refetch `/api/scene`: no state,
`scene_changed`, `epoch_changed`, `resync_required`, `gap`, refused patch),
`more`, `applied` or `unchanged` (late duplicates are skipped);
`patchQuery(state, waitS)` and `toSnapshot(state)` complete it.
`tests/unit/test_scene_transport_client.py` proves parity with the Python
reducer on random command sequences and convergence under drops, duplicates,
bounded responses, ring overflow and a Core restart.

### Runtime scene projection

Handoff Slice 04 (decisions 3, 4, 12, 17). Without any brain turn, every real
sub-agent and every Core job becomes a star of the scene, parent → child links
appear, and failures, interruptions and blocks attach a minimal signal. Core work
state stays the truth; the scene only projects it.

```text
WorkStateStore ─ core.work.updated ─► CoreEventBus ─ lossy queue (512) ─► SceneProjector  (jarvis/core/scene_projector.py)
      ▲                                                                       │ actor = runtime, in process
      └──── snapshot(): at start, on a revision gap, on another store_id ◄────┤
                                                                              ▼
                                                                    SceneService.apply()
```

`JarvisCoreApplication.scene_projector` is the only `runtime` writer of the scene.
It never publishes anything (the scene stays off the bus) and never goes through
HTTP (Core refuses `runtime` there).

Projection authority. The projector issues only what decision 3 grants runtime
(see [scene-model.md](scene-model.md) › *Authority matrix*): it creates `agent`,
`job` and `attention` objects, touches only objects whose `origin` is
`runtime`, never writes a composition field (`representation`, `geometry`,
`layer`, `order`, `visibility`) nor a relation layer, and never archives.

| Work fact (`WorkItem`) | Scene effect |
| --- | --- |
| `kind = agent` (Claude sub-agent) or `kind = job` (Core job, back-brain jobs included; speculative jobs are never observed) | star `agent` / `job`, `category` = the kind token, `exec_state` = `status`, `work_ref` = `{source, external_id, work_id}`, `payload.title` = label (clipped to 160, one printable line), `payload.summary` = summary (C0 controls other than `\n`/`\t` replaced, `\r\n` → `\n`); unplaced (`geometry = null`, the renderer places it) |
| `kind = shell`, `other`, empty | nothing (decision 4); a task whose kind later becomes `agent` gets its star then |
| status change | `exec_state` only; never visibility nor disposition (decision 12) |
| label / summary change | payload refreshed only while the star still carries the payload the projector wrote. In memory (per star, up to 1 024 stars) the rule is exact: a payload the brain or user changed is left alone. Without that memory (after a Core restart, or once forgotten) the projector treats a payload with an empty title or the same title as its own, so a brain or user edit that kept the title (a rewritten summary only) **can be overwritten** by the next refresh. Category is announced at creation only and never rewritten |
| `parent_external_id` (same source) | `parent_of` parent → child once both stars exist, whichever arrives first (child first: linked when the parent star is born, by scanning the ≤ 64 work items). A parent without a star (a shell task) gives no link and no star |
| `failed`, `interrupted`, `blocked` | one `attention` signal per work item, updated in place with `attach_signal`: `category` = status, `exec_state` = status, `payload.title` = `error_class` (or the status), `payload.summary` = activity (blocked) or summary, ≤ 240 characters, `work_ref` of the work |
| leaves that state (`blocked` → `running`, an interruption Core reopens, `blocked` → `completed` / `cancelled`) | the projector retires its signal: `unlink` of the signal's `explains` relation, then `patch_object` of the signal's `exec_state` to the new status. The attention object stays, not live. A later `blocked` / `failed` re-attaches the same id |
| `completed`, `cancelled` | no signal; the star's `exec_state` says it |
| star tombstoned (the user archived it) | nothing is sent: the projector reads `archived_ids` before writing, so an archived star never resurrects and produces no `object_archived` refusal |
| scene full (`MAX_SCENE_OBJECTS` = 512 active objects) | the star or signal creation is **deferred**, not lost (see *Saturation* below) |

Identity scheme (`star_object_id`, `signal_object_id`, `parent_relation_id`):
deterministic, at most 128 characters, collision-safe.

| Object | Short form | Longer than 128 characters |
| --- | --- | --- |
| star | `<source>:<external_id>` (`claude:toolu_01…`, `job:<job id>`) | `<source>#<sha256(source NUL external_id)[:24]>:<external_id prefix>` |
| signal | `attention!<star id>` | `attention#<sha256(star id)[:24]>!<star id prefix>` |
| `parent_of` relation | `parent_of!<child star id>` (a work item has one parent) | `parent_of#<sha256(child star id)[:24]>!<prefix>` |

A source is a token (no `:`, `#`, `!`), so the text before the first separator
tells the forms apart: short star ids start with a bare token then `:`, hashed
ones with `token#`; signal ids carry `!` before any `:`. Two hashed forms collide
only if 96 bits of SHA-256 collide. A brain or user object already holding one of
these ids is left alone (`core.scene.projection_conflict`, once per id).

Signal lifecycle. A runtime signal is **live exactly while its `explains`
relation exists** (`is_live_signal` in `jarvis/domain/scene.py`). The domain
change of this Slice (PM amendment F1) lets runtime `unlink` a relation of that
shape (`explains`, `relation_id` = source id) when its source is an `attention`
object of `origin = runtime` and its target a runtime `agent` / `job`; nothing
else is granted (no archive, no visibility, no geometry, no deletion). Retired
signals stay in the scene, at most one per star. See
[scene-model.md](scene-model.md) › *Runtime signal lifecycle* for the rule and
its residual risks (relations carry no origin).

Notes for the renderer (Slice 05, applied in *Scene renderer*):

- a retired signal keeps its last `category` (`failed`, `blocked`…) and payload;
  only its `exec_state` changes. Use `is_live_signal` (relation present), never
  the category or `exec_state`, to decide whether to draw it as an alert;
- `parent_of` cycles are possible: the domain does not validate them and runtime
  links whatever parents the producers report, while brain and user may add
  their own `parent_of`. A layout that walks parents must guard against cycles.

Saturation. Decision 12 stays: completed work is never removed automatically,
so a long-lived scene fills up (QA measured about 400 sub-agents at a realistic
failure mix). Saturation is made visible and recoverable instead:

- before creating a star or a signal, the projector checks the active object
  count; at the limit (or on an `invalid` / `scene_full` refusal raced by another
  writer) it **defers** the creation: the work item's last known state is kept
  in a pending set, ordered by first deferral, updated in place by later events,
  bounded to `MAX_PENDING_CREATIONS` = 1 024. Beyond the bound the oldest
  **finished** entry is dropped first (the oldest entry when none is finished),
  and counted. While Core runs, a deferred creation therefore survives the
  eviction of its item from Core's 64-item work snapshot;
- **the pending set lives in memory only.** A Core restart forgets it. After a
  restart only work that is still in Core's work snapshot (reconciliation) or
  that a producer re-sends (the Control Center resends its tracker's full state
  when it sees a new `store_id`) comes back, deferred again if the scene is still
  full; the rest never gets its star. The same holds for an entry dropped by the
  bound;
- `core.scene.projection_saturated` (warning) when a saturation episode opens,
  **at most once per `SATURATION_WARNING_INTERVAL_S` = 10 minutes**, with
  `objects`, `object_limit`, `pending` and `suppressed_episodes` (episodes opened
  silently since the previous warning): at the cap, a user archiving one star per
  new sub-agent opens an episode per sub-agent. An episode closes whenever the
  pending set becomes empty, whatever the reason (created, archived meanwhile,
  failed during catch-up); `core.scene.projection_desaturated` (info, `objects`,
  `object_limit`, `deferred`, `dropped`) is emitted only for an episode that was
  announced. `core.scene.projection_pending_overflow` (warning) at the first drop
  of an episode;
- while something is pending, a watcher task (`jarvis-scene-projector-space`)
  waits on `SceneService.wait_for_revision` (at most `SATURATION_RETRY_S` = 30 s)
  and puts an internal space-check marker in the projector's own queue (never on
  the bus): a user archive triggers the catch-up at once, the timeout is the
  periodic retry. The watcher is cancelled as soon as the pending set becomes
  empty, never started once `stop()` has begun, and cancelled by `stop()` after
  the drain, so none outlives the projector;
- catch-up order (PM decision, decision 4): **non-terminal work first**
  (`pending`, `running`, `blocked`), then terminal work, oldest first within
  each group; a star's signal is created right after its star when there is
  room. A work event for non-terminal work is projected before the catch-up
  runs, a terminal one after it. The catch-up stops at the first entry that no
  longer fits;
- `SceneService.capacity` (`objects`, `object_limit`, `saturated` =
  `objects >= object_limit`) is exposed in the `scene` block of `/v1/health` and
  of 503 scene errors, and the Control Center's `/api/scene` derives the same
  three fields from the snapshot it serves, so Slice 05 can show "scène pleine —
  archiver". Brain and user creations are refused with `scene_full` too while the
  scene is full.

Consistency and bounded work. Events carry `{store_id, revision}`; the projector
applies an event only when `store_id` is the one it reconciled with and
`revision` is exactly the next one. An older revision is skipped (already
covered); a jump means the lossy queue dropped events (`revision_gap`); another
`store_id` means Core work state was reset (`store_changed`); an unreadable
payload is `invalid_event`. Each leads to one reconciliation from
`WorkStateStore.snapshot()` (at most 64 items) that projects every item. Stars
whose work vanished are not touched (marking them after a restart is Slice 10).
Per event the projector sends at most a star upsert, a parent link, a signal
command (two to retire) and, only when a star is born, links for children
already present, the only case where it reads the work snapshot. Replays and
duplicates are `duplicate` outcomes: no revision, no patch.

Resilience. The subscription is lossy (a full queue drops its oldest event,
counted in `CoreEventBus.dropped_total`, and keeps the subscription), so the
projector is never evicted and never slows the bus, Voice's `/v1/events` socket
or the work attention policy. A `SceneStoreError` (scene refused at start,
closed, persistence failure) is journaled once per outage
(`core.scene.projection_unavailable`, warning, `code` and error); the projector
then drains its queue while it waits, retries a reconciliation with a backoff
from 1 s to 30 s, and on success journals `core.scene.projection_restored`
(info, `suppressed` = failed attempts). Any other exception on one work item is
journaled once per type (`core.scene.projection_failed`, error) and skipped; the
loop never dies. Refused commands are already journaled once per reason by
`SceneService` (`core.scene.command_refused`).

Expected path, all `info`, scalar ids only (never labels or summaries):
`core.scene.projection_reconciled` (`reason` = `start`, `revision_gap`,
`store_changed`, `invalid_event` or `scene_unavailable`; `store_id`,
`work_revision`, `items`, `applied`, `refused`), `core.scene.star_created`
(`object_id`, `kind`, `source`, `status`), `core.scene.signal_raised`
(`object_id`, `target_id`, `status`, `error_class`), `core.scene.signal_retired`.

Start and stop ordering. `start()`: `scene.start()` (never raises), then
`scene_projector.start()`, which subscribes before its first reconciliation so
nothing published meanwhile is missed, then the rest, so `jobs.recover()`
interruptions reach the scene. `stop()`: brain, attention policy, notifications
and scheduler stop as before; then `back_brain.stop()` and `jobs.stop()`, whose
cancellations publish the jobs' final work states; then, in a `finally` that
covers both early returns (`state_persistence_unknown`, `cleanup_unknown`) and
exceptions, `_stop_scene()`: the projector unsubscribes, lets what is already
queued reach the scene for at most 2 s (`stop_drain_s`), is cancelled (a command
in flight still finishes its transaction, `apply` is shielded), and only then
`scene.close()` runs. No writer outlives the scene, so shutdown never meets
`SceneUnavailableError`; a start failure stops them in the same order.

### Brain display MCP

Handoff `tasks/jarvis-constellation-scene-runtime/`, Slice 06 (decisions 1, 2,
14, 15, 16). The conversational brain composes the scene through an MCP tool
surface, as actor `brain`, on the same Core scene the user and the runtime
write. No dedicated display AI: the tools call Core's scene port over HTTP,
never the renderer.

```text
ControlCenter (scene.enabled) ─► ClaudeLocalAgent.display_mcp = DisplayMcpTarget
  └► claude -p … --mcp-config runtime/display-mcp.json      (conversation profile only)
       └► python -m jarvis display-mcp   (FastMCP stdio, env: JARVIS_CORE_HOST/PORT/TOKEN_FILE, JARVIS_RUNTIME_DIR)
            └► SceneDisplayTools ─► CoreSceneTransport ─► POST /v1/scene/commands  (actor = brain, always)
                                                         └► GET  /v1/scene/snapshot
```

| Piece | File | Role |
| --- | --- | --- |
| Gate | `jarvis/runtime/scene_settings.py` | `scene.enabled` in `control-center-settings.json` (default false); `JARVIS_SCENE_ENABLED` overrides; exposed by `GET/POST /api/settings` as `scene` (no UI before Slice 11) |
| Wiring | `jarvis/runtime/control_center.py`, `jarvis/app.py` | `_run_control_center_v2` builds `DisplayMcpTarget` from `V2Settings`; `_apply_agent_settings` hands it to the Claude agent only when the gate is on |
| Spawn | `jarvis/runtime/claude_local.py` | `_display_mcp_args`: atomic write of `runtime/display-mcp.json`, `--mcp-config <file>`; prompt program `conversation_display_session` |
| Server | `jarvis/runtime/display_mcp.py` | `build_server` (lazy `mcp` import), `SceneDisplayTools` (logic, testable against a real Core), `serve_stdio` |
| Prompt | `BRAIN_DISPLAY_PROMPT` → descriptor `backend.claude.conversation.display`; `BRAIN_ARTIFACT_PROMPT` → descriptor `backend.claude.conversation.artifacts` (Slice 07) | appended after `BRAIN_SYSTEM_PROMPT`, in that order, by program `backend.claude.conversation.display_session` |

Gating. Off, nothing changes for the brain: same argv, same system prompt
(`backend.claude.conversation.session`). On, only the `conversation` profile gets
`--mcp-config`; `job_result` never does, and `speculative_analysis` keeps
`--restricted --tools "" --strict-mcp-config`. The core projector and the store
run whatever the gate (Slice 11 PM decision). The CLI reads its MCP servers and
its system prompt when the process starts, so a change applies at the next brain
(re)start; a resumed CLI conversation keeps the system prompt it recorded first
(`--system-prompt-snapshot`) while the tools appear at once. The config is a file,
not inline JSON, because an npm `.cmd` shim re-parses quotes through `cmd.exe`;
it carries paths and a port, never the token. `--mcp-config` without
`--strict-mcp-config` **adds** the server: the user-scope servers (`jarvis-drive`,
claude.ai connectors, `claude-in-chrome`) stay loaded (checked on CLI 2.1.273,
`system/init.mcp_servers`). If the file cannot be written, the brain starts
without display tools and `agent.display_mcp_failed` (error) says why; voice
comes first. `agent.start` carries `display_mcp: true|false`. The routing hook
still matches `Agent|Task` only; under `bypassPermissions` the MCP tools need no
allowlist. The CLI may defer MCP tool schemas behind `ToolSearch` (one extra call
per new tool per conversation, observed). Display tools are not counted as inline
work by the turn budget audit (`DISPLAY_TOOLS`: the exact seven
`mcp__jarvis-display__<tool>` names, never a prefix match).

Tool catalog (V1). Exactly seven tools (six from Slice 06, `scene_add_artifact`
from Slice 07); **no archive, pin or unpin tool** and no
parameter that could carry `actor`, `placed_by`, `exec_state`, `work_ref` or a
disposition (tested). Unknown arguments are refused, never ignored: every tool
schema says `additionalProperties: false` (nested geometry and items too), and
the server's `call_tool` refuses an unknown key with an error naming it before
anything runs (FastMCP alone would drop `archived: true` and answer success).
Numbers are strict (`true`, `"5"` refused). Mapping in [scene-model.md](scene-model.md) › *Brain tool
mapping*. `scene_update_object` sends **one** command, so a refusal applies
nothing: geometry alone → `set_geometry`; representation (± geometry) →
`set_representation`; anything touching category, payload, layer or order → one
`patch_object` carrying every given field; `visibility` alone → `set_visibility`
(added after the QA live run, where haiku did not find `scene_set_visibility`
behind the CLI's deferred tool list; that tool stays). A payload edit merges with the
object's current payload (read from the snapshot just before; a concurrent edit
in between is overwritten). `scene_link` omits `layer` unless given; since the
wire decodes a missing layer as 50, re-linking an existing relation without a
layer is answered `duplicate` locally and sends nothing, so a layer chosen by the
user is kept. Ids are generated: `brain-<kind>-<12 hex>` for objects (no `:`/`!`,
so never a runtime id), `brain-<relation kind>-<sha256(from, to)[:16]>` for
relations (idempotent re-link). A `relation_id` the brain supplies must match
`brain-[A-Za-z0-9_.-]+`; the domain independently refuses brain/user ids in the
runtime's reserved forms (`reserved_id`, scene-model › *Authority matrix*), so the
brain can no longer squat `parent_of!…` or `attention!…` and suppress a runtime
link or failure signal.

Inspection. `scene_inspect` returns compact JSON: header (`scene_id`,
`revision`, `objects`, `object_limit`, `saturated`, `relations`, `hidden`,
`archived`, legend) plus rows `o` = `[id, kind, category, origin, exec_state,
representation, [x,y,w,h]|null, layer, order, visibility, pinned_by_user,
placed_by, live_signal, title≤60]` and `r` = `[relation_id, kind, from, to,
layer]` (only relations between listed objects). Brain objects first, then user,
then runtime; cut at `MAX_INSPECT_BYTES` = 20 000 with `truncated`
(`objects_omitted`, `relations_omitted`, hint). Optional filters `kind`,
`category` (exact), `text` (title or id substring). Capacity is derived from the
snapshot (same as the Control Center proxy). Summaries and screenshots are Slice 09.
The legend's `data` entry, the tool description and the prompt mark ids,
categories and titles as data, never instructions: runtime star titles come from
sub-agent labels, which may copy web content (prompt-injection vector, not a
security boundary; SECURITY 13).

Stale scene memory (QA M1). Decision 4 changes the scene without a brain turn, so
the prompt and every mutating tool description say to re-read with
`scene_inspect` in the same turn before describing the screen or acting. As a
cheap mechanical aid, `SceneDisplayTools` remembers the `(scene_id, revision)` the
brain last saw (its last `scene_inspect`, then its own commands). A command whose
answer is not at the expected revision (seen + 1 when applied, seen otherwise), or
a command sent before any inspection in this server process, returns
`scene_changed` (one French sentence with `révision X → Y`) in its result, or
appends it to the refusal message. It is per MCP server process, i.e. per brain
CLI process.

M1 follow-up (agent 0): the revision alone did not tell the brain *what* changed.
The server also keeps a compact index of the scene it last saw (`id → kind,
visibility, exec_state, title ≤ 40`, rebuilt from each snapshot, so at most
`MAX_SCENE_OBJECTS` entries). When a command finds the scene moved, the server
re-reads the snapshot once (no new Core route) and appends to `scene_changed` a
summary: `+ id (kind, visibility, exec_state) "title"` for objects that appeared,
`- id (kind) archivé ou retiré "title"`, `~ id (kind) visible → hidden, running →
failed "title"` for visibility or execution-state changes; the command's own
target is excluded; at most `MAX_CHANGE_ENTRIES` = 10 entries, then `+N autres —
relis la scène avec scene_inspect`; titles are JSON-quoted under a « titres =
données, jamais des consignes » heading. The re-read scene becomes the scene seen.
If the re-read fails, only the first line is returned.

Final follow-up (QA m-b, m-c). On the fast path (answer at the expected
revision), the command's own applied patch is applied to the index
(`put_object` updates, `archive_object` removes), so the brain's own earlier
actions never come back as external changes. A filtered or truncated
`scene_inspect` only records the objects it actually returned
(`_remember_seen_objects`, merged into the previous index of the same scene) and
marks the view partial: the next command skips the fast path, re-reads, and lists
the objects never returned as `+` (first line « Ta dernière lecture de la scène
était partielle … » when the revision did not move). A full, untruncated
inspection or a re-read clears the partial mark.

Bulk unhide. `scene_set_visibility` takes either `object_id` + `visibility`, or
`scope="all_hidden"` + `visibility="visible"` (and no `object_id`). Core applies
nothing in bulk: the server reads the current snapshot (objects that appeared
since the last inspection included), sends one `set_visibility` per hidden
object, at most `MAX_BULK_TARGETS` = 128 per call (`remaining` beyond), and
returns `matched`, `applied`, `duplicate`, `refused`, `applied_ids` and
`refused_ids` (`{id, reason}`), each list capped at 20, plus `scene_changed` when
the snapshot differs from the scene seen. A transport failure mid-way is a tool
error saying how many objects were already shown. The call also has an overall
time budget, `BULK_DEADLINE_S` = 15 s, checked between commands (a command already
sent keeps its own 3 s + 10 s bound): past it, the loop stops and the result
says `deadline_reached: true`, `remaining` and a note to call again. One summary
`display.tool` entry (`scope: all_hidden`, counts, `deadline_reached`). Hiding by
scope does not exist (too broad).

Semantic artifacts (Slice 07, decisions 1, 2, 5, 6, 12, 15). After background
work completes, the brain may keep what is worth returning to as **one grouped
artifact** linked to the work's star.

- **Tool surface.** One dedicated tool, `scene_add_artifact(target_id, category,
  title, summary?, items?, items_mode?, representation?, geometry?)`; everything
  else stays on the Slice 06 tools (retitle, move, hide or open as a window:
  `scene_update_object`). Why a dedicated tool rather than `scene_create_object`
  then `scene_link`: two calls let the brain forget the link, link to the wrong
  object or create a second artifact on a retry; the dedicated call carries the
  target, applies the grouping rule itself and cannot leave an unlinked artifact.
  Why no `scene_update_artifact`: re-calling `scene_add_artifact` with the same
  target and category is the update path, and generic edits already exist.
- **Atomicity: a narrow domain op.** `attach_artifact` (brain and user only, not
  runtime) writes the artifact and its `explains` relation in one patch, or
  nothing: an unknown or archived target, a taken or reserved `relation_id`, the
  relation limit, a full scene or a pin refuses both. Compensation after a refused
  `link` was rejected because the brain cannot archive or delete (decision 14):
  a created orphan could only be hidden, holding a slot. `attach_signal` is the
  precedent (one object plus its link). The relation id differs from the object
  id (`brain-explains-<sha256(from\nto)[:16]>`), so the link is never shaped like
  a signal link; and since the QA rework the domain refuses brain/user a `link` of
  `explains` whose `relation_id == from_id` from a non-`attention` source
  (`signal_shape`), so only signals carry that shape.
- **Idempotency rule: one artifact per target and category.** The category is
  normalised to lowercase (grouping is case-insensitive). The tool reads the
  snapshot, requires the target to be active (refused locally with
  `object_archived` or `unknown_object` and a target-specific sentence, « Rien n'a
  été envoyé », `display.tool_refused` with `sent: false`), then looks for the first
  active artifact of that category with a non-signal-shaped `explains` relation to
  the target. Found: `attach_artifact` on it (`action: updated`) carrying the
  **payload only**: title replaced (the brain owns the semantic title; a user
  rename is overwritten, residual), summary kept unless given, items merged
  (`items_mode=append`, default) or replaced (`items_mode=replace`); in both modes
  an item with a URL replaces the item with the same URL **in place** (label and
  ref updated), an item without URL is deduplicated on (label, ref); over 32 →
  `invalid_argument` asking to group or replace. `representation` and `geometry`
  are **never applied on update** (PM decision: they are the user's composition);
  the result lists them in `ignored`. Its existing relation id is reused. Not
  found: a fresh `brain-artifact-<12 hex>`, `capsule` unless another representation
  is given, geometry if given (`action: created`). Identical call → `duplicate`.
  The result carries `object_id`, `target_id`, `relation_id`, `action`, `category`,
  `items`, `outcome`, `revision`, `rule` (short code `un_par_cible_et_categorie`;
  the full sentence lives in the tool description, not repeated in every result),
  `ignored`/`ignored_note`, and `grouping_note` when several artifacts already
  match.
- **Concurrency.** The CLI can issue parallel tool calls. `SceneDisplayTools` holds
  one `asyncio.Lock` per (target, lowercase category) around read → decide →
  attach, so parallel calls for the same pair make exactly one artifact (`qa07_race.py` rerun: 90
  parallel trials with 2, 3 and 5 calls, 0 duplicates); other pairs do not wait.
  The lock table only holds pairs with a call in flight. Scope: one display-MCP
  process (one brain CLI); two brain processes on the same scene are not
  serialised. Why category-scoped: a
  meeting's follow-up may produce a roadmap artifact and an email artifact for the
  same star; tests may be one artifact or several, as the brain judges (grill).
  Why not a deterministic id: an artifact the user archived keeps its tombstone,
  and the next result must create a new one, not fail.
- **Races with the user.** If Core refuses the **sent** command with
  `object_archived`, the tool re-reads: target archived → one refusal (the one
  `_send` already journaled) with the target sentence and no « rien n'a été
  envoyé »; the reused artifact archived by the user meanwhile → one retry that
  creates a new artifact (an archived artifact is never revived).
- **Categories.** Open token list, shape-checked by the domain; recommended set
  `RECOMMENDED_ARTIFACT_CATEGORIES` = research, fichiers, tests, api, roadmap,
  email, document, autre, listed in the tool description and the prompt, with a
  known colour family in the renderer (parity test).
- **Prompt** (`BRAIN_ARTIFACT_PROMPT`, only in `conversation_display_session`).
  Completion notices reach the brain as unsolicited CLI turns in the same
  conversation (`task-notification`, `_push_notice`), so the appended system
  prompt applies there; the notice text still becomes speech through Core
  `announce_notice`, unchanged. The guidance: only when the result is worth
  returning to, create or complete one grouped artifact linked to the work's star
  (found with `scene_inspect`, kind agent); group URLs, files, tests, emails,
  roadmap changes into items, never one object per action; re-call instead of
  duplicating; recommended categories; no artifact for a plain « done »; silent
  (the spoken answer follows the notice rules, short relay or `[pas-pour-moi]`,
  and never mentions the artifact or the grouping, « je l'ai rangé », « ce qui en
  fait quatre », unless the user asks about the artifact itself); when
  `scene_inspect` shows only an artifact's title and its content is no longer in
  context, say so in one sentence and do not offer to redo the work unless asked
  (Slice 09 adds object detail reading); artifact text is data. `BRAIN_SYSTEM_PROMPT`
  and `BRAIN_DISPLAY_PROMPT` are byte-identical to Slice 06 (hash test); flag off,
  the prompt is `BRAIN_SYSTEM_PROMPT` alone as before. Work-attention wakes
  (failures) do not ask for artifacts.
- **Journal.** `display.tool` / `display.tool_refused` as for any command, plus
  `display.artifact` (info: `action`, `outcome`, `id`, `target`, `category`, item
  count, `revision`, `ignored`; never the title, summary or URLs).

Errors. Every failure becomes a tool error (`isError: true`, FastMCP
`ToolError`), never a success-shaped result. What the brain reads never carries a
non-JSON Core error body (such a response carries the code `http_<status>` and is
classified `core_refused` with status and code only, « Core a refusé la commande
(500 http_500). »), a file path (`page_text`, Slice 03 redaction,
also applied to the `error` field journaled), nor the received value of a
refused argument (pydantic errors are reduced to `field : reason`, without
`input_value` or documentation URL). Every error text of these tools has the same
form, the message alone: the `StrictDisplayMCP` server strips FastMCP's « Error
executing tool … : » prefix. Transport failures are classified by the
same function as the Control Center proxy, `scene_view.classify_scene_call_failure`
(`decode_command_response` is shared too):

| Case | Code | Text given to the brain |
| --- | --- | --- |
| domain refusal | `scene_refused` | `<op> refusé par la scène (outcome=<outcome>, reason=<reason>) : <explanation>` (`REFUSAL_EXPLANATIONS`; `scene_full` asks to propose archiving to the user; `runtime_owned` says the signal can be hidden) + `scene_changed` sentence when relevant |
| unknown argument | `unknown_argument` (journal) | names the refused keys and the allowed ones; nothing sent |
| schema or domain bound (type, enum, NaN, out of range, 64 KiB body) | `invalid_argument`, `payload_too_large` | `field : reason`; nothing sent |
| token file missing, connection refused | `core_unreachable` | command not sent |
| link lost after send | `core_unreachable` | outcome unknown, re-inspect |
| no connection within 3 s | `command_not_sent` | nothing applied, retry is safe |
| no answer 10 s after send, snapshot > 10 s | `core_timeout` | outcome unknown, re-inspect |
| 503 | `scene_unavailable` / `scene_persist_failed` | nothing applied |
| 400/413 with a JSON error | Core's code (`invalid_request`, `payload_too_large`) | Core's message, redacted |
| other HTTP (401 after one token re-read, 5xx, non-JSON body) | `core_refused` | status and code only |
| out-of-contract answer | `invalid_scene_response` | |
| anything else | `display_internal_error` | type and message only, redacted |

Journal (`runtime/trace.jsonl`, identifiers only): `display.server_started`,
`display.tool` (info: tool, op, outcome, revision, id, `scene_changed`),
`display.tool_refused` (info, with `reason`; Core also journals
`core.scene.command_refused`), `display.tool_failed` (warning for transport,
argument and schema failures with `code` and, for schema refusals, the field
names; error for `display_internal_error`). `display.server_stopped` is written
only when the stdio session ends cleanly (stdin closed); when the brain CLI stops,
its job object usually kills the server first, so the two events are not paired.

Authority and threat model. The actor is forced to `brain` by construction (the
tools build `SceneCommand(actor=brain)` and assert it before sending, never with
`placed_by`). Core's reducer refuses `archive`/`pin`/`unpin` to `brain`
(`op_not_allowed`) whatever the catalog, refuses brain and user an `unlink` of
runtime execution topology or of a runtime signal link, and a new `link` of
`parent_of` between two execution nodes (`runtime_owned`, QA rework and final
follow-up: the brain could silence a failure signal or leave false topology it
could never remove), and refuses ids in the
runtime's reserved forms (`reserved_id`). This protects against an honest caller
only: see *Scene transport* › threat-model limit and `docs/SECURITY.md` › 13.
Relations carry no origin: the runtime may remove a brain relation shaped like its
own; a `parent_of` between two execution stars can only come from the runtime.

### Scene renderer

Handoff Slice 05 (decisions 6–13, 18, 19). The Control Center page draws the
persistent scene as strict-2D layers: the ambient face underneath, an SVG
relation layer, then absolutely positioned DOM nodes. It only renders and places;
Core stays the owner (decision 11).

| Piece | File | Role |
| --- | --- | --- |
| Pure layout | `jarvis/runtime/control_center_scene_layout.js` (`window.JarvisSceneLayout`, marker `/*__CONTROL_CENTER_SCENE_LAYOUT_JS__*/`) | coordinate frame, text neutralisation, category tones, `isLiveSignal`, AutoResolver, view model, commit ledger |
| Page core (pure) | `jarvis/runtime/control_center_scene_page.js` › `JarvisScenePageCore` (marker `/*__CONTROL_CENTER_SCENE_PAGE_JS__*/`) | loop state machine (leader, follower, solo), message validation and resolver committer; every dependency injected (requests, timers, clock, random, broadcast) |
| Browser block | same file, `installJarvisScene` IIFE (`window.JarvisScene` = `{gate, statusLost, inspect}`) | scene container, SVG, DOM nodes, Web Locks leadership, BroadcastChannel, gate, status indicator, keyboard |
| Tests | `tests/unit/test_scene_renderer_logic.py` | node runs of the served files with fake timers and requests |

Both files are inserted verbatim by `ControlCenter.index`: the layout file right
after `control_center_scene.js`, the page file after Barehands. Their pure parts
contain no DOM, `window`, `fetch`, interval or storage access (asserted by test).

**Gate.** `GET /api/status` (already polled every second) carries `scene` =
`load_scene_gate(settings)` (`{enabled, source}`; `JARVIS_SCENE_ENABLED`
overrides the file). `refreshStatus` calls `JarvisScene.gate(s.scene)`. Off (the
default): no container, no style, no scene request, so the page is the one from
before Slice 05. Switching on creates the container and starts the loop; switching
off aborts the long-poll, releases the lock, stops the committer and removes the
container and its style element. A failed status read leaves the gate unchanged.

**Coordinate frame** (also in [scene-model.md](scene-model.md) › *Coordinate
frame*). Origin (0, 0) at the centre of the scene container (= the window), x
right, y down, scene units. The reference frame x ∈ [−160, 160], y ∈ [−90, 90]
(16:9; `SCENE_FRAME_HALF_WIDTH/HEIGHT` in `jarvis/domain/scene.py`, same values
in the JS, parity test) is always fully visible: scale
`s = min(W / 320, H / 180)` px per unit on both axes (no distortion), centred.
Another aspect ratio reveals extra scene on the long axis, never bars. Visible
extent: x ∈ ±W/(2s), y ∈ ±H/(2s). `geometry {x, y}` is the top-left corner and
`{w, h}` the size, same units. A `point` is drawn at its box centre with a fixed
26 px hit area; `capsule` and `window` fill their box (text clipped, box never
resized). An object outside the window is never moved (decision 10): it is
clipped and counted in "N objets hors champ".

**Composition safe area** (Slice 05 QA rework): x ∈ [−152, 138], y ∈ [−72, 68]
(`SCENE_SAFE_AREA` in `jarvis/domain/scene.py`, `SAFE_AREA` in the layout file,
parity test). It is the part of the frame no control covers at 1280 × 720, the
smallest supported 16:9 size (4 px per unit), in both themes. Measured there: top
bar bottom y −76.5 (circuit brand and state; Omega state pill −78.5, Omega dock
−77); circuit dock left edge x 142.5; voice hint top y 76.5; status chips top y 79
(one row) or 71 (two rows). The margins are 12–18 px. Larger windows give the
controls fewer units; a window that is not 16:9 but narrower than 1280 px, the
GPT-Live banner (a transient alert) and the Barehands badge (test mode) can
still cover the edges. The resolver places only inside the safe area. The brain
reads it in the `scene_inspect` legend `frame` line (`SCENE_FRAME_NOTE`: "zone
sûre x -152..138, y -72..68 (haut gauche ≈ x -150, y -70) ; cadre visible … dont
les bords peuvent passer sous les commandes"), the `geometry` schema
description, and one line of `BRAIN_DISPLAY_PROMPT` ("haut gauche ≈ x -150,
y -70 ; bas droite : x + w ≤ 138, y + h ≤ 68"). Browser check: a brain window at
(−150, −70, 60 × 36) overlaps no control at 1920 × 1080, 1366 × 768 and
1280 × 720 in both themes (corner and title hit tests return the window).

**Stacking registry.** Theme-independent. The scene container is its own
stacking context, so scene layers (0–1000) never escape it.

| Element | z-index (circuit-board) | z-index (Omega) |
| --- | --- | --- |
| `.face` iframe / `#omegaFace` canvas | 0 | 0 |
| `#sceneLayer.scene` | **20** | **20** |
| `.topbar` / `.voicehint` | 31 / 31 | 45 / 31 |
| `.dock` | 32 | 50 |
| `.panel` | 33 | 42 |
| `.live-banner` | 35 | 48 |
| `.bgpills` | 40 | 50 |
| `.tl` (conversation timeline, full-screen modal) | 55 | 55 |
| `.overlay` (settings) | 60 | 60 |
| `.toasts` | 70 | 70 |
| `.bgpop` | 75 | 75 |
| `.ctxmenu` | 80 | 80 |
| `.cdialog-back` (confirmation, Slice 08) | 85 | 85 |
| `#jarvisHands` (Barehands) | 2147483000 | 2147483000 |

The conversation timeline (`#timeline`, main's conversation-observability
Slice 05) is a full-screen modal above every control and the scene; toasts,
background popover, context menu and the Slice 08 confirmation stay above it.
Both modals make the other `body` children `inert` and skip children already
inert, so they nest in either order: a confirmation over the timeline inerts
the timeline and gives it back on close; the timeline closing restores only
what it inerted.

Before Slice 05 the face, top bar, voice hint, dock and panel had no z-index
(DOM order); the explicit values keep their previous relative order. Inside the
container, the SVG is at 0 and each node at
`layer × 2 000 001 + (order + 1 000 000) + 1` (monotonic in layer then order,
below 2³¹; ties follow Core order, which is DOM order); the status indicator
sits above all nodes. A hovered or focused point is raised so its label stays
readable; the status chips and the live region sit above all nodes.
`tests/unit/test_scene_renderer_logic.py` checks the registry against the CSS of
the three files.

**View model and visual grammar.** `viewModel(state, layout, viewport)` returns
the visible nodes in Core order (hidden objects are neither drawn, nor placed,
nor obstacles), the edges between two drawn objects (sorted by relation layer),
the hidden and off-screen counts, and the capacity (`objects ≥ object_limit`,
limit from the snapshot's `scene.object_limit`, default 512). One DOM element
per `object_id` keeps its identity across `point` / `capsule` / `window`. Its
content is rebuilt only when its content signature changes, its position only
when its geometry or stack changes.

- Primary colour = category tone: known families, otherwise a stable
  FNV-hashed tone.
- `exec_state` is a secondary cue only: breathing ring (running), dashed ring
  (pending), double ring (blocked), thin static ring (completed point: finished,
  not yet put away, decision 12), drawn badge (failed, interrupted, cancelled),
  check on terminated capsules and windows.
- Signals are live iff `isLiveSignal`, the same rule as `is_live_signal` (an
  `explains` relation whose id is the signal's id). Urgency: `high` (failed or
  error tone), `medium`, `low` for a `payload.title` of `process_stopped`, and
  `none` when retired (hollow outline, no ring, no link). Low urgency is
  decided on what the projector writes for a runtime signal: `origin` runtime,
  `category` `interrupted` and error class `process_stopped` (the projector
  carries the error class in `payload.title`). The displayed title of a runtime
  signal maps its error class through the page's `ERROR_CLASSES` wording
  ("processus arrêté", "Core redémarré"…) or a status token through the French
  status labels; an unmapped class ("TimeoutError") stays as is.
- A **runtime** signal stacks with its star: its z-index is the star's plus one
  (star found through its live `explains` link, else the same `work_ref`), so a
  window covering the star covers its signal too, instead of the signal (layer
  300) drawing over unrelated windows. Brain and user `attention` objects keep
  their own layer (decision 8). Live high- and medium-urgency runtime signals
  whose centre lies inside a window drawn above them are counted
  (`coveredSignals`, rectangle test on the view model at each render) and shown
  as a quiet chip: "N signal(s) d'échec sous une fenêtre / des fenêtres",
  "N signal(s) à vérifier sous …".
- Completed work stays drawn.
- **Compact rendering** (page only, never committed, the scene representation
  is unchanged): a window whose box is under 180 × 96 px is drawn as a capsule
  (title only, 28 px high, at the top of its box); a capsule narrower than 72 px
  as a point with its hover label; a capsule is at least 24 px high. At
  800 × 1000 (2.5 px per unit) a default 64 × 40 window becomes a capsule.
- Window title: two lines at most (margin, not padding, so no third line
  shows); summary and item list fade out at the bottom instead of cutting a row
  (no fade when the list fits).
- Point labels stay inside the scene: shifted horizontally from the node centre
  and the label's layout width (unaffected by its transition), and placed above
  the point near the bottom edge.
- Aesthetic reference: the grilling session's visual grammar and the existing
  Omega theme (dark glass surfaces, thin borders, monospace, `--omega-accent`
  palette). The visual-direction document named by the handoff is not in the
  repository. No 3D, parallax or space decoration.

**Text.** Scene payload reaches the DOM only through `textContent`; the page file
contains no `innerHTML` (asserted). `cleanLine` / `cleanText` also:

- remove bidi marks and isolates (U+061C, U+200E/F, U+202A–202E, U+2066–2069);
- remove invisible characters (U+00AD, U+180E, U+200B–200D, U+2060–2064,
  U+FEFF);
- remove C0, DEL and C1 controls (a summary keeps line feeds; tab becomes a
  space);
- turn U+2028/2029 into a space (line) or a line break (summary);
- clip by code points.

Removing U+200D also splits emoji ZWJ sequences (accepted).

**Artifact inspection view** (Slice 07). An artifact keeps one identity in every
form (decision 6); the view model adds `itemCount`, `explains` (first non-signal
`explains` relation to an active object: `{id, title, kindLabel, execLabel,
tone, hidden}`, from one `explainsIndex` pass over the relations per render) and,
per item, `href`/`host` when the URL is openable (the host is never shortened in
the model).

- **Point:** label `title · résultat · <category> · N entrées · explique « star »`
  (also the node's `aria-label` in every form).
- **Capsule:** category token in its colour, then the title.
- **Window** (the inspection view): header with category and entry count, the
  title on two lines at most, an **origin button** (drawn return arrow, the star's
  colour dot, its title, `sous-agent · terminé`) that selects and focuses the star
  (inert and announced « masqué » when the star is hidden), the summary (at most
  38 % of the height, faded), then the items list, which takes the remaining
  height, **scrolls** (wheel, focus) with `overscroll-behavior: contain`, and
  fades its last visible row until scrolled to the end (`sc-at-end`) or when it
  fits (`sc-fits`). Colours come from the existing scene tokens; both themes
  (circuit-board, Omega) keep the dark scene surface. A link row is one `<a>` with
  the **host first** (non-shrinking) then the label, followed by the out icon and
  the ref; the ref shrinks first, then the label. Below a 260 px row
  (`HOST_PRIORITY_ROW_PX`, final follow-up N1) the row is `sc-host-first`: the
  decorative icon is hidden, the host is set at 10 px and may take the whole row,
  the label can vanish while the link stays clickable through the host (the label
  stays in the accessible name).
  The list is `tabindex=-1` (Chrome would otherwise make a scrolling list an
  unnamed tab stop); PageUp/PageDown on the focused window scroll it.
- **Expand from the page menu** (« Afficher en fenêtre / en capsule », PM
  decision): the new box comes from `placeFor` → `freeBoxNearest` (final
  follow-up N2): the safe area is rasterised in 2-unit cells, every visible
  object (grown by 1 unit) and the face zone mark the cells they touch
  (conservative, never a false « free »), a 2D prefix sum answers each candidate
  box in O(1), and the free box whose centre is **nearest the anchor** (what the
  object explains, else its parent or star, else its current place) wins, ties by
  y then x. Work is bounded by the safe area (≈ 10 000 cells), not the object
  count: ≈ 1 ms warm on QA's dense scene and on 510-object scenes. Only when no
  free box exists does it fall back to the AutoResolver's least-overlap search
  with the other objects as obstacles. When the only free space is across the
  face, the window goes there and its link crosses the face (nearest free wins). Shrinking to a
  point keeps the centre. Drags and brain geometry stay authoritative (decision 9).
- **Orphan artifacts** (PM decision): the menu of an artifact or star offers
  « Archiver les artefacts orphelins (N)… » when some artifact explains no active
  object; the confirmation gives the count, up to three titles and « Les artefacts
  encore reliés à une étoile restent. », then one `archive_many` (re-validated by
  the domain, `not_bulk_archivable` → recomputed once). The « travaux terminés »
  confirmation says how many artifacts it will leave without a link.
- **Links and menus:** right-click on an item link keeps the browser's native menu
  (copy address); anywhere else in a node, the scene menu.
- **Edge:** an artifact's `explains` line is drawn dashed in the artifact's colour
  (`sc-link-artifact`), a signal's line keeps its signal style.
- **Keyboard:** one tab stop into the scene is kept. The origin button and item
  links have `tabindex=-1` until focus enters their node (`focusin`), then `0`,
  so Tab walks into the focused window's links and out of the scene; they return
  to `-1` when focus leaves the node. Escape on a link returns focus to its node.
  Pointer-down on a link or the origin button starts no drag and no menu (native
  click).
- **Archive confirmation** of a star says how many artifacts stay (« Son artefact
  reste dans la scène, à archiver à part. »), from `artifactsExplaining`; the bulk
  confirmation says artifacts stay.

**URL policy** (Slice 07, `linkOf`). Slice 05 rendered item URLs as text only. An
artifact is where the user returns to a research result, and copying from a
draggable, `user-select: none` node is impractical, so validated URLs become
openable links. An item URL becomes `<a>` only when:

- the raw string is an absolute `http:`/`https:` URL (the domain already refuses
  other schemes and non-printable characters in `url`) with no whitespace, C0/C1
  control, bidi mark or isolate, or invisible character;
- `new URL()` parses it, the protocol is still `http:`/`https:`, it has **no
  username or password** (`https://bank@evil/` shows a false host) and a non-empty
  hostname;
- `href` is the parser's normalised form (international hosts in punycode) and is
  checked again for `^https?://` in the page before assignment.

The link is built with `document.createElement('a')`, `href` set as a property,
`target="_blank"`, `rel="noopener noreferrer"`, `referrerpolicy="no-referrer"`,
label through `textContent`. The **host is written before the label** in its own
non-shrinking element; when the row is too narrow, `fitHosts` shortens it **from
the left** with `hostTail`: `…` plus the **longest suffix that fits** (a leading
dot dropped), so a narrow row shows `…ogin-check.co.uk` rather than `…co.uk`
(final follow-up N1: cutting on label boundaries could show far less than the
room), never `docs.python.org…`; measured from the element's font and re-checked
against the row's `scrollWidth`. The full host is in the link's accessible name and in the
tooltip (`title`); the model never pre-truncates it (URLs are bounded at 2 048 by
the domain). A long label or ref shrinks instead. `javascript:`, `data:`, `file:`
and credentialed URLs stay text. No `innerHTML`, no `setAttribute('href')`
(asserted).

**Motion.** Only compositor properties move: node `transform` (0.42 s ease-out,
enabled after the first placement so nothing slides in from the origin), ring
opacity and scale loops, label fade. A size or representation change is
immediate. Any running CSS animation costs a style recalculation per frame (QA:
94 per second at 116 objects; measured 140 per second whatever the number of
rings), so ring animations are bounded twice: at most 24 at once
(`MAX_ANIMATED`: live high-urgency signals, then medium, then running stars), and
only during the 12 s after a node appears or its execution state, category or
signal link changes (`ANIMATE_FOR_MS`; nothing animates on the first render).
Other rings keep the same cue, static. At rest the scene runs no animation: idle
probe 30 style recalculations in 30 s with the scene on (≈200 objects), the same
as with the scene off. Rings are also paused while the tab is hidden.
`prefers-reduced-motion: reduce` removes every transition and animation (static
rings). There is no `requestAnimationFrame` loop: one render is scheduled per
state change, window resize or animation window expiry. Hover (label) is the only
reflex of this section; gestures, menus and archive are in *Scene user interaction*.

**AutoResolver** (`resolveLayout(state)`: pure, deterministic for the same
snapshot, independent of the window size).

1. Every visible object with a geometry is fixed and becomes an obstacle,
   whoever placed it: user pin, brain or user placement, or an already committed
   resolver placement. The resolver moves none of them. There is no nudge in V1:
   stable geometry across reloads and tabs outweighs re-optimising.
2. Visible objects without geometry are placed by anchor depth, then Core order.
   Anchor: a signal's star (its live `explains` link, otherwise the star with
   the same `work_ref`), a child's `parent_of` parent, an artifact's `explains`
   target. Depth walks anchors with a visited set: a cycle stops at the first
   repeated id, and depth is at most 64.
3. Default sizes: point 6 × 6, signal 4 × 4, capsule 40 × 7, window 64 × 40.
   Around a placed anchor, candidates sit on five rings of preferred angles (a
   signal touches its star at the top right, children go below the parent).
   Otherwise they follow a square spiral from a home point: stars left of the
   face at (−62, 0), results and windows right of it at (72, 0), groups at the
   centre. Points try a spaced lattice first, then a dense one. Only boxes
   inside the safe area x ∈ [−154, 144], y ∈ [−80, 80] (the frame minus chrome
   margins) are candidates.
4. The first box with no overlap at all (1 unit padding) and outside the face
   zone (±34) wins. Otherwise the cheapest wins: same-layer overlap × 1000,
   other-layer overlap × 4, face overlap × 8. Near an anchor a same-layer
   overlap is never accepted (the spiral is tried instead). Overlap across
   layers and with explicit placements is therefore allowed; the resolver never
   creates a same-layer overlap while free space exists.
5. Work is bounded: a 16-unit spatial grid, candidates computed once per
   (home, size), a cursor that skips candidates already known not to be free, at
   most 1 200 candidates per lattice, and a budget of 400 000 box comparisons per
   pass (beyond it, each remaining object takes its first admissible candidate).
   Tests place 504 objects with no same-layer overlap under budget, and bound a
   pathological scene of 256 windows on one spot.

**Commit policy** (PM decision: resolver placements persist). The browser commits
`{op: set_geometry, object_id, geometry, placed_by: resolver}` through
`POST /api/scene/commands`, whose actor is forced to `user`, the only actor the
reducer accepts for `resolver`.

- Only the **leader** commits: the tab holding the profile's Web Locks lock
  `jarvis.scene.leader`, the same lock that owns the long-poll (see *Page
  loop*). In `solo` mode the tab commits alone. Followers render the same
  deterministic placement and send nothing.
- Only while the loop is **polling after a healthy read**, never during a
  snapshot reload, when the held state may be stale.
- After a settle delay (600 ms plus up to 400 ms of jitter), at most 32 commands
  per batch, one at a time. Just before each send, the object is re-read in the
  latest state: if a patch placed it meanwhile, it is not sent.
- The ledger keeps at most 2 048 entries; beyond, the oldest are evicted (an
  evicted object still unplaced in a very long session could be sent once more,
  which answers `duplicate` or `explicit_placement`).
- **Once per object per page**, through a ledger keyed by `scene_id` and
  `object_id`:
  - a domain answer (`applied`, `duplicate`, `rejected_authority` such as
    `explicit_placement` or `pinned_by_user`, `invalid`) or a form error
    (400, 403, 413, 502) is final;
  - 503, 504 or a network error (not applied, or outcome unknown) retries the
    same box after 2 s, then 8 s, three sends at most, and pauses every send in
    the meantime (8 s after giving up).

  Resending the same box is safe: an applied one comes back `duplicate`, and a
  box placed by someone else comes back `explicit_placement`.
- A later tab or a reload sees the committed geometry in the snapshot and sends
  nothing. Browser run (Slice 05 LOG): 506 objects placed, 506
  `scene.command set_geometry` journal entries, and none after reloads, a Core
  restart or a second tab.

Residual risks: two browsers that share no lock (two profiles or two machines)
and hold different revisions can each commit a different box for the same object;
the later one is accepted as a resolver nudge: one visible move, no loop, since
each page commits an object only once (QA with a 3 s delayed profile: no move
observed). A leader whose event loop stalls while it stays visible and keeps the
lock stalls commits until it resumes, and its followers can be up to about 40 s
behind Core (follower watchdog, see *Page loop*; QA `stall` scenario: render
delays 4.7–34.8 s, 0 commits while stalled, the 3 pending commits applied on
resume).

**Page loop** (`createSceneLoop`, Slice 05 QA rework): **one scene long-poll per
browser profile**, not per tab. Browsers allow about six HTTP/1.1 connections
per host; with one long-held request per tab, six visible Control Center windows
stalled `/api/status` for 16–24 s (QA). Roles:

| Role | Who | Network |
| --- | --- | --- |
| `leader` | the visible tab holding the Web Locks lock `jarvis.scene.leader` | snapshot, then the long-poll `GET /api/scene/patches?…&wait_s=25` (40 s deadline); broadcasts on `BroadcastChannel('jarvis.scene')` |
| `follower` | every other visible tab of the profile, queued on the lock | no long request: `GET /api/scene` on first load or resync, `GET /api/scene/patches?…&wait_s=0` (answered at once, 15 s deadline) to catch up |
| `solo` | fallback when Web Locks or BroadcastChannel is missing | per-tab long-poll, as before (documented limit: about six windows) |

One lock covers both the long-poll and the resolver commits: commits need the
freshest state, which only the long-poll holder has, and a single lock gives a
single handover. The lock is requested with `ifAvailable` first (the role is
known before the first request, so no request is wasted), then queued. A tab
releases it when hidden (a frozen page is hidden first), when the gate switches
off, and on `pagehide`; the browser also drops it when the tab closes or
navigates. The next queued visible tab gets it at once.

Messages (`v: 1`, sender id; any other shape is ignored):

A lock granted while the tab is hidden or the scene is off (the queued request
raced a visibility change) is given back at once: the tab stays follower and
journals `scene.leader_declined` to the console (`createLeadership`, pure, tested
with a fake Web Locks implementation).

- `patches` `{scene_id, epoch, body}`: the leader's patch response, sent after the
  leader applied it. A follower applies it with
  `JarvisSceneClient.applyPatchResponse` (late duplicates skipped); a gap,
  another epoch or a refused patch makes it catch up.
- `tick` `{scene_id, epoch, revision, health, objectLimit}`: after every
  snapshot, every long-poll answer (at least every 25 s) and every back-off. A
  follower behind that revision, epoch or scene catches up; a degraded leader
  health is mirrored, so every window shows the same outage indicator.
- `health` `{health}`: the leader's state before it holds any scene.

Catch-up is a short patch read from the held revision; `resync_required` (ring
too short, Core restarted) turns it into a snapshot read. A follower busy with a
read, or hidden, records the target revision and catches up when the read ends or
the tab becomes visible. The follower watchdog checks every 5 s, independently
of the follower's own reads: after 35 s without any leader message it makes one
short read, then none until another 35 s of silence has passed; a leader that
keeps ticking never triggers a read. A follower is therefore at most about 40 s
behind Core when its leader hangs while visible (fake-timer test on QA's
timeline: 39 s). On handover the new leader polls from its held
revision, so Core's patch ring returns whatever the old leader never
broadcast: no gap.

| Phase | Entered when | Does |
| --- | --- | --- |
| `off` | gate off | nothing; state forgotten, in-flight request aborted |
| `paused` | `document.visibilityState` is hidden | aborts the request; no request |
| `loading` | start without state, or resync | `GET /api/scene` (15 s deadline) |
| `polling` | leader or solo, snapshot accepted, patches applied | long-poll through `JarvisSceneClient.applyPatchResponse` |
| `following` | follower up to date | nothing; applies broadcasts |
| `catching_up` | follower behind | short patch read |
| `waiting` | `retry` or failure | timer, then back to the interrupted read |
| `stopped` | `pagehide` (not a bfcache entry) | aborts everything |

- `applied`, `unchanged` or `more`: poll again at once (leader), or back to
  `following`.
- `retry` (`patch_waits_busy`): wait `retry_after_ms` plus up to 250 ms, keep
  the state, no snapshot.
- `resync` (epoch or scene changed, gap, refused patch, `resync_required`): read
  the snapshot; after more than two resyncs in a row, back off first.
- `unavailable`, or a failed request (network, timeout, non-200): health becomes
  `degraded`, with back-off 1 s, 2 s, 4 s … 30 s at ±25 % jitter; the last state
  stays on screen, and the first success restores health.
- `/api/status` failing then succeeding again (`JarvisScene.statusLost`, then
  `gate`) cancels the pending back-off and reads at once (`retryNow`, at most
  every 2 s), so a Control Center restart does not wait up to 37 s.
- Changing role aborts the in-flight request and restarts from the held revision.
- A generation counter drops the answer of any aborted or superseded request.

Measured (headless Chrome, one profile, 1280 × 720 windows): at 5, 6, 8 and 10
visible windows, `/api/status` fetched from the first and last window took 2–8
ms; exactly one window was leader; every window reached Core's revision with an
identical layout; switching the gate off or on reached all ten windows within
1.2 s. Leader closed, navigated away, minimised or frozen during a 40-command
burst: a new leader within 1.7 s (burst included), every remaining window's DOM
equal to Core's visible objects. Details: Slice 05 LOG › QA rework.

The loop coexists with the 1 s `/api/status` and `/api/work` polls. Transitions,
never individual polls, go to the browser console as `[scène]` events:
`scene.view_degraded`, `scene.view_restored`, `scene.resync`,
`scene.snapshot_loaded`, `scene.loop_paused`, `scene.role`,
`scene.follower_watchdog`, `scene.retry_now`, `scene.resolver_committed`,
`scene.resolver_commit_refused`, `scene.resolver_commit_retry`. The Control
Center journal already records read outages (`scene.view_unavailable`,
`scene.view_restored`) and every relayed command (`scene.command`). The page has
no client-log route, and none was added. `JarvisScene.gate` runs in its own
`try` inside `refreshStatus`: a scene error is logged
(`[scène] scene.gate_failed`) and never breaks the status display.

**Status indicator** (bottom left, on the voice hint's line, outside the
composition safe area; raised above the Barehands badge when it is shown; chips
wrap upwards, two rows at most in practice, never blocking): loading; "Scène
figée · <raison>" plus a muted "N s · réessai N s" that is never truncated (a 1 s
ticker runs only while degraded); "Scène pleine — archiver des travaux terminés"
with "n/512", a button that opens the bulk archive confirmation (Slice 08); "N objets masqués", a button
listing hidden objects to show them again (Slice 08); "N signaux d'échec sous des fenêtres"
and "N signaux à vérifier sous des fenêtres"; "N objets hors champ". The visible chips
are not a live region. A separate visually hidden `role=status` region announces
state changes only ("Scène figée · Core injoignable. Nouvel essai automatique.",
"Scène pleine…", "Des signaux sont cachés sous des fenêtres.", "Des objets sont
hors champ."), never the counters.

**Keyboard.** One tab stop into the scene (roving `tabindex`): the last focused
node, else the first in spatial reading order (Slice 07: inside a focused artifact
window, its origin button and links follow in tab order). Arrow keys move to the nearest
node in that direction (`nextFocus`, transverse distance weighted twice), Home and
End to the first and last, Escape leaves (blur). A focused point shows its label.

### Scene user interaction

Handoff Slice 08 (implementation, then QA rework). The user acts on the same
scene model as the brain (decision 15): every gesture is a
`POST /api/scene/commands` call (actor `user`, set by the Control Center),
reconciled to the revision Core returns. Nothing is decided in the browser that
Core does not re-check.

Files:

- `jarvis/runtime/control_center_scene_interact.js` (`window.JarvisSceneInteract`,
  pure, node-tested in `tests/unit/test_scene_interaction_logic.py`):
  - geometry: drag, resize, keyboard steps, representation change, clamped to
    the **composition safe area** in whole units;
  - drag threshold per pointer, key intents, menu model;
  - bulk selection (parity with the domain rule), `archive_many` chunking;
  - command builders, response and transport classification in French;
  - stop outcomes, focus after a removal;
  - layered optimistic overlay (`createPending`), resolver commit layout
    (`commitLayout`), hidden list.

  It is injected at `/*__CONTROL_CENTER_SCENE_INTERACT_JS__*/`, between the
  layout and page modules.
- `jarvis/runtime/control_center_scene_page.js` browser block:
  - pointer, keyboard and context-menu listeners on the scene container (delegation);
  - preview while the hand is on an object, commits, toasts;
  - the actionable status chips, the stop pending state, the second live region.
- `jarvis/runtime/control_center.html`:
  - the existing context menu becomes a generic component,
    `showMenu({title, items, pos, origin, run})`, with the same keyboard
    (arrows, Home, End, Escape, Tab, ContextMenu / Shift+F10). `openMenu` for
    agent cards is a thin wrapper;
  - items may be a `note` (focusable, `aria-disabled="true"`, announced, inert
    on Enter);
  - an in-page modal confirmation, `confirmDialog({title, lines, confirmLabel,
    cancelLabel, danger})`, returns a promise. See *Confirmation* below.

  The page no longer calls `window.alert` or `window.confirm`.

| Gesture | Keyboard equivalent | Command(s) | Refusal / failure |
| --- | --- | --- | --- |
| select (click, focus); the grip of a selected capsule or window stays visible without hover | Tab into the scene, arrows (roving `tabindex`, Slice 05) | none | — |
| drag a node (4 px threshold for a mouse, 10 px for touch, pen or a Barehands token) | Shift+Arrow (2 units), Ctrl+Shift+Arrow (10) | `pin` then `set_geometry`; for an object without geometry: `set_geometry`, `pin`, `set_geometry` again (a `duplicate` if nothing moved in between). `commitGeometry` confirms the optimistic layer only after the **last** step, at the highest revision returned, so the preview never snaps back to the origin when the pin patch arrives first | both steps rolled back (compensating `unpin` when needed), toast |
| drag the corner grip (capsule, window) | Ctrl+Arrow (±2 units on w/h) | same as drag: every user geometry edit pins (decision 9, PM decision in the QA rework) | same |
| menu › Afficher en point / capsule / fenêtre | menu | `set_representation` with the new default size around the same centre | rolled back, toast |
| menu › Épingler ici / Désépingler | menu | `pin` / `unpin` (the drawn place is committed first when the object had none) | rolled back, toast |
| menu › Masquer | menu | `set_visibility hidden`; toast offers to show it again; the selection moves to the reading neighbour | rolled back, toast |
| chip « N objets masqués » › Afficher / Tout réafficher | chip is a button | `set_visibility visible`, one per object (≤ 512); the first object shown is selected | count of failures in a toast |
| menu › Archiver… (confirmation) | menu | `archive` (Core cascades the star's runtime signals); short confirmation toast; selection moves to the neighbour | rolled back, toast |
| menu › Archiver les travaux terminés (N objets)… or the « Scène pleine » chip (confirmation with counts) | menu / chip button | `archive_many` (one command in practice) | whole selection rolled back; `not_bulk_archivable` → counts recomputed and confirmed again once, then a toast offering « Cliquer ici pour réessayer » |
| menu › Arrêter la tâche… (job stars only, confirmation) | menu | `POST /api/jobs/cancel`; the star shows « arrêt en cours » until Core says it ended, or until the relay deadline | toast with Core's outcome in French |
| right click, ContextMenu, Shift+F10, long press (550 ms), click on the already selected object | ContextMenu / Shift+F10 | opens the menu | — |
| Escape | Escape | cancels a drag or keyboard edit, closes a menu or dialog, then leaves the node | — |

Keyboard edits:

- preview immediately;
- commit when the modifier is released, on blur, or after 700 ms without a key;
- Alt+Arrow and Meta are never intercepted (browser navigation).

**Safe-area clamp** (PM decision, QA rework). Drag, keyboard move, resize and representation changes keep the whole box inside `SCENE_SAFE_AREA` (x −152…138, y −72…68), so a user can no longer park an object under the page chrome.

- The limits are the same as the resolver's: a parity test covers the domain, the renderer and the interaction module.
- A window is at most 290 × 140 units and a capsule at most 160 × 10.
- An object the brain placed outside the safe area enters it at the first user edit.

**Optimistic display.** `createPending` keeps one **layer per operation**, in send order, drawn as `pending.overlay(heldState)`.

- `rollback(token)` removes that layer only, so a refused newer change never undoes an older accepted change that has not been received yet. No pin flicker.
- A layer disappears when the held state reaches the revision Core returned for it, when Core refuses it or the call fails (`rolledBack`), or after 30 s unconfirmed (`[scène] scene.user_change_unconfirmed`).
- While the hand is on a node (drag, keyboard edit), the renderer does not reposition it (`record.dragging`), and transitions are off for that node.

**Resolver commits use the held state only.** `pushCommitter` passes `serverLayout()`: the layout of the state Core confirmed (`commitLayout`), not the drawn overlay. A place freed only by a pending change (a move or archive that may still be refused) is never committed to another object. With nothing pending, the drawn layout is reused, so there is no second computation.

QA's repro `s8r_b3c.py`:

- before the fix: a new object took the optimistically freed box, and a rollback left a 100 % overlap (2 560 units²);
- after: the new object went elsewhere, overlap 0.

**Tabs.**

- User commands are sent from whichever tab the user acts in, leader or follower. The follower's change reaches other tabs through the leader's long-poll and broadcast.
- A committed user geometry is never a resolver candidate again, and Core refuses a late resolver commit on it (`explicit_placement`).

**Confirmation** (`confirmDialog`). While it is open:

- the other children of `body` are `inert`, except the Barehands overlay: no click, no focus, no scene gesture, no clickable toast. A `MutationObserver` applies the same rule to children added while the dialog is open (a toast container, an overlay), and is disconnected on close;
- one window-level capture listener takes every key. Escape cancels, even with focus on the dialog body. Tab and Shift+Tab stay on the two buttons. Enter or Space activate the focused button, and every other key is swallowed, so no UI shortcut passes;
- a click on the dialog body keeps focus on the dialog.

Measured: the « s » (settings) shortcut, Shift+Arrow on the node behind and a click behind the backdrop produced 0 commands and left settings closed; Escape from the body closed the dialog; focus came back to the node.

**Focus and announcements.**

- Archiving, hiding or bulk-archiving moves the selection to the next object in reading order (`focusAfterRemoval`), else the previous one, focused as soon as it is drawn.
- Showing hidden objects selects the first one shown.
- A second, visually hidden `role=status` region announces action outcomes (« … archivé. », « … masqué. », « Arrêt de … demandé. »), separate from the reading-state region.

**Menu model** (`menuModel(state, objectId, {title, finished})`):

| Object | Entries |
| --- | --- |
| any | the two other representations; Épingler ici or Désépingler; Masquer; Archiver… |
| execution star with runtime signals | « Archiver avec son signal… » (or « avec ses signaux ») |
| `job` star with `work_ref.source = job`, running / pending / blocked | Arrêter la tâche… |
| `agent` star (or `job` of another source), running / pending / blocked | note « Arrêt impossible : sous-agent du brain » (focusable, `aria-disabled`) |
| execution star or runtime signal, when bulk selection is not empty | Archiver les travaux terminés (N objets)… (same noun as the confirmation button) |

**Barehands.**

- Its pointer replays `pointerdown`, focus, `pointerup` and `click` on the element under the token, with no drag.
- A click on the already selected object opens its menu, and so does a long press.
- A gesture from its pointer (`pointerId` 9001, or a token on screen) needs 10 px before it becomes a drag, so a trembling long press never moves and pins.
- Menu items, chips and dialog buttons are ordinary buttons.

**Errors.**

- Every command answer goes through `classifyResponse` and `transportFailure`:
  - domain refusals come back in the user's words (`REFUSALS`);
  - transport failures use French sentences keyed on the Control Center code, with the Slice 03 distinction:

    | Code | Meaning |
    | --- | --- |
    | `command_not_sent`, `core_unreachable` with « non envoyée » | nothing was sent |
    | `core_timeout`, a lost link, an unreadable answer | outcome unknown |
    | a `fetch` with no HTTP answer (reset after sending, page deadline) | outcome **unknown**, never « rien n'a été envoyé » |

  - the raw text (English, host, port) only goes to the console (`scene.user_command_detail`).
- Each refusal or failure is a toast plus a `[scène] scene.user_command_refused` console event. Toast details wrap (up to three lines) instead of being cut on one line.
- An unexpected page error during an action (a rejected promise) is a toast too (`actionFailed`), never only a console line.
- Successful actions log `scene.user_moved`, `scene.user_resized`, `scene.user_archived`, `scene.user_bulk_archived`, `scene.user_stopped`, `scene.user_shown` and `scene.user_key_edit`.
- The Control Center journal records every relayed command (`scene.command` / `scene.command_failed`) and every stop (`scene.work_cancel`, `scene.work_cancel_refused`, `scene.work_cancel_failed`).
- `JarvisScene.inspect()` adds `pending`, `actions`, `gesture` (with its threshold), `selected`, `stopping` and `jobCancelTimeoutS`.

**Rendering of a capsule in a larger box** (QA rework). A brain `set_representation capsule` on a user-pinned window keeps the window's stored box, which used to be drawn as a giant capsule. `drawnBox` now draws a capsule whose box is taller than `CAPSULE_MAX` (160 × 10 units) at a capsule's natural height, and at most 160 units wide, centred in the stored box. A point was already drawn at its size, centred. This is render only: the stored geometry does not change.

**Archive cascade** (domain, `jarvis/domain/scene.py`; see `docs/scene-model.md` › *Archive cascade and bulk archive*). A user `archive` of an execution star archives, in the same patch and revision, every runtime signal whose owner is that star.

- The owner (`signal_owners`) is the target of the signal's live link; otherwise it is the active star with the same `work_ref` source and external id, which is how retired signals are found.
- Signals come first in the patch, so the star's tombstone is the newest and the last evicted. While it lives, the projector skips the star and its signal (`skipped_archived`, no refusal journaled).
- Brain and user `attention` objects are never cascaded.

**`archive_many`** (user-only `SceneOp`, absent from the brain matrix and the display MCP catalog) takes `object_ids`: 1 to 512 unique ids.

- Each id is re-validated by `bulk_archivable`. Accepted: an execution star in a terminal state (`completed`, `cancelled`, `failed`, `interrupted`); a runtime signal whose owner is selected and terminal; an orphan runtime signal.
- Already archived ids are skipped.
- An unknown id (`unknown_object`), or any other object (`not_bulk_archivable`), refuses the whole command.
- The command produces one revision, cascade included.
- Patch ops reuse `archive_object` and `delete_relation`; `MAX_PATCH_OPS` is now 512 + 1 024 = 1 536.
- The browser sends the terminal stars and orphan signals it sees, chunked under 512 ids and 48 KB of body.
- **The Control Center answer to an `archive_many` omits the patch** (`patch: null`, `patch_omitted: true`). It can weigh up to about 8 MiB (QA measured 8.2 MiB), and the page only reads the outcome and revision; the patch still reaches the page through the long-poll. Other ops keep their patch, and the brain's MCP path talks to Core directly and is unaffected.
- Measured at 512 objects: one `archive_many` (revision 1067 → 1068) removed 22 stars and their 6 signals, and the 20 creations the projector had deferred were caught up.

**Job stop route.**

```text
menu › Arrêter la tâche (job star, work_ref.source = job)
  └─ POST /api/jobs/cancel {source, external_id}      Control Center, origin guard, strict body ≤ 4 KiB (413 beyond)
       ├─ source ≠ job → 409 not_cancellable, Core not called
       └─ CoreSceneView.cancel_work → POST /v1/work/cancel {schema_version: 1, source, external_id}   bearer token, body ≤ 4 KiB (413)
            ├─ source ≠ job → 409 not_cancellable; unknown or speculative job → 404 not_found; malformed → 400
            └─ JobService.cancel_for_user(job_id) → cancel(job_id); waits ≤ 5 s for the job to end
                 → 200 {source, external_id, outcome: cancelled | cancel_requested | cleanup_unknown | already_terminal, status}
                 → the job's `cancelled` observation reaches the scene through the projector
```

- **Exactly one job.** `cancel_for_user` stops exactly one job, the one behind the star. It never touches the brain work item that may have requested it; that item's end comes from its own observations.
- **Why not `cancel_work`.** `JobService.cancel_work(work_id)` cancels every job linked to one brain `work_id`, and never reaches `back_brain` jobs (they have no `_links` entry), so it was not reused as such. `cancel_for_user` calls the same primitive, `cancel(job_id)`, and journals `core.job.user_cancel` (info).
- **Concurrency** (QA rework, MAJOR-1):
  - **Before:** two concurrent stops, or a stop racing the brain's `cancel_work`, called `task.cancel()` twice. The second call interrupted the write of `cancelled` in `_execute`, and the job stayed `running` for good (10 of 10 through the Control Center).
  - **Idempotent cancel.** `cancel(job_id)` is now idempotent: `_cancel_requested` means `task.cancel()` is called once.
  - **Atomic terminal settlement** (final fix, MAJOR-R1). Every terminal outcome (`cancelled`, `failed`, `completed`) is settled by `_settle_terminal`: persist, publish the `job.*` event, observe the work, in its own task awaited under `shield`. Any cancellation that arrives meanwhile is absorbed until settled, then re-raised. Before, a stop that landed inside the failure handler (lock wait, publish, observe) aborted it: `failed` was never written or observed, and the job stayed `running` (QA: 10/150 unhooked, 4/4 injected).
  - **The worker's outcome wins** (PM decision). Once the worker returned its result or raised its failure, that outcome is final: a stop racing it never writes `cancelled` over it, never drops the result or the `job.completed` event, and never makes a second terminal write. `cancel_for_user` then answers `already_terminal` with the real status (`completed`, `failed`); the page says « La tâche s'était déjà terminée · Elle a fini normalement / en échec ». Only a cancellation that reaches the worker before it produced its outcome ends `cancelled`.
  - **Stop before the first step.** A job stopped before it ever started (`_started`) is never executed and ends `cancelled`.
  - **Coverage.** Tests cover two concurrent user stops, `cancel_work` plus a user stop, a stop before the first step, a raw second cancel during the write, two stops of an owned `back_brain` job, a cancellation during the terminal settlement of a completion or a failure at each point (lock wait, after the write, during publish, during observe), a user stop that read `running` just before the worker's outcome, a bounded unhooked timing sweep, and Core `stop()` during a settling terminal write. QA's HTTP repro gives 10 of 10 `cancelled`; QA's `unhooked_sweep` gives 0 stuck over 150 trials each for failure and completion.
- **`cleanup_unknown`.** An owned `back_brain` job whose execution cleanup is not confirmed answers `cleanup_unknown` (job still `running`, `cancellation = cleanup_unknown`). The page says « Arrêt demandé, nettoyage non confirmé », never that Core is finishing.
- **Stop pending state.** While a stop is in flight, the star has a spinning dashed orange ring (static with reduced motion). A chip « Arrêt de « … » en cours » shows a live seconds counter. The state ends when the held state shows a terminal status, or at the relay deadline, which is then said in a toast (« Arrêt non confirmé … après N s »). The deadline is the real one: `/api/status` gives `scene_limits.job_cancel_timeout_s` = connect (3 s) + `WORK_CANCEL_TIMEOUT_S` (20 s) + 1 s, or `null` without Core.
- **Route location.** The Control Center route lives under `/api/jobs`, not `/api/work`: `/api/work` stays read-only, because the UI never writes work state; the job's own observation does. A test pins an allowlist: the only UI route that affects work is `POST /api/jobs/cancel` (`source = job`), and no UI route observes or ingests work.
- **Relay failures** are classified like commands (`command_not_sent`, `core_timeout`, `core_unreachable`, `invalid_scene_response`); 400, 404, 409 and 413 from Core are relayed with their code.


## Telemetry

Six latency measures are defined in `jarvis/core/latency.py` and emitted through
`DiagnosticSink` / `RuntimeJournal`, which means they land in
`runtime/trace.jsonl` and are visible in the Control Center **TRC** panel. Each
event carries `measure` and `elapsed_ms` in `data`, so one filter finds all six.

| Measure | Event kind | Join key |
| --- | --- | --- |
| `speech_started -> surface_first_audio` | `voice.latency.surface_first_audio` | `segment_id` |
| `transcript_completed -> brain_turn_accepted` | `voice.latency.brain_turn_accepted` | `correlation_id` |
| `brain_speech_requested -> first_brain_audio` | `voice.latency.first_brain_audio` | `speech_id` |
| `user_interrupt_detected -> local_output_stopped` | `voice.barge_in` (`stop_latency_ms`) | `speech_id` |
| `brain_work_started -> first_public_progress` | `core.brain.latency.first_public_progress` | `work_id` |
| `brain_work_started -> completed` | `core.brain.latency.work_completed` | `work_id` |

Both bounds of a measure are always taken in the same process with a monotonic
clock; no measure crosses the Core/Voice boundary. `LatencyTracker` builds its
own message from the measure name, so a caller cannot smuggle transcript content
into it.

## Sub-agent routing

The brain is a CLI process (`claude -p --input-format stream-json`). It spawns
its own sub-agents with the `Agent` tool and picks their `model` itself. Jarvis
never builds that launch, so a system prompt can *ask* for a model but cannot
*impose* one. Routing therefore has two halves, and only the second is binding.

**Intent** — the brain names a task profile, not a model. The system prompt
(`routing_hook.PROFILE_RULE`, appended to `BRAIN_SYSTEM_PROMPT`) asks it to start
each sub-agent description with `[code]`, `[desktop]`, `[fast]` or `[general]`.
An absent or invented marker means `general`; the text is never interpreted to
guess a profile, because guessing would hand the choice back to the model.

**Resolution** — a `PreToolUse` hook, declared to the CLI with `--settings` at
launch, sees every `Agent`/`Task` call before it runs. It resolves the profile
against the saved policy and rewrites `model` (`updatedInput`) when the model
the brain asked for is not allowed. This is the only point in the system where
an allowlist can actually bind.

| Piece | File | Holds |
| --- | --- | --- |
| Contracts | `jarvis/domain/routing.py` | profiles, policy, candidates, decision, refusal codes. No I/O, no provider, no model id |
| Persistence | `jarvis/runtime/agent_routing.py` | tolerant read, strict atomic write, candidates built from `cli_catalog` + `model_catalog` |
| Enforcement | `jarvis/runtime/routing_hook.py` | the hook, its declaration, and the routing trace |

Decisions are deterministic: the order of a profile's candidate list *is* the
preference, and the first allowed-and-usable candidate wins. There are no
weights and no cost estimates — providers publish no comparable figures, and an
invented number would be worse than an assumed order.

Conduct under doubt: policy off or profile empty → the hook stays silent and the
CLI keeps its own model (today's behaviour); model outside the policy → rewritten
rather than refused, so the work still happens; no usable candidate → explicit
refusal; hook failure → silence, because a broken policy must not paralyse the
brain.

Capabilities (`code`, `semantic`, `computer_use`, `background`, `streaming`,
`sandbox`) are declared on the CLI spec, not on the model: the agent is what
executes. `claude` declares `computer_use` because it is launched with
`--chrome`; it drives the browser, not the whole desktop. No agent for full
desktop/office work is integrated, and none is faked.

Each decision is journalled as `agent.routing.decided` with the profile, every
candidate's verdict code, the requested model and the resolved one — enough to
explain a wrong choice, and nothing resembling reasoning.

## Self-development: two planes

Jarvis can change its own code, never where it runs.

- the **serving plane** is the primary checkout, the one Core, the UI and Voice
  run from right now. No agent writes there;
- the **build plane** is a set of sibling git worktrees (`../sub-agents`, also
  spelled `sous-agents`; `JARVIS_WORKTREE_ROOT` overrides). Everything happens
  there: editing, tests, commit, pushing a candidate branch.

A folder proves nothing. `jarvis/runtime/worktrees.py` asks git for the common
repository directory of each candidate and rejects anything that is not a
worktree of *this* repository, is dirty, has vanished, or is already leased.
Leases live in the serving plane's `runtime/worktree-leases/`, so borrowing a
worktree never dirties it; a lease whose owner is dead is taken over, and a
lease that was reassigned is never released by its former holder.

`jarvis/runtime/self_dev.py` runs one job: lease a worktree, fetch `main`, open
`selfdev/<job>`, run the coding agent chosen by the routing policy with `cwd`
fixed to that worktree, require a non-empty diff and green tests, commit, push,
release the lease — including after a failure. It produces a candidate. It
deploys nothing.

## Deployment transaction

Merging is not deploying. `jarvis/runtime/deployment.py` treats integration as a
transaction that is only finished once the code answers.

1. **Integration lock** — many jobs build, one integrates.
2. **Serving-plane guards** — dirty, on another branch, or diverged: stop.
   Unvalidated human work outranks an automatic deployment.
3. **Reconciliation** — the candidate merges the newest `main` inside its own
   worktree. A conflict aborts the merge and sends the candidate back to its
   job; nothing is ever auto-resolved.
4. **Gates replayed** — after reconciliation it is no longer the code that was
   validated, so the tests run again.
5. **Integration** — fast-forward push only, straight from the worktree to
   `refs/heads/main`. No force push.
6. **Serving update** — `merge --ff-only` in the primary checkout.
7. **Reload** — the supervisor stops its children and re-execs itself, so no
   module of the old revision survives. Continuity comes from persistent
   Core/task state on disk, not from keeping processes alive.
8. **Health** — the deployment is marked `committed` only once Core answers
   ready. Otherwise the serving copy is detached back onto the last known-good
   revision: no commit disappears, `main` keeps the faulty revision, and a human
   decides what to do with it. If even that would crush someone's work, the
   transaction stops as `blocked` and says so.

The durable marker `runtime/deployment.json` is written *before* the serving
plane is touched, which is what makes an interrupted deployment recoverable: the
next start concludes it from the file alone.

Nothing here is automatic until it is opened. `self_development.enabled` allows
building a candidate; `self_development.auto_deploy` allows shipping one, and
cannot be switched on by itself. Both are off on a fresh install.

Surface: `GET /api/self-dev` (gate, worktrees, leases, jobs, deployment),
`POST /api/self-dev` (open a job, returns at once), `POST /api/self-dev/deploy`
(integrate a job's candidate), `GET /api/routing/candidates` (measured agent +
model candidates with availability).

## Deliberate limits of this path

- Acoustic echo is handled in software since 11 September 2026 (WebRTC AEC3 plus
  the echo guard of `jarvis/audio/duplex.py`, report `docs/fixes/voice-duplex/`),
  but its margins — and the Solo Owner verification built on top of them — have
  only been measured in simulation and on synthetic voices: the workstation
  protocol `docs/HARDWARE_ACCEPTANCE.md` is still to be run. `legacy` remains the
  half-duplex fallback and the default.
- Gemini Live is not part of continuous mode.
- One brain, no multi-agent scheduling.
- The transport is still the direct OpenAI Realtime WebSocket; WebRTC plus a
  sideband control channel is future scope.
