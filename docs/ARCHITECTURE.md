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

`JARVIS_VOICE_ARCH` selects the code path. It is a deployment switch, not a user
preference, so it lives in `jarvis/v2_config.py` rather than in the Control
Center settings file.

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
addressing verdict (`addressed` / `uncertain`) and the public working state, as
produced by `BrainWorkingState.to_rehydration_payload()` — nothing else, and no
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

Provider-neutral ports live in `jarvis/ports/v2.py`: `BrainBackend`,
`RealtimeOutputControl` (`speak` / `cancel_output` / `truncate`, probed as an
optional capability rather than widening `RealtimeSession`), `WorkCanceller`,
`JobProgressSink`, `DiagnosticSink`. Brain events reuse the existing
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

`Jarvis Mute` stops the voice surface, never Core work, and never auto-wakes to
speak a result the user muted through.

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

- Acoustic echo is not handled in software. In continuous mode the microphone
  stays open while the speakers play; `legacy` is the half-duplex fallback and
  stays the default.
- Gemini Live is not part of continuous mode.
- One brain, no multi-agent scheduling.
- The transport is still the direct OpenAI Realtime WebSocket; WebRTC plus a
  sideband control channel is future scope.
