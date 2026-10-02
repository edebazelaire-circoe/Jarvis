# Slice 11 - End-to-end recovery, regression, documentation and rollout

## Goal

Prove the complete Session/Context/Artifact/Capture feature against real current-main architecture, recovery boundaries and user-visible controls, then finish canonical documentation.

## Scope

### In scope

Build and execute a scenario matrix covering:

1. migrate an existing current-main data root;
2. resume the same open Session after supported runtime restart;
3. explicit new-session creates the only new user Session boundary;
4. create/switch/reactivate Contexts and prove dormant Context isolation;
5. start audio recording, create transcript evidence and take screenshots;
6. start screen recording concurrently;
7. restart the Brain mid-capture and prove capture continuity/catch-up according to the exact Slice 05 guarantee;
8. simulate/perform broader service restart and prove either uninterrupted capture or truthful partial recovery, whichever is the documented guarantee;
9. query artifacts by time/type/session/context and provenance;
10. start a Brain mid-session and prove bounded catch-up instead of full transcript replay;
11. exercise API/MCP and left-toolbar parity;
12. run Board/Voice/PRESENTATION/scene/MCP regression suites so the new Session semantics do not quietly destroy mature behavior;
13. finalize canonical docs, migration/rollback notes and operational troubleshooting.

## Architecture constraints

Do not weaken invariants to make E2E pass. In particular: no fake new Session on restart, no implicit dormant-Context mutation, no hidden capture gaps, no Board coupling in new data, no raw room speech authorization, no UI-owned recording state.

## Automated validation

Run the full relevant suite plus `qa-verification`, `code-review`, `runtime-validation`, and `agent-trace-analysis` with real trace evidence for restart/catch-up/MCP paths. Verify migration schema snapshots and data-root backup behavior. All machine findings from this task are resolved before Human acceptance.

## Human validation

Final human check focuses only on irreducible physical/runtime continuity after machine validation: real capture running while the Brain is restarted, then catch-up and artifact retrieval in the resumed Session.

## Acceptance criteria

- Same Session survives supported restarts until explicit new-session.
- One-active-Context/dormant isolation is proven.
- Explicit audio and screen media are durable and indexed; transcript derives/retries from source.
- Desktop screenshots are generic capture artifacts, not scene diagnostics.
- Brain can join mid-session/capture and catch up from bounded state.
- Left toolbar controls and MCP/API expose the same capture truth.
- Recovery limitations are explicit and demonstrated.
- Existing Board/Voice/PRESENTATION/scene behavior has no task-caused regression.
- Canonical docs match shipped behavior.

## Documentation updates

At minimum update Session/Board compatibility docs, local-data/schema docs, capture/audio/PRESENTATION docs, MCP tool contract/catalog, Control Center help/architecture, and any operations guide required for OS capture permissions/codecs.
