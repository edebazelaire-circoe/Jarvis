# Task 02 - Create Jarvis core skeleton and typed contracts

## Goal

Creer les frontieres de l'architecture avant tout comportement reel.

## Context

La V1 doit pouvoir changer de fournisseur IA sans reecrire audio, gestes, memoire ou UI.

## Scope
### In Scope
- Charger `/caveman` et `/coding-guideline`.
- Creer package structure.
- Definir domain models et Protocol/ABC ports.
- Implementer fake adapters.
- Implementer config typed/validated.
- Creer minimal session orchestration in-memory.

### Out of Scope
- Pas d'appel OpenAI reel.
- Pas d'audio reel.
- Pas de Barehands reel.

## Dependencies

Tasks 00-01 complete.

## Implementation Steps

1. Create `domain/`, `ports/`, `core/`, `adapters/`, `security/`, `diagnostics/`.
2. Define `AudioClip`, `TranscriptionResult`, `UserTurn`, `AgentResult`, `SpeechResult`, `ActionRequest`, `ActionResult`.
3. Define all ports in architecture spec.
4. Implement fakes for tests.
5. Add config loading with environment overrides.
6. Add an in-memory text-only orchestrator test.

## Files Likely Touched

- `jarvis/domain/*`
- `jarvis/ports/*`
- `jarvis/core/*`
- `jarvis/config.py`
- `tests/unit/*`

## Architecture Constraints

Provider SDK types may exist only in adapter modules. Core consumes domain types only. Results must carry diagnostics without exposing provider objects.

## Testing Requirements

- Import-boundary/architecture test.
- Unit tests for result models and config validation.
- Text turn using all fake adapters.

## Acceptance Criteria

- Core skeleton imports successfully.
- Fake end-to-end text turn passes.
- Provider independence is enforced by test/lint rule.
- Invalid config fails clearly.

## Documentation Updates

Update architecture spec only if names change.

## Handoff Notes

Do not add convenience imports that let OpenAI/Barehands types leak into core.
