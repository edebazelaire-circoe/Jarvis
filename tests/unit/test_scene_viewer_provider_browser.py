"""Production scene adapter + shell + PrefabHost with a canonical Remotion shell transport fixture.

The fixture forwards real focused-frame keys; it does not emulate/render React.
"""
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from tests.unit.test_object_viewer_browser import drive, read


RUNTIME=Path(__file__).resolve().parents[2]/'jarvis/runtime'


@pytest.fixture
async def provider_page():
    modules=['control_center_prefab_protocol.js','control_center_scene_layout.js','control_center_remotion_frame.js',
             'control_center_prefab_host.js','control_center_object_viewer.js','control_center_scene_viewer.js']
    scripts=''.join('<script>'+ (RUNTIME/m).read_text(encoding='utf-8')+'</script>' for m in modules)
    html='''<!doctype html><meta charset="utf-8"><button id="anchor">Ouvrir</button>'''+scripts+'''<script>
      const object={object_id:'jobj_scene',kind:'window',visibility:'visible',payload:{title:'Scène',prefab:{id:'test.scene',version:1}}};
      window.viewer=JarvisSceneViewer.create({document,window,scene:()=>({objects:new Map([[object.object_id,object]])}),
        log:()=>{},appendBlocks:()=>{},focusElement:()=>document.getElementById('anchor')});
      window.openScene=()=>viewer.open(['jobj_scene'],'jobj_scene');
    </script>'''
    stage='''<!doctype html><meta charset="utf-8"><button>Scène transport</button><script>
      const send=x=>parent.postMessage({rsh:1,...x},location.origin);
      addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();send({type:'key',key:e.key})}});
      send({type:'status',phase:'ready',composition:{width:640,height:360,fps:30,durationInFrames:30}});
      send({type:'clock',frame:0,playing:false,duration:30,fps:30});
    </script>'''
    app=web.Application()
    async def index(_):return web.Response(text=html,content_type='text/html')
    async def frame(_):return web.Response(text=stage,content_type='text/html')
    async def bundle(_):return web.json_response({'kind':'remotion'})
    app.router.add_get('/',index);app.router.add_get('/remotion-stage',frame)
    app.router.add_get('/api/prefabs/test.scene/1/bundle',bundle)
    async with TestServer(app) as server:yield str(server.make_url('/'))


async def test_remotion_escape_only_closes_from_the_active_provider_frame(provider_page):
    out=await drive(provider_page,[{'eval':'openScene()'},
        {'until':"viewer.snapshot().entries[0]?.state==='ready'",'ms':10000},
        {'eval':"window.frame=document.querySelector('#jvObjectViewer iframe');window.closeButton=document.querySelector('#jvObjectViewer [data-action=close]');closeButton.focus();frame.contentWindow.eval(\"parent.postMessage({rsh:1,type:'key',key:'Escape'},location.origin)\")"},
        {'wait':150},read('unfocused','viewer.snapshot().open'),
        {'eval':'frame.focus()'},read('focus','document.activeElement.tagName'),
        {'key':'Escape'},{'wait':150},read('closed','viewer.snapshot().open'),
        read('returned','document.activeElement.id')])
    assert out['unfocused'] and out['focus']=='IFRAME' and not out['closed'] and out['returned']=='anchor',out
