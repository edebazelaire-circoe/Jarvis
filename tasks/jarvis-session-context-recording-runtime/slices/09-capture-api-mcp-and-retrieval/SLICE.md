# Slice 09 - Capture/Context API, MCP facade and indexed retrieval

## Goal

Expose one consistent runtime surface for Session Context control, capture control/status, Artifact retrieval/search and transcript access, then expose the appropriate subset to the Brain through current MCP catalog conventions.

## Context

Current native MCP servers use introspected schemas plus shared metadata/catalog rules. MCP is a facade, not an owner. The UI and Brain should call the same underlying services so status and side effects cannot drift.

## Scope

### In scope

- HTTP/runtime API for current Session/Context status and explicit context create/switch/reactivate where not already exposed.
- Capture status/start/stop for audio and screen recording; screenshot action.
- Artifact get/query/search by bounded time/type/session/context and provenance.
- Transcript tail/read/query endpoints suitable for catch-up.
- MCP surface chosen after fresh catalog audit (`jarvis-capture`, `jarvis-console`, or another canonical owner), with typed schemas, metadata, side-effect/idempotency/availability semantics and parity tests.
- Tool errors use stable capture/session/artifact codes and never leak credentials/arbitrary paths.
- Trace evidence showing Brain tool calls reach the shared capture owner.

### Out of scope

Lifecycle ownership inside MCP, frontend toolbar rendering.

## Architecture constraints

- MCP/UI share service semantics.
- No handcrafted duplicate tool catalog in frontend.
- Read tools are bounded and do not dump unbounded media/transcripts into model context.
- Ambient room transcript retrieval does not convert evidence into action authorization.

## Automated validation

`qa-verification` + `code-review` + `runtime-validation` + `agent-trace-analysis`. Extend MCP catalog parity/annotation/schema tests, API protocol tests, authorization/path tests and real Brain trace proof.

## Acceptance criteria

The Brain can discover/control capture and retrieve bounded evidence through current MCP architecture; status matches the capture owner; tools are catalogued/typed; API and MCP parity is tested; no media lifecycle is hidden inside the tool server.
