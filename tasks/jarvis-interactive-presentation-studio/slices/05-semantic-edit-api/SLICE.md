# Slice 05 - Semantic Presentation Edit API

## Goal
Implement one semantic edit API used by both Jarvis voice commands and human GUI editing.

## Context
The user wants direct-feeling control without a broken regenerate-everything loop.

## Canonical Concepts
Edit intent, control patch, structural patch, source edit request, preview vs commit.

## Scope
### In Scope
- Edit operation vocabulary using stable presentation/variant/scene/control IDs.
- Mutation classifier: control patch vs structural patch vs source edit.
- Transaction/validation result shape.
- Preview/commit distinction.
- Undo operation record generation for committed edits.

### Out of Scope
- Source HMR implementation.
- GUI inspector.

## Dependencies
- `04-presentation-scene-control-contract`

## Implementation Steps
1. Define semantic operations around repository conventions.
2. Enforce current-state preconditions and stale-state rejection.
3. Make control changes atomic.
4. Keep direct DOM edits outside durable commit path.
5. Emit canonical observability events without user content leakage beyond existing policy.

## Files Likely Touched
Presentation editing domain/service/tool modules and tests.

## Architecture Constraints
Voice and GUI must call the same service/operations.

## Automated Validation
Equivalent GUI/agent operation fixtures, stale ID/precondition tests, invalid control tests, transaction rollback tests.

## Acceptance Criteria
Common edits can be expressed without source rewriting and all committed edits update canonical state.

## Documentation Updates
Document semantic edit vocabulary and error/refusal behavior.

## Handoff Notes
Use `/caveman` and `/coding-guideline`. Agent-facing changes require trace tests.
