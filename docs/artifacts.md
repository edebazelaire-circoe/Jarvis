# Artifacts and Session activity (contract)

Generic evidence layer of Jarvis (handoff `jarvis-session-context-recording-runtime`,
Slice 04; decisions D07–D10, D16, D-ART). Capture features (audio recording,
transcription, screenshots, screen recording, enrichment) create, finalize
and query **Artifacts** and write **activity** through one Core façade,
`ArtifactService` (`jarvis/core/artifact_service.py`), without knowing any
table or folder.

| Piece | Code |
| --- | --- |
| Artifact value, states, relations, query | `jarvis/domain/artifacts.py` |
| Activity event, vocabulary, query | `jarvis/domain/session_activity.py` |
| Ports | `jarvis/ports/artifacts.py` |
| Registry store | `jarvis/adapters/sqlite_artifacts.py` (`artifacts`, `artifact_relations`, v6) |
| Activity ledger store | `jarvis/adapters/sqlite_session_activity.py` (`session_activity`, v6) |
| Payload folders | `jarvis/adapters/artifact_payloads.py`, path defenses in `safe_folders.py` |
| Core façade + recovery | `jarvis/core/artifact_service.py` (`core.artifacts` in `v2_app`) |

## Artifact

A piece of evidence acquired by Jarvis. Acquisition precedes interpretation
(D07): identity, time, source and payload reference exist from the start;
descriptions and other semantics are appended later.

| Field | Rule |
| --- | --- |
| `artifact_id` | `jart_` + lowercase `[a-z0-9_-]` (path-safe segment, NTFS case), ≤ 128 |
| `kind` | closed set, below |
| `source` | short token (`capture.audio`, `stt`…) ≤ 64 |
| `state` | `pending` → `complete` / `partial` / `failed` |
| `created_at`, `updated_at` | aware datetimes, `updated_at` never goes back |
| `started_at?`, `ended_at?` | media time range, `ended_at ≥ started_at` |
| `jarvis_session_id?`, `context_id?` | optional association; a Context implies its Session (checked against `session_contexts` on insert) |
| `payload_ref?` | `artifacts/<artifact_id>/<name>`, **relative** to the data root, reserved at creation |
| `mime_type?`, `size_bytes?`, `duration_ms?`, `width?`/`height?` | bounded; `size_bytes` is measured on disk by the service |
| `text?` | short text carried by the row (transcript segment, description) ≤ 16 000 chars; longer text is a payload file |
| `error_code?` | token; required for `failed`, optional on `partial`, forbidden otherwise |
| `metadata` | acquisition scalars (≤ 32 keys, strings ≤ 512, integers within int64, finite floats) |
| `enrichment` | appended later (≤ 32 keys, strings ≤ 4 000) |

**Kinds (V1, closed):** `audio_recording`, `transcript_segment`, `transcript`,
`screenshot`, `screen_recording`, `description`, `derived`. There is no
`other` bucket: evidence without a kind cannot be indexed. A new kind is a new
`ArtifactKind` value plus this table; no migration (no SQL CHECK on `kind`).

**States.** `pending` is the only open state (`update_pending` records bytes, duration,
a rewritten `text` or merged `metadata` so far). `complete`, `partial` and `failed` are terminal for
every acquisition field: only `enrichment` (and `updated_at`) may change
afterwards (`check_artifact_update`, enforced by the store too). `partial` is
first-class: readable, queryable, never shown as complete. An artifact with a
payload becomes `complete` only when the final file is on disk
(`ArtifactService.finalize` refuses otherwise); `complete` needs a payload or
a `text`.

**Transcripts (Slice 06, [capture.md](capture.md#transcription-slice-06)).**
A `transcript_segment` is raw accepted STT text of one stretch of a
recording: created `complete` in one transaction
(`ArtifactService.record_text`, deterministic id `<audio_id>_seg<seq>`),
text in the row, recording-relative times in metadata and wall-clock
`started_at`/`ended_at`, relations `transcribed_from` the `audio_recording`
and `segment_of` its `transcript`; never rewritten. A `transcript` is the
**projection** of one recording (`<audio_id>_transcript`, `transcribed_from`
the audio): `pending` while transcription runs, its `text` (readable tail)
and metadata (cursor, state) rewritten through
`ArtifactService.update_pending`; finalized with the whole text as payload
`transcript.txt`. Only `pending` acquisition fields move; segments never do.

**Descriptions (Slice 08, [capture.md](capture.md#screenshot-enrichment-slice-08)).**
The Context enrichment worker writes one `description` per described
screenshot: id `<screenshot id>_desc`, created `complete` by `record_text`,
source `enrichment`, `described_from` the screenshot. `summary.md` itself is a
Context file, not an Artifact (revisable projection, D04).

**Errors** (`ArtifactError.code`, HTTP status): `invalid_artifact` 400,
`artifact_not_found` 404, `artifact_conflict` 409 (id taken, row changed since
read, identity edited), `artifact_not_pending` 409, `artifact_still_pending`
409, `artifact_has_dependents` 409, `invalid_relation` 400, `relation_cycle`
409. Store failures: `artifact_store_unreadable` (row contradicts its columns,
never repaired or skipped), `artifact_store_failed` (SQLite refused).

## Provenance

Explicit rows, never opaque metadata (D08): “`artifact_id` *relation*
`origin_artifact_id`”.

| Relation | Meaning |
| --- | --- |
| `transcribed_from` | transcript or segment from an audio recording |
| `segment_of` | segment of a whole (segment → transcript) |
| `frame_from` | image extracted from a screen recording |
| `described_from` | description of a capture, image or excerpt |
| `derived_from` | any other derivation (summary, observation) |

No self relation; ≤ 64 origins per artifact; both ends must exist; adding an
existing relation is a no-op (replay-safe); a relation that would close a
cycle of any relation kind is refused (`relation_cycle`, recursive check). The
graph is queryable both ways (`RelationDirection.ORIGINS` / `DEPENDENTS`,
index on each side). Relations given to `create` are written in the same
transaction as the artifact.

## Payloads

Large binaries are files, never SQLite rows (D09):
`<data_root>/artifacts/<artifact_id>/<name>` — under the per-PC data root
([local-data.md](local-data.md)), **not** under `./runtime`.

- the path is derived from validated ids and names only (lowercase
  `[a-z0-9_.-]`, no `..`, not hidden, not ending in `.partial`); the store
  keeps only the relative `payload_ref`, so moving the data root keeps every
  record valid;
- folder defenses are shared with Context folders
  (`jarvis/adapters/safe_folders.py`): absolute root, every component checked
  with `lstat`, symbolic link / junction / reparse point / file-instead-of-folder
  refused (`artifact_payload_unsafe`), nothing written through it;
- writers always write `<name>.partial`; `finalize` = `fsync`, close, rename
  to `<name>` (`replace_with_retry`). A file under its final name is complete.
  Neither a final file nor a leftover `.partial` is ever overwritten
  (`artifact_payload_conflict`);
- `read_range` / `ArtifactService.read_payload` reads a bounded range of the
  final file, else of the `.partial` being written (the recording
  transcription tails the spool, Slice 06); the file is open only for the
  read, so a concurrent rename is not blocked beyond it;
- `open_spool` is the streaming writer for long captures (Slices 06/07):
  `write`, `write_at` (rewrite bytes already written, e.g. a WAV header),
  `sync`, `finalize`, `close` (leaves the `.partial` as evidence), and
  `hand_over` (Slice 07: the Python handle is closed and the `.partial` path
  is given to an external writer — the screen encoder process; then `write`
  is refused, `size` is measured on disk, `sync`/`finalize` reopen the file
  to `fsync` it and rename it once the writer has exited);
  the Python write buffer is **64 KiB** (`SPOOL_BUFFER_BYTES`): `flush`
  hands it to the OS (survives the death of the process, not a power cut),
  `sync` also `fsync`s; `flushed_size` counts only what left the process
  (for an external writer, the size on disk). The flush/fsync cadence is the
  owner's (`docs/capture.md` › *Loss bounds*);
  `write_payload` is the atomic one-shot write (screenshot);
- under Windows, the planned file path (folder, name and `.partial`) above
  `MAX_PATH` (259) is refused before any folder is created
  (`artifact_payload_failed`, message names the limit);
- the folder itself is not `fsync`ed (Windows has no directory fsync); a lost
  rename leaves the `.partial`, which recovery handles.

Not scene captures (D16): `runtime/scene-captures/` keeps 5 files / 24 h for
diagnostics; user artifacts have **no automatic retention**.

## Recovery

`ArtifactService.recover_pending()` runs at Core start, after
`SessionManager.start()` and before any writer. Every artifact still
`pending` belongs to a previous life:

| On disk | Result |
| --- | --- |
| final file already there (rename done, DB not updated) | `partial`, `artifact_recovered`, measured size |
| non-empty `.partial` | promoted to the final name, `partial`, `artifact_recovered` |
| empty or no `.partial` | `failed`, `artifact_payload_missing` (an empty `.partial` stays) |
| no payload reserved | `failed`, `artifact_interrupted` |
| payload unreadable or refused (junction…) | left `pending`, `core.artifact.recovery_skipped` (error), retried next start |

`recover_pending(owned=...)`: an artifact for which `owned` answers true has a
live owner that resumes it (a `transcript` projection resumed by the
recording transcriber, Slice 06); it stays `pending` and is reported in
`RecoveryReport.owned`. Pending artifacts are read in pages of 128 by a `(created_at, artifact_id)`
cursor: a page of payloads left `pending` (refused) never hides the ones after
it. Each recovered artifact gets its `artifact.finalized` event (`recovered:
true`) in the same transaction. Recovery never raises (a broken registry is
logged as `core.artifact.recovery_failed` and Core keeps starting). Recovered
evidence is conservatively `partial`, never `complete`: Jarvis cannot prove the
writer had finished. Capture-specific repair (WAV header, video container)
runs **before** this generic pass: `CaptureService.recover()` (Slice 05,
[capture.md](capture.md#recovery-at-core-start)) repairs and recovers its own
artifacts one by one through `ArtifactService.recover(artifact_id)` (same
rules) and `payload_files(artifact)` (paths and sizes for the repair hook);
the generic pass then sees only what remains.

## Deletion

Explicit user delete only; nothing is deleted automatically.

- deleting an artifact others derive from is refused
  (`artifact_has_dependents`, up to 5 ids named) unless `cascade=True`, which
  deletes its dependents transitively — derived evidence does not outlive its
  source silently;
- deleting a `pending` artifact (or a cascade containing one) is refused
  (`artifact_still_pending`): stop the acquisition first;
- a cascade larger than 256 artifacts is refused, nothing deleted (delete in
  parts);
- the deleted artifact's own relations to its origins are removed; origins
  stay;
- rows go first, in one transaction with one `artifact.deleted` event per
  artifact (`cascade_of` names the requested root); payload folders are
  removed **after** the commit. A folder that resists (locked file, unexpected
  entry — never followed or removed blindly) does not undo the delete: it is
  returned in `orphan_folders` and logged (`core.artifact.folder_not_removed`).

Activity events of a deleted artifact stay in the ledger: they carry ids and
small codes only, never content.

## Activity ledger

Factual backend truth of what happens to a Session (D10). Table
`session_activity`, ordered by `seq` (SQLite `AUTOINCREMENT`: monotonic per
file, never reused), never pruned.

Event: `event_id` (`jact_…`), `seq`, `kind`, `occurred_at`,
`jarvis_session_id?` (required for `session.*`, `context.*`, `capture.*`),
`context_id?` (required for `context.*`), `artifact_ids` (≤ 16),
`capture_ids` (≤ 16 tokens), `data` (≤ 16 flat scalars, strings ≤ 256).
**Never** raw media and never transcript text.

| Kind | Written by |
| --- | --- |
| `session.opened` | `SessionManager` (Core start without open Session, new Session) |
| `session.resumed` | `SessionManager.start()` resuming the open Session (once per Core start); on the first start after a migration its `context_id` is null, because the Session's `adopted` Context is created right after (its own `context.created`) |
| `session.closed` | `start_new_session()` |
| `context.created` | first Context of a Session, `create_context`, adoption (`context_origin: adopted`) |
| `context.activated` | `activate_context` (nothing when already active) |
| `context.dormant` | the previous active Context, before `created`/`activated`; the old Session's Context on new Session |
| `artifact.created` / `artifact.finalized` / `artifact.enrichment.updated` / `artifact.deleted` | `ArtifactService` |
| `capture.started` / `capture.stopped` / `capture.gap` / `capture.association_changed` | capture owner `CaptureService` (Slice 05, [capture.md](capture.md)): in the transaction of the capture row, or via `ArtifactService.record` for live gaps and Context switches |
| `transcript.segment.created` / `transcript.projection.updated` | transcription (Slice 06+), via `record` |

**Same transaction.** A Session or Context transition and its events commit or
roll back together: `commit_switch(activity=…)`,
`commit_contexts(activity=…)` and `insert_adopted_if_absent(activity=…)` call
`append_activity` inside their own `BEGIN IMMEDIATE`. Same for every registry
write. Order of a new Session: `context.dormant` (old), `session.closed`,
`session.opened`, `context.created` (new).

**Reading.** `ActivityQuery(after_seq, limit ≤ 500, jarvis_session_id?,
context_id?, kinds?, since?, until?)` returns `seq > after_seq` ascending: a
tail cursor (`latest_seq()` gives the starting point).

## HTTP API (Slice 09)

Served by Core (`jarvis/protocol/capture_routes.py`, facade
`jarvis/core/capture_api.py`), relayed by the Control Center under `/api`
(`capture_relay.py`); routes and error envelope: [capture.md](capture.md) ›
*HTTP API*.

| Route | Answer and bounds |
| --- | --- |
| `GET /v1/artifacts` | newest first; filters `kind` (comma list), `state`, `jarvis_session_id` (`current` = the open Session), `context_id` (`active` = the active Context), `since` / `until` (ISO-8601 **with** offset), `cursor` (`next_cursor`), `limit` 1..50 (default 20). Items are summaries: identity, state, times, size, dimensions, `has_payload`, `text_chars`, `preview` (≤ 160 characters) — never `text`, metadata nor `payload_ref`; transcript kinds carry `addressed: false` |
| `GET /v1/artifacts/{id}[?text_chars=0..16000]` | the artifact's metadata (`payload_ref` relative), `text` cut at `text_chars` (default 1 000) with `text_truncated`; never its bytes |
| `GET /v1/artifacts/{id}/relations[?direction=origins\|dependents\|both]` | provenance (≤ 256 per direction) |
| `GET /v1/artifacts/{id}/transcript` | bounded transcript of an audio, transcript or segment artifact ([capture.md](capture.md)) |
| `GET /v1/artifacts/{id}/payload` | the bytes, **for the interface only** (no MCP tool calls it): terminal artifacts only (`artifact_still_pending` 409), `artifact_no_payload` / `artifact_payload_missing` 404; one `Range: bytes=` range (`a-b`, `a-`, `-n`) → 206 with `Content-Range`; at most 8 MiB per answer (`MAX_PAYLOAD_CHUNK_BYTES`): a whole read of a larger payload is 413 `artifact_payload_too_large` (read by ranges), an open range is served by chunk; invalid range 416 `artifact_range_invalid` with `Content-Range: bytes */<size>` (a bound longer than 19 digits included: never Python's integer-size error). Headers: the artifact's MIME type, `Content-Disposition: inline; filename="<payload name>"`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, `Accept-Ranges: bytes`. The Control Center relays the bytes (`forward_bytes`, `Range` passed through) and refuses a body above 8 MiB with 502 `payload_too_large_for_relay` — never half a payload |
| `DELETE /v1/artifacts/{id}[?cascade=true&origin=user\|brain]` | explicit delete (*Deletion* above) → `{deleted, orphan_folders}` |
| `GET /v1/activity` | ledger tail of the **open** Session: `after_seq` cursor, `limit` 1..200 (default 50), `context_id` (`active` alias), `kind` (comma list) → `{events, latest_seq}`; ids and small codes only |

## Boundaries

- **Conversation events** (`docs/conversation-events.md`) stay the truth of the
  conversation *addressed* to Jarvis. Nothing here writes `conversation_events`;
  ambient room transcript never becomes an addressed turn (D17).
- **RuntimeJournal** (`runtime/trace.jsonl`) is diagnostic. `ArtifactService`
  mirrors `core.artifact.*` lines (ids, states, codes, counts); the ledger is
  never rebuilt from it.
- **Scene captures** keep their own diagnostic store and retention (D16).
