# Task12 slice A — official contract review

Fetched 2026-09-12. OpenAI Docs skill applied; official pages and their Markdown representations were read. No credential inspection, provider connection, inference, production edit or slice-status change. This supplements `verified-provider-contracts.md`; it is not an implementation acceptance.

## Wire contract revalidated

Primary socket: `wss://api.openai.com/v1/live/sessions`, no query/model parameter, project Bearer authorization. Send `session.start` first with `session.model="gpt-live-1"`, `delegation={"type":"client"}`, configured instructions/history/audio, `store=false`; wait for `session.started` before audio or commands. One shared startup audio format applies both ways: mono PCM16LE 16/24 kHz, or PCMU/PCMA 8 kHz. Audio is raw base64 JSON, not a container. PCM samples must be complete. `session.input_audio.append.audio` has no ACK. `session.output_audio.delta.delta` has no primary timing or done event. Pace continuous input, including silence; EOF does not end the session. No Realtime commit/voice `response.create` loop exists. [WebSocket guide](https://developers.openai.com/api/docs/guides/voice-websockets?api=live)

The exact model remains `gpt-live-1`: audio/text input and output; Live endpoint only, not Realtime/Responses. Structured outputs are unsupported for the Live model itself. Published price is $0.05/minute billed per second, with separate backend usage. Concurrent-session tiers are 25/50/200/300/500 for tiers 1–5, Free unsupported; project access was not tested. Do not make these changing values permanent runtime constants. [Model](https://developers.openai.com/api/docs/models/gpt-live-1)

## Minimal server shapes

Fields below exclude optional common `client_event_id`; ordinary server events have `event_id`. Crucially, audio deltas do not require `event_id`.

| Type | Required relevant fields |
|---|---|
| `session.started`, `session.updated` | `session` resolved configuration |
| `session.input_transcript.delta`, `session.output_transcript.delta` | `delta:string`, `start_ms:int`, `end_ms:int` |
| `session.delegation.created` | `offset_ms:int`, `delegation:{id,type:"delegation",target:"client"}` |
| `session.{thinking,commentary,instructions}.appended` | `start_ms:int`, `end_ms:int`; command match through `client_event_id` |
| `session.usage.updated` | `usage:{seconds:float}`; optional `context_window:{usage_ratio:float}` |
| `session.closed` | `reason`, `session`, `usage:{seconds:float}` |
| `error` | `error:{type,message,code,client_event_id?,param?}` |

`SessionResource` includes `id`, `expires_at` Unix seconds, `model`, `status:"active"`, resolved optional configuration. **Even the final snapshot retains status active**: only `session.closed` establishes closure. Output audio is `{type,delta}`, with timestamps only for reflected sideband events. Context usage ratio may decrease after compaction; it is not a monotone counter. [API reference](https://developers.openai.com/api/reference/python/resources/live)

## Appends, update and transcript boundaries

Each append sends `type`, optional application `event_id`, plain `content` up to 500 tokens, and required nullable `delegation_id`. Thinking supplies quiet facts, commentary requests speakable facts, instructions supplies trusted application behavior. A non-null delegation ID must be a known client delegation; preserve it unchanged and only within that provider session. Repeated appends may use it. The delegation trigger contains no task text; derive context from retained observations and application state. Client delegation never configures or executes the application's backend. [Delegation guide](https://developers.openai.com/api/docs/guides/live-delegation)

Startup instructions allow 16384 tokens; history 128 messages/8192 tokens, one text part each, roles developer/user/assistant, no system. Model/audio/voice/storage/delegation mode cannot change in-session. `session.update` changes only existing Responses delegation settings, so it is not the client-mode prompt editor. Runtime behavior uses instructions append.

Transcript intervals are session-relative, start-inclusive/end-exclusive. Keep exact fragments and revisable local grouping; no item ID, authoritative final or silence inference. Append ACK estimates context injection, not full consumption or hearing; stalled frames can delay it, and closing rejects pending appends. Error code may be null per the guide despite the reference's string declaration: decoding must tolerate this documented discrepancy. Moderation can interrupt output without closing. Usage seconds are cumulative; closure reasons are close_requested/expired/content/remote_hangup/connection_lost. Keep receiving until closed; timeout/transport loss leaves finalization unknown. [Session guide](https://developers.openai.com/api/docs/guides/live-conversations)

## Recovery and playback limits

Sideband URL remains `wss://api.openai.com/v1/live/sessions/{session_id}/attach`, same project authorization, no start command. It permits close/closed on an existing session. It does not replay history; reflected audio is PCM16LE/24 kHz. Input mute does not stop output or tasks. Instructions can steer interruption but their ACK is not an audio barrier: local suppression/queue disposal remains necessary. Timestamps still do not prove device hearing. [Server controls](https://developers.openai.com/api/docs/guides/voice-server-controls?api=live)

A retained-ID attach-and-close recovery attempt is supported, but successful reattachment after lost primary transport and replay of a previously missed final event remain unproven. No retrieve/list/delete Live session endpoint was found. The fetched hangup reference still describes SIP, so generic primary-WebSocket hangup applicability remains unresolved; an HTTP success is not final usage. [Sideband](https://developers.openai.com/api/reference/python/resources/live/subresources/sideband), [hangup](https://developers.openai.com/api/reference/python/resources/live/subresources/sessions/methods/hangup)

## Drift from previous notes

No changed primary event names, startup path, client-delegation text semantics or newly authoritative transcript/audio finality found. Add the following precision before coding:

- Do not require event_id on output audio or interpret final session.status as closed.
- Preserve expires_at and optional context usage, with provenance distinct from local timers.
- Preserve nullable/uncorrelated error handling despite the generated type discrepancy.
- Startup and append acceptance are not provider idempotency guarantees: a lost append ACK must remain unknown; blindly resending can inject duplicate content.
- Sideband recovery and hangup limitations remain open, not solved by the unchanged documentation.

## Proposed adapter boundary — application design, not provider promises

Use the existing `VoiceFrontend` port: start, send_audio, three append methods, bounded/idempotent stop and one event consumer. `finish_input` is unsupported; there is no exact native cancel/truncate primitive equivalent to Realtime. A corrective instruction can be exposed only as steering after local output suppression, never as confirmed cancellation.

One reader validates/correlates provider messages and feeds bounded canonical queues. Reader delivery order provides local observation sequence; application-generated grouping/output IDs must be labeled application identities, not provider item IDs. Preserve raw fragment intervals. Emit transcript deltas/revisions only; do not fabricate committed input, completed assistant transcript, generation manifest or COMPLETE playback from inactivity, delegation, append ACK or socket close. Playback accounting can prove consumed PCM blocks, but cannot map exact heard words without alignment/finality the provider does not supply.

The controller flushes relevant observations through canonical Core before capturing delegation provenance, while bounded trigger jobs leave the socket reader free. It preserves provider session/delegation, local incarnation and exact dependency revisions. Quiet/speakable injection requires current source/dependencies and a fresh local operation; replacement sessions never inherit the old delegation ID. Existing Task11 status/list is the durable task authority. Unknown schema/loss/queue overflow must surface failure rather than silently drop authority-bearing events. Appends need real provider token-limit enforcement and bounded ACK ownership, including close/error races.

## Task11 versus Task12 acceptance conflict — explicit conclusion

Historical slice-A assessment below, superseded for supported native Claude by the approved Task12C restricted executor. Codex/unsupported profiles remain unavailable; no task admission or action authority is inferred. See [current implementation and tests](12-implementation-evidence.md). The provider contract above remains applicable.

**The current Task12 useful first-session provisional-analysis criterion cannot pass with the accepted Task11 executor.** Task11 intentionally persists advisory provenance and returns restricted_execution_unavailable before spawn. A Live delta/delegation does not turn that unavailable capability into authorized work. Neither a fake commit, an arbitrary matching old source, a prompt-only tool restriction, managed Responses delegation nor silent substitution of Luna is a valid resolution.

Recommended next scope: implement and test this adapter's wire/canonical behavior, retaining the honest unavailable advisory route. Keep the useful speculative-analysis acceptance criterion outstanding. Completing it requires a separately approved restricted executor for the configured backend/model, with actual tool/startup/network enforcement and controlled negative tests, then a real typed advisory Job/result path. Task11's current immutable unavailable-reference table is not that execution contract. Alternatively, the orchestrator must explicitly defer that criterion; this research does not change it. Already-admitted work may still use Task11 normally, but it cannot prove the first-session no-commit case. Action proposals remain pending until a real application admission boundary and existing confirmation policy authorize them.
