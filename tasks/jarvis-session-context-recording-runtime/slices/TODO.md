# Execution order

Start with **Slice 00 only**. It is the Project Manager readiness gate. Do not dispatch implementation work until it records `READY`.

| Slice | Goal | Depends on |
| --- | --- | --- |
| 00 | Blind audit, reconcile handoff, resolve Task Types and readiness | none |
| 01 | Canonical Session + SessionContext contract | 00 |
| 02 | SQLite persistence + Context workspace filesystem | 01 |
| 03 | Resume/reconstruction + active Context agent hydration | 02 |
| 04 | Generic Artifact registry + canonical Session activity ledger | 02 |
| 05 | Brain-independent capture runtime foundation | 03, 04 |
| 06 | Durable audio recording + live transcript artifacts | 05 |
| 07 | Generic desktop screenshot + screen recording | 05 |
| 08 | Live Context memory/enrichment + fast catch-up | 06, 07 |
| 09 | Capture/Context API, MCP facade and retrieval | 04, 05, 06, 07, 08 |
| 10 | Recording controls in existing floating left toolbar | 09 |
| 11 | E2E recovery, regression, documentation and rollout | 03, 04, 06, 07, 08, 09, 10 |

## Dispatch rules

- Before every Slice, the Project Manager performs a targeted freshness check against current `main` for that Slice's owners and dependencies.
- Every coding Slice loads `/caveman` and `/coding-guideline` before implementation.
- Slice 10 also loads `/impeccable` and uses a Claude Work Agent when supported by routing.
- Baseline QA for every implemented Slice: `qa-verification`.
- Add `code-review` for code changes.
- Add `runtime-validation` for user-visible/runtime behavior.
- Add `agent-trace-analysis` for agent prompts, tools, routing, modules, MCP, Context hydration/enrichment, or agent runtime.
- Human validation runs only after relevant machine validation is clean.
- A regression introduced by the current Slice is blocking and may not be deferred to `Issues/`.
