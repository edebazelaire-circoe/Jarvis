# Slice 07 — Presentation manifestation policy

## Goal

Decide when Presentation should say nothing, speak, request a visual manifestation, or raise discreet attention.

## Context

The central UX rule is conservative manifestation: ambient awareness should not turn Jarvis into a running commentator.

## Canonical Concepts

Addressed command, knowledge question, visual command, attention candidate, speech policy, semantic display intent.

## Scope

### In Scope

- Classify Presentation outcomes into `none`, visual/display intent, spoken answer, spoken+visual, or attention.
- Make visual/navigation commands silent by default unless speech is needed for error/clarification/safety.
- Allow concise speech for genuine questions where useful.
- Suppress ambient output by default.
- Gate contradiction attention by relevance/confidence/freshness.
- Produce a structured semantic result that downstream speech/Tool Brain paths can consume.

### Out of Scope

- Low-level UI-tool choice.
- Window geometry or concrete prefab rendering.
- User-specific interruption preference learning.

## Dependencies

- `06-background-intelligence-arbitration`
- `05-presentation-working-set`

## Implementation Steps

1. Define policy inputs/outputs against current runtime contracts.
2. Implement deterministic rules before model-driven nuance where possible.
3. Integrate with explicit-turn answer path and background results.
4. Ensure `none` is a first-class successful outcome.
5. Add scenario tests for visual command, knowledge question, ambient-only and contradiction cases.

## Files Likely Touched

Presentation policy module, Brain/context integration, speech-intent glue, tests, docs.

## Architecture Constraints

Policy emits semantic intent; Tool Brain owns concrete UI execution. Ambient context alone does not authorize actions.

## Automated Validation

Deterministic policy matrix tests, trace assertions for decision reason, regression tests for SIMPLE mode.

## Acceptance Criteria

Representative presentation interactions produce the intended silence/speech/display/attention behavior without filler output.

## Documentation Updates

Document the manifestation matrix and escalation rules.

## Handoff Notes

Coding/runtime Slice: load `/caveman` and `/coding-guideline`; add `agent-trace-analysis`.


## Slice 00 contract (binding)

Scope in:
- **Output intent.** New `jarvis/domain/presentation_intent.py` (R4):
  - `PresentationOutputIntent`, `DisplayIntent`, `DisplaySemantic{reveal_prepared, show_attention}`, `IntentUrgency{immediate, soon, opportunistic}`;
  - builders `intent_for_plan(plan, outcome)` and `intent_for_attention(attention)`;
  - reuses `PresentationSituation`, `OutputDisposition` and the `PRESENTATION_POLICY` speech ceiling;
  - `context_refs` ≤ 8 ids, never text;
  - `authorizes_actions = False`.
- **Display sink port.** `jarvis/core/presentation_display.py` with the `PresentationDisplaySink` Protocol (`publish`, `withdraw_speculative`) and a thin publisher that traces `presentation.intent.published` (ids and codes only).
- **Adapter.** `jarvis/runtime/presentation_display_sink.py` `DirectSceneDisplaySink`: `reveal_prepared` → `speculative.reveal(resource_id)`; `show_attention` → no-op receipt (the card path exists); `withdraw_speculative` → 0, said in the trace.
- **Rewire.** `PresentationAddressedTurnService._show_prepared` (`core/presentation_addressed_turn.py:798`) publishes an intent through the sink instead of calling `speculative.reveal` directly. An explicit turn calls `withdraw_speculative`. Composition in `PresentationComposition.build`.

Scope out: Tool Brain (08); prefab (09); changing the policy matrix or the gate; new speech kinds.

Files: new `jarvis/domain/presentation_intent.py`, new `jarvis/core/presentation_display.py`, new `jarvis/runtime/presentation_display_sink.py`, `jarvis/core/presentation_addressed_turn.py`, `jarvis/runtime/presentation_runtime.py`, `docs/presentation-response-policy.md` (intent section), `docs/presentation-mode.md`, new `tests/unit/test_presentation_intent.py`.

Acceptance:
- `test_intent_vocabulary_reuses_existing_enums`: no new speech enum; handoff names mapped in the docstring.
- `test_intent_never_authorizes_actions`.
- `test_intent_per_addressed_action`:
  - SHOW_PREPARED → reveal_prepared, immediate;
  - CLARIFY → no display, QUESTION ceiling;
  - REFRESH → no display, opportunistic;
  - ASK_BRAIN → no display.
- `test_attention_intent_visual_only`.
- `test_show_prepared_goes_through_sink_only`: `speculative.reveal` is not called by the turn service directly.
- `test_direct_sink_reveals_via_real_stager_and_scene_tools` (Slice 01 fixture).
- `test_explicit_turn_withdraws_speculative`.
- `test_intent_and_port_modules_import_no_runtime_or_scene`: import-closure guard, pattern of `core/presentation_attention.py:405`.
- Existing presentation suites green.

QA tier: glue. Passes: qa-verification + code-review + agent-trace-analysis (a SHOW_PREPARED trace shows `presentation.intent.published` → `presentation.staging.revealed` in order).

Not yours: timeline mapping (10).

Depends on: 05, 06.

Documentation: manifestation intent Level 3.
