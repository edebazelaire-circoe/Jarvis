"""One bounded current dense-click prefix, observing a copy of the existing harness."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile

qa=Path(__file__).parent.resolve()
repo=qa.parents[4]
sys.path.insert(0,str(repo))
output=qa/'graph-click-diagnostic.json'
if output.exists():
    raise SystemExit('Refusing to repeat/overwrite this allocated diagnostic.')
from tests.unit import test_status_centre_browser as harness
from tests.unit import test_scene_task_graph_browser as graph

diagnostic=r"""(()=>{
  const P=window.__graphClickProbe={events:[]};
  const who=e=>e?{tag:e.tagName,id:e.id,cls:typeof e.className==='string'?e.className:'',
    relation:e.closest?.('.sc-relmark')?.dataset.relationId||null,object:e.closest?.('.sc-node')?.dataset.objectId||null}:null;
  const rect=e=>e?JSON.parse(JSON.stringify(e.getBoundingClientRect())):null;
  P.record=(phase,x,y,target)=>{
    if(P.events.length>=40)return;
    const mark=document.querySelector('.sc-relmark[data-relation-id="rel_comm"]'),at=document.elementFromPoint(x,y),node=at?.closest('.sc-node');
    const ancestors=[];for(let e=at;e&&ancestors.length<12;e=e.parentElement)ancestors.push(who(e));
    const panels=['#presentationRail','#chatPanel','#panel','#jvStudioInspector','#settingsHub','#overlay'].map(s=>{
      const e=document.querySelector(s);return e?{selector:s,visible:e.checkVisibility(),rect:rect(e),z:getComputedStyle(e).zIndex,pointerEvents:getComputedStyle(e).pointerEvents}:null});
    P.events.push({phase,at:performance.now(),x,y,target:who(target),hit:who(at),markRect:rect(mark),
      ancestors,panels,viewport:{width:innerWidth,height:innerHeight},
      markStyle:mark?{z:getComputedStyle(mark).zIndex,pointerEvents:getComputedStyle(mark).pointerEvents,transform:getComputedStyle(mark).transform}:null,
      nodeStyle:node?{z:getComputedStyle(node).zIndex,rect:rect(node),hover:node.matches(':hover'),focus:node.matches(':focus-within')}:null,
      nodes:document.querySelectorAll('#sceneLayer .sc-node').length,points:document.querySelectorAll('#sceneLayer .sc-node.sc-point').length,
      grips:document.querySelectorAll('#sceneLayer .sc-grip').length,
      viewer:window.JarvisScene?.inspect().viewer||null,
      focus:who(document.activeElement)});
  };
  for(const type of ['pointermove','mousemove','pointerdown','mousedown','pointerup','mouseup','click'])document.addEventListener(type,e=>{
    if(!document.querySelector('.sc-relmark[data-relation-id="rel_comm"]'))return;
    P.record('capture:'+type,e.clientX,e.clientY,e.target);
    queueMicrotask(()=>P.record('after:'+type,e.clientX,e.clientY,e.target));
  },true);
})()"""
source=harness.HARNESS.read_text(encoding='utf-8')
original_hash=hashlib.sha256(source.encode()).hexdigest()
source=source.replace("from './_cdp_profile.mjs'",'from '+json.dumps((repo/'tests/unit/_cdp_profile.mjs').as_uri()))
needle="await send('Page.addScriptToEvaluateOnNewDocument',{source:SERVER});"
assert source.count(needle)==1
source=source.replace(needle,"await send('Page.addScriptToEvaluateOnNewDocument',{source:SERVER+"+json.dumps(';'+chr(10))+"+"+json.dumps(diagnostic)+"});")
needle="const mouse=async(selector,button,modifiers=0,clickCount=1)=>{\n    const {x,y}=await center(selector);\n    await send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y,button:'none',modifiers});"
assert source.count(needle)==1
source=source.replace(needle,"const mouse=async(selector,button,modifiers=0,clickCount=1)=>{\n    const {x,y}=await center(selector);\n    if(typeof selector==='string'&&selector.includes('rel_comm'))await evaluate(`window.__graphClickProbe.record('sample-before-move',${x},${y},document.querySelector(${JSON.stringify(selector)}))`);\n    await send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y,button:'none',modifiers});")
needle="out.push({results,console:consoleLines.filter"
assert source.count(needle)==1
source=source.replace(needle,"out.push({graphClickProbe:await evaluate('window.__graphClickProbe||null'),results,console:consoleLines.filter")
scratch=Path(tempfile.mkdtemp(prefix='jarvis-mov-graph-click-'))
copy=scratch/'graph-click-harness.mjs'
copy.write_text(source,encoding='utf-8')
old=harness.HARNESS
harness.HARNESS=copy
try:
    result=harness._drive(scratch,[{'width':720,'height':450,'scale':2,'seed':graph._seed(dense=30),'actions':[
        ['eval','read',graph.READ,50],['shot','before',str(qa/'graph-click-before.png'),150],
        ['click','open','.sc-relmark[data-relation-id="rel_comm"]',100],
        ['eval','waitBoard',graph.WAIT_BOARD,50],['eval','board',graph.BOARD,50],
        ['shot','after',str(qa/'graph-click-after.png'),150],
    ]}])
finally:
    harness.HARNESS=old
payload={'original_harness_sha256':original_hash,'copied_harness':str(copy),
    'scope':'One current 720x450/scale2 prefix, same seed/center/CDP click/settles; passive early capture plus one sample eval; timing perturbation possible',
    'result':result}
output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'output':str(output),'board':result[0]['results'].get('board'),
    'probe_present':bool(result[0]['graphClickProbe']),
    'events':len((result[0]['graphClickProbe'] or {}).get('events',[]))},ensure_ascii=False),flush=True)
