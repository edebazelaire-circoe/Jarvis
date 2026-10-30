# Audited implementation context

Read ../00-project-manager/READINESS.md for source evidence, routing fallback, boundaries and QA tiers. Canonical architecture starts at docs/ARCHITECTURE.md (repository root), docs/scene-selection-batch.md, docs/scene-model.md, docs/mission-history.md, docs/agent-orchestration.md and docs/chat.md. Existing source is authoritative over planning-time path guesses. No duplicate geometry, prefab renderer, fullscreen state machine, status owner or communication bus.

Environment: work only in assigned isolated worktree, use C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe for pytest with working directory set to worktree (pyproject pythonpath=. ensures local imports). Node available. Tests foreground, small focused batches; no full suite before S06. Do not launch/stop user's runtime. Isolated ControlCenter harnesses and own data/ports are permitted. Read CLAUDE.md. Load caveman, coding-guideline, ponytail, error-handling; frontend additionally impeccable. Implementer reports in IMPLEMENTATION.md; independent reviewer writes qa/. Prefix implementation commits S<n>: with Slice number. Do not commit other Slice files.

Exact lifecycle: remote folder current; final Human acceptance pending. No merge to main/push main/cleanup local handoff.

