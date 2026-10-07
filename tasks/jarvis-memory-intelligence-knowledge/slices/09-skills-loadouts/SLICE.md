# Slice 09 — Skills and agent loadouts

## Goal  
Make reusable Skills/SOPs first-class assets and select memory/knowledge loadouts per agent/task.

## Context  
Tencent-style reusable skills are valuable immediately for Jarvis's coding/review/research agents.

## Canonical Concepts  
Skill asset, loadout, agent scope, capability policy.

## Scope  
### In Scope  
Skill schema/version/provenance; discovery; enable/disable; per-agent/task loadout; Wiki/CodeGraph/Skill composition; isolation; trace of injected assets.  
### Out of Scope  
Unreviewed autonomous cross-agent publication of private user memory.

## Dependencies  
01,07,08.

## Implementation Steps  
Define Skill asset contract; create local registry; add extraction/import path with validation; implement loadout resolver; integrate into agent launches/prompts/tools; expose effective loadout state.

## Files Likely Touched  
agent routing/config, knowledge assets, prompts/runtime, tests.

## Architecture Constraints  
Explicit policy decides what is shared. Skills are versioned reusable instructions, not hidden prompt mutation. Coding uses /caveman and /coding-guideline.

## Automated Validation  
Loadout resolution, conflicting skill/version rules, isolation tests, trace evidence for coder/reviewer/research profiles.

## Acceptance Criteria  
Different agents receive appropriate, inspectable assets and no unauthorized private memory leaks into shared loadouts.

## Documentation Updates  
Skill lifecycle, loadout policy and agent matrix.  
