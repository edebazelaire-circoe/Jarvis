# Issue 02 — Master render failure attribution takes the first marker (low)

Slice 06 QA. Errors that pass through the per-scene `SceneBoundary` are attributed to the right scene even when a scene's message contains the
marker text. A scene that calls `cancelRender` directly, or throws outside render, can be attributed to the wrong scene id. Only the error label
is affected; no data or trust consequence. Left as is in A+B.
