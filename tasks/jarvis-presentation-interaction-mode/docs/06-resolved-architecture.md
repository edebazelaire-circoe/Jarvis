# 06 — Resolved Architecture (Slice 00, binding)

Status: binding. Written for the Project Manager after the blind audit (`slices/00-project-manager/BLIND-AUDIT.md`), with every reference below re-checked at `5378eb6`. **Where this document and docs 00–05 or any SLICE.md body disagree, this document wins.** Every Slice reads its own `## Slice 00 contract (binding)` first. A Work Agent that finds a fact here contradicted by the code stops and reports to the PM. It does not silently follow either side.

Numbering. In this task, the decisions of this handoff's `docs/01-decision-log.md` are written **HD1–HD14**. The code and the `docs/presentation-*.md` pages cite the **2026-09** decisions `D01–D14` (`jarvis/domain/presentation_policy.py` `LOCKED_DECISIONS`). These are different lists. Code comments are not renumbered (A1). The mapping is in R1.

## R0 — Canonical owners (evidence, file:line)

| Concept | Owner / API | Evidence |
|---|---|---|
| Interaction mode vocabulary | `InteractionMode{assistant,presentation,meeting}`; `DEFAULT_INTERACTION_MODE=ASSISTANT`; `behaving_interaction_mode` | `jarvis/domain/interaction_mode.py:52,120,230` |
| Live mode (Core) | `InteractionModeService.request` / `add_listener`; event `interaction.mode.changed` | `jarvis/core/interaction_mode.py:174,245,317,61` |
| Per-Board persistence | `work_boards.interaction_mode` + origin; Board kind is metadata only | `docs/boards.md:198-217,714-745` |
| Voice mode copy | `InteractionModeObserver` (epoch+revision guard), built per process | `runtime/interaction_mode_observer.py:49`; `runtime/voice_v2.py:137,218-220` |
| Voice mode feed | **only** `SpeechScheduler.handle_core_event` and `_resync_interaction_mode` | `speech_scheduler.py:1610-1614,1912`; the scheduler is created in `activate()` (`voice_v2.py:561`, ~730-750) and dropped on mute (`voice_v2.py:1209-1211`) |
| Brain mode hint | `_turn_context(interaction_mode)` → `BRIEF_PRESENTATION_MODE` | `adapters/control_center_brain.py:100,158-159`; `runtime/control_center.py:612,786,814` |
| Mode HUD | bottom-left selector driven by the `/api/status` poll | `runtime/control_center_interaction_mode.js`; `control_center.py:2015,2092` |
| Composition root | `_presentation_composition` → `PresentationComposition.build`; `PresentationCoordinator` | `app.py:730-836,1208-1229`; `presentation_runtime.py:1349,1400,906` |
| Legacy precondition | refuses entry when `voice.continuous` is False | `app.py:1224-1228`; `presentation_runtime.py:1145` |
| Mode application | `observe_mode` → `_drain` → `apply` (fresh stack per entry) | `presentation_runtime.py:999,1022,1038` |
| Explicit address | `ExplicitAddressLane`; sources `wake_word`, `manual_key`; router arms the window | `domain/explicit_address.py:46-50`; `runtime/explicit_address_lane.py:229,265`; `presentation_runtime.py:569,714-734` |
| Wake detection during an ACTIVE session | spoken wake **suspended**, manual key **kept armed** | `adapters/wakeword_shared_pcm.py:337-347`; `adapters/wakeword_keyboard.py:58-62` |
| Addressed window | 1.5 s preroll + 12 s, **one turn per window**; `open()` refuses with no window | `domain/presentation_addressed_turn.py:100,119,233`; `core/presentation_addressed_turn.py:421,446,608,626-629` |
| Ambient lane | `AmbientIngestionLane`: tail via `store.observe` before enrichment; ≤4 triggers per utterance | `runtime/ambient_lane.py:356`; `domain/ambient_observation.py:76` |
| Realtime routing (gap) | `ConservativeAddressingClassifier`: engaged + short/“?”/follow-up → ADDRESSED; not engaged → UNCERTAIN, routed to the brain | `realtime_audio.py:244-279,4536,4580-4611,4691` |
| Brain turn submit | `_submit_brain_turn` (correlation from `_brain_correlation_id`) → `LocalCoreClient.submit_brain_turn` → `POST /v1/conversations/{id}/brain-turns` → `BrainTurnInput` | `realtime_audio.py:2396,2414,2456`; `protocol/client.py:293`; `protocol/server.py:142,518`; `domain/v2.py:646` |
| Addressed turn classified **after** submit | bridge `_note_addressed_turn` → `SpeechScheduler.note_addressed_turn` → `turns.open()` | `realtime_audio.py:4084,4719`; `speech_scheduler.py:719-760` |
| Brain context | `BrainContext` aggregate (optional blocks) built in `_call_backend`; serialized by `_turn_context` | `domain/brain_context.py:823`; `core/brain_service.py:1727,1750-1751`; `adapters/control_center_brain.py:100` |
| Room speech → brain (existing) | `BrainSessionContext.transcript_tail` under `BRIEF_AMBIENT_RULE`; masked in trace by `mask_room_text` | `domain/brain_context.py:735,768`; `runtime/session_context_brief.py:63,75,176,208`; `runtime/claude_local.py:1365` |
| Projection (unwired) | `AddressedTurnContext.to_brain_context()`; ASK_BRAIN trace `context_projected: False` | `domain/presentation_addressed_turn.py:434`; `core/presentation_addressed_turn.py:777-794` |
| Working set | caps and age bounds; store `observe/prune/apply/use_resource`; prune called only by the lane | `domain/presentation_working_set.py:90-176,213,247`; `core/presentation_working_set.py:180,351,424,458,541`; `ambient_lane.py:1083` |
| Unused Core store | `V2App.presentation_working_set` (no producer) | `core/v2_app.py:131-132`; `docs/interaction-mode.md:388-395` |
| Speculative lane | capabilities/tools; ambient cannot stage; pool 8, reserve 2; trigger table | `domain/presentation_speculative.py:183-219,404,408,550`; `core/presentation_speculative.py:376,393-403,619,647,673,1144` |
| Preparation runner | restricted `ClaudeLocalAgent`; CLI tools ∩ `CLI_GRANTABLE_TOOLS` | `runtime/presentation_preparation.py:205`; `claude_local.py:294,1355-1361` |
| Stager | `HiddenSceneStager` protocol → `LedgeredSceneStager` → `DisplaySceneStager` | `core/presentation_speculative.py:222-235`; `presentation_runtime.py:287,1487-1494`; `presentation_staging.py:63` |
| Scene tools | `SceneDisplayTools.create_object(visibility=)`, `update_object(visibility=)`, `archive`; **no `set_visibility`** | `runtime/display_mcp.py:726,805,863,986`; `tests/unit/test_mcp_catalog.py:146-147` |
| Speech manifestation | `PresentationSpeechGate.admit` is enforced in `_enqueue`; withheld → trace only, no mouth event | `presentation_speech_gate.py:117,214`; `speech_scheduler.py:2356,2371-2373` |
| Attention | `decide_attention`; `PresentationAttentionService` (trace `presentation.attention.*`); `BackgroundEventLedger.attention_digest` → card; `bgCue` single emitter, attention = failure tone | `domain/presentation_attention.py:496`; `core/presentation_attention.py:127,164,321`; `runtime/background_events.py:418`; `control_center.html:1493,1544,1573` |
| Canonical timeline | closed types; `_SPECS`; attribute allowlist; adding a type is a contract change; mouth span rule | `domain/conversation_events.py:97-125,146,191,223`; `docs/conversation-events.md:204,514-533,813` |
| Voice event recorder | `ConversationEventForwarder` (sync `record`, never raises), built before the coordinator | `runtime/conversation_event_forwarder.py`; `app.py:1163-1169` |
| Voice→CC status channel | `VisualSignalBus` atomic files (e.g. `.voice_capture`) read by CC `/api/status` | `runtime/visual_signals.py:55`; `control_center.py:3169` |

## R1 — Handoff decisions vs repository (exists / gap / owner Slice)

| HD | 2026-09 equiv. | Exists | Gap → Slice |
|---|---|---|---|
| HD1 separate foundation | — | separate tasks | prefab not on main → **09 DEFERRED** |
| HD2 mode ≠ voice arch | D01, D02 | same mode on every continuous arch; legacy refused by precondition | Voice sees mode only while a session is ACTIVE; legacy refusal never fires (observer never moves) → **02** |
| HD3 ambient has no authority | D03 | lane structurally separate (`authorizes_actions=False`, import guard); `BrainTurnInput` refuses AMBIENT | realtime path in an ACTIVE session routes room speech as ADDRESSED/UNCERTAIN → **04** |
| HD4 explicit address wins | D04, D05 | arm preempts speculative (`core/presentation_addressed_turn.py:552-570`); reserved slots | spoken wake suspended in an ACTIVE session → vocative rule **04** |
| HD5 fresh vs enriched | D06 | tail written before enrichment; projection built | projection never transported; deaf lane never prunes → **05** |
| HD6 background bounded | D07, D08 | pool + preemption + timeouts | 6+2 sub-agents on a 15.6 GB host; unreachable capabilities → **06**; invisible in timeline → **10** |
| HD7 manifest conservative | D09 | `AMBIENT_OBSERVATION` silent; policy matrix validated at construction | — |
| HD8 visual commands silent | D09, D10 | gate withholds; preamble off | `reveal` broken in production → **01** |
| HD9 questions may speak | D10 | gate admits | answer lacks room context → **05** |
| HD10 discreet contradictions | D11 | judge + card + `bgCue` | same tone as failure → **10** |
| HD11 Tool Brain owns UI | D12 (partly) | no Tool Brain in code (audit §7) | semantic intent + sink port → **07**; adapter → **08 DEFERRED** |
| HD12 Scene/Prefab visuals | D12 | stager via `SceneDisplayTools` (`artifact`) | prefab windows → **09 DEFERRED** |
| HD13 recording orthogonal | D13 | memory-only ambient; recording never counted (`audio/input_ownership.py:26`) | trace leaks: `voice.transcript` full text in PRESENTATION (`realtime_audio.py:4556`) → **04**; Issue 002 (`:4565-4568,:4621-4624`) → **11** |
| HD14 canonical observability | — (2026-09 D14 = SIMPLE regression boundary, still binding) | trace only | → **10** |

## R2 — Agent 0 decisions (binding; each "decided by agent 0", Human delegated autonomy)

- **A1** Consolidation of the merged 2026-09 code, not greenfield. Slices are re-scoped to the R1 gaps. Existing contracts are preserved; nothing is renamed or rewritten for symmetry.
- **A2** Tool Brain is in Drive to-do with no code. Scene/prefab is complete on its branch but not merged. **Slices 08 and 09 are DEFERRED**, with entry conditions in R5. Slice 11 lists their acceptance items as deferred.
- **A3** Slice 07 adds a semantic `PresentationOutputIntent` and a `PresentationDisplaySink` port. The one adapter today is the direct scene path. Tool Brain later replaces the adapter, not the policy.
- **A4** The reveal regression is fixed in Slice 01 with `update_object(object_id, visibility="visible")`. A contract test makes fakes unable to hide drift. Stale `scene_set_visibility` comments are fixed. The reconciliation doc is written.
- **A5** Slice 04 closes the authority gap structurally (rule in R3/P2). SIMPLE is unchanged.
- **A6** Slice 05 transports a bounded presentation context on the brain-turn path. It is absent in SIMPLE (byte-identical) and never reaches durable sinks. It reconciles with `transcript_tail`/`BRIEF_AMBIENT_RULE`. The deaf-pruning gap is fixed.
- **A7** Default speculative pool is 2 + 1 reserved, configurable. Unreachable capabilities are documented. Named visual commands are resolved through Slice 05's projection, not a lexical matcher (P5).
- **A8** Slice 10 emits into the canonical timeline (withheld speech, `subagent.*`, mode, attention). `stats()` is exposed in `/api/status`. A distinct softer cue goes through the single `bgCue`.
- **A9** Slice 11 = deterministic scenario suite + privacy hardening, including Issue 002. Issue 001 is out of scope.
- **A10** 02 and 03 are small. Board kind `presentation` stays metadata.
- **A11** Task Types are waived; `task_type: null` stays.
- **A12** QA tiers are as in `slices/TODO.md`. Mutation testing runs only on critical tiers (04, 05, 11), ≤10 mutants, in the foreground.

## R3 — Planning decisions taken in Slice 00 (binding unless agent 0 overrides)

- **P1 — Process-lifetime mode follower (02).** Voice gets a mode feed that lives as long as the process, on every architecture. It subscribes to `core.events()` (`protocol/client.py:656`), filters `interaction.mode.changed`, and calls `adopt(core.interaction_mode())` (`client.py:521`) on each (re)subscription. The scheduler's own feed stays; double delivery is harmless under the observer's epoch/revision guard. Consequences: PRESENTATION entry, and the legacy refusal, happen at the mode change, not at the next wake. The docs' "Known limit" (`docs/interaction-mode.md:446-451`) is retired.
- **P2 — Brain-turn authority in PRESENTATION (04).** While a live PRESENTATION session exists (`PresentationCoordinator.turns` is not None), a complete transcript may reach the brain, or direct admission, **only if** one of these holds:
  - **(a)** It falls in an armed, unexpired explicit-address window (wake word or manual key). The window serves exactly one turn (`core/presentation_addressed_turn.py:619-622`).
  - **(b)** It is a vocative address: after the classifier's normalization it *starts with* `jarvis` (`realtime_audio.py:266-269`). Rationale: in an ACTIVE session the spoken wake detector is suspended, so the transcript is the only evidence of a spoken address. It also keeps `jarvis mute` working. A mention elsewhere in the sentence (`mentions_jarvis`) is **not** an address.

  Everything else, including UNCERTAIN and engagement-based ADDRESSED, becomes `ambient`: no brain turn, no `on_addressed`, no admission. **No implicit follow-up rule in V1.** Answering `CLARIFICATION_TEXT` (`speech_scheduler.py:120`) needs a new trigger or a vocative; this is accepted and checked at HV-E2E. With no live session (SIMPLE, failed entry, legacy refusal) routing is byte-identical to today.
- **P3 — Open before submit (04).** The bridge computes the correlation (`_brain_correlation_id`), then calls `turns.open(text, correlation_id)` **before** `_submit_brain_turn`:
  - Refusals `addressed_no_window`, `addressed_window_expired` and `addressed_speech_outside_window` mean "not authorized" (unless P2b).
  - Any other refusal means authorized without a plan.
  - The plan is handed to `SpeechScheduler.note_addressed_turn(..., plan=)`, which must not open again.
- **P4 — Transport shape (05).**
  - Domain: `BrainPresentationContext` lives in `domain/brain_context.py`, is built from `to_brain_context()`, and is bounded by `MAX_ADDRESSED_CONTEXT_CHARS`. `BrainTurnInput.presentation_context` is optional and never persisted. `BrainContext.presentation` is optional.
  - Wire: `submit_brain_turn(..., presentation_context=None)`. The body key is added **only when given**. The server validates it (400 when invalid). Duplicates do not reapply it.
  - Brief: `_turn_context` emits `context["presentation"]` only when present. The brief is rendered by a new `runtime/presentation_brief.py` under `BRIEF_AMBIENT_RULE`. `mask_room_text` learns its header.
  - The session-context `transcript_tail` is untouched; both tails may render, each under the ambient rule.
- **P5 — Named visual commands (05).** `prepared_resources` in the projection carry `object_id` for `SCENE_OBJECT` resources and the plan's `action`. The brain can then reveal a named, already-prepared object with the existing `scene_update_object(visibility="visible")` (`display_mcp.py:2481-2497`), and knows when the runtime already showed one (`show_prepared`). Accepted limit: a brain-side reveal bypasses `use_resource` accounting.
- **P6 — Timeline vocabulary (10).**
  - Withheld speech → existing `mouth.speech.superseded`, `reason=presentation_withheld`. This follows the precedent `superseded_on_arrival` (`speech_scheduler.py:2401-2405`) and the doc rule for closes of never-attempted speech (`docs/conversation-events.md:528-533`).
  - Preparation jobs → existing `subagent.started/finished/failed/stopped`:
    - producer `voice.presentation`, `task_id` = job id;
    - `conversation_id` = the live Voice conversation, read lazily (explicit binding, not inference — `docs/conversation-events.md:813`);
    - content = capability label only, never room text.
  - **New types** (contract change per `docs/conversation-events.md:204`: enum, `_SPECS`, doc table, tests together):
    - `system.mode.changed` and `system.attention.raised|cleared`;
    - instant, diagnostic, content forbidden;
    - attributes from the existing allowlist only (`kind`, `source`, `reason`, `revision`, `code`).
- **P7 — Status channel (10).** The coordinator publishes scalar stats through `VisualSignalBus.presentation(report)` → `.voice_presentation`. It writes on enter, leave, refusal and blockers, and on each diagnostics tick. CC `/api/status.presentation` reads it the way it reads `.voice_capture`, and returns `null` when Voice is offline.
- **P8 — Order.** Slice 03 renders P7's block, so it runs **after** Slice 10.
- **P9 — Numbering.** HD vs D, as stated in the preamble.
- **P10 — PRESENTATION ambient segments leave no text in the trace (04).** On the P2-ambient branch, `voice.transcript` carries `chars` and `addressing="ambient"` only. SIMPLE is unchanged until Slice 11 (Issue 002).
- **P11 — PRESENTATION is refused on DUPLEX (04, decided by agent 0).** GPT-Live answers on its own and emits no final transcript to the bridge (`live_frontend_session.py` `_legacy_events`), so P2 has no point of application and the speech gate never sees its audio. `presentation_architecture_refusal` (`presentation_runtime.py`) refuses entry next to the legacy refusal: code `presentation_architecture_unsupported`, reason `duplex_autonomous_output`, one alert, no microphone. Supported: `continuous_brain`, SIMPLE, FRONT_BRAIN.
- **P12 — Direct-path order (04, decided by agent 0).** On SIMPLE/FRONT_BRAIN direct sessions Core assigns the turn identity at admission (`admission_correlation_id`). Authority is decided **before** admission by the non-consuming `PresentationAddressedTurnService.window_live()` (or the vocative); the turn is opened **after** admission under Core's accepted correlation, before the answer is requested. P3 stays as written on the brain-turn path.

## R4 — Module boundaries of the new pieces

| Piece | Layer / file | Rule |
|---|---|---|
| Authority predicate | `domain/presentation_addressed_turn.py`: `is_vocative_address(text)` plus `TurnAuthority{explicit_address, vocative_address, ambient}` | pure, no I/O |
| Bridge hook | `RealtimeConversationBridge(presentation_turns=callable|None)`; checked in `_handle_admitted_transcript` before UNCERTAIN, admission and submit | wired in `voice_v2.py` from `self.presentation_turns`; `None` ⇒ today's code path |
| Mode follower | `runtime/interaction_mode_observer.py`: `follow_core_mode(observer, core, journal)` task, owned by `PersistentVoiceRuntime.run` | never raises; backoff; one line per outage |
| Context transport | domain `BrainPresentationContext`; protocol client/server; core `brain_service._call_backend`; adapter `_turn_context`; runtime `presentation_brief.py` | core never imports runtime (`tests/unit/test_v2_architecture.py`) |
| Output intent | `domain/presentation_intent.py`: `PresentationOutputIntent{situation: PresentationSituation, disposition: OutputDisposition, display: DisplayIntent|None, urgency: IntentUrgency, reason: str, context_refs: tuple, correlation_id}`; `DisplayIntent{semantic: DisplaySemantic, resource_refs}`; `authorizes_actions=False` | reuse `PresentationSituation`/`OutputDisposition`/`SpeechKind`; no new speech enum. Handoff `kind`→`situation`, `speech`→`disposition` + policy speech ceiling |
| Display sink port | `core/presentation_display.py`: `PresentationDisplaySink` Protocol `publish(intent) -> DisplayReceipt`, `withdraw_speculative(reason) -> int` | consumer-owned port, like `HiddenSceneStager` |
| Direct adapter | `runtime/presentation_display_sink.py`: `DirectSceneDisplaySink(speculative)` → `speculative.reveal(resource_id)` → stager → `SceneDisplayTools.update_object` | `withdraw` = 0 (nothing queued), said in trace |
| Timeline emission | `runtime/presentation_timeline.py`: adapter from speculative/attention/coordinator lifecycle → `ConversationEventRecorder` | core services take an optional lifecycle port; `record()` sync, never raises |
| Status file | `VisualSignalBus.presentation`; `ControlCenter._presentation_report` | scalars only, no text |

## R5 — Deferred Slices: entry conditions

- **08 Tool Brain.** Entry condition: `jarvis-tool-brain-ui-orchestrator` is merged on `main` **and** exposes a public intake for semantic UI intents with cancellation. Binding:
  - one `ToolBrainDisplaySink` implementing `PresentationDisplaySink`, swapped in `PresentationComposition.build`;
  - `withdraw_speculative` maps to Tool Brain cancellation;
  - no change to `presentation_intent.py` semantics beyond additive fields;
  - D11/HD11 trace assertion "UI action came through Tool Brain".
- **09 Scene/Prefab.** Entry condition: `task/jarvis-scene-window-prefab-foundation` is merged on `main`, and `docs/prefabs.md` › *Consumers (Presentation seam)* is present there with its conformance test green. Binding:
  - `DisplaySceneStager.stage_hidden` gains an optional `prefab` → `create_object(kind="window", visibility="hidden", prefab={…})` for DOCUMENT/DATASET/CHART_DESCRIPTOR resources;
  - reveal unchanged (P4/A4);
  - merge `BrainContext.prefab_events` with `BrainContext.presentation` (both additive);
  - record the prefab Issue `presentation-stager-reveal-calls-missing-set-visibility` as resolved by Slice 01 here.

## R6 — Inherited limitations (stated, not fixed here)

1. The addressed classifier is French-only and lexical (`domain/presentation_response.py:144`).
2. Provenance eviction race in the 12-source ring (`presentation_runtime.py:850-876`).
3. A lost or corrupt staged-object ledger leaks; overflow beyond 16 ids is only logged (`presentation_runtime.py:231-246`).
4. The Core `presentation_working_set` has no producer and is retained (`core/v2_app.py:131-132`).
5. Ambient transcription exists only on an OpenAI stack (`app.py:772-785`); otherwise the lane is deaf.
6. The attention card still reads the trace via `BackgroundEventLedger`; the canonical events are added beside it (P6). The trace stays diagnostic.
7. Preparation sub-agents are not `CoreWork`/`AgentTaskTracker` items (deliberate); visible in the timeline only.
8. A CLARIFY answer needs a new address (P2).
9. A brain-side reveal bypasses `use_resource` (P5).
10. Out of scope: Issue 001 (settings read) and Issue 003 (release verifier, `barehands_replay.py:144`).
11. No workstation validation yet; the HV checks are the first contact.
12. In PRESENTATION the manual key **arms an address window** instead of stopping the session (Slice 04 deviation, accepted by agent 0). "Stop" remains available by voice barge-in and "Jarvis mute".
13. A pending confirmation needs "Jarvis, oui" or a key press while a session is live: a bare "oui" is room speech (P2).
14. F5 — direct path (P12): a window that expires during admission still lets that turn be answered, without a plan (authority was decided before admission by `window_live()`).
15. F7 — during the ~1.2 s PRESENTATION entry period, and after a failed entry, routing is SIMPLE's: no live session exists yet (or any more) to apply P2.
16. The vocative is **prefix-only** (`is_vocative_address`): "Hé Jarvis, …" or "OK Jarvis …" is not an address; only a sentence that starts with "Jarvis" is.
17. B1 (Slice 05 QA) — the brain's `conversation` profile runs the Claude CLI with `--resume` and session persistence: the brief, room speech included, is written to the CLI's own session log and stays in the model's history beyond the 180 s bound and after the return to SIMPLE. Same accepted limit as the Session context's `transcript_tail` (`docs/session-context-capture.md`).
18. B2 (Slice 05 QA) — a brain answer that quotes room speech is persisted like any answer (Core state, Conversation Events, `agent.event` in the trace).

## R7 — Overrides of docs 00–05 and SLICE bodies

1. README "previous task deleted, not canonical": its **code is on main** and is repository reality (A1).
2. Doc 02 §2 authority labels: realized as the existing `UtteranceOrigin{ambient,addressed}` (`domain/presentation_working_set.py:213`) plus P2 `TurnAuthority`. No `system/runtime` origin is added; runtime events are not speech.
3. Doc 02 §7 intent shape: names reconciled per R4. There is no `speech: concise|normal` enum.
4. Doc 03 step order: 03 runs after 10 (P8). 08 and 09 are deferred (A2).
5. SLICE 01 "docs + minimal scaffolding" → small code + docs (A4).
6. Doc 05 levels are replaced by the per-Slice "Documentation" lines in each contract.
7. README Task Types: waived (A11).

## R8 — Human checks

| New id | Slice | Supersedes (2026-09, all open) |
|---|---|---|
| HV-PRESENTATION-MODE-UI-01 | 03 | HV-PRES-MODE-01 |
| HV-PRESENTATION-ATTENTION-01 | 10 | HV-PRES-ALERT-01 (now with the distinct cue) |
| HV-PRESENTATION-E2E-01 (last) | 11 | HV-PRES-AUDIO-01 (one mic owner), HV-PRES-SPEECH-01 (silence on visual commands, on the live continuous architecture), HV-PRES-PRIORITY-01 (addressed turn responsive under ambient load), HV-PRES-E2E-01 |

Slice 11 amends the E2E-01 instruction to name those three sub-checks. Agent 0 records the supersession in this task's LOG; the 2026-09 archive gets at most a pointer line.
