# OpenAI API Notes — initial 2026-09-11, verified 2026-09-12

These are external research notes, not claims derived from the JARVIS transcript.

Implementation wire contracts and current recovery limitations are documented in [verified-provider-contracts.md](verified-provider-contracts.md). That verification supersedes assumptions in these initial notes where more precise.

## Task12 implemented contract — 2026-09-12

The implementation targets the documented `/v1/live/sessions` WebSocket surface and exact model `gpt-live-1`; no separate dated API version is negotiated. The official contract was rechecked in [Task12 provider review](12-provider-contract-review.md). Implementation and controlled-test evidence are consolidated in [Task12 evidence](12-implementation-evidence.md); Task12 is accepted after the final parent release.

| Boundary | Implemented behavior |
|---|---|
| Connection/start | Project Bearer authentication, `wss://api.openai.com/v1/live/sessions`, then `session.start` with model, `delegation:{type:client}`, `store:false`, role-separated initial text, instructions and audio settings. Wait for `session.started`. |
| Audio | `session.input_audio.append.audio` and `session.output_audio.delta.delta`, raw base64 PCM16LE. Adapter supports 16/24 kHz; production facade uses shared 24 kHz mono format. No input ACK, Realtime commit, `response.create`, or `conversation.item.create`. |
| Transcripts | Input/output `.delta` preserves text and session-relative interval. Application grouping IDs remain local, provider item/turn identity and authoritative finality remain unknown. Input remains provisional; assistant text remains generated evidence. |
| Delegation | `session.delegation.created` carries offset and opaque client delegation ID, not task text. Flush canonical observations before Core captures bounded immutable dependencies; never treat adapter-local revision as Core snapshot revision. |
| Updates | Thinking, commentary and instructions append use `content`, fresh `event_id`, required nullable `delegation_id`. ACK must match command/channel via `client_event_id`. ACK proves append processing, never hearing; timeout remains unknown and is not blindly retried. |
| Usage | Preserve cumulative `usage.seconds`, final usage, close reason, provider expiry and optional context usage ratio. Ratio may decrease. These are provider observations, not a verified invoice or local elapsed-time calculation. |
| Stop | Send `session.close`, keep the reader alive for `session.closed`. Final resource `status:active` does not contradict terminal closure. EOF/timeout without terminal event stays unknown; runtime blocks idle/offline/reopen for uncertain typed close. |

Application bounds are deliberately narrower than provider allowances: append content at most **500 UTF-8 bytes**, startup instructions at most16384 UTF-8 bytes, initial text at most8192 UTF-8 bytes and128 messages. These are conservative admission limits, not an exact tokenizer. Results exceeding append capacity remain durable without automatic truncation or summarization. The facade's controller chooses fresh progress as thinking and fresh terminal results as commentary; instructions remain application-authored.

The accepted design wording “final state” refers to lifecycle/Job state, not invented transcript finals. “Spoken ledger” retains separate generated and playback evidence: primary Live supplies neither exact alignment nor the complete audio-part manifest used by Realtime's device drain. No output transcript, append ACK, empty device queue or silence promotes Live words to heard.

Live has no exact native cancel/truncate equivalent. Authorized local interruption now latches playback suppression for the remainder of that frontend incarnation, including queued and new-ID tails. Further speech requires a new incarnation after confirmed closure; input and independent Jobs continue. See [lifecycle/playback proof and usability limit](12d-lifecycle-playback-evidence.md).

Task12C supersedes the initial restricted-executor gap: configured native Claude can run a fresh result-only `speculative_analysis` Job with enforced restricted CLI flags and no tools/hooks/MCP/browser/session reuse. Codex and unsupported launch profiles return durable unavailable. This does not authorize actions or manufacture a committed user turn. Final Task12 repairs retain connection-cancellation cleanup through late startup/transport closure and emit `voice.live.usage` with cumulative/final provider provenance. Task13 still owns durable session leases, watchdog/reaper/recovery and crash-safe termination. A dedicated smoke guarded by `JARVIS_LIVE_GPT_LIVE=1` plus `OPENAI_API_KEY` is present, not executed; project entitlement, hardware acoustic quality and billing termination remain untested.

## GPT-Live client delegation

OpenAI documents GPT-Live as managing spoken conversation while reasoning/tool work can be delegated to a backend. In client delegation, the application prepares backend context, runs a model/agent/service it operates, and chooses results returned to Live. The application owns permissions, confirmations, task state, and conversation context.

Reference: https://developers.openai.com/api/docs/guides/live-delegation

Implementation consequences: delegation mode is chosen when creating the session; JARVIS retains conversation/application state; input/output transcript deltas are available; delegation metadata must be combined with JARVIS context to prepare backend requests.

## Quiet vs spoken updates

- `session.instructions.append` — redirect frontend behavior.
- `session.thinking.append` — quiet context usable for reasoning without immediate speech.
- `session.commentary.append` — information intended to be spoken/paraphrased.

An append acknowledgement is not proof that content was actually spoken. Output transcript supplies generated words; local playback supplies separate delivery evidence. Live primary WebSocket has no exact text/audio alignment, so interrupted heard words may remain unknown (Decision 19).

Reference: https://developers.openai.com/api/docs/guides/live-delegation

## Realtime WAIT behavior

OpenAI Realtime prompting guidance recommends a no-op `wait_for_user` pattern for silence, background noise, side conversation, or speech not addressed to the assistant, and recommends avoiding filler after it.

Reference: https://developers.openai.com/api/docs/guides/voice-prompting

## Realtime preambles

Preambles are recommended only when noticeable work is happening and discouraged for direct answers, confirmations/corrections/declines, unclear audio, background noise, or lightweight tool calls.

Reference: https://developers.openai.com/api/docs/guides/voice-prompting

## Semantic VAD

Realtime supports `semantic_vad` with configurable eagerness (`low`, `medium`, `high`, `auto`). Lower eagerness gives users more time to speak.

Reference: https://developers.openai.com/api/docs/guides/realtime-vad

## Migration principle

OpenAI's GPT-Live migration guide recommends recording existing prompts, tools, workflows, input types, and audio-dependent decisions that must be preserved before migration.

Reference: https://developers.openai.com/api/docs/guides/live-migration
