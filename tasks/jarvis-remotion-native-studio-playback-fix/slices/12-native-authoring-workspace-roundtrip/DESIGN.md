# Slice 12 design — Remotion Studio authoring workspace and publish round trip

Base `c25d1151`. Written before coding (SLICE step 2). Contract owners after this Slice: `docs/remotion-studio.md` (§ 2, § 5, § 6),
`docs/presentation-studio.md` › *Remotion Studio round trip (Level 3, Slice 12)*, `docs/remotion-source.md` § 3.

## 1. Re-audit on HEAD (SLICE step 1)

| Fact on `c25d1151` | Where | Consequence |
| --- | --- | --- |
| Remotion Studio serves `runtime/studio/work/` = the pin's `src/**` + `public/**` + generated `studio-root.tsx`, `package.json`; every file written with the read-only attribute | `remotion_studio_runner.py` `sync_work` | the user cannot save in an editor on Windows; Remotion Studio's own save buttons fail |
| `work.files.json` = hashes of the last sync; `modified_work()` = disk vs those hashes | runner | this IS a base snapshot: reused as the workspace base |
| `sync`, `open` on another pin, `open` after a stop, `restart` all call `sync_work`, which copies edited files to `studio/edits/<ts>/` then **overwrites** them; `close` copies them too | runner, service | the old path silently replaces authored files (backed up, but the workspace loses them and the rotation keeps 5 folders: a sixth backup deletes the oldest) |
| `studio/edits/` lives under `runtime/`; `uninstall` empties `runtime/` | `node_capability_runner.remove` | unpublished work would be destroyed by an uninstall |
| No code ever reads `edits/` back; nothing publishes from Remotion Studio | grep | PX-3 is entirely missing |
| The only source write door for a scene is `POST …/variants/{vid}/source-edits` (`apply_source_edit`): compose on the current pin, gate (paths, `SOURCE_GUARDS` isolation, carry-over, score, **real build**), publish a NEW immutable version, CAS the variant pin, keep `last_valid_pin`, mount report, rollback; `restore_version` republishes an older version as a new revision | `presentation_studio_reload.py` | reused as the publish path: no second writer |
| Imports allowed in a published scene: `SCENE_ALLOWED_IMPORTS` = `react`, `react/jsx-runtime`, `react/jsx-dev-runtime`, `remotion`; the Player host only exposes `HOST_EXPOSED_MODULES` | `remotion_compile.py`, `runtime-host.mjs` | Remotion Studio's webpack resolves ANY package of `runtime/node_modules`; the build gate refuses them at publish |
| Export (MP4) renders a frozen snapshot of a published version, separately | `remotion-render.md` | unchanged: preview (Player / Remotion Studio HMR), publish and export stay three verbs |

## 2. Workspace layout

The workspace is the existing served folder (`runtime/studio/work/`: `remotion`/`react` must resolve from `runtime/node_modules`), now
**writable** for `src/**` and `public/**` (generated `studio-root.tsx` and `package.json` stay read-only and unpublishable).

- **Base** = `state.pin` (the exact version the workspace was materialised from) + `work.files.json` (its hashes). Never moves except
  by a materialisation (open / sync / discard) or a successful publish (rebase).
- **Unpublished edits** = files whose hash differs from the base (added, changed, deleted, links). Computed for every status, also with
  Remotion Studio stopped, so they survive a close, an idle stop, a Core restart.
- **Backups** (`edits/`) move OUT of `runtime/` to `<capability>/studio-edits/<ts>/` (survive `uninstall`); written only when a user
  explicitly discards, and before a capability change (uninstall/repair/update/disable).

## 3. What the old sync path does now (never a silent overwrite)

| Operation | Workspace without edits | Workspace WITH unpublished edits |
| --- | --- | --- |
| `open` same pin (Studio stopped, or after a Core restart) | materialise + launch | **keep the workspace as is**, launch on it |
| `open` / `sync` another pin, `sync` same pin | materialise (HMR) | refused 409 `remotion_studio_unpublished_edits` (names the files), unless the body says `discard_unpublished: true` (user confirmation): then backup to `studio-edits/` and materialise |
| `restart` | as `open` same pin | workspace kept |
| `close`, idle stop, Core stop | process stopped | process stopped, **files kept in place** (no copy, no rotation) |
| capability change | stop | backup to `studio-edits/` first (uninstall empties `runtime/`), then stop |

## 4. Publish path (SLICE step 3)

`POST /v1/local-capabilities/remotion/studio/publish` `{presentation_id, variant_id, scene_id, base: {prefab_id, version}, confirm_publish: true}`
(relayed by the Control Center, same-origin page request only; no brain / MCP path calls it — tested).

1. Under the Studio lock (no sync/open can rewrite the workspace meanwhile): refuse unless `base` == the workspace base.
2. Read the workspace diff (one pass, `lstat` before and after each read: a link, a junction, a file swapped for a link, a path that
   is not a valid source path, a top-level file such as `studio-root.tsx` or `remotion.config.ts` → typed refusal naming the path; a
   link's target is never read). Nothing changed → `remotion_studio_publish_nothing`.
3. **Trust pre-check**: every bare import of the changed modules must be in `SCENE_ALLOWED_IMPORTS`, else
   `remotion_studio_publish_import_refused` naming the import (before any build).
4. **Conflict**: the scene's current pin must equal the workspace base. Otherwise, if the workspace content equals the scene's current
   version (a publish whose rebase was interrupted) the workspace is rebased (said, logged); else 409 `remotion_studio_publish_conflict`
   naming both versions; nothing is published.
5. `apply_source_edit(actor=user, basis = the variant revision read in 4, files: {sources, assets})`: the existing gate, build, new
   immutable version, pin CAS, mount report, rollback. A concurrent change gives `stale` → reported as the conflict.
6. On a standing result (`reloaded`, `reloaded_state_reset`, `repinned`, `pending_mount`): **rebase** = `state.pin` := the published
   version, `work.files.json` := its hashes (files on disk untouched: HMR keeps running; edits made during the publish stay unpublished).
   Any refusal leaves the workspace and its base untouched.

**Rollback**: the previous version is never touched (immutable); the result names `previous`; Variants offers « Revenir à la v<N> »,
which is the existing `restore_version` source edit (a new revision with the old content). **Interruption** (Core killed at any
point): before the publication nothing changed; after it and before the pin, one inert version exists, the variant and the workspace
are unchanged; after the pin and before the rebase, step 4 rebases on the next publish/status. Proved with a real subprocess kill.

## 5. Trust boundary (SLICE step 5)

- The **Player sandbox is unchanged** (iframe, CSP, origin): every published version still goes through `SOURCE_GUARDS` and the build.
- Remotion Studio keeps its guard (loopback only, no egress, no child process but esbuild, CSP `connect-src 'self'`) and its
  per-open acknowledgment with provenance. Writable workspace = the scene running in Remotion Studio's tab can now ask Remotion Studio's
  API to rewrite workspace files (before: read-only attribute on Windows): those changes are listed file by file in the publish
  confirmation, and they still pass the gate. Recorded as a residual risk.
- **No widening is offered** (decided by agent 0's Work Agent): third-party packages, imports beyond the list, host filesystem or
  network. The allowed list is a constant; nothing (route, brain, MCP, setting) changes it. A refused import says that widening would
  need an explicit per-project Human approval that this Jarvis does not offer (HV-RFX-12-01). Reason: an approved import must also
  be served by the Player host and the render bundler; building that safely is its own Slice.
- **Agent side**: unchanged. The agent writes sources only through `source-edits` (sandboxed Player preview, request authority). It
  does not write into the Remotion Studio workspace (code there runs unsandboxed under the user's acknowledgment of a version) and it
  cannot publish a workspace. MCP tools, schemas and descriptions unchanged.

## 6. Interface

Variants' state line (Slice 11): « n fichiers modifiés dans Remotion Studio, pas encore publiés. » + « Publier dans la variante… » →
one confirmation in Variants' layer (base version, files added/changed/removed, « nouvelle version, la v<N> reste disponible ») →
counter while the build runs (deadline) → « Publié : source v<N+1> (v<N> conservée). » + « Revenir à la v<N> ». Conflict / build failure /
refused import / unpublishable file: the sentence, the code, the diagnostics. Opening another scene with edits: the confirmation adds
« n fichiers modifiés seront mis de côté ». MCP card: same refusal sentence and a « Mettre de côté et continuer » confirmation.
