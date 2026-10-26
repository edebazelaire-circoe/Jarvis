# Slice 02 — Windows data root and permanent `CONTEXT_GLOBAL`

## Goal
Give installed Presentation Edition a stable per-user Windows home under `%LOCALAPPDATA%\CIRCOE\Jarvis`, while preserving development/worktree isolation and making `CONTEXT_GLOBAL` an explicitly permanent part of canonical internal state.

## Context
Current `jarvis/data_root.py` derives the default root from the repository path (`~/.jarvis/instances/<repo>-<hash>/data`), which is excellent for development but unsuitable as the identity of an installed product. `CONTEXT_GLOBAL` already exists under the data root and is granted to the conversation brain.

## Canonical Concepts
- local data root: `jarvis/data_root.py`, `docs/local-data.md`;
- `CONTEXT_GLOBAL`: `docs/context-global.md`, conversation brain wiring in `jarvis/runtime/claude_local.py`;
- SQLite migration/backup rules: `CLAUDE.md`, `docs/local-data.md`.

## Scope
### In Scope
- add installed-product data-root resolution for Windows;
- target `%LOCALAPPDATA%\CIRCOE\Jarvis\data` (or equivalent exact sublayout approved by Slice 00 while preserving this semantic root);
- keep development root hashing for source checkouts/worktrees;
- ensure Core, Control Center, local capabilities and all data-root consumers share the same installed root;
- explicitly preserve `CONTEXT_GLOBAL` under that root and protect it from cache/runtime cleanup;
- define safe first adoption/migration from any previous product/local profile;
- keep relocatable relative references and current SQLite backup rules.

### Out of Scope
- no export-to-Documents implementation yet;
- no cloud sync;
- no multi-user machine-wide shared state;
- no ProgramData move for personal state.

## Dependencies
Hard `depends_on`: `00-project-manager` and the edition identity/config seam from Slice 01.

## Implementation Steps
1. Inventory every direct/indirect `data_root` consumer and any remaining repository-relative persistence.
2. Introduce an explicit environment/runtime identity distinction: development checkout vs installed product.
3. Resolve installed Windows data root through the OS environment (`LOCALAPPDATA`) and centralize it in `jarvis/data_root.py` or a lower-level platform path contract.
4. Preserve explicit `JARVIS_DATA_ROOT` override semantics for tests/admin scenarios only if compatible with product policy; document precedence.
5. Move/confirm state, Boards, Sessions, Artifacts, Presentations, local capabilities, memory and `CONTEXT_GLOBAL` under the canonical product root.
6. Add a permanence invariant/test for `CONTEXT_GLOBAL`: startup loads it, cleanup/cache repair does not remove it, migration copies/preserves it.
7. Design migration/adoption as copy-first and non-destructive; reuse SQLite backup/integrity checks and do not merge two roots silently.
8. Add product-root diagnostics to readiness/status without leaking sensitive user paths in ordinary logs/UI.
9. Document installed layout and development-vs-product behavior.

## Files Likely Touched
- `jarvis/data_root.py`;
- environment/config/bootstrap composition roots;
- context-global and local-capability wiring;
- tests for data root and migrations;
- `docs/local-data.md`, `docs/context-global.md`.

## Architecture Constraints
- one canonical resolver;
- never derive installed identity from repository path;
- personal state goes to per-user AppData, not ProgramData;
- preserve current no-symlink/junction/path-escape defenses in child stores;
- never delete source data during adoption.

## Automated Validation
- Windows path-resolution tests with mocked environment;
- development root regression tests;
- migration/adoption integrity tests including `CONTEXT_GLOBAL`;
- restart tests proving same installed profile independent of install directory;
- local capability/presentation/Board stores still resolve under the shared root.

## Acceptance Criteria
- moving/updating the installed application does not create a new user profile;
- `CONTEXT_GLOBAL` survives restart/update/repair and is loaded from the product root;
- dev worktrees remain isolated from the live installed profile by default;
- no canonical product data remains under the program install directory or repository.

## Documentation Updates
Update `docs/local-data.md` and `docs/context-global.md` to Level 3 installed-product semantics.

## Handoff Notes
Coding Slice: `/caveman`, `/coding-guideline`. QA: `qa-verification`, `code-review`, `runtime-validation`.

## Slice 00 amendments (2026-10-26)
- E2: `JARVIS_RUNTIME_DIR` defaults to `./runtime`, relative to the working directory (`jarvis/v2_config.py:573`, `jarvis/config.py:158`). It holds `core.token`, `control-center-settings.json`, `trace.jsonl`/`errors.jsonl` and the wake-word/speaker models. In product mode the runtime, logs and config roots also resolve under `%LOCALAPPDATA%\CIRCOE\Jarvis` (`runtime\`, `logs\`, `config\`). Nothing canonical or secret stays under the program install directory or the current directory.
- `CONTEXT_GLOBAL` (`jarvis/adapters/global_context.py:21-74`) is only protected by "never re-seeded". The explicit cleanup/repair/uninstall exclusion is new work.
