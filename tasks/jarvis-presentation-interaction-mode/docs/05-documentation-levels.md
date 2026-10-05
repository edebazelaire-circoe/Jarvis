# Documentation levels

| Concept | Current evidence at planning time | Required level after task |
|---|---|---|
| Interaction mode (`SIMPLE`/`PRESENTATION`) | Level 2-ish: existing settings/runtime and Board persistence evidence, needs live audit | Level 3: canonical contract + tests + UI/runtime conformance |
| Ambient presentation lane | Level 3 evidence from completed Session/Context/Capture handoff and `docs/presentation-ambient-lane.md` references | Level 3 preserved, with explicit authority integration tests |
| Presentation working set | Level 2/3 evidence via existing `docs/presentation-working-set.md`; actual code must be audited | Level 3: bounded implementation + freshness/provenance tests |
| Ambient vs addressed authority | Level 2 decision across existing handoffs | Level 3: structural classification/validator + trace tests |
| Background Presentation work | Level 1/2 product intent | Level 3: bounded scheduler/arbitration behavior + tests |
| Manifestation policy | Level 1/2 product intent | Level 3: explicit policy contract + deterministic scenarios |
| Tool Brain UI orchestration | Pending handoff `jarvis-tool-brain-ui-orchestrator` | Consume its Level 3 public contract; do not duplicate |
| Scene/Prefab runtime | Active handoff `jarvis-scene-window-prefab-foundation` | Consume its Level 3 public contract; do not duplicate |
| Conversation observability | Completed Level 3 task | Extend canonical events/timeline only |
| Explicit recording/capture | Completed Level 3 task | Preserve orthogonality; no Presentation-owned capture lifecycle |
| Fact-check attention signal | Level 1/2 product intent | Level 3: event/state contract + UI/runtime test |

Slice 01 must replace this planning-time assessment with live-repository evidence. Any gap where the contract itself is genuinely unresolved becomes a prerequisite Slice before dependent behavior is dispatched.
