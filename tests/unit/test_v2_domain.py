from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jarvis.domain.v2 import MissedRunPolicy, ProtocolEnvelope, ScheduledItem
from jarvis.v2_config import validate_loopback_host


def test_schedule_requires_aware_time_and_recent_policy_lateness():
    with pytest.raises(ValueError):
        ScheduledItem(next_fire_at=datetime(2026, 9, 2, 10, 0))
    with pytest.raises(ValueError):
        ScheduledItem(next_fire_at=datetime.now(timezone.utc), missed_run_policy=MissedRunPolicy.RUN_IF_RECENT)


def test_protocol_rejects_unknown_version():
    with pytest.raises(ValueError):
        ProtocolEnvelope(message_type="x", payload={}, protocol_version=999)


def test_core_binding_accepts_only_loopback():
    assert validate_loopback_host("127.77.0.1") == "127.77.0.1"
    assert validate_loopback_host("::1") == "::1"
    for host in ("0.0.0.0", "192.168.1.10", "10.0.0.2", "8.8.8.8"):
        with pytest.raises(Exception):
            validate_loopback_host(host)
