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
