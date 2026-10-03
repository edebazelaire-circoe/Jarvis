# Slice execution order

Start with **00-project-manager**. No implementation Slice may be dispatched until Slice 00 returns `READY`.

Suggested dependency order:

- [x] `00-project-manager` — Project Manager readiness gate
- [x] `01-board-workspace-contract` — Canonical Board workspace memory contract (depends on: 00-project-manager) — implémentée, QA approuvée
- [x] `02-board-memory-persistence` — Board memory persistence and safe filesystem access (depends on: 01-board-workspace-contract) — implémentée, QA approuvée
- [x] `03-board-sessioncontext-hydration` — Board activation and SessionContext hydration (depends on: 02-board-memory-persistence) — implémentée, QA approuvée
- [x] `04-workspace-inspection-api` — Workspace relationship and inspection API (depends on: 02-board-memory-persistence, 03-board-sessioncontext-hydration) — implémentée, QA approuvée
- [x] `05-memory-mutations-analysis` — Board memory mutations and explicit historical analysis (depends on: 02-board-memory-persistence, 04-workspace-inspection-api) — implémentée, QA approuvée
- [x] `06-jarvis-workspace-mcp` — Dedicated jarvis-workspace MCP server (depends on: 04-workspace-inspection-api, 05-memory-mutations-analysis) — implémentée, QA approuvée
- [x] `07-deep-workspace-manager-ui` — Deep Sessions & Boards Manager UI (depends on: 04-workspace-inspection-api, 05-memory-mutations-analysis) — implémentée, QA approuvée ; **HV-WS-UI-001 en attente** (`09-e2e-rollout/HUMAN-CHECKS.md`)
- [x] `08-quick-board-browser` — Quick Board browser and switcher (depends on: 01-board-workspace-contract, 06-jarvis-workspace-mcp) — implémentée, QA approuvée ; **HV-WS-UI-002 en attente** (`09-e2e-rollout/HUMAN-CHECKS.md`)
- [x] `09-e2e-rollout` — End-to-end validation, migration and rollout (depends on: 03-board-sessioncontext-hydration, 06-jarvis-workspace-mcp, 07-deep-workspace-manager-ui, 08-quick-board-browser) — implémentée (`EVIDENCE.md`), QA à faire ; validation humaine après fusion

**État de la tâche (2026-10-03) : implémentée, en attente de validation humaine** (HV-WS-UI-001, HV-WS-UI-002). Pas encore terminée.
