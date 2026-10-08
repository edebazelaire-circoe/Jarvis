"""Confinement des cadres de prefab (prefab-foundation, Slice 03, rework QA).

Contrat : `docs/prefabs.md` › *Runtime* › *Containment*, `docs/SECURITY.md` §16.
Chaque couche y est éprouvée seule :

- la page du Control Center porte `Content-Security-Policy: frame-src ...`
  limité à ce qu'elle encadre vraiment (le visualiseur configuré), donc un
  cadre de prefab ne peut pas naviguer ailleurs (F1a) ;
- l'hôte traite un second `load` (navigation) et un second `ready` d'une même
  génération comme une violation : cadre retiré, bande d'erreur, journal, plus
  aucun `init` (F1b, F1c) ;
- le lint refuse `<area` (F1d, hygiène) ;
- le protocole borne un message avant toute expression régulière ou
  sérialisation, l'hôte regroupe `resize` et limite `error` (F2) ;
- le plafond de journal d'un cadre repart à chaque génération (F3) ;
- le cache des paquets est borné (LRU) et oublie un paquet inutilisable (F4) ;
- `open_url` d'un cadre refuse les hôtes locaux et privés (F5).
"""

from __future__ import annotations

import pytest

from jarvis.domain import prefab as p
from jarvis.runtime import control_center as cc
from jarvis.runtime.control_center import ControlCenter
from tests.fakes.prefab_js import catalogue_bundles, run_node


@pytest.fixture
async def bundles(tmp_path):
    return {"bundles": await catalogue_bundles(tmp_path, "test.counter")}


# ------------------------------------------------------------------ F1a : CSP de la page


@pytest.mark.asyncio
async def test_the_page_frames_only_the_configured_visualizer(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path,
                            visualizer_url="http://127.0.0.1:8790/faces/board/")
    response = await control.index(None)
    assert response.headers["Content-Security-Policy"] == "frame-src http://127.0.0.1:8790"
    assert '<iframe class="face" src="http://127.0.0.1:8790/faces/board/"' in response.text


@pytest.mark.asyncio
async def test_without_visualizer_the_page_frames_nothing_by_url(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    response = await control.index(None)
    # `'none'` : seuls les cadres `srcdoc` (prefabs) existent, et ils ne peuvent plus naviguer.
    assert response.headers["Content-Security-Policy"] == "frame-src 'none'"
    assert "<iframe" not in response.text.split("<body", 1)[1].split("<script", 1)[0]


@pytest.mark.parametrize(("url", "policy"), [
    (None, "frame-src 'none'"),
    ("", "frame-src 'none'"),
    ("http://127.0.0.1:8790/faces/board/", "frame-src http://127.0.0.1:8790"),
    ("https://LOCALHOST:9443/x?y=1", "frame-src https://localhost:9443"),
    ("http://[::1]:8790/", "frame-src http://[::1]:8790"),
    ("javascript:alert(1)", "frame-src 'none'"),
    ("http://127.0.0.1:8790/a b;c", "frame-src http://127.0.0.1:8790"),
    ("not a url", "frame-src 'none'"),
])
def test_frame_src_policy_is_one_origin_or_none(url, policy):
    assert cc.frame_src_policy(url) == policy


# ------------------------------------------------------------------ F1b, F1c : navigation, second ready


async def test_a_frame_that_navigates_is_removed_and_never_initialized_again(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      const frame=b.frameOf(s);
      frame.load();                         // le document srcdoc
      b.send(s,{jv:1,type:'ready'});
      const before=[b.host.state('obj_1'),frame.contentWindow.posted.length];
      frame.load();                         // location.href=... / <a href> : un autre document
      const view=frame.contentWindow;
      // La page distante parle avec la même fenêtre : plus rien n'est entendu.
      b.win.dispatch({source:view,origin:'null',data:{jv:1,type:'ready'}});
      b.win.dispatch({source:view,origin:'null',data:{jv:1,type:'event',name:'incremented',payload:{count:9}}});
      b.win.dispatch({source:view,origin:'null',data:{jv:1,type:'open_url',url:'https://example.com/x'}});
      await flush();
      return {before,state:b.host.state('obj_1'),attached:!!frame.parentNode,frames:s.children.filter(n=>n.tagName==='IFRAME').length,
              band:(s.byClass('sc-prefab-error')[0]||{textContent:null}).textContent,
              inbox:view.posted.map(p=>p.message.type),posted:b.posted.length,opened:b.win.opened.length,
              errors:b.logs.filter(l=>l.key==='scene.prefab_error').map(l=>l.data.reason)};
    """, bundles)
    assert result["before"] == ["ready", 1]
    assert result["state"] == "error" and result["attached"] is False and result["frames"] == 0
    assert result["band"].startswith("Prefab test.counter@1 failed: the frame navigated away from its document")
    assert result["inbox"] == ["init"] and result["posted"] == 0 and result["opened"] == 0
    assert result["errors"] == ["navigation"]


async def test_a_load_before_the_srcdoc_is_set_is_not_a_navigation(tmp_path, bundles):
    """`about:blank` initial du cadre inséré : son `load` précède le `srcdoc` et ne compte pas."""
    result = run_node(tmp_path, r"""
      let release;const gate=new Promise(r=>release=r);
      const b=bench({fetchBundle:async(id,v)=>{await gate;return JSON.parse(JSON.stringify(D.bundles[`${id}@${v}`]))}});
      const s=b.slot();
      b.host.mount(s,instance('obj_1'));
      const frame=b.frameOf(s);
      frame.load();                         // about:blank, avant le paquet
      release();await flush();
      frame.load();                         // le document srcdoc
      b.send(s,{jv:1,type:'ready'});
      return {state:b.host.state('obj_1'),inbox:b.inbox(s).map(m=>m.type)};
    """, bundles)
    assert result == {"state": "ready", "inbox": ["init"]}


async def test_a_second_ready_is_a_protocol_violation_and_gets_no_second_init(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      const frame=b.frameOf(s);const view=frame.contentWindow;
      b.send(s,{jv:1,type:'ready'});
      b.send(s,{jv:1,type:'ready'});
      return {state:b.host.state('obj_1'),attached:!!frame.parentNode,inbox:view.posted.map(p=>p.message.type),
              band:(s.byClass('sc-prefab-error')[0]||{textContent:null}).textContent,
              errors:b.logs.filter(l=>l.key==='scene.prefab_error').map(l=>l.data.reason)};
    """, bundles)
    assert result["inbox"] == ["init"] and result["state"] == "error" and result["attached"] is False
    assert result["band"].startswith("Prefab test.counter@1 failed: second ready")
    assert result["errors"] == ["protocol"]


async def test_reload_after_a_violation_mounts_a_fresh_frame(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      const first=b.frameOf(s);first.load();b.send(s,{jv:1,type:'ready'});first.load();
      s.byClass('sc-prefab-retry')[0].click();await flush();
      const fresh=b.frameOf(s);fresh.load();b.send(s,{jv:1,type:'ready'});
      return {fresh:fresh!==first,state:b.host.state('obj_1'),inbox:b.inbox(s).map(m=>m.type),bands:s.byClass('sc-prefab-error').length};
    """, bundles)
    assert result == {"fresh": True, "state": "ready", "inbox": ["init"], "bands": 0}


# ------------------------------------------------------------------ F1d : lint


def test_lint_refuses_area_links():
    assert any("<area>" in item for item in p.lint_sources('<map name="m"><AREA href="https://x.test/"></map>', "", ""))
    assert p.lint_sources("<p>a rearranged areas list</p>", "", "") == ()


# ------------------------------------------------------------------ F2 : bornes avant travail, débits


def test_an_oversized_message_is_refused_before_any_serialization_or_regex(tmp_path):
    result = run_node(tmp_path, r"""
      const huge='a'.repeat(64*1024*1024);
      const spy={stringify:0,replace:0,test:0};
      const stringify=JSON.stringify;JSON.stringify=function(){spy.stringify++;return stringify.apply(this,arguments)};
      const replace=String.prototype.replace;String.prototype.replace=function(){if(this.length>1e6)spy.replace++;return replace.apply(this,arguments)};
      const test=RegExp.prototype.test;RegExp.prototype.test=function(s){if(typeof s==='string'&&s.length>1e6)spy.test++;return test.apply(this,arguments)};
      const wide={};for(let i=0;i<200000;i++)wide['k'+i]=i;
      const t0=Date.now();
      const event=P.parseFrameMessage({jv:1,type:'event',name:'probed',payload:{s:huge}});
      const deep=P.parseFrameMessage({jv:1,type:'event',name:'probed',payload:wide});
      const nested=P.parseFrameMessage({jv:1,type:'event',name:'probed',payload:{a:[[[[huge]]]]}});
      const name=P.parseFrameMessage({jv:1,type:'event',name:huge,payload:{}});
      const error=P.parseFrameMessage({jv:1,type:'error',message:'boom\n'+huge});
      const url=P.parseFrameMessage({jv:1,type:'open_url',url:huge});
      const cyclic={};cyclic.self=cyclic;
      const cycle=P.parseFrameMessage({jv:1,type:'event',name:'probed',payload:cyclic});
      const ms=Date.now()-t0;
      JSON.stringify=stringify;String.prototype.replace=replace;RegExp.prototype.test=test;
      return {spy,ms,event:event.reason,deep:deep.reason,nested:nested.reason,name:name.reason,url:url.reason,cycle:cycle.ok,
              error:error.ok&&error.message.message.length,errorStart:error.message.message.slice(0,10),
              small:P.parseFrameMessage({jv:1,type:'event',name:'probed',payload:{s:'é'.repeat(100)}}).ok};
    """)
    assert result["spy"] == {"stringify": 0, "replace": 0, "test": 0}
    assert result["event"] == result["deep"] == result["nested"] == "event payload too large"
    assert result["name"] == "event name" and result["url"] == "url refused" and result["cycle"] is False
    assert result["error"] == 300 and result["errorStart"] == "boom aaaaa"
    assert result["small"] is True
    assert result["ms"] < 2000


async def test_a_resize_flood_is_coalesced(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'ready'});
      for(let i=0;i<2000;i++)b.send(s,{jv:1,type:'resize',height:30+i%500});
      const during=[b.resizes.length,b.frameOf(s).style.height];
      b.clock.advance(16);
      const after=[b.resizes.length,b.frameOf(s).style.height];
      b.clock.advance(100);
      b.clock.advance(H.SETTLE_MS);   // the host's own "mounted" settle timer (Slice 06) is the only one still pending
      return {during,after,later:b.resizes.length,last:b.resizes[b.resizes.length-1],timers:b.clock.timers.length};
    """, bundles)
    # Le premier s'applique tout de suite, le reste se résume au dernier, une fois par tranche de 16 ms.
    assert result["during"] == [1, "30px"]
    assert result["after"] == [2, f"{30 + 1999 % 500}px"] and result["later"] == 2
    assert result["last"] == ["obj_1", 30 + 1999 % 500] and result["timers"] == 0


async def test_an_error_flood_is_rate_limited(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'ready'});
      for(let i=0;i<1000;i++)b.send(s,{jv:1,type:'error',message:'e'+i});
      const stats=b.host.stats();
      b.clock.advance(1000);
      b.send(s,{jv:1,type:'error',message:'later'});
      return {errors:stats.errors,rateLimited:stats.rateLimited,band:s.byClass('sc-prefab-error')[0].textContent,
              rateLogs:b.logs.filter(l=>l.key==='scene.prefab_event_rate_limited').length};
    """, bundles)
    assert result["errors"] == 10 and result["rateLimited"] == 990
    assert result["band"].startswith("Prefab test.counter@1 failed: later")
    assert 1 <= result["rateLogs"] <= 20


# ------------------------------------------------------------------ F3 : plafond de journal par génération


async def test_the_per_frame_log_cap_restarts_on_reload(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const b=bench();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      const dropped=()=>b.logs.filter(l=>l.key==='scene.prefab_message_dropped').length;
      for(let i=0;i<8;i++)b.send(s,{jv:2,type:'ready'});
      const first=dropped();
      b.host.reload('obj_1');await flush();b.clock.advance(60);  // l'ancien cadre est parti
      b.send(s,{jv:2,type:'ready'});
      return {first,second:dropped()};
    """, bundles)
    assert result == {"first": 5, "second": 6}


# ------------------------------------------------------------------ F4 : cache des paquets


async def test_the_bundle_cache_is_bounded_and_forgets_an_unusable_bundle(tmp_path, bundles):
    result = run_node(tmp_path, r"""
      const good=D.bundles['test.counter@1'];
      let broken=true;const fetches=[];
      const b=bench({fetchBundle:async(id,v)=>{fetches.push(`${id}@${v}`);
        const copy=JSON.parse(JSON.stringify(good));if(id==='test.broken'&&broken)delete copy.runtime;return copy}});
      for(let i=0;i<80;i++){b.host.mount(b.slot(),instance('obj_'+i,{prefab:{id:'test.p'+i,version:1}}));await flush(2)}
      const size=b.host.stats().bundles;
      const s=b.slot();
      b.host.mount(s,instance('obj_b',{prefab:{id:'test.broken',version:1}}));await flush();
      const band=s.byClass('sc-prefab-error')[0].textContent;
      broken=false;
      s.byClass('sc-prefab-retry')[0].click();await flush();
      return {size,band,refetched:fetches.filter(f=>f==='test.broken@1').length,state:b.host.state('obj_b'),
              cap:H.BUNDLE_CACHE_CAP};
    """, bundles)
    assert result["cap"] == 64 and result["size"] == 64
    assert "bundle has no runtime" in result["band"]
    assert result["refetched"] == 2 and result["state"] == "loading"


# ------------------------------------------------------------------ F5 : open_url


def test_open_url_from_a_frame_refuses_local_and_private_hosts(tmp_path):
    urls = {
        "refused": ["http://127.0.0.1:17654/api/scene", "http://127.1/", "http://2130706433/", "http://0x7f.0.0.1/",
                    "http://localhost:8080/", "http://LocalHost./", "http://api.localhost/", "http://[::1]/",
                    "http://[::ffff:127.0.0.1]/", "http://[::ffff:10.0.0.1]/", "http://[fe80::1]/", "http://[fd00::1]/",
                    "http://[::]/", "http://0.0.0.0/", "http://0/", "http://10.1.2.3/", "http://172.16.0.1/",
                    "http://172.31.255.255/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data"],
        "allowed": ["https://example.com/", "http://172.15.0.1/", "http://172.32.0.1/", "http://11.0.0.1/",
                    "http://192.169.0.1/", "https://[2606:4700::1111]/", "https://localhost.example.com/"],
    }
    result = run_node(tmp_path, r"""
      return {refused:D.refused.map(u=>[u,P.isAllowedUrl(u)]),allowed:D.allowed.map(u=>[u,P.isAllowedUrl(u)]),
              scene:Lay.linkOf('http://127.0.0.1:17654/x')!==null,
              parsed:P.parseFrameMessage({jv:1,type:'open_url',url:'http://192.168.1.1/'}).reason};
    """, urls)
    assert [u for u, ok in result["refused"] if ok] == []
    assert [u for u, ok in result["allowed"] if not ok] == []
    # La règle des liens de la scène, elle, ne change pas.
    assert result["scene"] is True and result["parsed"] == "url refused"
