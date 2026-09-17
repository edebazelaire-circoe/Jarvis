# Issue — timeline layout cost on very large sessions and phone overlap visibility

Found by Slice 05 re-QA (2026-09-16). Not blocking; follow-up candidates.

## Layout cost roughly tripled by the readability redesign

Huge session (5 000 events, one open span), headless Chrome at 1440×900:

| Metric | Before redesign | After |
|---|---|---|
| Max layout | 12.7 ms | 38.6 ms |
| Idle re-layout while a span is open (1/s) | 8.4 ms | 23.8 ms |
| Scroll max frame | 17.3 ms | 33 ms |
| Scroll p95 | 17 ms | 17.1 ms |

2 400-event session max layout 2.7 → 12 ms. With an open sub-agent this is roughly one dropped frame per second on huge sessions. Candidates: cache per-entry measured heights by (entry, column width), only re-layout the clusters touched by the growing open span, skip the 1 s tick re-layout when the open span is outside the viewport.

## Phone: overlaps need horizontal scroll

Need-weighted lane widths make the 390 px canvas 1 108 px wide (≈1.2 lanes visible). Readable, but cross-lane overlaps are not visible at a glance on a phone. Candidate: a compact "overview" mode on narrow screens (lanes at minimum width, text in the drawer).
