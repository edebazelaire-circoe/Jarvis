"""Narrow final QA: real S05 sandbox + production fullscreen/native modal.

Prepared without execution. Run only when PM releases the browser slot after
the broad gate. No fetch substitution, user runtime or model request.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

QA = Path(__file__).parent
SOURCE = QA.parents[1] / '05-scene-integration-organize-viewer/qa/test_live_acceptance.py'
SPEC = importlib.util.spec_from_file_location('jarvis_s05_overlay_qa', SOURCE)
LIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIVE)
stack = LIVE.stack  # Reuse the exact owned Core/SQLite/TestServer fixture.
node = LIVE.node
NOTE = LIVE.NOTE_IDS[0]

SURFACES = """(()=>{
  const dialog=document.querySelector('#jvObjectViewer'),p=document.getElementById('jvFullscreenPrompt');
  const hit=el=>{if(!el)return false;const r=el.getBoundingClientRect(),at=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return at===el||el.contains(at)};
  const inspector=window.JarvisStudioInspector?.instance;
  return {viewer:!!dialog?.open,fullscreen:document.fullscreenElement?.dataset.objectId||document.fullscreenElement?.id||null,
    state:JarvisFullscreen.state(),focus:document.activeElement?.id||document.activeElement?.dataset.objectId||document.activeElement?.tagName,
    focusInViewer:!!dialog?.contains(document.activeElement),panel:document.querySelector('#panel')?.classList.contains('open'),
    settings:document.querySelector('#overlay')?.classList.contains('open'),studio:inspector?.view(),
    prompt:p?{popover:p.matches(':popover-open'),parentIsHtml:p.parentElement===document.documentElement,
      hit:hit(p.querySelector('.jvfs-go')),cancelHit:hit(p.querySelector('.jvfs-cancel')),inert:p.inert,
      rect:JSON.parse(JSON.stringify(p.getBoundingClientRect())),text:p.textContent}:null};
})()"""


def request_fullscreen(name, arm_s=60):
    body=json.dumps({'action':'enter','object_id':NOTE,'display':'current','keys':'none','arm_s':arm_s})
    return {'read':name,'expr':"fetch('/api/fullscreen/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:"
            +json.dumps(body)+"}).then(async r=>({status:r.status,body:await r.json()}))"}


def surface(name):
    return {'read':name,'expr':SURFACES}


def state(name):
    return {'read':name,'expr':"fetch('/qa/state').then(r=>r.json())"}


def save(name,result):
    (QA/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


async def test_armed_fullscreen_then_viewer_close_keeps_actionable_prompt_and_fullscreen_owner(stack):
    out=await stack.browser([
        {'until':'JarvisScene.inspect().nodes>=7&&!!window.JarvisFullscreen'},state('before'),
        request_fullscreen('request'),{'until':"JarvisFullscreen.state().state==='needs_gesture'"},surface('armed'),
        {'click':node(NOTE),'count':2},{'until':"document.querySelector('#jvObjectViewer')?.open===true"},surface('during'),
        {'click':'#jvObjectViewer [data-action=close]'},surface('closed'),
        {'shot':str(QA/'fullscreen-prompt-after-viewer.png')},
        {'click':'#jvFullscreenPrompt .jvfs-go'},
        {'until':'document.fullscreenElement!==null'},surface('entered'),
        # The supported scene dblclick must not layer the viewer over active browser fullscreen.
        {'click':node(NOTE),'count':2},surface('open_refused_in_fullscreen'),
        {'eval':'JarvisFullscreen.exit()'},{'until':'document.fullscreenElement===null'},surface('exited'),state('after'),
    ]);save('fullscreen-armed-before-viewer',out)
    assert not out['errors'],out['errors']
    r=out['reads'];assert r['request']['status']==200 and r['request']['body']['state']=='needs_gesture'
    assert r['during']['viewer'] and r['during']['fullscreen'] is None
    assert not r['closed']['viewer'] and r['closed']['prompt']['hit']
    assert r['entered']['fullscreen']==NOTE and not r['entered']['viewer']
    assert not r['open_refused_in_fullscreen']['viewer'] and r['open_refused_in_fullscreen']['fullscreen']==NOTE
    assert r['exited']['fullscreen'] is None
    assert r['before']['revision']==r['after']['revision']


async def test_request_during_native_viewer_has_reachable_prompt_and_escape_focus(stack):
    out=await stack.browser([
        {'until':'JarvisScene.inspect().nodes>=7&&!!window.JarvisFullscreen'},state('before'),
        {'click':node(NOTE),'count':2},{'until':"document.querySelector('#jvObjectViewer')?.open===true"},
        request_fullscreen('request'),{'until':"JarvisFullscreen.state().state==='needs_gesture'"},surface('during'),
        {'shot':str(QA/'fullscreen-prompt-during-viewer.png')},
        # Actual CDP click distinguishes top-layer paint from modal inertness.
        {'click':'#jvFullscreenPrompt .jvfs-cancel'},surface('after_cancel_click'),
        {'key':'Escape'},surface('after_escape'),
        # Bounded cleanup through owned production APIs if either surface remains.
        {'eval':"if(document.querySelector('#jvObjectViewer')?.open)document.querySelector('#jvObjectViewer [data-action=close]').click();JarvisFullscreen.cancel()"},
        surface('closed'),state('after'),
    ]);save('fullscreen-request-during-viewer',out)
    assert not out['errors'],out['errors']
    r=out['reads'];assert r['request']['status']==200 and r['request']['body']['state']=='needs_gesture'
    assert r['during']['fullscreen'] is None and r['during']['viewer']
    assert r['during']['prompt']['hit'] and r['during']['prompt']['cancelHit'],r['during']
    assert r['after_cancel_click']['state']['armed'] is None,r['after_cancel_click']
    assert not r['after_escape']['viewer'] and r['after_escape']['fullscreen'] is None,r['after_escape']
    assert not r['closed']['viewer'] and r['closed']['state']['armed'] is None
    assert r['closed']['focus']==NOTE
    assert r['before']['revision']==r['after']['revision']


async def test_ordinary_panels_settings_and_nonmodal_studio_keep_modal_focus_boundary(stack):
    out=await stack.browser([
        {'until':'JarvisScene.inspect().nodes>=7&&!!window.JarvisStudioInspector?.instance'},state('before'),
        {'eval':"openPanel('errors')"},{'until':"document.querySelector('#panel').classList.contains('open')"},
        {'click':node(NOTE),'count':2},{'until':"document.querySelector('#jvObjectViewer')?.open===true"},surface('ordinary_panel'),
        {'key':'Escape'},surface('ordinary_closed'),
        # Open the existing Settings UI, close through its ordinary Escape owner;
        # do not invent a supported scene click through an inert Settings modal.
        {'eval':"openSettingsHub({source:'qa'})"},{'until':"document.querySelector('#overlay').classList.contains('open')"},surface('settings'),
        {'key':'Escape'},{'until':"!document.querySelector('#overlay').classList.contains('open')"},
        {'click':node(NOTE),'count':2},{'until':"document.querySelector('#jvObjectViewer')?.open===true"},surface('after_settings'),
        {'key':'Escape'},
        {'eval':'JarvisStudioInspector.instance.open({noFocus:true})'},surface('studio_before'),
        {'click':node(NOTE),'count':2},{'until':"document.querySelector('#jvObjectViewer')?.open===true"},surface('studio_during'),
        {'eval':"document.querySelector('#jvStudioInspector button')?.focus()"},surface('studio_focus_attempt'),
        {'key':'Escape'},surface('studio_after'),
        {'eval':'JarvisStudioInspector.instance.close()'},state('after'),
    ]);save('ordinary-panels-settings-studio-viewer',out)
    assert not out['errors'],out['errors']
    r=out['reads'];assert r['ordinary_panel']['viewer'] and not r['ordinary_panel']['panel']
    assert not r['ordinary_closed']['viewer'] and r['ordinary_closed']['focus']==NOTE
    assert r['settings']['settings'] and not r['settings']['viewer']
    assert r['after_settings']['viewer'] and not r['after_settings']['settings']
    assert r['studio_before']['studio']['open']
    assert r['studio_during']['viewer'] and r['studio_focus_attempt']['focusInViewer']
    assert not r['studio_after']['viewer'] and r['studio_after']['focus']==NOTE
    # Keeping an ordinary nonmodal inspector inert behind a modal is permitted.
    assert r['before']['revision']==r['after']['revision']
