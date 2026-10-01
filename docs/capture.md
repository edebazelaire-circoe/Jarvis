# Capture owner (contract)

Explicit media capture of Jarvis — audio recording, screen recording,
screenshot — and its continuity guarantee (handoff
`jarvis-session-context-recording-runtime`, Slice 05; decisions D01, D11–D13,
D18, D-CAP). Media families plug into this owner: microphone in Slice 06,
desktop in Slice 07. HTTP/MCP (Slice 09) and the left toolbar (Slice 10) only
read and call it.

| Piece | Code |
| --- | --- |
| Capture value, states, transitions, error codes | `jarvis/domain/capture.py` |
| Ports (store, source, sink, registry, repair hook) | `jarvis/ports/capture.py` |
| Store | `jarvis/adapters/sqlite_captures.py` (`captures`, v7) |
| Owner | `jarvis/core/capture_service.py` (`core.captures` in `v2_app`) |
| Fake sources and failing storage (tests only) | `jarvis/adapters/fake_capture.py` |
| Microphone source, registry, WAV repair (Slice 06) | `jarvis/adapters/sounddevice_recording.py` |
| WAV PCM16 header (pure) | `jarvis/audio/wav_pcm.py` |
| Recording transcription (Slice 06) | `jarvis/core/recording_transcriber.py` (`core.transcripts` in `v2_app`) |

## Owner

`CaptureService` lives in **Core** and is the only status truth: state
machine, durable intent (table `captures`), finalization into the Artifact
registry ([artifacts.md](artifacts.md)), Session activity and reconciliation
after Core death. Core opens the sources itself (D-CAP). The Brain, MCP and
the Control Center are clients: none of them owns a capture's lifetime, and
an optimistic UI state is never truth (`status()` is). Capture does not depend
on interaction mode or Boards (D01, D06).

Production (`jarvis/app.py`, `_audio_recording_from_env`) installs the
microphone source for `audio`/`continuous` (`AudioRecordingSources`, below),
the WAV repair for the `audio` channel and the recording transcription
provider. `JARVIS_AUDIO_RECORDING=0` removes the microphone source (every
start refused `unsupported_source`, as before Slice 06). Other channels are
still refused until Slice 07 (`NoCaptureSources` when no registry is given).

## Capture

| Field | Rule |
| --- | --- |
| `capture_id` | `jcap_` + lowercase `[a-z0-9_-]`, ≤ 128 |
| `channel` | `audio`, `screen` (closed in the domain, no SQL CHECK: camera later = new value + source, D18) |
| `mode` | `continuous` (start/stop) or `one_shot` (screenshot) |
| `source`, `device` | short tokens (`microphone`, `desktop`, `fake`; `default`) |
| `state` | below |
| `created_at`, `updated_at`, `activated_at?`, `stop_requested_at?`, `ended_at?` | aware datetimes; `updated_at` never goes back |
| `jarvis_session_id`, `context_id` | Session and **active Context at start**, fixed for life |
| `artifact_id` | main media artifact, attached once during start |
| `error_code` | stable code (below); required for `partial`/`failed`, forbidden for `complete` |
| `stop_reason` | `user`, `source_lost`, `storage_failure`, `start_failed`, `core_shutdown`, `recovered`, `one_shot` |
| `gaps`, `bytes_written` | counts at the end (`status()` shows them live) |
| `data` | ≤ 16 small scalars (options, repair detail) |

Artifact kind: `audio`+`continuous` → `audio_recording`, `screen`+`continuous`
→ `screen_recording`, `screen`+`one_shot` → `screenshot`.

## States

```text
starting ──> active ──> stopping ──> complete | partial | failed
    │                      ▲
    ├──────────────────────┘ (stop requested while starting)
    └──> failed (start refused)          recovery only: starting|active ──> partial|failed
```

- `complete` only from `stopping`, only when the payload is final on disk and
  there was no error and no gap. Otherwise `partial` (bytes kept, with the
  reason) or `failed` (nothing usable). A crash never turns an incomplete
  payload into a silently `complete` artifact.
- **Stop is idempotent and single-flight**: concurrent stops await the same
  stop; a stop on a finished capture returns its final row; a stop while
  `starting` writes `stopping` at once, waits for the source start (bounded),
  then stops it — the capture never becomes `active` and no
  `capture.started` is written.
- Concurrency: **one open continuous capture per channel/device**
  (`already_active`, naming the holder, checked in memory, in the store
  transaction and by the partial unique index
  `idx_one_open_capture_per_device`). Different channels (audio + screen) and
  different devices run together. One-shot screenshots never conflict.
- Deadlines: source start ≤ 15 s (`source_timeout`), source stop ≤ 10 s
  (then finalized `partial`, `source_timeout`; the sink refuses any later
  write).

Start sequence: row `starting` → artifact `pending` (same Session/Context) →
row gets `artifact_id` → spool opened (storage refused here fails the start
**before** the device opens) → `source.start(sink)` → row `active` +
`capture.started` (one transaction). Stop: `stopping` → `source.stop()` →
spool finalized → artifact `complete`/`partial`/`failed` → row terminal +
`capture.stopped` (one transaction).

## Failure codes

`CaptureError.code` (HTTP status) when refused, or the durable `error_code` of
a `partial`/`failed` capture (copied on its artifact):

| Code | HTTP | Meaning |
| --- | --- | --- |
| `invalid_capture` | 400 | malformed id/value |
| `capture_not_found` | 404 | unknown capture |
| `already_active` | 409 | channel/device held (`capture_id` names the holder) |
| `source_unavailable` | 503 | device absent or failed to open |
| `permission_denied` | 403 | OS refused access |
| `source_timeout` | 504 | source did not start / stop in time |
| `source_lost` | 502 | device lost mid-capture |
| `storage_unavailable` | 503 | payload folder refused/unwritable at start |
| `storage_full` | 507 | disk full (ENOSPC, Windows 39/112) at open, write or finalize |
| `write_failed` | 500 | other write error |
| `finalize_failed` | 500 | spool could not be finalized (its `.partial` stays as evidence) |
| `unsupported_platform` / `unsupported_source` | 501 / 400 | no capture here / unknown source or channel |
| `recoverable_partial` | 409 | interrupted by Core death, bytes recovered |
| `capture_interrupted` | 409 | interrupted by Core death, nothing recoverable |
| `capture_gap` | 409 | evidence has a dated hole (`capture.gap`) |
| `capture_association_unavailable` | 503 | active Session/Context unreadable: no capture without association |
| `capture_service_stopping` | 503 | Core is stopping |
| `transcription_unavailable` / `transcription_timeout` | 503 / 504 | transcription of a recording waits (no provider, provider refusal or outage / attempt deadline); never a capture state, see *Transcription* |

`capture_invalid_transition` (409) is a code defect, never expected.

## Ports

- **`CaptureSource`** (one instance per capture): `payload_name`,
  `mime_type`, `async start(sink)`, `async stop()` (after it returns, no more
  writes), `health()`, `media_info()` (duration, dimensions). Raises
  `CaptureSourceError(code)`.
- **`CaptureSink`** (given by the owner, wraps the artifact spool):
  `write`/`write_at`/`sync` are synchronous disk calls, made from the source's
  writer thread — never from the device callback nor the event loop; they
  raise `CaptureSourceError` (`storage_full`, `write_failed`) and the owner
  stops the capture. `gap(reason, lost_ms)` and `lost(code, reason)` are safe
  from any thread. No silent loss: a bounded queue that overflows calls `gap`
  (D-AUDIO).
- **`OneShotSource`**: `async capture() -> OneShotResult(data, width, height)`.
- **`CaptureSourceRegistry`**: `continuous(...)`, `one_shot(...)`,
  `source_name(...)`; refuses with `unsupported_*`.
- **`CaptureRepair`** (per channel): `repair(RepairTarget) -> RepairOutcome`,
  synchronous, run in a thread at recovery. The target names the
  `.partial` and final paths and their sizes; the hook may only rewrite bytes
  in place (WAV header in Slice 06, video container in Slice 07), never
  create, rename or delete. An exception is logged
  (`core.capture.repair_failed`) and the evidence is recovered as it is.

## Session and Context

A capture is associated with the Session and **active Context at its start**
and keeps that association for life (artifact too).

- **Context switch mid-capture** (`create_context`, `activate_context`): the
  capture continues uninterrupted, keeps its start association, and a
  `capture.association_changed` event is written in the **newly active**
  Session/Context (`data`: `reason`, `started_session_id`,
  `started_context_id`), so a reader of the new Context knows a recording
  crosses it.
- **New Session mid-capture** (`start_new_session`): same rule — the capture
  continues, stays associated with the closed Session's Context, and the new
  Session's ledger gets `capture.association_changed` (`reason:
  new_session`). Rationale: a Session boundary is a conversation boundary
  (D02), not a recording boundary; stopping would cut evidence the human
  explicitly asked to record (D11), and only an explicit stop, a source loss,
  a storage failure or Core shutdown ends a capture.

Wiring: `SessionManager.add_association_listener` calls
`CaptureService.association_changed(reason)` after each committed
transition; a failure is logged, never raised to the transition.

## Continuity guarantee (V1)

The supervisor starts Core, then UI (Control Center), then Voice; Core's
death ends the whole tree (`supervisor_v2.py`); Voice and the Control Center
restart alone; the Brain is a child of the Control Center.

| Process death | Effect on a running capture |
| --- | --- |
| Brain (CLI crash, restart, new conversation) | **uninterrupted** — Brain is a client, holds nothing |
| Control Center (crash, restart) | **uninterrupted** — status is re-read from Core |
| Voice (crash, voice-stack change) | **uninterrupted** — Core opens its own source stream (D-CAP: distinct `sounddevice` stream, no `AudioCaptureHub`) |
| Core (= whole supervisor tree) | **recoverable partial** — reconciled at next Core start, never restarted |
| Capture service alone | not a separate process in V1: it *is* Core |
| Core graceful stop | captures stopped (`stop_reason: core_shutdown`), finalized like a user stop (`complete` when final and gap-free) |

The first three rows hold because nothing outside Core takes part in a
capture's lifetime; tests drive the owner without any Brain, Control Center or
Voice. A separate `jarvis capture` child process (D-CAP fallback) is not
needed: Slice 06 opened the real default microphone through the adapter
(3 s, WAV valid, no gap, about 1.9 s to open) while the live Jarvis tree was
running on the host; no PortAudio instability observed.

## Recovery at Core start

`CaptureService.recover()` runs in `JarvisCoreApplication.start()` after
`SessionManager.start()` and **before** `ArtifactService.recover_pending()`
(the family repair must precede the generic `.partial` promotion; tested).
Every capture still `starting`/`active`/`stopping` belongs to a previous life:

| What the crash left | Capture | Artifact |
| --- | --- | --- |
| no artifact yet | `failed`, `capture_interrupted` | — |
| artifact `pending` with bytes | repair hook, then `partial`, `recoverable_partial` | `partial`, `artifact_recovered` (promoted `.partial`, duration from the repair) |
| artifact `pending`, no bytes | `failed`, `capture_interrupted` | `failed`, `artifact_payload_missing` |
| artifact `pending`, payload refused (junction…) | `partial`, `recoverable_partial` (device freed) | left `pending`, retried by the generic pass |
| artifact already final (death between the two writes) | same state (`complete` only from `stopping`) | unchanged |

Each reconciled continuous capture gets `capture.gap` (`reason:
core_restart`, `last_seen_at`) then `capture.stopped` (`reason: recovered`),
both in the transaction of its final row (no gap when it ends `complete`).
Nothing is restarted automatically. `recover()` never raises (logged
`core.capture.recovery_failed`); its report is in `status().recovery`.

A store failure in the middle of a live stop leaves the row open: the capture
leaves memory, its device stays refused (`already_active`) until the next
start reconciles it.

## Audio recording (Slice 06)

Explicit recording of the microphone into an `audio_recording` artifact
(`source.wav`, `audio/wav`). Decisions D11, D12, D-CAP, D-AUDIO.

| Rule | Value |
| --- | --- |
| Stream | Core opens **its own** `sounddevice.RawInputStream` (`SoundDeviceInput`), distinct from Voice's streams (shared-mode host API, already multi-stream in SIMPLE). Never `AudioCaptureHub`, never its `drop_oldest`. Registered in Core's own `input_ownership` registry (`explicit_recording`), which is per process: it neither blocks nor counts Voice/PRESENTATION |
| Device | same setting as Voice: Control Center `audio_input_device`, else `JARVIS_AUDIO_INPUT_DEVICE`, else the system default; read at each start (`device: default`); a numeric `device` token is a PortAudio index |
| Format | PCM16 little-endian, mono, **16 kHz** (fallback 24 then 48 kHz if the device refuses). 16 kHz is what STT models use internally; 32 kB/s = **115 MB/h** (24 kHz would be 173 MB/h). Real rate in artifact metadata |
| Blocks | 100 ms per PortAudio callback; the callback only copies into the queue |
| Queue | bounded, 30 s of audio (about 1 MB); a writer thread drains it into the artifact spool |
| Header | canonical 44-byte WAV header written first with zero sizes; RIFF/`data` sizes rewritten in place (`write_at`) and `fsync` every 5 s and at stop |
| Start deadline | the service's 15 s; the real device took about 1.9 s to open on the dev host |

**Queue overflow is never silent.** When the queue is full the newest block
is refused (older blocks are already evidence on their way to disk) and its
samples are counted. With the next accepted block, the writer inserts exactly
that many samples of **digital silence** (zeros) at the place of the loss,
then writes the block, and calls `sink.gap(reason="queue_overflow",
lost_ms=...)`: `capture.gap`, capture and artifact end `partial` with
`capture_gap`. File time therefore stays wall time (transcript alignment
holds), and the hole is stated, never hidden. A loss still counted at stop is
padded at the end. A PortAudio `input_overflow` flag (driver-side loss,
duration unknown) is also a `capture.gap` (`input_overflow`, `lost_ms`
null). Final artifact metadata: `sample_rate`, `channels`, `sample_format`,
`audio_device`, `gap_count`, `gap_lost_ms`, `input_overflows`,
`dropped_blocks`, `stream_started_at` (merged by the service from
`MediaInfo.details` before finalization).

**Failures.** Open/start refused: `permission_denied` when the system says
access is denied, else `source_unavailable` (absent, busy or held in
exclusive mode by another application, format refused); the cause is kept in
the message and the opened stream is closed. Device lost mid-recording (the
driver stops the stream, or no block for 3 s): `source_lost`, `capture.gap`
(`source_lost`), automatic stop, evidence `partial` and playable. Disk full /
write refused: the writer stops writing, the owner stops the capture
(`storage_full` / `write_failed`).

**Repair after Core death** (`WavCaptureRepair`, the `audio` `CaptureRepair`):
reads the header of the `.partial` (or of the final file if the rename
happened), recomputes the RIFF and `data` sizes from the real file length,
truncates a torn trailing sample, `fsync`, and returns `duration_ms`. An
incomplete or non-PCM16 header is left as it is (`repaired: false`, reason in
the capture `data.repair`).

## Transcription (Slice 06)

`RecordingTranscriber` (Core) derives a transcript from the **durable spool**,
never from memory: transcription can lag, fail or be absent without losing a
single sample of evidence.

- **Trigger**: `CaptureService.add_started_listener`. After `capture.started`
  of an `audio` capture, a `transcript` projection artifact is created
  (`<audio_id>_transcript`, `transcribed_from` audio) and a job starts
  tailing the `.partial`, then the final file.
- **Boundaries**: `AmbientSegmenter` (energy gate with adaptive floor, 700 ms
  silence hangover, 200 ms lead-in, forced cut at **30 s**), fed frame by
  frame (20 ms) so each segment's end sample is exact. Forced cuts are
  contiguous (no gap between two cuts); silence is not sent to the provider.
- **Text**: `TranscriptionBackend` (same port as the ambient lane). One
  request per segment; at most **2** provider calls in flight across all
  recordings, **in order** per recording. Per attempt: 60 s deadline;
  3 attempts with 2 s then 8 s pauses for retryable errors (timeout, network,
  HTTP 408/409/429/5xx). An empty provider answer means *no speech*: no
  segment, cursor advances.
- **Waiting**: after its attempts, the segment stays first in line and the
  job **waits**: `waiting_retry` (retryable: new automatic try after 30 s,
  2 min, then every 10 min) or `unavailable` (no provider configured, or a
  refusal such as HTTP 401: waits for `retry(capture_id)`). The recording
  itself never waits. Codes: `transcription_unavailable`,
  `transcription_timeout`; the provider's own message is kept in
  `last_error` (never relabelled).
- **No provider** (no OpenAI key): the job says `unavailable` at once
  (`transcription_unavailable`); the recording completes normally;
  `retry()` re-reads the provider (production re-reads the key from the
  Control Center settings at each try, so adding a key needs no restart).
- **Evidence**: each accepted segment is a `transcript_segment` artifact
  created **complete in one transaction** (`ArtifactService.record_text`):
  text in the row (up to 16 000 chars), `started_at`/`ended_at` = wall clock
  (capture `activated_at` + offset, within one 100 ms block), metadata
  `start_ms`/`end_ms`/`start_frame`/`end_frame` (recording-relative),
  `seq`, `provider`, `model`, `attempts`, `forced_cut`, `speaker` (null:
  diarization can be added later as enrichment); relations
  `transcribed_from` audio and `segment_of` projection; events
  `artifact.created`, `artifact.finalized`, `transcript.segment.created`
  (counts and times only, never text). Segment ids are deterministic
  (`<audio_id>_seg000001`...): a replay never duplicates.
- **Projection**: the `transcript` artifact stays `pending` while the job
  runs; its `text` (readable tail, last 16 000 chars at most, cut at a
  segment boundary, `projection_truncated`) and metadata (`cursor_frame`,
  `next_seq`, `chars`, `transcription_state`, `error_code`, `last_error`)
  are rewritten with each segment and each state change
  (`ArtifactService.update_pending` + `transcript.projection.updated` in the
  same transaction). Segments are never rewritten. When the recording is
  terminal and every sample is handled: whole text written as payload
  `transcript.txt` (and in `text` when it fits), projection `complete`, or
  `partial` with the audio's error code when the audio is partial.
- **Restart catch-up**: at Core start, after `CaptureService.recover()`,
  `RecordingTranscriber.recover()` resumes every `pending` projection from its
  cursor (last handled sample) and opens one for a recovered recording that
  had none; then `ArtifactService.recover_pending(owned=transcripts.owns)`
  leaves those projections to their owner. A segment written just before the
  death but not yet noted in the projection is **adopted** (found by its
  deterministic id), not re-transcribed. A Core stop cancels jobs where they
  are (durable cursor, resumed next start; at most one paid request is
  repeated).
- **Status**: `RecordingTranscriber.status(capture_id)`: `state`
  (`running`, `waiting_retry`, `unavailable`, `complete`, `partial`),
  `error_code`, `last_error`, `segments`, `chars`, `cursor_ms`, `lag_ms`,
  `transcript_artifact_id`; durable in the projection metadata. The capture
  row itself is terminal once stopped and is not rewritten; HTTP/MCP
  (Slice 09) join the two.
- **Authority (D17)**: nothing is written to `conversation_events`; recorded
  room speech is evidence, never an addressed turn, and grants no action.
- **Cost**: `gpt-4o-mini-transcribe` (or `JARVIS_RECORDING_TRANSCRIPTION_MODEL`),
  about $0.003 per minute of **speech** (silence is not sent): at most about
  $0.18 per hour of continuous talk. A retried segment is paid again.
- **Limit**: while a projection is `pending` (e.g. `unavailable` forever), a
  cascade delete of its recording is refused (`artifact_still_pending`);
  Slices 09/10 expose `retry` (and decide an explicit abandon if needed).

## Activity and journal

| Event | When |
| --- | --- |
| `capture.started` | `starting → active` (same transaction) |
| `capture.gap` | dated hole (`reason`, `lost_ms`), source lost, or Core death at recovery |
| `capture.association_changed` | Context or Session changed while the capture runs |
| `capture.stopped` | every terminal state (`state`, `reason`, `error_code`, `gaps`, `bytes_written`) |
| `artifact.created` / `artifact.finalized` | through `ArtifactService` |

One-shot screenshots write no `capture.*` event (the artifact events say it).
Journal mirror `core.capture.*` (`started`, `stopped`, `gap`, `refused`,
`failure`, `finalize_failed`, `recovered`, `recovery`, `repair_failed`,
`association_changed`, `listener_failed`, `media_details_refused`...) and
`core.transcript.*` (`started`, `segment`, `segment_empty`,
`attempt_failed`, `waiting`, `retry_requested`, `replay_adopted`,
`finished`, `failed`, `recovery`...): ids, states, codes and counts only,
never media nor transcript text.

## Extension points

- **New family / camera (D18)**: add a `CaptureChannel` value, its
  `ARTIFACT_KIND` entries (and an `ArtifactKind` if needed), a source in the
  registry and optionally a `CaptureRepair`. No migration (no SQL CHECK on
  `channel`).
- **Real adapters** (Slices 06/07): implement `CaptureSource`, register them
  in a `CaptureSourceRegistry` passed to `JarvisCoreApplication`, and the
  repair hook per channel.
