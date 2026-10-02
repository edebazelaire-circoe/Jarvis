# Grill session

> Reconstructed faithfully from the planning conversation. This is not claimed to be a verbatim transcript. Locked decisions are repeated in `docs/01-decision-log.md` so implementation does not depend on conversational phrasing.

## Starting problem

The user wanted a full-transcript / recording capability useful for meetings, initially described as live recording/transcription with visible controls. Repository inspection showed an existing `InteractionMode.MEETING`, an in-memory PRESENTATION ambient speech lane, a scene-only PNG capture path, conversation events, Sessions/Boards, and multiple Control Center surfaces.

The first important correction was conceptual: **recording is not an interaction mode**. SIMPLE, PRESENTATION and REUNION describe Jarvis behavior. Audio recording, transcription, screenshot and screen recording are independent capabilities that may be started by the human or invoked by Jarvis through API/MCP. They must not be owned by the Brain.

## Canonical capture vs live ambient context

Inspection of `AudioCaptureHub`, `AmbientSegmenter`, `ambient_lane.py` and the presentation working set established that the current ambient lane is intentionally memory-only and freshness-oriented. Bounded queues use `drop_oldest`; stale segments may be discarded; the presentation working set is session-scoped and transient. Therefore it can provide reusable microphone ownership, segmentation and STT building blocks, but cannot be relabeled as a complete archival transcript.

For explicit recording, the user wants the actual source media and transcript to be durable artifacts. The agreed direction is to persist/spool the source recording first, then derive transcript/summary/index data from it, with explicit gap records if evidence is actually lost.

## Artifact layer

The user proposed a structured artifact database plus payload files. An artifact receives a stable identity and factual metadata when acquired. Semantic metadata can be added later. Examples include raw audio, transcript chunks, screenshots and screen recordings. Relationships preserve provenance, e.g. raw audio -> transcript -> summary/observation.

The database owns management data and indexes; large binary payloads should remain files under the Jarvis local data root. Acquisition must not require the system to know what the artifact means.

## Session live memory

The user then reframed Session memory as a living filesystem workspace. Backend data remains structured, but the agent may organize the content of the current working Context in whatever structure is useful: a trivial `summary.md` for a lightweight exchange, meeting-specific participants/decisions files for a meeting, or research/architecture files for a technical investigation.

The agent is allowed to reorganize the active Context as understanding evolves. The backend must not force every Context into one universal schema.

## Session lifecycle correction

Inspection showed that current `SessionManager.start()` closes a still-open Session with `end_reason=core_restart` and creates a new one. The user explicitly rejected that behavior for the target model.

A JarvisSession should continue across restart, relogin and runtime reconstruction. A new Session starts when the user explicitly asks for one. Reopening Jarvis should rehydrate the current Session instead of treating process lifetime as user-session lifetime.

## Context inside Session

A Session can contain successive working Contexts. Example: a meeting Context may contain calendar/participant/material information; after the meeting, an implementation Context may start with only the relevant decision summary rather than inheriting the whole live meeting state.

Locked lifecycle:

- exactly one active Context in the open Session;
- leaving it makes it dormant;
- dormant Contexts are readable but agents do not edit them implicitly;
- explicit reactivation or targeted edit is allowed;
- a transition may deliberately carry a compact handoff/reference set to the new Context.

## Timeline and trace

The user distinguished two timelines:

1. canonical backend activity/trace: exhaustive factual events such as context activation, capture start/stop and artifact creation;
2. agent-authored timeline/memory: selective semantic notes about what mattered.

The backend must automatically record canonical activity. The agent should never be responsible for remembering that it created a screenshot. A session-folder trace may exist as a projection, but canonical structured data remains queryable in the backend.

## Boards

The existing Board subsystem was inspected and explained. It is real and implemented, including persistence, BoardConversationBinding, speech authority and tests. The user decided to **ignore Boards for this feature** and base the new design on Session + Context. This task must not make new Session Contexts or capture artifacts Board-scoped, and it must not silently expand into wholesale Board removal.

## Recording UI

The user specified that the capture/recording controls belong in the existing floating toolbar on the left side of the screen.

Fresh inspection of `control_center_barehands_hud.js` confirmed that this is the Bare Hands palette: a fixed vertical strip on the left containing 44x44 interaction-tool icons. It is included in scene safe-area geometry. Capture controls should reuse/generalize this visual rail while remaining a separate control group. They are not `BH.TOOL` choices: pointer/pan/select are mutually-exclusive hand interaction tools; screenshot/audio/screen recording are concurrent actions/toggles with independent lifecycle.

## Final scope handed off

Implement durable Sessions across runtime restarts, active/dormant Context workspaces, artifact registry/provenance and canonical session activity, Brain-independent capture ownership, explicit audio recording + live transcript, generic desktop screenshot + screen recording, live context enrichment/catch-up, API/MCP facades, and recording controls in the existing left floating toolbar. Preserve current main contracts unless a Slice explicitly migrates them, and validate migrations/recovery aggressively.
