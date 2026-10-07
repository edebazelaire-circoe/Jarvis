# Presentation Studio - concepts, owner map and status

Entry page for the Presentation Studio (handoff `jarvis-interactive-presentation-studio`): a structured, editable, rehearsable and presentable **Presentation** that Jarvis can author and
deliver. It **holds no behaviour contract yet**: it names the canonical concepts, says who will own each, and tracks status per section. When a section gets its own contract page or code,
that owner wins and this row is updated in the same commit.

Status: **Level 2 skeleton** for the page as a whole; the *Presentation contract* section below is **Level 3** (Slice 02: domain, port, file store, Core service, Core routes, typed client, conformance tests) and so is the *Scene and control contract* (Slice 04: logical scene, curated controls, discovery, prefab compatibility) and the *Score and cue contract* (Slice 10: tracks, silence, cues, closed actions, locked sequences, score store and routes).
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
| Semantic edit (3 tiers) | control patch / structural patch / source edit; one layer for voice and GUI; preview vs commit | `jarvis/domain/presentation_studio_edit.py`, `core/presentation_studio_edit.py` | Slice 05 | planned |
| Scene hot reload | scene-local rebuild with state preservation and rollback | `core/presentation_studio_reload.py` | Slice 06 | planned |
| Autosave + undo | atomic continuous save of the active variant; bounded in-memory undo/redo | `core/presentation_studio_autosave.py` | Slice 08 | planned |
| Art direction | structured profile with provenance (provided / inferred / generated) | `jarvis/domain/presentation_studio_art_direction.py` | Slice 09 | planned |
| Score, cues, timing | multi-track score, explicit silence, armable finite-set cues, closed reversible actions, soft/locked timing, recovery points | `jarvis/domain/presentation_studio_score.py` (stored by the Slice 02 store and service) | [Score and cue contract](#score-and-cue-contract-level-3) below, Slice 10 | **implemented (Level 3)** |
| Playback runtime | roles (user presenter / Jarvis presenter / rehearsal), position, detours, "where are we" | `jarvis/domain/presentation_studio_playback.py`, `core/presentation_studio_playback.py` | Slice 12 | planned |
| Armed cue following | ambient speech may only satisfy a pre-armed cue id, bound to a pre-authorized reversible action | `jarvis/domain/presentation_studio_cues.py`, `runtime/presentation_studio_cue_follower.py` | Slice 13 + amendment of [presentation-addressed-turn.md](presentation-addressed-turn.md) section 12 | planned |
| Jarvis presenter, locked sequences | scripted speech and deterministic AV sequences through the existing speech path | `core/presentation_studio_presenter.py` | Slice 14 (needs the speech-authority decision) | planned |
| Rehearsal | practice, pause-edit-resume, no durable transcript | playback runtime | Slice 15 | planned |
| Variant compare / mix | side-by-side, synchronized navigation, selective composition into a new child | `jarvis/domain/presentation_studio_compose.py` | Slice 19 | planned |
| Template / promotion | whole-variant, scene, DA or motion promoted to the shared library | `presentation_studio_template.py` | Slice 20 | planned |
| Generic fullscreen surface | real browser fullscreen of a host element; armed request + user gesture; explicit `needs_gesture` / `unsupported` | `jarvis/domain/surface_fullscreen.py`, `runtime/control_center_fullscreen.js` | Slice 03 | implemented (Level 3) |
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
| `PresentationVariant` (`variants/<variant_id>.json`) | `variant_id` `psv_<32 hex>`, `variant_number`, `title`, `parent_variant_id` (the only graph trace, cycles refused; graph operations are Slice 16), ordered `scenes` (<= 64) of `{scene_id: pss_<12 hex>, prefab: {id, version}}`, `art_direction_id` (`psd_<12 hex>` or null, content is Slice 09), `score_id` (`psr_<12 hex>` or null; the score document is behind it, see *Score and cue contract*), `revision`, timestamps |

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
reads hit the disk every time (the file is the truth, also after a restart). Routes: `jarvis/protocol/presentation_studio_routes.py`, typed client: `LocalCoreClient.presentation_studio_*` (`jarvis/protocol/client.py`). There is no Control Center relay yet (Slice 05+ adds it
with the actor forced to `user`); the client constant `STUDIO_PREFIX` is not in `FORWARDABLE_PREFIXES` on purpose.

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
| GET | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/score` | `{score, problems}` (Slice 10, see *Score and cue contract*) |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/score` | `{expected_variant_revision, start_item_id, items, cues, sequences, recovery_points}` -> 201 `{score, problems: []}` (Slice 10) |
| PUT | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/score` | `{expected_revision, ...content}` -> `{score, problems: []}` (Slice 10) |

### Failures: typed, visible, logged

`PresentationStudioErrorCode` (`jarvis/domain/presentation_studio.py`), envelope `{"error": {"code", "message"}}`, message without absolute path:

| Code | HTTP | Meaning |
| --- | ---: | --- |
| `presentation_studio_invalid` | 400 | input refused (shape, bound, id, prefab pin, resource) |
| `presentation_studio_runtime_state_refused` | 400 | a runtime-only key or handle in a persistent document or body |
| `presentation_studio_unknown_presentation`, `presentation_studio_unknown_variant`, `presentation_studio_unknown_scene` | 404 | no such id (a malformed id is "unknown", never a path) |
| `presentation_studio_scene_incompatible` | 400 | a scene's controls or values disagree with its pinned prefab manifest (Slice 04) |
| `presentation_studio_prefab_unavailable` | 409 | the pinned prefab is unknown, tampered or its catalogue does not answer; the prefab service's own code is in the message (Slice 04). An id or version that simply does not exist is logged at `warning`; tampering is `error` |
| `presentation_studio_unknown_score` | 404 | the variant has no score yet, or its score file is absent (Slice 10) |
| `presentation_studio_score_incompatible` | 400 | a score reference or value does not resolve in the variant or its pinned prefab manifest (Slice 10) |
| `presentation_studio_stale_revision` | 409 | `expected_revision` differs from the stored revision |
| `presentation_studio_unsupported_schema_version` | 409 | stored document newer than this JARVIS; file untouched |
| `presentation_studio_corrupt_document` | 409 | stored document unreadable, oversize, linked, inconsistent, or an indexed variant missing |
| `presentation_studio_already_exists`, `presentation_studio_limit_reached` | 409 | id taken; 256 presentations, 64 variants/scenes/resources, or a 256 KiB document exceeded |
| `presentation_studio_storage_io` | 500 | disk, link/junction refusal, path limit, missing data root: the real cause is in the message |
| `invalid_request`, `core_unavailable`, `internal_error` | 400, 503, 500 | malformed query or body (not JSON, duplicate key, > 256 KiB) / Core not ready / unexpected |

Diagnostics `core.presentation_studio.{started,swept,created,saved,listed,validated,refused,scenes_checked,scene_described,score_loaded}` at `info` (ids, codes, counts; never titles, locators or content), and at `error`
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
<data_root>/presentations/<presentation_id>/scores/<score_id>.json     # Slice 10
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
| semantic edits, `expected_revision` as the edit basis, actor, relay | Slice 05 |
| debounced autosave, undo/redo ring (memory only) | Slice 08 |
| art direction content behind `art_direction_id` | Slice 09 |
| score content behind `score_id` | **done, Slice 10** (`scores/<score_id>.json`) |
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
scene is closed and pre-authored (R5). Slice 10 binds cues and actions to anchors (*Score and cue contract*): `reveal` / `hide` name an `anchor_id` of the scene.

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
| a score action | `ScoreAnchor` for `reveal` / `hide`, a declared `StudioControl` for `control_set` (Slice 10 reads, never invents one) | closed set per scene, bound to a declared control or a plain marker |
| an edit (Slice 05) | `StudioScene.control(control_id)`, `value_problem`, `effective_bounds` | validate through `check_scene`/`PrefabService`, write through `save_variant` under `expected_revision` |

Not here: the edit mutation engine (Slice 05), rendering and hot reload (Slice 06), the inspector UI (Slice 07), what a cue does
with an anchor (Slice 10: see its contract), the stage window lifecycle (Slice 12).

## Score and cue contract (Level 3)

Status: implemented by Slice 10. Conformance: `tests/unit/test_presentation_studio_{score,score_service}.py`, store/route/client rows in `test_presentation_studio_{store,routes}.py`,
data `tests/fakes/presentation_studio_score.py` and `tests/fixtures/presentation_studio/score.full12.json` (12 scenes, user/Jarvis/silent items, one locked sequence). Owner:
`jarvis/domain/presentation_studio_score.py` (pure), persisted by the Slice 02 store and service (`scores/<score_id>.json`, same atomic write, same single writer).

The score is the **inspectable plan** of a presentation: who speaks, what is shown, what is armed, how long things should take. It holds no playback position and no clock: it is data
that the playback runtime (Slice 12), the cue follower (Slice 13) and the Jarvis presenter (Slice 14) read. **Nothing in it is executable text** (below).

### Shape

| Piece | Holds |
| --- | --- |
| `Score` (`scores/<score_id>.json`, `score_id` `psr_<12 hex>`) | `presentation_id`, `variant_id`, `start_item_id`, `items` (<= 200), `cues` (<= 200), `sequences` (<= 16), `recovery_points` (<= 32), own `revision`, `created_at`, `updated_at` |
| `ScoreItem` (`item_id` `psi_<12 hex>`) | `scene_id`, `presenter` (`user` / `jarvis` / `none`), `kind` (`speech` / `silence`), `label`, `text` **or** `note`, `cue_id`, `visual` and `motion` action lists (<= 4 each), `target_duration_ms` (soft), `timing` (`soft` / `locked`), `interruption`, `recovery`, `recovery_point_id`, `next_item_id`, optional `loop` |
| `CueDefinition` (`cue_id` `psc_<12 hex>`) | `label`, `armable`, `predicate` = finite phrase / semantic set |
| `ActionRef` | one of five closed kinds, below |
| `LockedSequence` (`sequence_id` slug) | `label`, `steps` (<= 32) with relative offsets, `duration_ms`, `on_interrupt`, `recovery_id` |
| `RecoveryPoint` (`recovery_id` slug) | `label`, `item_id` |

Tracks (`Track`: `user_speech`, `jarvis_speech`, `visual`, `motion`, `cues`) are **views** over the items (`Score.track(track)`), listed in score order. The Jarvis speech track lists every
silence item as an explicit `{"silence": true}` entry: `jarvis speech: none` is a stated fact, not an absence.

### Order is the item graph, not a clock

- The order of a score is `start_item_id` then `next_item_id`. `next_item_id: null` ends the score. Each item has at most one successor and at most one predecessor: a score is **one chain**.
- **Cycles are refused.** The only repetition is a *declared loop* (`loop: {to_item_id, max_repeats}`, 1..8): after the item, return to an earlier-or-same item at most `max_repeats` times. Loops may nest;
  `Score.playback_order()` expands them deterministically and the total is bounded (`MAX_EXPANDED_ITEMS` = 2000, else the score is refused). An item unreachable from the start, two items leading to
  the same next item, or a forward loop are refused with a message naming the problem.
- `target_duration_ms` (1..3 600 000) is a **soft target**: the runtime may run shorter or longer and never waits on a wall clock to decide what comes next. `Score.estimated_duration_ms()` sums the
  targets over the expanded order for display only.

### Who speaks, and silence

| Rule | Where it is enforced |
| --- | --- |
| `presenter=none` is exactly `kind=silence`: no `text`, no `note`. A silence item may still carry actions and a soft target | `ScoreItem` constructor |
| A speaking item (`user` or `jarvis`) has **exactly one** of `text` (<= 1200, one printable line, said as written) or `note` (<= 300, the intention: the speaker improvises) | `ScoreItem` constructor |
| Jarvis speech exists only under `presenter=jarvis`: a locked sequence with a Jarvis step needs a `jarvis` host item, and a `jarvis` host over a sequence needs at least one Jarvis step | `Score` constructor |
| A locked sequence is Jarvis speech or silence, never the user; a `user` host item needs a `note` | `SequenceStep`, `ScoreItem` |

### Cues: a finite set, never a pattern

A cue predicate is `{phrases, semantics}`: up to 8 **normalised** phrases (NFKC, case-folded, whitespace collapsed; 2..60 characters, at most 8 words; letters, digits, space, apostrophe and hyphen only) and up to 4
semantic labels (slugs). Normalisation happens at construction, so two spellings of one phrase are one phrase; a repeated phrase is refused. There is no regular expression, no wildcard, no punctuation,
so a phrase cannot encode a pattern, markup, JSON or `tool: x`. `armable: true` requires a non-empty predicate; `armable: false` is a manual-advance cue (empty predicate allowed). Each cue names **exactly one item**
(`Score.resolve_cue(cue_id)`), every defined cue is used, an unknown cue id is refused. The cue id is the only thing an ambient match may name (R5): Slice 13 matches ambient text against the armed set,
emits `score.cue_satisfied(cue_id)` and the bound actions are resolved **from this stored score**. The matcher itself is not part of this Slice.

### Actions: a closed, reversible set

`ActionRef.kind` is one of `control_set` (`scene_id`, `control_id`, scalar `value`), `scene_goto` (`scene_id`), `reveal` / `hide` (`scene_id`, `anchor_id`), `sequence` (`sequence_id`). All are reversible
(`reveal` <-> `hide`; `control_set` restores the previous value; `scene_goto` returns to the previous scene; a sequence is left through its recovery point). There is no kind for a tool call, a command, a URL,
a script or free text, and no such field: a spare key is refused (`unknown keys`). `value` is a boolean, a finite number or a text <= 200 and never a list or an object. Actions are identified by their
canonical JSON, never by `==` (Python equates `1`, `1.0` and `true`).

`check_score(score, variant.scenes)` resolves every reference: the scene exists, the control is declared by that scene, the anchor is one of the scene's `ScoreAnchor`s, a `control_set` lies on the right track
(a `motion` group control is a `motion` action, every other group is `visual`) and its value respects the curated bounds (min / max / max_length / choices) and the control's own type.
When Core has a prefab catalogue, `check_score_values` also validates every `control_set` value against the **pinned manifest** (`value_problem`, the Slice 04 validator): a colour must be a colour, an integer an integer.

Structural guard: `FREE_TEXT_FIELDS` and `ID_FIELDS` classify every `str` field of the model. The free-text fields are exactly those that are **spoken** (`text`, step `text`), **shown** (`label`, `note`), **matched**
(`phrases`, normalised as above) or **written into a control** (`value`, bounded scalar). None of them is ever interpreted as an instruction; a test fails when a new string field is added without being classified.

### Locked sequences

A locked sequence is a segment of choreography whose relative timing is exact. It is started by one **host item** (`visual` holds `ActionRef(sequence)`), which must have `timing=locked`,
`target_duration_ms == duration_ms`, and an interruption policy other than `allow`. The converse holds: `timing=locked` is exactly "this item hosts a sequence".

| Rule | Value |
| --- | --- |
| steps | 1..32, in written order; `offset_ms` starts at 0 and **strictly increases**; `duration_ms` is greater than the last offset |
| step content | speaker `jarvis` (with `text`) or `none` (without), plus up to 4 `visual` and 4 `motion` actions (not another sequence); a step that does nothing is refused |
| determinism | `LockedSequence.timeline()` = `((offset_ms, step_id), ...)`: the same input always yields the same ordered offsets, whatever the JSON key order |
| `on_interrupt` | `pause_resume` (stop at the step boundary, resume from the next step) or `abort_to_recovery` (needs `recovery_id`, a `RecoveryPoint`) |
| item `interruption` | `allow` (a detour may start now), `at_boundary` (wait for the item or step boundary), `refuse` (only an explicit stop) |

### Recovery

`recovery` says where to continue after a detour: `continue_item`, `restart_item`, `skip_to_next`, or `recovery_point` (+ `recovery_point_id`, a `RecoveryPoint.recovery_id`). A recovery point names an item.
Position, reveal progress and detours are runtime state (R6) and stay in memory (Slice 12): the score only declares where to resume.

### Persistence, routes, failures

| Method | Route | Body -> answer |
| --- | --- | --- |
| GET | `.../variants/{variant_id}/score` | `{score, problems}`; `problems` lists references that no longer resolve in the **current** variant (a scene removed since); the stored score is never rewritten or hidden |
| POST | `.../variants/{variant_id}/score` | `{expected_variant_revision, start_item_id, items, cues, sequences, recovery_points}` -> 201 `{score, problems: []}`; the variant receives `score_id` |
| PUT | `.../variants/{variant_id}/score` | `{expected_revision, ...same content}` (whole replacement) -> `{score, problems: []}` |

- **Document**: `{"schema": "jarvis.presentation_studio.score", "schema_version": 1, ...}`, `UPGRADES[score] = {}`. A newer version is refused untouched (`unsupported_schema_version`), an unknown key is refused (a runtime-state key
  such as `position` gets `runtime_state_refused`), strict JSON, <= 256 KiB, canonical JSON via `Score.canonical()`; a score round-trips to the same canonical text.
- **Revisions**: the score has its own `revision`; a stale `expected_revision` is `stale_revision` and nothing is written. Saving a score does not touch the variant file. Creating one writes the **score first, then the variant** (which gets `score_id`
  and `revision + 1`): a crash between the two leaves an orphan, unreferenced score file, harmless and left in place (never deleted), and a retry creates a fresh one.
- **Link ownership**: once a variant has a `score_id`, `PUT .../variants/{id}` must send the same value (`presentation_studio_invalid` otherwise): a stale body cannot detach or swap the score.
- **Refusals**: `presentation_studio_unknown_score` (404: the variant has no score, or its file is absent), `presentation_studio_score_incompatible` (400: a reference or value does not resolve in the variant or its prefab), plus the existing
  `invalid`, `runtime_state_refused`, `stale_revision`, `already_exists`, `corrupt_document` (including a score file that names another variant), `unsupported_schema_version`, `prefab_unavailable`, `storage_io`.
- **Diagnostics**: `core.presentation_studio.score_loaded` at `info` (ids, revision, counts, number of problems; never speech, phrases or notes), writes under `saved` with `part: "score"`, refusals under `refused`.
- Typed client: `LocalCoreClient.presentation_studio_score`, `.presentation_studio_create_score`, `.presentation_studio_save_score`. No Control Center relay yet and no MCP tool (Slices 05, 21).

### Seams left for later Slices (not built here)

| Seam | Owner |
| --- | --- |
| armed-cue set delivery and ambient matching against `CuePredicate`, `score.cue_satisfied` | Slice 13 |
| playback position, reveal progress, detours, "where are we" over `playback_order()` | Slice 12 |
| speaking `text` through the speech path, executing a locked sequence's steps | Slice 14 |
| authoring a first score from a brief | Slice 11 |
| semantic edits of items and cues | Slice 05 |
| agent tools over the score | Slice 21 |

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

## Generic fullscreen surface (Level 3, Slice 03)

Contract and failure modes: [prefabs.md](prefabs.md) › *Host fullscreen*; surface mode:
[scene-model.md](scene-model.md) › *Surface mode: fullscreen*; Human check recipe:
[OPERATIONS.md](OPERATIONS.md) › *Plein écran d'une surface*. It is a generic surface capability
(`SurfaceFullscreenRequest` / `SurfaceFullscreenState`, `window.JarvisFullscreen`), not a presentation fork.

What later Slices may rely on, and nothing else:

- `JarvisFullscreen.enter({object_id, display, keys, arm_s})` / `exit()` / `onNavigate(fn)` / `state()` on the page
  (Slices 12 and 18 call these; `enter` armed without a gesture, entered with one).
- `POST /api/fullscreen/commands {action: "enter"|"exit", ...}` and `GET /api/fullscreen/state` for the agent side
  (Slice 21 wraps them as `presentation_fullscreen`). An `enter` answer is `needs_gesture`: **the agent must say the
  user has to click, never that it is fullscreen.** `entered` is read from `GET /api/fullscreen/state`.
- Navigation keys (next, previous, first, last) arrive through `onNavigate` while fullscreen; the frame relays none. **Opt-in**: `keys: "host"` (default `none`, which never steals focus from a prefab text field); Slice 12 passes `host` for playback.
- Slice 22 (hardening) re-checks fullscreen restore; the physical checks (Escape key, multi-monitor, permission
  prompt) stay Human checks.

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
| Generic fullscreen surface | 3 (Slice 03) | 3 |
| Presentation artifact (identity, variants as references, scene refs, DA/score refs, resources, storage) | 1-2 | 3 (**done**, Slice 02) |
| Studio scenes and controls (pin, curated controls, anchors, preview, discovery, payload cap, prefab compatibility) | 0-1 | 3 (**done**, Slice 04) |
| Score, cues, timing, locked sequences, recovery points (model, validators, store, routes) | 0-1 | 3 (**done**, Slice 10) |
| edit, hot reload, autosave, DA, playback, cue matching, rehearsal, variants, compare/mix, promotion, agent operations | 0-1 | 3 each |

There is no `docs/CONTEXT.md` or documentation-level registry in this repository: the level of a concept is stated in its page header (`Status: Level N`), as in [presentation-mode.md](presentation-mode.md).
