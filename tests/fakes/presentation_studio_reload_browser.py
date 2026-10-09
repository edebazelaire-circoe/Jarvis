"""Pont de test entre un VRAI Chrome et les VRAIS services du rechargement a chaud (jarvis-interactive-presentation-studio, Slice 06).

Le navigateur charge une page minimale qui embarque les VRAIS modules du Control Center (`control_center_prefab_protocol.js`,
`control_center_prefab_host.js`, `control_center_presentation_studio_reload.js`) et la meme logique de synchronisation de scene
que la page de scene (`JarvisPrefabHost.syncScene`). Le serveur local (`Bridge`) est le Control Center reduit a ce que la page
appelle : paquets de prefab (`PrefabService.bundle`), instantane de la scene globale (`SceneService`), evenements d'etat des
cadres (`PrefabEventService`), et les routes du Studio (`apply_source_edit`, rapports de montage, rechargements recents), sur
les services reels du `Rig`. En-tete `Content-Security-Policy: frame-src 'none'` comme le vrai Control Center.

Aucun double dans la boucle navigateur -> Core -> navigateur : un cadre qui ne monte pas est un cadre qui ne monte pas.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import tempfile

import pytest
from aiohttp import web

from jarvis.core.prefab_events import PrefabEventService, PrefabEventsRateLimited
from jarvis.domain.presentation_studio import PresentationStudioError

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
HARNESS = ROOT / "tests" / "unit" / "_presentation_studio_reload_browser.mjs"

CHROME_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
)


def chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    pytest.skip("Chrome absent")


def _inline(name: str) -> str:
    return (RUNTIME / name).read_text(encoding="utf-8")


PAGE = """<!doctype html><html lang="fr"><meta charset="utf-8"><title>studio reload bridge</title>
<style>
:root{--panel:#0b1620;--line:#183343;--text:#d8edf7;--muted:#7190a0;--accent:#6ee7ff;--danger:#ff6577;--ok:#68e0a0;--warn:#ffb85c}
html,body{margin:0;background:#101820;font:14px system-ui,sans-serif;color:#cde}
#stage{display:flex;flex-wrap:wrap;gap:12px;padding:12px;align-items:flex-start}
.win{position:relative;width:300px;min-height:120px;box-sizing:border-box;display:flex;flex-direction:column;background:#0b1620;
  border:2px solid #2a8;border-radius:10px}
.win .sc-title{flex:none;padding:6px 10px;box-sizing:border-box}
</style>
<div id="stage"></div>
<script>__PROTOCOL__</script>
<script>__LAYOUT__</script>
<script>__HOST__</script>
<script>window.__toasts=[];function toast(t){window.__toasts.push(t)}</script>
<script>__RELOAD__</script>
<script>
window.__hostLog=[];window.__events=[];window.__outcomes=[];window.__posts=[];
const post=async(path,body)=>{
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const json=await response.json().catch(()=>null);
  if(!response.ok)throw Object.assign(new Error((json&&json.error&&json.error.message)||('HTTP '+response.status)),{code:json&&json.error&&json.error.code});
  return json;
};
const studio=JarvisStudioReload.instance;
const host=JarvisPrefabHost.createPrefabHost({document,window,swapPrefix:'presentation-studio.',
  log:(k,d)=>window.__hostLog.push([k,d]),
  fetchBundle:JarvisPrefabHost.bundleFetcher((path,options)=>fetch(path,Object.assign({cache:'no-store'},options))),
  postEvent:async(event)=>{window.__events.push(event);return post('/api/prefabs/events',Object.assign({actor:'user'},event))},
  onOutcome:(info)=>{window.__outcomes.push(info);return studio.hostOutcome(info)}});
window.__host=host;
const records=new Map();
const stage=document.getElementById('stage');
let revision=-1;
async function tick(){
  const response=await fetch('/api/scene',{cache:'no-store'});
  const scene=await response.json();
  if(scene.revision===revision)return;
  revision=scene.revision;
  const seen=new Set();
  for(const obj of scene.objects){
    seen.add(obj.id);
    let rec=records.get(obj.id);
    if(!rec){
      const el=document.createElement('div');el.className='win';el.dataset.objectId=obj.id;
      const head=document.createElement('div');head.className='sc-title';head.textContent=obj.title;el.appendChild(head);
      stage.appendChild(el);
      rec={el,prefabKey:'',prefabSlot:null};records.set(obj.id,rec);
    }
    JarvisPrefabHost.syncScene(host,rec,rec.el,{id:obj.id,shape:'window',title:obj.title,prefab:obj.prefab,
      prefabKey:obj.prefab.id+'@'+obj.prefab.version});
  }
  for(const [id,rec] of records){if(!seen.has(id)){host.unmount(id);rec.el.remove();records.delete(id)}}
}
let ticking=false;
setInterval(async()=>{if(ticking)return;ticking=true;try{await tick()}catch(error){console.error('tick failed '+error.message)}finally{ticking=false}},50);
window.__records=records;
window.__post=post;
tick().then(()=>{window.__bridgeReady=true});
</script></html>
"""


class Bridge:
    """Serveur local d'une page de test : voir l'en-tete du module. `async with Bridge(rig) as bridge`."""

    def __init__(self, rig) -> None:
        self.rig = rig
        self.hits: dict[str, int] = {}
        self.requests: list[tuple[str, str]] = []
        self.events = PrefabEventService(rig.scene, rig.prefabs, diagnostics=rig.sink)
        app = web.Application()
        app.add_routes([
            web.get("/", self.index), web.get("/api/scene", self.scene),
            web.get("/api/prefabs/{prefab_id}/{version}/bundle", self.bundle),
            web.post("/api/prefabs/events", self.prefab_event),
            web.get("/secret", self.secret), web.get("/secret/{rest:.*}", self.secret),
            web.post("/api/presentation-studio/presentations/mount-reports", self.mount_report),
            web.post("/api/presentation-studio/presentations/{pid}/variants/{vid}/source-edits", self.source_edit),
            web.get("/api/presentation-studio/presentations/{pid}/reloads", self.reloads),
        ])
        self._runner = web.AppRunner(app)
        self.url = ""

    async def __aenter__(self) -> Bridge:
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = self._runner.addresses[0][1]
        self.url = f"http://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *exc) -> None:
        await self._runner.cleanup()

    # ------------------------------------------------------------ routes

    async def index(self, request: web.Request) -> web.Response:
        html = (PAGE.replace("__PROTOCOL__", _inline("control_center_prefab_protocol.js"))
                .replace("__LAYOUT__", _inline("control_center_scene_layout.js"))
                .replace("__HOST__", _inline("control_center_prefab_host.js"))
                .replace("__RELOAD__", _inline("control_center_presentation_studio_reload.js")))
        return web.Response(text=html, content_type="text/html",
                            headers={"Content-Security-Policy": "frame-src 'none'", "Cache-Control": "no-store"})

    async def scene(self, request: web.Request) -> web.Response:
        snapshot = await self.rig.scene.snapshot()
        objects = [{"id": item.object_id, "title": item.payload.title or item.object_id,
                    "prefab": {"id": item.payload.prefab.prefab_id, "version": item.payload.prefab.version,
                               "props": dict(item.payload.prefab.props), "data": dict(item.payload.prefab.data)}}
                   for item in snapshot.objects if item.payload.prefab is not None]
        return web.json_response({"revision": snapshot.revision, "objects": objects})

    async def bundle(self, request: web.Request) -> web.Response:
        info = request.match_info
        self.requests.append(("bundle", f"{info['prefab_id']}@{info['version']}"))
        try:
            return web.json_response(await self.rig.prefabs.bundle(info["prefab_id"], int(info["version"])))
        except Exception as exc:  # noqa: BLE001 - the test bridge answers like the relay: a coded envelope
            code = getattr(getattr(exc, "code", None), "value", "bundle_failed")
            return web.json_response({"error": {"code": code, "message": str(exc)[:200]}}, status=404)

    async def prefab_event(self, request: web.Request) -> web.Response:
        try:
            result = await self.events.submit(await request.json())
        except PrefabEventsRateLimited as exc:
            return web.json_response({"error": {"code": "rate_limited", "message": str(exc)}}, status=429)
        except ValueError as exc:
            return web.json_response({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
        return web.json_response(result.to_dict())

    async def secret(self, request: web.Request) -> web.Response:
        """Ce qu'un cadre hostile voudrait joindre : il ne doit JAMAIS etre appele."""

        self.hits[request.path] = self.hits.get(request.path, 0) + 1
        return web.json_response({"secret": True})

    async def mount_report(self, request: web.Request) -> web.Response:
        try:
            return web.json_response(await self.rig.reload.handle_mount_report(await request.json()))
        except PresentationStudioError as exc:
            return web.json_response({"error": {"code": exc.code.value, "message": exc.message}}, status=exc.status)

    async def source_edit(self, request: web.Request) -> web.Response:
        body = await request.json()
        body["actor"] = "user"          # the relay forces it
        try:
            result = await self.rig.reload.apply_source_edit(request.match_info["pid"], request.match_info["vid"], body)
        except PresentationStudioError as exc:
            return web.json_response({"error": {"code": exc.code.value, "message": exc.message}}, status=exc.status)
        return web.json_response(result.to_dict(), status=result.http_status)

    async def reloads(self, request: web.Request) -> web.Response:
        return web.json_response({"reloads": self.rig.reload.recent(request.match_info["pid"]),
                                  "stats": self.rig.reload.stats(), "pending": []})


async def drive(bridge: Bridge, tmp_path: Path, plan: list, *, timeout: float = 180) -> dict:
    """Execute `plan` dans un vrai Chrome (harnais CDP) contre le pont ; rend `{reads, console, errors, sessions}`."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    plan_file = Path(tempfile.mkstemp(suffix=".json", dir=tmp_path)[1])
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    process = await asyncio.create_subprocess_exec(node, str(HARNESS), bridge.url + "/", chrome(), str(plan_file),
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        raise
    assert process.returncode == 0, err.decode("utf-8", "replace")
    return json.loads(out.decode("utf-8"))
