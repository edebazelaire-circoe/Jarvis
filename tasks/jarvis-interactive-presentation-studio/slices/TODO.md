# Slices

Execute in this order subject to Slice 00 re-planning and explicit dependency readiness.

- [x] `00-project-manager` - Project Manager Readiness Gate
- [x] `01-contract-audit` - Presentation Artifact Integration Contract Audit (depends on: 00-project-manager)
- [ ] `01a-prefab-capacity-for-studio` - Prefab Library Capacity for Studio Scene Sources (depends on: 01-contract-audit)
- [ ] `01c-presenter-speech-authority` - Speech Authority for the Jarvis Presenter (depends on: 01-contract-audit)
- [x] `02-presentation-artifact-contract` - Presentation Artifact Domain Contract (depends on: 01-contract-audit)
- [x] `03-fullscreen-borderless-surface` - Generic Fullscreen Borderless Surface (depends on: 01-contract-audit)
- [x] `04-presentation-scene-control-contract` - Presentation Scene Module and Control Contract (depends on: 02-presentation-artifact-contract, 01-contract-audit)
- [ ] `05-semantic-edit-api` - Semantic Presentation Edit API (depends on: 04-presentation-scene-control-contract)
- [ ] `06-scene-hot-reload` - Scene-Local Hot Reload and State Preservation (depends on: 05-semantic-edit-api, 01a-prefab-capacity-for-studio)
- [ ] `07-edit-inspector-ui` - Dynamic Presentation Edit Inspector (depends on: 05-semantic-edit-api, 06-scene-hot-reload)
- [ ] `08-autosave-undo` - Continuous Autosave and Bounded Undo/Redo (depends on: 02-presentation-artifact-contract, 05-semantic-edit-api)
- [ ] `09-art-direction-profile` - Art Direction Profile and Source Derivation (depends on: 02-presentation-artifact-contract, 01-contract-audit)
- [ ] `10-presentation-score-cues` - Presentation Score, Tracks, Cues and Timing (depends on: 02-presentation-artifact-contract, 01-contract-audit)
- [ ] `11-authoring-planner-first-draft` - Authoring Planner and First-Draft Quality (depends on: 09-art-direction-profile, 10-presentation-score-cues, 04-presentation-scene-control-contract)
- [ ] `12-playback-runtime` - Presentation Playback Runtime State Machine (depends on: 03-fullscreen-borderless-surface, 10-presentation-score-cues, 02-presentation-artifact-contract)
- [ ] `13-user-presenter-sidekick` - User Presenter Sidekick and Armed Cue Following (depends on: 12-playback-runtime, 10-presentation-score-cues, 01-contract-audit)
- [ ] `14-jarvis-presenter-locked-sequences` - Jarvis Presenter and Locked AV Sequences (depends on: 12-playback-runtime, 10-presentation-score-cues, 01c-presenter-speech-authority)
- [ ] `15-rehearsal-workflow` - Rehearsal, Recall and Script Refinement (depends on: 12-playback-runtime, 13-user-presenter-sidekick, 14-jarvis-presenter-locked-sequences, 05-semantic-edit-api, 01c-presenter-speech-authority)
- [ ] `16-presentation-variants-domain` - Presentation Variant Graph and Branch Operations (depends on: 02-presentation-artifact-contract, 08-autosave-undo)
- [ ] `17-scene-local-variants` - Scene-Local Variants (depends on: 04-presentation-scene-control-contract, 16-presentation-variants-domain)
- [ ] `18-variant-explorer-ui` - Fullscreen Variant Explorer (depends on: 16-presentation-variants-domain, 17-scene-local-variants, 03-fullscreen-borderless-surface)
- [ ] `19-variant-compare-mix` - Variant Comparison and Semantic Branch Composition (depends on: 18-variant-explorer-ui, 16-presentation-variants-domain, 10-presentation-score-cues, 09-art-direction-profile)
- [ ] `20-template-prefab-promotion` - Template and Prefab Promotion (depends on: 17-scene-local-variants, 19-variant-compare-mix, 04-presentation-scene-control-contract)
- [ ] `21-agent-voice-operations` - Agent, Voice and UI Operations for Presentation Studio (depends on: 05-semantic-edit-api, 12-playback-runtime, 16-presentation-variants-domain, 17-scene-local-variants, 19-variant-compare-mix, 20-template-prefab-promotion)
- [ ] `22-end-to-end-hardening` - End-to-End Hardening and Release Gates (depends on: 07-edit-inspector-ui, 08-autosave-undo, 11-authoring-planner-first-draft, 13-user-presenter-sidekick, 14-jarvis-presenter-locked-sequences, 15-rehearsal-workflow, 18-variant-explorer-ui, 19-variant-compare-mix, 20-template-prefab-promotion, 21-agent-voice-operations)
