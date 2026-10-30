"""F2 regression: actual isolated Core/page/Chromium, canonical fullscreen owner."""
import importlib.util
import json
from pathlib import Path

QA = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location('mov_f2_live', QA / 'test_live_acceptance.py')
LIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIVE)
stack = LIVE.stack
NOTE = LIVE.NOTE_IDS[0]
NODE = LIVE.node(NOTE)

SURFACE = """(()=>{
  const v=document.querySelector('#jvObjectViewer'),p=document.getElementById('jvFullscreenPrompt');
  const hit=el=>{if(!el)return false;const r=el.getBoundingClientRect(),t=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return t===el||el.contains(t)};
  return {viewer:!!v?.open,entries:JarvisScene.inspect().viewer.entries||[],
    fullscreen:document.fullscreenElement?.dataset.objectId||null,state:JarvisFullscreen.state(),
    selection:JarvisScene.inspect().selection,focus:document.activeElement?.dataset.objectId||document.activeElement?.id,
    providerSignals:window.__providerSignals||null,
    prompt:p?{go:hit(p.querySelector('.jvfs-go')),cancel:hit(p.querySelector('.jvfs-cancel'))}:null,
    feedback:document.querySelector('.toasts')?.textContent||document.body.textContent};
})()"""


def surface(name):
    return {'read': name, 'expr': SURFACE}


def request(name):
    body = json.dumps({'action': 'enter', 'object_id': NOTE, 'display': 'current', 'keys': 'none', 'arm_s': 60})
    return {'read': name, 'expr': "fetch('/api/fullscreen/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:"
            + json.dumps(body) + "}).then(async r=>({status:r.status,body:await r.json()}))"}


def stable(out, filename):
    (QA / filename).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    assert not out['errors'], out['errors']
    r = out['reads']
    assert r['before']['revision'] == r['after']['revision']
    assert LIVE.boxes(r['before']) == LIVE.boxes(r['after'])
    assert r['initial']['selection'] == r['final']['selection'] == [NOTE]
    assert not [x for x in out['requests'] if x['method'] == 'POST' and x['path'] == '/api/scene/commands']


async def test_armed_request_refuses_viewer_and_keeps_cancel_actionable(stack):
    out = await stack.browser([
        {'until': 'JarvisScene.inspect().nodes>=7&&JarvisScene.inspect().pending===0&&!!window.JarvisFullscreen'},
        {'click': NODE}, LIVE.actual('before'), surface('initial'), request('request'),
        {'until': "JarvisFullscreen.state().state==='needs_gesture'"},
        {'click': NODE, 'count': 2}, surface('refused'),
        {'shot': str(QA / 'fullscreen-armed-viewer-refused.png')},
        {'click': '#jvFullscreenPrompt .jvfs-cancel'}, surface('cancelled'),
        {'click': NODE, 'count': 2}, {'until': "document.querySelector('#jvObjectViewer')?.open===true"},
        {'key': 'Escape'}, surface('final'), LIVE.actual('after'),
    ])
    stable(out, 'fullscreen-armed-viewer-refused.json')
    r = out['reads']
    assert r['request']['status'] == 200
    assert not r['refused']['viewer'] and r['refused']['fullscreen'] is None
    assert r['refused']['prompt'] == {'go': True, 'cancel': True}
    assert 'Répondez d’abord à la demande de plein écran' in r['refused']['feedback']
    assert r['cancelled']['state']['armed'] is None and r['cancelled']['fullscreen'] is None
    assert not r['final']['viewer'] and r['final']['focus'] == NOTE


async def test_request_during_viewer_closes_owner_before_actionable_go_and_preserves_active_guard(stack):
    out = await stack.browser([
        {'until': 'JarvisScene.inspect().nodes>=7&&JarvisScene.inspect().pending===0&&!!window.JarvisFullscreen'},
        {'click': NODE}, LIVE.actual('before'), surface('initial'),
        # Observe the real provider AbortSignal; leave its renderer, lifecycle
        # and network transport intact. No fixture response replaces a read.
        {'eval': """window.__providerSignals={mounted:0,aborted:0};
          const factory=JarvisObjectViewer.create;
          window.JarvisObjectViewer={...JarvisObjectViewer,create(deps){
            const v=factory(deps),open=v.openObjects;
            v.openObjects=(entries,options)=>open(entries.map(e=>!e.mount?e:{...e,mount(slot,ctx){
              __providerSignals.mounted++;ctx.signal.addEventListener('abort',()=>__providerSignals.aborted++);
              return e.mount(slot,ctx);
            }}),options);return v;
          }};"""},
        {'click': NODE, 'count': 2}, {'until': "!!document.querySelector('#jvObjectViewer .scv-document')"},
        request('request'), {'until': "JarvisFullscreen.state().state==='needs_gesture'"}, surface('armed'),
        {'wait': 500}, surface('settled'), {'shot': str(QA / 'fullscreen-request-closes-viewer.png')},
        {'click': '#jvFullscreenPrompt .jvfs-go'}, {'until': 'document.fullscreenElement!==null'}, surface('entered'),
        {'click': NODE, 'count': 2}, surface('active_refusal'),
        {'eval': 'JarvisFullscreen.exit()'}, {'until': 'document.fullscreenElement===null'},
        surface('final'), LIVE.actual('after'),
    ])
    stable(out, 'fullscreen-request-closes-viewer.json')
    r = out['reads']
    assert r['request']['status'] == 200
    assert not r['armed']['viewer'] and r['armed']['entries'] == [] and r['armed']['fullscreen'] is None
    assert r['armed']['providerSignals'] == {'mounted': 1, 'aborted': 1}
    assert r['armed']['prompt'] == {'go': True, 'cancel': True}
    assert not r['settled']['viewer'] and r['settled']['entries'] == []
    assert r['entered']['fullscreen'] == r['active_refusal']['fullscreen'] == NOTE
    assert not r['entered']['viewer'] and not r['active_refusal']['viewer']
    assert r['final']['fullscreen'] is None and r['final']['state']['armed'] is None
    assert r['final']['focus'] == NOTE


async def test_idless_local_arm_also_refuses_viewer_and_its_prompt_can_cancel(stack):
    out = await stack.browser([
        {'until': 'JarvisScene.inspect().nodes>=7&&JarvisScene.inspect().pending===0&&!!window.JarvisFullscreen'},
        {'click': NODE}, LIVE.actual('before'), surface('initial'),
        {'wait': 5500}, {'read': 'local', 'expr': 'JarvisFullscreen.enter({object_id:' + json.dumps(NOTE) + '})'},
        {'until': "JarvisFullscreen.state().armed!==null"},
        {'click': NODE, 'count': 2}, surface('refused'),
        {'click': '#jvFullscreenPrompt .jvfs-cancel'}, surface('final'), LIVE.actual('after'),
    ])
    stable(out, 'fullscreen-local-idless-viewer-refused.json')
    r = out['reads']
    assert r['local']['state'] == 'needs_gesture'
    assert r['refused']['state']['armed']['id'] is None
    assert not r['refused']['viewer'] and r['refused']['fullscreen'] is None
    assert r['refused']['prompt'] == {'go': True, 'cancel': True}
    assert r['final']['state']['armed'] is None and r['final']['fullscreen'] is None
