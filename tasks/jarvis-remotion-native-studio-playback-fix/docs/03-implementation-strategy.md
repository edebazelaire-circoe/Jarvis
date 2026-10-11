# Delivery sequence and compatibility strategy


1. **Investigate before editing.** Slice 00 readiness, Slice 01 intent/current architecture, Slice 02 UX contract, Slice 03 reproducible red tests.
2. **Fix the engine, not the skin.** Slice 04 canonical frame map, Slice 05 continuous composition, Slice 06 seek/lifecycle, Slice 07 presenter/cue coexistence, Slice 08 audio/fullscreen.
3. **Remove misleading surfaces.** Slice 09 deletes legacy floating viewer, Slice 10 rationalizes Variants transport, Slice 11 exposes both native Studio and Variants.
4. **Restore creative freedom.** Slice 12 native source/edit round trip, Slice 13 Claude baseline and agent flow.
5. **Verify and retire debt.** Slice 14 frame inspection, Slice 15 cleanup/migration, Slice 16 integrated QA and Human acceptance.


## Baseline and rollback


- Pin actual HEAD and test baseline at PM start; prior source inspection reference: `d2332e61c0e384d1e75d7d31a81efb730254eb6e` (not a verified working copy).
- Use isolated data root, test library/prefabs and dedicated localhost ports for all tests. Never restart/scrub a user's live presentation.
- Before deleting viewer/runtime code, preserve an inventory of unique capabilities and clients. Record migration compatibility and a rollback to previous version.
- Keep stable presentation/variant IDs, source digests, Board/Artifact backlinks and persisted document versions. No bulk conversion without migration tests.
- Reconcile simultaneous active handoffs/branches at the start of every Slice; block conflicting writes until integrated.


## Risk register


- Frame clock vs score clock: preserve presenter semantics while fixing video duration.
- Sandbox per scene vs contiguous composition: performance and isolation tradeoff require dedicated analysis.
- Native Studio run safety: unsandboxed source/package execution requires explicit authorization and a trusted workspace design.
- Browser autoplay gesture/audio: reliable behavior must comply with Chrome policies.
- UI archaeology: separate old viewer may be coupled to voice/MCP commands; never delete without route migration.
- Creative parity: user judges outcome by quality, not schema green; final Human review required.


## No premature polish


No redesign of left rail pending user sketch. Minor integration/legibility fixes are allowed to remove blocker, but final rail proportions, icons and organization must not be guessed.