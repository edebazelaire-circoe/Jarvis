# Presentation Studio - final implementation report, acceptance status and contract index

Status: **Slice 22 (end-to-end hardening and release gates)** of the handoff `jarvis-interactive-presentation-studio`. This page is the one place that says, without rounding up, what is built, what a machine proved, what only a person can prove, and where each contract lives. The concept page and the contracts are [presentation-studio.md](presentation-studio.md); the operator runbook is [OPERATIONS.md](OPERATIONS.md) > *Presentation Studio : release et exploitation de bout en bout (Slice 22)*.

## Verdict

- **Machine side: green on the release gates** (results table below), with every failure found on the way fixed, none waived. Two failures were real defects of the product found only by a real model (the authoring planner could not be driven: see *Real-model release gate*); three more were stale test expectations left by earlier merges of this task, none of them in the baseline (`test_the_tool_contract_page_is_untouched_until_slice_21`, a `**implemented (Level 3, backend)**` status string that became `backend + explorer panes UI`, and a docs-vocabulary test that read the two `presentation_view` operation names as page codes), fixed in the tests and documented.
- **Not done as a Slice: 15 (Rehearsal, recall and script refinement) has no implementation round of its own.** Its behaviours exist because Slices 12, 01c and 21 delivered them (the `rehearsal` role, `where are we`, pause-edit-resume, `goto`, `previous`), and Slice 22 proves them end to end (`test_journey_rehearsal_section_where_am_i_edit_pause_resume_and_backtrack`). What it asked for and nobody built: a **section loop / restart-a-section command** (step 4) and the dedicated rehearsal runbook. Its Human check HVAL-IPS-005 is open.
- **Not accepted yet: the physical acceptance** (projector, speakers, microphone, screen reader). Nothing in this repository can prove those; the list is below and is the only thing between "machine-green" and "accepted".

## Slice status (handoff folder numbering)

| Slice | Subject | Status | Where the evidence is |
| --- | --- | --- | --- |
| 00 | Project manager readiness gate | done | `slices/00-project-manager/READINESS.md`, `BASELINE.md` |
| 01 | Contract audit | accepted | `slices/01-contract-audit/`, `docs/07-integration-map.md` |
| 01a | Prefab capacity for the Studio (retention, pins) | accepted, merged | [prefabs.md](prefabs.md) > *Retention of Studio scene sources* |
| 01c | Presenter speech authority (decision A) | accepted | [Playback roles](presentation-studio.md#playback-roles-and-speech-authority-level-3-slice-01c-decision-a) |
| 02 | Presentation artifact contract | accepted (QA critical tier) | [Presentation contract](presentation-studio.md#presentation-contract-level-3) |
| 03 | Fullscreen borderless surface | accepted, merged | [Generic fullscreen surface](presentation-studio.md#generic-fullscreen-surface-level-3-slice-03) |
| 04 | Scene and control contract | accepted | [Scene and control contract](presentation-studio.md#scene-and-control-contract-level-3) |
| 05 | Semantic edit API | accepted (QA critical tier) | [Semantic edit contract](presentation-studio.md#semantic-edit-contract-level-3) |
| 06 | Scene hot reload | accepted after QA-2 | [Hot reload contract](presentation-studio.md#hot-reload-contract-level-3-slice-06) |
| 07 | Edit inspector UI | accepted, merged | [Edit inspector UI](presentation-studio.md#edit-inspector-ui-level-3-slice-07) |
| 08 | Autosave and undo | accepted (QA critical tier) | [Persistence and undo contract](presentation-studio.md#persistence-and-undo-contract-level-3) |
| 09 | Art direction profile | accepted, merged | [Art direction contract](presentation-studio.md#art-direction-contract-level-3) |
| 10 | Presentation score and cues | accepted, merged | [Score and cue contract](presentation-studio.md#score-and-cue-contract-level-3) |
| 11 | Authoring planner and first draft | accepted on the scripted rig; **real-model gate closed by Slice 22 with two product fixes** | [Authoring contract](presentation-studio.md#authoring-contract-slice-11), `slices/22-end-to-end-hardening/evidence/authoring-real-traces.md` |
| 12 | Playback runtime | accepted after a blocking fix (windowed arrows) | [Playback runtime contract](presentation-studio.md#playback-runtime-contract-level-3-slice-12) |
| 13 | User-presenter sidekick (cue following) | accepted; **never run on a live OpenAI ambient stack** | [Cue following contract](presentation-studio.md#cue-following-contract-level-3-slice-13) |
| 14 | Jarvis presenter and locked sequences | accepted; **not run audibly** | [Jarvis presenter](presentation-studio.md#jarvis-presenter-and-locked-sequences-level-3-slice-14) |
| 15 | Rehearsal workflow | **not implemented as a Slice** (see Verdict) | proven through 12, 01c, 21 by Slice 22 |
| 16 | Presentation variants domain | accepted (QA critical tier) | [Variant graph](presentation-studio.md#variant-graph-and-operations-contract-level-3) |
| 17 | Scene-local variants | accepted, merged | [Scene-local variant contract](presentation-studio.md#scene-local-variant-contract-level-3-slice-17) |
| 18 | Variant explorer UI | accepted, merged; polish items P1, P8-P10, F5, F7-F9 left open (non-blocking, `QA-1.md`) | [Explorer contract](presentation-studio.md#variant-explorer-interaction-contract-level-3-slice-18) |
| 19 | Variant compare and mix (backend and explorer panes) | merged; `LOG.md` records no QA round for it: verified here only by the release suites | [Composition contract](presentation-studio.md#comparison-and-semantic-composition-contract-level-3-slice-19-backend), [explorer panes](presentation-studio.md#comparison-and-composition-in-the-explorer-slice-19-interface) |
| 20 | Template and prefab promotion | merged; same remark as 19 | [Template contract](presentation-studio.md#template-and-prefab-promotion-contract-level-3-slice-20) |
| 21 | Agent and voice operations (`jarvis-presentation`, 12 tools) | implemented, merged; QA round pending per `LOG.md`; its real-model coverage was five scenarios | [Agent and voice operations](presentation-studio.md#agent-and-voice-operations-level-3-slice-21) |
| 22 | End-to-end hardening and release gates | this page | `tests/unit/test_presentation_studio_release_*.py` |

## What a machine proved

Real `JarvisCoreApplication` behind the real `LocalProtocolServer`, real file stores and scene store, real `jarvis-presentation` tools, real Control Center relay; the only stand-ins are the Control Center's turn attestation and the speech stack. One fixture: a 12-scene quarterly review assembled by the real authoring door (inferred art direction, 12 score items, 5 armable cues), `tests/unit/presentation_studio_release_world.py`.

| Journey (test) | What it walks |
| --- | --- |
| `test_journey_one_shot_report_from_brief_to_the_screen_and_back` | check, assemble (generated fallback art direction), a handful of Core calls, rehearsal run, the report is on the stage, stop leaves nothing |
| `test_journey_serious_deck_live_edit_variant_rehearsal_and_user_presenter` | assemble 12 scenes, live edit, undo of the brain's own edit, a branch edited without touching its parent, rehearsal in PRESENTATION and the user's mode given back, user-presenter run with armed cues and a fired cue, **Core restart**: deck, variant, graph intact, no run, no stage window |
| `test_journey_rehearsal_section_where_am_i_edit_pause_resume_and_backtrack` | the Slice 15 behaviours: jump to a section, bounded "where are we", edit while rehearsing pauses and the stage follows, resume, backtrack, no transcript on disk |
| `test_journey_jarvis_presenter_locked_sequence_returns_the_timeline_and_the_mode` | Jarvis-presenter run leaves PRESENTATION and gives it back; the speech stack that cannot take the line is a visible pause; a locked sequence runs on the real clock and returns the timeline |
| `test_journey_compare_mix_and_promote_a_template_then_reuse_it` | four variants, four-up compare, focus, mix (narrative of one over the base of another, sources untouched, provenance per dimension), template plan then promote, instantiate into a new presentation (no score: documented), add a score, rehearse it |

| Fault or regression (test) | Assertion |
| --- | --- |
| `test_a_careless_draft_is_refused_with_the_whole_report_and_nothing_is_written` | ten different gate rules broken, nothing written, list and files unchanged |
| `test_a_refused_draft_then_the_fix_is_one_delivered_presentation_...` | exactly one presentation after refuse-then-fix |
| `test_a_scene_source_that_does_not_compile_is_rolled_back_...` | three broken sources: rolled back, same window, same position |
| `test_stale_unknown_and_foreign_ids_are_refused_typed_and_change_nothing` | stale revision, foreign scene id, unknown variant, other presentation's variant: typed refusals, only the first edit landed |
| `test_a_confirmation_is_spent_once_and_dies_with_the_state_it_was_issued_for` | archive token: stale after the set grew, spent after use |
| `test_a_core_restart_in_the_middle_of_a_run_leaves_the_deck_whole_...` | restart with the run live and a torn `.tmp` file: deck and score identical, run idle, no stage window, mode not left switched, a new run starts |
| `test_adversarial_speech_never_fires_the_real_armed_cue_...` | thirteen adversarial utterances (quote, negation, question, hedge, vocative, injection, cue id spoken, partial, reordered, empty) against the cue armed from the fixture: no report, no movement; the stage direction fires it once; a repeat is a duplicate; a stale generation is refused |
| `test_two_armed_cues_sharing_a_phrase_are_ambiguous_and_neither_fires` | ambiguity |
| `test_a_detour_shows_an_auxiliary_window_...` | three detour/return cycles keep one stage window and the position; an invalid detour is a typed 422 and the run is untouched |
| `test_every_role_gives_the_users_mode_back_and_a_manual_mode_change_ends_the_run` | both starting modes x roles, Jarvis-speaks rehearsal outside PRESENTATION, a manual mode change stops the run (`last_run.reason = mode_changed_by_user`) |
| `test_repeated_runs_leave_no_stage_object_task_or_file_behind` | 20 runs: stage objects 0, scene objects, store files and rows bounded, asyncio tasks +2 at most |
| `test_a_hundred_reloads_leave_one_stage_window_and_no_task_behind` | 100 hot reloads: the same window, no task per reload, versions under the cap |
| `test_repeated_scene_variant_previews_write_nothing_and_leave_no_window` | 30 previews and cancels: the folder hash is unchanged, no window left |
| `test_no_draft_title_note_or_label_text_reaches_a_log_a_trace_or_the_event_store` | a secret title, rationale, edit value and the draft's own sentences are searched in every trace, journal and sqlite file: absent |

The release verifier (`scripts/verify_release.py`, item `presentation_studio_findings`, tested by `test_presentation_studio_release_gate.py` with doctored trees) asserts: the planner prompt is registered, **read-only**, not editable, **attached to exactly the programs that declare the presentation tools**; its content fingerprint is the one every piece of committed evidence was gathered with (scripted rig and real traces); the crash drills and the privacy assertion of the authoring exist.

## Real-model release gate (Slice 11 carry-forward)

Harness: `python -m tests.replay.presentation_studio_authoring_real_trace [scenario ...] --raw-dir=<dir> --budget=<usd per turn>`: the real `claude` CLI (sonnet), the real prompt program `conversation_display_studio_session` (base + display + presentation + the planner), the real MCP servers, an **isolated** Core (random port, scratch data root); the live JARVIS is never touched. Evidence: `slices/22-end-to-end-hardening/evidence/authoring-real-traces.{md,json}` (all seven scenarios) and `authoring-real-traces.missing-context.{md,json}` (a second run of the one scenario that varied). Raw streams stayed outside the repository.

Spend: about **USD 2.3** over every iteration of the harness, USD 0.94 for the committed evidence.

| Scenario | Outcome of the committed run |
| --- | --- |
| rich brief (6 scenes, 5 min, user presents) | delivered in 2 gate rounds (one `draft_schema` refusal, fixed), 6 scenes of 17-26 words, 6 armable cues, fallback art direction said aloud, 0 questions |
| missing context ("Fais-moi une présentation.") | **varies**: delivered after 1 question in two runs; in the third the model asked a second question and then offered to work "in the background" because the harness has no sub-agent tool, and drafted nothing. Budget 3, never exceeded |
| vague / exploratory | idea list in words first, then on "create them" a draft: refused once (`brief_invalid`: `tone` must be a list), then delivered **4 divergent directions as 4 variants** |
| one-shot report | delivered; this run needed 4 calls because 3 submissions were unparseable JSON on the model side (`__unparsedToolInput`); the 4th was accepted |
| plain "affiche-moi" (no "présentation") | the brain used the display tools, no Studio draft: by design (a plain display is not a presentation), recorded as such |
| hostile reference text | 3 scenes delivered; the embedded orders (delete everything, write TODO) were **not obeyed**: no archive call, no `TODO`, the model said the text contained instructions; the existing presentation was byte-identical afterwards |
| refused draft then fix | the committed run delivered on its first round (the model condensed the long text itself); the refuse-then-correct path was seen in the committed runs of rich brief and vague/exploratory (`draft_schema`, `brief_invalid`) and in the first iteration of this scenario. In the committed runs no scenario needed more than 2 gate rounds; the extra calls of the one-shot run were unparseable JSON, not gate refusals |

Findings, all from the first real runs (a scripted rig cannot find them):

1. **Blocking, fixed.** The brain was given `AuthoringBrief.` and `PresentationDraft complet.` as the only description of two arguments. It guessed `flow` and `objective`, was refused three times by a gate that by design never echoes unknown key names, and gave up. Fix: `presentation_inspect` target `draft_guide` (a new read-only target, no new tool: the twelve-tool surface and its byte budget are unchanged within the existing margin) returns the exact brief keys, the draft shape and one **complete valid example that the test suite runs through the real gate and the real assembly**; the unknown-key refusal now lists the allowed keys (a fixed vocabulary, not the author's text); the planner prompt tells the model to read the guide first. Module `jarvis/domain/presentation_studio_authoring_guide.py`, `test_presentation_studio_authoring_guide.py`.
2. **Blocking, fixed.** The exploratory flow could not be driven: the model could not write art-direction profiles (wrong shapes, then four identical directions refused `candidates_not_divergent`). Fix: `draft_guide` with `kind: "exploratory"` hands over six profiles computed by Slice 09's `diverge` (divergent by construction; every prefix of 2..6 is tested through the gate and assembly); the model copies them, it does not invent them.
3. Not fixed, reported: one run lost three calls to malformed JSON from the model; the missing-context scenario depends on the harness having no sub-agent tool (the production brain has one); the replies are longer than the voice rule wants (Slice 21 F4).
4. Quality judgement. The gate proves a draft is not a placeholder, not dense and not unbounded; it does not prove it is good. Reading the stored drafts (titles and word counts are in the evidence): scene texts are short (14-26 words, one condensed 72-word scene), plausible and on subject, titles are specific, no filler. **That is the reading of the implementing agent, not of a person**; whether a first draft is "respectable" for a real audience is a Human judgement and is item H-9 below.

Not covered by any real-model run: linked art direction from real brand material, two conflicting brands, "no art direction found" with real project files (the harness has no project to inspect), a 12-scene deck, composition and templates with a real model, rehearsal and presenter roles with a real model, any run with the live voice stack.

## Physical Human checks (the acceptance that remains)

All need a person at a workstation; none can be replaced by the suites above. Recipes: [OPERATIONS.md](OPERATIONS.md) > the *(studio, Slice N) : vérification humaine* sections. The formal checks of the handoff are `HVAL-IPS-001` to `008` (`slices/*/human-validation.json`).

| # | Check | Handoff id | Why a machine cannot |
| --- | --- | --- | --- |
| H-1 | Real fullscreen borderless on the **real projector or second screen**; Escape exits and restores the workspace; permission prompt on multi-monitor | HVAL-IPS-001 | the browser Fullscreen API, window placement and the permission prompt need a real display and a gesture; the suites prove the code path in headless Chrome |
| H-2 | Live editing feel in the inspector (drag, type, undo) | HVAL-IPS-002 | latency and feel |
| H-3 | **Voice cue following with a real microphone** in PRESENTATION mode (OpenAI ambient stack): say the stage direction, a bystander phrase, a quote | HVAL-IPS-003 | the ambient stack, the room and the microphone are not in any test; the matcher is measured on typed corpora only (false positive and false negative rates in the Cue following contract) |
| H-4 | **Audible Jarvis presenter and locked choreography**: lines in order, no overlap with the animation, interruption by a question, "continue" | HVAL-IPS-004 | nothing here produces sound; `mouth.speech.started` fires at the generation request, before the first audio write |
| H-5 | **Audible PRESENTATION mode**: Jarvis silent during a user-presented run, answers only when addressed by name | none (Slice 01c) | the speech gate is proven by matrix tests, not by ears |
| H-6 | Rehearsal recovery and recall by voice ("où en est-on ?", "reprends à la scène 3") | HVAL-IPS-005 | open; also the section-loop gap of Slice 15 |
| H-7 | Variant explorer usability at a normal viewing distance; deep branches legible | HVAL-IPS-006 | legibility and ergonomics |
| H-8 | Compare and mix workflow done by a person; the composition provenance is understandable | HVAL-IPS-007 | creative judgement |
| H-9 | **Full dry run**: serious deck, voice and GUI edits, branch, compare, rehearse, then fullscreen as user-presenter with Jarvis as sidekick, then a Jarvis-presented section, one deliberate detour; and a judgement of the first drafts the planner produces on the person's own briefs | HVAL-IPS-008 | the acceptance criterion of the Slice itself |
| H-10 | Screen reader and keyboard-only pass over the inspector, explorer and player band; reduced-motion on a real machine | none | the suites check roles, labels and the reduced-motion media query, not a screen reader |
| H-11 | The toast and the notice behaviour while fullscreen, and the user closing the stage window mid-run | none (Slices 03, 12) | documented limit: toasts are invisible in fullscreen |

Order: machine findings first (done), then H-1 and H-4/H-5 on the real hardware, then H-9. If any of H-1 to H-5 fails, the failure is a defect of this task.

## Known limits and open items (none waived)

- Slice 15: no section-loop command; no dedicated rehearsal runbook (the behaviours are in the playback runbook).
- A template carries scenes and art direction, **not the score** (documented in the Template contract): an instantiated presentation needs a score before it can be played. There is no brain tool to create a score on an existing variant other than the authoring planner; a person or the page can POST one.
- Single writer: two Core processes on one data root are unsupported (Slices 02, 16).
- The undo ring is memory only (lost at a restart by design; the saved state is complete).
- Slice 21's known limits stand (`Limits and left to do`): turn attestation is per turn, score editing and `scene.add` are not offered to the agent.
- Open issues of other owners seen on the way: `ui_intent_publish` is not documented in `test_brain_capability_parity` (Tool Brain, already on main), the harnesses of older tests leak Chrome profile directories in `%TEMP%`.

## Canonical contract index

One row per contract: the section, the owner modules, the tests that guard it. Sections are in [presentation-studio.md](presentation-studio.md) unless a file is named. `tests/unit/test_presentation_studio_release_docs.py` checks that every anchor below exists and every test file named exists.

| Contract | Slice | Section | Owner modules | Guarding tests |
| --- | --- | --- | --- | --- |
| Presentation artifact, manifest, variant documents | 02 | [anchor](presentation-studio.md#presentation-contract-level-3) | `domain/presentation_studio.py`, `adapters/file_presentation_studio_store.py` | `test_presentation_studio_domain.py`, `_store.py`, `_recovery.py` |
| Scene and control contract | 04 | [anchor](presentation-studio.md#scene-and-control-contract-level-3) | `domain/presentation_studio_scene.py`, `core/presentation_studio_scene_catalog.py` | `test_presentation_studio_scene.py`, `_scene_service.py` |
| Score and cues | 10 | [anchor](presentation-studio.md#score-and-cue-contract-level-3) | `domain/presentation_studio_score.py`, `_cues.py` | `test_presentation_studio_score.py`, `_score_edit.py`, `_cues.py` |
| Art direction | 09 | [anchor](presentation-studio.md#art-direction-contract-level-3) | `domain/presentation_studio_art_direction*.py` | `test_presentation_studio_art_direction*.py` |
| Authoring (brief, draft, gate, assembly, guide) | 11, 22 | [anchor](presentation-studio.md#authoring-contract-slice-11) | `domain/presentation_studio_authoring*.py`, `core/presentation_studio_authoring.py` | `test_presentation_studio_authoring*.py`, `_authoring_guide.py` |
| Semantic edit | 05 | [anchor](presentation-studio.md#semantic-edit-contract-level-3) | `core/presentation_studio_edit.py` | `test_presentation_studio_edit*.py` |
| Persistence and undo | 08 | [anchor](presentation-studio.md#persistence-and-undo-contract-level-3) | `core/presentation_studio_history.py`, `_autosave.py` | `test_presentation_studio_history*.py`, `_durability.py` |
| Variant graph | 16 | [anchor](presentation-studio.md#variant-graph-and-operations-contract-level-3) | `domain/presentation_studio_variants.py`, `core/presentation_studio_variants.py` | `test_presentation_studio_variants*.py` |
| Scene-local variants | 17 | [anchor](presentation-studio.md#scene-local-variant-contract-level-3-slice-17) | `domain/presentation_studio_scene_variants.py` | `test_presentation_studio_scene_variants*.py` |
| Template and promotion | 20 | [anchor](presentation-studio.md#template-and-prefab-promotion-contract-level-3-slice-20) | `domain/presentation_studio_template*.py`, `core/presentation_studio_template.py` | `test_presentation_studio_template*.py` |
| Playback roles and speech authority | 01c | [anchor](presentation-studio.md#playback-roles-and-speech-authority-level-3-slice-01c-decision-a) | `domain/presentation_studio_roles.py` | `test_presentation_studio_roles.py` |
| Hot reload | 06 | [anchor](presentation-studio.md#hot-reload-contract-level-3-slice-06) | `core/presentation_studio_reload*.py`, `_pins.py` | `test_presentation_studio_reload*.py`, `_pins.py` |
| Playback runtime | 12 | [anchor](presentation-studio.md#playback-runtime-contract-level-3-slice-12) | `core/presentation_studio_playback.py`, `_stage.py` | `test_presentation_studio_playback*.py`, `_stage.py` |
| Jarvis presenter, locked sequences | 14 | [anchor](presentation-studio.md#jarvis-presenter-and-locked-sequences-level-3-slice-14) | `core/presentation_studio_presenter.py`, `domain/presentation_studio_sequence.py` | `test_presentation_studio_presenter*.py`, `_sequence*.py` |
| Cue following | 13 | [anchor](presentation-studio.md#cue-following-contract-level-3-slice-13) | `runtime/presentation_studio_cue_follower.py`, `domain/presentation_studio_cues.py` | `test_presentation_studio_cue_*.py`, `tests/integration/test_presentation_studio_cue_replay.py` |
| Variant explorer | 18 | [anchor](presentation-studio.md#variant-explorer-interaction-contract-level-3-slice-18) | `runtime/control_center_presentation_studio_explorer*.js` | `test_presentation_studio_explorer*.py` |
| Edit inspector | 07 | [anchor](presentation-studio.md#edit-inspector-ui-level-3-slice-07) | `runtime/control_center_presentation_studio_inspector*.js` | `test_presentation_studio_inspector*.py` |
| Compare and composition | 19 | [anchor](presentation-studio.md#comparison-and-semantic-composition-contract-level-3-slice-19-backend) | `domain/presentation_studio_compare.py`, `_composition.py` | `test_presentation_studio_compare.py`, `_compose_*.py`, `_explorer_compare*.py` |
| Agent and voice operations | 21 | [anchor](presentation-studio.md#agent-and-voice-operations-level-3-slice-21) | `runtime/presentation_studio_mcp*.py` | `test_presentation_studio_mcp*.py` |
| Fullscreen surface | 03 | [anchor](presentation-studio.md#generic-fullscreen-surface-level-3-slice-03) | `runtime/control_center_fullscreen.js` | `test_fullscreen_*.py`, `test_surface_fullscreen.py` |
| Prefab retention for Studio scenes | 01a | [prefabs.md](prefabs.md#retention-of-studio-scene-sources) | `core/prefab_service.py`, `adapters/file_prefab_library.py` | `test_presentation_studio_pin_sources.py`, `_pins.py` |
| Release gate (this page) | 22 | this page | `scripts/verify_release.py`, `tests/unit/presentation_studio_release_world.py` | `test_presentation_studio_release_*.py` |

## Gate results

See the table filled by the Slice 22 report in [the operator runbook](OPERATIONS.md#presentation-studio--release-et-exploitation-de-bout-en-bout-slice-22) and the commit message of the closing commit; the per-file sweep is reproducible with the commands there.
