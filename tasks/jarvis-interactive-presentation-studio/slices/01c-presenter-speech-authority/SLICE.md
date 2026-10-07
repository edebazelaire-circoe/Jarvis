# Slice 01c (accepted by PM 2026-10-07) - Speech Authority for the Jarvis Presenter

Status: proposal from Slice 01 (`docs/07-integration-map.md` G3/3.4). Must be decided before Slice 14 codes; may be a decision-only Slice if option A is chosen.

## Goal
Make it possible, and safe, for Jarvis to speak a score-scripted line while a presentation runs, without loosening the PRESENTATION silence contract (D03/D11 of the 2026-09 handoff).

## Evidence (the gap)
- In PRESENTATION mode every spoken line passes `PresentationSpeechGate.admit` (`jarvis/runtime/presentation_speech_gate.py:116`, called from `SpeechScheduler._enqueue`, `jarvis/runtime/speech_scheduler.py:2421`). A line attached to no classified addressed turn has `situation=None`, and `admit_presentation_speech` admits only `UNADDRESSED_SAFETY_KINDS = (SpeechKind.ERROR,)` (`jarvis/domain/presentation_response.py:190`, `jarvis/domain/presentation_policy.py:228`).
- The matrix invariant `voice_allowed => requires_explicit_address` (`presentation_policy.py:~121-124`) and `LOCKED_DECISIONS` = D01..D14 of the 2026-09 handoff (`presentation_policy.py:41`) forbid a new "score speech" row without a decision and a set extension.
- Verbatim Core speech exists (`BrainOrchestrator.announce_notice`, `jarvis/core/brain_service.py:889`) but would be withheld in PRESENTATION.

## Scope
### In Scope
- Decide between:
  - **A. Presenter runs in ASSISTANT (SIMPLE) mode**: no policy change; the ambient lane is off during a Jarvis-presented run; rehearsal with user speech needs the mode set explicitly. Cost: a mode switch semantic (D15 "no restart" holds; `interaction.mode.changed` already hot-switches).
  - **B. New grant**: a `PresentationSituation` (e.g. `SCORE_SPEECH`) whose authority is the user's explicit request to present/continue (an explicit-address-derived, time-bounded, revocable grant), with a matrix row (`voice_allowed=True`, `requires_explicit_address=True`, speech kinds limited), `LOCKED_DECISIONS` extension through a new decision-log entry, structural tests (ambient text can never open the grant; explicit address preempts and ends it; silence items stay silent).
- Whichever is chosen: written contract in `docs/presentation-response-policy.md` (B) or `docs/presentation-studio.md` (A), tests, and the exact `announce_notice` argument set Slice 14 uses (`kind`, `supersedes_key`, `ttl_s`).

### Out of Scope
- The presenter driver and locked-sequence timing (Slice 14); cue following (Slice 13).

## Dependencies
- `01-contract-audit`. Blocks `14-jarvis-presenter-locked-sequences` and `15-rehearsal-workflow` (rehearsal with Jarvis speaking).

## Acceptance Criteria
A scripted line is either provably admitted under a bounded explicit grant or provably run outside PRESENTATION, ambient speech still cannot create speech or actions (existing tests `tests/unit/test_presentation_response_policy.py`, `test_presentation_turn_authority.py` stay green), and the Human-visible behavior (what Jarvis says when) is documented.

## QA tier
critical if option B (changes the authority matrix); standard if option A.
