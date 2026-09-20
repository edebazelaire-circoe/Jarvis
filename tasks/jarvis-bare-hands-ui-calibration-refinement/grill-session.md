# Reconstructed UI review / grill session — Bare Hands refinement

> Reconstructed faithfully from the active 2026-09-20 conversation because this host does not export the exact transcript into the task folder. This file records only decisions and corrections that were actually made.

## Why this refinement exists

The first Bare Hands implementation successfully delivered substantial runtime behavior, but the user found the UI hierarchy wrong: frequent controls were buried under Settings/Experimental, and the calibration flow looked like a small modal wizard rather than an immersive guided interface.

The user supplied screenshots of the current Control Center, the current Tools section, diagnostic/gesture text, current calibration modals, and a real Jarvis note/frame. Several visual concepts were generated during the discussion; the preferred direction is a full-screen blurred Jarvis background with large calm text above and a central schematic hand/exercise area.

## Main Bare Hands control

Bare Hands must be visible as its own main-screen button, not hidden under Settings.

The button is square, slightly larger than the small top action buttons, uses a hand icon, and lives as a first-class HUD control near the upper-left status area shown in the review.

The final visual state decision is:

- OFF: dim/grey, clearly inactive;
- SLEEP: ordinary Jarvis blue, no extra emphasis;
- ACTIVE: stronger electric blue and a light glow/surround highlight;
- the earlier idea of green ACTIVE was explicitly withdrawn.

Normal click does not cycle blindly and does not open a conventional text dropdown. It opens a compact visual chooser showing the three variants of the same control so the user can directly choose OFF, SLEEP, or ACTIVE.

The control must always reflect reality. C-wake, voice activation, inactivity returning to sleep, and any other path must update the button.

Right click opens: Settings, Calibration, Help/Gestures, Diagnostics. Activation is not repeated there. Tutorial is removed.

## Tools

The user rejected tools living in Settings. Tools are session actions that need one-click access.

Create a fixed vertical tool palette on the left side, visually like a small Paint/Photoshop toolbar. For this refinement, keep it simple: fixed vertical, not movable/dockable/horizontal yet.

Do not invent new tools. Move the current implemented V1 tools only: Pointer, Pan/Main, Selection (`pointer`, `pan`, `select`).

## Help / Gestures and Diagnostics

The raw, dense gesture text in Settings should become a small visual help card/window reachable from the Bare Hands right-click menu. It should be spaced, icon-driven, and show simple hand-position diagrams rather than a wall of debug text.

Diagnostics is also acceptable as a right-click quick action. Reuse the existing recorder/replay behavior; the correction is access and presentation.

## Tutorial correction

The earlier task separated Calibration and Tutorial. The user reversed that decision in this review: **the separate tutorial is removed**. Calibration now also teaches the user the interactions it measures/validates.

Existing interaction behavior that was already defined in the previous task is not to be reopened in this handoff.

## Calibration visual correction

The current centered card/modal is explicitly rejected.

Desired visual direction:

- full-screen translucent dark blur over the existing Jarvis scene;
- slightly less dead-black and more atmospheric than the current modal background;
- no central card/window boundary;
- large step title and short sentence placed higher on the screen;
- center reserved for the actual calibration interaction;
- progress/loading remains useful;
- simple virtual/robotic/schematic hand, less anatomically precise than the generated references;
- green may indicate a successfully recognized gesture, while normal guidance remains blue.

For C pose, the visual must make clear that thumb and index form the C. For primary pinch, clearly show thumb-index closing. For secondary pinch, use the same grammar but thumb-middle. For target calibration, the hand must visibly pinch the target; it must not look like a pointing-finger interaction.

## Step timing correction

The current flow begins timing/measuring while the user is still reading. That is rejected.

Each step first presents its title, short instruction, and demonstration for a few seconds. After that minimum reading period, it becomes ready.

For hand/posture exercises, nothing should burn down while the user remains inactive with hands away. When the user begins engaging with Bare Hands, the test begins.

For the target step, after the reading delay the targets appear so the user has something to aim at. For window manipulation, the practice window appears after the reading delay and the sub-test begins on a valid capture.

## Final calibration sequence

1. Main au repos.
2. Posture de réveil: C formed by thumb and index.
3. Pincement pouce-index.
4. Pincement pouce-majeur.
5. Viser et cliquer: pinch targets across the screen; this is the spatial exercise.
6. Manipulation de fenêtre, with sub-steps:
   - one hand captures one frame edge/corner and moves the whole window;
   - two hands capture two different compatible frame zones and resize larger/smaller.
7. Calibration complete/report.

The user supplied a screenshot of a real Jarvis note/window to clarify the target object. The implementation should exercise the real frame interaction semantics rather than invent a generic “move your hand right” exercise.

## Things explicitly not reopened

- existing contextual actions (buttons, scrollable text, stars, frame BODY, frame edges/corners);
- existing bimanual constraint rules;
- existing tracker/pinch/target-resolution algorithms unless an integration fix is required;
- gesture-to-action vocabulary beyond what is already canonical;
- new tools.
