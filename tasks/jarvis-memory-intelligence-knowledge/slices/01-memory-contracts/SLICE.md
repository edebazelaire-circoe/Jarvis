# Slice 01 — Memory contracts

## Goal  
Define stable Jarvis contracts separating canonical storage, retrieval/intelligence, consolidation, knowledge assets and agent memory policy.

## Context  
Current MemoryBackend mixes canonical read/write and search. The target must prevent Tencent or any derived index from becoming authority by accident.

## Canonical Concepts  
CanonicalMemoryStore, MemoryRetriever, MemoryConsolidator, KnowledgeAssetProvider, AgentMemoryPolicy.

## Scope  
### In Scope  
Protocols/models, identity/provenance fields, recall result schema, budgets, feature capability reporting, error/degraded semantics.  
### Out of Scope  
Persistent semantic implementation and UI.

## Dependencies  
00.

## Implementation Steps  
Define contracts; map legacy MemoryBackend compatibility; specify source/provenance/version/temporal/confidence fields; define private/shared scopes and loadout policy; add contract tests.

## Files Likely Touched  
jarvis/ports/, jarvis/domain/, tests/unit/, docs/.

## Architecture Constraints  
Canonical storage owns durable truth. Retrieval outputs reference canonical sources or explicitly derived assets. Coding uses /caveman and /coding-guideline.

## Automated Validation  
Protocol/model unit tests; type/static checks; regression suite for existing memory backend.

## Acceptance Criteria  
Legacy Markdown remains usable; future local/Tencent retrievers can implement the same contract without owning canonical writes.

## Documentation Updates  
Add Level-2/3 memory contracts and terminology.  
