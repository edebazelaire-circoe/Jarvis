# Slice 15 - Rehearsal, Recall and Script Refinement

## Goal
Support iterative rehearsal where the user and Jarvis can practice, ask where they are, refine script/animation, and immediately rehearse the updated result.

## Context
The user wants preparation to naturally lead into readiness to present because Jarvis already knows the agreed script and cues.

## Canonical Concepts
Rehearsal role, score recall, pause/comment/edit/resume, current cue, next planned point.

## Scope
### In Scope
- Enter/exit rehearsal mode on an artifact/variant.
- User can ask current/next planned point.
- Pause for feedback/edit, commit through semantic edit API, resume from coherent state.
- Rehearse a section or whole presentation.
- Record no separate durable "rehearsal transcript" unless existing explicit recording features are requested.

### Out of Scope
- Presentation analytics/coaching beyond the agreed score.

## Dependencies
- `12-playback-runtime`
- `13-user-presenter-sidekick`
- `14-jarvis-presenter-locked-sequences`
- `05-semantic-edit-api`

## Implementation Steps
1. Add rehearsal role/commands.
2. Expose bounded score recall helpers.
3. Integrate edit pause/resume and scene reload state repair.
4. Add section-loop/restart behavior.

## Files Likely Touched
Presentation runtime/authoring UI/agent operations and tests.

## Architecture Constraints
Do not turn ambient rehearsal speech into canonical memory or explicit recording automatically.

## Automated Validation
Section rehearsal, ask-where-we-are, edit-and-resume, backtrack, explicit-address scenarios.

## Acceptance Criteria
A user can rehearse and refine without losing score position or presentation state.

## Documentation Updates
Rehearsal workflow/runbook.

## Handoff Notes
Frontend/runtime: `/caveman`, `/coding-guideline`, `/impeccable`, Claude when supported.
