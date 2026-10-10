# Issue 03 - Prefab library page overflows horizontally at 360 px (found by Slice 17, 2026-10-09)

At a 360 px viewport `#prefabLibrary` has `scrollWidth` 397 for `clientWidth` 360. Measured in real Chrome with the Slice 17 filter row hidden (`display:none`): still 397, so it is **not introduced by Slice 17**. The elements past the edge are the pre-existing `header.tl-bar` (status text and the close button `#pfbClose`) and the first row of `.pfb-tools` (search field and `#pfbFamily`). At 390 px nothing overflows (guarded by `test_prefab_catalog_browser.py`).

Owner: a later UI polish pass of the prefab library (not a Remotion blocker). Fix direction: let `.tl-bar` wrap and give `.pfb-tools` first row `grid-template-columns:minmax(0,1fr)` below ~400 px.
