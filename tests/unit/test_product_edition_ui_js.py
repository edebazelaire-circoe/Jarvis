"""Logique pure de l'interface d'édition produit (node, sans navigateur ; jarvis-presentation-edition-v1, Slice 08).

Contrat : `docs/control-center-shell.md` › *Product edition UI*. Ce fichier épingle ce que les modules lisent de la
charge de Core (`ProductEditionPolicy.to_payload()`, servie ici telle que Python la produit) et ce qu'ils en font :
lecture stricte de la charge, choix du type de Board, lignes de la liste, catégories des Réglages, modèle du rail.
Le comportement dans une vraie page est prouvé par `test_presentation_edition_ui_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain.product_edition import FULL_EDITION, PRESENTATION_EDITION

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
PRESENTATION = json.dumps(PRESENTATION_EDITION.to_payload())
FULL = json.dumps(FULL_EDITION.to_payload())


def node(script: str):
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node absent")
    req = lambda name: json.dumps(str(RUNTIME / name))  # noqa: E731 - local helper for the require paths
    code = (f"const E=require({req('control_center_product_edition.js')});"
            f"const B=require({req('control_center_boards.js')});"
            f"const R=require({req('control_center_settings_registry.js')});"
            f"const P=require({req('control_center_presentation_rail.js')});"
            f"Promise.resolve((async()=>{{{script}}})()).then(v=>process.stdout.write(JSON.stringify(v)))"
            ".catch(e=>{console.error(e&&e.stack||e);process.exit(1)})")
    done = subprocess.run([exe, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_payload_of_core_is_read_strictly():
    out = node(f"const p=E.parse({PRESENTATION}).model;const f=E.parse({FULL}).model;"
               "return {p:[p.edition,p.defaultKind,p.developerSurfaces,p.available,p.restricts],"
               "f:[f.edition,f.defaultKind,f.developerSurfaces,f.available,f.restricts],"
               "bad:[E.parse(null).ok,E.parse({edition:'x'}).ok,E.parse({edition:'x',board_kinds:[{}]}).ok],"
               "old:E.parse({edition:'full',board_kinds:[{board_kind:'assistant',available:true}]}).model.developerSurfaces}")
    assert out["p"] == ["presentation", "presentation", "hidden", ["presentation"], True]
    assert out["f"] == ["full", "assistant", "visible", ["assistant", "presentation", "meeting"], False]
    assert out["bad"] == [False, False, False], "an unreadable payload is never a guessed model"
    assert out["old"] == "visible", "a Core older than Slice 08 hides nothing"


def test_surfaces_and_retries():
    out = node("return {page:[E.pageSurfaces('hidden'),E.pageSurfaces('__JARVIS_DEVELOPER_SURFACES__'),E.pageSurfaces(null)],"
               "shown:[E.surfaceShown('developer','hidden'),E.surfaceShown('developer','visible'),E.surfaceShown('product','hidden'),E.surfaceShown('developer',null)],"
               "retry:[1,2,3,4,5,9].map(E.retryDelay)}")
    assert out["page"] == ["hidden", None, None]
    assert out["shown"] == [False, True, True, True]
    assert out["retry"] == [2000, 4000, 8000, 16000, 30000, 30000]


def test_the_store_reads_on_demand_and_never_loops_while_core_is_down():
    """`ensure` lit une fois ; sans Boards servis par Core, une lecture tombée attend `gate` ou « Réessayer »."""
    out = node(
        "const calls=[],timers=[];let fail=true;"
        f"const ok={PRESENTATION};"
        "const fetch=async()=>{calls.push(1);if(fail)throw Object.assign(new Error('down'),{code:'core_unreachable'});"
        "return {ok:true,status:200,json:async()=>ok}};"
        "const st=E.createStore({fetch,setTimeout:(fn,ms)=>{timers.push({fn,ms});return timers.length},clearTimeout:()=>{},"
        "console:{info(){},warn(){},error(){}}});"
        "const flush=()=>new Promise(r=>setImmediate(r));"
        "const boot=[calls.length,st.state().status];"
        "st.ensure();await flush();await flush();"
        "const down=[calls.length,st.state().status,st.state().error.code];"
        "for(let i=0;i<5;i++){st.ensure();await flush()}"
        "const repeated=[calls.length,timers.filter(t=>t.ms!==E.DEADLINE_MS).length];"
        "st.gate({available:false});await flush();const stillDown=calls.length;"
        "st.gate({available:true});await flush();await flush();"
        "const retried=[calls.length,st.state().status,timers.filter(t=>t.ms===2000||t.ms===4000).map(t=>t.ms)];"
        "fail=false;await st.refresh();"
        "const back=[calls.length,st.state().status,st.state().model.edition];"
        "st.ensure();await flush();"
        "return {boot,down,repeated,stillDown,retried,back,after:calls.length}")
    assert out["boot"] == [0, "idle"], "nothing is read at boot"
    assert out["down"] == [1, "error", "core_unreachable"], "the error is shown (with its cause), never an endless wait"
    assert out["repeated"] == [1, 0], "ensure on every render never re-reads, and no retry while Core serves no Board"
    assert out["stillDown"] == 1
    assert out["retried"][0] == 2 and out["retried"][1] == "error", "Core back: read again at once"
    assert out["retried"][2] == [4000], "then the backoff resumes while Core serves its Boards"
    assert out["back"] == [3, "ready", "presentation"]
    assert out["after"] == 3, "a ready model is never re-read by ensure"



def test_a_body_slower_than_the_deadline_is_a_timeout_and_nothing_is_left_unhandled():
    """M6 (QA S08) : la réponse arrive, son corps traîne au-delà de l'échéance → cause `timeout`, aucun rejet orphelin."""
    out = node(
        "const unhandled=[];process.on('unhandledrejection',e=>unhandled.push(String(e&&e.message||e)));"
        "const timers=[];"
        "const fetch=async()=>({ok:true,status:200,json:()=>new Promise(()=>{})});"
        "const st=E.createStore({fetch,setTimeout:(fn,ms)=>{timers.push({fn,ms});return timers.length},clearTimeout:()=>{},"
        "console:{info(){},warn(){},error(){}}});"
        "const flush=()=>new Promise(r=>setImmediate(r));"
        "st.ensure();await flush();"
        "const deadline=timers.find(t=>t.ms===E.DEADLINE_MS);deadline.fn();await flush();await flush();"
        "await new Promise(r=>setTimeout(r,20));"
        "return {status:st.state().status,code:st.state().error.code,unhandled}")
    assert out == {"status": "error", "code": "timeout", "unhandled": []}


def test_an_unreadable_page_edition_is_said_at_the_console():
    """M5 (QA S08) : la page marquée `unreadable` par le serveur le redit, puis s'en remet à Core."""
    out = node(
        "const lines=[];const attrs={'data-product-edition':'unreadable'};"
        "const document={documentElement:{getAttribute:k=>attrs[k]===undefined?null:attrs[k],setAttribute(k,v){attrs[k]=v}}};"
        "const st=E.createStore({document,fetch:async()=>{throw new Error('no')},setTimeout:()=>0,clearTimeout:()=>{},"
        "console:{info(l){lines.push(['info',l])},warn(l){lines.push(['warn',l])},error(l){lines.push(['error',l])}}});"
        "const plain=[];E.createStore({document:{documentElement:{getAttribute:()=>null,setAttribute(){}}},"
        "console:{info(l){plain.push(l)},warn(l){plain.push(l)},error(l){plain.push(l)}}});"
        "return {lines,shown:st.developerSurfacesShown(),plain}")
    assert out["lines"] and out["lines"][0][0] == "error" and "edition.page_unreadable" in out["lines"][0][1]
    assert out["shown"] is True and out["plain"] == []

def test_the_board_kind_choice_follows_core_and_never_guesses():
    out = node(f"const ready={{status:'ready',model:E.parse({PRESENTATION}).model}};"
               "const kinds=['assistant','presentation','meeting'];"
               "return {ready:kinds.map(k=>B.kindChoiceOf(k,ready).state),"
               "loading:kinds.map(k=>B.kindChoiceOf(k,{status:'loading',model:null,since:1}).state),"
               "none:kinds.map(k=>B.kindChoiceOf(k,null).state),"
               "default:[B.defaultKindOf(ready),B.defaultKindOf(null)],"
               "note:B.kindNoteOf(ready,0),wait:B.kindNoteOf({status:'loading',model:null,since:1000},4200).text,"
               "bad:B.kindNoteOf({status:'error',model:null,error:{code:'core_unreachable',message:'down'}},0),"
               "timeout:B.kindNoteOf({status:'error',model:null,error:{code:'timeout',message:''}},0).text,"
               "idle:B.kindNoteOf({status:'idle',model:null,since:0},9000).text,"
               f"full:B.kindNoteOf({{status:'ready',model:E.parse({FULL}).model}},0)}}")
    assert out["ready"] == ["soon", "available", "soon"]
    assert out["loading"] == ["unknown"] * 3, "nothing is creatable before Core answers"
    assert out["none"] == ["available"] * 3, "without an edition source the control behaves as before"
    assert out["default"] == ["presentation", "assistant"]
    assert out["note"]["tone"] == "info" and out["note"]["text"] == \
        "Cette édition crée des Boards Présentation. Assistant et Réunion arrivent bientôt."
    assert out["wait"] == "Lecture des types de Board auprès de Jarvis… 3 s"
    assert out["bad"]["tone"] == "bad" and out["bad"]["retry"] and "Core ne répond pas" in out["bad"]["text"]
    assert out["bad"]["detail"] == "core_unreachable · down"
    assert "Jarvis n’a pas répondu à temps" in out["timeout"]
    assert out["full"] is None
    assert out["idle"] == "Lecture des types de Board auprès de Jarvis…", "never asked yet: no seconds counted"


def test_a_refused_session_never_points_to_a_hidden_settings_page():
    """M2 (QA S08) : en édition produit, le refus de la voix ne renvoie pas vers Avancé & Diagnostics (caché)."""
    out = node("const r={event:'refused',last_failure_code:'presentation_requires_continuous'};"
               "return {full:B.presenceOf(r,'presentation').said,visible:B.presenceOf(r,'presentation',{developerSurfaces:'visible'}).said,"
               "hidden:B.presenceOf(r,'presentation',{developerSurfaces:'hidden'})}")
    assert "Avancé & Diagnostics" in out["full"] and out["visible"] == out["full"]
    hidden = out["hidden"]
    assert hidden["state"] == "refused" and hidden["code"] == "presentation_requires_continuous"
    for word in ("Réglages ›", "Avancé", "Duplex", "PRESENTATION"):
        assert word not in hidden["said"], word
    assert "mode développeur" in hidden["said"]


def test_rows_mark_a_legacy_board_and_only_with_an_edition():
    out = node(f"const ed={{status:'ready',model:E.parse({PRESENTATION}).model}};"
               "const listing={boards:[{board_id:'a',board_kind:'assistant',title:'A'},{board_id:'p',board_kind:'presentation',title:'P'},"
               "{board_id:'z',board_kind:'meeting',title:'Z',status:'archived'}]};const block={available:true,active:{board_id:'p'}};"
               "return {edition:B.rowsOf(listing,block,null,{edition:ed}).map(r=>[r.board_id,r.unavailable]),"
               "archived:B.rowsOf(listing,block,null,{edition:ed,view:'archived'}).map(r=>[r.board_id,r.unavailable]),"
               "before:B.rowsOf(listing,block,null,{}).map(r=>[r.board_id,r.unavailable])}")
    assert out["edition"] == [["a", True], ["p", False]]
    assert out["archived"] == [["z", False]], "an archived Board already never opens; it keeps its own state"
    assert out["before"] == [["a", False], ["p", False]]


def test_settings_show_only_product_categories_and_sections_when_hidden():
    out = node("const reg=R.createRegistry();const m=()=>{};"
               "reg.register({id:'shortcuts',category:'interface_interactions',label:'Raccourcis',save:'self',mount:m});"
               "reg.register({id:'barehands',category:'interface_interactions',label:'Bare Hands',save:'self',surface:'developer',mount:m});"
               "reg.register({id:'providers',category:'connections',label:'Fournisseurs',save:'self',mount:m});"
               "reg.register({id:'prompts',category:'advanced_diagnostics',group:'prompts',label:'Prompts',save:'self',mount:m});"
               "const hidden={developerSurfaces:'hidden'};"
               "const nav=R.shellNavigation(reg,hidden);"
               "let refused=null;try{reg.register({id:'x',category:'connections',label:'X',save:'self',surface:'admin',mount:m})}catch(e){refused=e.code}"
               "return {cats:nav.categories.map(c=>[c.id,c.label,c.items.map(i=>i.id)]),all:R.shellNavigation(reg).categories.length,"
               "shown:['prompts','barehands','shortcuts','advanced_diagnostics','agents_models','voice_audio','nope'].map(t=>R.targetShown(t,reg,hidden)),"
               "visible:R.targetShown('prompts',reg,{developerSurfaces:'visible'}),"
               "cycle:[R.cycleCategory('connections',1,hidden),R.cycleCategory('voice_audio',-1,hidden),R.cycleCategory('connections',1)],"
               "refused}")
    # V1.2 Slice 06 : vocabulaire sans jargon et l'essentiel d'abord (`product.order`, docs/settings/novice-inventory.md).
    assert out["cats"] == [["voice_audio", "Personnalisation", []], ["connections", "Connexions", ["providers"]],
                           ["memory_knowledge", "Mémoire", []],
                           ["interface_interactions", "Raccourcis clavier", ["shortcuts"]]]
    assert out["all"] == 6
    assert out["shown"] == [False, False, True, False, False, True, False]
    assert out["visible"] is True
    assert out["cycle"] == ["memory_knowledge", "interface_interactions", "advanced_diagnostics"]
    assert out["refused"] == "settings_section_invalid"


def test_support_mode_reopens_only_the_support_categories_in_a_hiding_edition():
    """V1.2 Slice 06 : le mode support rouvre Architecture & Agents et Avancé & Diagnostics (toutes leurs sections),
    jamais une section `developer` d'une catégorie produit ; sans édition qui cache, il ne change rien."""
    out = node("const reg=R.createRegistry();const m=()=>{};"
               "reg.register({id:'shortcuts',category:'interface_interactions',label:'Raccourcis',save:'self',mount:m});"
               "reg.register({id:'barehands',category:'interface_interactions',label:'Bare Hands',save:'self',surface:'developer',mount:m});"
               "reg.register({id:'mcp_plugins',category:'connections',label:'Plugins MCP',save:'readonly',surface:'developer',mount:m});"
               "reg.register({id:'providers',category:'connections',label:'Fournisseurs',save:'self',mount:m});"
               "reg.register({id:'prompts',category:'advanced_diagnostics',group:'prompts',label:'Prompts',save:'self',mount:m});"
               "reg.register({id:'voice_output',category:'voice_audio',label:'Voix & transcription',save:'footer',mount:m});"
               "reg.register({id:'subagents',category:'agents_models',label:'Sous-agents',save:'self',mount:m});"
               "const support={developerSurfaces:'hidden',support:true};"
               "const nav=R.shellNavigation(reg,support);"
               "return {cats:nav.categories.map(c=>[c.id,c.supportOnly,c.items.map(i=>i.id)]),"
               "shown:['prompts','subagents','barehands','mcp_plugins','voice_output','agents_models'].map(t=>R.targetShown(t,reg,support)),"
               "full:R.categoriesFor({developerSurfaces:'visible',support:true}).map(c=>[c.id,c.label,!!c.supportOnly]),"
               "same:JSON.stringify(R.categoriesFor({developerSurfaces:'visible',support:true}))===JSON.stringify(R.categoriesFor()),"
               "off:R.categoriesFor({developerSurfaces:'hidden',support:false}).map(c=>c.id),"
               "cycle:R.cycleCategory('interface_interactions',1,support)}")
    assert out["cats"] == [["voice_audio", False, ["voice_output"]], ["connections", False, ["providers"]],
                           ["memory_knowledge", False, []], ["interface_interactions", False, ["shortcuts"]],
                           ["agents_models", True, ["subagents"]], ["advanced_diagnostics", True, ["prompts"]]]
    assert out["shown"] == [True, True, False, False, True, True]
    assert out["same"] is True, "full edition: support mode changes nothing"
    assert [c[0] for c in out["full"]] == ["voice_audio", "agents_models", "memory_knowledge", "interface_interactions",
                                            "connections", "advanced_diagnostics"]
    assert out["off"] == ["voice_audio", "connections", "memory_knowledge", "interface_interactions"]
    assert out["cycle"] == "agents_models"


def test_the_rail_home_and_plain_cards():
    p1 = "pst_" + "1" * 32
    out = node(f"const row={{presentation_id:'{p1}',title:'Bilan',engine:'remotion',type:{{engine:'remotion'}},variant_count:2,work:{{state:'done'}}}};"
               "const slide={...row,engine:'slidecar',type:{engine:'slidecar'}};"
               "const empty=P.modelOf([]);"
               "return {home:[P.shouldShow(empty,{pref:'auto',boardKind:'presentation',home:true}),P.shouldShow(empty,{pref:'auto',boardKind:'assistant',home:true}),"
               "P.shouldShow(empty,{pref:'hidden',boardKind:'presentation',home:true}),P.shouldShow(empty,{pref:'auto',boardKind:'presentation'})],"
               "plain:[P.cardOf(row,0,{plain:true}).type.label,P.cardOf(row,0).type.label,P.cardOf(slide,0,{plain:true}).type.label],"
               "menu:[P.menuModel(row,{developer:false}).map(i=>i.act||i).includes('studio'),P.menuModel(row,{}).map(i=>i.act||i).includes('studio')],"
               "journey:P.JOURNEY.map(s=>[s.step,s.action]),route:P.CREATE_ROUTE}")
    assert out["home"] == [True, False, False, False]
    assert out["plain"] == ["Présentation", "Présentation · Remotion", "Présentation · Slidecar"]
    assert out["menu"] == [False, True]
    assert out["journey"] == [["sources", "dossier"], ["create", "create"], ["scenes", "chat"], ["review", None]]
    assert out["route"] == "/api/presentation-studio/presentations"


def test_the_rail_creation_reads_every_engine_code_and_a_timeout_is_an_unknown_outcome():
    """M3 (QA S08) : les codes de création du rail sont ceux de la table du moteur ; `core_timeout` (504 du relais) et
    `timeout` laissent l'issue inconnue, jamais « Création impossible »."""
    engine = json.dumps(str(RUNTIME / "control_center_presentation_studio_engine.js"))
    out = node(f"const G=require({engine});"
               "const engineOnly=['presentation_studio_engine_selection_refused','presentation_studio_unknown_presentation'];"
               "return {missing:Object.keys(G.ERRORS).filter(c=>!engineOnly.includes(c)&&!(c in P.CREATE_ERRORS)),"
               "unknown:P.CREATE_UNKNOWN_OUTCOME,core_timeout:P.CREATE_ERRORS.core_timeout,"
               "cause:[P.editionCause({code:'timeout'}),P.editionCause({code:'core_unreachable'}),P.editionCause({code:'x',message:'boom'}),P.editionCause(null)]}")
    assert out["missing"] == []
    assert out["unknown"] == ["core_timeout", "timeout"]
    assert "issue est inconnue" in out["core_timeout"] and "impossible" not in out["core_timeout"]
    assert [c["code"] for c in out["cause"]] == ["timeout", "core_unreachable", "x", "network"]
    assert out["cause"][2]["text"] == "boom"


def test_the_store_tells_the_edition_marked_on_the_page():
    out = node("const mk=v=>({documentElement:{getAttribute:k=>k==='data-product-edition'?v:null,setAttribute(){}}});"
               "const c={info(){},warn(){},error(){}};"
               "return ['presentation','full','unreadable','__JARVIS_PRODUCT_EDITION__',null].map(v=>E.createStore({document:mk(v),console:c}).state().pageEdition)")
    assert out == ["presentation", "full", None, None, None]
