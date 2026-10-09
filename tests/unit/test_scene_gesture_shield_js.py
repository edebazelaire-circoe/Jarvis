"""Bouclier des cadres de prefab pendant un geste et clic dans un cadre
(handoff jarvis-scene-window-prefab-foundation, reprise QA de la Slice 05, F1 et F2).

Un cadre de prefab est un document isolé (`srcdoc` sandboxé, hors processus
dans Chrome) : un pointeur qui passe dessus pendant un glissement y part, la
capture du nœud ne le ramène pas et le lâcher n'arrive jamais à la page. La
scène porte donc `sc-gesture` tant que quelqu'un tient quelque chose, et la
règle `.scene.sc-gesture .sc-prefab-frame{pointer-events:none}` rend **tous**
les cadres transparents au pointeur. Un clic dans un cadre, lui, n'est vu que
par le `blur` de la page : il doit sélectionner la fenêtre par le chemin du
focus d'un nœud.

Ce fichier exécute avec node les **vraies** fonctions de
`control_center_scene_page.js` (extraites par leur nom, sans réécriture) contre
de petits doubles : bureau, scène, document. Ce qui doit tenir :

- la classe se pose à l'appui et tombe au lâcher, à l'annulation
  (`pointercancel`), à la capture perdue avant ou après un mouvement, et à la
  fenêtre quittée ;
- une main de Bare Hands (le bureau) qui tient encore garde le bouclier quand
  la souris lâche, et le rend en lâchant ;
- le rectangle de sélection lève le bouclier et le rend, lâché, annulé ou
  abandonné par un `blur` ;
- un `blur` dont le focus est parti dans un cadre de prefab sélectionne sa
  fenêtre (et reprend un cadre en pause) sans geste ni menu.

La preuve navigateur (vraie souris CDP, cadres hors processus) est dans
`tasks/jarvis-scene-window-prefab-foundation/slices/05-window-family-prefabs/evidence/rework/`.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

import pytest

PAGE_JS = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_scene_page.js"

#: Fonctions de la page exécutées telles quelles.
PAGE_FUNCTIONS = (
    "syncHolding", "onPointerDown", "onPointerMove", "endGesture", "onPointerUp", "dropGesture", "cancelGesture",
    "onPointerCancel", "startBand", "onBandMove", "onBandUp", "stopBandListening", "cancelBand", "bandFrame",
    "endBand", "onWindowBlur", "onFocusIn", "nodeElement", "select", "anchorSelection", "applySelection",
)


def page_function(source: str, name: str) -> str:
    """Texte exact de `function <name>(...){...}` dans la page (accolades appariées)."""

    match = re.search(r"\n  function " + re.escape(name) + r"\(", source)
    assert match, f"function {name} not found in the scene page"
    start = match.start() + 1
    depth = 0
    for index in range(source.index("{", start), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"unbalanced function {name}")


DOUBLES = r"""
const log=[];
function classes(){const set=new Set();return {set,add:n=>set.add(n),remove:n=>set.delete(n),contains:n=>set.has(n),
  toggle(n,on){if(on===undefined)on=!set.has(n);if(on)set.add(n);else set.delete(n);return on}}}
function el(tag,attrs){const e=Object.assign({tagName:tag,classList:classes(),dataset:{},parent:null,captured:new Set(),
  focused:0,removed:false},attrs||{});
  e.closest=sel=>{for(let n=e;n;n=n.parent){if(sel==='.sc-node'&&n.classList.contains('sc-node'))return n;
    if(sel==='.sc-grip'&&n.classList.contains('sc-grip'))return n;}return null};
  e.setPointerCapture=id=>e.captured.add(id);e.hasPointerCapture=id=>e.captured.has(id);
  e.releasePointerCapture=id=>e.captured.delete(id);e.focus=()=>{e.focused++;document.activeElement=e};
  e.remove=()=>{e.removed=true};e.appendChild=()=>{};e.style={};e.setAttribute=()=>{};
  e.getBoundingClientRect=()=>({left:0,top:0,width:100,height:100});return e}
const listeners=new Map();
const document={activeElement:null,
  addEventListener(t,f){listeners.set(t+':'+f.name,f)},removeEventListener(t,f){listeners.delete(t+':'+f.name)},
  createElement:tag=>el(tag)};
const window={clearTimeout(){},setTimeout(){return 1}};
const root=el('DIV');root.contains=n=>{for(let x=n;x;x=x.parent)if(x===root)return true;return false};
function windowNode(id){const node=el('DIV');node.classList.add('sc-node');node.dataset.objectId=id;node.parent=root;
  const grip=el('SPAN');grip.classList.add('sc-grip');grip.parent=node;
  const frame=el('IFRAME');frame.classList.add('sc-prefab-frame');frame.parent=node;
  return {node,grip,frame}}
const A=windowNode('pw-1'),B=windowNode('pw-2');
const nodes=new Map([['pw-1',{el:A.node}],['pw-2',{el:B.node}]]);
/* Bureau : qui tient quoi (souris ou main), comme `desk.heldIds()`. Le vrai
   bureau prévient la page à chaque prise et lâcher (`holdNode` → `syncHolding`). */
const held=new Map();let handles=0;
const desk={heldIds:()=>[...held.keys()],
  take(source,ids){const h={id:++handles,source,ids};for(const id of ids)held.set(id,h);syncHolding();return h},
  drag(){},cancel(h){for(const id of h.ids)held.delete(id);syncHolding();log.push(['cancel',h.source])},
  drop(h,kind){for(const id of h.ids)held.delete(id);syncHolding();log.push(['drop',h.source,kind]);return []}};
const touched=[];
const prefabHost={has:id=>id.startsWith('pw-'),touch:id=>touched.push(id)};
const I={resizable:()=>true,dragThreshold:()=>4,longPressOpensMenu:()=>false,LONG_PRESS_MS:550,
  bandBox:(a,b)=>({left:Math.min(a.x,b.x),top:Math.min(a.y,b.y),width:Math.abs(a.x-b.x),height:Math.abs(a.y-b.y)}),
  bandStarted:box=>box.width+box.height>4,bandHits:()=>['pw-1'],
  nextSelection:(current,hits,mode)=>mode==='add'?[...new Set([...current,...hits])]:hits};
const BH={isBareHandsPointerId:()=>false};
const raisedLog=[];const raiseWindow=id=>raisedLog.push(id);
let enabled=true,gesture=null,band=null,keyEdit=null,selection=[],selectedId=null,focusId=null,lastModel=null;
const frames={cancel(){}};
const consoleLog=(level,key,data)=>log.push([level,key,data&&data.reason||'']);
const nodeOf=()=>({}),drawnBox=()=>({x:0,y:0,w:300,h:200}),viewState=()=>({objects:new Map([['pw-1',{representation:'window'}],['pw-2',{representation:'window'}]])});
const takeHold=(source,ids)=>desk.take(source,ids),barehandsActive=()=>false;
const reportSent=()=>{},closeMenu=()=>{},openObjectMenu=()=>log.push(['menu']),announce=()=>{},updateTabStop=()=>{},
  setInnerTabs=()=>{},clampLabel=()=>{},flushKeyEdit=()=>{};
const shield=()=>root.classList.contains('sc-gesture');
const down=(target,extra)=>onPointerDown(Object.assign({button:0,pointerId:1,clientX:10,clientY:10,target,preventDefault(){}},extra||{}));
const move=(x,y)=>onPointerMove({pointerId:1,clientX:x,clientY:y});
"""


def run_page(tmp_path: Path, body: str) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    source = PAGE_JS.read_text(encoding="utf-8")
    functions = "\n".join(page_function(source, name) for name in PAGE_FUNCTIONS)
    script = tmp_path / f"gesture-shield-{len(list(tmp_path.glob('gesture-shield-*.cjs')))}.cjs"
    script.write_text(DOUBLES + functions + "\nconsole.log(JSON.stringify((()=>{\n" + body + "\n})()));\n",
                      encoding="utf-8")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_css_shields_every_prefab_frame_of_the_scene_while_anything_is_held():
    source = PAGE_JS.read_text(encoding="utf-8")
    assert ".scene.sc-gesture .sc-prefab-frame{pointer-events:none}" in source
    # Pas seulement le cadre de l'objet tenu : le voisin dans lequel la poignée entre aussi.
    assert not re.search(r"\.sc-dragging[^{]*\.sc-prefab-frame", source)
    assert "window.addEventListener('blur',onWindowBlur)" in source
    assert "window.removeEventListener('blur',onWindowBlur)" in source


def test_the_shield_rises_on_press_and_falls_on_release(tmp_path):
    result = run_page(tmp_path, r"""
      const states=[shield()];
      down(A.grip);states.push(shield());
      move(80,60);move(400,60);states.push(shield());
      onPointerUp({pointerId:1,clientX:400,clientY:60});states.push(shield());
      return {states,log};
    """)
    assert result["states"] == [False, True, True, False]
    assert ["drop", "mouse", "resize"] in result["log"]


@pytest.mark.parametrize(("event", "moved", "outcome"), [
    ("pointercancel", True, "cancel"),
    ("pointercancel", False, "cancel"),
    ("lostpointercapture", False, "cancel"),
    ("lostpointercapture", True, "drop"),
])
def test_every_cancel_path_drops_the_shield(tmp_path, event, moved, outcome):
    result = run_page(tmp_path, r"""
      down(A.node);
      if(%s)move(200,200);
      const during=shield();
      onPointerCancel({type:'%s',pointerId:1});
      return {during,after:shield(),gesture:gesture===null,log};
    """ % ("true" if moved else "false", event))
    assert result["during"] is True and result["after"] is False and result["gesture"] is True
    assert result["log"][-1][0] == outcome


def test_leaving_the_window_mid_gesture_cancels_it_and_drops_the_shield(tmp_path):
    result = run_page(tmp_path, r"""
      down(A.grip);move(300,300);
      const during=shield();
      onWindowBlur();
      return {during,after:shield(),gesture:gesture===null,log,held:desk.heldIds()};
    """)
    assert result["during"] is True and result["after"] is False and result["gesture"] is True
    assert ["info", "scene.gesture_cancelled", "window_blur"] in result["log"]
    assert ["cancel", "mouse"] in result["log"] and result["held"] == []


def test_a_hand_still_holding_keeps_the_shield_after_the_mouse_lets_go(tmp_path):
    result = run_page(tmp_path, r"""
      const hand=desk.take('barehands',['pw-2']);
      const handOnly=shield();
      down(A.node);move(90,90);onPointerUp({pointerId:1,clientX:90,clientY:90});
      const mouseReleased=shield();
      desk.drop(hand,'move');
      return {handOnly,mouseReleased,after:shield()};
    """)
    assert result == {"handOnly": True, "mouseReleased": True, "after": False}


def test_the_selection_band_raises_and_drops_the_shield_on_release_cancel_and_blur(tmp_path):
    result = run_page(tmp_path, r"""
      const out={};
      startBand({pointerId:7,clientX:0,clientY:0});out.started=shield();
      onBandMove({pointerId:7,clientX:60,clientY:60,preventDefault(){}});
      onBandUp({type:'pointerup',pointerId:7,clientX:80,clientY:80});
      out.released=[shield(),band===null,selection.join()];
      startBand({pointerId:8,clientX:0,clientY:0});onBandUp({type:'pointercancel',pointerId:8,clientX:5,clientY:5});
      out.cancelled=[shield(),band===null];
      startBand({pointerId:9,clientX:0,clientY:0});onBandMove({pointerId:9,clientX:60,clientY:60,preventDefault(){}});
      onWindowBlur();
      out.blurred=[shield(),band===null,[...listeners.keys()].filter(k=>k.includes('Band'))];
      return out;
    """)
    assert result["started"] is True
    assert result["released"] == [False, True, "pw-1"]
    assert result["cancelled"] == [False, True]
    assert result["blurred"] == [False, True, []]


def test_focus_taken_by_a_prefab_frame_selects_its_window_without_a_gesture(tmp_path):
    result = run_page(tmp_path, r"""
      const out={};
      document.activeElement=B.frame;onWindowBlur();
      out.selected=selection.slice();out.touched=touched.slice();out.focusId=focusId;
      out.frameKeepsFocus=document.activeElement===B.frame;out.menus=log.filter(e=>e[0]==='menu').length;
      /* La page perd le focus pour autre chose qu'un cadre : rien ne change. */
      document.activeElement=null;onWindowBlur();out.otherBlur=selection.slice();
      /* Un IFRAME qui n'est pas un cadre de prefab (visage) : ignoré. */
      const face=el('IFRAME');document.activeElement=face;onWindowBlur();out.face=selection.slice();
      return out;
    """)
    assert result == {"selected": ["pw-2"], "touched": ["pw-2"], "focusId": "pw-2", "frameKeepsFocus": True,
                      "menus": 0, "otherBlur": ["pw-2"], "face": ["pw-2"]}


def test_focus_in_a_frame_keeps_a_multi_selection_that_already_holds_its_window(tmp_path):
    result = run_page(tmp_path, r"""
      applySelection(['pw-2','pw-1']);
      document.activeElement=B.frame;onWindowBlur();
      return {selection,selectedId};
    """)
    assert result == {"selection": ["pw-1", "pw-2"], "selectedId": "pw-2"}
