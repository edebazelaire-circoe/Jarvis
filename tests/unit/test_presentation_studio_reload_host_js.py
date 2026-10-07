"""Ce que l'hote des cadres rapporte pour le rechargement a chaud (jarvis-interactive-presentation-studio, Slice 06).

`createPrefabHost` par node (faux DOM, horloge manuelle, paquets du vrai catalogue). Prouve : UN rapport par generation
(`mounted` seulement apres la stabilisation, `failed` a la premiere erreur, quelle qu'en soit l'origine), des compteurs par
objet qui survivent a un remontage de version, aucune fuite apres des rechargements repetes, et que ni le bac a sable ni
le protocole `jv:1` n'ont bouge. La preuve dans un vrai Chrome est `test_presentation_studio_reload_browser.py`.
"""

from __future__ import annotations

import pytest

from tests.fakes.prefab_js import catalogue_bundles, run_node

@pytest.fixture
async def bundles(tmp_path):
    return {"bundles": await catalogue_bundles(tmp_path, "test.counter")}


def _node(tmp_path, body, data):
    return run_node(tmp_path, r"""
      const outcomes=[];
      const mk=(extra)=>{
        const doc=new FakeDocument(),win=new FakeWindow(),c=clock(),logs=[];
        const host=H.createPrefabHost(Object.assign({document:doc,window:win,now:c.now,setTimeout:c.setTimeout,clearTimeout:c.clearTimeout,
          log:(k,d)=>logs.push({key:k,data:d}),onOutcome:(o)=>outcomes.push(o),
          fetchBundle:(id,v)=>{const b=D.bundles[`${id}@${v}`];return b?Promise.resolve(JSON.parse(JSON.stringify(b))):Promise.reject(new Error(`unknown_prefab: no prefab ${id}`))}},extra||{}));
        const slot=()=>{const s=doc.createElement('div');doc.body.appendChild(s);return s};
        const frameOf=(s)=>s.children.filter(n=>n.tagName==='IFRAME').pop()||null;   // the newest: an old one may still be departing
        const send=(s,data,origin)=>win.dispatch({source:frameOf(s).contentWindow,origin:origin===undefined?'null':origin,data});
        return {host,doc,win,c,logs,slot,frameOf,send};
      };
    """ + body, data)


async def test_a_frame_is_mounted_only_once_it_stayed_ready_and_quiet_for_the_settle_time(tmp_path, bundles):
    result = _node(tmp_path, r"""
      const b=mk();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'ready'});
      const atReady=outcomes.length;
      b.c.advance(H.SETTLE_MS-1);const justBefore=outcomes.length;
      b.c.advance(1);
      b.c.advance(5000);   // nothing more, whatever the time
      b.send(s,{jv:1,type:'resize',height:80});
      return {atReady,justBefore,outcomes,counters:b.host.counters('obj_1'),stats:b.host.stats(),settle:H.SETTLE_MS};
    """, bundles)
    assert (result["atReady"], result["justBefore"], result["settle"]) == (0, 0, 250)
    assert result["outcomes"] == [{"object_id": "obj_1", "prefab": {"id": "test.counter", "version": 1}, "outcome": "mounted",
                                   "reason": "", "message": "", "generation": 1,
                                   "counters": {"starts": 1, "mounted": 1, "failed": 0, "remounts": 0}}]
    assert result["counters"] == {"starts": 1, "mounted": 1, "failed": 0, "remounts": 0}
    assert (result["stats"]["starts"], result["stats"]["mounted"], result["stats"]["failed"]) == (1, 1, 0)


async def test_an_error_thrown_by_the_first_render_after_ready_means_failed_not_mounted(tmp_path, bundles):
    result = _node(tmp_path, r"""
      const b=mk();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'ready'});
      b.c.advance(100);
      b.send(s,{jv:1,type:'error',message:"TypeError: Cannot read properties of undefined (reading 'x')"});
      b.c.advance(5000);
      return {outcomes,band:s.byClass('sc-prefab-error')[0].textContent};
    """, bundles)
    assert [(o["outcome"], o["reason"]) for o in result["outcomes"]] == [("failed", "frame")]
    assert "TypeError" in result["outcomes"][0]["message"] and "TypeError" in result["band"]


async def test_an_error_before_ready_is_the_outcome_and_a_late_ready_does_not_make_a_second_one(tmp_path, bundles):
    result = _node(tmp_path, r"""
      const b=mk();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'error',message:'SyntaxError: Unexpected token'});
      b.send(s,{jv:1,type:'ready'});
      b.c.advance(5000);
      return {outcomes,state:b.host.state('obj_1'),counters:b.host.counters('obj_1')};
    """, bundles)
    assert [(o["outcome"], o["reason"], o["message"]) for o in result["outcomes"]] == [("failed", "frame", "SyntaxError: Unexpected token")]
    assert result["state"] == "error" and result["counters"]["failed"] == 1 and result["counters"]["mounted"] == 0


async def test_a_missing_bundle_a_silent_frame_and_a_navigating_frame_each_fail_once_with_their_reason(tmp_path, bundles):
    result = _node(tmp_path, r"""
      const out={};
      const missing=mk();const s1=missing.slot();
      missing.host.mount(s1,Object.assign(instance('obj_1'),{prefab:{id:'test.gone',version:1}}));await flush(3);
      out.bundle=outcomes.splice(0);
      const silent=mk();const s2=silent.slot();
      silent.host.mount(s2,instance('obj_2'));await flush();
      silent.c.advance(H.READY_TIMEOUT_MS);
      out.timeout=outcomes.splice(0);
      const nav=mk();const s3=nav.slot();
      nav.host.mount(s3,instance('obj_3'));await flush();
      const frame=nav.frameOf(s3);
      nav.send(s3,{jv:1,type:'ready'});
      frame.load();frame.load();
      out.navigation=outcomes.splice(0);
      return out;
    """, bundles)
    assert [(o["outcome"], o["reason"]) for o in result["bundle"]] == [("failed", "bundle")]
    assert [(o["outcome"], o["reason"]) for o in result["timeout"]] == [("failed", "timeout")]
    assert [(o["outcome"], o["reason"]) for o in result["navigation"]] == [("failed", "navigation")]


async def test_a_version_change_remounts_that_frame_and_the_counters_follow_the_object(tmp_path):
    from tests.fakes.prefabs import candidate, install_version
    import json
    package, data = tmp_path / "pkg", tmp_path / "data"
    package.mkdir()
    for version in (1, 2):
        install_version(data / "prefabs", "test.counter", version, source=candidate("test.counter")) if version == 1 else None
    bundles = {"bundles": await catalogue_bundles(tmp_path, "test.counter")}
    bundles["bundles"]["test.counter@2"] = {**bundles["bundles"]["test.counter@1"], "version": 2}
    result = _node(tmp_path, r"""
      const b=mk();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'ready'});b.c.advance(300);
      const first=b.frameOf(s);
      const remount=b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:2}}));await flush();
      b.c.advance(60);   // teardown delay of the departing frame
      const second=b.frameOf(s);
      b.send(s,{jv:1,type:'ready'});b.c.advance(300);
      const sameVersion=b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:2},data:{count:9}}));
      return {remount,sameVersion,swapped:first!==second,frames:s.children.filter(n=>n.tagName==='IFRAME').length,
              outcomes:outcomes.map(o=>[o.prefab.version,o.outcome,o.counters]),counters:b.host.counters('obj_1'),
              writes:[first.srcdocWrites.length,second.srcdocWrites.length]};
    """, bundles)
    assert result["remount"] is True and result["sameVersion"] is False and result["swapped"] and result["frames"] == 1
    assert result["outcomes"] == [[1, "mounted", {"starts": 1, "mounted": 1, "failed": 0, "remounts": 0}],
                                  [2, "mounted", {"starts": 2, "mounted": 2, "failed": 0, "remounts": 1}]]
    assert result["counters"] == {"starts": 2, "mounted": 2, "failed": 0, "remounts": 1} and result["writes"] == [1, 1]


async def test_a_failing_outcome_callback_is_logged_and_never_breaks_the_frame(tmp_path, bundles):
    result = _node(tmp_path, r"""
      const b=mk({onOutcome:()=>{throw new Error('page sink down')}});const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'ready'});b.c.advance(300);
      return {state:b.host.state('obj_1'),logs:b.logs.filter(l=>l.key==='scene.prefab_outcome_failed').map(l=>l.data.error),counters:b.host.counters('obj_1')};
    """, bundles)
    assert result["state"] == "ready" and result["logs"] == ["page sink down"] and result["counters"]["mounted"] == 1


async def test_a_manual_reload_is_a_new_generation_with_its_own_outcome(tmp_path, bundles):
    result = _node(tmp_path, r"""
      const b=mk();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      b.send(s,{jv:1,type:'ready'});b.c.advance(300);
      b.host.reload('obj_1');await flush();b.c.advance(60);
      b.send(s,{jv:1,type:'ready'});b.c.advance(300);
      return {outcomes:outcomes.map(o=>[o.generation,o.outcome]),counters:b.host.counters('obj_1')};
    """, bundles)
    assert result["outcomes"] == [[1, "mounted"], [2, "mounted"]] and result["counters"]["starts"] == 2


async def test_two_hundred_version_reloads_of_one_scene_leave_no_frame_listener_timer_or_cache_entry_behind(tmp_path, bundles):
    result = _node(tmp_path, r"""
      const b=mk();const s=b.slot();
      const versions=[];
      for(let v=1;v<=200;v++){
        D.bundles[`test.counter@${v}`]=Object.assign({},D.bundles['test.counter@1'],{version:v});
        b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:v}}));await flush(2);
        b.send(s,{jv:1,type:'ready'});
        if(v%2===0)b.c.advance(300);else b.c.advance(100);   // half of them are replaced before they settle
        b.c.advance(60);
      }
      b.c.advance(1000);
      const stats=b.host.stats();
      return {stats,counters:b.host.counters('obj_1'),children:s.children.length,
              iframes:s.children.filter(n=>n.tagName==='IFRAME').length,listeners:b.win.count('message'),
              timers:b.c.timers.length,docIframes:b.doc.created.filter(n=>n.tagName==='IFRAME'&&n.parentNode).length,
              outcomes:outcomes.length};
    """, bundles)
    stats = result["stats"]
    assert (stats["frames"], stats["live"], stats["departing"]) == (1, 1, 0)
    assert stats["bundles"] <= 64                                                    # the LRU cap holds
    assert result["iframes"] == 1 and result["listeners"] == 1 and result["timers"] == 0
    assert result["counters"]["starts"] == 200 and result["counters"]["remounts"] == 199
    assert result["counters"]["mounted"] == 100                                       # the half replaced before settling never reported
    assert result["outcomes"] == 100 and result["docIframes"] == 1


async def test_the_sandbox_and_the_protocol_are_exactly_what_they_were(tmp_path, bundles):
    result = _node(tmp_path, r"""
      const b=mk();const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();
      const f=b.frameOf(s);
      const P=require(PATHS.protocol);
      return {sandbox:f.getAttribute('sandbox'),allow:f.getAttribute('allow'),allowfs:f.hasAttribute('allowfullscreen'),
              host:P.HOST_TYPES||null,frame:P.FRAME_TYPES||null,keys:Object.keys(P).sort(),csp:P.CSP};
    """, bundles)
    assert result["sandbox"] == "allow-scripts" and result["allow"] is None and result["allowfs"] is False
    assert result["host"] is None or result["host"] == ["init", "update", "teardown", "event_result"]
    # no new message type for the frame to speak or to hear: no snapshot, no state export, nothing named after the reload
    assert "snapshot" not in " ".join(result["keys"]).lower() and "reload" not in " ".join(result["keys"]).lower()
    assert result["frame"] is None or result["frame"] == ["ready", "event", "resize", "open_url", "error"]
    assert "default-src 'none'" in result["csp"] and "connect" not in result["csp"]
