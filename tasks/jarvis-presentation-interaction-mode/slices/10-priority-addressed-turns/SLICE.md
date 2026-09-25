# Slice 10 - Complete priority addressed turns with fresh context and prepared-resource reuse

## Goal
Make explicit Presentation commands/questions immediate even while ambient work is behind, and reuse prepared resources instead of repeating expensive work.

## Context
Key risk is a command arriving late because it sits behind continuous analysis. The command path must be independently prioritized and receive enriched plus fresh context.

## Canonical Concepts
`ExplicitAddressTrigger`; P0 addressed work; working-set snapshot + recent transcript tail; prepared-resource resolution; output disposition.

## Scope
### In Scope
- Bind wake/manual trigger to following addressed speech window/turn.
- Immediately snapshot fresh tail + committed working set.
- Route at P0 without waiting for ambient drain.
- Resolve deictic refs using fresh tail first, then enriched working set/resources.
- Reuse valid prepared resource IDs/hidden Scene objects.
- If stale/ambiguous, refresh or minimally clarify rather than show wrong item.
- Integrate visual-command silence and knowledge-question speech.
- After completion, remain Presentation ambient, not ordinary Assistant.
- Telemetry trigger -> admission -> first visible/audible reaction.
### Out of Scope
Meeting and personalized speech preferences.

## Dependencies
Slices 05, 07, 08.

## Implementation Steps
1. Load `/caveman` and `/coding-guideline`.
2. Define addressed-window binding around trigger timestamps/pre-roll.
3. Implement P0 admission and reserved capacity/preemption.
4. Build context from working-set snapshot + fresh tail with provenance/freshness.
5. Implement prepared-resource resolver and stale/ambiguity rules.
6. Wire display and response disposition.
7. Return seamlessly to ambient Presentation.
8. Add deterministic tests with minute-scale simulated backlog/slow workers.

## Files Likely Touched
`voice_v2.py`, realtime/voice admission bridge, Core brain/context service, presentation scheduler/resolver, Scene/display integration, latency metrics/tests.

## Architecture Constraints
P0 never waits for ambient; fresh tail is data/context not executable instructions; stale cache cannot override fresher spoken context.

## Automated Validation
Load/priority, brain context protocol, voice admission, latency, Scene display and speech policy tests.

## Acceptance Criteria
Under slow ambient backlog trigger admits immediately; “show me that” resolves recent context; valid prepared material reused; visual command no filler; genuine question may speak/display; runtime stays Presentation.

## Documentation Updates
Document addressed-window binding, context precedence, cache reuse and latency telemetry.

## Handoff Notes
Human check `HV-PRES-PRIORITY-01` validates perceived responsiveness.
