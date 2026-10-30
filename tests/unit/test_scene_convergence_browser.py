"""Real served-page clicks using final S01/S03/S04 modules and isolated fetch fixture."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.unit.test_mouse_resize_browser import OBJECTS, _node, _state
from tests.unit.test_selection_actions_browser import _obj, _until
from tests.unit.test_status_centre_browser import _drive


MENU = lambda action: f'[data-act="{action}"]'


def _ready(ids):
    return _until('sceneReady',json.dumps(ids)+'.every(id=>document.querySelector(\'.sc-node[data-object-id="\'+id+\'"]\'))',12000)


def _commands(step):
    return [b['body'] for b in step['bodies'] if b['path'] == '/api/scene/commands' and b['body'].get('op') == 'layout_selection']


def test_organization_and_resize_are_atomic_and_undo_keeps_pin_and_selection(tmp_path):
    actions = [
        _ready(['jobj_w','jobj_c','jobj_p']),
        ['click', 'pick', _node('jobj_w'), 100], ['ctrlclick', 'add', _node('jobj_c'), 100],
        ['eval', 'before', _state(), 0], ['rclick', 'menu', _node('jobj_w'), 100],
        ['click', 'organize', MENU('organize'), 100], ['click', 'row', MENU('layout:row'), 700],
        ['eval', 'organized', _state(), 0], ['key', 'undo', 'z', 700, 2], ['eval', 'undone', _state(), 0],
        ['drag', 'resize', _node('jobj_w')+' > .sc-grip[data-resize-sides="right"]', 700, [18, 0]],
        ['eval', 'resized', _state(), 0], ['key', 'undoResize', 'z', 700, 2], ['eval', 'final', _state(), 0],
    ]
    step = _drive(tmp_path, [{'width':1920,'height':1080,'storage':{'orbit':False},'seed':{'objects':OBJECTS},'actions':actions}])[0]
    r=step['results']; cmds=_commands(step)
    assert len(cmds)==4, (cmds,r)
    assert len(cmds[0]['targets'])==2 and cmds[0]['pin'] is True
    assert 'pin' not in cmds[1] and len(cmds[2]['targets'])==1 and 'pin' not in cmds[3]
    before={o['object_id']:o['geometry'] for o in r['before']['objects']}
    assert {o['object_id']:o['geometry'] for o in r['undone']['objects']}==before
    assert {o['object_id']:o['geometry'] for o in r['final']['objects']}==before
    assert all(o['constraints']['pinned_by_user'] for o in r['final']['objects'] if o['object_id'] in {'jobj_w','jobj_c'})
    assert set(r['organized']['selection'])=={'jobj_w','jobj_c'}
    assert r['resized']['holding']==[]
    assert not [c for c in step['console'] if c['type'] in ('error','exception')]


@pytest.mark.parametrize('width,height',[(1920,1080),(600,800)])
def test_custom_numeric_grid_and_viewer_preserve_geometry_selection_focus(tmp_path,width,height):
    objects=[_obj('jobj_a','window',rep='window',geometry={'x':-50,'y':-30,'w':25,'h':18},payload={'title':'Premier','summary':'# Document premier'}),
             _obj('jobj_b','window',rep='window',geometry={'x':10,'y':0,'w':25,'h':18},payload={'title':'Second','summary':'Document second'}),
             _obj('jobj_p','agent',rep='point',geometry={'x':50,'y':30,'w':6,'h':6},payload={'title':'Agent'})]
    for o in objects:o['origin']='user'
    actions=[
        _ready(['jobj_a','jobj_b','jobj_p']),
        ['click','pick',_node('jobj_a'),100], ['ctrlclick','add',_node('jobj_b'),100],
        ['rclick','menu',_node('jobj_a'),100], ['click','organize',MENU('organize'),100],['click','custom',MENU('layout:custom'),150],
        ['eval','invalidGrid',"document.querySelector('[name=rows]').value='1';document.querySelector('[name=cols]').value='1';true",0],
        ['click','refuseSmall','[data-organize-apply]',150],['eval','gridRefusal',"({open:document.querySelector('#jvObjectViewer').open,text:document.querySelector('.scv-action-result').textContent})",0],
        ['click','graphical','.scv-grid-picker [data-rows="3"][data-cols="4"]',100],['eval','pickedGrid',"[document.querySelector('[name=rows]').value,document.querySelector('[name=cols]').value]",0],
        ['eval','numeric',"document.querySelector('[name=rows]').value='3';document.querySelector('[name=cols]').value='8';true",0],
        ['click','apply','[data-organize-apply]',700], ['eval','beforeView',_state(),0],
        ['ctrlclick','mixed',_node('jobj_p'),100], ['rclick','viewMenu',_node('jobj_a'),100], ['click','view',MENU('view'),600],
        ['eval','viewer',"({state:JarvisScene.inspect(),text:document.querySelector('#jvObjectViewer').textContent,open:document.querySelector('#jvObjectViewer').open})",0],
        ['shot','viewerShot',str(Path(os.environ.get('JARVIS_S5_EVIDENCE_DIR',str(tmp_path)))/f'scene-viewer-{width}.png'),50],
        ['key','close','Escape',300],['eval','afterView',"({..."+_state()+",active:document.activeElement.dataset.objectId})",0],
        ['key','enter','Enter',600],['eval','enterOpen','document.querySelector("#jvObjectViewer").open',0],['key','close2','Escape',200],
        ['dblclick','double',_node('jobj_a'),600],['eval','doubleOpen','document.querySelector("#jvObjectViewer").open',0],['key','close3','Escape',200],
    ]
    step=_drive(tmp_path,[{'width':width,'height':height,'storage':{'orbit':False},'seed':{'objects':objects},'actions':actions}])[0]
    r=step['results'];assert len(_commands(step))==1, (r,_commands(step))
    assert r['gridRefusal']['open'] and 'pas assez de cases' in r['gridRefusal']['text']
    assert r['pickedGrid']==['3','4']
    assert r['viewer']['open'] and 'Document premier' in r['viewer']['text'] and 'Document second' in r['viewer']['text']
    assert '1 objet(s) incompatible(s)' in r['viewer']['text']
    assert r['beforeView']['objects']==r['afterView']['objects']
    assert set(r['afterView']['selection'])=={'jobj_a','jobj_b','jobj_p'}
    assert r['afterView']['active']=='jobj_a', (r['afterView'],step['console'])
    assert r['enterOpen'] and r['doubleOpen']
    assert not [c for c in step['console'] if c['type'] in ('error','exception')]


def test_every_organization_menu_action_uses_one_batch_with_orbit_enabled(tmp_path):
    objects=[_obj('jobj_'+str(i),'artifact',rep='capsule',geometry={'x':-35+i*27,'y':-22+i*18,'w':12+i*2,'h':7+i},payload={'title':'Document '+str(i),'summary':'Texte'}) for i in range(3)]
    for o in objects:o['origin']='user'
    actions=[_ready(['jobj_0','jobj_1','jobj_2']),['click','pick',_node('jobj_0'),100],['ctrlclick','add1',_node('jobj_1'),100],['ctrlclick','add2',_node('jobj_2'),100]]
    operations=['row','column','grid','left','center','right','top','middle','bottom','distributeX','distributeY','width','height','size']
    for operation in operations:
        actions += [['rclick','menu'+operation,_node('jobj_0'),100],['click','organize'+operation,MENU('organize'),100]]
        section='align' if operation in {'left','center','right','top','middle','bottom'} else 'distribute' if operation.startswith('distribute') else 'size' if operation in {'width','height','size'} else None
        if section:actions += [['click','section'+operation,MENU('layout-'+section),100]]
        actions += [['click',operation,MENU('layout:'+operation),500],['eval','state'+operation,_state(),0]]
    step=_drive(tmp_path,[{'width':1920,'height':1080,'storage':{'orbit':True},'seed':{'objects':objects},'actions':actions}])[0]
    cmds=_commands(step)
    assert len(cmds)==len(operations), (cmds,step['results'])
    assert all(len(c['targets'])==3 and all('expected_geometry' in t for t in c['targets']) for c in cmds)
    assert all(step['results']['state'+op]['holding']==[] for op in operations)
    assert not [c for c in step['console'] if c['type'] in ('error','exception')]


@pytest.mark.parametrize('orbit,refused',[(False,False),(True,False),(True,True)])
def test_group_pointer_drop_is_one_compared_batch_or_rolls_back_all(tmp_path,orbit,refused):
    actions=[_ready(['jobj_w','jobj_c','jobj_p']),['click','pick',_node('jobj_w'),100],['ctrlclick','add1',_node('jobj_c'),100],['ctrlclick','add2',_node('jobj_p'),100],
        ['eval','before',"({..."+_state()+",revision:__sc.revision})",0],
        ['drag','group',_node('jobj_w')+' .sc-wtitle',700,[36,18]],
        ['eval','after',"({..."+_state()+",revision:__sc.revision,inspect:JarvisScene.inspect()})",0]]
    seed={'objects':OBJECTS,**({'refuse':{'layout_selection':'geometry_changed'}} if refused else {})}
    step=_drive(tmp_path,[{'width':1920,'height':1080,'storage':{'orbit':orbit},'seed':seed,'actions':actions}])[0]
    r=step['results'];cmds=_commands(step)
    assert len(cmds)==1 and len(cmds[0]['targets'])==3 and cmds[0]['pin'] is True,(r,cmds)
    assert set(cmds[0]['selection']['ids'])=={'jobj_w','jobj_c','jobj_p'}
    assert all('expected_geometry' in t for t in cmds[0]['targets'])
    assert r['after']['revision']==r['before']['revision']+(not refused)
    if refused:assert r['after']['objects']==r['before']['objects']
    else:assert all(t['geometry']!=t['expected_geometry'] for t in cmds[0]['targets'])
    assert r['after']['holding']==[] and r['after']['inspect']['pending']==0
    assert set(r['after']['selection'])=={'jobj_w','jobj_c','jobj_p'}
    commands=[b for b in step['bodies'][len(r['before']['bodies']):] if b['path']=='/api/scene/commands']
    assert len(commands)==1
    assert not [c for c in step['console'] if c['type'] in ('error','exception')]


def test_dimension_organization_keeps_brain_windows_out_of_late_auto_fit(tmp_path):
    objects=[_obj('jobj_short','window',rep='window',geometry={'x':-90,'y':-35,'w':50,'h':30},payload={'title':'Court','summary':'Une phrase.'}),
             _obj('jobj_long','window',rep='window',geometry={'x':15,'y':-35,'w':50,'h':30},payload={'title':'Long','summary':'\n\n'.join(['Un paragraphe public assez long pour occuper plusieurs lignes dans la fenêtre.']*10)})]
    actions=[_ready(['jobj_short','jobj_long']),['eval','settle','true',700],['click','pick',_node('jobj_short'),100],['ctrlclick','add',_node('jobj_long'),100],
        ['eval','before',_state(),0],['rclick','menu',_node('jobj_short'),100],['click','organize',MENU('organize'),100],
        ['click','sizes',MENU('layout-size'),100],['click','height',MENU('layout:height'),1800],['eval','after',_state(),0]]
    step=_drive(tmp_path,[{'width':1920,'height':1080,'storage':{'orbit':False},'seed':{'objects':objects},'actions':actions}])[0]
    r=step['results'];commands=[b['body'] for b in step['bodies'][len(r['before']['bodies']):] if b['path']=='/api/scene/commands']
    assert len({o['geometry']['h'] for o in r['before']['objects']})==2,r
    assert len(commands)==1 and commands[0]['op']=='layout_selection',(commands,r)
    assert len({o['geometry']['h'] for o in r['after']['objects']})==1
    assert r['after']['holding']==[]
    assert not [c for c in step['console'] if c['type'] in ('error','exception')]
