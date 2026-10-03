"""Banc node des modules JS du runtime des prefabs (prefab-foundation, Slice 03).

Même motif que `run_node` de `tests/unit/test_scene_interaction_logic.py` : un
script `.cjs` écrit dans `tmp_path`, des données JSON à côté, la valeur rendue
par le corps imprimée en JSON. Le prélude charge les vrais modules
(`Lay` = `JarvisSceneLayout`, `P` = `JarvisPrefabProtocol`, `H` =
`JarvisPrefabHost`, `Shim` = fabrique du shim) et un faux DOM minimal :
nœuds, attributs, style, écouteurs, sélecteurs d'attribut, cadre
(`contentWindow.posted`, `srcdoc` enregistré avec l'attribut `sandbox` du
moment, `load()` pour l'événement `load` d'un document chargé), fenêtre
(`dispatch`, `open`), horloge et minuteries manuelles.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
LAYOUT_JS = RUNTIME / "control_center_scene_layout.js"
PROTOCOL_JS = RUNTIME / "control_center_prefab_protocol.js"
HOST_JS = RUNTIME / "control_center_prefab_host.js"
SHIM_JS = ROOT / "jarvis" / "prefabs" / "runtime" / "shim.js"
SHELL_CSS = ROOT / "jarvis" / "prefabs" / "runtime" / "shell.css"

PRELUDE = r"""
const Lay=require(PATHS.layout);
const P=require(PATHS.protocol);
const H=require(PATHS.host);
const Shim=require(PATHS.shim);
const flush=async(n)=>{for(let i=0;i<(n||6);i++)await new Promise(r=>setImmediate(r))};

class FakeStyle{
  constructor(){this.vars={}}
  setProperty(k,v){this.vars[k]=String(v)}
  removeProperty(k){delete this.vars[k]}
  getPropertyValue(k){return this.vars[k]||''}
}
class FakeText{
  constructor(text){this.nodeType=3;this.data=String(text);this.parentNode=null}
  get textContent(){return this.data}
  set textContent(v){this.data=String(v)}
}
class FakeEl{
  constructor(tag,doc){
    this.tagName=String(tag).toUpperCase();this.ownerDocument=doc;this.nodeType=1;this.childNodes=[];this.parentNode=null;
    this.attributes={};this.style=new FakeStyle();this.listeners={};this.className='';this.id='';
    const self=this;
    this.classList={add(...n){const s=new Set(self.className.split(/\s+/).filter(Boolean));n.forEach(x=>s.add(x));self.className=[...s].join(' ')},
      contains(n){return self.className.split(/\s+/).includes(n)}};
  }
  get children(){return this.childNodes.filter(n=>n.nodeType===1)}
  get firstChild(){return this.childNodes[0]||null}
  _detach(c){if(c.parentNode){const k=c.parentNode.childNodes;k.splice(k.indexOf(c),1);c.parentNode=null}}
  appendChild(c){this._detach(c);c.parentNode=this;this.childNodes.push(c);return c}
  insertBefore(c,ref){this._detach(c);c.parentNode=this;const at=ref?this.childNodes.indexOf(ref):-1;
    if(at<0)this.childNodes.push(c);else this.childNodes.splice(at,0,c);return c}
  removeChild(c){const at=this.childNodes.indexOf(c);if(at<0)throw new Error('not a child');this.childNodes.splice(at,1);c.parentNode=null;return c}
  remove(){if(this.parentNode)this.parentNode.removeChild(this)}
  replaceChildren(...nodes){for(const c of this.childNodes.slice())this.removeChild(c);nodes.forEach(n=>this.appendChild(n))}
  setAttribute(k,v){this.attributes[k]=String(v);if(k==='id')this.id=String(v)}
  getAttribute(k){return Object.prototype.hasOwnProperty.call(this.attributes,k)?this.attributes[k]:null}
  hasAttribute(k){return Object.prototype.hasOwnProperty.call(this.attributes,k)}
  addEventListener(t,fn){(this.listeners[t]=this.listeners[t]||[]).push(fn)}
  removeEventListener(t,fn){const l=this.listeners[t]||[];const at=l.indexOf(fn);if(at>=0)l.splice(at,1)}
  click(){const ev={type:'click',defaultPrevented:false,preventDefault(){this.defaultPrevented=true},stopPropagation(){}};
    (this.listeners.click||[]).slice().forEach(fn=>fn(ev));return ev}
  key(k){const ev={type:'keydown',key:k,defaultPrevented:false,preventDefault(){this.defaultPrevented=true}};
    (this.listeners.keydown||[]).slice().forEach(fn=>fn(ev));return ev}
  get textContent(){return this.childNodes.map(n=>n.textContent).join('')}
  set textContent(v){this.replaceChildren();if(v!==''&&v!==null&&v!==undefined)this.appendChild(new FakeText(v))}
  descendants(){const out=[];const walk=n=>{for(const c of n.childNodes)if(c.nodeType===1){out.push(c);walk(c)}};walk(this);return out}
  querySelectorAll(sel){const m=/^\[([a-z-]+)\]$/.exec(sel);if(!m)throw new Error('unsupported selector '+sel);
    return this.descendants().filter(n=>n.hasAttribute(m[1]))}
  find(pred){return this.descendants().find(pred)||null}
  byClass(name){return this.descendants().filter(n=>n.classList.contains(name))}
  getBoundingClientRect(){return {height:this._height||0}}
}
class FakeFrameWindow{constructor(){this.posted=[]}postMessage(m,target){this.posted.push({message:JSON.parse(JSON.stringify(m)),target})}}
class FakeIframe extends FakeEl{
  constructor(doc){super('iframe',doc);this.contentWindow=new FakeFrameWindow();this.srcdocWrites=[]}
  set srcdoc(v){this.srcdocWrites.push({value:String(v),sandbox:this.getAttribute('sandbox')});this._srcdoc=String(v)}
  get srcdoc(){return this._srcdoc}
  /* Un document chargé dans le cadre (le `srcdoc`, puis toute navigation) : l'événement `load` de l'élément. */
  load(){(this.listeners.load||[]).slice().forEach(fn=>fn({type:'load',target:this}))}
}
class FakeDocument{
  constructor(){this.head=new FakeEl('head',this);this.body=new FakeEl('body',this);this.documentElement=new FakeEl('html',this);
    this.created=[];this.listeners={}}
  createElement(tag){const el=String(tag).toLowerCase()==='iframe'?new FakeIframe(this):new FakeEl(tag,this);this.created.push(el);return el}
  createTextNode(t){return new FakeText(t)}
  getElementById(id){return [this.head,this.body,...this.head.descendants(),...this.body.descendants()].find(n=>n.id===id)||null}
  querySelectorAll(sel){return this.body.querySelectorAll(sel)}
  addEventListener(t,fn){(this.listeners[t]=this.listeners[t]||[]).push(fn)}
}
class FakeWindow{
  constructor(){this.listeners={};this.opened=[]}
  addEventListener(t,fn){(this.listeners[t]=this.listeners[t]||[]).push(fn)}
  removeEventListener(t,fn){const l=this.listeners[t]||[];const at=l.indexOf(fn);if(at>=0)l.splice(at,1)}
  count(t){return (this.listeners[t]||[]).length}
  dispatch(event){(this.listeners.message||[]).slice().forEach(fn=>fn(event))}
  open(url,target,features){this.opened.push({url,target,features});return null}
}
function clock(){
  const c={t:1000,timers:[],seq:0};
  c.now=()=>c.t;
  c.setTimeout=(fn,ms)=>{const id=++c.seq;c.timers.push({id,at:c.t+ms,fn});return id};
  c.clearTimeout=(id)=>{c.timers=c.timers.filter(x=>x.id!==id)};
  c.advance=(ms)=>{c.t+=ms;for(;;){const due=c.timers.filter(x=>x.at<=c.t).sort((a,b)=>a.at-b.at)[0];if(!due)break;
    c.timers=c.timers.filter(x=>x!==due);due.fn()}};
  return c;
}
/* Banc d'hôte : document, fenêtre, horloge, journal, événements postés, paquets servis. */
function bench(opts){
  const o=opts||{};
  const doc=new FakeDocument(),win=new FakeWindow(),c=clock(),logs=[],posted=[],preview=[],fetches=[],resizes=[];
  const bundles=o.bundles||(D&&D.bundles)||{};
  const host=H.createPrefabHost({
    document:doc,window:win,now:c.now,setTimeout:c.setTimeout,clearTimeout:c.clearTimeout,mode:o.mode,
    log:(k,d)=>logs.push({key:k,data:d}),
    postEvent:o.noSink?undefined:(e)=>{posted.push(e);return o.postEvent?o.postEvent(e):Promise.resolve({outcome:'applied'})},
    onPreviewEvent:(e)=>preview.push(e),onResize:(id,h)=>resizes.push([id,h]),
    fetchBundle:o.fetchBundle||((id,v)=>{fetches.push(`${id}@${v}`);const b=bundles[`${id}@${v}`];
      return b?Promise.resolve(JSON.parse(JSON.stringify(b))):Promise.reject(new Error(`unknown_prefab: no prefab ${id}`))})
  });
  const slot=()=>{const s=doc.createElement('div');doc.body.appendChild(s);return s};
  const frameOf=(s)=>s.children.find(n=>n.tagName==='IFRAME')||null;
  const send=(s,data,origin)=>win.dispatch({source:frameOf(s).contentWindow,origin:origin===undefined?'null':origin,data});
  const inbox=(s)=>frameOf(s).contentWindow.posted.map(p=>p.message);
  return {host,doc,win,clock:c,logs,posted,preview,fetches,resizes,slot,frameOf,send,inbox};
}
const instance=(id,extra)=>Object.assign({object_id:id,title:'Counter '+id,prefab:{id:'test.counter',version:1},
  props:{label:'Count'},data:{count:3,notes:'**bold** note'}},extra||{});
"""


def run_node(tmp_path: Path, body: str, data: Any = None) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    paths = {"layout": str(LAYOUT_JS), "protocol": str(PROTOCOL_JS), "host": str(HOST_JS), "shim": str(SHIM_JS)}
    index = len(list(tmp_path.glob("prefab-js-*.cjs")))
    data_file = tmp_path / f"prefab-js-{index}.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / f"prefab-js-{index}.cjs"
    script.write_text(
        f"const PATHS={json.dumps(paths)};\n"
        f"const D=JSON.parse(require('fs').readFileSync({json.dumps(str(data_file))},'utf8'));\n"
        + PRELUDE
        + "(async()=>{\n" + body + "\n})().then(v=>console.log(JSON.stringify(v)),e=>{console.error(e&&e.stack||e);process.exit(1)});\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


async def catalogue_bundles(tmp_path: Path, *prefab_ids: str) -> dict[str, Any]:
    """Paquets `id@1` servis par le vrai catalogue (`PrefabService.bundle`) depuis les fixtures publiées.

    Aucune ligne de code ne nomme ces prefabs : ils passent par le seul chemin
    du catalogue (bibliothèque sur disque + runtime livré).
    """

    from jarvis.adapters.file_prefab_library import FilePrefabLibrary, FilePrefabRuntime
    from jarvis.core.prefab_service import PrefabService
    from tests.fakes.prefabs import candidate, install_version

    package, data = tmp_path / "bundle-package", tmp_path / "bundle-data"
    package.mkdir()
    for prefab_id in prefab_ids:
        install_version(data / "prefabs", prefab_id, 1, source=candidate(prefab_id))
    service = PrefabService(FilePrefabLibrary(package, data), runtime=FilePrefabRuntime(SHIM_JS.parent))
    return {f"{prefab_id}@1": await service.bundle(prefab_id, 1) for prefab_id in prefab_ids}
