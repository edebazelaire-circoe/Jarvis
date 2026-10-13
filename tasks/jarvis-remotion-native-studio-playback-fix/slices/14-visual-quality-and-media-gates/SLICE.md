# Slice 14 - Real rendered-frame quality and regression gates


## Goal
Make visual quality measurable, instead of treating schema pass as visual approval.


## Context
Fix existing Jarvis Remotion Presentation Studio. Screenshot 1 depicts rejected floating viewer; screenshot 2 is Variants to retain. Read docs/06-screen-evidence.md and owner references.


## Canonical Concepts
Native Remotion Studio, Player, Variants, source/variant pins, score and cues; verify repository Level 2 and Level 3 contracts.


## Scope
### In Scope
Make visual quality measurable, instead of treating schema pass as visual approval.
### Out of Scope
- No new viewer or media engine, no arbitrary per-slide video limit.
- No guessed redesign for the left rail.
- No silent unsandboxed generated code execution or unrelated infrastructure rewrite.


## Dependencies
`03-reproduce-timeline-and-transition-failures`, `05-continuous-remotion-sequencing`, `10-variants-interface-control-audit`, `13-claude-native-generation-parity`


## Implementation Steps
1. Create preview/render smoke paths for first/middle/final frames of each scene and critical transition frames.
2. Detect black/blank frames, clipped content, missing fonts/assets, overflowing text, early truncation and repeated frames where algorithmically possible.
3. Use side-by-side visual snapshots and recorded videos for 9-scene flow; keep authored fps/resolution.
4. Automate smoke/replay tests in isolated runtime and browser with no live Core interaction.
5. Track quality metrics separately from TSX compilation, first-draft gate and Human creative assessment.


## Files Likely Touched
- docs/presentation-studio.md, docs/presentation-engine.md, docs/remotion-studio.md, docs/remotion-source.md
- Confirm actual owners and affected tests before editing. Agent-side playbooks: jarvis/runtime/presentation_playbooks.py.


## Architecture Constraints
Preserve Remotion as default, Slidecar only deliberate Human experiment, no silent fallback, one source of truth, stable Prefab pins, variant versions, Boards and Artifacts. Respect sandbox isolation and explicit trusted Studio approval. No changes to live Core/test user data.


## Automated Validation
- Focused machine tests and isolated real-runtime/real-browser checks, with exact SHA, sample sources, frame captures, durations and QA evidence.
- qa-verification and code-review; runtime-validation where applicable; agent-trace-analysis with real traces required if tools/prompts/routing change.
- Current-Slice regressions block PM signoff; do not defer to Issues.


## Acceptance Criteria
- Automated release evidence includes complete video, deterministic timeline markers and per-scene contact sheet.
- Tests catch regression of transition flash, time carry, stale progress bar and cut-at-8s.


## Documentation Updates
Update canonical contracts, execution guide, source ownership and conformance tests.


## Handoff Notes
- PM resolves valid current Workspace Task Type, no invented assignment.
- Coding requires /caveman and /coding-guideline.
- Human validation: No separate Human check; machine gates must precede qualitative review.