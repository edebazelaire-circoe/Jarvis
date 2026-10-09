# Slice 13: trace analysis (agent-trace-analysis)

Reviewer: the implementer (Slice 13). QA re-runs it independently. No product code was changed by this analysis.

## Scenario and trace source

A rehearsed run, seven French utterances, through the real Voice path and the real Core playback service, in one process
(`python -m tests.replay.presentation_studio_cue_replay <dir>`; asserted by `tests/integration/test_presentation_studio_cue_replay.py`).

| Real | Not real |
| --- | --- |
| fake capture device -> `AudioCaptureHub` -> segmenter -> `AmbientIngestionLane` (tail, analysis, consumer slot) -> `PresentationComposition.build` -> `PresentationStudioCueFollower` | the microphone |
| `PresentationStudioPlaybackService` with the real scene service, edit service, file store and stage window; armed set, generation, report ledger, rate limiter | the OpenAI transcription (a scripted transcriber returns the next sentence) |
| the real explicit-address path for the one sentence addressed to Jarvis (realtime bridge, `decide_turn_authority`, brain turn intake double) | the HTTP hop between Voice and Core (an in-process adapter calls the methods the routes call) |
| the runtime journal (`trace.jsonl` shape) and the Core diagnostics sink | Voice's mode observer and Core's mode service are separate objects driven by hand |

**Not run live.** No OpenAI ambient stack, no real room, no real Control Center, no `follower` band (Slice 12 rework). The Human recipe is `docs/OPERATIONS.md`, *Suivi des cues à la voix*.

## Execution path (from `rehearsal-summary.json`, `core-calls.json`, `voice-trace.json`)

| Step | Said (never recorded; kind only) | Follower | Core |
| --- | --- | --- | --- |
| 1 | room chatter | `no_match` | no call |
| 2 | a quotation of the cue phrase ("il a dit ...") | `vetoed` (quoted) | no call |
| 3 | "Jarvis, <cue phrase>" (also heard by the realtime model) | `preempted_address`, state `paused_address` | no report; the sentence became ONE brain turn through the explicit path |
| 4 | the cue phrase as a stage direction | fire, 1 report | `fired`, position 1 -> 2, stage patched; armed set now empty (generation 2) |
| 5 | the same phrase again | `no_armed` | no call. Then the user pressed next by hand: position 3, cue 2 armed (generation 3) |
| 6 | the second phrase as a question | `vetoed` | no call |
| 7 | the second phrase as a stage direction | fire, 1 report | `fired`, position 3 -> 4; stage window shows the last scene |

Totals: 7 utterances, 2 reports, 3 armed-set pulls, 4 `armed.changed` bus messages, 0 failures, 0 refusals, 0 handler errors. Final follower state `following`.

## Model, prompt, tool observations

There is **no model call, no prompt and no tool call** in this feature, by construction: the follower is deterministic code between the ambient lane and one typed Core
report. The trace therefore has nothing to say about prompts, tokens or cost. What replaces them as the thing to inspect is the *call* list: the follower made exactly the two
Core calls it is allowed (`presentation_studio_playback_armed`, `presentation_studio_report_cue`), and the report keys are `run_id`, `generation`, `cue_id` in every row.

## Findings

| Severity | Finding | Evidence | Disposition |
| --- | --- | --- | --- |
| FLAGGED | The existing explicit-address path writes the addressed sentence (`voice.transcript`, `voice.brain_turn_submitted` rows). Not ambient, not changed, but it means the word "no utterance text in the trace" is true for **ambient** speech only | `test_no_ambient_utterance_text_reaches_any_trace_row` isolates exactly these two kinds and asserts they carry only step 3 | pre-existing behaviour of the bridge; stated in the docs |
| OPTIMIZATION (fixed) | First version pulled the armed set twice at start (supervisor + bus connect) | the first replay showed pulls `(gen 1)`, `(gen 1)` | `_on_connected` skips the pull when one is running or just happened; the test now asserts no `(generation, count)` is ever pulled twice |
| FLAGGED | Bus messages coalesce under the 1 s pull throttle: 4 messages -> 3 pulls | `core-calls.json`, summary `core_calls` | intended; a stale held set is safe (Core refuses `stale_generation`, and the held cue is already marked fired) |
| FLAGGED | While nothing is armed the follower still pulls every 5 s (`idle_poll_s`) so Core can show `follower: connected` and a missed bus message costs at most 5 s | design, `docs/presentation-studio.md` | one local GET per 5 s in a PRESENTATION session; not measured over a long run |
| MINOR (known) | Step 4: the follower's state shows `unarmed` right after the fire because Core's next item arms nothing; a human reading only the follower state would not see "the cue worked" | `rehearsal-summary.json` step 4 | the proof is the Core position and the `cue_fired` line |

No BLOCKER, no MAJOR.

## Unnecessary or redundant calls

None in the final trace: reports only for fires (2 for 2), no report for the 5 other utterances, no repeated pull of the same `(generation, count)`, no call while a decision was a veto.

## Error, retry, fallback

Not exercised in this trace (clean run). The failure paths are covered at unit level with the real follower and a scripted Core: Core unreachable (backoff 1 s to 30 s, one warning, one recovery line),
unreadable armed set (phrase never quoted), authority lapse, stale generation / run / expiry / not armed (set dropped, one throttled re-pull), `rate_limited` (2 s block, visible state), report timeout, bus stream lost or absent,
handler failure, unreadable address probes (fail closed). Missing here: a forced failure in a *live* process and the row in the Error Logs viewer (the follower writes Voice diagnostics, not an HTTP error path).

## Missing trace evidence

Latency from end of speech to the avancée (needs the real transcription); behaviour with two real voices; the Voice-to-Core HTTP latency and a real token expiry; the Control Center band (`follower`); a long idle run (cost of the 5 s poll).

## Optimization opportunities and future improvements

1. Speaker identity on the ambient lane would remove the main residual risk (a bystander saying the phrase) and let the anchoring rule be relaxed.
2. Replace the 5 s idle poll by a Core message when a run starts (Slice 12 could publish `armed.changed` on start even with an empty set).
3. A calibration pass on a real transcript corpus (the 121-case set was written with the rules in mind; the 3.8 % false positives are all the "phrase opens an ordinary sentence" weak spot).
4. The semantic labels of a cue are carried and never matched; a classifier would need its own authority decision.
