# Presentation Studio - concepts, owner map and status

Entry page for the Presentation Studio (handoff `jarvis-interactive-presentation-studio`): a structured, editable, rehearsable and presentable **Presentation** that Jarvis can author and
deliver. It **holds no behaviour contract yet**: it names the canonical concepts, says who will own each, and tracks status per section. When a section gets its own contract page or code,
that owner wins and this row is updated in the same commit.

Status: **Level 2 skeleton** for the page as a whole; the *Presentation contract* section below is **Level 3** (Slice 02: domain, port, file store, Core service, Core routes, typed client, conformance tests) and so is the *Scene and control contract* (Slice 04: logical scene, curated controls, discovery, prefab compatibility) and the *Semantic edit contract* (Slice 05: one edit API for voice and GUI).
Every other row is `planned` unless it says otherwise. Written by Slice 01 (contract audit) from `docs/07-integration-map.md` of the handoff (`tasks/jarvis-interactive-presentation-studio/docs/`); Slice 02 added the contract.

## Not to be confused with

| Existing thing | Where | Relation |
| --- | --- | --- |
| PRESENTATION **interaction mode** (ambient lane, explicit address, silence by default) | [presentation-mode.md](presentation-mode.md) and its owner pages | The Studio **consumes** it; it never loosens its authority rules (ambient speech has no authority, explicit address wins) |
| **Artifact** (capture evidence, `jart_` ids) | [artifacts.md](artifacts.md) | A Presentation is not an Artifact; no `Artifact*` name is reused |
| **Prefab** (sandboxed HTML/CSS/JS window definition) | [prefabs.md](prefabs.md) | Each Studio scene is rendered by a prefab instance; the Studio adds no renderer and no catalog |
| **Scene** (the single global constellation scene) | [scene-model.md](scene-model.md) | A Studio *logical scene* is not a scene-service object; only the displayed one is a `window` |

## Canonical concepts (Level 1 terms; contracts are Level 2/3 as the Slices land)

| Concept | Meaning | Owner (planned) | Contract | Status |
| --- | --- | --- | --- | --- |
| Presentation | durable aggregate: variants, resource refs, active variant | `jarvis/domain/presentation_studio.py`, `core/presentation_studio_service.py`, store `adapters/file_presentation_studio_store.py` | [Presentation contract](#presentation-contract-level-3) below, Slice 02 | **implemented (Level 3)** |
| Presentation Variant | creative branch of a whole presentation; immutable id, monotonic display number, title, provenance | `jarvis/domain/presentation_studio_variants.py` | Slice 16 | planned |
| Studio scene + control | logical scene pinned to a prefab `(id, version)`; curated typed controls bound to manifest inputs; score anchors; preview metadata; introspection | `jarvis/domain/presentation_studio_scene.py`, `core/presentation_studio_scene_catalog.py` | [Scene and control contract](#scene-and-control-contract-level-3) below, Slice 04 | **implemented (Level 3)** |
| Scene-local variant | lightweight alternative of one scene inside a variant | `presentation_studio_variants.py` | Slice 17 | planned |
| Semantic edit (3 tiers) | control patch / structural patch / source edit; one layer for voice and GUI; preview vs commit | `jarvis/domain/presentation_studio_edit.py`, `core/presentation_studio_edit.py`, `core/presentation_studio_events.py`, `runtime/presentation_studio_relay.py` | [Semantic edit contract](#semantic-edit-contract-level-3) below, Slice 05 | **implemented (Level 3)** |
| Scene hot reload | scene-local rebuild with state preservation and rollback | `core/presentation_studio_reload.py` | Slice 06 | planned |
| Autosave + undo | atomic continuous save of the active variant; bounded in-memory undo/redo | `core/presentation_studio_autosave.py` | Slice 08 | planned |
| Art direction | structured profile with provenance (provided / inferred / generated) | `jarvis/domain/presentation_studio_art_direction.py` | Slice 09 | planned |
| Score, cues, timing | multi-track script, explicit silence, armable cues, soft/locked timing | `jarvis/domain/presentation_studio_score.py` | Slice 10 | planned |
| Playback runtime | roles (user presenter / Jarvis presenter / rehearsal), position, detours, "where are we" | `jarvis/domain/presentation_studio_playback.py`, `core/presentation_studio_playback.py` | Slice 12 | planned |
| Armed cue following | ambient speech may only satisfy a pre-armed cue id, bound to a pre-authorized reversible action | `jarvis/domain/presentation_studio_cues.py`, `runtime/presentation_studio_cue_follower.py` | Slice 13 + amendment of [presentation-addressed-turn.md](presentation-addressed-turn.md) section 12 | planned |
| Jarvis presenter, locked sequences | scripted speech and deterministic AV sequences through the existing speech path | `core/presentation_studio_presenter.py` | Slice 14 (needs the speech-authority decision) | planned |
| Rehearsal | practice, pause-edit-resume, no durable transcript | playback runtime | Slice 15 | planned |
| Variant compare / mix | side-by-side, synchronized navigation, selective composition into a new child | `jarvis/domain/presentation_studio_compose.py` | Slice 19 | planned |
| Template / promotion | whole-variant, scene, DA or motion promoted to the shared library | `presentation_studio_template.py` | Slice 20 | planned |
| Generic fullscreen surface | real browser fullscreen of a host element; armed request + user gesture; explicit `needs_gesture` / `unsupported` | `jarvis/domain/surface_fullscreen.py`, `runtime/control_center_fullscreen.js` | Slice 03 | planned |
| Agent / voice operations | one MCP server `jarvis-presentation`, `presentation_*` tools, ids from choice providers | `jarvis/runtime/presentation_studio_mcp.py` | Slice 21, [mcp/tool-contract.md](mcp/tool-contract.md) | planned |

Exact names (ids, routes, events, tools): `tasks/jarvis-interactive-presentation-studio/docs/09-canonical-names.md`; the Presentation ids, routes, error codes and storage tree are now stated in the contract section below (Slice 02).

## Presentation contract (Level 3)

Status: implemented by Slice 02. Conformance: `tests/unit/test_presentation_studio_{domain,store,crash,service,routes,docs}.py`,
fixtures `tests/fixtures/presentation_studio/`. A Presentation can be created, saved, loaded, listed and validated **independently of
playback and of any UI**; nothing here imports the scene service, the prefab service, a renderer or the Control Center.

### What it holds, and what it never holds

| Document | Holds (references, never copies) |
| --- | --- |
| `Presentation` (`presentation.json`) | `presentation_id` `pst_<32 hex>`, `title` (<= 80, one printable line), `active_variant_id`, `variant_counter` (last number handed out, monotone, never reused), the variant index `[{variant_id, variant_number}]` (1..64), `resources` (<= 64, `{kind, locator, title}`), `revision`, `created_at`, `updated_at` |
| `PresentationVariant` (`variants/<variant_id>.json`) | `variant_id` `psv_<32 hex>`, `variant_number`, `title`, `parent_variant_id` (the only graph trace, cycles refused; graph operations are Slice 16), ordered `scenes` (<= 64) of `{scene_id: pss_<12 hex>, prefab: {id, version}}`, `art_direction_id` (`psd_<12 hex>` or null, content is Slice 09), `score_id` (`psr_<12 hex>` or null, content is Slice 10), `revision`, timestamps |

- A scene is the logical scene id and the **exact** prefab pin `(id, version)` (`PrefabRef`, `jarvis/domain/prefab.py`) plus, since Slice 04, its instance values and curated controls (see *Scene and control contract*).
  No manifest, template, style, behavior, html, css or js field exists in the schema; the unknown-key refusal makes copying prefab definition fields impossible, not merely discouraged.
- A resource is the existing `ResourceReference` (`jarvis/domain/presentation_working_set.py`: allowed-scheme locators, no markup, <= 300 chars) stored as `{kind, locator, title}`.
  Before any resolver exists (Slices 11, 12) the Studio adds a locator hygiene gate (`_check_locator_hygiene`), applied to the raw text **and** to the text percent-decoded to a fixpoint
  (at most 5 passes; a locator that keeps decoding is refused, so double encodings such as `scene%253A...` or `%252e%252e` cannot hide): only printable characters (no control, NUL, zero-width or bidi character, no
  no-break space), no surrounding space, no backslash, no `..` path segment, no `//host/share` and no `file://` locator, an ASCII scheme, and, after NFKC folding, nothing that reads as `scene:` (fullwidth colon,
  compatibility letters; those are runtime handles). An ordinary `%20` or `%C3%A9` in a URL passes. Native Windows backslash paths and a bare `#..` fragment are refused on purpose (policy: use `/`). A resolver must still
  decode exactly once and re-validate; this gate does not make a locator safe to open.
  The `descriptor` payload is **not** stored (references, never payloads). Kind `scene_object` and `scene:` locators are refused: a scene object id is a runtime handle.
- **Runtime-only state is never persisted.** Scene-service object ids, window or DOM or frame handles, playback state and score position, reveal progress, detours, the auxiliary resource stack and the undo/redo
  stack have no field. Every document and request body is an exact object: an unknown key is refused, and a key that names runtime state (`jarvis/domain/presentation_studio.py` `RUNTIME_KEYS`) is refused with its own code
  `presentation_studio_runtime_state_refused`, so the mistake is visible instead of generic. Later Slices keep that state in memory (playback, Slice 12; undo ring, Slice 08).
- Identity (`presentation_id`, `variant_id`, `variant_number`, `parent_variant_id`, `created_at`) is immutable: a save body has no such field.

### Versioning and compatibility

Every document carries `{"schema": "jarvis.presentation_studio.presentation" | "jarvis.presentation_studio.variant", "schema_version": n}`; `n` is 1 for the Presentation and 2 for the variant (Slice 04 added scene fields: see *Scene and control contract*, Versioning).

- A document with a **newer** `schema_version` than this JARVIS reads is refused (`presentation_studio_unsupported_schema_version`, HTTP 409), never read best-effort. The file is left untouched: a save reads the stored
  document first, so a newer file is never overwritten by an older JARVIS. The listing names it in `problems`.
- An **older** version goes through `UPGRADES[schema][n]` (`n -> n+1`, one step per version, empty for the Presentation, one step 1 -> 2 for the variant; `upgrade_document`). A missing step is `corrupt_document`, never a guess.
- Adding a field is a version bump with an upgrade step; the unknown-key refusal is why. There is no `_MIGRATIONS` entry: this is a file store, not part of `jarvis.sqlite3` (see *Storage*).

### Revisions

`revision` starts at 1 and grows by one per save of that document. `PUT` bodies carry `expected_revision`; a mismatch is `presentation_studio_stale_revision` (409, "reload, then retry"), nothing is written. The Presentation revision counts only its own
changes (title, resources, active variant); a variant save touches only its variant file. This is the seam for the semantic edit API (Slice 05, `apply_if`-style basis) and autosave (Slice 08).

### Core service and routes

`PresentationStudioService` (`jarvis/core/presentation_studio_service.py`) is the sole authority: `create`, `get`, `get_variant`, `list_presentations`, `save_presentation`, `save_variant`, `validate`, `describe_scene` (Slice 04). Core is the single writer; writes and reads take the same lock (a read never meets an atomic replace in flight; the store also re-inspects up to 4 times if a save from elsewhere lands between its inspection and open);
reads hit the disk every time (the file is the truth, also after a restart). Routes: `jarvis/protocol/presentation_studio_routes.py`, typed client: `LocalCoreClient.presentation_studio_*` (`jarvis/protocol/client.py`). The Control Center relay (Slice 05, `jarvis/runtime/presentation_studio_relay.py`) exposes the reads and the edit API only, with the actor forced to
`user` (see *Semantic edit contract*); `STUDIO_PREFIX` is in `FORWARDABLE_PREFIXES`, but the relay builds the paths itself.

| Method | Core route | Body -> answer |
| --- | --- | --- |
| GET | `/v1/presentation-studio/presentations[?limit]` | `{presentations: [{presentation_id, title, active_variant_id, variant_count, resource_count, revision, updated_at}], problems: [{presentation_id, code, message}]}` |
| POST | `/v1/presentation-studio/presentations` | `{title}` -> 201 `{presentation, variants}` (variant #1, empty, active) |
| POST | `/v1/presentation-studio/presentations/validate` | `{presentation, variants}` in disk format -> `{ok, errors: [{code, message}]}` (first error only), nothing written |
| GET | `/v1/presentation-studio/presentations/{presentation_id}` | `{presentation, variants}` |
| PUT | `/v1/presentation-studio/presentations/{presentation_id}` | `{expected_revision, title, active_variant_id, resources}` -> the `presentation` document |
| GET | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}` | the `variant` document |
| PUT | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}` | `{expected_revision, title, scenes, art_direction_id, score_id}` -> the `variant` document (new or changed scenes are checked against their pinned prefab) |
| GET | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/controls` | what is editable on a scene (Slice 04, see *Scene and control contract*) |

### Failures: typed, visible, logged

`PresentationStudioErrorCode` (`jarvis/domain/presentation_studio.py`), envelope `{"error": {"code", "message"}}`, message without absolute path:

| Code | HTTP | Meaning |
| --- | ---: | --- |
| `presentation_studio_invalid` | 400 | input refused (shape, bound, id, prefab pin, resource) |
| `presentation_studio_runtime_state_refused` | 400 | a runtime-only key or handle in a persistent document or body |
| `presentation_studio_unknown_presentation`, `presentation_studio_unknown_variant`, `presentation_studio_unknown_scene` | 404 | no such id (a malformed id is "unknown", never a path) |
| `presentation_studio_scene_incompatible` | 400 | a scene's controls or values disagree with its pinned prefab manifest (Slice 04) |
| `presentation_studio_prefab_unavailable` | 409 | the pinned prefab is unknown, tampered or its catalogue does not answer; the prefab service's own code is in the message (Slice 04). An id or version that simply does not exist is logged at `warning`; tampering is `error` |
| `presentation_studio_stale_revision` | 409 | `expected_revision` differs from the stored revision |
| `presentation_studio_unsupported_schema_version` | 409 | stored document newer than this JARVIS; file untouched |
| `presentation_studio_corrupt_document` | 409 | stored document unreadable, oversize, linked, inconsistent, or an indexed variant missing |
| `presentation_studio_already_exists`, `presentation_studio_limit_reached` | 409 | id taken; 256 presentations, 64 variants/scenes/resources, or a 256 KiB document exceeded |
| `presentation_studio_storage_io` | 500 | disk, link/junction refusal, path limit, missing data root: the real cause is in the message |
| `invalid_request`, `core_unavailable`, `internal_error` | 400, 503, 500 | malformed query or body (not JSON, duplicate key, > 256 KiB) / Core not ready / unexpected |

Diagnostics `core.presentation_studio.{started,swept,created,saved,listed,validated,refused,scenes_checked,scene_described}` at `info` (ids, codes, counts; never titles, locators or content), and at `error`
(which puts them in the Error Logs viewer) `failed` (storage, corrupt or newer document), `unreadable` (one presentation unusable while listing: it is named in `problems` and the others still list),
`sweep_failed`, `unexpected` (any non-typed exception at the route boundary, with the real cause).

### Storage (decision (a): file store, recorded by Slice 02)

Decision: a file store under `<data_root>/presentations/` (`jarvis/adapters/file_presentation_studio_store.py`, port `jarvis/ports/presentation_studio.py`), **not** a `jarvis.sqlite3` v9 migration. Reasons:
(1) no schema bump or `tests/schema` snapshot for a store whose unit is one document; (2) per-variant isolation (D15/D16) is one file per variant, so autosave of the active variant (Slice 08) rewrites one file, not a shared database;
(3) atomic replace, staged publication, folder defences and the startup sweep are existing, tested precedents (`FilePrefabLibrary`, `file_replace`, `safe_folders`); (4) the presentation is a document the user may back up or move,
which a row in a shared SQLite state cannot be; (5) Core is the single writer, so there is no concurrency that SQLite would resolve better. No hard reason for (b) was found. The cost accepted: no multi-file transaction (below).
Versioning is therefore per file (`schema_version` + `UPGRADES`), not `_MIGRATIONS`.

```
<data_root>/presentations/<presentation_id>/presentation.json
<data_root>/presentations/<presentation_id>/variants/<variant_id>.json
<data_root>/presentations/.staging-<16 hex>/          # a creation in progress; swept at start
```

- **Atomic file writes**: unique temporary beside the target, `fsync`, `replace_with_retry` (`os.replace`, bounded retry on a Windows lock). A crash leaves the old text whole or the new text whole; a leftover `*.<8 hex>.tmp` is swept at the next start and never blocks a save.
- **Atomic creation**: the whole folder is built in `.staging-*` (variants first, manifest last), then renamed; `os.rename` fails if the target exists. There is never a presentation folder without its manifest.
- **Multi-file operations** write variants first and `presentation.json` last; today no operation touches both. Reads reconcile (`check_consistency`): an indexed variant that is missing is `corrupt_document`, not silently dropped.
- **Defences** (`safe_folders`): absolute root, no link/junction/reparse point, Windows path limit, ids validated as exact-shape path components, files read by `lstat` + `fstat` (same inode, regular, <= 256 KiB, UTF-8), bounded retry when Windows refuses an open for a few milliseconds.
- **Never deletes a document**: `sweep` removes only `.staging-*` and our `*.tmp`. Archiving a variant (Slice 16) moves, never removes.
- Proof: `tests/unit/test_presentation_studio_crash.py` kills a real writer subprocess at varied instants (mutation-checked: an in-place write fails it) and a creator, and kills at the worst deterministic point (complete temporary, replace not done).

### Seams left for later Slices (not built here)

| Seam | Owner |
| --- | --- |
| scene controls, values, prefab mapping to the stage window | **done, Slice 04** (variant v2, `StudioScene`; `SceneRef` is now an alias of it) |
| semantic edits, `expected_revision` as the edit basis, actor, relay | **done, Slice 05** (*Semantic edit contract*) |
| debounced autosave, undo/redo ring (memory only) | Slice 08 |
| art direction and score content behind `art_direction_id` / `score_id` | Slices 09, 10 |
| variant create/switch/archive, `variant_counter` increments, `archive/<variant_id>.json` | Slice 16 |

## Scene and control contract (Level 3)

Status: implemented by Slice 04. Conformance: `tests/unit/test_presentation_studio_{scene,scene_service,routes,docs}.py`
(the Presentation contract above still holds; this section is what a **scene** adds to a variant).
Owner modules: `jarvis/domain/presentation_studio_scene.py` (pure model and validation),
`jarvis/domain/presentation_studio_checks.py` (shared error codes and input checks, extracted so the document and the scene
modules do not import each other), `jarvis/core/presentation_studio_scene_catalog.py` (the only place that talks to
`PrefabService`), port `PrefabCatalog` in `jarvis/ports/presentation_studio.py`.

### What a scene is

A **logical scene** (`StudioScene`, `scene_id` `pss_<12 hex>`) is an entry of a variant, *not* a scene-service object and not a
`window`. It names the shared prefab that renders it and carries the values and the editing surface:

| Field | Meaning |
| --- | --- |
| `prefab` | the **exact** pin `{id, version}` (never "latest"); the version is immutable, so a scene validated once stays valid |
| `title` (<= 80, may be empty), `section` (<= 40, may be empty) | logical identity for the inspector and the score; **order** is the position in `variant.scenes` |
| `props`, `data` | the values of the instance block (`ScenePrefabRef`): pure JSON, depth <= 8, keys <= 64. Values only; the prefab definition (manifest, template, style, behavior) is never copied here |
| `controls` (<= 32) | the curated editable surface, below |
| `anchors` (<= 16) | score anchors, below |
| `preview` | `{caption (<= 120), alt (<= 200)}` thumbnail metadata; an image reference is a later Slice's |

**Stage window mapping (R2, integration map 4.5).** Only the scene being shown is a global-scene object: one stable `window`
per Presentation, patched with `StudioScene.payload()` (`ScenePayload(title, prefab=ScenePrefabRef(id, version, props, data))`)
through `update_object(prefab=...)`; a version change is the remount, a `props`/`data` change is `host.update`. That window's
object id is a runtime handle owned by the playback service (Slice 12); it has no field in any document, and a scene body
that names `object_id`, `window_id`, `stage_object_id`... is refused with `presentation_studio_runtime_state_refused`.

### Controls: curated, bound to the manifest, never a style dump

A `StudioControl` is `{control_id, path, label, group, meaning, default?, bounds?}`:

| Field | Rule |
| --- | --- |
| `control_id` | the **stable semantic id**: `[a-z][a-z0-9_]{0,39}`, authored, unique in the scene. Agents and the inspector address a control by it, never by position or path; the same scene always answers the same ids in the same (authored) order |
| `path` | `props.<name>[.<name>...]` or `data...`, object properties only (depth <= 4, no index, no selector), unique in the scene, and **declared by the pinned manifest's `inputs`**. An object node is refused (bind one of its properties); an array is allowed as a `list` control |
| `label` (<= 40), `meaning` (<= 160) | one printable line each; `meaning` says what the setting is for, in the author's words |
| `group` | closed: `content`, `visual`, `layout`, `motion` |
| `default` | optional curated default (`null`: the manifest's); must satisfy the manifest schema and the curated bounds |
| `bounds` | optional, **narrower than the manifest, never wider**: `min`/`max` (number, integer), `max_length` (string, text), `choices` (a subset of an enum), `max_items` (array); any other key for a type is refused (booleans, colours, URLs take none) |

Unknown keys are refused at every level (`bounds`, `control`, `scene`), so there is no place to put a CSS property, a selector or a
script: a control can only exist for an input the prefab author declared. The widget is **derived**, never stored
(`widget_for`): string `text_line`, text `text_area`, number or integer `slider` when both ends are bounded (by the manifest or
by the curation) otherwise `number`, boolean `toggle`, colour `color`, enum `choice`, URL `url`, array `list`.
`effective_bounds` is the intersection of manifest and curation and is what the inspector and the agent must respect.
`suggest_controls(manifest)` is a deterministic starting point (one control per scalar leaf, at most 32, id from the property
name, `<root>_<name>` on a collision) for the author or Slice 19 to curate; it is not persisted by itself.

### Score anchors and preview

A `ScoreAnchor` is `{anchor_id, label, control_id?}`: a named hook the score (Slice 10) may bind a cue or a timing to. It carries
no tool, command or free text, and its `control_id` must be declared in the same scene, so the set of things a cue can name on a
scene is closed and pre-authored (R5). Slice 10 owns what a cue *does* with an anchor.

### Payload accounting

A scene is refused at construction when its displayable payload would exceed the global scene cap
(`jarvis.domain.scene.MAX_PAYLOAD_BYTES` = 16 384 bytes of compact UTF-8 JSON of `{title, summary, items, prefab}`), counted by
the same code path the scene service uses (`ScenePayload`). `StudioScene.budget()` answers `{bytes, limit, remaining}`; the
introspection answer carries it. The variant document stays <= 256 KiB (`limit_reached`), so a variant of many large scenes can
reach that cap before 64 scenes.

### Validation: where the prefab authority stays

`PrefabService` is the authority on prefabs; the Studio does not copy its checks.

1. **Shape** (domain, pure): ids, bounds, uniqueness, anchors point at declared controls, payload cap.
2. **Pin and compatibility** (`SceneCatalog`, on `save_variant` for every scene that is **new or changed**, judged by its stored form (canonical JSON), not by Python `==`, so `true` or `1.0` over `1` is a change; a scene whose stored form is identical is not
   rechecked, so renaming a variant never depends on the catalogue): `PrefabService.manifest(id, version)` must resolve
   (`presentation_studio_prefab_unavailable`, 409, with the prefab service's own code in the message: `unknown_prefab`,
   `unknown_version`, `tampered`...; a disk failure of the catalogue is `presentation_studio_storage_io`); every control path must
   exist in the manifest schema, curated bounds and defaults must fit it, stored values must satisfy the manifest *and* the curated
   bounds (`presentation_studio_scene_incompatible`, 400); then `PrefabService.validate_instance` judges `props`/`data`
   (incompatible: the same code, with its detail, for example a missing required data key).
3. A refused save writes nothing. A service built without a catalogue (store-only tests) checks the shape only; Core always wires it.

### Introspection: "what is editable on this scene?"

`GET /v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/controls`
(`PresentationStudioService.describe_scene`, client `LocalCoreClient.presentation_studio_scene_controls`) answers:

```
{presentation_id, variant_id, variant_revision, scene_id, order, title, section,
 prefab: {id, version}, preview: {caption, alt},
 controls: [{control_id, label, group, meaning, path, type, widget, required, bounds, default, current, is_set}],
 anchors: [{anchor_id, label, control_id}], payload: {bytes, limit, remaining},
 stage: {mode: "patch_stable_window", prefab_key}, problems: [string]}
```

`current` is the stored value, else `default` (curated, else the manifest's); `is_set` tells which. `problems` lists what is wrong with
the instance values (for example a required data key still absent) while the controls are still listed so the scene can be fixed;
controls that do not fit the manifest are not described at all (`scene_incompatible`). Unknown ids are `presentation_studio_unknown_scene`
(404, a malformed scene id is "unknown", never a path), `unknown_variant`, `unknown_presentation`. Nothing in the answer changes between calls
unless the scene or its stored values change.

### Versioning

The variant document is now `schema_version` **2**; the Presentation document stays 1 (`CURRENT_VERSIONS`). `UPGRADES[variant][1]`
fills the Slice 04 fields of each v1 scene with their defaults (`title ""`, `section ""`, `props {}`, `data {}`, no controls, no
anchors, empty preview): nothing a v1 file said is reinterpreted, a v1 file is read through the step and rewritten as v2 by the
next save (reading never rewrites), and a JARVIS that only knows v1 refuses a v2 file untouched (`unsupported_schema_version`). A scene body
may still be the bare `{scene_id, prefab}` pin.

### Extension points

| To add | Where | Rule |
| --- | --- | --- |
| a control for a new prefab | the scene's `controls` (data), never code | the path must be a manifest input; a prefab that needs a new kind of input extends the prefab input schema first (`docs/prefabs.md`), the widget follows |
| a widget for a new input type | `widget_for`, `effective_bounds`, `bounds_problem`, `value_problem` together | one table per concern, same test row |
| a control group | `ControlGroup` | closed on purpose; a new family needs a docs row and an inspector decision (Slice 07) |
| a score action | `ScoreAnchor` (Slice 10 reads, never invents one) | closed set per scene, bound to a declared control or a plain marker |
| an edit (Slice 05) | an operation in `presentation_studio_edit.py` | see *Semantic edit contract*, Extension points |

Not here: rendering and hot reload (Slice 06), the inspector UI (Slice 07), what a cue does
with an anchor (Slice 10), the stage window lifecycle (Slice 12).

## Semantic edit contract (Level 3)

Status: implemented by Slice 05. Conformance: `tests/unit/test_presentation_studio_{edit,edit_service,edit_routes,edit_docs}.py`.
Owner modules: `jarvis/domain/presentation_studio_edit.py` (pure: vocabulary, tiers, request parsing, transaction engine, undo record, result),
`jarvis/core/presentation_studio_edit.py` (`PresentationStudioEditService`: reads, validates, writes, records), `jarvis/core/presentation_studio_events.py`
(`StudioEditEvents`), `jarvis/runtime/presentation_studio_relay.py` (Control Center relay). The service reuses `PresentationStudioService`
(`check_scenes`, `write_variant`) and `SceneCatalog`: it validates nothing a second time.

**One door.** The voice/agent (actor `brain`, MCP tools in Slice 21) and the GUI (actor `user`, Control Center relay) call the same service with the same
validation and reach the same canonical state; the actor only labels who asked. Direct DOM edits in the frame never reach durable state: the only way to change a
Presentation by hand is this API (the relay exposes no `PUT`).

### Vocabulary (stable ids only: `presentation_id`, `variant_id`, `scene_id`, `control_id`)

| `op` | Fields | Tier | Inverse (the undo form) |
| --- | --- | --- | --- |
| `control.set` | `scene_id`, `control_id`, `value`, optional `if_current` | `control` (`structure` when the control binds a list) | `scene.restore_values` |
| `control.reset` | `scene_id`, `control_id`, optional `if_current`; writes the curated default, else unsets the key (the prefab then supplies its manifest default) | `control` / `structure` | `scene.restore_values` |
| `scene.restore_values` | `scene_id`, `props`, `data`: the whole instance values; may change **only paths a declared control covers** (see below) | `control` (`structure` when a restored path is under a list control) | `scene.restore_values` |
| `scene.add` | `scene` (a scene body; `scene_id` optional, generated), optional `index` | `structure` | `scene.remove` |
| `scene.remove` | `scene_id` | `structure` | `scene.add` with the full scene and its index |
| `scene.reorder` | `scene_id`, `to_index` | `structure` | `scene.reorder` to the old index |
| `scene.rename` | `scene_id`, `title` | `structure` | `scene.rename` to the old title |
| `scene.set_controls` | `scene_id`, `controls` (the new curated list; where `suggest_controls` lands) | `structure` | `scene.set_controls` with the old list |
| `scene.source_request` | `scene_id`, `intent` (one printable line <= 400 characters) | `source` | none |

The vocabulary is closed (`OpName`); an unknown `op`, an unknown key and a runtime key (`selection`, `playback`...) are refused. A change the declared controls cannot make is
**not** a free path: it is a `scene.source_request` (the refusal `presentation_studio_unknown_control` says so).

### Tiers (D11)

`classify_op(op, node_type)` derives the tier from the operation and the bound manifest input. A request is as high as its highest operation. Tier 1 changes values
(no remount); tier 2 changes the shape of the variant or of a list; tier 3 is **classified and kept in memory only**: the op changes no state, returns `effect:
"recorded_only"`, a `request_id` and `durable: false`, and the request is held by `pending_source_requests()` (bounded to 64, **lost on restart**) for Slice 06 (hot reload), which
owns durability and turning it into a new prefab revision. When the 64 slots are full the oldest are evicted **visibly**: `source_requests_dropped` in the result and a
`source_requests_dropped` warning in the journal. The intent text never leaves the process (no event, no journal line); the event status is `recorded_in_memory`.

**`scene.restore_values` is not a free path.** It is the form an undo takes, so it is held to the same closed set as `control.set`: every leaf that differs between the
current and the restored values must be a declared control path, lie under one (a list control), or be an empty intermediate object of one. Anything else is
`presentation_studio_unknown_control` (a restore cannot add `data.link` or drop an undeclared `props.accent`). An inverse always passes: it runs in the state right after the
operation it undoes, so it changes only what that operation changed.

### Request, preconditions, result

`POST .../variants/{variant_id}/edits` body `{actor: "user"|"brain", mode: "preview"|"commit", basis: {variant_revision}, ops: [1..16]}`.

- **Basis (required).** `basis.variant_revision` must equal the stored revision, else the result is `stale` and nothing is written (a write without a basis would be blind).
  `if_current` on a control op is a second precondition: the value the inspector shows (the stored value, else the default) must equal it (compared by canonical JSON,
  never `==`: `1`, `1.0` and `true` differ), else `stale`.
- **Result** `{status, mode, actor, presentation_id, variant_id, basis, revision, committed, changed, tier, ops: [per-operation outcome], undo, source_requests}`; a result that
  is not `applied` adds `code`, `message`, `failed_index` and `error: {code, message}`.

| `status` | HTTP | Meaning |
| --- | ---: | --- |
| `applied` | 200 | validated; in `commit` it is written (`committed: true`), in `preview` nothing is |
| `stale` | 409 | the basis or an `if_current` no longer holds (or another writer landed during validation): read again, then retry; nothing written |
| `refused` | 400 / 404 / 409 | an operation or the resulting scene is invalid; `failed_index` names the operation (absent for a scene-level or document-level refusal); nothing written. The HTTP status is that of the `code` (`HTTP_STATUS`): `presentation_studio_limit_reached` and `presentation_studio_prefab_unavailable` are **409, the same as `stale`**, so a client branches on `status`, never on the HTTP code alone |

Errors outside the result (the coded envelope, as everywhere else): malformed request (`presentation_studio_invalid`, `invalid_request` for a body that is not JSON or exceeds 128 KiB),
unknown presentation or variant (404), prefab unavailable (409), storage (500). New codes (Slice 05): `presentation_studio_unknown_control` (404: no such declared control),
`presentation_studio_value_refused` (400: the value fails the manifest schema or the curated bounds). A refused scene add or reset whose resulting values do not fit the
pinned prefab is `presentation_studio_scene_incompatible`.

### Transaction, preview and commit

1. The variant is read from disk (never a cache) and the basis compared. 2. The manifest of each touched pin is read (outside the lock). 3. The operations run **in order on a
copy**: the first refusal cancels the whole batch (all-or-nothing; `refused`, `failed_index`). 4. The changed scenes pass `SceneCatalog.check` exactly as in `PUT .../variants/{id}`
(pin exists, values valid for the manifest through `PrefabService.validate_instance`, controls inside the manifest). 5. `commit` only: `write_variant` compares the revision again **under
the service lock** and replaces the file atomically; two edits on one basis cannot both win (`stale` for the loser: no lost update). The prefab authority is awaited **outside** the lock
(`save_variant` too since this Slice: a slow catalogue stalls that save, never every Studio read and write).

`preview` computes and validates everything and writes **nothing**: no file, no revision, no event, no source request, no undo record. It also reports the refusal a commit would hit
at the document size limit (`presentation_studio_limit_reached`, 256 KiB): the candidate document is built before the preview/commit split. A no-op commit (every value already equal)
writes nothing and keeps the revision.

### Undo record (record only: the ring and autosave are Slice 08)

A committed edit that changed state returns `undo: {available, presentation_id, variant_id, restores_revision, applies_at_revision, ops, bytes}`: the inverse operations, in the order to
apply them, and the basis they apply against. Replaying `ops` through this API (`commit`, `basis.variant_revision = applies_at_revision`) restores the scenes **canonically** (the stored JSON compares equal, key order of the edited scene's values included; the file's whitespace and revision differ because an undo is a new revision);
replaying it on a moved state is `stale`, never forced. A `scene.add` without a `scene_id` gets a new id on each request, so a preview and its commit
differ in that id: give the id explicitly (the preview result returns it) when the two must match. An undo of a structure edit reports tier `structure`. Bounded to 64 KiB (`{available: false, reason: "too_large"}` beyond). The revision itself is
never rewound: an undo is a new revision.

### Actors

`StudioActor` = `user` | `brain` (not `SceneActor`). `ALLOWED_EDIT_OPS` maps each actor to its operations (both hold the whole vocabulary today: everything is undoable; Slice 21 can tighten a row,
for instance a confirmation for a voice-requested `scene.remove`). The Core route takes `actor` from the body (it is bearer-token authenticated, like `POST /v1/prefabs/events`); the
**Control Center relay replaces it with `user`** whatever the page says, and the MCP server (Slice 21) will stamp `brain`.

### Safe keys

Prefab property names pass the manifest grammar, `__proto__`, `constructor` and `prototype` included. Values travel to a JavaScript frame, so those three names are refused as a control
path segment (`control.set`, `scene.add`, `scene.set_controls`; `suggest_controls` skips them) and as a key anywhere in a written value (depth and size bounded, iterative). Paths are walked only
through the declared `StudioControl.keys`, never built from free text, and a non-object intermediate is a refusal, never overwritten. The page-side patching of a live frame (Slices 06, 12) must keep own-property-safe assignment.

### Suggested controls

`GET .../variants/{variant_id}/scenes/{scene_id}/control-suggestions` (`PresentationStudioEditService.suggest_controls`) proposes the scalar manifest inputs the scene does not declare yet
(ids made unique, at most 32 controls in total) and returns `apply`: a ready `scene.set_controls` operation. Proposing writes nothing.

### Routes

| Method | Core route | Control Center relay |
| --- | --- | --- |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/edits` | `POST /api/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/edits`, actor forced to `user` |
| GET | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/control-suggestions` | `GET /api/presentation-studio/presentations/...` same tail |

The relay also forwards the reads of the Presentation and Scene contracts (list, get, variant, controls). It forwards no other write (no `PUT`, no create, no raw `validate`).
`/api/presentation-studio` is in `READ_GUARDED_ROUTES` (loopback Host, no cross-site: a prefab frame, `Origin: null`, can neither read nor edit). Typed client: `LocalCoreClient.presentation_studio_edit`
(returns the result for all three outcomes) and `LocalCoreClient.presentation_studio_suggest_controls`.

### Observability

Conversation event `system.presentation_studio.edit_committed` (actor `system`, instant, diagnostic, content forbidden; producer `core.presentation_studio`; registered in Python and in the
`control_center_timeline.js` mirror): attributes `presentation_id`, `variant_id`, `scene_id` (when one scene), `op` (names), `tier`, `source` (the actor), `revision`, `status` (`applied`, or `recorded_in_memory` for a source request).
Never a title, a value or an intent. A storage failure during a commit is `system.failure` with a `code`. No live conversation (`BrainOrchestrator.live_conversation_id()`: the foreground conversation, `None` when none is bound, never the last finished turn): no event, and the
`edit_committed` journal row says `event_recorded: false`. Diagnostics (ids, op
names, tier, actor, counts, codes; never values, intents or titles, and the `refused` rows of the variant service carry the code without the refusal message, which may quote the value) `core.presentation_studio.edit_committed`, `edit_previewed`, `edit_refused`, `edit_stale`, `edit_source_recorded`, `controls_suggested` at `info`, `event_failed` and `source_requests_dropped` at `warning`;
a failure of storage or data is traced at `error` by the variant service (`failed`) and the request returns the coded error.

### Extension points

| To add | Where | Rule |
| --- | --- | --- |
| an operation | an `OpName`, a dataclass with `parse`/`to_dict`, a branch in `_apply_one` that returns its inverse, a row in `ALLOWED_EDIT_OPS` and in the vocabulary table | the inverse is part of the operation; the round-trip and undo tests are parametrized over the vocabulary |
| a tier rule | `classify_op` | one table row in `test_presentation_studio_edit.py` |
| a write to the live stage window | Slice 12, **inside `SceneService.apply_if`** (docs/07 section 4.4: read-modify-write of `prefab.data` races a frame `state` event otherwise) | this Slice writes the canonical variant only |

Not here: the source rebuild / hot reload (Slice 06), the inspector UI (Slice 07), the undo ring and autosave (Slice 08), the MCP server (Slice 21).

## Reused owners (do not rebuild)

| Need | Existing owner | Contract |
| --- | --- | --- |
| Interaction mode, ambient lane, explicit address, speech gate | see the owner map in [presentation-mode.md](presentation-mode.md) | the pages listed there |
| Scene objects, `window` kind, prefab block, `apply_if` | `jarvis/domain/scene.py`, `jarvis/core/scene_service.py` | [scene-model.md](scene-model.md), [prefabs.md](prefabs.md) |
| Prefab definitions, versions, provenance, events, input schemas | `jarvis/core/prefab_service.py`, `jarvis/core/prefab_events.py`, `jarvis/domain/prefab.py` (`InputSchema`, `validate_value`) | [prefabs.md](prefabs.md) (the Studio scene calls `PrefabService.manifest/validate_instance` and derives widgets from `InputSchema`; it validates nothing a second time) |
| Frame host, sandbox, `jv:1` protocol | `jarvis/runtime/control_center_prefab_host.js`, `control_center_prefab_protocol.js` | [prefabs.md](prefabs.md) (Runtime, Message protocol) |
| Brain to page commands with receipt | Bare Hands command channel (`jarvis/domain/barehands_command.py`) | [barehands-contracts.md](barehands-contracts.md) |
| Conversation events (Python + JS mirror) | `jarvis/domain/conversation_events.py`, `jarvis/runtime/control_center_timeline.js` | [conversation-events.md](conversation-events.md) |
| MCP server registration | `jarvis/runtime/mcp_tool_meta.py`, `mcp_catalog.py` | [mcp/tool-contract.md](mcp/tool-contract.md) |
| Resource references | `ResourceReference` in `jarvis/domain/presentation_working_set.py` | [presentation-working-set.md](presentation-working-set.md) |
| Local data root, file-store conventions | `jarvis/data_root.py`, `jarvis/adapters/file_prefab_library.py`, `file_replace.py` | [local-data.md](local-data.md) |
| UI intents / ownership of the screen by the Tool Brain | `jarvis/runtime/tool_brain_*`, `jarvis/domain/ui_intent.py` | [tool-brain-contracts.md](tool-brain-contracts.md) |

## Binding facts established by the Slice 01 audit (details and evidence in the handoff's `07-integration-map.md`)

- There is no desktop host. Fullscreen is the browser Fullscreen API on a **host element**; a prefab frame cannot fullscreen itself (permissions policy) and a voice request alone cannot start it (user activation).
- The prefab library caps versions per id (64) and ids (512) and has no deletion: Tier-3 source editing needs a capacity decision first.
- In PRESENTATION mode a scripted Jarvis line is withheld by the speech gate unless the policy is amended or the presenter runs outside that mode.
- Studio operations are Core services behind their own MCP server; they are **not** Tool Brain UI intents. The `ui_intent_publish` channel is currently broken on `main` (handoff Issue 01).
- Cue following runs in the Voice process, durable state in Core; ambient transcription needs the OpenAI voice stack.

## Documentation levels (target at hand-off close)

| Concept group | Today | Target |
| --- | ---: | ---: |
| PRESENTATION mode, ambient lane, working set | 3 | 3 (unchanged; one narrow amendment, Slice 13) |
| Scene / prefab foundation | 3 | 3 |
| Tool Brain contract | 3 (channel broken on `main`) | 3 |
| Generic fullscreen surface | 0 | 3 |
| Presentation artifact (identity, variants as references, scene refs, DA/score refs, resources, storage) | 1-2 | 3 (**done**, Slice 02) |
| Studio scenes and controls (pin, curated controls, anchors, preview, discovery, payload cap, prefab compatibility) | 0-1 | 3 (**done**, Slice 04) |
| Semantic edit API (vocabulary, tiers, preconditions, transactions, preview/commit, undo record, actors, relay, events) | 0-1 | 3 (**done**, Slice 05) |
| hot reload, autosave, DA, score, playback, cues, rehearsal, variants, compare/mix, promotion, agent operations | 0-1 | 3 each |

There is no `docs/CONTEXT.md` or documentation-level registry in this repository: the level of a concept is stated in its page header (`Status: Level N`), as in [presentation-mode.md](presentation-mode.md).
