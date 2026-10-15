"""Constat de l'utilisateur sur une clôture GPT-Live incertaine (soirée du 14/10/2026).

OpenAI n'a pas confirmé deux fermetures (réseau dégradé), et son rattachement
répond 503 à toutes les sessions, ouvertes comme fermées : le watchdog ne peut
jamais conclure, et la voix restait bloquée une heure. Le bouton « Considérer
comme fermée » du Control Center fait clore la session par Core, preuve
`operator_acknowledged`, usage jamais final ; Voice se libère seul ensuite.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from jarvis.core.live_reaper import LiveLifecycleWatchdog
from jarvis.domain.live_lifecycle import (
    LiveCloseEvidence, LiveLifecycleConflict, LiveLifecycleState, LiveOwnerKind,
)
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.live_status import CoreLiveStatusView, project_live_status
from jarvis.runtime.visual_signals import VisualSignalBus
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.domain.v2 import VoiceLifecycleState
from tests.unit.test_live_lifecycle_lease import bound_active, opened, reserve
from tests.unit.test_live_status_ui import LIVE_JS, NOW, PAGE, record


class FailingCloser:
    """Le rattachement réel répond 503 : aucune fermeture ne peut être prouvée."""

    async def close_session(self, provider_session_id, persist):  # noqa: ANN001
        raise RuntimeError("503")


async def uncertain(service, watchdog):
    """Une session active dont le propriétaire a disparu, puis une fermeture ratée."""
    await bound_active(service)
    service.clock.advance(31)
    await watchdog.run_once()
    record_ = await service.status()
    assert record_.state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED
    return record_


async def test_acknowledged_close_stops_the_session_and_frees_the_lease(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    watchdog = LiveLifecycleWatchdog(service, FailingCloser(), attempt_timeout_seconds=.1)
    try:
        before = await uncertain(service, watchdog)
        stopped = await watchdog.acknowledge_closed(before.session_id)

        assert stopped.state is LiveLifecycleState.STOPPED
        assert stopped.close_evidence is LiveCloseEvidence.OPERATOR_ACKNOWLEDGED
        assert stopped.provider_usage_final is False
        assert stopped.provider_session_id == before.provider_session_id
        assert await service.status() is None
        # La voix peut rouvrir : une nouvelle réservation passe.
        assert (await reserve(service, "session-b", "owner-b", at=service.clock.now())).state \
            is LiveLifecycleState.STARTING
        # Idempotent : un second constat rend la même session arrêtée.
        assert (await watchdog.acknowledge_closed(before.session_id)).revision == stopped.revision
    finally:
        await watchdog.stop()
        await repo.close()


async def test_a_primary_marked_uncertain_close_is_acknowledged_without_waiting_for_the_lease(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    watchdog = LiveLifecycleWatchdog(service, FailingCloser(), attempt_timeout_seconds=.1)
    try:
        active = await bound_active(service)
        unknown = await service.transition(
            active.session_id, active.owner_incarnation_id, active.owner_epoch, active.revision,
            LiveLifecycleState.UNKNOWN_REAP_REQUIRED, "user_close_unconfirmed",
        )
        assert unknown.owner_kind is LiveOwnerKind.PRIMARY
        stopped = await watchdog.acknowledge_closed(unknown.session_id)
        assert stopped.close_evidence is LiveCloseEvidence.OPERATOR_ACKNOWLEDGED
    finally:
        await watchdog.stop()
        await repo.close()


async def test_a_live_session_that_closes_normally_cannot_be_acknowledged(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    watchdog = LiveLifecycleWatchdog(service, FailingCloser(), attempt_timeout_seconds=.1)
    try:
        active = await bound_active(service)
        with pytest.raises(LiveLifecycleConflict) as refused:
            await watchdog.acknowledge_closed(active.session_id)
        assert refused.value.code == "live_invalid_transition"
        assert (await service.status()).state is LiveLifecycleState.ACTIVE
    finally:
        await watchdog.stop()
        await repo.close()


async def test_an_acknowledgement_never_carries_a_final_usage(tmp_path):
    repo, service = await opened(tmp_path / "state.sqlite")
    watchdog = LiveLifecycleWatchdog(service, FailingCloser(), attempt_timeout_seconds=.1)
    try:
        before = await uncertain(service, watchdog)
        owned = await service.status(before.session_id)
        with pytest.raises(LiveLifecycleConflict):
            await service.finalize(
                owned.session_id, owned.owner_incarnation_id, owned.owner_epoch, owned.revision,
                owned.provider_session_id, owned.active_seconds, 12.0,
                "operator_acknowledged", LiveCloseEvidence.OPERATOR_ACKNOWLEDGED,
            )
    finally:
        await watchdog.stop()
        await repo.close()


def test_the_button_is_offered_only_for_a_readable_uncertain_close():
    assert project_live_status(record(LiveLifecycleState.UNKNOWN_REAP_REQUIRED), now=NOW)["stop"]["acknowledge"] is True
    assert project_live_status(record(), now=NOW)["stop"]["acknowledge"] is False
    assert project_live_status(record(LiveLifecycleState.STOPPING), now=NOW)["stop"]["acknowledge"] is False
    # Core illisible : le record retenu peut être périmé, rien n'est offert.
    stale = project_live_status(record(LiveLifecycleState.UNKNOWN_REAP_REQUIRED), now=NOW,
                                core_reachable=False, stale=True)
    assert stale["stop"]["acknowledge"] is False


class AckReader:
    def __init__(self, records):
        self.records = list(records)
        self.acknowledged: list[str] = []

    async def live_session_status(self):
        return self.records.pop(0) if self.records else None

    async def acknowledge_live_session_closed(self, session_id):
        self.acknowledged.append(session_id)
        return None


async def test_control_center_acknowledges_only_an_uncertain_close(tmp_path):
    VisualSignalBus(tmp_path).heartbeat()
    reader = AckReader([record(LiveLifecycleState.UNKNOWN_REAP_REQUIRED), None])
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, live_view=CoreLiveStatusView(reader))
    response = await control.live_acknowledge_closed(None)
    assert response.status == 200
    assert reader.acknowledged == ["logical-live"]
    assert json.loads(response.text)["live"]["visible"] is False

    active = AckReader([record()])
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, live_view=CoreLiveStatusView(active))
    refused = await control.live_acknowledge_closed(None)
    assert refused.status == 409
    assert active.acknowledged == []


def test_the_page_offers_a_two_click_acknowledgement_without_a_browser_dialog():
    html = PAGE.read_text(encoding="utf-8")
    assert 'id="liveAck"' in html and "/api/live/acknowledge-closed" in html
    assert "CONFIRMER : SESSION FERMÉE" in html
    assert "confirm(" not in html.split('id="liveAck"')[1].split("</section>")[0]


def test_the_browser_projection_exposes_the_acknowledgement(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "live-ack.cjs"
    script.write_text(
        "const a=require('node:assert/strict'),v=require(process.argv[2]);"
        "a.equal(v.project({visible:true,state:'unknown_reap_required',core_reachable:true,stop:{acknowledge:true}}).acknowledge,true);"
        "a.equal(v.project({visible:true,state:'active',core_reachable:true,stop:{}}).acknowledge,false);",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(script), str(LIVE_JS)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


class Wake:
    resumed = 0

    async def suspend_for_active_session(self) -> None: ...

    async def resume(self) -> None:
        Wake.resumed += 1

    async def close(self) -> None: ...


async def _never(_context):  # noqa: ANN001
    raise AssertionError("aucune session n'est ouverte par ce test")


def voice_with(core):
    runtime = PersistentVoiceRuntime(wakeword=Wake(), core=core, realtime_factory=_never,
                                     auto_turn=True, active_timeout_s=0)
    runtime._pending_canonical_close = SimpleNamespace(_lifecycle_owner=object())
    runtime.runtime.state = VoiceLifecycleState.ERROR
    return runtime


async def test_voice_frees_itself_once_core_no_longer_holds_the_session():
    async def resolved():
        return None
    runtime = voice_with(SimpleNamespace(live_session_status=resolved))
    Wake.resumed = 0

    assert await runtime._release_if_core_resolved() is True
    assert runtime._pending_canonical_close is None
    assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
    assert Wake.resumed == 1, "le mot d'éveil doit être réarmé"


@pytest.mark.parametrize("answer", ["unresolved", "unreadable"])
async def test_voice_stays_blocked_while_core_holds_or_cannot_be_read(answer):
    async def status():
        if answer == "unreadable":
            raise ConnectionError("core down")
        return object()
    runtime = voice_with(SimpleNamespace(live_session_status=status))

    assert await runtime._release_if_core_resolved() is False
    assert runtime._pending_canonical_close is not None
    assert runtime.runtime.state is VoiceLifecycleState.ERROR
