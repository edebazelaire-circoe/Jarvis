# 05 - Documentation levels

| Concept | Current baseline | Target | Required action |
| --- | ---: | ---: | --- |
| Board domain/lifecycle | 3 | 3 | Extend canonically for memory/kind without weakening existing tests |
| Board free-form memory workspace | 0 | 3 | New contract + implementation + safety/conformance tests |
| Session/SessionContext durable semantics | prerequisite task | 3 | Reuse actual landed contract; do not fork |
| Board <-> SessionContext integration | 0/1 | 3 | Dedicated contract, integration tests, hydration rules |
| Artifact registry/provenance | prerequisite task | 3 | Reuse and add Board association/query documentation if needed |
| Historical non-activating inspection | 0/1 | 3 | Service/API/MCP contract + side-effect tests |
| `jarvis-workspace` MCP | 0 | 3 | Native server, shared metadata, catalog/parity/context-budget gates |
| Sessions & Boards Manager UI | 0 | 2 | UI contract and runtime/browser tests |
| Quick Board browser | 3 existing | 3 | Evolve existing UI, preserve semantics |
| Board kind taxonomy | 0/1 | 2 or 3 | Add typed field/migration/tests if absent; no live-mode behavior |

The PM must re-evaluate this table against the execution baseline before declaring `READY`.
