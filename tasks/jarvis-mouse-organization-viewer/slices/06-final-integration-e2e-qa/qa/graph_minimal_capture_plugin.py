"""Retain exact graph test output; observe within existing CDP evaluate calls."""
import hashlib
import json
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def graph_minimal_capture(request,monkeypatch,tmp_path):
    if request.node.name!='test_a_dense_graph_at_200_percent_and_in_forced_colours_stays_usable':
        yield
        return
    from tests.unit import test_status_centre_browser as driver
    repo=Path(driver.__file__).resolve().parents[2]
    source=driver.HARNESS.read_text(encoding='utf-8')
    original_hash=hashlib.sha256(source.encode()).hexdigest()
    source=source.replace("from './_cdp_profile.mjs'",'from '+json.dumps((repo/'tests/unit/_cdp_profile.mjs').as_uri()))
    needle="const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);"
    replacement=r"""const r=el.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;
      if(el.matches('.sc-relmark[data-relation-id="rel_comm"]')){
        const who=e=>e?{tag:e.tagName,id:e.id,cls:typeof e.className==='string'?e.className:'',relation:e.closest?.('.sc-relmark')?.dataset.relationId||null,object:e.closest?.('.sc-node')?.dataset.objectId||null}:null;
        const rect=e=>e?JSON.parse(JSON.stringify(e.getBoundingClientRect())):null;
        const record=(phase,px,py,target)=>{const mark=document.querySelector('.sc-relmark[data-relation-id="rel_comm"]'),hit=document.elementFromPoint(px,py),rail=document.getElementById('presentationRail');
          const ancestors=[];for(let p=hit;p&&ancestors.length<10;p=p.parentElement)ancestors.push(who(p));
          const node=hit?.closest('.sc-node');
          return {phase,wallTime:Date.now(),at:performance.now(),x:px,y:py,target:who(target),hit:who(hit),ancestors,
            markRect:rect(mark),viewport:{width:innerWidth,height:innerHeight},
            rail:rail?{rect:rect(rail),visible:rail.checkVisibility(),z:getComputedStyle(rail).zIndex}:null,
            node:node?{rect:rect(node),z:getComputedStyle(node).zIndex,hover:node.matches(':hover'),focus:node.matches(':focus-within')}:null,
            nodes:document.querySelectorAll('#sceneLayer .sc-node').length,points:document.querySelectorAll('#sceneLayer .sc-node.sc-point').length,
            grips:document.querySelectorAll('#sceneLayer .sc-grip').length,viewer:window.JarvisScene?.inspect().viewer||null};};
        const d=window.__graphMinimal||(window.__graphMinimal={sample:null,events:[]});d.sample=record('center',x,y,el);
        if(!d.installed){d.installed=true;for(const type of ['pointermove','mousemove','pointerdown','mousedown','pointerup','mouseup','click'])document.addEventListener(type,event=>{
          if(d.events.length<20)d.events.push(record(type,event.clientX,event.clientY,event.target));
        },true);}
      }
      return {x,y}})()`);"""
    assert source.count(needle)==1
    source=source.replace(needle,replacement)
    needle="acks:window.__sc.acks})`);"
    assert source.count(needle)==1
    source=source.replace(needle,"acks:window.__sc.acks,graphMinimal:window.__graphMinimal||null})`);")
    copied=tmp_path/'graph-minimal-harness.mjs'
    copied.write_text(source,encoding='utf-8')
    destination=Path(os.environ['JARVIS_GRAPH_MINIMAL_RAW'])
    metadata=destination.with_suffix('.metadata.json')
    original_run=driver.subprocess.run
    def retain(args,*positional,**kwargs):
        done=original_run(args,*positional,**kwargs)
        if isinstance(args,list) and len(args)>1 and str(args[1])==str(copied):
            destination.write_text(done.stdout,encoding='utf-8')
            metadata.write_text(json.dumps({'original_harness_sha256':original_hash,'copied_harness':str(copied),
                'node_returncode':done.returncode,'stderr':done.stderr,
                'extra_cdp_calls':0,'event_sequence_changed':False,'test_assertions_changed':False,
                'scope':'Observation in existing center evaluate and final server read only; no freeze/DOM mutation/retried click'},indent=2)+'\n',encoding='utf-8')
        return done
    monkeypatch.setattr(driver,'HARNESS',copied)
    monkeypatch.setattr(driver.subprocess,'run',retain)
    yield
