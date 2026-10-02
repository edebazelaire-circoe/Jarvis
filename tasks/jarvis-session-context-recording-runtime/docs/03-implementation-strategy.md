# 03 - Implementation strategy

## Rollout principle

Build from identity and persistence outward. Do not start with shiny record buttons that have nowhere trustworthy to put their evidence. Humans have tried that approach in many products; it produces excellent demos and terrible data.

## Phase 1 - Establish the Session/Context contract

Slice 01 changes the canonical Session lifecycle contract and introduces SessionContext semantics without capture behavior. The main breaking point is current `SessionEndReason.CORE_RESTART` and `SessionManager._open_at_start()`.

The Slice must decide the compatibility approach for existing Board-required Session fields. New Context state must not become Board-scoped. Existing Board functionality should continue to pass until a separate Board-removal task exists.

## Phase 2 - Persist and reconstruct Context workspaces

Slice 02 adds versioned `jarvis.sqlite3` migration(s), repository/service adapters and filesystem layout under the configured data root. Follow `docs/local-data.md` exactly: migration append-only, backup before migration, fresh DB and migrated DB converge, update `tests/schema/` snapshot.

Slice 03 changes startup/relogin behavior to resume the open Session and hydrate the active Context into the agent/runtime. It must explicitly test crashes/restarts and avoid silently creating new Sessions.

## Phase 3 - Build generic artifact/activity primitives

Slice 04 creates the registry and canonical activity ledger before any recording adapter. This gives every later capture implementation one identity/provenance/indexing path.

Keep product activity separate from `RuntimeJournal` diagnostics and from addressed conversation events. Mirror diagnostics where useful but do not duplicate truth ambiguously.

## Phase 4 - Capture owner before capture media

Slice 05 defines the supervised capture owner, state machine, durable incomplete-state recovery and common API used by UI/MCP. Use fake sources first. Establish idempotency, start/stop races, crash recovery, permissions/errors and artifact finalization with no physical device dependency.

## Phase 5 - Add media families independently

Slice 06 adds explicit audio recording and transcript derivation. It reuses microphone/STT building blocks without inheriting the ambient lane's lossy canonical semantics.

Slice 07 adds generic desktop screenshot and screen recording. It must not route through scene-only capture or inherit its short diagnostic retention.

## Phase 6 - Intelligence and retrieval

Slice 08 adds incremental Context enrichment/live memory. Keep raw evidence immutable and make revisions explainable through provenance/cursors.

Slice 09 adds the public runtime API/MCP facade and indexed retrieval. Tool schemas/metadata must use current MCP catalog contracts.

## Phase 7 - Human control surface

Slice 10 integrates capture controls into the **existing floating left palette**. It is intentionally late: UI reflects backend truth rather than inventing a parallel state machine. Frontend work requires `/impeccable` and a Claude Work Agent when routing supports it.

## Phase 8 - Recovery and rollout proof

Slice 11 proves the complete lifecycle: session resume, context switch, artifact continuity, capture start/stop, transcript recovery/catch-up, Brain restart mid-capture where supported, and final documentation.

## Migration constraints

- Never rewrite an existing schema migration.
- Existing open Session rows created under old semantics must be adopted safely.
- Removing `core_restart` as a normal close reason does not require deleting historical rows that already carry that reason.
- A migration must not fabricate Context history that never existed. For an old open Session, create exactly the minimal default active Context required by the new runtime and mark its origin explicitly if such origin metadata exists in the chosen contract.
- Existing Boards/bindings may need compatibility adapters when startup no longer creates a new Session. Preserve their integrity until intentionally removed elsewhere.
- Media files are user artifacts. Do not place them under disposable `runtime/scene-captures/` or apply its 5-file/24-hour policy.

## Failure semantics

Every capture family needs stable named failures for at least:

- source/device unavailable;
- permission denied;
- already active/conflicting capture;
- storage unavailable/full/write failure;
- source lost mid-capture;
- finalize failure;
- transcription unavailable/timeout;
- recoverable partial artifact;
- unsupported platform/source.

Do not return success with a missing or unfinalized payload. Partial evidence is a first-class state.
