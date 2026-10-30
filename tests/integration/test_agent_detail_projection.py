"""Real Core/SQLite → existing public Control Center reads → production JS projector."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil

from aiohttp.test_utils import TestServer
import pytest

from jarvis.domain.mission_history import MissionOpening
from jarvis.domain.work_state import WorkObservation, WorkStatus
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.declaration_relay import CoreMissionTransport
from jarvis.runtime.mission_view import CoreMissionView
from jarvis.runtime.work_ingress import CoreWorkTransport
from jarvis.runtime.work_view import CoreWorkView
from tests.fakes.mission_history import fact
from tests.integration.test_scene_transport import core  # noqa: F401


async def test_real_public_reads_show_running_terminal_and_restarted_unknown_without_private_fields(core, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent")
    work_view = CoreWorkView(CoreWorkTransport(host="127.0.0.1", port=core.port, token_file=core.token_file))
    mission_view = CoreMissionView(CoreMissionTransport(host="127.0.0.1", port=core.port, token_file=core.token_file))
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path, work_view=work_view, mission_view=mission_view)
    server = TestServer(control._app)
    await server.start_server()
    now = datetime.now(timezone.utc)
    parent = await core.core.mission_history.record_declaration(
        fact("tool-parent", role="coder", mission_id="mission-real", owner=True, label="Comparer les écrans"),
        work_source="claude", work_external_id="parent", mission=MissionOpening(objective="Choisir un écran"))
    assert parent.instance is not None, parent.to_payload()
    child = await core.core.mission_history.record_declaration(
        fact("tool-child", role="research", label="Vérifier les prix"), work_source="claude", work_external_id="child",
        parent_work_external_id="parent", inherit_mission=True)
    assert child.instance is not None, child.to_payload()
    await core.core.work_state.observe(WorkObservation(source="claude", external_id="parent", status=WorkStatus.RUNNING,
        observed_at=now, started_at=now, kind="agent", role_id="coder", label="Comparer les écrans", activity="Lecture des fiches", progress_fraction=.4))
    await core.core.work_state.observe(WorkObservation(source="claude", external_id="child", parent_external_id="parent",
        status=WorkStatus.RUNNING, observed_at=now, started_at=now, kind="agent", role_id="research", label="Vérifier les prix"))
    module = Path(__file__).resolve().parents[2] / "jarvis/runtime/control_center_agent_detail.js"
    script = tmp_path / "read-agent-detail.cjs"
    script.write_text(
        f"const A=require({json.dumps(str(module))}),base={json.dumps(str(server.make_url('/')).rstrip('/'))};\n"
        "const reader=A.createReader({log:()=>{},fetchJson:async path=>{const r=await fetch(base+path);const b=await r.json();"
        "if(!r.ok)throw Object.assign(new Error(b.error?.message||`HTTP ${r.status}`),{status:r.status,code:b.error?.code});return b}});\n"
        "reader.load({object:{object_id:'scene-parent',kind:'agent',work_ref:{source:'claude',external_id:'parent'},payload:{title:'Agent'}}})"
        ".then(r=>console.log(JSON.stringify(r))).catch(e=>{console.error(e);process.exitCode=1});",
        encoding="utf-8")

    async def read():
        process = await asyncio.create_subprocess_exec(node, str(script), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
        except asyncio.TimeoutError:
            process.kill()  # This exact QA child only; never process-name killing.
            await process.wait()
            raise
        assert process.returncode == 0, stderr.decode("utf-8")
        return json.loads(stdout)

    try:
        running = await read()
        assert running["phase"] == "ready" and running["model"]["status"] == "running"
        assert running["model"]["mission"] == {"mission_id": "mission-real", "objective": "Choisir un écran"}
        assert running["model"]["progress_fraction"] == .4 and running["model"]["steps"][0]["status"] == "running"
        assert running["model"]["actions"]["stop"]["enabled"] is False
        await core.core.work_state.observe(WorkObservation(source="claude", external_id="parent", status=WorkStatus.COMPLETED,
            observed_at=now + timedelta(seconds=10), label="Comparer les écrans", summary="Deux modèles retenus", progress_fraction=1))
        terminal = await read()
        assert terminal["model"]["status"] == "completed" and terminal["model"]["ended_at"] is not None
        assert terminal["model"]["findings"][0]["text"] == "Deux modèles retenus"
        await core.stop()
        await core.start()
        unknown = await read()
        assert unknown["model"]["status"] == "unknown" and unknown["model"]["started_at"] is None
        assert unknown["model"]["mission"]["objective"] == "Choisir un écran"
        assert unknown["model"]["steps"][0]["status"] == "unknown"
        assert unknown["model"]["published_plan"] is None
        for result in (running, terminal, unknown):
            payload = json.dumps(result)
            assert '"declaration"' not in payload and '"prompt"' not in payload and '"trace"' not in payload
    finally:
        await server.close()
        await mission_view.close()
        await work_view.aclose()
