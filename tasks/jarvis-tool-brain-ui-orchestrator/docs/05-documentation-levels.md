# 05 — Documentation Levels

These current levels are **planning estimates from durable Jarvis handoffs**, not a substitute for Slice 00's blind repository audit.

| Concept | Estimated current | Required | Notes |
|---|---:|---:|---|
| Tool Brain ownership boundary | 0 | 3 | New concept; needs canonical contract, runtime and conformance tests. |
| Jarvis UI intent contract | 0-1 | 3 | Planning exists; needs typed event/schema + producer tests. |
| Speech response/chunk progress contract | 1-2 | 3 | Voice/Mouth runtime exists, exact canonical progress surface must be audited. |
| Tool Brain perception snapshot | 0 | 3 | New projection over canonical state; schema + builder + tests required. |
| Stable model-selectable UI object identity | 2 | 3 | Scene/Board IDs exist in durable task evidence; Tool Brain-wide registry/choice semantics need audit. |
| MCP/tool catalog/introspection | 2-3 | 3 | Existing semantic MCP/catalog task established canonical metadata path. Extend rather than fork. |
| Dynamic runtime parameter choices | 0-1 | 3 | Central new requirement; provider contract + validators + tests required. |
| UI action queue and speech/event triggers | 0 | 3 | New canonical runtime component/contract. |
| Stale-action invalidation/replan | 0 | 3 | New behavior; event/result contract and trace tests required. |
| Board switching | 3 | 3 | Existing Board runtime should be reused. |
| Scene/window/prefab contract | 2 with pending work | 3 | Pending `jarvis-scene-window-prefab-foundation` owns reusable substrate. |
| Conversation event log/live timeline | 3 | 3 + extension | Existing observability task owns canonical history/timeline; add Tool Brain events/lane. |
| Browser/display-surface control | unknown | 2-3 | Audit existing browser/window primitives before adding new tools. |
| Tool Brain model adapter/evaluation format | 0 | 3 | Keep provider-neutral; create replayable decision fixtures. |

## Required prerequisite gaps

Slices 01-04 are deliberately contract-heavy. Implementation must not jump directly to a model prompt while stable IDs, dynamic choices, perception and speech-progress contracts remain ambiguous.
