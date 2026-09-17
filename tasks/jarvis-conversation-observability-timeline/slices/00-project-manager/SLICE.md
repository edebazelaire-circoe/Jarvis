# Slice 00 — Project Manager readiness and orchestration gate

## Goal

Act as Project Manager. Reconcile this observability handoff with the live Jarvis repository before any implementation dispatch.

## Context

The handoff was built against `main` at `c33207281a5b6a10a6630b8914f19855ea096473`. Existing relevant code includes `jarvis/runtime/journal.py`, `trace_summary.py`, `speech_scheduler.py`, `agent_tasks.py`, Core event infrastructure, and Control Center code.

## Canonical Concepts

- Conversation Event Log
- RuntimeJournal / trace.jsonl
- Core event transport
- Workspace Task Type vocabulary

## Scope

### In Scope

- Blind audit current conversation/event persistence, RuntimeJournal usage, Core event store/transport, agent task traces, voice events, Control Center APIs/UI, and tests.
- Reconcile overlapping active work and the separate voice-arbitration/settings tasks.
- Resolve Workspace Task Types and baseline QA commands.

### Out of Scope

- Product code edits.
- Premature choice of storage technology before auditing existing Core persistence.

## Dependencies

None.

## Implementation Steps

1. 1. Before reading `docs/05-documentation-levels.md` conclusions, perform an independent blind audit of the live repository against this task's goals.
2. 2. Inspect current `main`, git status/worktrees, active parallel branches, relevant canonical docs, implementations, and narrow tests. Record the live SHA.
3. 3. Reconcile the blind audit with this handoff. Correct stale file predictions, split/reorder/add/supersede Slices when necessary, but do not change locked user intent silently.
4. 4. Resolve every implementation Slice to a valid current Workspace Task Type. If no valid type exists, keep that Slice blocked and escalate instead of inventing a type.
5. 5. Establish baseline automated validation and likely integration/conflict zones.
6. 6. Declare exactly one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.
7. 7. Dispatch nothing unless the state is `READY`.
8. 8. Immediately before every later Slice dispatch, perform a targeted freshness check of that Slice's dependencies and affected code.

## Files Likely Touched

- (handoff planning files only)

## Architecture Constraints

- Do not collapse diagnostic telemetry and canonical conversation truth into one unversioned blob.
- Do not expose hidden chain-of-thought.

## Automated Validation

- Identify current release/full verification command.
- Identify narrow tests for journal/Core events/agent tasks/realtime/control-center.

## Acceptance Criteria

- Blind audit recorded and reconciled.
- Every later Slice has a valid Task Type or explicit block.
- One readiness state declared.
- No product code edited.

## Documentation Updates

Update planning docs only when live evidence proves them stale.

## Handoff Notes

Apply the mandatory QA doctrine from the README to every later Slice.

Mandatory QA doctrine for every implemented Slice:
- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation never substitutes for machine QA; escalate machine validation to the maximum reasonable level first.
