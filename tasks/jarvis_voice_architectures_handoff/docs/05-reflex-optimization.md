# Reflex gate — Task06 implementation

The continuous-brain OpenAI path now asks a provider-neutral policy whether a preamble is useful before requesting any generated output. WAIT is a normal successful decision: no speech candidate, response.create, or device write. It never suppresses a substantive answer supplied by Core.

| Action | Task06 behavior |
|---|---|
| WAIT | Silence for standalone acknowledgements/declines, correction/continuation markers, ongoing user speech, missing or terminal work evidence, insufficient wait, stale or already used correlation. |
| SPEAK | Advisory indication that useful Core speech is ready. Existing speech scheduling remains its executor. |
| PREAMBLE | Permit at most one short preamble for an admitted correlation with attested ongoing Core work after the configured delay. |
| BACKCHANNEL | Reserved neutral value; no generation path enabled. Task06 does not insert sounds into ongoing user speech. |
| DELEGATE | Reserved advisory value; no new task executor or authorization. Existing Core permissions remain authoritative. |

French normalization checks the whole utterance, including typographic apostrophes. “OK” and “non c’est bon” wait; “OK, très bien, peux-tu comparer les prix ?” remains a request. A phrase ending in “attends je réfléchis” waits. These deliberately small textual controls are not semantic task classification. Even a conservative WAIT leaves the actual Core answer untouched.

The existing owner/address gate remains upstream: ambient, uncertain or rejected input never requests a reflex. The policy also accepts admitted=False for isolated contract tests. It does not create a new owner detector or admit provisional ASR. Task10 owns speculative provisional processing.

## Production path and timing

_run_voice_v2 → PersistentVoiceRuntime → bridge admission/Brain submission → SpeechScheduler.request_reflex → decide_reflex → existing scheduler deadline → façade speak_reflex → canonical frontend → the sole low-level OpenAI wire reader.

The existing ack_delay_ms setting is reused (default 1200 ms; zero disables preambles). The existing scheduler grace of 2.5 s after that deadline is the expiry. No second arbitrary delay, network classifier, VAD setting, or model-selection setting is introduced.

brain.work.started attests work even if it precedes request_reflex. Completion, failure, cancellation/supersession, later admitted turns, user speech and any useful queued answer invalidate a preamble that has not begun a native write. Core stream/revision gaps discard cached attestation. The policy runs at request, deadline and after waiting for silence; an owned expiry remains active during response creation and until native write starts.

State is bounded: work/terminal/decision caches 128 entries; session correlation dedup, reserved output tokens and cancellation retention at most 4096 entries. Correlation dedup includes WAIT and expired candidates, so duplicate requests neither cancel valid preambles nor reset deadlines. Saturation stays silent until the runtime creates a new scheduler/session. Candidate transcript/avoidance limits reuse canonical VoiceReflexRequest (8192 characters, at most 16 avoidance phrases of 512 characters); correlation IDs are printable, nonempty and at most 256 characters.

## Output identity and race boundary

The scheduler reserves a unique local output ID before awaiting the provider. The canonical operation and existing response metadata carry it; provider response IDs remain separate. Cancellation resolves that exact reserved output/response pair and never falls back to a newer active response. Deferred cancellation is owned, deduplicated and bounded; a blocked WebSocket send cannot block the single event reader. Stop cancels and joins those tasks.

Each preamble has a lock-protected OutputAdmission token. On the device worker, begin_write atomically chooses INVALIDATED or WRITE_STARTED immediately before the first native write. It checks the original expiry without needing an asyncio tick. No policy, asyncio event or journal access occurs on that worker. A successful write acknowledges WRITTEN; a failed native write records WRITE_FAILED. Invalidation before write rejects queued and late PCM while generated transcript remains observable. Guarded first-audio/speaking observations follow successful device acceptance, including when the worker waited for the output lock.

Once native write has begun, a later result cannot honestly prove that preamble was unplayed. Task06 does not abort an in-flight native call or rewrite its evidence. Existing epoch/barge-in fences remain. Device acceptance is not device drain or heard-text confirmation: Task05 still conservatively produces PARTIAL/UNKNOWN, and Task07 owns real completion proof.

## Prompt and observability

REFLEX_INSTRUCTION is supplied only after PREAMBLE. It asks for one natural 3–10-word sentence acknowledging examination time, forbids generic “I understand your request”, fabricated results/progress/resource actions, reasoning narration, deadlines and unsolicited questions. Transcript/avoidance data remain untrusted prompt data. The historical general SURFACE_ACKNOWLEDGEMENTS compatibility list remains in continuous-brain session rules; it triggers no automatic output and is not the new preamble policy. Prompt registry work belongs to Task15.

Existing RuntimeJournal receives voice.reflex.decided at info: action, reason, phase, elapsed_ms, conversation_id and correlation_id. WAIT is never an error. voice.reflex.started means generation requested, not playback confirmed. Invalidation uses the existing skipped event plus a WAIT decision. Transport/start/control failures use sanitized stable codes; no raw transcript is added to gate logs. Full evidence, commands and limits: [06-implementation-evidence.md](06-implementation-evidence.md).

## Remaining slices

Task07 implementation preserves the Task06 first-write admission token. A weak local speech candidate now changes no output gain, including open-room mode; confirmed provider speech or, in Solo Owner, confirmed owner identity triggers interruption. Existing 800ms candidate expiry and acoustic detector thresholds (12 of40 ten-millisecond frames,6 consecutive,50-frame refractory) remain unchanged pending measured acoustic tuning. The controlled63-candidate rejection replay produces zero gain changes/cancellations; it is a synthetic control, not a recording of the source bus noise. Actual natural completion now requires a checked device drain and exact all-part byte coverage before the facade can confirm generated words. Device Stop has a bounded application wait with explicitly retained cleanup ownership. See [Task07 runtime/device evidence](07-runtime-device-evidence.md) for tests, diagnostics and native limitations.

Task07 owns VAD/interruption and device completion; Task08 owns general semantic speech scheduling; Task10 owns the analysis sidecar and provisional intent processing; Task11 owns independent backend delegation; Task14 owns architecture Settings; Task15 owns prompt registry; Task16 exposes Live lifecycle/timer/Stop; Task18 handles metrics and billing dimensions; Task19 owns replay and Task20 comparative benchmarks. Task06 tests are controlled policy and concurrency evidence, not a live acoustic benchmark.
