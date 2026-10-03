# Slice 00 — READINESS

**State: `READY`** (agent 0, 2026-10-03)

## 1. Declared vs real baseline

- Handoff created without repository access (README "Source evidence"). Real base:
  `origin/main@257e911` (merge of `bfa5cd4` "trash" with `af23e78`; includes
  `63fd36a`/`065f48d` window-height-to-content commits). Local `main@af23e78` was 4
  commits behind; task based on `origin/main` (precedent D-BASE of previous handoffs).
- Branch `task/jarvis-scene-window-prefab-foundation`, worktree `C:/Projects/jarvis/bpf`.
  The Human's main checkout `C:/Projects/jarvis/jarvis` stays on `main` (their live Jarvis).
- Handoff mirrored from Drive `to-do` folder `15oD9qdL5-V0DHMFHYbG0aB0lUAmKZKWZ`
  byte-for-byte (42 files, sizes verified) via the repo's own `GoogleDriveBackend`,
  because the `jarvis-drive` MCP server disconnected mid-session. Commit `1600dbf` (S0).
- Drive placement: still in `to-do`. Moving it to `current`
  (`1BG9J5tWTuNfExK86YqH43QjMTPbOhB3D`) is left to the Human (lifecycle hard gate).

## 2. Blind audit findings (detail: `docs/06-resolved-architecture.md` R0)

Audit performed by a read-only Explore pass on the code before docs/05 was read.

1. **No prefab, template, widget registry, window family/type or checklist exists.**
   A window is `kind="window"` or any object drawn in representation `window`;
   `category` only selects a colour tone.
2. **"Rework FENETRES" has no durable record** in the repo (only feedback
   2026-09-22 and commits 63fd36a/065f48d). The handoff's "recover the agreed
   families" premise is unfulfillable → D-FAMILIES (evidence-based base catalogue,
   Human confirms via HV-WINDOW-FAMILIES-01).
3. Scene authority is mature (Level 3): pure reducer `apply_scene_command`,
   `SceneService`, `scene.sqlite3` v1 storing objects as JSON → a payload `prefab`
   block needs **no DDL and no wire-version bump** (bumping `SCENE_SCHEMA_VERSION`
   would make every existing `scene.sqlite3` unreadable).
4. The scene page never renders agent HTML (tests forbid `innerHTML`; constellation
   decision 1 "semantic scene rather than generating HTML"). Prefabs therefore run in
   ONE sandboxed iframe runtime with a postMessage protocol; the host page invariant
   is preserved (`srcdoc` confined to one audited module).
5. Agent control is the `jarvis-display` MCP (13 tools, metadata in
   `mcp_tool_meta.DISPLAY`) → extended, not duplicated.
6. `BrainContext` is the existing per-turn channel → prefab notify events reuse it.
7. Frontend = vanilla JS IIFEs spliced into `control_center.html`, node-tested; no build.
8. `fill()` replaces children on every content change → S04 must add a persistent slot.

## 3. Planning repairs applied

- `docs/06-resolved-architecture.md` added (binding; wins over docs 00-05 and SLICE bodies; R9 agent-0 amendments).
- "Slice 00 contract" appended to every SLICE.md 01-09.
- HV checks rewritten for S05/S08/S09 (IDs kept).
- DAG unchanged (linear 01→09). No SQLite migration in this task.
- 8 Issues filed under `Issues/` (presentation `set_visibility` bug, undocumented scene file watcher, selection never reaches brain, legacy nowrap labels, no FENETRES record, decision-1 forward reference, notify does not wake brain, library per data root).

## 4. Decisions (agent 0, Human delegated autonomy)

- **D-TT** — No Workspace Task Type vocabulary exists; waived (`task_type: "waived"`), as for previous handoffs.
- **D-BASE** — Base on `origin/main@257e911`.
- **D-RENDER / D-LEGACY / D-FAMILIES / D-STORE / D-SCENE / D-EVENTS / D-TOOLS / D-UI** — see doc 06 R1.
- **Worktree** — all implementation in `bpf`; QA in detached `bqa`/`bwt`; reworks on `fix/pf-sN-rework` branches.

## 5. Baseline tests at 1600dbf (= 257e911 code)

Detached worktree `bwt`, main venv, foreground chunks; full list in `BASELINE-1600dbf.md`.

| dir | files | passed | failed | errors | skipped |
|---|---|---|---|---|---|
| tests/unit | 383 | 11645 | 17 | 0 | 12 |
| tests/integration | 72 | 630 | 0 | 0 | 23 |

No import/collection error (merge 257e911 lost nothing importable).

**Inherited, in this task's domain — fixed before S01 on `fix/scene-baseline-2026-10-03`
(decision D-FIX, agent 0), merged into the task branch, `main` untouched:**
- B `test_mcp_catalog.py` (2): scene output schemas lack `source_path`.
- C `test_control_center_mcp_api.py` (1): model-visible display surface size baseline stale (32598 vs 31864).
- D `test_scene_group_drag_js.py` (5): `orbitTurns` undefined in `control_center_scene_interact.js:1414` — real group-drag bug.

**Inherited, NOT this task's — "not yours, do not fix" for every implementer (9 tests):**
- A `barge_in_decider` contracts: `test_control_center_voice_architecture_review.py` (1), `test_control_center_voice_architecture_ui_review.py` (1), `test_settings_ia_contract.py` (1), `test_voice_settings_schema.py` (1).
- E `test_app.py` (1) fake lacks `data_root`.
- F `test_brain_delegation.py` (1) prompt tail changed.
- G `test_barehands_interaction_js.py` (2) practice-frame geometry.
- H `test_interaction_mode_hud_browser.py` (1) reduced-motion halo (env-dependent).

## 6. Risks


- **Downgrade breaks the scene.** Strict decoding (`check_wire_keys`) means an older build can't read a `scene.sqlite3` containing a `prefab` key. The scene becomes unavailable (the file is never erased) until the newer build returns. This is the same exposure as `annotation`/`source_path`. Document it in `docs/scene-model.md`; no mitigation planned.
- **The base-edit witness depends on the transcript.** STT drift or paraphrase can make a real request fail the witness. Mitigation: normalized substring match, 30-minute window, a refusal message telling the brain to quote the user's exact words. If `search` can't express the lookup, S07 falls back to the declared gate and the PM decides.
- **Iframe cost.** Up to 24 live frames, each with its own document. Mitigation: cap, LRU pause, bundle cache by immutable `id@version`, S09 stress test.
- **Capture fidelity.** `scene_capture` can't paint frame content. The brain's visual check of prefab windows is limited to title and summary. Prompt guidance: use `scene_get` for prefab content.
- **State-event race.** Between the event service reading the snapshot and `SceneService.apply`, a brain write can slip in. The `basis` check narrows but doesn't close the window; last writer wins inside it. Acceptable for UI toggles; documented.
- **CSP in srcdoc.** Behaviour relies on Chrome honouring `<meta http-equiv>` CSP in sandboxed srcdoc documents. S03 browser evidence is mandatory; if it fails, the sandbox still blocks storage and parent access, and the Origin guard still blocks writes.
- **16 KiB payload bound.** Long documents (`jarvis.document` ≤12k chars) and large tables can hit the limit; the brain gets `invalid` / `payload exceeds`. Prompt guidance plus a clear refusal detail.
- **Prompt growth.** Six new tools enlarge the jarvis-display surface the model sees. Keep descriptions short and measure them per `tool-contract.md` §10.3.
- **Version collision.** A future package base version can collide with a local base-edit version. Mitigation: package wins plus a loud `core.prefab.version_conflict` diagnostic; developers bump past local edits when they notice it.
- **Authoring quality.** Brain-written behaviour JS may be poor or broken. The sandbox contains the damage (error band); `prefab_validate` and lint catch structural faults only.
