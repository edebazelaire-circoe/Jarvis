# Slice 00 — Readiness (agent 0, 2026-10-07)

Base: `origin/main` @ 085928d (task branch `task/jarvis-tool-brain-ui-orchestrator`).
Lifecycle fallback: `docs/workflows/AGENT_TASK_LIFECYCLE.md` absent; Drive queue IDs and `main` as base branch taken from project memory (to-do `1pbNoTQ_nZKv3NVIe2ok-J6kplfnpmjmm`, current `1BG9J5tWTuNfExK86YqH43QjMTPbOhB3D`, done `16yBLZRVOEbfDAN_CRh5722bkN46IUmo7`). No `dev` branch.

## Blind audit (done before reading docs/01-05; two read-only Explore agents)

- **Scene/UI tools** — `jarvis/domain/scene.py` (kinds agent/job/artifact/attention/window/group; representations point/capsule/window), `jarvis/core/scene_service.py`, `jarvis/runtime/display_mcp.py` (server `jarvis-display`: `scene_inspect/query/get/capture`, `scene_create_object/update_object/update_many/move/archive/pin/link/unlink/add_artifact`, `prefab_*`). IDs are stable: runtime `source:external_id`, brain `brain-<kind>-<uuid12>`, reserved-prefix guard `scene.py:1541`, archived ids are tombstoned (never reused). Final authority: reducer `apply_scene_command` (`scene.py:1488`). Schemas are `additionalProperties:false` via `StrictDisplayMCP`.
- **Browser/window navigation: does not exist.** No open-URL / focus / scroll / back / forward / zoom tool. A scene "window" is a Jarvis scene object. `docs/prefabs.md` lists a focus op as an explicit non-goal.
- **Board/Session** — `jarvis/core/board_service.py` (`switch`, 7-step transaction under `SpeechAuthority.lock`), `speech_authority.py`, `session_manager.py`; brain tools `board_switch`, `session_new` in `runtime/workspace_mcp.py:554/570`; brain-requested switches are deferred to end of turn (`docs/boards.md` §Switch).
- **MCP catalog** — `runtime/mcp_tool_meta.py` (only copy of side-effect / idempotence / parameter_rules), `runtime/mcp_catalog.py` (introspects the real FastMCP servers). Servers are built once per brain launch, so enums/descriptions are frozen; **no per-turn dynamic-choice injection exists**. Existing seams: `BrainContext` per-turn blocks (`domain/brain_context.py`), read tools for discovery, `settings_describe` options.
- **Decision brain / action queue** — none. Seam only: `PresentationDisplaySink` (`core/presentation_display.py:67`); `DirectSceneDisplaySink` executes immediately; swap point `runtime/presentation_runtime.py:1762`. Nearest queues are non-UI (`speech_scheduler.py`, `back_brain.py`, `actions.py`, `front_brain_sidecar.py`).
- **Speech/Mouth** — `SpeechScheduler` (`runtime/speech_scheduler.py`); answers arrive whole (no token streaming); paragraph chunking `domain/speech_presentation.py:127`, deterministic chunk ids `:159`; state is scattered (`_ActiveSpeech`, `_Candidate.status`, Core `VoiceSpeechRecord`), no word alignment (`estimate_heard_text` is proportional). Interruption: `note_interruption` `:1364`.
- **Conversation events** — `domain/conversation_events.py` (`ConversationEventType`, `_SPECS`, `ATTRIBUTE_KEYS` allowlist), store `adapters/sqlite_conversation_events.py` (schema change = versioned migration), emitters `core/conversation_event_emitter.py:199`, forwarder `runtime/conversation_event_forwarder.py:188` (ingest refuses `user.*`, `brain.*`, `core.*` producers), template `runtime/presentation_timeline.py`.
- **Timeline UI** — `runtime/control_center_timeline.js` (4 hard-coded lanes `LANES` js:213; JS `SPECS` mirrored and tested by `tests/unit/test_control_center_timeline_js.py`), routes `/api/conversations*` proxying Core `/v1/conversation-events*`. A new lane needs a new `ConversationActor`, `laneOf`, CSS, docs.
- **Brain orchestration** — `core/brain_service.py` (`submit` :648, `wake_for_work_attention` :1034, `announce_notice` :883); brains are CLI subprocesses (`ports/v2.py:262`, `runtime/cli_catalog.py`); **no direct API-model brain**. Tick+wake pattern exists in `core/context_enrichment.py:~395`.

## Reconciliation with the handoff (repository wins)

| # | Finding | Planning correction |
|---|---|---|
| R1 | Browser/window navigation primitives don't exist | **Slice 07 builds them** (new display/browser surface verbs + validation), not only adapters. Size risk: consider splitting 07 into 07a (scene/Board/process adapters) and 07b (browser surface primitives) at Slice 02/03 close. |
| R2 | Valid choices are not dynamic; MCP servers built once per launch | Slice 02 defines a Tool-Brain projection of the catalog with a runtime `choice_provider` evaluated per decision (the Tool Brain is its own caller, so schemas can be generated per call). Do **not** change the main brain's frozen-launch behaviour. |
| R3 | No API-model path for brains (CLI subprocesses) | Slice 05 defines a provider-neutral `ToolBrainDecider` port + a deterministic/fake decider for tests; the real model adapter reuses `cli_catalog`/`model_catalog` primitives; model choice stays pluggable (D19). |
| R4 | Speech progress: no streaming, no word alignment, scattered state | Slice 04 builds a read-only speech-progress projection from `SpeechScheduler.presentation_snapshot()` + `VoiceSpeechRecord`; granularity is chunk (paragraph) level, proportional within a chunk. No second speech truth. "Future chunks" = pending spans of the already generated answer (D06 holds). |
| R5 | Presentation-mode S08 targets the same swap point | **This task owns the Tool Brain public intake** (semantic UI intent + cancellation). `jarvis-presentation-interaction-mode` S08 (DEFERRED; entry: this task merged + Level-3 doc) writes `ToolBrainDisplaySink` against it. Keep `PresentationDisplaySink` / `PresentationOutputIntent` unchanged except additive fields; document the intake at Level 3 in S10. |
| R6 | Dependencies described as pending | `scene-window-prefab-foundation`, `session-context-recording-runtime`, board/session, mcp-semantic-batch-inspector and presentation-mode are all merged in `main` (their `task.json` statuses are stale). Scene/prefab contracts are real, not pending. |
| R7 | Events | New actor `tool_brain` + event types follow the `ConversationEventType` mechanics; needs an ingest allowlist entry for a non-brain producer id and a migration check (S09). |

All Slice dependency IDs resolve (00→10 verified); no cycle.

## Decisions (agent 0, standing full-autonomy rule)

- **D0 Task Type:** `task_type: null` and no "Workspace Task Type" vocabulary exists in this repo; all 20 existing metadata files carry `"task_type": "waived"`. Apply `"waived"` to all 11 Slices; flagged for Human confirmation, not re-investigated.
- **D1 Mode:** shadow/observe-only first (handoff recommendation) — kept; S05 ships shadow, S08/S10 flip default ownership.
- **D2 Queue persistence:** ephemeral, invalidated on Board/Session authority change — kept.
- **D3 Worktree:** the main checkout `C:/Projects/jarvis/jarvis` stays on `main` (Human's live Jarvis); task code lives in this worktree.

## Pending before READY

1. Wide inherited-red baseline of `tests/unit` (+ integration) at 085928d, foreground chunks, recorded in `LOG.md` with the exact file list and count.
2. D0 applied to the metadata files (done in this commit).

State: **READY** (baseline recorded in LOG.md: 11 inherited failures in 6 files).
