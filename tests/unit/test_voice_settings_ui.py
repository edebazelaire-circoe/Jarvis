from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import ControlCenter


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"
FIXTURE = ROOT / "tasks" / "jarvis-settings-model-catalog-ux" / "slices" / "06-voice-settings-tabs" / "fixtures" / "voice-settings-ui.json"


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


def run_node(tmp_path: Path, data: object, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data_path = tmp_path / "voice-ui-data.json"
    data_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    script = tmp_path / "voice-ui.cjs"
    script.write_text(
        "const data=JSON.parse(require('node:fs').readFileSync(process.argv[2],'utf8'));" + source,
        encoding="utf-8",
    )
    result = subprocess.run(
        [node, str(script), str(data_path)], capture_output=True, text=True,
        encoding="utf-8", timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ControlCenter:
    for name in ("JARVIS_VOICE_ARCH", "JARVIS_VOICE_STACK", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path)


def voice_renderer_source(page: str) -> str:
    return page[page.index("function voiceArchitectureConfig()") : page.index("/* --- onglet Agent / CLI")]


async def test_every_backend_voice_category_and_option_is_rendered_exactly_once_and_escaped(
    control: ControlCenter, tmp_path: Path,
):
    data = json.loads((await control.get_settings(None)).text)
    data["voice"]["option_metadata"][0]["label"] = '<img src=x onerror="boom">'
    page = PAGE.read_text(encoding="utf-8")
    result = run_node(
        tmp_path,
        data,
        r"""
        const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        const SET={data,voiceTab:'architecture',voiceCatalogRole:'realtime',catalog:{},devices:null,architectureDirty:false,restartNotice:false,
          shortcuts:data.shortcuts,draft:{voice:{stack:data.voice.stack,arch:data.voice.arch||'',settings:JSON.parse(JSON.stringify(data.voice.settings)),authorization:{},architecture:JSON.parse(JSON.stringify(data.voice.architecture.selection.config))},audio:{...data.audio}}};
        const authValues=a=>({...a.stored,...(a.verifier_settings&&a.verifier_settings.stored||{}),...SET.draft.voice.authorization});
        const authVerdictHtml=()=>'',verifierHtml=()=>'',authEffectiveHtml=()=>'',aecHtml=()=>'',deviceOptions=()=>'';
        """
        + voice_renderer_source(page)
        + r"""
        (async()=>{const rendered={};for(const category of data.voice.categories){SET.voiceTab=category.id;rendered[category.id]=await voicePanelHtml()}
          SET.draft.voice.settings.openai_realtime.turn_mode='manual';const hiddenVad=voiceOptionHtml(voiceOption('openai.vad_type'));
          SET.draft.voice.authorization.conversation_mode='solo_owner';const soloVerification=voiceOptionHtml(voiceOption('speaker_verification'));
          const shell=await tabVoice();process.stdout.write(JSON.stringify({rendered,shell,hiddenVad,soloVerification}));})().catch(error=>{console.error(error);process.exitCode=1});
        """,
    )

    categories = data["voice"]["categories"]
    for category in categories:
        expected = [item["id"] for item in data["voice"]["option_metadata"] if item["category"] == category["id"]]
        html = result["rendered"][category["id"]]
        actual = []
        for identifier in expected:
            marker = f'data-voice-option="{identifier}"'
            assert html.count(marker) == 1, (category["id"], identifier)
            actual.append(identifier)
        assert len(actual) == len(expected)
        html_ids = re.findall(r'\sid="([^"]+)"', html)
        assert len(html_ids) == len(set(html_ids)), category["id"]
    assert "<img " not in result["rendered"]["architecture"]
    assert "&lt;img src=x onerror=&quot;boom&quot;&gt;" in result["rendered"]["architecture"]
    assert "settings_fields" not in json.dumps(result)
    assert result["shell"].count('role="tab"') == len(categories)
    assert 'role="tablist"' in result["shell"] and 'role="tabpanel"' in result["shell"]
    assert 'data-voice-option="openai.vad_type" hidden' in result["hiddenVad"]
    assert 'value="enforce"' in result["soloVerification"]
    assert 'value="shadow"' not in result["soloVerification"]


def test_voice_subtab_keyboard_navigation_updates_state_focus_and_aria(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    update = page[page.index("function updateVoiceTabs()") : page.index("async function renderVoicePanel")]
    binding = page[page.index("function bindVoiceSurface") : page.index("function voiceChanged")]
    result = run_node(
        tmp_path,
        {},
        r"""
        const ids=['architecture','conversation','turn_taking','models','audio','advanced','diagnostic'];let renders=[],focused='';
        const buttons=ids.map(id=>({dataset:{voiceTab:id},handlers:{},setAttribute(k,v){this[k]=v},addEventListener(k,v){this.handlers[k]=v},focus(){focused=id}}));
        const SET={voiceTab:'architecture',data:{voice:{categories:ids.map(id=>({id}))}}};
        const document={querySelectorAll:()=>buttons};
        const $=selector=>buttons.find(button=>selector===`#voiceTab_${button.dataset.voiceTab}`);
        const renderVoicePanel=async revision=>{renders.push([revision,SET.voiceTab])},bindVoicePanel=()=>{},mountVoiceCatalog=()=>{};
        """
        + update
        + binding
        + r"""
        (async()=>{bindVoiceSurface(12);let prevented=false;buttons[0].handlers.keydown({key:'End',preventDefault(){prevented=true}});await Promise.resolve();await Promise.resolve();
          process.stdout.write(JSON.stringify({voiceTab:SET.voiceTab,focused,prevented,renders,selected:buttons.map(item=>item['aria-selected']),indexes:buttons.map(item=>item.tabIndex)}));})().catch(error=>{console.error(error);process.exitCode=1});
        """,
    )

    assert result["voiceTab"] == "diagnostic" and result["focused"] == "diagnostic"
    assert result["prevented"] is True and result["renders"] == [[12, "diagnostic"]]
    assert result["selected"][-1] == "true" and result["indexes"][-1] == 0


def test_voice_catalog_has_backend_roles_owned_lifecycle_and_preserved_per_role_state(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    source = page[page.index("function destroyVoiceCatalog()") : page.index("function updateVoiceTabs()")]
    result = run_node(
        tmp_path,
        {},
        r"""
        let creates=[],destroys=0,loads=0;const host={};
        const SET={open:true,tab:'voice',voiceTab:'models',renderRevision:4,voiceCatalogRole:'realtime',voiceCatalogMountedRole:null,voiceCatalogStates:{},voiceCatalog:null};
        const currentVoicePanel=()=>true,$=()=>host;
        const JarvisCatalog={createCatalogTable:(_host,options)=>{creates.push(options);return {state:{query:'',sort:'name-asc',filters:{},selection:new Set()},render(){},load(){loads+=1},destroy(){destroys+=1}}}};
        """
        + source
        + r"""
        mountVoiceCatalog(4);SET.voiceCatalog.state.query='realtime search';SET.voiceCatalog.state.selection.add('m1');
        SET.voiceCatalogRole='transcription';mountVoiceCatalog(4);SET.voiceCatalog.state.query='transcription search';destroyVoiceCatalog();
        SET.voiceCatalogRole='realtime';mountVoiceCatalog(4);
        process.stdout.write(JSON.stringify({creates,destroys,loads,state:{query:SET.voiceCatalog.state.query,selection:[...SET.voiceCatalog.state.selection]},mounted:SET.voiceCatalogMountedRole}));
        """,
    )

    assert [item["role"] for item in result["creates"]] == ["realtime", "transcription", "realtime"]
    assert all(item["surface"] == "voice" and "actions" not in item["columns"] for item in result["creates"])
    assert result["destroys"] == 2 and result["loads"] == 3
    assert result["state"] == {"query": "realtime search", "selection": ["m1"]}
    assert result["mounted"] == "realtime"


def test_audio_and_diagnostic_fetches_are_local_retryable_and_stale_safe(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    audio = page[page.index("async function hydrateAudioDevices") : page.index("async function hydrateVoiceDiagnostics")]
    diagnostic = page[page.index("async function hydrateVoiceDiagnostics") : page.index("async function runAudioTest")]
    result = run_node(
        tmp_path,
        {},
        r"""
        function deferred(){let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}}
        let calls=0,renders=0;const late=deferred(),status={textContent:''};
        const draft={voice:{settings:{openai_realtime:{voice:'ash'}}},audio:{active_timeout_s:'0'}};
        const SET={open:true,tab:'voice',voiceTab:'audio',renderRevision:5,devices:null,audioGeneration:0,diagnosticGeneration:0,voiceDiagnosticError:'',data:{voice:{marker:'old'}},draft};
        const currentVoicePanel=(revision,category=SET.voiceTab)=>SET.open&&SET.tab==='voice'&&revision===SET.renderRevision&&category===SET.voiceTab;
        const $=()=>status,renderVoicePanel=()=>{renders+=1};
        const api=async path=>{calls+=1;if(path==='/api/audio/devices'&&calls===1)throw new Error('audio offline');if(path==='/api/audio/devices'&&calls===2)return {ok:true,inputs:[],outputs:[]};return late.promise};
        """
        + audio
        + diagnostic
        + r"""
        (async()=>{await hydrateAudioDevices(5);const failed=SET.devices;await hydrateAudioDevices(5,true);const recovered=SET.devices;
          SET.voiceTab='diagnostic';const before=JSON.stringify(SET.draft);const refresh=hydrateVoiceDiagnostics(5);SET.voiceTab='models';late.resolve({voice:{marker:'late'}});await refresh;
          process.stdout.write(JSON.stringify({failed,recovered,calls,renders,draftSame:before===JSON.stringify(SET.draft),voice:SET.data.voice}));})().catch(error=>{console.error(error);process.exitCode=1});
        """,
    )

    assert result["failed"]["error"] == "audio offline" and result["recovered"]["ok"] is True
    assert result["calls"] == 3 and result["renders"] == 2
    assert result["draftSame"] is True and result["voice"] == {"marker": "old"}


def test_audio_device_renderer_preserves_missing_and_system_default_choices(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    source = page[page.index("function deviceOptions") : page.index("/* --- onglet API Keys")]
    result = run_node(
        tmp_path,
        {},
        "const esc=value=>String(value);" + source
        + "process.stdout.write(JSON.stringify({missing:deviceOptions([{id:1,name:'Mic'}],'9',1),empty:deviceOptions([{id:1,name:'Mic'}],'',1)}));",
    )

    assert "Périphérique indisponible (#9)" in result["missing"]
    assert 'value="9" selected' in result["missing"]
    assert 'value="" selected' in result["empty"] and "Système par défaut (Mic)" in result["empty"]


@pytest.mark.asyncio
async def test_provider_model_select_hydrates_locally_retries_ignores_stale_and_persists(
    control: ControlCenter, tmp_path: Path,
):
    data = json.loads((await control.get_settings(None)).text)
    meta = next(item for item in data["voice"]["option_metadata"] if item["id"] == "openai.model")
    page = PAGE.read_text(encoding="utf-8")
    request = page[page.index("async function requestCatalog") : page.index("async function catalog")]
    hydration = page[page.index("function voiceChanged") : page.index("function bindVoicePanel")]
    result = run_node(
        tmp_path,
        {"settings": data, "meta": meta},
        r"""
        const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        const meta=data.meta,settings=data.settings;settings.voice.settings.openai_realtime.model='saved-removed';
        const SET={open:true,tab:'voice',voiceTab:'models',renderRevision:5,voiceGeneration:7,voiceModelSources:{},voiceModelGenerations:{},voiceCatalog:{marker:'same'},data:settings,
          devices:null,architectureDirty:false,shortcuts:settings.shortcuts,draft:{voice:{stack:settings.voice.stack,arch:settings.voice.arch,settings:JSON.parse(JSON.stringify(settings.voice.settings)),authorization:{},architecture:settings.voice.architecture.selection.config},audio:{...settings.audio}}};
        const authValues=()=>({}),authDraftAfterChange=(draft,key,value)=>({...draft,[key]:value}),say=()=>{};
        const authVerdictHtml=()=>'',verifierHtml=()=>'',authEffectiveHtml=()=>'',aecHtml=()=>'',deviceOptions=()=>'';
        const providerLabel=value=>value,catalogNote=(value,provider)=>`<span>${provider}:${value.source}</span>`;
        const currentVoicePanel=(revision,category=SET.voiceTab)=>SET.open&&SET.tab==='voice'&&SET.voiceTab===category&&revision===SET.renderRevision;
        const field={html:'',set outerHTML(value){this.html=value},get outerHTML(){return this.html},querySelector(){return null}};
        const $=()=>field;
        function deferred(){let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}}
        const old=deferred(),calls=[];let call=0;
        const api=async path=>{calls.push(path);call+=1;if(call===1)throw new Error('catalogue hors ligne');if(call===2)return old.promise;return {ok:true,source:'live',models:[{id:'new-model',label:'Nouveau'}]}};
        """
        + request
        + voice_renderer_source(page)
        + hydration
        + r"""
        (async()=>{const controller=SET.voiceCatalog;await hydrateVoiceModel(meta,5);const failed=field.html;
          const stale=hydrateVoiceModel(meta,5,true);const fresh=hydrateVoiceModel(meta,5,true);await fresh;
          old.resolve({ok:true,source:'live',models:[{id:'old-model',label:'Ancien'}]});await stale;
          const finalHtml=field.html;voiceChanged({dataset:{voiceMeta:meta.id,voicePersistence:meta.persistence},type:'select-one',value:'new-model'},5);
          process.stdout.write(JSON.stringify({failed,finalHtml,calls,value:SET.draft.voice.settings.openai_realtime.model,sameController:controller===SET.voiceCatalog,state:SET.voiceModelSources[meta.id]}));
        })().catch(error=>{console.error(error);process.exitCode=1});
        """,
    )

    assert "catalogue hors ligne" in result["failed"] and "réessayer" in result["failed"]
    assert "new-model" in result["finalHtml"] and "old-model" not in result["finalHtml"]
    assert "saved-removed (conservé — indisponible)" in result["finalHtml"]
    assert result["calls"] == [
        "/api/models?provider=openai&role=realtime",
        "/api/models?provider=openai&role=realtime&refresh=1",
        "/api/models?provider=openai&role=realtime&refresh=1",
    ]
    assert result["value"] == "new-model" and result["sameController"] is True
    assert result["state"]["result"]["models"][0]["id"] == "new-model"


@pytest.mark.asyncio
async def test_models_panel_hydrates_only_the_three_provider_catalog_selects(
    control: ControlCenter, tmp_path: Path,
):
    data = json.loads((await control.get_settings(None)).text)
    page = PAGE.read_text(encoding="utf-8")
    request = page[page.index("async function requestCatalog") : page.index("async function catalog")]
    model_binding = page[page.index("function bindVoiceModelField") : page.index("async function hydrateAudioDevices")]
    result = run_node(
        tmp_path,
        data,
        r"""
        const SET={open:true,tab:'voice',voiceTab:'models',renderRevision:9,voiceGeneration:3,voiceModelSources:{},voiceModelGenerations:{},data};
        const panel={querySelectorAll:()=>[],querySelector:()=>null};
        const $=selector=>selector==='#voicePanel'?panel:null;
        const currentVoicePanel=(revision,category=SET.voiceTab)=>SET.open&&SET.tab==='voice'&&SET.voiceTab===category&&revision===SET.renderRevision;
        const voiceOptions=category=>(data.voice.option_metadata||[]).filter(item=>item.category===category&&item.destination===`voice.${category}`);
        const voiceOptionId=meta=>'voiceOption_'+String(meta.id).replace(/[^a-zA-Z0-9_-]/g,'_');
        const calls=[];const api=async path=>{calls.push(path);return {ok:true,source:'live',models:[]}};
        const destroyVoiceCatalog=()=>{throw new Error('catalog controller touched')},mountVoiceCatalog=()=>{throw new Error('catalog controller remounted')};
        """
        + request
        + model_binding
        + r"""
        (async()=>{const catalogSelects=voiceOptions('models').filter(item=>item.type==='catalog-select');
          const hydrated=catalogSelects.filter(voiceProviderModelSource).map(item=>item.id);bindVoicePanel(9);
          await Promise.resolve();await Promise.resolve();
          process.stdout.write(JSON.stringify({all:catalogSelects.map(item=>({id:item.id,source:item.source,persistence:item.persistence})),hydrated,calls}));
        })().catch(error=>{console.error(error);process.exitCode=1});
        """,
    )

    assert len(result["all"]) == 6
    assert result["hydrated"] == ["openai.model", "openai.transcription_model", "gemini.model"]
    assert result["calls"] == [
        "/api/models?provider=openai&role=realtime",
        "/api/models?provider=openai&role=transcription",
        "/api/models?provider=google&role=realtime",
    ]
    assert all("registry" not in call and "undefined" not in call for call in result["calls"])


@pytest.mark.asyncio
async def test_diagnostic_records_are_authoritative_once_and_use_effective_owner_profile(
    control: ControlCenter, tmp_path: Path,
):
    data = json.loads((await control.get_settings(None)).text)
    profile = "C:/effective/owner-profile.json"
    data["voice"]["authorization"]["status"] = "diagnostic-truth"
    data["voice"]["authorization"]["verifier_settings"]["effective"]["owner_profile_path"] = profile
    page = PAGE.read_text(encoding="utf-8")
    result = run_node(
        tmp_path,
        data,
        r"""
        const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        const SET={data,voiceTab:'diagnostic',voiceCatalogStates:{},voiceModelSources:{},devices:null,architectureDirty:false,shortcuts:data.shortcuts,
          draft:{voice:{stack:data.voice.stack,arch:data.voice.arch,settings:data.voice.settings,authorization:{},architecture:data.voice.architecture.selection.config},audio:data.audio}};
        const authValues=()=>({}),authVerdictHtml=()=>'<b>DUPLICATE_AUTH</b>',verifierHtml=()=>'<b>DUPLICATE_VERIFIER</b>',authEffectiveHtml=()=>'<b>DUPLICATE_EFFECTIVE</b>',aecHtml=()=>'<b>DUPLICATE_AEC</b>',deviceOptions=()=>'',catalogNote=()=>'';
        """
        + voice_renderer_source(page)
        + r"""
        const records=voiceOptions('diagnostic'),html=voiceDiagnosticHtml(records);
        process.stdout.write(JSON.stringify({html,ids:records.map(item=>item.id)}));
        """,
    )

    html = result["html"]
    assert profile in html and html.count(profile) == 1
    assert html.count("diagnostic-truth") == 1
    assert "DUPLICATE_" not in html
    for identifier in result["ids"]:
        assert html.count(f'data-voice-option="{identifier}"') == 1


@pytest.mark.asyncio
async def test_audio_empty_and_partial_hardware_are_explicit_and_not_actionable(
    control: ControlCenter, tmp_path: Path,
):
    data = json.loads((await control.get_settings(None)).text)
    page = PAGE.read_text(encoding="utf-8")
    result = run_node(
        tmp_path,
        data,
        r"""
        const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        const SET={data,voiceTab:'audio',voiceModelSources:{},architectureDirty:false,shortcuts:data.shortcuts,
          draft:{voice:{stack:data.voice.stack,arch:data.voice.arch,settings:data.voice.settings,authorization:{},architecture:data.voice.architecture.selection.config},audio:data.audio}};
        const authValues=()=>({}),authVerdictHtml=()=>'',verifierHtml=()=>'',authEffectiveHtml=()=>'',aecHtml=()=>'',catalogNote=()=>'';
        const deviceOptions=(items)=>items.map(item=>`<option value="${item.id}">${item.name}</option>`).join('');
        """
        + voice_renderer_source(page)
        + r"""
        (async()=>{const records=voiceOptions('audio');const render=async state=>{SET.devices=state;return await voicePanelHtml()};
          process.stdout.write(JSON.stringify({empty:await render({ok:true,inputs:[],outputs:[]}),inputOnly:await render({ok:true,inputs:[{id:'mic',name:'Mic'}],outputs:[]}),outputOnly:await render({ok:true,inputs:[],outputs:[{id:'out',name:'Out'}]}),full:await render({ok:true,inputs:[{id:'mic',name:'Mic'}],outputs:[{id:'out',name:'Out'}]})}));
        })().catch(error=>{console.error(error);process.exitCode=1});
        """,
    )

    assert "Aucun périphérique d’entrée détecté" in result["empty"]
    assert "Aucun périphérique de sortie détecté" in result["empty"]
    assert result["empty"].count('id="audioRetry"') == 1
    assert result["empty"].count('disabled aria-disabled="true"') == 3
    assert "Aucun périphérique de sortie détecté" in result["inputOnly"]
    assert "Aucun périphérique d’entrée détecté" not in result["inputOnly"]
    assert 'id="testAudio" disabled aria-disabled="true"' in result["inputOnly"]
    assert "Aucun périphérique d’entrée détecté" in result["outputOnly"]
    assert "Aucun périphérique de sortie détecté" not in result["outputOnly"]
    assert 'id="testAudio" disabled aria-disabled="true"' in result["outputOnly"]
    assert 'id="testAudio" disabled' not in result["full"] and 'id="audioRetry"' not in result["full"]


def test_wake_shortcut_waits_for_rerender_and_confirms_on_the_current_hint(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    source = page[page.index("function startCapture") : page.index("/* --- ouverture, enregistrement")]
    result = run_node(
        tmp_path,
        {},
        r"""
        const GLOBAL_KEY_NAMES={};let listener=null,posts=[],renders=0;
        const oldHint={textContent:''},newHint={textContent:''};let currentHint=oldHint;
        const SET={capture:null,shortcuts:null};const $=()=>currentHint;
        const window={addEventListener:(_name,fn)=>{listener=fn},removeEventListener:()=>{}};
        const api=async(path,options)=>{posts.push({path,body:JSON.parse(options.body)});return {values:{wake_toggle:'f10'}}};
        const renderTab=async()=>{renders+=1;currentHint=newHint};
        const button={textContent:'F9',dataset:{scope:'global',shortcut:'wake_toggle'},classList:{add(){},remove(){}}};
        """
        + source
        + r"""
        (async()=>{startCapture(button);await listener({key:'F10',ctrlKey:false,altKey:false,metaKey:false,preventDefault(){},stopPropagation(){}});
          process.stdout.write(JSON.stringify({posts,renders,old:oldHint.textContent,current:newHint.textContent,shortcut:SET.shortcuts.values.wake_toggle}));
        })().catch(error=>{console.error(error);process.exitCode=1});
        """,
    )

    assert result["posts"] == [{"path": "/api/shortcuts", "body": {"shortcuts": {"wake_toggle": "f10"}}}]
    assert result["renders"] == 1 and result["current"] == "Raccourci enregistré."
    assert result["shortcut"] == "f10"


@pytest.mark.asyncio
async def test_voice_categories_round_trip_without_losing_inactive_stack_audio_or_wake(
    control: ControlCenter,
):
    data = json.loads((await control.get_settings(None)).text)
    duplex = next(item for item in data["voice"]["architecture"]["architectures"] if item["id"] == "duplex")
    settings = json.loads(json.dumps(data["voice"]["settings"]))
    settings["openai_realtime"].update({"voice": "ash", "noise_reduction": "near_field", "turn_mode": "auto"})
    settings["gemini_live"].update({"voice": "Zephyr", "turn_mode": "auto"})
    await control.save_settings(JsonRequest({
        "voice": {
            "stack": "gemini_live", "arch": "legacy", "architecture": duplex["defaults"],
            "settings": settings,
            "authorization": {"conversation_mode": "open_room", "speaker_verification": "off", "owner_threshold": 0.5},
        },
        "audio": {"input_device": "", "output_device": "", "active_timeout_s": "0"},
    }))
    await control.save_shortcuts(JsonRequest({"shortcuts": {"wake_toggle": "f10"}}))

    reloaded = json.loads((await control.get_settings(None)).text)
    assert reloaded["voice"]["stack"] == "gemini_live" and reloaded["voice"]["arch"] == "legacy"
    assert reloaded["voice"]["architecture"]["selection"]["config"] == duplex["defaults"]
    assert reloaded["voice"]["settings"]["openai_realtime"]["voice"] == "ash"
    assert reloaded["voice"]["settings"]["openai_realtime"]["noise_reduction"] == "near_field"
    assert reloaded["voice"]["settings"]["gemini_live"]["voice"] == "Zephyr"
    assert reloaded["audio"] == {"input_device": "", "output_device": "", "active_timeout_s": "0"}
    assert reloaded["shortcuts"]["values"]["wake_toggle"] == "f10"


def test_top_navigation_has_no_config_and_wake_is_not_duplicated_in_shortcuts():
    page = PAGE.read_text(encoding="utf-8")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    tabs = page[page.index("const TABS=") : page.index("const SET=")]
    shortcuts = page[page.index("function tabShortcuts()") : page.index("/* --- rendu et liaisons")]
    work = PAGE.with_name("control_center_work.js").read_text(encoding="utf-8")

    assert f"id:'{fixture['removed_top_tab']}'" not in tabs
    assert all(f"label:'{label}'" in tabs for label in fixture["top_tabs"] if label != "Apparence")
    assert "{id:'appearance',label:'Apparence',save:false}" in work
    assert "item.id!=='wake_toggle'" in shortcuts
    assert "Voix → Tours &amp; interruptions" in shortcuts
    assert "function tabConfig" not in page
