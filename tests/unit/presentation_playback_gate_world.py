"""Banc de la porte de release « lecture de présentation » (handoff jarvis-remotion-native-studio-playback-fix, Slice 03).

Réutilise le banc réel des Slices 10/23 (`RemotionStack` : Core, protocole, Control Center, bac à sable sur des ports libres et une
racine jetable ; `_remotion_stage_browser.mjs` : Chrome sans tête par CDP). Ajoute seulement ce qu'il faut pour MESURER la lecture :

- `make_deck` : une présentation de 9 scènes Remotion aux durées mêlées (3 s, 8 s, 30 s), cadences mêlées (24, 25, 30, 60 i/s), des
  ancres sur certaines scènes et aucune sur d'autres, et une partition dont chaque élément vise 8 s (`target_duration_ms`), donc
  PLUS COURT que la scène de 30 s : de quoi voir si une durée de partition coupe une composition ;
- `PAGE_PROBE` : un échantillonneur de la page (à chaque image d'animation) et des écoutes de messages : montage / départ / échange des
  cadres, état de chaque page de scène (phase, image, lecture, durée), texte de l'horloge `rs-bar` et de l'horloge de la bande, ordres
  de l'hôte au Player et horloge du Player (`clock`, émise de force à chaque lecture / pause / saut) ;
- `CorePoller` : l'état de lecture de Core relevé toutes les 150 ms pendant que Chrome joue ;
- `png_rgb_mean` : la couleur moyenne d'une capture (PNG décodé avec la bibliothèque standard) pour dire « scène X », « blanc », « vide ».

Ne lance ni n'arrête jamais le Jarvis vivant. Les preuves (JSON, PNG) vont dans `JARVIS_PLAYBACK_GATE_EVIDENCE_DIR` si posé, le chemin du
dossier personnel remplacé par `<home>`.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import struct
import time
from typing import Any
import zlib

import pytest

from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.domain.remotion_source import Composition
from tests.fakes.remotion_player_stack import RemotionStack
from tests.fakes.remotion_scene import scene_candidate

def harness(ok: object, why: object) -> None:
    """A broken measure (setup refused, driver crash, precondition timed out, unreadable capture) is a real failure, never the expected one:
    the gate's xfail marks accept `AssertionError` only (`raises=`), and this raises pytest's `Failed`."""

    if not ok:
        pytest.fail(f"harness: {why}")


PLAYBACK = "/v1/presentation-studio/playback"
BASE = "/v1/presentation-studio/presentations"

SCENE_TSX = """import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";

export default function Scene(props: {title: string; bg: string}) {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  return (
    <AbsoluteFill style={{background: props.bg}}>
      <p id="label" style={{color: "#ffffff", fontSize: 40, margin: 24}}>{props.title}</p>
      <p id="frame" style={{color: "#ffffff", fontSize: 28, margin: 24}}>{String(frame)}</p>
      <div id="bar" style={{position: "absolute", left: 0, bottom: 0, height: 24, background: "#ffffff",
        width: `${Math.round(100 * frame / Math.max(1, durationInFrames - 1))}%`}} />
    </AbsoluteFill>
  );
}
"""
PROPS = {"type": "object", "properties": {"title": {"type": "string", "default": "Scene", "max_length": 80},
                                          "bg": {"type": "color", "default": "#202060"}}}
SAMPLE = {"props": {"title": "Scene", "bg": "#202060"}, "data": {}}
CONTROLS = [{"control_id": "headline", "path": "props.title", "label": "Titre", "group": "content"},
            {"control_id": "bg", "path": "props.bg", "label": "Fond", "group": "visual"}]

#: (secondes, images/s, ancres en ms, fond). Fonds saturés et distincts : une capture dit quelle scène est visible.
DECK: list[tuple[int, int, list[int], str]] = [
    (3, 30, [], "#b01010"),          # 1 : 3 s, sans ancre
    (8, 30, [2000, 5000], "#10a010"),  # 2 : 8 s, deux ancres
    (30, 30, [], "#1030c0"),         # 3 : 30 s, sans ancre, partition 8 s : la scène que « 8 s » couperait
    (3, 25, [], "#c0a000"),          # 4 : 3 s à 25 i/s
    (8, 60, [4000], "#a000a0"),      # 5 : 8 s à 60 i/s, une ancre
    (3, 30, [], "#00a0a0"),          # 6
    (8, 24, [3000], "#e06000"),      # 7 : 8 s à 24 i/s, une ancre
    (3, 30, [], "#606060"),          # 8
    (8, 30, [], "#005050"),          # 9 : 8 s, sans ancre
]
TARGET_MS = 8000
PREFABS = [f"presentation-studio.p0000000000a1.s{n:012d}" for n in range(1, 10)]
SCENE_IDS = [f"pss_{n:012d}" for n in range(1, 10)]


def frames_of(index: int) -> int:
    seconds, fps, _anchors, _bg = DECK[index]
    return seconds * fps


async def make_deck(stack: RemotionStack, *, title: str = "Neuf scenes") -> tuple[str, str]:
    """Publie les 9 sources, crée la présentation, sa partition (un élément d'entrée par scène + un élément de révélation par ancre, chacun
    visant 8 s) et la direction artistique de secours. Rend `(presentation_id, variant_id)`."""

    for index, prefab_id in enumerate(PREFABS):
        seconds, fps, _anchors, bg = DECK[index]
        await stack.core.prefabs.save(scene_candidate(
            prefab_id, engine=shipped_engine_pin(), title=f"S{index + 1}", composition=Composition("Scene", 1280, 720, fps, seconds * fps),
            files={"src/Scene.tsx": SCENE_TSX}, props=PROPS, sample={"props": {"title": f"S{index + 1}", "bg": bg}, "data": {}}),
            actor="user")
    _, created = await stack.call("POST", BASE, json={"title": title})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    vid = variant["variant_id"]
    scenes = []
    for index, (seconds, fps, anchors, bg) in enumerate(DECK):
        scenes.append({"scene_id": SCENE_IDS[index], "prefab": {"id": PREFABS[index], "version": 1}, "title": f"S{index + 1} {seconds}s@{fps}",
                       "props": {"title": f"S{index + 1} {seconds}s@{fps}", "bg": bg}, "data": {}, "controls": CONTROLS,
                       "anchors": [{"anchor_id": f"a{index + 1}_{k}", "label": f"Ancre {k}", "at_ms": at} for k, at in enumerate(anchors)]})
    status, saved = await stack.call("PUT", f"{BASE}/{pid}/variants/{vid}", json={
        "expected_revision": variant["revision"], "title": variant["title"], "scenes": scenes,
        "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"]})
    harness(status == 200, f"variant save refused: {saved}")
    items: list[dict[str, Any]] = []
    for index, (_s, _f, anchors, _bg) in enumerate(DECK):
        items.append({"scene_id": SCENE_IDS[index], "reveal": None})
        items += [{"scene_id": SCENE_IDS[index], "reveal": f"a{index + 1}_{k}"} for k in range(len(anchors))]
    wire = []
    for n, entry in enumerate(items, start=1):
        visual = [{"kind": "reveal", "scene_id": entry["scene_id"], "anchor_id": entry["reveal"]}] if entry["reveal"] else []
        wire.append({"item_id": f"psi_{n:012d}", "scene_id": entry["scene_id"], "presenter": "user", "kind": "speech", "note": f"Element {n}",
                     "target_duration_ms": TARGET_MS, **({"next_item_id": f"psi_{n + 1:012d}"} if n < len(items) else {}),
                     **({"visual": visual} if visual else {})})
    status, made = await stack.call("POST", f"{BASE}/{pid}/variants/{vid}/score", json={
        "expected_variant_revision": saved["revision"], "start_item_id": wire[0]["item_id"], "items": wire, "cues": [],
        "sequences": [], "recovery_points": []})
    harness(status == 201, f"score refused: {made}")
    status, art = await stack.call("POST", f"{BASE}/{pid}/variants/{vid}/art-direction/fallback",
                                   json={"expected_variant_revision": saved["revision"] + 1})
    harness(status == 201, f"art direction refused: {art}")
    return pid, vid


# ---------------------------------------------------------------------------------------------------------------- sonde de la page

#: Installée par `{eval: PAGE_PROBE}`. `__pg.rows` : `[ms, [cadres]]` à chaque changement (image d'animation), un cadre étant
#: `[uid, lieu, visible, phase, image, lecture, durée, texte rs-time]` ; `__pg.ev` : `[ms, sorte, uid, ...]` (mount, gone, live, host->stage
#: `control`, Player->stage `clock`/`ready`, stage->hôte `status`) ; `__pg.band` : `[ms, horloge de la bande, où]` à chaque changement.
PAGE_PROBE = r"""(()=>{if(window.__pg)return;const W=window;const pg=W.__pg={t0:performance.now(),epoch:Date.now(),rows:[],ev:[],band:[],uid:0,last:'',lastBand:''};
const T=()=>Math.round(performance.now()-pg.t0);
const place=f=>f.closest('#jvStudioExplorer')?'explorer':f.closest('#jvPresWindow')?'window':'board';
const vis=f=>f.isConnected&&!f.classList.contains('sc-prefab-staged')&&f.style.visibility!=='hidden'&&f.getBoundingClientRect().width>0;
function tap(f){const hook=()=>{try{const w=f.contentWindow;if(!w||w.__pgTap)return;w.__pgTap=1;
  w.addEventListener('message',e=>{const d=e.data;if(!d||typeof d!=='object')return;
    if(e.source===W){if(d.type==='control')pg.ev.push([T(),'order',f.__pgu,d.action,d.frame===undefined?null:d.frame,d.until===undefined?null:d.until]);return}
    if(d.type==='clock'||d.type==='ready')pg.ev.push([T(),d.type,f.__pgu,d.frame===undefined?null:d.frame,d.playing===undefined?null:d.playing]);},true)}catch(_e){}};
  hook();f.addEventListener('load',hook)}
const scn=id=>{const m=/\.s0*(\d+)(?:@|$)/.exec(String(id||''));return m?'S'+m[1]:null};
function uidOf(f){if(!f.__pgu){f.__pgu=++pg.uid;let id=null;try{id=new URL(f.src,location.href).searchParams.get('id')}catch(_e){}
  pg.ev.push([T(),'mount',f.__pgu,place(f),scn(id),f.classList.contains('sc-prefab-staged')]);tap(f);f.__pgVis=false}return f.__pgu}
W.addEventListener('jarvis:studio-timeline',e=>{const d=e.detail||{},tl=d.timeline;
  const row=[tl?scn(tl.prefab):null,tl?tl.seq:null,tl?tl.from_frame:null,tl?tl.until_frame:null,tl?tl.playing:null,d.preload&&d.preload.prefab?scn(d.preload.prefab.id):null];
  const k=JSON.stringify(row);if(k!==pg.lastTl){pg.lastTl=k;pg.ev.push([T(),'tl',0,...row])}},true);
W.addEventListener('jarvis:studio-segment',e=>{const d=e.detail||{};pg.ev.push([T(),'segment',0,d.event,d.seq])},true);
W.addEventListener('message',e=>{const d=e.data;if(!d||d.rsh!==1||d.type!=='status')return;
  const f=[...document.querySelectorAll('iframe[data-remotion-stage]')].find(x=>x.contentWindow===e.source);
  if(f)pg.ev.push([T(),'status',uidOf(f),d.phase]);},true);
const known=new Set();
function sample(){try{
  const all=[...document.querySelectorAll('iframe[data-remotion-stage]')];
  for(const f of known)if(!f.isConnected){known.delete(f);pg.ev.push([T(),'gone',f.__pgu])}
  const rec=all.map(f=>{const u=uidOf(f);known.add(f);const v=vis(f);if(v&&!f.__pgVis)pg.ev.push([T(),'live',u]);f.__pgVis=v;
    let s=null,txt=null;try{s=f.contentWindow.__remotionStage.state();const t=f.contentDocument.querySelector('.rs-time');txt=t?t.textContent:null}catch(_e){}
    return [u,place(f),v,s&&s.phase,s&&s.frame,s&&s.playing,s&&s.duration,txt]});
  const key=JSON.stringify(rec);if(key!==pg.last){pg.last=key;pg.rows.push([T(),rec])}
  const band=document.querySelector('#jvStudioBand');const clock=band&&!band.hidden?band.querySelector('.jvsp-clock'):null;
  const bk=clock?clock.textContent+'|'+(band.querySelector('.jvsp-where')||{}).textContent:'';
  if(bk!==pg.lastBand){pg.lastBand=bk;pg.band.push([T(),bk])}
}catch(e){pg.ev.push([T(),'probe_error',0,String(e)])}requestAnimationFrame(sample)}
requestAnimationFrame(sample);})()"""

READ_PROBE = "window.__pg&&{t0:window.__pg.t0,epoch:window.__pg.epoch,rows:window.__pg.rows,ev:window.__pg.ev,band:window.__pg.band}"
VISIBLE_RECT = ("(()=>{const f=[...document.querySelectorAll('iframe[data-remotion-stage]')].find(x=>!x.classList.contains('sc-prefab-staged')"
                "&&x.style.visibility!=='hidden'&&x.getBoundingClientRect().width>0);if(!f)return null;const r=(f.parentElement||f).getBoundingClientRect();"
                "return {x:Math.max(0,r.left),y:Math.max(0,r.top),width:Math.max(16,Math.min(r.width,innerWidth-Math.max(0,r.left))),"
                "height:Math.max(16,Math.min(r.height,innerHeight-Math.max(0,r.top)))}})()")


class CorePoller:
    """`async with CorePoller(stack) as poll:` relève `GET /playback` toutes les `every_ms` (temps Unix en ms) pendant que Chrome joue."""

    def __init__(self, stack: RemotionStack, every_ms: int = 150) -> None:
        self.stack, self.every = stack, every_ms / 1000
        self.rows: list[dict[str, Any]] = []
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        while True:
            try:
                status, body = await self.stack.call("GET", PLAYBACK)
                state = (body or {}).get("state") or {}
                tl = state.get("timeline") or {}
                el = state.get("elapsed") or {}
                self.rows.append({"at": int(time.time() * 1000), "status": status, "phase": state.get("phase"), "scope": state.get("scope"),
                                  "index": (state.get("position") or {}).get("index"), "scene": (state.get("scene") or {}).get("number"),
                                  "tl": {k: tl.get(k) for k in ("scene_id", "from_frame", "until_frame", "seq", "play_ms", "playing", "auto", "fps",
                                                                "duration_frames")} if tl else None,
                                  "item_ms": el.get("item_ms"), "item_target_ms": el.get("item_target_ms")})
            except Exception as exc:  # noqa: BLE001 - a missed poll is recorded, the measure goes on
                self.rows.append({"at": int(time.time() * 1000), "error": repr(exc)[:200]})
            await asyncio.sleep(self.every)

    async def __aenter__(self) -> "CorePoller":
        self._task = asyncio.get_running_loop().create_task(self._loop())
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


VISIBLE = ("[...document.querySelectorAll('iframe[data-remotion-stage]')].find(x=>!x.classList.contains('sc-prefab-staged')"
           "&&x.style.visibility!=='hidden'&&x.getBoundingClientRect().width>0)")


def next_boundary(frames_left: int = 20) -> str:
    """Vrai quand le cadre visible n'est pas celui de la rafale précédente et approche de sa dernière image (rafale de frontière)."""

    return (f"(()=>{{const f={VISIBLE};if(!f||!window.__pg||f.__pgu===window.__pgBurst)return false;"
            f"try{{const s=f.contentWindow.__remotionStage.state();if(s.duration>0&&s.frame>=s.duration-1-{frames_left}){{window.__pgBurst=f.__pgu;return true}}"
            f"return false}}catch(e){{return false}}}})()")


# ---------------------------------------------------------------------------------------------------------------- the Variants Player (contract)
#
# Contract-level observations of `docs/presentation-studio.md` > *Presentation experience contract* (§ 2, § 4, § 6): the Variants Player is
# the visible Remotion stage frame inside `#jvStudioExplorer`; controls are found by their ROLE and NAME (toolbar « Lire » / « Pause »,
# overflow « Lire seulement cette scène », `role="slider"`, the scene listbox), never by today's classes. Where the contract control does
# not exist yet, a gesture falls back to today's control ONLY when the test measures today's defect through it (`legacy`), and says which
# control it used. Today's selectors (`.jvx-play`, `.rs-scrub`, `.rs-time`, the band `#jvStudioBand`) are retargeted to the Variants Player
# by Slices 06/09/10; the helpers below keep working across that change.

EXPLORER_FRAME = ("[...document.querySelectorAll('#jvStudioExplorer iframe[data-remotion-stage]')].find(x=>!x.classList.contains('sc-prefab-staged')"
                  "&&x.style.visibility!=='hidden'&&x.getBoundingClientRect().width>0)")
#: The Variants Player: `{frame, playing, duration, phase, scene}` (scene from the mounted pin, `S<n>`), or null when Variants shows no Player.
VSTATE = (f"(()=>{{const f={EXPLORER_FRAME};if(!f)return null;let s=null;try{{s=f.contentWindow.__remotionStage.state()}}catch(e){{return null}}"
          "const m=/\\.s0*(\\d+)(?:@|&|$)/.exec(decodeURIComponent(f.src||''));"
          "return {frame:s.frame,playing:s.playing,duration:s.duration,phase:s.phase,scene:m?'S'+m[1]:null}})()")
#: The run's Player wherever it plays today (Board stage) or after Slice 09 (Variants): the visible frame showing `duration` frames.
def run_state(duration: int) -> str:
    return (f"(()=>{{for(const f of document.querySelectorAll('iframe[data-remotion-stage]')){{if(f.classList.contains('sc-prefab-staged')||"
            f"f.style.visibility==='hidden'||!f.getBoundingClientRect().width)continue;try{{const s=f.contentWindow.__remotionStage.state();"
            f"if(s.duration==={duration})return {{frame:s.frame,playing:s.playing,phase:s.phase,place:f.closest('#jvStudioExplorer')?'variants':'board'}}}}"
            "catch(e){}}return null})()")


#: Everything a viewer reads at one instant (§ 4.8): every VISIBLE time readout of the page and of the same-origin stage pages (text `a / b`
#: with `m:ss` or `x s` terms), the scene label « Scène n sur N », the strip selection, the scrub slider, the Variants Player.
READOUTS = (r"""(()=>{const RX=/(\d{1,2}:\d{2}(?::\d{2})?|\d+(?:[.,]\d+)?\s?s)\s*\/\s*(\d{1,2}:\d{2}(?::\d{2})?|\d+(?:[.,]\d+)?\s?s)/;
const out=[];const shown=(el,v)=>{const cs=v.getComputedStyle(el);return el.getClientRects().length>0&&cs.visibility!=='hidden'&&cs.display!=='none'&&!el.closest('[hidden]')};
const scan=(doc,where)=>{for(const el of doc.querySelectorAll('body *')){if(['SCRIPT','STYLE','IFRAME'].includes(el.tagName))continue;
  const own=[...el.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join('');const m=RX.exec(own);
  if(m&&shown(el,doc.defaultView))out.push({where,text:own.trim().slice(0,80)})}};
scan(document,'page');
for(const f of document.querySelectorAll('iframe[data-remotion-stage]')){if(f.classList.contains('sc-prefab-staged')||f.style.visibility==='hidden'||!f.getBoundingClientRect().width)continue;
  try{scan(f.contentDocument,f.closest('#jvStudioExplorer')?'variants-stage':'board-stage')}catch(e){}}
const x=document.querySelector('#jvStudioExplorer');let label=null,selected=null,slider=null;
if(x){const lm=/Scène (\d+) sur (\d+)/.exec(x.innerText||'');label=lm?+lm[1]:null;
  const sel=x.querySelector('[aria-selected="true"][data-scene]');selected=sel?sel.getAttribute('data-scene'):null;
  const sl=x.querySelector('[role="slider"]');slider=sl?{now:sl.getAttribute('aria-valuenow'),max:sl.getAttribute('aria-valuemax'),
    text:sl.getAttribute('aria-valuetext'),disabled:sl.getAttribute('aria-disabled')==='true'}:null}
""" + f"return {{readouts:out,label,selected,slider,player:{VSTATE},open:!!(window.JarvisStudioExplorer&&JarvisStudioExplorer.isOpen())}}}})()")


def gesture(kind: str, *, legacy: bool) -> str:
    """Click the contract control for `kind` (synthetic click) and return the name of the control used, or null.

    `play`: toolbar « Lire » (§ 4.2); legacy « Tout jouer ». `scene_only`: overflow « Lire seulement cette scène » (§ 5 table); legacy
    « Jouer cette slide ». `pause`: toolbar « Pause » (§ 4.3); legacy: the stage page's own toggle while it reads « Pause »."""

    return (r"""(()=>{const x=document.querySelector('#jvStudioExplorer');if(!x)return null;
const names=el=>[el.getAttribute('aria-label')||'',(el.textContent||'').replace(/\s+/g,' ').trim()];
const find=(re,root)=>[...(root||x).querySelectorAll('button,[role="menuitem"],[role="button"]')].find(b=>names(b).some(n=>re.test(n))&&b.getAttribute('aria-disabled')!=='true'&&b.getClientRects().length);
const press=(b,label)=>{b.click();return label};
const KIND=""" + json.dumps(kind) + ";const LEGACY=" + ("true" if legacy else "false") + r""";
if(KIND==='play'){const b=find(/^(▶\s*)?Lire$/i,x.querySelector('[role="toolbar"]')||x);if(b)return press(b,'Lire');
  if(LEGACY){const t=find(/Tout jouer/);if(t)return press(t,'legacy:Tout jouer')}return null}
if(KIND==='scene_only'){let item=find(/Lire seulement cette scène/);
  if(!item){const more=[...x.querySelectorAll('[aria-haspopup="menu"],[aria-haspopup="true"]')].find(b=>b.getClientRects().length);if(more){more.click();item=find(/Lire seulement cette scène/,document)}}
  if(item)return press(item,'Lire seulement cette scène');
  if(LEGACY){const t=find(/Jouer cette slide/);if(t)return press(t,'legacy:Jouer cette slide')}return null}
if(KIND==='pause'){const b=find(/^Pause$/i,x.querySelector('[role="toolbar"]')||x);if(b)return press(b,'Pause');
  if(LEGACY){const f=""" + EXPLORER_FRAME + r""";try{const t=f.contentDocument.querySelector('.rs-btn');if(t&&t.textContent==='Pause')return press(t,'legacy:rs-bar Pause')}catch(e){}}return null}
return null})()""")


def scrub_to(scene_index: int, seconds: int, *, legacy_local_frame: int) -> str:
    """The user scrubs (§ 4.6) to `seconds` after the start of scene `scene_index`. Contract: the `role="slider"` of Variants with its ARIA keys
    (`Home`, `PageDown` per scene, `→` per second). Legacy (today): the stage page's own scrub (`.rs-scrub`) of the Variants Player, set to the
    scene-local frame. Returns which one was used, or null."""

    return (r"""(()=>{const x=document.querySelector('#jvStudioExplorer');if(!x)return null;const sl=x.querySelector('[role="slider"]');
if(sl&&sl.getAttribute('aria-disabled')!=='true'){sl.focus();const key=k=>sl.dispatchEvent(new KeyboardEvent('keydown',{key:k,bubbles:true,cancelable:true}));
  key('Home');for(let i=0;i<""" + str(scene_index) + r""";i++)key('PageDown');for(let i=0;i<""" + str(seconds) + r""";i++)key('ArrowRight');
  sl.dispatchEvent(new KeyboardEvent('keyup',{key:'ArrowRight',bubbles:true}));return 'slider'}
const f=""" + EXPLORER_FRAME + r""";try{const r=f.contentDocument.querySelector('.rs-scrub');if(r){r.value='""" + str(legacy_local_frame)
            + r"""';r.dispatchEvent(new Event('input',{bubbles:true}));return 'legacy:rs-scrub'}}catch(e){}return null})()""")


def open_variants(pid: str) -> list[dict]:
    """Plan prefix: the page, the probe, Variants opened windowed on the presentation, its Player ready (a precondition: `required`)."""

    return [{"until": "!!window.JarvisStudioExplorer", "ms": 20000, "required": True, "as": "explorer_api"}, {"eval": PAGE_PROBE},
            {"eval": f"JarvisStudioExplorer.open({{presentation_id:'{pid}',fullscreen:false}})"},
            {"until": f"(()=>{{const s={VSTATE};return !!s&&s.phase==='ready'}})()", "ms": 90000, "required": True, "as": "variants_ready"}]


def variants_scene_ready(scene_index: int) -> dict:
    return {"until": f"(()=>{{const s={VSTATE};return !!s&&s.phase==='ready'&&s.scene==='S{scene_index + 1}'}})()", "ms": 90000,
            "required": True, "as": f"variants_ready_S{scene_index + 1}"}


def thumbnail(scene_index: int) -> dict:
    """A click on the strip thumbnail of a scene (§ 4.5): the option of the scene listbox that carries its id."""

    return {"click": f"#jvStudioExplorer [data-scene=\"{SCENE_IDS[scene_index]}\"]"}


def composition_seconds(scene_index: int, local_frame: int) -> float:
    """§ 3: the composition time of a scene-local frame (scenes abut; fps-agnostic in seconds)."""

    seconds, fps, _a, _b = DECK[scene_index]
    return sum(s for s, _f, _a2, _b2 in DECK[:scene_index]) + local_frame / fps


def parse_readout(text: str) -> tuple[float, float | None] | None:
    """`(shown, total)` in seconds from `0:12 / 1:30`, `12.3 s / 30.0 s`; None when it is not a time readout."""

    import re
    term = r"(\d{1,2}:\d{2}(?::\d{2})?|\d+(?:[.,]\d+)?\s?s)"
    m = re.search(term + r"\s*/\s*" + term, text)
    if not m:
        return None

    def sec(t: str) -> float:
        t = t.strip().rstrip("s").strip().replace(",", ".")
        if ":" in t:
            parts = [int(p) for p in t.split(":")]
            value = 0
            for p in parts:
                value = value * 60 + p
            return float(value)
        return float(t)
    return sec(m.group(1)), sec(m.group(2))


def readout_problems(snapshot: dict, scene_index: int) -> list[str]:
    """§ 4.8 / § 6 #18: at least one visible time readout, and every one shows the composition time of the Player's frame over the
    composition length (never a score item time over a target, never a scene-local time)."""

    player = snapshot.get("player") or {}
    if player.get("frame") is None:
        return ["no Variants Player"]
    expected = composition_seconds(scene_index, player["frame"])
    total = sum(s for s, _f, _a, _b in DECK)
    problems = [] if snapshot.get("readouts") else ["no visible time readout"]
    for r in snapshot.get("readouts") or []:
        parsed = parse_readout(r["text"])
        if parsed is None:
            continue
        shown, length = parsed
        if abs(shown - expected) > 1.0 or (length is not None and abs(length - total) > 1.0):
            problems.append(f"{r['where']} {r['text']!r} != composition {expected:.1f} s / {total} s")
    return problems


def drive_long(url: str, plan: list, *, timeout: int = 600, viewport: str = "1280x720") -> dict:
    """Le pilote CDP partagé (`_remotion_stage_browser.mjs`) avec une échéance plus longue (une présentation entière se joue)."""

    import subprocess
    from tests.unit.test_fullscreen_browser import _chrome
    driver = Path(__file__).parent / "_remotion_stage_browser.mjs"
    done = subprocess.run(["node", str(driver), url, _chrome(), json.dumps(plan)], capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, check=False, env={**os.environ, "CDP_VIEWPORT": viewport})
    harness(done.returncode == 0, f"CDP driver exit {done.returncode}: {done.stderr[-2000:]}")
    return json.loads(done.stdout)


async def run_long(url: str, plan: list, **kwargs: Any) -> dict:
    return await asyncio.to_thread(drive_long, url, plan, **kwargs)


# ---------------------------------------------------------------------------------------------------------------- analyses

def frame_rows(probe: dict) -> dict[int, list[tuple[int, bool, str | None, int | None, bool | None, int | None]]]:
    """`{uid: [(ms, visible, phase, image, lecture, durée)]}` depuis les lignes de la sonde."""

    out: dict[int, list] = {}
    for ms, rec in probe["rows"]:
        for uid, _place, visible, phase, frame, playing, duration, _txt in rec:
            out.setdefault(uid, []).append((ms, visible, phase, frame, playing, duration))
    return out


def player_clocks(probe: dict) -> dict[int, list[tuple[int, int, bool]]]:
    """`{uid: [(ms, image, lecture)]}` : l'horloge que le Player lui-même a émise (forcée à chaque lecture / pause / saut)."""

    out: dict[int, list] = {}
    for row in probe["ev"]:
        if row[1] == "clock":
            out.setdefault(row[2], []).append((row[0], row[3], row[4]))
    return out


def wraps(clocks: list[tuple[int, int, bool]]) -> list[tuple[int, int, int]]:
    """Retours en arrière de l'horloge du Player SANS ordre de saut entre les deux : `(ms, avant, après)` (une boucle)."""

    return [(b[0], a[1], b[1]) for a, b in zip(clocks, clocks[1:]) if b[1] < a[1] and a[2] and b[2]]


def blank_spans(probe: dict, *, after_ms: int = 0, place: str | None = None) -> list[tuple[int, int]]:
    """Intervalles `(début, durée ms)` où AUCUN cadre visible (au lieu donné) n'est prêt : la fenêtre montre un chargement ou rien."""

    spans, since, seen_ready = [], None, False
    for ms, rec in probe["rows"]:
        ready = any(v and phase == "ready" for _u, p, v, phase, *_ in rec if place is None or p == place)
        seen_ready = seen_ready or ready
        if ms < after_ms or not seen_ready:
            continue
        if not ready and since is None:
            since = ms
        elif ready and since is not None:
            spans.append((since, ms - since))
            since = None
    if since is not None:
        spans.append((since, probe["rows"][-1][0] - since))
    return spans


def first_play(probe: dict, uid: int) -> tuple[int, int] | None:
    """`(ms, image)` du premier `clock {playing: true}` du Player de ce cadre : l'image où sa lecture a commencé."""

    return next(((ms, frame) for ms, frame, playing in player_clocks(probe).get(uid, []) if playing), None)


# ---------------------------------------------------------------------------------------------------------------- captures

def _png_rows(path: Path) -> tuple[int, int, int, list[bytes]]:
    data = path.read_bytes()
    harness(data[:8] == b"\x89PNG\r\n\x1a\n", f"not a PNG: {path}")
    pos, idat, width = 8, b"", 0
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", body[:10])
            harness(depth == 8 and color in (2, 6), f"unsupported PNG depth/colour {depth}/{color}: {path}")
            channels = 3 if color == 2 else 4
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * channels
    rows, prev = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b, c = prev[x], prev[x - channels] if x >= channels else 0
            if kind == 1:
                line[x] = (line[x] + a) & 255
            elif kind == 2:
                line[x] = (line[x] + b) & 255
            elif kind == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    return width, height, channels, rows


def png_rgb_mean(path: Path) -> tuple[int, int, int]:
    """Couleur moyenne du tiers haut de l'image (le fond de la scène, loin du texte et de la barre de progression)."""

    width, height, channels, rows = _png_rows(path)
    acc, n = [0, 0, 0], 0
    for line in rows[height // 6: height // 2]:
        for x in range(width // 3, width, 4):
            px = line[x * channels:x * channels + 3]
            acc[0] += px[0]; acc[1] += px[1]; acc[2] += px[2]; n += 1  # noqa: E702
    return tuple(round(v / max(1, n)) for v in acc)  # type: ignore[return-value]


def classify(rgb: tuple[int, int, int]) -> str:
    """`S<n>` (scène dont le fond est le plus proche), `white`, `dark` (vide / chargement) ou `other`."""

    if min(rgb) > 225:
        return "white"
    best, dist = None, 1e9
    for index, (_s, _f, _a, bg) in enumerate(DECK):
        ref = tuple(int(bg[i:i + 2], 16) for i in (1, 3, 5))
        d = sum((a - b) ** 2 for a, b in zip(rgb, ref)) ** 0.5
        if d < dist:
            best, dist = f"S{index + 1}", d
    if dist < 60:
        return best or "other"
    return "dark" if max(rgb) < 60 else "other"


# ---------------------------------------------------------------------------------------------------------------- preuves

def evidence_dir() -> Path | None:
    raw = os.environ.get("JARVIS_PLAYBACK_GATE_EVIDENCE_DIR")
    if not raw:
        return None
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def redact(text: str) -> str:
    home = str(Path.home())
    for form in {home, home.replace("\\", "/"), home.replace("\\", "\\\\"), json.dumps(home)[1:-1]}:
        text = text.replace(form, "<home>")
    return text.replace(Path.home().name, "<user>")


def record(name: str, payload: dict, shots: list[Path] = ()) -> None:  # type: ignore[assignment]
    """Écrit `<name>.json` (et copie les captures choisies) dans le dossier de preuves, chemin personnel masqué."""

    folder = evidence_dir()
    if folder is None:
        return
    (folder / f"{name}.json").write_text(redact(json.dumps(payload, indent=1, ensure_ascii=False, default=str)), encoding="utf-8")
    for shot in shots:
        if shot.is_file():
            shutil.copy2(shot, folder / f"{name}-{shot.name}")


def bursts_classified(shots: list[list]) -> list[tuple[int, str, str]]:
    """`[(ms page, classe, fichier)]` d'une rafale."""

    return [(t, classify(png_rgb_mean(Path(f))), Path(f).name) for t, f in shots]


def transition_shots(classified: list[tuple[int, str, str]], folder: Path, limit: int = 6) -> list[Path]:
    """Les captures de part et d'autre de chaque changement de classe d'une rafale (la frontière vue à l'écran), au plus `limit`."""

    picked: list[str] = []
    for a, b in zip(classified, classified[1:]):
        if a[1] != b[1]:
            picked += [a[2], b[2]]
    return [folder / name for name in dict.fromkeys(picked)][:limit]
