"""Task14 real HTTP persistence and executed browser-draft contract."""
import json
from pathlib import Path
import shutil
import subprocess

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.journal import read_jsonl_tail


async def test_architecture_endpoint_is_atomic_and_does_not_touch_active_voice(tmp_path, monkeypatch):
    monkeypatch.delenv('JARVIS_VOICE_ARCH', raising=False)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    seed = {'voice_arch': 'legacy', 'voice_stack': 'gemini_live', 'custom_prompts': {'voice': 'private prompt'},
            'inactive_profile': {'model': 'old'}, 'active_timeout_s': '0'}
    control._write_settings(seed)
    (tmp_path / '.voice_state').write_text('listening')
    async with TestClient(TestServer(control._app)) as client:
        view = await (await client.get('/api/settings')).json()
        profiles = {p['id']: p for p in view['voice']['architecture']['architectures']}
        response = await client.post('/api/settings', json={'voice': {'architecture': profiles['duplex']['defaults']}})
        assert response.status == 200
        stored = json.loads(control.settings_path.read_text())
        assert stored['voice_architecture']['config'] == profiles['duplex']['defaults']
        assert stored['voice_architecture']['compatibility'] is None
        assert all(stored[k] == v for k, v in seed.items())
        assert (tmp_path / '.voice_state').read_text() == 'listening'
        before = control.settings_path.read_bytes()
        bad = dict(profiles['duplex']['defaults'], idle_timeout_s=0)
        rejected = await client.post('/api/settings', json={'voice': {'architecture': bad}})
        assert rejected.status == 400
        assert rejected.headers['X-Jarvis-Error-Code'] == 'voice_idle_timeout_invalid'
        assert control.settings_path.read_bytes() == before
    trace = read_jsonl_tail(control.journal.trace_path)
    assert any(e['kind'] == 'settings.update' for e in trace)
    assert any(e['kind'] == 'voice.settings.rejected' and e['data']['code'] == 'voice_idle_timeout_invalid' for e in trace)
    assert 'private prompt' not in json.dumps(trace)


async def test_explicit_realtime_rejects_inactive_manual_segmentation_until_corrected(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    control._write_settings({'voice_stack_settings': {'openai_realtime': {'turn_mode': 'manual'}},
                             'custom_prompts': {'voice': 'private manual-segmentation prompt'}})
    async with TestClient(TestServer(control._app)) as client:
        view = await (await client.get('/api/settings')).json()
        config = view['voice']['architecture']['architectures'][0]['defaults']
        # Use the actual stored namespace from the endpoint rather than invent a profile.
        response = await client.post('/api/settings', json={'voice': {'architecture': config, 'settings': {'openai_realtime': {'turn_mode': 'manual'}}}})
        assert response.status == 400
        assert response.headers['X-Jarvis-Error-Code'] == 'voice_auto_turn_required'
        trace = read_jsonl_tail(control.journal.trace_path)
        rejected = [event for event in trace if event['kind'] == 'voice.settings.rejected']
        assert len(rejected) == 1
        assert rejected[0]['data'] == {'code': 'voice_auto_turn_required'}
        assert 'private manual-segmentation prompt' not in json.dumps(trace)
        assert config['conversation_model']['model_id'] not in json.dumps(trace)
        assert 'custom_prompts' not in json.dumps(trace)
        response = await client.post('/api/settings', json={'voice': {'architecture': config, 'settings': {'openai_realtime': {'turn_mode': 'auto'}}}})
        assert response.status == 200


def test_browser_renderer_and_draft_preserve_same_mode_and_only_post_explicit_changes(tmp_path, monkeypatch):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node required to execute browser draft functions')
    monkeypatch.delenv('JARVIS_VOICE_ARCH', raising=False)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    data = control._settings_payload(control._settings())
    query = data['voice']['architecture']
    # Preserve a non-default but supported model during explicit same-mode activation.
    query['selection']['config']['conversation_model'] = {
        k: query['architectures'][0]['fields'][0]['options'][1][k] for k in ('provider_id', 'model_id')}
    page = Path('jarvis/runtime/control_center.html').read_text(encoding='utf-8')
    functions = page[page.index('function voiceArchitectureConfig()'):page.index('/* --- onglet CLI')]
    functions += page[page.index('function draftFrom(data)'):page.index('async function openSettings()')]
    functions += page[page.index('async function saveDraft(options)'):page.index("modalSave.addEventListener('click'")]
    script = r'''
const assert=require('node:assert/strict');
const data=JSON.parse(require('node:fs').readFileSync(process.argv[2],'utf8'));
const SET={data,dirty:false},modalSave={};
const esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const renderField=async(field)=>`<input data-stack-field="${field.key}">`;
const authSectionHtml=async()=>'',aecHtml=()=>'',selectOptions=()=>'';
const say=()=>{},renderTab=async()=>{};
let sent;
const api=async(_url,options)=>{sent=JSON.parse(options.body);return data};
''' + functions + r'''
(async()=>{
SET.draft=draftFrom(data);
const original=JSON.stringify(data.voice.architecture.selection.config);
await saveDraft({silent:true});
assert.equal('architecture' in sent.voice,false);
voiceArchitectureChanged('architecture',data.voice.architecture.selection.config.architecture);
assert.equal(JSON.stringify(SET.draft.voice.architecture),original);
await saveDraft({silent:true});
assert.equal(JSON.stringify(sent.voice.architecture),original);
assert.equal('compatibility' in sent.voice.architecture,false);
for(const profile of data.voice.architecture.architectures){
 voiceArchitectureChanged('architecture',profile.id);
 const rendered=await voiceArchitectureHtml();
 for(const field of profile.fields)assert.ok(rendered.includes('architecture_'+field.key));
 if(profile.fields.some(f=>f.key==='idle_timeout_s')){
  assert.ok(!rendered.includes('data-stack-field'));
  assert.ok(rendered.includes('min="5" max="3600"'));
 }
}
assert.equal(JSON.stringify(data.voice.architecture.selection.config),original);
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    path = tmp_path / 'settings-browser.cjs'
    path.write_text(script, encoding='utf-8')
    fixture = tmp_path / 'settings-data.json'
    fixture.write_text(json.dumps(data), encoding='utf-8')
    run = subprocess.run([node, str(path), str(fixture)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr


def test_async_browser_render_does_not_restore_a_previous_panel(tmp_path):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node required to execute browser rendering')
    page = Path('jarvis/runtime/control_center.html').read_text(encoding='utf-8')
    render = page[page.index('async function renderTab()'):page.index('function bindTab()')]
    script = r'''
const assert=require('node:assert/strict');
const SET={tab:'voice'},TABS=[{id:'voice',save:true},{id:'routing',save:true}];
const modalContent={},modalSub={},modalSave={style:{}};
const esc=String,say=()=>{},bindTab=()=>{};
let finish;
const tabVoice=()=>new Promise(resolve=>{finish=resolve});
const tabRouting=async()=>'<new routing panel>';
''' + render + r'''
(async()=>{
const first=renderTab();
SET.tab='routing';
await renderTab();
finish('<old voice panel>');
await first;
assert.equal(modalContent.innerHTML,'<new routing panel>');
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    path = tmp_path / 'settings-render.cjs'
    path.write_text(script, encoding='utf-8')
    run = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
