# Presentation Studio - concepts, owner map and status

Entry page for the Presentation Studio (handoff `jarvis-interactive-presentation-studio`): a structured, editable, rehearsable and presentable **Presentation** that Jarvis can author and
deliver. It **holds no behaviour contract yet**: it names the canonical concepts, says who will own each, and tracks status per section. When a section gets its own contract page or code,
that owner wins and this row is updated in the same commit.

Status: **Level 2 skeleton** for the page as a whole; the *Presentation contract* section below is **Level 3** (Slice 02: domain, port, file store, Core service, Core routes, typed client, conformance tests) and so is the *Scene and control contract* (Slice 04: logical scene, curated controls, discovery, prefab compatibility) and the *Semantic edit contract* (Slice 05: one edit API for voice and GUI) and the *Score and cue contract* (Slice 10: tracks, silence, cues, closed actions, locked sequences, score store and routes) and the *Art direction contract* (Slice 09: structured DA profile, provenance, contrast in numbers, deterministic fallback / divergence / derivation, theme mapping, `require_art_direction`; its authoring policy for Slice 11 follows it) and the *Persistence and undo contract* (Slice 08: durable commit, restart recovery, bounded undo/redo ring, history routes) and the *Playback roles and speech authority* contract (Slice 01c: role -> mode, switch/restore, scripted-line arguments) and the *Playback runtime contract* (Slice 12: the state machine, stage window, auxiliary windows, "where are we", armed-cue delivery) and the *Variant graph and operations contract* (Slice 16: branches, display numbers, activate, rename, archive under a confirmation token, restore, crash reconciliation) and the *Authoring contract* (Slice 11: the brief and the draft the brain submits, workflow choice, question budget, the first-draft quality gate, atomic assembly, the registered planner prompt; the real-model behaviour is not verified there).
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
| Scene hot reload | scene-local rebuild with state preservation and rollback | `jarvis/domain/presentation_studio_reload.py`, `core/presentation_studio_reload.py`, `presentation_studio_reload_stage.py`, `presentation_studio_mounts.py`, `presentation_studio_pins.py`, `runtime/control_center_presentation_studio_reload.js` | [Hot reload contract](#hot-reload-contract-level-3-slice-06) | Level 3 (Slice 06) |
| Edit inspector (GUI) | contextual dock panel generated from the controls introspection: widget per type, bounds, default / reset, preview while dragging and one commit on release, typed refusals, stale / reload states, undo / redo, hidden in playback, read-only art direction chip | `runtime/control_center_presentation_studio_inspector.js` (+ read-only relay `GET .../art-direction`) | [Edit inspector UI](#edit-inspector-ui-level-3-slice-07), Slice 07 | **implemented (Level 3)** (look and feel on a real screen: Human check) |
| Autosave + undo | every acknowledged commit is durable (no buffer, no second path); restart recovery of the active variant; bounded in-memory undo/redo ring per variant; pins held by undo entries | `domain/presentation_studio_history.py`, `core/presentation_studio_autosave.py` | [Persistence and undo contract](#persistence-and-undo-contract-level-3) below, Slice 08 | **implemented (Level 3)** |
| Art direction | structured profile with provenance (provided / inferred / generated), contrast checked in numbers, theme mapping, deterministic fallback, divergent candidates, derivation from extracted signals | `jarvis/domain/presentation_studio_art_direction.py`, `jarvis/domain/presentation_studio_art_direction_authoring.py` (stored by the Slice 02 store and service) | [Art direction contract](#art-direction-contract-level-3) and [authoring policy](#art-direction-authoring-policy-for-slice-11) below, Slice 09 | **implemented (Level 3)** (the authoring planner that drives it is [Authoring contract](#authoring-contract-slice-11), Slice 11; the tools are Slice 21) |
| Authoring planner | the brief and the one-transaction draft the brain submits; workflow choice (`one_shot` / `directed` / `exploratory`); question budget; first-draft quality gate (48 coded rules); atomic assembly of the whole Presentation; registered planner prompt | `jarvis/domain/presentation_studio_authoring*.py`, `core/presentation_studio_authoring.py`, `protocol/presentation_studio_authoring_routes.py`, `runtime/presentation_studio_authoring_relay.py` | [Authoring contract](#authoring-contract-slice-11), Slice 11 | **implemented (Level 3)** (real-model trace: Slices 21, 22) |
| Score, cues, timing | multi-track score, explicit silence, armable finite-set cues, closed reversible actions, soft/locked timing, recovery points | `jarvis/domain/presentation_studio_score.py` (stored by the Slice 02 store and service) | [Score and cue contract](#score-and-cue-contract-level-3) below, Slice 10 | **implemented (Level 3)** |
| Playback runtime | roles (user presenter / Jarvis presenter / rehearsal), position, detours, "where are we", stage window, armed-cue delivery | `jarvis/domain/presentation_studio_playback.py`, `presentation_studio_armed_set.py`, `core/presentation_studio_playback.py`, `core/presentation_studio_stage.py`, `runtime/control_center_presentation_studio_player.js` | [Playback runtime contract](#playback-runtime-contract-level-3-slice-12), Slice 12 | **implemented (Level 3)** |
| Armed cue following | ambient speech may only satisfy a pre-armed cue id, bound to a pre-authorized reversible action (the Core to Voice delivery contract is decided and implemented by Slice 12) | `jarvis/domain/presentation_studio_cues.py`, `runtime/presentation_studio_cue_follower.py` | Slice 13 + amendment of [presentation-addressed-turn.md](presentation-addressed-turn.md) section 12 | planned |
| Playback roles, speech authority (decision A) | role -> interaction mode, ambient-lane and speech policy; who may switch the mode; restore protocol; the `announce_notice` argument set | `jarvis/domain/presentation_studio_roles.py` | [Playback roles and speech authority](#playback-roles-and-speech-authority-level-3-slice-01c-decision-a) below, Slice 01c | **implemented (Level 3)** |
| Jarvis presenter, locked sequences | scripted speech through the existing speech path (`announce_notice`), outside PRESENTATION; deterministic locked-sequence executor on a monotonic clock; interruption policy and recovery; visible failures | `jarvis/core/presentation_studio_presenter.py`, `jarvis/domain/presentation_studio_sequence.py`, `jarvis/domain/presentation_studio_line.py` | [Jarvis presenter and locked sequences](#jarvis-presenter-and-locked-sequences-level-3-slice-14) below, Slice 14 (speech authority: Slice 01c) | **implemented (Level 3)** (audible proof: Human check) |
| Rehearsal | practice, pause-edit-resume, no durable transcript | playback runtime | Slice 15 | **planned as a Slice, never implemented as one**: the behaviours exist through Slices 12, 01c and 21 (the `rehearsal` role, "where are we", pause-edit-resume, `goto`, `previous`) and are proven end to end by Slice 22; a section-loop command is missing ([release report](presentation-studio-release.md)) |
| End-to-end hardening, release gates | journeys, injected faults, leak counters, privacy, release verifier, real-model authoring traces | `tests/unit/presentation_studio_release_world.py`, `scripts/verify_release.py`, `jarvis/domain/presentation_studio_authoring_guide.py` | [Final report, acceptance and contract index](presentation-studio-release.md), Slice 22 | **machine gates green; physical acceptance open** (Human checks H-1 to H-11) |
| Variant Explorer (UI) | fullscreen dark workspace: branch tree, live preview of the selected variant, activate / branch / rename / archive (plan + token) / restore, context menu; opened by voice through a command channel; never the source of truth | `jarvis/runtime/control_center_presentation_studio_explorer{,_core,_widgets}.js`, `jarvis/domain/presentation_studio_explorer.py`, `runtime/presentation_studio_explorer_commands.py` | [Variant Explorer interaction contract](#variant-explorer-interaction-contract-level-3-slice-18) (Slice 18) | **Level 3** |
| Variant compare / mix | side-by-side, synchronized navigation, selective composition into a new child | `jarvis/domain/presentation_studio_compare.py`, `presentation_studio_composition.py`, `core/presentation_studio_compare.py`, `presentation_studio_composition.py`, `protocol/presentation_studio_compose_routes.py`, `runtime/presentation_studio_compose_relay.py` | [Comparison and semantic composition contract](#comparison-and-semantic-composition-contract-level-3-slice-19-backend), Slice 19 | **implemented (Level 3, backend + explorer panes UI)**; [UI contract](#comparison-and-composition-in-the-explorer-slice-19-interface), 
untime/control_center_presentation_studio_explorer_compare*.js, ..._compose.js |
| Template / promotion | whole-variant, scene, DA or motion promoted: reusable code published to the shared prefab library, composition in a `ptp_` document, project content stripped or parameterized, provenance kept | `jarvis/domain/presentation_studio_template{,_sanitize}.py`, `core/presentation_studio_template.py`, `adapters/file_presentation_template_store.py` | [Template and prefab promotion contract](#template-and-prefab-promotion-contract-level-3-slice-20), Slice 20 | **implemented (Level 3)** |
| Generic fullscreen surface | real browser fullscreen of a host element; armed request + user gesture; explicit `needs_gesture` / `unsupported` | `jarvis/domain/surface_fullscreen.py`, `runtime/control_center_fullscreen.js` | Slice 03 | implemented (Level 3) |
| Agent / voice operations | one MCP server `jarvis-presentation`, twelve `presentation_*` tools, ids read from the state (`presentation_inspect`), the only `brain` door, destructive gestures behind the canonical confirmation | `jarvis/runtime/presentation_studio_mcp{,_tools,_support}.py`, `runtime/presentation_studio_turn.py` | Slice 21, [Agent and voice operations](#agent-and-voice-operations-level-3-slice-21), [mcp/tool-contract.md](mcp/tool-contract.md) | **implemented (Level 3)**; real-model traces: 5 scenarios, limited |

Exact names (ids, routes, events, tools): `tasks/jarvis-interactive-presentation-studio/docs/09-canonical-names.md`; the Presentation ids, routes, error codes and storage tree are now stated in the contract section below (Slice 02).

## Presentation contract (Level 3)

Status: implemented by Slice 02. Conformance: `tests/unit/test_presentation_studio_{domain,store,crash,service,routes,docs}.py`,
fixtures `tests/fixtures/presentation_studio/`. A Presentation can be created, saved, loaded, listed and validated **independently of
playback and of any UI**; nothing here imports the scene service, the prefab service, a renderer or the Control Center.

### What it holds, and what it never holds

| Document | Holds (references, never copies) |
| --- | --- |
| `Presentation` (`presentation.json`) | `presentation_id` `pst_<32 hex>`, `title` (<= 80, one printable line), `active_variant_id`, `variant_counter` (last number handed out, monotone, never reused), the variant index of live nodes (1..64: `{variant_id, variant_number}` plus, since Slice 16 and manifest v2, `rationale`, `created_by`, `sources`, `preview_id`), `archived` (Slice 16: nodes whose file was moved to `archive/`, <= 128), `resources` (<= 64, `{kind, locator, title}`), `revision`, `created_at`, `updated_at` |
| `PresentationVariant` (`variants/<variant_id>.json`) | `variant_id` `psv_<32 hex>`, `variant_number`, `title`, `parent_variant_id` (the tree edge; cycles refused; the graph operations are Slice 16), ordered `scenes` (<= 64) of `{scene_id: pss_<12 hex>, prefab: {id, version}}`, `art_direction_id` (`psd_<12 hex>` or null; the profile is behind it, see *Art direction contract*), `score_id` (`psr_<12 hex>` or null; the score document is behind it, see *Score and cue contract*), `revision`, timestamps |

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
| `presentation_studio_active_variant_protected` | 409 | the active variant (or the last live one) is in the set an archive would touch (Slice 16) |
| `presentation_studio_confirmation_required` | 400 | an archive without the confirmation token of a plan (Slice 16) |
| `presentation_studio_confirmation_stale` | 409 | the token is forged, expired, or no longer matches the set, a title, the revision or the chosen active variant (Slice 16) |
| `presentation_studio_not_archived` | 409 | restoring a variant that is not archived (Slice 16) |
| `presentation_studio_linked_document_unsupported` | 409 | the variant cites a linked document no registered kind can copy, so a branch is refused rather than sharing it (Slice 16) |
| `presentation_studio_variant_in_playback` | 409 | archiving a variant (or an ancestor of it) that a live playback run is playing (Slice 16) |
| `presentation_studio_compare_mapping_conflict` | 409 | a manual scene link would put two scenes of one variant in the same logical scene (Slice 19) |
| `presentation_studio_composition_refused` | 409 | a semantic composition has typed conflicts; the envelope also carries `error.conflicts`, nothing was written (Slice 19) |
| `presentation_studio_unknown_composition` | 404 | the variant is not the result of a composition: no provenance file (Slice 19) |
| `presentation_studio_draft_refused` | 400 | the first-draft quality gate refused a submission: the complete report is in the answer (`status: "refused"`), nothing was written (Slice 11) |
| `presentation_studio_unknown_template` | 404 | no template of that `ptp_` id in the template store (Slice 20) |
| `presentation_studio_template_leak` | 409 | a promotion would keep project content or references (a finding is blocking), or the final record still holds a trace: nothing was written; the plan lists every finding (Slice 20) |
| `presentation_studio_template_selection_required` | 400 | a promotion without the explicit choice of dimensions and parameters, or a presentation template that does not cover every scene (Slice 20) |
| `presentation_studio_unsupported_schema_version` | 409 | stored document newer than this JARVIS; file untouched |
| `presentation_studio_corrupt_document` | 409 | stored document unreadable, oversize, linked, inconsistent, or an indexed variant missing |
| `presentation_studio_already_exists`, `presentation_studio_limit_reached` | 409 | id taken; 256 presentations, 64 variants/scenes/resources, or a 256 KiB document exceeded |
| `presentation_studio_storage_io` | 500 | disk, link/junction refusal, path limit, missing data root: the real cause is in the message |
| `invalid_request`, `core_unavailable`, `internal_error` | 400, 503, 500 | malformed query or body (not JSON, duplicate key, > 256 KiB) / Core not ready / unexpected |

Diagnostics `core.presentation_studio.{started,swept,created,saved,listed,validated,refused,scenes_checked,scene_described,score_loaded,score_relinked,art_direction_loaded,art_direction_relinked,art_direction_candidates,art_direction_resolved}` at `info` (ids, codes, counts; never titles, locators or content), and at `error`
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
<data_root>/presentations/<presentation_id>/art_directions/<art_direction_id>.json   # Slice 09
<data_root>/presentations/<presentation_id>/archive/<variant_id>.json    # Slice 16: archived variants (moved, never deleted)
<data_root>/presentations/.staging-<16 hex>/          # a creation in progress; swept at start
```

- **Atomic file writes**: unique temporary beside the target, `fsync`, `replace_with_retry` (`os.replace`, bounded retry on a Windows lock), then the folder is flushed so the rename itself survives a power cut (Slice 08, *Persistence and undo contract*). A crash leaves the old text whole or the new text whole; a leftover `*.<8 hex>.tmp` is swept at the next start and never blocks a save.
- **Atomic creation**: the whole folder is built in `.staging-*` (variants, then since Slice 11 the scores and art directions of an assembled Presentation, manifest last), then renamed; `os.rename` fails if the target exists. There is never a presentation folder without its manifest, nor (Slice 11) one whose variants cite a score or art direction that is not there.
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
| art direction content behind `art_direction_id` | **done, Slice 09** (`art_directions/<art_direction_id>.json`) |
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

The variant document is now `schema_version` **4** (Slice 06 took 3, Slice 17 took 4: see *Scene-local variant contract*); the Presentation manifest is 2 since Slice 16 (`CURRENT_VERSIONS`). `UPGRADES[variant][1]`
fills the Slice 04 fields of each v1 scene with their defaults (`title ""`, `section ""`, `props {}`, `data {}`, no controls, no
anchors, empty preview) and `UPGRADES[variant][2]` (Slice 06) adds `source_revision 0` and `last_valid_pin null` to each scene: nothing an
older file said is reinterpreted, an old file is read through the steps and rewritten as v3 by the next save (reading never rewrites), and a
JARVIS that only knows an older version refuses a newer file untouched (`unsupported_schema_version`). A scene body may still be the bare
`{scene_id, prefab}` pin.

### Extension points

| To add | Where | Rule |
| --- | --- | --- |
| a control for a new prefab | the scene's `controls` (data), never code | the path must be a manifest input; a prefab that needs a new kind of input extends the prefab input schema first (`docs/prefabs.md`), the widget follows |
| a widget for a new input type | `widget_for`, `effective_bounds`, `bounds_problem`, `value_problem` together | one table per concern, same test row |
| a control group | `ControlGroup` | closed on purpose; a new family needs a docs row and an inspector decision (Slice 07) |
| a score action | `ScoreAnchor` for `reveal` / `hide`, a declared `StudioControl` for `control_set` (Slice 10 reads, never invents one) | closed set per scene, bound to a declared control or a plain marker |
| an edit (Slice 05) | an operation in `presentation_studio_edit.py` | see *Semantic edit contract*, Extension points |

Not here: rendering and hot reload (Slice 06, see *Hot reload contract*), the stage window lifecycle (Slice 12). The inspector UI is [Edit inspector UI](#edit-inspector-ui-level-3-slice-07) (Slice 07).

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
emits `score.cue_satisfied(cue_id)` and the bound actions are resolved **from this stored score**. The matcher itself is not part of this Slice (it is Slice 13: *Cue following contract*). A cue phrase that is one word, only stopwords or shorter than 4 letters fires on ordinary speech: the score answers carry a non-blocking `warnings: [{code: "weak_cue", ...}]` for it (Slice 13), prefer distinctive multi-word phrases.

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
| armed-cue set delivery and ambient matching against `CuePredicate`, `score.cue_satisfied`; ambiguity of the armed set via `ambiguous_phrases` | **done, Slice 13** (*Cue following contract*) |
| runtime meaning of `reveal` / `hide` on a plain marker anchor (no `control_id`) versus a control-bound one: this Slice only checks that the anchor exists | Slice 12 |
| surfacing `problems` when a scene, control or anchor a score references is removed or renamed (`save_variant` does not block it; `GET score` reports it and `save_score` refuses until fixed); the score revision is separate from the variant revision, so autosave / undo / compare track both | Slices 05, 08, 19 |
| playback position, reveal progress, detours, "where are we" over `playback_order()` | **done, Slice 12** (*Playback runtime contract*; `reveal`/`hide` on a marker versus a control-bound anchor is decided there) |
| speaking `text` through the speech path, executing a locked sequence's steps | **done, Slice 14** (*Jarvis presenter and locked sequences*) |
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
- Typed client: `LocalCoreClient.presentation_studio_art_direction`, `.presentation_studio_create_art_direction`, `.presentation_studio_save_art_direction`, `.presentation_studio_fallback_art_direction`, `.presentation_studio_art_direction_candidates`. Control Center relay: only the read-only `GET .../art-direction` (Slice 07, the inspector chip; actor `user`, nothing written); create, save, fallback and candidates are not relayed. No MCP tool yet (Slice 21).

### Seams left for later Slices (not built here)

| Seam | Owner |
| --- | --- |
| inspecting the project through agent tools, producing `DesignSignals`, calling `derive_from_signals`; asking at most the question that matters; deciding serious versus exploratory | Slice 11 (policy below) |
| writing divergent candidates by prompt (richer than `diverge`), the "style tour" in exploratory mode | Slices 11, 21 |
| agent tools over the DA (`presentation_art_direction`), choice providers | Slice 21 |
| applying the theme to the stage: `to_theme()` into the scene prefab `host.update`, per-scene overrides | Slices 11, 12 |
| comparing and mixing a DA between variants (`distance`, per-dimension provenance) | Slice 19 |
| rich media in a DA (images, web fonts) needs the optional frame asset delivery (handoff proposal `01b`); until then a DA is CSS, SVG and inline data only | proposal 01b |
| surfacing the DA in the inspector (**done, Slice 07**: read-only chip, own-revision comparison, the 10 undelivered variables shown `non appliqué`), promoting a DA to the shared library | Slice 20 |

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
10. **`require_art_direction` has callers.** Slice 11 enforces it twice in `PresentationStudioAuthoring.assemble` (`require_art_directions` on the documents about to be stored, the service method on what was stored) and the gate reports `da_missing` first; a serious (`one_shot`, `directed`) or generated variant never leaves authoring without a DA, an exploratory candidate may be a bare draft. Slice 12 before it plays one (`PresentationStudioPlaybackService` gate).
11. **Agent trace scenarios** (inspect then derive, no needless question, fallback when the project has nothing, one question when two brands conflict, hostile project text) belong to Slices 11 and 21 in the first plan; Slice 11 delivered the deterministic side, so the real-model traces are carried by Slices 21 and 22, each in its *Slice 11 carry-forward* section. Slice 11 itself proves the deterministic side with a scripted rig and states what that does not show ([What is NOT verified here](#what-is-not-verified-here)).


## Authoring contract (Slice 11)

Status: **Level 3 for the deterministic side** (brief and draft schema, workflow choice, question budget, quality gate, atomic assembly, routes, client, relay, registered planner prompt). **Not verified here: whether the real model follows the policy** (see [What is NOT verified here](#what-is-not-verified-here)).

Who does what. The creative work (narrative, scenes, copy, art direction, score) is done by the Jarvis brain, an LLM, through tools that Slice 21 will expose. This Slice delivers what makes the result **good by construction**: one validated submission (`AuthoringBrief` + `PresentationDraft`), a first-draft quality gate that refuses a weak draft with the complete list of what to fix, an assembly that is atomic, and the planner policy the brain follows (workflow choice, inspect before asking, a question budget, the art direction priority). Tool Brain is not involved; there is no MCP tool yet (`docs/mcp/tool-contract.md` is untouched until Slice 21).

Modules: `jarvis/domain/presentation_studio_authoring.py` (brief and draft schema, `parse_brief`, `parse_draft`), `jarvis/domain/presentation_studio_authoring_build.py` (id allocation, the documents, `validate_built`), `jarvis/domain/presentation_studio_authoring_gate.py` (`check_first_draft`, `RULES`), `jarvis/domain/presentation_studio_authoring_text.py` (the lexical helpers: placeholders, content floor, filler, language guess, must-cover, risky sources), `jarvis/domain/presentation_studio_authoring_finalize.py` (a stored variant back to a draft for `finalize`), `jarvis/domain/presentation_studio_authoring_policy.py` (`choose_workflow`, `question_budget`, `PLANNER_PROMPT`), `jarvis/core/presentation_studio_authoring.py` (`PresentationStudioAuthoring`: `check`, `assemble`, `reconcile`), `jarvis/protocol/presentation_studio_authoring_routes.py`, `jarvis/runtime/presentation_studio_authoring_relay.py`. Tests: `test_presentation_studio_authoring*.py`, the scripted rig `tests/fakes/presentation_studio_fake_author.py`.

### Three workflows (`Workflow`)

| Workflow | When | What the brain delivers | Art direction | Gate |
| --- | --- | --- | --- | --- |
| `one_shot` | information or a report to display now | one coherent draft, no interview | required (the flagged fallback if nothing to derive from) | full |
| `directed` | a prepared presentation, however much is known | a near-presentable first draft: story, scenes, DA, content, animation, score, cues, transitions, timing | required | full |
| `exploratory` | the user asks for ideas, styles or options | `candidates`: 2 to 6 genuinely different directions, stored as **draft** variants; adopted as the deck only through `finalize` | optional per candidate | the lighter subset below (`strict_content`: the `directed` level of every rule) |

`choose_workflow(RequestSignals)` is pure; the first rule that applies decides:

| Rule | When | Workflow |
| --- | --- | --- |
| W1 | the user named a workflow | that one |
| W5 | the user asks for alternatives and the object is a Presentation or scenes that **already exist** (`targets_existing_deck`) | `exploratory`, **scoped**: variants of the existing scene set (Slice 16 branches, Slice 17 scene-local variants), never a new deck and never `assemble` |
| W2 | the user asks for ideas, styles or options, whatever else is known | `exploratory`; `strict_content` when the deck is briefed (audience, purpose, content) or final with its content given |
| W3 | a result or information to display now, not a prepared talk | `one_shot` |
| W4 | everything else | `directed` |

The rules apply in the order W1, W5, W2, W3, W4 (`WorkflowChoice` carries `rule`, `scoped`, `strict_content`). A vague request that is not an invitation to improvise stays `directed`: vagueness alone never becomes a fan of styles. W5 comes before W2 because "give me alternatives for the opening" of a deck that exists is a variant of that deck: routing it to a new exploratory deck delivered one without structure (QA-1 P1). The lightness of the exploratory column is for candidates that are deliberately light; it does not apply to what does not depend on lightness (the arc with a closing scene, a score item for every scene, motion that honours reduced motion are errors in every column), and an exploratory request over a briefed deck sets `strict_content`. `finalize` is the last guard: a candidate becomes the deck only after the `directed` gate has judged it.

### Question budget (`question_budget`)

Ask only what changes the narrative, the art direction, the audience or purpose, the evidence, or an output constraint; never what the project can answer; look first.

| Rule | Effect |
| --- | --- |
| Q0 | sources not inspected yet: nothing may be asked |
| Q1 | `one_shot`: 0, except ONE `evidence` question when the inspection found no source and the brief names neither a purpose nor an audience (otherwise the model must invent the content, which no gate can detect) |
| Q2 | `exploratory`: at most 1, only about the subject (`evidence`), and only when there is no content at all |
| Q3 | `directed`: at most 3 over the whole request, one at a time, highest leverage first (`audience_purpose`, `evidence`, `art_direction`, `narrative`, `output_constraints`) |
| Q4 | `audience_purpose` when audience or purpose is missing; `evidence` when there is no content; `art_direction` **only on a conflict between sources** (nothing found means the generated fallback, never "what colours?"); `narrative` only when two storylines are plausible; `output_constraints` (duration, language) only for a final deliverable whose duration is missing |
| Q5 | a topic the sources can answer (`discoverable`) is removed |

### The brief (`AuthoringBrief`, untrusted text)

Exact keys; unknown keys refused; a runtime-state name keeps its own code (`presentation_studio_runtime_state_refused`).

| Key | Rule |
| --- | --- |
| `title`, `workflow` | required; title one printable line <= 80 |
| `purpose`, `audience` | one printable line <= 200 |
| `duration_target_s` | integer 5..10 800; the gate holds the soft targets of the score to +-35 % of it |
| `tone` | <= 8 words of <= 24; `language` `fr`, `en`, `fr-CA` |
| `speech` | `jarvis` (default), `user`, `none` |
| `resources` | <= 64 references `{kind, locator, title}` through the Slice 02 hygiene (decoded to a fixpoint; no `file://`, UNC, `..`, backslash, control, zero-width or bidi character, no scene handle). Stored on the Presentation as provenance, never a copied content |
| `must_cover` | <= 8 lines of <= 120; every item must be traceable in the scene texts (`must_cover_missing`: 60 % of its significant words, compared by 5-letter stem; an item of short words only must appear as a phrase) |
| `max_scenes` | 1..48 |
| `literal_terms` | <= 8 words of <= 40, one printable line each: terms that look like a placeholder but are the subject (a status deck that says `todo` or `WIP`). They lift the placeholder rule for that span only and the report says so (`placeholder_allowed`, a count, never the term) |
| `strict_content` | boolean, exploratory only: the `directed` level of every rule applies and only the art direction varies |

`language` is checked against the scene texts by a cheap French/English stop-word guess (`language_mismatch`: at least 6 hits and twice the other language; a language the guess does not know is not judged). **`purpose`, `audience` and `tone` are not machine-checkable**: they are untrusted prose with no deterministic test worth the name. They steer the model through the prompt and seed the art direction fallback; the gate does not pretend to read them.

### The draft (`PresentationDraft`)

The brain names scenes, bundles and candidates with **slugs of its own** (`[a-z][a-z0-9_]{0,39}`); it never gives an id. Core allocates every `pst_`, `psv_`, `pss_`, `psi_`, `psc_`, `psr_` and `psd_` id and returns them. The only ids that come from outside are prefab pins `{id, version}` of existing prefabs, read from a tool result.

| Part | Shape | Reuses |
| --- | --- | --- |
| `prefabs` (<= 16) | `[{key, candidate: {manifest, template, style, behavior}}]` new sources; ids under `presentation-studio.`, one bundle per id, every bundle used | `PrefabService.validate_candidate` / `parse_candidate` |
| `scenes` (<= 48, 1..) | `{key, role, title, prefab: {bundle} or {id, version}, section?, props?, data?, controls?, anchors?, alt?, long_form?, cut?}`; `role` `opening` / `body` / `closing` / `single` | `StudioScene`, `StudioControl`, `ScoreAnchor` (Slice 04) |
| `score.items` (<= 150, ordered) | `{scene, presenter, text xor note, label?, cue?, visual?, motion?, target_duration_ms?, interruption?}`; a cue is `{label, armable, phrases?, semantics?}`; actions are the closed set `control_set` / `reveal` / `hide` / `scene_goto` (motion: `control_set` only), naming a scene key (default: the item's own). The order is the chain; **locked sequences and loops are not authored in a first draft** (add them afterwards) | `ScoreItem`, `CuePredicate`, `ActionRef` (Slice 10) |
| `art_direction` (serious) | `{mode: "profile", profile}`, `{mode: "signals", signals}` (inspect then derive), or `{mode: "fallback"}` (reads the brief) | `parse_profile`, `derive_from_signals`, `generate_fallback_profile` (Slice 09) |
| `candidates` (exploratory, 2..6) | `{title, rationale <= 240, art_direction?, scenes_patch?: {scene key: {title?, props?, data?}}}` over the shared scenes and score | `diverge` (Slice 09) for the divergence, the Slice 16 graph for the result |

Scene flags: `long_form: true` declares a full-read scene (the word cap rises to 600 and the report says so); `cut: true` attests that the hard cut into the scene is intended (no transition declared). Art direction modes: `profile` (the brain hands over a complete profile with its own provenance), `signals` (the brain reports what it inspected and Core derives, provenance `inferred`), `fallback` (Core generates from the brief, provenance `generated`, flagged).

`parse_draft` collects **every** schema problem (at most 20) and returns no draft while there is one: the brain fixes them in one round. A scene that waits on a bundle that did not parse is not reported a second time.

### One transaction (`PresentationStudioAuthoring`)

1. **`check`** (dry run, `POST .../authoring/check`): parse, resolve the pins (`PrefabService.manifest`), validate the bundles with the prefab authority, assemble the documents in memory with the candidates' own provisional pins, validate scenes, controls, values and the score against the manifests, run the gate. **Nothing is written or published.** Same draft, same report.
2. **`assemble`** (`POST .../authoring/assemble`): the same preparation (so `assemble` alone is enough: it refuses with the full report and writes nothing, the brain does not need to send a draft to `check` first). If the gate has an error: `refused`, **nothing is written**, the answer carries the complete report. Otherwise: `require_art_directions` on the documents (the Slice 09 invariant: a serious or generated variant resolves a DA); `require_room` (a full store of 256 Presentations is refused before anything is published); publish each new bundle with `PrefabService.save` (retention-aware, namespace `presentation-studio.`; **Core assigns the version**, whatever the candidate says); read the published manifests back; assemble the documents again with the real pins and validate again; store the **whole** Presentation (manifest, every variant, every score, every art direction) with `PresentationStudioStore.create` in ONE folder rename; read the result back from disk (`get`, `require_art_direction`, `get_score`, the Slice 16 graph `check`).
3. **Graph.** A serious draft is variant 1. An exploratory draft is `n` candidates: candidate 1 is the root, the others are its children (parent and `sources` = the root, numbers 2..n), all draft (`rationale` starts with `draft direction k/n:`), same scene ids in every variant like a Slice 16 branch, each with its own score and art direction documents. `created_by` is the request's actor.
4. **`finalize`** (`POST .../authoring/finalize`, `{presentation_id, variant_id, actor?, activate?}`): the stored variant, its score and its art direction are turned back into a draft and judged by the **same** gate as a `directed` draft (`presentation_studio_authoring_finalize.py`). On success it is switched to the active variant (`activate`, default true; the Slice 16 `switch`); otherwise 400 with the report and nothing changes. A stored variant keeps no brief, no roles, no `long_form`, no `cut`: roles are inferred from position, the long-form cap applies, every cut is taken as declared, and the rules that need the brief or an attestation are listed in `not_judged` instead of guessed. A plain `activate` stays the user's own choice; `finalize` is the gated way for the brain to adopt a draft.
5. **Why `PrefabService.save` and not the Slice 01a coalescer**: the coalescer merges a *burst of edits of one id*; an assembly publishes each id once, so there is nothing to merge and the coalescer would only add its quiet period. `save` is the path the coalescer ends in.

Crash states (proved by real `Popen.kill()` drills, `test_presentation_studio_authoring_crash.py`):

| Killed at | Left on disk | What happens next |
| --- | --- | --- |
| before any publication | nothing | nothing to do |
| after bundle k is published | prefab versions no variant pins | `reconcile()` **reports** them (`unreferenced_prefabs`); never adopted, never deleted; the retention archives an unpinned `presentation-studio.*` version; a retry publishes new versions |
| documents built, not stored | the same | the same |
| inside the store write | one `.staging-*` folder (variants, scores, DAs, no manifest) | swept at `start()`; never listed as a Presentation |
| right after the rename | the complete Presentation | reads clean, the graph check is clean, every DA and score resolve |

There is no state in which a Presentation exists without its scores and art directions. `PresentationStudioService.create_assembled` is the single door (limit check under the Studio lock, then `store.create`), `_persist_variant` is untouched.

### The quality gate (`check_first_draft`)

Deterministic and explainable: each finding has a `code`, a `severity` (`error` blocks, `warning` does not), a `where` in the brain's keys (`scene:intro`, `item:4`, `candidate:2`, `bundle:hero`, `art_direction`, `score`) and a message that says what to change. A message never carries the author's free text: a placeholder finding names the *kind*, unknown keys are counted (`unknown keys (2, names not echoed)`), a refused value is replaced by `<value>` (`safe_text`); what does appear is a position (`item:4`), a validated slug (`scene:intro`), an enumeration member, a code or a size. (QA-1 P4: an earlier claim that nothing was echoed was false for unknown key names and refused values; they are now sanitised at the single point every message passes, and a canary test covers 28 injection points.) The gate is a **floor, not a judge of quality**: it refuses empty, placeholder, repeated and unbounded content and structural gaps; whether the content is good remains the model's job and the Human's judgement. At most 5 findings per rule are listed, the rest is counted in `suppressed`. A serious draft with any error is refused with the whole list; the exploratory column is the documented lighter subset (what is objectively broken still refuses). `skipped` lists any rule that could not run for lack of an input. `stage` says how far the verdict went: `complete`; `partial` (the draft had schema problems but part of it parsed: the text, motion, source and control rules ran on what could be read, with the author's own item numbers, and the structure rules wait for a parsable draft, so the next round can still reveal them); `schema` (nothing readable); `brief` (the brief was refused; `workflow` is then what the author declared, or `null`).

| Rule | one_shot | directed | exploratory | Checks |
| --- | --- | --- | --- | --- |
| **Validation (always blocking)** | | | | |
| `brief_invalid` | error | error | error | the brief is an exact, bounded object |
| `draft_schema` | error | error | error | the draft is an exact, bounded object (every schema problem is listed) |
| `prefab_invalid` | error | error | error | a published source is a valid prefab candidate (`validate_candidate`) |
| `prefab_namespace` | error | error | error | a published source lives under `presentation-studio.` |
| `pin_unknown` | error | error | error | an existing pin names a healthy prefab version |
| `scene_incompatible` | error | error | error | controls and values of a scene fit the manifest of its pin |
| `score_incompatible` | error | error | error | every score reference resolves (scenes, controls, anchors, bounded values) |
| `document_invalid` | error | error | error | the Presentation, its variants and its index are consistent, every document fits its size cap |
| **Art direction** | | | | |
| `da_missing` | error | error | warning | every serious variant carries an art direction (Slice 09 `require_art_direction`) |
| `da_incoherent` | error | error | warning | the provenance of the art direction is backed (provided or inferred needs references) |
| `da_fallback_ignored_sources` | warning | warning | off | a generated fallback while the brief lists sources to inspect |
| `contrast_low` | error | error | error | text and colour controls keep contrast on the art direction background |
| **Structure and narrative** | | | | |
| `arc_incomplete` | error | error | error | opening, body and closing scenes, in that order |
| `scene_no_score` | error | error | error | every scene has at least one score item |
| `scene_unbound` | error | error | error | every scene declares a control or carries content values |
| `scene_no_controls` | warning | warning | off | a scene with no curated control cannot be tuned by voice or inspector |
| `transition_missing` | error | error | off | a transition style, or a motion on the entering item, or a declared cut |
| **Text** | | | | |
| `placeholder_text` | error | error | error | no lorem, TODO, 'xxx', bracketed or generic placeholder text (colours, numbers and table cells are not text) |
| `placeholder_allowed` | warning | warning | warning | a placeholder-looking term the brief declared legitimate (`literal_terms`) was allowed |
| `content_thin` | error | error | warning | a scene shows at least 3 meaningful words (2 outside its title) and a spoken line at least 3 |
| `repeated_filler` | error | error | warning | the same text is not repeated as filler across scenes |
| `filler_numeric_variants` | error | error | warning | texts and titles that differ only by digits, case or spacing are not filler |
| `text_density` | error | error | warning | at most 120 visible words per scene (600 for a declared long_form scene) |
| `text_dense` | warning | warning | off | a scene past two thirds of the word cap |
| **Timing, speech and the brief** | | | | |
| `duration_off` | error | error | off | the soft targets add up to the brief's duration within +-35 % |
| `duration_missing` | warning | warning | off | speaking items carry a soft target duration |
| `duration_item_range` | warning | warning | off | an item target is 500 ms to 15 min |
| `presenter_mismatch` | error | error | warning | presenters match who speaks in the brief; `none` is the explicit silence |
| `jarvis_line_missing` | warning | warning | off | an item Jarvis presents carries the line he says, not only an intention |
| `notes_missing` | warning | error | off | every scene has speech or a speaker note (directed) |
| `must_cover_missing` | warning | error | off | every `brief.must_cover` item is found in the scene texts (60 % of its significant words) |
| `language_mismatch` | warning | error | warning | the scene texts read as French or English like the brief's language says |
| **Cues** | | | | |
| `cue_weak` | error | error | warning | an armable cue has distinctive multi-word phrases (Slice 13 `weak_cue`) |
| `cue_stopword_phrase` | error | error | warning | a multi-word armable phrase is not made only of stop-words and fillers |
| `cue_ambiguous` | error | error | error | no phrase names two armable cues among neighbouring items |
| `cue_nested` | warning | warning | off | an armable phrase is not contained in a neighbour's phrase |
| `cues_sparse` | warning | warning | off | a user-presented deck arms cues on half of its scenes |
| **Controls** | | | | |
| `controls_too_many` | error | error | warning | at most 12 controls per scene |
| `control_unlabelled` | error | error | warning | a control has a human label, not its machine id |
| `control_label_meaningless` | error | error | warning | a control label is words, not `???`, `x` or `ctrl1` |
| `control_no_meaning` | warning | warning | off | a control says what it is for |
| `control_unbounded` | error | error | warning | a numeric control is bounded on both sides |
| **Motion, sources and caps** | | | | |
| `motion_unguarded` | error | error | error | an animated published source honours prefers-reduced-motion |
| `behavior_risky` | error | error | warning | a published source has no network call, eval, dynamic import, javascript: or remote reference (a lint; the host sandbox is the wall) |
| `payload_headroom` | error | error | warning | a scene payload uses at most 75 % of its cap |
| `document_headroom` | error | error | warning | a document uses at most 75 % of its size cap |
| **Exploratory shape** | | | | |
| `candidates_count` | off | off | error | 2 to 6 candidates |
| `candidates_not_divergent` | off | off | error | candidates differ by at least 0.2 (Slice 09 distance) |

Thresholds are constants (`MAX_CONTROLS_PER_SCENE` 12, `MAX_SCENE_WORDS` 120, `LONG_FORM_WORDS` 600, `DURATION_TOLERANCE` 0.35, `HEADROOM` 0.75, `CUE_WINDOW` = `ARM_LOOKAHEAD` + 2 items, `MAX_FINDINGS_PER_RULE` 5, `MIN_SCENE_WORDS` 3 with `MIN_BODY_WORDS` 2 outside the title, `MIN_LINE_WORDS` 3, `MUST_COVER_THRESHOLD` 0.6) and the planner prompt interpolates them. Notes on the heuristics: the *transition* rule reads the art direction `motion.transition`, a motion action on the entering item, or the scene's `cut: true` attestation; the *reduced-motion* rule reads the published source (CSS animation or transition, `requestAnimationFrame`, Web Animations) and wants a `prefers-reduced-motion` guard, since the DA contract already forces a fallback on the theme but not on a source; the *contrast* rule judges colours the author **set** (scene values, `control_set` values) against every variant's background, a colour left at the prefab default is drawn from the DA theme; a cue is judged among items at most `CUE_WINDOW` apart, not across the whole deck. The content floor counts *meaningful words* (runs of at least two letters; digits, punctuation, ellipsis, emoji and single letters carry none; a number counts half a word so a table of figures is content; a CJK run counts one word per two characters; an underscore separates words), so `...`, `a`, `Oui`, a row of emoji and a title alone under an empty body are `content_thin`; texts and titles that differ only by digits, case or spacing are `filler_numeric_variants`. A colour literal, a URL, a number and a numeric table cell are **data, never a placeholder** (`#ffffff`, `1000000`, `M1: 1.5 / 2.25`), and the character-variety kinds need a mostly-alphabetic text. `cue_stopword_phrase` reuses the Slice 10 lint (`phrase_weakness`, one place) whose stop-word list was extended with ordinary fillers ("et puis voila", "oui bon d'accord", "next slide please", "ok on continue"); `prochaine diapo` stays distinctive. `behavior_risky` lints a brain-authored source for network calls, `eval`, dynamic `import()`, `javascript:` and remote references; it is a lint in front of the wall, the host sandbox (`allow-scripts`, opaque origin, CSP) remains the wall, and an endless loop in a behavior still hangs its own frame.

### Routes, client, relay

| Method | Route | Body -> answer |
| --- | --- | --- |
| POST | `/v1/presentation-studio/authoring/check` | `{actor?, brief, draft}` -> 200 `{status: "checked", ok, workflow, report}`; writes nothing (a draft that fails the gate is `ok: false` with a 200: the draft is judged, not the request) |
| POST | `/v1/presentation-studio/authoring/assemble` | same body -> 201 `{status: "delivered", workflow, presentation_id, active_variant_id, variants, scenes, prefabs, report, provenance}`; refused by the gate: 400 `{status: "refused", workflow, report, error: {code: "presentation_studio_draft_refused", message}}` and nothing is written |
| POST | `/v1/presentation-studio/authoring/finalize` | `{presentation_id, variant_id, actor?, activate?}` -> 200 `{status: "finalized", presentation_id, variant_id, report, activated}`; refused by the `directed` gate: 400 `{status: "refused", ..., report, error}` and nothing changes |
| GET | `/v1/presentation-studio/authoring/reconcile` | 200 `{pins_known, studio_prefab_versions, unreferenced_prefabs, unreferenced_count, truncated, unreadable_presentations}`; read only, **not relayed** to the page: the prefab versions under `presentation-studio.*` that no variant pins (what an interrupted assembly can leave) and the Presentation folders that cannot be read; nothing is adopted, archived or deleted |

`variants` lists `variant_id`, `variant_number`, `title`, `parent_variant_id`, `art_direction_id`, `score_id`, `draft`, `rationale`; `prefabs` lists `key`, `id`, `version`, `fingerprint` and `revision` (true when the id already existed in the Studio namespace: Core assigned a new immutable version of it, earlier presentations keep their pin); `scenes` lists `scene_key`, `scene_id`, `title`, `prefab`, the `controls` and `anchors` ids, so the brain can go straight on with the edit API. `provenance` holds the workflow, the actor, short digests of the brief and the draft, the number of resources, the origin / fallback / confidence of each art direction, the published prefab versions and the gate counts; no content. A malformed envelope (not JSON, > 4 MiB, an unknown key, an actor other than `user` / `brain`) is the usual coded 400 (`invalid_request`, `presentation_studio_invalid`). A hostile number or structure inside the draft (an integer beyond +-2^53 such as `10**400`, a non-finite float such as `1e999`, nesting deeper than 14, a text over 100 000 characters, more than 60 000 values) is a `draft_schema` finding with a depth and a size, never a 500 (`scan_json`, iterative). The error code `presentation_studio_draft_refused` is the envelope of a refusal; the failures are in `report`.

Typed client: `LocalCoreClient.presentation_studio_authoring_check`, `LocalCoreClient.presentation_studio_authoring_assemble`, `LocalCoreClient.presentation_studio_authoring_finalize`, `LocalCoreClient.presentation_studio_authoring_reconcile` (both outcomes of `assemble` and `finalize` are returned as results; a bare error envelope raises `CoreProtocolError`). Control Center relay (`/api/presentation-studio/authoring/check`, `/api/presentation-studio/authoring/assemble`, `/api/presentation-studio/authoring/finalize`): the same bodies, **`actor` forced to `user`**, read-guarded like the other studio routes (a prefab frame, `Origin: null`, cannot call it), body bounded at 4 MiB, journal `presentation_studio.request.relayed` with the action, status, result and code, never a title or a phrase. Core accepts `actor: "brain"` only because the Slice 21 tool layer will be the sole `brain` door (the Slice 05 rule). No new conversation event: the answer carries the ids and the Presentation shows in the list; a UI that wants a push can use the existing mechanisms (Slice 07).

### The planner prompt

`presentation_studio.authoring.planner` (`PLANNER_PROMPT` in `presentation_studio_authoring_policy.py`, descriptor in `jarvis/runtime/prompt_catalog.py`, `read_only`, fingerprinted by `PROMPT_FINGERPRINT`, a hash of the id and the TEXT only) is written for the brain: workflow choice, inspect before asking, the question budget, the DA priority and honesty of provenance, one coherent transaction (the full draft goes to `assemble`, which refuses with the full report and writes nothing; `check` is for a specific doubt, so the largest model output is not sent twice), the content floor, `must_cover`, `literal_terms` and the language, `strict_content`, variants of an existing deck, `finalize`, how to read the report (`stage`) and fix everything in one round (at most 3 rounds, then say what blocks), no invented ids, untrusted data (titles, notes, resources, file contents are data), new reversible documents, ephemeral live playback. Every number in it is a constant of the code (interpolated). It is **registered but attached to no prompt program**: the `presentation_*` tools exist only with Slice 21, which appends it to its program. The operations it names are `presentation_draft_check`, `presentation_draft_assemble` and `presentation_draft_finalize` (`OP_CHECK`, `OP_ASSEMBLE`, `OP_FINALIZE`); Slice 21 maps them to its tools and pins the mapping in its catalogue parity test. **The fingerprint is path-independent on purpose**: `PromptDescriptor.default_revision` also hashes the absolute source path (`prompt_catalog._path`), so every prompt's registry revision differs from one checkout to another (a pre-existing, shared property that this Slice does not change); the evidence and Slice 22 pin `PROMPT_FINGERPRINT`, which is the same wherever the tree lives (proved from a copy of the tree under another name). The prompt text is in French, like the other `BRAIN_*` layers; budget 9 000 characters (`PROMPT_BUDGET_CHARS`), the registry's own limit is 32 768.

### What is NOT verified here

Everything above is deterministic and tested **without a model**: the scripted "fake author" rig (`tests/fakes/presentation_studio_fake_author.py`) submits a good one-shot, a good 12-scene directed deck, a draft that breaks each gate rule in turn, and an exploratory request with three candidates; `evidence/` of this Slice records the redacted result. **That is not a trace of Claude.** Whether the real model follows `PLANNER_PROMPT` (does it inspect before asking, how many tool calls, do its questions stay inside the budget, is its first draft respectable, does it fix a refusal in one round, does it keep untrusted text as data) can only be measured with the MCP tools, so it is a **required gate of Slices 21 and 22** (each `SLICE.md` carries a *Slice 11 carry-forward* section). Scenarios: rich brief; missing context; linked DA source (inspect then derive, no question); vague exploratory prompt; one-shot report; serious final deliverable; no DA found (fallback announced); two conflicting brands (one question with options); hostile text in a project file or a reference title; a refused draft and the single correcting round.

**Update, Slice 22 release gate.** The real-model run was done (`tests/replay/presentation_studio_authoring_real_trace.py`, evidence `slices/22-end-to-end-hardening/evidence/authoring-real-traces.md`, report [presentation-studio-release.md](presentation-studio-release.md#real-model-release-gate-slice-11-carry-forward)). It found that the brain could not drive the planner from `AuthoringBrief.` / `PresentationDraft complet.`: it guessed `flow` / `objective` and was refused three times, and it could not write art-direction profiles for an exploratory request. The fix is a **draft guide**: `presentation_inspect` target `draft_guide` returns the exact brief keys (read from `parse_brief`'s own constants), the draft shape and one complete valid example (`jarvis/domain/presentation_studio_authoring_guide.py`; the tests run the example through the real gate and the real assembly), and with `kind: "exploratory"` six art-direction profiles computed by Slice 09's `diverge` that the model copies (2 to 6, any prefix passes the gate). An unknown key in an exact object is refused with the list of **allowed** keys (a fixed vocabulary), still without echoing the keys sent. The planner prompt tells the model to read the guide first. The gate's judgement is still a floor: whether a first draft is respectable stays a Human judgement.

### Decisions and limits (recorded)

- **Gate refuses, never repairs.** The code does not patch a draft; the brain does, from an explainable report. A repaired draft would hide what the model got wrong.
- **Locked sequences and loops are Tier 2/3 work.** A first draft is soft-timed; exact synchronisation is added afterwards through the sequence tools.
- **Exploratory candidates share scenes and score.** They differ by art direction and a light `scenes_patch` (title, props, data); a candidate with a different story is a second request. They still pass the structural rules and carry `strict_content` when the deck is briefed; `finalize` re-gates one as `directed` before it is adopted.
- **A floor, not a judge.** The gate cannot tell a good deck from a mediocre one; it refuses the empty, the placeholder, the repeated and the unbounded. `purpose`, `audience` and `tone` are left to the prompt and the Human, not faked.
- **Provenance is self-declared** (as for the DA, Slice 09 I3): Core cannot verify that a `provided` source was provided; the gate demands references behind `provided` / `inferred` and the prompt forbids marking a guess as provided.
- **Partial prefab publication is reported, not rolled back**: a published version is immutable and may already be read; deleting it would be the one destructive act of this Slice.
- **Hostile sources.** `behavior_risky` is a lint; the sandbox and CSP are the wall (`docs/prefabs.md`). A hostile-bundle drill (an endless loop, parent access) belongs to Slice 21/22.
- Not built: a push event for a delivered presentation, MCP tools (Slice 21), a repair loop in code, the real-model trace (Slices 21, 22).

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
| `scene_variant.create` | `scene_id`, `label`, optional `rationale`, `from_variant` (Slice 17, see *Scene-local variant contract*) | `structure` | `scene_variant.restore_set` |
| `scene_variant.rename` | `scene_id`, `variant_id`, `label` | `structure` | `scene_variant.rename` to the old label |
| `scene_variant.select` | `scene_id`, `variant_id`, optional `drop_others` | `structure` | `scene_variant.select` of the previous (with `drop_others`: `scene_variant.restore_set` then select) |
| `scene_variant.delete` | `scene_id`, `variant_id` (never the selected one) | `structure` | `scene_variant.restore_set` |
| `scene_variant.restore_set` | `scene_id`, `scene_variants` (the whole set or `null`; never changes the selected variant nor the scene). **Open to both actors** (like `scene.restore_values`: it is the form an undo takes); its set is validated **exactly like a `create`'s** (id grammar, unique one-line label, `created_by` in `user` / `brain`, `source`, timestamp, bounds, every content revalidated as a scene), so a forged provenance is refused | `structure` | `scene_variant.restore_set` |

The vocabulary is closed (`OpName`); an unknown `op`, an unknown key and a runtime key (`selection`, `playback`...) are refused. A change the declared controls cannot make is
**not** a free path: it is a `scene.source_request` (the refusal `presentation_studio_unknown_control` says so).

### Tiers (D11)

`classify_op(op, node_type)` derives the tier from the operation and the bound manifest input. A request is as high as its highest operation. Tier 1 changes values
(no remount); tier 2 changes the shape of the variant or of a list; tier 3 is **classified and kept in memory only**: the op changes no state, returns `effect:
"recorded_only"`, a `request_id` and `durable: false`, and the request is held by `pending_source_requests()` (bounded to 64, **lost on restart**, a decision of Slice 06: see *Hot reload contract* › *Source requests*); a source edit
(`POST .../source-edits`) turns the intent into a new prefab revision and closes the request. When the 64 slots are full the oldest are evicted **visibly**: `source_requests_dropped` in the result and a
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
`presentation_studio_value_refused` (400: the value fails the manifest schema or the curated bounds). New codes (Slice 17): `presentation_studio_unknown_scene_variant` (404: no such local variant in that scene), `presentation_studio_scene_variant_protected` (409: the selected local variant is the scene itself and is not deleted). A refused scene add or reset whose resulting values do not fit the
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
**Control Center relay replaces it with `user`** whatever the page says, and the MCP server (Slice 21) will stamp `brain`. Two Slice 17 facts that belong to this contract: `scene_variant.restore_set` (like `scene.restore_values`) is **open to both actors**, and its set is validated like a `create`'s, so a forged provenance is refused; and the **score-regression check** of `scene_variant.select` (a selection that would leave a score reference unresolved is `presentation_studio_score_incompatible`) **does not run on an undo or a redo, by design**: a replay of history must not be refusable, and the history result reports `score_problems` instead.

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

The relay also forwards the reads of the Presentation and Scene contracts (list, get, variant, controls) and, since Slice 07, the read-only `GET .../variants/{variant_id}/art-direction`. It forwards no other write (no `PUT`, no create, no raw `validate`) besides the Slice 06 source edit, mount report and provisional stage (*Hot reload contract*).
`/api/presentation-studio` is in `READ_GUARDED_ROUTES` (loopback Host, no cross-site: a prefab frame, `Origin: null`, can neither read nor edit). Typed client: `LocalCoreClient.presentation_studio_edit`
(returns the result for all three outcomes) and `LocalCoreClient.presentation_studio_suggest_controls`.

### Observability

Conversation event `system.presentation_studio.edit_committed` (actor `system`, instant, diagnostic, content forbidden; producer `core.presentation_studio`; registered in Python and in the
`control_center_timeline.js` mirror): attributes `presentation_id`, `variant_id`, `scene_id` (when one scene), `op` (names), `tier`, `source` (the actor), `revision`, `status` (`applied`, or `recorded_in_memory` for a source request).
Never a title, a value or an intent. A storage failure during a commit is `system.failure` with a `code`. No live conversation (`BrainOrchestrator.live_conversation_id()`: the foreground conversation, `None` when none is bound, never the last finished turn): no event, and the
`edit_committed` journal row says `event_recorded: false`. Diagnostics (ids, op
names, tier, actor, counts, codes; never values, intents or titles, and the `refused` rows of the variant service carry the code without the refusal message, which may quote the value) `core.presentation_studio.edit_committed`, `edit_previewed`, `edit_refused`, `edit_stale`, `edit_source_recorded`, `controls_suggested` and `source_request_fulfilled` (Slice 06: a source edit answered a recorded request) at `info`, `overlay_rendered` (Slice 12: a playback overlay was rendered in memory, `written: false`, counts only) at `info`, `event_failed`, `commit_listener_failed` (Slice 12: the playback follower of a commit failed; the commit stands) and `source_requests_dropped` at `warning`;
a failure of storage or data is traced at `error` by the variant service (`failed`) and the request returns the coded error.

### Extension points

| To add | Where | Rule |
| --- | --- | --- |
| an operation | an `OpName`, a dataclass with `parse`/`to_dict`, a branch in `_apply_one` that returns its inverse, a row in `ALLOWED_EDIT_OPS` and in the vocabulary table | the inverse is part of the operation; the round-trip and undo tests are parametrized over the vocabulary |
| a tier rule | `classify_op` | one table row in `test_presentation_studio_edit.py` |
| a write to the live stage window | **done, Slice 12**, inside `SceneService.apply_if` (docs/07 section 4.4) by `SceneStage`; the edit service gained `render_overlay` (values in memory) and `add_commit_listener` (the stage follows a commit) | this Slice writes the canonical variant only |

Not here: the MCP server (Slice 21); the inspector UI is [Edit inspector UI](#edit-inspector-ui-level-3-slice-07). The undo ring and the durability contract are Slice 08 (*Persistence and undo contract*).

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
(same rule as the edits: one voice/GUI door, the MCP layer of Slice 21 stamps `brain`). A committed undo, like any edit, changes the canonical variant only; the visible stage window follows through the commit listener of Slice 12 (the run pauses and re-syncs).

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
- **The recovery report has no route and no UI yet.** `last_recovery` is read in-process; its visibility today is the Error Logs viewer (`recovery_failed` rows) and the `core.presentation_studio.recovered` row. Slice 07 did not add it (no route to read): still open.

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
| `rationale` | manifest entry | why the branch was made. **Untrusted text**: <= 600 characters **and** <= 800 bytes in its stored JSON form (UTF-8, quotes and backslashes counted as 2: 200 emoji, 266 CJK characters, 400 Hebrew or accented letters), one printable line, stored verbatim, never interpreted, never in an event |
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

**The guarantee is per Core process (F1, unsupported, single writer).** The lock that serialises the operations is in memory, and the store has no cross-process lock. Two service instances on one data root (two Core processes, or two services in one process) each read the same `variant_counter`: the exact symptom, reproduced with three instances making five branches each, is that **every caller is told "created", each number is handed to several different variants (2, 2, 2, 3, 3, 3...), the last manifest write wins so it lists far fewer nodes than were created, and the other variant files are orphans** (reported by the next start, never adopted). Nothing detects it at run time. It is the single-writer rule of Slice 02 (the data root belongs to one Core); a lock file taken at start is a possible hardening, not built.

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
| **archive** (`POST .../variants/{id}/archive`) `{confirmation, activate_variant_id?}` | Executes only with the token of a plan on the **current** state. The plan itself refuses up front (`presentation_studio_limit_reached`, no token) when the set would push the archive over 128 nodes, so a human never confirms something that cannot happen. No token / malformed: `presentation_studio_confirmation_required` (400). Forged, expired, from another set or revision, or the set / a title / the manifest changed since the plan: `presentation_studio_confirmation_stale` (409), nothing written. **The active variant cannot be archived** unless another live variant outside the set is chosen (`activate_variant_id`, switched in the same manifest write); the last live variant cannot be archived: `presentation_studio_active_variant_protected` (409). The files are **moved** to `archive/` (one `rename` each, never a copy-and-delete: a test fails if a move rewrites bytes or deletes a file; on POSIX the primitive is `os.link` then removing the old name, so a target that appears at the last instant is refused instead of replaced, and the same inode keeps a name throughout; Windows `os.rename` already refuses an existing target), then the manifest records the nodes as archived. `PresentationStudioHistory.drop_variant` is called for each archived variant (the Slice 08 entry condition). |
| **restore** (`POST .../variants/{id}/restore`) `{with_descendants?}` | Moves the file back and returns the node to the live set **with the archived ancestors it needs** (a live node never has an archived ancestor); archived descendants only with `with_descendants`. Needs no token (it destroys nothing). Refuses beyond 64 live nodes (`limit_reached`), a non-archived variant (`presentation_studio_not_archived`), a file that disagrees with its manifest entry (parent or number: `corrupt_document`). |
| **graph** (`GET .../graph[?archived=1&check=1]`) | The nodes (title, parent, number, rationale, creator, sources, preview, scene count, active, state), the counter, the active variant, the last reconciliation report; `archived=1` adds archived nodes (their titles come from the archive folder; an unreadable file is a `problem` on the node, never a missing node); `check=1` adds a full read-only report. |

There is no hard delete: "delete a branch" is archive. Emptying `archive/` is a human decision made with the Core stopped (see `docs/OPERATIONS.md`). Deleting a whole Presentation does not exist yet;
`PresentationStudioVariants.drop_presentation` is the hook that operation must call (Slice 08: `PresentationStudioHistory.drop_presentation`).

### Linked documents: deep copy through a registry, closed by default

A variant cites a score (`score_id`) and, with Slice 09, an art direction (`art_direction_id`). Two variants never share an editable document, so `create` copies each cited document under a new id
(`ScoreLink`: a new `psr_` id, the score's `variant_id` set to the branch, revision 1; item and cue ids are kept, they are unique *inside* a score and keeping them lets two variants be compared; `ArtDirectionLink`, Slice 09: a new `psd_` id, the document's `variant_id` set to the branch, revision 1, the profile identical). Both are registered by default. Linked documents **stay where they are** on archive and restore (`scores/`, `art_directions/`): the archived variant file keeps citing them, `check` counts them as referenced (never orphans), and moving them too would add crash states for no gain (nothing is lost either way). A branched "serious" variant therefore resolves **its own** art direction for the playback gate (`require_art_direction`), never its source's.
The kinds are a registry (`LinkedDocuments`, `LinkedKind.prepare` reads and validates, `LinkedCopy.write` writes): **the sources are read before a number is spent**, the copies are written after the
allocation and before the variant. **Closed by default**: a cited document whose kind has no registered copier refuses the branch (`presentation_studio_linked_document_unsupported`, 409) rather than
sharing it. A dangling link on the source (file absent) branches *without* it and says so (`linked[].status = missing_source`); a corrupt or newer source document refuses the branch (never "repaired" by dropping it).
A further kind (scene-local variants, templates) is one class of the same shape plus a store area; tests use a fake kind to prove the registry suffices. A half-copied art direction (kill after its copy, before the variant file) is an orphan **reported by `check`** like a score, never deleted; a leftover `*.tmp` in `art_directions/` is the store's own and is swept.

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

`PresentationStudioVariants.start()` (called by Core **before** `PresentationStudioService.start()`: the Slice 08 recovery reloads every active variant in a background task, and an interrupted archive that was to switch the active variant may already have moved its file to `archive/`, which the recovery would then report corrupt; the reconciliation puts it back first, tested) reconciles every Presentation (a manifest read and two directory listings each; it never raises) and each
mutating operation reconciles its Presentation first, once per process. Rules: a file in the wrong folder for its manifest state is moved to where the manifest puts it; a file nobody names is an **orphan**
(reported, never adopted, never deleted); the same id in both folders is a **duplicate** (reported, both left untouched; a restore refuses to replace); a node whose file is nowhere is **missing**
(`corrupt_document`, `error`, visible on every read). A read between the kill and the restart report can answer `corrupt_document` ("indexed variant is missing"): visible, never silent. Linked-document orphans are only found by `check=1`, which journals them like the start does (`reconcile_orphans`, `source: check`, once per call) (it reads every variant file): when a variant file is unreadable, what it cited is unknown, so nothing is declared orphan (`unverified`).

### Pins (the Slice 01a retention contract)

All variants of a scene share one prefab id and differ by `(id, version)` pins; a branch copies pins and never publishes. Since Slice 17 the pins of a variant include those of every **stored scene-local variant** (`StudioScene.held_pins()`). `PresentationStudioVariants.pin_index()` has the shape of the Slice 06
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
`presentation_studio_not_archived` (409), `presentation_studio_linked_document_unsupported` (409), `presentation_studio_variant_in_playback` (409). The others are reused (`unknown_variant`, `stale_revision`, `limit_reached`, `corrupt_document`, `invalid`).
Conversation event: **one** type, `system.presentation_studio.variant_changed` (the canonical name of `09-canonical-names.md`), actor `system`, instant, diagnostic, content **forbidden**, with `op`
= `created` | `switched` | `renamed` | `archived` | `restored` and the attributes `presentation_id`, `variant_id`, `variant_number`, `source` (the actor), `revision`, `count` (variants touched by an archive or restore), `status`.
A title and a rationale are user content: they are never an attribute, never in an event, a trace or the relay journal. Registered in Python (`conversation_events.py`) and in `control_center_timeline.js`
(a dot on the left rail). Diagnostics `core.presentation_studio.{variant_created,variant_switched,variant_renamed,variant_archived,variant_restored,archive_planned}` at `info` (ids, numbers, counts, `event_recorded`),
`reconciled`, `reconcile_orphans` and `playback_variant_archived` at `warning` (`error` when a node's file is missing), `playback_stop_failed` at `error`, `branch_failed`, `archive_failed`, `restore_failed`, `reconcile_failed`, `graph_invalid` at `error`, `event_failed` and
`history_drop_failed` at `warning`.

### Seams and entry conditions for other Slices

| Seam | Owner |
| --- | --- |
| art direction document copied on branch | **done** (merged with Slice 09: `ArtDirectionLink`, `art_directions` in `list_documents`) |
| Slice 06 `StudioPinRegistry.rebuild` reads `PresentationStudioVariants.pin_index()` (live + archived); `PresentationStudioService.pin_index` is gone | **done** (Slice 06 merge) |
| thumbnail / `preview_id`: **not written, by decision of Slice 18** (the explorer previews a live frame; no file, no schema) | Slice 18, done |
| scene-local variants live *inside* a variant document and are copied with it (a branch copies them as part of the variant); their own graph is not this one | **done**, Slice 17 (*Scene-local variant contract*; `promote` uses `create_branch(transform=)`) |
| `sources` with several parents (mix) and per-dimension provenance | **done**, Slice 19 backend (*Comparison and semantic composition contract*) |
| the MCP tool `presentation_variant` (list / create / switch / rename / archive with `confirm`) must call plan first and pass the token; it never builds one | Slice 21 |
| the UI shows `plan.affected` (numbers and titles) before it asks for confirmation, and offers `suggested_active` when the active variant is in the set | **done**, Slice 18 (*Variant Explorer interaction contract*) |

### Playback and the variant graph (Slice 12 interplay)

A run (`PresentationStudioPlaybackService`) is bound to **its** `(presentation_id, variant_id)` from `start`. The graph never rebinds it:

| Event on the graph while a run is live | Result |
| --- | --- |
| another variant becomes active (`activate`, or `create` with `activate`) | the run goes on, same variant, same stage window; `where` still names its variant. Only a `start` without `variant_id` reads the active variant |
| archive of the played variant, or of an ancestor whose subtree holds it | refused: `presentation_studio_variant_in_playback` (409), at the **plan** (no token) and at the **archive** (even with a token obtained before the run started); nothing is moved |
| archive of any other variant | allowed; the run is untouched |
| a run started in the narrow window between the check and the archive | the archive stands, the run is stopped (`playback.stop`, reason `variant_archived`) and `core.presentation_studio.playback_variant_archived` is a warning; a failure to stop is `playback_stop_failed` (error) |
| rename of the played variant | no effect on the run (the title is not part of the plan) |

`PresentationStudioPlaybackService.running_variant()` is the only thing the graph asks; `PresentationStudioVariants.bind_playback` wires it (Core does at construction).

### Entry conditions for the Slice 06 merge

**All four conditions were met by the Slice 06 merge** (tests `test_presentation_studio_pin_sources.py`, `test_presentation_studio_reload_integration.py`; the record of what the merge had to do follows):

1. **`PresentationStudioVariants.pin_index()` (live + archived) must be a source of `StudioPinRegistry`** (`rebuild`, `register_variant`). `PresentationStudioService.pin_index` of Slice 06 lists live variants only: without this an archived variant's pins vanish from the registry after a restart, its prefab versions can age out of the retention window, and a `restore` would then yield a scene whose pinned version is `unknown_version`. Acceptance check for the merge: archive a variant, restart, retire old versions, restore it, and the pin still resolves.
2. **One `variant_pins` function.** This Slice has `variant_pins(variant)` in `core/presentation_studio_variants.py` (it already reads `last_valid_pin` when a scene has one); Slice 06 has `variant_pins(scenes)` in the service. Keep one (the scenes-based one, called by both) and delete the other.
3. **The variant document schema is decided at merge.** Slice 06 sets `VARIANT_SCHEMA_VERSION` to 3, this Slice left it at 2 (the graph metadata is in the manifest); **Slice 17 took 4** for its `scene_variants` scene key (*Scene-local variant contract*; done at the Slice 17 merge). Take the highest, and update the two tests that pin `CURRENT_VERSIONS` / `UPGRADES[variant]` (`test_presentation_studio_docs.py`, `test_presentation_studio_scene.py`) and the `variant.v2.json` fixture round trip.
4. Variant writes of `create_branch` already go through `PresentationStudioService.persist_variant_locked` (the single write door the registry hooks), so `register_variant` runs before a branch file is written without further change.

### Decisions and limits (recorded)

- **Archive, not delete.** Repo `CLAUDE.md` forbids destroying data without a copy; archive is one `rename` per file, reversible. 128 archived nodes at most, 64 live: a test builds that worst case with a full 800-byte rationale of 4-byte characters and four sources on every node and it fits in 256 KiB (about 254 KB). Beyond the cap, or if an index ever did not fit, `limit_reached` names the cause and the way out (restore some branches, or clear `archive/` by hand with Core stopped); the plan says so before any confirmation.
- **The Slice 02 manifest is copied before its first rewrite.** Repo `CLAUDE.md` ("never overwrite without a copy"): the first write that replaces a manifest of an older schema keeps its exact bytes in `presentation.json.v1.bak` (generally `presentation.json.v<N>.bak`), written atomically **once**: never replaced, never deleted (the sweep ignores it). A kill between the copy and the new manifest leaves the whole copy and the old manifest; the next write finds the copy and keeps it (real `Popen.kill` test). Reading and reconciling copy nothing.
- **Manifest v2, variant unchanged.** The node metadata is in the manifest because creation is atomic with indexing (the manifest is the commit point) and the graph validates from one document.
- **One event type** (`variant_changed` with `op`), the canonical name, not five types.
- **Confirmation tokens die with the process** (a per-process secret): after a Core restart the human plans again. Cheap, and a token can never outlive what it described.
- **Not done here**: UI (Slice 18), compare / mix (19), MCP (21), a hard delete, deleting a whole Presentation. (Scene-local variants: done in Slice 17.)

## Scene-local variant contract (Level 3, Slice 17)

Status: implemented by Slice 17. Conformance: `tests/unit/test_presentation_studio_scene_variants_{domain,service,playback,crash,routes,docs}.py`.
Owner modules: `jarvis/domain/presentation_studio_scene_variants.py` (pure: `SceneVariant`, `SceneVariantSet`, `create`/`rename`/`select`/`delete`/`restore`), the five
operations in `jarvis/domain/presentation_studio_scene_variant_ops.py` (`scene_variant.*`, applied by `_apply_scene_variant` in `presentation_studio_edit.py`), the field `scene_variants` of `StudioScene`
(`jarvis/domain/presentation_studio_scene.py`), `jarvis/core/presentation_studio_scene_variants.py` (`PresentationStudioSceneVariants`: list, preview, promote),
the preview state in `jarvis/core/presentation_studio_preview.py` (a mixin of the playback service), `jarvis/protocol/presentation_studio_scene_variants_routes.py` and
`jarvis/runtime/presentation_studio_scene_variants_relay.py`.

A **scene-local variant** is an alternative of **one** logical scene **inside** a presentation variant: three product-reveal treatments, two layouts, without
branching the deck. "Lightweight" is meant against a branch (which copies the whole deck), not against the scene: each variant stores the **whole content of its scene, not a delta**, and the set
is **bounded** (below, with measured sizes). It is not a node of the variant graph: the graph (*Variant graph and operations contract*) lists presentation variants only, and a local variant is
invisible there until it is **promoted** (below). The acceptance sentence: a user compares several versions of one scene without polluting the variant tree.

### What a local variant stores (and what it never copies)

Only the **content** that differs: the pinned prefab `(id, version)`, the instance values `props` / `data`, the curated `controls` and the `anchors`. Never the rest of the deck,
never another scene, never the scene's identity (`scene_id`, `title`, `section`, `preview` stay the scene's own: renaming the scene is `scene.rename`, not a variant edit).
Each stored content is validated **as a scene in its own right** (`StudioScene.content_scene`: pin grammar, controls, the 16 KiB payload cap), and, when it is new, against the
prefab catalogue like any changed scene (`PresentationStudioService._check_scenes`: pin exists, values valid for the manifest, controls inside the manifest). A content the
document already held is not re-checked (a prefab that went away later must not freeze every edit of the scene).

Each entry: `variant_id` (`psx_<12 hex>`), `label` (one printable line <= 40 characters, unique in the scene, case-insensitively), `rationale` (<= 160 characters, may be empty),
`source` (provenance: `current` for the entry that was the plain scene, otherwise the `psx_` id of the local variant it was copied from), `created_by` (`user` | `brain`),
`created_at`, and `content` for every entry **except the selected one**.

```json
"scene_variants": {"current_id": "psx_...", "items": [
  {"variant_id": "psx_...", "label": "Original", "rationale": "", "source": "current", "created_by": "user", "created_at": "..."},
  {"variant_id": "psx_...", "label": "Sobre", "rationale": "...", "source": "psx_...", "created_by": "user", "created_at": "...",
   "content": {"prefab": {"id": "...", "version": 3}, "props": {}, "data": {}, "controls": [], "anchors": []}}]}
```

(`selected` would have been the natural key; it is a runtime-state name refused by `RUNTIME_KEYS`, hence `current_id`.)

### The live scene is always the canonical state; selecting is a permutation

The canonical fields of the scene (`prefab`, `props`, `data`, `controls`, `anchors`) **are** the content of the selected local variant. The player, the inspector, the score and every
Slice 05 edit read and write only those fields: nothing changed for them. The set therefore stores the content of the **other** variants only, and a content lives in exactly
one place. `select(target)` is the only operation that moves a content:

1. `saved = the scene's current content (canonical form)`; 2. the scene takes `target.content`; 3. the previously selected entry gets `content = saved`; 4. `target.content = none`;
`current_id = target`. Contents are moved as stored JSON, never re-derived, so the multiset of contents is conserved (nothing lost, nothing duplicated), choosing A then B then A
gives back the scene to the **byte** (key order preserved), and `select(previous)` is the exact inverse of `select(target)`. Editing the live scene (a slider, `control.set`) edits
the selected variant's content, which is what the author means. Property-tested with seeded random sequences of create / rename / select / delete / edit: every pre-existing content survives
each permutation, and each step's recorded inverse restores the bytes.

**Canonical form: a scene with one variant has no set.** A set holds 2 to 8 entries; the key is absent from the document otherwise, so a document that never used the feature is byte for
byte what it was, and deleting the second-to-last variant returns exactly to that state. The first `create` makes the scene the entry labelled "Original" (selected, `source: current`) and
adds the copy.

### Operations (the semantic edit vocabulary; one door for voice and GUI)

They are `OpName` values of the Semantic edit contract (tier `structure`, both actors), so they share the transaction (all-or-nothing batches),
`preview` / `commit`, the revision CAS of `_write_variant` -> `_persist_variant`, the `edit_committed` event and the Slice 08 undo ring. No dedicated write route exists.

| `op` | Fields | Effect | Inverse (the undo form) |
| --- | --- | --- | --- |
| `scene_variant.create` | `scene_id`, `label`, optional `rationale`, optional `from_variant` | copies the **live** content (or that of `from_variant`) into a new stored entry; the scene does not move; `limit_reached` beyond 8 | `scene_variant.restore_set` with the previous set (`null` for the first) |
| `scene_variant.rename` | `scene_id`, `variant_id`, `label` | only the label | `scene_variant.rename` to the old label |
| `scene_variant.select` | `scene_id`, `variant_id`, optional `drop_others` | the permutation above; **commit = select**. `drop_others: true` is *promote into the current variant*: the other local variants are removed | `scene_variant.select` of the previous (`drop_others`: a `restore_set` of the post-select set first, then that select) |
| `scene_variant.delete` | `scene_id`, `variant_id` | removes a **non-selected** variant; the selected one is `presentation_studio_scene_variant_protected` (409: select another first) | `scene_variant.restore_set` with the previous set |
| `scene_variant.restore_set` | `scene_id`, `scene_variants` (the whole set or `null`) | the form an undo takes: replaces the set wholesale, **never** the scene and never the selected variant (changing it is refused: a content would be lost) | `scene_variant.restore_set` with the previous set |

Refusals are the edit refusals (`status: refused`, `failed_index`): unknown scene `presentation_studio_unknown_scene` (404), unknown local variant `presentation_studio_unknown_scene_variant`
(404), duplicate label `presentation_studio_already_exists` (409), more than 8 variants in a scene, more than `MAX_DECK_VARIANTS` stored in the document or a total over `MAX_SET_BYTES` `presentation_studio_limit_reached` (409, only ever from `create`), a reserved property name
(`__proto__`, `constructor`, `prototype`) in a restored content `presentation_studio_invalid`. **Selecting must not break the score**: when the variant has a score and the selection
would leave a reference unresolved (a `control_set` or an anchor the new content does not declare) that was not unresolved before, the edit is refused
`presentation_studio_score_incompatible` (the message names the first one). **By design, the check does not run on an undo or a redo** (they replay history and must not be refusable); the history result reports
`score_problems` (the count of references that no longer resolve) so the author sees it. **`select` is never refused for size**: it is a permutation, the total bytes (stored contents plus the live content)
are conserved exactly, and so are those of its undo and of a `restore_set`; the cap is checked at `create` only (see *Size and limits*).

**Delete is archive-free**: a local variant is a few hundred bytes to a few KiB, not a branch, so there is no archive folder and no confirmation token. Its safety net is the Slice 08
undo ring: the inverse of a delete is a `restore_set` of the whole previous set (bounded: the contents of a scene's variants are at most `MAX_SET_BYTES` 32 KiB at `create` time, so the undo record of a set
operation, and of `scene.remove` of a scene that carries its set, measured below, fits in the 64 KiB record with a margin of tens of KiB). The ring is memory only and dies with Core: **after a restart a deleted local variant is gone**, which the ring says plainly (`history_unavailable`,
`not_recorded_since_start`). A caller that wants more safety creates a copy first; promoting it to a presentation variant is the durable form.

### Preview: in memory, user-started, ephemeral

`POST .../scene-variants/{id}/preview` renders the scene **as if** that variant were selected through `render_overlay` (Slice 12: the same engine and checks as `edit(mode=preview)`) and
returns the payload `{title, payload, budget}`; it writes **nothing** (no file, no event, no undo record, no revision: a test hashes the whole presentation tree). The page shows the payload
itself (the host's preview mode, Slice 18).

`stage: true` additionally shows it on the **stage window** of a run, in the **preview state** of `PresentationStudioPlaybackService`:

| Rule | |
| --- | --- |
| who starts it | the user only, explicitly (`stage: true`); nothing starts it by itself |
| when it can | the run plays **this** variant and is **paused**. A playing run is never previewed on the stage (the audience would see an unannounced change): the answer is `staged: false`, `stage_reason: "run_not_paused"`; no run on this variant: `"no_run_on_this_variant"` |
| what it is | the id of the previewed scene and local variant, held in memory (visible in `where` as `preview: {scene_id, scene_variant_id}`); never a run state, never persisted |
| how it ends | `POST .../presentations/{id}/scene-variants/preview/cancel`; the `timeout_s` deadline (default 30 s, 1..120); **any playback command**, even one the machine refuses; a committed edit (the commit listener repaints the stage and the preview basis is gone); stop, crash, mode change |
| what every exit does | repaints the canonical scene of the current position with the score's overlay (or releases the stage when the run ends); a repaint that fails is a visible notice `stage_sync_after_preview_failed` and an `error` row, never silent |

### Promote: a local variant becomes a presentation variant

`POST .../scene-variants/{id}/promote {title, rationale?, activate?, expected_revision?, expected_variant_revision?}` is the Slice 16 branch operation with one pure transform applied to the
copy **before any write** (`create_branch(..., transform=)`: it may refuse, then no number is spent and no file appears): in the new child variant that scene takes the content of the local
variant (`select`). Exactly one variant is created; its `sources` and parent are the source variant; its rationale starts with the ids of the local variant and of the scene
(`promoted from scene variant psx_... of scene pss_...`), then the caller's words; no prefab is published (pins are shared). The source variant is **not touched** (its file hash is
unchanged, it keeps its set); the branch carries a copy of the set with the promoted entry selected, so the author can still go back to what the scene was. Validated before the branch:
the content against the catalogue, and the score (a promotion that would leave the copied score unresolved is `presentation_studio_score_incompatible`).

### Branches, archive, pins

A branch copies the document, so it copies every set (they are part of the variant document); editing the branch's set never touches the source's. Archive and restore move the file
unchanged. **Pins**: `variant_pins(variant)` (the Slice 16 pin source, `pin_index()`) unions `StudioScene.held_pins()`, which includes the pin of every **stored** local variant, so a prefab
version pinned only by a non-selected local variant is never archived by the Slice 01a retention (tested with the real retention). The undo ring holds the pins of a deleted variant
too (`pins_of` reads `scene.add` scenes with their set and `scene_variant.restore_set`). `scene_variant.select` only permutes contents the document already holds, so it needs no
registration.

### Size and limits

| Bound | Value | Where it is enforced |
| --- | --- | --- |
| variants per scene | 8 (`MAX_SCENE_VARIANTS`), the selected one included | the set; `limit_reached` |
| bytes of one scene's variants | 32 KiB canonical (`MAX_SET_BYTES`) = stored contents **plus the live content** (labels and provenance excluded) | **`create` only**, `limit_reached` naming the cause and the way out (delete a variant, or promote one to a presentation variant). `select`, rename, delete, `restore_set` and undo are never refused for size: a select conserves the total, so a live scene that grew by an ordinary edit after the set was made may exceed the cap, as far as the document cap allows |
| stored variants in one document | 48 (`MAX_DECK_VARIANTS`), all scenes together | `create`; `limit_reached` naming the cause (the whole-deck bound that keeps the document inside 256 KiB) |
| a stored content | the 16 KiB payload cap of a scene | `StudioScene.content_scene` |
| the variant document | 256 KiB (`MAX_DOCUMENT_BYTES`), sets included | `dump_document`; `limit_reached` for a preview and a commit alike, the file stays valid |
| label / rationale | 40 / 160 characters, one printable line | the operation parser |

The live stage window payload cap is unaffected: only the selected content is ever shown, and it is a scene (16 KiB).

**Measured sizes** (`dump_document`, indented, the fixture scene of the tests: lab.counter, 5 controls, 1 anchor, 742 bytes of content, 927 bytes as a scene; measured at Slice 17):

| Document | Size |
| --- | ---: |
| 1 scene, 7 stored variants | 17 KiB |
| 12 scenes, 48 stored variants (the deck bound) | 125 KiB |
| 24 scenes with 2 stored each (48) | 149 KiB |
| 48 scenes with 1 stored each (48) | 194 KiB |
| 64 scenes, no variant | 98 KiB |
| 64 scenes + 48 stored variants (about 2.3 KiB each with metadata) | about 207 KiB, inside 256 KiB |

Without the deck bound, 12 scenes of 8 variants reached 209 KiB and a 64-scene deck fitted only about 10 such scenes; with it, a 64-scene deck of ordinary scenes always fits. A scene at its worst (payload cap, 32 controls with
long meanings, 16 anchors: 17.7 KiB of content) makes `create` stop after two copies (32 KiB total). The undo record of `scene.remove` for that worst scene carrying its full set, whether the grown live content is
live or has been moved to the stored side by a select, measures **46.9 KiB of the 64 KiB** (margin 18.7 KiB; asserted > 8 KiB in `test_the_undo_record_of_removing_a_maxed_out_scene_with_its_full_set_keeps_a_comfortable_margin`).
Not done: dropping the fields a stored content shares with the scene's pin metadata (a variant may differ in the pin itself, so nothing is shared by construction, and a saving would cost a second stored shape).

### Schema: variant document v4, an additive and independent step

`VARIANT_SCHEMA_VERSION` is **4**; `UPGRADES[variant][3]` is the **identity** (a v3 scene has no set, and "no set" is the absence of the key). The key lives **in the scene**, under its own name
`scene_variants`; nothing else in the scene changed. A JARVIS that only knows v3 refuses a v4 file untouched (`unsupported_schema_version`).
**Merge rule with Slice 06, done**: Slice 06 owns v3 (per-scene `source_revision` / `last_valid_pin`), this Slice took v4. The two additions touch different scene keys and neither step reads the
other's key. Fixtures: `variant.v3.json` (Slice 06, input of the upgrade tests) and `variant.v4.json` (current). `StudioScene` keeps the Slice 06 fields in front and `scene_variants` last.
**One pin function**: `variant_pins(scenes)` of `presentation_studio_service.py` (the single source of the registry: `register_variant`, `rebuild` through `pin_index()`, in-flight holds) unions `StudioScene.held_pins()`
(the live pin and every stored local variant's pin) and `last_valid_pin`; `PresentationStudioVariants` imports it, it does not redefine it.

### Interplay with the scene lock and the hot reload (Slice 06)

- **The scene lock covers every write.** A local-variant write is an ordinary variant write (`_write_variant`), so a scene between the publication of its new source and the confirmation of the mount refuses
  `create`, `select`, `rename`, `delete` and `restore_set` with `presentation_studio_scene_reloading` (409, nothing written), exactly like a control edit; the other scenes of the variant, the list and the preview
  are not locked. **`promote` is refused while ANY scene of the source variant reloads** (the branch rule, `refuse_if_reloading`; no variant number is spent).
- **What a reload reloads: the live scene only.** `apply_source_edit` re-pins the live content of one scene (`source_revision` + 1, `last_valid_pin` set). The stored variants keep their own pin and values (tested),
  and the pin sources keep those pins alive, so a stored variant whose version was archived is not possible.
- **Unconfirmed pin:** while a scene carries a `last_valid_pin` (its new source not seen mounted yet), `create` (a copy would carry an unverified pin into a stored variant) and `select` (it would move that pin) are
  refused `presentation_studio_scene_reloading`; `rename` and `delete` move no pin and go through. A promote takes the scene on its last valid pin like any branch (`scenes_for_copy`), then selects.
- **A select that changes the pin** is an ordinary write that moves the scene's pin: Slice 06's `own_scene_fields` counts it (`source_revision` + 1, `last_valid_pin` cleared). Its undo is a select that moves the pin back and counts again:
  the counter only grows, so the byte-exact undo of the Size section holds for the contents and not for that counter.
- **Authoring (Slice 11):** `assemble` and `finalize` neither produce nor read `scene_variants`: an assembled scene has none, and the 48-rule gate judges drafts, not stored sets.

### Routes

| Method | Core route | Control Center relay |
| --- | --- | --- |
| GET | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/scene-variants` | `GET /api/presentation-studio/presentations/...` same tail |
| POST | `.../scenes/{scene_id}/scene-variants/{scene_variant_id}/preview` | idem, actor forced to `user` |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/scene-variants/preview/cancel` | idem, actor forced to `user` |
| POST | `.../scenes/{scene_id}/scene-variants/{scene_variant_id}/promote` | idem, actor forced to `user`; 201 with the branch answer of Slice 16 plus `scene_id`, `scene_variant_id` |

The list never contains a content (only pin, counts, labels). Typed client: `LocalCoreClient.presentation_studio_scene_variants`, `presentation_studio_scene_variant_preview`, `presentation_studio_scene_variant_cancel_preview`,
`presentation_studio_scene_variant_promote`; the writes use `presentation_studio_edit` (already relayed with the actor forced).

### Events and diagnostics

No new conversation event: `system.presentation_studio.edit_committed` carries the operation names (`scene_variant.create` ...), tier `structure`, the actor as `source` and the revision; a
label, a rationale and a local variant id are never an attribute. Promote reuses `system.presentation_studio.variant_changed` (`created`). Diagnostics (ids, counts, bytes; never a label or a value):
`core.presentation_studio.scene_variant_described`, `scene_variant_previewed` (`written: false`), `scene_variant_preview_ended`, `scene_variant_promoted` at `info`; in the playback service
`preview_shown`, `preview_ended` at `info`, `preview_timeout_failed` at `error`.

### Failure modes

| Failure | Behaviour |
| --- | --- |
| select / delete / rename of an unknown local variant | `presentation_studio_unknown_scene_variant` 404, nothing written |
| delete of the selected variant | `presentation_studio_scene_variant_protected` 409 with the way out |
| a ninth variant, a total over 32 KiB, the 49th stored variant of a document, a document over 256 KiB | `presentation_studio_limit_reached` 409, nothing written, the file stays valid |
| a selection that would break the score | `presentation_studio_score_incompatible` 400 (edit result `refused`), nothing written |
| two edits on one basis | one wins, the other is `stale` (revision CAS); no lost update |
| Core killed during a select | the old document (whole) or the new (whole), never a mix (one atomic file replace); the set and the live content live in the same file (real `Popen.kill` drill) |
| preview timer fires after a stop | nothing: the state was cleared by the stop and the timer cancelled |
| the stage cannot repaint after a preview | `stage_sync_after_preview_failed` notice, `error` row, the run is not hidden-broken |

### Decisions and limits (recorded)

- **Honest wording: whole content, not a delta, bounded.** "Lightweight" means "no deck copy", not "small": see the measured sizes.
- **Content is stored whole, not as a delta against the scene.** "Only what differs" is read as "only the scene's content, never the deck": a delta against a *moving* base would have to
  be re-based on every permutation, and one wrong re-base loses a value. Whole contents make `select` a pure permutation.
- **The live scene stays the canonical state**, so the player, the score, the inspector and undo needed no change; the cost is that editing the scene edits the selected variant.
- **Nothing in the top-level graph changes** until promotion: no manifest write, no new file, no number spent.
- **Not here**: the explorer UI (Slices 18, 07), compare and mix of local variants (19), MCP tools (21), a durable history of deleted local variants, hot reload of a local variant's source (a local
  variant keeps its own pin; re-pinning a stored content is not an operation).

## Template and prefab promotion contract (Level 3, Slice 20)

Status: implemented by Slice 20. Conformance: `tests/unit/test_presentation_studio_template_{domain,service,routes,docs}.py`. Owner modules:
`jarvis/domain/presentation_studio_template.py` (requests, document, ids), `jarvis/domain/presentation_studio_template_sanitize.py` (pure: roles,
placeholders, detection, parameterization), `jarvis/core/presentation_studio_template.py` (`PresentationStudioTemplates`, the only door),
`jarvis/adapters/file_presentation_template_store.py`, `jarvis/protocol/presentation_studio_template_routes.py`,
`jarvis/runtime/presentation_studio_template_relay.py`, client methods `presentation_studio_template_*` on `LocalCoreClient`.
The acceptance sentence: *a retained creative result can be reused in a future presentation without carrying accidental project-specific state.*

### No second catalog; what lives where

| Material | Where it lives | Why |
| --- | --- | --- |
| reusable **code** of a scene (manifest, template, style, behavior) | the **shared prefab library**, published by `PrefabService.save` under `studio-template.<slug>[-<n>]` (origin `fork`, `derived_from` = the project prefab version it was promoted from, actor `user` or `brain`) | the library is the one catalog of prefab definitions ([prefabs.md](prefabs.md#publication-and-provenance-publicationjson-jarvisprefabpublication-v1)); the namespace is not the reserved `presentation-studio.` one, so it is a normal library entry the prefab view lists and forks |
| the **composition** (which library versions, in which order, neutral values, chosen controls, art direction sections) | one document `ptp_<12 hex>.json` in `<data_root>/presentation_templates/` | the library cannot hold a deck, a DA or a motion pattern; this file is an index of library versions plus data, never a definition (an unknown key such as `manifest` or `template` is refused on read) |
| art direction and motion | only in the composition document (`art_direction.sections`) | the shared library model supports prefabs only; a DA is never published as a prefab |
| the project it came from | `derived_from` of the document and `publication.json` of each prefab (ids and versions only) | provenance, never read when a template is instantiated |

### Four kinds, one flow

`kind` is `presentation` (a whole variant: every scene, optionally selected DA sections), `scene` (one scene), `art_direction` (chosen sections of the variant's DA) or
`motion` (the `motion` section alone). The flow is the same for the four: **plan** (read-only; describes candidates, roles, planned prefab ids, findings), the caller chooses,
**promote** (analysis again, then writes), **instantiate** (a template becomes new work through the existing doors).

### The explicit selection

Nothing is kept by default. Per scene the caller lists, with both lists present (empty is an explicit choice, "a fixed look, nothing exposed"):

| List | Meaning | Allowed |
| --- | --- | --- |
| `dimensions` | the control is kept **and its current look value becomes the default** of the promoted prefab | a control whose input is a `number`, `integer`, `boolean`, `color` or `enum` and whose group is not `content` (or an unbound `props` input of those types) |
| `parameters` | the control is kept, **its value is neutralised** (a placeholder) | any control |
| (neither) | the control is dropped from the template | - |

A content control (string, text, URL, array, anything under `data`) listed as a dimension is refused `presentation_studio_invalid` ("list it as a parameter or leave it out"). A control
in both lists, an unknown control, an unknown scene are refused. A **presentation** template must name **every** scene of the variant (`presentation_studio_template_selection_required`
otherwise); the plan without `scenes` is the discovery mode (`selection_required: true`, every scene with empty lists). `art_direction` templates name `art_direction.sections`
(`palette typography spacing shapes imagery dataviz motion`) and `motifs: "strip"` (default) or `"keep"`.

### Parameterization (what a promoted prefab is made of)

Every leaf of the pinned manifest's `inputs` is a **look** or a **content** leaf (`leaf_role`): content when its type is not scalar-non-textual, or it sits under `data`, or its control is
in group `content`. On a copy of the manifest:

| Leaf | Default of the promoted manifest | `sample` and template values |
| --- | --- | --- |
| a chosen dimension | the scene's current value | the same value |
| a content leaf | replaced by a neutral placeholder if the source had a default (`[name]`, `0`/`min`, `false`, `#808080`, first enum value, `https://example.com/`, `[]`); a default is never invented | the placeholder |
| a look leaf not chosen | the source default is kept (the scene's own value is dropped, counted as `look_reset`) | the source default |

The promoted manifest carries a new id, the caller's title (80), description (600, plus a generic sentence) and tags (`presentation-template`, then the caller's, at most 8), **no aliases** (they name
the original) and the generic events of the source. A curated control `default` and a scene `title`, `section` and preview `caption`/`alt` are dropped (they are the project's words); the
template scene keeps `props`/`data` placeholders, the chosen controls, and the anchors whose control survived. Scenes whose sanitized candidate is identical **share one library prefab**
(`studio-template.<slug>-<n>`, `n` by first appearance; a `scene` template is `studio-template.<slug>`): the library has 512 ids and no deletion.

### Detection and validation (the gate)

`scan_text` / `scan_value` run on the source files, on the whole promoted manifest and on the final record. Findings carry a code, a place and a **count, never the value**.

| Code | Blocking | Meaning |
| --- | :---: | --- |
| `project_identifier` | yes | a `pst_ psv_ pss_ psx_ psc_ psi_ psa_` id, a `presentation-studio.*` prefab id, a `user-prefab-*` or `studio-stage-*` handle |
| `local_path` | yes | a drive path, a home/`tmp` path, `.jarvis`, `file:`, `~/`, a UNC path |
| `project_content` | yes | a string of the project (scene content values, titles, sections, captions, the presentation's resource locators and titles, kept DA motifs) is still present, after case/space normalisation; strings shorter than 6 characters without a space or digit are not searched |
| `prefab_invalid` | yes | `PrefabService.validate_candidate` refuses the candidate (first error, `safe_text`-redacted) |
| `prefab_id_taken` | yes | the library id exists with other content (the same content is a **reuse**, see below) |
| `placeholder_unfit` | yes | the neutral values do not fit the source schema (the source needs a default) |
| `art_direction_unfit` | yes | the chosen DA sections do not stand alone over the deterministic fallback profile (select the sections they depend on, for example `palette` with `dataviz`) |
| `external_url`, `embedded_asset` | no | a hard-coded external URL or a `data:` asset over 2 KiB in the source: kept, reported |

The detection is a repository heuristic (normalised substring comparison), **not a proof**: reworded, split or encoded content is not seen. After publication, `_verify` re-reads every cited
`(id, version)` from the library (healthy, not `presentation-studio.*`) and validates every template scene's neutral values with `PrefabService.validate_instance`: no broken project-local
reference can remain. The request `scan_json` net (depth, node count, size, numbers) runs first, as in Slice 11.

### Provenance

Each library prefab: `publication.json` `origin: fork`, `derived_from` the project version, `created_by` the actor. The document: `derived_from {presentation_id, variant_id, variant_revision, scenes: [{key, scene_id, prefab}], art_direction_id}` and
`report {stripped: {content_values, defaults, look_reset, controls_dropped, anchors_dropped, references_dropped, motifs_dropped, sections_dropped}, scenes, prefabs}`. Provenance may name a project
version the retention later archives; nothing reads it back.

### Reusable presentation template document (`jarvis.presentation_studio.template` v1)

```
{schema, schema_version: 1, template_id: "ptp_<12 hex>", kind, title, description, tags,
 scenes: [{key: "s1", label, scene: <StudioScene: prefab pin to studio-template.*, neutral props/data, chosen controls, anchors, empty title/section/preview>}],
 art_direction: null | {sections: {<section>: <closed-vocabulary dict>}},
 parameters: [{scene_key, control_id, kind: "dimension"|"parameter", role: "look"|"content", type, group, label}],
 prefabs: [{id, version}], report, derived_from, created_by, created_at, revision: 1}
```

A template scene's `scene_id` is a record-local slot (`template_scene_id`), regenerated by every instantiation. At most 512 templates, 256 KiB per document; a newer schema is refused untouched
(`unsupported_schema_version`); the file is created once and never rewritten or deleted by Core.

### Routes and the operation surface (for the agent tools of Slice 21)

Core `/v1/presentation-studio`, Control Center `/api/presentation-studio` (same suffixes; every write has `actor` **forced to `user`** by the relay; guarded like the other Studio routes). Bodies at most 128 KiB.

| Method | Route | Body -> answer |
| --- | --- | --- |
| POST | `/presentations/{presentation_id}/variants/{variant_id}/templates/plan` | `{kind, title, slug, description?, tags?, scenes?: [{scene_id, label?, dimensions, parameters}], art_direction?: {sections, motifs?}, actor?, expected_revision?}` -> 200 `{ok, kind, presentation_id, variant_id, variant_revision, slug, title, selection_required, scenes: [{scene_id, key, source, prefab_id, shared_with, prefab_state: new\|reused\|taken, controls: [{control_id, label, group, path, type, role, eligible_dimension}], kept, stripped}], art_direction, would_publish, findings, blocking}` ; writes nothing |
| POST | `/presentations/{presentation_id}/variants/{variant_id}/templates` | the same body, selection mandatory -> 201 `{template_id, template (summary), kind, prefabs: [{id, version, published, reused}], scenes, parameters, findings (non-blocking), derived_from}` |
| GET | `/templates[?kind=]` | `{templates: [summary], count, problems: [{template_id, code}], limit}` |
| GET | `/templates/{template_id}` | `{template, summary, prefab_availability: [{id, version, available}]}` |
| POST | `/templates/{template_id}/instantiate` | `{title?, presentation_id?, variant_id?, expected_revision?, actor?}` -> 201 by kind, below |

Stable ids: `ptp_<12 hex>` (template), `studio-template.<slug>[-n]` (library prefab, version from the library), `s1..sn` (scene key inside a template). The typed client methods are
`presentation_studio_template_plan`, `presentation_studio_template_promote`, `presentation_studio_templates`, `presentation_studio_template` and `presentation_studio_template_instantiate`.
A Core service call is `app.presentation_studio_templates.{plan, promote, list_templates, get_template, instantiate}`; Slice 21 wraps these five, with the choice (`dimensions`/`parameters`) made by the agent from the plan, never defaulted.

Instantiation by kind (all through existing doors, so the same validation, revision and undo rules): `presentation` -> `title` required; a new Presentation (`create`), its variant filled by `save_variant`
(new scene ids, `source_revision 0`), the template's DA sections over the deterministic fallback (`create_art_direction`) or the fallback itself (`create_fallback_art_direction`); the answer lists
`presentation_id, variant_id, scene_ids, art_direction_id, rendered: [{scene_id, prefab, payload, problems}]` (`describe_scene`: payload budget and instance problems of every scene). A failure after the
Presentation was created is raised with the new id in the message (a Presentation cannot be deleted by Core). `scene` -> `presentation_id, variant_id, expected_revision` required; one `scene.add`
op through the edit API (undoable, `STALE_REVISION` when the variant moved). `art_direction`/`motion` -> same three fields; the sections are laid over the destination's current DA (its
name, references and other sections are kept, the laid sections are marked `provided`) or create one. Every instantiation first verifies the cited library versions.

### Failure modes

| Failure | Behaviour |
| --- | --- |
| no selection, a presentation template that skips a scene, a content control as dimension, an unknown control or scene | `presentation_studio_template_selection_required` 400 / `presentation_studio_invalid` 400 / `presentation_studio_unknown_scene` 404, nothing written |
| a blocking finding (project content, id, path, invalid candidate, id taken, unfit DA) | `presentation_studio_template_leak` 409 naming at most three finding codes and places; nothing written; the plan has the full list |
| the variant moved (`expected_revision`) | `presentation_studio_stale_revision` 409 |
| a scene with an unconfirmed hot reload (`last_valid_pin`) | `presentation_studio_scene_reloading` 409: promote after it is confirmed |
| the shared library refuses (definition, id or version limit, disk) | `presentation_studio_source_invalid` 400, `presentation_studio_limit_reached` 409, `presentation_studio_storage_io` 500, with the library's own code in the message |
| a failure between the publications and the document | prefabs stay published (the library has no deletion), a `template_orphans` `warning` row names them; repeating the **same** promotion reuses them (same id, same content: no new version) and writes the document |
| an unknown, damaged or newer template | `presentation_studio_unknown_template` 404 / listed in `problems` / `presentation_studio_unsupported_schema_version` 409 |
| a cited library version missing or tampered at instantiation | `presentation_studio_prefab_unavailable` 409, nothing created |

### Observability

`core.presentation_studio.{template_planned, template_promoted, template_refused, template_orphans, template_instantiated}`: ids, counts, kinds and finding codes; never a title, a slug, a
label, a value or a string of the project. The relay journal (`presentation_studio.request.relayed`) notes the action, status and code.

### Decisions and limits (recorded)

- **One library id per unique sanitized source, not per scene**: the library has 512 ids and no deletion; a promotion of a deck of identical-looking scenes costs one.
- **Retry reuses, it never forks again**: an existing id whose latest version has the same fingerprint is reused; any other content under that id is `prefab_id_taken`.
- **DA and motion are composition data, not prefabs**: the shared library model has no representation for them. They are laid over a deterministic fallback profile; a section that does not stand alone is refused at promotion, not at use.
- **Not promoted**: the score and its cues (they name scene and anchor ids of the project), scene-local variants (only the selected content is promoted), linked resources of the presentation, undo history.
- **Library versions of a template are custom ids, not retention ids**: `studio-template.*` is never archived by the Slice 01a retention, so templates register no pin source.
- **A promoted prefab is a normal library entry**: it can be forked or revised through the prefab view; a template pins the exact version it was promoted at.
- **Not run in a real browser**: the instantiated scenes are validated and described (payload budget, instance validation) by the same gates as any scene; a pixel-level drill of a promoted template belongs to Slice 22.

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
| `jarvis_presenter` | ASSISTANT | `off` (structural: the PRESENTATION session is stopped, "nothing of the room survives") | `score_lines` | score-driven: the speech facts the mouth records and timers (Slice 14, *Jarvis presenter and locked sequences*), never ambient text |
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
| PRESENTATION unavailable on the voice architecture (`legacy`, `duplex`: `presentation_architecture_unsupported`) | Voice refuses the mode and says so on the mode HUD (`Refusé par la voix`); **Core cannot see the architecture**, so `user_presenter` and a silent rehearsal still start, with a follower that never pulls: `follower: absent` after 10 s, band *Suivi vocal indisponible*, manual navigation continues (Slice 12). `jarvis_presenter` is unaffected (ASSISTANT) |
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

Decided afterwards: locked-sequence timing and speech-progress sync (Slice 14, *Jarvis presenter and locked sequences*). Not decided here: cue binding (Slice 13), the run banner copy (Slices 12/18), and the audible end-to-end proof (Human check, needs a real voice stack).

## Hot reload contract (Level 3, Slice 06)

Status: implemented by Slice 06. Conformance: `tests/unit/test_presentation_studio_reload_{domain,service,routes,core,crash,
host_js,page_js,browser,real_page_browser,integration,docs}.py`, `test_presentation_studio_pins.py`, `test_presentation_studio_pin_sources.py` and `test_presentation_studio_authoring_reload.py` (the two browser files drive a **real Chrome**;
`real_page_browser` serves the real Control Center page from a real Core and the base prefab `jarvis.window`, `browser` uses a thin bridge so a
frame's DOM, listeners and memory can be measured over 36 reloads).
Owner modules: `jarvis/domain/presentation_studio_reload.py` (pure: request, candidate, value continuity, statuses),
`jarvis/core/presentation_studio_reload.py` (`PresentationStudioReloadService`), `presentation_studio_reload_stage.py`
(`StageWindows`: which playback window shows which scene, and the one write the reload makes to it: the pin; the window
itself is the playback's, `SceneStage` in `presentation_studio_stage.py`), `presentation_studio_mounts.py` (`MountBook`),
`presentation_studio_pins.py` (`StudioPinRegistry`), `jarvis/runtime/control_center_presentation_studio_reload.js` (page
module) and the outcome/swap parts of `control_center_prefab_host.js`.

A source edit (tier 3, D11) is applied to **one** scene and gives a coherent live result or fails without damaging the last
valid scene. It adds no renderer and no second `srcdoc` path, and it does not touch the iframe `sandbox`, the CSP or `jv:1`.

### Mechanism (R2, decided by Slice 00)

```
request -> [phase 1, no lock]  read pin + source -> compose candidate -> GATE (before anything is published):
                               reserved property names, PrefabService.validate_candidate, studio values vs the candidate's
                               manifest, score still matches -> publish through PrefabDraftCoalescer (a burst = ONE version)
        -> [phase 2, per-scene lock]  re-read (base unchanged?) -> catalogue instance check -> write the pin (variant CAS,
                               last_valid_pin = the previous pin) -> patch the stage window (compare-and-set under apply_if)
                               -> wait for the host's mount report (deadline) -> confirm (clear the fallback) | roll back
```

- The candidate is the **current pin's source** with the given files replaced (`manifest`, `template`, `style`, `behavior`).
  Its id is the scene's own source id `presentation-studio.p<12 hex>.s<12 hex>` (`source_prefab_id`): a revision of that id when
  it exists, else a **fork** of the current pin (so editing a base or shared prefab never touches it). Variants share the id
  and differ by the `(id, version)` pin.
- **What the gate is, honestly.** The validation before publication is **structural only**: manifest schema, files present and
  within their size limits, no forbidden tag, inline handler or `@import`, reserved names, values against the manifest, the
  score. It does **not** parse or run JavaScript. A syntax error or a `throw` in `behavior.js` passes the gate, is **published
  as a version** (immutable, one version per bad edit) and is caught only at mount, by the **host** (below), then rolled back.
  A cheap syntax pre-check is not feasible in Python (there is no JavaScript parser in this process; the only real parser is the
  browser's) and it is deliberately not faked: a regex "check" would refuse valid code and miss real errors. The cost of a bad
  edit is therefore one inert published version, bounded by the library's `version_limit` and by the agent rate limit below;
  retention archives the unpinned ones.
- **Agent rate limit.** The `brain` actor may send at most `BRAIN_EDIT_LIMIT` = 10 source edits per scene per
  `BRAIN_EDIT_WINDOW_S` = 60 s; the 11th gets the typed error `presentation_studio_source_edit_rate` (HTTP 429, retry after the
  stated number of seconds; a request the limit refuses does not extend the window). The `user` actor is never limited: its
  retouches are already coalesced into one version per burst. The limiter is `core/presentation_studio_reload_limits.py`.
  **Core's `actor` is a label.** The Control Center relay, the page's only channel, REPLACES the body's actor with `user`
  before Core sees it (so a page is never limited as `brain` and cannot pass itself off as the agent: tested over HTTP); a
  direct bearer-token caller is what it claims; the agent's one door will be Slice 21's tool layer, which sets `brain` itself.
  Core has no verified channel identity before then and none is invented here.
- **Archive growth policy.** Every edit publishes an immutable version of the scene's own source id. Retention (Slice 01a)
  triggers at 32 live versions, keeps the 16 newest plus every pinned version (all pin sources above), and **moves** the rest to
  `prefabs/.archive/<id>/<version>` (renamed, never deleted, numbers never reused). No new deletion exists here. The count is
  visible: `GET .../presentations/{id}/reloads` carries `versions: {scene_id: {live, archived, newest, trigger, keep_last}}`
  (`archived = newest - live`); a Human who sees it growing clears `.archive/` by hand with Core stopped.
- **A scene being reloaded refuses other edits.** From the moment a source version is published until the mount is confirmed or
  fails (at most the mount deadline), any ordinary write that **changes or removes that scene** (`/edits` control, structure or
  restore operations, a variant save) is refused with the typed 409 `presentation_studio_scene_reloading` (retry in a few
  seconds); other scenes stay editable. A reload that ended `pending_mount` is no longer "in flight": edits are accepted again and
  the late rollback stays safe because of the compare-and-restore below.
- Coalescing: Studio bursts use a shorter quiet period than the library default (0.4 s quiet, 4 s ceiling,
  `DEFAULT_QUIET_S`/`DEFAULT_MAX_WAIT_S`) so editing feels live. Retouches of one burst compose on each other (a per-source-id
  draft), publish **one** version, and every caller receives the same outcome (`merged: true` on all but the first).

### Result states (`ReloadStatus`)

| Status | HTTP | Meaning | What the Human sees (`JarvisStudioReload`) |
| --- | --- | --- | --- |
| `reloaded` | 200 | published, pinned, stage patched, **mount confirmed by the host**; studio values kept | green band, 6 s, then gone |
| `reloaded_state_reset` | 200 | as `reloaded`, but some studio-owned values could not be kept: `reset` names them (keys, control ids, anchor ids; never a value) | persistent warning band listing the names |
| `repinned` | 200 | published and pinned; **no stage window shows this scene**, nothing was reloaded; the pin waits to be seen mounted | persistent info band |
| `pending_mount` | 202 | the page did not report within `DEFAULT_MOUNT_DEADLINE_S` (8 s); the pin and its fallback stay, a late report confirms or rolls back | persistent warning band |
| `refused_validation` | 400 | refused **before any publication** (code `presentation_studio_source_invalid`, `_scene_incompatible`, `_score_incompatible`, `_limit_reached`); nothing changed | persistent error band |
| `rolled_back` | 409 | a step failed after the pin moved (`presentation_studio_mount_failed` with the host's short `reason`, or `_stage_failed`): the pin is back on the last valid version | persistent error band, plus a toast |
| `stale` | 409 | the variant moved (or the scene's pin changed) since the caller's basis: read again, retry | warning band |
| `degraded` | 409 | the mount failed **and** the rollback could not be completed (the stage window could not be put back after `STAGE_RESTORE_ATTEMPTS` = 3 tries, or the previous pin could not be written): the scene keeps the new version **and its fallback** (`last_valid_pin`); a later report, a reload or a restart repairs it | persistent error band |

Every non-success result also carries `error: {code, message}`. `prefab` is the pin **in force** after the call, `previous` the
pin before it, `published` the version that was published (even when rolled back), `source_revision` the scene counter,
`revision` the variant revision, `merged`, `mounted` (`true` confirmed, `false` failed, `null` no window or no report),
`reset`, `waited_s`, `request_id`, and `preserved` (below). A malformed request, an unknown presentation/variant/scene, a
prefab that is unavailable and a data fault are coded **errors** (`presentation_studio_*`), not results.

### Guarantees

1. **Only the affected scene's frame is rebuilt.** Other frames keep their iframe node, their live document and their
   listeners (proved in a real browser, `test_presentation_studio_reload_browser.py`).
2. **The previous frame is never replaced by something that did not mount.** For studio sources the host loads the new
   version *beside* the live frame (hidden) and swaps only once it is `ready` and quiet for `SETTLE_MS` (250 ms). A source that
   fails (syntax error, exception at load or at first render, a frame that hangs, a navigation) leaves the old frame, its DOM
   and its frame-local state untouched; the host reports `failed`, Core rolls back, and the rollback patch (the live version
   again) mounts nothing.
3. **No publication without validation.** A refused candidate leaves the library, the variant, the stage and every frame as they
   were. A version published and then not pinned (a failure between the two) is harmless, immutable, and archived by retention
   when nothing pins it; its number is never reused.
4. **The last valid scene is never destroyed, and a rollback never overwrites newer work.** A rollback is a minimal
   **compare-and-restore**: it re-reads the scene and puts back only the pin, its fallback and the monotonic `source_revision`;
   each value (`props`/`data` key, controls, anchors) that the reload had written and that nobody touched since returns to what it
   was before the reload, while any value written since (a control edit) is **kept**. The result is re-validated against the
   restored manifest; what no longer fits is removed by name and reported (`reset`, and the message says so), never silently.
   A required key that cannot be reset stays as the user wrote it and is **named** in `reset.unfit` (`props.<key>` / `data.<key>`,
   never a value), in the message and in the rolled-back band: the scene needs a correction, it is never left silently invalid.
   The stage gets back the values it had (including values committed by the frame's own `state` events).
5. **Every step is visible.** `core.presentation_studio.reload_*` rows (info for the normal path), the conversation event
   `system.presentation_studio.scene_reloaded`, the page band with a live counter and a deadline, the console lines
   `[studio-reload] …`. No row, event or log carries a source text, a scene value or a frame message (names, ids, statuses,
   counts only); the frame's message appears only in the HTTP result and the band, as `textContent`.
6. **No silent state mismatch.** Studio-owned values that cannot be carried over are either refused (default) or reset **by an
   explicit `allow_state_reset: true`** and then named; a reload that would break the variant's **score** is refused.
7. **Bounded everywhere.** Edits per burst, drafts, per-scene locks, result ring (64), outcome cache (64), pending mount waiters,
   host frames (24), bundle cache (64), staged frames (one per object), reports (3 attempts, 10 s each).

### State preservation: what is kept, by whom, and the reset cases

| State | Kept by | Rule |
| --- | --- | --- |
| active variant, the scene, the score and its position | Core documents; the playback runtime (Slice 12) | a reload never writes the score, the active variant or the playback position. `PlaybackProbe.position(presentation_id)` is the **read** interface, implemented by `PresentationStudioPlaybackService.position` (`run_id`, `variant_id`, `scene_id`, `item_id`, `position`, `state`, `role`, `stage_object_id`); the result reports it (`preserved.playback`, `playback_unchanged`). The run is **not paused and does not move**: a reload announces its writes to the edit service's commit listeners with a `ReloadOrigin` token, the playback recognises it, re-reads the plan on the same item and writes nothing to the stage (the reload already patched it) |
| editor selection and other page context | the caller (Slice 07 shell) | `applySourceEdit` updates only `state.revision` of the object it is given; selection and position are never touched (tested) |
| scene values (`props`/`data`), controls, anchors | the variant document (authored values) | carried over to the new pin when the candidate's manifest accepts them (`plan_carry_over`); otherwise refused or reset (below) |
| values the frame committed through its declared `state` events | the **stage window's** `prefab.data` (Core writes them under `apply_if`) | re-pinned with the live values when they are valid for the new manifest; else back to the scene's values and `reset.runtime_values` is `true`. The variant's authored values are not rewritten (R6: playback state is not written to the variant) |
| anything else inside the frame (DOM, scroll, local variables) | nobody | **not preserved by design** after a successful swap; preserved untouched when the swap fails |

**Decision: no new `jv:1` message pair (snapshot / restore).** Reasons: (1) every value that matters to a presentation can and
should be a declared `data` key written by a `state` event, which already survives the remount through `init`; (2) a snapshot
pair needs an opt-in manifest key, and `parse_manifest` rejects unknown keys, so an older JARVIS could not read a newer prefab
folder; (3) re-injecting state saved by *older untrusted code* into new code is a type-confusion hole that needs its own
versioning and bounds; (4) it would change the protocol, the shim and the parity tests for a case the staged swap already
softens (a failing edit never loses frame-local state). It can be added later, strictly additively, if a real prefab needs
animation or scroll continuity; `docs/prefabs.md` › *Message protocol* is unchanged.

**Reset cases (Level 3).** With `allow_state_reset: false` (default) any of these is `refused_validation`
(`presentation_studio_scene_incompatible`); with `true` the listed thing is removed **by name** and the result is
`reloaded_state_reset`:

| Case | Refused / reset |
| --- | --- |
| a top-level `props`/`data` key of the scene is no longer declared, or its value no longer validates | key removed (`reset.props`/`reset.data`) |
| a control's path is no longer declared, or its curated bounds/default no longer fit | control removed (`reset.controls`) |
| an anchor was bound to a removed control | the anchor stays, unbound (`reset.anchors`) |
| a key is now **required without a default** | cannot be reset: refused |
| the removal would break the score (a cue, action or anchor it names) | cannot be reset: `presentation_studio_score_incompatible` |
| the frame's live values are invalid for the new manifest | back to the scene's values, `reset.runtime_values` |

### Rollback, step by step

| Step that fails | Result | State afterwards |
| --- | --- | --- |
| candidate validation, reserved name, values vs manifest, score | `refused_validation` | nothing changed, nothing published |
| validation or the prefab service **crashes** | error (500) | nothing changed (`inflight` released, draft dropped) |
| publication | error `storage_io`, or `refused_validation` + `presentation_studio_limit_reached` (the prefab `version_limit`/`id_limit` message names the way out) | nothing changed |
| instance check against the catalogue | `refused_validation` | a version was published but is not pinned |
| pin write (variant CAS) | `stale`, or error `storage_io` | the stage was not patched; the next edit works |
| stage patch (`StagePatchError`) | `rolled_back` / `presentation_studio_stage_failed` | the variant is restored |
| host reports `failed` | `rolled_back` / `presentation_studio_mount_failed` + `reason` | stage and variant restored; the previous frame was never replaced |
| no report within the deadline | `pending_mount` | the pin and its fallback stay; a late `failed` report rolls back, a late `mounted` confirms |
| the stage cannot be put back (3 bounded tries) | `degraded` / `presentation_studio_stage_failed` | the scene keeps the new pin and its fallback, listed by `pending_scenes()`; the next report or a restart repairs it |
| the rollback write itself fails | `degraded` / its code (`storage_io`...) | the document still names the new pin **and** its fallback: recoverable by the next report |
| an unexpected stage fault, then the variant restore also fails | the original fault is raised; the scene is tracked as degraded | fallback written and tracked (`reload_rollback_failed`, `stats.degraded`) |
| the host mounted but the confirmation write fails | `pending_mount` with `mounted: true` and the store's code (never `reloaded`) | the fallback stays until a later report or reload confirms it |

### Source revision and the document (variant schema v3)

`StudioScene` gains `source_revision` (monotonic counter, `0` for a scene never hot-reloaded) and `last_valid_pin`
(`{id, version}` or `null`: the pin to restore while the current pin has not been seen mounted). The variant document is
`schema_version` 3; `UPGRADES[variant][2]` adds `source_revision: 0, last_valid_pin: null` to every scene (nothing an older
file said is reinterpreted). Both fields are **owned by the service**, like `score_id`: a variant save cannot set them (it is
refused), a scene added by a save starts at `0/null`, a pin changed by an ordinary save moves the counter by exactly one and
clears the fallback; only `replace_scene_source` (the reload service) writes a fallback. `source_revision` moves by exactly one
when the pin changes and never otherwise, including on a rollback.

### Crash consistency (kill between any two steps)

Proved with a real killed subprocess (`test_presentation_studio_reload_crash.py`): after a kill (1) *after publication, before the
pin* the document is unchanged, one inert version exists, the next edit is the next number; (2) *after the pin, before the stage
patch* the file holds the new pin **and** its fallback together, both are protected by the registry from the first answer after
restart, `recover()` finds the scene, and the next mount report (or the next show) confirms or rolls back, stage included;
(3) *after the stage patch, before the report* the same pair is found. The stage window belongs to the playback (Slice 12): at
Core start `start_service` takes back the killed life's `studio-stage-<run_id>` by its id ledger, so after a restart there is
**no window and no run**, the reload has no binding, and nothing is guessed. The next run that shows the scene puts the
document's pin on its own new window (`studio-stage-<new run id>`, never a reused id), the host mounts it and its report
confirms the pin or, on a `failed` report, rolls it back, stage included (the playback bound the new window to the scene
when it showed it).

### Pins and retention (`StudioPinRegistry`)

The registry implements the 01a port and is passed to `PrefabService(pin_registry=…)` in `v2_app`. It answers from memory only,
**never takes the Studio lock** (it runs under the prefab write lock) and **fails closed**: not built, incomplete (an unreadable
document at start), or no bound scene means `RuntimeError`, hence nothing is archived (`core.prefab.retention_failed`). **One
source per store**, all in memory at answer time: (1) the variant documents, **live and archived**, built at Core start by
`rebuild(PresentationStudioVariants)` (`pin_index()` of Slice 16 is the only index; the scene pin and `last_valid_pin` of every
variant) and kept current by the single variant write door, which registers **before** it writes the file and restores the
previous set when the write fails (a branch, an archive/restore, a save, an edit, an undo and a reload all go through it);
(2) the Slice 08 undo stacks (`add_source("undo", PresentationStudioHistory.pins)`: the pins an undo would write back, held from
`begin`, before the document stops naming them, to the entry's creation; an undo whose scene was removed re-registers through
the same door); (3) the live global scene (every active object's prefab block: the stage windows of a **running playback**
`studio-stage-<run_id>` and its auxiliary windows, any window the host may redraw or reload); (4) in-flight holds (`hold(old,
new)` for a whole reload); (5) `add_source(name, fn)` for later Slices (variants 17, templates 20). Order at start: variant
reconciliation, then `rebuild`, then `recover()`. `docs/prefabs.md` › *Retention of studio scene sources* lists the entry
conditions this satisfies. The `presentation-studio.` namespace is now reserved: `POST /v1/prefabs` (hence the MCP `prefab_save` and
the relay) refuses such an id with `invalid_definition`.

### Authoring planner (Slice 11) and the hot reload

Tested on one real stack (`test_presentation_studio_authoring_reload.py`):

- **An assembled deck is a valid v3 document set.** `build_presentation` leaves every scene at `source_revision` 0 with no
  `last_valid_pin`; `PresentationStudioService.create_assembled` **refuses** (`invalid_presentation`, before any write or
  registration) a scene that arrives with either field set: those fields belong to the reload service whatever a draft says.
- **Its pins are protected from the first instant.** `create_assembled` registers the pins of every assembled variant with the
  `StudioPinRegistry` BEFORE the folder is published and puts the previous (empty) sets back if the write fails: the same entry
  condition as every variant write. Without it, an assembled bundle version would be unpinned until the next restart's rebuild
  and retention (32 live versions) could archive it. Tested at 64+ versions.
- **A fresh deck takes a source edit at once.** The assembled bundle id (`presentation-studio.<authored id>`) is shared by the
  scenes that use it, so the first source edit **forks** a scene-own id `presentation-studio.p<12>.s<12>`; the assembled pin becomes
  the scene's `last_valid_pin` until the new source is seen mounted. Neighbouring scenes are untouched.
- **`finalize` waits for a reload.** `PresentationStudioAuthoring.finalize` calls `PresentationStudioService.refuse_if_reloading`
  first: any scene of the variant between publication and mount confirmation gives 409 `scene_reloading` (it neither judges a
  half-reloaded variant nor activates it). The agent rate limit of source edits does not touch `finalize` (different operation,
  no version published).
- **Single write door.** `assemble` creates a *new* Presentation through `create_assembled` (one folder, one rename); every later
  write of its variants goes through the one variant write door with its guards (score and art direction ownership, scene guard,
  pin registration).
- **One definition of "unreferenced" and of counts.** `reconcile()` (Slice 11) reports prefab versions under `presentation-studio.`
  that **no pin source** holds: it asks the same `StudioPinRegistry` that retention asks (variant documents live and archived,
  undo stacks, live windows, in-flight holds) on top of the variant index. Both it (`studio_prefab_versions`) and the reload's
  `versions` counts (`GET .../reloads`, `PrefabService.retention_counts`) count the **live catalogue**; `archived` is only
  `newest - live` of one id and is counted nowhere else, so nothing is counted twice and an archived version is never
  "unreferenced" (it is archived, not live).

### Source requests (`scene.source_request`): durability decision

**Not durable, on purpose.** The ring of 64 in memory stays (`pending_source_requests`, eviction is a `warning` row), and a
source edit that carries `request_id` closes the request (`fulfil_source_request`). Reasons: the intent is free text that must
not reach a file or a journal; a request without a producer has no consumer until the agent surface (Slice 21) exists, and AI
code generation is out of scope here; after a restart a stale request is misleading because the scene moved on; losing one is
visible (eviction row, `durable: false` in every result) and costs only a repeated sentence. An unknown or evicted
`request_id` never blocks an edit. Revisit when Slice 21 needs requests to outlive a restart (then a bounded, content-free
index in a file store).

### Concurrency

Per-scene lock only after publication; two edits from one basis: the first wins, the second is `stale` (the published version
stays, unpinned); a control edit landing meanwhile makes the source edit `stale`, not lost; a burst shares one publication and
one outcome; edits to different scenes are independent (only the scene shown on the stage is patched, others are `repinned`);
an edit during playback never moves the position; shutdown (`close()`) refuses new edits, **flushes** the burst, and lets in-flight
edits finish (bounded).

### Host side

`createPrefabHost({onOutcome, swapPrefix})`: one observed outcome per frame generation (`mounted` after `SETTLE_MS`, or the
first error with its short reason: `bundle`, `frame`, `timeout`, `navigation`, `protocol`), per-object `counters`
(`starts`, `mounted`, `failed`, `remounts`) that survive a version remount, and the staged swap above. `JarvisStudioReload.
hostOutcome` posts `POST /api/presentation-studio/presentations/mount-reports` for `presentation-studio.*` frames only (3
attempts, a final failure is a toast and a console error); `applySourceEdit` renders the running band (live counter, deadline
50 s, "Arrêter d'attendre"), then the exact outcome; `watch(presentationId)` shows what the user did not start (a voice edit, a
late rollback) and never announces the history on the first poll.

### Routes, client, events

| Method | Core route | Control Center relay (read-guarded) |
| --- | --- | --- |
| POST | `/v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/source-edits` | `POST /api/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/source-edits`, actor forced to `user`; body `{actor, basis: {variant_revision}, scene_id, files: {manifest?, template?, style?, behavior?}, request_id?, allow_state_reset?}`; the result above (HTTP per status) |
| POST | `/v1/presentation-studio/presentations/mount-reports` | `POST /api/presentation-studio/presentations/mount-reports`; body `{object_id, prefab: {id, version}, outcome: mounted or failed, reason?, message?}` -> `{matched, waiting, resolved, scenes: [{scene_id, source_revision}]}` (the scene revisions the report settled) |
| GET | `/v1/presentation-studio/presentations/{presentation_id}/reloads` | `GET /api/presentation-studio/presentations/{presentation_id}/reloads`; `{reloads, pending, stats}` |

The relay forwards no `PUT` and no create: a page changes a Presentation only through `/edits` and `/source-edits`.

| Surface | Name |
| --- | --- |
| Typed client | `LocalCoreClient.presentation_studio_source_edit` (returns every outcome; an error envelope raises `CoreProtocolError`), `LocalCoreClient.presentation_studio_reloads` (the mount-report route is called by the page and the relay, not by a typed client method; there is no stage route any more: the playback shows the scene) |
| Control Center relay | the routes above under `/api/presentation-studio/...`, **actor forced to `user`** on `source-edits`, read-guarded (`Origin: null`, a frame, can neither edit nor report) |
| Event | `system.presentation_studio.scene_reloaded` (actor `system`, instant, diagnostic, content forbidden; `status`, `code`, `reason`, `revision` = source revision, `source` = actor, `tier` = `source`) |
| Diagnostics (`core.presentation_studio.<kind>`; ids, statuses, codes, counts, never values) | `reload_published`, `reload_applied`, `reload_refused`, `reload_stale`, `reload_pending` (warning), `reload_rolled_back` (warning), `reload_late` (a mount report that arrived after the call returned; warning when it rolled back), `reload_failed` (error), `reload_confirm_failed`, `reload_rollback_failed` (error), `reload_rate_limited`, `reload_restore_unvalidated`, `reload_announce_failed` (warning), `reload_unverified` (warning, at start), `reload_flush_failed`, `reload_close_timeout`, `reload_recover_failed`, `mount_reported`, `stage_unreadable`, `playback_unreadable`, `pins_ready`, `pins_degraded` (error), `source_request_fulfilled`, `event_failed` |
| Error codes added | `presentation_studio_source_invalid` (400), `presentation_studio_mount_failed` (409), `presentation_studio_stage_failed` (409), `presentation_studio_reload_unavailable` (409), `presentation_studio_scene_reloading` (409), `presentation_studio_source_edit_rate` (429) |

### Limits and known gaps

- The stage window and its lifecycle are the playback's (Slice 12, `SceneStage`): one window per run, `studio-stage-<run_id>`,
  taken back after a crash. The reload only **binds** to it (`StageWindows.bind/unbind`, called by the playback each time it
  shows a scene and when the run ends) and reads the position (`PlaybackProbe`). A scene that no run shows has no binding: its
  source is re-pinned and waits to be seen mounted. The provisional `POST .../stage` route of the first Slice 06 build is
  removed. After a Core restart there is no binding until a run shows the scene again.
- **Playback and a reload of the shown scene** (tested with a real run): the run's window is patched (compare-and-set on the
  pin), the run keeps its item and phase, the mount report names `studio-stage-<run_id>`; a failed mount puts the run's window
  back. If the user closed the window mid-run the playback reopens it under a new id and rebinds; a reload whose window
  disappeared in between is `repinned`.
- **Undo/redo and branches.** Undo and redo of a scene being reloaded are refused like any edit (`scene_reloading`, they are
  edits through the same write door, the history ticket is released). Undo after a reload is `stale` (the document moved on
  outside the ring: its steps are dropped with `document_moved_on`, never replayed over a new source). A **branch**
  (Slice 16) of a variant that has a scene being reloaded is refused 409 `scene_reloading`; a branch of a scene whose pin
  was not seen mounted yet takes the scene's **last valid pin** (repair data is not copied, an unverified pin is never
  inherited) provided its values fit that version, else the same refusal. Archiving a variant a run is playing is still
  refused (`variant_in_playback`, Slice 16).
- The host reports only for frames of a **page that is open**; with no page the result is `pending_mount`/`repinned`, never a
  silent success.
- The static gate does not execute JavaScript; hostile code is *contained* (sandbox, CSP: no network, no parent access, no `eval`,
  no navigation, tested), not *detected*. A broken `behavior.js` costs one published version before the mount catches it.
- A source edit forks a base/shared prefab into the scene's own id on the first edit: one id per edited scene (384 studio ids).

### Extension points

| To add | Where | Rule |
| --- | --- | --- |
| a pin source (undo, scene-local variants, templates) | `StudioPinRegistry.add_source(name, fn)` | synchronous, in memory, never the Studio lock |
| a stage-window source other than the playback (a preview, a second screen) | call `StageWindows.bind(StageBinding(...))` when it shows a scene and `unbind` when it ends | the reload then patches that window; never create one here |
| a new reset case | `plan_carry_over` + one row in the table above + one test | names only, never values |
| frame state continuity beyond `data` | a **new, opt-in, size-bounded** `jv` message version | not before a prefab needs it; see the decision above |

## Playback runtime contract (Level 3, Slice 12)

Status: implemented by Slice 12. Owners: `jarvis/domain/presentation_studio_playback.py` (the pure state machine, plan, progress, "where are we"),
`jarvis/domain/presentation_studio_playback_requests.py` (strict request bodies), `jarvis/domain/presentation_studio_armed_set.py` (the Core to Voice cue contract),
`jarvis/core/presentation_studio_playback.py` (the Core service), `jarvis/core/presentation_studio_stage.py` (stage window, auxiliary windows, id ledger),
`jarvis/adapters/file_presentation_studio_stage_ledger.py`, `jarvis/protocol/presentation_studio_playback_routes.py`, the relay `jarvis/runtime/presentation_studio_relay.py`
and the page module `jarvis/runtime/control_center_presentation_studio_player.js`. Conformance: `tests/unit/test_presentation_studio_{playback,playback_service,playback_rework,playback_routes,stage,edit_overlay,player_js,player_browser,player_realpage_browser}.py`.

The runtime knows **exactly where the presentation is** and can navigate, pause, detour and come back. It is *Presentation* playback, not the generic PRESENTATION interaction mode (which it consumes through Slice 01c). It does **not** match speech to cues (Slice 13), speak the score (Slice 14) or rehearse (Slice 15); it owns the state they all read and the contract they call.

### State is memory (R6), the variant is never written

| Fact | Where it lives |
| --- | --- |
| role, phase, position, reveal progress, detour stack, locked-sequence ownership, armed set, speaker, timers | `PlaybackState`, in Core memory only. A Core restart ends the run; nothing resumes it |
| the values a score sets (`control_set`, control-bound reveals) | an **ephemeral overlay** rendered by `PresentationStudioEditService.render_overlay` (the Slice 05 engine, same checks, chunks of 16 ops chained) and shown on the stage window. The variant file and its revision are byte-identical after any run (tested over a full run with value actions) |
| ids of the stage and auxiliary windows | the stage ledger `state/presentation-studio-stage-ledger.json`: ids only, no title, no content, erased when taken back, **outside** `presentations/` |

Only an **explicit edit instruction** writes, and only through Slice 05 (below). Improvisation (what the presenter says, a cue, navigation, speaker changes) never writes: tested by hashing every stored document before and after.

### The machine (closed table)

`apply(plan, state, event) -> Transition(state, effects, refusal)`; pure, no clock (events carry `at_ms`), never an exception for a bad *situation*: a typed `Refusal` and the state untouched.

Phases: `idle`, `playing`, `paused`, `detour`, `resuming` (transient: the stage is being brought back; ends with `stage_synced` or `stage_failed`), `ended` (past the last item, still inspectable), `stopped`.

| Event | Allowed in | Does |
| --- | --- | --- |
| `start` | idle, stopped | role + `run_id`; lands on position 0; effects `sync_stage`, `arm_changed` |
| `stop` | playing, paused, detour, resuming, ended | `stopped`; effects `retire_all`, `end_run` |
| `pause` | playing, resuming | `paused`; the item's interruption policy applies (below) |
| `resume` | paused | `resuming`, effect `sync_stage` |
| `next`, `previous`, `goto` | playing, ended | move; `goto` names exactly one of item, scene, position |
| `detour` | playing, paused, detour | push an auxiliary resource (bounded), `detour`, effect `show_aux` |
| `return` | detour | pop one; the last one applies the item's recovery policy; effect `retire_aux` |
| `reveal`, `hide` | playing | manual override of an anchor of the active scene |
| `cue_satisfied` | playing | a **typed id only** (below) |
| `boundary` | playing | applies an interruption that waited for the boundary |
| `stage_synced`, `stage_failed` | resuming/playing, playing/resuming/paused/detour/ended | the stage's own acknowledgement; a failure pauses with a visible problem |
| `sequence_step`, `sequence_done`, `sequence_abort` | playing (abort: also paused) | reports of the locked-sequence executor (Slice 14: the Jarvis presenter, exact offsets from t0) |
| `speaking` | playing | who is speaking now (`user`, `jarvis`, nobody) |
| `skip_sequence` | playing, paused | **provisional user-only exit** from a locked sequence (below): clears the ownership and lands on the item after the host (a paused run stays paused there); effect `sync_stage` |

Every other (phase, event) is `illegal_transition`, except the navigations which say the real reason. Typed refusal codes (`RefusalCode`): `illegal_transition`, `not_running`, `already_running`, `empty_score`, `role_invalid`, `paused`, `in_detour`, `resuming`, `at_start`, `at_end`, `locked_sequence_active`, `no_sequence`, `unknown_target`, `unknown_anchor`, `cue_not_armed`, `cue_already_fired`, `interruption_refused`, `aux_stack_full`, `no_detour`, `reveal_limit`, `bad_step`, `detour_invalid`, `mode_switch_refused`. Every table cell is tested; a seeded random walk (40 seeds x 150 events) checks after every step that the state is legal (`check_invariants`: position in range, aux stack bounded, `detour` iff the stack is not empty, **armed set exactly the lookahead of a free `playing` position and a subset of the score's armable cues**, nothing held by a stopped run, sequence ownership only at its host item, generation monotonic and moving exactly when the armed set does).

Effects are `sync_stage`, `show_aux`, `retire_aux`, `retire_all`, `arm_changed`, `end_run`: what the caller must do, in order. The machine does none of it.

**Position** is an index into `Score.playback_order()` (declared loops expanded, bounded by `MAX_EXPANDED_ITEMS` 2000), so a looped item has several positions and "back" is exact; `goto` an item picks the nearest occurrence.

**Detour and resume.** A detour freezes the position. Returning restores it exactly under `continue_item`; `restart_item` re-enters the item afresh; `skip_to_next` moves on (past the end: `ended`); `recovery_point` goes to the nearest occurrence at or before the position of the named item. A detour started from a pause returns to the pause. Auxiliary resources are bounded (`MAX_AUX_STACK` 4).

**Interruption policy** (`ScoreItem.interruption`): `allow` interrupts now; `at_boundary` records a *pending* interruption that takes effect at the next `boundary`/`sequence_step`, or right after the next move; `refuse` refuses pause, detour and sequence abort with `interruption_refused` (only `stop` interrupts).

**Locked sequences.** Entering a host item gives the timeline to the sequence (`owner: "sequence"`): `next`, `previous`, `goto` and `cue_satisfied` are refused `locked_sequence_active`, nothing is armed. The executor (Slice 14) reports `sequence_step` (forward only), then `sequence_done` (ownership returns to the user) or `sequence_abort` (`pause_resume`: paused at the step boundary, ownership kept; `abort_to_recovery`: to the recovery point). This module owns position and ownership; it executes no step.

**The user's escape: `skip_sequence`.** Born provisional in Slice 12 (nothing then sent `sequence_done`, so a run that reached a locked host item would have been wedged); **Slice 14 now executes the sequence** (*Jarvis presenter and locked sequences*): Slice 14 keeps it, as the user's own exit. `skip_sequence` (user only: the verb refuses a `brain` actor with `invalid_request`; the relay forces `user` anyway) leaves the sequence the current item hosts and continues after it, whatever the item's interruption policy says (it is the user's own exit, not an interruption by the score); a pause that waited for the boundary takes effect after the move; refused `no_sequence` when none is running. The band shows a **Sortir de la séquence** button (and the `S` key) only while a sequence owns the timeline. A presenter must always be able to get out.

**Progress is a fold, not an accumulation.** `progress_at(plan, position, sequence_started)` folds the actions of every played item (visual then motion, then the started steps of a hosted sequence) and then the manual overrides. Going back or jumping therefore restores exactly the values and reveals the score implies at that position, whatever the route taken (tested: `progress_at(p)` equals the progress reached by navigating to `p`). `scene_goto` needs no execution: entering an item shows its scene.

**`reveal` / `hide` semantics** (decided here, Slice 10 left it open): the anchor is always tracked as reveal progress (`revealed` in the answer). An anchor that **drives a control** (`ScoreAnchor.control_id`) also writes `true` / `false` to that control in the overlay; if the control is not a toggle the overlay refuses it, the marker still counts, the pixels do not move, and the run says so (`notices: anchor_control_not_toggle`). A plain **marker** anchor is a synchronisation point with no pixel effect.

### "Where are we" (bounded)

`where_are_we(plan, state, now_ms)` answers without replaying anything, in at most 2048 bytes (`MAX_WHERE_BYTES`, **the pure part**: tested with the longest allowed free text; `json.dumps` escapes every accent to six bytes, so a worst case of eighty accented characters per label is larger on the wire than the 2048 of the constant). The **whole** answer, with the Core fields below, is bounded by `MAX_VIEW_BYTES` 3072 (measured 2378 bytes at the worst case in the QA drill, asserted in `test_the_whole_where_answer_stays_inside_its_bound_at_the_worst_case`): `phase`, `role`, `position {index, of}`, `scene {title, section, number, of}`, `item {label, presenter, kind, timing, interruption, recovery}`, `speaking`, explicit `silence`, `revealed` anchors, `next {item_label, scene_title, cue {label, armable, armed, phrases (at most MAX_WHERE_PHRASES 3)}}`, `elapsed {item_ms, item_target_ms, item_over_target, run_ms, run_estimated_ms}` (time paused or in a detour is not counted; the target is soft, never a limit), `detour`, `sequence`, `owner`, `pending`, `armed`, `generation`, `problems`. It **never** contains an item's `text` or `note` (the script) or a full cue predicate. `scene.title`, `item.label` and the `next.*` labels are free text typed by an author or a model: the answer lists them in `untrusted`; a consumer treats them as data, and the page writes them with `textContent` only. Core adds `presentation_id`, `variant_id`, `stage_object_id`, `art_direction` (`checked`, `fallback` or `none`), `notices`, `mode`, `follower` (below) and, after a run, `last_run {run_id, reason, problems}`.

### Core service, routes, statuses

`POST /v1/presentation-studio/playback/{verb}` with `verb` in `start stop pause resume next previous goto detour return reveal hide edit skip_sequence`; bodies are exact-key objects with a required `actor` (`user` through the Control Center relay, forced; `brain` for the future MCP server): an unexpected field is `invalid_request`. `GET /v1/presentation-studio/playback` is the bounded state. Statuses: `applied` 200; `refused` 409 (`reason` = a `RefusalCode`, `error.code` = `presentation_studio_playback_refused`), or **422** for `detour_invalid` (the request itself is wrong, not the moment: nothing changed); `stage_failed` 500 (the transition happened but the stage could not follow: `error.code` = `presentation_studio_playback_stage_failed`, `reason` and `message` carry the real cause, the run is paused with a problem). Start also raises coded `PresentationStudioError`s: `presentation_studio_unknown_score` (404, a variant without a score cannot be played), `presentation_studio_score_incompatible` (400, the score has `problems`: a removed scene or control is refused at start, not discovered mid-run), `presentation_studio_playback_stage_failed` (the first scene could not be shown: the run is ended cleanly). Commands are serialised by one lock.

| Command | Notes |
| --- | --- |
| `start {presentation_id, role, variant_id?, jarvis_speaks?, origin?}` | loads the variant and its score, refuses `problems`, runs the art direction gate, plans the mode, creates the stage window. `origin` defaults to `explicit_user_request` for `user` and to `brain_spontaneous` for `brain` |
| `goto {item_id | scene_id | position}` | `position` is 1-based on the wire |
| `detour {title, prefab: {id, version, props?, data?}}` | an auxiliary prefab window, exact pin; **validated against the prefab catalogue before any state change** (`PrefabService.validate_instance`: unknown prefab, unknown version, props or data the manifest refuses): refused `detour_invalid`, 422, state untouched, nothing staged. Then shown through `SceneStage` (hidden at birth, then revealed) and always retired. A window the scene still cannot show (a bound, a catalogue that failed between the check and the write) is `stage_failed` 500 with the real cause **and the transition is undone** (window retired, stack popped, phase restored, generation moved on): no phantom detour that blocks `next` |
| `skip_sequence {}` | provisional user-only exit from a locked sequence (see *Locked sequences*) |
| `edit {ops, basis?}` | see below |

Python-only (not an HTTP surface): `notify(kind, ...)` for the timeline owner (`sequence_*`, `speaking`, `boundary`, and since Slice 14 the presenter pacing its own run with `next`, `pause`, `goto`), `halt(problem)`, `finish(reason)`, `resolve_problem`, `add_observer`, `set_presenter_view`: see *Jarvis presenter and locked sequences*.

### The stage window

One stable `window` object per run, `studio-stage-<run_id>`, created once and then **patched** with the next scene's `prefab` block (`PATCH_OBJECT` inside `SceneService.apply_if`, actor `user`): a version change remounts the frame, a props/data change is a `host.update`. A payload already on screen is not written again (a frame's own state survives a resume). An archived id keeps its tombstone and cannot be reused, so the id carries the run id, and a stage the user closed is re-created under `-1`, `-2`... (the old id leaves the ledger, the state says `notices: ["stage_closed_by_user"]` and the band says so; after `MAX_STAGE_REOPENS` 3 reopenings in one run the sync fails `stage_closed`: the run pauses with that problem instead of fighting the user, and a `resume` reopens it once more). Core cannot import the brain-side `SceneDisplayTools`; `SceneStage` sends the same scene commands. Studio objects are categories `studio_stage` and `studio_aux`. **Tool Brain:** studio tools have no `ui_surface` and keep working when the Tool Brain owns the screen; with `JARVIS_TOOL_BRAIN` off (default) nothing else writes these objects; the arbiter test of Slice 21 must refuse the Tool Brain adapters on these two categories (open point recorded in the handoff).

**Scene variant preview (Slice 17).** The stage window can also show a *preview state*: a scene rendered in memory with a scene-local variant selected, started by the user while the run is paused (`show_preview`, `end_preview`). It is memory only, ends on cancel, timeout, any playback command, a committed edit, stop or crash, and always repaints the canonical scene; `where` carries `preview: {scene_id, scene_variant_id}` while it lasts (see *Scene-local variant contract*).

### Auxiliary resources: stager rules, always retired

Same lifetime rule as the speculative stager ([presentation-speculative-preparation.md](presentation-speculative-preparation.md) section 8): a scene object is durable, so the Studio archives what it put there. The stager port there is artifact-only (07 C5), so playback stages prefab windows through `SceneStage` and keeps the same two protections: **hidden at birth** and an **id-list ledger**. Retirement happens on `return`, `stop`, a crash inside a command, a foreign mode change, Core shutdown (`close`), and at the next Core start / next run for whatever a killed life or a failed archive left (`reclaim`, by id list, never by filter: a look-alike object of the brain survives; tested with a simulated kill). A retire that fails is an `error` row, a visible problem (`aux_retire_failed`) and the id stays in the ledger. **An unreadable ledger** (truncated by a crash, hand-edited) no longer means "nothing to do": the bad file is kept aside as `state/presentation-studio-stage-ledger.json.corrupt-<UTC timestamp>-<4 hex>` (the newest `KEEP_QUARANTINED` 3 are kept; the next write never overwrites it), a `warning` row names it, and the reclaim falls back to a **scan of the scene** for the objects this module namespaces (category `studio_stage` or `studio_aux` **and** an id starting `studio-stage-` or `studio-aux-`, at most 64 in one archive command), which it archives (`stage_ledger_scan_reclaimed`, `warning`, with the count). A look-alike object of the brain (right category, wrong id, or the reverse) survives; tested.

### Explicit edit during playback vs improvisation

`edit` **pauses** the run (a `playing`/`resuming` run; refused with `interruption_refused` if the item cannot be interrupted), re-reads variant and score, commits through `PresentationStudioEditService.edit` (`mode: commit`, `basis` defaults to the current variant revision), rebases the run on the same item (`rebase`: the nearest occurrence of the item, else the first item of its scene, else the start, with a problem code) and re-syncs the stage; the run stays **paused**: the author resumes on purpose. An edit that did not come through `edit` (the inspector, undo, redo) reaches the same place by the edit service's commit listener: the run pauses and follows. A commit is the run's own **by the identity of a token** the service passes to `PresentationStudioEditService.edit(origin=token)` (never read from a request body) and the edit service hands back to every listener of that commit (`CommitListener(presentation_id, variant_id, revision, origin)`; `None` for any other commit): a foreign commit that lands while the run's own edit is in flight is still seen (tested with two concurrent commits), which a service-wide flag missed. A score that no longer resolves after an edit keeps the last good plan, pauses and says `score_problems` (it never crashes the run). On `resume` the plan is re-read, and the art direction's **own** revision is compared (a saved art direction does not move `variant.revision`): a change is a notice.

### Roles, mode, art direction

Role to mode comes from the Slice 01c helper only: `plan_mode_entry`, `InteractionModeService.request(target, source="presentation_studio_run")`, `decide_restore` on every exit path. A switch is remembered only when `APPLIED`. The mode service's listener stops the run when someone else changes the mode (`reason: mode_changed_by_user`, the user's choice is never forced back); our own switch and restore are ignored by source. A failed restore is `core.presentation_studio.mode_restore_failed` (`error`), a visible problem, and the mode is left as is (no retry loop). The Board preference is never written (the source is transient). `require_art_direction` is a port (`ArtDirectionGate`, the signature of `PresentationStudioService.require_art_direction`): called before a presenter run (`serious=true`; a rehearsal passes `false`), a refusal raised by it starts nothing and changes nothing. The gate is **required**: Core wires the studio service itself (`v2_app.py` refuses to start without `require_art_direction`, and `PresentationStudioPlaybackService(gate=None)` is a construction error). A serious run (`user_presenter`, `jarvis_presenter`) on a variant with no art direction is refused with the typed `presentation_studio_art_direction_required` (409 envelope, visible in the player and the Error Logs path like any refusal) and a dangling link with `presentation_studio_unknown_art_direction`; a DA of provenance `fallback` starts and the state says `art_direction: "fallback"`, a normal one says `"checked"`; a rehearsal passes `serious=false` and may run without one, and then says `"none"` (a dangling link is not hidden either: it is refused for a serious run and unnoticed only by a draft). Playback never writes `art_directions/` nor `scores/`, nor the variant file (a test hashes them across a run).

### Armed-cue delivery (Core to Voice), decided here, followed by Slice 13

The armed set lives in Core (it follows the position and survives a Voice crash); the **follower** lives in Voice beside the ambient lane (R5).

1. **Core to Voice: invalidate, then pull.** Same pattern as `interaction.mode.changed`. When the armed set changes Core publishes the content-free bus message `presentation_studio.armed.changed` `{run_id, generation, count}` (on the `/v1/events` stream Voice already consumes; phrases never travel on the bus, in an event, a trace or a log). The follower then pulls `GET /v1/presentation-studio/playback/armed` (bearer, loopback, **not relayed** to the page) and also pulls when it (re)subscribes: a missed message loses nothing.
2. **The set**: `{run_id, generation, expires_in_s, cues: [{cue_id, phrases, semantics}], ambiguous: {phrase: [cue_id...]}}`. At most the cues of the next item (`ARM_LOOKAHEAD` 1) and only `armable` ones; `cues: []` means "produce nothing"; nothing is armed while paused, in a detour, resuming, ended, stopped, under a locked sequence or with an interruption pending. `ambiguous` lists the phrases that name more than one cue of **this armed set** (Slice 13 must not fire on them). A pull renews the follower's authority for `expires_in_s` (90 s); a follower should pull every `expires_in_s / 3`.
3. **Voice to Core: a typed report** `POST /v1/presentation-studio/cues/satisfied` `{run_id, generation, cue_id}`, exactly those keys (a `text` is `invalid_request`: there is no way in for room speech). Judged against Core's state now: `stale_run`, `stale_generation` (the set moved on), `armed_set_expired`, `cue_not_armed` (409), `rate_limited` (429; 3 per second, burst 5); answers `{status: "refused", code}`. A report that fired answers `{status: "fired", position}`; the same report again answers the same with `duplicate: true` and fires nothing (one cue fires once; the last 8 answers are remembered). A cue can fire again only when a declared loop arms it again, under a new generation.
4. **What the bound action is**: the item the cue names, resolved from the stored score by `Score.resolve_cue` semantics; its pre-authorized, reversible actions are applied by the overlay. The matcher, ambient text and the explicit-address preemption are Slice 13. Core never builds a `BrainTurnInput`, a tool call or a UI intent from any of this.

**The follower is a visible state (`follower` in the answer).** Core cannot see the voice architecture or whether an ambient lane exists, so it watches the one fact it owns: whether the follower **pulled** the armed set. For a role that follows cues (`user_presenter`, and a silent `rehearsal`; Jarvis-speaking runs have no ambient lane, `follower: null`) the state is `waiting` for the first `FOLLOWER_GRACE_S` 10 s after the start, `connected` as soon as a pull has been made during the run (sticky: authority expiry is a separate matter, `armed_set_expired`), and `absent` when no pull came within the 10 s (once-per-run `playback_follower_absent` warning). `absent` is information, not a refusal: the run continues in manual (keyboard / mouse) mode and the band says *Suivi vocal indisponible* with the reason hint (the `legacy` and `duplex` voice architectures have no PRESENTATION lane; the OpenAI ambient stack is required). The mode HUD carries Voice's own refusal (`Refusé par la voix`); the band never covers it. Tested with a fake follower (a pull) and without.

Tested with a fake follower over the real `/v1/events` WebSocket (`test_presentation_studio_playback_routes.py`) and in memory (`test_presentation_studio_playback_service.py`).

### Page: band and keyboard

`control_center_presentation_studio_player.js` (marker `/*__CONTROL_CENTER_PRESENTATION_STUDIO_PLAYER_JS__*/`, after the fullscreen module). Outside fullscreen a **band** shows who presents (`Vous présentez` / `Jarvis présente` / `Répétition`), the phase, scene `n/N` and title, the item, what comes next and the phrase to say, a live clock against the soft target, and the buttons (previous, pause/resume, next, fullscreen, stop). It states the temporary mode of a Jarvis run and that the stored preference is unchanged. Keys act **only when the target is inside the stage window's host element** (the frame relays none): right/down/page-down/space next, left/up/page-up/backspace previous, Home first, End last, `P` pause/resume, `Esc` pause (only a playing run), `S` leave a locked sequence. The listener is on the document root in the **capture phase**: the scene page has its own keyboard navigation between windows that calls `preventDefault()` on Arrow/Home/End/Escape of a focused window node, so a bubble-phase reader never saw those keys on the real page (QA-1 B1; the first browser proof used a synthetic page without that handler). A consumed key is `preventDefault` + `stopPropagation` (the scene page does not also act); text fields, modifiers, Space on a native button inside the host, and everything outside the host are left alone. In **fullscreen** the player stays out of the way (`document.fullscreenElement`) and the fullscreen module's capture handler forwards the keys with `onNavigate`, so each key acts once. Proved against the real page in headless Chrome (`test_presentation_studio_player_realpage_browser.py`: isolated Core, real Control Center, real CDP key events, windowed and fullscreen, Escape pauses, arrows navigate, another input and another window untouched).
**Band placement**: the band measures `#interactionModeHud` and sits to its right (above it when the viewport is too narrow), so the mode selector (the way out of a run, and where Voice's refusal shows) is never covered and stays the topmost element at its centre (asserted at 1280x720 and 1920x1080). **Band content** adds the pending interruption (`pause demandée`, the Pause button reads *Pause demandée…*), the follower state, the art direction note (`fallback` / `none`) and the *Sortir de la séquence* button. The same routes as the voice, through the relay. `JarvisFullscreen.enter({object_id, keys: "host"})` is called inside the click on `Plein écran`. Every command is visibly in flight (verb and seconds), ends in a state a human can act from (refusal said in plain words; stage failure: toast + console + the cause in the band; unreachable Core: the duration, once), has a 10 s deadline, and the band of a run that ended with a problem stays until closed. Polling is 1.5 s while running and 5 s idle (one `GET` of about 100 bytes to the local Core, 12 per minute, only while the tab is visible: the price for a run started by the voice to appear without any action), with back-off and a "Core does not answer since N s" line.

### Failure modes

| Failure | Behaviour |
| --- | --- |
| stage cannot be shown at start | the run is ended cleanly (aux retired, stage released, mode restored), coded `presentation_studio_playback_stage_failed` with the cause |
| stage cannot follow mid-run | `stage_failed` status, run `paused`, `problems: ["stage_<code>"]`, band + toast + console |
| unexpected exception in a command | `playback_crashed` (`error`), the run ends cleanly, the exception propagates to the route boundary (`internal_error`, Error Logs) |
| Core killed mid-run | state gone; at the next start `reclaim` archives the ledger's ids (by id list) |
| mode changed by the user | the run stops, `mode_changed_by_user`, nothing forced back |
| mode restore fails | `mode_restore_failed` error + visible problem; mode left as is |
| score or variant edited | plan re-read at `resume` and after any commit; `score_problems` if it no longer resolves |
| detour block refused by the catalogue | `detour_invalid` 422, nothing changed, nothing staged |
| detour window cannot be shown | `stage_failed` 500, the transition is undone (no phantom detour) |
| stage window closed by the user | reopened (new id, old id dropped from the ledger), `stage_closed_by_user` notice; after 3 reopenings `stage_closed` pauses the run |
| stage ledger unreadable | file kept as `.corrupt-<ts>`, scene scanned for `studio-stage-*` / `studio-aux-*` objects of the two categories and archived, `warning` rows |
| no cue follower within 10 s (voice architecture, ambient stack) | `follower: absent`, band says so, the run goes on manually |
| a locked sequence | executed by the Jarvis presenter (Slice 14); `skip_sequence` (user only) always leaves it |
| bus publish fails | `armed_publish_failed` error row; the pull still works |
| follower silent past 90 s | its reports are refused `armed_set_expired` |

### Observability

Diagnostics `core.presentation_studio.{playback_started, playback_transition, playback_refused, playback_stopped, playback_crashed, playback_stage_failed, playback_edit, playback_mode_decision, playback_mode_changed, playback_plan_refreshed, playback_plan_problems, playback_art_direction_changed, playback_reclaimed, playback_reclaim_failed, playback_aux_retire_failed, playback_stage_release_failed, playback_foreign_stop_failed, playback_invariant_broken, mode_restore_failed, armed_set_pulled, armed_publish_failed, cue_report_duplicate, cue_report_refused, event_failed, stage_shown, aux_staged, aux_revealed, archived, archive_already_gone, stage_ledger_unreadable, stage_ledger_unwritable, stage_ledger_overflow, stage_ledger_quarantined, stage_ledger_quarantine_failed, stage_ledger_scan_reclaimed, stage_reopened, playback_detour_invalid, playback_detour_validator_failed, playback_follower_absent, playback_observer_failed, playback_stage_bind_failed (Slice 06: the reload observer failed to bind, the run goes on), overlay_rendered, commit_listener_failed, preview_shown, preview_ended, preview_timeout_failed}`: ids, codes, counts, phases; never a title, a phrase, a note or an error message from the author. One canonical event, `system.presentation_studio.playback_changed` (actor `system`, instant, diagnostic, content forbidden): `status` in `started`, `stopped`, `paused`, `resumed`, `detour`, `returned`, `ended`, `stage_failed`, `edit_committed`, plus `presentation_id`, `variant_id`, `role`, `depth`; identity `(run_id, sequence)`; recorded only with a live conversation. Movement (next, previous, cues) is deliberately not an event.

### Human checks and known limits

**Fullscreen key gap (known, not fixed in the product).** The browser sets `document.fullscreenElement` one frame before it fires `fullscreenchange`; the fullscreen module binds its host key listener and focuses the host on that event, so a key sent in that single frame (a voice-armed entry followed at once by a key) is dropped by both layers. A person cannot hit it, and the module cannot bind earlier without guessing the browser's answer (`fullscreenchange` is the truth, `docs/presentation-studio.md` > fullscreen). Tests therefore wait for `JarvisFullscreen.state().state === 'entered'` and the host focus before sending keys.

Human-only: the physical Esc key leaving fullscreen (and that it does not also pause), a second screen, the look on a projector, and cue following on an OpenAI ambient stack (Slice 13). Recipe: [OPERATIONS.md](OPERATIONS.md), *Lecture d'une présentation*. Limits: a state a prefab frame writes into the stage window (a click in a counter) is not canonical: a payload already on screen is not rewritten (so a resume keeps it), but the next scene's patch replaces `props`/`data` as a whole. Playback resolves and opens no `ResourceReference` and no `file:`/`scheme:` locator (the Slice 02/04 locator carry-forward is a Slice 11 resolver concern: nothing here dereferences one). PRESENTATION is unavailable on the `legacy`/`duplex` voice architectures; Core cannot see the architecture, so such a run **starts** and the cue follower never pulls: the run says `follower: absent` after 10 s and continues in manual mode (see *Armed-cue delivery*); a stored `ResourceReference` cannot be shown as a detour (only prefab windows); starting a run is exposed to the page through the API (`JarvisStudioPlayer.startRun`) but the explorer UI that offers it is Slice 18.

## Jarvis presenter and locked sequences (Level 3, Slice 14)

Status: implemented by Slice 14. Owners: `jarvis/core/presentation_studio_presenter.py` (the driver, `PresentationStudioPresenter`), `jarvis/domain/presentation_studio_sequence.py` (pure: schedule, clock, interruption table, action log),
`jarvis/domain/presentation_studio_line.py` (pure: progress of one scripted line), plus small additions to the Slice 12 machine and service (below). Conformance:
`tests/unit/test_presentation_studio_{sequence,sequence_machine,line,presenter,presenter_sequences,presenter_property,presenter_speech,presenter_routes,presenter_js,presenter_browser,presenter_docs}.py`;
doubles `tests/fakes/presentation_studio_presenter.py`.

Jarvis presents a prepared score **on top of** the playback runtime. It adds no speech stack, no provider call, no timeline of its own: it reads the playback state, speaks through the one existing path, observes what the speech stack
records, and moves the run through the same machine a user does (`PresentationStudioPlaybackService.notify`), so the machine's closed table and the score's interruption policy bind it exactly as they bind a click.
It is attached to **every** run (one presenter per Core, built in `v2_app` after the brain) and acts only as far as the role lets it: it paces a run and speaks only when `jarvis_speaks` (`jarvis_presenter`, or a rehearsal with a speaking
Jarvis); in a user-presenter run it executes locked **visual** sequences and nothing else (the user paces; Jarvis stays silent, 01c).

### Decisions (recorded, with the reason)

| Topic | Decision | Why |
| --- | --- | --- |
| Speech path | `BrainOrchestrator.announce_notice(text, **ScoreLineNotice.call_kwargs())` only: `kind=progress`, `supersedes_key=presentation_studio:<run_id>`, `ttl_s=30` | Slice 01c; no second TTS stack, no `verbatim`/`work_id`/`conversation_id` |
| Learning the speech id | from the `brain.speech.requested` conversation event whose `supersedes_key` is this run's (Core records it before `announce_notice` returns); nothing in `brain_service.py` changed | the call returns a bool; the event is the existing source of truth |
| Progress source | the conversation events the Voice process already records (`brain.speech.requested`, `mouth.speech.started / completed / interrupted / superseded / expired / failed / unconfirmed`, `mouth.floor.taken`, `user.transcript.accepted`), folded by `presentation_studio_line.observe`; phase words are those of `tool_brain_speech.py` (parity test) | one source of truth for "what happened to this speech" |
| One line at a time | a spoken item issues one line and the next only after `completed` (+ `GAP_MS` 300); in a sequence a step's line waits while an earlier line is still unstarted | the shared slot (`supersedes_key`) replaces an UNSTARTED earlier line: issuing faster would silently drop speech |
| Soft target | pace of an explicit **silence** item (`target_duration_ms`, default `SILENCE_DEFAULT_MS` 1500 without one); for a speech item it is only the band's soft clock (a spoken item ends when the mouth says `completed`, never on a wall clock) | the score contract: a target is soft and never decides what comes next |
| `user` items in a Jarvis run | Jarvis says nothing and waits for the user's navigation (or cue, Slice 13) | "never speak a non-Jarvis item"; a `note` is the user's intention and is never read |
| End of a Jarvis-paced run | the presenter stops the run (`last_run.reason: completed`): stage released, auxiliary windows retired, **mode restored** | otherwise the user would stay in SIMPLE after the last item |
| Pause/stop/escape | the machine's table decides; `skip_sequence` stays the **user-only** escape (the provisional verb of Slice 12 is kept, now next to a real executor) | a presenter must always be able to get out |
| Event | one new instant `system.presentation_studio.presenter_changed` (see *Observability*) | the failures and interruptions of the presenter are news a human reads on the timeline |

### Speaking a line

`pump()` (the whole driver, serialised, deterministic given the clock and the facts) does, for a `presenter=jarvis`, `kind=speech` item with `text`: build `ScoreLineNotice(text, run_id)` (refuses empty text and the not-addressed marker), hand it to
`announce_notice`, bind the speech id from the requested-event, and then **observe**. The facts are stamped with the presenter's own monotonic clock when they arrive.

| Observed | The item |
| --- | --- |
| `announce_notice` returns `False` (no current intention: e.g. right after a Core restart; withheld by the Board gate; stopping; invalid) | pause with `announce_refused` (visible; `Continuer` retries) |
| `announce_notice` raises | pause with `announce_failed` (`error` row with the exception class, never its message) |
| the text is refused by `ScoreLineNotice` (empty, or the not-addressed marker) | pause with `line_invalid` |
| no `mouth.speech.started` within `START_TIMEOUT_S` 10 | pause with `speech_not_started` (voice not connected, nothing records mouth events, or the line was withheld by the speech policy: in PRESENTATION mode the very same line is withheld, which is why the role runs in ASSISTANT) |
| started, no end within `LINE_TIMEOUT_S` 180 | pause with `speech_stalled` |
| `mouth.speech.failed` / `unconfirmed` / `expired` / `superseded` before it was said | pause with `speech_failed` / `speech_unconfirmed` / `speech_obsolete` |
| `mouth.speech.completed` | `speaking` returns to nobody; after `GAP_MS` the machine moves to the next item (`next`) |
| `mouth.speech.interrupted` (the user cut it), `mouth.floor.taken` (while a line of the run is outstanding or a sequence runs), an admitted user turn (`user.transcript.accepted`, always) | an **interruption** (below) |

While a line plays the machine's `speaking` is `jarvis` (`notify(speaking)`): the band shows *Jarvis parle*. A line is **issued once per entry of an item**; it is issued again only after an interruption or a failure and an explicit continue (`resume`): the property test
`test_presentation_studio_presenter_property.py` checks `issues <= 1 + explicit resumes` for every item entry, over random scores.
`PlaybackState.epoch` moves every time an item is (re-)entered (a move, a `restart_item`, a recovery point), never on a pause: the driver keys its per-item work by `(position, epoch)`.

### Locked sequences: the deterministic executor

A locked sequence is executed by `presentation_studio_sequence` (pure) and driven by the presenter. **Schedule.** Every step is due at `t0 + shift + offset_ms`: computed from the sequence start, never from the previous step, on the injected monotonic clock; a late poll delays one release
(`late_ms` in the action log) and moves nothing else, so no drift accumulates (tested over 1280 steps with random jitter). `shift` is the total time spent paused, added whole on resume: **a pause preserves every remaining offset exactly**.
A step is *released* by a `sequence_step` report: the Slice 12 stage then applies its `visual` / `motion` actions (`control_set`, `reveal`, `hide` through the ephemeral overlay, never the variant file; `scene_goto` shows the named scene on the stage window until the
sequence ends, `stage_scene_id`; the host item's scene is where the run is). The end is the exact `duration_ms` after the last release (`sequence_done`, ownership returns to the user).

**Synchronisation with speech (policy).** t0 is the instant the first spoken line of the sequence **started** (`mouth.speech.started`) when the step at offset 0 is a Jarvis step. **What `started` means (checked in `SpeechScheduler`)**: the scheduler records it when it asks the voice surface to *generate* the speech, before the first audio is written, and it can still cancel the line until then (a barge-in, a newer intention, a provider failure close the span as `interrupted` / `failed` / `superseded`). The scheduler exposes **no first-audio signal** as a conversation event (`audio_heard` is internal and live-surface only), so the driver cannot wait for it: t0 is *generation requested*, not *first sound*. The step-0 visuals therefore start **ahead of the first sound by the provider's generation latency** (not measured here; the Human check records it, `OPERATIONS.md`). Worst case: the line is cancelled inside that window (or never gets audio): the visuals of step 0 were already released and the run pauses (`interrupted`, or the failure code for a failed line); on the explicit continue a `pause_resume` sequence goes on from its remaining offsets without repeating the cut line (visuals stay ahead of the voice for that step), an `abort_to_recovery` sequence restarts from its recovery point. Another worst case: a same-key line issued early (a step line handed over while the previous one is still playing) is queued by the scheduler behind it and starts late; its start timeout is not counted while an earlier line of the run is playing (a busy voice is not a failing one). If the scheduler ever records a first-audio fact, t0 should move to it (one place: `_await_t0`). The wait is bounded (`speech_not_started`, a visible pause; a resume starts the
sequence afresh). When step 0 is silent, or Jarvis does not speak in this role, t0 is the explicit start (`basis: explicit_start` in the presenter status). Later Jarvis steps are *issued* at their offset; the audio follows with the voice stack's latency, which the log records (`late_ms`, and the
`presenter_sequence_started` row's `lag_ms`) but nothing here can change. An action log (`LogEntry`: sequence id, step id, index, offset, scheduled and released times, canonical action keys; no text, no value) is kept per run: the same score on the same clock gives the same log whatever the key order of the document.

**Ownership and the interruption policy.** While a sequence runs `PlaybackState.sequence` is set and `owner` is `sequence` (the `locked_owner` of the brief): `next`, `previous`, `goto` and cues are refused `locked_sequence_active` **whatever the policy** (a sequence that owns the timeline is not moved from outside); the policy governs *interruptions*, one table read by the executor
(`input_verdict`) and enforced by the machine (`tests/unit/test_presentation_studio_sequence_machine.py` proves they agree cell by cell):

| Input | `interruption: allow` | `at_boundary` | `refuse` |
| --- | --- | --- | --- |
| pause, the user's address (floor taken, admitted turn, a cut line), detour | taken now | pending; taken at the next step boundary **before** that step starts (`boundary`), or at the end of the sequence | refused (`interruption_refused`); the choreography goes on, the interruption is recorded (`interrupted`, `refused_by_policy`) |
| next / previous / goto / cue | refused while a sequence owns the timeline | refused | refused |
| stop, `skip_sequence` | always | always | always |

A locked host cannot declare `allow` (Slice 10); a plain item can. After an interruption the run is **paused**, never auto-resumed; the user's turn is answered; **resume is the user's explicit continue** (`resume`, the *Continuer* button, a voice request through Slice 21). A user signal older than that continue (the turn that says
"continue" is recorded before the resume runs) is its cause, not a new interruption (`PlaybackState.resumed_at_ms`). On the continue the declared recovery applies, to the entry that was interrupted:

| Entry | Lands on |
| --- | --- |
| a spoken item, `continue_item` | the same item and entry; the line is said again **from its start** (never mid-sentence, 01c) unless it had been heard in full |
| `restart_item` | the item re-entered afresh (new epoch), line said again |
| `skip_to_next` | the next item |
| `recovery_point` | the nearest occurrence at or before the position of the named item (`recovery_position`) |
| a locked sequence, `on_interrupt` = `pause_resume` | the same sequence, every remaining offset preserved; the cut step line is not repeated |
| a locked sequence, `on_interrupt` = `abort_to_recovery` | the sequence's recovery point exactly (`sequence_abort`; the sequence restarts from its first words, position and epoch as the machine's recovery gives them) |

A pause or interruption deferred to a boundary that lands on the *next* item (`at_boundary` on a plain item: the line finishes, the run pauses before the next item) resumes at that next item's start.

### Failure behaviour (every case visible, none a hang)

| Failure | Behaviour |
| --- | --- |
| `announce_notice` False / raises, line never starts, stalls, fails, is dropped or unheard | the run is **paused** with the stated problem on the band, a `presenter_*` diagnostic, a `presenter_changed` event; `Continuer` retries (the line, or for a step the step's line, is said again once) |
| the speech stack is absent (no Voice process, no mouth events) | `speech_not_started` after 10 s: the same visible pause |
| the line is withheld by the speech policy (Voice still believes PRESENTATION) | the mouth records it dropped (`speech_obsolete`) or the wait ends (`speech_not_started`) |
| mode switch refused or raising at start | the run does not start (`mode_switch_refused`), the presenter never attaches and says nothing |
| the user changes the mode during the run | the run stops (`mode_changed_by_user`), nothing is said afterwards, the user's choice is never forced back |
| Core restarts mid-run | run and presenter are memory and are gone; `BoardService.restore_interaction_mode` reapplies the stored preference (the run's source `presentation_studio_run` is transient and never stored); the next start reclaims the stage by id list |
| the presenter itself raises | the run is ended cleanly with the stated reason `presenter_crashed` (`last_run.reason`; mode restored), an `error` row |
| stop | everything is dropped, nothing more is issued; a line already handed over is cut by the existing barge-in path or ends naturally (Core has no "cancel this notice", none is added) |

### State, routes, events

`where` gains `presenter` (bounded, content-free: `speaks`, `lines` issued, `interrupted`, `problem`, `line` phase, and while a sequence runs `sequence {state, step, of, elapsed_ms, duration_ms, basis}`); `sequence` gains `duration_ms`. The machine's state gains `epoch`, `resumes`, `resumed_at_ms`. **No new HTTP route or verb**: a Jarvis run is `POST .../playback/start`
with `role: jarvis_presenter` (the relay forces `actor: user` and the explicit-request origin, so only an explicit user action may switch the mode; the `brain` actor stays Slice 21's), the controls are the existing verbs, `skip_sequence` is user-only on the wire. The typed client is unchanged (`presentation_studio_playback(verb, body)`).
Python-only: `notify` now also accepts `next`, `pause`, `goto` (the presenter pacing its own run, under the same machine and policy); `halt(problem)` pauses with a stated problem; `finish(reason)` ends a run with a reason; `resolve_problem(code)`; `add_observer`, `set_presenter_view`.

### Entry condition for Slice 21 (the origin of a start)

The Slice 12 start contract takes `origin` from the request body and accepts a Core caller with actor `brain` and origin `explicit_user_request`: such a start switches the mode and runs Jarvis (pinned by `test_entry_condition_for_slice_21_a_brain_actor_with_an_explicit_request_origin_is_accepted_by_the_start_contract`). The Control Center relay is safe because it forces `actor: user`. **Slice 21 MUST derive the origin from the real turn** (a user request admitted as addressed, via the turn authority) **and never from model input or tool arguments**: a model that can write `origin` can switch the user's mode. The test fails the day the contract changes, which is the moment to revisit this.

### Observability

Diagnostics `core.presentation_studio.{presenter_attached, presenter_detached, presenter_line_issued, presenter_line_heard, presenter_line_failed, presenter_announce_refused, presenter_announce_failed, presenter_advanced, presenter_interrupted, presenter_interruption_ignored,
presenter_resumed, presenter_sequence_begun, presenter_sequence_started, presenter_sequence_step, presenter_sequence_done, presenter_sequence_left, presenter_sequence_recovered, presenter_completed, presenter_crashed, presenter_crash_finish_failed, presenter_event_failed,
presenter_event_unrecorded}` and `playback_observer_failed`: ids, counts (`chars`), codes, times; **never the text of a line, a step or a note, never an exception message**. One conversation event `system.presentation_studio.presenter_changed` (actor `system`, instant, diagnostic, content forbidden): `status` in
`line_failed`, `interrupted`, `sequence_done`, `sequence_skipped`, `sequence_aborted`, `completed`; `presentation_id`, `variant_id`, `role`, `code` (a token), `count` (lines issued). Identity `(run_id, "p<sequence>")`. A spy test checks that no marker of the script reaches a log, a trace, an event, a view or a wire answer.
Trace evidence of a replayed scripted presentation through the real scheduler path: `tasks/jarvis-interactive-presentation-studio/slices/14-jarvis-presenter-locked-sequences/evidence/`.

### Human checks and limits

Human-only (`OPERATIONS.md`, *Présentation par Jarvis*): audible output on the real voice stack, the cut by a real barge-in, the look of the band on a projector. Not run live by this Slice: nothing was spoken on a real voice stack. Limits: the floor-taken signal is **not filtered for noise** (any `mouth.floor.taken` while a line of the run is outstanding, or a sequence runs, pauses the run; accepted by the PM, to be refined with real-voice data); a run where Jarvis does not speak ignores user turns and floor signals except while a locked sequence runs (the user may talk to Jarvis freely in their own presentation); Core cannot see the voice architecture, so a withheld line is
learned from the mouth's own facts or the bounded wait; a line already queued in the scheduler when the user pauses may still start (it carries a 30 s deadline and dies at the next intention; a resume re-issues it and the shared slot replaces an unstarted one); a mouth event recorded by no process (no Conversation Event recorder in Voice) looks like a speech stack that
never starts; the executor's lateness is the poll's, bounded by one wake-up (the loop wakes at the exact next deadline); a step line that cannot start because an earlier one is still unstarted is delayed, not dropped (its `late` audio is the voice stack's).

## Cue following contract (Level 3, Slice 13)

Status: implemented by Slice 13. Owners: `jarvis/domain/presentation_studio_cues.py` (the pure matcher: `CueMatcher`, `CueMatch`, `CueEvidence`, `CueDecision`, `Verdict`, `MatcherConfig`, `parse_armed`),
`jarvis/runtime/presentation_studio_cue_follower.py` (the Voice follower: `PresentationStudioCueFollower`, `FollowerState`, `FollowerConfig`, `FollowerCounters`), the consumer slot `AmbientIngestionLane.add_utterance_consumer`
(`jarvis/runtime/ambient_lane.py`) and the composition `build_cue_follower` (`jarvis/runtime/presentation_studio_cue_composition.py`, called by `PresentationComposition.cue_follower` in `jarvis/runtime/presentation_runtime.py`, wired by `jarvis/app.py` with the Voice `LocalCoreClient`).
Conformance: `tests/unit/test_presentation_studio_{cues,cue_follower,cue_authority,cue_corpus}.py`, `tests/integration/test_presentation_studio_cue_replay.py`; data `tests/fakes/presentation_studio_cue_corpus.py`;
replay `tests/replay/presentation_studio_cue_replay.py`; evidence `tasks/jarvis-interactive-presentation-studio/slices/13-user-presenter-sidekick/evidence/`.
Authority: [presentation-addressed-turn.md](presentation-addressed-turn.md) section 12, *Amendment (Slice 13, R5)*.

When **the user presents** (roles `user_presenter` and a silent `rehearsal`: mode PRESENTATION, ambient lane `armed_cues_only`), Jarvis listens to the room and advances the presentation when the presenter says the
phrase of the **next** cue. It is a sidekick for one thing (cues), not a general ambient command channel.

```text
ambient utterance (post-transcription, <= 600 chars)  ->  explicit-address preemption  ->  CueMatcher (pure)  ->  CueMatch  ->  POST cues/satisfied {run_id, generation, cue_id}  ->  Core judges + resolves the bound actions
```

### What may leave the follower

Exactly one thing: `CueMatch(cue_id, generation, evidence)`, `evidence = CueEvidence(utterance_id, start, end, rule)` (`rule` in `whole_phrase`, `ordered_tokens`, `fuzzy_phrase`; `start`/`end` are character offsets in the utterance).
No field can hold speech: the only `str` fields are `cue_id` (a `psc_` id) and `utterance_id`, which is an **opaque counter id set by the lane** (`amb-000005`: a lowercase prefix, a dash, at most 16 hex digits, enforced by the constructor; the matcher replaces any other shape by `utt-` plus a hash of the ID itself, never of the text), so it cannot hold a sentence; a structural test fails when a `str`/`Any`/`dict` field is added to the output types. The wire report is the three values of the Slice 12 contract and nothing more.
`CueMatch.authorizes_actions` is `False` (class constant, like the ambient carriers): a match authorises nothing; Core re-checks run, generation, authority and armed set, then resolves the actions from the stored score.

### The matcher: when a cue fires

All of these must hold. The default values are in `MatcherConfig` / `FollowerConfig`; the anchoring was tightened after the QA of Slice 13 measured 24 % false positives on its independent corpus (see *Measured* below).

| # | Condition | Default | Verdict when it fails |
| --- | --- | --- | --- |
| 1 | the armed set is not empty (Core's answer; semantic labels are carried but **never matched**: that would need a model reading the room) | | `no_armed` |
| 2 | **exactly one** armed cue is touched; two touched, or a phrase that two armed cues share (even spelled differently), is ambiguity | | `ambiguous` + the candidate ids, nothing fires |
| 3 | a rule matches on **normalised** text: NFKC, casefold, accents removed, `oe`/`ae` ligatures expanded, every non-letter/digit is a separator (apostrophe, hyphen, punctuation), matching **on token boundaries only** (never inside a word); non-Latin look-alike letters and zero-width characters never fold to Latin | | `no_match` |
| 3a | `whole_phrase`: the phrase's tokens are contiguous | on | |
| 3b | `ordered_tokens`: phrase of >= 3 tokens, all present in order, at most 1 inserted token between two, 2 in all, never a negation or a quotation marker | on | |
| 3c | `fuzzy_phrase`: phrase of >= 16 characters, every token equal but one of >= 6 letters that is one edit away (substitution, insertion, deletion, adjacent swap) with the same first letter. A transcription typo, never a short word or a homophone ("fin"/"faim", "presentons"/"presentent" do not match) | on | |
| 4 | not **quoted** (inside guillemets, quotes, an unclosed quote, or with a marker such as "dit", "je dis", "expression", "phrase", "ecrit", "mot" within **4 tokens before** or **2 tokens after** the phrase) | | `quoted` |
| 5 | not a **question** (the sentence ends with `?`, starts "est-ce", or starts with "pourquoi/comment/combien" before the phrase). Checked before the hedges | | `question` |
| 6 | not **hedged**, on **either side**: within the 3 tokens before, a negation or a frame that introduces the phrase instead of being it ("ne", "pas", "jamais", "non", "sans", "avant", "il faut", "va", "veux", "voudrais", "aimerais", "attend", "pour", "que", "qu'", "crois", "puis", "ensuite"...); anywhere earlier in the sentence a subordinator ("si", "quand", "lorsque", "puisque", "parce", "tandis", "pendant", "sauf"); within the 3 tokens after (a comma does not stop the look) a retraction ("non", "pas", "attends", "mais", "enfin", "sinon", "plus", "jamais", "finalement", "peut", "stop", "demain"...) | | `hedged` |
| 7 | **anchored**: inside the phrase's own **clause** (it ends at `, ; : . ! ? ( ) -` or a line break) at most **1** content word before it and **1** after it; discourse fillers ("bon", "alors", "voila", "donc", "ok", "merci", "a tous", "s'il vous plait", "allez"...) are free. Over the **whole utterance**, at most **6** content words before it and **4** after it. A one-word cue needs a sentence of at most 2 tokens, the other one being a filler ("allez-y" and "allez on mange" do not fire) | 1 / 1 / 6 / 4 | `not_anchored` |
| 8 | **order**: no earlier cue of the armed set is still unfired (`allow_skip_ahead` false) | off | `order_blocked` |
| 9 | not fired already **in this generation**; not the same cue within `cue_cooldown_s`; no fire within `min_interval_s` of another | 4 s, 1 s | `already_fired`, `cooldown` |

The verdicts (`Verdict`) are `fire` (the only one that carries a match), `no_armed`, `no_match`, `ambiguous`, `quoted`, `hedged`, `question`, `not_anchored`, `order_blocked`, `already_fired` and `cooldown`.

A cue fires **once per generation**. A declared loop arms it again under a new generation; the cooldown still applies. A report that Core could not take (Core unreachable, rate limited, stale) *retracts* the match, so the cue can fire again.
Core arms at most the next item's cue (`ARM_LOOKAHEAD` = 1), so in practice one cue is armed and conditions 2 and 8 are guard rails for a future wider lookahead.

The price of anchoring is explicit: a stage direction with a complement ("Regardons maintenant le plan de financement de l'entreprise."), a phrase repeated inside one utterance, a direction after a long preamble in the same utterance, or a transcription error is **not** fired. The presenter uses the keyboard (`next`) for those; a missed cue is recoverable, a false fire is not welcome.

**Advice for authors.** Choose distinctive multi-word cue phrases ("regardons maintenant le plan de financement", "prochaine diapo"), not one word or common words ("ok", "allez", "suite"). The score validator warns about the weak ones: `warnings: [{code: "weak_cue", cue_id, phrase_index, reasons}]` on the score answers (`reasons` in `one_word`, `only_stopwords`, `under_4_letters`), only when there is one, never blocking, never quoting the phrase.

### The follower

| Concern | Behaviour |
| --- | --- |
| Input | a synchronous `on_utterance(utterance, analysis)` registered with `add_utterance_consumer`. The text exists only inside that call: no field, queue, log or trace keeps it. An exception inside is swallowed with its class name (the lane would otherwise log the message, which may quote speech) |
| Armed set | pulled from Core (`GET .../playback/armed`): at start, on a bus message `presentation_studio.armed.changed` whose `(run_id, generation)` is not the one held, on every (re)connect of the bus stream, every `expires_in_s / 3` (30 s) while armed and every 5 s (`idle_poll_s`) while nothing is armed (this also lets Core see `follower: connected` for a run that arms nothing yet). Pulls are throttled to one per second, and **a bus message obeys the same backoff as a poll** (one mechanism, `_next_pull_at`: while pulls fail, a message never makes the follower pull sooner than its backoff); a pull renews the follower's authority for 90 s. Follow-up for Slice 12 (code, not done here): Core publishes `armed.changed` at run start even when the set is empty, which would remove the 5 s idle poll; the 30 s safety poll stays, the bus has no replay |
| Report | one at a time (`reports_dropped_in_flight` counts a second match). The call has a 5 s deadline. `fired` ends it; `duplicate: true` is counted, not re-fired |
| Roles | the follower exists only inside a PRESENTATION session (`jarvis_presenter` and a speaking rehearsal run in ASSISTANT: no session, no follower) |

States (`FollowerState`, read with `status()` which holds counts only): `starting`, `idle` (no run), `unarmed` (a run, nothing armed: paused, detour, last item), `following`, `paused_address`, `backoff`, `lapsed`, `stopped`.
Each change of state is one Voice diagnostic line `presentation.studio.follower_state`.

### Explicit address preempts, immediately

Before matching, the follower evaluates `decide_turn_authority(window_live=..., vocative=is_vocative_address(text))` with the two reads the bridge itself uses, plus a probe "an addressed turn is in flight" (the addressed-turn
service has a latency measure open until `conclude`). It also reads a **marker** (`counters.armed` of that service, a number that only grows each time an explicit address is armed) and the **`jarvis` token anywhere in the utterance** ("Merci Jarvis, passons a la suite", "passons a la suite Jarvis": not only the prefix `is_vocative_address` checks). If the authority admits a turn, or a turn is in flight, or the marker moved since the last read, or `jarvis` is named, or the last sign of an address is less than `hold_s` (4 s) old, then **cue automation is paused**: that utterance is dropped
(counted `preempted_address`, never matched), and a report that has not left yet is cancelled and its match retracted. The hold covers the lag between the user addressing Jarvis (the realtime stack uses the window at once) and the ambient transcript of the same
sentence arriving. The marker closes the sampling gap of the window probes: a window that opened and closed between two supervisor ticks (0.25 s) still moved it, so the next utterance is preempted and a report not yet sent is dropped. An address probe or the marker that raises is read as "addressed" (fail closed, one `error` line). The follower never arms, opens, consumes or reads the content of a window, never changes the mode, and has no handle on the brain.

### Stops, failures, and how they are seen

Everything is counted in `status()["counters"]`, one line per episode, never a silent loop.

| Situation | Behaviour |
| --- | --- |
| run ended, paused, in a detour, resumed, last item, another role | Core's armed set is empty (a new generation is published): the follower goes `unarmed`/`idle` and matches nothing. On resume or return Core arms a **new generation**: the follower pulls it and the cue can fire again |
| session ends (mode left PRESENTATION) | `PresentationStack.stop` stops the follower (tasks cancelled, slot removed, matcher emptied); meanwhile `mode_ok` false skips every utterance |
| armed set empty | nothing matched (`no_armed`) |
| authority lapses (no successful pull for `expires_in_s`) | the set is dropped (`lapsed`, `lapses`), a pull is attempted at once; Core refuses a late report anyway (`armed_set_expired`) |
| Core unreachable / answer unreadable (`parse_armed` fails) | `backoff`: 1 s doubling to 30 s, matching suspended, **one** `warning` line (`follower_degraded`: step, exception class, Core code) and one `info` line at recovery (`follower_recovered`) |
| report refused `stale_run` / `stale_generation` / `armed_set_expired` / `cue_not_armed` | counted by code, the held set is dropped, the cue is retracted, one re-pull (throttled) |
| report refused `rate_limited` (429) | reports blocked for 2 s (`backoff`, visible), counted, one `warning` line; matching resumes after |
| report fails (timeout, connection) | counted `reports_failed`, match retracted, backoff as above |
| bus stream lost | one `warning` (`follower_events_lost`); the periodic pull keeps the follower working, slower to notice a change |
| Core without a bus stream (a double) | one `warning` (`follower_events_unavailable`), polling only |
| a handler failure | swallowed, class name only, `handler_errors` |

What the **Human** sees: the Control Center band shows `follower: waiting | connected | absent` (Slice 12 rework: it turns `connected` at the first pull of the run, `absent` after a grace period without any pull). The Voice trace holds the lines above.
Per decision, only `cue_fired` (cue id, rule, offsets, generation, position) and `cue_ambiguous` (candidate cue ids) are written: ordinary chatter writes nothing.

### Observability and privacy

Voice diagnostics `presentation.studio.{follower_started, follower_stopped, follower_state, armed_set_changed, cue_fired, cue_ambiguous, cue_report_refused, follower_degraded, follower_recovered, follower_events_lost, follower_events_unavailable,
follower_probe_failed, follower_handler_failed}`: ids, codes, counts, rule, offsets, generation. Never a word of the room, a phrase or a transcript. Counters (`FollowerCounters`, also in `follower_stopped`): utterances, preempted_address, skipped_mode,
skipped_backoff, no_armed, no_match, fired, ambiguous, vetoed, suppressed, pulls, pull_failures, lapses, reports_{sent,fired,duplicate,failed,dropped_in_flight,dropped_preempted}, refused{code}, probe_errors, handler_errors.
**No conversation event** is added: Slice 12 decided that movement and cues are not events and that no event names a cue (`conversation-events.md` note 8), so there is no `system.presentation_studio.cue_satisfied`, no Python/JS parity to keep and no new
`ATTRIBUTE_KEYS`. The one pre-existing trace of the explicit-address path (`voice.transcript`, `voice.brain_turn_submitted` for a sentence addressed to Jarvis) is not ambient and not changed.

### Measured on the labelled sets (these sets, not an expected rate)

Three French sets, kept apart, all run through the real follower with the real authority functions (`tests/unit/test_presentation_studio_cue_corpus.py`, `pytest -s` prints the table):

| Set | Cases (pos / neg) | False positives | False negatives |
| --- | --- | --- | --- |
| implementer's first set (`presentation_studio_cue_corpus.py`) | 121 (39 / 82) | 0 / 82 = 0.0 % | 7 / 39 = 17.9 % |
| **the QA's independent set**, verbatim (`..._corpus_qa.py`, QA-1 section 4) | 84 (33 / 51) | **0 / 51 = 0.0 %** (QA measured **24 %**, 12 / 50, on the first version of the rule) | 4 / 33 = 12.1 % (QA: 3 %) |
| fresh set, written AFTER the rule was frozen and never used to tune it (`..._corpus_fresh.py`) | 43 (16 / 27) | 1 / 27 = 3.7 % | 5 / 16 = 31.2 % |
| seeded random 50 / 50 split of the union: half used to choose the numeric budgets | 124 (37 / 87) | 1 / 87 = 1.1 % | 7 / 37 = 18.9 % |
| seeded random 50 / 50 split of the union: **held-out half** | 124 (51 / 73) | 0 / 73 = 0.0 % | 9 / 51 = 17.6 % |

How the rule was re-derived: the word lists (modal and desire frames, subordinators, retractions, fillers) were written from the QA's findings (the examples quoted in QA-1) and from the implementer's first set; the four numeric budgets (1 / 1 / 6 / 4) were then chosen by a sweep on a seeded half of a union that contained a
RECONSTRUCTION of the QA's set. The QA's original file was found afterwards (it sits in the shared scratch directory) and substituted verbatim; the rule did not change after that, so the QA row is a genuine out-of-sample measurement of the frozen rule, and the table's split rows now use the verbatim file (so "selection half" is not exactly what the sweep saw).
The held-out half was not used to choose anything, but the author saw all the sets while writing the word lists, so held-out numbers are optimistic. The fresh set is the closest thing to an unseen test: it found one false positive ("La prochaine diapo": the phrase preceded by a determiner is a noun phrase), left as is, and four
direction-with-complement false negatives that are the price described above.

Conclusion to carry: the false-positive rate on these sets is **under 4 %**, the false-negative rate **12 to 31 %** (mostly transcription errors and directions with a complement); on a real room both are unknown. The accepted trade is a higher miss rate for a lower false-fire rate.
Safety categories (chatter, quoted, negated, hedged, question, partial, substring, imperative, injection, look-alike, ambiguous, address anywhere) never fire in any set.

Property runs (unchanged guarantees): 10 000 random utterances (100 random armed sets x 100) never fire an unarmed cue, never twice in a generation, never when two armed cues are whole-matched, and the decision never carries any text; 1 000 more through the follower send only `(run, generation, cue)` triples.

**Residual risks**: (1) the ambient lane has no speaker identity, so a bystander who says exactly a short stage direction ("Prochaine diapo !") fires the (reversible, pre-authorized) action; a future speaker-verified lane is the real fix; (2) the noun-phrase false positive above; (3) French only; (4) latency: the cue fires after the ambient transcription, seconds after the words;
(5) a presenter who rephrases the cue, or adds a complement, does not fire it (use `next`). None of these can execute anything beyond the armed cue's reversible actions.

### Not verified here

A live run on the OpenAI ambient transcription stack, a real microphone and a real room (Human check in [OPERATIONS.md](OPERATIONS.md), *Suivi des cues a la voix*); the HTTP hop between Voice and Core (the replay calls the same service methods in process; the typed client and routes are covered by Slice 12 tests);
the Control Center band showing `follower` (Slice 12 rework, not in this branch).

### Extension points

A speaker-verified ambient lane (owner voice) would let the follower ignore bystanders; semantic cues need a classifier and an authority decision of their own; a wider `ARM_LOOKAHEAD` is already guarded by conditions 2 and 8; a second consumer of utterances plugs into the same slot.

## Variant Explorer interaction contract (Level 3, Slice 18)

Status: implemented by Slice 18. Conformance: `tests/unit/test_presentation_studio_explorer_{core_js,js,view_js,actions_js,lifecycle_js,commands,browser,docs}.py`
(the real-Chrome proof is `_browser`, against a real Core, with real clicks and keys; `tests/fakes/explorer_{dom.cjs,world.cjs,js.py,browser.py}` are the benches).
Owner modules: `jarvis/runtime/control_center_presentation_studio_explorer_core.js` (pure: tree model, keyboard, time, French refusals, archive-plan model, CSS),
`..._explorer_widgets.js` (the virtualised ARIA tree, the dialogs, the page-side command channel), `..._explorer.js` (the controller, the only one that installs
`window.JarvisStudioExplorer`); `jarvis/domain/presentation_studio_explorer.py` (pure: closed vocabulary of the command channel) and
`jarvis/runtime/presentation_studio_explorer_commands.py` (`ExplorerCommandBroker`, `PresentationStudioExplorerRoutes`). Page markers and files are the three
`STUDIO_EXPLORER_*_SCRIPT_{FILE,MARKER}` pairs of `control_center.py`. **No Core code changed**: the explorer is a view of the graph of Slice 16 and of the
documents of Slices 04 / 09 / 17, and it writes only through the canonical operations of the relay.

**The explorer is never the source of truth.** The tree is the graph of Core (`GET .../graph?archived=1`), read again after **every** operation (and every 10 s,
so a branch made by voice appears; the change is announced). An action that fails, is refused or finds the graph stale says so on screen and assumes nothing.

### What the user sees

A dark, blurred workspace that covers the screen: the **branch tree on the left** (measured readable on a 60-deep chain plus a 20-wide fan at 800, 1280 and 1920 px: every title keeps at least 90, 110 and 150 px and 8 characters; beyond that the two-line title, the chip and the breadcrumb carry the meaning), the **preview of the selected
variant on the right** (one scene at a time, a strip of scenes under it), its **metadata** and its **actions**. The glow of the background takes the palette of the
selected variant's art direction (validated `#rrggbb` only; a default otherwise), so moving through the tree moves the mood.

| Part | Content |
| --- | --- |
| Header | title, presentation title and counts, the mode chip (`Plein écran` / `Plein écran en attente de votre clic` / `Fenêtré`, and *why* when windowed: `plein écran indisponible` / `refusé`), the fullscreen toggle, close |
| Tree row | `#12` badge (the immutable number of Core, never recomputed), title, relative creation time, creator (`vous` / `Jarvis` / `système`), number of scenes, `ACTIF` and `En lecture` flags, the rationale as the tooltip, lineage guide lines (a vertical line per ancestor with a later sibling, an elbow into the node), collapsible subtrees, indentation that shrinks with the pane width (14 px a level at most, never more than a quarter of the row) and stops growing after `MAX_DEPTH_SHOWN` 6 levels; from `DEEP_FROM` 3 levels the title takes two lines and the metadata line leaves the row; beyond 6 levels a depth chip (`⋯ ›37`) says how deep the row is; the whole path of the selected variant is a breadcrumb in the metadata and the tooltip of a row names the full title, number and rationale. Typing digits goes to the variant with that number (`TYPEAHEAD_MS` 700 ms buffer; letters stay the action shortcuts). The archived variants are a **collapsed section** (`Archivées (n)`) with their own tree |
| Preview | the real scene mounted in a `JarvisPrefabHost` of mode `preview` (no event leaves the frame), the scene title and role (`section`), the **local-variant count** of the scene as a badge (`3 variantes locales`: they stay out of the tree until promoted), the scene position, previous / next, the strip |
| Metadata | `#12`, title, parent (`Issue de #3`), creation, number of scenes, the rationale (text), chips: active, in playback, score linked or not, **art direction** (name, provenance, a palette strip; read-only, `GET .../art-direction`, its own revision) |
| Actions | `Activer` (A), `Brancher d'ici…` (N), `Renommer…` (F2), `Archiver…` (Suppr), and for an archived variant `Restaurer` (R) and `Restaurer avec ses sous-branches`. A button that cannot act is `aria-disabled` with its reason (`Cette variante est déjà la variante active.`, `64 variantes vivantes au plus…`, `Une présentation garde toujours au moins une variante vivante.`) and says it when clicked |
| Notice | one floating message (it never shifts the layout) with the real outcome, `aria-live`, a retry or reread action when there is one; a failure stays until it is dismissed |

### The preview never mutates a variant

Selecting reads `GET .../variants/{variant_id}` (read-only; 120 ms of calm first, so a burst of arrow keys reads once) and mounts the scene's pin and values in the preview
host. The page writes nothing: **the whole presentation tree on disk is hashed before and after a tour of 6 variants and 3 scenes in a real browser and is identical**
(`test_the_tree_and_the_preview_render_from_the_real_graph_and_browsing_writes_not_one_byte`). An archived variant has no preview (Core reads live variants only): the
stage says so and offers `Restaurer`. The theme of the art direction is **not** applied to the frame, because the stage does not apply it either (Slice 09 seam): the
preview shows what the stage would show. A stale preview (the variant was archived meanwhile) rereads the graph instead of reporting a failure.

### Actions: the canonical operations, nothing else

Every action is a `POST` of the variants relay (`/api/presentation-studio/presentations/{id}/variants...`, the actor forced to `user` by the relay) carrying
`expected_revision` (the manifest revision of the graph that was read). After it the graph is read again.

| Action | Request | Page behaviour |
| --- | --- | --- |
| Activate | `.../variants/{id}/activate` | idempotent; refused up front when already active |
| Branch | `POST .../variants` `{title, rationale?, source_variant_id, activate, expected_revision}` | a form (title <= 80 characters, rationale <= 600 characters **and** <= 800 bytes, counted exactly like Core, with a live counter); an invalid form never reaches Core; the new branch is selected and focused; the dialog closes first, then the graph is read |
| Rename | `.../variants/{id}/rename` | prefilled; an unchanged title sends nothing; the number never changes |
| Archive | `.../archive-plan`, then `.../archive` | below |
| Restore | `.../variants/{id}/restore` `{with_descendants?}` | the ancestors it needs come back with it; the notice says how many |

**Archive is two steps and the page has no door around them.** `archive-plan` writes nothing and answers the exact set and a token; the dialog lists **every variant that
would move (`#number`, title, short id)**, with `Annuler` focused (Enter never destroys anything). When the active variant is in the set it asks which live variant
replaces it (the suggestion is preselected; choosing another **plans again**, because the token binds that choice). The token's remaining life is a live countdown
(`Confirmation valable encore 9:41`); at expiry the confirm button is disabled and `Recalculer` appears, and an expired token is never sent. `confirmation_stale` (the
set, a title, the revision or the replacement changed since the plan, which the voice can cause while the dialog is open) **plans again under the user's eyes**, shows
`La liste a changé : 5 → 6` and waits for a new confirmation: it never executes what the user did not see. `variant_in_playback`, `limit_reached` (128 archived) and
`active_variant_protected` are refused at the plan with their French sentence, before any dialog. The relay itself refuses an archive without `confirmation` (Slice 16).
After an archive the selection leaves the archived variant for its live parent (or the active one) and the notice says where the variants went.

### Refusals, in French, each with its next step

`describeRefusal` maps every code of the variant contract (`stale_revision`, `confirmation_stale`, `confirmation_required`, `variant_in_playback`, `active_variant_protected`,
`not_archived`, `unknown_variant`, `unknown_presentation`, `linked_document_unsupported`, `scene_reloading`, `corrupt_document`, `unsupported_schema_version`, `storage_io`,
`limit_reached` by operation: 64 live to branch or restore, 128 archived to archive) to a sentence and a kind (`stale`: reread then redo; `refused`; `failed`). A timeout is
`Core ne répond pas depuis 15 s : l'action a peut-être été prise en compte. Relisez la liste avant de recommencer.`, a dead Core says nothing is affirmed. Each failure is
on screen (never only a toast: toasts are not drawn in fullscreen), logged (`[studio-explorer] op_failed {op, code, kind, status}`, never a title) and the interface is released.
A slow operation shows its verb and a live counter (`Activation… 2 s`), and a second action is refused while one runs.

### Keyboard, pointer, menu

The tree follows the WAI-ARIA tree pattern: one roving tab stop, flat `treeitem`s with `aria-level` / `aria-posinset` / `aria-setsize` / `aria-expanded` / `aria-selected`,
the DOM kept in tree order although only the visible rows plus a margin exist.

| Key | Effect |
| --- | --- |
| `↑` `↓` / `Home` `End` / `PageUp` `PageDown` | move the focus (10 rows for the pages); **the focus moves, the selection does not** |
| `→` / `←` | expand, then first child / collapse, then parent |
| `Enter` or `Space` | select (loads the preview); `*` expands the siblings |
| `F2` / `Suppr` / `N` / `A` / `R` | rename / plan the archive / branch from here / activate / restore (an archived row) |
| `Menu`, `Maj+F10`, right click, long press (550 ms, touch and pen) | the context menu: the same actions, `↑ ↓ Home End`, `Enter`, `Échap` back to the row |
| in the preview: `← →` `↑ ↓` `Page` `Home` `End` | browse the scenes (the stage and the strip are focusable); the same scene is kept when another variant is chosen (the seam of Slice 19) |
| `Échap` | **nested**: the menu, then the dialog, then the explorer (focus returns to the element that opened it) |

In real fullscreen the browser keeps the first `Échap` to leave fullscreen (the page is not told); the explorer then stays open in the window (`Plein écran quitté`),
and the next `Échap` closes it. This is the browser's rule and the explorer does not fight it (no Keyboard Lock). Keys typed in a dialog field act on nothing else.

### Entry points

- **Voice / agent**: the command channel, a sibling of the fullscreen channel (a command in flight, an exclusive long-poll, a single-use receipt, a deadline).

  | Control Center | Role |
  | --- | --- |
  | `GET /api/presentation-studio/explorer/commands?wait_s&page&visible` | the page's long-poll (<= 25 s); a hidden page receives nothing |
  | `POST /api/presentation-studio/explorer/commands` | the agent's request: `{action: "open", presentation_id, variant_id?, fullscreen?, arm_s?}` or `{action: "close"}`; answers the page's **receipt** |
  | `POST /api/presentation-studio/explorer/commands/{command_id}` | the receipt: `opened` + `mode` (`fullscreen`, `fullscreen_armed`, `windowed`) + the browser's fullscreen answer (an `open` may first send `accepted`, which pushes the deadline to `deadline_s`, 4..10 s, default 10, so a slow read of 64 documents is not cut at the 4 s delivery deadline; journal `explorer.command_accepted`), `refused` + a code of the closed list, `closed` |
  | `GET` / `POST /api/presentation-studio/explorer/state` | the page's report and the **dated mirror** an agent reads (**advisory**: the page reports on its own and the 10 s gap is real; the answer to the user must rest on the receipt `mode`, and say `dernier état rapporté il y a N s` when it quotes the mirror): `open` (+ mode, ids, the number) / `closed` / `unknown` (no visible page for 60 s) |

  **A voice open never claims fullscreen.** With no user activation the explorer is already visible in the window and the browser's one-click prompt of Slice 03 is armed
  (`fullscreen_armed`, `needs_gesture`); the agent must say the user has to click (`explanation` says it). A real click on the prompt enters fullscreen
  (`fullscreen`, read from the mirror). Codes of a refusal (closed list): `explorer_run_in_progress`, `explorer_unknown_presentation`, `explorer_unavailable`,
  `explorer_load_failed`, `explorer_page_error`, `explorer_dialog_open` (a voice open of another presentation while a form is open: the typed text is never thrown away); server codes `explorer_bad_page_token` (403: the receipt or the state report did not carry the page token the Control Center served in its HTML in `X-Jarvis-Page-Token`; journal `explorer.write_refused`), `explorer_bad_request`, `_command_busy` (409), `_no_visible_page` (504), `_command_expired` (504),
  `_unknown_command`, `_bad_receipt` / `_receipt_invalid` (the page's malformed receipt settles the command at once, 502), `_command_cancelled` (503). The prefix is in
  `READ_GUARDED_ROUTES`: a prefab frame (`Origin: null`) can neither dictate nor read. No title or rationale ever crosses the channel or the journal (`explorer.*`
  rows: ids, states, durations, codes). Slice 21 wraps it as `open_explorer` (**typed client note**: like the fullscreen channel it lives on the Control Center, not on Core, so
  there is no `LocalCoreClient` method; the tool calls these routes, the request/receipt shapes are `jarvis/domain/presentation_studio_explorer.py`).
- **Graphical**: `window.JarvisStudioExplorer.open({presentation_id, variant_id?, fullscreen?})` (the inspector of Slice 07 and any future button call it; called inside a
  click it enters fullscreen at once), `.close()`, `.isOpen()`, `.state()`, `.selection()`, `.onSelectionChange(fn)`, `.select(id)`, `.refresh()`, `.stats()`, `.inspectTree()`, `.repaint()` (the controller itself is not handed out). There is **no dock button** and **no menu entry on
  the stage window** (it exists only while a run plays, and the explorer is refused then). **Two graphical doors, both calling `open` with the ids of the surface:**
  the **header of the edit inspector** (Slice 07) carries `Variantes` (`aria-label` « Ouvrir l'explorateur de variantes », a tab stop, opens the presentation and the active variant being edited; the inspector is
  hidden during a run and in fullscreen, so the button is then `aria-disabled` with its reason, and a click in the race window is refused in the inspector's status line); and the **stopped band of the player** (Slice 12:
  « Lecture arrêtée », which stays 12 s after a clean stop and until closed after a problem) carries `Ouvrir l'explorateur de variantes` for the presentation and variant that were played (never offered while a
  run plays; the band stays while the explorer opened from it is open). Both pass their button as `opener`: closing the explorer returns the focus to it. The fullscreen of the explorer puts the inspector away
  (Slice 07 rule), so the explorer announces its closing (`jarvis:studio-explorer-closed` on `window`) and the inspector reopens and focuses its button.

### Playback

The explorer is an authoring surface. **Opening is refused while a run plays** (`explorer_run_in_progress`, French sentence, toast; the page's player is read and Core is asked,
because the player polls at rest only every 5 s), and **a run that starts while it is open closes it** within 2 s (message, focus restored): one element only can be fullscreen,
and the audience must never see the workshop. The `En lecture` flag marks the played variant and its ancestors (the ones whose archive Core would refuse); it is nearly never
visible, by design, and is the honest state in the race window.

### Accessibility, motion, security, storage

Roles: `dialog` (`aria-modal`, the rest of the page `inert`, restored to **exactly** what it was), `tree` / `treeitem`, `listbox` / `option` (scenes), `toolbar`, `menu` / `menuitem`,
`timer` (the token), live regions (`status`, `alert` for a form error). Every control has a name; text is >= 4.5:1 on the composited background (measured in Chrome over every text
class); pointer targets >= 24 px; a 2 px focus ring; forced-colors and reduced-transparency styles. Under `prefers-reduced-motion` no CSS animation or transition runs (measured); the blur
is a static effect, never animated. All author text (titles, rationales, art-direction names) is written with `textContent` after `cleanLine` (controls, NUL and bidi overrides
removed, length bounded by code points, never inside an emoji) with `dir="auto"`; `innerHTML` and friends are absent (tested in the source and by hostile titles in Chrome).
`localStorage` holds view preferences only (`jarvis.studio_explorer.ui`: folded nodes and last selection per presentation, archive open), in `try/catch`.

### Measured (Chrome headless 1280x720, this machine)

64 live variants: opened and drawn in 394 ms from the call (including Core reading the 64 documents), full render 26 ms, one repaint of the virtualised tree 2.5 ms, 17 rows in the DOM
(334 elements in all). The tree model builds 64 live + 128 archived in < 20 ms in node.

### Decisions and limits (recorded)

- **Preview by a live frame, not a stored thumbnail.** `preview_id` of the graph node stays `null`: nothing writes it, so Slice 18 adds no file and no schema. Thumbnails of scenes in the
  strip are text (number, title, role, local-variant badge): 24 frames would hit the host's `LIVE_CAP` and run 24 prefab scripts for a navigation aid.
- **Comparison is out of scope** of Slice 18 and is now the [Comparison and composition in the explorer](#comparison-and-composition-in-the-explorer-slice-19-interface) section below (Slice 19): `selection()` answers the compared variants while a comparison is open (a set of one otherwise), `onSelectionChange` still fires on a tree selection only.
- **No hard delete**: `Suppr` archives (Slice 16); restoring is in the same window.
- **The scene-window menu entry was not added**: see *Entry points*. A button in the inspector (Slice 07) or in the band of a stopped run is the natural graphical entry; both only call `open()`.
- Known limits: the art-direction **theme is not applied** to the preview frame (neither is it on the stage); a variant whose file is unreadable shows `À vérifier` and no preview; the page reads the
  graph every 10 s only while open and visible; the in-page `JarvisStudioPlayer` view and Core's playback state are the two sources of the playback guard.

### Human checks (not provable headless)

Physical `Échap` in real fullscreen, a second screen or a projector (`display` of the fullscreen request is not exposed by the explorer: it is the current display), the look of the glow and
the blur on the real display, and a screen reader (NVDA/Narrator) reading the tree: see `docs/OPERATIONS.md` › *Explorateur de variantes*.

## Edit inspector UI (Level 3, Slice 07)

Status: implemented by Slice 07. Conformance: `tests/unit/test_presentation_studio_inspector{_js,_behaviour_js,_browser,_docs}.py` (`_js` and `_behaviour_js` run the real module under node against a
miniature Core, `_browser` drives a **real Chrome** against an isolated real Core and the real Control Center page; bench `tests/unit/_studio_inspector_bench.cjs`, harness
`tests/unit/_presentation_studio_inspector_browser.mjs`, fixtures `tests/fakes/presentation_studio_inspector_browser.py`).
Owner: three page files spliced in this order after the player module: `jarvis/runtime/control_center_presentation_studio_inspector_core.js` (constants, CSS and the pure functions: `widgetSpec`, `validateValue`, `setAtPath`...; marker `/*__CONTROL_CENTER_PRESENTATION_STUDIO_INSPECTOR_CORE_JS__*/`), `..._widgets.js` (the generated widgets, three gestures only: preview, idle, commit; `..._WIDGETS_JS__*/`) and `jarvis/runtime/control_center_presentation_studio_inspector.js` (the controller: state, network, commit queue, history, local preview, availability; the only one that installs and publishes `window.JarvisStudioInspector`; `..._INSPECTOR_JS__*/`),
dock button `INS` (`#openStudioInspector`) and panel `#jvStudioInspector` (docked left of the dock, same place and tokens as the ERR / TRC / AGT panel). The only Core addition is the read-only relay
`GET /api/presentation-studio/presentations/{id}/variants/{vid}/art-direction`.

The inspector is the **optional tactile surface of the semantic edit API**. It is generated, not hand-written: a scene is described by the introspection route
(`GET .../variants/{vid}/scenes/{scene_id}/controls`, *Scene and control contract*) and every widget, bound, default and sentence comes from that answer. There is **no per-control code**
(`widgetSpec` is the only table) and **no inspector-only write**: every mutation is `POST .../variants/{vid}/edits` (or `.../undo`, `.../redo`) through the relay, actor forced to `user`, with
the same refusals, the same basis and the same undo record as the voice. A tier-3 source edit has no entry point here (voice / agent only); the inspector only *shows* what the reload service says.

### Widgets: derived from the introspection row (`widgetSpec`)

| Row `type` / `widget` | Widget | Notes |
| --- | --- | --- |
| `number` / `integer` bounded both ends (`slider`) | range + number field + − / + steppers | bounds are `row.bounds` (the manifest narrowed by the author, never wider); step 1 for an integer, else a power of ten near 1/100 of the range (`stepFor`); a typed value is not forced to the step |
| `number` / `integer` not bounded both ends (`number`) | number field + − / + steppers | |
| `boolean` (`toggle`) | `role="switch"` button | commits at once |
| `color` | native colour picker + `#rrggbb` field | live preview while the picker moves, commit on its `change`; hex field commits on Enter / blur |
| `enum` (`choice`) | segmented `radiogroup` for at most 4 short choices, else `select` | commits at once; arrows / Home / End move inside the group |
| `string` (`text_line`), `url` | one-line field with a length counter | |
| `text` (`text_area`) | text area with a counter | Enter is a new line, Ctrl+Enter commits |
| `array` whose current value is a list of `#rrggbb` | **colour stops** editor: gradient bar, one picker + hex per stop, move up / down, remove, add (bounded by `max_items`) | every structural change is one commit |
| any other `array` | JSON text area, **guarded**: parsed before anything is sent, `JSON invalide` is shown and nothing leaves the page, then Core validates the items | the item schema is not in the introspection answer (see limits) |
| anything else (`object`) | read-only JSON | never editable |

Each row shows the control `label`, its `meaning` (the author's words, also the accessible description), a state (`par défaut` / `modifié` / `aperçu · non enregistré` / `enregistré`), the default when it
differs from what is shown, and `Rétablir` (`control.reset`, offered only for a value that was set). Controls are grouped by `group` into tabs (`Contenu`, `Style`, `Mise en page`, `Mouvement`; a tab with its
count; ARIA tabs with roving focus). **Client-side validation** (`validateValue`: bounds, integer, `#rrggbb`, choices, http(s) URL, length, item count, JSON) only saves a round trip: Core stays the authority
and its own refusal is shown when it says more (for example a `pattern`).

### Preview versus commit (ENTRY CONDITION of the Persistence and undo contract: one commit = one undo entry, the ring holds 32)

| Gesture | While it goes on | When it ends |
| --- | --- | --- |
| drag a slider / colour picker | `mode: "preview"` at most every `PREVIEW_MIN_MS` = 120 ms, **only the latest value** (intermediate values are dropped, never queued), one request in flight; the local preview frame follows at once | **one** `commit` on pointer release (pointer up / cancel, `change`, blur, Enter) with `basis.variant_revision` and `if_current` |
| type in a text / URL field | preview at most every `TEXT_PREVIEW_MS` = 250 ms | one commit on Enter (Ctrl+Enter in a text area), blur or `change`; Escape abandons the draft first, then closes the panel |
| **every stepping path**: keyboard on a slider, − / +, a **number field** (typed digits, ArrowUp / ArrowDown, spinner, mouse wheel: Chrome fires `change` at every step), colour picker, gradient stop picker, arrows on a radio group or a closed list | preview (120 ms) | **one** commit after `IDLE_COMMIT_MS` = 700 ms without another step, or at once on Enter / blur / pointer release. No input path commits directly: a node test steps every widget five times and requires 0 commits during and exactly 1 after, and a real-Chrome test presses ArrowUp five times in 300 ms (1 history entry, 1 revision), holds it 2 s (at most 3 commits) and rolls the wheel (at most 1) |
| toggle, a click on a radio, reset, stop edits (add, move, remove) | none | one commit at once |

A preview never writes: no file, no revision, no event, no undo record (*Semantic edit contract*), proved in a real browser by hashing the variant file mid-drag. Commits are **serialised** (one at a time) and **rebased**: the operation (`if_current` and the basis) is built when the commit starts, from the values re-read after the previous commit, never on the base that
our own earlier write just made stale (a draft made while a commit is in flight waits and is sent against the new base; the draft is kept if the user went on adjusting). A not-yet-started commit for the same control is replaced by the newer one. An unchanged value sends nothing.

**The local preview card.** Outside a run there is no stage window (Slice 12 owns it: one per run), so the inspector mounts the scene's prefab in a sandboxed frame of its own through
`JarvisPrefabHost` in `mode: "preview"` (the host's existing preview mode: events are dropped, nothing is posted to Core, same sandbox and CSP, no `jv:1` change, `studio-inspector-preview`). It shows the stored
values plus the draft; it is **not** the projected scene and applies no art direction theme. During a run the whole inspector is hidden, so it never competes with the real stage.

### Typed answers: what the user sees (every one is also logged)

| Answer | Shown | Then |
| --- | --- | --- |
| `applied` (commit) | `enregistré`, live-region announcement | values and history re-read (`GET controls`, `GET history`) |
| `refused`: `value_refused`, `scene_incompatible`, `limit_reached`, `prefab_unavailable`... | the row, tied to the field (`aria-invalid`, `aria-describedby`), with **Core's own message** | widget returns to the stored value |
| `refused`: `unknown_control` / unknown scene | `Ce réglage n'existe plus sur cette scène` | the control list is rebuilt from Core |
| `stale` on a **commit** | `il n'a pas été appliqué`, then the list of what changed (`label : before → after`, up to 5) | values re-read, the other writer's value is kept and shown, **Réappliquer ma valeur (X)** commits against the new base; never an overwrite |
| `stale` on a **preview** | the same list; the gesture restarts from the value just read | the release commits against what the user was told |
| `409 presentation_studio_scene_reloading` | status `Rechargement en cours`, `tentative n/5 · prochaine dans N s`, **Arrêter d'attendre** | automatic bounded retry (`RELOAD_RETRY_MS` = 0.8, 1.5, 2.5, 4, 6 s, about 15 s), then `Rien n'a été enregistré` with **Réessayer** |
| source `degraded` / `pending_mount` (read from `GET .../reloads`, every 4 s while open) | banner `Source dégradée` / `Source récente non confirmée`; a last reload whose `reset.unfit` is not empty (Slice 06 QA-2: required values the new source no longer accepts, kept as written) shows `Valeurs à corriger après le rechargement` naming them | informational: control edits are not blocked |
| the scene's source, always (read-only line from the same answer) | `Source du modèle : N versions (+ M archivées) · dernier rechargement : <état>` from `versions[scene_id]` (`live`, `archived`) and the newest row | none; a **new reload row** (voice, another tab) makes the page re-read the scene at once |
| `stale` on a commit while **no control changed** (the revision moved because a source reload re-pinned the scene, or the art direction, or a write elsewhere) | nothing | **rebased silently once** on the re-read base (`stale_rebased` info line); `if_current` still protects this control's value. A change to any control keeps the visible `stale` path above |
| transport failure, Core silent | `Chargement impossible` / `Enregistrement impossible` with the real cause and **Réessayer**; every request has a 15 s deadline and a live `n s / 15 s` counter | never a spinner without an exit |
| undo / redo: `history_unavailable`, `nothing_to_undo`, `nothing_to_redo`, `stale`, `refused` | `Annulation impossible` + the status and Core's message (after a restart: `Historique indisponible`) | `stale` re-reads; the page passes `expected_entry_id` of the entry it showed |

Every failure is a `[studio-inspector] <key> {json}` console line (`warn` / `error`) and, when the page defines one, a call to `obsClientLog` (this repository has no `obsClientLog`: the console line is the record, and
the relay journals each request as `presentation_studio.request.relayed` with status and code). Errors are toasted when the user did not cause them in view. Nothing swallows an error.

### Undo, redo, keyboard

Buttons `↶` / `↷` and **Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z)** only while focus is inside the inspector. **Rule: undo / redo discard a pending draft first.** Ctrl+Z on a control with an unsent draft only abandons that draft (like Escape, no history call); the buttons abandon every pending draft and then undo, so a discarded draft never commits afterwards and never wipes the redo entries. In a text field with an unsent draft Ctrl+Z stays the browser's text undo. The page keys (`s`, `e`, `t`, `a`, arrows,
Home, End, Space, `p`...) never leave the panel (`stopPropagation` on the panel, Tab / F-keys / browser shortcuts pass); the module installs **no** document-level capture handler, so the presentation navigation keys
(Slice 12: acting only on the stage host) are untouched. Escape closes the panel and returns focus to the dock button. Full keyboard operation of every widget, visible focus rings, native roles, 24 px minimum targets.

### Hidden entirely during a run and in fullscreen

`JarvisStudioPlayer.view()` (`running` and not `idle` / `stopped`) or `document.fullscreenElement` hides the panel entirely (`hidden` + `inert`), abandons any draft (never written), unmounts the preview frame, stops its
polling, **closes** it (it comes back closed, not forced open) and disables the dock button with the reason as its title. The check runs every 500 ms, on `fullscreenchange` and on the window event `jarvis:studio-playback` that the player dispatches the moment its state flips between running and not running; opening also asks the player to refresh.
Known window (kept): a run started by the voice is learned by the player on its poll (idle 5 s), so the inspector can stay visible for up to that long; the event then hides it at once instead of at the next 500 ms tick. An edit in that window is a normal edit (Core pauses the run, Slice 12).

### Short screens and the dock

Below 700 px of height the local preview starts **folded** (unless the user chose otherwise: the stored preference wins), an open preview keeps at most 150 px and loses its note, and the reload card is two lines. The dock now holds **ten** tools: cosmos row 10 x 34 + 9 x 6 = 394 px; at 620 px of width and below the cosmos row wraps into **two rows of five** (194 x 74 px) and the top bar, the pills and the panels sit under it; the vertical dock shrinks to 44 px buttons below 720 px of height, 38 px below 560 px and, at 480 px and below, becomes **two columns of five** (the panels move 50 px left). Checked by a geometry sweep over widths 360 / 500 / 566 / 700 / 1024 / 1280 and heights 600 / 720 / 900 in both themes (all ten buttons on screen, none overlapping the Boards button, the voice state, the pills or each other) and by `test_boards_hud_browser.py` unmodified.

### Art direction chip (read-only) and the theme variables decision

A chip reads `GET .../variants/{vid}/art-direction` (relay, actor `user`, no write): name, provenance (`fournie` / `déduite` / `générée`, `repli`), the text-on-background contrast recomputed from the palette
(WCAG ratio, `✓` at 4.5), five swatches. Because saving a DA does **not** bump the variant revision (*Art direction contract*), the chip compares the DA's **own `revision`** (re-read every 8 s while open) and announces a change.

**Decision (Slice 09 QA-1 I2): the 10 `--jv-*` variables with no delivery path are shown as `non appliqué`, not hidden.** The frame applies only the five of `THEME_VARS` in `shim.js` (`--jv-accent`, `--jv-text`,
`--jv-muted`, `--jv-surface`, `--jv-scale`); `--jv-font`, `--jv-radius`, `--jv-gap`, `--jv-ground`, `--jv-veil`, `--jv-title`, `--jv-link`, `--jv-body`, `--jv-edge`, `--jv-wash` are produced by the DA but nothing can set
them in a frame today, so a user who changes a DA must not believe typography or radius followed. The lists are constants of the module; a test compares them with `ALLOWED_THEME_VARIABLES` and with the shim, so a
change on either side fails. Extending the shim (same validated grammar) is a protocol change and out of this Slice.

### Persistence

None of its own. `localStorage` holds one key (`jarvis.studio_inspector.ui`: the last tab and whether the preview is open), read and written inside `try/catch`. No draft, no value, no selection is stored; a reload of the
page starts from Core. The presentation shown is the first one `GET /presentations` lists (most recent first) and its **active** variant; choosing another variant is Slice 18.

### Limits and decisions (recorded)

- **No unit, no step, no enum labels, no array item schema in the introspection answer** (the manifest `InputSchema` has none of them): the step is derived, a unit is not shown (put it in the control `label` or `meaning`),
  enum values are shown as the manifest spells them, and a non-colour array is a guarded JSON editor. Adding `unit`, `step`, `labels` or `items` to the manifest and the answer is the clean fix (PM question).
- The scene preview image (`preview {caption, alt}`) is not drawn: the live preview card replaces it.
- The recovery report of Slice 08 (`last_recovery`) still has no route, so the inspector cannot show it.
- A scene is read with two requests (variant document and controls) and its values are paired by the controls answer's `variant_revision`; any other writer in between is the `stale` path above.

### Extension points

| To add | Where | Rule |
| --- | --- | --- |
| a widget for a new input type | `widgetSpec`, `validateValue` and a `*Widget` builder together, one test row each | never a widget keyed by a control id |
| a new typed answer | `classifyEdit` / `describeRefusal` and the table above | say Core's own message |
| a gesture that commits | call `onCommit`; a continuous one calls `onPreview` first | never one commit per input event |

## Comparison and composition in the explorer (Slice 19, interface)

Status: implemented by the second half of Slice 19, on top of the Slice 18 explorer and the backend contract below. Conformance:
`tests/unit/test_presentation_studio_explorer_compare_{core_js,js,browser}.py` (benches: `tests/fakes/explorer_compare_world.cjs`, a tiny Core that speaks the compare / composition
routes; the browser test runs against a REAL Core). Owner modules, loaded by three more page markers (`STUDIO_EXPLORER_COMPARE_CORE|COMPARE|COMPOSE_SCRIPT_{FILE,MARKER}`, between the
widgets and the controller): `jarvis/runtime/control_center_presentation_studio_explorer_compare_core.js` (pure: marks, layout, pane model, statuses, keys, French refusals, composition
request, conflict rows), `..._explorer_compare.js` (the panes, the toolbar, the links dialog, the command actions), `..._explorer_compose.js` (the composition dialog and `plan` / `commit`).
**No Core code changed**: the panes read `GET .../compare` and `GET .../variants/{id}` and write only through the relay routes of the backend contract.

**The comparison is Core's state, shown.** Equivalence of scenes, the pair, the mode, the links and the status of a navigation are read from Core's answer, never guessed by the page.
A gesture that is refused or stale (`stale_revision`, an archived compared variant) is said on screen in French and the view is read again. The panes mount each variant's scene in the
same `preview`-mode prefab host as the single preview (`studio-explorer-cmp-<index>` objects, at most 4 frames, released when a pane is hidden): no event leaves a frame and no variant is
written (a real-Chrome test hashes the whole presentation tree before and after a comparison with navigation, a refused link and the mode toggle: identical).

### Entering, leaving

| Gesture | Effect |
| --- | --- |
| `C` on a tree row, `Ctrl` + click, or the context menu entry | **mark** (or unmark) the variant for comparison; marking never moves the selection and writes nothing. A marked row has a `✓`, an accent edge and `marquée pour la comparaison` in its accessible name. An archived variant is refused with its reason; a 5th mark is refused |
| the bar under `Évolution` (`2 variantes marquées…`), `Comparer`, or `Maj`+`C` on a row | start the comparison: **exactly 2 or 4** marks, otherwise the button is `aria-disabled` and its title says why (`Marquez-en au moins une autre`, `2 ou 4 variantes…`). `POST .../compare/select` |
| `Échap` | nested: menu, dialog, **the comparison** (the single preview comes back, the focus returns to the opener), then the explorer. Leaving also clears Core's set (`compare/clear`) |
| `Fermer la comparaison` | same as `Échap` |

A comparison opened by an agent through the Core routes appears in an open explorer at the next 10 s read (`compare_adopted`, `Une comparaison a été ouverte ailleurs`), and one cleared
elsewhere closes the panes: the state is Core's.

### What the user sees

The compare view replaces the single preview (the tree stays on the left, with the marks). Toolbar: title (`Comparaison · 4 variantes`), the **mode** toggle (`Navigation synchronisée` /
`Navigation indépendante`, `aria-pressed`, key `M`), a chip with the structure relation (`Structures identiques` / `Ordre différent` / `Structures différentes`), `Liens… (n)`, `Composer…`,
`Tout afficher` (only in the pair view) and `Fermer la comparaison`.

| Layout (`view.layout`) | Panes | Grid |
| --- | --- | --- |
| `two_up` | 2 | 2 columns |
| `four_up` | 4 | 2 x 2 |
| `focus` | the chosen pair only, **50/50**; the other panes are hidden and release their frames | 2 columns of equal width |
| narrow (the compare area under 560 px: a container query) | any | 1 column, the area scrolls |

Each pane: `#number`, title, `Actif`, a **status chip**, the 16:9 preview, previous / next, a scene list (`01 · Ouverture`, the same names for all panes), `n / total`, one sentence, and two
buttons (`Vis-à-vis` with 4 variants, `Lier cette scène…`). The pane is a focus stop (`role=group`, `aria-label` such as `Variante 4, Sobre, scène 2 sur 3 : Les chiffres, synchronisée`).

| Status (from `navigation` of the last move) | Chip | Sentence |
| --- | --- | --- |
| `origin` | Choisie | `Vous avez choisi cette scène.` |
| `synced` | Synchronisée | `Suit la scène choisie (scène équivalente).` |
| `unmapped` | Sans équivalent | `Aucune scène équivalente : cette fenêtre garde sa scène. Liez-la à la main, ou passez en mode indépendant.` The pane **keeps** its scene; the link button is emphasised |
| `held` | Indépendante | `Mode indépendant : seule la fenêtre choisie a bougé.` |
| none yet | no chip | the mapping of the shown scene (`Même scène logique`, `Scène liée à la main`, `Sans équivalent dans les autres variantes`) |

**Divergent structures never block.** The banner says `Structures différentes : n scènes sans équivalent` with `Passer en mode indépendant` and `Gérer les liens`; sync works where the mapping
exists, the rest is a manual link or independent mode. The **links dialog** (`L`, `Liens…`, `Lier cette scène…`) lists the manual links (`#1 · scène 2 « Deux » ↔ #4 · scène 20`, a stale one is
flagged and never applied), removes one, and adds one from two (variant, scene) selects; Core's refusals are said inline (`compare_mapping_conflict`: `Ce lien mettrait deux scènes d'une même
variante en face l'une de l'autre…`; the 64-link cap; `stale_revision`).

### Keyboard (inside the comparison)

| Key | Effect |
| --- | --- |
| `←` `↑` / `→` `↓` / `PageUp` `PageDown` / `Début` / `Fin` on a pane | previous / next / first / last scene of **that** pane (`POST compare/navigate` with `step`; in sync mode the equivalents follow). Navigation sends no expected revision (last write wins; repeated keys never go stale against each other) |
| `M` | toggle sync / independent |
| `F` | 4 variants: pick this pane for the 50/50 pair (a second pick sends `compare/pair`); in the pair view, back to all |
| `L` | links dialog for this pane's scene |
| `Maj`+`C` | composition dialog |
| keys in a scene list | native `select` behaviour (the change navigates) |

### The composition dialog

`Composer…` opens a dialog over the comparison: **title** (<= 80 characters), **base** (the parent; among the compared variants), one **source per dimension** — `Scènes`, `Narration`,
`Mouvement`, `Direction artistique`, each `Comme la variante de départ` (omitted from the request, so Core records it as inherited) or one compared variant —, an optional **reason**
(<= 400 characters), `on_unmapped` (`refuse` / `keep_motion`) and `Activer la nouvelle variante tout de suite` (default off).

- **Plan first, always.** Every change re-runs `POST .../compositions/plan` after 400 ms (and once on opening); `Créer la variante` stays `aria-disabled` until the plan shown is `ok` for
  **exactly** the current form (the request signature), and pressing it with an old or missing plan only re-plans. A test pins that the commit body equals the last plan body and that the
  request order is plan then commit.
- **Conflicts are listed all together**, each with its dimension name, Core's message and `À faire : <fix>` (text from Core, cleaned and written with `textContent`), `data-code` = Core's code.
  A commit refused at the door (`composition_refused`, state changed after the plan) shows its conflicts the same way and creates nothing.
- **An accepted plan** says `Aucun conflit` and shows the result (scenes, items) and the provenance per dimension (`Narration : prise de #4`, `Mouvement : héritée de #1`).
- **The request** carries `source_revisions` of every source actually used, read from the comparison view **re-read just before each plan**, and `expected_revision` (the graph revision the
  explorer holds); never `actor` (the relay forces `user`). A moved source gives `stale_revision`: said, the view re-read, the plan to redo.
- **Commit** creates ONE new child of the base (`POST .../compositions`, 201). The dialog closes, the tree re-reads Core's graph, **reveals and selects the child**, and the notice says
  `Variante #13 composée (...). Les sources n'ont pas bougé.` The comparison stays open. The sources are byte-identical afterwards (a real-Chrome test hashes the two variant files).

### Page API and command entry points (what Slice 21 can drive)

`window.JarvisStudioExplorer` gains two frozen objects (the explorer must be open; a refusal is an `{error}` or a `state: "refused"`):

| Entry | Effect |
| --- | --- |
| `compare.open({variant_ids, pair?, mode?})` / `.close()` / `.isOpen()` / `.view()` / `.state()` | start (2 or 4 live ids) / close / read the last Core view |
| `compare.mark(id)` / `.marks()` | the marks of the tree |
| `compare.focus(pair or null)` / `.mode("sync"|"independent")` / `.navigate({variant_id, scene_id | step})` / `.link(a, b)` / `.unlink(a, b)` / `.refresh()` | one call per Core compare route |
| `compose.plan(request)` | re-reads the comparison, builds and signs the request (`source_revisions`, `expected_revision`), `POST compositions/plan`; answers `{ok, conflicts: [{code, dimension, dimensionLabel, message, fix}], summary}` or `{error}` |
| `compose.create(request)` | plan, then — only if the plan is `ok` — `POST compositions`, then the tree selects the child; answers `{ok, created, variant_id, variant_number, message}` or `{ok: false, conflicts}`; the same request keys as the backend contract (`scenes` as one variant id; segments are not offered here) |
| `compose.dialog({preset?})` | open the dialog, optionally prefilled |

The page-side command handler (`handleCommand`, the function the command channel calls) understands, besides `open` / `close`: `{action: "compare", op: "open"|"close"|"focus"|"mode"|"navigate"|"link"|"unlink", ...}` and
`{action: "compose", op: "plan"|"create"|"dialog", request}`; each answers `{state: "done", view}` (a bounded summary: layout, pair, mode, anchors, relation, link count, statuses) or
`{state: "refused", code: "explorer_page_error", reason, conflicts?}`.

**What is deliberately NOT extended: the Python broker.** `ExplorerCommandBroker` / `jarvis/domain/presentation_studio_explorer.py` still carry `open` and `close` only (closed vocabulary,
1 KiB receipts: a conflict list does not fit). The agent does not need it: the compare state is Core's, and the Slice 21 tools `presentation_compare` / `presentation_compose` call the **Core
routes** of the backend contract directly (never typed ids from memory, `actor: "brain"` set by the tool layer); an open explorer shows the result at the next 10 s read, and
`open_explorer` (Slice 18) is the only call that needs the page. If Slice 21 wants an immediate refresh it adds `compare` to `ACTIONS` with the shapes above and a bounded receipt; the page
side is ready and tested.

### Limits of this half

- The scene strip of each pane is a text list (`select`), not thumbnails (24 live frames would hit the host's `LIVE_CAP`).
- `scenes` is one source variant in the dialog; the segment form of the backend request is reachable by the API only through a future extension.
- Marks are interface state of the page (lost on close, never stored); the pair pick (first of two) is local until the second.
- Physical checks (a screen reader on the panes, the look on a projector, touch) are Human checks: `docs/OPERATIONS.md` › *Explorateur de variantes*.

## Comparison and semantic composition contract (Level 3, Slice 19 backend)

Status: implemented by Slice 19 (backend and domain; the side-by-side UI is described in [Comparison and composition in the explorer](#comparison-and-composition-in-the-explorer-slice-19-interface)). Conformance:
`tests/unit/test_presentation_studio_{compare,compose_service,compose_routes}.py`.
Owner modules: `jarvis/domain/presentation_studio_compare.py` (pure: `CompareState`, scene equivalence classes, transitions, the view),
`jarvis/core/presentation_studio_compare.py` (`PresentationStudioCompare`: in-memory state), `jarvis/domain/presentation_studio_composition.py`
(pure: request, typed conflicts, provenance document, scene selection, narrative merge), `jarvis/core/presentation_studio_composition.py`
(`PresentationStudioComposition`: plan, compose, provenance), the `compose=` / `dry_run=` seam of `PresentationStudioVariants.create_branch`,
routes `jarvis/protocol/presentation_studio_compose_routes.py`, relay `jarvis/runtime/presentation_studio_compose_relay.py`, typed client
`LocalCoreClient.presentation_studio_{compare,compare_op,composition_plan,compose,composition}`.

Two independent things share the page: **comparing** (reading, interface state, nothing is written) and **composing** (one write, always a
new child variant). Neither merges files; neither modifies a source variant.

### Comparison set (interface state, memory only)

A comparison set is the state of one Presentation's compare view: 2 or 4 **live** variants (`variant_ids`), an optional focused pair, a mode, the
manual scene links and the current scene of each variant. It lives in Core memory (one set per Presentation, the 16 most recently used
Presentations are kept) and dies with Core: no file, no manifest, no undo ring, no event. A page after a restart starts empty
(`GET .../compare` answers `active: false`). `revision` counts the transitions of the set (0 when empty); every operation takes an optional
`expected_revision` (409 `presentation_studio_stale_revision` when another page moved it).

| Field | Meaning |
| --- | --- |
| `variant_ids` | exactly 2 or 4 distinct live variants; 1, 3, 5+ or a duplicate is `presentation_studio_invalid`; unknown or archived: 404 `presentation_studio_unknown_variant` (an archived variant is restored first) |
| `pair` | `null`, or two members: the **50/50 focus**. `layout` is `focus` when set, else `two_up` (2) / `four_up` (4) / `empty`; `shown` is the pair or the whole set |
| `mode` | `sync` (default) or `independent` |
| `anchors` | `{variant_id: scene_id or null}`, the scene each pane shows (the first scene when selected) |

### Logical scene mapping

The **logical scene** is an equivalence class of scenes across the compared variants, built from two rules and nothing else:

1. **identity**: a branch keeps the `scene_id` of its source, so an equal `scene_id` in two variants is the same logical scene (the variant may have changed its content: that is what is compared);
2. **manual link**: the user pairs scenes whose ids differ once the structures diverged. Classes are transitive (a link to one member joins the class).

A link that would put two scenes **of one variant** in a class is refused (409 `presentation_studio_compare_mapping_conflict`; remove the link that already joins one of them). A link needs two different compared variants and two real scenes (`presentation_studio_invalid`, 404 `presentation_studio_unknown_scene`), at most 64 per set (`presentation_studio_limit_reached`). A link whose scene or variant has since disappeared is returned with `stale: true` and **never applied**. `(a, b)` of a link is in canonical order (variant id, scene id), not the order of the request: treat it as unordered.

Per variant and per scene the view gives `mapping` (`identity`, `manual`, `none`), `equivalents` (`{variant_id: scene_id}` in the other compared variants) and, for a scene with no equivalent anywhere, up to 4 `suggestions` (scenes of other variants that have no equivalent in this one and use the same prefab id: candidates for a manual link, never applied). Per pair, `structure.pairs[]` says `relation`: `identical` (same logical scenes, same order), `reordered` (same scenes, other order), `divergent` (scenes without counterpart; also `shared`, `only_a`, `only_b`, `order_preserved`); `structure.relation` is the worst of them.

**Navigation.** `navigate` sets the scene of one variant (`scene_id`, or `step`: `next`, `previous`, `first`, `last`, which clamp at the ends) and, in `sync`, the scene of every other variant where an equivalent exists. The answer adds `navigation: {origin: {variant_id, scene_id}, results: {variant_id: {scene_id, status}}}`; `status` is `origin`, `synced`, `unmapped` (no equivalent: that pane **keeps** its scene; show "no equivalent scene", offer the link or `independent`) or `held` (`independent` mode: only the origin moves). Divergent structures therefore never block the user: sync where the mapping exists, link by hand, or switch to `independent`.

### Operations (Core, loopback, bearer token, same guard and envelope as the other Studio routes)

| Method and route | Body | Answer |
| --- | --- | --- |
| `GET /v1/presentation-studio/presentations/{presentation_id}/compare` | none | the **view** (below); empty: `active: false`, `revision: 0`, `layout: "empty"` |
| `POST /v1/presentation-studio/presentations/{presentation_id}/compare/select` | `{variant_ids: [2 or 4], pair?, mode?, expected_revision?}` | the view; replaces the selection, keeps links between variants still selected |
| `POST /v1/presentation-studio/presentations/{presentation_id}/compare/pair` | `{pair: [a, b] or null, expected_revision?}` | the view |
| `POST /v1/presentation-studio/presentations/{presentation_id}/compare/mode` | `{mode: "sync" or "independent", expected_revision?}` | the view |
| `POST /v1/presentation-studio/presentations/{presentation_id}/compare/navigate` | `{variant_id, scene_id` **or** `step, expected_revision?}` | the view plus `navigation` |
| `POST /v1/presentation-studio/presentations/{presentation_id}/compare/links` | `{a: {variant_id, scene_id}, b: {variant_id, scene_id}, expected_revision?}` | the view (the same link twice changes nothing) |
| `POST /v1/presentation-studio/presentations/{presentation_id}/compare/links/remove` | same body | the view (404 `presentation_studio_unknown_scene` when there is no such link) |
| `POST /v1/presentation-studio/presentations/{presentation_id}/compare/clear` | `{expected_revision?}` or none | `{presentation_id, cleared, active: false, revision}` |
| `POST /v1/presentation-studio/presentations/{presentation_id}/compositions/plan` | a composition request (below) | `{ok, dry_run: true, conflicts, composition}`; writes nothing |
| `POST /v1/presentation-studio/presentations/{presentation_id}/compositions` | the same request | 201 the answer of a branch plus `composition`; or 409 `presentation_studio_composition_refused` with `error.conflicts` |
| `GET /v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/composition` | none | `{composition}`: the persisted provenance |

The **view**: `{presentation_id, revision, active, variant_ids, layout, pair, shown, mode, variants: [{variant_id, variant_number, title, revision, active, scene_count, scenes: [{scene_id, index, title, prefab: {id, version}, mapping, equivalents, suggestions}]}], structure: {relation, pairs}, unmapped: {variant_id: [scene_id]}, links: [{a, b, stale}], anchors, problems}`. It is recomputed from the stored variants at every call (the structures can move between two calls). A selected variant that stopped being live appears in `problems` (`{variant_id, code: "variant_unavailable"}`) and is missing from `variants`; navigation then answers 404 `presentation_studio_unknown_variant`: select again. The view carries the `revision` of each variant: pass those as `source_revisions` of a composition so that what the user compared is what is composed. Body keys follow the Studio rule that runtime-only names (`selected`, `focus`, `cursor`, `position`...) are refused, hence `pair` and `anchors`.

### Semantic composition: always a new child, sources immutable

A composition request names, per **semantic dimension**, the variant it borrows from. There are four dimensions and no others:

| Dimension | Borrows | Default |
| --- | --- | --- |
| `scenes` | the scene list: structure, pinned prefab, values, controls, anchors and the scene's local variants, exactly as the source stores them (the Slice 06 branch normalisation applies: a copy takes the last valid pin of an unconfirmed reload and a scene that is reloading refuses the copy). One variant id, or 1..4 segments `{from, scene_ids?}` in the order of the result (`scene_ids` omitted: all scenes of `from`) | the base, all scenes |
| `narrative` | per score item, `label`, `text` and `note` (what is said and the intention). Items are matched by `item_id` (a branch keeps item ids) and otherwise by rank inside the same scene | the base |
| `motion` | the rest of the score: item skeleton and order, visual / motion actions, timing, interruption, recovery, cues, locked sequences, recovery points | the base |
| `art_direction` | the whole art direction document, deep-copied under a new `psd_` id | the base |

`base` (required) is the variant the child branches from: it is the **parent** (`parent_variant_id`) and the default of every dimension. A dimension the request does not name is *inherited*, and the provenance says so (`inherited: true`): nothing is implicit. `narrative` and `motion` come from one score document each; when they name the same variant the score is copied whole. The result's `sources` (manifest node) are the distinct contributing variants, base first, at most 4 (`MAX_SOURCES`).

**Request** (both composition routes, same body, at most 64 KiB):

```json
{
  "title": "Direction sobre + ton de Beta",
  "base": "psv_...",
  "rationale": "optional, one printable line, <= 400 characters (the composition prefixes its own summary line)",
  "scenes": "psv_...",
  "narrative": "psv_...", "motion": "psv_...", "art_direction": "psv_...",
  "on_unmapped": "refuse",
  "source_revisions": {"psv_...": 3},
  "activate": false, "actor": "user", "expected_revision": 7
}
```

`scenes` is a variant id or `[{"from": "psv_...", "scene_ids": ["pss_..."]}, ...]`. `on_unmapped` is `refuse` (default) or `keep_motion` (an item of the motion source with no equivalent in the narrative source keeps its own narration; reported as a warning and in the provenance). `source_revisions` and `expected_revision` are compare-and-set: a source or the Presentation that moved is 409 `presentation_studio_stale_revision` ("reload the comparison, then retry"), before anything is written. Unknown keys, malformed ids, an empty `scene_ids`, a duplicate, more than 4 segments are 400 `presentation_studio_invalid` before any file is read. An unknown or archived source is 404 `presentation_studio_unknown_variant`.

**Plan, then commit.** The plan runs the *same* composer under the same lock and writes nothing and spends no variant number (the `variant_id` inside its `composition` is a placeholder, not reserved). The commit answers 201 with the answer of a branch (`variant`, `node`, `presentation_revision`, `activated`, `source_variant_id` = base, `linked`) plus `composition` (the provenance document plus `result: {scene_count, scene_ids, has_score, has_art_direction, item_count, sources, parent_variant_id, summary}`), or **409 `presentation_studio_composition_refused`** with every conflict:

```json
{"error": {"code": "presentation_studio_composition_refused", "message": "2 conflict(s), first: ...",
           "conflicts": [{"code": "score_scene_missing", "dimension": "motion", "message": "...", "fix": "...", "details": {}}]}}
```

The typed client raises `CoreProtocolError(409, "presentation_studio_composition_refused")` with `details["conflicts"]`. Conflicts are collected together (all of them, not the first) and **before any write**: no file, no number, no event.

| Conflict `code` | Dimension | When | `fix` (given in words in the answer) |
| --- | --- | --- | --- |
| `too_many_sources` | scenes | more than 4 distinct variants | use fewer source variants |
| `scene_not_in_source` | scenes | a `scene_ids` entry is not a scene of `from` | pick ids from that variant |
| `duplicate_scene` | scenes | the same scene id is taken from two segments | take each scene from one source |
| `too_many_scenes` | scenes | more than 64 scenes | select fewer |
| `scene_incompatible` | scenes | a chosen scene fails its prefab check (version gone, values refused) | take it from a variant whose prefab is available |
| `source_has_no_score` | narrative or motion | a **named** source has no score (an inherited one is simply absent) | pick a variant with a score |
| `source_has_no_art_direction` | art_direction | a **named** source has none | pick one that has |
| `source_document_missing` | motion, art_direction | the source cites a file that is gone | repair that variant first |
| `score_scene_missing` | motion | the score cites scenes the composed scenes do not contain (`details.scene_ids`, `item_ids`) | take those scenes from the same variant, or take the score from another |
| `score_incompatible` | motion | a score control, anchor or value does not resolve in the composed scenes | take the scenes from the score's owner |
| `narrative_unmapped_items` | narrative | items of the motion source without an equivalent (`details.item_ids`) and `on_unmapped: refuse` | same variant for both, or `keep_motion` |
| `narrative_item_incompatible` | narrative | the borrowed text breaks the speech rule of the item (silence, locked-sequence host...) | same variant for both |
| `score_invalid` | motion | the composed score fails its own validation | same variant for both |

`details` lists are bounded: `{items: [<= 12], total}`.

**Provenance (persisted).** The result's score and art direction are new documents (new ids, revision 1, item and cue ids kept); the provenance is a further file `compositions/<variant_id>.json` (`schema` `jarvis.presentation_studio.composition`, version 1; not a migrated schema: written once with the variant, never rewritten, kept on archive like the linked documents), written **after** the linked documents and **before** the variant file and the manifest (the manifest stays the last write):

```json
{"schema": "jarvis.presentation_studio.composition", "schema_version": 1, "presentation_id": "pst_...", "variant_id": "psv_... (the child)",
 "base_variant_id": "psv_...", "created_at": "...Z", "created_by": "user",
 "dimensions": [
   {"dimension": "scenes", "inherited": false, "sources": [{"variant_id": "psv_...", "variant_number": 2, "source_revision": 3, "document_id": null, "scene_ids": ["pss_..."]}], "detail": {"applied": true, "scene_count": 2, "segments": 1}},
   {"dimension": "narrative", "inherited": false, "sources": [{"variant_id": "psv_...", "variant_number": 3, "source_revision": 1, "document_id": "psr_..."}], "detail": {"applied": true, "fields": ["label", "text", "note"], "matched": {"item_id": 3, "scene_ordinal": 0}, "kept_from_motion": [], "kept_from_motion_total": 0, "dropped_source_items": 0}},
   {"dimension": "motion", "inherited": true, "sources": [{"variant_id": "psv_...", "variant_number": 1, "source_revision": 4, "document_id": "psr_..."}], "detail": {"applied": true, "fields": ["items", "actions", "timing", "cues", "sequences", "recovery_points"]}},
   {"dimension": "art_direction", "inherited": false, "sources": [{"variant_id": "psv_...", "variant_number": 2, "source_revision": 3, "document_id": "psd_..."}], "detail": {"applied": true}}],
 "warnings": []}
```

Always the four dimensions, in that order, each with its source variant, the **revision read** and the borrowed document. The graph node also carries `sources` (base first) and a `rationale` that starts with a summary line (`composed on #1; narrative #3; art_direction #2.`). The read route answers 404 `presentation_studio_unknown_composition` when the variant is not a composition result; a damaged file is 409 `presentation_studio_corrupt_document`.

### Guarantees

- **Sources are inputs.** A composition reads variants, scores and art directions and writes none of them: a test hashes every file of the Presentation before and after and only new files and the manifest differ. The child is a normal node: parent edge to the base, `sources` edges to the others, a fresh number.
- **One write door.** The child is written by `create_branch(compose=...)` of Slice 16: same lock, same number allocation before the first write, same `persist_variant_locked` (so the Slice 06 pin registry sees the child's pins, held pins of scene-local variants included, before the file exists), same event (`system.presentation_studio.variant_changed`, op `created`, no content), same crash behavior: the manifest is last, an interrupted composition never becomes a node, its files are reported by the reconciliation and the spent number is not reused. Hard stops at five steps are tested.
- **Nothing is merged.** There is no three-way merge and no text merge; a dimension comes from one source or the request is refused.
- **Revision CAS.** `source_revisions`, `expected_revision`, and the revision checks of the scene copy.
- **Untrusted text stays text.** Titles, rationale, narration and notes are never interpreted; the diagnostics (`core.presentation_studio.{composition_planned,composition_created,composition_refused,compare_select,compare_pair,compare_mode,compare_navigate,compare_link,compare_clear}`) carry ids, counts and flags only.

### Control Center relay and loopback

`GET /api/presentation-studio/presentations/{id}/compare`, `POST .../compare/{select,pair,mode,navigate,links,links/remove,clear}`, `POST .../compositions`, `POST .../compositions/plan` and `GET .../variants/{vid}/composition` relay to the Core routes above, with the status and body of Core returned as is (so `error.conflicts` reaches the page). The relay holds no state; for `compositions` and `compositions/plan` it **forces `actor` to `user`**; the compare bodies have no actor. Same origin guard as the rest of `/api/presentation-studio` (a foreign origin or a frame is 403).

### Agent-facing shape (what Slice 21 wraps)

The MCP server `jarvis-presentation` (Slice 21) exposes this contract as tools; they add nothing to the rules above. Proposed surface, one-to-one with the routes, ids chosen from the choice providers (never typed from memory):

| Tool | Arguments | Calls |
| --- | --- | --- |
| `presentation_compare` | `op`: `open` `{variant_ids, pair?, mode?}` / `focus` `{pair}` / `mode` `{mode}` / `navigate` `{variant_id, scene_id or step}` / `link` `{a, b}` / `unlink` `{a, b}` / `close`; `presentation_id?` (default: the current one) | `compare/select`, `pair`, `mode`, `navigate`, `links`, `links/remove`, `clear`; the answer is the view |
| `presentation_compose` | `op`: `plan` / `create`; the request body above (`base`, `scenes`, `narrative`, `motion`, `art_direction`, `title`, `rationale?`, `on_unmapped?`, `activate?`) | `compositions/plan`, `compositions` |
| `presentation_composition` | `variant_id` | `variants/{id}/composition` (read-only: where did this variant come from) |

Rules for the tool layer: it sets `actor: "brain"` itself, never from the model's arguments (Slice 14 entry condition); it passes `source_revisions` from the revisions of the **last view or graph it read**, so a stale picture is a `stale_revision` and not a silent overwrite; `create` is only offered after a `plan` that answered `ok: true` in the same turn, and it returns the conflicts verbatim (code, dimension, message, fix) so the model can tell the user what to change; a composition needs no confirmation token (it creates a new node and destroys nothing; the way back is the Slice 16 archive, which has its own plan and token); `activate` stays `false` unless the user asked for the child to become the presented one; and the tool states the child's number and title and the summary line, never the contents of the narration. `presentation_compare` changes interface state only and may be used while a run is live (it neither starts nor stops the playback).

### Limits and what is not done here

| Item | Value or status |
| --- | --- |
| compared variants | exactly 2 or 4 |
| manual links per set | 64 |
| tracked comparison sets | 16 Presentations (memory) |
| scene segments per composition | 4; scenes in the result: 64 |
| distinct source variants | 4 (`MAX_SOURCES`) |
| user rationale | 400 characters (the node's rationale keeps its 600 / 800 bytes bound) |
| the side-by-side preview panes, 2-up / 4-up responsive layout | done in the explorer (Slice 19 UI); scene thumbnails are not offered (a text scene list) |
| comparison state across a Core restart | not kept (by design) |
| field-level narrative borrowing, borrowing only some score items or cues, merging two art directions | not offered: a dimension has one source |
| item matching by text similarity | not done: `item_id`, then scene and rank |
| orphan `compositions/*.json` after a hard stop | harmless; not listed by the reconciliation report yet (variant and linked-document orphans are) |

## Agent and voice operations (Level 3, Slice 21)

Status: implemented by Slice 21. Owners: `jarvis/runtime/presentation_studio_mcp.py` (the FastMCP server `jarvis-presentation`, 12 tools), `presentation_studio_mcp_tools.py` (the logic, `PresentationTools`), `presentation_studio_mcp_support.py` (targets, errors, confirmation ledger), `presentation_studio_turn.py` (turn attestation in the Control Center), `jarvis/runtime/mcp_tool_meta.py` (`PRESENTATION`), the brain prompt `BRAIN_PRESENTATION_PROMPT` plus the Slice 11 planner prompt in the `*_display_studio_*` programs. Conformance: `tests/unit/test_presentation_studio_mcp{,_ops,_policy,_trace}.py`, `test_tool_brain_studio_ownership.py`, `test_mcp_catalog.py`, `test_brain_capability_parity.py`. Evidence: `tasks/jarvis-interactive-presentation-studio/slices/21-agent-voice-operations/evidence/`.

There is **no natural-language router and no second UI scheduler**: the brain (Claude) understands the sentence, and calls one of twelve semantic tools with ids it read from the state. A tool is a facade: it calls the Core route (typed `LocalCoreClient`) or the Control Center command channel that already owns the operation, so voice and interface reach the same canonical state through the same validation. The server is the **only `brain` door**: it sets `actor: "brain"` itself (no tool has an `actor` or `origin` argument; a catalogue test fails if one appears), where the Control Center relay forces `user`.

### The twelve tools

| Tool | `op` / `target` | Calls | Class |
| --- | --- | --- | --- |
| `presentation_inspect` | `overview`, `presentation` (variant graph with numbers), `variant` (scenes), `scene` (controls, bounds, current values, scene-local variants), `score` (items **without** `text` / `note`), `history`, `playback`, `compare`, `composition`, `templates`, `template`, `explorer` (dated mirror + full-screen state), `choices` (every valid id), `draft_guide` (exact brief and draft keys and a valid example to adapt; `kind: exploratory` adds six computed, divergent art-direction profiles; no Core call) | the Core reads, the Control Center mirrors | read |
| `presentation_view` | `explorer_open` (`variant_id?`, `fullscreen?`), `explorer_close`, `stage_fullscreen_enter`, `fullscreen_exit` | `POST /api/presentation-studio/explorer/commands`, `POST /api/fullscreen/commands` | write |
| `presentation_play` | `start` (`role`, `jarvis_speaks?`), `stop`, `pause`, `resume`, `next`, `previous`, `goto` (one of `item_id`, `scene_id`, `position`), `reveal`, `hide`, `return` | `POST .../playback/{verb}` | write |
| `presentation_edit` | `ops` (1..16; `control.set`, `control.reset`, `scene.remove`, `scene.reorder`, `scene.rename`, `scene.source_request`, `scene_variant.create`, `scene_variant.rename`, `scene_variant.select`, `scene_variant.delete`), `revision?`, `mode` `preview` or `commit`, `confirmation?` | `POST .../variants/{id}/edits` | write |
| `presentation_undo` | `direction` `undo` or `redo`, `confirmation?` | `GET .../history`, then `POST .../undo` with `expected_entry_id` | write |
| `presentation_variant` | `create`, `activate`, `rename`, `archive_plan`, `archive`, `restore`, `art_direction_fallback`, `scene_preview`, `scene_cancel_preview`, `scene_promote` | the Slice 16 / 17 / 09 routes | destructive class (archive) |
| `presentation_compare` | `open` (2 or 4 ids), `focus`, `mode`, `navigate`, `link`, `unlink`, `close` | `compare/*` | write (interface state) |
| `presentation_compose` | `plan`, `create` (`request`: `base`, `scenes`, `narrative`, `motion`, `art_direction`, `title`, ...) | `compositions/plan`, `compositions` | write |
| `presentation_template` | `plan`, `promote`, `instantiate` | the Slice 20 routes | write |
| `presentation_draft_check`, `presentation_draft_assemble`, `presentation_draft_finalize` | `brief`, `draft` | `authoring/{check,assemble,finalize}` | read / write |

Not exposed on purpose: `scene.add`, `scene.set_controls` and the `*.restore_*` forms (they take a whole scene body or are the shape of an undo; use a template or a branch), score writing (`POST/PUT .../score`: the planner assembles it), prefab detours, `skip_sequence` (user only on the wire), the page-side compare API (the compare state is Core's). Deleting a Presentation does not exist.

### Rules the tool layer holds (each has a test)

1. **Ids come from the state, never from the model.** `id` arguments are checked before anything is sent (grammar, then existence). An unknown id is refused with the valid ids (`presentation_studio_unknown_*`, `choices`). A default (no `presentation_id` / `variant_id`) is read: the running presentation, else the one the open explorer shows, else the only presentation; the variant is the active one. Several presentations and none named: `presentation_id_required`. Model-visible `title` / `label` fields are one clipped line each and listed under `untrusted`; the score is read without its spoken text and notes.
2. **The start origin is attested by the real turn.** Core's start contract takes `origin` from the request and lets `brain` + `explicit_user_request` switch the user's interaction mode (Slice 14 entry condition). `presentation_play start` has no `origin` argument. The Control Center, which serves every brain turn (`agent_ask`), counts the addressed user turns in flight (`presentation_studio_turn.AddressedTurnTracker`; a turn Core opens itself, `source: system`, or a non-addressed turn does not count; a typed panel message does) and answers `GET /api/presentation-studio/agent/turn` `{addressed_user_turn}`. Only then does the server add `origin: explicit_user_request`. Otherwise Core applies `brain_spontaneous` and refuses (`mode_switch_refused`, French sentence: the user starts the run from the player, or asks for it aloud). **Limit:** the attestation says a user turn is running, not that the sentence asked to present; the prompt says to start only on an explicit request.
3. **Destructive gestures use the canonical confirmation.** Archiving a branch ("delete" = archive, restorable): `archive_plan` returns the exact set (numbers, titles clipped, `includes_active`) and Core's token (HMAC bound to the set, titles and revision, 10 minutes); the tool answers `confirmation_required` with the question to read; `archive` needs the token of a plan **made by this process**, `confirmed: true` (the user's yes) and Core re-checks the token (`presentation_studio_confirmation_stale` when the set grew). Removing a scene: the first `presentation_edit` with `scene.remove` writes nothing and returns a token bound to variant, revision and scene ids; the same request with it commits. Undoing the **user's** last modification (entry `actor` is not `brain`): same two steps, the token bound to the entry. Every undo sends `expected_entry_id` read from the history (Slice 08 condition), so a blind "undo" never undoes someone else's later edit. A preview of a removal needs no token.
4. **Visual gestures are silent by default.** Every result carries `speech`: `silent` for a successful visual gesture (open / close the explorer, compare, navigate, edit, start / stop / navigate playback, activate, rename, undo) and `say` plus a one-sentence `say` only for: a new fact (variant number created), a confirmation question, a click the user must make (`needs_gesture`), a refusal (tool error), an archive done. This is exactly the PRESENTATION matrix (`COMMAND_CONFIRMATION` and `VISUAL_COMMAND` forbid voice; `ERROR` and `QUESTION` are the safety exceptions); the runtime speech gate stays the enforcement, the tool result and the prompt only stop the model from asking for speech. The classifier gained `compare`, `mélange`, `mixe` as visual verbs. Not classified (no unambiguous verb): "fais une variante", "rends X plus froid"; their confirmation is a short `say` or silence by the prompt.
5. **Full screen is never claimed.** `explorer_open` rests on the receipt's `mode` (`windowed`, `fullscreen_armed` or `fullscreen`, observed by the page); `fullscreen_armed` and a `needs_gesture` answer say the user must click. `stage_fullscreen_enter` needs a running playback (the stage object id comes from the playback state).
6. **Art direction.** A serious start without one is refused by Core (`presentation_studio_art_direction_required`); the tool's sentence names the fix, `presentation_variant art_direction_fallback` (revision read, not typed).
7. **Composition.** `create` is offered only after a `plan` of the same request answered; `source_revisions` default to the graph read at the same moment (a state that moved is `stale_revision`); conflicts (`code`, `dimension`, `message`, `fix`) are returned verbatim; `activate` stays false unless asked. The explorer's comparison state is never driven through the page, only through Core (an open explorer shows it at its next read).
8. **Correlation.** Every call writes one `presentation_studio.tool` line (tool, op, resolved ids, `correlation_id`, `revision`, `speech`, duration, and the canonical event Core posts: `system.presentation_studio.edit_committed`, `system.presentation_studio.variant_changed` or `system.presentation_studio.playback_changed`); a refusal writes `presentation_studio.tool_failed` with its code. No title, value, rationale or spoken line ever reaches the journal (tested with sentinels). The result's `revision` and ids match the event's attributes (tested against the real emitter; the event's `source` is `brain`).

### Examples (utterance, calls, what is said)

| Utterance | Calls | Said |
| --- | --- | --- |
| "montre toutes les variantes" | `presentation_view explorer_open` | nothing (a click prompt if the page armed full screen) |
| "ouvre la 37" | `presentation_inspect presentation` (number to id), `presentation_view explorer_open variant_id` | nothing |
| "fais une variante" | `presentation_variant create title rationale` | "La variante 2 est créée." |
| "compare ces quatre" | `presentation_inspect presentation`, `presentation_compare open variant_ids` | nothing |
| "mélange la structure de A avec le ton de B" | `presentation_compose plan`, then `create` | the new variant number; conflicts with their `fix` |
| "rends le titre plus court" | `presentation_inspect variant`, `scene`, `presentation_edit` (`revision`, `if_current`) | nothing |
| "supprime la branche 3" | `presentation_inspect presentation`, `presentation_variant archive_plan` | the question; after "oui": `archive` then "archivée, elle se restaure" |
| "répète depuis la scène produit" | `presentation_inspect variant`, `presentation_play start rehearsal`, `goto scene_id` | nothing |
| "annule" | `presentation_undo` (asks if the last edit is the user's) | nothing |
| "fais-moi une présentation sur..." | the Slice 11 planner prompt, `presentation_draft_assemble` (one transaction) | what was created |

### Declaration, prompt, budgets

`jarvis-presentation` is declared with the display (`condition: scene.enabled`, Claude conversation profile only; the Control Center gives the agent its `presentation_mcp` target next to `display_mcp`). The conversation prompt programs gain a `studio` variant (`backend.claude.conversation.display_studio_session`, ..., 4 programs): `BRAIN_PRESENTATION_PROMPT` then the registered `presentation_studio.authoring.planner`, which was attached to no program until now. Model-visible tool context: 16 849 bytes for the 12 tools (budget 17 100 in `test_mcp_catalog`); the whole-surface budget rose from 84 000 to 101 075 for this server (the 12 tools are the only addition; each is one closed `op` per domain). The prompt programs with studio carry about 9 600 characters more than `display_session`. `ui_intent_publish` is not documented in the brain prompt (a baseline red of `test_brain_capability_parity`, not ours).

### Tool Brain

With `JARVIS_TOOL_BRAIN=active` the Tool Brain executes scene tools by adapters. `run_scene_plan` (its only scene write path) now refuses any command that targets an object of category `studio_stage` / `studio_aux` (the playback stage window and its auxiliary windows), or imposes such a category, with `studio_owned`; tested adapter by adapter and through filter selections. The presentation tools are not Tool Brain operations (no `ui_surface`), so the Tool Brain never plays or edits a presentation.

### Real-model traces (Slice 11 / 21 gate)

Run by `python -m tests.replay.presentation_studio_mcp_real_trace` (real `claude` CLI, `sonnet`, the real `conversation_display_studio_session` prompt, the real MCP servers as children of the CLI, an isolated in-process Core on a random port with a scratch data root; the Control Center is a stand-in for the explorer, full-screen and attestation routes). Redacted result and findings: `evidence/real-model-traces.md`, `evidence/trace-analysis.md`. The scripted rig (`scripted-tool-traces.*`) is not a model trace.

### Limits and left to do

- Real-model traces cover five scenarios (make a variant, compare four, delete a branch with confirmation, hostile title, semantic edit). **Slice 22 ran the authoring scenarios** (rich brief, missing context, vague exploratory, one-shot report, plain display, hostile text, refused draft then fix; questions counted against the budget) and fixed what they found, see the [release report](presentation-studio-release.md#real-model-release-gate-slice-11-carry-forward). **Still not covered by a real model:** linked art direction and conflicting brands, a 12-scene deck, composition, templates, rehearsal with a speaking Jarvis, full screen on a real page, and any run with the live voice stack. A resumed `claude -p` starts a new MCP process, so the delete scenario re-planned once (safe, the user's yes covered the same set); the production brain keeps one MCP process per launch.
- The start attestation is a per-turn fact (above). A turn-level binding of the sentence itself needs a turn-authority port in the Control Center; not built.
- Score editing, `scene.add`, prefab detours and score `text` reading by the agent are not offered.
- Voice-undo confirmation and destructive confirmations are enforced by token binding and the prompt; a model that says "oui" for the user cannot be told from the user by the tools (same trust level as `confirm` of `scene_update_many`).
- Physical checks (a spoken session in PRESENTATION mode, full screen on a projector) are Human checks.

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
- Navigation keys (next, previous, first, last) arrive through `onNavigate` while fullscreen; the frame relays none. **Opt-in**: `keys: "host"` (default `none`, which never steals focus from a prefab text field); Slice 12 passes `host` for playback (`control_center_presentation_studio_player.js`).
- Slice 22 (hardening) re-checks fullscreen restore; the physical checks (Escape key, multi-monitor, permission
  prompt) stay Human checks.

## Binding facts established by the Slice 01 audit (details and evidence in the handoff's `07-integration-map.md`)

- There is no desktop host. Fullscreen is the browser Fullscreen API on a **host element**; a prefab frame cannot fullscreen itself (permissions policy) and a voice request alone cannot start it (user activation).
- The prefab library caps versions per id (64 live) and ids (512) and has no deletion. **Decided by Slice 01a** ([prefabs.md](prefabs.md#retention-of-studio-scene-sources)): a Tier-3 source edit goes through `PrefabDraftCoalescer` (one burst, one version); only ids `presentation-studio.*` are retained, and Core may *archive* (move, never delete) the versions of such an id that nothing pins. "Pins" are asked of a `PrefabPinRegistry` that **the Studio implements** (variants, scene-local variants, templates, scene objects, scene documents, undo stack) and passes to `PrefabService`; with no registry nothing is archived and the hard caps apply. Studio code must therefore (1) name its scene sources `presentation-studio.<...>`, (2) let variants share the scene's id and differ by `(id, version)` pin, forking a new id only when sources diverge, (3) register every pin it writes in the registry before the pinned version can age out of the last 16, (4) turn the typed refusals `version_limit` / `id_limit` into a visible message offering a fork under a new id. Slice 06 wired the registry (`StudioPinRegistry`, see *Hot reload contract* › *Pins and retention*).
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
| Scene hot reload (mechanism, result states, rollback, state preservation and reset cases, source revision, crash consistency, pin registry, host swap) | 0-1 | 3 (**done**, Slice 06) |
| Persistence and undo (durable commit, restart recovery, bounded ring, typed history results, pins) | 1-2 | 3 (**done**, Slice 08) |
| Variant graph (nodes, numbers, branch, switch, archive / restore under a token, crash reconciliation, linked documents, pins) | 0-1 | 3 (**done**, Slice 16) |
| Playback runtime (state machine, stage window, auxiliary windows, "where are we", armed-cue delivery, page band and keys) | 0-1 | 3 (**done**, Slice 12) |
| Edit inspector UI (generated widgets, preview / commit granularity, typed answers, undo / redo, hidden in playback, art direction chip) | 0-1 | 3 (**done**, Slice 07) |
| Authoring planner (brief, draft, workflows, question budget, quality gate, atomic assembly, planner prompt) | 0-1 | 3 (**done**, Slice 11; real-model trace: Slices 21, 22) |
| Scene-local variants (set per scene, selection as a permutation, preview, promote, bounds, pins) | 0-1 | 3 (**done**, Slice 17) |
| Variant explorer UI (tree, preview, actions, command channel, fullscreen, keyboard, a11y) | 0-1 | 3 (**done**, Slice 18; the physical fullscreen checks are Human checks) |
| Variant comparison and semantic composition (compare set, logical scene mapping, composition request, typed conflicts, per-dimension provenance) | 0-1 | 3 (**done**, Slice 19 backend and explorer panes UI; physical checks are Human checks) |
| Cue matching, template and prefab promotion, agent and voice operations | 0-1 | 3 (**done**, Slices 13, 20, 21) |
| Rehearsal (section loop, restart-a-section, dedicated runbook) | 0-1 | 3 (**not delivered as a Slice**: the `rehearsal` role, `goto`, `previous` and "where are we" exist through Slices 12, 01c and 21; the section loop and the runbook do not, see [presentation-studio-release.md](presentation-studio-release.md)) |

There is no `docs/CONTEXT.md` or documentation-level registry in this repository: the level of a concept is stated in its page header (`Status: Level N`), as in [presentation-mode.md](presentation-mode.md).
