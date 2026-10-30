# I-003 — Existing Bare Hands practice-frame expectation failure

Independently reproduced in PM mov at baseline scene JS (S02 not integrated):
main venv Python -m pytest --assert=plain --tb=short -q tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones
Result1 failed in2.61s; line2425 expects opposite["commit"][3:] == [-62,-20,124,40].
S02 implementer encountered same failure; unlocked side math unchanged. Root cause not established, no feature-induced regression demonstrated. Preserve as baseline for S06; other actual browser mouse and focused Bare Hands seams are independently exercised.

