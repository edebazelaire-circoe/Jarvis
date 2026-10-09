# Issue 02 - Local capability host: wiring and UI deliberately deferred (opened by Slice 03, 2026-10-09)

Slice 03 delivers the contract and a host skeleton (`docs/local-capabilities.md`, `jarvis/core/local_capability_host.py`). Two things are intentionally not done there; neither is a regression of Slice 03.

| # | Deferred work | Owner | Why it matters |
| --- | --- | --- | --- |
| a | **Control Center one-card UI** for local capabilities: show a local capability next to remote MCP plugins as one card, reading `family` / `transport` / `status` of `public_view`, without sharing routes or fields with `McpPlugin`. | Slice 04 (first capability) / Slice 20 (engine UI) | Until then a local capability has no user-visible card; the data contract is frozen, the JS is not written. |
| b | **Host not wired into Core**: no `LocalCapabilityHost` is built in `jarvis/app.py`, no Core routes expose it, and `reconcile()` is **not called at Core startup**. | **Slice 04 must do it** (composition root, token-authenticated routes, `reconcile()` once at startup, real `CapabilityRunner`) | Without `reconcile`, an `installing` state left by a Core crash stays displayed as `installing`; operations treat it as interrupted, but nothing shows it until the next operation. |

Blocks Remotion? (a) no for Slice 04 acceptance by machine tests, yes for any claim of a user-visible install flow; (b) yes for Slice 04.
