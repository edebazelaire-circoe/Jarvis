# Slice 03 - Session resume, reconstruction and active-Context hydration

## Goal

Make runtime restart/relogin reconstruct the existing open JarvisSession and active Context rather than closing the Session, and wire the active Context as the agent's only implicit live workspace.

## Context

On the inspected baseline, `SessionManager._open_at_start()` closes the current Session with `CORE_RESTART`, creates a new Core conversation and aligns a Board binding. This Slice must change that without silently breaking Voice, Board compatibility or speech authority.

## Scope

### In scope

- Resume the same open `jarvis_session_id` after supported runtime restart.
- Reconstruct/rebind process-local conversation/agent state as required without treating process identity as Session identity.
- Implement explicit new-session transition as the normal terminal user boundary.
- Expose active Context locator/brief to the current agent launch/turn hydration path.
- Ensure only the active Context is an implicit write/read workspace.
- Support explicit context create/switch/reactivate commands/service calls.
- On context switch, optionally create a selective handoff summary/reference object through an explicit operation, never copy the old workspace wholesale.
- Preserve current Board/binding invariants needed by main, but do not make Context depend on them.

### Out of scope

Generic artifacts or media capture.

## Architecture constraints

- Resume behavior must be idempotent across repeated startup calls.
- If an agent process cannot resume, a new process may be created while retaining the same JarvisSession identity.
- Dormant Contexts are not implicit agent mutation targets.
- A Context path or summary must not become an authorization bypass.

## Automated validation

`qa-verification` + `code-review` + `runtime-validation` + `agent-trace-analysis` with real agent/session trace evidence. Include Session manager/protocol, Voice binding, Board compatibility and restart integration tests.

## Acceptance criteria

Restart no longer creates a new user Session; explicit new-session still does; active Context survives reconstruction; agent context does not merge dormant Contexts; existing Voice/speech-authority behavior remains single-owner and regression-clean.
