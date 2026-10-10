# 05 - Documentation levels and owners

Scale: Level 0 implicit; Level 1 canonical named; Level 2 dedicated contract for required/default/optional/variable/forbidden; Level 3 implementation/validator/template/conformance gate.

| Concept | Current branch at snapshot | Required after task | Canonical owner |
| --- | --- | --- | --- |
| Presentation aggregate, Score, DA, scene controls, edit, history, variants | Level 3 | Level 3 reuse | `docs/presentation-studio.md`, Presentation Studio Core |
| Scene/Prefab runtime and validation | Level 3 | Level 3 reuse, extend compat metadata | `docs/prefabs.md`, `PrefabService` |
| Browser fullscreen | Level 3 browser-only | Level 3 measured target constraints | `docs/presentation-studio.md`, `surface_fullscreen` |
| Board/Session and artifact links | Level 3 | Level 3 reuse | `docs/boards.md`, `docs/artifacts.md` |
| Artifact parent/derivative semantics for mutable presentations | Level 0-1 | Level 2 before code, Level 3 after | `docs/artifacts.md` + new presentation extension |
| EngineSelectionPolicy / PresentationEngine | Level 0 | Level 2 before code, Level 3 after | `docs/presentation-studio.md` / engine module |
| Remotion local host and plugin installer | Level 0; remote MCP plugins Level 3 only | Level 2 then 3, no incorrect reuse of remote MCP contract | `docs/mcp/plugins.md` + local capability documentation |
| Remotion Player, Studio and score adapter | Level 0 | Level 3 | engine adapter and host docs |
| Parameter bridge and source-edit controls | Slidecar Level 3; Remotion Level 0 | cross-engine Level 3 | `docs/presentation-studio.md`, `docs/prefabs.md` |
| Source asset resolver and self-contained freeze | Level 0 | Level 3 | artifacts/boards/source resolver docs |
| Prefab shop taxonomy, provenance and licenses | Partial, older prefab library model | Level 2 then 3 | `docs/prefabs.md` plus shop UI docs |
| Voice tools and engine policy | planned in old S21 | Level 3 | `docs/mcp/tool-contract.md`, Tool Brain contracts |
| Testing/observability and release readiness | Partial, old S22 pending | Level 3 | `docs/OPERATIONS.md`, replay and integration suites |

PM performs a blind re-audit first and corrects this table for branch drift before dispatch. A missing contract becomes a prerequisite Slice, not a guessed implementation.
