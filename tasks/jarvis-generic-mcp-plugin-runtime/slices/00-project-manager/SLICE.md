# Slice 00 — Project Manager readiness gate

## Goal
Blind-audit the current Jarvis repository, canonical MCP docs/tests and active task queue before implementation. Reconcile drift from commit 58eeb181e592bb10c4266fb265c33c74151f0a86, especially concurrent board/session edits around MCP catalog/console files. Resolve valid Workspace Task Types and record READY, CONTEXT_REWORK_REQUIRED, CONFLICT, or HUMAN_DECISION_REQUIRED. No product code changes in this slice.

## Dependencies
None.

## Quality gates
Every implemented slice gets qa-verification. Code changes get code-review. User-visible/runtime work gets runtime-validation. MCP/tool/routing/agent work gets agent-trace-analysis. Coding slices load /caveman and /coding-guideline; frontend also /impeccable. Regressions caused by this slice are blocking and cannot be parked in Issues/.

## Acceptance criteria
Implement only after dependencies are green; update canonical docs/tests; preserve the single MCP catalog and secret boundary; provide evidence required by this slice before marking complete.
