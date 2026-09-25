# Slice 06 — Add the scoped calibration agent and full voice feedback loop

## Goal

Let a dedicated calibration agent interpret evidence plus user feedback, form falsifiable hypotheses, and run bounded trials.

## Context

This Slice belongs to the successor adaptive-calibration task. The prior UI refinement is already merged; work from current `main`, never from the historical task branch.

## Canonical Concepts

Bare Hands canonical contracts; current `docs/barehands-contracts.md`; current implementation and tests; current Jarvis agent/voice/MCP contracts

## Scope

### In Scope

- Calibration-session agent context containing measures, current/effective settings, trial history and user feedback.
- Voice-first free-form feedback ingestion.
- Hypothesis list with evidence/confidence/status, not one hard-coded diagnosis.
- Bounded actions: inspect evidence, apply trial, rollback, accept, rerun current exercise, move to next validated exercise.
- Update confidence after trial outcomes; do not repeat disproven cause without new evidence.
- Receipts state what actually changed.
- UI fallback controls for users who do not use voice.

### Out of Scope

- LLM in per-frame loop.
- LLM inventing or rewriting measurements.
- General unrestricted settings tool.
- Permanent autonomous learning outside calibration.

## Dependencies

01, 02, 03, 04, 05

## Implementation Steps

1. Freshness-check current Jarvis agent/voice/MCP architecture and active task changes.
2. Define smallest scoped control plane compatible with current agent runtime.
3. Route calibration utterances to this mode while overlay/session is active.
4. Provide structured evidence summaries and trial actions.
5. Add agent trace fixtures for ambiguous/falsified hypotheses.
6. Prove readback receipts and rollback.

## Files Likely Touched

- current agent/voice routing modules identified by freshness audit
- Bare Hands MCP/command/session modules
- calibration UI
- tests/prompts/docs

## Architecture Constraints

Agent authority is calibration-scoped and temporary. It can request only validated trial actions; persistent acceptance remains explicit.

## Automated Validation

Real trace evidence shows the agent grounds explanations in provided measurements, tests alternatives after a failed trial, and never claims a setting changed without a matching receipt.

## Acceptance Criteria

User can conduct the calibration conversationally without knowing parameter names.

## Documentation Updates

Update `docs/barehands-contracts.md` and relevant operational/user documentation for every changed canonical concept. Update this task LOG with durable execution decisions and evidence references.

## Handoff Notes

Baseline `qa-verification` is mandatory. Add `code-review` for code changes and `runtime-validation` for user-visible/runtime changes. Agent/runtime/control-plane changes additionally require `agent-trace-analysis` with real trace evidence. Coding work requires `/caveman` and `/coding-guideline`; frontend/browser work also requires `/impeccable` and Claude routing when supported.
