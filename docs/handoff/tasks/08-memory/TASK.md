# Task 08 - Implement Markdown memory and local search index

## Goal

Donner a Jarvis une memoire locale persistante, lisible et reconstructible.

## Context

The source of truth is Markdown. The index is an acceleration layer, not canonical data.

## Scope
### In Scope
- Charger `/caveman` et `/coding-guideline`.
- Configurable memory root.
- Safe Markdown read/append.
- SQLite FTS or equivalent simple local text index.
- Rebuild index.
- Search/read tools.
- Write through ActionBroker.

### Out of Scope
- Embeddings/vector DB.
- Automatic personality profiling.
- Obsidian plugin dependency.

## Dependencies

Tasks 02 and 07 complete.

## Implementation Steps

1. Define memory IDs/paths.
2. Enforce canonical root containment.
3. Implement MarkdownMemoryBackend.
4. Implement local FTS index as derived state.
5. Add atomic append/write behavior.
6. Rebuild on startup only if needed or explicit command.
7. Wire memory tools to registry/broker.

## Files Likely Touched

- `jarvis/adapters/markdown_memory.py`
- `jarvis/adapters/*index*.py`
- `jarvis/ports/memory.py`
- memory fixtures/tests

## Architecture Constraints

No note can escape configured memory root. Index can be deleted and rebuilt without data loss. Writes require broker confirmation.

## Testing Requirements

- Traversal and symlink tests.
- Search ranking smoke tests.
- Rebuild determinism.
- Persistence across process restart.
- Failed write does not corrupt index/source.

## Acceptance Criteria

- Search finds seeded facts.
- Confirmed memory append persists Markdown.
- Restart retrieves persisted fact.
- Deleting index and rebuilding restores search.

## Documentation Updates

Document memory layout and backup semantics.

## Handoff Notes

Keep the first schema boring. Rich metadata/embeddings can be added after V1 evidence.
