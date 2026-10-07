# 03 — Implementation Strategy

## Rollout order

1. **Blind audit and contract recovery.** Find the real scene/window/prefab implementations and the prior Rework FENETRES decisions in the Jarvis repository.
2. **Canonical schema.** Establish the prefab definition/instance contracts and protection rules before changing runtime behavior.
3. **Dynamic runtime.** Make valid prefabs discoverable/loadable without per-prefab core code edits.
4. **Scene bridge.** Connect prefab instances to the existing scene contract without leaking DOM concerns upward.
5. **Window migration.** Convert the already-defined window families into the new reusable base-prefab model.
6. **Structured/interactive proof.** Implement at least one data-driven interactive prefab proof such as checklist, exercising array/object inputs and semantic events.
7. **Agent operations.** Expose controlled read/instantiate/fork/create/save operations.
8. **Library management.** Make the shared library inspectable and understandable to humans and agents.
9. **Hardening.** Migrate call sites, remove duplicate legacy paths only when proven safe, and run full regression/visual/runtime validation.

## Compatibility with Presentation mode

The foundation should expose stable contracts that Presentation mode can consume later:

- query/search prefab catalog
- instantiate prepared visual material
- update an existing instance with fresh data
- bring an instance forward / hide / replace it
- preserve instance provenance and board/task ownership

Do not implement presentation timing, initiative policies, ambient transcript interpretation, or speech behavior here.

## Migration constraints

- Preserve current scene behavior before replacing legacy window construction.
- Prefer adapters around legacy windows before a broad rewrite if the audit finds a large installed surface.
- Do not delete a legacy renderer until all call sites and runtime states are covered by tests and the replacement path.
- If the real repository already has a prefab system, extend and converge it rather than creating a parallel catalog/runtime.
- If naming differs from this handoff, preserve canonical repository terminology and update this handoff's docs during Slice 00 reconciliation.

## Dependency rule

No Presentation-content integration Slice should depend on speculative internals. It should depend only on the stable public scene/prefab contracts produced by this task.
