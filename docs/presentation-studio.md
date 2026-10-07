# Presentation Studio - concepts, owner map and status

Entry page for the Presentation Studio (handoff `jarvis-interactive-presentation-studio`): a structured, editable, rehearsable and presentable **Presentation** that Jarvis can author and
deliver. It **holds no behaviour contract yet**: it names the canonical concepts, says who will own each, and tracks status per section. When a section gets its own contract page or code,
that owner wins and this row is updated in the same commit.

Status: **Level 2 skeleton** for the page as a whole; the *Presentation contract* section below is **Level 3** (Slice 02: domain, port, file store, Core service, Core routes, typed client, conformance tests) and so is the *Scene and control contract* (Slice 04: logical scene, curated controls, discovery, prefab compatibility) and the *Semantic edit contract* (Slice 05: one edit API for voice and GUI) and the *Score and cue contract* (Slice 10: tracks, silence, cues, closed actions, locked sequences, score store and routes) and the *Art direction contract* (Slice 09: structured DA profile, provenance, contrast in numbers, deterministic fallback / divergence / derivation, theme mapping, `require_art_direction`; its authoring policy for Slice 11 follows it) and the *Playback roles and speech authority* contract (Slice 01c: role -> mode, switch/restore, scripted-line arguments).
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
| Art direction | structured profile with provenance (provided / inferred / generated), contrast checked in numbers, theme mapping, deterministic fallback, divergent candidates, derivation from extracted signals | `jarvis/domain/presentation_studio_art_direction.py`, `jarvis/domain/presentation_studio_art_direction_authoring.py` (stored by the Slice 02 store and service) | [Art direction contract](#art-direction-contract-level-3) and [authoring policy](#art-direction-authoring-policy-for-slice-11) below, Slice 09 | **implemented (Level 3)** (the LLM-driven authoring is Slices 11 and 21) |
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
| `Presentation` (`presentation.json`) | `presentation_id` `pst_<32 hex>`, `title` (<= 80, one printable line), `active_variant_id`, `variant_counter` (last number handed out, monotone, never reused), the variant index `[{variant_id, variant_number}]` (1..64), `resources` (<= 64, `{kind, locator, title}`), `revision`, `created_at`, `updated_at` |
| `PresentationVariant` (`variants/<variant_id>.json`) | `variant_id` `psv_<32 hex>`, `variant_number`, `title`, `parent_variant_id` (the only graph trace, cycles refused; graph operations are Slice 16), ordered `scenes` (<= 64) of `{scene_id: pss_<12 hex>, prefab: {id, version}}`, `art_direction_id` (`psd_<12 hex>` or null; the profile is behind it, see *Art direction contract*), `score_id` (`psr_<12 hex>` or null; the score document is behind it, see *Score and cue contract*), `revision`, timestamps |

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

`PresentationStudioService` (`jarvis/core/presentation_studio_service.py`) is the sole authority: `create`, `get`, `get_variant`, `list_presentations`, `save_presentation`, `save_variant`, `validate`, `describe_scene` (Slice 04), the score methods (Slice 10) and the art direction methods (Slice 09). Core is the single writer; writes and reads take the same lock (a read never meets an atomic replace in flight; the store also re-inspects up to 4 times if a save from elsewhere lands between its inspection and open);
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
| GET | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/art-direction` | `{art_direction}` (Slice 09, see *Art direction contract*); 404 `presentation_studio_unknown_art_direction` when the variant has none |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/art-direction` | `{expected_variant_revision, profile}` -> 201 `{art_direction}` (+ `relinked_from` when a dangling link is repaired); the variant receives `art_direction_id` (Slice 09) |
| PUT | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/art-direction` | `{expected_revision, profile}` (whole replacement) -> `{art_direction}` (Slice 09) |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/art-direction/fallback` | `{expected_variant_revision, seed_context?}` -> 201 `{art_direction}`, the deterministic generated fallback (`provenance.fallback`) (Slice 09) |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/art-direction/candidates` | `{count 1..6, seed_context?}` -> `{base, base_profile, candidates}`; computed, nothing written (Slice 09) |

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

Diagnostics `core.presentation_studio.{started,swept,created,saved,listed,validated,refused,scenes_checked,scene_described,score_loaded,score_relinked,art_direction_loaded,art_direction_relinked,art_direction_candidates,art_direction_resolved}` at `info` (ids, codes, counts; never titles, locators or content), and at `error`
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
| semantic edits, `expected_revision` as the edit basis, actor, relay | **done, Slice 05** (*Semantic edit contract*) |
| debounced autosave, undo/redo ring (memory only) | Slice 08 |
| art direction content behind `art_direction_id` | **done, Slice 09** (`art_directions/<art_direction_id>.json`) |
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

## Art direction contract (Level 3)

Status: implemented by Slice 09 (the **deterministic half** of art direction). Conformance: `tests/unit/test_presentation_studio_art_direction{,_authoring,_service}.py`, store/route/client rows in
`test_presentation_studio_{store,routes}.py`, data `tests/fakes/presentation_studio_art_direction.py` and the frozen stored document `tests/fixtures/presentation_studio/art_direction.v1.json`.
Owners: `jarvis/domain/presentation_studio_art_direction.py` (pure: profile, validation, theme mapping, `require_art_direction`) and
`jarvis/domain/presentation_studio_art_direction_authoring.py` (pure: fallback, divergence, derivation from signals) and `jarvis/domain/presentation_studio_art_direction_vocab.py` (pure: closed vocabularies, bounds, token parsers, contrast maths; re-exported by the first); stored and served by the Slice 02 store, service and routes (`art_directions/<art_direction_id>.json`, same atomic write, same single writer).

An **art direction (DA)** is structured **data**, never code. It says how a presentation looks (palette, type, space, shape, imagery, data, motion), where that look came from, and how sure we are. It is consumed by scene authoring (Slice 11), playback (Slice 12)
and variant comparison and mixing (Slice 19). The LLM-driven half (inspect the project, ask the one question that matters, write divergent candidates by prompt) is Slices 11 and 21; this Slice delivers the contract, the validators, the deterministic generators and the seams they plug into
(see *Art direction authoring policy*).

### Shape

| Piece | Holds |
| --- | --- |
| `ArtDirection` (`art_directions/<art_direction_id>.json`, `art_direction_id` `psd_<12 hex>`) | `presentation_id`, `variant_id`, `profile`, own `revision`, `created_at`, `updated_at`; `schema` `jarvis.presentation_studio.art_direction`, `schema_version` 1, `UPGRADES[art_direction] = {}` |
| `ArtDirectionProfile` | `name` (<= 80, one printable line), `provenance`, `palette`, `typography`, `spacing`, `shapes`, `imagery`, `dataviz`, `motion`, `references` (<= 12) |
| `Provenance` | `origin` (`provided` / `inferred` / `generated`) for the whole profile; `sections` (a map from a section to its own origin, for a mixed DA: `palette`, `typography`, `spacing`, `shapes`, `imagery`, `dataviz`, `motion`); `fallback` (true only with origin `generated`); `confidence` 0..1 (finite, never a bool, stored with 3 decimals); `notes` (<= 8, each <= 200) |
| `Palette` | `background`, `surface`, `text`, `muted`, `accent` (`#rrggbb`), `accent_alt` (colour or null), `surface_opacity` 30..100, `gradients` (<= 6) |
| `Gradient` | `gradient_id` (slug), `kind` (`linear` / `radial`), `angle` 0..359 (0 for radial), `stops` (2..5, strictly increasing `at` 0..100, each a colour), `text_token` (`text` / `background`: the palette colour set over the gradient) |
| `Typography` | `heading`, `body` = `{stack, preferred}`; `text_size`, `scale_ratio`, `heading_weight`, `body_weight`, `label_case` |
| `Spacing` | `density`, `margin` |
| `Shapes` | `radius_px` 0..48, `stroke_px` 0..6, `elevation` |
| `Imagery` | `photo`, `illustration`, `icons`, `treatment`, `motifs` (<= 6 plain words, each <= 40) |
| `DataViz` | `mode`, `series` (3..8 distinct colours), `grid`, `labels`, `emphasis` |
| `Motion` | `tempo`, `enter_ms`, `exit_ms`, `emphasis_ms`, `easing`, `stagger_ms`, `transition`, `reduced_motion` |

References are `{kind, locator, title}` (`ResourceReference`, reused, with the Slice 02 locator hygiene). They are **locators only**: a DA never stores or copies a file, a folder or a font. On top of the hygiene gate, a DA locator is refused when it has the shape of an
injection: a CSS function at the start of a word (`url(`, `expression(`, `var(`, `calc(`, `attr(`, `image-set(`, `env(`), `@import`, `javascript:` or `vbscript:` at the start of a word, or one of `< > { } "` and the backtick, raw or percent-decoded, so a reference could never become a
style fragment even if someone one day interpolated it. Nothing else is refused: `;` and `'` in a URL, `data:` inside a word (`metadata:v2`), `myenv(1)` or `Function_(mathematics)` are legitimate locators.

### Closed vocabularies (a value outside is refused, naming the field)

| Field | Members |
| --- | --- |
| `provenance.origin`, section origins | `provided`, `inferred`, `generated` |
| `gradient.kind` | `linear`, `radial` |
| `gradient.text_token` | `text`, `background` |
| `typography.*.stack` | `system_sans`, `humanist_sans`, `geometric_sans`, `rounded_sans`, `condensed_sans`, `transitional_serif`, `old_style_serif`, `slab_serif`, `system_mono` |
| `typography.text_size` | `compact`, `normal`, `large`, `xlarge` (scale 0.9, 1, 1.15, 1.3) |
| `typography.scale_ratio` | `tight`, `balanced`, `comfortable`, `dramatic` |
| `typography.heading_weight` / `body_weight` | 400, 500, 600, 700, 800 / 300, 400, 500 |
| `typography.label_case` | `none`, `uppercase` |
| `spacing.density` | `compact`, `balanced`, `airy` (gap 4, 6, 10 px) |
| `spacing.margin` | `narrow`, `standard`, `wide` |
| `shapes.elevation` | `flat`, `soft`, `dramatic` |
| `imagery.photo` | `none`, `documentary`, `editorial`, `product`, `abstract` |
| `imagery.illustration` | `none`, `flat`, `line`, `isometric`, `hand_drawn`, `geometric` |
| `imagery.icons` | `outline`, `filled`, `duotone`, `rounded`, `sharp` |
| `imagery.treatment` | `natural`, `duotone`, `monochrome`, `high_contrast` |
| `dataviz.mode` | `categorical`, `sequential`, `diverging` |
| `dataviz.grid` | `none`, `subtle`, `full` |
| `dataviz.labels` | `direct`, `legend` |
| `dataviz.emphasis` | `single_accent`, `multi` |
| `motion.tempo` | `calm`, `measured`, `lively` |
| `motion.enter_ms` / `exit_ms` / `emphasis_ms` | 0, 120, 200, 320, 480, 720 |
| `motion.stagger_ms` | 0, 40, 80, 120 |
| `motion.easing` | `linear`, `ease_out`, `ease_in_out`, `standard`, `emphasized`, `snappy` (each a constant cubic-bezier of the module) |
| `motion.transition` | `none`, `fade`, `slide`, `scale`, `wipe` |
| `motion.reduced_motion` (**required**) | `fade_only`, `static` (never "keep the motion") |

Font stacks are **system** stacks only: the prefab frame has no network and no embedded font (CSP `font-src data:`), so a web font could never load. A stack's CSS text is a constant of the module; the only received text that can reach a font declaration is
`preferred`, a *declared* family such as `Inter` or `Source Sans 3` (letters, digits, single spaces or hyphens, <= 40, ASCII), written first and in quotes, then the closed stack.

### Contrast, in numbers

The palette is checked at construction with the WCAG 2.x ratio (`contrast_ratio`, luminance with the 0.03928 threshold); a failing palette is refused and the message names the pair, its measured ratio and the threshold. The surface is judged where it is **seen**: composited on
the background at `surface_opacity` (`Palette.effective_surface()`). `Palette.contrast_report()` lists every pair.

| Pair | Needs |
| --- | --- |
| `text` on `background`, `text` on the effective surface | 4.5 : 1 |
| `muted` on `background`, `muted` on the effective surface | 3 : 1 |
| `accent`, `accent_alt` on `background` | 3 : 1 |
| `accent`, `accent_alt` on the effective surface | 3 : 1 |
| `text` on `--jv-wash` (the text colour at 9% over the background; the fill behind a button or a chip), and on the wash over the effective surface | 4.5 : 1 (so the boundary-legal `#767676` text on white, 4.09:1 on the wash, is refused; `#6e6e6e`, 4.55:1, passes) |
| the `text_token` colour along **the whole ramp** of every gradient: each stop and `GRADIENT_SEGMENT_STEPS` = 8 steps per segment, linear in sRGB as a browser renders it (`Gradient.samples()`, at most 4 x 9 measures); a gradient from `#0a8465` to `#e71610` passes at both stops under black text (4.5 : 1) and is 2.92 : 1 at its middle, so it is refused | 4.5 : 1 |
| every `dataviz.series` colour on `background` | 3 : 1 (and the series are distinct) |

### No raw CSS, JS or URL, by construction

No field accepts CSS. A colour is `#rrggbb` (a name, `rgb()`, `var()`, `url()`, a 3-digit form or anything with a trailing character is refused; upper case is folded to lower case). A length is an integer in px, or, when read from an agent signal, a number and a unit from the closed
set `px` / `rem` / `em` (`parse_length`, clamped to 48 px). Everything else is a member of a vocabulary. So `url()`, `expression()`, `@import`, `var()` cycles and `javascript:` are not blocked by a deny list that someone could forget to extend: they are simply not a colour, an integer,
a member or a plain name. Tests sweep **every leaf** of a full profile with a list of hostile strings and require a refusal everywhere except the declared free-text fields.

CSS is only ever *produced*, from validated tokens: `gradient_css(gradient)`, `easing_css(easing)` and `to_theme_variables()`. **Free text** (`name`, `notes`, `motifs`, reference titles; `FREE_TEXT_FIELDS`) is **untrusted data**: printable, bounded, stored verbatim, never interpreted and never copied into a
CSS value (a test builds two profiles that differ only by injected text and requires identical theme output). Slice 11 must treat `notes` and `motifs` as content to show, never as an instruction. `FREE_TEXT_FIELDS`, `ID_FIELDS`, `TOKEN_FIELDS` and `STRUCTURE_FIELDS` classify **every** field of the model;
a test fails when a field is added without being classified, whatever its annotation, and when a field is annotated `Any`, `object`, `dict` or `bytes`.

### Theme mapping: nothing new executable

`profile.to_theme()` returns exactly the five keys the prefab host already applies (`accent`, `text`, `muted`, `surface`, `scale`: `shim.js` `THEME_VARS`; delivered by `host.update`, no new channel). `profile.to_theme_variables()` returns the Studio's view of the shell tokens, restricted to
`ALLOWED_THEME_VARIABLES` = `--jv-accent`, `--jv-text`, `--jv-muted`, `--jv-surface`, `--jv-scale`, `--jv-font`, `--jv-radius`, `--jv-gap`, `--jv-ground`, `--jv-veil`, `--jv-title`, `--jv-link`, `--jv-body`, `--jv-edge`, `--jv-wash`. A test requires that set to be declared in
`jarvis/prefabs/runtime/shell.css` (`:root`), and every value to match a closed token grammar (`#rrggbb`, `rgba(n,n,n,0.nn)`, a number, `Npx`, a quoted plain family followed by a closed stack). The frame applies the first five today; the others are the contract for a future shell extension
(a protocol change, not part of this Slice) and for scene authors that set them as values. Gradients, easing and the motion language are data for Slices 11 and 12 and are **not** written as theme variables. The mapping is deterministic.

### Provenance

`origin` is `provided` (the user gave a design system or said so), `inferred` (derived from inspectable project context) or `generated` (invented). `sections` lets one DA say that its palette is `provided` while its motion is `generated`. `fallback: true` marks a profile
produced only because nothing else existed (`generate_fallback_profile`): it is a real, usable DA, flagged so that a later better source can replace it, and `require_art_direction(...).is_fallback` says so. `confidence` is how sure the author is, 0..1.

### Generators (deterministic, no model, no I/O)

| Function | Does |
| --- | --- |
| `generate_fallback_profile(seed_context)` | `SeedContext` = `{title, audience, purpose, tone[]}` (all optional; <= 200 characters; <= 8 tone words of <= 24). A closed French and English lexicon picks one of seven directions (`corporate_calm`, `editorial_bold`, `technical_dark`, `playful_bright`, `luxury_minimal`, `warm_human`, `bold_contrast`); with no known word the SHA-256 of the folded context decides. Same input, same profile, in any process. Provenance `generated`, `fallback: true`, `confidence` 0.5 (wording match) or 0.3 |
| `diverge(profile, n)` | `n` in 1..6 candidates from the 21 direction x accent combinations, chosen by farthest-point selection on `profile_distance` so that each differs from the start **and** from the others by at least `MIN_DIVERGENCE` = 0.2. Axes and weights (`AXES`): palette 0.30, typography 0.20, shape 0.15, motion 0.15, density 0.10, imagery 0.10. Deterministic; the same call extends a shorter call |
| `derive_from_signals(signals)` | `DesignSignals` = `{sources[], colors[{value, role?, weight?}], fonts[{family, role?}], radii[], mentions[]}`: **already extracted** by an agent's tools (this module reads nothing). Role hints win; otherwise luminance and saturation decide. A palette that fails contrast is **repaired** (never refused) and the profile stays valid. Provenance `inferred` for the sections that used a signal (palette, typography, shapes), `generated` for the gaps filled from the direction the mentions point to; when **only mentions** were usable no section is inferred, so the profile is `generated` (not `fallback`), `confidence` 0.3; `references` = `sources`; `confidence` 0.35 + 0.15 per inferred section (+0.05 with sources), at most 0.85. No usable signal: the flagged fallback, keeping the sources |

Signal text is untrusted: a `mentions` string only selects from the lexicon and is never copied into the profile; a font family becomes `preferred` only as a plain name and also selects the closest closed stack (`classify_family`).

### Every serious variant resolves a DA

`require_art_direction(variant, profile_store, serious=True)` (pure; the Core method `PresentationStudioService.require_art_direction` loads the document and calls it):

| Variant | `serious=True` (serious, or any generated variant) | `serious=False` (exploratory draft) |
| --- | --- | --- |
| `art_direction_id` set and the document found | `resolved` | `resolved` |
| `art_direction_id` null | refusal `presentation_studio_art_direction_required` (409) | `missing` |
| `art_direction_id` set, document absent | refusal `presentation_studio_unknown_art_direction` (404) | `dangling` |

A fallback DA resolves (it is a DA) and reports `is_fallback`. A document that names another variant, presentation or id is `corrupt_document` in both modes, and an unreadable or newer file is never downgraded to `dangling`. `serious` must be a real boolean.
Which variants are serious is the caller's decision (the authoring planner, Slice 11); a generated variant is always serious.

### Routes, persistence, failures

The five routes are tabled with the others in *Presentation contract* (`.../variants/{variant_id}/art-direction`: GET, POST, PUT; `.../art-direction/fallback` POST; `.../art-direction/candidates` POST). Bodies: create `{expected_variant_revision, profile}`, save `{expected_revision, profile}`,
fallback `{expected_variant_revision, seed_context?}`, candidates `{count, seed_context?}` (computed, **nothing written**, POST only because it carries a body).

- **Candidates are not stored.** `diverge` is deterministic, so a candidate is recomputed from its base; adopting one is a normal `POST` (create) or `PUT` (save) of its content. This avoids an unbounded pile of unlinked files and a delete path.
- **Revisions**: the DA has its own `revision`; a stale `expected_revision` is `stale_revision` and nothing is written. Saving a DA does not touch the variant file, so **it does not bump the variant `revision` or `updated_at`**: a reader that caches or compares by variant revision (the Slice 07 relay and inspector, Slice 12 playback) will not see a DA change and must compare the art direction's **own** `revision` (`GET .../art-direction`). Creating one writes the **DA first, then the variant** (which gets `art_direction_id` and `revision + 1`): a crash between the two leaves an orphan,
  unreferenced file, harmless and left in place (never deleted).
- **Link ownership**: `art_direction_id` belongs to the art direction routes. `PUT .../variants/{id}` cannot attach, swap or clear it (`presentation_studio_invalid`; the body keeps the stored value). The guard sits in `_persist_variant`, the one place that writes a variant file, with its own flag
  (`relink_art_direction`), so it covers `save_variant`, the Slice 05 edit API and every future writer. This **tightens Slice 02**, which let a variant save attach any well-formed `psd_` id; a variant that already carries such a made-up id is repaired by the next create.
- **Dangling link repair**: if the stored id names an absent file, `POST` (or `POST .../fallback`) replaces the link: the answer carries `relinked_from` and Core logs `core.presentation_studio.art_direction_relinked` at `warning`. A file that exists but is corrupt or newer is never replaced; a usable one is `already_exists`.
- **Refusals**: `presentation_studio_unknown_art_direction` (404), `presentation_studio_art_direction_required` (409), plus `invalid` (a contrast, vocabulary, bound, hygiene or injection-shape refusal names its field), `runtime_state_refused`, `stale_revision`, `already_exists`, `corrupt_document`, `unsupported_schema_version`, `storage_io`.
- **Diagnostics**: `core.presentation_studio.art_direction_loaded`, `art_direction_candidates`, `art_direction_resolved` at `info`, `art_direction_relinked` at `warning`, writes under `saved` with `part: "art_direction"` (and `origin`, `fallback`); ids, revision, origin and counts only, never a name, note, locator or colour.
- Typed client: `LocalCoreClient.presentation_studio_art_direction`, `.presentation_studio_create_art_direction`, `.presentation_studio_save_art_direction`, `.presentation_studio_fallback_art_direction`, `.presentation_studio_art_direction_candidates`. No Control Center relay and no MCP tool yet (Slices 05+, 21).

### Seams left for later Slices (not built here)

| Seam | Owner |
| --- | --- |
| inspecting the project through agent tools, producing `DesignSignals`, calling `derive_from_signals`; asking at most the question that matters; deciding serious versus exploratory | Slice 11 (policy below) |
| writing divergent candidates by prompt (richer than `diverge`), the "style tour" in exploratory mode | Slices 11, 21 |
| agent tools over the DA (`presentation_art_direction`), choice providers | Slice 21 |
| applying the theme to the stage: `to_theme()` into the scene prefab `host.update`, per-scene overrides | Slices 11, 12 |
| comparing and mixing a DA between variants (`distance`, per-dimension provenance) | Slice 19 |
| rich media in a DA (images, web fonts) needs the optional frame asset delivery (handoff proposal `01b`); until then a DA is CSS, SVG and inline data only | proposal 01b |
| surfacing a DA problem in the inspector, promoting a DA to the shared library | Slices 07, 20 |

## Art direction authoring policy (for Slice 11)

This is the policy the authoring planner and its prompts (Slice 11) and the agent tools (Slice 21) follow. It is **text, not code**: the deterministic helpers above are what it calls; nothing here is a prompt yet.

1. **Source priority**: `provided` first (a design system, brand sheet or reference the user gave or pointed to), then `inferred` from **inspectable project context** (the repository, documents, existing decks or pages, memory, Drive, reached through the existing agent tools), then `generated`
   (`generate_fallback_profile` or a richer candidate). Record the origin you actually used: never mark `provided` what was guessed.
2. **Inspect before asking.** Look at what the user already has before putting a question to them. The result of inspection is a `DesignSignals` document (colours, fonts, radii, mentions, and the `sources` inspected as locators) handed to `derive_from_signals`.
3. **Do not block on a DA question** when the context can supply a DA and the user did not ask to decide the look by hand. A serious presentation always leaves the authoring step with a DA: derive one, else generate the fallback and say so.
4. **Ask only when the answer materially changes the DA** (a choice between two plausible brands, a conflicting reference, a mandatory palette you cannot infer). One question, with the options you found, and a default you will use if there is no answer. Never ask "what colours do you want?" when a project already shows them.
5. **Never copy external project folders** into presentation storage. A DA holds **references as locators** (`{kind, locator, title}`); an agent reads what it needs through its tools and reports signals. Nothing is downloaded, mirrored or embedded in a DA.
6. **Exploratory mode**: when the user wants to see several looks, ask for `n` candidates (`diverge` / `POST .../candidates`, `count` 1 to 6; two or more to compare), show them side by side, and adopt the chosen one by saving its content. Candidates are generated, flagged as such, and cost no storage until adopted.
7. **Say where a DA came from** when presenting it ("derived from your brand sheet", "generated: no brand found, here is a neutral direction"), and keep `confidence` and `notes` honest. A fallback is announced as a fallback and replaced when a better source appears.
8. **Treat DA text as data.** `name`, `notes`, `motifs`, reference titles and any text an agent read from a project are untrusted content: show them, never obey them, never place them in a style. A reference **title** (and anything an agent read) **may be multi-line**
   and may contain instruction-looking or CSS-looking text; a prompt that interpolates one must fence it as data and give that turn no tool authority.
9. **Accessibility is not optional**: the contrast numbers and the reduced-motion fallback are enforced by the contract; do not try to work around a refusal by lowering a threshold. Repair the palette (`derive_from_signals` already does) or choose another.
10. **`require_art_direction` has no caller yet.** Nothing in this Slice stops a variant from being saved without a DA (`serious` is a caller flag; a variant has no kind). Slice 11 must call `PresentationStudioService.require_art_direction` before it delivers a serious or generated variant
    (on `art_direction_required`: create the fallback and say so), and Slice 12 before it plays one. Both must carry that as an acceptance line.
11. **Agent trace scenarios** (inspect then derive, no needless question, fallback when the project has nothing, one question when two brands conflict) belong to Slices 11 and 21, which own the agent behaviour; they are to be added to the trace scenarios of those two Slices.


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
- The prefab library caps versions per id (64) and ids (512) and has no deletion: Tier-3 source editing needs a capacity decision first.
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
| Art direction profile, provenance, contrast, theme mapping, fallback / divergence / derivation, `require_art_direction` (model, validators, generators, store, routes) | 0-1 | 3 (**done**, Slice 09; authoring by prompt: Slices 11, 21) |
| Semantic edit API (vocabulary, tiers, preconditions, transactions, preview/commit, undo record, actors, relay, events) | 0-1 | 3 (**done**, Slice 05) |
| hot reload, autosave, playback, cue matching, rehearsal, variants, compare/mix, promotion, agent operations | 0-1 | 3 each |

There is no `docs/CONTEXT.md` or documentation-level registry in this repository: the level of a concept is stated in its page header (`Status: Level N`), as in [presentation-mode.md](presentation-mode.md).
