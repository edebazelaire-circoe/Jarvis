# Documentation levels


| Concept | Current | Required | Gap |
| --- | ---: | ---: | --- |
| Scene selection domain contract | 0 | 3 | Add model, resolver, serialization, tests |
| Constellation semantics | 1 | 3 | UI/MCP drift; define canonical rules and parity fixtures |
| Atomic general scene batch | 1 | 3 | `archive_many` exists but general MCP batches are loops |
| Relative group translation | 0 | 3 | Add semantic command and rigid geometry contract |
| MCP output schemas | 1 | 3 | Replace opaque result objects where possible |
| MCP semantic categories | 0 | 2 | Define stable human taxonomy |
| Canonical MCP tool catalog | 0 | 3 | Add shared/introspected registry and parity gate |
| MCP runtime availability | 1 | 2 | Define known/configured/advertised states |
| Control Center MCP inspector | 0 | 3 | Add API, UI, tests, accessibility/runtime validation |


Expected canonical docs after implementation: a scene-selection/batch contract and `docs/mcp/tool-contract.md`; historical `plan-outils-interface.md` should point to delivered contracts and remove stale claims.