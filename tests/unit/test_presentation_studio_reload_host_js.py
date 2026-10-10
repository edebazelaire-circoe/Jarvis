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


# ------------------------------------------------------------------ remplacement a cote (hot swap)

def _swap(tmp_path, bundles, body):
    bundles = {"bundles": {**bundles["bundles"],
                           "test.counter@2": {**bundles["bundles"]["test.counter@1"], "version": 2},
                           "test.counter@3": {**bundles["bundles"]["test.counter@1"], "version": 3}}}
    return _node(tmp_path, r"""
      const resizes=[];
      const b=mk({swapPrefix:'test.',onResize:(id,h)=>resizes.push([id,h])});
      const iframes=(s)=>s.children.filter(n=>n.tagName==='IFRAME');
      const live=async(s)=>{b.host.mount(s,instance('obj_1'));await flush();b.send(s,{jv:1,type:'ready'});b.c.advance(300);return iframes(s)[0]};
    """ + body, bundles)


async def test_a_swap_loads_the_new_version_beside_the_live_frame_and_replaces_it_only_once_mounted(tmp_path, bundles):
    result = _swap(tmp_path, bundles, r"""
      const s=b.slot();
      const old=await live(s);
      outcomes.length=0;
      const staged=b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:2}}));await flush();
      const during=iframes(s);
      const stagedFrame=during[1];
      const beside={staged,count:during.length,oldIsLive:during[0]===old,hiddenClass:stagedFrame.className.includes('sc-prefab-staged'),
        key:b.host.key('obj_1'),pending:b.host.pendingKey('obj_1'),state:b.host.state('obj_1'),stats:b.host.stats().staging,
        oldPosted:old.contentWindow.posted.map(p=>p.message.type)};
      // the staged frame becomes ready and sends a resize, an event and a link: none of them counts before it replaces the live one
      b.win.dispatch({source:stagedFrame.contentWindow,origin:'null',data:{jv:1,type:'ready'}});
      b.win.dispatch({source:stagedFrame.contentWindow,origin:'null',data:{jv:1,type:'event',name:'incremented',payload:{count:1}}});
      b.win.dispatch({source:stagedFrame.contentWindow,origin:'null',data:{jv:1,type:'open_url',url:'https://example.com/'}});
      b.win.dispatch({source:stagedFrame.contentWindow,origin:'null',data:{jv:1,type:'resize',height:90}});
      const beforeSettle={outcomes:outcomes.length,resizes:resizes.length,opened:b.win.opened.length,
        dropped:b.logs.filter(l=>l.key==='scene.prefab_message_dropped').length,live:b.host.key('obj_1')};
      b.c.advance(H.SETTLE_MS);
      const swapped={frames:b.host.stats().frames,key:b.host.key('obj_1'),pending:b.host.pendingKey('obj_1'),
        outcomes:outcomes.map(o=>[o.prefab.version,o.outcome]),resizes:resizes.slice(),oldHidden:old.style.visibility,
        oldTeardown:old.contentWindow.posted.map(p=>p.message.type).includes('teardown'),
        newVisible:!stagedFrame.className.includes('sc-prefab-staged'),counters:b.host.counters('obj_1'),
        logs:b.logs.filter(l=>l.key==='scene.prefab_swapped').length};
      b.c.advance(60);
      return {beside,beforeSettle,swapped,final:iframes(s).length,departing:b.host.stats().departing,timers:b.c.timers.length,
              sandbox:iframes(s)[0].getAttribute('sandbox')};
    """)
    assert result["beside"] == {"staged": True, "count": 2, "oldIsLive": True, "hiddenClass": True, "key": "test.counter@1",
                                "pending": "test.counter@2", "state": "ready", "stats": 1, "oldPosted": ["init"]}
    # nothing the staged frame says counts yet: no outcome, no window resize, no link; the event and the link are refused and counted
    assert result["beforeSettle"] == {"outcomes": 0, "resizes": 0, "opened": 0, "dropped": 2, "live": "test.counter@1"}
    swapped = result["swapped"]
    assert swapped["frames"] == 1 and swapped["key"] == "test.counter@2" and swapped["pending"] is None
    assert swapped["outcomes"] == [[2, "mounted"]] and swapped["resizes"] == [["obj_1", 90]]
    assert swapped["oldHidden"] == "hidden" and swapped["oldTeardown"] is True and swapped["newVisible"] is True
    assert swapped["counters"] == {"starts": 2, "mounted": 2, "failed": 0, "remounts": 1} and swapped["logs"] == 1
    assert result["final"] == 1 and result["departing"] == 0 and result["timers"] == 0 and result["sandbox"] == "allow-scripts"


async def test_a_new_version_that_fails_to_mount_leaves_the_live_frame_untouched_and_is_reported(tmp_path, bundles):
    result = _swap(tmp_path, bundles, r"""
      const s=b.slot();
      const old=await live(s);
      outcomes.length=0;
      const postedBefore=old.contentWindow.posted.length;
      b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:2}}));await flush();
      const stagedFrame=iframes(s)[1];
      b.win.dispatch({source:stagedFrame.contentWindow,origin:'null',data:{jv:1,type:'error',message:'SyntaxError: Unexpected token'}});
      const failed={outcomes:outcomes.map(o=>[o.prefab.version,o.outcome,o.reason,o.message]),pending:b.host.pendingKey('obj_1'),
        key:b.host.key('obj_1'),state:b.host.state('obj_1'),bands:s.byClass('sc-prefab-error').length,notes:s.byClass('sc-prefab-note').length,
        staging:b.host.stats().staging};
      b.c.advance(60);
      const afterFailure={frames:iframes(s).length,sameFrame:iframes(s)[0]===old,oldPosted:old.contentWindow.posted.length-postedBefore,
        stagedGone:stagedFrame.parentNode===null};
      // Core rolls the pin back to the live version: nothing is mounted, nothing is remounted
      const back=b.host.mount(s,instance('obj_1'));await flush();
      return {failed,afterFailure,back,frames:iframes(s).length,counters:b.host.counters('obj_1'),stats:b.host.stats()};
    """)
    assert result["failed"] == {"outcomes": [[2, "failed", "frame", "SyntaxError: Unexpected token"]], "pending": None,
                                "key": "test.counter@1", "state": "ready", "bands": 0, "notes": 0, "staging": 0}
    assert result["afterFailure"] == {"frames": 1, "sameFrame": True, "oldPosted": 0, "stagedGone": True}
    assert result["back"] is False and result["frames"] == 1
    assert result["counters"] == {"starts": 2, "mounted": 1, "failed": 1, "remounts": 0}
    assert result["stats"]["errorFrames"] == 0 and result["stats"]["departing"] == 0


async def test_a_staged_frame_that_never_becomes_ready_times_out_beside_the_live_one(tmp_path, bundles):
    result = _swap(tmp_path, bundles, r"""
      const s=b.slot();
      const old=await live(s);
      outcomes.length=0;
      b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:2}}));await flush();
      b.c.advance(H.READY_TIMEOUT_MS);
      b.c.advance(60);
      return {outcomes:outcomes.map(o=>[o.outcome,o.reason]),frames:iframes(s).length,sameFrame:iframes(s)[0]===old,state:b.host.state('obj_1'),
              bands:s.byClass('sc-prefab-error').length};
    """)
    assert result == {"outcomes": [["failed", "timeout"]], "frames": 1, "sameFrame": True, "state": "ready", "bands": 0}


async def test_a_pin_that_comes_back_before_the_staged_frame_settles_abandons_it_without_a_report(tmp_path, bundles):
    result = _swap(tmp_path, bundles, r"""
      const s=b.slot();
      const old=await live(s);
      outcomes.length=0;
      b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:2}}));await flush();
      const stagedFrame=iframes(s)[1];
      b.win.dispatch({source:stagedFrame.contentWindow,origin:'null',data:{jv:1,type:'ready'}});
      b.host.mount(s,instance('obj_1'));            // back to version 1 while version 2 was settling
      b.c.advance(5000);
      return {outcomes:outcomes.length,frames:iframes(s).length,sameFrame:iframes(s)[0]===old,key:b.host.key('obj_1'),
              timers:b.c.timers.length,staging:b.host.stats().staging};
    """)
    assert result == {"outcomes": 0, "frames": 1, "sameFrame": True, "key": "test.counter@1", "timers": 0, "staging": 0}


async def test_a_newer_version_replaces_a_staged_attempt_and_only_the_latest_can_win(tmp_path, bundles):
    result = _swap(tmp_path, bundles, r"""
      const s=b.slot();
      const old=await live(s);
      outcomes.length=0;
      b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:2}}));await flush();
      const second=iframes(s)[1];
      b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:3}}));await flush();
      b.c.advance(60);
      const third=iframes(s).filter(f=>f!==old)[0];
      b.win.dispatch({source:third.contentWindow,origin:'null',data:{jv:1,type:'ready'}});
      b.win.dispatch({source:second.contentWindow,origin:'null',data:{jv:1,type:'ready'}});   // the abandoned attempt is ignored
      b.c.advance(H.SETTLE_MS);
      b.c.advance(60);
      return {outcomes:outcomes.map(o=>[o.prefab.version,o.outcome]),key:b.host.key('obj_1'),frames:iframes(s).length,
              secondGone:second.parentNode===null};
    """)
    assert result == {"outcomes": [[3, "mounted"]], "key": "test.counter@3", "frames": 1, "secondGone": True}


async def test_updates_reach_the_staged_frame_too_so_it_starts_from_the_latest_values(tmp_path, bundles):
    result = _swap(tmp_path, bundles, r"""
      const s=b.slot();
      const old=await live(s);
      b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:2}}));await flush();
      const staged=iframes(s)[1];
      b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:2},data:{count:41,notes:'n'}}));
      b.win.dispatch({source:staged.contentWindow,origin:'null',data:{jv:1,type:'ready'}});
      const init=staged.contentWindow.posted.map(p=>p.message).find(m=>m.type==='init');
      const oldUpdate=old.contentWindow.posted.map(p=>p.message).filter(m=>m.type==='update').pop();
      return {initData:init.data,oldData:oldUpdate&&oldUpdate.data};
    """)
    assert result["initData"]["count"] == 41 and result["oldData"]["count"] == 41


async def test_outside_the_studio_namespace_a_version_change_still_remounts_immediately(tmp_path, bundles):
    data = {"bundles": {**bundles["bundles"], "test.counter@2": {**bundles["bundles"]["test.counter@1"], "version": 2}}}
    result = _node(tmp_path, r"""
      const b=mk({swapPrefix:'presentation-studio.'});const s=b.slot();
      b.host.mount(s,instance('obj_1'));await flush();b.send(s,{jv:1,type:'ready'});b.c.advance(300);
      const first=s.children.filter(n=>n.tagName==='IFRAME')[0];
      b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:2}}));await flush();
      return {staging:b.host.stats().staging,key:b.host.key('obj_1'),pending:b.host.pendingKey('obj_1'),
              oldDeparted:first.contentWindow.posted.map(p=>p.message.type).includes('teardown')};
    """, data)
    assert result == {"staging": 0, "key": "test.counter@2", "pending": None, "oldDeparted": True}


async def test_an_unmount_or_a_pause_during_a_swap_leaves_nothing_behind(tmp_path, bundles):
    result = _swap(tmp_path, bundles, r"""
      const s=b.slot();
      const old=await live(s);
      b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:2}}));await flush();
      b.host.unmount('obj_1');b.c.advance(5000);
      const unmounted={frames:b.host.stats().frames,iframes:iframes(s).length,timers:b.c.timers.length,listeners:b.win.count('message')};
      const s2=b.slot();
      await live(s2);
      b.host.mount(s2,instance('obj_1',{prefab:{id:'test.counter',version:3}}));await flush();
      b.host.pause('obj_1');b.c.advance(5000);
      return {unmounted,paused:{state:b.host.state('obj_1'),staging:b.host.stats().staging,iframes:iframes(s2).length,timers:b.c.timers.length}};
    """)
    assert result["unmounted"] == {"frames": 0, "iframes": 0, "timers": 0, "listeners": 0}
    assert result["paused"] == {"state": "paused", "staging": 0, "iframes": 0, "timers": 0}


async def test_two_hundred_swaps_leave_one_frame_and_no_timer_listener_or_staged_leftover(tmp_path, bundles):
    result = _node(tmp_path, r"""
      const b=mk({swapPrefix:'test.'});const s=b.slot();
      const iframes=()=>s.children.filter(n=>n.tagName==='IFRAME');
      b.host.mount(s,instance('obj_1'));await flush();b.send(s,{jv:1,type:'ready'});b.c.advance(300);
      outcomes.length=0;
      let good=1;
      for(let v=2;v<=201;v++){
        D.bundles[`test.counter@${v}`]=Object.assign({},D.bundles['test.counter@1'],{version:v});
        b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:v}}));await flush(2);
        const staged=iframes().filter(f=>f.className.includes('sc-prefab-staged'))[0];
        if(v%3===0){       // every third version throws at mount
          b.win.dispatch({source:staged.contentWindow,origin:'null',data:{jv:1,type:'ready'}});
          b.win.dispatch({source:staged.contentWindow,origin:'null',data:{jv:1,type:'error',message:'boom'}});
          b.host.mount(s,instance('obj_1',{prefab:{id:'test.counter',version:good}}));   // Core rolls the pin back
        }else{
          b.win.dispatch({source:staged.contentWindow,origin:'null',data:{jv:1,type:'ready'}});
          good=v;
        }
        b.c.advance(300);b.c.advance(60);
        if(b.host.key('obj_1')!==`test.counter@${good}`)throw new Error('live frame is '+b.host.key('obj_1')+' at '+v);
      }
      b.c.advance(1000);
      return {stats:b.host.stats(),counters:b.host.counters('obj_1'),iframes:iframes().length,listeners:b.win.count('message'),
              timers:b.c.timers.length,outcomes:{mounted:outcomes.filter(o=>o.outcome==='mounted').length,failed:outcomes.filter(o=>o.outcome==='failed').length}};
    """, bundles)
    stats = result["stats"]
    assert (stats["frames"], stats["staging"], stats["departing"], stats["errorFrames"]) == (1, 0, 0, 0)
    assert stats["bundles"] <= 64 and result["iframes"] == 1 and result["listeners"] == 1 and result["timers"] == 0
    assert result["outcomes"] == {"mounted": 133, "failed": 67}
    assert result["counters"]["starts"] == 201 and result["counters"]["mounted"] == 134 and result["counters"]["failed"] == 67


# ------------------------------------------------------------------ Slice 14 : a Remotion scene is mounted when it RENDERED

REMOTION_BUNDLE = {"bundles": {"lab.remotion@1": {"kind": "remotion", "id": "lab.remotion", "version": 1, "title": "Scene"}}}


def _remotion(tmp_path, body):
    return run_node(tmp_path, r"""
      const outcomes=[];
      const c=clock(),doc=new FakeDocument(),win=new FakeWindow(),logs=[];
      const host=H.createPrefabHost({document:doc,window:win,now:c.now,setTimeout:c.setTimeout,clearTimeout:c.clearTimeout,
        log:(k,d)=>logs.push({key:k,data:d}),onOutcome:(o)=>outcomes.push(o),
        fetchBundle:(id,v)=>Promise.resolve(JSON.parse(JSON.stringify(D.bundles[`${id}@${v}`])))});
      const s=doc.createElement('div');doc.body.appendChild(s);
      const frameOf=()=>s.children.filter(n=>n.tagName==='IFRAME').pop();
      const status=(phase,extra)=>win.dispatch({source:frameOf().contentWindow,origin:win.location&&win.location.origin,
        data:Object.assign({rsh:1,type:'status',phase},extra||{})});
      const clockMsg=()=>win.dispatch({source:frameOf().contentWindow,origin:win.location&&win.location.origin,
        data:{rsh:1,type:'clock',frame:0,playing:true,duration:90,fps:30}});
      host.mount(s,instance('obj_1',{prefab:{id:'lab.remotion',version:1}}));await flush();
    """ + body, REMOTION_BUNDLE)


async def test_a_remotion_scene_is_mounted_only_after_its_player_rendered_a_first_frame(tmp_path):
    result = _remotion(tmp_path, r"""
      status('ready');
      c.advance(H.SETTLE_MS+50);const readyOnly=outcomes.length;      // sandbox loaded, nothing rendered yet: not mounted
      clockMsg();c.advance(H.SETTLE_MS-1);const justBefore=outcomes.length;
      c.advance(1);
      return {readyOnly,justBefore,outcomes:outcomes.map(o=>o.outcome)};
    """)
    assert (result["readyOnly"], result["justBefore"], result["outcomes"]) == (0, 0, ["mounted"])


async def test_a_remotion_scene_that_throws_at_render_is_a_failed_outcome_not_a_mounted_one(tmp_path):
    result = _remotion(tmp_path, r"""
      status('ready');
      status('scene_error',{message:'Error: boom at render'});      // the sandbox boundary reports BEFORE the first clock
      clockMsg();c.advance(5000);
      return {outcomes:outcomes.map(o=>[o.outcome,o.reason,o.message])};
    """)
    assert result["outcomes"] == [["failed", "frame", "Error: boom at render"]]


async def test_a_remotion_scene_that_never_renders_fails_after_the_proof_delay_instead_of_waiting_forever(tmp_path):
    result = _remotion(tmp_path, r"""
      status('ready');
      c.advance(9999);const before=outcomes.length;
      c.advance(2);
      return {before,outcomes:outcomes.map(o=>[o.outcome,o.reason]),message:outcomes[0]&&outcomes[0].message};
    """)
    assert result["before"] == 0 and result["outcomes"] == [["failed", "timeout"]] and "first frame" in result["message"]


async def test_a_staged_remotion_frame_receives_the_windows_current_values_when_its_page_is_up(tmp_path):
    """Slice 14: the hot reload patches the window with the values to keep (live preview values included); the new page of the scene gets
    exactly those, from the host, when it says `shell` (before any render): nothing the user was previewing is lost by the swap."""

    result = _remotion(tmp_path, r"""
      status('shell');
      const sent=frameOf().contentWindow.posted.map(p=>p.message).filter(m=>m.type==='props');
      return {sent};
    """)
    assert [m["props"] for m in result["sent"]] == [{"label": "Count"}] and result["sent"][0]["data"] == {"count": 3, "notes": "**bold** note"}
