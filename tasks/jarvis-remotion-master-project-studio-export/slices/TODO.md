# Slices — dependency-ordered implementation plan

Start with `00-project-manager`. No implementation Slice is considered complete from this planning handoff. A current Workspace Task Type must be resolved before every Work Agent assignment.

- [ ] `00-project-manager` — Readiness, independent audit and execution control
- [ ] `01-current-state-and-compatibility-audit` — Fresh code/runtime audit and master-compatibility risk map (depends on: `00-project-manager`)
- [ ] `02-master-project-contract` — Lock Level-2 master project, compatibility, Studio and render contracts (depends on: `01-current-state-and-compatibility-audit`)
- [ ] `03-master-project-planner` — Pure deterministic master-project plan/status and shared compatibility codes (depends on: `02-master-project-contract`)
- [ ] `04-master-workspace-materialization` — Materialize/compile the full variant Remotion project (depends on: `03-master-project-planner`)
- [ ] `05-remotion-studio-master-project` — Open the whole variant in managed native Remotion Studio (depends on: `04-master-workspace-materialization`)
- [ ] `06-whole-variant-render-export` — Render/export the frozen master composition as one video Artifact (depends on: `04-master-workspace-materialization`)
- [ ] `07-voice-generation-and-reedit` — Make voice/native authoring reliably produce and refresh master-ready videos (depends on: `03-master-project-planner`, `06-whole-variant-render-export`)
- [ ] `08-variants-master-entrypoints` — Minimal project-level Studio/export/status wiring in Variants (depends on: `05-remotion-studio-master-project`, `06-whole-variant-render-export`, `07-voice-generation-and-reedit`)
- [ ] `09-release-and-human-acceptance` — Integrated old-path regression + real master Studio/export/voice release gate (depends on: `05-remotion-studio-master-project`, `06-whole-variant-render-export`, `07-voice-generation-and-reedit`, `08-variants-master-entrypoints`)
