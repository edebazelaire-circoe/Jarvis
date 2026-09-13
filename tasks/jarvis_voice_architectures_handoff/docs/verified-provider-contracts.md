# Verified provider contracts

Checked 2026-09-12 against fetched official OpenAI documentation. Documentation research only: no credentials read, provider sessions opened, or billed requests sent. These notes distinguish documented wire behavior from JARVIS integration decisions and unverified recovery behavior.

## GPT-Live 1 primary WebSocket

Endpoint: `wss://api.openai.com/v1/live/sessions`, without model/query parameters; authenticate with the project key in `Authorization: Bearer ...`. First JSON message is `session.start`; configuration is inside `session`. Wait for `session.started` and retain its opaque `session.id` before audio or commands.

Minimal client-delegation configuration:

```json
{
  "type": "session.start",
  "event_id": "jarvis-start-1",
  "session": {
    "model": "gpt-live-1",
    "instructions": "Application-owned conversation instructions",
    "delegation": {"type": "client"},
    "audio": {
      "format": {"type": "audio/pcm", "rate": 24000},
      "output": {"voice": "marin"}
    },
    "store": false
  }
}
```

Both directions share the startup format. Supported formats: mono PCM16LE at 24000/16000 Hz; PCMU/PCMA at 8000 Hz. PCM chunks require complete samples. Send base64 raw audio through `session.input_audio.append.audio`; no append ACK. Receive audio through `session.output_audio.delta.delta`, ordered, without timing fields or an audio-done event. Pace input continuously, including silence; EOF does not close Live. No Realtime-style audio commit or voice response trigger. [WebSocket guide](https://developers.openai.com/api/docs/guides/voice-websockets?api=live).

## Transcript, history and acknowledgement boundaries

`session.input_transcript.delta` and `session.output_transcript.delta` carry `event_id`, `delta`, `start_ms`, `end_ms`. Preserve fragments exactly. Intervals are session-relative milliseconds, start-inclusive/end-exclusive, not word alignment or playback time. No transcript item ID or authoritative turn-completed event exists. Missing fragments do not establish silence; grouping must remain revisable.

Startup `input` accepts at most 128 text messages/8192 total tokens: developer/user content `input_text`, assistant content `text` or `output_text`; one part each, no system role. Initial instructions allow 16384 tokens. Model, voice, initial instructions/history, audio format and storage cannot change in-session. `session.update` is for supported Responses delegation settings; use instructions append for behavior changes.

Appends acknowledge with `client_event_id` matching outgoing `event_id`; `start_ms`/`end_ms` estimate context injection. Acceptance does not prove complete consumption, speech or playback. Error events may lack correlation/code; handle them independently. [Session guide](https://developers.openai.com/api/docs/guides/live-conversations).

## Client delegation

Wire trigger:

```json
{
  "type": "session.delegation.created",
  "event_id": "provider-event",
  "offset_ms": 1000,
  "delegation": {"id": "opaque-provider-id", "type": "delegation", "target": "client"}
}
```

This contains no utterance, task description, audio or parsed tool arguments. Build backend requests from retained transcripts and application state. Return the exact delegation ID; do not derive it from a task ID or parse its prefix.

Use `session.thinking.append` for factual context, `session.commentary.append` for information intended for speech (possibly paraphrased), and `session.instructions.append` for application-authored behavior. Each requires string `content` ≤500 tokens and `delegation_id` (known client delegation ID or null). Corresponding ACKs are `session.thinking.appended`, `session.commentary.appended`, `session.instructions.appended`. Repeated updates may reuse a delegation. Quiet context can influence later speech; it is not secret storage. Client work, permissions, confirmation and cancellation remain application responsibilities. [Delegation guide](https://developers.openai.com/api/docs/guides/live-delegation).

## Playback and interruption

Input mute/unmute commands acknowledge through `session.input_audio.muted`/`session.input_audio.unmuted`; they do not stop output or backend work. Corrective instructions can interrupt speech, but their ACK is no playback barrier. Immediate suppression requires local output mute/drop plus discarding queued audio and an explicit recovery policy. Transcript checks cannot assume advance audio approval time.

Sideband URL is `wss://api.openai.com/v1/live/sessions/{session_id}/attach`, same project authorization, no new `session.start`. The guide describes attaching to WebRTC/SIP sessions. Attachment supplies subsequent events, not history replay. Its reflected audio is always PCM16LE/24000 Hz; reflected output has timeline intervals, unlike primary WebSocket audio. Do not send mic audio over sideband. [Server controls](https://developers.openai.com/api/docs/guides/voice-server-controls?api=live).

The generic Sideband reference accepts attachment to an existing Live session, includes `SessionCloseEvent` among accepted commands and `SessionClosedEvent` among received events. This supports a **recovery attempt** using a retained session ID: attach, register the terminal receiver, send `session.close`, await `session.closed`. It does not establish successful reattachment after primary-WebSocket loss, replay of an already-emitted terminal event, or semantics of attach failure/404. No new `session.start` belongs in a reaper. The reference's SDK connect example omits the ID argument; use the guide's documented URL rather than guessing that SDK signature. [Sideband reference](https://developers.openai.com/api/reference/python/resources/live/subresources/sideband).

## Closure, duration and reaping limits

Install the terminal receiver before sending `session.close`; keep transport receiving until `session.closed`. Persist final `usage.seconds`, `reason`, and session snapshot before device/transport cleanup. `session.usage.updated.usage.seconds` is cumulative, never summed. Final reasons include `close_requested`, `expired`, `content`, `remote_hangup`, `connection_lost`. Even connection loss is final when accompanied by `session.closed`; socket closure alone is not. Timeout means incomplete finalization, not OFF. [Session lifecycle](https://developers.openai.com/api/docs/guides/live-conversations#usage-and-graceful-close).

Voice is billed per second, including silence and input-muted time; backend usage is separate. Duration snapshots and final usage differ from an application timer estimate. Persist both with explicit provenance; no permanent price constant belongs in lifecycle code. The WebRTC creation path bills 15 seconds during initialization, credited against running duration; do not extrapolate that charge to WebSocket or add it twice. [Live overview](https://developers.openai.com/api/docs/guides/live), [cost guide](https://developers.openai.com/api/docs/guides/voice-latency-cost?api=live).

`POST /v1/live/sessions/{session_id}/hangup` exists, returning no final usage. **Documentation discrepancy:** search snippets describe a Live session generally, but the fetched Python reference says SIP call. General primary-WebSocket applicability and HTTP success as authoritative billing finalization are therefore unverified. No Live session retrieve/list/delete operation is listed in the fetched Sessions surface; recording download is not status retrieval. Do not invent a GET-status or DELETE reaper. [Hangup reference](https://developers.openai.com/api/reference/python/resources/live/subresources/sessions/methods/hangup), [Sessions surface](https://developers.openai.com/api/reference/python/resources/live/subresources/sessions).

## Luna sidecar request

Preserve `gpt-5.6-luna`. Official model page supports Responses, streaming, function calling and structured outputs; text in/out and image input, no audio. Reasoning efforts: none/low/medium/high/xhigh/max; medium is default. Low is a candidate sidecar setting, not a benchmark conclusion. [Luna model](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

Application-shaped request to `POST /v1/responses`:

```json
{
  "model": "gpt-5.6-luna",
  "instructions": "Classify supplied provisional context; return only an advisory hint.",
  "input": [{"role": "user", "content": "Bounded transcript and state data"}],
  "reasoning": {"effort": "low"},
  "text": {
    "format": {
      "type": "json_schema",
      "name": "jarvis_front_brain_hint",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {"wait": {"type": "boolean"}},
        "required": ["wait"],
        "additionalProperties": false
      }
    }
  }
}
```

Replace this illustrative schema with Task09's complete contract. Responses uses `text.format`, not Chat Completions `response_format`. Require declared properties and reject extras; optional fields use nullable types. Handle refusals, incomplete responses, transport failure and stale results outside the success parser. Structured output constrains shape, not factual correctness or authorization. [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Integration decisions still required

- Delegation `offset_ms` is not a transcript commit boundary. A silence timeout is only an application heuristic. Delegate a bounded, revision-tagged context; preserve existing explicit action/confirmation gates. Late text/corrections must invalidate speculative decisions.
- Actual transcript and actual playback are separate evidence. Primary Live supplies no exact transcript-to-audio alignment. Never promote all received transcript text to heard merely because one audio chunk played, a local queue briefly emptied, or an append was accepted. Unknown/partial heard state must survive switching and interruption.
- Keep a durable session-owner record and `UNKNOWN_REAP_REQUIRED` on lost finalization; block replacement billable startup while cleanup is unresolved. A watchdog can retry on a usable connection or attempt the documented sideband attach/close flow for the retained ID. Lost terminal delivery remains uncertain even after attach failure or an HTTP hangup ACK. Process-crash/transport-loss cleanup needs explicit fault tests; do not emulate success in production.
- Documentation is not evidence of project entitlement, installed SDK compatibility, end-to-end audio quality, actual billing termination after transport failure, or measured latency. Validate those in explicitly enabled smoke/hardware tests after lifecycle protection exists.
