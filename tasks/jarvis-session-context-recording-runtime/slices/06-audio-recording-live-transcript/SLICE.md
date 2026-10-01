# Slice 06 - Durable audio recording and live transcript artifacts

## Goal

Add explicit audio recording whose raw source is durably preserved and whose near-live transcript is derived into canonical timestamped artifacts without inheriting the PRESENTATION ambient lane's lossy archival semantics.

## Context

Current `AudioCaptureHub` is the single physical microphone owner in PRESENTATION and has reusable subscription machinery, but queued subscribers deliberately use `drop_oldest` and persist no PCM. `AmbientSegmenter` and `TranscriptionBackend` are reusable for utterance boundaries/STT. The target must keep passive ambient privacy behavior unchanged while giving explicit recording a durable path.

## Scope

### In scope

- Explicit audio-recording source adapter integrated with Slice 05 ownership.
- Durable spool/write path that receives source PCM/media before transcript dependency.
- Final audio Artifact with source/device/sample-rate/duration/time metadata.
- Near-live segmentation and STT derived from the durable/source stream.
- Immutable transcript segment artifacts/records with recording-relative and wall-clock time ranges.
- Readable whole-transcript projection/tail and retry from durable source.
- Explicit gap/partial semantics on source loss; STT lag/failure must not erase source evidence.
- Integration with existing device selection and microphone ownership without two competing physical streams.
- Preserve current ambient PRESENTATION lane as memory-only/freshness-oriented.

### Out of scope

Speaker diarization unless current provider/backend already supplies it reliably; do keep nullable speaker metadata/extensibility. No meeting-mode redesign.

## Architecture constraints

- No canonical audio recording sink may silently `drop_oldest`.
- Provider transcription failure is retryable independently of recording success.
- Raw accepted transcript evidence is append-oriented/immutable; later semantic summaries can revise projections, not raw evidence.
- Ambient transcript does not authorize actions.

## Automated validation

`qa-verification` + `code-review` + `runtime-validation`. Test slow transcription, provider timeout/retry, forced segmentation, ordering/timecodes, duplicate retry, microphone conflict, source loss, partial finalization, restart catch-up and PRESENTATION non-persistence regression.

## Human validation

Run only after machine QA is clean: physical microphone start/stop, audible-room sample, file playback/length sanity and transcript time alignment on the supported host.

## Acceptance criteria

Explicit recording produces a durable source Artifact and timestamped transcript evidence; transcript can lag/retry without source loss; errors/gaps are truthful; current passive ambient path remains non-persistent.
