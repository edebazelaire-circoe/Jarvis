# 03 - Implementation Strategy

## Dependency graph

```text
00 Project Manager readiness
 |
 +--> 01 Architecture graph runtime contract ---------+
 +--> 02 Brain config runtime contract ---------------+
 +--> 03 Sub-agent role routing contract -------------+
 +--> 04 Architecture canvas UI ----------------------+--> 07 Settings integration + migration --> 08 Final integration/E2E QA
 +--> 05 Brain config popup UI -----------------------+
 +--> 06 Sous-agents tab UI --------------------------+
```

Slice numbers do not impose serial execution.

## Initial ready set after Slice 00

All of the following are hard-dependency-ready after `READY`:

- 01
- 02
- 03
- 04
- 05
- 06

They are intended to run concurrently when the PM confirms file ownership separation.

## Soft requirements and seams

### UI <-> runtime

Slices 04/05/06 require eventual runtime contracts from 01/02/03 but can start from the contracts in `docs/02-architecture.md` plus fixtures. They must isolate transport behind adapters. Live reconciliation becomes mandatory before Slice 07 completion.

### Topology <-> brain config

Slice 02 eventually needs the architecture graph's brain/connection snapshot for connection summaries and activation constraints. Until then it uses stable brain ids/config fixtures. Reconcile before Slice 07.

### Brain delegation <-> role routing

Slice 02 defines **when** a brain delegates. Slice 03 defines **who** executes a requested role. They can proceed independently using the documented role-request seam. Any mismatch is resolved at the boundary; do not invent a second selection model.

### Settings shell

The umbrella task `jarvis-settings-ui-reorganization` owns broader Settings shell/navigation work. This task can build its page modules against the current mount. Slice 07 must reconcile with whichever shell implementation is live before final integration.

## Hard chains

The only intended major hard chain is:

`00 -> {01..06 in parallel} -> 07 -> 08`

This minimizes false serialization while keeping the shared hot-file wiring in one convergence Slice.

## Hot-file/conflict boundaries

- `jarvis/runtime/control_center.py` - final route registration belongs to Slice 07.
- `jarvis/runtime/control_center.html` - final tab/page shell wiring belongs to Slice 07.
- `jarvis/runtime/control_center_subagents_settings.js` - owned by Slice 06 until convergence.
- current routing/domain files - Slice 03 owns role-routing changes; Slice 01/02 should use new separate modules unless a PM-approved contract move is needed.

If current main makes this separation impossible, Slice 00 must modify the graph before dispatch rather than allowing predictable merge conflicts.

## Migration/rollout

- Preserve current settings and runtime behavior until an explicit migrated config is valid.
- Do not delete legacy fields merely because the new UI stops exposing them.
- Project current routing policy into sensible role defaults; record provenance so users do not silently lose candidate choices.
- Old direct deep links/section ids from the Settings reorganization should redirect to the new page/tab or Advanced destination as appropriate.
- The old umbrella Slice 04 must be marked superseded to avoid concurrent conflicting implementation.
