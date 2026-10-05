# Slice 00 — blind repository audit (2026-10-05)

Run by a read-only Explore agent on `5378eb6` with only the product goal, before agent 0 read the handoff's docs. Kept verbatim.

# Presentation interaction mode: blind repository audit

Repo `C:/Projects/jarvis/bpm`. HEAD is `5378eb6` on `task/jarvis-presentation-interaction-mode`, which is `origin/main` plus one S0 commit. The local `main` ref is stale (`af23e78`). The only working-copy change is line endings in `tests/unit/test_interaction_mode_contract.py`. I did not open `tasks/jarvis-presentation-interaction-mode/`.

**The main finding: the "show prepared visual" path cannot work in production.** `DisplaySceneStager.reveal` at `jarvis/runtime/presentation_staging.py:100` calls `SceneDisplayTools.set_visibility`. That method was removed by `df28431` (2026-09-25), the day after Presentation's Slice 11 (`d7eeeb8`). The tests still pass because they use fakes that keep the method (`tests/unit/test_presentation_speculative.py:189`, `tests/unit/test_presentation_integration.py:218`). In real use every `reveal` fails into `speculative_reveal_failed` at `jarvis/core/presentation_speculative.py:1167-1175`, and `SHOW_PREPARED` falls back to a `REFRESH`, which stages yet another hidden object. The unmerged prefab branch had already recorded this independently as Issue `presentation-stager-reveal-calls-missing-set-visibility`.

---

## 1. Interaction mode (SIMPLE / PRESENTATION / REUNION)

**Domain contract**
- In `jarvis/domain/interaction_mode.py`:
  - `InteractionMode{assistant, presentation, meeting}` (:52), whose labels are SIMPLE, PRESENTATION and REUNION. There is deliberately no `InteractionMode.SIMPLE`.
  - `DEFAULT_INTERACTION_MODE = ASSISTANT` (:120).
  - Parsers and readers: `parse_interaction_mode` (:146), `parse_interaction_mode_label` (:168), `stored_interaction_mode` (:188), `ensure_activatable` (:214), `behaving_interaction_mode` (:230).
- `OutputDisposition` lives in `jarvis/domain/output_disposition.py:19`.
- The policy matrix is in `jarvis/domain/presentation_policy.py`: `PresentationSituation` (:44), `PRESENTATION_POLICY` (:146), `UNADDRESSED_SAFETY_KINDS=(ERROR,)` (:228), `may_speak` (:243).
- REUNION is listed everywhere but cannot be activated: a request gets 409 `interaction_mode_not_implemented`.

**Persistence and ownership**
- Core holds the live value: `InteractionModeService` (`jarvis/core/interaction_mode.py:174`).
  - `request(value, source)` (:245) and `add_listener(..., with_state, with_unchanged)` (:317).
  - Event `interaction.mode.changed` (:61), state carries `epoch` + `revision`.
- The stored preference is per Board: column `interaction_mode` plus `interaction_mode_origin` (`unset | migrated | user`) on `work_boards`, written by the `BoardService` listener. It is re-applied as `board_restore` / `board_switch`; an `unset` Board falls back to the default mode (`docs/boards.md:714-745`).
- The Control Center global key is now only migration input and no-Board fallback (`jarvis/runtime/interaction_mode_settings.py`, `SETTING_KEY` :47).
- Voice keeps a read-only `InteractionModeObserver` (`jarvis/runtime/interaction_mode_observer.py:49`), created at `voice_v2.py:137`, with its listener wired to the Presentation coordinator at `voice_v2.py:219-220`.
  - Its snapshot resync and event subscription live only inside `SpeechScheduler`, which exists only in continuous mode (`speech_scheduler.py:1610`, `:1912`).
  - On `voice_arch=legacy` the observer never moves, so Presentation is refused by a precondition (`app.py:1224-1228`).
- Board kind (`empty | meeting | presentation`) is metadata only. It never touches the mode, and no live behaviour depends on it (`docs/boards.md:198-217`).

**Brain hint**
- Core forwards the mode to the brain backend (`core/v2_app.py:350`, `adapters/control_center_brain.py:158-159, 412`).
- The per-turn brief `BRIEF_PRESENTATION_MODE` is at `runtime/control_center.py:612`, applied at :813.
- The `settings_set("interaction_mode")` handle is in `runtime/settings_mcp.py`.

**UI**
- `jarvis/runtime/control_center_interaction_mode.js`: a bottom-left selector driven by the 1 Hz `/api/status` poll (`gate` / `statusLost`), never optimistic.
- Routes: `GET/POST /v1/interaction-mode` and `/api/interaction-mode`.

**Tests**
- `test_interaction_mode_contract.py`, `_control_plane.py`, `_protocol.py`, `_hud_js.py`, `_hud_browser.py`, `test_settings_mcp.py`
- `test_board_service.py`, `test_board_switch.py`, `test_board_protocol.py`, `integration/test_board_session_e2e.py`

**Gaps**
- Presentation only works on continuous voice architectures.
- Board kind `presentation` does not imply or suggest the mode.
- The Control Center has no live view of the Presentation session (stats only reach the trace, see §8).

## 2. Ambient lane, authority, priority, privacy

**Capture: one microphone in PRESENTATION**
- `PresentationAudioSession` (`runtime/presentation_audio.py:116`) owns the microphone through `AudioCaptureHub` (`audio/capture_hub.py:411`).
- Ownership accounting is in `audio/input_ownership.py`.
- On entry the SIMPLE wake stack is suspended first, then the session starts (`presentation_runtime.py:1052-1112`).

**Explicit address**
- `ExplicitAddressLane` (`runtime/explicit_address_lane.py:75`) merges wake word and manual key into one typed `ExplicitAddressTrigger` (`domain/explicit_address.py`), with `triggers()` at :229.
- The lane is independent of ambient work: bounded queue, monotonic timestamps.
- `PresentationWakeRouter` (`presentation_runtime.py:569`) is the Voice `WakeWordBackend`. In PRESENTATION it calls `turns.arm(trigger)` before yielding (:714-734).

**Ambient pipeline**
- `AmbientIngestionLane` (`runtime/ambient_lane.py:356`) runs hub → `AmbientSegmenter` (`audio/ambient_segmenter.py`) → `TranscriptionBackend` → `store.observe()` (the tail, before any enrichment) → `analyse_ambient_text` (`domain/ambient_observation.py`) → `store.apply()`.
- Each analysed utterance emits at most 4 `AmbientTrigger`s (`MAX_TRIGGERS_PER_UTTERANCE`, `ambient_observation.py:76`).
- Transcription is a single task with `drop_oldest` bounded queues.
- An import-graph guard prevents the lane from importing any brain or turn types.
- Transcription exists only on an OpenAI stack (`app.py:773-785`). Otherwise `_AbsentTranscriber` makes the lane report itself as deaf (`ambient_deaf`).

**Authority**
- Ambient text never becomes a brain turn. `PresentationSituation.AMBIENT_OBSERVATION` is silent and grants no authority, and this is checked at construction.
- An addressed window is preroll 1.5 s + 12 s (`domain/presentation_addressed_turn.py:100-119`). It serves one turn, and `open()` refuses with no window (`core/presentation_addressed_turn.py:626-629`).
- **Gap:** when no window is armed, the turn still runs the normal SIMPLE path. In an ACTIVE continuous session, the realtime bridge receives the shared PCM (`voice_v2.py:876-881`). So room speech can still become an addressed or uncertain brain turn through the existing realtime addressing heuristics. The speech gate then classifies it with its own classifier. The ambient-vs-addressed boundary is strict only inside the armed window.

**Privacy**
- Ambient audio stays in memory. Nothing is written to disk except the staged-object ledger and the hidden scene objects (`OPERATIONS.md:3889-3895`).
- Explicit recording (`adapters/sounddevice_recording.py`) is a separate Core stream and is never counted by PRESENTATION (`input_ownership.py:26`).
- The session-context recording feeds the brain a `transcript_tail` under `BRIEF_AMBIENT_RULE` ("not addressed, no authority"; `docs/session-context.md:480-510`). That is today the only room-speech-to-brain path, and it is not Presentation.

**Tests:** `test_presentation_audio_capture.py`, `test_ambient_ingestion_lane.py`, `test_presentation_addressed_turn.py`, `test_presentation_integration.py`.

## 3. Working set and transcript tail

**Domain** (`jarvis/domain/presentation_working_set.py`)
- Collection caps (:90-112): topics 12, entities 24, claims 24, sources 12, resources 16, open questions 12, attention items 8.
- Tail caps: 16 entries / 4 000 chars / 600 chars per entry.
- Age bounds: tail 180 s, records 1 800 s, idle resource 600 s (:171-176); whole-set budget 120 000 chars (:163).
- Vocabulary: `UtteranceOrigin`, `ResourceTemperature`, `ResourceKind`, `ClaimStatus`, `AttentionCategory`.

**Store:** `PresentationWorkingSetStore` (`core/presentation_working_set.py:180`) with `bind_session`, `retire` (:302), `observe` (:351), `prune` (:424, called only from `ambient_lane.py:1083`), `apply` (:458) and `use_resource` (:541).

**Two stores exist.** The live one is built per session in the Voice process (`presentation_runtime.py:1408`). Core still builds `V2App.presentation_working_set`, which has no producer; this is documented in `docs/interaction-mode.md:388-395`.

**Tests:** `test_presentation_working_set.py`.

**Gaps**
- Pruning depends on the ambient lane running. If transcription is deaf, nothing prunes.
- The working set never reaches the brain (§5, risk 2).

## 4. Speculative preparation, sub-agents, priority

**Domain** (`domain/presentation_speculative.py`)
- Capability → tools table (:183) and risk table (:133).
- `AMBIENT_CAPABILITIES` excludes `DISPLAY_PREPARATION` (:204), so ambient work can never stage a visual. `SpeculativeGrant` (:263).
- Priorities P0 to P4 (:367): P0 is the addressed turn, P1 an explicit preparation, P2-P4 are speculative and can be sacrificed.
- Pool of 8 with 2 slots reserved for explicit work (:404, :408), so at most 6 speculative jobs.
- `TRIGGER_PREPARATION` (:550) maps ambient trigger kinds to priority and capabilities.

**Service:** `PresentationSpeculativeService` (`core/presentation_speculative.py:376`)
- Entry points: `submit_trigger` (:619), `reserve_explicit` (:647), `note_addressed_turn` (:673), `reveal` (:1144).
- `note_addressed_turn` preempts speculative jobs, lowest priority and newest first.
- The addressed turn preempts at `arm()` (`core/presentation_addressed_turn.py:555`) and uses `reserve_explicit` for `REFRESH` (:943).

**Runner:** `PresentationPreparationRunner` (`runtime/presentation_preparation.py:205`) launches restricted `ClaudeLocalAgent` sub-agents with profile `presentation_preparation` and `--tools` limited to `CLI_GRANTABLE_TOOLS` = Read, Glob, Grep, WebSearch, WebFetch (`claude_local.py:294`).
- MCP tools (`memory_search`, `scene_*`) are stripped. The service, not the agent, does the staging.
- If the agent CLI is not Claude, `_AbsentRunner` is used (`presentation_runtime.py:1498`).

**Not integrated with existing work lanes.**
- These sub-agents are not back-brain jobs (deliberately).
- They are not `CoreWork` items, not tracked by `AgentTaskTracker`, and emit no `subagent.*` conversation events.
- "Never delay an addressed request" holds only at the scheduling level: separate processes, a reserved explicit pool, preemption. There is no CPU or RAM arbitration.

**Tests:** `test_presentation_speculative.py`, `test_presentation_integration.py`.

## 5. Response and speech manifestation

**Classifier:** `classify_addressed_situation` (`domain/presentation_response.py:144`) is a lexical French classifier.
- Order: speak request (with negation handling) → leading question word → visual verb → "?" → otherwise a question. Silence requires positive evidence.
- `admit_presentation_speech` is at :190.

**Gate:** `PresentationSpeechGate` (`runtime/presentation_speech_gate.py:117`), owned by `SpeechScheduler` (:433).
- Methods: `note_addressed_turn`, `admit` (:214), `allows_preamble` (:238, always false in PRESENTATION), `settle_all` (:256).
- Enforcement point: `speech_scheduler.py:2371`. The preamble is suppressed at :957.
- Trace kinds: `voice.presentation.turn_classified`, `.speech_withheld`, `.turn_silent`.

**Addressed-turn delivery**
- The scheduler calls `note_addressed_turn` (`speech_scheduler.py:719`), opens the Slice 10 plan, then delivers (`speech_scheduler.py:803`).
- `CLARIFY` speaks the constant `CLARIFICATION_TEXT` as `SpeechKind.QUESTION` (:874-951).

**Requirement check**
- Visual commands are silent: yes, enforced by the runtime gate.
- Real questions may speak: yes.
- No unsolicited speech: speech with no addressed turn is limited to `ERROR` (`UNADDRESSED_SAFETY_KINDS`).

**Tests:** `test_presentation_response_policy.py`, `test_presentation_revalidation_contract.py`, `test_speech_presentation*.py`.

**Gaps**
- `ASK_BRAIN` carries no projection. `AddressedTurnContext.to_brain_context()` (`domain/presentation_addressed_turn.py:434`) is used only to measure size (:432). `LocalCoreClient.submit_brain_turn` (`protocol/client.py:293`) has no context parameter. `ACCEPTANCE_STATUS.md` marks this "NOT WIRED".
- The classifier is French-only and lexical.

## 6. Attention / fact-check cue

**Judge:** `decide_attention` (`domain/presentation_attention.py:496`).
- Requires confidence of at least 0.6 and verified provenance (sources must exist in the working set).
- Category is mapped from `ALERTING_VERDICTS`; output policy `FACT_CHECK_ATTENTION` is visual-only with a cue and no voice.

**Service:** `PresentationAttentionService` (`core/presentation_attention.py:127`), at most 2 alerts per batch. It writes an `AttentionItem` into the store and emits `presentation.attention.raised` to `trace.jsonl`.

**Path to the screen**
- `BackgroundEventLedger` reads the trace (`runtime/background_events.py:223, 355`).
- `attention_digest()` (:418) feeds the `background.attention` block of `/api/status`.
- `control_center_presentation_attention.js` draws the card and arbitrates `bgCue` across tabs (`claimCue`).
- `bgCue` in `control_center.html` remains the only sound emitter. A contradiction plays the existing failure cue.

**Tests:** `test_presentation_attention.py`, `_js.py`, `_browser.py`.

**Gaps**
- No distinct cue sound (an open Human decision).
- The path depends on the trace file plus a 1 Hz poll: there is no typed event channel.

## 7. UI execution path

**No "Tool Brain" or UI orchestrator exists anywhere in code or docs.** Grep for tool-brain, UI orchestrator, UI decision and action queue found nothing.

**How Presentation visuals reach the scene today**
- Speculative work → `PresentationSpeculativeService._stage` → `HiddenSceneStager` → `LedgeredSceneStager` (`presentation_runtime.py:287`) → `DisplaySceneStager` (`presentation_staging.py:63`) → `SceneDisplayTools.create_object(kind="artifact", visibility="hidden")` (`display_mcp.py:805`) → Core scene.
- `discard` uses `archive(object_ids=)` (`display_mcp.py:986`).
- **`reveal` is broken** (headline): it calls `self._tools.set_visibility`, which no longer exists. Revealing would now need `update_object(object_id, visibility="visible")`.
- The domain still names the old `scene_set_visibility` tool in comments (`domain/presentation_speculative.py:36,155,182`). That is harmless but stale.
- Staging is reachable only through explicit `REFRESH`, never from ambient work.
- Visual commands in general are executed by the main brain through its `jarvis-display` MCP tools (`scene_*`, `display_mcp.py:2373-2633`). There is no presentation-specific UI conductor and no timing logic.

**Windows on `main`**
- `SceneObjectKind.WINDOW` (`domain/scene.py:150`) and `Representation.WINDOW` exist.
- File-linked windows use `source_path` and `core/scene_file_watcher.py`.
- There is no prefab system on `main`.

**Branch `task/jarvis-scene-window-prefab-foundation` (not merged; ~11.2k lines across 69 files)**
- Prefab definition: `manifest.json` (`jarvis.prefab` v1, with `inputs.props` / `inputs.data` schemas, `events` classed `state`/`notify`, `sample`) plus `template.html`, `style.css`, `behavior.js` and an immutable `publication.json` per version.
- Base `jarvis.*` prefabs: window, document, table, checklist. Custom prefabs live in a data-root library (`FilePrefabLibrary`, `PrefabService`).
- Instantiation: the `prefab` block `{id, version, props, data}` on a **window** `ScenePayload`, going through the normal `SceneService.apply`. There is no separate instantiate op. Rendering is one sandboxed iframe per instance (`control_center_prefab_host.js`, `shim.js`, protocol `jv:1`).
- Agent tools: `prefab_search`, `prefab_get`, `prefab_validate`, `prefab_save`, `prefab_edit_base` (behind a witness gate), `prefab_events`, plus a `prefab` argument on `scene_create_object` / `scene_update_object` and prefab detail on `scene_get`.
- Core routes `/v1/prefabs*`. `notify` events reach the next turn via `BrainContext.prefab_events` but never wake the brain.
- It defines a "Presentation seam": stage hidden with `create_object(kind="window", visibility="hidden", prefab=…)`, reveal with `update_object(visibility="visible")`. Non-goals: no focus op, no presentation conductor, timing or speech policy. Its own Issue records the stager reveal bug.

## 8. Observability

**Canonical timeline**
- `jarvis/domain/conversation_events.py:97-125` defines types for user, brain, mouth, subagent, tool and system.
- Store, ingest, forwarder and timeline UI are documented in `docs/conversation-events.md`. The Voice forwarder is `runtime/conversation_event_forwarder.py`, built at `app.py:1163-1169`.

**Presentation decisions are not in it.**
- None of the presentation modules import the conversation-event layer. The only reference is an import allow-list in `core/presentation_attention.py:415-418`.
- Every decision goes only to `runtime/trace.jsonl` via `RuntimeJournal`:
  - `presentation.runtime.*` (including `diagnostics` every 30 s)
  - `presentation.working_set.*`, `presentation.tail.*`, `presentation.speculative.*`, `presentation.preparation.*`, `presentation.staging.*`, `presentation.attention.raised`, `presentation.addressed.*`
  - `voice.presentation.*`, `interaction.mode.*`
- **Consequence:** a reply withheld by the gate returns at `speech_scheduler.py:2371-2373` with no `mouth.*` event. The timeline shows `brain.speech.requested` with no outcome.
- Preparation sub-agents produce no `subagent.*` events.
- `PresentationCoordinator.stats()` is not exposed in `/api/status`.

## 9. Wiring

- **Composition root (Voice):** `_presentation_composition` (`app.py:730-836`) builds a `PresentationComposition` dataclass (`presentation_runtime.py:1349`, `build()` :1400).
- **Coordinator:** created at `app.py:1174-1229`. Composition failures are caught and SIMPLE still starts. `reclaim_orphans()` runs at Voice start (:1275).
- **Hand-off to the runtime:** passed to `PersistentVoiceRuntime(presentation=…, wakeword=presentation_wake)`.
- **Mode changes:** `observe_mode` → `_drain` → `apply` (:999-1048) build a fresh stack on every entry. On entry failure a visual alert is shown and SIMPLE resumes.
- **Enablement:** purely the effective mode, plus the continuous-architecture precondition. Named blockers (`presentation_transcription_unavailable`, `presentation_runner_unavailable`) are reported once at first entry.

**Dead or unwired pieces**
- The Core `V2App.presentation_working_set` has no producer.
- `to_brain_context()` has no transport consumer.
- `reveal` is broken in production.
- Grants that name `memory_search` / `scene_*` are stripped before reaching the CLI.
- `CODE_INSPECTION` and `DATA_ANALYSIS` are not reachable from any trigger.
- Board kind `presentation` drives no behaviour.

---

## 2026-09 close-out residual risks: still present?

| # | Risk | Status today |
|---|---|---|
| 1 | No workstation validation | **Still true.** `ACCEPTANCE_STATUS.md` checklist "Not executed"; all HV-PRES-* checks open. |
| 2 | `ASK_BRAIN` carries no projection | **Still true.** `to_brain_context` unused; `submit_brain_turn` has no context param (`protocol/client.py:293`). |
| 3 | Named visual command not matched to prepared material | **Still true.** `addressed_no_deictic` → `NOT_REQUESTED` (`core/presentation_addressed_turn.py:667-673`). |
| 4 | Up to 6 concurrent `claude` sub-agents unobserved | **Still true.** Pool 8, reserve 2, so 6 speculative, plus up to 2 explicit (8 total possible). |
| 5 | CLI acceptance of `--tools` unproven | **Still unproven** (`claude_local.py:294-302`, no real-CLI test). |
| 6 | Provenance eviction race (12-source ring) | **Still present** (`presentation_runtime.py:850-876`). |
| 7 | Ledger reclaims only at PRESENTATION entry | **Partly fixed.** `reclaim_orphans()` now also runs at Voice start (`app.py:1275`, `presentation_runtime.py:1236`). A lost or corrupt ledger still leaks; overflow beyond 16 ids is logged (`presentation_runtime.py:231-246`). |
| 8a | Issue 001: corrupt settings read as first launch | **Still present:** bare `except (OSError, json.JSONDecodeError): pass` and plain `utf-8`, so a BOM still breaks it (`control_center.py:2639-2647`). |
| 8b | Issue 002: dropped transcripts write `text[:300]` to the trace | **Still present** (`realtime_audio.py:4567-4568`, `:4623-4624`). |

**New since close-out:** the reveal regression from `df28431` described at the top. It is not in the close-out's list because it happened the next day.
