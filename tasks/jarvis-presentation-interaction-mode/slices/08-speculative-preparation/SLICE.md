# Slice 08 - Implement speculative preparation, delegation, and staged display resources

## Goal
Let Presentation proactively research and prepare useful material from ambient context while keeping work restricted, lower priority, bounded and normally invisible.

## Context
Current normal back-brain requires addressed admission. Preserve it. Presentation needs a distinct speculative path, not a weakened addressed gate.

## Canonical Concepts
Presentation speculative work admission; priorities P1-P4; working-set resources; existing Display MCP/Scene authority.

## Scope
### In Scope
- Add/reuse distinct speculative analysis/work admission owned by Core or policy owner.
- Permit safe research/preparation: read/search, document resolution, code inspection, web/news lookup through available tools, data analysis, fact verification, display prep.
- Ambient does not grant persistent-write or unrelated side-effect authority.
- Lower-priority sub-agents with concurrency/budget/dedupe controls.
- Normalize results/provenance into working set.
- Prepare hidden/staged scene artifacts/windows where useful.
- Reuse hidden -> visible later.
- Add safe structured chart/table descriptor only if existing Scene cannot represent need; no arbitrary executable HTML.
- P0/P1 can preempt/deprioritize speculative work.
### Out of Scope
Personalized fact-check aggressiveness; Meeting; automatic long-term memory writes.

## Dependencies
Slices 04, 06, 07.

## Implementation Steps
1. Load `/caveman` and `/coding-guideline`.
2. Audit existing `back_brain` speculative support before creating machinery.
3. Define allowed capabilities and forbidden effects.
4. Add/integrate priority/budget scheduler.
5. Coalesce repeated work by topic/resource key.
6. Normalize results into working-set resources.
7. Stage display objects hidden and retain IDs.
8. Cancel/evict on mode/session changes.
9. Test authority, priority, dedupe, staging and stale rejection.

## Files Likely Touched
`back_brain.py` or adjacent presentation service; owned jobs/delegation; agent routing/subagent scope; Display MCP/Scene only if narrowly needed; working-set modules; tests.

## Architecture Constraints
Do not weaken addressed admission; ambient cannot persistent-write; Scene authority remains canonical; explicit turns retain reserved capacity.

## Automated Validation
Back-brain speculative/adversarial, agent routing, Scene artifact/visibility, work-state, priority/capability tests.

## Acceptance Criteria
Ambient can launch useful bounded work; results reusable; visuals can stage hidden; no ambient side-effect authority; explicit interaction not starved.

## Documentation Updates
Document capability boundaries, priorities and staging.

## Handoff Notes
Prefer existing speculative primitives if the freshness audit confirms they fit.
