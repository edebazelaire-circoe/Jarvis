# The library preview briefly keeps the old and the new frame side by side.

Found by: Slice 09 replay of the S08 rework probe (2026-10-03). Status: open — minor, harmless.

When the PFB library switches the preview from one prefab to another, the outgoing preview iframe is still in the
slot next to the incoming one for up to ~1.5 s (teardown window), so the next focusable element after the first
frame is the second frame. A user tabbing in that instant would land on an empty frame. `rw_probe.mjs` step
`rwAfterFrame` reads the focus order 300 ms after the swap and fails on it (2/2 runs); a read after 1.5 s gives
`pfbStageClose`. Product files unchanged since `5f7b552`. Options: hide (`inert`, `display:none`) a departing
preview frame at once, or make the probe wait for a single iframe.
