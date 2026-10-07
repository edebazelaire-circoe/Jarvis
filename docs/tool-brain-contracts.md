# Tool Brain: runtime contracts and canonical boundaries (Level 2)

Audit of the live contracts a Tool Brain (a dedicated decider of UI-tool calls
and their timing, handoff `jarvis-tool-brain-ui-orchestrator`) must integrate
with. **Nothing here is Tool Brain behaviour**: the Tool Brain does not exist
yet. This page names, with `file:line` anchors verified against the code on
branch `task/jarvis-tool-brain-ui-orchestrator`, what already exists, what is
missing, and the names later Slices (S2 to S10) must use.

- Level: **2** for sections 1-7 (dedicated contract, anchors pinned by
  `tests/unit/test_tool_brain_contracts.py`). Section 8 (UI tool choice
  contract, Slice S2) is **Level 3**: implementation
  `jarvis/runtime/tool_brain_choices.py`, conformance
  `tests/unit/test_tool_brain_choices.py`. Section 9 (perception, Slice S3) is
  **Level 3** too: `jarvis/runtime/tool_brain_perception.py`,
  `tests/unit/test_tool_brain_perception.py`. Sections 10 to 12 (speech progress,
  Jarvis UI intent, Jarvis capability awareness, Slice S4) are **Level 3** too:
  `tool_brain_speech.py`, `tool_brain_intents.py`, `tool_brain_brief.py`, domain
  `ui_intent.py`, Core `ui_intents.py`, conformance `test_tool_brain_speech.py`,
  `test_tool_brain_intents.py`, `test_tool_brain_brief.py`. The rest of the gap
  report is still the job of the Slices it names.
- Rule: one canonical owner per mutation or read. A Tool Brain adapter calls
  that owner; it never wraps two diverging paths and never keeps a second copy
  of a truth.
- Line numbers drift; the test pins symbols and behaviour, not lines.

Related contracts: [scene-model.md](scene-model.md),
[prefabs.md](prefabs.md), [boards.md](boards.md),
[conversation-events.md](conversation-events.md),
[mcp/tool-contract.md](mcp/tool-contract.md),
[presentation-mode.md](presentation-mode.md).

## 1. Tool inventory and canonical owners

### 1.1 Scene and window objects (the only "UI mutation" surface that exists)

| Concern | Canonical owner (single) | Anchor |
|---|---|---|
| Truth + reducer | pure `apply_scene_command(snapshot, command) -> SceneUpdate` | `jarvis/domain/scene.py:1488` |
| Authority matrix | `ALLOWED_SCENE_OPS[SceneActor] -> frozenset[SceneOp]`; `runtime` has 5 ops, `brain` and `user` have all | `jarvis/domain/scene.py:304` |
| Command / ops / actors | `SceneCommand` :1080, `SceneOp` :248, `SceneActor` :240 (`runtime` / `brain` / `user`) | `jarvis/domain/scene.py` |
| Storage + serialization | `SceneService.apply(command)` :333 and `apply_if(plan)` :346 (plan evaluated **under the lock** on the current snapshot: the only atomic read-then-write primitive) | `jarvis/core/scene_service.py` |
| Reads | `SceneService.snapshot()` :516, `patches_since(revision, scene_id=)` :519, `wait_for_revision(after, timeout_s=)` :535 | `jarvis/core/scene_service.py` |
| Wire (Core) | `GET /v1/scene/snapshot`, `GET /v1/scene/patches` (long-poll), `POST /v1/scene/commands` | `jarvis/protocol/server.py:222-224` |
| Brain-facing MCP | server `jarvis-display` (`SERVER_NAME`, `jarvis/runtime/display_mcp.py:138`), backend class `SceneDisplayTools` :737, transport `SceneTransport` / `CoreSceneTransport` | `jarvis/runtime/scene_view.py:153,186` |

`jarvis-display` tools (all verified `async def` in `display_mcp.py`):

| Kind | Tools (registration order) |
|---|---|
| Read (side effect `read`) | `scene_inspect` :2524, `scene_query` :2543, `scene_get` :2579, `scene_capture` :2787, `prefab_search` :2794, `prefab_get` :2804, `prefab_validate` :2813, `prefab_events` :2837 |
| Reversible write | `scene_create_object` :2596, `scene_update_object` :2633, `scene_update_many` :2669, `scene_move` :2695, `scene_pin` :2728, `scene_link` :2740, `scene_unlink` :2752, `scene_add_artifact` :2768 |
| Destructive | `scene_archive` :2714 (definitive; the id is tombstoned) |
| Prefab library (not scene UI) | `prefab_save` :2818, `prefab_edit_base` :2826 |

Facts that bind the Tool Brain:

- **One tool call = one `SceneCommand` = at most one revision.** Selection
  tools (`*_selection`, `jarvis/domain/scene_batch.py`) are all-or-nothing.
  Schemas are `additionalProperties: false` (`StrictDisplayMCP`, :2381).
- **The brain already has the user's authority** (`ALLOWED_SCENE_OPS`
  comment, `scene.py:293`). What stays refused is a truth of another layer
  (`runtime` execution fields, runtime-owned relations, resolver placement).
  So authority matrices need no change for a Tool Brain acting as `brain`.
- **The Tool Brain must act as `SceneActor.BRAIN`** (the Core HTTP route only
  accepts `brain` and `user`; `runtime` is 403, and the Control Center proxy
  forces `user`; `docs/scene-model.md` › *Actors over HTTP*). The actor is
  declared, not authenticated.
- **No focus operation exists** in the reducer (`docs/prefabs.md`:315 "Focus
  has no op"). "Focus a window" is today a browser-side gesture only
  (`onFocusIn`, `docs/prefabs.md`:381), not a runtime command.
- Everything the user sees in the scene is a **Jarvis scene object**: kinds
  `agent`, `job`, `artifact`, `attention`, `window`, `group`
  (`SceneObjectKind` :145); representations `point`, `capsule`, `window`
  (`Representation` :191); visibility `visible` / `hidden` (`Visibility`
  :199); disposition `active` / `archived` (`Disposition` :206).

### 1.2 Boards and Sessions

| Concern | Canonical owner | Anchor |
|---|---|---|
| Board / Session domain | `Board`, `JarvisSession`, `BoardConversationBinding`, `SceneRef` | `jarvis/domain/workspace_board.py:347,452,524,317` |
| Switch | `BoardService.switch(board_id, *, origin=)` (under `SpeechAuthority.lock`, 7-step transaction with rollback) | `jarvis/core/board_service.py:490`, `_switch_locked` :502 |
| New Session | `SessionManager.start_new_session(...)` | `jarvis/core/session_manager.py:434` |
| Reads | `BoardService.list/get/get_active/active_board_id`, `SessionManager.current/get/history` | `board_service.py:329-344`, `session_manager.py:398-425` |
| Brain-facing MCP | `jarvis-workspace`: `board_list/get/get_active/create/update/archive/switch`, `session_current/new/list/get`, `board_inspect`, memory and artifact tools | `jarvis/runtime/workspace_mcp.py:488-673` (`board_switch` :555, `session_new` :571) |
| Brain-origin switch semantics | `ORIGINS = {"user", "brain"}` (`board_routes.py:77`, never relayed to Core); with `origin: brain` **and** an agent turn in flight (`_ask_in_flight`, :184) the route answers `scheduled` (HTTP 202) and runs at turn end; with no turn in flight it runs at once; a second call replaces the first | `jarvis/runtime/board_routes.py:29-38,180-189`, `jarvis/runtime/workspace_boards.py:283-312`, `docs/boards.md` › *Switch* |
| Outcome events | Core bus `board.switched`, `board.voice_binding.changed` | `jarvis/core/speech_authority.py:31-32` |

Facts that bind the Tool Brain:

- A Tool Brain "switch Board" capability **is** `BoardService.switch`
  (via the same Core route `/api/boards/switch` or `workspace_boards`). Do not
  build a second Board state machine (decision D16).
- The deferral protects a brain turn from losing the floor under its feet. A
  Tool Brain call is not a brain tool call: S6/S7 must choose between
  `origin: "brain"` (deferred while a turn is in flight, so a mid-answer
  switch waits for the answer to be said) and `origin: "user"` (immediate, the
  floor moves at once). See gap G6. Either way the switch moves the speech
  binding (`SpeechAuthority`), which is exactly what the action queue must
  invalidate on.
- **The scene is global in V1.** `scene_ref.kind` is only `global`
  (`SceneRefKind` :223); `SceneRef.revision_at_leave` is informational. A Board
  switch does **not** change the scene objects. So "visible objects of the active
  Board" does not exist as a scene filter today (Issue
  `jarvis-board-session-context-runtime/Issues/per-board-scene-isolation.md`
  per `docs/boards.md`:1794).

### 1.3 Browser, window and process control: does not exist

Verified by search of `jarvis/`:

- No tool opens a URL, focuses, scrolls, goes back or forward, or zooms any
  browser or window surface. The only `webbrowser.open` is the one-shot launch
  of the Control Center page (`jarvis/app.py:1565`).
- A scene "window" is a Jarvis scene object (kind `window`, optional
  `payload.prefab`), not an OS or browser window. Prefab windows report
  `notify` events to the brain through `prefab_events`
  (`BrainContext.prefab_events`, `jarvis/domain/brain_context.py:1036`).
- Process, agent and job state are **read-only projections** into the scene
  (`exec_state`, `work_ref`; written by `runtime` only; `EXECUTION_FIELDS`
  `scene.py:313`). No UI tool starts, stops or focuses a process. Work
  cancellation is a separate Core route (`POST /v1/work/cancel`,
  `SceneTransport.work_cancel`).

**State of the contract: browser navigation does not exist.** Anything in the
handoff phrased as "open/focus URL, scroll, back/forward, zoom" is new surface
(Slice 07b), not an adapter over an existing one.

## 2. IDs and revision semantics

| Entity | Identity | Revision / version | Optimistic check available today |
|---|---|---|---|
| Scene | `SceneSnapshot.scene_id` (stable across restarts), plus `SceneService.epoch` :214, new at every Core `start()` | `SceneSnapshot.revision` (0 to 2^63-1, +1 per applied command; patch `revision = previous + 1`, `scene.py:1318`) | Cache key is `(scene_id, epoch, revision)`. Per-command precondition only through `apply_if(plan)` (plan sees the current snapshot under the lock) |
| Scene object | `object_id`: runtime stars `<source>:<external_id>` or hashed form (always contain `:`); brain objects `brain-<kind>-<uuid4 hex 12>` (`display_mcp.py:882,1303`); relations `brain-<relation kind>-<sha256[:16]>` (:1767); reserved forms refused for `brain`/`user` by `is_runtime_reserved_id` (`scene.py:1541`) | **No per-object revision.** Only the scene revision moves | A tombstone (`archived_ids`) makes any later command on an archived id `invalid / object_archived`: ids are never reused |
| Prefab | `prefab_id` (`jarvis.*` = base, protected) | integer `version`, instance pins a version (`scene_create_object prefab.version`) | `prefab.latest_version` in `scene_get` |
| Board | `board_id`: `"default"` or `board_` + opaque (`workspace_board._check_board_id`, `DEFAULT_BOARD_ID` :50, `BOARD_ID_PREFIX` :52) | **No revision**; `updated_at` and `last_opened_at` only | `SessionView`/`active_board_id` re-read; switch re-validates (archived, already active) inside the lock |
| Session | `jarvis_session_id`: `jsess_` + opaque (`SESSION_ID_PREFIX` :53) | none; `status` open/closed | `start_new_session(expected_session_id=...)` is the compare-and-swap |
| Conversation binding | `(jarvis_session_id, board_id) -> conversation_id`; the conversation id is what every event, turn and speech carries | none | n/a |
| Brain turn | `turn_id = "brain-turn-" + sha256(conversation_id, correlation_id)` (`domain/voice_admission.py:28`; `core/voice_admission.py:119`) | `BrainTurnAcceptance.revision` (working-state revision) | dedup by `correlation_id` |
| Browser / window surface | **none** | **none** | **none** |

Consequences for later Slices:

- A Tool Brain "object revision" precondition cannot be an object revision.
  Use the **scene revision + epoch** observed by the snapshot, and rely on the
  reducer's existing invalid results (`unknown_object`, `object_archived`,
  `unplaced`, ...) for object-level staleness. If a finer precondition is ever
  needed, it is a *domain* change (S6 decision), never a Tool Brain side table.
- The cheapest correct revalidation is **`SceneService.apply_if(plan)`**
  (plan built from the live snapshot, no await between check and write).
- `board_id` has no revision: Board staleness is "active Board changed", i.e.
  compare `active_board_id` (and the `board.switched` event) to the snapshot.

## 3. Speech, chunks, progress, interruption

### 3.1 What exists

Generation is not streamed: a brain answer reaches the mouth as a **whole**
`SpeechRequest` (`jarvis/domain/v2.py:452`: `id`, `correlation_id`, `work_id`,
`source: SpeechSource`, `outcome_id`, `chunks: tuple[SpeechTextSpan]`). So "the
future of the response" is real and known: the pending chunks of an already
generated text (decision D06 holds).

| Layer | Representation | Anchor |
|---|---|---|
| Provenance | `SpeechSource(turn_id, correlation_id, intent_id, intent_epoch, dependencies)`; `source.correlation_id == request.correlation_id` is validated | `jarvis/domain/speech_presentation.py:48`, `v2.py:~490` |
| Spans | `semantic_text_spans(text)`: explicit paragraph boundaries only, <= `MAX_SPEECH_CHUNKS` (16), contiguous exact ranges of the original text | `speech_presentation.py:127` |
| Merge (surface without output final, GPT-Live) | `single_output_spans` | `:143` |
| **Chunk id (deterministic)** | `presentation_chunk_ids(speech, spans)`: one span keeps the request id; several get `uuid5(NAMESPACE_URL, f"jarvis-speech:{speech}:{index}:{start}:{end}")`. Shared by the mouth (plays) and Core (reads dispatch proof in the voice ledger) | `speech_presentation.py:159`; users `core/brain_service.py:1357`, `runtime/speech_scheduler.py:2459` |
| Chunk object | `SpeechChunk(chain_id, index, count, span)`; `chain_id` = original request id | `speech_presentation.py:110`, built at `speech_scheduler.py:2464` |
| Chunk lifecycle | `SpeechCandidateStatus` (`eligible`, `selected`, `started`, `deferred`, `superseded`, `expired`, `completed`, `interrupted`, `unconfirmed`) held in `SpeechScheduler._candidates: {chunk_id: _Candidate(request, status, reason, chunk)}` | `speech_presentation.py:95`; `speech_scheduler.py:246` |
| Playout | `_ActiveSpeech` (`played_ms`, `interrupted`, `completion_basis`, ...) for the one speech playing | `speech_scheduler.py:206` |
| Heard evidence (Core) | `VoiceSpeechRecord` (`state: VoiceSpeechState`, `playback_status`, `played_ms`, `received_audio_ms`, `confirmed_text`), keyed by `VoiceCorrelation.speech_id` (= chunk id) | `jarvis/domain/voice_state.py:119`; `core/voice_ledger.py` |
| Heard text | **estimate only**: `estimate_heard_text(text, played_ms, total_ms)` is proportional, cut back to a whole word; no provider word alignment | `jarvis/domain/brain_context.py:372` |
| Diagnostic dump | `SpeechScheduler.presentation_snapshot()` -> `{source_complete, current_source, candidates[{status, reason, chunk{chain_id,index,count,span}, age_ms, ...}]}`. **No caller in `jarvis/`** (verified): it is a method awaiting a consumer, text excluded | `speech_scheduler.py:1882` |

Granularity of "progress": **chunk (paragraph) level**, plus `played_ms` for the
chunk being played; inside a chunk only a proportional estimate. There is no
`speech.chunk_progress` event and no per-word event today.

### 3.2 Interruption

1. The bridge stops playback and calls `SpeechScheduler.note_floor_taken("speaking" | "thinking")`
   (journal `voice.floor_taken`, event `mouth.floor.taken`) then
   `note_interruption(PlaybackCursor)` (`speech_scheduler.py:1364`): the active
   speech is marked `interrupted`, its chain is **blocked** (`_blocked_chains`),
   the rest of the queue is frozen until the new turn's addressing decision
   (`mouth.floor.released`, reason `addressed` / `noise` / `unaddressed` /
   `rejected` / timeouts).
2. Events: close `mouth.speech.interrupted` (public, `played_ms` attribute) for
   the interrupted chunk; later chunks of the chain end as `superseded` /
   `expired` / diagnostic closes (never played, text withheld).
3. Brain feedback: `BrainSpeechInterruption(text, heard_text, played_ms,
   total_ms)` through `BrainContext.interruptions`
   (`jarvis/domain/brain_context.py:395,1028`), built from
   `VoiceLedger.interrupted_speeches` (`core/voice_ledger.py:~200`).

A Tool Brain therefore receives interruption as `mouth.floor.taken` +
`mouth.speech.interrupted` (bus/log) and must treat all pending actions
triggered by chunks of that chain as obsolete (cancel or supersede).

## 4. Event and correlation ID mapping

Canonical store: `jarvis/domain/conversation_events.py` (schema v1), details in
[conversation-events.md](conversation-events.md). Mapping that the Tool Brain
timeline must join on (`TRACE_JOIN_FIELDS` :431):

```text
User      user.transcript.accepted    correlation_id C, turn_id T = "brain-turn-"+h(conv, C)     (producer core.voice_admission)
Brain     brain.turn.accepted         correlation_id C, turn_id T                                 (core.brain_service)
          brain.speech.requested      correlation_id C, speech_id R (request id, source_ids (R,)) (core.brain_service)
          brain.message.published     correlation_id C, outcome_id O
          brain.work.*                correlation_id C, work_id W (span_id = W)
Mouth     mouth.speech.queued/held    correlation_id C, speech_id = chunk id K                    (voice.speech_scheduler)
          mouth.speech.started        span_id = speech_id = K; parent_event_id = id(brain.speech.requested, source_ids (R,))
          mouth.speech.completed | interrupted | superseded | expired | failed | unconfirmed   (close of the same span K)
          mouth.floor.taken/released  correlation_id (of the interrupting/decided turn), attributes.while, source id floor_id
          mouth.reflex.started        correlation_id C, source_ids (C, output_id)
Subagent  subagent.started/...        task_id, span_id = task_id
Tool      tool.call.started/finished  span_id = call_id (realtime model tool calls only)
```

- **Joins**: `C` links User -> Brain -> every chunk. `parent_event_id` links
  each Mouth chunk to its `brain.speech.requested`. `K` (chunk id) is a pure
  function of `R` and the spans (section 3.1), so a Tool Brain can compute the
  chunk ids of a not-yet-spoken answer. A one-paragraph answer has `K == R`.
- **Event id** is `cev-` + sha256 of
  `["conversation-event", producer, event_type, conversation_id, *source_ids]`
  (`derive_conversation_event_id` :606): `producer` is part of the identity,
  so one producer per fact.
- **Producers**: Core emitter `jarvis/core/conversation_event_emitter.py:199`
  (`core.*` producers, not ingestable); out-of-process forwarder
  `jarvis/runtime/conversation_event_forwarder.py:188` (producers
  `voice.speech_scheduler`, `voice.realtime_audio`, `control_center.agent_tasks`
  :70-72). Ingestion (`jarvis/domain/conversation_event_ingest.py:59`) **refuses
  by denylist**: actors `user`/`brain` and producer `core`/`core.*` are
  Core-owned. There is **no producer allowlist** (this corrects an assumption
  in the readiness note: a new actor with a non-`core` producer is ingestable
  without any registry change).
- Instrumentation never changes behaviour (`record()` returns `None` on any
  invalid fact, counters only).
- **Timeline UI**: four hard-coded lanes (`LANES`,
  `jarvis/runtime/control_center_timeline.js:213`: `user`, `mouth`, `brain`,
  `subagent`). `laneOf` (:223) sends an unknown actor (`tool`, `system`) to
  `mouth` if the producer starts with `voice.`, else to `brain`. A new actor
  would silently land in the Brain lane until `laneOf`, `LANES`, the JS `SPECS`
  mirror (checked by `tests/unit/test_control_center_timeline_js.py`), CSS and
  docs are updated together.
- **Storage**: `actor` and `event_type` are plain TEXT, no CHECK
  (`docs/conversation-events.md` › *Schema*): a new actor or type needs **no
  SQLite migration**. A new envelope id column (an `action_id` correlation
  field) would need one, and would break the "span_id = natural id" pattern the
  `tool.call.*` events already use. Avoid it (see 6.3). Caveat: rows with an
  unknown `event_type` are *undecodable* for an older reader (skipped and
  counted, never returned): rollbacks lose Tool Brain rows from view.
- **Redaction**: attributes outside `ATTRIBUTE_KEYS` (:233) are rejected;
  forbidden name segments include `reasoning`, `thinking`, `prompt`,
  `arguments`, `args`, `token` (:246-254). Tool arguments and model reasoning
  therefore can never be stored in an event; `arguments_redacted: true` is the
  existing way to say "arguments exist".

## 5. MCP catalog and tool metadata

| Concern | Canonical owner | Anchor |
|---|---|---|
| Per-tool metadata (the **only copy**) | `ToolMeta(label, side_effect, idempotent, atomicity, output_format, parameter_rules, output_notes, deprecation)` inside `ServerMeta.tools` | `jarvis/runtime/mcp_tool_meta.py:71,83`; `DISPLAY` :103; `SERVERS` :436 |
| Side-effect classes | `SideEffect = Literal["read", "write", "destructive"]` | `mcp_tool_meta.py:29` |
| Annotations | `tool_annotations(server, name)` / `annotation_hints` derive MCP hints from the class | `:454-474` |
| Introspection of the **real** FastMCP servers (inert backend, nothing invoked) | `build_introspection_server(server)` :67, `describe_tool` :223, `build_catalog()` :256 | `jarvis/runtime/mcp_catalog.py` |
| Descriptor fields | `name, server, qualified_name (mcp__<server>__<tool>), category, label, summary, description, input_schema, parameters, parameter_rules, output, side_effect, idempotent, atomicity, annotations, deprecation, context_bytes` | `mcp_catalog.py:223` |
| Surfaced to humans | Control Center MCP inspector (`/api/mcp*`), contract `docs/mcp/tool-contract.md` | |
| Per-turn dynamic data the brain gets | `BrainContext` blocks (`board`, `session_context`, `prefab_events`, `presentation`, `interruptions`, `pending_replies`) and read tools (`scene_inspect`, `settings_describe` option lists) | `jarvis/domain/brain_context.py:1016` |

Facts that bind S2:

- Servers are **built once per brain launch**: enums and descriptions in a
  brain's tool schemas are frozen for the process. There is no per-turn
  "valid choices" injection. The main brain's frozen behaviour must not change.
- A Tool Brain is its *own caller*, so it can receive a **per-decision
  projection** of the same descriptors (`describe_tool` output) with a runtime
  `choices` block computed from authoritative state at snapshot time. The
  projection reads `ToolMeta` / `build_catalog`; it must not introduce a
  Tool-Brain-only registry (D13, D20).
- `ToolMeta` has no notion of "UI surface", "reversible UI" vs "destructive",
  "needs preconditions" or "choice provider". `side_effect: write` covers both
  `scene_move` (reversible) and `prefab_save` (library write). S2 extends
  `ToolMeta` (single copy) rather than adding a parallel table; the parity test
  `tests/unit/test_mcp_catalog.py` guards registration order.

## 6. Gap report: what S2..S10 create versus reuse

### 6.1 Reuse as is (do not rebuild)

| Need | Reuse |
|---|---|
| Scene mutation, authority, atomicity | `apply_scene_command`, `SceneService.apply/apply_if`, `jarvis-display` tools, actor `brain` |
| Scene reads and change feed | `SceneService.snapshot/patches_since/wait_for_revision`, `/v1/scene/*` |
| Board switch / Session new | `BoardService.switch`, `SessionManager.start_new_session`, `jarvis-workspace` `board_*`/`session_*` |
| Chunk identity | `presentation_chunk_ids`, `SpeechChunk`, `SpeechSource` |
| Heard evidence | `VoiceSpeechRecord`, `PlaybackCursor`, `BrainSpeechInterruption` |
| Event store and timeline | `ConversationEventType` + `_SPECS`, emitter / forwarder, `/v1/conversation-events*`, `control_center_timeline.js` |
| Tool metadata and introspection | `mcp_tool_meta.py`, `mcp_catalog.py` |
| Display seam (Presentation mode) | `PresentationDisplaySink` (`jarvis/core/presentation_display.py:67`), swap point `jarvis/runtime/presentation_runtime.py:~1762` (`DirectSceneDisplaySink`, `presentation_display_sink.py:37`) |

### 6.2 Gaps (each with the Slice that must close it)

| # | Gap (verified absent) | Closed by | Naming / decision |
|---|---|---|---|
| G1 | Browser / window navigation primitives (open or focus URL, scroll, back/forward, zoom), focus op, browser-surface ids | S7 (07b) | New display-surface verbs behind one owner; never in `jarvis-display` scene ops without a domain decision. Names: `surface_open`, `surface_focus`, `surface_scroll`, `surface_history`, `surface_zoom`; ids `surf_<opaque>` |
| G2 | **Closed by S2 (section 8).** Dynamic choices (`choice_provider`) and Tool-Brain projection of the catalog | S2 | Extend `ToolMeta` with `ui_surface`, `reversibility` (`reversible` / `irreversible`), `preconditions`, `choice_providers`; projection function next to `describe_tool` |
| G3 | Per-object revision | decided (agent 0): **not added** | use scene `(scene_id, epoch, revision)` + `apply_if` + reducer refusals |
| G4 | **Closed by S3 (section 9).** Perception snapshot (compact, board-scoped) | S3 | Pure projection over `SceneSnapshot` + `SessionView` + speech projection. Scene is global: Board-scoping is a presentation filter, say so |
| G5 | **Closed by S4 (section 10).** Speech progress projection: no `chunk_progress` event, no consumer of `presentation_snapshot()`, no word alignment | S4 | A read-only `SpeechProgress` projection (chunk level + `played_ms`, proportional inside a chunk). Do **not** add a second truth or per-word events. If an event is unavoidable, extend `mouth.speech.*` attributes |
| G6 | Board switch `origin` for a Tool Brain call | decided (agent 0): `origin: "brain"` | `ORIGINS` is closed to `user`/`brain`. Use `origin: "brain"` (inherits the turn-end deferral, safest while Jarvis speaks). Adding an origin token is a `board_routes.py` change and needs a decision |
| G7 | **Closed by S4 (section 11).** Jarvis to Tool Brain intent channel | S4 | Event `brain.ui_intent.published` (instant, diagnostic, Core-owned), correlation `C`, speech `R` optional; produced from a **typed** brain tool (non-prose, D05). Speech planning needs no new event: `brain.speech.requested` already carries the full generated text and `R` |
| G8 | Decision port, deterministic decider | S5 | `ToolBrainDecider` port (provider-neutral), fake decider; real adapter reuses `cli_catalog`/`model_catalog`. No API-model brain exists |
| G9 | Action queue with speech/event triggers, revalidation, replan | S6 | Ephemeral queue, invalidated on Board/Session authority change; trigger vocabulary = chunk id `K`, event type, `correlation_id`; revalidate via `apply_if` |
| G10 | Tool Brain lane in the timeline | S9 | New actor, event types, `laneOf` + `LANES` + CSS + JS `SPECS` + docs, in one change |
| G11 | Ownership guardrails (shadow vs live, destructive tools) | S8 | Mode default `shadow`; mechanical guard on `side_effect == destructive` / `reversibility != reversible` |
| G12 | Public intake for Presentation S08 | S10 | Document at Level 3: Tool Brain intake replaces `DirectSceneDisplaySink` at the swap point; `PresentationOutputIntent` only gets additive fields |

### 6.3 Canonical names (proposal, to be locked by S9 with the contract change)

Convention verified in the registry: `ConversationEventType.value =
"<actor>.<noun>.<verb>"` (or `"<actor>.<verb>"`, e.g. `subagent.started`) where
`<actor>` equals the `ConversationActor` value;
verbs are past participles for facts (`accepted`, `published`, `requested`,
`started`, `completed`, `interrupted`), `*.started` / `*.completed|failed` for
spans, `snake_case` nouns. Adding a type is a contract change: enum,
`_SPECS`, `conversation-events.md` table and tests together.

Actor: `ConversationActor.TOOL_BRAIN = "tool_brain"`. Not `TOOL`: `tool` means
"a tool call made by the realtime model" (`tool.call.*`), a different producer
and lane.

| Proposed event type | Shape | Visibility | Required ids | Notes |
|---|---|---|---|---|
| `tool_brain.wake.requested` | instant | diagnostic | `correlation_id` optional | attributes `reason` (wake class), `source` (`event` / `tick`) |
| `tool_brain.snapshot.captured` | instant | diagnostic | | `revision` = scene revision seen |
| `tool_brain.decision.made` | instant | diagnostic | | `status`, `model`, `tokens`, `duration_ms`; no content |
| `tool_brain.inspect.requested` | instant | diagnostic | | `tool_name` |
| `tool_brain.action.queued` / `.cancelled` / `.rescheduled` | instant | diagnostic | | `priority`, `reason`; the action id is the `source_ids` entry and not an envelope field |
| `tool_brain.action.invalidated` | instant | diagnostic | | `code` = reducer refusal (`unknown_object`, `object_archived`, stale revision ...) |
| `tool_brain.action.started` | span open | diagnostic | | `span_id` = action id (like `tool.call.*`), `tool_name`, `arguments_redacted: true` |
| `tool_brain.action.completed` / `.failed` | span close | diagnostic | | `revision` = resulting scene revision, `code`, `error_class` |
| `tool_brain.replan.requested` | instant | diagnostic | | `reason` |
| `brain.ui_intent.published` | instant | diagnostic | `correlation_id` | actor `brain` (Core-owned); `kind` attribute |

Rules for these:

- `content` forbidden everywhere on `tool_brain.*` (reasoning and arguments must
  not leak; `reasoning`/`arguments` segments are already forbidden keys). A
  bounded human summary, if wanted, is a deliberate S9 decision.
- Reuse existing allowlisted attributes (`reason`, `code`, `status`, `kind`,
  `source`, `priority`, `revision`, `model`, `tokens`, `tool_name`,
  `duration_ms`, `arguments_redacted`, `error_class`) before adding any
  (`ATTRIBUTE_KEYS`, one more reviewed key at most per need).
- Producer id: if the Tool Brain runs inside Core, `core.tool_brain` through the
  Core emitter; if out of process, `tool_brain.runtime` through the forwarder
  (ingestable). Pick once: the producer is part of `event_id`.
- Do not invent `speech.chunk_started` / `speech.chunk_completed` /
  `speech.interrupted`: they already exist as `mouth.speech.started` /
  `mouth.speech.completed` / `mouth.speech.interrupted` (+ `mouth.floor.taken`),
  keyed by the chunk id. Only `speech.chunk_progress` has no counterpart (G5).

Non-event names: `ToolBrainDecider` (port), `ToolBrainAction` (queue record),
`SpeechProgress` (projection), `UiPerception` (snapshot). Use `ui` in prose
(user-visible surface), never "browser" for scene windows.

### 6.4 Cross-task dependencies (all merged in `main`)

`jarvis-scene-window-prefab-foundation` (prefab and window contract),
`jarvis-board-session-context-runtime`, `jarvis-mcp-semantic-batch-inspector`,
`jarvis-conversation-observability-timeline`,
`jarvis-session-context-recording-runtime`, and
`jarvis-presentation-interaction-mode` (its Slice 08 display sink is deferred
until this task's intake exists: gap G12). No blocking ambiguity remains; the
decisions needing a human are G3 (per-object revision) and G6 (switch origin),
both with a stated default.

## 7. Conformance

`tests/unit/test_tool_brain_contracts.py` pins: symbol existence (section 1 to
5 anchors), `ALLOWED_SCENE_OPS` shape, `SceneObjectKind`, `ConversationEventType`
registry invariants (actor prefix, one spec per type, span openers), the absence
of any browser-navigation tool in `jarvis-display` metadata, deterministic
chunk ids, and a User -> Brain -> Mouth correlation fixture. When a Slice
creates something listed as a gap, it updates this page and the matching test
in the same change.

## 8. UI tool choice contract (Slice S2, Level 3)

Goal: the Tool Brain builds a valid UI call **without inventing an identifier**.
It picks from values the runtime derived from authoritative state a moment ago,
and the same validator can refuse the call at mutation time.

### 8.1 What lives where (no second registry)

| Piece | Owner |
|---|---|
| Per-tool UI facts: `ui_surface` (`scene` / `board`), `reversibility` (`reversible` / `irreversible`, writes only), `preconditions` (codes), `choice_providers` (parameter -> provider id) | `ToolMeta` in `jarvis/runtime/mcp_tool_meta.py` (the one copy). Vocabularies `CHOICE_PROVIDERS` and `UI_PRECONDITIONS` live next to it |
| Descriptor field `ui` (`null` for non-UI and external tools) | `mcp_catalog.describe_tool` via `ui_projection` |
| Provider implementations, state read, validator, manifest | `jarvis/runtime/tool_brain_choices.py` |

`reversibility` refines `side_effect`, it does not replace it. Mechanical
guardrails (S8) key on `side_effect == "destructive"` **or**
`reversibility == "irreversible"`. Tagged tools (V1): the 13 `scene_*` tools of
`jarvis-display` (`scene_archive` is `irreversible`) and `board_list`,
`board_get`, `board_get_active`, `board_switch` (`reversible`). Prefab library,
settings, memory, `session_*`, `board_create/update/archive` are **not** UI
tools here (`ui = null`); promoting one is a `ToolMeta` change plus a provider
when it takes an id. Browser primitives (G1) are S7.

### 8.2 Choice providers

`ChoiceProvider(provider_id, list_choices(UiState), refusal(UiState, value))`.
A `Choice` is `value` (stable id, drives execution), `label` (<= 60 chars, one
line, never an authority) and `meta` (compact typed facts). One implementation
per `CHOICE_PROVIDERS` id (`PROVIDERS`, tested):

| Provider | Legal values now | Meta | Refusal code when absent |
|---|---|---|---|
| `scene.object` | active scene objects (visible first, then by id) | `kind, category, representation, visibility, exec_state, pinned, placed` | `object_archived` (tombstoned) else `unknown_object` |
| `scene.relation` | relations the brain may unlink (not `is_runtime_owned_relation`) | `kind, from_id, to_id` | `runtime_owned` else `unknown_relation` |
| `board.switchable` | non-archived Boards, current one marked | `status, active, board_kind` | `board_archived` else `board_not_found` |
| `board.readable` | every Board, archived included | same | `board_not_found` |

Codes are the owners' own (`SceneRefusal`, `BoardErrorCode`), so a Tool Brain
refusal and a reducer or service refusal read the same. One deliberate
strictness: `scene_unlink` of a non-existent id is a `duplicate` no-op in the
reducer; the validator refuses it (`unknown_relation`) because the Tool Brain
must not fabricate ids.

### 8.3 Authoritative state and freshness

`read_ui_state(scene, boards) -> UiState` reads `SceneService.snapshot()` and
`epoch`, `BoardService.list(include_archived=True)` and `active_board_id()`. A
scene that is not served gives `scene=None` (validator code
`scene_unavailable`); any other failure propagates (a guessed state would be a
fabricated id). `UiState.ref() -> StateRef(scene_id, epoch, revision,
active_board_id)` is what a decider keeps from its snapshot. Per the G3
decision there is **no per-object revision**:

- other `scene_id` / `epoch` -> `stale_scene_epoch`; other `active_board_id` on
  a Board tool -> `stale_active_board`;
- an older scene `revision` is **not** a refusal (ids are stable and never
  reused): it is reported as `Validation.revision_drift`; object-level
  staleness is the reducer's job (`unknown_object`, `object_archived`, ...);
- the atomic read-then-write stays `SceneService.apply_if(plan)` (section 2);
  the validator is a cheap pre-check, not a lock.

### 8.4 Validator

`validate_call(server, tool, arguments, state, *, observed=None) ->
Validation(refusals, revision_drift)`, pure. Order: unknown tool
(`unknown_tool`), non-UI tool (`not_ui_tool`), unserved scene, `observed`
freshness, then every parameter with a provider: **each** value (a list is
checked element by element, all failures reported) must be in the **full**
legal list, not only the advertised page. Absent optional parameters are not
checked (the schema decides). Same code for the Tool Brain and any Python
caller. The main brain's MCP servers are frozen per launch and are **not**
wired to it (their behaviour is unchanged); S6 calls it right before
`apply_if`. Read tools are validated too (a Tool Brain must not read ids it
invented), although the MCP read itself answers `not_found`.

### 8.5 Manifest

`build_manifest(catalog, state, *, include_surfaces=None, include_tools=None)`
(pure) and `await tool_brain_manifest(scene, boards, ...)` (reads state and the
cached catalog). Shape: `schema: "tool_brain.manifest/1"`, `state` (the
`StateRef`), `precondition_rules` (code -> rule, said once), `choices`
(provider id -> `{total, truncated, items[<= 48], unavailable?}`, said once per
provider) and `tools[]` = `name, server, label, summary (<= 140), surface,
side_effect, reversibility, idempotent, atomicity, preconditions[],
parameter_rules[], parameters[]`. Each parameter has a `mode`:

- `provider`: value taken from `choices[choices_ref]`;
- `enum`: closed list in the schema (`constraints.enum`);
- `bounded`: boolean or numeric range (`constraints`);
- `free_form`: the only case where the model writes the value (titles,
  summaries, `select` filters, new ids). Kept minimal: no `*_id` / `*_ids`
  parameter is free-form, except `scene_link.relation_id` (a **new** optional
  id, derived when absent). Free-form values are bounded by the advertised
  schema only.

Parameter descriptions are cut to 100 chars. The full 17-tool manifest is about
25 KB for a 4-object scene (roughly 7k tokens): use `include_surfaces` /
`include_tools` for a targeted wake. The cap of 48 only limits what is
*advertised*; a decider narrows with the `scene_query` read tool, and the
validator always sees the full list.

### 8.6 Trace evidence

`agent-trace-analysis` is mandatory for this Slice but no model is in the loop
yet: the evidence is the deterministic manifest and verdict fixtures in
`tests/unit/test_tool_brain_choices.py` (size budget, refusal codes, no
content). Real-model trace evidence belongs to S5 and S10 once a decider
exists.

## 9. Perception and world model (Slice S3, Level 3)

Goal: a decider understands what the user sees from a **bounded** snapshot and
zooms on one stable id with targeted reads, without full-state dumping.
Perception is a **projection**: no state, no write, no second source of truth.
Everything comes from the S2 `UiState` (`read_ui_state` over `SceneService` and
`BoardService`). Module `jarvis/runtime/tool_brain_perception.py`.

### 9.1 Snapshot (`tool_brain.perception/1`)

`build_perception(state, *, speech=None, queue=None, max_bytes=8192) ->
UiPerception` (pure) and `await perceive(scene, boards, ...)` (reads owners).
Keys: `schema`, `state` (the S2 `StateRef`: scene id, epoch, revision, active
Board; no per-object revision, G3), `board` (`active`, up to 8 active Boards,
active first, `more`, `archived`, `scene_scope: "global"`: the scene is global
in V1, so Board scoping is a presentation fact, never a filter), `scene`
(`null` when not served; else `counts` (objects, hidden, relations, by kind, by
non-unknown exec state), `objects[]`, `relations[]`), `surfaces`
(`status: unavailable`, empty: no browser/window surface exists, G1/S7),
`queue` and `speech` seams, `truncated`, `omitted {objects, relations}`,
`budget {max_bytes}`.

Object entry: `id, kind, category, label (<= 60), shape` always; `state` (exec
state, omitted when `unknown`), `pinned` (only if true), `placed: false` (only
if unplaced), `summary` (<= 80 chars, one line), `prefab`. Payload items,
geometry, layers and work refs are **not** in the snapshot (inspect them).

### 9.2 Relevance and budget

- Only `visible` objects are listed (a hidden object is not seen; it is
  counted in `counts.hidden` and stays inspectable).
- Rank: attention signals, then nodes with an exec state needing a look
  (blocked, failed, running, pending, interrupted), then windows, then pinned,
  then the rest; ties by higher layer, then `object_id`. Deterministic.
- **Hard cap** `MAX_PERCEPTION_BYTES = 8192` (compact UTF-8 JSON, about 2.7k
  tokens at 3 bytes/token). Objects take the longest ranked **prefix** that fits
  80% of the room left after the skeleton; relations take the rest, only
  between kept objects. Over cap is impossible: a skeleton too big or an
  oversized wired `speech`/`queue` section raises `ValueError` (never silent).
  Measured: a 5-object scene is about 1.4 KB; a 400-note scene is 8.2 KB with 21
  objects kept and `truncated: true`, `omitted.objects: 379`.
- `truncated` is true iff something visible was omitted; a decider then
  narrows with `scene_query` (jarvis-display) or `get_information_on`.

### 9.3 Replay

`UiPerception.serialize()` is canonical (sorted keys, compact, no timestamp or
random field): same state gives the same bytes; `digest()` is its sha256. A
decision input is reconstructible from `(state, speech, queue, max_bytes)`.

### 9.4 Targeted reads (names in `INSPECTION_READS`)

All return `{schema: "tool_brain.inspection/1", ok, ...}`; a refusal carries
`code` + `id` (cut to 80 chars) and never raises.

| Read | Returns |
|---|---|
| `get_information_on(state, id)` | object (richer than the entry: title, summary <= 600, items <= 8 + total, geometry, work ref, origin, layer, related count), relation (`removable`) or Board (status, kind, `context_summary` <= 600, ref counts). Hidden objects included. Codes: `unknown_id`, `object_archived`, `scene_unavailable` |
| `list_related(state, id)` | links of a scene object, both directions, <= 24 (`total`, `truncated`) |
| `get_available_actions(catalog, state, id)` | UI tools from the canonical catalog (`ToolMeta` via `build_catalog`) where `id` is a legal value of a provider parameter, each re-checked by S2 `validate_call`; shows `side_effect` and `reversibility` for guardrails (S8) |
| `get_queue_state(queue=None)` | placeholder: `status: not_wired`, `count: 0` until S6 supplies a `QueueSection` |

`inspectable_ids(state)` lists the ids the reads accept now (objects incl.
hidden, relations, Boards). Id resolution order: object, relation, Board.

### 9.5 Seams for later Slices

- **S4 (speech)**: pass `SpeechSection("wired", {...})` built from its
  `SpeechProgress`; perception stores it verbatim and counts it in the budget.
  Perception invents no speech truth.
- **S6 (queue)**: pass `QueueSection("wired", items)`; `get_queue_state` reads it.
- **S5**: call `perceive(...)`, keep `state.ref()` for `validate_call(observed=)`.
- **S7**: when browser surfaces exist, fill `surfaces` from their one owner.

## 10. Speech progress (Slice S4, Level 3)

Goal: a decider knows what Jarvis is saying **now**, what generated segment
comes **next**, and which pending segments an interruption made **obsolete**.
Module `jarvis/runtime/tool_brain_speech.py`; conformance
`tests/unit/test_tool_brain_speech.py` (snapshots plus a real `SpeechScheduler`).

Read-only projection, **no second speech truth** and **no new `speech.*` event**
(decision R4): the plan is `SpeechScheduler.presentation_snapshot()` (finally
consumed; additive key `floor: {while, decision} | null`), the listening proof is
`VoiceSpeechRecord` handed in as `ChunkEvidence` (`evidence_from_voice_records`:
`total_ms` only once generation is `COMPLETED`, same rule as
`VoiceLedger.interrupted_speeches`). Listening facts stay the existing
`mouth.speech.started/completed/interrupted/superseded/expired/unconfirmed` and
`mouth.floor.taken/released`, keyed by chunk id `K` (section 4); that is the
"authoritative playback layer" emission required by the Slice.

`SpeechProgressTracker.observe(snapshot, evidence=None, *, texts=None,
max_bytes=2048) -> SpeechProgress`; `.to_section()` is the `SpeechSection("wired",
data)` S3 seam (perception counts it in its 8 KB budget). Shape
`tool_brain.speech/1`: `chains[<= 3]` (`chain` = request id R, `corr` = C, `n`,
`state` = `playing | interrupted | frozen | queued | done`, `heard`, `pending`,
`cursor`, `basis`, `chunks[]`, `obsolete?`, `restarts?`), `more_chains`, `floor`,
`obsolete_chunk_ids[<= 8]`. A chunk entry is `id` (= `presentation_chunk_ids`),
`i`, `ph` (`pending | playing | heard | interrupted | obsolete | unconfirmed`),
`s`/`e` (offsets in the original response text), `played_ms` (playing or cut),
`preview` (<= 60 chars, only when the caller supplies the response text, the
`brain.speech.requested` content; scheduler snapshots never carry text). Only
the cut chunk, the playing chunk and up to 3 upcoming chunks are listed; the
rest is counted.

- **Granularity**: chunk (paragraph). `cursor` = absolute offset in the response
  text: chunk end for heard chunks; inside the playing chunk
  `start + (end-start) * played_ms/total_ms` (`basis: proportional`), or the chunk
  start while `total_ms` is unknown (`basis: chunk_start`, a lower bound). No word
  alignment exists and none is invented.
- **Monotonic**: the tracker keeps the highest cursor per chain, so a regressing
  proof never moves it back. Explicit restart: a chain that returns entirely to
  `pending` after progress resets its cursor and bumps `restarts`. State of a
  chain that left the scheduler is dropped.
- **Interruption**: a chunk `interrupted` makes the later, unplayed chunks of its
  chain `obsolete` (`chain_interrupted`; section 3.2: chain blocked, never
  resumed). `superseded` / `expired` chunks are `obsolete` too. `unconfirmed`
  is never counted as heard. S6 cancels every queued action bound to a chunk id
  in `obsolete_chunk_ids` (or whose chain `state` is `interrupted`).
- **Budget**: `MAX_SPEECH_SECTION_BYTES = 2048`; reduction order previews, then
  upcoming chunks, then chains; a section that still does not fit raises
  `ValueError` (never silent truncation).
- **Future context** is the already generated response (spans, previews), never
  hidden reasoning.

## 11. Jarvis UI intent (Slice S4, Level 3, closes G7)

Goal: Jarvis tells the Tool Brain **what it wants the user to see**, typed and
bounded, and never a low-level command. Domain `jarvis/domain/ui_intent.py`;
Core `jarvis/core/ui_intents.py` + `BrainOrchestrator.publish_ui_intent`;
route `POST/GET /v1/ui-intents`; tool `ui_intent_publish` on `jarvis-display`;
reader helpers `jarvis/runtime/tool_brain_intents.py`; conformance
`tests/unit/test_tool_brain_intents.py`.

### 11.1 Channel decision (simplest canonical one)

An **MCP tool on an existing server**, not a typed block in the answer text.
Reasons: (1) G7 and D05 already name a typed brain tool; (2) a block inside the
answer would have to be stripped from the text before `semantic_text_spans` /
`presentation_chunk_ids` and from the history the brain re-reads, which puts the
speech path (exact span ranges, chunk ids shared with Core) at risk for no gain;
(3) the tool reuses the whole existing path (CLI brain -> `jarvis-display` ->
`CoreSceneTransport` -> Core, same token, same error and journal conventions);
(4) the paragraph anchor does not need the text. The server is `jarvis-display`
because it is the one already gated by `scene.enabled` and already holds the
Core transport; the tool is **not** a UI action (`ToolMeta.ui_surface = None`,
absent from the Tool Brain manifest, `docs/mcp/tool-contract.md` amendment).

### 11.2 Payload (`UiIntentDraft`)

`kind` (`reveal | attention | relevance | dismiss`), `refs[<= 8]` (`{kind:
object | board, id}`; `object` = S2 provider `scene.object`, `board` =
`board.switchable`, one table `PROVIDER_OF_REF`), `subject` (one line <= 80, for
what has no id yet), `timing` (`now | with_speech` default `| after_speech`),
`paragraph` (0..15, only with `with_speech`). Needs `refs` or `subject`.
Strict codec (unknown fields refused). **No** coordinates, layer, tool name or
command exists in the type. `paragraph` is the `SpeechChunk.index` of the
response paragraph the screen should follow: the chunk id is computed with
`anchor_chunk_id(draft, request_id, text)` (`presentation_chunk_ids`), no text
or id has to be copied by Jarvis.

### 11.3 Core semantics

Core mints `intent_id` and time, attaches the intent to the **in-flight turn** of
the speaking conversation (`correlation_id` C; the tool cannot know it) and keeps
it in a bounded registry (<= 8 per turn, <= 64 per conversation, oldest
forgotten and counted). No turn in flight: refused `no_turn_in_flight` (HTTP 409,
never retained without anchor); over the bound: `too_many_intents`. Shape errors
are HTTP 400 / tool `invalid_argument`, sent before anything is stored. Refs are
**not** validated against live state at publication (an intent is a hint, not a
right); the Tool Brain does it when it decides:
`check_intent_refs(draft, state)` reuses the S2 providers and owner codes
(`unknown_object`, `object_archived`, `board_not_found`, ...).
`GET /v1/ui-intents?conversation_id=&correlation_id=` returns the retained
intents (S5 reads them; the registry is not persisted, like the queue, D2).

### 11.4 Event `brain.ui_intent.published`

Actor `brain`, instant, diagnostic, producer `core.brain_service`, required
`correlation_id`, **content forbidden**, `source_ids = (intent_id,)` (no
envelope field, no migration). Attributes: `kind`, `timing`, `ref_count`, and
`paragraph` when set; three keys were added to `ATTRIBUTE_KEYS` (`timing`,
`ref_count`, `paragraph`), one reviewed need each. Refs and `subject` never leave
the registry. The event is registered with the JS `SPECS` mirror, a dot type and
a label in `control_center_timeline.js`, and in
[conversation-events.md](conversation-events.md).

### 11.5 Status of an intent against the speech (`intent_status`)

`intent_status(draft, correlation_id, speech_progress) -> due | pending |
obsolete | unanchored`, a pure function of `SpeechProgress.data` (per-chunk
`phases` string: `p` pending, `P` playing, `h` heard, `i` interrupted, `o`
obsolete, `u` unconfirmed). `now` is always due. `with_speech`: due once the
paragraph was started (even cut: its beginning was said), `pending` before,
`obsolete` when the paragraph will never be said (interruption made the tail
obsolete, superseded or expired, or the paragraph does not exist). Without a
paragraph: due once the response started. `after_speech`: due when the chain is
`done`, obsolete when interrupted. `unanchored`: no speech of that turn in the
scheduler. This is what makes "interruption marks future speech-bound actions
obsolete" a testable rule; S6 maps it to cancelling queued actions.

## 12. Jarvis capability awareness (Slice S4, Level 3)

Goal: Jarvis knows a Tool Brain exists, knows the whole UI capability surface,
never claims an action unavailable because "another brain does it", and knows
who executes the screen and how to declare an intent. Module
`jarvis/runtime/tool_brain_brief.py`, wired in `build_agent_brief`
(`render_tool_brain_brief(context["tool_brain"])`) and in
`ControlCenter._compose_ask` (added only when `scene.enabled`, i.e. when
`jarvis-display` is declared to the CLI; legacy callers without a `context`
dict get the text unchanged). Conformance `tests/unit/test_tool_brain_brief.py`.

- **Per turn, not in the system prompt**: the mode changes at run time (like
  `BRIEF_PRESENTATION_MODE`), and `BRAIN_DISPLAY_PROMPT` is fingerprint-tested
  and stays untouched. About 1.76 KB (`MAX_BRIEF_BYTES = 1900`).
- **Capability surface** = `ui_capability_surface()`, read from `ToolMeta`
  (`ui_surface`, `side_effect`, `reversibility`: the single copy S2 projects). A
  test pins it equal to the S2 manifest tool set, so catalog changes reach Jarvis
  without editing prose. Irreversible tools are named; browser/window navigation
  (G1) is stated as **not existing yet** (`MISSING_SURFACES`, to be emptied by S7)
  so Jarvis neither denies existing capabilities nor promises that one.
- **Ownership** (`tool_brain_ownership()`, the seam S8 flips):
  `jarvis_direct` = observation (default now: the Tool Brain does not act, Jarvis
  executes the display tools once per gesture as before, hence no duplicate
  execution); `tool_brain` = delegated (Jarvis must not call the UI **action**
  tools, lists exactly those from `ToolMeta`, keeps reads, and the **direct
  fallback is explicit**: only for a precise gesture an intent cannot say, or a
  Tool Brain outage, and Jarvis says so). The fallback stays observable through
  the existing tool traces (`display.*` journal lines, `tool.call.*`); S8 adds the
  mechanical guard and counter, not a hidden path.
- **How to publish**: the line names `ui_intent_publish` and its typed fields
  (section 11), states "what the user should see, never where or how", and
  requires a call during the turn, before the answer, unspoken.
- **Agent-trace evidence**: no model is in the loop (the Tool Brain does not
  exist), so the evidence is the deterministic brief and the correlated trace
  fixture `test_trace_fixture_one_long_response_joins_intent_speech_progress_and_interruption`.
  Real-model traces (does Jarvis call the tool, in time, once) belong to S5/S10.

### 12.1 Public API for S5-S10

| Need | Call |
|---|---|
| Speech section of the perception | `SpeechProgressTracker.observe(scheduler.presentation_snapshot(), evidence_from_voice_records(records), texts=...).to_section()` then `build_perception(..., speech=section)` |
| Retained intents of a turn | `GET /v1/ui-intents?conversation_id=&correlation_id=` or `BrainOrchestrator.list_ui_intents` (payload = `UiIntent.to_payload()`) |
| Is an intent still valid | `check_intent_refs(draft, state)` (S2 providers), `intent_status(draft, correlation_id, speech.data)` |
| Chunk an intent is anchored on | `anchor_chunk_id(draft, request_id, response_text)` |
| What to cancel on interruption | `SpeechProgress.data["obsolete_chunk_ids"]`, chain `state == "interrupted"`, `intent_status == "obsolete"` |
| Flip execution ownership | `tool_brain_ownership()` (S8) |
