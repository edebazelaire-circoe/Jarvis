# Slice 08 - QA-1 (critical tier: qa-verification + code-review + runtime-validation)

Reviewed: `git diff ec6da364..196952e5` (3 S8 commits) in the detached worktree `bipr` at `196952e5`. HEAD checked before and after every step; `git status` clean at the end. No product code touched. Scratch scripts live outside the repo (session scratchpad). All runtime work used isolated temp data roots, never the live Jarvis.

## Verdict recommendation: APPROVE with polish. No BLOCKING finding.

The acceptance sentence ("killing/restarting cannot revert the presentation behind the last committed state") holds for process kill. It is not proven for a power cut, and the docs say so honestly.

## Acceptance: proved, with its limits

- Commits were already durable before S8: unique temp, `fsync`, `os.replace` retry, read-compare under the revision check. S8 adds a directory flush after the replace. No second persistence path, no buffer, no timer. Confirmed by reading `_write_file`.
- REAL DRILL (own scripts `drill_parent.py` / `drill_child.py`): Core stack (service + edit + history) in a child process on an isolated root, random scene.add/remove/reorder/rename (actor user/brain) + undo/redo, 8-scene docs padded to 6 KB and 15 KB per scene, `Popen.kill()` at random instants, restart, loop.
  - Run 1: 5 kills, 280 ack lines. Run 2: 30 kills, 337 ack lines, final revision 259.
  - Checked after every kill: disk revision never below the last acknowledged one; disk digest equals the acknowledged digest when the revision matches; disk at most last_ack+1 (an in-flight replace that landed); no torn or unparseable document; `.tmp` leftovers 0; the first undo after every restart answered `history_unavailable / not_recorded_since_start`; `last_recovery.unreadable` always empty; child stderr empty. 0 problems.
  - Not verified: power loss or OS crash (cannot be simulated here). `Popen.kill` on Windows leaves the OS cache intact, so it cannot prove the directory flush helps. Docs say "Not proven by a test here": accurate.
- Directory flush API (`_flush_folder_nt`, real calls on this Windows box): `CreateFileW(GENERIC_WRITE, FILE_SHARE_READ|WRITE|DELETE (0x7), OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS (0x02000000))` then `FlushFileBuffers`, `CloseHandle` in `finally`. This is the correct recipe (GENERIC_WRITE is required for `FlushFileBuffers`; BACKUP_SEMANTICS is required to open a directory). `argtypes/restype` set, the invalid-handle check works (`HANDLE(-1).value` compares equal to the 64-bit return; missing dir -> False). Results: real dir True, missing dir False, bogus UNC False, unicode dir True, read-only-attribute dir True. Cost 0.57 ms per call; `_write_file` of a 50 KB doc 2.6 ms with flush vs 1.5 ms without. POSIX path (`open O_RDONLY` + `fsync`, errors -> False) is read-only verified, no POSIX box available. Never-raises claim: only `OSError` is converted; an unexpected ctypes exception would escape after the replace already happened (unrealistic, see P4).

## Runtime evidence

| Check | Result |
| --- | --- |
| 7 new S8 files one at a time (history 23, history_service 33, history_routes 13, history_crash 6, recovery 18, durability 5, history_docs 6) | all pass |
| history_crash x3 | 6/6, 6/6, 6/6 (17-18 s each) |
| all 16 other presentation_studio_* files | all pass (crash, docs, domain, edit, edit_docs, edit_routes, edit_service, roles, routes, scene, scene_service, score, score_edit, score_service, service, store) |
| conversation_events 142, control_center_timeline_js 71, documented_routes 3, v2_architecture 8, schema_migrations 8, capture_relay 35, prefab_relay 22 | all pass |
| BASELINE.md (10 red tests) | file not found anywhere under bipr/bips; none of the files I ran was red, so no baseline red test was hit |

## Own adversarial results (what I tried, what happened)

- Exactness: 6 seeds x 300 steps of random control.set (strings with unicode/emoji/empty/50 chars, numbers 1, 1.0, True, 0, 100, 50.5, -1), rename, reorder, add (prefab v1/v2), remove, reset, set_controls, mixed with 25% undo and 20% redo, shadow model of canonical states. 0 mismatches (canonical JSON identical after every undo/redo), ring bounds asserted at every step, revisions monotonic (undo = new revision). Digest is canonical and keeps `1` / `1.0` / `true` distinct (checked on `canonical_json`).
  - File bytes are canonical-equal, not byte-identical (key order) - the Slice 05 P1 carry-forward, unchanged, docs say "canonical".
- Bounds, UndoBook level: 20 000 random record_edit/record_step/drop with entry sizes 100 B to 200 KB over 12 variants: 0 violations of 32 entries, 256 KiB/variant, 1 MiB total, 8 variants, 32 remembered drop notes. Service level: 9 presentations x 34 add/remove pairs of 1.6 KB scenes: 8 rings tracked, 32 entries each, 356 evicted + 1 ring dropped, `reserved` empty, eviction visible (`evicted`, `history_evicted`/`history_dropped` rows).
- Memory: 8 rings at 27 KB serialized each (220 KB) = 1.9 MiB Python heap (x8.7 on structured scene ops; x1.13 on blob-dominated). Worst case at the 1 MiB bound is about 9 MiB heap. See P5.
- `step` smuggling: top-level `step`, `direction`/`entry_id`, `step` inside an op, `_step`, `history`, via Core `/edits`, via the relay `/edits`, via the typed client, and in `/undo` bodies: all 400 `presentation_studio_invalid`, revision and ring untouched. Typed client signature has no `step`. Only in-process caller of `edit(step=)` is `PresentationStudioHistory._apply`. Unreachable from a request today. (A test for it does not exist: P3.)
- Actor: relay forces `user` on undo/redo/edits (claimed `brain`, `system`, missing, `root` all end `user`; existing test + M7). Core takes the actor from the body, as for edits (Slice 05 ISSUE, Slice 21 must be the only `brain` door).
- Undo vs outside write: `PUT` variant changing scenes -> `in_sync: false`, undo `stale / document_moved_on` and the ring is dropped (second undo `history_unavailable / document_moved_on`). Title-only save keeps the ring (undo applied).
- Concurrency (2 edits + 2 undos + 1 redo gathered, 60 rounds x 6 runs incl. a 10 ms delay after the write): 0 exceptions, 0 leaked reservations, ring digest equals the disk digest every round, losers `stale` (`presentation_studio_stale_revision` or `revision_moved`). One window found: P1.
- Pins/hook: at the instant `write_variant` runs for a `scene.remove`, `pins()` already holds `(lab.counter, 1)`; after commit the reservation is gone and the entry holds the pin. Failing write (storage_io) and a cancelled write: reservations empty (abort in `finally`). `pinned_versions` returns every requested id (unknown ids -> empty frozenset, duplicates fine, empty request -> `{}`) and my copy of 01a `checked_pins` logic accepts the answer (int versions in 1..9999, mapping, every id a key). Never raises (pure memory read). Only `scene.add` inverses carry pins (`pins_of`); no other op can change a scene's prefab version, so the set is complete for the current vocabulary.
- Recovery (200 presentations, 12 corrupted: truncated, empty, invalid bytes, missing variant file, torn manifest; plus a newer valid `.tmp` and a `.bak` beside intact docs): `start()` did not raise; 190 loaded, 10 unreadable, each a row with `presentation_studio_corrupt_document` and a `core.presentation_studio.recovery_failed` error row; the newer `.tmp` was swept and not adopted (revision stays 1, 2 swept); `.bak` never read; `get_variant` of a torn doc raises the same coded error (no silent fallback); `list_presentations` stays up (198 listed, 2 problems). A `presentations` path that is a file: no raise, `sweep_failed` + `recovery_failed` rows, `last_recovery` stays `None`.
- Content leakage: a secret control value never appears in diagnostics, conversation events, the undo wire result, or (existing test) the relay journal. Entries expose only op names, tier, actor, revision, byte count.
- Event status `undone`/`redone`: `status` is a free attribute string, no per-value list in `conversation_events.py` or `control_center_timeline.js`, and no new event type, so there is no Python/JS drift to check; parity tests green.
- Score carry-forward (Slice 10 I2): `score_problems` is a count after undo/redo, `None` without score, a score read failure is traced and does not undo the step. Test `test_undoing_a_scene_removal_reports_the_score_references...` passes. The "warn before deleting a referenced scene" part of I2 is still not done (S5 edit path), and nothing here tracks the score revision separately. Still open for Slice 05/07, not a S8 defect.

## Mutation testing (10 distinct mutations, 11 runs because M1 was done twice, each restored by `git checkout`, status clean after each)

| # | Mutation | Result | Killed by |
| --- | --- | --- | --- |
| M1a | remove the `_sync_folder(path.parent)` call in `_write_file` | KILLED | durability `test_the_write_order_is_file_fsync_then_replace_then_folder_flush` |
| M1b | `_sync_folder` body stubbed to `return True` (syscall never issued) | KILLED, but only because the stub does not return False for a missing folder; a stub `return os.path.isdir(folder)` would survive (P4) | durability `...never_raises_on_a_missing_folder` |
| M2 | in-place write instead of temp + replace | KILLED | durability write-order test (crash tests not reached, `-x`) |
| M3 | digest check off in `_step` | KILLED | history_service `test_a_write_outside_the_ring_...` |
| M4 | redo not cleared on a new edit | KILLED | history `test_a_new_edit_clears_redo_and_says_so` |
| M5 | entry-count bound off | KILLED | history `test_the_entry_count_is_bounded_...` |
| M6 | `step` readable from the request body (stripped from `raw`, passed on) | SURVIVED | no test sends `step` in a body (P3) |
| M7 | relay does not force `user` on undo/redo | KILLED | history_routes relay test |
| M8 | reservation (`begin`) taken after the write | KILLED | history_service `test_a_pin_is_held_before_the_document_stops_holding_it` |
| M9 | `abort` does not release the reservation | KILLED | history_service `test_a_failed_write_releases_the_reservation...` |
| M10 | sweep promotes a `.tmp` over the document (no `.bak` concept exists in the store, so `.tmp` is the mutant) | KILLED | recovery `test_an_orphan_temporary_is_swept_and_never_adopted...` |

9 of 10 killed, 1 survivor (test gap, code correct).

## Findings

None BLOCKING.

### POLISH

**P1 - an undo that lands in the gap between an edit's disk replace and its `commit` hook destroys the older history.** `jarvis/core/presentation_studio_autosave.py:143-147` compares the stored scenes digest to `ring.expected_digest`; a plain edit updates that digest only in `commit` (`presentation_studio_edit.py:162-175`), which runs after `await write_variant` resumes. Repro (`adv3b.py`): ring with 1 entry, edit B writes (held 50 ms after the write), undo arrives: undo answers `stale / document_moved_on` and drops the ring; B's `commit` then records a brand-new ring with only B (old entry lost, `history_dropped` warning traced). Next undo works on B only. Never a wrong state, but a user loses undo depth and gets a confusing "changed outside the history" message. Window is microseconds in production, 0 hits in 360 randomized rounds. Fix: when `self._book._reserved` is non-empty (an edit is in flight), answer `stale / revision_moved` without dropping the ring.

**P2 - an actor-policy refusal of the replayed inverse destroys the ring.** `autosave.py:158-162`: any `REFUSED` from `edit()` drops the ring (`entry_not_applicable`). Today both actors may run every op (`ALLOWED_EDIT_OPS`, `domain/presentation_studio_edit.py:111`), so it cannot trigger. The first time Slice 21 narrows it (the comment at `:109-110` plans exactly that), a `brain` undo of a user's `scene.remove` (inverse `scene.add`) is refused and the whole ring is dropped. Distinguish actor refusals (keep the ring, return refused) from deterministic state refusals (drop). Hand to Slice 21 entry conditions if not fixed now.

**P3 - test gap: nothing asserts that `step` cannot arrive in a body (M6 survived).** Behaviour is correct (I verified Core, relay, typed client, nested). Add one test posting `step` (top-level and in an op) to Core and relay `/edits` and `/undo`, expecting 400 and an untouched ring. `PresentationStudioEditService.edit(step=)` is also a public keyword: any future in-process caller (Slice 21 MCP) that passes a wrong `HistoryStep` only drops the ring (`record_failed`), so low risk, but say in the docstring that only the history may pass it.

**P4 - folder flush: proof and visibility gaps.**
- No test observes that a flush syscall is made: `test_..._write_order` wraps `_sync_folder` itself, and the other test only checks `True/False` (M1b). Patch `os.fsync`/`ctypes` or `FlushFileBuffers` to observe the call.
- `file_presentation_studio_store.py:98` says the result is read by `FilePresentationStudioStore.folder_sync`; that attribute does not exist (grep: only the docstring).
- `_write_file` discards the return value (`:88`): on a filesystem that refuses the flush nobody is told, not even once. Suggest a single warning trace per process (`folder_flush_refused`) so the honest-degradation claim is observable.
- `_flush_folder_nt` re-creates `WinDLL` and re-sets argtypes on every call; harmless, could be module-level.

**P5 - "1 MiB" is a serialized bound, not a memory bound.** `ops_size` counts compact JSON bytes. Measured heap is about 8.7x on real scene ops (220 KB serialized = 1.9 MiB heap), so the worst case at the bound is about 9 MiB per Core. Still hard-bounded and fine for a desktop, but `docs/presentation-studio.md` and `docs/local-data.md` should say "serialized size" and give the real order of magnitude.

**P6 - `start()` recovery cost grows with the library and runs in the startup path.** Measured 4.8 s for 200 presentations (24 ms each), so about 6 s at `MAX_PRESENTATIONS` (256); `v2_app.py` awaits it sequentially before `scene_captures.start()`. Not a correctness issue; consider bounded concurrency or checking only what the listing already reads.

**P7 - naming.** The history lives in `presentation_studio_autosave.py` / `domain/presentation_studio_history.py`, but there is no autosave in it (doc 09 s12 explains). Acceptable; a docstring pointer at the top of the file already exists.

### ISSUES (for the PM, not defects of this Slice)

- **I1 (Slice 07 UI): no coalescing means commit granularity = ring granularity.** Without a debounce, a text field committing per keystroke fills the 32-entry ring with 32 keystrokes and evicts every earlier meaningful step. The docs rely on `mode=preview` for drags. Slice 07 must commit on release/blur/Enter and use preview while typing or dragging; add this to its entry conditions.
- **I2 (Slice 21): blind undo.** `expected_entry_id` is optional; a voice "undo" without it undoes whoever edited last (the user's slider move). Slice 21 should require the `brain` path to read `/history` and pass `expected_entry_id`, and own the confirmation for undoing a user edit.
- **I3 (Slice 16): nothing calls `drop_variant` / `drop_presentation` yet.** Rings of a deleted presentation linger until the 8-variant LRU removes them (harmless, bounded). Add the call to Slice 16's entry conditions.
- **I4: per-entry bound 64 KiB below the 256 KiB document.** One batch of at most 16 ops removing large scenes can exceed 64 KiB; then the ring is dropped (`entry_too_large`) and the removal cannot be undone (the edit result carries `undo.available:false`). I could not reach it with real prefabs (16 fat scenes = 26 KB; scene payload cap 16 KiB means about 4 maximal scenes per 64 KiB). Bound is a PM decision, visible and documented.
- **I5: `last_recovery` has no route, health field or UI.** Visibility today = Error Logs viewer rows plus `GET list` problems. Slice 07 may want to surface it.
- **I6: `BASELINE.md` is not in the handoff folder** I was pointed to; the 10 known-red tests could not be cross-checked.

## Judgements requested

- **No debounce vs "Debounced/atomic autosave" in the Slice goal: accept.** The wording is a literal deviation, the goal and the acceptance sentence are better served: with a debounce there is a window where an acknowledged edit is not on disk, which the acceptance forbids. Cost is measured and small (a commit with flush is about 2.6 ms on a 50 KB doc, 1.1 ms more than without the flush). Do record the deviation in the Slice 08 notes/LOG (the docs already do, and the Extension-points row blocks a future debounce without a PM decision). Condition: I1 for Slice 07.
- **Ring survives variant switches with an 8-variant LRU, Slice 16 calls `drop_variant` on archive: accept** (I3).
- **Voice-undo confirmation belongs to Slice 21: agree**, with I2 and P2.
- **`psh_` id prefix: accept** (`psh_[0-9a-f]{12}`, `secrets.token_hex(6)`, validated by regex on input).

## Spec/design review notes (all as expected)

- Spec: restart recovery, bounded ring, redo cleared on new edit, explicit `history_unavailable` after restart, atomic write, kill drill all present. "Debounced" is the only deviation.
- Reuse: undo is an edit through `PresentationStudioEditService.edit` (same validation, base revision, durable write, event). Hook is synchronous `begin/commit/abort` around the single write; `commit` never raises and drops the ring on its own failure.
- Results: statuses `applied` 200, `history_unavailable` / `nothing_to_*` / `stale` 409, `refused` 400-409; 3 new 409 codes listed in route docs; `documented_routes` green; typed client returns result bodies for the 5 outcome statuses and raises on bare envelopes.
- Module sizes: history 479 lines, autosave 261, edit 325, service 573 (before S8 it was already large; S8 added about 72), store 407. No repo size rule found in CLAUDE.md; `history` is near the size where a split (bounds/book vs request/result types) would help.
- Docs: persistence contract, OPERATIONS, local-data, canonical names s12 are consistent with the code, except the `folder_sync` reference (P4) and the serialized-size wording (P5). The "unverified power-cut" statement is honest and prominent.

## Not verified

Power loss / OS crash; POSIX behaviour; two Core processes on one data root (documented unsupported); a real browser or any UI (none in this Slice); the full repository suite (only the files listed); MCP/agent paths (Slice 21); 16 maximal-payload scenes in one batch (I4); the live Jarvis (deliberately untouched).
