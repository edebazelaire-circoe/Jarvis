# Exact browser comparisons — completed facts, graph still open

All allocated cases below executed once per listed revision/group, sequential
Chrome only. Baseline is exact clean `c0858a80`; current is `a0f7105c` with
product equal to accepted F2 `dc0c5036`. Each `pending-*-run.json` records exact
nodes, revision, command/PIDs/timestamps, retained synthetic temp root; matching
logs/JUnit/captures are beside it. No whole-file/browser-suite repeat, model,
physical recording or user runtime. The runner refuses overwriting a group.

| Exact case/group | Baseline outcome | Current outcome | Classification limit |
|---|---|---|---|
| Dense graph200%/forced colours |1passed38.25s|1failed28.97s, original line438 boardNone|Not a proven baseline failure; remains open for bounded click diagnostic|
| Architecture two-tab/legacy IDs and canvas/Core/subagents |2passed60.06s|2passed56.34s|Both non-reproductions preserved; not relabeled baseline failures|
| Variant run recording chips1280×720,1920×1032,600×800 |3failed39.63s|Original full-gate3 reds retained|All baseline failures at original line338, same overlap controls/message: proven pre-existing mechanism|
| Settings voice-model comparison1366×768 |Not allocated|1passed30.16s|Current bootstrap retry succeeds; original pre-navigation CDP failure retained separately|

## Fixture/provider audit

Graph uses the original served-page/JS fetch fixture and actual role/relation
modules. Architecture uses its original isolated Control Center/settings
fixture and CDP driver; no CLI model turn is made. Variant runs use actual
isolated Core/SQLite/HTTP, FakeCaptureSources and fake transcription, not real
camera/screen/audio capture or live Remotion. Only PNGs were copied from
retained owned temp roots; SQLite or user data was not committed.

## Proven baseline recording-chip overlap

Every exact baseline viewport reproduces:

```text
test_variants_run_browser.py:338
assert rec['under'] == []
AssertionError: ('une puce couvre une commande du Studio', ['Plein écran', 'Fermer Variantes'])
```

These are actual geometry assertions after browser startup, not port/timeouts.
The untouched test/harness, indicator/Studio rank/placement path and fixture
facts match the earlier source pretriage. Recommend PM classify these three
specific full-gate failures as proven pre-existing/unrelated, with their original
red and separate baseline red retained. No product fix/ignore was introduced.

## Architecture and bootstrap limits

Source pretriage bounds Architecture's original failures to an initial fixed
1100ms settle/button-exists predicate and a fixed400ms CLI-field hydration
sample; relevant Settings owners/registry/render functions are unchanged.
Passing baseline/current here does not establish the original timing cause.
PM subsequently authorized a separate test-only readiness correction
`bddc1c95`; its review/reverification is separate from these exact original
case comparisons. The shared harness/OPEN and product are not changed by that
correction. The1366 bootstrap retry proves actual current operation but does
not erase its original before-navigation infrastructure failure.

## Graph follow-up scope

The exact current graph test re-fails at boardNone after its unchanged native
click and≈8053ms board wait. `--showlocals` preserved those values, but nested
raw results remain pytest-truncated. The initial valid passive diagnostic
prefix later opened the board and therefore did not reproduce the miss. Its
actual event targets/rect/panel/grip data and setup correction are reported in
`graph-click-prefix-review.md`; no waiver or root-cause claim follows from it.
PM allocated one minimal full-original-case capture next, preserving existing
CDP roundtrips/event sequence and retaining raw stdout before assertions.
