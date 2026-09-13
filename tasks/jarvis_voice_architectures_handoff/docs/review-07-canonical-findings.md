# Task07 canonical proof join — independent review

2026-09-12. Scope: `voice_playback_manifest.py`, façade/adapter provenance and Core join. No production or test files changed. Controlled Python snippets run through stdin, without provider session/device access. Focused recheck results are recorded below; this note does not change a slice gate.

## F1 — Contradictory evidence after freeze still permits COMPLETE

`freeze()` validates received/closed/expected sets, but `complete()` trusts the saved manifest without rechecking their current consistency. `observe()` accepts an extra closed part and ignores the significance of a delta arriving after that part's transcript final.

Reproduction: create one 480-byte audio part, close it, complete transcript `BEFORE`, complete generation with that one expected part, then freeze. In separate runs, inject either:

- `AssistantAudioPartCompleted(VoiceAudioPart('extra', 0, 1))`;
- `AssistantTranscriptDelta('text', ' AFTER', original_part)`.

Submit a COMPLETE device proof matching the original frozen part/bytes/IDs. Both runs returned `AssistantPlaybackEvidence(status=COMPLETE, confirmed_text='BEFORE')` despite the contradiction known before proof acceptance.

Expected fix: reject/invalidate unknown post-terminal part closures and post-final transcript deltas; revalidate frozen inventory at proof and late-text join. Preserve legitimate late *first* transcript-final evidence. Repeated identical close/final events may be idempotent; contradictory evidence must not become a new eligibility path.

## F2 — Final manifest transcript is discarded before cross-check

`OpenAIRealtimeSession._response_audio_parts()` returns only part IDs/indices. Two response manifests differing only in final audio transcript (`BEFORE` versus `CONTRADICTORY`) produce identical canonical inventories. The helper can subsequently confirm an earlier transcript-final string without detecting the terminal manifest's different text.

Expected fix: preserve bounded final per-audio-part transcript evidence and compare it with independently observed final transcripts before confirming words. Missing final text remains unknown; it must not be coerced to an empty final. A contradictory final cannot be ignored merely because IDs/bytes match. Maintain mixed text/audio distinctions: text-only content is never attributed to played audio.

## Exact initial controlled snippet

```python
from types import SimpleNamespace
from jarvis.runtime.voice_playback_manifest import VoicePlaybackManifests
from jarvis.domain.voice_events import *
from jarvis.domain.voice_frontend import VoiceAudioChunk, VoiceCorrelation
from jarvis.domain.voice_playback import *
from jarvis.adapters.openai_realtime import OpenAIRealtimeSession

p = VoiceAudioPart('item', 0, 0)
c = VoiceCorrelation('session', output_id='output', provider_output_id='response')
def event(payload):
    return SimpleNamespace(correlation=c, payload=payload)
def prepare():
    m = VoicePlaybackManifests()
    for value in [AssistantAudioChunk(VoiceAudioChunk(b'\0\0' * 240), p),
                  AssistantAudioPartCompleted(p),
                  AssistantTranscriptCompleted('text', 'BEFORE', p),
                  AssistantGenerationFinished(VoiceGenerationStatus.COMPLETED, (p,))]:
        m.observe(event(value))
    f = m.freeze('session', 'output', 'response')
    proof = VoiceDevicePlaybackProof(
        VoiceDevicePlaybackStatus.COMPLETE, 'session', 'output', 'response',
        'device', 0, 0, 'op', f.parts, f.received_bytes, f.received_bytes)
    return m, f, proof

for late in [AssistantAudioPartCompleted(VoiceAudioPart('extra', 0, 1)),
             AssistantTranscriptDelta('text', ' AFTER', p)]:
    m, f, proof = prepare()
    m.observe(event(late))
    result = m.complete(f, proof)
    print(type(late).__name__, result.status if result else None,
          result.confirmed_text if result else None)

for text in ['BEFORE', 'CONTRADICTORY']:
    response = {'output': [{'id': 'item', 'type': 'message', 'role': 'assistant',
        'status': 'completed', 'content': [{'type': 'output_audio', 'transcript': text}]}]}
    print(text, OpenAIRealtimeSession._response_audio_parts(response))
```

Observed initial output:

```text
AssistantAudioPartCompleted complete BEFORE
AssistantTranscriptDelta complete BEFORE
BEFORE [{'item_id': 'item', 'content_index': 0, 'output_index': 0}]
CONTRADICTORY [{'item_id': 'item', 'content_index': 0, 'output_index': 0}]
```

## Focused recheck after owner fix

Repeat the two contradiction paths and the final-manifest mismatch, adapting construction only for deliberate new typed fields. Also verify two positives: a legitimate first final transcript arriving after device drain can establish text once; a consistent multipart output with all expected parts and exact proof confirms the combined audio transcripts in manifest order. Do not replace the reproduction with an isolated test that simply injects desired COMPLETE evidence into Core. Device proof remains controlled input here: these checks validate the proof join, not physical device drain or a live provider trace.

### Independent recheck after owner fix — passed

The owner added `AssistantGenerationFinished.audio_transcripts`, preserved raw final-manifest text through the adapter, rejected contradictory post-final evidence and revalidated the part inventory when accepting proof. Replayed the original two F1 sequences unchanged. For F2, supplied the new final transcript tuple while keeping the observed transcript and device proof identical. Checked the low-level extractor now retains each distinct terminal string.

Two positive controls were executed in the same stdin process: one 480-byte/10ms part with a missing transcript final at drain, followed by its legitimate first final and an identical duplicate; then two complete parts with exact proof and ordered transcript combination. Result:

```text
AssistantAudioPartCompleted BLOCKED
AssistantTranscriptDelta BLOCKED
manifest contradiction BLOCKED
wire final transcript preserved BEFORE
wire final transcript preserved CONTRADICTORY
late first final POSITIVE; duplicate no new evidence
multipart consistent POSITIVE ONE TWO 20.0
```

Both actionable findings are resolved in this focused recheck. This is helper/transport-field evidence only; it does not replace the owning agents' canonical integration tests, Core history checks or the parent's native/bridge review. No provider or hardware session was used.
