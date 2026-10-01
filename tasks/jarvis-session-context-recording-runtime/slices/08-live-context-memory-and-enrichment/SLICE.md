# Slice 08 - Live Context memory, artifact enrichment and fast catch-up

## Goal

Add an independent incremental worker that turns new transcript/artifact/activity evidence into useful revisable live Context memory, while keeping raw evidence immutable and allowing a Brain to catch up quickly mid-session.

## Context

The active Context workspace is deliberately free-form. The worker therefore needs a small stable protocol for inputs/cursors/provenance, not a universal document schema. It may create `summary.md` first and evolve the active workspace when the work genuinely benefits from more structure.

## Scope

### In scope

- Incremental evidence cursor/version over canonical activity/artifacts/transcript.
- Worker trigger/cadence/backpressure and restart replay semantics.
- Update active Context memory using bounded current state + new evidence rather than rereading the whole Session.
- Permit semantic revision: e.g. an issue initially open becomes resolved after later evidence.
- Add provenance/reference conventions so important statements can point back to artifact/time ranges.
- Add screenshot/keyframe description enrichment using current vision/agent capabilities when available, asynchronously after artifact creation.
- Define fast Brain catch-up payload: active Context compact state, recent activity/transcript tail, relevant artifact refs and deeper retrieval pointers.
- Ensure Context switch stops implicit writes to the now-dormant workspace.

### Out of scope

A rigid required folder taxonomy, rewriting raw transcripts, per-frame video vision, autonomous actions based solely on ambient speech.

## Architecture constraints

- Semantic projections are revisable; source evidence is not.
- Worker writes only active Context unless explicitly targeting another Context.
- Replay after crash should be idempotent enough not to duplicate content endlessly.
- Keep prompt/context payload bounded.

## Automated validation

`qa-verification` + `code-review` + `runtime-validation` + `agent-trace-analysis` with real traces showing evidence intake, Context update, revision and catch-up. Test stale/duplicate event replay, context switch race, long transcript bounds and later resolution of earlier summary state.

## Acceptance criteria

A long-running capture can update useful live Context memory incrementally; later evidence can revise prior semantic state; restart resumes from a cursor; a newly started Brain can understand current work from bounded state without full transcript replay.
