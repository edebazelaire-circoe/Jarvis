# QA-1 - Slice 02 (critical) - Presentation artifact contract

Reviewed `4dcc5cd4..a5dfdb51` (a59455a9, a5dfdb51) in detached `bipq` at a5dfdb51. HEAD checked before/after each step; `git status` clean at end. No product code changed.

## Verdict recommendation (PM decides): REWORK (small)

Contract met, tests strong (13/13 mutants killed). One BLOCKING (false `corrupt_document` on healthy file when a read races a save, plus a writer `storage_io` under heavy read contention). Fix is a few lines. Two POLISH items worth batching with it.

## Runtime evidence
All green, run one file at a time: domain 77, store 17, service 24, routes 11, crash 6 (x4 runs: 11.8s, 11.7s, 11.8s, 12.0s, all pass), docs 6, test_documented_routes 3, test_v2_architecture 8, test_schema_migrations 8. No SQLite/schema change (decision (a) file store); migrations rules N/A and `test_schema_migrations` still green.

## Mutation (critical tier). 10 distinct mutations + 3 variants, all KILLED, each restored (hash equal, git status clean)
| # | Mutant | Killed by |
| --- | --- | --- |
| 1 / 1b | `replace_with_retry` -> in-place write | store test; crash test alone also kills (so the kill test is not decorative) |
| 2 | unknown-key refusal off | domain |
| 3 | future `schema_version` refusal off | domain |
| 4 / 4b | id regex `.+` / store `_check_ids` off | domain / store |
| 5 | `scene:` / `scene_object` locator accepted | domain |
| 6 | scene bound off | domain |
| 7 | `variant_counter` invariant off | domain |
| 8 | read permission retry off | **only the subprocess kill test** (probabilistic; store/service pass). See P2 |
| 9 | stale-revision check off | service |
| 10 | DA/score swapped on parse | domain |
| 11 | sweep also deletes `presentation.json` | store |
"Stale cache" mutant not applicable: service has no cache (reads disk every call, verified).

## Findings

### BLOCKING
**B1 - read racing a save returns a false `corrupt_document` (409 + error log); writer can fail `storage_io`.**
`jarvis/adapters/file_presentation_studio_store.py:146` (inode check "replaced between inspection and opening") raises `CORRUPT_DOCUMENT` when an atomic replace lands between `lstat` and `open`. `get`/`get_variant` (`core/presentation_studio_service.py:112,116`) take no lock, the docs say "Core is the single writer, no concurrency", but reads run in threads beside saves. This is exactly the autosave (Slice 08) + UI read pattern.
Evidence (script `rw.py`, one service, 4 hot readers + 200 saves, 2 runs): 16 and 8 reader errors `presentation_studio_corrupt_document ... replaced between inspection and opening`, each logged `core.presentation_studio.failed` at `error`; in both runs the writer died with `presentation_studio_storage_io: PermissionError` (Windows refuses replace while a reader holds the file; `replace_with_retry` budget exhausted). At 1 reader polling every 20 ms: 0 errors in 3x200 saves, so risk is contention-dependent but real and reproducible. No data lost (nothing stored is corrupt), but a healthy store is reported as corrupt and the Error Logs get false alarms.
Fix: take the service lock (or a read/write lock) for reads, or retry the open once on inode mismatch instead of declaring corruption. Add a concurrent read/save test (none exists: only two saves race in `test_two_concurrent_saves...`).

### POLISH
**P1 - lone surrogate in a resource locator/title -> `UnicodeEncodeError` -> HTTP 500 `internal_error` instead of 400.**
`domain/presentation_studio.py:525` `dump_document` encodes UTF-8 outside the typed errors; reached from `service:165` inside the lock. Reproduced at service level: `save_presentation` with `resources=[{"kind":"note","locator":"a\ud800b"}]` (JSON `"\ud800"` is accepted by the JSON parser; `ResourceReference` accepts it) -> `UnicodeEncodeError`. Nothing written (encode precedes write), failure is visible (500 + `unexpected` error log), so not data loss, but a caller error is mis-classed. Titles are safe (`isprintable`). Fix: refuse non-encodable text in `resource_from_dict` or catch in `dump_document`.
**P2 - read retry (`retry_on_permission`, store:~152) has no deterministic unit test.** Mutant 8 survives store+service tests, killed only by the probabilistic subprocess kill test. Add a monkeypatched `PermissionError`-once test.
**P3 - parent cycles accepted.** `check_consistency` (domain:425) rejects self-parent only; `a.parent=b, b.parent=a` builds a valid `PresentationView` (reproduced). Slice 16 owns graph ops, but a loader that accepts a cycle will hang naive ancestor walks. Cheap to reject now.
**P4 - `_STAMP` uses `\d`** (domain:72): matches non-ASCII digits at the regex stage (still rejected later by `strptime`; harmless today). Use `[0-9]`.
**P5 - locator hygiene is inherited, not added.** `ResourceReference` (reused, correct) lets `\x00`, newline, `../x`, `//host/share`, `file:///...`, drive paths through for `web_page`/`document`; ` scene:abc` (leading space) and `scene%3A..` bypass the `scene:` heuristic. Never dereferenced in this Slice; re-check when a consumer resolves locators (Slice 11/12). Doc line "allowed-scheme locators, no markup" is true but could say "no path check".

### ISSUE (out of scope)
- Two Core processes on one data root: lost updates (2 processes x 60 saves: 117 successes, final revision 61) and spurious `corrupt_document`; startup `sweep` could delete another process's live `*.tmp`. Documented single writer; no lock file. Open an Issue only if multi-Core on one root is ever possible.
- Parent/variant graph integrity beyond reference (Slice 16).

## Checks with no finding
- Completeness vs SLICE.md: identity/title/metadata, active variant ref, ordered scene refs, DA + score refs, resource refs, validation, serialization, round-trip, runtime state excluded: all present and tested.
- Reuse: `ResourceReference`, `PrefabRef`, `file_replace`, `safe_folders`, staging pattern reused, nothing copied; no prefab definition field in schema (unknown-key refusal + test).
- Domain purity: only `jarvis.domain.*`, stdlib. `test_v2_architecture` exception: **justified**, identical to the existing `file_prefab_library` precedent (constructed only, injected through the port).
- Data rules: nothing versioned, no DB. Ids are strict `[0-9a-f]{n}\Z` (fullwidth digits, trailing newline, `..`, device names refused before any disk access). Bounds: title 80, 64 scenes/resources/variants, 256 KiB doc (64 max resources at 300+120x2 chars saves fine), 256 presentations, body 256 KiB. NaN/Infinity/dup keys/100k-deep nesting refused cleanly (typed). Future schema refused, file untouched, never rewritten.
- Concurrency: 20 same-revision saves in one service -> exactly 1 wins, 19 `stale_revision`. Delete folder during save -> typed `unknown_variant`, no crash, no orphan.
- Errors typed and logged (`failed`/`refused`/`unreadable`/`unexpected`); no swallowed `except` without `# intentional` reason; `_trace` swallow is deliberate and tested.
- Routes and docs parity: 7 routes in doc table and routes module; `test_documented_routes` green. Typed client present, quotes ids, no `forward_json` relay (tested).
- Doc claims spot-checked true: file layout, codes/status, "mutation-checked kill test" (mutant 1b), single-writer wording (**partly false for reads, see B1**: "reads hit disk every time" is true, "no concurrency" is not).

## Implementer's 4 open questions
The prompt did not include them and the Slice folder, LOG.md, commit messages and bips contain no list, so I could not answer them item by item. Views on the decisions most likely meant: (1) file store over v9 migration: agree, reasoning in docs is sound and consistent with R3; (2) no `StudioActor` yet: agree, no consumer; (3) arch-test exception: justified (precedent); (4) `archive/` not created and `variant_counter` owned by Slice 16: agree. Please resend the actual 4 questions for a real answer.

## Not verified
Live Core process end-to-end (only in-process aiohttp tests and the service harness; no running JARVIS, no browser, no Control Center since there is no UI in this Slice). HTTP-level repro of P1 (inferred from route boundary code: any non-typed exception -> 500). POSIX behavior (Windows only). BASELINE's 10 known red tests not re-run (outside the touched files).
