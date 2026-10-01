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
| Desktop screenshot, screen recording, registry, MP4 repair (Slice 07) | `jarvis/adapters/screen_capture.py` |
| Displays and GDI capture, per-thread DPI (Slice 07) | `jarvis/adapters/windows_display.py` |
| PNG encoder, fragmented-MP4 box scan (pure) | `jarvis/media/png.py`, `jarvis/media/fmp4.py` |
| HTTP facade over the owners (Slice 09) | `jarvis/core/capture_api.py` (`core.capture_api`), routes `jarvis/protocol/capture_routes.py` |
| Control Center relay (Slice 09) | `jarvis/runtime/capture_relay.py` |
| Brain MCP server `jarvis-capture` (Slice 09) | `jarvis/runtime/capture_mcp.py` ([mcp/tool-contract.md](mcp/tool-contract.md) §10.11) |

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
start refused `unsupported_source`, as before Slice 06). Since Slice 07 the
same registry delegates the `screen` channel to `ScreenCaptureSources`
(screenshot + screen recording, *Screen capture* below) and the `screen`
repair is `FragmentedMp4Repair`; `JARVIS_SCREEN_CAPTURE=0` removes the screen
channel. With both off, `NoCaptureSources` refuses everything.

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
| `gaps`, `bytes_written` | counts at the end; `status()` shows them live, `bytes_written` counting only bytes already handed to the OS (they survive Core death; it lags writing by at most 1 s) |
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
  stops the capture. A source **need not** call `sync`: the owner bounds the
  loss itself (`checkpoint`, *Loss bounds* below). `hand_over()` (Slice 07) gives the `.partial` path to an
  **external writer** (the screen encoder process): the sink stops writing
  itself, `bytes_written` is the size measured on disk, finalization stays
  the owner's. `gap(reason, lost_ms)` and `lost(code, reason)` are safe
  from any thread. No silent loss: a bounded queue that overflows calls `gap`
  (D-AUDIO).
- **`OneShotSource`**: `async capture() -> OneShotResult(data, width, height, details)`;
  `details` (display, DPI, time of capture...) is merged into the artifact
  metadata before the payload is written (refusal logged
  `core.capture.media_details_refused`, the screenshot is still stored).
- **`CaptureSourceRegistry`**: `continuous(...)`, `one_shot(...)`,
  `source_name(...)`; refuses with `unsupported_*`.
- **`CaptureRepair`** (per channel): `repair(RepairTarget) -> RepairOutcome`,
  synchronous, run in a thread at recovery. The target names the
  `.partial` and final paths and their sizes; the hook may only rewrite bytes
  in place (WAV header in Slice 06, video container in Slice 07; truncating
  a torn tail counts as in place), never create, rename or delete. It may
  return `usable=False` (Slice 07: a video with no complete fragment): the
  artifact is then `failed` (`capture_interrupted`) instead of a `partial`
  no player could open, and the `.partial` stays on disk as evidence. An
  exception is logged (`core.capture.repair_failed`) and the evidence is
  recovered as it is. Each repair runs in a daemon thread under a **45 s**
  deadline (`repair_timeout_s`; the MP4 repair's own ffmpeg probe is
  bounded at 30 s): a hung repair is logged `core.capture.repair_timeout`,
  counted in `repair_failed`, and the evidence is recovered as it is — Core
  start is never held. If the stuck thread still holds the file, the
  promotion fails and the artifact stays `pending` for the next start's
  generic pass. A repair must therefore **open the file for writing once**
  (one handle, every rewrite through it, closed before it returns; a
  read-only measurement afterwards, like the MP4 ffmpeg probe, is fine) and
  never reopen it for writing later:
  after the 45 s deadline its result is **discarded** (the thread is
  abandoned, not killed), and a repair that kept writing would touch a file
  recovery has already promoted — harmless on Windows (an open handle blocks
  the rename) but a real late-write risk on POSIX, where the rename succeeds
  under the open handle. `RepairOutcome` carries no width/height: the screen family
  knows them at start (artifact metadata) and its fragmented MP4 needs no
  remux, only a torn-tail truncation (Slice 07), so none is added.

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

## Loss bounds (Core death)

The **owner**, not each source, bounds what a hard kill of Core (the whole
supervisor tree, `TerminateProcess`) can lose. Every live continuous capture
has a durability task (`CaptureService._durability`):

| Step | Cadence | Survives | Measured cost on the host |
| --- | --- | --- | --- |
| spool buffer handed to the OS (`flush`) | every **1 s** (`FLUSH_INTERVAL_S`), and whenever the 64 KiB spool buffer fills | death of Core | 0.02 ms per second of audio (32 kB) |
| `fsync` | every **5 s** (`FSYNC_INTERVAL_S`), as soon as the source is stopped, and at finalization | power cut / OS crash | 0.9 ms median, 1.6 ms max (160 kB); encoder file reopened: 1–47 ms (QA, 6 live reopens) |

All disk work — checkpoints, `finalize`, `close` — runs in a thread, never on
Core's loop: a slow disk (a `fsync` in flight that holds the sink lock while
a stop arrives) delays the stop, not Core (tested with a 0.6 s `fsync`: the
loop keeps ticking under 100 ms). A refusal is a storage failure like a
refused write (`storage_full`/`write_failed`, the capture stops) — except
the `fsync` of an external encoder's file, see below.

The tail is pushed to disk (`fsync`) **as soon as the source stops**, before
the payload is finalized: a stop the store refuses (*Store refused during a
live stop*) keeps the capture open until its replay, and a hard kill in the
meantime loses nothing the source wrote. The live `bytes_written` of `status()` is the **flushed** count, so
every byte it ever reported survives a hard kill (tested with a real child
process killed mid-write:
`test_a_real_hard_kill_keeps_every_byte_the_status_reported`).

| Family | Lost on Core death | Lost on power cut |
| --- | --- | --- |
| Audio recording (Slice 06) | at most **≈ 1.1 s**: the last flush period (≤ 1 s, < 64 KiB at 32 kB/s) plus the block in flight between callback and writer (100 ms); the WAV sizes may be stale, the repair recomputes them from the file length | at most ≈ 5 s (owner `fsync`; the source also rewrites the header and `fsync`s every 5 s) |
| Screen recording (Slice 07) | at most **≈ 1 s**: ffmpeg writes every packet to the OS itself (`-flush_packets 1`) and the kernel kills it with Core (Job Object); only the fragment being built (1 s) is lost, its torn tail truncated by the repair. Host: killed after 4.4 s → 4.0 s readable | at most **≈ 5 s**: every `FSYNC_INTERVAL_S` the owner reopens the encoder's file and `fsync`s it while ffmpeg writes (no sharing refusal observed on the host). A refusal (`OSError`, sharing) is **not fatal**: logged once per capture (`core.capture.encoder_sync_refused`), the recording goes on, and the power-cut bound is then the stop's `fsync` only |
| Any other source writing through the sink | the last flush period: ≤ 1 s **and** ≤ 64 KiB | ≤ 5 s |
| Screenshot | nothing partial: the payload is written atomically (`write_payload`) | same |

Nothing still in Core's memory is ever reported as written.

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
core_restart`, `last_seen_at`, `last_seen_source`) then `capture.stopped`
(`reason: recovered`), both in the transaction of its final row (no gap when
it ends `complete`). `last_seen_at` is the **last write that reached the
disk**: the payload file's modification time, read before any repair
(`last_seen_source: payload_write`; the owner flushes every second, so it is
within about a second of the death, at no cost while recording); without a
payload file, the row's last transition (`capture_row`). Nothing is
restarted automatically. `recover()` never raises; its report is in
`status().recovery`.

Recovery lists the open ids **without decoding the rows**, then reads and
reconciles each one in its own `try`: an unreadable row (or one whose
reconciliation fails) is logged `core.capture.recover_one_failed`, counted
in `recovery.unreadable`, left open, and never stops the others. A store that
refuses the listing itself is logged `core.capture.recovery_failed`.

Why an artifact can stay `pending` while its capture ends `partial`: its
payload folder was refused (junction, unreadable folder), so nothing can be
measured or promoted. Failing it would throw away evidence that becomes
readable once the folder is fixed; `ArtifactService.recover_pending` retries
it at every start. The capture itself is closed so the device is freed.

### Store refused during a live stop

A database (or registry) refusal — locked, I/O error, **disk full** — in the
middle of a stop never loses the capture:

- the source is stopped anyway (the human asked to stop; nothing written is
  lost) and the durability task ends;
- `stop()` raises `CaptureError` with a stable code — `storage_full`
  (SQLite `SQLITE_FULL`, ENOSPC, Windows 39/112) or `storage_unavailable` —
  naming the capture; journal `core.capture.stop_stuck`;
- the capture stays in memory and in `status().captures` (its last known
  state, normally `stopping`) **and** in `status().stuck` (`capture_id`,
  `error_code`, `reason`); `get()` returns it; it keeps its device;
- the stop is **replayed** where it stopped (source already stopped,
  payload already finalized, artifact already finished —
  `artifact_not_pending` tolerated) by the next `stop()`, by the next
  `start()` on the same channel/device (if the replay still fails, that start
  is refused with the storage code and the stuck `capture_id`), and by Core
  `close()`. What is still open at exit is reconciled at the next start.

A row left open by an **earlier life** that recovery could not close (any
open row the store names as holder while this Core does not run it) is
reconciled **inline** by `start()` — same rules as recovery,
`core.capture.orphan_recovered` — then the insert is retried once; if that
reconciliation fails (`core.capture.orphan_unrecovered`) the start keeps its
`already_active` refusal naming the orphan.

Screenshots finish every path: a source crash (`source_unavailable`, the
exception type in the message), a refused artifact (`storage_unavailable`,
no artifact), a refused payload write or a store refusal end the row and the
artifact `failed` with that code; if even that write is refused, the row is
logged `core.capture.left_open` and recovery closes it.

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
driver stops the stream, or no block for 3 s counted from the moment
`stream.start()` returned, so a slow-starting Bluetooth microphone is never
lost before it started): `source_lost`, `capture.gap`
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
- **Stopped on an error** (a database refusal, an unexpected defect): the
  in-memory job never runs ahead of its projection (a refused projection
  write rolls back cursor and rank); the error state (`unavailable`,
  `transcription_unavailable`, the real cause in `last_error`) is written to
  the projection when the database accepts it (else
  `core.transcript.state_save_failed`); `retry()` restarts from the
  **durable** projection, adopting any segment already written, so no
  segment is duplicated and no frame range overlaps. A success resets the
  automatic wait (a later outage waits 30 s again, not the next step).
- **Missing projection**: if its creation was refused when the recording
  started (`core.capture.listener_failed`), the transcript is created when
  the recording stops (`CaptureService.add_stopped_listener` →
  `RecordingTranscriber.on_capture_stopped`) or by `retry()`
  (`core.transcript.caught_up`).
- **Status**: `RecordingTranscriber.status(capture_id)`: `state`
  (`running`, `waiting_retry`, `unavailable`, `complete`, `partial`),
  `error_code`, `last_error`, `segments`, `chars`, `cursor_ms`, `lag_ms`,
  `transcript_artifact_id`; durable in the projection metadata. The capture
  row itself is terminal once stopped and is not rewritten; HTTP/MCP
  (Slice 09) join the two (`transcription` of every capture in
  `GET /v1/captures/status`, *HTTP API* below).
- **Authority (D17)**: nothing is written to `conversation_events`; recorded
  room speech is evidence, never an addressed turn, and grants no action.
- **Cost**: `gpt-4o-mini-transcribe` (or `JARVIS_RECORDING_TRANSCRIPTION_MODEL`),
  about $0.003 per minute of **speech** (silence is not sent): at most about
  $0.18 per hour of continuous talk. A retried segment is paid again.
- **Limit and explicit abandon** (Slice 09): while a projection is `pending`
  (e.g. `unavailable` forever), a cascade delete of its recording is refused
  (`artifact_still_pending`). `RecordingTranscriber.abandon(capture_id,
  reason)` is the user's way out: refused `capture_still_open` (409) while the
  recording runs; otherwise the job is cancelled, segments written during the
  cancellation are adopted, and the projection is finalized **`partial`** with
  `error_code` `transcription_abandoned`, `transcription_state` `abandoned`,
  the reason (≤ 200 characters) in `last_error`, and the text of the segments
  already accepted as its payload. Segments are kept (immutable evidence);
  nothing more is sent to the provider; journal `core.transcript.abandoned`.
  Already terminal: returned as is (idempotent). The recording can then be
  deleted with `cascade`.

## Screen capture (Slice 07)

Desktop screenshot (`screen`/`one_shot` → `screenshot` artifact) and
continuous screen recording (`screen`/`continuous` → `screen_recording`
artifact), owned by Core like every capture. Decisions D16, D18, D-CAP,
D-SCREEN. **Separate from scene capture**: the scene PNG of the Control
Center (`runtime/scene-captures/`, ≤ 1280×720, 5 files/24 h, diagnostic) is
untouched and never routed here; a screenshot is never a scene render.
Screen captures are durable user data under `<data_root>/artifacts/`, with
no automatic retention.

### Host audit (2026-10-01)

| Fact | Value |
| --- | --- |
| OS | Windows 11 Pro 10.0.26200, 20 logical CPUs |
| Displays (`EnumDisplayMonitors`) | 2: `\\.\DISPLAY1` primary 1920×1080 at (0,0), 120 dpi (125 %); `\\.\DISPLAY5` 1920×1080 at (1920,0), 96 dpi; virtual desktop 3840×1080 |
| DPI trap | a DPI-unaware process (Core) sees the primary display as **1536×864**: capture must run per-monitor DPI aware to get physical pixels |
| Installed before Slice 07 | no ffmpeg, Pillow, mss, opencv or av |

### Backend decision (measured on the host)

| Need | Choice | Why (measurements) |
| --- | --- | --- |
| Screenshot | **GDI `BitBlt` through `ctypes` + PNG by the standard library** (`windows_display.py`, `media/png.py`). No dependency | `mss` 10.2 (MIT) was the candidate, but it calls `SetProcessDpiAwareness(2)`, changing DPI awareness of the **whole Core process**; the ctypes path switches only the capturing thread (`SetThreadDpiAwarenessContext(PER_MONITOR_AWARE_V2)`) and restores it. Grab 32–45 ms; PNG (zlib 6, filter None) 34 ms / 150 KiB for a flat desktop, 212 ms / 5.3 MiB for a photo-rich one. PNG `Sub`/`Up` filters (tried with numpy) gained ≤ 9 %: not worth a dependency |
| Recording input | **ffmpeg `gdigrab`** limited to the display rectangle | `ddagrab` (Desktop Duplication) used 16 % of a core vs 21 % at 5 fps for the same size, but needs a D3D11 duplication session (fails on RDP / secure desktop, GPU path); `gdigrab` works everywhere GDI does and is DPI-correct (ffmpeg reports the whole desktop as 3840×1080 physical) |
| Codec | **H.264, `libx264 -preset veryfast -tune zerolatency -crf 30`, yuv420p, keyframe every 10 s** | `h264_mf` (Media Foundation) used 27.5 % vs 21 %. `zerolatency` is **required**: without it x264's lookahead and frame threads (20 CPUs) keep about 6 s of frames in memory, and a kill after 4 s left **0 frames** on disk |
| Container | **fragmented MP4** (`frag_keyframe+empty_moov+default_base_moof`, 1 s fragments, `flush_packets 1`) written directly into the spool `.partial` | Hard kill after ~4 s: plain MKV = 0 bytes (unreadable); MKV with 2 s clusters = 2.0 s readable; fMP4 = 3.0 s readable with a duration. Each `moof`+`mdat` fragment is self-contained, so a crash loses at most the last second. MP4/H.264 also plays in the browser (Slice 10) and Windows players; MKV does not reliably in Chrome |
| ffmpeg binary | `imageio-ffmpeg==0.6.0` (extra `capture`) | pip-installable, pinned, no system dependency (D-SCREEN); bundled ffmpeg 7.1 Windows build |

**Licences.** Screenshots add no third-party code. `imageio-ffmpeg` is
BSD-2-Clause; its bundled binary is the gyan.dev *essentials* build,
configured `--enable-gpl --enable-version3` with libx264: **GPLv3**. Jarvis
only *executes* it as a separate process (no linking) and does not
redistribute it: the user installs it with pip. If Jarvis is ever shipped as
a bundle containing that binary, the GPLv3 obligations (source offer) apply
to it. `JARVIS_FFMPEG_EXE` can point at another build, but the encoder
arguments require `libx264` today.

### Source policy (V1)

- Device token: `default` = **primary display**; `displayN` = N-th display,
  `display1` being the primary, the others left to right then top to bottom.
  Resolved at each screenshot / recording start; a missing display is
  `source_unavailable`; any other token is `invalid_capture`.
- No window capture and no "all displays" capture in V1 (minimal UX; window
  semantics — minimized, occluded, other DPI — were not audited).
- One recording per display (`already_active`); two displays can record
  together; a screenshot never conflicts with a recording; screen and audio
  recordings coexist.
- The mouse cursor is drawn in recordings, not in screenshots.

### Screenshot

`DesktopScreenshotSource`: payload `screenshot.png` (`image/png`), artifact
width/height in **physical pixels**, metadata `display`, `display_device`,
`display_left`, `display_top`, `display_primary`, `dpi`, `dpi_scale`,
`captured_at`, `capture_backend: gdi_bitblt`, `image_format: png_rgb8`,
`capture_ms`. Real host: primary display 1920×1080 at 125 % → 1920×1080 PNG
in 167 ms.

### Screen recording

`ScreenRecordingSource`, payload `screen.mp4` (`video/mp4`), default
**5 fps** (1–30 accepted by the source). Lifecycle:

1. resolve the display, `sink.hand_over()` → the `.partial` path;
2. start ffmpeg with explicit arguments (`recording_args`) **suspended**,
   put it in a Windows Job Object, resume it (`FfmpegProcess`, below);
3. started when the first bytes (`ftyp`+`moov`) are on disk (≤ 13 s, else
   killed, `source_unavailable`; a cold first start measured 9.0 s on the
   host, and 13 s stays under the service's 15 s start deadline). The time to
   ready is kept as `encoder_ready_ms` in the artifact metadata and journaled
   as `source_start_ms` in `core.capture.started` (ids and ms only); an encoder that exits before that is
   `permission_denied` when its stderr says access is denied, else
   `source_unavailable`, with its last stderr lines;
4. a watcher thread (every 0.5 s): encoder exited by itself → `source_lost`;
   file not growing for 15 s → `source_lost` (encoder killed); every 2 s the
   recorded display is looked up again: gone, moved or resized →
   `source_lost` (gdigrab would keep filming a rectangle that is no longer
   that display). The capture then stops by itself and ends `partial` with
   its bytes up to the change. A DPI-only change keeps recording;
5. stop: `q` on stdin, wait 5 s; else end the job (kill), wait 3 s, capture
   `partial` with `source_timeout` (the last fragment, ≤ 1 s, may be lost).
   A non-zero exit is `storage_full` when ffmpeg says the disk is full, else
   `write_failed` (`partial`, bytes kept);
6. duration: ffmpeg stream-copy probe of the file (≤ 2 s, keeps stop under the
   service's 10 s), else wall clock (`duration_source`). Then the owner
   `fsync`s and renames the spool (`finalize`).

stdout is discarded; stderr is drained by a thread into a bounded buffer
(40 lines × 300 chars) — no unbounded memory. Final metadata: `fps`,
`video_codec`, `video_encoder`, `container: mp4_fragmented`,
`capture_backend: gdigrab`, `keyframe_interval_s`, `encoder_exit_code`,
`encoder_killed`, `duration_source` and the display facts above.

Measured on the host (final arguments, 10 s each, `GetProcessTimes` of ffmpeg):

| Display content | fps | ffmpeg CPU (one core) | Size |
| --- | --- | --- | --- |
| primary, mostly static desktop | 5 | 21–31 % (≈ 1–1.5 % of the 20-CPU host) | 0.5–0.9 MB/min |
| primary, mostly static desktop | 10 | 56 % | 0.6 MB/min |
| second display, moving content | 5 | 39 % | 10 MB/min (≈ 600 MB/h) |
| second display, moving content | 10 | 65 % | 16.5 MB/min |

Core-side cost (watcher, service) was 1.4 % of one core. Start latency
(service `start` → `active`) 0.39 s; stop latency 0.69 s (including the
probe). 5 fps stays the default: half the CPU of 10 fps, enough to read a
working screen; Slice 08 samples frames at a lower rate anyway.

### Orphan safety

Windows does **not** kill a child when its parent dies, and the supervisor
ends Core with `TerminateProcess` (no tree kill): an unmanaged ffmpeg would
keep recording with no owner. `FfmpegProcess` therefore reuses
`jarvis/runtime/owned_process_tree.py` (`OwnedProcessTree`, already used for
the agent CLIs): the process is created suspended, assigned to a Job Object
with `KILL_ON_JOB_CLOSE`, then resumed. Only Core holds the job handle; when
Core dies, the kernel closes it and kills ffmpeg. If the job cannot be
created or assigned, the recording is refused (`source_unavailable`) rather
than started uncontained. Tested: unit test with a real child process
(`test_the_encoder_dies_with_core_even_on_a_hard_kill`) and on the host —
Core harness hard-killed mid-recording, ffmpeg gone 0.02 s later.

### Recovery after Core death

`FragmentedMp4Repair` (the `screen` `CaptureRepair`): scans the top-level MP4
boxes of the `.partial` (or final file), truncates the torn trailing
fragment **in place**, `fsync`, then measures the duration with ffmpeg when it
is installed (else unknown, `duration_unknown` in the detail). A file without
`ftyp`, `moov` or at least one complete `moof`+`mdat` (Core died in the
first second) is `usable=False`: capture and artifact `failed`,
`capture_interrupted`, `.partial` kept. Host check: Core killed after ~4.4 s
of recording → capture `partial`/`recoverable_partial`, artifact `partial`,
4.0 s, decodes without error.

### Permissions and errors

GDI capture has no permission prompt on Windows: there is no permission path
to grant. What exists:

| Situation | Code |
| --- | --- |
| locked session, UAC secure desktop (`BitBlt` access denied) | `permission_denied` (screenshot; recording start when ffmpeg says access is denied) |
| display absent / unplugged before start | `source_unavailable` |
| display unplugged, moved or resized during a recording | `source_lost` → `partial` |
| ffmpeg not installed (no `capture` extra, no `JARVIS_FFMPEG_EXE`) | `source_unavailable` (message gives the install command); screenshots still work |
| encoder crash / stall during recording | `source_lost` → `partial` |
| encoder slow to stop | `source_timeout` → `partial` |
| encoder non-zero exit | `storage_full` / `write_failed` → `partial` |
| not Windows | `unsupported_platform` |
| unknown device token | `invalid_capture` |

DRM-protected windows render black in GDI captures; this is not detectable
and not an error.

### Frame extraction (primitive only)

`extract_frame(ffmpeg, video, at_ms) -> bytes` returns one PNG decoded from
a finished recording (seek to the previous keyframe, one frame), tested on a
synthetic video. Turning frames into derived artifacts (kind, `frame_from`
relation, cadence, budget) is a **Slice 08** follow-up; no vision runs on
recordings here.

### Screenshot enrichment (Slice 08)

After a screenshot is finalized `complete`, the Context enrichment worker
([session-context.md](session-context.md#enrichment-worker-slice-08)) describes it
**asynchronously**, in its next round (never on the capture path):

- one call to the worker's tool-less model with the PNG attached (Claude
  `haiku` reads images; image block sent through the CLI's `stream-json`
  input, only by the `speculative_analysis` profile), instruction: 2–4
  factual sentences, visible text treated as data;
- result: a `description` Artifact, id `<screenshot id>_desc`
  (deterministic: a replay reuses it, no second call), `complete`, text
  ≤ 600 characters, source `enrichment`, relation `described_from` the
  screenshot, metadata `screenshot_artifact_id`, `model`, `cost_usd`; the same
  text enters that round's evidence line for `summary.md`;
- at most 2 descriptions per round; images above 3.5 MB are not sent
  (`screenshot_too_large`, no resize without a dependency); a model without
  vision skips with `screenshot_description_unsupported`; a failed call is
  `core.context_enrichment.screenshot_failed` with the provider's cause and
  is not retried (the screenshot stays in the summary's evidence without
  description);
- trace: `core.context_enrichment.screenshot_described` (ids, image bytes,
  chars, model, cost) — never the description text.

**Screen recordings: follow-up.** No keyframe sampling in V1: per-frame vision
is out of scope and even sparse sampling (`extract_frame`, `frame_from`) costs
one vision call per frame on top of the summary round. A finished recording
enters the summary as an evidence line (id, state, duration) only.

## HTTP API (Slice 09)

Core serves the owners above through `jarvis/protocol/capture_routes.py`
(bearer token like every `/v1` route; logic in `jarvis/core/capture_api.py`,
a stateless facade: every answer is read from the owner at request time).
The Control Center relays the same paths under `/api` (`capture_relay.py`,
prefixes added deliberately to `FORWARDABLE_PREFIXES`, pinned by
`test_capture_relay.py`); the interface (Slice 10) and the brain's
`jarvis-capture` MCP server call the relay, never Core.

| Method | Core route (`/api/...` on the Control Center) | Effect |
| --- | --- | --- |
| GET | `/v1/contexts` | Contexts of the open Session, `active_context_id` |
| POST | `/v1/contexts` | new active Context `{title?, handoff_summary? (≤ 8 000), source_context_ids? (≤ 16), origin?}` → 201 `{context, workspace_ref, previous_context_id, handoff_written, handoff_error?}` |
| GET | `/v1/contexts/current` | active Context |
| POST | `/v1/contexts/{context_id}/activate` | reactivate `{origin?}` → `{context, previous_context_id, changed}` |
| GET | `/v1/captures/status[?recent=0..20]` | open captures (live bytes, gaps), `stuck`, last finished (`recent`, default 5), `recovery`, `enrichment` (worker state); each capture carries its `transcription` |
| POST | `/v1/captures/start` | `{channel: audio\|screen, options?: {source?, device?}, origin?}` → 201 `{capture}` |
| POST | `/v1/captures/screenshot` | `{options?, origin?}` → 201 `{capture, artifact}` |
| GET | `/v1/captures/{capture_id}` | one capture and its transcription |
| POST | `/v1/captures/{capture_id}/stop` | idempotent stop → final state |
| POST | `/v1/captures/{capture_id}/transcription/retry` | `RecordingTranscriber.retry` |
| POST | `/v1/captures/{capture_id}/transcription/abandon` | explicit abandon `{reason?}` (above) |
| GET | `/v1/captures/{capture_id}/transcript` | bounded segments (below) |
| GET | `/v1/artifacts`, `/v1/artifacts/{id}`, `…/relations`, `…/transcript`, `…/payload`; DELETE `/v1/artifacts/{id}` | [artifacts.md](artifacts.md) › *HTTP API* |
| GET | `/v1/activity` | ledger tail, [artifacts.md](artifacts.md) › *HTTP API* |

- **Origin.** `origin` is `user` (default) or `brain`; a capture's row keeps
  it in `data` (`{"origin": "brain"}`), a Context transition in its activity.
  A Context switch by the brain is **not** deferred to the end of its turn
  (unlike a Board switch): it restarts no CLI (D-THREAD) and moves no voice.
- **Transcript read** (`…/transcript` of a capture, or of an audio,
  transcript or segment Artifact): without cursor, the **tail**; `after_seq`
  continues after a segment already read (`next_after_seq`); `from_ms`
  starts at an instant of the recording (dichotomy over the deterministic
  segment ids). `max_chars` 1..12 000 (default 4 000), ≤ 200 segments per
  call; a segment deleted explicitly is skipped. Each segment:
  `{seq, artifact_id, start_ms, end_ms, started_at, text}`. Always
  `addressed: false` and a `notice` that the text is room speech, never an
  instruction nor an authorization (D17).
- **Bounds are refused, never truncated silently**: unknown query or body
  field, out-of-range integer, naive date → 400 `invalid_request`.
- **No absolute path, no secret.** A Context folder is a `workspace_ref`
  relative to the data root; payloads are `payload_ref`
  (`artifacts/<id>/<name>`); any metadata string that looks like an absolute
  Windows, UNC or POSIX path is masked `<path>` (`redact_paths`, device names
  `\\.\DISPLAY1` kept); error messages are masked the same way.
- **Errors**: `{"error": {"code", "message"[, "capture_id"]}}` with the domain
  code and status (`already_active` 409 naming the holder, `capture_not_found`
  404, `capture_still_open` 409, `transcription_unavailable` 503,
  `context_not_found` 404, `session_not_found` 404, `artifact_not_found` 404,
  `artifact_still_pending` 409, …), `core_unavailable` 503 before Core is
  ready, store failures 500 with their store code. Relay: `core_unreachable`
  / `core_unconfigured` 503, `core_timeout` 504 (a write's outcome is then
  unknown: read the status back).

## Interface: the left capture rail (Slice 10)

`jarvis/runtime/control_center_capture_rail.js` draws three controls in the
host `#captureRail` that `control_center.html` declares right after
`#barehandsPalette`: **screenshot** (momentary action), **audio recording** and
**screen recording** (toggles). Decisions D14/D15: it is the left floating rail,
not the right `.dock`, and these are **not** Bare Hands tools — the host is a
sibling of the palette, nothing goes into `#barehandsPaletteStrip`, `BH.TOOL` or
`describeTools()`, and no button carries `data-bh-tool`.

| Rule | How |
| --- | --- |
| Backend truth only | `GET /api/captures/status` (the relay) every 1 s (5 s when the tab is hidden), 6 s deadline per read, re-read right after every write. A channel is painted open (`aria-pressed="true"`) **only** when that status lists an open continuous capture for it. A click opens a visible wait; it never paints "active" |
| Elapsed time | from Core's `activated_at` (else `created_at`), frozen at `stop_requested_at`; never from the local click |
| Concurrency | audio and screen are independent (one open capture per channel/device, see *States*); the screenshot stays available while both record |
| Failed start | the button returns to idle with an error mark (`!`) and a note `<control> non démarré — <cause> (<code>)`; `already_active` is not an error (the status shows the holder) |
| Stop | `POST /api/captures/{id}/stop` on the id the status gave; `partial`/`failed` results say so (`arrêté mais incomplet`) |
| `stuck` | a capture listed in `status.stuck` is shown as an error (`arrêt bloqué (<code>)`); clicking stops it again |
| Ended elsewhere | an open capture that disappears into `recent` as `partial`/`failed` without this page stopping it is announced (`interrompu — <cause>`); a refused start (`stop_reason: start_failed`) this page asked for is reported once, as `non démarré` |
| Status lost | relay or Core unreachable, timeout, unreadable body → every control shows **état inconnu** (`?` mark, dashed border, `aria-pressed="false"`), starts are refused; a capture known open just before can still be **stopped** (privacy first) |
| Waits | every write has a 50 s deadline (relay 45 s); then the page gives the hand back and re-reads the status (`pas de réponse à temps, issue inconnue`) |

States painted (`data-capture-state`): `idle`, `starting`, `active`,
`stopping`, `stuck`, `error`, `unknown`, and for the screenshot `busy` and
`done` (a check for 2.5 s). Cues never rely on colour alone: an open channel
shows the **stop square**, a 3 px side bar (like the palette's active tool) and
its timer **inside** the button; errors carry `!`, unknown `?` and a dashed
border; waits show a sweep bar and a seconds counter. Under
`prefers-reduced-motion` the bar and sweep stop moving, the counters keep
counting; `forced-colors` maps states to system colours. Short French error
texts by code: `refusalText()` (`source_unavailable` → micro / écran
indisponible, or the ffmpeg install hint when Core's message names ffmpeg;
`permission_denied`, `storage_full`, `core_unreachable`, `core_timeout`, …; an
unknown code is shown as `échec (<code>)`).

Keyboard: `role="toolbar"`, vertical, one tab stop (roving), arrows in both
axes, Home/End; Enter/Space are the native `<button>`; Escape closes the note.
Every control has an `aria-label` equal to its tooltip; the note is linked by
`aria-describedby`; state changes are announced in a polite live region.

Placement (measured, not assumed — the palette's height depends on the tools
installed and the column is centred under 700 px): **below** the Bare Hands
column, same 64 px column, separated by a rule; when that would leave the
window or touch another control (interaction-mode button, voice hint, dock,
chips, top bar, GPT-Live banner, scene status), **beside** the column, aligned
on its top, then on its bottom (`data-capture-slot`). Bare Hands not mounted →
the top of the column (`alone`). Stacking rank 30, the palette's. The scene
measures the rail as a control (`#captureRail` in `CONTROL_SELECTOR` of
`control_center_scene_page.js`), so a held object stops against it.

Journal (browser console, `[capture]`): `capture_rail.installed`, `placed`,
`status_received`, `status_lost` / `status_restored`, `start_requested` /
`started` / `start_failed` / `start_already_active`, `stop_requested` /
`stopped` / `stopped_incomplete` / `stop_failed`, `screenshot_requested` /
`screenshot_taken` / `screenshot_failed`, `capture_interrupted`,
`capture_ended_elsewhere`, `no_free_slot`.

Tests: `tests/unit/test_capture_rail_js.py` (pure model, placement, insertion),
`tests/unit/test_capture_rail_browser.py` (headless Chrome: placement at 1440 →
375 px with Bare Hands off/on/absent, keyboard, failed start, status loss,
concurrency, stuck, reduced motion, forced colours, axe-core when
`JARVIS_AXE_JS` points to `axe.min.js`).

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
`repair_timeout`, `recover_one_failed`, `stop_stuck`, `stopping_refused`,
`orphan_recovered`, `orphan_unrecovered`, `left_open`, `association_changed`, `listener_failed`, `media_details_refused`, `encoder_sync_refused`...) and
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
