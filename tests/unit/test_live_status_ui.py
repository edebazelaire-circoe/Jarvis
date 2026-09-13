from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis import app
from jarvis.domain.live_lifecycle import (
    LiveLifecycleOperation, LiveLifecycleState, LiveOwnerKind, LiveSessionRecord,
)
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.live_status import CoreLiveStatusView, project_live_status
from jarvis.runtime.visual_signals import VisualSignalBus


NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
LIVE_JS = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_live.js"
PAGE = LIVE_JS.with_name("control_center.html")


def record(state: LiveLifecycleState = LiveLifecycleState.ACTIVE) -> LiveSessionRecord:
    created = NOW - timedelta(seconds=90)
    active = state is not LiveLifecycleState.STARTING
    closing = state in {LiveLifecycleState.STOPPING, LiveLifecycleState.UNKNOWN_REAP_REQUIRED}
    return LiveSessionRecord(
        session_id="logical-live", provider_session_id="provider-live" if active else None,
        owner_incarnation_id="voice-owner", owner_epoch=1, owner_kind=LiveOwnerKind.PRIMARY,
        state=state, start_may_have_been_sent=active, heartbeat_at=NOW - timedelta(seconds=1),
        lease_deadline=NOW + timedelta(seconds=29), created_at=created, updated_at=NOW,
        state_entered_at=NOW - timedelta(seconds=2), activated_at=NOW - timedelta(seconds=80) if active else None,
        stopped_at=None, active_seconds=12.0, provider_usage_seconds=30.0 if active else None,
        provider_usage_final=False, close_reason="user" if closing else None,
        close_evidence=None, last_operation=LiveLifecycleOperation.TRANSITION, revision=4,
    )


def test_projection_uses_core_time_and_only_proven_pricing_metadata():
    item = record()
    runtime = {"session_id": item.session_id, "model_id": "gpt-live-1", "idle_enabled": True,
               "idle_timeout_s": 60.0, "idle_remaining_s": 11.0,
               "idle_waiting_for_safe_point": False}
    price = {"schema_version": 1, "model_id": "gpt-live-1", "currency": "usd", "price_per_minute": 0.2,
             "source": "provider price sheet", "effective_at": "2026-09-01T00:00:00+00:00"}

    payload = project_live_status(item, now=NOW, runtime=runtime, pricing=price)

    assert payload["visible"] is True
    assert payload["elapsed_seconds"] == 80.0
    assert payload["usage"] == {"seconds": 30.0, "final": False, "source": "provider"}
    assert payload["cost_estimate"]["amount"] == pytest.approx(0.1)
    assert payload["cost_estimate"]["basis"] == "provider_usage"
    assert payload["idle"]["remaining_seconds"] == 11.0
    assert project_live_status(item, now=NOW, runtime=runtime,
                               pricing={**price, "source": ""})["cost_estimate"] is None


def test_uncertain_and_stale_sessions_remain_visible_and_actionable():
    uncertain = project_live_status(record(LiveLifecycleState.UNKNOWN_REAP_REQUIRED), now=NOW)
    stale = project_live_status(record(), now=NOW, core_reachable=False, stale=True)

    assert uncertain["visible"] and uncertain["uncertain"]
    assert uncertain["stop"]["can_retry"] is True
    assert "facturable" in uncertain["warning"]
    assert stale["visible"] and stale["uncertain"]
    assert "conservé" in stale["warning"]
    unavailable = project_live_status(None, now=NOW, core_reachable=False)
    assert unavailable["visible"] and unavailable["state"] == "status_unavailable"
    assert unavailable["stop"]["available"] is False


class Reader:
    def __init__(self, values):
        self.values = iter(values)
        self.closed = False

    async def live_session_status(self):
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value

    async def close(self):
        self.closed = True


async def test_core_view_does_not_hide_held_live_state_on_outage():
    view = CoreLiveStatusView(Reader([record(), ConnectionError("down"), None]))
    first = await view.read()
    failed = await view.read()
    cleared = await view.read()

    assert first[0] is not None and first[1:] == (True, False)
    assert failed[0] == first[0] and failed[1:] == (False, True)
    assert cleared == (None, True, False)


async def test_control_center_stop_is_idempotent_and_does_not_claim_stopped(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.heartbeat()
    view = CoreLiveStatusView(Reader([record(), record()]))
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, live_view=view)

    first = json.loads((await control.live_stop(None)).text)
    second = json.loads((await control.live_stop(None)).text)

    assert first["live"]["state"] == "active"
    assert first["live"]["stop"]["pending"] is True
    assert second["live"]["stop"]["request_id"] == first["live"]["stop"]["request_id"]
    assert bus.read_live_stop_request()["session_id"] == "logical-live"


def test_global_live_banner_is_accessible_and_stop_is_outside_settings():
    html = PAGE.read_text(encoding="utf-8")
    assert 'id="liveBanner" role="status" aria-live="assertive"' in html
    assert html.index('id="liveStop"') < html.index('id="overlay"')
    assert "/api/live/stop" in html


def test_live_browser_projection_keeps_failure_visible(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "live-view-test.cjs"
    script.write_text(
        "const a=require('node:assert/strict'),v=require(process.argv[2]);"
        "let x=v.project({visible:true,state:'active',elapsed_seconds:65,core_reachable:true,stop:{}});"
        "a.equal(x.visible,true);a.equal(x.label,'ACTIF');a.equal(v.duration(x.elapsed),'01:05');"
        "x=v.project({visible:true,state:'stopping',elapsed_seconds:66,core_reachable:true,stop:{pending:true}});"
        "a.equal(x.visible,true);a.equal(x.disabled,true);a.equal(x.action,'ARRÊT DEMANDÉ');"
        "x=v.project({visible:true,state:'unknown_reap_required',elapsed_seconds:70,core_reachable:false,stop:{can_retry:true}});"
        "a.equal(x.visible,true);a.equal(x.uncertain,true);a.equal(x.action,'RÉESSAYER L’ARRÊT');"
        "a.deepEqual(v.project({visible:false,state:'stopped'}),{visible:false});",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(script), str(LIVE_JS)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


async def test_voice_consumes_matching_stop_request_and_writes_receipt(tmp_path):
    bus = VisualSignalBus(tmp_path)
    request = bus.request_live_stop("logical-live")

    class Voice:
        def __init__(self):
            self.reasons = []

        def live_runtime_report(self):
            return {"session_id": "logical-live", "runtime_state": "active"}

        async def mute(self, reason):
            self.reasons.append(reason.value)

    voice = Voice()
    handled = await app._handle_live_ui_supervision(voice, bus, None, None)

    assert handled == request["request_id"]
    assert voice.reasons == ["user"]
    assert bus.read_live_stop_request() is None
    assert bus.live_stop_receipt()["status"] == "accepted"


async def test_voice_rejects_stop_for_a_different_session_without_muting(tmp_path):
    bus = VisualSignalBus(tmp_path)
    bus.request_live_stop("old-live")

    class Voice:
        def live_runtime_report(self):
            return {"session_id": "new-live", "runtime_state": "active"}

        async def mute(self, reason):  # pragma: no cover - prohibited path
            raise AssertionError(reason)

    await app._handle_live_ui_supervision(Voice(), bus, None, None)

    receipt = bus.live_stop_receipt()
    assert receipt["session_id"] == "old-live"
    assert receipt["status"] == "failed"
