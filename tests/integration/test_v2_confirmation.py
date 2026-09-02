from __future__ import annotations

import pytest

from jarvis.core.v2_app import JarvisCoreApplication


@pytest.mark.asyncio
async def test_sensitive_calendar_action_requires_exact_confirmation_and_expires(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    try:
        created = await core.tools.call("calendar_create", {"title": "Réunion", "start_at": "2026-09-03T10:00:00+02:00", "end_at": "2026-09-03T11:00:00+02:00"}, conversation_id=None)
        event_id = created["event"]["id"]
        clock = [10.0]
        core.tools.clock = lambda: clock[0]
        core.tools.confirmation_timeout_s = 5.0
        request = await core.tools.call("calendar_delete", {"event_id": event_id}, conversation_id=None)
        assert request["disposition"] == "confirm" and request["executed"] is False
        action_id = request["action_id"]
        ambiguous = await core.tools.resolve_confirmation(action_id, "peut-être")
        assert ambiguous["disposition"] == "confirm"
        assert await core.calendar.backend.get_event(event_id) is not None
        clock[0] = 16.0
        expired = await core.tools.resolve_confirmation(action_id, "oui")
        assert expired["executed"] is False
        assert await core.calendar.backend.get_event(event_id) is not None
        request2 = await core.tools.call("calendar_delete", {"event_id": event_id}, conversation_id=None)
        approved = await core.tools.resolve_confirmation(request2["action_id"], "oui")
        assert approved["executed"] is True
        assert await core.calendar.backend.get_event(event_id) is None
    finally:
        await core.stop()
