# Task 14 — Redesign Settings around voice architecture modes

## Goal

Let users select Simple, Front Brain, or Duplex first, then show only the model/options meaningful for that mode.

## Context

The settings mental model should shift from selecting one voice model to selecting an architecture and configuring its roles.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Add architecture selector with Simple / Front Brain / Duplex labels and concise descriptions.
- Render mode-specific panels from capability registry.
- Simple: conversational voice model/provider options.
- Front Brain: conversational/reflex model plus analysis model and relevant tunables.
- Duplex: GPT-Live 1 initially plus duplex-specific lifecycle/delegation options.
- Preserve/migrate existing voice settings.
- Show unsupported/unavailable model reasons rather than invalid choices.

### Out of Scope
- Prompt editor implementation (Task 15).
- Active Live timer/stop indicator (Task 16).
- Benchmark dashboard beyond selection/config metadata.

## Dependencies
- Task 02 schema/registry; adapters available enough for selected choices to be validated.

## Implementation Steps
- 1. Map existing Settings components from Task 01.
- 2. Implement architecture-first selector.
- 3. Build conditional fields from typed config/capability registry.
- 4. Bind values to persisted configuration with validation.
- 5. Add migration display for current users.
- 6. Add UI tests for all architecture panels and incompatible choices.

## Files Likely Touched
- Settings UI components
- Settings view-model/state
- Config persistence bridge
- UI tests

## Architecture Constraints
- No provider/model names duplicated across multiple UI switch statements.
- Only expose options whose runtime implementation exists or explicitly label experimental/unavailable state.
- Changing an active architecture must go through safe switch service when Task 17 is available.

## Testing Requirements
- Simple shows one conversational model role.
- Front Brain shows conversation/reflex + analysis roles.
- Duplex shows GPT-Live-specific fields and hides irrelevant Realtime fields.
- Legacy config renders equivalent Simple selection.

## Acceptance Criteria
- A user can understand and configure all three architectures without seeing irrelevant controls.

## Documentation Updates
- Update docs/06-settings-and-prompts.md with final Settings field names and screenshots only if project conventions require them.

## Handoff Notes

Exact Gemini choices come from Task 01/registry; do not invent them.
