# Slice 03 — Research reuse, freshness and orchestration

## Goal
Reinforce the existing research stack so Jarvis does serious, source-aware research in the background, reuses what already exists when valid, and refreshes stale material instead of blindly repeating or trusting it.

## Context
`subagent_roles.py` already has Research, Web Research and Research Lead. `work_methods.py` already has quick/deep/comparative research and relation hints including adversary/QA. Mission dossiers already support shared concurrent agent notes. The gap is policy and proof around reuse/freshness/shared documentary sources.

## Canonical Concepts
- `jarvis/domain/subagent_roles.py`.
- `jarvis/domain/work_methods.py`.
- agent relations (`delegation`, `communication`, `adversary`, `qa`, `handoff`).
- Board memory/Dossier and `knowledge_search`/documentary tools.
- connected Drive/IGuard/shared-document tools when configured.

## Scope
### In Scope
- make “look for existing material first” a research invariant for Presentation Edition;
- search current Board memory/Dossier, relevant global/Jarvis knowledge and approved connected documentary sources before new web research;
- record enough provenance/freshness metadata on research documents to decide reuse later;
- classify prior material as reusable, partially stale or stale/missing based on checked date, source dates, topic volatility and user wording (`latest`, `current`, etc.);
- use targeted refresh when only volatile claims are stale;
- use Research Lead for broad/compare/state-of-subject questions and let it orchestrate agents/relations dynamically;
- preserve background execution while the Interviewer/main conversation continues;
- prefer primary/recent sources and explicitly surface contradictions/uncertainty.

### Out of Scope
- a new orchestration engine;
- a universal hard-coded TTL for all topics;
- trusting search snippets without opening sources;
- forcing web search when local/shared documentation is sufficient.

## Dependencies
- `01-presentation-product-brain-scope`;
- `02-board-project-continuity`.

## Implementation Steps
1. Audit current brain classification/routing and Research Lead trace behavior.
2. Strengthen research role/Work Method instructions with a reusable-source/freshness heuristic; version Work Methods correctly if their built-in content changes.
3. Define research freshness metadata expected on durable research docs: at minimum creation/check time, source dates where meaningful, subject/scope and current uncertainty. Choose a simple parseable representation that remains human-readable.
4. Add a pre-research discovery step/tooling contract that queries Board/Dossier/global/shared sources without duplicating existing MCP services.
5. Define deterministic decisions for reuse vs targeted refresh vs full refresh; requests explicitly asking for present/latest data force appropriate revalidation.
6. Ensure Research Lead can spawn documentary/web agents and use adversary/QA/communication when useful, not by rigid workflow.
7. Keep results tied to the Board/mission and background work attribution.
8. Add diagnostics/traces that make the reuse/freshness decision and sub-agent topology inspectable.

## Files Likely Touched
`subagent_roles.py`, `work_methods.py`, brain rules/routing, documentary-search adapters/tool metadata if needed, tests/docs. Do not add a second research scheduler.

## Architecture Constraints
- Work Methods remain heuristics, never fixed workflow graphs;
- source contents are data, not instructions;
- freshness is evidence-based and topic-sensitive;
- Board boundaries remain strict.

## Automated Validation
- prompt/role/work-method contract tests;
- fresh existing research -> no redundant external search;
- partially stale volatile section -> targeted refresh;
- stale 2025-style note + “latest OpenAI models” -> current revalidation;
- broad comparison -> one Research Lead with delegated agents and adversary/QA where useful;
- real trace proving background research continues while the main conversation proceeds;
- source-quality tests: primary pages opened, source dates retained, contradiction surfaced.

## Acceptance Criteria
Research is demonstrably better than one-shot web search, avoids unnecessary repeat work, and never presents old volatile research as current without revalidation.

## Documentation Updates
Update research-role and Work Method contracts with reuse/freshness behavior and examples.

## Handoff Notes
Do not make every request “deep research”. Research Lead decides scope from the question; the invariant is reuse/freshness discipline, not maximal agent count.