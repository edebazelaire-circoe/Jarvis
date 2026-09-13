# Task10 — direct conversation and optional Luna analysis

Implementation delivered for parent review; only the orchestrator accepts the slice. No provider inference, microphone or hardware test was performed.

## Composition and authority

`runtime/voice_composition.py` resolves the existing versioned selection. Saved compatibility metadata retains legacy or continuous_brain execution. Explicit Simple and Front Brain use persistent capture, local owner/echo/addressing guards, automatic Realtime segmentation with automatic responses/interruptions disabled, and direct conversational instructions. Explicit Duplex is rejected before credential/session construction. An unrelated saved Gemini stack cannot override an explicit OpenAI model. Realtime and Luna are implemented READY entries; account availability remains UNKNOWN, Google remains legacy-only and Live remains planned.

`app.py` chooses the exact conversational model and optional independent analysis model. The compatibility Claude gateway remains available only to compatibility legacy. New modes have no execution tools and never submit substantive turns to the backend. UNCERTAIN input waits; Luna confidence cannot promote it. Task11 owns later work dispatch from already admitted Core sources.

Core admission is documented separately in [10-core-admission-evidence.md](10-core-admission-evidence.md). The facade admits and flushes the exact canonical committed record before the typed HTTP call. Core derives its own stable correlation and returns origin source; canonical voice turn ID, Core turn ID and source correlation remain distinct. `brain.source.changed` and the existing subscription/snapshot barrier supply actual current source and invalidations. An acceptance alone cannot overwrite a newer current intent.

## Direct output contract

`VoiceConversationRequest(input_item_ids: tuple[str,...])` permits one to sixteen unique opaque references. Optional `VoiceConversationControl.request_conversation(request, *, operation: VoiceOperation)` reserves/correlates the local output before awaiting the provider. The facade exposes `request_conversation(input_item_ids, *, source, output_id)`; `SpeechScheduler.request_conversation(*, input_item_ids, source)` queues a distinct `ConversationCandidate` in the existing delivery queue.

There is no fabricated SpeechRequest text, backend outcome or Job. The existing scheduler owns serialization, source freshness, pre-write OutputAdmission, cancellation and output fences. A candidate with a future source waits for the exact feed without spinning; older source is retired. Stop invalidates the reservation. A provider response arriving after invalidation is canceled by exact response ID and cannot pass the device's first-write token.

Realtime sends `response.create.response.input` with `item_reference` entries and omits `conversation` (normal default conversation). No current transcript is reinserted. The bounded ordered whitelist includes admitted user inputs, assistant items whose complete text has actual matching device proof, and initial confirmed context. Rejected provider items and unknown/partial assistant tails are excluded. Input selection therefore remains stable even if another provider item arrives before send.

Initial context uses `VoiceFrontendConfig.initial_context` with USER/ASSISTANT roles, unique local item IDs and no response trigger. Persona/rules are the only session instructions in explicit modes. A historical user instruction injection stays a user data message. Legacy assistant history is omitted until canonical heard evidence exists. Context selection retains at most eight messages/8192 characters; response references retain at most sixteen IDs. Compatibility prompt construction stays unchanged.

## Luna and ownership

`adapters/openai_front_brain.py::LunaFrontBrainAnalyzer` implements the Task09 analyzer port using injected HTTPX or a client owned for one call. It sends nonstreaming Responses with exact model `gpt-5.6-luna`, configured reasoning effort (initial low), `store:false`, no tools/continuation and strict `text.format.json_schema` derived from Task09 enums. The application envelope never comes from model JSON. Refusal dominates adjacent JSON; incomplete/error/ambiguous/executable output cannot become an available hint. Duplicate keys, nonfinite numbers (including exponent overflow), invalid/oversized UTF-8 and confidence type errors are rejected. URLs require HTTPS or exact HTTP loopback. Decompressed response accumulation is bounded before decoding.

`runtime/front_brain_sidecar.py::FrontBrainSidecar` owns one worker, one in-flight analyze task and one replaceable latest pending request. The sole facade event reader calls synchronous `observe(event)`; there is no second provider consumer. The bridge grants session/item-specific `allow_item` only after local provenance/open-room admission, and cleanup distinguishes admitted records from actual rejection. Known rejection revokes permission and late results. An earlier permitted provisional request cannot be retroactively unsent when later addressing rejects it.

Final transcript arrival cancels speculation even when Core admission is still pending. A final is dispatched only after committed input, admitted origin, complete Core projection and exact current source agree. `update_source` re-evaluates the held final when the feed catches up. A newer current source rejects an older final. Before admission, provisional B may have unknown origin and committed context A. Task09 checks actual consumption-time expiry, exact input/source/config/admission and revoked dependencies again.

Accepted hints are **diagnostic advisory observations only in Task10**. No WAIT delays a response, no PREAMBLE attests work, no DELEGATE executes, no suggested speech text enters the conversation. Direct response scheduling never awaits Luna. The sidecar owns no Core, scheduler, audio or backend handles. Stop revokes before cancellation and joins its task; the real HTTP adapter propagates cancellation and closes only owned clients. Remote processing/cost cancellation is not claimed.

## Defaults, budgets and prompt hooks

| Setting | Effective default / bound |
|---|---|
| Analysis prompt | `domain/front_brain_prompt.py`, `jarvis.front-brain.v1` |
| Conversation rules | `domain/conversation_prompt.py`, `jarvis.conversation.v1` |
| Debounce / minimum dispatch interval | 150 ms / 300 ms |
| Request deadline / transport ceiling | 2 seconds / 2 seconds; smaller remaining deadline wins |
| Calls per provider input turn | 3 total, at most 2 provisional; final allowance reserved |
| Selected input / aggregate text | 8192 / 16384 characters, Task09 bounds |
| Serialized request / response | 131072 / 65536 UTF-8 bytes |
| Output cap | 512 tokens initially; adapter configurable 64–4096, including reasoning |
| Fixed reservation | 135168 local units per dispatched call; 405504 per turn |
| Retention | 64 item identities; saturation disables speculation for that incarnation, direct conversation continues |

The fixed reservation conservatively charges the maximum request byte budget plus maximum allowed output-token cap before dispatch. It is an accounting guard, **not a tokenizer measurement or a guaranteed provider input-token count**. No characters/4 estimate or zero-cost assumption is used. Reservations are never refunded after failure, timeout or absent usage. Valid provider input/output/total/cached/reasoning counts are observed separately; subsets are not added twice. Missing/malformed usage remains unknown. Task18 owns actual cost aggregation.

`FrontBrainVoiceConfig` retains exact model, reasoning and speculative flag. Sidecar timing/budget dataclass, adapter limits, versioned prompt constants and composition fingerprint are the hooks for Task15; no UI or hot switching is implemented here. Analyzer construction is lazy with respect to HTTP resources, so a failed factory attachment has no created client/session to abandon.

## Evidence and remaining gates

Focused regression command (warnings as errors) covered architecture/config03, canonical adapter/pipeline, Task09 contract/review, Luna review, sidecar, direct candidate races, prior scheduler/presentation, voice toggle/barge-in/Solo Owner and real composition/device control-plane: **428 passed in 9.87 seconds**. The separate reviewer owns Luna and sidecar adversarial tests; final updated review results are recorded in its document. Parent owns full release/status.

Exact command that produced that result, run from `C:/Projects/jarvis/jarvis`:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_v2_architecture.py tests/unit/test_voice_architecture_config.py tests/unit/test_voice_composition.py tests/unit/test_voice_frontend_contract.py tests/unit/test_realtime_frontend_adapter.py tests/unit/test_realtime_frontend_pipeline.py tests/unit/test_front_brain_hints.py tests/unit/test_front_brain_hint_review.py tests/unit/test_luna_front_brain_review.py tests/unit/test_front_brain_sidecar.py tests/unit/test_conversation_presentation.py tests/unit/test_v2_speech_scheduler.py tests/unit/test_speech_presentation_scheduler.py tests/unit/test_v2_voice_toggle.py tests/unit/test_v2_barge_in.py tests/unit/test_solo_owner_acceptance.py tests/integration/test_simple_front_brain_composition.py tests/integration/test_voice_production_composition.py tests/integration/test_voice_device_control_plane.py -q -W error --tb=short
```

The independent `test_front_brain_sidecar_review.py` suite was not part of this 428-test command; its updated final-source fixtures and independent rerun remain separately attributed to the reviewer.

Final app compatibility review reproduced one failure in 0.84 seconds: legacy `voice_arch="duplex"` leaked `ConfigurationError` because composition resolution preceded the existing user-facing error mapping. Resolution now runs inside that mapping. The existing unknown-architecture test retains its French `RuntimeError` assertion; a separate app test proves versioned Duplex still raises its specific unsupported `VoiceConfigError`, before credentials or session creation. Compatibility metadata is unchanged.

Post-fix app/config/composition gate: **83 passed in 6.44 seconds**, with warnings as errors. Exact command, from the same repository directory:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_app.py tests/unit/test_voice_architecture_config.py tests/unit/test_voice_composition.py tests/integration/test_simple_front_brain_composition.py tests/integration/test_voice_production_composition.py -q -W error --tb=short
```

Release follow-up: the surface-policy AST expected the old `continuous_brain` variable at the connector, although Task10 deliberately shares manual VAD flags with explicit modes through `continuous_capture`. Production semantics were verified and kept. The updated static assertion plus stronger app/wire behavior assertions pass **107 tests in 6.74 seconds**; the exact command and mode distinctions are recorded in the [surface policy regression review](10-surface-policy-regression-review.md).

Permanent new tests:

- `test_voice_composition.py`: versioned provider selection, compatibility preservation, early Duplex refusal, poison user context with roles and no response trigger, real VisualSignalBus cleanup-pending behavior.
- `test_conversation_presentation.py`: future source without event-loop starvation, later source activation, Stop removal, exact provider item references, invalidation during wire await and exact late cancellation.
- `test_front_brain_sidecar.py`: long delta coalescing, permission, final supersession/reserved budget, cancellation, failures, revision gaps and fail-closed retention.
- `test_simple_front_brain_composition.py`: actual app factory, authenticated Core/SQLite, canonical adapter/facade/bridge/scheduler, HTTPX Luna and buffered native device wrapper. Simple has zero Luna/backend calls; Front Brain answers while Luna is blocked, later consumes a real parsed final hint. Two turns preserve exact `[user A, confirmed assistant A, user B]` references while excluding rejected noise. Generated text is not intended or heard until actual controlled drain.

Real RuntimeJournal inspected at `C:/Users/Clarice/AppData/Local/Temp/pytest-of-Clarice/pytest-966/test_explicit_conversation_is_1/runtime/trace.jsonl`. Request `29761d5f-17e2-4b10-b9b3-38aaa6ba0a5b` records final dispatch (135168 reserved units), provider-shaped AVAILABLE receipt and `voice.hint.consumed` with committed revision1, while direct candidate `170a6c6c-f9c4-5f8a-8fbf-69924ab5fdf9` independently proceeds selected→generation_requested. Noise `rejected` records application rejection. Logs contain IDs/status/reasons and validated usage, no Luna hypothesis, refusal body or reasoning. These controlled timings establish ordering, not live latency or acoustic performance.

Concrete extra defect exposed by real composition: pending device cleanup called unsupported VisualSignalBus state `error`. Runtime now retains lifecycle ERROR plus an explicit alert, with supported visual state `thinking`; no false idle or reopening. The actual bus regression test covers it.

No independent jobs, live provider entitlement, monetary guarantees, hardware playback quality, active switching or Settings UI are claimed. Task11 uses the retained Core admission/source rather than appending another user turn. Task17 must retain the established provider/device cleanup ownership when replacing an active composition.
