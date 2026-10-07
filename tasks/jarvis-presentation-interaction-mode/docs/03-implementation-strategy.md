# Implementation strategy

## Principle

Implement the Presentation semantics independently of unfinished rendering/UI-orchestration details, then bind to the canonical Tool Brain and Scene/Prefab contracts when those contracts are available.

## Order

1. Re-audit repository reality and dependent handoffs.
2. Lock/repair canonical interaction-mode state and activation semantics.
3. Ensure the Control Center exposes the mode correctly without duplicating settings ownership.
4. Wire the existing ambient lane into a structurally separate Presentation context feed.
5. Implement fresh transcript tail and bounded working set.
6. Add background preparation and preemption rules.
7. Implement manifestation policy independent of concrete UI-tool selection.
8. Integrate semantic display/attention intents with Tool Brain.
9. Integrate prepared visual resources with Scene/Prefab runtime.
10. Add observability/attention UI integration.
11. Run deterministic end-to-end scenario validation and hardening.

## Parallelism

Core Presentation semantics (mode state, ambient authority, working set, background arbitration, output policy) can progress before Tool Brain and Scene/Prefab are fully landed.

Slices that call their public contracts must perform a freshness check immediately before implementation. If a dependency is still unstable, the Project Manager may split adapter work into a later Slice without blocking unrelated Presentation behavior.

## Migration constraints

- Preserve SIMPLE behavior exactly unless an explicit shared contract needs repair.
- Reuse any existing `presentation-*` runtime/docs found in the repository; this task may be a consolidation/completion exercise rather than greenfield work.
- Preserve the current ambient audio privacy behavior and explicit recording boundary.
- Preserve Board/Session/Context ownership; only consume the canonical effective interaction mode.
- Keep public semantic contracts narrow so Presentation is not coupled to one particular Tool Brain model or prefab implementation.
