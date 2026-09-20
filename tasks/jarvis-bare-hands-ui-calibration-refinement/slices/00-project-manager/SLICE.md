# Slice 00 — Project Manager readiness and reconciliation gate

## Goal

You are the Project Manager and orchestrator for this handoff. Execute this Slice yourself; do not delegate it. Reconcile the UI-refinement handoff against the current repository and the already-implemented Bare Hands V1 before any coding is dispatched.

## Context

This is not a greenfield Bare Hands task. The original `jarvis-bare-hands-v1` work has already landed substantially in the repository. This task changes information architecture and calibration UX while preserving established interaction semantics.

## Canonical Concepts

- `docs/barehands-contracts.md`
- prior `Jarvis/task/to-do/jarvis-bare-hands-v1/` handoff
- current Control Center HUD/dock/context-menu conventions
- Bare Hands lifecycle/tool/profile/calibration/tutorial/diagnostic contracts
- scene frame/window target/capture/geometry contracts
- Bare Hands voice/MCP command contract

## Scope

### In Scope

1. Perform an independent blind audit of current `main` based only on this Slice's goals before reading this handoff's documentation-level conclusions.
2. Inspect current Bare Hands lifecycle UI, tools/settings UI, calibration shell/steps, tutorial module, diagnostics surface, command channel, and scene frame interaction.
3. Reconcile the audit with this handoff and record one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.
4. Resolve the Workspace's valid Task Type vocabulary and assign a valid type to each implementation Slice before dispatch.
5. Decide the exact compatibility migration for the existing `tutorial` command/state. Preferred behavior is a deprecated alias to calibration if that preserves the command contract cleanly; no separate tutorial flow may remain.
6. Verify the exact main-HUD insertion point and existing context-menu component that should be reused.
7. Verify current installed tools from the canonical contract rather than trusting planning prose.
8. Repair planning where current code has moved: adjust file references, split/reorder/add Slices if necessary, without changing locked product decisions.
9. Require a targeted freshness check immediately before every Slice dispatch.

### Out of Scope

- Editing product code.
- Reopening contextual Bare Hands interaction semantics already canonical in the repository.
- Inventing new tools or gesture actions.

## Dependencies

none

## Implementation Steps

1. Read current repository state and latest main SHA.
2. Audit canonical Bare Hands docs/contracts before reading this handoff's conclusions.
3. Inspect `control_center.html`, Bare Hands page modules, calibration/tutorial/recorder modules, server settings/profile code, command channel, scene window interaction and relevant tests.
4. Compare findings with this task's README and decision log.
5. Resolve Task Types from the actual Workspace vocabulary; do not invent a type.
6. Decide whether legacy tutorial command compatibility is alias, explicit removal/version bump, or another equivalent migration that leaves only one user-facing flow.
7. Update planning only where needed.
8. Record readiness and do not dispatch below `READY`.

## Files Likely Touched

Task handoff planning files only. Product code is read-only during Slice 00.

## Architecture Constraints

- `docs/barehands-contracts.md` remains authoritative for existing interaction behavior.
- Locked UI corrections in this task override older UI-placement decisions from the previous handoff.
- Separate tutorial product UI is no longer allowed.

## Automated Validation

Planning consistency check: Slice IDs/dependencies resolve, current canonical files exist, current installed tool list is known, tutorial migration is explicit, Task Types are valid, and no implementation Slice is dispatchable before READY.

## Acceptance Criteria

- Blind audit completed and reconciled.
- Readiness state explicitly recorded.
- Valid Task Type assigned for every dispatchable Slice.
- Current HUD/context-menu/settings/calibration/tutorial/diagnostic/window integration points identified.
- Tutorial compatibility migration chosen without restoring a separate tutorial flow.
- No hidden conflict with current Bare Hands contracts remains.

## Documentation Updates

Update handoff planning only if freshness requires it.

## Handoff Notes

Every later implemented Slice gets baseline `qa-verification`; code changes add `code-review`; user-visible/runtime changes add `runtime-validation`; agent/MCP/tool/routing changes add `agent-trace-analysis` with real trace evidence. Current-Slice regressions are blocking. Human validation never substitutes for QA.
