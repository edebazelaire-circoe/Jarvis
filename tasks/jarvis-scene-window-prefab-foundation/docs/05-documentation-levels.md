# 05 — Documentation Levels

These are planning estimates only. Slice 00 must perform a blind repository audit first and replace them with evidence-backed levels.

| Concept | Estimated current level | Required level | Requirement |
| --- | ---: | ---: | --- |
| Scene ownership / Brain-to-scene boundary | 1-2 | 2 | Canonical contract for who may create/update/remove visible objects |
| Window families | 1-2 | 3 | Named families + reusable prefab implementations + conformance tests |
| Prefab definition | unknown | 3 | Canonical schema + validator + runtime loader |
| Prefab instance | 0-1 | 3 | Explicit instance contract separated from definition |
| Prefab inputs | 1 | 3 | Primitive + structured input schema and validation |
| Prefab behavior lifecycle | 1 | 3 | Mount/update/unmount contract + cleanup tests |
| Prefab event bridge | 0-1 | 3 | Semantic event contract and authority boundary |
| Base prefab protection | 0 | 3 | Explicit-intent gate + tests |
| Prefab provenance/versioning | 0-1 | 3 | Persisted/inspectable derivation metadata |
| Agent prefab operations | 0-1 | 3 | Tool/MCP contracts + trace tests |
| Shared prefab library UI | 1 | 3 | Browse/search/preview/manage surface with runtime validation |
| Presentation integration seam | 1 | 2 | Public consumption contract only; behavior implementation remains separate |

## Slice 00 rule

If the blind audit finds any concept already at Level 3, reuse it and remove redundant planned work. If a contract is ambiguous, resolve that contract before behavior-heavy Slices. Do not build a second system beside an existing canonical one.
