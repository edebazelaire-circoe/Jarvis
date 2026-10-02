# 00 - Overview

## Goal

Jarvis needs a durable concept of **what the user is currently doing** that is not coupled to process lifetime and is not coupled to Boards. It also needs capture tools that can document that work independently of the Brain.

This handoff joins two intentionally complementary layers:

1. **Session + Context memory**: durable Session identity plus one active free-form Context workspace and dormant history.
2. **Capture + artifacts**: structured, queryable evidence and media that can be acquired even when the reasoning agent is unavailable.

The result must support a meeting that begins before the Brain, continues through an agent restart, accumulates audio/transcript/screenshots, and then becomes an implementation Context without dragging the whole meeting prompt forward.

## Target user flow

```text
Open Jarvis
  -> resume open Session
  -> resume active Context

Start audio recording from left tool rail
  -> backend starts capture owner
  -> raw audio is durably spooled
  -> artifact/activity records appear
  -> transcript segments are derived asynchronously
  -> Context live memory may summarize/revise what matters

Take screenshot
  -> artifact exists immediately
  -> semantic description can arrive later

Switch Context: "now implement the decision"
  -> old Context becomes dormant
  -> new Context becomes active
  -> only a deliberate handoff summary/references carry over

Restart Brain/Core where supported
  -> same Session identity is reconstructed
  -> active capture state is discovered, not owned by Brain
  -> agent catches up from Context state + activity/transcript tail/indexes

Explicit "new session"
  -> old Session closes
  -> new Session starts clean
```

## In scope

- Session resume semantics across runtime restart/relogin/relaunch.
- One active Context and dormant Context history per open Session.
- Free-form Context filesystem workspace under the local data root.
- Structured artifact registry, provenance, metadata, time ranges and payload references.
- Canonical session activity ledger and bounded query/tail APIs.
- Explicit raw audio recording and near-live transcript derivation.
- Generic desktop screenshot and screen recording.
- Capture recovery/status independent of Brain lifecycle.
- Incremental live Context memory/enrichment over transcript/artifact evidence.
- Fast catch-up for a Brain joining an already-active Session/capture.
- API/MCP facade for session/context/capture/artifact queries and actions.
- Existing floating left Control Center tool rail as the human capture surface.
- Schema migrations, recovery, observability and regression tests.

## Non-goals

- Removing the current Board subsystem.
- Redesigning SIMPLE/PRESENTATION/REUNION.
- Making meeting room speech a Jarvis command channel.
- Camera capture in this V1.
- Cloud media sync.
- A universal rigid document schema for Context workspaces.
- Storing long binary media in SQLite.
- Reusing short-retention diagnostic scene captures as user screenshots.

## Core boundary

**Canonical backend state answers "what happened and where is the evidence?". Free-form Context memory answers "what is useful to think about now?".** Neither should impersonate the other.
