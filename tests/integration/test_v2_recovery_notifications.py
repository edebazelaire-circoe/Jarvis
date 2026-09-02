from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import MissedRunPolicy, NotificationState, ScheduledItem


@pytest.mark.asyncio
async def test_overdue_reminder_recovery_becomes_persisted_notification(tmp_path):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    item = ScheduledItem(kind="reminder", payload={"message": "Appeler Alice"}, next_fire_at=datetime.now(timezone.utc) - timedelta(minutes=2), missed_run_policy=MissedRunPolicy.NOTIFY_LATE)
    await state.save_scheduled_item(item)
    await state.close()

    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        for _ in range(50):
            delivered = await core.state.list_notifications(state=NotificationState.DELIVERED.value)
            if delivered:
                break
            await asyncio.sleep(0.01)
        assert delivered
        assert delivered[0].body == "Appeler Alice"
        schedules = await core.state.list_scheduled_items()
        assert schedules[0].status.value == "completed"
    finally:
        await core.stop()
