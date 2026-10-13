# Implementation strategy

## Rollout rule: additive first

Do not start by replacing current working code. Build and prove the master path beside it.

### Phase 1 — audit and contract

Confirm current owners, exact schemas, render/studio routes, real runtime assumptions and historical fixture behavior. Lock a small compatibility envelope and typed reasons. No product code dispatch until Slice 00 says READY.

### Phase 2 — pure planner

Implement a deterministic pure master-project plan/status. This is the shared decision point. Do not let Studio, renderer and UI each invent their own compatibility checks.

### Phase 3 — project materialization

Generate a normal Remotion project workspace from exact pinned scene source versions. Prove compilation against the real pinned Remotion runtime before wiring Studio or export.

### Phase 4 — native Studio

Extend the managed Studio target/provider path so a variant master project can be materialized and opened. Keep current scene target behavior and process/security rules intact.

### Phase 5 — whole-video render/export

Use the frozen snapshot and new master planner to render the whole composition through the existing guarded renderer. Keep scene render behavior stable.

### Phase 6 — voice regeneration

Make the existing native authoring/scene source edit loop intentionally produce master-compatible videos and surface master readiness. A voice edit should repin the scene, change the master key and produce an updated full export without requiring Studio.

### Phase 7 — minimum UI

Make the presentation-level Studio/export semantics visible in Variants. No broad layout redesign. Do not expose two equally prominent competing "Remotion Studio" meanings.

### Phase 8 — release

Run old-path regression gates plus real master Studio/export/voice journeys on isolated infrastructure. Only then consider the task complete.

## Migration and persistence

Default plan: no SQLite migration and no rewrite of Presentation/Variant documents for A+B unless Slice 01 proves a small schema field is unavoidable. Prefer deriving master readiness from the current exact pins and source manifests.

If a persistent master spec is proposed, the PM must prove why derivation is insufficient, define an upgrade path, and either add a dedicated prerequisite Slice or escalate a Human decision before implementation.

## Legacy compatibility

Historical presentations remain byte-stable when merely opened/played. A master-incompatible variant must continue to open/play with the current runtime. Do not "upgrade" scene code or pins just to make it master-ready.

## Unpublished Studio work

The existing scene Studio has a mature unpublished-change contract. Master Studio needs an equally explicit policy. For this task, the safest default is:

- generated orchestration files are regenerated, not canonical;
- user modifications are detected and never silently replaced;
- switching/rebuilding with modifications requires an explicit discard/set-aside action;
- A+B provides no generic publish-back of arbitrary master-project edits;
- scene-level edits can still be published through the existing scene round trip if retained.

## Rollback

Because the old path remains intact, rollback should primarily mean disabling/removing the master entrypoints and reverting additive code. No presentation/source data should require destructive downgrade.

The release Slice must document exact files/state created by master Studio/runtime workspaces and how to preserve/set aside user modifications before rollback.
