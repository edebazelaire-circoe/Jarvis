# Screenshot-based observable defects


## Screenshot 1 (unwanted floating viewer, image `evidence/01-unwanted-floating-viewer.png`)


- Chrome shows Jarvis dark Board/constellation as the background.
- Narrow presentation rail at upper-left plus left tool dock.
- A separate floating `STUDIO_STAGE` window appears around center-right with a Remotion-like play bar.
- A separate presentation control box occupies bottom-left with Prev/Pause/Next, Slide, Tout, Fullscreen, Stop and cue warning.
- The user rejects this presentation display as unnecessary and wants it removed rather than improved in parallel. The Board/agent graph should not dominate video playback.


## Screenshot 2 (Variants as retained visual base, image `evidence/02-variants-screen-base.png`)


- Full-page dark Variants interface with left rail, evolution/variant tree on the left and a large preview image/video centered.
- Inner video timeline at roughly 2.6/30s; global lower transport around 2s/8s, potentially conflicting authorities.
- Buttons above/below player include scene prev/next, 'Jouer cette slide', 'Tout jouer', separate prev/seek/play groups, duration-per-slide, replay and fullscreen; visually redundant.
- Nine scenes referenced, thumbnail strip (scene 6 selected) and variant actions under preview. User wants to KEEP this visual base while consolidating controls and restoring timing correctness.


## Required defect reports


A. Full playback sometimes does not start or continue.
B. Visible boundary flash/stutter.
C. Next scene can begin mid-animation rather than frame zero.
D. Scrubbing inner bar does not affect outer timeline.
E. Global per-slide dwell setting may cut animated scene before authored duration.
F. Too many overlapping controls and disconnected states.
G. Agent-created presentations worse/slower to achieve than direct console Claude+Remotion.
H. Native Remotion Studio is not treated as first-class primary creation environment.


Do not attribute a root cause based only on these images. Slice 03 must prove exact mechanism and identify modules.