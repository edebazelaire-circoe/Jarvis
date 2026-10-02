# 01 - Decision log

## D01 - Recording is not an interaction mode

Locked. Capture tools are cross-cutting capabilities. REUNION or PRESENTATION may invoke them, but do not define their lifecycle.

## D02 - Session lifetime is user-controlled

Locked. Process restart is not a new Session. `core_restart` must cease to be the normal Session termination mechanism. An explicit new-session action closes the open Session.

## D03 - Session contains Contexts

Locked. A Session has exactly one active Context. Previous Contexts are dormant and readable. Agents do not mutate dormant Contexts implicitly.

## D04 - Context memory is free-form

Locked. Backend owns Context identity, lifecycle and location. Inside the Context workspace, the agent may create/restructure files according to the work. No universal meeting/research/coding folder template is mandatory.

## D05 - Context switch is a clean boundary

Locked. A new Context does not inherit the previous live workspace wholesale. The agent may create a deliberate handoff summary or references when continuity is useful.

## D06 - Boards are not part of this design

Locked. Existing Boards remain a compatibility surface on current main but new Session Context and Capture models must not be Board-scoped. Wholesale Board removal is a separate future decision/task.

## D07 - Artifact acquisition precedes interpretation

Locked. Screenshot/audio/video/transcript artifacts obtain stable identity, timestamps, source and payload reference at acquisition. Descriptions, summaries, speakers, semantic context and other metadata may be appended later.

## D08 - Provenance is explicit

Locked. Derived evidence must retain source relationships, e.g. audio recording -> transcript segment -> derived summary/observation.

## D09 - Media payloads are filesystem data

Locked. SQLite indexes management metadata and relationships; large audio/video payloads live under the local data root. Atomic write/finalization and safe path handling are required.

## D10 - Backend activity is canonical

Locked. Backend records factual context/capture/artifact events automatically. Agent-written timelines are optional semantic projections, not the canonical event ledger.

## D11 - Full transcript requires durable source evidence

Locked. The existing ambient PRESENTATION lane may drop old/stale blocks and is memory-only. It cannot be the canonical full-transcript path. Explicit recording persists source audio before/while transcription so failed STT can retry. Evidence loss is represented as a gap, never silently hidden.

## D12 - Current privacy invariant remains for passive ambient lane

Locked. Do not globally change `AudioCaptureHub`/PRESENTATION semantics to persist everything. Persistence begins because an explicit recording capability was started.

## D13 - Capture owner is independent of Brain/MCP

Locked. The Brain and MCP are callers. Capture lifecycle must live in a supervised runtime/service that remains discoverable across Brain restart and can reconcile durable state after broader process restart.

## D14 - Existing left floating toolbar is the recording UI home

Locked. Reuse/generalize the left Bare Hands palette visual rail. Do not put the new controls in the right `.dock` as the primary surface.

## D15 - Capture controls are not Bare Hands tools

Locked. Do not extend `BH.TOOL`/`BH.describeTools()` with recording actions. Hand tools are mutually exclusive. Capture actions/toggles may run concurrently and must remain usable even when Bare Hands itself is off.

## D16 - Desktop capture is new capability

Locked. Existing scene capture renders only Jarvis's scene and has 5-file/24-hour diagnostic retention. Reuse lifecycle/validation/atomic-write patterns where useful, not its domain or retention policy.

## D17 - Canonical conversation events remain addressed-conversation truth

Locked. Ambient room transcript must not be projected as addressed user turns or grant action authority.

## D18 - Camera later

Locked for V1. Data model should permit a future camera/video source without implementing camera capture now.
