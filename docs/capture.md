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

## Owner

`CaptureService` lives in **Core** and is the only status truth: state
machine, durable intent (table `captures`), finalization into the Artifact
registry ([artifacts.md](artifacts.md)), Session activity and reconciliation
after Core death. Core opens the sources itself (D-CAP). The Brain, MCP and
the Control Center are clients: none of them owns a capture's lifetime, and
an optimistic UI state is never truth (`status()` is). Capture does not depend
on interaction mode or Boards (D01, D06).

Production installs **no** source yet: `NoCaptureSources` refuses every start
with `unsupported_source` until Slices 06/07 register real ones
(`JarvisCoreApplication(capture_sources=..., capture_repairs=...)`).

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
| `transcription_unavailable` / `transcription_timeout` | 503 / 504 | reserved for Slice 06 |

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
needed: no evidence yet of PortAudio instability inside Core (Slice 06
re-checks with the real microphone).

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
`association_changed`…): ids, states, codes and counts only, never media.

## Extension points

- **New family / camera (D18)**: add a `CaptureChannel` value, its
  `ARTIFACT_KIND` entries (and an `ArtifactKind` if needed), a source in the
  registry and optionally a `CaptureRepair`. No migration (no SQL CHECK on
  `channel`).
- **Real adapters** (Slices 06/07): implement `CaptureSource`, register them
  in a `CaptureSourceRegistry` passed to `JarvisCoreApplication`, and the
  repair hook per channel.
