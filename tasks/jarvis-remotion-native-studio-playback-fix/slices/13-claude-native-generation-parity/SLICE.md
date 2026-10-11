# Slice 13 - Agent-native creative workflow and Remotion parity benchmark


## Goal
Restore baseline capability: a normal Claude agent using Remotion can create an excellent deck without restrictive Jarvis schema as the only path.


## Context
Fix existing Jarvis Remotion Presentation Studio. Screenshot 1 depicts rejected floating viewer; screenshot 2 is Variants to retain. Read docs/06-screen-evidence.md and owner references.


## Canonical Concepts
Native Remotion Studio, Player, Variants, source/variant pins, score and cues; verify repository Level 2 and Level 3 contracts.


## Scope
### In Scope
Restore baseline capability: a normal Claude agent using Remotion can create an excellent deck without restrictive Jarvis schema as the only path.
### Out of Scope
- No new viewer or media engine, no arbitrary per-slide video limit.
- No guessed redesign for the left rail.
- No silent unsandboxed generated code execution or unrelated infrastructure rewrite.


## Dependencies
`01-independent-intention-and-code-audit`, `12-native-authoring-workspace-roundtrip`


## Implementation Steps
1. Create comparable controlled prompts for Jarvis and direct terminal Claude with Remotion on Jarvis and iGuard topics.
2. Record tool affordances and differences in source access, dependencies, design references, prompt truncation, instruction budgets, restricted schemas and permissions.
3. Introduce a default agent-native workflow: inspect project, storyboard, create React/TSX, run native preview/tests, review visuals and iterate.
4. Keep optional Jarvis safety/metadata/quality gates only where they add demonstrable value, not creative restrictions.
5. Reuse current presentation playbooks and agent routing hook only after proving they reach the agent with enough context; no invented features/data.
6. Store raw traces, generated sources, frames, reviewer findings, elapsed work and comparisons.


## Files Likely Touched
- docs/presentation-studio.md, docs/presentation-engine.md, docs/remotion-studio.md, docs/remotion-source.md
- Confirm actual owners and affected tests before editing. Agent-side playbooks: jarvis/runtime/presentation_playbooks.py.


## Architecture Constraints
Preserve Remotion as default, Slidecar only deliberate Human experiment, no silent fallback, one source of truth, stable Prefab pins, variant versions, Boards and Artifacts. Respect sandbox isolation and explicit trusted Studio approval. No changes to live Core/test user data.


## Automated Validation
- Focused machine tests and isolated real-runtime/real-browser checks, with exact SHA, sample sources, frame captures, durations and QA evidence.
- qa-verification and code-review; runtime-validation where applicable; agent-trace-analysis with real agent traces required.
- Current-Slice regressions block PM signoff; do not defer to Issues.


## Acceptance Criteria
- Jarvis succeeds on the same brief without more avoidable tool retries than direct workflow; quality meets independent human evaluation gate.
- Works with normal editable Remotion code; restricted prefab schema is not the only creation path.


## Documentation Updates
Update canonical contracts, execution guide, source ownership and conformance tests.


## Handoff Notes
- PM resolves valid current Workspace Task Type, no invented assignment.
- Coding requires /caveman and /coding-guideline.
- Human validation: Human reviews blinded final decks side-by-side; do not claim quality parity from tests alone.