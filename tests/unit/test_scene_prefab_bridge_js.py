"""Pont page de scène ↔ hôte des cadres (handoff jarvis-scene-window-prefab-foundation, Slice 04).

Exécuté par node avec le faux DOM de `tests/fakes/prefab_js.py`, le vrai hôte
(`control_center_prefab_host.js`), ses aides de scène (`sceneSlot`,
`clearAround`, `placeAround`, `syncScene`, celles que la page appelle) et les
paquets servis par le vrai catalogue. Ce qui doit tenir :

- un nouveau dessin du nœud (titre changé) ne détache ni ne remonte le cadre ;
- un changement de `data` = un seul message `update`, rien de plus ;
- une autre forme dessinée ou le retrait de l'objet démontent le cadre ;
- un événement `stale` renvoie l'état courant au cadre ;
- la capture dessine le repli `prefab <id>@<version>` ;
- la page passe par ces aides et ne pose aucun HTML elle-même.
"""

from __future__ import annotations

import re

import pytest

from tests.fakes.prefab_js import catalogue_bundles, run_node
from tests.unit.test_scene_capture_logic import run_node as run_capture
from tests.unit.test_scene_renderer_logic import PAGE_JS

#: Ce que la page fait pour un nœud, réduit à ses appels au module hôte (voir
#: `fill` et `applyNodes` dans `control_center_scene_page.js`).
PAGE = r"""
function page(b){
  const el=b.doc.createElement('div');b.doc.body.appendChild(el);
  const record={el,content:''};
  function fill(node){
    const slot=node.prefab&&node.shape==='window'?H.sceneSlot(el,true):null;
    if(slot)H.clearAround(el,slot);else el.replaceChildren();
    const head=b.doc.createElement('div');head.className='sc-head';
    const title=b.doc.createElement('div');title.className='sc-wtitle';title.textContent=node.title;
    const grip=b.doc.createElement('span');grip.className='sc-grip';
    if(slot)H.placeAround(el,slot,[head,title],[grip]);else{el.appendChild(head);el.appendChild(title)}
  }
  function pass(node){
    const content=JSON.stringify([node.shape,node.title,node.prefabKey]);
    if(content!==record.content){fill(node);record.content=content}
    return node.prefab||record.prefabKey?H.syncScene(b.host,record,el,node):'none';
  }
  return {el,record,pass,remove(id){if(b.host.has(id))b.host.unmount(id);el.remove()}};
}
const node=(extra)=>Object.assign({id:'obj_1',shape:'window',title:'Compteur',
  prefab:{id:'test.counter',version:1,props:{label:'Clics'},data:{count:3}},prefabKey:'test.counter@1'},extra||{});
const updates=(inbox)=>inbox.filter(m=>m.type==='update');
"""


@pytest.fixture
async def bundles(tmp_path):
    return {"bundles": await catalogue_bundles(tmp_path, "test.counter")}


async def test_redrawing_the_window_never_detaches_or_remounts_the_frame(tmp_path, bundles):
    result = run_node(tmp_path, PAGE + r"""
      const b=bench();const p=page(b);
      const first=p.pass(node());await flush();
      const slot=H.sceneSlot(p.el,false),frame=b.frameOf(slot);
      b.send(slot,{jv:1,type:'ready'});
      const removed=[];const original=slot.removeChild.bind(slot);
      slot.removeChild=(c)=>{removed.push(c.tagName);return original(c)};
      const elRemoved=[];const elOriginal=p.el.removeChild.bind(p.el);
      p.el.removeChild=(c)=>{elRemoved.push(c.className||c.tagName);return elOriginal(c)};
      const second=p.pass(node({title:'Compteur renommé'}));
      const order=p.el.children.map(c=>c.className);
      return {first,second,same:b.frameOf(H.sceneSlot(p.el,false))===frame,sameSlot:H.sceneSlot(p.el,false)===slot,
        writes:frame.srcdocWrites.length,iframes:b.doc.created.filter(n=>n.tagName==='IFRAME').length,removed,elRemoved,order,
        title:p.el.children[1].textContent,inbox:b.inbox(slot).map(m=>m.type)};
    """, bundles)
    assert result["first"] == "mount" and result["second"] == "none"
    assert result["same"] and result["sameSlot"] and result["writes"] == 1 and result["iframes"] == 1
    assert result["removed"] == [] and "sc-prefab-slot" not in result["elRemoved"]
    assert result["order"] == ["sc-head", "sc-wtitle", "sc-prefab-slot", "sc-grip"]
    assert result["title"] == "Compteur renommé" and result["inbox"] == ["init"]


async def test_a_data_change_is_one_update_message(tmp_path, bundles):
    result = run_node(tmp_path, PAGE + r"""
      const b=bench();const p=page(b);
      p.pass(node());await flush();
      const slot=H.sceneSlot(p.el,false);b.send(slot,{jv:1,type:'ready'});
      const changed=p.pass(node({prefab:{id:'test.counter',version:1,props:{label:'Clics'},data:{count:4}}}));
      const again=p.pass(node({prefab:{id:'test.counter',version:1,props:{label:'Clics'},data:{count:4}}}));
      const list=updates(b.inbox(slot));
      return {changed,again,count:list.length,data:list[0].data,props:list[0].props,iframes:b.doc.created.filter(n=>n.tagName==='IFRAME').length};
    """, bundles)
    assert result["changed"] == "update" and result["again"] == "none" and result["count"] == 1
    assert result["data"] == {"count": 4} and result["props"] == {"label": "Clics"} and result["iframes"] == 1


async def test_another_drawn_shape_a_new_version_or_removal_unmount(tmp_path, bundles):
    bundles["bundles"]["test.counter@2"] = {**bundles["bundles"]["test.counter@1"], "version": 2}
    result = run_node(tmp_path, PAGE + r"""
      const b=bench();const p=page(b);
      p.pass(node());await flush();
      let slot=H.sceneSlot(p.el,false);const first=b.frameOf(slot);b.send(slot,{jv:1,type:'ready'});
      const compact=p.pass(node({shape:'capsule'}));
      const afterCompact={has:b.host.has('obj_1'),slot:!!H.sceneSlot(p.el,false),teardown:first.contentWindow.posted.some(m=>m.message.type==='teardown')};
      const back=p.pass(node());await flush();
      const v2=p.pass(node({prefab:{id:'test.counter',version:2,props:{},data:{count:1}},prefabKey:'test.counter@2'}));await flush();
      const fetches=b.fetches.slice();
      p.remove('obj_1');b.clock.advance(100);
      return {compact,afterCompact,back,v2,fetches,has:b.host.has('obj_1'),listening:b.win.count('message'),stats:b.host.stats()};
    """, bundles)
    assert result["compact"] == "unmount"
    assert result["afterCompact"] == {"has": False, "slot": False, "teardown": True}
    assert result["back"] == "mount" and result["v2"] == "mount"
    assert result["fetches"] == ["test.counter@1", "test.counter@2"]
    assert result["has"] is False and result["listening"] == 0 and result["stats"]["frames"] == 0


async def test_drawing_keeps_live_frames_recent_but_never_resumes_a_paused_one(tmp_path, bundles):
    result = run_node(tmp_path, PAGE + r"""
      const b=bench();const p=page(b);
      p.pass(node());await flush();
      b.clock.t+=500;p.pass(node());
      const live=b.host.state('obj_1');
      b.host.pause('obj_1');
      p.pass(node());
      const paused=b.host.state('obj_1');
      b.host.touch('obj_1');  // ce que fait la page à la sélection
      return {live,paused,resumed:b.host.state('obj_1')};
    """, bundles)
    assert result == {"live": "loading", "paused": "paused", "resumed": "loading"}


async def test_a_stale_event_resends_the_current_state(tmp_path, bundles):
    result = run_node(tmp_path, PAGE + r"""
      const b=bench({fetchBundle:(id,v)=>Promise.resolve(JSON.parse(JSON.stringify(D.bundles[`${id}@${v}`])))});
      const p=page(b);
      const outcomes=['stale','applied'];const posted=[];
      // Puits d'événements comme la page : le Core répond stale puis applied.
      const host=H.createPrefabHost({document:b.doc,window:b.win,now:b.clock.now,setTimeout:b.clock.setTimeout,clearTimeout:b.clock.clearTimeout,
        fetchBundle:(id,v)=>Promise.resolve(JSON.parse(JSON.stringify(D.bundles[`${id}@${v}`]))),
        postEvent:(e)=>{posted.push(e);return Promise.resolve({outcome:outcomes.shift()})}});
      b.host=host;
      p.pass(node());await flush();
      const slot=H.sceneSlot(p.el,false);b.send(slot,{jv:1,type:'ready'});
      b.send(slot,{jv:1,type:'event',name:'incremented',payload:{count:4}});await flush();
      const afterStale=updates(b.inbox(slot)).length;
      b.send(slot,{jv:1,type:'event',name:'incremented',payload:{count:4}});await flush();
      return {posted,afterStale,afterApplied:updates(b.inbox(slot)).length,data:updates(b.inbox(slot))[0].data};
    """, bundles)
    assert result["posted"][0] == {"object_id": "obj_1", "prefab": {"id": "test.counter", "version": 1},
                                   "event": "incremented", "payload": {"count": 4}, "basis": {"count": 3}}
    assert result["afterStale"] == 1 and result["afterApplied"] == 1 and result["data"] == {"count": 3}


def test_the_capture_draws_the_prefab_fallback(tmp_path):
    result = run_capture(tmp_path, r"""
      const s=state([obj('w','window',{origin:'user',category:'note',geometry:{x:-60,y:-30,w:64,h:40},
        payload:{title:'Compteur',summary:'Trois clics',items:[{label:'ignorée'}],
          prefab:{id:'test.counter',version:1,props:{},data:{count:3}}}})]);
      const vp=L.viewport(1920,1080);
      const plan=C.drawCommands(L.viewModel(s,L.resolveLayout(s),vp,{}),vp,palette,L);
      return plan.commands.filter(c=>c.op==='text').map(c=>[c.text,c.marker||'']);
    """)
    texts = [text for text, _ in result]
    assert ["prefab test.counter@1", "prefab"] in result
    assert texts.index("Compteur") < texts.index("prefab test.counter@1") < texts.index("Trois clics")
    assert not any("ignorée" in text for text in texts)


def test_the_page_uses_the_host_bridge_and_never_writes_html():
    page = PAGE_JS.read_text(encoding="utf-8")
    for call in ("PrefabHostApi.sceneSlot(el,true)", "PrefabHostApi.clearAround(el,slot)",
                 "PrefabHostApi.placeAround(el,slot,parts,", "PrefabHostApi.syncScene(host,record,record.el,node)",
                 "'/api/prefabs/events'", "prefabHost.unmount(id)", "prefabHost.destroy()", "node.label,node.prefabKey,"):
        assert call in page, call
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|srcdoc", page)
    # La clé de contenu porte `prefabKey`, jamais `props`/`data` (un message, pas un nouveau dessin).
    key = re.search(r"const content=JSON\.stringify\(\[(.*?)\]\);", page, re.S).group(1)
    assert "prefabKey" in key and "prefab.data" not in key and "prefab.props" not in key
