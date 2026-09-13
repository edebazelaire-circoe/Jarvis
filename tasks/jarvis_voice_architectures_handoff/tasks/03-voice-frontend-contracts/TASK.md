# Task 03 — Define canonical VoiceFrontend and event contracts

## Goal

Create the provider-agnostic boundary that makes Realtime, Realtime+Front Brain, and GPT-Live interchangeable.

## Context

JARVIS Core should not depend directly on OpenAI Realtime, OpenAI Live, or Gemini event names. Adapters normalize provider events into canonical JARVIS events.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Define `VoiceFrontend` lifecycle contract: configure/start/stop/send context or equivalent based on language conventions.
- Define canonical input/output events including speech start/stop, transcript delta/final, actual spoken text, interruption, delegation request, frontend error, session usage, and lifecycle state.
- Define typed operation/result/error objects and correlation IDs.
- Create fake/in-memory frontend for tests.
- Add architecture/import-boundary tests that prevent Core from importing provider event types.

### Out of Scope
- Porting the current Realtime implementation.
- GPT-Live implementation.
- UI.

## Dependencies
- Task 02 config schema.

## Implementation Steps
- 1. Use current event flow from Task 01 to enumerate minimum canonical semantics.
- 2. Define lifecycle and cancellation guarantees.
- 3. Add turn/session/task/speech correlation identifiers.
- 4. Implement fake frontend with deterministic event injection.
- 5. Add boundary tests or dependency checks.
- 6. Document translation responsibility: provider adapter in, canonical Core events out.

## Files Likely Touched
- New voice frontend contract module
- New canonical event/result types
- Test fake frontend
- Architecture tests

## Architecture Constraints
- Provider SDK types must not leak above the adapter boundary.
- Stop must be idempotent.
- Actual spoken output must be representable separately from intended output.
- Errors must preserve enough diagnostics to understand provider/session state.

## Testing Requirements
- Fake frontend lifecycle and event ordering.
- Stop called multiple times is safe.
- Core modules cannot import provider-specific voice SDK event definitions.

## Acceptance Criteria
- A fake frontend can drive a complete synthetic conversation without a provider SDK.
- Provider-specific event names are isolated below the contract.

## Documentation Updates
- Update docs/02-architecture-spec.md with exact interface and event names.

## Handoff Notes

Prefer the narrowest contract that supports all three architectures; do not encode GPT-Live-specific concepts unless normalized.
