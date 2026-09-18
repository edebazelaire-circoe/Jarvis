# Issue — intermittent `jarvis.sqlite3` connection leak in a back-brain capacity test (pre-existing)

Found during Slice 02 QA rework (non-blocking, not caused by this task — pending independent confirmation by QA).

`tests/unit/test_back_brain_tasks.py::test_capacity_sixteen_refuses_without_partial_source_reservation`: `core.stop()` sometimes returns early (`cleanup_unknown`) before `state.close()`, leaving `state/jarvis.sqlite3` open. Surfaces as an intermittent "unclosed database" `PytestUnraisableExceptionWarning` under `-W error::ResourceWarning`.

Implementer measurement: 5/15 leaks on base `725f1a7`, 7/15 on task HEAD.

Also flagged by Slice 02 QA (pre-existing, uncertain): a garbage `jarvis.sqlite3` makes `SQLiteStateRepository` keep its connection open after a failed start. And a flaky `tests/integration/test_v2_async_conversation.py::test_three_turns_run_in_one_session_without_a_second_wake` / `tests/integration/test_voice_device_control_plane.py::test_blocked_canonical_drain_keeps_capture_urgent_input_and_stop_responsive` under host load.

Resolution target: outside this task's scope; report to Human at close-out.
