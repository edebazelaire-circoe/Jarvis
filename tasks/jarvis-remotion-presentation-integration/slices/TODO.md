# Slices

Execute `00-project-manager` first. This task is **queued**, not authorized for coding while the original branch remains active. PM may split/reorder Slices after final-head audit.

- [ ] `00-project-manager` - Completion/readiness and orchestration gate
- [ ] `01-final-branch-conformance` - Full branch conformance and gap proof (depends on: 00-project-manager)
- [ ] `02-engine-and-compatibility-contract` - Engine semantics and forced-default policy (depends on: 01-final-branch-conformance)
- [ ] `03-local-plugin-host-contract` - Installable local capability vs remote MCP plugins (depends on: 01-final-branch-conformance)
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
- [ ] `14-source-edit-hmr-and-agents` - Subagent structural edits and safe hot reload (depends on: 06-remotion-source-isolation, 11-remotion-studio-process-ui, 13-remotion-controls-bridge)
- [ ] `15-remotion-one-shot-authoring` - High-quality generation with storyboard and DA (depends on: 09-live-assets-and-freeze, 11-remotion-studio-process-ui, 13-remotion-controls-bridge)
- [ ] `16-render-export-and-derived-artifacts` - MP4, stills, PDF and exact origin links (depends on: 07-source-artifact-model-contract, 09-live-assets-and-freeze, 12-score-to-remotion-runtime)
- [ ] `17-prefab-shop-semantic-catalog` - Unified reusable components and marketplace UX (depends on: 01-final-branch-conformance, 02-engine-and-compatibility-contract)
- [ ] `18-upstream-template-import` - External Remotion and Opus assets with provenance (depends on: 17-prefab-shop-semantic-catalog, 06-remotion-source-isolation, 09-live-assets-and-freeze)
- [ ] `19-promotion-pins-and-upgrades` - Explicit prefab save and version trial branching (depends on: 17-prefab-shop-semantic-catalog, 18-upstream-template-import, 13-remotion-controls-bridge)
- [ ] `20-engine-ui-policy-and-slidecar` - Remotion default, Slidecar experiment and no fallback (depends on: 02-engine-and-compatibility-contract, 10-remotion-player-host, 11-remotion-studio-process-ui, 13-remotion-controls-bridge)
- [ ] `21-voice-tools-and-toolbrain` - Voice commands, authoring agents and tool ownership (depends on: 12-score-to-remotion-runtime, 14-source-edit-hmr-and-agents, 19-promotion-pins-and-upgrades, 20-engine-ui-policy-and-slidecar)
- [ ] `22-end-to-end-release` - QA, migration, performance and final Human sign-off (depends on: 08-artifact-board-registration, 12-score-to-remotion-runtime, 14-source-edit-hmr-and-agents, 15-remotion-one-shot-authoring, 16-render-export-and-derived-artifacts, 19-promotion-pins-and-upgrades, 20-engine-ui-policy-and-slidecar, 21-voice-tools-and-toolbrain)
