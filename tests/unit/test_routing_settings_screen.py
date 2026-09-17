"""L'écran d'aiguillage : décrit par le serveur, enregistré par le serveur.

Ce que ces tests défendent : la page ne connaît aucun modèle, un enregistrement
refusé ne touche à rien, et régler l'aiguillage ne déplace pas un seul réglage
vocal ou CLI au passage.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import time

import pytest
from aiohttp import web

from jarvis.domain import routing
from jarvis.runtime import agent_routing, cli_catalog
from jarvis.runtime.control_center import SETTINGS_ERROR_CODE_HEADER, ControlCenter

PAGE = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html"


class QueryRequest:
    def __init__(self, **query: str) -> None:
        self.query = query


class PostRequest:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def json(self) -> dict:
        return self._payload


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


async def settings_of(control: ControlCenter) -> dict:
    return json.loads((await control.get_settings(None)).text)


async def save(control: ControlCenter, payload: dict) -> dict:
    return json.loads((await control.save_settings(PostRequest(payload))).text)


# ------------------------------------------------------------------ serveur


async def test_the_routing_screen_is_described_by_the_server(control):
    payload = (await settings_of(control))["routing"]

    assert payload["enabled"] is False
    assert [entry["id"] for entry in payload["profiles"]] == list(routing.TASK_PROFILE_IDS)
    assert all(entry["label"] and entry["description"] for entry in payload["profiles"])
    assert set(payload["policy"]) == set(routing.TASK_PROFILE_IDS)
    # Les candidats ne sont pas dans ce GET : les lister demande de sonder les
    # CLI et d'appeler les fournisseurs.
    assert payload["candidates"] == []


async def test_a_routing_policy_is_saved_and_read_back_without_touching_the_rest(control):
    before = await settings_of(control)

    after = await save(
        control,
        {"routing": {"enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude", "model": "m1"}]}}}},
    )

    assert after["routing"]["enabled"] is True
    assert after["routing"]["policy"]["code"]["candidates"] == [{"agent": "claude", "model": "m1"}]
    # Rien d'autre n'a bougé : ni la voix, ni l'audio. Le CLI expose la
    # projection canonique du même switch routing, sans second stockage.
    for section in ("voice", "audio"):
        assert after[section] == before[section]
    assert after["cli"] == {**before["cli"], "delegation_mode": "auto"}
    # Et c'est bien écrit sur le disque, pas seulement en mémoire.
    stored = json.loads((control.runtime_root / "control-center-settings.json").read_text(encoding="utf-8"))
    assert agent_routing.load_policy(stored).enabled is True


async def test_a_refused_policy_leaves_the_previous_one_intact(control):
    await save(control, {"routing": {"enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude"}]}}}})

    with pytest.raises(web.HTTPBadRequest) as error:
        await save(control, {"routing": {"profiles": {"code": {"candidates": [{"agent": "astra"}]}}}})

    assert error.value.headers[SETTINGS_ERROR_CODE_HEADER] == "routing_unknown_agent"
    payload = await settings_of(control)
    assert payload["routing"]["policy"]["code"]["candidates"] == [{"agent": "claude", "model": ""}]
    assert payload["routing"]["enabled"] is True


async def test_the_candidates_endpoint_measures_instead_of_assuming(control, monkeypatch):
    async def fake_detect(commands):
        assert set(commands) == set(cli_catalog.AGENT_CLI_IDS)
        return [
            {"id": "claude", "label": "Claude Code", "model_provider": "anthropic", "available": True, "error": "", "path": "/bin/claude"},
            {"id": "codex", "label": "Codex CLI", "model_provider": "openai", "available": False, "error": "introuvable", "path": ""},
        ]

    async def fake_models(provider, api_key, **kwargs):
        if provider != "anthropic":
            raise __import__("jarvis.runtime.model_catalog", fromlist=["x"]).CatalogError("catalog_no_key", "pas de clé")
        return {
            "provider": provider,
            "models": [{"id": "m1", "label": "M1", "roles": ("text",)}],
            "source": "live",
            "fetched_at": time.time(),
        }

    monkeypatch.setattr(cli_catalog, "detect_all", fake_detect)
    monkeypatch.setattr(control.catalog, "models", fake_models)
    monkeypatch.setattr(control.catalog, "cached", lambda provider: None)

    payload = json.loads((await control.routing_candidates(None)).text)

    keys = [(item["agent"], item["model"]) for item in payload["candidates"]]
    assert ("claude", "m1") in keys
    claude = next(item for item in payload["candidates"] if item == payload["candidates"][0])
    assert claude["available"] is True
    # Le CLI absent est décrit, pas caché : l'utilisateur doit savoir pourquoi.
    codex = [item for item in payload["candidates"] if item["agent"] == "codex"]
    assert codex and all(not item["available"] and item["unavailable_reason"] for item in codex)
    assert payload["sources"]["openai"] == "catalog_no_key"
    # Les capacités viennent de la fiche du CLI, pas du modèle.
    assert routing.CODE in claude["capabilities"]
    # Et le même état, rangé par harness, pour le choix en deux étapes.
    harnesses = {group["id"]: group for group in payload["harnesses"]}
    assert set(harnesses) == {"claude", "codex"}
    assert "m1" in [entry["model"] for entry in harnesses["claude"]["models"]]
    assert harnesses["codex"]["available"] is False and harnesses["codex"]["unavailable_reason"]


async def test_a_saved_candidate_that_vanished_is_still_shown(control, monkeypatch):
    await save(control, {"routing": {"profiles": {"code": {"candidates": [{"agent": "claude", "model": "disparu"}]}}}})

    async def fake_detect(commands):
        return [{"id": "claude", "label": "Claude", "model_provider": "anthropic", "available": True, "error": ""}]

    async def fake_models(provider, api_key, **kwargs):
        return {
            "provider": provider,
            "models": [{"id": "m1", "label": "M1", "roles": ("text",)}],
            "source": "live",
            "fetched_at": time.time(),
        }

    monkeypatch.setattr(cli_catalog, "detect_all", fake_detect)
    monkeypatch.setattr(control.catalog, "models", fake_models)

    payload = json.loads((await control.routing_candidates(None)).text)

    ghost = next(item for item in payload["candidates"] if item["model"] == "disparu")
    assert ghost["available"] is False and ghost["unavailable_reason"]


async def test_no_secret_ever_reaches_the_routing_payload(control, monkeypatch):
    async def fake_detect(commands):
        return [{"id": "claude", "label": "Claude", "model_provider": "anthropic", "available": True, "error": ""}]

    async def fake_models(provider, api_key, **kwargs):
        return {
            "provider": provider,
            "models": [{"id": "m1", "roles": ("text",)}],
            "source": "live",
            "fetched_at": time.time(),
            "key_hint": "…9ab",
        }

    monkeypatch.setattr(cli_catalog, "detect_all", fake_detect)
    monkeypatch.setattr(control.catalog, "models", fake_models)

    body = (await control.routing_candidates(None)).text

    assert "key_hint" not in body and "9ab" not in body


# ------------------------------------------------------------------- page


def test_the_advanced_agent_section_never_writes_a_model_or_profile_of_its_own():
    """Un nom de modèle codé dans le HTML périmerait sans que personne le voie."""

    page = PAGE.read_text(encoding="utf-8")
    start = page.index("function routingAdvancedBody()")
    body = page[start : page.index("/* --- onglet Config", start)]

    for invented in ("opus", "sonnet", "haiku", "gpt-", "astra", "luna", "claude-"):
        assert invented not in body.lower(), invented
    # Les profils viennent du serveur : la page itère, elle ne les nomme pas.
    assert "state.profiles" in body
    assert "profile.label" in body and "profile.description" in body


def test_the_page_shows_why_a_candidate_cannot_be_used():
    page = PAGE.read_text(encoding="utf-8")
    body = page[page.index("function routingRow(") : page.index("function routingAdvancedBody()")]

    assert "unavailable_reason" in body
    assert "indisponible" in body
    # Les candidats affichés sont ceux qu'on a retenus, disponibles ou non : un
    # enregistrement devenu inutilisable reste listé, avec sa raison.
    assert "data-routing-drop" in body




def test_policy_ui_is_advanced_inside_agent_cli_and_saved_canonically():
    page = PAGE.read_text(encoding="utf-8")

    assert re.search(r"\{id:'cli',label:'Agent / CLI',save:true\}", page)
    assert "id:'routing'" not in page
    assert "Configuration avancée des sous-agents" in page
    # Awaited panels publish only after the render revision guard; an older
    # catalog response cannot overwrite a newly selected voice architecture.
    assert "else if(SET.tab==='cli')content=tabCli()" in page
    assert "if(revision!==SET.renderRevision||SET.open===false)return" in page
    # Le brouillon envoie le mode via cli, jamais le switch historique en double.
    assert "delegation_mode:data.cli.delegation_mode" in page
    assert "routing:{profiles:JSON.parse(JSON.stringify(data.routing.policy))}" in page
    assert "routing:{enabled:data.routing.enabled" not in page


# --------------------------------------------------------------------------
# Ce que fait l'écran, pas comment il est écrit.
#
# Ces deux tests-là épinglaient le texte source par des noms de fonctions et de
# variables hérités de l'époque où l'aiguillage était un onglet. Ils exécutent
# maintenant le rendu et les gestes de la page sous node : mêmes exigences de
# comportement, plus aucune contrainte sur la façon de nommer.

_NODE = shutil.which("node")

HELPERS_FROM, HELPERS_TO = "function candidateKey(", "function routingAdvancedShell("
FOCUS_FROM, FOCUS_TO = "function routingFocusTarget(", "function renderRoutingAdvanced("
RENDER_FROM, RENDER_TO = "function renderRoutingAdvanced(", "function bindDelegationMode("
BIND_FROM, BIND_TO = "function bindRoutingAdvanced(", "async function hydrateRoutingAdvanced"

PRELUDE = r"""
const esc=value=>String(value===undefined||value===null?'':value)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const selectOptions=(values,selected,placeholder)=>
  (placeholder?`<option value="">${placeholder}</option>`:'')+
  values.map(v=>`<option value="${esc(v.value)}"${String(selected)===String(v.value)?' selected':''}>${esc(v.label)}</option>`).join('');
const providerLabel=p=>String(p);
const says=[];let renders=0,FOCUSED=null;
const say=text=>{says.push(text)};
function renderRoutingAdvanced(revision){renders++}
function hydrateRoutingAdvanced(){}
function el(dataset){
  return {dataset:{...dataset},value:'',checked:false,disabled:false,
    _h:{},addEventListener(type,fn){(this._h[type]||(this._h[type]=[])).push(fn)},
    fire(type){for(const fn of this._h[type]||[])fn()},focus(){FOCUSED=this}};
}
const attrKey=sel=>sel.replace(/^\[data-/,'').replace(/\]$/,'').replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
/* Reconstituer les commandes à partir du HTML rendu : mêmes attributs, même
   état `disabled`, dans le même ordre. */
function parseBody(html){
  const nodes=[],tags=/<(select|button|input)\b([^>]*)>/g;
  let tag;
  while((tag=tags.exec(html))){
    const attrs=tag[2],dataset={},data=/data-([a-z-]+)="([^"]*)"/g;
    let found;
    while((found=data.exec(attrs)))dataset[attrKey('[data-'+found[1]+']')]=found[2];
    if(!Object.keys(dataset).length)continue;
    const node=el(dataset);
    node.disabled=/(^|\s)disabled(\s|>|$)/.test(attrs);
    node.checked=/(^|\s)checked(\s|>|$)/.test(attrs);
    nodes.push(node);
  }
  return nodes;
}
function makeBody(list){
  const body={list,_html:'',
    get innerHTML(){return body._html},
    set innerHTML(html){body._html=html;body.list=parseBody(html)},
    querySelectorAll(sel){
      if(sel.charAt(0)!=='[')return [];
      const key=attrKey(sel);
      return body.list.filter(node=>node.dataset[key]!==undefined);
    },
    querySelector(sel){return body.querySelectorAll(sel)[0]||null},
    contains(node){return body.list.indexOf(node)>=0}};
  return body;
}
/* Le contenu d'un `<select>` désigné par un de ses attributs : c'est la seule
   façon de vérifier ce que propose *ce* sélecteur, sans ramasser au passage
   les options du sélecteur voisin. */
const selectSlice=(html,attribute)=>{
  const at=html.indexOf(attribute);
  if(at<0)return '';
  return html.slice(html.lastIndexOf('<select',at),html.indexOf('</select>',at)+9);
};
const optionValues=html=>[...html.matchAll(/<option value="([^"]*)"/g)].map(m=>m[1]);
const STATE={ok:true,sources:{anthropic:'live'},profiles:[
    {id:'code',label:'Code avancé',description:'Lire et écrire du code.',requires:['code']}],
  harnesses:[
    {id:'claude',label:'Claude Code',available:true,unavailable_reason:'',
     models:[{model:'',label:'Modèle par défaut du CLI',available:true,unavailable_reason:''},
             {model:'modele-a',label:'Modèle A',available:true,unavailable_reason:''},
             {model:'modele-b',label:'Modèle B',available:true,unavailable_reason:''}]},
    {id:'codex',label:'Codex CLI',available:false,unavailable_reason:'« codex » est introuvable dans le PATH.',
     models:[{model:'',label:'Modèle par défaut du CLI',available:false,unavailable_reason:'introuvable'},
             {model:'modele-o',label:'Modèle O',available:false,unavailable_reason:'introuvable'}]}]};
const SET={routingPick:{},dirty:false,routing:null,open:true,tab:'cli',renderRevision:1,routingAdvancedOpen:true,
  draft:{routing:{profiles:{code:{candidates:[],enabled:true,allow_general_fallback:true}}}}};
let BODY=makeBody([]);
const $=()=>BODY;
const currentAgentTab=()=>true;
const document={activeElement:null};
const copy=()=>JSON.parse(JSON.stringify(SET.draft.routing.profiles.code.candidates||[]));
const find=sel=>BODY.querySelector(sel);
"""

BIND_HARNESS = """
BODY=makeBody([
  el({routingProfileEnabled:'code'}),
  el({routingHarness:'code',routingFocus:'harness|code'}),
  el({routingModel:'code',routingFocus:'model|code'}),
  el({routingAdd:'code',routingFocus:'add|code'}),
  el({routingDrop:'code',routingRank:'0',routingFocus:'drop|code|claude|modele-a'}),
  el({routingUp:'code',routingRank:'1',routingFocus:'up|code|claude|modele-b'}),
  el({routingFallback:'code'}),
]);
bindRoutingAdvanced(1);
"""


def slice_of(page: str, start: str, end: str) -> str:
    return page[page.index(start):page.index(end)]


def run_routing(tmp_path: Path, source: str, *, renderer: bool = False):
    """Exécuter le rendu et les gestes de la section, tirés de la page servie.

    `renderer` embarque en plus le vrai `renderRoutingAdvanced`, qui remplace
    alors le compteur du banc : c'est lui qui redessine et rend le focus.
    """
    if _NODE is None:
        pytest.skip("node absent")
    page = PAGE.read_text(encoding="utf-8")
    script = tmp_path / "routing-ui.cjs"
    script.write_text(
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        + PRELUDE
        + slice_of(page, HELPERS_FROM, HELPERS_TO)
        + slice_of(page, FOCUS_FROM, FOCUS_TO)
        + slice_of(page, BIND_FROM, BIND_TO)
        + (slice_of(page, RENDER_FROM, RENDER_TO) if renderer else "")
        + "(()=>{" + source + "})();",
        encoding="utf-8",
    )
    completed = subprocess.run([_NODE, str(script)], capture_output=True, text=True,
                               encoding="utf-8", timeout=60, check=False)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_the_choice_is_made_in_two_steps_harness_then_model(tmp_path):
    """Une liste unique de tous les couples harness × modèle est inutilisable :
    on choisit le harness, puis un modèle parmi les siens.

    Ce que rend la page, pas comment elle est écrite : on exécute le rendu et on
    lit le résultat.
    """

    page = PAGE.read_text(encoding="utf-8")
    result = run_routing(tmp_path, """
      SET.routingPick={};
      const nothing=routingPicker('code',STATE);
      SET.routingPick={code:{agent:'claude',model:''}};
      const chosen=routingPicker('code',STATE);
      SET.routingPick={code:{agent:'codex',model:''}};
      const broken=routingPicker('code',STATE);
      out({nothing,chosen,broken,
        chosenModels:optionValues(selectSlice(chosen,'data-routing-model')),
        chosenHarnesses:optionValues(selectSlice(chosen,'data-routing-harness'))});
    """)

    # Tant qu'aucun harness n'est choisi, il n'y a rien à choisir au second cran.
    assert "Choisir d'abord un harness" in result["nothing"]
    assert "data-routing-model" not in result["nothing"]
    assert "data-routing-harness" in result["nothing"]
    for harness in ("Claude Code", "Codex CLI"):
        assert harness in result["nothing"]
    # Harness choisi : le second sélecteur n'offre que ses modèles, et rien
    # d'autre. Les deux assertions portent sur les *valeurs* du seul sélecteur
    # de modèles : un libellé peut être décoré (« — indisponible ») et les
    # options du sélecteur de harness ne doivent pas être comptées avec.
    assert "data-routing-model" in result["chosen"]
    models = set(result["chosenModels"])
    assert "modele-o" not in models
    assert {"modele-a", "modele-b"} <= models
    assert set(result["chosenHarnesses"]) == {"", "claude", "codex"}
    # Un harness éteint reste proposé, dit pourquoi, et prévient avant l'ajout.
    assert "introuvable" in result["broken"] and "data-routing-unusable" in result["broken"]
    # Et la liste plate de toutes les combinaisons n'existe plus.
    assert "data-routing-candidate" not in page


def test_changing_the_harness_clears_the_model_and_only_adding_changes_the_policy(tmp_path):
    """Choisir ne modifie rien ; seul « ajouter » touche au brouillon."""

    result = run_routing(tmp_path, BIND_HARNESS + """
      const harness=find('[data-routing-harness]');
      harness.value='claude';harness.fire('change');
      const afterHarness={pick:{...SET.routingPick.code},dirty:SET.dirty,draft:copy(),said:[...says]};
      find('[data-routing-model]').value='modele-b';find('[data-routing-model]').fire('change');
      const afterModel={pick:{...SET.routingPick.code},dirty:SET.dirty,draft:copy(),said:[...says]};
      find('[data-routing-add]').fire('click');
      const afterAdd={dirty:SET.dirty,draft:copy(),said:[...says]};
      // Changer de harness oublie le modèle : il appartenait à l'autre.
      harness.value='codex';harness.fire('change');
      const switched={...SET.routingPick.code};
      out({afterHarness,afterModel,afterAdd,switched});
    """)

    # Choisir un harness : rien dans le brouillon, rien de « non enregistré ».
    assert result["afterHarness"]["pick"] == {"agent": "claude", "model": ""}
    assert result["afterHarness"]["dirty"] is False and result["afterHarness"]["draft"] == []
    assert result["afterHarness"]["said"] == []
    # Choisir un modèle non plus.
    assert result["afterModel"]["pick"] == {"agent": "claude", "model": "modele-b"}
    assert result["afterModel"]["dirty"] is False and result["afterModel"]["draft"] == []
    # « Ajouter » seulement : le couple entre, et la page le dit.
    assert result["afterAdd"]["draft"] == [{"agent": "claude", "model": "modele-b"}]
    assert result["afterAdd"]["dirty"] is True
    assert result["afterAdd"]["said"] == ["Modifications non enregistrées."]
    assert result["switched"] == {"agent": "codex", "model": ""}


def test_adding_a_candidate_already_listed_never_demotes_it(tmp_path):
    """Réajouter le préféré le renverrait en dernier recours et en promouvrait
    un autre — en un clic, sans que rien ne le dise."""

    result = run_routing(tmp_path, BIND_HARNESS + """
      SET.draft.routing.profiles.code.candidates=[
        {agent:'claude',model:'modele-a'},{agent:'codex',model:''}];
      SET.routingPick={code:{agent:'claude',model:'modele-a'}};
      find('[data-routing-add]').fire('click');
      out({draft:copy(),dirty:SET.dirty,said:[...says],renders});
    """)

    # L'ordre ne bouge pas, le brouillon n'est pas sali, et l'utilisateur est prévenu.
    assert result["draft"] == [{"agent": "claude", "model": "modele-a"}, {"agent": "codex", "model": ""}]
    assert result["dirty"] is False and result["renders"] == 0
    assert result["said"] and "Déjà dans la liste" in result["said"][0]


def test_every_routing_edit_says_so_and_keeps_the_focus_where_it_was(tmp_path):
    """« Monter », « retirer » et « ajouter » redessinent la section : sans
    rattrapage, le focus repart au début du document à chaque clic."""

    result = run_routing(tmp_path, BIND_HARNESS + """
      SET.draft.routing.profiles.code.candidates=[
        {agent:'claude',model:'modele-a'},{agent:'claude',model:'modele-b'}];
      find('[data-routing-up]').fire('click');
      const moved={draft:copy(),said:[...says],dirty:SET.dirty};
      says.length=0;
      find('[data-routing-drop]').fire('click');
      const dropped={draft:copy(),said:[...says]};
      // Le rattrapage du focus : la même commande, sinon son équivalent.
      const body=makeBody([
        el({routingFocus:'drop|code|claude|modele-b'}),
        el({routingFocus:'harness|code'}),
      ]);
      const gone=routingFocusTarget(body,'up|code|claude|modele-b');
      const missing=routingFocusTarget(body,'up|code|claude|inconnu');
      out({moved,dropped,fallback:gone&&gone.dataset.routingFocus,
        lastResort:missing&&missing.dataset.routingFocus});
    """)

    assert result["moved"]["draft"] == [{"agent": "claude", "model": "modele-b"},
                                        {"agent": "claude", "model": "modele-a"}]
    assert result["moved"]["said"] == ["Modifications non enregistrées."]
    assert result["moved"]["dirty"] is True
    assert result["dropped"]["said"] == ["Modifications non enregistrées."]
    # « Monter » disparaît quand la ligne devient préférée : le focus va sur
    # « retirer » du même couple, jamais au début du document.
    assert result["fallback"] == "drop|code|claude|modele-b"
    assert result["lastResort"] == "harness|code"


def test_a_disabled_profile_says_its_candidates_do_not_serve(tmp_path):
    result = run_routing(tmp_path, BIND_HARNESS + """
      SET.routing=STATE;
      // Éteindre le profil doit redessiner son bloc : sans cela, rien à l'écran
      // ne dirait que ses candidats ne servent plus.
      const toggle=find('[data-routing-profile-enabled]');
      toggle.checked=false;toggle.fire('change');
      SET.draft.routing.profiles.code.enabled=false;
      const body=routingAdvancedBody();
      out({body,renders,enabled:SET.draft.routing.profiles.code.enabled,said:[...says],
        off:body.includes('routing-off'),inert:body.includes('aria-disabled="true"')});
    """)
    assert result["enabled"] is False and result["renders"] == 1
    assert result["said"] == ["Modifications non enregistrées."]
    assert result["off"] and result["inert"]
    assert "ne servent pas tant qu" in result["body"]


def test_removing_a_candidate_keeps_the_keyboard_in_the_list(tmp_path):
    """« Retirer » supprime sa propre commande : sans relais, le focus repart au
    début du document à chaque suppression, et il faut retraverser la fenêtre
    pour retirer le candidat suivant."""

    result = run_routing(tmp_path, """
      const rows=agent=>makeBody([
        el({routingDrop:'code',routingRank:'0',routingFocus:'drop|code|claude|m1'}),
        el({routingDrop:'code',routingRank:'1',routingFocus:'drop|code|claude|m2'}),
        el({routingHarness:'code',routingFocus:'harness|code'}),
      ]);
      // La ligne du milieu vient d'être retirée : celle qui prend son rang.
      const middle=routingFocusTarget(rows(),'drop|code|claude|parti','1');
      // La dernière ligne retirée : on retombe sur la nouvelle dernière.
      const last=routingFocusTarget(rows(),'drop|code|claude|parti','7');
      // Plus aucune ligne : le sélecteur du profil, jamais le document.
      const alone=routingFocusTarget(makeBody([
        el({routingHarness:'code',routingFocus:'harness|code'})]),'drop|code|claude|parti','0');
      // Une commande désactivée n'est jamais un repli.
      const off=makeBody([el({routingDrop:'code',routingRank:'0',routingFocus:'drop|code|claude|m1'}),
        el({routingHarness:'code',routingFocus:'harness|code'})]);
      off.list[0].disabled=true;
      const skipped=routingFocusTarget(off,'drop|code|claude|parti','0');
      out({middle:middle&&middle.dataset.routingFocus,last:last&&last.dataset.routingFocus,
        alone:alone&&alone.dataset.routingFocus,skipped:skipped&&skipped.dataset.routingFocus});
    """)

    assert result["middle"] == "drop|code|claude|m2"
    assert result["last"] == "drop|code|claude|m2"
    assert result["alone"] == "harness|code"
    assert result["skipped"] == "harness|code"


def test_the_renderer_itself_puts_the_focus_back(tmp_path):
    """La recherche du repli ne suffit pas : c'est le rendu qui doit s'en
    servir. Sans cette queue de `renderRoutingAdvanced`, tout le reste reste
    vert et le focus est quand même perdu."""

    result = run_routing(tmp_path, """
      SET.routing=STATE;
      SET.draft.routing.profiles.code.candidates=[
        {agent:'claude',model:'modele-a'},{agent:'claude',model:'modele-b'},{agent:'claude',model:''}];
      BODY=makeBody([]);
      BODY.innerHTML=routingAdvancedBody();
      const before=BODY.querySelectorAll('[data-routing-drop]').map(n=>n.dataset.routingFocus);
      // On retire la deuxième ligne, comme le ferait un clic clavier dessus.
      document.activeElement=BODY.querySelectorAll('[data-routing-drop]')[1];
      SET.draft.routing.profiles.code.candidates.splice(1,1);
      FOCUSED=null;
      renderRoutingAdvanced(1);
      const afterDrop=FOCUSED&&FOCUSED.dataset.routingFocus;
      // Et « monter » sur la dernière : la ligne devient préférée, « monter »
      // disparaît, le focus tombe sur « retirer » du même couple.
      const up=BODY.querySelectorAll('[data-routing-up]');
      document.activeElement=up[up.length-1];
      const moved=SET.draft.routing.profiles.code.candidates;
      moved.splice(0,0,moved.splice(moved.length-1,1)[0]);
      FOCUSED=null;
      renderRoutingAdvanced(1);
      out({before,afterDrop,afterUp:FOCUSED&&FOCUSED.dataset.routingFocus});
    """, renderer=True)

    assert result["before"] == ["drop|code|claude|modele-a", "drop|code|claude|modele-b",
                                "drop|code|claude|"]
    # Le focus reste dans la liste, à la place libérée.
    assert result["afterDrop"] == "drop|code|claude|"
    assert result["afterUp"] == "drop|code|claude|"


def test_a_disabled_profile_refuses_the_keyboard_too(tmp_path):
    """`pointer-events:none` n'est qu'une peinture : au clavier, les commandes
    d'un profil éteint restaient atteignables et modifiaient le brouillon
    pendant que la page annonçait `aria-disabled`."""

    result = run_routing(tmp_path, """
      SET.routing=STATE;
      const candidates=()=>[{agent:'claude',model:'modele-a'},{agent:'claude',model:'modele-b'}];
      SET.draft.routing.profiles.code.candidates=candidates();
      SET.draft.routing.profiles.code.enabled=false;
      SET.routingPick={code:{agent:'claude',model:''}};
      BODY=makeBody([]);
      BODY.innerHTML=routingAdvancedBody();
      bindRoutingAdvanced(1);
      const locked=['[data-routing-drop]','[data-routing-up]','[data-routing-add]',
        '[data-routing-harness]','[data-routing-model]','[data-routing-fallback]']
        .map(sel=>[sel,BODY.querySelectorAll(sel).map(n=>n.disabled)]);
      // Le clavier atteint quand même une commande : elle ne doit rien faire.
      for(const sel of ['[data-routing-drop]','[data-routing-up]','[data-routing-add]']){
        const node=BODY.querySelector(sel);
        if(node)node.fire('click');
      }
      const fallback=BODY.querySelector('[data-routing-fallback]');
      if(fallback){fallback.checked=false;fallback.fire('change')}
      const after={draft:copy(),
        fallback:SET.draft.routing.profiles.code.allow_general_fallback,
        dirty:SET.dirty,said:[...says]};
      // La case « Profil actif » reste, elle, utilisable : sinon on ne pourrait
      // plus rallumer le profil.
      const toggle=BODY.querySelector('[data-routing-profile-enabled]');
      const canReenable=!toggle.disabled;
      SET.draft.routing.profiles.code.enabled=true;
      BODY.innerHTML=routingAdvancedBody();
      const restored=['[data-routing-drop]','[data-routing-add]','[data-routing-harness]',
        '[data-routing-fallback]'].map(sel=>BODY.querySelectorAll(sel).map(n=>n.disabled));
      out({locked,after,canReenable,restored});
    """)

    # Toutes les commandes du bloc portent vraiment `disabled`.
    for selector, flags in result["locked"]:
        assert flags and all(flags), selector
    # Et même actionnées, elles ne touchent à rien.
    assert result["after"]["draft"] == [{"agent": "claude", "model": "modele-a"},
                                        {"agent": "claude", "model": "modele-b"}]
    assert result["after"]["fallback"] is True
    assert result["after"]["dirty"] is False and result["after"]["said"] == []
    # Rallumer reste possible, et tout redevient utilisable.
    assert result["canReenable"] is True
    for flags in result["restored"]:
        assert flags and not any(flags)
