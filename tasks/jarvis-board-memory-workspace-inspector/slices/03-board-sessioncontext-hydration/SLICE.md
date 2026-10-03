# Slice 03 — Board activation and SessionContext hydration

## Goal
Integrate Board memory with the active Session/SessionContext lifecycle so switching Boards restores useful context without merging unrelated work or loading unbounded data.

## Context
The user wants one Session able to load any Board and thereby change/reinject the agent's context, while Board memory and agent context continue to evolve separately.

## Canonical Concepts
JarvisSession, SessionContext, Board switch/binding, foreground speech authority, Board memory.

## Scope
### In Scope
- Determine the active Board's compact hydration block/pointers.
- Board A -> B -> A context correctness.
- Explicit Board-targeted background/historical reads that do not activate.
- Reconcile Board binding conversation reuse with SessionContext semantics from the prerequisite task.
- Durable Board summary/manifest strategy if needed to avoid filesystem dumps.
- Agent write-target rules: active Board implicit target; inactive Board requires explicit target.

### Out of Scope
- MCP registration.
- Manager UI.
- Meeting live behavior.

## Dependencies
Slice 02 and prerequisite SessionContext implementation verified by Slice 00.

## Implementation Steps
1. Trace current Board switch and agent hydration paths.
2. Insert Board memory brief/pointers at the canonical hydration seam.
3. Preserve foreground/binding atomicity.
4. Add explicit inactive-Board targeting for service-level reads/writes where allowed.
5. Prove no cross-Board context bleed.

## Files Likely Touched
Board service/switch coordinator, SessionContext hydration/runtime modules, agent prompt/context assembly, tests.

## Architecture Constraints
- Never inject all Board files automatically.
- Historical inspection must not promote a binding.
- One foreground speech authority remains true.
- Dormant SessionContexts remain protected per prerequisite contract.

## Automated Validation
`qa-verification` + `code-review` + `runtime-validation` + `agent-trace-analysis` with A/B/A and historical-inspection traces.

## Acceptance Criteria
Switching Boards produces correct bounded context; returning to A recovers A; inspecting B while A is active does not change foreground state or leak B into A implicitly.

## Documentation Updates
Update Board/SessionContext integration contract and agent hydration docs.

## Handoff Notes
Treat any ambiguity about whether Board binding conversations replace or complement SessionContext identity as a blocker to resolve in this Slice, not as an implementation guess.

## Slice 00 contract (agent 0, 2026-10-02)

Binding over the generic sections above; source: `docs/06-resolved-architecture.md`.

- Board brief additions per R3 (kind, relative memory locator, bounded manifest <= 40 entries depth 2, head of `memory/summary.md` <= 2048 bytes), budgeted and tested at the limits.
- `--add-dir <data_root>/boards` for the conversation profile in `claude_local.py` (beside `sessions/`).
- Brain prompt rule (R3) in the canonical prompt catalog; measure the prompt-size delta.
- Prove: Board switch changes the next turn's Board block; does not create/switch/copy a SessionContext; Context switch does not switch Board.
- No MCP, no UI.
