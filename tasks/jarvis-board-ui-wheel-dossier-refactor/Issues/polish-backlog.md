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

## From Slice 01b QA and sandbox run (derived interaction mode)

- **No end-to-end test that a `switch_noop` stops a Studio run.** `test_board_switch.py:314-329` covers the
  mode service only. Add to `test_presentation_studio_playback_service.py`: run on an Assistant Board, switch
  to the active Board, assert stop `mode_changed_by_user` and assistant mode.
- **`docs/presentation-studio.md` §6 (~l. 1819)** does not say a switch to the already-active Board also stops
  the run (only the failure table l. 1826 and `interaction-mode.md` do).
- **The brain is not told the mode was re-applied on `switch_noop`.** `workspace_boards.py:333-335` answers
  `unchanged` (« Déjà sur … ») although a Studio run may have stopped; relay `mode` / `mode_source`.
- **Stale comments** in `jarvis/runtime/control_center.html:1944-1946` (« sélecteur à trois choix ») and
  `:2245-2246` (409 reserved / 503 saved-not-applied cases that no longer exist); docstring
  `jarvis/domain/presentation_studio_roles.py:189` (« Board preference was reapplied »).
- **`settings_get` / `settings_describe` answer « Réglage inconnu » for `interaction_mode`** while
  `settings_set` gives the guiding `interaction_mode_derived` refusal; return the same code and sentence.
- **Core refusal trace logs a missing field as `"NoneType"`** (`_mode_value`); log `null` / `absent`.
- **Versioned `jarvis_local_v1.egg-info/SOURCES.txt:317`** still lists the deleted `interaction_mode_settings.py`
  (pre-existing generated file).
- **Agent behaviour, cross-cutting (Issue candidate, not 01b):** when a Board session is resumed after a switch
  announced in a previous turn was executed and then left, the brief's « Déjà dit » still carries « La bascule
  se fera à la fin de ce message » and the model claimed a switch was « déjà programmé » (sandbox evidence
  `s01b/evidence/trace-turn-b2.txt`). The Board-session context should mark an announced switch as done/left,
  or the brain should verify `board_get_active` before stating a switch state.

## From Slice 05 QA (Dossier contract and projection) — targets Slices 07/08

1. **Title of a Ranger note** shows the file name with its digest suffix (`pistes-de-financement-2352da72`) instead of the `#` heading of the note (Slice 07 view, or a title read from the heading).
2. **After `no_visible_page`** the agent promised « je la rouvre dès que l'interface est visible »: harden the `ERROR_SENTENCES["no_visible_page"]` sentence (nothing reopens by itself; say so, no promise).
3. **The agent read a note with `Read` on an absolute path** instead of `board_memory_read` (prompt/tool guidance, Slice 08 agent trace).
4. **An explicit drop on the Board** is listed as « ajouté automatiquement (Board actif à sa création) »: the drop links with `origin=active_board`; tell a drop apart (upload `provenance`) in the Dossier provenance.
5. **`present` echoes `entry_id` in the received case**, not canonicalized to the file name on disk (`Summary.md` vs `summary.md`).
6. **`memory/stat` gives no `sha256`**: an editor must `memory/read` the whole file to get the `expected_sha256` of a safe replace.
7. **Navigation doc** « 200 `{state…}` » reads as if every answer were a 200; say first that `no_visible_page` / `command_expired` are 504 refusals (`docs/dossier.md` › *Agent -> UI navigation*).
8. **`dry_run` / `backing` does not check the active Board**: it answers `rangeable` where Ranger then refuses 409 `dossier_board_not_active`; say the Board rule in the preview.
9. **Ranger of an Artifact window presented from Board A while B is active** links the Artifact to B without the user seeing it; consider refusing or saying the cross-Board link.
10. **`boards_of_artifact(limit=500)`** in `_resolve_entry`: an Artifact linked to more than 500 Boards would read as not in this Dossier; use a direct link lookup.
11. **Duplicate comment on the `DOSSIER_PAGE_TOKEN_MARKER` line of `control_center.py`** — fixed in the S05 rework commit (explorer comment restored on its own line).
12. **Brain, outside the Slice:** the 8 s turn budget was exceeded, and a stray text block « Single small file read is allowed. » appeared in the answer.
