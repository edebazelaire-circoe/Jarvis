"""Hôte des cadres de prefab (prefab-foundation, Slice 03).

Contrat : `jarvis/runtime/control_center_prefab_host.js`, `docs/prefabs.md` ›
*Runtime*. `createPrefabHost(deps)` exécuté par node avec un faux document,
une fausse fenêtre, une horloge manuelle et les paquets servis par le vrai
catalogue (`PrefabService.bundle`) : montage unique, mise à jour sans
remontage, remontage au changement de version, écoute retirée au dernier
démontage, contrôle source/origine, limite de débit, plafond de 24 en LRU,
bande d'erreur, mode aperçu sans envoi.
"""

from __future__ import annotations

import re

import pytest

from tests.fakes.prefab_js import HOST_JS, catalogue_bundles, run_node


@pytest.fixture
async def bundles(tmp_path):
    return {"bundles": await catalogue_bundles(tmp_path, "test.counter", "test.netprobe")}


async def test_a_prefab_unknown_to_core_code_mounts_through_the_catalogue(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      const first=b.host.mount(s,instance('obj_1'));
      await flush();
      const frame=b.frameOf(s);
      const write=frame.srcdocWrites[0];
      b.send(s,{jv:1,type:'ready'});
      return {first,fetches:b.fetches,writes:frame.srcdocWrites.length,sandbox:write.sandbox,attr:frame.getAttribute('sandbox'),
              csp:write.value.includes("default-src 'none'"),template:write.value.includes('data-jv-text="data.count"'),
              shim:write.value.includes('createShim'),listening:b.win.count('message'),inbox:b.inbox(s),
              style:!!b.doc.getElementById('jv-prefab-host-style'),slotClass:s.className,state:b.host.state('obj_1'),
              title:frame.getAttribute('title'),notes:s.byClass('sc-prefab-note').length,
              blocks:JSON.stringify(b.inbox(s)[0].blocks)===JSON.stringify({'data.notes':Lay.markdownBlocks('**bold** note')})};
    """, bundles)
    assert result["first"] is True and result["fetches"] == ["test.counter@1"]
    assert result["writes"] == 1 and result["sandbox"] == "allow-scripts" and result["attr"] == "allow-scripts"
    assert result["csp"] and result["template"] and result["shim"]
    assert result["listening"] == 1 and result["style"] and "sc-prefab-slot" in result["slotClass"]
    assert result["state"] == "ready" and result["notes"] == 0
    assert result["title"] == "Counter obj_1 (prefab test.counter@1)"
    init = result["inbox"][0]
    assert init["type"] == "init" and init["instance"] == {"object_id": "obj_1", "prefab": {"id": "test.counter", "version": 1},
                                                           "mode": "scene"}
    assert init["data"] == {"count": 3, "notes": "**bold** note"} and init["props"] == {"label": "Count"}
    assert init["theme"]["accent"] == "#6ee7ff"
    # Une seule source markdown : les blocs de `data.notes` (format markdown) viennent de JarvisSceneLayout.
    assert result["blocks"] is True


async def test_updates_never_remount_and_are_diffed(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      const frame=b.frameOf(s);
      const early=b.host.update('obj_1',{label:'Early'},{count:3,notes:'**bold** note'});
      b.send(s,{jv:1,type:'ready'});
      const same=b.host.update('obj_1',{label:'Early'},{count:3,notes:'**bold** note'});
      const changed=b.host.update('obj_1',{label:'Early'},{count:4,notes:'**bold** note'});
      const again=b.host.mount(s,instance('obj_1',{props:{label:'Early'},data:{count:5}}));
      return {early,same,changed,again,sameFrame:b.frameOf(s)===frame,writes:frame.srcdocWrites.length,
              inbox:b.inbox(s).map(m=>[m.type,m.data&&m.data.count,m.props&&m.props.label]),fetches:b.fetches};
    """, bundles)
    assert (result["early"], result["same"], result["changed"], result["again"]) == (True, False, True, False)
    assert result["sameFrame"] is True and result["writes"] == 1 and result["fetches"] == ["test.counter@1"]
    assert result["inbox"] == [["init", 3, "Early"], ["update", 4, "Early"], ["update", 5, "Early"]]


async def test_a_version_change_remounts_and_the_old_frame_gets_teardown(tmp_path, bundles):
    bundles["bundles"]["test.counter@2"] = {**bundles["bundles"]["test.counter@1"], "version": 2}
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      const old=b.frameOf(s);b.send(s,{jv:1,type:'ready'});
      b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:2}}));await flush();
      const frames=s.children.filter(n=>n.tagName==='IFRAME');
      const during=frames.length;
      b.clock.advance(50);
      const after=s.children.filter(n=>n.tagName==='IFRAME');
      return {during,after:after.length,fresh:after[0]!==old,oldLast:old.contentWindow.posted.map(p=>p.message.type),
              fetches:b.fetches,state:b.host.state('obj_1')};
    """, bundles)
    assert result["during"] == 2 and result["after"] == 1 and result["fresh"] is True
    assert result["oldLast"] == ["init", "teardown"]
    assert result["fetches"] == ["test.counter@1", "test.counter@2"] and result["state"] == "loading"


async def test_unmount_removes_the_frame_and_the_last_one_removes_the_listener(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const a=b.slot(),c=b.slot();
      b.host.mount(a,instance('obj_a'));b.host.mount(c,instance('obj_c'));await flush();
      b.send(a,{jv:1,type:'ready'});
      const listeners=[b.win.count('message')];
      b.host.unmount('obj_a');listeners.push(b.win.count('message'));
      b.host.unmount('obj_c');listeners.push(b.win.count('message'));
      b.clock.advance(60);
      return {listeners,left:[a.children.length,c.children.length],gone:[b.host.has('obj_a'),b.host.has('obj_c')],
              again:b.host.unmount('obj_a'),stats:b.host.stats()};
    """, bundles)
    assert result["listeners"] == [1, 1, 0] and result["left"] == [0, 0] and result["gone"] == [False, False]
    assert result["again"] is False and result["stats"]["frames"] == 0 and result["stats"]["departing"] == 0


async def test_only_the_frame_itself_with_an_opaque_origin_is_heard(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      const frame=b.frameOf(s);
      b.win.dispatch({source:{},origin:'null',data:{jv:1,type:'ready'}});           // another window: not ours
      b.win.dispatch({source:frame.contentWindow,origin:'http://127.0.0.1:17654',data:{jv:1,type:'ready'}});
      b.win.dispatch({source:frame.contentWindow,origin:'null',data:{jv:2,type:'ready'}});
      b.win.dispatch({source:frame.contentWindow,origin:'null',data:'{"jv":1,"type":"ready"}'});
      const before=b.host.state('obj_1');
      b.send(s,{jv:1,type:'ready'});
      return {before,after:b.host.state('obj_1'),stats:b.host.stats(),
              logs:b.logs.filter(l=>l.key==='scene.prefab_message_dropped').map(l=>l.data.reason)};
    """, bundles)
    assert result["before"] == "loading" and result["after"] == "ready"
    assert result["stats"]["dropped"] == 3
    assert result["logs"] == ["origin is not opaque", "not jv:1", "not an object"]


async def test_state_events_carry_the_basis_and_are_rate_limited(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      const early=()=>b.send(s,{jv:1,type:'event',name:'incremented',payload:{count:4}});
      early();
      b.send(s,{jv:1,type:'ready'});
      b.send(s,{jv:1,type:'event',name:'incremented',payload:{count:4}});
      b.send(s,{jv:1,type:'event',name:'reset_requested',payload:{from:3}});
      b.send(s,{jv:1,type:'event',name:'not_declared',payload:{}});
      for(let i=0;i<12;i++)b.send(s,{jv:1,type:'event',name:'reset_requested',payload:{from:i}});
      b.clock.advance(1000);
      b.send(s,{jv:1,type:'event',name:'reset_requested',payload:{from:99}});
      await flush();
      return {posted:b.posted,stats:b.host.stats(),
              rate:b.logs.filter(l=>l.key==='scene.prefab_event_rate_limited').length};
    """, bundles)
    first, second = result["posted"][0], result["posted"][1]
    assert first == {"object_id": "obj_1", "prefab": {"id": "test.counter", "version": 1}, "event": "incremented",
                     "payload": {"count": 4}, "basis": {"count": 3}}
    assert second["event"] == "reset_requested" and second["basis"] == {}
    # 10 par seconde : 2 + 8 de la rafale passent, 4 refusés ; la seconde suivante repart.
    assert len(result["posted"]) == 11 and result["posted"][-1]["payload"] == {"from": 99}
    assert result["stats"]["rateLimited"] == 4 and result["rate"] == 1
    assert result["stats"]["dropped"] == 2  # avant `ready`, puis l'événement non déclaré


async def test_preview_mode_never_posts_events(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench({mode:'preview'});const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'ready'});
      b.send(s,{jv:1,type:'event',name:'incremented',payload:{count:4}});
      await flush();
      return {posted:b.posted.length,preview:b.preview,mode:b.inbox(s)[0].instance.mode,stats:b.host.stats()};
    """, bundles)
    assert result["posted"] == 0 and result["mode"] == "preview"
    assert result["preview"][0]["event"] == "incremented" and result["stats"]["previewEvents"] == 1


async def test_twenty_four_live_frames_then_the_least_recent_pauses(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const slots=[];
      for(let i=0;i<25;i++){b.clock.t+=10;const s=b.slot();slots.push(s);b.host.mount(s,instance('obj_'+i))}
      await flush();
      const first=b.host.stats();
      const paused0=b.host.state('obj_0');
      const placeholder=slots[0].textContent;
      b.clock.t+=10;b.host.touch('obj_0');await flush();
      return {first,paused0,placeholder,resumed:b.host.state('obj_0'),paused1:b.host.state('obj_1'),second:b.host.stats(),
              frame0:!!b.frameOf(slots[0]),fetches:b.fetches.length};
    """, bundles)
    assert result["first"]["live"] == 24 and result["first"]["paused"] == 1 and result["paused0"] == "paused"
    assert "Counter obj_0" in result["placeholder"] and "En pause" in result["placeholder"]
    assert result["resumed"] == "loading" and result["paused1"] == "paused" and result["frame0"] is True
    assert result["second"]["live"] == 24 and result["second"]["paused"] == 1
    # Un seul paquet par version, quel que soit le nombre de cadres.
    assert result["fetches"] == 1


async def test_errors_show_a_band_and_the_window_stays_usable(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot(),t=b.slot(),u=b.slot();
      b.host.mount(s,instance('obj_err'));await flush();
      b.send(s,{jv:1,type:'error',message:'boom'});
      const band=s.byClass('sc-prefab-error')[0];
      b.send(s,{jv:1,type:'ready'});
      const afterReady=[b.host.state('obj_err'),s.byClass('sc-prefab-error').length];
      b.host.mount(t,instance('obj_slow'));await flush();
      b.clock.advance(3000);
      const timeout=t.byClass('sc-prefab-error')[0].textContent;
      b.send(t,{jv:1,type:'ready'});
      const recovered=[b.host.state('obj_slow'),t.byClass('sc-prefab-error').length];
      b.host.mount(u,instance('obj_missing',{prefab:{id:'test.missing',version:1}}));await flush();
      b.clock.advance(3000);
      const missing=u.byClass('sc-prefab-error')[0].textContent;
      const retry=u.byClass('sc-prefab-retry')[0];
      retry.click();await flush();
      return {band:band.textContent,role:band.getAttribute('role'),afterReady,timeout,recovered,missing,
              retried:b.fetches.filter(f=>f==='test.missing@1').length,frameKept:!!b.frameOf(s),
              errors:b.logs.filter(l=>l.key==='scene.prefab_error').map(l=>[l.data.object_id,l.data.reason])};
    """, bundles)
    assert result["band"].startswith("Prefab test.counter@1 failed: boom") and result["role"] == "alert"
    assert result["afterReady"] == ["error", 1] and result["frameKept"] is True
    assert result["timeout"].startswith("Prefab test.counter@1 failed: no ready within 3 s")
    assert result["recovered"] == ["ready", 0]
    assert result["missing"].startswith("Prefab test.missing@1 failed: unknown_prefab: no prefab test.missing")
    assert result["retried"] == 2
    assert ["obj_err", "frame"] in result["errors"] and ["obj_slow", "timeout"] in result["errors"]
    assert ["obj_missing", "bundle"] in result["errors"]
    assert ["obj_missing", "timeout"] not in result["errors"]


async def test_resize_and_open_url(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'ready'});
      b.send(s,{jv:1,type:'resize',height:9000});
      const h1=[b.frameOf(s).style.height,b.host.height('obj_1')];
      b.send(s,{jv:1,type:'resize',height:131.6});
      b.clock.advance(16);  // resize regroupés : un par tranche de 16 ms
      b.send(s,{jv:1,type:'open_url',url:'https://example.com/doc'});
      b.send(s,{jv:1,type:'open_url',url:'javascript:alert(1)'});
      return {h1,h2:b.frameOf(s).style.height,resizes:b.resizes,opened:b.win.opened,dropped:b.host.stats().dropped};
    """, bundles)
    assert result["h1"] == ["4000px", 4000] and result["h2"] == "132px"
    assert result["resizes"] == [["obj_1", 4000], ["obj_1", 132]]
    assert result["opened"] == [{"url": "https://example.com/doc", "target": "_blank", "features": "noopener,noreferrer"}]
    assert result["dropped"] == 1


async def test_repeated_lifecycles_leave_nothing_behind(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      for(let i=0;i<200;i++){
        b.host.mount(s,instance('obj_'+i));await flush(2);
        b.send(s,{jv:1,type:'ready'});
        b.host.unmount('obj_'+i);b.clock.advance(60);
      }
      return {stats:b.host.stats(),listeners:b.win.count('message'),children:s.children.length,timers:b.clock.timers.length};
    """, bundles)
    assert result["stats"]["frames"] == 0 and result["stats"]["departing"] == 0 and result["stats"]["bundles"] == 1
    assert result["listeners"] == 0 and result["children"] == 0 and result["timers"] == 0


def test_the_host_requires_its_dependencies(tmp_path):
    result = run_node(tmp_path, r"""
      const errors=[];
      for(const deps of [undefined,{},{fetchBundle:()=>null},{fetchBundle:()=>null,document:new FakeDocument()}]){
        try{H.createPrefabHost(deps);errors.push(null)}catch(e){errors.push(e.name)}
      }
      const b=bench();
      for(const bad of [[null,instance('x')],[b.slot(),{object_id:'',prefab:{id:'a.b',version:1}}],[b.slot(),{object_id:'x',prefab:{id:'a.b',version:0}}]]){
        try{b.host.mount(...bad);errors.push(null)}catch(e){errors.push(e.name)}
      }
      return {errors,constants:[H.LIVE_CAP,H.READY_TIMEOUT_MS,H.TEARDOWN_MS,H.OUTPUT_RATE]};
    """)
    assert result["errors"] == ["TypeError"] * 7
    assert result["constants"] == [24, 3000, 50, 10]


def test_bundle_fetcher_checks_the_response(tmp_path):
    result = run_node(tmp_path, r"""
      const calls=[];
      const ok=H.bundleFetcher(async(path,opts)=>{calls.push(path);return {ok:true,status:200,json:async()=>({id:'a.b'})}});
      const ko=H.bundleFetcher(async()=>({ok:false,status:409,json:async()=>({error:{code:'tampered',message:'a.b@1: edited'}})}));
      const bad=H.bundleFetcher(async()=>({ok:false,status:502,json:async()=>{throw new Error('not json')}}));
      const out=[await ok('a.b',3)];
      for(const f of [ko,bad]){try{await f('a.b',1);out.push(null)}catch(e){out.push(e.message)}}
      return {out,calls};
    """)
    assert result["out"] == [{"id": "a.b"}, "tampered: a.b@1: edited", "http_502: HTTP 502"]
    assert result["calls"] == ["/api/prefabs/a.b/3/bundle"]


def test_the_frame_takes_its_reported_height_but_shrinks_to_the_window():
    """Slice 05 (reprise QA F7) : le cadre part de la hauteur rapportée (`flex-basis:auto` + `style.height`) et
    rétrécit à son conteneur (`flex:0 1 auto` dans une colonne flex) ; il ne grandit jamais au-delà, et son
    contenu plus haut défile dans le cadre au lieu d'un second défileur."""

    css = re.sub(r"\s+", " ", HOST_JS.read_text(encoding="utf-8"))
    frame = re.search(r"\.sc-prefab-frame\{([^}]*)\}", css).group(1)
    slot = re.search(r"\.sc-prefab-slot\{([^}]*)\}", css).group(1)
    assert "flex:0 1 auto" in frame and "flex-shrink:0" not in frame and "height:100%" not in frame
    assert "display:flex" in slot and "flex-direction:column" in slot and "min-height" in slot


# ------------------------------------------------------------ reprise QA S04 (A2, A4, A5)


async def test_a_written_key_the_frame_never_saw_goes_out_as_a_null_basis_a2(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1',{data:{count:3}}));await flush();
      b.send(s,{jv:1,type:'ready'});
      b.send(s,{jv:1,type:'event',name:'incremented',payload:{count:4,history:[{delta:1}]}});
      await flush();
      return b.posted[0].basis;
    """, bundles)
    assert result == {"count": 3, "history": None}


async def test_the_frame_learns_every_event_outcome_and_stale_forces_an_update_a4(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const answers=[{outcome:'applied',revision:2},{outcome:'stale',reason:'stale'},
        {outcome:'refused',reason:'invalid_event',detail:'payload.count: got 7'},
        Object.assign(new Error('rate_limited: too many'),{code:'rate_limited'}),new Error('network down'),
        {outcome:'recorded'}];
      const b=bench({postEvent:()=>{const a=answers.shift();return a instanceof Error?Promise.reject(a):Promise.resolve(a)}});
      const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'ready'});
      const state=()=>b.send(s,{jv:1,type:'event',name:'incremented',payload:{count:4}});
      for(let i=0;i<5;i++){state();await flush();b.clock.advance(1000)}
      b.send(s,{jv:1,type:'event',name:'reset_requested',payload:{from:1}});await flush();
      return b.inbox(s).filter(m=>m.type!=='init').map(m=>m.type==='update'?{type:'update',force:m.force,data:m.data}:m);
    """, bundles)
    assert result == [
        {"jv": 1, "type": "event_result", "name": "incremented", "outcome": "applied"},
        {"jv": 1, "type": "event_result", "name": "incremented", "outcome": "stale", "reason": "stale"},
        # `stale` : l'état connu repart aussitôt, marqué `force` (le shim ne le prend pas pour un doublon).
        {"type": "update", "force": True, "data": {"count": 3, "notes": "**bold** note"}},
        {"jv": 1, "type": "event_result", "name": "incremented", "outcome": "refused", "reason": "invalid_event"},
        {"jv": 1, "type": "event_result", "name": "incremented", "outcome": "failed", "reason": "rate_limited"},
        {"jv": 1, "type": "event_result", "name": "incremented", "outcome": "failed", "reason": "unreachable"},
        {"jv": 1, "type": "event_result", "name": "reset_requested", "outcome": "recorded"},
    ]


async def test_host_side_drops_are_told_to_the_frame_a4(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'ready'});
      b.send(s,{jv:1,type:'event',name:'not_declared',payload:{}});
      b.send(s,{jv:1,type:'event',name:'reset_requested',payload:{from:1,pad:'x'.repeat(9000)}});
      for(let i=0;i<11;i++)b.send(s,{jv:1,type:'event',name:'reset_requested',payload:{from:i}});
      await flush();
      return {posted:b.posted.length,results:b.inbox(s).filter(m=>m.type==='event_result'&&m.outcome!=='applied')};
    """, bundles)
    # Un notify de plus de 8 Kio n'est pas envoyé ; le débit (10/s) compte chaque sortie acceptée.
    assert result["posted"] == 10
    assert result["results"] == [
        {"jv": 1, "type": "event_result", "name": "not_declared", "outcome": "refused", "reason": "undeclared_event"},
        {"jv": 1, "type": "event_result", "name": "reset_requested", "outcome": "refused", "reason": "too_large"},
        {"jv": 1, "type": "event_result", "name": "reset_requested", "outcome": "refused", "reason": "rate_limited"},
    ]


async def test_a_state_event_may_carry_up_to_16_kib_a5(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'ready'});
      const history=Array.from({length:8},(_,i)=>({delta:i,pad:'é'.repeat(800)}));
      b.send(s,{jv:1,type:'event',name:'incremented',payload:{count:4,history}});
      b.send(s,{jv:1,type:'event',name:'incremented',payload:{count:4,history:[{pad:'x'.repeat(17000)}]}});
      await flush();
      return {posted:b.posted.length,bytes:P.jsonBytes(b.posted[0].payload),limits:[P.MAX_EVENT_PAYLOAD_BYTES,
        P.MAX_STATE_EVENT_PAYLOAD_BYTES,P.MAX_NOTIFY_PAYLOAD_BYTES],
        dropped:b.logs.filter(l=>l.key==='scene.prefab_message_dropped').map(l=>l.data.reason)};
    """, bundles)
    assert result["posted"] == 1 and 12 * 1024 < result["bytes"] <= 16 * 1024
    assert result["limits"] == [16384, 16384, 8192] and result["dropped"] == ["event payload too large"]
