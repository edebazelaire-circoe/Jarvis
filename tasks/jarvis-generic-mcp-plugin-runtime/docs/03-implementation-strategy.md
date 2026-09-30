# Implementation strategy

1. **Audit and contract first.** Reconcile the current MCP contract with the new product decision, including concurrent Board/session work touching the same catalog files.
2. **Persist safe plugin definitions before networking.** Define plugin lifecycle/state and credential-vault boundaries with fake/in-memory adapters first.
3. **Implement remote connection/auth behind one manager.** Add transport and auth discovery with deterministic fakes, then controlled live probes.
4. **Merge remote capabilities into the canonical catalog.** Preserve current native catalog parity while adding dynamic external descriptors.
5. **Add `list_tools(intent)` and generic external invocation.** Treat relevance, detail level, output budgets and repeated discovery as explicit contracts.
6. **Propagate the stable gateway across agent runtimes/subagents.** Do not couple plugin auth to one CLI.
7. **Extend the existing MCP Control Center.** Plugin cards and Add/Connect/Disconnect/Enable/Disable flows consume runtime APIs; no hard-coded tool catalogs.
8. **Validate with Circuit Toolbox, then classify/migrate Drive.** Live evidence is a release gate, not an early design dependency.
9. **Run final context-budget, secret-redaction, trace, UI and regression QA.** Remove stale compatibility code only after proof.

## Migration constraints

- The existing MCP inspector and catalog are production contracts. Keep native tool parity green throughout.
- `jarvis-drive` must remain functional until a managed-plugin path can replace it with explicit migration criteria.
- The existing Board/session task may concurrently edit the console MCP/catalog. Slice 00 owns freshness and rebase/split decisions.
- Do not enlarge model context by advertising every external schema. The whole point of `list_tools(intent)` is bounded deferred discovery.
- Do not make plugin availability depend on the Control Center browser being open.
