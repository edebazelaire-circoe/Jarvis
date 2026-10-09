# QA-1 - Slice 01a (prefab capacity for Studio scene sources), critical tier

Reviewed: bipr detached at 0f32e86a (diff cf5bc1f2..0f32e86a, commits 8d4cdbe9 + 0f32e86a). HEAD and `git status` checked clean before and after every step, including after each mutant. No product file modified (all mutants restored by `git checkout`). Python: jarvis .venv, PYTHONPATH=bipr, `import jarvis` verified to resolve to bipr.

## Recommendation: approve with POLISH (no BLOCKING)

Core safety invariants hold in tests, mutations and a real filesystem drill: a pinned version is never moved, bytes are identical, archive is one rename, numbers never reissued, user and base ids untouched, no registry or failing registry means nothing archived. Retention is inert (no registry wired in v2_app). Several defects below make the feature fragile once Slice 06 wires it; P1 to P3 are cheap and I recommend a short rework or a tracked follow-up to Slice 06 before any registry is wired.

## Runtime evidence (all foreground, one file at a time)

| Command | Result |
| --- | --- |
| test_prefab_retention | 21 passed |
| test_prefab_retention_crash (run 3 times in total) | 6 passed each time (3.3 s) |
| test_prefab_draft_coalescer | 9 passed |
| test_file_prefab_library | 24 passed, 2 skipped (symlink privilege, WinError 1314, environment) |
| all other test_prefab_*.py (base_behaviors_js, base_catalog, base_lock, browser_js, checklist, checklist_js, domain, events, frame_containment, host_js, library, protocol_js, relay, routes, service, shim_js, witness) | all passed (10, 39, 4, 4, 19, 18, 182, 26, 21, 18, 25, 14, 22, 25, 44, 14, 18) |
| test_scene_service_prefab 18, test_display_mcp_prefabs 23, test_documented_routes 3, test_schema_migrations 8, test_v2_architecture 8, test_mcp_catalog 81 | all passed |
| scripts/measure_prefab_capacity.py | **CRASHES** (see P4) after about 1 min |

Tool budget of jarvis-display: I built the real catalog (`build_catalog`) at cf5bc1f2 and at 0f32e86a: declared native surface 83 475 bytes both times, jarvis-display 39 516 bytes both times, delta 0. Ceiling is 84 000 so measured headroom is **525 bytes** (the "484" in the brief did not match; the test file's comment says 83 475 / 84 000). The new MCP sentences live in `PREFAB_ERROR_SENTENCES`, a runtime result string, not a tool description, so they cost nothing in the budget.

### Real end-to-end drill (isolated temp data root, real FilePrefabLibrary + PrefabService, fake registry pinning {3, 10, 20})
- 70 saves of `presentation-studio.scene1`: 0 errors. Live at end: 3, 10, 20, 44..70 (30). Archived 40 (1,2,4..9,11..19,21..43). Retention started at 32 live, kept last 16 plus pins.
- Pinned v3, v10, v20: sha256 of all 5 files identical before and after.
- Every archived folder holds all 5 files. Provenance: v70 is `revision` with `derived_from` v69; v44 derives from v43 which is archived (chain still readable on disk, see I2).
- Restart with a new service: next version 71 (monotonic), archived `get(id, 1)` gives `unknown_version`, pinned versions still load. No `.staging-*`, `.lock`, `.tmp` files. `scan().problems` empty (`.archive` is skipped by the id scan, scanned separately).
- Scan cost with 15 360 archived folders (384 ids x 40): 0.053 s. Archive growth is cheap to scan.
- Adversarial, two OS processes saving the same id 60 times each against one data root (pin v2): no duplicate numbers, no traceback, pin v2 survived, 58 clean `version_exists` refusals (no cross-process lock exists; pre-existing behaviour of publish, now also around a retire).
- Adversarial registries (32 live versions, one save): raises -> nothing archived, save succeeds as v33. Returns None -> same. Returns `{}` (missing key) -> **archives with no pins** (P2). Returns string versions `{"3","4"}` -> archives v3 (P2). Hangs -> save never returns and an unrelated user prefab save is also blocked (P3).
- Stale archive slot (folder `.archive/<id>/1` already present while live v1 exists): every later save retries v1 and stops; id reaches `version_limit` at 64 live although 47 versions are retirable (P1).
- Look-alike ids against `is_prefab_id` and `is_retention_id`: `presentation-studio` no, `Presentation-Studio.x` no, `PRESENTATION-STUDIO.x` no, unicode hyphen `presentation‐studio.x` no, cyrillic `presentation-studio.а` not a valid id, `lab.presentation-studio.x` not retention, `jarvis.presentation-studio.x` not retention, `presentation-studio.x/../../jarvis.y` not a valid id. Case-insensitive FS collision is impossible because ids are `[a-z0-9_-]` only. Note `is_retention_id` alone returns True for non-ids such as `presentation-studio./x` (P6); every caller validates first.

### Mutation testing (10 mutants, all killed, all restored, status clean after each)
| # | Mutant | Killed by |
| --- | --- | --- |
| M1 | ignore pins in `retirable_versions` | test_retirable_versions_keeps_the_last_ones_the_pinned_and_the_refused |
| M2 | namespace matches every custom id | test_the_namespace_policy_covers_only_studio_custom_ids |
| M3 | archive not counted as occupied | test_prefab_retention (DID NOT RAISE, line 97) |
| M4 | drop keep-last | test_retirable_versions_keeps_the_last_ones... |
| M5 | retire tampered/unreadable | test_a_tampered_version_is_never_retired |
| M6 | registry failure treated as open (`return {}`) | test_a_failing_registry_archives_nothing_traces_an_error... |
| M7 | copy+delete instead of `os.rename` | test_prefab_retention_crash:96 |
| M8 | coalescer merges different actors | test_a_different_actor_or_origin_flushes_the_pending_burst_first |
| M9 | cap off-by-one (`>` for `>=`) | test_prefab_retention:97 |
| M10 | id eviction ignores pins | both test_a_new_studio_id_at_the_quota_archives... and test_the_id_quota_never_evicts_pinned_or_fresh_ids... |

The implementer's invalid 9th mutant is not relied on. Gaps the mutants do not exercise: P1, P2, P3, P5 below have no test.

## Findings

### BLOCKING
None.

### POLISH (recommend fixing now or recording as Slice 06 entry conditions)

**P1. One stuck version permanently disables retention for an id.** `prefab_service.py:682-698` (`_retire`) stops at the first failure, oldest first. Scenario (reproduced): stale `.archive/<id>/1` exists (e.g. a restore done by copy instead of move, which the docs invite: "remettre le dossier"), or on Windows the oldest version folder is open in Explorer or locked by an antivirus (`retry_on_permission` then `storage_io`). Every later save retries the same first version, nothing else is retired, the id hits `version_limit` at 64 live although 47 are archivable. Recovers only by hand or after unlocking. Fix: skip the failing version and continue, trace once per version; and make the adapter message distinguish "slot taken" from "locked".

**P2. The port contract "all or raise" is only trusted, not checked, and a partial answer fails open.** `prefab_service.py:719-733` and `prefab_retention.py:retirable_versions` use `pinned.get(prefab_id, frozenset())`. A registry that returns `{}`, omits a requested id, returns a non-mapping value type or non-int members (strings) leads to archiving pinned versions (reproduced for `{}` and for string members; `None` is caught by the broad except). The sparse-mapping reading is plausible for a real registry ("only ids with pins"), so the contract is ambiguous: either state in the port docstring that missing keys mean "no pins" and add a type check, or require every requested id as a key and treat otherwise as failure (fail closed). Same for `CompositePinRegistry` (it pre-seeds keys, so a composite is safe against sparse stores). Suggest: validate `isinstance(v, int)` for all members and key presence; any violation counts as registry failure (traced `retention_failed`).

**P3. A registry that never answers blocks every prefab save in Core.** The registry call runs under the global `_write_lock` with no timeout (reproduced: unrelated `test.counter` save is blocked as long as the registry hangs). Retention is the only feature that makes the library write path depend on a foreign component. Fix: `asyncio.wait_for(..., timeout)` (a few seconds) treated as registry failure (fail closed), or document the registry as in-memory and non-blocking. Slice 06 must honour this either way.

**P4. `scripts/measure_prefab_capacity.py` does not run and the documented table is not reproducible.** Scenario 2 (`MAX_PREFAB_IDS - 1` studio ids + probe) raises `id_limit` ("dont 511 du Studio (au plus 384)") because the script names all ids `presentation-studio.sceneN` and the new 384 quota applies; the script dies after 1 minute with a traceback, no output (the first scenario's numbers are lost, `--json` too). The docs (`prefabs.md:308-311`) show a 511-id row, so the row was either measured before the quota or by another script version. The script docstring also says "64 ids x 64" while the code runs 96 x 16. Fix: name the 511-id scenario ids outside the namespace (user ids), print incrementally, align docstring and doc. The modelled part (rehearsal and id model) is plausible and labelled as assumptions; the doc numbers I spot-checked (970 = 15x64+10, 5 presentations x 105 ids = 525 > 512) are consistent.

**P5. Cancelling a caller can drop a pending draft of another actor.** `prefab_draft_coalescer.py` `submit` -> `await self._flush_one(...)` is not shielded. When actor/derived_from changes and the second caller is cancelled during the flush, the first burst has already been removed from `_bursts`, `save` is cancelled, and the first caller receives `RuntimeError('CancelledError()')` (reproduced: svc saved nothing, pending empty). The draft is lost with a (misleading) error, not silently, and with the real service the cancelled `asyncio.to_thread` publish may still complete on disk after the lock is released (possible `version_exists` on the next save). Same exposure if a timer task is cancelled at loop shutdown. Fix: run the publish as its own task (`create_task`) and `shield` it, or store the task in `_inflight`.

**P6. `is_retention_id` does not validate the id itself.** `domain/prefab.py` `startswith(...)` only; returns True for `presentation-studio./x`, `presentation-studio.x\n`, `presentation-studio.K`. Safe today because every caller (service via validated manifest, adapter `retire` via `is_prefab_id`, scan names) has validated first; add `is_prefab_id(prefab_id) and` for defence in depth since the function guards destructive moves. The adapter-level `retire` itself has no namespace guard (a future caller could archive a user or `jarvis.*` data-root version); the service guard is the only barrier.

**P7. Error messages.** (a) Core messages in this file are English (`"{id} has reached its version limit"`, `"the library holds ... ids already"`), the new ones are French with vouvoiement ("enregistrez", "réutilisez"). The MCP layer is French with tutoiement ("enregistre", "réutilise"), and appends `(Core : <message>)`, so the agent reads tu then vous and the same advice twice. Judgement: keep French (the human-facing sentence is the point) but use one register: the MCP sentence tu, the Core message either short English like its neighbours with the French left to the MCP/UI sentence, or tu. (b) `id_limit` message for a **non-Studio** save says "ou libérez des scènes du Studio", but no user action frees Studio scenes (no delete, no restore API, retirement only runs on a Studio save). (c) For a Studio id at the 384 quota with **no registry**, the note says "tous épinglés ou récents" though nothing was examined (`_make_room_for_id`: note is set before knowing why `_retire_idle_id` returned None); it should say retention unavailable like the version message does. (d) the status 409 matches `tampered`/`version_exists`; fine. Cap change `invalid_definition` (400) -> `version_limit`/`id_limit` (409) is a deliberate contract change, documented in prefabs.md, test updated; no other consumer of the old code found by grep.

### ISSUE (tracked, not defects of this Slice; for Slice 06/08/16/17/20 and PM)

**I1. Archived versions have no restore path except by hand** (documented: stop Core, move folder back). A whole-id eviction (oldest unpinned Studio id older than 1 hour, `_retire_idle_id`) is a move, never a delete, so user work is recoverable, but there is no tool and the id then reads `unknown_prefab`. Also nothing stops the brain or user from saving their own prefab as `presentation-studio.<x>` via MCP `prefab_save`; such an id is eligible for archive when unpinned for an hour once the Studio quota fills. The namespace is reserved only by documentation. Decide in Slice 06 whether `PrefabService.save` should refuse that prefix for non-Studio actors.

**I2. Provenance chain** : `derived_from` of a live version may point at an archived version (v44 -> v43). The chain is intact on disk, but `get`/fork from an archived version fails (`unknown_version`/`unknown_prefab`) and nothing in the catalogue shows that an ancestor exists in the archive. Acceptable; mention for Slice 16/17 variants that fork from an old version: they must pin it first.

**I3. Live frames and archiving.** `PrefabService.bundle` and `_lookup` read only the current catalogue (reloaded by `_refresh` on every save; no stale cache), so an archived version answers `unknown_version`. The browser host keeps up to 64 bundles in an LRU (`control_center_prefab_host.js:82`) and refetches `GET /api/prefabs/{id}/{version}/bundle` on a cache miss or re-render; a frame that is already running keeps its srcdoc, but a reload of an archived pinned version would fail with a visible `bundle` band. So "a live scene never loses its bundle" depends entirely on the Slice 06 registry including every global-scene object and every host-cached/displayed version, not only documents. Pin-after-publish race (admitted by the implementer): publication and pin are two steps. Protection is the keep-last 16 (and 1 h for whole ids); a pin written for an old, unpinned version (variant/scene-local variant fork of v20) after retention ran is lost. Doc states the writer-registers-first rule; Slices 16/17 must test it. Note that instantiating via `validate_instance` then writing to the scene is also not atomic with retirement.

**I4. Pending coalescer burst on shutdown/crash.** Nothing in Core calls `flush()` yet (not wired). At loop end a pending burst is simply never published and its waiters never resolve (reproduced: `pending_ids` non-empty, nothing saved). The doc says flush on "arrêt de Core"; Slice 06 must wire `flush()` in the shutdown path and decide whether a crash-lost draft is acceptable (the source remains in the editor). Merge safety is good: last candidate wins per id, actor or `derived_from` change flushes first (M8 killed), all waiters share one publication or one typed error, a burst never merges two actors.

**I5. Inert state is safe and nothing is wired half-way.** `PrefabService(..., pin_registry=None)` is the default; grep shows no `pin_registry=` in `v2_app` or elsewhere, no coalescer instantiation outside tests and docs. With no registry: a trace-once warning `retention_inactive`, hard cap 64 gives typed `version_limit` (reproduced), Studio-id quota 384 gives `id_limit` even when the library is not full (acceptable, only ids in a namespace no code uses yet). Schema/migrations untouched (test_schema_migrations passes; no SQLite change).

**I6. Per-id retention only runs when an id holds at least 32 live versions and the save is that id's own.** Tampered versions are never retired (by design) and accumulate toward the hard cap. Archived folders are never pruned (unbounded disk growth, about 3.5 KiB per version, scan cost negligible at 15k folders).

## Checks against the brief (compact)
- Immutability of pinned versions, exact-version pins: held (drill, M1, M4, tests `pinned_versions_survive_every_pass_byte_for_byte`).
- `catalog.lock.json` / `jarvis.*`: `prefab_class` guard, base and package never written (test passes; M2 killed). User prefabs untouched (test `user_prefabs_are_never_retired...`).
- Archive: single `os.rename`; no copy-delete anywhere (M7 killed by crash test); target slot taken -> refuses without moving (P1 consequence); id folder `rmdir` only when empty. Windows rename failure -> `storage_io`, traced, pass stops (P1). Long paths: archive path adds only 9 characters, scan lists only folder names under `.archive`; not exercised past MAX_PATH (not verified).
- Case-insensitive FS: impossible for ids; archive slot comparison uses `lexists`, fine.
- Kill during rename: crash test covers each retire step (6 passes x3 runs); on NTFS a directory rename is atomic.
- Coalescer: exception propagation tested; cancellation issue P5; event loop close I4.
- v9999: `version_limit`, tested (`test_the_last_numbered_version_9999...`).
- Docs: `prefabs.md`, `local-data.md`, `presentation-studio.md` consistent with code, except the measurement table (P4). The "484 bytes" headroom is not in the repo docs I could find; measured headroom is 525.

## Answers to the implementer's 4 questions
1. Who builds the Studio `PrefabPinRegistry`: Slice 06 builds it from the Slice 02/04/05 stores (presentation store, scene documents, edit-tier state) and must also cover the live global scene and every frame the host may reload. Slices 08 (undo stack: registers pins), 16, 17, 20 add their own stores through `CompositePinRegistry`. Add P2/P3 (shape check, timeout) to Slice 06's entry conditions.
2. Slice 08 registers undo-stack pins: yes, with the rule that a store registers an old version before it is written to any document.
3. Defaults 32 trigger / 16 keep / 384 ids / 1 h grace / 2 s quiet / 10 s max: accepted; no reason found to change. (The model in the script shows coalescing alone only postpones the cap, retention is what carries a long rehearsal; the 1 h grace is a time bound on an unlocked race and acceptable.)
4. Message language: keep French but one register (tu, like the MCP neighbours) and drop the duplicated advice between the Core message and the MCP sentence (P7).

## Not verified
- Behaviour on a real Windows locked directory (simulated only by a stale slot), long-path (> MAX_PATH) ids, symlink cases (skipped by environment).
- UI rendering of the new codes in the Control Center (no consumer found; no browser run).
- Cross-process archive races beyond the 2-process save race above; kill -9 during rename beyond what the crash test simulates.
- Full test suite outside the files listed above; the 10 baseline red tests were not part of the runs.
