# Verified Realtime contracts for Tasks 05–07

Checked 2026-09-12. Read `jarvis/adapters/openai_realtime.py` and `docs/current-code-map.md`; fetched current official OpenAI guides and event references, including Markdown when the large HTML reference could not be opened. No credentials, provider sessions, implementation changes or tests in this research slice. Preserve configured model IDs; these notes do not select a new model.

## Event mapping

| Wire event | Fields to preserve / meaning |
|---|---|
| `conversation.item.input_audio_transcription.delta` | `event_id`, `item_id`, optional `content_index`, `delta`; provisional text. |
| `conversation.item.input_audio_transcription.completed` | Same identity, `transcript`, ASR `usage`; finalized transcription, not action authorization. |
| `conversation.item.input_audio_transcription.failed` | Item-scoped failure; never manufacture an empty successful final. |
| `input_audio_buffer.committed` | `item_id`, nullable `previous_item_id`; conversation ordering. |
| `response.created` | `response.id` plus metadata; generation started, not playback. |
| `response.output_item.added` | `response_id`, `output_index`, `item.id`; discriminate message/function-call items. |
| `response.output_audio_transcript.delta/done` | `response_id`, `item_id`, `output_index`, `content_index`, `event_id`; `delta` versus final `transcript`. |
| `response.output_audio.delta/done` | Same output identity; delta contains base64 audio. |
| `response.done` | `response.id`, `status`, `status_details`, `output`, `usage`; terminal generation. |

Audio/transcript `.done` also occur on cancellation, interruption or incomplete output. `response.done.status` distinguishes `completed/cancelled/failed/incomplete`. None proves playback. Usage has input/output/total tokens and optional modality/cache detail; preserve absence rather than inventing zero. ASR usage is separate, with token or duration variants. [Server event reference](https://developers.openai.com/api/reference/resources/realtime/server-events).

Input ASR runs separately from the audio model. Completion may precede or follow response events; finals from different turns can arrive out of order. Reconcile by item identity, not arrival order. The transcript can differ from the speech model's interpretation. Delta availability/latency depends on the selected ASR model; a model capability is not proof that useful partial text arrives before the user's turn ends. [Transcription guide](https://developers.openai.com/api/docs/guides/realtime-transcription).

## Quiet context and prompt changes

Context insertion and response generation are separate operations. Send `conversation.item.create` without the subsequent `response.create` to update context without explicitly asking for speech. A concurrently running or VAD-triggered response can still speak; quiet insertion is not a global silence guarantee. With VAD enabled, setting both `create_response` and `interrupt_response` false keeps detection while leaving generation decisions to JARVIS. [Conversation guide](https://developers.openai.com/api/docs/guides/realtime-conversations).

Application-authored context may use a system message with `content:[{"type":"input_text","text":"..."}]`; raw untrusted results must not become instructions. Tool results use `function_call_output` with the actual `call_id`. Major prompt changes use:

```json
{"type":"session.update","session":{"type":"realtime","instructions":"Resolved application prompt"}}
```

Only supplied fields change; empty instructions clear them. `session.updated` returns effective configuration. The model cannot change; voice changes are restricted after audio output. This is not Live's append protocol. [Client event reference](https://developers.openai.com/api/reference/resources/realtime/client-events).

## Interruption contract

`response.cancel` optionally targets `response_id`; success terminates with cancelled `response.done`. No active response produces an error without invalidating the session.

`conversation.item.truncate` requires an assistant audio `item_id`, `content_index:0`, and inclusive `audio_end_ms` within actual audio duration. ACK: `conversation.item.truncated`. Truncation removes server transcript text; it does not return precisely aligned heard words. [Client event reference](https://developers.openai.com/api/reference/resources/realtime/client-events#conversation.item.truncate).

JARVIS integration: stop/drop local output immediately, cancel active generation separately, then truncate the item actually playing using its bounded playback cursor. Await/observe rejection and ACK; issuing the command is not successful synchronization. Preserve generated text and playback extent separately. Calculate received PCM duration from decoded bytes, not base64 string length, which includes padding. Generation can finish while local playback continues.

## Semantic VAD

Supported conversation configuration:

```json
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "audio": {"input": {"turn_detection": {
      "type": "semantic_vad",
      "eagerness": "low",
      "create_response": false,
      "interrupt_response": false
    }}}
  }
}
```

Eagerness supports `low/medium/high/auto`; auto equals medium. Low allows longer continuation; semantic completion is model inference, not speaker identity or authorization. Server VAD instead exposes threshold (0–1), prefix padding and silence duration. Do not mix those server-VAD fields into semantic config. Setting turn detection null disables it. Flags shown above are application-controlled conversation choices, not provider defaults. Local owner/echo/noise admission remains necessary. [VAD guide](https://developers.openai.com/api/docs/guides/realtime-vad).

## WAIT and preamble policy

`wait_for_user` is an application-defined no-op function tool, not a special server event. Register it with `type:"function"`, a clear description, and an empty object parameter schema. The prompt should select it for silence, noise, TV/hold audio, side conversation and speech not addressed to JARVIS, without conversational filler afterward. A clearly addressed but unintelligible request instead warrants clarification.

Handle WAIT locally without backend dispatch or an unconditional new `response.create`. If returning a tool result, separate insertion from requesting a new response. Prompt guidance is not a hard output gate; JARVIS still owns local suppression decisions.

Preambles are conditional spoken updates for noticeable work. Direct answers, short confirmations/corrections/declines, unclear/background audio and lightweight tools should not get systematic filler. Delegation alone is not sufficient reason to speak. [Realtime prompting guide](https://developers.openai.com/api/docs/guides/voice-prompting).

## Necessary adapter changes identified from the current code

- Existing user delta/final mapping already separates provisional and completed text. Preserve wire event IDs and `previous_item_id` (currently discarded); add ASR failure mapping and separate ASR usage. Final transcription must still pass existing addressing/owner/action gates.
- Add assistant transcript delta mapping. Existing done mapping covers current `response.output_audio_transcript.done` and legacy spelling, but done alone cannot mean complete or heard speech.
- Preserve response usage/status details and per-content identity. Existing `response.done` projection only retains status/output IDs; current received-duration calculation approximates base64 length.
- Existing `send_context` and `send_tool_result` both unconditionally request a response. Add genuinely separate non-triggering operations rather than reusing these under a quiet/WAIT name. Keep their old behavior for existing callers until migrated.
- Expose prompt updates and accepted effective configuration. Current connect returns after sending `session.update`, and the reader ignores `session.updated`; do not mark prompt application confirmed at send time. Realtime's session ACK schema does not expose Live-style `client_event_id`; serialize updates or reconcile effective configuration rather than inventing correlation.
- Observe truncate ACK/error before reporting synchronization success. Existing method only sends a command. Its bounded item lookup is valuable and should remain.
- Existing `build_turn_detection` already produces valid semantic shape and disables auto response/interruption in continuous mode. New Simple policy must choose those flags deliberately instead of inheriting old architecture assumptions.

Documentation drift: some reference prose still says `conversation.item.created`, while current event listings/examples use `conversation.item.added`/`done`. Preserve compatibility where justified; do not make a new critical gate depend on an unverified spelling. Live tests must verify current account/model wire behavior. No official source here establishes word-accurate playback alignment or that a WAIT prompt always guarantees zero emitted audio.
