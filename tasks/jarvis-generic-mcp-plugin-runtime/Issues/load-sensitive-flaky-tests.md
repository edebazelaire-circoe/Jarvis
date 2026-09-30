# Two pre-existing tests flake under a full-suite load

Seen in the Slice 08 phase A full regression (2026-09-30, foreground chunks of 30 files), not in READINESS §Baseline, and not touched by this task (no commit of the handoff changes their files or the code under them):

- `tests/unit/test_back_brain_tasks.py::test_persistent_transition_failure_keeps_owner_and_stop_bounded_until_recovery` — failed once in chunk 00 (`core.health.status == 'state_persistence_unknown'`, expected `stopped`); passed 3/3 alone and 34/34 for the whole file. Timing race on the stop deadline under load.
- `tests/unit/test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo` — failed once in chunk 04 and once in 3 isolated file runs (headless Chrome; the computed-style assertion saw `'none' != 'none'` on one animation read). Browser timing.

Suggested: make the first wait on the health transition instead of a fixed budget, and the second wait for the computed animation state. Out of scope for this handoff.
