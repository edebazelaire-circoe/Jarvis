# Issue — timing-sensitive `test_three_turns_run_in_one_session_without_a_second_wake`

Found during Slice 02 validation (2026-09-16), outside this task's scope.

- `tests/integration/test_v2_async_conversation.py::test_three_turns_run_in_one_session_without_a_second_wake` failed once on a full-suite run under load (404 s run vs 302 s baseline): its 10 s wait expired.
- The file is untouched by this task; it passed 16/16 three times in isolation and on the clean full rerun (3561 passed, 6 skipped).
- Action for a separate task: make the wait condition event-driven or scale the timeout for slow CI hosts.
