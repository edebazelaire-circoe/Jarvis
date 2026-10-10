# Slice 07 — Wiki knowledge assets

## Goal  
Introduce structured Wiki/document knowledge as a first-class asset distinct from personal durable memory.

## Context  
Project facts and reference material should be reusable by agents without polluting personal memory.

## Canonical Concepts  
KnowledgeAsset, Wiki, provenance, scope, loadout.

## Scope  
### In Scope  
Wiki asset schema, ingestion/indexing, source links/version, search/read API, private/project/team scope, rebuild, Brain/agent consumption.  
### Out of Scope  
CodeGraph extraction and Skill execution.

## Dependencies  
01,03,05.

## Implementation Steps  
Define asset model; implement local storage/index; import project docs safely; expose retrieval; tag provenance; integrate with loadout interface; test stale/update behavior.

## Files Likely Touched  
knowledge domain/ports/adapters, Brain context assembly, tests.

## Architecture Constraints  
Wiki is knowledge, not an excuse to duplicate canonical personal memory. Source/version must be visible. Coding uses /caveman and /coding-guideline.

## Automated Validation  
Ingestion/update/delete-rebuild tests, scope isolation, retrieval fixtures, trace evidence.

## Acceptance Criteria  
Agents can retrieve current project knowledge with source provenance and without cross-scope leakage.

## Documentation Updates  
Knowledge asset contract and ingestion lifecycle.  


## Slice 00 contract

Binding contract, dependencies, wave and QA tier: see `docs/06-resolved-architecture.md` section 3 (this Slice, including any 05b/10a/10b split). It overrides the template above. Inherited red tests: `slices/00-project-manager/READINESS.md`.
