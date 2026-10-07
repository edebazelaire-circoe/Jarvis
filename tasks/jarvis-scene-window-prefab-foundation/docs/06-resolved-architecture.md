# 06 — Resolved Architecture (Slice 00, binding)

Status: binding. Written by the Project Manager after the blind repository audit of
branch `task/jarvis-scene-window-prefab-foundation`. **Where this document and docs 00-05
or any SLICE.md body disagree, this document wins.** Every later Slice reads its own
"Slice 00 contract" section first. A Work Agent that finds a fact here contradicted
by the code stops and reports to the PM. It does not silently follow either side.

## R0 — Audit summary (evidence, file:line)

### What exists

- **Scene domain** `jarvis/domain/scene.py`:
  - Closed kinds `agent/job/artifact/attention/window/group` (143-151).
  - `ScenePayload` (532-591) = `title` ≤160, `summary` ≤2000 (markdown subset), `items` ≤32 `{label, ref, url}`, `annotation` ≤60, `source_path` ≤512. The whole payload is ≤16 KiB (`MAX_PAYLOAD_BYTES`, 91).
  - At most 512 active objects.
  - Authority matrix `ALLOWED_SCENE_OPS` (302-308): brain = user = every op.
  - Pure reducer `apply_scene_command` (1358). Payload writes replace the whole payload (`_plan_object_write`, 1452).
  - `SCENE_SCHEMA_VERSION = 1` (72).
- **Ports** `jarvis/ports/scene.py`. **Service** `jarvis/core/scene_service.py`: `SceneService.apply` (282) runs the reducer under an asyncio lock, persists first, then publishes.
- **Persistence** `jarvis/adapters/sqlite_scene.py`: objects are stored as a JSON `data` column. `wire_schema_version` is stored in `scene_meta`, and any value other than `SCENE_SCHEMA_VERSION` is refused (581-589).
- **Wiring** `jarvis/core/v2_app.py:252-274` (scene, projector, `SceneFileWatcher`).
- **Core routes** `jarvis/protocol/server.py:206-210`. Route modules exist as classes with `routes()` (`capture_routes.py:187`, `workspace_routes.py:84`), spliced into the table at 218-219. A domain refusal is HTTP 200 with `outcome` and `reason` (`scene_wire.command_body`, `scene_wire.py:200`).
- **Control Center** (aiohttp 127.0.0.1:17654) relays `/api/scene*` to Core and forces actor `user` (`scene_view.user_command`, `scene_view.py:456`). Routes are at `control_center.py:1166-1170`. Relay modules exist: `workspace_relay.py`, `capture_relay.py`.
- **Origin guard** `control_center.py:1732`: non-GET with a non-loopback `Origin` is refused, `Origin: null` included. `READ_GUARDED_ROUTES` adds Host, Origin and Sec-Fetch-Site checks on every method.
- **Renderer**: vanilla JS IIFEs, no build, no package.json. Spliced into `control_center.html` by `ControlCenter.index` (`control_center.py:1888-2013`) through `/*__X_JS__*/` markers (html 1430-1834).
  - Pure modules may not touch `document.`, `window.`, `fetch(`, and similar (`test_scene_renderer_logic.py:1368`).
  - The scene page may not contain `innerHTML`, `insertAdjacentHTML` or `outerHTML` (`test_scene_artifacts.py:717`).
  - `fill()` (`control_center_scene_page.js:1576`) calls `el.replaceChildren()` on every content-key change (`applyNodes`, ~1863-1884).
  - Window height is reduced to the measured content (`naturalWindowHeight`/`fitBrainWindows`, ~1983-2010; commits 63fd36a, 065f48d).
  - Capture draws its own model on a canvas (`control_center_scene_capture.js`).
- **Brain display MCP** `jarvis/runtime/display_mcp.py`:
  - `build_server` (2229) with strict schemas (`StrictDisplayMCP`); logic lives in `SceneDisplayTools` (726).
  - It acts as actor `brain` on Core `/v1/scene/*`, and is declared only for the `conversation` profile (`claude_local.py:923`).
  - `update_object` reads, merges, then writes the payload (863-918).
  - Tool metadata has a single source: `jarvis/runtime/mcp_tool_meta.py` (`DISPLAY`, ~102-155). The tool contract is `docs/mcp/tool-contract.md` (§10.2 "Adding or changing a tool").
  - Prompts: `BRAIN_DISPLAY_PROMPT` (`claude_local.py:99`, fingerprint-tested) plus appended blocks `BRAIN_SCENE_READ_PROMPT` and `BRAIN_ARTIFACT_PROMPT`. These are registered in `jarvis/runtime/prompt_catalog.py:180-188` and composed by `PromptStep` (~287).
- **Brain turn context**: `BrainContext` aggregate (`jarvis/domain/brain_context.py:823`, docstring invites new blocks). It is built in `BrainService` (`core/brain_service.py:1745-1751`) and serialized by `_turn_context` (`adapters/control_center_brain.py:100`), where optional blocks are absent when empty. **This is the existing channel the prefab notify events use.**
- **Storage patterns**:
  - Data root per repo copy (`docs/local-data.md`, `jarvis/data_root.py`).
  - Path guards in `jarvis/adapters/safe_folders.py` (`ensure_folder_tree`, `check_existing_tree`, `check_file_path`, reparse-point refusal).
  - Atomic temp-then-replace in `jarvis/adapters/file_scene_captures.py`.
  - Versioned immutable catalog with a fingerprint lock: `jarvis/testlab/official/<domain>/<name>.v<N>.json` plus `catalog.lock.json` (`docs/testlab.md` §580+).
  - Canonical JSON sha256: `jarvis.domain.prompt_registry.fingerprint` (52).
- **Architecture gates**:
  - `tests/unit/test_v2_architecture.py`: domain and ports import no infrastructure; core never imports `jarvis.runtime`; core→adapters only through the exhaustive `CORE_ADAPTER_IMPORT_EXCEPTIONS` for `v2_app.py` (35); stale entries fail.
  - `tests/unit/test_documented_routes.py`: every `/api/...` quoted in `docs/ARCHITECTURE.md` or `docs/OPERATIONS.md` must be registered.

### What does not exist

- No prefab, template, widget registry, window family/type or checklist anywhere (grep "prefab" in `jarvis/` and `docs/`: zero hits).
- A "window" is kind `window` or any object in representation `window`. `category` only selects a colour tone (`CATEGORY_TONES`, `control_center_scene_layout.js:354`).
- `view_table` is a proposal only (`docs/mcp/plan-outils-interface.md:591-622`).
- **"Rework FENETRES" has no durable record.** The only evidence:
  - `retours-utilisateur/1790090231/2026-09-22-fenetre-selectionnee-et-agrandissement-sans-effet.md`: selection never reaches the brain; item labels are nowrap and unreadable; the real need is to read an artifact's content in full.
  - Commits 63fd36a and 065f48d.
  - Constellation decision log (`tasks/jarvis-constellation-scene-runtime/docs/01-decision-log.md`, decision 1: the brain manipulates a semantic scene "rather than generating HTML").
  - The reconstructed `grill-session.md` of this handoff.
- No Workspace Task Type vocabulary is exposed in the repo.

### Documentation levels (evidence-based; replaces doc 05 estimates; last column = final, Slice 09)

| Concept | Level now | Target | Owner Slice | Final (S09) |
| --- | ---: | ---: | --- | ---: |
| Scene ownership / Brain→scene boundary | 3 (`docs/scene-model.md`, reducer, tests) | 3 (unchanged; prefab block added) | S01 doc, S04 code | 3 |
| Window families | 0 (no taxonomy) | 3 for the 4 base prefabs | S05, S06 | 3 (4 base prefabs locked) |
| Prefab definition / instance / inputs / events / protection / provenance | 0 | 3 | S01 doc, S02-S04 code | 3 |
| Agent prefab operations | 0 | 3 | S07 | 3 |
| Library UI | 0 | 3 | S08 | 3 |
| Presentation seam | 1 (stager uses artifacts) | 2 | S09 | 2 (`docs/prefabs.md` › *Consumers*) |

## R1 — Binding decisions

### D-RENDER: one sandboxed runtime for every prefab

- Every prefab instance (base or custom) renders in **one** runtime: a sandboxed `<iframe>` owned by the scene window node.
  - `sandbox="allow-scripts"`, exactly. Never `allow-same-origin`, `allow-popups`, `allow-forms`, `allow-top-navigation` or `allow-modals`.
  - The frame has an opaque origin: no cookies or storage of the Control Center, no access to `parent.document`.
- The host builds `srcdoc` from manifest, template, style and behavior, plus the injected runtime shim and shell stylesheet. Order:
  1. `<meta charset="utf-8">`
  2. `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'">` (first element in `<head>`)
  3. `<style>` shell.css
  4. `<style>` prefab style
  5. `<body>` template
  6. `<script>` shim
  7. `<script>` behavior, wrapped by the shim loader
- `eval` stays blocked (no `'unsafe-eval'`). Network is blocked by `default-src 'none'`.
- Defence in depth on the Control Center:
  - `Origin: null` is already refused on writes (`control_center.py:1748-1768`).
  - `/api/prefabs` is added to `READ_GUARDED_ROUTES`.
- **Host page invariant.** The scene page keeps zero `innerHTML`, `insertAdjacentHTML` and `outerHTML`. Setting `iframe.srcdoc` as a property is the only HTML path, and it lives in **one audited module**, `jarvis/runtime/control_center_prefab_host.js`. A static test asserts that `srcdoc` appears in no other runtime file and that the sandbox value is the literal `allow-scripts`.
- **Messages** use `postMessage` only, with a versioned protocol `jv: 1` (see R4).
  - The host accepts a message only if `event.source === iframe.contentWindow` and `event.origin === "null"`.
  - Host→frame messages use `targetOrigin "*"`, because an opaque origin cannot be targeted. They carry only the instance's own props, data and theme, never secrets.
- **Prefab JS limits**: no network, no parent DOM, no tools, no storage. Its only outputs are `event`, `resize`, `open_url` (host-validated http/https, opened with `noopener,noreferrer`, same rule as `itemRow`) and `error`.
- **Host-owned chrome.** Head (dot, category, pin, state badge, origin button), grip, drag, resize, selection, pin, Bare Hands zones and keyboard entry stay drawn by the scene page exactly as today. The iframe fills only the body area of the window.
  - Interaction semantics are therefore unchanged for prefab windows.
  - `payload.title` stays the window title: drawn by the head, read by `scene_inspect` and drawn by capture.
- **Lifecycle** (`createPrefabHost`):
  - One iframe per object id, kept in a host `Map`.
  - It is **never detached during updates**. `fill()` gets a prefab branch that keeps a persistent `.sc-prefab-slot` child. A props, data or theme change becomes `host.update` (diffed by JSON string), never a re-fill.
  - Remount happens only on a `(prefab id, version)` change, on a node shape change away from `window` (compact or capsule draw), or on object removal.
  - Live frames are capped at 24 (LRU by last visible draw). Beyond the cap, the slot shows a static "paused" placeholder with the title.
- **Height**: the frame reports `resize{height}` (clamped 24..4000 px). `naturalWindowHeight` treats `.sc-prefab-slot` as a growing child whose natural height is the last reported height, so `fitBrainWindows` keeps working.
- **Capture**: `drawCommands` draws a prefab window as head + `payload.title` + a muted line `prefab <id>@<version>` + `payload.summary` if non-empty. A sandboxed frame cannot be rasterized by the host. This is a stated limitation, not a bug.
- **Markdown**: one parser only. For inputs declared `{"type": "text", "format": "markdown"}`, the host converts the value with `JarvisSceneLayout.markdownBlocks` before posting. The shim offers `jarvis.renderBlocks(el, blocks)`, which builds DOM with `textContent` and mirrors the page's `appendBlocks`.

### D-LEGACY: the legacy window path stays first-class

- An object whose payload has no `prefab` block is legacy and keeps the current DOM renderer **unchanged**.
- No forced migration of existing objects. The projector, artifacts (`scene_add_artifact`), the presentation stager and every existing scene keep using it.
- S05 ships `jarvis.window` as a prefab reproducing the generic window as a starting point.
- **The legacy path is not deleted in this task.** S09 re-proves its consumers (it will find `scene_projector.py`, `display_mcp.add_artifact`, `presentation_staging.py`) and records the retention.

### D-FAMILIES: the base catalogue, from evidence only

There is no durable Rework FENETRES taxonomy. The base catalogue is:

1. `jarvis.window` (S05): generic window. Inputs: `body` markdown, `items` list with wrapping labels, `accent`. Parity with the current window look.
2. `jarvis.document` (S05): full-read document. Long markdown text that wraps and scrolls, with keyboard paging. Source: feedback 2026-09-22, "lire le contenu en entier".
3. `jarvis.table` (S05): `columns` (1..8) plus `rows` (≤64 of ≤8 string cells). Source: the documented `view_table` proposal, which this supersedes.
4. `jarvis.checklist` (S06): the structured, interactive proof.

- Shared shell = `jarvis/prefabs/runtime/shell.css` plus `shim.js`, injected by the runtime into every srcdoc (composition, not copy-paste). Base prefabs use the shell classes (`.jv-*`) and CSS variables (`--jv-accent`, `--jv-text`, `--jv-muted`, `--jv-surface`, `--jv-font`, `--jv-scale`).
- HV-WINDOW-FAMILIES-01 asks the Human to confirm the base catalogue or name missing Rework FENETRES families. Any addition becomes a follow-up task, not scope creep.

### D-STORE: file library, no SQLite, no migration

- **Package (base)**: `jarvis/prefabs/base/<prefab_id>/<version>/` containing:
  - `manifest.json`, `template.html`, `style.css`, `behavior.js`
  - `publication.json` (shipped)
  - plus `jarvis/prefabs/base/catalog.lock.json` (`jarvis.prefab.catalog_lock` v1: one entry per base version, `{prefab_id, version, fingerprint}`; testlab lock pattern).
  - Package files are **never written at runtime**. A test asserts the lock matches the files, so nothing was edited in place and no version is unlocked or orphaned.
- **Shared library (this install)**: `<data_root>/prefabs/<prefab_id>/<version>/`, same layout. "Shared/global" means one library per Jarvis install (per data root), not per Board, Session or user. Worktrees and `jarvis-dst` have their own data root and therefore their own library (stated limitation).
- **Immutability**: a published version is never rewritten.
  - Publishing writes into `<data_root>/prefabs/.staging-<16 hex>/`. Each file is written by temp-then-replace (`file_replace.replace_with_retry`).
  - The folder is then renamed with `os.rename` to `<prefab_id>/<version>`, which fails if the target exists, so the version is never overwritten.
  - Folders go through `safe_folders.ensure_folder_tree` (`<prefab_id>` component) and `check_file_path`. Links, junctions and reparse points are refused. Stale `.staging-*` folders are swept at start (same rule as `SceneService._sweep`).
- **Catalogue** = union of both roots, discovered by scanning `*/<int>/manifest.json`. There is no central table.
  - Version fingerprints are recomputed on load. A mismatch with `publication.json` marks the version `tampered`, refused for new instances, with diagnostic `core.prefab.tampered`.
  - Same `(id, version)` in both roots: the package wins and diagnostic `core.prefab.version_conflict` is emitted.
  - Bounds: ≤512 ids, ≤64 versions per id.
  - Manifests are cached by `(root, id, version, fingerprint)`. Rescan happens on list and after each publish (cheap mtime check).
- **Base edit** = publishing a new version of a `jarvis.*` id into the **data-root** library, only through the explicit-intent gate (D-TOOLS `prefab_edit_base`), recorded in `publication.json.provenance.base_edit`.

### D-SCENE: an optional instance block in the payload

- `ScenePayload` gains optional `prefab: ScenePrefabRef | None` (`jarvis/domain/scene.py`):
  - `id`: prefab id grammar, see R2.
  - `version`: int 1..9999, always exact (never "latest").
  - `props`: JSON object.
  - `data`: JSON object.
- Domain checks (pure):
  - JSON-only values (str, int, finite float, bool, null, list, dict with str keys).
  - Depth ≤8; keys ≤64 chars; strings without C0 controls except `\n` and `\t`.
  - The whole payload, block included, stays ≤ `MAX_PAYLOAD_BYTES` (16 KiB).
- Wire: the `prefab` key is emitted **only when present**, the same rule as `annotation` and `source_path` (scene.py:571-579). Legacy objects serialize byte-identically.
- `SceneObject.__post_init__` refuses a prefab block on any kind but `window`. Representation stays free: a point or capsule draw shows the legacy compact shape with `payload.title`.
- **Validation authority = Core.**
  - `SceneService.__init__` gains `prefab_validator: PrefabInstanceValidator | None` (port in `jarvis/ports/prefabs.py`).
  - In `_apply_serialized`, after `apply_scene_command` returns `APPLIED`, every `PUT_OBJECT` op whose `object.payload.prefab` differs from the previous object's block is validated by `await validator.validate_instance(ref)`. This checks that the id and version exist and are not tampered, and that props and data validate against the manifest input schemas.
  - The first failure returns `SceneUpdate(INVALID, current, reason=SceneRefusal.PREFAB_INVALID, detail="<≤300 chars>")`: no commit, no revision.
  - No validator wired means any new or changed prefab block is refused (`PREFAB_INVALID`, detail `prefab catalog unavailable`): fail closed.
  - An unchanged block (move, pin, annotation through `patch_selection`, file-watcher summary) is not revalidated. Moving a window whose prefab folder disappeared still works.
- `SceneUpdate` gains `detail: str = ""` (only with a refusal, ≤300 chars). `scene_wire.command_body` emits `detail` only when non-empty. `scene_view.decode_command_response` accepts it.
- **`SCENE_SCHEMA_VERSION` stays 1.** It gates root wire forms (`_check_schema_version`, scene.py:376) and the stored `scene_meta.wire_schema_version`, where any other value is refused with no migration path (sqlite_scene.py:581-589). Bumping it would make every existing `scene.sqlite3` unreadable and force a migration. The precedent for optional payload keys (`annotation`, `source_path`) is no bump. No DDL change: objects are a JSON `data` column.
- **Ownership and provenance of an instance** use the existing fields only: `origin` (creating actor), `constraints.placed_by`, plus the prefab's `publication.json`. The scene has no Board or task owner and this task adds none (Session/Board/Context out of scope).
- "Diverged from saved definition": instances cannot change code. Divergence = `version < latest_version`, reported by `scene_get` and the library.
- **There is no separate `state` field.** `prefab.data` is the canonical persisted instance state; ephemeral UI state lives in the frame only.
- Show, hide, reorder and destroy are the existing ops (`set_visibility`, `layer`/`order`, `archive`). "Focus" has no op and stays out of scope.

### D-EVENTS: user events reach Core through the Control Center

Path: frame → host (`control_center_prefab_host.js`) → `POST /api/prefabs/events` (CC, actor forced `user`) → `POST /v1/prefabs/events` (Core) → `PrefabEventService` (`jarvis/core/prefab_events.py`).

Two classes are declared per event in the manifest:

- **`state`** declares `writes: [<top-level data keys>]`.
  - The frame emits `payload = {<written keys>: <new value>}`. The host attaches `basis = {k: lastSentData[k]}`.
  - Core checks, in order:
    1. the object is active, kind `window`, and its `prefab.id`/`version` match the request;
    2. the event is declared and of class `state`;
    3. the payload keys are a subset of `writes`;
    4. `basis` deep-equals the current `data` on those keys; otherwise outcome `stale`, nothing written, and the host re-sends `update` from the scene stream;
    5. `merged = {**data, **payload}` validates against the data schema.
  - Then Core applies `PATCH_OBJECT` as actor `user` through `SceneCommandSink.apply`. The reducer stays the authority, and the D-SCENE validator runs again.
  - No rule language and no reducer per prefab.
- **`notify`** records the event and writes nothing.
- **Event log**: both classes are recorded in a bounded in-memory ring.
  - 256 entries: `seq`, `at`, `object_id`, `prefab_id@version`, `event`, `class`, `payload` ≤8 KiB, `outcome`.
  - Each entry also emits diagnostic `core.prefab.event`.
  - The brain reads it with `prefab_events`.
- **Turn surfacing**: undelivered `notify` events (≤8, oldest first, payload preview ≤1 KiB each) go into a new optional `BrainContext.prefab_events` block on the next brain turn. They are serialized by `_turn_context` as `prefab_events`, absent when empty (byte-identical context otherwise), and marked delivered once included.
  - No wake: a notify does not open a brain turn (follow-up Issue).
- **Limits**:
  - Host: ≤10 events/s per frame, excess dropped and counted.
  - Core: token bucket of 30 events/s; beyond, 429 `rate_limited`.
  - **No event executes a tool.**

### D-TOOLS: agent operations on the existing display server

- The same `jarvis-display` server and the same metadata source are extended.
- Logic lives in a new module `jarvis/runtime/display_prefabs.py` (class `PrefabDisplayTools`, transport to Core `/v1/prefabs*`). Tools are registered in `display_mcp.build_server`.
- Instantiation and update go through `scene_create_object`/`scene_update_object` with a new `prefab` argument. There is no parallel instantiate tool. See R6.

### D-UI: library panel in the existing dock

- New dock button `PFB` next to `MCP` and `WSP` (`control_center.html:1275-1284`). It opens a full-screen dialog `.pfb`, on the same layer and with the same one-open-at-a-time rule as `.mcpi`/`.wsp` (html 44-45).
- Script `jarvis/runtime/control_center_prefabs.js`, spliced by marker `/*__CONTROL_CENTER_PREFABS_JS__*/`.
- It renders catalogue truth from `/api/prefabs` only, and builds its DOM with `textContent` only (test asserts no `innerHTML`).
- Preview = `JarvisPrefabHost` in `preview` mode with manifest `sample` props and data: events are shown locally and never posted.
- The UI does **not** author source (no code editor).
  - Actions: browse, search, filter, inspect, preview, "Place on scene", and "Fork as new prefab" (new id, title, description, sample; source copied unchanged; `POST /api/prefabs` as actor user).
  - Base prefabs show a protection badge and their base-edit history (quoted user request, date, actor). Base edits are made only by the brain through `prefab_edit_base`. The UI explains this instead of offering a button.

### D-TT

No Workspace Task Type vocabulary exists in the repo, so it is waived, as for previous handoffs. Every slice metadata gets `"task_type": "waived"` and `"task_type_resolution_required": false`.

## R2 — Manifest schema (`manifest.json`, `jarvis.prefab` v1)

```json
{
  "schema": "jarvis.prefab",
  "schema_version": 1,
  "id": "jarvis.checklist",
  "version": 1,
  "title": "Checklist",
  "description": "Interactive checklist populated from a list of items.",
  "family": "window",
  "tags": ["list", "tasks", "interactive"],
  "aliases": ["todo", "checklist", "liste de contrôle"],
  "scene": {"kind": "window", "default_size": {"w": 60, "h": 48}},
  "inputs": {
    "props": {"type": "object", "properties": {
      "accent": {"type": "color", "default": "#6ee7ff"},
      "show_progress": {"type": "boolean", "default": true}}},
    "data": {"type": "object", "required": ["items"], "properties": {
      "items": {"type": "array", "max_items": 64, "items": {"type": "object", "required": ["id", "label"],
        "properties": {"id": {"type": "string", "max_length": 64},
                       "label": {"type": "string", "max_length": 200},
                       "done": {"type": "boolean", "default": false},
                       "note": {"type": "text", "max_length": 500}}}}}}
  },
  "events": {
    "item_toggled": {"class": "state", "writes": ["items"],
                     "payload": {"type": "object", "properties": {"items": {"$ref": "data.items"}}}},
    "checklist_completed": {"class": "notify", "summary": "User ticked every item",
                            "payload": {"type": "object", "properties": {"count": {"type": "integer", "min": 0, "max": 64}}}}
  },
  "sample": {"props": {}, "data": {"items": [{"id": "a", "label": "Example", "done": false}]}},
  "files": {"template": "template.html", "style": "style.css", "behavior": "behavior.js"}
}
```

### Field rules (`jarvis/domain/prefab.py`, strict decode, unknown keys refused)

- **`id`**: `^[a-z][a-z0-9_-]{0,31}(\.[a-z][a-z0-9_-]{0,31}){1,3}$`, ≤96 chars. Namespace `jarvis.` is reserved for base prefabs. Because a dot is required, ids can never collide with route segments `events`/`validate`.
- **`version`**: int 1..9999, matching the folder name.
- **Text bounds**: `title` ≤80, `description` ≤600, `family` token ≤32 (`window` now; open vocabulary for later families such as indicators or lights), `tags`/`aliases` ≤16 each, ≤40 chars.
- **`scene.kind`**: must be `window` in v1. `default_size` is in scene units, within domain extents.
- **Input schema types** (nesting depth ≤4; every node may carry `default`, `description` ≤200 and `required` (object only)):

  | type | fields | value rule |
  | --- | --- | --- |
  | `string` | `max_length` ≤2000 (default 200), `pattern`? (anchored, ≤200) | single line |
  | `text` | `max_length` ≤12000, `format`? = `plain` or `markdown` | multi-line, `\n`/`\t` only |
  | `number` / `integer` | `min`, `max` | finite |
  | `boolean` | – | – |
  | `color` | – | `#rrggbb` |
  | `enum` | `values` (1..32 strings) | member |
  | `url` | – | http(s) only, ≤2048 |
  | `object` | `properties` (≤32), `required` | closed: unknown keys refused |
  | `array` | `items` (schema), `max_items` ≤256, `min_items` | – |
  | `$ref` | `"props.<path>"` or `"data.<path>"` | events only, reuses an input schema |

  Defaults are applied by Core at validation; the validated, defaulted value is what is stored. Asset references and child-prefab composition have no existing contract and are out of scope.
- **`events`**: ≤16 per prefab. Name `^[a-z][a-z0-9_]{0,39}$`. `class` is `state` or `notify`. `writes` is required for `state` (top-level keys of `inputs.data`, ≥1) and forbidden for `notify`. `payload` schema ≤ depth 4; payload ≤8 KiB. `summary` ≤120 (shown to the brain).
- **`sample`**: must validate against the inputs (used by preview and `prefab_validate`).
- **`files`**: fixed names in v1. Size bounds: template ≤32 KiB, style ≤32 KiB, behavior ≤64 KiB, manifest ≤32 KiB.
- **Hygiene lint** (rejects; this is not the security boundary, the sandbox is):
  - Template: no `<script`, `<style`, `<iframe`, `<object`, `<embed`, `<base`, `<link`, `<meta`, `<form`, and no `on*=` attributes.
  - Style: no `@import` and no `url(` other than `url(data:`.
  - Behavior: no `</script` (case-insensitive).
- **Classification** is derived, never declared: `base` iff `id` starts with `jarvis.`, otherwise `custom`. The manifest has **no provenance field**; a candidate that carries one is refused.

### `publication.json` (Core-written, `jarvis.prefab.publication` v1)

```json
{"schema": "jarvis.prefab.publication", "schema_version": 1, "prefab_id": "...", "version": 3,
 "fingerprint": "<sha256 of canonical {manifest, template, style, behavior}>",
 "published_at": "2026-10-03T12:00:00Z",
 "provenance": {"origin": "base|custom|fork|revision|base_edit",
                "derived_from": {"id": "...", "version": 1} ,
                "created_by": {"actor": "system|brain|user"},
                "base_edit": {"confirmed_by_user": true, "user_request": "<quoted words ≤500>",
                              "witness": "conversation_event:<event_id>"}}}
```

- `derived_from` is null for `base` and `custom`.
- `base_edit` is null unless `origin = base_edit`.
- The fingerprint uses `jarvis.domain.prompt_registry.fingerprint` over the canonical JSON `{"manifest": <obj>, "template": str, "style": str, "behavior": str}`.

## R3 — Instance block (scene payload)

```json
"payload": {"title": "Release checklist", "summary": "", "items": [],
            "prefab": {"id": "jarvis.checklist", "version": 1,
                       "props": {"accent": "#ff7a59"}, "data": {"items": [ ... ]}}}
```

- `title` stays the window title.
- `summary` is optional fallback text for capture and readers.
- `items` of a prefab window are ignored by the renderer (kept for wire compatibility). Brain guidance: leave empty.

## R4 — Message protocol `jv: 1`

| Direction | Message | Fields |
| --- | --- | --- |
| host→frame | `init` | `instance:{object_id, prefab:{id,version}, mode:"scene"\|"preview"}`, `props`, `data`, `theme:{name, accent, text, muted, surface, scale}` |
| host→frame | `update` | `props`, `data`, `theme` (full values; the shim diffs) |
| host→frame | `teardown` | – (sent before removal; the frame has ≤50 ms) |
| frame→host | `ready` | – (sent by the shim once behavior is loaded; host then sends `init`) |
| frame→host | `event` | `name`, `payload` |
| frame→host | `resize` | `height` (CSS px, number) |
| frame→host | `open_url` | `url` (http/https; validated by the host) |
| frame→host | `error` | `message` ≤300 (shim catches behavior exceptions, `onerror`, `onunhandledrejection`) |

- Every message is `{jv: 1, type, ...}`. Anything else is dropped and counted (`console` key `scene.prefab_message_dropped`).
- **Shim API** in the frame (`window.jarvis`):
  - `on('init'|'update'|'teardown', fn)`, `emit(name, payload)`
  - `props`, `data`, `theme` (read-only snapshots)
  - `renderBlocks(el, blocks)`, `openUrl(url)`
  - automatic `ResizeObserver` → `resize`
  - text binding `data-jv-text="props.x"` / `"data.y"` (textContent only)
  - colour inputs exposed as CSS variables `--jv-prop-<name>`; an input named `accent` of type `color` overrides `--jv-accent`.
- **Error state**: on `error`, or no `ready` within 3 s, the host shows an inline error band in the slot ("Prefab <id>@<v> failed: <message>"), logs `scene.prefab_error`, and keeps the window chrome usable.

## R5 — Storage layout

```
jarvis/prefabs/
  runtime/shim.js, runtime/shell.css              # injected into every srcdoc (versioned with the package)
  base/catalog.lock.json
  base/jarvis.window/1/{manifest.json,template.html,style.css,behavior.js,publication.json}
  base/jarvis.document/1/...  base/jarvis.table/1/...  base/jarvis.checklist/1/...
<data_root>/prefabs/
  <prefab_id>/<version>/{manifest.json,template.html,style.css,behavior.js,publication.json}
  .staging-<hex>/                                  # swept at start
```

`docs/local-data.md` gains the row "prefab library | `prefabs/<prefab_id>/<version>/`" (S02).

## R6 — Modules, validation authority, tools, routes

### Layering (gates in `test_v2_architecture.py` stay green)

| Layer | File | Content |
| --- | --- | --- |
| domain | `jarvis/domain/prefab.py` | id/version grammar, `PrefabManifest`, `InputSchema` parse + `validate_value(schema, value) -> (value_with_defaults, errors)`, `EventDecl`, `Publication`/`Provenance`, `check_state_event(manifest, event, payload, basis, current_data)`, hygiene lint, bundle fingerprint |
| domain | `jarvis/domain/scene.py` | `ScenePrefabRef`, `ScenePayload.prefab`, kind rule, `SceneRefusal.PREFAB_INVALID`, `SceneUpdate.detail` |
| domain | `jarvis/domain/brain_context.py` | `BrainPrefabEvent`, `BrainContext.prefab_events` (≤8) |
| ports | `jarvis/ports/prefabs.py` | `PrefabLibrary` (adapter: `scan()`, `read_version(root, id, v)`, `publish(candidate, publication) -> path`, `sweep()`), `PrefabInstanceValidator` (`validate_instance(ref) -> ValidationResult`), `PrefabStoreError` with codes |
| adapters | `jarvis/adapters/file_prefab_library.py` | `FilePrefabLibrary(package_root, data_root)`: scanning, atomic publish, safe_folders guards; never writes `package_root` |
| core | `jarvis/core/prefab_service.py` | `PrefabService` = catalogue (search, get, bundle), `validate_candidate`, `save`, `edit_base` (gate + witness), `validate_instance` (implements the port), diagnostics `core.prefab.*` |
| core | `jarvis/core/prefab_events.py` | `PrefabEventService(scene: SceneCommandSink & SceneReader, catalog: PrefabService)`: state/notify, ring, rate limit, `take_undelivered_notify()` |
| core | `jarvis/core/scene_service.py` | `prefab_validator` hook (D-SCENE) |
| core | `jarvis/core/v2_app.py` | builds `FilePrefabLibrary(Path(jarvis.__file__).parent/"prefabs"/"base", root)`, `PrefabService`, passes it to `SceneService`, `PrefabEventService`, BrainService provider; `CORE_ADAPTER_IMPORT_EXCEPTIONS["jarvis/core/v2_app.py"] += "jarvis.adapters.file_prefab_library"` |
| protocol | `jarvis/protocol/prefab_routes.py` | `PrefabProtocolRoutes(core).routes()` spliced into `server.py` like `CaptureProtocolRoutes` |
| runtime | `jarvis/runtime/prefab_relay.py` | `CorePrefabTransport` (shared by relay and MCP) + `PrefabRelayRoutes(...).routes()` for the CC; actor forced `user` |
| runtime | `jarvis/runtime/display_prefabs.py` | `PrefabDisplayTools` (MCP logic) |
| runtime JS | `control_center_prefab_protocol.js` (pure: constants, `buildSrcdoc`, `parseFrameMessage`, `hostMessage`, `isAllowedUrl`), `control_center_prefab_host.js` (DOM, sole `srcdoc` site, `createPrefabHost(deps)`), `control_center_prefabs.js` (library UI) | |

**Validation authority**: Core (`PrefabService`) for definitions, instances and events. The MCP and the CC only pre-check shape for better error text. Frontend descriptors are never a second catalogue.

### Core routes (`/v1`, token-authenticated)

Registered **before** any `{prefab_id}` route.

| Method | Path | Body / query | Result |
| --- | --- | --- | --- |
| GET | `/v1/prefabs` | `query?`, `family?`, `class?=base\|custom`, `limit≤50` | rows `{id, latest_version, versions, title, family, class, description, input_names, event_names, base_edited}` |
| GET | `/v1/prefabs/events` | `after?`, `object_id?`, `limit≤50` | ring entries |
| POST | `/v1/prefabs/events` | `{actor:"user", object_id, prefab:{id,version}, event, payload, basis}` | `{outcome: applied\|recorded\|stale\|refused, reason?, detail?, revision?}`; 429 `rate_limited` |
| POST | `/v1/prefabs/validate` | `{candidate}` | `{ok, errors[], fingerprint?}` (no write) |
| POST | `/v1/prefabs` | `{actor, candidate, derived_from?}` | publication; `409 version_exists`, `403 base_protected` for a `jarvis.*` id |
| GET | `/v1/prefabs/{prefab_id}` | – | versions + provenance chain |
| GET | `/v1/prefabs/{prefab_id}/{version}` | `include_source=0\|1` | manifest + publication (+ files ≤128 KiB) |
| GET | `/v1/prefabs/{prefab_id}/{version}/bundle` | – | `{manifest, files, runtime:{version, shim, shell_css}}` (immutable; ETag = fingerprint) |
| POST | `/v1/prefabs/{prefab_id}/base-edits` | `{actor:"brain", candidate, user_request, confirmed_by_user:true}` | publication; `403 base_edit_unconfirmed` |

### Control Center routes (relay, `/api/prefabs` added to `READ_GUARDED_ROUTES`)

`GET /api/prefabs`, `GET /api/prefabs/events`, `POST /api/prefabs/events`, `POST /api/prefabs` (fork/save-as-new from the UI, actor user), `GET /api/prefabs/{prefab_id}`, `GET /api/prefabs/{prefab_id}/{version}`, `GET /api/prefabs/{prefab_id}/{version}/bundle`.

There is no base-edit route on the CC. Each route is quoted in `docs/ARCHITECTURE.md` **by the Slice that registers it** (`test_documented_routes.py`).

### Base-edit gate (`PrefabService.edit_base`)

All of the following must hold:

1. The id is an existing `jarvis.*` id.
2. `confirmed_by_user is True`.
3. `user_request` is 12..500 chars.
4. **Witness**: `user_request` (normalized: casefold, collapsed whitespace, stripped punctuation) is a substring of a user turn recorded in Conversation Events within the last 30 minutes. It is looked up through `ConversationEventQueryService.search` (`core/conversation_event_query.py:260`), injected as a callable `user_utterance_witness(text) -> event_id | None`.

- Failure returns `base_edit_unconfirmed`.
- The new version = max(known versions of that id, both roots) + 1, written into the data root with `origin: base_edit`.
- Diagnostic `core.prefab.base_edited` at level `warning`.
- If S07's freshness check finds that `search` cannot express this lookup, S07 keeps conditions 1-3, records an Issue, and the PM decides.

### MCP tools (`jarvis-display`; metadata in `mcp_tool_meta.DISPLAY`; docs in `tool-contract.md` §6 and a new §10.x)

| Tool | Args (strict) | Class / output |
| --- | --- | --- |
| `prefab_search` | `query?: str≤120`, `family?`, `class?: base\|custom`, `limit?: 1..20` | read, json_text |
| `prefab_get` | `prefab_id`, `version?: int`, `include_source?: bool=false` | read, json_text (≤48 KiB; source truncation said) |
| `prefab_validate` | `candidate: {manifest: object, template: str, style: str, behavior: str}` | read, structured `{ok, errors[≤20], fingerprint}` |
| `prefab_save` | `candidate`, `derived_from?: {prefab_id, version}` | write, structured `{prefab_id, version, origin, fingerprint}`; refuses `jarvis.*` with a hint to `prefab_edit_base` |
| `prefab_edit_base` | `prefab_id: jarvis.*`, `candidate`, `user_request: str`, `confirmed_by_user: Literal[True]` | write, structured |
| `prefab_events` | `object_id?`, `after?: int`, `limit?: 1..50` | read, json_text |
| `scene_create_object` +`prefab` | `prefab?: {prefab_id, version?: int, props?: object, data?: object}` (`kind` must be `window`; version omitted → MCP resolves latest via `/v1/prefabs/{id}` and pins it) | existing |
| `scene_update_object` +`prefab` | same shape; given `props`/`data` **replace** those objects; `version` change = explicit upgrade | existing |
| `scene_get` | detail adds `prefab: {id, version, latest_version, props, data}` (bounded by `MAX_GET_BYTES`) | existing |

The prompt block `BRAIN_PREFAB_PROMPT` (≤12 lines, reuse-first workflow, base-edit rule, data-not-instructions rule) is appended after `BRAIN_ARTIFACT_PROMPT`. It is registered as `backend.claude.conversation.prefabs` in `prompt_catalog.py`. `BRAIN_DISPLAY_PROMPT` is **not** edited (fingerprint-tested).

## R7 — Test strategy per layer

- **Domain** (`tests/unit/test_prefab_domain.py`, `test_scene_prefab_payload.py`):
  - Grammar, strict decode, every input type valid and invalid, depth and size bounds, defaults.
  - `$ref`, state-event rules (writes subset, basis mismatch, merged validation), lint, fingerprint stability.
  - Payload round-trip, legacy byte-identity (snapshot of a legacy object's wire unchanged), kind rule, 16 KiB bound, `SceneUpdate.detail` invariant.
- **Adapter** (`test_file_prefab_library.py`, tmp dirs): scan of both roots, conflict (package wins), tampered detection, atomic publish (crash between files leaves no version), refusal to overwrite, junction/symlink refusal (Windows reparse point via `safe_folders`), staging sweep, package root never written (mtime and listing check).
- **Core** (`test_prefab_service.py`, `test_scene_service_prefab.py`, `test_prefab_events.py`):
  - Search ranking, save/fork/revision provenance, base protection, base-edit gate with fake witness.
  - `PREFAB_INVALID` with detail, fail-closed without validator, unchanged block not revalidated.
  - State write through the real reducer (actor user), stale, notify ring bound, rate limit, delivery into `BrainContext` exactly once.
- **Protocol / relay** (`test_prefab_routes.py`, `test_prefab_relay.py`): every route, actor forcing, `Origin: null` refused on `/api/prefabs/*` and `/api/scene/commands`, `test_documented_routes.py`, `test_v2_architecture.py`.
- **JS (node, `run_node` pattern of `test_scene_interaction_logic.py:65`)**:
  - `test_prefab_protocol_js.py`: `buildSrcdoc` puts the CSP meta first in `<head>`, sandbox constant, message validation, URL rule.
  - `test_prefab_shim_js.py`: the shim is a factory `createShim(env)` with injected `post`, `listen` and a minimal fake DOM.
  - `test_prefab_host_js.py`: `createPrefabHost(deps)` with fake iframe and document. Mount once, update without remount, remount on version change, unmount removes the listener, source/origin check, rate limit, cap 24 with LRU, error band, preview mode never posts.
  - Static: `srcdoc` only in `control_center_prefab_host.js`; no `innerHTML` in scene page or prefab modules; pure modules free of `document.`/`window.`/`fetch(`.
- **Browser (Chrome via claude-in-chrome on the real CC, from S03 on)**:
  - Sandbox attribute, CSP blocks `fetch` (fixture `test.netprobe` logs a CSP violation and posts `error`), `parent.document` throws.
  - Resize and height fit, drag and resize of a prefab window, keyboard (checklist), capture fallback.
  - 200 create/archive cycles without growth of frame count or listeners (S09).
- **Agent (S07, S09)**: `agent-trace-analysis` on real Claude CLI conversation turns with jarvis-display.

## R8 — Explicit overrides of docs 00-05 and SLICE bodies

1. Doc 02 §5 and S05 "recover the agreed Rework FENETRES families": no durable record exists. D-FAMILIES replaces it; the Human confirms through HV-WINDOW-FAMILIES-01.
2. Doc 02 §2 instance shape: no `owner{board_id,task_id,agent_id}`, no separate `state`, no instance id beyond `object_id`. See D-SCENE.
3. Doc 02 §3 "asset/reference" and "prefab/child reference": out of scope (no existing contract). Composition = shared shell only.
4. Doc 02 example `"version": "1.2.0"`: versions are integers (testlab `.v<N>` convention).
5. Doc 03 step 9 / S09 "remove duplicate legacy paths": the legacy window renderer is retained (D-LEGACY).
6. S01 "possibly schema stubs": S01 is docs only.
7. S08 "explicit base-edit affordance": the UI shows protection and history; base edits are agent-mediated (D-UI).
8. Constellation decision 1 ("semantic scene rather than generating HTML") is **refined, not reversed**. Ordinary display stays semantic (instance = id, version and data). HTML/CSS/JS authoring is confined to library definitions, validated by Core and sandboxed. `docs/scene-model.md` records this.
9. README "task_type null": waived (D-TT).

## R9 — Agent 0 amendments (after review of this document)

1. **State-event race (D-EVENTS).** `jarvis/domain/scene.py` has no compare-and-set
   (`expected_revision` absent). S04 must close the read→apply window rather than
   only narrowing it: perform the `basis` check *inside* the `SceneService` lock
   (e.g. a `SceneService.apply_if(command, precondition)` whose precondition runs
   on the current snapshot under the lock, or an equivalent minimal seam). If that
   seam proves invasive, S04 stops and reports to the PM before choosing the
   documented last-writer-wins fallback.
2. **Risks** of this architecture are recorded in `slices/00-project-manager/READINESS.md` §Risks.
