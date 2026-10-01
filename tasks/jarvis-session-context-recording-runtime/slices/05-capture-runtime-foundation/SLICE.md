# Slice 05 - Capture runtime foundation and lifecycle owner

## Goal

Introduce the common capture owner/state machine used by audio, screenshot and screen recording, independent of the reasoning Brain and reusable from UI/API/MCP.

## Context

Current capture code has useful but domain-specific pieces: `AudioCaptureHub` owns a microphone in PRESENTATION; scene capture has IDs/deadlines/validation/atomic file write; neither is a generic durable user-capture owner. The target requires truthful recovery and a precise guarantee about which process deaths recording survives.

## Scope

### In scope

- Choose and implement the runtime/process owner after Slice 00 freshness audit.
- Define common capture IDs/channels/states (`starting`, `active`, `stopping`, `complete`, `partial`, `failed` or the audited equivalent).
- Support concurrent independent capture channels where sensible, e.g. audio and screen recording together.
- Persist enough capture intent/state to reconcile after restart and finalize recoverable partial artifacts.
- Define source ownership/conflict/permission/storage failures with stable codes.
- Provide in-process/service API for status/start/stop/finalize and event publication to Artifact/activity services.
- Build fake sources/sinks so lifecycle, race and crash behavior are testable without devices.
- Document the exact continuity guarantee: Brain restart, Core restart, Control Center restart and capture-service restart must each be stated as supported uninterrupted, recoverable-partial, or unsupported.

### Out of scope

Real microphone adapter, real desktop adapter, MCP/UI surface.

## Architecture constraints

- Brain and MCP never own capture lifetime.
- Frontend optimistic state is not authoritative.
- Multiple stop requests are idempotent.
- A crash never turns an incomplete payload into a silently `complete` Artifact.
- No dependency on interaction mode or Board.

## Automated validation

`qa-verification` + `code-review` + `runtime-validation`. Add deterministic state-machine/race tests, restart/reconcile tests, disk-full/write-failure simulation, duplicate commands and fake-source loss. Use `agent-trace-analysis` only if this Slice changes agent/tool/runtime routing visible to agents.

## Acceptance criteria

A fake capture can be started, observed, stopped, finalized into the generic Artifact registry and recovered after simulated crash; status truth is single-owner; continuity limits are documented and tested rather than implied.
