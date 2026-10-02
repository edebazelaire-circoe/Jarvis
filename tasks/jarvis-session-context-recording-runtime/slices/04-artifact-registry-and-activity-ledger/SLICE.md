# Slice 04 - Generic Artifact registry and canonical Session activity ledger

## Goal

Create the generic structured data layer that recording features will use: stable Artifact identities, payload references, provenance/relations, enrichment metadata, and factual Session/Context activity events.

## Context

Current scene captures/artifacts and `RuntimeJournal` are specialized. Conversation events are canonical for addressed Jarvis conversation, not ambient meeting evidence. This Slice creates a separate generic product evidence layer.

## Scope

### In scope

- Artifact domain contract and typed kinds/extensibility.
- Stable IDs, timestamps/time ranges, source, state, optional Session/Context association, payload ref, MIME/size/duration/dimensions and bounded metadata.
- Explicit ArtifactRelation/provenance contract.
- Durable payload directory conventions under the local data root with atomic finalize/partial recovery helpers.
- Canonical Session activity event contract/store/query/tail with context/capture/artifact event families.
- Versioned SQLite migration(s), indexes for time/type/session/context and schema snapshot.
- Backend hooks for automatic context activity events.
- Deletion/retention contract sufficient for user artifacts, including relation/cascade rules; user media must not inherit scene diagnostic retention.

### Out of scope

Actual microphone/screen capture, semantic AI enrichment, UI.

## Architecture constraints

- Large binaries remain files.
- Artifact acquisition does not require semantic description.
- Activity ledger is factual backend truth; `RuntimeJournal` remains diagnostic.
- Do not write ambient room transcript as addressed conversation events.
- Partial/incomplete artifacts are representable and queryable.

## Automated validation

`qa-verification` + `code-review` + `runtime-validation`. Exercise migrations, query bounds, path safety, atomic finalize, provenance validity, partial recovery, deletion semantics and no binary leakage into traces.

## Acceptance criteria

Later capture Slices can create/finalize/query an artifact and emit canonical activity without knowing media-specific database tables; provenance is explicit; activity is ordered/bounded/queryable; storage survives restart.
