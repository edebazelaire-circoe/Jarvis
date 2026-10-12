"""Bench of the rendered-frame quality gates (handoff jarvis-remotion-native-studio-playback-fix, Slice 14).

Reuses, never rebuilds: `RemotionStack` (real Core, Control Center, sandbox on free ports, throw-away data root), the Slice 03 gate deck
(`presentation_playback_gate_world.make_deck`), the real guarded render host through Core's preview route
(`POST /v1/local-capabilities/remotion/render/preview`, Slice 13), the pinned ffmpeg of the runtime (`remotion_media_tools`) and the pure
detectors (`jarvis.media.frame_quality`). Adds only:

- `quality_options`: the stack's Core with the real `RemotionRenderRunner` on the stack's own runtime folder (never the live one);
- `native_deck`: a Slice 13 native deck (`slices/13-.../evidence/runs/<run>/sources/deck1`, the real TSX the agent wrote) loaded as
  prefabs and a presentation;
- `control_deck`: the positive controls (a black scene, text running out of the frame, a missing font, a missing image, a still card
  that fades out): every detector must fire on it;
- `smoke_deck`: the smoke path of step 1, first / entry / middle / exit / last frame of every scene through the preview route, then the
  detectors, a per-scene contact sheet and a transition sheet (last frame of a scene beside the first of the next);
- `SCENE_DOM_PROBE`: the page probe (fonts, assets, text out of the frame) evaluated in every live sandbox page of the Variants Player.

Evidence goes to `JARVIS_QUALITY_EVIDENCE_DIR` when set, home path and user name masked (`presentation_playback_gate_world.redact`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import time
from typing import Any

from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.adapters.remotion_media_tools import compositor_tool, contact_sheet, decode_gray
from jarvis.adapters.remotion_render_runner import RemotionRenderRunner
from jarvis.domain.remotion_source import Composition, build_candidate
from jarvis.media import frame_quality as Q
from tests.fakes.remotion_player_stack import RemotionStack
from tests.unit.presentation_playback_gate_world import harness, redact

PREVIEW = "/v1/local-capabilities/remotion/render/preview"
BASE = "/v1/presentation-studio/presentations"
REPO = Path(__file__).resolve().parents[2]
NATIVE_RUNS = REPO / "tasks" / "jarvis-remotion-native-studio-playback-fix" / "slices" / "13-claude-native-generation-parity" / "evidence" / "runs"
#: Preview scale of the smoke: 640x360 for a 1280x720 scene, 960x540 for 1920x1080 (the detectors work at `Q.WORK_WIDTH` anyway).
SMOKE_SCALE = 0.5


def quality_options(stack: RemotionStack) -> dict[str, Any]:
    return {"remotion_render_runner": RemotionRenderRunner(lambda: stack.data_root / "local_capabilities" / "remotion" / "runtime")}


def media_tools(runtime: Path) -> tuple[Path, Path]:
    ffmpeg, ffprobe = compositor_tool(runtime, "ffmpeg"), compositor_tool(runtime, "ffprobe")
    harness(ffmpeg and ffprobe, f"no pinned ffmpeg/ffprobe under the runtime's @remotion/compositor-* ({runtime.name})")
    return ffmpeg, ffprobe  # type: ignore[return-value]


def evidence_dir() -> Path | None:
    raw = os.environ.get("JARVIS_QUALITY_EVIDENCE_DIR")
    if not raw:
        return None
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_evidence(name: str, payload: Any, files: dict[str, Path] | None = None) -> None:
    folder = evidence_dir()
    if folder is None:
        return
    (folder / f"{name}.json").write_text(redact(json.dumps(payload, indent=1, ensure_ascii=False, default=str)), encoding="utf-8")
    for target, source in (files or {}).items():
        if source.is_file():
            shutil.copyfile(source, folder / target)


# ------------------------------------------------------------------ decks


async def _save_scene(stack: RemotionStack, prefab_id: str, *, title: str, composition: Composition, files: dict[str, str],
                      props: dict, sample: dict) -> int:
    saved = await stack.core.prefabs.save(build_candidate(prefab_id=prefab_id, title=title, composition=composition, engine=shipped_engine_pin(),
                                                          files=files, props=props, sample=sample), actor="user")
    return saved.version


async def native_deck(stack: RemotionStack, run: str = "jn4") -> tuple[str, str, list[str]]:
    """The final deck of a Slice 13 Jarvis run, from its committed sources (manifest + `src/**`). Returns `(pid, vid, scene titles)`."""

    root = NATIVE_RUNS / run / "sources" / "deck1"
    meta = json.loads((NATIVE_RUNS / run / "meta.json").read_text(encoding="utf-8"))
    order = [s["scene_id"] for s in meta["decks"][0]["variants"][0]["scenes"]]
    scenes, titles = [], []
    for index, scene_id in enumerate(order, start=1):
        folder = root / scene_id
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        comp = manifest["source"]["composition"]
        files = {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8") for p in sorted((folder / "src").rglob("*")) if p.is_file()}
        prefab_id = f"presentation-studio.p0000000000c1.s{index:012d}"
        version = await _save_scene(stack, prefab_id, title=manifest["title"], composition=Composition(
            comp["id"], comp["width"], comp["height"], comp["fps"], comp["duration_in_frames"]), files=files,
            props=manifest["inputs"]["props"], sample=manifest["sample"])
        scenes.append({"scene_id": f"pss_{index:012d}", "prefab": {"id": prefab_id, "version": version}, "title": manifest["title"],
                       "props": manifest["sample"]["props"], "data": {}})
        titles.append(manifest["title"])
    pid, vid = await stack.presentation(scenes, title=meta["decks"][0]["title"])
    return pid, vid, titles


_CONTROL_HEAD = 'import React from "react";\nimport {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";\n\n'
#: (title, body of `Scene`, what must be found). 1280x720, 30 i/s, 1 s each: the positive controls of every detector.
CONTROL_SCENES: list[tuple[str, str, set[str]]] = [
    ("Noir", 'export default function Scene() {\n  return <AbsoluteFill style={{background: "#000000"}} />;\n}\n', {"black"}),
    ("Debordement",
     'export default function Scene() {\n  const frame = useCurrentFrame();\n  return (\n    <AbsoluteFill style={{background: "#203040"}}>\n'
     '      <p style={{position: "absolute", left: 760, top: 260, fontSize: 96, color: "#ffffff", whiteSpace: "nowrap", margin: 0}}>'
     'Un titre beaucoup trop long {frame}</p>\n    </AbsoluteFill>\n  );\n}\n', {"edge_text_overflow", "text_overflow"}),
    ("Police absente",
     'export default function Scene() {\n  const frame = useCurrentFrame();\n  return (\n    <AbsoluteFill style={{background: "#302040", padding: 60}}>\n'
     '      <p style={{fontFamily: "JarvisNoSuchFont", fontSize: 72, color: "#ffffff", margin: 0}}>Police absente {frame}</p>\n'
     '      <p style={{fontFamily: "JarvisNoSuchFontToo, sans-serif", fontSize: 48, color: "#ffffff"}}>Repli voulu</p>\n'
     '      <style>{"@font-face{font-family:JarvisMissingFace;src:url(jarvis-missing-face.woff2)}"}</style>\n'
     '      <p style={{fontFamily: "JarvisMissingFace, serif", fontSize: 48, color: "#ffffff"}}>Fichier de police absent</p>\n'
     '    </AbsoluteFill>\n  );\n}\n', {"font_fallback", "font_substituted", "font_load_failed"}),
    ("Image absente",
     'export default function Scene() {\n  const frame = useCurrentFrame();\n  return (\n    <AbsoluteFill style={{background: "#204030", padding: 60}}>\n'
     '      <p style={{fontSize: 64, color: "#ffffff", margin: 0}}>Image absente {frame}</p>\n'
     '      <img src="jarvis-missing-asset.png" style={{width: 200, height: 120}} />\n    </AbsoluteFill>\n  );\n}\n', {"asset_missing"}),
    ("Carte fixe",
     'export default function Scene() {\n  const frame = useCurrentFrame();\n'
     '  const opacity = interpolate(frame, [20, 29], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});\n'
     '  return (\n    <AbsoluteFill style={{background: "#404020", padding: 60, opacity}}>\n'
     '      <p style={{fontSize: 72, color: "#ffffff", margin: 0}}>Une carte immobile</p>\n    </AbsoluteFill>\n  );\n}\n',
     {"black"}),
]
CONTROL_PROPS = {"type": "object", "properties": {"title": {"type": "string", "default": "Controle", "max_length": 80}}}


async def control_deck(stack: RemotionStack) -> tuple[str, str, list[str]]:
    scenes, titles = [], []
    for index, (title, body, _expected) in enumerate(CONTROL_SCENES, start=1):
        prefab_id = f"presentation-studio.p0000000000d1.s{index:012d}"
        version = await _save_scene(stack, prefab_id, title=title, composition=Composition("Scene", 1280, 720, 30, 30),
                                    files={"src/Scene.tsx": _CONTROL_HEAD + body}, props=CONTROL_PROPS,
                                    sample={"props": {"title": title}, "data": {}})
        scenes.append({"scene_id": f"pss_{index:012d}", "prefab": {"id": prefab_id, "version": version}, "title": title,
                       "props": {"title": title}, "data": {}})
        titles.append(title)
    pid, vid = await stack.presentation(scenes, title="Controles qualite")
    return pid, vid, titles


# ------------------------------------------------------------------ the smoke path (step 1) and the frame detectors (step 2)


async def scene_list(stack: RemotionStack, pid: str) -> tuple[str, list[dict[str, Any]]]:
    """`(variant_id, [{scene_id, title, composition}])` of the active variant, compositions read from each scene's source manifest."""

    status, doc = await stack.call("GET", f"{BASE}/{pid}")
    harness(status == 200, f"presentation unreadable: {doc}")
    vid = doc["presentation"]["active_variant_id"]
    variant = next(v for v in doc["variants"] if v["variant_id"] == vid)
    out = []
    for scene in variant["scenes"]:
        status, source = await stack.call("GET", f"{BASE}/{pid}/variants/{vid}/scenes/{scene['scene_id']}/source")
        harness(status == 200, f"scene source unreadable: {source}")
        out.append({"scene_id": scene["scene_id"], "title": scene.get("title"), "composition": source["manifest"]["source"]["composition"]})
    return vid, out


async def smoke_deck(stack: RemotionStack, pid: str, *, ffmpeg: Path, work: Path, profile: Q.Profile, name: str) -> dict[str, Any]:
    """Step 1 + 2 on one deck: every scene's smoke frames rendered by the guarded host (one preview per scene), decoded, measured; the
    per-scene sheet (`<name>-contact.jpg`, one row per scene: first, entry, middle, exit, last) and the transition sheet
    (`<name>-transitions.jpg`, one row per hand-over: last frame of scene k, first frame of scene k+1)."""

    vid, scenes = await scene_list(stack, pid)
    work.mkdir(parents=True, exist_ok=True)
    findings: list[Q.Finding] = []
    rows: list[dict[str, Any]] = []
    sheet_cells: list[Path | None] = []
    ends: dict[str, tuple[Path, Path]] = {}
    for index, scene in enumerate(scenes):
        label = f"S{index + 1}"
        comp = scene["composition"]
        picks = Q.smoke_frames(int(comp["duration_in_frames"]))
        started = time.monotonic()
        status, body = await stack.call("POST", PREVIEW, json={"presentation_id": pid, "variant_id": vid, "scene_id": scene["scene_id"],
                                                               "frames": [f for f, _r in picks], "scale": SMOKE_SCALE})
        took = round(time.monotonic() - started, 1)
        if status != 200:
            error = body.get("error") if isinstance(body, dict) else body
            findings.append(Q.Finding("render_failed", Q.Severity.BLOCKING, f"the guarded render host refused or failed: {error}", label))
            rows.append({"scene": label, "scene_id": scene["scene_id"], "title": scene["title"], "composition": comp, "http": status,
                         "error": error, "preview_s": took})
            sheet_cells += [None] * 5
            continue
        frames = {item["frame"]: Path(item["path"]) for item in body["preview"]["frames"]}
        measured, decoded = [], []
        for frame, role in picks:
            local = work / f"{name}-{label}-f{frame:05d}.jpg"
            shutil.copyfile(frames[frame], local)
            gray = decode_gray(ffmpeg, local)
            metrics = Q.measure(gray)
            found = Q.frame_findings(metrics, role=role, profile=profile, scene=label, frame=frame)
            findings += found
            decoded.append((frame, gray))
            measured.append({"frame": frame, "role": role.value, "metrics": metrics.to_dict(), "findings": [f.code for f in found]})
        findings += Q.repeated_findings(decoded, scene=label)
        ends[label] = (work / f"{name}-{label}-f{picks[0][0]:05d}.jpg", work / f"{name}-{label}-f{picks[-1][0]:05d}.jpg")
        by_role = {role: work / f"{name}-{label}-f{frame:05d}.jpg" for frame, role in picks}
        sheet_cells += [by_role.get(role) for role in (Q.Role.FIRST, Q.Role.ENTRY, Q.Role.MIDDLE, Q.Role.EXIT, Q.Role.LAST)]
        rows.append({"scene": label, "scene_id": scene["scene_id"], "title": scene["title"], "composition": comp, "http": status,
                     "preview_s": took, "render_elapsed_ms": body["preview"]["elapsed_ms"], "frames": measured})
    contact = contact_sheet(ffmpeg, sheet_cells, columns=5, out=work / f"{name}-contact.jpg")
    pairs: list[Path | None] = []
    labels = [f"S{i + 1}" for i in range(len(scenes))]
    for a, b in zip(labels, labels[1:]):
        pairs += [ends[a][1] if a in ends else None, ends[b][0] if b in ends else None]
    transitions = contact_sheet(ffmpeg, pairs, columns=2, out=work / f"{name}-transitions.jpg") if pairs else None
    return {"deck": name, "presentation_id": pid, "variant_id": vid, "profile": profile.value, "scale": SMOKE_SCALE, "scenes": rows,
            "findings": findings, "contact": contact, "transitions": transitions}


# ------------------------------------------------------------------ the scene's page (fonts, assets, text out of the frame)

#: Evaluated with `scope: "sandboxes"` in every live sandbox page (`/page/scene-...`). The composition box is the Player's scaled
#: container (the first element under `#root` with a transform); overflow is measured in composition pixels. A family is available when
#: drawing it differs from at least one generic family (canvas width, the classic font-availability test).
SCENE_DOM_PROBE = r"""(()=>{const out={page:location.pathname,text:'',fonts:[],assets:[],overflow:[]};const root=document.getElementById('root');if(!root)return out;
out.text=(root.innerText||'').trim().replace(/\s+/g,' ').slice(0,60);
let box=null;for(const el of root.querySelectorAll('div')){const t=getComputedStyle(el).transform;if(t&&t!=='none'&&el.offsetWidth>50){box=el;break}}
const br=(box||root).getBoundingClientRect();const sx=box&&box.offsetWidth?br.width/box.offsetWidth:1;
const GEN=new Set(['serif','sans-serif','monospace','cursive','fantasy','system-ui','ui-serif','ui-sans-serif','ui-monospace','ui-rounded','math','emoji','fangsong']);
const ctx=document.createElement('canvas').getContext('2d');const SAMPLE='mmmmmmmmmmlli1WwQ@#ÉÈàç0123';
const width=f=>{ctx.font='72px '+f;return ctx.measureText(SAMPLE).width};
const has=n=>['monospace','serif','sans-serif'].some(g=>width('"'+n+'",'+g)!==width(g));
const fams=new Set();
for(const el of root.querySelectorAll('*')){const own=[...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim());if(!own)continue;
  const cs=getComputedStyle(el);if(cs.visibility==='hidden'||cs.display==='none')continue;fams.add(cs.fontFamily);
  const r=el.getBoundingClientRect();if(!r.width&&!r.height)continue;const text=el.textContent.trim().slice(0,40);
  const o={left:Math.max(0,Math.round((br.left-r.left)/sx)),top:Math.max(0,Math.round((br.top-r.top)/sx)),
    right:Math.max(0,Math.round((r.right-br.right)/sx)),bottom:Math.max(0,Math.round((r.bottom-br.bottom)/sx))};
  if(o.left>2||o.top>2||o.right>2||o.bottom>2)out.overflow.push({text,outside:o});
  else if(el.clientWidth&&(el.scrollWidth>el.clientWidth+1||el.scrollHeight>el.clientHeight+1)&&/hidden|clip/.test(cs.overflowX+cs.overflowY))out.overflow.push({text,clipped:true})}
for(const fam of fams){const available={};for(const part of fam.split(',')){const n=part.trim().replace(/^["']|["']$/g,'');if(n&&!GEN.has(n.toLowerCase()))available[n]=has(n)}
  out.fonts.push({family:fam,available,failed_faces:[]})}
const failed=[];document.fonts.forEach(f=>{if(f.status==='error')failed.push(f.family.replace(/^["']|["']$/g,''))});
if(failed.length)out.fonts.push({family:'',available:{},failed_faces:failed});
for(const img of root.querySelectorAll('img'))if(img.complete&&img.naturalWidth===0)out.assets.push({kind:'image',url:img.currentSrc||img.getAttribute('src')||''});
for(const m of root.querySelectorAll('video,audio'))if(m.error)out.assets.push({kind:'media',url:m.currentSrc||m.getAttribute('src')||''});
for(const e of performance.getEntriesByType('resource'))if(e.responseStatus>=400)out.assets.push({kind:'resource',url:e.name,status:e.responseStatus});
return out})()"""


def dom_findings(records: list[dict[str, Any]], *, scene: str) -> list[Q.Finding]:
    """The page probe's records of one scene -> findings (assets deduplicated by URL)."""

    fonts = [f for r in records for f in r.get("fonts") or []]
    seen, assets = set(), []
    for r in records:
        for a in r.get("assets") or []:
            if a.get("url") not in seen:
                seen.add(a.get("url"))
                assets.append(a)
    overflow = {json.dumps(o, sort_keys=True): o for r in records for o in r.get("overflow") or []}
    return Q.font_findings(fonts, scene=scene) + Q.asset_findings(assets, scene=scene) + Q.dom_overflow_findings(overflow.values(), scene=scene)


def deck_summary(result: dict[str, Any]) -> dict[str, Any]:
    """The JSON evidence of one smoke: per scene, per frame metrics and finding codes; findings; the four separate report sections."""

    findings = result["findings"]
    return {**{k: v for k, v in result.items() if k not in ("findings", "contact", "transitions")},
            "report": Q.report_sections(findings)}
