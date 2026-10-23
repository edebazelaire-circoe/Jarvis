# Slice 02 - Brain config runtime contract

## Goal

Create a generic, data-driven brain configuration contract for current and future brains, including model/provider, mission/instructions and five-level sub-agent delegation tendency.

## Context

Brain-specific configuration must not become another top-level tab. The Architecture canvas opens a contextual popup that reads/writes this contract.

## Canonical Concepts

- model/provider catalog
- existing agent settings and prompt override mechanisms
- Tool Brain ownership/config when applicable
- this handoff's delegation separation rule

## Scope

### In Scope

- Stable brain config descriptor/read model.
- Provider/model compatibility and availability from server-owned catalog.
- Mission/responsibility/prerogative fields supported by each brain.
- Brain-specific instruction/prompt override where a canonical editable prompt exists.
- Valid activation/deactivation capability.
- Delegation tendency enum: never, rare, standard, proactive, exploratory.
- Service/persistence/update validation.
- Read-only connection summary seam from Slice 01.
- Unmounted handler/controller module for Slice 07.

### Out of Scope

- No selection of exact Code/Research/QA models here.
- No personality controls.
- No CLI command/path/permission UI contract.
- No frontend.
- No shared route registration hot-file edits.

## Dependencies

### Hard `depends_on`

None after Slice 00 READY.

### Soft `requires`

- Slice 01:
  - need: authoritative brain ids, activation/connection mutability and connection summary.
  - fallback: use audited stable ids plus a small adapter interface returning `unknown/unavailable` for graph-only fields.
  - integration_required_before: Slice 07 live wiring.
  - mismatch_policy: adopt Slice 01 ids/capability contract; do not maintain aliases as a second registry unless explicit compatibility needs them.
- Slice 03:
  - need: role-request/delegation boundary.
  - fallback: emit a generic role/capability delegation request per documented seam.
  - integration_required_before: runtime validation in Slice 07/08.
  - mismatch_policy: change the adapter boundary, not the user-facing five-level vocabulary.

### Can Start With

Current model catalog, agent settings, prompts and the documented generic brain config shape.

### Produces

- brain config service/read-write contract;
- delegation tendency contract;
- config capability descriptors;
- fixtures for Slice 05.

### Integration Checkpoint

Slice 07 live route and graph/popup wiring.

## Implementation Steps

1. Audit current per-brain configuration owners.
2. Create generic descriptors without forcing unsupported fields onto every brain.
3. Bind model/provider selectors to catalog capability filters.
4. Implement mission/instruction update only where canonical persistence exists.
5. Implement five-level delegation behavior contract and runtime mapping.
6. Preserve current settings during migration.
7. Expose stable validation/unavailable reasons.

## Files Likely Touched

Prefer new brain-config domain/runtime modules plus focused adapters/docs. Avoid `control_center.py` and shared page shell until Slice 07.

## Architecture Constraints

One brain identity source; one model catalog; no role->candidate policy in brain config; no personality settings.

## Automated Validation

Static/import checks plus targeted config service smoke checks and genuine trace evidence for delegation behavior mapping. **Do not launch the full unit test suite at this Slice boundary.**

## Acceptance Criteria

- Current brains expose only supported editable fields.
- Five delegation levels are persisted/translated consistently.
- `never` demonstrably prevents delegation from that brain in a focused trace.
- Model choices come from live catalog with unavailable reasons.
- Existing CLI technical fields are untouched/kept outside this contract.

## Documentation Updates

Document generic brain config and delegation semantics.

## Handoff Notes

The UI text can use friendly French labels while the runtime enum remains stable and language-neutral.
