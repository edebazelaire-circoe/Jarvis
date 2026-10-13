# Issue 01 — Pre-existing loader bypass in the per-scene isolation guard (fixed in this task)

Found by Slice 04 critical QA (2026-10-13). At `d101d887` the per-source isolation guard (`jarvis/domain/remotion_isolation.py`, `dynamic_import`)
was textual and could be bypassed with `require(...)`, an aliased `require` (`const r = require; r.context(...)`) or `require.context(...)`.
QA proved with the pinned webpack 5.105 + esbuild-loader that a JSON file outside the workspace ended up in the bundle. This affected the
**existing scene lane** (scene Studio, scene render, preview), not only the new master root.

Decision by agent 0: fixed at the per-source guard so both lanes are protected (`S4: rework` 54ed51bb → cherry-picked 324e028c): `require` token
in any form, `.context(`, `import.meta`, `module.hot`, `__webpack_*`, `__non_webpack_require__`, ASCII `\u` escapes (`identifier_escape`).

Accepted narrowing (D8 reviewed): the guard is textual, so the word `require` and ASCII `\uXXXX` escapes are refused even inside text/strings. A
repository-wide grep found no fixture, sample or authoring path using them. Authoring guidance (Slice 07) should mention it so an agent writing an
English sentence with "require" rephrases or uses a non-ASCII-safe wording. A tokenizer-aware rule is possible future work.
