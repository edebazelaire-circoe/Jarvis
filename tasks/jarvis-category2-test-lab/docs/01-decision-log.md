# 01 - Decision Log

Locked during the 2026-09-12 grill:

1. Native Jarvis subsystem, not a pytest family.
2. One diagnostic identity with specialized execution profiles.
3. No intelligence embedded in Test Lab.
4. Native internal API is canonical; adapters are thin; MCP optional.
5. Every execution creates a persistent/replayable/comparable TestRun.
6. Runs isolated by default; real resources only when a profile requires them.
7. Metrics/assertions/score are diagnostic-specific; dashboard aggregation is secondary.
8. Stable catalog plus safe ad-hoc scenarios composed from controlled primitives.
9. Run-local overrides and parameter sweeps are allowed; permanent config mutation is forbidden.
10. Real sessions normalize to first-class DiagnosticBundle objects.
11. `hardware:guided` is first-class and may require explicit user actions.
12. Official diagnostics use declarative manifests plus specialized code where needed.
13. Each TestRun executes in a supervised isolated worker, not inside Control Center.
14. Cost/capability gates are mechanical and profile-aware.

The transcript from 2026-09-12 is evidence for seed diagnostics, not a frozen description of current `main`. Current code must always be audited before implementation or diagnosis.
