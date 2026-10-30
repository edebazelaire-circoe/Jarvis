"""Native Chromium viewer fixtures; real clicks, keys, wheel, pan and screenshots.

Only fixture Artifact payloads are served. No running Jarvis, microphone, user data
or model calls. Canonical PrefabHost is exercised through the injected provider.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from tests.fakes.prefab_js import catalogue_bundles
from tests.unit.test_fullscreen_browser import _chrome

ROOT=Path(__file__).resolve().parents[2]
RUNTIME=ROOT/'jarvis/runtime'
HARNESS=Path(__file__).with_name('_object_viewer_browser.mjs')
PAGE=r'''<!doctype html><html lang="fr"><meta charset="utf-8"><title>Viewer fixture</title>
<style>
:root{color-scheme:dark;--bg:#05080b;--panel:rgba(6,12,18,.94);--solid:#070d13;--line:#183343;--text:#d8edf7;--muted:#8faab9;--accent:#6ee7ff;--warn:#ffb85c}
html[data-jarvis-theme="cosmos"]{--line:#29404a;--solid:#081118;--text:#d5e7ef;--accent:#6ee7ff}
body{margin:0;background:#07131a;color:var(--text);font:14px system-ui}
main{padding:70px;max-width:1000px}h1{font-size:28px}button{padding:12px}
.fixture-paper{padding:32px;max-width:70ch;line-height:1.75}.fixture-paper p{margin:0 0 22px}
</style><body><main><h1>Board de démonstration</h1><p>Documents synthétiques pour vérifier la comparaison.</p>
<button id="opener">Ouvrir les documents</button><button id="behind">Bouton du Board</button></main>
<script>__PROTOCOL__</script><script>__HOST__</script><script>__VIEWER__</script><script>
window.__logs=[];window.__clockExtra=0;window.__board={selection:['first','second'],geometry:{first:{x:10,y:20,w:30,h:40}}};
window.viewer=JarvisObjectViewer.create({document,window,now:()=>Date.now()+window.__clockExtra,log:(level,key,data)=>window.__logs.push({level,key,data})});
window.entry=n=>n%4===3?{id:'doc-'+n,title:'Note de recherche '+(n+1),kind:'text',text:('Une observation documentée, son contexte et ses limites.\n\n').repeat(90)}:
  {id:'image-'+n,title:['Atelier — matin','Matières et lumière','Étude de façade','Comparaison'][n%4]+' '+(n+1),kind:'image',artifactId:'fixture-'+n};
window.openSet=(n,options={})=>viewer.openObjects(Array.from({length:n},(_,i)=>entry(i)),{title:'Comparer les documents',returnFocus:document.getElementById('opener'),...options});
document.getElementById('opener').addEventListener('click',()=>openSet(5));document.getElementById('opener').focus();
window.__probe=()=>({state:viewer.snapshot(),focus:document.activeElement.id||document.activeElement.className||document.activeElement.tagName,
  modal:viewer.element.matches(':modal'),full:document.fullscreenElement!==null,tiles:document.querySelectorAll('.jvov-tile').length,
  bounds:[viewer.element.clientWidth,viewer.element.clientHeight],outside:document.querySelector('.jvov-head').getBoundingClientRect().right>innerWidth,
  text:viewer.element.textContent,board:JSON.stringify(window.__board)});
window.__mounts=0;window.__disposes=0;window.__pauses=0;window.__resumes=0;
window.openMission=()=>viewer.openCustom({id:'agent-fixture',title:'Comparaison des documents',mount:(slot)=>{
  window.__mounts++;const paper=document.createElement('div');paper.className='fixture-paper';
  const button=document.createElement('button');button.id='artifact-link';button.textContent='Voir le document';button.onclick=()=>openSet(1,{push:true});paper.appendChild(button);
  for(let i=0;i<60;i++){const p=document.createElement('p');p.textContent='Observation publique '+(i+1)+' : les sources restent à comparer, sans plan futur inventé.';paper.appendChild(p)}slot.appendChild(paper);
  return {dispose:()=>window.__disposes++,pause:()=>window.__pauses++,resume:()=>window.__resumes++};
}},{returnFocus:document.getElementById('opener')});
const bundle=__BUNDLE__;window.__hostLog=[];window.host=JarvisPrefabHost.createPrefabHost({document,window,log:(key,data)=>__hostLog.push({key,data}),fetchBundle:async()=>bundle,onEscape:()=>viewer.close()});
window.openPrefab=()=>viewer.openObjects([{id:'prefab-document',kind:'provider',title:'Document du fournisseur canonique',mount:(slot,context)=>{
  host.mount(slot,{object_id:'viewer-prefab',title:'Document',prefab:{id:'test.counter',version:1},props:{label:'Document'},data:{count:3,notes:'Lecture'}});
  const timer=setInterval(()=>{if(host.state('viewer-prefab')==='ready'){clearInterval(timer);context.ready()}},30);
  return {pending:true,dispose:()=>{clearInterval(timer);host.unmount('viewer-prefab')},pause:()=>host.pause('viewer-prefab'),resume:()=>host.resume('viewer-prefab')};
}}],{returnFocus:document.getElementById('opener')});
window.__pendingMounts=0;window.openPending=()=>viewer.openCustom({id:'slow',title:'Document lent',mount:()=>{window.__pendingMounts++;return {pending:true}}});
</script></body></html>'''


@pytest.fixture
async def page(tmp_path):
    bundles=await catalogue_bundles(tmp_path,'test.counter')
    html=PAGE.replace('__PROTOCOL__',(RUNTIME/'control_center_prefab_protocol.js').read_text(encoding='utf-8'))
    html=html.replace('__HOST__',(RUNTIME/'control_center_prefab_host.js').read_text(encoding='utf-8'))
    html=html.replace('__VIEWER__',(RUNTIME/'control_center_object_viewer.js').read_text(encoding='utf-8'))
    html=html.replace('__BUNDLE__',json.dumps(bundles['test.counter@1']))
    async def index(_request):
        return web.Response(text=html,content_type='text/html')
    async def payload(request):
        number=int(request.match_info['id'].split('-')[-1])
        colors=['#357e8a','#aa7654','#566ca0','#8b6b85']
        svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="650" viewBox="0 0 900 650">
        <rect width="900" height="650" fill="{colors[number%4]}"/>
        <path d="M0 500L200 190L400 360L600 110L900 430V650H0Z" fill="#0c222d"/>
        <circle cx="680" cy="175" r="65" fill="#e6d6b1"/><path d="M0 550L240 420L520 560L900 350V650H0Z" fill="#163b45"/>
        <text x="40" y="610" fill="#f4ead6" font-family="sans-serif" font-size="20">Étude synthétique {number+1}</text></svg>'''
        return web.Response(text=svg,content_type='image/svg+xml')
    app=web.Application();app.router.add_get('/',index);app.router.add_get('/api/artifacts/{id}/payload',payload)
    async with TestServer(app) as server:
        yield str(server.make_url('/'))


async def drive(page,plan):
    binary=shutil.which('node')
    if not binary:
        pytest.skip('node absent')
    result=await asyncio.to_thread(subprocess.run,[binary,str(HARNESS),page,_chrome(),json.dumps(plan)],capture_output=True,text=True,encoding='utf-8',timeout=100)
    assert result.returncode==0,result.stderr
    out=json.loads(result.stdout)
    assert not out['errors'],out['errors']
    return out['reads']


def read(name,expr='__probe()'):
    return {'read':name,'expr':expr}


@pytest.mark.parametrize('theme',['circuit-board','cosmos'])
async def test_real_viewer_fixtures_layouts_focus_and_both_themes(page,tmp_path,theme):
    shots=Path(os.environ.get('JARVIS_VIEWER_SHOTS',tmp_path));shots.mkdir(parents=True,exist_ok=True)
    plan=[{'eval':f"document.documentElement.dataset.jarvisTheme={json.dumps(theme)}"},read('before')]
    for count in (1,2,4,5,24):
        plan += [{'eval':f'openSet({count})'}, {'until':"viewer.snapshot().entries.some(e=>e.state==='ready')"},read('count'+str(count))]
        if count in (5,24):
            plan.append({'shot':str(shots/f'{theme}-{count}.png')})
    plan += [{'eval':"openSet(5);window.__tile=document.querySelector('.jvov-tile');window.__image=document.querySelector('.jvov-image')"},
             {'until':"viewer.snapshot().entries[0].state==='ready'"},
             {'eval':"for(const name of Object.keys(JarvisObjectViewer.LAYOUTS))viewer.setLayout(name,{rows:3,cols:8})"},
             read('layouts',"({same:window.__tile===document.querySelector('.jvov-tile'),state:viewer.snapshot()})"),
             {'eval':"viewer.setLayout('custom',{rows:3,cols:8})"},
             read('custom',"({rows:document.querySelector('.jvov-fields input').value,cols:document.querySelectorAll('.jvov-fields input')[1].value,state:viewer.snapshot()})"),
             {'eval':"document.querySelector('.jvov-picker button[data-rows=\"3\"][data-cols=\"4\"]').click()"},read('picker','viewer.snapshot()'),
             {'eval':"document.getElementById('behind').focus()"},read('inert',"document.activeElement.id"),
             {'key':'Tab'},{'key':'Tab','shift':True},read('tab',"viewer.element.contains(document.activeElement)"),
             {'key':'Escape'},read('closed')]
    out=await drive(page,plan)
    for count in (1,2,4,5,24):
        state=out['count'+str(count)]
        assert state['modal'] and not state['full'] and state['tiles']==count
        assert state['state']['open'] and len(state['state']['entries'])==count
        assert state['board']==out['before']['board']
        assert not state['outside']
    assert out['layouts']['same']
    assert out['custom']['rows']=='3' and out['custom']['cols']=='8'
    assert out['picker']['layout']=='custom'
    assert out['inert']!='behind' and out['tab']
    assert not out['closed']['state']['open'] and out['closed']['focus']=='opener'
    assert out['closed']['board']==out['before']['board']


async def test_real_image_zoom_pan_fit_and_document_scroll(page):
    out=await drive(page,[{'eval':"openSet(1)"},{'until':"viewer.snapshot().entries[0].state==='ready'"},
        {'wheel':'.jvov-image','dy':-400},{'drag':'.jvov-image','dx':90,'dy':45},read('zoom','viewer.snapshot()'),
        {'eval':"viewer.setLayout('row')"},read('retained','viewer.snapshot()'),
        {'click':'.jvov-image-tools button:last-child'},read('fit','viewer.snapshot()'),
        {'eval':"viewer.openObjects([entry(3)])"},{'until':"viewer.snapshot().entries[0].state==='ready'"},
        {'wheel':'.jvov-slot','dy':550},read('scroll',"document.querySelector('.jvov-slot').scrollTop"),
        {'eval':"viewer.openObjects([{id:'unsafe',kind:'text',title:'Texte sûr',text:'<img src=x onerror=window.__injected=1>'}])"},
        {'until':"viewer.snapshot().entries[0].state==='ready'"},read('safe',"({injected:!!window.__injected,imgs:document.querySelectorAll('.jvov-slot img').length,text:document.querySelector('.jvov-text').textContent})")])
    image=out['zoom']['entries'][0]['image']
    assert image['scale']>1 and image['x']>0 and image['y']>0
    assert out['retained']['entries'][0]['image']==image
    assert out['fit']['entries'][0]['image']=={'scale':1,'x':0,'y':0}
    assert out['scroll']>0
    assert not out['safe']['injected'] and out['safe']['imgs']==0 and '<img' in out['safe']['text']


async def test_custom_history_preserves_dom_scroll_and_provider_lifecycle(page):
    out=await drive(page,[{'eval':'openMission()'},{'until':"viewer.snapshot().entries[0].state==='ready'"},
        {'eval':"window.__paper=document.querySelector('.fixture-paper');document.querySelector('.jvov-slot').scrollTop=280;openSet(1,{push:true})"},
        {'until':"viewer.snapshot().entries[0].state==='ready'"},read('pushed','viewer.snapshot()'),
        {'click':'.jvov-head button:first-child'},read('back',"({state:viewer.snapshot(),same:__paper===document.querySelector('.fixture-paper'),scroll:document.querySelector('.jvov-slot').scrollTop,mounts:__mounts,pauses:__pauses,resumes:__resumes,disposes:__disposes})"),
        {'key':'Escape'},read('disposed','__disposes')])
    assert out['pushed']['depth']==2 and out['back']['state']['kind']=='custom'
    assert out['back']['same'] and out['back']['scroll']==280
    assert out['back']['mounts']==1 and out['back']['pauses']==1 and out['back']['resumes']==1
    assert out['back']['disposes']==0 and out['disposed']==1


async def test_canonical_prefab_provider_stays_mounted_and_escape_works_from_iframe(page):
    out=await drive(page,[{'eval':'openPrefab()'},{'until':"viewer.snapshot().entries[0].state==='ready'",'ms':10000},
        {'eval':"window.__frame=document.querySelector('.jvov iframe');viewer.setLayout('row');viewer.setLayout('single')"},
        read('frame',"({same:__frame===document.querySelector('.jvov iframe'),sandbox:__frame.getAttribute('sandbox'),state:host.state('viewer-prefab')})"),
        {'eval':'__frame.focus()'},read('focus','document.activeElement.tagName'),{'key':'Escape'},read('closed','viewer.snapshot()')])
    assert out['frame']=={'same':True,'sandbox':'allow-scripts','state':'ready'}
    assert out['focus']=='IFRAME' and not out['closed']['open'],out


async def test_paginated_provider_lifecycle_pauses_hidden_content_without_remount(page):
    out=await drive(page,[{'eval':"""
      window.__life={};
      viewer.openObjects([0,1,2].map(id=>({id:'provider-'+id,title:'Document '+id,kind:'provider',mount:slot=>{
        const state=window.__life[id]={mounts:1,pauses:0,resumes:0};slot.textContent='Document '+id;
        return {pause:()=>state.pauses++,resume:()=>state.resumes++};
      }})));
    """},{'until':"viewer.snapshot().entries.every(e=>e.state==='ready')"},
        {'eval':"viewer.setLayout('single')"},read('single','__life'),
        {'click':'.jvov-pages button:last-child'},read('next','({life:__life,state:viewer.snapshot()})'),
        {'click':'.jvov-pages button:first-child'},read('previous','({life:__life,state:viewer.snapshot()})')])
    assert out['single']['0']=={'mounts':1,'pauses':0,'resumes':0}
    assert out['single']['1']=={'mounts':1,'pauses':1,'resumes':0}
    assert out['next']['life']['0']=={'mounts':1,'pauses':1,'resumes':0}
    assert out['next']['life']['1']=={'mounts':1,'pauses':1,'resumes':1}
    assert out['previous']['life']['0']=={'mounts':1,'pauses':1,'resumes':1}
    assert out['previous']['life']['1']=={'mounts':1,'pauses':2,'resumes':1}
    assert all(value['mounts']==1 for value in out['previous']['life'].values())


async def test_timeouts_unsupported_pdf_reduced_motion_and_zoom(page,tmp_path):
    shots=Path(os.environ.get('JARVIS_VIEWER_SHOTS',tmp_path));shots.mkdir(parents=True,exist_ok=True)
    out=await drive(page,[{'media':'reduce'},{'eval':'openPending()'},read('loading'),
        {'eval':'window.__clockExtra=21000'},{'until':"viewer.snapshot().entries[0].state==='failed'"},read('failed'),
        {'click':'.jvov-state button'},read('retry','({mounts:__pendingMounts,state:viewer.snapshot()})'),
        {'eval':"viewer.openObjects([{id:'pdf',kind:'pdf',artifactId:'pdf-fixture',title:'Document PDF'},{id:'other',kind:'unsupported',title:'Autre contenu'}])"},
        {'until':"viewer.snapshot().entries.every(e=>e.state==='ready')"},read('fallback',"({state:viewer.snapshot(),url:document.querySelector('.jvov-slot a').getAttribute('href'),target:document.querySelector('.jvov-slot a').target,text:viewer.element.textContent})"),
        {'size':[640,400]},{'eval':"openSet(5)"},{'until':"viewer.snapshot().entries[0].state==='ready'"},read('zoomed'),
        {'shot':str(shots/'viewer-200-percent.png')},
        {'eval':'openPending()'},read('motion',"getComputedStyle(document.querySelector('.jvov-busy svg')).animationName"),{'key':'Escape'}])
    assert 'Chargement' in out['loading']['text'] and '0 s' in out['loading']['text']
    assert '20 s' in out['failed']['text'] and out['failed']['state']['entries'][0]['state']=='failed'
    assert out['retry']['mounts']==2 and out['retry']['state']['entries'][0]['state']=='loading'
    assert [entry['code'] for entry in out['fallback']['state']['entries']]==['provider_missing','unsupported_content']
    assert out['fallback']['url']=='/api/artifacts/pdf-fixture/payload' and out['fallback']['target']=='_blank'
    assert 'Aperçu PDF indisponible' in out['fallback']['text']
    assert out['zoomed']['bounds']==[640,400] and not out['zoomed']['outside']
    assert out['motion']=='none'


async def test_selected_layout_schematic_is_decorative_bounded_and_preserves_content(page,tmp_path):
    shots=Path(os.environ.get('JARVIS_VIEWER_SHOTS',tmp_path));shots.mkdir(parents=True,exist_ok=True)
    out=await drive(page,[{'eval':'openSet(24)'},{'until':"viewer.snapshot().entries[0].state==='ready'"},
        {'eval':"window.firstTile=document.querySelector('.jvov-tile');window.schemes=Object.keys(JarvisObjectViewer.LAYOUTS).map(name=>{viewer.setLayout(name,{rows:3,cols:8});const p=document.querySelector('.jvov-layout-preview');return {name,layout:p.dataset.layout,cells:p.children.length,hidden:p.getAttribute('aria-hidden'),focusable:p.querySelectorAll('button,input,[tabindex]').length}});viewer.setLayout('largeLeft')"},
        read('schemes','schemes'),read('asymmetric',"(()=>{const p=document.querySelector('.jvov-layout-preview');return {ratio:p.children[0].getBoundingClientRect().width/p.children[1].getBoundingClientRect().width,same:firstTile===document.querySelector('.jvov-tile'),caption:p.title}})()"),
        {'shot':str(shots/'selected-layout-desktop.png')}, {'size':[600,800]},read('narrow','__probe()'),
        {'shot':str(shots/'selected-layout-narrow.png')},{'key':'Escape'},read('closed')])
    assert len(out['schemes'])==10
    assert all(s['layout']==s['name'] and 1<=s['cells']<=24 and s['hidden']=='true' and not s['focusable'] for s in out['schemes'])
    assert out['asymmetric']['same'] and out['asymmetric']['ratio']==pytest.approx(2,abs=.2)
    assert 'Grand à gauche' in out['asymmetric']['caption']
    assert not out['narrow']['outside'] and not out['closed']['state']['open'] and out['closed']['focus']=='opener'
