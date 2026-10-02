# Jarvis Session Context + Recording Runtime

## Project

- Project: **Jarvis**
- Repository: `edebazelaire-circoe/Jarvis`
- Planning source: repository `main` at `96a93963a6faf0723be5839e89545e64546ccdb7` (inspected 2026-10-01)
- Execution entrypoint: [`slices/TODO.md`](slices/TODO.md)

## Goal

Turn the current Jarvis Session into a durable user-controlled continuity boundary, add one active free-form working Context inside that Session, and introduce first-class capture/recording capabilities whose artifacts, transcripts and metadata are durably indexed.

The target must let Jarvis resume the same open Session after a Core/Brain/Control Center restart unless the user explicitly requests a new Session. Within the Session, the active Context is a live agent workspace that may reorganize itself as the work evolves. Leaving a Context makes it dormant; agents must not mutate dormant Contexts implicitly.

Capture is orthogonal to interaction modes and to the existing Board subsystem. Explicit recording can create durable raw audio, live transcript artifacts, desktop screenshots and screen recordings. The capture lifecycle must not be owned by the Brain or by MCP. Recording controls must be added to the existing **floating left tool palette** in the Control Center, currently implemented by the Bare Hands palette, without turning capture actions into mutually-exclusive Bare Hands interaction tools.

## Mental model

```text
JarvisSession  (durable until explicit "new session")
  |
  +-- active Context  --------------------------+
  |      free-form agent workspace             |
  |      summary.md / research/ / ...          |
  |                                             |
  +-- dormant Contexts (no implicit mutation)  |
  |                                             |
  +-- canonical activity ledger                |
  |                                             |
  +-- artifact references ---------------------+----> Artifact registry (SQLite metadata)
                                                        |
                                                        +-- audio recording
                                                        +-- transcript segments/projections
                                                        +-- screenshot
                                                        +-- screen recording
                                                        +-- derived descriptions/summaries
                                                             |
                                                             +-- payload files under local data root
```

Canonical identity, lifecycle, provenance, timestamps and indexes are structured backend data. Agent working memory is intentionally flexible filesystem content. The database does not prescribe how the agent must think.

## Locked decisions

1. **Boards are ignored for this feature.** Do not make Session Contexts, capture ownership, artifact identity, or recording controls Board-scoped. Do not remove the already-implemented Board subsystem as part of this task; treat it as a compatibility surface only.
2. **A JarvisSession ends only on an explicit new-session action.** Restart/logout/relaunch resumes and reconstructs the open Session instead of closing it with `core_restart`.
3. **Exactly one active Context per open Session.** Previous Contexts become dormant. Dormant Contexts remain readable but are not mutated implicitly. Explicit reactivation or explicitly targeted edits are allowed.
4. **Context content is free-form and evolvable.** The backend owns context identity/status/path, not a universal `decisions[]`/`participants[]` document schema.
5. **Context switches are selective handoffs.** A new Context may receive a focused summary/reference set from the old Context; it must not automatically inherit the old live workspace wholesale.
6. **Artifacts are canonical, separately indexed objects.** Acquisition does not depend on semantic interpretation. Analysis/description/summary metadata may arrive later.
7. **Large media payloads live on the filesystem; SQLite holds registry/index/provenance.** Do not put long audio/video blobs in SQLite.
8. **Backend activity is factual and automatic.** Events such as context changes, capture start/stop and artifact creation are recorded by the backend. The agent may maintain a human-oriented semantic timeline, but it is not the canonical trace.
9. **Explicit recording persists media.** This is separate from the current PRESENTATION ambient lane, whose privacy and freshness semantics intentionally keep PCM memory-only and may drop stale blocks.
10. **A canonical full transcript cannot ride a `drop_oldest` path.** Persist/spool the explicit audio recording first and derive/retry transcription from durable media. Record explicit gaps when evidence is actually lost.
11. **Capture tools are independent of interaction modes and Brain lifecycle.** SIMPLE/PRESENTATION/REUNION may invoke them, but do not own them.
12. **MCP/API are facades over the capture owner.** They must not own recording lifecycle.
13. **Use the existing floating left palette.** Preserve its visual language and safe-area behavior, but do not add capture actions to `BH.TOOL` or `BH.describeTools()` as if screenshot/audio/screen-recording were mutually-exclusive hand gestures.
14. **Ambient meeting speech is not an addressed Jarvis turn.** Do not inject room transcript into canonical conversation events in a way that grants action authority.
15. **Camera capture is an extension point, not a V1 deliverable.** Desktop screenshot and screen recording are in scope.

## Source evidence to audit first

The handoff was designed from current `main`, especially:

- `jarvis/domain/workspace_board.py`
- `jarvis/core/session_manager.py`
- `docs/boards.md`
- `jarvis/adapters/sqlite_state.py`
- `docs/local-data.md`
- `jarvis/runtime/journal.py`
- `jarvis/audio/capture_hub.py`
- `jarvis/audio/ambient_segmenter.py`
- `jarvis/ports/transcription.py`
- `jarvis/adapters/openai_transcription.py`
- `jarvis/runtime/ambient_lane.py`
- `docs/presentation-audio-capture.md`
- `docs/presentation-ambient-lane.md`
- `docs/presentation-working-set.md`
- `jarvis/core/scene_capture.py`
- `jarvis/domain/scene_capture.py`
- `jarvis/adapters/file_scene_captures.py`
- `jarvis/runtime/control_center_scene_capture.js`
- `jarvis/runtime/control_center_barehands_hud.js`
- `jarvis/runtime/control_center_scene_page.js`
- `docs/mcp/tool-contract.md`
- conversation-event contracts and timeline implementation

The Project Manager must independently re-audit these boundaries before trusting this list because `main` may have moved. Humanity did, after all, invent branches specifically to make yesterday's certainty today's archaeology.

## Execution

Start with Slice `00-project-manager`. It is a readiness gate, not implementation work. No product-code Slice may be dispatched until Slice 00 reports `READY`.

Every coding Slice must load `/caveman` and `/coding-guideline`. Frontend Slice 10 must additionally load `/impeccable` and use a Claude Work Agent when the host supports that routing rule.

## QA doctrine

Every implemented Slice receives baseline `qa-verification`. Code changes additionally receive `code-review`. User-visible or runtime behavior additionally receives `runtime-validation`. Agent prompts, tools, routing, modules, MCP, or agent runtime additionally receive `agent-trace-analysis` with real trace evidence. QA agents return evidence and findings; the Project Manager decides approve, rework, continue, add a Slice, create an Issue, or escalate.

A regression caused by the current Slice is blocking and may not be parked in `Issues/`. Human validation never substitutes for machine validation: before asking a human to touch a microphone, permission dialog or screen recorder, exhaust all reasonable automated tests, fakes, deterministic replays and runtime checks first.

## Planning blocker

The current Workspace Task Type vocabulary was not exposed to the task creator. Slice 00 must resolve it and assign valid Task Types to implementation Slices. Do not invent or default a Task Type.
