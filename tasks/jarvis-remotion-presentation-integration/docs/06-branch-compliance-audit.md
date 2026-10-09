# 06 - Branch compliance audit (static snapshot)

**Reference**: https://github.com/edebazelaire-circoe/Jarvis/tree/task/jarvis-interactive-presentation-studio at `16e3dc585a29a767af26440e5a4364c8d57d9065`. Read-only GitHub connector review; **no local checkout or independent test execution** (git host network unavailable in this session). Old `LOG.md` recorded a sweep, not reproduced here. Branch was still in progress at the time of review. The statuses below describe code/doc evidence as of this commit, not readiness to ship.

### 01. Presentation aggregate and per-scene structures

- **Status**: Implemented, Level 3.
- **Finding**: StudioScene/PresentationVariant and service support editable source pointers, pins and controls.
- **Evidence**: `docs/presentation-studio.md:19-50; jarvis/domain/presentation_studio_scene.py`.

### 02. High-quality serious first draft + art direction

- **Status**: Partial.
- **Finding**: Authoring quality gate with rules; real-model end-to-end results and source harvesting still need proof.
- **Evidence**: `docs/presentation-studio.md:583-766; tasks/.../LOG.md S11`.

### 03. Script/score and prepared cues

- **Status**: Implemented, with runtime caveats.
- **Finding**: Score supports tracks, roles, silence, soft cues, locked sequences; real live voice behavior still must be validated.
- **Evidence**: `jarvis/domain/presentation_studio_score.py`.

### 04. Audience sidekick and Jarvis presenter

- **Status**: Partial in practice.
- **Finding**: Services in branch, live microphone and audible timing tests pending.
- **Evidence**: `jarvis/core/presentation_studio_playback.py; presenter.py`.

### 05. Rehearsal

- **Status**: Pending.
- **Finding**: Old Slice 15 unchecked at snapshot.
- **Evidence**: `tasks/.../slices/TODO.md`.

### 06. Fullscreen host

- **Status**: Partial.
- **Finding**: Browser API requires click; not proof of arbitrary monitor native takeover.
- **Evidence**: `jarvis/domain/surface_fullscreen.py`.

### 07. Semantic control patch/Inspector/Hot reload

- **Status**: Implemented (Slidecar).
- **Finding**: Prefab pins, controls, source revision publication and one scene reload exist; not a Remotion bridge.
- **Evidence**: `jarvis/core/presentation_studio_reload.py; runtime/inspector.js`.

### 08. Autosave, bounded undo/redo

- **Status**: Implemented.
- **Finding**: File store + session memory undo; no infinite snapshots.
- **Evidence**: `jarvis/core/presentation_studio_autosave.py`.

### 09. Whole-presentation and scene alternatives

- **Status**: Implemented (domain).
- **Finding**: Operations exist; visual explorer/comparison remain pending.
- **Evidence**: `jarvis/core/presentation_studio_variants.py; scene_variants.py`.

### 10. Visual variant explorer + multi-compare/mix

- **Status**: Pending.
- **Finding**: Old Slices 18/19 unchecked.
- **Evidence**: `tasks/.../slices/TODO.md`.

### 11. Template/prefab promotion

- **Status**: Pending.
- **Finding**: Old Slice 20 unchecked; new explicit promotion only rule locked.
- **Evidence**: `tasks/.../slices/TODO.md`.

### 12. Voice-edit / agent tool surface

- **Status**: Pending.
- **Finding**: Old Slice 21 unchecked; existing ambient follower does not equal voice authoring.
- **Evidence**: `tasks/.../slices/TODO.md`.

### 13. Remotion Player / Studio / export

- **Status**: Missing.
- **Finding**: No Remotion integration in inspected branch; HTML/JS prefab host used.
- **Evidence**: `docs/presentation-studio.md / code refs`.

### 14. Engine policy (Remotion forced, Slidecar experimental)

- **Status**: Missing.
- **Finding**: No multi-engine interface or selection; all scenes prefab HTML.
- **Evidence**: `jarvis/domain/presentation_studio_scene.py`.

### 15. Local install-once plugin

- **Status**: Missing.
- **Finding**: Current plugin registry remote MCP URL only.
- **Evidence**: `docs/mcp/plugins.md:49-100`.

### 16. Board artifact source and derivatives

- **Status**: Missing bridge.
- **Finding**: Presentations live under data_root/presentations, not ArtifactService; existing Artifact kinds closed/terminal and Board links available.
- **Evidence**: `docs/presentation-studio.md:143-165; docs/artifacts.md:20-60,204-245`.

### 17. Live assets + self-contained export

- **Status**: Missing bridge.
- **Finding**: Resource references recorded; no verified freeze-and-export pipeline.
- **Evidence**: `jarvis/domain/presentation_studio.py`.

### 18. Prefabs category/taxonomy/compat/tech stack

- **Status**: Missing extension.
- **Finding**: Current Prefab is a window HTML bundle with version and props/data, without Remotion engine details.
- **Evidence**: `docs/prefabs.md`.

### 19. External provenance/licenses

- **Status**: Missing extension.
- **Finding**: Current Prefab provenance records base/custom/fork/revision, no full imported upstream manifest.
- **Evidence**: `docs/prefabs.md`.

### 20. Prefab latest notice and upgrade-in-variant

- **Status**: Missing extension.
- **Finding**: Immutability/pinning exists, but explicit new-version trial UX is new.
- **Evidence**: `docs/prefabs.md; StudioScene`.

### 21. Main branch integration readiness

- **Status**: Conflict risk.
- **Finding**: Branch 129 ahead / 85 behind main at snapshot; cannot assume clean merge.
- **Evidence**: `GitHub compare main...task branch`.

## Special risks and contract conflicts

- Artifact immutable terminal lifecycle vs repeatedly saved Presentation source; resolve mapping *before* implementing registry links. Do not substitute renaming directories for integration.
- Existing browser fullscreen cannot satisfy a spoken-only enter without user gesture; new native-host capability is a separate explicit decision if required.
- Existing MCP external Plugin is a remote server endpoint; local Node tools need an actual host lifecycle/permissions model.
- Remotion Player can preview props, not automatically render arbitrary browser-only interactivity to MP4. Compatibility declaration must be capability-scoped, including export.
- Upstream Remotion SDK/codemods are experimental; pinned versions, seam isolation and live tests are prerequisites.
- Source/head drift, unmerged WIP and baseline reds need fresh PM audit after original task completes.

---

# Final-head audit (main de7b9c59)

**Reference**: `main` = `de7b9c59` (local `main` equals `origin/main`, 0/0). The audited branch `task/jarvis-interactive-presentation-studio` is an ancestor of this head (`git merge-base --is-ancestor 16e3dc58 de7b9c59` is true), so the "129 ahead / 85 behind" divergence of the snapshot above no longer exists: requirement 21 is **resolved**. Worktree: `C:/Projects/jarvis/brm`, branch `task/jarvis-remotion-presentation-integration` at `7648eba5` (main plus the handoff only, no product change). Audit date: 2026-10-09.

**Method.** The code of this head was read before the snapshot table above was consulted (domain, Core, protocol, relay/MCP, Control Center JS, tests, docs), then compared. Every line number below is from this head. "Tested" means a named test or suite exists in the tree; **the measured results of those suites are in `slices/01-final-branch-conformance/BASELINE.md`** (re-measured on this head, no number carried over from the old LOG). "Unverified" means no machine evidence exists, or none could be produced here.

Status words: **Implemented** (code and tests, behaviour matches the requirement), **Partial** (a real part exists, the rest is named), **Missing** (nothing in the tree), **Unverified** (code exists, the requirement needs evidence nobody produced).

## What changed since the snapshot (corrections to the table above)

| Snapshot claim | Truth on `de7b9c59` | Evidence |
| --- | --- | --- |
| Old Slice 15 unchecked ("Pending") | **Still not built as a Slice**: only part of its behaviours exist through other Slices | R05 |
| Old Slices 18, 19 unchecked (explorer, compare/mix) | **Built and merged** (S18 explorer; S19 backend and S19ui panes) | R10 |
| Old Slice 20 unchecked (template / prefab promotion) | **Built and merged** | R11 |
| Old Slice 21 unchecked (agent / voice operations) | **Built and merged** (`jarvis-presentation` MCP, 12 tools); its QA round is still "pending" in the old LOG | R12 |
| Old Slice 22 unchecked (hardening) | **Built and merged** as a report plus release suites; **physical checks H-1..H-11 not done** | `docs/presentation-studio-release.md:1-12,100-119` |
| 129 ahead / 85 behind main | The branch is an ancestor of `main`: nothing left to integrate | git |

The old task's `slices/TODO.md` (`tasks/jarvis-interactive-presentation-studio/slices/TODO.md`) is stale: it shows 15 and 18-22 unchecked although 18, 19, 20, 21, 22 are in `main` (e.g. merges `7fd422ee`, `ddf1a8c0`, final commit `0bd43312`). Only **15** is genuinely not delivered. Original Slice 01b (frame assets) stayed "proposed" by design (old LOG 2026-10-07).

## Matrix

File:line are on `de7b9c59`. "Doc" means `docs/presentation-studio.md`.

### R01. Presentation aggregate, variants, per-scene structures
- **Status**: Implemented.
- **Evidence**: `jarvis/domain/presentation_studio.py:249` (`Presentation`), `:302` (`PresentationVariant`); `jarvis/domain/presentation_studio_scene.py:289` (`StudioScene`: `prefab: PrefabRef` pin, `props`, `data`, `controls`, `anchors`, `source_revision`, `last_valid_pin`, `scene_variants`); store `jarvis/adapters/file_presentation_studio_store.py:3-12,57` (`<data_root>/presentations/<id>/presentation.json`, `variants/`, `scores/`, `archive/`, `art_directions/`); Core writer `jarvis/core/presentation_studio_service.py:184`. Doc `:49`.
- **Tested**: 133 `tests/unit/test_presentation_studio_*.py` files (domain, store, service, durability, crash, routes).
- **Remotion-relevant fact**: a scene source **is** an HTML prefab bundle (`PrefabRef`). There is **no engine or source-kind discriminator** anywhere (`presentation_studio_scene.py:289-310`, `presentation_studio.py:249-262`; the word "engine" in `core/presentation_studio_edit.py` only means "edit engine").

### R02. High-quality first draft and art direction
- **Status**: Implemented on the machine side; **quality unverified by a person**.
- **Evidence**: gate `jarvis/domain/presentation_studio_authoring_gate.py:81` (`Rule`), guide `presentation_studio_authoring_guide.py`, Core `jarvis/core/presentation_studio_authoring.py:159`, art direction `jarvis/domain/presentation_studio_art_direction.py` (+ `_authoring`, `_vocab`); playback refuses a serious start without DA (`jarvis/core/presentation_studio_playback.py:20-21,76`). Doc `:422` (DA), `:592` (authoring).
- **Tested**: `test_presentation_studio_authoring_*`, `_art_direction_*`; real-model traces `tasks/jarvis-interactive-presentation-studio/slices/22-end-to-end-hardening/evidence/authoring-real-traces.md` (7 scenarios; two blocking product defects found and fixed: `docs/presentation-studio-release.md:75-95`).
- **Unverified**: brand-linked DA with real brand files, a 12-scene deck with a real model, composition / templates with a real model (`release.md:95`); whether a first draft is "respectable" (H-9, Human).

### R03. Script / score / prepared cues / locked sequences
- **Status**: Implemented (machine-proven); live voice unverified.
- **Evidence**: `jarvis/domain/presentation_studio_score.py:716` (`Score`), `:426` (`LockedSequence`), `:509` (`LoopSpec`: declared loops inside a score, **not** a rehearsal command), `:273` (`CueDefinition`); executor `jarvis/domain/presentation_studio_sequence.py:133` (`SequenceClock`); matcher `presentation_studio_cues.py`; armed set `presentation_studio_armed_set.py:78`. Doc `:305`, `:2106`, `:2223`.
- **Tested**: `test_presentation_studio_score*`, `_sequence*`, `_cues`, `_cue_corpus`, `_release_faults` (13 adversarial utterances). Matcher rates are measured on typed corpora only (old LOG).
- **Unverified**: any real microphone / OpenAI ambient stack (H-3), audible timing (H-4).

### R04. User-presenter sidekick and Jarvis presenter
- **Status**: Implemented; **Unverified live**.
- **Evidence**: roles `jarvis/domain/presentation_studio_roles.py:53-58` (`StudioRole`), speech-authority decision A (Doc `:1566`), `jarvis/core/presentation_studio_presenter.py`, cue follower `jarvis/runtime/presentation_studio_cue_follower.py`. `mouth.speech.started` fires at generation request, before the first audio write (`release.md`, H-4 row).
- **Unverified**: H-3, H-4, H-5 (no test produces audio).

### R05. Rehearsal, recall, script refinement (original Slice 15)
- **Status**: **Partial**. This is the one original Slice not delivered.
- **Delivered through other Slices**: `rehearsal` role (`presentation_studio_roles.py:58`, used `jarvis/core/presentation_studio_playback.py:614,896`), `goto` / `previous` events (`jarvis/domain/presentation_studio_playback.py:80-81`), bounded "where are we" (`:906`), pause-edit-resume through the playback `edit` verb (`jarvis/protocol/presentation_studio_playback_routes.py:11`), `presentation_play` goto / previous (Doc `:2910-2918`).
- **Missing** (checked in the closed event enum `playback.py:73-96`, the verb list `playback_routes.py:11` and the tool ops): a **section loop / restart-a-section command** and the dedicated rehearsal runbook. `release.md:8,119` says the same; confirmed independently.
- **Tested**: `tests/unit/test_presentation_studio_release_flows.py:139` (`test_journey_rehearsal_section_where_am_i_edit_pause_resume_and_backtrack`).
- **Unverified**: HVAL-IPS-005 / H-6 (voice recall).
- **Integration note**: not a prerequisite of the Remotion work; carried as an Issue (see Slice 01 REPORT).

### R06. Fullscreen borderless host
- **Status**: Partial (as designed; browser limits).
- **Evidence**: domain `jarvis/domain/surface_fullscreen.py:159-310`; page `jarvis/runtime/control_center_fullscreen.js:15,336,368` (`requestFullscreen()` called inside the prompt click, single call site); Doc `:2990` and `:3010` ("There is no desktop host ... a voice request alone cannot start it").
- **Unverified**: real projector / multi-monitor / permission prompt (H-1), toasts invisible in fullscreen (H-11). System-wide voice-only fullscreen is **not** provided and the Remotion work must not claim it.

### R07. Semantic control patch, inspector, scene hot reload
- **Status**: Implemented, **for HTML prefab sources only**.
- **Evidence**: edit tiers `jarvis/domain/presentation_studio_edit.py:86-92` (CONTROL / STRUCTURE / SOURCE), `scene.source_request` `:117,367` (the escape for a source change, no free path); Core edit `jarvis/core/presentation_studio_edit.py`; reload service `jarvis/core/presentation_studio_reload.py:110`; domain `jarvis/domain/presentation_studio_reload.py:105` (`SourceEditRequest`), `:152` (`source_prefab_id`), `:159` (`compose_candidate`: manifest and files of a prefab bundle); inspector `jarvis/runtime/control_center_presentation_studio_inspector*.js`. Doc `:788`, `:1656`, `:2505`.
- **Tested**: `test_presentation_studio_edit_*`, `_reload_*` (incl. real-page browser tests), `_inspector_*` (real Chrome).
- **Remotion-relevant**: reload works on prefab bundle files through `PrefabService` / `PrefabDraftCoalescer` and the pin registry. A TSX source needs a new source kind inside this pipeline, not a parallel pipeline.

### R08. Autosave, bounded undo / redo
- **Status**: Implemented. Power-cut durability unproven (stated in the old LOG).
- **Evidence**: `jarvis/core/presentation_studio_autosave.py:62` (`PresentationStudioHistory`), `jarvis/domain/presentation_studio_history.py:66-166`. Doc `:923`.
- **Tested**: `test_presentation_studio_history_*` (crash drills).

### R09. Whole-presentation and per-scene alternatives
- **Status**: Implemented.
- **Evidence**: `jarvis/core/presentation_studio_variants.py:76`, `presentation_studio_scene_variants.py`, domain `presentation_studio_variants.py:120-151`, `presentation_studio_scene_variants.py:122-167`. Doc `:1042`, `:1219`.
- **Tested**: `test_presentation_studio_variants_*`, `_scene_variants_*`.

### R10. Visual variant explorer, multi-compare, semantic mix
- **Status**: Implemented; QA rounds incomplete.
- **Evidence**: explorer `jarvis/runtime/control_center_presentation_studio_explorer*.js`, commands `jarvis/runtime/presentation_studio_explorer_commands.py`, compare `jarvis/domain/presentation_studio_compare.py:77`, composition `jarvis/domain/presentation_studio_composition.py:117`, Core `presentation_studio_compare.py`, `_composition.py`. Doc `:2355`, `:2621`, `:2734`.
- **Tested**: explorer / compare files incl. real-Chrome browser tests.
- **Unverified**: Slice 18 polish items P1, P8-P10, F5, F7-F9 left open (old LOG); **Slice 19 has no QA round recorded** (`release.md` row 19); legibility / usability (H-7, H-8).

### R11. Template / prefab promotion
- **Status**: Implemented (Slice 20) in a narrower shape than the Remotion handoff asks for. **No QA round recorded** (`release.md` row 20).
- **Evidence**: `jarvis/domain/presentation_studio_template.py:3-14,49` (kinds `presentation | scene | art_direction | motion`); Core `jarvis/core/presentation_studio_template.py:121` (`plan`), `:300` (`promote`), `:352` (`_publish`: scene sources are published into the **shared prefab library** as `studio-template.<slug>[-n]`, origin `fork`, **one library prefab per distinct sanitized source**, `:229-260`), `:460` (`instantiate`). Explicit only (plan then promote). Doc `:1422`.
- **Differences against the Remotion decisions**: (a) promoting a full presentation publishes each distinct scene source as a library prefab; D10 allows explicit promotion, but "without individually publishing all constituent scenes" is **not** what the code does (needs a Human product decision before Slice 19); (b) a template carries scenes and DA, **not the score** (Doc, `release.md` known limits); (c) no Component / Composition / Page / Presentation / Asset type; (d) no licence or upstream fields.
- **Tested**: `test_presentation_studio_template_*`.

### R12. Voice-edit / agent tool surface
- **Status**: Implemented; QA round of Slice 21 unrecorded; **not run on the live voice stack**.
- **Evidence**: MCP server `jarvis/runtime/presentation_studio_mcp.py:169-334` (12 tools `presentation_inspect|view|play|edit|undo|variant|compare|compose|template|draft_check|draft_assemble|draft_finalize`), logic `presentation_studio_mcp_tools.py`, support `presentation_studio_mcp_support.py`; Tool Brain guard `studio_owned` in `jarvis/runtime/tool_brain_executor.py`; start origin attested by the real addressed turn (`presentation_studio_turn.py`, Doc `:2906`). Context budget `tests/unit/test_mcp_catalog.py:233` (`PRESENTATION_CONTEXT_BUDGET_BYTES = 17_100`; the old LOG records 16 849 B in use, about **250 B of margin**).
- **Tested**: `test_presentation_studio_mcp_*` (ops, policy, trace, docs), `_cue_authority`, replay traces. Real model: 5 scenarios (Slice 21) + 7 (Slice 22, authoring only).
- **Known red**: the brain-prompt parity test (`ui_intent_publish`) is red on `main`, not ours (BASELINE.md).

### R13. Remotion Player / Studio / export
- **Status**: **Missing** (confirmed).
- **Evidence**: `grep -ri remotion` over `jarvis docs scripts tests pyproject.toml` returns nothing; the repo has no `package.json`. Node v24.18.0 / npm 12.0.1 exist on this PC (READINESS), nothing in the repo uses them for the product.

### R14. Engine policy (Remotion forced default, Slidecar experimental, no fallback)
- **Status**: **Missing**. No engine field or selection exists at any layer (R01).

### R15. Local install-once capability vs remote MCP plugins
- **Status**: **Missing**; the plugin registry exists exactly as the handoff describes.
- **Evidence**: `jarvis/domain/mcp_plugins.py:203-234` (`McpPlugin`: `endpoint` URL; `transport` must equal `streamable_http`, else `mcp_transport_unsupported` at `:233`), `jarvis/core/mcp_plugin_service.py:254`, `jarvis/adapters/sqlite_mcp_plugins.py`, UI `jarvis/runtime/control_center_mcp_plugins.js`, contract `docs/mcp/plugins.md`. Local stdio servers are "operator-managed" (`docs/mcp/plugins.md:1093-1101`; `jarvis-drive` is registered by `claude mcp add`).

### R16. Board artifact source and derivatives
- **Status**: **Missing bridge**; the primitives exist as described.
- **Evidence**: `ArtifactKind` is a **closed** enum of 7 kinds, none a document / video / presentation (`jarvis/domain/artifacts.py:136-148`); terminal states `:150-163`; relation vocabulary closed (`:165-180`, no "rendered_from"); payload store `jarvis/adapters/artifact_payloads.py`; `ArtifactService` `jarvis/core/artifact_service.py:82`; Board links `jarvis/domain/board_artifact_links.py:32-67`, port `jarvis/ports/board_artifact_links.py:24-41`, adapter `jarvis/adapters/sqlite_board_artifact_links.py`, **service door** `jarvis/core/workspace_service.py:801` (`artifact_link`) and `:825` (`artifact_unlink`). A second, memory-level reference list exists (`artifact_refs` in Board memory, `jarvis/core/board_service.py:95,219`): Slice 08 must pick one owner. A Presentation is explicitly not an Artifact (Doc `:10-17`); storage is `<data_root>/presentations/` (store `:57`); presentation `resources` are `ResourceReference` of kinds document / web_page / chart_descriptor / scene_object / dataset / note (`jarvis/domain/presentation_working_set.py:247-261`), none an Artifact id or a Board id.

### R17. Live assets and self-contained freeze / export
- **Status**: **Missing**. `grep -i "freeze|frozen|export"` over `presentation_studio_*` only finds the cue-clock pause (`presentation_studio_presenter.py:125-356`), nothing about a package or an export.

### R18. Prefab taxonomy, compatibility, tech stack
- **Status**: **Partial**: storage and shop UI exist, the taxonomy does not.
- **Evidence**: manifest has `family` (token, `jarvis/domain/prefab.py:55-56,614-640,690`) and `tags`; library UI `jarvis/runtime/control_center_prefabs.js` (filter by kind and family `:324-326,481-491`, live preview object `:52`, provenance and badge model). Absent: semantic type (Component / Composition / Page / Presentation / Asset), engine compatibility, tech stack, dependency and licence fields.

### R19. External provenance and licences
- **Status**: Missing extension. Provenance today is `Publication.provenance.origin in {base, custom, fork, revision, base_edit}` (`docs/prefabs.md:32,186-203`); no upstream URL / hash / licence / import record.

### R20. Newer-version notice and upgrade-in-variant
- **Status**: **Partial**. Exact pins and immutable versions exist (`StudioScene.prefab`, `held_pins()`, `StudioPinRegistry`, `docs/prefabs.md:343-397`; `scene_get` reports `latest_version`, `prefabs.md:969`); variants and scene-local variants (R09) can host a trial. **Missing**: a "newer version available" notice for a Studio scene and an "upgrade this scene in a new variant" operation (`grep newer|upgrade` finds only schema upgrades).

### R21. Integration with `main`
- **Status**: **Resolved** (see header). Remaining integration debt: the open items of the old LOG (S18 polish, QA for S19/S20/S21, H-1..H-11) and the red tests of BASELINE.md.

## Verdict of the audit

1. The Slidecar foundation is real, merged and much larger than the snapshot knew (S18-S22 landed). **Do not rebuild** anything in R01-R12.
2. Things the Remotion plan could believe missing but that exist: variant explorer, compare / mix, template and prefab promotion, an agent / voice MCP surface with Tool Brain ownership guard, an authoring planner with quality gate and real-model traces, a prefab library UI with provenance badges, pins and retention.
3. Everything Remotion-specific (R13-R17, the R18 / R19 extensions, the R20 trial UX) is genuinely missing.
4. Integration risks found by this audit and not in the snapshot: `docs/06-branch-compliance-audit.md` (sections "Redundant, overlapping or re-scoped plan entries" and "Integration risks for Remotion").

## Handoff dependencies resolved by this audit

- Phase A ("wait for the original task"): resolved. The studio branch is an ancestor of `main`; there is nothing to integrate; the 129 / 85 divergence is gone.
- Which original Slices are really done (verified in code, not from TODO.md): 00-14, 16, 17 done and merged; **18, 19, 20, 21, 22 done and merged** (the old TODO.md is stale); **15 not delivered**. QA rounds are unrecorded for 19, 20, 21. Physical Human checks H-1..H-11 are open (`docs/presentation-studio-release.md`).
- Handoff premises confirmed on this head: Artifact kinds closed (7) with terminal states; Board link service exists (`WorkspaceService.artifact_link`, `jart_` ids only); presentation storage is `<data_root>/presentations/`; the remote MCP plugin registry is URL / `streamable_http` only; Remotion is absent from code, docs and repository.

## Redundant, overlapping or re-scoped plan entries

No Slice is deleted (each still has genuinely missing content), but five shrink, one splits and two move. Details are in the "Plan amendment after Slice 01" section of each SLICE.md and the banner of `slices/TODO.md`.

| Slice | Verdict | Why (existing code) |
| --- | --- | --- |
| 13 controls bridge | Shrink | `StudioControl`, CONTROL-tier ops with CAS, inspector and scene-local variants exist (R07). Left: map the Remotion props schema to manifest inputs and push `inputProps` live. |
| 15 one-shot authoring | Shrink, overlap | Brief, 48-rule gate, `draft_guide`, atomic assemble, DA fallback / divergence and the real-trace harness exist (R02). The planner builds HTML prefab scenes today: add a Remotion generator behind the same `presentation_draft_*` tools. |
| 17 prefab shop | Shrink, re-scope | The library UI (filters, ranked search, provenance, preview) and `family` / `tags` exist (R18). The work is a prefab **manifest contract version** (closed keys, `schema_version == 1`) plus a UI extension. Needs Slice 05 (dependency added). |
| 19 promotion, pins, upgrades | Shrink, split, Human decision | Explicit promotion exists (old Slice 20, R11). Keep Remotion-aware promotion, newer-version notice and upgrade-in-new-variant (R20). Today a presentation promotion publishes one library prefab per distinct scene source, which the handoff's last bullet rejects. |
| 21 voice tools | Shrink, budget risk | 12-tool `jarvis-presentation` surface, Tool Brain `studio_owned` guard and turn attestation exist (R12). Tool context is at about 16 849 / 17 100 B: new verbs need another server / category or a deliberate budget change. |
| 20 engine policy | Split | Enforcement (no engine argument on any agent tool, typed errors, no fallback) is tested in Slice 02; 20 keeps the Human toggle, diagnostics and legacy-engine-identity migration. |
| 11 Studio window | Reorder | Optional by decision 5; removed from the dependency chains of 14 and 15 (now 14 on 10, 15 on 14); added to the gates of 21 and 22. |
| 14 source edit / HMR | Re-scope | Extend `scene.source_request` -> `PresentationStudioReloadService` (rollback, locks, coalescer, pins). Only the TSX build / validate step is new. |
| 02, 05, 07, 10, 12 | Keep, add decisions and constraints | See the risks below. |

Unchanged and genuinely new: 03 (local capability host), 04 (provisioning), 06 (isolation), 08 (registration, reuses `artifact_link`), 09 (freeze: no code exists), 16 (export), 18 (importer: none exists), 22 (reuse the old release machinery).

## Integration risks for Remotion (found by this audit)

1. **No engine discriminator exists.** A scene source is an HTML prefab bundle pinned by `PrefabRef` (`presentation_studio_scene.py:289`). The edit engine, hot reload (`compose_candidate`), pin registry, retention, undo pins, stage window and templates all assume it. A Remotion source must become a source kind **inside** this pipeline (recommended: a bundle kind of the prefab library) or each of those owners needs a parallel implementation. Decide in 02 / 05.
2. **"Remotion forced default" and "no forced conversion" contradict unless legacy is defined.** All existing presentations and everything the existing planner assembles are Slidecar (HTML). Without a rule for documents with no engine field (recommended: implicit `slidecar`, untouched; new documents and new agent scenes are `remotion`) the no-fallback rule cannot be tested.
3. **No compile step in the plan.** The Player needs a browser bundle of TSX; nothing in 04 / 05 / 06 / 10 provides the compiler / bundler process. Added to 04 and 05.
4. **The prefab manifest is closed.** Unknown keys are refused and `schema_version` must equal 1 (`prefab.py:614,681`): engine, type, licence and TSX files all require a manifest version bump with old immutable versions still readable.
5. **A Presentation cannot be Board-linked.** `artifact_link` accepts only `jart_` ids; `ArtifactKind` and the relation vocabulary are closed; Board memory holds a second `artifact_refs` list. Choose the catalog-link vs Artifact split in 07 and one owner for "which Boards show this".
6. **Stage and fullscreen.** Scenes play as prefab window objects on a stage window with an id ledger and reclaim rules; fullscreen needs a user gesture. A Player host that is not a prefab frame needs its own sandbox and reclaim rules; voice-only fullscreen must not be claimed.
7. **Tool context budget** (Slice 21).
8. **Template promotion publishes shared-library prefabs per distinct scene source and carries no score**; Remotion promotion must not silently inherit this.
9. **Repository rules that bind the implementation**: schema changes only by versioned migration with snapshot (CLAUDE.md); no agent starts or stops Core / Control Center / voice, so Node processes launched by Core and Studio must be exercised in a sandbox data root with its own ports; data lives outside the repository (`docs/local-data.md`).
10. **Inherited red tests and unverified physical behaviour** (BASELINE.md, `Issues/01-inherited-debt-from-the-studio-task.md`): a release gate that demands all-green would block on tests that are not ours; the Slice 22 gate must list them as inherited, not hide them.

## Not verified by this audit

- The real-model authoring harness (`tests/replay/presentation_studio_authoring_real_trace.py`) was not run (it costs money and needs the `claude` CLI); the committed traces were read, not reproduced.
- No live voice, microphone, audio, projector or multi-monitor behaviour (H-1..H-11).
- That a Remotion scene can live as a prefab bundle (risk 1) is a design hypothesis for Slice 05 to prove, not a finding.
- `docs/presentation-studio.md` (3 040 lines) was read in the sections cited, not end to end.
- Line numbers are on `de7b9c59` and drift as main moves.
