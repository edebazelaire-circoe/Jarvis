# Slice 00 - Readiness record

**State: `READY` — conditional on two Human decisions (W1 Task Type waiver, D15 restart semantics).**
No implementation Slice is dispatched until both are answered.

| | |
| --- | --- |
| Executed by | agent 0 (Project Manager), not delegated |
| Date | 2026-09-23 |
| Branch | `task/jarvis-presentation-interaction-mode` |
| Branch point | `ddcdb71e17d7be76236c7dd6ab070af90e8f7d65` (`main`) |
| Drift vs. handoff snapshot | **none** — `task.json.source_snapshot.sha` *is* the branch point, and `origin/main == main == ddcdb71` at branch time |
| Drive origin | remote, `Jarvis/task/to-do/jarvis-presentation-interaction-mode` |

## 1. Method

The repository audit was performed **blind**, by a sub-agent forbidden from opening `tasks/`
at all, dispatched before any handoff conclusion was read. It was asked where things *are*,
never whether the handoff was right. Only afterwards were `docs/01-decision-log.md`,
`docs/02-architecture.md`, `docs/03-implementation-strategy.md`, `docs/04-testing-and-quality.md`
and `docs/05-documentation-levels.md` read and reconciled against it. This ordering is the
Slice 00 acceptance criterion and it was respected.

## 2. What the handoff got right

The audit independently confirms every Level-0 claim in `docs/05-documentation-levels.md`:

- **Interaction mode, presentation mode, meeting mode and output disposition are genuinely
  absent.** A repo-wide search for `interaction_mode`, `InteractionMode`, `presentation_mode`,
  `meeting_mode`, `reunion`, `output_disposition`, `response_policy` returns zero product-code
  hits. Every `réunion` hit is French test-fixture *content* (a calendar example sentence),
  never a mode. Nothing today decides "speak vs. show vs. stay silent" as a first-class concept.
- **`conversation_mode` is authorization, not a mode** — `ConversationMode{OPEN_ROOM, SOLO_OWNER}`
  at `jarvis/domain/speaker.py:28-36`. Correctly excluded by `docs/02-architecture.md`.
- **Shared microphone capture is Level 0.** Capture is genuinely single-consumer: one
  `sd.RawInputStream` (`jarvis/runtime/realtime_audio.py:469-480`), one `CaptureProcessor.observer`
  slot (`jarvis/audio/duplex.py:767,812`) with a latch that permanently detaches on first
  exception (`:1272-1290`), one `on_capture_signal` callback (`realtime_audio.py:348`).
  Slice 05 is as large as the plan assumes.
- **Background-event notifications are Level 3 and reusable.** `#bgPills` plus
  `GET /api/background` / `POST /api/background/ack` (`control_center.py:698-699`), categories
  `failed / attention / done / said`. The "discreet sound" already exists as `bgCue()`
  (`control_center.html:920-934`): two WebAudio sine notes, no asset file, played **only on a
  rise of the sequence number**, never on first poll — the dedupe Slice 09 needs is already
  implemented and just has to be honoured rather than rebuilt.
- **Addressed vs. ambient admission is Level 2-3 and must not be weakened.** `AMBIENT` is never
  routed: it raises in `BrainTurnInput.__post_init__` (`jarvis/domain/v2.py:639-654`) and is
  refused by `VoiceTurnAdmissionRequest` (`jarvis/domain/voice_admission.py:131,152`).
- **The wake abstraction is reusable.** `CompositeWakeWordBackend` already fans *in* N backends
  (`jarvis/adapters/wakeword_composite.py:9-68`); the manual key is `wake_toggle`, default `f9`
  (`jarvis/runtime/shortcuts.py:70-80`), and `suspend_for_active_session()` deliberately keeps
  it armed so a second press submits the turn (`wakeword_keyboard.py:57-62`).
- **Scene supports brain-created artifacts, windows and visibility changes**, so hidden staged
  resources are a real reuse path, as `docs/02-architecture.md` assumes.

## 3. Drift and gaps found by the audit — plan amended

Seven findings the handoff does not cover. Each is now a binding constraint on the named
Slice. None invalidates a Slice; the plan is enriched, not reordered.

### G1 — There are *two* voice-architecture axes, not one (Slices 01, 02)

The handoff reasons about `Simple | Front Brain | Duplex`. That is the *typed* axis
(`VoiceArchitectureId`, `jarvis/domain/voice_architecture.py:14-18`, persisted as
`voice_architecture`, `schema_version: 1`). A **second, older axis is still the runtime
authority**: `VoiceArchitecture{LEGACY, CONTINUOUS_BRAIN}` (`jarvis/v2_config.py:69-93`),
persisted as `voice_arch`, read at `jarvis/app.py:648` to compute `continuous_brain`. Both keys
live side by side in `runtime/control-center-settings.json` today, bridged by
`LegacyVoiceCompatibility` (`voice_architecture_config.py:24-35`) and reconciled by
`resolve_voice_composition` (`voice_composition.py:32-48`).

`docs/03-implementation-strategy.md` already forbids renaming either, which is right, but
"orthogonal to voice architecture" must be proven against **both** axes, not one.

Worse, `ControlCenter._apply_voice` (`control_center.py:2637-2665`) is a **three-way mutually
exclusive branch** (`brain_compatibility` / `architecture` / `arch`) whose first branch *deletes*
`voice_architecture`. A new axis routed naively through the same `POST /api/settings` payload
lands inside that if/elif and inherits its mutual exclusion.

**Constraint:** interaction mode gets its own settings key and its own apply path. It is never
written inside `_apply_voice`, and Slice 02 carries a test proving the mode survives a
`brain_compatibility` toggle unchanged.

### G2 — `Disposition` is already taken (Slice 01)

`jarvis/domain/scene.py:190-200` defines `Disposition{ACTIVE, ARCHIVED}` — presence in the
scene. `docs/02-architecture.md` proposes "output disposition" `silent / visual_only /
voice_only / visual_and_voice`. Two unrelated `Disposition` types in one domain is a trap.

**Constraint:** name the new type `OutputDisposition`, in its own module, and never import it
unqualified into a module that also imports the scene one.

### G3 — A new persisted control silently fails to save unless allow-listed (Slices 02, 03)

`jarvis/runtime/voice_settings_schema.py:71-86` holds `PERSISTABLE_OPTION_IDS`, an explicit
allow-list of **47** option ids. Anything absent from it cannot be persisted, and fails
*silently*. Related: `decode_voice_architecture` uses strict unknown-field rejection
(`voice_architecture_config.py:62-67`, code `voice_schema_unknown_field`), so adding a field to
a voice config object without bumping `SCHEMA_VERSION` hard-fails at load.

**Constraint:** Slice 02 acceptance criterion — a round-trip test that writes the mode, reloads
it from disk, and asserts it survived. Not a unit test against the in-memory object.

### G4 — Restart semantics are undecided and cannot be discovered late (Slice 02) — Human decision **D15**

`VoiceComposition.configuration_id` is a SHA-256 over `{selection, conversation_prompt,
analysis_prompt[, live_prompt]}` (`voice_composition.py:22-30`), and `VoiceSwitchCoordinator`
restarts the Voice process when source and target ids differ (`voice_switch.py:36-53`).

That forces a choice the handoff never makes:

- **fold interaction mode into `configuration_id`** — every `SIMPLE` ⇄ `PRESENTATION` toggle
  restarts the Voice process. Correct, but heavy, and it cuts audio mid-presentation, which is
  the worst possible moment.
- **keep it out** — the mode changes live, but any path gated on a configuration change will
  not observe it, and Voice keeps a stale view.

`docs/02-architecture.md` already says "Core owns the effective live mode/revision; Voice
consumes Core truth/events rather than keeping a second optimistic mode state", which points at
the second option plus an explicit live event. That is my recommendation, recorded as **D15**
for Human confirmation, because discovering it wrong at Slice 11 costs the whole control plane.

### G5 — The work lane has no priority field at all (Slices 08, 10)

`docs/03-implementation-strategy.md` specifies a P0-P4 capacity and preemption model. Nothing in
the repository has priorities outside the *speech* lane (`SpeechPriority`,
`jarvis/domain/v2.py:336-359`). `WorkItem` / `WorkSnapshot` (`jarvis/domain/work_state.py:485,587`)
carry status, not priority; `MAX_WORK_ITEMS=64`; removal requires an explicit brain decision
naming the `work_id`. `BackBrainTaskService` has a flat capacity of 32
(`jarvis/core/back_brain.py:40-41`) and no notion of sacrificial work.

**Constraint:** P0-P4 is built **inside the new presentation-speculative admission path**.
`WorkItem` is canonical and shared with Simple mode; an implementer must not add a priority
field to it "while they are there". That would be a D14 regression-boundary violation.

### G6 — There is no generic UI seam, and no framework (Slice 03)

The frontend is vanilla JS with no framework, no bundler and no state store; the page is served
as one concatenated script and refreshes by `setInterval(refreshStatus, 1000)`. The only push
mechanism on the page is `openLifecycleSeam`, and it is **Bare Hands-specific**
(`control_center_barehands.js:4759-4828`). The handoff asks for a selector "analogous in
interaction quality to the Bare Hands lifecycle selector" — achievable, but Slice 03 must
either generalize a seam or accept 1 s polling, and say which.

Two further hard requirements the audit surfaced:

- the page's **z-index registry comment** (`control_center.html:1-23`) is asserted by
  `tests/unit/test_scene_renderer_logic.py`; a new floating element must be registered there or
  that test fails;
- the reference pattern is `role="menu"` + `role="menuitemradio"` with roving `tabindex`,
  deliberately *not* `radiogroup` (`control_center_barehands_hud.js:1304-1308`), with zero local
  state and canonical status only. Slice 03 copies this, including the rule that an *undergone*
  state (`starting`, `error`) leaves **no chip checked**. `REUNION` being reserved fits that
  pattern exactly: presented, never selectable.

### G7 — `AddressingDecision` is closed, wire-encoded and persisted (Slice 06)

Three values (`jarvis/domain/v2.py:88-91`), rejected at two admission points, carried on the wire
(`protocol/server.py:508-514`) and persisted as a literal string (`sqlite_state.py:673`).

**Constraint:** Slice 06 must not widen this enum or relax either rejection. Ambient observation
gets a distinct path, exactly as `docs/02-architecture.md` says — this records *why* the
alternative is closed.

## 4. Regression baseline

Full `tests/unit` suite at the branch point, run in 8 foreground chunks (the host has ~15.6 GB
RAM with little free; a single whole-suite process gets killed).

```
.venv/Scripts/python.exe -m pytest <chunk> -q -p no:cacheprovider
```

| | |
| --- | ---: |
| Test files | 248 |
| Tests collected | 7022 |
| Passed | 6994 |
| **Failed (pre-existing)** | **26** |
| Skipped | 2 |

6994 + 26 + 2 = 7022, reconciling exactly against `--collect-only`. No collection errors.

### Pre-existing failures by file

| File | Failures |
| --- | ---: |
| `tests/unit/test_back_brain_tasks.py` | 1 |
| `tests/unit/test_barehands_interaction_js.py` | 2 |
| `tests/unit/test_barehands_tutorial_retired_js.py` | 1 |
| `tests/unit/test_brain_delegation.py` | 1 |
| `tests/unit/test_scene_artifacts.py` | 6 |
| `tests/unit/test_scene_batch_tools.py` | 3 |
| `tests/unit/test_scene_capture.py` | 1 |
| `tests/unit/test_scene_interaction_logic.py` | 1 |
| `tests/unit/test_scene_query_tools.py` | 2 |
| `tests/unit/test_scene_service.py` | 2 |
| `tests/unit/test_scene_settings.py` | 2 |
| `tests/unit/test_scene_transport_client.py` | 4 |

### Pre-existing failures, full list

These 26 are **inherited, not ours**. Every implementer receives this list with the instruction
"not yours, do not fix". A failure outside this list is unambiguously the current Slice's.

- `tests/unit/test_back_brain_tasks.py::test_persistent_storage_read_failure_preserves_owner_and_bounds_stop[owned_read]`
- `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`
- `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`
- `tests/unit/test_barehands_tutorial_retired_js.py::test_the_brain_is_told_the_tutorial_tool_is_deprecated_and_opens_calibration`
- `tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`
- `tests/unit/test_scene_artifacts.py::test_a_full_scene_refuses_the_artifact_with_its_reason`
- `tests/unit/test_scene_artifacts.py::test_a_pinned_artifact_refuses_a_brain_move_and_keeps_everything`
- `tests/unit/test_scene_artifacts.py::test_a_race_with_the_user_is_told_truthfully_and_never_revives_an_archived_artifact`
- `tests/unit/test_scene_artifacts.py::test_an_archived_or_unknown_target_is_refused_before_anything_is_sent`
- `tests/unit/test_scene_artifacts.py::test_orphan_artifacts_are_bulk_archivable_by_the_user_only_and_linked_ones_never`
- `tests/unit/test_scene_artifacts.py::test_the_artifact_guidance_exists_only_with_the_flag_and_the_other_prompts_are_byte_identical`
- `tests/unit/test_scene_batch_tools.py::test_a_batch_leaves_a_pinned_object_alone_for_anything_but_visibility_and_says_so`
- `tests/unit/test_scene_batch_tools.py::test_an_explicit_list_of_ids_cannot_bypass_the_pin`
- `tests/unit/test_scene_batch_tools.py::test_the_batch_tool_says_when_to_prefer_it_and_still_offers_no_archive_or_pin`
- `tests/unit/test_scene_capture.py::test_the_capture_tool_is_counted_as_display_work_and_the_catalog_has_no_archive_or_pin`
- `tests/unit/test_scene_interaction_logic.py::test_menu_entries_depend_on_kind_origin_and_state`
- `tests/unit/test_scene_query_tools.py::test_the_catalog_adds_two_read_tools_counted_as_display_work`
- `tests/unit/test_scene_query_tools.py::test_the_read_line_exists_only_with_the_flag_and_the_other_prompts_stay_byte_identical`
- `tests/unit/test_scene_service.py::test_refused_and_duplicate_commands_neither_persist_nor_wake`
- `tests/unit/test_scene_service.py::test_scene_commands_never_reach_the_core_event_bus`
- `tests/unit/test_scene_settings.py::test_the_gate_decides_the_brain_launch_arguments_and_its_system_prompt[False-None-False-False]`
- `tests/unit/test_scene_settings.py::test_the_gate_decides_the_brain_launch_arguments_and_its_system_prompt[None-0-False-False]`
- `tests/unit/test_scene_transport_client.py::test_the_js_applier_reproduces_the_python_reducer[1]`
- `tests/unit/test_scene_transport_client.py::test_the_js_applier_reproduces_the_python_reducer[20260916]`
- `tests/unit/test_scene_transport_client.py::test_the_js_applier_reproduces_the_python_reducer[4242]`
- `tests/unit/test_scene_transport_client.py::test_the_js_applier_reproduces_the_python_reducer[99]`

### Risk carried by this baseline

**21 of the 26 failures are in Scene** — and Scene is precisely the reuse surface for Slice 08
(hidden staged artifacts) and Slice 09 (attention objects). Slices 08 and 09 will build on a red
suite, so "the Scene tests are failing" will not be usable as a signal there. Those two Slices
get a narrower, explicitly named green subset as their gate, chosen at dispatch time, plus a
re-measure of the Scene failure set immediately before dispatch (it may have been fixed on
`main` by then — `fix/scene-deplacement-2d` and `fix/session-par-lancement` are live branches
touching this area).

The 5 non-Scene failures are unrelated to this task's surface except
`test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`,
which touches delegation — the mechanism Slice 08 extends. Slice 08 must not be credited with
fixing it, nor blamed for it.

## 5. Planning verification

- **Dependency graph.** All 12 Slices resolve; every dependency id in `slices/TODO.md` names an
  existing Slice folder; the graph is acyclic and the stated order is a valid topological order.
- **Human validation ids.** 12 `human-validation.json` files, all parse. Five carry content
  (Slices 03, 05, 07, 09, 10, 11); the rest are empty placeholders, consistent with Slices whose
  acceptance is machine-checkable.
- **Required skills.** Every coding Slice must load `/caveman` and `/coding-guideline`; frontend
  Slices (03, 09) additionally `/impeccable` with Claude-agent routing. The audit confirms the
  frontend is hand-written vanilla JS with a documented stacking registry and a strict
  accessibility pattern, so the `/impeccable` requirement is substantive here, not ceremonial.
- **Competing live work.** Worktrees currently exist for `fix/scene-deplacement-2d`,
  `fix/session-par-lancement`, `fix/orb-live-state-colors`,
  `fix/wave-amplitude-orchestration-color` and `task/jarvis-constellation-scene-runtime`. Four of
  the five touch Scene or the live orb. Per `docs/03-implementation-strategy.md` and prior
  precedent, `origin/main` is re-checked immediately before **every** Slice dispatch, and
  `origin/main` is merged *into* this task branch, never the reverse.
- **Secret check.** `runtime/control-center-settings.json` holds a plaintext API key and a
  `credentials[]` array. Verified `.gitignore`d (`/runtime/`) and untracked, so nothing leaks
  through this task's commits. Slice 11's privacy scope must keep it that way; no action needed
  now.

## 6. Open Human decisions

### W1 — Workspace Task Type waiver (blocks dispatch)

`task.json.planning_blockers` requires resolving Workspace Task Types or obtaining an explicit
waiver. The vocabulary does not exist in this environment — no "Workspace Task Type" concept is
exposed anywhere the host can reach. The Human has waived this gate for four previous tasks
(settings/model catalog, conversation observability, category 2 test lab, bare hands). Requested
action: the same waiver, leaving `task_type: null` in all 12 `metadata.json`. Inventing labels is
forbidden by the handoff and will not be done.

### D15 — Interaction mode and `configuration_id` (blocks Slice 02)

See G4. Recommendation: **keep interaction mode out of `configuration_id`**, make Core own the
effective live mode plus a revision counter, and have Voice consume it through an explicit live
event rather than a process restart. Rationale: a mid-presentation Voice restart is the single
worst user-visible failure this feature could introduce, and `docs/02-architecture.md` already
assigns mode ownership to Core.

## 7. Verdict

`READY`, conditional on W1 and D15.

The handoff is unusually accurate: zero snapshot drift, and every documentation-level claim held
up under a blind audit. The seven gaps above are additions the plan did not know about, not
contradictions, and all seven are recorded as constraints on Slices that have not started.
