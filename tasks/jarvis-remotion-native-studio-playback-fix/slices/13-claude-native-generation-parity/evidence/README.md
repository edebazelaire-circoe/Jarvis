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

## Rework

Critical-tier QA returned REWORK; branch `fix/rnsp-s13-rework` from c228872e. Commits: `53e4250d` (S12: fix, I6), `6b7548de` (code,
tests, docs), `3ab4a3b7` (I1 privacy), this README.

| Item | Fix | Test |
| --- | --- | --- |
| B1 | `authoring` row in the brief table; `authored_scenes_recorded`, `authored_scene_released`, `authored_scenes_dropped`, `authored_release_unchecked` in the edit diagnostics; route count 5 -> 6 in `test_presentation_render_docs.py` (the only test changed for staleness: `/render/preview` is a real sixth route) | the three docs files |
| B2 | `BrowserSlot`: exports always before a waiting preview; `MAX_WAITING_PREVIEWS = 1`, any other refused at once `presentation_render_preview_busy` (429); wait for the browser bounded at `PREVIEW_SLOT_WAIT_S = 60` (same code); render 150 s; a caller that left (`request.transport` absent or closing) cancels the preview while waiting and every 0.25 s while rendering (process stopped through the cancel event); client timeout 230 s; MCP sentence "attends, puis redemande un seul aperçu"; docs state these bounds | `test_presentation_studio_native_loop.py`: 30 at once -> 1 renders, 1 waits, 28 busy; deadline; export queued behind a waiting preview goes first; caller gone while waiting and while rendering. `test_presentation_render_routes.py`: real HTTP client timeout -> render stopped, browser freed |
| B3 | Remotion Studio `open` (start or reuse) and `sync` await scene listeners; `v2_app` wires `release_authored_for_pin`: the permission of every scene pinning that exact version, in its variant, ends. A `brain` source edit is refused 409 `presentation_studio_scene_edited_in_remotion` while the Studio workspace holds unpublished files of that scene's source (unlistable = held), request or not. Playbook sentence and docs say exactly that | native loop: open -> refused, other scene kept; unpublished edits -> refused (with and without request, unlistable), user edit allowed; scene not open / no workspace -> allowed. `test_remotion_studio.py`: listeners on open, reuse, sync, failing listener journaled; `workspace_base`. `test_remotion_studio_publish_routes.py`: real Core wiring |
| P1 | permission keyed by (presentation, variant, scene) | `test_the_permission_is_bound_to_its_variant` (by key and by request_id) |
| P2 | `/render/preview` in `test_every_route_needs_the_core_token` | same |
| I1 | README text replaced in the 4 traces by `<redacted: IGuard README, 10469 bytes>` (1 line each, all JSONL lines parse); `BENCHMARK.md` corrected; history untouched | privacy test: SHA-256 of 8 distinctive lines, JSON strings and `cat -n` prefixes unescaped (finds 16 hits in the pre-rework trace), plus a self-check |
| I2 | agent permissions in their own store (`MAX_AUTHORED_SCENES = 96`, expired first, then oldest agent one, traced); never in the user's ring of 64, not in `pending_source_requests` | 3 decks of 48 -> the user's request still pending, 96 kept, oldest dropped |
| I3 | claim admits without renewing; `renew_authored_scene` only when a brain write stood | refused attempt at 29 min 55 s, then +10 s -> expired |
| I5 | with a `scene_id`, `where` = `SCENE_CARD_PATH` (that scene's button, no rail) | `test_remotion_mcp_tools.py`, `test_variants_remotion_studio_docs.py` |
| I6 | `test_remotion_import_docs` names the one allowed reuse (`from jarvis.domain.remotion_import import specifiers` in `remotion_studio_workspace.py`, nothing else); `docs/remotion-import.md` says so | `test_remotion_import_docs.py` |

Mutants (applied one at a time, each killed by the named test): M7 presentation + scene match (any variant); B2 no busy refusal; B2 no
wait deadline; B2 route never reports the caller gone; B2 service ignores the caller while rendering; B2 waiting preview before queued
exports; B3 open does not tell the listeners; B3 no refusal over unpublished edits; B3 release ignores the pin; I2 agent permissions also
in the user's ring; I3 every admitted attempt renews. 11/11 killed.

Regression gate (one file per process): 160 files, 3 855 passed, 1 skipped, 2 failed, both the known inherited ones
(`test_brain_capability_parity` `ui_intent_publish`, one in `test_brain_delegation`). MCP catalog: no declared surface changed (budget
unchanged); the two new refusal sentences live in `presentation_studio_mcp_support.py`. Out of scope, untouched: I4, the guard's
`Frame`/`Link` false positive.
