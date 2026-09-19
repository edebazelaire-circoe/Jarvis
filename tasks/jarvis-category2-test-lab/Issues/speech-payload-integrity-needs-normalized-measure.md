# `speech.payload_integrity` needs a normalized producer measure

Found during the second Slice 03 QA (2026-09-17). This is a producer signal defect, not a Test Lab regression.

`jarvis/core/voice_state.py` (around lines 148-152) emits `voice.state.spoken_diverged` when the provider's confirmed transcript of a completed playback is not exactly equal, as a string, to the intended text. `voice.state.diverged` is the same test on the generated text. Punctuation, casing, number formatting and ordinary transcription noise all trigger it. On the live `runtime/trace.jsonl`, it flags about 40 % of normal, complete playbacks.

Consequence for the Test Lab:

- the DiagnosticBundle counts these lines on speech items (`spoken_divergences`, `state_divergences`, `spoken_diverged_at`) but emits no anomaly finding (PM decision, second Slice 03 rework; see `docs/testlab.md`, "Why no payload divergence rule");
- the Slice 12 seed diagnostic `speech.payload_integrity` must not use this signal as its metric or assertion.

Suggested fix, owned by the voice state producer, not by the Test Lab: emit, with the divergence line or instead of it, a normalized measure computed in process and carrying no text. For example:

- a normalized similarity or word error rate between intended and confirmed text (after case folding, punctuation and whitespace normalization, and number normalization);
- the intended and confirmed lengths (characters and words);
- the `speech_id` and the playback status.

With it, a Slice 12 assertion can threshold the similarity (for example word error rate below 0.2 on a completed playback), and the bundle can map it as a speech measure without ever copying text.

## Slice 12 decision (2026-09-19): still open, and still not the Test Lab's to close

`speech.payload_integrity` ships at v1 with the harness measure only, exactly as Slice 04
wrote it, and Slice 12 did not bump it. Nothing changed on the producer side, so an
assertion on a normalized similarity would have no signal to threshold: the version bump
belongs with the producer change, in one reviewable step, not before it.

What that costs today, stated plainly: the seed proves the SCHEDULER delivers what was
scripted, and says nothing about whether what Jarvis actually spoke matched what he meant
to say. The bundle still counts `spoken_divergences` and `state_divergences` on speech
items, so the evidence is visible in a captured session; it is just not a verdict.

Owner unchanged: `jarvis/core/voice_state.py`.
