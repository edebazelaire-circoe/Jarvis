"""Onglet « Plugins externes » du dialogue MCP (generic-mcp-plugin-runtime, Slice 06), exécuté par node.

Le module servi à la page (`jarvis/runtime/control_center_mcp_plugins.js`) est
exécuté tel quel contre des réponses RÉELLES : une vraie chaîne Control Center
→ Core (`LocalProtocolServer`, connecteur scripté, coffre factice) produit les
listes, les connexions (200, 202 OAuth, refus codés), le catalogue fusionné et
le descripteur d'un outil de plugin ; rien n'est écrit à la main. Ce que ces
tests prouvent (`docs/mcp/plugins.md` §9, ARCH §10.2) :

- cartes : icône ou lettre, nom, hôte, connexion + accès, interrupteur
  (`role=switch`, `aria-checked`), nombre d'outils, « Gérer », dernière erreur ;
- ajout par URL → création → connexion ; OAuth : nouvel onglet `noopener,noreferrer`,
  attente relue toutes les 2 s, 5 min au plus, puis dite ;
- accès manuel (Bearer / en-tête) : champ mot de passe, valeur envoyée une
  seule fois dans le corps du `PUT`, jamais gardée, jamais re-rendue ;
- activer/désactiver, déconnecter, supprimer (confirmé), relecture de Core ;
- outils : lignes et détail rendus par l'inspecteur (client en lecture seule) ;
- erreurs : codes stables traduits, Core absent dit avec « Réessayer » ;
- clavier : onglets du dialogue aux flèches, Échap revient d'un cran ;
- aucune saisie effacée par un rendu d'arrière-plan ;
- aucun nom d'outil, de serveur ni de fournisseur dans le module.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.domain.mcp_plugins import McpErrorCode
from jarvis.runtime import mcp_catalog
from jarvis.runtime.control_center import MCP_PLUGINS_SCRIPT_MARKER, ControlCenter
from tests.fakes.scripted_mcp_connector import ScriptedConnector
from tests.unit.test_control_center_mcp_plugins_api import Chain

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_mcp_plugins.js"
INSPECTOR = ROOT / "jarvis" / "runtime" / "control_center_mcp_inspector.js"
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"
SENTINEL = "SENTINEL-SECRET-7f3a"


# ----------------------------------------------------------------- harnais

def run_node(tmp_path: Path, source: str, data: object = None) -> object:
    """Exécuter `source` avec le module sous `P`, l'inspecteur sous `I`, les données sous `D`."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data_file = tmp_path / "mcpp-data.json"
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    script = tmp_path / "mcpp-test.cjs"
    script.write_text(
        f"const MODULE_PATH={json.dumps(str(MODULE))};\n"
        f"const INSPECTOR_PATH={json.dumps(str(INSPECTOR))};\n"
        "const I=require(INSPECTOR_PATH);\n"
        "const P=require(MODULE_PATH);\n"
        f"const D=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data_file))},'utf8'));\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const tick=()=>new Promise(r=>setImmediate(r));\n"
        "const settle=async()=>{for(let i=0;i<80;i++)await tick()};\n"
        "(async()=>{" + source + "})().then(value=>out(value===undefined?null:value))"
        ".catch(e=>{process.stderr.write(String(e&&e.stack||e));process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8",
                               timeout=60, check=False)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture(scope="module")
def api(tmp_path_factory) -> dict:
    """Réponses réelles du Control Center devant un vrai Core, à chaque état d'un plugin."""

    root = tmp_path_factory.mktemp("mcpp")
    connector = ScriptedConnector("ok", McpErrorCode.REAUTHORIZATION_REQUIRED, McpErrorCode.REMOTE_UNREACHABLE,
                                  "authorize", "ok", "ok")

    async def collect() -> dict:
        out: dict = {}
        async with Chain(root, connector) as chain:
            async def call(method, path, body=None):
                status, payload, _ = await (chain.call(method, path, json=body) if body is not None
                                            else chain.call(method, path))
                return [status, payload]

            out["empty"] = await call("GET", "/api/mcp/plugins")
            out["created"] = await call("POST", "/api/mcp/plugins", {"endpoint": "https://plugins.example.com/mcp"})
            out["created_list"] = await call("GET", "/api/mcp/plugins")
            out["connected"] = await call("POST", "/api/mcp/plugins/plugins/connect", {})
            out["connected_list"] = await call("GET", "/api/mcp/plugins")
            out["catalog"] = await call("GET", "/api/mcp/tools")
            out["detail"] = await call("GET", "/api/mcp/tools/plugins/search")
            out["b_created"] = await call("POST", "/api/mcp/plugins", {"endpoint": "https://b.example.com/mcp"})
            out["b_refused"] = await call("POST", "/api/mcp/plugins/b/connect", {})
            out["b_list"] = await call("GET", "/api/mcp/plugins")
            out["b_credential"] = await call("PUT", "/api/mcp/plugins/b/credential",
                                             {"strategy": "bearer", "value": SENTINEL})
            await call("POST", "/api/mcp/plugins", {"endpoint": "https://c.example.com/mcp"})
            out["c_refused"] = await call("POST", "/api/mcp/plugins/c/connect", {})
            await call("POST", "/api/mcp/plugins", {"endpoint": "https://d.example.com/mcp"})
            out["d_created_list"] = await call("GET", "/api/mcp/plugins")
            out["d_authorizing"] = await call("POST", "/api/mcp/plugins/d/connect", {})
            out["authorizing_list"] = await call("GET", "/api/mcp/plugins")
            state = out["d_authorizing"][1]["authorization_url"].split("state=")[1].split("&")[0]
            await chain.call("GET", "/api/mcp/oauth/callback", params={"code": "x", "state": state,
                                                                        "iss": "https://auth.example.com"})
            out["authorized_list"] = await call("GET", "/api/mcp/plugins")
            out["b_connected"] = await call("POST", "/api/mcp/plugins/b/connect", {})
            out["disabled"] = await call("PATCH", "/api/mcp/plugins/plugins", {"enabled": False})
            out["disabled_list"] = await call("GET", "/api/mcp/plugins")
            await call("PATCH", "/api/mcp/plugins/plugins", {"enabled": True})
            out["disconnected"] = await call("POST", "/api/mcp/plugins/d/disconnect")
            out["removed"] = await call("DELETE", "/api/mcp/plugins/c")
            out["final_list"] = await call("GET", "/api/mcp/plugins")
        # Core arrêté : la vraie réponse du relais.
        down = ControlCenter(runtime_root=root / "down", project_root=root)
        from aiohttp.test_utils import TestClient, TestServer
        from jarvis.runtime.core_sessions import CoreSessionTransport
        (root / "dead.token").write_text("t" * 48, encoding="utf-8")
        down.sessions = CoreSessionTransport(host="127.0.0.1", port=1, token_file=root / "dead.token")
        async with TestClient(TestServer(down._app)) as client:
            response = await client.get("/api/mcp/plugins")
            out["core_down"] = [response.status, await response.json()]
        await down.sessions.close()
        return out

    return asyncio.run(collect())


def plugin(api: dict, key: str, plugin_id: str) -> dict:
    listing = api[key][1]
    return next(p for p in listing["plugins"] if p["plugin_id"] == plugin_id)


def test_the_real_payloads_cover_every_card_state(api):
    assert api["connected"][0] == 200 and api["d_authorizing"][0] == 202
    assert api["b_refused"][1]["error"]["code"] == "mcp_plugin_reauthorization_required"
    assert api["c_refused"][1]["error"]["code"] == "mcp_remote_unreachable"
    assert api["core_down"][0] == 503 and api["core_down"][1]["error"]["code"] == "core_unreachable"
    states = {(p["connection_status"], p["auth_status"]) for key in ("authorizing_list", "b_list", "final_list")
              for p in api[key][1]["plugins"]}
    assert ("connecting", "authorizing") in states and ("connected", "authorized") in states
    assert SENTINEL not in json.dumps(api)


# ----------------------------------------------------------------- logique pure : cartes

def test_cards_show_icon_or_letter_name_host_badges_switch_count_and_manage(tmp_path, api):
    listing = api["authorized_list"][1]
    answer = run_node(tmp_path, """
      const L=D.authorized_list[1];
      const out={};
      for(const p of L.plugins)out[p.plugin_id]=P.cardHtml(p);
      out.b=P.cardHtml(D.b_list[1].plugins.find(p=>p.plugin_id==='b'));
      const iconned={...L.plugins[0],icon_url:'https://icons.example.com/p.png'};
      out.icon=P.cardHtml(iconned);
      out.iconFailed=P.cardHtml(iconned,{iconFailed:true});
      out.httpIcon=P.cardHtml({...L.plugins[0],icon_url:'http://icons.example.com/p.png'});
      out.evil=P.cardHtml({...L.plugins[0],display_name:'<img src=x onerror=alert(1)>'});
      out.list=P.listHtml(L);
      out.empty=P.listHtml(D.empty[1]);
      return out""", api)
    connected = answer["plugins"]
    assert '<span class="mcpp-letter">S</span>' in connected and "<img" not in connected
    assert '<h3 class="mcpp-name" id="mcpp-name-plugins">Scripted</h3>' in connected
    assert '<span class="mcpp-host">plugins.example.com</span>' in connected
    assert '<span class="chip ok" title="état de la connexion">Connecté</span>' in connected
    assert '<span class="chip" title="état de l’accès">Sans authentification</span>' in connected
    assert 'role="switch"' in connected and 'aria-checked="true"' in connected
    assert "1 outil</span>" in connected and 'data-act="manage"' in connected and 'aria-label="Gérer Scripted"' in connected
    assert 'data-act="connect"' not in connected  # connecté : pas d'action principale
    authorized = answer["d"]
    assert '<span class="chip ok" title="état de l’accès">Autorisé</span>' in authorized
    unreachable = answer["c"]
    assert 'data-state="error"' in unreachable and "Serveur injoignable <code>mcp_remote_unreachable</code>" in unreachable
    assert 'data-act="connect"' in unreachable and ">Reconnecter<" in unreachable
    refused = answer["b"]
    assert "Nouvelle autorisation nécessaire <code>mcp_plugin_reauthorization_required</code>" in refused
    assert '<span class="chip bad" title="état de l’accès">Accès refusé</span>' in refused
    # Icône : https seulement, sans referer, lettre dessous ; en échec, la lettre seule.
    assert '<img src="https://icons.example.com/p.png" alt="" referrerpolicy="no-referrer"' in answer["icon"]
    assert "<img" not in answer["iconFailed"] and "<img" not in answer["httpIcon"]
    assert "<img src=x" not in answer["evil"] and "&lt;img src=x onerror=alert(1)&gt;" in answer["evil"]
    assert answer["list"].count('class="mcpp-card"') == len(listing["plugins"])
    assert "Aucun plugin externe" in answer["empty"] and 'id="mcpp-add-empty"' in answer["empty"]


def test_a_disabled_plugin_reads_as_off_with_its_tools_withdrawn(tmp_path, api):
    html = run_node(tmp_path, "return P.cardHtml(D.disabled[1].plugin)", api)
    assert 'data-state="off"' in html and 'aria-checked="false"' in html
    assert "désactivé : outils retirés" in html and ">Désactivé<" in html


def test_the_vault_absence_is_said_above_the_cards(tmp_path, api):
    html = run_node(tmp_path, "return P.listHtml({...D.final_list[1],vault_available:false})", api)
    assert "Aucun coffre de secrets local." in html


def test_poll_decisions_follow_the_plugin_states(tmp_path, api):
    answer = run_node(tmp_path, """
      const d=D.authorizing_list[1].plugins.find(p=>p.plugin_id==='d');
      const done=D.authorized_list[1].plugins.find(p=>p.plugin_id==='d');
      const failed={...d,connection_status:'error',auth_status:'failed',last_error_code:'mcp_oauth_denied'};
      return [P.pollDecision(d,0,1000),P.pollDecision(d,0,P.POLL_MAX_MS),P.pollDecision(done,0,1000),
        P.pollDecision(failed,0,1000),P.pollDecision(null,0,0),P.POLL_MS,P.POLL_MAX_MS]""", api)
    assert answer == ["continue", "timeout", "done", "failed", "gone", 2000, 300000]


# ----------------------------------------------------------------- erreurs codées

def test_every_management_code_reads_as_a_french_sentence(tmp_path):
    tool_only = {"mcp_remote_tool_error", "mcp_tool_unknown", "native_tool_call_directly", "mcp_arguments_invalid",
                 "mcp_cursor_invalid", "mcp_tool_name_invalid", "mcp_tool_schema_too_large", "mcp_tool_schema_invalid",
                 "mcp_tool_list_too_large"}
    codes = sorted({code.value for code in McpErrorCode} - tool_only
                   | {"mcp_plugin_store_unreadable", "mcp_plugin_store_failed", "core_unreachable",
                      "core_unconfigured", "core_timeout", "forbidden_origin", "method_not_allowed", "not_found",
                      "timeout", "network", "bad_response", "oauth_timeout"})
    views = run_node(tmp_path, "return D.map(code=>P.errorView({code,status:409,message:'m'}))", codes)
    for code, view in zip(codes, views):
        assert view["code"] == code and view["title"] != "Échec de l’opération", code
        assert view["title"] != code and view["hint"], code
    required = {v["code"]: v for v in views}
    assert required["mcp_plugin_internal_error"]["title"] == "Erreur interne de JARVIS"
    assert required["mcp_vault_unavailable"]["title"] == "Coffre de secrets indisponible"
    assert required["mcp_plugin_reauthorization_required"]["title"] == "Nouvelle autorisation nécessaire"
    assert required["mcp_endpoint_forbidden"]["title"] == "Adresse interdite"


def test_an_error_block_shows_title_server_message_code_status_and_recourse(tmp_path, api):
    html = run_node(tmp_path, "return P.errorHtml({code:D.core_down[1].error.code,status:D.core_down[0],"
                              "message:D.core_down[1].error.message})", api)
    assert 'role="alert"' in html and "Cœur de JARVIS injoignable" in html
    assert "core_unreachable · HTTP 503" in html and ">Réessayer</button>" in html
    assert "Exposition interne reste utilisable" in html


# ----------------------------------------------------------------- client

def test_the_client_only_speaks_to_plugin_routes_and_keeps_both_error_shapes(tmp_path, api):
    answer = run_node(tmp_path, """
      const calls=[];
      const reply=(status,body)=>({ok:status<400,status,text:async()=>body===undefined?'':JSON.stringify(body)});
      const answers={
        'GET /api/mcp/plugins':reply(...D.core_down),
        'POST /api/mcp/plugins':reply(403,{ok:false,code:'forbidden_origin',error:'forbidden origin'}),
        'POST /api/mcp/plugins/b/connect':reply(...D.b_refused),
        'POST /api/mcp/plugins/d/connect':reply(...D.d_authorizing),
        'PUT /api/mcp/plugins/b/credential':reply(...D.b_credential),
      };
      const timers=[];
      const c=P.createClient({fetchImpl:async(path,init)=>{calls.push({path,method:init.method,body:init.body??null,
          type:(init.headers||{})['Content-Type']||null});
          return answers[`${init.method} ${path}`]||reply(404,{error:{code:'not_found',message:'x'}})},
        setTimer:(fn,ms)=>{timers.push(ms);return 0},clearTimer:()=>{}});
      const r={};
      const grab=async p=>{try{await p;return 'ok'}catch(e){return [e.code,e.status,e.message]}};
      r.down=await grab(c.list());
      r.guard=await grab(c.create('https://x.example.com/mcp'));
      r.refused=await grab(c.connect('b'));
      const auth=await c.connect('d');r.auth=[auth.status,auth.body.status];
      r.cred=(await c.setCredential('b',{strategy:'bearer',value:'SECRET-VALUE'})).plugin.auth_strategy;
      r.header=await grab(c.setCredential('b',{strategy:'header',headerName:'X-K',value:'v'}));
      r.badId=await grab(c.update('../x',{enabled:true}));
      r.badAction=await grab((async()=>P.pluginPath('b','call'))());
      r.routes=['/api/mcp/plugins','/api/mcp/plugins/b','/api/mcp/plugins/b/connect','/api/mcp/tools',
        '/api/mcp/plugins/b/call','/api/mcp/plugins/B','/api/mcp/plugins/b?x=1','/api/mcp/oauth/callback'].map(P.pluginRoute);
      r.calls=calls;r.timers=timers;
      return r""", api)
    assert answer["down"] == ["core_unreachable", 503, api["core_down"][1]["error"]["message"]]
    assert answer["guard"] == ["forbidden_origin", 403, "forbidden origin"]
    assert answer["refused"][:2] == ["mcp_plugin_reauthorization_required", 409]
    assert answer["auth"] == [202, "authorizing"] and answer["cred"] == "bearer"
    assert answer["badId"][0] == "forbidden_route" and answer["badAction"][0] == "forbidden_route"
    assert answer["routes"] == [True, True, True, False, False, False, False, False]
    methods = [(c["method"], c["path"]) for c in answer["calls"]]
    assert ("PATCH", "/api/mcp/plugins/../x") not in methods  # refusé avant le réseau
    put = [c for c in answer["calls"] if c["method"] == "PUT"]
    assert json.loads(put[0]["body"]) == {"strategy": "bearer", "value": "SECRET-VALUE"}
    assert json.loads(put[1]["body"]) == {"strategy": "header", "header_name": "X-K", "value": "v"}
    assert all(c["type"] == "application/json" for c in answer["calls"] if c["body"] is not None)
    # Délai long pour la connexion (le relais attend 35 s), court sinon.
    assert answer["timers"].count(45000) == 2 and 15000 in answer["timers"]


def test_a_request_past_its_deadline_is_a_timeout(tmp_path):
    answer = run_node(tmp_path, """
      const c=P.createClient({deadlineMs:20,fetchImpl:(path,init)=>new Promise((_,reject)=>{
        init.signal.addEventListener('abort',()=>reject(new Error('aborted')))})});
      try{await c.list();return 'no'}catch(e){return [e.code,e.message]}""")
    assert answer == ["timeout", "aucune réponse en 0 s"]


# ----------------------------------------------------------------- formulaires et fiche

def test_the_credential_form_is_write_only(tmp_path, api):
    answer = run_node(tmp_path, """
      const b=D.b_list[1].plugins.find(p=>p.plugin_id==='b');
      return {bearer:P.credentialFormHtml(b,{}),header:P.credentialFormHtml(b,{strategy:'header',headerName:'X-Api-Key'}),
        noVault:P.credentialFormHtml(b,{vault:false})}""", api)
    bearer = answer["bearer"]
    secret = re.search(r'<input type="password" id="mcppSecret"[^>]*>', bearer).group(0)
    assert "value=" not in secret and 'autocomplete="off"' in secret and 'maxlength="4096"' in secret
    assert '<label for="mcppSecret" id="mcppSecretLabel">Jeton</label>' in bearer
    assert 'id="mcppHeaderField" hidden' in bearer and 'name="strategy" value="bearer" id="mcppCredBearer" checked' in bearer
    assert 'value="X-Api-Key"' in answer["header"] and "Valeur de l’en-tête" in answer["header"]
    assert 'id="mcppHeaderField" hidden' not in answer["header"]
    assert "Aucun coffre de secrets" in answer["noVault"] and 'id="mcppCredSubmit" disabled' in answer["noVault"]


def test_the_manage_view_lists_facts_actions_and_reuses_the_inspector_rows(tmp_path, api):
    answer = run_node(tmp_path, """
      const p=D.connected_list[1].plugins[0];
      const rows=P.pluginTools(D.catalog[1],p.plugin_id);
      const detail={state:'ok',tool:D.detail[1].tool};
      const key=I.toolKey(rows[0]);
      const html=I.toolRowsHtml(rows,{idPrefix:'mcpp-t',expanded:new Set([key]),details:{[key]:detail}});
      return {rows:rows.length,view:P.manageHtml(p,{tools:{state:'ok',count:rows.length,html}}),
        disabled:P.manageHtml(D.disabled[1].plugin,{}),
        err:P.manageHtml(D.b_list[1].plugins.find(x=>x.plugin_id==='b'),{actionError:{code:'mcp_plugin_reauthorization_required',status:409,message:'m'}}),
        authorizing:P.manageHtml(D.authorizing_list[1].plugins.find(x=>x.plugin_id==='d'),{authorizing:{url:D.d_authorizing[1].authorization_url,started:0},now:61000})}""", api)
    view = answer["view"]
    assert answer["rows"] == 1
    for label in ("Adresse", "Identifiant", "Serveur", "Accès", "Outils découverts"):
        assert f"<dt>{label}</dt>" in view
    assert "<code>https://plugins.example.com/mcp</code>" in view and "Scripted 1" in view
    for act, label in (("refresh", "Actualiser les outils"), ("connect", "Reconnecter"), ("cred", "Saisir un jeton"),
                       ("disconnect", "Déconnecter"), ("remove", "Supprimer")):
        assert f'data-act="{act}"' in view and f">{label}</button>" in view
    assert 'class="action danger" id="mcpp-m-remove"' in view
    # Les outils : lignes ET détail de l'inspecteur, sous un préfixe propre.
    assert 'class="mcpi-list"' in view and 'id="mcpi-mcpp-t-0-t"' in view and 'class="mcpi-toggle"' in view
    assert "mcpi-noparam" in view or "catalog-table mcpi-params" in view
    assert '<code class="mcpi-wire">search</code>' in view
    assert "Plugin désactivé : ses outils sont retirés" in answer["disabled"]
    assert 'id="mcpp-err-cred"' in answer["err"] and ">Saisir un jeton</button>" in answer["err"]
    authorizing = answer["authorizing"]
    assert "Autorisation attendue dans l’onglet du service" in authorizing
    assert 'target="_blank" rel="noopener noreferrer"' in authorizing and "1 min 01 s · reste 3 min 59 s" in authorizing


def test_the_add_form_labels_its_fields_and_ties_its_error(tmp_path):
    answer = run_node(tmp_path, """
      return {plain:P.addFormHtml({}),error:P.addFormHtml({endpoint:'https://x',error:{code:'mcp_endpoint_forbidden',status:400,message:'m'}}),
        busy:P.addFormHtml({endpoint:'https://x',busy:{label:'Enregistrement du plugin…',started:0},now:2500})}""")
    plain = answer["plain"]
    assert '<label for="mcppEndpoint">Adresse du serveur</label>' in plain and 'type="url"' in plain
    assert '<label for="mcppName">Nom affiché' in plain
    assert 'aria-invalid="true" aria-describedby="mcppAddError"' in answer["error"] and "Adresse interdite" in answer["error"]
    assert 'role="status">Enregistrement du plugin…</span>' in answer["busy"] and "2,5 s" in answer["busy"]
    assert 'id="mcppAddSubmit" disabled' in answer["busy"]


# ----------------------------------------------------------------- bloc navigateur

#: Un DOM minimal : les nœuds existent s'ils sont statiques ou présents dans un
#: HTML rendu ; remplacer un HTML détruit le focus qu'il contenait ET remet les
#: champs qu'il contient à leur attribut `value` (une saisie effacée se voit).
DOM_STUB = r"""
const STATIC=new Set(['mcpInspector','mcpPlugins','openMcpInspector','mcpViewTabs','mcpViewInternal','mcpViewPlugins',
  'mcpViewCount','mcppStatus','mcppStatusLabel','mcppStatusDetail','mcppStatusClock','mcppAdd','mcppRefresh','mcppBody',
  'mcppAnnounce','confirmBack']);
const listeners={},winListeners=[],cache={},calls=[],opened=[],toasts=[],confirms=[],timers=[],logs=[];
let focused=null,timerId=0,skew=0;
const realNow=Date.now;Date.now=()=>realNow()+skew;
global.setTimeout=(fn,ms)=>{const id=++timerId;timers.push({id,fn,ms});return id};
global.clearTimeout=id=>{const i=timers.findIndex(t=>t.id===id);if(i>=0)timers.splice(i,1)};
global.setInterval=()=>0;global.clearInterval=()=>{};
for(const k of ['info','warn','error'])console[k]=line=>logs.push(line);
function attrs(html,re){const out=[];let m;while((m=re.exec(html)))out.push(m);return out}
function everything(){return Object.values(cache).map(n=>n._html).join('\n')}
function exists(id){return STATIC.has(id)||everything().includes(`id="${id}"`)}
function node(id){
  const self={id,hidden:false,inert:false,textContent:'',className:'',isConnected:true,disabled:false,style:{},dataset:{},
    tabIndex:0,value:'',tagName:'DIV',_html:'',
    classList:{add(){},remove(){},contains(){return false}},setAttribute(k,v){self['@'+k]=String(v)},getAttribute(k){return self['@'+k]??null},
    focus(){focused=id},contains(){return true},closest(){return null},
    addEventListener(kind,fn){(listeners[id]=listeners[id]||{})[kind]=fn},
    querySelector(selector){return selector.startsWith('#')&&exists(selector.slice(1))?pick(selector.slice(1)):null},
    querySelectorAll(selector){
      const scope=id==='mcppBody'?everything():self._html;
      if(selector==='.mcpi-toggle')return attrs(scope,/class="mcpi-toggle" id="([^"]+)" data-key="([^"]+)"/g).map(m=>{
        const b=button(m[1],{key:m[2]});b.classList={contains:c=>c==='mcpi-toggle'};return b});
      return [];
    }};
  Object.defineProperty(self,'innerHTML',{set(v){
      if(focused&&self._html.includes(`id="${focused}"`))focused=null;
      self._html=String(v);
      for(const m of attrs(self._html,/<input[^>]*\bid="([^"]+)"[^>]*>/g)){
        const value=/\svalue="([^"]*)"/.exec(m[0]);pick(m[1]).value=value?value[1]:'';
        pick(m[1]).disabled=/\sdisabled[\s>]/.test(m[0]);
      }
      for(const m of attrs(self._html,/<div class="field" id="([^"]+)"( hidden)?/g))pick(m[1]).hidden=!!m[2];
    },get(){return self._html}});
  return self;
}
function pick(id){return cache[id]=cache[id]||node(id)}
function button(id,data){const b=pick(id);b.dataset={...data};b.tagName='BUTTON';b.classList={contains:()=>false};
  b.closest=s=>s==='button'||s.includes('button')?b:null;return b}
/* Un bouton rendu, lu dans le HTML : ses `data-*`, `disabled`. */
function rendered(id){
  const html=everything();const m=new RegExp(`<button[^>]*\\bid="${id}"[^>]*>`).exec(html);
  if(!m)throw new Error('bouton absent : '+id);
  const data={};for(const a of attrs(m[0],/data-([a-z-]+)="([^"]*)"/g))data[a[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=a[2];
  const b=button(id,data);b.disabled=/\sdisabled[\s>]/.test(m[0]);return b;
}
const click=id=>listeners.mcppBody.click({target:rendered(id)});
const form=id=>({id,dataset:{id:(new RegExp(`<form[^>]*id="${id}"[^>]*data-id="([^"]+)"`).exec(everything())||[])[1]},
  querySelector:s=>exists(s.slice(1))?pick(s.slice(1)):null});
const submit=id=>listeners.mcppBody.submit({target:form(id),preventDefault(){}});
const reply=(status,body)=>({ok:status<400,status,text:async()=>JSON.stringify(body)});
/* Réponses par « MÉTHODE chemin » : une file ; la dernière reste servie. */
const control={answers:{},confirm:true};
const serve=(key,...answers)=>{control.answers[key]=answers.slice()};
global.window={
  fetch:async(path,init)=>{calls.push({method:init.method,path,body:init.body??null});
    const queue=control.answers[`${init.method} ${path}`];
    if(!queue||!queue.length)return reply(404,{error:{code:'not_found',message:'unknown'}});
    const [status,body]=queue.length>1?queue.shift():queue[0];
    return reply(status,body)},
  open:(url,target,features)=>{opened.push([url,target,features]);return null},
  addEventListener:(kind,fn,capture)=>winListeners.push({kind,fn,capture}),
};
global.requestAnimationFrame=fn=>fn();
global.toast=spec=>toasts.push(spec);
global.confirmDialog=async spec=>{confirms.push(spec);return control.confirm};
global.JarvisMcpInspectorCore=I;
global.document={getElementById:id=>exists(id)?pick(id):null,body:{children:[]},
  get activeElement(){return focused?pick(focused):global.document.body},addEventListener(){}};
pick('confirmBack').hidden=true;pick('mcpPlugins').hidden=true;
delete require.cache[require.resolve(MODULE_PATH)];
require(MODULE_PATH);
const W=global.window.JarvisMcpPlugins,S=W.state;
const escape=()=>{let prevented=false;for(const l of winListeners)if(l.kind==='keydown'&&l.capture)
  l.fn({key:'Escape',preventDefault(){prevented=true},stopPropagation(){}});return prevented};
const firePolls=async()=>{const due=timers.filter(t=>t.ms===P.POLL_MS);for(const t of due){clearTimeout(t.id);t.fn()}await settle()};
const writes=()=>calls.filter(c=>c.method!=='GET').map(c=>`${c.method} ${c.path}`);
const html=()=>everything();
"""


def test_the_view_tabs_switch_by_click_and_arrows_and_load_the_plugins(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      serve('GET /api/mcp/plugins',D.final_list);
      const r={};
      r.before={view:pick('mcpInspector').dataset.view,hidden:pick('mcpPlugins').hidden};
      listeners.mcpViewPlugins.click({});await settle();
      r.after={view:pick('mcpInspector').dataset.view,hidden:pick('mcpPlugins').hidden,
        selected:pick('mcpViewPlugins')['@aria-selected'],internal:pick('mcpViewInternal')['@aria-selected'],
        tabIndex:[pick('mcpViewInternal').tabIndex,pick('mcpViewPlugins').tabIndex],count:pick('mcpViewCount').textContent,
        status:pick('mcppStatusLabel').textContent,detail:pick('mcppStatusDetail').textContent,tone:pick('mcppStatus').dataset.tone,
        cards:(html().match(/class="mcpp-card"/g)||[]).length,announce:pick('mcppAnnounce').textContent};
      let prevented=false;
      listeners.mcpViewTabs.keydown({key:'ArrowLeft',preventDefault(){prevented=true}});
      r.left={view:S.view,focus:focused,prevented,hidden:pick('mcpPlugins').hidden};
      listeners.mcpViewTabs.keydown({key:'End',preventDefault(){}});await settle();
      r.end={view:S.view,focus:focused};
      r.gets=calls.filter(c=>c.method==='GET').length;
      return r""", api)
    assert answer["before"] == {"view": "internal", "hidden": True}
    after = answer["after"]
    total = len(api["final_list"][1]["plugins"])
    assert (after["view"], after["hidden"], after["selected"], after["internal"]) == ("plugins", False, "true", "false")
    assert after["tabIndex"] == [-1, 0] and after["count"] == str(total) and after["cards"] == total
    assert (after["status"], after["tone"]) == ("Plugins lus", "live") and "connecté" in after["detail"]
    assert after["announce"] == f"{total} plugins externes."
    assert answer["left"] == {"view": "internal", "focus": "mcpViewInternal", "prevented": True, "hidden": True}
    assert answer["end"] == {"view": "plugins", "focus": "mcpViewPlugins"}
    assert answer["gets"] == 2  # chaque passage sur l'onglet relit Core


def test_add_by_url_creates_connects_and_lands_on_the_new_card(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      serve('GET /api/mcp/plugins',D.empty,D.created_list,D.connected_list);
      serve('POST /api/mcp/plugins',D.created);
      serve('POST /api/mcp/plugins/plugins/connect',D.connected);
      W.select('plugins');await settle();
      listeners.mcppAdd.click({});
      const r={formFocus:focused,form:html().includes('id="mcppAddForm"')};
      /* Adresse vide : refusée ici, sans réseau. */
      pick('mcppEndpoint').value='  ';submit('mcppAddForm');await settle();
      r.emptyError=html().includes('aria-invalid="true"')&&html().includes('Adresse invalide');r.emptyFocus=focused;
      r.writesAfterEmpty=writes().length;
      pick('mcppEndpoint').value='https://plugins.example.com/mcp';pick('mcppName').value='';
      submit('mcppAddForm');await settle();
      r.writes=writes();r.createBody=JSON.parse(calls.find(c=>c.method==='POST'&&c.path==='/api/mcp/plugins').body);
      r.form=html().includes('id="mcppAddForm"');r.focus=focused;
      r.card=html().includes('<span class="chip ok" title="état de la connexion">Connecté</span>');
      r.toasts=toasts.map(t=>t.title);r.busy=Object.keys(S.busy).length;
      return r""", api)
    assert answer["formFocus"] == "mcppEndpoint" and answer["form"] is False  # le formulaire est refermé ensuite
    assert answer["emptyError"] is True and answer["emptyFocus"] == "mcppEndpoint" and answer["writesAfterEmpty"] == 0
    assert answer["writes"] == ["POST /api/mcp/plugins", "POST /api/mcp/plugins/plugins/connect"]
    assert answer["createBody"] == {"endpoint": "https://plugins.example.com/mcp"}
    assert answer["focus"] == "mcpp-manage-plugins" and answer["card"] is True
    assert answer["toasts"] == ["Scripted connecté"] and answer["busy"] == 0


def test_a_refused_create_keeps_the_typed_address_and_says_why(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      serve('GET /api/mcp/plugins',D.empty);
      serve('POST /api/mcp/plugins',[400,{error:{code:'mcp_endpoint_forbidden',message:'the endpoint resolves to a forbidden address'}}]);
      W.select('plugins');await settle();
      listeners.mcppAdd.click({});
      pick('mcppEndpoint').value='https://10.0.0.1/mcp';submit('mcppAddForm');await settle();
      return {value:pick('mcppEndpoint').value,focus:focused,error:html().includes('Adresse interdite')&&html().includes('mcp_endpoint_forbidden · HTTP 400'),
        logged:logs.some(l=>l.includes('mcp.plugins.action_failed')&&l.includes('mcp_endpoint_forbidden')),
        submit:/id="mcppAddSubmit"(?! disabled)/.test(html())}""", api)
    assert answer == {"value": "https://10.0.0.1/mcp", "focus": "mcppEndpoint", "error": True, "logged": True,
                      "submit": True}


def test_oauth_opens_a_noopener_tab_polls_every_two_seconds_and_lands_connected(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      const url=D.d_authorizing[1].authorization_url;
      serve('GET /api/mcp/plugins',D.d_created_list,D.authorizing_list,D.authorizing_list,D.authorized_list);
      serve('POST /api/mcp/plugins/d/connect',D.d_authorizing);
      W.select('plugins');await settle();
      click('mcpp-connect-d');
      const r={busyLabel:html().includes('role="status">Connexion…</span>')};
      await settle();
      r.opened=opened;r.waiting=Object.keys(S.authorizing);
      r.link=html().includes(`href="${url.replace(/&/g,'&amp;')}" target="_blank" rel="noopener noreferrer"`);
      r.pollTimers=timers.filter(t=>t.ms===P.POLL_MS).length;
      await firePolls();
      r.stillWaiting=Object.keys(S.authorizing);
      await firePolls();
      r.done=Object.keys(S.authorizing);r.toasts=toasts.map(t=>t.title);
      r.card=html().includes('title="état de l’accès">Autorisé</span>');
      r.gets=calls.filter(c=>c.method==='GET').length;r.pending=timers.filter(t=>t.ms===P.POLL_MS).length;
      return r""", api)
    assert answer["busyLabel"] is True
    url = api["d_authorizing"][1]["authorization_url"]
    assert answer["opened"] == [[url, "_blank", "noopener,noreferrer"]]
    assert answer["waiting"] == ["d"] and answer["link"] is True and answer["pollTimers"] == 1
    assert answer["stillWaiting"] == ["d"]
    assert answer["done"] == [] and answer["toasts"] == ["Scripted connecté"] and answer["card"] is True
    assert answer["pending"] == 0 and answer["gets"] == 4


def test_the_authorization_wait_ends_after_five_minutes_and_says_so(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      serve('GET /api/mcp/plugins',D.d_created_list,D.authorizing_list);
      serve('POST /api/mcp/plugins/d/connect',D.d_authorizing);
      W.select('plugins');await settle();
      click('mcpp-connect-d');await settle();
      await firePolls();
      const r={waitingAt2s:Object.keys(S.authorizing)};
      skew=P.POLL_MAX_MS+1000;
      await firePolls();
      r.waiting=Object.keys(S.authorizing);r.toast=toasts.at(-1);r.pending=timers.filter(t=>t.ms===P.POLL_MS).length;
      r.logged=logs.some(l=>l.includes('oauth_timeout'));r.announce=pick('mcppAnnounce').textContent;
      r.retry=html().includes('id="mcpp-connect-d"');
      return r""", api)
    assert answer["waitingAt2s"] == ["d"] and answer["waiting"] == [] and answer["pending"] == 0
    assert answer["toast"]["title"] == "d.example.com : Autorisation non reçue" and answer["toast"]["kind"] == "bad"
    assert answer["logged"] is True and answer["announce"] == "Autorisation non reçue."
    assert answer["retry"] is True  # « Reconnecter » est proposé de nouveau


def test_an_oauth_wait_that_ends_refused_opens_the_manual_form(tmp_path, api):
    """Validation S6 : un serveur qui publie OAuth mais refuse le jeton obtenu
    (Bearer statique) finit `failed` ; l'écran propose aussitôt la saisie."""

    answer = run_node(tmp_path, DOM_STUB + """
      const refused=JSON.parse(JSON.stringify(D.authorizing_list));
      Object.assign(refused[1].plugins.find(p=>p.plugin_id==='d'),{connection_status:'error',auth_status:'failed',
        last_error_code:'mcp_plugin_reauthorization_required'});
      serve('GET /api/mcp/plugins',D.d_created_list,D.authorizing_list,refused);
      serve('POST /api/mcp/plugins/d/connect',D.d_authorizing);
      W.select('plugins');await settle();
      click('mcpp-connect-d');await settle();
      await firePolls();
      return {manage:S.manage,cred:!!S.cred,focus:focused,error:S.actionError&&S.actionError.code,
        waiting:Object.keys(S.authorizing),toast:toasts.at(-1).title}""", api)
    assert answer == {"manage": "d", "cred": True, "focus": "mcppSecret",
                      "error": "mcp_plugin_reauthorization_required", "waiting": [],
                      "toast": "d.example.com : autorisation non aboutie"}


def test_a_refused_connect_opens_the_manual_form_and_the_secret_never_stays(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      const refused=D.b_list;
      serve('GET /api/mcp/plugins',D.created_list,refused,refused,refused,D.authorized_list);
      serve('POST /api/mcp/plugins',D.b_created);
      serve('POST /api/mcp/plugins/b/connect',D.b_refused,D.b_connected);
      serve('PUT /api/mcp/plugins/b/credential',D.b_credential);
      W.select('plugins');await settle();
      listeners.mcppAdd.click({});
      pick('mcppEndpoint').value='https://b.example.com/mcp';submit('mcppAddForm');await settle();
      const r={manage:S.manage,cred:!!S.cred,focus:focused,notice:html().includes('Nouvelle autorisation nécessaire'),
        form:html().includes('id="mcppCredForm"')};
      /* Un rendu d'arrière-plan ne vide pas le champ en cours de saisie. */
      pick('mcppSecret').value=SECRET;
      listeners.mcppRefresh.click({});await settle();
      r.survives=pick('mcppSecret').value===SECRET;
      submit('mcppCredForm');await settle();
      const put=calls.find(c=>c.method==='PUT');
      r.putBody=JSON.parse(put.body);
      r.fieldAfter=pick('mcppSecret').value;
      r.inState=JSON.stringify(S,(k,v)=>v instanceof Set?[...v]:v).includes(SECRET);
      r.inHtml=html().includes(SECRET);r.inLogs=logs.join('\\n').includes(SECRET);
      r.inToasts=JSON.stringify(toasts).includes(SECRET);
      r.writes=writes();r.credAfter=S.cred;
      r.secretSent=calls.filter(c=>(c.body||'').includes(SECRET)).map(c=>`${c.method} ${c.path}`);
      return r""".replace("SECRET", json.dumps(SENTINEL)), api)
    assert answer["manage"] == "b" and answer["cred"] is True and answer["focus"] == "mcppSecret"
    assert answer["notice"] is True and answer["form"] is True
    assert answer["survives"] is True
    assert answer["putBody"] == {"strategy": "bearer", "value": SENTINEL}
    assert answer["fieldAfter"] == "" and answer["credAfter"] is None
    for leak in ("inState", "inHtml", "inLogs", "inToasts"):
        assert answer[leak] is False, leak
    assert answer["secretSent"] == ["PUT /api/mcp/plugins/b/credential"]  # une seule fois, un seul endroit
    assert answer["writes"] == ["POST /api/mcp/plugins", "POST /api/mcp/plugins/b/connect",
                                "PUT /api/mcp/plugins/b/credential", "POST /api/mcp/plugins/b/connect"]


def test_the_custom_header_form_needs_a_name_and_sends_it(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      serve('GET /api/mcp/plugins',D.b_list);
      serve('PUT /api/mcp/plugins/b/credential',D.b_credential);
      serve('POST /api/mcp/plugins/b/connect',D.b_connected);
      W.select('plugins');await settle();
      click('mcpp-manage-b');await settle();
      click('mcpp-m-cred');
      const r={focus:focused,expanded:html().includes('id="mcpp-m-cred" data-act="cred" data-id="b" aria-expanded="true"')};
      listeners.mcppBody.change({target:{name:'strategy',value:'header'}});
      r.headerShown=pick('mcppHeaderField').hidden===false;r.label=pick('mcppSecretLabel').textContent;
      pick('mcppSecret').value='v-1';pick('mcppHeaderName').value='';
      submit('mcppCredForm');await settle();
      r.missing={puts:calls.filter(c=>c.method==='PUT').length,focus:focused,field:pick('mcppSecret').value,
        error:html().includes('mcppCredError')};
      pick('mcppSecret').value='v-2';pick('mcppHeaderName').value='X-Api-Key';
      submit('mcppCredForm');await settle();
      r.body=JSON.parse(calls.find(c=>c.method==='PUT').body);
      return r""", api)
    assert answer["focus"] == "mcppSecret" and answer["expanded"] is True
    assert answer["headerShown"] is True and answer["label"] == "Valeur de l’en-tête"
    assert answer["missing"] == {"puts": 0, "focus": "mcppHeaderName", "field": "", "error": True}
    assert answer["body"] == {"strategy": "header", "header_name": "X-Api-Key", "value": "v-2"}


def test_the_switch_toggles_enabled_and_rereads_core(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      serve('GET /api/mcp/plugins',D.connected_list,D.disabled_list);
      serve('PATCH /api/mcp/plugins/plugins',D.disabled);
      W.select('plugins');await settle();
      pick('mcpp-sw-plugins').focus();
      click('mcpp-sw-plugins');
      const r={busy:/id="mcpp-sw-plugins"[^>]*disabled/.test(html())};
      await settle();
      r.body=JSON.parse(calls.find(c=>c.method==='PATCH').body);
      r.checked=/id="mcpp-sw-plugins"[^>]*aria-checked="false"/.test(html());r.focus=focused;
      r.announce=pick('mcppAnnounce').textContent;
      return r""", api)
    assert answer["busy"] is True and answer["body"] == {"enabled": False}
    assert answer["checked"] is True and answer["focus"] == "mcpp-sw-plugins"
    assert answer["announce"].startswith("Scripted désactivé")


def test_remove_asks_first_and_only_deletes_once_confirmed(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      serve('GET /api/mcp/plugins',D.connected_list,D.empty);
      serve('DELETE /api/mcp/plugins/plugins',D.removed);
      W.select('plugins');await settle();
      click('mcpp-manage-plugins');await settle();
      control.confirm=false;click('mcpp-m-remove');await settle();
      const r={afterCancel:writes(),confirm:confirms[0]};
      control.confirm=true;click('mcpp-m-remove');await settle();
      r.writes=writes();r.manage=S.manage;r.toast=toasts.at(-1).title;r.focus=focused;
      return r""", api)
    assert answer["afterCancel"] == []
    assert answer["confirm"]["danger"] is True and answer["confirm"]["title"] == "Supprimer Scripted ?"
    assert answer["confirm"]["confirmLabel"] == "Supprimer"
    assert answer["writes"] == ["DELETE /api/mcp/plugins/plugins"] and answer["manage"] is None
    assert answer["toast"] == "Scripted supprimé" and answer["focus"] == "mcppAdd"


def test_disconnect_of_an_authorized_plugin_is_confirmed_then_forgets_its_access(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      serve('GET /api/mcp/plugins',D.authorized_list);
      serve('POST /api/mcp/plugins/d/disconnect',D.disconnected);
      W.select('plugins');await settle();
      click('mcpp-manage-d');await settle();
      click('mcpp-m-disconnect');await settle();
      return {confirm:confirms.map(c=>c.title),writes:writes(),toast:toasts.at(-1).title}""", api)
    assert answer == {"confirm": ["Déconnecter Scripted ?"], "writes": ["POST /api/mcp/plugins/d/disconnect"],
                      "toast": "Scripted déconnecté"}


def test_manage_lists_the_plugin_tools_through_the_inspector_read_only_client(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      serve('GET /api/mcp/plugins',D.connected_list);
      serve('GET /api/mcp/tools',D.catalog);
      serve('GET /api/mcp/tools/plugins/search',D.detail);
      W.select('plugins');await settle();
      click('mcpp-manage-plugins');await settle();
      const r={focus:focused,title:html().includes('id="mcpp-m-title" tabindex="-1">Scripted</h3>'),
        rows:(html().match(/class="mcpi-toggle"/g)||[]).length};
      const toggle=pick('mcppBody').querySelectorAll('.mcpi-toggle')[0];
      toggle.focus();listeners.mcppBody.click({target:toggle});await settle();
      r.expanded=[...S.expanded];r.detail=html().includes('<dt>Nom complet</dt><dd><code>plugins.search</code></dd>');
      r.toggleFocus=focused;
      r.reads=calls.map(c=>`${c.method} ${c.path}`).filter(c=>c.includes('/api/mcp/tools'));
      /* Retour à la liste : le focus revient sur « Gérer ». */
      click('mcpp-back');
      r.back={manage:S.manage,focus:focused};
      return r""", api)
    assert answer["focus"] == "mcpp-m-title" and answer["title"] is True and answer["rows"] == 1
    assert answer["expanded"] == ["plugins/search"] and answer["detail"] is True
    assert answer["toggleFocus"] == "mcpi-mcpp-t-0-t"
    assert answer["reads"] == ["GET /api/mcp/tools", "GET /api/mcp/tools/plugins/search"]
    assert answer["back"] == {"manage": None, "focus": "mcpp-manage-plugins"}


def test_core_down_shows_the_coded_error_and_retry_reloads(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      serve('GET /api/mcp/plugins',D.core_down,D.final_list);
      W.select('plugins');await settle();
      const r={alert:html().includes('role="alert"')&&html().includes('Cœur de JARVIS injoignable')&&html().includes('core_unreachable · HTTP 503'),
        status:pick('mcppStatusLabel').textContent,tone:pick('mcppStatus').dataset.tone,
        logged:logs.some(l=>l.includes('mcp.plugins.action_failed')&&l.includes('core_unreachable'))};
      click('mcpp-retry-list');await settle();
      r.after=(html().match(/class="mcpp-card"/g)||[]).length;r.tone=[r.tone,pick('mcppStatus').dataset.tone];
      return r""", api)
    assert answer["alert"] is True and answer["status"] == "Cœur de JARVIS injoignable" and answer["logged"] is True
    assert answer["after"] == len(api["final_list"][1]["plugins"]) and answer["tone"] == ["bad", "live"]


def test_escape_steps_back_before_the_dialog_closes(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      serve('GET /api/mcp/plugins',D.b_list);
      W.select('plugins');await settle();
      click('mcpp-manage-b');await settle();click('mcpp-m-cred');
      const r=[];
      r.push([escape(),!!S.cred,S.manage,focused]);
      r.push([escape(),!!S.cred,S.manage,focused]);
      listeners.mcppAdd.click({});
      r.push([escape(),!!S.add,focused]);
      r.push([escape()]);  // rien à refermer : l'inspecteur fermera le dialogue
      pick('confirmBack').hidden=false;click('mcpp-manage-b');await settle();
      r.push([escape(),S.manage]);  // la confirmation ouverte garde sa touche
      return r""", api)
    assert answer[0] == [True, False, "b", "mcpp-m-cred"]
    assert answer[1] == [True, False, None, "mcpp-manage-b"]
    assert answer[2] == [True, False, "mcppAdd"]
    assert answer[3] == [False]
    assert answer[4] == [False, "b"]


def test_a_background_reread_never_wipes_a_typed_address(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      serve('GET /api/mcp/plugins',D.final_list);
      W.select('plugins');await settle();
      listeners.mcppAdd.click({});
      pick('mcppEndpoint').value='https://typed.example.com/mcp';
      listeners.mcppRefresh.click({});await settle();
      return pick('mcppEndpoint').value""", api)
    assert answer == "https://typed.example.com/mcp"


def test_a_broken_icon_falls_back_to_the_letter_and_is_not_asked_again(tmp_path, api):
    answer = run_node(tmp_path, DOM_STUB + """
      const list=JSON.parse(JSON.stringify(D.connected_list));list[1].plugins[0].icon_url='https://icons.example.com/p.png';
      serve('GET /api/mcp/plugins',list);
      W.select('plugins');await settle();
      const r={img:html().includes('data-icon-for="plugins"')};
      let removed=false;
      listeners.mcppBody.error({target:{tagName:'IMG',dataset:{iconFor:'plugins'},remove(){removed=true}}});
      listeners.mcppRefresh.click({});await settle();
      r.removed=removed;r.after=html().includes('data-icon-for="plugins"');r.letter=html().includes('<span class="mcpp-letter">S</span>');
      return r""", api)
    assert answer == {"img": True, "removed": True, "after": False, "letter": True}


# ----------------------------------------------------------------- source et page

def test_the_module_parses_and_names_no_tool_server_or_provider():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    completed = subprocess.run([node, "--check", str(MODULE)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    catalog = asyncio.run(mcp_catalog.build_catalog())
    for path in (MODULE, INSPECTOR):
        source = path.read_text(encoding="utf-8")
        for tool in catalog["tools"]:
            assert not re.search(rf"\b{re.escape(tool['name'])}\b", source), (path.name, tool["name"])
        for server in {tool["server"] for tool in catalog["tools"]}:
            assert server not in source, (path.name, server)
        assert not re.search(r"circuit|circoe|drive|google", source, re.I), path.name


def test_every_network_path_of_the_module_goes_through_its_two_clients():
    source = MODULE.read_text(encoding="utf-8")
    assert re.findall(r"fetch\w*\(", source) == ["fetchImpl(", "fetch(", "fetch("]
    assert "P.createClient({fetchImpl:(path,options)=>window.fetch(path,options)})" in source
    assert "I.createClient({fetchImpl:(path,options)=>window.fetch(path,options)})" in source  # outils : lecture seule
    assert "api(" not in source and "XMLHttpRequest" not in source and "sendBeacon" not in source
    # Aucun secret gardé : la valeur saisie n'est jamais recopiée dans l'état.
    assert not re.search(r"S\.\w+\s*=\s*\{[^}]*\bvalue\b", source)


@pytest.mark.asyncio
async def test_the_served_page_carries_the_tabs_the_panel_and_the_module_after_the_inspector(tmp_path):
    center = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = (await center.index(None)).text
    assert MCP_PLUGINS_SCRIPT_MARKER not in html
    assert html.index("const JarvisMcpInspectorCore=") < html.index("const JarvisMcpPluginsCore=")
    view = html[html.index('<section class="mcpi"'): html.index("</section>", html.index('<section class="mcpi"'))]
    tabs = re.search(r'<div class="mcpv-tabs" id="mcpViewTabs" role="tablist" aria-label="Vues MCP">.*?</div>', view).group(0)
    assert 'id="mcpViewInternal" aria-selected="true" aria-controls="mcpiMain" tabindex="0">Exposition interne' in tabs
    assert 'id="mcpViewPlugins" aria-selected="false" aria-controls="mcpPlugins" tabindex="-1">Plugins externes' in tabs
    assert '<div class="mcpi-main" id="mcpiMain" role="tabpanel" aria-labelledby="mcpViewInternal">' in view
    assert '<div class="mcpp" id="mcpPlugins" role="tabpanel" aria-labelledby="mcpViewPlugins"' in view
    assert 'id="mcppAnnounce" aria-live="polite"' in view and 'id="mcppStatus" role="status"' in view
    assert view.count('id="openMcpInspector"') == 0 and html.count('id="mcpInspector"') == 1  # un seul dialogue


def test_every_element_the_browser_block_reaches_for_exists_in_the_page():
    source = MODULE.read_text(encoding="utf-8")
    browser = source[source.index("(function installJarvisMcpPlugins(){"):]
    page = PAGE.read_text(encoding="utf-8")
    static = set(re.findall(r"getElementById\('([A-Za-z0-9_]+)'\)", browser))
    assert static, "aucun identifiant trouvé : le test ne prouverait rien"
    rendered = set(re.findall(r'id="([A-Za-z0-9_]+)"', source[:source.index("(function installJarvisMcpPlugins(){")]))
    assert sorted(name for name in static if f'id="{name}"' not in page and name not in rendered) == []


def test_the_view_uses_page_tokens_is_responsive_and_respects_reduced_motion():
    html = PAGE.read_text(encoding="utf-8")
    css = html[html.index("/* ---------- Plugins MCP externes"): html.index("</style>")]
    assert "var(--accent)" in css and "var(--line)" in css and "var(--danger)" in css and "var(--ok)" in css
    assert not re.search(r"#6ee7ff|#ff6577|#ffb85c|#68e0a0", css, re.I)
    assert "@media(max-width:700px)" in css
    reduced = re.search(r"@media\(prefers-reduced-motion:reduce\)\{([^\n]*)\}", css).group(1)
    assert ".mcpp-track,.mcpp-knob{transition:none}" in reduced and ".mcpp-spin{animation:none}" in reduced
    assert ".mcpi[data-view=plugins] :is(" in css  # la vue interne s'efface, elle n'est pas démontée
    for selector in (".mcpp-switch:focus-visible", ".mcpp button.action:focus-visible", ".mcpv-tabs button:focus-visible"):
        assert selector in css
