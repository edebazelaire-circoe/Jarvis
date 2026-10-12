# Slice 13 evidence — parity benchmark and native authoring

- `../BENCHMARK.md`: prompts, affordances, results per run, comparison, gates kept/dropped, the `remotion_studio` check.
- `trace-analysis.md`: the agent-trace analysis of the real runs (both sides).
- `runs/index.json`: one line per run; `runs/<run>/metrics.json` (tool calls by tool, refusals with their words, frames read, elapsed,
  tokens, cost); `runs/<run>/meta.json` (brief, model, flags, decks); raw redacted traces (`stream.jsonl` direct; `cli/*.jsonl` and
  `jarvis-trace.jsonl` Jarvis); `runs/<run>/sources/` (the TSX produced: direct `src/`, Jarvis `deck<n>/<scene>/src/`).
- `blind/<topic>/deck-A|deck-B/01..08.jpg`: the final deck of each side, 8 frames at the same relative moments of the whole timeline,
  960x540 JPEG, side hidden. Key: `blind/key.json` (do not open before judging).
- `harness/`: `bench.py` (start, ask, wait, collect, stop; detached processes polled in bounded chunks), `run_cc_strict.py` (Control
  Center with `--strict-mcp-config`, no browser tab), `briefs.json`, `smoke_native.py` (no-model check of assemble → write → 2 previews),
  `trace_tools.py`, `frames.py`, `collect_evidence.py` (redaction targets derived at runtime).

## HV-RFX-13-01 — blinded side-by-side review (Human)

1. Open `blind/jarvis/deck-A` and `deck-B` side by side, then `blind/iguard/deck-A` and `deck-B`. Judge each pair on: faithfulness to the
   brief (4 scenes, dark, one accent, animated diagrams rather than bullet lists, short French text, nothing invented), hierarchy and
   legibility, layout quality, visual consistency across scenes.
2. Write your verdict per topic (A better / B better / equal, with one reason) before opening `blind/key.json`.
3. Optionally play the decks: the direct projects are plain Remotion projects (`runs/d-*/sources` into a Remotion project, `npx remotion
   studio`); the Jarvis decks' sources are in `runs/jn4/sources` and `runs/ji2/sources` (one composition per scene).

The frames are stills: motion quality is only partly visible. Quality parity is NOT claimed by this Slice.

## Reproduce (never against the live Jarvis)

```
set BENCH_ROOT=<short scratch folder>          (a long one breaks Chrome's profile path, see BENCHMARK § 7)
python harness/bench.py direct-start d-x jarvis --model sonnet --budget 3 ; python harness/bench.py wait d-x
python harness/bench.py jarvis-up j-x --model sonnet ; python harness/bench.py jarvis-ask j-x jarvis ; python harness/bench.py wait j-x
python harness/bench.py jarvis-collect j-x ; python harness/frames.py jarvis j-x <presentation_id> ; python harness/bench.py jarvis-down j-x
```
