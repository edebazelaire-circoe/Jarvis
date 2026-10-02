# Slice execution order

Start with **00-project-manager**. No implementation Slice may be dispatched until Slice 00 returns `READY`.

Suggested dependency order:

- [ ] `00-project-manager` — Project Manager readiness gate
- [ ] `01-board-workspace-contract` — Canonical Board workspace memory contract (depends on: 00-project-manager)
- [ ] `02-board-memory-persistence` — Board memory persistence and safe filesystem access (depends on: 01-board-workspace-contract)
- [ ] `03-board-sessioncontext-hydration` — Board activation and SessionContext hydration (depends on: 02-board-memory-persistence)
- [ ] `04-workspace-inspection-api` — Workspace relationship and inspection API (depends on: 02-board-memory-persistence, 03-board-sessioncontext-hydration)
- [ ] `05-memory-mutations-analysis` — Board memory mutations and explicit historical analysis (depends on: 02-board-memory-persistence, 04-workspace-inspection-api)
- [ ] `06-jarvis-workspace-mcp` — Dedicated jarvis-workspace MCP server (depends on: 04-workspace-inspection-api, 05-memory-mutations-analysis)
- [ ] `07-deep-workspace-manager-ui` — Deep Sessions & Boards Manager UI (depends on: 04-workspace-inspection-api, 05-memory-mutations-analysis)
- [ ] `08-quick-board-browser` — Quick Board browser and switcher (depends on: 01-board-workspace-contract, 06-jarvis-workspace-mcp)
- [ ] `09-e2e-rollout` — End-to-end validation, migration and rollout (depends on: 03-board-sessioncontext-hydration, 06-jarvis-workspace-mcp, 07-deep-workspace-manager-ui, 08-quick-board-browser)
