# The async conversation harness flakes under host load

Seen 2026-09-17 during Slice 05. Running `tests/integration/test_testlab_worker.py` and `tests/integration/test_v2_async_conversation.py` back to back in ONE pytest process made `test_three_turns_run_in_one_session_without_a_second_wake` fail 2 times in 5 ("seulement 2 tour(s) assistant persisté(s) sur 3").

It is a wall-clock deadline, not a behavioural assertion: `tests/integration/async_conversation_harness.py:76 TIMEOUT_S` (10 s) via `wait_for_assistant_turns`. Evidence that it's host load rather than an interaction: the voice file alone passed 5/5, and inserting a 6-second settle test between the two files made the pair 3/3 green. The Test Lab worker tests leave no process or thread behind.

Owner: outside this task. Either the harness waits on a condition rather than a wall clock, or its deadline scales with host load. Meanwhile, run the two files in separate foreground chunks on this host, as READINESS already prescribes.
