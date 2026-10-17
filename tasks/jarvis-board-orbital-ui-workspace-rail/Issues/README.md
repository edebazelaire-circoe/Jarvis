# Issues

This folder is for residual issues discovered during implementation that are **not regressions introduced by this task** and are safe to separate from the active Slice.

A regression caused by a Slice blocks that Slice and may not be parked here.

## Open issues (Slice 10 release check, 2026-10-17)

| Issue | Owner | Impact | Regression? |
| --- | --- | --- | --- |
| [bh-left-reveal-gesture.md](bh-left-reveal-gesture.md) | Bare Hands recognizer, Human product decision | none today: the wheel opens with the hand pointer on the anchor, as with the mouse | no (deferred by decision O02) |
| [capture-physical-device-busy.md](capture-physical-device-busy.md) | Core capture | a second recording of the same screen or microphone under another token name (brain or direct HTTP); the wheel itself never offers it | no (rule in Core since before `57f28a74`) |
