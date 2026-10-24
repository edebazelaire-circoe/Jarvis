# 07 — Existing task coordination

## Settings shell

`jarvis-settings-ui-reorganization` is already in `Jarvis/task/done/`. Reuse its six-category registry/shell direction and current implementation. Do not restart its entire IA migration.

## Architecture & Agents

`jarvis-architecture-agents-settings-editor` is in `Jarvis/task/done/` and its implementation is reflected in recent `main` commits. Treat its runtime and interaction decisions as canonical.

This refactor may replace/refine visual composition of its Architecture canvas, brain popup and Sous-agents tab, but must preserve:

- canonical role registry;
- live candidate/fallback behavior;
- graph mutability semantics;
- contextual brain config;
- no separate Brains page;
- server-owned model/provider availability.

## Memory & connaissances

`jarvis-memory-knowledge-settings-ui` is still in `Jarvis/task/to-do/` at creation time. Its contracts remain the target semantics for memory UI.

The PM must decide at dispatch time whether:

- this visual task consumes already-merged memory UI foundations;
- memory Slices implement visual composition against the stable runtime directly;
- or memory Slices work against adapters/fixtures and converge after the memory task lands.

Do not duplicate memory APIs or settings persistence to avoid the dependency.
