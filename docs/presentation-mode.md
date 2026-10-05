# Presentation mode — index and owner map

Entry page for everything PRESENTATION. It **holds no contract of its own**: each
row points at the page or module that owns the rule. When this page and an owner
disagree, the owner wins and this page is stale.

Status: Level 2 (index + owner map). The reveal path is Level 3: contract test
`tests/unit/test_presentation_staging_contract.py`. The Voice mode feed is
Level 3: contract in [interaction-mode.md](interaction-mode.md) › *The mode
follower*, tests `tests/unit/test_interaction_mode_follower.py`. The output
intent and display sink are Level 3: contract in
[presentation-response-policy.md](presentation-response-policy.md) › *Output
intent and display sink*, tests `tests/unit/test_presentation_intent.py`.

History: built by the 2026-09 handoff (`jarvis-presentation-interaction-mode-2026-09`,
decisions **D01–D14**); consolidated by the 2026-10 handoff
`jarvis-presentation-interaction-mode` (decisions **HD1–HD14**). The two lists are
different; the mapping is below. Code comments keep citing D01–D14 and are not
renumbered.

## Contract pages

| Page | Owns |
| --- | --- |
| [interaction-mode.md](interaction-mode.md) | the three modes, output disposition, the policy matrix, the control plane (Core service, routes, `interaction.mode.changed`), the Control Center selector |
| [presentation-audio-capture.md](presentation-audio-capture.md) | microphone ownership in PRESENTATION, explicit-address triggers (wake word, manual key) |
| [presentation-ambient-lane.md](presentation-ambient-lane.md) | continuous room speech → recent text, ambient triggers |
| [presentation-working-set.md](presentation-working-set.md) | the session working set and transcript tail, bounds, pruning |
| [presentation-addressed-turn.md](presentation-addressed-turn.md) | the addressed window and turn, its plan, the brain-context projection |
| [presentation-response-policy.md](presentation-response-policy.md) | the situation classifier and the speech gate (silence as success); the output intent and display sink |
| [presentation-speculative-preparation.md](presentation-speculative-preparation.md) | the speculative lane, capability table, hidden staging and **reveal** |
| [presentation-attention.md](presentation-attention.md) | fact-check attention: card, cue, never speech |

Neighbours owned elsewhere: Board persistence of the mode —
[boards.md](boards.md); the canonical timeline — [conversation-events.md](conversation-events.md);
the scene and its tools — [scene-model.md](scene-model.md),
[mcp/tool-contract.md](mcp/tool-contract.md); durable writes and operations —
[OPERATIONS.md](OPERATIONS.md); acceptance — [ACCEPTANCE_STATUS.md](ACCEPTANCE_STATUS.md).

## Owner map

One owner per concept. Reuse it; do not build a second one.

| Concept | Owner (module › symbol) | Contract |
| --- | --- | --- |
| Mode vocabulary | `domain/interaction_mode.py` › `InteractionMode`, `DEFAULT_INTERACTION_MODE`, `behaving_interaction_mode` | [interaction-mode.md](interaction-mode.md) |
| Live mode (Core) | `core/interaction_mode.py` › `InteractionModeService.request` / `add_listener`; event `interaction.mode.changed` | [interaction-mode.md](interaction-mode.md) › Control plane |
| Per-Board mode | `work_boards.interaction_mode` (+ origin); Board kind is metadata only | [boards.md](boards.md) |
| Voice copy of the mode | `runtime/interaction_mode_observer.py` › `InteractionModeObserver` (epoch + revision guard), fed for the life of the process by `follow_core_mode` (owned by `PersistentVoiceRuntime.run`, every architecture); `SpeechScheduler` also feeds it during a session | [interaction-mode.md](interaction-mode.md) |
| Brain mode hint | `adapters/control_center_brain.py` › `_turn_context` (mode in the turn context); `runtime/control_center.py` › `BRIEF_PRESENTATION_MODE` | [interaction-mode.md](interaction-mode.md) |
| Composition | `app.py` › `_presentation_composition`; `runtime/presentation_runtime.py` › `PresentationComposition.build`, `PresentationCoordinator` | [presentation-audio-capture.md](presentation-audio-capture.md) |
| Explicit address | `domain/explicit_address.py`; `runtime/explicit_address_lane.py` › `ExplicitAddressLane` | [presentation-audio-capture.md](presentation-audio-capture.md) |
| Addressed window / turn | `domain/presentation_addressed_turn.py`; `core/presentation_addressed_turn.py` | [presentation-addressed-turn.md](presentation-addressed-turn.md) |
| Ambient lane | `runtime/ambient_lane.py` › `AmbientIngestionLane`; `domain/ambient_observation.py` | [presentation-ambient-lane.md](presentation-ambient-lane.md) |
| Working set | `domain/presentation_working_set.py`; `core/presentation_working_set.py` › `PresentationWorkingSetStore` | [presentation-working-set.md](presentation-working-set.md) |
| Brain turn and context | `protocol/client.py` › `submit_brain_turn`; `domain/v2.py` › `BrainTurnInput`; `domain/brain_context.py` › `BrainContext` | — (code) |
| Speculative lane | `domain/presentation_speculative.py` (capability table); `core/presentation_speculative.py` › `PresentationSpeculativeService` | [presentation-speculative-preparation.md](presentation-speculative-preparation.md) |
| Preparation runner | `runtime/presentation_preparation.py` (restricted `ClaudeLocalAgent`) | [presentation-speculative-preparation.md](presentation-speculative-preparation.md) |
| Hidden staging and reveal | `HiddenSceneStager` (core port) → `LedgeredSceneStager` → `runtime/presentation_staging.py` › `DisplaySceneStager` → `SceneDisplayTools` | [presentation-speculative-preparation.md](presentation-speculative-preparation.md) › Reveal path |
| Scene tools | `runtime/display_mcp.py` › `SceneDisplayTools.create_object(visibility=)`, `update_object(visibility=)`, `archive` — there is **no** `set_visibility` | [mcp/tool-contract.md](mcp/tool-contract.md) |
| Output intent (semantic manifestation) | `domain/presentation_intent.py` › `PresentationOutputIntent`, `intent_for_plan`, `intent_for_attention` | [presentation-response-policy.md](presentation-response-policy.md) › Output intent and display sink |
| Display sink | `core/presentation_display.py` › `PresentationDisplaySink` (port), `PresentationDisplayPublisher`; adapter `runtime/presentation_display_sink.py` › `DirectSceneDisplaySink` (Tool Brain replaces it in 08) | [presentation-response-policy.md](presentation-response-policy.md) › Output intent and display sink |
| Speech manifestation | `runtime/presentation_speech_gate.py` › `PresentationSpeechGate.admit`, enforced in `SpeechScheduler._enqueue` | [presentation-response-policy.md](presentation-response-policy.md) |
| Attention | `domain/presentation_attention.py` › `decide_attention`; `core/presentation_attention.py` › `PresentationAttentionService` | [presentation-attention.md](presentation-attention.md) |
| Canonical timeline | `domain/conversation_events.py` (closed types, `_SPECS`); `runtime/conversation_event_forwarder.py` | [conversation-events.md](conversation-events.md) |
| Voice → Control Center status | `runtime/visual_signals.py` › `VisualSignalBus` | — (code) |

## Decision numbering: HD ↔ D

| 2026-10 (HD) | 2026-09 (D) | Exists today | Gap → Slice (2026-10 handoff) |
| --- | --- | --- | --- |
| HD1 separate foundation | — | separate tasks | prefab not on `main` → 09 (deferred) |
| HD2 mode ≠ voice architecture | D01, D02 | same mode on every continuous architecture; legacy refused by precondition, at the mode change | **02 (fixed)**: process-lifetime mode follower |
| HD3 ambient has no authority | D03 | lane structurally separate; `BrainTurnInput` refuses AMBIENT | realtime path routes room speech as ADDRESSED/UNCERTAIN → 04 |
| HD4 explicit address wins | D04, D05 | arm preempts speculative; reserved slots | spoken wake suspended in an active session → vocative rule, 04 |
| HD5 fresh vs enriched | D06 | tail written before enrichment; projection built | projection never transported; deaf lane never prunes → 05 |
| HD6 background bounded | D07, D08 | pool, preemption, timeouts | pool size, unreachable capabilities → 06; invisible in timeline → 10 |
| HD7 manifest conservative | D09 | `AMBIENT_OBSERVATION` silent; matrix validated at construction | — |
| HD8 visual commands silent | D09, D10 | gate withholds | reveal broken in production → **01 (fixed)** |
| HD9 questions may speak | D10 | gate admits | answer lacks room context → 05 |
| HD10 discreet contradictions | D11 | judge + card + cue | same tone as failure → 10 |
| HD11 Tool Brain owns UI | D12 (partly) | no Tool Brain in code | semantic intent + sink port → 07; adapter → 08 (deferred) |
| HD12 Scene/Prefab visuals | D12 | stager via `SceneDisplayTools` (`artifact`) | prefab windows → 09 (deferred) |
| HD13 recording orthogonal | D13 | memory-only ambient; recording never counted | transcript text in the trace → 04, 11 |
| HD14 canonical observability | — (2026-09 D14 = SIMPLE regression boundary, still binding) | trace only | → 10 |

## Gaps by Slice

| Slice | Gap closed | Status |
| --- | --- | --- |
| 01 | `DisplaySceneStager.reveal` called the removed `set_visibility`; doubles hid it | **done** — `update_object(visibility="visible")` + contract test |
| 02 | process-lifetime mode follower in Voice; legacy refusal at the mode change | **done** — `follow_core_mode` owned by `PersistentVoiceRuntime.run`; `test_interaction_mode_follower.py` |
| 03 | Control Center renders the presentation status block (after 10) | open |
| 04 | brain-turn authority in an active session (explicit window or vocative); no room text in the trace | open |
| 05 | bounded presentation context on the brain-turn path; deaf-lane pruning | open |
| 06 | default pool 2 + 1 reserved, configurable; unreachable capabilities documented | open |
| 07 | `PresentationOutputIntent` + `PresentationDisplaySink` port, direct scene adapter | **done** — `show_prepared` publishes through the sink; `test_presentation_intent.py` |
| 08 | Tool Brain adapter | deferred until Tool Brain is on `main` |
| 09 | prefab staging | deferred until the scene/prefab foundation is on `main` |
| 10 | canonical timeline events, `stats()` in `/api/status`, distinct attention cue | open |
| 11 | deterministic scenario suite, privacy hardening | open |

Update the Status column when a Slice lands; leave the rows.
