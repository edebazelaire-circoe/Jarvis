# Implementation strategy

## Order of work

### Phase A — lock product semantics
1. Slice 00 audits current `main` and resolves Task Types.
2. Slice 01 introduces the canonical Presentation product edition and Board lock.
3. Slice 02 gives the installed product a stable AppData data root and migration/restore behavior.
4. Slice 03 formalizes internal-document ownership and explicit export semantics.
5. Slice 04 closes the broad agent write/shell boundary.

These are the architectural prerequisites. Packaging before these would freeze unsafe or ambiguous behavior into an installer.

### Phase B — product services and distribution
6. Slice 05 integrates the allowed connector set and makes the IGuard seam implementation-ready.
7. Slice 06 produces the private-runtime packaging model and dependency/license manifest.
8. Slice 07 builds installer/first-run/readiness/repair flow.

### Phase C — user experience
9. Slice 08 performs the Presentation Edition product-shell and Presentation workflow UI pass.
10. Slice 09 performs the dedicated editing UX pass.

Slices 05, 08 and parts of 09 can run in parallel once their hard dependencies are satisfied; the Project Manager should minimize hot-file conflicts.

### Phase D — release proof
11. Slice 10 builds production health/recovery/CI/release artifact gates.
12. Slice 11 runs final clean-machine Windows E2E and Human validation.

## Migration strategy
- Existing development `~/.jarvis/instances/<repo-hash>/data` remains valid for development.
- Installed edition selects the stable product root explicitly rather than inferring from repository path.
- Migration from a prior installed/product profile must be copy-first, integrity-checked, non-destructive and documented. Reuse existing SQLite backup/migration rules.
- Never silently merge two independent Jarvis data roots.
- Keep canonical relative references in databases where current contracts already rely on relocatable roots.

## Legacy Boards
Presentation Edition may encounter stored Assistant/Meeting Boards. Preserve their data. They must not become active through normal product flows. Define a clear unavailable/read-only representation and a deterministic startup fallback to an available Presentation Board/new-board onboarding.

## Packaging strategy
Keep `setup.ps1` as a developer bootstrap unless a deliberate migration says otherwise. Add a production packaging path that builds from a known source SHA and produces a versioned installer/artifact. Private runtimes must be pinned and verified.

## Rollback
Each schema/storage migration must preserve the repository's existing backup doctrine. Installer updates must not erase AppData. A failed new version must leave a documented rollback path that does not require deleting user data.

## Scope control
If implementation discovers a need for server/cloud decomposition, cross-device sync, Meeting behavior, Assistant behavior, or unrestricted computer-use, record it outside the critical path. Do not expand V1 to solve it.
