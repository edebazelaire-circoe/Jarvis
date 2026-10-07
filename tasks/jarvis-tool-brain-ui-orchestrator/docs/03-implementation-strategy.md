# 03 — Implementation Strategy

## Rollout order

### Phase 1 — Audit and contracts

Recover live repository contracts for scene, Board, speech/Mouth, conversation events, MCP metadata and the existing timeline. Reconcile pending scene/prefab work before defining new abstractions.

### Phase 2 — Make UI tools machine-selectable

Before building intelligence, make the UI tool surface deterministic:

- canonical stable IDs;
- parameter descriptions;
- dynamic choice providers;
- side-effect classes and preconditions;
- targeted read/inspection operations;
- parity tests against the existing MCP/tool catalog.

This is a prerequisite. A Tool Brain cannot be reliable if the tool surface requires it to guess runtime identifiers.

### Phase 3 — Build perception and Jarvis signals

Add the compact world snapshot and the typed Jarvis intent/speech-progress events. The snapshot is a projection over existing state, not a new persistence domain.

### Phase 4 — Shadow Tool Brain

Run Tool Brain decisions without executing mutations. Record:

- wake reason;
- snapshot version;
- proposed actions;
- dynamic choices used;
- would-be queue operations;
- model latency.

Replay representative traces and compare proposed actions against current user/Jarvis behavior.

### Phase 5 — Enable a narrow reversible UI subset

Start with operations that are easy to validate and reverse, such as focus/show/hide/reorder/move among known destinations. Keep destructive operations guarded.

### Phase 6 — Queue + speech synchronization

Enable scheduled actions tied to speech chunks/events, then interruption cancellation and stale-state replan behavior.

### Phase 7 — Expand UI coverage

Integrate Board switching and browser/display surfaces after their canonical ownership and choice providers are proven.

### Phase 8 — Observability and full rollout

Extend the existing timeline, add replay/latency metrics, run end-to-end scenarios, and only then make Tool Brain the default UI-tool owner.

## Migration constraints

- Do not remove UI tools from Jarvis capability understanding; change **execution ownership**, not product capability semantics.
- Do not advertise the same UI mutating tool simultaneously to two autonomous brains in the normal path.
- A debug/fallback path may keep direct access available internally, but it must be gated and observable so it cannot cause silent double execution.
- Existing UI/MCP callers continue to work through canonical services; Tool Brain is an additional decision client, not a replacement service.
- Existing Board/Session/scene/prefab identifiers and lifecycle rules remain authoritative.
- Existing conversation timeline remains canonical for live transcript/debug projections.

## Cross-task dependency strategy

The pending scene-window-prefab foundation may change scene object APIs. Core Tool Brain runtime/perception work can proceed against the current canonical scene contract, but any Slice that exposes new scene actions must perform a freshness check and coordinate contract changes rather than fork the API.

## Model strategy

Keep a provider/model-neutral decision interface. V1 evaluation should collect enough structured examples for future model comparison or fine-tuning:

```text
trigger + snapshot + tool choices + queue
    -> chosen inspections / chosen actions / queue edits
    -> execution result
```

Do not couple runtime contracts to one model's proprietary response format.
