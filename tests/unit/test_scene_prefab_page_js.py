"""Fenêtre prefab dans la VRAIE page de scène (handoff jarvis-scene-window-prefab-foundation, reprise QA S04 F5).

`test_scene_prefab_bridge_js.py` exerce les aides du module hôte avec une
page réduite écrite pour le test ; ici node exécute les fonctions de
`control_center_scene_page.js` elles-mêmes, extraites par leur nom sans
réécriture (motif de `test_scene_gesture_shield_js.py`) : `fill` (contenu
d'un nœud), `syncPrefab` (le pont vers l'hôte) et `applyNodes` (la passe de
dessin : création, nouveau dessin, retrait). Autour d'elles : le faux DOM de
`tests/fakes/prefab_js.py`, le vrai `JarvisSceneLayout`, le vrai hôte des
cadres et le paquet servi par le vrai catalogue ; les aides de dessin sans
rapport avec le cadre (badge, épingle, poignée, placement, tabulation) sont
de petits doubles.

Ce qui doit tenir :

- un nouveau dessin (titre, résumé, épingle changés) refait la tête et le
  titre AUTOUR du conteneur du cadre : le conteneur n'est jamais détaché du
  nœud, l'iframe n'est ni recréé ni réécrit (`srcdoc` une fois) — un iframe
  détaché recharge son document (mutant M17) ;
- un changement de `data` est un message `update`, pas un nouveau dessin ;
- l'objet retiré de la scène démonte son cadre (`teardown`, l'hôte l'oublie)
  et une autre forme dessinée aussi (mutant M19).
"""

from __future__ import annotations

import pytest

from tests.fakes.prefab_js import catalogue_bundles, run_node
from tests.unit.test_scene_gesture_shield_js import PAGE_JS, page_function

#: Fonctions de la page exécutées telles quelles.
PAGE_FUNCTIONS = ("element", "fill", "syncPrefab", "applyNodes")

#: Doubles autour des fonctions de la page, et le faux DOM complété de ce que
#: la page appelle en plus du runtime des prefabs (`append`, `contains`,
#: `dataset`, `classList` itérable avec `toggle`).
DOUBLES = r"""
FakeEl.prototype.append=function(...nodes){for(const n of nodes)this.appendChild(typeof n==='string'?new FakeText(n):n)};
FakeEl.prototype.contains=function(n){for(let x=n;x;x=x.parentNode)if(x===this)return true;return false};
const baseCreate=FakeDocument.prototype.createElement;
FakeDocument.prototype.createElement=function(tag){
  const el=baseCreate.call(this,tag);el.dataset={};const cl=el.classList;
  cl[Symbol.iterator]=function*(){yield* el.className.split(/\s+/).filter(Boolean)};
  cl.toggle=(n,on)=>{if(on===undefined)on=!cl.contains(n);if(on)cl.add(n);else cl.remove(n);return on};
  return el;
};
const b=bench();
const document=b.doc;
const L=Lay,PrefabHostApi=H,I={};
let prefabHost=b.host;
const prefabs=()=>prefabHost;
const logs=[];
const consoleLog=(level,key,data)=>logs.push([level,key]);
const errorText=(e)=>String(e&&e.message||e);
const root=b.doc.createElement('div');b.doc.body.appendChild(root);
const nodes=new Map(),stopping=new Set(),barehandsHeld=new Set();
let selection=[],desk=null;
const appendSpans=(el,spans)=>{for(const s of spans||[])el.appendChild(new FakeText(s.text));return el};
const appendBlocks=(el,blocks)=>el;
const badge=()=>null,originButton=()=>element('button','sc-origin'),itemRow=()=>element('li');
const pin=()=>element('span','sc-pin'),grip=()=>element('span','sc-grip');
const position=()=>{},markItemsThatFit=()=>{},fitBrainWindows=()=>{},updateTabStop=()=>{},restorePendingFocus=()=>{},
  setInnerTabs=()=>{},syncHolding=()=>{};
const node=(extra)=>Object.assign({id:'obj_1',shape:'window',representation:'window',kind:'window',tone:'note',exec:'idle',
  urgency:'',pinned:false,compact:false,titleSpans:[{text:'Compteur'}],category:'note',summary:'',items:[],label:'Compteur',
  prefab:{id:'test.counter',version:1,props:{label:'Clics'},data:{count:3}},prefabKey:'test.counter@1',itemCount:0,
  explains:null,alerted:false,animate:false,cx:100,cy:100,box:{left:0,top:0,width:300,height:200},stack:0},extra||{});
const elOf=(id)=>nodes.get(id).el;
const slotOf=(id)=>H.sceneSlot(elOf(id),false);
const frame=(id)=>b.frameOf(slotOf(id));
"""


def run_page(tmp_path, body: str, bundles, source: str | None = None):
    page = source if source is not None else PAGE_JS.read_text(encoding="utf-8")
    functions = "\n".join(page_function(page, name) for name in PAGE_FUNCTIONS)
    return run_node(tmp_path, DOUBLES + functions + "\n" + body, bundles)


REDRAW = r"""
  applyNodes([node()]);await flush();
  const el=elOf('obj_1'),slot=slotOf('obj_1'),iframe=frame('obj_1');
  b.send(slot,{jv:1,type:'ready'});
  const detached=[];
  const watch=(parent)=>{const remove=parent.removeChild.bind(parent);
    parent.removeChild=(c)=>{if(c===slot||c===iframe)detached.push(c.tagName);return remove(c)}};
  watch(el);watch(slot);
  const replace=el.replaceChildren.bind(el);el.replaceChildren=(...n)=>{if(el.childNodes.includes(slot))detached.push('replace');return replace(...n)};
  applyNodes([node({titleSpans:[{text:'Compteur renommé'}],label:'Compteur renommé',summary:'repli',pinned:true})]);
  await flush();
  const afterTitle={sameSlot:slotOf('obj_1')===slot,slotParent:slot.parentNode===el,sameFrame:frame('obj_1')===iframe,
    frameInSlot:iframe.parentNode===slot,writes:iframe.srcdocWrites.length,iframes:b.doc.created.filter(n=>n.tagName==='IFRAME').length,
    order:el.children.map(c=>c.className.split(' ')[0]),title:el.children[1].textContent};
  applyNodes([node({titleSpans:[{text:'Compteur renommé'}],label:'Compteur renommé',summary:'repli',pinned:true,
    prefab:{id:'test.counter',version:1,props:{label:'Clics'},data:{count:4}}})]);
  await flush();
  return {afterTitle,detached,inbox:b.inbox(slot).map(m=>m.type),lastData:b.inbox(slot).slice(-1)[0].data,
    windowClass:el.classList.contains('sc-prefab-window'),errors:logs.filter(l=>l[0]==='error')};
"""

REMOVE = r"""
  applyNodes([node(),node({id:'obj_2',prefab:{id:'test.counter',version:1,props:{},data:{count:1}}})]);await flush();
  const first=frame('obj_1'),second=frame('obj_2');
  b.send(slotOf('obj_1'),{jv:1,type:'ready'});b.send(slotOf('obj_2'),{jv:1,type:'ready'});
  const el1=elOf('obj_1');
  applyNodes([node({id:'obj_2',shape:'capsule',prefab:{id:'test.counter',version:1,props:{},data:{count:1}}})]);  // obj_1 retiré, obj_2 en capsule
  await flush();b.clock.advance(100);
  return {has1:b.host.has('obj_1'),has2:b.host.has('obj_2'),teardown1:first.contentWindow.posted.map(p=>p.message.type),
    teardown2:second.contentWindow.posted.map(p=>p.message.type),el1Gone:!root.childNodes.includes(el1),
    frame1Attached:!!first.parentNode,slot2:H.sceneSlot(elOf('obj_2'),false),stats:b.host.stats().frames};
"""


@pytest.fixture
async def bundles(tmp_path):
    return {"bundles": await catalogue_bundles(tmp_path, "test.counter")}


async def test_a_redraw_rebuilds_around_the_slot_without_detaching_the_frame(tmp_path, bundles):
    result = run_page(tmp_path, REDRAW, bundles)
    assert result["afterTitle"] == {"sameSlot": True, "slotParent": True, "sameFrame": True, "frameInSlot": True,
                                    "writes": 1, "iframes": 1, "order": ["sc-head", "sc-wtitle", "sc-prefab-slot",
                                                                         "sc-grip"],
                                    "title": "Compteur renommé"}
    assert result["detached"] == [] and result["windowClass"] and result["errors"] == []
    # Les données changées : un message au cadre, pas un nouveau dessin.
    assert result["inbox"] == ["init", "update"] and result["lastData"] == {"count": 4}


async def test_removal_and_another_drawn_shape_unmount_the_frame(tmp_path, bundles):
    result = run_page(tmp_path, REMOVE, bundles)
    assert result["has1"] is False and result["has2"] is False and result["stats"] == 0
    assert result["teardown1"] == ["init", "teardown"] and result["teardown2"] == ["init", "teardown"]
    assert result["el1Gone"] and result["frame1Attached"] is False and result["slot2"] is None
