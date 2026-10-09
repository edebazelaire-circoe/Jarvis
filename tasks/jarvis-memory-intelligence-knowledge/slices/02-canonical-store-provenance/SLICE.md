# Slice 02 — Canonical store and provenance

## Goal  
Extend Jarvis-owned canonical memory with inspectable provenance and lifecycle metadata while preserving human-readable Markdown and rebuildability.

## Context  
Current MarkdownMemoryBackend is durable and secure but notes are minimally structured.

## Canonical Concepts  
CanonicalMemoryStore, provenance, retention class, abstraction level, temporal validity.

## Scope  
### In Scope  
Backward-compatible metadata representation; source IDs; timestamps; confidence/quality; version/revision lineage; contradiction/supersession links; safe mutation path; index rebuild compatibility.  
### Out of Scope  
Automatic consolidation decisions.

## Dependencies  
01.

## Implementation Steps  
Choose readable metadata format; parse legacy files; add safe write/update helpers; preserve path/symlink protections; expose provenance reads; migrate lazily or via explicit tool; expand tests.

## Files Likely Touched  
jarvis/adapters/markdown_memory.py, domain models, tests/unit/test_memory.py, docs.

## Architecture Constraints  
Markdown stays canonical; SQLite/semantic state remains disposable. Protected retention classes are never silently deleted. Coding uses /caveman and /coding-guideline.

## Automated Validation  
Traversal/symlink/corrupt-index tests plus metadata round-trip, legacy compatibility and atomic-write failure tests.

## Acceptance Criteria  
A user can inspect where a memory came from and when; deleting derived indexes loses no durable truth.

## Documentation Updates  
Document metadata schema and retention/abstraction orthogonality.  


## Slice 00 contract

Binding contract, dependencies, wave and QA tier: see `docs/06-resolved-architecture.md` section 3 (this Slice, including any 05b/10a/10b split). It overrides the template above. Inherited red tests: `slices/00-project-manager/READINESS.md`.
