# Documentation Levels

| Concept | Current level at handoff creation | Required level | Action |
| --- | --- | --- | --- |
| Existing Agent/CLI settings semantics | 2-3 | 3 | Preserve canonical docs/tests; do not fork semantics. |
| Existing Voice settings schema | 3 | 3 | Preserve schema-driven rendering and compatibility rules. |
| Memory settings | 3 | 3 | Preserve server-described schema and documented precedence. |
| Wake-word settings | 2-3 | 3 | Preserve provider/restart contract; relocate surface only. |
| Appearance / scene view preferences | 2 | 3 | Document canonical ownership and new destination; keep localStorage contract. |
| Bare Hands settings vs tools vs test surfaces | 2-3 | 3 | Keep lifecycle/tool ownership separate from Settings; codify which controls are ordinary vs Labs. |
| Sub-agent role Settings | 2 | 3 | Integrate new role/work-method surface into the new IA and document its canonical home. |
| Settings top-level information architecture | 1-2 (old contract exists but is stale) | 3 | **Slice 01 prerequisite**: create canonical six-category registry/contract and conformance tests. |
| Settings section registration lifecycle | 0-1 | 3 | **Slice 01 prerequisite**: define registration, uniqueness, cleanup and alias rules. |
| Settings visual shell | 1 | 2-3 | Slice 02 creates reusable layout/components and documents usage. |
| Legacy tab aliases | 1 | 2 | Slice 01/09 define and test temporary compatibility mapping. |

## Important stale contract

`tasks/jarvis-settings-model-catalog-ux/docs/settings-ia-contract.json` documented an earlier Settings organization and remains useful evidence for live setting metadata. It is **not** the target navigation contract for this task. Slice 01 must supersede its navigation portion without invalidating the runtime metadata it captured.
