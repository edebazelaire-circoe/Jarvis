# Slice 12 evidence — Remotion Studio authoring workspace and publish round trip

Commits: `8f271c37` (code and tests), `3c88f090` (docs, wording after the real run, real round-trip test), `4f2a6baf` (test wait on the
final wording). Design: `../DESIGN.md`. Contracts: `docs/remotion-studio.md` § 2 bis, `docs/presentation-studio.md` › *Remotion Studio
round trip (Level 3, Slice 12)*. **No schema change, no migration** (file stores only).

## Real runtime / real browser (`roundtrip.json`, tested head `4f2a6baf`)

`tests/unit/test_remotion_studio_roundtrip_real_browser.py` with `JARVIS_REMOTION_RUNTIME_DIR` = the gate runtime (only read: its
`node_modules` is copied into the throw-away data root, Remotion Studio's guard needs esbuild under that root), real Core
(`RemotionStack`, real compiler), real `remotion studio`, headless Chrome over CDP, free loopback ports. The live Jarvis and the user's own
Remotion Studio were never contacted. Home path and user name redacted at write time.

| Step | Measured |
| --- | --- |
| private runtime copy | 7.6 s |
| Remotion Studio open, cold (webpack) | 62.0 s |
| edit `src/Scene.tsx` in the workspace → Remotion Studio's page shows it, same document (HMR, no render) | **0.69 s** |
| « Publier » click → « Publié dans la variante … » (real esbuild build, new version, pin) | **0.90 s** |
| Variants stage mean RGB before / after publish / after a Core restart | (176,16,16) red → (0,224,255) cyan → (0,224,255) |

Sample source: `sample-Scene.tsx` (background `#00e0ff`, text `STUDIO-EDIT-OK`).

| File | What it shows |
| --- | --- |
| `studio-before-edit.png`, `studio-after-edit.png` | Remotion Studio's own page on the scene, before and after the workspace edit (HMR) |
| `variants-unpublished-1280x720.png` | Variants: « Remotion Studio est ouvert sur cette scène … 1 fichier modifié dans Remotion Studio, pas encore publié : la variante n'a pas changé. » + « Publier dans la variante… » |
| `variants-publish-confirm-1280x720.png` | the confirmation (scene, files, new version, base kept, what refuses it) |
| `variants-published-1280x720.png` | « Publié dans la variante : nouvelle version de la scène (v1) ; la version d'avant reste disponible. » + « Revenir à la version d'avant », the new version playing |
| `variants-after-restart-1280x720.png` | Core life 2 on the same data root: Variants plays the published version |
| `variants-*-000.png` | half-size captures of the Player frame used for the colour measures |

After the restart the Studio view says `stopped` / `core_stopped`, base = the published pin, `unpublished: 0`.

## Adversarial and regression tests (one file per process, fresh `JARVIS_DATA_ROOT`)

| File | Result | Adversarial cases |
| --- | --- | --- |
| `test_remotion_studio_publish.py` (new) | 26 passed, 1 skipped | stale base → conflict; concurrent write between check and door → conflict; base not seen by the page; symlink (skipped: no symlink privilege on this account), junction folder, replaced `public/`, hard link → refused, target never in the library; top-level / generated / bad-name / CSS / hidden / non-UTF-8 files; hostile relative paths; `zod`, `fs`, `node:child_process`, `@remotion/renderer` refused before the build, no widening field; build failure publishes nothing; another version refused with unpublished edits; capability change copies outside `runtime/`; rollback; fresh services on the same data root |
| `test_remotion_studio_publish_crash.py` (new) | 2 passed | REAL subprocess `kill` during the build and after the pin, before the rebase |
| `test_remotion_studio_publish_routes.py` (new) | 6 passed | confirmation, exact body (`allowed_imports`, `actor`, `trust` refused), envelope keeps `publish_code`, discard only `true`, relay page-only (no header, `same-site`, `none`, `cross-site`, foreign Origin → 403), no brain/MCP/agent path names publish |
| `test_variants_remotion_studio_publish_js.py` (new) | 9 passed | cancel publishes nothing, conflict said + logged, discard line only for another scene |
| `test_remotion_studio_publish_docs.py` (new) | 7 passed | |
| `test_remotion_studio_roundtrip_real_browser.py` (new, opt-in) | 1 passed | |
| `test_remotion_studio.py`, `_runner.py`, `_rework.py`, `_routes.py`, `_docs.py` | 42, 22, 42, 19, 10 | |
| `test_control_center_remotion_studio.py`, `test_variants_remotion_studio_js.py`, `_docs.py`, `_browser.py` | 26, 14, 5, 7 + 1 skipped | |
| `test_remotion_isolation.py`, `_docs`, `test_remotion_source{,_docs,_store}.py`, `test_remotion_source_edit_{domain,service,routes,docs}.py` | 229, 7, 81, 6, 26, 27, 36, 2, 5 | |
| `test_remotion_mcp_{tools,server,ownership,docs}.py`, `test_remotion_compiler.py`, `test_remotion_player{,_routes,_docs}.py` | 40, 18, 6, 4, 35, 17, 9, 6 | |
| `test_presentation_studio_{service,mcp,mcp_ops,mcp_policy,mcp_docs}.py`, `test_mcp_catalog.py` | 25, 23, 27, 11, 3, 92 | |
| `test_presentation_studio_reload_{service,routes,crash}.py` | 57, 18, 6 | |
| `test_presentation_studio_explorer_{js,view_js,lifecycle_js,actions_js,browser}.py`, `test_control_center_presentation_rail_js.py`, `test_variants_controls_browser.py` | 1, 15, 19, 23, 18, 9, 8 + 2 skipped | |
| `test_schema_migrations.py`, `test_documented_routes.py`, `test_task_evidence_privacy.py`, `test_remotion_no_fallback_privacy.py` | 8, 3, 2, 25 | |

## Mutants (each reverted after its run)

| Mutant | Killed by |
| --- | --- |
| conflict check removed (`current != state.pin`) | stale-base and rollback tests |
| hard-link check removed (`st_nlink == 1`) | hard-link test |
| unpublished-edits refusal removed (start and sync) | publish bench « another version refused », service « confirmed discard » test |

## Found by the real run

- The CDP harness: Remotion Studio's guard refuses esbuild resolved through a junction (Node follows it to the target, outside the data
  root's `runtime/`): the real test copies `node_modules`. A real installation is unaffected (its `node_modules` is under `runtime/`).
- Wording: a first publication forks the scene's own source id, so « source v1 (la v1 reste disponible) » named two different v1; the
  line now says « nouvelle version de la scène (v1) ; la version d'avant reste disponible ». The « prochaine lecture » sentence was wrong
  (Variants re-reads at once) and is gone.

## Rework

Critical-tier QA returned REWORK. Branch `fix/rnsp-s12-rework` from `cb7e733b`; code and tests `b8a1664d`, docs `39c66c28`.

### Fixes and the tests that prove them

| Item | Fix | Proof |
| --- | --- | --- |
| B1 (blocking) planted `remotion.config.js` ran on a kept reopen | `RemotionStudioRunner.enforce_shape` runs before EVERY launch (`_start_locked`, kept path and `restart` included). Allowed: `src/`, `public/` (real folders), `studio-root.tsx` / `package.json` equal to what Jarvis generates (regenerated, read-only), the tool cache `node_modules/`; regular files in `src/**` and `public/**`. Everything else (top-level file or folder, link, junction, hard link) is moved into a new `studio-edits/` folder (never deleted; the link moves, not its target), said (`work_copy.set_aside`, a `diagnostics` line, Variants' line) and logged (`remotion_studio.workspace_set_aside`, warning). A move that fails: `failed` / `sync_failed`, « not launched ». `_scan_work` docstring corrected; hard links now count as `link` in the scan. | `test_remotion_studio_shape.py`: `remotion.config.js`, `remotion.config.ts`, `notes.txt`, `.env`, a top-level folder, a junction under `src/`, a hard link under `src/`, a junction replacing `public/` + a tampered generated root + a missing `package.json`, clean workspace says nothing, failed move never launches, `restart` enforces too. Real: `test_remotion_studio_shape_real.py` |
| I1 confirmation not bound to what is published | `work_copy.digest` (`listing_digest` of path to content hash / `link` / removed) and the FULL `modified_files`; `publish` requires `digest` and refuses 409 `remotion_studio_publish_listing_changed` (`count`, `files`) when the bytes it read give another digest, before any build; the page sends the digest the dialog showed, lists every file (scrolling list) and re-reads after the refusal. | `test_remotion_studio_publish.py::test_a_publish_is_bound_to_the_listing_the_confirmation_showed`, routes `test_a_base_the_page_did_not_see…` (mismatch then the right digest), body tests; node `test_the_confirmation_lists_every_file_focuses_cancel_and_sends_the_digest_it_showed` (14 files listed, digest shown is the one sent even if a poll changed it), `test_a_listing_that_changed_since_the_confirmation_is_said_and_read_again` |
| I2 parent-folder race | `_read_regular` opens the file and checks the handle: `fstat` is the same plain file as the `lstat` before and after, and its real path bound to the handle (`GetFinalPathNameByHandleW` on Windows, `/proc/self/fd` elsewhere) is inside `realpath(work)`. | `test_a_parent_folder_swapped_for_a_junction_after_the_check_is_never_read` (the QA race forced by monkeypatching `_check_inside`), `test_the_same_race_through_the_service_publishes_nothing` |
| I3 surviving mutants | new tests | M3 `test_a_file_replaced_while_it_is_read_is_refused`; M9 `test_a_result_that_does_not_stand_never_rebases_even_when_it_names_a_published_version` (`stale`, `rolled_back`, `refused_validation` carrying `published`); M1 `test_the_already_published_catch_up_is_refused_while_a_link_is_present` (and the same workspace without the junction is `already_published`) |
| I4 rotation deleted the wrong copy | set-aside folders named `AAAAMMJJTHHMMSS.ffffff-<seq>` (local time as before, microsecond never goes back in a process); cap kept at 5, the OLDEST removed, each removed name reported (`take_rotated`) and logged by the service (`remotion_studio.edits_rotated`, warning). Documented in `docs/remotion-studio.md` § 1 / § 2 bis / § 11. | `test_seven_set_asides_in_the_same_second_keep_the_five_newest_and_name_the_removed` (frozen wall clock), `test_the_service_logs_each_rotation_naming_what_was_removed` |
| P-a stray Enter publishes | publish dialog focuses « Annuler » | node test above (`focus == cancel`, Enter sends nothing) |

Docs: `docs/remotion-studio.md` (workspace shape, set-aside naming and rotation, `digest` body, `publish_listing_changed`, § 11 line 208 rewritten), `docs/presentation-studio.md` (source ownership, confirmation, outcome table, reopen).

### Mutants (each applied, run, reverted; `git diff` clean afterwards)

| Mutant | Killed by |
| --- | --- |
| B1: `enforce_shape` call removed (`aside = ()`) | 11 of 13 `test_remotion_studio_shape.py` tests fail |
| M3: after-read `lstat` dropped from the checks | `test_a_file_replaced_while_it_is_read_is_refused` |
| M9: `status not in STANDING_RESULTS` dropped | the 3 `…does_not_stand…` cases |
| M1: `not diff.links` dropped from the catch-up | `test_the_already_published_catch_up_is_refused_while_a_link_is_present` |
| I2: handle real-path check removed | `test_a_parent_folder_swapped_for_a_junction_after_the_check_is_never_read` (the service-level race test still passes under this mutant: the digest of I1 also refuses it) |
| I1: digest comparison disabled | `test_a_publish_is_bound_to_the_listing_the_confirmation_showed` |
| I4: old random-suffix name restored | `test_seven_set_asides_in_the_same_second_keep_the_five_newest…` |

### Regression gate (one file per process, foreground, on `b8a1664d` + docs)

| File | Result |
| --- | --- |
| `test_remotion_studio.py`, `_data`, `_docs`, `_guard`, `_rework`, `_routes`, `_runner` | 42, 2, 10, 19, 42, 19, 22 passed |
| `test_remotion_studio_publish.py`, `_crash`, `_docs`, `_routes` | 34 passed + 1 skipped (symlink privilege), 2, 7, 6 passed |
| `test_remotion_studio_shape.py` (new) | 13 passed |
| `test_remotion_studio_real.py`, `test_remotion_studio_shape_real.py` (without runtime) | skipped (opt-in) |
| `test_control_center_remotion_studio.py` | 26 passed |
| `test_variants_remotion_studio_js.py`, `_publish_js.py`, `_docs.py`, `_browser.py` | 15, 12, 5 passed; 7 passed + 1 skipped (evidence-only) |
| `test_remotion_isolation.py`, `_docs` | 229, 7 passed (`_real` skipped) |
| `test_remotion_source.py`, `_docs`, `_store`, `_edit_domain`, `_edit_service`, `_edit_routes`, `_edit_docs` | 81, 6, 26, 27, 36, 2, 5 passed (`_edit_real`, `_edit_realpage_browser` skipped) |
| `test_presentation_studio_explorer_browser.py` | 18 passed (4 min 48 s) |
| `test_schema_migrations.py`, `test_documented_routes.py` | 8, 3 passed |
| privacy: `test_dropped_transcript_privacy.py`, `test_remotion_no_fallback_privacy.py`, `test_task_evidence_privacy.py`, `test_tool_brain_evidence_privacy.py` | 5, 25, 2, 3 passed |

One transient failure seen once (`test_the_service_logs_each_rotation…`): `write_state` got `PermissionError` on `os.replace` of `state.json` during six back-to-back restarts (a Windows file lock, pre-existing code); three re-runs of the file passed. Not changed (out of scope).

### Real runtime (read-only gate runtime, `node_modules` copied into a throw-away data root, free loopback ports)

- `test_remotion_studio_shape_real.py`: open, close, plant the QA probe's `remotion.config.js` (writes `CONFIG_RAN.txt` outside `work/` if run), status lists it as unpublished, reopen on the same pin (kept path): `ready` in 5.8 s, **no marker**, the config is in `studio-edits/<AAAAMMJJTHHMMSS.ffffff-0001>/`, `work_copy.set_aside == ["remotion.config.js"]`, the diagnostics line names it. 1 passed (109 s).
- `test_remotion_studio_roundtrip_real_browser.py` on `39c66c28`: 1 passed (165 s). Cold open 99.2 s, HMR edit to screen 0.92 s, publish click to said 0.90 s; the real confirmation shows « 1 fichier modifié dans Remotion Studio, tous publiés tels quels : » and the list (`rework-publish-confirm-1280x720.png`), the page sent the digest it showed and Core published; `work_copy.digest` present in every view. Report: `rework-roundtrip.json` (home path and user name redacted at copy time, targets derived at runtime).
