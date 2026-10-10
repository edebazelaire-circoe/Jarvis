"""Export RÉEL de bout en bout (Remotion Slice 16) : vrai Core, vrai registre, vrai paquet, vrai Node + Remotion épinglé + Chrome installé, vrai
Control Center, vrai Chrome qui clique « Exporter » dans la vue Artefacts d'un Board.

Opt-in : `JARVIS_REMOTION_RUNTIME_DIR` = le dossier `runtime/` d'une installation Remotion (la preuve de la Slice 16 utilise le runtime privé
de la Slice 10, une jonction `node_modules` vers l'installation de la Slice 06 : aucune installation de plus). Se saute sans Node, sans Chrome ou
sans ce réglage. Racine de données jetable sous `tmp_path`, ports libres, jamais le JARVIS vivant. Captures : `JARVIS_S16_EVIDENCE_DIR`.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import socket

import pytest

from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.adapters.remotion_render_runner import RemotionRenderRunner
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.artifacts import ArtifactKind, ArtifactState
from jarvis.domain.remotion_source import Composition
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.core_sessions import CoreSessionTransport
from aiohttp.test_utils import TestClient, TestServer
from tests.fakes.remotion_scene import scene_candidate
from tests.unit.test_interaction_mode_hud_browser import _chrome
from tests.unit.test_local_capability_host import FakeRunner

RUNTIME = os.environ.get("JARVIS_REMOTION_RUNTIME_DIR", "")
HARNESS = Path(__file__).parent / "_workspace_browser.mjs"
TOKEN = "r" * 48
SCENE = "presentation-studio.p000000000001.s000000000001"
SCENE_TSX = '''import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
export default function Scene(props: {title: string; accent: string}) {
  const frame = useCurrentFrame();
  const {durationInFrames, width} = useVideoConfig();
  const left = interpolate(frame, [0, durationInFrames - 1], [0, width - 240]);
  return (
    <AbsoluteFill style={{background: "#101820"}}>
      <div style={{position: "absolute", left, top: 300, width: 240, height: 120, background: props.accent}} />
      <h1 style={{color: "#ffffff", fontSize: 72, fontFamily: "sans-serif", margin: 60}}>{props.title} {frame}</h1>
    </AbsoluteFill>
  );
}
'''
PROPS = {"type": "object", "properties": {"title": {"type": "string", "default": "Jarvis", "max_length": 80},
                                           "accent": {"type": "color", "default": "#3366ff"}}}

pytestmark = pytest.mark.skipif(not RUNTIME or shutil.which("node") is None,
                                reason="JARVIS_REMOTION_RUNTIME_DIR (a Remotion runtime) and Node.js are required")


class Stack:
    pass


async def build(tmp_path: Path) -> Stack:
    def free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    s = Stack()
    s.runner = RemotionRenderRunner(lambda: Path(RUNTIME))
    root = tmp_path / "data"
    s.core = JarvisCoreApplication(data_root=root, local_capability_runner=FakeRunner(),
                                   local_capability_store=FileLocalCapabilityStore(root.resolve()), remotion_render_runner=s.runner)
    await s.core.start()
    port = free_port()
    s.server = LocalProtocolServer(s.core, host="127.0.0.1", port=port, token=TOKEN)
    await s.server.start()
    s.client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    assert (await s.client.local_capability_action("remotion", "install"))["capability"]["status"] == "ready"  # fake capability runner, real render runner
    token_file = tmp_path / "core.token"
    token_file.write_text(TOKEN, encoding="utf-8")
    s.sessions = CoreSessionTransport(host="127.0.0.1", port=port, token_file=token_file)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    s.center = ControlCenter(runtime_root=runtime, project_root=tmp_path)
    s.center.sessions = s.sessions
    s.center.board_routes._transport = s.sessions
    s.cc = TestClient(TestServer(s.center._app))
    await s.cc.start_server()
    return s


async def close(s: Stack) -> None:
    await s.cc.close()
    await s.sessions.close()
    await s.client.close()
    await s.server.stop()
    await s.core.stop()


async def frozen(s: Stack) -> tuple[str, str]:
    c = s.core
    published = await c.prefabs.save(scene_candidate(SCENE, files={"src/Scene.tsx": SCENE_TSX}, composition=Composition("Scene", 1280, 720, 30, 90),
                                                     engine=shipped_engine_pin(), props=PROPS, sample={"props": {"title": "Jarvis"}, "data": {}}),
                                     actor="user")
    home = (await c.boards.create({"title": "Atelier export"})).board_id
    await c.boards.switch(home)
    created = await c.presentation_studio.create({"title": "Lancement"})
    pid, vid = created.presentation.presentation_id, created.presentation.active_variant_id
    variant = created.variants[0].to_document()
    await c.presentation_studio.save_variant(pid, vid, {
        "expected_revision": variant["revision"], "title": variant["title"], "scenes": [
            {"scene_id": "pss_000000000001", "prefab": {"id": SCENE, "version": published.version}, "props": {"title": "Export reel"}}],
        "art_direction_id": None, "score_id": None})
    view = await c.presentation_studio.get(pid)
    done = await c.presentation_packager.freeze(pid, vid, expected_presentation_revision=view.presentation.revision,
                                                expected_variant_revision=view.variants[0].revision, authorised_boards={home})
    return home, done["artifact_id"]


async def test_the_board_exports_a_still_an_mp4_and_a_pdf_and_previews_them_in_a_real_browser(tmp_path):
    chrome = _chrome()
    shots = Path(os.environ.get("JARVIS_S16_EVIDENCE_DIR") or tmp_path / "shots")
    shots.mkdir(parents=True, exist_ok=True)
    s = await build(tmp_path)
    try:
        home, snapshot = await frozen(s)
        panel = "document.getElementById('wspPanel')"
        section = f"{panel}.querySelector('#wspPresTitle').closest('section')"
        form = f"{section}.querySelector('form[data-form=export-start]')"

        def export(fmt: str, frame_wait: str) -> list[dict]:
            return [
                {"do": f"(()=>{{const f={form};f.querySelector('select[name=format]').value={json.dumps(fmt)};f.querySelector('button[type=submit]').click();return true}})()"},
                {"wait": f"!!{section}.querySelector('[data-act=export-cancel]')", "ms": 60000},
                {"get": f"running_{fmt}", "expr": f"{section}.querySelector('.wsp-export').textContent"},
                {"wait": f"{section}.textContent.includes('Export terminé')||{section}.textContent.includes('Export échoué')||{section}.textContent.includes('Export impossible')", "ms": 240000},
                {"get": f"done_{fmt}", "expr": f"{section}.textContent"},
                {"do": f"{section}.querySelector('[data-act=export-dismiss]').click()"},
                {"wait": frame_wait, "ms": 20000},
            ]

        steps = [
            {"do": "document.getElementById('openWorkspace').click()"},
            {"wait": "document.getElementById('wsp-tab-artifacts')"},
            {"do": "document.getElementById('wsp-tab-artifacts').click()"},
            {"wait": f"{panel}.textContent.includes('Présentations de «')&&{panel}.textContent.includes('Lancement')"},
            {"wait": "document.getElementById('wspStatus').dataset.tone!=='busy'"},
            {"get": "form_offered", "expr": f"!!({form})"},
            {"shot": "s16-board-before-export.png"},
            *export("still", f"!!({form})"),
            *export("mp4", f"!!({form})"),
            *export("pdf", f"!!({form})"),
            {"get": "renders", "expr": f"[...{section}.querySelectorAll('li')].filter(li=>li.firstElementChild&&li.firstElementChild.textContent.trim()==='Rendu').map(li=>li.textContent.replace(/\\s+/g,' ').trim())"},
            {"wait": f"{section}.querySelector('img.wsp-thumb')&&{section}.querySelector('img.wsp-thumb').complete", "ms": 20000},
            {"get": "thumb", "expr": f"(()=>{{const i={section}.querySelector('img.wsp-thumb');return {{w:i.naturalWidth,h:i.naturalHeight,src:i.getAttribute('src')}}}})()"},
            {"get": "video", "expr": f"new Promise(r=>{{const v={section}.querySelector('video.wsp-thumb');v.addEventListener('loadedmetadata',()=>r({{w:v.videoWidth,h:v.videoHeight,d:v.duration,src:v.getAttribute('src')}}));v.addEventListener('error',()=>r({{error:v.error&&v.error.code}}));v.load()}})"},
            {"get": "pdf", "expr": f"(async()=>{{const a={section}.querySelector('a.wsp-link[href$=\"/payload\"]');const r=await fetch(a.getAttribute('href'));const b=new Uint8Array(await r.arrayBuffer());return {{status:r.status,type:r.headers.get('content-type'),head:String.fromCharCode(...b.slice(0,5)),size:b.length}}}})()"},
            {"get": "flat_note", "expr": f"{section}.textContent.includes('export à plat : non éditable')"},
            {"get": "overflow", "expr": f"(()=>{{const p={panel};return p.scrollWidth-p.clientWidth}})()"},
            {"shot": "s16-board-after-export.png"},
        ]
        plan = {"width": 1440, "height": 1000, "waitMs": 60000, "steps": steps}
        proc = await asyncio.create_subprocess_exec(shutil.which("node"), str(HARNESS), f"http://127.0.0.1:{s.cc.server.port}/", chrome, json.dumps(plan),
                                                    str(shots), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=900)
        assert proc.returncode == 0, err.decode("utf-8", "replace")[-3000:]
        seen = json.loads(out.decode("utf-8"))
        r = seen["results"]
        assert r["form_offered"] is True
        for fmt in ("still", "mp4", "pdf"):
            running = r[f"running_{fmt}"]  # what the user sees while it runs: what, which phase, how long, how to stop
            assert "en cours" in running and " s" in running and "Annuler l’export" in running and "Demande d’export" not in running, running
            assert "Export terminé" in r[f"done_{fmt}"], r[f"done_{fmt}"][:600]
        assert len(r["renders"]) == 3 and all("export à plat" in line for line in r["renders"])
        assert r["thumb"]["w"] == 1280 and r["thumb"]["h"] == 720
        assert r["video"].get("error") is None and (r["video"]["w"], r["video"]["h"]) == (1280, 720) and abs(r["video"]["d"] - 3.0) < 0.1
        assert r["pdf"]["status"] == 200 and r["pdf"]["type"] == "application/pdf" and r["pdf"]["head"] == "%PDF-" and r["pdf"]["size"] > 1000
        assert r["flat_note"] is True and r["overflow"] <= 0
        bad = [line for line in seen["console"] if line["type"] == "exception" or (line["type"] == "error" and "[workspace]" in line["text"])]
        assert bad == [], bad
        # the registry agrees with what the browser showed
        derivatives = [a for a in (await s.core.artifacts.query(__import__("jarvis.domain.artifacts", fromlist=["ArtifactQuery"]).ArtifactQuery(
            kinds=(ArtifactKind.PRESENTATION_VIDEO, ArtifactKind.PRESENTATION_STILL, ArtifactKind.PRESENTATION_PDF), limit=10))).items]
        assert sorted(a.kind.value for a in derivatives) == ["presentation_pdf", "presentation_still", "presentation_video"]
        assert all(a.state is ArtifactState.COMPLETE for a in derivatives) and (await s.core.artifacts.get(snapshot)).state is ArtifactState.COMPLETE
        described = await s.core.presentation_artifacts.describe_source(next(iter({x.metadata["source_presentation_id"] for x in [await s.core.artifacts.get(snapshot)]})))
        assert len(described["snapshots"][0]["renders"]) == 3 and home in described["board_ids"]
        assert not any(p for p in (Path(RUNTIME) / "render" / "jobs").glob("*/work"))
    finally:
        await close(s)
