# Overview

## Goal

Make conversation history a backend-native, crash-resilient, searchable event record and expose it as a live multi-lane transcript/debug timeline with trace-linked Brain, Mouth and sub-agent activity.

## Scope

- Transcripts are produced from backend/runtime events, never by asking an LLM to rewrite the conversation.
- The canonical conversation record must survive crashes and remain traceable/searchable.
- The transcript view is live and based on a shared time axis, not a post-hoc text summary.
- The primary timeline shows User, Jarvis Mouth/Reflex, Brain, and sub-agent activity with distinct visual lanes.
- User content is shown on the left; Jarvis/Mouth is light blue, Brain is orange, and sub-agents are red duration blocks.
- Brain/Mouth/sub-agent entries link to diagnostic trace evidence; user entries do not need a diagnostic drill-down.
- A readable text transcript and machine-readable export are projections of the canonical event record, not separate truths.

## Non-goals

- Do not replace the existing RuntimeJournal telemetry or its scalar voice summary with a transcript-only log.
- Do not persist raw audio as part of this task.
- Do not expose hidden chain-of-thought; Brain events may contain externally visible messages, structured decisions, statuses, tool/agent spans, and trace references only.
- Do not solve speech arbitration itself here; emit enough evidence for the separate arbitration task.

## Mental model

Jarvis already has `jarvis/runtime/journal.py`, an append-only `runtime/trace.jsonl`, and `trace_summary.py` for scalar voice diagnostics. Those are diagnostic observability primitives, not a canonical conversation transcript. The target introduces a **Conversation Event Log** with a stable JSON envelope and durable append semantics. Runtime producers emit events at the source of truth (user transcript accepted, Brain message/request emitted, Mouth speech lifecycle, sub-agent task lifecycle, relevant tool spans). Each event carries correlation identifiers and may reference a `trace_id`/diagnostic event. The UI consumes the same canonical events through query + live-stream APIs.

The storage adapter is deliberately not locked to a new technology in this handoff: Slice 00/02 must audit existing Core persistence/event-store facilities and reuse them when they satisfy durability, ordering, indexing, and crash-recovery requirements. The canonical schema is storage-independent. `RuntimeJournal` remains appropriate for telemetry and trace-level details; the conversation log must not rely on replaying arbitrary trace lines as its only source of truth.

The frontend renders four synchronized lanes over one chronological axis: User (left/white), Mouth/Reflex/Jarvis (light blue), Brain (orange), and sub-agent spans (red blocks adjacent to Brain). Events preserve `started_at`/`ended_at` where duration exists, allowing overlap to be visible rather than flattened into chat order.
