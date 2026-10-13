# Documentation levels

Reference levels: L0 implicit/ambiguous; L1 named/discoverable; L2 dedicated behavior contract; L3 reusable implementation/schema/validator/conformance gate.

| Concept | Current state at planning reference | Required by this task | Notes |
| --- | ---: | ---: | --- |
| Scene Remotion source/version | L3 | L3 | Keep existing source manifest, guards, versioning and edit gate. |
| Scene-level Remotion Studio workspace | L3 | L3 | Preserve as compatibility functionality; new docs must clearly distinguish it from master Studio. |
| Variants composition clock / multi-Player sequencing | L3 | L3 | Keep implementation; rename/describe accurately so it is not confused with a real master Remotion Composition. |
| Variant master Remotion project | L0 | L3 | New canonical contract + pure planner + conformance tests. |
| Master composition video spec | L0/L1 | L3 | Must define compatibility, dimensions, fps, durations, props/data and refusal reasons. |
| Master public-asset merge | L0 | L3 | Deterministic plan, collision rules, tests. |
| Remotion Studio master target | L0 | L3 | Dedicated target semantics, lifecycle and unpublished-edit policy. |
| Whole-variant native Remotion export | L0 (explicitly unsupported) | L3 | New render scope/plan, Artifact semantics, real-render tests. |
| Voice creation -> master-ready video | L1/L2 via current native authoring | L3 | Update authoring contract/tool guidance and real traces. |
| Voice scene re-edit -> refreshed master | L1 | L3 | Existing source-edit semantics plus master invalidation/readiness proof. |
| Arbitrary master workspace publish-back | L0 | L1 (explicit non-goal) | Name it as deferred; do not accidentally imply support. |
| Master Player replacing Variants sequencer | L0 | L1 (future phase C) | Explicitly deferred. |

Slice 02 (2026-10-13): every row whose current state was L0 or L1 above (master project, master spec, public-asset merge, Studio master target, whole-variant export, voice creation and re-edit) is now **L2** in the canonical contract `docs/remotion-master-project.md`, pinned by `tests/unit/test_remotion_master_project_docs.py`; the two non-goal rows (master publish-back, master Player) are L1 there, named as deferred. L3 is reached by Slices 03-08.

## Documentation files expected to change

At minimum refresh canonical repository docs after implementation, based on actual owner audit:

- `docs/presentation-studio.md`
- `docs/remotion-studio.md`
- `docs/remotion-render.md`
- `docs/remotion-source.md` where project-vs-scene terminology changes
- `docs/presentation-engine.md` if it owns presentation engine semantics
- `docs/ARCHITECTURE.md`
- `docs/OPERATIONS.md` for workspace/process/export operations
- `docs/mcp/tool-contract.md` if whole-video export or inspection tool contracts change

Do not leave the old sentence "one scene per export" or "Studio serves only the selected scene" unqualified after the master path is implemented. Preserve historical/compatibility behavior explicitly where it still exists.
