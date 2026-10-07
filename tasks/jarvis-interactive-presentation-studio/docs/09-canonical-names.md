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
| Score | `Score`, `ScoreItem`, `Track`, `Cue` | tracks: `user_speech`, `jarvis_speech`, `visual`, `motion`, `cues`; `Silence` is an explicit item kind (D07) |
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
| `score_item_id`, `cue_id` | `psi_` / `psc_` + 12 hex | unique inside a variant; the **only** thing an ambient match may name |
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
