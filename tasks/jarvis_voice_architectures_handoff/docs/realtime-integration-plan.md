# Concrete Task05 integration plan

Original preparation:2026-09-12 during Task04 review. Task05 now implements this path; see `05-implementation-evidence.md` for exact shipped boundaries/tests. Root `docs/state-model.md` was subsequently read and reconciled with accepted Task04. The plan below remains design context, not a claim that deferred policy/device/lifecycle tasks have shipped.

## Delivery boundary

Task05 must move the **existing selected OpenAI Realtime path** through a real `VoiceFrontend`, including old legacy tools and continuous reflex/verbatim output. Preserve `voice_arch=legacy/continuous_brain` execution semantics and exact model/settings selection. This does not activate new Simple behavior, Front Brain or Duplex, change policy defaults, or migrate UI.

An isolated new adapter plus tests is insufficient. Actual `_run_voice_v2 → PersistentVoiceRuntime.activate → audio bridge/scheduler` must instantiate/use the adapter; Core must receive canonical conversation evidence. Existing Gemini path remains separate and unchanged.

## Smallest actual ownership chain

```text
app._run_voice_v2 (resolved existing model/settings/credentials)
  → OpenAIRealtimeFrontend (sole owner of OpenAIRealtimeSession)
    → compatibility session facade (old runtime methods, canonical controls)
      → PersistentVoiceRuntime / RealtimeConversationBridge
        → existing ordered playout + urgent control fences
        → bounded canonical observation dispatcher
          → existing authenticated LocalCoreClient/server
            → Core-owned VoiceConversationState + one history projection
```

The facade is a temporary adapter for existing bridge/scheduler contracts, not a second provider connection. Its sole `events()` reader consumes `VoiceFrontend.events()` and creates the bridge's existing internal event envelopes as needed. Only `OpenAIRealtimeFrontend` consumes low-level session events/wire data; no parallel ledger reader, no optional observer opening `session.events()` a second time. Internal `realtime.*` compatibility envelopes stay in runtime; Core receives only strict canonical values.

Keep `SoundDeviceRealtimeAudio`, capture processor, owner replay/gate, bridge output identity, interrupted-output blacklist and audio queues. Do not rewrite acoustic logic while proving the abstraction. The facade must expose required optional structural methods (`speak`, `speak_reflex`, `cancel_output`, `truncate`, active-output queries) through frontend operations or frontend-owned typed migration controls, never through a publicly exposed `.raw_session` escape hatch.

## Contract extensions required for truthful compatibility

Current VoiceFrontend has no tool-call/result or reflex generation operation. These are required by existing legacy/continuous behavior. Add the narrow typed canonical values/operations and contract tests before wrapping:

- Tool-call event: opaque call ID, application tool name and strictly bounded JSON argument values. Preserve source identity/deduplicate dual provider completion spellings. Arguments are untrusted data; event does not grant execution permission. Existing runtime `CoreToolRouter`/action confirmation still decides. Do not convert tool arguments into runtime instructions.
- Tool-result operation: matching actual call ID plus bounded result data and explicit continuation flag. Existing legacy behavior continues requesting the next response; quiet/WAIT use can omit it later. No fake user transcript or textual concatenation into a system prompt.
- Reflex request operation: admitted user transcript plus bounded avoid-phrase list; frontend builds the existing reflex response instruction. This differs semantically from reading a verified backend result. Keep it explicit, rather than misusing `append_spoken_result` or changing session instructions temporarily.
- Received-audio evidence for Core: typed cumulative duration for one correlated output (or a batch-level accounted delta with explicit dedup identity). Task04 currently counts `AssistantAudioChunk.pcm` bytes. Audio remains on local playout path; **do not send PCM/base64 over HTTP to Core** just to compute duration. Add lightweight validated evidence to reducer without asserting playback. Task04 owner must approve that minimal extension after review.

Transport keepalive remains frontend-owned, below canonical semantics. Existing quiet-context and prompt-update operations need true provider primitives: context item insertion without `response.create`, and serialized/confirmed `session.update`. Preserve legacy `send_context` and tool-result continuation semantics until explicit callers change.

## File responsibilities

| File | Task05 responsibility |
|---|---|
| `jarvis/adapters/openai_realtime.py` | Retain low-level wire/session/output accounting. Preserve wire event IDs, session/item/response IDs, previous input ID, assistant deltas, final status/details, separate ASR usage and generation usage. Decode PCM length accurately. Observe session.updated and truncate ACK/error; distinguish sent from confirmed. |
| New `jarvis/adapters/openai_realtime_frontend.py` | Canonical lifecycle/control/event adapter; one reader and bounded queue; exact selected old model/settings; opaque correlation binding; output/text/usage translation; close during start/cancel cleanup. No Core state/history ownership. |
| Narrow canonical domain/port extensions | Typed tool call/result/reflex and lightweight received-audio evidence only. Unsupported operations remain explicit for other adapters/fakes. No provider payload escape field. |
| New runtime compatibility facade | Adapt canonical frontend back to old session/optional output-control interfaces so existing bridge/scheduler acoustic behavior remains intact. Document removal condition when runtime itself consumes canonical controls in later migration. |
| New runtime observation dispatcher | Single session identity/observation sequence owner for normalized provider and local playback observations. Bounded queue/coalescing/batch transport, no audio upload, no transcript/terminal silent loss. |
| `jarvis/runtime/realtime_audio.py` | Add evidence hooks at receipt and actual device boundaries, retaining `_dispatch`, `ORDERED_OUTPUT_EVENTS`, `_play_out`, `_drop_audio_before`, per-output blacklist and SoloOwner admission. Stop direct assistant-history writes only when canonical history authority is active. |
| `jarvis/runtime/speech_scheduler.py` | Register intended candidate separately, preserve queue/reflex policy, stop `_persist(request.text)` as heard truth on migrated path. Report output completion/interruption into single canonical evidence owner. Avoid duplicate assistant turns. |
| `jarvis/runtime/voice_v2.py`, `jarvis/app.py` | Construct frontend/facade/dispatcher in real OpenAI factory; bind Core ledger session before events; flush/close dispatcher on runtime teardown; keep exact old execution mode. Do not stop Core jobs. |
| Core voice service + `JarvisCoreApplication` | Own one `VoiceConversationState` per conversation on Core event loop; bind frontend incarnation, apply validated batches, register speech intent, expose bounded snapshot/context and deduped history projection. Reducer is currently not production-owned. |
| `protocol/client.py`, `protocol/server.py` + narrow codec | Extend existing authenticated loopback transport for session bind/observation batch/snapshot/candidate intent. Validate envelope and payloads before application; forbid credentials/raw SDK objects/audio. Reuse snapshot codec, but don't treat a client-provided snapshot as authoritative replacement of Core state. |
| `ConversationService`/history projection | One explicit migration path for durable assistant history and rehydration; generated transcript, intended text and playback metadata remain distinct. Existing history must not override canonical heard projection on migrated sessions. |

## Observation ordering and transport cost

Use one session incarnation and sequence source shared by normalized provider observations and local device evidence. A naive provider sequence counter plus independent playback counter collides. Prefer dispatcher stamping global sequence at dispatch/application order while retaining original receipt timestamp and provider event ID; injected shared sequencer is also valid if delayed playout observations cannot be retired as stale. State acceptance/dedup remains `(session_id,event_id)` with explicit source IDs. Do not join on wall-clock proximity.

Provider-generated text enters state as generated evidence at reception, even if output is later discarded. Device playback evidence is emitted only from playout/cursor handling. Ordered completion fences ensure a generated terminal event never implies speaker drain. Late/canceled text can remain generated evidence but cannot revive interrupted speech or publish heard content.

Core transport should batch small canonical observations, with a bounded flush interval and batch size (e.g. provisional50ms/32 events, configurable implementation constants), and coalesce cumulative duration/usage for the same output before assigning final batch sequence. Final transcripts, tool calls, cancellation, terminal lifecycle and playback boundaries must not be silently coalesced away. Backpressure/overflow must stop/refuse with a stable diagnostic rather than grow memory or block mic/playout indefinitely. Immediate local interruption never awaits HTTP. These are transport proposals, not measured performance defaults.

Only compact received-audio counters cross to Core; PCM is delivered directly from canonical frontend to local audio. Snapshot/context retrieval happens on activation/rehydration/review, not on each frame. Do not POST an entire snapshot as every event's replacement. Reject stale session batches without resetting current state or touching new-session output.

## Playback/history details that must be explicit

1. Register scheduler `SpeechRequest.text` as intended candidate with speech/turn/task lineage, not assistant heard history. Provider transcript carries generated words for both speech-id and spontaneous reflex output.
2. For device start, publish `AssistantSpeechActivity.STARTED` only after a real local playback boundary; `response.created` maps to `AssistantGenerationStarted` instead.
3. Preserve cursor before `_release_playback_output` or abort resets accounting. Publish UNPLAYED at zero audio, PARTIAL when interrupted after positive extent, UNKNOWN when reliable extent/end is unavailable. COMPLETE requires provider end evidence plus drained device output, not empty Python queue or response.done alone.
4. Raw transcript and positive PCM duration do not provide word alignment. Leave `confirmed_text=None` unless the implementation establishes the independently supported full-output/span relationship. Never truncate text by character/audio ratio. Task04 recent_context intentionally represents unknown heard wording honestly.
5. Choose one canonical history projection; old bridge spontaneous assistant append and scheduler `_persist` cannot run alongside it. Persist delivery/source/correlation metadata and only words justified by its evidence. Generation-only output must not be inserted as a heard answer. Partial unknown delivery should remain explicit without inserting the entire intended answer as known public fact.
6. Legacy durable records have weaker provenance. Do not retroactively relabel old intended transcripts as verified heard speech. Preserve records for compatibility and seed new canonical state using explicit legacy/unknown source semantics; follow final Task04 review for allowed snapshot projection.

## Usage and lifecycle pitfalls

Realtime `response.done.usage` is per response, whereas canonical `VoiceUsageUpdated` counters are cumulative per session. Deduplicate by response ID and accumulate once; do not replace session totals with one response or add retransmissions twice. Input ASR usage is separate and may be duration-shaped; do not merge it into conversational token totals without source distinction. Missing fields stay unknown. `get_usage_snapshot` is not currently in VoiceFrontend protocol; use canonical usage events unless a typed explicit accessor is added.

Current connect returns after sending session.update. Canonical ACTIVE/application of prompts must follow actual session acknowledgement, handled by the sole reader. Avoid deadlock where start awaits an ACK before any reader starts. Realtime WebSocket closure semantics differ from GPT-Live billing terminal confirmation; document the evidence chosen for Realtime stop, keep unknown on ambiguous cleanup, and do not invent Live close events. Idempotent stop during connect must retain cleanup ownership.

## What waits for later tasks

| Later slice | Explicitly deferred |
|---|---|
|06| WAIT/reflex/preamble decisions, new fillers suppression, changing closed/open tool policy. Task05 only preserves existing reflex requests and enables truthful operations. |
|07| Semantic VAD defaults/tuning, repeated duck/noise policy redesign. Owner gates and old VAD values remain intact. |
|08| Semantic chunk freshness/priority/result routing changes. Existing scheduler policy stays while history provenance changes. |
|09–13| Luna speculation, generalized nonblocking backend work, GPT-Live transport/cost watchdog. |
|14–15| Architecture selector and prompt editor UI; schema presence is not behavior activation. |
|17| Explicit new architecture/model transition and full state rehydration coordinator. Task05 only makes normal existing Realtime activation/close pass through canonical ownership. |

## Required validation before accepting05

- Real composition test patches only provider transport/audio backend, invokes existing runtime activation and verifies VoiceFrontend start/events/control/stop, canonical Core state update, correct old model/settings and no raw provider reader bypass.
- Wire translation: actual documented events, out-of-order user finals linked by item/previous item, assistant delta/done, cancelled/incomplete status, malformed ASR failure, per-response deduped usage, missing values, exact decoded PCM duration.
- Compatibility: legacy tools still execute through existing policy/confirmation; native tool call duplicate events execute once; continuous tools remain closed; reflex instruction and verbatim request unchanged; no fake user turn; Gemini separation unchanged.
- Acoustic fences: generated transcript before first playback; interruption before first PCM; interruption after partial PCM; finished generation with queued/device-buffered audio; delayed canceled audio; correct item truncation; owner replay and provider/local confirmation authority.
- Core truth: exactly one assistant history authority; intended/generated divergence recorded; zero-played answer absent from heard context; unknown partial words remain unknown; late events cannot change new session; source turn lineage survives out-of-order finals.
- Transport: no PCM in Core JSON, bounded queue and batch sizes, slow Core/overflow handled without silent transcript loss, local cut does not await Core HTTP, stale/replayed batch rejected/deduped, no secrets in diagnostic payloads.
- Lifecycle: start twice, stop twice, stop/cancel while starting, lost provider, reader exit versus explicit close, idle reader awakened on stop, failed initialization cleans every created client/audio/dispatcher resource. Existing queued Core work survives mute.
- Run existing targeted adapters/lifecycle/scheduler/migration/SoloOwner tests plus new production composition tests and global collection (Task03 repair showed focused suites miss package-level collection regressions). Hardware/live tests remain separate and bounded, not inferred from fakes.

The substantive new behavior in05 is truthful observation/history ownership mandated by decisions05/19; audio and conversational policy remain compatibility behavior. Document that intentional history change clearly instead of weakening tests to preserve the old intended-text claim.
