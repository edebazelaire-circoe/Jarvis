# Slices

Execute `00-project-manager` first. This task is **queued**, not authorized for coding while the original branch remains active. PM may split/reorder Slices after final-head audit.

> **Plan amendments proposed by Slice 01 (2026-10-09, base `main` de7b9c59), pending PM approval.** Details and evidence: `docs/06-branch-compliance-audit.md` (sections "Redundant, overlapping or re-scoped plan entries" and "Integration risks for Remotion"); each affected `SLICE.md` ends with a "Plan amendment after Slice 01" section.
> The original studio branch is merged in `main`; its Slidecar foundation (variants, explorer, compare/mix, template promotion, 12-tool MCP surface, authoring planner) exists. No Slice is deleted; these shrink or move:
> - **Dependency changes applied below**: 14 no longer depends on 11 (depends on 10); 15 depends on 09, 13, 14 (not 11); 17 also depends on 05; 21 also depends on 11; 22 also depends on 11. Slice 11 (Studio window) becomes an optional parallel Slice after 10.
> - **Shrunk (reuse, do not rebuild)**: 13 (controls already exist), 15 (authoring planner/gate exist), 17 (library UI and `family`/`tags` exist; the work is a manifest contract version), 19 (explicit promotion exists; keep Remotion-aware promotion, newer-version notice and upgrade-in-variant), 21 (agent surface exists; tool budget is nearly full).
> - **Split / moved**: 20 (policy tests move to 02; 20 keeps the Human toggle and legacy-engine-identity migration).
> - **Decisions to take earlier**: 02 (where the engine identity lives; engine of legacy presentations and of agent-assembled scenes), 05 (Remotion source as a prefab-bundle kind vs separate tree; compile/bundle contract), 07 (catalog link vs Artifact for the mutable source), 19 (promotion publishes one library prefab per distinct scene source today).
> - Slice 10 needs a compile/bundle source (added to 04/05); the old plan had none.

- [x] `00-project-manager` - Completion/readiness and orchestration gate
- [x] `01-final-branch-conformance` - Full branch conformance and gap proof (depends on: 00-project-manager)
- [x] `02-engine-and-compatibility-contract` - Engine semantics and forced-default policy (depends on: 01-final-branch-conformance)
- [x] `03-local-plugin-host-contract` - Installable local capability vs remote MCP plugins (depends on: 01-final-branch-conformance)
- [ ] `04-remotion-one-time-provisioning` - Remotion environment installation and lifecycle (depends on: 03-local-plugin-host-contract)
- [ ] `05-remotion-project-source-contract` - Source workspace and module layout (depends on: 02-engine-and-compatibility-contract, 04-remotion-one-time-provisioning)
- [ ] `06-remotion-source-isolation` - Local runtime security, capabilities and bounds (depends on: 04-remotion-one-time-provisioning, 05-remotion-project-source-contract)
- [ ] `07-source-artifact-model-contract` - Editable source parent vs terminal Artifacts (depends on: 01-final-branch-conformance, 02-engine-and-compatibility-contract)
- [ ] `08-artifact-board-registration` - Board discoverability and derived provenance (depends on: 07-source-artifact-model-contract, 05-remotion-project-source-contract)
- [ ] `09-live-assets-and-freeze` - Live Board references and immutable freeze (depends on: 05-remotion-project-source-contract, 06-remotion-source-isolation, 08-artifact-board-registration)
- [ ] `10-remotion-player-host` - Embed Remotion Player into Jarvis scene fullscreen (depends on: 05-remotion-project-source-contract, 06-remotion-source-isolation, 02-engine-and-compatibility-contract)
- [ ] `11-remotion-studio-process-ui` - Optional Studio launch, hot preview server (depends on: 04-remotion-one-time-provisioning, 05-remotion-project-source-contract, 06-remotion-source-isolation)
- [ ] `12-score-to-remotion-runtime` - Cue, roles and timeline bridge (depends on: 02-engine-and-compatibility-contract, 10-remotion-player-host)
- [ ] `13-remotion-controls-bridge` - Shared typed variables and fast edits (depends on: 02-engine-and-compatibility-contract, 10-remotion-player-host)
- [ ] `14-source-edit-hmr-and-agents` - Subagent structural edits and safe hot reload (depends on: 06-remotion-source-isolation, 10-remotion-player-host, 13-remotion-controls-bridge)
- [ ] `15-remotion-one-shot-authoring` - High-quality generation with storyboard and DA (depends on: 09-live-assets-and-freeze, 13-remotion-controls-bridge, 14-source-edit-hmr-and-agents)
- [ ] `16-render-export-and-derived-artifacts` - MP4, stills, PDF and exact origin links (depends on: 07-source-artifact-model-contract, 09-live-assets-and-freeze, 12-score-to-remotion-runtime)
- [ ] `17-prefab-shop-semantic-catalog` - Unified reusable components and marketplace UX (depends on: 01-final-branch-conformance, 02-engine-and-compatibility-contract, 05-remotion-project-source-contract)
- [ ] `18-upstream-template-import` - External Remotion and Opus assets with provenance (depends on: 17-prefab-shop-semantic-catalog, 06-remotion-source-isolation, 09-live-assets-and-freeze)
- [ ] `19-promotion-pins-and-upgrades` - Explicit prefab save and version trial branching (depends on: 17-prefab-shop-semantic-catalog, 18-upstream-template-import, 13-remotion-controls-bridge)
- [ ] `20-engine-ui-policy-and-slidecar` - Remotion default, Slidecar experiment and no fallback (depends on: 02-engine-and-compatibility-contract, 10-remotion-player-host, 11-remotion-studio-process-ui, 13-remotion-controls-bridge)
- [ ] `21-voice-tools-and-toolbrain` - Voice commands, authoring agents and tool ownership (depends on: 11-remotion-studio-process-ui, 12-score-to-remotion-runtime, 14-source-edit-hmr-and-agents, 19-promotion-pins-and-upgrades, 20-engine-ui-policy-and-slidecar)
- [ ] `22-end-to-end-release` - QA, migration, performance and final Human sign-off (depends on: 08-artifact-board-registration, 11-remotion-studio-process-ui, 12-score-to-remotion-runtime, 14-source-edit-hmr-and-agents, 15-remotion-one-shot-authoring, 16-render-export-and-derived-artifacts, 19-promotion-pins-and-upgrades, 20-engine-ui-policy-and-slidecar, 21-voice-tools-and-toolbrain)
