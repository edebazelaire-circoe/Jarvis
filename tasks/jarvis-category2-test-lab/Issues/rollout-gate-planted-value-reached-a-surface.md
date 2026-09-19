# A planted value reached an export/transcript surface once (rollout gate)

Observed 2026-09-17 by the Slice 06 QA agent, on the current tree: over 11 repeats of the five harness-consumer files, `tests/integration/test_conversation_event_rollout_gate.py:280` failed once with `AssertionError: 4242` — a planted value reaching an export or transcript surface. The same set run 6 times against a `git archive HEAD` copy did not reproduce it (the only failures there were the known wall-clock flake).

Slice 06 changes nothing in the conversation-events export or transcript path, so this is not attributed to it. It is recorded because the rollout gate exists precisely to prove that diagnostic-visibility content never reaches a public surface, and a 1-in-11 failure of that gate is worth chasing rather than losing.

Owner: outside this task (conversation observability). Suggested next step: run that file in a loop (50+) on an idle host to characterise it, and check whether the assertion is order- or timing-dependent rather than a real leak.
