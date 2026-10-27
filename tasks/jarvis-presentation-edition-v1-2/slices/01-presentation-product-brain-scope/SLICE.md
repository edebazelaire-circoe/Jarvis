# Slice 01 — Presentation product brain scope

## Goal
Make Presentation Edition's brain capable for project/research/presentation work while mechanically refusing general Jarvis development and arbitrary machine coding.

## Context
The current role registry exposes a generic `coder` role with Bash/Write and the current CLI can be broadly permissive. Parent V1 already planned confinement. V1.2 clarifies the intended positive scope: research, interviewing, conceptualization, approved connectors and bounded Presentation authoring remain available.

## Canonical Concepts
- `jarvis/domain/subagent_roles.py` role registry and generated brain rules.
- `jarvis/domain/work_methods.py`.
- Agent routing/profiles and tool grants.
- Parent V1 capability/confinement Slice.
- Presentation authoring/Remotion capability contracts.

## Scope
### In Scope
- define a Presentation Edition capability manifest/policy consumed by prompt, role exposure, agent profiles and tool routing;
- remove/disable generic coder/development affordances from the distributed Presentation product path;
- refuse instructions to edit the Jarvis repository, modify arbitrary source projects, run arbitrary shell commands or write outside Jarvis-owned bounded surfaces;
- preserve Interviewer, Research, Web Research, Research Lead, Concept, QA and relation tools;
- preserve document search, Board/Dossier tools, CIRCOE Mail/Calendar, Drive/IGuard connector access when configured;
- preserve bounded Presentation authoring: Remotion/prefab code generation/rendering only through the Presentation pipeline;
- make the refusal true at tool/profile/capability level, not prompt prose only.

### Out of Scope
- redesigning the organic orchestration system;
- removing the coder role from the shared repository for developer editions;
- granting generic Bash merely because Remotion uses code internally.

## Dependencies
- `00-project-manager`.

## Implementation Steps
1. Audit current edition/product-policy seams and parent V1 confinement design; choose one owner.
2. Add/extend a Presentation Edition capability manifest covering allowed roles, MCP/tool families, local code capability and forbidden development surfaces.
3. Make brain prompt/rules describe the Presentation project role: interview/research/organize/create; no Jarvis development.
4. Filter model-visible role/tool catalog in Presentation Edition so generic coder paths are not suggested or routable.
5. Ensure Presentation authoring invokes a bounded profile/capability that can create required Remotion/prefab code only within Jarvis-managed Presentation storage/runtime roots.
6. Hard-refuse attempts to mutate the Jarvis source repo or arbitrary filesystem even through direct API/tool calls.
7. Verify approved connector tools stay available.
8. Add diagnostics for capability refusals with stable codes; never leak secret paths/tokens.

## Files Likely Touched
Product-edition/capability policy modules; agent prompt/routing/profile code; `subagent_roles.py` exposure logic if appropriate; Presentation authoring profile; tests/docs. Exact files are chosen after Slice 00 freshness audit.

## Architecture Constraints
- one capability policy, not separate contradictory UI/prompt/tool allowlists;
- shared developer code remains available outside Presentation Edition;
- Presentation coding is a named bounded capability, not general shell authority.

## Automated Validation
- unit tests for policy matrix and direct bypass attempts;
- model-visible catalog snapshot tests;
- runtime tests proving Research Lead, documentary/web tools and approved connectors are still reachable;
- Presentation authoring smoke test proving Remotion/prefab generation still works;
- malicious/direct request tests proving Jarvis repo edits/arbitrary shell/filesystem writes are refused;
- real agent trace analysis showing routing chooses research/presentation roles and does not spawn `coder` for product requests.

## Acceptance Criteria
- product brain cannot become a general Jarvis developer;
- research/connectors remain functional;
- Presentation authoring still produces working bounded code/render output;
- enforcement survives direct tool/API attempts and is not prompt-only.

## Documentation Updates
Update the canonical Presentation Edition capability contract and any role/tool catalog docs.

## Handoff Notes
Coordinate with parent V1 confinement work; supersede duplicate implementation rather than layering two security policies.