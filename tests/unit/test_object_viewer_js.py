"""Pure viewer layout and canonical resource boundary."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

MODULE=Path(__file__).parents[2]/'jarvis/runtime/control_center_object_viewer.js'


def node(code):
    binary=shutil.which('node')
    if not binary:
        pytest.skip('node absent')
    result=subprocess.run([binary,'-e',f'const V=require({json.dumps(str(MODULE))});\n'+code],capture_output=True,text=True,encoding='utf-8',timeout=20)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_all_layouts_bound_capacity_without_losing_entries():
    rows=node("process.stdout.write(JSON.stringify(Object.keys(V.LAYOUTS).map(name=>V.layoutPlan(24,name,{rows:3,cols:8,width:1280}))));")
    assert len(rows)==10
    assert {row['name'] for row in rows}=={'single','horizontal','vertical','quad','row','column','auto','custom','largeLeft','largeTop'}
    for row in rows:
        assert row['rows']*row['cols']>=row['capacity']
        assert row['pages']*row['capacity']>=24
    by_name={row['name']:row for row in rows}
    assert by_name['single']['pages']==24
    assert by_name['horizontal']['pages']==12
    assert by_name['quad']['pages']==6
    assert by_name['custom']['capacity']==24 and by_name['custom']['pages']==1


def test_grid_and_count_validation_and_no_external_image_urls():
    result=node("""
      const bad=[()=>V.layoutPlan(0),()=>V.layoutPlan(513),()=>V.layoutPlan(2,'invented'),
        ()=>V.gridSize(0,2),()=>V.gridSize(2.5,2),()=>V.gridSize(64,64),()=>V.gridSize(2,65)];
      process.stdout.write(JSON.stringify({errors:bad.map(fn=>{try{fn();return false}catch{return true}}),
        urls:['art-1','https://evil.test/a','../bad','javascript:alert(1)','',null].map(V.payloadUrl)}));
    """)
    assert all(result['errors'])
    assert result['urls']==['/api/artifacts/art-1/payload',None,None,None,None,None]


def test_native_dialog_and_content_boundary_are_explicit():
    source=MODULE.read_text(encoding='utf-8')
    assert '.showModal()' in source and "addEventListener('cancel'" in source
    assert 'requestFullscreen(' not in source and '.srcdoc=' not in source and '.innerHTML=' not in source
    assert "entry.mount(record.slot,context)" in source
