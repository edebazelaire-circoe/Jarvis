"""One exact-baseline natural rail-occlusion witness, not the original test."""
from datetime import datetime,timezone
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

qa=Path(__file__).parent.resolve();baseline=qa.parents[4].parent/'movb'
sys.path.insert(0,str(baseline))
output=qa/'graph-baseline-occlusion-witness.json'
manifest=qa/'graph-baseline-occlusion-witness-run.json'
if manifest.exists():raise SystemExit('Refusing to repeat the allocated witness.')
revision=subprocess.check_output(['git','-C',str(baseline),'rev-parse','HEAD'],text=True).strip()
assert revision=='c0858a8000e2ca23b57231edb8f46c643080ad07'
from tests.unit import test_status_centre_browser as driver
from tests.unit import test_scene_task_graph_browser as graph
from graph_minimal_capture_plugin import instrument_harness
assert Path(driver.__file__).resolve().is_relative_to(baseline)
assert Path(graph.__file__).resolve().is_relative_to(baseline)
scratch=Path(tempfile.mkdtemp(prefix='jarvis-mov-baseline-occlusion-'))
copied=scratch/'baseline-occlusion-harness.mjs'
source_hash=instrument_harness(driver,copied)
record={'revision':revision,'started_at':datetime.now(timezone.utc).isoformat(),
 'runner_pid':os.getpid(),'scratch':str(scratch),'driver_source':driver.__file__,
 'graph_source':graph.__file__,'original_harness_sha256':source_hash,
 'condition_budget_ms':245000,'qa_node_ceiling_ms':300000,
 'one_native_click':True,'original_test_baseline_failure_claim':False}
old=driver.HARNESS;driver.HARNESS=copied
predicate=r"""(async()=>{
  const start=performance.now(),deadline=start+245000;
  while(performance.now()<deadline){
    const mark=document.querySelector('.sc-relmark[data-relation-id="rel_comm"]');
    if(mark){const r=mark.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2,hit=document.elementFromPoint(x,y);
      if(hit?.closest('#presentationRail')){return {reached:true,waitedMs:performance.now()-start,wallTime:Date.now(),x,y,
        target:{tag:hit.tagName,id:hit.id,cls:typeof hit.className==='string'?hit.className:''},
        markRect:JSON.parse(JSON.stringify(r)),railRect:JSON.parse(JSON.stringify(document.getElementById('presentationRail').getBoundingClientRect()))};}}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  return {reached:false,waitedMs:performance.now()-start,wallTime:Date.now()};
})()"""
# Reuse the same mouse helper unchanged. Its original action catches an
# absent selector; an added conditional action gate only prevents any click
# when the natural predicate timed out. It does not retry or move a target.
source=copied.read_text(encoding='utf-8')
needle="else if(kind==='click'){await mouse(arg,'left');results[name]='ok'}"
if needle not in source:
    # The original driver dispatches this exact first branch as `if`.
    needle="if(kind==='click'){await mouse(arg,'left');results[name]='ok'}"
assert source.count(needle)==1
prefix='else if' if needle.startswith('else') else 'if'
source=source.replace(needle,prefix+"(kind==='click'){if(results.naturalCondition?.reached){await mouse(arg,'left');results[name]='ok'}else results[name]='skipped:condition_timeout'}")
# Local observational ceiling only. Canonical profile-bound disposal still runs
# on exit, including expiry; no shared/CDP/Core/product deadline is changed.
needle='disposeChromeOnExit(chrome,profile);'
assert source.count(needle)==1
source=source.replace(needle,needle+"\nsetTimeout(()=>{process.stderr.write('QA observation ceiling 300000ms exceeded\\n');process.exit(124)},300000).unref();")
copied.write_text(source,encoding='utf-8')
subprocess.run(['node','--check',str(copied)],check=True,capture_output=True,text=True)
record['copied_harness_sha256']=hashlib.sha256(copied.read_bytes()).hexdigest()
imports={name:Path(module.__file__).resolve() for name,module in list(sys.modules.items())
         if (name=='jarvis' or name.startswith('jarvis.') or name.startswith('tests.unit.'))
         and getattr(module,'__file__',None)}
assert all(path.is_relative_to(baseline) for path in imports.values()),imports
record['baseline_imports']={name:{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                            for name,path in imports.items()}
original_served=driver._served_page
def retain_served(root):
    page=original_served(root)
    record['served_page']={'path':str(page),'sha256':hashlib.sha256(page.read_bytes()).hexdigest(),
                           'runtime':str(sys.modules['tests.unit.test_boards_card_browser'].RUNTIME)}
    assert Path(record['served_page']['runtime']).resolve().is_relative_to(baseline)
    manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    return page
driver._served_page=retain_served
manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
try:
    result=driver._drive(scratch,[{'width':720,'height':450,'scale':2,'seed':graph._seed(dense=30),'actions':[
        ['eval','initial',graph.READ,50],
        ['shot','before',str(qa/'graph-baseline-occlusion-before.png'),1],
        ['eval','naturalCondition',predicate,1],
        ['click','oneClick','.sc-relmark[data-relation-id="rel_comm"]',100],
        ['eval','waitBoard',graph.WAIT_BOARD,50],['eval','board',graph.BOARD,50],
        ['shot','after',str(qa/'graph-baseline-occlusion-after.png'),50],
    ]}])
    output.write_text(json.dumps({'record':record,'result':result},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    record['condition']=result[0]['results'].get('naturalCondition')
    record['board_open']=bool(result[0]['results'].get('board') and result[0]['results']['board'].get('open'))
    record['click']=result[0]['results'].get('oneClick')
finally:
    driver.HARNESS=old
    driver._served_page=original_served
    record['ended_at']=datetime.now(timezone.utc).isoformat()
    manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps({key:value for key,value in record.items() if key!='baseline_imports'},ensure_ascii=False),flush=True)
