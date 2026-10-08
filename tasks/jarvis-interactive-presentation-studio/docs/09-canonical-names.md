# 09 - Canonical Names (proposed by Slice 01, binding for later Slices once the PM accepts them)

Every name follows a precedent cited in the right column. A later Slice that needs a different name amends this page in the same commit; it never invents a parallel one.
Rule from R1: new code uses the prefix `presentation_studio`; the words *artifact* and `Artifact*` are never used for the aggregate (a "Presentation" is not a capture artifact).

## 1. Domain vocabulary (English identifiers, French user labels where the UI needs them)

| Concept | Name | Notes |
| --- | --- | --- |
| Aggregate | `Presentation` | has `Variant`s, `StudioScene`s, one `Score` per variant, one `ArtDirection` per variant |
| Variant | `PresentationVariant` | whole-presentation branch (D15/D16/D18) |
| Logical scene | `StudioScene` | **not** a Scene-service object and not a `window`; carries a `PrefabRef` pin. Avoids the clash with the global scene (`jarvis/domain/scene.py`) |
| Scene-local variant | `SceneVariant` | lives inside a `PresentationVariant` (D16) |
| Art direction | `ArtDirection` | profile with `provenance` provided/inferred/generated (D06) |
| Score | `Score`, `ScoreItem`, `Track`, `CueDefinition` (+ `CuePredicate`, `ActionRef`, `LockedSequence`, `RecoveryPoint`; the plan name `Cue` is `CueDefinition` in code) | tracks: `user_speech`, `jarvis_speech`, `visual`, `motion`, `cues`; `Silence` is an explicit item kind (D07) |
| Playback | `PlaybackState`, `PlaybackRole` | roles `user_presenter`, `jarvis_presenter`, `rehearsal` (D10); states `idle`, `running`, `paused`, `detour`, `locked_sequence`, `stopped` |
| Control | `StudioControl` | curated edit control bound to a manifest `inputs` path (`props.<key>` / `data.<key>`); metadata is studio-owned because `parse_manifest` rejects unknown manifest keys (`jarvis/domain/prefab.py:642-660`) |
| Edit | `EditOp`, `EditTier` | tiers `control` (1), `structure` (2), `source` (3) (D11); preview vs commit |
| Actor | `StudioActor` = `user` / `brain` | forced `user` by the Control Center relay, `brain` by MCP (precedent `prefab_relay.py`); not `SceneActor` |
| Resource | `ResourceReference` (reused, `jarvis/domain/presentation_working_set.py:653`) | plus `PrefabRef` (`jarvis/domain/prefab.py:237`) and `jart_` ids |
| Cue satisfaction | `CueSatisfied(cue_id, armed_set_id, at)` | typed value; carries **no text** (R5) |
| Fullscreen (generic) | `SurfaceFullscreenRequest`, `SurfaceFullscreenState` | states `entered`, `exited`, `needs_gesture`, `unsupported`, `refused`, `expired`; **not** presentation-prefixed because D02 makes it a generic surface capability |

## 2. Ids (shape: `<prefix>_<lowercase hex>`, like `jart_<uuid4().hex>` in `jarvis/domain/artifacts.py:186`, `cred_`; **not** `pres-`, which is already the Voice PRESENTATION *session* id, `presentation_runtime.py:135`)

| Id | Format | Scope / rule |
| --- | --- | --- |
| `presentation_id` | `pst_` + `uuid4().hex` (32) | immutable |
| `variant_id` | `psv_` + `uuid4().hex` (32) | immutable machine id (D18) |
| `variant_number` | positive integer, monotonic per presentation, **never reused** after archive | the short display id ("#29", D18); stored in the manifest counter, voice resolves it through the choice provider, never by guessing |
| `scene_id` (logical) | `pss_` + 12 hex | stable across variants when the scene is "the same" (enables compare/sync, D19) |
| `scene_variant_id` | `psl_` + 12 hex | scoped to a `(variant_id, scene_id)` |
| `item_id` (was `score_item_id`; Slice 10 implemented `ScoreItem.item_id`), `cue_id` | `psi_` / `psc_` + 12 hex | unique inside a score; the **only** thing an ambient match may name is a `cue_id` |
| `action_id` (bound visual/motion action) | slug `[a-z][a-z0-9_]{0,39}` | authored, closed per scene (declared by the scene's controls/sequences), never free text |
| `art_direction_id` | `psd_` + 12 hex | |
| Prefab id of a studio scene | `presentation-studio.p<12hex>.s<12hex>` | satisfies `PREFAB_ID` (`jarvis/domain/_checks.py:37`: 2-4 segments, each `[a-z][a-z0-9_-]{0,31}`, <= 96); custom class (not `jarvis.`); one id per `(presentation, scene)` and **shared by all variants** as different `(id, version)` pins (see proposed Slice 01a) |
| Studio window object id | assigned by Core (`create_object` returns it), held by the studio service only | one stable stage window per presentation (07 section 4.5) |

Limits to pin in tests: title <= 80 chars (prefab `MAX_TITLE_CHARS`, `prefab.py:53`), single printable line; rationale <= 600 (`MAX_DESCRIPTION_CHARS`); every collection bounded (precedent: all of `scene.py`).

## 3. Modules (layering follows the repo: domain pure, ports, adapters, core services, protocol routes, runtime edges)

| Area | Path | Slice | Precedent |
| --- | --- | --- | --- |
| Artifact, ids, errors, actors | `jarvis/domain/presentation_studio.py` | 02 | `jarvis/domain/prefab.py` |
| Scene + controls | `jarvis/domain/presentation_studio_scene.py` | 04 | |
| Edit ops, tiers, results | `jarvis/domain/presentation_studio_edit.py` | 05 | `jarvis/domain/scene_batch.py` |
| Art direction | `jarvis/domain/presentation_studio_art_direction.py` | 09 | |
| Score, cues | `jarvis/domain/presentation_studio_score.py` | 10 | |
| Playback state machine (pure) | `jarvis/domain/presentation_studio_playback.py` | 12 | `jarvis/domain/presentation_working_set.py` |
| Cue arming/matching (pure) | `jarvis/domain/presentation_studio_cues.py` | 13 | `ambient_observation.py` |
| Variants graph, scene variants | `jarvis/domain/presentation_studio_variants.py` | 16, 17 | |
| Compose/provenance | `jarvis/domain/presentation_studio_compose.py` | 19 | |
| Template/promotion | `jarvis/domain/presentation_studio_template.py` | 20 | |
| Store port | `jarvis/ports/presentation_studio.py` (`PresentationStudioStore`) | 02 | `jarvis/ports/prefabs.py` |
| File store adapter | `jarvis/adapters/file_presentation_studio_store.py` (tree `<data_root>/presentations/`) | 02 | `file_prefab_library.py` |
| Core facade | `jarvis/core/presentation_studio_service.py` | 02 | `prefab_service.py` |
| Edit service | `jarvis/core/presentation_studio_edit.py` | 05 | `prefab_events.py` (`apply_if`) |
| Hot reload | `jarvis/core/presentation_studio_reload.py` | 06 | |
| Autosave + undo ring | `jarvis/core/presentation_studio_autosave.py` | 08 | |
| Playback service (in-memory state in Core) | `jarvis/core/presentation_studio_playback.py` | 12 | `core/presentation_working_set.py` |
| Cue follower (Voice process, consumes `AmbientIngestionLane.on_utterance`) | `jarvis/runtime/presentation_studio_cue_follower.py` | 13 | `presentation_runtime.py` |
| Presenter driver (score -> `announce_notice`) | `jarvis/core/presentation_studio_presenter.py` | 14 | `core/brain_service.py:889` |
| Variants/promotion services | `jarvis/core/presentation_studio_variants.py`, `..._promotion.py` | 16, 20 | |
| Core routes | `jarvis/protocol/presentation_studio_routes.py`, prefix `/v1/presentation-studio` | 02+ | `protocol/prefab_routes.py` |
| CC relay | `jarvis/runtime/presentation_studio_relay.py`, prefix `/api/presentation-studio`, added to `READ_GUARDED_ROUTES` | 05+ | `runtime/prefab_relay.py` |
| Generic fullscreen domain | `jarvis/domain/surface_fullscreen.py`; page module `jarvis/runtime/control_center_fullscreen.js` (`window.JarvisFullscreen`); route prefix `/api/fullscreen` (long-poll + receipt, like Bare Hands) | 03 | `domain/barehands_command.py` |
| Page modules | `control_center_presentation_studio.js` (shell/state), `..._stage.js` (playback + keys), `..._inspector.js` (07), `..._explorer.js` (18); markers `/*__CONTROL_CENTER_PRESENTATION_STUDIO_<PART>_JS__*/` | 03, 07, 12, 18 | `control_center_prefabs.js` |
| MCP server | `jarvis/runtime/presentation_studio_mcp.py`, server `jarvis-presentation`, category `presentation` ("Presentations") | 21 | `capture_mcp.py` |
| Tests | `tests/unit/test_presentation_studio_<area>.py`; fixtures `tests/fixtures/presentation_studio/`; integration `tests/integration/test_presentation_studio_*.py` | all | `tests/unit/test_presentation_*.py` |
| Docs | `docs/presentation-studio.md` (Level 2 owner map, this Slice) + one page per area when a section would exceed ~400 lines: `docs/presentation-studio-<area>.md` | all | `docs/presentation-*.md` |

## 4. Persistence tree (Slice 02 may change it, with a reason, before 08 and 16)

```
<data_root>/presentations/
  <presentation_id>/
    presentation.json            # schema jarvis.presentation_studio.presentation v1: id, title, active_variant_id, variant_counter, variant index, resource refs
    variants/<variant_id>.json   # schema ...variant v1: parent/provenance, art direction, scenes (PrefabRef pins, control values), score, scene variants
    archive/<variant_id>.json    # archived (deleted) variants, never rmtree'd
  .staging-<16 hex>/             # staged writes, swept at start (precedent file_prefab_library.py)
```

## 5. Core/protocol routes and events

| Kind | Name | Notes |
| --- | --- | --- |
| Core route prefix | `/v1/presentation-studio/...` | `presentations`, `presentations/{id}`, `.../variants`, `.../edits`, `.../playback`, `cues/satisfied`, `fullscreen` |
| CC relay prefix | `/api/presentation-studio/...` | forces actor `user`; read-guarded (`Origin: null` refused) |
| Generic fullscreen | `GET/POST /api/fullscreen/commands`, `POST /api/fullscreen/commands/{id}` (receipt) | sibling of `/api/barehands/commands` |
| Conversation events (actor SYSTEM, INSTANT, DIAGNOSTIC, content forbidden) | `system.presentation_studio.edit_committed`, `.variant_changed`, `.playback_changed`, `.cue_satisfied`, `.fullscreen_changed` | failures use the existing `system.failure` with a `code` attribute |
| New `ATTRIBUTE_KEYS` | `presentation_id`, `variant_id`, `scene_id`, `cue_id`, `op`, `tier`, `role` | existing and reusable: `kind`, `reason`, `code`, `revision`, `status`, `source` |
| Diagnostic kinds | Core `core.presentation_studio.<event>`; page console `studio.<event>`; Voice `presentation.studio.<event>` | precedents `core.prefab.saved`, `scene.prefab_mounted`, `presentation.display.withdraw_noop` |
| Error codes | `presentation_studio_<reason>` snake_case in a `PresentationStudioErrorCode` StrEnum | precedent `presentation_policy_*`, `PrefabStoreErrorCode` |

## 6. Agent tools (server `jarvis-presentation`; strict schemas; ids come from choice providers, never typed by the model)

Proposed set, ~16 consolidated tools to fit the server's own byte budget (07 C4); Slice 21 finalizes and measures:
`presentation_list`, `presentation_get`, `presentation_where`, `presentation_choices`, `presentation_create`, `presentation_open`, `presentation_present`
(action: start/pause/resume/stop/next/back/jump/focus/reveal, role), `presentation_detour`, `presentation_fullscreen` (enter/exit), `presentation_rehearse`, `presentation_edit`,
`presentation_edit_source`, `presentation_undo` (undo/redo), `presentation_variant` (list/create/switch/rename/archive with `confirm=true`), `presentation_compare` (compare/mix),
`presentation_scene_variant`, `presentation_promote`. `ToolMeta.ui_surface=None` (not Tool Brain UI actions); `side_effect` write/destructive per row; `idempotent`/`atomicity` declared.
New choice-provider ids (added in `CHOICE_PROVIDERS`, implemented in `tool_brain_choices.py`): `presentation.presentation`, `presentation.variant`, `presentation.scene`, `presentation.control`, `presentation.cue`, `presentation.scene_variant`.

## 7. Settings and flags
No new user setting is proposed. If Slice 13 needs an opt-out for cue following it goes through the existing generic settings tool (`settings_describe/get/set`), not a new surface.

## 8. Slice 02 amendments (implemented; stable parts now live in `docs/presentation-studio.md`, "Presentation contract")

| Topic | Amendment | Reason |
| --- | --- | --- |
| Decision (a)/(b) | (a) file store under `<data_root>/presentations/`; no `_MIGRATIONS`, no `tests/schema` snapshot | recorded with reasons in the repo page |
| `score_id` | new id `psr_` + 12 hex (the score is referenced from a variant before Slice 10 defines it); `art_direction_id` = `psd_` + 12 hex as in section 2 | the variant needs a typed ref for both |
| Route prefix | as sections 3/5 (`/v1/presentation-studio/presentations`); implemented: list/create/validate/get/put and `.../variants/{variant_id}` get/put. the `.../variants` collection (create), `.../edits`, `.../playback`, `cues/satisfied`, `fullscreen` stay for their Slices | one resource tree |
| Persistence tree (section 4) | unchanged: `presentation.json`, `variants/<variant_id>.json`, `.staging-<16 hex>/`; `archive/` is **not** created by Slice 02 (Slice 16 owns it). Added: `*.<8 hex>.tmp` leftovers beside a target, swept at start | unique temporary names so a leftover never blocks the next save |
| Documents | `schema` = `jarvis.presentation_studio.presentation` / `.variant`, `schema_version` 1; upgrade chain `UPGRADES[schema][n]` in `jarvis/domain/presentation_studio.py`; newer version refused, file untouched | forward-compatible refusal |
| Errors | `PresentationStudioErrorCode` in `jarvis/domain/presentation_studio.py` (not `ports`), all `presentation_studio_*`: invalid, runtime_state_refused, unsupported_schema_version, corrupt_document, unknown_presentation, unknown_variant, already_exists, stale_revision, limit_reached, storage_io | statuses in the repo page |
| Resources | stored as `{kind, locator, title}`; `ResourceKind.SCENE_OBJECT` and `scene:` locators refused; no `descriptor` | a scene object id is a runtime handle; references, never payloads |
| `StudioActor` | not introduced by Slice 02 (no consumer); **introduced by Slice 05**, see section 10 | no consumer yet |
| Diagnostics | `core.presentation_studio.{started,swept,created,saved,listed,validated,refused,failed,unreadable,sweep_failed,unexpected}` | section 5 pattern |

## 9. Slice 04 amendments (implemented; stable parts in `docs/presentation-studio.md`, "Scene and control contract")

| Topic | Amendment | Reason |
| --- | --- | --- |
| Modules | `jarvis/domain/presentation_studio_scene.py` (as section 3) plus `jarvis/domain/presentation_studio_checks.py` (error codes and input checks extracted from `presentation_studio.py`, re-exported there) and `jarvis/core/presentation_studio_scene_catalog.py` (`SceneCatalog`, the only caller of `PrefabService`) | `presentation_studio.py` must hold `StudioScene` in the variant and the scene module needs the same checks: a shared base avoids an import cycle |
| `SceneRef` | now an alias of `StudioScene` (same `scene_id`, `prefab` constructor); a scene adds `title, section, props, data, controls, anchors, preview` | one scene class, Slice 02 call sites unchanged |
| Variant schema | `schema_version` 2 (Presentation stays 1); `UPGRADES[variant][1]` fills the new fields; `CURRENT_VERSIONS` | stored shape grew; a v1-only JARVIS refuses v2 untouched |
| Control ids | `control_id` and `anchor_id` are slugs `[a-z][a-z0-9_]{0,39}` (the `action_id` grammar), authored and unique per scene; `ScoreAnchor` = `{anchor_id, label, control_id?}` is the closed action set Slice 10 binds cues to | 09 section 2 `action_id` |
| Route | `GET .../presentations/{id}/variants/{vid}/scenes/{scene_id}/controls` (client `presentation_studio_scene_controls`) | section 5 route tree |
| Error codes | `presentation_studio_unknown_scene` (404), `presentation_studio_scene_incompatible` (400), `presentation_studio_prefab_unavailable` (409) | distinct caller fault, manifest disagreement, catalogue fault |
| Diagnostics | `core.presentation_studio.{scenes_checked,scene_described}` | section 5 pattern |
| Choice provider | `presentation.control` (section 6) can be fed by `describe_scene(...)["controls"][*].control_id` | Slice 21 |

## 10. Slice 05 amendments (implemented; stable parts in `docs/presentation-studio.md`, "Semantic edit contract")

| Topic | Amendment | Reason |
| --- | --- | --- |
| Modules | `jarvis/domain/presentation_studio_edit.py` (pure: `StudioActor`, `EditTier`, `EditMode`, `EditStatus`, `OpName`, the op dataclasses, `EditRequest`, `EditResult`, `apply_ops`, `classify_op`, `undo_record`); `jarvis/core/presentation_studio_edit.py` (`PresentationStudioEditService`); **`jarvis/core/presentation_studio_events.py`** (`StudioEditEvents`, not in section 3); `jarvis/runtime/presentation_studio_relay.py` (`PresentationStudioRelayRoutes`, prefix `/api/presentation-studio/presentations`) | section 3 listed the first two and the relay; the events translator is a separate small module like `tool_brain_events.py` |
| `StudioActor` | `user` / `brain`, in the edit domain module (not `SceneActor`); `ALLOWED_EDIT_OPS` is the authority table; the Core route reads `actor` from the body (bearer-authenticated), the **relay replaces it with `user`**, the future MCP server stamps `brain` | C10, R10 |
| Operations | closed `OpName`: `control.set`, `control.reset`, `scene.add`, `scene.remove`, `scene.reorder`, `scene.rename`, `scene.set_controls`, `scene.source_request`, and **`scene.restore_values`** (not in the first list: the exact form of an undo; limited to declared control paths) | undo must be exact without a free-path write |
| Request / result | `POST /v1/presentation-studio/presentations/{id}/variants/{vid}/edits` body `{actor, mode: preview|commit, basis: {variant_revision}, ops}`; result `status` `applied` / `refused` / `stale`, plus `GET .../scenes/{scene_id}/control-suggestions`; typed client `presentation_studio_edit`, `presentation_studio_suggest_controls` | section 5 route tree |
| Error codes | `presentation_studio_unknown_control` (404), `presentation_studio_value_refused` (400) added to `PresentationStudioErrorCode` | a control id that does not exist vs a value the prefab or the curated bounds refuse |
| Relay surface | 5 GET (list, get, variant, controls, control-suggestions) and one POST (`.../edits`, actor forced to `user`); `/api/presentation-studio` in `READ_GUARDED_ROUTES`; `STUDIO_PREFIX` in `FORWARDABLE_PREFIXES` | no other write is relayed |
| Conversation event | `system.presentation_studio.edit_committed` (actor `system`, instant, diagnostic, content forbidden), producer `core.presentation_studio` (`PRODUCER_PRESENTATION_STUDIO`); status `applied` / `recorded_in_memory`; failures use `system.failure` with `code` | section 5 |
| `ATTRIBUTE_KEYS` | added `presentation_id`, `variant_id`, `scene_id`, `op`, `tier` (section 5 also listed `cue_id` and `role`: still to add in their Slices) | section 5 |
| Brain | `BrainOrchestrator.live_conversation_id()` (foreground conversation or `None`) | a Core producer needs the conversation of its event |
| Diagnostics | `core.presentation_studio.{edit_committed,edit_previewed,edit_refused,edit_stale,edit_source_recorded,source_requests_dropped,controls_suggested,event_failed}` | section 5 pattern |
| Source requests | `scene.source_request` is held in memory (`pending_source_requests()`, 64, not durable); durability is Slice 06 | no schema in this Slice |

## 11. Slice 01c additions (decision A; stable parts in `docs/presentation-studio.md`, "Playback roles and speech authority")

| Topic | Name | Note |
| --- | --- | --- |
| Module | `jarvis/domain/presentation_studio_roles.py` | pure; `StudioRole` (`user_presenter`, `jarvis_presenter`, `rehearsal`), `RoleRequirements`, `AmbientLanePolicy`, `SpeechPolicy`, `SwitchOrigin`, `ModePlan`, `ModeEventKind`, `RestoreAction`, `RestoreDecision`, `ScoreLineNotice` |
| Mode source | `presentation_studio_run` (`STUDIO_RUN_MODE_SOURCE`, in `TRANSIENT_MODE_SOURCES`) | sent to `InteractionModeService.request` for the switch and the restore; `BoardService.NON_PERSISTED_SOURCES` never stores it |
| Speech slot | `supersedes_key = presentation_studio:<run_id>` | one per run |
| Scripted line kind | `SpeechKind.PROGRESS` (`SCORE_LINE_KIND`) | transient, never retained |
| Diagnostic (to emit in Slices 12/14) | `presentation_studio.mode_restore_failed` | restore refused or raised |

## 12. Slice 08 amendments (implemented; stable parts in `docs/presentation-studio.md`, "Persistence and undo contract")

| Topic | Name | Note |
| --- | --- | --- |
| Modules | `jarvis/domain/presentation_studio_history.py` (pure: `UndoBook`, `HistoryEntry`, `HistoryResult`, `HistoryStatus`, `DropReason`, `scenes_digest`), `jarvis/core/presentation_studio_autosave.py` (`PresentationStudioHistory`, the `EditHistory` hook) | the file name `presentation_studio_autosave.py` of section 3 is kept; it hosts the durability contract and the ring, not a buffer (there is none) |
| Id | `psh_<12 hex>` | an undo entry |
| Statuses | `applied`, `history_unavailable`, `nothing_to_undo`, `nothing_to_redo`, `stale`, `refused` | typed results with HTTP 200 / 409 / 400-409 |
| Codes | `presentation_studio_history_unavailable`, `presentation_studio_history_empty`, `presentation_studio_history_stale` (all 409) | on the envelope of every non-`applied` result |
| Routes | `GET/POST .../variants/{variant_id}/{history,undo,redo}` (Core) and the same under `/api/presentation-studio/presentations` (relay, actor forced to `user`) | section 5 |
| Client | `LocalCoreClient.presentation_studio_{history,undo,redo}` | all outcomes returned, envelopes raise |
| Event | none new: `system.presentation_studio.edit_committed` with `status` `undone` / `redone` | no JS/Python registration needed |
| Diagnostics | `core.presentation_studio.{history_applied,history_not_applied,history_evicted,history_dropped,history_record_failed,history_score_unchecked,recovered,recovery_failed}` | section 5 pattern |
| Pins | `PresentationStudioHistory.pinned_versions(prefab_ids)` / `pins()` | `PrefabPinRegistry` shape (Slice 01a), registered via `EditHistory.begin` before the document write |
| Durability | no debounce, no `autosave` op class: a commit is durable at its acknowledgement; folder flush after the replace | section 6 recommendation kept ("temp + fsync + replace_with_retry"), plus the folder flush |

## 13. Slice 12 amendments (implemented; stable parts in `docs/presentation-studio.md`, "Playback runtime contract")

| Topic | Name | Note |
| --- | --- | --- |
| Modules | `jarvis/domain/presentation_studio_playback.py` (pure: `PlaybackPlan`, `PlaybackState`, `PlaybackEvent`, `EventKind`, `Phase`, `Effect`, `RefusalCode`, `apply`, `TABLE`, `progress_at`, `where_are_we`, `rebase`, `check_invariants`), `presentation_studio_playback_requests.py` (`Verb`, strict bodies), `presentation_studio_armed_set.py` (`ArmedSetMessage`, `CueReport`, `ReportLimiter`, `ReportLedger`); `jarvis/core/presentation_studio_playback.py` (`PresentationStudioPlaybackService`, `ArtDirectionGate`), `jarvis/core/presentation_studio_stage.py` (`SceneStage`, `StageLedger`), `jarvis/adapters/file_presentation_studio_stage_ledger.py`, `jarvis/protocol/presentation_studio_playback_routes.py`; page `control_center_presentation_studio_player.js` (marker `/*__CONTROL_CENTER_PRESENTATION_STUDIO_PLAYER_JS__*/`, not the `..._stage.js` of section 3) | section 3 listed the first and fourth only |
| Position | an index into `Score.playback_order()` (expanded loops), not an item id | a looped item has several positions |
| Routes | Core `GET /v1/presentation-studio/playback`, `GET .../playback/armed` (Voice only, not relayed), `POST .../playback/{verb}` (verbs: start stop pause resume next previous goto detour return reveal hide edit skip_sequence), `POST /v1/presentation-studio/cues/satisfied`; relay `/api/presentation-studio/playback[/{verb}]` forcing actor `user`; `PLAYBACK_PREFIX` added to `FORWARDABLE_PREFIXES` | section 5 listed `.../playback`, `cues/satisfied` |
| Results | `applied` 200, `refused` 409 (422 for `detour_invalid`), `stage_failed` 500 | like the edit result envelope |
| Error codes | `presentation_studio_playback_refused` (409), `presentation_studio_playback_stage_failed` (500); a refusal also carries `reason` = a `RefusalCode` | |
| Bus message | `presentation_studio.armed.changed` `{run_id, generation, count}` | content-free; the follower pulls the set |
| Event | `system.presentation_studio.playback_changed` (status words), new `ATTRIBUTE_KEYS` entry `role` (`cue_id` stays unused: no event names a cue) | section 5 |
| Ids | run id `[a-z0-9]{12}`; stage object `studio-stage-<run_id>[-<n>]`, auxiliary `studio-aux-<run_id>-a<n>`; categories `studio_stage`, `studio_aux` | never persisted in a document |
| Mode source | `presentation_studio_run` (Slice 01c) | unchanged |
| Edit service additions | `render_overlay(presentation_id, variant_id, basis_revision, ops, actor=)`, `add_commit_listener(listener)`; rework: `edit(..., origin=token)` and listeners `(presentation_id, variant_id, revision, origin)` | Slice 05 file, no change to its results; the token is never read from a body |
| Rework names | verb `skip_sequence` (user only, provisional, Slice 14 keeps it); `RefusalCode.detour_invalid`; `EventKind.SKIP_SEQUENCE`; `drop_failed_aux`; state field `follower` (`waiting`/`connected`/`absent`/`null`); `FOLLOWER_GRACE_S` 10, `MAX_VIEW_BYTES` 3072, `MAX_STAGE_REOPENS` 3, `KEEP_QUARANTINED` 3; `.corrupt-<ts>` ledger copy; diagnostics `stage_reopened`, `stage_ledger_quarantined`, `stage_ledger_scan_reclaimed`, `playback_detour_invalid`, `playback_follower_absent` | QA-1 rework |
| File | `<data_root>/state/presentation-studio-stage-ledger.json` | ids only; outside `presentations/` |
| Diagnostics | `core.presentation_studio.playback_*`, `stage_*`, `aux_*`, `armed_*`, `cue_report_*`, `mode_restore_failed` (replaces the bare `presentation_studio.mode_restore_failed` of section 11), `overlay_rendered`, `commit_listener_failed` | section 5 pattern |

## 14. Slice 09 amendments (implemented; stable parts in `docs/presentation-studio.md`, "Art direction contract" and "Art direction authoring policy")

| Topic | Amendment | Reason |
| --- | --- | --- |
| Id | the DA id stays `psd_<12 hex>` (`art_direction_id`, section 2 and the Slice 02 variant field `art_direction_id`); the brief's `pda_` was **not** introduced | the Slice 02 variant already validates `psd_` and fixtures carry it; two prefixes would orphan stored data |
| Names | the stored document is `ArtDirection` (`art_directions/<art_direction_id>.json`, schema `jarvis.presentation_studio.art_direction` v1) wrapping an `ArtDirectionProfile` | section 1 says `ArtDirection`; the brief says `ArtDirectionProfile`: the profile is the content, the document is the stored unit |
| Modules | `jarvis/domain/presentation_studio_art_direction.py` (model, validation, contrast, theme mapping, `require_art_direction`) **and** `jarvis/domain/presentation_studio_art_direction_authoring.py` (fallback, divergence, derivation from signals) and `jarvis/domain/presentation_studio_art_direction_vocab.py` (closed vocabularies, bounds, token parsers, WCAG maths; public names, re-exported by the first) | the section 3 list named one module; one responsibility per module and the file would otherwise pass 1 500 lines |
| Store | `PresentationStudioStore.read_art_direction` / `write_art_direction`; folder `art_directions/` swept for `*.tmp` | same mechanics as `scores/` |
| Core service | `get_art_direction`, `create_art_direction`, `save_art_direction`, `create_fallback_art_direction`, `art_direction_candidates`, `require_art_direction` | section 5 route tree |
| Routes | `GET/POST/PUT .../variants/{variant_id}/art-direction`, `POST .../art-direction/fallback`, `POST .../art-direction/candidates` (a computation, POST because it carries a body) | one resource per variant |
| Candidates | **computed, never stored**: `diverge` is deterministic; adopting a candidate is a normal create or save | no unlinked files, no delete path, no cap to manage |
| Error codes | `presentation_studio_unknown_art_direction` (404), `presentation_studio_art_direction_required` (409) | no DA yet / a serious variant needs one |
| Link ownership | `_persist_variant` refuses a change of `art_direction_id` unless `relink_art_direction=True`; **tightens Slice 02**, which accepted any well-formed id on `PUT .../variants/{id}` | same dead-end analysis as Slice 10 B1: a made-up id would lock the variant out of its own DA; a dangling id is repaired by the next create |
| Theme | `ArtDirectionProfile.to_theme()` (the five host theme keys) and `.to_theme_variables()` (`ALLOWED_THEME_VARIABLES`, all declared in `shell.css`) | no new channel, no new variable, no protocol change |
| Diagnostics | `core.presentation_studio.{art_direction_loaded,art_direction_relinked,art_direction_candidates,art_direction_resolved}` and `saved` with `part: "art_direction"` | section 5 pattern |

## 15. Slice 16 amendments (implemented; stable parts in `docs/presentation-studio.md`, "Variant graph and operations contract")

| Topic | Name | Note |
| --- | --- | --- |
| Modules | `jarvis/domain/presentation_studio_variants.py` (pure: `VariantIndexEntry`, `ArchivedEntry`, `validate_graph`, `plan_archive`, `plan_restore`, `reconcile_plan`, confirmation token, `with_*` transitions), `jarvis/core/presentation_studio_variants.py` (`PresentationStudioVariants`), `jarvis/core/presentation_studio_linked.py` (`LinkedDocuments`, `LinkedKind`, `ScoreLink`), `jarvis/core/presentation_studio_variant_events.py` (`StudioVariantEvents`), `jarvis/protocol/presentation_studio_variants_routes.py`, `jarvis/runtime/presentation_studio_variants_relay.py` | section 3 listed only the first two; routes and relay are siblings of the Slice 02/05 ones so the three Slices that edit the route / relay modules (06, 12, 16) do not collide |
| Variant id | `psv_<32 hex>` | the handoff's shorthand `pv_...` is this id; section 2 was right |
| New ids | `psb_<12 hex>` (archive batch), `psp_<12 hex>` (opaque preview handle, reserved for Slice 18), `psk_<expiry>.<64 hex>` (confirmation token) | |
| Manifest | `presentation.json` schema_version **2**: `variants[]` gain `rationale`, `created_by`, `sources`, `preview_id`; new `archived[]` (the same fields plus `parent_variant_id`, `archived_at`, `archived_by`, `batch_id`) | the **variant** document is unchanged (Slice 06 owns its v3); `UPGRADES[presentation][1]` |
| Tree | `presentations/<id>/archive/<variant_id>.json` | moved, never deleted; linked documents stay in `scores/` |
| Codes | `presentation_studio_active_variant_protected` (409), `..._confirmation_required` (400), `..._confirmation_stale` (409), `..._not_archived` (409), `..._linked_document_unsupported` (409), `..._variant_in_playback` (409) | |
| Routes | Core `GET .../presentations/{id}/graph`, `POST .../variants`, `POST .../variants/{vid}/{activate,rename,archive-plan,archive,restore}`; relay the same under `/api/presentation-studio/presentations`, actor forced to `user`, `archive` without `confirmation` refused by the relay | section 5 listed `.../variants` only |
| Client | `LocalCoreClient.presentation_studio_{graph,create_branch,activate,rename,archive_plan,archive,restore}` | |
| Event | `system.presentation_studio.variant_changed` with `op` = `created` / `switched` / `renamed` / `archived` / `restored` | one type (section 5), not five |
| `ATTRIBUTE_KEYS` | added `variant_number`, `count` | |
| Diagnostics | `core.presentation_studio.{variant_created,variant_switched,variant_renamed,variant_archived,variant_restored,archive_planned,reconciled,reconcile_orphans,reconcile_failed,branch_failed,archive_failed,restore_failed,graph_invalid,history_drop_failed}` | section 5 pattern |
| Linked documents | `ArtDirectionLink` registered by default beside `ScoreLink` (merge with Slice 09); documents stay in `scores/` and `art_directions/` on archive | |
| Playback | `PresentationStudioPlaybackService.running_variant()`, `PresentationStudioVariants.bind_playback` | a run stays bound to its variant; archive of the played one is refused |
| Hooks for later Slices | `PresentationStudioVariants(linked=LinkedDocuments(...))` (a future kind; `ArtDirectionLink` is already registered), `pin_index()` (Slice 06 registry), `drop_presentation` (Presentation deletion, not built) | |

## 16. Slice 14 amendments (implemented; stable parts in `docs/presentation-studio.md`, "Jarvis presenter and locked sequences")

| Topic | Name | Note |
| --- | --- | --- |
| Modules | `jarvis/core/presentation_studio_presenter.py` (`PresentationStudioPresenter`, `pump()`, `on_event()`, `view()`), pure `jarvis/domain/presentation_studio_sequence.py` (`SequenceSchedule`, `SequenceClock`, `begin/start/pause/resume/due/release/finish`, `InputKind`, `Verdict`, `input_verdict`, `interruption_plan`, `LogEntry`), pure `jarvis/domain/presentation_studio_line.py` (`SpeechLine`, `LinePhase`, `FactKind`, `SpeechFact`, `observe`, `FACT_OF_EVENT`) | section 3 listed the first only |
| Playback additions | state fields `epoch`, `resumes`, `resumed_at_ms`; `stage_scene_id`; `where.sequence.duration_ms`; service `plan`, `add_observer`, `set_presenter_view`, `halt(problem)`, `finish(reason)`, `resolve_problem(code)`; `notify` also accepts `next`, `pause`, `goto` | `locked_owner` of the brief is `PlaybackState.sequence` / `owner: "sequence"` (Slice 12), not a second flag |
| Speech | `announce_notice(text, **ScoreLineNotice.call_kwargs())` only; the speech id is learned from `brain.speech.requested` carrying `supersedes_key=presentation_studio:<run_id>` | `brain_service.py` is unchanged |
| Facts | `brain.speech.requested`, `mouth.speech.{started,completed,interrupted,superseded,expired,failed,unconfirmed}`, `mouth.floor.taken`, `user.transcript.accepted` | read through `ConversationEventEmitter.add_listener` |
| Constants | `START_TIMEOUT_S` 10, `LINE_TIMEOUT_S` 180, `GAP_MS` 300, `SILENCE_DEFAULT_MS` 1500 | |
| Problem / reason codes | `announce_refused`, `announce_failed`, `speech_not_started`, `speech_stalled`, `speech_failed`, `speech_obsolete`, `speech_unconfirmed`, `line_invalid`, `presenter_crashed`; `last_run.reason` `completed`, `presenter_crashed` | tokens, shown on the band |
| Event | `system.presentation_studio.presenter_changed` (`status`: `line_failed`, `interrupted`, `sequence_done`, `sequence_skipped`, `sequence_aborted`, `completed`; plus `code`, `count`) | section 5 pattern; Python + JS mirror |
| Diagnostics | `core.presentation_studio.presenter_*` and `playback_observer_failed` | ids, counts, codes; never text |
| Routes / client | none added: `POST .../playback/start` with `role: jarvis_presenter`, `skip_sequence` user-only (Slice 12 verbs) | the relay still forces `user` |
| Page | band additions in `control_center_presentation_studio_player.js`: speaking indicator, sequence progress (`role=progressbar`), `Continuer`, presenter problem texts | no new module |
| Wiring | `JarvisCoreApplication.presentation_studio_presenter` (built after the brain), `conversation_event_emitter.add_listener(presenter.on_event)`, closed before the playback service | |
| Repaired on the way | `control_center_timeline.js` had a stray duplicated `DOT_TYPES` line (a syntax error since the Slice 16 merge: 70 timeline tests failed at the branch head) | fixed in the same commit that registers the event |

## 17. Slice 13 amendments (implemented; stable parts in `docs/presentation-studio.md`, "Cue following contract", and `docs/presentation-addressed-turn.md` section 12, "Amendment (Slice 13, R5)")

| Topic | Name | Note |
| --- | --- | --- |
| Modules | `jarvis/domain/presentation_studio_cues.py` (pure: `CueMatcher`, `CueMatch`, `CueEvidence`, `CueDecision`, `Verdict`, `MatchRule`, `MatcherConfig`, `ArmedCues`, `parse_armed`, `fold_token`), `jarvis/runtime/presentation_studio_cue_follower.py` (`PresentationStudioCueFollower`, `FollowerState`, `FollowerConfig`, `FollowerCounters`) | section 3 named `presentation_studio_cues.py` and the follower; both exist as named |
| Output | `CueMatch(cue_id, generation, evidence)`, `evidence = CueEvidence(utterance_id, start, end, rule)` | no text field; `authorizes_actions = False` |
| Lane seam | `AmbientIngestionLane.add_utterance_consumer(consumer) -> remove` | beside `on_utterance` / `on_trigger`, which are unchanged; no new import in the lane |
| Composition | `PresentationComposition.cue_core` (Voice `LocalCoreClient`) and `.cue_follower(turns)`; `PresentationStack.cue_follower` (started after the lane, stopped first) | `jarvis/app.py` passes `core=core` to `_presentation_composition` |
| Core reads/writes used | `LocalCoreClient.presentation_studio_playback_armed`, `.presentation_studio_report_cue`, and the `/v1/events` stream for `presentation_studio.armed.changed` | nothing new in Core or in the protocol |
| Event | **none**: `system.presentation_studio.cue_satisfied` is not created | section 5 listed it; Slice 12 decided that a cue is movement and no event names a cue, so no Python/JS parity work and no `cue_id` in `ATTRIBUTE_KEYS` |
| Diagnostics (Voice) | `presentation.studio.{follower_started, follower_stopped, follower_state, armed_set_changed, cue_fired, cue_ambiguous, cue_report_refused, follower_degraded, follower_recovered, follower_events_lost, follower_events_unavailable, follower_probe_failed, follower_handler_failed}` | section 5 pattern `presentation.studio.<event>`; codes `cue_fired`, `cue_ambiguous`, `armed_set_pulled`, `cue_follower_{state,degraded,recovered,probe_failed,handler_failed,events_lost,events_unavailable}` |
| Verdicts | `fire`, `no_armed`, `no_match`, `ambiguous`, `quoted`, `hedged`, `question`, `not_anchored`, `order_blocked`, `already_fired`, `cooldown` | one `Verdict`, only `fire` carries a match |
| Follower states | `starting`, `idle`, `unarmed`, `following`, `paused_address`, `backoff`, `lapsed`, `stopped` | Core's own `follower` field (`waiting`, `connected`, `absent`; Slice 12 rework) is derived from the pulls |
| Tests | `test_presentation_studio_{cues,cue_follower,cue_authority,cue_corpus}.py`, `tests/integration/test_presentation_studio_cue_replay.py`, `tests/fakes/presentation_studio_cue_corpus.py`, `tests/replay/presentation_studio_cue_replay.py` | `build_rig(..., cue_core=)` added to `tests/fakes/presentation_scenario.py` |
| Docs amended | `presentation-addressed-turn.md` s12 (amendment), `presentation-ambient-lane.md` s12, `presentation-studio.md`, `conversation-events.md` (note 8), `OPERATIONS.md` (*Suivi des cues à la voix*) | |
| Rework (QA-1) | `jarvis/runtime/presentation_studio_cue_composition.py` (`build_cue_follower`), `presentation_studio_score.weak_cue_warnings` (+ `CUE_STOPWORDS`), score answers gain `warnings: [{code: "weak_cue", cue_id, phrase_index, reasons}]` only when non-empty; follower `address_marker` (the addressed-turn service's `counters.armed`), `jarvis` token anywhere pauses cue automation; `MatcherConfig.{before_tokens, after_tokens, utterance_before_tokens, utterance_after_tokens}` replace `anchor_tokens` | clause-level anchoring (1 / 1 / 6 / 4), hedges on both sides, opaque utterance id (`^[a-z]{1,8}-[0-9a-f]{1,16}$`), bus messages share the poll backoff; fixtures `tests/fakes/presentation_studio_cue_corpus_{qa,fresh}.py`; Slice 12 follow-up: publish `armed.changed` at run start even when empty |

## 18. Slice 11 amendments (implemented; stable parts in `docs/presentation-studio.md`, "Authoring contract (Slice 11)")

| Topic | Name | Note |
| --- | --- | --- |
| Modules | `jarvis/domain/presentation_studio_authoring.py` (`AuthoringBrief`, `PresentationDraft`, `parse_brief`, `parse_draft`, `safe_text`, `scan_json`, `Workflow`, `Speech`, `SceneRole`, `DaMode`), `..._authoring_text.py` (the lexical helpers: placeholders, content floor, filler, language guess, must-cover, risky sources), `..._authoring_finalize.py` (`draft_from_stored`, `NOT_JUDGED`), `..._authoring_build.py` (`build_presentation`, `BuiltPresentation`, `validate_built`, `require_art_directions`), `..._authoring_gate.py` (`check_first_draft`, `RULES`, `QualityReport`, `Finding`), `..._authoring_policy.py` (`choose_workflow`, `question_budget`, `RequestSignals`, `QuestionTopic`, `PLANNER_PROMPT`), `jarvis/core/presentation_studio_authoring.py` (`PresentationStudioAuthoring`: `check`, `assemble`, `reconcile`), `jarvis/protocol/presentation_studio_authoring_routes.py`, `jarvis/runtime/presentation_studio_authoring_relay.py` | section 3 had no authoring row; one responsibility per module (the schema, the documents, the rules, the policy) |
| Ids | none new | every `pst_`, `psv_`, `pss_`, `psi_`, `psc_`, `psr_`, `psd_` id is allocated by Core at assembly; the brain names scenes, bundles and candidates with its own slugs |
| Routes | Core `POST /v1/presentation-studio/authoring/check`, `POST .../assemble`, `POST .../finalize`, `GET .../reconcile`; relay `POST /api/presentation-studio/authoring/{check,assemble,finalize}` (actor forced to `user`) | section 5 listed `presentations`, `.../variants`, `.../edits`, `.../playback`, `cues/satisfied`, `fullscreen`; the `authoring` prefix is added to `FORWARDABLE_PREFIXES` |
| Client | `LocalCoreClient.presentation_studio_authoring_check`, `.presentation_studio_authoring_assemble`, `.presentation_studio_authoring_finalize`, `.presentation_studio_authoring_reconcile` | both outcomes of `assemble` (`delivered` 201, `refused` 400 with the report) are returned as results |
| Store | `PresentationStudioStore.create(..., scores=None, art_directions=None)`; `PresentationStudioService.create_assembled` | the whole Presentation in ONE folder rename (scores and art directions included); `_remove_staging` knows the `scores/` and `art_directions/` subfolders |
| Error code | `presentation_studio_draft_refused` (400) | the envelope of a refused draft; the failures are in `report` |
| Rule codes (48, `RULES`) | `brief_invalid`, `draft_schema`, `prefab_invalid`, `prefab_namespace`, `pin_unknown`, `scene_incompatible`, `score_incompatible`, `document_invalid`, `da_missing`, `da_incoherent`, `da_fallback_ignored_sources`, `contrast_low`, `arc_incomplete`, `scene_no_score`, `scene_unbound`, `scene_no_controls`, `transition_missing`, `placeholder_text`, `placeholder_allowed`, `content_thin`, `repeated_filler`, `filler_numeric_variants`, `text_density`, `text_dense`, `duration_off`, `duration_missing`, `duration_item_range`, `presenter_mismatch`, `jarvis_line_missing`, `notes_missing`, `must_cover_missing`, `language_mismatch`, `cue_weak`, `cue_stopword_phrase`, `cue_ambiguous`, `cue_nested`, `cues_sparse`, `controls_too_many`, `control_unlabelled`, `control_label_meaningless`, `control_no_meaning`, `control_unbounded`, `motion_unguarded`, `behavior_risky`, `payload_headroom`, `document_headroom`, `candidates_count`, `candidates_not_divergent` | a finding code is a rule code, not an error code; levels per workflow in the doc table |
| Prompt | id `presentation_studio.authoring.planner`, constant `PLANNER_PROMPT`, path-independent `PROMPT_FINGERPRINT` (id + text; the registry's `default_revision` also hashes the source path) in the **domain** policy module (precedent: `conversation_prompt`, `front_brain_prompt`), descriptor in `jarvis/runtime/prompt_catalog.py`, `read_only`, no program step | the matrix row 11 said "`claude_local.py` constant"; the domain module lets the prompt interpolate the gate's constants and keeps `claude_local.py` (hot, shared) untouched. Slice 21 appends it to its program |
| Operation names | `presentation_draft_check`, `presentation_draft_assemble`, `presentation_draft_finalize` (`OP_CHECK`, `OP_ASSEMBLE`, `OP_FINALIZE`) | **proposed** MCP tool names for section 6 (the set there predates them); Slice 21 decides and pins the mapping in its catalogue parity test |
| Event | **none** | the answer carries the ids; reuse of an existing mechanism (the list of Presentations) if a UI wants to refresh. No Python/JS parity work, no new `ATTRIBUTE_KEYS` |
| Diagnostics | `core.presentation_studio.{authoring_checked,authoring_refused,authoring_delivered,authoring_unreferenced,authoring_reconciled}`, `created` (reused, `create_assembled`); relay `presentation_studio.request.relayed` (actions `studio_authoring_check`, `studio_authoring_assemble`) | ids, codes and counts only, never the brain's text |
| Tests | `test_presentation_studio_authoring{,_gate,_policy,_service,_store,_crash,_routes,_docs}.py`; rig `tests/fakes/presentation_studio_fake_author.py`, `presentation_studio_authoring_env.py` | the crash drills use a real `Popen.kill()` |
| Docs amended | `presentation-studio.md` (Authoring contract, policy items 10 and 11, concept and levels rows, failures table, storage), `prefabs.md` (consumer row), `ARCHITECTURE.md` (owner row), `OPERATIONS.md` (*Assemblage d'une presentation*), `docs/mcp/tool-contract.md` **untouched** (Slice 21) | |

## 20. Slice 06 additions (merged after 12 to 18; 19 is Slice 07's) (scene hot reload; stable parts in `docs/presentation-studio.md`, "Hot reload contract")

| Topic | Name | Note |
| --- | --- | --- |
| Modules | `jarvis/domain/presentation_studio_reload.py` (pure), `jarvis/core/presentation_studio_reload.py` (`PresentationStudioReloadService`), `presentation_studio_reload_stage.py` (`StageWindows`, the reload's bindings to the playback's stage windows; the playback's own `presentation_studio_stage.py` / `SceneStage` creates them), `presentation_studio_mounts.py` (`MountBook`), `presentation_studio_pins.py` (`StudioPinRegistry`), `jarvis/runtime/control_center_presentation_studio_reload.js` (`window.JarvisStudioReload`, marker `/*__CONTROL_CENTER_PRESENTATION_STUDIO_RELOAD_JS__*/`) | section 3 listed only `core/presentation_studio_reload.py`; the stage, mounts and pins are separate small modules |
| Variant schema | `schema_version` 3: each scene gains `source_revision` (monotonic, service-owned) and `last_valid_pin` (the pin to restore while the current one is unconfirmed); `UPGRADES[variant][2]` | stored with the scene document, as the PM required |
| Statuses | `ReloadStatus`: `reloaded`, `reloaded_state_reset`, `repinned`, `pending_mount`, `refused_validation`, `rolled_back`, `stale`, `degraded` | `repinned` and `pending_mount` are additions to the four the handoff named: "no stage window" and "no report from the page" are different facts from success and rollback |
| Source ids | `presentation-studio.p<12 hex of presentation>.s<12 hex of scene>` (`source_prefab_id`) | one id per scene; variants differ by pin; a base/shared prefab is forked on the first edit |
| Error codes | `presentation_studio_source_invalid` (400), `_mount_failed` (409), `_stage_failed` (409), `_reload_unavailable` (409) | |
| Routes | Core `POST /v1/presentation-studio/presentations/{id}/variants/{vid}/source-edits`, `POST .../presentations/mount-reports`, `GET .../presentations/{id}/reloads`; same three on the relay, actor forced to `user` on `source-edits` (the provisional `.../stage` route was removed at the merge) | typed client `presentation_studio_source_edit/_mount_report/_reloads/_show` |
| Event | `system.presentation_studio.scene_reloaded` | no new `ATTRIBUTE_KEYS` |
| Stage window id | `studio-stage-<run_id>[-<n>]` (Slice 12's, one per run); the reload never creates one | a runtime handle: never in a document; the reload only binds to it (`StageWindows.bind/unbind`, called by the playback's `stage_observer`) |
| Interfaces for later Slices | `PlaybackProbe.position(presentation_id)` = `PresentationStudioPlaybackService.position` (done), `StudioPinRegistry.add_source(name, fn)` (undo 08 done; 17, 20 later; variants 16 by `rebuild(PresentationStudioVariants)`), `StageWindows.bind/unbind` (done); `ReloadOrigin` (token of the reload's commit announcements, `PresentationStudioEditService.announce_commit`), `PresentationStudioService.scenes_for_copy` (branch rule) | |
| Host | `createPrefabHost({onOutcome, swapPrefix})`, `host.counters(id)`; hot swap of studio sources; no `jv:1` change | `docs/prefabs.md` |
| Decisions | source requests stay in memory (not durable); no state snapshot message in `jv:1`; the `presentation-studio.` id namespace is refused by `POST /v1/prefabs` | reasons in the repo page |

## 21. Slice 17 amendments (implemented; stable parts in `docs/presentation-studio.md`, "Scene-local variant contract")

| Topic | Name | Note |
| --- | --- | --- |
| Modules | `jarvis/domain/presentation_studio_scene_variant_ops.py` (the five operation dataclasses), `jarvis/core/presentation_studio_preview.py` (`ScenePreviewMixin`, `Preview`), `jarvis/domain/presentation_studio_scene_variants.py` (pure: `SceneVariant`, `SceneVariantSet`, `create`, `rename`, `select`, `delete`, `restore`), `jarvis/core/presentation_studio_scene_variants.py` (`PresentationStudioSceneVariants`: `describe`, `preview`, `cancel_preview`, `promote`), `jarvis/protocol/presentation_studio_scene_variants_routes.py`, `jarvis/runtime/presentation_studio_scene_variants_relay.py` | section 3 had `SceneVariant` in `presentation_studio_variants.py` (the graph module): the set lives in its own pure module, below `presentation_studio_scene.py` in the import order |
| Id | `psx_<12 hex>` | a scene-local variant, unique in its scene |
| Stored shape | the key `scene_variants` of a scene: `{current_id, items: [{variant_id, label, rationale, source, created_by, created_at, content?}]}`; absent when a scene has fewer than two variants | `selected` is a runtime-state name (`RUNTIME_KEYS`), hence `current_id`; `content` is `{prefab, props, data, controls, anchors}` and is absent for the selected entry (its content is the scene) |
| Schema | variant document `schema_version` **4** (`UPGRADES[variant][3]` is the identity); v3 is Slice 06 (`source_revision`, `last_valid_pin`); Presentation unchanged | merge rule done: the two additions use different scene keys, Slice 06 took 3 and this Slice renumbered to 4 |
| Operations | `scene_variant.create`, `.rename`, `.select` (optional `drop_others` = promote into the current variant), `.delete`, `.restore_set` (undo form) | members of `OpName`, tier `structure`, both actors; no new event type |
| Codes | `presentation_studio_unknown_scene_variant` (404), `presentation_studio_scene_variant_protected` (409) | the others reused: `limit_reached`, `already_exists`, `score_incompatible`, `stale_revision`, `unknown_scene` |
| Bounds | `MAX_SCENE_VARIANTS` 8, `MAX_SET_BYTES` 32 KiB (stored + live, `create` only), `MAX_DECK_VARIANTS` 48, label 40, rationale 160; preview `timeout_s` 1..120 (default 30) | the variant document cap (256 KiB) and the 16 KiB scene payload cap are unchanged |
| Routes | Core `GET .../scenes/{scene_id}/scene-variants`, `POST .../scene-variants/{scene_variant_id}/preview`, `POST .../scene-variants/{scene_variant_id}/promote`, `POST .../presentations/{presentation_id}/scene-variants/preview/cancel`; relay the same under `/api/presentation-studio/presentations`, actor forced to `user` | writes of a set are `.../edits` |
| Client | `LocalCoreClient.presentation_studio_scene_variants`, `presentation_studio_scene_variant_preview`, `presentation_studio_scene_variant_cancel_preview`, `presentation_studio_scene_variant_promote` | |
| Pin source | `StudioScene.held_pins()` called by the ONE `variant_pins(scenes)` of `presentation_studio_service.py` (which adds `last_valid_pin`; the registry reads it through `PresentationStudioVariants.pin_index()` and `register_variant`); `pins_of` reads `scene.add` with a set and `scene_variant.restore_set` | |
| Playback | `PresentationStudioPlaybackService.show_preview`, `end_preview` (from `ScenePreviewMixin`); `where()` gains `preview` only while a preview lasts; `_Preview` | the preview state is memory only |
| Branch hook | `PresentationStudioVariants.create_branch(..., transform=)` | pure, applied before any write; never read from a body |
| Edit engine | `apply_ops(..., now=, new_scene_variant_id=)`; `PresentationStudioEditService(new_variant_id=)`, `score_regression(variant, scenes)` | injected for tests |
| Diagnostics | `core.presentation_studio.{scene_variant_described,scene_variant_previewed,scene_variant_preview_ended,scene_variant_promoted,preview_shown,preview_ended,preview_timeout_failed}` | ids and counts only |
