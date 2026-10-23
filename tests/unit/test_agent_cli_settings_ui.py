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
FIXTURE = (
    ROOT
    / "tasks"
    / "jarvis-settings-model-catalog-ux"
    / "slices"
    / "05-agent-cli-settings-ui"
    / "fixtures"
    / "agent-cli-ui.json"
)


class JsonRequest:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def json(self) -> dict:
        return self.payload


def run_node(tmp_path: Path, data: object, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data_path = tmp_path / "agent-cli-data.json"
    data_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    script = tmp_path / "agent-cli-ui.cjs"
    script.write_text(
        "const fs=require('fs');const data=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
        + source,
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script), str(data_path)], capture_output=True, text=True,
        encoding="utf-8", timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_navigation_fixture_matches_the_sections_and_the_retired_programmatic_ids():
    page = PAGE.read_text(encoding="utf-8")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    registry = (PAGE.parent / "control_center_settings_registry.js").read_text(encoding="utf-8")

    # jarvis-settings-ui-reorganization, Slice 09 : plus aucun onglet de premier niveau, plus d'injecteur.
    assert expected["tabs"] == [] and "\nconst TABS=" not in page
    work = PAGE.with_name("control_center_work.js").read_text(encoding="utf-8")
    assert "TABS.splice" not in work and "TABS.push" not in work
    # Voix (Slice 03), Agent / CLI et Sous-agents (Slice 04), Raccourcis et Apparence (Slice 06), API Keys (Slice 07),
    # Prompts (Slice 08) réhébergés en sections (jarvis-settings-ui-reorganization) : chaque cible est enregistrée.
    sections = (page[page.index("const VOICE_SECTIONS=[") : page.index("function voiceSectionSpec")]
                + page[page.index("const AGENT_SECTIONS=[") : page.index("function agentSectionSpec")]
                + page[page.index("const SUBAGENT_SECTIONS=[") : page.index("function installAgentSettingsSections")]
                + page[page.index("const ARCHITECTURE_SECTION=") : page.index("/* --- Micro & son : périphériques audio")]
                + page[page.index("const SHORTCUTS_SECTION=") : page.index("function renderShortcutsSection")]
                + page[page.index("const CONNECTIONS_SECTION=") : page.index("/* --- `interface_interactions` › Raccourcis")]
                + page[page.index("const PROMPTS_SECTION=") : page.index("/* --- Agent principal et Runtime & CLI")]
                + work[work.index("const THEME_SCENE_SECTION=") : work.index("function installSettingsSection")])
    for _legacy_id, target in expected["rehosted_as_sections"].items():
        assert f"{{id:'{target['section']}',category:'{target['category']}'" in sections, target
    # Slice 09 : la redirection `routing` → `cli` et les anciens ID sans appelant sont retirés ; aucun n'est plus un
    # alias (la table explicite `LEGACY_TAB_ALIASES` du registre ne les porte pas) ni l'ID d'une section.
    table = registry[registry.index("const LEGACY_TAB_ALIASES=Object.freeze({") :]
    table = table[: table.index("});")]
    for retired in expected["retired_programmatic_ids"]:
        assert f"{retired}:" not in table and f"{{id:'{retired}'," not in sections, retired
    assert "function canonicalSettingsTab" not in page
    assert "Aiguillage" not in page


def test_agent_cli_sections_are_in_locked_order_and_advanced_policy_is_disclosed():
    page = PAGE.read_text(encoding="utf-8")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # Slice 07 (jarvis-architecture-agents-settings-editor) : les deux onglets de `agents_models`, dans l'ordre ;
    # Runtime & CLI sous Avancé.
    registered = page[page.index("const AGENT_SECTIONS=[") : page.index("/* --- Micro & son : périphériques audio")]
    labels = re.findall(r"category:'agents_models',order:(\d+),label:'([^']+)'", registered)
    assert len(labels) == 2, labels  # exactement deux onglets : Architecture et Sous-agents
    assert [label for _order, label in sorted(labels, key=lambda item: int(item[0]))] == expected["agent_section_order"]
    assert "{id:'runtime_cli',category:'advanced_diagnostics',group:'runtime_cli',order:30,advanced:true,label:'Runtime & CLI'" in registered
    body = page[page.index("function routingRow(") : page.index("/* --- Micro & son : périphériques audio")]
    assert '<details class="rd" id="routingAdvanced"' in body
    assert "Configuration avancée des sous-agents" in body
    # Le choix se fait en deux temps — un harness, puis un de ses modèles — donc
    # ce qui est retenu est une liste ordonnée, plus une case à cocher par
    # couple. L'invariant tenu ici ne change pas : la section dit ce qu'elle a
    # retenu, dans quel ordre, et pourquoi un candidat n'est pas utilisable.
    assert "unavailable_reason" in body and "rank===0?'préféré'" in body
    assert "data-routing-harness" in body and "data-routing-drop" in body
    builders = page[page.index("function agentBehaviorHtml()") : page.index("/* --- configuration avancée")]
    assert "await " not in builders and "api(" not in builders and "catalog(" not in builders
    # Runtime & CLI porte le technique du CLI, le mode hérité Auto / Dupliqué, les profils et l'inventaire comparatif.
    assert builders.index("${cliTechnicalHtml()}") < builders.index("${delegationModeHtml()}${routingAdvancedShell()}")
    assert '<details class="rd" id="agentCatalogDisclosure">' in builders and 'id="agentCatalog"' in builders


def test_cli_failure_keeps_mode_behavior_and_catalog_shell_visible(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    functions = page[page.index("function cliTechnicalHtml()") : page.index("/* --- configuration avancée")]
    result = run_node(
        tmp_path,
        {},
        """
        const SET={agentSection:'runtime_cli',clis:{ok:false,error:'CLI probe failed',agents:[]},draft:{cli:{agent:'claude'}}};
        const esc=value=>String(value),delegationModeHtml=()=>'<mode>MODE</mode>',behaviorHtml=()=>'<behavior>BEHAVIOR</behavior>',tabAgenda=()=>'<agenda>AGENDA</agenda>',routingAdvancedShell=()=>'<advanced>CLOSED</advanced>';
        """
        + functions
        + "process.stdout.write(JSON.stringify({behavior:agentBehaviorHtml(),runtime:runtimeCliHtml()}));",
    )

    # Une sonde en échec reste locale : Runtime & CLI le dit avec « réessayer » ; le mode hérité, les profils et
    # l'inventaire restent rendus, Comportement aussi.
    runtime = result["runtime"]
    assert "CLI probe failed" in runtime and "data-cli-retry" in runtime
    assert "MODE" in runtime and "CLOSED" in runtime and 'id="agentCatalog"' in runtime
    assert 'data-settings-open="subagents"' in runtime  # le modèle d'un rôle se règle dans l'onglet Sous-agents
    assert "BEHAVIOR" in result["behavior"] and "AGENDA" in result["behavior"]
    assert "<label>Agent piloté</label>" not in functions


def test_runtime_cli_carries_the_technical_fields_and_no_cli_or_model_choice(tmp_path: Path):
    """Slice 07 (jarvis-architecture-agents-settings-editor) : le choix du CLI et du modèle de Core passe par la fenêtre
    du cerveau Core ; Runtime & CLI garde commande, chemin, re-détection, permission (`cli.settings[<CLI>]`)."""
    page = PAGE.read_text(encoding="utf-8")
    functions = page[page.index("function cliTechnicalHtml()") : page.index("function agentBehaviorHtml()")]
    result = run_node(
        tmp_path,
        {},
        """
        const esc=value=>String(value),keyStateFor=()=>'',providerLabel=String,catalogNote=()=>'NOTE',connectionCardId=p=>'connection_'+p;
        const selectOptions=(values,selected,placeholder)=>(placeholder?`<option value="">${placeholder}</option>`:'')+values.map(v=>`<option value="${v.value}">${v.label}</option>`).join('');
        const SET={agentSection:'runtime_cli',catalog:{'anthropic:text':{ok:true,models:[{id:'m1'}]}},
          clis:{agents:[{id:'claude',label:'Claude Code',available:true,version:'9.9',path:'C:/bin/claude.exe',description:'D',model_provider:'anthropic',permission_label:'Permissions',permission_modes:['default','bypass'],docs:'docs'},
                        {id:'codex',label:'Codex',available:false,error:'introuvable',description:'D',model_provider:'openai',permission_modes:[]}]},
          draft:{cli:{agent:'claude',settings:{claude:{model:'m1',command:'claude',permission_mode:'default'}}}}};
        """
        + functions
        + "process.stdout.write(JSON.stringify({runtime:cliTechnicalHtml()}));",
    )

    runtime = result["runtime"]
    assert 'data-cli-field="command"' in runtime and 'data-cli-field="permission_mode"' in runtime
    assert "C:/bin/claude.exe" in runtime and 'id="reprobe"' in runtime and 'data-scope="claude"' in runtime
    assert 'name="clicagent"' not in runtime and 'data-cli-field="model"' not in runtime
    assert 'data-settings-open="architecture"' in runtime and 'data-settings-open="main_agent"' not in runtime
    assert "function cliMainAgentHtml" not in page and "function hydrateCliModel" not in page


@pytest.mark.asyncio
async def test_browser_draft_posts_exact_canonical_shape_and_round_trips(tmp_path: Path, monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path)
    data = json.loads((await control.get_settings(None)).text)
    page = PAGE.read_text(encoding="utf-8")
    draft_source = page[page.index("function draftFrom(data)") : page.index("async function openSettings()")]
    payload = run_node(
        tmp_path,
        data,
        "const SET={};"
        + draft_source
        + "const draft=draftFrom(data);"
        "draft.cli.delegation_mode='auto';"
        "draft.cli.behavior.response_verbosity='balanced';"
        "draft.cli.behavior.politeness_formality='direct';"
        "process.stdout.write(JSON.stringify(draft));",
    )

    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert list(payload["cli"]) == expected["cli_payload_keys"]
    assert list(payload["routing"]) == expected["routing_payload_keys"]
    assert "enabled" not in payload["routing"]

    saved = json.loads((await control.save_settings(JsonRequest(payload))).text)
    assert saved["cli"]["delegation_mode"] == "auto"
    assert saved["cli"]["behavior"]["values"] == {
        "response_verbosity": "balanced",
        "politeness_formality": "direct",
    }
    assert saved["routing"]["policy"] == payload["routing"]["profiles"]


@pytest.mark.asyncio
async def test_agent_controls_render_only_backend_metadata_options(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JARVIS_VOICE_ARCH", raising=False)
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path)
    cli = json.loads((await control.get_settings(None)).text)["cli"]
    page = PAGE.read_text(encoding="utf-8")
    functions = page[page.index("function metadataOptions") : page.index("function cliTechnicalHtml()")]
    result = run_node(
        tmp_path,
        cli,
        "const esc=value=>String(value);"
        "const SET={data:{cli:data},draft:{cli:{delegation_mode:data.delegation_mode,behavior:{...data.behavior.values}}}};"
        + functions
        + "process.stdout.write(JSON.stringify({mode:delegationModeHtml(),behavior:behaviorHtml()}));",
    )

    mode = result["mode"]
    assert [option["label"] for option in cli["delegation_mode_metadata"]["options"]] == [
        label for label in ("Auto", "Dupliqué") if label in mode
    ]
    assert cli["delegation_mode_metadata"]["help"] in mode
    for field in cli["behavior"]["fields"]:
        assert field["label"] in result["behavior"] and field["help"] in result["behavior"]
        assert all(option["label"] in result["behavior"] for option in field["options"])
    assert "fan-out" not in functions and "concise" not in functions


@pytest.mark.asyncio
async def test_backend_metadata_is_escaped_by_the_production_html_escape(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JARVIS_VOICE_ARCH", raising=False)
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path)
    cli = json.loads((await control.get_settings(None)).text)["cli"]
    hostile = json.loads(json.dumps(cli))
    hostile["delegation_mode_metadata"]["options"][0]["label"] = '<img src=x onerror="boom">'
    hostile["behavior"]["fields"][0]["label"] = "<script>boom()</script>"
    hostile["behavior"]["fields"][0]["help"] = 'help "quoted" & unsafe'
    page = PAGE.read_text(encoding="utf-8")
    esc_source = re.search(r"function esc\(v\)\{[^\n]+\}", page)
    assert esc_source
    functions = page[page.index("function metadataOptions") : page.index("function cliTechnicalHtml()")]
    result = run_node(
        tmp_path,
        hostile,
        esc_source.group(0)
        + "const SET={data:{cli:data},draft:{cli:{delegation_mode:data.delegation_mode,behavior:{...data.behavior.values}}}};"
        + functions
        + "process.stdout.write(JSON.stringify(delegationModeHtml()+behaviorHtml()));",
    )

    assert "<script>" not in result and "<img " not in result
    assert "&lt;script&gt;boom()&lt;/script&gt;" in result
    assert "&lt;img src=x onerror=&quot;boom&quot;&gt;" in result
    assert "help &quot;quoted&quot; &amp; unsafe" in result


def test_catalog_mount_is_shared_async_and_has_owned_lifecycle(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    functions = page[page.index("function destroyAgentCatalog()") : page.index("async function runAudioTest()")]
    result = run_node(
        tmp_path,
        {},
        """
        let destroyed=0,loaded=0,refreshed=0,captured=null,refreshHandler=null;
        const host={},refresh={addEventListener:(kind,handler)=>{refreshHandler=handler}};
        const SET={section:'runtime_cli',agentSection:'runtime_cli',agentCatalog:{destroy:()=>{destroyed+=1}}};
        const currentAgentSection=()=>true;
        const $=selector=>selector==='#agentCatalog'?host:selector==='#agentCatalogRefresh'?refresh:null;
        const JarvisCatalog={createCatalogTable:(target,options)=>{
          captured={targetIsHost:target===host,options};
          return {load:()=>{loaded+=1},refresh:()=>{refreshed+=1},destroy:()=>{destroyed+=1}};
        }};
        """
        + functions
        + "mountAgentCatalog(1);refreshHandler();destroyAgentCatalog();"
        "process.stdout.write(JSON.stringify({destroyed,loaded,refreshed,captured,held:SET.agentCatalog}));",
    )

    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))["catalog"]
    assert result["loaded"] == 1 and result["refreshed"] == 1
    assert result["destroyed"] == 2 and result["held"] is None
    assert result["captured"]["targetIsHost"] is True
    assert result["captured"]["options"]["surface"] == expected["surface"]
    assert result["captured"]["options"]["role"] == expected["role"]
    assert "actions" not in result["captured"]["options"]["columns"]
    assert "controller.load();" in functions and "await controller.load()" not in functions


def test_agent_catalog_lifecycle_error_and_accessibility_contracts_are_wired():
    page = PAGE.read_text(encoding="utf-8")
    catalog_module = (ROOT / "jarvis" / "runtime" / "control_center_catalog.js").read_text(encoding="utf-8")

    render = page[page.index("async function renderTab()") : page.index("/* Rappels d'agenda")]
    cleanup = page[page.index("function cleanupSettingsSurface()") : page.index("function renderTabs()")]
    close = page[page.index("function closeSettings()") : page.index("async function saveDraft")]
    sections = page[page.index("const AGENT_SECTIONS=[") : page.index("function bindAgentSection(")]
    assert render.lstrip().startswith("async function renderTab(){\n  cleanupSettingsSurface();")
    assert "destroyAgentCatalog();destroyVoiceCatalog()" in cleanup
    # Slice 07 (jarvis-architecture-agents-settings-editor) : le catalogue est dans Runtime & CLI, monté à l'ouverture
    # de sa divulgation et détruit par le `destroy` de la section.
    assert "bindAgentCatalogDisclosure(revision)}," in sections and "stop:destroyAgentCatalog}," in sections
    assert "destroy(){if(stop)stop();" in sections
    assert "mountAgentCatalog" not in render
    assert "SET.renderRevision=(SET.renderRevision||0)+1" in close
    assert "SET.routingAdvancedOpen=false" in close
    assert "cleanupSettingsSurface();" in close
    assert 'aria-label="Catalogue des modèles de sous-agents"' in page
    assert 'role="search" aria-label="Recherche et tri du catalogue"' in catalog_module
    assert '<th scope="row"' in catalog_module
    assert "@media(max-width:700px)" in page


def test_open_close_race_cannot_publish_or_mount_after_settings_response(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    functions = page[page.index("async function openSettings()") : page.index("async function saveDraft")]
    result = run_node(
        tmp_path,
        {},
        """
        function deferred(){let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}}
        const request=deferred();let rendered=0,destroyed=0,tabs=0;
        const SET={open:false,dirty:false,data:null,capture:null,openGeneration:0,cliGeneration:0,cliModelGeneration:0,routingGeneration:0,voiceGeneration:0,audioGeneration:0,diagnosticGeneration:0,renderRevision:0,routingAdvancedOpen:false};
        const overlay={classList:{add:()=>{},remove:()=>{}}},modalContent={innerHTML:''};
        const api=()=>request.promise,renderTabs=()=>{tabs+=1},renderTab=async()=>{rendered+=1},draftFrom=value=>value;
        const destroyAgentCatalog=()=>{destroyed+=1},destroyVoiceCatalog=()=>{},cleanupSettingsSurface=()=>{destroyAgentCatalog();destroyVoiceCatalog()};
        """
        + functions
        + "(async()=>{const opening=openSettings();await Promise.resolve();closeSettings();request.resolve({shortcuts:{},marker:'late'});await opening;process.stdout.write(JSON.stringify({rendered,destroyed,tabs,data:SET.data,open:SET.open,content:modalContent.innerHTML}));})().catch(error=>{console.error(error);process.exitCode=1});",
    )

    assert result["rendered"] == 0
    assert result["destroyed"] == 1 and result["tabs"] == 1
    assert result["data"] is None and result["open"] is False
    assert "late" not in result["content"]


def test_advanced_policy_is_lazy_local_and_last_render_wins(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    hydrate = page[page.index("async function hydrateRoutingAdvanced") : page.index("/* --- Architecture & Agents (`agents_models`)")]
    result = run_node(
        tmp_path,
        {},
        """
        function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}}
        const calls=[],body={innerHTML:''};let renders=[];
        const SET={open:true,section:'runtime_cli',agentSection:'runtime_cli',renderRevision:7,routingAdvancedOpen:false,routingGeneration:0,routing:null};
        const currentAgentSection=revision=>SET.open&&SET.section===SET.agentSection&&revision===SET.renderRevision;
        const $=()=>body,renderRoutingAdvanced=()=>{renders.push(SET.routing&&SET.routing.marker||SET.routing&&SET.routing.error)};
        const api=()=>{const call=deferred();calls.push(call);return call.promise};
        """
        + hydrate
        + """
        (async()=>{
          await hydrateRoutingAdvanced(7);const closedCalls=calls.length;
          SET.routingAdvancedOpen=true;
          const old=hydrateRoutingAdvanced(7,true),latest=hydrateRoutingAdvanced(7,true);
          calls[1].resolve({ok:true,marker:'NEW'});await latest;
          calls[0].resolve({ok:true,marker:'OLD'});await old;
          const afterRace=SET.routing.marker;
          const failed=hydrateRoutingAdvanced(7,true);calls[2].reject(new Error('advanced offline'));await failed;
          const failedState=SET.routing;
          const recovered=hydrateRoutingAdvanced(7);calls[3].resolve({ok:true,marker:'RECOVERED'});await recovered;
          process.stdout.write(JSON.stringify({closedCalls,afterRace,failedState,final:SET.routing,renders,body:body.innerHTML,calls:calls.length}));
        })().catch(error=>{console.error(error);process.exitCode=1});
        """,
    )

    assert result["closedCalls"] == 0
    assert result["afterRace"] == "NEW" and "OLD" not in result["renders"]
    assert result["failedState"]["ok"] is False and result["failedState"]["error"] == "advanced offline"
    assert result["calls"] == 4 and result["final"]["marker"] == "RECOVERED"
    assert result["renders"][-2:] == ["advanced offline", "RECOVERED"]
    assert 'id="routingRetry"' in page


def test_cli_hydration_retries_locally_without_remounting_catalog_or_accumulating_binds(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    cli_runtime = page[
        page.index("function currentAgentSection(revision)") : page.index("function renderRoutingAdvanced")
    ]
    mount_runtime = page[
        page.index("function destroyAgentCatalog()") : page.index("async function runAudioTest()")
    ]
    result = run_node(
        tmp_path,
        {},
        """
        let apiCalls=0,mounts=0,destroys=0,fullRenders=0,partialRenders=0;
        const boundNodes=[];
        function node(dataset={}){return {dataset,addEventListener(){this.binds=(this.binds||0)+1}}}
        const technical={
          _html:'',radios:[],fields:[],
          replaceNodes(){this.fields=[node({scope:'claude',cliField:'command'})];boundNodes.push(...this.fields)},
          set innerHTML(value){this._html=value;partialRenders+=1;this.replaceNodes()},get innerHTML(){return this._html},
          querySelectorAll(selector){return selector==='[data-cli-field]'?this.fields:[]},
          querySelector(){return null}
        };
        technical.replaceNodes();
        const catalogHost={},refresh={addEventListener(){}};
        const controller={state:{search:'needle',compare:['model-a']},load(){},refresh(){},destroy(){destroys+=1}};
        const SET={open:true,section:'runtime_cli',agentSection:'runtime_cli',renderRevision:9,clis:null,cliGeneration:0,cliModelGeneration:0,catalog:{},agentCatalog:null,draft:{cli:{agent:'claude',settings:{claude:{model:'',command:'claude',permission_mode:'default'}}}}};
        const $=selector=>selector==='#cliTechnical'?technical:selector==='#agentCatalog'?catalogHost:selector==='#agentCatalogRefresh'?refresh:null;
        const cliTechnicalHtml=()=>'<technical></technical>',say=()=>{},saveDraft=async()=>{};
        const api=async()=>{apiCalls+=1;if(apiCalls===1)throw new Error('probe offline');return {ok:true,agents:[{id:'claude',model_provider:'anthropic'}]}};
        const requestCatalog=async()=>({ok:true,models:[{id:'model-a'}]});
        const renderTab=()=>{fullRenders+=1};
        const JarvisCatalog={createCatalogTable:()=>{mounts+=1;return controller}};
        """
        + cli_runtime
        + mount_runtime
        + """
        (async()=>{
          bindCliTechnical(technical,9);mountAgentCatalog(9);
          await hydrateCliAgents(9);
          const failed=SET.clis.error;
          await hydrateCliAgents(9,true);
          process.stdout.write(JSON.stringify({
            apiCalls,mounts,destroys,fullRenders,partialRenders,failed,
            revision:SET.renderRevision,sameController:SET.agentCatalog===controller,
            controllerState:controller.state,bindCounts:boundNodes.map(item=>item.binds||0),
            clisOk:SET.clis.ok,catalog:SET.catalog['anthropic:text']
          }));
        })().catch(error=>{console.error(error);process.exitCode=1});
        """,
    )

    assert result["failed"] == "probe offline" and result["apiCalls"] == 2
    assert result["clisOk"] is True and result.get("catalog") is None  # plus de modèle principal à lister ici (Slice 07)
    assert result["mounts"] == 1 and result["destroys"] == 0
    assert result["sameController"] is True
    assert result["controllerState"] == {"search": "needle", "compare": ["model-a"]}
    assert result["fullRenders"] == 0 and result["revision"] == 9
    assert result["partialRenders"] == 3  # échec, nouvelle sonde, réussite
    assert set(result["bindCounts"]) == {1}


def test_cli_hydration_ignores_a_closed_render(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    cli_hydrate = page[page.index("async function hydrateCliAgents") : page.index("/* Redessiner la section jette le focus")]
    assert "renderTab()" not in cli_hydrate
    result = run_node(
        tmp_path,
        {},
        """
        function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}}
        const cliRequest=deferred();let renders=0;
        const SET={open:true,section:'runtime_cli',agentSection:'runtime_cli',renderRevision:3,clis:null,cliGeneration:0,catalog:{},draft:{cli:{agent:'claude'}}};
        const currentAgentSection=revision=>SET.open&&SET.section===SET.agentSection&&revision===SET.renderRevision;
        const api=()=>cliRequest.promise,renderTab=()=>{renders+=1},renderCliTechnical=()=>{renders+=1};
        """
        + cli_hydrate
        + """
        (async()=>{
          const cli=hydrateCliAgents(3);SET.open=false;cliRequest.reject(new Error('probe failed'));await cli;
          process.stdout.write(JSON.stringify({clis:SET.clis,renders}));
        })().catch(error=>{console.error(error);process.exitCode=1});
        """,
    )

    assert result == {"clis": None, "renders": 0}


@pytest.mark.asyncio
async def test_combined_agent_save_preserves_profiles_unknown_candidate_and_voice_audio(
    tmp_path: Path, monkeypatch,
):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path)
    await control.save_settings(JsonRequest({
        "cli": {
            "delegation_mode": "auto",
            "behavior": {
                "response_verbosity": "balanced",
                "politeness_formality": "courteous",
            },
        },
        "routing": {"profiles": {"code": {
            "enabled": True,
            "candidates": [
                {"agent": "claude", "model": "saved-but-disappeared"},
                {"agent": "codex", "model": "unknown-model"},
            ],
            "allow_general_fallback": False,
        }}},
        "voice": {"settings": {"openai_realtime": {"voice": "ash"}}},
        "audio": {"input_device": "4", "output_device": "7", "active_timeout_s": 42},
    }))
    stored_path = control.settings_path
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    stored["future_extension"] = {"keep": True}
    stored_path.write_text(json.dumps(stored), encoding="utf-8")

    data = json.loads((await control.get_settings(None)).text)
    page = PAGE.read_text(encoding="utf-8")
    draft_source = page[page.index("function draftFrom(data)") : page.index("async function openSettings()")]
    payload = run_node(
        tmp_path,
        data,
        "const SET={};"
        + draft_source
        + "const draft=draftFrom(data);"
        "draft.cli.delegation_mode='duplicate';"
        "draft.cli.behavior.response_verbosity='detailed';"
        "draft.cli.behavior.politeness_formality='formal';"
        "process.stdout.write(JSON.stringify(draft));",
    )

    assert "enabled" not in payload["routing"]
    await control.save_settings(JsonRequest(payload))
    final = json.loads(stored_path.read_text(encoding="utf-8"))
    assert final["agent_routing"]["enabled"] is False
    code_profile = final["agent_routing"]["profiles"]["code"]
    assert code_profile["enabled"] is True
    assert code_profile["candidates"] == [
        {"agent": "claude", "model": "saved-but-disappeared"},
        {"agent": "codex", "model": "unknown-model"},
    ]
    assert code_profile["allow_general_fallback"] is False
    assert final["agent_behavior"] == {
        "response_verbosity": "detailed",
        "politeness_formality": "formal",
    }
    assert final["voice_stack_settings"]["openai_realtime"]["voice"] == "ash"
    assert final["audio_input_device"] == "4"
    assert final["audio_output_device"] == "7"
    assert final["active_timeout_s"] == "42"
    assert final["future_extension"] == {"keep": True}


@pytest.mark.asyncio
async def test_agent_cli_save_payload_is_frozen_key_by_key(tmp_path: Path, monkeypatch):
    """Slice 04 (jarvis-settings-ui-reorganization) : Agent / CLI éclaté en sections, la charge d'enregistrement ne
    change pas d'une clé. Clés et sous-clés figées ; toute valeur vient du serveur et revient telle quelle."""
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path)
    data = json.loads((await control.get_settings(None)).text)
    page = PAGE.read_text(encoding="utf-8")
    draft_source = page[page.index("function draftFrom(data)") : page.index("async function openSettings()")]
    payload = run_node(tmp_path, data, "const SET={};" + draft_source + "process.stdout.write(JSON.stringify(draftFrom(data)));")

    assert list(payload) == ["voice", "cli", "routing", "audio", "agenda_reminders"]
    cli = payload["cli"]
    assert list(cli) == ["agent", "settings", "delegation_mode", "behavior"]
    assert cli["agent"] == data["cli"]["agent"] and cli["delegation_mode"] == data["cli"]["delegation_mode"]
    assert sorted(cli["settings"]) == ["claude", "codex"]
    for agent, values in cli["settings"].items():
        assert sorted(values) == ["command", "model", "permission_mode"], agent
    assert cli["settings"] == data["cli"]["settings"]
    assert sorted(cli["behavior"]) == ["politeness_formality", "response_verbosity"]
    assert cli["behavior"] == data["cli"]["behavior"]["values"]
    assert list(payload["routing"]) == ["profiles"] and payload["routing"]["profiles"] == data["routing"]["policy"]
    assert sorted(payload["routing"]["profiles"]) == ["code", "desktop", "fast", "general"]
    for profile, entry in payload["routing"]["profiles"].items():
        assert sorted(entry) == ["allow_general_fallback", "candidates", "enabled", "profile"], profile
    assert payload["agenda_reminders"] == {f["key"]: data["agenda_reminders"][f["key"]] for f in data["agenda_reminders"]["fields"]}
    assert payload["audio"] == data["audio"]
