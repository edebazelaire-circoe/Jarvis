# Slice 00 — Readiness, independent audit and execution control

## Goal

You are the Project Manager and orchestrator for this handoff. Execute this Slice yourself. Do not delegate Slice 00. Establish a fresh, evidence-backed readiness state before any implementation agent changes product code.

## Context

The task intentionally corrects a foundational Remotion boundary while preserving a recently stabilized compatibility path. Stale assumptions are dangerous: the previous task merged on 2026-10-13 and the current `main` must be re-read.

## Canonical Concepts

Project: `Jarvis`; repository expected: `edebazelaire-circoe/Jarvis`; master project, scene source/version pin, Remotion Studio target, frozen snapshot/render, Variants composition clock.

## Scope
### In Scope

- blind audit before reading this handoff's documentation conclusions;
- repository/branch/test/runtime owner map;
- reconcile blind audit with task assumptions and user mandate;
- repair/split/reorder/supersede Slices when evidence demands it;
- resolve a valid Workspace Task Type immediately before each dispatch;
- enforce QA and Human-validation doctrine.

### Out of Scope

- editing product code yourself;
- touching the user's live Core/data;
- silently expanding into phase C.

## Dependencies

None.

## Implementation Steps

1. Blindly inspect current repository and relevant tests/docs based only on this Slice goal. Record current HEAD and working context.
2. Identify current owners for Studio workspace planning/service/runner, presentation source packaging, render planning/service/runner, Presentation/Variant store, native authoring MCP/tools, Variants Studio/export UI, and regression harnesses.
3. Establish current baseline failures and specifically classify anything inherited from the preceding Remotion task.
4. Only after the blind audit, read this handoff's docs and reconcile facts/terminology.
5. Produce one state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.
6. If not READY, repair planning/docs/slices as allowed; do not dispatch implementation.
7. If READY, choose the next dependency-eligible Slice and perform a targeted freshness check immediately before dispatch.

## Files Likely Touched

Task handoff files only (`tasks/jarvis-remotion-master-project-studio-export/**`) for readiness notes or planning repair. No product code.

## Architecture Constraints

Preserve D1-D10 in `docs/01-decision-log.md` unless a real conflict requires Human escalation. Provisional choices P1-P5 may be refined from fresh evidence.

## Automated Validation

- verify Slice IDs/dependencies/human IDs/metadata are internally consistent;
- verify expected repository exists and current HEAD is captured;
- run a targeted baseline sufficient to know whether Remotion/presentation tests are currently green or have inherited failures;
- no dispatch until evidence is recorded.

## Acceptance Criteria

- blind audit exists and predates reading handoff conclusions;
- reconciliation is explicit;
- readiness state is explicit;
- current baseline failures are classified;
- valid task-type resolution method is known;
- no phase-C work has leaked into A+B.

## Documentation Updates

Update task planning only if the fresh audit proves stale assumptions. Do not pretend product docs are implemented.

## Handoff Notes

Every implemented Slice must receive `qa-verification`; code -> `code-review`; runtime/UI -> `runtime-validation`; agent/tool/prompt -> real `agent-trace-analysis`. QA findings are evidence for you to decide, not automatic approval. A regression introduced by a Slice is blocking and cannot be moved to Issues. Before any Human check, exhaust machine checks.
