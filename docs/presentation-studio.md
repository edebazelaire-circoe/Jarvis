# Presentation Studio - concepts, owner map and status

Entry page for the Presentation Studio (handoff `jarvis-interactive-presentation-studio`): a structured, editable, rehearsable and presentable **Presentation** that Jarvis can author and
deliver. It **holds no behaviour contract yet**: it names the canonical concepts, says who will own each, and tracks status per section. When a section gets its own contract page or code,
that owner wins and this row is updated in the same commit.

Status: **Level 2 skeleton** for the page as a whole; the *Presentation contract* section below is **Level 3** (Slice 02: domain, port, file store, Core service, Core routes, typed client, conformance tests) and so is the *Scene and control contract* (Slice 04: logical scene, curated controls, discovery, prefab compatibility) and the *Semantic edit contract* (Slice 05: one edit API for voice and GUI) and the *Score and cue contract* (Slice 10: tracks, silence, cues, closed actions, locked sequences, score store and routes) and the *Playback roles and speech authority* contract (Slice 01c: role -> mode, switch/restore, scripted-line arguments) and the *Variant graph and operations contract* (Slice 16: branches, display numbers, activate, rename, archive under a confirmation token, restore, crash reconciliation).
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
| Presentation Variant | creative branch of a whole presentation; immutable id, monotonic display number, title, provenance; graph, branch, switch, archive / restore | `jarvis/domain/presentation_studio_variants.py`, `core/presentation_studio_variants.py` | [Variant graph and operations contract](#variant-graph-and-operations-contract-level-3) below, Slice 16 | **implemented (Level 3)** |
| Studio scene + control | logical scene pinned to a prefab `(id, version)`; curated typed controls bound to manifest inputs; score anchors; preview metadata; introspection | `jarvis/domain/presentation_studio_scene.py`, `core/presentation_studio_scene_catalog.py` | [Scene and control contract](#scene-and-control-contract-level-3) below, Slice 04 | **implemented (Level 3)** |
| Scene-local variant | lightweight alternative of one scene inside a variant | `presentation_studio_variants.py` | Slice 17 | planned |
| Semantic edit (3 tiers) | control patch / structural patch / source edit; one layer for voice and GUI; preview vs commit | `jarvis/domain/presentation_studio_edit.py`, `core/presentation_studio_edit.py`, `core/presentation_studio_events.py`, `runtime/presentation_studio_relay.py` | [Semantic edit contract](#semantic-edit-contract-level-3) below, Slice 05 | **implemented (Level 3)** |
| Scene hot reload | scene-local rebuild with state preservation and rollback | `core/presentation_studio_reload.py` | Slice 06 | planned |
| Autosave + undo | every acknowledged commit is durable (no buffer, no second path); restart recovery of the active variant; bounded in-memory undo/redo ring per variant; pins held by undo entries | `domain/presentation_studio_history.py`, `core/presentation_studio_autosave.py` | [Persistence and undo contract](#persistence-and-undo-contract-level-3) below, Slice 08 | **implemented (Level 3)** |
| Art direction | structured profile with provenance (provided / inferred / generated) | `jarvis/domain/presentation_studio_art_direction.py` | Slice 09 | planned |
| Score, cues, timing | multi-track score, explicit silence, armable finite-set cues, closed reversible actions, soft/locked timing, recovery points | `jarvis/domain/presentation_studio_score.py` (stored by the Slice 02 store and service) | [Score and cue contract](#score-and-cue-contract-level-3) below, Slice 10 | **implemented (Level 3)** |
| Playback runtime | roles (user presenter / Jarvis presenter / rehearsal), position, detours, "where are we" | `jarvis/domain/presentation_studio_playback.py`, `core/presentation_studio_playback.py` | Slice 12 | planned |
| Armed cue following | ambient speech may only satisfy a pre-armed cue id, bound to a pre-authorized reversible action | `jarvis/domain/presentation_studio_cues.py`, `runtime/presentation_studio_cue_follower.py` | Slice 13 + amendment of [presentation-addressed-turn.md](presentation-addressed-turn.md) section 12 | planned |
| Playback roles, speech authority (decision A) | role -> interaction mode, ambient-lane and speech policy; who may switch the mode; restore protocol; the `announce_notice` argument set | `jarvis/domain/presentation_studio_roles.py` | [Playback roles and speech authority](#playback-roles-and-speech-authority-level-3-slice-01c-decision-a) below, Slice 01c | **implemented (Level 3)** |
| Jarvis presenter, locked sequences | scripted speech and deterministic AV sequences through the existing speech path, outside PRESENTATION | `core/presentation_studio_presenter.py` | Slice 14 (speech authority decided: Slice 01c) | planned |
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
| `Presentation` (`presentation.json`) | `presentation_id` `pst_<32 hex>`, `title` (<= 80, one printable line), `active_variant_id`, `variant_counter` (last number handed out, monotone, never reused), the variant index of live nodes (1..64: `{variant_id, variant_number}` plus, since Slice 16 and manifest v2, `rationale`, `created_by`, `sources`, `preview_id`), `archived` (Slice 16: nodes whose file was moved to `archive/`, <= 128), `resources` (<= 64, `{kind, locator, title}`), `revision`, `created_at`, `updated_at` |
| `PresentationVariant` (`variants/<variant_id>.json`) | `variant_id` `psv_<32 hex>`, `variant_number`, `title`, `parent_variant_id` (the tree edge; cycles refused; the graph operations are Slice 16), ordered `scenes` (<= 64) of `{scene_id: pss_<12 hex>, prefab: {id, version}}`, `art_direction_id` (`psd_<12 hex>` or null, content is Slice 09), `score_id` (`psr_<12 hex>` or null; the score document is behind it, see *Score and cue contract*), `revision`, timestamps |

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

Every document carries `{"schema": "jarvis.presentation_studio.presentation" | "jarvis.presentation_studio.variant", "schema_version": n}`; `n` is 2 for the Presentation (Slice 16 added the node metadata and `archived`: see *Variant graph and operations contract*) and 2 for the variant (Slice 04 added scene fields: see *Scene and control contract*, Versioning).

- A document with a **newer** `schema_version` than this JARVIS reads is refused (`presentation_studio_unsupported_schema_version`, HTTP 409), never read best-effort. The file is left untouched: a save reads the stored
  document first, so a newer file is never overwritten by an older JARVIS. The listing names it in `problems`.
- An **older** version goes through `UPGRADES[schema][n]` (`n -> n+1`, one step per version, one step 1 -> 2 for the Presentation (Slice 16) and one for the variant; `upgrade_document`). A missing step is `corrupt_document`, never a guess.
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
| `presentation_studio_active_variant_protected` | 409 | the active variant (or the last live one) is in the set an archive would touch (Slice 16) |
| `presentation_studio_confirmation_required` | 400 | an archive without the confirmation token of a plan (Slice 16) |
| `presentation_studio_confirmation_stale` | 409 | the token is forged, expired, or no longer matches the set, a title, the revision or the chosen active variant (Slice 16) |
| `presentation_studio_not_archived` | 409 | restoring a variant that is not archived (Slice 16) |
| `presentation_studio_linked_document_unsupported` | 409 | the variant cites a linked document no registered kind can copy, so a branch is refused rather than sharing it (Slice 16) |
| `presentation_studio_unsupported_schema_version` | 409 | stored document newer than this JARVIS; file untouched |
| `presentation_studio_corrupt_document` | 409 | stored document unreadable, oversize, linked, inconsistent, or an indexed variant missing |
| `presentation_studio_already_exists`, `presentation_studio_limit_reached` | 409 | id taken; 256 presentations, 64 variants/scenes/resources, or a 256 KiB document exceeded |
| `presentation_studio_storage_io` | 500 | disk, link/junction refusal, path limit, missing data root: the real cause is in the message |
| `invalid_request`, `core_unavailable`, `internal_error` | 400, 503, 500 | malformed query or body (not JSON, duplicate key, > 256 KiB) / Core not ready / unexpected |

Diagnostics `core.presentation_studio.{started,swept,created,saved,listed,validated,refused,scenes_checked,scene_described,score_loaded,score_relinked}` at `info` (ids, codes, counts; never titles, locators or content), and at `error`
(which puts them in the Error Logs viewer) `failed` (storage, corrupt or newer document), `unreadable` (one presentation unusable while listing: it is named in `problems` and the others still list),
`sweep_failed`, `unexpected` (any non-typed exception at the route boundary, with the real cause). Since Slice 08 `start()` also writes `recovered` (`info`: counts) and `recovery_failed` (`error`: an unreadable active variant, with its code; [Persistence and undo contract](#persistence-and-undo-contract-level-3)).

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
<data_root>/presentations/<presentation_id>/archive/<variant_id>.json    # Slice 16: archived variants (moved, never deleted)
<data_root>/presentations/.staging-<16 hex>/          # a creation in progress; swept at start
```

- **Atomic file writes**: unique temporary beside the target, `fsync`, `replace_with_retry` (`os.replace`, bounded retry on a Windows lock), then the folder is flushed so the rename itself survives a power cut (Slice 08, *Persistence and undo contract*). A crash leaves the old text whole or the new text whole; a leftover `*.<8 hex>.tmp` is swept at the next start and never blocks a save.
- **Atomic creation**: the whole folder is built in `.staging-*` (variants first, manifest last), then renamed; `os.rename` fails if the target exists. There is never a presentation folder without its manifest.
- **Multi-file operations** write variants first and `presentation.json` last. Slice 16 is the first to touch both: its operations, their order and the reconciliation rule for every interrupted state are in *Variant graph and operations contract*. Reads reconcile (`check_consistency`): an indexed variant that is missing is `corrupt_document`, not silently dropped.
- **Defences** (`safe_folders`): absolute root, no link/junction/reparse point, Windows path limit, ids validated as exact-shape path components, files read by `lstat` + `fstat` (same inode, regular, <= 256 KiB, UTF-8), bounded retry when Windows refuses an open for a few milliseconds.
- **Never deletes a document**: `sweep` removes only `.staging-*` and our `*.tmp`. Archiving a variant (Slice 16) moves (`move_variant`: one `rename`, never replaces), never removes.
- Proof: `tests/unit/test_presentation_studio_crash.py` kills a real writer subprocess at varied instants (mutation-checked: an in-place write fails it) and a creator, and kills at the worst deterministic point (complete temporary, replace not done).

### Seams left for later Slices (not built here)

| Seam | Owner |
| --- | --- |
| scene controls, values, prefab mapping to the stage window | **done, Slice 04** (variant v2, `StudioScene`; `SceneRef` is now an alias of it) |
| semantic edits, `expected_revision` as the edit basis, actor, relay | **done, Slice 05** (*Semantic edit contract*) |
| autosave (= the durable commit) and the bounded undo/redo ring (memory only) | **done, Slice 08** (*Persistence and undo contract*) |
| art direction content behind `art_direction_id` | Slice 09 |
| score content behind `score_id` | **done, Slice 10** (`scores/<score_id>.json`) |
| variant create/switch/archive, `variant_counter` increments, `archive/<variant_id>.json` | **done, Slice 16** (*Variant graph and operations contract*) |

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

The variant document is now `schema_version` **2**; the Presentation document stays 1 at this Slice (Slice 16 raises it to 2) (`CURRENT_VERSIONS`). `UPGRADES[variant][1]`
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
| an edit (Slice 05) | an operation in `presentation_studio_edit.py` | see *Semantic edit contract*, Extension points |

Not here: rendering and hot reload (Slice 06), the inspector UI (Slice 07), the stage window lifecycle (Slice 12).

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
- **Cycles are refused.** The only repetition is a *declared loop* (`loop: {to_item_id, max_repeats}`, 1..8): after the item, return to an earlier-or-same item at most `max_repeats` times. Loops may nest or follow one another; two loops that overlap partially are refused;
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
| An item's own `scene_goto` action names the item's own scene (an item cannot belong to scene 3 and navigate to scene 9; other actions may target other scenes) | `ScoreItem` constructor |

`text`, `note` and `label` are **untrusted data**: they are stored verbatim (printable, bounded) and may contain anything an author or a model typed, including instruction-looking text. Slices 13 and 14 must treat them as
content to say or to show, never as a command or a tool request: a presenter-speech turn built from a `note` carries no tool authority, and the cue matcher only ever names a `cue_id`.

### Cues: a finite set, never a pattern

A cue predicate is `{phrases, semantics}`: up to 8 **normalised** phrases (NFKC, case-folded, whitespace collapsed, U+2018 / U+2019 / U+02BC folded to `'`; 2..60 characters, at most 8 words; **Latin-script letters** (accented French is fine), ASCII digits, space, apostrophe and hyphen only: a Cyrillic or Greek lookalike letter or a non-ASCII digit is refused, so a phrase can never look identical to another yet never collide with it) and up to 4
semantic labels (slugs). Normalisation happens at construction, so two spellings of one phrase are one phrase; a repeated phrase inside one cue is refused. The same phrase on different cues is **allowed** (the same "suivant" can recur), and is surfaced instead: `phrase_index(score)` maps each normalised phrase to its cue ids, `semantic_index` does the same for semantic labels, and `ambiguous_phrases(score, armed_cue_ids)` lists the ones that name more than one *armable* cue of the given set. Ambiguity is a property of the **armed** set, so Slice 13 evaluates it on the cues it arms, not score-wide. There is no regular expression, no wildcard, no punctuation,
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
- **Link ownership**: `score_id` belongs to the score routes. `PUT .../variants/{id}` cannot attach, swap or clear it (`presentation_studio_invalid`; the body keeps the stored value, `null` while there is none): a stale body cannot detach a score and a made-up id cannot lock the variant out of its own score. The guard sits in `_persist_variant`, the one place that writes a variant file, so every writer is covered: `save_variant`, the Slice 05 edit API (`write_variant`) and `create_score`; only `create_score` may change the link. An edit commit on a variant that has a score keeps `score_id` and bumps only the variant revision.
- **Dangling link repair**: if the stored `score_id` names a file that is absent (deleted, restored backup), `POST .../score` replaces the link: the answer carries `relinked_from` (the missing id) and Core logs `core.presentation_studio.score_relinked` at `warning`. A file that exists but is corrupt or newer is never replaced (`corrupt_document` / `unsupported_schema_version`); a usable one is `already_exists`.
- **Refusals**: `presentation_studio_unknown_score` (404: the variant has no score, or its file is absent), `presentation_studio_score_incompatible` (400: a reference or value does not resolve in the variant or its prefab), plus the existing
  `invalid`, `runtime_state_refused`, `stale_revision`, `already_exists`, `corrupt_document` (including a score file that names another variant), `unsupported_schema_version`, `prefab_unavailable`, `storage_io`.
- **Diagnostics**: `core.presentation_studio.score_loaded` at `info` (and `score_relinked` at `warning`, see above) (ids, revision, counts, number of problems; never speech, phrases or notes), writes under `saved` with `part: "score"`, refusals under `refused`.
- Typed client: `LocalCoreClient.presentation_studio_score`, `.presentation_studio_create_score`, `.presentation_studio_save_score`. No Control Center relay yet and no MCP tool (Slices 05, 21).

### Seams left for later Slices (not built here)

| Seam | Owner |
| --- | --- |
| armed-cue set delivery and ambient matching against `CuePredicate`, `score.cue_satisfied`; ambiguity of the armed set via `ambiguous_phrases` | Slice 13 |
| runtime meaning of `reveal` / `hide` on a plain marker anchor (no `control_id`) versus a control-bound one: this Slice only checks that the anchor exists | Slice 12 |
| surfacing `problems` when a scene, control or anchor a score references is removed or renamed (`save_variant` does not block it; `GET score` reports it and `save_score` refuses until fixed); the score revision is separate from the variant revision, so autosave / undo / compare track both | Slices 05, 08, 19 |
| playback position, reveal progress, detours, "where are we" over `playback_order()` | Slice 12 |
| speaking `text` through the speech path, executing a locked sequence's steps | Slice 14 |
| authoring a first score from a brief | Slice 11 |
| granular score edit operations (items, cues, sequences) on the Slice 05 edit API; Slice 05 edits scenes and controls only | Slices 11, 15, 21 |
| agent tools over the score | Slice 21 |

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

### Undo record (the ring on top of it is Slice 08: *Persistence and undo contract*)

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

Not here: the source rebuild / hot reload (Slice 06), the inspector UI (Slice 07), the MCP server (Slice 21). The undo ring and the durability contract are Slice 08 (*Persistence and undo contract*).

## Persistence and undo contract (Level 3)

Status: implemented by Slice 08. Conformance: `tests/unit/test_presentation_studio_{history,history_service,history_routes,history_crash,recovery,durability,history_docs}.py`.
Owner modules: `jarvis/domain/presentation_studio_history.py` (pure: bounds, `UndoBook`, results, request), `jarvis/core/presentation_studio_autosave.py`
(`PresentationStudioHistory`: the hook, undo/redo, status, pins), `jarvis/core/presentation_studio_service.py` (`Recovery`, `start()`), the store's folder flush
(`jarvis/adapters/file_presentation_studio_store.py`), routes in `presentation_studio_routes.py`, relay in `presentation_studio_relay.py`, typed client
`LocalCoreClient.presentation_studio_{history,undo,redo}`.

### Durability: there is no second persistence path

Every commit of the semantic edit API (Slice 05) is durable **at its acknowledgement**: temporary file, `fsync` of the file, atomic replace, then the folder is flushed
(`fsync` of the directory on POSIX, `FlushFileBuffers` on a directory handle on Windows), all under the revision comparison. "Autosave" is this contract, not a queue:

| Question | Answer |
| --- | --- |
| After `kill -9` / `Popen.kill()` of Core | the document is the last acknowledged revision, or the one in flight if its replace had already happened: never older, never torn, never mixed (real-subprocess tests kill during an edit, an undo and a redo) |
| After a power cut | the file content was `fsync`ed before the replace and the directory entry is flushed after it; whether the OS and the disk honour the flush is theirs (a write cache that lies is outside the proof). If the flush is refused the commit still stands and the platform's own journal applies (`_sync_folder` returns `False`, never raises) and the store says so once per run of Core: `core.presentation_studio.folder_flush_refused` (`warning`, `scope` only, no path). **Not proven by a test here** (no power-cut harness): only the call order and the kill behaviour are |
| Delay or loss window of an acknowledged commit | none: nothing is buffered, no timer, nothing to flush at shutdown, at a variant switch or on sleep |
| High-rate gestures (slider drag, typing) | `mode=preview` writes nothing, so there is nothing to lose; the interface commits once on release / blur / Enter. No debounce class exists on purpose: a coalescer would be a window in which an acknowledged edit is not on disk, which the Slice acceptance forbids |
| Several writers on one data root | single writer by design (Slice 02); two Core processes on one root are unsupported (lost updates), as documented there |

The active variant is whatever the file holds: every read hits the disk (no cache), so a restart has nothing to rebuild.

### Restart recovery (`PresentationStudioService.start`)

0. **Recovery never delays startup.** Reloading an active variant costs about 24 ms, so 6 s at the 256-Presentation limit. `start()` sweeps and scans (fast), then returns; the reload runs in a background task, one Presentation per turn of the event loop. `last_recovery.pending` / `complete` say how far it is (`complete: false` until `pending` is 0, and after a `stop()` or an unexpected loader failure that interrupted it), so the report is never read as clean while it is partial. A read never waits for it: every read hits the disk and raises its own typed error. `stop()` (called by Core's stop) cancels it; it writes nothing.
1. `sweep` removes only our leftovers (`.staging-*`, `*.<8 hex>.tmp`). A temporary is **never promoted**, even when complete and newer than the stored document: it was not acknowledged.
2. `last_recovery` (`Recovery`: `presentations`, `active_loaded`, `unreadable`, `swept`, `sweep_failed`, `pending`, `complete`) reloads, from disk only, the active variant of every Presentation and reports the result in
   `core.presentation_studio.recovered` (`info`).
3. An unreadable document (truncated, empty, not JSON, wrong type, wrong schema name or a non-integer `schema_version`, missing or foreign variant, missing variant file, truncated or absent manifest) is a row in `unreadable`
   with its typed code (`presentation_studio_corrupt_document`; a variant from a newer JARVIS is `presentation_studio_unsupported_schema_version`) and `core.presentation_studio.recovery_failed` at `error`
   (it appears in the Error Logs viewer). **Never** a silent fallback: no older variant, no `*.tmp`, no `.bak` is loaded in its place; the next read raises the same code; the other Presentations load; nothing is rewritten.
   `start()` never raises (a store that cannot even be scanned is `recovery_failed` too).

### Undo/redo ring (memory only, hard bounds)

A committed edit that changed state records its inverse operations (the Slice 05 undo record) in a ring **per variant**. Undo and redo are semantic operations: they call
`PresentationStudioEditService.edit` with the inverse operations, so they get the same validation, the same revision basis, the same durable write and the same conversation event
(`status` `undone` / `redone`) as any edit; the revision is never rewound (an undo is a new revision). The actor is a label, as everywhere: `POST .../undo` takes `{actor, expected_entry_id?}`.

| Bound | Value | When exceeded |
| --- | ---: | --- |
| entries per variant (undo + redo) | 32 | the oldest cedes: `core.presentation_studio.history_evicted` (`warning`, reason `variant_bound`), counted in `evicted` |
| bytes of one entry | 64 KiB (`MAX_UNDO_BYTES`) | not kept; the ring of the variant is dropped (`entry_too_large`) rather than left with a hole: older steps would replay on a state that is no longer theirs. The edit itself stands |
| bytes per variant | 256 KiB | the oldest entry cedes (`variant_bound`) |
| bytes in total | 1 MiB of **serialized** operations | the least recently used other ring is dropped (`memory_bound`) |
| variants tracked | 8 | the least recently used ring is dropped (`tracked_variants_bound`) |

The byte bounds count the compact JSON size of the stored inverse operations, not the Python heap. Measured on real scene operations the heap is about 8.7 times larger (220 KB serialized held 1.9 MiB), so the worst case at the 1 MiB bound is about 9 MiB per Core. It is still a hard bound and fine for a desktop; the numbers were not halved to compensate because that would shorten useful history for no practical gain.

Every loss is visible: a `warning` diagnostic with ids, reason and counts (`history_evicted` for entries, `history_dropped` for a ring), the counters `evicted` / `redo_cleared` on the history status, and the typed answer of the
next undo (`history_unavailable` with the reason, or `nothing_to_undo` with "older steps were dropped"). Clearing the redo branch on a new edit is semantics (`info`, counted as `redo_cleared`), not an eviction.

### Results (typed, visible; HTTP in brackets)

| `status` | HTTP | Meaning |
| --- | ---: | --- |
| `applied` | 200 | the inverse (or the redo) was committed durably; `revision` is the new one, `entry` the step, `history` the new state, `score_problems` the number of score references that no longer resolve (`null` without a score) |
| `history_unavailable` | 409 | no ring for this variant; `reason`: `not_recorded_since_start` (after a restart or before any edit since Core started), or why it was dropped (`document_moved_on`, `entry_too_large`, `entry_not_applicable`, `variant_bound`, `memory_bound`, `tracked_variants_bound`, `variant_archived`, `presentation_removed`, `record_failed`) |
| `nothing_to_undo` / `nothing_to_redo` | 409 | the ring exists and that stack is empty |
| `stale` | 409 | `expected_entry_id` is not the head (another actor edited since the caller looked, `head_changed`), the stored scenes no longer match what the ring expects (`document_moved_on`: written outside the ring, the ring is dropped), an edit is being recorded (`revision_moved`: its file is replaced and its history hook has not run yet, retry; the ring is **kept**), or another writer won the base revision (`revision_moved`): nothing is written, never forced |
| `refused` | 400 / 404 / 409 | the inverse edit failed the edit validations (deterministic): the code is the edit's own, the ring is dropped (`entry_not_applicable`). **Exception:** if the actor may not request an operation of the step (`ALLOWED_EDIT_OPS`, e.g. Slice 21 narrows the voice), the reason is `actor_not_allowed`, nothing is written and the ring is **kept** for someone who may |

Codes (envelope `error` on every non-`applied` result): `presentation_studio_history_unavailable`, `presentation_studio_history_empty` (both `nothing_to_*`), `presentation_studio_history_stale`, all 409. A malformed body, an
unknown variant or a storage fault is the coded envelope, not a result (`presentation_studio_invalid` 400, `presentation_studio_unknown_variant` 404, `presentation_studio_storage_io` 500).

### Coherence rules

- **One ring per variant, shared by all actors.** An edit by the voice and one by the page are two entries of the same ring; undo undoes the head whoever made it. A caller that showed a button for an entry passes `expected_entry_id`: if the head changed it gets `stale`, never a different undo.
- **The ring knows which scenes it expects** (`scenes_digest`, the canonical stored form, so `1`, `1.0` and `true` differ). A `PUT` of the variant that changes the scenes breaks that: the next undo is `stale` / `document_moved_on` and the ring is dropped; a change that leaves the scenes equal (the variant title) breaks nothing.
- **A new edit clears redo.** Undo moves an entry to the redo stack as its own inverse and back; the count is conserved.
- **Concurrency.** Undo and redo are serialized with each other; a plain edit never waits for them. An undo and an edit on the same base: one wins the revision comparison, the other is `stale`; the ring always describes the stored document (`in_sync`).
- **Restart.** The ring is not durable: after a restart every undo is `history_unavailable` / `not_recorded_since_start`, and `GET .../history` says `tracked: false, durable: false`. Editing starts a new ring.
- **Variants (Slice 16, done).** Switching the active variant keeps the rings (bounded by the 8-variant LRU). Archiving a variant calls `PresentationStudioHistory.drop_variant` for each archived variant (undo then answers `variant_archived`); `PresentationStudioVariants.drop_presentation` is the hook a future Presentation deletion must call (`presentation_removed`).
- **No durable snapshots, no branches** (user decision D14): this is a short efficient memory, not a version history.

### Prefab pins held by undo entries (for the Slice 01a retention)

An entry whose inverse is a `scene.add` re-adds a scene with its exact `(prefab_id, version)`. `PresentationStudioHistory.pinned_versions(prefab_ids)` has the `PrefabPinRegistry` shape
(`{prefab_id: frozenset(versions)}`, every requested id present, never raises) and `pins()` the flat set; the Slice 06 registry wiring unions it in `CompositePinRegistry`. The registration rule
of `docs/prefabs.md` ("register an old version in its store **before** writing that pin into any document") is met by `EditHistory.begin`, called synchronously before the document write: the inverse and its pins are
held (reserved) while the pin leaves the document, converted into the entry in the same synchronous step after the write, and released if the write does not happen. Evicting or dropping an entry releases its pins.

### Routes

| Method | Core route | Control Center relay |
| --- | --- | --- |
| GET | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/history` | `GET /api/presentation-studio/presentations/...` same tail |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/undo` | `POST /api/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/undo`, actor forced to `user` |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/redo` | `POST /api/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/redo`, actor forced to `user` |

`GET .../history` answers `{revision, in_sync, durable: false, tracked, reason, message, undo_count, redo_count, undo, redo, next_undo, next_redo, bytes, evicted, redo_cleared, stats}`
(`undo` / `redo`: the 8 most recent entries, newest first, as `{entry_id, ops, tier, actor, revision, bytes}`: operation names only). It reads and writes nothing. Core takes `actor` from the body; the relay replaces it with `user`
(same rule as the edits: one voice/GUI door, the MCP layer of Slice 21 stamps `brain`). A committed undo, like any edit, changes the canonical variant only: the visible stage window follows in Slice 12.

### Observability

No new conversation event type: an undo or redo is the existing `system.presentation_studio.edit_committed` with `status` `undone` / `redone` (operation names are the inverse operations; ids, tier, actor, revision; never a value, a title or an intent).
Diagnostics `core.presentation_studio.history_applied`, `history_not_applied` (`info`: ids, direction, actor, status, reason, code), `history_evicted`, `history_dropped` (`warning`), `history_record_failed` (`error`),
`history_score_unchecked` (`warning`), `folder_flush_refused` (`warning`, once per run), and for recovery `recovered` (`info`), `recovery_failed` (`error`). The relay journals `studio_undo` / `studio_redo` with status, result and code only.

### Decisions, deviations and entry conditions for other Slices

- **Deviation from the literal Slice wording "Debounced/atomic autosave".** There is no debounce. The goal and the acceptance sentence ("killing/restarting cannot revert the presentation behind the last committed autosaved state") are served better without one: any debounce is a window in which an acknowledged edit is not on disk. The measured cost of the immediate durable commit is small (about 2.6 ms for a 50 KB document with the folder flush, 1.1 ms more than without). A future debounce needs a PM decision and must be a distinct op class with a documented, tested maximum latency and a flush on shutdown and variant switch.
- **Slice 07 (inspector UI), entry condition.** Commit granularity is history granularity: one commit is one undo entry and the ring holds 32. The UI must commit on release / blur / Enter and use `mode=preview` while dragging or typing, never one commit per keystroke (it would evict every earlier meaningful step).
- **Slice 16 (variants), entry condition (met by Slice 16).** It MUST call `PresentationStudioHistory.drop_variant` on archive and `drop_presentation` on deletion: `PresentationStudioVariants.archive` calls `drop_variant` per archived variant (tested); there is no Presentation deletion yet, `drop_presentation` is wired as the hook it must call.
- **Slice 21 (agent and voice), entry conditions.** `expected_entry_id` is optional on the wire, so a blind voice "undo" undoes whoever edited last, the user's slider move included. The `brain` path of the MCP undo tool must read `GET .../history` and pass `expected_entry_id`, and it owns the confirmation before the voice undoes a user's edit. When it narrows `ALLOWED_EDIT_OPS`, an actor refusal keeps the ring (`actor_not_allowed`), tested.
- **Per-entry bound below the document limit.** An entry is at most 64 KiB while a variant document may reach 256 KiB: one batch of up to 16 operations that removes large scenes can exceed 64 KiB. The edit then stands, its result carries `undo.available: false`, the ring is dropped (`entry_too_large`) and that removal cannot be undone. Not reachable with the current prefabs (a scene payload is capped at 16 KiB, so about four maximal scenes per 64 KiB); the bound is a PM decision, visible and documented.
- **The recovery report has no route and no UI yet.** `last_recovery` is read in-process; its visibility today is the Error Logs viewer (`recovery_failed` rows) and the `core.presentation_studio.recovered` row. Slice 07 may want a health field or a banner.

### Extension points

| To add | Where | Rule |
| --- | --- | --- |
| a bound | `presentation_studio_history.py` constants and the table above | `test_presentation_studio_history_docs.py` compares them |
| a reason a ring is dropped | `DropReason` + `REASON_TEXT` | every reason has a sentence and is listed in the results table |
| a pin source (templates, scene-local variants) | its own store implementing `pinned_versions`, unioned by the Slice 06 registry | register before the document write, as `begin` does |
| debounced autosave | **not allowed** without a PM decision: it would create an acknowledged-but-not-durable window | if ever needed, a distinct op class with a documented, tested maximum latency and flush on shutdown |

## Variant graph and operations contract (Level 3)

Status: implemented by Slice 16. Conformance: `tests/unit/test_presentation_studio_variants_{domain,service,crash,recovery,routes,docs}.py`.
Owner modules: `jarvis/domain/presentation_studio_variants.py` (pure: node model, graph invariant, plans, confirmation token, reconcile plan),
`jarvis/core/presentation_studio_variants.py` (`PresentationStudioVariants`: the operations), `jarvis/core/presentation_studio_linked.py` (linked-document
registry, `ScoreLink`), `jarvis/core/presentation_studio_variant_events.py` (`StudioVariantEvents`), routes `jarvis/protocol/presentation_studio_variants_routes.py`,
relay `jarvis/runtime/presentation_studio_variants_relay.py`, typed client `LocalCoreClient.presentation_studio_{graph,create_branch,activate,rename,archive_plan,archive,restore}`.

A **variant** is a durable creative direction of the whole presentation, not an undo state: the fine history stays the per-variant memory ring of Slice 08 and is
never a node. Variants form a graph, a rooted tree for ordinary use (every branch has a parent; variant #1 is the root). The model already carries `sources`
so that composition (Slice 19) can add provenance edges later; Slice 16 writes only the parent edge (`sources == [parent]`).

### A node, and where each field lives

| Field | Where | Rule |
| --- | --- | --- |
| `variant_id` | manifest entry + the variant file | `psv_<32 hex>` (the existing format; the handoff's `pv_` shorthand is this id), immutable machine id |
| `variant_number` | manifest entry + the variant file | short positive integer, **immutable**, allocated from `variant_counter`, **never reused** (below) |
| `title` | the variant file only | human title (`rename`), <= 80, one printable line |
| `parent_variant_id` | the variant file only (and, for an archived node, its manifest entry) | the tree edge |
| `rationale` | manifest entry | why the branch was made. **Untrusted text**: <= 600, one printable line, stored verbatim, never interpreted, never in an event |
| `created_by` | manifest entry | `user`, `brain` or `system` (variant #1 and migrated nodes) |
| `sources` | manifest entry | variants this one derives from (<= 4); Slice 16 writes `[parent]`; each must exist and be older |
| `preview_id` | manifest entry | opaque handle `psp_<12 hex>` or `null`: placeholder for the thumbnail of Slice 18, nothing writes it yet |
| archive state | manifest (`variants` live, `archived` archived) + the folder of the file | an archived node's file is in `archive/`, never deleted |

The manifest is therefore **schema v2** (`UPGRADES[presentation][1]` fills the defaults of a Slice 02 manifest: empty rationale, `system`, no sources, no preview, no archive;
reading never rewrites, the first graph operation writes v2; a JARVIS that only knows v1 refuses a v2 manifest untouched). The variant document is **unchanged** by Slice 16
(it stays at the version Slice 04 / 06 define), so the two Slices never fight over its schema. The tree on disk:

```
<data_root>/presentations/<presentation_id>/presentation.json            # v2: counter, live nodes, archived nodes
<data_root>/presentations/<presentation_id>/variants/<variant_id>.json   # live variants
<data_root>/presentations/<presentation_id>/archive/<variant_id>.json    # archived variants (moved, never deleted)
<data_root>/presentations/<presentation_id>/scores/<score_id>.json       # linked documents stay where they are on archive
```

### Graph invariant (run on load and before and after every operation)

`validate_graph` (pure) is called by `Presentation` / `check_consistency` (so by **every load**), on the **candidate** manifest before any operation writes it (a candidate that
violates it never reaches the disk: `presentation_studio_corrupt_document`, "graph invariant refused before writing"), and again on what the disk holds after the write
(`graph_invalid` at `error`). Rules: ids and numbers unique across live **and** archived; `variant_counter` >= every number; the active variant exists and is **not** archived;
every parent exists; a live node has only live ancestors (a subtree is archived whole); no cycle; a child's number is above its parent's; `sources` exist and are older; at most
64 live and 128 archived nodes.

### Display numbers: monotonic, never reused

`variant_counter` is the last number handed out. **Allocation is durable before use**: `create` first writes the manifest with `variant_counter + 1` and no node, and only then
writes anything else. A crash after that leaves a *hole* in the numbers, never a reuse (proved by a real `Popen.kill` at that exact point). Archive and restore never touch the counter or a number; a restored
node keeps its number. A branch refused before the allocation (limits, an unsupported or corrupt linked document, a stale `expected_revision`) spends no number. Ceiling: 10 000 (`limit_reached`).

### Operations (Core service; one writer, one lock, one door to write a variant)

All operations take the Studio lock and write a variant only through `PresentationStudioService.persist_variant_locked` (the single door of Slice 10, which the Slice 06 pin
registry hooks), so concurrent creates serialise (distinct numbers) and an edit never interleaves with a branch. Every body is an exact object and may carry `actor`
(`user` default, `brain`) and `expected_revision` (the manifest revision; a mismatch is `presentation_studio_stale_revision`).

| Operation | Effect |
| --- | --- |
| **create** (`POST .../variants`) `{title, rationale?, source_variant_id?, activate?}` | Branch from the selected live variant (default: the active one). The new variant document is the source's, **deep-copied**: same scenes (same `scene_id`s, so compare/sync can align them), same values, controls, anchors, same prefab pins; it differs by `variant_id`, `variant_number`, `title`, `parent_variant_id`, `revision` (1) and timestamps (and `score_id` / `art_direction_id`, below). Linked documents are copied under new ids (below). **No prefab is published** and the prefab catalogue is not asked anything: the branch *shares* the scene pins (`docs/prefabs.md`, retention). `activate: true` makes it active in the same final manifest write. |
| **activate** (`POST .../variants/{id}/activate`) | Writes the manifest only (`active_variant_id`), after checking the target file reads. Idempotent (no write, no revision when already active). The undo rings are kept per variant (Slice 08, 8-variant LRU); nothing leaks between branches: each variant has its own file, score and ring. |
| **rename** (`POST .../variants/{id}/rename`) `{title}` | Rewrites that variant's file only (revision + 1). The number never changes. |
| **plan** (`POST .../variants/{id}/archive-plan`) | **Dry run, writes nothing.** Answers the exact set that archiving would touch: `affected: [{variant_id, variant_number, title}]` (the variant and all its descendants, by number), whether it holds the active variant, and, when nothing blocks it, a **confirmation token** bound to that set, to every title in it, to the presentation revision and to the chosen new active variant, valid 10 minutes, valid only in this process (HMAC with a per-process secret). |
| **archive** (`POST .../variants/{id}/archive`) `{confirmation, activate_variant_id?}` | Executes only with the token of a plan on the **current** state. No token / malformed: `presentation_studio_confirmation_required` (400). Forged, expired, from another set or revision, or the set / a title / the manifest changed since the plan: `presentation_studio_confirmation_stale` (409), nothing written. **The active variant cannot be archived** unless another live variant outside the set is chosen (`activate_variant_id`, switched in the same manifest write); the last live variant cannot be archived: `presentation_studio_active_variant_protected` (409). The files are **moved** to `archive/` (one `rename` each, never a copy-and-delete), then the manifest records the nodes as archived. `PresentationStudioHistory.drop_variant` is called for each archived variant (the Slice 08 entry condition). |
| **restore** (`POST .../variants/{id}/restore`) `{with_descendants?}` | Moves the file back and returns the node to the live set **with the archived ancestors it needs** (a live node never has an archived ancestor); archived descendants only with `with_descendants`. Needs no token (it destroys nothing). Refuses beyond 64 live nodes (`limit_reached`), a non-archived variant (`presentation_studio_not_archived`), a file that disagrees with its manifest entry (parent or number: `corrupt_document`). |
| **graph** (`GET .../graph[?archived=1&check=1]`) | The nodes (title, parent, number, rationale, creator, sources, preview, scene count, active, state), the counter, the active variant, the last reconciliation report; `archived=1` adds archived nodes (their titles come from the archive folder; an unreadable file is a `problem` on the node, never a missing node); `check=1` adds a full read-only report. |

There is no hard delete: "delete a branch" is archive. Emptying `archive/` is a human decision made with the Core stopped (see `docs/OPERATIONS.md`). Deleting a whole Presentation does not exist yet;
`PresentationStudioVariants.drop_presentation` is the hook that operation must call (Slice 08: `PresentationStudioHistory.drop_presentation`).

### Linked documents: deep copy through a registry, closed by default

A variant cites a score (`score_id`) and, with Slice 09, an art direction (`art_direction_id`). Two variants never share an editable document, so `create` copies each cited document under a new id
(`ScoreLink`: a new `psr_` id, the score's `variant_id` set to the branch, revision 1; item and cue ids are kept, they are unique *inside* a score and keeping them lets two variants be compared).
The kinds are a registry (`LinkedDocuments`, `LinkedKind.prepare` reads and validates, `LinkedCopy.write` writes): **the sources are read before a number is spent**, the copies are written after the
allocation and before the variant. **Closed by default**: a cited document whose kind has no registered copier refuses the branch (`presentation_studio_linked_document_unsupported`, 409) rather than
sharing it. A dangling link on the source (file absent) branches *without* it and says so (`linked[].status = missing_source`); a corrupt or newer source document refuses the branch (never "repaired" by dropping it).
Slice 09 plugs in by registering an `ArtDirectionLink` (same shape as `ScoreLink`) and its store area; tests use a fake kind to prove the registry suffices.

### Crash safety: order, recovery rule, report

There is no multi-file transaction, so each operation has an order and a rule for every state a kill can leave. **The manifest wins.** Every step is atomic (an atomic file replace or one `rename`).
Proved with a real subprocess killed (`Popen.kill`) at deterministic pause points (`checkpoint`):

| Operation | Order | Kill after... | State left and the deterministic result |
| --- | --- | --- | --- |
| create | allocate (manifest `counter + 1`) -> linked copies -> variant file -> manifest with the node | allocation | a hole in the numbers; nothing else |
| | | linked copy | orphan linked document: **reported** (`check`), kept; no node |
| | | variant file | orphan variant file: **reported** (`reconcile_orphans`, `warning`), kept, never adopted, not in the graph; its number is already spent |
| | | manifest | done |
| archive | move each file `variants/` -> `archive/` (leaves first) -> manifest | some files moved | files in the wrong folder for the manifest: **moved back** at the next start (`reconciled`, `warning`), the archive did not happen |
| | | manifest | done |
| restore | move each file `archive/` -> `variants/` -> manifest | some files moved | moved back to `archive/` at the next start |
| | | manifest | done |

`PresentationStudioVariants.start()` (called by Core after `PresentationStudioService.start()`) reconciles every Presentation (a manifest read and two directory listings each; it never raises) and each
mutating operation reconciles its Presentation first, once per process. Rules: a file in the wrong folder for its manifest state is moved to where the manifest puts it; a file nobody names is an **orphan**
(reported, never adopted, never deleted); the same id in both folders is a **duplicate** (reported, both left untouched; a restore refuses to replace); a node whose file is nowhere is **missing**
(`corrupt_document`, `error`, visible on every read). A read between the kill and the restart report can answer `corrupt_document` ("indexed variant is missing"): visible, never silent. Linked-document
orphans are only found by `check=1` (it reads every variant file): when a variant file is unreadable, what it cited is unknown, so nothing is declared orphan (`unverified`).

### Pins (the Slice 01a retention contract)

All variants of a scene share one prefab id and differ by `(id, version)` pins; a branch copies pins and never publishes. `PresentationStudioVariants.pin_index()` has the shape of the Slice 06
`PresentationStudioService.pin_index` (`{(presentation_id, variant_id): frozenset[(prefab_id, version)]}`) and covers **live and archived** variants (an archived variant can be restored, so its versions must not age out
of the retention window). The archive keeps its pins unchanged; the variant writes of `create` go through the single write door that the pin registry hooks (register before write).

### Routes

| Method | Core route | Control Center relay |
| --- | --- | --- |
| GET | `/v1/presentation-studio/presentations/{presentation_id}/graph` | `GET /api/presentation-studio/presentations/{presentation_id}/graph` |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants` | `POST /api/presentation-studio/presentations/{presentation_id}/variants`, actor forced to `user` |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/activate` | idem, actor forced to `user` |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/rename` | idem, actor forced to `user` |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/archive-plan` | idem, actor forced to `user` |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/archive` | idem, actor forced to `user`; **the relay refuses a body without `confirmation` itself** (400, Core not called) |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/restore` | idem, actor forced to `user` |

Bodies are tiny (<= 16 KiB) and exact. The relay is in `READ_GUARDED_ROUTES` (`/api/presentation-studio`): a prefab frame (`Origin: null`) or a foreign origin can neither read nor change the graph.

### Failures, events, diagnostics

New codes (also in the table of the Presentation contract): `presentation_studio_active_variant_protected` (409), `presentation_studio_confirmation_required` (400), `presentation_studio_confirmation_stale` (409),
`presentation_studio_not_archived` (409), `presentation_studio_linked_document_unsupported` (409). The others are reused (`unknown_variant`, `stale_revision`, `limit_reached`, `corrupt_document`, `invalid`).
Conversation event: **one** type, `system.presentation_studio.variant_changed` (the canonical name of `09-canonical-names.md`), actor `system`, instant, diagnostic, content **forbidden**, with `op`
= `created` | `switched` | `renamed` | `archived` | `restored` and the attributes `presentation_id`, `variant_id`, `variant_number`, `source` (the actor), `revision`, `count` (variants touched by an archive or restore), `status`.
A title and a rationale are user content: they are never an attribute, never in an event, a trace or the relay journal. Registered in Python (`conversation_events.py`) and in `control_center_timeline.js`
(a dot on the left rail). Diagnostics `core.presentation_studio.{variant_created,variant_switched,variant_renamed,variant_archived,variant_restored,archive_planned}` at `info` (ids, numbers, counts, `event_recorded`),
`reconciled` and `reconcile_orphans` at `warning` (`error` when a node's file is missing), `branch_failed`, `archive_failed`, `restore_failed`, `reconcile_failed`, `graph_invalid` at `error`, `event_failed` and
`history_drop_failed` at `warning`.

### Seams and entry conditions for other Slices

| Seam | Owner |
| --- | --- |
| art direction document copied on branch: register an `ArtDirectionLink` and add its folder to the store's `list_documents` areas and to the pin/orphan checks; until then a variant citing `art_direction_id` cannot be branched | Slice 09 merge |
| Slice 06 `StudioPinRegistry.rebuild` reads `PresentationStudioService.pin_index`, which lists live variants only: at merge, make it also take `PresentationStudioVariants.pin_index()` (live + archived) | Slice 06 merge |
| thumbnail / `preview_id`: set by the explorer; no operation writes it yet | Slice 18 |
| scene-local variants live *inside* a variant document and are copied with it (a branch copies them as part of the variant); their own graph is not this one | Slice 17 |
| `sources` with several parents (mix) and per-dimension provenance | Slice 19 |
| the MCP tool `presentation_variant` (list / create / switch / rename / archive with `confirm`) must call plan first and pass the token; it never builds one | Slice 21 |
| the UI shows `plan.affected` (numbers and titles) before it asks for confirmation, and offers `suggested_active` when the active variant is in the set | Slice 18 |

### Decisions and limits (recorded)

- **Archive, not delete.** Repo `CLAUDE.md` forbids destroying data without a copy; archive is one `rename` per file, reversible. 128 archived nodes at most (the manifest must stay under 256 KiB with a 600-character rationale on each); beyond that `limit_reached` says to restore or to clear `archive/` by hand.
- **Manifest v2, variant unchanged.** The node metadata is in the manifest because creation is atomic with indexing (the manifest is the commit point) and the graph validates from one document.
- **One event type** (`variant_changed` with `op`), the canonical name, not five types.
- **Confirmation tokens die with the process** (a per-process secret): after a Core restart the human plans again. Cheap, and a token can never outlive what it described.
- **Not done here**: UI (Slice 18), scene-local variants (17), compare / mix (19), MCP (21), a hard delete, deleting a whole Presentation.

## Playback roles and speech authority (Level 3, Slice 01c, decision A)

Status: decided by the Project Manager on 2026-10-08 under the Human's standing autonomy; implemented as a pure helper, no service.
Code: `jarvis/domain/presentation_studio_roles.py`. Conformance: `tests/unit/test_presentation_studio_roles.py`,
`tests/unit/test_board_service.py` (transient source). Consumers: Slice 12 (playback), 13 (cues), 14 (Jarvis presenter), 15 (rehearsal).

**Decision A.** A Jarvis-presented run, and a rehearsal in which Jarvis speaks, run **outside** the PRESENTATION interaction mode
(ASSISTANT, user label SIMPLE). The authority matrix, `LOCKED_DECISIONS` (D01..D14) and `PresentationSpeechGate` are **not changed**: outside PRESENTATION the
gate is inert (`mode_not_presentation`, `jarvis/runtime/presentation_speech_gate.py`). Option B (a `SCORE_SPEECH` situation) is rejected: it would amend a critical-tier authority matrix to
save a mode switch that already hot-switches (D15). The user-presenter sidekick stays in PRESENTATION and Jarvis stays silent there.

### Role to mode table (`requirements(role, jarvis_speaks=)`)

| Role | Mode | Ambient lane | Speech policy | Progress source |
| --- | --- | --- | --- | --- |
| `user_presenter` | PRESENTATION | `armed_cues_only` (Slice 13; OpenAI ambient stack only, else deaf and only explicit address works) | `presentation_silence`: the matrix as is; Jarvis acts only through authorized, reversible visual cue actions (Slice 13) | cues + user navigation |
| `jarvis_presenter` | ASSISTANT | `off` (structural: the PRESENTATION session is stopped, "nothing of the room survives") | `score_lines` | score-driven: speech chunk progress and timers (Slice 14), never ambient text |
| `rehearsal`, Jarvis silent (default) | PRESENTATION | `armed_cues_only` | `presentation_silence` | cues + user navigation |
| `rehearsal`, `jarvis_speaks=True` | ASSISTANT | `off` | `score_lines` | as `jarvis_presenter` |

Invariant (tested): score lines are spoken **iff** the mode is ASSISTANT **iff** the ambient lane is off. `user_presenter` with a speaking Jarvis and `jarvis_presenter` with a silent Jarvis are refused (`ValueError`). `MEETING` is never a studio mode.
Consequence to tell the Human: **rehearsing with Jarvis speaking cannot rehearse ambient cue following** (the lane is off); cue following is rehearsed with Jarvis silent.

### Who may switch the mode, and when

Only `SwitchOrigin.EXPLICIT_USER_REQUEST` (a voice turn admitted as addressed that asks to present or rehearse with Jarvis, or a Control Center action) may switch the mode (`mode_switch_allowed`, `plan_mode_entry`).
Ambient text, score or scene content, the brain acting on its own initiative, and system replays (Core start, Board restore, retries) are refused with `mode_switch_origin_refused`; the allow-list is closed, a new origin is refused until added on purpose.
The switch is made in the Core service that owns the run (Slice 12/14), never from Voice, and never from the cue follower (it emits typed `cue_satisfied` only, R5).

### Switch and restore protocol (existing API, nothing new in `InteractionModeService`)

1. **Enter.** `plan_mode_entry(role, origin, current_mode)`; if `switch_needed`: `state, disposition = await interaction_mode.request(target, source="presentation_studio_run")`
   (`jarvis/core/interaction_mode.py`, `request`). Only when `disposition` is `APPLIED` does the run remember `previous_mode`, `state.epoch` and `state.revision`; `UNCHANGED` remembers nothing (nothing to restore).
   A refusal (`InteractionModeError`) is surfaced and the run does not start.
2. **Hot switch, no restart (D15, verified).** `request` publishes `interaction.mode.changed` on the Core bus after releasing its lock; Voice's `InteractionModeObserver` applies it (epoch first, then revision); the mode is not in `VoiceComposition.configuration_id`, so `VoiceSwitchCoordinator` never restarts Voice.
   The PRESENTATION session is stopped on PRESENTATION to ASSISTANT (ambient lane, working set and audio session closed, wake stack resumed) and a new one is composed on the way back (`presentation_runtime.py` header).
3. **The source is transient.** `source="presentation_studio_run"` (`STUDIO_RUN_MODE_SOURCE`) is in `TRANSIENT_MODE_SOURCES`; `BoardService._persist_mode` skips it (like `board_restore` / `board_switch`, `NON_PERSISTED_SOURCES`). Any other source (e.g. `protocol`) would **overwrite the Board's stored preference** (`set_interaction_mode`, origin `USER`), and a Core restart mid-run would keep the temporary mode. A run never touches the Board preference.
4. **Watch.** The run follows `interaction.mode.changed` and classifies each event with `classify_mode_event(applied_epoch, applied_revision, event_*)`: `own_or_stale` (ignore), `foreign_change` (the user, a Board switch or a retry changed the mode during the run), `core_restarted` (different epoch).
5. **Leave.** On completion, stop or crash (every exit path, in a `finally`): `decide_restore(...)` returns
   `restore` (`request(previous_mode, source="presentation_studio_run")`), `none` (no switch applied, or already the previous mode), `leave_user_choice` (the revision moved: **the user's choice wins, nothing is restored**, the remembered mode is dropped) or `core_restarted` (no restore).
6. **Manual change during a run.** A `foreign_change` stops a Jarvis-presenter run: if the user went to PRESENTATION, scripted lines would now be withheld. The run stops speaking, says so on screen, and does not force the mode back.

### Failure modes

| Failure | Behaviour |
| --- | --- |
| mode service refuses or raises on enter | the run does not start; visible error with the code; mode unchanged |
| switch applied, then the run crashes | `finally` restore; if the restore itself fails, a visible error names the mode Jarvis is left in and the stored preference; the Control Center selector (source `control_center`) fixes it; the Board preference was never changed |
| restore refused or raises | traced error `presentation_studio.mode_restore_failed`, visible on screen, mode left as is; no retry loop |
| Core restarts mid-run | playback state is in memory (R6) and is gone; `BoardService.restore_interaction_mode` reapplies the stored per-Board preference (`source="board_restore"`); a Board never set stays at the default ASSISTANT and the Control Center replays its legacy setting. Deterministic: stored preference or default, never the temporary mode |
| Voice restarts mid-run | `follow_core_mode` re-adopts the snapshot on every subscription; no run state lives in Voice |
| the user changes the mode or switches Board during the run | `foreign_change` (above) |
| PRESENTATION unavailable on the voice architecture (`legacy`, `duplex`: `presentation_architecture_unsupported`) | `user_presenter` and silent rehearsal cannot start; the refusal reason is shown. `jarvis_presenter` is unaffected (ASSISTANT) |
| Control Center replays its own setting (`save_retry`) during a run | read as `foreign_change` (known limit) |

### What the Human sees and hears

Entering a Jarvis run is shown **on screen** (the run banner of Slice 12/18 must say it): "Jarvis presents: mode set to SIMPLE for this run, restored to <previous> at the end; your stored preference is unchanged". The mode selector shows the effective mode.
Nothing is spoken for the switch itself. At the end the restored mode is shown; after a `foreign_change` the banner says "run stopped: mode changed by you". The audience-facing behaviour is: Jarvis speaks only the score's lines, and only while the run is active.

### Scripted line: the exact `announce_notice` call (Slice 14)

```python
notice = ScoreLineNotice(text, run_id=run_id)   # jarvis/domain/presentation_studio_roles.py, validates before sending
spoken = await brain.announce_notice(notice.text, **notice.call_kwargs())
# call_kwargs() == {"kind": SpeechKind.PROGRESS, "supersedes_key": "presentation_studio:<run_id>", "ttl_s": 30.0}
```

| Argument | Value | Why (verified in code) |
| --- | --- | --- |
| `text` | the score line, as written | never rephrased (`announce_notice` docstring, Decision 13); `[pas-pour-moi]` and empty text are dropped silently by Core, so `ScoreLineNotice` refuses them |
| `kind` | `SpeechKind.PROGRESS` | `NOTICE_KINDS` = ack/progress/result (`jarvis/domain/brain_notice.py`); `error` and `question` are refused (safety kinds). `progress` is transient: it gets a deadline, is **not** retained as an outcome nor added to `known_public_facts` (a `result` would be, and would be handed back to the brain when stale), and dies as `stale_source` when a new intention starts (`SpeechScheduler._eligibility`). That keeps a rehearsal non-durable and makes user interruption clean |
| `supersedes_key` | `presentation_studio:<run_id>` | one speech slot per run: a later line replaces an unstarted earlier one (seek, skip), never another run's. The presenter issues **one line at a time** (the next after the previous ended), so the slot never eats a queued next line |
| `ttl_s` | 30.0 default, range [1, 3600] | counted from creation in Core; covers queue wait only because lines are issued just in time |
| `verbatim` | no such argument | verbatim is intrinsic to `announce_notice` |
| `work_id`, `conversation_id` | omitted | `work_id` would wire the line into the brain work-dependency logic; the conversation is the foreground one |

`announce_notice` returns `False` when nothing was published (`no_current_source`: no intention was ever activated in the conversation, e.g. just after a Core restart; `invalid_notice`; stopping; inactive Board; withheld by policy). The presenter treats `False` as a **visible failure** (pause the run, say why on screen), never as success.
Admission outside PRESENTATION is proven by `test_a_score_line_is_admitted_outside_presentation`; the same line in PRESENTATION is withheld (`test_the_same_line_stays_withheld_in_presentation_so_the_role_needs_the_other_mode`).

### Interruption, stop and pause

- **Explicit user address** (any admitted user turn in ASSISTANT): the bridge takes the floor (`SpeechScheduler.note_floor_taken` / `note_interruption`): the active line is cut and its chain blocked (`interrupted_chain`), queued lines freeze, then die as `stale_source` when Core activates the new intention. Nothing is retained or re-said by the brain (transient kind).
  The presenter treats `mouth.floor.taken` / `mouth.speech.interrupted` (or the new intention) as **pause**, never auto-resumes: the user's turn is answered, then the presenter resumes only on an explicit "continue" (a new `EXPLICIT_USER_REQUEST`).
- **Stop** (user "stop", Escape, run end): the presenter stops issuing lines, drops its pending timers, restores the mode (protocol above). A queued line not yet started carries a <= 30 s deadline and the next intention kills it; a line mid-sentence is cut by the barge-in path when the user speaks. Core has no "cancel this notice" call; none is added for this.
- **Pause** (user "pause", pause-edit-resume in rehearsal): no new line is issued; the line in flight ends naturally unless the pause came with a barge-in. Resume re-issues the **current line from its start** (no mid-sentence resume: `played_ms` is a read-only projection, not a seek).
- Ambient speech never pauses, stops or resumes anything in a Jarvis run: the lane is off.

Not decided here: locked-sequence timing and chunk-progress sync (Slice 14), cue binding (Slice 13), the run banner copy (Slices 12/18), and the audible end-to-end proof (Human check, needs a real voice stack).

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
- The prefab library caps versions per id (64 live) and ids (512) and has no deletion. **Decided by Slice 01a** ([prefabs.md](prefabs.md#retention-of-studio-scene-sources)): a Tier-3 source edit goes through `PrefabDraftCoalescer` (one burst, one version); only ids `presentation-studio.*` are retained, and Core may *archive* (move, never delete) the versions of such an id that nothing pins. "Pins" are asked of a `PrefabPinRegistry` that **the Studio implements** (variants, scene-local variants, templates, scene objects, scene documents, undo stack) and passes to `PrefabService`; with no registry nothing is archived and the hard caps apply. Studio code must therefore (1) name its scene sources `presentation-studio.<...>`, (2) let variants share the scene's id and differ by `(id, version)` pin, forking a new id only when sources diverge, (3) register every pin it writes in the registry before the pinned version can age out of the last 16, (4) turn the typed refusals `version_limit` / `id_limit` into a visible message offering a fork under a new id. Slice 06 wires the registry.
- In PRESENTATION mode a scripted Jarvis line is withheld by the speech gate. Decided (Slice 01c, option A): the Jarvis presenter, and a rehearsal in which Jarvis speaks, run outside PRESENTATION; the policy is not amended.
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
| Semantic edit API (vocabulary, tiers, preconditions, transactions, preview/commit, undo record, actors, relay, events) | 0-1 | 3 (**done**, Slice 05) |
| Persistence and undo (durable commit, restart recovery, bounded ring, typed history results, pins) | 1-2 | 3 (**done**, Slice 08) |
| Variant graph (nodes, numbers, branch, switch, archive / restore under a token, crash reconciliation, linked documents, pins) | 0-1 | 3 (**done**, Slice 16) |
| hot reload, DA, playback, cue matching, rehearsal, compare/mix, promotion, agent operations | 0-1 | 3 each |

There is no `docs/CONTEXT.md` or documentation-level registry in this repository: the level of a concept is stated in its page header (`Status: Level N`), as in [presentation-mode.md](presentation-mode.md).
