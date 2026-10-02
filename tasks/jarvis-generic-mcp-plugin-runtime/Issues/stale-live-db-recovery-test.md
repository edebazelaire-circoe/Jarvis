# Stale opt-in test: live DB schema version

`tests/integration/test_conversation_event_store_recovery.py:103` asserts schema version 2 on the live `data/state/jarvis.sqlite3`. The schema was v3 before this task and becomes v4 with Slice 02. The test is skipped unless `JARVIS_TEST_REAL_STATE_DB=1`, so no gate sees it. Suggested fix: compare against `sqlite_state._SCHEMA_VERSION`, or against "≥ the version of the running binary". Found 2026-09-30 by the Slice 02 implementer.
