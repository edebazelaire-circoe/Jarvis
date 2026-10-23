"""Fenêtre de configuration d'un cerveau : contrôleur et adaptateurs (jarvis-architecture-agents-settings-editor, Slice 05).

Le module est exécuté par node sur les fixtures de la Slice 02 (`tests/fixtures/brain_config_{core,voice}.json`,
produites par le service, copiées telles quelles). Seul le transport est simulé : l'adaptateur de fixture joue le
serveur de `docs/brain-config.md`, ou une réponse imposée (`script`) reproduit un refus précis. Doc :
`docs/settings/brain-config-panel.md`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_brain_config_panel.js"
FIXTURES = ROOT / "tests" / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"brain_config_{name}.json").read_text(encoding="utf-8"))


def tool_brain() -> dict:
    """Un Tool Brain dérivé du fixture Core, selon le tableau des champs de `docs/brain-config.md` § 2."""
    cfg = copy.deepcopy(fixture("core"))
    cfg.update(brain_id="tool_brain", brain_type="tool_brain", label="Tool Brain", system=False)
    f = cfg["fields"]
    del f["provider"]
    f["model"].update(applies="next_turn", owner="tool_brain.model", value="")
    f["instructions"] = {"value": None, "editable": False, "applies": None, "owner": None,
                         "reason": "La consigne du Tool Brain n'est pas au catalogue des prompts : elle n'est pas modifiable."}
    f["delegation"] = {"value": "not_applicable", "editable": False, "applies": None, "owner": None,
                       "reason": "Le Tool Brain ne lance aucun sous-agent."}
    f["activation"] = {"value": "off", "editable": True, "applies": "core_restart", "owner": "tool_brain.mode",
                       "reason": "Lu au démarrage de Core.", "live": "off",
                       "choices": [{"value": "off", "label": "Coupé"}, {"value": "shadow", "label": "Observation (n'exécute rien)"},
                                   {"value": "active", "label": "Actif (pilote l'écran)"}]}
    return cfg


def run_node(tmp_path: Path, source: str, configs: dict | None = None):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data = tmp_path / "configs.json"
    data.write_text(json.dumps(configs if configs is not None else {"core": fixture("core"), "voice": fixture("voice"),
                                                                    "tool_brain": tool_brain()}), encoding="utf-8")
    script = tmp_path / "t.cjs"
    script.write_text(
        "const errors=[],infos=[];console.error=(c,e,x)=>errors.push([c,x||null]);console.info=(c,d)=>infos.push([c,d]);\n"
        f"const P=require({json.dumps(str(MODULE))});\n"
        f"const CFG=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data))},'utf8'));\n"
        # DOM minimal : la fenêtre n'a besoin que d'un élément dont on lit innerHTML.
        "const el=()=>({innerHTML:'',attrs:{},className:'',setAttribute(k,v){this.attrs[k]=v},addEventListener(){},removeEventListener(){},remove(){this.removed=true}});\n"
        "const doc={createElement:el,head:null,activeElement:null,body:null};\n"
        "const host={ownerDocument:doc,children:[],events:[],appendChild(c){this.children.push(c)},dispatchEvent(e){this.events.push([e.type,e.detail]);return true}};\n"
        "const quiet={setInterval:()=>null,clearInterval:()=>{}};\n"
        "const html=w=>w.element.innerHTML;\n"
        "const tick=()=>new Promise(r=>setTimeout(r,5));\n"
        "const patches=a=>a.calls.filter(c=>c[0]==='patch');\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "(async()=>{" + source + "})().catch(e=>{process.stderr.write(String(e&&e.stack||e));process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout) if done.stdout else None


def unescape(html: str) -> str:
    return html.replace("&#39;", "'").replace("&quot;", '"').replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")


OPEN = "const a=P.createFixtureAdapter(CFG);const seen=[],saved=[];\n" \
       "const w=P.open(host,{adapter:a,brainId:'%s',onFocusConnection:(id)=>seen.push(id),onSaved:d=>saved.push([d.field,d.applies,d.changed]),...quiet});\n" \
       "await tick();\n"


def test_the_core_descriptor_drives_every_section_and_nothing_is_invented(tmp_path):
    out = run_node(tmp_path, OPEN % "core" + "out({html:html(w),errors,infos:infos.map(i=>i[0]),phase:w.state.phase});")
    h = unescape(out["html"])
    core = fixture("core")
    assert out["phase"] == "ready" and out["errors"] == []
    assert out["infos"][:2] == ["brain_config_panel.opened", "brain_config_panel.loaded"]
    assert 'role="dialog"' in h and "Core Brain" in h and "Système" in h and "Actif" in h
    assert core["fields"]["mission"]["value"] in h and "Lecture seule" in h
    # Modèle et CLI : seulement les choix du descripteur ; un indisponible reste visible avec sa raison.
    for ch in core["fields"]["model"]["choices"]:
        assert f'value="{ch["value"]}"' in h
    assert "claude · claude-retired-1 — indisponible" in h and "Modèle retiré par le fournisseur." in h
    assert "Codex CLI — indisponible" in h and "CLI Codex introuvable." in h
    # Délégation : cinq niveaux, libellés et explication du descripteur, contrôle accessible.
    assert 'role="radiogroup" aria-label="Tendance de délégation"' in h
    labels = re.findall(r'data-bcp-radio="delegation"[^>]*>([^<]+)</button>', h)
    assert labels == [c["label"] for c in core["fields"]["delegation"]["choices"]]
    assert re.search(r'aria-checked="true" tabindex="0" data-bcp-radio="delegation" data-bcp-value="standard"', h)
    assert core["fields"]["delegation"]["choices"][2]["description"] in h
    assert "Le choix du modèle de chaque rôle se fait dans l’onglet Sous-agents." in h and 'data-settings-open="subagents"' in h
    # Prise d'effet par champ.
    assert h.count("Effectif au prochain démarrage de Core") >= 3
    # Connexions en lecture seule, chacune avec « Voir sur le graphe ».
    for c in core["connections"]["incoming"] + core["connections"]["outgoing"]:
        assert f'data-bcp-conn="{c["id"]}"' in h
    assert "Obligatoire" in h and "Suit « Tendance de délégation »" in h and "Les liaisons se modifient sur le graphe" in h
    assert "Activation" in h and "Core porte la conversation" in h and 'data-bcp-radio="activation"' not in h
    assert "8192 caractères" in h or "0 / 8192 caractères" in h


def test_no_model_name_personality_control_or_cli_path_is_written_in_the_module():
    src = MODULE.read_text(encoding="utf-8")
    for literal in ("claude-", "gpt", "whisper", "gemini", "opus", "haiku", "openai", "anthropic"):
        assert literal not in src.lower(), literal
    for forbidden in ("politesse", "humour", "verbosit", "voice.persona", "permission_mode", "sandbox", "cli_path", "command"):
        assert forbidden not in src.lower(), forbidden
    for brain in ("'core'", "'voice'", "'tool_brain'", "'luna'"):
        # Seul l'adaptateur de fixture connaît `core` (règle provider+model du contrat).
        assert src.count(brain) <= (1 if brain == "'core'" else 0), brain


def test_the_voice_descriptor_shows_delegation_not_applicable_and_no_control(tmp_path):
    out = run_node(tmp_path, OPEN % "voice" + "out({html:html(w)});")
    h = unescape(out["html"])
    voice = fixture("voice")
    assert "Sans objet" in h and voice["fields"]["delegation"]["reason"] in h
    assert 'data-bcp-radio="delegation"' not in h
    assert "Le choix du modèle de chaque rôle se fait dans l’onglet Sous-agents." in h
    assert "Fournisseur" in h and ">openai<" in h and 'data-bcp-input="provider"' not in h
    assert "Effectif au prochain démarrage de la voix" in h
    assert "Inactif" in h and voice["state"]["reason"] in h


def test_apply_sends_one_patch_per_field_chaining_the_returned_revision(tmp_path):
    out = run_node(tmp_path, OPEN % "core" + """
w.setDraft('delegation','proactive');w.setDraft('instructions','Réponds en français.');
const before=html(w);
const r=await w.apply();
out({r,patches:patches(a),saved,html:html(w),draft:w.state.draft,rev:w.state.config.revision,infos:infos.map(i=>i[0])});""")
    p = out["patches"]
    assert [list(c[2].keys()) for c in p] == [["base_revision", "delegation"], ["base_revision", "instructions"]]
    assert p[0][2]["base_revision"] == fixture("core")["revision"]
    assert p[1][2]["base_revision"] != p[0][2]["base_revision"], "le second PATCH porte la révision renvoyée par le premier"
    assert p[1][2]["instructions"] == {"text": "Réponds en français.", "effective_revision": "<effective_revision>"}
    assert out["r"]["ok"] and out["r"]["done"] == ["delegation", "instructions"]
    assert out["saved"] == [["delegation", "core_restart", True], ["instructions", "core_restart", True]]
    assert out["draft"] == {}
    h = unescape(out["html"])
    assert 'aria-checked="true" tabindex="0" data-bcp-radio="delegation" data-bcp-value="proactive"' in h
    assert "Enregistré · effectif au prochain démarrage de Core" in h and "2 réglages enregistrés." in h
    assert out["infos"].count("brain_config_panel.saved") == 2


def test_a_refusal_shows_the_server_reason_keeps_the_draft_and_never_a_false_state(tmp_path):
    out = run_node(tmp_path, OPEN % "core" + """
const refused=JSON.parse(JSON.stringify(CFG.core));
a.script({result:{ok:false,status:423,code:'brain_config_field_locked',reason:'Imposé par l’environnement.',field:'model',config:refused}});
w.setDraft('model','claude-haiku-5');
const r=await w.apply();
out({r,html:html(w),draft:w.state.draft,value:w.state.config.fields.model.value,errors:errors.map(e=>e[0]),loads:a.calls.filter(c=>c[0]==='load').length});""")
    assert out["r"]["ok"] is False and out["r"]["code"] == "brain_config_field_locked"
    assert out["draft"] == {"model": "claude-haiku-5"}, "brouillon conservé"
    assert out["value"] == fixture("core")["fields"]["model"]["value"], "l'écran montre la config du refus"
    h = unescape(out["html"])
    assert 'role="alert"' in h and "Imposé par l’environnement." in h and "brain_config_field_locked" in h and "HTTP 423" in h
    assert "Refusé : Modèle" in h and "votre brouillon est conservé" in h
    assert out["errors"] == ["brain_config_field_locked"] and out["loads"] == 1, "refus avec config : pas de relecture"


def test_a_refusal_without_config_forces_a_reread(tmp_path):
    out = run_node(tmp_path, OPEN % "core" + """
a.script({result:{ok:false,status:500,code:'brain_config_write_failed',reason:'Disque plein.',field:'delegation',config:null}});
w.setDraft('delegation','never');await w.apply();
out({loads:a.calls.filter(c=>c[0]==='load').length,html:html(w),draft:w.state.draft});""")
    assert out["loads"] == 2 and "Disque plein." in unescape(out["html"]) and out["draft"] == {"delegation": "never"}


def test_a_stale_revision_rereads_and_keeps_the_draft(tmp_path):
    out = run_node(tmp_path, OPEN % "core" + """
a.tamper('core',c=>{c.fields.model.value='claude-haiku-5'});
w.setDraft('delegation','rare');const r=await w.apply();
const h1=html(w),draft={...w.state.draft},model=w.state.config.fields.model.value;
const r2=await w.apply();
out({r,r2,h1,draft,model,after:a.current('core').fields.delegation.value});""")
    assert out["r"]["status"] == 409 and out["r"]["code"] == "brain_config_revision_stale"
    assert out["draft"] == {"delegation": "rare"} and out["model"] == "claude-haiku-5", "la config relue est affichée"
    assert "Modifié ailleurs : Tendance de délégation" in unescape(out["h1"]) and "appliquez à nouveau" in unescape(out["h1"])
    assert out["r2"]["ok"] and out["after"] == "rare"


def test_an_instructions_conflict_keeps_the_draft_shows_the_server_text_then_reapplies(tmp_path):
    out = run_node(tmp_path, OPEN % "core" + """
w.setDraft('instructions','Mon brouillon.');
a.tamper('core',c=>{c.fields.instructions.value='Texte posé ailleurs.';c.fields.instructions.effective_revision='e-other'});
a.script({result:{ok:false,status:409,code:'prompt_override_concurrent',reason:'Ces instructions ont été modifiées ailleurs depuis votre lecture ; relisez-les.',field:'instructions',config:a.current('core')}});
const r=await w.apply();
const h=html(w),draft={...w.state.draft},conflict=w.state.conflict;
const r2=await w.apply();
out({r,h,draft,conflict,r2,last:patches(a).at(-1)[2],after:a.current('core').fields.instructions.value,h2:html(w)});""")
    assert out["r"]["code"] == "prompt_override_concurrent"
    assert out["draft"] == {"instructions": "Mon brouillon."} and out["conflict"] == {"text": "Texte posé ailleurs."}
    h = unescape(out["h"])
    assert "Texte actuel du serveur" in h and "Texte posé ailleurs." in h and ">Mon brouillon.</textarea>" in h
    assert out["r2"]["ok"] and out["last"]["instructions"]["effective_revision"] == "e-other"
    assert out["after"] == "Mon brouillon." and "Texte actuel du serveur" not in unescape(out["h2"])


def test_an_unknown_outcome_rereads_and_says_so(tmp_path):
    out = run_node(tmp_path, OPEN % "core" + """
const err=new Error('Control Center injoignable : ECONNRESET');err.code='brain_config_unreachable';
a.script({error:err});
w.setDraft('delegation','exploratory');const r=await w.apply();
out({r,html:html(w),loads:a.calls.filter(c=>c[0]==='load').length,draft:w.state.draft});""")
    assert out["r"]["unknown"] is True and out["loads"] == 2
    h = unescape(out["html"])
    assert "Issue inconnue" in h and "ECONNRESET" in h and "la fenêtre relit la configuration" in h
    assert out["draft"] == {"delegation": "exploratory"}, "non appliqué d'après la relecture : reste en brouillon"


#: Ouverture qui garde ce que l'hôte reçoit : `onSaved` et `onReread` (I-002 point 2 de la tâche
#: jarvis-architecture-agents-settings-editor), avec le modèle de Core de la configuration transmise.
OPEN_HOST = ("const a=P.createFixtureAdapter(CFG);const hosted=[];\n"
             "const w=P.open(host,{adapter:a,brainId:'core',...quiet,\n"
             "  onSaved:d=>hosted.push(['saved',d.field,d.config.fields.model.value]),\n"
             "  onReread:d=>hosted.push(['reread',d.field,d.config.fields.model.value])});\n"
             "await tick();\n")


def test_an_unknown_model_outcome_hands_the_reread_config_to_the_host(tmp_path):
    """Délai dépassé sur le PATCH du modèle, alors que l'écriture est passée : la fenêtre relit, et l'hôte reçoit
    la configuration relue (`onReread`) pour aligner son brouillon `/api/settings` (`syncCoreCliDraft`)."""
    out = run_node(tmp_path, OPEN_HOST + """
a.tamper('core',c=>{c.fields.model.value='claude-haiku-5'});
const err=new Error('Pas de réponse.');err.code='brain_config_timeout';a.script({error:err});
w.setDraft('model','claude-haiku-5');const r=await w.apply();
out({r,hosted,events:host.events.map(e=>e[0])});""")
    assert out["r"]["unknown"] is True
    assert out["hosted"] == [["reread", "model", "claude-haiku-5"]]
    assert "brain-config:reread" in out["events"]


def test_a_success_without_config_hands_the_reread_config_to_on_saved(tmp_path):
    """Réponse `ok` sans descripteur : la fenêtre relit AVANT de prévenir l'hôte, qui reçoit la configuration relue
    et non l'ancienne."""
    out = run_node(tmp_path, OPEN_HOST + """
a.tamper('core',c=>{c.fields.model.value='claude-haiku-5'});
a.script({result:{ok:true,changed:true,applies:'core_restart',config:null}});
w.setDraft('model','claude-haiku-5');const r=await w.apply();
out({r,hosted,loads:a.calls.filter(c=>c[0]==='load').length});""")
    assert out["r"]["ok"] is True and out["loads"] == 2
    assert out["hosted"] == [["saved", "model", "claude-haiku-5"]]


def test_catalog_unavailable_is_said_and_a_503_shows_its_reason(tmp_path):
    cfgs = {"core": fixture("core")}
    cfgs["core"]["catalog"] = {"status": "unavailable", "reason": "Sonde des modèles en échec."}
    out = run_node(tmp_path, OPEN % "core" + """
w.setDraft('model','claude-haiku-5');const r=await w.apply();
out({r,html:html(w)});""", cfgs)
    h = unescape(out["html"])
    assert "Catalogue des modèles indisponible" in h and "Sonde des modèles en échec." in h and "Seul le choix par défaut reste permis." in h
    assert out["r"]["status"] == 503 and "brain_config_catalog_unavailable" in h


def test_changing_the_cli_sends_the_provider_alone_and_waits_for_its_models(tmp_path):
    cfgs = {"core": fixture("core")}
    cfgs["core"]["fields"]["provider"]["choices"][1]["available"] = True
    out = run_node(tmp_path, OPEN % "core" + """
w.setDraft('model','claude-haiku-5');w.setDraft('provider','codex');
const h=html(w);await w.apply();
out({h,body:patches(a)[0][2]});""", cfgs)
    assert out["body"] == {"base_revision": fixture("core")["revision"], "provider": "codex"}
    assert "Les modèles de ce CLI s’affichent après l’application du changement de CLI" in unescape(out["h"])
    assert re.search(r'data-bcp-input="model"[^>]* disabled', out["h"])


def test_tool_brain_activation_is_editable_and_instructions_are_not(tmp_path):
    out = run_node(tmp_path, OPEN % "tool_brain" + """
const h=html(w);w.setDraft('activation','shadow');await w.apply();
out({h,body:patches(a)[0][2],after:a.current('tool_brain').fields.activation.value});""")
    h = unescape(out["h"])
    assert 'role="radiogroup" aria-label="Activation du cerveau"' in h and "Observation (n'exécute rien)" in h
    assert "Non modifiable" in h and "pas au catalogue des prompts" in h and 'data-bcp-input="instructions"' not in h
    assert "Effectif au prochain tour" in h, "modèle du Tool Brain : next_turn"
    assert out["body"]["activation"] == "shadow" and out["after"] == "shadow"


def test_too_long_instructions_block_apply_with_the_descriptor_limit(tmp_path):
    out = run_node(tmp_path, OPEN % "core" + """
w.setDraft('instructions','x'.repeat(8193));const h=html(w);const r=await w.apply();
out({h,r,patches:patches(a).length});""")
    h = unescape(out["h"])
    assert "Les instructions dépassent 8192 caractères." in h and "8193 / 8192 caractères — trop long" in h
    assert re.search(r'data-bcp-act="apply"[^>]*disabled', h) and out["patches"] == 0


def test_one_window_only_reopening_with_a_draft_asks_first(tmp_path):
    out = run_node(tmp_path, OPEN % "core" + """
w.setDraft('delegation','never');
const again=P.open(host,{adapter:a,brainId:'voice',...quiet});
const asked={same:again===w,confirm:w.state.confirm&&w.state.confirm.kind,brain:w.brainId,html:html(w)};
w.confirm(true);await tick();
const switched={brain:w.brainId,draft:w.state.draft,label:w.state.config.label};
const third=P.open(host,{adapter:a,brainId:'core',...quiet});await tick();
const closed=w.close();
out({asked,switched,third:third===w,closed,current:P.current===null,removed:!!w.element.removed,windows:host.children.length,patches:patches(a).length});""")
    asked = out["asked"]
    assert asked["same"] and asked["confirm"] == "replace" and asked["brain"] == "core"
    assert "abandonne vos modifications non appliquées (Tendance de délégation)" in unescape(asked["html"])
    assert out["switched"] == {"brain": "voice", "draft": {}, "label": "Voice Brain"}
    assert out["third"] and out["closed"] and out["current"] and out["removed"]
    assert out["windows"] == 1 and out["patches"] == 0


def test_close_with_a_draft_asks_and_keep_editing_keeps_it(tmp_path):
    out = run_node(tmp_path, OPEN % "core" + """
w.setDraft('delegation','never');
const first=w.close();const kind=w.state.confirm&&w.state.confirm.kind;
w.confirm(false);const kept={draft:w.state.draft,confirm:w.state.confirm};
w.close();w.confirm(true);
out({first,kind,kept,destroyed:w.state.destroyed});""")
    assert out["first"] is False and out["kind"] == "close"
    assert out["kept"] == {"draft": {"delegation": "never"}, "confirm": None}
    assert out["destroyed"] is True


def test_loading_has_a_counter_and_a_deadline_ends_it_with_its_code(tmp_path):
    out = run_node(tmp_path, """
let t=1000;const a={load:()=>new Promise(()=>{}),patch:async()=>({ok:true})};
const w=P.open(host,{adapter:a,brainId:'core',timeoutMs:30,now:()=>t,...quiet});
const loading=html(w);t=4000;
await new Promise(r=>setTimeout(r,60));
out({loading,after:html(w),phase:w.state.phase,errors:errors.map(e=>e[0])});""")
    assert "Lecture de la configuration…" in out["loading"] and 'data-bcp-since="1000"' in out["loading"]
    assert "Échéance" in out["loading"] and "Fermer" in out["loading"]
    assert out["phase"] == "error" and "brain_config_timeout" in out["after"] and "Relire" in out["after"]
    assert out["errors"] == ["brain_config_timeout"]


def test_the_http_adapter_speaks_the_contract_routes_and_keeps_refusals_as_results(tmp_path):
    out = run_node(tmp_path, """
const seen=[];
const reply=(status,body)=>({ok:status<400,status,text:async()=>JSON.stringify(body),headers:{get:()=>null}});
let next=[reply(200,CFG.core),reply(200,{ok:true,changed:true,applies:'core_restart',config:CFG.core}),
  reply(409,{ok:false,code:'brain_config_revision_stale',reason:'Périmée.',field:null,config:CFG.core}),
  reply(404,{ok:false,code:'brain_config_unknown_brain',reason:'Cerveau inconnu : x.',field:null,config:null})];
const fetch=async(url,init)=>{seen.push([url,init.method,init.body||null]);return next.shift()};
const h=P.createHttpAdapter({fetch});
const cfg=await h.load('core');
const ok=await h.patch('core',{base_revision:'c-1',delegation:'never'});
const stale=await h.patch('core',{base_revision:'c-0',delegation:'never'});
let missing=null;try{await h.load('a/b')}catch(e){missing=[e.code,e.status,e.message]}
const down=P.createHttpAdapter({fetch:async()=>{throw new Error('ECONNREFUSED')}});
let unreachable=null;try{await down.patch('core',{})}catch(e){unreachable=e.code}
out({seen,label:cfg.label,ok:{...ok,config:!!ok.config},stale:{...stale,config:!!stale.config},missing,unreachable});""")
    assert out["seen"][0] == ["/api/brains/core/config", "GET", None]
    assert out["seen"][1] == ["/api/brains/core/config", "PATCH", json.dumps({"base_revision": "c-1", "delegation": "never"}, separators=(",", ":"))]
    assert out["seen"][3][0] == "/api/brains/a%2Fb/config"
    assert out["label"] == "Core Brain"
    assert out["ok"] == {"ok": True, "changed": True, "applies": "core_restart", "config": True}
    assert out["stale"] == {"ok": False, "status": 409, "code": "brain_config_revision_stale", "reason": "Périmée.", "field": None, "config": True}
    assert out["missing"] == ["brain_config_unknown_brain", 404, "Cerveau inconnu : x."]
    assert out["unreachable"] == "brain_config_unreachable"


def test_the_fixture_adapter_refuses_like_the_server(tmp_path):
    out = run_node(tmp_path, """
const a=P.createFixtureAdapter(CFG);const rev=CFG.voice.revision,core=CFG.core.revision;
out({
  unsupported:(await a.patch('voice',{base_revision:rev,delegation:'never'})).code,
  stale:(await a.patch('voice',{base_revision:'c-old',model:'gpt-live-2'})).status,
  two:(await a.patch('voice',{base_revision:rev,model:'gpt-live-2',instructions:{text:'',effective_revision:'x'}})).code,
  unavailable:(await a.patch('core',{base_revision:core,model:'claude-retired-1'})).reason,
  invalid:(await a.patch('core',{base_revision:core,delegation:'souvent'})).code,
  unknown:(await a.patch('nobody',{base_revision:'x'})).status,
});""")
    assert out == {"unsupported": "brain_config_field_unsupported", "stale": 409, "two": "brain_config_request_invalid",
                   "unavailable": "Modèle retiré par le fournisseur.", "invalid": "brain_config_delegation_invalid", "unknown": 404}



def test_a_pending_relaunch_is_said_next_to_the_delegation_control(tmp_path):
    cfgs = {"core": fixture("core")}
    assert cfgs["core"]["fields"]["delegation"]["pending_relaunch"] is False  # fixture de la Slice 02
    cfgs["core"]["fields"]["delegation"]["launched"] = "standard"  # cohérent : enregistré = lancé
    out = run_node(tmp_path, OPEN % "core" + """
const before=html(w);w.setDraft('delegation','proactive');await w.apply();
const after=html(w);w.setDraft('delegation','standard');await w.apply();
out({before,after,back:html(w)});""", cfgs)
    before, after, back = (unescape(out[k]) for k in ("before", "after", "back"))
    assert "data-bcp-pending-relaunch" not in before and "Reçue par le cerveau en cours d’exécution : « Standard »" in before
    assert "data-bcp-pending-relaunch" in after
    assert "« Proactive » est enregistré : effectif à la relance de Core Brain. Le cerveau en cours d’exécution a reçu « Standard »." in after
    assert "data-bcp-pending-relaunch" not in back


def test_a_failed_reread_keeps_the_original_refusal_or_unknown_outcome(tmp_path):
    out = run_node(tmp_path, OPEN % "core" + """
const gone=new Error('Control Center injoignable : ECONNREFUSED');gone.code='brain_config_unreachable';
a.script({result:{ok:false,status:500,code:'brain_config_write_failed',reason:'Disque plein.',field:'delegation',config:null}});
a.script({error:gone});
w.setDraft('delegation','never');await w.apply();const refused=html(w);
const lost=new Error('Pas de réponse.');lost.code='brain_config_timeout';
a.script({error:lost});a.script({error:gone});
await w.apply();
out({refused,unknown:html(w)});""")
    refused, unknown = unescape(out["refused"]), unescape(out["unknown"])
    assert "Refusé : Tendance de délégation" in refused and "Disque plein." in refused and "brain_config_write_failed" in refused
    assert "data-bcp-reread-error" in refused and "Relecture impossible" in refused and "ECONNREFUSED" in refused
    assert "Issue inconnue" in unknown and "Pas de réponse." in unknown and "brain_config_timeout" in unknown
    assert "data-bcp-reread-error" in unknown and "brain_config_unreachable" in unknown


def test_brain_absent_is_not_a_conflict_and_does_not_invite_to_reapply(tmp_path):
    out = run_node(tmp_path, OPEN % "voice" + """
a.script({result:{ok:false,status:409,code:'brain_config_brain_absent',reason:'Absent de l’architecture Duplex.',field:null,config:a.current('voice')}});
w.setDraft('model','gpt-live-2');await w.apply();
out({html:html(w),conflict:w.state.conflict});""")
    h = unescape(out["html"])
    assert "Cerveau absent" in h and "Ce cerveau n’existe pas dans l’architecture vocale actuelle" in h and "brain_config_brain_absent" in h
    assert "Modifié ailleurs" not in h and "appliquez à nouveau" not in h and out["conflict"] is None


def test_changing_the_cli_says_the_chosen_model_was_dropped(tmp_path):
    cfgs = {"core": fixture("core")}
    cfgs["core"]["fields"]["provider"]["choices"][1]["available"] = True
    out = run_node(tmp_path, OPEN % "core" + """
w.setDraft('model','claude-haiku-5');w.setDraft('provider','codex');const dropped=html(w);
w.setDraft('provider','claude');const back=html(w);
out({dropped,back,draft:w.state.draft});""", cfgs)
    assert "Votre choix « claude-haiku-5 » est retiré : il appartient à l’autre CLI." in unescape(out["dropped"])
    assert "data-bcp-dropped-model" not in out["back"] and out["draft"] == {}
