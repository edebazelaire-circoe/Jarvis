# Chronological decisions, hypotheses and questions


## Locked user decisions


1. The old floating viewer shown in screenshot 1 must go, rather than being improved in parallel with another viewer.
2. Retain screenshot-2 Variants as the visual starting point but conduct thorough UI/hierarchy/control cleanup.
3. Provide separate, selectable **Remotion Studio** and **Variants** destinations. Neither is a duplicate video engine.
4. Prioritize reliable native Remotion behavior over inventing Jarvis-specific media logic; continuous playback must honor authored durations.
5. Seeking and play/pause across visual control surfaces must synchronize; next scene starts at its intended opening frame.
6. Redundant button banks and time-per-slide cutting are not acceptable in ordinary video playback.
7. Jarvis should deliver at least the baseline freedom and practical effectiveness of normal Claude+Remotion from the terminal.
8. Future left rail layout must wait for the user's explicit sketch.


## Existing repository decisions to preserve unless separately approved


- Remotion is normal default; Slidecar is an explicitly human-enabled experiment; no automatic fallback (`tasks/jarvis-remotion-presentation-integration/README.md`, `docs/presentation-engine.md`).
- Canonical Presentation, Variant, Prefab, Board and Artifact ownership must not bifurcate (`docs/presentation-studio.md`, `docs/presentation-artifacts.md`, `docs/remotion-source.md`).
- Player isolation and native Studio security are separate concerns (`docs/remotion-isolation.md`, `docs/remotion-studio.md`).
- Presenter roles and speech are owned by score/runtime, not by the Player (`docs/presentation-studio.md`, `docs/presentation-mode.md`).


## Technical hypotheses, require proof


- Discontinuity may be caused by a per-scene remount/loading gap, stale local frame, conflicting clocks or scheduling; cannot diagnose from screenshot alone.
- Visible '30s' and '8s' likely come from Remotion composition and Jarvis score/autoplay; inspect before asserting exact owners.
- A single multi-scene Remotion composition with Sequence/Series/TransitionSeries may simplify playback; do not bypass per-scene isolation without architectural and security review.
- The native Studio is currently an optional managed process, while edits in its working copy are staged aside instead of automatically persisted (`docs/remotion-studio.md`); this must be reconciled before promising normal authoring.


## Open or gated decisions


- Exact geometry/visual hierarchy of left rail: user sketch pending; not a blocker for P0.
- Should video end hold final frame or stop at final frame? propose hold; confirm using product contract if divergence arises.
- Trust/approval boundary for running new third-party packages or agent-generated source outside sandbox requires a documented secure path.
- Remotion license/production terms: confirm separately from implementation before shipping if relevant (`docs/remotion-integration-release.md`).