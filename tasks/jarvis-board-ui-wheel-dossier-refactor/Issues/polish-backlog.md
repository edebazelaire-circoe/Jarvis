# Polish backlog (for Slice 08)

Non-blocking findings, kept here so Slice 08 (integration, accessibility, regression) picks them up. Each is
outside the acceptance of the Slice that found it.

## From Slice 01a QA (fixed Board type, schema v9)

- **No log line says the database was migrated.** The v9 step (like every SQL-string step) leaves no
  diagnostic; only the `.v8.bak` and the version row tell. Suggestion: one `core.state.migrated` info line
  per applied step, with `from`, `to` and, for a data step, the number of rows changed.
- **The brain brief writes the internal value.** `jarvis/runtime/board_brief.py` renders `Type : presentation.`
  / `Type : meeting.`; it should use the user words « Présentation » / « Réunion ».
- **`requested_kind` is logged with extra quotes.** `core.board.kind_change_refused` carries
  `preview(value)`, which quotes a string (`"'presentation'"`); log the bounded raw value instead.
- **`runtime/trace.jsonl` holds interleaved non-JSON lines** (seen during the 01a sandbox run): find the writer
  that bypasses the journal and make every line one JSON object.
- **The `.v8.bak` stays in WAL mode and a plain read creates `-wal` / `-shm` next to it.** The pre-migration
  copy should be switched to `journal_mode=DELETE` (or opened read-only by the procedures that inspect it) so
  that reading a backup never adds files beside it.
