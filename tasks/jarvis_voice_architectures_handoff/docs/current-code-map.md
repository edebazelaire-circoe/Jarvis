# Current voice implementation — Task 01

## Task05 ownership update (2026-09-12)

The inventory below is the pre-migration baseline. OpenAI production composition now follows `app._run_voice_v2` → `PersistentVoiceRuntime` → `runtime/realtime_frontend_session.py` → `adapters/openai_realtime_frontend.py` → existing `OpenAIRealtimeSession`. The canonical frontend owns the sole wire reader. The temporary facade preserves existing bridge/audio fences and legacy controls; Gemini remains separate.

`runtime/voice_observations.py` sequences canonical receipt and playback evidence and sends bounded non-PCM batches to Core's `VoiceLedgerService`. Core owns conversation state and confirmed assistant history. Bridge/scheduler no longer write assistant history for this migrated path. Admission remains behind owner/address gates; generated text is never heard evidence. Device playback is conservative PARTIAL/UNKNOWN pending Task07's real drain proof. See `05-implementation-evidence.md` and root `docs/legacy/realtime-frontend-facade.md` for validation and removal criteria.

Inventory date: 2026-09-12. Repository: `C:/Projects/jarvis/jarvis`, branch `main`, baseline HEAD `2ced8dd`. Tracked tree clean at task entry; only this new handoff directory was untracked. This slice changes documentation only. Paths below are repository-relative; symbols are stable navigation anchors.

## Critical migration findings

1. Existing `VoiceArchitecture` means `legacy | continuous_brain`, not `simple | front_brain | duplex`. `legacy` closes after a response; `continuous_brain` keeps listening but forces the voice model into reflex/verbatim speech and submits every accepted complete turn to Core. Neither is the new Simple specification. Preserve old selection as explicit compatibility metadata until a new runtime selection is wired; do not silently rename `continuous_brain` to Simple.
2. Current heard-history implementation deliberately trusts intended brain text. `realtime_audio.py::_handle_event` traces provider assistant transcripts carrying `speech_id` but does not persist them; `speech_scheduler.py::_persist` writes `SpeechRequest.text`. Interrupted output retains the entire intended text plus `delivery=partial` and `played_ms`. New decision 05 requires changing this old contract and its tests, not adding a second competing history writer.
3. Backend ingress is already asynchronous in Core, but the actual CLI conversation serializes asks (`ClaudeLocalAgent._ask_lock`, `CodexLocalAgent._turn_lock`). An `asyncio.create_task` around the same CLI ask is insufficient to guarantee an available conversational brain. Existing background-agent dispatch must remain independent of that serialized turn.
4. Gemini has no configured or production hard-coded default model. Its live candidates come from Google's declared `bidiGenerateContent` method. A fixture named `gemini-live-2.5-flash` is test data, not verified account availability. Current adapter lacks semantic output controls and is explicitly refused in `continuous_brain`.
5. Existing active timeout permits `0` (never time out). It is not a billable Live watchdog. Do not reuse the saved `0` value as a default for GPT-Live safety.
6. Existing UI label `ChatGPT Live (OpenAI Realtime)` names the Realtime stack. This is not a GPT-Live adapter; update terminology when the new Duplex option lands.

## Entry points, ownership, lifetime

| Component | File and symbols | Responsibility |
|---|---|---|
| Composition | `jarvis/app.py::_run_voice_v2`, `_run_core_v2`, `_brain_backend_from_env`, `_run_control_center_v2` | Loads environment then persisted overrides, constructs adapters/Core client/owner capture/runtime; finalizer cancels timeout task and closes runtime. |
| Voice lifetime | `jarvis/runtime/voice_v2.py::PersistentVoiceRuntime.activate`, `mute`, `close`, `check_timeout`, `UsefulActivityTracker` | Creates/resumes Core conversation, gets context, opens provider, starts audio bridge and continuous scheduler. Owns teardown and wake suspension/resumption. `BACKGROUND/CONNECTING/ACTIVE/ERROR` are existing states, distinct from required Live billing states. |
| Audio I/O | `jarvis/runtime/realtime_audio.py::SoundDeviceRealtimeAudio` | SoundDevice capture/playout, PCM queues, playback identity and cursor, written-vs-played duration, stop/abort and cleanup. |
| Event bridge | `jarvis/runtime/realtime_audio.py::RealtimeConversationBridge` | Provider reader, ordered control consumer and playout worker; transcript admission, Core ingress, legacy tools, output/interruption callbacks. |
| Provider ports | `jarvis/ports/v2.py::RealtimeSession`, `RealtimeOutputControl`, `BrainBackend`, `ContextAwareBrainBackend`, `DiagnosticSink` | Existing neutral contracts. Output controls are optional and structurally checked. No canonical `VoiceFrontend` contract yet. |
| Domain | `jarvis/domain/v2.py` | `ProtocolEnvelope`, `ConversationTurn`, `SpeechRequest`, `PlaybackCursor`, `BrainTurnInput`, `BrainWorkingState`, `BrainEvent`, speech priority/provenance. |
| Core runtime | `jarvis/core/v2_app.py`, `jarvis/core/v2_services.py` | Core composition, `ConversationService`, `CoreEventBus`, durable `JobService`, scheduling and notifications. |
| Core brain | `jarvis/core/brain_service.py::BrainOrchestrator.submit`, `_run_turn`, `_dispatch_backend_event`, `_emit_speech`, `rehydrate` | Deduplicated accepted turns; per-turn task ownership; revisions/work state; backend facts/events to speech requests. |
| Work state | `jarvis/core/work_state.py::WorkStateStore`, `jarvis/core/brain_context.py::BrainContextBuilder`, `jarvis/domain/work_state.py` | Bounded work snapshots, lineage, status/progress, context selection. Reuse for background jobs. |
| Protocol | `jarvis/protocol/client.py::LocalCoreClient`, `jarvis/protocol/server.py` | Loopback authenticated Core calls and `/v1/events` stream; submit brain turns, append history, context, work and job APIs. |
| Backend adapter | `jarvis/adapters/control_center_brain.py::ControlCenterBrainBackend` | Calls Control Center agent API, streams notices/results into typed brain events; provider details stay outside Core. |
| Legacy backend | `jarvis/runtime/claude_gateway.py::ClaudeGateway`, `realtime_audio.py::_call_claude` | Voice-owned legacy delegation through Control Center; deliberately absent in continuous mode. |
| Local agents | `jarvis/runtime/claude_local.py::ClaudeLocalAgent`, `jarvis/runtime/codex_local.py::CodexLocalAgent` | Persistent CLI sessions and serialized turn execution. |
| Agent dispatch | `jarvis/runtime/agent_tasks.py::AgentTaskTracker`, `agent_routing.py`, `routing_hook.py`, `work_brief.py` | Task/subagent events, model/profile routing hook, work projection and context formatting. |

## One turn, end to end

1. Wake/keyboard activates `PersistentVoiceRuntime`; `core.create_conversation` / `core.context` supplies durable recent context. Provider factory is selected from saved stack plus old architecture. SoloOwner enforced activation checks happen before opening provider/micro.
2. `SoundDeviceRealtimeAudio.pump_input` sends PCM through `RealtimeSession.send_audio`. In continuous mode, `CaptureProcessor` can remove speaker echo and enforce owner admission before provider upload.
3. Provider adapters translate wire messages into `ProtocolEnvelope` events. Bridge `_read_provider` dispatches independently of `_play_out`, preventing microphone/control events from waiting for speaker writes.
4. OpenAI user deltas become `realtime.transcript_delta`; bridge currently treats these as tentative activity, not committed backend instructions. Complete `realtime.transcript` enters `_handle_transcript`: admission, echo/noise filter, addressing, punctuation-tolerant mute.
5. Continuous path `_submit_brain_turn` sends complete text plus deterministic correlation/provider item IDs, addressing and interrupted speech ID. Core returns acceptance, persists/deduplicates and runs backend independently. Legacy path appends the user turn; model's tool calls route through `realtime_tools.py` and `ClaudeGateway`.
6. `BrainOrchestrator` publishes `brain.*` events including speech requests. `SpeechScheduler._consume_core_events` filters by conversation, tracks revisions/work IDs, queues priority/TTL candidates, suppresses stale transient work, and waits for user silence/output idle. Reflex generation is delayed/optional and separate from final speech.
7. OpenAI `speak` makes one `response.create` with instruction plus opaque output/speech metadata, without fabricating a user turn. It asks for exact reading. `speak_reflex` makes an independently identified response with no speech ID.
8. Provider audio runs through bridge playout; `output_started/audio/audio_done/response_done` notify scheduler. `_barge_in` stops local playback immediately, records cursor, then cancels/truncates provider output. Late audio from canceled output is discarded.
9. Scheduler completes only on explicit completed status; a disappeared output without completion is not assumed spoken. However its stored content is still intended text. Mute closes voice resources but does not cancel accepted Core work.

## Spoken evidence: exact current limits

| Evidence | Existing consumer | Meaning and limit |
|---|---|---|
| OpenAI `response.*audio_transcript.done` | Adapter → `realtime.assistant_transcript` with output/response/item/speech identity | Provider-generated text, not acoustic proof of playback. Assistant delta wire events are not currently translated. |
| Provider transcript with `speech_id` | Bridge `_handle_event` around line 2799 | Trace-only `voice.assistant`; scheduler separately archives intended text. This is the main new ledger integration point. |
| Provider transcript without `speech_id` | Same bridge branch | Archived directly as assistant, tagged `surface.reflex` in continuous mode. It lacks a uniform playback-confirmed heard ledger; zero-played output must not become heard merely because text arrived. |
| `PlaybackCursor.played_ms` | Audio `playback_cursor`, bridge `_barge_in`, scheduler `note_interruption` | Per-item estimated played audio after stream latency, bounded by written PCM. It does not align words with timestamps or prove acoustic perception. |
| Interrupted intended speech | Scheduler `_persist` | Full request text retained with partial metadata. Existing Core distinguishes partial delivery from complete public facts; do not infer which words were heard by proportional string slicing. |
| Gemini output text | `_translate_server_content`, `_flush_output_transcript` | Aggregated provider transcript/text at turn complete, no output/speech ID or word timing. Native interrupted flag emits audio-done, not a precise heard span. |

New ledger should separate intended text, provider-generated transcript, playback extent, and heard confidence/source. Unknown partial words remain unknown; an append/send acknowledgement is never heard proof. Reuse one authoritative persistence path and retain correlation/conversation/output/speech identity.

## Existing providers and models

| Stack/provider | Exact identifiers and capability facts from code |
|---|---|
| `openai_realtime` / credential `openai` | `OpenAIRealtimeSession` in `jarvis/adapters/openai_realtime.py`; input/output PCM 24 kHz. Default legacy model `gpt-realtime-2.1`; continuous recommendation `gpt-realtime-2.1-mini`; transcription default `gpt-4o-mini-transcribe`. Supports audio in/out, user transcript deltas, semantic/server VAD, function tools, speak/reflex/cancel/truncate. Existing event adapter does not expose usage events or assistant transcript deltas. `send_context` injects a user message AND triggers response; it is not quiet-context injection. No public runtime prompt-update operation. |
| `gemini_live` / credential `google` | `GeminiLiveSession` in `jarvis/adapters/gemini_live.py`; BidiGenerateContent endpoint; input PCM16 kHz/output24 kHz. No fixed/default model identifier. Model supplied from real catalog or explicit saved setting. Supports audio in/out, optional accumulated input/output transcription, tools, VAD sensitivity, native interrupted indication. Does not implement `RealtimeOutputControl`; no emitted transcript deltas, usage, or output lineage. `send_context` creates completed user turn; not quiet context. |
| Model discovery | `jarvis/runtime/model_catalog.py::ModelCatalog`; 600s cache, 15s request timeout, provider API calls. OpenAI role classification is name-based (`realtime` substring etc.); new GPT-Live would currently be classified as text via `gpt-`. Google requires `bidiGenerateContent` for realtime. `coerce` checks model strings but cannot prove remote compatibility. Registry must distinguish account-discovered models from locally implemented capability contracts. |

Exact static voices: OpenAI `cedar, ash, verse, ballad, echo, sage, alloy, marin, coral, shimmer`; Gemini `Puck, Charon, Kore, Fenrir, Aoede, Leda, Orus, Zephyr`. These are code declarations, not a fresh provider availability assertion. No GPT-Live or Luna adapter is present at baseline.

## Settings persistence and UI

`jarvis/runtime/control_center.py::_settings/_write_settings/_settings_payload/save_settings/_apply_voice` reads/writes `runtime/control-center-settings.json` atomically using temporary file + replacement. GET/POST `/api/settings`; `/api/models` uses catalog; credentials have separate routes and masked projection. UI is `jarvis/runtime/control_center.html` (Settings state `SET`, voice draft, `data-voice-arch`, generated stack fields). Work panel is `control_center_work.js`.

`voice_stack.py::VoiceStackSpec/Field/describe_stacks/coerce/settings_for/store_for` is the shared schema for UI and launcher. Nested persistence: `voice_stack_settings[stack_id][field]`. Resolution: declared defaults → old flat keys → nested saved values. Legacy flat `voice_turn_mode→turn_mode`, `realtime_voice→openai_realtime.voice` remain mirrored; preserve round trips and inactive-stack settings.

Old architecture resolution: nonempty saved `voice_arch` → `JARVIS_VOICE_ARCH` → `default_voice_arch()`. Default stays `legacy` because `brain_calendar_access_unverified` and `brain_reminder_access_unverified` block default promotion. Environment `OPENAI_REALTIME_MODEL` overrides architecture recommendation, then nonempty per-stack saved `model` overrides it at construction. Conversation authorization is independent of architecture and turn mode.

| Setting | Default / relevant bounds |
|---|---|
| `voice_stack` | `openai_realtime`; UI `_settings` also accepts `JARVIS_VOICE_STACK`. |
| `voice_arch` | Empty means environment/calculated old default; enum `legacy/continuous_brain`. |
| `active_timeout_s` / `JARVIS_ACTIVE_TIMEOUT_S` | Environment default90s; 0 disables, otherwise at least5s; useful activity only. |
| `JARVIS_RECENT_TURN_LIMIT` |12, range1–100. |
| OpenAI `model`, `voice`, `turn_mode` | Empty, `cedar`, `auto`; auto/manual. |
| OpenAI `transcription_model/language` | `gpt-4o-mini-transcribe` / `fr`; empty transcription can disable it. |
| OpenAI `noise_reduction`, `echo_cancellation`, `ack_delay_ms` | `far_field`, true,1200ms (0 disables; max10000). Noise choices `far_field/near_field/off`. |
| OpenAI `vad_type/eagerness/threshold` | `server_vad` / `auto` /0.55; semantic eagerness auto/low/medium/high. |
| Both `vad_prefix_padding_ms/silence_duration_ms` |300 /1500; ranges0–2000 /100–4000. |
| Gemini `model/voice/turn_mode` | Empty (startup refused until chosen) /`Puck` /`auto`. |
| Gemini `input_transcription/output_transcription` | true/true. |
| Gemini `vad_start_sensitivity/vad_end_sensitivity` | `LOW/LOW`; choices LOW/HIGH. |
| `conversation_mode/speaker_verification` | `open_room/off`; `solo_owner` defaults enforcement. See `domain/speaker.py`, `v2_config.parse_conversation_authorization`. |
| Owner tuning | `owner_buffer_ms` from `domain/speaker.py` (2500ms); `owner_threshold` unset/calibrated; `owner_evidence_ms`1500 (500–4000); `owner_short_evidence_ms`600 (0 disables, otherwise ≥300 and < evidence); `owner_short_margin`0.1 (0–0.3). Profile path is constrained under runtime; biometric content not inventoried. |

Whitelisted saved snapshot on this machine (not environment or active-process proof): `voice_arch=continuous_brain`, stack OpenAI, voice cedar, auto turns, `active_timeout_s="0"`; nested OpenAI model empty and transcription `gpt-4o-transcribe`; Gemini model empty, voice Puck, auto. No secrets or profile data read into this document. Do not infer currently running provider model from blank saved model without environment resolution.

## Prompt inventory

| Layer | Existing construction |
|---|---|
| Voice base | `openai_realtime.py::JARVIS_PERSONA`. |
| Voice operating policy | `OPERATING_RULES` vs `CONTINUOUS_BRAIN_OPERATING_RULES`, selected by `operating_rules_for`; combined with persona and recent `context.turns` by `build_session_instructions`. Continuous policy closes tools and forbids substantive voice reasoning. |
| Gemini base/policy | `GeminiLiveSession.connect` imports/reuses OpenAI persona and legacy operating rules; appends recent turns into systemInstruction. Provider-specific split is not clean yet. |
| Per-response exact speech | `VERBATIM_SPEECH_INSTRUCTION.format(text=...)` in OpenAI `speak`; changes response instructions, not a stored user setting. |
| Per-response reflex | `REFLEX_INSTRUCTION`, `build_reflex_instruction` with transcript and recent phrases to avoid. |
| Tool contracts | `jarvis/runtime/realtime_tools.py::REALTIME_TOOLS`, `tools_for`; descriptions participate in model behavior. Continuous tool list is empty. |
| Legacy contextual result | Both adapters' `send_context`; response-triggering user message. `send_tool_result` sends tool results and requests response. Must not be relabeled quiet context. |
| Claude system | `jarvis/runtime/claude_local.py::BRAIN_SYSTEM_PROMPT` (background delegation + oral format), `routing_hook.py::PROFILE_RULE`; CLI `--append-system-prompt`. CLI resumed sessions can retain old system-prompt snapshot, so editing a constant does not guarantee a live session changed. |
| Backend per-turn | `control_center.py::build_agent_brief`, `_BRIEF_STATE_FIELDS`, `BRIEF_DELEGATION_REMINDER`, `work_brief.py::render_work_brief`; includes addressing uncertainty/sentinel, state, work and user request. Used by agent ask endpoint for Claude or Codex. |
| Codex backend | `codex_local.py::_turn_command/_run_turn` sends stdin text to CLI `codex exec [resume session_id] --json`; no app-server transport or equivalent explicit Jarvis `BRAIN_SYSTEM_PROMPT` injection found. CLI/repository/provider instructions may apply independently. |

There is no unified prompt registry, editable voice prompt persistence, effective prompt preview or prompt revision identifier. Existing code constants and dynamic context must become explicit registry layers without overwriting user settings or claiming provider-hidden instructions are exposed. Older non-v2 pipeline (`runtime/voice.py`, `runtime/factory.py`, `config.py`, `OPENAI_TTS_INSTRUCTIONS`) also exists; it is a separate compatibility entrypoint, not the active v2 voice factory.

## VAD, interruption, SoloOwner, diagnostics

- `openai_realtime.py::build_turn_detection`: continuous mode forces `create_response=False`, `interrupt_response=False`; Jarvis decides after admitted transcript. Default server VAD remains explicit above.
- `audio/duplex.py::CaptureProcessor`, `adapters/webrtc_echo.py`: cleaned microphone, near-end/echo guard; optional AEC. `realtime_audio.py::_on_near_end/_on_barge_timeout/_barge_in`: local candidate ducks output, confirmed source cancels; restore on timeout. Provider confirmation and local candidate are distinct.
- `audio/speaker_shadow.py`, `audio/owner_verifier.py`, `adapters/sherpa_speaker_embedder.py`, `runtime/owner_voice.py`, `domain/speaker.py`: verification evidence and owner state. Owner-enforced bridge gates capture/replay and interruption. `PersistentVoiceRuntime._authorization_refusal/authorization_lost` fail closed. New frontend/VAD code must preserve this pre-upload boundary; provider VAD alone cannot replace owner evidence.
- `runtime/turn_filters.py`: echo, low-information transcription filters. Addressing classifier lives in realtime_audio. Neither is a complete new WAIT/preamble policy yet.
- `runtime/journal.py::RuntimeJournal.emit` writes structured `ts/kind/level/message/data` to trace.jsonl and errors to errors.jsonl. `DiagnosticSink` is the neutral port. Existing supported inspection is Control Center `/api/trace`, `/api/errors`, and `read_jsonl_tail`; there is no installed project LogBroker/observability CLI to invoke. Do not introduce another logging system for this task.
- `core/latency.py`, brain service and bridge/scheduler emit correlated latency and milestones. Useful families: `voice.stack`, `voice.active`, `voice.brain_turn_submitted`, `voice.assistant`, `voice.barge_in*`, `voice.input.*`, `brain.*`, speech scheduler constants (including `speech_output_stalled`). New benchmark metrics can extend these with architecture/model/prompt IDs. Raw transcript messages already exist in current traces; new diagnostic defaults should not copy source transcripts unnecessarily.

## Baseline validation and next-slice tests

Executed from repository root, Python `.venv/Scripts/python.exe`, no provider calls or hardware session:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_realtime_output_control.py tests/unit/test_realtime_audio_lifecycle.py tests/unit/test_gemini_live.py tests/unit/test_v2_voice_toggle.py tests/unit/test_v2_speech_scheduler.py tests/unit/test_v2_brain_migration.py tests/unit/test_settings_endpoints.py tests/unit/test_settings_workbench.py tests/unit/test_owner_input_gate.py tests/unit/test_owner_barge_in.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

Result: **300 passed in 9.78s**, exit0. No pre-existing failures observed in this focused scope. Documentation-only slice adds no behavior tests. This is not a full-suite, acoustic or live-provider benchmark.

Additional existing validation entrypoints by concern:

- Config/UI: `tests/unit/test_v2_brain_migration.py`, `test_settings_endpoints.py`, `test_settings_workbench.py`, `test_routing_settings_screen.py`, `test_agent_routing_settings.py`, `test_config.py`.
- Provider/lifetime: `test_realtime_output_control.py`, `test_gemini_live.py`, `test_realtime_audio_lifecycle.py`, `test_v2_voice_toggle.py`, `test_v2_voice_activity.py`; `tests/integration/test_voice_runtime.py`.
- Heard/speech/turns: `test_v2_speech_scheduler.py`, `test_v2_barge_in.py`, `test_v2_brain_contracts.py`, `test_v2_brain_orchestrator.py`, `test_voice_to_claude.py`.
- Authorization/acoustics: `test_owner_input_gate.py`, `test_owner_barge_in.py`, `test_owner_voice.py`, `test_owner_replay.py`, `test_solo_owner_acceptance.py`, `test_voice_duplex.py`; hardware acceptance remains separate.
- Work/delegation: `test_brain_delegation.py`, `test_brain_work_context.py`, `test_agent_tasks.py`, `test_v2_work_progress.py`; integration `test_brain_work_context_protocol.py`, `test_work_state_protocol.py`.
- Release: `scripts/verify_release.py` combines full pytest and structural/privacy gates. Explicit asyncio fixture scope avoids pytest startup deprecation when warnings are errors.

Task01 acceptance: major components mapped; exact declared model IDs and dynamic Gemini constraint recorded; config and persistence/migration risks recorded; focused baseline passes. Remaining uncertainty concerns provider availability/semantics and real acoustic measurements, not missing implementation locations.
