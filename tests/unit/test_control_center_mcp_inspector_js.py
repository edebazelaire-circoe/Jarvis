"""Inspecteur MCP du Control Center (Slice 07 de jarvis-mcp-semantic-batch-inspector), exécuté par node.

Le module servi à la page (`jarvis/runtime/control_center_mcp_inspector.js`)
est exécuté tel quel contre les réponses RÉELLES de l'API du catalogue : la
liste et les descripteurs sont lus par `GET /api/mcp/tools[/{server}/{name}]`
sur un vrai `ControlCenter` (introspection `build_catalog()`), jamais écrits à la
main. Ce que ces tests prouvent (contrat `docs/mcp/tool-contract.md` §3, §4,
§10.6, §10.7) :

- onglets dans l'ordre des catégories, comptes exacts, Général vide qui le dit ;
- lignes compactes par défaut (libellé, nom, résumé, badges), dépliage par
  outil et global, détail chargé à la demande puis gardé ;
- table des paramètres fidèle à `parameters[]` (requis, défaut absent ≠ null,
  contraintes, structure imbriquée) ; schéma de sortie lisible sur les vrais
  schémas imbriqués (`SceneBatchResult`, colonnes de `scene_inspect`) ; schéma
  brut en dernier seulement ;
- recherche sur nom, libellé, résumé et noms de paramètres (imbriqués compris) ;
- états de chargement, d'erreur codée (503, 404, délai) et vides ;
- clavier : onglets aux flèches, lignes aux flèches, Échap ferme et rend le
  focus au bouton MCP ; piège de tabulation, reste de la page inerte ;
- lecture seule : aucune requête hors de `GET /api/mcp/tools…` ;
- le bouton du dock, la vue et le module sont dans la page servie.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import shutil
import subprocess
import unicodedata

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.runtime import barehands_test_mode, mcp_catalog
from jarvis.runtime.barehands_mcp import BarehandsMcpTarget
from jarvis.runtime.control_center import (
    MCP_INSPECTOR_SCRIPT_MARKER,
    MCP_TOOLS_ROUTE,
    ControlCenter,
)
from jarvis.runtime.display_mcp import DisplayMcpTarget
from jarvis.runtime.settings_mcp import ConsoleMcpTarget

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_mcp_inspector.js"
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"
WORK = ROOT / "jarvis" / "runtime" / "control_center_work.js"


# ----------------------------------------------------------------- harnais

def run_node(tmp_path: Path, source: str, data: object = None) -> object:
    """Exécuter `source` avec le module chargé sous `M` et les données sous `D`."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data_file = tmp_path / "mcpi-data.json"
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    script = tmp_path / "mcpi-test.cjs"
    script.write_text(
        f"const MODULE_PATH={json.dumps(str(MODULE))};\n"
        "const M=require(MODULE_PATH);\n"
        f"const D=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data_file))},'utf8'));\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const tick=()=>new Promise(r=>setImmediate(r));\n"
        "const cache=()=>{const c={};for(const [k,t] of Object.entries(D.details||{}))c[k]={state:'ok',tool:t};return c};\n"
        "(async()=>{" + source + "})().then(value=>out(value===undefined?null:value))"
        ".catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _center(root: Path) -> ControlCenter:
    """Un Control Center réel : scène et Bare Hands allumés, cerveau Claude en cours
    lancé SANS Bare Hands → `jarvis-barehands` configuré, redémarrage en attente."""

    runtime = root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    settings = {"scene": {"enabled": True},
                barehands_test_mode.SETTING_KEY: {barehands_test_mode.SCHEMA_KEY: barehands_test_mode.SCHEMA_VERSION,
                                                  "enabled": True}}
    (runtime / "control-center-settings.json").write_text(json.dumps(settings), encoding="utf-8")
    center = ControlCenter(
        runtime_root=runtime, project_root=root,
        display_mcp=DisplayMcpTarget("127.0.0.1", 47001, root / "core.token", runtime),
        barehands_mcp=BarehandsMcpTarget("127.0.0.1", 47002, runtime),
        console_mcp=ConsoleMcpTarget("127.0.0.1", 47002, runtime),
    )
    center.agent.snapshot = lambda: {"name": "Claude", "state": "running", "display_tools": True,  # type: ignore[method-assign]
                                     "barehands_tools": False, "console_tools": True}
    return center


async def _served(center: ControlCenter, paths: list[str]) -> list[tuple[int, dict]]:
    async with TestClient(TestServer(center._app)) as client:
        out = []
        for path in paths:
            response = await client.get(path)
            out.append((response.status, await response.json()))
        return out


@pytest.fixture(scope="module")
def payload(tmp_path_factory) -> dict:
    """La liste et chaque descripteur, tels que l'API servie les rend (vrai `build_catalog()`)."""

    center = _center(tmp_path_factory.mktemp("mcpi"))

    async def collect() -> dict:
        [(status, listing)] = await _served(center, [MCP_TOOLS_ROUTE])
        assert status == 200
        paths = [f"{MCP_TOOLS_ROUTE}/{t['server']}/{t['name']}" for t in listing["tools"]]
        answers = await _served(center, paths + [f"{MCP_TOOLS_ROUTE}/jarvis-display/nope"])
        details = {}
        for card, (code, body) in zip(listing["tools"], answers):
            assert code == 200
            details[f"{card['server']}/{card['name']}"] = body["tool"]
        return {"list": listing, "details": details, "unknown": answers[-1]}

    return asyncio.run(collect())


def _tool(payload: dict, name: str) -> dict:
    return next(t for k, t in payload["details"].items() if k.endswith("/" + name))


def _by(payload: dict, predicate) -> dict:
    """Le premier descripteur qui satisfait `predicate` : les tests ne présument d'aucun nom d'outil."""

    found = [t for t in payload["details"].values() if predicate(t)]
    assert found, "le catalogue réel n'a plus d'outil de cette forme : le test ne prouverait rien"
    return found[0]


# ------------------------------------------------------------ onglets, comptes

def test_tabs_follow_the_contract_categories_with_exact_counts(tmp_path, payload):
    answer = run_node(tmp_path, "return {tabs:M.tabsOf(D.list,'',{}),html:M.tabsHtml(M.tabsOf(D.list,'',{}),'scene','')}",
                      payload)
    categories = [c["category"] for c in payload["list"]["categories"]]
    assert [t["category"] for t in answer["tabs"]] == categories == ["general", "scene", "settings", "barehands", "external"]
    for tab in answer["tabs"]:
        expected = sum(1 for t in payload["list"]["tools"] if t["category"] == tab["category"])
        assert tab["total"] == tab["count"] == expected
    assert answer["tabs"][0]["total"] == 0  # aucun outil transversal aujourd'hui (§3)
    html = answer["html"]
    assert html.count('role="tab"') == 5
    assert 'id="mcpi-tab-scene" data-tab="scene" aria-selected="true"' in html and 'tabindex="0"' in html
    assert html.count('tabindex="-1"') == 4 and html.count('aria-controls="mcpiPanel"') == 5
    # Les libellés viennent de l'API, jamais du module.
    for category in payload["list"]["categories"]:
        assert category["label"] in html


def test_the_general_tab_is_an_overview_that_says_there_is_no_cross_domain_tool(tmp_path, payload):
    html = run_node(tmp_path, "return M.panelHtml({list:D.list,tab:'general',query:'',expanded:[],details:{}})", payload)
    assert "Outils transversaux" in html and "Aucun aujourd’hui" in html
    assert 'class="mcpi-list"' not in html
    for server in payload["list"]["servers"]:
        assert f"<code>{server['server']}</code>" in html
        assert f'data-tab="{server["category"]}"' in html  # chaque serveur mène à son onglet
    # Coût de contexte par serveur et état, y compris le redémarrage attendu.
    display = next(s for s in payload["list"]["servers"] if s["server"] == "jarvis-display")
    assert f"{display['context_bytes']:,}".replace(",", " ") + " o" in html
    assert "À prendre en compte au prochain (re)démarrage du brain" in html
    assert "Inspection seulement" in html


def test_the_header_summarises_servers_state_bytes_and_the_pending_restart(tmp_path, payload):
    answer = run_node(tmp_path, """return {chips:M.serversHtml(D.list),notice:M.pendingNotice(D.list),
      status:M.statusView({list:D.list})}""", payload)
    chips = answer["chips"]
    assert chips.count('class="mcpi-srv"') == len(payload["list"]["servers"])
    assert 'data-tone="warn"' in chips and "redémarrage" in chips  # jarvis-barehands, pending
    assert 'data-tone="ok"' in chips  # jarvis-display annoncé
    assert "Connu" in chips  # jarvis-drive, jamais prouvable
    assert answer["notice"].startswith("À prendre en compte au prochain (re)démarrage du brain : jarvis-barehands")
    assert answer["status"]["tone"] == "warn" and "28 outils" in answer["status"]["detail"]


# ------------------------------------------------------------ lignes compactes

def test_rows_are_compact_by_default_with_label_name_summary_and_badges(tmp_path, payload):
    html = run_node(tmp_path, "return M.panelHtml({list:D.list,tab:'scene',query:'',expanded:[],details:{}})", payload)
    scene = [t for t in payload["list"]["tools"] if t["category"] == "scene"]
    assert html.count('class="mcpi-row') == len(scene)
    assert html.count('aria-expanded="false"') == len(scene) and 'aria-expanded="true"' not in html
    assert html.count(" hidden>") == len(scene)  # aucun détail rendu tant qu'on ne déplie pas
    assert "Paramètres" not in html and "Schéma brut" not in html
    for card in scene:
        assert f'<code class="mcpi-wire">{card["name"]}</code>' in html
    assert html.count(">Lot atomique<") == sum(1 for t in scene if t["atomicity"] == "atomic_batch")
    assert html.count(">Destructif<") == sum(1 for t in scene if t["side_effect"] == "destructive")
    assert html.count(">Idempotent<") == sum(1 for t in scene if t["idempotent"])
    assert html.count(">Lecture<") == sum(1 for t in scene if t["side_effect"] == "read")
    # Serveur annoncé : son état n'est pas répété sur chaque ligne.
    assert ">Annoncé<" not in html
    # Bare Hands n'est pas annoncé (redémarrage attendu) : chaque ligne le dit.
    hands = run_node(tmp_path, "return M.panelHtml({list:D.list,tab:'barehands',query:'',expanded:[],details:{}})", payload)
    assert hands.count(">Configuré<") == sum(1 for t in payload["list"]["tools"] if t["category"] == "barehands")
    assert ">Déprécié<" in hands


def test_a_row_expands_to_the_lazy_detail_and_shows_loading_then_error_then_content(tmp_path, payload):
    batch = _by(payload, lambda t: t["atomicity"] == "atomic_batch" and any(p["constraints"].get("keys") for p in t["parameters"]))
    key = f"{batch['server']}/{batch['name']}"
    answer = run_node(tmp_path, f"""
      const card=D.list.tools.find(t=>M.toolKey(t)==={json.dumps(key)});
      return {{
        loading:M.cardHtml(card,5,{{expanded:true,detail:{{state:'loading',started:1000}},now:3400}}),
        error:M.cardHtml(card,5,{{expanded:true,detail:{{state:'error',error:Object.assign(new Error('unknown MCP tool'),{{code:'mcp_tool_unknown',status:404}})}}}}),
        done:M.cardHtml(card,5,{{expanded:true,detail:cache()[{json.dumps(key)}]}}),
      }}""", payload)
    assert 'aria-expanded="true"' in answer["loading"] and "Chargement du descripteur… <span>2,4 s</span>" in answer["loading"]
    assert 'role="status"' in answer["loading"]
    assert "Outil inconnu du catalogue" in answer["error"] and "mcp_tool_unknown · HTTP 404" in answer["error"]
    assert 'data-act="retry" data-retry="detail"' in answer["error"]
    done = answer["done"]
    assert 'id="mcpi-5-d" role="region" aria-labelledby="mcpi-5-t">' in done  # plus de `hidden`
    assert batch["qualified_name"] in done


# ------------------------------------------------------------ paramètres

def test_the_parameter_table_is_faithful_to_the_descriptor(tmp_path, payload):
    tool = _by(payload, lambda t: any(p["required"] for p in t["parameters"])
               and any(not p["required"] and p["has_default"] for p in t["parameters"]))
    html = run_node(tmp_path, f"return M.parametersHtml(D.details[{json.dumps(tool['server'] + '/' + tool['name'])}])", payload)
    rows = re.findall(r'<tr><th scope="row" data-label="Paramètre"><code>([^<]+)</code></th>(.*?)</tr>', html, re.S)
    assert [name for name, _ in rows] == [p["name"] for p in tool["parameters"]]
    for (name, cells), param in zip(rows, tool["parameters"]):
        assert f'<code class="mcpi-type">{param["type"]}</code>' in cells.replace("&lt;", "<").replace("&gt;", ">")
        assert ('<span class="chip on">requis</span>' in cells) is param["required"]
        assert ('<span class="mcpi-opt">facultatif</span>' in cells) is (not param["required"])
        default = re.search(r'data-label="Défaut">(.*?)</td>', cells).group(1)
        if param["has_default"]:
            assert default == f"<code>{json.dumps(param['default'])}</code>"
        else:
            assert "aucune valeur par défaut" in default  # absent ≠ null
    required = sum(1 for p in tool["parameters"] if p["required"])
    assert f"{required} requis" in html


def test_constraints_read_in_words_including_nested_structure(tmp_path, payload):
    tool = _by(payload, lambda t: any(p["constraints"].get("keys") for p in t["parameters"])
               and any("maxLength" in p["constraints"] for p in t["parameters"])
               and any("maxItems" in p["constraints"] for p in t["parameters"]))
    html = run_node(tmp_path, f"return M.parametersHtml(D.details[{json.dumps(tool['server'] + '/' + tool['name'])}])", payload)
    for param in tool["parameters"]:
        c = param["constraints"]
        if "maxLength" in c:
            assert f"≤ {c['maxLength']} caractères" in html
        if "minItems" in c and "maxItems" in c:
            assert f"{c['minItems']} à {c['maxItems']} éléments" in html
        if "enum" in c:
            assert "un de : " + ", ".join(c["enum"]) in html
        if c.get("keys"):
            assert f"Structure de <code>{param['name']}</code>" in html
            for key, info in c["keys"].items():
                assert f'<code class="mcpi-k">{key}</code>' in html
                for nested in (info.get("keys") or {}):
                    assert f'<code class="mcpi-k">{nested}</code>' in html
    assert html.count('<span class="mcpi-req">requis</span>') >= 1  # une clé imbriquée requise est marquée
    assert "$ref" not in html and "anyOf" not in html


def test_a_tool_without_parameters_says_so(tmp_path, payload):
    tool = _by(payload, lambda t: not t["parameters"])
    html = run_node(tmp_path, f"return M.parametersHtml(D.details[{json.dumps(tool['server'] + '/' + tool['name'])}])", payload)
    assert "Aucun paramètre" in html and "<table" not in html


# ------------------------------------------------------------ schéma de sortie

def test_the_batch_result_schema_reads_as_a_tree_not_raw_json(tmp_path, payload):
    tool = _by(payload, lambda t: (t["output"]["schema"] or {}).get("title") == "SceneBatchResult")
    schema = tool["output"]["schema"]
    html = run_node(tmp_path, f"return M.detailHtml(D.details[{json.dumps(tool['server'] + '/' + tool['name'])}])", payload)
    readable, raw = html.split('<details class="mcpi-raw">')
    for name in schema["properties"]:
        assert f'<code class="mcpi-k">{name}</code> <span class="{"mcpi-req" if name in schema["required"] else "mcpi-opt"}">' in readable
    # Les `$defs` sont résolus : les clés des objets imbriqués apparaissent sous leur parent.
    for definition in ("SceneBatchSkipped", "SceneBatchDelta", "SceneOffset"):
        for key in schema["$defs"][definition]["properties"]:
            assert f'<code class="mcpi-k">{key}</code>' in readable
    assert "objet SceneBatchDelta ou null" in readable or "objet SceneBatchDelta" in readable
    assert "liste de objet SceneBatchSkipped" in readable and "clés fermées" in readable
    assert '"$ref"' not in readable and '{"' not in readable
    # Le brut vient en dernier, replié, et contient bien les deux schémas.
    assert raw.startswith("<summary>Schéma brut (JSON)</summary>") and "&quot;$ref&quot;" in raw
    assert readable.index("<h4>Paramètres</h4>") < readable.index("<h4>Résultat</h4>")


def test_row_schemas_of_json_text_tools_read_as_titled_columns(tmp_path, payload):
    tool = _by(payload, lambda t: t["output"]["format"] == "json_text"
               and "prefixItems" in json.dumps(t["output"]["schema"]) and "oneOf" not in json.dumps(t["output"]["schema"]))
    rows = tool["output"]["schema"]["properties"]["o"]["items"]["prefixItems"]
    html = run_node(tmp_path, f"return M.schemaHtml(D.details[{json.dumps(tool['server'] + '/' + tool['name'])}].output.schema)", payload)
    assert f"ligne de {len(rows)} colonnes" in html
    for index, column in enumerate(rows, 1):
        assert f'<span class="mcpi-pos">{index}</span><code class="mcpi-k">{column["title"]}</code>' in html
    variants = _by(payload, lambda t: "oneOf" in json.dumps(t["output"]["schema"]))
    html = run_node(tmp_path, f"return M.schemaHtml(D.details[{json.dumps(variants['server'] + '/' + variants['name'])}].output.schema)", payload)
    assert "une des formes" in html and 'class="mcpi-tree mcpi-variants"' in html


def test_every_real_descriptor_renders_and_escapes(tmp_path, payload):
    answer = run_node(tmp_path, """
      const out={};for(const [k,t] of Object.entries(D.details)){const h=M.detailHtml(t);
        out[k]={raw:h.lastIndexOf('<details class="mcpi-raw">')>h.lastIndexOf('mcpi-schema'),script:/<script/i.test(h),
          format:h.includes('class="mcpi-format"')}}
      const evil=Object.assign({},Object.values(D.details)[0],{description:'<img src=x onerror=alert(1)>',label:'<b>x</b>'});
      out.evil=M.detailHtml(evil);return out""", payload)
    evil = answer.pop("evil")
    assert "<img" not in evil and "&lt;img src=x" in evil
    assert set(answer) == set(payload["details"])
    for key, facts in answer.items():
        assert facts == {"raw": True, "script": False, "format": True}, key


def test_the_deprecated_tool_names_its_replacement(tmp_path, payload):
    tool = _by(payload, lambda t: t["deprecation"])
    html = run_node(tmp_path, f"return M.detailHtml(D.details[{json.dumps(tool['server'] + '/' + tool['name'])}])", payload)
    assert "Outil déprécié." in html and f"Remplacé par <code>{tool['deprecation']['replacement']}</code>" in html


# ------------------------------------------------------------ recherche

def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))


def _searchable(term: str, tool: dict) -> bool:
    """Ce que la recherche doit trouver, recalculé ici : nom, libellé, résumé, serveur, paramètres (clés imbriquées)."""

    names: list[str] = []

    def walk(keys: dict, prefix: str) -> None:
        for name, info in (keys or {}).items():
            names.append(prefix + name)
            walk(info.get("keys") or (info.get("items") or {}).get("keys"), f"{prefix}{name}.")

    for param in tool["parameters"]:
        names.append(param["name"])
        c = param["constraints"]
        walk(c.get("keys") or (c.get("items") or {}).get("keys"), f"{param['name']}.")
    own = _fold(" ".join([tool["name"], tool["label"], tool["summary"].replace("**", ""), tool["server"]]))
    return _fold(term) in own or _fold(term) in _fold(" ".join(names))


def test_search_covers_name_label_summary_and_parameter_names(tmp_path, payload):
    nested = _by(payload, lambda t: any(p["constraints"].get("keys") for p in t["parameters"]))
    param = next(p for p in nested["parameters"] if p["constraints"].get("keys"))
    deep = next(iter(param["constraints"]["keys"]))
    label_word = payload["list"]["tools"][0]["label"].split()[0]
    answer = run_node(tmp_path, f"""
      const hits=(q,d)=>D.list.tools.filter(t=>M.matchOf(t,q,d[M.toolKey(t)]).hit).map(t=>t.name);
      return {{
        name:hits({json.dumps(nested['name'])},{{}}),
        label:hits({json.dumps(label_word.upper())},{{}}),
        none:hits('zzzz-rien',{{}}),
        paramCold:hits({json.dumps(deep)},{{}}),
        paramWarm:hits({json.dumps(deep)},cache()),
        why:M.matchOf(D.list.tools.find(t=>t.name==={json.dumps(nested['name'])}),{json.dumps(deep)},cache()[{json.dumps(nested['server'] + '/' + nested['name'])}]).why,
        accents:hits('etiqueter',{{}}).length===hits('étiqueter',{{}}).length,
        tabs:M.tabsOf(D.list,{json.dumps(deep)},cache()),
      }}""", payload)
    assert nested["name"] in answer["name"]
    assert answer["label"] and answer["none"] == []
    expected = sorted(t["name"] for t in payload["details"].values() if _searchable(deep, t))
    assert sorted(answer["paramWarm"]) == expected and nested["name"] in answer["paramWarm"]
    assert set(answer["paramCold"]) <= set(answer["paramWarm"])  # sans descripteur, pas de nom de paramètre
    assert answer["why"] and all(name.endswith(deep) or deep in name for name in answer["why"])
    assert answer["accents"] is True
    assert sum(t["count"] for t in answer["tabs"]) == len(expected)


def test_an_empty_search_in_a_tab_points_to_the_tabs_that_match(tmp_path, payload):
    settings = next(t for t in payload["list"]["tools"] if t["category"] == "settings")
    html = run_node(tmp_path, f"return M.panelHtml({{list:D.list,tab:'scene',query:{json.dumps(settings['name'])},expanded:[],details:cache()}})", payload)
    assert "Aucun outil de cet onglet ne correspond" in html
    assert 'data-tab="settings"' in html and 'data-act="clear"' in html
    nothing = run_node(tmp_path, "return M.panelHtml({list:D.list,tab:'scene',query:'zzzz',expanded:[],details:{}})", payload)
    assert "Aucun autre onglet non plus" in nothing and "descripteurs encore en lecture : 0/28" in nothing


# ------------------------------------------------------------ erreurs, client

def test_the_client_reads_only_the_catalog_with_get_and_keeps_coded_errors(tmp_path, payload):
    answer = run_node(tmp_path, """
      const calls=[];
      const reply=(status,body)=>({ok:status<400,status,text:async()=>JSON.stringify(body)});
      const fetchImpl=async(path,options)=>{calls.push({path,method:options.method,body:options.body===undefined});
        if(path.endsWith('/nope'))return reply(404,D.unknown[1]);
        if(path.includes('/jarvis-drive/'))return reply(503,D.unavailable);
        if(path===M.ROUTE)return reply(503,D.catalog);
        return reply(200,{ok:true,tool:{}})};
      const c=M.createClient({fetchImpl});
      const grab=async p=>{try{await p;return null}catch(e){return {code:e.code,status:e.status,message:e.message}}};
      const r={list:await grab(c.list()),unknown:await grab(c.get(M.ROUTE+'/jarvis-display/nope')),
        server:await grab(c.detail('jarvis-drive','drive_search')),
        outside:await grab(c.get('/api/scene/commands')),
        sneaky:await grab(c.get('/api/mcp/toolsX')),
        url:M.detailUrl('a/b','c?d#e'),calls};
      r.html=M.errorHtml(Object.assign(new Error(r.list.message),r.list));
      /* Délai : une requête qui ne répond jamais finit en erreur « timeout ». */
      const slow=M.createClient({fetchImpl:(p,o)=>new Promise((_,rej)=>o.signal.addEventListener('abort',()=>rej(new Error('aborted')))),deadlineMs:20});
      r.timeout=await grab(slow.list());
      const down=M.createClient({fetchImpl:async()=>{throw new TypeError('Failed to fetch')}});
      r.network=await grab(down.list());
      return r""", {**payload,
                    "unavailable": {"ok": False, "code": "mcp_server_unavailable",
                                    "error": "MCP server not describable (ModuleNotFoundError)", "server": "jarvis-drive"},
                    "catalog": {"ok": False, "code": "mcp_catalog_unavailable",
                                "error": "MCP catalog could not be built (LookupError)"}})
    assert payload["unknown"][0] == 404
    assert answer["list"] == {"code": "mcp_catalog_unavailable", "status": 503,
                              "message": "MCP catalog could not be built (LookupError)"}
    assert answer["unknown"]["code"] == "mcp_tool_unknown" and answer["unknown"]["status"] == 404
    assert answer["server"]["code"] == "mcp_server_unavailable"
    assert answer["outside"]["code"] == "forbidden_route" and answer["sneaky"]["code"] == "forbidden_route"
    assert answer["url"] == "/api/mcp/tools/a%2Fb/c%3Fd%23e"  # deux segments, chacun encodé
    assert answer["calls"] and all(c["method"] == "GET" and c["body"] for c in answer["calls"])
    assert all(c["path"].startswith("/api/mcp/tools") for c in answer["calls"])
    assert "Catalogue MCP indisponible" in answer["html"] and "mcp_catalog_unavailable · HTTP 503" in answer["html"]
    assert "mcp.catalog_failed" in answer["html"] and 'data-act="retry"' in answer["html"]
    assert answer["timeout"]["code"] == "timeout" and answer["network"]["code"] == "network"


def test_list_loading_shows_motion_label_and_elapsed_time(tmp_path, payload):
    answer = run_node(tmp_path, "return {html:M.listLoadingHtml(1250),status:M.statusView({loading:true,elapsedMs:1250})}", payload)
    assert "Chargement du catalogue MCP… <span>1,3 s</span>" in answer["html"] and 'aria-hidden="true"' in answer["html"]
    assert answer["status"] == {"tone": "busy", "label": "Chargement…", "detail": "1,3 s"}


def test_an_undescribable_server_is_said_not_guessed(tmp_path, payload):
    listing = json.loads(json.dumps(payload["list"]))
    drive = next(s for s in listing["servers"] if s["category"] == "external")
    drive.update(described=False, error="ModuleNotFoundError", tool_count=0, context_bytes=0)
    listing["tools"] = [t for t in listing["tools"] if t["server"] != drive["server"]]
    html = run_node(tmp_path, "return M.panelHtml({list:D,tab:'external',query:'',expanded:[],details:{}})+M.serversHtml(D)", listing)
    assert "Descripteur indisponible" in html and "ModuleNotFoundError" in html and 'data-tone="bad"' in html
    assert 'class="mcpi-list"' not in html


# ------------------------------------------------------------ clavier

def test_arrow_keys_move_between_tabs_and_rows():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    source = (f"const M=require({json.dumps(str(MODULE))});process.stdout.write(JSON.stringify(["
              "M.tabKey('ArrowRight',4,5),M.tabKey('ArrowLeft',0,5),M.tabKey('Home',3,5),M.tabKey('End',0,5),M.tabKey('a',1,5),"
              "M.cardKey('ArrowDown',2,3),M.cardKey('ArrowUp',0,3),M.cardKey('ArrowDown',0,3),M.cardKey('Enter',0,3)]))")
    completed = subprocess.run([node, "-e", source], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [0, 4, 0, 4, None, 2, 0, 1, None]


#: Un DOM minimal : assez pour que le bloc navigateur s'installe, charge, rende
#: et réponde au clavier. Les listes (`[role="tab"]`, `.mcpi-toggle`) sont lues
#: dans le HTML que le module vient d'écrire, comme le ferait le navigateur.
DOM_STUB = r"""
const listeners={},cache={};let focused=null;
function attrs(html,re){const out=[];let m;while((m=re.exec(html)))out.push(m);return out}
function node(id){
  const self={id,hidden:id==='mcpInspector',inert:false,textContent:'',className:'',isConnected:true,disabled:false,
    style:{},dataset:{},tabIndex:0,offsetParent:{},value:'',tagName:'DIV',_html:'',
    classList:{add(){},remove(){},contains(){return false}},setAttribute(k,v){self['@'+k]=v},getAttribute(k){return self['@'+k]??null},
    focus(){focused=id},contains(){return true},closest(){return null},
    addEventListener(kind,fn){(listeners[id]=listeners[id]||{})[kind]=fn},
    querySelector(selector){return pick(selector.startsWith('#')?selector.slice(1):id+' '+selector)},
    querySelectorAll(selector){
      if(selector==='[role="tab"]')return attrs(self._html,/role="tab" id="([^"]+)" data-tab="([^"]+)"/g).map(m=>{const b=pick(m[1]);b.dataset={tab:m[2]};return b});
      if(selector==='.mcpi-toggle')return attrs(self._html,/class="mcpi-toggle" id="([^"]+)" data-key="([^"]+)"/g).map(m=>{const b=pick(m[1]);b.dataset={key:m[2]};
        b.classList={contains:c=>c==='mcpi-toggle'};b.closest=s=>s.includes('mcpi-toggle')||s==='button'?b:null;return b});
      return [];
    }};
  Object.defineProperty(self,'innerHTML',{set(v){self._html=String(v)},get(){return self._html}});
  return self;
}
function pick(id){return cache[id]=cache[id]||node(id)}
const calls=[];
const reply=(status,body)=>({ok:status<400,status,text:async()=>JSON.stringify(body)});
global.window={addEventListener(){},requestAnimationFrame(fn){fn()},
  fetch:async(path,options)=>{calls.push({path,method:(options&&options.method)||'GET'});
    if(path===M.ROUTE)return reply(200,D.list);
    const [server,name]=path.slice(M.ROUTE.length+1).split('/').map(decodeURIComponent);
    return reply(200,{ok:true,tool:D.details[server+'/'+name]})}};
global.requestAnimationFrame=fn=>fn();
global.document={getElementById:pick,body:{children:[pick('app'),pick('mcpInspector')]},
  get activeElement(){return focused?pick(focused):null},addEventListener(){}};
delete require.cache[require.resolve(MODULE_PATH)];
require(MODULE_PATH);
const I=global.window.JarvisMcpInspector;
const key=(id,k,target)=>{let prevented=false;listeners[id].keydown({key:k,target:target||pick(focused),preventDefault(){prevented=true},stopPropagation(){}});return prevented};
const settle=async()=>{for(let i=0;i<60;i++)await tick()};
"""


def test_the_browser_block_opens_loads_expands_and_answers_the_keyboard(tmp_path, payload):
    answer = run_node(tmp_path, DOM_STUB + """
      pick('openMcpInspector').focus();
      I.open();await settle();
      const r={opened:{hidden:pick('mcpInspector').hidden,appInert:pick('app').inert,
        expanded:pick('openMcpInspector')['@aria-expanded'],focus:focused,tab:I.state.tab}};
      r.tabs=pick('mcpiTabs').innerHTML;r.servers=pick('mcpiServers').innerHTML;
      r.notice={hidden:pick('mcpiNotice').hidden,text:pick('mcpiNotice').textContent};
      /* Onglets au clavier : flèche droite depuis Général → Étoiles / Scène, focus suivi. */
      pick('mcpi-tab-general').focus();
      r.arrow=key('mcpiTabs','ArrowRight');r.afterArrow={tab:I.state.tab,focus:focused};
      key('mcpiTabs','End');r.end=I.state.tab;key('mcpiTabs','Home');r.home=I.state.tab;
      key('mcpiTabs','ArrowRight');
      /* Une ligne : clic (Entrée/Espace natifs du <button>) → détail chargé, gardé. */
      const toggles=pick('mcpiPanel').querySelectorAll('.mcpi-toggle');
      r.rows=toggles.length;
      const first=toggles[0];
      listeners.mcpiPanel.click({target:first});await settle();
      r.afterToggle={expanded:[...I.state.expanded],state:I.state.details[first.dataset.key].state,
        panelHasTable:pick('mcpiPanel').innerHTML.includes('class="mcpi-params"')};
      const before=calls.length;
      listeners.mcpiPanel.click({target:first});listeners.mcpiPanel.click({target:first});await settle();
      r.cached=calls.length===before;
      /* Lignes au clavier. */
      first.focus();r.down=key('mcpiPanel','ArrowDown',first);r.downFocus=focused;
      /* Tout déplier puis tout replier. */
      listeners.mcpiExpandAll.click({});await settle();
      r.all={count:I.state.expanded.size,label:pick('mcpiExpandAll').textContent};
      listeners.mcpiExpandAll.click({});
      r.none={count:I.state.expanded.size,label:pick('mcpiExpandAll').textContent};
      /* Recherche : indexe les descripteurs et compte par onglet. */
      pick('mcpiSearch').value='select';listeners.mcpiSearch.input({});await settle();
      r.search={query:I.state.query,announce:pick('mcpiAnnounce').textContent,tabs:pick('mcpiTabs').innerHTML};
      /* Tab au dernier élément : piège (aucun élément filtré ici ⇒ pas d'effet), Échap ferme. */
      r.esc=key('mcpInspector','Escape',pick('mcpiSearch'));
      r.closed={hidden:pick('mcpInspector').hidden,appInert:pick('app').inert,focus:focused,
        expanded:pick('openMcpInspector')['@aria-expanded'],open:I.state.open};
      r.calls=calls;r.handle=Object.keys(I).sort();
      return r""", payload)
    assert answer["opened"] == {"hidden": False, "appInert": True, "expanded": "true", "focus": "mcpiSearch", "tab": "general"}
    assert answer["tabs"].count('role="tab"') == 5 and answer["servers"].count("mcpi-srv") >= 4
    assert answer["notice"]["hidden"] is False and "jarvis-barehands" in answer["notice"]["text"]
    assert answer["arrow"] is True and answer["afterArrow"] == {"tab": "scene", "focus": "mcpi-tab-scene"}
    assert answer["end"] == "external" and answer["home"] == "general"
    assert answer["rows"] == sum(1 for t in payload["list"]["tools"] if t["category"] == "scene")
    assert answer["afterToggle"]["state"] == "ok" and answer["afterToggle"]["panelHasTable"] is True
    assert answer["cached"] is True  # replier/redéplier ne relit pas le descripteur
    assert answer["down"] is True and answer["downFocus"] == "mcpi-1-t"
    assert answer["all"]["count"] == answer["rows"] and answer["all"]["label"] == "Tout replier"
    assert answer["none"] == {"count": 0, "label": "Tout déplier"}
    assert answer["search"]["query"] == "select" and "correspond" in answer["search"]["announce"]
    assert answer["esc"] is True
    assert answer["closed"] == {"hidden": True, "appInert": False, "focus": "openMcpInspector",
                                "expanded": "false", "open": False}
    assert answer["handle"] == ["close", "open", "state"]
    # Lecture seule : que des GET, que le catalogue, chaque détail à deux segments.
    for call in answer["calls"]:
        assert call["method"] == "GET"
        assert call["path"] == MCP_TOOLS_ROUTE or re.fullmatch(re.escape(MCP_TOOLS_ROUTE) + r"/[^/]+/[^/]+", call["path"])
    assert len({c["path"] for c in answer["calls"]}) == len(answer["calls"])  # aucun descripteur lu deux fois


# ------------------------------------------------------------ source et page

def test_the_module_parses_and_contains_no_tool_name_nor_write():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    completed = subprocess.run([node, "--check", str(MODULE)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    source = MODULE.read_text(encoding="utf-8")
    catalog = asyncio.run(mcp_catalog.build_catalog())
    for tool in catalog["tools"]:
        assert not re.search(rf"\b{re.escape(tool['name'])}\b", source), tool["name"]  # contrat §5.1
    assert not re.search(r"method\s*:\s*['\"](POST|PUT|PATCH|DELETE)", source)
    assert "api(" not in source  # le client de la page n'est pas utilisé : GET seul, par construction
    # Un seul appel réseau, celui du client ; le navigateur lui prête `window.fetch`, rien d'autre.
    assert re.findall(r"fetch\w*\(", source) == ["fetchImpl(", "fetch("]
    assert "createClient({fetchImpl:(path,options)=>window.fetch(path,options)})" in source


@pytest.mark.asyncio
async def test_the_served_page_carries_the_dock_button_the_dialog_and_the_module(tmp_path):
    center = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = (await center.index(None)).text
    assert MCP_INSPECTOR_SCRIPT_MARKER not in html, "le repère n'a pas été remplacé"
    assert "const JarvisMcpInspectorCore=" in html
    assert html.index("const JarvisTestLabCore=") < html.index("const JarvisMcpInspectorCore=")
    dock = html[html.index('<nav class="dock"'): html.index("</nav>", html.index('<nav class="dock"'))]
    order = re.findall(r">([A-Z]{3})</button>", dock)
    assert order == ["ERR", "TRC", "LAB", "CNV", "SET", "MCP", "AGT"]
    button = re.search(r'<button id="openMcpInspector"[^>]*>MCP</button>', dock).group(0)
    for attribute in ('aria-haspopup="dialog"', 'aria-expanded="false"', 'aria-controls="mcpInspector"', "aria-label="):
        assert attribute in button
    view = html[html.index('<section class="mcpi"'): html.index("</section>", html.index('<section class="mcpi"'))]
    for attribute in ('role="dialog"', 'aria-modal="true"', 'aria-labelledby="mcpiTitle"', 'aria-describedby="mcpiHelp"', " hidden>"):
        assert attribute in view
    assert 'role="tablist"' in view and 'role="tabpanel"' in view and 'aria-live="polite"' in view


def test_every_element_the_browser_block_reaches_for_exists_in_the_page():
    source = MODULE.read_text(encoding="utf-8")
    browser = source[source.index("(function installJarvisMcpInspector(){"):]
    html = PAGE.read_text(encoding="utf-8")
    wanted = set(re.findall(r"q\('#([A-Za-z0-9_]+)'\)", browser)) | set(re.findall(r"getElementById\('([A-Za-z0-9_]+)'\)", browser))
    assert wanted, "aucun identifiant trouvé : le test ne prouverait rien"
    assert sorted(name for name in wanted if f'id="{name}"' not in html) == []


def test_page_shortcuts_never_cross_the_open_inspector():
    html = PAGE.read_text(encoding="utf-8")
    handler = html[html.index("window.addEventListener('keydown',event=>{\n  if(SET.capture"):]
    handler = handler[: handler.index("\n});")]
    assert handler.index("if(mcpInspector&&!mcpInspector.hidden)return;") < handler.index("const match=")


def test_the_view_uses_page_tokens_is_responsive_and_respects_reduced_motion():
    html = PAGE.read_text(encoding="utf-8")
    css = html[html.index("/* ---------- Inspecteur MCP"): html.index("</style>")]
    # Aucune nouvelle couleur de marque : accent, danger, avertissement viennent des jetons.
    assert "var(--accent)" in css and "var(--line)" in css and "--mcpi" not in css
    assert not re.search(r"#6ee7ff|#ff6577|#ffb85c|#68e0a0", css, re.I)
    assert "@media(max-width:700px)" in css and "@media(max-width:900px)" in css
    reduced = re.search(r"@media\(prefers-reduced-motion:reduce\)\{([^\n]*)\}", css).group(1)
    assert ".mcpi-chev{transition:none}" in reduced and ".mcpi-skel span{animation:none}" in reduced
    assert re.search(r"\.mcpi\{position:fixed;inset:0;z-index:55;", css)  # rang des vues plein écran


def test_the_cosmos_theme_draws_the_mcp_tool_like_its_neighbours():
    work = WORK.read_text(encoding="utf-8")
    assert "['openMcpInspector','mcp',4]" in work and "mcp:`<svg ${common}>" in work
