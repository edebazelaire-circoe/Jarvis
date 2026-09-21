# Voice architectures implementation index

Program: `tasks/jarvis_voice_architectures_handoff`.

| Ownership | Module |
|---|---|
| Neutral types, strict mode settings, model capability values | `jarvis/domain/voice_architecture.py` |
| Evidence-backed registry, architecture/role queries and readiness | `jarvis/runtime/voice_capabilities.py` |
| Version1 codec, compatibility projection, isolated persistence/query | `jarvis/runtime/voice_architecture_config.py` |
| Existing provider account model discovery | `jarvis/runtime/model_catalog.py` |
| Shared sourced comparison projection (read-only, not runtime authority) | `docs/catalog/INDEX.md`, `jarvis/runtime/catalog_view.py` |
| Regression and journal evidence | `tests/unit/test_voice_architecture_config.py` |
| Canonical commands, correlation, PCM, lifecycle, bounded context and diagnostics | `jarvis/domain/voice_frontend.py` |
| Typed canonical provider observations and local playback evidence | `jarvis/domain/voice_events.py` |
| Single-consumer lifecycle/audio/control protocol | `jarvis/ports/voice_frontend.py::VoiceFrontend` |
| Deterministic test-only frontend: `start`, `stop`, `inject`, `events` | `tests/fakes/voice_frontend.py::FakeVoiceFrontend` |
| Synthetic conversation, cancellation, evidence and contract regression | `tests/unit/test_voice_frontend_contract.py` |
| Recursive neutral-layer/Core import boundaries and test-only isolation | `tests/unit/test_v2_architecture.py` |
| Immutable canonical user, speech, task and version1 snapshot records | `jarvis/domain/voice_state.py` |
| Evidence reducer, candidate/task references, replay/retention, recent context | `jarvis/core/voice_state.py::VoiceConversationState` |
| State semantics, snapshot and Task05 integration obligations | `docs/state-model.md` |
| Real reducer/fake stream, strict snapshots and RuntimeJournal evidence | `tests/unit/test_voice_conversation_state.py` |
| Strict Core-safe event encoding; PCM prohibited | `jarvis/domain/voice_event_codec.py` |
| Core-owned ledger, context and confirmed-range projection coordination | `jarvis/core/voice_ledger.py::VoiceLedgerService` |
| Existing history writer with exact pending-range retry | `jarvis/core/v2_services.py::ConversationService.project_confirmed_voice_text` |
| Indexed projection/pending ranges and terminal ledger snapshots | `jarvis/adapters/sqlite_state.py`, neutral methods in `jarvis/ports/v2.py` |
| Authenticated canonical voice endpoints/client methods | `jarvis/protocol/server.py`, `jarvis/protocol/client.py` |
| Codec, multi-item identity, Core ingress/history, crash and retention regressions | `tests/unit/test_voice_event_codec.py`, `tests/unit/test_voice_ledger_protocol.py` |
| Provider-neutral WAIT/preamble decision | `jarvis/domain/reflex_policy.py` |
| Scheduler work attestation, deadlines, bounded correlation dedup | `jarvis/runtime/speech_scheduler.py` |
| Thread-safe preamble admission at native write boundary | `jarvis/runtime/output_admission.py`, `jarvis/runtime/realtime_audio.py` |
| Reserved local output and exact deferred cancellation | `jarvis/runtime/realtime_frontend_session.py`, `jarvis/adapters/openai_realtime_frontend.py`, `jarvis/adapters/openai_realtime.py` |
| Policy replay, close ownership and real façade/device races | `tests/unit/test_reflex_gate.py`, `tests/unit/test_reflex_frontend_cleanup.py`, `tests/integration/test_reflex_preamble_race.py` |
| Explicit source/dependency, exact bounded paragraph spans, chunk/outcome types | `jarvis/domain/speech_presentation.py`, `jarvis/domain/v2.py::SpeechRequest` |
| Existing scheduler freshness, bounded diagnostics, source reconciliation and generic first-write reservation | `jarvis/runtime/speech_scheduler.py`, `jarvis/ports/voice_frontend.py::ReservedSpeechOutput` |
| Advisory analysis request/value/result and strict version1 hint JSON | `jarvis/domain/front_brain_hints.py` |
| Optional analysis-only port | `jarvis/ports/front_brain.py::FrontBrainAnalyzer` |
| One expected hint, deterministic freshness/expiry/duplicate consumption | `jarvis/runtime/front_brain_hints.py::FrontBrainHintConsumer` |
| Permanent controlled sidecar fake and contract/authority/journal regressions | `tests/fakes/front_brain.py`, `tests/unit/test_front_brain_hints.py`, `tests/unit/test_front_brain_hint_review.py` |
| Durable available outcomes and current source allocation/selection | `jarvis/core/brain_outcomes.py`, `jarvis/core/brain_service.py`, `jarvis/adapters/sqlite_state.py` |
| Outcome/source HTTP queries and actual subscription acknowledgement barrier | `jarvis/protocol/server.py`, `jarvis/protocol/client.py` |
| Long backend result retained before presentation | `jarvis/adapters/control_center_brain.py`, `tests/unit/test_core_brain_outcomes.py` |
| Source-aware queue, stop/reconnect and actual multichunk/device races | `tests/unit/test_speech_presentation_scheduler.py`, `tests/unit/test_speech_scheduler_review_races.py`, `tests/integration/test_speech_presentation_race.py`, `tests/integration/test_speech_multichunk_composition.py` |

Task02 adds configuration only. Existing `voice_arch=legacy/continuous_brain` runtime remains authoritative. New profiles are not launchable until their canonical adapters and switch coordinator exist. `voice_architecture` is the new versioned namespace; compatibility projection and readiness remain explicit.

Observability contract: pure codec/registry functions do not log. Query boundary accepts existing `DiagnosticSink`/`RuntimeJournal`. Valid inspection emits `voice.config.validated` at info with schema version, architecture, compatibility flag and readiness code; schema rejection emits `voice.config.rejected` at warning with stable error code, then raises. Planned adapter readiness is an expected inspection result, not an error. Configuration inspection has no conversation/session correlation ID because it precedes session creation. No prompts, credentials, transcript or complete settings payload enters those events. No temporary probes or new logging subsystem.

Validation:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_voice_architecture_config.py tests/unit/test_settings_workbench.py tests/unit/test_settings_endpoints.py tests/unit/test_v2_brain_migration.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

2026-09-12: 174 passed in7.75s. Includes real `RuntimeJournal` output inspected with its supported `read_jsonl_tail` helper, normal/rejected levels/codes, no error-file creation and no credential leakage. Provider calls and acoustic behavior are outside this slice.

Task03 contract adds no production execution path, adapter migration, ledger writer, or runtime logging boundary. Domain/port values are pure; no journal output is fabricated. Stable error codes, operation identity, session/turn/task/speech/provider correlations and separate observation/provider timing establish the later runtime diagnostic contract. The fake is a permanent contract-testing component confined to `tests`, not a fallback and not evidence of provider access or acoustic quality. Exact API/event names and semantics live in handoff `docs/02-architecture-spec.md`.

Task03 validation:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_voice_frontend_contract.py tests/unit/test_v2_architecture.py tests/unit/test_voice_architecture_config.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

2026-09-12: 103 passed in1.38s. Covers full synthetic conversation, intended/generated/played separation, unavailable alignment, late/duplicate/out-of-order events, stop during start, cancelled start with full/default buffer bounds, repeated/uncertain Stop, iterator cancellation/aclose, explicit unsupported operations, bounded context/PCM and recursive import boundaries. Existing configuration tests also exercise real `RuntimeJournal` diagnostics through its supported helper. Task04 owns the canonical state reducer and explicit provisional replacement API; increasing delta revisions mean append progression, never reset. Task05 connects this contract to actual Realtime and playback runtime ownership.

Task04 adds `UserTranscriptRevised` for explicit provisional replacement, frozen state records, strict defensive snapshot serialization, and a synchronous Core reducer. Key methods: `bind_session`, `apply`, `queue_speech`, `update_task`, `recent_context`, `from_snapshot`; immutable access through `snapshot`, `active_tasks`, `speech_candidates`. It does not create a second durable history writer or execute tasks. Task05 must wire the production adapter/bridge/history projection and use a shared canonical sequence allocator when merging deferred playback with urgent input. See [state model](../state-model.md) for exact evidence and retention semantics.

Task04 validation:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_voice_conversation_state.py tests/unit/test_voice_frontend_contract.py tests/unit/test_voice_architecture_config.py tests/unit/test_v2_architecture.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

2026-09-12: 146 passed in1.66s (43 state tests). RuntimeJournal contract uses info for normal/stale/divergence outcomes, warning for invalid/capacity rejection, and error for an observed canonical frontend failure. Its real files are inspected through supported `read_jsonl_tail` in tests; no transcript or secret payload is logged. No temporary probes or provider/hardware calls. Full details and required Task05/17 replacement of legacy rehydration projection are in `docs/state-model.md`.

Task05 Core slice: `JarvisCoreApplication` now owns the canonical ledger; loopback ingress decodes bounded canonical batches, never PCM or client snapshots. Context uses committed/heard evidence for canonical sessions and preserves legacy behavior otherwise. The existing `ConversationService` appends confirmed suffix ranges with an exact durable pending range before writes, then advances an indexed SQLite cursor after both existing stores succeed. Terminal inactive ledger snapshots allow safe bounded registry eviction/reload. Root state documentation contains exact API schemas, recovery windows, ownership and device-proof limits.

Task05 Core validation:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_voice_ledger_protocol.py tests/unit/test_voice_event_codec.py tests/unit/test_voice_conversation_state.py tests/unit/test_voice_frontend_contract.py tests/unit/test_voice_architecture_config.py tests/unit/test_v2_architecture.py tests/integration/test_v2_protocol.py tests/integration/test_v2_brain_protocol.py tests/integration/test_v2_core_recovery.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

2026-09-12: 218 passed in3.86s. Includes strict codec/authenticated ingress, output-only and multi-item identity, source/work lineage without invented task identity, confirmed-history chronology, exact pending-range recovery before turn/archive/index writes with and without restart, stopped-ledger eviction/reload, failed persistence retention and real RuntimeJournal privacy/error evidence. Four deterministic SQLite cancellation cases cover blocked staging, repeated cancellation, successful/rolled-back native work and subsequent read/close; caller cancellation propagates only after connection ownership is safe. No provider or device playback claim follows from these tests.

Task06 adds a deliberate gate to the existing continuous-brain OpenAI reflex path. WAIT produces no speech; at most one preamble requires admitted input and the existing acknowledgement delay. The trigger is temporal: brain silence past that delay is enough, and no correlated `brain.work.started` is required (2026-09-18 — the attestation requirement had silenced the reflex entirely since 2026-09-13; `JARVIS_REFLEX_REQUIRE_WORK=1` restores it). An exact reserved output ID and thread-safe first-write token prevent useful-result/expiry races from playing an unstarted preamble. Provider cancellation remains outside the sole wire reader and is joined on close. BACKCHANNEL/DELEGATE remain reserved policy values; no executor, VAD or sidecar is added.

Task06 focused gate: 285 passed in13.53s, warnings as errors; parent independent gate567 passed in22.07s. The synthetic scheduler comparison reduces potential preambles from6 to3, retaining both long waits and the plain unattested request. Real RuntimeJournal checks validate privacy, correlations, latency and normal WAIT level. Device doubles prove admission/ordering, never acoustic completion. Exact command, controls, failure codes and evidence limits: tasks/jarvis_voice_architectures_handoff/docs/06-implementation-evidence.md; implemented rules: docs/05-reflex-optimization.md in that bundle.

Task07 canonical ownership: `domain/voice_playback.py` defines strict audio-part extents, complete provider inventory and immutable device proof values. `runtime/voice_playback_manifest.py` joins them through the actual `RealtimeFrontendSession.playback_manifest/observe_device_completion` API. The low-level/canonical adapters preserve item_id, content_index and output_index plus final transcript contradictions. The existing codec and state snapshot preserve optional generated-part identity, migrating old version1 identity to explicit unknown. `PlaybackCursor.content_index` carries exact part-relative truncate scope through the canonical cancellation control; no millisecond-to-word alignment is inferred.

The effective join is bounded to 128 outputs and 16 parts/output (neutral decode limit 128 is not a runtime support claim). A genuine matching drain can establish COMPLETE with unknown text; full generated transcript is promoted only after every audio part's final words are present and consistent. Explicit close/interruption invalidates pending joins. Core remains the sole history writer. `tests/unit/test_voice_playback_manifest.py` covers the strict join using labeled injected proof values; device accuracy and native ownership require the lead's real-wrapper tests. Canonical focused gate: 178 passed in 10.37 s, warnings as errors. See root state model and handoff `docs/evidence07-canonical.md` for migration, exact command and limits.

Task07 runtime/device ownership resides in `SoundDeviceRealtimeAudio`, the bridge's ordered completion fence and `PersistentVoiceRuntime` cleanup retention. Weak local candidates no longer duck speech. Checked output-only drain confirms exact written part extents; lazy start rechecks epochs and Task06 admission before writing. Native worker ownership survives timeout/cancellation, provider STOPPED remains distinct from device cleanup pending, and reactivation cannot reopen an owned device. Permanent tests use `tests/fakes/audio_device.py`, `test_device_playback_completion.py` (25 tests), real app composition and independent `test_voice_device_control_plane.py`. Final correction gate:64 passed in3.50s; earlier runtime/composition gate237 passed in7.08s. Real RuntimeJournal files verify normal/failed/pending transitions without PCM/transcript logging. Full commands, replay evidence and driver limitations: handoff `docs/07-runtime-device-evidence.md`; full release remains the parent gate.

Task08 extends the existing scheduler with explicit source/dependency freshness,
bounded inspectable candidates and exact paragraph chunks. It reuses the
Task06 atomic first-write token and Task07 ordered device fence. Results remain
durable Core outcomes independently of whether their presentation is current.
Source reconciliation starts only after the actual event subscription ACK;
Stop closes admission before awaiting cleanup. Unknown source/capability defers
for every scheduler instance. See [presentation contracts and evidence](../../tasks/jarvis_voice_architectures_handoff/docs/08-implementation-evidence.md)
and [Core outcome storage/query ownership](../../tasks/jarvis_voice_architectures_handoff/docs/08-core-outcomes.md).
Final focused presentation gate: 48 passed in 3.94 s, warnings as errors;
Task08 parent release accepted: **2294 passed, 4 skipped in242.19s**, all guards green.

Task09 supplies advisory contracts and a deterministic consumer, with no model
call, worker, queue, output capability or Core mutation. Provisional origin B
remains distinct from selected committed context A. Strict JSON, typed nullable
unknowns, actual consumption-time expiry, exact source/dependency checks and
same-request dedup keep hints optional. Task06/08 retain output authority.
Combined hint suites:128 passed in0.40s; parent regression gate284 passed in6.70s,
warnings as errors. The controlled fake and real RuntimeJournal tests prove
contract/cancellation/privacy behavior, not live model timing or quality.
See [Task09 schema, consumer, evidence and Task10 handoff](../../tasks/jarvis_voice_architectures_handoff/docs/09-hint-contract.md).

Task10 adds explicit direct conversation selection (`runtime/voice_composition.py`), role-separated confirmed context and versioned conversation/Luna prompts. `VoiceConversationRequest` selects admitted provider items without reinserting current text; `ConversationCandidate` uses the existing scheduler queue, Core source barrier and first-write token. Realtime/Front Brain share the same direct path; Front Brain adds the sole-reader fan-out and bounded optional `FrontBrainSidecar`/`LunaFrontBrainAnalyzer`. Accepted hints are diagnostic-only and own no speech/work authority. Core admission is durable, ordered by server evidence across restart/snapshot eviction, and independent of backend dispatch. Parent acceptance:428 focused tests and full release **2595 passed,4 skipped in294.40s**. See [Task10 parent review](../../tasks/jarvis_voice_architectures_handoff/docs/review-10.md), [implementation, budgets, RuntimeJournal and limits](../../tasks/jarvis_voice_architectures_handoff/docs/10-implementation-evidence.md) and [Core admission](../../tasks/jarvis_voice_architectures_handoff/docs/10-core-admission-evidence.md).

Task11 extends the existing Core JobService with atomic admitted-source jobs,
exact immutable context dependencies, typed status/progress/result/cancel and
independent CLI/process ownership. Transient storage failures and delayed cleanup
retain the owner/result; bounded Stop keeps reconciling until closure. Explicit
Simple/Front Brain expose a no-argument lineage-checked delegation tool. Only its
controller enqueues a source/job-bound acceptance ACK through the scheduler;
playback alone establishes hearing and job completion stays silent. Restricted
speculative execution at the Task11 acceptance boundary remained unavailable with a typed nonauthorizing advisory
reference. Parent acceptance: focused105, independent QA178 and full release
**2700 passed,4 skipped in320.97s**. See [Task11 parent review](../../tasks/jarvis_voice_architectures_handoff/docs/review-11.md), [Core contracts and fault replays](../../tasks/jarvis_voice_architectures_handoff/docs/11-core-back-brain-evidence.md) and [runtime/process/controller evidence](../../tasks/jarvis_voice_architectures_handoff/docs/11-runtime-implementation-evidence.md).

Task12 implementation adds `adapters/openai_live_frontend.py` behind the neutral
frontend port, `runtime/live_frontend_session.py` and `live_delegation.py`, and
`domain/live_prompt.py`. Explicit Duplex uses `openai/gpt-live-1`, client
delegation, one provider reader and canonical Core evidence. Restricted native
Claude now executes typed speculative Jobs from complete bounded provisional
dependencies; unsupported profiles remain durable unavailable. Existing
JobService/SQLite own acceptance, result retention, freshness and cancellation;
no fake committed turn or action authority is created.

Canonical flush and local input watermarks guard result injection. Thinking is
quiet; commentary requests speech; neither ACK nor generated transcript proves
heard words. Authorized barge-in suppresses playback for the entire Live
incarnation, while input and Jobs continue. An uncertain typed close retains
ownership and blocks idle/offline/reopen. Task13 still owns durable leases,
watchdogs, reaping and crash-safe termination.

Surface state in Duplex. The Live wire carries no end-of-output event and no
final user transcript, so `_legacy_events` used to emit only five legacy types
and the device bridge could reach `on_speaking` alone: the orb latched on
"JARVIS parle" for the rest of the session and never showed the brain at work.
Two facts now cross the façade instead. A provider delegation — the only usable
finality signal on this wire — is translated to `realtime.brain_pending`, which
sets the brain-working fact and publishes the colour derived from it. End of
speech is taken from local device quiescence
(`requires_local_quiescence_without_output_final`), already the project's
substitute for the missing output final: `_note_live_output_quiescent` rests the
surface exactly where `on_response_done` would. The visual return is best-effort
and never breaks playout. Evidence: `tests/integration/test_duplex_orb_states.py`
(real façade, bridge, runtime and on-disk signal bus).

Task12 parent targeted gate: **376 passed in12.42s**, warnings as errors.
Final connection-cancellation cleanup, `voice.live.usage` diagnostics and
dedicated smoke repair gate: **76 passed,3 skipped**. Final parent release:
**2765 passed,5 skipped in299.86s**, release verification passed; Task12 accepted.
Tests use controlled provider transport,
CLI streams and devices. The dedicated `JARVIS_LIVE_GPT_LIVE=1` smoke is present,
not executed; no model-inference, acoustic or billing claim. See [implementation and exact commands](../../tasks/jarvis_voice_architectures_handoff/docs/12-implementation-evidence.md),
[review](../../tasks/jarvis_voice_architectures_handoff/docs/review-12.md),
[wire contract and limits](../../tasks/jarvis_voice_architectures_handoff/docs/10-openai-api-notes.md)
and [lifecycle/playback evidence](../../tasks/jarvis_voice_architectures_handoff/docs/12d-lifecycle-playback-evidence.md).

Task14 Settings implementation now renders architecture, role/model and option
panels from `VoiceCapabilityRegistry`, with strict explicit-save validation and
atomic persistence. Legacy projections remain nonmigrating when unchanged;
readiness and account availability are separate. Settings changes do not replace
active voice sessions. See [Settings contract](../../tasks/jarvis_voice_architectures_handoff/docs/06-settings-and-prompts.md)
and [implementation evidence](../../tasks/jarvis_voice_architectures_handoff/docs/14-implementation-evidence.md).
Task14 parent acceptance/release remains pending.
