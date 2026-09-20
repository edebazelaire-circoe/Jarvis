# Slice 00 — Project Manager readiness and orchestration gate

## Goal

You are the Project Manager and orchestrator for this handoff. Execute this Slice yourself; do not delegate it. Decide whether the handoff is ready to dispatch and repair planning if the repository has moved.

## Context

The Bare Hands design was produced against repository evidence from 2026-09-19, but current Control Center/Constellation and voice-command work may have evolved. Implementation must begin from a blind audit, not from trusting this handoff blindly.

## Canonical Concepts

- Bare Hands V1 decision log
- current native Bare Hands implementation/tests
- current Constellation/frame/star component contracts
- current voice-command registration/dispatch
- Workspace Task Type vocabulary
- clean-room native vs AGPL third-party boundary

## Scope

### In Scope

1. Perform an independent blind repository/context audit based only on the Slice goals before reading this handoff's documentation-level conclusions.
2. Inspect current Bare Hands, Control Center/Constellation, settings, voice, tests and third-party licensing boundaries.
3. Reconcile findings against this handoff and classify readiness as READY, CONTEXT_REWORK_REQUIRED, CONFLICT, or HUMAN_DECISION_REQUIRED.
4. Resolve valid Workspace Task Types for every implementation Slice.
5. Repair planning as necessary: enrich contracts, split/reorder/add/supersede Slices, or correct stale file references. Do not edit product code in Slice 00.
6. Require a targeted freshness check immediately before every future Slice dispatch.

### Out of Scope

- Product code implementation.
- Silent product-scope changes that contradict locked user decisions.

## Dependencies

none

## Implementation Steps

1. Audit repository state and latest main SHA.
2. Verify current implementation facts: MediaPipe backend, assets, click anchor, settings, tests, any existing Bare Hands evolution.
3. Locate current frame/star/Constellation APIs and voice-command extension points.
4. Verify the existing task/docs conventions and applicable skills.
5. Resolve Task Types from the workspace's real vocabulary; do not invent labels.
6. Reconcile conflicts. If a locked decision conflicts with current architecture but can be implemented compatibly, update planning. If it requires changing the product decision, return HUMAN_DECISION_REQUIRED.
7. Record the readiness state and revised dependency graph in task planning artifacts/LOG as appropriate.
8. Do not dispatch any Slice unless state is READY.

## Files Likely Touched

- Task handoff planning files only.
- Repository product code is read-only during this Slice.

## Architecture Constraints

- Preserve all locked user decisions unless a human changes them.
- Do not treat upstream AGPL code as reusable native implementation code.
- Do not invent a voice/Constellation API when the current repository can answer the question.

## Automated Validation

Planning consistency check: all Slice IDs/dependencies resolve, Task Types are valid, canonical references exist or are intentionally marked discover-at-runtime, and no implementation Slice is dispatchable before READY.

## Acceptance Criteria

- Blind audit completed and reconciled.
- Readiness state explicitly recorded.
- Valid Task Type assigned for every dispatchable Slice.
- Current component/voice integration points are identified.
- No unresolved contradiction remains hidden.

## Documentation Updates

Update task planning only where repository freshness requires it.

## Handoff Notes

QA doctrine for all later Slices: baseline qa-verification; code changes add code-review; user-visible/runtime changes add runtime-validation; agent/tool/routing changes add agent-trace-analysis with real evidence. Human validation never substitutes for machine QA.
