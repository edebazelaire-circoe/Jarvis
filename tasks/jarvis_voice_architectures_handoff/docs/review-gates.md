# Slice review gates

Each slice must supply changed ownership, focused commands/results, observable normal/error outcomes, and remaining integration work. Parent review checks the actual runtime entrypoints, not just isolated new classes. Provider fakes are test-only and cannot establish live quality or model access.

## Migration and configuration (02, 14, 17, 20)

- Existing `VoiceArchitecture` values (`legacy`, `continuous_brain`) govern tool authority, model defaults, and audio capture. The new selection must not silently reinterpret existing saved settings or environment values.
- Preserve explicitly selected model/provider and custom prompts. Unknown/incompatible selections must produce actionable validation; capability support and account availability are separate facts.
- New architecture behavior must be reachable through the production composition root. Merely adding a dropdown or factory without wiring does not pass.

## Conversation truth (03–05, 08, 12)

- Correlate session, turn, speech, backend task and provider output IDs without relying on timestamp joins alone.
- Distinguish backend intent, provider-generated transcript, and playback confirmation. A generated transcript before audio playback is not proof the user heard it.
- Zero played audio cannot enter heard history. Interrupted output may have unknown word boundaries: retain explicit partial/unknown evidence rather than falsely claiming the whole generated sentence was spoken.
- Device-buffer completion needs explicit evidence: the existing Python playout fence and `written - latency` cursor alone do not prove a fully drained device. Provider output start is generation, not local speech start. Any new drain implementation must preserve interruption epochs, PortAudio lock safety and input capture; failed device operations cannot claim confirmed delivery.
- Provider paraphrase must remain observable and distinct from the original backend result. Snapshot projection must not promote unspoken intent to heard history.
- Existing `BrainWorkingState.known_public_facts` includes backend summaries that may not have been spoken; it is not a substitute for heard-ledger evidence when constructing frontend conversation history.
- Test late/duplicate events after stop or switching; old sessions must not mutate new-session state or execute duplicate tasks.

## Responsiveness and task ownership (06–11)

- WAIT produces no queued speech, including on short confirmations and likely ambient noise.
- A late useful answer invalidates a pending preamble. New user intent invalidates stale unstarted conversational output while backend result data remains available.
- Weak local VAD may capture evidence but does not repeatedly duck/cancel real speech. Confirmed-owner interruption remains prompt; preserve Solo Owner enforcement.
- Sidecar failure/timeout is advisory and cannot block the voice path. Speculative deltas cannot dispatch irreversible work.
- Backend task lifetime is independent of frontend lifetime. Results become state/candidates; completion alone does not forcibly seize audio.

## Lifecycle and provider contracts (12–17)

- Verify wire schemas against official documentation. Delegation metadata is not task text; build the request from bounded canonical conversation state.
- Explicit runtime ownership covers starting, active, stopping and unknown provider state. Do not display OFF on close request alone.
- Test cancellation while starting, lost transport, close timeout, repeated Stop, process shutdown, and restart/orphan recovery. Uncertain old ownership must block duplicate billable starts.
- UI shows authoritative lifecycle state and exposes Stop outside Settings. Idle timeout and cost metadata are configurable; absent pricing means unknown cost, not zero.

## Evidence (18–20)

- Comparable timestamps distinguish backend readiness, queue delay and first audible/useful speech.
- Prompt/config fingerprints exclude credentials and sensitive runtime context. Diagnostic defaults do not duplicate raw transcripts needlessly.
- Historical replay must exercise integrated policy paths; a fake provider that unconditionally emits the desired outcome is not evidence of a fix.
- Live tests remain explicitly opt-in and bounded; unavailable access/hardware is a recorded gap. Keep the safe default unless comparative evidence supports a change.
