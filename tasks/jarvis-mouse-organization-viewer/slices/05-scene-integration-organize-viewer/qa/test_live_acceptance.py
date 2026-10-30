"""Independent S05 QA. Real isolated Core/SQLite + Control Center + Chromium.

Run explicitly from repository root. This file lives under the Slice QA area,
not the default suite. No user runtime/data, model or mutation fetch doubles.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import struct
import zlib

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from jarvis.domain.artifacts import ArtifactKind
from jarvis.domain.mission_history import MissionOpening
from jarvis.domain.scene import (
    ExecState, Representation, SceneActor, SceneCommand, SceneGeometry,
    SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload, SceneRelation, RelationKind,
)
from jarvis.domain.work_state import WorkObservation, WorkStatus
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.core_sessions import CoreSessionTransport
from jarvis.runtime.declaration_relay import CoreMissionTransport
from jarvis.runtime.mission_view import CoreMissionView
from jarvis.runtime.scene_view import CoreSceneTransport, CoreSceneView
from jarvis.runtime.work_ingress import CoreWorkTransport
from jarvis.runtime.work_view import CoreWorkView
from tests.fakes.mission_history import fact
from tests.integration.test_work_cancel_protocol import JobCore, running_job
from tests.unit.test_fullscreen_browser import _chrome

QA=Path(__file__).parent
ARTIFACT='jart_'+'a'*32
IMAGE='jart_'+'b'*32
NOTE_IDS=('qa-note-a','qa-note-b','qa-note-c')
AGENT='claude:qa-parent'


class LiveAcceptance:
    def __init__(self,tmp_path):
        self.root=tmp_path
        self.process=JobCore(tmp_path/'core')
        self.now=datetime.now(timezone.utc)
        self.server=None
        self.transports=[]

    async def start(self):
        self.process.token_file.parent.mkdir(parents=True,exist_ok=True)
        await self.process.start()
        args={'host':'127.0.0.1','port':self.process.port,'token_file':self.process.token_file}
        self.scene=CoreSceneView(CoreSceneTransport(**args))
        self.work=CoreWorkView(CoreWorkTransport(**args))
        self.missions=CoreMissionView(CoreMissionTransport(**args))
        self.sessions=CoreSessionTransport(**args)
        runtime=self.root/'control-runtime';runtime.mkdir()
        self.control=ControlCenter(runtime_root=runtime,project_root=self.root,
            scene_view=self.scene,work_view=self.work,mission_view=self.missions,sessions=self.sessions)
        self.control._app.router.add_get('/qa/state',self.state)
        self.control._app.router.add_post('/qa/external-edit',self.external_edit)
        self.control._app.router.add_post('/qa/work-complete',self.work_complete)
        self.control._app.router.add_post('/qa/restart',self.restart)
        await self.seed()
        self.server=TestServer(self.control._app,shutdown_timeout=1)
        await self.server.start_server()
        return self

    async def close(self):
        if self.server:
            await self.server.close()
        await self.scene.aclose();await self.work.aclose();await self.missions.close();await self.sessions.close()
        await self.process.stop()

    async def apply(self,op,actor=SceneActor.USER,**kwargs):
        out=await self.process.core.scene.apply(SceneCommand(op=op,actor=actor,**kwargs))
        assert out.outcome.value in ('applied','duplicate'),out
        return out

    async def seed(self):
        core=self.process.core
        await core.sessions.current()
        core.voice_channel.started_at-=10  # Canonical test setup: no Voice process exists in this sandbox.
        await core.artifacts.record_text(artifact_id=ARTIFACT,kind=ArtifactKind.TRANSCRIPT,source='qa',
            text=('Document de QA : une observation publique et ses limites.\n\n')*60,
            jarvis_session_id=None,context_id=None,started_at=None,ended_at=None,duration_ms=None,
            metadata={'title':'Compte rendu de QA'},origins=())
        for index,object_id in enumerate(NOTE_IDS):
            payload=ScenePayload(title=['Compte rendu','Hypothèses','Sources'][index],summary='Texte public de QA '+str(index),
                registry_artifact_id=ARTIFACT if index==0 else '')
            await self.apply(SceneOp.UPSERT_OBJECT,object_id=object_id,
                fields=SceneObjectFields(kind=SceneObjectKind.WINDOW,category='note',representation=Representation.WINDOW,
                    geometry=SceneGeometry(-65+index*55,-18+index*15,30+index*4,20+index*4),payload=payload))
            await self.apply(SceneOp.PIN,object_id=object_id)
        image=await core.artifacts.create(kind=ArtifactKind.SCREENSHOT,source='qa',payload_name='fixture.png',mime_type='image/png',artifact_id=IMAGE)
        def chunk(kind,data):
            return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
        raw=b''.join(b'\0'+bytes([30,130,160])*128 for _ in range(96))
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',128,96,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
        await core.artifacts.store_payload(image.artifact_id,png,width=128,height=96)
        await self.apply(SceneOp.UPSERT_OBJECT,object_id='qa-image',fields=SceneObjectFields(kind=SceneObjectKind.WINDOW,
            category='image',representation=Representation.WINDOW,geometry=SceneGeometry(40,-40,26,20),
            payload=ScenePayload(title='Image réelle du registre',registry_artifact_id=IMAGE)))
        await self.apply(SceneOp.PIN,object_id='qa-image')
        parent=await core.mission_history.record_declaration(
            fact('qa-tool-parent',role='coder',mission_id='qa-mission',owner=True,label='Comparer les documents'),
            work_source='claude',work_external_id='qa-parent',mission=MissionOpening(objective='Comparer trois sources et expliquer leurs limites'))
        assert parent.instance is not None,parent.to_payload()
        await core.work_state.observe(WorkObservation(source='claude',external_id='qa-parent',status=WorkStatus.RUNNING,
            observed_at=self.now,started_at=self.now,kind='agent',role_id='coder',label='Comparer les documents',
            activity='Lecture des sources publiques',progress_fraction=.4,summary='Deux sources concordent.'))
        await core.work_state.observe(WorkObservation(source='claude',external_id='qa-child',parent_external_id='qa-parent',
            status=WorkStatus.RUNNING,observed_at=self.now,started_at=self.now,kind='agent',label='Vérifier une source'))
        self.job=await running_job(self.process)
        async def projected():
            while (await core.scene.snapshot()).get_object(AGENT) is None:
                await asyncio.sleep(.02)
        await asyncio.wait_for(projected(),5)
        snapshot=await core.scene.snapshot()
        for index,item in enumerate(snapshot.objects):
            if item.kind not in (SceneObjectKind.AGENT,SceneObjectKind.JOB,SceneObjectKind.ATTENTION):
                continue
            await self.apply(SceneOp.SET_GEOMETRY,object_id=item.object_id,geometry=SceneGeometry(-70+(index-4)*25,60,6,6))
            await self.apply(SceneOp.PIN,object_id=item.object_id)
        await self.apply(SceneOp.LINK,relation=SceneRelation('qa-produced',RelationKind.EXPLAINS,NOTE_IDS[0],AGENT))

    async def state(self,_request):
        scene=await self.process.core.scene.snapshot()
        job=await self.process.core.state.get_job(self.job.id)
        return web.json_response({'snapshot':scene.to_payload(),'revision':scene.revision,'job_status':job.status.value,
                                  'job_id':self.job.id,'agent_id':AGENT,'note_ids':NOTE_IDS})

    async def external_edit(self,request):
        data=await request.json();object_id=data.get('id',NOTE_IDS[0])
        assert object_id in NOTE_IDS
        current=(await self.process.core.scene.snapshot()).get_object(object_id)
        geometry=SceneGeometry(current.geometry.x+7,current.geometry.y,current.geometry.w,current.geometry.h)
        await self.apply(SceneOp.SET_GEOMETRY,object_id=object_id,geometry=geometry)
        return await self.state(request)

    async def work_complete(self,request):
        await self.process.core.work_state.observe(WorkObservation(source='claude',external_id='qa-parent',
            status=WorkStatus.COMPLETED,observed_at=self.now+timedelta(seconds=10),
            label='Comparer les documents',summary='Trois sources comparées, une divergence expliquée.',progress_fraction=1))
        return await self.state(request)

    async def restart(self,request):
        await self.process.stop();await self.process.start()
        return await self.state(request)

    async def browser(self,plan):
        node=shutil.which('node')
        if not node:
            pytest.skip('node absent')
        process=await asyncio.create_subprocess_exec(node,str(QA/'live-browser.mjs'),str(self.server.make_url('/')),
            _chrome(),json.dumps(plan),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            stdout,stderr=await asyncio.wait_for(process.communicate(),timeout=180)
        except asyncio.TimeoutError:
            process.kill();await process.wait();raise
        assert process.returncode==0,stderr.decode('utf-8')
        return json.loads(stdout)


@pytest.fixture
async def stack(tmp_path,monkeypatch):
    monkeypatch.setenv('JARVIS_DATA_ROOT',str(tmp_path/'isolated-default-data'))
    monkeypatch.setenv('JARVIS_RUNTIME_DIR',str(tmp_path/'isolated-default-runtime'))
    instance=LiveAcceptance(tmp_path)
    try:
        await instance.start()
        yield instance
    finally:
        await instance.close()


async def test_live_stack_renders_real_seeded_scene_without_mutation_fetch_double(stack):
    out=await stack.browser([
        {'until':"window.JarvisScene&&JarvisScene.inspect().nodes>=5",'ms':12000},
        {'read':'scene','expr':'JarvisScene.inspect()'},
        {'read':'state','expr':"fetch('/qa/state').then(r=>r.json())"},
        {'read':'ids','expr':"[...document.querySelectorAll('#sceneLayer [data-object-id]')].map(n=>n.dataset.objectId)"},
        {'read':'chat','expr':"fetch('/api/chat/state').then(r=>r.json())"},
    ])
    assert not out['errors'],out['errors']
    assert set(NOTE_IDS).issubset(out['reads']['ids'])
    assert AGENT in out['reads']['ids']
    assert out['reads']['scene']['enabled']
    (QA/'live-preflight.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')


def node(object_id):
    return '#sceneLayer [data-object-id="'+object_id+'"]'


def actual(name):
    return {'read':name,'expr':"fetch('/qa/state').then(r=>r.json())"}


def layout_setup(action='row'):
    return [
        {'until':"JarvisScene.inspect().nodes>=7&&JarvisScene.inspect().pending===0"},
        {'click':node(NOTE_IDS[0])},{'click':node(NOTE_IDS[1]),'ctrl':True},{'click':node(NOTE_IDS[2]),'ctrl':True},
        {'read':'selection_before','expr':'JarvisScene.inspect().selection'},
        {'eval':"fetch('/qa/state').then(v=>v.json()).then(v=>window.__before=v)"},
        actual('before'),{'click':node(NOTE_IDS[1]),'button':'right'},
        {'read':'selection_menu','expr':'JarvisScene.inspect().selection'},
        {'click':'#ctxMenu button[data-act="organize"]'},
        {'click':'#ctxMenu button[data-act="layout:'+action+'"]'},
        {'until':"fetch('/qa/state').then(r=>r.json()).then(v=>v.revision>window.__before.revision)"},
        {'eval':"fetch('/qa/state').then(r=>r.json()).then(v=>window.__organized=v)"},
        {'until':"JarvisScene.inspect().revision>=window.__organized.revision&&JarvisScene.inspect().pending===0"},
        actual('organized'),
    ]


def boxes(state):
    return {entry['object_id']:entry['geometry'] for entry in state['snapshot']['objects'] if entry['object_id'] in NOTE_IDS}


def save(name,out):
    (QA/(name+'.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')


@pytest.mark.parametrize('orbit',[False,True])
async def test_one_real_layout_revision_then_geometry_undo_and_viewer_preserve_selection(stack,orbit):
    plan=[{'view':{'orbit':orbit,'breathe':False,'speed':2}}]+layout_setup()+[
        {'eval':"document.querySelector("+json.dumps(node(NOTE_IDS[1]))+").focus()"},
        {'key':'Enter'},{'until':"document.querySelector('#jvObjectViewer')?.open===true"},
        {'until':"document.querySelector('#jvObjectViewer .jvov-text')!==null"},
        {'read':'viewer','expr':'JarvisScene.inspect()'},
        {'shot':str(QA/('live-documents-orbit.png' if orbit else 'live-documents.png'))},
        {'eval':"const s=document.querySelector('#jvObjectViewer select');s.value='quad';s.dispatchEvent(new Event('change',{bubbles:true}))"},
        {'key':'Escape'},actual('after_view'),
        {'read':'selection_after','expr':'JarvisScene.inspect().selection'},
        {'key':'z','ctrl':True},
        {'until':"fetch('/qa/state').then(r=>r.json()).then(v=>v.revision>window.__organized.revision)"},
        actual('undone'),
    ]
    out=await stack.browser(plan);save('live-layout-viewer-undo-'+('orbit' if orbit else 'fixed'),out)
    assert not out['errors'],out['errors']
    data=out['reads']
    assert set(data['selection_before'])==set(NOTE_IDS)==set(data['selection_menu'])==set(data['selection_after'])
    assert data['organized']['revision']==data['before']['revision']+1
    assert boxes(data['organized'])!=boxes(data['before'])
    assert data['after_view']['revision']==data['organized']['revision']
    assert boxes(data['after_view'])==boxes(data['organized'])
    assert data['undone']['revision']==data['organized']['revision']+1
    assert boxes(data['undone'])==boxes(data['before'])
    commands=[json.loads(req['body']) for req in out['requests'] if req['method']=='POST' and req['path']=='/api/scene/commands']
    assert len(commands)==2 and all(cmd['op']=='layout_selection' for cmd in commands),commands
    assert all('expected_geometry' in target for target in commands[1]['targets'])


async def test_external_geometry_change_prevents_stale_undo_without_any_overwrite(stack):
    out=await stack.browser(layout_setup()+[
        {'eval':"fetch('/qa/external-edit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:'qa-note-a'})}).then(r=>r.json()).then(v=>window.__external=v)"},
        {'until':"JarvisScene.inspect().revision>=window.__external.revision"},actual('external'),
        {'key':'z','ctrl':True},{'wait':600},actual('after_stale'),
        {'read':'feedback','expr':"document.querySelector('#toasts')?.textContent||''"},
    ]);save('live-stale-undo',out)
    assert not out['errors'],out['errors']
    assert out['reads']['after_stale']['revision']==out['reads']['external']['revision']
    assert boxes(out['reads']['after_stale'])==boxes(out['reads']['external'])
    assert out['reads']['feedback']


async def test_real_registry_image_text_mapping_agent_artifact_back_and_truthful_states(stack):
    out=await stack.browser([
        {'until':"JarvisScene.inspect().nodes>=7"},
        {'click':node('qa-image'),'count':2},{'until':"document.querySelector('#jvObjectViewer')?.open===true"},
        {'until':"document.querySelector('#jvObjectViewer img')?.naturalWidth===128"},
        {'read':'image','expr':"({src:document.querySelector('#jvObjectViewer img').getAttribute('src'),text:document.querySelector('#jvObjectViewer').textContent})"},
        {'key':'Escape'},{'click':node(AGENT),'count':2},
        {'until':"document.querySelector('.scv-agent')?.dataset.status==='running'"},
        {'read':'running','expr':"({text:document.querySelector('.scv-agent').textContent,stop:document.querySelector('[data-agent-action=stop]').disabled})"},
        {'click':'.scv-agent [data-agent-artifact="qa-note-a"]'},
        {'until':"document.querySelector('#jvObjectViewer .jvov-text')?.textContent.includes('Document de QA')"},
        {'read':'artifact','expr':"document.querySelector('#jvObjectViewer .jvov-text').textContent"},
        {'click':'#jvObjectViewer .jvov-head button:first-child'},
        {'until':"document.querySelector('.scv-agent')?.dataset.status==='running'"},
        {'eval':"fetch('/qa/work-complete',{method:'POST'}).then(r=>r.json())"},
        {'until':"document.querySelector('.scv-agent')?.dataset.status==='completed'",'ms':12000},
        {'read':'terminal','expr':"document.querySelector('.scv-agent').textContent"},
        {'key':'Escape'},
        {'eval':"fetch('/qa/restart',{method:'POST'}).then(r=>r.json())"},
        {'click':node(AGENT),'count':2},
        {'until':"document.querySelector('.scv-agent')?.dataset.status==='unknown'",'ms':12000},
        {'read':'unknown','expr':"document.querySelector('.scv-agent').textContent"},
        {'shot':str(QA/'live-agent-unknown.png')},
    ]);save('live-artifacts-agent-states',out)
    assert not out['errors'],out['errors']
    reads=out['reads']
    assert reads['image']['src']=='/api/artifacts/'+IMAGE+'/payload'
    assert reads['running']['stop'] and 'Lecture des sources publiques' in reads['running']['text']
    assert 'Comparer trois sources' in reads['running']['text']
    assert 'Document de QA' in reads['artifact']
    assert 'Trois sources comparées' in reads['terminal']
    assert 'Comparer trois sources' in reads['unknown']


async def test_stop_uses_real_canonical_job_cancel_and_ask_preserves_existing_chat_draft(stack):
    job_node=node('job:'+stack.job.id)
    out=await stack.browser([
        {'until':"JarvisScene.inspect().nodes>=7"},
        {'eval':'JarvisChat.open()'},
        {'until':"document.querySelector('#chatInput')&&!document.querySelector('#chatInput').disabled"},
        {'type':'#chatInput','text':'Question déjà rédigée.'},
        {'click':node(AGENT),'count':2},
        {'until':"document.querySelector('.scv-agent')?.dataset.status==='running'"},
        {'click':'[data-agent-action=ask]'},
        {'until':"document.querySelector('#jvObjectViewer')?.open===false"},
        {'read':'draft','expr':"document.querySelector('#chatInput').value"},
        {'eval':'JarvisChat.close()'},
        {'click':job_node,'count':2},
        {'until':"document.querySelector('.scv-agent')?.dataset.status==='running'"},
        {'read':'stop_enabled','expr':"!document.querySelector('[data-agent-action=stop]').disabled"},
        {'click':'[data-agent-action=stop]'},
        {'until':"fetch('/qa/state').then(r=>r.json()).then(v=>v.job_status==='cancelled')",'ms':12000},
        actual('stopped'),
        {'read':'stop_feedback','expr':"document.querySelector('#jvObjectViewer').textContent"},
        {'shot':str(QA/'live-job-stopped.png')},
    ]);save('live-stop-ask',out)
    assert not out['errors'],out['errors']
    assert 'Question déjà rédigée.' in out['reads']['draft'] and 'claude/qa-parent' in out['reads']['draft']
    assert out['reads']['stop_enabled'] and out['reads']['stopped']['job_status']=='cancelled'
    assert out['reads']['stop_feedback']
    calls=[req for req in out['requests'] if req['method']=='POST']
    cancels=[req for req in calls if req['path']=='/api/jobs/cancel']
    assert len(cancels)==1
    body=json.loads(cancels[0]['body'])
    assert body['source']=='job' and body['external_id']==stack.job.id
    assert not any(req['path'] in ('/api/chat/turns','/api/chat/voice/disable') for req in calls)
