# Slice 03 - Sub-agent role routing contract

## Goal

Evolve the existing task-profile routing foundation into the global role-oriented configuration requested by the user, without losing existing role, model, fallback or compatibility behavior.

## Context

Current main has seven canonical roles but routing candidates are primarily stored by task profile. The target UI configures the candidate harness/model order for each role. Brain config only decides when to delegate.

## Canonical Concepts

- `jarvis/domain/subagent_roles.py`
- `docs/subagent-roles.md`
- `jarvis/domain/routing.py`
- `jarvis/runtime/agent_routing.py`
- `jarvis/runtime/model_catalog.py`

## Scope

### In Scope

- Role-oriented routing policy keyed by canonical `role_id`.
- Ordered harness/agent + model candidates using existing `CandidateRef`/catalog semantics where possible.
- Availability/rejection reasons.
- Fallback semantics.
- Migration/projection from existing task-profile policies using each role's `default_profile` as provenance/default.
- Preservation of all seven roles and aliases.
- API/read model suitable for the new Sous-agents UI.
- Preserve role instructions/Work Methods/loadout/tools/skills as canonical existing data rather than copying them into routing storage.
- Compatibility handling for current `agent_routing.enabled` / Auto-Duplique state without exposing those names as the new primary UI.
- Unmounted handler/controller integration for Slice 07.

### Out of Scope

- No per-brain delegation intensity implementation (Slice 02).
- No frontend (Slice 06).
- No Work Method candidate-promotion redesign unless required by compatibility.
- No shared page/controller hot-file registration.

## Dependencies

### Hard `depends_on`

None after Slice 00 READY.

### Soft `requires`

- Slice 02:
  - need: final role-request/delegation event shape used by brains.
  - fallback: accept canonical role id + optional capability requirements at resolver boundary.
  - integration_required_before: Slice 07/08 runtime wiring.
  - mismatch_policy: adapt resolver input; do not make model choice a brain-config field.

### Can Start With

Current role registry, routing policy, candidate catalog and `default_profile` mapping.

### Produces

- role policy storage/read model;
- migration/projection path from current profile policies;
- resolver adapter using ordered role candidates/fallback;
- fixtures for Slice 06.

### Integration Checkpoint

Slice 07 live handler and delegation-resolver wiring; Slice 08 trace validation.

## Implementation Steps

1. Audit exact current task profiles/candidate persistence.
2. Define role policy keyed only by resolved canonical role ids.
3. Reuse candidate eligibility/fallback machinery.
4. Define migration/inheritance behavior from each role's current default profile.
5. Preserve unavailable candidates with reasons.
6. Keep prompt instructions/Work Methods/loadout in their existing owners.
7. Project legacy Auto/Duplique safely for compatibility without retaining it as the target UX.
8. Expose stable role-policy payload/validation.

## Files Likely Touched

Routing/subagent domain/runtime modules and focused docs/tests. Avoid `control_center.py` route registration until Slice 07.

## Architecture Constraints

Do not clone the role registry. Do not clone the model catalog. Do not convert soft migration uncertainty into silent destructive rewrites.

## Automated Validation

Static/import checks plus narrow resolver smoke checks proving role isolation, ordered preference, fallback and unavailable reasons. Use a real agent trace if the runtime selection path is changed. **Do not launch the full unit test suite at this Slice boundary.**

## Acceptance Criteria

- All canonical roles can have independent candidate order.
- Existing profile policy produces deterministic inherited defaults without losing data.
- Changing one role policy does not silently alter unrelated roles.
- Candidate availability reasons survive round-trip.
- Old Auto/Duplique settings remain safely interpretable but are no longer the target user model.

## Documentation Updates

Update routing and sub-agent role docs with the role-policy layer and migration semantics.

## Handoff Notes

Current `research`, `web-research`, `concept`, `research-lead`, `qa`, etc. may share `general` today; the new policy must let them diverge without mutating the role registry itself.
