# Task 02 — Add voice architecture config schema and capability registry

## Goal

Replace a flat voice-model choice with a typed architecture configuration that can represent Simple, Front Brain, and Duplex modes.

## Context

Settings must first select an architecture, then expose only models/options compatible with that architecture. UI model lists must be capability-driven, not hardcoded.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Define architecture enum/IDs: `simple`, `front_brain`, `duplex`.
- Define typed configuration for each mode.
- Add provider/model capability registry describing audio input/output, realtime conversation, duplex/delegation suitability, transcript deltas, prompt controls, and other capabilities actually used.
- Represent Simple primary conversational model; Front Brain conversational/reflex model plus analysis model; Duplex live frontend plus backend delegation config.
- Add migration/default mapping from current voice config to Simple without changing current runtime behavior.

### Out of Scope
- Settings UI rendering.
- Actual GPT-Live network implementation.
- Luna runtime calls.

## Dependencies
- Task 01 code map.

## Implementation Steps
- 1. Design discriminated/typed config objects for three architectures.
- 2. Design provider-neutral model capability descriptors.
- 3. Populate registry only with models verified by repository/provider integration evidence.
- 4. Implement validation that rejects incompatible model/architecture combinations.
- 5. Add backwards-compatible load/migration for existing settings.
- 6. Expose a query API the Settings UI can later consume.

## Files Likely Touched
- Voice config/schema module discovered in Task 01
- New capability registry module
- Config migration tests

## Architecture Constraints
- No hardcoded model dropdowns in UI-facing code.
- Capability checks must be testable without network calls.
- Unknown models should fail safely or be explicitly marked unsupported.

## Testing Requirements
- Schema serialization/deserialization.
- Legacy config maps to equivalent Simple configuration.
- Invalid architecture/model pair is rejected.
- Registry query returns only compatible models for each role.

## Acceptance Criteria
- All three modes are representable and validated.
- Current users keep equivalent behavior after config migration.
- Future provider models can be added through registry data plus an adapter, not UI surgery.

## Documentation Updates
- Update architecture spec with exact schema names chosen in code.

## Handoff Notes

Do not prematurely decide the global default architecture here; benchmark evidence comes in Task 20.
