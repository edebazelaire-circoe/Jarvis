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
panel) reach the agent with their text unchanged.

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

Its subscription is the one `CoreEventBus.subscribe(lossy=True)` in Core:
nothing re-subscribes the policy, so the default eviction of a saturated
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
