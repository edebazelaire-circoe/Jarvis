# Overview: what this fix must achieve


## User objective


A fresh, nontechnical user should be able to ask Jarvis for a great Remotion deck, inspect/edit it in native Remotion Studio, manage variants in a single purpose-built Jarvis Variants view, then press play and watch the entire authored composition smoothly. Jarvis voice and presenter modes are optional enhancement lanes, not prerequisites for video playback.


## Scope


- Full intent/code reconciliation, reproducible defect investigation and regression harness.
- Canonical media timeline, correct frame-0 transitions, non-discontinuous full-deck playback and global/scrub sync.
- Consolidate/remigrate controls in the current Variants view and retire floating legacy viewer.
- Expose native Remotion Studio and Variants as first-class choices without creating duplicate product code.
- Provide safe native TSX authoring and a real Studio edits -> persisted source/variant round trip.
- Compare direct Claude+Remotion terminal authoring against Jarvis and remove artificial creative limitations.
- Add rendered-frame checks, real-browser tests and Human qualitative gates.


## Explicit non-goals


- No from-scratch Remotion replacement, second video engine, second timeline editor or speculative rail geometry.
- No wholesale removal of presenter sidekick/cues/score, prefabs, Boards, links, exports or Slidecar experimental support.
- No unsandboxed execution or unrestricted filesystem/network access granted silently to untrusted generated code.
- No claim that code compilation establishes quality; no silent fallback to a different media engine.


## Priority


P0: make 9-scene deck start, seek, transition, finish correctly; one clock; no cut at 8s; remove duplicate viewing behavior. P1: Variants controls, native Studio navigation, agent-native source workflow. P2: creative/visual QA, cleanup, compatibility/release. Slices are dependency-ordered, not permission to indefinitely postpone P0.