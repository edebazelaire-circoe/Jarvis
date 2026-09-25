# Slice 07 — Runtime validation (MCP inspector UI)

HEAD `3def741`, 2026-09-25. No source modified, nothing committed. Evidence: `screenshots/` (20 PNG, ~2 MB), `evidence/` (JSON dumps from each scripted run, `api/` raw API responses, `scripts/` the harness).

**Verdict: PASS with CONCERNS.** All ten checks were exercised in a real browser against a real Control Center, with a real brain whose MCP servers were really launched. There are two concerns, both non-blocking: stale availability when the view is reopened (C1), and a status LED that keeps breathing under reduced motion (C2). There is also one cosmetic note (N1).

## Environment

- The S6 harness was reused (`evidence/scripts/env.sh`, `start.sh`), with fresh data and runtime dirs in the scratchpad (`s7/`). Core ran on `127.77.0.1:17683` and the CC on `127.0.0.1:17685`. The fake Messages endpoint was on `17689`. `webbrowser.open` was a no-op.
- The brain was launched by the CC itself through the `JARVIS_CLAUDE_CLI` wrapper (`--chrome` stripped, fake endpoint, isolated CLI config, **$0**). Its MCP servers were the real ones: `/api/agent` reported `display_tools/console_tools:true` and then `barehands_tools:true` after the restart.
- The browser was **headless Chrome 153** with its own profile in the scratchpad, driven over CDP on port 9333 (`evidence/scripts/cdp.py`, aiohttp). The claude-in-chrome extension was not used. No dialog was triggered.
- Default theme is `circuit-board`. `cosmos` was switched to with `JarvisThemeAPI.activate`.
- Cleanup: Chrome, the CC (and the brain with its MCP children), Core and the fake API were stopped with `taskkill /T`. The live Jarvis on 17653/17654 was never touched and was still listening afterwards. Some `jarvis control-center` / `display-mcp` processes from this worktree's venv were created on 2026-09-24 16:39, before this session. They are not mine and were left running.

## Results

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Dock: MCP between SET and AGT, same look; other panels and pills unchanged | **PASS** | `01-dock-err-panel.png`, `01-dock-pills-circuit.png`, `01-dock-pills-cosmos.png` |
| 2 | Compact view: servers + states; Scène tab 13 rows, badges | **PASS** | `02-compact-scene-tab.png`, `02-cosmos-inspector.png`, `evidence/t2-main-flow.json` |
| 3 | `scene_update_many` expanded | **PASS** (N1) | `03-sum-detail-top.png`, `03-sum-detail-select.png`, `03-sum-detail-output.png` |
| 4 | Réglages / Bare Hands / Général / Externe tabs | **PASS** | `04-tab-settings.png`, `04-tab-barehands.png`, `04-tab-general.png`, `04-tab-external.png` |
| 5 | Search `radius` | **PASS** | `05-search-radius.png` |
| 6 | Pending restart | **PASS** / **CONCERN C1** | `06-pending-restart-banner.png`, `06-after-restart.png`, `06-brain-stopped.png`, `06-reopen-after-restart-stale.png`, `evidence/t5-*.json`, `t6-*.json` |
| 7 | Narrow 360 px | **PASS** | `07-narrow-360-list.png`, `07-narrow-360-detail.png`, `07-narrow-360-tabs-scrolled.png`, `evidence/t7-cosmos-narrow.json` |
| 8 | Keyboard flow | **PASS** | `evidence/t3-keyboard.json` |
| 9 | Network / console | **PASS** | `evidence/t2-main-flow.json` (`req_all`, `allreq_nonGET`, `errors`) |
| 10 | Reduced motion | **CONCERN C2** | `evidence/t9-reduced-motion.json` |

### 1. Dock and neighbours
- **Dock order and style.** The DOM order is ERR, TRC, LAB, CNV, SET, **MCP**, AGT. Every button measures 52×52 at x=1370 on a 62 px pitch, and all seven share the same computed border, background, colour, radius and font. In Cosmos, MCP gets the plug icon at the specified order (AGT, CNV, LAB, **MCP**, TRC, SET, ERR, left to right).
- **Panels.** ERR, TRC and AGT opened the side panel with the right title. LAB opened `#testlab`, CNV opened `#timeline`, SET opened `#overlay` and MCP opened `#mcpInspector`. Esc closed each one. No console errors (`t4.py`, output inline in the run log).
- **Pills.**
  - None appear naturally in this environment (there were no background tasks). They were forced visually by wrapping `renderBackgroundPills` with synthetic counts (failed 1, attention 2, done 3, said 1). This is only a visual probe.
  - Circuit at 1440: the pills sit in a column starting at y=674, 12 px under AGT (bottom 662), with no overlap.
  - Cosmos at 1440: the pills sit in a row ending at x=1138, 10 px left of AGT (x=1148), with no overlap.
  - Cosmos and circuit at 360: no overlap either.
- **Not done:** a pixel diff against `b499b31`. There was no RAM for a second instance. The only CSS changes to neighbours are the pill offsets for a 7-button dock (`git show 16e155e`), and those offsets were verified above.

### 2. Compact view
- **Server chips.**
  - display: *Annoncé* · 13 outils · 31 864 o
  - console: *Annoncé* · 3 · 2 918 o
  - barehands: *Désactivé* · 5 · 4 107 o
  - drive: *Connu* · 7 · 2 126 o
- **Tabs and status.** The tabs read Général / Étoiles·Scène 13 / Réglages 3 / Bare Hands 5 / Externe 7. The status reads "Catalogue lu · 28 outils · 4 serveurs".
- **Scène rows.** There are 13 rows, one per tool, in contract order.
  - Badges match the list API (§4.1): Lecture/Écriture/Destructif, *Lot atomique* on `scene_update_many`, `scene_move`, `scene_archive` and `scene_pin`, and *Idempotent* where `idempotent:true`. `scene_create_object` and `scene_move` correctly have no Idempotent badge.
  - No server badge is shown, because display is `advertised`.
- The default tab on open is **Général**.

### 3. `scene_update_many` detail
- **Header.** The description has its first paragraph dropped because it equals the summary. The facts read: qualified name `mcp__jarvis-display__scene_update_many`, Écriture, Lot atomique, Idempotent oui, 4 790 o.
- **Parameter table.** 9 parameters, none required. Every default is `null`.
  - `select` is `object | null`, "15 clés, fermé".
  - `object_ids` is `array<string> | null`, "1 à 512 éléments".
  - `visibility` and `representation` show their enum values.
  - `annotation` shows "≤ 60 caractères".
- **Structure of select.** It lists all 15 keys with their enums. `constellation` is ConstellationArg, closed, with `object_id` required and `depth` "(1–6)". `near` is NearArg, with `object_id` and `radius` required and "(0–100000)". `exclude` holds 1 to 32 items.
- **Rules.** 5 parameter rules are listed.
- **Output.**
  - The Résultat section carries the format sentence, the notes, and the schema description (SceneBatchSkipped/SceneBatchReport text).
  - Its tree has `skipped` as a list of SceneBatchSkipped{id, reason}.
  - It also has `delta` as SceneBatchDelta{requested: SceneOffset{dx, dy}, effective: SceneOffset{dx, dy}, clamped}, `hidden_count`, `cascade_ids` and more.
- **Raw schema.** "Schéma brut (JSON)" is a closed `<details>` (`open=false`) and is the last child of the detail.
- **N1 (cosmetic):** the root of the output tree reads "objet · clés fermées" without its title `SceneBatchResult`. The schema has `title: "SceneBatchResult"`, and nested nodes do show their titles.

### 4. Other tabs
- **Réglages.** `settings_set` shows 2 required parameters, `option_id` and `value` (`boolean | number | string`). Its output tree covers before, after, changed and `restart_required` ("string ou null"). Idempotent.
- **Bare Hands.**
  - The `barehands_tutorial` row carries Écriture, **Déprécié** and Désactivé.
  - Its detail opens on an amber notice: "Outil déprécié. Remplacé par `barehands_calibrate`", with the removal condition, the "since" slice and the legacy doc path.
  - The other tools have no Déprécié badge.
- **Général.**
  - A servers table (state, declaration, tools, context, tab button) and "Aucun [outil transversal] aujourd'hui".
  - A badge legend with 6 badges, and the line "Inspection seulement… Aucun outil de catalogue n'est annoncé au modèle".
  - "Tout déplier" is disabled on this tab.
- **Externe.** 7 drive rows, each with a *Connu* badge, under the server line "défini dans le code ; sa déclaration n'est pas prouvable par Jarvis".

### 5. Search `radius`
- The tab counts become Scène **5/13**, Réglages 0/3, Bare Hands 0/5, Externe 0/7.
- The 5 hits are `scene_query` ("correspond au paramètre near.radius"), `scene_update_many`, `scene_move`, `scene_archive` and `scene_pin` (each "select.near.radius").
- The first search indexed every descriptor (see item 9).

### 6. Pending restart
- **Bare Hands turned on while the brain runs without it** (`POST /api/barehands {"enabled":true}` → 200; the page's settings API):
  - The API reports barehands `configured`, `pending_restart:true`.
  - Status: "Redémarrage en attente".
  - Notice banner: "À prendre en compte au prochain (re)démarrage du brain : jarvis-barehands — le brain en cours n'a pas la configuration du prochain lancement."
  - The barehands chip is amber, "Configuré · redémarrage".
  - The rows carry a *Configuré* badge.
- **After `POST /api/agent/restart {"new_conversation":true}`** (brain pid 30380 → 34484, `barehands_tools:true`) and **Actualiser**:
  - No banner; status "Catalogue lu".
  - barehands *Annoncé*, and the server badges disappear from the rows.
- **Brain stopped** (`POST /api/agent/kill`, then Actualiser):
  - No notice. display, console and barehands show *Configuré* (tone "on", not amber).
  - The API shows `pending_restart:false` everywhere. Turning Bare Hands off with the brain stopped also gives no notice.
- **C1 is found here**, see below.

### 7. Narrow 360×780 (mobile emulation)
- **Page width.** `document.documentElement.scrollWidth = body.scrollWidth = 360 = innerWidth`, both in list and detail views, and also on the Cosmos and circuit home pages.
- **Scrollers.**
  - Tabs: scrollWidth 541 / client 360, `overflow-x:auto`. End moved `scrollLeft` to 181 and the last tab is fully visible (right edge 356).
  - Server strip: 1085 / 360, `overflow-x:auto`.
  - Panel: 360 / 360.
- **Parameter table.** The thead is visually hidden (`clip rect(0,0,0,0)`), each `tr` is a block card, and each `td` is a grid with a `::before` label ("Type", …).
- **Elements past the viewport edge.** Only three, and none creates page scroll:
  - Two `<code>` inside the summary, clipped by the ellipsis of `.mcpi-sum`.
  - The visually hidden `thead th`.
- The header wraps onto three lines (title, search and Tout déplier on the first; Actualiser; status).

### 8. Keyboard flow (`document.activeElement` at each step)
1. focus → `BUTTON#openMcpInspector`
2. Enter → `INPUT#mcpiSearch`
3. Tab → `#mcpiRefresh`. "Tout déplier" is skipped because it is disabled on Général.
4. Tab → `#mcpiClose`
5. Tab ×4 → the 4 `.mcpi-srv` server chips
6. Tab → `#mcpi-tab-general` (role=tab, selected)
7. ArrowRight → `#mcpi-tab-scene`; ArrowRight → `#mcpi-tab-settings`; ArrowLeft → `#mcpi-tab-scene`; End → `#mcpi-tab-external`; Home → `#mcpi-tab-general`; ArrowRight → `#mcpi-tab-scene`. Each move is selected and focused (roving tabindex).
8. Tab → `#mcpi-0-t` (`scene_inspect` toggle, `aria-expanded=false`)
9. ArrowDown → `#mcpi-1-t`; ArrowDown → `#mcpi-2-t`; ArrowUp → `#mcpi-1-t`
10. Enter → `#mcpi-1-t` now `aria-expanded=true`, and the detail facts are rendered
11. `/` → `#mcpiSearch`; Shift+Tab → wraps to the last toggle `#mcpi-12-t` (focus trap)
12. Escape → `BUTTON#openMcpInspector` (`aria-expanded=false`), dialog hidden

The same Esc-returns-to-MCP result was seen in the mouse flow (`t2`: `after_esc1`).

### 9. Network and console
- **Requests.** The whole main flow (open, 5 tabs, 3 expands, search, Esc) made **29** `/api/mcp` requests, all `GET`:
  - 1 × `/api/mcp/tools`
  - 28 two-segment `/api/mcp/tools/{server}/{name}`, **each exactly once**. The 3 descriptors already opened were not refetched when search indexed the rest.
- Reopening after Esc sent 0 new `/api/mcp` requests (`t6`).
- **No POST, PUT or DELETE** from the page for the whole session, across all URLs (`allreq_nonGET: []`).
- **Console.** No exceptions and no errors from the inspector. Seen during the runs:
  - `favicon.ico` 404, which predates S7.
  - With Bare Hands enabled, `[barehands] camera_denied` warnings and a "Caméra refusée" toast. These are expected in headless mode and not S7.

### 10. Reduced motion (`Emulation.setEmulatedMedia prefers-reduced-motion: reduce`, `matchMedia` true)
- **Scan method.** I checked every element of `#mcpInspector`, plus an injected `.mcpi-skel span` probe, for a non-zero `transition-duration` or an animation.
- **With no preference:** `.mcpi-chev` (transform 0.16s), the `.mcpi-skel span` shimmer and the `.tl-led` breathe.
- **With reduce:** the chevron has a 0s transition and the shimmer is gone. **The `.tl-led` of `#mcpiStatus` still runs `breathe`**, see C2.

## Concerns

- **C1: stale availability when the inspector is reopened (MINOR–MEDIUM, UX correctness).**
  - `openView()` reloads only if `!S.list || S.listError`. After the brain restarts, the notice "À prendre en compte au prochain (re)démarrage…" and the amber chip keep showing, even though the API already says `advertised`/`pending:false`. They stay until the user clicks **Actualiser** or reloads the page.
  - Repro:
    1. Brain running without Bare Hands, then `POST /api/barehands {"enabled":true}`.
    2. Open MCP (the notice shows), then Esc.
    3. `POST /api/agent/restart`, which is what the user would do from Réglages.
    4. Open MCP again. The notice and "Redémarrage en attente" are still there, and **0 GETs** were sent (`t6-reopen-stale.json`, `06-reopen-after-restart-stale.png`).
  - The doc (§10.7) only states that descriptors are cached "until Actualiser". The list, which carries availability, is cached the same way. Since restarting requires closing the modal, the stale view is the normal path.
  - Option: refetch the (cheap) list on every open, and keep only the descriptors cached.
- **C2: status LED still animates under reduced motion (MINOR, inherited).**
  - The reduced-motion rule `.tl-status .tl-led{animation:none}` (html l.593) loses on specificity to `.tl-status[data-tone=live] .tl-led{animation:breathe…}` (l.426) and to `[data-tone=busy]`.
  - The inspector reuses this shell, and its "Catalogue lu" status is `live`, so the LED keeps breathing.
  - This defect predates S7 (timeline shell) but is now visible in the S7 view.
  - Repro: emulate reduce, open MCP, `getComputedStyle(document.querySelector('#mcpiStatus .tl-led')).animationName === 'breathe'`.
  - The S7-specific rules (chevron, skeleton) are correct.
- **N1 (cosmetic):** the output tree root does not show its schema title (`SceneBatchResult`), while nested nodes show theirs. The check asked for "SceneBatchResult".

## Not verified

- Pixel comparison with `b499b31`. There was no RAM for a second CC; the neighbours were judged from geometry, computed style, the CSS diff and screenshots.
- Real background-task pills. They were injected synthetically, for a visual check only.
- The Cosmos inspector at 360 px. Only the Cosmos home page at 360 was captured; the circuit inspector at 360 was fully measured.
- The loading skeleton, the 15 s timeout and the coded-error and Réessayer states at runtime. The API always answered quickly; the skeleton was only probed for its reduced-motion CSS.
- Screen-reader output (the `aria-live` announcements were not listened to), and real OS-level reduced motion (emulated only).
