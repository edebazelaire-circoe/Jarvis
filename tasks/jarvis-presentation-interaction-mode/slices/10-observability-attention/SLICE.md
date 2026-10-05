# Slice 10 — Presentation observability and discreet attention surface

## Goal

Make Presentation behavior debuggable and surface high-value contradiction attention without spoken interruption.

## Context

The canonical conversation observability task already owns the shared event record and live timeline. Presentation must extend it, not create a separate log.

## Canonical Concepts

Conversation event, trace link, Presentation decision, background job, fact-check attention, Tool Brain action.

## Scope

### In Scope

- Emit canonical events for ambient classification, working-set changes, background work, preemption, manifestation decisions and Tool Brain intent/action correlation.
- Extend the existing timeline/debug surface with Presentation-specific visibility where useful.
- Implement/reuse a discreet small attention/fact-check UI signal plus non-verbal audible cue if product audio conventions support it.
- Let the user explicitly ask Jarvis to explain the attention item.
- Support clearing/expiry/staleness.

### Out of Scope

- A second diagnostics page/log.
- Unsolicited spoken fact-check explanation.
- Full fact-check research engine redesign.

## Dependencies

- `07-manifestation-policy`
- `08-tool-brain-integration`
- `09-scene-prefab-integration`
- External canonical observability contract.

## Implementation Steps

1. Map Presentation lifecycle to canonical event types/trace links.
2. Extend timeline projections/lanes minimally.
3. Implement attention signal through canonical Tool Brain/scene path where appropriate.
4. Add explain/clear/expire semantics.
5. Validate trace correlation end to end.

## Files Likely Touched

Event schemas/producers, timeline UI projection, attention UI adapter, tests, docs.

## Architecture Constraints

Canonical event ledger remains source of truth. Attention is a manifestation of a Presentation decision, not a new conversation turn.

## Automated Validation

Event projection tests, frontend/runtime tests, trace-analysis proving event chain, attention expiry/clear tests.

## Acceptance Criteria

A developer can trace why Jarvis stayed silent, prepared work, interrupted speculative work, displayed something or raised attention; the user gets a discreet actionable signal for high-confidence contradictions.

## Documentation Updates

Document new event types/projections and attention lifecycle.

## Handoff Notes

Frontend/runtime coding Slice: load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude when supported. Requires `agent-trace-analysis`.


## Slice 00 contract (binding)

Scope in (P6, P7, A8):
- **Withheld speech.** In `SpeechScheduler._enqueue`, at the withheld return (`speech_scheduler.py:2371-2373`), record `mouth.speech.superseded` via `_mouth_event` (:3018) with `reason="presentation_withheld"`.
  - Diagnostic; content = the withheld brain text (doc rule `docs/conversation-events.md:528-533`).
  - Parent = the `brain.speech.requested` id (existing logic).
- **Preparation sub-agents.** Add an optional lifecycle port on `PresentationSpeculativeService`. A runtime adapter `jarvis/runtime/presentation_timeline.py` maps job start/prepared/failed+timeout/preempted+retired to `subagent.started/finished/failed/stopped`:
  - producer `voice.presentation`, `task_id` = job id;
  - `conversation_id` = live Voice conversation, read lazily (`app.py` passes `lambda: voice.runtime.conversation_id` and the forwarder from `app.py:1165`);
  - attributes `subagent_type="presentation_preparation"`, `background=True`, `status`, `duration_ms`;
  - content = capability label only.
- **New types** (`domain/conversation_events.py:97-125`, `_SPECS` :146; `docs/conversation-events.md` table + note; tests together):
  - `system.mode.changed` (from the coordinator on apply);
  - `system.attention.raised` (from `PresentationAttentionService._emit`, `core/presentation_attention.py:321`);
  - `system.attention.cleared` (at session retire for every `raised_ids()` still live, `reason=session_ended`; eviction if detectable);
  - all instant, diagnostic, content forbidden, existing allowlisted attributes only.
  - Verify the timeline UI renders them in the system lane.
- **Status.** Add `VisualSignalBus.presentation(report)` → `.voice_presentation` (`runtime/visual_signals.py`, pattern :55). The coordinator writes it on enter, leave, refusal, blockers and each diagnostics tick, from `PresentationCoordinator.stats()` (`presentation_runtime.py:1296`), scalars only. CC `/api/status.presentation` (`control_center.py:2015-2105`) reads it; `null` when Voice is offline (heartbeat).
- **Cue.** `bgCue(tone)` with tone ∈ {`ok`,`bad`,`attention`} (`control_center.html:1493`). `renderBackgroundPills` (:1544,:1573) passes `attention` when the rise is attention-only, which plays a distinct softer pair at lower gain than `bad`; failure wins. Still the single emitter. `/impeccable`, Claude agent.

Scope out: replacing the trace/ledger card path; Core-side mode events; HUD status line (03).

Files: `jarvis/runtime/speech_scheduler.py`, `jarvis/domain/conversation_events.py`, `docs/conversation-events.md`, `jarvis/core/presentation_speculative.py`, `jarvis/core/presentation_attention.py`, new `jarvis/runtime/presentation_timeline.py`, `jarvis/runtime/presentation_runtime.py`, `jarvis/app.py`, `jarvis/runtime/visual_signals.py`, `jarvis/runtime/control_center.py`, `jarvis/runtime/control_center.html`, `docs/presentation-attention.md`, `docs/OPERATIONS.md`, tests below.

Acceptance:
- `tests/unit/test_presentation_timeline_events.py`:
  - `test_withheld_speech_closes_brain_request_in_reconstruction` (`reconstruct_conversation`: requested → superseded, no orphan);
  - `test_preparation_jobs_are_subagent_spans_without_room_text` (planted phrase absent in every event);
  - `test_mode_change_and_attention_events_validate_against_specs`;
  - `test_attention_cleared_at_session_end`;
  - `test_recorder_failure_never_breaks_speculative_lane`.
- `test_conversation_events.py` extended: the new specs, attribute allowlist unchanged.
- `test_status_exposes_presentation_scalars_only`; `test_presentation_report_hidden_when_voice_offline`.
- JS: `test_presentation_attention_js.py` additions:
  - `test_attention_only_rise_plays_attention_tone`;
  - `test_failure_wins_over_attention`;
  - static `test_single_audio_emitter` (one `AudioContext` construction site).
- Browser: the card + cue through the CC (`_presentation_attention_browser.mjs`).

QA tier: glue + ui. Passes:
- qa-verification + code-review + runtime-validation (browser + timeline view);
- agent-trace-analysis: a fake-driven PRESENTATION run's timeline reconstructs withheld speech and prep spans.

Human check: HV-PRESENTATION-ATTENTION-01 (supersedes HV-PRES-ALERT-01), after machine QA.

Not yours: HUD status line (03); Issue 002 (11).

Depends on: 06, 07.

Documentation: Presentation events Level 3 in `docs/conversation-events.md`.
