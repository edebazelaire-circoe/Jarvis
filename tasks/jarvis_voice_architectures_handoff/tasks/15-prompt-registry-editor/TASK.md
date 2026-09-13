# Task 15 — Add prompt registry, inspector, and editor

## Goal

Expose every JARVIS-controlled initialization prompt layer relevant to the selected architecture and model, including the resolved effective prompt.

## Context

The user explicitly wants to inspect and modify backend/JARVIS, conversation/reflex, Front Brain analysis, Duplex/Live, and provider/model-specific prompt additions from Settings.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Create prompt registry with stable prompt layer IDs, role, provider/model applicability, source/provenance, default/current value, editability, and revision ID.
- Expose backend/JARVIS prompt.
- Expose Simple conversation prompt.
- Expose Front Brain conversational/reflex prompt and analysis-model prompt separately.
- Expose Duplex/GPT-Live prompt and delegation-related JARVIS-controlled layers.
- Expose provider/model-specific additions when JARVIS controls them.
- Show resolved effective prompt plus provenance/order.
- Allow edit/reset where safe and persist user overrides.
- Fingerprint prompt revisions into session metrics.

### Out of Scope
- Claiming visibility into provider-internal hidden/system prompts that the API does not expose.
- Allowing arbitrary prompt edits to bypass hard safety/runtime invariants.

## Dependencies
- Task 14 Settings architecture UI; Task 02 config registry.

## Implementation Steps
- 1. Inventory all current prompt construction sites from Task 01.
- 2. Centralize JARVIS-controlled layers into registry or registry-backed descriptors.
- 3. Define merge/order/resolution semantics.
- 4. Build Settings prompt inspector/editor tied to selected architecture/model roles.
- 5. Display effective prompt and layer provenance.
- 6. Add revision/fingerprint to session config/metrics.
- 7. Add prompt edit/reset tests and provider-hidden disclaimer.

## Files Likely Touched
- Prompt registry/resolver
- Existing prompt builders
- Settings prompt UI
- Persistence
- Tests

## Architecture Constraints
- Hard runtime invariants should not depend on editable prose alone when enforceable in code.
- Never fabricate or expose provider-internal prompts.
- Prompt resolution order must be deterministic and inspectable.

## Testing Requirements
- Each architecture shows all and only relevant JARVIS-controlled prompt layers.
- Editing a layer changes effective prompt and revision fingerprint.
- Reset returns to default.
- Provider-internal prompt absence is clearly represented, not guessed.

## Acceptance Criteria
- A user can inspect exactly what JARVIS sends/configures for each visible model role and trace where each prompt fragment comes from.

## Documentation Updates
- Update docs/06-settings-and-prompts.md with final prompt layer registry and editability rules.

## Handoff Notes

Prompt transparency is also a debugging feature for reflex behavior and cross-architecture benchmarks.
