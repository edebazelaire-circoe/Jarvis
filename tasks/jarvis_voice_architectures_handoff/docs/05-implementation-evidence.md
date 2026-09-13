# Task05 implementation evidence

Implementation slice, 2026-09-12. Parent owns acceptance/release status.

## Production path

`app._run_voice_v2` → `PersistentVoiceRuntime.activate` → `RealtimeFrontendSession.connect` → `OpenAIRealtimeFrontend.start` → existing `OpenAIRealtimeSession.connect`. Only the canonical adapter consumes the low-level stream. Facade canonical subscription preserves bridge/scheduler envelopes and playout fences. Runtime binds Core ledger before bridge playback. Gemini stays separate; old model/settings precedence and `legacy` / `continuous_brain` execution remain authoritative.

START completes after matching `session.updated` instructions. Connect/update/ACK failure finishes the iterator. Concurrent STOP shares shielded cleanup; close timeout returns UNKNOWN. Cancellation during connection/update/ACK preserves injected shared HTTP ownership. Quiet context inserts data without `response.create`; runtime instruction update awaits matching acknowledgement. Bounded immutable tool JSON rejects malformed syntax, duplicate keys and non-finite numbers before dispatch. Existing Core tool permissions remain authoritative.

Local output ID, provider response/audio item/user input IDs and speech request ID remain distinct. Function items never become user turns or truncation targets. Multiple audio/transcript items aggregate under one response. Speech requests retain opaque source correlation and backend work references without inventing canonical tasks; source turns resolve only from admitted local input mappings.

## Evidence and admission

Dispatcher assigns one sequence at the merged receipt/playback boundary: queue256, batch32, at most20 control batches/second, bounded3s Core calls. PCM remains local. HTTP receives cumulative audio duration, never PCM/base64. Realtime usage deduplicates4096 response IDs; a missing usage field makes that cumulative field unknown. ASR usage remains in a separate bounded diagnostic cache and is never added to response token totals; full billing dimensions belong to Task18, display to Task16, and prompt registry to Task15.

Frontend emits input deltas, VAD/order and finals. Facade sends accepted input to Core only after the existing owner/address gate. Buffer limits:128 finals of8192 characters (at most4MiB UTF-8 text),128 opens,256 ancestry entries,128 source-turn mappings. No lists of deltas accumulate. Rejected input is discarded; >64 ignored inputs cannot fill Core provisional state. Original provider adjacency remains `previous_provider_input_id`; application order skips rejected predecessors. Late final A after B does not rewind active turn. Pre-admission speculative access remains Task10.

Provider transcript is generated evidence. Device playback gives only an output-matched lower bound; another device epoch cannot credit an old output. No duration ratio confirms words. Natural `response.done` produces UNKNOWN. Zero PCM/tool-only output never enters assistant heard history. Task07 must establish actual device drain confirmation before17/20; controlled tests here do not validate hardware.

Core owns reducer and confirmed assistant-history projection. User persistence remains Brain/legacy-owned. Observation transport failure stops frontend. After confirmed close, control-only snapshot/reconciliation submits STOPPING→STOPPED for the same session without replaying missing text. If Core stays unavailable, runtime retains pending cleanup and retries before activation. It never forcibly replaces a newer session.

## Validation / observability contract

New tests: `tests/unit/test_realtime_frontend_adapter.py` and `tests/unit/test_realtime_frontend_pipeline.py`. Pipeline uses production low-level normalization, frontend, dispatcher, ledger, SQLite and JSONL; wire/client transport is controlled. Parent-owned `tests/integration/test_voice_production_composition.py` also exercises actual app factory/runtime and authenticated Core HTTP, in legacy/full and continuous/mini. Core codec/projection/crash evidence is recorded by its agent.

Focused integration gate:286 passed in9.66s. After adding verified pre-ACK authentication/rate-limit classification, adapter gate20 passed in0.50s. Global collection:2116 tests collected in1.81s with warnings treated as errors. Parent release testing remains a separate gate.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_realtime_frontend_adapter.py tests/unit/test_realtime_frontend_pipeline.py tests/integration/test_voice_production_composition.py tests/unit/test_realtime_output_control.py tests/unit/test_realtime_audio_lifecycle.py tests/unit/test_v2_speech_scheduler.py tests/unit/test_v2_brain_migration.py tests/unit/test_owner_input_gate.py tests/unit/test_owner_barge_in.py tests/unit/test_voice_frontend_contract.py tests/unit/test_voice_conversation_state.py tests/unit/test_v2_architecture.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

Project observability is existing `RuntimeJournal` / `DiagnosticSink`; Task01 found no installed project `observability.cli`/LogBroker. Core state emits structured observations/divergence/error diagnostics with session/turn/speech/provider identity. `voice.observation_failed` reports bounded ingress failure with stable code, IDs and exception type only. `voice.evidence_cleanup_pending` reports reconciliation failure without provider payloads. Frontend errors are typed/sanitized. Tests inspect outcomes and projection; no live provider/device or production-log validation is claimed. No temporary probes remain. Facade removal is specified in `docs/legacy/realtime-frontend-facade.md`.
