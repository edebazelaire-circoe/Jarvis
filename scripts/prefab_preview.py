"""Rendu réel d'un ou plusieurs prefabs dans Chrome headless (aucun JARVIS lancé).

Construit, avec le vrai `buildSrcdoc` du runtime, le document de chaque cadre
(CSP, shell.css, style, template, shim, behavior), le pose dans un
`<iframe sandbox="allow-scripts" srcdoc>` à l'intérieur d'une fausse fenêtre de
la scène, répond `init` comme l'hôte, puis photographie la page.

    python scripts/prefab_preview.py scenario.json out.png [--size 1920x1080]

`scenario.json` : {"windows": [{"source": "dossier du prefab (manifest.json,
template.html, style.css, behavior.js)", "title": "...", "x": 40, "y": 40,
"w": 900, "h": 640, "data": {...}|null (sinon le sample), "props": {...},
"scale": 1, "click": ["sélecteur CSS", ...], "wait_ms": 1500}]}
`click` : sélecteurs cliqués dans le cadre après l'init (pour l'état replié,
le survol n'est pas simulable : utiliser :focus-visible via "focus").
"""
from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "jarvis" / "runtime" / "control_center_prefab_protocol.js"
LAYOUT = ROOT / "jarvis" / "runtime" / "control_center_scene_layout.js"
RUNTIME = ROOT / "jarvis" / "prefabs" / "runtime"
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

BUILD = r"""
const fs=require('fs');const P=require(process.argv[2]);
const spec=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const out=spec.map(s=>P.buildSrcdoc({files:s.files,runtime:{shim:s.shim,shell_css:s.shell}}));
fs.writeFileSync(process.argv[4],JSON.stringify(out));
"""

PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>preview</title>
<style>
html{color-scheme:dark}html,body{margin:0;height:100%;background:#02060a}
body{background:
 radial-gradient(1200px 700px at 18% 12%,rgba(60,120,160,.22),transparent 60%),
 radial-gradient(900px 600px at 85% 90%,rgba(40,70,140,.20),transparent 60%),#02060a;
 font:12px/1.4 ui-monospace,Consolas,monospace;color:#8aa5b3;overflow:hidden}
.win{position:absolute;display:flex;flex-direction:column;border:1px solid rgba(151,191,209,.18);border-radius:8px;
 background:rgba(4,10,15,.88);box-shadow:0 18px 60px rgba(0,0,0,.55);overflow:hidden}
.head{flex:none;display:flex;gap:8px;align-items:center;height:26px;padding:0 11px;color:#b3cbd6;
 border-bottom:1px solid rgba(151,191,209,.12);font-size:11px;letter-spacing:.04em}
.dot{width:7px;height:7px;border-radius:50%;background:#6ee7ff}
iframe{flex:1 1 auto;border:0;width:100%;min-height:0;background:transparent}
</style></head><body>
__WINDOWS__
<script>
const SPECS=__SPECS__;
const frames=[...document.querySelectorAll('iframe')];
window.addEventListener('message',(e)=>{
  const i=frames.findIndex(f=>f.contentWindow===e.source);
  if(i<0||!e.data||e.data.jv!==1)return;
  const s=SPECS[i];
  if(e.data.type==='ready'){
    e.source.postMessage({jv:1,type:'init',props:s.props,data:s.data,blocks:{},
      theme:{name:'scene',accent:'#6ee7ff',text:'#dcecf4',muted:'#8aa5b3',surface:'rgba(4,10,15,.88)',scale:s.scale},
      instance:{object_id:'preview_'+i,prefab:{id:s.id,version:1},mode:'preview'}},'*');
  }else if(e.data.type==='error'){
    const d=document.createElement('div');d.style.cssText='position:fixed;left:8px;bottom:8px;color:#f66;z-index:9;font:12px monospace';d.textContent='ERREUR cadre '+i+' : '+e.data.message;document.body.appendChild(d);
  }else if(e.data.type==='event'){
    window.__events=(window.__events||[]).concat([{i,name:e.data.name,payload:e.data.payload}]);
  }
});
</script></body></html>
"""


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("chrome.exe introuvable")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("out")
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    width, height = (int(v) for v in args.size.split("x"))
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    shim = (RUNTIME / "shim.js").read_text(encoding="utf-8")
    shell = (RUNTIME / "shell.css").read_text(encoding="utf-8")
    specs, nodes = [], []
    for w in scenario["windows"]:
        src = (ROOT / w["source"]) if not Path(w["source"]).is_absolute() else Path(w["source"])
        manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
        files = {k: (src / f"{k if k != 'template' else 'template'}.{ext}").read_text(encoding="utf-8")
                 for k, ext in (("template", "html"), ("style", "css"), ("behavior", "js"))}
        specs.append({"files": files, "shim": shim, "shell": shell})
        nodes.append({"id": manifest["id"], "scale": w.get("scale", 1),
                      "props": w.get("props") or manifest["sample"]["props"],
                      "data": w.get("data") or manifest["sample"]["data"]})
    tmp = Path(tempfile.mkdtemp(prefix="jv-preview-"))
    (tmp / "spec.json").write_text(json.dumps(specs), encoding="utf-8")
    (tmp / "build.cjs").write_text(BUILD, encoding="utf-8")
    subprocess.run(["node", str(tmp / "build.cjs"), str(PROTOCOL), str(tmp / "spec.json"), str(tmp / "srcdocs.json")], check=True)
    srcdocs = json.loads((tmp / "srcdocs.json").read_text(encoding="utf-8"))
    blocks = []
    for i, (w, doc) in enumerate(zip(scenario["windows"], srcdocs)):
        blocks.append(
            f'<div class="win" style="left:{w.get("x",40)}px;top:{w.get("y",40)}px;width:{w.get("w",800)}px;height:{w.get("h",600)}px">'
            f'<div class="head"><span class="dot"></span><span>{html.escape(w.get("title","fenêtre"))}</span></div>'
            f'<iframe sandbox="allow-scripts" srcdoc="{html.escape(doc, quote=True)}"></iframe></div>')
    page = PAGE.replace("__WINDOWS__", "\n".join(blocks)).replace("__SPECS__", json.dumps(nodes))
    (tmp / "page.html").write_text(page, encoding="utf-8")
    wait = max([w.get("wait_ms", 2600) for w in scenario["windows"]] or [2600])
    actions = [{"wait": wait}] + scenario.get("actions", [])
    (tmp / "actions.json").write_text(json.dumps(actions), encoding="utf-8")
    subprocess.run(["node", str(ROOT / "scripts" / "prefab_shot.cjs"), find_chrome(), str(tmp / "page.html"),
                    str(Path(args.out).resolve()), str(width), str(height), str(tmp / "actions.json")],
                   check=True, timeout=180)
    print(f"{args.out} ({width}x{height}), page: {tmp / 'page.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
