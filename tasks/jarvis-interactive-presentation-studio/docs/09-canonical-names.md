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


## 12. Slice 09 amendments (implemented; stable parts in `docs/presentation-studio.md`, "Art direction contract" and "Art direction authoring policy")

| Topic | Amendment | Reason |
| --- | --- | --- |
| Id | the DA id stays `psd_<12 hex>` (`art_direction_id`, section 2 and the Slice 02 variant field `art_direction_id`); the brief's `pda_` was **not** introduced | the Slice 02 variant already validates `psd_` and fixtures carry it; two prefixes would orphan stored data |
| Names | the stored document is `ArtDirection` (`art_directions/<art_direction_id>.json`, schema `jarvis.presentation_studio.art_direction` v1) wrapping an `ArtDirectionProfile` | section 1 says `ArtDirection`; the brief says `ArtDirectionProfile`: the profile is the content, the document is the stored unit |
| Modules | `jarvis/domain/presentation_studio_art_direction.py` (model, validation, contrast, theme mapping, `require_art_direction`) **and** `jarvis/domain/presentation_studio_art_direction_authoring.py` (fallback, divergence, derivation from signals) | the section 3 list named one module; one responsibility per module and the file would otherwise pass 1 500 lines |
| Store | `PresentationStudioStore.read_art_direction` / `write_art_direction`; folder `art_directions/` swept for `*.tmp` | same mechanics as `scores/` |
| Core service | `get_art_direction`, `create_art_direction`, `save_art_direction`, `create_fallback_art_direction`, `art_direction_candidates`, `require_art_direction` | section 5 route tree |
| Routes | `GET/POST/PUT .../variants/{variant_id}/art-direction`, `POST .../art-direction/fallback`, `POST .../art-direction/candidates` (a computation, POST because it carries a body) | one resource per variant |
| Candidates | **computed, never stored**: `diverge` is deterministic; adopting a candidate is a normal create or save | no unlinked files, no delete path, no cap to manage |
| Error codes | `presentation_studio_unknown_art_direction` (404), `presentation_studio_art_direction_required` (409) | no DA yet / a serious variant needs one |
| Link ownership | `_persist_variant` refuses a change of `art_direction_id` unless `relink_art_direction=True`; **tightens Slice 02**, which accepted any well-formed id on `PUT .../variants/{id}` | same dead-end analysis as Slice 10 B1: a made-up id would lock the variant out of its own DA; a dangling id is repaired by the next create |
| Theme | `ArtDirectionProfile.to_theme()` (the five host theme keys) and `.to_theme_variables()` (`ALLOWED_THEME_VARIABLES`, all declared in `shell.css`) | no new channel, no new variable, no protocol change |
| Diagnostics | `core.presentation_studio.{art_direction_loaded,art_direction_relinked,art_direction_candidates,art_direction_resolved}` and `saved` with `part: "art_direction"` | section 5 pattern |
