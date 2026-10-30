# Audited implementation context

Read ../00-project-manager/READINESS.md for source evidence, routing fallback, boundaries and QA tiers. Canonical architecture starts at docs/ARCHITECTURE.md (repository root), docs/scene-selection-batch.md, docs/scene-model.md, docs/mission-history.md, docs/agent-orchestration.md and docs/chat.md. Existing source is authoritative over planning-time path guesses. No duplicate geometry, prefab renderer, fullscreen state machine, status owner or communication bus.

Environment: work only in assigned isolated worktree, use C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe for pytest with working directory set to worktree (pyproject pythonpath=. ensures local imports). Node available. Tests foreground, small focused batches; no full suite before S06. Do not launch/stop user's runtime. Isolated ControlCenter harnesses and own data/ports are permitted. Read CLAUDE.md. Load caveman, coding-guideline, ponytail, error-handling; frontend additionally impeccable. Implementer reports in IMPLEMENTATION.md; independent reviewer writes qa/. Prefix implementation commits S<n>: with Slice number. Do not commit other Slice files.

Exact lifecycle: remote folder current; final Human acceptance pending. No merge to main/push main/cleanup local handoff.

## Published predecessor seams (verify final IMPLEMENTATION.md at dispatch)
- S02 emits bubbling document event `jarvis:scene-open`, detail `{objectId, ids, source:'keyboard'|'double-click'}`. No scene writes. Normal mouse single-click no longer opens context actions; Bare Hands selected-click retained. Enter and double-click ignore interactive descendants.
- S01 selected wire: `layout_selection`, `selection:{ids:[...]}`, `targets:[{object_id,geometry,expected_geometry?}]`, optional `pin:true`. Every target compared or none. Stale `geometry_changed` refuses whole batch. Geometry-only undo preserves current pin and nongeometry fields.
- Wire64KiB remains authoritative over domain512 targets. Even short IDs may exceed budget for512 compared targets. Preflight UTF-8 JSON byte length (TextEncoder), report oversize without chunking/partial writes, never silently record an undo that cannot be sent. Typical24-target compare fits.
- Canonical Stop route is POST `/api/jobs/cancel` with `{source,external_id}`; only source job supported, CLI children must have disabled/explained Stop.
- Modifier clarification: initial Shift locks gesture-start aspect; toggling mid-gesture rebases current drawn box and locks its ratio for the next segment, preserving pointer continuity.
- Organization must respect visual orbit/field transform: `drawnBox(id)` returns current layout placement; stored geometry is not necessarily where the object is drawn. Existing hold desk and `JarvisSceneLayout.holdStart/holdPlace` own conversion/freeze/rebase. Use these seams for visual ordering/anchor and commit conversion, no second inverse-transform math. Final runtime must include orbit enabled as well as fixed fixture layouts, so one group does not jump when organized.


## Convergence guardrails from source/runtime review
- Native dialog is a top-layer surface: visible async errors/loading/counters/action outcomes belong inside it; global toasts/confirmation can be behind it.
- S03 optional PrefabHost.onEscape must be bound for iframe providers so actual focused sandbox frames can close viewer. S03 bridge owns validation; no manual window message listener in S05.
- PrefabHost.pause intentionally tears down iframe under canonical LRU policy; provider internals may reset on resume. Native text/markdown view DOM can preserve scrolling. Do not add a new suspension engine or claim opaque iframe state survives teardown.
- Canonical chat prefill should preserve an existing draft (append/explicit handling), never auto-send or silently switch Voice channel. Open current chat, retain normal lock/refusal behavior and target identity.
- Stop result is request/actual outcome, not an assumed terminal status. Reuse existing stop semantics; show pending motion/counter/deadline and true refusal inside viewer.
- Dimension-matching actions must respect nonresizable representations; disable/explain unsupported mixed selections rather than silently mutating meaningless displayed sizes.
