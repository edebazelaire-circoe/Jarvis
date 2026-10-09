# Issue 02 - Local capability host: wiring and UI deliberately deferred (opened by Slice 03, 2026-10-09)

Slice 03 delivers the contract and a host skeleton (`docs/local-capabilities.md`, `jarvis/core/local_capability_host.py`). Two things are intentionally not done there; neither is a regression of Slice 03.

| # | Deferred work | Owner | Why it matters |
| --- | --- | --- | --- |
| a | **Control Center one-card UI** for local capabilities: show a local capability next to remote MCP plugins as one card, reading `family` / `transport` / `status` of `public_view`, without sharing routes or fields with `McpPlugin`. | Slice 04 (first capability) / Slice 20 (engine UI) | Until then a local capability has no user-visible card; the data contract is frozen, the JS is not written. |
| b | **Host not wired into Core**: no `LocalCapabilityHost` is built in `jarvis/app.py`, no Core routes expose it, and `reconcile()` is **not called at Core startup**. | **Slice 04 must do it** (composition root, token-authenticated routes, `reconcile()` once at startup, real `CapabilityRunner`) | Without `reconcile`, an `installing` state left by a Core crash stays displayed as `installing`; operations treat it as interrupted, but nothing shows it until the next operation. |

Blocks Remotion? (a) no for Slice 04 acceptance by machine tests, yes for any claim of a user-visible install flow; (b) yes for Slice 04.


## Update by Slice 04 (2026-10-09)

- **(b) resolved.** `JarvisCoreApplication` now builds a `LocalCapabilityHost` (`jarvis/core/v2_app.py`), calls `reconcile()` once in `start()` (it installs, starts and stops nothing) and cancels in-flight installs in `stop()`; `jarvis/app.py` injects the real `NodeCapabilityRunner`; token-authenticated routes `/v1/local-capabilities*` exist and are documented (`docs/local-capabilities.md` §7, `docs/remotion-runtime.md` §7), with `tests/unit/test_local_capability_routes.py` as guard. Evidence: `docs/07-evidence-index.md` Slice 04.
- **(a) still open.** No Control Center card or `/api/...` relay exists; the explicit install action is the Core route recipe in `docs/OPERATIONS.md`. Owner unchanged: Slice 11 (Studio process UI) / Slice 20. A user-visible install flow cannot be claimed until then.

## Update by Slice 05 (2026-10-09)

- **(c) new, deferred to Slice 10.** `RemotionCompiler` (`jarvis/adapters/remotion_compiler.py`, factory `build_remotion_compiler(host, store, runner)`) exists and is proven against a real install, but **nothing in Core builds it yet**: there is no route that serves `host.js` / `scene.js` / `public/**`, and `v2_app.py` / `app.py` do not hold a compiler. That is the Player host's job (Slice 10; contract in `docs/remotion-source.md` section 8). Not a regression of Slice 05: no caller exists to wire it to.

## Update by Slice 11 (2026-10-09)

- **(a) partly resolved.** The Control Center now has a Remotion card (`jarvis/runtime/control_center_remotion_studio.js`, top of the "Plugins externes" tab) showing the local capability status and the optional Studio, relayed by six `/api/local-capabilities/remotion*` routes (`docs/remotion-studio.md` section 8). It deliberately does **not** relay install/repair/uninstall (still an explicit Core action, `docs/OPERATIONS.md`) and is not a generic card for any local capability: a second capability or an install button is still Slice 20's decision.
