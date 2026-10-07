# 05 — Documentation Levels

These were planning estimates. Slice 00 replaced them with evidence-backed levels (doc 06 R0); **Slice 09 recorded the final levels** in the last column (canonical copy: `docs/prefabs.md` › *Documentation levels*).

| Concept | Estimated current level | Required level | Requirement | Final (S09) |
| --- | ---: | ---: | --- | ---: |
| Scene ownership / Brain-to-scene boundary | 1-2 | 2 | Canonical contract for who may create/update/remove visible objects | 3 |
| Window families | 1-2 | 3 | Named families + reusable prefab implementations + conformance tests | 3 |
| Prefab definition | unknown | 3 | Canonical schema + validator + runtime loader | 3 |
| Prefab instance | 0-1 | 3 | Explicit instance contract separated from definition | 3 |
| Prefab inputs | 1 | 3 | Primitive + structured input schema and validation | 3 |
| Prefab behavior lifecycle | 1 | 3 | Mount/update/unmount contract + cleanup tests | 3 |
| Prefab event bridge | 0-1 | 3 | Semantic event contract and authority boundary | 3 |
| Base prefab protection | 0 | 3 | Explicit-intent gate + tests | 3 |
| Prefab provenance/versioning | 0-1 | 3 | Persisted/inspectable derivation metadata | 3 |
| Agent prefab operations | 0-1 | 3 | Tool/MCP contracts + trace tests | 3 |
| Shared prefab library UI | 1 | 3 | Browse/search/preview/manage surface with runtime validation | 3 |
| Presentation integration seam | 1 | 2 | Public consumption contract only; behavior implementation remains separate | 2 |

## Slice 00 rule

If the blind audit finds any concept already at Level 3, reuse it and remove redundant planned work. If a contract is ambiguous, resolve that contract before behavior-heavy Slices. Do not build a second system beside an existing canonical one.
