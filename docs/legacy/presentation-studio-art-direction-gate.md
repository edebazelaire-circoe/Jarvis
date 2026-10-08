# Presentation Studio: playback runs without an art direction check (temporary)

Created by Slice 12 of `jarvis-interactive-presentation-studio` (2026-10-08).

## What is temporary

`PresentationStudioPlaybackService` takes an `ArtDirectionGate` (the signature of `PresentationStudioService.require_art_direction` from
Slice 09) and calls it before a presenter run. The Slice 09 code was being merged by another worker when Slice 12 was built, so `jarvis/core/v2_app.py`
wires the gate with `hasattr(self.presentation_studio, "require_art_direction")`: **without** that method the gate is `None`, the run starts, says
`art_direction: "unchecked"` in its state (the player band shows "Direction artistique non vérifiée") and writes the warning
`core.presentation_studio.playback_art_direction_unchecked`.

## Why it is acceptable for now

Nothing plays by itself: a run is started by an explicit user request. The state says what was not checked, on screen and in the journal. Rehearsal passes
`serious=false` and never needed the check to be fatal.

## Removal condition

Slice 09 is merged into the task branch: `hasattr` is then true and the gate is wired with no further change. At that merge: delete this page, change
`test_without_a_gate_the_run_says_so_and_with_one_it_says_checked` (and `docs/presentation-studio.md`, "Roles, mode, art direction") to assert the real gate, and
make `gate=None` a construction error in `v2_app.py`.
