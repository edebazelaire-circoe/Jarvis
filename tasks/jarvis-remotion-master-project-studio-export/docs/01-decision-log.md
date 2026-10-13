# Decision log

## Locked decisions

### D1 — Remotion is the base architecture

Jarvis must build on native Remotion concepts rather than substitute a custom video engine where Remotion already provides the correct abstraction.

### D2 — The current scene-based system stays intact during A+B

The recent playback/Studio work is valuable and currently stable enough to preserve. This task adds a master-project path; it does not retire the current Variants multi-Player sequencer, scene-level source versions, scene-level Studio round trip, presenter runtime or existing compatibility readers.

### D3 — Scope is A + B, not C

A = one master Remotion project/composition per compatible variant.  
B = native Studio opens that project and the renderer exports the whole variant.  
C = replacing the playback runtime and/or making the project workspace canonical is explicitly deferred.

### D4 — Existing scene pins remain canonical writes for now

Presentation/Variant/Scene identity, immutable prefab/source versions and source-edit CAS remain the durable model. The master project is derived. A voice edit publishes a new scene source version; the master project then changes because its inputs changed.

### D5 — Voice re-edit is a first-class acceptance path

The user does not require direct live editing of arbitrary master-project files in Remotion Studio in this task. It must be possible to create a video and later request source/content/design changes by voice/text without opening Studio.

### D6 — Remotion Studio becomes project-level for the primary presentation workflow

The primary **Remotion Studio** entrypoint for a Presentation Variant must open a workspace containing the whole compatible variant/master composition. The current scene-only Studio path is kept as compatibility/legacy functionality, not silently deleted.

### D7 — Whole-video export is real Remotion rendering

A full presentation export must render the generated master Composition through the existing guarded Remotion renderer and Artifact pipeline. It must not be implemented as hidden concatenation of pre-rendered scene clips while being presented as an editable master project.

### D8 — No new narrowing of valid scene behavior

This task does not widen the existing trust policy, but the master assembler must not add accidental restrictions beyond it. Existing valid scene audio/video/media and source behavior must remain valid when the variant is declared master-compatible.

### D9 — Failure must be explicit

If a legacy variant cannot be represented faithfully (for example incompatible video configs or conflicting public assets), return a typed incompatibility and preserve the existing path. No silent rewriting or fallback.

### D10 — Isolated implementation and validation

Develop/test in a separate task branch/worktree and isolated Jarvis data root/runtime ports. Automated QA must not manipulate the user's live Core or data.

## Provisional technical choices — audit before locking

These are recommendations, not user-approved immutable details. Slice 01/02 may refine them while preserving D1-D10.

### P1 — Common video-spec compatibility envelope

Preferred first implementation: a master project is ready only when all scenes can run under one shared width/height/fps contract without source rewriting. New voice-authored videos should intentionally generate scenes with that common spec. Historical mixed-spec variants keep the existing scene-based path.

Reason: `Sequence`/`Series` can shift local frame time, but child scene code reading `useVideoConfig()` observes the master composition config. Pretending mixed FPS/dimensions are transparent risks semantic changes.

### P2 — Public asset collision policy

Preferred first implementation: merge scene `public/**` paths only when colliding paths contain identical bytes. Different bytes at the same public path make the master project incompatible with a typed reason. Do not rewrite `staticFile()` strings automatically.

### P3 — Additive render scope

Prefer an explicit low-level whole-variant/master scope rather than changing the existing multi-scene-without-`scene_id` error out from under old callers. User-facing presentation export may default to the master scope when `ready`.

### P4 — One Studio process, multiple target kinds

Preserve the current one-process-per-profile lifecycle. Extend targeting/provider semantics so the process can serve either the existing scene workspace or a variant master workspace. Do not run a second parallel Remotion Studio unless a fresh audit proves it necessary.

### P5 — Generated orchestration files are not publishable source yet

Master `Root`/orchestration/shared generated files should be treated as generated or non-canonical in A+B. Arbitrary changes in that workspace must never silently overwrite scene pins or Presentation documents. Direct project-authoring round trip is future work.
