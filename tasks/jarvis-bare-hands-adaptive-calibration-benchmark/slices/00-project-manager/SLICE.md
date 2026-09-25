# Slice 00 — Project Manager readiness and reconciliation gate

## Goal

Establish that this successor matches current `main`, the prior refinement is already merged, and no newer active handoff conflicts with the plan.

## Context

This Slice belongs to the successor adaptive-calibration task. The prior UI refinement is already merged; work from current `main`, never from the historical task branch.

## Canonical Concepts

Bare Hands canonical contracts; current `docs/barehands-contracts.md`; current implementation and tests; current Jarvis runtime contracts

## Scope

### In Scope

- Blind-audit current Bare Hands, voice/agent, MCP and scene code before reading `docs/05-documentation-levels.md`.
- Verify merge `e684a468...` is ancestor/history and inspect changes since it.
- Confirm current source head and tests.
- Resolve Workspace Task Types.
- Repair/split/reorder this handoff if repository drift demands it.
- Produce exactly one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, `HUMAN_DECISION_REQUIRED`.

### Out of Scope

- Product code edits.
- Delegating Slice 00.

## Dependencies

None

## Implementation Steps

1. Run blind audit.
2. Check active Drive/GitHub tasks touching Bare Hands/voice/scene.
3. Reconcile against this handoff only after the audit.
4. Run baseline relevant test set.
5. Resolve Task Types.
6. Record readiness in LOG/TODO; no dispatch below READY.

## Files Likely Touched

- `tasks/...` planning files only

## Architecture Constraints

No product code in Slice 00. Preserve prior merged implementation as baseline, not work to repeat.

## Automated Validation

Baseline Bare Hands tests and targeted current-head checks recorded; dependency graph and Human IDs validated.

## Acceptance Criteria

Readiness is explicit, conflicts are named, and later Slices are safe to dispatch.

## Documentation Updates

Update `docs/barehands-contracts.md` and relevant operational/user documentation for every changed canonical concept. Update this task LOG with durable execution decisions and evidence references.

## Handoff Notes

Baseline `qa-verification` is mandatory. Add `code-review` for code changes and `runtime-validation` for user-visible/runtime changes. Agent/runtime/control-plane changes additionally require `agent-trace-analysis` with real trace evidence. Coding work requires `/caveman` and `/coding-guideline`; frontend/browser work also requires `/impeccable` and Claude routing when supported.
