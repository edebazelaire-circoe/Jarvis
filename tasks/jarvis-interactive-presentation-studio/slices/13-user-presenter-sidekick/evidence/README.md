# Slice 13: evidence index

Produced by `python -m tests.replay.presentation_studio_cue_replay <this dir>` (then redacted with `tests/replay/evidence_privacy.py`: home, user name, repo path,
temp root and secrets are derived at run time and replaced). `tests/integration/test_presentation_studio_cue_replay.py::test_the_committed_evidence_is_clean_and_small`
re-sweeps this directory and checks that no word of the scripted utterances is in it.

| File | What |
| --- | --- |
| `rehearsal-summary.json` | the seven scripted steps (what was wanted, counter deltas, Core position, follower state), final state, Core call counts, follower status |
| `core-calls.json` | every call the follower made to Core (`armed` pulls with generation and count; `report` with the three keys and the answer) |
| `voice-trace.json` | the Voice journal rows of `presentation.studio.*` and `ambient.*`: ids, codes, rule, offsets, counts. No text |
| `core-trace.json` | the Core diagnostics rows `core.presentation_studio.*` of the same run |
| `trace-analysis.md` | the `agent-trace-analysis` findings, what was and was not run live |

**What was run live: nothing.** No OpenAI transcription, no microphone, no real room. The lane, the follower and the Core playback service are the real code; the transcription and the
HTTP hop are replaced (see `trace-analysis.md`). The live check is the Human recipe in `docs/OPERATIONS.md` (*Suivi des cues à la voix*).

Reproducibility: re-running the command gives byte-identical `core-calls.json`, `rehearsal-summary.json` and `voice-trace.json`; `core-trace.json` differs only in the
random ids of the Presentation, Variant and Score (`pst_...`, `psv_...`, `psr_...`), which are generated per run. The rework of Slice 13 (stricter anchoring, `jarvis` anywhere, address marker) did not change the story of the rehearsal.
