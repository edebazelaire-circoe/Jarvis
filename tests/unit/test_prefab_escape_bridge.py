"""Escape-only local UI bridge: shape, focused live source, teardown and rate."""
from tests.fakes.prefab_js import catalogue_bundles, run_node
from tests.unit.test_prefab_shim_js import FRAME


def test_protocol_accepts_only_exact_escape_notice(tmp_path):
    out=run_node(tmp_path,"""
      const values=[{jv:1,type:'escape'},{jv:1,type:'escape',key:'Escape'},
        {jv:1,type:'escape',text:'private'},{jv:1,type:'key',key:'Escape'},
        {jv:1,type:'escape',payload:{}},{jv:2,type:'escape'}];
      return values.map(P.parseFrameMessage);
    """)
    assert out[0]=={'ok':True,'message':{'type':'escape'}}
    assert all(not entry['ok'] for entry in out[1:])


def test_shim_only_posts_trusted_plain_escape_after_init_and_removes_listener_on_teardown(tmp_path):
    out=run_node(tmp_path,FRAME+"""
      const f=frame(),send=(fields)=>f.doc.dispatch('keydown',{key:'Escape',isTrusted:true,...fields});
      send({});f.send(INIT);
      send({key:'Enter'});send({key:'e'});send({isTrusted:false});send({repeat:true});
      for(const modifier of ['altKey','ctrlKey','metaKey','shiftKey'])send({[modifier]:true});
      send({});const before=f.msgs.filter(m=>m.type==='escape');
      f.send({jv:1,type:'teardown'});send({});
      return {before,after:f.msgs.filter(m=>m.type==='escape'),listeners:f.doc.listeners.keydown.length};
    """)
    assert out['before']==out['after']==[{'jv':1,'type':'escape'}]
    assert out['listeners']==0


async def test_host_only_delivers_focused_live_escape_and_rate_limits_locally(tmp_path):
    bundles=await catalogue_bundles(tmp_path,'test.counter')
    out=run_node(tmp_path,"""
      const calls=[],b=bench({onEscape:id=>calls.push(id)}),s=b.slot();
      b.host.mount(s,{object_id:'obj',prefab:{id:'test.counter',version:1}});await flush();
      const frame=b.frameOf(s),send=(origin='null',data={jv:1,type:'escape'})=>b.win.dispatch({source:frame.contentWindow,origin,data});
      b.doc.activeElement=frame;send();
      b.send(s,{jv:1,type:'ready'});b.doc.activeElement=null;send();
      b.doc.activeElement=frame;send('https://spoof.test');
      b.win.dispatch({source:{},origin:'null',data:{jv:1,type:'escape'}});
      send('null',{jv:1,type:'escape',key:'Escape'});send('null',{jv:1,type:'key',key:'Escape'});
      send();send();b.clock.advance(1000);send();
      return {calls,posted:b.posted,limited:b.host.stats().rateLimited,normal:b.logs.filter(l=>l.key==='scene.prefab_escape').length};
    """,{'bundles':bundles})
    assert out=={'calls':['obj','obj'],'posted':[],'limited':1,'normal':2}


async def test_old_unmounted_paused_and_staged_frames_cannot_close_viewer(tmp_path):
    bundles=await catalogue_bundles(tmp_path,'test.counter')
    out=run_node(tmp_path,"""
      const calls=[],b=bench({onEscape:id=>calls.push(id),swapPrefix:'test.',fetchBundle:()=>Promise.resolve(D.bundle)}),s=b.slot();
      const instance=version=>({object_id:'obj',prefab:{id:'test.counter',version}});
      const send=frame=>b.win.dispatch({source:frame.contentWindow,origin:'null',data:{jv:1,type:'escape'}});
      b.host.mount(s,instance(1));await flush();const old=b.frameOf(s);b.send(s,{jv:1,type:'ready'});
      b.host.mount(s,instance(2));await flush();
      const staged=s.children.filter(el=>el.tagName==='IFRAME')[1];b.doc.activeElement=staged;
      b.win.dispatch({source:staged.contentWindow,origin:'null',data:{jv:1,type:'ready'}});send(staged);
      b.host.pause('obj');b.doc.activeElement=old;send(old);send(staged);
      b.host.resume('obj');await flush();const active=b.frameOf(s);b.send(s,{jv:1,type:'ready'});b.doc.activeElement=old;send(old);
      b.host.unmount('obj');b.doc.activeElement=active;send(active);
      return {calls,listening:b.win.count('message')};
    """,{'bundle':bundles['test.counter@1']})
    assert out=={'calls':[],'listening':0}


async def test_host_without_callback_ignores_escape_and_callback_failure_is_visible_and_logged(tmp_path):
    bundles=await catalogue_bundles(tmp_path,'test.counter')
    out=run_node(tmp_path,"""
      const a=bench(),s=a.slot();a.host.mount(s,{object_id:'obj',prefab:{id:'test.counter',version:1}});await flush();a.send(s,{jv:1,type:'ready'});a.doc.activeElement=a.frameOf(s);a.send(s,{jv:1,type:'escape'});
      const b=bench({onEscape:()=>{throw new Error('fixture close failed')}}),t=b.slot();b.host.mount(t,{object_id:'obj',prefab:{id:'test.counter',version:1}});await flush();b.send(t,{jv:1,type:'ready'});b.doc.activeElement=b.frameOf(t);b.send(t,{jv:1,type:'escape'});
      return {ignored:a.host.state('obj'),ignoredLog:a.logs.some(l=>l.key==='scene.prefab_escape'),
        visible:t.textContent,logged:b.logs.some(l=>l.key==='scene.prefab_error'&&l.data.reason==='escape')};
    """,{'bundles':bundles})
    assert out['ignored']=='ready' and not out['ignoredLog']
    assert 'fixture close failed' in out['visible'] and out['logged']
