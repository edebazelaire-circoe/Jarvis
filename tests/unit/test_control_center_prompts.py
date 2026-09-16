"""Task15C HTTP contract for architecture-scoped prompt inspection and mutation."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.journal import read_jsonl_tail


async def test_prompt_api_edits_and_resets_scoped_override_without_false_application(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_VOICE_ARCH", raising=False)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    control._write_settings({"unrelated": {"keep": True}})
    async with TestClient(TestServer(control._app)) as client:
        response = await client.get("/api/prompts")
        assert response.status == 200
        before = await response.json()
        assert before["provider_internal_prompts"] == "unavailable"
        assert before["application"] == "preview_only"
        persona = next(item for item in before["layers"] if item["prompt_id"] == "voice.persona")
        original_program = next(item for item in before["programs"]
                                if item["program_id"] == "voice.legacy.openai.session")

        secret = "PRIVATE custom voice persona"
        edited = await client.post("/api/prompts/voice.persona", json={
            "action": "edit", "text": secret, "base_revision": persona["default_revision"],
            "expected_effective_revision": persona["effective_revision"],
        })
        assert edited.status == 200
        result = await edited.json()
        assert result["mutation"]["application"] == "saved_only"
        changed = next(item for item in result["prompts"]["programs"]
                       if item["program_id"] == "voice.legacy.openai.session")
        assert changed["static_fingerprint"] != original_program["static_fingerprint"]
        stored = json.loads(control.settings_path.read_text(encoding="utf-8"))
        assert stored["unrelated"] == {"keep": True}
        assert stored["prompt_overrides"]["overrides"]["voice.persona"]["text"] == secret

        reset = await client.post("/api/prompts/voice.persona", json={"action": "reset"})
        assert reset.status == 200
        stored = json.loads(control.settings_path.read_text(encoding="utf-8"))
        assert "prompt_overrides" not in stored and stored["unrelated"] == {"keep": True}

    trace = read_jsonl_tail(control.journal.trace_path)
    assert secret not in json.dumps(trace)
    assert any(item["kind"] == "prompt.override.saved" for item in trace)


async def test_prompt_api_rejects_read_only_and_stale_edits_atomically(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    async with TestClient(TestServer(control._app)) as client:
        view = await (await client.get("/api/prompts")).json()
        rules = next(item for item in view["layers"] if item["prompt_id"] == "voice.rules.legacy")
        before = control.settings_path.read_bytes() if control.settings_path.exists() else None
        rejected = await client.post("/api/prompts/voice.rules.legacy", json={
            "action": "edit", "text": "unsafe", "base_revision": rules["default_revision"],
        })
        assert rejected.status == 400
        assert rejected.headers["X-Jarvis-Error-Code"] == "prompt_read_only"
        stale = await client.post("/api/prompts/voice.persona", json={
            "action": "edit", "text": "new", "base_revision": "0" * 64,
        })
        assert stale.status == 400
        assert stale.headers["X-Jarvis-Error-Code"] == "prompt_override_stale"
        after = control.settings_path.read_bytes() if control.settings_path.exists() else None
        assert after == before


async def test_prompt_projection_tracks_front_brain_architecture_and_backend_provider(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    async with TestClient(TestServer(control._app)) as client:
        settings = await (await client.get("/api/settings")).json()
        front = next(item for item in settings["voice"]["architecture"]["architectures"]
                     if item["id"] == "front_brain")["defaults"]
        assert (await client.post("/api/settings", json={"voice": {"architecture": front}})).status == 200
        prompts = await (await client.get("/api/prompts")).json()
        programs = {item["program_id"] for item in prompts["programs"]}
        layers = {item["prompt_id"] for item in prompts["layers"]}
        assert "voice.front_brain.openai.session" in programs
        assert "front_brain.openai.analysis" in programs
        assert "front_brain.analysis.addition" in layers
        assert "live.duplex.instructions" not in layers
        assert "backend.claude.conversation.system" in layers
        assert all(item["missing_variables"] == [] for item in prompts["programs"])


def test_prompt_tab_renders_server_projection_and_editability_without_inventing_layers(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required to execute prompt renderer")
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    fixture = control._prompt_payload(control._settings())
    page = Path("jarvis/runtime/control_center.html").read_text(encoding="utf-8")
    functions = page[page.index("function promptLayerHtml"):page.index("function tabCli()")]
    script = r'''
const assert=require('node:assert/strict');
const fixture=JSON.parse(require('node:fs').readFileSync(process.argv[2],'utf8'));
const SET={prompts:fixture};
const api=async()=>{throw new Error('unexpected API call')};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
''' + functions + r'''
(async()=>{
 const html=await tabPrompts();
 assert.ok(html.includes('prompts internes du fournisseur'));
 assert.ok(html.includes('Prompt effectif'));
 assert.ok(html.includes('voice.persona'));
 assert.ok(html.includes('data-prompt-save="voice.persona"'));
 assert.ok(html.includes('voice.rules.legacy'));
 assert.ok(!html.includes('data-prompt-save="voice.rules.legacy"'));
 for(const program of fixture.programs)assert.ok(html.includes(program.program_id));
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    js = tmp_path / "prompt-tab.cjs"
    data = tmp_path / "prompts.json"
    js.write_text(script, encoding="utf-8")
    data.write_text(json.dumps(fixture), encoding="utf-8")
    run = subprocess.run([node, str(js), str(data)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
