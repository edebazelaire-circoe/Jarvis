# Scene window prefabs

Handoff `tasks/jarvis-scene-window-prefab-foundation/`. This page is the
canonical contract for prefabs: what a prefab definition is, how it is stored,
validated, rendered in a scene window, how its user events reach Core and the
brain, and which tools and routes expose it. The scene itself (objects,
reducer, authority, revisions) stays [scene-model.md](scene-model.md); the
security boundary is [SECURITY.md](SECURITY.md) › *16. Prefab sandbox*.

Every section carries its status. "Contract" means the rule is decided and
binding but the code does not exist yet; the named Slice implements it and
turns the status to "implemented". **Until a route is registered, its path is
quoted only here** (`tests/unit/test_documented_routes.py` checks every `/api/…`
path quoted in `ARCHITECTURE.md` and `OPERATIONS.md`).

## Terminology

Status: definition, publication and library implemented (Slice 02); frame
runtime and read routes implemented (Slice 03); instance block, events and
scene integration (Slice 04) still contract.

| Term | Meaning |
| --- | --- |
| **prefab definition** | A reusable window body: `manifest.json` + `template.html` + `style.css` + `behavior.js`, identified by a prefab id. Authored HTML/CSS/JS lives **only** here. |
| **version** | Integer 1..9999. One immutable folder per `(prefab id, version)`; a published version is never rewritten. |
| **publication** | `publication.json`, written by Core when a version is published: bundle fingerprint, date, provenance. |
| **base prefab** | A definition whose id starts with `jarvis.`. Shipped in the package, protected: changed only through the base-edit gate. |
| **custom prefab** | Any other id. Published into the data-root library. |
| **provenance origin** | `base` (shipped), `custom` (new id), `fork` (new id derived from another prefab), `revision` (new version of an existing custom id), `base_edit` (new version of a `jarvis.*` id through the gate). |
| **instance block** | The optional `prefab` key of a window's `ScenePayload`: `{id, version, props, data}`. An instance is a scene object; it has no id beyond `object_id` and never carries code. |
| **props / data** | Two JSON objects validated against the manifest's `inputs.props` / `inputs.data`. `data` is the canonical persisted instance state; there is no separate `state` field. |
| **frame** | The sandboxed `<iframe>` that renders one instance inside the window body. |
| **shim** | `jarvis/prefabs/runtime/shim.js`, injected into every frame: the `window.jarvis` API and the message protocol. |
| **shell** | `jarvis/prefabs/runtime/shell.css`, injected into every frame: shared `.jv-*` classes and CSS variables. Composition between prefabs is this shared shell only. |
| **legacy window** | A window whose payload has no `prefab` block. Rendered by the existing DOM renderer, unchanged. |

Classification is derived, never declared: `base` iff the id starts with
`jarvis.`, otherwise `custom`.

## Canonical paths

Status: contract — implemented by Slices 02–04; legacy retention proved by Slice 09.

- **One scene path.** Every instance is created, updated, moved, hidden,
  reordered and archived as an ordinary scene object through
  `SceneService.apply` (`jarvis/core/scene_service.py`) and
  `apply_scene_command`. There is no parallel instantiate op or tool.
- **One prefab path.** Definitions, instances and events are validated by
  `PrefabService` (`jarvis/core/prefab_service.py`) in Core. Every instance
  renders in one sandboxed runtime (`jarvis/runtime/control_center_prefab_host.js`).
  The MCP and the Control Center only pre-check shape for better error text;
  no frontend descriptor is a second catalogue.
- **Legacy stays first-class.** Objects without a `prefab` block keep the
  current renderer; nothing is migrated. The projector, `scene_add_artifact`,
  the presentation stager and the file watcher keep using it. The legacy path
  is not deleted.

## Manifest (`manifest.json`, `jarvis.prefab` v1)

Status: implemented by Slice 02 (`jarvis/domain/prefab.py`, tests
`tests/unit/test_prefab_domain.py`, fixtures `tests/fixtures/prefabs/`).

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

Strict decode: unknown keys are refused at every level. Errors are collected
in one pass, each named by its path (`inputs.data.items[].label: ...`): at
most 20 errors of at most 300 characters each, never echoing a large value.

Required: `schema`, `schema_version`, `id`, `version`, `title`, `family`,
`scene`, `inputs`, `sample`, `files`. Optional: `description` (""), `tags`,
`aliases` ([]), `events` ({}), `scene.default_size` (none). `inputs` is exactly
`{props, data}`, each an `object` schema; `sample` is exactly `{props, data}`.
Property names match `[A-Za-z_][A-Za-z0-9_]{0,63}`. Core assigns the version
of a published candidate (the folder name): the highest **occupied** version
number of that id + 1, counting every numbered version folder in both roots,
catalogued or not (an empty or refused folder still takes its number, so it
never turns later saves into `version_exists`). The candidate's `version` is
replaced before the fingerprint is computed.

| Field | Rule |
| --- | --- |
| `id` | `^[a-z][a-z0-9_-]{0,31}(\.[a-z][a-z0-9_-]{0,31}){1,3}$`, ≤ 96 chars. Namespace `jarvis.` reserved for base prefabs. A dot is required, so an id never collides with the route segments `events` / `validate`. |
| `version` | int 1..9999, equal to the folder name. |
| `title` / `description` | ≤ 80 / ≤ 600 chars. |
| `family` | token ≤ 32; `window` in v1, open vocabulary for later families. |
| `tags`, `aliases` | ≤ 16 each, ≤ 40 chars each. |
| `scene.kind` | `window` in v1. `default_size` in scene units, within domain extents. |
| `events` | ≤ 16. Name `^[a-z][a-z0-9_]{0,39}$`. `class` = `state` or `notify`. `writes` required for `state` (≥ 1 top-level key of `inputs.data`), forbidden for `notify`. `payload` (required) is an `object` schema, depth ≤ 4; a `state` payload carries only keys it `writes`; payload ≤ 8 KiB. `summary` ≤ 120 (shown to the brain). |
| `sample` | must validate against `inputs` (preview and `prefab_validate`). |
| `files` | fixed names in v1. Bounds: template ≤ 32 KiB, style ≤ 32 KiB, behavior ≤ 64 KiB, manifest ≤ 32 KiB. |
| provenance | **absent**: a candidate manifest that carries a provenance field is refused. Provenance is Core-written in `publication.json`. |

### Input schema

Nesting depth ≤ 4, counted from the root object (`inputs.props`) at 0, and
checked on the **effective** schema: a `$ref` inlines the referenced subtree
at its own depth, so `depth of the $ref + depth of the subtree ≤ 4`. Every
node may carry `default` (validated against the node itself), `description`
(≤ 200) and, for `object` only, `required`. A `text` without `max_length` is
bounded at 2000 characters; an `array` without `max_items` at 256. A missing
optional key with a `default` receives a copy of it; a missing `required` key
without one is an error.

| Type | Fields | Value rule |
| --- | --- | --- |
| `string` | `max_length` ≤ 2000 (default 200), `pattern`? (anchored, ≤ 200) | single line |
| `text` | `max_length` ≤ 12000, `format`? = `plain` \| `markdown` | multi-line, `\n` / `\t` only |
| `number` / `integer` | `min`, `max` | finite |
| `boolean` | – | – |
| `color` | – | `#rrggbb` |
| `enum` | `values` (1..32 strings) | member |
| `url` | – | http(s) only, ≤ 2048 |
| `object` | `properties` (≤ 32), `required` | closed: unknown keys refused |
| `array` | `items` (schema), `max_items` ≤ 256, `min_items` | – |
| `$ref` | `"props.<path>"` or `"data.<path>"` | events only; reuses an input schema |

Core applies defaults at validation; the validated, defaulted value is the one
stored. Asset references and child-prefab composition have no contract and are
out of scope.

### Hygiene lint

Rejects, but is **not** the security boundary (the sandbox is):

- template: no `<script`, `<style`, `<iframe`, `<object`, `<embed`, `<base`,
  `<link`, `<meta`, `<form` (one error per forbidden tag, not per
  occurrence), no `on*=` attribute — attributes are read tag by tag with
  quoted values blanked, so a quoted `>` (`<img title=">" onerror=x>`) does
  not hide a handler and handler-like text inside a value is not one;
- style: no `@import`, no `url(` other than `url(data:`, no `image-set(`
  (and `-webkit-image-set(`) whose quoted arguments are not `data:` URLs;
- behavior: no `</script` (case-insensitive).

The lint is hygiene, not a parser: CSS escape sequences (`u\72l(`), comments
splitting a token and similar obfuscations are not decoded (see *Known
limitations*).

## Publication and provenance (`publication.json`, `jarvis.prefab.publication` v1)

Status: implemented by Slice 02 (`Publication`, `Provenance` in `jarvis/domain/prefab.py`).

```json
{"schema": "jarvis.prefab.publication", "schema_version": 1, "prefab_id": "...", "version": 3,
 "fingerprint": "<sha256 of canonical {manifest, template, style, behavior}>",
 "published_at": "2026-10-03T12:00:00Z",
 "provenance": {"origin": "base|custom|fork|revision|base_edit",
                "derived_from": {"id": "...", "version": 1},
                "created_by": {"actor": "system|brain|user"},
                "base_edit": {"confirmed_by_user": true, "user_request": "<quoted words ≤500>",
                              "witness": "conversation_event:<event_id>"}}}
```

- Written by Core only. `derived_from` is null for `base` and `custom`; for
  `fork` it is the source (another id); for `revision` and `base_edit` it is
  the latest version of the same id at publication. `base_edit` is null unless
  `origin = base_edit`. `base` and `base_edit` only for `jarvis.*` ids, the
  other origins only for custom ids. For `revision` and `base_edit`,
  `derived_from.version` is lower than the published version. `created_by.actor`
  is `system` for shipped bases, `brain` for `base_edit` (the base-edit gate
  accepts no other actor), `brain` or `user` otherwise.
- The fingerprint is `jarvis.domain.prompt_registry.fingerprint` over the
  canonical JSON `{"manifest": <obj>, "template": str, "style": str, "behavior": str}`,
  bounded by `MAX_FINGERPRINT_BYTES` — the JSON-escaping worst case of the
  per-file bounds (a control character becomes `\u00XX`, 6 bytes), so any
  bundle within its file bounds is fingerprintable.
- "Diverged from saved definition" means `version < latest_version` (reported
  by `scene_get` and the library). An instance cannot change code.

## Storage and library

Status: implemented by Slice 02 — adapter `jarvis/adapters/file_prefab_library.py`
(port `jarvis/ports/prefabs.py`), catalogue `jarvis/core/prefab_service.py`,
built in `jarvis/core/v2_app.py` as `JarvisCoreApplication.prefabs` (not yet
given to `SceneService`: Slice 04), with `FilePrefabRuntime`
(`jarvis/prefabs/runtime/`, read-only) for the bundles (Slice 03). The base catalogue is empty until Slice 05
(`jarvis/prefabs/base/catalog.lock.json`, test `tests/unit/test_prefab_base_lock.py`).
Fingerprints cover the exact bytes read from disk, so `.gitattributes` keeps
`jarvis/prefabs/**` and `tests/fixtures/prefabs/**` in LF on checkout (a CRLF
checkout would make every shipped base `tampered`).
No SQLite, no DDL, no migration.

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

- **Package root** (`jarvis/prefabs/base/`): base prefabs and their shipped
  `publication.json`, plus `catalog.lock.json` (`jarvis.prefab.catalog_lock` v1,
  one entry `{prefab_id, version, fingerprint}` per base version — the Test Lab
  lock pattern, [testlab.md](testlab.md)). Never written at runtime. A test
  asserts the lock matches the files: nothing edited in place, no unlocked or
  orphan version.
- **Data-root library** (`<data_root>/prefabs/`, [local-data.md](local-data.md)):
  one shared library per Jarvis install, not per Board, Session or user.
  Worktrees and `jarvis-dst` have their own data root, hence their own library.
- **Immutable publish.** Files are written into `<data_root>/prefabs/.staging-<16 hex>/`
  (each by temp-then-replace, `file_replace.replace_with_retry`), then the folder
  is renamed with `os.rename` to `<prefab_id>/<version>`, which fails if the
  target exists. Folders go through `safe_folders.ensure_folder_tree` and
  `check_file_path`; links, junctions and reparse points are refused. Stale
  `.staging-*` folders are swept at start.
- **Catalogue** = union of both roots, discovered by scanning
  `*/<int>/manifest.json`; no central table. Bounds: ≤ 512 ids, ≤ 64 versions
  per id. Fingerprints are recomputed on load: a mismatch with
  `publication.json` marks the version `tampered` (refused for new instances,
  diagnostic `core.prefab.tampered`). The same `(id, version)` in both roots:
  the package wins (`core.prefab.version_conflict`). Manifests are cached by
  `(root, id, version, fingerprint)`; rescan on list and after each publish.
- **Base edit** = a new version of a `jarvis.*` id written into the
  **data-root** library through the base-edit gate below, recorded in
  `publication.json.provenance.base_edit`.
- **Refused versions.** Besides a fingerprint mismatch, a version is
  `tampered` when a source file or `publication.json` is missing, unreadable
  as UTF-8 or above its bound, when the manifest is invalid or names another
  folder, or when its origin does not belong to its root (`base` only in the
  package, never `base` in the data root). A version the disk refuses to read
  (link, permission) is `unreadable` (`storage_io`). Each is reported once
  (`core.prefab.tampered`), not on every listing; a folder that is not a
  prefab id or a version, or a link, is skipped (`core.prefab.scan_problem`).
- **Save rules** (`PrefabService.save`, actor `brain` or `user`): a new custom
  id is `custom`, or `fork` with `derived_from` (which must exist and be
  healthy); either way a new id is refused once the catalogue holds 512 ids.
  An existing custom id is a `revision` (highest occupied version + 1); a
  `jarvis.*` id is `base_protected`. Publications are serialized in Core.
- **Errors** (`PrefabStoreError`, `jarvis/ports/prefabs.py`): `unknown_prefab`
  and `unknown_version` (404), `tampered` and `version_exists` (409),
  `base_protected` and `base_edit_unconfirmed` (403), `invalid_definition`
  (400, with the collected `errors`), `storage_io` (500).
- **Diagnostics** (`core.prefab.*`): `catalog_loaded`, `catalog_unavailable`,
  `scan_problem`, `tampered`, `version_conflict`, `saved`, `save_refused`,
  `save_failed`, `base_edited`, `base_edit_refused`, `swept`, `sweep_failed`.
  Ids, versions and codes only; the user's words in a base-edit request
  never enter the journal (their length does).

## Instance block

Status: contract — implemented by Slice 04. Scene-side rules (kind, wire,
validation hook, refusal) are in [scene-model.md](scene-model.md) › *Prefab windows*.

```json
"payload": {"title": "Release checklist", "summary": "", "items": [],
            "prefab": {"id": "jarvis.checklist", "version": 1,
                       "props": {"accent": "#ff7a59"}, "data": {"items": [ ... ]}}}
```

- `version` is always exact, never "latest". The brain tool resolves an
  omitted version to the latest and pins it.
- `title` stays the window title (drawn by the head, read by `scene_inspect`,
  drawn by capture). `summary` is optional fallback text for capture and
  readers. `items` are ignored by the renderer for a prefab window (kept for
  wire compatibility; the brain leaves them empty).
- Ownership and provenance of an instance use existing fields only: `origin`,
  `constraints.placed_by`, and the definition's `publication.json`. No Board,
  task or agent owner.
- Show, hide, reorder and destroy are the existing ops (`set_visibility`,
  `layer` / `order`, `archive`). Focus has no op.

## Runtime: one sandboxed frame per instance

Status: runtime implemented by Slice 03 —
`jarvis/runtime/control_center_prefab_protocol.js` (pure:
`window.JarvisPrefabProtocol`), `jarvis/runtime/control_center_prefab_host.js`
(`window.JarvisPrefabHost`, `createPrefabHost(deps)`),
`jarvis/prefabs/runtime/shim.js` (`createShim(env)` + frame bootstrap) and
`shell.css`; tests `tests/unit/test_prefab_protocol_js.py`,
`test_prefab_shim_js.py`, `test_prefab_host_js.py`. Scene page integration
(`fill()` slot, `naturalWindowHeight`, capture fallback) is still contract —
Slice 04. Until then nothing in the page mounts a frame.

- **Sandbox.** Every instance, base or custom, renders in one runtime: an
  `<iframe>` owned by the window node, `sandbox="allow-scripts"` exactly —
  never `allow-same-origin`, `allow-popups`, `allow-forms`,
  `allow-top-navigation` or `allow-modals`. Opaque origin: no Control Center
  cookies or storage, no `parent.document`.
- **srcdoc**, built by the host (`buildSrcdoc`) in this order:
  1. `<meta charset="utf-8">`
  2. `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'">`
     — right after the charset, before anything that can load (a charset meta loads nothing)
  3. `<style>` shell.css
  4. `<style>` prefab style
  5. `<body>` template
  6. `<script>` shim
  7. `<script>` behavior, wrapped by the shim loader (`__jvLoad(function(jarvis){…})`)

  No `'unsafe-eval'`; network blocked by `default-src 'none'`. A closing
  `</style` or `</script` inside the shell, the style, the shim or the
  behavior is escaped (`<\/…`), and `<!--` in a script too, so no text can
  leave its block (the lint is hygiene; this is not the boundary either).
- **One HTML path.** The scene page keeps zero `innerHTML`,
  `insertAdjacentHTML`, `outerHTML`. Setting `iframe.srcdoc` as a property is
  the only HTML path and lives only in `jarvis/runtime/control_center_prefab_host.js`
  (static test: `srcdoc` in no other runtime file, sandbox value the literal
  `allow-scripts`).
- **Prefab JS limits.** No network, no parent DOM, no tools, no storage. Its
  only outputs are the frame→host messages below.
- **Host-owned chrome.** Head (dot, category, pin, state badge, origin button),
  grip, drag, resize, selection, pin, Bare Hands zones and keyboard entry are
  drawn by the scene page exactly as for a legacy window; the frame fills only
  the body. Interaction semantics do not change.
- **Lifecycle** (`createPrefabHost`). One frame per object id, kept in a host
  `Map`, never detached during updates: `fill()` keeps a persistent
  `.sc-prefab-slot`; a props, data or theme change is `host.update` (diffed by
  JSON string), never a re-fill. Remount only on a `(prefab id, version)`
  change, a shape change away from `window` (compact or capsule draw) or
  removal. At most 24 live frames (LRU by last visible draw: `touch(objectId)`
  on each draw); beyond, the least recently drawn frame receives `teardown`
  and its slot shows a static "paused" placeholder with the title; touching it
  resumes it (and pauses the next least recent). One bundle request per
  `id@version` (kept in memory; a failed request is not kept).
- **Host API.** `createPrefabHost({fetchBundle, document, window, now,
  setTimeout, clearTimeout, log, postEvent, mode, theme, onResize,
  onPreviewEvent, openUrl})` → `mount(slot, instance)`, `update(objectId,
  props, data, theme)`, `unmount(objectId)`, `pause` / `resume` / `touch` /
  `reload(objectId)`, `height(objectId)`, `state(objectId)`, `stats()`,
  `destroy()`. `JarvisPrefabHost.bundleFetcher(fetch)` reads
  `GET /api/prefabs/{id}/{version}/bundle`, checks `response.ok` and unfolds
  the `{error: {code, message}}` envelope. While a frame loads, the slot says
  so (« Chargement du prefab <id>@<v> »); the 3 s `ready` deadline runs from
  the mount, so a slow bundle request is covered too.
- **Height.** The frame reports `resize{height}` (clamped 24..4000 px);
  `naturalWindowHeight` treats `.sc-prefab-slot` as a growing child of that
  height, so `fitBrainWindows` keeps working.
- **Markdown.** One parser: for every input declared
  `{"type": "text", "format": "markdown"}` (nested in objects and arrays too)
  the host converts the value with `JarvisSceneLayout.markdownBlocks` and posts
  the blocks **beside** the values, in `blocks: {"<path>": blocks}` (`data.notes`,
  `data.items.0.note`). The values stay text, so what a `state` event sends back
  is exactly what Core stored. The shim's `jarvis.renderBlocks(el, blocks)`
  builds DOM through `textContent`, mirroring the page's `appendBlocks`; a link
  is drawn without `href` (a frame never navigates) and opens through `openUrl`.
- **Capture.** `drawCommands` draws a prefab window as head + `payload.title` +
  a muted line `prefab <id>@<version>` + `payload.summary` if non-empty. The
  host cannot rasterize a sandboxed frame: a stated limitation.

### Message protocol `jv: 1`

Status: implemented by Slice 03 (`control_center_prefab_protocol.js`, `shim.js`).

| Direction | Message | Fields |
| --- | --- | --- |
| host→frame | `init` | `instance:{object_id, prefab:{id,version}, mode:"scene"\|"preview"}`, `props`, `data`, `theme:{name, accent, text, muted, surface, scale}`, `blocks` |
| host→frame | `update` | `props`, `data`, `theme`, `blocks` (full values; the shim diffs) |
| host→frame | `teardown` | – (sent before removal; the frame has ≤ 50 ms) |
| frame→host | `ready` | – (sent by the shim once behavior is loaded; the host then sends `init`) |
| frame→host | `event` | `name`, `payload` |
| frame→host | `resize` | `height` (CSS px, number) |
| frame→host | `open_url` | `url` (http/https, validated by the host, opened with `noopener,noreferrer` — same rule as `itemRow`) |
| frame→host | `error` | `message` ≤ 300 (the shim catches behavior exceptions, `onerror`, `onunhandledrejection`) |

- Every message is `{jv: 1, type, ...}` over `postMessage`, with exactly the
  fields above (an unknown field is refused). Anything else is dropped and
  counted (`scene.prefab_message_dropped`). `resize` is clamped and rounded,
  `error` is stripped of control characters and bounded, `event` payloads are
  JSON objects ≤ 8 KiB with a declared name; an `event` before `ready` or not
  declared by the manifest is dropped too.
- The host accepts a message only if `event.source === iframe.contentWindow`
  and `event.origin === "null"`. Host→frame messages use `targetOrigin "*"`
  (an opaque origin cannot be targeted) and carry only the instance's own
  props, data and theme, never secrets.
- **Shim API** (`window.jarvis`): `on('init'|'update'|'teardown', fn)` (returns
  an unsubscribe function; handlers receive `{props, data, theme, instance,
  changed}`), `emit(name, payload)`; read-only, frozen `props`, `data`,
  `theme`, `instance`; `blocks(path)`; `renderBlocks(el, blocks)`,
  `openUrl(url)`; automatic `ResizeObserver` on `body` → `resize`; text binding
  `data-jv-text="props.x"` / `"data.y.z"` (textContent only) and markdown
  binding `data-jv-markdown="data.notes"` (blocks), re-applied on `init` and
  on every `update`; colour inputs exposed as `--jv-prop-<name>` — every
  top-level prop whose value has the form `#rrggbb` (Core has already
  validated a `color` input to that form) — and a prop `accent` of that form
  overrides `--jv-accent`. Exceptions at load, in a handler (rejected promises
  included), `onerror` and `onunhandledrejection` are posted as `error`, at
  most 20 per frame. A click on any `<a href>` in the frame is cancelled and
  an http(s) target goes through `openUrl`.
- **Shell variables**: `--jv-accent`, `--jv-text`, `--jv-muted`,
  `--jv-surface`, `--jv-font`, `--jv-scale`.
- **Error state**: on `error`, a refused bundle, or no `ready` within 3 s, the
  slot shows an inline band "Prefab <id>@<v> failed: <message>" (`role=alert`)
  with a « Recharger » button (remount), logs `scene.prefab_error` (at most 5
  log lines per frame), and the window chrome stays usable. A late `ready`
  clears a timeout band; a real error stays shown.
- **Host limits**: ≤ 10 outputs per second per frame (`event` and
  `open_url` share the budget), excess dropped and counted
  (`scene.prefab_event_rate_limited`). Client log keys: `scene.prefab_mounted`,
  `scene.prefab_error`, `scene.prefab_message_dropped`,
  `scene.prefab_event_rate_limited`, `scene.prefab_event_failed`.

## Events

Status: contract — implemented by Slice 04 (`jarvis/core/prefab_events.py`);
brain-turn surfacing by Slice 07.

Path: frame → host (`control_center_prefab_host.js`) → Control Center relay
(actor forced `user`) → Core `PrefabEventService`. Each event is declared in
the manifest with one of two classes. **No event executes a tool.**

- **`state`** declares `writes: [<top-level data keys>]`. The frame emits
  `payload = {<written key>: <new value>}`; the host attaches
  `basis = {k: lastSentData[k]}`. Core checks, in order:
  1. the object is active, kind `window`, and its `prefab.id` / `version`
     match the request;
  2. the event is declared and of class `state`;
  3. the payload keys are a subset of `writes`;
  4. `basis` deep-equals the current `data` on those keys — otherwise outcome
     `stale`, nothing written, and the host re-sends `update` from the scene
     stream;
  5. `merged = {**data, **payload}` validates against the data schema.

  Core then applies `PATCH_OBJECT` as actor `user` through
  `SceneCommandSink.apply`; the reducer stays the authority and the instance
  validator runs again. The `basis` check runs **inside** the `SceneService`
  lock (a precondition evaluated on the current snapshot), so no concurrent
  write slips between check and apply. No rule language, no reducer per prefab.
- **`notify`** records the event and writes nothing.
- **Event log.** Both classes enter a bounded in-memory ring of 256 entries
  (`seq`, `at`, `object_id`, `prefab_id@version`, `event`, `class`, `payload`
  ≤ 8 KiB, `outcome`); each also emits diagnostic `core.prefab.event`. The
  brain reads it with `prefab_events`.
- **Turn surfacing.** Undelivered `notify` events (≤ 8, oldest first, payload
  preview ≤ 1 KiB each) enter the optional `BrainContext.prefab_events` block
  of the next brain turn, serialized by `_turn_context` as `prefab_events`
  (absent when empty, so the context is byte-identical otherwise), then marked
  delivered. A notify does not open a brain turn.
- **Limits.** Host: ≤ 10 events/s per frame, excess dropped and counted.
  Core: token bucket of 30 events/s, beyond → 429 `rate_limited`.

## Modules and validation authority

Status: the Slice 02 and Slice 03 rows are implemented (for `prefab_routes.py` and `prefab_relay.py`: the read routes); the others are contract, implemented by the Slice noted.

| Layer | File | Content | Slice |
| --- | --- | --- | --- |
| domain | `jarvis/domain/prefab.py` | id/version grammar, `PrefabManifest`, `InputSchema` parse + `validate_value(schema, value) -> (value_with_defaults, errors)`, `EventDecl`, `Publication` / `Provenance`, `check_state_event(manifest, event, payload, basis, current_data)`, hygiene lint, bundle fingerprint | 02 |
| domain | `jarvis/domain/scene.py` | `ScenePrefabRef`, `ScenePayload.prefab`, kind rule, `SceneRefusal.PREFAB_INVALID`, `SceneUpdate.detail` | 04 |
| domain | `jarvis/domain/brain_context.py` | `BrainPrefabEvent`, `BrainContext.prefab_events` (≤ 8) | 07 |
| ports | `jarvis/ports/prefabs.py` | `PrefabLibrary` (`scan()`, `read_version(root, id, v)`, `publish(bundle, publication) -> "<id>/<version>"`, `sweep()`), `PrefabInstanceValidator` (`validate_instance(PrefabInstanceRef) -> InstanceValidation`), `PrefabStoreError` with codes | 02 |
| adapters | `jarvis/adapters/file_prefab_library.py` | `FilePrefabLibrary(package_root, data_root)`: scanning, atomic publish, `safe_folders` guards; never writes `package_root` | 02 |
| core | `jarvis/core/prefab_service.py` | `PrefabService` = catalogue (search, get, bundle), `validate_candidate`, `save`, `edit_base` (gate + witness), `validate_instance` (implements the port), diagnostics `core.prefab.*` | 02 |
| core | `jarvis/core/prefab_events.py` | `PrefabEventService(scene: SceneCommandSink & SceneReader, catalog: PrefabService)`: state / notify, ring, rate limit, `take_undelivered_notify()` | 04 |
| core | `jarvis/core/scene_service.py` | `prefab_validator` hook | 04 |
| core | `jarvis/core/v2_app.py` | builds `FilePrefabLibrary(Path(jarvis.__file__).parent/"prefabs"/"base", root)` and `PrefabService`, passes it to `SceneService`, `PrefabEventService` and the BrainService provider; `jarvis.adapters.file_prefab_library` joins `CORE_ADAPTER_IMPORT_EXCEPTIONS["jarvis/core/v2_app.py"]` | 02, 04, 07 |
| protocol | `jarvis/protocol/prefab_routes.py` | `PrefabProtocolRoutes(core).routes()`, spliced into `server.py` like `CaptureProtocolRoutes` | 03, 04, 07 |
| runtime | `jarvis/runtime/prefab_relay.py` | `CorePrefabTransport` (shared by relay and MCP) + `PrefabRelayRoutes(...).routes()` for the Control Center; actor forced `user` | 03, 04, 08 |
| runtime | `jarvis/runtime/display_prefabs.py` | `PrefabDisplayTools` (MCP logic) | 07 |
| runtime JS | `jarvis/runtime/control_center_prefab_protocol.js` | pure: constants, `buildSrcdoc`, `parseFrameMessage`, `hostMessage`, `isAllowedUrl` | 03 |
| runtime JS | `jarvis/runtime/control_center_prefab_host.js` | DOM, sole `srcdoc` site, `createPrefabHost(deps)` | 03 |
| runtime JS | `jarvis/runtime/control_center_prefabs.js` | library UI | 08 |

**Validation authority: Core** (`PrefabService`) for definitions, instances
and events. The layering gates of `tests/unit/test_v2_architecture.py` stay
green: domain and ports import no infrastructure, core never imports
`jarvis.runtime`, and core reaches adapters only through the named
composition-root exception of `v2_app.py`.

## Core routes (`/v1`, token-authenticated)

Status: the Slice 03 rows are registered (`jarvis/protocol/prefab_routes.py`,
test `tests/unit/test_prefab_routes.py`); the others are contract, registered
by the Slice in the last column. Fixed segments are registered **before** any
`{prefab_id}` route. Refusals use the `PrefabStoreError` codes and statuses
(`unknown_prefab` / `unknown_version` 404, `tampered` 409, `storage_io` 500),
`invalid_request` 400 for a malformed query, `core_unavailable` 503 before
start. The bundle's `runtime.version` is the first 16 hex of the fingerprint
of `{shim, shell_css}`; its `ETag` is `"<version fingerprint>.<runtime
version>"` (`If-None-Match` → 304). No runtime wired, or a runtime file
missing → `storage_io` (`core.prefab.runtime_unavailable`).

| Method | Path | Body / query | Result | Slice |
| --- | --- | --- | --- | --- |
| GET | `/v1/prefabs` | `query?`, `family?`, `class?=base\|custom`, `limit≤50` | rows `{id, latest_version, versions, title, family, class, description, input_names, event_names, base_edited}` | 03 |
| GET | `/v1/prefabs/events` | `after?`, `object_id?`, `limit≤50` | ring entries | 04 |
| POST | `/v1/prefabs/events` | `{actor:"user", object_id, prefab:{id,version}, event, payload, basis}` | `{outcome: applied\|recorded\|stale\|refused, reason?, detail?, revision?}`; 429 `rate_limited` | 04 |
| POST | `/v1/prefabs/validate` | `{candidate}` | `{ok, errors[], fingerprint?}` (no write) | 07 |
| POST | `/v1/prefabs` | `{actor, candidate, derived_from?}` | publication; `409 version_exists`, `403 base_protected` for a `jarvis.*` id | 07 |
| GET | `/v1/prefabs/{prefab_id}` | – | versions + provenance chain | 03 |
| GET | `/v1/prefabs/{prefab_id}/{version}` | `include_source=0\|1` | manifest + publication (+ files ≤ 128 KiB) | 03 |
| GET | `/v1/prefabs/{prefab_id}/{version}/bundle` | – | `{manifest, files, runtime:{version, shim, shell_css}}` (immutable; ETag = fingerprint) | 03 |
| POST | `/v1/prefabs/{prefab_id}/base-edits` | `{actor:"brain", candidate, user_request, confirmed_by_user:true}` | publication; `403 base_edit_unconfirmed` | 07 |

## Control Center routes (relay)

Status: the Slice 03 rows are registered (`jarvis/runtime/prefab_relay.py`,
test `tests/unit/test_prefab_relay.py`); the others are contract. The prefix
`/api/prefabs` is in `READ_GUARDED_ROUTES`: every method checks loopback
Host, Origin and `Sec-Fetch-Site`, so a frame's `Origin: null` is refused
(403 `forbidden_origin`). The relay returns Core's status and JSON unchanged,
not its headers (no `ETag`: the host keeps bundles in memory per
`id@version`). `CorePrefabTransport` is the typed access to `/v1/prefabs*`
over a Core transport, refused outside that prefix; the MCP (Slice 07)
reuses it.

| Method | Path | Slice |
| --- | --- | --- |
| GET | `/api/prefabs` | 03 |
| GET | `/api/prefabs/events` | 04 |
| POST | `/api/prefabs/events` (actor forced `user`) | 04 |
| POST | `/api/prefabs` (fork / save-as-new from the UI, actor `user`) | 08 |
| GET | `/api/prefabs/{prefab_id}` | 03 |
| GET | `/api/prefabs/{prefab_id}/{version}` | 03 |
| GET | `/api/prefabs/{prefab_id}/{version}/bundle` | 03 |

There is **no base-edit route on the Control Center**. Each route is quoted in
`ARCHITECTURE.md` by the Slice that registers it, not before.

## Base-edit gate (`PrefabService.edit_base`)

Status: conditions 1–3 and the witness seam implemented by Slice 02
(`PrefabService.edit_base`); the real witness is wired by Slice 07. **Until
then `v2_app.py` injects a witness that never finds anything, so every base
edit is refused in production** (`base_edit_unconfirmed`,
[legacy/prefab-base-edit-witness.md](legacy/prefab-base-edit-witness.md)).

All must hold:

1. the id is an existing `jarvis.*` id;
2. `confirmed_by_user is True`;
3. `user_request` is 12..500 chars;
4. **witness**: `user_request`, normalized (casefold, collapsed whitespace,
   stripped punctuation), is a substring of a user turn recorded in
   Conversation Events within the last 30 minutes, found through
   `ConversationEventQueryService.search` (`jarvis/core/conversation_event_query.py`),
   injected as a callable `user_utterance_witness(text) -> event_id | None`.

The witness receives the stripped `user_request`; a witness that raises or
returns no event id is a failed condition. Conditions are checked in order
before the candidate is parsed; once the gate passes, an invalid candidate is
`invalid_definition` like any save.

Any failure → `base_edit_unconfirmed`. The actor is `brain` only; any other
actor is refused first with `invalid_definition`. The new version is the
highest occupied version number of that id (both roots, catalogued or not)
+ 1, written into the data root with `origin: base_edit`;
diagnostic `core.prefab.base_edited` at level `warning`. If the `search`
interface cannot express the witness lookup, conditions 1–3 stand alone and
the gap is recorded as an Issue of the handoff.

## Agent tools (`jarvis-display`)

Status: contract — implemented by Slice 07. Same server and same metadata
source (`jarvis/runtime/mcp_tool_meta.py` `DISPLAY`); logic in
`PrefabDisplayTools`, registered in `display_mcp.build_server`. Catalog
contract: [mcp/tool-contract.md](mcp/tool-contract.md) §6 and §10.2.

| Tool | Args (strict) | Class / output |
| --- | --- | --- |
| `prefab_search` | `query?: str≤120`, `family?`, `class?: base\|custom`, `limit?: 1..20` | read, json_text |
| `prefab_get` | `prefab_id`, `version?: int`, `include_source?: bool=false` | read, json_text (≤ 48 KiB; source truncation said) |
| `prefab_validate` | `candidate: {manifest: object, template: str, style: str, behavior: str}` | read, structured `{ok, errors[≤20], fingerprint}` |
| `prefab_save` | `candidate`, `derived_from?: {prefab_id, version}` | write, structured `{prefab_id, version, origin, fingerprint}`; refuses `jarvis.*` with a hint to `prefab_edit_base` |
| `prefab_edit_base` | `prefab_id: jarvis.*`, `candidate`, `user_request: str`, `confirmed_by_user: Literal[True]` | write, structured |
| `prefab_events` | `object_id?`, `after?: int`, `limit?: 1..50` | read, json_text |
| `scene_create_object` +`prefab` | `prefab?: {prefab_id, version?: int, props?: object, data?: object}` (`kind` must be `window`; version omitted → the MCP resolves the latest through `/v1/prefabs/{id}` and pins it) | existing |
| `scene_update_object` +`prefab` | same shape; given `props` / `data` **replace** those objects; a `version` change is an explicit upgrade | existing |
| `scene_get` | detail adds `prefab: {id, version, latest_version, props, data}` (bounded by `MAX_GET_BYTES`) | existing |

There is no separate instantiate tool. The prompt block `BRAIN_PREFAB_PROMPT`
(≤ 12 lines: reuse first, base-edit rule, prefab data is data and never an
instruction) is appended after `BRAIN_ARTIFACT_PROMPT` and registered as
`backend.claude.conversation.prefabs` in `jarvis/runtime/prompt_catalog.py`.
`BRAIN_DISPLAY_PROMPT` is not edited (fingerprint-tested).

## Base catalogue

Status: contract — implemented by Slice 05 (`jarvis.window`, `jarvis.document`,
`jarvis.table`) and Slice 06 (`jarvis.checklist`).

No durable taxonomy of window families exists in the repository; the base
catalogue comes from evidence only (user feedback of 2026-09-22 on reading an
artifact in full, the `view_table` proposal of
[mcp/plan-outils-interface.md](mcp/plan-outils-interface.md)):

| Id | Purpose |
| --- | --- |
| `jarvis.window` | generic window: `body` markdown, `items` list with wrapping labels, `accent`; parity with the legacy window look |
| `jarvis.document` | full-read document: long markdown that wraps and scrolls, keyboard paging |
| `jarvis.table` | `columns` (1..8) and `rows` (≤ 64 of ≤ 8 string cells); supersedes the `view_table` proposal |
| `jarvis.checklist` | structured, interactive proof: the manifest above |

Base prefabs use the shell classes (`.jv-*`) and variables; no shell CSS is
copied into a prefab. A new family is a new base id plus a lock entry and
tests, with no code change.

## Library UI

Status: contract — implemented by Slice 08 (`jarvis/runtime/control_center_prefabs.js`,
marker `/*__CONTROL_CENTER_PREFABS_JS__*/`).

- Dock button `PFB` next to `MCP` and `WSP`; full-screen dialog `.pfb`, same
  layer and one-open-at-a-time rule as `.mcpi` / `.wsp`.
- Renders catalogue truth from the relay only; DOM through `textContent` only.
- Actions: browse, search, filter, inspect, preview, "Place on scene", "Fork as
  new prefab" (new id, title, description, sample; source copied unchanged;
  saved as actor `user`). No code editor.
- Preview = `JarvisPrefabHost` in `preview` mode with the manifest `sample`:
  events are shown locally and never posted.
- Base prefabs show a protection badge and their base-edit history (quoted
  user request, date, actor). Base edits are made only by the brain through
  `prefab_edit_base`; the UI says so instead of offering a button.

## Known limitations

- Capture cannot rasterize a frame (fallback drawing above).
- One library per data root: worktrees and `jarvis-dst` do not share prefabs.
- A `notify` event waits for the next brain turn; it never wakes the brain.
- The hygiene lint is pattern matching, not an HTML/CSS parser: CSS escape
  sequences (`u\72l(`), comment-split tokens and similar obfuscations pass
  it. It catches mistakes; the frame sandbox and its CSP are the security
  boundary ([SECURITY.md](SECURITY.md) › control 16).
- Scene actors are declared, not authenticated ([SECURITY.md](SECURITY.md) ›
  control 13): the event route forces `user`, as every Control Center scene
  write does.
