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
